"""Build the RV universe cost model.

The after-hours IBKR probe (results/credit_rv/ibkr_spread_probe.csv) is unusable as
a cost estimate - it printed HYG at 13.9bp half against a true RTH spread under 1bp,
and FALN at 1490bp on a stale book.  So half-spreads are anchored the way
config/costs.yaml already does it for the older names:

  anchor (b)  one-tick floor  = $0.005 / price * 1e4   (penny-quoted US ETFs)
  anchor (a)  liquidity tier  = a multiple of that floor reflecting AUM/volume

and the result is rounded UP.  Tiers are assigned from trailing dollar volume,
which we measure here rather than assume.  Every number is an ESTIMATE pending the
RTH re-probe; the strategy must clear its cost gate at 2x these values.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "data" / "rv" / "etf_panel.parquet"
OUT_YAML = ROOT / "config" / "costs_rv.yaml"
OUT_CSV = ROOT / "results" / "credit_rv" / "cost_model.csv"

# multiple of the one-tick half-spread floor, by measured liquidity tier
TIER_MULT = {1: 1.0, 2: 1.75, 3: 3.0, 4: 5.0}
TIER_ADV = [  # (tier, minimum trailing median dollar volume)
    (1, 500e6),
    (2, 100e6),
    (3, 20e6),
    (4, 0.0),
]


def main() -> int:
    p = pd.read_parquet(PANEL)
    p = p.sort_values(["ticker", "date"])
    recent = p[p["date"] >= p["date"].max() - pd.Timedelta(days=180)]

    rows = []
    for t, g in recent.groupby("ticker"):
        px = float(g["close"].median())
        adv = float((g["close"] * g["volume"]).median())
        tier = next(tr for tr, lo in TIER_ADV if adv >= lo)
        tick_floor_bp = 0.005 / px * 1e4
        half_bp = float(np.ceil(tick_floor_bp * TIER_MULT[tier] * 10) / 10)
        rows.append({
            "ticker": t, "price": round(px, 2), "adv_usd": round(adv),
            "tier": tier, "tick_floor_half_bp": round(tick_floor_bp, 3),
            "half_spread_bp": half_bp,
        })

    df = pd.DataFrame(rows).sort_values(["tier", "ticker"])
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    cfg = {
        "_provenance": (
            "tick floor ($0.005/price) x liquidity-tier multiple, rounded up; "
            "tiers from trailing-180d median dollar volume measured in "
            "scripts/rv/build_cost_model.py. ESTIMATE pending RTH IBKR re-probe. "
            "After-hours probe 2026-07-28 20:0x ET was unusable (HYG 13.9bp half)."
        ),
        "commission_usd_per_trade": 0.0,
        "slippage_extra_bp": 0.0,
        "impact_coefficient": 1.0,
        "max_participation_pct": 2.0,
        "financing_spread_bp": 150.0,
        "short_borrow_bp": 50.0,
        "tickers": {r["ticker"]: {"half_spread_bp": r["half_spread_bp"]}
                    for _, r in df.iterrows()},
    }
    OUT_YAML.write_text(yaml.safe_dump(cfg, sort_keys=False))

    print(df.to_string(index=False))
    print(f"\n-> {OUT_YAML}\n-> {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
