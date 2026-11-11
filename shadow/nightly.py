"""The scheduled run: refresh, decide, build the marks, mark, write the scoreboard.

    SHADOW_STATE_DIR=<dir> QUANTT_ENV_FILE=<key file> python3 -m shadow nightly

WHY ONE COMMAND: the timer on the VM fires it several times an evening and once in the
morning (shadow/deploy/install_shadow_vm.sh). Every step is safe to repeat: a decision is
written once, a stored mark never changes, a scored session is never rescored. So a run
that finds a panel not yet published simply records UNMEASURED and the next run tries
again, and nothing needs to know which run it is.

THE AS-OF DATE is never taken from the clock alone. It is the latest session on the
exchange calendar that has closed: an earlier day, or today from SETTLE (16:30 New
York), which is after the close and its auction prints on a normal day and long after on
an early-close day. Before SETTLE on a session day the as-of date is the previous
session, which is the morning backstop's case.

A FAILED STEP DOES NOT STOP THE OTHERS, and is never silent: a refresh command that
fails is printed with its exit code, and the freshness gate then sees a stale panel and
refuses to decide. The exit code is 0 only if every book decided or already had, every
refresh command succeeded and every held name has its marks; else 3.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import pandas as pd

from . import engine, marks, scoreboard
from .book import Book

DATA_BOOK = "cef"          # whose key reads the data (team lead, 2026-11-09; sources.py WHICH KEY)
SETTLE = dt.time(16, 30)   # New York: from here a session's close and prints exist
TOL_BP = 25.0              # primary vs check: report beyond this (the mark is never changed)
REFRESH_TIMEOUT_S = 900


def asof_session(sessions: list, now: dt.datetime):
    """The latest closed session at `now` (timezone-aware), or None if there is none."""
    ny = now.astimezone(engine.NY)
    closed = [s for s in sorted(sessions)
              if s < ny.date() or (s == ny.date() and ny.time() >= SETTLE)]
    return closed[-1] if closed else None


def _refresh(book: Book, state: Path) -> list:
    """Run the book's refresh commands. Returns [(command, exit code or error)] that failed."""
    failed = []
    env = {**os.environ, "SHADOW_STATE_DIR": str(state)}
    for cmd in book.refresh:
        try:
            r = subprocess.run(list(cmd), cwd=engine.REPO, env=env, timeout=REFRESH_TIMEOUT_S)
            if r.returncode != 0:
                failed.append((" ".join(cmd), r.returncode))
        except (OSError, subprocess.TimeoutExpired) as e:
            failed.append((" ".join(cmd), type(e).__name__))
    return failed


def _needed(state: Path, books: list) -> tuple[list, dt.date | None]:
    """Every symbol any stored decision names, and the earliest decision date."""
    syms, first = set(), None
    for b in books:
        for p in sorted((state / b.slug / "decisions").glob("*.json")):
            rec = json.loads(p.read_text())
            syms |= set(rec["weights"])
            d = dt.date.fromisoformat(rec["asof"])
            first = d if first is None or d < first else first
    return sorted(syms), first


def _log(path: Path, fields, rows) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        if new:
            w.writeheader()
        w.writerows(rows)


def update_marks(state: Path, books: list, src, check, sessions: list, asof: dt.date) -> int:
    """Add the (session, symbol) marks the stored decisions need and the file lacks.
    Returns the number of gaps found (a held name with no primary print)."""
    syms, first = _needed(state, books)
    if not syms:
        return 0
    path = state / "marks.parquet"
    have = set()
    if path.exists():
        old = pd.read_parquet(path, columns=["date", "symbol"])
        have = set(zip(pd.to_datetime(old["date"]).dt.date, old["symbol"]))
    days = [s for s in sessions if first <= s <= asof and any((s, x) not in have for x in syms)]
    if not days:
        return 0
    new, bad, gaps = marks.build(syms, days, primary=src.prints, check=check,
                                 distributions=src.distributions, tol_bp=TOL_BP,
                                 primary_name="alpaca_auction_M", check_name="yfinance_close")
    marks.append(path, new)
    if len(bad):
        _log(state / "marks_disagreements.csv", list(bad.columns), bad.astype(str).to_dict("records"))
    # a gap already logged on an earlier run is not logged twice
    seen = set()
    gp = state / "marks_gaps.csv"
    if gp.exists():
        seen = {(r["date"], r["symbol"]) for r in csv.DictReader(open(gp))}
    fresh = [{"date": d.isoformat(), "symbol": s} for d, s in gaps if (d.isoformat(), s) not in seen]
    if fresh:
        _log(gp, ("date", "symbol"), fresh)
    return len(gaps)


def run(state: Path, books: list, src, *, check, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    enabled = [b for b in books if b.enabled]
    if not enabled:
        print("no enabled book under shadow/books/: nothing to do")
        return 0
    today = now.astimezone(engine.NY).date()
    first = min(b.started for b in books)
    sessions = src.sessions(first - dt.timedelta(days=10), today)
    asof = asof_session(sessions, now)
    if asof is None:
        raise engine.ShadowError(f"the calendar holds no closed session up to {today}")
    rc = 0
    for b in enabled:
        if asof < b.started:
            print(f"{b.slug}: starts {b.started}; as-of {asof} is before it")
            continue
        for cmd, code in _refresh(b, state):
            print(f"{b.slug}: REFRESH FAILED ({code}): {cmd}")
            rc = 3
        res = engine.decide(b, state, asof, now=now)
        print(f"decide {b.slug} {asof}: {res['status']} {res.get('reason', '')}".rstrip())
        if res["status"] == "UNMEASURED":
            rc = 3
    gaps = update_marks(state, books, src, check, sessions, asof)
    if gaps:
        print(f"marks: {gaps} (session, symbol) pair(s) have no primary print; see marks_gaps.csv")
        rc = 3
    mp = state / "marks.parquet"
    if mp.exists():
        m = pd.read_parquet(mp)
        for b in books:
            rows = engine.mark(b, state, m)
            bad = [r["date"] for r in rows if r["status"] == "UNMEASURED"]
            print(f"mark {b.slug}: {len(rows)} new session(s)" + (f", UNMEASURED on {bad}" if bad else ""))
        late = {b.slug: engine.late_decisions(b, state, sessions) for b in books}
        (state / "SCOREBOARD.md").write_text(scoreboard.render(books, state, late=late, today=asof))
    return rc
