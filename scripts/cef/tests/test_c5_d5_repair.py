"""Trial C5, stage 8: the D-5 repair the team lead ruled on 2026-10-19.

WHY THESE TESTS. Stage 8 (the 2023-26 holdout) halted on 2026-10-15 before the
holdout gain was formed: 9 of 4,858 WIDE material trade name-days had no panel
close (class D-5), above the 0.1% halt
(`results/cef/c5/c5_holdout_halt_output_2026-10-15.txt`). The ruling
(PREREG_C5's dated amendment of 2026-10-19): a D-5 name-day takes the NYSE
closing print when that print and a second independent close agree within
$0.005 + 1e-6, mirroring D-6's two-source rule; a D-5 name-day without two
agreeing sources still counts toward the halt.

The ways to get that wrong silently, each pinned below:

* not repairing at all -- the 2026-10-15 behaviour, where a repairable
  name-day still halts the stage and earns no gain. The checks are run against
  that version too and must FAIL on it (a test that passes on the old code is
  not a test of the repair);
* repairing from ONE source, or from two that disagree -- the single-vendor
  number this desk has been burnt by;
* touching a name-day that HAS a panel close (that is D-6's job, applied to
  the frozen copy already), or reading the tolerance as a strict $0.005 on
  float32-stored prices (ruling 2 of 2026-10-14);
* a second source that differs from the one the holdout's freeze checked D-6
  with (CRSP through 2024, CEFConnect after);
* opening the holdout a second time.

Synthetic frames only: statements about the code, never about any fund or
market. Nothing reads `data/`, the frozen caches or the network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef import band_frontier as bf
from scripts.cef import c5_open_auction as M

COLS = ["A", "B", "C", "D", "E"]
IDX = pd.bdate_range("2026-02-02", periods=12)
S = 6                       # the session whose OPEN fills the trade decided at S-1
OPEN, PANEL, NYSE = 19.80, 20.00, 20.10


def _nan():
    return pd.DataFrame(np.nan, index=IDX, columns=COLS)


def _frames(second_row):
    """One trade, decided at S-1, filled at the open of S: A, B, C, D material (0.10),
    E small (0.001). A, B, C and E have no panel close on S; D has one. The NYSE
    closing print exists for all five; `second_row` is the second source on S."""
    H = pd.DataFrame(0.0, index=IDX, columns=COLS)
    H.iloc[S - 1:] = [0.10, -0.10, 0.10, 0.10, 0.001]
    C = pd.DataFrame(PANEL, index=IDX, columns=COLS)
    C.iloc[S, [0, 1, 2, 4]] = np.nan
    O = pd.DataFrame(OPEN, index=IDX, columns=COLS)
    nyse = _nan()
    nyse.iloc[S] = NYSE
    second = _nan()
    second.iloc[S] = second_row
    return dict(H=H, C=C, O=O, nyse=nyse, second=second)


# A agrees at exactly half a cent (ruling 2), B disagrees, C has one source only,
# D has a panel close (never touched), E (a small trade) agrees exactly.
MIXED = [NYSE + 0.005, NYSE + 0.02, np.nan, NYSE + 0.50, NYSE]


def _run(f):
    n = _nan()
    return M.stage8_classes({"WIDE": f["H"], "deployed": f["H"]}, f["O"], _nan(), f["C"], f["nyse"],
                            f["second"], n, n, n, n, IDX)


def _no_repair(C, close_nyse, second, tol=M.TOL):
    """The 2026-10-15 behaviour: no cell is ever filled, every missing close is D-5."""
    return C, C.isna() & False, C.isna()


def _check_mixed(out, f):
    d = IDX[S]
    rep, unres = out["repaired"], out["unresolved"]
    assert sorted(rep.columns[rep.loc[d]]) == ["A", "E"]
    assert sorted(unres.columns[unres.loc[d]]) == ["B", "C"]
    assert out["C_rep"].at[d, "A"] == NYSE and out["C_rep"].at[d, "D"] == PANEL     # D keeps its own close
    w = out["cls"]["WIDE"]
    assert (w["material"], w["D5_as_counted_2026_10_15"], w["D5_resolved_by_repair"], w["D5"]) == (4, 3, 1, 2)
    assert w["small_trade_name_days_repaired"] == 1
    assert any(h.startswith("D-5 (WIDE)") for h in out["halts"])                     # B and C still halt
    RS = out["RS"]
    assert RS.at[d, "A"] == pytest.approx(NYSE / OPEN - 1) and RS.at[d, "E"] == pytest.approx(NYSE / OPEN - 1)
    assert RS.at[d, "B"] == 0.0 and RS.at[d, "C"] == 0.0
    assert out["no_cross"].at[d, "B"] and out["no_cross"].at[d, "C"] and not out["no_cross"].at[d, "A"]
    G = bf.open_fill_gain(f["H"], RS)
    want = 0.10 * (NYSE / OPEN - 1) + 0.10 * (PANEL / OPEN - 1) + 0.001 * (NYSE / OPEN - 1)
    assert G.loc[d] == pytest.approx(want, abs=1e-15)
    assert (G.drop(d) == 0.0).all()


def test_repair_fills_only_two_agreeing_sources_and_the_rest_still_halts():
    f = _frames(MIXED)
    _check_mixed(_run(f), f)


def test_the_checks_fail_against_the_2026_10_15_behaviour(monkeypatch):
    f = _frames(MIXED)
    monkeypatch.setattr(M, "d5_repair", _no_repair)
    with pytest.raises(AssertionError):
        _check_mixed(_run(f), f)


def test_all_repairable_means_no_d5_halt_and_the_gain_uses_the_nyse_print(monkeypatch):
    f = _frames([NYSE, NYSE - 0.004, NYSE + 0.005, NYSE, NYSE])
    out = _run(f)
    w = out["cls"]["WIDE"]
    assert (w["D5"], w["D5_resolved_by_repair"], w["D5_rate"]) == (0, 3, 0.0)
    assert out["halts"] == []
    d = IDX[S]
    for t in ("A", "B", "C", "E"):
        assert out["RS"].at[d, t] == pytest.approx(NYSE / OPEN - 1)
    assert out["RS"].at[d, "D"] == pytest.approx(PANEL / OPEN - 1)
    # the 2026-10-15 behaviour on the same frames: it halts, and the four legs earn nothing
    monkeypatch.setattr(M, "d5_repair", _no_repair)
    old = _run(f)
    assert old["cls"]["WIDE"]["D5"] == 3 and any(h.startswith("D-5 (WIDE)") for h in old["halts"])
    assert all(old["RS"].at[d, t] == 0.0 for t in ("A", "B", "C", "E"))


def test_d5_repair_contract():
    f = _frames(MIXED)
    C2, rep, unres = M.d5_repair(f["C"], f["nyse"], f["second"])
    d = IDX[S]
    assert not rep.at[d, "D"] and C2.at[d, "D"] == PANEL           # a panel close is never replaced here
    assert (C2.drop(d) == PANEL).all().all()                         # nothing outside the missing cells moves
    assert (rep | unres).equals(f["C"].isna())                       # every missing cell is one or the other
    # the tolerance is ruling 2's: half a cent agrees, half a cent plus 2e-6 does not
    s2 = f["second"].copy()
    s2.at[d, "A"] = NYSE + 0.005 + 2e-6
    assert not M.d5_repair(f["C"], f["nyse"], s2)[1].at[d, "A"]
    # one source alone never fills, whichever source it is
    n2 = f["nyse"].copy()
    n2.at[d, "E"] = np.nan
    _, rep2, unres2 = M.d5_repair(f["C"], n2, f["second"])
    assert not rep2.at[d, "E"] and unres2.at[d, "E"]
    with pytest.raises(ValueError):
        M.d5_repair(f["C"], f["nyse"].iloc[:-1], f["second"])


def test_second_source_is_crsp_through_2024_then_cefconnect():
    idx = pd.DatetimeIndex(["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"])
    U = ["X", "Y"]
    crsp = pd.DataFrame({"date": list(idx[:2]) * 2 + [idx[2]], "ticker": ["X", "X", "Y", "Y", "X"],
                         "prc": [-10.0, 10.1, 5.0, 5.1, 99.0]})    # negative prc is a bid/ask midpoint: |prc|
    cc = pd.DataFrame({"date": [idx[1], idx[2], idx[3], idx[3], idx[2]], "ticker": ["X", "X", "X", "X", "Y"],
                       "close_cc": [77.0, 10.2, 10.3, 10.4, 5.2], "window": ["1Y", "1Y", "1Y", "All", "All"]})
    sec, amb = M.holdout_second_close(idx, U, crsp, cc)
    assert sec.at[idx[0], "X"] == 10.0 and sec.at[idx[1], "X"] == 10.1   # CRSP to 2024-12-31, never CEFConnect
    assert sec.at[idx[2], "X"] == 10.2                                    # CEFConnect after, never CRSP
    assert sec.at[idx[2], "Y"] == 5.2                                     # the weekly window where alone
    assert np.isnan(sec.at[idx[3], "X"]) and amb.at[idx[3], "X"]          # two windows disagree: neither used
    assert np.isnan(sec.at[idx[3], "Y"])


def test_holdout_is_opened_once(monkeypatch, tmp_path):
    done = tmp_path / "C5_HOLDOUT_RESULT.json"
    done.write_text("{}")
    monkeypatch.setattr(M, "H_RESULT", done)
    monkeypatch.setattr(M, "REPO", tmp_path)

    def boom():
        raise AssertionError("holdout() must not run once a result exists")

    monkeypatch.setattr(M, "holdout", boom)
    monkeypatch.setattr(M, "OUT_DIR", tmp_path)
    assert M.main(["holdout"]) == 2
