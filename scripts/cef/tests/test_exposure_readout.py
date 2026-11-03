"""The exposure readout (`scripts/cef/exposure_readout.py`), on synthetic data only.

These test the CODE: the lookahead assert, the Dimson aggregation, the orthogonalisation,
the exposure arithmetic and its signs, the review flag, and every refusal path. They make
no claim about any fund or any market (CLAUDE.md: synthetic data tests a method, never
the world). No panel is read, no network is touched, and no account data is used.

Each test was run against a deliberately broken copy of the module (window including t,
lag 0 only, unsigned value, signed contribution, a default equity, the refusals and the
finite-data check removed, the orthogonalisation turned off) and failed there; the
session that built this recorded that check.

The review of 2026-11-02 (finding 2) found eight more broken copies that passed: price-only
returns, the distribution over today's close, the split ratio inverted or ignored, factor
vol not annualised or annualised by 360, a t-stat SE from the residual-covariance diagonal
only, group exposures on lag-0 betas, and P&L booked across a gap in the positions dates.
The tests under "arithmetic the first suite did not reach" kill each of them, and the tests
of the guard, equity, plateau, lag-rule and cross-check fixes each kill a copy with that fix
undone (checked 2026-11-02 by loading each broken copy in place of the module). One
survivor is equivalent, not missed: `total_factor_vol` with the covariance's diagonal only.
The orthogonal factors are uncorrelated on the window by construction, so the two agree.
"""
from __future__ import annotations

import ast
import datetime as dt
import math
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.cef import exposure_readout as ER

ETFS = list(ER.FACTOR_ETFS)
SESS = ER.nyse_sessions(dt.date(2020, 1, 2), dt.date(2020, 12, 31))
W, L = 60, 3


def _factor_returns(seed=0, sessions=SESS, corr=True):
    """Four ETF return series with realistic collinearity (MUB and HYG load on IEF; BKLN
    on HYG), so that the orthogonalisation has something to do."""
    rng = np.random.default_rng(seed)
    n = len(sessions)
    z = rng.normal(0, 0.004, size=(n, 4))
    ief = z[:, 0]
    hyg = z[:, 1] + (0.3 * ief if corr else 0)
    mub = z[:, 2] + (0.5 * ief + 0.2 * hyg if corr else 0)
    bkln = z[:, 3] + (0.6 * hyg if corr else 0)
    return pd.DataFrame({"IEF": ief, "HYG": hyg, "MUB": mub, "BKLN": bkln}, index=sessions)


def _lagged(s: pd.Series, l: int) -> pd.Series:
    return s.shift(l)


def _returns_with_names(seed=0):
    """R with the four ETFs and two names whose returns are exact lagged responses."""
    E = _factor_returns(seed)
    R = E.copy()
    # AAA: a pure TERM response spread over lags 0..3 (sum 1.1)
    R["AAA"] = (0.3 * E["IEF"] + 0.5 * _lagged(E["IEF"], 1) + 0.2 * _lagged(E["IEF"], 2)
                + 0.1 * _lagged(E["IEF"], 3))
    # BBB: a raw-MUB response at lag 1 plus small idiosyncratic noise
    rng = np.random.default_rng(seed + 1)
    R["BBB"] = 0.8 * _lagged(E["MUB"], 1) + rng.normal(0, 1e-4, len(E))
    return R


# --------------------------------------------------------------------------- H7

def test_assert_strictly_before_raises_on_a_window_reaching_t():
    t = SESS[100]
    ER.assert_strictly_before(SESS[40:100], t, "w")              # ends t-1: fine
    with pytest.raises(ER.LookaheadError, match="strictly before"):
        ER.assert_strictly_before(SESS[41:101], t, "w")          # includes t
    with pytest.raises(ER.LookaheadError):
        ER.assert_strictly_before(SESS[41:120], t, "w")          # runs past t
    with pytest.raises(ER.LookaheadError, match="empty"):
        ER.assert_strictly_before(SESS[:0], t, "w")


def test_window_rows_end_strictly_before_t_and_reach_the_lags():
    t = SESS[100]
    y, f = ER.window_rows(SESS, t, W, L)
    assert len(y) == W and len(f) == W + L
    assert y.max() < t and f.max() < t
    assert y[-1] == SESS[99] and f[0] == SESS[100 - W - L]


def test_fit_is_unchanged_by_any_data_on_or_after_t():
    """The readout's no-lookahead property, tested on output, not on the assert: scramble
    every return dated t or later and the fit used on t must not move by a bit."""
    R = _returns_with_names()
    t = SESS[150]
    a = ER.fit_window(R, SESS, t, ["AAA", "BBB"], window=W, lags=L)
    R2 = R.copy()
    rng = np.random.default_rng(99)
    R2.loc[t:] = rng.normal(0, 0.05, size=R2.loc[t:].shape)
    b = ER.fit_window(R2, SESS, t, ["AAA", "BBB"], window=W, lags=L)
    pd.testing.assert_frame_equal(a.beta, b.beta, check_exact=True)
    pd.testing.assert_frame_equal(a.M, b.M, check_exact=True)
    pd.testing.assert_series_equal(a.factor_vol, b.factor_vol, check_exact=True)
    assert a.y_dates.max() < t


# --------------------------------------------------------------------------- Dimson

def test_dimson_sum_recovers_a_response_spread_over_lags():
    R = _returns_with_names()
    fit = ER.fit_window(R, SESS, SESS[150], ["AAA"], window=W, lags=L)
    lags = [fit.beta.at["AAA", ("TERM", l)] for l in range(L + 1)]
    assert lags == pytest.approx([0.3, 0.5, 0.2, 0.1], abs=1e-9)
    assert fit.beta_sum.at["AAA", "TERM"] == pytest.approx(1.1, abs=1e-9)
    for k in ("CREDIT", "MUNI", "LOANS"):
        assert fit.beta_sum.at["AAA", k] == pytest.approx(0.0, abs=1e-9)


