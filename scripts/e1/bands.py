"""E1 as PRE-REGISTERED: cost-derived OU bands, not continuous z-weighting.

`economics.py` tested a continuous `w ∝ -z` book. That is NOT the specification in
E1_PREREG.md §3.3, which requires entry/exit thresholds derived from the OU
optimal-stopping solution GIVEN ROUND-TRIP COST. The distinction is the whole
strategy, for one reason:

    A cost-derived band stands down on its own when the dislocation is smaller
    than the cost of capturing it.

Continuous weighting always holds a position, so in the post-2017 regime — where
the relative premium's dispersion has collapsed from ~188bp to ~4bp — it trades
constantly into an edge that no longer clears the spread and bleeds. A banded
strategy simply stops trading. That is the mechanism behaving correctly, not a
regime filter bolted on afterwards.

ENTRY RULE (per §6, applied per-trade rather than in aggregate)
--------------------------------------------------------------
The relative premium is OU around μ. Entering at deviation `d` has expected
convergence gain `d` (it reverts to μ). So require, at the moment of entry:

    |d|  >=  EDGE_MULT x round_trip_cost

with EDGE_MULT = 2.5, the workflow §5.6 gate. Exit when the deviation has decayed
to EXIT_FRAC of the entry band, or on the §4.4 hard stop at |z| > 4.

Everything is point-in-time: μ, σ and the cost are all computed from data strictly
before the decision date, and the position is executed at the NEXT close.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "e1"

IS_END = pd.Timestamp("2019-12-31")
OOS_END = pd.Timestamp("2023-12-31")
HOLDOUT_END = pd.Timestamp("2026-07-24")

EDGE_MULT = 2.5          # workflow §5.6 gate, applied per trade
EXIT_FRAC = 0.25         # exit when deviation decays to this fraction of entry band
Z_STOP = 4.0             # §4.4 hard stop
WIN = 250                # trailing PIT window for mu/sigma


def load():
    df = pd.read_parquet(OUT / "e1_panel.parquet")
    df["date"] = pd.to_datetime(df["date"])
    w = lambda c: df.pivot(index="date", columns="ticker", values=c).sort_index()
    return w("pd_mid"), w("ret_total")


def cost_bp():
    meas = pd.read_csv(ROOT / "results/credit_rv/ibkr_measured_spreads.csv").set_index("ticker")
    def half(t):
        v = meas.loc[t].get("close_half_spread_bp")
        return float(v) if pd.notna(v) else float(meas.loc[t]["half_spread_bp_median"])
    # entering AND exiting the pair crosses both legs twice
    return 2.0 * (half("HYG") + half("JNK"))


def backtest(s, spread_ret, rt_cost_bp, borrow, edge_mult=EDGE_MULT):
    """Banded OU trade on the relative premium. Returns a per-day frame."""
    mu = s.rolling(WIN).mean().shift(1)          # PIT: strictly prior data
    sd = s.rolling(WIN).std().shift(1)
    band = edge_mult * rt_cost_bp / 1e4          # in return units

    pos, rows = 0.0, []
    entry_dev = np.nan
    for t in s.index:
        d = s.loc[t] - mu.loc[t] if pd.notna(mu.loc[t]) else np.nan
        z = d / sd.loc[t] if pd.notna(sd.loc[t]) and sd.loc[t] > 0 else np.nan
        prev = pos
        if pd.notna(d):
            if pos == 0.0:
                if abs(d) > band:
                    pos = -np.sign(d)            # rich HYG (d>0) -> short the pair
                    entry_dev = abs(d)
            else:
                if abs(d) <= EXIT_FRAC * band:
                    pos, entry_dev = 0.0, np.nan   # converged — take the profit
                elif pd.notna(z) and abs(z) > Z_STOP:
                    pos, entry_dev = 0.0, np.nan   # §4.4 hard stop
        rows.append((t, d, z, prev, pos))

    f = pd.DataFrame(rows, columns=["date", "dev", "z", "pos_prev", "pos"]).set_index("date")
    f["turn"] = (f["pos"] - f["pos_prev"]).abs()
    # decide at T, execute at T+1 close
    f["ret"] = spread_ret.reindex(f.index)
    f["gross"] = f["pos"].shift(1) * f["ret"]
    # cost: each unit of position change crosses both legs once (half the round trip)
    f["cost"] = f["turn"] * (rt_cost_bp / 2.0) / 1e4
    bb = borrow.reindex(f.index).ffill() / 100.0 / 252.0
    f["borrow"] = f["pos"].abs().shift(1).fillna(0.0) * bb
    f["net"] = f["gross"] - f["cost"] - f["borrow"]
    return f


def stats(f, label):
    n = f["net"].dropna()
    if len(n) < 100:
        return None
    trades = int((f["turn"] > 0).sum() / 2)
    days_in = float((f["pos"] != 0).mean())
    sr = n.mean() / n.std() * np.sqrt(252) if n.std() > 0 else np.nan
    g = f["gross"].dropna()
    gsr = g.mean() / g.std() * np.sqrt(252) if g.std() > 0 else np.nan
    tot_turn = f["turn"].sum()
    return dict(period=label, n_days=len(n), trades=trades,
                pct_days_in_market=days_in * 100,
                gross_pct_yr=g.mean() * 252 * 100,
                cost_pct_yr=f["cost"].mean() * 252 * 100,
                borrow_pct_yr=f["borrow"].mean() * 252 * 100,
                net_pct_yr=n.mean() * 252 * 100,
                gross_sharpe=gsr, net_sharpe=sr,
                edge_bp_per_turn=(g.sum() / tot_turn * 1e4) if tot_turn > 0 else np.nan)


def main() -> int:
    pd_mid, ret_c = load()
    s = (pd_mid["HYG"] - pd_mid["JNK"]).dropna()
    spread_ret = ((ret_c["HYG"] - ret_c["JNK"]) / 2.0).reindex(s.index)
    rt = cost_bp()
    fin = pd.read_parquet(ROOT / "data/financing_curve.parquet")
    fin["date"] = pd.to_datetime(fin["date"])
    borrow = fin.set_index("date")["r_short_etf_pct"]

    print(f"measured round-trip cost (both legs, in and out): {rt:.2f}bp")
    print(f"entry band = {EDGE_MULT} x cost = {EDGE_MULT*rt:.2f}bp of relative premium\n")

    f = backtest(s, spread_ret, rt, borrow)
    f.to_parquet(OUT / "bands_path.parquet")

    rows = []
    for label, m in (("IS  2007-2019", f.index <= IS_END),
                     ("OOS 2020-2023", (f.index > IS_END) & (f.index <= OOS_END)),
                     ("IS+OOS", f.index <= OOS_END)):
        r = stats(f[m], label)
        if r:
            rows.append(r)
    res = pd.DataFrame(rows)
    print("BANDED STRATEGY (holdout 2024+ NOT shown — still sealed)")
    print(res.round(2).to_string(index=False))

    print("\nby year (net %/yr, trades, % of days holding a position):")
    print(f"{'yr':>5s} {'trades':>7s} {'%days_in':>9s} {'gross%':>8s} {'cost%':>7s} {'net%':>8s}")
    for y, g in f[f.index <= HOLDOUT_END].groupby(f[f.index <= HOLDOUT_END].index.year):
        st = stats(g, str(y))
        if st:
            print(f"{y:>5d} {st['trades']:>7d} {st['pct_days_in_market']:>8.1f}% "
                  f"{st['gross_pct_yr']:>7.2f}% {st['cost_pct_yr']:>6.2f}% {st['net_pct_yr']:>7.2f}%")

    res.to_csv(OUT / "bands_summary.csv", index=False)
    json.dump({"round_trip_bp": rt, "edge_mult": EDGE_MULT,
               "entry_band_bp": EDGE_MULT * rt, "exit_frac": EXIT_FRAC,
               "z_stop": Z_STOP, "window": WIN},
              open(OUT / "bands_params.json", "w"), indent=2)
    print(f"\nwrote {OUT/'bands_summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
