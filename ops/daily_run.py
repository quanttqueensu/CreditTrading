"""The daily job. Run this once a day after the US close.

    python3 ops/daily_run.py                      # live: pull from yfinance
    python3 ops/daily_run.py --asof 2026-07-17    # pretend today is that day
    python3 ops/daily_run.py --source local       # replay from the audited panel

What it does, in order:

    1. reads the FROZEN spec (ops/spec/frozen_spec.json) — the only source of
       target weights anywhere in ops/
    2. pulls fresh bars for the traded tickers and appends them to the local
       price store (ops/state/prices.csv), never overwriting a stored bar
    3. advances the ledger through today, filling yesterday's order at today's
       close and deciding a new order on rebalance days
    4. writes today's TARGET vs CURRENT positions to
       ops/state/target_vs_current.csv and prints it

It is safe to run twice. It is safe to miss days: the next run catches up on
every trading day it missed, in order.

It does NOT place orders anywhere. There is no broker connection in this
directory and there is not meant to be one.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import common, ledger as ledger_mod  # noqa: E402

# How much price history to keep in front of the first live day. The impact
# model needs a 21-day trailing vol, so a cold start with no history would
# price its first trade off the fallback.
WARMUP_CALENDAR_DAYS = 90


def target_weights(spec, asof, prices):
    """Target weights on ``asof``, from the frozen spec.

    Today this is a static allocation, so the function ignores prices. It is
    still a function, and every caller goes through it, so that a spec with a
    real rule (a signal, a band, a vol target) is a change in ONE place.
    """
    alloc = spec["allocation"]
    if alloc["type"] == "static_weights":
        return dict(alloc["weights"])                       # UNCHANGED
    raise ValueError(
        f"allocation type {alloc['type']!r} is not weight-expressible on the "
        "standalone ops/daily_run.py path; run it under src/deploy/run_book.py "
        "(PortfolioOrchestrator with LongOnlySleeveLedger), which decides every "
        "day. The month-end-only decision calendar and the weights/book_usd "
        "spec assumptions here cannot serve a calendar-timed sleeve.")


def refresh_prices(spec, state_dir, asof, source, start, refetch, verbose=True):
    tickers = common.spec_tickers(spec)
    fetch_from = pd.Timestamp(start) - pd.Timedelta(days=WARMUP_CALENDAR_DAYS)
    if verbose:
        print(f"[daily] pulling {source} bars for {tickers} "
              f"{fetch_from.date()}..{pd.Timestamp(asof).date()}")
    if source == "local":
        new = common.fetch_local(tickers, fetch_from, asof)
    elif source == "yfinance":
        new = common.fetch_yfinance(tickers, fetch_from, asof, verbose=verbose)
    else:
        raise ValueError(f"unknown --source {source!r} (use yfinance or local)")

    prices, n_added, n_conflicts = common.append_prices(
        state_dir, new, refetch=refetch, verbose=verbose)
    if prices.empty:
        raise SystemExit(
            "price store is empty and nothing was fetched. If the network is "
            "down, re-run later — do NOT hand-edit ops/state/prices.csv.")

    missing = [t for t in tickers if t not in set(prices["ticker"])]
    if missing:
        raise SystemExit(f"no price history at all for {missing} — the ledger "
                         "cannot be advanced safely. Fix the feed first.")
    if verbose:
        last = prices.groupby("ticker")["date"].max()
        print(f"[daily] price store: {len(prices)} rows, "
              f"{prices['date'].min().date()}..{prices['date'].max().date()}, "
              f"{n_added} new bar(s) this run"
              + (f", {n_conflicts} restatement(s)" if n_conflicts else ""))
        for t, d in last.items():
            stale = (pd.Timestamp(asof) - pd.Timestamp(d)).days
            flag = "  <-- STALE" if stale > 5 else ""
            print(f"[daily]   {t}: last bar {pd.Timestamp(d).date()} "
                  f"({stale}d before asof){flag}")
    return prices


def write_target_vs_current(spec, lg, prices, asof, state_dir, verbose=True):
    """Today's target book against what the ledger actually holds."""
    px = common.wide(prices, "close")
    day = px.index[px.index <= pd.Timestamp(asof)][-1]
    close = px.loc[day]

    shares = lg.held_shares()
    nav = float(lg.nav_series().iloc[-1]) if not lg.nav.empty else np.nan
    targets = target_weights(spec, day, prices)
    min_trade = float(spec["rebalance"].get("min_trade_usd", 0.0))

    rows = []
    for t in sorted(set(targets) | set(shares)):
        price = float(close.get(t, np.nan))
        held = float(shares.get(t, 0.0))
        cur_val = held * price
        tw = float(targets.get(t, 0.0))
        tgt_val = nav * tw
        tgt_shares = np.floor(tgt_val / price) if price > 0 else np.nan
        rows.append({
            "asof": day.date(), "ticker": t,
            "close": round(price, 4),
            "current_shares": held,
            "current_value": round(cur_val, 2),
            "current_weight": round(cur_val / nav, 4) if nav else np.nan,
            "target_weight": tw,
            "target_shares": tgt_shares,
            "drift_shares": tgt_shares - held,
            "drift_usd": round((tgt_shares - held) * price, 2),
        })
    cash = nav - sum(r["current_value"] for r in rows)
    rows.append({"asof": day.date(), "ticker": ledger_mod.CASH,
                 "close": np.nan, "current_shares": np.nan,
                 "current_value": round(cash, 2),
                 "current_weight": round(cash / nav, 4) if nav else np.nan,
                 "target_weight": 0.0, "target_shares": np.nan,
                 "drift_shares": np.nan, "drift_usd": np.nan})

    out = pd.DataFrame(rows)
    path = Path(state_dir) / "target_vs_current.csv"
    out.to_csv(path, index=False)

    if verbose:
        common.banner(f"TARGET vs CURRENT — {day.date()}  (NAV {common.money(nav)})")
        print(out.to_string(index=False))
        due = out[out["drift_usd"].abs() >= min_trade]["ticker"].tolist()
        nxt = "the next month-end" if spec["rebalance"]["rule"] == "month_end" \
              else spec["rebalance"]["rule"]
        if due:
            print(f"\n  Drift above the {common.money(min_trade)} minimum in: "
                  f"{', '.join(due)}. This book only trades at {nxt}, so no "
                  "order is placed today unless today IS a rebalance day.")
        else:
            print(f"\n  No leg has drifted past the {common.money(min_trade)} "
                  "minimum trade size.")
        print(f"  written to {path}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", default=None,
                    help="run as if today were this date (YYYY-MM-DD)")
    ap.add_argument("--source", default="yfinance", choices=["yfinance", "local"],
                    help="where prices come from. 'local' replays the audited "
                         "panel data/etf_daily.parquet (used by the smoke test)")
    ap.add_argument("--state-dir", default=str(common.DEFAULT_STATE_DIR))
    ap.add_argument("--spec", default=str(common.SPEC_PATH))
    ap.add_argument("--start", default=None,
                    help="first live trading day, used only when the ledger is "
                         "empty (default: one week before --asof)")
    ap.add_argument("--refetch", action="store_true",
                    help="let a re-pulled bar overwrite a stored one "
                         "(default: keep the stored bar and print the clash)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    verbose = not args.quiet
    state_dir = Path(args.state_dir)
    spec = common.load_spec(args.spec)
    costs = common.load_costs()
    asof = pd.Timestamp(args.asof) if args.asof else pd.Timestamp.today().normalize()

    if verbose:
        common.banner(f"DAILY RUN — asof {asof.date()}  spec {spec['spec_id']} "
                      f"({spec['status']})")
        w = spec["allocation"]["weights"]
        print("  frozen weights : "
              + ", ".join(f"{k} {v:.1%}" for k, v in sorted(w.items())))
        print(f"  book           : {common.money(spec['book_usd'])}")
        print(f"  rebalance      : {spec['rebalance']['rule']}")
        print("  costs          : config/costs.yaml (half-spreads "
              + ", ".join(f"{k} {costs['tickers'][k]['half_spread_bp']}bp"
                          for k in sorted(w))
              + f"; impact_coef {costs['impact_coefficient']}; "
              f"max participation {costs['max_participation_pct']}%)")
        print(f"  state          : {state_dir}")

    lg = ledger_mod.Ledger(state_dir)
    if lg.last_date is None:
        start = pd.Timestamp(args.start) if args.start else (
            pd.Timestamp(spec.get("live_start"))
            if spec.get("live_start") else asof - pd.Timedelta(days=7))
    else:
        start = lg.last_date

    prices = refresh_prices(spec, state_dir, asof, args.source, start,
                            args.refetch, verbose=verbose)

    result = lg.advance(prices, spec, costs, target_weights, through=asof,
                        start=start, verbose=verbose)

    write_target_vs_current(spec, lg, prices, asof, state_dir, verbose=verbose)

    if verbose:
        if result["no_op"]:
            print("\n  Nothing changed. Running this job again today will "
                  "keep doing nothing, which is the point.")
        print("\n  Next: ops/monitor.py for the Gate S divergence check, "
              "ops/weekly_report.py once a week.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
