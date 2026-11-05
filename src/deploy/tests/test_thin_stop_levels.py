"""CEF trial 55 (te4): the K1-K3 report thresholds, `risk.thin_*`, as the registry parses them.

The runner's owner (answer 3, 2026-11-03): the thresholds are report-only spec keys, set in the
ACTIVATION commit with a sibling note naming the compose_<stamp>.json that derived them; the
live path never reads results/. In this pass the registry accepts and validates them when
present, the misspelling guard knows them, and absent reads UNMEASURED
(src/deploy/registry.py `cef_thin_stop_levels`). Each test fails on the code before this commit,
which has no `cef_thin_stop_levels` and validates a spec carrying any of these keys without a
word.
"""
import copy
import json
from pathlib import Path

import pytest

from src.deploy import registry as R

ROOT = Path(__file__).resolve().parents[3]

# K3's run length is required under the rule (the runner owner's review 2026-11-04, item 9).
K3_RUN_NOTE = "test only: §6.3's 3 consecutive reduced closes"
SPEC = {
    "spec_id": "test.te4-lines.v1", "status": "test", "capital_usd": 100_000.0,
    "allocation": {"type": "cef_discount"},
    "risk": {"max_gross_exposure_usd": 260_000.0, "halve_drawdown": 0.12, "kill_drawdown": 0.18,
             "thin_k3_run_sessions": 3, "_thin_k3_run_sessions_note": K3_RUN_NOTE},
    "frozen": {"universe": [f"F{i}" for i in range(8)], "z_window": 252, "rebalance_days": 1,
               "vol_target_annual": 0.06, "min_adv_usd": 3_000_000.0, "max_nav_age_bd": 3,
               "min_names": 6, "min_abs_weight": 0.005, "gross_leverage": 1.0,
               "order_type": "MOC", "band_width": 0.048, "max_gross_stress": 1.8,
               "below_min_names": "trade_eligible", "below_min_names_floor": 4},
}
# Test values (the pre-registration's drafting-day figures, §6.3); never the live ones.
VALUES = {"thin_k1_episode_drawdown": 0.1052, "thin_k2_max_name_frac": 0.956,
          "thin_k3_net_run": 0.248, "thin_k3_net_once": 0.833}
NOTE = "derived by results/cef/prereg_thin_te4/compose.py --stamp 2026-12-01: compose_2026-12-01.json §E"


def spec_with(**kw) -> dict:
    s = copy.deepcopy(SPEC)
    for k, v in kw.items():
        s["risk"][k] = v
        s["risk"][f"_{k}_note"] = NOTE
    return s


def test_absent_reads_none_for_every_line_and_the_live_specs_validate():
    assert R.cef_thin_stop_levels(SPEC) == {**{k: None for k in R.CEF_THIN_STOP_KEYS},
                                            "thin_k3_run_sessions": 3}
    for f in ("cef_discount", "c4_families"):
        live = json.loads((ROOT / "ops" / "specs" / f"{f}.frozen.json").read_text())
        R.validate_spec(live)
        assert R.cef_thin_stop_levels(live) == {k: None for k in R.CEF_THIN_KEYS}


def test_present_values_are_read_with_their_notes():
    got = R.cef_thin_stop_levels(spec_with(**VALUES))
    assert got == {**VALUES, "thin_k3_run_sessions": 3}
    R.validate_spec(spec_with(**VALUES))


@pytest.mark.parametrize("key,bad", [
    ("thin_k1_episode_drawdown", 10.52),      # a percent
    ("thin_k1_episode_drawdown", 1.0),
    ("thin_k1_episode_drawdown", 0.0),
    ("thin_k2_max_name_frac", 95.6),          # a percent: above max_gross_stress
    ("thin_k2_max_name_frac", 1.8),           # at the cap
    ("thin_k3_net_once", float("nan")),
    ("thin_k3_net_run", True),
    ("thin_k3_net_run", "0.248"),
    ("thin_k2_max_name_frac", -0.1),
])
def test_a_bad_value_is_refused_naming_the_key(key, bad):
    with pytest.raises(ValueError, match=key):
        R.validate_spec(spec_with(**{key: bad}))


def test_the_run_line_must_be_below_the_once_line():
    with pytest.raises(ValueError, match="thin_k3_net_run"):
        R.cef_thin_stop_levels(spec_with(thin_k3_net_run=0.9, thin_k3_net_once=0.8))


def test_a_threshold_without_its_compose_note_is_refused():
    s = spec_with(**VALUES)
    del s["risk"]["_thin_k2_max_name_frac_note"]
    with pytest.raises(ValueError, match="_thin_k2_max_name_frac_note"):
        R.validate_spec(s)
    s["risk"]["_thin_k2_max_name_frac_note"] = "the fit maximum, from the draft"
    with pytest.raises(ValueError, match="compose_"):
        R.validate_spec(s)


def test_a_threshold_under_another_rule_is_refused():
    for rule in ("flatten", "hold", None):
        s = spec_with(thin_k2_max_name_frac=0.956)
        for k in ("thin_k3_run_sessions", "_thin_k3_run_sessions_note"):
            s["risk"].pop(k)
        s["frozen"].pop("below_min_names_floor")
        if rule is None:
            s["frozen"].pop("below_min_names")
        else:
            s["frozen"]["below_min_names"] = rule
        with pytest.raises(ValueError, match="read only under 'trade_eligible'"):
            R.validate_spec(s)


