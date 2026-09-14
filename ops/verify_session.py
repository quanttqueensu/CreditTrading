"""Did today's trades actually happen? Asked of the broker, after the close.

    python3 -m ops.verify_session --book ops/books/cef_discount_book.json \\
        --books-root ops/books/cef_live --client-id 125
    python3 -m ops.verify_session ... --no-alert --auction 2026-09-11

WHY THIS EXISTS
---------------
For six weeks every failure of this book was discovered the same way: someone
read a log the next day. 2026-09-08 through 09-13 alone produced a session
that ran 17h20m with every guard green, fills that happened and were never
recorded (the evening capture ran after IB's nightly restart), a ledger that
booked fills the broker never executed, a date guard that refused a legitimate
session, and a heartbeat reading `ok` on a day nothing traded. Each got a guard
after it was found. None was found by the system.

Every one of those guards answers a question about a CAUSE. This module
answers one question about the OUTCOME, and does not care what the cause was:

    what we transmitted for auction D   (_order_map.csv, written at placement)
    what the broker executed at D        (reqExecutions)
    what the broker now holds            (positions)
    what our ledger believes we hold     (_ibkr_shadow/<sleeve>/positions.csv)
    what is still resting                (reqAllOpenOrders)

Five records of one fact. When they agree the day worked. When they do not,
something broke -- possibly something nobody has thought of yet -- and a human
is told THE SAME DAY, with the numbers, while the broker still holds the
execution records and before the next session trades on a wrong book.

IT ALSO TELLS YOU WHEN IT WORKED, ON PURPOSE. One message per trading day,
pass or fail. Silence is not success: if the message does not arrive, the
verifier itself, the machine, the gateway or the mail path is broken, and that
absence is the alert. A monitor that only speaks on failure fails silently
exactly when it is the thing that failed.

WHAT IT WRITES, AND WHAT IT NEVER TOUCHES
----------------------------------------
Writes: a raw snapshot of every broker answer and the verdict, under
`<books-root>/_broker_archive/<D>/` (a new file per run; nothing is overwritten),
and a heartbeat under `verify_<book_id>`. The snapshot is the durable copy of
D's executions -- IB's gateway forgets them at its nightly restart.

Never touches: a ledger, the order map, `broker_fills.csv`, a halt. It connects
with `readonly=True`, so the API session itself refuses to transmit, and there
is no placeOrder / cancelOrder / reqGlobalCancel anywhere in this file.

It still opens a broker socket, so under CLAUDE.md's order-path rule a human
(or the launchd job a human loads) runs it; an agent does not.

EXIT CODES: 0 every check passed; 1 at least one FAIL; 2 could not verify
(broker unreachable, or D's executions are no longer visible and positions
alone had to carry the verdict).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops import pending_orders as po  # noqa: E402

PASS, WARN, FAIL, UNVERIFIED, INFO = "PASS", "WARN", "FAIL", "UNVERIFIED", "INFO"
_RANK = {INFO: 0, PASS: 0, WARN: 1, UNVERIFIED: 2, FAIL: 3}


class VerifyInputError(RuntimeError):
    """A record this check depends on is missing or unreadable. Raised, never
    defaulted: a verifier that fills a gap with zero reports a clean book."""


@dataclass
class Check:
    name: str
    status: str
    message: str
    rows: list = field(default_factory=list)


def _signed(action: str, qty) -> float:
    a = str(action).upper()
    if a in ("BUY", "BOT"):
        return float(qty)
    if a in ("SELL", "SLD"):
        return -float(qty)
    raise VerifyInputError(f"unrecognised side {action!r}")


def _auction_of_row(row) -> dt.date:
    ts = dt.datetime.fromisoformat(str(row["recorded_utc"]).strip())
    if ts.tzinfo is None:
        raise VerifyInputError(f"naive recorded_utc {row['recorded_utc']!r} "
                               f"on {row.get('instrument')}")
    from ops.decision_age import EXCHANGE_TZ
    return po.auction_for(ts.astimezone(EXCHANGE_TZ))


def _net(rows) -> dict:
    out: dict[str, float] = {}
    for r in rows:
        out[r["instrument"]] = out.get(r["instrument"], 0.0) + r["signed"]
    return out


def evaluate(*, auction: dt.date, universe: dict, contested: set,
             broker_positions: dict, open_trades: list, executions: list,
             order_map_rows: list, ledger: dict) -> list[Check]:
    """The five-way comparison. Pure: no broker, no files, no clock.

    universe          {sleeve: set(instrument)} for THIS book
    contested         instruments another book also trades -- the account net
                      of those is not ours, so they are compared only where
                      an order-map row attributes them
    broker_positions  {symbol: signed shares}; IBKR emits NO row for a flat
                      position, so absent means 0 here and nowhere else
    open_trades       dicts from pending_orders.resting_at_broker
    executions        [{instrument, side, shares, time_et (datetime), ...}]
    order_map_rows    raw `_order_map.csv` rows
    ledger            {sleeve: (last_date, {instrument: shares})}
    """
    from ops.decision_age import EXCHANGE_TZ

    mine = set().union(*universe.values()) if universe else set()
    owner = {i: s for s, insts in universe.items() for i in insts}
    checks: list[Check] = []

    # -- what we sent, by auction --------------------------------------
    sent = []
    for r in order_map_rows:
        inst = str(r.get("instrument", "")).strip()
        if inst not in mine:
            continue
        try:
            auc = _auction_of_row(r)
        except ValueError as exc:
            raise VerifyInputError(
                f"_order_map.csv row for {inst} has an unparseable "
                f"recorded_utc {r.get('recorded_utc')!r}") from exc
        sent.append({"instrument": inst, "sleeve": str(r.get("sleeve", "")),
                     "action": str(r.get("action", "")),
                     "qty": float(r.get("qty") or 0),
                     "signed": _signed(r.get("action", ""), r.get("qty") or 0),
                     "auction": auc,
                     "recorded_utc": str(r.get("recorded_utc", ""))})
    for_d = [s for s in sent if s["auction"] == auction]
    checks.append(Check(
        "transmitted", INFO,
        f"{len(for_d)} order(s) on {len({s['instrument'] for s in for_d})} "
        f"symbol(s) were transmitted for the {auction} close"
        + ("" if for_d else " -- a band hold, a stand-down, or a session that "
                            "never reached the trade phase; the session log "
                            "says which"),
        [{k: (v.isoformat() if isinstance(v, dt.date) else v)
          for k, v in s.items()} for s in for_d]))

    # -- what the broker executed at D ----------------------------------
    ex_d = [e for e in executions if e["time_et"].astimezone(EXCHANGE_TZ).date()
            == auction]
    for e in ex_d:
        e["signed"] = _signed(e["side"], e["shares"])
    ours = [e for e in ex_d if e["instrument"] in mine
            and e["instrument"] not in contested]
    if not ex_d and for_d:
        checks.append(Check(
            "fills", UNVERIFIED,
            f"the broker shows NO executions dated {auction} on any symbol, "
            f"while {len(for_d)} order(s) were sent for that close. Either "
            f"nothing filled, or the gateway session no longer holds that "
            f"day (IB restarts it nightly). Positions below carry the verdict."))
    else:
        want = _net([s for s in for_d if s["instrument"] not in contested])
        got = _net(ours)
        bad = []
        for inst in sorted(set(want) | set(got)):
            w, g = want.get(inst, 0.0), got.get(inst, 0.0)
            if abs(w - g) > 1e-6:
                kind = ("NOT FILLED" if g == 0 else
                        "UNEXPLAINED EXECUTION -- nothing was sent" if w == 0
                        else "OVERFILLED -- more than was sent (stacked set?)"
                        if abs(g) > abs(w) else "PARTIAL")
                bad.append({"instrument": inst, "sent": w, "executed": g,
                            "kind": kind})
        skipped = sorted({s["instrument"] for s in for_d
                          if s["instrument"] in contested})
        if bad:
            checks.append(Check(
                "fills", FAIL,
                f"{len(bad)} symbol(s) did not execute as sent at the "
                f"{auction} close: " + "; ".join(
                    f"{b['instrument']} sent {b['sent']:+.0f} executed "
                    f"{b['executed']:+.0f} ({b['kind']})" for b in bad), bad))
        else:
            checks.append(Check(
                "fills", PASS,
                f"every order sent for the {auction} close executed in full "
                f"({len(want)} symbol(s), {len(ours)} execution(s))"
                + (f"; not attributable by symbol, not checked: {skipped}"
                   if skipped else "")))

    # -- ledger + what was sent since == broker ---------------------------
    diffs, compared = [], 0
    for sleeve, (last, held) in ledger.items():
        since = [s for s in sent if s["sleeve"] == sleeve
                 and last < s["auction"] <= auction]
        expect = dict(held)
        for s in since:
            expect[s["instrument"]] = expect.get(s["instrument"], 0.0) + s["signed"]
        for inst in sorted(universe.get(sleeve, set()) | set(expect)):
            if inst in contested:
                continue
            compared += 1
            e = float(expect.get(inst, 0.0))
            b = float(broker_positions.get(inst, 0.0))
            if abs(e - b) > 1e-6:
                diffs.append({"sleeve": sleeve, "instrument": inst,
                              "ledger": float(held.get(inst, 0.0)),
                              "ledger_date": last.isoformat(),
                              "sent_since": sum(s["signed"] for s in since
                                                if s["instrument"] == inst),
                              "expected": e, "broker": b, "gap": b - e})
    stray = sorted(sym for sym, q in broker_positions.items()
                   if sym in mine and sym not in contested and sym not in owner
                   and abs(q) > 1e-6)
    if diffs:
        checks.append(Check(
            "positions", FAIL,
            f"{len(diffs)} of {compared} position(s) at the broker differ from "
            f"ledger + orders sent since the ledger's last date: " + "; ".join(
                f"{d['instrument']} broker {d['broker']:+.0f} vs expected "
                f"{d['expected']:+.0f} (ledger {d['ledger']:+.0f} @ "
                f"{d['ledger_date']}, sent since {d['sent_since']:+.0f})"
                for d in diffs[:8]) + (" ..." if len(diffs) > 8 else "")
            + ". The next session sizes against the broker for these, not "
              "the ledger -- but the ledger's P&L is wrong until reconciled.",
            diffs))
    else:
        checks.append(Check(
            "positions", PASS,
            f"broker == ledger + orders sent since, share for share, on "
            f"{compared} position(s)"
            + (f"; {len(contested & mine)} contested symbol(s) not compared"
               if contested & mine else "")))
    if stray:
        checks.append(Check("positions_unowned", FAIL,
                            f"broker holds book symbols no sleeve owns: {stray}"))

    # -- nothing left resting that should not be ---------------------------
    future = [s for s in sent if s["auction"] > auction]
    unmatched = []
    pool = [dict(s) for s in future]
    for t in open_trades:
        hit = next((s for s in pool if s["instrument"] == t["instrument"]
                    and s["action"].upper() == t["action"].upper()
                    and abs(s["qty"] - float(t["qty"])) < 1e-6), None)
        if hit:
            pool.remove(hit)
        else:
            unmatched.append(t)
    if unmatched:
        checks.append(Check(
            "resting", FAIL,
            f"{len(unmatched)} order(s) resting on book symbols after the "
            f"{auction} close that no order-map row sends to a later auction: "
            + "; ".join(f"{t['instrument']} {t['action']} {t['qty']:.0f} "
                        f"{t['order_type']} {t['status']}" for t in unmatched)
            + ". The next session's pending-order guard will refuse to trade "
              "until they clear.", unmatched))
    else:
        n = len(open_trades)
        checks.append(Check(
            "resting", PASS,
            "nothing resting on book symbols" if not n else
            f"{n} resting order(s), each recorded for a later auction"))
    return checks


def overall(checks: list[Check]) -> str:
    worst = max((_RANK[c.status] for c in checks), default=0)
    return {0: PASS, 1: WARN, 2: UNVERIFIED, 3: FAIL}[worst]


# -- inputs ------------------------------------------------------------------

def default_auction(now_et: dt.datetime) -> dt.date:
    """The most recent close that has happened: today after 16:00 ET on a
    trading day, otherwise the previous trading day."""
    sys.path.insert(0, str(REPO_ROOT / "ops" / "schedule"))
    import nyse_calendar as cal
    d = now_et.date()
    if cal.is_trading_day(d) and (now_et.hour, now_et.minute) >= (16, 0):
        return d
    return cal.previous_trading_day(d)


def read_ledger(books_root: Path, sleeves) -> dict:
    """{sleeve: (last_date, {instrument: shares})} from each sleeve's
    positions.csv. A missing or unreadable file RAISES."""
    import pandas as pd
    out = {}
    for s in sleeves:
        path = books_root / "_ibkr_shadow" / s / "positions.csv"
        if not path.exists():
            raise VerifyInputError(f"{path} does not exist; there is no ledger "
                                   f"to compare the broker against")
        df = pd.read_csv(path)
        if df.empty:
            raise VerifyInputError(f"{path} is empty")
        last = pd.to_datetime(df["date"]).max()
        rows = df[pd.to_datetime(df["date"]) == last]
        rows = rows[rows["ticker"] != "CASH"]
        out[s] = (last.date(), {str(r.ticker): float(r.shares)
                                for r in rows.itertuples()})
    return out


def contested_symbols(book_path: Path) -> set:
    """Instruments this book trades that another *_book.json also trades."""
    from ops.preflight import deployed_tickers
    mine = set().union(*[set(v) for v in deployed_tickers(book_path).values()])
    other = set()
    for cand in sorted(book_path.resolve().parent.glob("*_book.json")):
        if cand.resolve() == book_path.resolve():
            continue
        for v in deployed_tickers(cand).values():
            other |= set(v)
    return mine & other


def read_broker(client_id: int) -> dict:
    """One read-only session: positions, open orders, executions."""
    try:
        import ib_async as ibapi
    except ImportError:                                  # pragma: no cover
        import ib_insync as ibapi                        # see CLAUDE.md landmine 8
    from ops.decision_age import EXCHANGE_TZ
    from src.deploy.broker.ibkr import IBKRConfig

    cfg = IBKRConfig.from_env()
    ib = ibapi.IB()
    ib.connect(cfg.host, int(cfg.port), clientId=int(client_id),
               readonly=True, timeout=30)
    try:
        positions: dict[str, float] = {}
        for p in ib.positions():
            sym = (getattr(p.contract, "localSymbol", None)
                   or p.contract.symbol)
            positions[sym] = positions.get(sym, 0.0) + float(p.position)
        trades = list(ib.reqAllOpenOrders() or [])
        seen = {id(t) for t in trades}
        trades += [t for t in ib.openTrades() if id(t) not in seen]
        fills = list(ib.reqExecutions() or [])
        executions = []
        for f in fills:
            e = f.execution
            t = e.time if e.time.tzinfo else e.time.replace(tzinfo=dt.timezone.utc)
            executions.append({
                "instrument": (getattr(f.contract, "localSymbol", None)
                               or f.contract.symbol),
                "side": e.side, "shares": float(e.shares),
                "price": float(e.price), "exec_id": e.execId,
                "order_id": e.orderId, "client_id": e.clientId,
                "perm_id": e.permId, "order_ref": e.orderRef,
                "time_et": t.astimezone(EXCHANGE_TZ)})
        return {"positions": positions, "trades": trades,
                "executions": executions,
                "account": getattr(cfg, "account", None)}
    finally:
        ib.disconnect()


# -- run ---------------------------------------------------------------------

def _summary(book_id, auction, status, checks) -> tuple[str, str]:
    lines = [f"{c.status:<10} {c.name:<18} {c.message}" for c in checks]
    head = {PASS: "OK", WARN: "OK with warnings", UNVERIFIED: "COULD NOT VERIFY",
            FAIL: "FAILED"}[status]
    n_fail = sum(c.status == FAIL for c in checks)
    subject = (f"QUANTT {book_id} {auction}: {head}"
               + (f" ({n_fail} check(s))" if n_fail else ""))
    body = "\n".join(lines)
    return subject, body


def run(book: Path, books_root: Path, client_id: int, auction=None,
        now=None, send_alert=True) -> int:
    from ops import halt as halt_mod
    from ops.decision_age import EXCHANGE_TZ
    from ops.preflight import deployed_tickers

    now_et = (now or dt.datetime.now(EXCHANGE_TZ)).astimezone(EXCHANGE_TZ)
    auction = auction or default_auction(now_et)
    spec = json.loads(book.read_text())
    book_id = spec.get("book_id") or book.stem
    job = f"verify_{book_id}"
    archive = books_root / "_broker_archive" / auction.isoformat()
    archive.mkdir(parents=True, exist_ok=True)
    stamp = f"{now_et:%Y%m%d_%H%M%S}"

    try:
        universe = {k: set(v) for k, v in deployed_tickers(book).items()}
        contested = contested_symbols(book)
        ledger = read_ledger(books_root, universe)
        rows = po.read_order_map(books_root / "_ibkr_shadow" / "_order_map.csv")
    except Exception as exc:                          # noqa: BLE001 - reported
        checks = [Check("inputs", UNVERIFIED, f"local records unreadable: {exc!r}")]
        return _finish(halt_mod, job, book_id, auction, checks, archive, stamp,
                       send_alert, snapshot=None)

    try:
        broker = read_broker(client_id)
    except Exception as exc:                          # noqa: BLE001 - reported
        checks = [Check("broker", UNVERIFIED,
                        f"could not read the broker read-only as client "
                        f"{client_id}: {exc!r}. If the gateway is down after "
                        f"the close, tomorrow's session cannot trade either.")]
        return _finish(halt_mod, job, book_id, auction, checks, archive, stamp,
                       send_alert, snapshot=None)

    mine = set().union(*universe.values()) if universe else set()
    resting = po.resting_at_broker(broker["trades"],
                                   mine | set(ledger_syms(ledger)))
    snapshot = {"measured_et": now_et.isoformat(), "auction": auction.isoformat(),
                "client_id": client_id, "positions": broker["positions"],
                "resting": resting,
                "executions": [{**e, "time_et": e["time_et"].isoformat()}
                               for e in broker["executions"]]}
    try:
        checks = evaluate(auction=auction, universe=universe,
                          contested=contested,
                          broker_positions=broker["positions"],
                          open_trades=resting,
                          executions=broker["executions"],
                          order_map_rows=rows, ledger=ledger)
    except VerifyInputError as exc:
        checks = [Check("inputs", UNVERIFIED, str(exc))]
    return _finish(halt_mod, job, book_id, auction, checks, archive, stamp,
                   send_alert, snapshot=snapshot)


def ledger_syms(ledger: dict):
    for _, (_, held) in ledger.items():
        yield from held


def _finish(halt_mod, job, book_id, auction, checks, archive, stamp,
            send_alert, snapshot) -> int:
    status = overall(checks)
    subject, body = _summary(book_id, auction, status, checks)
    print(subject)
    print(body)
    delivered = None
    if send_alert:
        delivered = halt_mod.alert(subject=subject, body=body)
        # Only email reaches a person who is not at this Mac. The banner and
        # speech are recorded, but they do not make a message "delivered".
        if delivered.get("email") is not True:
            print(f"[verify] *** NOBODY AWAY FROM THIS MAC WAS TOLD: email "
                  f"{delivered.get('email')} ***")
    verdict = {"book_id": book_id, "auction": auction.isoformat(),
               "status": status, "checks": [asdict(c) for c in checks],
               "alert": delivered}
    if snapshot is not None:
        (archive / f"broker_{stamp}.json").write_text(
            json.dumps(snapshot, indent=2, default=str))
    (archive / f"verdict_{stamp}.json").write_text(
        json.dumps(verdict, indent=2, default=str))
    halt_mod.beat(job, {PASS: "ok", WARN: "ok", UNVERIFIED: "unverified",
                        FAIL: "failed"}[status],
                  {"auction": auction.isoformat(),
                   "failed": [c.name for c in checks if c.status == FAIL],
                   "email_delivered": (delivered or {}).get("email") is True})
    return {PASS: 0, WARN: 0, FAIL: 1, UNVERIFIED: 2}[status]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--book", required=True, type=Path)
    ap.add_argument("--books-root", required=True, type=Path)
    ap.add_argument("--client-id", required=True, type=int,
                    help="read-only id; convention is the session's id + 80")
    ap.add_argument("--auction", default=None,
                    help="YYYY-MM-DD; default the most recent completed close")
    ap.add_argument("--no-alert", action="store_true")
    a = ap.parse_args(argv)
    auction = dt.date.fromisoformat(a.auction) if a.auction else None
    if auction is None:
        # The launchd job fires Mon-Fri. On an exchange holiday the "last close"
        # is yesterday's, already verified and already messaged; a second
        # message would train the reader that the daily one is noise.
        from ops.decision_age import EXCHANGE_TZ
        sys.path.insert(0, str(REPO_ROOT / "ops" / "schedule"))
        import nyse_calendar as cal
        today = dt.datetime.now(EXCHANGE_TZ).date()
        if not cal.is_trading_day(today):
            print(f"[verify] {today} is not an NYSE trading day; nothing closed")
            return 0
    return run(a.book, a.books_root, a.client_id, auction=auction,
               send_alert=not a.no_alert)


if __name__ == "__main__":
    raise SystemExit(main())
