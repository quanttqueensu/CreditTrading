"""Is an order set already on its way to an auction we are about to trade into?

WHY THIS EXISTS
---------------
CLAUDE.md hard rule 2: the trade phase is not idempotent. `arm()` re-seeds from
`ib.positions()`, which does not include unfilled MOC orders, so a second armed
run diffs its targets against a book that has not yet received the first run's
orders, sends the same deltas again, and both sets fill in the same closing
auction. The book doubles.

Until 2026-09-13 every defence against that lived OUTSIDE the broker, keyed on
local proxies for "did we already trade":

  * `launch_job.py`'s SAME-DAY GUARD, keyed on the wall-clock date a heartbeat
    was FILED. On 2026-09-10 a session slept overnight and filed at 10:38 on
    09-11, so the guard refused the legitimate 09-11 session -- and would have
    let a genuinely stacked set through on any night the clock and the auction
    disagreed the other way.
  * `ops/session_plan.py`'s pair and today guards (W3), keyed on the same
    heartbeat file. Written at the END of the job, so a process that transmits
    and then dies before `beat()` leaves no record at all.

`grep -n reqOpenOrders src/deploy/broker/ibkr.py` returned nothing: the adapter
was structurally blind to its own resting orders. Each of those guards fixed the
last incident's shape, and the next incident had a different shape. This module
asks the question the way the broker would answer it, so it does not care WHY a
second run happened -- a double fire, a sleep, a manual re-run, a scheduler
patch, a clock bug nobody has found yet.

TWO SOURCES, BECAUSE EITHER ALONE HAS A KNOWN BLIND SPOT
-------------------------------------------------------
  (1) THE BROKER -- `reqAllOpenOrders()`. The authority on what is resting.
      Its blind spot is documented in this repo: on 2026-07-31 four armed runs
      stacked 79 MOC orders that were "invisible because `openTrades()` returns
      only the querying client's orders" (docs/INFRASTRUCTURE.md §5.4).
      `reqAllOpenOrders` is the call that is supposed to close that, and
      `ops/cancel_open_orders.py` relies on it, but whether it still reports
      another client id's order across IB's nightly restart has NOT been
      measured here [U].

  (2) OUR OWN ORDER MAP -- `_ibkr_shadow/_order_map.csv`, one row per
      transmitted order, written by `_record_order_attribution` immediately
      after `placeOrder` in the same process. It cannot be blind to a
      restart. Its blind spot is the opposite one: it cannot see an order it
      did not place, or know that the broker rejected one it did.

A row in (2) whose auction has not happened yet is an order set on its way,
whatever (1) says. A resting order in (1) is one too, whatever (2) says. So the
guard refuses on EITHER. When they disagree, that disagreement is printed, and
refusing is the direction that cannot double a book.

WHAT IT COSTS, NAMED
--------------------
A transmitted set the broker REJECTED still shows as pending in (2) until its
auction passes, so a same-auction retry (W3's 12:00 fire after a failed 08:30
one) is refused. That is deliberate: a rejected MOC set is a reason for a human
to look, and a retry of a rejected set is usually rejected again. The refusal
clears itself at the auction's close -- it never writes a halt.

The early-close gap in `ops/decision_age.py` applies here unchanged: an order's
auction is assumed to close at 16:00 ET, so on a 13:00 half-day a row looks
pending until 16:00. No session transmits in that window.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

# ib_async / ib_insync `OrderStatus.DoneStates`. Everything else -- including
# `Inactive`, which IB also uses for an order it is holding but not working --
# counts as resting. Excluding Inactive would be a guess about which kind of
# inactive it is, made in the direction that transmits.
DONE_STATUSES = frozenset({"Filled", "Cancelled", "ApiCancelled"})

NYSE_CLOSE = dt.time(16, 0)


class PendingOrdersUnknown(RuntimeError):
    """The pending-order question could not be answered, so nothing may be sent.

    NO SILENT FALLBACKS. An unreadable order map or a failed broker query is
    not evidence that nothing is pending.
    """


def _symbol(contract) -> str:
    """Same key `IBKRBroker.sync_positions` uses, so the two cannot disagree."""
    return str(getattr(contract, "localSymbol", None)
               or getattr(contract, "symbol", ""))


def resting_at_broker(trades, instruments) -> list[dict]:
    """Every not-done order on one of `instruments`, as plain dicts.

    `trades` is what `ib.reqAllOpenOrders()` / `ib.openTrades()` return. Anything
    malformed raises: a trade whose status or symbol cannot be read is not a
    trade we can call "not ours".
    """
    wanted = {str(i) for i in instruments}
    out = []
    for t in trades or ():
        try:
            sym = _symbol(t.contract)
            status = str(t.orderStatus.status)
            order = t.order
        except AttributeError as exc:
            raise PendingOrdersUnknown(
                f"an open trade returned by the broker could not be read "
                f"({exc!r}); refusing to assume it is not on this book's "
                f"symbols") from exc
        if status in DONE_STATUSES or sym not in wanted:
            continue
        out.append({"instrument": sym, "status": status,
                    "action": str(getattr(order, "action", "")),
                    "qty": float(getattr(order, "totalQuantity", 0) or 0),
                    "order_type": str(getattr(order, "orderType", "")),
                    "client_id": getattr(order, "clientId", None),
                    "order_id": getattr(order, "orderId", None),
                    "perm_id": getattr(order, "permId", None)})
    return out


def read_order_map(path) -> list[dict]:
    """Rows of `_order_map.csv`. A MISSING file is an empty map (a book that has
    never transmitted); an UNREADABLE one raises."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception as exc:                       # noqa: BLE001 - re-raised
        raise PendingOrdersUnknown(
            f"{path} exists but could not be read ({exc!r}); it is the only "
            f"record of what this book has already transmitted") from exc


