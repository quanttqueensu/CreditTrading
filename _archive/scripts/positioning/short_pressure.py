"""Crowded-hedge reversal: FINRA daily short-sale volume on credit ETFs.

MECHANISM, AND WHY IT IS DIFFERENT FROM EVERYTHING ELSE TESTED. HYG is the
market's primary vehicle for hedging credit risk -- an institution that wants to
be less exposed to high yield for two weeks shorts HYG rather than selling a
hundred bonds. So a surge in HYG short-selling is not a view that HYG is
overpriced; it is hedging demand, and it is transient by construction. When the
hedge is lifted the flow reverses. That is positioning, not valuation, and none
of the twelve mechanisms killed so far touches it.

    signal(t)   = short_volume_pct deviation from the ticker's own baseline
    claim       = a crowded short unwinds => forward return is HIGHER

WHY LEVELS ARE USELESS AND DEVIATIONS ARE NOT. Reg SHO flags market-maker
hedging prints as short, so every ticker sits around 45-60% short volume all the
time. The level says nothing. Only the deviation from a ticker's own trailing
baseline carries information, so everything here is z-scored per ticker.

CONTROL GROUP. SHY / IEF / TLT are rates ETFs. They are also hedging vehicles, so
this is a weaker control than the Treasury tests used elsewhere -- if the effect
is generic "crowded hedge unwinds" it should appear there too, and only a
credit-specific effect would show up in credit alone. Reported side by side and
interpreted honestly rather than claimed as a clean falsification.

POINT-IN-TIME. FINRA publishes the daily file after the close, so a signal built
on day t is actionable at the close of t+1 at the earliest. Returns are measured
from t+1 forward and the baseline window ends at t-1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results/positioning"
OUT.mkdir(parents=True, exist_ok=True)

CREDIT = ["HYG", "JNK", "USHY", "SHYG", "LQD", "EMB", "ANGL", "BKLN", "PFF", "MBB"]
RATES = ["SHY", "IEF", "TLT"]
BASE = 63          # trailing baseline window for the z-score


def load():
    sv = pd.read_parquet(REPO / "data/positioning/short_volume_daily_finra.parquet")
    sv["date"] = pd.to_datetime(sv["date"])
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
    return sv, m.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)


def main() -> int:
    sv, ret = load()
    piv = sv.pivot_table(index="date", columns="ticker", values="short_volume_pct")
    piv = piv.reindex(ret.index).dropna(how="all")

    # z-score against the ticker's OWN trailing baseline, window ending t-1
    mu = piv.rolling(BASE, min_periods=30).mean().shift(1)
    sd = piv.rolling(BASE, min_periods=30).std().shift(1)
    z = ((piv - mu) / sd.replace(0, np.nan)).clip(-5, 5)

    # hedge out the asset class so this is not a duration or credit-beta bet:
    # measure each name against the equal-weight return of its own group.
    print("=" * 92)
    print("CROWDED-HEDGE REVERSAL: does a spike in short-selling predict a bounce?")
    print(f"  signal = short_volume_pct z-score vs own {BASE}d baseline, PIT")
    print("  claim: crowded short unwinds => beta > 0 on forward EXCESS return")
    print("=" * 92)
    rows = []
    for grp, names in [("CREDIT", CREDIT), ("RATES-ctl", RATES)]:
        have = [t for t in names if t in ret.columns and t in z.columns]
        grpret = ret[have].mean(axis=1)
        for tk in have:
            excess = ret[tk] - grpret          # within-group, class-neutral
            for h in (1, 3, 5, 10):
                fwd = excess.shift(-1).rolling(h).sum().shift(-(h - 1)) * 1e4
                j = pd.DataFrame({"x": z[tk], "y": fwd}).replace(
                    [np.inf, -np.inf], np.nan).dropna()
                if len(j) < 400:
                    continue
                b, a = np.polyfit(j.x, j.y, 1)
                r = j.y - (b * j.x + a)
                xc = j.x.values - j.x.mean()
                s2 = (xc ** 2 * r.values ** 2).sum()
                for L in range(1, h + 1):
                    w = 1 - L / (h + 1)
                    s2 += 2 * w * (xc[L:] * r.values[L:] * xc[:-L] * r.values[:-L]).sum()
                se = np.sqrt(s2) / (xc ** 2).sum()
                rows.append(dict(grp=grp, ticker=tk, h=h, n=len(j),
                                 beta=b, t=b / se if se else np.nan))
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "short_pressure.csv", index=False)

    print(f"{'group':<11}{'horizon':>9}{'names':>7}{'mean beta bp':>15}"
          f"{'mean t':>9}{'n sig +':>9}{'n sig -':>9}")
    for (grp, h), g in r.groupby(["grp", "h"]):
        print(f"{grp:<11}{h:>8}d{len(g):>7}{g.beta.mean():>15.2f}{g.t.mean():>9.2f}"
              f"{int((g.t > 2).sum()):>9}{int((g.t < -2).sum()):>9}")
    best = r[r.grp == "CREDIT"].groupby("h").t.mean().abs().idxmax()
    print(f"\nPER-NAME at h={best}d")
    print(f"  {'tkr':<7}{'grp':<11}{'n':>7}{'beta bp':>10}{'t':>8}")
    for _, x in r[r.h == best].sort_values("t", ascending=False).iterrows():
        print(f"  {x.ticker:<7}{x.grp:<11}{x.n:>7,.0f}{x.beta:>10.2f}{x.t:>8.2f}")
    print(f"\nwrote {OUT/'short_pressure.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
