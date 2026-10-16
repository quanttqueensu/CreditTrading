"""The live CEF book's own risk profile: the baseline every new sleeve is combined
with. ZERO trials.

    python3 scripts/cef/portfolio_baseline.py                  # every section, to stdout
    python3 scripts/cef/portfolio_baseline.py tails breadth    # chosen sections only

The write-up is results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md §6; the run behind it
is results/cef/portfolio_baseline/portfolio_baseline_output.txt.

WHY THIS EXISTS
---------------
The team lead asked on 2026-10-15 for a portfolio-level framework that combines the
live discount book with any number of event-driven and special-situation sleeves
in one Alpaca account. Every allocation rule in that framework (the combined vol
target under W6, the shared Reg T gross, the drawdown lines, the capacity caps,
the factor limits) is a function of the live book's own risk. Those inputs had
never been measured together on the deployed v7 book: the figures the desk
quotes for them (effective breadth 1.17, PC2 65.7%, kurtosis 41.2, the vol
scalar averaging 1.50) are 17-name, pre-v7 numbers, several measured on panels
that reach into the 2023+ holdout. This script measures them on the book that
trades, in the fit window only, so the framework keys on a re-runnable method
rather than on a figure written in a document (H14).

WHAT IT IS, AND WHAT IT IS NOT
------------------------------
Descriptive measurement of the DEPLOYED policy, `band_gross_capped(T, BAND_WIDTH,
MAX_GROSS_STRESS)` on the frozen spec's 13 names, exactly as `real_money_costs.Book`
builds it (that class is reused, so there is one definition of the deployed book).
It tests no signal and no policy variant, chooses nothing, and moves no counter.
The kill-probability section scales the book's OWN P&L to other volatilities to
evaluate a constraint function for W6; it does not run a different policy, and
the vol target it would imply is the team lead's decision (§7 of the note).

THE TWO HOLDOUTS
----------------
* Time (H13): every return, position and covariance stops at 2022-12-30. `Book`
  truncates T and R with `fit_only` before the policy runs; every frame this
  script builds is checked by `_assert_fit`. The one input dated after 2022 is
  the borrow FEE level of the P3 proxy (each name's mean over the last 63
  FEE_RATE dates), read as a cost input exactly as
  results/cef/REAL_MONEY_COSTS_2026-10-12.md did; no 2023+ return is read.
* Names (H9): only the spec's universe is read. The factor proxies (HYG, IEF,
  MUB, BKLN) are ETFs, not CEFs, and come from the W4 CRSP cache, which stops at
  2022-12-31.

THE HARNESS
-----------
P&L comes only from `evaluate()` (shift(2): decide t, MOC fill t+1, earn t+2),
on total returns. The cost grid (5/15/30bp) is beside every gross figure, and
borrow is charged separately and labelled (H3, H4).

DATA (read-only; nothing under data/ is written)
------------------------------------------------
data/cef/{cef_prices,cef_nav,cef_distributions,cef_splits,cef_borrow_history}.parquet,
data/cef/cef_universe.csv (group labels). Gitignored caches, each built by a
fetcher: results/cef/w4/_cache_w4/ff5_umd_daily.parquet
(scripts/data/fetch_ff_factors.py) and crsp_dsf_w4.parquet
(scripts/data/stage_crsp_w4.py). A missing cache raises, naming its builder.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import (  # noqa: E402
    HOLDOUT_START, _stats, borrow_charge, build_panel, total_returns,
)
from scripts.cef.real_money_costs import (  # noqa: E402
    FIT_END, RECENT, Book, const_fee, fee_history, net_series,
)
from scripts.cef.spec import (  # noqa: E402
    CAPITAL_USD, MAX_GROSS_STRESS, UNIVERSE, VOL_TARGET, risk, summary,
)
from scripts.cef.w4_artifacts import CACHE, _assert_fit, _need, groups  # noqa: E402

# The mandate's ceiling on the vol target: team lead, 2026-09-08, docs/SYSTEM.md §5
# ("Derive the vol target, cap 20%"), restated 2026-10-09. It is a mandate bound,
# not a frozen-spec parameter, so it is not read from the spec; nothing live reads
# it from here.
VOL_CAP = 0.20
# The drawdown lines are the frozen spec's own (risk.halve_drawdown and
# risk.kill_drawdown), FRACTIONS of equity: 0.12 means 12%. Units trap (the
# 2026-08-31 incident): the book json's book_drawdown_suspend_pct is a WHOLE-NUMBER
# percent, and 0.99 there meant 0.99%. These two are fractions; assert it.
HALVE_DD = float(risk("halve_drawdown"))
KILL_DD = float(risk("kill_drawdown"))
assert 0.0 < HALVE_DD < KILL_DD < 1.0, "the spec's drawdown lines must be fractions of equity"

ERAS = [("live 2013-06..2014", None, "2014-12-31"), ("2015-19", "2015-01-01", "2019-12-31"),
        ("2020-22", "2020-01-01", "2022-12-31"), ("live fit 2013-06..2022", None, FIT_END)]
HORIZON = 252                 # twelve months of sessions: "still running in twelve months"
BOOT_REPS, SEED = 10_000, 20261015
SCAL_FLOOR, SCAL_CAP = 0.2, 2.5   # the vol-scalar clip in build_targets and the sleeve
COV_WINDOW, COV_MIN = 252, 126    # ex-ante covariance: one year, at least half of it
NW_LAGS = 5
SCENARIOS = {                     # declared stress windows (descriptive, not chosen on P&L)
    "GFC 2008-09..2009-03": ("2008-09-01", "2009-03-31"),
    "taper 2013-05..2013-08": ("2013-05-01", "2013-08-30"),
    "COVID 2020-02-20..04-30": ("2020-02-20", "2020-04-30"),
    "rates 2022-01..2022-10": ("2022-01-03", "2022-10-31"),
}
MUNI = "muni"


def hr(title: str) -> None:
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


# --------------------------------------------------------------------------- pure helpers
# Each is tested in scripts/cef/tests/test_portfolio_baseline.py on synthetic inputs
# (a test of the method, never a claim about the market).

def max_drawdown(pnl: pd.Series) -> dict:
    """Largest peak-to-trough fall of compounded equity (1 + pnl).cumprod(), as a
    positive fraction, with the peak, trough and recovery dates. Equity starts at
    1.0 before the first row, so a loss on day one is a drawdown from 1.0.
    `recovered` is None when equity never regains the peak inside the series."""
    if pnl.isna().any():
        raise ValueError("max_drawdown: the P&L series holds NaN; a gap is not a zero")
    eq = (1.0 + pnl).cumprod()
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq.values]))[1:]
    dd = 1.0 - eq.values / peak
    i = int(dd.argmax())
    if dd[i] <= 0:
        return dict(mdd=0.0, peak=None, trough=None, recovered=None)
    pk_val = peak[i]
    before = np.where(np.concatenate([[1.0], eq.values[:i + 1]]) >= pk_val - 1e-15)[0]
    pk_pos = int(before.max()) - 1            # -1: the synthetic start
    after = np.where(eq.values[i:] >= pk_val - 1e-15)[0]
    return dict(mdd=float(dd[i]),
                peak=None if pk_pos < 0 else eq.index[pk_pos],
                trough=eq.index[i],
                recovered=None if not len(after) else eq.index[i + int(after[0])])


def euler_split(h: np.ndarray, S: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Euler (marginal-contribution) split of the variance h'Sh between a component
    b and the rest w = h - b: (b'Sh / h'Sh, w'Sh / h'Sh). The two shares sum to 1
    exactly; either may be negative when the components hedge each other."""
    tot = float(h @ S @ h)
    if tot <= 0:
        raise ValueError("euler_split: the book has no variance")
    sb = float(b @ S @ h) / tot
    return sb, 1.0 - sb


