"""`MarketState.extras["nav_unverified"]`: the runner's stale-NAV gate drops a name for the day.

WHY (team lead 2026-10-13, "Use CEFConnect, else drop"): Yahoo serves a NAV row
dated D carrying D-1's NAV; on the laptop's paper sessions 28 of 73 checkable
name-days were decided on one (results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5).
The runner (`quantt/session/nav_gate.py`) checks every repeat against
CEFConnect and names the ones it could not verify; the sleeve drops them on the
path `max_nav_age_bd` uses.

WHAT EACH TEST WOULD HAVE CAUGHT:

  1. THE NO-OP. A new input on the live path must be today's behaviour when
     absent, proved byte for byte. Absent and an empty name list are compared
     on the REAL panels (the live spec, pinned and latest dates, a flat and a
     held book) and on the synthetic panel of `test_group_cap.py`. The proof
     against the sleeve BEFORE this change (commit 225f459) was run once, by
     loading both versions on the same panels; it is in the commit message.
  2. A DROP IS A DROP, NOT A NEW RULE. The other names' weights are exactly
     those of the same sleeve with the dropped name removed from the universe:
     the name left the cross-section and nothing else moved.
  3. WHAT A DROP DOES TO A HELD NAME (the sleeve's existing rule, pinned so the
     consequence is visible): target zero, so the band holds a position inside
     `band_width` and trades one outside it to the band EDGE.
  4. min_names (existing rule, pinned): drops that leave fewer than `min_names`
     eligible names make EVERY target FLAT ("only N eligible names"), before the
     band -- a held book is then closed by decide. Not new behaviour; recorded
     because the gate can now cause it.
  5. REFUSAL. A malformed extra, a ticker outside the universe, or a gate run
     for another day than the signal date raises.
"""
import json
import math

import pandas as pd
import pytest

from src.deploy.sleeve import FLAT, LONG, MarketState
from src.deploy.sleeves import cef_discount as cefmod
from src.deploy.sleeves.cef_discount import CEFDiscountSleeve
from src.deploy.tests.test_group_cap import (
    BAND,
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
        extras["nav_unverified"] = {"asof": gate_date or asof, "names": names}
    sl = CEFDiscountSleeve(spec, nav)
    ms = MarketState(asof=pd.Timestamp(asof), prices=pd.DataFrame(),
                     holdings=dict(holdings or {}), extras=extras)
    return sl.target_positions(pd.Timestamp(asof), ms)


def _weights(targets):
    return {t.instrument: float(t.weight) for t in targets
            if t.side != FLAT and t.weight is not None}


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


def _signal_date(asof):
    """The date the sleeve decides on: the last date <= asof with both a close
    and a NAV (it inner-joins them). On the local panel the price runs a session
    past the NAV, so for the last price date this is the session before."""
    P = pd.read_parquet(cefmod.PX_PATH, columns=["date", "ticker"])
    N = pd.read_parquet(cefmod.NAV_PATH, columns=["date", "ticker"])
    d = pd.to_datetime(P.merge(N, on=["date", "ticker"])["date"])
    return str(d[d <= pd.Timestamp(asof)].max().date())


@needs_panel
@pytest.mark.parametrize("asof", sorted(set(_pinned_dates() + _real_dates()))
                         if cefmod.PX_PATH.exists() else [])
def test_real_panel_absent_and_empty_are_byte_identical(asof):
    day_one = _run(LIVE_SPEC, LIVE_NAV, asof, {})
    held = _held_book(day_one, LIVE_NAV, _real_close(asof))
    gate_date = _signal_date(asof)
    for holdings in ({}, held):
        a = _fingerprint(_run(LIVE_SPEC, LIVE_NAV, asof, holdings))
        assert a, "emitted nothing; the comparison would be vacuous"
        assert a == _fingerprint(_run(LIVE_SPEC, LIVE_NAV, asof, holdings, names={},
                                      gate_date=gate_date))


# ---------------------------------------------------------------------------
# 2. a drop is the name leaving the cross-section, nothing else
# ---------------------------------------------------------------------------

def test_a_dropped_name_leaves_the_cross_section_and_nothing_else_moves(tmp_path, monkeypatch):
    asof, _ = _write_panel(tmp_path, monkeypatch)
    spec = _syn_spec()
    got = _run(spec, SYN_NAV, asof, names={"TAX1": "NAV 2025 10.00 = NAV prev 10.00; "
                                                    "CEFConnect has no NAV dated D"})
    t = {x.instrument: x for x in got}["TAX1"]
    assert t.side == FLAT and t.reason.startswith("cef: NAV unverified: NAV 2025 10.00")
    without = json.loads(json.dumps(spec))
    without["frozen"]["universe"] = [x for x in TICKERS if x != "TAX1"]
    ref = _weights(_run(without, SYN_NAV, asof))
    assert ref and _weights(got) == ref, "dropping one name moved the others differently " \
                                         "from removing it"
    assert _weights(got) != _weights(_run(spec, SYN_NAV, asof)), "the drop changed nothing"


# ---------------------------------------------------------------------------
# 3. a held name: target zero, then the band
# ---------------------------------------------------------------------------

def test_a_dropped_held_name_is_banded_toward_zero(tmp_path, monkeypatch):
    asof, close = _write_panel(tmp_path, monkeypatch)
    spec = _syn_spec()                                  # band on, no gross cap
    big = math.floor(0.10 * SYN_NAV / close["TAX1"])    # held weight ~ +0.10 > band
    small = math.floor(0.03 * SYN_NAV / close["TAX2"])  # held weight ~ +0.03 < band
    held = {"TAX1": float(big), "TAX2": float(small)}
    got = {x.instrument: x for x in _run(spec, SYN_NAV, asof, held,
                                         names={"TAX1": "r", "TAX2": "r"})}
    assert got["TAX1"].side == LONG and got["TAX1"].weight == pytest.approx(BAND, abs=1e-12), \
        "outside the band: traded to the band edge"
    assert got["TAX2"].qty == float(small) and "band hold" in got["TAX2"].reason, \
        "inside the band: held, not traded"


# ---------------------------------------------------------------------------
# 4. min_names: the existing rule, unchanged
# ---------------------------------------------------------------------------

def test_drops_below_min_names_make_every_target_flat(tmp_path, monkeypatch):
    asof, close = _write_panel(tmp_path, monkeypatch)
    spec = _syn_spec()
    held = _held_book(_run(spec, SYN_NAV, asof), SYN_NAV, close)
    keep = int(spec["frozen"]["min_names"]) - 1
    names = {t: "r" for t in TICKERS[keep:]}           # leaves min_names - 1 eligible
    got = _run(spec, SYN_NAV, asof, held, names=names)
    assert all(t.side == FLAT and t.qty is None and t.weight is None for t in got)
    assert {t.reason for t in got} == {f"cef: only {keep} eligible names"}
    assert any(q for q in held.values()), "the held book was empty; the case is vacuous"


# ---------------------------------------------------------------------------
# 5. refusal
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
                     extras={"sleeve_nav": SYN_NAV, "nav_unverified": bad})
    with pytest.raises(ValueError):
        sl.target_positions(pd.Timestamp(asof), ms)
