"""QUEUE 1 -- premium/discount dispersion, ranked across every wrapper we can price.

The buried lede from run 1: the naive PD band trade's SHARPE held across eras
(0.75 -> 2.64 -> 0.41 -> 0.48) while its RETURN collapsed (2.54% -> 0.05%/yr). It
did not start losing. It stopped trading, because the dislocation shrank below the
band. Edge per opportunity survived; opportunity COUNT died.

That points somewhere specific. HYG's dispersion collapsed because portfolio
trading industrialised that one name -- dealers can now price and risk-transfer a
whole HY basket in one ticket, which is exactly what compresses the AP arbitrage
band. Nobody built that desk for municipal high yield, long-maturity IG,
preferreds, or mortgages.

So: measure sigma(PD) everywhere, and compare it to the round-trip cost of
actually trading that wrapper. The trade exists where dispersion >> cost,
regardless of what HYG is doing.

    PD(f,t)      = (price - NAV) / NAV, price on the (H+L)/2 mid to kill bounce
    dispersion   = sd of the fund's PD, in bp of NAV
    round trip   = 2 x measured half-spread (both legs in and out for a pair)
    VIABILITY    = dispersion / round-trip cost   <- the number that matters
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

OUT = REPO / "results/disp"
OUT.mkdir(parents=True, exist_ok=True)
CM = SCENARIOS["base"]

CLASS = {
    "HYG": "HY", "JNK": "HY", "SHYG": "HY-short", "USHY": "HY", "ANGL": "HY-fallen",
    "LQD": "IG", "IGSB": "IG-short", "IGIB": "IG-int", "VCIT": "IG-int",
    "EMB": "EM-sov", "AGG": "Aggregate",
    "SHY": "UST-ctl", "IEI": "UST-ctl", "IEF": "UST-ctl", "TLT": "UST-ctl",
    "TLH": "UST-ctl", "GOVT": "UST-ctl",
}


def load_nav() -> pd.DataFrame:
    frames = []
    n = pd.read_parquet(REPO / "data/holdings/ishares_nav_daily.parquet")
    n["date"] = pd.to_datetime(n["date"])
    frames.append(n[["date", "ticker", "nav_per_share"]])
    for p, col in [("data/forced_flow2/jnk_nav_so_daily.parquet", "nav_per_share"),
                   ("data/forced_flow/angl_nav_aum_daily.parquet", "nav_per_share")]:
        f = REPO / p
        if f.exists():
            d = pd.read_parquet(f)
            d["date"] = pd.to_datetime(d["date"])
            if col in d.columns:
                frames.append(d[["date", "ticker", col]].rename(
                    columns={col: "nav_per_share"}))
    return pd.concat(frames, ignore_index=True).dropna(subset=["nav_per_share"])


def load_px() -> pd.DataFrame:
    frames = []
    for p in ["data/rv/etf_ohlc.parquet", "data/rv/etf_ohlc_extended.parquet"]:
        f = REPO / p
        if f.exists():
            o = pd.read_parquet(f)
            o["date"] = pd.to_datetime(o["date"])
            frames.append(o[["date", "ticker", "high", "low", "close", "volume"]])
    o = pd.concat(frames, ignore_index=True)
    return o.drop_duplicates(subset=["date", "ticker"], keep="first")


def main() -> int:
    nav, px = load_nav(), load_px()
    d = px.merge(nav, on=["date", "ticker"], how="inner")
    # PD MUST use the closing print, not the (H+L)/2 mid. NAV is struck at 16:00
    # and the close is the 16:00 print, so the two are contemporaneous. The day's
    # high/low midpoint is a different moment entirely, and differencing it
    # against a 16:00 NAV manufactures dispersion out of ordinary intraday
    # movement -- which showed up as TLT, a Treasury fund that cannot possibly
    # have a stale mark, appearing to have 32bp of "dislocation". The bid-ask
    # bounce in the close is real but is ~0.6bp, an order of magnitude smaller
    # than the artifact it would be trading away.
    d["pd_bp"] = 1e4 * (d["close"] - d.nav_per_share) / d.nav_per_share
    d = d[d.pd_bp.abs() < 2000]                       # drop corporate-action junk
    d["advusd"] = d.close * d.volume

    eras = {"2007-2014": (2007, 2014), "2015-2019": (2015, 2019),
            "2020-2022": (2020, 2022), "2023-2026": (2023, 2026)}
    rows = []
    for tk, g in d.groupby("ticker"):
        g = g.sort_values("date").set_index("date")
        adv = g.advusd.tail(63).mean()
        px_last = g.close.iloc[-1]
        rt = 2.0 * CM.half_spread_bp(px_last, adv, tk)     # round trip, one leg
        for era, (lo, hi) in eras.items():
            s = g[(g.index.year >= lo) & (g.index.year <= hi)].pd_bp
            if len(s) < 200:
                continue
            # dispersion of the DE-TRENDED PD: a fund can carry a persistent
            # structural premium (fee, tax, FX) that is not tradable. Only the
            # wiggle around it is.
            resid = s - s.rolling(63, min_periods=20).mean()
            sd = resid.std()
            ar1 = resid.autocorr(1)
            hl = -np.log(2) / np.log(abs(ar1)) if 0 < abs(ar1) < 1 else np.nan
            # A dislocation is only worth harvesting to the extent it actually
            # comes back. For an AR(1), entering at 2 sigma and exiting at the
            # mean captures 2*sd*(1-ar1)/(1-ar1) = 2*sd in the limit, but only
            # the mean-reverting FRACTION is real; the rest is a random walk we
            # would be holding, not harvesting. Weighting by ar1 is what stops a
            # pure-noise series (Treasuries, ar1 ~ 0) scoring well.
            edge = 2.0 * sd * max(ar1, 0.0)
            rows.append(dict(ticker=tk, cls=CLASS.get(tk, "?"), era=era, N=len(s),
                             disp_bp=sd, ar1=ar1, halflife=hl, rt_cost_bp=rt,
                             edge_bp=edge,
                             viability=edge / rt if rt else np.nan,
                             adv_musd=adv / 1e6))
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "dispersion_scan.csv", index=False)

    for era in eras:
        e = r[r.era == era].sort_values("viability", ascending=False)
        if e.empty:
            continue
        print("=" * 98)
        print(f"ERA {era}   dispersion of premium/discount vs cost to trade it")
        print("=" * 98)
        print(f"{'tkr':<7}{'class':<11}{'N':>6}{'disp bp':>10}{'AR1':>7}"
              f"{'half-life':>11}{'edge bp':>9}{'RT cost':>9}{'VIABILITY':>11}{'ADV $M':>9}")
        for _, x in e.iterrows():
            flag = "  <<<" if x.viability >= 2.5 else ""
            print(f"{x.ticker:<7}{x.cls:<11}{x.N:>6,.0f}{x.disp_bp:>10.1f}"
                  f"{x.ar1:>7.2f}{x.halflife:>11.1f}{x.edge_bp:>9.1f}"
                  f"{x.rt_cost_bp:>9.2f}{x.viability:>11.1f}{x.adv_musd:>9.0f}{flag}")
        print()
    print("edge = 2*sd*max(ar1,0): the mean-reverting part only. VIABILITY = edge/cost.")
    print("The E1 gate wants gross edge >= 2.5x cost. Treasuries MUST score ~0 --")
    print("they are screen-marked, so any Treasury scoring well means the metric is broken.")
    print(f"\nwrote {OUT/'dispersion_scan.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