def test_dimson_sum_with_too_few_lags_misses_the_tail():
    """Guards the arithmetic, not the lag choice: with lags=1 the sum cannot see lags 2-3."""
    R = _returns_with_names()
    fit = ER.fit_window(R, SESS, SESS[150], ["AAA"], window=W, lags=1)
    assert fit.beta_sum.at["AAA", "TERM"] == pytest.approx(0.8, abs=0.05)


def test_ols_standard_error_identity_matches_statsmodels_for_one_name():
    sm = pytest.importorskip("statsmodels.api")
    R = _returns_with_names()
    t = SESS[150]
    fit = ER.fit_window(R, SESS, t, ["BBB"], window=W, lags=L)
    ex = ER.exposures(fit, pd.Series({"BBB": 1.0}), equity=None).set_index("factor")
    X, cols = ER.design((R.loc[fit.f_dates, ETFS] @ fit.M).set_axis(list(ER.FACTOR_NAMES), axis=1),
                        fit.y_dates, L)
    m = sm.OLS(R.loc[fit.y_dates, "BBB"].to_numpy(), X).fit()
    for k in ER.FACTOR_NAMES:
        a = np.array([1.0 if (c != "const" and c[0] == k) else 0.0 for c in cols])
        tt = m.t_test(a)
        assert ex.at[k, "t_stat"] == pytest.approx(float(np.ravel(tt.tvalue)[0]), rel=1e-8)


# --------------------------------------------------------------------------- orthogonalisation

def test_orthogonal_factors_are_uncorrelated_on_their_window():
    E = _factor_returns()
    M = ER.orthogonaliser(E.iloc[:W])
    F = E.iloc[:W] @ M
    C = np.cov(F.to_numpy().T)
    off = C - np.diag(np.diag(C))
    assert np.abs(off).max() < 1e-12 * np.abs(np.diag(C)).max() * 1e3
    assert list(M.columns) == list(ER.FACTOR_NAMES)
    assert all(M.at[e, f] == 1.0 for f, e in ER.FACTORS)
    # the raw ETFs here ARE correlated, so the orthogonaliser must have done something
    assert abs(np.corrcoef(E.iloc[:W]["IEF"], E.iloc[:W]["MUB"])[0, 1]) > 0.2


def test_total_factor_pnl_is_the_same_in_the_raw_basis():
    """Orthogonalising changes the split, never the total: E_orth . f_orth(t) equals the
    raw-ETF regression's summed betas . raw f(t), for any out-of-window day."""
    R = _returns_with_names()
    t = SESS[150]
    fit = ER.fit_window(R, SESS, t, ["BBB"], window=W, lags=L)
    v = pd.Series({"BBB": -2500.0})
    E = ER.exposures(fit, v, None).set_index("factor")["exposure_usd"]
    f_raw = R.loc[t, ETFS]
    total_orth = float(E.to_numpy() @ (f_raw.to_numpy() @ fit.M.to_numpy()))
    # the raw basis, fitted directly
    Er = R.loc[fit.f_dates, ETFS]
    Xr, cols = ER.design(Er, fit.y_dates, L)
    b = np.linalg.lstsq(Xr, R.loc[fit.y_dates, "BBB"].to_numpy(), rcond=None)[0]
    raw_sum = {e: sum(b[i] for i, c in enumerate(cols) if c != "const" and c[0] == e) for e in ETFS}
    total_raw = float(sum(-2500.0 * raw_sum[e] * f_raw[e] for e in ETFS))
    assert total_orth == pytest.approx(total_raw, rel=1e-9, abs=1e-12)


# --------------------------------------------------------------------------- exposure, signs, rule

def _fit_with(beta_sum: dict, vols: dict, names=("LNG", "SHT")):
    """A WindowFit with chosen summed betas (lag 0 only) and factor vols."""
    cols = ["const"] + [(k, l) for k in ER.FACTOR_NAMES for l in range(1)]
    idx = pd.MultiIndex.from_tuples(cols[1:], names=["factor", "lag"])
    beta = pd.DataFrame([[beta_sum[n][k] for k in ER.FACTOR_NAMES] for n in names],
                        index=list(names), columns=idx)
    bs = pd.DataFrame([[beta_sum[n][k] for k in ER.FACTOR_NAMES] for n in names],
                      index=list(names), columns=list(ER.FACTOR_NAMES))
    fv = pd.Series(vols)[list(ER.FACTOR_NAMES)]
    return ER.WindowFit(t=SESS[100], y_dates=SESS[40:100], f_dates=SESS[40:100],
                        M=pd.DataFrame(np.eye(4), index=ETFS, columns=list(ER.FACTOR_NAMES)),
                        beta=beta, beta_sum=bs, cols=cols, xtx_inv=np.eye(len(cols)),
                        resid_cov=pd.DataFrame(np.eye(len(names)) * 1e-4, index=list(names), columns=list(names)),
                        factor_vol=fv, factor_cov=pd.DataFrame(np.diag(fv ** 2), index=fv.index, columns=fv.index),
                        n_obs=60, lags=0)


BETAS = {"LNG": {"TERM": 0.1, "CREDIT": 1.0, "MUNI": 0.2, "LOANS": 0.5},
         "SHT": {"TERM": 0.6, "CREDIT": 0.5, "MUNI": 1.5, "LOANS": 0.1}}
VOLS = {"TERM": 0.05, "CREDIT": 0.06, "MUNI": 0.02, "LOANS": 0.03}


