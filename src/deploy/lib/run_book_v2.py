"""The daily book-v2 runner (full-institutional expression). Same code, two
backends:

    EXECUTION=simulator python3 src/deploy/v2/run_book_v2.py --book ops/books/v2/book_v2.json --asof 2026-07-10
    EXECUTION=ibkr      python3 src/deploy/v2/run_book_v2.py --book ops/books/v2/book_v2.json --asof 2026-07-10

It reads a v2 BOOK SPEC (the v1 shape plus `margin`, `vol_target`, and per-sleeve
`expression` blocks), builds the MarginBroker over ONE shared MarginBook, wires
the vol-target overlay and the futures expression registry, and advances the
MarginPortfolioOrchestrator (resolve -> express -> net -> scale -> clamp ->
commit) to `--asof`. `--replay-start` loops it day-by-day so a cold book builds
up. EXECUTION=ibkr additionally lazy-connects the v1 IBKR paper account (one
account = native portfolio margin) and forwards the netted book to it; the local
MarginBook remains the simulator-of-record. `ib_insync` stays lazy in the v1
adapter — the simulator path never imports it.

Prints the book roll-up + gross/net leverage + margin utilization + the A1
financing bill, with sample dates + N (standing rule).
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.deploy import report as book_report  # noqa: E402
from src.deploy.run_book import (book_price_loader, replay_calendar,  # noqa: E402
                                 wire_runtime)
from src.deploy.lib.broker.margin_broker import MarginBroker  # noqa: E402
from src.deploy.lib.expression import Expression  # noqa: E402
from src.deploy.lib.financing import FinancingModel  # noqa: E402
from src.deploy.lib.futures import FuturesReturns  # noqa: E402
from src.deploy.lib.portfolio_v2 import MarginPortfolioOrchestrator  # noqa: E402
from src.deploy.lib.vol_target import VolTargetOverlay  # noqa: E402


def load_book_spec(path):
    with open(path) as fh:
        return json.load(fh)


def build_vol_target(book_spec):
    vt = book_spec.get("vol_target")
    if not vt or vt.get("annual_vol_target") in (None, 0):
        return None
    return VolTargetOverlay(
        annual_vol_target=float(vt["annual_vol_target"]),
        vol_window_days=int(vt.get("vol_window_days", 63)),
        k_max=vt.get("k_max"))


def build_expression(book_spec):
    cfg = {e["name"]: e["expression"] for e in book_spec.get("sleeves", [])
           if e.get("expression")}
    return Expression(cfg)


def build_broker(execution, book_spec, books_root, costs, verbose):
    try:
        futures = FuturesReturns()
    except Exception:
        futures = None
    financing = FinancingModel()
    broker = MarginBroker(books_root=books_root,
                          margin_spec=book_spec.get("margin", {}),
                          financing=financing, futures_returns=futures,
                          costs=costs, verbose=verbose)
    if execution == "ibkr":
        from src.deploy.broker import make_broker      # lazy; ib_insync inside
        live = make_broker("ibkr", books_root=books_root, verbose=verbose)
        live.connect()
        broker.attach_live(live)
        if verbose:
            print("[run_book_v2] EXECUTION=ibkr: v1 IBKR paper account attached "
                  "(one account = portfolio margin); MarginBook is the local "
                  "simulator-of-record.")
    return broker


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--source", default="local", choices=["local", "yfinance"])
    ap.add_argument("--books-root", default="ops/books/v2")
    ap.add_argument("--replay-start", default=None)
    ap.add_argument("--no-report", action="store_true",
                    help="skip the human daily report + target_vs_current.csv")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    execution = os.environ.get("EXECUTION", "simulator")
    asof = pd.Timestamp(args.asof)
    book_spec = load_book_spec(args.book)
    verbose = not args.quiet

    from ops import common as ops_common
    costs = ops_common.load_costs()

    events = wire_runtime(book_spec, verbose=verbose)
    vol_target = build_vol_target(book_spec)
    expression = build_expression(book_spec)
    broker = build_broker(execution, book_spec, args.books_root, costs, verbose)

    orch = MarginPortfolioOrchestrator(
        book_spec, broker, books_root=args.books_root,
        price_loader=book_price_loader, costs=costs, events=events,
        vol_target=vol_target, expression=expression, verbose=verbose)

    if args.replay_start:
        days = replay_calendar(book_spec, asof, args.replay_start)
        if verbose:
            print(f"[run_book_v2] EXECUTION={execution} replay "
                  f"{days[0].date()}..{days[-1].date()} N={len(days)} days")
        view = None
        for d in days:
            view = orch.advance(d, source=args.source)
    else:
        if verbose:
            print(f"[run_book_v2] EXECUTION={execution} single day asof={asof.date()}")
        view = orch.advance(asof, source=args.source)

    # human daily report + machine target_vs_current.csv (governance rule #2:
    # the daily runner writes the target book, per-sleeve state, kill-switch
    # status, and the Gate-S grade). book_status_v2.json was written by _persist.
    if view is not None and not args.no_report:
        book_report.write_v2_daily_report(
            orch, view, args.books_root, asof=view.asof,
            data_sources=book_spec.get("data_sources"), verbose=verbose)

    if verbose and view is not None:
        # today's target book — the positions each sleeve wants to hold
        print(f"\n[run_book_v2] TARGET BOOK asof {pd.Timestamp(view.asof).date()}:")
        any_t = False
        for name in orch.sleeves:
            for t in orch.last_targets.get(name, []):
                any_t = True
                size = (f"{t.qty:+,.0f} {t.kind.lower()}" if t.qty is not None
                        else f"weight {t.weight:+.2%}" if t.weight is not None
                        else "")
                print(f"[run_book_v2]   {name}: {t.side} {t.instrument} {size}"
                      + (f"  ({t.reason})" if t.reason else ""))
        if not any_t:
            print("[run_book_v2]   (no sleeve emitted a target today)")

        mu = getattr(view, "margin_util", None)
        mu_s = f"{mu:.1%}" if mu is not None else "n/a"
        print(f"\n[run_book_v2] BOOK v2 asof {pd.Timestamp(view.asof).date()}  "
              f"NAV ${view.book_nav:,.2f}  PnL ${view.book_pnl:,.2f}")
        print(f"[run_book_v2]   gross lev {getattr(view,'gross_leverage',0):.2f}x  "
              f"net lev {getattr(view,'net_leverage',0):.2f}x  "
              f"margin_util {mu_s}  financing/day ${getattr(view,'financing_usd',0):,.2f}")
        for name, sv in view.sleeves.items():
            snav = sv["shadow_nav"]
            snav_s = f"${snav:,.0f}" if snav == snav else "n/a"
            state = ("DISABLED" if sv["disabled"]
                     else "enabled" if sv["enabled"] else "off")
            print(f"[run_book_v2]   {name}: shadow NAV {snav_s}  "
                  f"verdict {sv['risk_verdict']['status']}  {state}")
        for lim, res in view.limits.items():
            print(f"[run_book_v2]   limit {lim}: {'OK' if res.get('ok') else 'BREACH'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
