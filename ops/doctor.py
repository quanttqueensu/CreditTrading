"""Is this machine actually able to run the books unattended?

    python3 -m ops.doctor              # full check
    python3 -m ops.doctor --quick      # skip the broker probe

WHY
---
Every failure this system has had was silent, and each one was invisible to the
guards that existed at the time:

  2026-07-31  launchd could not read the repo (TCC). Exit 126, no log.
  2026-08-01  TWS down for 21 consecutive sessions. Preflight blocked
              correctly every time; nobody was reading preflight.
  2026-08-31  the repo moved. `REPO` in launch_job.py still pointed at the old
              path, which `mkdir(parents=True)` then silently RECREATED.
  2026-09-01  four plists still carried WorkingDirectory=<old path>. launchd
              refused to spawn them (EX_CONFIG 78) — no process, no log, no
              heartbeat, no alert. One of the four was the WATCHDOG, so the
              job whose entire purpose is reporting stopped jobs was killed by
              the same fault and could not report itself.

The pattern is always the same: a guard that lives *inside* a job cannot catch
a job that never starts, and a guard that shares a broken assumption with the
thing it guards is not a guard. So this runs OUTSIDE all of them, checks the
plumbing rather than the strategy, and is meant to be run by the watchdog every
day and by a human after any move, upgrade or reinstall.

It changes nothing. FAIL means unattended operation is broken right now; WARN
means it will break later or you will not hear about it when it does.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LAUNCH_JOB = Path.home() / "Library/Application Support/quantt/launch_job.py"
AGENTS = Path.home() / "Library/LaunchAgents"
JOBS = ["cef", "cef_pm", "benchmarks", "phase0", "collect",
        "watchdog", "weekly", "backup"]

# Exit codes that are NOT a failure for a given job, and what they mean.
#
# `backup` was missing from JOBS entirely until 2026-09-10, so the job whose
# whole purpose is to replace git history as the ledgers' off-machine copy --
# and which the untracking is explicitly gated on -- had been reporting
# `last exit 1` since it was scheduled, with nothing anywhere to say so.
#
# It is added with a tolerated code rather than plainly, because plainly would
# have rebuilt the promotion deadlock in a new place: `promote.sh` rolls back on
# ANY non-zero doctor, and `ops/backup_state.sh` exits 2 for "archive written,
# but a file it wanted was unreadable" -- in practice the borrow panel, on the
# far side of the launchd TCC boundary. A FAIL there would block every promotion
# over a file that has nothing to do with what a checkout can destroy, which is
# exactly the class of failure that sank the 11:36 promotion on 2026-09-10.
# WARN is the honest level: the ledgers ARE in the archive, and something else
# is not.
# A non-zero exit here is reported but NEVER escalated to FAIL, per job.
JOB_NEVER_FAILS = {
    "backup": ("the nightly state archive failed, so the ledgers have no "
               "off-machine copy tonight. This does NOT stop the book trading, "
               "which is why it is a WARN — but it is the prerequisite for "
               "untracking the live ledgers, and that must not proceed while "
               "this is non-zero"),
}
# Codes that carry a specific meaning worth printing instead of the generic one.
JOB_CODE_MEANING = {
    ("backup", "2"): "archive written but INCOMPLETE — the ledgers are in it, "
                     "something under data/ was not (launchd TCC boundary)",
    ("backup", "1"): "NO archive was written",
}

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, name, msg, fix=""):
        self.rows.append((level, name, msg, fix))

    def render(self):
        w = max((len(n) for _, n, _, _ in self.rows), default=10)
        for level, name, msg, _ in self.rows:
            print(f"  [{level}] {name:<{w}}  {msg}")
        fails = [r for r in self.rows if r[0] == FAIL]
        warns = [r for r in self.rows if r[0] == WARN]
        print()
        if fails:
            print("UNATTENDED OPERATION IS BROKEN:")
            for _, n, m, fix in fails:
                print(f"  - {n}: {m}")
                if fix:
                    print(f"      fix: {fix}")
        if warns:
            print("WILL BREAK LATER, OR YOU WILL NOT HEAR ABOUT IT:")
            for _, n, m, fix in warns:
                print(f"  - {n}: {m}")
                if fix:
                    print(f"      fix: {fix}")
        if not fails and not warns:
            print("All checks pass. The books can run unattended.")
        return 1 if fails else 0


def _plist_path(job):
    for cand in (AGENTS / f"com.quantt.{job}.daily.plist",
                 AGENTS / f"com.quantt.{job}.plist"):
        if cand.exists():
            return cand
    return None


def check_entrypoint(r):
    """The launchd entry point, and the REPO it resolves."""
    if not LAUNCH_JOB.exists():
        r.add(FAIL, "entrypoint", f"missing {LAUNCH_JOB}")
        return None
    repo = None
    for line in LAUNCH_JOB.read_text().splitlines():
        if line.startswith("REPO = Path("):
            repo = Path(line.split('"')[1])
            break
    if repo is None:
        r.add(WARN, "entrypoint", "could not parse REPO from launch_job.py")
        return None
    if not (repo / "ops").is_dir():
        r.add(FAIL, "repo-path", f"REPO={repo} has no ops/ — nothing will run",
              f"edit REPO in {LAUNCH_JOB}")
    elif repo.resolve() != REPO_ROOT.resolve():
        r.add(FAIL, "repo-path",
              f"REPO={repo} is not this repo ({REPO_ROOT}) — the scheduler is "
              f"driving a different checkout",
              f"edit REPO in {LAUNCH_JOB}")
    else:
        r.add(PASS, "repo-path", f"{repo}")
    return repo


def check_plists(r):
    """The 2026-09-01 fault: a stale WorkingDirectory stops launchd spawning."""
    for job in JOBS:
        p = _plist_path(job)
        if p is None:
            r.add(WARN, f"plist:{job}", "no plist installed")
            continue
        try:
            d = plistlib.load(open(p, "rb"))
        except Exception as exc:
            r.add(FAIL, f"plist:{job}", f"unreadable: {exc!r}")
            continue
        wd = d.get("WorkingDirectory")
        if wd and not Path(wd).is_dir():
            r.add(FAIL, f"plist:{job}",
                  f"WorkingDirectory={wd} does not exist — launchd will refuse "
                  f"to spawn this job (EX_CONFIG 78), silently",
                  f"remove the WorkingDirectory key from {p.name}, then reload it")
            continue
        args = d.get("ProgramArguments") or []
        if args and not Path(args[0]).exists():
            r.add(FAIL, f"plist:{job}", f"interpreter {args[0]} does not exist")
            continue
        prog = [a for a in args[1:] if a.endswith(".py")]
        if prog and not Path(prog[0]).exists():
            r.add(FAIL, f"plist:{job}", f"script {prog[0]} does not exist")
            continue
        r.add(PASS, f"plist:{job}", "paths resolve")


def check_launchd(r):
    """Loaded, and what did each last exit with?"""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception as exc:
        r.add(WARN, "launchd", f"could not query: {exc!r}")
        return
    loaded = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith("com.quantt."):
            loaded[parts[2]] = parts[1]
    for job in JOBS:
        label = None
        p = _plist_path(job)
        if p:
            label = p.stem
        if label not in loaded:
            r.add(WARN, f"loaded:{job}", "not loaded — it will never fire",
                  f"launchctl bootstrap gui/$(id -u) {p}" if p else "")
            continue
        code = loaded[label]
        if code not in ("0", "-") and job in JOB_NEVER_FAILS:
            meaning = JOB_CODE_MEANING.get((job, code), "")
            r.add(WARN, f"loaded:{job}",
                  f"last exit {code}"
                  + (f" — {meaning}" if meaning else "")
                  + f". {JOB_NEVER_FAILS[job]}")
        elif code not in ("0", "-"):
            hint = (" (EX_CONFIG — almost always a bad path in the plist)"
                    if code == "78" else "")
            r.add(FAIL, f"loaded:{job}", f"last exit {code}{hint}",
                  "fix the plist, then bootout + bootstrap it to reload")
        else:
            r.add(PASS, f"loaded:{job}", "loaded, last exit 0")


def _session_deadline_minutes(job):
    """Minutes from a job's scheduled start to the latest it may still be alive.

    Derived, not written down -- and the derivation had to change on 2026-09-11
    when cef split into two fires. It used to read: cef waits for NAV, so its
    ceiling is `cef.env`'s NAV_DEADLINE minus its plist start, plus an hour of
    slack for the trade and capture phases. That hard-coded "cef is the job
    that waits", which stopped being true. The 08:30 cef session does not wait
    at all -- the pair published the previous evening -- and `cef_pm` at 17:30
    is now the fire that can sit on a NAV poll.

    Left alone the old rule computed 23:30 - 08:30 + 1h = 16 HOURS for the
    morning session: a ceiling so generous that the exact incident this check
    exists for, a session hung all day, would have sailed through it.

    THE RULE, and why it is shaped to survive the transition rather than to be
    flipped by hand. A job can be waiting on NAV only if BOTH of two artefacts
    that actually exist on this machine say so: its env carries a parseable
    NAV_DEADLINE, and its installed plist fires AFTER the 16:00 close. A fire
    before the close cannot be waiting for a NAV that has not been struck yet.
    Nothing here has to be told which schedule is installed -- it reads it --
    so the ceiling is correct on both sides of the change, in either order, and
    correct again if the split is rolled back.

    NAV_DEADLINE deliberately stays in `cef.env` even once the morning fire has
    stopped reading it: `ops/promote.sh` derives the session window it refuses
    inside from that same line, and deleting it would refuse every promotion
    (ops/tests/test_promote_gate.py::..._unparseable).

    A post-close job with an unparseable deadline returns None and the check
    SKIPS rather than guessing. The whole defect class here is a literal that
    stopped matching reality, and a default would rebuild it.
    """
    start = _plist_start_minutes(job)
    if start is None:
        return None
    # Before the close: the session cannot be waiting on today's NAV, so its
    # ceiling is the ordinary one. Two hours is generous for a session whose
    # phases are minutes long.
    if start < 16 * 60:
        return 120
    env = REPO_ROOT / "ops" / "schedule" / f"{job}.env"
    if not env.exists():
        return 120
    raw = ""
    for line in env.read_text().splitlines():
        if line.startswith("NAV_DEADLINE="):
            raw = line.split("=", 1)[1].strip()
    if not raw:
        return 120          # a post-close job that does not wait (benchmarks)
    try:
        hh, mm = (int(x) for x in raw.split(":"))
    except Exception:
        return None         # it DOES wait, and we cannot say until when
    end = hh * 60 + mm
    if end <= start:
        return None
    return (end - start) + 60


def _plist_start_minutes(job):
    """Minutes-past-midnight of a job's StartCalendarInterval, or None."""
    import plistlib
    path = _plist_path(job)
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            d = plistlib.load(fh)
    except Exception:
        return None
    cal = d.get("StartCalendarInterval")
    if isinstance(cal, dict):
        cal = [cal]
    if not cal:
        return None
    return int(cal[0].get("Hour", 0)) * 60 + int(cal[0].get("Minute", 0))