def test_exposure_is_signed_shares_times_close_times_beta():
    fit = _fit_with(BETAS, VOLS)
    shares = pd.Series({"LNG": 1000.0, "SHT": -2000.0})
    close = pd.Series({"LNG": 10.0, "SHT": 12.5})
    ex = ER.exposures(fit, shares * close, equity=100_000.0).set_index("factor")
    # MUNI: 10,000 x 0.2 + (-25,000) x 1.5 = -35,500: the short dominates, sign negative
    assert ex.at["MUNI", "exposure_usd"] == pytest.approx(10_000 * 0.2 - 25_000 * 1.5)
    assert ex.at["MUNI", "exposure_usd"] < 0
    assert ex.at["CREDIT", "exposure_usd"] == pytest.approx(10_000 * 1.0 - 25_000 * 0.5)
    assert ex.at["MUNI", "exposure_frac"] == pytest.approx(-35_500 / 100_000)
    # contribution uses |E|: a short exposure contributes risk, never negative risk
    assert ex.at["MUNI", "contrib_frac"] == pytest.approx(0.355 * 0.02)
    assert ex.at["MUNI", "contrib_usd"] == pytest.approx(35_500 * 0.02)
    assert ex.at["MUNI", "contrib_of_target"] == pytest.approx(0.355 * 0.02 / ER.VOL_TARGET)
    assert (ex["contrib_frac"] >= 0).all()


def test_review_flag_fires_above_the_line_on_a_short_exposure_and_not_below():
    """The line is REVIEW_FRACTION x the vol target. Equity is chosen so the short MUNI
    exposure sits just above it, then just below it."""
    fit = _fit_with(BETAS, VOLS)
    value = pd.Series({"LNG": 0.0, "SHT": -25_000.0})        # MUNI E = -37,500
    line = ER.REVIEW_FRACTION * ER.VOL_TARGET
    E_muni = -25_000.0 * 1.5
    eq_at_line = abs(E_muni) * VOLS["MUNI"] / line
    above = ER.exposures(fit, value, equity=eq_at_line * 0.99).set_index("factor")
    below = ER.exposures(fit, value, equity=eq_at_line * 1.01).set_index("factor")
    assert above.at["MUNI", "review"] == "REVIEW"
    assert below.at["MUNI", "review"] == "within"
    assert above.at["MUNI", "contrib_of_target"] > ER.REVIEW_FRACTION > below.at["MUNI", "contrib_of_target"]


def test_review_line_follows_the_vol_target_it_is_given():
    fit = _fit_with(BETAS, VOLS)
    value = pd.Series({"LNG": 0.0, "SHT": -25_000.0})
    eq = 100_000.0
    c = 37_500 / eq * VOLS["MUNI"]                            # 0.0075
    lo = ER.exposures(fit, value, eq, vol_target=c / ER.REVIEW_FRACTION * 1.01).set_index("factor")
    hi = ER.exposures(fit, value, eq, vol_target=c / ER.REVIEW_FRACTION * 0.99).set_index("factor")
    assert lo.at["MUNI", "review"] == "within" and hi.at["MUNI", "review"] == "REVIEW"


def test_no_equity_means_unmeasured_never_a_default_capital():
    fit = _fit_with(BETAS, VOLS)
    ex = ER.exposures(fit, pd.Series({"LNG": 5_000.0, "SHT": -25_000.0}), equity=None)
    assert (ex["review"] == "UNMEASURED").all()
    assert ex["exposure_frac"].isna().all() and ex["contrib_of_target"].isna().all()
    assert ex["exposure_usd"].notna().all()                   # dollars need no equity


def test_total_factor_vol_is_the_root_sum_of_squared_contributions_when_orthogonal():
    fit = _fit_with(BETAS, VOLS)
    ex = ER.exposures(fit, pd.Series({"LNG": 10_000.0, "SHT": -25_000.0}), 100_000.0).set_index("factor")
    tv = ER.total_factor_vol(fit, ex["exposure_usd"])
    assert tv == pytest.approx(math.sqrt((ex["contrib_usd"] ** 2).sum()))


# --------------------------------------------------------------------------- end to end

def _px_from_returns(R: pd.DataFrame, base=50.0) -> pd.DataFrame:
    rows = []
    for tk in R.columns:
        r = R[tk].fillna(0.0).to_numpy()
        close = base * np.cumprod(1.0 + r)
        rows.append(pd.DataFrame({"date": R.index, "ticker": tk, "close": close, "adj_close": close,
                                  "dividend": 0.0, "split": 0.0}))
    return pd.concat(rows, ignore_index=True)


def _positions(dates, book, equity=100_000.0):
    return pd.DataFrame([dict(date=d, symbol=s, shares=q, equity=equity) for d in dates for s, q in book.items()])


def test_readout_factor_pnl_is_previous_exposure_times_todays_factor_return():
    R = _returns_with_names()
    px = _px_from_returns(R)
    dates = list(SESS[150:153])
    P = _positions(dates, {"AAA": 1000.0, "BBB": -400.0})
    ro = ER.readout(px, P, {"AAA": "multi", "BBB": "muni"}, window=W, lags=L)
    R2, C2, _ = ER.returns_panel(px)
    fp = ro.factor_pnl[ro.factor_pnl["scope"] == "book"]
    assert sorted(fp["date"].unique()) == dates[1:]           # needs the previous session's book
    for t_prev, t in zip(dates[:-1], dates[1:]):
        fit = ER.fit_window(R2, SESS, t_prev, ["AAA", "BBB"], window=W, lags=L)
        v = pd.Series({"AAA": 1000.0, "BBB": -400.0}) * C2.loc[t_prev, ["AAA", "BBB"]]
        E = v.to_numpy() @ fit.beta_sum.to_numpy()
        f = R2.loc[t, ETFS].to_numpy() @ fit.M.to_numpy()
        got = fp[fp["date"] == t].set_index("factor")["pnl_summed"].reindex(list(ER.FACTOR_NAMES))
        assert got.to_numpy() == pytest.approx(E * f, rel=1e-10, abs=1e-12)
    # group scopes add up to the book
    g = ro.factor_pnl[ro.factor_pnl["scope"] != "book"].groupby(["date", "factor"])[["pnl_summed", "pnl_lagdist"]].sum()
    b = fp.set_index(["date", "factor"])[["pnl_summed", "pnl_lagdist"]]
    pd.testing.assert_frame_equal(g.sort_index(), b.sort_index(), check_exact=False, rtol=1e-10)


