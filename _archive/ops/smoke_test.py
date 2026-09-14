"""End-to-end smoke test: run the whole ops chain on historical data.

    python3 ops/smoke_test.py

Two passes, both replaying the audited panel (data/etf_daily.parquet) rather
than hitting the network, so this is reproducible and can be run any time.

  PASS A — "a couple of weeks", day by day.
      Calls daily_run.py once per trading day across a month boundary, so a
      real rebalance decision and its next-close fills happen in the middle.
      Then it checks the two properties the ledger promises:
        * re-running the same day changes nothing at all (byte-identical state)
        * no trading day is ever filled or recorded twice

  PASS B — a year, in one catch-up run.
      Enough live days for Gate S to actually grade a 3-month window, so the
      monitor produces a real verdict rather than INSUFFICIENT_DATA, and the
      weekly report has some fills to measure slippage on.

Both passes write to throwaway state directories under ops/state_smoke/ and
never touch the real ops/state/.
"""

import hashlib
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import common, daily_run, ledger as ledger_mod, monitor as monitor_mod  # noqa: E402
from ops import weekly_report  # noqa: E402

SMOKE_ROOT = common.OPS_DIR / "state_smoke"

PASS_A_START = "2026-06-22"     # ~3.5 weeks, spans the 2026-06-30 month end
PASS_A_END = "2026-07-17"
PASS_B_START = "2025-07-01"     # ~1 year, so Gate S has >63 live days
PASS_B_END = "2026-07-17"

FAILURES = []


def check(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)
    return ok


def state_fingerprint(state_dir):
    h = hashlib.sha256()
    for name in sorted(["prices.csv", "orders.csv", "trades.csv",
                        "positions.csv", "nav.csv"]):
        p = Path(state_dir) / name
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()[:16]


def trading_days(tickers, start, end):
    px = common.fetch_local(tickers, start, end)
    return sorted(pd.DatetimeIndex(px["date"].unique()))


def backtest_total(spec, start, end):
    """The same book run through the audited engine over the same window.

    This is the reference the simulator is supposed to track. It reuses
    monitor.backtest_path's conventions rather than re-deriving them.
    """
    from src.backtest import engine

    panel, _ = engine.load_panel(verbose=False)
    raw = pd.read_parquet(common.PANEL_PATH)
    raw["date"] = pd.to_datetime(raw["date"])
    dv = (raw.assign(d=raw["volume"] * raw["prc_adj"])
             .pivot(index="date", columns="ticker", values="d"))
    weights = spec["allocation"]["weights"]
    cols = sorted(set(weights) | {spec["risk_free_ticker"]})
    rets = panel.loc[start:end].dropna(subset=cols)
    marks = common.month_end_dates(rets.index)
    marks = pd.DatetimeIndex(sorted(set(marks) | {rets.index[0]}))
    w = pd.DataFrame({t: v for t, v in weights.items()}, index=marks)
    res = engine.run_backtest(
        w, rets, engine.load_costs(), book_usd=float(spec["book_usd"]),
        dollar_volume=dv, info_dates=pd.Series(w.index, index=w.index),
        verbose=False)
    return float((1.0 + res.net).prod() - 1.0)


# ---------------------------------------------------------------------------

