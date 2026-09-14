#!/usr/bin/env python3
"""One reader for 'what is the book actually doing right now'.

Shared by the SessionStart hook, the status line, and the /book-status skill,
so all three can never disagree with each other.

THE NUMBER THIS EXISTS TO SURFACE
---------------------------------
`armed_gap`: trading days since the last BROKER-CONFIRMED fill. Not since the
last session, not since the last log line, not since the last ledger row --
since the last execution the broker actually reported.

That distinction is the whole point. Between 2026-08-03 and 2026-08-28 the
book ran 21 consecutive sessions that logged "ok", wrote a heartbeat, advanced
a ledger with MODELLED fills, and traded nothing, because config/.env pointed
at TWS 7497 while the gateway served 4002. Preflight caught it correctly every
single time and refused to arm. Nobody was reading preflight. A non-armed
session is silent by design, so a month went by.

docs/SYSTEM_AND_STRATEGY.md 12 -- "if you change one thing" -- says to make
that visible. This puts it in the status line and at the top of every session.

Prints JSON on stdout. Never raises: every field is independently guarded and
degrades to None with a reason, because a monitor that dies on a missing file
is the same failure mode it is supposed to catch.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR") or
            Path(__file__).resolve().parents[2])

# The prod worktree's location is a convention, not a config -- hardcoded the
# same way in ops/session_uptime.py:114, ops/schedule/install_backup.sh:44 and
# ops/promote.sh's usage line. Module constant so a test can point it elsewhere.
PROD_TREE = Path.home() / "prod" / "QUANTT"

SHADOW_SUBDIR = Path("ops/books/cef_live/_ibkr_shadow/cef_discount")
LOG_SUBDIR = Path("ops/schedule/logs")

# WHY EVERY LIVE READ BELOW IS TREE-AWARE (fixed 2026-09-11)
# ---------------------------------------------------------
# This file used to resolve all four paths against REPO -- the tree it is
# running in, i.e. dev. Since the prod split on 2026-09-10 that is the wrong
# tree for every one of them, and the failure was silent in the worst possible
# place: the SessionStart banner is the first and often the only thing an agent
# reads, and it was reporting a clean book.
#
# Measured 2026-09-11, the day this was fixed:
#
#   halts   `ls ops/HALT*.md` in dev returned NOTHING while
#           `~/prod/QUANTT/ops/HALT_phase0_null.md` was ACTIVE. Halt files are
#           UNTRACKED, so they are not merely stale in dev -- they never arrive
#           at all, by any promotion, ever. This is the one that could have cost
#           money: that halt is what stands between the phantom 1,503-share JAAA
#           short and an armed session.
#   logs    dev's newest cef log was `cef_2026-09-09`; prod had `cef_2026-09-10`
#           and every log written since lands only in prod.
#   ledger  tracked in git, so both trees hold a copy, but the scheduler writes
#           prod's. Dev's is whatever was last committed -- on 2026-09-11 dev
#           carried the null_trader repair and prod did not.
#
# So: prod first for anything the SCHEDULER writes, dev as the fallback when
# there is no prod tree (a fresh clone, another machine). Every reader reports
# the `tree` it actually read, because "which tree said this" is exactly the
# question that went unasked for a day.
def live_trees() -> list[Path]:
    """Trees to read live state from, authoritative first, deduped.

    Order is prod-then-dev and not the reverse: prod is what trades. A reader
    that silently preferred the tree it was running in is the bug this fixes.
    """
    out = []
    for t in (PROD_TREE, REPO):
        try:
            t = t.resolve()
        except Exception:
            continue
        if t.is_dir() and t not in out:
            out.append(t)
    return out or [REPO]


def _newest(rel: Path, trees: list[Path] | None = None):
    """First existing `rel` across the trees, with the tree that supplied it."""
    for t in (trees if trees is not None else live_trees()):
        p = t / rel
        if p.exists():
            return p, t
    return None, None


def _trading_days_between(start: dt.date, end: dt.date) -> int | None:
    """NYSE sessions strictly after `start`, up to and including `end`.
    Uses the scheduler's own pure-stdlib calendar so this can never disagree
    with the gate the launchd wrapper applies."""
    try:
        sys.path.insert(0, str(REPO / "ops/schedule"))
        import nyse_calendar as cal
        n, d = 0, start
        while d < end and n < 2000:
            d += dt.timedelta(days=1)
            if cal.is_trading_day(d):
                n += 1
        return n
    except Exception:
        return None


def last_broker_fill() -> dict:
    """Last row of broker_fills.csv -- the ONLY evidence of a real execution.
    Modelled ledger rows are excluded on purpose: 22 of 24 ledger trade dates
    are modelled fills for sessions that never traded."""
    out = {"date": None, "n_fills": 0, "n_sessions": 0, "gap_sessions": None,
           "tree": None}
    path, tree = _newest(SHADOW_SUBDIR / "broker_fills.csv")
    try:
        if path is None:
            return out
        out["tree"] = str(tree)
        dates = []
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                d = (row.get("fill_date") or "").strip()
                if d:
                    dates.append(d)
        if not dates:
            return out
        out["n_fills"] = len(dates)
        out["n_sessions"] = len(set(dates))
        out["date"] = max(dates)
        last = dt.date.fromisoformat(out["date"])
        out["gap_sessions"] = _trading_days_between(last, dt.date.today())
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def ledger_nav() -> dict:
    """Latest shadow-ledger NAV, displayed as indicative and never as truth.

    The ledger is a local reconstruction; the account is the fact. When the two
    diverge, order SIZING is unaffected because arm() re-seeds from
    ib.positions(), but reported NAV and P&L are wrong.

    DO NOT hardcode a divergence magnitude here. The figure that circulated for
    weeks -- "all 17 positions, ~$223k account-wide" -- predates the 2026-09-08
    epoch re-seed and no longer reproduces. Measured 2026-09-10 against a broker
    snapshot: NONE of the 17 CEFs diverge; every divergent symbol belongs to
    null_trader and the benchmark books. Re-measure with
    `ops/reconcile_orders.py --check-broker` rather than quoting any number.
    """
    out = {"date": None, "nav": None, "tree": None}
    path, tree = _newest(SHADOW_SUBDIR / "nav.csv")
    try:
        if path is None:
            return out
        out["tree"] = str(tree)
        rows = list(csv.DictReader(open(path, newline="")))
        if not rows:
            return out
        last = rows[-1]
        for k in ("date", "asof", "asof_date"):
            if last.get(k):
                out["date"] = last[k]
                break
        for k in ("nav", "nav_usd", "total_nav"):
            if last.get(k):
                out["nav"] = float(last[k])
                break
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def heartbeat() -> dict:
    """Prod's heartbeat when there is one -- the scheduler writes that copy.

    `ops/heartbeat.json` is tracked, so dev holds a copy too and the two read
    identical right after a promotion, which is exactly what makes preferring
    the wrong one hard to notice. Note the `date` field is the date the beat was
    WRITTEN, not the session it describes, so this cannot answer "did today
    arm?" -- `todays_log()` and `ops.session_uptime` can.

    Every value in the returned mapping is a dict, with no tree/meta key mixed
    in among the jobs: `session_context.py` iterates `.items()` and calls
    `v.get("status")` on every value, so a bare string here is an AttributeError
    in the SessionStart hook. Which tree supplied it is reported by `collect()`
    under `trees`, not smuggled in here.
    """
    path, _tree = _newest(Path("ops/heartbeat.json"))
    if path is None:
        return {}
    try:
        hb = json.load(open(path))
        return {job: {"status": v.get("status"),
                      "date": v.get("date"),
                      "armed": (v.get("detail") or {}).get("armed")}
                for job, v in hb.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _halt_reason(path: Path) -> dict:
    """The most recent halt ENTRY, not the file's boilerplate preamble.

    `ops/halt.py:write_halt` writes `## <timestamp>  <reason>` per entry, newest
    first, under a fixed explanatory header. Reading "the first non-heading
    line" -- which this did until 2026-09-11 -- returns that header every time,
    so every halt rendered as the same generic sentence about what a halt file
    is, and never said what actually broke.

    The `## ` + double-space split mirrors `ops/halt.py:_parse_halt` exactly.
    Deliberately a copy and not an import: this runs in the SessionStart hook,
    and `ops.halt` at import time reads `config/.env` and builds alert channels.
    A monitor must not be able to die of the thing it monitors. If that format
    ever changes, it changes in both places -- the docstring is the link.
    """
    out = {"when": None, "reason": ""}
    try:
        for line in open(path, errors="replace"):
            if line.startswith("## "):
                when, _, reason = line[3:].strip().partition("  ")
                out["when"] = when
                out["reason"] = (reason or when).strip()[:160]
                return out
        # No entry heading: a hand-written halt file. Fall back to its first
        # real line, which for a human halt is usually the whole message.
        for line in open(path, errors="replace"):
            line = line.strip()
            if line and not line.startswith("#"):
                out["reason"] = line[:160]
                break
    except Exception:
        pass
    return out


def halted() -> dict:
    """Every halt file active in EITHER tree, global and per-book.

    TWO SCOPES SINCE 2026-09-10, and this reader knew about neither until
    2026-09-11. `ops/halt.py:46` has had `scoped_path(book)` the whole time;
    this file still globbed one hardcoded `ops/HALT.md` in one tree.

      global  `ops/HALT.md`          blocks EVERY book. A human halt, or a
                                     fault nobody can attribute.
      scoped  `ops/HALT_<book>.md`   blocks ONE book; other books see it as a
                                     non-blocking preflight WARNING. arm()
                                     failures write this one, because arm only
                                     ever refuses on symbols the failing book
                                     trades. Two small books had stopped the
                                     $500k strategy over their own bookkeeping
                                     in two days before this scope existed.

    `active` DELIBERATELY still means "a global halt is up", unchanged, because
    the status line keys on it: a $20k benchmark book's bookkeeping halt must
    not paint the strategy's status line red, which is the same mistake scoped
    halts were invented to stop. Scoped halts come back in `scoped` and are
    reported by name -- visible, but not as a global block.
    """
    out = {"active": False, "reason": None, "scoped": [],
           "trees_read": [], "error": None}
    try:
        for tree in live_trees():
            out["trees_read"].append(str(tree))
            g = tree / "ops/HALT.md"
            if g.exists() and not out["active"]:
                r = _halt_reason(g)
                out["active"] = True
                out["reason"] = r["reason"]
                out["when"] = r["when"]
                out["tree"] = str(tree)
                out["path"] = str(g)
            for p in sorted((tree / "ops").glob("HALT_*.md")):
                book = p.stem[len("HALT_"):]
                if any(s["book"] == book for s in out["scoped"]):
                    continue
                r = _halt_reason(p)
                out["scoped"].append({"book": book,
                                      "reason": r["reason"],
                                      "when": r["when"],
                                      "tree": str(tree),
                                      "path": str(p)})
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def todays_log() -> dict:
    """Did the most recent CEF session arm, and what blocked it if not?

    Reads the UNION of both log trees and takes the newest by session date.
    Reading one tree undercounts by one more every session -- the defect
    `ops/session_uptime.py` was written to end, reproduced here in miniature.
    For a HISTORY rather than the last session, call that module; this is the
    cheap one-session read the SessionStart banner can afford.
    """
    out = {"date": None, "armed": None, "blockers": [], "status": None,
           "tree": None}
    try:
        cands: dict[str, tuple[Path, Path]] = {}
        for tree in live_trees():
            d = tree / LOG_SUBDIR
            if not d.is_dir():
                continue
            for p in d.glob("cef_*.log"):
                date = p.stem[len("cef_"):]
                # prod is visited first, so keep the first tree that has a date
                cands.setdefault(date, (p, tree))
        if not cands:
            return out
        date = max(cands)
        path, tree = cands[date]
        out["date"], out["tree"] = date, str(tree)
        text = path.read_text(errors="replace")
        out["armed"] = "ARMED:" in text or "arm: ARMED" in text
        for line in text.splitlines():
            if "[FAIL]" in line or "[BLOCK]" in line:
                out["blockers"].append(line.strip()[:120])
            if "status=" in line:
                out["status"] = line.split("status=")[-1].strip()[:40]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def git_state() -> dict:
    out = {"branch": None, "dirty": None}
    try:
        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                           cwd=REPO, capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            out["branch"] = r.stdout.strip()
        r = subprocess.run(["git", "status", "--porcelain"],
                           cwd=REPO, capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            out["dirty"] = len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception:
        pass
    return out


def collect() -> dict:
    trees = live_trees()
    return {
        "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        # Which trees this reading came from, authoritative first. Present so
        # that "which tree said this" is never again a question a reader has to
        # think to ask -- it went unasked for a day and hid an active halt.
        "trees": {"read": [str(t) for t in trees],
                  "prod_present": PROD_TREE.is_dir(),
                  "running_in": str(REPO)},
        "halt": halted(),
        "heartbeat": heartbeat(),
        "fills": last_broker_fill(),
        "ledger": ledger_nav(),
        "today": todays_log(),
        "git": git_state(),
    }


if __name__ == "__main__":
    try:
        json.dump(collect(), sys.stdout, indent=2 if "-p" in sys.argv else None)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
