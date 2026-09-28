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
guard anywhere. It also refuses when the tree this scheduler drives cannot
import what the patched file imports -- the patch must land AFTER the promotion
that ships ops/session_plan.py, never before it.
"""
from __future__ import annotations

import argparse
import ast
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

# -- 7b. THE REFUSAL ASKS BOTH QUESTIONS (2026-09-13, LIMIT C) ----------------
# What this replaces asked ONE question, keyed on `prior["date"]` -- the date
# the beat was FILED, not the decision it was about -- and asked it of one job.
# ops/session_plan.py already implements BOTH questions; this is the plumbing
# that calls them. The comment written into the target says why either alone is
# a hole, because that is where a reader of the scheduler will look.
EDITS.append((
    '''    # SAME-DAY GUARD. The trade phase is NOT idempotent and there is no dedupe
    # at the broker: a second armed run stacks a whole second order set. And it
    # is worse than a plain duplicate, because `arm()` reads ib.positions(),
    # which does not include the still-unfilled MOC orders the first run placed
    # -- so run two sees the OLD position, computes the SAME delta, and both
    # order sets fill in the same auction. The book doubles.
    #
    # cef.env has warned about this since 2026-07-31 ("this only bites manual
    # runs"), which was fine while only launchd fired the job. It stops being
    # fine the moment a human drives it daily, or launchd double-fires after a
    # wake. So the guard lives in code now rather than in a comment.
    #
    # Only phase 3 is gated. Refresh and preflight are read-only, and capture
    # dedupes on execId by design -- re-running those is safe and often useful,
    # which is exactly why the whole session must not be refused.
    same_day_block = False
    if live and env.get("FORCE_TRADE") != "1":
        prior = halt_mod.last_beat(job)
        if (prior and str(prior.get("date")) == today
                and (prior.get("detail") or {}).get("armed")):
            same_day_block = True
            live = False
            stamp(f"SAME-DAY GUARD: {job} already ran ARMED today at "
                  f"{prior.get('at')}. NOT transmitting a second order set. "
                  f"Data refresh and fill capture still run. Override with "
                  f"FORCE_TRADE=1 only after cancelling the pending orders.")''',
    '''    # THE TWO-QUESTION GUARD (2026-09-13; was the SAME-DAY GUARD).
    #
    # The trade phase is NOT idempotent and there is no dedupe at the broker: a
    # second armed run stacks a whole second order set. It is worse than a
    # plain duplicate, because `arm()` reads ib.positions(), which does not
    # include the still-unfilled MOC orders the first run placed -- so run two
    # sees the OLD position, computes the SAME delta, and both sets fill in the
    # same auction. The book doubles. That blindness is structural and is not a
    # bug about to be fixed: `grep -n reqOpenOrders src/deploy/broker/ibkr.py`
    # returns nothing, so this guard is the only thing standing here.
    #
    # WHY IT STILL RUNS HERE AND NOT IN THE PLAN. `plan` was computed in phase
    # 0, BEFORE the NAV wait. On 2026-09-10 that wait ran 17h23m across a
    # system sleep (ops/decision_age.py), so a plan computed at 17:15 was acted
    # on at 10:38 the next morning against a heartbeat that had moved under it.
    # This is the only read of the heartbeat taken immediately before the order
    # goes out; folding it into the plan would delete the fresh read.
    #
    # TWO QUESTIONS. NEITHER IS SUFFICIENT ALONE AND NEITHER REPLACES THE OTHER:
    #
    #   PAIR  -- keyed on the beat's `session_date`, the decision it was ABOUT.
    #            Catches yesterday evening's fallback deciding pair D and this
    #            morning deciding pair D again. Those are different CALENDAR
    #            days, so a date-keyed test is structurally blind to them.
    #
    #   TODAY -- keyed on the beat's `date`, the day it was FILED, the closest
    #            proxy this system records for the day the set was TRANSMITTED.
    #            Catches two fires on DIFFERENT pairs both reaching this point
    #            before the 15:50 ET freeze, whose sets land in the SAME
    #            auction. A pair-keyed test is structurally blind to them.
    #
    # The TODAY question is asked of the date this process STARTED and of the
    # date it is asking ON, because a session that slept has two of them: on
    # 2026-09-10 `today` was still 2026-09-10 when the order went out on 09-11.
    #
    # Only phase 3 is gated. Refresh and preflight are read-only, and capture
    # dedupes on execId by design -- re-running those is safe and often useful,
    # which is exactly why the whole session must not be refused.
    same_day_block = False
    guard_reason = None
    guard_blocker_job = None
    if live and env.get("FORCE_TRADE") != "1":
        beats_now = halt_mod.all_beats()
        if plan is not None:
            # The cef family writes TWO beats into ONE heartbeat and each fire
            # must be able to see the other, so this reads EVERY beat and not
            # just this job's. Both helpers live in ops/session_plan.py, inside
            # the repo and behind ops/promote.sh. Nothing is decided here.
            from ops import session_plan
            guard_blocker_job = session_plan.pair_already_decided(beats_now, asof)
            if guard_blocker_job:
                guard_reason = (
                    f"PAIR GUARD: pair {asof} was already decided by an armed "
                    f"{guard_blocker_job} session at "
                    f"{(beats_now.get(guard_blocker_job) or {}).get('at')}")
            else:
                guard_dates = [today]
                guard_now_date = f"{datetime.now():%Y-%m-%d}"
                if guard_now_date != today:
                    guard_dates.append(guard_now_date)
                for guard_date in guard_dates:
                    guard_blocker_job = session_plan.decided_today(beats_now,
                                                                  guard_date)
                    if guard_blocker_job:
                        guard_reason = (
                            f"TODAY GUARD: {guard_blocker_job} already armed on "
                            f"{guard_date} at "
                            f"{(beats_now.get(guard_blocker_job) or {}).get('at')}"
                            f"; a second set entered before 15:50 ET fills in "
                            f"the SAME auction")
                        break
        else:
            # Every other book keeps the single-job, date-keyed test unchanged.
            # They record NO decision date -- the live `benchmarks` beat of
            # 2026-09-10 carries armed=True with no pair_date at all -- so
            # asking them the PAIR question would take the fail-closed branch of
            # pair_already_decided() on every fire and never open again.
            prior = halt_mod.last_beat(job)
            if (prior and str(prior.get("date")) == today
                    and (prior.get("detail") or {}).get("armed")):
                guard_blocker_job = job
                guard_reason = (f"SAME-DAY GUARD: {job} already ran ARMED today "
                                f"at {prior.get('at')}")
        if guard_reason:
            same_day_block = True
            live = False
            stamp(f"{guard_reason}. NOT transmitting a second order set. "
                  f"Data refresh and fill capture still run. Override with "
                  f"FORCE_TRADE=1 only after cancelling the pending orders.")'''))

# -- 8. the sleeve decides on the pair, not on the calendar date --------------
# `--job` rides along here because this edit already owns the line. arm()
# derives how old a decision may be from the job's plist and env, and the job
# is NOT derivable from the book: preflight records that job "cef" maps to book
# "cef_discount_paper", and since the split "cef" (08:30) and "cef_pm" (17:30)
# share one book and one books-root while having different plists and therefore
# different ceilings. Without it the decision-age guard is silently inert.
EDITS.append((
    '''            "--asof", today, "--book", str(REPO / cfg["book"]),''',
    '''            "--asof", asof, "--book", str(REPO / cfg["book"]),
            "--job", job,'''))
EDITS.append((
    '''        stamp(f"ARMED: EXECUTION=ibkr books-root={cfg['root']} asof={today}")''',
    '''        stamp(f"ARMED: EXECUTION=ibkr books-root={cfg['root']} asof={asof}")'''))

# -- 9. say WHY in the dry-run record ----------------------------------------
EDITS.append((
    '''        why = ("already traded today (same-day guard)" if same_day_block
               else "human halt (DRY_RUN=1)" if human_halt
               else "; ".join(verdict.get("blockers", [])) or "not armed")''',
    '''        # `guard_reason` is set on exactly the branch that sets same_day_block,
        # so it is never None here. The dry-run record names WHICH question
        # refused; "already traded today" said the same thing for both, which is
        # how a pair refusal and a date refusal stayed indistinguishable in the
        # only durable record of a day the book did not trade.
        why = (guard_reason if same_day_block
               else "human halt (DRY_RUN=1)" if human_halt
               else plan.refusal if (plan is not None and plan.refusal)
               else "; ".join(verdict.get("blockers", [])) or "not armed")'''))

# -- 10. the beat is what both guards read tomorrow ---------------------------
EDITS.append((
    '''    if cfg.get("wait"):
        detail["nav_via"] = nav_via            # None = not published by deadline
        detail["nav_ready_at"] = nav_ready_at
        detail["pair_date"] = today if refresh_ok else None''',
    '''    if guard_reason:
        # WHICH question refused, on the beat itself, for the operator and for
        # ops/orient.py. Recorded alongside `armed`, never instead of it.
        detail["guard"] = guard_reason
        detail["guard_blocker"] = guard_blocker_job
    if plan is not None:
        detail["mode"] = plan.mode
        # THE FIELD BOTH GUARDS READ. It records the pair an order set actually
        # went out on, so it must stay None on a dry run or a stand-down --
        # otherwise a quiet week would lock the book out of every later fire.
        if live and refresh_ok:
            detail["pair_date"] = asof
        elif same_day_block:
            # The day DID trade; carry forward the pair it traded, read off THE
            # BEAT THE GUARD MATCHED -- which since 2026-09-13 may belong to the
            # OTHER cef fire and not to this job, so last_beat(job) would carry
            # the wrong pair, or None. `armed` stays True on a guarded re-run,
            # so a None here hits the fail-closed branch of
            # pair_already_decided() and blocks every later fire.
            blocked_by = halt_mod.all_beats().get(guard_blocker_job) or {}
            detail["pair_date"] = (blocked_by.get("session_date")
                                   or (blocked_by.get("detail") or {}
                                       ).get("pair_date"))
        else:
            detail["pair_date"] = None
    if cfg.get("wait"):
        detail["nav_via"] = nav_via            # None = not published by deadline
        detail["nav_ready_at"] = nav_ready_at'''))

# -- 11. do not alert about a race the morning never ran ----------------------
EDITS.append((
    '''    if cfg.get("wait") and nav_via is None:''',
    '''    if cfg.get("wait") and (plan is None or plan.wait) and nav_via is None:'''))


# -- 11. NO PHASE MAY OUTLIVE THE SESSION -------------------------------------
# `run()` took no timeout and NO caller passed one, across all six call sites.
# Phases 1, 2, 3, 6 and 7 are serial-blocking, so a hang in any of them holds
# the book's trading day. The same file already does this correctly for
# `run_collect` (timeout=1200) -- a job that CANNOT hurt trading. The cheap
# thing was bounded and the expensive thing was left open.
#
# THE BUDGET IS DERIVED, NOT WRITTEN. A phase gets whatever the session's own
# ceiling leaves it after a reserve for the phases that must still follow. The
# ceiling comes from ops/doctor.py::_session_deadline_minutes -- the same
# derivation the stuck-session guard uses -- so the two cannot drift apart, and
# a job whose ceiling cannot be derived gets NO timeout rather than a guessed
# one (the whole defect class here is a literal that stopped matching reality).
#
# HONEST LIMIT, SO NOBODY MISREADS THIS AS THE SLEEP FIX: subprocess timeouts
# are measured on a monotonic clock, which on Darwin does not advance across
# system sleep. This would NOT have caught 2026-09-11, where the Mac
# clamshell-slept at 22:06 and resumed at 07:09. It bounds a hung child, a real
# and separate class -- `qualifyContracts` and `ib.sleep(15)` in
# scripts/cef/fetch_borrow_rates.py have no bound at all. `sudo pmset -a
# disablesleep 1` is what PREVENTS the sleep; edit 16 below is what makes a
# session that slept anyway refuse to act. The two are not interchangeable and
# neither replaces this one.
EDITS.append((
    '''    def run(args, **kw) -> int:
        with open(log, "a") as fh:
            return subprocess.call(args, stdout=fh, stderr=fh, cwd=str(REPO), **kw)''',
    '''    # Memo, not a recomputation per phase: [] = not derived yet, [None] =
    # underivable AND already announced, so the warning is printed once.
    _ceiling = []

    def session_ceiling():
        """Minutes from this fire's start to the latest it may still be alive.

        THE ONE DERIVATION, AND DELIBERATELY NOT A SECOND ONE.
        `ops/doctor.py::_session_deadline_minutes` is what the stuck-session
        guard compares `ps -o etime=` against -- and `etime` is wall clock, so
        a session judging itself by anything else would disagree with the guard
        that judges it from outside. It reads the INSTALLED plist and the job's
        env, so it is correct at 17:15 today, correct at 08:30/17:30 once the
        split is rendered, and correct again if the split is rolled back. The
        whole defect class here is a literal that stopped matching the schedule
        it described.

        None when it cannot be derived -- and SAID OUT LOUD when that happens.
        A guessed ceiling would kill healthy sessions, but an unannounced None
        silently disarms BOTH the phase budget and the wall-clock deadline, and
        `cef_pm` has no installed plist until the schedule is rendered. That is
        exactly the window in which this would otherwise go quiet.
        """
        if not _ceiling:
            try:
                from ops import doctor as _doc
                _ceiling.append(_doc._session_deadline_minutes(job))
            except Exception as exc:
                _ceiling.append(None)
                stamp(f"NO SESSION CEILING: ops.doctor could not derive one for "
                      f"{job} ({exc!r}). The phase budgets and the wall-clock "
                      f"session deadline are both INERT for this fire.")
            else:
                if _ceiling[0] is None:
                    stamp(f"NO SESSION CEILING for {job}: no installed plist, or "
                          f"a post-close job whose NAV_DEADLINE will not parse. "
                          f"The phase budgets and the wall-clock session "
                          f"deadline are both INERT for this fire.")
        return _ceiling[0]

    def session_elapsed_min() -> float:
        """Wall-clock minutes since this fire started. NOT monotonic, on purpose.

        MEASURED on this machine 2026-09-13: time.monotonic() is
        mach_absolute_time() and does NOT advance across system sleep -- 3617h
        of wall clock since boot against 1232h of monotonic, a 2385h gap. A
        session that slept HAS burned its window: the auction it meant to trade
        into has been and gone. Only the wall clock can see that, which is why
        `session_started` is a datetime and not a counter.
        """
        return (datetime.now() - session_started).total_seconds() / 60.0

    def phase_budget(reserve_min: int):
        """Minutes this phase may run: the session ceiling, less what the
        session has already spent, less a reserve for the phases still to come.
        None when the ceiling cannot be derived -- unbounded beats invented."""
        ceiling = session_ceiling()
        if ceiling is None:
            return None
        return max(1, int(ceiling - session_elapsed_min() - reserve_min))

    def run(args, budget_min=None, **kw) -> int:
        with open(log, "a") as fh:
            if budget_min is None:
                return subprocess.call(args, stdout=fh, stderr=fh,
                                       cwd=str(REPO), **kw)
            try:
                return subprocess.call(args, stdout=fh, stderr=fh,
                                       cwd=str(REPO), timeout=budget_min * 60,
                                       **kw)
            except subprocess.TimeoutExpired:
                stamp(f"TIMEOUT: {' '.join(str(a) for a in args[-3:])} exceeded "
                      f"its {budget_min}m budget and was killed. The budget is "
                      f"the session ceiling less time already spent; see "
                      f"ops/doctor.py::_session_deadline_minutes.")
                return 124'''))

# The session's own start, so a budget is measured from the session rather than
# from whenever a phase happens to begin. Wall clock deliberately: a monotonic
# clock does not advance across system sleep on Darwin, and a session that
# slept HAS burned its window even though no CPU time passed.
EDITS.append((
    '''    sys.path.insert(0, str(REPO))
    today = f"{datetime.now():%Y-%m-%d}"''',
    '''    sys.path.insert(0, str(REPO))
    session_started = datetime.now()
    today = f"{datetime.now():%Y-%m-%d}"'''))

# The panel phase is the one explicitly allowed to FAIL, and it is still
# serial-blocking -- "non-fatal to the verdict" is not "non-blocking in time".
# Reserve 20 minutes for preflight, trade and capture; capture alone measured
# 9m48s on the 1,529-execution session of 2026-09-08.
EDITS.append((
    '''        prc = run([PY_BIN, "-u", str(REPO / panel)])''',
    '''        prc = run([PY_BIN, "-u", str(REPO / panel)],
                  budget_min=phase_budget(reserve_min=20))'''))

# -- 16. NO SESSION MAY OUTLIVE ITS WINDOW ------------------------------------
# The subprocess budget above bounds a hung CHILD and cannot bound a sleeping
# MACHINE: its timeout is monotonic, and on Darwin the monotonic clock stops
# with the box. This is the other half, and the halves are not interchangeable.
# Placed immediately after the halt import because it beats and alerts; every
# boundary below it calls it.
DEADLINE_HELPER = '''    # -- THE WALL-CLOCK SESSION DEADLINE ------------------------------------
    # subprocess timeouts are measured on a MONOTONIC clock, which on Darwin is
    # mach_absolute_time() and does not advance across system sleep (measured on
    # this machine 2026-09-13: 3617h of wall clock since boot against 1232h of
    # monotonic, a 2385h gap). So the budget above cannot see the failure that
    # has now cost three sessions. On 2026-09-11 cef started 17:15:05 and won
    # its NAV race at 22:00:52; the log's next timestamp is 07:09:11 the NEXT
    # MORNING, on the panel phase's rc line -- 13h54m into a 7h15m window. (The
    # sleep is bounded by those two stamps and no further: the lines between
    # them are the refresh's and the panel's own unstamped output, so WHICH
    # phase was running when the box went down is not established by the log.)
    # It then ran preflight, run_book and capture as though nothing had
    # happened, and transmitted nothing only because the same-day guard, which
    # exists to answer an entirely different question, happened to say no.
    #
    # So the session is given the ability to see its own lateness, at every
    # boundary where it still has the choice not to act.
    #
    # WHAT THIS DELIBERATELY DOES NOT DO: it writes NO halt file. A halt is
    # durable, blocks every later fire and needs a human to clear it, so one
    # late night would become an outage -- the failure this desk has already
    # had twice in two days from two small books. A stand-down is a SKIPPED
    # SESSION, not a fault: the beat records it, the alert says it, and the
    # next scheduled fire runs normally.
    LATE_RC = 75        # EX_TEMPFAIL: "try again later", not "this is broken".
                        # Distinct from 2 (unknown job), 3 (repo missing),
                        # 4 (calendar unreadable) and 124 (a child timed out).

    def stood_down_late(phase: str) -> bool:
        """True if this fire has outlived its window; stands it down first.

        The beat must be distinguishable from a crash, because the two want
        opposite responses: a crash wants someone to read a traceback, a
        stand-down wants someone to stop the machine sleeping. So the status is
        its own string, `late` is explicit, and the detail carries the
        arithmetic that produced the verdict rather than just its conclusion.
        """
        ceiling = session_ceiling()
        if ceiling is None:
            return False              # already announced, once, by session_ceiling
        elapsed = session_elapsed_min()
        if elapsed <= ceiling:
            return False

        prior = halt_mod.last_beat(job) or {}
        pdetail = prior.get("detail") or {}
        # NEVER ERASE TODAY'S ARMED BEAT -- AND NEVER CARRY IT PAST MIDNIGHT.
        # Two guards read `detail.armed`: the same-day guard below, and
        # session_plan's TODAY guard, which is what stops the evening fallback
        # deciding after the morning already has. Writing armed=False here
        # would blind both and let a second order set into the auction. But
        # carrying armed=True into a beat FILED the next morning rebuilds the
        # 2026-09-10 defect with the opposite sign -- `date` is the day the
        # beat was filed, so tomorrow's session would refuse itself (see
        # ops/halt.py::beat, "one power event, two lost sessions"). So it is
        # carried only when this beat lands on the same calendar day as the
        # armed beat it replaces.
        filed = f"{datetime.now():%Y-%m-%d}"
        carry = bool(pdetail.get("armed")) and str(prior.get("date")) == filed

        stamp(f"SESSION DEADLINE: started {session_started:%Y-%m-%d %H:%M:%S}, "
              f"it is now {datetime.now():%Y-%m-%d %H:%M:%S} -- "
              f"{int(elapsed) // 60}h{int(elapsed) % 60:02d}m against a "
              f"{ceiling // 60}h{ceiling % 60:02d}m ceiling derived from the "
              f"installed plist and {job}.env. STANDING DOWN at the {phase} "
              f"boundary; this fire transmitted nothing. No halt file is "
              f"written, so the next scheduled fire runs normally.")
        halt_mod.beat(job, "stood_down_late",
                      {"armed": carry,
                       "this_fire_armed": False,
                       "late": True,
                       "phase": phase,
                       "rc": LATE_RC,
                       "started_at": f"{session_started:%Y-%m-%d %H:%M:%S}",
                       "elapsed_min": int(elapsed),
                       "ceiling_min": int(ceiling),
                       "pair_date": pdetail.get("pair_date") if carry else None,
                       "blockers": [f"session deadline exceeded at {phase}: "
                                    f"{int(elapsed)}m of a {int(ceiling)}m "
                                    f"window"]})
        halt_mod.alert(
            subject=f"QUANTT {job}: stood down - the session outlived its window",
            body=(f"started {session_started:%Y-%m-%d %H:%M:%S}, now "
                  f"{datetime.now():%Y-%m-%d %H:%M:%S}: {int(elapsed)} minutes "
                  f"against a {int(ceiling)}-minute ceiling.\\n\\n"
                  f"Stood down at the {phase} boundary. NOTHING WAS "
                  f"TRANSMITTED by this fire and no halt file was written, so "
                  f"the next scheduled fire runs normally.\\n\\n"
                  f"The usual cause is the machine sleeping mid-session; "
                  f"python3 -m ops.doctor --quick reports the power state that "
                  f"allowed it.\\n\\nSee {log}"),
            speak="Quant session stood down. It outlived its window.")
        return True
'''
EDITS.append((
    """    # Import AFTER sys.path is set; these live inside the TCC-protected repo.
    from ops import halt as halt_mod
    from ops import preflight as pf
