"""CLAUDE.md order-path rule 2 at IBKR: is a set already headed for an auction this send would reach?

THE RULE. The trade phase is not idempotent and the broker does not dedupe. An MOC order rests
at IBKR from the send until the auction, and a position does not include it, so a second run in
that window sees the old position, sends the same difference again, and both sets fill in one
auction: the book doubles. That window is exactly the twin's 15:30 send and its 15:40 backup.

FOUR SOURCES, ANY ONE OF WHICH REFUSES (contract §4.4; October §2.3; ported from
`git show pre-clean-slate:_archive/ops/pending_orders.py`, whose two-source design this keeps):
  1. STARTED. `<state>/<F>/STARTED`, written exclusively BEFORE the first order. It survives a
     Gateway restart and a crash. It is local: it cannot see another machine or a manual order.
  2. THE BROKER: ANY open order on the account, from ANY client id (`IBKRClient.open_orders`,
     `reqAllOpenOrders` + `openTrades`). Not only the twin's symbols: the account is the twin's
     alone, so any resting order is either a set headed for the auction or something a person
     must look at. Blind spot, documented in the archive: on 2026-07-31 four armed runs stacked 79
     MOC orders that `openTrades()` did not show. Whether `reqAllOpenOrders` sees another client's
     order across the Gateway's nightly restart is [U] (October R7).
  3. THE TWIN'S OWN ORDER LOG, `<state>/<D>/orders.jsonl`: an `intent` line is written and fsynced
     BEFORE each `placeOrder`, carrying the session and its calendar close. A line whose auction
     has not closed is a set on its way, whatever the broker says. Its blind spot is the opposite
     one: an order it did not place.
  4. TODAY'S EXECUTIONS. The twin's own MOC orders fill at the close, so before the send nothing
     should have executed today. An execution says something traded the account today.
When the sources disagree, the refusal says so; refusing is the direction that cannot double the
book. A source that cannot be read REFUSES (`GuardUnknown`): not knowing is not "nothing pending".

THE LOCK. Two processes could both pass the check before either's first order is acknowledged
(the archive's 2026-09-13 review: two coalesced fires on wake). `transmit_lock` takes a
non-blocking `flock` on `<state>/.transmit.lock` before the check and holds it to the process's
end; a second process refuses rather than waits. The kernel releases it at exit, crash included.

WHAT IT COSTS, NAMED (the archive's words, still true). A set the broker rejected still shows in
the log until its auction closes, so a same-day retry is refused. That is deliberate: a rejected
MOC set is a reason for a person to look. It clears at the close and writes no halt.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
from pathlib import Path

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
LOOKBACK_DAYS = 10          # day directories scanned for order-log lines (a week of sessions and a holiday)


class GuardUnknown(RuntimeError):
    """The pending-order question could not be answered, so nothing may be sent."""


class AlreadyTransmitting(RuntimeError):
    """Another process holds the transmit lock."""


def pending_in_logs(state: Path, now_et: dt.datetime) -> list:
    """Order-log `intent` lines whose auction (their recorded `close_et`) is after `now_et`.
    A line that cannot be read, or carries no close, raises: skipping it is precisely how a
    pending order becomes an unpending one."""
    if now_et.tzinfo is None:
        raise GuardUnknown("now_et must be timezone-aware")
    out = []
    floor = (now_et.date() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    for d in sorted(p for p in state.iterdir() if p.is_dir() and _DAY.fullmatch(p.name) and p.name >= floor):
        path = d / "orders.jsonl"
        if not path.exists():
            continue
        try:
            lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        except (OSError, ValueError) as e:
            raise GuardUnknown(f"{path} exists but cannot be read ({type(e).__name__}); it is the record of "
                               f"what was already sent") from None
        for i, r in enumerate(lines, 1):
            if not isinstance(r, dict) or r.get("event") != "intent":
                continue
            try:
                closes = dt.datetime.fromisoformat(r["close_et"])
            except (KeyError, TypeError, ValueError):
                raise GuardUnknown(f"{path} line {i}: no readable close_et; cannot tell which auction "
                                   f"that order reached") from None
            if closes.tzinfo is None:
                raise GuardUnknown(f"{path} line {i}: close_et {r['close_et']!r} has no zone")
            if closes > now_et:
                out.append({"symbol": r.get("symbol"), "side": r.get("side"), "qty": r.get("qty"),
                            "session_date": r.get("session_date"), "close_et": r["close_et"]})
    return out


def refusals(*, started: bool, open_orders: list | None, open_orders_error: str | None,
             pending: list, executions: list | None, executions_error: str | None) -> list:
    """[(gate, detail)] for rule 2, empty when every source is clear. Pure."""
    out = []
    if started:
        out.append(("no_set_in_auction", "STARTED exists for this session: a set already began to go"))
    if open_orders_error is not None:
        out.append(("no_set_in_auction", f"could not read the open orders: {open_orders_error}"))
    elif open_orders:
        desc = ", ".join(f"{o['symbol']} {o['action']} {o['qty']:.0f} {o['order_type']} {o['status']} "
                         f"(client {o['client_id']})" for o in sorted(open_orders, key=lambda o: str(o["symbol"]))[:12])
        out.append(("no_set_in_auction", f"IBKR shows {len(open_orders)} open order(s) on the account: {desc}"
                    + (" ..." if len(open_orders) > 12 else "")
                    + ". A person cancels them (`python3 -m quantt.twin cancel-open`) or waits for the close"))
    if pending:
        auctions = sorted({p["close_et"] for p in pending})
        out.append(("no_set_in_auction", f"the twin's order log records {len(pending)} order(s) sent for "
                    f"auction(s) closing {', '.join(auctions)}, not yet closed"))
    if executions_error is not None:
        out.append(("no_set_in_auction", f"could not read today's executions: {executions_error}"))
    elif executions:
        out.append(("no_set_in_auction", f"IBKR shows {len(executions)} execution(s) on the account today, "
                    "before the twin's send: something traded the account"))
    if bool(open_orders) != bool(pending) and (open_orders or pending) and open_orders_error is None:
        out.append(("no_set_in_auction", "THE SOURCES DISAGREE: "
                    + ("the broker shows orders the twin has no record of sending (another process, a manual "
                       "order, or a lost log line)" if open_orders else
                       "the twin's log records orders the broker does not show resting (rejected, or the "
                       "query is blind to another client id: 2026-07-31)")))
    return out


class transmit_lock:
    """`with transmit_lock(state):` -- one transmitting process per twin state directory."""

    def __init__(self, state: Path):
        self.path = Path(state) / ".transmit.lock"
        self.fd = None

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            raise GuardUnknown(f"cannot open the transmit lock {self.path} ({type(e).__name__})") from None
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise AlreadyTransmitting(f"another process is already sending for this twin (it holds {self.path}); "
                                      "this one stands down") from None
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"pid {os.getpid()}\n".encode())
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        return False
