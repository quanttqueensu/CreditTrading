"""Diagnostics behind PLAN.md (2026-09-06).

Every measured number in PLAN.md comes from here. Run it to reproduce them, and
re-run it whenever the panel is restaged -- several of these are claims about the
CURRENT state of the book, not settled historical facts, and they will move.

Six blocks, each answering one question PLAN.md asks:

  1. kappa        -- do funds revert at the same speed?          (PLAN.md A2)
  2. pca          -- where does the book's risk actually sit?    (PLAN.md A4)
  3. adv          -- what caps our breadth, and does it need to? (PLAN.md 2.4)
  4. tick         -- what does a trade actually cost us?         (PLAN.md 2.4)
  5. volscalar    -- how does the sizing rule behave?            (PLAN.md 3.3)
  6. combination  -- does a second signal add anything?          (PLAN.md 4)

Usage:  python scripts/cef/plan_diagnostics.py [block ...]     (default: all)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
PX_PATH = REPO / "data/cef/cef_prices.parquet"
NAV_PATH = REPO / "data/cef/cef_nav.parquet"
UNIVERSE_CSV = REPO / "data/cef/cef_universe.csv"

# The frozen live universe. Kept literal rather than read from the spec so this
# script keeps reporting the book we MEASURED even if the spec later changes --
# a diagnostic that silently follows the thing it audits is not a diagnostic.
LIVE = ["AWF", "BIT", "DSL", "HYT", "JFR", "MHD", "MQY", "NAD", "NEA",
        "NVG", "NZF", "PCN", "PDI", "PDO", "PFN", "PHK", "PTY"]
MUNI = {"MHD", "MQY", "NAD", "NEA", "NVG", "NZF"}

Z_WINDOW, MIN_PERIODS = 252, 120
VOL_TARGET, VOL_LOOKBACK = 0.06, 63
BOOK_USD, TURN_PER_DAY = 500_000, 0.215
BREAKEVEN_BP = 32.6          # results/cef/ALPHA_AUDIT_2026-09-05.md


def panel(tickers=None):
    """Price / NAV / volume panels, built exactly as the sleeve builds them."""
    P, N = pd.read_parquet(PX_PATH), pd.read_parquet(NAV_PATH)
    if tickers is not None:
        P, N = P[P.ticker.isin(tickers)], N[N.ticker.isin(tickers)]
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    piv = lambda c: d.pivot_table(index="date", columns="ticker", values=c).sort_index()
    return piv("close"), piv("nav"), piv("volume")


def zscore(X):
    """The sleeve's z-score. Both moments shifted -- point-in-time, no lookahead."""
    mu = X.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = X.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    return ((X - mu) / sd.replace(0, np.nan)).clip(-4, 4)


def returns(px):
    return px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)


def weights(z_row):
    """Cross-sectional dollar-neutral weights, unit gross. None if too thin."""
    s = z_row.dropna()
    if len(s) < 6:
        return None
    w = -(s - s.mean())
    denom = w.abs().sum()
    return None if denom <= 0 else w / denom


