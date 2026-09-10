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

CEF_SHADOW = REPO / "ops/books/cef_live/_ibkr_shadow/cef_discount"
HEARTBEAT = REPO / "ops/heartbeat.json"
HALT = REPO / "ops/HALT.md"
LOGS = REPO / "ops/schedule/logs"


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
    out = {"date": None, "n_fills": 0, "n_sessions": 0, "gap_sessions": None}
    path = CEF_SHADOW / "broker_fills.csv"
    try:
        if not path.exists():
            return out
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
    out = {"date": None, "nav": None}
    path = CEF_SHADOW / "nav.csv"
    try:
        if not path.exists():
            return out
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
    try:
        hb = json.load(open(HEARTBEAT))
        return {job: {"status": v.get("status"),
                      "date": v.get("date"),
                      "armed": (v.get("detail") or {}).get("armed")}
                for job, v in hb.items() if isinstance(v, dict)}
    except Exception:
        return {}


def halted() -> dict:
    try:
        if HALT.exists():
            first = ""
            for line in open(HALT, errors="replace"):
                line = line.strip()
                if line and not line.startswith("#"):
                    first = line[:160]
                    break
            return {"active": True, "reason": first}
    except Exception:
        pass
    return {"active": False, "reason": None}


def todays_log() -> dict:
    """Did today's CEF session arm, and what blocked it if not?"""
    out = {"date": None, "armed": None, "blockers": [], "status": None}
    try:
        today = dt.date.today().isoformat()
        path = LOGS / f"cef_{today}.log"
        if not path.exists():
            cands = sorted(LOGS.glob("cef_*.log"))
            if not cands:
                return out
            path = cands[-1]
        out["date"] = path.stem.replace("cef_", "")
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
    return {
        "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
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