""",
    """    # Import AFTER sys.path is set; these live inside the TCC-protected repo.
    from ops import halt as halt_mod
    from ops import preflight as pf

""" + DEADLINE_HELPER))

# -- 17. boundary: after the NAV wait, the only phase that blocks for HOURS ---
EDITS.append((
    '''            refresh_ok = False
    if cfg["refresh"]:''',
    '''            refresh_ok = False
    # wait_for_nav computes its deadline ONCE at start and checks it only AFTER
    # the completeness check (its own docstring says why), so a poll that lands
    # the next morning and finds the pair complete returns 0 -- a clean success,
    # hours outside the window. On 2026-09-11 the box slept somewhere between
    # 22:00:52 and 07:09:11 instead; either way the session
    # wakes up believing it is still in its window. The 2026-09-10 session did
    # exactly that and went on to ARM at 10:38:32 the NEXT morning, during
    # market hours, on a decision computed the previous evening.
    if stood_down_late("1. REFRESH"):
        return LATE_RC
    if cfg["refresh"]:'''))

# -- 18. boundary: before the panels, which open a broker socket --------------
EDITS.append((
    '''    for panel in cfg.get("panels", ()):''',
    '''    if stood_down_late("1b. PANELS"):
        return LATE_RC
    for panel in cfg.get("panels", ()):'''))

# -- 19. boundary: before preflight ------------------------------------------
EDITS.append((
    '''    # -- 2. PREFLIGHT ------------------------------------------------------
    try:''',
    '''    # -- 2. PREFLIGHT ------------------------------------------------------
    if stood_down_late("2. PREFLIGHT"):
        return LATE_RC
    try:'''))

# -- 20. boundary: before the trade phase. THE ONE THAT MATTERS --------------
EDITS.append((
    '''    # -- 3. TRADE ----------------------------------------------------------
    args = [PY_BIN,''',
    '''    # -- 3. TRADE ----------------------------------------------------------
    # THE BOUNDARY THAT MATTERS: nothing has been transmitted yet. An MOC
    # entered after 15:50 ET cannot be cancelled at all, not even to correct a
    # legitimate error, so a session that has lost track of what time it is must
    # not reach place_targets. arm()'s decision-age guard asks whether the
    # DECISION is stale; this asks whether the FIRE carrying it is, and they are
    # different questions -- the decision can be minutes old while the session
    # that computed it is fourteen hours old.
    if stood_down_late("3. TRADE"):
        return LATE_RC
    args = [PY_BIN,'''))

# -- 21. and NO boundary before capture, on purpose --------------------------
EDITS.append((
    '''    if wants_ibkr:
        stamp("capturing broker executions''',
    '''    # NO DEADLINE CHECK HERE, DELIBERATELY, AND DO NOT ADD ONE TO COMPLETE
    # THE SET. Phase 4 is the one phase whose failure policy is "always":
    # ib.fills() serves the current TWS session only and IB's 03:00 restart
    # empties it, so a fill not captured today is gone -- the 2026-09-11 log
    # shows `[capture] 0 execution(s) in the TWS session` at 07:09:14, after
    # that restart. A late session reaches this line only by having been late
    # DURING phase 3, i.e. after it may already have transmitted, which is the
    # moment capture matters most. Standing down here would have the guard
    # destroy the record the incident it guards against destroyed.
    if wants_ibkr:
        stamp("capturing broker executions'''))


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


EXIT_MISSING_MODULE = 3

# The tree THIS patcher was run from: the one ops/session_plan.py and friends
# were written in, and the one a promotion would ship. parents[2] because this
# file sits at <repo>/ops/schedule/.
SOURCE_REPO = Path(__file__).resolve().parents[2]

if not (SOURCE_REPO / "ops").is_dir():
    # Fail CLOSED on the one assumption the classifier rests on. If this file is
    # ever moved out of ops/schedule/ the depth is wrong, every lookup below
    # misses, `repo_imports` returns [] and the guard silently passes everything
    # -- a guard that fails open is worse than no guard, because it is read as
    # evidence. Refuse to load instead.
    raise SystemExit(
        f"patch_launch_job_w3am.py resolves SOURCE_REPO to {SOURCE_REPO}, which "
        f"has no ops/. This file must live at <repo>/ops/schedule/ for the "
        f"import check to tell a repo module from an environment dependency.")


def _module_file(root: Path, dotted: str) -> Path | None:
    """Where `import dotted` would resolve under `root`, or None.

    Filesystem only, deliberately. The tree being interrogated is PROD, and
    importing a module to find out whether it exists would execute prod's code
    from a tool whose whole job is to not disturb prod until a human says so.
    """
    base = root.joinpath(*dotted.split("."))
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def repo_imports(built: str) -> list[str]:
    """Every dotted name the BUILT output imports that THIS repo supplies.

    Read out of the output's own AST, never from a list kept by hand. A
    hand-written list is correct the day it is written and wrong the day
    somebody adds an import to EDITS -- which is precisely the day it matters,
    because that is the day the scheduler grows a dependency the tree it drives
    has never been given.

    "That this repo supplies" is settled by looking each name up in SOURCE_REPO,
    so `ops.session_plan` is in and `pandas` is out without anyone naming
    either, and a future edit that imports `src.deploy.anything` is covered for
    free. pandas is an environment dependency; ops/ is a promotion artifact, and
    only the second kind can be missing because someone patched before promoting.

    `from P import n` contributes BOTH `P.n` and `P`: if `P/n.py` exists here
    then n is a submodule and the target needs that file; if it does not, n is
    an attribute of P's __init__ and only P is required. The filesystem decides,
    not a rule about how things are spelled.

    There is NO try/except exemption. An import inside `except Exception` is
    softer at runtime, but deciding which handlers actually swallow ImportError
    is judgement, and judgement that gets it wrong here ships a scheduler that
    dies at 08:30. A wrong refusal costs one promotion, done in the order it
    should have been done anyway; a wrong pass costs the trading day.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(built)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                # launch_job.py is a top-level script, not a package, so a
                # relative import cannot resolve there at all. Say so rather
                # than skip it: an import this function cannot reason about is
                # not an import it may quietly ignore.
                raise SystemExit(
                    f"line {node.lineno} of the patched output is a relative "
                    f"import, which cannot resolve in a top-level script and "
                    f"cannot be checked against the target tree. Refusing.")
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return sorted(n for n in names if _module_file(SOURCE_REPO, n))