def test_readout_lag_distributed_pnl_reproduces_an_exact_lagged_response():
    """AAA's return is an exact lag-0..3 function of IEF, so the lag-distributed factor
    P&L of a 1-share AAA book on t equals that share's price change on t."""
    R = _returns_with_names()
    px = _px_from_returns(R)
    dates = list(SESS[150:152])
    ro = ER.readout(px, _positions(dates, {"AAA": 1.0}), {"AAA": "multi"}, window=W, lags=L)
    R2, C2, _ = ER.returns_panel(px)
    fp = ro.factor_pnl[(ro.factor_pnl["scope"] == "book")]
    pnl = fp["pnl_lagdist"].sum()
    assert pnl == pytest.approx(C2.loc[dates[1], "AAA"] - C2.loc[dates[0], "AAA"], rel=1e-8)


# --------------------------------------------------------------------------- arithmetic the
# first suite did not reach (review 2026-11-02, finding 2: eight mutants of these lines passed)

def _flat_px(ticker="AAA", n=10, close=50.0):
    d = SESS[:n]
    return pd.DataFrame({"date": d, "ticker": ticker, "close": close, "adj_close": close,
                         "dividend": 0.0, "split": 0.0})


def test_total_return_adds_the_distribution_over_the_previous_close():
    """H15: r = close_t / close_{t-1} - 1 + D_t / close_{t-1}, on the ex-date."""
    px = _flat_px()
    m = px["date"] == SESS[5]
    px.loc[m, "close"] = 49.6
    px.loc[m, "dividend"] = 0.5
    R, _, _ = ER.returns_panel(px)
    assert R.at[SESS[5], "AAA"] == pytest.approx((49.6 + 0.5) / 50.0 - 1.0, rel=1e-12, abs=1e-15)
    assert R.at[SESS[6], "AAA"] == pytest.approx(50.0 / 49.6 - 1.0, rel=1e-12)
    assert R.at[SESS[4], "AAA"] == 0.0 and np.isnan(R.at[SESS[0], "AAA"])


def test_total_return_multiplies_by_the_split_ratio_on_a_raw_close():
    """A 2-for-1 split on a raw (unadjusted) close: 50 -> 25.2 is a +0.8% day, not -49.6%."""
    px = _flat_px()
    m = px["date"] == SESS[5]
    px.loc[m, "close"] = 25.2
    px.loc[m, "split"] = 2.0
    px.loc[px["date"] > SESS[5], "close"] = 25.2
    R, _, _ = ER.returns_panel(px)
    assert R.at[SESS[5], "AAA"] == pytest.approx(25.2 * 2.0 / 50.0 - 1.0, rel=1e-12)
    assert R.at[SESS[6], "AAA"] == 0.0


def test_factor_vol_is_the_window_sd_of_the_orthogonal_factors_annualised_by_252():
    """sigma_k = sd(F_k on the W sessions before t) x sqrt(252): on the y rows only (not the
    W + L lagged rows), and annualised exactly once, by the desk's 252."""
    R = _returns_with_names()
    t = SESS[150]
    fit = ER.fit_window(R, SESS, t, ["AAA"], window=W, lags=L)
    F = R.loc[fit.y_dates, ETFS] @ ER.orthogonaliser(R.loc[fit.y_dates, ETFS])
    want = F.std(ddof=1).to_numpy() * math.sqrt(252)
    assert fit.factor_vol.to_numpy() == pytest.approx(want, rel=1e-12)
    assert np.diag(fit.factor_cov.to_numpy()) == pytest.approx(want ** 2, rel=1e-12)
    # and the readout's contribution uses that annualised vol
    px = _px_from_returns(R)
    ro = ER.readout(px, _positions([t], {"AAA": 100.0}), {"AAA": "multi"}, window=W, lags=L)
    R2, C2, _ = ER.returns_panel(px)
    fit2 = ER.fit_window(R2, SESS, t, ["AAA"], window=W, lags=L)
    F2 = R2.loc[fit2.y_dates, ETFS] @ fit2.M
    ex = ro.exposure.set_index("factor")
    E = 100.0 * C2.at[t, "AAA"] * fit2.beta_sum.loc["AAA"]
    for j, k in enumerate(ER.FACTOR_NAMES):
        sig = float(F2.iloc[:, j].std(ddof=1)) * math.sqrt(252)
        assert ex.at[k, "factor_vol"] == pytest.approx(sig, rel=1e-12)
        assert ex.at[k, "contrib_frac"] == pytest.approx(abs(E[k]) / 100_000.0 * sig, rel=1e-10)


def _correlated_names(seed=7):
    """AAA and BBB plus two names CCC, DDD whose residuals share a common shock, so a
    portfolio's residual variance carries cross terms."""
    R = _returns_with_names(seed)
    rng = np.random.default_rng(seed + 10)
    common = rng.normal(0, 0.003, len(R))
    R["CCC"] = 0.5 * R["IEF"] + 0.2 * _lagged(R["HYG"], 1) + common + rng.normal(0, 0.001, len(R))
    R["DDD"] = 0.7 * _lagged(R["MUB"], 1) + 0.9 * common + rng.normal(0, 0.001, len(R))
    return R


