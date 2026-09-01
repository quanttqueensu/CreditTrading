"""Weekly book report — the Saturday summary a human reads over coffee.

    python3 ops/schedule/weekly_book_report.py                 # -> ops/reports/weekly_book_<date>.md
    python3 ops/schedule/weekly_book_report.py --asof 2026-07-18

Read-only roll-up of what the daily runs already wrote: per-sleeve NAV / week
PnL / since-inception PnL from ops/books/<sleeve>/nav.csv, the latest book
rollup (book_status.json), the monitor verdicts (book_monitor.json), and any
dry-run logs from the week. It never grades or trades — it reads, so it cannot
disagree with the daily runner or the monitor. Every table prints its sample
dates and N (standing rule). Exits 0 with a stub report if the book has not
run yet (a freshly-enabled scheduler's first Saturday).
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "ops" / "schedule"))

import pandas as pd  # noqa: E402

from nyse_calendar import previous_trading_day  # noqa: E402


def _load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


# A book's live root holds its sub-ledgers under _ibkr_shadow/<sleeve>/, which
# is where ibkr.py's shadow Simulator writes them (src/deploy/broker/ibkr.py).
# This script used to look only at <root>/<sleeve>/nav.csv, found nothing, and
# reported "the book has not advanced yet" for five consecutive weeks while
# cef_discount and null_trader both held a funded ledger with real fills.
# Shadow path first, flat path second, so either layout resolves.
def _sleeve_nav(books_root, sleeve):
    for cand in (Path(books_root) / "_ibkr_shadow" / sleeve / "nav.csv",
                 Path(books_root) / sleeve / "nav.csv"):
        if cand.exists():
            nav = pd.read_csv(cand, parse_dates=["date"]).sort_values("date")
            if not nav.empty:
                return nav
    return None


# The live books, and the root each one's sub-ledgers are written under. This
# mirrors JOBS in ~/Library/Application Support/quantt/launch_job.py plus the
# benchmark book, which has no scheduled job of its own. The default used to be
# a single "ops/books/book.json" that has never existed in this repo, so the
# spec always fell back to {"sleeves": []} and every table rendered empty.
BOOKS = [
    ("ops/books/cef_discount_book.json", "ops/books/cef_live"),
    ("ops/books/phase0_book.json",       "ops/books/phase0_live"),
    ("ops/books/benchmarks_book.json",   "ops/books/benchmarks_live"),
]


def _dryrun_date(p):
    """Date from dryrun_<date>.json, tolerating a __<sleeve> recovery suffix."""
    stem = p.stem.replace("dryrun_", "").split("__")[0]
    try:
        return dt.date.fromisoformat(stem)
    except ValueError:
        return dt.date(1900, 1, 1)


def _book_section(book_path, books_root, asof, week_start, A):
    """Render one book. Returns True if any sub-ledger has advanced."""
    books_root = Path(books_root)
    if not books_root.is_absolute():
        books_root = REPO / books_root
    book_spec = _load_json(REPO / book_path)
    if book_spec is None:
        A(f"### `{book_path}` — **spec not found**, skipped")
        A("")
        return False

    status = _load_json(books_root / "book_status.json")
    monitor = _load_json(books_root / "book_monitor.json")

    A(f"### Book `{book_spec.get('book_id', '?')}`")
    A("")
    A("| sleeve | last asof | NAV | week PnL | since-inception PnL | N days | note |")
    A("|---|---|---:|---:|---:|---:|---|")
    ran_any = False
    first_dates = []
    for entry in book_spec.get("sleeves", []):
        name = entry["name"]
        note = entry.get("note", "")
        if not entry.get("enabled", True):
            note = (note + " (disabled)").strip()
        nav = _sleeve_nav(books_root, name)
        if nav is None:
            A(f"| {name} | — | — | — | — | 0 | {note} (no ledger yet) |")
            continue
        ran_any = True
        first_dates.append(pd.Timestamp(nav["date"].iloc[0]))
        last = nav.iloc[-1]
        week = nav[nav["date"] >= week_start]
        week_pnl = (float(week["nav"].iloc[-1]) - float(week["nav"].iloc[0])
                    if len(week) > 1 else 0.0)
        incep_pnl = float(last["nav"]) - float(nav["nav"].iloc[0])
        # A ledger whose last row predates the window is not flat, it is STALE.
        # Saying "week PnL $0" for a book that has not marked to market since
        # July would be the single most misleading number this report can print.
        lag = len(pd.bdate_range(pd.Timestamp(last["date"]), asof)) - 1
        flag = f" **STALE {lag}bd**" if lag > 1 else ""
        A(f"| {name} | {pd.Timestamp(last['date']).date()}{flag} "
          f"| ${float(last['nav']):,.0f} | ${week_pnl:+,.0f} "
          f"| ${incep_pnl:+,.0f} | {len(nav)} | {note} |")
    A("")
    if ran_any:
        A(f"Sample: {min(first_dates).date()}..{asof.date()} across "
          f"{len(first_dates)} live sub-ledger(s).")
    else:
        A("**No sub-ledger has advanced.** Either the book has never been armed, "
          "or every session since funding ran dry.")
    A("")

    if status:
        A(f"- rollup asof **{status.get('asof')}** — NAV "
          f"${status.get('book_nav', float('nan')):,.2f}, "
          f"PnL ${status.get('book_pnl', 0):,.2f}, "
          f"gross ${status.get('gross_exposure', 0):,.0f}, "
          f"turnover ${status.get('book_turnover', 0):,.0f}")
        for lim, res in (status.get("limits") or {}).items():
            A(f"- limit `{lim}`: {'OK' if res.get('ok') else '**BREACH**'}")
    else:
        A("- no book_status.json yet (no non-dry run has completed).")
    if monitor:
        for name, sv in (monitor.get("sleeves") or {}).items():
            A(f"- monitor {name}: **{sv.get('verdict', sv.get('status', '?'))}**")
    A("")
    return ran_any


def build(asof=None, books=None):
    books = books or BOOKS
    asof = pd.Timestamp(asof) if asof else pd.Timestamp(
        previous_trading_day(dt.date.today() + dt.timedelta(days=1)))
    week_start = asof - pd.Timedelta(days=6)

    L = []
    A = L.append
    A(f"# Weekly book report — week ending {asof.date()}")
    A("")
    A(f"Read-only roll-up of the daily runs across {len(books)} live book(s) "
      f"(window {week_start.date()}..{asof.date()}).")
    A("")

    A("## Sleeves")
    A("")
    ran_any = False
    for book_path, root in books:
        ran_any |= _book_section(book_path, root, asof, week_start, A)

    # -- dry-run activity --------------------------------------------------
    # Searched in the durable per-job directories, the live roots, and the
    # recovery drop. Before 2026-08-31 these went to tempfile.mkdtemp() and
    # were evicted, so this section reported "none" for the whole of August
    # while 43 dry runs had in fact been computed.
    dry = []
    for pat in ("_dryruns/*/dryrun_*.json", "_recovered_dryruns/dryrun_*.json",
                "*_live/dryrun_*.json", "dryrun_*.json"):
        dry += list((REPO / "ops" / "books").glob(pat))
    dry = sorted({p.resolve() for p in dry})
    dry = [p for p in dry if week_start.date() <= _dryrun_date(p) <= asof.date()]

    A("## Dry-run activity this week")
    A("")
    if dry:
        for p in dry:
            payload = _load_json(p) or {}
            n_t = sum(len(x.get("targets", []))
                      for x in payload.get("planned", []))
            A(f"- {p.parent.name}/{p.name}: {n_t} targets logged, "
              f"transmitted={payload.get('transmitted', False)}")
        A("")
        A(f"N = {len(dry)} dry-run file(s) in {week_start.date()}..{asof.date()}.")
    else:
        A(f"- none in {week_start.date()}..{asof.date()}.")
    A("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", default=None,
                    help="week-ending date (default: last trading day)")
    ap.add_argument("--out-dir", default=str(REPO / "ops" / "reports"))
    ap.add_argument("--print", action="store_true", dest="to_stdout")
    args = ap.parse_args(argv)

    text = build(asof=args.asof)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asof_tag = text.splitlines()[0].rsplit(" ", 1)[-1]
    out = out_dir / f"weekly_book_{asof_tag}.md"
    out.write_text(text)
    if args.to_stdout:
        print(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