def _pid_age_minutes(pid):
    """Elapsed minutes of a running pid via `ps -o etime=`, or None."""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "etime="],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None
    if not out:
        return None
    days, _, rest = out.partition("-")
    if not rest:
        days, rest = "0", out
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, _sec = parts
    return int(days) * 1440 + h * 60 + m


def check_stuck_sessions(r):
    """A session still alive long after its own deadline is a STUCK session.

    WHY THIS EXISTS (2026-09-11). The 2026-09-10 cef session started 17:15, got
    NAV 0/17 from both sources all evening, and was still alive at 10:32 the
    NEXT DAY -- 17h17m, 0% CPU, no log line for 45 minutes, hung in the borrow
    fetch. It never armed, so nothing was transmitted; what it did was block the
    promotion, block the data refresh, and sit on the CEF book's whole trading
    day while every existing guard read green.

    Nothing could see it, and that is the point of putting the check HERE:

      * `wait_for_nav` checks completeness BEFORE the deadline (deliberately),
        so a poll that sleeps through 23:30 and wakes at 09:46 to find the data
        returns 0 and the session proceeds -- ten hours late, on a stale
        decision. The deadline bounds the WAIT, not the session.
      * `check_launchd` reads a pid as "running", which is what "hung" looks
        like.
      * `run_watchdog` compares heartbeat DATES, so a session that has not
        finished has not written one, and the arithmetic only trips after two
        business days. On the evening it broke it computed `missed = 1` and
        said all clear.

    So this is deliberately not a heartbeat check and not an exit-code check:
    it asks the one question none of those ask -- is a session still running
    that cannot possibly still be doing useful work. FAIL, because unlike the
    backup job this one does stop the book trading: a stuck session holds the
    day and the next one may collide with it.
    """
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception as exc:
        r.add(WARN, "stuck-session", f"could not query launchctl: {exc!r}")
        return
    running = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith("com.quantt.") and parts[0] != "-":
            running[parts[2]] = parts[0]

    for job in ("cef", "phase0", "benchmarks"):
        label = f"com.quantt.{job}.daily"
        pid = running.get(label)
        if pid is None:
            continue
        age = _pid_age_minutes(pid)
        ceiling = _session_deadline_minutes(job)
        if age is None or ceiling is None:
            r.add(WARN, f"stuck:{job}",
                  f"running (pid {pid}) but its age or ceiling could not be "
                  f"derived, so staleness cannot be judged")
            continue
        if age > ceiling:
            r.add(FAIL, f"stuck:{job}",
                  f"pid {pid} has been running {age // 60}h{age % 60:02d}m, past "
                  f"its {ceiling // 60}h{ceiling % 60:02d}m ceiling. It cannot "
                  f"still be doing useful work, it holds the session slot, and "
                  f"the next run may collide with it",
                  f"check the tail of ops/schedule/logs/{job}_*.log, then "
                  f"launchctl kill TERM gui/$(id -u)/{label}")
        else:
            r.add(PASS, f"stuck:{job}",
                  f"running (pid {pid}) {age // 60}h{age % 60:02d}m, within "
                  f"{ceiling // 60}h{ceiling % 60:02d}m")


