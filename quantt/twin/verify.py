"""The twin's VERIFY (17:45 ET, any close): book the day's IBKR executions, score them, set them beside Alpaca's.

SAME DAY ONLY. `reqExecutions` returns the current day's executions only [V, October §2.13], so
verify must run on the session date; a later date is refused, naming why, and that session cannot
be booked until a person rebuilds it (from IBKR's Flex statement; not built). The archived capture
lost 2026-07-31's 302 executions exactly that way.

WHAT IS BOOKED IS WHAT WAS SENT. The slugs, their targets and the orders come from the session's
STARTED record, never from a plan read again. Every execution on the account must belong to an
order the twin's own log says it placed (by permId, else client id and order id); one that does
not is a FOREIGN execution and the day FAILs unbooked. Then `quantt/sleeves/ledger.apply` books the
fills to the slugs, a symbol crossed completely inside the account books at the official close,
and the new ledger must sum to IBKR's positions on every symbol (contract §2 line 4) or nothing is
written.

THE SCORE (contract §4.6, §2 line 3; B6). Every fill is scored against the primary exchange's
official close (condition M, `quantt.session.verify.fetch_prints`), signed so + is worse
(`quantt.session.score.fill_vs_auction_bp`), notional-weighted per book per session. Crossed
shares are booked AT that close, so they are counted apart and never enter the twin's figure
(contract §8 N5: they cannot flatter the twin). The Alpaca books' own fills for the same session
(core and C4 from reconcile.json, events from verify.json) are scored against the SAME prints, so
both columns are on one basis; the events book's Alpaca fills had no fill-vs-close score before.
A symbol with no print is unscored and named, never priced from a bar. All figures are paper
fills: neither broker runs the auction (contract §3), and none of this is evidence about auction
impact.

NET LIQUIDATION is IBKR's own record and is read every day. The residual against the ledger is
REPORT ONLY (ops/twin/ibkr_twin.json `nlv_report_only`): measured from the first session at which
`legacy` holds nothing (its shares were seeded with no cost), in USD when the base is USD.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path

from quantt.session import gate as gt
from quantt.session import records as rec
from quantt.session.score import fill_vs_auction_bp
from quantt.sleeves import ledger, net
from quantt.twin import books, run, status
from quantt.twin.books import LEGACY, TwinRefused, slug_book

COMPARE_FILE = "compare.csv"
COMPARE_COLUMNS = ("date", "book", "twin_traded", "alpaca_traded", "twin_orders", "twin_full",
                   "twin_bp", "twin_scored_usd", "twin_crossed_shares", "twin_unscored",
                   "alpaca_orders", "alpaca_full", "alpaca_bp", "alpaca_scored_usd", "alpaca_unscored",
                   "residual_shares", "residual_usd", "refused_shorts", "reconciled", "double_send",
                   "verdict", "basis")
BASIS = ("paper fills vs the primary exchange's official close (condition M), notional-weighted, "
         "+ = worse; crossed shares excluded from twin_bp; both brokers simulate, neither runs the auction")
NLV_BASELINE = "nlv_baseline.json"


def _f(x, nd=2):
    return "" if x is None else f"{x:.{nd}f}"


def _wavg(rows):
    w = sum(n for n, _ in rows)
    return None if w <= 0 else sum(n * b for n, b in rows) / w


def alpaca_side(name: str, book_state: Path, F: dt.date) -> dict:
    """The Alpaca book's own record of F: its orders and its raw FILL rows. Core and C4 write
    reconcile.json; events writes verify.json. Missing = UNMEASURED, by name."""
    from quantt.session.verify import parse_fill
    p = book_state / F.isoformat() / ("verify.json" if name == "events" else "reconcile.json")
    if not p.exists():
        return {"unmeasured": f"no {p}"}
    d = json.loads(p.read_text())
    orders = d.get("orders") or []
    full = sum(1 for o in orders if o.get("qty") and o.get("filled_qty") is not None
               and int(float(o["filled_qty"])) == int(o["qty"]))
    return {"orders": len(orders), "full": full, "fills": [parse_fill(a) for a in d.get("fills") or []]}


def score_alpaca(fills, prices: dict) -> dict:
    by = {}
    for f in fills:
        q, usd = by.get((f.symbol, f.side), (0, 0.0))
        by[(f.symbol, f.side)] = (q + f.qty, usd + f.qty * f.price)
    rows, unscored = [], []
    for (sym, side), (q, usd) in sorted(by.items()):
        a = prices.get(sym)
        if a is None:
            unscored.append(f"{sym} {side}")
            continue
        rows.append((q * a, fill_vs_auction_bp(side, usd / q, a)))
    return {"bp": _wavg(rows), "scored_usd": sum(n for n, _ in rows), "unscored": unscored}


def market_part(b: dict, account_fill: int, opposite: int) -> float:
    """The shares of booking `b` that reached the market. `ledger.apply` prices every share booked in
    a symbol with a fill at the fills' average, crossed ones included, so the crossing is undone
    here for scoring (contract §8 N5): a booking AGAINST the account's net fill was met inside the
    account in full; a booking WITH it took the fill and the opposite side's shares in proportion,
    so its market part is |b| x |fill| / (|fill| + opposite). A symbol with no fill was all crossed."""
    if b["kind"] == "cross" or account_fill == 0 or (b["shares"] > 0) != (account_fill > 0):
        return 0.0
    return abs(b["shares"]) * abs(account_fill) / (abs(account_fill) + opposite)


def score_twin(name: str, slugs: list, before: dict, bookings: list, prices: dict, rejected: list,
               orders: list, fills_by_symbol: dict | None = None) -> dict:
    """One book's twin figures from the day's bookings (`ledger.apply`). Only the shares that reached
    the market are scored (`market_part`); the rest are counted as crossed."""
    fills_by_symbol = fills_by_symbol or {}
    mine = [s for s in slugs if slug_book(s["slug"]) == name]
    names = {s["slug"] for s in mine}
    wanted: dict = {}
    for s in mine:
        held = (before["sleeves"].get(s["slug"]) or {}).get("shares", {})
        for sym in set(s["targets"]) | set(held):
            d = s["targets"].get(sym, 0) - held.get(sym, 0)
            if d:
                wanted[sym] = wanted.get(sym, 0) + d
    opposite: dict = {}
    for b in bookings:
        f = fills_by_symbol.get(b["symbol"], (0, None))[0]
        if f and (b["shares"] > 0) != (f > 0):
            opposite[b["symbol"]] = opposite.get(b["symbol"], 0) + abs(b["shares"])
    booked: dict = {}
    fills, crossed, unscored = [], 0.0, []
    for b in bookings:
        if b["slug"] not in names:
            continue
        booked[b["symbol"]] = booked.get(b["symbol"], 0) + b["shares"]
        mk = market_part(b, fills_by_symbol.get(b["symbol"], (0, None))[0], opposite.get(b["symbol"], 0))
        crossed += abs(b["shares"]) - mk
        if mk <= 0:
            continue
        a = prices.get(b["symbol"])
        side = "buy" if b["shares"] > 0 else "sell"
        if a is None:
            unscored.append(f"{b['symbol']} {side}")
            continue
        fills.append((mk * a, fill_vs_auction_bp(side, b["price"], a)))
    crossed = round(crossed, 6)
    res_sh = sum(abs(wanted[s] - booked.get(s, 0)) for s in wanted)
    res_usd = sum(abs(wanted[s] - booked.get(s, 0)) * prices[s] for s in wanted if s in prices)
    by_ref = {o["symbol"]: o for o in orders}
    refused = sorted(r["symbol"] for r in rejected if r.get("opens_short") and wanted.get(r["symbol"], 0) < 0
                     and r["symbol"] in by_ref)
    return {"orders": len(wanted), "full": sum(1 for s in wanted if booked.get(s, 0) == wanted[s]),
            "bp": _wavg(fills), "scored_usd": sum(n for n, _ in fills), "crossed_shares": crossed,
            "unscored": unscored, "residual_shares": res_sh, "residual_usd": res_usd,
            "refused_shorts": refused}


def slug_pnl(led: dict, marks: dict) -> dict:
    """{slug: cash + shares x official close, or None where a held symbol has no close}."""
    out = {}
    for slug, r in sorted(led["sleeves"].items()):
        v = r["cash"]
        for sym, q in r["shares"].items():
            m = marks.get(sym)
            if m is None:
                v = None
                break
            v += q * m
        out[slug] = v
    return out


def _append_compare(path: Path, rows: list) -> None:
    new = not path.exists() or path.stat().st_size == 0
    if not new:
        with path.open(newline="") as fh:
            head = next(csv.reader(fh), None)
        if tuple(head or ()) != COMPARE_COLUMNS:
            raise TwinRefused(f"{path} header {head} is not this runner's")
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COMPARE_COLUMNS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def _log(state: Path, F, ok: bool, reason: str) -> None:
    with (state / "verify.log").open("a") as fh:
        fh.write(f"{F} {'PASS' if ok else 'FAIL'} twin {reason}\n")


def verify(deps, *, date: dt.date | None = None) -> int:
    return run._guarded(lambda: _verify(deps, date), deps, "verify")


def _verify(deps, date) -> int:
    from quantt.session.verify import _session_window
    out = deps.out
    state = run.setup(deps)
    states = books.book_states(deps.env)
    clk = deps.market.clock()
    now = clk["timestamp"].astimezone(gt.ET)
    F = date or now.date()
    if F != now.date():
        raise TwinRefused(f"verify for {F} must run ON {F}: IBKR returns the current day's executions only, so "
                          "that session cannot be booked from the API (rebuild it from the Flex statement)")
    row, _asof = run.session_for(deps.market, F)
    day = state / F.isoformat()
    if row is None:
        if (day / "STARTED").exists():
            raise TwinRefused(f"{F} is not a trading day, yet {day / 'STARTED'} exists")
        print(f"{F} PASS twin not a trading day; nothing to verify", file=out)
        return 0
    why = _session_window(clk, F)
    if why:
        raise TwinRefused(f"not verifiable now: {why}")
    led_path = state / "ledger.json"
    vpath = day / "verify.json"
    if vpath.exists() and json.loads(vpath.read_text()).get("ledger_applied"):
        v = json.loads(vpath.read_text())
        print(f"{F} {'PASS' if v['ok'] else 'FAIL'} twin already verified; nothing changed ({v['reason']})", file=out)
        return 0 if v["ok"] else 1
    before, _ep = run.read_ledger(state)
    if before["session"] is not None and before["session"] >= F.isoformat():
        raise TwinRefused(f"the ledger is booked to {before['session']}; not booking {F} again")
    started = (day / "STARTED").exists()
    send_d = json.loads((day / "send.json").read_text()) if (day / "send.json").exists() else None

    # the Alpaca side, whatever the twin did (contract §2 line 1 counts a session only one side traded)
    alp = {n: alpaca_side(n, states[n], F) for n in books.BOOK_NAMES}
    at = deps.utcnow().isoformat()

    if not started:
        gates = {r["gate"] for r in (send_d or {}).get("refusals") or []}
        if send_d is None:
            ok, reason = False, "MISSED: no send ran for this session"
        elif send_d.get("exit", {}).get("name") == "NOTHING_TO_SEND":
            ok, reason = True, "nothing to send"
        elif gates and gates <= run.DELIBERATE:
            ok, reason = True, f"not sent by choice ({', '.join(sorted(gates))})"
        else:
            ok, reason = False, (f"MISSED: the send ended {send_d.get('exit', {}).get('name')}: "
                                 + "; ".join(r["detail"] for r in send_d.get("refusals") or [])[:600])
        syms = sorted({f.symbol for a in alp.values() for f in a.get("fills", [])})
        prints = deps.market.official_closes(syms, F) if syms else None
        prices = dict(prints.prices) if prints else {}
        rows = []
        for n in books.BOOK_NAMES:
            a = alp[n]
            sa = score_alpaca(a["fills"], prices) if "fills" in a else None
            rows.append(_row(F, n, None, a, sa, reconciled="", double="", verdict="PASS" if ok else "FAIL"))
        rec.write_json_atomic(vpath, {"session_date": F, "ok": ok, "reason": reason, "started": False,
                                      "ledger_applied": False, "read_at": now, "alpaca": _alp_rec(alp, prices)})
        _append_compare(state / COMPARE_FILE, rows)
        _log(state, F, ok, reason)
        status.update(state, "last_verify", {"session_date": F.isoformat(), "ok": ok, "reason": reason[:300]}, at)
        _tally(state, at)
        print(f"{F} {'PASS' if ok else 'FAIL'} twin {reason}", file=out)
        return 0 if ok else 1

    st = json.loads((day / "STARTED").read_text())
    log_rows = rec.read_jsonl(day / "orders.jsonl")
    intents = [r for r in log_rows if r.get("event") == "intent"]
    placed = [r for r in log_rows if r.get("event") == "placed"]
    by_perm = {r["perm_id"]: r for r in placed if r.get("perm_id")}
    by_cid = {(r.get("client_id"), r.get("order_id")): r for r in placed}
    orders = st["orders"]
    order_by_ref = {o["order_ref"]: o for o in orders}
    problems, fails, notes = [], [], []
    double = len(intents) != len({r["order_ref"] for r in intents})
    if double:
        problems.append("an order ref has more than one intent line: a second set may have gone (rule 2)")
    rejected = (send_d or {}).get("rejected") or []
    if send_d is None:
        fails.append("STARTED exists and send.json does not: the send did not finish")
    elif send_d.get("stopped"):
        fails.append(f"the send stopped: {send_d['stopped']}")

    client = deps.ibkr("read")
    from quantt.broker.ibkr import NotConnected, WrongAccount
    try:
        client.connect()
    except (NotConnected, WrongAccount) as e:
        run._gateway_down(deps, state, e)
        raise TwinRefused(f"the Gateway is not reachable at verify ({e}); today's executions cannot be read "
                          "and IBKR keeps them for the day only: re-run verify before midnight ET") from None
    try:
        execs = client.executions_today()
        pos = client.positions()
        oo = client.open_orders()
        summ = client.account_summary()
    finally:
        client.disconnect()
    status.update(state, "gateway", {"logged_in": True, "why": "verify connected"}, at)
    if oo:
        problems.append(f"{len(oo)} order(s) still open at IBKR after the close")

    # every execution is one of ours
    filled_by_ref, agg, comm, comm_missing = {}, {}, 0.0, 0
    for e in execs:
        r = by_perm.get(e["perm_id"]) if e["perm_id"] else None
        r = r or by_cid.get((e["client_id"], e["order_id"]))
        if r is None:
            problems.append(f"execution {e['side']} {e['qty']} {e['symbol']} is not an order the twin placed today "
                            "(a FOREIGN execution)")
            continue
        o = order_by_ref.get(r["order_ref"])
        if o is None or o["symbol"] != e["symbol"] or o["side"] != e["side"]:
            problems.append(f"execution {e['side']} {e['symbol']} does not match the twin's order {r['order_ref']}")
            continue
        filled_by_ref[r["order_ref"]] = filled_by_ref.get(r["order_ref"], 0) + e["qty"]
        q, usd = agg.get(e["symbol"], (0, 0.0))
        agg[e["symbol"]] = (q + (e["qty"] if e["side"] == "buy" else -e["qty"]), usd + e["qty"] * e["price"])
        if e["commission"] is None:
            comm_missing += 1
        else:
            comm += e["commission"]
    for ref, q in filled_by_ref.items():
        if q > order_by_ref[ref]["qty"]:
            problems.append(f"{ref}: executions sum to {q}, above the order's {order_by_ref[ref]['qty']}")
    fills = {s: (q, usd / abs(q)) for s, (q, usd) in agg.items() if q}
    tot = ledger.totals(before)
    for s in sorted(set(tot) | set(pos) | set(fills)):
        want = tot.get(s, 0) + fills.get(s, (0, None))[0]
        if pos.get(s, 0) != want:
            problems.append(f"{s}: IBKR holds {pos.get(s, 0):+d}; the ledger's {tot.get(s, 0):+d} and today's "
                            f"executions {fills.get(s, (0, None))[0]:+d} give {want:+d}")

    slugs = st["slugs"]
    syms = sorted(set(tot) | {s for p in slugs for s in p["targets"]} | set(fills)
                  | {f.symbol for a in alp.values() for f in a.get("fills", [])})
    prints = deps.market.official_closes(syms, F) if syms else None
    prices = dict(prints.prices) if prints else {}
    gaps = dict(prints.gaps) if prints else {}

    def fail_unbooked(msg):
        rec.write_json_atomic(vpath, {"session_date": F, "ok": False, "reason": msg, "started": True,
                                      "ledger_applied": False, "problems": problems, "read_at": now})
        _log(state, F, False, msg)
        status.update(state, "last_verify", {"session_date": F.isoformat(), "ok": False, "reason": msg[:300]}, at)
        print(f"{F} FAIL twin {msg}", file=out)
        return 1

    if problems:
        return fail_unbooked("; ".join(problems) + " | the ledger was NOT booked; repair it before the next send")
    plans = [net.SleevePlan(p["slug"], p["action"], p["why"], dict(p["targets"]), 0, tuple(p.get("dropped") or ()))
             for p in slugs]
    try:
        new, bookings = ledger.apply(before, plans, fills, prices, F.isoformat())
        ledger.check_against_broker(new, pos)
    except ledger.LedgerError as e:
        problems.append(str(e))
        return fail_unbooked(f"{e} | the ledger was NOT booked")

    scores = {n: score_twin(n, slugs, before, bookings, prices, rejected, orders, fills) for n in books.BOOK_NAMES}
    pnl = slug_pnl(new, prices)
    prev = _prev_pnl(state, F)
    nlv = _nlv(state, summ, new, pnl, comm, comm_missing, F)
    rows = []
    for n in books.BOOK_NAMES:
        a = alp[n]
        sa = score_alpaca(a["fills"], prices) if "fills" in a else None
        rows.append(_row(F, n, scores[n], a, sa, reconciled="True", double=str(double), verdict="PASS" if not fails else "FAIL"))
    head = (f"sent {send_d.get('sent') if send_d else '?'} MOC order(s), {len(fills)} symbol(s) filled, "
            f"{len(bookings)} booking(s); ledger booked to {F}; reconciled with IBKR on every symbol")
    for n in books.BOOK_NAMES:
        s = scores[n]
        head += (f"; {n} {s['full']}/{s['orders']} full, fill vs close {_f(s['bp'], 1) or 'none'}bp, "
                 f"{s['crossed_shares']:.0f} share(s) crossed inside the account")
    reason = ("; ".join(fails) + " | " + head) if fails else head
    rec.write_json_atomic(day / "ledger_before.json", before)
    rec.write_json_atomic(led_path, new)
    rec.write_json_atomic(vpath, {
        "session_date": F, "ok": not fails, "reason": reason, "started": True, "ledger_applied": True,
        "read_at": now, "fills_by_symbol": {s: {"shares": q, "avg_price": p} for s, (q, p) in fills.items()},
        "bookings": bookings, "positions_after": pos, "official_closes": prices, "official_close_gaps": gaps,
        "scores": scores, "slug_pnl": pnl,
        "slug_day_change": {s: (None if v is None or prev.get(s) is None else v - prev[s]) for s, v in pnl.items()},
        "commissions": None if comm_missing else comm, "commission_reports_missing": comm_missing,
        "net_liquidation": nlv, "alpaca": _alp_rec(alp, prices), "fails": fails, "notes": notes})
    _append_compare(state / COMPARE_FILE, rows)
    _log(state, F, not fails, reason)
    status.update(state, "last_verify", {"session_date": F.isoformat(), "ok": not fails, "reason": reason[:300]}, at)
    _tally(state, at)
    print(f"{F} {'PASS' if not fails else 'FAIL'} twin {reason}", file=out)
    return 0 if not fails else 1


def _alp_rec(alp: dict, prices: dict) -> dict:
    out = {}
    for n, a in alp.items():
        if "unmeasured" in a:
            out[n] = {"unmeasured": a["unmeasured"]}
        else:
            out[n] = {"orders": a["orders"], "full": a["full"], **score_alpaca(a["fills"], prices)}
    return out


def _row(F, n, s, a, sa, *, reconciled, double, verdict) -> dict:
    return {"date": F.isoformat(), "book": n, "twin_traded": str(s is not None and s["orders"] > 0),
            "alpaca_traded": "" if "unmeasured" in a else str(a["orders"] > 0),
            "twin_orders": "" if s is None else s["orders"], "twin_full": "" if s is None else s["full"],
            "twin_bp": "" if s is None else _f(s["bp"]), "twin_scored_usd": "" if s is None else _f(s["scored_usd"]),
            "twin_crossed_shares": "" if s is None else _f(s["crossed_shares"], 0),
            "twin_unscored": "" if s is None else len(s["unscored"]),
            "alpaca_orders": a.get("orders", ""), "alpaca_full": a.get("full", ""),
            "alpaca_bp": "" if sa is None else _f(sa["bp"]), "alpaca_scored_usd": "" if sa is None else _f(sa["scored_usd"]),
            "alpaca_unscored": "" if sa is None else len(sa["unscored"]),
            "residual_shares": "" if s is None else s["residual_shares"],
            "residual_usd": "" if s is None else _f(s["residual_usd"]),
            "refused_shorts": "" if s is None else len(s["refused_shorts"]),
            "reconciled": reconciled, "double_send": double, "verdict": verdict, "basis": BASIS}


def _prev_pnl(state: Path, F: dt.date) -> dict:
    for d in sorted((x for x in state.iterdir() if x.is_dir() and x.name < F.isoformat()), reverse=True):
        v = d / "verify.json"
        if v.exists():
            vd = json.loads(v.read_text())
            if vd.get("ledger_applied"):
                return vd.get("slug_pnl") or {}
    return {}


def _nlv(state: Path, summ: dict, new: dict, pnl: dict, comm: float, comm_missing: int, F) -> dict:
    """IBKR's net liquidation, and the REPORT-ONLY residual against the ledger (module docstring)."""
    out = {"net_liquidation": summ["net_liquidation"], "base_currency": summ["base_currency"], "residual_usd": None}
    if summ["base_currency"] != "USD":
        out["why"] = f"base currency {summ['base_currency']}: the ledger is in USD; residual UNMEASURED"
        return out
    if any((new["sleeves"].get(LEGACY) or {}).get("shares", {}).values()):
        out["why"] = "legacy still holds shares seeded with no cost; residual measured once it is flat"
        return out
    if any(v is None for v in pnl.values()) or comm_missing:
        out["why"] = "a held symbol has no official close, or a commission report is missing; residual UNMEASURED"
        return out
    total = sum(pnl.values())
    commsum = comm + sum(json.loads((d / "verify.json").read_text()).get("commissions") or 0.0
                         for d in state.iterdir() if d.is_dir() and d.name < F.isoformat() and (d / "verify.json").exists())
    b = state / NLV_BASELINE
    if not b.exists():
        rec.write_json_atomic(b, {"session_date": F, "net_liquidation": summ["net_liquidation"],
                                  "ledger_pnl": total, "commissions": commsum})
        out["why"] = "baseline recorded this session; the residual starts next session"
        return out
    base = json.loads(b.read_text())
    out["residual_usd"] = ((summ["net_liquidation"] - base["net_liquidation"])
                           - ((total - base["ledger_pnl"]) - (commsum - base["commissions"])))
    out["why"] = "report only (ops/twin/ibkr_twin.json nlv_report_only)"
    return out


def _tally(state: Path, at: str) -> None:
    from quantt.twin import compare
    status.update(state, "tally", compare.tally(compare.read_rows(state)), at)
