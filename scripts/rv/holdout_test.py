"""ONE-SHOT holdout test: 2024-01-01 -> 2026-07-28. Sealed since the build began.

READ THIS BEFORE RUNNING IT
---------------------------
The holdout is the only clean sample left in this project. 141 trials have been
spent in-sample; every configuration choice, every cost correction and every
diagnostic in FINDINGS.md was made with in-sample data visible. That is exactly
the situation a holdout exists for, and it is worth precisely one look. After this
runs, no variant tested against this data is honest evidence again.

So this script takes ONE configuration — the frozen spec handed to it — and runs
it once. It deliberately offers no grid, no sweep and no tuning knobs. If the
answer is disappointing, the correct response is to stop, not to come back with a
second configuration.

The configuration must be fixed BEFORE this runs, from in-sample evidence only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "credit_rv"

from src.strategies.credit_rv.signal import SignalConfig, compute_signals  # noqa: E402

HOLDOUT_START = pd.Timestamp("2024-01-01")
HOLDOUT_END = pd.Timestamp("2026-07-28")
SEAL = OUT / "HOLDOUT_OPENED.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="frozen spec json")
    ap.add_argument("--force", action="store_true",
                    help="re-open an already-opened holdout (recorded as a reuse)")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    f = spec["frozen"]

    if SEAL.exists() and not args.force:
        prior = json.loads(SEAL.read_text())
        print("REFUSING: the holdout has already been opened.")
        print(f"  opened_at : {prior.get('opened_at')}")
        print(f"  config    : {prior.get('config')}")
        print(f"  result    : Sharpe {prior.get('sharpe')}, "
              f"CAGR {prior.get('cagr_at_target_vol')}")
        print("\nRunning a second configuration against it converts an out-of-sample")
        print("test into an in-sample one. If you genuinely intend that, pass")
        print("--force; it will be recorded as a reuse and the result deflated.")
        return 3

    universe = list(f["universe"])
    smooth = int(f["smooth"])
    gross_lev = float(f["gross_leverage"])
    target_vol = float(spec.get("risk", {}).get("target_vol", 0.13))
    half = {k: float(v) for k, v in f["half_spread_bp"].items()}

    p = pd.read_parquet(ROOT / "data/rv/etf_ohlc.parquet")
    rf = pd.read_parquet(ROOT / "data/riskfree_daily.parquet").set_index("date")["rf_daily"]
    rf.index = pd.to_datetime(rf.index)

    ret_close = p.pivot(index="date", columns="ticker", values="ret_total").sort_index()
    mid = p.pivot(index="date", columns="ticker", values="mid_hl").sort_index()
    div = p.pivot(index="date", columns="ticker", values="dividend").sort_index().fillna(0.0)
    ret_mid = (mid + div) / mid.shift(1) - 1.0
    dv = p.assign(dv=p.close * p.volume).pivot(
        index="date", columns="ticker", values="dv").sort_index()

    sig = compute_signals(ret_mid, rf, dv, SignalConfig(
        w_beta=int(f.get("w_beta", 120)), w_resid=int(f.get("w_resid", 60)),
        theta=float(f.get("theta", 0.60)), tradeable=universe))
    S = sig["s_blend"]
    betas = sig["betas"]
    cols = list(S.columns)
    rt = ret_close.reindex(columns=cols)
    hs = np.array([half.get(c, 2.0) for c in cols]) / 1e4

    # The EWMA is warmed on pre-holdout data (state, not evidence) and only
    # holdout-dated P&L is scored.
    alpha = 2.0 / (smooth + 1.0) if smooth > 1 else 1.0
    max_w = float(f.get("max_weight_per_name", 0.35))
    prev = None
    dates, W, P = [], [], []
    for d in S.index:
        if d > HOLDOUT_END:
            break
        B = betas.get(d)
        if B is None or d not in rt.index:
            continue
        j = rt.index.get_loc(d)
        if j + 1 >= len(rt):
            continue
        s = S.loc[d].values.astype(float)
        ok = np.isfinite(s)
        if ok.sum() < 4:
            continue
        w = np.zeros(len(cols))
        w[ok] = -s[ok]
        w[ok] -= w[ok].mean()
        Bv = B.reindex(cols).values
        good = ok & np.isfinite(Bv).all(axis=1)
        if good.sum() < 7:
            continue
        Bk, wk = Bv[good], w[good]
        wk = wk - Bk @ np.linalg.solve(Bk.T @ Bk + 1e-10 * np.eye(Bk.shape[1]), Bk.T @ wk)
        w = np.zeros(len(cols))
        w[good] = wk - wk.mean()
        n = np.abs(w).sum()
        if n < 1e-12:
            continue
        w /= n
        if prev is not None and smooth > 1:
            w = alpha * w + (1 - alpha) * prev
            n = np.abs(w).sum()
            w = w / n if n > 1e-12 else w
        prev = w
        wc = np.clip(w, -max_w, max_w)
        nn = np.abs(wc).sum()
        wc = wc / nn * gross_lev if nn > 1e-12 else wc
        dates.append(d)
        W.append(wc)
        P.append(float(wc @ np.nan_to_num(rt.iloc[j + 1].values, nan=0.0)))

    idx = pd.DatetimeIndex(dates)
    W = np.array(W)
    P = pd.Series(P, index=idx)
    dW = np.abs(np.diff(W, axis=0))
    cost = pd.Series((dW * hs).sum(axis=1), index=idx[1:])
    net = (P.iloc[1:] - cost)

    ho = net[net.index >= HOLDOUT_START]
    if len(ho) < 100:
        print(f"FATAL: only {len(ho)} holdout observations")
        return 1

    turn = pd.Series(dW.sum(axis=1), index=idx[1:])
    ho_turn = turn[turn.index >= HOLDOUT_START]
    ho_gross = P.iloc[1:][P.iloc[1:].index >= HOLDOUT_START]
    ho_cost = cost[cost.index >= HOLDOUT_START]

    sr = ho.mean() / ho.std() * np.sqrt(252)
    lev = target_vol / (ho.std() * np.sqrt(252))
    scaled = ho * lev
    cagr = (1 + scaled).prod() ** (252 / len(scaled)) - 1
    eq = (1 + scaled).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    t_stat = ho.mean() / (ho.std() / np.sqrt(len(ho)))

    print("=" * 72)
    print("HOLDOUT RESULT — 2024-01-01 to 2026-07-28  (ONE SHOT, NOW SPENT)")
    print("=" * 72)
    print(f"  observations        {len(ho)}")
    print(f"  net Sharpe          {sr:>8.2f}      t-stat {t_stat:>6.2f}")
    print(f"  CAGR @ {target_vol:.0%} vol       {cagr*100:>7.2f}%")
    print(f"  max drawdown        {dd*100:>7.2f}%")
    print(f"  turnover            {ho_turn.mean()*252:>7.0f}x/yr")
    print(f"  gross               {ho_gross.mean()*252*100:>7.2f}%/yr")
    print(f"  cost                {ho_cost.mean()*252*100:>7.2f}%/yr")
    print(f"  earns/pays per unit turnover  "
          f"{ho_gross.mean()/ho_turn.mean()*1e4:.2f}bp / "
          f"{ho_cost.mean()/ho_turn.mean()*1e4:.2f}bp")

    by_year = scaled.groupby(scaled.index.year).apply(lambda x: (1 + x).prod() - 1)
    print("\n  by year @ target vol:")
    for y, v in by_year.items():
        print(f"    {y}   {v*100:>7.2f}%")

    rec = dict(
        opened_at=datetime.now(ZoneInfo("America/New_York")).isoformat(),
        config=dict(universe=universe, smooth=smooth, gross_leverage=gross_lev,
                    spec_id=spec.get("spec_id")),
        n_obs=int(len(ho)), sharpe=float(sr), t_stat=float(t_stat),
        cagr_at_target_vol=float(cagr), max_drawdown=float(dd),
        turnover_per_yr=float(ho_turn.mean() * 252),
        gross_pct_yr=float(ho_gross.mean() * 252 * 100),
        cost_pct_yr=float(ho_cost.mean() * 252 * 100),
        reuse=bool(args.force and SEAL.exists()),
    )
    SEAL.write_text(json.dumps(rec, indent=2))
    ho.to_frame("net").to_csv(OUT / "holdout_daily.csv")
    print(f"\nsealed record -> {SEAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