def check_env_paths(r):
    """BOOK / BOOKS_ROOT in the job envs must exist.

    Only envs belonging to a REAL job are checked. launch_job.py loads
    `ops/schedule/<job>.env` and nothing else, so schedule.env — a leftover
    pointing at a v2 book that was never built — is dead config, not a broken
    dependency. Reporting it as a failure would train the reader to skim past
    this list, which is the failure mode this whole file exists to prevent.
    """
    for env in sorted((REPO_ROOT / "ops" / "schedule").glob("*.env")):
        if env.name.endswith(".bak") or env.stem not in JOBS:
            continue
        bad = []
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in ("BOOK", "BOOKS_ROOT") and not Path(v.strip()).exists():
                bad.append(f"{k.strip()}={v.strip()}")
        if bad:
            r.add(FAIL, f"env:{env.stem}", "; ".join(bad) + " does not exist",
                  f"correct the paths in {env}")
        else:
            r.add(PASS, f"env:{env.stem}", "book paths resolve")


def check_broker(r, quick=False):
    if quick:
        r.add(WARN, "broker", "skipped (--quick)")
        return
    try:
        from src.deploy.broker.ibkr import IBKRConfig
        cfg = IBKRConfig.from_env()
    except Exception as exc:
        r.add(FAIL, "broker", f"cannot read config: {exc!r}")
        return
    try:
        from ops.switch_broker import _probe
        res = _probe(cfg.host, cfg.port)
    except Exception as exc:
        r.add(FAIL, "broker", f"probe failed: {exc!r}")
        return
    if not res.get("ok"):
        r.add(FAIL, "broker",
              f"{cfg.host}:{cfg.port} does not answer the API "
              f"({res.get('error')}) — no book can trade",
              "start IB Gateway (and IBC, so it logs itself back in)")
        return
    r.add(PASS, "broker",
          f"{cfg.host}:{cfg.port} account={res['accounts']} "
          f"{len(res['positions'])} position(s)")


