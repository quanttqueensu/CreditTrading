"""nav_gate_replay's per-name rules: which decides count as a repeat, and which names were eligible.

The replay (report only) says how often the 2026-10-13 stale-NAV gate would
have bound on the laptop's sessions. Its judgements are which NAV(D) the
session used, from the z it printed, and whether that NAV triggers the gate;
these pin them on literal numbers. No network: the fetchers are never called.
"""
import numpy as np

from scripts.data import nav_gate_replay as rp


def _z(close, nav, mu, sd):
    return round((100.0 * (close - nav) / nav - mu) / sd, 2)


def test_a_z_computed_on_the_previous_nav_identifies_the_stale_copy():
    close, mu, sd, final, prev = 14.20, -5.0, 1.5, 15.04, 14.98
    assert rp.identify(_z(close, prev, mu, sd), close, mu, sd, final, prev) == "prev"
    assert rp.identify(_z(close, final, mu, sd), close, mu, sd, final, prev) == "final"
    assert rp.identify(np.nan, close, mu, sd, final, prev) == "no z"
    assert rp.identify(-4.0, close, mu, sd, final, prev) == "no z"          # clipped


def test_the_replay_triggers_as_the_gate_does():
    """Both triggers: the panel's previous NAV, and CEFConnect's NAV(D-1) (the
    reviewer's PDI case: 15.06 against a previous row of 15.12)."""
    assert rp.trigger_of(15.06, 15.12, 15.06) == "cc_prev"
    assert rp.trigger_of(10.00, 10.00, 9.98) == "yf_repeat"
    assert rp.trigger_of(20.00, 20.00, 20.00) == "yf_repeat+cc_prev"
    assert rp.trigger_of(15.10, 15.06, None) == ""


def test_only_the_sleeves_own_drops_are_ineligible():
    assert not rp.eligible("cef: illiquid gmax=1.8000")
    assert not rp.eligible("cef: only 5 eligible names")
    assert rp.eligible("cef: below min weight gmax=1.8000")      # band zero, still in the row
    assert rp.eligible("cef band hold: |gap|<=0.0480 w=+0.1656")
