"""A no-trade-band HOLD must cost exactly nothing to hold.

THE BUG THESE TESTS PIN (results/cef/DUST_ORDERS_2026-09.md). The band decides
in WEIGHT space: it reads the held weight as `q * px[-1] / nav` off the last
close in the signal panel, finds the gap inside the band, and said "hold" by
returning that same weight as the target. The executor then converted the
weight back to shares with `floor(nav * |w| / price)` — using the close it
reads on the SIZING date, which is routinely one session newer, because price
and NAV are inner-joined and a fund's NAV publishes after its close. Different
price, different floor, and twelve names the band had told us to leave alone
emitted a few shares each as live MOC orders: $3,019 gross on the 2026-09-03
signal, ~$15/session of commission and half-spread, ~0.75%/yr of a $500k book
against a policy whose whole expectation is ~2.3%/yr — and every one of them
counted against the band's pre-registered turnover readout.

The fix is at the source: a HOLD is expressed in SHARES, so the executor's diff
is exactly zero whatever close it sizes on. These tests hand the executor a
sizing close 1% away from the signal close — far more than the drift that
produced the real dust — and require silence.

Synthetic panel throughout, in the house style of src/backtest/tests: the
mechanism must be provably correct on toy inputs, independent of whatever the
live parquet happens to hold today.
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.deploy import exec_ledger
from src.deploy.exec_ledger import LongOnlySleeveLedger, _target_shares_for
from src.deploy.sleeve import ETF, LONG, SHORT, MarketState, PositionTarget
from src.deploy.sleeves import cef_discount as cefmod
from src.deploy.sleeves.cef_discount import CEFDiscountSleeve

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
NAV_USD = 500_000.0
BAND = 0.048


def _spec(band=True, min_trade=0.0):
    """A CEF spec with the deployed knobs, band on or off.

    Values mirror ops/specs/cef_discount.frozen.json except `rebalance_days`,
    which is 1 here so that the band-off run signals on the SAME date as the
    band-on run (the calendar would otherwise anchor it up to a day earlier and
    the two runs would not be comparable).
    """
    spec = {
        "capital_usd": NAV_USD,
        "allocation": {"type": "cef_discount"},
        "rebalance": {"min_trade_usd": min_trade},
        "frozen": {
            "universe": list(TICKERS),
            "z_window": 252,
            "rebalance_days": 1,
            "vol_target_annual": 0.06,
            "min_adv_usd": 3_000_000.0,
            "max_nav_age_bd": 3,
            "min_names": 6,
            "min_abs_weight": 0.005,
            "gross_leverage": 1.0,
            "order_type": "MOC",
        },
        "risk": {},
    }
    if band:
        spec["frozen"]["band_width"] = BAND
    return spec


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """A price/NAV panel deep enough for a 252-day z-score, written to parquet.

    Each name gets a NAV random walk near $10 and an AR(1) discount around its
    own level, which is what the signal is built from; volume is set so every
    name clears `min_adv_usd` and none is dropped as illiquid.
    """
    rng = np.random.default_rng(20260908)
    dates = pd.bdate_range("2024-09-02", periods=330)
    px_rows, nav_rows = [], []
    for i, tk in enumerate(TICKERS):
        nav = 10.0 + np.cumsum(rng.normal(0.0, 0.02, len(dates)))
        d = np.zeros(len(dates))
        d[0] = -0.03 + 0.01 * i
        for t in range(1, len(dates)):
            d[t] = 0.97 * d[t - 1] + 0.03 * (-0.03 + 0.01 * i) + rng.normal(0, 0.004)
        close = nav * (1.0 + d)
        for dt, c, n in zip(dates, close, nav):
            px_rows.append({"date": dt, "ticker": tk, "close": float(c),
                            "volume": 1_000_000.0})
            nav_rows.append({"date": dt, "ticker": tk, "nav": float(n)})
    px_path = tmp_path / "px.parquet"
    nav_path = tmp_path / "nav.parquet"
    pd.DataFrame(px_rows).to_parquet(px_path)
    pd.DataFrame(nav_rows).to_parquet(nav_path)
    monkeypatch.setattr(cefmod, "PX_PATH", px_path)
    monkeypatch.setattr(cefmod, "NAV_PATH", nav_path)
    asof = str(dates[-1].date())
    signal_close = {r["ticker"]: r["close"] for r in px_rows
                    if r["date"] == dates[-1]}
    return asof, signal_close


def _targets(spec, asof, holdings):
    sl = CEFDiscountSleeve(spec, NAV_USD)
    ms = MarketState(asof=asof, prices=pd.DataFrame(), holdings=dict(holdings),
                     extras={"sleeve_nav": NAV_USD})
    return sl.target_positions(asof, ms)


def _book_at_target(spec_no_band, asof, signal_close):
    """The share book the frictionless weights imply at the SIGNAL close.

    Sized exactly as the executor sizes a weight target, so every name's held
    weight lands within one share of its target and the band must call all of
    them HOLD.
    """
    held = {}
    for pt in _targets(spec_no_band, asof, {}):
        if pt.weight is None or pt.weight == 0.0:
            continue
        price = signal_close[pt.instrument]
        mag = math.floor(NAV_USD * abs(float(pt.weight)) / price)
        held[pt.instrument] = float(-mag if pt.side == SHORT else mag)
    return held


def _orders(targets, held, close, spec, tmp_path):
    """Run the executor's diff — the sub-ledger the CEF book actually uses."""
    lg = LongOnlySleeveLedger(tmp_path / "ledger")
    return lg._make_orders(pd.Timestamp("2026-09-04"), targets, dict(held),
                           close, NAV_USD, spec, reason="test", verbose=False)


