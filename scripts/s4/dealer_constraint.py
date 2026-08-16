"""S4 -- dealer balance-sheet constraint as a standalone timing signal.

DIFFERENT MECHANISM from everything killed tonight. Nothing here is about the ETF
wrapper, stale marks, or index rules. This is intermediary asset pricing: dealers
are the marginal holder of corporate credit risk, and when their balance sheets
are full they require more compensation to keep warehousing it. So a build-up in
primary-dealer corporate inventory should predict HIGHER subsequent credit excess
returns -- the market pays dealers to hold what nobody else will.

  signal(t)  = z-score of primary-dealer net corporate positions
  claim      = high inventory -> dealers constrained -> credit excess return rises

WHY IT IS NOT MECHANICALLY CIRCULAR: dealer inventory is reported by the NY Fed
from dealer submissions, not derived from prices. A price-based signal predicting
prices invites the bounce and non-synchronous artifacts that killed the lead-lag
test. This one cannot suffer from them.

POINT-IN-TIME: the NY Fed publishes with a lag -- the survey week ends Wednesday
and release is the following Thursday, so roughly 8 calendar days. The series is
therefore shifted by 10 business days before use, which is deliberately more
conservative than the true lag.

NEGATIVE CONTROL: the same signal on Treasury ETFs. Dealers warehouse Treasuries
too, but the Treasury market's depth means inventory should carry far less price
pressure than it does in credit. A signal equally strong in both is a macro
factor, not a credit-intermediation effect.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
OUT = REPO / "results/s4"
OUT.mkdir(parents=True, exist_ok=True)

PUB_LAG_BD = 10          # deliberately > the true ~8 calendar day release lag
CREDIT = ["HYG", "JNK", "LQD", "USHY", "SHYG", "IGIB", "VCIT", "EMB", "ANGL"]
UST = ["SHY", "IEI", "IEF", "TLT", "GOVT"]


def dealer_z() -> pd.Series:
    d = pd.read_parquet(REPO / "data/forced_flow2/nyfed_pd_corp_raw.parquet")
    d["date"] = pd.to_datetime(d["date"])
    # sum every corporate series into one net-inventory number per week
    w = d.groupby("date").value_musd.sum().sort_index()
    # inventory grows with the market, so level is not comparable across decades.
    # Use the deviation from a 2y trailing mean, scaled by trailing sd.
    mu = w.rolling(104, min_periods=52).mean()
    sd = w.rolling(104, min_periods=52).std()
    return ((w - mu) / sd.replace(0, np.nan)).clip(-4, 4).dropna()


def load_ret() -> pd.DataFrame:
    frames = []
    for p in ["data/rv/etf_ohlc.parquet", "data/rv/etf_ohlc_extended.parquet"]:
        f = REPO / p
        if f.exists():
            o = pd.read_parquet(f)
            o["date"] = pd.to_datetime(o["date"])
            frames.append(o[["date", "ticker", "high", "low", "close"]])
    o = pd.concat(frames).sort_values("date").drop_duplicates(
        subset=["date", "ticker"], keep="last")
    mid = o.pivot_table(index="date", columns="ticker", values=["high", "low"])
    m = (mid["high"] + mid["low"]) / 2.0
    return m.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)


def main() -> int:
    z, ret = dealer_z(), load_ret()
    bd = ret.index
    # weekly -> daily, held forward, then pushed out by the publication lag
    zd = z.reindex(bd.union(z.index)).ffill().reindex(bd)
    zd = zd.shift(PUB_LAG_BD)

    # credit EXCESS of duration: the trade must not be a rates bet
    ief = ret["IEF"] if "IEF" in ret.columns else 0.0
    print(f"dealer z: {z.index.min().date()} -> {z.index.max().date()}, "
          f"{len(z)} weekly obs\n")
    print("=" * 88)
    print("DEALER INVENTORY -> FORWARD CREDIT RETURN (duration-hedged, bp per 1 sigma)")
    print(f"  signal shifted {PUB_LAG_BD} business days for publication lag")
    print("  claim: constrained dealers demand compensation => beta > 0")
    print("=" * 88)
    rows = []
    for grp, names in [("CREDIT", CREDIT), ("UST-ctl", UST)]:
        for h in (5, 10, 21, 42, 63):
            for tk in names:
                if tk not in ret.columns:
                    continue
                r = ret[tk]
                if grp == "CREDIT" and not isinstance(ief, float):
                    b = r.rolling(126).cov(ief) / ief.rolling(126).var()
                    r = r - b.shift(1).clip(0, 3) * ief
                fwd = r.shift(-1).rolling(h).sum().shift(-(h - 1))
                j = pd.DataFrame({"x": zd, "y": fwd * 1e4}).replace(
                    [np.inf, -np.inf], np.nan).dropna()
                if len(j) < 500:
                    continue
                bb, aa = np.polyfit(j.x, j.y, 1)
                res = j.y - (bb * j.x + aa)
                # Newey-West for the overlap the horizon creates
                xc = j.x.values - j.x.mean()
                s2 = (xc ** 2 * res.values ** 2).sum()
                for L in range(1, h + 1):
                    wgt = 1 - L / (h + 1)
                    s2 += 2 * wgt * (xc[L:] * res.values[L:] *
                                     xc[:-L] * res.values[:-L]).sum()
                se = np.sqrt(s2) / (xc ** 2).sum()
                rows.append(dict(grp=grp, h=h, ticker=tk, beta=bb,
                                 t=bb / se if se else np.nan, n=len(j)))
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "dealer_constraint.csv", index=False)
    print(f"{'group':<9}{'horizon':>9}{'names':>7}{'mean beta bp':>15}{'mean t':>9}"
          f"{'n sig':>7}")
    for (grp, h), g in r.groupby(["grp", "h"]):
        print(f"{grp:<9}{h:>8}d{len(g):>7}{g.beta.mean():>15.1f}{g.t.mean():>9.2f}"
              f"{int((g.t.abs() > 2).sum()):>7}")
    print()
    best = r[r.grp == "CREDIT"].groupby("h").t.mean().idxmax()
    print(f"strongest credit horizon: {best}d")
    print(f"{'  tkr':<8}{'beta bp':>10}{'t':>8}")
    for _, x in r[(r.grp == "CREDIT") & (r.h == best)].sort_values(
            "t", ascending=False).iterrows():
        print(f"  {x.ticker:<6}{x.beta:>10.1f}{x.t:>8.2f}")
    print(f"\nwrote {OUT/'dealer_constraint.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