def pass_a(spec):
    common.banner("PASS A — a couple of weeks, one daily_run.py call per day")
    state = SMOKE_ROOT / "pass_a"
    if state.exists():
        shutil.rmtree(state)
    days = trading_days(common.spec_tickers(spec), PASS_A_START, PASS_A_END)
    print(f"replaying {len(days)} trading days {days[0].date()}..{days[-1].date()} "
          f"from data/etf_daily.parquet\n")

    for i, d in enumerate(days):
        first = (i == 0)
        daily_run.main([
            "--asof", str(d.date()), "--source", "local",
            "--state-dir", str(state),
            *(["--start", str(days[0].date())] if first else []),
            *([] if first or d == days[-1] else ["--quiet"]),
        ])

    lg = ledger_mod.Ledger(state)
    common.banner("PASS A — checks")

    check("ledger recorded every replayed trading day",
          len(lg.nav) == len(days),
          f"{len(lg.nav)} NAV rows vs {len(days)} trading days")
    check("no duplicate NAV dates", not lg.nav["date"].duplicated().any())
    check("no duplicate (fill_date, ticker) trades",
          lg.trades.empty or
          not lg.trades.duplicated(subset=["fill_date", "ticker"]).any(),
          f"{len(lg.trades)} fills")
    check("a rebalance actually happened", len(lg.trades) > 0,
          f"{len(lg.trades)} fill(s) on "
          f"{sorted(set(str(pd.Timestamp(x).date()) for x in lg.trades['fill_date']))}")
    check("every order was resolved (none left open)",
          lg.open_orders().empty,
          f"{len(lg.orders)} order(s), "
          f"{(lg.orders['status'] == 'filled').sum()} filled")

    nav = lg.nav_series()
    check("NAV is finite and positive throughout",
          bool(nav.notna().all() and (nav > 0).all()),
          f"{common.money(float(nav.iloc[0]))} -> {common.money(float(nav.iloc[-1]))}")
    check("NAV never moves more than 10% in a day (sanity, not a gate)",
          bool(lg.daily_returns().abs().max() < 0.10),
          f"worst daily move {lg.daily_returns().abs().max():.2%}")
    check("cash never goes negative", bool((lg.nav["cash"] >= -1e-6).all()),
          f"min cash {common.money(float(lg.nav['cash'].min()))}")
    last = lg.positions[lg.positions["date"] == lg.positions["date"].max()]
    invested = last[last["ticker"] != ledger_mod.CASH]["weight"].sum()
    check("book is close to fully invested after the rebalance",
          0.97 <= invested <= 1.0, f"invested weight {invested:.3%}")

    print("\nfinal positions:")
    print(last.to_string(index=False))
    print("\nall simulated fills:")
    print(lg.trades.to_string(index=False) if not lg.trades.empty else "  (none)")

    # -- idempotence ------------------------------------------------------
    common.banner("PASS A — idempotence: re-run the same day, twice")
    before = state_fingerprint(state)
    rows_before = (len(lg.nav), len(lg.trades), len(lg.orders), len(lg.positions))
    for _ in range(2):
        daily_run.main(["--asof", str(days[-1].date()), "--source", "local",
                        "--state-dir", str(state), "--quiet"])
    after = state_fingerprint(state)
    lg2 = ledger_mod.Ledger(state)
    rows_after = (len(lg2.nav), len(lg2.trades), len(lg2.orders), len(lg2.positions))
    check("state files are byte-identical after two extra runs",
          before == after, f"{before} -> {after}")
    check("no rows added by the re-runs", rows_before == rows_after,
          f"{rows_before} -> {rows_after}")

    # -- catch-up ---------------------------------------------------------
    common.banner("PASS A — catch-up: a fresh ledger jumped straight to the end")
    state_c = SMOKE_ROOT / "pass_a_catchup"
    if state_c.exists():
        shutil.rmtree(state_c)
    daily_run.main(["--asof", str(days[-1].date()), "--source", "local",
                    "--state-dir", str(state_c),
                    "--start", str(days[0].date()), "--quiet"])
    lgc = ledger_mod.Ledger(state_c)
    same_nav = (abs(float(lgc.nav_series().iloc[-1])
                    - float(lg.nav_series().iloc[-1])) < 1e-6)
    check("catching up in one run gives the same NAV as running daily",
          same_nav,
          f"{common.money(float(lgc.nav_series().iloc[-1]))} vs "
          f"{common.money(float(lg.nav_series().iloc[-1]))}")
    return state