def check_ibc(r):
    """Gateway alone is not unattended — something must answer the daily login."""
    # Match on DISTINCTIVE launcher names only. A bare "ibc" substring test
    # matches almost anything -- including this process's own command line when
    # the check is run from a one-liner -- and produced a false PASS on
    # 2026-09-01, i.e. the check reported the gateway was supervised when no
    # IBC existed at all. A check that can pass while the thing is absent is
    # worse than no check.
    running = False
    try:
        out = subprocess.run(["ps", "axo", "pid=,command="], capture_output=True,
                             text=True, timeout=20).stdout
        me = str(os.getpid())
        for line in out.splitlines():
            line = line.strip()
            pid, _, cmd = line.partition(" ")
            if pid == me:
                continue                      # never match ourselves
            low = cmd.lower()
            if any(tok in low for tok in
                   ("ibcstart", "gatewaystart", "ibcontroller", "ibc.jar",
                    "ibcalpha")):
                running = True
                break
    except Exception:
        pass
    ini = Path.home() / "ibc" / "config.ini"
    installed = (Path.home() / "ibc" / "IBC.jar").exists()
    if not installed:
        r.add(FAIL, "ibc",
              "IBC is not installed. IB Gateway restarts daily and will sit at "
              "a login prompt with nothing to answer it — the book dies "
              "tomorrow exactly as it did on 2026-08-01",
              "see deploy/ibgw/README.md")
        return

    # Installed. Now: is it configured, and is it actually up?
    cfg = {}
    try:
        for line in ini.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except Exception as exc:
        r.add(WARN, "ibc", f"installed but config.ini unreadable: {exc!r}")
        return

    if cfg.get("TradingMode") != "paper":
        # Worth its own FAIL: this repo's specs, cost model and kill rules are
        # all written for the paper account. `live` is IBC's shipped default.
        r.add(FAIL, "ibc-mode",
              f"config.ini TradingMode={cfg.get('TradingMode')!r}, expected "
              f"'paper' — this repo is a paper deployment",
              f"set TradingMode=paper in {ini}")

    if not cfg.get("IbLoginId") or not cfg.get("IbPassword"):
        r.add(FAIL, "ibc",
              "IBC is installed and configured but has NO CREDENTIALS, so it "
              "cannot log the gateway in. Everything else is ready",
              f"set IbLoginId and IbPassword in {ini} (chmod 600), then: "
              f"launchctl bootstrap gui/$(id -u) "
              f"~/Library/LaunchAgents/com.quantt.ibgateway.plist")
        return

    if running:
        r.add(PASS, "ibc", "IBC is managing the gateway")
    else:
        r.add(FAIL, "ibc",
              "IBC is installed and has credentials but is not running — the "
              "gateway will stop at the login prompt after its daily restart",
              "launchctl bootstrap gui/$(id -u) "
              "~/Library/LaunchAgents/com.quantt.ibgateway.plist")


