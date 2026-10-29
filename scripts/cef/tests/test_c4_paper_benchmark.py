"""C4's frozen spec and its fidelity check (C4_DEPLOY_PLAN_2026-10-27.md §2 step 2).

WHAT EACH GROUP WOULD HAVE CAUGHT:

  1. THE SPEC IS THE TRIAL'S. The universe is the trial's frozen file, name for name, and
     none of it is in the core's 13; every signal parameter equals what trial C4 read
     through `scripts/cef/spec.py` (and that is still the spec the trial recorded); the four
     C4 keys say what the trial did; every key carries its `_<key>_note`, and every frozen
     note a REVERT. A retyped ticker, a parameter "improved" in passing, or a mask left off
     fails here before anything runs.
  2. IT VALIDATES AND IT IS DARK. It builds through the registry; no book json names it; the
     runner refuses its panel; and with its panel absent the sleeve raises, naming the path,
     instead of deciding or flattening.
  3. THE CAP IS THE RULE'S. The rule's arithmetic reproduces both of the core's recorded
     applications (IBKR 1.90, Alpaca 1.80), and the spec's value is the committed
     derivation's.
  4. THE FIDELITY CHECK HAS TEETH, on a real families panel cut to 2003-07..2007-06 (read
     only, into tmp_path; both sides read the same rows): the spec matches the trial's T on
     every compared session, holds and trades alike; and it BREAKS when a mask is off, when
     the hold is off, and when any signal parameter moves. M2 masks nothing an eligible fund
     needs on the real fit panel (the benchmark reports it), so its control injects one
     zero-volume day into the copy: a synthetic edit testing the check, not a claim about a
     market. The probe refuses a sleeve whose code it does not recognise.

`data/` is gitignored: without the families panels group 4 SKIPS, naming why; groups 1-3
still run.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.cef import c4_families as c4
from scripts.cef import c4_paper_benchmark as bm
from src.deploy import registry
from src.deploy.sleeve import MarketState
from src.deploy.sleeves import cef_discount as cefmod

REPO = bm.REPO
LO, HI = pd.Timestamp("2003-07-01"), pd.Timestamp("2007-06-29")   # a short real panel: holds and trades
STEP = 7     # odd, so the compared sessions alternate in parity and the 2-day calendar control can bite

needs_families = pytest.mark.skipif(
    not all((c4.FAM_DIR / f"{f}.parquet").exists() for f in bm.FAMILY_FILES),
    reason="data/cef_families/ absent (data/ is gitignored); the spec, registry and rule tests still run")


def _spec():
    return bm.load_spec()


# ---------------------------------------------------------------------------
# 1. the spec is the trial's
# ---------------------------------------------------------------------------

def test_the_universe_is_the_trials_frozen_file_and_disjoint_from_the_core():
    fz = pd.read_csv(c4.FROZEN)
    assert set(fz["read_utc"]) == {c4.FROZEN_READ_UTC}
    uni = _spec()["frozen"]["universe"]
    assert uni == sorted(fz["ticker"]) and len(uni) == 74 == len(set(uni))
    from scripts.cef.spec import UNIVERSE as CORE
    assert not set(uni) & set(CORE)


def test_every_signal_parameter_is_the_one_the_trial_read():
    """Equal to scripts/cef/spec.py, which `build_targets` read for the trial, AND that file is
    still the spec the trial recorded. If the core moves on, this fails: whether C4 follows is a
    decision (a new trial), never an inheritance by accident."""
    from scripts.cef import spec as core
    assert core.SPEC_ID == json.loads(c4.FIT_JSON.read_text())["spec"], (
        "the core spec is no longer the one trial C4 read; decide what C4's spec should hold")
    f = _spec()["frozen"]
    want = {"z_window": core.Z_WINDOW, "vol_target_annual": core.VOL_TARGET, "min_adv_usd": core.MIN_ADV_USD,
            "min_names": core.MIN_NAMES, "band_width": core.BAND_WIDTH, "min_abs_weight": core.MIN_ABS_WEIGHT,
            "max_nav_age_bd": core.MAX_NAV_AGE_BD, "gross_leverage": core.GROSS_LEVERAGE,
            "warmup_days": core.WARMUP_DAYS, "order_type": core.ORDER_TYPE, "rebalance_days": core.REBALANCE_DAYS}
    assert {k: f[k] for k in want} == want
    assert _spec()["rebalance"]["min_trade_usd"] == core.MIN_TRADE_USD


def test_the_four_c4_keys_say_what_the_trial_did():
    s = _spec()
    assert registry.cef_optional_keys(s["frozen"]) == {
        "panel_source": (bm.C4_PANEL["prices"], bm.C4_PANEL["nav"]),
        "nav_repeat_mask": True, "zero_volume_mask": True, "below_min_names": "hold"}
    assert s["frozen"]["panel_source"] == bm.C4_PANEL


def test_every_key_has_its_note_and_every_frozen_note_a_revert():
    """The spec-change standard (`_band_width_note`): a sibling note per key. Top level, the
    self-describing blocks (description, the blocks themselves, the kill rule's own text and the
    evidence pointers) are exempt; `_drawdown_levels_note` documents keys left out on purpose."""
    s = _spec()
    exempt_top = {"description", "frozen", "rebalance", "risk", "kill_rule", "evidence"}
    for name, b, exempt in (("top", s, exempt_top), ("frozen", s["frozen"], set()),
                            ("rebalance", s["rebalance"], set()), ("risk", s["risk"], set())):
        keys = [k for k in b if not k.startswith("_") and k not in exempt]
        assert keys, name
        for k in keys:
            assert f"_{k}_note" in b, f"{name}.{k} has no _{k}_note"
    for k, v in s["frozen"].items():
        if k.startswith("_"):
            assert k.endswith("_note") and k[1:-len("_note")] in s["frozen"], f"frozen.{k} documents no key"
            assert "REVERT" in v, f"frozen.{k} names no REVERT"
    assert "halve_drawdown" not in s["risk"] and "kill_drawdown" not in s["risk"]
    assert "_drawdown_levels_note" in s["risk"]


# ---------------------------------------------------------------------------
# 2. it validates, and it is dark
# ---------------------------------------------------------------------------

def test_the_spec_validates_and_builds_through_the_registry():
    s = _spec()
    registry.validate_spec(s)
    sl = bm.build_sleeve(s)
    assert isinstance(sl, cefmod.CEFDiscountSleeve)
    assert sl.instruments() == s["frozen"]["universe"]
    assert sl.panel_paths() == (cefmod.REPO / bm.C4_PANEL["prices"], cefmod.REPO / bm.C4_PANEL["nav"])


def test_no_book_names_it_and_the_runner_refuses_it():
    from quantt.session import run as rn
    for p in (REPO / "ops" / "books").glob("*.json"):
        assert "c4_families" not in p.read_text(), f"{p.name} names the C4 spec"
    assert all(b.spec_path.name != bm.SPEC_PATH.name for b in rn.BOOKS.values())
    with pytest.raises(rn.SessionError, match="data/cef_c4/cef_prices.parquet"):
        rn.require_core_panel(_spec())


def test_an_absent_panel_refuses_naming_it(tmp_path, monkeypatch):
    """Step 3 has not built data/cef_c4/: the sleeve must say so and decide nothing, never
    flatten. `cefmod.REPO` points at an empty root so the test cannot see a later real panel."""
    monkeypatch.setattr(cefmod, "REPO", tmp_path)
    sl = bm.build_sleeve(_spec())
    ms = MarketState(asof=pd.Timestamp("2022-12-30"), prices=pd.DataFrame(), holdings={},
                     extras={"sleeve_nav": 100000.0})
    with pytest.raises(FileNotFoundError, match="data/cef_c4/cef_prices.parquet") as e:
        sl.target_positions(pd.Timestamp("2022-12-30"), ms)
    assert "not flattening" in str(e.value)


# ---------------------------------------------------------------------------
# 3. the cap is the rule's
# ---------------------------------------------------------------------------

def test_the_rule_reproduces_both_of_the_cores_applications():
    # PREREG_GROUP_CAP_2026-09-16 §3b (IBKR): 1.930940, less the 0.02 mark sensitivity -> 1.90
    g = bm.g_stress(714475.4510832613, 194797.03120376007, 0.5, 0.038264817497540925, 500000.0)
    assert round(g, 6) == 1.930940 and bm.floor_to(g - 0.02) == 1.90
    # PREREG_ALPACA_V7_2026-09-28 §3b: 1.843041, no mark sensitivity -> 1.80
    g = bm.g_stress(100000.0, 0.0, 0.5, 0.0425814, 100000.0)
    assert round(g, 6) == 1.843041 and bm.floor_to(g) == 1.80
    assert bm.floor_to(1.95) == 1.95 and bm.floor_to(1.9499999) == 1.90   # down, never to nearest


def test_the_specs_cap_is_the_committed_derivation():
    d = json.loads(bm.OUT_JSON.read_text())["cap"]
    s = _spec()
    want = bm.floor_to(bm.g_stress(d["inputs"]["nlv_usd"][0], d["inputs"]["m_other_usd"][0],
                                   d["inputs"]["m"][0], d["w5"], s["capital_usd"])
                       - d["inputs"]["mark_sensitivity"][0])
    assert s["frozen"]["max_gross_stress"] == want == d["max_gross_stress"]
    assert d["method_check"]["end"] == "2020-03-18" and d["traded_end"] <= str(bm.FIT_END.date())
    from scripts.cef.spec import MAX_GROSS_STRESS as CORE_CAP
    assert d["inputs"]["e_book_usd"][0] == s["capital_usd"]
    assert CORE_CAP is not None    # the core's value exists; C4's is derived, not copied from it


def test_the_probe_refuses_a_sleeve_it_does_not_recognise():
    class Other(cefmod.CEFDiscountSleeve):
        def target_positions(self, asof, market_state):
            self._req("min_abs_weight")
            return []
    sl = Other(_spec(), 100000.0)
    probe = bm.Probe(sl)
    with pytest.raises(bm.ProbeError, match="not CEFDiscountSleeve.target_positions"):
        probe.decide("2022-12-30")


# ---------------------------------------------------------------------------
# 4. the fidelity check, on a real panel
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def short(tmp_path_factory):
    if not all((c4.FAM_DIR / f"{f}.parquet").exists() for f in bm.FAMILY_FILES):
        pytest.skip("data/cef_families/ absent")
    cut = tmp_path_factory.mktemp("c4cut")
    bm.cut_families(cut, lo=LO, hi=HI)
    T, info = bm.trial_targets(cut)
    return dict(cut=cut, T=T, dates=bm.fidelity_dates(T, step=STEP))


@needs_families
def test_the_spec_matches_the_trial_on_every_compared_session(short):
    rep = bm.fidelity(_spec(), short["cut"], short["dates"], T=short["T"])
    assert rep["n_breaks"] == 0 and rep["session_match_rate"] == 1.0 and rep["cell_match_rate"] == 1.0
    assert rep["largest_gap"] <= bm.TOL
    assert rep["hold_sessions"] >= 1 and rep["trade_sessions"] >= 5, "not vacuous: both paths compared"


@needs_families
@pytest.mark.parametrize("name", [n for n, _ in bm.controls(json.loads(bm.SPEC_PATH.read_text()))
                                  if not n.startswith("zero_volume_mask")])
def test_the_check_breaks_when_a_mask_the_hold_or_a_parameter_changes(short, name):
    sp = dict(bm.controls(_spec()))[name]
    with pytest.raises(bm.FidelityBreak) as e:
        bm.fidelity(sp, short["cut"], short["dates"], T=short["T"], first_break=True)
    assert e.value.report["n_breaks"] >= 1


@needs_families
def test_the_check_breaks_with_m2_off_on_a_zero_volume_day(short, tmp_path):
    """Set one eligible fund-day's volume to 0 in a copy of the cut. The trial masks it (M2) and
    rebuilds T without that fund that day; the spec, M2 on, still matches; M2 off, it breaks."""
    T0 = short["T"]
    floor = _spec()["frozen"]["min_names"] + 1          # one fund out must not tip the day into a hold
    d = next(x for x in short["dates"] if bm._trial_kind(T0, T0.index.get_loc(x)) == "trade"
             and x > T0.index[T0.abs().sum(axis=1) > 0][0] and int((T0.loc[x] != 0).sum()) >= floor)
    tk = T0.loc[d].abs().idxmax()
    cut = tmp_path / "cut"
    cut.mkdir()
    for f in bm.FAMILY_FILES:
        df = pd.read_parquet(short["cut"] / f"{f}.parquet")
        if f == "cef_prices":
            hit = (df["ticker"] == tk) & (pd.to_datetime(df["date"]) == d)
            assert hit.sum() == 1
            df.loc[hit, "volume"] = 0
        df.to_parquet(cut / f"{f}.parquet")
    T1, _ = bm.trial_targets(cut)
    assert T1.loc[d, tk] == 0 and T0.loc[d, tk] != 0, "the injected day is masked in the trial"
    dates = [x for x in short["dates"] if x <= d][-3:]
    rep = bm.fidelity(_spec(), cut, dates, T=T1)
    assert rep["n_breaks"] == 0
    with pytest.raises(bm.FidelityBreak) as e:
        bm.fidelity(bm.with_keys(_spec(), zero_volume_mask=False), cut, dates, T=T1)
    assert any(b["date"] == str(d.date()) and b["kind"] == "eligibility" for b in e.value.report["breaks"])


@needs_families
def test_no_date_after_the_fit_is_compared_or_cut(short, tmp_path):
    with pytest.raises(AssertionError, match="after the fit end"):
        bm.fidelity(_spec(), short["cut"], [pd.Timestamp("2023-01-03")], T=short["T"])
    with pytest.raises(AssertionError, match="after the fit end"):
        bm.cut_families(tmp_path / "x", hi="2023-01-03")
    for f in bm.FAMILY_FILES:
        assert pd.to_datetime(pd.read_parquet(short["cut"] / f"{f}.parquet")["date"]).max() <= HI
