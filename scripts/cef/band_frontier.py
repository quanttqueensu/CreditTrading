"""Part 2 of PLAN.md — the trading policy frontier.

Asks one question: at a given amount of trading, which policy keeps more of the
gross edge, a fixed rebalance calendar or a no-trade band?

Both policies run on an IDENTICAL signal (the live sleeve's z-score, ADV filter
and vol scalar) and identical execution (decide at t, MOC fill at t+1, so the
weights set at t earn the t+2 return). The only difference is when they trade.

  calendar(k)  ignore the signal for k days, then implement all of it
  band(b)      hold a position until it is more than b from target, then trade
               back only to the band EDGE -- the optimal form under proportional
               costs (Constantinides 1986, Davis & Norman 1990)

Costs are charged as bp per unit of turnover, swept rather than assumed, because
the realised figure is not yet known. `net` columns are therefore a sensitivity
surface, not a forecast.

IMPORTANT: this table characterises the POLICY CLASS. Do not read the argmax of a
column as the band width to deploy -- deriving a parameter from the cube-root law
and checking it lands on the plateau is legitimate; picking the top of a swept
column is how z_window=63 was selected, and it failed out of sample.

Usage:  python scripts/cef/band_frontier.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]

# Parameters the LIVE BOOK owns come from the frozen spec, never from a literal
# here. Until 2026-09-10 these were module constants that happened to agree with
# the spec; "happened to agree" stops being true at the next spec bump, and a
# baseline measured against a policy nobody deployed is worse than no baseline.
# See scripts/cef/spec.py for the full argument.
import sys                                                          # noqa: E402
sys.path.insert(0, str(REPO))
from scripts.cef.spec import (  # noqa: E402
    BAND_WIDTH, GROSS_LEVERAGE, LIVE_POLICY, MIN_ADV_USD, MIN_NAMES,
    REBALANCE_DAYS, UNIVERSE, VOL_TARGET, Z_WINDOW, summary,
)

MIN_ADV = MIN_ADV_USD
# Not spec-owned: estimation choices local to this harness.
MIN_PERIODS, VOL_LOOKBACK = 120, 63
SAMPLE_START = "2005-01-03"
COSTS_BP = [5, 10, 15, 20, 30]

# The width sweep is a DELIBERATE variation -- characterising the policy class is
# the entire point of this script, and H8 permits it explicitly. The live width
# is unioned in so the sweep always contains the deployed policy, whatever it is.
BAND_SWEEP = sorted({0.002, 0.004, 0.008, 0.016, 0.024, 0.032,
                     0.048, 0.064, 0.096, 0.128, BAND_WIDTH})


def build_targets():
    """Frictionless daily target weights, exactly as the sleeve would build them."""
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    P, N = P[P.ticker.isin(UNIVERSE)], N[N.ticker.isin(UNIVERSE)]
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    piv = lambda c: d.pivot_table(index="date", columns="ticker", values=c).sort_index()
    px, nav, vol = piv("close"), piv("nav"), piv("volume")

    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)

    tgt = pd.DataFrame(0.0, index=z.index, columns=UNIVERSE)
    start = z.index.searchsorted(pd.Timestamp(SAMPLE_START))
    for i in range(start, len(z.index)):
        row = z.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV]]
        if len(row) < MIN_NAMES:
            tgt.iloc[i] = tgt.iloc[i - 1]          # hold; nothing eligible
            continue
        w = -(row - row.mean())
        w = w / w.abs().sum()
        hist = ret[list(row.index)].iloc[:i + 1].mul(w, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w * scal).reindex(UNIVERSE).fillna(0.0).values
    T = tgt.iloc[start:]
    return T, ret.reindex(T.index)[UNIVERSE].fillna(0.0)


def calendar(T, k):
    """Refresh every k days, hold in between."""
    H = T.copy()
    keep = np.zeros(len(T), bool)
    keep[::k] = True
    H[~keep] = np.nan
    return H.ffill().fillna(0.0)


def band(T, b):
    """Hold unless a name is more than b from target; then trade to the EDGE."""
    A, cur = T.values, np.zeros(T.shape[1])
    H = np.zeros_like(A)
    for i in range(len(A)):
        gap = A[i] - cur
        mv = np.abs(gap) > b
        cur = cur.copy()
        cur[mv] = A[i][mv] - np.sign(gap[mv]) * b
        H[i] = cur
    return pd.DataFrame(H, index=T.index, columns=T.columns)


def evaluate(H, R):
    """H.loc[t] = weights decided at t. MOC fills at t+1 -> earns the t+2 return."""
    pnl = (H.shift(2).fillna(0.0) * R).sum(axis=1)
    turn = H.diff().abs().sum(axis=1).fillna(0.0)
    gross_v = H.abs().sum(axis=1).mean()
    return dict(
        gross_sr=pnl.mean() / pnl.std() * np.sqrt(252),
        ann_ret=pnl.mean() * 252,
        vol=pnl.std() * np.sqrt(252),
        turn=turn.sum() * 252 / len(pnl),
        hold=gross_v / turn.mean() if turn.mean() > 0 else np.inf,
        turn_series=turn,
    )


def row(label, H, R):
    r = evaluate(H, R)
    nets = [(r["ann_ret"] - r["turn"] * c / 1e4) / r["vol"] for c in COSTS_BP]
    print(f"{label:<22}{r['gross_sr']:8.2f}{r['ann_ret'] * 100:7.2f}"
          f"{r['vol'] * 100:7.2f}{r['turn']:9.1f}{r['hold']:9.1f}"
          + "".join(f"{n:11.2f}" for n in nets))
    return r, nets


# --- labels -----------------------------------------------------------------
# Which row is LIVE is read from the frozen spec, never asserted here. Three
# scripts in this directory labelled "calendar 2d (LIVE)" for four days after
# the band replaced it on 2026-09-06, and PLAN.md carried the same claim in five
# tables. A label that can go stale silently is the same bug as a hardcoded
# baseline, one layer up.
LIVE_TAG = "  <-- LIVE"


def _cal_is_live(k: int) -> bool:
    from scripts.cef.spec import BAND_IS_LIVE
    return (not BAND_IS_LIVE) and k == REBALANCE_DAYS


def _band_is_live(b: float) -> bool:
    from scripts.cef.spec import BAND_IS_LIVE
    return BAND_IS_LIVE and abs(b - BAND_WIDTH) < 1e-12


def _lab_cal(k: int) -> str:
    return f"calendar {k}d" + (LIVE_TAG if _cal_is_live(k) else "")


def _lab_band(b: float) -> str:
    return f"band {b * 100:.1f}%" + (LIVE_TAG if _band_is_live(b) else "")


def main():
    T, R = build_targets()
    print(summary())
    print(f"sample {T.index[0].date()} .. {T.index[-1].date()}  ({len(T)} days)\n")

    hdr = (f"{'policy':<22}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'turn/yr':>9}{'hold(d)':>9}"
           + "".join(f"{'net@' + str(c) + 'bp':>11}" for c in COSTS_BP))
    print(hdr, "-" * len(hdr), sep="\n")
    for k in (1, 2, 5, 10):
        row(f"calendar {k}d" + (LIVE_TAG if _cal_is_live(k) else ""), calendar(T, k), R)
    for b in BAND_SWEEP:
        row(f"band {b * 100:.1f}% of gross" + (LIVE_TAG if _band_is_live(b) else ""),
            band(T, b), R)

    print("\n\n=== matched on turnover: the only honest comparison ===")
    print("H2: pairs must match turn/yr within 5%. Note that pairing calendar 5d")
    print("with the LIVE band is a near-exact match, where the retired 6.4%")
    print("baseline this block used until 2026-09-10 was ~19% adrift -- i.e. that")
    print("row was violating the rule it exists to demonstrate.\n")
    print(f"{'policy':<22}{'turn/yr':>9}{'grossSR':>9}{'net@15bp':>10}")
    for lab, H in [("calendar 1d", calendar(T, 1)), ("band 0.2%", band(T, 0.002)),
                   (_lab_cal(2), calendar(T, 2)), (_lab_band(0.016), band(T, 0.016)),
                   ("calendar 5d", calendar(T, 5)), (_lab_band(BAND_WIDTH), band(T, BAND_WIDTH))]:
        r = evaluate(H, R)
        net = (r["ann_ret"] - r["turn"] * 15 / 1e4) / r["vol"]
        print(f"{lab:<22}{r['turn']:9.1f}{r['gross_sr']:9.2f}{net:10.2f}")

    print("\n\n=== turnover stability, 2015+ (universe stable; pre-2010 is degenerate) ===")
    print("Recorded against an earlier draft of PLAN.md, which claimed the band")
    print("would be MORE turnover-stable. It is not. See PLAN.md 0.3 and 2.3.\n")
    eras = [("2015-2019", "2015", "2019"), ("2020-2022", "2020", "2022"),
            ("2023-2026", "2023", "2026")]
    print(f"{'policy':<22}" + "".join(f"{e[0]:>11}" for e in eras) + f"{'mean':>8}{'sd/mean':>9}")
    era_widths = sorted({0.016, 0.024, BAND_WIDTH})
    for lab, H in ([("calendar 1d", calendar(T, 1)), (_lab_cal(2), calendar(T, 2)),
                    ("calendar 5d", calendar(T, 5))]
                   + [(_lab_band(b), band(T, b)) for b in era_widths]):
        t = evaluate(H, R)["turn_series"]
        v = np.array([t.loc[a:b].mean() * 252 for _, a, b in eras])
        print(f"{lab:<22}" + "".join(f"{x:11.1f}" for x in v)
              + f"{v.mean():8.1f}{v.std() / v.mean():9.1%}")

    print("\n\n=== sensitivity to being wrong about cost — the robustness that matters ===")
    print(f"{'policy':<22}{'turn/yr':>9}{'net@5bp':>10}{'net@30bp':>10}{'span':>8}{'flips?':>9}")
    widths = sorted({0.024, 0.064, BAND_WIDTH})
    for lab, H in ([("calendar 1d", calendar(T, 1)), (_lab_cal(2), calendar(T, 2)),
                    ("calendar 5d", calendar(T, 5))]
                   + [(_lab_band(b), band(T, b)) for b in widths]):
        r = evaluate(H, R)
        lo = (r["ann_ret"] - r["turn"] * 5 / 1e4) / r["vol"]
        hi = (r["ann_ret"] - r["turn"] * 30 / 1e4) / r["vol"]
        print(f"{lab:<22}{r['turn']:9.1f}{lo:10.2f}{hi:10.2f}{lo - hi:8.2f}"
              f"{('YES' if hi < 0 else 'no'):>9}")


if __name__ == "__main__":
    main()
