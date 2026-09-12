#!/usr/bin/env python3
"""Teach `launch_job.py` the two-session cef schedule. Review, then apply.

WHY A PATCHER AND NOT AN EDIT
------------------------------
`launch_job.py` lives outside the repo (macOS TCC; see its own header) and must
stay there. That means it is not in git, not covered by the prod/dev split, and
NOT GATED BY ops/promote.sh: an edit to it is live on the next fire with no tag,
no smoke test and no rollback. Every other change to the order path has to earn
its way through a promotion; this one cannot, so the change is expressed here
instead -- versioned, diffable, reviewable, idempotent, and applied by a human
in one deliberate step with a timestamped backup beside the original.

The decision logic itself is NOT in this patch. It is in ops/session_plan.py,
inside the repo and behind the gate, and everything below is plumbing that
obeys it. If you find yourself adding a rule here, it belongs there.

    python3 ops/schedule/patch_launch_job_w3am.py            # print the diff
    python3 ops/schedule/patch_launch_job_w3am.py --apply    # write it

Applying refuses while a cef session is running, because the file is read fresh
on every fire and a half-written scheduler is the one failure mode that has no
guard anywhere.
"""
from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TARGET = Path.home() / "Library/Application Support/quantt/launch_job.py"
MARKER = "-- 0. THE SESSION PLAN"

# Each (old, new). Every `old` must appear EXACTLY once or nothing is written:
# a fuzzy match against the file that places orders is not a convenience, it is
# how you get a scheduler that runs something nobody reviewed.
EDITS: list[tuple[str, str]] = []

# -- 1. the evening job exists ------------------------------------------------
EDITS.append((
    '''            "panels": ["scripts/cef/fetch_borrow_rates.py"]},
    "phase0": {"book": "ops/books/phase0_book.json",''',
    '''            "panels": ["scripts/cef/fetch_borrow_rates.py"]},
    # The evening half of the schedule (2026-09-11, W3 Part A). SAME book and
    # SAME books-root as `cef` -- it is not a second book, it is the same book's
    # other fire, which is exactly why ops/session_plan.py has to stop the two
    # of them deciding on the same day. Its duties, in order: capture today's
    # fills before IB's 03:00 restart destroys them; write tonight's pair so the
    # 08:30 session has something to read; and decide only if the morning could
    # not. See ops/schedule/cef_pm.env.
    "cef_pm": {"book": "ops/books/cef_discount_book.json",
               "root": "ops/books/cef_live",
               "wait": "scripts/cef/wait_for_nav.py",
               "refresh": "scripts/cef/fetch_daily.py",
               "refresh_args": ["--require-asof", "{asof}", "--nav-fallback",
                                "cefconnect", "--book", "{book}"],
               "panels": ["scripts/cef/fetch_borrow_rates.py"]},
    "phase0": {"book": "ops/books/phase0_book.json",'''))

# -- 2. the refresh proves the DECISION date, which is no longer today --------
EDITS.append((
    '''            "refresh_args": ["--require-asof", "{today}", "--nav-fallback",''',
    '''            "refresh_args": ["--require-asof", "{asof}", "--nav-fallback",'''))

