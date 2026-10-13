"""nav_gate_replay's per-name rules: which decides count as a repeat, and which names were eligible.

The replay (report only) says how often the 2026-10-13 stale-NAV gate would
have bound on the laptop's sessions. Its one judgement is whether NAV(D)
equalled NAV(D-1) at decide time, from the z the session printed; these pin
that judgement on literal numbers. No network: the fetchers are never called.
"""
import numpy as np

from scripts.data import nav_gate_replay as rp


def _z(close, nav, mu, sd):
    return round((100.0 * (close - nav) / nav - mu) / sd, 2)


def test_a_z_computed_on_the_previous_nav_is_a_stale_repeat():
    close, mu, sd, final, prev = 14.20, -5.0, 1.5, 15.04, 14.98
    assert rp.identify(_z(close, prev, mu, sd), close, mu, sd, final, prev) == "prev"
    assert rp.identify(_z(close, final, mu, sd), close, mu, sd, final, prev) == "final"
    assert rp.repeat_status("prev", final, prev) == "yes_stale"
    assert rp.repeat_status("final", final, prev) == "no"


def test_without_a_z_only_an_equal_pair_is_known():
    assert rp.identify(np.nan, 14.2, -5.0, 1.5, 15.0, 15.0) == "no z"
    assert rp.identify(-4.0, 14.2, -5.0, 1.5, 15.0, 15.0) == "no z"      # clipped
    assert rp.repeat_status("no z", 15.00, 15.00) == "yes_genuine"
    assert rp.repeat_status("no z", 15.01, 15.00) == "unknown"
    assert rp.repeat_status("other", 15.01, 15.00) == "unknown"


def test_only_the_sleeves_own_drops_are_ineligible():
    assert not rp.eligible("cef: illiquid gmax=1.8000")
    assert not rp.eligible("cef: only 5 eligible names")
    assert rp.eligible("cef: below min weight gmax=1.8000")      # band zero, still in the row
    assert rp.eligible("cef band hold: |gap|<=0.0480 w=+0.1656")
