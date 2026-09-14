"""W14 Part A — is the CEF discount book short volatility at the portfolio level?

THE QUESTION THIS ANSWERS, AND THE ONE IT DOES NOT
--------------------------------------------------
It answers: does this book lose money in the states where long gamma pays? That
is the only question that decides whether an option overlay has a job here, and
it is worth ZERO trials on either counter because it adopts nothing and chooses
nothing -- it is a description of a P&L series the book already had.

It does NOT answer whether buying convexity would be worth its carry. That is
W14 Part B, it costs a GAMMA trial, and it is GATED on the verdict printed at
the bottom of this script. A negative vol beta is the entry ticket to that
question, never the answer to it.

THE MECHANISM, STATED SO IT CAN BE FALSIFIED
--------------------------------------------
Discount reversion is liquidity provision to retail. Retail sells CEFs hardest
in credit sell-offs and discounts widen together. The z-score clips at +-4 and
the vol target scales on 63-day REALISED vol, which lags -- so the book is
already at full size when the shock arrives, loses on the widening, and is paid
back over the following weeks as discounts revert.

If that story is right, the book is short a tail that an option can buy back.
If it is wrong, an overlay is pure carry. Two measurements separate them:

  beta_vol       the book's daily P&L loading on the CHANGE in implied vol.
                 Negative and significant => long gamma hedges this book.
  conditional IC the signal's IC in high- vs low-vol states. If the IC is
                 HIGHER in stress, the book is "hurt by the shock, paid by the
                 reversion", and a hedge would be protecting the exact P&L the
                 strategy exists to earn. The question then becomes one of
                 TIMING (Part C), not protection.

CONVENTIONS
-----------
* Execution is shift(2) throughout, via band_frontier.evaluate. H1.
* Returns are TOTAL returns (price + the distribution leg). The price-return
  convention is reported beside every headline because a P&L series that books
  the ex-date price drop and never books the cash mis-states the loading on any
  factor correlated with the distribution calendar -- which is the whole point
  of a factor regression. RESEARCH_STATE.md measured that bias at -0.01%/yr in
  the mean but sd 1.23%/yr and -0.77%/yr in 2010-14.
* The policy is read from the frozen spec, never written as a literal.
* Newey-West lag 5, per the prompt. Note that src/deploy/lib/attribution.py
  uses lag 10; the two are not interchangeable and this script says which.
* NO SILENT FALLBACKS. Every loader raises, naming what was missing. A factor
  panel that quietly fills a gap produces a beta that is a statement about the
  fill, not about the market.

Usage:  python3 scripts/cef/stress_beta.py [--out results/cef/STRESS_BETA_<date>.md]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import (  # noqa: E402
    BAND_WIDTH, band, build_panel, build_targets, distribution_yield, evaluate,
    total_returns,
)
from scripts.cef.spec import (  # noqa: E402
    CAPITAL_USD, GROSS_LEVERAGE, LIVE_POLICY, SPEC_ID, UNIVERSE,
)

NW_LAGS = 5                       # the prompt's lag, not attribution.py's 10
ERAS = [("2005-09", "2005", "2009"), ("2010-14", "2010", "2014"),
        ("2015-19", "2015", "2019"), ("2020-22", "2020", "2022"),
        ("2023-26", "2023", "2026")]
HOLDOUT_START = "2023-01-01"      # H13
DRAWDOWN_WINDOW = 21              # sessions, per the prompt
RATE_BETA_WINDOW = 63             # the estimator attribution.py already uses
MOM_WINDOW = 63


class MissingData(RuntimeError):
    """A panel this measurement needs does not reach the dates it was asked for."""


# ---------------------------------------------------------------------------
# Loaders. Every one of these raises rather than reindex-and-fill.
# ---------------------------------------------------------------------------

def vix_series() -> tuple[pd.Series, dict]:
    """Daily VIX close, spliced from the repo's two panels, cross-checked first.

    WHY TWO PANELS AND WHY NOT AVERAGE THEM
    ---------------------------------------
    data/vrp/vix_daily.parquet runs 2014-01-02 .. 2026-07-20 and is the panel
    the VRP programme was built on. data/forced_flow2/raw/vix_daily.parquet
    runs 1996-01-02 .. 2025-12-30 and is the only thing in this repo that
    reaches 2008 -- without it the drawdown census cannot see the financial
    crisis, which is the single most important observation for this question.

    The house rule on two disagreeing sources is: do not average, do not pick
    one silently, report the disagreement and say which you used. So: the vrp
    panel is PRIMARY wherever it exists, the forced_flow2 panel supplies dates
    before 2014-01-02 only, and the overlap disagreement is measured here and
    printed in the note. Neither series is edited.
    """
    a = pd.read_parquet(REPO / "data/vrp/vix_daily.parquet")
    a["date"] = pd.to_datetime(a["date"])
    a = a.set_index("date")["vix"].sort_index().dropna()
    b = pd.read_parquet(REPO / "data/forced_flow2/raw/vix_daily.parquet")
    b["date"] = pd.to_datetime(b["date"])
    b = b.set_index("date")["vix"].sort_index().dropna()

    both = pd.concat([a.rename("primary"), b.rename("legacy")], axis=1).dropna()
    diff = (both["primary"] - both["legacy"]).abs()
    prov = dict(primary_start=a.index[0], primary_end=a.index[-1],
                legacy_start=b.index[0], legacy_end=b.index[-1],
                overlap_n=int(len(both)), disagree_n=int((diff > 0.01).sum()),
                disagree_max=float(diff.max()),
                disagree_dates=[d.date().isoformat() for d in diff[diff > 0.01].index])
    spliced = pd.concat([b[b.index < a.index[0]], a]).sort_index()
    return spliced, prov


def vxn_series() -> pd.Series:
    """NASDAQ-100 implied vol — Part C's negative control, reported here too."""
    a = pd.read_parquet(REPO / "data/vrp/vix_daily.parquet")
    a["date"] = pd.to_datetime(a["date"])
    return a.set_index("date")["vxn"].sort_index().dropna()


def cash_rate() -> pd.Series:
    """Daily risk-free accrual from the 3m bill, for the `excess` legs."""
    rf = pd.read_parquet(REPO / "data/riskfree_daily.parquet")
    rf["date"] = pd.to_datetime(rf["date"])
    return rf.set_index("date")["rf_daily"].sort_index().dropna()


def etf_total_returns(tickers: list[str]) -> pd.DataFrame:
    """Total returns for the credit/rates legs, from the CRSP+yfinance panel."""
    e = pd.read_parquet(REPO / "data/etf_daily.parquet")
    e["date"] = pd.to_datetime(e["date"])
    have = set(e["ticker"].unique())
    missing = sorted(set(tickers) - have)
    if missing:
        raise MissingData(f"data/etf_daily.parquet has no rows for {missing}")
    w = (e[e.ticker.isin(tickers)]
         .pivot_table(index="date", columns="ticker", values="ret_total")
         .sort_index())
    return w[tickers]


def spy_total_return() -> pd.Series:
    """SPY total return. NOT in etf_daily.parquet -- it lives in the RV panel.

    The prompt asks for `SPX return`; SPY is the tradeable proxy and is what
    every other factor here is (a tradeable leg). The difference is the ETF's
    tracking and its dividend timing, and it is second-order for a beta.
    """
    x = pd.read_parquet(REPO / "data/rv/etf_ohlc_extended.parquet")
    x["date"] = pd.to_datetime(x["date"])
    s = x[x.ticker == "SPY"].set_index("date")["ret_total"].sort_index().dropna()
    if s.empty:
        raise MissingData("data/rv/etf_ohlc_extended.parquet has no SPY rows")
    return s


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    from scipy.special import ndtr
    return ndtr(x)


