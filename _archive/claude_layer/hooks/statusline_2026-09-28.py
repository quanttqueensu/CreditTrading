#!/usr/bin/env python3
"""Status line: model, context, git — and whether the book is actually trading.

The last segment is the point. It shows trading days since the last
BROKER-CONFIRMED fill, colour-coded, permanently, in front of the operator:

    green   0-2 sessions   the book traded recently
    yellow  3-5 sessions   check it
    red     6+ / none      it is not trading and nothing else will tell you

A 21-session silent outage went unnoticed for a month here because every
surface that could have shown it — logs, heartbeat, ledger, reports — read
"ok" for a book that was refusing to arm. This is the one surface that can't.

Book state is read at most once every 45s and cached under the session id;
the status line re-runs on every assistant message and the state changes at
most once a day.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS))

R = "\033[0m"; DIM = "\033[2m"; BOLD = "\033[1m"
GREEN = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"
BLUE = "\033[34m"; CYAN = "\033[36m"; MAGENTA = "\033[35m"

CACHE_TTL = 45


def cached_book_state(session_id: str) -> dict:
    cache = Path(os.environ.get("TMPDIR", "/tmp")) / f"quantt-book-{session_id}.json"
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
            return json.loads(cache.read_text())
    except Exception:
        pass
    try:
        from book_state import collect
        state = collect()
        try:
            cache.write_text(json.dumps(state))
        except Exception:
            pass
        return state
    except Exception:
        return {}


def book_segment(state: dict) -> str:
    halt = (state.get("halt") or {})
    if halt.get("active"):
        return f"{RED}{BOLD}HALTED{R}"
    f = state.get("fills") or {}
    gap = f.get("gap_sessions")
    if f.get("date") is None:
        return f"{RED}no fills{R}"
    if gap is None:
        return f"{DIM}fill {f['date']}{R}"
    colour = GREEN if gap <= 2 else (YELLOW if gap <= 5 else RED)
    return f"{colour}fill −{gap}d{R}"


def ctx_bar(pct: float) -> str:
    filled = int(round(pct / 10.0))
    colour = GREEN if pct < 50 else (YELLOW if pct < 80 else RED)
    return f"{colour}{'█' * filled}{DIM}{'░' * (10 - filled)}{R} {pct:.0f}%"


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    parts = []

    model = (d.get("model") or {}).get("display_name")
    if model:
        parts.append(f"{MAGENTA}{model}{R}")

    cwd = (d.get("workspace") or {}).get("current_dir") or d.get("cwd") or ""
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd or None,
            capture_output=True, text=True, timeout=3).stdout.strip()
        if branch:
            dirty = subprocess.run(
                ["git", "status", "--porcelain"], cwd=cwd or None,
                capture_output=True, text=True, timeout=5).stdout
            n = len([l for l in dirty.splitlines() if l.strip()])
            parts.append(f"{CYAN}{branch}{R}" + (f"{YELLOW}*{n}{R}" if n else ""))
    except Exception:
        pass

    cw = d.get("context_window") or {}
    if cw.get("used_percentage") is not None:
        parts.append(ctx_bar(float(cw["used_percentage"])))

    # No cost segment. Auth here is the Max subscription (oauthAccount,
    # rate-limit tier default_claude_max_5x) — nothing is billed per token, so
    # the harness's cost.total_cost_usd is a notional API-rate equivalent, not a
    # charge. Showing it read as a running bill and prompted the question
    # "am I burning API credits?", which is exactly the wrong signal on a desk
    # where every displayed dollar figure is meant to be a real one.

    parts.append(book_segment(cached_book_state(str(d.get("session_id", "x")))))
    print(f" {DIM}│{R} ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
