"""The XASSET protocol module on synthetic inputs: claims about the code, not the market.

Covers the alignment rules a trial's verdict rests on: r_f strictly before its
session; the eligibility rule equal to slate_feasibility's; the P&L window from
the first decision + 2 sessions; coverage raising when a held name has no
return; the stationary bootstrap's reproducibility and block length; the DSR
inputs pinned as validate.py does; and the regression refusing missing rows.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.xasset import protocol as P
from scripts.xasset import slate_feasibility as sf


def test_risk_free_is_strictly_before(tmp_path):
    cal = pd.bdate_range("2021-01-04", "2021-01-15")
    f = pd.DataFrame({"date": pd.to_datetime(["2020-12-31", "2021-01-05", "2021-01-08", "2021-01-11"]),
                      "value": [1.0, 2.0, 3.0, 4.0]})
    path = tmp_path / "dgs.parquet"
    f.to_parquet(path)
    rf = P.risk_free(cal, path)
    # 01-05 uses 12-31's value (01-05's own is not strictly before); 01-06 uses 01-05's
    assert rf.loc["2021-01-05"] == pytest.approx(1.0 / 100 / 252)
    assert rf.loc["2021-01-06"] == pytest.approx(2.0 / 100 / 252)
    assert rf.loc["2021-01-11"] == pytest.approx(3.0 / 100 / 252)
    assert rf.loc["2021-01-12"] == pytest.approx(4.0 / 100 / 252)
    late = tmp_path / "late.parquet"
    f[f.date > "2021-01-04"].to_parquet(late)
    with pytest.raises(P.ProtocolError):
        P.risk_free(cal, late)


def test_eligibility_matches_slate_feasibility():
    cal = pd.bdate_range("2000-01-03", "2003-12-31")
    firsts = {"A": pd.Timestamp("2000-01-03"), "B": pd.Timestamp("2000-06-01"),
              "C": pd.Timestamp("2002-01-01")}
    me = P.month_ends(cal)
    first_dec, _, _ = sf.fit_window(["A", "B", "C"], 12, "half", {k: v.date() for k, v in firsts.items()}, cal)
    E = pd.Timestamp(first_dec)
    assert sorted(P.eligible_at(E, ["A", "B", "C"], firsts, cal, me, 12)) == ["A", "B"]
    prev = me[me.get_loc(E) - 1]
    assert P.eligible_at(prev, ["A", "B", "C"], firsts, cal, me, 12) == ["A"]


def test_pnl_window_starts_two_sessions_after_decision():
    cal = pd.bdate_range("2022-12-01", "2023-01-31")
    w = P.pnl_window(pd.Timestamp("2022-12-09"), cal)
    assert w[0] == pd.Timestamp("2022-12-13") and w[-1] == P.FIT_END


def test_assert_covered_raises_on_held_name_without_return():
    idx = pd.bdate_range("2021-01-04", periods=6)
    H = pd.DataFrame({"A": [1.0] * 6, "B": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]}, index=idx)
    Rx = pd.DataFrame({"A": 0.001, "B": [np.nan] * 6}, index=idx)
    with pytest.raises(P.ProtocolError):
        P.run(H, Rx, "t")                      # B decided row 3, held (earning) row 5: no return there
    Rx2 = Rx.copy()
    Rx2.loc[idx[5], "B"] = 0.0
    P.run(H, Rx2, "t")                         # covered now (rows 0-4 do not hold B): no raise
    # an UNHELD name with no return is fine
    H2 = H.copy()
    H2["B"] = 0.0
    P.run(H2, Rx, "t")


def test_stationary_bootstrap_reproducible_and_centred():
    rng = np.random.default_rng(0)
    x = rng.normal(0.001, 0.01, 1500)
    m1, s1 = P.stationary_bootstrap(x, 21, 400, 7)
    m2, s2 = P.stationary_bootstrap(x, 21, 400, 7)
    assert np.array_equal(m1, m2) and np.array_equal(s1, s2)
    assert abs(m1.mean() - x.mean()) < 3 * x.std() / np.sqrt(len(x))
    # block structure: an AR(1) series' bootstrap sd of the mean is larger with
    # long blocks than with blocks of 1 (which destroy the dependence)
    e = rng.normal(0, 1, 3000)
    y = np.empty(3000)
    y[0] = e[0]
    for t in range(1, 3000):
        y[t] = 0.8 * y[t - 1] + e[t]
    mb, _ = P.stationary_bootstrap(y, 21, 300, 1)
    m1b, _ = P.stationary_bootstrap(y, 1, 300, 1)
    assert mb.std() > 1.8 * m1b.std()


def test_dsr_inputs_pinned_as_validate():
    from scripts.cef.validate import _dsr
    rng = np.random.default_rng(3)
    x = pd.Series(rng.standard_t(5, 3000) * 0.004 + 0.0004,
                  index=pd.bdate_range("2010-01-01", periods=3000))
    d = P.dsr(x, 4)
    r = x.values
    want, _, _ = _dsr(x.mean() / x.std() * np.sqrt(252), len(r), pd.Series(r).skew(),
                      pd.Series(r).kurt() + 3.0, 4)
    assert d["dsr"] == pytest.approx(want)
    assert P.bar(x)["agenda_reading_bar"] == pytest.approx(np.sqrt(2 * np.log(4)))


def test_ols_hac_refuses_missing_rows_and_recovers_betas():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2015-01-01", periods=2000)
    X = pd.DataFrame({"F1": rng.normal(0, 0.01, 2000), "F2": rng.normal(0, 0.01, 2000)}, index=idx)
    y = 0.0002 + 0.3 * X["F1"] - 0.05 * X["F2"] + rng.normal(0, 0.002, 2000)
    r = P.ols_hac(y, X, 21, 252)
    assert r["betas"]["F1"]["beta"] == pytest.approx(0.3, abs=0.02)
    assert r["alpha_pct_yr"] == pytest.approx(0.0002 * 252 * 100, abs=2.0)
    assert set(r["betas"]["F1"]) >= {"beta", "t", "ci95", "vif"}
    v = P.d4_verdict(r)
    assert v["betas_ok"] is False and v["largest_beta"][0] == "F1"
    X.iloc[10, 0] = np.nan
    with pytest.raises(P.ProtocolError):
        P.ols_hac(y, X, 21, 252)


def test_size_k_hits_the_pinned_vol_and_cap_only_scales():
    rng = np.random.default_rng(9)
    idx = pd.bdate_range("2010-01-01", "2012-12-31")
    Rx = pd.DataFrame(rng.normal(0, 0.01, (len(idx), 2)), index=idx, columns=["A", "B"])
    H = pd.DataFrame({"A": 1.0, "B": -1.0}, index=idx)
    win = idx[2:]
    s = P.size(H, Rx, win, "t")
    pnl = P.run(s["H_sized"], Rx, "t")["pnl"].reindex(win)
    assert pnl.std() * np.sqrt(252) == pytest.approx(P.PINNED_VOL_TARGET)
    g = s["H_trad"].abs().sum(axis=1)
    assert (g <= P.PINNED_MAX_GROSS + 1e-12).all()
    ratio = (s["H_trad"]["A"] / s["H_sized"]["A"])
    assert np.allclose(ratio, s["H_trad"]["B"] / s["H_sized"]["B"])


def test_monthly_regression_lag_rule():
    assert int(np.floor(4 * (176 / 100) ** (2 / 9))) == 4
    assert int(np.floor(4 * (244 / 100) ** (2 / 9))) == 4


def test_aqr_regression_on_monthly_periods(tmp_path, monkeypatch):
    """R-AQR regresses a MONTHLY (PeriodIndex) series; partial first/last months are
    dropped; the factor columns are read from caches shaped like the fetcher's."""
    rng = np.random.default_rng(4)
    months = pd.date_range("2005-01-31", "2023-06-30", freq="ME")
    ts = pd.DataFrame({"date": months, **{c: rng.normal(0, 0.02, len(months)) for c in
                                          ["TSMOM", "TSMOM^CM", "TSMOM^EQ", "TSMOM^FI", "TSMOM^FX"]}})
    vm = pd.DataFrame({"date": months, "MOM": rng.normal(0, 0.02, len(months)),
                       "MOMLS_VME_FI": rng.normal(0, 0.02, len(months))})
    for df in (ts, vm):
        df["file_sha256"], df["last_data_month"] = "x" * 64, "2023-06"
    ts.to_parquet(tmp_path / "t.parquet")
    vm.to_parquet(tmp_path / "v.parquet")
    monkeypatch.setattr(P, "AQR_TSMOM", tmp_path / "t.parquet")
    monkeypatch.setattr(P, "AQR_VME", tmp_path / "v.parquet")
    cal = pd.bdate_range("2008-01-01", "2022-12-30")
    pnl = pd.Series(rng.normal(0, 0.004, len(cal)), index=cal).loc["2008-05-02":]
    r = P.aqr_regression(pnl, ["TSMOM^FI", "TSMOM", "VME_MOM"], cal)
    assert r["start"] == "2008-06" and r["end"] == "2022-12" and r["lags"] == 4
    assert set(r["betas"]) == {"TSMOM^FI", "TSMOM", "VME_MOM"}