def target_repo(src: str) -> Path:
    """The tree the INSTALLED scheduler drives, read out of the file itself.

    One line, and it is the entire prod/dev boundary. Parsed exactly as
    ops/doctor.py::check_entrypoint parses it -- same startswith, same split --
    so the two can never disagree about which checkout the scheduler points at.
    Not imported from doctor: check_entrypoint reads doctor's own module-level
    LAUNCH_JOB and reports into a doctor Report, while this has to answer for
    whatever --target names.
    """
    for line in src.splitlines():
        if line.startswith("REPO = Path("):
            if '"' not in line:
                raise SystemExit(
                    f"the REPO line is not a double-quoted literal, so it "
                    f"cannot be read without executing the file:\n  "
                    f"{line.strip()}")
            return Path(line.split('"')[1])
    raise SystemExit(
        'no `REPO = Path("...")` line in the target: there is no way to tell '
        'which tree this scheduler drives, and therefore no way to tell '
        'whether that tree has the modules the patch needs. Refusing to write.')


def _target_version(repo: Path) -> str:
    """What the target tree is checked out at. For the message only.

    Best effort, and it SAYS SO when it fails: the string is decoration in a
    human-readable refusal, never an input to the refusal itself.
    """
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "describe", "--tags", "--always"],
            text=True, stderr=subprocess.DEVNULL, timeout=20).strip()
    except Exception as exc:
        return f"<could not read: {exc!r}>"