def group_component(h: pd.Series, grp: dict, names: list[str]) -> pd.Series:
    """The book's between-group bet: each group's net weight spread equally over
    the group's names in `names` (the names with an estimable covariance today).
    h - group_component(h) then nets to zero inside every group, so it is pure
    selection. A held name outside `names` raises: its risk would be dropped."""
    held_out = sorted(t for t, v in h.items() if v != 0 and t not in names)
    if held_out:
        raise ValueError(f"group_component: held names without a covariance: {held_out}")
    b = pd.Series(0.0, index=names)
    for g in sorted({grp[t] for t in names}):
        members = [t for t in names if grp[t] == g]
        net = float(sum(h.get(t, 0.0) for t in members))
        b[members] = net / len(members)
    return b


def estimable_names(S: pd.DataFrame, counts: pd.Series) -> list[str]:
    """The largest set of names, found greedily, on which every pairwise covariance
    in S is defined: start from every name with its own variance, and while any
    pair is undefined drop the name with the fewest observations (ties: the later
    name in S's order). A name that did not trade yet (PDO before 2021-02) is
    therefore dropped from the set, never given an invented covariance; whether a
    HELD name was dropped is the caller's check."""
    names = [c for c in S.columns if S.loc[c, c] == S.loc[c, c]]
    while names:
        sub = S.loc[names, names]
        if sub.notna().all().all():
            return names
        bad = sub.isna().sum()
        worst = bad[bad > 0].index
        drop = min(worst, key=lambda c: (counts[c], -names.index(c)))
        names.remove(drop)
    return names


def breadth(h: np.ndarray, S: np.ndarray) -> dict:
    """Effective breadth of a book on a covariance S: BR = 1 / sum_k v_k^2, where
    v_k = lambda_k (e_k'h)^2 / h'Sh is principal component k's share of the book's
    variance (the measure docs/BRIEF.md §1 and plan_diagnostics.pca use, with every
    component kept separately instead of lumping the tail). BR equals the number
    of names for an equal-risk book on uncorrelated names and tends to 1 when one
    factor carries the risk. Raises on a covariance that is not PSD."""
    lam, E = np.linalg.eigh(S)
    if lam.min() < -1e-10 * max(lam.max(), 1e-300):
        raise ValueError(f"breadth: covariance not PSD (min eigenvalue {lam.min():.3e})")
    lam = np.clip(lam, 0.0, None)
    proj = E.T @ h
    contrib = lam * proj ** 2
    tot = contrib.sum()
    if tot <= 0:
        raise ValueError("breadth: the book has no variance")
    v = contrib / tot
    return dict(br=float(1.0 / np.sum(v ** 2)), top=float(v.max()))


def stationary_index(n: int, length: int, reps: int, mean_block: float,
                     rng: np.random.Generator) -> np.ndarray:
    """Index paths (reps x length) into a series of n observations by the
    Politis & Romano (1994) stationary bootstrap: each path starts at a uniform
    index, and each later step starts a new block (a uniform index) with
    probability 1/mean_block, else continues the current one, modulo n. The same
    scheme `w4_artifacts.stationary_boot` uses, returned as paths because a
    drawdown needs the ORDER of a year's returns, not only their mean."""
    if n < 3 * mean_block or mean_block < 1:
        raise ValueError(f"stationary_index: {n} observations for a mean block of {mean_block}")
    pos = np.arange(length)
    starts = rng.integers(0, n, size=(reps, length))
    new = rng.random((reps, length)) < 1.0 / mean_block
    new[:, 0] = True
    last = np.maximum.accumulate(np.where(new, pos[None, :], 0), axis=1)
    return (np.take_along_axis(starts, last, axis=1) + (pos[None, :] - last)) % n


