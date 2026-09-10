"""What the short leg actually costs, and what it does to the answer.

PLAN.md 3.3 flagged that no Sharpe this programme has ever quoted charges the
short leg a borrow cost. `scripts/cef/fetch_borrow_rates.py` now measures the
rate. This applies it.

THE APPROXIMATION, STATED UP FRONT
----------------------------------
We hold ONE day of measured borrow (the panel starts 2026-09-06) and apply it to
21 years of held weights. That is a counterfactual -- "what if today's schedule
had held throughout" -- not a historical cost. Borrow rates move, and the muni
complex's rates in particular move with the fund's own premium.

It is still the right number to act on, for a specific reason: the question is
not "what did we pay in 2011", it is "what will we pay going forward at this
size in these names". Today's schedule is the best estimate of that, and the
panel accumulates so this gets less approximate every session.

Borrow is charged on the HELD short market value, not on turnover -- so unlike
spread cost it is not reduced by trading less. It is reduced only by shorting
different names, or by shorting less.

Usage:  python3 scripts/cef/borrow_impact.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from band_frontier import build_targets, calendar, band, evaluate  # noqa: E402
from spec import BAND_WIDTH, LIVE_POLICY  # noqa: E402  spec-owned, never a literal

BORROW = REPO / "data" / "cef" / "cef_borrow.csv"
SPREAD_BP = 15.0          # the mid-case in PLAN.md 2.2
ASSUMED_BP = 50.0         # what FinancingModel currently charges


def fee_schedule(require=None) -> pd.Series:
    """Latest measured fee per name, in annual percent.

    RAISES on any required name we have no rate for, rather than substituting
    one. An earlier version of this file filled missing names with the panel
    median, which meant a name nobody had ever measured was silently charged
    0.83%/yr and then reported inside a confident-looking drag total. A borrow
    cost we do not know is not a borrow cost of roughly average size -- it is an
    unknown, and the only honest thing a cost model can do with it is refuse.
    """
    b = pd.read_csv(BORROW)
    b = b[b.date == b.date.max()]
    fee = b.set_index("ticker").fee_rate_pct.astype(float)
    fee = fee[fee.notna()]
    if require is not None:
        missing = sorted(set(require) - set(fee.index))
        if missing:
            raise SystemExit(
                f"no borrow rate for {len(missing)} name(s): {', '.join(missing)}\n"
                f"  panel: {BORROW.relative_to(REPO)} (latest {b.date.max()})\n"
                f"  refusing to price a short book with unpriced names. Run\n"
                f"  scripts/cef/fetch_borrow_rates.py, or drop them from the test.")
    return fee


def borrow_drag(H: pd.DataFrame, fee: pd.Series) -> pd.Series:
    """Daily borrow cost as a fraction of capital, from held short weights."""
    shorts = (-H).clip(lower=0.0)                       # positive where short
    # No reindex-and-fill: `fee` is required to cover every column, enforced at
    # load by fee_schedule(require=...). A KeyError here is the correct outcome.
    rate = fee[list(H.columns)] / 100.0
    return shorts.mul(rate, axis=1).sum(axis=1) / 252.0


def line(label, H, R, fee):
    r = evaluate(H, R)
    spread = r["turn"] * SPREAD_BP / 1e4
    drag = borrow_drag(H, fee).mean() * 252
    flat = (-H).clip(lower=0.0).sum(axis=1).mean() * ASSUMED_BP / 1e4
    net_sp = (r["ann_ret"] - spread) / r["vol"]
    net_old = (r["ann_ret"] - spread - flat) / r["vol"]
    net_new = (r["ann_ret"] - spread - drag) / r["vol"]
    print(f"{label:<20}{r['gross_sr']:8.2f}{net_sp:10.2f}{net_old:11.2f}"
          f"{net_new:11.2f}{drag * 100:10.2f}{r['ann_ret'] * 100:9.2f}")
    return net_sp, net_new


def main() -> int:
    T, R = build_targets()
    fee = fee_schedule(require=list(T.columns))
    print(f"targets {T.index[0].date()} -> {T.index[-1].date()}  ({len(T)} days)")
    print(f"fee schedule: {len(fee)} names, "
          f"median {fee.median():.2f}%  max {fee.max():.2f}% ({fee.idxmax()})\n")

    hdr = (f"{'policy':<20}{'gross':>8}{'+spread':>10}{'+50bp GC':>11}"
           f"{'+MEASURED':>11}{'borrow%':>10}{'ann ret%':>9}")
    print(hdr); print("-" * len(hdr))
    # The LIVE row is whichever policy the frozen spec currently declares. Until
    # 2026-09-10 this table labelled "calendar 2d (LIVE)" and baselined 6.4%,
    # four days after the 4.8% band replaced the calendar.
    pols = [("calendar 2d", calendar(T, 2)),
            (LIVE_POLICY + "  <-- LIVE", band(T, BAND_WIDTH)),
            ("band 6.4%", band(T, 0.064))]
    res = {lab: line(lab, H, R, fee) for lab, H in pols}
    print("-" * len(hdr))
    print(f"spread charged at {SPREAD_BP:.0f}bp/turnover; borrow on held short MV.\n")

    # Where the drag comes from -- this is the actionable part, and it must be
    # computed on the policy the book ACTUALLY RUNS. It used calendar(T, 2)
    # until 2026-09-10: the per-name borrow bill was being attributed across the
    # average short weights of a retired policy. Borrow scales with HOLDINGS,
    # and the band holds a different book from the calendar, so the per-name
    # shares this table reports were not the shares we are paying.
    H = band(T, BAND_WIDTH)
    shorts = (-H).clip(lower=0.0)
    rate = fee[list(H.columns)] / 100.0
    per = shorts.mean() * rate
    tot = per.sum()
    print(f"{'SYM':6}{'avg short wt':>14}{'fee %':>8}{'drag %/yr':>11}{'share':>8}")
    print("-" * 47)
    for t in per.sort_values(ascending=False).index:
        if per[t] <= 0:
            continue
        print(f"{t:6}{shorts[t].mean():>14.4f}{100 * rate[t]:>8.2f}"
              f"{100 * per[t]:>11.3f}{100 * per[t] / tot:>7.1f}%")
    print("-" * 47)
    print(f"{'TOT':6}{shorts.sum(axis=1).mean():>14.4f}{'':>8}{100 * tot:>11.3f}{'100.0%':>8}")

    top3 = per.sort_values(ascending=False).head(3)
    print(f"\ntop 3 names are {100 * top3.sum() / tot:.0f}% of the borrow drag: "
          f"{', '.join(top3.index)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
