"""The option order path, which has never run and has never been tested.

WHY THIS FILE EXISTS
--------------------
`grep -rn "OPTION\\|opt_type\\|strike" src/deploy/tests/` returned NOTHING before
this file. Every option branch in `IBKRBroker` — contract construction, order
construction, the BAG combo path, the multiplier defaults — was written, merged
and carried for months with no test touching any of it. It has never executed
either: no deployed sleeve emits an `OPTION` `PositionTarget`, so
`_order`'s `pt.kind == OPTION` branch is unreachable today.

That combination is the specific thing CLAUDE.md's hard rules call most
dangerous: code on the path that transmits orders, dormant, unexercised, and
confidently wrong. Both shipped silent-fallback examples in that file —
`nav_now = _nav_last(...) or 500000.0` and `fee.fillna(fee.median())` — were
dormant for months before they cost anything.

WHAT EACH TEST PINS, AND THE DEFECT IT ENCODES
----------------------------------------------
G4 Part A names four defects; one of its four (the `.v2.odd_lot` import) was
already fixed before this file was written and is NOT tested here — see
`test_g4_part_a4_is_already_fixed` for the evidence, because a prompt that
claims a live defect which does not exist sends the next reader hunting.

  A1  every combo leg is submitted with conId = 0
  A2  an option with no limit_price becomes a LIMIT order at $0.00
  A3  the combo package is a MarketOrder on a multi-leg option spread

THE COUNT, BECAUSE IT HAS BEEN WRONG THREE TIMES IN ONE DAY
-----------------------------------------------------------
G4 Part A says four. A reconnaissance pass said eight. Both are wrong, and the
number of live defects in the ORDER PATH is **three** — A1, A2, A3 above.
Checked one at a time, against the code rather than against the prompt:

  * A4 (`.v2.odd_lot`)  ALREADY FIXED; see the last test in this file.
  * A5 (multiplier 1.0) NOT A DEFECT. Both sites sit behind an explicit
    `kind != OPTION` guard -- `ibkr.py:642` returns None for a weight-expressed
    option BEFORE reaching :650, and the min-trade block at :1062 excludes
    OPTION by name. An option never reads either default, and 1.0 is correct
    for the kinds that do.
  * A7 (`leg.ratio`)    NOT A DEFECT. IB combo semantics are
    `contracts = ratio x package quantity`, so ratio 5 on a 1-unit package IS
    a 5-lot straddle. `test_combo_ratio_and_quantity_multiply_to_the_intended_size`
    pins that invariant and PASSES TODAY; it is a regression guard, not a fix.
    The residual is `int(abs(delta))` truncating a fractional delta, which
    cannot arise while contracts are integral -- guarded below rather than
    "fixed".

NO BROKER, NO NETWORK. `IBKRBroker` is built with `__new__` and only the
attributes under test are set by hand, the same construction
`test_arm_attribution.py` uses. `ib` is a stub that records what it was asked to
place and places nothing.

THE DESIGN QUESTION THESE TESTS SETTLE
--------------------------------------
The bond path (`ibkr.py:566-572`) meets the identical situation — a leg with no
usable limit price — and chooses to WARN AND SKIP. G4 says options must RAISE.
Both are right, and they are reconciled by WHERE the raise happens: validating
every option target BEFORE the first `placeOrder` means a raise cannot leave a
half-transmitted basket, which is the thing the bond path's author was avoiding.
`test_invalid_option_transmits_nothing_at_all` is the test that pins it, and it
is the most important one in this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.broker.ibkr import IBKRBroker  # noqa: E402
from src.deploy.sleeve import LONG, OPTION, SHORT, PositionTarget  # noqa: E402


# -- stubs ----------------------------------------------------------------

class _Order:
    """Records what an order would have been, without an ib_async install."""

    def __init__(self, action="", qty=0.0, orderType="", lmtPrice=None):
        self.action = action
        self.totalQuantity = qty
        self.orderType = orderType
        self.lmtPrice = lmtPrice
        self.tif = ""
        self.orderRef = ""


class _ComboLeg:
    def __init__(self):
        self.conId = None
        self.ratio = None
        self.action = None
        self.exchange = None


class _Contract:
    def __init__(self, **kw):
        self.conId = 0
        self.comboLegs = []
        for k, v in kw.items():
            setattr(self, k, v)


class _Option(_Contract):
    def __init__(self, underlier, expiry, strike, right, exchange="SMART",
                 multiplier="100"):
        super().__init__()
        self.symbol = underlier
        self.lastTradeDateOrContractMonth = expiry
        self.strike = float(strike)
        self.right = right
        self.exchange = exchange
        self.multiplier = multiplier
        self.secType = "OPT"
        self.conId = 0            # UNQUALIFIED, exactly as ib_async leaves it


class _Stock(_Contract):
    def __init__(self, symbol, exchange="SMART", currency="USD"):
        super().__init__()
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self.secType = "STK"


class _IbInsync:
    """The handful of ib_async constructors the order path calls."""

    Contract = _Contract
    Option = _Option
    ComboLeg = _ComboLeg
    Stock = _Stock

    @staticmethod
    def LimitOrder(action, qty, lmt):
        return _Order(action, qty, "LMT", float(lmt))

    @staticmethod
    def MarketOrder(action, qty):
        return _Order(action, qty, "MKT", None)

    @staticmethod
    def Order():
        return _Order()


class _StubIB:
    """Records placements. Qualification is opt-in so A1 can be tested both ways."""

    def __init__(self, qualify=True):
        self.placed = []
        self._qualify = qualify
        self.qualify_calls = 0

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        trade = type("T", (), {})()
        trade.order = order
        trade.contract = contract
        trade.fills = []
        trade.orderStatus = type("S", (), {"status": "Submitted"})()
        return trade

    def qualifyContracts(self, *contracts):
        self.qualify_calls += 1
        if not self._qualify:
            return []                       # IB's real "could not resolve" answer
        for i, c in enumerate(contracts, start=1):
            c.conId = 1000 + i
        return list(contracts)


def _broker(qualify=True):
    b = IBKRBroker.__new__(IBKRBroker)
    b._ib_insync = _IbInsync()
    b.ib = _StubIB(qualify=qualify)
    b._sleeves = {}
    return b


def _opt(instrument="HYG_P78", strike=78.0, right="P", side=LONG, qty=2.0,
         combo_id=None, **meta):
    m = {"underlier": "HYG", "expiry": "20261120", "strike": strike,
         "opt_type": right}
    m.update(meta)
    return PositionTarget(instrument=instrument, side=side, kind=OPTION,
                          qty=qty, combo_id=combo_id, meta=m)


# -- A2: the $0.00 limit --------------------------------------------------

def test_option_without_limit_price_is_refused_not_priced_at_zero():
    """THE defect. A missing key produced `LimitOrder(action, qty, 0.0)`.

    A buy at a $0.00 limit can never fill; a SELL at a $0.00 limit is an offer
    to sell at any price the book will pay. The bond path refuses in exactly
    this situation (`ibkr.py:566-572`, "bonds are LIMIT-ONLY"); options did not.
    """
    b = _broker()
    with pytest.raises(ValueError) as exc:
        b._order(_opt(), 2.0)
    assert "HYG_P78" in str(exc.value), "the refusal must name the instrument"
    assert "limit_price" in str(exc.value)


@pytest.mark.parametrize("bad", [0.0, -1.0, "", None])
def test_option_limit_price_must_be_positive(bad):
    """Zero, negative, empty and None are all "no price", not a price."""
    b = _broker()
    with pytest.raises(ValueError):
        b._order(_opt(limit_price=bad), 2.0)


def test_option_with_a_real_limit_price_still_works():
    """The positive control: a valid target must still produce a limit order.

    Without this, the refusal above would pass on a path that refused
    everything.
    """
    b = _broker()
    o = b._order(_opt(limit_price=1.23), 2.0)
    assert o.orderType == "LMT"
    assert o.lmtPrice == pytest.approx(1.23)
    assert o.action == "BUY" and o.totalQuantity == 2.0


def test_option_sell_side_direction_is_preserved():
    b = _broker()
    o = b._order(_opt(side=SHORT, qty=-2.0, limit_price=1.23), -2.0)
    assert o.action == "SELL" and o.totalQuantity == 2.0


# -- A1: conId = 0 --------------------------------------------------------

def test_no_combo_leg_reaches_the_broker_with_conid_zero():
    """`ib_async.Option(...)` has conId == 0 until qualifyContracts resolves it.

    `qualifyContracts` appeared NOWHERE in src/ (verified by grep), so every
    BAG order this repo could build carried unresolved legs. IB rejects or,
    worse, mis-resolves them.
    """
    b = _broker(qualify=True)
    legs = [(_opt("HYG_P78", 78.0, "P", combo_id="c1", limit_price=1.10), 2.0),
            (_opt("HYG_C80", 80.0, "C", combo_id="c1", limit_price=0.90), 2.0)]
    b._place_combo("c1", legs, "gamma_scalp")
    assert b.ib.qualify_calls > 0, "qualifyContracts was never called"
    contract, _ = b.ib.placed[0]
    assert contract.comboLegs, "no combo legs were attached"
    for leg in contract.comboLegs:
        assert leg.conId, f"leg reached placeOrder with conId={leg.conId!r}"


def test_qualification_failure_raises_rather_than_sending_a_zero():
    """When IB cannot resolve the contract, proceeding with 0 is the bug."""
    b = _broker(qualify=False)
    legs = [(_opt("HYG_P78", 78.0, "P", combo_id="c1", limit_price=1.10), 2.0)]
    with pytest.raises(ValueError) as exc:
        b._place_combo("c1", legs, "gamma_scalp")
    assert "qualif" in str(exc.value).lower()
    assert not b.ib.placed, "an order was transmitted after a failed qualification"


# -- A3 + A7: the package order -------------------------------------------

def test_combo_package_is_a_limit_not_a_market_order():
    """A MarketOrder on a two-leg option spread crosses two spreads at once.

    Single option legs were limit-only by design; the combo path contradicted
    that in the same class. The package limit comes from the legs' own
    limit_price meta, which is our surface's mid, never the broker's.
    """
    b = _broker()
    legs = [(_opt("HYG_P78", 78.0, "P", combo_id="c1", limit_price=1.10), 2.0),
            (_opt("HYG_C80", 80.0, "C", combo_id="c1", limit_price=0.90), 2.0)]
    b._place_combo("c1", legs, "gamma_scalp")
    _, order = b.ib.placed[0]
    assert order.orderType == "LMT", "the BAG went out as a market order"
    assert order.lmtPrice == pytest.approx(2.00), \
        "the package limit must be the sum of the legs' limits"


def test_combo_without_leg_limits_raises_before_transmitting():
    b = _broker()
    legs = [(_opt("HYG_P78", 78.0, "P", combo_id="c1", limit_price=1.10), 2.0),
            (_opt("HYG_C80", 80.0, "C", combo_id="c1"), 2.0)]     # no limit
    with pytest.raises(ValueError):
        b._place_combo("c1", legs, "gamma_scalp")
    assert not b.ib.placed


def test_combo_ratio_and_quantity_multiply_to_the_intended_size():
    """A7. `leg.ratio = int(abs(delta)) or 1` with `MarketOrder(action, 1)`.

    A 5-lot straddle became ratio 5 on a 1-unit package, which is only
    accidentally right, and truncates any fractional delta. The invariant that
    must hold whatever the encoding: ratio x package quantity == contracts.
    """
    b = _broker()
    legs = [(_opt("HYG_P78", 78.0, "P", combo_id="c1", limit_price=1.10), 5.0),
            (_opt("HYG_C80", 80.0, "C", combo_id="c1", limit_price=0.90), 5.0)]
    b._place_combo("c1", legs, "gamma_scalp")
    contract, order = b.ib.placed[0]
    for leg in contract.comboLegs:
        assert leg.ratio * float(order.totalQuantity) == pytest.approx(5.0), (
            f"ratio {leg.ratio} x qty {order.totalQuantity} != 5 contracts")


def test_combo_direction_follows_the_legs():
    b = _broker()
    legs = [(_opt("HYG_P78", 78.0, "P", side=SHORT, qty=-3.0, combo_id="c1",
                  limit_price=1.10), -3.0),
            (_opt("HYG_C80", 80.0, "C", side=SHORT, qty=-3.0, combo_id="c1",
                  limit_price=0.90), -3.0)]
    b._place_combo("c1", legs, "gamma_scalp")
    _, order = b.ib.placed[0]
    assert order.action == "SELL"


# -- A5: the multiplier ---------------------------------------------------

def test_option_multiplier_helper_defaults_to_one_hundred():
    """One definition of "a contract is 100 shares", for the notional cap.

    `exec_ledger._multiplier` already defaults OPTION to 100.0. This is the
    same rule on the broker side, needed by `max_underlying_notional_usd` in
    the gamma sleeve. It is NOT a defect fix -- see the header on A5.
    """
    from src.deploy.broker import ibkr as M
    assert M._option_multiplier(_opt()) == pytest.approx(100.0)
    assert M._option_multiplier(_opt(multiplier=10)) == pytest.approx(10.0)


def test_the_two_1x_multiplier_defaults_are_unreachable_for_options():
    """A5 withdrawn, pinned as behaviour so it cannot be "fixed" wrongly.

    `_resolve_qty` returns None for a weight-expressed option before it reaches
    the 1.0 default, and the min-trade block excludes OPTION by name. Someone
    changing those 1.0s to 100.0 would be changing the SHARE path, which is
    live on three books today.
    """
    b = _broker()
    weighted = PositionTarget(instrument="HYG_P78", side=LONG, kind=OPTION,
                              weight=0.1,
                              meta={"underlier": "HYG", "expiry": "20261120",
                                    "strike": 78.0, "opt_type": "P"})
    assert b._resolve_qty(weighted, None, None, "gamma_scalp") is None


# -- the design question --------------------------------------------------

def test_invalid_option_transmits_nothing_at_all():
    """THE most important test here: a raise must not half-send a basket.

    The bond path chose warn-and-skip precisely because raising in the middle
    of the placement loop leaves some legs at the broker and some not — which
    on a straddle is a naked position. Validating every option target BEFORE
    the first placeOrder reconciles G4's "raise" with that concern.

    Three legs, the second invalid. ZERO orders may reach the broker.
    """
    b = _broker()
    targets = [_opt("HYG_P78", 78.0, "P", limit_price=1.10),
               _opt("HYG_C80", 80.0, "C"),                   # no limit_price
               _opt("HYG_P76", 76.0, "P", limit_price=0.55)]
    with pytest.raises(ValueError):
        b._validate_option_targets(targets)
    assert not b.ib.placed, (
        "orders were transmitted before validation failed — a raise mid-loop "
        "leaves a half-sent basket, which on a straddle is a naked leg")


def test_validation_passes_a_well_formed_basket():
    b = _broker()
    targets = [_opt("HYG_P78", 78.0, "P", limit_price=1.10),
               _opt("HYG_C80", 80.0, "C", limit_price=0.90)]
    b._validate_option_targets(targets)            # must not raise


def test_validation_requires_the_contract_keys():
    """`_contract` does a bare meta[...] lookup — a KeyError at placement time.

    Missing underlier/expiry/strike/opt_type must be caught in validation, with
    the instrument named, not discovered as a KeyError one line before transmit.
    """
    b = _broker()
    bad = PositionTarget(instrument="HYG_P78", side=LONG, kind=OPTION, qty=1.0,
                         meta={"underlier": "HYG", "limit_price": 1.0})
    with pytest.raises(ValueError) as exc:
        b._validate_option_targets([bad])
    assert "HYG_P78" in str(exc.value)


def test_shares_are_untouched_by_option_validation():
    """The inertness proof, in miniature: a share target is not an option.

    Every book trading today is shares-only. Validation must be a no-op for
    them — this is the unit-level half of the byte-for-byte dry-run diff.
    """
    b = _broker()
    share = PositionTarget(instrument="HYG", side=LONG, qty=100.0)
    b._validate_option_targets([share])            # must not raise
    o = b._order(share, 100.0)
    assert o.orderType == "MKT"


# -- the withdrawn defect -------------------------------------------------

def test_g4_part_a4_is_already_fixed():
    """G4 Part A4, G0 §5 and G2 Part D all claim a live `.v2.odd_lot` import.

    It is not live and has not been for some time: the module is imported from
    `.lib.odd_lot`, `src/deploy/v2` does not exist, and `src/deploy/lib/odd_lot.py`
    does. This test exists so the claim cannot be re-asserted from the prompts
    without something failing, and so the next reader does not spend an hour
    hunting a defect that was fixed before they arrived.
    """
    src = (REPO / "src/deploy/exec_ledger.py").read_text()
    assert "from .lib.odd_lot import" in src
    assert ".v2.odd_lot" not in src
    assert not (REPO / "src/deploy/v2").exists()
    assert (REPO / "src/deploy/lib/odd_lot.py").exists()


# -- the WIRING, not just the validator -----------------------------------

def test_place_targets_validates_before_transmitting_anything():
    """The wiring test. Calling the validator directly does not prove it is CALLED.

    WHY THIS EXISTS SEPARATELY FROM `test_invalid_option_transmits_nothing_at_all`.
    That test exercises `_validate_option_targets` in isolation, so it keeps
    passing if the call is deleted from `place_targets` — verified, it did. This
    is the same defect shape as the W14 harness test on 2026-09-11 that passed
    under the very regression it was written to catch. A guard that shares its
    entry point with the thing it guards is not a guard.

    So: drive the real `place_targets` with a three-leg basket whose middle leg
    has no `limit_price`, and assert the broker received NOTHING.
    """
    b = _broker()
    b._armed = True
    b._live_positions = {"gamma_scalp": {}}
    b._bond_instruments = set()
    b._refuse_if_ledger_is_behind = lambda *a, **k: None
    b._record_order_attribution = lambda *a, **k: None
    b._fills_from_trade = lambda *a, **k: []

    targets = [_opt("HYG_P78", 78.0, "P", limit_price=1.10),
               _opt("HYG_C80", 80.0, "C"),                    # no limit_price
               _opt("HYG_P76", 76.0, "P", limit_price=0.55)]

    with pytest.raises(ValueError) as exc:
        b.place_targets("gamma_scalp", targets, "2026-09-11", None)
    assert "HYG_C80" in str(exc.value)
    assert not b.ib.placed, (
        "place_targets transmitted before validating. A raise partway through "
        "the placement loop leaves a naked leg at the broker — which is the "
        "reason the bond path chose warn-and-skip instead of raising.")


def test_place_targets_still_sends_a_well_formed_option_basket():
    """Positive control: the wiring must not refuse everything."""
    b = _broker()
    b._armed = True
    b._live_positions = {"gamma_scalp": {}}
    b._bond_instruments = set()
    b._refuse_if_ledger_is_behind = lambda *a, **k: None
    b._record_order_attribution = lambda *a, **k: None
    b._fills_from_trade = lambda *a, **k: []

    targets = [_opt("HYG_P78", 78.0, "P", limit_price=1.10),
               _opt("HYG_C80", 80.0, "C", limit_price=0.90)]
    b.place_targets("gamma_scalp", targets, "2026-09-11", None)
    assert len(b.ib.placed) == 2
    for _, order in b.ib.placed:
        assert order.orderType == "LMT" and order.lmtPrice > 0
