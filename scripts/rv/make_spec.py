"""Freeze a deployable spec for the credit RV sleeve from the measured cost grid.

Reads `measured_best_cell.json` (written by rerun_measured_costs.py) and the
measured spreads, and emits `ops/specs/credit_rv.frozen.json` in the shape
`src.deploy.registry.validate_spec` accepts.

The spec embeds the MEASURED half-spread per name, so the live risk/reporting path
prices a trade with the same numbers the backtest used. If those two ever diverge,
the paper P&L stops being evidence about the backtest.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RES = ROOT / "results" / "credit_rv"
SPECS = ROOT / "ops" / "specs"
SPECS.mkdir(parents=True, exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--target-vol", type=float, default=0.13)
    ap.add_argument("--gross", type=float, default=None,
                    help="override gross leverage; default from the measured cell")
    ap.add_argument("--status", default="PAPER")
    ap.add_argument("--out", default=str(SPECS / "credit_rv.frozen.json"))
    args = ap.parse_args()

    best = json.loads((RES / "measured_best_cell.json").read_text())
    meas = pd.read_csv(RES / "ibkr_measured_spreads.csv")

    half = {}
    for _, r in meas.iterrows():
        v = r.get("close_half_spread_bp")
        if pd.isna(v):
            v = r.get("half_spread_bp_median")
        if pd.notna(v):
            half[r["ticker"]] = round(float(v), 4)

    universe = list(best["names"]) if isinstance(best.get("names"), list) else \
        [s.strip().strip("'\"") for s in str(best["names"]).strip("[]").split(",")]
    universe = [t for t in universe if t in half]

    gross = float(args.gross) if args.gross is not None else 1.0

    spec = {
        "spec_id": f"credit_rv.v1.{datetime.now(ZoneInfo('America/New_York')):%Y%m%d}",
        "status": args.status,
        "capital_usd": args.capital,
        "allocation": {"type": "credit_rv_statarb"},
        "frozen": {
            "universe": universe,
            "signal_price": "hl_mid",
            "w_beta": 120,
            "w_resid": 60,
            "theta": 0.60,
            "smooth": int(best["smooth"]),
            "gross_leverage": gross,
            "max_weight_per_name": 0.35,
            "min_abs_weight": 0.005,
            "min_names": 6,
            "min_names_neutral": 7,
            "half_spread_bp": {t: half[t] for t in universe},
            "cost_provenance": "IBKR historical BID_ASK, RTH, closing-window "
                               "median; scripts/rv/fetch_ibkr_spreads.py",
        },
        "risk": {
            "target_vol": args.target_vol,
            "kill_drawdown": 0.25,
            "halve_drawdown": 0.15,
        },
        "provenance": {
            "frozen_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "in_sample_sharpe": best.get("sr_net"),
            "in_sample_cagr_at_13v": best.get("cagr13"),
            "earn_bp_per_turnover": best.get("earn_bp_per_turn"),
            "pay_bp_per_turnover": best.get("pay_bp_per_turn"),
            "selected_max_half_spread_bp": best.get("max_hs"),
            "note": "Signal price is the (H+L)/2 mid. A close-built signal is "
                    "bid-ask bounce (FINDINGS.md §8e) and is rejected by the "
                    "registry validator.",
        },
    }

    out = Path(args.out)
    out.write_text(json.dumps(spec, indent=2))

    from src.deploy import registry, sleeves  # noqa: F401
    registry.validate_spec(spec)
    sleeve = registry.build_sleeve(spec, args.capital)

    print(f"wrote {out}")
    print(f"  validates OK, builds {type(sleeve).__name__}")
    print(f"  universe ({len(universe)}): {universe}")
    print(f"  smooth {spec['frozen']['smooth']}  gross {gross}  "
          f"capital ${args.capital:,.0f}")
    print(f"  warmup needed: {sleeve.history_warmup_trading_days()} trading days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