def test_book_t_stat_equals_the_portfolio_return_regression_with_correlated_residuals():
    """t = E_k / SE with SE^2 = (v' S v) a' (X'X)^-1 a is the OLS t-test on the portfolio's
    own return series v'Y: the cross-name residual covariance counts, not just its diagonal."""
    sm = pytest.importorskip("statsmodels.api")
    R = _correlated_names()
    t = SESS[150]
    names = ["CCC", "DDD"]
    fit = ER.fit_window(R, SESS, t, names, window=W, lags=L)
    v = pd.Series({"CCC": 3_000.0, "DDD": 2_000.0})          # same sign: the common shock adds
    ex = ER.exposures(fit, v, equity=None).set_index("factor")
    X, cols = ER.design((R.loc[fit.f_dates, ETFS] @ fit.M).set_axis(list(ER.FACTOR_NAMES), axis=1),
                        fit.y_dates, L)
    port = R.loc[fit.y_dates, names].to_numpy() @ v[names].to_numpy()
    m = sm.OLS(port, X).fit()
    for k in ER.FACTOR_NAMES:
        a = np.array([1.0 if (c != "const" and c[0] == k) else 0.0 for c in cols])
        assert ex.at[k, "t_stat"] == pytest.approx(float(np.ravel(m.t_test(a).tvalue)[0]), rel=1e-8)
    # the residuals really are correlated, so a diagonal-only SE would differ
    S = fit.resid_cov.to_numpy()
    assert S[0, 1] / math.sqrt(S[0, 0] * S[1, 1]) > 0.5


def test_group_exposures_use_the_summed_dimson_betas_and_add_up_to_the_book():
    R = _correlated_names()
    px = _px_from_returns(R)
    dates = list(SESS[150:152])
    book = {"AAA": 1000.0, "CCC": 500.0, "DDD": -800.0}
    groups = {"AAA": "multi", "CCC": "multi", "DDD": "muni"}
    ro = ER.readout(px, _positions(dates, book), groups, window=W, lags=L)
    R2, C2, _ = ER.returns_panel(px)
    for t in dates:
        fit = ER.fit_window(R2, SESS, t, list(book), window=W, lags=L)
        v = pd.Series(book) * C2.loc[t, list(book)]
        g = ro.by_group[ro.by_group["date"] == t].set_index(["grp", "factor"])["exposure_usd"]
        for grp in ("multi", "muni"):
            mem = [s for s in book if groups[s] == grp]
            want = v[mem].to_numpy() @ fit.beta_sum.loc[mem].to_numpy()
            got = g.xs(grp, level="grp").reindex(list(ER.FACTOR_NAMES)).to_numpy()
            assert got == pytest.approx(want, rel=1e-10)
        tot = g.groupby(level="factor").sum().reindex(list(ER.FACTOR_NAMES)).to_numpy()
        ex = ro.exposure[ro.exposure["date"] == t].set_index("factor")["exposure_usd"]
        assert tot == pytest.approx(ex.reindex(list(ER.FACTOR_NAMES)).to_numpy(), rel=1e-10)
    # AAA's response is spread over lags, so a lag-0 beta would not be the sum
    assert abs(fit.beta.at["AAA", ("TERM", 0)] - fit.beta_sum.at["AAA", "TERM"]) > 0.5


def test_factor_pnl_needs_the_immediately_previous_session_in_the_positions():
    """E(t-1) x f(t) needs the book at t-1's close. Across a gap in the positions dates no
    P&L is booked: an older book is not t-1's book."""
    R = _returns_with_names()
    px = _px_from_returns(R)
    gap = [SESS[150], SESS[152]]
    ro = ER.readout(px, _positions(gap, {"AAA": 1.0}), {"AAA": "multi"}, window=W, lags=L)
    assert len(ro.factor_pnl) == 0
    some = [SESS[150], SESS[151], SESS[153]]
    ro = ER.readout(px, _positions(some, {"AAA": 1.0}), {"AAA": "multi"}, window=W, lags=L)
    assert sorted(ro.factor_pnl["date"].unique()) == [SESS[151]]
    assert set(ro.factor_pnl["prev"]) == {SESS[150]}


# --------------------------------------------------------------------------- plateau check

