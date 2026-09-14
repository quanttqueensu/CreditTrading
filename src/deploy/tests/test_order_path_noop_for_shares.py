"""The inertness proof for the 2026-09-11 option-path change.

WHY THIS FILE EXISTS
--------------------
`docs/prompts/gamma/G4` Part A's fixes touch `_order`, `_place_combo` and
`place_targets` — three functions the CEF book calls in every live session. The
option branches they change are unreachable for a share target, but "unreachable
by reading" is exactly the confidence CLAUDE.md warns about: the cwd defect of
2026-09-10 was found by WRITING a test, not by running the suite, which passed
green throughout.

So this file asserts the property directly rather than by inspection: **for a
book of share targets, the exact sequence of (contract, order) pairs handed to
the broker is unchanged.** The expected sequence is written out literally below
rather than captured from the current code, so a future edit that changes both
the code and a recorded golden in the same commit still fails here.

Three books trade today and all three are shares-only:
`cef_discount` (17 CEFs, MOC), `benchmarks` (5 static-weight ETF sleeves) and
`phase0_null`. The cases below cover the two order shapes those produce — a
plain market order and the MOC the CEF band uses — plus the FLAT path that
closes a held-but-unmentioned position, which is the one that reaches for
`_order` with a negative delta.

NO BROKER, NO NETWORK. Same `__new__` + stub construction as
`test_arm_attribution.py` and `test_option_order_path.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.broker.ibkr import IBKRBroker  # noqa: E402
from src.deploy.sleeve import LONG, SHORT, PositionTarget  # noqa: E402

from src.deploy.tests.test_option_order_path import (  # noqa: E402
    _IbInsync, _StubIB,
)


def _broker():
    b = IBKRBroker.__new__(IBKRBroker)
    b._ib_insync = _IbInsync()
    b.ib = _StubIB()
    b._sleeves = {}
    b._bond_instruments = set()      # `_is_bond` consults it on every contract
    return b


def _share(instrument, side=LONG, qty=100.0, **meta):
    return PositionTarget(instrument=instrument, side=side, qty=qty,
                          meta=meta or None)


# -- the order shapes the three live books produce ------------------------

def test_plain_share_target_is_still_a_market_order():
    """benchmarks and phase0: static weights, plain market orders."""
    b = _broker()
    o = b._order(_share("HYG"), 100.0)
    assert (o.action, o.totalQuantity, o.orderType) == ("BUY", 100.0, "MKT")


def test_moc_share_target_is_still_an_moc_with_a_day_tif():
    """The CEF band's order type. `order_type: MOC` + `tif: DAY`.

    IB rejects an MOC with an empty TIF, and overnight market orders realised
    100.5bp against a 32.6bp breakeven on 2026-07-31. Both facts are why this
    branch exists; neither may move.
    """
    b = _broker()
    o = b._order(_share("NVG", order_type="MOC"), 250.0)
    assert o.orderType == "MOC"
    assert o.tif == "DAY"
    assert (o.action, o.totalQuantity) == ("BUY", 250.0)


def test_moc_is_case_insensitive_and_accepts_the_long_spelling():
    b = _broker()
    assert b._order(_share("NVG", order_type="moc"), 10.0).orderType == "MOC"
    assert b._order(_share("NVG", order_type="MARKETONCLOSE"),
                    10.0).orderType == "MOC"


def test_sell_side_share_order_is_unchanged():
    """The FLAT path: closing a held-but-unmentioned position sends a SELL."""
    b = _broker()
    o = b._order(_share("PHK", side=SHORT, qty=-40.0), -40.0)
    assert (o.action, o.totalQuantity, o.orderType) == ("SELL", 40.0, "MKT")


# -- the sequence, written out rather than captured -----------------------

def test_share_basket_transmits_exactly_the_expected_sequence():
    """A realistic mixed basket. The expectation is literal, not a golden file.

    If `_validate_option_targets` ever stopped skipping non-OPTION kinds, or if
    the validation pass reordered placement, this is what would catch it.
    """
    b = _broker()
    targets = [_share("NVG", qty=250.0, order_type="MOC"),
               _share("PHK", side=SHORT, qty=-40.0, order_type="MOC"),
               _share("HYG", qty=100.0)]

    b._validate_option_targets(targets)          # the new pass: must be inert

    for pt in targets:
        b.ib.placeOrder(b._contract(pt), b._order(pt, pt.signed_qty()))

    got = [(c.symbol if hasattr(c, "symbol") else c.localSymbol,
            o.action, float(o.totalQuantity), o.orderType)
           for c, o in b.ib.placed]
    assert got == [
        ("NVG", "BUY", 250.0, "MOC"),
        ("PHK", "SELL", 40.0, "MOC"),
        ("HYG", "BUY", 100.0, "MKT"),
    ]


def test_validation_pass_is_a_noop_for_every_non_option_kind():
    """ETF, EQUITY and FUTURES targets must all pass through untouched.

    Only OPTION carries the `limit_price` requirement. A validation pass that
    tightened on any other kind would block three live books on its first
    session.
    """
    from src.deploy.sleeve import EQUITY, ETF, FUTURES

    b = _broker()
    for kind in (ETF, EQUITY, FUTURES):
        pt = PositionTarget(instrument="X", side=LONG, kind=kind, qty=1.0)
        b._validate_option_targets([pt])          # must not raise


def test_validation_pass_tolerates_an_empty_and_a_none_basket():
    """`place_targets` can reach it with nothing to send on a hold day."""
    b = _broker()
    b._validate_option_targets([])
    b._validate_option_targets(None)


# -- the guard that would have caught a bad fix ---------------------------

def test_a_bond_target_with_no_limit_price_is_not_forced_to_options_rules():
    """Bonds carry `limit_price` too. The option rule must not leak to them.

    `_place_bond` reads the same key and, when it is absent, falls back to the
    local close and only then warns-and-skips — deliberately, because a raise
    mid-basket leaves a half-sent order set. If the option validation ever
    matched on the KEY rather than on `kind == OPTION`, the bond path would
    start raising instead of skipping: a behaviour change on a live path, from
    an edit that looks like a tightening.

    Bonds are identified by meta (`asset='corporate_bond'` or a `cusip`), not
    by `kind` — there is no bond kind in the enum.
    """
    b = _broker()
    bond = PositionTarget(instrument="XS123", side=LONG, qty=1.0,
                          meta={"asset": "corporate_bond", "cusip": "XS123",
                                "limit_price": None})
    b._validate_option_targets([bond])    # must not raise
