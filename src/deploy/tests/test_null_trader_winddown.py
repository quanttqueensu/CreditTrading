"""The retirement path for phase0_null, pinned before anyone runs it.

WHY THIS TEST EXISTS
--------------------
Retiring a live sleeve has one obvious-looking move that is WRONG, and the
wrongness is silent. Setting `"enabled": false` in the book JSON does NOT wind
the position down -- `Orchestrator.advance` reads

    disabled_now = name in self.disabled
    if not disabled_now and name not in self.enabled:
        continue

and `self.disabled` is populated ONLY at runtime, by `risk.py` on a KILL
verdict. A sleeve turned off in config lands in NEITHER set, so `advance`
skips it entirely and its 12 positions and $560k of gross sit on the account
forever, unmanaged, with nothing left that would ever close them.

The path that does work is to leave the sleeve enabled and take its gross to
zero, so it emits FLAT for every name it could hold and the ordinary
target->order path closes the book. That is what this pins:

  1. `gross_leverage: 0.0` yields an EXPLICIT FLAT for every universe name --
     not an empty list. The distinction matters because an empty list would
     rely on the broker's held-but-unmentioned branch, which is the same code
     path that would have sent BUY 1,503 against a phantom JAAA short
     (CLAUDE.md landmine 3). Explicit FLAT states the intent; omission infers
     it.
  2. It is the *number of names*, not the weights, that must survive: every
     symbol the sleeve could be holding has to be named, or the one that is
     missed is the one left naked.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.sleeve import FLAT                          # noqa: E402
from src.deploy.sleeves.null_trader import NullTraderSleeve  # noqa: E402

SPEC = REPO / "ops/specs/null_trader.frozen.json"


class _MS:
    def __init__(self, asof, prices):
        self.asof, self.prices = asof, prices
        self.holdings, self.extras, self.events = {}, {}, None
        self.mark_fn = self.greeks_fn = None


def _targets(gross_leverage):
    spec = copy.deepcopy(json.loads(SPEC.read_text()))
    spec["frozen"]["gross_leverage"] = gross_leverage
    sleeve = NullTraderSleeve(spec, float(spec["capital_usd"]))
    uni = spec["frozen"]["universe"]
    idx = pd.bdate_range("2026-06-01", "2026-09-11")
    px = pd.DataFrame(100.0, index=idx, columns=uni)
    return uni, sleeve.target_positions(idx[-1], _MS(idx[-1], px))


def test_zero_gross_flattens_every_name_explicitly():
    uni, ts = _targets(0.0)
    assert len(ts) == len(uni), (
        f"{len(uni) - len(ts)} universe name(s) got no target at all; an "
        f"unmentioned symbol is one the wind-down would leave open")
    assert {t.instrument for t in ts} == set(uni)
    assert all(t.side == FLAT for t in ts), \
        f"not every target is FLAT: {sorted({t.side for t in ts})}"
    assert not any(float(getattr(t, "weight", 0.0) or 0.0) for t in ts)


def test_the_live_configuration_still_trades():
    """The guard on the guard: if unit gross ALSO produced FLAT, the test above
    would pass for the wrong reason and tell us nothing about the change."""
    uni, ts = _targets(1.0)
    assert len(ts) == len(uni)
    assert any(t.side != FLAT for t in ts), \
        "the unmodified spec produced no live position; test 1 proves nothing"


def test_disabling_in_config_is_not_a_winddown_path():
    """Documents the trap in executable form.

    `Orchestrator.advance` skips a sleeve that is in neither `enabled` nor
    `disabled`. Nothing in the repo puts a name into `disabled` from config --
    only `risk.py` does, at runtime, on KILL. So `"enabled": false` abandons
    the position rather than closing it.
    """
    src = (REPO / "src/deploy/portfolio.py").read_text()
    assert "if not disabled_now and name not in self.enabled:" in src, \
        "advance()'s skip condition changed -- re-verify the retirement path"
    risk = (REPO / "src/deploy/risk.py").read_text()
    assert "orchestrator.disabled.add(sleeve_name)" in risk
    # and no config key reaches that set
    assert ".disabled.add" not in (REPO / "src/deploy/run_book.py").read_text()