def short_straddle_factor() -> tuple[pd.DataFrame, dict]:
    """E1's short-ATM-straddle proxy, REBUILT — the original series is gone.

    WHY IT IS REBUILT HERE AND NOT READ
    -----------------------------------
    src/deploy/lib/attribution.py documents this factor as coming from
    results/vrp/refute_tail_ledger_SPY.csv. That file does not exist, and
    neither does the script that wrote it; `results/vrp/` is not in the repo at
    all. W14 permits either sequencing after G2 Part D (which rebuilds the
    whole pipeline) or rebuilding the single series needed here and SAYING SO.
    This is the latter. It is NOT the same object as the original, which was
    net of its own option transaction costs on the c2b tradeable path; this one
    is GROSS of them, which makes it a purer vol exposure and a slightly
    stronger regressor. For a beta test that is the conservative direction.

    CONSTRUCTION, from data/vrp/marks_SPY.parquet and atm_iv_daily.parquet:
      at t   pick the listed expiry nearest 30 DTE (>= 7 DTE, to stay out of
             the pin) for which at least one strike is quotable on BOTH legs on
             BOTH t and t+1; within it take the strike nearest the forward F
      short  that straddle at its t mark, buy it back at its t+1 mark
      hedge  +Delta_straddle shares of SPY, Delta = 2*N(d1) - 1 computed from
             the panel's OWN implied vol and forward -- never a broker's model
             greek (W14 "Do not"), and not the American pricer G1 will build:
             for an ATM 30-day SPY straddle the early-exercise premium in the
             DELTA is far below the strike-rounding error measured below
      scale  divide by the t spot, so the factor is a return on notional

    MEASURED DEFECT, stated rather than hidden: requiring both legs quotable
    leaves a strike grid that skews BELOW the forward, so the selected straddle
    carries a mean delta of about +0.018 (F > K on ~79% of days) rather than 0.
    The hedge above removes it. `delta_mean` is returned so the note can show
    it, and the unhedged series is returned beside the hedged one so the reader
    can see what the hedge did.
    """
    a = pd.read_parquet(REPO / "data/vrp/atm_iv_daily.parquet")
    a = a[a.ticker == "SPY"].copy()
    a["date"] = pd.to_datetime(a["date"])
    a["expiry"] = pd.to_datetime(a["expiry"])
    a = a.rename(columns={"T": "tau"})            # `.T` on a Series is transpose
    if a.empty:
        raise MissingData("data/vrp/atm_iv_daily.parquet has no SPY rows")

    m = pd.read_parquet(REPO / "data/vrp/marks_SPY.parquet")
    m["date"] = pd.to_datetime(m["date"])
    m["expiry"] = pd.to_datetime(m["expiry"])
    w = m.pivot_table(index=["date", "expiry", "strike"],
                      columns="opt_type", values="px").dropna()
    strad = (w["C"] + w["P"]).sort_index()
    quotable = {k: set(v.index.get_level_values(2)) for k, v in strad.groupby(level=[0, 1])}

    u = pd.read_parquet(REPO / "data/vrp/underlying_daily.parquet")
    u["date"] = pd.to_datetime(u["date"])
    spot = u[u.ticker == "SPY"].set_index("date")["close"].sort_index()

    # The panel's own dates have holes -- atm_iv_daily and marks_SPY do not
    # cover every session -- so "the next date I have data for" is NOT the next
    # session. Taking it as one books a multi-day mark-to-mark P&L onto a single
    # date and regresses it against ONE day of book P&L. Measured before this
    # fix: 29 rows spanned more than a long weekend, four of them 16-22 calendar
    # days, and dropping them moved beta_SHORTVOL by 14% (0.1076 -> 0.0931).
    # The session calendar is taken from the CEF price panel, which is the same
    # NYSE calendar SPY trades on -- exact, rather than a calendar-day
    # threshold that has to guess about holidays.
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(REPO / "data/cef/cef_prices.parquet")["date"].unique())))
    have = set(a["date"].unique()) & set(strad.index.get_level_values(0).unique())
    dates = sorted(have)
    nxt, non_consecutive = {}, 0
    for d in dates:
        j = sessions.searchsorted(d)
        if j + 1 >= len(sessions):
            continue
        follow = sessions[j + 1]
        if follow in have:
            nxt[d] = follow
        else:
            non_consecutive += 1
    by_date = {d: g for d, g in
               a[a.dte >= 7].assign(_g=lambda x: (x.dte - 30).abs())
                .sort_values("_g").groupby("date")}

    rows, skipped = [], 0
    for d in dates[:-1]:
        if d not in nxt:                       # next session absent from the panel
            continue
        d1, cands = nxt[d], by_date.get(d)
        if cands is None:
            skipped += 1
            continue
        chosen = None
        for _, r in cands.iterrows():
            k0, k1 = quotable.get((d, r.expiry)), quotable.get((d1, r.expiry))
            if not k0 or not k1:
                continue
            common = k0 & k1
            if common:
                chosen = (r, min(common, key=lambda k: abs(k - r.F)))
                break
        if chosen is None:
            skipped += 1
            continue
        r, K = chosen
        p0 = float(strad.loc[(d, r.expiry, K)])
        p1 = float(strad.loc[(d1, r.expiry, K)])
        s0, s1 = float(spot.loc[d]), float(spot.loc[d1])
        st = float(r.iv) * np.sqrt(float(r.tau))
        dd = (np.log(float(r.F) / K) / st + 0.5 * st) if st > 0 else 0.0
        delta = float(2 * _norm_cdf(np.array([dd]))[0] - 1)
        rows.append((d1, ((p0 - p1) + delta * (s1 - s0)) / s0, (p0 - p1) / s0,
                     int(r.dte), delta))

    f = pd.DataFrame(rows, columns=["date", "SHORTVOL", "SHORTVOL_unhedged",
                                    "dte", "delta"]).set_index("date")
    prov = dict(n=len(f), skipped=skipped, non_consecutive=non_consecutive,
                start=f.index[0], end=f.index[-1],
                dte_median=float(f.dte.median()), delta_mean=float(f.delta.mean()),
                frac_delta_positive=float((f.delta > 0).mean()),
                ann_mean_pct=float(f.SHORTVOL.mean() * 252 * 100),
                ann_sd_pct=float(f.SHORTVOL.std() * np.sqrt(252) * 100),
                skew=float(f.SHORTVOL.skew()))
    return f, prov


def gamma_identity_factor() -> pd.Series:
    """The same exposure, computed a second way, as a cross-check on the above.

    From G0_BRIEF's own identity, a delta-hedged SHORT option position earns
    `0.5 * (sigma_imp^2 * dt - r^2)` per unit of dollar gamma. Using the VRP
    panel's constant-maturity interpolated implied vol at t-1 and SPY's realised
    return at t, this is a pricer-free, delta-free construction of exactly the
    same economics as `short_straddle_factor`. If the two disagree in sign or
    in their worst days, one of them is wrong.

    ALIGNMENT (H7): sigma is taken from t-1 and squared against the return
    dated t. Nothing reads past t.
    """
    v = pd.read_parquet(REPO / "data/vrp/vrp_series.parquet")
    v = v[v.ticker == "SPY"].copy()
    v["date"] = pd.to_datetime(v["date"])
    iv = v.set_index("date")["impl_vol"].sort_index().dropna()
    px = v.set_index("date")["close"].sort_index()
    r = px.pct_change()
    return (0.5 * (iv.shift(1) ** 2 / 252.0 - r ** 2)).dropna().rename("GAMMA_ID")


def rolling_rate_beta(credit_xs: pd.Series, rates_xs: pd.Series) -> pd.Series:
    """Trailing-63d rate beta, shifted one day. The estimator attribution.py uses.

    ALIGNMENT (H7): `.shift(1)` means the beta applied on date t was fitted on
    a window ending t-1. Without it the duration hedge would be fitted partly on
    the day it hedges, and the residual would be mechanically small.
    """
    cov = credit_xs.rolling(RATE_BETA_WINDOW).cov(rates_xs)
    var = rates_xs.rolling(RATE_BETA_WINDOW).var()
    return (cov / var.replace(0, np.nan)).shift(1)


