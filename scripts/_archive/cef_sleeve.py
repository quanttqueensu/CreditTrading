"""Credit CEF discount reversion -- the tradable, market-neutral sleeve.

CONSTRUCTION. Buying cheap closed-end funds and holding them is a well-known value
trade, and it is mostly credit beta plus yield -- exactly the carry the mandate
forbids. So this is strictly CROSS-SECTIONAL: every day, rank the credit CEF
universe by how cheap each fund is against its OWN discount history, go long the
cheapest and short the richest in equal dollars. The book is dollar-neutral by
construction, so a market-wide move in credit cancels and what is left is the
relative dislocation.

WHY THE Z-SCORE IS AGAINST THE FUND'S OWN HISTORY, not the cross-section. A muni
CEF structurally trades at a wider discount than a multi-sector one -- levered,
different buyer base, different fee. Ranking on raw discount would just be a
permanent long-muni/short-multisector bet, i.e. a static tilt wearing a signal's
clothes. Ranking on each fund's deviation from its OWN norm removes that.

COSTS ARE THE REAL RISK HERE. CEFs trade at $3-16, so one cent of spread is 6-30bp
-- an order of magnitude worse than HYG's 0.63bp. A four-legged round trip can
cost 40bp+. Costs are therefore charged off each fund's own price using the tick
model, never a flat assumption, and the sleeve is only interesting if it clears
them with room.

POINT-IN-TIME throughout: the discount at t uses the close and NAV of t, its
z-score uses a window ending t-1, and the position is executed at the close of
t+1. The signal's own price never appears in the return it is predicting.
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

WIN = 252          # window each fund's discount is z-scored against
MIN_ADV = 3.0e6    # tradable at a $640k book
HOLD = 5           # rebalance cadence in trading days
N_SIDE = 4         # funds long and short each side


def build():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    M = pd.read_csv(REPO / "data/cef/cef_universe.csv")
    keep = set(M[M.adv_musd >= MIN_ADV / 1e6].ticker)
    d = P[P.ticker.isin(keep)].merge(N, on=["date", "ticker"], how="inner")
    d = d[(d.nav > 0.5) & (d.close > 0.5)].sort_values(["ticker", "date"])

    px = d.pivot_table(index="date", columns="ticker", values="close")
    nav = d.pivot_table(index="date", columns="ticker", values="nav")
    vol = d.pivot_table(index="date", columns="ticker", values="volume")
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(WIN, min_periods=120).mean().shift(1)
    sd = disc.rolling(WIN, min_periods=120).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-5, 5)
    adv = (px * vol).rolling(21, min_periods=5).mean().shift(1)
    return px, nav, z, adv


def run(px, z, adv, hold=HOLD, n_side=N_SIDE, start="2005-01-01"):
    idx = px.index[px.index >= start]
    z, px, adv = z.reindex(idx), px.reindex(idx), adv.reindex(idx)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)

    # rebalance every `hold` days; between rebalances the book is held
    W = pd.DataFrame(0.0, index=idx, columns=px.columns)
    reb = idx[::hold]
    for t in reb:
        row = z.loc[t].dropna()
        row = row[adv.loc[t, row.index].fillna(0) >= MIN_ADV]
        if len(row) < 2 * n_side:
            continue
        cheap = row.nsmallest(n_side).index      # most below its own norm
        rich = row.nlargest(n_side).index
        W.loc[t, cheap] = 0.5 / n_side
        W.loc[t, rich] = -0.5 / n_side
    W = W.replace(0.0, np.nan).ffill(limit=hold - 1).fillna(0.0)

    held = W.shift(1).fillna(0.0)                 # executed at the close of t+1
    gross = (held * ret).sum(axis=1)

    # cost from each fund's own price -- a penny on a $4 CEF is not a penny on HYG
    hs = pd.DataFrame(
        {c: [CM.half_spread_bp(p, a) for p, a in
             zip(px[c].values, adv[c].fillna(0).values)] for c in px.columns},
        index=idx)
    dw = held.diff().abs().fillna(held.abs())
    cost = (dw * hs / 1e4).sum(axis=1)
    net = gross - cost
    return pd.DataFrame({"gross": gross, "net": net, "cost": cost,
                         "turn": dw.sum(axis=1),
                         "n_pos": (held != 0).sum(axis=1)}, index=idx).dropna()


def stats(s: pd.Series) -> dict:
    if len(s) < 250 or s.std() == 0:
        return {}
    ann = np.sqrt(252)
    eq = (1 + s).cumprod()
    return dict(n=len(s), sharpe=s.mean() / s.std() * ann,
                cagr=100 * (eq.iloc[-1] ** (252 / len(s)) - 1),
                vol=100 * s.std() * ann,
                maxdd=100 * (eq / eq.cummax() - 1).min())


def main() -> int:
    px, nav, z, adv = build()
    print(f"universe {px.shape[1]} liquid credit CEFs, "
          f"{px.index.min().date()} -> {px.index.max().date()}\n")
    d = run(px, z, adv)
    gs, ns = stats(d.gross), stats(d.net)
    print("=" * 88)
    print(f"CREDIT CEF DISCOUNT REVERSION -- long {N_SIDE} cheapest / short "
          f"{N_SIDE} richest, {HOLD}d hold")
    print("=" * 88)
    print(f"  {'':16}{'GROSS':>10}{'NET':>10}")
    for k, lab in [("sharpe", "Sharpe"), ("cagr", "CAGR %"),
                   ("vol", "vol %"), ("maxdd", "maxDD %")]:
        print(f"  {lab:<16}{gs.get(k, float('nan')):>10.2f}{ns.get(k, float('nan')):>10.2f}")
    print(f"  {'turnover/yr':<16}{d.turn.mean()*252:>20.1f}")
    print(f"  {'cost bp/yr':<16}{1e4*d.cost.mean()*252:>20.0f}")
    print(f"  {'cost/gross':<16}{d.cost.sum()/abs(d.gross).sum():>20.1%}")

    print("\n  BY ERA  (the last two strategies died of decay -- check for it)")
    print(f"  {'era':<12}{'n':>7}{'gross SR':>11}{'net SR':>9}{'net CAGR%':>11}")
    for lo, hi in [(2005, 2009), (2010, 2014), (2015, 2019),
                   (2020, 2022), (2023, 2026)]:
        s = d[(d.index.year >= lo) & (d.index.year <= hi)]
        if len(s) < 250:
            continue
        a, b = stats(s.gross), stats(s.net)
        print(f"  {f'{lo}-{hi}':<12}{len(s):>7,}{a.get('sharpe', 0):>11.2f}"
              f"{b.get('sharpe', 0):>9.2f}{b.get('cagr', 0):>11.2f}")

    print("\n  SENSITIVITY (one specification per row, nothing re-fitted)")
    print(f"  {'hold':>6}{'n/side':>8}{'gross SR':>11}{'net SR':>9}{'turn/yr':>9}")
    for hold in (5, 10, 21):
        for nside in (3, 4, 5):
            r = run(px, z, adv, hold=hold, n_side=nside)
            a, b = stats(r.gross), stats(r.net)
            print(f"  {hold:>6}{nside:>8}{a.get('sharpe', 0):>11.2f}"
                  f"{b.get('sharpe', 0):>9.2f}{r.turn.mean()*252:>9.1f}")
    d.to_parquet(OUT / "cef_sleeve_daily.parquet")
    print(f"\n  hurdle: B2 duration-hedged HY carry, net Sharpe 0.54 (0.47 in 2023-26)")
    print(f"wrote {OUT/'cef_sleeve_daily.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