# ---------------------------------------------------------------------------
# Sleep.
#
# WHY THIS CHECK MEASURES INSTEAD OF LECTURING
# --------------------------------------------
# The old version of this check read `pmset -g sched`, and if no repeating wake
# was scheduled it printed a fixed sentence about closed lids. It said exactly
# the same thing on a machine plugged in with the lid open (which runs the
# session fine) as on a machine on battery at 20% with the lid shut (which
# loses it). A guard that cannot tell those two apart is a lecture, not a
# check, and on 2026-09-10 it stood at WARN while the session died.
#
# WHAT ACTUALLY HAPPENED, 2026-09-10 (all times local, from `pmset -g log`)
#
#   17:15:05  cef session starts, polls for the day's NAV every 900s
#   19:45:30  last poll before the gap
#   19:51:36  "Entering Sleep state due to 'Clamshell Sleep' ... Using Batt
#             (Charge:20%)"           <- lid shut, charger off. Session frozen.
#   21:26:57  DarkWake from an unrelated rtc/SleepService timer
#   21:27:24  ONE poll gets through
#   21:28:54  "Sleep Service Back to Sleep"    <- awake for 117 seconds
#   09:46:26  next poll, the following morning
#
# That 21:26:57 wake is the most useful thing in the log, because it is the
# accidental experiment for the remedy everyone reaches for first. A wake DID
# fire during the session window. It bought 117 seconds and one poll, because
# nothing held an assertion that survives on battery, so the machine went
# straight back to sleep. `sudo pmset repeat wakeorpoweron` alone would have
# reproduced exactly this. A wake is worth having, but it is not the fix, and
# this check must not report PASS on the strength of it.
#
# THE TWO REASONS THE NO-SUDO SUBSTITUTE DID NOT HOLD
#   1. `caffeinate -s` is documented "valid only when system is running on AC
#      power" (man caffeinate). At 19:51 this machine was on battery, so the
#      com.quantt.awake job was holding nothing at all.
#   2. A closed lid beats it even on AC. At 2026-09-10 00:46:31 clamshell sleep
#      fired while a caffeinate PreventSystemSleep assertion had been held for
#      10h54m, on AC at 100%. Only `sudo pmset disablesleep 1` or an open lid
#      defeats clamshell.
#
# So the machine survives the evening only if BOTH hold: it is on AC (or the
# assertion in force is one that works on battery), AND the lid is open (or
# sleep is disabled outright). The session runs 17:15 until its NAV deadline --
# observed NAV arrivals 21:45 on 2026-09-09 and 22:43 on 2026-09-08 -- so this
# is six hours after the point at which a laptop normally gets shut.
#
# WHY THIS NEVER RETURNS FAIL
# ---------------------------
# `ops/promote.sh` rolls back on ANY non-zero `ops.doctor`, and power source,
# lid angle and wake schedule are MACHINE state that a `git checkout` cannot
# change. A FAIL here would refuse every promotion for as long as the lid was
# shut -- including the promotion carrying the fix for whatever else is broken.
# That is the same layer-3 deadlock `JOB_NEVER_FAILS` exists to prevent for
# `backup`, and the same severity argument applies: a sleeping Mac does not
# make the code wrong, it makes the box unable to run it. See
# ops/tests/test_doctor_sleep.py, which pins this.


def _cmd(argv):
    """stdout of `argv`, or None if it cannot be run. Never raises.

    Doctor is called by the watchdog, and a check that raises takes down the
    one job that reports every other job (the 2026-09-01 fault). Every probe
    below is allowed to be unavailable; unavailable is reported as unknown and
    never silently treated as healthy.
    """
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    return out.stdout


def on_battery():
    """True on battery, False on AC, None if `pmset -g ps` is unreadable.

    This is the condition that voids `caffeinate -s` entirely (man caffeinate:
    "valid only when system is running on AC power"), which is why it is not
    folded into a general 'power looks fine' boolean.
    """
    out = _cmd(["pmset", "-g", "ps"])
    if out is None:
        return None
    head = out.lower()
    if "drawing from 'ac power'" in head:
        return False
    if "drawing from 'battery power'" in head:
        return True
    return None


def lid_closed():
    """True if the clamshell is shut, False if open, None if unreadable.

    Clamshell sleep ignores caffeinate assertions, so this is read directly
    from IOKit rather than inferred from anything pmset reports.
    """
    out = _cmd(["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"])
    if out is None:
        return None
    for line in out.splitlines():
        if "AppleClamshellState" in line:
            return "Yes" in line
    return None       # no clamshell key: a desktop, or IOKit said nothing


def clamshell_causes_sleep():
    """True if shutting the lid will actually sleep this machine, else False.
    None if unreadable or the key is absent (a desktop).

    ASK THE SYSTEM, DO NOT INFER FROM THE LID ANGLE. `AppleClamshellState` says
    only whether the lid is shut; the neighbouring `AppleClamshellCausesSleep`
    is macOS's own answer to the question this check actually asks, and the two
    routinely disagree. Clamshell MODE -- lid shut, machine awake -- is
    supported on AC with an external display and an input device, and is a
    normal way to run a laptop.

    MEASURED 2026-09-11 on this machine (MacBook Air, Mac14,2, external 1080p
    display, AC at 96%):

        "AppleClamshellCausesSleep" = No
        "AppleClamshellState"       = Yes

    The first version of this check read only the second line and reported
    "THE EVENING SESSION IS UNPROTECTED" in the desk's ordinary operating
    configuration. That is the precise failure the rewrite was meant to end --
    the old check "said the same words on a plugged-in machine with the lid
    open" -- rebuilt one key over. A guard that cries wolf in the normal case
    gets read past, and then it is worth less than nothing.

    It does NOT excuse the closed lid in general: on BATTERY clamshell mode is
    not supported, this flips to Yes, and the lid sleeps the machine. That is
    what happened at 19:51:36 on 2026-09-10 -- `pmset -g log` recorded
    "Clamshell Sleep ... Using Batt (Charge:20%)". The lid was a proximate
    cause; losing AC was the real one.
    """
    out = _cmd(["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"])
    if out is None:
        return None
    for line in out.splitlines():
        if "AppleClamshellCausesSleep" in line:
            return "Yes" in line
    return None