# -- 3. compute the plan before anything can act on it ------------------------
EDITS.append((
    '''        stamp("not an NYSE trading day - skip")
        halt_mod.beat(job, "skipped_non_trading_day")
        return 0

    # -- 1. REFRESH --------------------------------------------------------''',
    '''        stamp("not an NYSE trading day - skip")
        halt_mod.beat(job, "skipped_non_trading_day")
        return 0

    # -- 0. THE SESSION PLAN -----------------------------------------------
    # WHICH pair this fire decides on, and whether it may arm at all, comes
    # from ops/session_plan.py -- inside the repo, under test, behind the
    # promotion gate. Nothing about that decision is made in this file.
    #
    # `asof` and `today` are DIFFERENT from here down, and conflating them is
    # the specific error W3's "Do not" list opens with: the morning session
    # decides on the PREVIOUS trading day's pair and its MOC fills at today's
    # close, so a run_book called with --asof today would date the ledger's
    # fill tomorrow while the broker fills today.
    plan = None
    asof = today
    if job in ("cef", "cef_pm"):
        from ops import session_plan
        try:
            prev = subprocess.check_output(
                [PY_BIN, str(cal), "--prev", today],
                cwd=str(REPO), text=True, timeout=60).strip()
        except Exception as exc:
            # NO SILENT FALLBACK. today-minus-one would hand the sleeve a
            # Sunday or a holiday as a decision date, and the sleeve would
            # decide on whatever the panel happened to hold for it.
            stamp(f"FATAL: cannot resolve the previous trading day ({exc!r}). "
                  f"Nothing decided, nothing transmitted.")
            halt_mod.beat(job, "failed",
                          {"armed": False, "rc": 4,
                           "blockers": ["previous trading day unresolvable"]})
            halt_mod.alert(
                subject=f"QUANTT {job}: no session - calendar unreadable",
                body=f"{today}\\n\\nnyse_calendar --prev failed: {exc!r}\\n"
                     f"See {log}",
                speak="Quant session could not resolve the trading calendar.")
            return 4
        _n = datetime.now()
        plan = session_plan.plan(
            job, today=today, prev_trading_day=prev,
            beats=halt_mod.all_beats(),
            minutes_now=_n.hour * 60 + _n.minute,
            force=env.get("FORCE_TRADE") == "1")
        asof = plan.asof
        stamp(f"plan: mode={plan.mode} asof={asof} may_arm={plan.may_arm} "
              f"(today={today}, prev trading day={prev})")
        for _note in plan.notes:
            stamp(f"plan: {_note}")
        if plan.refusal:
            stamp(f"plan: WILL NOT DECIDE - {plan.refusal}")

    # -- 1. REFRESH --------------------------------------------------------'''))

# -- 4. the NAV wait is the EVENING's race, and only the evening's ------------
EDITS.append((
    '''    if cfg.get("wait"):
        # Blocks, usually for an hour or three.''',
    '''    if cfg.get("wait") and (plan is None or plan.wait):
        # Blocks, usually for an hour or three.'''))

# -- 5. the refresh args follow the decision date, and the demand is scoped ---
EDITS.append((
    '''        extra = [a.format(today=today, book=str(REPO / cfg["book"]))
                 for a in cfg.get("refresh_args", [])]''',
    '''        extra = [a.format(today=today, asof=asof, book=str(REPO / cfg["book"]))
                 for a in cfg.get("refresh_args", [])]
        if plan is not None and not plan.require_asof and "--require-asof" in extra:
            # Capture-only fire: keep the panel current, but do NOT stand the
            # session down over a pair that normally completes at ~21:45, hours
            # after this job runs. The 08:30 session fetches it again and IS
            # required to prove it.
            _i = extra.index("--require-asof")
            del extra[_i:_i + 2]
            stamp("refresh: not demanding today's pair (this fire decides "
                  "nothing; the morning session will demand it)")'''))

# -- 6. preflight checks the data for the date we are DECIDING on -------------
EDITS.append((
    '''        verdict = pf.run(job, str(REPO / cfg["book"]), today,''',
    '''        verdict = pf.run(job, str(REPO / cfg["book"]), asof,'''))

# -- 7. the plan can veto arming, and never authorises it ---------------------
EDITS.append((
    '''    live = bool(verdict.get("arm")) and not human_halt and refresh_ok''',
    '''    live = bool(verdict.get("arm")) and not human_halt and refresh_ok
    # One-way: the plan can only ever REMOVE permission. Preflight, the human
    # halt and the refresh remain the things that grant it.
    if plan is not None and not plan.may_arm:
        live = False'''))

# -- 8. the sleeve decides on the pair, not on the calendar date --------------
EDITS.append((
    '''            "--asof", today, "--book", str(REPO / cfg["book"]),''',
    '''            "--asof", asof, "--book", str(REPO / cfg["book"]),'''))
EDITS.append((
    '''        stamp(f"ARMED: EXECUTION=ibkr books-root={cfg['root']} asof={today}")''',
    '''        stamp(f"ARMED: EXECUTION=ibkr books-root={cfg['root']} asof={asof}")'''))

