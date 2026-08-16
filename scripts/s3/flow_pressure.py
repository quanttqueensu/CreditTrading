"""S3 -- ETF creation/redemption flow as price pressure.

The mechanism. When investors buy an ETF faster than the market can supply it,
an authorised participant creates new shares and must go buy the underlying
bonds to back them. That buying pushes the bonds up. If the move is pressure
rather than news, it reverses once the flow stops. If it is news, it does not.

Everything here is measured on data with real history, unlike S1/S2 which need a
holdings archive that does not exist yet:
  flow(f,t)   = d(shares outstanding) -- the actual creation/redemption, daily,
                back to 2002, straight from the issuer's own file.
  return      = ETF total return built on the (H+L)/2 mid, never the close, so
                bid-ask bounce cannot manufacture the reversal we are looking for.

The negative control is built in. Treasury ETFs (SHY/IEI/IEF/TLT/GOVT/TLH) hold
bonds that trade on a continuous screen market and absorb flow without price
concession. If the effect is real credit price pressure it must be far weaker
there. If it shows up equally in Treasuries, it is not a credit microstructure
effect and we have found nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results/s3"
OUT.mkdir(parents=True, exist_ok=True)

CREDIT = ["HYG", "LQD", "SHYG", "IGSB", "IGIB", "EMB", "JNK"]
UST = ["SHY", "IEI", "IEF", "TLT", "GOVT", "TLH"]


def load_flows() -> pd.DataFrame:
    """Daily flow in % of shares outstanding, per fund."""
    frames = []
    n = pd.read_parquet(REPO / "data/holdings/ishares_nav_daily.parquet")
    n["date"] = pd.to_datetime(n["date"])
    frames.append(n[["date", "ticker", "nav_per_share", "shares_outstanding"]])

    j = REPO / "data/forced_flow2/jnk_nav_so_daily.parquet"
    if j.exists():
        d = pd.read_parquet(j)
        d["date"] = pd.to_datetime(d["date"])
        frames.append(d[["date", "ticker", "nav_per_share", "shares_outstanding"]])

    f = pd.concat(frames, ignore_index=True).dropna(subset=["shares_outstanding"])
    f = f.sort_values(["ticker", "date"])
    # Shares outstanding only moves in whole creation units, so the raw diff is a
    # lumpy step function; that is the true flow, not noise to be smoothed away.
    f["so_prev"] = f.groupby("ticker").shares_outstanding.shift(1)
    f["flow_pct"] = 100.0 * (f.shares_outstanding - f.so_prev) / f.so_prev
    return f[np.isfinite(f.flow_pct)]


def load_returns() -> pd.DataFrame:
    o = pd.read_parquet(REPO / "data/rv/etf_ohlc.parquet")
    o["date"] = pd.to_datetime(o["date"])
    o = o.sort_values(["ticker", "date"])
    mid = (o.high + o.low) / 2.0
    o["ret_mid"] = np.log(mid).groupby(o.ticker).diff()
    return o[["date", "ticker", "ret_mid", "close", "volume"]]


def build(min_obs: int = 500) -> pd.DataFrame:
    f, r = load_flows(), load_returns()
    d = f.merge(r, on=["date", "ticker"], how="inner").sort_values(["ticker", "date"])

    g = d.groupby("ticker")
    # z-score of flow against the fund's own trailing distribution, PIT: the
    # window ends yesterday so today's flow never enters its own normalisation.
    mu = g.flow_pct.transform(lambda s: s.shift(1).rolling(252, min_periods=60).mean())
    sd = g.flow_pct.transform(lambda s: s.shift(1).rolling(252, min_periods=60).std())
    d["flow_z"] = ((d.flow_pct - mu) / sd.replace(0, np.nan)).clip(-6, 6)

    # forward returns, non-overlapping horizons measured from t+1
    for h in (1, 2, 3, 5, 10, 21):
        d[f"fwd{h}"] = (g.ret_mid.transform(
            lambda s: s.shift(-1).rolling(h).sum().shift(-(h - 1))))
    d["past5"] = g.ret_mid.transform(lambda s: s.rolling(5).sum())
    keep = d.groupby("ticker").flow_z.transform("count") >= min_obs
    return d[keep]


def xs_report(d: pd.DataFrame, label: str, tickers: list[str]) -> pd.DataFrame:
    """Pooled predictive regression of forward return on flow z, by horizon."""
    s = d[d.ticker.isin(tickers)]
    rows = []
    for h in (1, 2, 3, 5, 10, 21):
        j = s[["flow_z", f"fwd{h}"]].dropna()
        if len(j) < 200:
            continue
        x, y = j.flow_z.values, j[f"fwd{h}"].values * 1e4  # bp
        b = np.polyfit(x, y, 1)[0]
        # Newey-West t-stat, lag h, to handle the overlap the horizon induces
        resid = y - np.polyval(np.polyfit(x, y, 1), x)
        xc = x - x.mean()
        s2 = (xc ** 2 * resid ** 2).sum()
        for L in range(1, h + 1):
            w = 1 - L / (h + 1)
            s2 += 2 * w * (xc[L:] * resid[L:] * xc[:-L] * resid[:-L]).sum()
        se = np.sqrt(s2) / (xc ** 2).sum()
        rows.append(dict(group=label, h=h, n=len(j), beta_bp=b, t=b / se if se else np.nan))
    return pd.DataFrame(rows)


def main() -> int:
    d = build()
    d.to_parquet(OUT / "flow_panel.parquet", index=False)
    have = sorted(d.ticker.unique())
    print(f"panel {d.date.min().date()} -> {d.date.max().date()}  "
          f"rows={len(d):,}  funds={have}\n")

    print("=" * 78)
    print("FLOW -> FORWARD RETURN.  beta = bp of return per 1 sigma of flow")
    print("  pressure-and-reversal predicts beta < 0 (inflow today -> lower return")
    print("  after, as the push unwinds). information predicts beta > 0 or flat.")
    print("=" * 78)
    cr = xs_report(d, "CREDIT", [t for t in CREDIT if t in have])
    us = xs_report(d, "UST-control", [t for t in UST if t in have])
    both = pd.concat([cr, us], ignore_index=True)
    both.to_csv(OUT / "flow_regression.csv", index=False)
    for lab, part in both.groupby("group", sort=False):
        print(f"\n  {lab}")
        print(f"    {'horizon':>8}{'n':>9}{'beta bp/sigma':>16}{'t(NW)':>9}")
        for _, x in part.iterrows():
            print(f"    {x.h:>7}d{x.n:>9,.0f}{x.beta_bp:>16.2f}{x.t:>9.2f}")

    # per-fund at the horizon with the strongest pooled credit signal
    best = cr.loc[cr.t.abs().idxmax(), "h"] if len(cr) else 5
    print(f"\n{'='*78}\nPER-FUND at h={best}d\n{'='*78}")
    print(f"  {'fund':<7}{'grp':<9}{'n':>7}{'beta bp':>10}{'t':>8}")
    for tk in have:
        s = d[d.ticker == tk][["flow_z", f"fwd{best}"]].dropna()
        if len(s) < 200:
            continue
        x, y = s.flow_z.values, s[f"fwd{best}"].values * 1e4
        b, a = np.polyfit(x, y, 1)
        resid = y - (b * x + a)
        se = resid.std() / (np.sqrt(len(x)) * x.std())
        grp = "credit" if tk in CREDIT else ("ust" if tk in UST else "?")
        print(f"  {tk:<7}{grp:<9}{len(s):>7,}{b:>10.2f}{b/se:>8.2f}")
    print(f"\nwrote {OUT/'flow_panel.parquet'}\n      {OUT/'flow_regression.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