def pass_b(spec):
    common.banner("PASS B — one year, so Gate S can actually grade something")
    state = SMOKE_ROOT / "pass_b"
    if state.exists():
        shutil.rmtree(state)
    daily_run.main(["--asof", PASS_B_END, "--source", "local",
                    "--state-dir", str(state), "--start", PASS_B_START])

    lg = ledger_mod.Ledger(state)
    days = trading_days(common.spec_tickers(spec), PASS_B_START, PASS_B_END)
    common.banner("PASS B — checks")
    check("ledger recorded every trading day in the year",
          len(lg.nav) == len(days), f"{len(lg.nav)} vs {len(days)}")
    check("12-13 rebalance decisions in a year",
          11 <= lg.trades["decision_date"].nunique() <= 14,
          f"{lg.trades['decision_date'].nunique()} rebalance dates, "
          f"{len(lg.trades)} fills")
    check("enough live days for Gate S to grade",
          len(lg.daily_returns()) >= spec["gate_s"]["min_live_days"],
          f"{len(lg.daily_returns())} days vs "
          f"{spec['gate_s']['min_live_days']} needed")

    # -- the check that matters most: does the sim track the backtest? -----
    common.banner("PASS B — live sim against the engine, same window")
    nav = lg.nav_series()
    live_total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    bt_total = backtest_total(spec, nav.index.min(), nav.index.max())
    gap_bp = (live_total - bt_total) * 1e4
    print(f"  live simulator : {live_total:+.4%}")
    print(f"  engine backtest: {bt_total:+.4%}   (same weights, same window, "
          f"same costs.yaml)")
    print(f"  gap            : {gap_bp:+.1f} bp over "
          f"{len(nav)/common.TRADING_DAYS:.2f} years")
    print("  The sim should sit slightly BELOW the backtest, and it should be "
          "explainable:\n"
          "    - whole-share rounding leaves ~0.5% of the book in cash "
          "earning nothing\n"
          "    - distributions sit in cash until the next month-end instead of "
          "compounding\n"
          "    - the sim pays real drift-rebalancing costs; the engine charges "
          "cost on changes\n"
          "      in TARGET weight, and a fixed tilt never changes its target "
          "(CALIBRATION.md)\n"
          "  A gap the other way, or a large one, means something is wrong.")
    check("live sim tracks the backtest within 50bp over a year",
          abs(gap_bp) < 50, f"{gap_bp:+.1f} bp")
    check("live sim is not ABOVE the backtest (frictions only subtract)",
          gap_bp < 5, f"{gap_bp:+.1f} bp")

    status = monitor_mod.run(spec, state, rebuild=True, verbose=True)

    common.banner("PASS B — monitor checks")
    g = status["gate_s"]
    check("Gate S produced a real verdict",
          g["status"] in (monitor_mod.CONTINUE, monitor_mod.HALVE,
                          monitor_mod.SUSPEND),
          g["status"])
    b = status["bands"]
    check("return band is ordered p10 < p50 < p90",
          b["return_3m"]["p10"] < b["return_3m"]["p50"] < b["return_3m"]["p90"],
          f"{b['return_3m']['p10']:+.2%} / {b['return_3m']['p50']:+.2%} / "
          f"{b['return_3m']['p90']:+.2%}")
    check("Sharpe band is ordered p10 < p50 < p90",
          b["sharpe_3m"]["p10"] < b["sharpe_3m"]["p50"] < b["sharpe_3m"]["p90"])
    check("suspend threshold is 1.25x the backtest maxDD",
          abs(status["backtest"]["max_drawdown"] * 1.25
              - monitor_mod.load_bands(state)["suspend_drawdown"]) < 1e-9,
          f"maxDD {status['backtest']['max_drawdown']:+.2%} -> suspend at "
          f"{monitor_mod.load_bands(state)['suspend_drawdown']:+.2%}")
    c = status["crowding"]
    check("crowding kill criterion is surfaced, not hidden",
          c.get("light") is not None and "fired" in c,
          f"light {c.get('light')}, fired={c.get('fired')}, "
          f"run={c.get('current_run_months')} months")
    check("the known-RED crowding state reaches the action list",
          any("CUT SIZE" in a for a in status["actions"]) or not c.get("fired"),
          "; ".join(status["actions"]))

    common.banner("PASS B — weekly report")
    path, md = weekly_report.build(spec, state, report_dir=state / "reports",
                                   verbose=True)
    check("report is non-trivial", len(md) > 2000, f"{len(md):,} chars")
    check("report names the Gate S verdict", g["status"] in md)
    check("report carries the crowding light", "Crowding light" in md)
    check("report has a slippage table",
          "Slippage" in md and "overnight move" in md)
    print("\n" + "-" * 78)
    print(md)
    print("-" * 78)
    return state


def main():
    spec = common.load_spec()
    common.banner(f"OPS SMOKE TEST — spec {spec['spec_id']} ({spec['status']})")
    print("Replaying data/etf_daily.parquet. No network, no real money, and "
          "the real ops/state/ is never touched.")
    pass_a(spec)
    pass_b(spec)

    common.banner("SMOKE TEST RESULT")
    if FAILURES:
        print(f"  {len(FAILURES)} CHECK(S) FAILED:")
        for f in FAILURES:
            print(f"    - {f}")
        return 1
    print("  All checks passed. The chain runs: daily_run -> ledger -> "
          "monitor -> weekly_report.")
    print(f"  Throwaway state left under {SMOKE_ROOT} for inspection; delete "
          "it whenever.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
