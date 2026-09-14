"""The CEF sleeve refuses a spec that is missing a sizing or signal knob.

WHY THIS FILE EXISTS
--------------------
Until 2026-09-14 every knob in `CEFDiscountSleeve` was read as
`frozen.get(key, <number>)`. The live spec carries all of them, so nothing ever
fired -- which is exactly the shape CLAUDE.md warns about: a fallback that is
dormant until the day a spec is edited, copied or truncated, and then sizes the
book on a vol target (6%), a z window (252) or an order type (MOC) that nobody
decided for that spec. The documents disagreed about the vol target at the same
time, so a silent 0.06 would have been indistinguishable from a real setting.

Now a missing key raises, naming it. `band_width` is the deliberate exception:
absent means the band is off, and that no-op is what made turning it on a single
visible edit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.deploy.sleeves.cef_discount import CEFDiscountSleeve

REPO = Path(__file__).resolve().parents[3]
LIVE = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())

REQUIRED = {
    "_vol_target": "vol_target_annual",
    "_win": "z_window",
    "_min_adv": "min_adv_usd",
    "_rebal_days": "rebalance_days",
}


def _spec(drop=None):
    spec = json.loads(json.dumps(LIVE))
    if drop:
        spec["frozen"].pop(drop)
    return spec


@pytest.mark.parametrize("attr,key", sorted(REQUIRED.items()))
def test_a_missing_knob_raises_and_names_the_key(attr, key):
    sl = CEFDiscountSleeve(_spec(drop=key), 500000.0)
    with pytest.raises(KeyError, match=key):
        getattr(sl, attr)


def test_a_missing_universe_is_not_an_empty_book():
    sl = CEFDiscountSleeve(_spec(drop="universe"), 500000.0)
    with pytest.raises(KeyError, match="universe"):
        sl.instruments()


def test_the_live_spec_has_every_required_knob():
    """If this fails, the live spec is missing a key the sleeve now refuses
    to invent -- fix the spec through /spec-change, not the sleeve."""
    sl = CEFDiscountSleeve(_spec(), 500000.0)
    for attr in REQUIRED:
        getattr(sl, attr)
    assert sl.instruments()
    for key in ("max_nav_age_bd", "min_names", "gross_leverage",
                "min_abs_weight", "order_type"):
        assert key in LIVE["frozen"], key


def test_band_width_absent_still_means_off():
    sl = CEFDiscountSleeve(_spec(drop="band_width"), 500000.0)
    assert sl._band_width is None