# ---------------------------------------------------------------------------
# 1. a HOLD sized on a different close must send nothing
# ---------------------------------------------------------------------------

def test_band_hold_is_qty_expressed_and_sends_no_order_on_a_newer_close(
        panel, tmp_path):
    asof, signal_close = panel
    held = _book_at_target(_spec(band=False), asof, signal_close)
    assert len(held) >= 6, "fixture must build a real book to hold"

    targets = _targets(_spec(), asof, held)
    holds = [t for t in targets if "band hold" in t.reason]
    assert len(holds) == len(held), "every held name should be inside the band"
    for t in holds:
        assert t.weight is None, f"{t.instrument} HOLD is still weight-expressed"
        assert t.qty == held[t.instrument]
        assert t.signed_qty() == held[t.instrument]

    # The sizing close is 1% away from the close the band decided on — two
    # orders of magnitude more drift than the real dust orders needed.
    sizing_close = {tk: px * 1.01 for tk, px in signal_close.items()}
    rows = _orders(targets, held, sizing_close, _spec(), tmp_path)
    assert rows == [], f"a band HOLD emitted {len(rows)} order(s): {rows}"

    # CONTROL: the same book, expressed the old way, is exactly how the dust
    # was produced. If this stops emitting orders the test above is vacuous.
    old_style = [
        PositionTarget(instrument=t.instrument, side=t.side, kind=ETF,
                       weight=t.signed_qty() * signal_close[t.instrument] / NAV_USD,
                       meta=dict(t.meta), reason=t.reason)
        if "band hold" in t.reason else t
        for t in targets]
    assert _orders(old_style, held, sizing_close, _spec(), tmp_path), (
        "weight-expressed HOLDs should still round-trip into dust orders")


# ---------------------------------------------------------------------------
# 2. a TRADE still trades
# ---------------------------------------------------------------------------

