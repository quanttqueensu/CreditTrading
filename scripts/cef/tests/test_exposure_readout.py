"""The exposure readout (`scripts/cef/exposure_readout.py`), on synthetic data only.

These test the CODE: the lookahead assert, the Dimson aggregation, the orthogonalisation,
the exposure arithmetic and its signs, the review flag, and every refusal path. They make
no claim about any fund or any market (CLAUDE.md: synthetic data tests a method, never
the world). No panel is read, no network is touched, and no account data is used.

Each test was run against a deliberately broken copy of the module (window including t,
lag 0 only, unsigned value, signed contribution, a default equity, the refusals and the
finite-data check removed, the orthogonalisation turned off) and failed there; the
session that built this recorded that check.
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


def test_refuses_to_write_a_file_git_can_see(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)       # no user excludes file
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    out = repo / "results" / "out"
    with pytest.raises(ER.ReadoutError, match="git can see"):
        ER._refuse_git_visible(out, ["exposure.csv"], repo=repo)
    (repo / ".gitignore").write_text("results/out/\n")
    ER._refuse_git_visible(out, ["exposure.csv"], repo=repo)
    ER._refuse_git_visible(tmp_path / "outside", ["exposure.csv"], repo=repo)


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
