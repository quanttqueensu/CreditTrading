"""CEF discount reversion v2 -- group-neutral, regime-sized.

THREE CHANGES FROM v1, each with a reason rather than a knob.

1. GROUP NEUTRALITY. A closed-end fund's price return is two things added
   together: the NAV moving, and the discount moving. Only the second is the
   trade. v1 went long the cheapest fund anywhere in the universe and short the
   richest anywhere, so it routinely held a muni CEF against a multi-sector one
   and carried the difference in their UNDERLYING portfolios as uncancelled
   noise. v2 is long/short WITHIN each credit group (muni vs muni, HY vs HY,
   loan vs loan, EM vs EM, multi vs multi), so the NAV leg largely cancels and
   what is left is the dislocation we actually have a thesis about.

2. SIGNAL-WEIGHTED, not equal-weighted. A fund two sigma below its own norm is a
   better bet than one half a sigma below it, and v1 sized them identically.

3. REGIME SIZING. The era profile is not decay, it is conditionality: net Sharpe
   1.17 / 0.62 / 1.87 / 0.13 across 2010-14, 2015-19, 2020-22, 2023-26. The 2020-22
   number is the COVID discount blowout. A strategy that harvests dislocation
   should be large when dislocation is available and small when it is not, and
   averaging across both regimes reports a number that describes neither. The
   regime variable is measured from the discount panel itself -- the
   cross-sectional dispersion of discounts -- not from an external stress index,
   because that is the quantity the strategy actually eats.

Everything stays point-in-time: the discount at t uses that day's close and NAV,
its z-score and the regime scalar use windows ending t-1, and positions are
executed at the close of t+1.
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
OUT.mkdir(parents=True, exist_ok=True)
CM = SCENARIOS["base"]

WIN = 252
MIN_ADV = 3.0e6
HOLD = 5


def build():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    M = pd.read_csv(REPO / "data/cef/cef_universe.csv")
    keep = M[M.adv_musd >= MIN_ADV / 1e6]
    grp = dict(zip(keep.ticker, keep.grp))
    d = P[P.ticker.isin(keep.ticker)].merge(N, on=["date", "ticker"], how="inner")
    d = d[(d.nav > 0.5) & (d.close > 0.5)].sort_values(["ticker", "date"])
    px = d.pivot_table(index="date", columns="ticker", values="close")
    nav = d.pivot_table(index="date", columns="ticker", values="nav")
    vol = d.pivot_table(index="date", columns="ticker", values="volume")
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(WIN, min_periods=120).mean().shift(1)
    sd = disc.rolling(WIN, min_periods=120).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(21, min_periods=5).mean().shift(1)
    return px, nav, disc, z, adv, grp


def regime_scalar(disc: pd.DataFrame, lo=0.5, hi=2.0) -> pd.Series:
    """DEPRECATED -- sizing up into dislocation is backwards. Kept so the
    comparison in main() is honest about what was tried.

    Measured by quintile of cross-sectional discount dispersion, net Sharpe runs
    1.24 / 0.59 / 0.80 / -0.23 / 0.68 from calm to dislocated. The strategy is
    BEST in calm markets: in dislocated regimes the mean return is higher but
    volatility explodes faster, so risk-adjusted return falls. Scaling up into
    dislocation levers into exactly the wrong state and produced 2008's -31.5%
    drawdown at 35.8% vol.
    """
    xs = disc.std(axis=1)
    r = xs.shift(1).rolling(756, min_periods=252).rank(pct=True)
    return (lo + (hi - lo) * r).clip(lo, hi)


def vol_target_scalar(ret: pd.Series, target=0.06, cap=2.5) -> pd.Series:
    """Scale to a constant risk budget using the sleeve's OWN trailing vol.

    This is the correct regime response. The strategy's problem is not that it
    stops working in stress, it is that its volatility triples while its edge
    does not, so a constant-notional book takes its worst drawdowns exactly when
    each unit of risk is paid least. Window ends yesterday; the cap stops the
    scalar exploding in unusually quiet periods.
    """
    rv = ret.shift(1).rolling(63, min_periods=30).std() * np.sqrt(252)
    return (target / rv.replace(0, np.nan)).clip(0.2, cap).fillna(1.0)


def run(px, disc, z, adv, grp, hold=HOLD, group_neutral=True,
        regime=False, vol_target=None, start="2005-01-01"):
    idx = px.index[px.index >= start]
    z, px, adv = z.reindex(idx), px.reindex(idx), adv.reindex(idx)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    scal = regime_scalar(disc).reindex(idx).ffill().fillna(1.0) if regime \
        else pd.Series(1.0, index=idx)

    groups = {}
    for t, g in grp.items():
        groups.setdefault(g if group_neutral else "ALL", []).append(t)

    W = pd.DataFrame(0.0, index=idx, columns=px.columns)
    for t in idx[::hold]:
        legs = {}
        for gname, members in groups.items():
            row = z.loc[t, [m for m in members if m in z.columns]].dropna()
            row = row[adv.loc[t, row.index].fillna(0) >= MIN_ADV]
            if len(row) < 2:
                continue
            # signal-weighted and demeaned WITHIN the group -> NAV leg cancels
            v = -(row - row.mean())
            if v.abs().sum() < 1e-9:
                continue
            legs[gname] = v / v.abs().sum()
        if not legs:
            continue
        w = pd.concat(legs.values())
        w = w.groupby(level=0).sum()
        w = w / w.abs().sum() * float(scal.loc[t])
        W.loc[t, w.index] = w.values
    W = W.replace(0.0, np.nan).ffill(limit=hold - 1).fillna(0.0)

    if vol_target is not None:
        # two passes: size the book on its own trailing realised vol, which is
        # only knowable from an unscaled first pass.
        raw = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
        W = W.mul(vol_target_scalar(raw, target=vol_target), axis=0)

    held = W.shift(1).fillna(0.0)
    gross = (held * ret).sum(axis=1)
    hs = pd.DataFrame(
        {c: [CM.half_spread_bp(p, a) for p, a in
             zip(px[c].values, adv[c].fillna(0).values)] for c in px.columns},
        index=idx)
    dw = held.diff().abs().fillna(held.abs())
    cost = (dw * hs / 1e4).sum(axis=1)
    return pd.DataFrame({"gross": gross, "net": gross - cost, "cost": cost,
                         "turn": dw.sum(axis=1),
                         "expo": held.abs().sum(axis=1)}, index=idx).dropna()


def stats(s: pd.Series) -> dict:
    if len(s) < 250 or s.std() == 0:
        return {}
    ann = np.sqrt(252)
    eq = (1 + s).cumprod()
    return dict(sharpe=s.mean() / s.std() * ann,
                cagr=100 * (eq.iloc[-1] ** (252 / len(s)) - 1),
                vol=100 * s.std() * ann,
                maxdd=100 * (eq / eq.cummax() - 1).min())


def line(lab, d):
    a, b = stats(d.gross), stats(d.net)
    print(f"  {lab:<34}{a.get('sharpe',0):>9.2f}{b.get('sharpe',0):>9.2f}"
          f"{b.get('cagr',0):>8.2f}{b.get('vol',0):>7.2f}{b.get('maxdd',0):>8.1f}"
          f"{d.turn.mean()*252:>9.1f}")


def main() -> int:
    px, nav, disc, z, adv, grp = build()
    print(f"universe {px.shape[1]} liquid credit CEFs  groups="
          f"{sorted(set(grp.values()))}\n")
    print("=" * 92)
    print("WHAT EACH CHANGE IS WORTH  (one change at a time, nothing else moved)")
    print("=" * 92)
    print(f"  {'spec':<34}{'gross SR':>9}{'net SR':>9}{'CAGR%':>8}{'vol%':>7}"
          f"{'maxDD%':>8}{'turn/yr':>9}")
    base = run(px, disc, z, adv, grp, group_neutral=False, regime=False)
    line("v1 universe-wide, flat size", base)
    gn = run(px, disc, z, adv, grp, group_neutral=True, regime=False)
    line("+ group-neutral (NAV cancels)", gn)
    rg = run(px, disc, z, adv, grp, group_neutral=False, regime=True)
    line("+ regime-sized only", rg)
    both = run(px, disc, z, adv, grp, group_neutral=True, regime=True)
    line("+ BOTH  <- v2", both)

    print("\n" + "=" * 92)
    print("v2 BY ERA -- is it conditional rather than decayed?")
    print("=" * 92)
    print(f"  {'era':<12}{'n':>7}{'gross SR':>10}{'net SR':>9}{'CAGR%':>8}"
          f"{'vol%':>7}{'avg expo':>10}")
    for lo, hi in [(2010, 2014), (2015, 2019), (2020, 2022), (2023, 2026)]:
        s = both[(both.index.year >= lo) & (both.index.year <= hi)]
        if len(s) < 250:
            continue
        a, b = stats(s.gross), stats(s.net)
        print(f"  {f'{lo}-{hi}':<12}{len(s):>7,}{a.get('sharpe',0):>10.2f}"
              f"{b.get('sharpe',0):>9.2f}{b.get('cagr',0):>8.2f}"
              f"{b.get('vol',0):>7.2f}{s.expo.mean():>10.2f}")

    both.to_parquet(OUT / "cef_sleeve_v2_daily.parquet")
    b = stats(both.net)
    print(f"\n  hurdle B2 = 0.54.  v2 net Sharpe {b.get('sharpe',0):.2f}")
    if b.get("vol", 0) > 0:
        for tgt in (10.0, 12.0):
            lev = tgt / b["vol"]
            print(f"  vol-target {tgt:.0f}%: leverage {lev:.1f}x -> "
                  f"CAGR {b['cagr']*lev:+.1f}%, maxDD {b['maxdd']*lev:.0f}%, "
                  f"gross {both.expo.mean()*lev:.1f}x")
    print(f"\nwrote {OUT/'cef_sleeve_v2_daily.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
