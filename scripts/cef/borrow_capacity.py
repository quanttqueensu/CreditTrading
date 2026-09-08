"""Where borrow availability binds -- i.e. how much capital this strategy holds.

THE QUESTION
------------
`fetch_borrow_rates.py` measures what borrow COSTS. This measures whether it is
THERE. They are different constraints and they bind on different names: HYT is
expensive (10.56%) but plentiful (2.5m shares), NAD is expensive AND scarce
(3-5k shares). A cost is a price you pay; an availability limit is a position you
cannot take at any price.

Nothing in this programme has ever asked how much capital the strategy holds.
That is fine at $500k of paper. It is the first question a funded book asks.

WHAT `AVAILABLE` MEANS
----------------------
It is the pool IBKR can lend RIGHT NOW -- it does not count shares already lent
to us. So an existing short larger than `available` is not a violation; it means
we cannot ADD, and that a recall would leave us with nothing to re-borrow. The
constraint is therefore on the DELTA we can establish, and on recall exposure for
what we hold.

Availability is also a snapshot that moves. Sizing to today's number is not
robust, so the capacity test uses a haircut phi -- take only a fraction of the
visible pool -- which is what a prime broker would expect anyway.

Usage:  python3 scripts/cef/borrow_capacity.py [--phi 0.25]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from band_frontier import build_targets, calendar, band, evaluate, UNIVERSE  # noqa: E402

BORROW = REPO / "data" / "cef" / "cef_borrow.csv"
CAPITALS = [0.5e6, 2e6, 5e6, 10e6, 25e6, 50e6]


def latest_borrow(require=None) -> pd.DataFrame:
    """Latest borrow panel row per name.

    RAISES on a required name with no availability figure. The earlier version
    treated a missing `available_shares` as np.inf -- i.e. a fund nobody had
    measured was assumed infinitely shortable, which is the single most
    dangerous default a capacity model can hold. Unknown availability is not
    unlimited availability.
    """
    b = pd.read_csv(BORROW)
    b = b[b.date == b.date.max()].set_index("ticker")
    if require is not None:
        have = set(b.index[b.available_shares.notna()])
        missing = sorted(set(require) - have)
        if missing:
            raise SystemExit(
                f"no borrow availability for {len(missing)} name(s): "
                f"{', '.join(missing)}\n"
                f"  panel: {BORROW.relative_to(REPO)} (latest {b.index.name or ''} "
                f"{b.date.iloc[0] if 'date' in b else ''})\n"
                f"  refusing to compute capacity while treating unknown names as\n"
                f"  unconstrained. Run scripts/cef/fetch_borrow_rates.py.")
    return b


def last_prices() -> pd.Series:
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    P = P[P.ticker.isin(UNIVERSE)]
    P["date"] = pd.to_datetime(P["date"])
    px = P.pivot_table(index="date", columns="ticker", values="close").sort_index()
    # Names do not all print on the same last date (HYT lags the panel by a
    # day), so take each name's own last close rather than the last row.
    return px.ffill().iloc[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phi", type=float, default=0.25,
                    help="fraction of the visible pool we are willing to take")
    a = ap.parse_args()

    px = last_prices()
    bor = latest_borrow(require=UNIVERSE)
    avail = bor.available_shares.astype(float)
    fee = bor.fee_rate_pct.astype(float)
    T, R = build_targets()
    H = calendar(T, 2)

    shorts = (-H).clip(lower=0.0)
    # The size that matters is not the average but a bad day: the 95th pct short.
    p95 = shorts.quantile(0.95)
    mean_w = shorts.mean()

    print(f"phi = {a.phi:.2f} (we take at most {a.phi:.0%} of the visible pool)")
    print(f"availability as of {bor.date.iloc[0]}; prices as of {px.name.date()}\n")

    hdr = (f"{'SYM':6}{'fee %':>7}{'avail sh':>11}{'p95 wt':>8}{'px':>7}"
           f"{'binds at $':>13}")
    print(hdr); print("-" * len(hdr))
    binds = {}
    for t in UNIVERSE:
        if p95[t] <= 0 or t not in avail.index or not np.isfinite(avail[t]):
            continue
        # capital C -> short notional C*w -> shares C*w/px. Binds when that
        # exceeds phi * available.
        cap = a.phi * avail[t] * px[t] / p95[t]
        binds[t] = cap
        print(f"{t:6}{fee[t]:>7.2f}{avail[t]:>11,.0f}{p95[t]:>8.3f}"
              f"{px[t]:>7.2f}{cap:>13,.0f}")
    print("-" * len(hdr))
    b = pd.Series(binds).sort_values()
    print(f"\nFIRST BINDING NAME: {b.index[0]} at ${b.iloc[0]:,.0f} of capital")
    print(f"second: {b.index[1]} at ${b.iloc[1]:,.0f}   third: {b.index[2]} at ${b.iloc[2]:,.0f}")

    # How much of the book is unreachable at each capital level?
    print(f"\n{'capital':>12}{'names binding':>15}{'% of short wt unfillable':>26}")
    print("-" * 53)
    for C in CAPITALS:
        need = C * p95 / px                       # shares wanted
        room = a.phi * avail[list(p95.index)]     # guaranteed present
        over = (need - room).clip(lower=0.0)
        lost_w = over * px[list(p95.index)] / C
        n = int((over > 0).sum())
        print(f"{C:>12,.0f}{n:>15d}{100 * lost_w.sum() / p95.sum():>25.1f}%")

    print(f"\nnote: p95 short weight is used, not the mean -- a constraint that binds")
    print(f"only on the days the signal is most confident is still a binding constraint.")

    # ---- What does respecting the constraint COST? -----------------------
    # A proposed fix is not a solution until its price is known. Cap each short
    # at the borrowable size, then scale the long leg to match so the book stays
    # dollar-neutral, and re-evaluate. Longs are never capped -- you can always
    # buy.
    print("\n" + "=" * 66)
    print("COST OF RESPECTING THE CONSTRAINT (calendar 2d, spread 15bp)")
    print("=" * 66)
    hdr2 = (f"{'capital':>12}{'gross SR':>10}{'net@15bp':>10}{'borrow%':>9}"
            f"{'net+borrow':>12}{'avg gross':>11}")
    print(hdr2); print("-" * len(hdr2))
    rate = fee.reindex(H.columns).fillna(fee.median()) / 100.0

    def report(label, Hx):
        r = evaluate(Hx, R)
        sh = (-Hx).clip(lower=0.0)
        drag = sh.mul(rate, axis=1).sum(axis=1).mean()   # rate is already annual
        net = (r["ann_ret"] - r["turn"] * 15 / 1e4) / r["vol"]
        netb = (r["ann_ret"] - r["turn"] * 15 / 1e4 - drag) / r["vol"]
        gv = Hx.abs().sum(axis=1).mean()
        print(f"{label:>12}{r['gross_sr']:>10.2f}{net:>10.2f}"
              f"{100 * drag:>9.2f}{netb:>12.2f}{gv:>11.2f}")

    report("uncapped", H)
    # Every column is guaranteed present by latest_borrow(require=...) above, so
    # this is a plain lookup -- no reindex, no fill. A KeyError is correct.
    room_sh = a.phi * avail[list(H.columns)]
    for C in [0.5e6, 2e6, 5e6, 10e6, 25e6]:
        lim = room_sh * px[list(H.columns)] / C                      # max short WEIGHT
        S = (-H).clip(lower=0.0)
        L = H.clip(lower=0.0)
        Sc = S.clip(upper=lim, axis=1)
        # Dollar-neutral: shrink longs to the fillable short size. scale is NaN
        # only on days with no short leg at all, where 1.0 (leave longs alone)
        # is the intended answer and not a papered-over failure.
        scale = (Sc.sum(axis=1) / S.sum(axis=1).replace(0, np.nan)).fillna(1.0)
        Hc = L.mul(scale, axis=0) - Sc
        report(f"{C:,.0f}", Hc)
    print("-" * len(hdr2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
