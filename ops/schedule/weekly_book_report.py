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


def _sleeve_nav(state_dir):
    p = Path(state_dir) / "nav.csv"
    if not p.exists():
        return None
    nav = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
    return nav if not nav.empty else None


def build(books_root, asof=None, book="ops/books/book.json"):
    books_root = Path(books_root)
    asof = pd.Timestamp(asof) if asof else pd.Timestamp(
        previous_trading_day(dt.date.today() + dt.timedelta(days=1)))
    week_start = asof - pd.Timedelta(days=6)

    book_spec = _load_json(REPO / book) or {"sleeves": []}
    status = _load_json(books_root / "book_status.json")
    monitor = _load_json(books_root / "book_monitor.json")

    L = []
    A = L.append
    A(f"# Weekly book report — week ending {asof.date()}")
    A("")
    A(f"Book `{book_spec.get('book_id', '?')}` — read-only roll-up of the "
      f"daily runs (window {week_start.date()}..{asof.date()}).")
    A("")

    # -- per-sleeve table --------------------------------------------------
    A("## Sleeves")
    A("")
    A("| sleeve | last asof | NAV | week PnL | since-inception PnL | N days | note |")
    A("|---|---|---:|---:|---:|---:|---|")
    ran_any = False
    for entry in book_spec.get("sleeves", []):
        name = entry["name"]
        nav = _sleeve_nav(books_root / name)
        note = entry.get("note", "")
        if nav is None:
            A(f"| {name} | — | — | — | — | 0 | {note} (no ledger yet) |")
            continue
        ran_any = True
        last = nav.iloc[-1]
        week = nav[nav["date"] >= week_start]
        week_pnl = (float(week["nav"].iloc[-1]) - float(week["nav"].iloc[0])
                    if len(week) > 1 else 0.0)
        incep_pnl = float(last["nav"]) - float(nav["nav"].iloc[0])
        A(f"| {name} | {pd.Timestamp(last['date']).date()} "
          f"| ${float(last['nav']):,.0f} | ${week_pnl:+,.0f} "
          f"| ${incep_pnl:+,.0f} | {len(nav)} | {note} |")
    A("")
    if ran_any:
        first_dates = []
        for entry in book_spec.get("sleeves", []):
            nav = _sleeve_nav(books_root / entry["name"])
            if nav is not None:
                first_dates.append(pd.Timestamp(nav["date"].iloc[0]))
        A(f"Sample: {min(first_dates).date()}..{asof.date()} across "
          f"{len(first_dates)} live sub-ledgers.")
    else:
        A("**The book has not advanced yet** — no sub-ledger has a nav.csv. "
          "If the scheduler is in DRY_RUN=1 (the shipped default) this is "
          "expected: dry runs log targets without writing ledgers.")
    A("")

    # -- book rollup -------------------------------------------------------
    A("## Book rollup (last daily run)")
    A("")
    if status:
        A(f"- asof **{status.get('asof')}** — NAV "
          f"${status.get('book_nav', float('nan')):,.2f}, "
          f"PnL ${status.get('book_pnl', 0):,.2f}, "
          f"gross ${status.get('gross_exposure', 0):,.0f}, "
          f"turnover ${status.get('book_turnover', 0):,.0f}")
        for lim, res in (status.get("limits") or {}).items():
            A(f"- limit `{lim}`: {'OK' if res.get('ok') else '**BREACH**'}")
    else:
        A("- no book_status.json yet (no non-dry run has completed).")
    A("")

    # -- monitor verdicts --------------------------------------------------
    A("## Monitor (Gate S / staleness)")
    A("")
    if monitor:
        for name, sv in (monitor.get("sleeves") or {}).items():
            verdict = sv.get("verdict", sv.get("status", "?"))
            A(f"- {name}: **{verdict}**")
        stale = monitor.get("staleness") or monitor.get("data_staleness")
        if stale:
            A(f"- data staleness: {stale}")
    else:
        A("- no book_monitor.json yet.")
    A("")

    # -- the week's dry-run logs ------------------------------------------
    dry = sorted(books_root.glob("dryrun_*.json"))
    dry = [p for p in dry
           if week_start.date() <= _dryrun_date(p) <= asof.date()]
    A("## Dry-run activity this week")
    A("")
    if dry:
        for p in dry:
            payload = _load_json(p) or {}
            n_t = sum(len(x.get("targets", []))
                      for x in payload.get("planned", []))
            A(f"- {p.name}: {n_t} targets logged, transmitted="
              f"{payload.get('transmitted', False)}")
        A("")
        A(f"N = {len(dry)} dry-run days in {week_start.date()}..{asof.date()}.")
    else:
        A(f"- none in {week_start.date()}..{asof.date()}.")
    A("")
    return "\n".join(L)


def _dryrun_date(p):
    try:
        return dt.date.fromisoformat(p.stem.replace("dryrun_", ""))
    except ValueError:
        return dt.date(1900, 1, 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", default=None,
                    help="week-ending date (default: last trading day)")
    ap.add_argument("--book", default="ops/books/book.json")
    ap.add_argument("--books-root", default=str(REPO / "ops" / "books"))
    ap.add_argument("--out-dir", default=str(REPO / "ops" / "reports"))
    args = ap.parse_args(argv)

    text = build(args.books_root, asof=args.asof, book=args.book)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asof_tag = text.splitlines()[0].rsplit(" ", 1)[-1]
    out = out_dir / f"weekly_book_{asof_tag}.md"
    out.write_text(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
