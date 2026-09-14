"""Wrapper-pair reversion sleeve -- the D5 inventory play, built correctly.

WHAT CHANGED FROM v1. Two bugs made v1 meaningless and both are fixed here:

1. The forward spread return was computed as spread_{t+h} - spread_t, where the
   spread embeds a ROLLING hedge ratio. That differences two different betas, so
   it includes beta drift times the second leg -- a quantity nobody can earn. It
   made every pair look like momentum and made the Treasury control the strongest
   result in the table. The return is now
        (la_{t+h} - la_t) - beta_t * (lb_{t+h} - lb_t)
   with beta FIXED at the value known when the position was opened.

2. Dispersion was measured on a 252-day window of the spread LEVEL, which
   captures a year of composition drift rather than a dislocation, so the
   z-score collapsed and the band pinned to its floor while holding 80% of the
   time. The anchor is now a 21-day window.

THE EDGE, HONESTLY SIZED. After those fixes the per-pair signal is weak: mean
t = -1.17 at one day, 5 of 22 pairs individually significant, Treasury control
+0.12 with none. This is not a strong signal and is not presented as one.

It is a D5 sleeve -- inventory. The value is in combination: 22 pairs with mean
pairwise correlation of +0.014 are close to independent, and
    S_portfolio = S * sqrt(N / (1 + (N-1)*rho))
turns a set of ~0.2 Sharpe components into something materially better. That is
the whole thesis of this file, and if the realised correlation comes in much
above ~0.1 the thesis fails and the sleeve should be dropped.

NEUTRALITY. Every pair sits inside one asset class and is beta-hedged, so no leg
expresses a credit or duration view. Treasury pairs are measured as a control and
never traded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.ou.ou_band_sleeve import PAIRS, WIN, REV_WIN, load, rt_cost_bp  # noqa: E402

OUT = REPO / "results/ou"
OUT.mkdir(parents=True, exist_ok=True)

START = "2019-01-01"
ENTRY_Z = 1.5      # enter beyond this many sd of the 21d dislocation
EXIT_Z = 0.25      # exit once it has come most of the way back
MAX_W = 1.0


def pair_returns(a: str, b: str, cl, mid, adv):
    """Net return series for one pair, beta fixed at entry, measured costs."""
    idx = cl.index[(cl.index >= START) & cl[a].notna() & cl[b].notna()]
    if len(idx) < 600:
        return None
    la, lb = np.log(mid[a].reindex(idx)), np.log(mid[b].reindex(idx))
    beta = (la.rolling(WIN).cov(lb) / lb.rolling(WIN).var()).shift(1).clip(0.2, 3.0)
    spread = la - beta * lb
    mu = spread.rolling(REV_WIN).mean().shift(1)
    sd = spread.rolling(REV_WIN).std().shift(1)
    z = ((spread - mu) / sd.replace(0, np.nan)).clip(-6, 6)

    # band position: fade the dislocation
    pos, cur = [], 0.0
    for zi in z.values:
        if not np.isfinite(zi):
            pos.append(cur); continue
        if cur == 0.0:
            cur = -1.0 if zi >= ENTRY_Z else (1.0 if zi <= -ENTRY_Z else 0.0)
        elif abs(zi) <= EXIT_Z:
            cur = 0.0
        pos.append(cur)
    pos = pd.Series(pos, index=idx)

    held = pos.shift(1).fillna(0.0)                 # decided t-1, earns t
    beta_held = beta.shift(1).ffill()               # the beta we actually opened at
    ra = la.diff()
    rb = lb.diff()
    gross = held * (ra - beta_held * rb)            # fixed-beta spread return

    c_bp = rt_cost_bp(a, b, cl, adv)
    turn = held.diff().abs().fillna(0.0) * (1.0 + beta_held.abs())
    cost = turn * (c_bp / 2.0) / 1e4
    net = (gross - cost).replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame({"gross": gross, "net": net, "held": held,
                         "turn": turn}, index=idx).dropna()


def stats(s: pd.Series) -> dict:
    ann = np.sqrt(252)
    if s.std() == 0 or len(s) < 250:
        return {}
    return dict(n=len(s), sharpe=s.mean() / s.std() * ann,
                cagr=100 * ((1 + s).prod() ** (252 / len(s)) - 1),
                vol=100 * s.std() * ann,
                maxdd=100 * ((1 + s).cumprod() /
                             (1 + s).cumprod().cummax() - 1).min())


def main() -> int:
    cl, mid, adv = load()
    nets, grosses, rows = {}, {}, []
    for a, b, klass in PAIRS:
        if a not in cl.columns or b not in cl.columns:
            continue
        d = pair_returns(a, b, cl, mid, adv)
        if d is None or len(d) < 500:
            continue
        st = stats(d.net)
        if not st:
            continue
        gs = d.gross.mean() / d.gross.std() * np.sqrt(252)
        rows.append(dict(pair=f"{a}/{b}", klass=klass, gross_sr=gs,
                         trades=int((d.held.diff().abs() > 0).sum() / 2),
                         time_on=100 * (d.held != 0).mean(), **st))
        if klass != "UST_ctl":
            nets[f"{a}/{b}"] = d.net
            grosses[f"{a}/{b}"] = d.gross
    r = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    r.to_csv(OUT / "pair_sleeve_v2.csv", index=False)

    print("=" * 104)
    print(f"PAIR REVERSION SLEEVE v2   enter |z|>{ENTRY_Z}, exit |z|<{EXIT_Z}, "
          f"beta fixed at entry, measured costs")
    print("=" * 104)
    print(f"{'pair':<13}{'class':<9}{'n':>6}{'trades':>8}{'on%':>6}"
          f"{'gross SR':>10}{'net SR':>9}{'CAGR%':>8}{'vol%':>7}{'maxDD%':>8}")
    for _, x in r.iterrows():
        tag = "  <- CONTROL" if x.klass == "UST_ctl" else ""
        print(f"{x.pair:<13}{x.klass:<9}{x.n:>6,.0f}{x.trades:>8.0f}{x.time_on:>6.0f}"
              f"{x.gross_sr:>10.2f}{x.sharpe:>9.2f}{x.cagr:>8.2f}{x.vol:>7.2f}"
              f"{x.maxdd:>8.1f}{tag}")

    tr = r[r.klass != "UST_ctl"]; ct = r[r.klass == "UST_ctl"]
    print(f"\n  tradable : mean net SR {tr.sharpe.mean():+.2f}, "
          f"{int((tr.sharpe > 0).sum())}/{len(tr)} positive")
    print(f"  CONTROL  : mean net SR {ct.sharpe.mean():+.2f}, "
          f"{int((ct.sharpe > 0).sum())}/{len(ct)} positive   <- must be ~0")

    W = pd.DataFrame(nets).dropna(how="all")
    G = pd.DataFrame(grosses).dropna(how="all")
    # equal RISK weight, using only trailing information
    iv = 1.0 / W.rolling(126, min_periods=60).std().shift(1)
    iv = iv.div(iv.sum(axis=1), axis=0)
    combo = (W.fillna(0.0) * iv.fillna(0.0)).sum(axis=1)
    combo_g = (G.fillna(0.0) * iv.fillna(0.0)).sum(axis=1)
    cm = W.corr().values
    off = cm[~np.eye(len(cm), dtype=bool)]
    rho = float(np.nanmean(off))

    cs, gsx = stats(combo), stats(combo_g)
    print("\n" + "=" * 104)
    print(f"COMBINED, equal risk weight across {W.shape[1]} pairs")
    print("=" * 104)
    print(f"  mean pairwise correlation   {rho:+.3f}   (thesis needs this << 0.1)")
    print(f"  combined GROSS Sharpe       {gsx.get('sharpe', float('nan')):+.2f}")
    print(f"  combined NET Sharpe         {cs.get('sharpe', float('nan')):+.2f}")
    print(f"  combined vol                {cs.get('vol', float('nan')):.2f}%")
    print(f"  combined maxDD              {cs.get('maxdd', float('nan')):.1f}%")
    n = W.shape[1]; s_avg = tr.sharpe.mean()
    print(f"  theory S*sqrt(N/(1+(N-1)rho)) = "
          f"{s_avg*np.sqrt(n/(1+(n-1)*max(rho,0))):+.2f}")

    if cs and cs.get("vol", 0) > 0:
        for tgt in (12.0, 15.0):
            lev = tgt / cs["vol"]
            print(f"  vol-targeted to {tgt:.0f}%: leverage {lev:.1f}x -> "
                  f"CAGR {cs['cagr']*lev:+.1f}%, maxDD {cs['maxdd']*lev:.0f}%")
    pd.DataFrame({"combo_net": combo, "combo_gross": combo_g}).to_parquet(
        OUT / "combo_returns.parquet")
    W.to_parquet(OUT / "pair_net_returns.parquet")
    print(f"\nwrote {OUT/'pair_sleeve_v2.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