def check_target_tree_has_imports(target: Path, src: str, built: str) -> int:
    """0 if the target tree can import everything the patched file imports.

    Otherwise prints why and returns EXIT_MISSING_MODULE. --apply ONLY.

    WHY THIS EXISTS
    ---------------
    2026-09-11 (W3 Part A) put `from ops import session_plan` on the session
    path of the patched output, unguarded. ops/session_plan.py is in git and
    behind ops/promote.sh; launch_job.py is neither, and applying this patch
    takes effect on the very next fire. So the patcher can hand the scheduler a
    dependency on a module the tree it drives has not been promoted yet -- and
    nothing else in the system would catch it. The patched file COMPILES, so
    the compile() above passes. doctor reads launch_job.py for `--job`, not for
    its imports. The suite runs against THIS tree, where the module obviously
    exists. The first symptom is ImportError at 08:30, after launchd has
    already started the job: no order set, no NAV wait, and a stand-down that
    looks like a machine fault rather than an ordering mistake.

    The remedy is an ordering, not a code change: promote, then patch.

    ONE HOP DEEP, and it does not pretend otherwise. It reads launch_job.py's
    own imports and does not follow what those modules import in the target
    tree -- src/deploy/broker/ibkr.py imports ops.decision_age, which imports
    ops.session_plan, and prod today lacks both. That transitive chain is
    caught here only because the direct import of ops.session_plan happens to
    share its cause (the tree is behind). Closing it properly means walking the
    target's import graph.
    """
    repo = target_repo(src)
    if not (repo / "ops").is_dir():
        print(f"\nREFUSING to write: {target} points at REPO={repo}, which has "
              f"no ops/ -- nothing will run there and nothing can be checked.",
              file=sys.stderr)
        return EXIT_MISSING_MODULE

    required = repo_imports(built)
    missing = [m for m in required if _module_file(repo, m) is None]
    if not missing:
        return 0

    rows = []
    for m in missing:
        rel = _module_file(SOURCE_REPO, m).relative_to(SOURCE_REPO)
        rows.append(f"    {m:<22} needs {repo / rel}")
    print(
        f"\nREFUSING to write: the tree this scheduler drives cannot import "
        f"everything the patched file imports.\n"
        f"\n  target launch_job : {target}"
        f"\n  its REPO         : {repo}  (at {_target_version(repo)})"
        f"\n  missing there    :\n" + "\n".join(rows) +
        f"\n\nApplying now would leave every fire that reaches one of those "
        f"imports dying with ImportError, after launchd has already started "
        f"it: no order set, no NAV wait, and a stand-down that reads like a "
        f"machine fault instead of an ordering mistake.\n"
        f"\nEach of those modules exists in this tree ({SOURCE_REPO}) and is "
        f"behind the promotion gate. PROMOTE FIRST: tag this tree and run "
        f"ops/promote.sh <tag>, which checks the tag out into {repo} and smoke-"
        f"tests it -- then re-run this patcher. Nothing about the patch itself "
        f"changes; only the tree it will run against does.",
        file=sys.stderr)
    return EXIT_MISSING_MODULE


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

    # --apply ONLY, and BEFORE the running-session check: a session is over in
    # an hour, but a tree that has not been promoted stays wrong until someone
    # promotes it, so that is the refusal a human should hear about first.
    rc = check_target_tree_has_imports(target, src, out)
    if rc:
        return rc

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
