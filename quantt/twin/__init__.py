"""The IBKR twin: the three Alpaca paper books' saved plans, netted, sent as MOC orders to ONE IBKR
paper account, and booked to a per-strategy ledger. PAPER ONLY.

    python3 -m quantt.twin probe                     read the account (read-only)
    python3 -m quantt.twin epoch                     once: seed the ledger from the account
    python3 -m quantt.twin send [--approve SHA]      the 15:30 / 15:40 send (12:30 / 12:40 early)
    python3 -m quantt.twin send --dry [--session D]  the whole send, nothing transmitted, any day
    python3 -m quantt.twin verify                    17:45: book the executions, score them
    python3 -m quantt.twin compare [--aggregates]    the side-by-side table so far
    python3 -m quantt.twin cancel-open [--confirm N] human-run: list, then cancel, resting orders

WHY (team lead, 2026-11-25; results/ops/IBKR_PAPER_MOVE_2026-11-25.md on its own branch). The
books' orders must be MOC, and Alpaca paper under-fills `cls` (CLAUDE.md order-path rule 3's paper
exception). IBKR paper takes MOC and filled 41 of 42 in September. The account is the team lead's
existing one, which has ONE paper account, so the three books share it ("All three together"):
one MOC order a symbol, netted, and a ledger that says who owns what. Each book's twin trades the
plan its Alpaca book decided, on the same day, and a book switches after it matches or beats
Alpaca on a clean side-by-side session (team lead, 2026-11-25: one session).

WHAT IT NEVER DOES
  * Decide. Every share target is read from a book's own saved plan.json, checked the way that
    book's own send checks it (`books.py`). A book whose plan did not decide HOLDS its ledger
    shares, as its Alpaca book does not trade.
  * Touch an Alpaca account. Alpaca is read for the clock, the calendar, corporate actions and the
    official closing prints only, through `market.MarketData`, which exposes no order method.
  * Change a file the Alpaca books run. Nothing under quantt/session, quantt/sleeves or
    quantt/collect is written by this package; it imports their checks and the ledger.
  * Send an alert. "No phone" (team lead, 2026-11-25): a logged-out Gateway shows on the daily page
    and in orient (status.json), and nowhere else.

THE CUT-OVER READ (contract step 11, a later build on top of this one). `ledger_view(state_dir)`,
in `view.py` and re-exported here, is the one public read of the twin's ledger: {slug: {"shares", "cash"}}. A book cut over to
IBKR sizes from its own slugs there. Nothing else in this package is an interface.
"""
from __future__ import annotations

from quantt.twin.view import ledger_view

__all__ = ["ledger_view"]
