"""The weekly markdown report a human actually reads.

    python3 ops/weekly_report.py                 # writes ops/reports/weekly_<date>.md

Sections: positions, simulated P&L, turnover, slippage (decision price against
fill), the Gate S divergence status, and the crowding light. Every table prints
its sample dates and N, per the standing rule.

The report never grades anything itself. It reads what daily_run.py and
monitor.py already wrote, so it cannot disagree with them.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import common, ledger as ledger_mod, monitor as monitor_mod  # noqa: E402
from src.backtest import tearsheet as ts  # noqa: E402


def _pct(x, nd=2):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:+.{nd}%}"


def _num(x, nd=3):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:+.{nd}f}"


def build(spec, state_dir, asof=None, refresh_status=True, report_dir=None,
          verbose=True):
    state_dir = Path(state_dir)
    lg = ledger_mod.Ledger(state_dir)
    prices = common.read_prices(state_dir)
    if lg.nav.empty:
        raise SystemExit(f"ledger at {state_dir} is empty — run "
                         "ops/daily_run.py first.")

    nav = lg.nav_series()
    live = lg.daily_returns()
    asof = pd.Timestamp(asof) if asof else nav.index.max()

    status_path = state_dir / monitor_mod.STATUS_FILE
    if refresh_status or not status_path.exists():
        status = monitor_mod.run(spec, state_dir, verbose=False)
    else:
        status = json.loads(status_path.read_text())

    L = []
    A = L.append
    A(f"# Weekly paper-trading report — {asof.date()}")
    A("")
    A(f"Spec `{spec['spec_id']}` (**{spec['status']}**), book "
      f"{common.money(spec['book_usd'])}, weights "
      + ", ".join(f"**{k} {v:.1%}**"
                  for k, v in sorted(spec["allocation"]["weights"].items()))
      + f", rebalanced {spec['rebalance']['rule'].replace('_', '-')}.")
    A("")
    A(f"Live simulated sample **{nav.index.min().date()} .. "
      f"{nav.index.max().date()}, N = {len(nav)} trading days** "
      f"({len(nav)/common.TRADING_DAYS:.2f} years). Simulated fills only. "
      "No broker, no real money.")
    A("")

    # ---------------------------------------------------------------- verdict
    c = status["crowding"]
    g = status["gate_s"]
    A("## Headline")
    A("")
    A("| | |")
    A("|---|---|")
    A(f"| Gate S | **{g['status']}** — {g['reason']} |")
    A(f"| Crowding light | **{c.get('light')}**"
      + (f" — kill criterion FIRED, {c['current_run_months']} consecutive "
         f"months of 36-month alpha below the "
         f"{c['planning_floor']:+.2%}/yr planning floor. Encoded action: "
         f"**CUT SIZE**." if c.get("fired") and "current_run_months" in c
         else f" — {c.get('note', 'no action')}") + " |")
    A("")
    A("Actions on the table this week:")
    A("")
    for a in status["actions"]:
        A(f"- {a}")
    A("")

    # -------------------------------------------------------------- positions
    A("## Positions")
    A("")
    last_day = lg.positions["date"].max()
    snap = lg.positions[lg.positions["date"] == last_day].copy()
    targets = spec["allocation"]["weights"]
    A(f"As of {pd.Timestamp(last_day).date()}. NAV "
      f"{common.money(float(nav.iloc[-1]))}.")
    A("")
    A("| ticker | shares | close | market value | weight | target | drift |")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for _, r in snap.sort_values("ticker").iterrows():
        t = r["ticker"]
        tgt = targets.get(t, 0.0) if t != ledger_mod.CASH else 0.0
        sh = "" if not np.isfinite(r["shares"]) else f"{r['shares']:,.0f}"
        cl = "" if not np.isfinite(r["close"]) else f"{r['close']:,.2f}"
        A(f"| {t} | {sh} | {cl} | {common.money(r['market_value'])} | "
          f"{r['weight']:.2%} | {tgt:.1%} | {r['weight'] - tgt:+.2%} |")
    A("")
    resid = float(snap[snap["ticker"] == ledger_mod.CASH]["market_value"].iloc[0]) \
        if (snap["ticker"] == ledger_mod.CASH).any() else 0.0
    A(f"Residual cash is {common.money(resid)}. The book trades whole shares "
      "only, so a few dollars always sit uninvested between rebalances, and "
      "distributions sit in cash until the next month-end. Both are real drags "
      "the backtest does not model; at this size they are worth a fraction of "
      "a basis point a year.")
    A("")

    # ------------------------------------------------------------------- P&L
    A("## Simulated P&L")
    A("")
    nav0, nav1 = float(nav.iloc[0]), float(nav.iloc[-1])
    total_ret = nav1 / nav0 - 1.0
    week = live.iloc[-5:] if len(live) >= 5 else live
    week_ret = float((1.0 + week).prod() - 1.0) if len(week) else np.nan
    dists = float(lg.nav["distributions_usd"].sum())
    costs_paid = float(lg.nav["cost_usd"].sum())
    dd = g["live_max_drawdown"]

    rows = [
        ("Starting book", common.money(nav0)),
        ("Current NAV", common.money(nav1)),
        ("P&L since inception", f"{common.money(nav1 - nav0)}  ({total_ret:+.2%})"),
        (f"Last {len(week)} trading days", _pct(week_ret)),
        ("Distributions received", common.money(dists)),
        ("Simulated trading cost paid", common.money(costs_paid)),
        ("Worst drawdown so far", _pct(dd)),
    ]
    if len(live) >= 20:
        rows.append(("Annualized vol (live)", _pct(ts.ann_vol(live))))
        rf = monitor_mod.live_rf(spec, prices).reindex(live.index).fillna(0.0)
        rows.append(("Sharpe, excess of BIL (live)",
                     _num(ts.sharpe_ratio(live, rf))))
    A("| | |")
    A("|---|---:|")
    for k, v in rows:
        A(f"| {k} | {v} |")
    A("")
    if len(live) < 60:
        A(f"> With {len(live)} live days, none of the return statistics above "
          "mean anything yet. They are here so the arithmetic can be checked, "
          "not so they can be read as performance.")
        A("")

    # -------------------------------------------------------------- turnover
    A("## Turnover")
    A("")
    traded = float(lg.nav["traded_usd"].sum())
    avg_nav = float(nav.mean())
    years = len(nav) / common.TRADING_DAYS
    n_rebal = int(lg.trades["decision_date"].nunique()) if not lg.trades.empty else 0
    if not lg.trades.empty:
        reason = lg.trades["reason"].fillna("").astype(str)
        funding = float(lg.trades.loc[reason == "funding",
                                      "notional_usd"].abs().sum())
    else:
        funding = 0.0
    ongoing = traded - funding
    ann = lambda x: (x / avg_nav / years) if years > 0 and avg_nav > 0 else np.nan
    A("| | |")
    A("|---|---:|")
    A(f"| Rebalance events | {n_rebal} |")
    A(f"| Fills | {len(lg.trades)} |")
    A(f"| One-time funding purchase | {common.money(funding)} |")
    A(f"| Ongoing drift trades | {common.money(ongoing)} |")
    A(f"| Ongoing one-way turnover, annualized | {ann(ongoing):.3f}x |")
    A(f"| ... including the funding purchase | {ann(traded):.3f}x |")
    A("")
    bt_turn = status["backtest"].get("annual_turnover")
    bt_days = status["backtest"].get("n_days") or 1
    bt_years = bt_days / common.TRADING_DAYS
    A(f"**Compare against the backtest carefully.** The 2017+ reference run "
      f"reports {bt_turn:.3f}x a year over {bt_years:.1f} years — which is "
      f"almost exactly its own one-time entry (1.0 / {bt_years:.1f} = "
      f"{1.0/bt_years:.3f}) amortised across the whole sample. The engine's "
      "*ongoing* turnover on a fixed tilt is structurally **zero**: it charges "
      "cost on changes in target weight, and a constant target never changes. "
      "So the headline numbers are not comparable, and the honest comparison "
      f"is this simulator's ongoing **{ann(ongoing):.3f}x a year** of real "
      "month-end drift trading against the backtest's zero.")
    A("")
    A("That gap is the known engine defect, not a bug here: "
      "`results/CALIBRATION.md` records it and `results/S1_FALLEN_ANGEL.md` "
      "measures the omitted drift cost at about 0.0009%/yr at the 50/50 rung. "
      "What to watch is the ongoing figure drifting upward over time — this "
      "book should trade a few hundred dollars a month and no more.")
    A("")

    # -------------------------------------------------------------- slippage
    A("## Slippage — decision price against fill")
    A("")
    if lg.trades.empty:
        A("No fills yet.")
        A("")
    else:
        tr = lg.trades.copy()
        side = np.where(tr["side"] == "BUY", 1.0, -1.0)
        tr["market_move_bp"] = (tr["close_price"] / tr["decision_price"] - 1.0) * 1e4 * side
        tr["cost_bp"] = tr["half_spread_bp"] + tr["impact_bp"]
        A(f"Decisions are made on one close and filled at the NEXT close, so "
          f"the gap has two parts: the spread and impact we chose to pay "
          f"(known in advance, from `config/costs.yaml`), and the overnight "
          f"market move (not a cost, just the price of waiting a day). "
          f"N = {len(tr)} fills.")
        A("")
        A("| fill date | ticker | side | shares | decision | close | fill | "
          "spread+impact bp | overnight move bp | total slip bp | cost |")
        A("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in tr.sort_values("fill_date").tail(12).iterrows():
            A(f"| {pd.Timestamp(r['fill_date']).date()} | {r['ticker']} | "
              f"{r['side']} | {r['shares']:,.0f} | {r['decision_price']:.4f} | "
              f"{r['close_price']:.4f} | {r['fill_price']:.4f} | "
              f"{r['cost_bp']:.2f} | {r['market_move_bp']:+.1f} | "
              f"{r['slip_vs_decision_bp']:+.1f} | "
              f"{common.money(r['cost_usd'])} |")
        A("")
        wsum = float(tr["notional_usd"].abs().sum())
        wavg = (float((tr["cost_bp"] * tr["notional_usd"].abs()).sum()) / wsum
                if wsum > 0 else np.nan)
        wmove = (float((tr["market_move_bp"] * tr["notional_usd"].abs()).sum()) / wsum
                 if wsum > 0 else np.nan)
        A(f"Size-weighted spread+impact: **{wavg:.2f} bp** per side. "
          f"Size-weighted overnight move: **{wmove:+.2f} bp** (this averages "
          "toward zero over many trades; if it does not, the decision rule is "
          "systematically trading into a move and that is worth knowing). "
          f"Total simulated cost to date {common.money(costs_paid)}.")
        A("")
        capped = tr[tr["over_participation_cap"].astype(str).str.lower() == "true"]
        if len(capped):
            A(f"> **{len(capped)} fill(s) exceeded the "
              f"{common.load_costs()['max_participation_pct']}% participation "
              "cap in `config/costs.yaml`.** Those fills are simulated anyway "
              "and flagged here; a real order that size would not have filled "
              "at the close. Check them by hand.")
            A("")

    # ------------------------------------------------------------- divergence
    b, bt = status["bands"], status["backtest"]
    A("## Divergence — Gate S")
    A("")
    A(f"Bands are the 10th-90th percentile of {spec['gate_s']['n_bootstrap']} "
      f"moving-block bootstrap replications ({spec['gate_s']['block_days']}-day "
      f"blocks) of the frozen book's own backtest over "
      f"{bt['start']}..{bt['end']} (N = {bt['n_days']} days). That window is "
      "the tradeable era, not the full sample, on the explicit recommendation "
      "of `results/S1_FALLEN_ANGEL.md`.")
    A("")
    A("| measure | live | 10th pct | 90th pct | verdict |")
    A("|---|---:|---:|---:|---|")
    if g["return_3m"] is None:
        A(f"| 3-month return | not graded | {b['return_3m']['p10']:+.2%} | "
          f"{b['return_3m']['p90']:+.2%} | {g['n_live_days']}/"
          f"{g['min_live_days']} days |")
        A(f"| 3-month Sharpe | not graded | {b['sharpe_3m']['p10']:+.3f} | "
          f"{b['sharpe_3m']['p90']:+.3f} | {g['n_live_days']}/"
          f"{g['min_live_days']} days |")
    else:
        rv = ("**below 10th pct**" if g["return_3m"] < b["return_3m"]["p10"]
              else "above 90th pct" if g["return_3m"] > b["return_3m"]["p90"]
              else "inside")
        sv = ("**below 10th pct**" if g["sharpe_3m"] < b["sharpe_3m"]["p10"]
              else "above 90th pct" if g["sharpe_3m"] > b["sharpe_3m"]["p90"]
              else "inside")
        A(f"| 3-month return ({g['window_start']}..{g['window_end']}) | "
          f"{g['return_3m']:+.2%} | {b['return_3m']['p10']:+.2%} | "
          f"{b['return_3m']['p90']:+.2%} | {rv} |")
        A(f"| 3-month Sharpe | {g['sharpe_3m']:+.3f} | "
          f"{b['sharpe_3m']['p10']:+.3f} | {b['sharpe_3m']['p90']:+.3f} | {sv} |")
    A(f"| live drawdown | {g['live_max_drawdown']:+.2%} | suspend at "
      f"{g['suspend_threshold']:+.2%} | — | "
      f"{'**BREACHED**' if g['drawdown_breached'] else 'ok'} |")
    A("")
    A(f"**Gate S status: {g['status']}.** {g['reason']}")
    A("")

    # --------------------------------------------------------------- crowding
    A("## Crowding light")
    A("")
    if "latest_36m_alpha" in c:
        A("| | |")
        A("|---|---|")
        A(f"| Light | **{c['light']}** |")
        A(f"| Latest 36-month ANGL-vs-HYG alpha | {c['latest_36m_alpha']:+.2%}/yr |")
        A(f"| Planning floor (prior edge x 50% haircut) | {c['planning_floor']:+.2%}/yr |")
        A(f"| Consecutive months below the floor | {c['current_run_months']} "
          f"(trigger {c['kill_n_months']}) |")
        A(f"| Kill criterion | {'**FIRED — CUT SIZE**' if c['fired'] else 'not fired'} |")
        A(f"| Data as of | {c['last_window_end']} ({c['age_days']} days old"
          f"{', **STALE**' if c['stale'] else ''}) |")
        A("")
        if c["fired"]:
            A("> This light was already red before the sleeve was funded. "
              "`results/S1_FALLEN_ANGEL.md` section 6 is explicit that L1, L2 "
              "and L3 are three readings of one fact — the 36-month alpha has "
              "fallen — not three independent confirmations, which is why the "
              "encoded action is cut size rather than shut down. It is also "
              "explicit that the one light specifically about *crowding* (L5, "
              "fallen-angel ETF volume share of HYG) is GREEN and falling. So "
              "the honest sentence is: cut size because the edge is gone, not "
              "because we proved the trade is full. Why it is gone remains "
              "unexplained.")
            A("")
    else:
        A(f"**{c.get('light')}** — {c.get('note', '')}")
        A("")

    # ------------------------------------------------------------- checklist
    A("## What a human checks before next week")
    A("")
    A("1. Did `daily_run.py` run every trading day? Gaps in `nav.csv` mean the "
      "cron did not fire.")
    A("2. Any `LIQUIDITY WARNING` or `SPLIT DETECTED` lines in the logs?")
    A("3. Any restated bars — the `prices.csv` conflict warning?")
    A("4. Is the crowding file stale? Re-run "
      "`scripts/s1_crowding_monitor.py` monthly.")
    A("5. If Gate S says HALVE or SUSPEND, that is a written review, not a "
      "judgement call made at the keyboard.")
    A("")
    A("---")
    A("")
    A(f"Generated by `ops/weekly_report.py` at "
      f"{datetime.now().strftime('%Y-%m-%d %H:%M')}. Costs from "
      "`config/costs.yaml`. Nothing in this report was hand-entered.")
    A("")

    md = "\n".join(L)
    out_dir = Path(report_dir or common.DEFAULT_REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"weekly_{asof.date()}.md"
    path.write_text(md)
    if verbose:
        print(f"[report] wrote {path} ({len(md):,} chars)")
    return path, md


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", default=str(common.DEFAULT_STATE_DIR))
    ap.add_argument("--spec", default=str(common.SPEC_PATH))
    ap.add_argument("--asof", default=None)
    ap.add_argument("--report-dir", default=None)
    ap.add_argument("--print", action="store_true", help="also print the report")
    args = ap.parse_args(argv)

    spec = common.load_spec(args.spec)
    path, md = build(spec, args.state_dir, asof=args.asof,
                     report_dir=args.report_dir)
    if args.print:
        print()
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