# -- 9. say WHY in the dry-run record ----------------------------------------
EDITS.append((
    '''        why = ("already traded today (same-day guard)" if same_day_block
               else "human halt (DRY_RUN=1)" if human_halt
               else "; ".join(verdict.get("blockers", [])) or "not armed")''',
    '''        why = ("already traded today (same-day guard)" if same_day_block
               else "human halt (DRY_RUN=1)" if human_halt
               else plan.refusal if (plan is not None and plan.refusal)
               else "; ".join(verdict.get("blockers", [])) or "not armed")'''))

# -- 10. the beat is what both guards read tomorrow ---------------------------
EDITS.append((
    '''    if cfg.get("wait"):
        detail["nav_via"] = nav_via            # None = not published by deadline
        detail["nav_ready_at"] = nav_ready_at
        detail["pair_date"] = today if refresh_ok else None''',
    '''    if plan is not None:
        detail["mode"] = plan.mode
        # THE FIELD BOTH GUARDS READ. It records the pair an order set actually
        # went out on, so it must stay None on a dry run or a stand-down --
        # otherwise a quiet week would lock the book out of every later fire.
        if live and refresh_ok:
            detail["pair_date"] = asof
        elif same_day_block:
            # The day DID trade; carry forward the pair it traded, read off the
            # beat the guard just matched. Writing None here would hit the
            # fail-closed branch of pair_already_decided() and block everything.
            detail["pair_date"] = ((halt_mod.last_beat(job) or {})
                                   .get("detail") or {}).get("pair_date")
        else:
            detail["pair_date"] = None
    if cfg.get("wait"):
        detail["nav_via"] = nav_via            # None = not published by deadline
        detail["nav_ready_at"] = nav_ready_at'''))

# -- 11. do not alert about a race the morning never ran ----------------------
EDITS.append((
    '''    if cfg.get("wait") and nav_via is None:''',
    '''    if cfg.get("wait") and (plan is None or plan.wait) and nav_via is None:'''))


def build(src: str) -> str:
    for i, (old, new) in enumerate(EDITS, 1):
        n = src.count(old)
        if n != 1:
            raise SystemExit(
                f"edit {i} matched {n} times, expected exactly 1. The target "
                f"file is not the version this patch was written against "
                f"(2026-09-11, 542 lines). Re-read it and update this patch; "
                f"do NOT relax the match.\n--- looking for ---\n{old[:400]}")
        src = src.replace(old, new)
    return src


def cef_session_running() -> str | None:
    try:
        out = subprocess.check_output(["ps", "-Ao", "pid,command"], text=True)
    except Exception as exc:
        return f"could not check for a running session ({exc!r})"
    for line in out.splitlines():
        if "launch_job.py" in line and ("cef" in line) and "patch_launch" not in line:
            return line.strip()
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the file (default: print the diff only)")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()

    target = Path(a.target)
    if not target.exists():
        raise SystemExit(f"not found: {target}")
    src = target.read_text()
    if MARKER in src:
        print(f"already applied ({target}); nothing to do.")
        return 0

    out = build(src)
    compile(out, str(target), "exec")     # never hand launchd a file that will not parse

    diff = difflib.unified_diff(src.splitlines(True), out.splitlines(True),
                                fromfile=f"{target} (current)",
                                tofile=f"{target} (patched)")
    sys.stdout.writelines(diff)

    if not a.apply:
        print("\n-- diff only. Re-run with --apply to write it. --")
        return 0

    running = cef_session_running()
    if running:
        raise SystemExit(
            f"\nREFUSING to write: a cef session is running and this file is "
            f"read fresh on every fire.\n  {running}\nWait for it to finish.")

    backup = target.with_suffix(f".py.bak-{datetime.now():%Y%m%d-%H%M%S}")
    backup.write_text(src)
    target.write_text(out)
    print(f"\nwrote {target}\nbackup {backup}")
    print("Roll back with:  cp '{}' '{}'".format(backup, target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