def test_plateau_check_brackets_w_and_l_and_reports_review_counts():
    R = _returns_with_names()
    px = _px_from_returns(R)
    dates = list(SESS[150:153])
    P = _positions(dates, {"AAA": 20_000.0, "BBB": -40_000.0}, equity=100_000.0)
    groups = {"AAA": "multi", "BBB": "muni"}
    ro = ER.readout(px, P, groups, window=W, lags=L)
    rows = ER.plateau_check(px, P, groups, ro)
    runs = [(r["window"], r["lags"]) for r in rows]
    assert runs == [(W // 2, L), (W, L), (2 * W, L)] + [(W, l) for l in range(L + ER.PLATEAU_LAG_SPAN + 1)
                                                         if l != L]
    assert [r["adopted"] for r in rows] == [r == (W, L) for r in runs]
    adopted = rows[1]
    rev = ro.exposure[ro.exposure["review"] == "REVIEW"]
    assert adopted["review"] == {k: int(rev.loc[rev["factor"] == k, "date"].nunique()) for k in ER.FACTOR_NAMES}
    big = rev[rev["t_stat"].abs() >= 2.0]
    assert adopted["review_t2"] == {k: int(big.loc[big["factor"] == k, "date"].nunique()) for k in ER.FACTOR_NAMES}
    assert len(big) < len(rev)                                # the |t| filter bites on this book
    assert sum(adopted["review"].values()) > 0                # the book is large enough to flag
    assert adopted["book_summed"] == pytest.approx(
        ro.factor_pnl.loc[ro.factor_pnl["scope"] == "book", "pnl_summed"].sum())
    for r in rows[3:]:                                        # each lag row is its own readout
        other = ER.readout(px, P, groups, window=W, lags=r["lags"])
        assert r == dict(ER.plateau_summary(other), adopted=False)
    md = ER.summary_md(ro, {"asof": "x", "fetched_at_utc": "y"}, rows)
    assert "REVIEW dates TERM/CREDIT/MUNI/LOANS" in md and "(adopted)" in md


def test_plateau_counts_say_unmeasured_without_equity():
    R = _returns_with_names()
    px = _px_from_returns(R)
    P = _positions(list(SESS[150:152]), {"AAA": 1.0}).drop(columns=["equity"])
    ro = ER.readout(px, P, {"AAA": "multi"}, window=W, lags=L)
    s = ER.plateau_summary(ro)
    assert s["review"] is None and s["review_t2"] is None


# --------------------------------------------------------------------------- derive's lag rules

def test_lag_rule_helpers():
    single = {0: 43, 1: 14, 2: 10, 3: 7, 4: 2, 5: 12}
    assert ER._first_gap(single, 5) == 3
    assert ER._first_gap(single, 9) == 2
    assert ER._first_gap(single, 13) == 1
    assert ER._first_gap(single, 14) == 0
    assert ER._first_gap(single, 1) is None
    assert ER._smallest_within({0: 17, 1: 15, 2: 5, 3: 3}, 5) == 2
    assert ER._smallest_within({0: 17}, 5) is None
    assert ER._fmt_runs({b: ER._first_gap(single, b) for b in range(0, 16)}) == \
        "bound 0-1 -> L None; 2-6 -> L 3; 7-9 -> L 2; 10-13 -> L 1; 14+ -> L 0"


def test_lag_rule_counts_on_a_lagged_response():
    """A response at lags 0, 1 and (weakly) 2, none at 3. The lag-2 effect is set so its
    joint p-value sits well inside (0, 0.05), so the count follows the 5% level, not just a
    huge signal. Checks the counting, not any market."""
    pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(3)
    n = 2000
    F = pd.DataFrame(rng.normal(0, 0.01, (n, 4)), columns=list(ER.FACTOR_NAMES),
                     index=pd.RangeIndex(n))
    y = (2.0 * F["TERM"] + 1.5 * F["TERM"].shift(1) + 0.1 * F["TERM"].shift(2)
         + rng.normal(0, 0.011, n)).rename("y")
    m = ER._dimson_ols(y, F, 3)
    idx = list(m.params.index)
    Rm = np.zeros((4, len(idx)))
    for j, k in enumerate(ER.FACTOR_NAMES):
        Rm[j, idx.index(f"{k}_2")] = 1.0
    p2 = float(m.wald_test(Rm, scalar=True).pvalue)
    assert 1e-6 < p2 < 0.01                                   # moderate, by construction
    c = ER.lag_rule_counts({"X": m})
    assert c["joint"] == {0: 1, 1: 1, 2: 1, 3: 0}
    assert c["single"][0] >= 1 and c["single"][1] >= 1 and c["single"][2] >= 1
    assert c["tail"][0] == 1 and c["tail"][1] == 1             # lags 1..3 and 2..3 carry signal
    assert set(c["single"]) == {0, 1, 2, 3} and set(c["tail"]) == {0, 1, 2}


# --------------------------------------------------------------------------- cross-check labels

def test_crosscheck_names_each_panels_vendor_and_splits_etf_daily_by_leg(tmp_path):
    """Review 2026-11-02, finding 6: agreeing with a yfinance panel checks the fetch, not the
    data. Every row says whose numbers it compared against."""
    R = _returns_with_names()[ETFS + ["AAA"]]
    px = _px_from_returns(R)
    R2, C2, _ = ER.returns_panel(px)
    d = tmp_path / "data"
    (d / "rv").mkdir(parents=True)
    (d / "cef").mkdir()
    etf = [e for e in ETFS if e != "MUB"]
    C2[etf].to_parquet(d / "rv" / "close_unadj_wide.parquet")
    R2[etf].to_parquet(d / "rv" / "returns_wide.parquet")
    long = px[px["ticker"].isin(ETFS)].merge(
        R2.stack().rename("ret_total").reset_index().rename(columns={"level_1": "ticker"}),
        on=["date", "ticker"])
    long[["date", "ticker", "close", "ret_total", "dividend"]].to_parquet(d / "rv" / "etf_ohlc_extended.parquet")
    ed = long[long["ticker"] == "IEF"][["date", "ticker", "ret_total"]].copy()
    ed["source"] = np.where(ed["date"] < SESS[100], "crsp", "yfinance")
    ed.to_parquet(d / "etf_daily.parquet")
    px[px["ticker"] == "AAA"][["date", "ticker", "close"]].to_parquet(d / "cef" / "cef_prices.parquet")
    pd.DataFrame({"ticker": ["AAA"], "ex_date": [SESS[10]], "amount": [0.0]}).to_parquet(
        d / "cef" / "cef_distributions.parquet")
    tab, notes = ER.crosscheck(px, data_dir=d)
    legs = tab[tab["panel"].str.startswith("etf_daily")].set_index("panel")
    assert set(legs.index) == {"etf_daily[crsp]", "etf_daily[yfinance]"}
    assert legs.at["etf_daily[crsp]", "independent_of_yfinance"] == "yes"
    assert legs.at["etf_daily[yfinance]", "independent_of_yfinance"] == "no"
    assert legs.at["etf_daily[crsp]", "last"] < SESS[100].date() <= legs.at["etf_daily[yfinance]", "first"]
    assert (tab.loc[tab["panel"].str.startswith("cef/"), "independent_of_yfinance"] == "no").all()
    assert tab["vendor"].notna().all()
    assert any("confirms the fetch, not the data" in n for n in notes)
    ed.loc[ed.index[0], "source"] = "bloomberg"
    ed.to_parquet(d / "etf_daily.parquet")
    with pytest.raises(ER.ReadoutError, match="bloomberg"):
        ER.crosscheck(px, data_dir=d)


# --------------------------------------------------------------------------- refusals

def test_fit_raises_naming_a_missing_return_in_a_held_names_window():
    R = _returns_with_names()
    t = SESS[150]
    R.loc[SESS[120], "BBB"] = np.nan
    with pytest.raises(ER.ReadoutError, match=r"BBB.*2020"):
        ER.fit_window(R, SESS, t, ["AAA", "BBB"], window=W, lags=L)
    # the same gap in a name that is not held does not block the fit
    ER.fit_window(R, SESS, t, ["AAA"], window=W, lags=L)


def test_fit_raises_on_a_missing_factor_return():
    R = _returns_with_names()
    R.loc[SESS[100], "MUB"] = np.nan
    with pytest.raises(ER.ReadoutError, match="MUB"):
        ER.fit_window(R, SESS, SESS[150], ["AAA"], window=W, lags=L)


def test_fit_raises_when_history_is_shorter_than_the_window():
    R = _returns_with_names()
    with pytest.raises(ER.ReadoutError, match="needs"):
        ER.fit_window(R, SESS, SESS[W + L - 1], ["AAA"], window=W, lags=L)


def test_readout_refuses_a_split_after_the_first_positions_date_on_a_held_name():
    R = _returns_with_names()
    px = _px_from_returns(R)
    px.loc[(px["ticker"] == "AAA") & (px["date"] == SESS[152]), "split"] = 2.0
    P = _positions(list(SESS[150:153]), {"AAA": 100.0})
    with pytest.raises(ER.ReadoutError, match="split"):
        ER.readout(px, P, {"AAA": "multi"}, window=W, lags=L)


def test_readout_refuses_a_missing_close_on_a_positions_date():
    R = _returns_with_names()
    px = _px_from_returns(R)
    px.loc[(px["ticker"] == "AAA") & (px["date"] == SESS[151]), "close"] = np.nan
    with pytest.raises(ER.ReadoutError, match=r"no close on 2020.*AAA"):
        ER.readout(px, _positions([SESS[151]], {"AAA": 1.0}), {"AAA": "multi"}, window=W, lags=L)


def test_readout_refuses_a_held_symbol_without_a_group_and_a_non_session_date():
    R = _returns_with_names()
    px = _px_from_returns(R)
    with pytest.raises(ER.ReadoutError, match="no group"):
        ER.readout(px, _positions(list(SESS[150:152]), {"AAA": 1.0}), {}, window=W, lags=L)
    sat = pd.Timestamp("2020-08-01")                         # a Saturday
    with pytest.raises(ER.ReadoutError, match="not cached sessions"):
        ER.readout(px, _positions([sat], {"AAA": 1.0}), {"AAA": "multi"}, window=W, lags=L)


def test_returns_panel_refuses_a_split_and_a_distribution_on_one_name_date():
    R = _returns_with_names()
    px = _px_from_returns(R)
    m = (px["ticker"] == "AAA") & (px["date"] == SESS[100])
    px.loc[m, "split"] = 1.01                                 # 'undecidable' size for the guard
    px.loc[m, "dividend"] = 0.05
    with pytest.raises(ER.ReadoutError, match="same name-date"):
        ER.returns_panel(px)


@pytest.mark.parametrize("mutate, msg", [
    (lambda P: pd.concat([P, P.iloc[[0]]]), "duplicate"),
    (lambda P: P.assign(equity=[100_000.0] + [np.nan] * (len(P) - 1)), "some rows"),
    (lambda P: P.assign(equity=[100_000.0 + i for i in range(len(P))]), "more than one equity"),
    (lambda P: P.assign(equity=-1.0), "finite positive"),
    (lambda P: P.assign(shares=[np.inf] + list(P["shares"].iloc[1:])), "non-finite"),
])
def test_positions_validation_raises(mutate, msg):
    P = _positions(list(SESS[150:152]), {"AAA": 1.0, "BBB": -2.0})
    with pytest.raises(ER.ReadoutError, match=msg):
        ER.validate_positions(mutate(P))


def test_positions_without_equity_are_accepted_and_carry_none():
    P = _positions(list(SESS[150:152]), {"AAA": 1.0}).drop(columns=["equity"])
    assert "equity" not in ER.validate_positions(P).columns


@pytest.mark.parametrize("value, msg", [("$100,000.00", "not plain numbers"),
                                        ("100,000", "not plain numbers"),
                                        ("", "empty on every row"),
                                        (np.nan, "empty on every row")])
def test_an_equity_that_does_not_parse_raises_naming_the_column(value, msg):
    """Review 2026-11-02, finding 4: the first build coerced an unparseable equity to NaN,
    dropped the column without a word, and the summary blamed a missing equity."""
    P = _positions(list(SESS[150:152]), {"AAA": 1.0, "BBB": -2.0}).assign(equity=value)
    with pytest.raises(ER.ReadoutError, match=f"equity.*{msg}|{msg}"):
        ER.validate_positions(P)


def test_an_equity_written_as_a_numeric_string_is_read():
    P = _positions(list(SESS[150:152]), {"AAA": 1.0}).assign(equity="100000.5")
    assert (ER.validate_positions(P)["equity"] == 100000.5).all()


def test_validate_prices_raises_on_a_missing_session_an_extra_row_and_a_bad_close():
    R = _returns_with_names()
    px = _px_from_returns(R)
    asof = SESS[-1].date()
    ER.validate_prices(px, asof)
    with pytest.raises(ER.ReadoutError, match="missing"):
        ER.validate_prices(px.drop(px.index[(px["ticker"] == "IEF") & (px["date"] == SESS[50])]), asof)
    extra = px.iloc[[0]].assign(date=pd.Timestamp("2020-01-04"))        # a Saturday
    with pytest.raises(ER.ReadoutError, match="extra"):
        ER.validate_prices(pd.concat([px, extra], ignore_index=True), asof)
    bad = px.copy()
    bad.loc[bad.index[5], "close"] = 0.0
    with pytest.raises(ER.ReadoutError, match="non-positive"):
        ER.validate_prices(bad, asof)


class _FakeTicker:
    """Stands in for yfinance.Ticker: no network. Rows on the given sessions."""
    def __init__(self, sessions):
        self.sessions = sessions

    def history(self, start, end, auto_adjust, actions):
        assert auto_adjust is False and actions is True
        d = self.sessions[(self.sessions >= pd.Timestamp(start)) & (self.sessions < pd.Timestamp(end))]
        idx = pd.DatetimeIndex(d).tz_localize("America/New_York")
        return pd.DataFrame({"Close": 50.0, "Adj Close": 50.0, "Dividends": 0.0, "Stock Splits": 0.0},
                            index=idx)


def test_fetch_refuses_a_last_row_that_is_not_the_asof(monkeypatch):
    import sys
    import types
    asof = SESS[-1].date()
    fake = types.SimpleNamespace(Ticker=lambda tk: _FakeTicker(SESS))
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    px, cg = ER.fetch_yf(["IEF"], SESS[0].date(), asof)
    assert px["date"].max().date() == asof and cg == {"IEF": "absent"}
    fake.Ticker = lambda tk: _FakeTicker(SESS[:-1])           # the vendor stops a session short
    with pytest.raises(ER.ReadoutError, match="not the asof session"):
        ER.fetch_yf(["IEF"], SESS[0].date(), asof)


def test_check_asof_refuses_today_and_a_non_session():
    now = dt.datetime(2026, 11, 2, 20, 0, tzinfo=ER.NY)
    with pytest.raises(ER.ReadoutError, match="not before today"):
        ER.check_asof(dt.date(2026, 11, 2), now=now)
    with pytest.raises(ER.ReadoutError, match="not an NYSE session"):
        ER.check_asof(dt.date(2026, 11, 1), now=now)             # a Sunday
    ER.check_asof(dt.date(2026, 10, 30), now=now)


def test_refuses_to_write_under_data(tmp_path):
    d = tmp_path / "data"
    (d / "cef").mkdir(parents=True)
    with pytest.raises(ER.ReadoutError, match="under data/"):
        ER._refuse_data_dir(d / "cef" / "out", data_dir=d)
    with pytest.raises(ER.ReadoutError, match="under data/"):
        ER._refuse_data_dir(d, data_dir=d)
    ER._refuse_data_dir(tmp_path / "elsewhere", data_dir=d)


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=str(cwd), check=True, capture_output=True)