def auction_for(transmitted_et: dt.datetime) -> dt.date:
    """The NYSE session whose close an MOC transmitted at this moment reached.

    One definition, shared with `ops.decision_age` -- the freeze constant and
    the holiday calendar are not re-derived here.
    """
    from ops.decision_age import reachable_auction
    return reachable_auction(transmitted_et)


def pending_in_order_map(rows, instruments, now_et: dt.datetime) -> list[dict]:
    """Order-map rows on `instruments` whose auction has not closed at `now_et`.

    `recorded_utc` is when the order was written down, which is at most a few
    milliseconds after `placeOrder` returned (same process, next statement).
    A row whose timestamp cannot be parsed raises rather than being skipped:
    skipping it is precisely how a pending order becomes an unpending one.
    """
    from ops.decision_age import EXCHANGE_TZ
    if now_et.tzinfo is None:
        raise PendingOrdersUnknown("now_et must be timezone-aware")
    now_et = now_et.astimezone(EXCHANGE_TZ)
    wanted = {str(i) for i in instruments}
    out = []
    for i, r in enumerate(rows):
        inst = str(r.get("instrument", "")).strip()
        if inst not in wanted:
            continue
        raw = str(r.get("recorded_utc", "")).strip()
        try:
            ts = dt.datetime.fromisoformat(raw)
        except ValueError as exc:
            raise PendingOrdersUnknown(
                f"_order_map.csv row {i + 2} ({inst}) has an unparseable "
                f"recorded_utc {raw!r}; cannot tell which auction that order "
                f"reached") from exc
        if ts.tzinfo is None:
            raise PendingOrdersUnknown(
                f"_order_map.csv row {i + 2} ({inst}) has a naive recorded_utc "
                f"{raw!r}; the writer stamps UTC explicitly, so this row was "
                f"not written by it")
        ts_et = ts.astimezone(EXCHANGE_TZ)
        auction = auction_for(ts_et)
        closes_at = dt.datetime.combine(auction, NYSE_CLOSE, tzinfo=EXCHANGE_TZ)
        if closes_at > now_et:
            out.append({"instrument": inst,
                        "action": str(r.get("action", "")),
                        "qty": str(r.get("qty", "")),
                        "sleeve": str(r.get("sleeve", "")),
                        "transmitted_et": f"{ts_et:%Y-%m-%d %H:%M:%S}",
                        "auction": auction.isoformat()})
    return out


def refusal(resting: list[dict], pending: list[dict]) -> str | None:
    """The refusal message, or None when neither source reports anything."""
    if not resting and not pending:
        return None
    lines = []
    if resting:
        lines.append(f"the BROKER reports {len(resting)} resting order(s) on "
                     f"this book's symbols:")
        for r in sorted(resting, key=lambda r: r["instrument"]):
            lines.append(f"    {r['instrument']:<6} {r['action']:<4} "
                         f"{r['qty']:>8.0f} {r['order_type']:<4} {r['status']} "
                         f"(client {r['client_id']}, permId {r['perm_id']})")
    if pending:
        auctions = sorted({p["auction"] for p in pending})
        lines.append(f"this book's ORDER MAP records {len(pending)} order(s) "
                     f"transmitted for auction(s) {', '.join(auctions)} that "
                     f"have not closed:")
        for p in sorted(pending, key=lambda p: (p["auction"], p["instrument"])):
            lines.append(f"    {p['instrument']:<6} {p['action']:<4} "
                         f"{p['qty']:>8} sent {p['transmitted_et']} ET "
                         f"-> {p['auction']} close ({p['sleeve']})")
    if bool(resting) != bool(pending):
        lines.append("THE TWO SOURCES DISAGREE. "
                     + ("The broker shows orders this book has no record of "
                        "sending -- another process, a manual order, or a map "
                        "write that failed." if resting else
                        "The broker shows nothing resting for orders this book "
                        "recorded sending -- they may have been rejected, or "
                        "the broker query may be blind to another client id's "
                        "orders (docs/INFRASTRUCTURE.md §5.4, 2026-07-31)."))
    lines.append("A second order set now would stack on the first in the same "
                 "closing auction (CLAUDE.md hard rule 2). Nothing was "
                 "transmitted and no halt was written: this clears itself once "
                 "that auction closes. To inspect without cancelling: "
                 "`python3 -m ops.cancel_open_orders --client-id <id>` "
                 "(list-only unless --confirm; a human runs it).")
    return "\n".join(lines)