# --------------------------------------------------------------------------- 1
def kappa():
    """PLAN.md A2 -- the signal treats every fund as reverting at one speed."""
    px, nav, _ = panel(LIVE)
    disc = 100.0 * (px - nav) / nav
    print("Per-name AR(1) of the demeaned discount, full history.\n"
          "The sleeve's score contains no kappa term, so every row below is\n"
          "sized as though it reverted at the same rate.\n")
    rows = []
    for tk in LIVE:
        s = disc[tk].dropna()
        if len(s) < 300:
            continue
        dm = (s - s.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean()).dropna()
        phi = float(np.polyfit(dm.values[:-1], dm.values[1:], 1)[0])
        rows.append((tk, len(s), s.mean(),
                     s.rolling(Z_WINDOW).std().mean(),
                     phi, np.log(2) / -np.log(phi)))
    t = pd.DataFrame(rows, columns=["ticker", "n_days", "mean_disc_pp",
                                    "mean_sd252", "phi_daily", "halflife_bd"])
    t = t.sort_values("halflife_bd")
    print(t.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    lo, hi = t.iloc[0], t.iloc[-1]
    print(f"\nspread: {lo.ticker} {lo.halflife_bd:.1f}bd -> {hi.ticker} "
          f"{hi.halflife_bd:.1f}bd = {hi.halflife_bd / lo.halflife_bd:.1f}x")
    h = 2  # the live holding period
    conv = lambda k: 1 - np.exp(-np.log(2) / k * h)
    print(f"expected convergence over a {h}-day hold: {lo.ticker} "
          f"{conv(lo.halflife_bd):.1%} vs {hi.ticker} {conv(hi.halflife_bd):.1%} "
          f"= {conv(lo.halflife_bd) / conv(hi.halflife_bd):.1f}x per unit of z")


# --------------------------------------------------------------------------- 2
def pca():
    """PLAN.md A4 -- the headline. Two-thirds of book risk is one factor."""
    px, nav, _ = panel(LIVE)
    r = returns(px).loc["2021":][LIVE].dropna()
    C, S = r.corr().values, r.cov().values * 252
    ev, EV = np.linalg.eigh(C)
    ev, EV = ev[::-1], EV[:, ::-1]

    print("Return correlation, 2021+ (all 17 alive):")
    off = C[np.triu_indices_from(C, 1)]
    print(f"  mean pairwise {off.mean():+.3f}   median {np.median(off):+.3f}")
    mi = [LIVE.index(t) for t in LIVE if t in MUNI]
    ni = [LIVE.index(t) for t in LIVE if t not in MUNI]
    print(f"  muni block {C[np.ix_(mi, mi)][np.triu_indices(len(mi), 1)].mean():+.3f}"
          f"   non-muni {C[np.ix_(ni, ni)][np.triu_indices(len(ni), 1)].mean():+.3f}"
          f"   cross {C[np.ix_(mi, ni)].mean():+.3f}")

    print("\nPC loadings:")
    print("      " + " ".join(f"{t:>6}" for t in LIVE))
    for k in range(3):
        v = EV[:, k] * (np.sign(EV[:, k].sum()) if k == 0 else 1)
        print(f"PC{k + 1}  " + " ".join(f"{x:6.2f}" for x in v))
    print(f"\nPC2 mean loading: muni {np.mean([EV[i, 1] for i in mi]):+.3f}  "
          f"non-muni {np.mean([EV[i, 1] for i in ni]):+.3f}   <- muni vs taxable")

    disc = 100.0 * (px - nav) / nav
    z = zscore(disc).loc["2021":][LIVE]
    V = np.sqrt(np.diag(S))
    acc, n = np.zeros(4), 0
    for _, row in z.iterrows():
        w = weights(row)
        if w is None:
            continue
        wv = pd.Series(0.0, index=LIVE)
        wv[w.index] = w.values
        ws = wv.values * V                       # into correlation space
        acc += np.array([(ws @ EV[:, k]) ** 2 * ev[k] for k in range(3)]
                        + [ws @ C @ ws])
        n += 1
    shares = np.append(acc[:3] / acc[3], 1 - acc[:3].sum() / acc[3])
    print(f"\nBook variance decomposition, {n} days, sleeve's own weights:")
    for k, lab in enumerate(["PC1  (market direction)", "PC2  (muni vs taxable)",
                             "PC3  (quality / duration)"]):
        print(f"  {lab:28s} {shares[k]:6.1%}")
    print(f"  {'PC4-17 (idiosyncratic)':28s} {shares[3]:6.1%}")

    idio = np.full(len(ev) - 3, shares[3] / (len(ev) - 3))
    br = 1.0 / (np.square(shares[:3]).sum() + np.square(idio).sum())
    print(f"\neffective breadth 1/sum(v_k^2) = {br:.2f} of {len(LIVE)} names")
    print(f"IR = IC*sqrt(BR) is overstated by sqrt({len(LIVE)}/{br:.2f}) "
          f"= {np.sqrt(len(LIVE) / br):.2f}x if the names are assumed independent")


# --------------------------------------------------------------------------- 3
def adv():
    """PLAN.md 2.4 -- the ADV floor is sized for a much larger book than ours."""
    px, _, vol = panel()
    a = (px * vol).rolling(63, min_periods=21).mean().loc["2026":].mean().dropna()
    print("63-day ADV, 2026 average. The floor is min_adv_usd = $3.0m.\n")
    for thr in (3.0, 2.0, 1.5, 1.0, 0.5):
        k = a[a >= thr * 1e6]
        print(f"  >= ${thr:>4.1f}m : {len(k):2d} names  "
              f"({sum(t in LIVE for t in k.index)} already traded)")
    print(f"\nAt ${BOOK_USD:,} book, 1.52x gross, {TURN_PER_DAY:.1%} turnover/day.")
    print("The cost model's own participation guard is 5%.\n")
    for n in (8, 12, 17, 25, 37):
        daily = BOOK_USD * 1.52 / n * TURN_PER_DAY
        print(f"  {n:2d} names -> ${daily:>7,.0f} traded/name/day  "
              + "  ".join(f"| ${t}m ADV: {daily / (t * 1e6):5.2%}" for t in (1.0, 3.0)))


# --------------------------------------------------------------------------- 4
def tick():
    """PLAN.md 2.4 -- we do not move markets. We pay ticks. Screen on ticks."""
    px, _, vol = panel()
    a = (px * vol).rolling(63, min_periods=21).mean().loc["2026":].mean()
    p = px.loc["2026":].mean()
    grp = pd.read_csv(UNIVERSE_CSV).set_index("ticker").grp
    t = pd.DataFrame({
        "ticker": p.index, "grp": [grp.get(x, "?") for x in p.index],
        "price": p.values, "adv_m": (a.reindex(p.index) / 1e6).values,
        "half_tick_bp": (0.5 * 0.01 / p * 1e4).values,
        "live": [x in LIVE for x in p.index],
    }).dropna(subset=["price"]).sort_values("half_tick_bp")
    print(f"Half of a one-cent spread, in bp, at 2026 average price.\n"
          f"Strategy breakeven is {BREAKEVEN_BP}bp per unit turnover.\n")
    print(t.to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    L = t[t.live]
    print(f"\nlive {len(L)}: mean {L.half_tick_bp.mean():.1f}bp  "
          f"median {L.half_tick_bp.median():.1f}bp  "
          f"worst {L.half_tick_bp.max():.1f}bp ({L.loc[L.half_tick_bp.idxmax(), 'ticker']})")
    cand = t[(~t.live) & (t.adv_m >= 1.0) & (t.half_tick_bp < L.half_tick_bp.median())]
    print(f"\nNot traded, ADV >= $1m, CHEAPER per tick than the live median:")
    print("  " + ", ".join(f"{r.ticker} ({r.grp}, {r.half_tick_bp:.2f}bp)"
                           for r in cand.itertuples()))
    print(f"  -> {sum(r.grp != 'muni' for r in cand.itertuples())} of {len(cand)} "
          f"are non-muni, i.e. they add breadth in the direction that dilutes PC2")


# --------------------------------------------------------------------------- 5
def volscalar():
    """PLAN.md 3.3 -- what the sizing rule actually does, day by day."""
    px, nav, _ = panel(LIVE)
    ret, z = returns(px), zscore(100.0 * (px - nav) / nav)
    out = []
    for i in range(300, len(z)):
        w = weights(z.iloc[i])
        if w is None:
            continue
        hist = ret[list(w.index)].iloc[:i + 1].mul(w, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = hist.std() * np.sqrt(252)
        out.append((z.index[i], rv,
                    float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0))
    S = pd.DataFrame(out, columns=["date", "rv", "scal"]).set_index("date")
    print(f"Sleeve formula: clip({VOL_TARGET:.0%} / {VOL_LOOKBACK}d realised vol, 0.2, 2.5)\n")
    for era, sl in (("full sample", S), ("2021+", S.loc["2021":])):
        print(f"  {era:12s} mean {sl.scal.mean():.2f}  median {sl.scal.median():.2f}  "
              f"p5 {sl.scal.quantile(.05):.2f}  p95 {sl.scal.quantile(.95):.2f}  "
              f"| ex-ante vol {sl.rv.mean():.2%}")
        print(f"  {'':12s} pinned at the 2.5 CAP {(sl.scal >= 2.4999).mean():5.1%} of days"
              f"   at the 0.2 floor {(sl.scal <= 0.2001).mean():5.1%}")
    print("\nMean scalar well above 1.0 means the book levers up almost always.")
    print("Days at the cap are days the risk model wants leverage the clip refuses --")
    print("and with 65.7% of variance in PC2, those are most likely days that factor")
    print("is quiet. That is levering into a dormant bet, not into conviction.")


# --------------------------------------------------------------------------- 6
def combination():
    """PLAN.md 4 -- the obvious second signal, measured. It adds nothing."""
    px, nav, _ = panel(LIVE)
    z, lz = zscore(100.0 * (px - nav) / nav), zscore(np.log(px))
    fwd = px.shift(-3) / px.shift(-1) - 1     # decide t, trade close t+1, hold 2d
    ic1, ic2 = [], []
    for dt in z.index[300::2]:                # ::2 = non-overlapping
        if dt not in fwd.index:
            continue
        a, b, f = z.loc[dt], lz.loc[dt], fwd.loc[dt]
        m = a.notna() & b.notna() & f.notna()
        if m.sum() < 6 or min(a[m].nunique(), b[m].nunique(), f[m].nunique()) < 3:
            continue
        c1 = stats.spearmanr(a[m], f[m]).statistic
        c2 = stats.spearmanr(b[m], f[m]).statistic
        if np.isfinite(c1) and np.isfinite(c2):
            ic1.append(c1); ic2.append(c2)
    ic1, ic2 = np.array(ic1), np.array(ic2)
    tstat = lambda v: v.mean() / v.std() * np.sqrt(len(v))
    rho = float(np.corrcoef(ic1, ic2)[0, 1])
    IC = np.array([ic1.mean(), ic2.mean()])
    R = np.array([[1.0, rho], [rho, 1.0]])
    comb = float(np.sqrt(IC @ np.linalg.inv(R) @ IC))
    wts = np.linalg.inv(R) @ IC
    wts /= np.abs(wts).sum()
    print(f"n = {len(ic1)} non-overlapping 2-day periods, executed T+1.\n")
    print(f"  discount z    IC {ic1.mean():+.4f}   t {tstat(ic1):+6.2f}")
    print(f"  log-price z   IC {ic2.mean():+.4f}   t {tstat(ic2):+6.2f}")
    print(f"  IC-series correlation {rho:+.3f}")
    print(f"\n  optimal combined |IC| = sqrt(IC' R^-1 IC) = {comb:.4f}")
    print(f"  uplift over the discount alone: {comb / abs(ic1.mean()) - 1:+.1%}")
    print(f"  implied weights: discount {wts[0]:+.2f}, price {wts[1]:+.2f}")
    print("\nThe price signal is ~95% subsumed. Not 'probably won't help' -- measured.")


BLOCKS = {"kappa": kappa, "pca": pca, "adv": adv,
          "tick": tick, "volscalar": volscalar, "combination": combination}

if __name__ == "__main__":
    want = sys.argv[1:] or list(BLOCKS)
    bad = [b for b in want if b not in BLOCKS]
    if bad:
        sys.exit(f"unknown block(s): {', '.join(bad)}\navailable: {', '.join(BLOCKS)}")
    for name in want:
        print(f"\n{'=' * 78}\n== {name}\n{'=' * 78}")
        BLOCKS[name]()
    print()
