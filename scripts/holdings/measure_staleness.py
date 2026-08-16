"""Measure NAV mark-staleness per fund.

If a fund's bonds are marked with stale/smoothed vendor prices, its reported NAV
return is a moving average of true returns => positive AR(1) and understated vol.
The ETF's own price return has no such smoothing. So

    excess_ar1 = AR1(NAV return) - AR1(price return)

is a direct, model-free read on how stale the fund's marks are.
Treasury funds are the negative control: continuously screen-marked, so excess ~ 0.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CLASS = {"HYG": "HY", "SHYG": "HY-short", "FALN": "HY-fallen", "LQD": "IG",
         "IGSB": "IG-short", "IGIB": "IG-int", "SLQD": "IG-ultra", "EMB": "EM-sov",
         "AGG": "Aggregate", "GOVT": "UST-ctl", "SHY": "UST-ctl", "IEI": "UST-ctl",
         "IEF": "UST-ctl", "TLT": "UST-ctl", "JNK": "HY", "ANGL": "HY-fallen"}


def load():
    nav = pd.read_parquet(REPO / "data/holdings/ishares_nav_daily.parquet")
    ohlc = pd.read_parquet(REPO / "data/rv/etf_ohlc.parquet")
    return nav, ohlc


def series_for(tk, nav, ohlc):
    g = nav[nav.ticker == tk].copy()
    g["date"] = pd.to_datetime(g["date"])
    n = g.set_index("date").sort_index()
    navtr = (n.nav_per_share + n.ex_dividend.fillna(0.0)) / n.nav_per_share.shift(1) - 1.0
    o = ohlc[ohlc.ticker == tk].copy()
    if o.empty:
        return None
    o["date"] = pd.to_datetime(o["date"])
    o = o.set_index("date").sort_index()
    rmid = np.log((o.high + o.low) / 2.0).diff()
    return pd.DataFrame({"nav": navtr, "mid": rmid}).dropna()


def main():
    nav, ohlc = load()
    eras = {"full": (2002, 2026), "2015-19": (2015, 2019),
            "2020-22": (2020, 2022), "2023-26": (2023, 2026)}
    rows = []
    for tk in sorted(nav.ticker.unique()):
        df = series_for(tk, nav, ohlc)
        if df is None or df.empty:
            print(f"  (no price history for {tk}, skipped)")
            continue
        for era, (lo, hi) in eras.items():
            s = df[(df.index.year >= lo) & (df.index.year <= hi)]
            if len(s) < 250:
                continue
            a_nav, a_px = s.nav.autocorr(1), s["mid"].autocorr(1)
            rows.append(dict(ticker=tk, cls=CLASS.get(tk, "?"), era=era, N=len(s),
                             nav_ar1=a_nav, px_ar1=a_px, excess=a_nav - a_px,
                             volratio=s.nav.std() / s["mid"].std(),
                             se=1.0 / np.sqrt(len(s))))
    r = pd.DataFrame(rows)
    r.to_csv(REPO / "results/s1/staleness_cross_section.csv", index=False)

    for era in eras:
        e = r[r.era == era].sort_values("excess", ascending=False)
        if e.empty:
            continue
        print("=" * 82)
        print(f"ERA {era}    excess = AR1(NAV ret) - AR1(price ret).  "
              f">0 => NAV smoothed by stale marks")
        print("=" * 82)
        print(f"{'tkr':<6}{'class':<11}{'N':>6}{'NAV AR1':>9}{'px AR1':>9}"
              f"{'EXCESS':>9}{'t':>7}{'vol NAV/px':>12}")
        for _, x in e.iterrows():
            print(f"{x.ticker:<6}{x.cls:<11}{x.N:>6,.0f}{x.nav_ar1:>+9.3f}"
                  f"{x.px_ar1:>+9.3f}{x.excess:>+9.3f}{x.excess/x.se:>7.1f}"
                  f"{x.volratio:>12.3f}")
        print()
    print(f"wrote results/s1/staleness_cross_section.csv")


if __name__ == "__main__":
    sys.exit(main())
