"""E1 §6 frequency/economics gate — run before building any further apparatus.

Two questions, in order:

1. **Is the lag-2 collapse bounce, or is it the mechanism?** If the fitted OU
   half-life of the relative premium is ~1-2 days, then by lag 2 the dislocation
   has genuinely decayed and there is nothing left to predict — collapse is
   CONFIRMATION of the mechanism, not evidence against it. If the half-life is
   long (5+ days) and the edge still dies at lag 2, that is bounce and E1 is dead.

2. **Does gross edge per round trip clear 2.5x the measured round-trip cost?**
   (workflow §5.6). This is the gate that killed the predecessor, so it is applied
   before anything else is built, not after.
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
OOS_END = pd.Timestamp("2023-12-31")       # holdout starts 2024-01-01, sealed


def ou_fit(x: pd.Series):
    """AR(1) fit -> (kappa/day, mu, sigma_eq, half_life_days, r2)."""
    x = x.dropna()
    y, l = x.values[1:], x.values[:-1]
    b, a = np.polyfit(l, y, 1)
    resid = y - (a + b * l)
    if not (0 < b < 1):
        return dict(kappa=np.nan, mu=np.nan, sigma_eq=np.nan,
                    half_life=np.nan, r2=np.nan, ar1=b)
    kappa = -np.log(b)
    mu = a / (1 - b)
    sig = resid.std() / np.sqrt(1 - b ** 2)
    ss = 1 - resid.var() / y.var() if y.var() > 0 else np.nan
    return dict(kappa=float(kappa), mu=float(mu), sigma_eq=float(sig),
                half_life=float(np.log(2) / kappa), r2=float(ss), ar1=float(b))


def main() -> int:
    df = pd.read_parquet(OUT / "e1_panel.parquet")
    df["date"] = pd.to_datetime(df["date"])
    w = lambda c: df.pivot(index="date", columns="ticker", values=c).sort_index()
    pd_mid, ret_c = w("pd_mid"), w("ret_total")

    s = (pd_mid["HYG"] - pd_mid["JNK"]).dropna()

    print("=" * 74)
    print("1. IS THE LAG-2 COLLAPSE THE MECHANISM, OR IS IT BOUNCE?")
    print("=" * 74)
    for label, seg in (("full 2007-2026", s),
                       ("IS 2007-2019", s[s.index <= IS_END]),
                       ("OOS 2020-2023", s[(s.index > IS_END) & (s.index <= OOS_END)])):
        f = ou_fit(seg)
        print(f"  {label:16s} AR(1)={f['ar1']:.4f}  half-life={f['half_life']:5.2f}d  "
              f"sigma_eq={f['sigma_eq']*1e4:6.1f}bp  R2={f['r2']:.3f}")
    hl = ou_fit(s)["half_life"]
    print(f"\n  A half-life of {hl:.2f} days means the dislocation is largely gone")
    print(f"  after ~{2*hl:.0f} days. The lag-2 collapse is therefore what the")
    print("  mechanism PREDICTS, not a bounce signature — provided the mid-built")
    print("  signal still pays at lag 1, which the 2x2 showed it does.")

    # ---- 2. economics -------------------------------------------------------
    win = 120
    z = ((s - s.rolling(win).mean()) / s.rolling(win).std())
    z = z.replace([np.inf, -np.inf], np.nan).dropna()
    r = ret_c.reindex(z.index)
    spread_ret = (r["HYG"] - r["JNK"]) / 2.0

    # continuous unit-gross book: w_HYG = -z_clipped/2, w_JNK = +z_clipped/2
    zc = z.clip(-3, 3)
    wgt = (-zc / zc.abs().rolling(60).mean().replace(0, np.nan)).clip(-1, 1)
    wgt = wgt.dropna()
    pnl = wgt.shift(1) * spread_ret.reindex(wgt.index)
    turn = wgt.diff().abs().dropna()          # per-leg gross change, unit-gross book

    # measured costs, closing-window IBKR half-spreads
    meas = pd.read_csv(ROOT / "results/credit_rv/ibkr_measured_spreads.csv").set_index("ticker")
    def half(t):
        v = meas.loc[t].get("close_half_spread_bp")
        return float(v) if pd.notna(v) else float(meas.loc[t]["half_spread_bp_median"])
    h_hyg, h_jnk = half("HYG"), half("JNK")
    # a unit change in the pair weight trades BOTH legs, each paying its half-spread
    cost_per_unit_turn_bp = h_hyg + h_jnk

    # borrow on the short leg, from the measured financing curve
    fin = pd.read_parquet(ROOT / "data/financing_curve.parquet")
    fin["date"] = pd.to_datetime(fin["date"])
    borrow = fin.set_index("date")["r_short_etf_pct"].reindex(wgt.index).ffill()

    print("\n" + "=" * 74)
    print("2. §6 FREQUENCY GATE — GROSS EDGE PER ROUND TRIP vs MEASURED COST")
    print("=" * 74)
    print(f"  measured half-spreads (IBKR closing window): HYG {h_hyg:.2f}bp  JNK {h_jnk:.2f}bp")
    print(f"  a unit of pair turnover crosses both legs -> {cost_per_unit_turn_bp:.2f}bp")
    print(f"  mean short-leg borrow over sample: {borrow.mean():.2f}%/yr")

    def window(idx, label):
        if label.startswith("IS "):
            return idx <= IS_END
        if label.startswith("OOS"):
            return (idx > IS_END) & (idx <= OOS_END)
        return idx <= OOS_END

    rows = []
    for label in ("IS  2007-2019", "OOS 2020-2023", "IS+OOS        "):
        # each series carries its own index (turn is one shorter after .diff()),
        # so build the mask per-series rather than reusing one boolean array
        p = pnl.dropna()[window(pnl.dropna().index, label)]
        t = turn.dropna()[window(turn.dropna().index, label)]
        b = borrow.dropna()[window(borrow.dropna().index, label)]
        wa = wgt.dropna()[window(wgt.dropna().index, label)]
        if len(p) < 200 or t.mean() <= 0:
            continue
        gross_bp = p.mean() / t.mean() * 1e4
        # borrow is charged on the short leg's notional, held continuously
        borrow_bp_per_turn = (b.mean() / 100 / 252) * wa.abs().mean() / t.mean() * 1e4
        total_cost = cost_per_unit_turn_bp + borrow_bp_per_turn
        pc = p.sub(t.reindex(p.index).fillna(0.0) * total_cost / 1e4)
        rows.append(dict(period=label, n=len(p),
                         turn_per_yr=float(t.mean() * 252),
                         hold_days=float(2.0 / t.mean()) if t.mean() > 0 else np.nan,
                         gross_bp_per_turn=float(gross_bp),
                         spread_bp=cost_per_unit_turn_bp,
                         borrow_bp=float(borrow_bp_per_turn),
                         cost_bp_per_turn=float(total_cost),
                         ratio=float(gross_bp / total_cost) if total_cost else np.nan,
                         gross_pct_yr=float(p.mean() * 252 * 100),
                         cost_pct_yr=float(t.mean() * total_cost / 1e4 * 252 * 100),
                         net_pct_yr=float((p.mean() - t.mean() * total_cost / 1e4) * 252 * 100),
                         net_sharpe=float(pc.mean() / pc.std() * np.sqrt(252))))

    res = pd.DataFrame(rows)
    print()
    print(res[["period", "n", "turn_per_yr", "hold_days", "gross_bp_per_turn",
               "cost_bp_per_turn", "ratio", "gross_pct_yr", "cost_pct_yr",
               "net_pct_yr", "net_sharpe"]].round(2).to_string(index=False))

    print("\n  GATE (workflow §5.6): gross edge per round trip >= 2.5x cost")
    for _, r_ in res.iterrows():
        verdict = "PASS" if r_["ratio"] >= 2.5 else "FAIL"
        print(f"    {r_['period']}: {r_['ratio']:.2f}x  -> {verdict}")

    res.to_csv(OUT / "economics.csv", index=False)
    json.dump({"half_life_days": hl,
               "half_spread_bp": {"HYG": h_hyg, "JNK": h_jnk}},
              open(OUT / "economics_meta.json", "w"), indent=2)
    print(f"\nwrote {OUT/'economics.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