def path_max_drawdown(paths: np.ndarray) -> np.ndarray:
    """Max drawdown of each row of daily returns, compounded, from a start of 1.0."""
    eq = np.cumprod(1.0 + paths, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((len(eq), 1)), eq], axis=1), axis=1)[:, 1:]
    return (1.0 - eq / peak).max(axis=1)


def p_breach(x: np.ndarray, sigma: float, line: float, idx: np.ndarray | None = None,
             gauss: np.ndarray | None = None) -> float:
    """P(max drawdown over a path >= line) for the daily series x rescaled to an
    annualised vol of `sigma`. Rescaling multiplies every return by one constant,
    so the Sharpe is kept and only the size of the book changes. The same `idx`
    (or the same standard-normal `gauss` draws) is used at every sigma: common
    random numbers, so the function of sigma is smooth and monotone enough to
    solve. Exactly one of idx / gauss is given."""
    if (idx is None) == (gauss is None):
        raise ValueError("p_breach: give exactly one of idx or gauss")
    s = x.std(ddof=1) * np.sqrt(252)
    if s <= 0:
        raise ValueError("p_breach: the series has no variance")
    c = sigma / s
    paths = c * x[idx] if idx is not None else c * (x.mean() + x.std(ddof=1) * gauss)
    return float((path_max_drawdown(paths) >= line).mean())


def sigma_star(x: np.ndarray, line: float, p: float, idx=None, gauss=None,
               lo: float = 0.001, hi: float = 0.40, iters: int = 40) -> float | None:
    """The largest annualised vol at which P(max drawdown >= line) <= p, by
    bisection on [lo, hi]. `hi` is the registry's sanity bound on
    vol_target_annual (src/deploy/registry.py). None when even `lo` breaches
    (the constraint cannot be met by any book worth running); `hi` itself when
    the constraint does not bind inside the bracket."""
    f = lambda s: p_breach(x, s, line, idx, gauss)
    if f(lo) > p:
        return None
    if f(hi) <= p:
        return hi
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) <= p:
            lo = mid
        else:
            hi = mid
    return lo


def group_proxy(r: pd.DataFrame, grp: dict) -> tuple[pd.DataFrame, int]:
    """Fill a name's missing return with the equal-weight mean of its group's
    names that have one that day (a SCENARIO proxy for names that did not exist
    yet, labelled wherever it is used). Raises if a group has no name with a
    return on a day a member needs one. Returns the filled frame and the number
    of name-days proxied."""
    out = r.copy()
    n = 0
    for g in sorted(set(grp[c] for c in r.columns)):
        cols = [c for c in r.columns if grp[c] == g]
        m = r[cols].mean(axis=1, skipna=True)
        for c in cols:
            miss = r[c].isna()
            if miss.any():
                if m[miss].isna().any():
                    d = m[miss][m[miss].isna()].index[0]
                    raise ValueError(f"group_proxy: group {g} has no return on {d.date()}")
                out.loc[miss, c] = m[miss]
                n += int(miss.sum())
    return out, n


# --------------------------------------------------------------------------- the book

class Base:
    """The deployed book (reused from real_money_costs.Book) plus the frames the
    sections share. Built once; every frame is checked against the holdout."""

    def __init__(self):
        self.B = Book()
        B = self.B
        self.idx = B.H.index
        self.live0 = B.live0
        self.U = list(UNIVERSE)
        self.grp = groups()
        p = build_panel(end=FIT_END)
        # Returns WITH NaN kept (the harness's R is fillna(0), right for P&L but
        # wrong for a covariance: a name that did not exist would read as riskless).
        self.r_nan = total_returns(p["ret"][self.U].reindex(self.idx))
        self.adv = p["adv"][self.U].reindex(self.idx)
        _assert_fit(self.idx, self.r_nan, self.adv, B.T, B.H, B.R_tr)

    def window(self, a, b):
        return (self.live0 if a is None else pd.Timestamp(a)), pd.Timestamp(b)


# --------------------------------------------------------------------------- sections

def sec_book(X: Base):
    hr("1. THE DEPLOYED BOOK -- gross headline (total returns), cost grid beside it")
    B = X.B
    print(summary())
    print(f"fit index {X.idx[0].date()} .. {X.idx[-1].date()} ({len(X.idx)} sessions); first "
          f"position {X.live0.date()}; 2023+ is the sealed holdout and is not computed.")
    print("Second method: real_money_costs.py §1 printed gross SR 0.69 (fit) / 0.96 (live) on "
          "the same book; the 'live fit' row below must reproduce 0.96.\n")
    print(f"{'window':<26}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'turn/yr':>8}{'@5':>7}{'@15':>7}"
          f"{'@30':>7}{'flips?':>7}{'gross':>7}{'short':>7}")
    for lab, a, b in ERAS:
        a, b = X.window(a, b)
        s = _stats(B.pnl.loc[a:b], B.turn.loc[a:b])
        signs = {np.sign(s["sr"])} | {np.sign(n) for n in s["nets"]}
        print(f"{lab:<26}{s['sr']:8.2f}{s['ann'] * 100:7.2f}{s['vol'] * 100:7.2f}{s['turn']:8.1f}"
              + "".join(f"{n:7.2f}" for n in s["nets"])
              + f"{'YES' if len(signs) > 1 else 'no':>7}"
              + f"{B.gross_held.loc[a:b].mean():7.2f}{B.short_held.loc[a:b].mean():7.2f}")
    print("gross / short = mean held gross and short (H.shift(2)) as multiples of capital.")


