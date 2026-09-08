"""When should a position be closed? Measured, not assumed.

THE QUESTION
------------
The sleeve has an entry rule (cross-sectional z) and, since 2026-09-06, a
rebalance rule (the no-trade band). It has NO exit rule. A position is closed
only as a side effect of its target weight decaying, which means the holding
period is whatever the signal happens to produce -- nobody chose it.

Bertram (2010) shows that for an OU spread under proportional cost the object to
maximise is EXPECTED RETURN PER UNIT TIME, not expected return. Those two have
different maxima: holding longer always accumulates more convergence, but the
rate falls, and capital tied up in a decayed position is capital not earning.
That trade-off has an interior optimum and it is directly measurable here.

WHAT THIS MEASURES
------------------
For every name-day whose signal is active, the forward cumulative return in the
direction of the trade over h = 1..60 business days, bucketed by entry |z|:

    R(h | z)    cumulative -- "how much do I make if I hold h days"
    R(h | z)/h  per unit time -- Bertram's objective; its argmax is the exit

Everything is measured on NON-OVERLAPPING entries within a name so the standard
errors mean something, and every return is a REAL forward price return, not a
discount change: what we earn is price, not NAV convergence.

NO LOOKAHEAD: z uses moments shifted one day; the forward window starts at t+2
(decide at t, MOC fill at t+1, so the first return we own is t+2).

Usage:  python3 scripts/cef/exit_study.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from band_frontier import UNIVERSE, Z_WINDOW, MIN_PERIODS      # noqa: E402

HORIZONS = [1, 2, 3, 5, 8, 10, 13, 15, 21, 26, 34, 42, 50, 60]
Z_BUCKETS = [(0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 4.0)]
FILL_LAG = 2          # decide t, fill t+1 close, first owned return t+2


def panel():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    P, N = P[P.ticker.isin(UNIVERSE)], N[N.ticker.isin(UNIVERSE)]
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    piv = lambda c: d.pivot_table(index="date", columns="ticker", values=c).sort_index()
    px, nav = piv("close"), piv("nav")
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    return px, disc, ret, z


def forward(ret, z, lo, hi, hmax):
    """Non-overlapping signed forward returns keyed by horizon.

    Signed by the trade direction: z>0 is rich -> short, so the trade return is
    -sign(z) * cumulative return. A positive number means the trade made money.
    """
    logr = np.log1p(ret.fillna(0.0))
    out = {h: [] for h in HORIZONS}
    for t in ret.columns:
        s, lr = z[t], logr[t].to_numpy()
        idx = np.where(s.abs().between(lo, hi).to_numpy())[0]
        used_to = -1
        for i in idx:
            if i <= used_to or i + FILL_LAG + hmax >= len(lr):
                continue
            sgn = -np.sign(s.iloc[i])
            a = i + FILL_LAG
            for h in HORIZONS:
                out[h].append(sgn * float(np.expm1(lr[a:a + h].sum())))
            used_to = i + FILL_LAG + hmax          # non-overlapping
    return out


def main() -> int:
    px, disc, ret, z = panel()
    hmax = max(HORIZONS)
    print(f"panel {ret.index[0].date()} -> {ret.index[-1].date()}, "
          f"{len(ret)} sessions, {len(UNIVERSE)} names")
    print("signed forward returns, non-overlapping, fill lag "
          f"{FILL_LAG}d (decide t, fill t+1, own t+2)\n")

    best = {}
    for lo, hi in Z_BUCKETS:
        fw = forward(ret, z, lo, hi, hmax)
        n = len(fw[HORIZONS[0]])
        if n < 40:
            print(f"|z| in [{lo},{hi}): only {n} non-overlapping entries -- skipped\n")
            continue
        print(f"ENTRY |z| in [{lo}, {hi})   n = {n} non-overlapping entries")
        print(f"  {'h':>4}{'cum bp':>9}{'t':>7}{'bp/day':>9}{'ann %':>8}{'hit %':>7}")
        rows = []
        for h in HORIZONS:
            a = np.array(fw[h], float)
            a = a[np.isfinite(a)]
            m = a.mean() * 1e4
            t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if a.std(ddof=1) > 0 else np.nan
            per = m / h
            ann = (a.mean() / h) * 252 * 100
            hit = 100.0 * (a > 0).mean()
            rows.append((h, m, t, per, ann, hit))
            print(f"  {h:>4}{m:>9.1f}{t:>7.2f}{per:>9.2f}{ann:>8.1f}{hit:>7.1f}")
        # Bertram: the exit is the argmax of return PER UNIT TIME
        star = max(rows, key=lambda r: r[3])
        peak = max(rows, key=lambda r: r[1])
        best[(lo, hi)] = star
        print(f"  -> max bp/DAY at h = {star[0]}d ({star[3]:.2f} bp/day, "
              f"{star[4]:.1f}%/yr ann)")
        print(f"  -> max CUMULATIVE at h = {peak[0]}d ({peak[1]:.1f} bp) "
              f"-- holding to here earns more in total but less per day\n")

    if best:
        print("=" * 62)
        print("OPTIMAL HOLD BY CONVICTION (argmax of return per unit time)")
        print("=" * 62)
        print(f"  {'entry |z|':>12}{'hold (d)':>10}{'bp/day':>9}{'ann %':>8}")
        for (lo, hi), s in sorted(best.items()):
            print(f"  {f'[{lo},{hi})':>12}{s[0]:>10}{s[3]:>9.2f}{s[4]:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
