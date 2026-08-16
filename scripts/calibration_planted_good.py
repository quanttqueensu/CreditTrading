#!/usr/bin/env python3
"""Phase 2 calibration — PLANTED CASE: KNOWN GOOD (ANGL vs HYG).

Man-AHL-style planted case. We hand the harness a relationship we already
believe is there and check the harness finds it, at roughly the right size.

The plant
---------
Strategy  : hold ANGL (fallen-angel HY ETF), 100% long, from its inception.
Benchmark : hold HYG (broad HY ETF), 100% long, over the SAME window.
Both go through ``engine.run_backtest`` with costs from ``config/costs.yaml``.

Prior estimate (QUANTT-research-report-july-2026.md, line 19): ANGL beat HYG
by +2.12%/yr over 14.3 years, winning 11 of 14 calendar years. That figure is
a GROSS price/total-return comparison, so the net number here should land
slightly below it (ANGL costs 3.0bp half-spread to enter vs HYG's 1.0bp, but
that is a one-time entry cost on a buy-and-hold, so the drag is ~0.01bp/yr —
essentially invisible).

PASS criteria (set by the Phase 2 task, consistent with PREREGISTRATION G1)
--------------------------------------------------------------------------
1. Net active return (ANGL net CAGR - HYG net CAGR) > +0.50%/yr.
2. Order of magnitude +1 to +3 %/yr.
3. The tearsheet prints correct sample dates (must match the audited panel
   ranges in data/README.md: ANGL 2012-04-12..2026-07-17, N=3586).

This script is deliberately written as an EXTERNAL CALLER: it touches only
the public harness API (engine.load_costs, engine.load_panel,
engine.run_backtest, tearsheet.tearsheet / to_markdown / compare). It does
not import private helpers or reach into engine internals. If the public API
cannot express "hold one ETF and compare it to another", that is itself a
finding.

An independent clean-room cross-check (raw parquet, no engine) is run at the
end to confirm the engine's numbers are not an artifact of the engine.

Run:  python3 scripts/calibration_planted_good.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.backtest import engine, tearsheet as ts  # noqa: E402

STRATEGY_TICKER = "ANGL"
BENCHMARK_TICKER = "HYG"
RF_TICKER = "BIL"          # risk-free proxy, per data/README.md

# Gates
MIN_NET_ACTIVE = 0.005     # +0.50%/yr, PREREGISTRATION G1
BAND_LO, BAND_HI = 0.01, 0.03   # expected order of magnitude, +1..+3%/yr
PRIOR_ESTIMATE = 0.0212    # +2.12%/yr gross, prior live test

# Expected sample, from data/README.md (audited Phase 1)
EXPECTED_START = pd.Timestamp("2012-04-12")
EXPECTED_END = pd.Timestamp("2026-07-17")
EXPECTED_N = 3586


def banner(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def buy_and_hold_weights(ticker, dates):
    """Target weights for a 100%-long buy-and-hold of ``ticker``.

    One row per trading day, all 1.0. The engine's T+1 rule means the row
    dated t earns from t+1, so the first day of the sim is flat (in cash at
    rf) for BOTH legs — identical treatment, so it cannot bias the active
    number. Holding the target constant means turnover is paid once, at
    entry, which is what a buy-and-hold actually pays.
    """
    return pd.DataFrame({ticker: 1.0}, index=dates)


def calendar_year_table(strat_net, bench_net):
    """Per-calendar-year compounded net returns and the active difference."""
    rows = []
    for year, idx in strat_net.groupby(strat_net.index.year).groups.items():
        s = float((1.0 + strat_net.loc[idx]).prod() - 1.0)
        b = float((1.0 + bench_net.loc[idx]).prod() - 1.0)
        rows.append({"year": int(year), "n_days": len(idx),
                     f"{STRATEGY_TICKER}_net": s,
                     f"{BENCHMARK_TICKER}_net": b, "active": s - b})
    return pd.DataFrame(rows).set_index("year")


def main():
    banner("PLANTED CASE — KNOWN GOOD: hold ANGL vs hold HYG, net of costs")

    # ---------------------------------------------------------------- inputs
    costs = engine.load_costs()
    print(f"[calib] costs from config/costs.yaml: "
          f"commission ${costs['commission_usd_per_trade']}/trade, "
          f"slippage_extra {costs['slippage_extra_bp']}bp, "
          f"book ${costs['book_usd_default']:,.0f}")
    print(f"[calib]   {STRATEGY_TICKER} half_spread "
          f"{costs['tickers'][STRATEGY_TICKER]['half_spread_bp']}bp | "
          f"{BENCHMARK_TICKER} half_spread "
          f"{costs['tickers'][BENCHMARK_TICKER]['half_spread_bp']}bp")

    returns, rf = engine.load_panel(
        tickers=[STRATEGY_TICKER, BENCHMARK_TICKER, RF_TICKER])

    # ------------------------------------------------- common sample window
    # Both legs must run over the SAME window or the comparison is meaningless.
    both = returns[[STRATEGY_TICKER, BENCHMARK_TICKER]].dropna()
    dates = both.index
    print(f"[calib] common {STRATEGY_TICKER}/{BENCHMARK_TICKER} sample: "
          f"{dates.min().date()}..{dates.max().date()} N={len(dates)} days "
          f"({len(dates) / engine.TRADING_DAYS:.2f}y)")

    # Calendar-alignment check: a date where one trades and the other does not
    # would silently shift the comparison.
    s_only = returns[STRATEGY_TICKER].dropna().index.difference(dates)
    b_only = returns[BENCHMARK_TICKER].dropna().index.difference(
        returns[BENCHMARK_TICKER].dropna().index.intersection(dates))
    b_only = b_only[b_only >= dates.min()]
    if len(s_only) or len(b_only):
        print(f"[calib] WARNING: calendar mismatch inside the common window — "
              f"{STRATEGY_TICKER}-only {len(s_only)}, "
              f"{BENCHMARK_TICKER}-only {len(b_only)} days")
    else:
        print("[calib] calendar check: both tickers trade on every day of the "
              "common window (no alignment gaps)")

    if rf.reindex(dates).isna().any():
        raise SystemExit("[calib] rf (BIL) has gaps in the window — abort")
    print(f"[calib] rf = {RF_TICKER} ret_total (BIL starts 2007-05-31, well "
          f"before {dates.min().date()}; no SHY/zero fallback needed here)")

    # ------------------------------------------------------------- backtests
    banner("Engine runs")
    res_strat = engine.run_backtest(
        buy_and_hold_weights(STRATEGY_TICKER, dates), returns, costs, rf=rf,
        info_dates=pd.Series(dates, index=dates),
        name=f"hold {STRATEGY_TICKER}")
    res_bench = engine.run_backtest(
        buy_and_hold_weights(BENCHMARK_TICKER, dates), returns, costs, rf=rf,
        info_dates=pd.Series(dates, index=dates),
        name=f"hold {BENCHMARK_TICKER}")

    banner("Tearsheets")
    m_strat = ts.tearsheet(res_strat)
    m_bench = ts.tearsheet(res_bench)

    print()
    print(ts.to_markdown(m_strat))
    print(ts.to_markdown(m_bench))

    # -------------------------------------------------------- active return
    banner("Active return (the planted edge)")

    net_active = m_strat["cagr"] - m_bench["cagr"]
    gross_active = m_strat["cagr_gross"] - m_bench["cagr_gross"]

    # Arithmetic cross-check: annualized mean of the daily net difference.
    daily_active = (res_strat.net - res_bench.net).dropna()
    arith_active = float(daily_active.mean()) * engine.TRADING_DAYS
    active_te = float(daily_active.std(ddof=1)) * np.sqrt(engine.TRADING_DAYS)
    active_ir = arith_active / active_te if active_te > 0 else np.nan
    # Newey-West-free t-stat on the daily active mean (descriptive only).
    t_stat = (float(daily_active.mean()) / float(daily_active.std(ddof=1))
              * np.sqrt(len(daily_active)))

    print(f"[calib] sample {m_strat['start'].date()}..{m_strat['end'].date()} "
          f"N={m_strat['n_days']} days ({m_strat['years']:.2f}y)")
    print(f"[calib] {STRATEGY_TICKER} net CAGR   {m_strat['cagr']:+.4%}   "
          f"gross CAGR {m_strat['cagr_gross']:+.4%}")
    print(f"[calib] {BENCHMARK_TICKER} net CAGR   {m_bench['cagr']:+.4%}   "
          f"gross CAGR {m_bench['cagr_gross']:+.4%}")
    print(f"[calib] NET ACTIVE (geometric, CAGR diff)   {net_active:+.4%}/yr")
    print(f"[calib] gross active (geometric)            {gross_active:+.4%}/yr")
    print(f"[calib] net active (arithmetic, ann. mean)  {arith_active:+.4%}/yr")
    print(f"[calib] tracking error {active_te:.4%}/yr | info ratio "
          f"{active_ir:+.3f} | daily-mean t-stat {t_stat:+.2f}")
    print(f"[calib] cost drag: {STRATEGY_TICKER} "
          f"{m_strat['cost_drag_annual']:.5%}/yr, {BENCHMARK_TICKER} "
          f"{m_bench['cost_drag_annual']:.5%}/yr (buy-and-hold pays once)")
    print(f"[calib] vs prior estimate {PRIOR_ESTIMATE:+.2%}/yr gross: net gap "
          f"{net_active - PRIOR_ESTIMATE:+.4%}/yr, gross gap "
          f"{gross_active - PRIOR_ESTIMATE:+.4%}/yr")

    # ------------------------------------------------------- per-year detail
    banner("Per-calendar-year net returns")
    yr = calendar_year_table(res_strat.net, res_bench.net)
    with pd.option_context("display.float_format", lambda v: f"{v:+.2%}"):
        print(yr.to_string())
    wins = int((yr["active"] > 0).sum())
    print(f"[calib] {STRATEGY_TICKER} beat {BENCHMARK_TICKER} in {wins} of "
          f"{len(yr)} calendar years (2012 and 2026 are partial)")
    print("[calib] prior live test reported 11 of 14 years")

    # ------------------------------------------------------- side-by-side
    banner("compare() table")
    cmp_df = ts.compare([res_strat, res_bench], verbose=False)
    with pd.option_context("display.width", 200, "display.max_columns", 50):
        print(cmp_df[["start", "end", "n_days", "cagr", "cagr_gross",
                      "ann_vol", "sharpe_net", "max_drawdown",
                      "avg_annual_turnover", "cost_drag_annual"]].to_string())

    # ------------------------------------------------ clean-room cross-check
    banner("Clean-room cross-check (raw parquet, no engine)")
    raw = pd.read_parquet(REPO_ROOT / "data" / "etf_daily.parquet",
                          columns=["date", "ticker", "ret_total"])
    raw = raw[raw["ticker"].isin([STRATEGY_TICKER, BENCHMARK_TICKER])]
    raw = raw.pivot(index="date", columns="ticker", values="ret_total").dropna()
    n = len(raw)
    cr_s = float((1 + raw[STRATEGY_TICKER]).prod() ** (252 / n) - 1)
    cr_b = float((1 + raw[BENCHMARK_TICKER]).prod() ** (252 / n) - 1)
    print(f"[cleanroom] sample {raw.index.min().date()}.."
          f"{raw.index.max().date()} N={n} days")
    print(f"[cleanroom] {STRATEGY_TICKER} CAGR {cr_s:+.4%} | "
          f"{BENCHMARK_TICKER} CAGR {cr_b:+.4%} | active {cr_s - cr_b:+.4%}/yr")
    # The engine spends day 1 in cash (T+1), so a tiny difference is expected
    # and is not an error; flag only if it is material.
    engine_vs_clean = gross_active - (cr_s - cr_b)
    print(f"[cleanroom] engine gross active - cleanroom active = "
          f"{engine_vs_clean:+.5%}/yr "
          f"({'OK, T+1 first-day-in-cash only' if abs(engine_vs_clean) < 0.001 else 'MATERIAL — investigate'})")

    # ---------------------------------------------------------------- gates
    banner("VERDICT")
    checks = []

    checks.append((
        "net active > +0.50%/yr",
        net_active > MIN_NET_ACTIVE,
        f"{net_active:+.4%}/yr vs gate {MIN_NET_ACTIVE:+.2%}/yr"))

    checks.append((
        "net active in +1..+3%/yr band",
        BAND_LO <= net_active <= BAND_HI,
        f"{net_active:+.4%}/yr vs band [{BAND_LO:+.0%}, {BAND_HI:+.0%}]"))

    dates_ok = (m_strat["start"] == EXPECTED_START
                and m_strat["end"] == EXPECTED_END
                and m_strat["n_days"] == EXPECTED_N
                and m_bench["start"] == EXPECTED_START
                and m_bench["end"] == EXPECTED_END
                and m_bench["n_days"] == EXPECTED_N)
    checks.append((
        "tearsheet sample dates correct",
        dates_ok,
        f"strategy {m_strat['start'].date()}..{m_strat['end'].date()} "
        f"N={m_strat['n_days']}; benchmark {m_bench['start'].date()}.."
        f"{m_bench['end'].date()} N={m_bench['n_days']}; expected "
        f"{EXPECTED_START.date()}..{EXPECTED_END.date()} N={EXPECTED_N}"))

    checks.append((
        "engine agrees with clean-room",
        abs(engine_vs_clean) < 0.001,
        f"difference {engine_vs_clean:+.5%}/yr"))

    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")

    overall = all(ok for _, ok, _ in checks)
    print()
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
