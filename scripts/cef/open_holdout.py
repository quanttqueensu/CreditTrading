"""Open the sealed 2024-01+ holdout for the CEF discount sleeve. ONCE.

Pre-registration: `results/cef/HOLDOUT_PREREG.md`, written before this ran.
Result: `results/cef/HOLDOUT_OPENED.json`, written once and never overwritten.

Parameters are READ FROM THE FROZEN SPEC rather than restated here, so the thing
tested cannot drift from the thing deployed. The reference configuration (the one
running this morning) is reported alongside, but the choice between them was made
on pre-2024 data and is not revisited on this evidence.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.cef.validate import load_raw  # noqa: E402
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

SPEC = REPO / "ops/specs/cef_discount.frozen.json"
OUT = REPO / "results/cef/HOLDOUT_OPENED.json"
HOLDOUT_START = "2024-01-01"
CM = SCENARIOS["base"]


def deep_get(o, k):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        for v in o.values():
            r = deep_get(v, k)
            if r is not None:
                return r
    return None


def evaluate(disc, px, adv, hs, ret, z_window, hold, shift, spec, start, end):
    idx = px.index[(px.index >= pd.Timestamp(start)) & (px.index <= pd.Timestamp(end))]
    mu = disc.rolling(z_window, min_periods=max(10, z_window // 2)).mean().shift(1)
    sd = disc.rolling(z_window, min_periods=max(10, z_window // 2)).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4).loc[idx]
    elig = (adv.fillna(0.0) >= float(deep_get(spec, "min_adv_usd"))).loc[idx]
    minn = int(deep_get(spec, "min_names"))
    W = pd.DataFrame(0.0, index=idx, columns=px.columns)
    for t in idx[::hold]:
        row = z.loc[t][elig.loc[t]].dropna()
        if len(row) < minn:
            continue
        v = -(row - row.mean())
        if v.abs().sum() < 1e-9:
            continue
        W.loc[t, v.index] = (v / v.abs().sum()).values
    W = (W.replace(0.0, np.nan).ffill(limit=hold - 1) if hold > 1
         else W.replace(0.0, np.nan)).fillna(0.0)
    r = ret.loc[idx]
    raw = (W.shift(1).fillna(0.0) * r).sum(axis=1)
    rv = raw.shift(1).rolling(63, min_periods=30).std() * np.sqrt(252)
    vt = float(deep_get(spec, "vol_target_annual"))
    W = W.mul((vt / rv.replace(0, np.nan)).clip(0.2, 2.5).fillna(1.0), axis=0)
    held = W.shift(shift).fillna(0.0)
    gross = (held * r).sum(axis=1)
    dw = held.diff().abs().fillna(held.abs())
    cost = (dw * hs.loc[idx] / 1e4).sum(axis=1)
    net = (gross - cost).dropna()
    eq = (1 + net).cumprod()
    sr = lambda s: float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else float("nan")
    return {
        "n_days": int(len(net)),
        "gross_sharpe": round(sr(gross), 3),
        "net_sharpe": round(sr(net), 3),
        "net_t_stat": round(float(net.mean() / net.std() * np.sqrt(len(net))), 2),
        "cagr_pct": round(float(100 * (eq.iloc[-1] ** (252 / len(net)) - 1)), 2),
        "vol_pct": round(float(net.std() * np.sqrt(252) * 100), 2),
        "max_dd_pct": round(float(100 * (eq / eq.cummax() - 1).min()), 2),
        "turnover_per_yr": round(float(dw.sum(axis=1).mean() * 252), 1),
        "cost_pct_of_gross": (round(float(100 * cost.sum() / gross.sum()), 1)
                              if gross.sum() != 0 else None),
        "by_year": {str(y): round(sr(net[net.index.year == y]), 2)
                    for y in sorted(set(net.index.year))},
    }


def main() -> int:
    if OUT.exists():
        print(f"REFUSING: {OUT} already exists. The holdout is spent — a second "
              f"run would not be a holdout. Read the file.")
        return 1

    spec = json.loads(SPEC.read_text())
    px, nav, vol = load_raw()
    disc = 100.0 * (px - nav) / nav
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    hs = pd.DataFrame(
        {c: [CM.half_spread_bp(p, a) for p, a in
             zip(px[c].values, adv[c].fillna(0).values)] for c in px.columns},
        index=px.index)
    end = str(px.index.max().date())

    zw = int(deep_get(spec, "z_window"))
    rb = int(deep_get(spec, "rebalance_days"))
    print(f"spec under test: {spec['spec_id']}  z_window={zw} rebalance={rb} shift=2")
    print(f"holdout window : {HOLDOUT_START} .. {end}\n")

    v3 = evaluate(disc, px, adv, hs, ret, zw, rb, 2, spec, HOLDOUT_START, end)
    ref = evaluate(disc, px, adv, hs, ret, 252, 5, 2, spec, HOLDOUT_START, end)

    for label, r in (("v3 FROZEN (63/2)", v3), ("reference as-deployed (252/5)", ref)):
        print(f"=== {label} ===")
        for k, v in r.items():
            print(f"  {k:22s} {v}")
        print()

    net = v3["net_sharpe"]
    verdict = ("PASS" if net >= 0.40 else "WEAK" if net >= 0.0 else "FAIL")
    print(f"PRE-REGISTERED VERDICT: {verdict}  (net Sharpe {net:+.3f} "
          f"against >=0.40 PASS / >=0.00 WEAK / <0.00 FAIL)")

    OUT.write_text(json.dumps({
        "opened_utc": datetime.now(timezone.utc).isoformat(),
        "spec_id": spec["spec_id"],
        "prereg": "results/cef/HOLDOUT_PREREG.md",
        "holdout_window": [HOLDOUT_START, end],
        "config_under_test": {"z_window": zw, "rebalance_days": rb, "shift": 2},
        "result": v3,
        "reference_as_deployed": {"z_window": 252, "rebalance_days": 5,
                                  "shift": 2, "result": ref},
        "verdict": verdict,
        "decision_rule": ">=0.40 PASS, 0.00-0.40 WEAK, <0.00 FAIL",
    }, indent=1))
    print(f"\nrecorded -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
