"""`MarketState.extras["nav_hold"]`: a name the stale-NAV gate could not verify keeps its shares.

THE RULING (team lead 2026-10-13, the redesign): a name whose NAV is still
unverified at the final pre-send check KEEPS ITS CURRENT SHARES -- no order in
it -- and leaves the cross-section. It is never targeted to zero, and the gate's
holds can never trigger the `min_names` flatten (the sleeve's FLAT-everything
rule, which decide turns into orders closing the book). Why: the first
version dropped such names, and its replay on the laptop's sessions left 4
eligible names on 2026-10-05 -- the whole book closed on a missing CEFConnect
row (docs/REFERENCES.md §12s).

WHAT EACH TEST WOULD HAVE CAUGHT:

  1. THE NO-OP. Absent and an empty name list are byte-identical, on the real
     panels (live spec, pinned and latest dates, flat and held books) and on the
     synthetic panel. The proof against the sleeve BEFORE the gate (225f459) was
     run by loading both versions on the same panels; it is in the commit message.
  2. HELD AT CURRENT SHARES. A held name's target is its exact share count, so
     decide sends nothing in it; an unheld one is FLAT, 0 against 0, nothing
     sent. The other names' weights are exactly those of the same sleeve without
     the name in its universe: it left the cross-section and nothing else moved.
  3. NO FLATTEN FROM HOLDS. Holds that leave fewer than `min_names` make the
     whole book hold (decide: no order at all), where the first version emitted
     every name FLAT. Fewer than `min_names` WITHOUT the holds is today's rule,
     unchanged, except that the held names still keep their shares.
  4. REFUSAL. A malformed extra, a ticker outside the universe, or a gate run
     for another day than the signal date raises.
"""
import datetime as dt
import json
import math

import pandas as pd
import pytest

from quantt.session import decide as dec
from src.deploy.sleeve import FLAT, LONG, SHORT, MarketState
from src.deploy.sleeves import cef_discount as cefmod
from src.deploy.sleeves.cef_discount import CEFDiscountSleeve
from src.deploy.tests.test_group_cap import (
    NAV_USD as SYN_NAV,
    TICKERS,
    _fingerprint,
    _spec as _syn_spec,
    _write_panel,
)
from src.deploy.tests.test_opening_session import (
    LIVE_NAV,
    LIVE_SPEC,
    _held_book,
    _pinned_dates,
    _real_close,
    _real_dates,
    needs_panel,
)

ABSENT = object()


def _run(spec, nav, asof, holdings=None, names=ABSENT, gate_date=None):
    extras = {"sleeve_nav": nav}
    if names is not ABSENT:
        extras["nav_hold"] = {"asof": gate_date or asof, "names": names}
    sl = CEFDiscountSleeve(spec, nav)
    ms = MarketState(asof=pd.Timestamp(asof), prices=pd.DataFrame(),
                     holdings=dict(holdings or {}), extras=extras)
    return sl.target_positions(pd.Timestamp(asof), ms)


def _weights(targets):
    return {t.instrument: float(t.weight) for t in targets
            if t.side != FLAT and t.weight is not None}


def _orders(targets, holdings, close, universe):
    """What decide would send for these targets against these whole-share holdings."""
    d = dec.decide(targets, {k: int(v) for k, v in holdings.items()}, SYN_NAV, close,
                   {t: True for t in universe}, session_date=dt.date(2026, 1, 2),
                   universe=universe, cid_prefix="t", min_trade_usd=0.0)
    return {o.symbol: o.signed_qty for o in d.orders}


def _signal_date(asof):
    """The date the sleeve decides on: the last date <= asof with both a close
    and a NAV (it inner-joins them)."""
    P = pd.read_parquet(cefmod.PX_PATH, columns=["date", "ticker"])
    N = pd.read_parquet(cefmod.NAV_PATH, columns=["date", "ticker"])
    d = pd.to_datetime(P.merge(N, on=["date", "ticker"])["date"])
    return str(d[d <= pd.Timestamp(asof)].max().date())


# ---------------------------------------------------------------------------
# 1. the no-op
# ---------------------------------------------------------------------------

def test_synthetic_absent_and_empty_are_byte_identical(tmp_path, monkeypatch):
    asof, close = _write_panel(tmp_path, monkeypatch)
    for spec in (_syn_spec(), _syn_spec(group_cap=0.30, max_gross_stress=1.90)):
        held = _held_book(_run(spec, SYN_NAV, asof), SYN_NAV, close)
        assert held
        for holdings in ({}, held):
            a = _fingerprint(_run(spec, SYN_NAV, asof, holdings))
            assert a and a == _fingerprint(_run(spec, SYN_NAV, asof, holdings, names={}))


@needs_panel
@pytest.mark.parametrize("asof", sorted(set(_pinned_dates() + _real_dates()))
                         if cefmod.PX_PATH.exists() else [])
def test_real_panel_absent_and_empty_are_byte_identical(asof):
    held = _held_book(_run(LIVE_SPEC, LIVE_NAV, asof, {}), LIVE_NAV, _real_close(asof))
    gate_date = _signal_date(asof)
    for holdings in ({}, held):
        a = _fingerprint(_run(LIVE_SPEC, LIVE_NAV, asof, holdings))
        assert a, "emitted nothing; the comparison would be vacuous"
        assert a == _fingerprint(_run(LIVE_SPEC, LIVE_NAV, asof, holdings, names={},
                                      gate_date=gate_date))


