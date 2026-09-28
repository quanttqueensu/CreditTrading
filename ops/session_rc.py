"""The session return-code table. Constants, one set and the table; no behaviour.

WHY THIS EXISTS
---------------
Until 2026-09-21 a session's return codes lived as bare literals at their
`return` statements in `src/deploy/run_book.py` (3, 4, 5, 6, each explained in
a comment beside it), read by the launcher's `rc != 0` branch and by nothing
under ops/. The hardening plan changes that: it adds four codes, and it makes
`ops.halt.beat`, `ops.session_plan` and `ops.verify_session` key on one
question -- "given this rc, can an order have left the machine?" -- because a
failed session that provably transmitted nothing must not count as today's
armed session, and one that might have transmitted must never be retried into
the same auction (the trade phase is not idempotent and the broker does not
dedupe: a second armed run doubles the book).

So the answer is written down ONCE, here, as data. Every workstream imports
it; none invents a code. The source is section P.6 of
`results/ops/hardening_2026-09-21/PLAN.md`.

This module is on the live path, so it imports nothing from the repo and
nothing beyond the stdlib, and it does nothing at import but build constants.

WHAT IS AND IS NOT IN `NON_TRANSMITTING_RCS`
--------------------------------------------
Membership means: a session that exited with this code CANNOT have placed an
order, so a reader may treat the session as not armed. The direction of error
matters. Wrongly OUT of the set costs a trading day (the book reads as armed
and the later fire stands down). Wrongly IN the set lets a second armed fire
into an auction that already holds this book's orders. So the set fails closed
and every doubtful code stays out:

  1     any unhandled exception, including ShadowLedgerDesync, and any refusal
        raised after `n_placed > 0`. Orders may have left. Out.
  2     argparse usage error. Nothing can have left, but the launcher cannot
        produce it, so nothing is lost by failing closed. Out.
  5, 6  OrdersAlreadyPending / PendingStateUnknown. In a multi-sleeve book an
        earlier sleeve may already have transmitted when a later one refuses.
        Out: it stays "armed", the safe direction.
  3     arm refused. `arm()` precedes every `place_targets`, so P.6 admits it
        -- "yes, only if its two tests pass". Those tests do not exist yet
        (WS2 step 2.2.5, `src/deploy/tests/test_run_book_refusal_rc.py`), so
        it is held in `PENDING_PROOF_RCS` and is NOT in the set. Whoever lands
        the two tests moves it in the same commit. An rc 3 also writes a
        scoped halt, which blocks the later fire on its own.

For every code that IS in the set, P.6 requires two tests before anything
relies on it: (i) run_book returns it only with `ib.placed == []`; (ii) with a
stub whose placeOrder succeeds once and then raises, or whose second sleeve
refuses, run_book never returns it. Codes 7-10 do not exist in run_book yet;
they are reserved here so the workstreams that add them cannot collide.
"""

from __future__ import annotations

from typing import NamedTuple

# -- src.deploy.run_book -----------------------------------------------------

RC_OK = 0
RC_ERROR = 1
RC_USAGE = 2
RC_ARM_REFUSED = 3
RC_DECISION_TOO_OLD = 4
RC_ORDERS_ALREADY_PENDING = 5
RC_PENDING_STATE_UNKNOWN = 6
RC_PRE_TRANSMIT_REFUSAL = 7
RC_SLEEVE_CANNOT_DECIDE = 8
RC_DRY_RUN_HALT = 9
RC_HALT_ACTIVE = 10


class RcRow(NamedTuple):
    """One row of P.6. The three text fields are the plan's own wording."""
    rc: int
    name: str
    raised_by: str
    order_may_have_left: str
    non_transmitting: bool


TABLE = (
    RcRow(RC_OK, "RC_OK",
          "success",
          "yes",
          False),
    RcRow(RC_ERROR, "RC_ERROR",
          "any unhandled exception, ShadowLedgerDesync, or any refusal when "
          "n_placed > 0",
          "yes/unknown",
          False),
    RcRow(RC_USAGE, "RC_USAGE",
          "argparse: --job missing for ibkr non-dry-run",
          "no, but unreachable from the launcher",
          False),
    RcRow(RC_ARM_REFUSED, "RC_ARM_REFUSED",
          "arm refused (existing; also writes a halt)",
          "no, arm precedes every place_targets",
          False),   # PENDING_PROOF_RCS: admitted only once its two tests pass
    RcRow(RC_DECISION_TOO_OLD, "RC_DECISION_TOO_OLD",
          "DecisionTooOld (existing)",
          "no",
          True),
    RcRow(RC_ORDERS_ALREADY_PENDING, "RC_ORDERS_ALREADY_PENDING",
          "OrdersAlreadyPending (existing)",
          "possible in a multi-sleeve book",
          False),
    RcRow(RC_PENDING_STATE_UNKNOWN, "RC_PENDING_STATE_UNKNOWN",
          "PendingStateUnknown (existing)",
          "possible in a multi-sleeve book",
          False),
    RcRow(RC_PRE_TRANSMIT_REFUSAL, "RC_PRE_TRANSMIT_REFUSAL",
          "pre-transmit ledger/NAV refusal (ShadowLedgerBehind, "
          "BookingWouldFail, SleeveNavUnknown) and n_placed == 0",
          "no",
          True),
    RcRow(RC_SLEEVE_CANNOT_DECIDE, "RC_SLEEVE_CANNOT_DECIDE",
          "SleeveCannotDecide and n_placed == 0",
          "no",
          True),
    RcRow(RC_DRY_RUN_HALT, "RC_DRY_RUN_HALT",
          "DRY_RUN=1 visible to an ibkr non-dry-run call",
          "no, returns before make_broker",
          True),
    RcRow(RC_HALT_ACTIVE, "RC_HALT_ACTIVE",
          "halt active",
          "no",
          True),
)

# Derived from the table so the two cannot disagree.
NON_TRANSMITTING_RCS = frozenset(r.rc for r in TABLE if r.non_transmitting)

# P.6 says "yes, only if its two tests pass". See the module docstring.
PENDING_PROOF_RCS = frozenset({RC_ARM_REFUSED})

# -- scripts/cef/fetch_daily.py ----------------------------------------------
# A different program with its own small table. 0, 1 and 4 are what it returns
# today (1 = no staged panel, 4 = INCOMPLETE for the required asof); P.6 keeps
# them and adds 14. Its 4 is not run_book's 4, which is why these carry a
# FETCH_ prefix and are never mixed into TABLE.

FETCH_OK = 0
FETCH_NO_STAGED_PANEL = 1
FETCH_INCOMPLETE = 4
FETCH_VENDOR_EMPTY = 14   # vendor returned nothing / no network

# -- the launcher --------------------------------------------------------------
# What launch_job.py already returns when a child outlives its `budget_min`
# and is killed (its `except subprocess.TimeoutExpired` branch). Never returned
# by a session itself; named here so a repo-side reader of a beat's rc does not
# write the literal.

LAUNCHER_BUDGET_KILL = 124
