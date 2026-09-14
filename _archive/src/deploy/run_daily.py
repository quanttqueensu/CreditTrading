"""Daily book unit — the cron entry point.

Runs the two steps a person (or a scheduler) does every trading afternoon, in
order, against the SAME book spec:

    1. src/deploy/run_book.py   — advance every sleeve to --asof, route orders
       through the broker, roll up NAV/PnL/turnover, write book_status.json +
       report_<asof>.md + target_vs_current.csv;
    2. ops/portfolio_monitor.py — grade the multi-sleeve book (Gate S per
       sleeve where applicable) + flag data staleness -> book_monitor.json.

Same binary, two execution backends: `EXECUTION=simulator` (proves the book on
local data) or `EXECUTION=ibkr` (after the IB Gateway runbook). Cron example
(4:30pm ET, after the close):

    30 16 * * 1-5  cd /path/to/repo && EXECUTION=ibkr \
        /opt/anaconda3/bin/python3 -m src.deploy.run_daily \
        --asof $(date +%F) --book ops/books/book.json >> ops/books/daily.log 2>&1

Exit code is non-zero if the runner fails; the monitor's verdict (CONTINUE/
HALVE/SUSPEND) is in book_monitor.json for the human to action.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.deploy import run_book  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--book", default="ops/books/book.json")
    ap.add_argument("--books-root", default="ops/books")
    ap.add_argument("--replay-start", default=None)
    ap.add_argument("--rebuild-bands", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and log the target book only — no orders, "
                         "no ledger writes, no monitor grade (book_monitor.json "
                         "and book_status.json untouched)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    verbose = not args.quiet

    # 1) advance + report
    run_argv = ["--asof", args.asof, "--book", args.book,
                "--books-root", args.books_root]
    if args.replay_start:
        run_argv += ["--replay-start", args.replay_start]
    if args.dry_run:
        run_argv.append("--dry-run")
    if args.quiet:
        run_argv.append("--quiet")
    rc = run_book.main(run_argv)
    if rc != 0:
        return rc

    if args.dry_run:
        # nothing moved, so there is nothing new to grade; leave
        # book_monitor.json exactly as the last real run wrote it.
        return 0

    # 2) grade the whole book (import here so run_book stays broker-dep-free)
    from ops import portfolio_monitor
    with open(args.book) as fh:
        book_spec = json.load(fh)
    portfolio_monitor.grade_book(book_spec, books_root=args.books_root,
                                 asof=args.asof, rebuild_bands=args.rebuild_bands,
                                 verbose=verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
