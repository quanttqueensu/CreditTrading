"""Is the lead-lag effect real, or is it non-synchronous trading?

The raw regression showed t-statistics of 12-25, which is too large to believe.
The prime suspect is the measurement: returns were built on (H+L)/2, and the
midpoint of a day's trading range is NOT a price anyone can transact at. For a
thin fund that traded twice, that midpoint is stale, and tomorrow's "catch-up" is
an artifact of the price never having been available, not an opportunity.

So this file re-tests the same signal under progressively harsher and more
realistic assumptions, and reports all of them side by side:

  A  mid -> mid, same day      the original claim (NOT executable)
  B  mid signal -> CLOSE ret   signal bounce-free, return at a real price
  C  close -> close            everything at transactable prices
  D  close -> close, T+1 EXEC  signal at t, trade at the close of t+1, earn t+2
                               <- this is the repo's standing convention and the
                                  only one that is honestly implementable

If the effect only exists in A, it is non-synchronous trading and it dies here.
D is the number that decides whether anything gets deployed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.leadlag.build_panel import GROUPS, load_universe  # noqa: E402

OUT = REPO / "results/leadlag"


def panels():
    o = load_universe()
    hi = o.pivot_table(index="date", columns="ticker", values="high")
    lo = o.pivot_table(index="date", columns="ticker", values="low")
    cl = o.pivot_table(index="date", columns="ticker", values="close")
    vol = o.pivot_table(index="date", columns="ticker", values="volume")
    mid = (hi + lo) / 2.0
    r_mid = mid.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    r_cls = cl.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    adv = (cl * vol).rolling(21, min_periods=5).mean().shift(1)
    return r_mid, r_cls, adv, cl


def group_factor(R: pd.DataFrame, A: pd.DataFrame, have: list[str]):
    rank = A[have].rank(axis=1, ascending=False)
    deep = rank <= max(1, int(np.ceil(len(have) / 3)))
    w = (A[have] * deep).div((A[have] * deep).sum(axis=1), axis=0)
    return (R[have] * w).sum(axis=1, min_count=1), deep


def run(sig_ret, fwd_ret, adv, exec_lag: int, label: str) -> pd.DataFrame:
    """exec_lag=0 -> signal at t earns t+1. exec_lag=1 -> trade at t+1, earn t+2."""
    rows = []
    for grp, members in GROUPS.items():
        have = [t for t in members if t in sig_ret.columns and t in fwd_ret.columns]
        if len(have) < 3:
            continue
        f_sig, deep = group_factor(sig_ret, adv, have)
        f_fwd, _ = group_factor(fwd_ret, adv, have)
        for tk in have:
            if bool(deep[tk].iloc[-1]):
                continue
            lag = (f_sig - sig_ret[tk]).shift(exec_lag)
            fwd = fwd_ret[tk].shift(-1) - f_fwd.shift(-1)
            j = pd.DataFrame({"x": lag, "y": fwd}).replace(
                [np.inf, -np.inf], np.nan).dropna()
            j = j[j.index.year >= 2019]
            if len(j) < 400 or j.x.std() < 1e-8:
                continue
            b, a = np.polyfit(j.x, j.y, 1)
            res = j.y - (b * j.x + a)
            se = res.std() / (np.sqrt(len(j)) * j.x.std())
            rows.append(dict(spec=label, group=grp, ticker=tk, n=len(j),
                             beta=b, t=b / se))
    return pd.DataFrame(rows)


def main() -> int:
    r_mid, r_cls, adv, cl = panels()
    specs = [
        ("A mid->mid  (NOT executable)", r_mid, r_mid, 0),
        ("B mid sig -> close ret",       r_mid, r_cls, 0),
        ("C close->close",               r_cls, r_cls, 0),
        ("D close->close  T+1 EXEC",     r_cls, r_cls, 1),
    ]
    all_r = []
    for label, s, f, lagn in specs:
        all_r.append(run(s, f, adv, lagn, label))
    r = pd.concat(all_r, ignore_index=True)
    r.to_csv(OUT / "leadlag_specs.csv", index=False)

    print("=" * 96)
    print("DOES THE LEAD-LAG SURVIVE EXECUTABLE PRICES?   mean t by group and spec")
    print("=" * 96)
    piv = r.pivot_table(index="group", columns="spec", values="t", aggfunc="mean")
    cols = [s[0] for s in specs]
    piv = piv[[c for c in cols if c in piv.columns]]
    print(f"{'group':<10}" + "".join(f"{c[:26]:>28}" for c in piv.columns))
    for g, row in piv.iterrows():
        tag = "  <- CONTROL" if g == "UST_ctl" else ""
        print(f"{g:<10}" + "".join(f"{v:>28.2f}" for v in row.values) + tag)
    print()
    print("  A is the original claim. If the effect collapses from A to B/C/D it was")
    print("  non-synchronous trading: (H+L)/2 is not a price you can transact at.")
    print()
    nA = r[r.spec.str.startswith("A")].t.mean()
    nD = r[r.spec.str.startswith("D")].t.mean()
    print(f"  overall mean t   A={nA:.2f}   D={nD:.2f}   "
          f"retention {100*nD/nA if nA else 0:.0f}%")
    print(f"\nwrote {OUT/'leadlag_specs.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
