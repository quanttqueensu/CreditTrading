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
    still the spec the trial recorded, or that spec plus CEF trial 53's account key and nothing
    else. If the core moves on in any other way, this fails: whether C4 follows is a decision (a
    new trial), never an inheritance by accident.

    TRIAL 53 (merged here 2026-11-02). The core's spec became cef_discount.v8.20261101: v7, the
    spec trial C4 recorded, plus `sizing_multiplier` 1.13 and its note. That key sizes the core's
    ACCOUNT, not the signal, and trial 53 decided C4's own value separately (1.27, its spec's
    `_sizing_multiplier_note`), so it is the one difference allowed. v7 is read from git at
    35b429f (test_combine_noop.pre_trial_spec, the same bytes as the local revert tag)."""
    from quantt.session.tests.test_combine_noop import (
        PRE_TRIAL_COMMIT, assert_live_is_pre_trial_plus_the_multiplier, pre_trial_spec)
    from scripts.cef import spec as core
    recorded = json.loads(c4.FIT_JSON.read_text())["spec"]
    if core.SPEC_ID != recorded:
        pre = pre_trial_spec()
        if pre is None:
            pytest.skip(f"git cannot show {PRE_TRIAL_COMMIT}:ops/specs/cef_discount.frozen.json, "
                        f"the spec trial C4 recorded ({recorded}); the core is {core.SPEC_ID}")
        assert pre[1]["spec_id"] == recorded, (
            "the core spec is no longer the one trial C4 read; decide what C4's spec should hold")
        assert_live_is_pre_trial_plus_the_multiplier(pre[1], json.loads(core.SPEC_PATH.read_text()))
    f = _spec()["frozen"]
    want = {"z_window": core.Z_WINDOW, "vol_target_annual": core.VOL_TARGET, "min_adv_usd": core.MIN_ADV_USD,
            "min_names": core.MIN_NAMES, "band_width": core.BAND_WIDTH, "min_abs_weight": core.MIN_ABS_WEIGHT,
            "max_nav_age_bd": core.MAX_NAV_AGE_BD, "gross_leverage": core.GROSS_LEVERAGE,
            "warmup_days": core.WARMUP_DAYS, "order_type": core.ORDER_TYPE, "rebalance_days": core.REBALANCE_DAYS}
    assert {k: f[k] for k in want} == want
    assert _spec()["rebalance"]["min_trade_usd"] == core.MIN_TRADE_USD


def test_the_spec_carries_trial_53s_multiplier_with_its_note():
    """CEF trial 53's C4 value, as amended (amendment 1, team lead 2026-11-02, spec v4.20261102):
    1.26 (1.2642, derived once the core is measured on its live thin-day rule; rounded down), with
    its sibling note, which names 1.27 (1.2712, applied 2026-11-02 in v2/v3) as not chosen.
    Nothing the fidelity gate reads moved. Fails on v3 (1.27) and on v1 (no key), by design."""
    s = _spec()
    f = s["frozen"]
    assert f["sizing_multiplier"] == 1.26
    assert registry.cef_sizing_multiplier(f) == 1.26
    note = f["_sizing_multiplier_note"]
    for must in ("CEF trial 53", "AMENDMENT 1", "1.2642", "1.2712", "ROUNDED DOWN", "NOT CHOSEN",
                 "REVERT", "UNITS", "spec-c4_families.v3.20261102"):
        assert must in note, must
    # The unit book is the trial's: the vol target, gross leverage and band are not moved.
    assert (f["vol_target_annual"], f["max_gross_stress"]) == (0.06, 1.9)
    # v2.20261101 applied it (1.27); v3.20261102 added only the halve/kill levels (the next test);
    # v4.20261102 is amendment 1's 1.26, nothing else.
    assert s["spec_id"] == "c4_families.v4.20261102" and s["_supersedes"] == "c4_families.v3.20261102"
    registry.build_sleeve(s, float(s["capital_usd"]))          # validates (cap set, 0.06 x m sane)


def test_the_halve_kill_levels_are_the_cores_and_read_in_report_mode_only():
    """Team lead 2026-10-30 (docs/SYSTEM.md section 5): C4's HALVE/KILL drawdown levels are the
    core's, in report mode, until a C4-specific derivation exists. Wired as the core's are: the
    spec's risk.halve_drawdown / risk.kill_drawdown, read by quantt/session/drawdown.py through the
    book json's risk.drawdown = 'report'. Copied, so this fails the day the two specs differ: a
    change to the core's levels is then a C4 spec change too, never an inheritance by accident.
    Fails on v2 (no levels)."""
    from quantt.session import drawdown as ddm
    from scripts.cef import spec as core
    c4r, corer = _spec()["risk"], json.loads(core.SPEC_PATH.read_text())["risk"]
    assert (c4r["halve_drawdown"], c4r["kill_drawdown"]) == \
        (corer["halve_drawdown"], corer["kill_drawdown"])
    for k in ("_halve_drawdown_note", "_kill_drawdown_note"):
        for must in ("THE CORE'S LEVEL", "team lead 2026-10-30", "UNITS", "REPORT", "NOTHING ACTS",
                     "REVERT"):
            assert must.lower() in c4r[k].lower(), (k, must)
    lv = ddm.levels(_spec())
    assert (lv["halve"], lv["kill"]) == (corer["halve_drawdown"], corer["kill_drawdown"])
    assert lv["source"].startswith(_spec()["spec_id"])
    book = json.loads((REPO / "ops" / "books" / "c4_families_book.json").read_text())
    assert book["risk"]["drawdown"] == ddm.REPORT == "report"


def test_h11_reads_the_account_book_under_the_multiplier(monkeypatch):
    """`h11_reference` (trial 53's edit): with `sizing_multiplier` m the reference is
    m x band_gross_capped(T, band, cap / m), the book the account trades (the sleeve bands on
    held / m and caps at cap / m in unit weights); absent, it is band_gross_capped(T, band, cap)
    exactly as before. Synthetic T and zero returns: a test of the construction, not a market."""
    from scripts.cef import band_frontier as bf
    idx = pd.bdate_range("2005-03-01", periods=40)
    cols = ["AAA", "BBB", "CCC", "DDD"]
    k = pd.DataFrame([[((i * 7 + j * 3) % 11 - 5) / 10.0 for j in range(4)] for i in range(40)],
                     index=idx, columns=cols)
    T = k * 1.9      # unit gross 1.90-2.28: capped at 1.90 without m, at 1.90 / 1.27 = 1.496 with it
    zero = pd.DataFrame(0.0, index=idx, columns=cols)
    tb = {"T": T, "R0": zero, "R0x": zero}
    base = {"spec_id": "synthetic", "frozen": {"band_width": 0.048, "max_gross_stress": 1.9}}
    with_m = {"spec_id": "synthetic-m", "frozen": dict(base["frozen"], sizing_multiplier=1.27)}
    absent = bm.h11_reference(tb, base)["H"]
    pd.testing.assert_frame_equal(absent, bf.band_gross_capped(T, 0.048, 1.9))
    got = bm.h11_reference(tb, with_m)
    pd.testing.assert_frame_equal(got["H"], 1.27 * bf.band_gross_capped(T, 0.048, 1.9 / 1.27))
    assert "sizing_multiplier 1.27" in got["policy"]
    assert got["H"].abs().sum(axis=1).max() <= 1.9 + 1e-12          # the account's cap holds
    assert not got["H"].equals(1.27 * absent)                        # the cap binds differently


def test_the_four_c4_keys_say_what_the_trial_did():
    s = _spec()
    assert registry.cef_optional_keys(s["frozen"]) == {
        "panel_source": (bm.C4_PANEL["prices"], bm.C4_PANEL["nav"]),
        "nav_repeat_mask": True, "zero_volume_mask": True, "below_min_names": "hold"}
    assert s["frozen"]["panel_source"] == bm.C4_PANEL


def test_every_key_has_its_note_and_every_frozen_note_a_revert():
    """The spec-change standard (`_band_width_note`): a sibling note per key. Top level, the
    self-describing blocks (description, the blocks themselves, the kill rule's own text and the
    evidence pointers) are exempt. (v1 and v2 had `_drawdown_levels_note` for the halve/kill
    levels they left out on purpose; v3 carries the core's, each with its own note.)"""
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
    assert "_drawdown_levels_note" not in s["risk"]          # the levels are there now (v3)


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


def test_only_c4s_own_book_names_it_and_the_runner_reads_it_from_its_own_panel():
    """Was `test_no_book_names_it_and_the_runner_refuses_it` (step 2). Row 6A
    replaced the refusal (`require_core_panel`) with per-sleeve panels, and the
    C4 integration (2026-10-29) gave the spec its own book: ops/books/
    c4_families_book.json and run.BOOKS["c4"]. Still, the CORE's book never
    names it, and the runner prices, gates and refreshes it on data/cef_c4/
    (quantt/session/tests/test_c4_book.py), never on data/cef/."""
    from quantt.session import run as rn
    naming = sorted(p.name for p in (REPO / "ops" / "books").glob("*.json")
                    if "c4_families" in p.read_text())
    assert naming == ["c4_families_book.json"]
    assert [k for k, b in rn.BOOKS.items() if b.spec_path.name == bm.SPEC_PATH.name] == ["c4"]
    assert rn.spec_panel(_spec()) == rn.Panel(REPO / bm.C4_PANEL["prices"], REPO / bm.C4_PANEL["nav"])
    assert rn.spec_panel(_spec()) != rn.core_panel()
    assert rn.refresh_flags(rn.spec_panel(_spec())) == ("--data-book", "c4")


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
    # TS: what the spec's sleeve must reproduce. T itself when the spec has no level_signal; CEF
    # trial 54's blend when it does (bm.spec_targets).
    return dict(cut=cut, T=T, TS=bm.spec_targets(cut, T, _spec()), dates=bm.fidelity_dates(T, step=STEP))


@needs_families
def test_the_spec_matches_the_trial_on_every_compared_session(short):
    rep = bm.fidelity(_spec(), short["cut"], short["dates"], T=short["TS"])
    assert rep["n_breaks"] == 0 and rep["session_match_rate"] == 1.0 and rep["cell_match_rate"] == 1.0
    assert rep["largest_gap"] <= bm.TOL
    assert rep["hold_sessions"] >= 1 and rep["trade_sessions"] >= 5, "not vacuous: both paths compared"


@needs_families
@pytest.mark.parametrize("name", [n for n, _ in bm.controls(json.loads(bm.SPEC_PATH.read_text()))
                                  if not n.startswith("zero_volume_mask")])
def test_the_check_breaks_when_a_mask_the_hold_or_a_parameter_changes(short, name):
    sp = dict(bm.controls(_spec()))[name]
    if name.startswith("band_width dropped") and "level_signal" in sp["frozen"]:
        # CEF trial 54: with level_signal set, a spec without a band is REFUSED by the registry
        # (cef_level_signal: the blend is defined through the band), before the probe can run.
        # A refusal is a stronger answer than a break, and it is the one asserted here.
        with pytest.raises(ValueError, match="band_width is not"):
            registry.validate_spec(sp)
        with pytest.raises(ValueError, match="band_width is not"):
            bm.fidelity(sp, short["cut"], short["dates"], T=short["TS"], first_break=True)
        return
    with pytest.raises(bm.FidelityBreak) as e:
        bm.fidelity(sp, short["cut"], short["dates"], T=short["TS"], first_break=True)
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
    TS1 = bm.spec_targets(cut, T1, _spec())         # the blend's own masked day, when the spec sets it
    assert TS1.loc[d, tk] == 0
    dates = [x for x in short["dates"] if x <= d][-3:]
    rep = bm.fidelity(_spec(), cut, dates, T=TS1)
    assert rep["n_breaks"] == 0
    with pytest.raises(bm.FidelityBreak) as e:
        bm.fidelity(bm.with_keys(_spec(), zero_volume_mask=False), cut, dates, T=TS1)
    assert any(b["date"] == str(d.date()) and b["kind"] == "eligibility" for b in e.value.report["breaks"])


def _level_on(spec):
    """`spec` with CEF trial 54's key at the pre-registered value (the live value once activated)."""
    fam = pd.read_csv(c4.FROZEN).set_index("ticker")["family"].to_dict()
    return bm.with_keys(spec, level_signal={"risk_share": 0.5, "family_of": fam})


def _level_off(spec):
    return bm.with_keys(spec, drop=[k for k in ("level_signal", "_level_signal_note") if k in spec["frozen"]])


@needs_families
def test_the_blended_sleeve_matches_the_trials_blend(short):
    """§1.3 test 6 (CEF trial 54). With level_signal set, the probe compares the sleeve's blend with
    the trial's blend (`spec_targets`, trial54.py's `level_targets` unmasked) and every compared
    session matches to TOL, trades and holds; the blend is not the z book (not vacuous); and the
    key absent, `spec_targets` is T itself. Fails before spec_targets existed."""
    on, off = _level_on(_spec()), _level_off(_spec())
    TB = bm.spec_targets(short["cut"], short["T"], on)
    assert bm.spec_targets(short["cut"], short["T"], off) is short["T"]
    rep = bm.fidelity(on, short["cut"], short["dates"], T=TB)
    assert rep["n_breaks"] == 0 and rep["session_match_rate"] == 1.0 and rep["largest_gap"] <= bm.TOL
    assert rep["hold_sessions"] >= 1 and rep["trade_sessions"] >= 5
    traded = [d for d in short["dates"] if bm._trial_kind(TB, TB.index.get_loc(d)) == "trade"]
    assert float((TB.loc[traded] - short["T"].loc[traded]).abs().max().max()) > 1e-3


@needs_families
def test_the_blend_check_breaks_against_the_other_book(short):
    """The probe has teeth both ways: the blended sleeve against build_book's z T breaks, and the
    z sleeve against the blend breaks. Fails before spec_targets existed."""
    on, off = _level_on(_spec()), _level_off(_spec())
    TB = bm.spec_targets(short["cut"], short["T"], on)
    with pytest.raises(bm.FidelityBreak):
        bm.fidelity(on, short["cut"], short["dates"], T=short["T"], first_break=True)
    with pytest.raises(bm.FidelityBreak):
        bm.fidelity(off, short["cut"], short["dates"], T=TB, first_break=True)


def test_spec_targets_refuses_a_family_map_that_is_not_the_trials(tmp_path):
    """The trial read the frozen CSV; the sleeve reads the spec's family_of. If they differ the
    probe would compare two books, so spec_targets refuses before reading any panel."""
    on = _level_on(_spec())
    fam = dict(on["frozen"]["level_signal"]["family_of"], ADX="preferred")
    bad = bm.with_keys(on, level_signal={"risk_share": 0.5, "family_of": fam})
    with pytest.raises(ValueError, match=r"differs from .* for \['ADX'\]"):
        bm.spec_targets(tmp_path, pd.DataFrame(), bad)
    with pytest.raises(ValueError, match="no level book"):
        bm.spec_targets(tmp_path, pd.DataFrame(), _level_off(_spec()), level_only=True)


def test_h11_reads_the_blended_book_against_raw_returns():
    """§6.3: C4's kill rule is rebuilt on the BLENDED spec book. With level_signal set, h11_reference
    reads tb["T_spec"] and checks it against the RAW returns, so a blended position on a name-day the
    z book never held, with no return, raises (H15) instead of meeting R0's zero. Without T_spec it
    refuses. Synthetic frames: a test of the construction, not a market."""
    from scripts.cef import band_frontier as bf
    idx = pd.bdate_range("2005-03-01", periods=30)
    cols = list(_spec()["frozen"]["universe"])[:4]
    T = pd.DataFrame(0.0, index=idx, columns=cols)
    T[cols[0]], T[cols[1]] = 0.3, -0.3
    TS = T.copy()
    TS[cols[2]], TS[cols[3]] = 0.2, -0.2
    R0 = pd.DataFrame(0.0, index=idx, columns=cols)
    raw = R0.copy()
    spec = _level_on(_spec())
    tb = {"T": T, "T_spec": TS, "R0": R0, "R0x": R0, "R_raw": raw, "Rx_raw": raw}
    got = bm.h11_reference(tb, spec)
    f = spec["frozen"]
    m, cap = float(f["sizing_multiplier"]), float(f["max_gross_stress"])
    pd.testing.assert_frame_equal(got["H"], m * bf.band_gross_capped(TS, float(f["band_width"]), cap / m))
    assert "level_signal (z_share 0.5)" in got["policy"]
    raw2 = raw.copy()
    raw2.loc[idx[10], cols[2]] = float("nan")
    with pytest.raises(c4.GateError, match="no primary return"):
        bm.h11_reference(dict(tb, R_raw=raw2, Rx_raw=raw2), spec)
    with pytest.raises(KeyError, match="T_spec"):
        bm.h11_reference({"T": T, "R0": R0, "R0x": R0}, spec)


@needs_families
def test_no_date_after_the_fit_is_compared_or_cut(short, tmp_path):
    with pytest.raises(AssertionError, match="after the fit end"):
        bm.fidelity(_spec(), short["cut"], [pd.Timestamp("2023-01-03")], T=short["T"])
    with pytest.raises(AssertionError, match="after the fit end"):
        bm.cut_families(tmp_path / "x", hi="2023-01-03")
    for f in bm.FAMILY_FILES:
        assert pd.to_datetime(pd.read_parquet(short["cut"] / f"{f}.parquet")["date"]).max() <= HI


# ---------------------------------------------------------------------------
# 5. the team lead's rulings of 2026-10-29, recorded where they are read
# ---------------------------------------------------------------------------

def test_h11_reads_the_spec_book_not_the_trials():
    """Ruling 1: paper trades the 1.90 book, so H11's percentile and drawdown stop read it."""
    assert bm.H11_BOOK == "spec_book"
    s = _spec()
    assert "1.90 SPEC BOOK" in s["kill_rule"] and "not the trial's 1.80 book" in s["kill_rule"]
    out = json.loads(bm.OUT_JSON.read_text())
    assert out["h11_reference"] == "spec_book" and out["spec_sha256"] == bm._sha(bm.SPEC_PATH)
    ref = out["lines"]["spec_book"]
    assert ref["role"].startswith("H11 REFERENCE")
    assert f"cap {s['frozen']['max_gross_stress']}" in ref["policy"]
    assert "NOT read by H11" in out["lines"]["trial_book"]["role"]


def test_the_rulings_are_in_the_notes_and_the_counter_stays():
    note = _spec()["frozen"]["_max_gross_stress_note"]
    for must in ("KEEP 1.90", "does NOT count as a CEF trial", "trial-50 precedent", "ARMING GATE",
                 "0.02632", "2023-26 returns are not read", "left for step 5's book json"):
        assert must in note, must
    assert "superseded 2026-10-30: the core's levels" in note       # ruling (4), then 2026-10-30
    assert "team lead 2026-10-29 left them to the book json" in _spec()["risk"]["_halve_drawdown_note"]
    # The cap spent no trial: the counter was 52 at the ruling, and the only trial since is
    # CEF trial 53, the vol-target raise (results/cef/PREREG_VOLTARGET_2026-10-30.md, approved
    # 2026-11-01), which does count, and CEF trial 54, C4's family-level signal
    # (results/cef/PREREG_C4_LEVEL_2026-11-02.md, approved 2026-11-03), which does too, and CEF
    # trial 55, the paper-only thin-session rule trade_eligible
    # (results/cef/PREREG_THIN_TRADE_ELIGIBLE_2026-11-03.md, approved 2026-11-03), which does too;
    # none of them is the cap. Re-read 2026-11-03 (CEF 54 -> 55). A further trial fails here:
    # re-read this line then.
    assert c4.cef_counter() == 55
    rs = (REPO / "docs" / "RESEARCH_STATE.md").read_text()
    assert "2026-10-29: C4's re-derived `max_gross_stress`" in rs and "CEF stays 52" in rs


def test_the_igr_seed_ruling_is_the_corrected_books_four_bars():
    """Ruling 5: the seed file loads where step 3 will pass it, holds exactly the 2026-10-19
    corrected book's four bars, and logs every replaced cell (corrected close = panel / 3)."""
    from scripts.cef.data_guards import load_bar_rulings
    R, doc = load_bar_rulings(bm.SEED_RULINGS)
    src = json.loads(c4.BAR_RULINGS.read_text())
    assert doc["bars"] == src["bars"] and len(R) == 4 and set(R["ticker"]) == {"IGR"}
    assert "accepts exactly the four cells" in doc["standing_rule"]
    assert doc["source_ruling"]["sha256"] == bm._sha(c4.BAR_RULINGS)
    assert [c["date"] for c in doc["cells"]] == list(bm.SEED_DATES)
    for c in doc["cells"]:
        assert set(c["columns"]) == set(bm.SEED_COLUMNS)
        k = 3.0
        assert abs(c["columns"]["close"]["corrected"] - c["columns"]["close"]["panel"] / k) <= bm.SEED_CLOSE_TOL


@needs_families
def test_the_guard_accepts_exactly_those_four_cells_and_nothing_else(tmp_path):
    from scripts.cef.data_guards import SpikeRevertError
    close, out, log = bm.families_guard(bm.SEED_RULINGS)
    assert sorted((r.ticker, str(pd.Timestamp(r.date).date())) for r in log.itertuples()) == \
        [("IGR", d) for d in bm.SEED_DATES]
    doc = json.loads(bm.SEED_RULINGS.read_text())
    for c in doc["cells"]:                                     # the logged panel values are the panel's
        assert close.loc[pd.Timestamp(c["date"]), "IGR"] == c["columns"]["close"]["panel"]
    short_doc = dict(doc, bars=doc["bars"][:3])                # one cell fewer: the fourth is unruled
    p = tmp_path / "three.json"
    p.write_text(json.dumps(short_doc))
    with pytest.raises(SpikeRevertError, match="no recorded ruling"):
        bm.families_guard(p)
    extra = dict(doc, bars=doc["bars"] + [dict(doc["bars"][0], date="2026-07-30", run_end="2026-07-30")])
    p.write_text(json.dumps(extra))                            # one cell more: a ruling with no bar
    with pytest.raises(SpikeRevertError, match="matches no"):
        bm.families_guard(p)


# ---------------------------------------------------------------------------
# the arming gate: the cap re-derived from a fresh account read (C4 integration)
# ---------------------------------------------------------------------------

def _probe(tmp_path, equity, maint, positions=(), book="c4"):
    p = tmp_path / f"probe_{book}.json"
    p.write_text(json.dumps({"book": book, "fetched_at_utc": "2026-10-30T21:00:00+00:00",
                             "account": {"equity": equity, "maintenance_margin": maint},
                             "positions": [{"symbol": s} for s in positions]}))
    return p


def test_recap_rederives_the_cap_from_the_probe_and_the_committed_w5(tmp_path):
    """Ruling 3: from a fresh read of the account's NLV and of the other book's
    margin. The ruled inputs ($100k, nothing else held) give the spec's 1.90 by
    the committed w5; $5,000 of the agent lab's margin moves it a step down, and
    the command says a new spec id is needed. A snapshot holding a C4 name is
    refused (M_other would include C4's own margin)."""
    r = bm.recap(_probe(tmp_path, "100000", "0"), 0.0)
    assert r["cap"] == r["spec_cap"] == 1.90 and r["same_as_spec"]
    assert r["w5"] == json.loads(bm.OUT_JSON.read_text())["cap"]["w5"]
    r = bm.recap(_probe(tmp_path, "100000", "5000", positions=("SPY",)), 0.0)
    assert r["cap"] == 1.80 and not r["same_as_spec"] and r["positions"] == 1
    assert bm.main(["recap", "--probe", str(_probe(tmp_path, "100000", "5000")),
                    "--mark-sensitivity", "0"]) == 1
    with pytest.raises(ValueError, match="holds C4 names"):
        bm.recap(_probe(tmp_path, "100000", "0", positions=("ADX",)), 0.0)
    with pytest.raises(ValueError, match="not c4"):
        bm.recap(_probe(tmp_path, "100000", "0", book="cef"), 0.0)
    with pytest.raises(ValueError, match="maintenance_margin"):
        bm.recap(_probe(tmp_path, "100000", None), 0.0)
    with pytest.raises(SystemExit):
        bm.main(["recap", "--probe", str(_probe(tmp_path, "100000", "0"))])   # no default mark