def sec_sizing(X: Base):
    hr("2. SIZING -- the vol scalar, held gross, the stress cap, and vol per unit of gross")
    B = X.B
    a, b = X.live0, pd.Timestamp(FIT_END)
    scal = B.T.abs().sum(axis=1).loc[a:b]            # build_targets: unit gross x scalar
    scal = scal[scal > 0]
    print(f"vol scalar = gross of the frictionless target (unit gross x clip({VOL_TARGET:.0%}/rv63, "
          f"{SCAL_FLOOR}, {SCAL_CAP})), live fit window, {len(scal)} sessions:")
    print(f"  mean {scal.mean():.2f}  median {scal.median():.2f}  p5 {scal.quantile(.05):.2f}  "
          f"p95 {scal.quantile(.95):.2f}  at the {SCAL_CAP} cap {(scal >= SCAL_CAP - 1e-9).mean():.1%}"
          f"  at the {SCAL_FLOOR} floor {(scal <= SCAL_FLOOR + 1e-9).mean():.1%}")
    gH = B.H.abs().sum(axis=1).loc[a:b]
    cap = MAX_GROSS_STRESS
    print(f"\nheld gross of the deployed book (H, after band and cap {cap}x):")
    print(f"  mean {gH.mean():.2f}  median {gH.median():.2f}  p95 {gH.quantile(.95):.2f}  max "
          f"{gH.max():.2f}  sessions at the cap {(gH >= cap - 1e-9).mean():.1%}")
    print(f"\n{'window':<26}{'vol%':>7}{'target%':>8}{'ratio':>7}{'sigma1%':>9}{'sigma1b%':>9}"
          f"{'vol@cap%':>9}{'G@20%':>7}")
    for lab, a2, b2 in ERAS:
        a2, b2 = X.window(a2, b2)
        p = B.pnl.loc[a2:b2]
        g = B.gross_held.loc[a2:b2]
        vol = p.std() * np.sqrt(252)
        # sigma1: vol of the P&L per unit of the gross that earned it (two methods)
        per_unit = (p / g.where(g > 0)).dropna()
        s1 = per_unit.std() * np.sqrt(252)
        s1b = vol / g.mean()
        print(f"{lab:<26}{vol * 100:7.2f}{VOL_TARGET * 100:8.2f}{vol / VOL_TARGET:7.2f}"
              f"{s1 * 100:9.2f}{s1b * 100:9.2f}{cap * s1 * 100:9.2f}{VOL_CAP / s1:7.2f}")
    print("sigma1 = annualised sd of pnl_t / gross held_t; sigma1b = vol / mean gross (second "
          "method).\nvol@cap = max_gross_stress x sigma1: the most vol the CEF book ALONE can carry "
          "under the Reg T stress cap\nif its vol per unit gross is unchanged. G@20% = the gross a "
          f"{VOL_CAP:.0%} vol book would need (against the {cap}x cap).")

    # RETURN PER UNIT OF GROSS. Under Reg T the account's scarce resource is gross
    # (margin), not vol: when the stress cap binds, the most the book can earn is
    # cap x (return per unit of gross held), whatever its vol target. Turnover and
    # borrow scale with gross too, so the net figure is per unit of gross as well.
    print(f"\nreturn per unit of gross held, and the most the book earns at the {cap}x cap "
          "(gross of costs, then net of 15bp):")
    print(f"{'window':<26}{'ann%':>7}{'gross':>7}{'ret/G%':>8}{'@cap%':>7}{'net15/G%':>10}{'@cap%':>7}")
    for lab, a2, b2 in ERAS:
        a2, b2 = X.window(a2, b2)
        p = B.pnl.loc[a2:b2]
        g = B.gross_held.loc[a2:b2].mean()
        ann = p.mean() * 252
        net = ann - B.turn.loc[a2:b2].mean() * 252 * 15 / 1e4
        print(f"{lab:<26}{ann * 100:7.2f}{g:7.2f}{ann / g * 100:8.2f}{cap * ann / g * 100:7.2f}"
              f"{net / g * 100:10.2f}{cap * net / g * 100:7.2f}")
    print("@cap = the return of the same book held at the stress cap every session (linear "
          "scaling: Sharpe unchanged, vol x cap/gross).")


def sec_tails(X: Base):
    hr("3. TAILS AND DRAWDOWNS -- daily P&L of the deployed book, gross (total returns)")
    B = X.B
    print(f"{'window':<26}{'skew':>7}{'exkurt':>8}{'worst d%':>9}{'(sd)':>6}{'w5d%':>7}{'w21d%':>7}"
          f"{'VaR99%':>8}{'ES99%':>7}{'maxDD%':>8}  peak -> trough -> recovered")
    for lab, a, b in ERAS:
        a, b = X.window(a, b)
        p = B.pnl.loc[a:b]
        sd = p.std()
        q = p.quantile(0.01)
        m = max_drawdown(p)
        rec = m["recovered"].date() if m["recovered"] is not None else "not by 2022-12-30"
        pk = m["peak"].date() if m["peak"] is not None else "start"
        print(f"{lab:<26}{p.skew():7.2f}{p.kurt():8.1f}{p.min() * 100:9.2f}{p.min() / sd:6.1f}"
              f"{p.rolling(5).sum().min() * 100:7.2f}{p.rolling(21).sum().min() * 100:7.2f}"
              f"{-q * 100:8.2f}{-p[p <= q].mean() * 100:7.2f}{m['mdd'] * 100:8.2f}  "
              f"{pk} -> {m['trough'].date()} -> {rec}")
    print("worst d (sd) = the worst day in units of that window's daily sd. w5d / w21d = worst "
          "rolling sum of 5 / 21 sessions.\nVaR99 / ES99 = historical 1% quantile loss and the mean "
          "loss beyond it. Kurtosis is EXCESS (normal = 0).")
    worst = B.pnl.loc[X.live0:FIT_END].nsmallest(5)
    print("\nfive worst days, live fit window: " +
          ", ".join(f"{d.date()} {v * 100:+.2f}%" for d, v in worst.items()))