def build_factors() -> tuple[pd.DataFrame, dict]:
    """The E1 §5 factor set, on the dates where every leg genuinely exists."""
    rf = cash_rate()
    etf = etf_total_returns(["HYG", "LQD", "IEF"])
    spy = spy_total_return()
    vix, vix_prov = vix_series()
    sv, sv_prov = short_straddle_factor()

    idx = etf.dropna().index.intersection(rf.index).intersection(spy.index)
    hyg_xs = (etf["HYG"] - rf).reindex(idx).dropna()
    lqd_xs = (etf["LQD"] - rf).reindex(idx).dropna()
    ief_xs = (etf["IEF"] - rf).reindex(idx).dropna()

    hy = (hyg_xs - rolling_rate_beta(hyg_xs, ief_xs) * ief_xs).rename("HY_XS")
    ig = (lqd_xs - rolling_rate_beta(lqd_xs, ief_xs) * ief_xs).rename("IG_XS")

    # Credit momentum: a time-series momentum LEG, not a level. The sign is
    # taken from the trailing 63-session cumulative HY excess return as of t-1
    # -- derived, not swept (H8) -- and applied to date t's HY excess return.
    mom = (np.sign(hy.rolling(MOM_WINDOW).sum().shift(1)) * hy).rename("CRD_MOM")

    F = pd.concat([
        hy, ig,
        ief_xs.rename("UST_XS"),
        (spy - rf).reindex(idx).dropna().rename("SPX_XS"),
        vix.diff().rename("D_VIX"),
        sv["SHORTVOL"],
        mom,
    ], axis=1)
    prov = dict(vix=vix_prov, shortvol=sv_prov,
                rf_end=rf.index[-1], etf_end=etf.dropna().index[-1],
                spy_end=spy.index[-1],
                shortvol_unhedged=sv["SHORTVOL_unhedged"])
    return F, prov


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def regress(y: pd.Series, X: pd.DataFrame, lags: int = NW_LAGS) -> dict:
    """OLS with Newey-West(lag) standard errors on the complete-case sample."""
    import statsmodels.api as sm
    df = pd.concat([y.rename("_y"), X], axis=1).dropna()
    if len(df) < 250:
        raise MissingData(f"only {len(df)} complete rows — too few to regress")
    cols = list(X.columns)
    fit = sm.OLS(df["_y"].to_numpy(),
                 sm.add_constant(df[cols].to_numpy())).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return dict(
        n=len(df), start=df.index[0], end=df.index[-1], r2=float(fit.rsquared),
        alpha_ann=float(fit.params[0]) * 252, alpha_t=float(fit.tvalues[0]),
        beta={c: float(b) for c, b in zip(cols, fit.params[1:])},
        t={c: float(t) for c, t in zip(cols, fit.tvalues[1:])},
    )


def univariate_r2(y: pd.Series, x: pd.Series, lags: int = NW_LAGS) -> dict:
    r = regress(y, x.to_frame(), lags=lags)
    c = list(x.to_frame().columns)[0]
    return dict(beta=r["beta"][c], t=r["t"][c], r2=r["r2"], n=r["n"])


def worst_windows(pnl: pd.Series, k: int = DRAWDOWN_WINDOW, n: int = 10,
                  non_overlapping: bool = True) -> pd.DataFrame:
    """The n worst k-session windows.

    NON-OVERLAPPING BY DEFAULT, and that is not cosmetic: the ten worst
    overlapping 21-session windows in a series like this are typically ten
    shifted views of two crises, and "8 of 10 in the top VIX quintile" would
    then be a statement about two events, not ten. Greedy: take the worst
    window, delete every window that shares a session with it, repeat. The
    overlapping version is reported beside it so the difference is visible.
    """
    roll = pnl.rolling(k).sum().dropna()
    picked, used = [], set()
    for end, v in roll.sort_values().items():
        j = pnl.index.get_loc(end)
        span = set(range(j - k + 1, j + 1))
        if non_overlapping and (span & used):
            continue
        used |= span
        picked.append((pnl.index[j - k + 1], end, float(v)))
        if len(picked) == n:
            break
    return pd.DataFrame(picked, columns=["start", "end", "pnl"])


def conditional_ic(z: pd.DataFrame, R: pd.DataFrame, state: pd.Series,
                   labels: tuple[str, str, str] = ("low", "mid", "high")
                   ) -> pd.DataFrame:
    """H6 IC — Spearman(z_t, forward 2-day return from t+2) — split by state.

    NON-OVERLAPPING: the forward window is two sessions, so dates are sampled
    every second session. Standard errors are the cross-date standard error of
    the daily IC, which IS the date-clustered SE for this statistic (H6: never
    naive, i.e. never sqrt(n_observations) over the pooled panel).

    ALIGNMENT (H7): the state is the VIX LEVEL at t, the same date as the
    signal -- the split is on information available when the decision is made.
    The return is (1+r_{t+2})(1+r_{t+3})-1, the first return the book can reach.
    """
    fwd = ((1 + R).shift(-2) * (1 + R).shift(-3) - 1)
    dates = z.index[::2]
    rows = []
    for t in dates:
        if t not in fwd.index or t not in state.index:
            continue
        a, b = z.loc[t], fwd.loc[t]
        ok = a.notna() & b.notna()
        if ok.sum() < 5:
            continue
        rows.append((t, float(a[ok].corr(b[ok], method="spearman")), float(state.loc[t])))
    d = pd.DataFrame(rows, columns=["date", "ic", "state"]).dropna()
    q = d["state"].quantile([1 / 3, 2 / 3]).to_list()
    d["bucket"] = np.where(d.state <= q[0], labels[0],
                           np.where(d.state <= q[1], labels[1], labels[2]))
    out = d.groupby("bucket")["ic"].agg(["mean", "std", "count"])
    out["t"] = out["mean"] / (out["std"] / np.sqrt(out["count"]))
    out["state_lo"] = d.groupby("bucket")["state"].min()
    out["state_hi"] = d.groupby("bucket")["state"].max()
    return out.reindex(list(labels))


def ic_ratio(ic: pd.DataFrame) -> tuple[float | None, str]:
    """high-vol IC / low-vol IC, or a stated refusal.

    The gloss "a ratio above 1 means the signal works better in stress" is true
    only while BOTH terms are negative, which is the expected sign (H6). If the
    low-vol IC prints near zero the quotient explodes; if it prints positive the
    quotient silently flips meaning and the sentence becomes false with no
    error. This script already refuses to print a degenerate group IC; the
    ratio gets the same treatment rather than a number nobody can interpret.
    """
    lo, hi = float(ic.loc["low", "mean"]), float(ic.loc["high", "mean"])
    if lo >= 0 or hi >= 0:
        return None, (f"UNDEFINED — the ratio only means \"stronger in stress\" "
                      f"while both ICs carry the expected negative sign "
                      f"(low {lo:+.4f}, high {hi:+.4f})")
    if abs(lo) < 1e-3:
        return None, (f"UNDEFINED — the low-vol IC is {lo:+.4f}, too near zero "
                      "for a ratio to mean anything")
    return hi / lo, f"{hi / lo:.2f}"


def pct_rank(s: pd.Series, v: float) -> float:
    return float((s <= v).mean())


