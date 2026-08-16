"""Phase 2 planted case — KNOWN BAD: random long/flat signals on HYG.

Man-AHL style calibration. 20 independent random long/flat daily signals
(numpy default_rng seeds 0..19, P(long) = 0.5, weight 1.0 or 0.0) are run on
HYG through the production engine, properly lagged (T+1 via the engine, plus
info_dates so the lookahead guard actually fires) and WITH costs from
config/costs.yaml.

A random signal carries no information, so the harness must not manufacture
edge from it. Two things are reported separately, because they answer
different questions:

  * GROSS Sharpe (excess of rf) — tests whether the engine invents alpha.
    A coin-flip long/flat overlay on a positive-drift asset is not expected
    to be 0: it holds HYG about half the days, so it inherits roughly
    1/sqrt(2) of HYG's own excess Sharpe. That is beta, not alpha, and the
    benchmark row makes the comparison explicit.
  * NET Sharpe (excess of rf) — gross minus the cost of trading a signal
    that flips on ~50% of days (~126x one-way annual turnover). This is the
    number the calibration gate is written against.

Risk-free proxy: BIL ret_total from data/etf_daily.parquet, per data/README.md
(data/riskfree_daily.parquet is not yet built). BIL starts 2007-05-31, after
HYG's 2007-04-12 inception, so the sample starts at BIL inception — the first
date on which both a HYG return and a risk-free rate exist. No pre-BIL zero-rf
stub is used, so the excess-return series is honest for its whole length.

Run:  python3 scripts/calibration_planted_bad.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.backtest import guard  # noqa: E402
from src.backtest.engine import load_costs, load_panel, run_backtest  # noqa: E402
from src.backtest.tearsheet import tearsheet  # noqa: E402

N_SEEDS = 20
P_LONG = 0.5
ASSET = "HYG"

# Gate as specified for this planted case.
MEAN_NET_SHARPE_TOL = 0.25   # |mean net Sharpe across seeds| must be <= this
MAX_SINGLE_SEED_NET = 0.8    # no single seed's net Sharpe may exceed this


def random_long_flat_weights(dates, seed, p_long=P_LONG, asset=ASSET):
    """Coin-flip long/flat target weights (1.0 or 0.0) on ``asset``.

    Row dated t is a decision made with information available at t's close;
    the engine applies it from t+1's return. The draw uses no market data at
    all, so its info date is trivially <= t.
    """
    rng = np.random.default_rng(seed)
    w = (rng.random(len(dates)) < p_long).astype(float)
    return pd.DataFrame({asset: w}, index=dates)


def main():
    print("=" * 78)
    print("PLANTED CASE — KNOWN BAD: random long/flat signals on HYG")
    print("=" * 78)

    costs = load_costs()
    print(f"[costs] config/costs.yaml | book ${costs['book_usd_default']:,.0f} "
          f"| commission ${costs['commission_usd_per_trade']:.2f}/trade "
          f"| slippage_extra {costs['slippage_extra_bp']:.1f}bp "
          f"| {ASSET} half-spread {costs['tickers'][ASSET]['half_spread_bp']:.1f}bp")

    returns, rf = load_panel(tickers=[ASSET, "BIL"])
    if rf is None:
        raise SystemExit("BIL missing from panel — no risk-free proxy")

    # Sample = dates with BOTH a HYG return and a risk-free rate.
    both = returns[[ASSET, "BIL"]].dropna()
    dates = both.index
    print(f"[sample] {ASSET} + rf(BIL) overlap: {dates.min().date()}.."
          f"{dates.max().date()} N={len(dates)} trading days "
          f"({len(dates) / 252:.1f}y)")
    print(f"[sample] rf = BIL ret_total (proxy per data/README.md; "
          f"riskfree_daily.parquet not yet built)")

    # --- benchmark: always-long HYG, same window ---------------------------
    bh_w = pd.DataFrame({ASSET: np.ones(len(dates))}, index=dates)
    bh_info = pd.Series(dates, index=dates)
    bh = run_backtest(bh_w, returns, costs, rf=rf, info_dates=bh_info,
                      name=f"{ASSET} buy-and-hold (benchmark)", verbose=True)
    bh_m = tearsheet(bh, verbose=True)
    print()

    # --- 20 random seeds ---------------------------------------------------
    rows = []
    for seed in range(N_SEEDS):
        w = random_long_flat_weights(dates, seed)
        info = pd.Series(w.index, index=w.index)  # decision uses only data <= t
        guard.assert_lagged(w, info)              # explicit; engine repeats it

        res = run_backtest(w, returns, costs, rf=rf, info_dates=info,
                           name=f"random seed {seed:02d}", verbose=False)
        m = tearsheet(res, verbose=False)

        # Same signal with costs switched off, to split beta from cost drag.
        zero_costs = {**costs, "slippage_extra_bp": 0.0,
                      "commission_usd_per_trade": 0.0,
                      "tickers": {t: {"half_spread_bp": 0.0}
                                  for t in costs["tickers"]}}
        res0 = run_backtest(w, returns, costs=zero_costs, rf=rf,
                            info_dates=info, name=f"random seed {seed:02d} (0 cost)",
                            verbose=False)

        rows.append({
            "seed": seed,
            "frac_long": float(w[ASSET].mean()),
            "sharpe_gross": m["sharpe_gross"],
            "sharpe_net": m["sharpe_net"],
            "cagr_net": m["cagr"],
            "cagr_gross": m["cagr_gross"],
            "ann_vol": m["ann_vol"],
            "max_dd": m["max_drawdown"],
            "turnover_yr": m["avg_annual_turnover"],
            "cost_drag_yr": m["cost_drag_annual"],
            "sharpe_net_zerocost": tearsheet(res0, verbose=False)["sharpe_net"],
        })
        print(f"[seed {seed:02d}] long {rows[-1]['frac_long']:.1%} of days | "
              f"turnover {m['avg_annual_turnover']:6.1f}x/yr | "
              f"cost {m['cost_drag_annual']:6.2%}/yr | "
              f"Sharpe gross {m['sharpe_gross']:+.3f} net {m['sharpe_net']:+.3f}")

    df = pd.DataFrame(rows).set_index("seed")

    # --- distribution ------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"DISTRIBUTION ACROSS {N_SEEDS} SEEDS — sample {dates.min().date()}.."
          f"{dates.max().date()} N={len(dates)} days")
    print("=" * 78)
    for col in ("sharpe_net", "sharpe_gross", "sharpe_net_zerocost",
                "turnover_yr", "cost_drag_yr"):
        s = df[col]
        print(f"  {col:20s} mean {s.mean():+8.4f} | median {s.median():+8.4f} "
              f"| sd {s.std(ddof=1):7.4f} | min {s.min():+8.4f} "
              f"| max {s.max():+8.4f}")
    print(f"\n  benchmark {ASSET} buy-and-hold: Sharpe gross "
          f"{bh_m['sharpe_gross']:+.3f} net {bh_m['sharpe_net']:+.3f} | "
          f"CAGR net {bh_m['cagr']:+.2%} | vol {bh_m['ann_vol']:.2%}")
    print(f"  expected gross Sharpe for a 50% coin-flip overlay "
          f"(~1/sqrt(2) x benchmark): {bh_m['sharpe_gross'] / np.sqrt(2):+.3f}")

    # --- gate --------------------------------------------------------------
    mean_net = float(df["sharpe_net"].mean())
    max_net = float(df["sharpe_net"].max())
    mean_ok = abs(mean_net) <= MEAN_NET_SHARPE_TOL
    max_ok = max_net <= MAX_SINGLE_SEED_NET
    passed = mean_ok and max_ok

    print("\n" + "-" * 78)
    print(f"GATE  |mean net Sharpe| = {abs(mean_net):.4f} <= "
          f"{MEAN_NET_SHARPE_TOL}  -> {'PASS' if mean_ok else 'FAIL'}")
    print(f"GATE  max single-seed net Sharpe = {max_net:+.4f} <= "
          f"{MAX_SINGLE_SEED_NET}  -> {'PASS' if max_ok else 'FAIL'}")
    print(f"VERDICT: {'PASS' if passed else 'FAIL'}")
    print("-" * 78)

    out_csv = REPO_ROOT / "results" / "calibration_planted_bad.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv)
    print(f"[out] per-seed table -> {out_csv}")

    print("\nPER-SEED TABLE")
    print(df[["frac_long", "sharpe_gross", "sharpe_net", "sharpe_net_zerocost",
              "turnover_yr", "cost_drag_yr", "cagr_net", "max_dd"]]
          .to_string(float_format=lambda x: f"{x:+.4f}"))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