def _factors(X: Base) -> pd.DataFrame:
    ff = pd.read_parquet(_need(CACHE / "ff5_umd_daily.parquet", "scripts/data/fetch_ff_factors.py"))
    c = pd.read_parquet(_need(CACHE / "crsp_dsf_w4.parquet", "scripts/data/stage_crsp_w4.py"))
    print(f"factors: Ken French daily, CRSP vintage {ff.crsp_vintage.iloc[0]}, last "
          f"{ff.date.max().date()}, fetched {ff.fetched_at_utc.iloc[0]}; ETF total returns: CRSP "
          f"dsf `ret` (W4 cache), last {c.date.max().date()}")
    ff = ff.set_index("date")
    E = c[c.ticker.isin(["HYG", "IEF", "MUB", "BKLN"])].pivot_table(
        index="date", columns="ticker", values="ret").reindex(X.idx)
    F = pd.DataFrame({
        "mktrf": ff["mktrf"], "smb": ff["smb"], "hml": ff["hml"], "rmw": ff["rmw"],
        "cma": ff["cma"], "umd": ff["umd"]}).reindex(X.idx)
    F["credit"] = E["HYG"] - E["IEF"]              # HY credit excess of duration-matched-ish Treasuries
    F["rates"] = E["IEF"] - ff["rf"].reindex(X.idx)  # 7-10y Treasury excess of cash
    F["muni"] = E["MUB"] - E["IEF"]                # munis against Treasuries
    F["loans"] = E["BKLN"] - ff["rf"].reindex(X.idx)  # leveraged loans excess of cash (from 2011-03)
    _assert_fit(F)
    return F


def sec_factors(X: Base):
    import statsmodels.api as sm
    hr("4. FACTOR EXPOSURE -- the D4 test (alpha t >= 3.0, every |beta| <= 0.10) on the book itself")
    B = X.B
    F = _factors(X)
    a, b = X.live0, pd.Timestamp(FIT_END)

    def reg(y, Xf, lags=NW_LAGS):
        d = pd.concat([y.rename("y"), Xf], axis=1).dropna()
        return sm.OLS(d["y"], sm.add_constant(d.drop(columns="y"))).fit(
            cov_type="HAC", cov_kwds={"maxlags": lags}), len(d)

    # (A) W4's 6d model, as a second method on W4's published figures
    A = ["mktrf", "smb", "hml", "rmw", "cma", "umd", "credit", "rates", "muni"]
    print("\n4a. W4's model (FF5 + UMD + HYG-IEF + IEF-rf + MUB-IEF), contemporaneous, gross, "
          "HAC(5). alpha %/yr.\n    Second method: results/cef/W4_ARTIFACTS_2026-10-11.md §6d "
          "ran this regression on the same book.")
    print(f"{'window':<26}{'n':>6}{'alpha%':>8}{'t':>6}" + "".join(f"{k:>8}" for k in A) + f"{'R2':>7}")
    for lab, a2, b2 in ERAS:
        a2, b2 = X.window(a2, b2)
        f, n = reg(B.pnl.loc[a2:b2], F[A].loc[a2:b2])
        print(f"{lab:<26}{n:6d}{f.params['const'] * 25200:8.2f}{f.tvalues['const']:6.2f}"
              + "".join(f"{f.params[k]:8.3f}" for k in A) + f"{f.rsquared:7.3f}")

    # (B) the risk model the framework uses: five macro factors, Dimson (t and t-1),
    # betas summed, because a thinly traded CEF can price a factor move a day late.
    K = ["mktrf", "credit", "rates", "muni", "loans"]
    print("\n4b. RISK-MODEL FACTORS, Dimson (t and t-1, betas summed), gross, HAC(5); "
          "loans from BKLN's first return (2011-03).\n    'scaled' = summed beta x "
          f"{VOL_TARGET:.0%} / window vol: the beta of the same book run at the spec's vol target.")
    print(f"{'window':<26}{'n':>6}{'alpha%':>8}{'t':>7}" + "".join(f"{k:>9}{'t':>6}" for k in K)
          + f"{'R2':>7}{'max|scaled|':>12}{'D4':>6}")
    for lab, a2, b2 in ERAS:
        a2, b2 = X.window(a2, b2)
        y = B.pnl.loc[a2:b2]
        Xd = pd.concat([F[K].loc[a2:b2], F[K].shift(1).loc[a2:b2].add_suffix("_l1")], axis=1)
        f, n = reg(y, Xd)
        V = f.cov_params()
        sums, ts = {}, {}
        for k in K:
            s = f.params[k] + f.params[k + "_l1"]
            v = V.loc[k, k] + V.loc[k + "_l1", k + "_l1"] + 2 * V.loc[k, k + "_l1"]
            sums[k], ts[k] = s, s / np.sqrt(v)
        vol = y.std() * np.sqrt(252)
        scaled = {k: sums[k] * VOL_TARGET / vol for k in K}
        mx = max(abs(v) for v in scaled.values())
        d4 = "pass" if (f.tvalues["const"] >= 3.0 and mx <= 0.10) else "FAIL"
        print(f"{lab:<26}{n:6d}{f.params['const'] * 25200:8.2f}{f.tvalues['const']:7.3f}"
              + "".join(f"{sums[k]:9.3f}{ts[k]:6.2f}" for k in K)
              + f"{f.rsquared:7.3f}{mx:12.3f}{d4:>6}")
    print("D4 is judged on the whole live window; an era row can fail it on the alpha t alone "
          "(fewer sessions).")

    # (C) the short-put check: is the book's credit exposure larger on credit's down days?
    print("\n4c. DOWNSIDE CREDIT (the short-put signature of merger arbitrage, Mitchell & Pulvino "
          "2001):\n    pnl on mktrf, credit, and min(credit, 0); Dimson-summed, live fit window, HAC(5).")
    y = B.pnl.loc[a:b]
    Fd = F[["mktrf", "credit"]].copy()
    Fd["credit_dn"] = F["credit"].clip(upper=0.0)
    Xd = pd.concat([Fd.loc[a:b], Fd.shift(1).loc[a:b].add_suffix("_l1")], axis=1)
    f, n = reg(y, Xd)
    V = f.cov_params()
    for k in ("mktrf", "credit", "credit_dn"):
        s = f.params[k] + f.params[k + "_l1"]
        v = V.loc[k, k] + V.loc[k + "_l1", k + "_l1"] + 2 * V.loc[k, k + "_l1"]
        print(f"  {k:<10} summed beta {s:+.4f}  t {s / np.sqrt(v):+.2f}")
    print("  A significantly positive credit_dn beta would mean the book loses MORE per unit of "
          "credit sell-off than it gains\n  per unit of rally: the shape every event sleeve with "
          "deal-break risk also has, so the two would add in a tail.")


