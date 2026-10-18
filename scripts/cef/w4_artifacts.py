"""W4 -- the artifact battery on the DEPLOYED discount signal. Zero trials.

    python3 scripts/cef/w4_artifacts.py               # every section, to stdout
    python3 scripts/cef/w4_artifacts.py ic bounce     # chosen sections only

Item 0.6 of results/cef/RESEARCH_PLAN_2026-10-09.md; the questions are the
archived work order (`git show pre-clean-slate:_archive/docs/prompts/W4_artifact_battery.md`)
plus a factor attribution. The write-up is results/cef/W4_ARTIFACTS_2026-10-11.md.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
Descriptive measurement of the signal the book trades -- the frozen spec's
universe, z-window, ADV filter, min-names, band width and gross ceiling, all
read through `scripts/cef/spec.py` -- so that every later "incremental to the
z-score" claim has a clean baseline. It tests NO new signal, chooses NOTHING,
and increments no counter. Where a section builds an alternative version of
the discount (on the quote midpoint, on the closing-auction print, with the
stale part of the NAV removed) it is a DECOMPOSITION of the deployed signal:
only its IC is reported, never a policy P&L, and nothing here is a candidate
for the spec. Trading any of those versions is W13 / C3, a counted trial.

THE TWO HOLDOUTS
----------------
* Time: every panel is truncated to 2022-12-30 BEFORE anything is computed
  (`build_panel(end=FIT_END)`, `fit_only`), and `_assert_fit` checks every
  frame that reaches a statistic. A forward window that would need a 2023
  return is NaN and drops out; it is never filled.
* Names: only the spec's universe is read. No name from `cef_universe.csv`
  outside it (the untouched set) enters any computation.

THE HARNESS
-----------
P&L comes only from `evaluate()` in band_frontier.py (shift(2): decide t, MOC
fill t+1, earn t+2). The deployed policy is `band_gross_capped(T, BAND_WIDTH,
MAX_GROSS_STRESS)`, exactly the v7 live policy. "Skip a day" is
`evaluate(H.shift(1), R)` -- the canonical function fed a book decided one day
earlier, i.e. shift(3) -- not a second backtester. Every P&L table carries the
gross headline and the 5/15/30bp grid beside it (`band_frontier._stats`), and a
"flips?" column that is YES if any of gross/5/15/30 differ in sign.

IC (H6): Spearman between the signal at t and the forward 2-day return over
closes t+1 -> t+3 (the days a book decided at t earns), on a NON-OVERLAPPING
grid (every second session), min names = the spec's `min_names`. One IC per
date, so its t is clustered by date by construction; Newey-West and a moving-
block bootstrap are reported beside it, and the pooled-regression t is shown
naive / date-clustered / two-way clustered (Part E of the work order).

The DEPLOYED set on date t is {names with a z-score and 63-day ADV through t-1
>= min_adv_usd}, used only when it has >= min_names names -- exactly the rows
`build_targets` acts on (checked date by date in the 2026-10-11 review: 0 of
4,531 dates differ; NOT pinned by a test, so re-check if build_targets'
eligibility rule ever changes). On 13 names this first happens on 2013-06-21; the
2005-09 era is EMPTY and 2010-14 is 18 months. A WIDE set (every name with a
z-score, no ADV filter) is reported beside it, labelled, because it is the only
way to see 2005-12; it is NOT the deployed signal.

DATA (all read-only; nothing under data/ is written)
-----------------------------------------------------
data/cef/cef_prices.parquet, cef_nav.parquet, cef_distributions.parquet,
cef_universe.csv (group labels). Gitignored caches written by the fetchers in
scripts/data/: crsp_dsf_w4.parquet (stage_crsp_w4.py), ff5_umd_*.parquet
(fetch_ff_factors.py), ps_liquidity_monthly.parquet (fetch_pastor_liquidity.py),
alpaca_closing_prints_2016_2022.parquet (fetch_alpaca_auction_history.py).
A missing cache raises naming the script that builds it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import (  # noqa: E402
    HOLDOUT_START, MIN_ADV, SAMPLE_START, _stats, band, band_gross_capped,
    build_panel, build_targets, evaluate, fit_only, total_returns,
)
from scripts.cef.spec import (  # noqa: E402
    BAND_WIDTH, MAX_GROSS_STRESS, MIN_NAMES, UNIVERSE, Z_WINDOW, summary,
)
from scripts.cef.band_frontier import MIN_PERIODS  # noqa: E402

CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
FIT_END = "2022-12-30"                      # last session before the sealed holdout
ERAS = [("2005-09", "2005-01-01", "2009-12-31"), ("2010-14", "2010-01-01", "2014-12-31"),
        ("2015-19", "2015-01-01", "2019-12-31"), ("2020-22", "2020-01-01", "2022-12-31")]
FIT = ("fit 2005-22", "2005-01-01", "2022-12-31")
COSTS = (5, 15, 30)
DEPLOYED_WIN = (2, 3)                       # closes t+1 -> t+3: what a book decided at t earns
CRISES = {"GFC 2008-09..2009-03": ("2008-09-01", "2009-03-31"),
          "COVID 2020-02-20..04-30": ("2020-02-20", "2020-04-30"),
          "March 2020": ("2020-03-01", "2020-03-31")}
NW_LAGS = 5
BOOT_BLOCK, BOOT_REPS, SEED = 20, 2000, 20261011
PROXY_OF = {"muni": ["MUB"], "hy": ["HYG"], "loan": ["BKLN"], "multi": ["HYG", "LQD"]}
LEADLAG_K = 3                               # proxy lags 0..3


# --------------------------------------------------------------------------- utilities

def _assert_fit(*frames):
    """H13: nothing that reaches a statistic may carry a 2023+ date."""
    for f in frames:
        idx = f.index if hasattr(f, "index") else f
        if len(idx) and pd.Timestamp(idx.max()) >= HOLDOUT_START:
            raise AssertionError(f"holdout leak: a frame reaches {idx.max()}")


def _need(path: Path, builder: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(REPO)} is missing; build it with "
                                f"`python3 {builder}`. No substitute is used.")
    return path


def groups() -> dict:
    g = pd.read_csv(REPO / "data/cef/cef_universe.csv").set_index("ticker")["grp"]
    missing = sorted(set(UNIVERSE) - set(g.index))
    if missing:
        raise ValueError(f"cef_universe.csv has no group for {missing}")
    return {t: g[t] for t in UNIVERSE}


def fwd(r: pd.DataFrame, a: int, b: int) -> pd.DataFrame:
    """Compounded return over sessions t+a .. t+b. NaN if any day is NaN.

    ALIGNMENT: row t holds returns of rows t+a..t+b. With a=2, b=3 that is the
    move from close t+1 to close t+3 -- what weights decided at t earn under
    shift(2). a=1 includes close t -> t+1, a price NO book decided at t can
    trade at; it is used only where labelled 'infeasible'."""
    if a < 1 or b < a:
        raise ValueError(f"window [{a},{b}] must start at t+1 or later")
    out = None
    for k in range(a, b + 1):
        x = 1.0 + r.shift(-k)
        out = x if out is None else out * x
    return out - 1.0


def fwd_log(r: pd.DataFrame, a: int, b: int) -> pd.DataFrame:
    out = None
    for k in range(a, b + 1):
        x = np.log1p(r.shift(-k))
        out = x if out is None else out + x
    return out


def grid(index: pd.DatetimeIndex, phase: int = 0) -> pd.DatetimeIndex:
    """Every second session: non-overlapping 2-day windows (H6)."""
    return index[phase::2]


def ic_series(S, F, M, dates, min_n=MIN_NAMES) -> pd.Series:
    """Spearman(S_t, F_t) across names on each date in `dates`, where M is True."""
    S, F, M = S.reindex(dates), F.reindex(dates), M.reindex(dates, fill_value=False)
    ok = M & S.notna() & F.notna()
    rs = S.where(ok).rank(axis=1)
    rf = F.where(ok).rank(axis=1)
    rs = rs.sub(rs.mean(axis=1), axis=0)
    rf = rf.sub(rf.mean(axis=1), axis=0)
    num = (rs * rf).sum(axis=1)
    den = np.sqrt((rs ** 2).sum(axis=1) * (rf ** 2).sum(axis=1))
    ic = num / den.replace(0, np.nan)
    n = ok.sum(axis=1)
    return ic[(n >= min_n) & ic.notna()]


def fm_slopes(S, F, M, dates, min_n=MIN_NAMES) -> pd.Series:
    """Per-date OLS slope of demeaned F on demeaned S (Fama-MacBeth)."""
    S, F, M = S.reindex(dates), F.reindex(dates), M.reindex(dates, fill_value=False)
    ok = M & S.notna() & F.notna()
    s = S.where(ok)
    f = F.where(ok)
    s = s.sub(s.mean(axis=1), axis=0)
    f = f.sub(f.mean(axis=1), axis=0)
    b = (s * f).sum(axis=1) / (s ** 2).sum(axis=1).replace(0, np.nan)
    n = ok.sum(axis=1)
    return b[(n >= min_n) & b.notna()]


def nw_t(x: pd.Series, lags: int = NW_LAGS) -> float:
    """t of the mean with a Newey-West (Bartlett) long-run variance."""
    v = x.dropna().values
    n = len(v)
    if n < 10:
        return np.nan
    e = v - v.mean()
    lrv = e @ e / n
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        lrv += 2 * w * (e[L:] @ e[:-L]) / n
    return v.mean() / np.sqrt(lrv / n)


def nw_auto_lag(x: pd.Series) -> int:
    """Newey & West (1994) automatic bandwidth for the Bartlett kernel (added
    2026-10-14 for trial C5's inference table, PREREG_C5 §8; a second method
    beside the declared fixed L, never the deciding one).

    The plug-in rule of "Automatic Lag Selection in Covariance Matrix
    Estimation" (Rev. Econ. Stud. 61, 1994), univariate: with
    n = floor(4 (T/100)^(2/9)) pilot lags and sample autocovariances g_j,
    s0 = g_0 + 2 sum_{j<=n} g_j, s1 = 2 sum_{j<=n} j g_j,
    gamma = 1.1447 ((s1/s0)^2)^(1/3), and the lag is floor(gamma T^(1/3)).
    Raises on fewer than 10 observations rather than returning a default."""
    v = x.dropna().values.astype(float)
    T = len(v)
    if T < 10:
        raise ValueError(f"nw_auto_lag: {T} observations; at least 10 are needed")
    e = v - v.mean()
    n = int(np.floor(4 * (T / 100.0) ** (2.0 / 9.0)))
    g = np.array([e[j:] @ e[:T - j] / T for j in range(n + 1)])
    s0 = g[0] + 2 * g[1:].sum()
    s1 = 2 * (np.arange(1, n + 1) * g[1:]).sum()
    if not s0 > 0:
        raise ValueError("nw_auto_lag: the pilot long-run variance is not positive")
    gamma = 1.1447 * ((s1 / s0) ** 2) ** (1.0 / 3.0)
    return int(np.floor(gamma * T ** (1.0 / 3.0)))


def stationary_boot(x: pd.Series, mean_block: float = 21, reps: int = 10_000,
                    seed: int = 20261013, chunk: int = 1_000) -> dict:
    """Politis & Romano (1994) stationary bootstrap of a daily series: the
    resampled MEAN and annualised SHARPE (mean / sd(ddof=1) * sqrt(252)) of each
    of `reps` draws.

    Added 2026-10-14 beside `nw_t` for trial C5 (PREREG_C5 §8: mean block 21,
    10,000 resamples, seed 20261013). C4's pre-registration declares the same
    helper "beside nw_t" (PREREG_C4 §8); whichever trial lands first serves
    both, so the defaults are the declared ones and each caller scales the
    draws to its own units (bp/yr, %/yr, per unit of turnover).

    WHY STATIONARY AND NOT `block_boot_t`'s MOVING BLOCKS: block lengths are
    geometric with mean `mean_block` and the series is wrapped circularly, so
    the resample is itself stationary and the result does not hinge on one
    fixed block length or lose the series' ends; `block_boot_t` stays as the
    declared second method.

    Each draw: the first index is uniform; each later one starts a new block
    with probability 1/mean_block (a uniform index) and otherwise continues the
    current block one step, modulo n. Drawn in chunks of `chunk` resamples to
    bound memory; the random stream is fixed by `seed` alone.

    Returns dict(means, sharpes) as arrays of length `reps`, plus the 95%
    percentile intervals lo_mean/hi_mean and lo_sr/hi_sr. Raises on a series
    shorter than three mean blocks (no default answer)."""
    v = x.dropna().values.astype(float)
    n = len(v)
    if n < 3 * mean_block:
        raise ValueError(f"stationary_boot: {n} observations for a mean block of {mean_block}")
    if mean_block < 1:
        raise ValueError("stationary_boot: mean_block must be >= 1")
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block
    means, sharpes = np.empty(reps), np.empty(reps)
    pos = np.arange(n)
    done = 0
    while done < reps:
        k = min(chunk, reps - done)
        starts = rng.integers(0, n, size=(k, n))
        new = rng.random((k, n)) < p
        new[:, 0] = True
        last = np.maximum.accumulate(np.where(new, pos[None, :], 0), axis=1)
        idx = (np.take_along_axis(starts, last, axis=1) + (pos[None, :] - last)) % n
        s = v[idx]
        m = s.mean(axis=1)
        sd = s.std(axis=1, ddof=1)
        means[done:done + k] = m
        with np.errstate(divide="ignore", invalid="ignore"):
            sharpes[done:done + k] = np.where(sd > 0, m / sd * np.sqrt(252), np.nan)
        done += k
    return dict(means=means, sharpes=sharpes,
                lo_mean=float(np.percentile(means, 2.5)), hi_mean=float(np.percentile(means, 97.5)),
                lo_sr=float(np.nanpercentile(sharpes, 2.5)), hi_sr=float(np.nanpercentile(sharpes, 97.5)))


def nw94_lag(x: pd.Series) -> int:
    """C4's name for `nw_auto_lag` (PREREG_C4 §8), capped at T - 1 as C4 declared.

    C4 and C5 each added the Newey-West (1994) plug-in on 2026-10-14; the two
    were the same formula, so one implementation serves both (merged
    2026-10-18). Reported beside the declared L, never used to decide."""
    v = pd.Series(x).dropna()
    return int(min(len(v) - 1, nw_auto_lag(v)))


def block_boot_t(x: pd.Series, block=BOOT_BLOCK, reps=BOOT_REPS, seed=SEED):
    """Moving-block bootstrap of the mean: (t = mean/se, lo95, hi95)."""
    v = x.dropna().values
    n = len(v)
    if n < 3 * block:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n]
    means = v[idx].mean(axis=1)
    se = means.std(ddof=1)
    return v.mean() / se, np.percentile(means, 2.5), np.percentile(means, 97.5)


def ic_row(ic: pd.Series) -> dict:
    if len(ic) < 10:
        return dict(n=len(ic), ic=np.nan, t=np.nan, t_nw=np.nan)
    return dict(n=len(ic), ic=ic.mean(), t=ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic)),
                t_nw=nw_t(ic))


def fmt_ic(label, ic, extra="") -> str:
    r = ic_row(ic)
    return (f"{label:<46}{r['n']:6d}{r['ic']:+9.4f}{r['t']:8.2f}{r['t_nw']:8.2f}{extra}")


IC_HDR = f"{'':<46}{'dates':>6}{'meanIC':>9}{'t':>8}{'t(NW)':>8}"


def by_era(series: pd.Series, eras=ERAS + [FIT]):
    return [(lab, series.loc[a:b]) for lab, a, b in eras]


def pnl_table(rows, title):
    """rows: list of (label, H, R). Gross headline, cost grid beside it, by era."""
    print(f"\n{title}")
    print("GROSS SR is the headline; net@5/15/30bp is the real-money cost grid "
          "(bp per unit turnover), labelled, not mixed in. No borrow charged.")
    hdr = (f"{'':<34}{'era':<12}{'grossSR':>8}{'ann%':>7}{'vol%':>6}{'turn/yr':>8}"
           f"{'net@5':>7}{'net@15':>7}{'net@30':>7}{'flips?':>7}")
    print(hdr)
    print("-" * len(hdr))
    out = {}
    for lab, H, R in rows:
        _assert_fit(H, R)
        r = evaluate(H, R)
        turns = []
        # Book-live sessions: from the first non-zero P&L. The harness's era rows (kept,
        # for comparability with every other table in the repo) include the flat
        # sessions before the book first trades, which dilute 2010-14 and the fit row
        # (review 2026-10-11); the 'live' rows below remove that dilution.
        live0 = r["pnl"].index[r["pnl"].ne(0)].min()
        live_eras = [("live 2010-14", live0, "2014-12-31"), ("live fit", live0, "2022-12-31")]
        live_turns = []
        for era, a, b in ERAS + [FIT] + live_eras:
            pnl, turn = r["pnl"].loc[a:b], r["turn_series"].loc[a:b]
            if pnl.std() == 0 or pnl.abs().sum() == 0:
                print(f"{lab:<34}{era:<12}{'book flat: no position in this era':>40}")
                continue
            if era.startswith("live") or era in ("2015-19", "2020-22"):
                if era != "live fit":
                    live_turns.append(_stats(pnl, turn)["turn"])
            s = _stats(pnl, turn)
            sg = [np.sign(s["sr"])] + [np.sign(n) for n in s["nets"]]
            flip = "YES" if len(set(sg)) > 1 else "no"
            print(f"{lab:<34}{era:<12}{s['sr']:8.2f}{s['ann'] * 100:7.2f}{s['vol'] * 100:6.2f}"
                  f"{s['turn']:8.1f}" + "".join(f"{n:7.2f}" for n in s["nets"]) + f"{flip:>7}")
            out[(lab, era)] = s
            if era != FIT[0] and not era.startswith("live"):
                turns.append(s["turn"])
        t = np.array(turns)
        if len(t) > 1:
            print(f"{'':<34}{'era turnover sd/mean (eras with a book)':<52}{t.std() / t.mean():6.1%}")
        tl = np.array(live_turns)
        if len(tl) > 1:
            print(f"{'':<34}{'  same, 2010-14 on book-live sessions only':<52}{tl.std() / tl.mean():6.1%}")
    return out


# --------------------------------------------------------------------------- data

class Data:
    """Everything every section reads, built once, fit period only."""

    def __init__(self):
        self.grp = groups()
        p = build_panel(end=FIT_END)
        _assert_fit(p["px"])
        self.p = p
        idx = p["px"].index
        self.idx = idx[idx >= pd.Timestamp(SAMPLE_START)]
        U = list(UNIVERSE)
        self.U = U
        px, nav = p["px"][U], p["nav"][U]
        # price return, NaN-preserving (the harness's filter: |r| < 50%)
        self.r_px = p["ret"][U].reindex(self.idx)
        # total return: total_returns() adds D/P_{t-1} on ex-dates and splits (none pre-2023)
        self.r_tr = total_returns(self.r_px)
        # NAV total return: D/N_{t-1} on the same ex-dates (the distribution leaves the NAV)
        self.dist = self._dist_amounts(U)
        r_nav = nav.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
        y_nav = (self.dist / nav.shift(1)).reindex(index=idx, columns=U)
        self.r_nav_tr = (r_nav + y_nav.fillna(0.0)).reindex(self.idx)
        self.y_px = (self.dist / px.shift(1)).reindex(index=self.idx, columns=U).fillna(0.0)
        self.z = p["z"][U].reindex(self.idx)
        self.disc = p["disc"][U].reindex(self.idx)
        self.sd = p["sd"][U].reindex(self.idx)
        self.px = px.reindex(self.idx)
        self.nav = nav.reindex(self.idx)
        adv = p["adv"][U].reindex(self.idx)
        elig = self.z.notna() & (adv >= MIN_ADV)
        enough = elig.sum(axis=1) >= MIN_NAMES
        self.M_dep = elig.apply(lambda col: col & enough)
        self.M_wide = self.z.notna()
        # ex-date flags (name, date)
        self.ex = self.dist.reindex(index=self.idx, columns=U).notna()
        # harness objects (fillna(0) returns, as evaluate() expects)
        T, R_px = build_targets()
        T, R_px = fit_only(T, R_px)
        self.T, self.R_px = T, R_px
        self.R_tr = total_returns(R_px)
        self.R_nav_tr = self.r_nav_tr.reindex(T.index).fillna(0.0)[U]
        cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
        self.H = band_gross_capped(T, BAND_WIDTH, cap)
        self.H_plain = band(T, BAND_WIDTH)
        _assert_fit(self.T, self.R_tr, self.H, self.r_tr, self.r_nav_tr)
        self.G0, self.G1 = grid(self.idx, 0), grid(self.idx, 1)

    @staticmethod
    def _dist_amounts(U):
        d = pd.read_parquet(REPO / "data/cef/cef_distributions.parquet")
        d = d[d.ticker.isin(U)]
        d["ex_date"] = pd.to_datetime(d["ex_date"])
        d = d[d.ex_date < HOLDOUT_START]
        return d.groupby(["ex_date", "ticker"])["amount"].sum().unstack()

    def crsp(self) -> pd.DataFrame:
        c = pd.read_parquet(_need(CACHE / "crsp_dsf_w4.parquet", "scripts/data/stage_crsp_w4.py"))
        _assert_fit(c.set_index("date"))
        return c


def _pivot(c, col, tickers, index):
    x = c[c.ticker.isin(tickers)].pivot_table(index="date", columns="ticker", values=col)
    return x.reindex(index=index, columns=tickers)


# =========================================================================== sections

def sec_baseline(D: Data):
    """The deployed IC and its standard errors (work-order Part E) -- the baseline."""
    print("\n" + "=" * 100 + "\n0. THE DEPLOYED IC -- baseline and standard errors\n" + "=" * 100)
    F_tr, F_px = fwd(D.r_tr, *DEPLOYED_WIN), fwd(D.r_px, *DEPLOYED_WIN)
    print(f"signal: frozen-spec z (window {Z_WINDOW}, min_periods {MIN_PERIODS}, moments "
          f"shift(1), clip +/-4); forward window closes t+1 -> t+3; non-overlapping grid")
    print(IC_HDR)
    rows = {}
    for setlab, M in (("DEPLOYED set", D.M_dep), ("WIDE set (no ADV filter; NOT deployed)", D.M_wide)):
        for flab, F in (("total ret", F_tr), ("price ret", F_px)):
            for ph, G in (("phase 0", D.G0), ("phase 1", D.G1)):
                ic = ic_series(D.z, F, M, G)
                print(fmt_ic(f"{setlab[:22]} {flab} {ph}", ic))
                rows[(setlab, flab, ph)] = ic
    # second source for the forward return: CRSP `ret` (independent of yfinance prices and
    # of the panel's distribution file), same z, same dates and names
    c = D.crsp()
    r_crsp = _pivot(c[c.ticker.isin(D.U)], "ret", D.U, D.idx).where(lambda x: x.abs() < 0.5)
    F_cr = fwd(r_crsp, *DEPLOYED_WIN)
    common = D.M_dep & F_cr.notna() & F_tr.notna()
    print("second source for the forward return (CRSP ret), DEPLOYED set, common sample:")
    for ph, G in (("phase 0", D.G0), ("phase 1", D.G1)):
        print(fmt_ic(f"  panel total ret {ph}", ic_series(D.z, F_tr, common, G)))
        print(fmt_ic(f"  CRSP ret        {ph}", ic_series(D.z, F_cr, common, G)))
    print("\nby era, DEPLOYED set, total returns, phase 0 (the headline row is 'fit 2005-22'):")
    print(IC_HDR + f"{'FM bp/z':>9}{'t(FM)':>7}")
    ic0 = rows[("DEPLOYED set", "total ret", "phase 0")]
    fm0 = fm_slopes(D.z, F_tr, D.M_dep, D.G0) * 1e4
    for lab, s in by_era(ic0):
        f = fm0.loc[s.index.min():s.index.max()] if len(s) else fm0.iloc[:0]
        extra = (f"{f.mean():9.2f}{f.mean() / f.std() * np.sqrt(len(f)):7.2f}" if len(f) > 10 else "")
        print(fmt_ic(lab, s, extra) if len(s) >= 10 else f"{lab:<46}{len(s):6d}   (fewer than 10 dates: no estimate)")
    print("\nby era, WIDE set, total returns, phase 0 (context for 2005-12; NOT the deployed signal):")
    print(IC_HDR)
    icw = rows[("WIDE set (no ADV filter; NOT deployed)", "total ret", "phase 0")]
    for lab, s in by_era(icw):
        print(fmt_ic(lab, s))

    # Reconciliation with the 17-name figure docs/BRIEF.md quotes (IC -0.074, t -11.6,
    # 2026-09-05 [S]). v7 dropped NAD, NEA, NVG, NZF (PREREG_ALPACA_V7_2026-09-28.md):
    # deployed until 2026-09-28, never part of the untouched holdout, so reading them
    # here consumes nothing. Context only -- they are not the deployed book.
    v6 = list(UNIVERSE) + ["NAD", "NEA", "NVG", "NZF"]
    p6 = build_panel(end=FIT_END, universe=v6)
    _assert_fit(p6["px"])
    r6 = p6["ret"][v6].reindex(D.idx)
    z6 = p6["z"][v6].reindex(D.idx)
    a6 = p6["adv"][v6].reindex(D.idx)
    e6 = z6.notna() & (a6 >= MIN_ADV)
    en6 = e6.sum(axis=1) >= MIN_NAMES
    print("\nreconciliation, v6 17-name universe (NOT deployed since 2026-09-28), price returns, phase 0:")
    print(IC_HDR)
    print(fmt_ic("  17 names, deployed-style set (ADV, min_names)", ic_series(z6, fwd(r6, *DEPLOYED_WIN), e6.apply(lambda c: c & en6), D.G0)))
    print(fmt_ic("  17 names, WIDE set (no ADV filter)", ic_series(z6, fwd(r6, *DEPLOYED_WIN), z6.notna(), D.G0)))

    # Part E: the same slope, pooled, under four standard errors
    print("\nPart E -- the pooled slope of demeaned fwd return on demeaned z, DEPLOYED set, "
          "total returns, phase 0 grid:")
    S = D.z.reindex(D.G0)
    F = F_tr.reindex(D.G0)
    ok = D.M_dep.reindex(D.G0, fill_value=False) & S.notna() & F.notna()
    enough = ok.sum(axis=1) >= MIN_NAMES
    ok = ok.apply(lambda col: col & enough)
    s = S.where(ok)
    f = F.where(ok)
    s = s.sub(s.mean(axis=1), axis=0)
    f = f.sub(f.mean(axis=1), axis=0)
    st = s.stack()
    ft = f.stack().reindex(st.index)
    b = (st * ft).sum() / (st ** 2).sum()
    e = ft - b * st
    sxx = (st ** 2).sum()
    g_date = (st * e).groupby(level=0).sum()
    g_name = (st * e).groupby(level=1).sum()
    Gd, Gn = g_date.size, g_name.size
    # Small-sample corrections (review 2026-10-11). Within-date demeaning absorbs one
    # mean per date, so the iid residual dof is n - 1 - dates. Cluster variances
    # carry G/(G-1); with 12 name clusters the right reference is t(G-1), not the
    # normal, so its 5% critical value is printed beside the t.
    v_iid = (e ** 2).sum() / (len(e) - 1 - Gd) / sxx
    v_date = Gd / (Gd - 1) * (g_date ** 2).sum() / sxx ** 2
    v_name = Gn / (Gn - 1) * (g_name ** 2).sum() / sxx ** 2
    v_het = ((st * e) ** 2).sum() / sxx ** 2
    G2 = min(Gd, Gn)
    v_two = G2 / (G2 - 1) * ((g_date ** 2).sum() + (g_name ** 2).sum()
                             - ((st * e) ** 2).sum()) / sxx ** 2
    from scipy import stats as _st
    print(f"  obs {len(st)}, dates {Gd}, names {Gn}; slope {b * 1e4:+.2f} bp of "
          f"2-day return per unit z")
    for lab, v, df in (("naive iid (dof n-1-dates)", v_iid, len(e) - 1 - Gd),
                       ("clustered by date", v_date, Gd - 1),
                       ("clustered by name", v_name, Gn - 1),
                       ("two-way date x name", v_two, G2 - 1)):
        print(f"  t {lab:<28}{b / np.sqrt(v):8.2f}   5% two-sided critical value "
              f"t({df}) {_st.t.ppf(0.975, df):.2f}")
    tb, lo, hi = block_boot_t(ic0)
    print(f"  mean IC {ic0.mean():+.4f}: date-clustered t {ic_row(ic0)['t']:.2f}, NW({NW_LAGS}) t "
          f"{nw_t(ic0):.2f}, block bootstrap (block {BOOT_BLOCK}, {BOOT_REPS} reps) t {tb:.2f}, "
          f"95% [{lo:+.4f}, {hi:+.4f}]")
    return rows


def sec_total_return(D: Data):
    """1. The total-return panel: source, completeness against CRSP, and what it moves."""
    print("\n" + "=" * 100 + "\n1. TOTAL-RETURN PANEL\n" + "=" * 100)
    U = D.U
    # --- completeness: panel ex-dates vs CRSP's own distribution days
    c = D.crsp()
    c = c[c.ticker.isin(U)]
    ret, retx = _pivot(c, "ret", U, D.idx), _pivot(c, "retx", U, D.idx)
    crsp_dy = (ret - retx)                       # CRSP's distribution component on ex-dates
    crsp_ex = crsp_dy.abs() > 1e-6
    pan_ex = D.ex
    inwin = D.px.notna() & ret.notna()
    print("ex-dates 2005-01-03..2022-12-30 on name-days both sources price:")
    print(f"{'ticker':<7}{'panel':>7}{'CRSP':>7}{'both':>7}{'panel only':>11}{'CRSP only':>10}"
          f"{'med |y_pan-y_crsp| bp':>23}")
    tot = np.zeros(5)
    only_rows = []
    for t in U:
        a, b, w = pan_ex[t] & inwin[t], crsp_ex[t] & inwin[t], inwin[t]
        both = a & b
        ypan = D.y_px[t][both]
        ycr = crsp_dy[t][both]
        dd = (ypan - ycr).abs() * 1e4
        print(f"{t:<7}{a.sum():7d}{b.sum():7d}{both.sum():7d}{(a & ~b).sum():11d}{(b & ~a).sum():10d}"
              f"{dd.median():23.2f}")
        tot += [a.sum(), b.sum(), both.sum(), (a & ~b).sum(), (b & ~a).sum()]
        for d in a[a & ~b].index:
            only_rows.append((t, d.date(), "panel only", float(D.y_px.at[d, t] * 1e4),
                              float(D.r_tr.at[d, t] * 1e4), float(ret.at[d, t] * 1e4)))
        for d in b[b & ~a].index:
            only_rows.append((t, d.date(), "CRSP only", float(crsp_dy.at[d, t] * 1e4),
                              float(D.r_tr.at[d, t] * 1e4), float(ret.at[d, t] * 1e4)))
    print(f"{'ALL':<7}" + "".join(f"{int(x):7d}" if i < 3 else f"{int(x):11d}" if i == 3 else f"{int(x):10d}"
                                   for i, x in enumerate(tot)))
    if only_rows:
        o = pd.DataFrame(only_rows, columns=["ticker", "date", "which", "yield_bp",
                                             "panel_total_ret_bp", "crsp_ret_bp"])
        o["total_ret_agrees"] = (o.panel_total_ret_bp - o.crsp_ret_bp).abs() < 5
        print("unmatched ex-dates (yield bp on the source that has it). total_ret_agrees: the "
              "panel's TOTAL return equals CRSP `ret` within 5bp -- the two agree on the cash, and "
              "the mismatch is only CRSP's retx convention (it books capital-gain specials inside "
              "retx). Where it is False the panel is missing a distribution, or has one CRSP lacks:")
        print(o.to_string(index=False, float_format=lambda v: f"{v:9.1f}"))
    # --- the total return series vs CRSP ret, day by day
    diff = (D.r_tr - ret).where(inwin) * 1e4
    print(f"\ndaily |r_total(panel) - ret(CRSP)| over {int(inwin.sum().sum())} name-days: "
          f"median {diff.abs().stack().median():.3f}bp, p99 {diff.abs().stack().quantile(.99):.2f}bp, "
          f"share > 5bp {(diff.abs() > 5).sum().sum() / inwin.sum().sum():.4%}")
    exd = diff.where(pan_ex | crsp_ex).abs().stack()
    print(f"  on ex-dates only ({len(exd)}): median {exd.median():.2f}bp, p95 {exd.quantile(.95):.2f}bp")

    # --- the deployed book on three return conventions (harness, fillna(0) as build_targets)
    R_crsp = ret.reindex(D.T.index)[U].where(lambda x: x.abs() < 0.5).fillna(0.0)
    res = pnl_table([("price returns (panel)", D.H, D.R_px),
                     ("TOTAL returns (panel + dists)", D.H, D.R_tr),
                     ("total returns (CRSP ret)", D.H, R_crsp)],
                    f"deployed policy {summary()} -- three return conventions")
    # the distribution leg on its own
    carry = evaluate(D.H, D.R_tr)["pnl"] - evaluate(D.H, D.R_px)["pnl"]
    print("\nthe distribution leg = P&L(total) - P&L(price) on the deployed holdings path:")
    print(f"{'era':<14}{'ann bp/yr':>10}{'sd bp/yr':>10}{'days ex':>9}")
    for lab, a, b in ERAS + [FIT]:
        x = carry.loc[a:b]
        print(f"{lab:<14}{x.mean() * 252 * 1e4:10.1f}{x.std() * np.sqrt(252) * 1e4:10.1f}"
              f"{int((x != 0).sum()):9d}")
    # ex-date discount arithmetic (BRIEF §3 correction): measured coefficient
    dd = D.disc.diff()
    exm = D.ex & dd.notna() & D.disc.shift(1).notna()
    N1 = D.nav.shift(1)
    amt = D.dist.reindex(index=D.idx, columns=U)
    mech = (D.disc.shift(1) / 100) * amt / (N1 - amt) * 100       # pp: d.D/(N-D)
    x = mech[exm].stack()
    y = dd[exm].stack()
    non = dd[~D.ex & dd.notna()].stack()
    b_mech = np.polyfit(x.values, y.values, 1)
    print("\nex-date discount arithmetic: one-day change in discount (pp) on ex-dates")
    print(f"  ex-dates {len(y)}: mean change {y.mean():+.3f}pp vs non-ex {non.mean():+.4f}pp; "
          f"mechanical d*D/(N-D) mean {x.mean():+.3f}pp; slope of change on mechanical term "
          f"{b_mech[0]:+.2f} (1.0 = pure arithmetic), intercept {b_mech[1]:+.3f}pp")
    pdrop = ((D.px.shift(1) - D.px) / amt)[exm].stack()
    ndrop = ((D.nav.shift(1) - D.nav) / amt)[exm].stack()
    print(f"  price drop / distribution: median {pdrop.median():.2f}; NAV drop / distribution: "
          f"median {ndrop.median():.2f} (Bali-Hite: price drop slightly below 1)")
    print("  discount change (pp) around the ex-date, every ex-date of these names 2005-22:")
    for lab, sh in (("ex-1", -1), ("ex", 0), ("ex+1", 1), ("ex+2", 2)):
        m = D.ex.shift(sh, fill_value=False) & dd.notna()
        x = dd[m].stack()
        print(f"    {lab:<5} n {len(x):5d}  mean {x.mean():+.3f}  median {x.median():+.3f}")
    ex1 = D.ex.shift(1, fill_value=False) & dd.notna()
    print(f"  (two-day NAV drop through ex+1) / distribution: median "
          f"{(((D.nav.shift(2) - D.nav) / amt.shift(1))[ex1].stack()).median():.2f}")
    return res


def sec_bounce(D: Data):
    """2. Bid-ask bounce: skip a day, the quote midpoint, the auction print, spreads."""
    print("\n" + "=" * 100 + "\n2. BID-ASK BOUNCE\n" + "=" * 100)
    U = D.U
    print("2a. IC by single forward day k (Spearman z_t vs r_{t+k}, total returns, every "
          "session, NW t); DEPLOYED set. k=1 is the day no book decided at t can earn.")
    print(IC_HDR)
    for k in range(1, 7):
        ic = ic_series(D.z, D.r_tr.shift(-k), D.M_dep, D.idx)
        print(fmt_ic(f"  day t+{k}" + ("  (infeasible: before the fill)" if k == 1 else ""), ic))
    print("\n2b. two-day windows, non-overlapping, DEPLOYED set, total returns:")
    print(IC_HDR)
    for lab, (a, b) in (("[t+1,t+2] infeasible: entry at close t", (1, 2)),
                        ("[t+2,t+3] DEPLOYED: entry close t+1", (2, 3)),
                        ("[t+3,t+4] skip a day: entry close t+2", (3, 4))):
        for ph, G in (("p0", D.G0), ("p1", D.G1)):
            print(fmt_ic(f"  {lab} {ph}", ic_series(D.z, fwd(D.r_tr, a, b), D.M_dep, G)))
    pnl_table([("deployed (shift 2)", D.H, D.R_tr),
               ("skip a day (shift 3)", D.H.shift(1).fillna(0.0), D.R_tr)],
              "2c. P&L: the deployed book vs the same book filled one session later "
              "(evaluate(H.shift(1), R)), TOTAL returns")

    # 2d. quote midpoint from CRSP closing bid/ask
    c = D.crsp()
    c = c[c.ticker.isin(U)]
    bid, ask = _pivot(c, "bid", U, D.idx), _pivot(c, "ask", U, D.idx)
    good = (bid > 0) & (ask > 0) & (ask >= bid)
    mid = ((bid + ask) / 2).where(good)
    # the discount on the midpoint, z-scored EXACTLY as the sleeve does (same window,
    # min_periods, shift(1) moments, clip): only the price input changes
    p = D.p
    nav_full = p["nav"][U]
    mid_full = mid.reindex(nav_full.index)
    dmid = 100.0 * (mid_full - nav_full) / nav_full
    mu = dmid.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = dmid.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    z_mid = ((dmid - mu) / sd.replace(0, np.nan)).clip(-4, 4).reindex(D.idx)
    r_mid = mid.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    y_mid = (D.dist / mid_full.shift(1)).reindex(index=D.idx, columns=U).fillna(0.0)
    r_mid_tr = r_mid + y_mid
    Fc, Fm = fwd(D.r_tr, *DEPLOYED_WIN), fwd(r_mid_tr, *DEPLOYED_WIN)
    both = D.M_dep & z_mid.notna() & Fm.notna() & Fc.notna()
    priced = D.px.notna()
    print(f"\n2d. closing quote MIDPOINT (CRSP bid/ask; a valid quote on "
          f"{(good & priced).sum().sum() / priced.sum().sum():.1%} of the name-days the panel prices, "
          f"2005-22). Same DEPLOYED dates and names in every row (common sample):")
    print(IC_HDR)
    for lab, S, F in (("z(close)  vs fwd close-to-close  [deployed]", D.z, Fc),
                      ("z(close)  vs fwd mid-to-mid", D.z, Fm),
                      ("z(mid)    vs fwd close-to-close", z_mid, Fc),
                      ("z(mid)    vs fwd mid-to-mid  [no bounce]", z_mid, Fm)):
        print(fmt_ic(f"  {lab}", ic_series(S, F, both, D.G0)))
    Fc1, Fm1 = fwd(D.r_tr, 1, 2), fwd(r_mid_tr, 1, 2)
    both1 = D.M_dep & z_mid.notna() & Fm1.notna() & Fc1.notna()
    print("  the INFEASIBLE window [t+1,t+2] (entry at close t, where bounce would live):")
    for lab, S, F in (("z(close)  vs fwd close-to-close", D.z, Fc1),
                      ("z(mid)    vs fwd mid-to-mid  [no bounce]", z_mid, Fm1)):
        print(fmt_ic(f"  {lab}", ic_series(S, F, both1, D.G0)))
    zc = (D.z - z_mid).where(both)
    print(f"  bounce part of the signal, z(close) - z(mid): sd {zc.stack().std():.3f} vs sd of z "
          f"{D.z.where(both).stack().std():.3f}; corr(z(close), z(mid)) "
          f"{np.corrcoef(D.z.where(both).stack(), z_mid.where(both).stack().reindex(D.z.where(both).stack().index))[0, 1]:.3f}")
    print(fmt_ic("  IC of the bounce part alone vs fwd close-to-close", ic_series(zc, Fc, both, D.G0)))
    # wide set, every era: does the midpoint IC hold where spreads were widest?
    bothw = D.M_wide & z_mid.notna() & Fm.notna() & Fc.notna()
    print("  WIDE set by era (context; NOT deployed): z(close) vs close | z(mid) vs mid")
    for lab, a, b in ERAS + [FIT]:
        G = D.G0[(D.G0 >= a) & (D.G0 <= b)]
        r1 = ic_row(ic_series(D.z, Fc, bothw, G))
        r2 = ic_row(ic_series(z_mid, Fm, bothw, G))
        print(f"    {lab:<12} n {r1['n']:5d}  close {r1['ic']:+.4f} (t {r1['t']:6.2f})   mid "
              f"{r2['ic']:+.4f} (t {r2['t']:6.2f})")

    # 2e. spreads by name: CRSP quoted vs Corwin-Schultz, AR(1), and IC vs spread
    hs_q = ((ask - bid) / mid / 2 * 1e4).where(good)
    hs_cs = corwin_schultz_halfspread(p["px"][U].reindex(D.idx), D)
    Fc_dm = Fc.where(D.M_dep)
    zd = D.z.where(D.M_dep)
    zd = zd.sub(zd.mean(axis=1), axis=0)
    Fd = Fc_dm.sub(Fc_dm.mean(axis=1), axis=0)
    rows = []
    for t in U:
        msk = D.M_dep[t].reindex(D.G0, fill_value=False) & zd[t].reindex(D.G0).notna() & Fd[t].reindex(D.G0).notna()
        a, b = zd[t].reindex(D.G0)[msk], Fd[t].reindex(D.G0)[msk]
        ic_t = a.rank().corr(b.rank()) if len(a) > 30 else np.nan
        dep = D.M_dep[t]
        rows.append(dict(ticker=t, grp=D.grp[t], n=int(msk.sum()), ic_name=ic_t,
                         hs_quoted_bp=hs_q[t][dep].median(), hs_cs_bp=hs_cs[t][dep].median(),
                         price=D.px[t][dep].median(),
                         ar1_close=D.r_px[t][dep].autocorr(1), ar1_mid=r_mid[t][dep].autocorr(1),
                         ar1_nav=D.r_nav_tr[t][dep].autocorr(1)))
    T2 = pd.DataFrame(rows)
    print("\n2e. by name, on the DEPLOYED name-days: per-name IC (time-series Spearman of "
          "cross-sectionally demeaned z and fwd return), half-spreads, AR(1) of daily returns")
    print(T2.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    ok = T2.dropna(subset=["ic_name", "hs_quoted_bp"])
    for col in ("hs_quoted_bp", "hs_cs_bp"):
        x, y = ok[col].values, ok["ic_name"].values
        X = np.c_[np.ones_like(x), x]
        beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
        e = y - X @ beta
        se = np.sqrt(e @ e / (len(y) - 2) * np.linalg.inv(X.T @ X)[1, 1])
        print(f"  cross-section of {len(y)} names: IC_name = a + b*{col}: b {beta[1]:+.4f} per bp "
              f"(t {beta[1] / se:+.2f}); bounce predicts b < 0 (more negative IC where spreads are wide)")
    print(f"  corr(quoted, Corwin-Schultz) half-spread across names: "
          f"{ok['hs_quoted_bp'].corr(ok['hs_cs_bp']):.2f}")

    # 2f. the closing-auction print (Alpaca SIP, 2016-22)
    sec_auction(D, Fc)
    return T2


def corwin_schultz_halfspread(px_close, D) -> pd.DataFrame:
    """Corwin & Schultz (2012, J. Finance 67(2)) two-day high-low spread estimator.

    S = 2(e^a - 1)/(1 + e^a), a = (sqrt(2b) - sqrt(b))/(3 - 2 sqrt 2) - sqrt(g/(3 - 2 sqrt 2)),
    b = sum over the two days of ln(H/L)^2, g = ln(max H / min L)^2 over both days.
    The paper sets negative two-day estimates to zero; that is the estimator's
    definition, applied here as published, and it is the only adjustment.
    Returned as a HALF-spread in bp, on the date of the second day."""
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    P = P[P.ticker.isin(D.U) & (P.date < HOLDOUT_START)]
    hi = P.pivot_table(index="date", columns="ticker", values="high").reindex(index=D.idx, columns=D.U)
    lo = P.pivot_table(index="date", columns="ticker", values="low").reindex(index=D.idx, columns=D.U)
    ok = (hi > 0) & (lo > 0) & (hi >= lo)
    hi, lo = hi.where(ok), lo.where(ok)
    beta = np.log(hi / lo) ** 2 + (np.log(hi / lo) ** 2).shift(1)
    H2 = np.maximum(hi, hi.shift(1))
    L2 = np.minimum(lo, lo.shift(1))
    gamma = np.log(H2 / L2) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    S = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return (S.clip(lower=0) / 2) * 1e4


def sec_auction(D: Data, Fc):
    path = _need(CACHE / "alpaca_closing_prints_2016_2022.parquet",
                 "scripts/data/fetch_alpaca_auction_history.py")
    a = pd.read_parquet(path)
    _assert_fit(a.set_index("date"))
    U = D.U
    # The PRIMARY listing's print (all 13 are NYSE-listed, exchange code "N"
    # [V: docs/REFERENCES.md section 8]); condition "M" (official close) where
    # NYSE published one, else "6" (closing trade) -- the two never disagree
    # where both exist (checked below and raised if they do).
    n = a[a.exchange == "N"]
    piv = n.pivot_table(index=["date", "ticker"], columns="condition", values="price", aggfunc="first")
    if {"6", "M"} <= set(piv.columns):
        both = piv["6"].notna() & piv["M"].notna()
        if ((piv["6"] - piv["M"]).abs()[both] > 0.005).any():
            raise ValueError("NYSE condition-6 and condition-M closing prints disagree; "
                             "decide which is the auction price before using either")
    auc = piv["M"].combine_first(piv["6"]).unstack().reindex(index=D.idx, columns=U)
    win = D.idx >= pd.Timestamp("2016-01-04")
    have = auc.notna() & D.px.notna()
    have.loc[~win] = False
    agree = ((D.px - auc).abs() <= 0.005) & have
    print(f"\n2f. CLOSING-AUCTION print (Alpaca SIP, NYSE, 2016-01-04..2022-12-30): a print exists "
          f"on {have[win].sum().sum() / D.px[win].notna().sum().sum():.1%} of panel name-days; the "
          f"panel close equals it (|diff| <= $0.005) on {agree.sum().sum() / have.sum().sum():.2%} of them")
    dev = ((D.px / auc - 1).abs() * 1e4)[have & ~agree].stack()
    print(f"  where they differ ({len(dev)} name-days): median {dev.median():.1f}bp, max {dev.max():.1f}bp")
    cov = (have[win].sum(axis=1).groupby(D.idx[win].year).sum()
           / D.px[win].notna().sum(axis=1).groupby(D.idx[win].year).sum())
    print("  print coverage by year (share of panel name-days):")
    print(cov.round(2).to_string())
    # IC on the auction price, on the common sample where every input exists
    nav_full = D.p["nav"][U]
    auc_full = auc.reindex(nav_full.index)
    dA = 100.0 * (auc_full - nav_full) / nav_full
    mu = dA.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = dA.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    zA = ((dA - mu) / sd.replace(0, np.nan)).clip(-4, 4).reindex(D.idx)
    rA = auc.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    yA = (D.dist / auc_full.shift(1)).reindex(index=D.idx, columns=U).fillna(0.0)
    FA = fwd(rA + yA, *DEPLOYED_WIN)
    common = D.M_dep & zA.notna() & FA.notna() & Fc.notna()
    print("  IC on the common sample (DEPLOYED dates/names where an auction print exists on every "
          "day the row needs; z on the auction price needs 120 prior prints, so it starts mid-2016):")
    print("  " + IC_HDR)
    for lab, S, F in (("z(close)   vs fwd close    [deployed]", D.z, Fc),
                      ("z(auction) vs fwd auction  [auction only]", zA, FA)):
        for ph, G in (("p0", D.G0), ("p1", D.G1)):
            print("  " + fmt_ic(f"{lab} {ph}", ic_series(S, F, common, G)))


def sec_stale_nav(D: Data):
    """3. Stale-NAV catch-up: autocorrelation, lead-lag, and the split of discount reversion."""
    print("\n" + "=" * 100 + "\n3. STALE-NAV CATCH-UP\n" + "=" * 100)
    U = D.U
    # 3a. autocorrelation of NAV and price total returns, by name and group (fit period)
    rows = []
    for t in U:
        nv, pr = D.r_nav_tr[t].dropna(), D.r_tr[t].dropna()
        rows.append(dict(ticker=t, grp=D.grp[t], n=len(nv),
                         nav_ac1=nv.autocorr(1), nav_ac2=nv.autocorr(2), nav_ac3=nv.autocorr(3),
                         px_ac1=pr.autocorr(1), px_ac2=pr.autocorr(2),
                         nav_zero_share=float((D.nav[t].diff() == 0)[D.nav[t].notna()].mean())))
    A = pd.DataFrame(rows)
    print("3a. autocorrelation of daily NAV total returns (and price total returns), 2005-01..2022-12; "
          "nav_zero_share = sessions on which the NAV did not change")
    print(A.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))
    # group means with a block bootstrap over dates
    rng = np.random.default_rng(SEED)
    X = D.r_nav_tr
    n = len(X)
    print("  group mean NAV AC(1) with moving-block bootstrap 95% CI (block 20 sessions, 500 reps):")
    for g in ("muni", "loan", "multi", "hy"):
        names = [t for t in U if D.grp[t] == g]
        est = np.mean([X[t].autocorr(1) for t in names])
        boots = []
        nb = int(np.ceil(n / BOOT_BLOCK))
        for _ in range(500):
            st = rng.integers(0, n - BOOT_BLOCK, nb)
            ix = (st[:, None] + np.arange(BOOT_BLOCK)).ravel()[:n]
            Xb = X.iloc[ix].reset_index(drop=True)
            boots.append(np.mean([Xb[t].autocorr(1) for t in names]))
        lo, hi = np.percentile(boots, [2.5, 97.5])
        print(f"    {g:<6} ({', '.join(names)}): {est:+.3f}  [{lo:+.3f}, {hi:+.3f}]")

    # 3b. lead-lag on live-priced proxies (CRSP total returns)
    c = D.crsp()
    prox = sorted({x for v in PROXY_OF.values() for x in v})
    P = _pivot(c, "ret", prox, D.idx).where(lambda x: x.abs() < 0.5)
    import statsmodels.api as sm
    print(f"\n3b. lead-lag: NAV total return_t on proxy total returns at t, t-1 .. t-{LEADLAG_K} "
          f"(CRSP; muni MUB, hy HYG, loan BKLN, multi HYG+LQD), HAC({NW_LAGS}); 2005-22 where both exist")
    ll = []
    for t in U:
        cols = PROXY_OF[D.grp[t]]
        Xl = pd.concat({f"{x}_L{k}": P[x].shift(k) for x in cols for k in range(LEADLAG_K + 1)}, axis=1)
        dfm = pd.concat([D.r_nav_tr[t].rename("y"), Xl], axis=1).dropna()
        if len(dfm) < 250:
            ll.append(dict(ticker=t, grp=D.grp[t], n=len(dfm)))
            continue
        fit = sm.OLS(dfm["y"], sm.add_constant(dfm.drop(columns="y"))).fit(
            cov_type="HAC", cov_kwds={"maxlags": NW_LAGS})
        b0 = sum(fit.params[f"{x}_L0"] for x in cols)
        blag = sum(fit.params[f"{x}_L{k}"] for x in cols for k in range(1, LEADLAG_K + 1))
        # t of the lag sum
        Lnames = [f"{x}_L{k}" for x in cols for k in range(1, LEADLAG_K + 1)]
        w = np.array([1.0 if nm in Lnames else 0.0 for nm in fit.params.index])
        tl = blag / np.sqrt(w @ fit.cov_params().values @ w)
        ll.append(dict(ticker=t, grp=D.grp[t], n=len(dfm), proxy="+".join(cols), b_contemp=b0,
                       b_lags_sum=blag, t_lags=tl, stale_share=blag / (b0 + blag) if (b0 + blag) else np.nan,
                       r2=fit.rsquared))
    L = pd.DataFrame(ll)
    print(L.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))
    print("  stale_share = lag-sum / (contemporaneous + lag-sum): the fraction of a proxy move that "
          "reaches the NAV only on later days. Group means:")
    print(L.groupby("grp")[["b_contemp", "b_lags_sum", "stale_share"]].mean().round(3).to_string())

    # 3c. the forward discount change, split into price and NAV, per unit z
    print("\n3c. forward discount change per unit z, split into its PRICE and NAV legs "
          "(log total returns; Fama-MacBeth slope on cross-sectionally demeaned z, DEPLOYED set; "
          "bp; discount = price - NAV exactly)")
    print(f"{'window':<34}{'price':>9}{'t':>7}{'NAV':>9}{'t':>7}{'discount':>10}{'t':>7}"
          f"{'price share':>12}")
    out3c = {}
    for lab, (a, b), G in (("t+1 only (unearned day)", (1, 1), D.idx),
                           ("[t+2,t+3] DEPLOYED window", (2, 3), D.G0),
                           ("[t+2,t+6]", (2, 6), D.idx[::5]),
                           ("[t+2,t+11]", (2, 11), D.idx[::10]),
                           ("[t+2,t+22]", (2, 22), D.idx[::21])):
        Fp, Fn = fwd_log(D.r_tr, a, b), fwd_log(D.r_nav_tr, a, b)
        Fd = Fp - Fn
        comm = D.M_dep & Fp.notna() & Fn.notna()
        sp, sn, sd_ = (fm_slopes(D.z, F, comm, G) * 1e4 for F in (Fp, Fn, Fd))
        tt = lambda s: s.mean() / s.std() * np.sqrt(len(s)) if len(s) > 10 else np.nan
        print(f"{lab:<34}{sp.mean():9.2f}{tt(sp):7.2f}{sn.mean():9.2f}{tt(sn):7.2f}{sd_.mean():10.2f}"
              f"{tt(sd_):7.2f}{sp.mean() / sd_.mean():12.2f}")
        out3c[lab] = (sp.mean(), sn.mean(), sd_.mean())
    Fn23 = fwd(D.r_nav_tr, 2, 3)
    print(IC_HDR)
    print(fmt_ic("  IC of z vs fwd NAV return [t+2,t+3] (catch-up > 0)", ic_series(D.z, Fn23, D.M_dep, D.G0)))
    print(fmt_ic("  IC of z vs fwd NAV return t+1 (catch-up > 0)", ic_series(D.z, D.r_nav_tr.shift(-1), D.M_dep, D.idx)))

    # 3d. the decisive split: the stale part of z vs the rest
    stale_z = stale_component_z(D, P)
    Fc = fwd(D.r_tr, *DEPLOYED_WIN)
    comm = D.M_dep & stale_z.notna() & Fc.notna()
    zd = D.z - stale_z
    print(f"\n3d. the stale part of the signal. From the lead-lag model refitted each January on data "
          f"strictly before it (expanding, >= 250 sessions), the NAV catch-up still pending at t "
          f"is c_t = sum_j sum_(k>=j) b_k x_(t+j-k); a NAV that low makes the discount read +100 c_t P/N too high, in z "
          f"units divided by the sleeve's own sd_t. z = stale part + residual. Common sample "
          f"{int(comm.sum().sum())} name-days ({int(comm.reindex(D.G0, fill_value=False).sum().sum())} on the grid):")
    print("  " + IC_HDR)
    for lab, S in (("z (deployed)", D.z), ("stale part of z", stale_z), ("z minus its stale part", zd)):
        for ph, G in (("p0", D.G0), ("p1", D.G1)):
            print("  " + fmt_ic(f"{lab} {ph}", ic_series(S, Fc, comm, G)))
    sz = stale_z.where(comm).stack()
    print(f"  sd of the stale part {sz.std():.3f} z vs sd of z {D.z.where(comm).stack().std():.3f}; "
          f"corr {np.corrcoef(sz, D.z.where(comm).stack().reindex(sz.index))[0, 1]:+.3f}")
    print(f"  Fama-MacBeth, both regressors (bp per unit, [t+2,t+3]): ", end="")
    fmz, fms = fm_two(D.z, stale_z, Fc, comm, D.G0)
    print(f"z {fmz.mean() * 1e4:+.2f} (t {fmz.mean() / fmz.std() * np.sqrt(len(fmz)):.2f}), "
          f"stale {fms.mean() * 1e4:+.2f} (t {fms.mean() / fms.std() * np.sqrt(len(fms)):.2f})")
    # The size of the stale part is a LOWER BOUND: lags stop at K=3 while NAV AC(3) is
    # still 0.15-0.36 for most names (3a), and it covers only the staleness the proxies
    # explain. A longer-lag sensitivity, reported, nothing chosen from it:
    K2 = 10
    sz10 = stale_component_z(D, P, K=K2)
    c10 = D.M_dep & sz10.notna() & Fc.notna()
    s10 = sz10.where(c10).stack()
    print(f"  sensitivity, lags 0..{K2}: sd of the stale part {s10.std():.3f} z; common sample "
          f"{int(c10.reindex(D.G0, fill_value=False).sum().sum())} grid name-days")
    for lab, S in (("z (deployed)", D.z), (f"stale part of z, K={K2}", sz10),
                   (f"z minus its stale part, K={K2}", D.z - sz10)):
        print("  " + fmt_ic(f"{lab} p0", ic_series(S, Fc, c10, D.G0)))

    # 3e. bond-market holidays
    sec_bond_holidays(D)
    return A, L, out3c


def stale_component_z(D: Data, P: pd.DataFrame, K: int = LEADLAG_K) -> pd.DataFrame:
    """The part of z that a stale NAV fakes, estimated without lookahead.

    For each name, regress its NAV total return on its group proxies at lags
    0..K using ONLY data before 1 January of year Y (expanding window, at least
    250 sessions), and apply the coefficients through year Y. The NAV move still
    owed at t, given proxy moves already observed through t, is
        c_t = sum_{j=1..K} sum_{k=j..K} b_k x_{t+j-k}
    (lags k >= j of a move at t+j-k fall after t). A NAV marked c_t too low
    makes the discount read 100*c_t*P/N too high; dividing by the sleeve's
    own sd_t (shifted, H7) puts it in z units. NaN where no fit exists yet --
    never filled."""
    import statsmodels.api as sm
    U = D.U
    out = pd.DataFrame(np.nan, index=D.idx, columns=U)
    years = sorted(set(D.idx.year))
    for t in U:
        cols = PROXY_OF[D.grp[t]]
        Xl = pd.concat({f"{x}_L{k}": P[x].shift(k) for x in cols for k in range(K + 1)}, axis=1)
        dfm = pd.concat([D.r_nav_tr[t].rename("y"), Xl], axis=1)
        for Y in years:
            start = pd.Timestamp(f"{Y}-01-01")
            train = dfm[dfm.index < start].dropna()
            if len(train) < 250:
                continue
            assert train.index.max() < start          # H7: fit strictly before the year it is used in
            fit = sm.OLS(train["y"], sm.add_constant(train.drop(columns="y"))).fit()
            yr = (D.idx >= start) & (D.idx < pd.Timestamp(f"{Y + 1}-01-01"))
            c = pd.Series(0.0, index=D.idx)
            for x in cols:
                for j in range(1, K + 1):
                    for k in range(j, K + 1):
                        # x_{t+j-k} = P[x].shift(k-j) at row t: known at t since k >= j
                        c = c + fit.params[f"{x}_L{k}"] * P[x].shift(k - j)
            out.loc[yr, t] = c[yr]
    fake_pp = 100.0 * out * (D.px / D.nav)
    return fake_pp / D.sd.replace(0, np.nan)


def fm_two(S1, S2, F, M, dates):
    b1, b2 = [], []
    for d in dates:
        if d not in M.index:
            continue
        m = M.loc[d]
        if m.sum() < MIN_NAMES:
            continue
        y = F.loc[d][m]
        X = np.c_[np.ones(m.sum()), S1.loc[d][m].values, S2.loc[d][m].values]
        beta, *_ = np.linalg.lstsq(X, y.values, rcond=None)
        b1.append(beta[1])
        b2.append(beta[2])
    return pd.Series(b1), pd.Series(b2)


def bond_holidays(idx) -> list:
    """SIFMA full-close days on which the NYSE trades: Columbus Day (second Monday of
    October) and Veterans Day (11 November when a weekday; Monday 12 November when
    the 11th is a Sunday; nothing when it is a Saturday). The
    recommendation is SIFMA's [S: docs/BRIEF.md section 3]; the panel decides
    whether the NAV actually stood still (reported, not assumed)."""
    out = []
    for y in sorted(set(idx.year)):
        mons = [d for d in pd.date_range(f"{y}-10-01", periods=14) if d.weekday() == 0]
        vet = pd.Timestamp(f"{y}-11-11")
        if vet.weekday() == 6:                 # Sunday: observed Monday 12 November
            vet = vet + pd.Timedelta(days=1)   # (review 2026-10-11: 2007, 2012, 2018)
        for d in (mons[1], vet):
            if d.weekday() < 5 and d in idx:
                out.append(d)
    return out


def sec_bond_holidays(D: Data):
    bh = bond_holidays(D.idx)
    dd = D.disc.diff()
    nav_unch = (D.nav.diff() == 0)
    nxt = [D.idx[D.idx.get_loc(d) + 1] for d in bh if D.idx.get_loc(d) + 1 < len(D.idx)]
    other = D.idx.difference(bh)
    print(f"\n3e. bond-market holidays (Columbus, Veterans; NYSE open): {len(bh)} in 2005-22")
    print(f"  NAV unchanged on {nav_unch.loc[bh].sum().sum() / D.nav.loc[bh].notna().sum().sum():.1%} "
          f"of name-days on those days vs {nav_unch.loc[other].sum().sum() / D.nav.loc[other].notna().sum().sum():.1%} "
          f"on other days")
    print(f"  mean |discount change| {dd.loc[bh].abs().stack().mean():.3f}pp vs {dd.loc[other].abs().stack().mean():.3f}pp; "
          f"corr(change on the holiday, change next session) "
          f"{np.corrcoef(dd.loc[bh].stack(), dd.shift(-1).loc[bh].stack().reindex(dd.loc[bh].stack().index))[0, 1]:+.3f}")
    Fc = fwd(D.r_tr, *DEPLOYED_WIN)
    M_x = D.M_dep.copy()
    M_x.loc[bh] = False
    M_x.loc[nxt] = False
    print("  " + IC_HDR)
    print("  " + fmt_ic("DEPLOYED, all signal dates", ic_series(D.z, Fc, D.M_dep, D.idx)))
    print("  " + fmt_ic("DEPLOYED, holiday + next session dropped", ic_series(D.z, Fc, M_x, D.idx)))
    print("  (every-session grid here, so the t's above overlap; NW t is the one to read)")


def sec_where(D: Data):
    """4. Where the IC lives: ex-dates, crises, turn of year, volatility, by group."""
    print("\n" + "=" * 100 + "\n4. WHERE THE IC LIVES\n" + "=" * 100)
    Fc = fwd(D.r_tr, *DEPLOYED_WIN)
    Fp = fwd(D.r_px, *DEPLOYED_WIN)
    # name-dates touched by an ex-date anywhere in [t, t+3]
    exw = D.ex.copy()
    for k in range(1, 4):
        exw = exw | D.ex.shift(-k, fill_value=False)
    print("4a. ex-dates. 'touched' = an ex-date for that name on t..t+3 (signal day, unearned day, "
          f"or the forward window): {exw.where(D.M_dep).stack().mean():.1%} of deployed name-days")
    print(IC_HDR)
    for setlab, M in (("DEPLOYED", D.M_dep), ("WIDE (context)", D.M_wide)):
        print(fmt_ic(f"  {setlab} all name-days, total ret", ic_series(D.z, Fc, M, D.G0)))
        print(fmt_ic(f"  {setlab} all name-days, PRICE ret", ic_series(D.z, Fp, M, D.G0)))
        print(fmt_ic(f"  {setlab} untouched name-days only, total", ic_series(D.z, Fc, M & ~exw, D.G0, min_n=4)))
        print(fmt_ic(f"  {setlab} untouched name-days only, PRICE", ic_series(D.z, Fp, M & ~exw, D.G0, min_n=4)))
    print("  (untouched-only rows need >= 4 names, not min_names, because removing touched names "
          "thins the cross-section; read the slope table below for the like-for-like split)")
    print("  Fama-MacBeth slope (bp per unit z, [t+2,t+3] total return) on touched vs untouched "
          "name-days, demeaned against the full deployed cross-section, by group:")
    zd = D.z.where(D.M_dep)
    zd = zd.sub(zd.mean(axis=1), axis=0)
    fd = Fc.where(D.M_dep)
    fd = fd.sub(fd.mean(axis=1), axis=0)
    print(f"  {'group':<8}{'touched':>10}{'t':>7}{'untouched':>11}{'t':>7}")
    for g in ("ALL", "muni", "hy", "loan", "multi"):
        cols = D.U if g == "ALL" else [t for t in D.U if D.grp[t] == g]
        res = []
        for msk in (exw, ~exw):
            m = msk[cols].reindex(D.G0, fill_value=False) & zd[cols].reindex(D.G0).notna() & fd[cols].reindex(D.G0).notna()
            s, f = zd[cols].reindex(D.G0).where(m), fd[cols].reindex(D.G0).where(m)
            # pooled slope with date-clustered SE
            st, ft = s.stack(), f.stack()
            ft = ft.reindex(st.index)
            b = (st * ft).sum() / (st ** 2).sum()
            e = ft - b * st
            v = ((st * e).groupby(level=0).sum() ** 2).sum() / (st ** 2).sum() ** 2
            res += [b * 1e4, b / np.sqrt(v)]
        print(f"  {g:<8}{res[0]:10.2f}{res[1]:7.2f}{res[2]:11.2f}{res[3]:7.2f}")

    # special distributions: D/P_{t-1} > 2% on the ex-date (year-end capital-gain specials;
    # a regular monthly payment is ~0.4-1.2%). Around one the discount jumps by
    # d*D/(N-D) mechanically, so a z-score there is partly arithmetic.
    spec = D.y_px > 0.02
    print(f"\n  special distributions (D/P > 2% on the ex-date): {int(spec.sum().sum())} in 2005-22 on "
          f"these names. IC with name-days from 3 sessions before to W after one removed "
          f"(W = 5 / 10 / 21: a sensitivity, nothing is chosen from it):")
    print(IC_HDR + f"{'Dec-Jan':>9}{'n':>5}{'Feb-Nov':>9}")
    pre = spec | spec.shift(-1, fill_value=False) | spec.shift(-2, fill_value=False) | spec.shift(-3, fill_value=False)
    for W in (5, 10, 21):
        post = spec.copy()
        for k in range(1, W + 1):
            post = post | spec.shift(k, fill_value=False)
        excl = pre | post
        for setlab, M in (("DEPLOYED", D.M_dep), ("WIDE (context)", D.M_wide)):
            ic = ic_series(D.z, Fc, M & ~excl, D.G0, min_n=4)
            toy = ic.index.month.isin([12, 1])
            print(fmt_ic(f"  {setlab} ex specials [-3,+{W}] "
                         f"({excl.where(M).stack().mean():.1%} out)", ic,
                         f"{ic[toy].mean():+9.4f}{int(toy.sum()):5d}{ic[~toy].mean():+9.4f}"))

    print("\n4b. crisis windows (signal date inside / outside), total returns:")
    print(IC_HDR)
    for setlab, M in (("DEPLOYED", D.M_dep), ("WIDE (context)", D.M_wide)):
        ic = ic_series(D.z, Fc, M, D.G0)
        print(fmt_ic(f"  {setlab} all", ic))
        allin = pd.Series(False, index=ic.index)
        for lab, (a, b) in CRISES.items():
            inside = (ic.index >= a) & (ic.index <= b)
            allin |= inside
            r = ic_row(ic[inside]) if inside.sum() >= 1 else None
            n_in = int(inside.sum())
            mean_in = ic[inside].mean() if n_in else np.nan
            print(f"  {setlab + ' inside ' + lab:<46}{n_in:6d}{mean_in:+9.4f}")
        print(fmt_ic(f"  {setlab} OUTSIDE every crisis window", ic[~allin.values]))
    print("\n4c. turn of year (signal dated December or January) vs the rest, total returns:")
    print(IC_HDR)
    for setlab, M in (("DEPLOYED", D.M_dep), ("WIDE (context)", D.M_wide)):
        ic = ic_series(D.z, Fc, M, D.G0)
        toy = ic.index.month.isin([12, 1])
        print(fmt_ic(f"  {setlab} Dec-Jan", ic[toy]))
        print(fmt_ic(f"  {setlab} Feb-Nov", ic[~toy]))
    print("  by group, Fama-MacBeth-style pooled slope (bp/unit z), DEPLOYED, date-clustered t:")
    print(f"  {'group':<8}{'Dec-Jan':>10}{'t':>7}{'Feb-Nov':>10}{'t':>7}")
    toy_mask = pd.DataFrame(np.repeat(D.idx.month.isin([12, 1])[:, None], len(D.U), axis=1),
                            index=D.idx, columns=D.U)
    for g in ("ALL", "muni", "hy", "loan", "multi"):
        cols = D.U if g == "ALL" else [t for t in D.U if D.grp[t] == g]
        res = []
        for msk in (toy_mask, ~toy_mask):
            m = msk[cols].reindex(D.G0) & zd[cols].reindex(D.G0).notna() & fd[cols].reindex(D.G0).notna()
            st, ft = zd[cols].reindex(D.G0).where(m).stack(), fd[cols].reindex(D.G0).where(m).stack()
            ft = ft.reindex(st.index)
            b = (st * ft).sum() / (st ** 2).sum()
            e = ft - b * st
            v = ((st * e).groupby(level=0).sum() ** 2).sum() / (st ** 2).sum() ** 2
            res += [b * 1e4, b / np.sqrt(v)]
        print(f"  {g:<8}{res[0]:10.2f}{res[1]:7.2f}{res[2]:10.2f}{res[3]:7.2f}")

    print("\n4d. by volatility state: quintile of the trailing 63-session realised vol of the "
          "equal-weight 13-name total-return index, known at t (breakpoints over the dates shown):")
    ew = D.r_tr.mean(axis=1)
    rv = ew.rolling(63, min_periods=40).std().shift(0) * np.sqrt(252)   # through t: known at t's close
    print(IC_HDR + f"{'rv%':>7}")
    for setlab, M in (("DEPLOYED", D.M_dep), ("WIDE (context)", D.M_wide)):
        ic = ic_series(D.z, Fc, M, D.G0)
        q = pd.qcut(rv.reindex(ic.index), 5, labels=False)
        for k in range(5):
            s = ic[q == k]
            print(fmt_ic(f"  {setlab} vol quintile {k + 1}", s, f"{rv.reindex(s.index).mean() * 100:7.1f}"))
    print("\n4e. by era: section 0.")


def sec_pnl_split(D: Data):
    """5. The deployed P&L, split into the NAV leg and the discount-closure leg."""
    print("\n" + "=" * 100 + "\n5. P&L SPLIT: NAV LEG + DISCOUNT LEG\n" + "=" * 100)
    R_tr, R_nav = D.R_tr, D.R_nav_tr
    R_disc = R_tr - R_nav
    print("price total return = NAV total return + (price TR - NAV TR). The first is what the "
          "book's long-short FUND PORTFOLIOS earned at NAV; the second is the discount closing "
          "(or widening) in price. They add exactly; costs belong to the total and are shown on "
          "its row only.")
    res = pnl_table([("TOTAL (price total return)", D.H, R_tr),
                     ("  NAV leg", D.H, R_nav),
                     ("  discount leg", D.H, R_disc)],
                    "deployed policy, TOTAL returns (cost-grid columns on the leg rows are "
                    "arithmetic only: costs are not split between legs)")
    pt, pn, pd_ = (evaluate(D.H, R)["pnl"] for R in (R_tr, R_nav, R_disc))
    assert np.allclose(pt, pn + pd_), "legs do not add up to the total"
    live = pt.index[pt.ne(0).cumsum() > 0]
    print(f"\nlegs add to the total exactly (max |diff| {(pt - pn - pd_).abs().max():.2e}); "
          f"corr(NAV leg, discount leg) on book-live days {pn.loc[live].corr(pd_.loc[live]):+.3f}")
    print("share of the total's annual return, by era:")
    for lab, a, b in ERAS + [FIT]:
        T_ = pt.loc[a:b].mean()
        if T_ == 0:
            continue
        print(f"  {lab:<12} NAV leg {pn.loc[a:b].mean() / T_:+6.2f}   discount leg {pd_.loc[a:b].mean() / T_:+6.2f}")
    # by group of the position
    print("\nby group (each group's names only, same book), ann % / gross SR, fit period:")
    for g in ("muni", "hy", "loan", "multi"):
        cols = [t for t in D.U if D.grp[t] == g]
        Hg = D.H.copy()
        Hg[[t for t in D.U if t not in cols]] = 0.0
        x = [evaluate(Hg, R)["pnl"] for R in (R_tr, R_nav, R_disc)]
        print(f"  {g:<6} total {x[0].mean() * 252 * 100:+6.2f}%  NAV leg {x[1].mean() * 252 * 100:+6.2f}%  "
              f"discount leg {x[2].mean() * 252 * 100:+6.2f}%")
    return res


def sec_factors(D: Data):
    """6. Factor attribution: FF5 + UMD daily; FF5 + UMD + PS traded liquidity monthly."""
    import statsmodels.api as sm
    print("\n" + "=" * 100 + "\n6. FACTOR ATTRIBUTION\n" + "=" * 100)
    ff = pd.read_parquet(_need(CACHE / "ff5_umd_daily.parquet", "scripts/data/fetch_ff_factors.py"))
    ffm = pd.read_parquet(_need(CACHE / "ff5_umd_monthly.parquet", "scripts/data/fetch_ff_factors.py"))
    ps = pd.read_parquet(_need(CACHE / "ps_liquidity_monthly.parquet", "scripts/data/fetch_pastor_liquidity.py"))
    print(f"factors: Ken French library, CRSP vintage {ff.crsp_vintage.iloc[0]}, daily last "
          f"{ff.date.max().date()}, fetched {ff.fetched_at_utc.iloc[0]}; Pastor-Stambaugh "
          f"{ps.source_url.iloc[0].rsplit('/', 1)[-1]}, last {ps.date.max().date()}, fetched "
          f"{ps.fetched_at_utc.iloc[0]}")
    ff = ff.set_index("date")
    r = evaluate(D.H, D.R_tr)
    pnl, turn = r["pnl"], r["turn_series"]
    live0 = pnl.index[pnl.ne(0)].min()
    print(f"deployed book live from {live0.date()} (first non-zero P&L); regressions start there. "
          f"P&L is a self-financing long-short return; no risk-free rate is subtracted.")
    fac = ["mktrf", "smb", "hml", "rmw", "cma", "umd"]
    # net-of-cost daily P&L: a trade decided at t fills at t+1 (cost charged on t+1)
    nets = {c: pnl - turn.shift(1).fillna(0.0) * c / 1e4 for c in COSTS}
    windows = [("2013-06..2014", live0, "2014-12-31"), ("2015-19", "2015-01-01", "2019-12-31"),
               ("2020-22", "2020-01-01", "2022-12-31"), ("all live 2013-22", live0, "2022-12-31")]

    def reg(y, X, lags):
        d = pd.concat([y.rename("y"), X], axis=1).dropna()
        f = sm.OLS(d["y"], sm.add_constant(d.drop(columns="y"))).fit(cov_type="HAC",
                                                                      cov_kwds={"maxlags": lags})
        return f, len(d)

    print("\n6a. DAILY, gross P&L on FF5 + UMD, HAC(5). alpha in %/yr (x252).")
    print(f"{'window':<18}{'n':>6}{'alpha%':>8}{'t':>7}" + "".join(f"{c:>8}" for c in fac) + f"{'R2':>7}"
          + "".join(f"{'a@' + str(c):>8}{'t':>6}" for c in COSTS))
    for lab, a, b in windows:
        y = pnl.loc[a:b]
        f, n = reg(y, ff[fac].reindex(y.index), NW_LAGS)
        netcols = ""
        for c in COSTS:
            fn, _ = reg(nets[c].loc[a:b], ff[fac].reindex(y.index), NW_LAGS)
            netcols += f"{fn.params['const'] * 252 * 100:8.2f}{fn.tvalues['const']:6.2f}"
        print(f"{lab:<18}{n:6d}{f.params['const'] * 252 * 100:8.2f}{f.tvalues['const']:7.2f}"
              + "".join(f"{f.params[c]:8.3f}" for c in fac) + f"{f.rsquared:7.3f}" + netcols)
    print("  beta t-stats, all live:", end=" ")
    f, _ = reg(pnl.loc[live0:"2022-12-31"], ff[fac].reindex(pnl.loc[live0:"2022-12-31"].index), NW_LAGS)
    print(", ".join(f"{c} {f.tvalues[c]:+.2f}" for c in fac))
    # Dimson: contemporaneous + 1 lag (a thin CEF price can lag the market by a day)
    print("\n6b. DAILY, Dimson (factors at t and t-1, betas summed), gross:")
    print(f"{'window':<18}{'alpha%':>8}{'t':>7}" + "".join(f"{'S' + c:>9}" for c in fac))
    for lab, a, b in windows:
        y = pnl.loc[a:b]
        X = pd.concat([ff[fac].reindex(y.index), ff[fac].shift(1).reindex(y.index).add_suffix("_l1")], axis=1)
        f, n = reg(y, X, NW_LAGS)
        print(f"{lab:<18}{f.params['const'] * 252 * 100:8.2f}{f.tvalues['const']:7.2f}"
              + "".join(f"{f.params[c] + f.params[c + '_l1']:9.3f}" for c in fac))

    # monthly
    ffm = ffm.set_index("date")
    psm = ps.set_index("date")["liq_v"]
    mp = (1 + pnl.loc[live0:"2022-12-31"]).groupby(pd.Grouper(freq="ME")).prod() - 1
    mnet = {c: (1 + nets[c].loc[live0:"2022-12-31"]).groupby(pd.Grouper(freq="ME")).prod() - 1 for c in COSTS}
    first_full = (live0 + pd.offsets.MonthBegin(1)) + pd.offsets.MonthEnd(0)
    mp = mp.loc[first_full:]
    Xm = pd.concat([ffm[fac], psm.rename("liq_v")], axis=1).reindex(mp.index)
    print(f"\n6c. MONTHLY (compounded daily P&L, first full month {first_full.date()}), FF5 + UMD + "
          f"Pastor-Stambaugh traded LIQ_V, HAC(3). alpha in %/yr (x12).")
    facm = fac + ["liq_v"]
    print(f"{'window':<18}{'n':>5}{'alpha%':>8}{'t':>7}" + "".join(f"{c:>8}" for c in facm) + f"{'R2':>7}"
          + "".join(f"{'a@' + str(c):>8}{'t':>6}" for c in COSTS))
    mwins = [("2013-07..2014", first_full, "2014-12-31"), ("2015-19", "2015-01-01", "2019-12-31"),
             ("2020-22", "2020-01-01", "2022-12-31"), ("all live 2013-22", first_full, "2022-12-31")]
    for lab, a, b in mwins:
        y = mp.loc[a:b]
        f, n = reg(y, Xm.loc[y.index], 3)
        netcols = ""
        for c in COSTS:
            fn, _ = reg(mnet[c].loc[y.index], Xm.loc[y.index], 3)
            netcols += f"{fn.params['const'] * 12 * 100:8.2f}{fn.tvalues['const']:6.2f}"
        print(f"{lab:<18}{n:5d}{f.params['const'] * 12 * 100:8.2f}{f.tvalues['const']:7.2f}"
              + "".join(f"{f.params[c]:8.3f}" for c in facm) + f"{f.rsquared:7.3f}" + netcols)
    f, _ = reg(mp, Xm.loc[mp.index], 3)
    print("  beta t-stats, all live:", ", ".join(f"{c} {f.tvalues[c]:+.2f}" for c in facm))
    print(f"  mean monthly P&L {mp.mean() * 12 * 100:.2f}%/yr; months {len(mp)}")

    # credit and rates, CRSP ETF total returns (an addition: the book is a credit book)
    c = D.crsp()
    E = _pivot(c, "ret", ["HYG", "IEF", "LQD", "MUB"], D.idx)
    Xc = pd.DataFrame({"hyg_ief": E["HYG"] - E["IEF"], "ief_rf": E["IEF"] - ff["rf"].reindex(D.idx),
                       "mub_ief": E["MUB"] - E["IEF"]})
    print("\n6d. ADDITION (not in the work order): credit and rates, daily, gross, HAC(5); "
          "HYG-IEF, IEF-rf, MUB-IEF from CRSP total returns, beside FF5 + UMD")
    print(f"{'window':<18}{'alpha%':>8}{'t':>7}{'hyg_ief':>9}{'t':>6}{'ief_rf':>9}{'t':>6}{'mub_ief':>9}{'t':>6}{'R2':>7}")
    for lab, a, b in windows:
        y = pnl.loc[a:b]
        X = pd.concat([ff[fac].reindex(y.index), Xc.reindex(y.index)], axis=1)
        f, n = reg(y, X, NW_LAGS)
        print(f"{lab:<18}{f.params['const'] * 252 * 100:8.2f}{f.tvalues['const']:7.2f}"
              + "".join(f"{f.params[k]:9.3f}{f.tvalues[k]:6.2f}" for k in ("hyg_ief", "ief_rf", "mub_ief"))
              + f"{f.rsquared:7.3f}")
    print("\nSadka liquidity: NOT USED. No free public source was found (2026-10-11 search: it is "
          "distributed through WRDS's licensed Fama-French & Liquidity Factors bundle). The desk's "
          "R2 WRDS mirror holds ff_all.liq_sadka, but it ENDS 1983-04..2008-12, before the "
          "deployed book's first position (2013-06), so it could not attribute this P&L even if "
          "it were used. Not substituted by any other liquidity measure.")


SECTIONS = {"ic": sec_baseline, "total": sec_total_return, "bounce": sec_bounce,
            "stale": sec_stale_nav, "where": sec_where, "split": sec_pnl_split,
            "factors": sec_factors}


def main(argv):
    want = argv or list(SECTIONS)
    bad = [w for w in want if w not in SECTIONS]
    if bad:
        raise SystemExit(f"unknown section(s) {bad}; choose from {list(SECTIONS)}")
    print(summary())
    print(f"W4 artifact battery -- FIT PERIOD ONLY ({SAMPLE_START} .. {FIT_END}); the 2023-01-01 "
          f"holdout is sealed and never computed. Run {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC.")
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet", columns=["date"])
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet", columns=["date"])
    Dd = pd.read_parquet(REPO / "data/cef/cef_distributions.parquet", columns=["ex_date"])
    print(f"panels: cef_prices last {P.date.max().date()}, cef_nav last {N.date.max().date()}, "
          f"cef_distributions last ex-date {Dd.ex_date.max().date()} (read-only; only <= {FIT_END} used)")
    D = Data()
    print(f"deployed book: {len(D.T)} sessions {D.T.index[0].date()}..{D.T.index[-1].date()}; "
          f"first session with >= {MIN_NAMES} eligible names "
          f"{D.M_dep.any(axis=1).idxmax().date()}; deployed signal dates "
          f"{int(D.M_dep.any(axis=1).sum())}")
    for w in want:
        SECTIONS[w](D)


if __name__ == "__main__":
    main(sys.argv[1:])
