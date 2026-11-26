"""The twin's VERIFY (17:45 ET, any close): book the day's IBKR executions, score them, set them beside Alpaca's.

THE READ IS SAVED AT ONCE (review of the build, finding 1). `reqExecutions` returns the current
day's executions only [V, October §2.13]; the archived capture lost 2026-07-31's 302 executions
that way. So the first verify slot that reaches the Gateway writes the raw read (executions with
commission reports, positions, open orders, account summary; no credential) to
`<day>/ibkr_read.json` before it does anything else, and the slots after it (17:45, 18:30, 20:30,
23:00) and any later run book from that file when the Gateway is down. The official closes are
saved the same way (`prints.json`). With no read saved, a session that STARTED cannot be booked
on a later date (Flex statement; not built). A crossed share with no official close waits for the
next slot; after 23:00 the session is UNBOOKED (`UNBOOKED.json`) for a person, never priced on a
guess, and the send refuses until it is repaired.

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
    """`verify --date D` verifies D. With no date (the timer) it first books every EARLIER session
    that STARTED and is neither booked nor UNBOOKED, oldest first, each from its own saved read
    (re-review 1: a reboot that missed a day's later slots); then today's, where a session that has
    not closed yet is a no-op, not a refusal (the 07:00 slot exists for the catch-up)."""
    if date is not None:
        return run._guarded(lambda: _verify(deps, date), deps, "verify")
    return run._guarded(lambda: _scheduled(deps), deps, "verify")


def _scheduled(deps) -> int:
    state = run.setup(deps)
    now = deps.market.clock()["timestamp"].astimezone(gt.ET)
    rc = 0
    for d in sorted(x for x in state.iterdir() if x.is_dir() and x.name[:2] == "20" and x.name < now.date().isoformat()):
        v = d / "verify.json"
        done = v.exists() and json.loads(v.read_text()).get("ledger_applied")
        if (d / "STARTED").exists() and not done and not (d / UNBOOKED_FILE).exists():
            rc = max(rc, _verify(deps, dt.date.fromisoformat(d.name)))
    return max(rc, _verify(deps, None, scheduled=True))


LAST_SLOT = dt.time(23, 0)      # the last verify slot of the day (install_twin_vm.sh: 17:45 18:30 20:30 23:00)
READ_FILE = "ibkr_read.json"     # the day's IBKR read, saved at once (review finding 1)
PRINTS_FILE = "prints.json"      # the day's official closes, merged across runs
UNBOOKED_FILE = "UNBOOKED.json"  # a session the twin could not book: a person repairs it


def _save_read(day: Path, read: dict) -> bool:
    """The raw IBKR read, written ONCE, by an exclusive create (re-review 1: a saved read is never
    overwritten), mode 0600 (mkstemp's, kept by the link). It holds executions, positions, open
    orders and the account summary, and no credential or account id. False if one already exists."""
    return rec.create_exclusive(day / READ_FILE, read)


def _read_ibkr(deps, state: Path, day: Path, F: dt.date, at: str, today: dt.date) -> tuple:
    """(read, source), by these rules (re-review 1):
      * a read saved for F is THE read: it is used, and IBKR is not asked again;
      * for F before today (ET) IBKR is never read: today's executions are not F's. With no saved
        read the answer is (None, why) and the caller leaves the session UNBOOKED;
      * on F itself, with no saved read, IBKR is read once and the read saved at once."""
    from quantt.broker.ibkr import IBKRError, NotConnected, WrongAccount
    if (day / READ_FILE).exists():
        return json.loads((day / READ_FILE).read_text()), "saved (the read taken on the session day)"
    if F < today:
        return None, (f"no IBKR read was saved on {F}, and IBKR now returns {today}'s executions, not {F}'s")
    client = deps.ibkr("read")
    try:
        client.connect()
    except (NotConnected, WrongAccount) as e:
        run._gateway_down(deps, state, e)
        why = f"the Gateway is not reachable at verify ({e})"
    else:
        try:
            read = {"read_at": at, "executions": client.executions_today(since=run.midnight_et(F)),
                    "positions": client.positions(), "open_orders": client.open_orders(),
                    "account": client.account_summary()}
        except IBKRError as e:
            why = f"the IBKR read failed ({type(e).__name__}: {e})"
        else:
            status.update(state, "gateway", {"logged_in": True, "why": "verify connected"}, at)
            if not _save_read(day, read):          # another run saved one meanwhile: that one stands
                return json.loads((day / READ_FILE).read_text()), "saved (by a run that finished first)"
            return read, "fresh"
        finally:
            client.disconnect()
    return None, why


def _prints(deps, day: Path, syms: list, F: dt.date) -> tuple:
    """(prices, gaps): fetched now, merged with what an earlier run saved (Alpaca failing now does
    not lose a print already read), saved again. A gap is a symbol neither run could price."""
    saved = json.loads((day / PRINTS_FILE).read_text()) if (day / PRINTS_FILE).exists() else {"prices": {}, "gaps": {}}
    prices, gaps = dict(saved.get("prices") or {}), {}
    if syms:
        got = deps.market.official_closes(syms, F)
        prices.update(got.prices)
        gaps = {s: g for s, g in got.gaps.items() if s not in prices}
    rec.write_json_atomic(day / PRINTS_FILE, {"prices": prices, "gaps": gaps})
    return prices, gaps


def _finish_unrecorded(out, F, msg, code=1) -> int:
    print(f"{F} {msg}", file=out)
    return code


def _verify(deps, date, scheduled: bool = False) -> int:
    """The day's verify (module docstring). Idempotent: a session already booked, or a no-send
    session already recorded, is reported and left alone. Persistent: the IBKR read and the prints
    are saved as soon as they are taken, so a later slot books from them when the Gateway or
    Alpaca fails. A crossed share with no official close yet waits for the next slot (PENDING);
    after the last slot it is UNBOOKED for a person, never priced on a guess."""
    from quantt.session.verify import _session_window
    from quantt.sleeves.run import ledger_sha
    out = deps.out
    state = run.setup(deps)
    states = books.book_states(deps.env)
    clk = deps.market.clock()
    now = clk["timestamp"].astimezone(gt.ET)
    F = date or now.date()
    day = state / F.isoformat()
    if F > now.date():
        raise TwinRefused(f"{F} is after today's date {now.date()}")
    row, _asof = run.session_for(deps.market, F)
    if row is None:
        if (day / "STARTED").exists():
            raise TwinRefused(f"{F} is not a trading day, yet {day / 'STARTED'} exists")
        print(f"{F} PASS twin not a trading day; nothing to verify", file=out)
        return 0
    if F == now.date():
        why = _session_window(clk, F)
        if why:
            if scheduled:
                print(f"{F} twin verify: not yet ({why}); nothing to do", file=out)
                return 0
            raise TwinRefused(f"not verifiable now: {why}")
    last = F < now.date() or now.time() >= LAST_SLOT
    led_path = state / "ledger.json"
    vpath = day / "verify.json"
    if (day / UNBOOKED_FILE).exists():
        u = json.loads((day / UNBOOKED_FILE).read_text())
        return _finish_unrecorded(out, F, f"FAIL twin UNBOOKED (a person repairs it): {u.get('reason')}")
    if vpath.exists():
        v = json.loads(vpath.read_text())
        if v.get("ledger_applied") or v.get("recorded"):
            print(f"{F} {'PASS' if v['ok'] else 'FAIL'} twin already verified; nothing changed ({v['reason']})", file=out)
            return 0 if v["ok"] else 1
    before, _ep = run.read_ledger(state)
    if before["session"] is not None and before["session"] >= F.isoformat():
        raise TwinRefused(f"the ledger is booked to {before['session']}; not booking {F} again")
    day.mkdir(exist_ok=True)
    started = (day / "STARTED").exists()
    # Release check 2: with STARTED, the record of the run that wrote it (send.json, written once); a
    # later backup's own record never stands in for it. Without, the newest run's record.
    send_d = run.started_send_record(day) if started else run.latest_send_record(day)
    alp = {n: alpaca_side(n, states[n], F) for n in books.BOOK_NAMES}
    at = deps.utcnow().isoformat()
    held_syms = sorted(ledger.totals(before))

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
        syms = sorted(set(held_syms) | {f.symbol for a in alp.values() for f in a.get("fills", [])})
        prices, _gaps = _prints(deps, day, syms, F)
        pnl = slug_pnl(before, prices)
        prev = _prev_pnl(state, F)
        rows = []
        for n in books.BOOK_NAMES:
            a = alp[n]
            sa = score_alpaca(a["fills"], prices) if "fills" in a else None
            rows.append(_row(F, n, None, a, sa, reconciled="", double="", verdict="PASS" if ok else "FAIL"))
        rec.write_json_atomic(vpath, {"session_date": F, "ok": ok, "reason": reason, "started": False,
                                      "ledger_applied": False, "recorded": True, "read_at": now,
                                      "slug_pnl": pnl, "slug_day_change": _day_change(pnl, prev),
                                      "alpaca": _alp_rec(alp, prices)})
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
    if st.get("ledger_sha") != ledger_sha(before):
        problems.append("the ledger is not the one this session's STARTED was built on (its sha differs): it "
                        "changed after the send, so nothing is booked")
    double = len(intents) != len({r["order_ref"] for r in intents})
    if double:
        problems.append("an order ref has more than one intent line: a second set may have gone (rule 2)")
    rejected = (send_d or {}).get("rejected") or []
    if send_d is None:
        fails.append("STARTED exists and send.json does not: the send did not finish")
    elif send_d.get("stopped"):
        fails.append(f"the send stopped: {send_d['stopped']} ({send_d.get('sent')} sent, "
                     f"{len(rejected)} rejected, of {len(send_d.get('orders') or [])} order(s))")

    read, source = _read_ibkr(deps, state, day, F, at, now.date())
    if read is None:
        if last:
            return _unbooked(state, day, F, at, f"no IBKR read for {F}: {source}", [], out)
        return _finish_unrecorded(out, F, f"PENDING twin: {source}; retried at the next verify slot")
    if source != "fresh":
        notes.append(source)
    execs, pos, oo, summ = read["executions"], read["positions"], read["open_orders"], read["account"]
    if oo:
        problems.append(f"{len(oo)} order(s) still open at IBKR after the close")

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
    prices, gaps = _prints(deps, day, syms, F)

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
    plans, flip_notes = change_of_side_targets(plans, before, orders, fills)
    notes.extend(flip_notes)
    # A symbol whose shares change hands with no fill books at the official close: without that
    # close it waits for the next slot, and after the last one it is UNBOOKED, never a guess.
    need_cross = sorted(s for s in syms if s not in fills and s not in prices and any(
        p.targets.get(s, 0) != (before["sleeves"].get(p.slug) or {}).get("shares", {}).get(s, 0) for p in plans))
    if need_cross:
        if last:
            return _unbooked(state, day, F, at, f"no official close for {need_cross}, whose shares cross inside "
                             f"the account ({ {s: gaps.get(s) for s in need_cross} })", need_cross, out)
        return _finish_unrecorded(out, F, f"PENDING twin: no official close yet for crossed {need_cross}; retried "
                                  "at the next verify slot")
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
        "read_at": now, "ibkr_read": source, "fills_by_symbol": {s: {"shares": q, "avg_price": p} for s, (q, p) in fills.items()},
        "bookings": bookings, "positions_after": pos, "official_closes": prices, "official_close_gaps": gaps,
        "scores": scores, "slug_pnl": pnl, "slug_day_change": _day_change(pnl, prev),
        "commissions": None if comm_missing else comm, "commission_reports_missing": comm_missing,
        "net_liquidation": nlv, "alpaca": _alp_rec(alp, prices), "fails": fails, "notes": notes})
    _append_compare(state / COMPARE_FILE, rows)
    _log(state, F, not fails, reason)
    status.update(state, "last_verify", {"session_date": F.isoformat(), "ok": not fails, "reason": reason[:300]}, at)
    _tally(state, at)
    print(f"{F} {'PASS' if not fails else 'FAIL'} twin {reason}", file=out)
    return 0 if not fails else 1


def change_of_side_targets(plans: list, before: dict, orders: list, fills: dict) -> tuple:
    """(plans, notes): for each symbol sent as a change of side (a leg `-2` order), the slugs that
    OPEN the new side get only what actually filled beyond the closing (re-review 3), so a refused,
    skipped or unfilled opening leg never leaves a closing slug open or an opening slug short.

    For such a symbol, s = the side's sign (-1 for sells). An OPENER is a slug whose target is on
    the new side and moves that way. Its base target c is its holding if that is on the new side
    or zero, else 0 (it closes, nothing more). The openers then share, by `ledger.allocate` (the
    events book's own rule: in proportion, whole shares), the fill beyond what the base targets
    account for; with none, they stay at c. Every other slug keeps its target, and
    `ledger.apply` books the symbol's summed fill as before. Done here, in the twin: ledger.py is
    not changed. Example: legacy +200 -> 0, cef 0 -> -50; leg 1 SELL 200 fills, leg 2 is refused:
    cef's base is 0, the base targets account for -200 = the fill, so the ledger ends legacy 0,
    cef 0, and the account 0."""
    from quantt.sleeves import ledger as L
    flips = sorted({o["symbol"] for o in orders if o.get("leg") == 2})
    if not flips:
        return plans, []
    held = {p.slug: (before["sleeves"].get(p.slug) or {}).get("shares", {}) for p in plans}
    targets = {p.slug: dict(p.targets) for p in plans}
    notes = []
    for sym in flips:
        side = next(o["side"] for o in orders if o["symbol"] == sym)
        sgn = -1 if side == "sell" else 1
        openers = {}
        for slug in targets:
            t, h = targets[slug].get(sym, 0), held[slug].get(sym, 0)
            if t * sgn > 0 and (t - h) * sgn > 0:
                c = h if h * sgn >= 0 else 0
                openers[slug] = (c, t - c)
        if not openers:
            continue
        base_net = sum((openers[sl][0] if sl in openers else targets[sl].get(sym, 0)) - held[sl].get(sym, 0)
                       for sl in targets)
        filled = fills.get(sym, (0, None))[0]
        excess = (filled - base_net) * sgn
        want = {sl: o for sl, (c, o) in openers.items()}
        cap = sum(abs(o) for o in want.values())
        share = L.allocate(want, sgn * min(max(excess, 0), cap)) if excess > 0 else {sl: 0 for sl in want}
        for sl, (c, o) in openers.items():
            new = c + share.get(sl, 0)
            if new:
                targets[sl][sym] = new
            else:
                targets[sl].pop(sym, None)
        if excess < cap:
            notes.append(f"{sym}: the opening leg filled {max(excess, 0)} of {cap}; the opening slugs "
                         f"{sorted(openers)} were held to what filled")
    from quantt.sleeves import net as N
    out = [N.SleevePlan(p.slug, p.action, p.why, dict(sorted(targets[p.slug].items())), p.stale_sessions,
                        p.dropped, p.scale) for p in plans]
    return out, notes


def _day_change(pnl: dict, prev: dict) -> dict:
    return {s: (None if v is None or prev.get(s) is None else v - prev[s]) for s, v in pnl.items()}


def _unbooked(state: Path, day: Path, F, at: str, reason: str, symbols: list, out) -> int:
    """After the last slot: the session is left UNBOOKED, named, for a person. The send refuses
    every later session until it is repaired (`run.unbooked`), because the ledger would be wrong."""
    rec.write_json_atomic(day / UNBOOKED_FILE, {
        "session_date": F, "at": at, "reason": reason, "symbols": symbols,
        "repair": "book this session by hand from <day>/ibkr_read.json and the official closes, write the ledger "
                  "and verify.json (ledger_applied), then delete this file (docs/RUNBOOK.md section 9.7)"})
    _log(state, F, False, f"UNBOOKED: {reason}")
    status.update(state, "last_verify", {"session_date": F.isoformat(), "ok": False,
                                         "reason": f"UNBOOKED: {reason}"[:300]}, at)
    print(f"{F} FAIL twin UNBOOKED: {reason}", file=out)
    return 1


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