def sec_breadth(X: Base):
    hr("5. BREADTH AND THE GROUP BET -- ex-ante, on the held book and a trailing covariance")
    B = X.B
    grp = X.grp
    print("For each live fit session t: h = H.loc[t] (the book decided at t), S = covariance of "
          f"total returns over the {COV_WINDOW}\nsessions ending at t (known at the evening "
          f"decision; pairwise, >= {COV_MIN} observations per pair). A session where a held name "
          "has\nfewer observations is skipped and counted, never filled. Groups: "
          + ", ".join(f"{g} {sorted(t for t in X.U if grp[t] == g)}" for g in sorted(set(grp.values()))))
    rows, skipped, nonpsd = [], 0, 0
    dates = X.idx[(X.idx >= X.live0)]
    for t in dates:
        h_all = B.H.loc[t]
        if h_all.abs().sum() == 0:
            continue
        win = X.r_nan.loc[:t].tail(COV_WINDOW)
        _assert_fit(win)
        S_full = win.cov(min_periods=COV_MIN)
        names = estimable_names(S_full, win.notna().sum())
        held = [c for c in X.U if h_all[c] != 0]
        if any(c not in names for c in held):
            skipped += 1
            continue
        S = S_full.loc[names, names].values * 252
        h = h_all.reindex(names).fillna(0.0)
        hv = h.values
        try:
            br = breadth(hv, S)
        except ValueError:
            nonpsd += 1
            continue
        b2 = group_component(h, {c: (MUNI if grp[c] == MUNI else "taxable") for c in names}, names)
        b4 = group_component(h, grp, names)
        mt2, _ = euler_split(hv, S, b2.values)
        mt4, _ = euler_split(hv, S, b4.values)
        muni_net = float(sum(h[c] for c in names if grp[c] == MUNI))
        rows.append(dict(date=t, br=br["br"], top=br["top"], n_held=len(held),
                         share_mt=mt2, share_g4=mt4, muni_net=muni_net,
                         vol=float(np.sqrt(hv @ S @ hv))))
    D = pd.DataFrame(rows).set_index("date")
    _assert_fit(D)
    print(f"\nsessions measured {len(D)}; skipped (a held name without a covariance) {skipped}; "
          f"non-PSD {nonpsd}")
    print(f"\n{'window':<26}{'BR med':>8}{'p10':>6}{'p90':>6}{'top PC':>8}{'held':>6}"
          f"{'muni-vs-tax':>12}{'p90':>6}{'4-group':>9}{'p90':>6}{'|muni net|':>11}{'ex-ante vol%':>13}")
    for lab, a, b in ERAS:
        a, b = X.window(a, b)
        d = D.loc[a:b]
        print(f"{lab:<26}{d.br.median():8.2f}{d.br.quantile(.1):6.2f}{d.br.quantile(.9):6.2f}"
              f"{d.top.median():8.1%}{d.n_held.median():6.0f}{d.share_mt.median():12.1%}"
              f"{d.share_mt.quantile(.9):6.1%}{d.share_g4.median():9.1%}{d.share_g4.quantile(.9):6.1%}"
              f"{d.muni_net.abs().median():11.3f}{d.vol.median() * 100:13.2f}")
    print("BR = 1/sum v_k^2 over principal components (every component kept). top PC = the "
          "largest single component's share.\nmuni-vs-tax / 4-group = Euler share of ex-ante "
          "variance carried by the between-group bet (muni vs taxable; or the four groups);\n"
          "the rest is selection within groups. |muni net| = |sum of muni weights| (multiples of "
          "capital).")

    # Realised: the group bet's share of the realised P&L variance (second method)
    r = X.B.R_tr.where(X.r_nan.notna())
    held = B.H.shift(2).fillna(0.0)
    between = pd.Series(0.0, index=X.idx)
    for g in sorted(set(grp.values())):
        cols = [c for c in X.U if grp[c] == g]
        between += held[cols].sum(axis=1) * r[cols].mean(axis=1).fillna(0.0)
    tot = B.pnl
    print("\nrealised (second method): cov(group-spread P&L, P&L) / var(P&L), four groups, where "
          "group-spread P&L = sum_g net_g x mean return of g:")
    for lab, a, b in ERAS:
        a, b = X.window(a, b)
        bb, tt = between.loc[a:b], tot.loc[a:b]
        print(f"  {lab:<26}{np.cov(bb, tt)[0, 1] / tt.var():7.1%}   group-spread P&L "
              f"{bb.mean() * 252 * 100:+.2f}%/yr of {tt.mean() * 252 * 100:+.2f}%/yr")