def sleep_disabled():
    """True if `pmset disablesleep 1` is in force -- the only setting that
    defeats clamshell sleep. None if unreadable."""
    out = _cmd(["pmset", "-g"])
    if out is None:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "disablesleep":
            return parts[1] == "1"
    return False      # pmset omits the key entirely when it is 0


def awake_window():
    """(start, end) as 'HH:MM' for com.quantt.awake, or None.

    Derived from the plist -- the StartCalendarInterval hour/minute plus the
    `-t` seconds handed to caffeinate -- rather than written down here. The
    sentence this replaces said "09:00-20:00" while the job had been running
    `-t 54000` (15h, so 09:00-00:00) for as long as it had existed. A window
    quoted in prose goes stale the first time the plist is edited; a window
    computed from the plist cannot.
    """
    path = AGENTS / "com.quantt.awake.plist"
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            plist = plistlib.load(fh)
        argv = [str(a) for a in plist.get("ProgramArguments", [])]
        secs = int(argv[argv.index("-t") + 1])
        cal = plist.get("StartCalendarInterval") or []
        if isinstance(cal, dict):
            cal = [cal]
        start = min((int(d.get("Hour", 0)) * 60 + int(d.get("Minute", 0)))
                    for d in cal)
    except Exception:
        return None
    end = (start + secs // 60) % (24 * 60)
    return (f"{start // 60:02d}:{start % 60:02d}",
            f"{end // 60:02d}:{end % 60:02d}")


def check_sleep(r):
    sched = _cmd(["pmset", "-g", "sched"])
    if sched is None:
        r.add(WARN, "sleep", "could not read pmset")
        return
    wake = "wakeorpoweron" in sched.lower() or "poweron" in sched.lower()

    batt, lid, disabled = on_battery(), lid_closed(), sleep_disabled()
    win = awake_window()
    held = "com.quantt.awake" in (_cmd(["launchctl", "list"]) or "")

    # Each entry is a condition that ENDS the evening session on its own.
    blockers = []
    if batt is True:
        blockers.append("on BATTERY, which voids `caffeinate -s` entirely "
                        "(it is valid only on AC) and idle-sleeps in 1 minute")
    causes = clamshell_causes_sleep()
    if lid is True and causes is not False and not disabled:
        # `causes is not False` rather than `causes is True`: an unreadable key
        # is treated as dangerous, because the cost of a false alarm is a line
        # in a report and the cost of a false all-clear is a lost session.
        detail = ("and macOS says it WILL sleep the machine"
                  if causes is True else
                  "and whether that sleeps the machine could not be read")
        blockers.append(f"lid is CLOSED {detail}, with disablesleep off -- "
                        f"clamshell sleep wins over any caffeinate assertion")
    if batt is None or lid is None:
        blockers.append("could not read power source or lid state")

    # An unparseable plist is NOT the same as an absent one, and saying
    # nothing about it is the silent fallback this repo keeps being bitten by.
    # Demonstrated while writing this check: adding a comment containing `--`
    # to the awake plist left `plutil -lint` saying OK and made plistlib
    # (expat) refuse the file, so the window silently became "unknown". If the
    # job is loaded, its plist must be readable; if it is not, say so.
    plist_there = (AGENTS / "com.quantt.awake.plist").exists()
    if win:
        window = f" ({win[0]}-{win[1]})"
    elif plist_there:
        window = " (plist present but UNREADABLE, so its window is unknown)"
    else:
        window = " (no plist)"
    holding = (f"com.quantt.awake is loaded{window}" if held
               else "com.quantt.awake is NOT loaded")
    if lid is True and causes is False:
        # Worth naming, because it is the configuration the desk actually runs
        # in and a reader who knows the lid is shut will otherwise distrust a
        # PASS. It also names the thing that would change the answer.
        holding += ("; lid is shut but macOS reports it will not sleep "
                    "(clamshell mode -- external display on AC). Losing AC "
                    "flips that, which is how 2026-09-10 was lost")

    if not blockers:
        if wake:
            r.add(PASS, "sleep",
                  f"on AC, lid usable, repeating wake scheduled; {holding}")
        else:
            r.add(PASS, "sleep",
                  f"on AC and the lid will not sleep it; {holding}. No "
                  "repeating wake, so nothing recovers it if it does sleep",
                  "sudo pmset repeat wakeorpoweron MTWRF 17:00:00")
        return

    # A scheduled wake is explicitly NOT an excuse here: 2026-09-10 21:26:57
    # is the measurement that says a wake without a valid assertion is worth
    # 117 seconds.
    recovery = ("a repeating wake is scheduled, but 2026-09-10 21:26:57 "
                "measured a wake without a holding assertion at 117 seconds "
                "and one poll" if wake else
                "Nothing brings it back either: no repeating wake is scheduled")
    r.add(WARN, "sleep",
          "THE EVENING SESSION IS UNPROTECTED, which is how 2026-09-10 was "
          "lost: " + "; ".join(blockers)
          + f". {recovery}. {holding}",
          "plug in the charger and open the lid, or: sudo pmset -a disablesleep 1 "
          "&& sudo pmset -b sleep 0 && sudo pmset repeat wakeorpoweron MTWRF 17:00:00")


def check_heartbeats(r):
    try:
        import pandas as pd
        from ops import halt as halt_mod
        sys.path.insert(0, str(REPO_ROOT / "ops" / "schedule"))
        today = pd.Timestamp.today().normalize()
    except Exception as exc:
        r.add(WARN, "heartbeat", f"could not evaluate: {exc!r}")
        return
    for job in ("cef", "benchmarks", "phase0", "collect"):
        beat = halt_mod.last_beat(job)
        if beat is None:
            r.add(WARN, f"beat:{job}", "has never reported")
            continue
        missed = len(pd.bdate_range(pd.Timestamp(beat["date"]), today)) - 1
        if missed > 1:
            r.add(FAIL, f"beat:{job}",
                  f"last ran {beat['date']} ({beat['status']}), "
                  f"{missed} session(s) ago")
        else:
            r.add(PASS, f"beat:{job}", f"{beat['date']} ({beat['status']})")


def check_alerts(r):
    env = REPO_ROOT / "config" / ".env"
    txt = env.read_text() if env.exists() else ""
    have = all(f"{k}=" in txt and txt.split(f"{k}=", 1)[1].splitlines()[0].strip()
               for k in ("ALERT_SMTP_USER", "ALERT_SMTP_PASS"))
    if have:
        r.add(PASS, "alerts", "email configured")
    else:
        r.add(WARN, "alerts",
              "email not configured — alerts reach only the macOS banner and "
              "the speech synthesiser, which is nobody when you are away from "
              "the machine",
              "add ALERT_SMTP_USER and ALERT_SMTP_PASS (a Google App Password) "
              "to config/.env")


def failures(quick=False) -> list[str]:
    """[(name: message)] for every FAIL. Used by the watchdog.

    Silent, and never raises: a doctor that crashes the watchdog would take
    down the one job that reports everything else, which is precisely the
    2026-09-01 fault (the watchdog died of the same bad path it should have
    reported).
    """
    r = Report()
    for fn, args in ((check_entrypoint, ()), (check_plists, ()),
                     (check_launchd, ()), (check_stuck_sessions, ()),
                     (check_env_paths, ()),
                     (check_broker, (quick,)), (check_ibc, ()),
                     (check_sleep, ()), (check_heartbeats, ()),
                     (check_alerts, ()), (check_panels, ())):
        try:
            fn(r, *args)
        except Exception as exc:
            r.add(WARN, fn.__name__, f"check raised {exc!r}")
    return [f"{n}: {m}" for lvl, n, m, _ in r.rows if lvl == FAIL]


# ---------------------------------------------------------------------------
# Panel staleness.
#
# WHY THIS IS A DOCTOR CHECK AND NOT A PREFLIGHT CHECK
# ----------------------------------------------------
# Preflight already gates the two panels the SESSION cannot trade without --
# price and NAV -- and refuses to arm on a stale pair, because a stale NAV is a
# blind signal, not a cheap fund. That is the right behaviour for the order
# path.
#
# This is the other half: the panels that RESEARCH depends on, which no session
# ever blocks on. Those rot quietly. Measured 2026-09-10, with the price panel
# current to the previous session:
#
#     cef_distributions.parquet   48 days behind   feeds the return convention
#                                                  and the ex-date calendar
#     etf_ohlc.parquet            43 days behind   feeds every ETF proxy
#     etf_daily.parquet           52 days behind
#
# Nothing announced any of that. A script joining a 48-day-old distribution
# panel to a current price panel does not fail; it silently applies the wrong
# correction, or none, and returns a number.
#
# "A stale input that fails loudly is an inconvenience; a stale input that
# fails silently is a wrong number."
#
# WARN rather than FAIL on purpose: a stale research panel does not stop the
# book trading tonight, and doctor's FAIL level means "unattended operation is
# broken right now". Overloading it would train the operator to ignore it.
# ---------------------------------------------------------------------------

# (path, max sessions behind the price panel before it is worth saying, why)
PANELS = [
    ("data/cef/cef_prices.parquet", 3,
     "the signal's own price panel"),
    ("data/cef/cef_nav.parquet", 3,
     "the signal's own NAV panel"),
    ("data/cef/cef_distributions.parquet", 21,
     "total-return convention (W4) and the ex-date calendar (W9)"),
    ("data/rv/etf_ohlc.parquet", 21,
     "ETF proxies in W10/W13 and gamma/G3's variance work"),
    ("data/cef/cef_borrow.csv", 10,
     "borrow cost and availability; drives short-side sizing"),
    # Fund attributes change slowly, so the limit is a quarter rather than a
    # fortnight -- but "slowly" is not "never", and an undated snapshot silently
    # applying today's attributes to 2005 is the look-ahead this flags.
    ("data/cef/cef_facts.csv", 63,
     "per-fund attributes; a SNAPSHOT, never join it to history un-dated"),
]

# Undated snapshots that LOOK like fact tables. Joining one to a historical
# panel is a look-ahead error with no error message.
UNDATED = [
    ("data/cef/cef_facts.csv", "fetched_at",
     "a single undated yfinance snapshot: 13 of 46 columns are 100% null and "
     "sector/industry are constant across all rows. Anything joining it to a "
     "27-year panel is committing look-ahead"),
]


# A date this project could plausibly hold. Outside this window the column is
# not dates, whatever it is called.
_PLAUSIBLE = (dt.date(1985, 1, 1), dt.date.today() + dt.timedelta(days=370))


def _panel_last_date(path):
    """Newest plausible date in a panel, or None.

    Never raises -- a monitor that dies on a malformed input is the failure
    mode it exists to catch.

    The plausibility window is not decoration. `pd.to_datetime` reads a bare
    integer as NANOSECONDS SINCE EPOCH, so a column named `date` holding 3
    returns 1970-01-01, and one holding 20260909 returns 1970 as well. Without
    this guard the check would confidently report a panel as ~20,000 sessions
    stale, or -- for the right integer -- as current. That is precisely the
    class of silent wrong answer this check exists to catch, so it must not
    commit it itself. Caught by ops/tests/test_doctor_panels.py.
    """
    try:
        import pandas as pd
        if path.suffix == ".csv":
            df = pd.read_csv(path)
        else:
            df = pd.read_parquet(path)
        # `fetched_at` counts: a snapshot's stamp is its date. Without this a
        # file stamped by the fetcher would still read as undated.
        cols = [c for c in df.columns
                if "date" in str(c).lower() or "fetched" in str(c).lower()]
        # A stamp beats a content date -- it says when we LEARNED the row, which
        # is what staleness means for a snapshot.
        cols.sort(key=lambda c: 0 if "fetched" in str(c).lower() else 1)
        for col in cols:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if parsed.empty:
                continue
            last = parsed.max()
            if _PLAUSIBLE[0] <= last.date() <= _PLAUSIBLE[1]:
                return last
        return None
    except Exception:
        return None


def check_panels(r):
    """Are the panels research depends on current enough to trust?"""
    try:
        import pandas as pd
    except ImportError:
        r.add(WARN, "panels", "pandas unavailable; cannot check staleness")
        return

    ref_path = REPO_ROOT / "data/cef/cef_prices.parquet"
    ref = _panel_last_date(ref_path)
    if ref is None:
        r.add(WARN, "panels", "cannot read the price panel; staleness unknown")
        return

    try:
        sys.path.insert(0, str(REPO_ROOT / "ops/schedule"))
        import nyse_calendar as cal
    except Exception:
        cal = None

    def sessions_between(a, b):
        """NYSE sessions strictly after a, through b. Calendar days if the
        calendar module is unavailable -- stated, not silently substituted."""
        if cal is None:
            return (b - a).days, "cal-days"
        n, d = 0, a
        while d < b and n < 400:
            d += dt.timedelta(days=1)
            if cal.is_trading_day(d):
                n += 1
        return n, "sessions"

    for rel, limit, why in PANELS:
        path = REPO_ROOT / rel
        name = f"panel:{Path(rel).stem}"
        if not path.exists():
            r.add(WARN, name, f"missing — {why}")
            continue
        last = _panel_last_date(path)
        if last is None:
            r.add(WARN, name,
                  f"no date column; freshness unknowable — {why}",
                  fix="add a date or fetched_at column to the fetcher's output")
            continue
        n, unit = sessions_between(last.date(), ref.date())
        if n > limit:
            r.add(WARN, name,
                  f"{n} {unit} behind the price panel "
                  f"(ends {last.date()}, prices end {ref.date()}) — {why}",
                  fix=f"refresh it; any note quoting it must state {last.date()}")
        else:
            r.add(PASS, name, f"{n} {unit} behind prices (ends {last.date()})")

    for rel, wanted, why in UNDATED:
        path = REPO_ROOT / rel
        name = f"panel:{Path(rel).stem}"
        if not path.exists():
            continue
        try:
            head = path.read_text(errors="replace").splitlines()[0]
        except Exception:
            continue
        if wanted not in head:
            r.add(WARN, name, f"has no `{wanted}` column — {why}",
                  fix=f"add {wanted} in the fetcher, or supersede the file")
        else:
            r.add(PASS, name, f"carries `{wanted}`")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true",
                    help="skip the broker probe")
    a = ap.parse_args(argv)

    print(f"[doctor] repo   {REPO_ROOT}")
    print(f"[doctor] python {sys.executable}")
    print()
    r = Report()
    check_entrypoint(r)
    check_plists(r)
    check_launchd(r)
    check_stuck_sessions(r)
    check_env_paths(r)
    check_broker(r, quick=a.quick)
    check_ibc(r)
    check_sleep(r)
    check_heartbeats(r)
    check_alerts(r)
    check_panels(r)
    return r.render()


if __name__ == "__main__":
    sys.exit(main())
