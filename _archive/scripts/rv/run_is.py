"""In-sample research run (CREDIT_RV_PREREG.md §6: IS through 2023-12-31).

Sample starts 2012-01-01: before that the credit ETF complex does not exist
(zero names pass the mask 1993-2006, 3.4/day 2007-2011).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals, TRADEABLE
from src.strategies.credit_rv.book import BookConfig, simulate, stats
from src.strategies.credit_rv.trials import log_trial

IS_START, IS_END = pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31")

# Amendment 1.3: economic admissibility. E[edge]=14bp at |s|>=2, require 3x margin
# on the round trip => half_spread <= 14/3/2 = 2.33bp. A formula, not a name list.
EDGE_BP, MARGIN = 14.0, 3.0
MAX_HALF_SPREAD_BP = EDGE_BP / MARGIN / 2.0


def load():
    panel = pd.read_parquet(ROOT / "data/rv/etf_panel.parquet")
    rets = panel.pivot(index="date", columns="ticker", values="ret_total").sort_index()
    dv = (panel.assign(dv=panel.close * panel.volume)
               .pivot(index="date", columns="ticker", values="dv").sort_index())
    rf = pd.read_parquet(ROOT / "data/riskfree_daily.parquet").set_index("date")["rf_daily"]
    rf.index = pd.to_datetime(rf.index)
    costs = yaml.safe_load((ROOT / "config/costs_rv.yaml").read_text())
    hs = {k: v["half_spread_bp"] for k, v in costs["tickers"].items()}
    return rets, dv, rf, hs


def admissible(hs: dict[str, float], verbose: bool = True) -> list[str]:
    keep = [t for t in TRADEABLE if hs.get(t, 99) <= MAX_HALF_SPREAD_BP]
    drop = [t for t in TRADEABLE if t not in keep]
    if verbose:
        print(f"cost filter (half_spread <= {MAX_HALF_SPREAD_BP:.2f}bp)")
        print(f"  admissible ({len(keep)}): {keep}")
        print(f"  excluded   ({len(drop)}): {[(t, hs.get(t)) for t in drop]}")
    return keep


def run(scfg, bcfg, tag, note="", start=IS_START, end=IS_END, cached=None, **kw):
    rets, dv, rf, hs = load()
    rets_w = rets[rets.index <= end]
    dv_w = dv[dv.index <= end]
    sig = cached if cached is not None else compute_signals(rets_w, rf, dv_w, scfg)
    keep = sig["s_blend"].index >= pd.Timestamp(start)
    res = simulate(sig["s_blend"][keep], sig["tradeable_mask"][keep], sig["betas"],
                   sig["excess_returns"], dv_w, hs, rf, bcfg,
                   s_entry=scfg.s_entry, s_exit=scfg.s_exit, s_stop=scfg.s_stop,
                   sigma_eq=sig["sigma_eq"], kappa=sig["kappa"], **kw)
    st = stats(res["path"], rf, res["median_hold"])
    st["tag"] = tag
    log_trial(tag, st, note=note)
    return res, st, sig


def show(st: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    for k, v in st.items():
        print(f"  {k:22s} {v:>14}" if isinstance(v, str) else f"  {k:22s} {v:14.4f}")


if __name__ == "__main__":
    _, _, _, hs = load()
    # Amendment 2 supersedes the blanket name filter: cost admissibility is now
    # evaluated per trade against that trade's own OU-implied expected edge, so a
    # wide name is tradeable when the dislocation is large enough to pay for it.
    scfg = SignalConfig()
    bcfg = BookConfig()
    res, st, sig = run(scfg, bcfg, "T003_amendment1",
                       note="s_entry=2.0, cost filter, concentrated sizing, turnover fixes")
    show(st, "IS: amendment 1")

    out = ROOT / "results/credit_rv"
    out.mkdir(parents=True, exist_ok=True)
    res["path"].to_parquet(out / "is_path.parquet")
    res["weights"].to_parquet(out / "is_weights.parquet")
    res["trades"].to_csv(out / "is_trades.csv", index=False)
    json.dump(st, open(out / "is_stats.json", "w"), indent=2, default=float)
    for k in ["s_blend", "tradeable_mask", "halflife"]:
        sig[k].to_parquet(out / f"is_{k}.parquet")

    ca = res["cost_by_leg"].sort_values(ascending=False)
    tn = res["turnover_by_leg"]
    print("\n--- cost attribution (USD over IS, $1M book) ---")
    df = pd.DataFrame({"cost_usd": ca, "turnover_usd": tn.reindex(ca.index)})
    df["cost_bp_of_turnover"] = df.cost_usd / df.turnover_usd.replace(0, float("nan")) * 1e4
    print(df[df.cost_usd > 0].round(1).to_string())
    print(f"\ntotal cost ${ca.sum():,.0f}  total turnover ${tn.sum():,.0f}")