def sec_capacity(X: Base):
    hr(f"6. CAPACITY -- each trade against the name's 63-session ADV, at the spec's capital "
       f"${CAPITAL_USD:,.0f}")
    B = X.B
    a, b = X.live0, pd.Timestamp(FIT_END)
    dH = B.H.diff().loc[a:b]
    adv = X.adv.loc[a:b]
    part = (dH.abs() * CAPITAL_USD / adv).where(dH.abs() > 0)
    no_adv = int((dH.abs().gt(0) & adv.isna()).sum().sum())
    v = part.stack().dropna()
    notional = (dH.abs() * CAPITAL_USD).where(dH.abs() > 0).stack().reindex(v.index)
    order = v.sort_values()
    cw = notional.reindex(order.index).cumsum() / notional.sum()
    nw_med = float(order[cw >= 0.5].iloc[0])
    day_max = part.max(axis=1).dropna()
    print(f"name-trade days {len(v)}; with no ADV (not scored) {no_adv}; trade days {len(day_max)}")
    print(f"participation in 63-session ADV: median {v.median():.3%}  p90 {v.quantile(.9):.3%}  "
          f"p99 {v.quantile(.99):.3%}  max {v.max():.3%}  notional-weighted median {nw_med:.3%}")
    for thr in (0.01, 0.05, 0.10):
        print(f"  share of name-trades above {thr:.0%} of ADV: {(v > thr).mean():.2%}")
    med = day_max.median()
    print(f"each day's largest participation: median {med:.3%}, p90 {day_max.quantile(.9):.3%}")
    print("capital at which the MEDIAN day's largest trade reaches a share of ADV (linear in "
          "capital, and in the vol target at fixed capital):")
    for thr in (0.01, 0.05, 0.10):
        k = CAPITAL_USD * thr / med
        print(f"  {thr:>4.0%} of ADV: ${k / 1e6:,.2f}m at the {VOL_TARGET:.0%} target; capital x "
              f"vol target = ${k * VOL_TARGET / 1e6:,.3f}m-vol (so ${k * VOL_TARGET / VOL_CAP / 1e6:,.2f}m "
              f"at {VOL_CAP:.0%})")
    print("An MOC-only book trades in the closing cross, not the day: "
          "results/cef/EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md measured the\ncross at about 0.57% of "
          "the day's volume in these names (median, last 60 sessions to 2026-10-13) [doc, not "
          "re-run],\nso the same trades are roughly two orders of magnitude larger against the "
          "cross than against ADV.")


def _series(X: Base) -> dict:
    """The P&L variants the kill-probability section reads, live fit window."""
    B = X.B
    a, b = X.live0, pd.Timestamp(FIT_END)
    F = fee_history()
    idx = B.H.index
    p1 = borrow_charge(B.H, const_fee(idx, F.loc[:FIT_END].mean().to_dict()))
    p3 = borrow_charge(B.H, const_fee(idx, F.tail(RECENT).mean().to_dict()))
    for lab, c in (("P1", p1), ("P3", p3)):
        if c["covered_share"] < 1.0:
            raise ValueError(f"borrow proxy {lab} leaves {1 - c['covered_share']:.2%} of the short "
                             "book unpriced; a gap is not a zero")
    gross = B.pnl.loc[a:b]
    out = {
        "gross": gross,
        "net 15bp": net_series(B, 0.0 * B.pnl, 15.0).loc[a:b],
        "net 15bp + borrow P3 (fee level of the last 63 FEE_RATE dates)":
            net_series(B, p3["cost"], 15.0).loc[a:b],
        "net 15bp + borrow P1 (each name's 2021-09..2022 mean fee)":
            net_series(B, p1["cost"], 15.0).loc[a:b],
        "zero edge (gross, demeaned)": gross - gross.mean(),
    }
    for k, v in out.items():
        _assert_fit(v)
    return out


def sec_killprob(X: Base):
    hr(f"7. SURVIVAL -- P(max drawdown over {HORIZON} sessions >= the spec's lines), the book's own "
       "P&L rescaled to a vol")
    print(f"lines: risk.halve_drawdown {HALVE_DD:.0%}, risk.kill_drawdown {KILL_DD:.0%} (frozen spec, "
          f"fractions). Live fit window only. {BOOT_REPS:,} paths; seed {SEED}.")
    print("Methods (reported side by side, never averaged): SB21 / SB63 = stationary bootstrap, "
          "mean block 21 / 63 sessions;\nGAUSS = iid normal with the series' own mean and sd (what "
          "the fat tails add is the gap to SB21).")
    print("Rescaling keeps each series' Sharpe and changes only the book's size. The borrow "
          "proxies are counterfactual schedules (H4).")
    S = _series(X)
    rng = np.random.default_rng(SEED)
    n = len(next(iter(S.values())))
    idx21 = stationary_index(n, HORIZON, BOOT_REPS, 21, rng)
    idx63 = stationary_index(n, HORIZON, BOOT_REPS, 63, rng)
    gauss = rng.standard_normal((BOOT_REPS, HORIZON))
    methods = (("SB21", dict(idx=idx21)), ("SB63", dict(idx=idx63)), ("GAUSS", dict(gauss=gauss)))
    for name, s in S.items():
        x = s.values.astype(float)
        sr = x.mean() / x.std(ddof=1) * np.sqrt(252)
        print(f"\n{name}: Sharpe {sr:+.2f}, realised vol {x.std(ddof=1) * np.sqrt(252) * 100:.2f}%")
        print(f"  {'method':<7}" + "".join(f"{'P(DD>=' + f'{L:.0%}' + ')@' + f'{v:.0%}':>17}"
                                          for v in (VOL_TARGET, VOL_CAP) for L in (HALVE_DD, KILL_DD))
              + "".join(f"{'sig*(' + f'{L:.0%}' + ',' + f'{p:.0%}' + ')':>15}"
                        for L in (HALVE_DD, KILL_DD) for p in (0.05, 0.10)))
        for mlab, kw in methods:
            cells = [p_breach(x, v, L, **kw) for v in (VOL_TARGET, VOL_CAP) for L in (HALVE_DD, KILL_DD)]
            stars = [sigma_star(x, L, p, **kw) for L in (HALVE_DD, KILL_DD) for p in (0.05, 0.10)]
            print(f"  {mlab:<7}" + "".join(f"{c:17.1%}" for c in cells)
                  + "".join(f"{'none' if s is None else f'{s:.1%}':>15}" for s in stars))
    print("\nsig*(L, p) = the largest annualised vol at which P(max drawdown >= L within "
          f"{HORIZON} sessions) <= p. 'none' = no vol\nabove 0.1% meets it. The tolerance p is the "
          "team lead's to state (PORTFOLIO_FRAMEWORK §2.6); 5% and 10% are shown, not chosen.")


