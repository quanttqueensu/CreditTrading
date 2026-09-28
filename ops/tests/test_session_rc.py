"""The return-code table says what P.6 says, and cannot quietly say more.

`ops/session_rc.py` has no behaviour to test. What can go wrong with a table is
that someone edits it: adds a code to `NON_TRANSMITTING_RCS` because a session
"obviously" sent nothing, reuses a number, or lets the set and the table drift
apart. Each of those would let a failed session that may have transmitted be
read as not armed, and the next fire would send the book into the same auction
a second time. So the values are pinned here, literally, and changing one
means changing this file in the same commit -- which is the review.

The literals below are copied from section P.6 of
`results/ops/hardening_2026-09-21/PLAN.md`, not from the module under test.

Each test names the one-line mutation that turns it red; the recorded red runs
are in `results/ops/hardening_2026-09-21/failing_first/`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import session_rc as rc  # noqa: E402


def test_the_codes_are_the_ones_P6_assigns():
    """MUTATION: RC_PRE_TRANSMIT_REFUSAL = 7 -> 5 (a reused number)."""
    assert {r.name: r.rc for r in rc.TABLE} == {
        "RC_OK": 0,
        "RC_ERROR": 1,
        "RC_USAGE": 2,
        "RC_ARM_REFUSED": 3,
        "RC_DECISION_TOO_OLD": 4,
        "RC_ORDERS_ALREADY_PENDING": 5,
        "RC_PENDING_STATE_UNKNOWN": 6,
        "RC_PRE_TRANSMIT_REFUSAL": 7,
        "RC_SLEEVE_CANNOT_DECIDE": 8,
        "RC_DRY_RUN_HALT": 9,
        "RC_HALT_ACTIVE": 10,
    }
    codes = [r.rc for r in rc.TABLE]
    assert len(codes) == len(set(codes)), "two rows share a return code"


def test_every_row_is_a_module_constant_of_the_same_name_and_value():
    """A row whose constant was renamed or renumbered is a row nobody imports.

    MUTATION: the RC_HALT_ACTIVE row built from RC_DRY_RUN_HALT.
    """
    for row in rc.TABLE:
        assert getattr(rc, row.name) == row.rc, row.name


def test_the_non_transmitting_set_is_exactly_the_proven_no_rows():
    """MUTATION: flip RC_ORDERS_ALREADY_PENDING's row to True.

    5 and 6 can follow a transmission in a multi-sleeve book; 1 can follow
    anything; 2 fails closed; 0 is a success. None may ever be in the set.
    """
    assert rc.NON_TRANSMITTING_RCS == frozenset({4, 7, 8, 9, 10})
    for never in (0, 1, 2, 5, 6):
        assert never not in rc.NON_TRANSMITTING_RCS


def test_arm_refused_waits_outside_the_set_until_it_is_proved():
    """P.6 admits rc 3 "only if its two tests pass". Until the commit that
    lands them moves it, it reads as armed -- the safe direction.

    MUTATION: flip RC_ARM_REFUSED's row to True.
    """
    assert rc.PENDING_PROOF_RCS == frozenset({3})
    assert not (rc.PENDING_PROOF_RCS & rc.NON_TRANSMITTING_RCS)


def test_the_set_is_derived_from_the_table_and_is_immutable():
    """MUTATION: NON_TRANSMITTING_RCS = frozenset(...) -> set(...)."""
    assert rc.NON_TRANSMITTING_RCS == frozenset(
        r.rc for r in rc.TABLE if r.non_transmitting)
    assert isinstance(rc.NON_TRANSMITTING_RCS, frozenset)
    assert isinstance(rc.TABLE, tuple)


def test_a_row_in_the_set_says_no_order_can_have_left():
    """The membership flag and the plan's own words must agree on every row.

    MUTATION: RC_SLEEVE_CANNOT_DECIDE's order_may_have_left "no" -> "yes".
    """
    for row in rc.TABLE:
        if row.non_transmitting:
            assert row.order_may_have_left.startswith("no"), row


def test_the_fetcher_and_launcher_codes():
    """MUTATION: FETCH_VENDOR_EMPTY = 14 -> 4 (collides with INCOMPLETE)."""
    assert (rc.FETCH_OK, rc.FETCH_NO_STAGED_PANEL, rc.FETCH_INCOMPLETE,
            rc.FETCH_VENDOR_EMPTY) == (0, 1, 4, 14)
    assert rc.LAUNCHER_BUDGET_KILL == 124


def test_the_module_is_constants_only_and_imports_nothing_from_the_repo():
    """It is imported on the live path, so it must not be able to fail, do
    I/O, or pull the rest of `ops` in behind it.

    MUTATION: add `import os` under the typing import.
    """
    tree = ast.parse(Path(rc.__file__).read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module)
    assert sorted(imported) == ["__future__", "typing"]
    defs = [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert defs == [], f"session_rc grew behaviour: {defs}"