@pytest.mark.parametrize("typo", ["thin_k1_episode_drawdwn", "thin_k2_max_name_fracs",
                                  "think3netrun", "_thin_k3_net_once", "Thin-K3-Net-Once"])
def test_a_misspelt_threshold_is_refused(typo):
    s = copy.deepcopy(SPEC)
    s["risk"][typo] = 0.2
    with pytest.raises(ValueError, match="looks like a misspelling"):
        R.validate_spec(s)


def test_a_threshold_written_in_frozen_is_refused():
    s = copy.deepcopy(SPEC)
    s["frozen"]["thin_k2_max_name_frac"] = 0.956
    with pytest.raises(ValueError, match="move it to risk"):
        R.validate_spec(s)


def test_the_live_keys_are_far_from_every_threshold():
    """No key either live spec carries is within the guard's reach of a threshold, so the guard
    cannot refuse a live spec (checked key by key, as test_c4_sleeve_keys does for C4's)."""
    for f in ("cef_discount", "c4_families"):
        live = json.loads((ROOT / "ops" / "specs" / f"{f}.frozen.json").read_text())
        for block in ("risk", "frozen"):
            for key in live.get(block) or {}:
                assert R._thin_stop_near_miss(key) is None, (f, block, key)


# ---------------------------------------------------------------------------
# K3's run length, `risk.thin_k3_run_sessions` (the runner owner's review 2026-11-04, item 9)
# ---------------------------------------------------------------------------

RUN_KEY = "thin_k3_run_sessions"


def _without_run(s: dict) -> dict:
    s = copy.deepcopy(s)
    for k in (RUN_KEY, f"_{RUN_KEY}_note"):
        s["risk"].pop(k, None)
    return s


def test_the_k3_run_length_is_required_under_the_rule_with_no_default():
    """It was a module constant (drawdown.THIN_K3_RUN = 3). Now the spec states it, and under
    "trade_eligible" a spec without it refuses at load, as one without a floor does. Fails on
    8527488, which validates the spec without it."""
    with pytest.raises(ValueError, match=f"needs risk.{RUN_KEY}.*no default"):
        R.validate_spec(_without_run(SPEC))
    with pytest.raises(ValueError, match=RUN_KEY):
        R.cef_thin_stop_levels(_without_run(spec_with(**VALUES)))
    for v in (2, 3, 5):
        s = copy.deepcopy(SPEC)
        s["risk"][RUN_KEY] = v
        R.validate_spec(s)
        assert R.cef_thin_stop_levels(s)[RUN_KEY] == v


@pytest.mark.parametrize("bad", [True, 3.0, "3", 1, 0, -3, None])
def test_a_bad_k3_run_length_is_refused_naming_the_key_and_the_value(bad):
    s = copy.deepcopy(SPEC)
    s["risk"][RUN_KEY] = bad
    with pytest.raises(ValueError, match=RUN_KEY) as e:
        R.validate_spec(s)
    assert repr(bad) in str(e.value) or str(bad) in str(e.value)


@pytest.mark.parametrize("note", [None, "", "   ", 3])
def test_the_k3_run_length_needs_its_note(note):
    s = copy.deepcopy(SPEC)
    if note is None:
        s["risk"].pop(f"_{RUN_KEY}_note")
    else:
        s["risk"][f"_{RUN_KEY}_note"] = note
    with pytest.raises(ValueError, match=f"_{RUN_KEY}_note"):
        R.validate_spec(s)


def test_the_k3_run_length_under_another_rule_is_refused():
    """As the floor and the lines: a count nothing reads is a spec that says one thing and does
    another. The revert spec deletes it with them."""
    for rule in ("flatten", "hold", None):
        s = copy.deepcopy(SPEC)
        s["frozen"].pop("below_min_names_floor")
        if rule is None:
            s["frozen"].pop("below_min_names")
        else:
            s["frozen"]["below_min_names"] = rule
        with pytest.raises(ValueError, match=f"{RUN_KEY}.*read only under 'trade_eligible'"):
            R.validate_spec(s)
        R.validate_spec(_without_run(s))          # deleted with the rule: validates


@pytest.mark.parametrize("typo", ["thin_k3_run_session", "thin_k3_runs_sessions", "think3runsessions",
                                  "_thin_k3_run_sessions", "Thin-K3-Run-Sessions"])
def test_a_misspelt_k3_run_length_is_refused(typo):
    s = copy.deepcopy(SPEC)
    s["risk"][typo] = 3
    with pytest.raises(ValueError, match=f"looks like a misspelling of '{RUN_KEY}'"):
        R.validate_spec(s)


def test_the_k3_run_length_written_in_frozen_is_refused():
    s = copy.deepcopy(SPEC)
    s["frozen"][RUN_KEY] = 3
    with pytest.raises(ValueError, match=f"move it to risk.{RUN_KEY}"):
        R.validate_spec(s)
