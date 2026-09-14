"""Unified tradable universe + the lead-lag test.

MECHANISM. Tonight's PD work established that a credit ETF's price LEADS its own
stale NAV -- the wrapper is where price discovery happens, and the fund's official
valuation catches up afterwards. That is not tradable on its own (you cannot trade
a NAV). But it has a corollary that IS tradable.

If HYG at $2.3bn/day is where high-yield price discovery happens, then a thin
wrapper holding nearly the same bonds -- SPHY, SJNK, FLHY at $5-50m/day -- cannot
be absorbing that information as fast. Its price should lag. So:

    group_factor(t)  = liquidity-weighted return of the DEEP names in a class
    signal(thin,t)   = group_factor(t) - own_return(t)     [how far it lagged]
    trade            = long the laggard / short the group, held ~1-3 days

This is wrapper-to-wrapper information diffusion, NOT wrapper-vs-NAV dislocation.
Different mechanism, different failure modes, and both legs are liquid ETFs.

NEGATIVE CONTROL. Treasury ETFs hold instruments that trade on a continuous
screen market, so there is no slow-diffusing information for a thin wrapper to
lag on. The effect must be far weaker there. If Treasuries show the same lag, we
have found a generic microstructure artifact, not a credit effect.

BOUNCE CONTROL. Every return here is built on the (H+L)/2 mid, never the close.
A close-built signal predicting a close-built return is contaminated by bid-ask
alternation, which is exactly how the PD test produced its fake Treasury results.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results/leadlag"
OUT.mkdir(parents=True, exist_ok=True)

# asset-class groups. The trade is always WITHIN a group -- across groups it
# would be a credit or duration view, which the mandate forbids.
GROUPS = {
    "HY":        ["HYG", "JNK", "USHY", "SPHY", "SJNK", "FLHY", "SHYG", "HYGH"],
    "IG":        ["LQD", "USIG", "VCIT", "IGIB", "SPIB", "VCSH", "IGSB", "SPSB"],
    "IG_long":   ["IGLB", "SPLB", "VCLT", "ILTB"],
    "MUNI":      ["MUB", "HYD", "HYMB", "TFI", "SHM", "SUB"],
    "PREF":      ["PFF", "PGX", "PFFD", "FPE"],
    "MBS":       ["MBB", "VMBS", "SPMB"],
    "LOAN":      ["BKLN", "SRLN", "JAAA", "JBBB", "CLOI"],
    "EM":        ["EMB", "EMHY", "VWOB", "PCY", "EMLC"],
    "UST_ctl":   ["SHY", "IEI", "IEF", "TLT", "TLH", "GOVT"],
}
DROP = {"GNMA", "SEIX", "IBND", "HYXU"}   # untradable or too many zero-volume days


def load_universe() -> pd.DataFrame:
    """Union of the core and extended panels, partial final bar removed."""
    frames = []
    for p in ["data/rv/etf_ohlc.parquet", "data/rv/etf_ohlc_extended.parquet"]:
        f = REPO / p
        if f.exists():
            o = pd.read_parquet(f)
            o["date"] = pd.to_datetime(o["date"])
            frames.append(o[["date", "ticker", "high", "low", "close", "volume"]])
    o = pd.concat(frames, ignore_index=True)
    # The extended pull is the later capture, so prefer it on collisions: the
    # core panel's last bar was taken intraday (SPY volume 10.4m against a
    # settled 70.7m) and would inject a fake return on the final day.
    o = o.sort_values("date").drop_duplicates(subset=["date", "ticker"], keep="last")
    o = o[~o.ticker.isin(DROP)]
    last = o.date.max()
    n_last = o[o.date == last].ticker.nunique()
    if n_last < 0.8 * o.ticker.nunique():
        o = o[o.date < last]
        print(f"  dropped partial final bar {last.date()} ({n_last} tickers only)")
    return o


def main() -> int:
    o = load_universe()
    mid = o.pivot_table(index="date", columns="ticker", values="close")   # placeholder
    hi = o.pivot_table(index="date", columns="ticker", values="high")
    lo = o.pivot_table(index="date", columns="ticker", values="low")
    cl = o.pivot_table(index="date", columns="ticker", values="close")
    vol = o.pivot_table(index="date", columns="ticker", values="volume")
    mid = (hi + lo) / 2.0
    ret = mid.pct_change(fill_method=None)       # simple returns, matching repo convention
    ret = ret.where(ret.abs() < 0.5)             # corporate-action junk
    advusd = (cl * vol).rolling(21, min_periods=5).mean().shift(1)

    print(f"universe {ret.shape[1]} tickers, {ret.index.min().date()} -> "
          f"{ret.index.max().date()}, {len(ret):,} sessions\n")

    rows = []
    for grp, members in GROUPS.items():
        have = [t for t in members if t in ret.columns]
        if len(have) < 3:
            print(f"  {grp}: only {len(have)} members, skipped")
            continue
        R = ret[have]
        A = advusd[have]
        # DEEP = the group's most liquid third, by trailing ADV, recomputed daily
        # so the split is point-in-time and a fund that grows into liquidity
        # moves groups when it actually did.
        rank = A.rank(axis=1, ascending=False)
        deep = rank <= max(1, int(np.ceil(len(have) / 3)))
        w = (A * deep).div((A * deep).sum(axis=1), axis=0)
        factor = (R * w).sum(axis=1, min_count=1)

        for tk in have:
            lag = (factor - R[tk])                    # positive => tk lagged the group
            fwd = R[tk].shift(-1) - factor.shift(-1)  # next day, vs the same group
            j = pd.DataFrame({"x": lag, "y": fwd}).replace(
                [np.inf, -np.inf], np.nan).dropna()
            j = j[j.index.year >= 2019]
            # A group's deepest name IS most of the factor, so its own lag is
            # ~0 by construction and the fit is singular. It is also not the
            # trade -- we buy laggards, not leaders -- so exclude it.
            if len(j) < 400 or j.x.std() < 1e-8 or bool(deep[tk].iloc[-1]):
                continue
            b, a = np.polyfit(j.x, j.y, 1)
            resid = j.y - (b * j.x + a)
            se = resid.std() / (np.sqrt(len(j)) * j.x.std())
            rows.append(dict(group=grp, ticker=tk, n=len(j), beta=b, t=b / se,
                             adv_musd=A[tk].iloc[-1] / 1e6,
                             is_deep=bool(deep[tk].iloc[-1])))
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "leadlag_regression.csv", index=False)

    print("=" * 92)
    print("LEAD-LAG: does lagging the group today predict catching up tomorrow?")
    print("  beta > 0 means the laggard reverts toward the group = tradable underreaction")
    print("  UST_ctl MUST be flat: screen-marked bonds leave nothing to diffuse slowly")
    print("=" * 92)
    print(f"{'group':<10}{'names':>7}{'mean beta':>12}{'mean t':>9}"
          f"{'n sig +':>9}{'n sig -':>9}   read")
    for grp, g in r.groupby("group"):
        thin = g[~g.is_deep]
        if thin.empty:
            thin = g
        npos = int((thin.t > 2).sum()); nneg = int((thin.t < -2).sum())
        read = ("CONTROL" if grp == "UST_ctl"
                else ("underreaction" if thin.t.mean() > 2 else "flat"))
        print(f"{grp:<10}{len(thin):>7}{thin.beta.mean():>12.3f}{thin.t.mean():>9.2f}"
              f"{npos:>9}{nneg:>9}   {read}")
    print()
    print("PER-NAME, thin members only, sorted by t")
    print(f"  {'group':<10}{'tkr':<7}{'ADV $M':>9}{'n':>7}{'beta':>9}{'t':>8}")
    for _, x in r[~r.is_deep].sort_values("t", ascending=False).iterrows():
        print(f"  {x.group:<10}{x.ticker:<7}{x.adv_musd:>9.0f}{x.n:>7,.0f}"
              f"{x.beta:>9.3f}{x.t:>8.2f}")
    print(f"\nwrote {OUT/'leadlag_regression.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
