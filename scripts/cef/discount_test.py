"""Does the CEF discount predict the PRICE, or only the NAV?

This is the same decomposition that killed the ETF premium/discount trade, run on
a structure where the arbitrage machine does not exist.

For an ETF the answer was: the discount predicts the NAV REVISION at t = 15 to 24
and barely predicts price at all -- the fund's stale valuation catches up to a
price that was right all along, so there is nothing to trade. Authorised
participants had already compressed any real gap to 4bp.

A closed-end fund cannot do that. Its share count is fixed, no one can create or
redeem against the basket, so if a discount is going to close, the PRICE has to
move. That is the whole hypothesis and this file tests it directly.

CONTAMINATION CONTROL. The trap that produced spurious results earlier tonight is
a price appearing on both sides of a regression. The discount at t contains P_t,
so the forward return is measured from t+1 onward -- r = log(P_{t+1+h} / P_{t+1}).
P_t never touches the dependent variable, so no shared term can manufacture
correlation. This also happens to be the honest execution assumption: the signal
is known at the close of t and we trade at the close of t+1.

The forward NAV return is measured the same way, so the two columns are
comparable and the ETF-versus-CEF contrast is like for like.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results/cef"
OUT.mkdir(parents=True, exist_ok=True)

WIN = 252          # trailing window the discount is z-scored against
MIN_ADV = 3.0e6    # tradable at a $640k book
HORIZONS = (5, 10, 21, 63)


def load():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    M = pd.read_csv(REPO / "data/cef/cef_universe.csv")
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d = d[(d.nav > 0.5) & (d.close > 0.5)].sort_values(["ticker", "date"])
    return d, M.set_index("ticker")


def nw_t(x, y, lag) -> tuple[float, float]:
    b, a = np.polyfit(x, y, 1)
    r = y - (b * x + a)
    xc = x - x.mean()
    s2 = (xc ** 2 * r ** 2).sum()
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        s2 += 2 * w * (xc[L:] * r[L:] * xc[:-L] * r[:-L]).sum()
    se = np.sqrt(s2) / (xc ** 2).sum()
    return b, (b / se if se else np.nan)


def main() -> int:
    d, M = load()
    rows, widths = [], []
    for tk, g in d.groupby("ticker"):
        g = g.set_index("date").sort_index()
        adv = M.loc[tk, "adv_musd"] * 1e6 if tk in M.index else 0.0
        grp = M.loc[tk, "grp"] if tk in M.index else "?"
        disc = 100.0 * (g.close - g.nav) / g.nav          # percent of NAV
        mu = disc.rolling(WIN, min_periods=120).mean().shift(1)
        sd = disc.rolling(WIN, min_periods=120).std().shift(1)
        z = ((disc - mu) / sd.replace(0, np.nan)).clip(-5, 5)

        widths.append(dict(ticker=tk, grp=grp, adv=adv, n=len(g),
                           mean_disc=disc.mean(), sd_disc=disc.std(),
                           p5=disc.quantile(0.05), p95=disc.quantile(0.95),
                           ar1=disc.diff().autocorr(1)))

        lp, ln = np.log(g.close), np.log(g.nav)
        for h in HORIZONS:
            # trade at t+1; the signal's own price never enters the return
            fp = (lp.shift(-(1 + h)) - lp.shift(-1)) * 1e4
            fn = (ln.shift(-(1 + h)) - ln.shift(-1)) * 1e4
            j = pd.DataFrame({"x": z, "p": fp, "n": fn}).replace(
                [np.inf, -np.inf], np.nan).dropna()
            if len(j) < 500:
                continue
            bp, tp = nw_t(j.x.values, j.p.values, h)
            bn, tn = nw_t(j.x.values, j.n.values, h)
            rows.append(dict(ticker=tk, grp=grp, adv=adv, h=h, n=len(j),
                             beta_px=bp, t_px=tp, beta_nav=bn, t_nav=tn))
    r = pd.DataFrame(rows)
    w = pd.DataFrame(widths).sort_values("adv", ascending=False)
    r.to_csv(OUT / "cef_discount_regression.csv", index=False)
    w.to_csv(OUT / "cef_discount_width.csv", index=False)

    print("=" * 94)
    print("HOW WIDE IS THE DISCOUNT?  (percent of NAV; the ETF equivalent was 0.04%)")
    print("=" * 94)
    print(f"{'grp':<7}{'funds':>7}{'mean disc':>12}{'sd':>8}{'p5':>8}{'p95':>8}")
    for grp, g in w.groupby("grp"):
        print(f"{grp:<7}{len(g):>7}{g.mean_disc.mean():>11.2f}%{g.sd_disc.mean():>8.2f}"
              f"{g.p5.mean():>8.2f}{g.p95.mean():>8.2f}")
    print(f"{'ALL':<7}{len(w):>7}{w.mean_disc.mean():>11.2f}%{w.sd_disc.mean():>8.2f}"
          f"{w.p5.mean():>8.2f}{w.p95.mean():>8.2f}")

    print("\n" + "=" * 94)
    print("DOES THE DISCOUNT PREDICT THE PRICE, OR ONLY THE NAV?")
    print("  discount cheap (z<0) should mean price RISES  => beta_px < 0")
    print("  if it only moves the NAV, this is the ETF failure repeating")
    print("=" * 94)
    liq = r[r.adv >= MIN_ADV]
    print(f"{'horizon':>9}{'funds':>7}{'mean beta_px':>15}{'mean t_px':>11}"
          f"{'n sig':>8}{'mean t_nav':>12}")
    for h, g in liq.groupby("h"):
        print(f"{h:>8}d{g.ticker.nunique():>7}{g.beta_px.mean():>15.1f}"
              f"{g.t_px.mean():>11.2f}{int((g.t_px < -2).sum()):>8}"
              f"{g.t_nav.mean():>12.2f}")

    best = liq.groupby("h").t_px.mean().idxmin()
    print(f"\nPER-FUND at h={best}d, liquid only (ADV > ${MIN_ADV/1e6:.0f}M)")
    print(f"  {'tkr':<6}{'grp':<7}{'ADV $M':>8}{'n':>7}{'beta_px bp':>12}"
          f"{'t_px':>8}{'t_nav':>8}")
    for _, x in liq[liq.h == best].sort_values("t_px").iterrows():
        print(f"  {x.ticker:<6}{x.grp:<7}{x.adv/1e6:>8.1f}{x.n:>7,.0f}"
              f"{x.beta_px:>12.1f}{x.t_px:>8.2f}{x.t_nav:>8.2f}")
    print(f"\nwrote {OUT/'cef_discount_regression.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