def test_band_trade_still_produces_the_expected_share_delta(panel, tmp_path):
    """Flattening one name puts its gap outside the band, so the sleeve must
    trade it back to the band EDGE — and the executor must send exactly the
    share delta that edge weight implies at the close it sizes on."""
    asof, signal_close = panel
    held = _book_at_target(_spec(band=False), asof, signal_close)
    traded = max(held, key=lambda tk: abs(held[tk] * signal_close[tk]))
    held_gap = dict(held)
    del held_gap[traded]                      # nothing held: gap = |target| > band

    targets = _targets(_spec(), asof, held_gap)
    pt = next(t for t in targets if t.instrument == traded)
    assert "band hold" not in pt.reason, "the flattened name must be a TRADE"
    assert pt.qty is None and pt.weight is not None, (
        "a TRADE stays weight-expressed: it is a statement about the book, not "
        "about a share count we already hold")

    sizing_close = {tk: px * 1.01 for tk, px in signal_close.items()}
    expected = math.floor(NAV_USD * abs(pt.weight) / sizing_close[traded])
    expected = -expected if pt.side == SHORT else expected

    rows = _orders(targets, held_gap, sizing_close, _spec(), tmp_path)
    assert [r["ticker"] for r in rows] == [traded], (
        f"expected exactly one order, in {traded}: {rows}")
    assert rows[0]["delta_shares"] == pytest.approx(expected)
    assert rows[0]["target_shares"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 3. the two executor mechanics the fix leans on
# ---------------------------------------------------------------------------

def test_short_qty_target_keeps_its_sign_through_the_sub_ledger():
    """`_target_shares_for` returned floor(|qty|) until 2026-09-08, when no
    sleeve had ever handed it a SHORT qty target. The CEF book's shadow ledger
    is this class, so that would have read a HOLD of -5,862 shares as a target
    of +5,862 and ordered 11,724 shares to "hold" the position."""
    short = PositionTarget(instrument="MHD", side=SHORT, kind=ETF, qty=-5862.0)
    long_ = PositionTarget(instrument="BIT", side=LONG, kind=ETF, qty=8137.0)
    assert _target_shares_for(short, 11.22, NAV_USD) == -5862.0
    assert _target_shares_for(long_, 11.88, NAV_USD) == 8137.0
    # and a qty target never consults the close: an unpriced HOLD is a hold,
    # not a flatten.
    assert _target_shares_for(short, float("nan"), NAV_USD) == -5862.0


def test_min_trade_usd_filters_the_small_order_and_keeps_the_large_one(tmp_path):
    """The belt-and-braces backstop, read from the same spec key the live
    broker now reads. $517 is the notional at which $1 of commission plus a
    10.67bp half-spread equals 30bp of the trade."""
    spec = _spec(min_trade=517.0)
    targets = [PositionTarget(instrument="AWF", side=LONG, kind=ETF, qty=1743.0),
               PositionTarget(instrument="BIT", side=LONG, kind=ETF, qty=8137.0)]
    close = {"AWF": 10.03, "BIT": 11.88}
    held = {"AWF": 1700.0, "BIT": 8000.0}          # $431 and $1,628 of delta
    rows = _orders(targets, held, close, spec, tmp_path)
    assert [r["ticker"] for r in rows] == ["BIT"]
    assert rows[0]["delta_shares"] == pytest.approx(137.0)


def test_ibkr_resolve_qty_never_prices_a_qty_target():
    """The live path's half of the same guarantee: a qty target returns the
    signed quantity without a price lookup, so a HOLD in a name the price store
    lags (HYT, landmine 7) is no longer 'cannot size weight target' — which the
    caller answers by sending nothing for that leg.

    Called unbound with `self=None` on purpose: passing no instance is the
    proof that neither the price store nor the sleeve NAV is consulted.
    """
    from src.deploy.broker.ibkr import IBKRBroker

    pt = PositionTarget(instrument="HYT", side=LONG, kind=ETF, qty=4598.0)
    ms = MarketState(asof="2026-09-04", prices=pd.DataFrame(), holdings={})
    assert IBKRBroker._resolve_qty(None, pt, ms, "2026-09-04", "cef_discount") == 4598.0

    short = PositionTarget(instrument="MHD", side=SHORT, kind=ETF, qty=-5862.0)
    assert IBKRBroker._resolve_qty(None, short, ms, "2026-09-04", "cef_discount") == -5862.0
