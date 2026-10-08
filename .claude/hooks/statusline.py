#!/usr/bin/env python3
"""Status line: model, context, git — and whether anything is actually trading.

The last segment is the point. A 21-session silent outage went unnoticed for a
month here because every surface read "ok" for a book that was refusing to arm.
Until 2026-09-28 this segment showed trading days since the last IBKR
broker-confirmed fill (the old version is at git tag `pre-clean-slate`). From
then until 2026-10-08 it read "no live book" in red from a constant, nine days
past the first armed Alpaca session (`docs/ROADMAP.md` 4.8).

It now shows `ops.prod_state` through `book_state.collect(vm="cached")`: which
machine is prod and how it is armed, the prod's last verify verdict, and the
other machine's state. Two armed machines read `TWO ARMED` in bold red. The VM
part is the SessionStart banner's ssh reading, shown with its age in minutes;
the status line itself never opens ssh (`book_state.py` says why).

Book state is read at most once every 45s and cached under the session id;
the status line re-runs on every assistant message and the state changes at
most a few times a day.
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
        state = collect(vm="cached")
        try:
            cache.write_text(json.dumps(state))
        except Exception:
            pass
        return state
    except Exception:
        return {}


SHORT = {"ARMED": "ARMED", "PER_DAY": "per-day", "DRY": "dry", "OFF": "off",
         "NOT_INSTALLED": "none", "UNMEASURED": "?"}
COLOUR = {"ARMED": GREEN, "PER_DAY": YELLOW, "UNMEASURED": RED}
NAME = {"laptop": "laptop", "vm": "VM"}


def _machine(name: str, m: dict) -> str:
    a = m.get("arming", "UNMEASURED")
    age = m.get("cached_age_s")
    mark = "!" if m.get("cautions") else ""
    return (f"{COLOUR.get(a, DIM)}{NAME.get(name, name)} {SHORT.get(a, a)}{mark}"
            + (f" {age // 60}m" if isinstance(age, int) else "") + R)


def book_segment(state: dict) -> str:
    """`prod VM per-day 10-07 PASS · laptop off!`, or `TWO ARMED laptop+VM`.

    Silence never reads as success: an unreadable state is red `prod ?`, and
    a state with no armed machine is red `nothing armed`, never blank.
    """
    p = (state or {}).get("prod") or {}
    v, ms = p.get("verdict"), p.get("machines") or {}
    if not v:
        return f"{RED}prod ?{R}"
    if v.get("warning"):
        return f"{RED}{BOLD}TWO ARMED {'+'.join(NAME.get(n, n) for n in v.get('hot', {}))}{R}"
    parts = []
    if v.get("prod"):
        name = v["prod"]
        seg = f"prod {_machine(name, ms.get(name) or {})}"
        vl = (ms.get(name) or {}).get("verify_last") or {}
        if "value" in vl and vl["value"].get("verdict"):
            d, verdict = vl["value"].get("date"), vl["value"]["verdict"]
            when = d[5:] if d else "undated"
            seg += f" {GREEN if verdict == 'PASS' else RED}{when} {verdict}{R}"
        else:
            seg += f" {RED}no verdict{R}"
        parts.append(seg)
    else:
        parts.append(f"{RED}nothing armed{R}")
    parts += [_machine(n, m) for n, m in ms.items() if n != v.get("prod")]
    return f" {DIM}·{R} ".join(parts)


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