# ---------------------------------------------------------------------------
# 2. held at current shares, out of the cross-section
# ---------------------------------------------------------------------------

def test_a_held_name_keeps_its_shares_and_leaves_the_cross_section(tmp_path, monkeypatch):
    asof, close = _write_panel(tmp_path, monkeypatch)
    spec = _syn_spec()
    big = math.floor(0.10 * SYN_NAV / close["TAX1"])          # outside the band
    held = {"TAX1": float(big), "MUN1": -float(math.floor(0.08 * SYN_NAV / close["MUN1"]))}
    got = {t.instrument: t for t in _run(spec, SYN_NAV, asof, held,
                                         names={"TAX1": "r", "TAX2": "r"})}
    assert got["TAX1"].side == LONG and got["TAX1"].qty == float(big)
    assert got["TAX1"].reason == "cef: held, NAV unverified: r"
    assert got["TAX2"].side == FLAT and got["TAX2"].reason == "cef: not opened, NAV unverified: r"
    orders = _orders(list(got.values()), held, close, TICKERS)
    assert "TAX1" not in orders and "TAX2" not in orders
    # Nothing else moved: the same sleeve without TAX1 and TAX2 in its universe.
    without = json.loads(json.dumps(spec))
    without["frozen"]["universe"] = [x for x in TICKERS if x not in ("TAX1", "TAX2")]
    ref = {t.instrument: (t.side, t.qty, t.weight)
           for t in _run(without, SYN_NAV, asof, {"MUN1": held["MUN1"]})}
    assert {k: (t.side, t.qty, t.weight) for k, t in got.items()
            if k not in ("TAX1", "TAX2")} == ref


# ---------------------------------------------------------------------------
# 3. no min_names flatten from holds
# ---------------------------------------------------------------------------

def test_holds_never_trigger_the_min_names_flatten(tmp_path, monkeypatch):
    asof, close = _write_panel(tmp_path, monkeypatch)
    spec = _syn_spec()
    held = _held_book(_run(spec, SYN_NAV, asof), SYN_NAV, close)
    assert len(held) >= 6
    keep = int(spec["frozen"]["min_names"]) - 1
    names = {t: "r" for t in TICKERS[keep:]}             # leaves min_names - 1 eligible
    got = _run(spec, SYN_NAV, asof, held, names=names)
    for t in got:
        q = held.get(t.instrument, 0.0)
        assert (t.qty == q) if q else (t.side == FLAT), t
        assert "book holds" in t.reason
    assert _orders(got, held, close, TICKERS) == {}, "the book must stand still, not close"


def test_short_of_min_names_without_the_holds_is_todays_rule_but_held_names_hold(
        tmp_path, monkeypatch):
    asof, close = _write_panel(tmp_path, monkeypatch)
    spec = _syn_spec()
    spec["frozen"]["min_names"] = len(TICKERS) + 1          # short whatever the gate does
    held = {"TAX1": 100.0, "MUN1": -100.0}
    assert {t.reason for t in _run(spec, SYN_NAV, asof, held)} == \
        {f"cef: only {len(TICKERS)} eligible names"}       # today's rule, unchanged
    got = {t.instrument: t for t in _run(spec, SYN_NAV, asof, held, names={"TAX1": "r"})}
    assert got["TAX1"].qty == 100.0 and got["TAX1"].reason == "cef: held, NAV unverified: r"
    assert got["MUN1"].side == FLAT and got["MUN1"].qty is None      # today's FLAT


# ---------------------------------------------------------------------------
# 4. refusal
# ---------------------------------------------------------------------------

def test_a_gate_run_for_another_day_raises(tmp_path, monkeypatch):
    asof, _ = _write_panel(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="gate checked"):
        _run(_syn_spec(), SYN_NAV, asof, names={"TAX1": "r"}, gate_date="2020-01-02")


@pytest.mark.parametrize("bad", [
    {"names": {"TAX1": "r"}},                              # no date
    {"asof": "D", "names": ["TAX1"]},                      # not a mapping
    {"asof": "D", "names": {"TAX1": ""}},                  # no reason
    {"asof": "D", "names": {"NOPE": "r"}},                 # not in the universe
    "TAX1",
])
def test_a_malformed_extra_raises(tmp_path, monkeypatch, bad):
    asof, _ = _write_panel(tmp_path, monkeypatch)
    if isinstance(bad, dict) and bad.get("asof") == "D":
        bad = {**bad, "asof": asof}
    sl = CEFDiscountSleeve(_syn_spec(), SYN_NAV)
    ms = MarketState(asof=pd.Timestamp(asof), prices=pd.DataFrame(), holdings={},
                     extras={"sleeve_nav": SYN_NAV, "nav_hold": bad})
    with pytest.raises(ValueError):
        sl.target_positions(pd.Timestamp(asof), ms)


def test_an_unreadable_holding_of_a_held_name_raises(tmp_path, monkeypatch):
    asof, _ = _write_panel(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="cannot hold"):
        _run(_syn_spec(), SYN_NAV, asof, {"TAX1": float("nan")}, names={"TAX1": "r"})