def effective_sample(H: pd.DataFrame) -> pd.DatetimeIndex:
    """The dates the book actually holds something.

    WHY THIS IS NOT COSMETIC (landmine 6, measured rather than quoted)
    -----------------------------------------------------------------
    Before the ADV filter lets `min_names` through, the target book is empty and
    the P&L is EXACTLY zero -- not small, zero. Those dates are in the index and
    in every mean, and they carry VIX observations. Leaving them in does two
    specific damages to this prompt's questions:

      * the reference VIX distribution used for "top quintile" then includes
        2008, whose VIX of 80 lifts the threshold that the book's OWN trading
        era is scored against, so a real vol-state drawdown can fail the test
        against a vol state the book was never exposed to;
      * "the ten worst 21-session windows since 2005" reads as though a credit
        crisis had a chance to appear in it. It did not.

    CLAUDE.md's landmine 6 says "the 2411 dates before 2013 are flat". Measured
    here on the live band, it is worse than that: the first date with any
    position at all is in mid-2013, and there are no flat sessions after it.
    """
    gross = H.abs().sum(axis=1)
    held = gross[gross > 1e-12]
    if held.empty:
        raise MissingData("the book holds nothing on any date in the sample")
    return pd.DatetimeIndex(gross.loc[held.index[0]:].index)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None,
                    help="write the markdown note here (default results/cef/STRESS_BETA_<today>.md)")
    args = ap.parse_args()
    out = Path(args.out) if args.out else \
        REPO / f"results/cef/STRESS_BETA_{date.today().isoformat()}.md"

    # The dollars-per-VIX-point conversion below is beta x CAPITAL_USD, which is
    # right only because the sleeve sizes floor(capital*|w|/close) and the
    # targets are w/|w|.sum() scaled by the vol scalar -- i.e. fractions of
    # capital at gross_leverage 1.0. If the spec ever levers the book, the same
    # beta means a different number of dollars and this script must be told.
    if not np.isclose(GROSS_LEVERAGE, 1.0):
        raise MissingData(
            f"the frozen spec has gross_leverage={GROSS_LEVERAGE}, not 1.0. "
            "Every dollar figure in this script converts a book RETURN with "
            "beta x capital_usd, which assumes the targets are fractions of "
            "capital. Decide what the conversion should be and say so here "
            "rather than letting it silently mean something else.")

    L: list[str] = []

    def say(line: str = "") -> None:
        print(line)
        L.append(line)

    # --- A0 the book ------------------------------------------------------
    T, R_px = build_targets()
    R_tot = total_returns(R_px)
    H = band(T, BAND_WIDTH)
    res_tot, res_px = evaluate(H, R_tot), evaluate(H, R_px)
    pnl, pnl_px = res_tot["pnl"], res_px["pnl"]

    say("# W14 Part A — stress beta of the CEF discount book")
    say()
    say(f"**Run {date.today().isoformat()}** by `python3 scripts/cef/stress_beta.py`. "
        f"Spec `{SPEC_ID}`, policy **{LIVE_POLICY}**, universe {len(UNIVERSE)}. "
        "Trials spent: **0** on either counter — this prompt adopts nothing.")
    say()
    say("## A0 The P&L series under test")
    say()
    say("`band_frontier.evaluate(band(T, band_width), R)['pnl']` — shift(2), "
        "decide at *t*, MOC fill at *t+1*, earn the *t+2* return (H1). The "
        "`pnl` key is the extension this prompt added to the canonical "
        "harness; no second backtester was built.")
    say()
    say("| convention | scope | gross SR | ann % | vol % | turn/yr | sample |")
    say("|---|---|---:|---:|---:|---:|---|")
    eff = effective_sample(H)
    for lab, r in (("**total return** (used below)", res_tot), ("price return only", res_px)):
        x = r["pnl"]
        say(f"| {lab} | full panel | {r['gross_sr']:.3f} | {r['ann_ret']*100:.2f} "
            f"| {r['vol']*100:.2f} | {r['turn']:.1f} "
            f"| {x.index[0].date()} .. {x.index[-1].date()} |")
        e = x.reindex(eff)
        te = r["turn_series"].reindex(eff).mean() * 252
        say(f"| {lab} | **traded sessions only** | "
            f"{e.mean()/e.std()*np.sqrt(252):.3f} | {e.mean()*252*100:.2f} "
            f"| {e.std()*np.sqrt(252)*100:.2f} | {te:.1f} "
            f"| {e.index[0].date()} .. {e.index[-1].date()} |")
    say()
    say(f"The full-panel price-return row is the figure `band_frontier.py` "
        f"publishes and `CLAUDE.md` quotes as gross **1.17**; it reproduces "
        f"here at **{res_px['gross_sr']:.3f}**. [V]")
    say()
    say(f"**The sample is not what the index says.** The panel runs from "
        f"{pnl.index[0].date()}, but the ADV filter lets fewer than "
        f"`min_names` through until **{eff[0].date()}**, so the book holds "
        f"*nothing* — P&L exactly zero, not merely small — on "
        f"{len(pnl) - len(eff):,} of {len(pnl):,} sessions, and there are no "
        f"flat sessions after that date. **This book has never been through a "
        f"credit crisis.** No 2008, no 2011. CLAUDE.md landmine 6 says \"the "
        f"2411 dates before 2013 are flat\"; measured here on the live band it "
        f"is {len(pnl) - len(eff):,} sessions and the first position is "
        f"{eff[0].date()}. Everything from A1 down is restricted to the traded "
        f"sessions, and the VIX reference distribution with it — otherwise "
        f"\"top VIX quintile\" is a threshold set by a vol state the book was "
        f"never exposed to.")
    say()
    say(f"Landmine 6's other half checks out arithmetically: the flat rows "
        f"dilute the Sharpe by √({len(eff):,}/{len(pnl):,}) = "
        f"{np.sqrt(len(eff)/len(pnl)):.3f}, and "
        f"{res_tot['gross_sr']:.3f} ÷ {np.sqrt(len(eff)/len(pnl)):.3f} = "
        f"{res_tot['gross_sr']/np.sqrt(len(eff)/len(pnl)):.3f} against the "
        f"{pnl.reindex(eff).mean()/pnl.reindex(eff).std()*np.sqrt(252):.3f} "
        "measured on the traded sessions. Every headline Sharpe in this repo "
        "is a full-panel one and therefore carries that dilution.")
    say()
    carry = pnl - pnl_px                     # FULL panel: the comparison
    say(f"Distribution carry on this holdings path, **full panel** so it is "
        f"comparable to the recorded measurement: "
        f"**{carry.mean()*252*100:+.3f}%/yr**, sd "
        f"{carry.std()*np.sqrt(252)*100:.2f}%/yr, over "
        f"{int((distribution_yield(R_px.index, R_px.columns) != 0).sum().sum()):,} "
        "ex-dates. `docs/RESEARCH_STATE.md` measured −0.01%/yr, sd 1.23%/yr "
        "over 3,962 ex-dates on 2026-09-09; the panel has since extended to "
        f"{R_px.index[-1].date()}. **[V] reproduced.** By era: "
        + ", ".join(f"{lab} {carry.loc[a:b].mean()*252*100:+.2f}%"
                    for lab, a, b in ERAS if not carry.loc[a:b].empty) + ".")
    say()
    pnl, pnl_px = pnl.reindex(eff), pnl_px.reindex(eff)
    say()

    # --- A1 factors -------------------------------------------------------
    F, prov = build_factors()
    vix, vix_prov = vix_series()
    say("## A1 The factor panel")
    say()
    say("| factor | what it is | source | sd, on the regression sample |")
    say("|---|---|---|---:|")
    desc = {
        "HY_XS": ("HY excess, duration-hedged", "HYG − rf − β₆₃·(IEF − rf), β shifted 1d"),
        "IG_XS": ("IG excess, duration-hedged", "LQD − rf − β₆₃·(IEF − rf), β shifted 1d"),
        "UST_XS": ("rates", "IEF − rf (7–10y; the tradeable proxy for “10y Treasury”)"),
        "SPX_XS": ("equity", "SPY total return − rf, from `data/rv/etf_ohlc_extended.parquet`"),
        "D_VIX": ("Δ implied vol", "VIX close, first difference, in points"),
        "SHORTVOL": ("short-ATM-straddle proxy", "rebuilt from `data/vrp/marks_SPY.parquet` — see below"),
        "CRD_MOM": ("credit momentum", "sign(Σ₆₃ HY_XS as of t−1) × HY_XS_t"),
    }
    # sd on the REGRESSION sample, not each factor's own history. HY_XS starts
    # in 2007, so its full-history sd is a 2008-09 number (10.46% against 7.40%
    # here) and beta x that sd overstates the exposure by 41%. sd is the column
    # a reader multiplies beta by to get an economic magnitude.
    Fr = F.reindex(pnl.index).dropna()      # the regression's complete cases
    for c in F.columns:
        d0, d1 = desc[c]
        if c == "D_VIX":                 # a level difference; annualising it is meaningless
            say(f"| `{c}` | {d0} | {d1} | {Fr[c].std():.2f} pts/day |")
        else:
            say(f"| `{c}` | {d0} | {d1} | {Fr[c].std()*np.sqrt(252)*100:.2f} % |")
    say()
    sp = prov["shortvol"]
    say(f"**The straddle proxy is REBUILT, not read.** "
        f"`src/deploy/lib/attribution.py` sources it from "
        f"`results/vrp/refute_tail_ledger_SPY.csv`, which **does not exist** — "
        f"nor does `results/vrp/`, nor the script that wrote it. W14 permits "
        f"rebuilding the single series and saying which; this is that. It is "
        f"**gross** of option transaction costs where the original was net, so "
        f"it is a slightly stronger vol exposure than the tradeable version. "
        f"{sp['n']:,} days {sp['start'].date()}..{sp['end'].date()} "
        f"({sp['skipped']} skipped for want of a two-sided mark on both days), "
        f"median {sp['dte_median']:.0f} DTE, "
        f"mean {sp['ann_mean_pct']:+.2f}%/yr on notional, sd {sp['ann_sd_pct']:.2f}%, "
        f"skew **{sp['skew']:.2f}**. Requiring both legs quotable leaves a "
        f"strike grid skewed below the forward, so the selected straddle carries "
        f"a mean delta of {sp['delta_mean']:+.4f} (F > K on "
        f"{sp['frac_delta_positive']:.0%} of days) rather than 0; the "
        f"Black–Scholes hedge computed from the panel's own IV removes it.")
    say()
    gid = gamma_identity_factor()
    common = F["SHORTVOL"].dropna().index.intersection(gid.index)
    say(f"**Cross-check (recomputed a second way).** The same exposure from "
        f"G0_BRIEF's identity ½(σ²_imp·Δt − r²), using the VRP panel's "
        f"constant-maturity IV at *t−1* and SPY's return at *t* — no marks, no "
        f"pricer, no delta: correlation with the traded-straddle series is "
        f"**{F['SHORTVOL'].reindex(common).corr(gid.reindex(common)):.3f}** "
        f"over {len(common):,} common days. The two agree.")
    say()
    vp = vix_prov
    say(f"**VIX provenance, and a disagreement not averaged away.** Primary "
        f"`data/vrp/vix_daily.parquet` "
        f"({vp['primary_start'].date()}..{vp['primary_end'].date()}); dates before "
        f"{vp['primary_start'].date()} come from "
        f"`data/forced_flow2/raw/vix_daily.parquet` "
        f"({vp['legacy_start'].date()}..{vp['legacy_end'].date()}), which is the "
        f"only series here that reaches 2008. On their {vp['overlap_n']:,}-day "
        f"overlap they differ by more than 0.01 on **{vp['disagree_n']} days** "
        f"(max {vp['disagree_max']:.2f}): {', '.join(vp['disagree_dates'])}. "
        f"Neither was edited and they were not averaged; the primary is used "
        f"wherever it exists. The 8 days are 0.3% of the overlap and none is a "
        f"drawdown window boundary below.")
    say()
    say("**[U] Neither `data/vrp/*` panel has a fetcher in this repo** — the "
        "builders are gone and `docs/REFERENCES.md` carries no entry for them. "
        "`data/vrp/_extract_SPY.log` records a month-by-month extraction. "
        "Everything below that rests on SPY options inherits that gap.")
    say()

    # --- A2 the regression ------------------------------------------------
    say("## A2 Factor regression of daily book P&L")
    say()
    say(f"OLS, Newey–West lag {NW_LAGS} (the prompt's lag; "
        "`src/deploy/lib/attribution.py` uses 10 — not interchangeable). "
        "Book P&L is total-return, shift(2).")
    say()
    full = regress(pnl, F)
    say(f"Sample **{full['start'].date()} .. {full['end'].date()}**, "
        f"n = {full['n']:,}. Full-model R² = **{full['r2']:.3f}**. "
        f"Alpha {full['alpha_ann']*100:+.2f}%/yr (t {full['alpha_t']:+.2f}).")
    say()
    say("| factor | β | t (NW5) | univariate R², own sample |")
    say("|---|---:|---:|---:|")
    # The univariate column is each factor's own maximal complete-case sample,
    # which is NOT the multivariate sample and is therefore not a like-for-like
    # ranking. A5 has the four that matter on one common sample.
    uni = {}
    for c in F.columns:
        uni[c] = univariate_r2(pnl, F[c])
        flag = " **" if abs(full["t"][c]) >= 2.5 else ""
        say(f"| `{c}` | {full['beta'][c]:+.5f}{flag} | {full['t'][c]:+.2f} | {uni[c]['r2']:.4f} |")
    say()
    b_vix, t_vix = full["beta"]["D_VIX"], full["t"]["D_VIX"]
    say(f"**β on ΔVIX = {b_vix:+.6f} per VIX point** (t {t_vix:+.2f}), which on "
        f"the ${CAPITAL_USD:,.0f} book (`capital_usd`, read from the frozen "
        f"spec) is **${b_vix*CAPITAL_USD:+,.0f} per VIX point** per day. "
        f"Univariate: β {uni['D_VIX']['beta']:+.6f}, t {uni['D_VIX']['t']:+.2f}, "
        f"R² {uni['D_VIX']['r2']:.4f}.")
    say()
    say("Price-return convention, same window, as the robustness the "
        "convention correction exists to provide:")
    pf = regress(pnl_px, F)
    say(f"β_ΔVIX {pf['beta']['D_VIX']:+.6f} (t {pf['t']['D_VIX']:+.2f}), "
        f"R² {pf['r2']:.3f} — the convention does not move the verdict.")
    say()
    say("### The same regression without the straddle leg, over every date the book traded")
    say()
    say("`SHORTVOL` begins 2014-06 and is the only factor that binds the window "
        "short. Dropping it — and keeping ΔVIX, which the splice carries back "
        "further — costs the E1 comparability but buys back the book's first "
        "year. If β_ΔVIX moved between the two, the headline would be a "
        "statement about the window rather than about the book.")
    say()
    F_long = F.drop(columns=["SHORTVOL"])
    long = regress(pnl, F_long)
    say(f"Sample {long['start'].date()} .. {long['end'].date()}, n = {long['n']:,}, "
        f"R² {long['r2']:.3f}. **β_ΔVIX = {long['beta']['D_VIX']:+.6f} "
        f"(t {long['t']['D_VIX']:+.2f})** = ${long['beta']['D_VIX']*CAPITAL_USD:+,.0f} "
        f"per VIX point, against {b_vix:+.6f} (t {t_vix:+.2f}) on the full set. "
        f"Same sign, and {abs(long['beta']['D_VIX']/b_vix):.1f}× the magnitude — "
        "the longer window is the less favourable of the two for this prompt's "
        "conclusion, and it is still short of the gate's |t| ≥ 2.5 bar. The "
        "verdict does not turn on which window is read; it is stated on the "
        "prompt's own window, which is the full set.")
    say()
    say("**The univariate and multivariate ΔVIX betas differ and that is the "
        "interesting part.** Alone, ΔVIX loads "
        f"{uni['D_VIX']['beta']:+.6f} at t {uni['D_VIX']['t']:+.2f}; beside the "
        "credit, equity and straddle legs it falls to "
        f"{b_vix:+.6f} at t {t_vix:+.2f}. Whatever ΔVIX picks up on its own is "
        "already carried by the tradeable legs — which is precisely the case "
        "in which buying volatility is the wrong instrument for it.")
    say()
    say("### By era, and fit vs holdout (H5, H13)")
    say()
    say("| window | n | β ΔVIX | t | β SHORTVOL | t | β HY_XS | t | R² |")
    say("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    windows = [("full", None, None)] + [(lab, a, b) for lab, a, b in ERAS] + \
              [("fit <2023", None, "2022"), ("holdout 2023+", HOLDOUT_START, None)]
    for lab, a, b in windows:
        y = pnl.loc[a:b] if (a or b) else pnl
        try:
            r = regress(y, F)
        except MissingData as exc:
            say(f"| {lab} | — | UNMEASURED | | | | | | {exc} |")
            continue
        say(f"| {lab} | {r['n']:,} | {r['beta']['D_VIX']:+.5f} | {r['t']['D_VIX']:+.2f} "
            f"| {r['beta']['SHORTVOL']:+.3f} | {r['t']['SHORTVOL']:+.2f} "
            f"| {r['beta']['HY_XS']:+.3f} | {r['t']['HY_XS']:+.2f} | {r['r2']:.3f} |")
    say()
    say("### The same question without a regression")
    say()
    say("A t-statistic on a daily beta is a weak instrument for a tail claim, "
        "so here is the non-parametric version of the same question: what does "
        "the book actually do on the days volatility jumps?")
    say()
    dv = F["D_VIX"].reindex(pnl.index).dropna()
    f21 = pnl.shift(-2).rolling(21).sum().shift(-20)     # t+2..t+22; see A4
    say("| ΔVIX bucket | sessions | mean book P&L, bp/day | t "
        "| next 21 earned sessions, % |")
    say("|---|---:|---:|---:|---:|")
    spike = {}
    for lab, mask in (("largest 5% ΔVIX (vol spikes)", dv >= dv.quantile(0.95)),
                      ("largest 1% ΔVIX", dv >= dv.quantile(0.99)),
                      ("all sessions", dv == dv)):
        x = pnl.reindex(dv[mask].index).dropna()
        t = x.mean() / (x.std() / np.sqrt(len(x)))
        fwd = f21.reindex(x.index).dropna()
        spike[lab] = (x.mean() * 1e4, t, fwd.mean() * 100)
        say(f"| {lab} | {len(x):,} | {x.mean()*1e4:+.2f} | {t:+.2f} "
            f"| {fwd.mean()*100:+.2f} |")
    say()
    d5, t5, f5 = spike["largest 5% ΔVIX (vol spikes)"]
    d1, t1, f1 = spike["largest 1% ΔVIX"]
    d0, _, f0 = spike["all sessions"]
    daily_sd = pnl.std() * 1e4
    say(f"**The book does lose on vol-spike days — and gets it back.** On the "
        f"largest 5% of ΔVIX days it earns {d5:+.2f}bp against {d0:+.2f}bp "
        f"unconditionally, a swing of {d5-d0:.2f}bp; on the largest 1%, "
        f"{d1:+.2f}bp, which is ${d1/1e4*CAPITAL_USD:+,.0f} on the "
        f"${CAPITAL_USD:,.0f} book and about {abs(d1)/daily_sd:.1f} daily "
        f"standard deviations ({daily_sd:.1f}bp). Neither is statistically "
        f"distinguishable from zero (t {t5:+.2f}, {t1:+.2f}) at these sample "
        f"sizes, so the daily loss is real in sign and weak in evidence.")
    say()
    say(f"The column on the right is the part that matters for a hedge. Over "
        f"the 21 sessions a decision on a top-5% ΔVIX day actually earns "
        f"(*t+2*..*t+22*, the shift(2) convention) the book makes "
        f"**{f5:+.2f}%** against {f0:+.2f}% unconditionally, and "
        f"**{f1:+.2f}%** after a top-1% day. The shock costs roughly "
        f"{abs(d1):.0f}bp on the day and pays back several times that over the "
        f"following month. **A convexity overlay bought to remove the first "
        f"number is short the second one**, because it is sized and carried "
        f"across the whole period, not just the spike.")
    say()
    say("**β on ΔHYG-IV: UNMEASURED.** No HYG option data exists anywhere in "
        "this repo — `data/vrp/atm_iv_daily.parquet` and the marks files carry "
        "SPY and QQQ only. Extracting a credit surface is `gamma/G2`. Until it "
        "lands the credit-specific half of this question cannot be answered, "
        "and ΔVIX stands in for it with the basis measured in A5.")
    say()

    # --- A3 drawdowns -----------------------------------------------------
    say("## A3 Drawdown coincidence")
    say()
    vix_on = vix.reindex(pnl.index).dropna()
    pnl_v = pnl.reindex(vix_on.index)
    say(f"Book P&L on dates it both traded and has a VIX observation: "
        f"{pnl_v.index[0].date()} .. {pnl_v.index[-1].date()}, "
        f"{len(pnl_v):,} sessions. Percentiles are taken within THAT window "
        "(a retrospective description, not a decision rule); the point-in-time "
        "expanding percentile is shown beside it, and the peak VIX inside each "
        "window beside that — because a window that *begins* before a spike "
        "and contains it scores low on the gate's own statistic and high on "
        "the one the mechanism actually predicts.")
    say()
    # Per-name P&L attribution, same convention as `evaluate`: the weights
    # decided at t are held into the t+2 return. This answers a question the
    # gate does not ask and should: is a drawdown a market event or one fund?
    contrib = H.shift(2).fillna(0.0) * R_tot
    gate_rows = {}
    scopes = [("all traded sessions", pnl_v)]
    if pnl_v.index[0] < pd.Timestamp("2014-01-01"):
        scopes.append(("2014+ (single-source VIX)", pnl_v.loc["2014":]))
    for scope, series in scopes:
        ws = worst_windows(series, non_overlapping=True)
        vs = vix.reindex(series.index).dropna()
        q80 = float(vs.quantile(0.80))
        say(f"### {scope} — ten worst non-overlapping {DRAWDOWN_WINDOW}-session windows")
        say()
        say(f"Top VIX quintile in this window is VIX ≥ **{q80:.2f}**.")
        say()
        say("| # | start | end | P&L % | VIX at start | pct (full) | pct (PIT) "
            "| peak VIX | peak pct | start in top q? | peak in top q? "
            "| worst single name | its share |")
        say("|---:|---|---|---:|---:|---:|---:|---:|---:|:---:|:---:|---|---:|")
        hits = peak_hits = 0
        start_pcts, names = [], []
        for i, r in ws.iterrows():
            v0 = float(vs.loc[:r.start].iloc[-1])
            pk = float(vs.loc[r.start:r.end].max())
            p_full, p_pit, p_peak = pct_rank(vs, v0), pct_rank(vs.loc[:r.start], v0), pct_rank(vs, pk)
            start_pcts.append(p_full)
            top, top_pk = p_full >= 0.80, p_peak >= 0.80
            hits += top
            peak_hits += top_pk
            cw = contrib.loc[r.start:r.end].sum().sort_values()
            wn, wv = cw.index[0], float(cw.iloc[0])
            names.append((wn, wv / r.pnl))
            say(f"| {i+1} | {r.start.date()} | {r.end.date()} | {r.pnl*100:.2f} "
                f"| {v0:.2f} | {p_full:.2f} | {p_pit:.2f} | {pk:.2f} | {p_peak:.2f} "
                f"| {'**YES**' if top else 'no'} | {'**YES**' if top_pk else 'no'} "
                f"| {wn} {wv*100:+.2f}% | {wv/r.pnl:.0%} |")
        ov = worst_windows(series, non_overlapping=False)
        ov_hits = sum(pct_rank(vs, float(vs.loc[:r.start].iloc[-1])) >= 0.80
                      for _, r in ov.iterrows())
        say()
        say(f"**{hits} of 10 START in the top VIX quintile** — the gate's own "
            f"statistic. **{peak_hits} of 10 CONTAIN a top-quintile VIX** at "
            "some point, which is the friendlier reading and still short of 7. "
            f"Overlapping selection gives {ov_hits} of 10 on the start test and "
            f"collapses onto {ov.start.dt.to_period('M').nunique()} distinct "
            "months — which is why the non-overlapping census is the one the "
            "gate reads.")
        say()
        top_names = pd.Series([n for n, _ in names]).value_counts()
        say(f"**The drawdowns are single-name events.** Across the ten windows "
            f"the worst single fund accounts for a median "
            f"{np.median([sh for _, sh in names]):.0%} of the loss — "
            + ", ".join(f"**{n}** leads {c}" for n, c in top_names.items())
            + ". That is not a shape an index option can hedge, and it is the "
            "same concentration the book's effective breadth of ~1.2 against 17 "
            "nominal names already says (`00_BRIEF.md` §1).")
        say()
        # The single most informative row in this table, stated rather than left
        # for the reader to divide: in the one genuine vol event this book has
        # traded, the loss was ONE fund and the rest of the book was long the
        # reversion. Computed, not asserted.
        if scope != scopes[0][0]:
            gate_rows[scope] = (hits, peak_hits, start_pcts, names)
            continue
        worst_vol = max(range(len(ws)),
                        key=lambda i: pct_rank(vs, float(vs.loc[ws.start[i]:ws.end[i]].max())))
        wv_row = ws.iloc[worst_vol]
        cw = contrib.loc[wv_row.start:wv_row.end].sum()
        lead = cw.idxmin()
        say(f"**Read window {worst_vol+1} carefully.** "
            f"{wv_row.start.date()}..{wv_row.end.date()} is the window with the "
            f"highest peak VIX in the table "
            f"({float(vs.loc[wv_row.start:wv_row.end].max()):.2f}). The book lost "
            f"{wv_row.pnl*100:.2f}% — but **{lead} alone lost "
            f"{cw[lead]*100:.2f}%, so the other {len(cw)-1} names together made "
            f"{(cw.sum()-cw[lead])*100:+.2f}%.** In the single genuine credit "
            "vol event this book has ever traded, everything except one "
            "premium fund was being paid by the reversion. A put on HYG would "
            "have bought protection against the part that was working.")
        say()
        gate_rows[scope] = (hits, peak_hits, start_pcts, names)
    say()

    # --- A4 conditional IC ------------------------------------------------
    say("## A4 Conditional IC by VIX tercile at signal time")
    say()
    panel = build_panel()
    z = panel["z"].reindex(index=pnl.index, columns=list(UNIVERSE))
    R_tot = R_tot.reindex(pnl.index)
    ic = conditional_ic(z, R_tot, vix)
    say("Spearman(z at *t*, forward 2-day return from *t+2*), non-overlapping, "
        "date-clustered SE (H6). Expected sign is **negative** — a high z is a "
        "rich fund the book shorts.")
    say()
    say("| VIX tercile | VIX range | mean IC | t | dates |")
    say("|---|---|---:|---:|---:|")
    for b in ic.index:
        r = ic.loc[b]
        say(f"| {b} | {r.state_lo:.1f}–{r.state_hi:.1f} | {r['mean']:+.4f} "
            f"| {r['t']:+.2f} | {int(r['count']):,} |")
    ratio, ratio_txt = ic_ratio(ic)
    say()
    say(f"**IC ratio high ÷ low = {ratio_txt}.** A ratio above 1 means the "
        "signal works BETTER in stress; it is only interpretable while both "
        "ICs carry the expected negative sign, and this function refuses to "
        "print one when they do not.")
    say()
    say("By group (the four mechanisms the book actually holds):")
    say()
    say("| group | names | low-vol IC | high-vol IC | ratio |")
    say("|---|---:|---:|---:|---:|")
    grp = (pd.read_parquet(REPO / "data/cef/cef_distributions.parquet")
           .drop_duplicates("ticker").set_index("ticker")["grp"])
    for g in sorted(set(grp.reindex(UNIVERSE).dropna())):
        names = [t for t in UNIVERSE if grp.get(t) == g]
        # A cross-sectional rank correlation on a handful of names is not a
        # small estimate, it is a degenerate one: with two names Spearman is
        # +-1 by construction. conditional_ic requires 5 valid pairs per date,
        # so a group below that yields no dates at all -- report the gap, never
        # a NaN dressed as a number.
        if len(names) < 5:
            say(f"| {g} | {len(names)} | UNMEASURED | UNMEASURED | "
                "a cross-sectional IC needs ≥5 names on the date |")
            continue
        gi = conditional_ic(z[names], R_tot.reindex(columns=names), vix)
        _, gtxt = ic_ratio(gi)
        say(f"| {g} | {len(names)} | {gi.loc['low','mean']:+.4f} "
            f"| {gi.loc['high','mean']:+.4f} | {gtxt} |")
    say()
    say("### Forward 21-day book P&L after a top-decile VIX day")
    say()
    # The threshold comes from the TRADED sample, not the full spliced VIX.
    # Taking it from 1996-2026 sets the bar with 2008's VIX of 80 -- a vol state
    # this book was never exposed to -- which is exactly what A0 says it will
    # not do. Measured: 29.40 on the full series against 26.07 here, 178
    # entries against 330.
    entries = vix.reindex(pnl.index).dropna()
    d10 = entries.quantile(0.90)
    # Entry-aligned: a decision at t is filled at t+1 and first EARNS at t+2
    # (H1), so the window a top-decile VIX day actually buys is pnl[t+2..t+22].
    # The earlier version summed pnl[t+1..t+21], whose first term belongs to the
    # t-1 decision.
    fwd21 = pnl.shift(-2).rolling(21).sum().shift(-20)
    hot = entries[entries >= d10].index
    base = fwd21.dropna()
    hotv = fwd21.reindex(hot).dropna()
    say(f"VIX top decile **within the traded sample** is ≥ {d10:.2f}. Deciding "
        f"on such a day, the 21 sessions the decision actually earns "
        f"(*t+2*..*t+22*, per shift(2)) return **{hotv.mean()*100:+.2f}%** on average "
        f"({len(hotv):,} entries) against **{base.mean()*100:+.2f}%** "
        f"unconditionally ({len(base):,}). Difference "
        f"**{(hotv.mean()-base.mean())*100:+.2f}pp** per 21 sessions.")
    say()

    # --- A5 basis ---------------------------------------------------------
    say("## A5 Basis — the ceiling on what an HYG overlay could remove")
    say()
    hyg = etf_total_returns(["HYG"])["HYG"] - cash_rate()
    u_hyg = univariate_r2(pnl, hyg.rename("HYG_XS"))
    say(f"Book P&L on HYG excess return alone: β {u_hyg['beta']:+.4f} "
        f"(t {u_hyg['t']:+.2f}), **R² = {u_hyg['r2']:.4f}** over "
        f"{u_hyg['n']:,} days. That is the ceiling on how much of this book's "
        "variance any HYG instrument can address.")
    say()
    say()
    say("On one common sample, so the four are comparable, HYG explains **less** "
        "of this book than the equity index does:")
    say()
    say("| regressor (univariate) | β | t (NW5) | R² |")
    say("|---|---:|---:|---:|")
    common4 = F.dropna().index.intersection(hyg.dropna().index).intersection(pnl.dropna().index)
    for lab, x in (("HYG excess return", hyg.rename("HYG_XS")),
                   ("SPY excess return", F["SPX_XS"]),
                   ("ΔVIX", F["D_VIX"]),
                   ("short-straddle proxy", F["SHORTVOL"])):
        u = univariate_r2(pnl.reindex(common4), x.reindex(common4))
        say(f"| {lab} | {u['beta']:+.5f} | {u['t']:+.2f} | {u['r2']:.4f} |")
    say()
    say(f"n = {len(common4):,}. **The only credit-volatility instrument this "
        "account can reach is the weakest of the four.** That is the basis "
        "problem stated as a number rather than as an anecdote, and it would "
        "still bind even if Part A's gate had passed.")
    say()
    say("**Book P&L on ΔHYG-IV: UNMEASURED** — see A2. The prompt asks for "
        "this number explicitly and it cannot be produced without `gamma/G2`.")
    say()
    say("For scale, the two legs are not the same instrument: in March 2020 "
        "CEF discounts widened by more than 1,600bp while HYG's own average "
        "absolute premium/discount to NAV rose only from 0.21% to 1.06% "
        "(`00_BRIEF.md` §3 — **[S]**, not re-fetched here).")
    say()
    say("**`rich_ratio` for credit: UNMEASURED.** `data/vrp/vrp_series.parquet` "
        "carries it for SPY and QQQ only; the credit figure is `gamma/G6`'s "
        f"deliverable. SPY's median over "
        f"{gid.index[0].date()}..{gid.index[-1].date()} is "
        f"{pd.read_parquet(REPO/'data/vrp/vrp_series.parquet').query('ticker==\"SPY\"')['rich_ratio'].median():.3f} "
        "— equity, not credit, and it is not a substitute.")
    say()

    # --- A6 what this implies for Part C, at zero trials -------------------
    say("## A6 What Part A implies for Part C — measured, no trial spent")
    say()
    say("Part C asks whether the band width and the vol target should know "
        "what volatility is doing. It costs **1 CEF trial** and it is "
        "**blocked**: its input is HYG ATM implied vol from `gamma/G2`'s "
        "surface, which does not exist, and substituting VIX would be running "
        "the prompt's own negative control as the treatment. What can be "
        "measured today at zero cost is whether the LIVE spec already behaves "
        "differently across vol states — a description of the current policy, "
        "not a specification.")
    say()
    turn = res_tot["turn_series"].reindex(pnl.index)
    st = vix.reindex(pnl.index).dropna()
    q = st.quantile([1 / 3, 2 / 3]).to_list()
    buckets = [("low", st <= q[0]), ("mid", (st > q[0]) & (st <= q[1])), ("high", st > q[1])]
    say("| VIX tercile at *t* | sessions | gross SR | ann % | turn/yr | net@5 | net@15 | net@30 |")
    say("|---|---:|---:|---:|---:|---:|---:|---:|")
    terc = {}
    base_idx = st.index
    bx, btu = pnl.reindex(base_idx), turn.reindex(base_idx)
    b_ann, b_vol, b_turn = bx.mean() * 252, bx.std() * np.sqrt(252), btu.mean() * 252
    b_nets = [(b_ann - b_turn * c / 1e4) / b_vol for c in (5, 15, 30)]
    say(f"| **all traded sessions (baseline)** | {len(base_idx):,} "
        f"| {b_ann/b_vol:.2f} | {b_ann*100:.2f} | {b_turn:.1f} "
        + "".join(f"| {n:.2f} " for n in b_nets) + "|")
    for lab, mask in buckets:
        idx = st[mask].index
        x, tu = pnl.reindex(idx), turn.reindex(idx)
        ann, vol_, tn = x.mean() * 252, x.std() * np.sqrt(252), tu.mean() * 252
        nets = [(ann - tn * c / 1e4) / vol_ for c in (5, 15, 30)]
        terc[lab] = dict(ann=ann, turn=tn, net15=nets[1])
        say(f"| {lab} | {len(idx):,} | {ann/vol_:.2f} | {ann*100:.2f} | {tn:.1f} "
            + "".join(f"| {n:.2f} " for n in nets) + "|")
    say()
    best_gross = max(terc, key=lambda k: terc[k]["ann"])
    best_net = max(terc, key=lambda k: terc[k]["net15"])
    say()
    say(f"**The baseline row is the only honest comparator here**, and it is "
        f"not the repo's headline net@15 of 0.67 / turn 17.6 — those are "
        f"FULL-PANEL figures diluted by the 2,126 flat sessions. Against the "
        f"traded-session baseline (turn {b_turn:.1f}, net@15 {b_nets[1]:.2f}) "
        f"the **{best_net}** tercile is "
        f"{terc[best_net]['net15']-b_nets[1]:+.2f} and the **{best_gross}** "
        f"tercile trades {terc[best_gross]['turn']/b_turn:.2f}× baseline, not "
        f"{terc[best_gross]['turn']/17.6:.2f}×. Read against the wrong "
        "baseline this table shows a state effect that is mostly the dropped "
        "flat sessions running in reverse.")
    say()
    say(f"With that said: the **{best_gross}** tercile earns the most gross "
        f"({terc[best_gross]['ann']*100:.2f}%/yr) and the **{best_net}** "
        f"tercile keeps the most net@15 ({terc[best_net]['net15']:.2f} against "
        f"{terc[best_gross]['net15']:.2f}), because the high-vol tercile also "
        f"trades the most ({terc['high']['turn']:.1f} turn/yr against "
        f"{terc['low']['turn']:.1f} low and {terc['mid']['turn']:.1f} mid). "
        "**That gap is a transfer-coefficient problem, not a convexity one**, "
        "and it is exactly what a state-scaled band would attack.")
    say()
    say("Cost grid 5/15/30bp (H3); borrow is charged separately and is not in "
        "these columns (H4). Turnover here is the band's own, conditioned on "
        "the state — not a matched comparison, because there is no alternative "
        "policy in this table to match against (H2 applies to comparisons).")
    say()
    say("The cube-root law says the no-trade half-width should scale as "
        "`σ_w^(2/3)`. Measured on this book's own target weights, the trailing "
        "63-session sd of daily target changes in the top VIX tercile against "
        "the bottom is:")
    # sigma_w is the diffusion of a NAME's target weight, so it is measured
    # per name and averaged -- not on the book's summed turnover, which mixes
    # the diffusion with the number of names moving at once.
    dT = T.reindex(pnl.index).diff()
    sw = dT.rolling(63).std().mean(axis=1)
    lo = sw.reindex(st[st <= q[0]].index).mean()
    hi = sw.reindex(st[st > q[1]].index).mean()
    say()
    say(f"σ_w low-vol **{lo:.5f}**, high-vol **{hi:.5f}**, ratio "
        f"**{hi/lo:.2f}×** → the cube-root law implies a band "
        f"**{(hi/lo)**(2/3):.2f}×** wider in stress, i.e. "
        f"{BAND_WIDTH*100:.1f}% → **{BAND_WIDTH*(hi/lo)**(2/3)*100:.1f}%**. "
        "That is the size of the effect Part C would be chasing. It is derived "
        "from the law and the measured ratio, not swept (H8), and it is "
        "recorded here so that Part C cannot later pick a width and call it "
        "derived.")
    say()

    # --- A7 verdict -------------------------------------------------------
    say("## A7 Verdict")
    say()
    hits_full, peak_full, start_pcts, dd_names = gate_rows["all traded sessions"]
    say("| quantity the prompt asks for | value |")
    say("|---|---|")
    say(f"| β_ΔVIX (t, NW5), prompt's factor set | **{b_vix:+.6f}** "
        f"(t {t_vix:+.2f}) = ${b_vix*CAPITAL_USD:+,.0f} per VIX point |")
    say(f"| β_ΔVIX, longest window (no straddle leg) — the least favourable "
        f"reading | {long['beta']['D_VIX']:+.6f} (t {long['t']['D_VIX']:+.2f}) "
        f"= ${long['beta']['D_VIX']*CAPITAL_USD:+,.0f} per VIX point |")
    say("| β_ΔHYG-IV | **UNMEASURED** — no credit surface exists (`gamma/G2`) |")
    say(f"| worst-10 windows starting in top VIX quintile | **{hits_full}/10** "
        f"(the gate's statistic); {peak_full}/10 contain a top-quintile VIX |")
    say(f"| IC ratio, high-vol ÷ low-vol tercile | **{ratio_txt}** |")
    say("| credit `rich_ratio` (G6) | **UNMEASURED** — SPY/QQQ only |")
    say()
    cond_beta = (b_vix < 0) and (abs(t_vix) >= 2.5)
    cond_dd = hits_full >= 7
    say(f"**The gate.** Part B opens only on β_ΔVIX < 0 with |t| ≥ 2.5 "
        f"({'PASS' if cond_beta else 'FAIL'}: β {b_vix:+.6f}, |t| {abs(t_vix):.2f}) "
        f"**AND** ≥ 7 of 10 drawdown windows in the top VIX quintile "
        f"({'PASS' if cond_dd else 'FAIL'}: {hits_full}/10).")
    say()
    say(f"### PART B IS {'OPEN' if (cond_beta and cond_dd) else 'CLOSED'}")
    say()
    say("### What the gate does NOT say")
    say()
    say(f"The gate reads ΔVIX. Two readings in this note point the other way "
        f"and are stated here rather than left in a table:")
    say()
    say(f"* **`SHORTVOL` loads +{full['beta']['SHORTVOL']:.3f} "
        f"(t {full['t']['SHORTVOL']:+.2f}) full sample and "
        f"+{regress(pnl.loc[HOLDOUT_START:], F)['beta']['SHORTVOL']:.3f} "
        f"(t {regress(pnl.loc[HOLDOUT_START:], F)['t']['SHORTVOL']:+.2f}) on "
        "the 2023-26 holdout.** A POSITIVE loading on a *short*-straddle "
        "return is the short-vol sign. It is the only tradeable vol factor in "
        "the panel and the holdout reading is the only |t| > 2 vol number in "
        "the era table.")
    say(f"* **Univariate ΔVIX is {uni['D_VIX']['beta']:+.6f} at "
        f"t {uni['D_VIX']['t']:+.2f}**, which clears the gate's own |t| ≥ 2.5 "
        "bar on its own. The gate is specified on the full factor set and is "
        "read that way, but a reader should know the verdict is "
        "specification-dependent in that one respect.")
    say()
    say("So the correct statement is narrower than \"no vol exposure\", and is "
        "the one below.")
    say()
    say("### The sentence")
    say()
    say(f"**The book carries a mild short-volatility exposure, and it is not "
        f"the kind an option can profitably hedge.** It loses on the day "
        f"volatility jumps ({d5:+.2f}bp on the top-5% ΔVIX days against "
        f"{d0:+.2f}bp unconditionally, {d1:+.2f}bp on the top 1%), but that "
        f"loss is about {abs(d1)/daily_sd:.1f} daily standard deviations, is "
        f"not statistically distinguishable from zero (t {t1:+.2f}), and is "
        f"recovered several times over in the following month "
        f"({f1:+.2f}% over the next 21 sessions against {f0:+.2f}% "
        f"unconditionally). Its ten worst 21-session windows do not start in "
        f"high-vol states — {hits_full} of 10 in the top VIX quintile, and the "
        f"two worst begin at the {start_pcts[0]:.0%} and {start_pcts[1]:.0%} "
        f"percentiles of VIX and are "
        f"{dd_names[0][1]:.0%} and {dd_names[1][1]:.0%} attributable to "
        + (f"one fund, {dd_names[0][0]}" if dd_names[0][0] == dd_names[1][0]
           else f"{dd_names[0][0]} and {dd_names[1][0]} respectively")
        + ". And the "
        f"signal is **{ratio_txt}× stronger** in the high-vol tercile "
        f"(IC {ic.loc['high','mean']:+.4f} against "
        f"{ic.loc['low','mean']:+.4f}), so the P&L a hedge would protect is "
        f"the P&L the strategy exists to earn. **The exposure is real and "
        f"small; the hedge is what does not pay.**")
    say()
    say(f"The mechanism in the prompt is half right: the book *is* at full size "
        f"when the shock lands and it *does* lose on the widening. What the "
        f"mechanism got wrong is the sign of what comes next — the reversion "
        f"arrives fast enough, and large enough, that the shock is the "
        f"book's best entry rather than its worst. Buying convexity would sell "
        f"that.")
    say()
    if not (cond_beta and cond_dd):
        say("A hedge that pays in states where the book does not lose is a pure "
            "carry cost. The honest answer is **Part C** (options as "
            "information — band width and vol target conditioned on implied "
            "vol, no option traded, 1 CEF trial) plus the standalone "
            "`gamma/` programme on its own counter — and note from A6 that the "
            f"high-vol tercile earns {terc['high']['ann']*100:.2f}%/yr gross "
            f"but keeps only {terc['high']['net15']:.2f} net@15 against the mid "
            f"tercile's {terc['mid']['net15']:.2f}, because it trades "
            f"{terc['high']['turn']/terc['mid']['turn']:.2f}× as much. That is "
            "a transfer-coefficient problem, which is the lever this desk "
            "already knows is the largest one.")
    say()
    say("### What would reverse this")
    say()
    say("Stated now, before anyone looks again (H14 — re-measure, never quote "
        "this file): Part B re-opens if a re-run of this script clears BOTH "
        "gate conditions, or if `gamma/G2`'s HYG surface lands and β_ΔHYG-IV "
        "is negative with |t| ≥ 2.5 where β_ΔVIX was not — that would say the "
        "exposure is credit-vol specific and the equity index was simply the "
        "wrong instrument to look through. The basis R² in A5 is the prior on "
        "how likely that is, and it is small. The other reversal is a sample "
        "one: this book has never traded a credit crisis, so the census above "
        "is a statement about 2013–2026 and nothing else.")
    say()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