def sec_scenarios(X: Base):
    hr("8. STRESS REPLAYS -- the last fit-window book held through declared stress windows")
    B = X.B
    w_last = B.H.iloc[-1]
    g = w_last.abs().sum()
    w_cap = w_last * MAX_GROSS_STRESS / g
    print(f"book: H decided {X.idx[-1].date()} (gross {g:.2f}x, net {w_last.sum():+.3f}); the same "
          f"book scaled to the {MAX_GROSS_STRESS}x cap is the second column set.")
    print("Weights are held fixed through each window (no band, no vol scalar): today's book, no "
          "reaction. A name with no return\nthat day takes its group's mean that day (a labelled "
          "proxy, counted). Long-only = the shorts disappear (all recalled)\nand the longs are held: "
          "the loss if the hedge goes.")
    print(f"\n{'window':<26}{'proxied':>8}{'total%':>8}{'maxDD%':>8}{'worst d%':>9}"
          f"{'@cap DD%':>9}{'long-only DD%':>14}{'policy DD%':>11}")
    for lab, (a, b) in SCENARIOS.items():
        r = X.r_nan.loc[a:b]
        _assert_fit(r)
        rp, nprox = group_proxy(r, X.grp)
        pnl = (rp * w_last).sum(axis=1)
        pnl_cap = (rp * w_cap).sum(axis=1)
        longs = (rp * w_last.clip(lower=0)).sum(axis=1)
        tot = float((1 + pnl).prod() - 1)
        pol = B.pnl.loc[a:b]
        pol_dd = (f"{max_drawdown(pol)['mdd'] * 100:11.2f}" if pol.abs().sum() > 0
                  else f"{'flat':>11}")
        print(f"{lab:<26}{nprox:8d}{tot * 100:8.2f}{max_drawdown(pnl)['mdd'] * 100:8.2f}"
              f"{pnl.min() * 100:9.2f}{max_drawdown(pnl_cap)['mdd'] * 100:9.2f}"
              f"{max_drawdown(longs)['mdd'] * 100:14.2f}{pol_dd}")
    print("policy DD = the deployed policy's own realised drawdown in the window (evaluate(), "
          "with its band and vol scalar); 'flat' =\nthe ADV filter left the deployed book empty "
          "(before 2013-06): the 13-name book has never traded 2008.")

    # The group bet in a blow-out: worst 21-session move of the muni-minus-taxable spread
    grp = X.grp
    r = X.r_nan
    mun = r[[c for c in X.U if grp[c] == MUNI]].mean(axis=1)
    tax = r[[c for c in X.U if grp[c] != MUNI]].mean(axis=1)
    spread21 = (mun - tax).rolling(21).sum().dropna()
    _assert_fit(spread21)
    held = B.H.loc[X.live0:FIT_END]
    mnet = held[[c for c in X.U if grp[c] == MUNI]].sum(axis=1)
    print(f"\ngroup bet: worst 21-session muni-minus-taxable return spread, full fit history: "
          f"{spread21.min() * 100:+.2f}% (ending {spread21.idxmin().date()}); best "
          f"{spread21.max() * 100:+.2f}% (ending {spread21.idxmax().date()}).")
    print(f"the deployed book's net muni weight, live fit window: median |net| {mnet.abs().median():.3f}, "
          f"p95 {mnet.abs().quantile(.95):.3f}, max {mnet.abs().max():.3f} (multiples of capital).")
    worst = max(abs(spread21.min()), abs(spread21.max()))
    print(f"a p95 group net held through the worst spread move costs about "
          f"{mnet.abs().quantile(.95) * worst * 100:.2f}% of capital (first-order: net x spread).")


SECTIONS = {"book": sec_book, "sizing": sec_sizing, "tails": sec_tails, "factors": sec_factors,
            "breadth": sec_breadth, "capacity": sec_capacity, "killprob": sec_killprob,
            "scenarios": sec_scenarios}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want = argv or list(SECTIONS)
    bad = [w for w in want if w not in SECTIONS]
    if bad:
        raise SystemExit(f"unknown section(s) {bad}; choose from {list(SECTIONS)}")
    print(f"portfolio_baseline.py -- zero trials; fit window only (holdout from {HOLDOUT_START.date()} "
          "sealed)")
    X = Base()
    for w in want:
        SECTIONS[w](X)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