def test_refuses_to_write_a_file_git_can_see(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)       # no user excludes file
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    out = repo / "results" / "out"
    with pytest.raises(ER.ReadoutError, match="can see"):
        ER._refuse_git_visible(out, ["exposure.csv"])
    (repo / ".gitignore").write_text("results/out/\n")
    ER._refuse_git_visible(out, ["exposure.csv"])
    outside = tmp_path / "outside"
    if ER._enclosing_repo(outside) is None:                 # tmp dirs sit outside any repository
        ER._refuse_git_visible(outside, ["exposure.csv"])


def test_git_guard_checks_the_repository_enclosing_the_target_not_its_own(tmp_path, monkeypatch):
    """Review 2026-11-02, finding 3: a linked worktree inside the main checkout. Written from
    the worktree, a target in the MAIN checkout is visible to the main checkout's git, and
    the first build let it through because it checked only its own checkout."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    (main / ".gitignore").write_text(".claude/worktrees/\n")
    _git("add", ".gitignore", cwd=main)
    _git("commit", "-q", "-m", "init", cwd=main)
    wt = main / ".claude" / "worktrees" / "wt"
    _git("worktree", "add", "-q", "-b", "wt", str(wt), cwd=main)
    assert (wt / ".git").is_file()                           # a linked worktree's .git is a file
    assert ER._enclosing_repo(wt / "results" / "x") == wt.resolve()
    assert ER._enclosing_repo(main / "results" / "x") == main.resolve()
    with pytest.raises(ER.ReadoutError, match="can see"):
        ER._refuse_git_visible(main / "results" / "cef" / "x", ["summary.md"])
    with pytest.raises(ER.ReadoutError, match="can see"):
        ER._refuse_git_visible(wt / "results" / "cef" / "x", ["summary.md"])
    (wt / ".gitignore").write_text("results/cef/x/\n")
    ER._refuse_git_visible(wt / "results" / "cef" / "x", ["summary.md"])
    with pytest.raises(ER.ReadoutError, match="can see"):   # ignoring it in the worktree
        ER._refuse_git_visible(main / "results" / "cef" / "x", ["summary.md"])  # does not cover main


def test_git_guard_refuses_when_git_cannot_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / ".gitignore").write_text("out/\n")
    real = subprocess.run

    def failing(step):
        def run(args, *a, **k):
            if step in args:
                return subprocess.CompletedProcess(args, 128, "", "fatal: simulated")
            return real(args, *a, **k)
        return run
    ER._refuse_git_visible(repo / "out", ["x.csv"])           # ignored: allowed
    for step, msg in (("check-ignore", "exited 128"), ("rev-parse", "top level")):
        monkeypatch.setattr(ER.subprocess, "run", failing(step))
        with pytest.raises(ER.ReadoutError, match=msg):
            ER._refuse_git_visible(repo / "out", ["x.csv"])
        monkeypatch.setattr(ER.subprocess, "run", real)


def test_the_repository_defaults_are_gitignored():
    ER._refuse_git_visible(ER.DEFAULT_CACHE, ER.CACHE_FILES)
    ER._refuse_git_visible(ER.DEFAULT_OUT / "2026-10-30", ER.OUT_FILES)


# --------------------------------------------------------------------------- what it is not

def test_module_holds_no_order_code_no_keys_and_no_live_path_import():
    src = Path(ER.__file__).read_text()
    for needle in ("submit_order", "cancel_order", "replace_order", "cancel_all", "close_position",
                   "AlpacaClient", "QUANTT_ENV_FILE", "dotenv", "config/.env", "mcp__alpaca",
                   "paper-api.alpaca", "SECRET_KEY", "KEY_ID"):
        assert needle not in src, needle
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    assert not {m for m in mods if m.split(".")[0] in ("quantt", "src") or m.startswith("ops.books")}, mods
    assert {m for m in mods if m.startswith("scripts.")} <= {"scripts.cef.data_guards", "scripts.cef.spec"}


def test_review_constants_trace_to_d4_and_the_spec():
    assert ER.REVIEW_FRACTION == ER.D4_BETA_BAR == 0.10
    from scripts.cef.spec import VOL_TARGET, Z_WINDOW
    assert ER.VOL_TARGET == VOL_TARGET and ER.WINDOW == Z_WINDOW
