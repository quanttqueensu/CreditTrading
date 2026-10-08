"""Install (or update) the CEF book on the prod VM at a release tag, as systemd units.

    qi() { sudo env PYTHONPATH=/home/quantt/prod/quantt-alpaca \\
             /home/quantt/venv/bin/python -B -P -m quantt.deploy.install_vm "$@"; }
    qi --tag T --vault V --seed-from DIR          # dry run
    qi --tag T --vault V --seed-from DIR --apply
    qi --tag T --vault V --apply --enable

The installer is imported from the prod clone through PYTHONPATH, because
/home/quantt is mode 750 and the admin user cannot `cd` into it
(docs/RUNBOOK.md section 8.3). `-P` keeps the caller's working directory
off sys.path, so root never imports a module planted there.

WHY THIS EXISTS
---------------
From 2026-09-30 to 10-07 the laptop missed the send on 3 of 6 trading days,
because it was asleep or offline (verify.log, 10-02, 10-05 and 10-06). On
2026-10-07 the team lead moved prod to a cloud VM: Azure for Students, Ubuntu
24.04. This module is install_prod's twin for Linux. The rule is the same: prod
is THIS REPOSITORY AT A TAG AND NOTHING ELSE. So are the jobs, the commands, the
environment and the times; only the scheduler differs (systemd timers, not
launchd). It is a new module rather than an edit to install_prod (RUNBOOK section 8).
It IMPORTS install_prod's JOBS, seed lists, expected_env and timezone reader, so
the two schedulers cannot drift apart without a test failing.

WHERE IT RUNS, AND AS WHOM
--------------------------
On the VM, as root, because it writes /etc/systemd/system and runs systemctl.
It runs with the venv interpreter, the prod clone on PYTHONPATH, and `-B`. Without `-B`,
root would write __pycache__ into the quantt user's tree, leaving root-owned
files there. Every git command runs as the `quantt` user
(`runuser -u quantt --`): git refuses a repository another user owns
("dubious ownership"), and prod's files must stay quantt's. The clone itself is
made once, by quantt/deploy/vm/bootstrap.sh.

TEMPLATES AT THE TAG
--------------------
The units are rendered from templates read AT THE TAG (`git show`). Each is
then parsed and checked, key by key, against what this module expects:

  * the command and environment from install_prod.expected_env;
  * the schedule from `oncalendar(job.schedule)`.

An installer older than the release refuses a release whose units changed,
rather than installing its own idea of them. In that case, check out the tag
as quantt and run the installer again.

DRY RUN BY DEFAULT
------------------
Without `--apply`, it runs every check and prints the steps and the rendered
units. The one write it makes is `git fetch --tags` into the clone's .git,
which changes no checked-out file, no unit and no state. `--apply` writes the
units and runs `systemctl daemon-reload`, after which systemd runs the new
definitions. So a re-install without `--armed` disarms at once. That differs
from launchd, where a written plist is ignored until it is reloaded: here the
reload is part of every apply. `--enable` (only with `--apply`) also enables and
starts the timers and the key service. Enabling is a separate act on purpose,
because enabled timers are what trade.

Arming takes two things: `--armed` (DRY_RUN=0 in the units) and AUTO_ARMED in
the state dir (docs/RUNNER.md gate 2). AUTO_ARMED is the team lead's act; this
module never writes it.

THE TIMERS ARE STOPPED FOR THE RUN (release-check NO-GO, 2026-10-08)
--------------------------------------------------------------------
Checking `is-active` at the right moments is not enough. A 15:52 firing that
lands between the last look and daemon-reload starts the OLD unit, say
DRY_RUN=0, and with AUTO_ARMED it sends, while a disarm run would report
DRY_RUN=1 loaded. So `--apply` runs in this order:

  1. stop every quantt-cef timer that is running;
  2. check that no job is running or QUEUED. A queued start reads `is-active`
     inactive, so the check uses ActiveState and Job (measured, see the parser
     comment). The key service `activating` also counts;
  3. checkout, write, daemon-reload, confirm_loaded;
  4. check again. A job found now exits 3 (EXIT_JOB_DURING_INSTALL), naming
     the job, its MainPID and the DRY_RUN it started with, read from /proc and
     never guessed;
  5. restart quantt-secret.service and confirm it is active and the key file is
     a 0600 file owned by quantt (stat only). A oneshot with RemainAfterExit is
     otherwise never re-run, so a changed --vault or rotated keys would leave
     the old keys in /run/quantt while the run reported success (release-check
     #2). It is done here, while no job can run, because the restart removes and
     re-creates /run/quantt;
  6. start every ENABLED timer, plus any that was running, or enable them all
     with `--enable`, then READ BACK that each is active, and refuse if one is
     not. The end state is set by enablement, not by what happened to be
     running. Otherwise a re-run after a refusal that had stopped the timers
     would exit 0 with all three still stopped (release-check #2).

Restarting DOES replay a slot missed while the timers were stopped. Measured
on the VM, 2026-10-08 [V]: an ENABLED Persistent=false timer, stopped and
restarted within one boot across a missed slot, fires at once on the restart.
(This corrects an earlier note in this file, which said restarting did not
replay; parser comment (b).) So an install that spans 15:52/15:55 (12:52/12:55
on an early close) would replay the send slot into a late, partial send. To
prevent that, the installer refuses at planning on a weekday inside 15:30-16:00
or 12:30-13:00 ET (PLAN_REFUSE_RANGES_ET, a superset of the runner's
LATE_LOCAL_RANGES). It refuses the timer restart inside 15:52-16:00 or
12:52-13:00 (RESTART_REFUSE_RANGES_ET, the send window to the close), and checks
the clock again before restarting the timers, leaving them stopped if it is
now inside a window. Other replays are harmless: a replayed :00/:30 session
idles outside its slots, a replayed collect is a collect, a replayed 17:30
verify writes the day's line, and a replayed 22:00 decide decides once
(DECIDED). Any failure after step 1, a refusal or an unexpected
exception, reads the timers back and reports any that are STOPPED: nothing
trades until the installer is re-run or the timers are started. Planning also
refuses a venv built from a requirements.txt other than the tag's
(REQUIREMENTS_RECORD, written by bootstrap.sh).

TIMEZONE: ONE MECHANISM
-----------------------
The timers' OnCalendar lines carry no zone, so systemd reads them as
system-local time. The installer refuses unless /etc/localtime names
America/New_York (bootstrap.sh sets it). There is no `--accept-timezone`: on a
VM the zone is ours to set, so nothing equivalent needs accepting. The runner's
own ET clock gates are the second guard.

SCHEDULE
--------
* `Persistent=false`: a firing missed while the VM was DOWN never runs at boot
  (systemd.timer(5)). Measured on the VM, 2026-10-08 04:43-04:56 UTC [V]: last
  run 04:44:00, then powered off; slots 04:46-04:54 passed while down; boot at
  04:55:07; next run at the regular 04:56:00. A stop and restart WITHIN one
  boot is different: it replays (see THE TIMERS ARE STOPPED FOR THE RUN).
* A firing that passes WHILE ITS SERVICE IS STILL RUNNING is not dropped.
  MEASURED on the VM, 2026-10-07 (Ubuntu 24.04.4, systemd 255.4-1ubuntu8.17): a
  transient timer firing every minute at :00 (AccuracySec=1s, Persistent=false)
  on a 90-second job started the next run the moment the previous one exited.
  The 23:14:00 firing ran at 23:14:30. For this book that means:
    - the 15:52 send polls its orders until each is final (`_poll_final`). That
      usually ends within seconds; in the worst case it runs to 30 s before the
      close (15:59:30 for a 16:00 close);
    - so the 15:55 firing usually lands INSIDE the window, while the send is
      still running or just after, and then idles on STARTED. In the worst case
      it starts after the window, where the date roll idles it;
    - either way the session must idle on STARTED and the Alpaca-clock send
      window.
  The runner's gates are the ONLY guard on that path, not a second one. The
  test that covers the idle is quantt/session/tests/test_run.py::
  test_late_scheduled_decides_once_then_sends_once. `DeferReactivation=`
  (systemd >= 256) would remove the late start, but Ubuntu 24.04 ships 255.
* `AccuracySec=1s`: systemd's default is 1min, and within that window "the
  expiry time will be placed at a host-specific, randomized" position
  (systemd.timer(5)). That would put a 15:52 firing anywhere up to 15:53.

THE KEY FILE
------------
`quantt-secret.service` (quantt.deploy.boot_secrets) writes /run/quantt/alpaca.env
at boot. The job units declare `Wants=` + `After=` on it, deliberately NOT
`Requires=`. systemd.unit(5): a unit with Requires= "will be stopped (or
restarted) if one of the other units is explicitly stopped (or restarted)".
Rotating the keys (`systemctl restart quantt-secret`) during the 15:52 window
would then kill a send mid-batch. A failed fetch would also stop verify from
starting at all, leaving that day with no verify.log line, and silence must
never read as success. With Wants=, a job whose key file is missing fails
loudly in its own log, and verify records FAIL.

"Once per boot" holds only when the fetch SUCCEEDS. A failed key service is
inactive, so every job start pulls it in again through Wants=. That makes it
self-healing (a role assignment made later starts working on the next firing).
The cost is delay: After= holds the job until the fetch ends, up to about 4
minutes per job start when every request times out. That is IMDS 6 x 10 s plus
82 s of backoff, about 142 s, then about 47 s per secret
(azure_keyvault.IMDS_DELAYS, KEYVAULT_DELAYS, TIMEOUT_S). A 4xx refusal ends
the fetch at once.

WHAT IT NEVER DOES
------------------
* Reads a credential. It knows the vault's NAME only.
* Runs anything quantt cannot already change, with one exception, accepted:
  it runs as root FROM the quantt-writable venv and clone. So quantt (or code
  running as quantt) can make root run code at the next install. The impact is
  low, because quantt already holds the keys and runs the book; the gap is
  noted in docs/RUNBOOK.md section 8.
* Imports quantt.session or any broker code.
* Writes a unit not named quantt-*.
* Writes AUTO_ARMED.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import os
import pwd
import re
import shlex
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable
from zoneinfo import ZoneInfo

from quantt.deploy import azure_keyvault as akv
from quantt.deploy import install_prod as ip
from quantt.deploy.install_prod import InstallRefused

BOOK = ip.BOOK
REQUIRED_TZ = ip.REQUIRED_TZ
SERVICE_USER = "quantt"
ORIGIN_URL = "https://github.com/quanttqueensu/CreditTrading.git"
UNITS_DIR = Path("/etc/systemd/system")
UNIT_PREFIX = "quantt-"
TEMPLATE_DIR = "quantt/deploy/templates/systemd"

# RuntimeDirectory=quantt in quantt-secret.service creates /run/quantt; the key
# file lives in it. The two must agree, so both come from here.
RUNTIME_DIR = "quantt"
ENV_FILE = Path("/run") / RUNTIME_DIR / "alpaca.env"
SECRET_UNIT = "quantt-secret.service"
SECRET_PROVIDER = "azure-keyvault"
# Key Vault secret name -> variable in the key file. Two secrets because a vault
# secret name allows only 0-9 a-z A-Z '-' (azure_keyvault.SECRET_RE), and the
# portal's value box is a single line. The variable names are
# quantt.broker.alpaca's (env_names("cef")).
SECRET_MAP = (("alpaca-cef-key-id", "ALPACA_CEF_KEY_ID"),
              ("alpaca-cef-secret-key", "ALPACA_CEF_SECRET_KEY"))

# Session exits that are normal outcomes, not failures (quantt/session/run.py:
# NOTHING_TO_SEND 3, PREVIEW 4, IDLE 5, PLANNED 6, DRY 10). REFUSED 11 and FAIL 20
# stay failures. `test_session_success_exits_match_run_py` re-reads run.py.
SESSION_SUCCESS_EXIT = (3, 4, 5, 6, 10)

# Exit codes: 0 done, 2 refused (nothing unsafe happened), 3 a quantt job ran or
# was queued after the reload, which with the timers stopped should be
# impossible, so the run says so loudly instead of reporting success.
EXIT_JOB_DURING_INSTALL = 3

# One install (or bootstrap) at a time (release-check #5). Without it, a disarm
# run could confirm DRY_RUN=1 from systemd and exit 0 while an armed update,
# already in flight, went on to write DRY_RUN=0 and restart the timers: the
# next slot would send after a confirmed halt (CLAUDE.md order-path rule 4).
# An exclusive, non-blocking flock(2) on a root-owned file in /run/lock (tmpfs,
# so a reboot clears it), taken before ANY planning and held until the process
# exits; bootstrap.sh takes the same lock with `flock -n`.
INSTALL_LOCK = Path("/run/lock/quantt-install.lock")


def acquire_install_lock(path: Path) -> int:
    """Take the install lock or raise InstallRefused naming the holder's pid.
    Returns the fd; closing it (or exiting) releases the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = os.read(fd, 64).decode("utf-8", "replace").strip() or "unknown"
        os.close(fd)
        raise InstallRefused(
            f"another install or bootstrap is running (lock {path}, held by pid "
            f"{holder}). Never run two at once: one could undo the other's disarm. "
            f"Wait for it to finish") from None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd

# Two windows, weekdays, for a 16:00 and a 13:00 (early) close. Release-check #5
# narrowed the restart window, so fewer days are lost for the same safety.
#   PLAN_REFUSE_RANGES_ET: no install STARTS inside these. They are a superset of
#     the runner's LATE_LOCAL_RANGES (15:40/12:40), and start at 15:30/12:30 so a
#     run, whose key fetch can take about 4 minutes, finishes before the send
#     window (docs/RUNBOOK.md 8.6: "start any --apply before 15:30").
#   RESTART_REFUSE_RANGES_ET: the timers are not RESTARTED inside these. They run
#     from the book's send window start (close - window_minutes_before_close[0]
#     = 15:52/12:52) to the close. A restart there replays a missed 15:52/15:55
#     slot into a late, partial send (M1). A restart in 15:30-15:52 can only
#     replay a :00/:30 session (decide or idle) or a :40 collect, never a send.
# Both are MIRRORED, not imported: the installer never imports quantt.session.
# test_the_windows_cover_the_runners_late_ranges_and_the_books_send_window pins
# them to the runner's ranges and to the book's window.
PLAN_REFUSE_RANGES_ET = ((dt.time(15, 30), dt.time(16, 0)), (dt.time(12, 30), dt.time(13, 0)))
RESTART_REFUSE_RANGES_ET = ((dt.time(15, 52), dt.time(16, 0)), (dt.time(12, 52), dt.time(13, 0)))

# sha256 of the requirements.txt the venv was built from, written by bootstrap.sh
# (and by the RUNBOOK 8.6 dependency step) into the venv directory.
REQUIREMENTS_RECORD = ".quantt-requirements.sha256"

# Every rendered value must match this pattern. It excludes the space (which
# would split ExecStart's argv), '%' (a systemd specifier), '$' (variable
# expansion), quotes and backslashes (systemd's own quoting).
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9/_.:@+=-]+$")

# launchd numbers weekdays 0..7 with 0 and 7 both Sunday (`man launchd.plist`).
WEEKDAY_NAMES = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
DAY_ORDER = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class VmJob:
    unit: str                  # e.g. quantt-cef-session
    job: ip.Job                # the launchd job it reproduces
    success_exit: tuple = ()

    @property
    def service(self) -> str:
        return f"{self.unit}.service"

    @property
    def timer(self) -> str:
        return f"{self.unit}.timer"


_BY_STEM = {j.log_stem: j for j in ip.JOBS}
VM_JOBS = (
    VmJob(f"quantt-{BOOK}-session", _BY_STEM["session"], SESSION_SUCCESS_EXIT),
    VmJob(f"quantt-{BOOK}-verify", _BY_STEM["verify"]),
    VmJob(f"quantt-{BOOK}-collect", _BY_STEM["collect"]),
)


def template_path(unit_file: str) -> str:
    return f"{TEMPLATE_DIR}/{unit_file}.tmpl"


ALL_UNIT_FILES = (SECRET_UNIT,) + tuple(f for vj in VM_JOBS for f in (vj.service, vj.timer))

# What the units need at the tag, beyond what install_prod requires.
REQUIRED_AT_TAG = ip.REQUIRED_AT_TAG + (
    "quantt/deploy/boot_secrets.py",
    "quantt/deploy/azure_keyvault.py",
    "requirements.txt",
) + tuple(template_path(f) for f in ALL_UNIT_FILES)


@dataclass(frozen=True)
class Layout:
    """Every path the VM prod uses. `home` and `units_dir` are parameters so
    the tests build the whole thing under tmp_path."""
    home: Path                       # /home/quantt
    units_dir: Path = UNITS_DIR
    sysroot: Path = Path("/")        # where the drop-in scan looks for /etc, /run, /usr

    @property
    def prod_dir(self) -> Path:
        return self.home / "prod" / "quantt-alpaca"

    @property
    def state_root(self) -> Path:
        return self.home / "quantt_state"

    @property
    def state_dir(self) -> Path:
        return self.state_root / BOOK

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def seed_log(self) -> Path:
        return self.state_dir / "seed.log"

    @property
    def venv_python(self) -> Path:
        return self.home / "venv" / "bin" / "python"

    @property
    def requirements_record(self) -> Path:
        return self.home / "venv" / REQUIREMENTS_RECORD

    def unit_path(self, unit_file: str) -> Path:
        return self.units_dir / unit_file


# -- schedule ---------------------------------------------------------------

def oncalendar(schedule) -> list:
    """launchd StartCalendarInterval dicts -> systemd OnCalendar expressions.

    A dict without Weekday fires every day; one without Hour fires every
    hour (an omitted launchd key is a wildcard). Weekday dicts sharing an
    hour and minute are folded into one line with a day list, e.g.
    `Mon,Tue,Wed,Thu,Fri *-*-* 15:52:00`. The tests prove the result fires at
    exactly the launchd times, by expanding both over a whole week.
    """
    plain, by_time = [], {}
    for d in schedule:
        if not set(d) <= {"Weekday", "Hour", "Minute"} or "Minute" not in d:
            raise InstallRefused(f"cannot translate launchd interval {d!r}")
        hh = f"{d['Hour']:02d}" if "Hour" in d else "*"
        mm = f"{d['Minute']:02d}"
        if "Weekday" in d:
            by_time.setdefault((hh, mm), set()).add(WEEKDAY_NAMES[d["Weekday"]])
        else:
            plain.append(f"*-*-* {hh}:{mm}:00")
    for (hh, mm), days in by_time.items():
        plain.append(f"{','.join(sorted(days, key=DAY_ORDER.index))} *-*-* {hh}:{mm}:00")
    return plain


# -- units ------------------------------------------------------------------

def parse_unit(text: str, name: str) -> dict:
    """A unit file -> {section: [(key, value), ...]}, keeping repeated keys.

    configparser would collapse the repeated keys systemd allows (Environment=,
    OnCalendar=). Line continuations are refused, so that what is checked is
    exactly what systemd reads.
    """
    sections, cur = {}, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.endswith("\\"):
            raise InstallRefused(f"{name}:{n}: line continuation not allowed")
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]
            if cur in sections:
                raise InstallRefused(f"{name}:{n}: section [{cur}] repeated")
            sections[cur] = []
            continue
        if cur is None or "=" not in line:
            raise InstallRefused(f"{name}:{n}: not a key=value line in a section: {line!r}")
        k, v = line.split("=", 1)
        sections[cur].append((k.strip(), v.strip()))
    return sections


def check_unit(text: str, name: str, expected: dict) -> dict:
    """Parse a rendered unit and require exactly `expected`, or raise.

    `expected` maps section -> [(key, value)]. Order within a section is free,
    multiplicity is not. [Unit] must also hold exactly one non-empty
    Description=, whose text is not checked. Returns the parsed unit.
    """
    got = parse_unit(text, name)
    problems = []
    for sec, pairs in got.items():
        for k, v in pairs:
            if "$" in v or "%" in v:
                problems.append(f"[{sec}] {k}={v!r} contains '$' or '%' (systemd would expand it)")
    unit = list(got.get("Unit", []))
    desc = [v for k, v in unit if k == "Description"]
    if len(desc) != 1 or not desc[0]:
        problems.append(f"[Unit] needs exactly one non-empty Description=, has {desc!r}")
    got_cmp = {sec: [p for p in pairs if not (sec == "Unit" and p[0] == "Description")]
               for sec, pairs in got.items()}
    if set(got_cmp) != set(expected):
        problems.append(f"sections are {sorted(got_cmp)}, expected {sorted(expected)}")
    for sec in set(got_cmp) & set(expected):
        # Environment= order is what systemd reports (measured), and the
        # post-reload check compares it in order, so planning pins it too.
        env_have = [v for k, v in got_cmp[sec] if k == "Environment"]
        env_want = [v for k, v in expected[sec] if k == "Environment"]
        if Counter(env_have) == Counter(env_want) and env_have != env_want:
            problems.append(f"[{sec}] Environment order is {env_have}, expected {env_want}")
        have, want = Counter(got_cmp[sec]), Counter(expected[sec])
        for k, v in sorted((want - have).elements()):
            problems.append(f"[{sec}] missing {k}={v}")
        for k, v in sorted((have - want).elements()):
            problems.append(f"[{sec}] unexpected {k}={v}")
    if problems:
        raise InstallRefused(f"{name}: rendered unit fails its checks: " + "; ".join(problems))
    return got


def expected_job_service(vj: VmJob, *, python: Path, layout: Layout, env: dict) -> dict:
    svc = [("Type", "oneshot"), ("User", SERVICE_USER), ("Group", SERVICE_USER),
           ("WorkingDirectory", str(layout.prod_dir)),
           *[("Environment", f"{k}={v}") for k, v in env.items()],
           ("ExecStart", " ".join([str(python), *vj.job.args])),
           ("StandardOutput", f"append:{layout.log_dir}/{vj.job.log_stem}.out.log"),
           ("StandardError", f"append:{layout.log_dir}/{vj.job.log_stem}.err.log")]
    if vj.success_exit:
        svc.append(("SuccessExitStatus", " ".join(str(c) for c in vj.success_exit)))
    return {"Unit": [("Wants", SECRET_UNIT), ("After", SECRET_UNIT)], "Service": svc}


def expected_timer(vj: VmJob) -> dict:
    return {"Unit": [],
            "Timer": [*[("OnCalendar", e) for e in oncalendar(vj.job.schedule)],
                      ("AccuracySec", "1s"), ("Persistent", "false"),
                      ("Unit", vj.service)],
            "Install": [("WantedBy", "timers.target")]}


def secret_command(python: Path, vault: str) -> list:
    cmd = [str(python), "-m", "quantt.deploy.boot_secrets", "--provider", SECRET_PROVIDER,
           "--config", f"vault={vault}"]
    for name, env in SECRET_MAP:
        cmd += ["--secret", f"{name}={env}"]
    return cmd + ["--out", str(ENV_FILE)]


def expected_secret_service(*, python: Path, layout: Layout, env: dict, vault: str) -> dict:
    return {"Unit": [("Wants", "network-online.target"), ("After", "network-online.target")],
            "Service": [("Type", "oneshot"), ("RemainAfterExit", "yes"),
                        ("User", SERVICE_USER), ("Group", SERVICE_USER),
                        ("RuntimeDirectory", RUNTIME_DIR), ("RuntimeDirectoryMode", "0700"),
                        ("WorkingDirectory", str(layout.prod_dir)),
                        ("Environment", f"PATH={env['PATH']}"),
                        ("Environment", f"PYTHONUNBUFFERED={env['PYTHONUNBUFFERED']}"),
                        ("ExecStart", " ".join(secret_command(python, vault))),
                        ("StandardOutput", f"append:{layout.log_dir}/secret.out.log"),
                        ("StandardError", f"append:{layout.log_dir}/secret.err.log")],
            "Install": [("WantedBy", "multi-user.target")]}


def render(template_text: str, values: dict, name: str) -> str:
    """Substitute ${NAME} placeholders. Every value must match SAFE_VALUE_RE, and
    a placeholder with no value raises rather than shipping a literal `${X}`."""
    for k, v in values.items():
        if not SAFE_VALUE_RE.match(str(v)):
            raise InstallRefused(f"{name}: value for ${{{k}}} ({v!r}) has characters a "
                                 f"unit file would misread (space, %, $, quotes)")
    try:
        return Template(template_text).substitute({k: str(v) for k, v in values.items()})
    except KeyError as e:
        raise InstallRefused(f"{name}: template placeholder {e} has no value") from e
    except ValueError as e:
        raise InstallRefused(f"{name}: template is malformed: {e}") from e


# -- processes --------------------------------------------------------------

def _real_run(args):
    return subprocess.run(args, capture_output=True, text=True)


def _user_ids(user: str) -> tuple:
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        raise InstallRefused(f"no user {user!r} on this machine; run "
                             f"quantt/deploy/vm/bootstrap.sh first") from None
    return pw.pw_uid, pw.pw_gid


class Git:
    """git in the prod clone, as the service user.

    HOME is set to that user's home, so git never reads root's config. That
    matters because `runuser` without `-l` would keep root's HOME, and git
    cannot read /root as quantt.
    """

    def __init__(self, repo: Path, as_user: list, home: Path):
        self.repo, self.as_user, self.home = repo, as_user, home

    def __call__(self, *args, allow_fail=False, raw=False):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", HOME=str(self.home))
        r = subprocess.run([*self.as_user, "git", "-C", str(self.repo), *args],
                           capture_output=True, text=not raw, env=env)
        if r.returncode != 0:
            if allow_fail:
                return None
            err = r.stderr.decode("utf-8", "replace") if raw else r.stderr
            raise InstallRefused(f"`git {' '.join(args)}` failed (exit {r.returncode}): "
                                 f"{err.strip()}")
        return r.stdout


def remote_tag_commit(git: Git, url: str, tag: str) -> str:
    """The commit `refs/tags/<tag>` names on `url`, peeled for annotated tags."""
    out = git("ls-remote", "--tags", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    refs = {}
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        refs[ref] = sha
    plain, peeled = refs.get(f"refs/tags/{tag}"), refs.get(f"refs/tags/{tag}^{{}}")
    if plain is None:
        raise InstallRefused(f"tag {tag} is not on origin ({url}); push it first")
    return peeled or plain


# -- what systemd runs (review 2026-10-07) -----------------------------------
#
# A unit FILE is not what systemd runs. A drop-in (`systemctl edit` writes
# <unit>.d/override.conf; `set-property` writes under system.control; a
# `quantt-.service.d/` directory applies to every quantt-* service) is merged on
# top of the file. A disarm-by-reinstall that rewrote only the file would leave
# an override's Environment=DRY_RUN=0 in force. So the installer asks systemd:
# before planning, that no drop-in exists and the unit comes from our file; after
# daemon-reload, that what systemd loaded is exactly what was written. This is
# install_prod's launchd precedent (refuse when the loaded job and the file could
# disagree), applied to systemd.
#
# The `systemctl show` formats parsed here (`Key=value` lines; ExecStart as
# `{ path=... ; argv[]=... ; ... }`; TimersCalendar as `{ OnCalendar=... ; ... }`)
# are systemd's [S]. A format this code cannot read REFUSES, never passes.
# MEASURED on the VM (systemd 255.4-1ubuntu8.17, 2026-10-07) [V]:
#   * `systemctl show quantt-nonexistent.service -p FragmentPath -p DropInPaths
#     -p Environment` exits 0 and reports all three, empty, with
#     LoadState=not-found. So a first install's planning reads empty values, and
#     no "unit not found" error.
#   * Environment= is reported in FILE order (file ZED, ALPHA, MID -> show
#     `ZED=1 ALPHA=2 MID=3`), so the ordered comparison below is exact, and
#     check_unit pins the order at planning.
#   * A drop-in written WITHOUT daemon-reload is INVISIBLE here. DropInPaths
#     stays empty, the old Environment is shown, and NeedDaemonReload stays
#     `no`, until the next reload, which would be this installer's own. So
#     `systemctl show` cannot be the pre-write check. `dormant_overrides`
#     scans the disk instead. (A naive probe on an inactive, unreferenced unit
#     looks fine, because systemd re-reads that from disk on query; the
#     measurement used a unit held loaded by an active timer.)
# MEASURED on the VM (systemd 255.4-1ubuntu8.17, 2026-10-08 ~01:10 UTC) [V]:
#   (a) A start queued behind its After= dependency (the dependency
#       `activating`) reads `systemctl is-active` = inactive, ActiveState=
#       inactive, SubState=dead. But `show -p Job` is a job id, and
#       `list-jobs` shows `<id> <unit> start waiting`. So `is-active` alone
#       misses a queued job; `job_states` reads ActiveState AND Job.
#   (b) CORRECTED 2026-10-08 (release-check #3). This note first said a
#       restart does NOT replay a missed slot. That came from a probe on a
#       started-but-NOT-ENABLED timer, which is likely unloaded on stop and
#       so forgets its last trigger. It does not apply to our enabled timers.
#       MEASURED on the VM [V: 2026-10-08 04:38-04:41 UTC; OnCalendar *:*:00
#       and *:*:30, enabled]: fired 04:39:00, stopped 04:39:00, slots
#       04:39:30 and 04:40:00 missed, `systemctl start` at 04:40:15 -> ran at
#       04:40:15, LastTriggerUSec=04:40:15. So an ENABLED Persistent=false
#       timer restarted within one boot across a missed slot fires AT ONCE.
#       That is why the installer refuses inside the late windows and
#       re-checks the clock before it restarts the timers (_refuse_if_late).

# Directories where set-property and transient units live. On a system manager
# `systemd-analyze unit-paths` lists them already [S]; they are added anyway,
# because missing one would let an override through.
CONTROL_DIRS = ("etc/systemd/system.control", "run/systemd/system.control",
                "run/systemd/transient")


def unit_search_path(run_cmd: Callable) -> list:
    """systemd's unit search path, in priority order (`systemd-analyze unit-paths`)."""
    r = run_cmd(["systemd-analyze", "unit-paths"])
    if r.returncode != 0:
        raise InstallRefused(f"`systemd-analyze unit-paths` failed: "
                             f"{(r.stderr or r.stdout).strip()}")
    dirs = [Path(line.strip()) for line in (r.stdout or "").splitlines() if line.strip()]
    if not dirs:
        raise InstallRefused("`systemd-analyze unit-paths` listed no directories")
    return dirs


def dropin_dir_names(unit: str) -> list:
    """Every drop-in directory name systemd reads for `unit` (systemd.unit(5)):

      * `<unit>.d/`;
      * each dash-truncated prefix, e.g. `quantt-.service.d/` and
        `quantt-cef-.service.d/` for quantt-cef-session.service. The full stem
        plus '-' is included too: a name that can only refuse more is safe;
      * the type-wide `service.d/` or `timer.d/`, which applies to every unit of
        that type. That is since systemd 253 [S: release notes, not re-read];
        Ubuntu 24.04 ships 255.
    """
    stem, typ = unit.rsplit(".", 1)
    parts = stem.split("-")
    return ([f"{unit}.d"] + [f"{'-'.join(parts[:i])}-.{typ}.d" for i in range(1, len(parts) + 1)]
            + [f"{typ}.d"])


def dormant_overrides(run_cmd: Callable, layout: "Layout") -> list:
    """Files on disk that would change what systemd runs for our units at the
    next daemon-reload, which is the installer's own. They are invisible to
    `systemctl show` until then (measured; see the comment above). Returns a
    sorted list of descriptions; empty means none.

      * any `*.conf` in any drop-in directory of any of our units, in any
        directory of the search path or the control/transient directories;
      * a unit file with one of our names in a directory that outranks ours,
        which systemd would load instead of the file written here.
    """
    search = unit_search_path(run_cmd)
    resolved = [d.resolve() for d in search]
    ours = layout.units_dir.resolve()
    if ours not in resolved:
        raise InstallRefused(f"{layout.units_dir} is not on systemd's unit search path "
                             f"({', '.join(map(str, search))}); systemd would not load "
                             f"the units written there")
    roots = list(dict.fromkeys(search + [layout.sysroot / d for d in CONTROL_DIRS]))
    found = set()
    for d in roots:
        for unit in ALL_UNIT_FILES:
            for name in dropin_dir_names(unit):
                for conf in (d / name).glob("*.conf") if (d / name).is_dir() else ():
                    found.add(f"drop-in {conf} (applies to {unit})")
    for d in search[:resolved.index(ours)]:
        for unit in ALL_UNIT_FILES:
            if (d / unit).exists() or (d / unit).is_symlink():
                found.add(f"unit file {d / unit} outranks {layout.unit_path(unit)}")
    for d in roots[len(search):]:              # control/transient dirs not on the path
        for unit in ALL_UNIT_FILES:
            if (d / unit).exists() or (d / unit).is_symlink():
                found.add(f"unit file {d / unit} (control/transient) for {unit}")
    return sorted(found)


def _refuse_if_overridden_on_disk(run_cmd: Callable, layout: "Layout") -> None:
    found = dormant_overrides(run_cmd, layout)
    if found:
        raise InstallRefused(
            "files on disk would change what systemd runs at the next daemon-reload "
            "(the installer's own), and `systemctl show` cannot see them until then: "
            + "; ".join(found) + ". Read them, remove them, and re-run")


BUSY_STATES = frozenset({"active", "activating", "deactivating", "reloading", "refreshing"})
IDLE_STATES = frozenset({"inactive", "failed", "maintenance"})


def systemd_show(run_cmd: Callable, unit: str, props: list) -> dict:
    """{property: [value, ...]} from `systemctl show`, or raise."""
    args = ["systemctl", "show", unit]
    for prop in props:
        args += ["-p", prop]
    r = run_cmd(args)
    if r.returncode != 0:
        raise InstallRefused(f"`systemctl show {unit}` failed: {(r.stderr or r.stdout).strip()}")
    out = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out.setdefault(k, []).append(v)
    missing = [prop for prop in props if prop not in out]
    if missing:
        raise InstallRefused(f"`systemctl show {unit}` did not report {missing}; cannot "
                             f"confirm what systemd runs")
    return out


def _one(props: dict, key: str, unit: str) -> str:
    if len(props[key]) != 1:
        raise InstallRefused(f"`systemctl show {unit}` reported {key} {len(props[key])} times")
    return props[key][0]


def check_not_overridden(run_cmd: Callable, layout: "Layout", unit: str) -> dict:
    """Planning: no drop-in on `unit`, and if systemd has it loaded, from our file."""
    service = unit.endswith(".service")
    props = systemd_show(run_cmd, unit, ["FragmentPath", "DropInPaths"]
                         + (["Environment"] if service else []))
    drop = _one(props, "DropInPaths", unit).split()
    if drop:
        raise InstallRefused(
            f"{unit} has drop-in(s) {drop}: systemd merges them over the unit file, so "
            f"this install could not decide what runs (an Environment=DRY_RUN=0 there "
            f"would survive a disarm). Read them, then remove them (`systemctl revert "
            f"{unit}`, or delete the file) and re-run")
    frag = _one(props, "FragmentPath", unit)
    if frag and frag != str(layout.unit_path(unit)):
        raise InstallRefused(f"systemd loads {unit} from {frag}, not {layout.unit_path(unit)}; "
                             f"refusing to install over a unit defined elsewhere")
    return props


def verify_loaded(run_cmd: Callable, layout: "Layout", unit: str, expect: dict) -> None:
    """After daemon-reload: systemd's loaded `unit` is exactly what was written."""
    service = unit.endswith(".service")
    props = systemd_show(run_cmd, unit, ["FragmentPath", "DropInPaths"]
                         + (["Environment", "ExecStart"] if service else ["TimersCalendar"]))
    problems = []
    drop = _one(props, "DropInPaths", unit).split()
    if drop:
        problems.append(f"drop-in(s) {drop}")
    frag = _one(props, "FragmentPath", unit)
    if frag != str(layout.unit_path(unit)):
        problems.append(f"FragmentPath is {frag!r}, expected {str(layout.unit_path(unit))!r}")
    if service:
        env = _one(props, "Environment", unit).split()
        if env != expect["env"]:
            problems.append(f"Environment is {env}, expected {expect['env']}")
        argv = re.findall(r"argv\[\]=(.*?) ;", " ".join(props["ExecStart"]))
        if argv != [expect["exec"]]:
            problems.append(f"ExecStart argv is {argv}, expected {[expect['exec']]}")
    else:
        cal = re.findall(r"OnCalendar=(.*?) ;", " ".join(props["TimersCalendar"]))
        if sorted(cal) != sorted(expect["calendar"]):
            problems.append(f"calendar is {sorted(cal)}, expected {sorted(expect['calendar'])}")
    if problems:
        raise InstallRefused(
            f"after daemon-reload systemd's {unit} is not the unit written: "
            + "; ".join(problems) + ". systemd is NOW running the configuration shown. "
            + HALT_ADVICE + ", then find the cause")


# How to halt NOW, named in every refusal that leaves systemd running something
# unexpected. The halt file comes first because it stops every send, whatever
# arms it. On the cut-over day the VM sends from <state>/<D>/APPROVED with no
# AUTO_ARMED (RUNBOOK 8.5), so removing AUTO_ARMED alone would halt nothing
# (release-check #8, 2026-10-08).
HALT_ADVICE = ("Halt now with docs/RUNBOOK.md 8.6 halting step 1 or 2: the halt file "
               "(ops/HALT.md), which stops every send; or remove AUTO_ARMED AND the "
               "APPROVED file of any session not yet sent (<state>/<D>/APPROVED)")


def late_window_at(now_utc: dt.datetime, ranges=PLAN_REFUSE_RANGES_ET):
    """(start, end, local time) if `now_utc` is a weekday inside one of `ranges`, else None.

    Every weekday is guarded for both ranges, as the runner's pre-check does:
    which days close early is a calendar fact the installer does not need to
    get right in order to stay out of the way.
    """
    t = now_utc.astimezone(ZoneInfo(REQUIRED_TZ))
    if t.weekday() >= 5:
        return None
    for a, b in ranges:
        if a <= t.time() < b:
            return a, b, t
    return None


def _refuse_if_late(clock: Callable, what: str, ranges=PLAN_REFUSE_RANGES_ET) -> None:
    """Why (release-check #3, measured on the VM 2026-10-08): an ENABLED
    Persistent=false timer, stopped and restarted within one boot across a
    missed slot, FIRES AT ONCE on the restart. An --apply stops the timers, so
    one that spans 15:52/15:55 (12:52/12:55) would replay the send slot at its
    restart: a late, partial send. So: no install inside the windows, and no
    restart of the timers inside them. The planning window is the wider one
    (see PLAN_REFUSE_RANGES_ET)."""
    hit = late_window_at(clock(), ranges)
    if hit:
        a, b, t = hit
        raise InstallRefused(
            f"{what}: it is {t:%H:%M:%S} ET on a weekday, inside the late-market window "
            f"{a:%H:%M}-{b:%H:%M} ET (start any --apply before 15:30, or 12:30 on an "
            f"early close, or after the close). A timer restarted across a missed slot fires at "
            f"once (measured on the VM, 2026-10-08), so stopping and restarting the timers "
            f"here could replay the 15:52/15:55 (12:52/12:55) send slot into a late, "
            f"partial send. Re-run after {b:%H:%M} ET (after 16:00, or 13:00 on an early "
            f"close)")


def deps_script(layout: "Layout") -> str:
    """The RUNBOOK 8.6 dependency step as one bash script, run as the service user.

    Why this shape (release-check #4): an earlier form hashed requirements.txt as
    the admin user, who cannot read /home/quantt (mode 750), and piped the result
    into `tee` without pipefail. A failed hash then still TRUNCATED the record,
    so the installer refused again with the same advice, and the timers stayed
    stopped. Here everything runs as quantt under `set -euo pipefail`. The hash
    is computed first; the record is written only if the hash is non-empty, via a
    temp file and `mv`, so it is never left truncated.
    """
    q = shlex.quote
    req, rec = layout.prod_dir / "requirements.txt", layout.requirements_record
    return (f"set -euo pipefail; "
            f"{q(str(layout.home / '.uv' / 'bin' / 'uv'))} pip install --no-build "
            f"--python {q(str(layout.venv_python))} -r {q(str(req))}; "
            f"h=$(sha256sum {q(str(req))} | cut -d' ' -f1); "
            f'[ -n "$h" ]; '
            f"printf '%s\\n' \"$h\" > {q(str(rec) + '.tmp')}; "
            f"mv {q(str(rec) + '.tmp')} {q(str(rec))}")


def deps_command(layout: "Layout") -> str:
    """deps_script, run as the service user: the whole step is quantt's."""
    return (f"sudo -u {SERVICE_USER} env HOME={shlex.quote(str(layout.home))} "
            f"bash -c {shlex.quote(deps_script(layout))}")


def _refuse_if_venv_is_stale(git: "Git", commit: str, tag: str, layout: "Layout") -> None:
    """The venv must have been built from the TAG's requirements.txt.

    The installer does not install dependencies. Without this check, a release
    that changed requirements.txt would run its new code against the old
    packages, and nothing would say so until something failed at run time.
    bootstrap.sh (and the RUNBOOK 8.6 step) record the sha256 of the
    requirements.txt they installed; it is compared here with the tag's blob.
    """
    want = hashlib.sha256(git("show", f"{commit}:requirements.txt", raw=True)).hexdigest()
    rec = layout.requirements_record
    try:
        words = rec.read_text().split()
    except FileNotFoundError:
        words = []
    if not words:
        raise InstallRefused(
            f"{rec} is missing or empty, so the venv has no record of the "
            f"requirements.txt it was built from. With the timers stopped and the clone "
            f"at {tag} (docs/RUNBOOK.md 8.6 steps 1 and 3), run: {deps_command(layout)}")
    if words[0] != want:
        raise InstallRefused(
            f"the venv was built from a requirements.txt with sha256 {words[0][:12]}..., but "
            f"{tag}'s has {want[:12]}...: its packages do not match the release. With the "
            f"timers stopped, check out {tag} (docs/RUNBOOK.md 8.6 step 3), then run: "
            f"{deps_command(layout)}")


def _confirm_key_file(layout: "Layout", uid: int) -> None:
    """The key file exists, is a regular 0600 file, and is owned by the service
    user. The check uses stat only: the file is never opened."""
    f = layout.sysroot / ENV_FILE.relative_to("/")
    try:
        st = os.lstat(f)
    except FileNotFoundError:
        raise InstallRefused(f"{SECRET_UNIT} is active but {ENV_FILE} does not exist") from None
    problems = []
    if not stat.S_ISREG(st.st_mode):
        problems.append("is not a regular file")
    if st.st_mode & 0o777 != 0o600:
        problems.append(f"has mode {oct(st.st_mode & 0o777)}, expected 0o600")
    if st.st_uid != uid:
        problems.append(f"is owned by uid {st.st_uid}, not {SERVICE_USER} ({uid})")
    if problems:
        raise InstallRefused(f"{ENV_FILE} {' and '.join(problems)}")


class JobDuringInstall(InstallRefused):
    """A quantt job ran or was queued AFTER the reload. That should be
    impossible with the timers stopped, so it is a separate exit code and a
    louder message than a refusal."""


def job_states(run_cmd: Callable) -> list:
    """Every quantt service that is running or has a job queued, as dicts.

    Busy means one of:
      * a job service whose ActiveState is active, activating, deactivating,
        reloading or refreshing;
      * a job service with a non-empty `Job` (queued, which `is-active` misses;
        measured, see (a) above);
      * the key service `activating`, or with a queued Job, because jobs may be
        queued behind it (After=). The key service being `active` is normal
        (RemainAfterExit=yes).
    A state this code does not know refuses.
    """
    rows = []
    for unit in [*(vj.service for vj in VM_JOBS), SECRET_UNIT]:
        props = systemd_show(run_cmd, unit, ["ActiveState", "Job", "MainPID"])
        state = _one(props, "ActiveState", unit).strip()
        job = _one(props, "Job", unit).strip()
        pid = _one(props, "MainPID", unit).strip()
        if state not in BUSY_STATES | IDLE_STATES:
            raise InstallRefused(f"`systemctl show {unit} -p ActiveState` said {state!r}; "
                                 f"cannot confirm no job is running")
        busy = (state == "activating" if unit == SECRET_UNIT else state in BUSY_STATES)
        if busy or job:
            rows.append({"unit": unit, "state": state, "job": job, "pid": pid})
    return rows


def _describe(row: dict) -> str:
    queued = f", queued job {row['job']}" if row["job"] else ""
    return f"{row['unit']} is {row['state']}{queued}"


def _refuse_if_busy(run_cmd: Callable) -> None:
    rows = job_states(run_cmd)
    if rows:
        raise InstallRefused(
            f"{'; '.join(_describe(r) for r in rows)}: never install under a running or "
            f"queued job (it could be mid-send, and a checkout would change its code). "
            f"Wait for it to finish (docs/RUNBOOK.md section 8.6)")


def _read_environ(pid: str) -> dict:
    """A running process's environment, from /proc (needs root for another user's)."""
    raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace")
    return dict(item.split("=", 1) for item in raw.split("\0") if "=" in item)


def _stop_if_a_job_ran(run_cmd: Callable, read_environ: Callable) -> None:
    """After the reload, with the timers stopped, no job should run or be queued.
    If one is, name it, its MainPID and the DRY_RUN it STARTED with. That is
    read from /proc, never inferred: an unreadable environment is reported as
    unknown."""
    rows = job_states(run_cmd)
    if not rows:
        return
    parts = []
    for r in rows:
        if r["pid"] and r["pid"] != "0":
            try:
                env = read_environ(r["pid"])
                how = (f"started with DRY_RUN={env['DRY_RUN']}" if "DRY_RUN" in env
                       else "started with NO DRY_RUN in its environment")
            except OSError as e:
                how = (f"the DRY_RUN it started with is UNKNOWN: /proc/{r['pid']}/environ "
                       f"unreadable ({type(e).__name__}: {e})")
            parts.append(f"{_describe(r)}, MainPID {r['pid']}, {how}")
        else:
            parts.append(f"{_describe(r)}, not started yet (queued): it will run whatever "
                         f"definition systemd has loaded when it starts")
    raise JobDuringInstall(
        "a quantt job is running or queued after the reload: " + "; ".join(parts)
        + ". " + HALT_ADVICE + ", then check Alpaca for any order it sent")


# -- the plan ---------------------------------------------------------------

@dataclass
class Step:
    text: str
    run: Callable[[], None]


@dataclass
class Plan:
    notes: list
    warnings: list
    steps: list
    rendered: dict       # unit file name -> text
    state: dict          # run-time facts main() reports, e.g. timers this run left stopped


def _mkdir_owned(path: Path, uid: int, gid: int) -> None:
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)
    os.chown(path, uid, gid)


def build_plan(*, tag: str, vault: str, layout: Layout, python: Path, armed: bool,
               enable: bool, seed_from, origin_url: str, localtime: Path,
               run_cmd: Callable, as_user: list, euid: int, dont_write_bytecode: bool,
               user_ids: Callable, now_utc: dt.datetime,
               read_environ: Callable = _read_environ,
               clock: Callable = lambda: dt.datetime.now(dt.timezone.utc)) -> Plan:
    """Run every check, then return the steps an install would take.

    Everything that can refuse does so HERE, before any step runs. A refusal
    halfway through would leave prod in a state no tag describes.
    """
    notes, warnings, steps = [], [], []

    if euid != 0:
        raise InstallRefused("must run as root (sudo): it writes /etc/systemd/system "
                             "and runs systemctl")
    if not dont_write_bytecode:
        raise InstallRefused("run python with -B: as root it would otherwise write "
                             "root-owned __pycache__ into the quantt user's clone")
    uid, gid = user_ids(SERVICE_USER)
    zone = ip.system_timezone(localtime)
    if zone != REQUIRED_TZ:
        raise InstallRefused(f"system timezone is {zone}, not {REQUIRED_TZ}; the timers "
                             f"are local wall-clock time written in US/Eastern. Set it: "
                             f"`sudo timedatectl set-timezone {REQUIRED_TZ}`")
    notes.append(f"system timezone {zone}")
    _refuse_if_late(clock, "refusing to install")
    try:
        akv.check_vault_name(vault)
    except akv.SecretFetchError as e:
        raise InstallRefused(str(e)) from None
    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise InstallRefused(f"--python {python} is not an absolute path to an executable")
    ip.validate_tag(tag)

    prod = layout.prod_dir
    if not (prod / ".git").is_dir():
        raise InstallRefused(f"no prod clone at {prod}; run quantt/deploy/vm/bootstrap.sh first")
    git = Git(prod, as_user, layout.home)
    url = git("remote", "get-url", "origin").strip()
    if url != origin_url:
        raise InstallRefused(f"{prod} is a clone of {url!r}, not of {origin_url!r}")
    dirty = git("status", "--porcelain").strip()
    if dirty:
        raise InstallRefused(f"prod clone {prod} has local modifications; refusing to "
                             f"update over them:\n{dirty}")
    commit = remote_tag_commit(git, origin_url, tag)
    # Fetching changes only .git. A tag that moved on origin is refused by git
    # itself ("would clobber existing tag"), and the comparison below catches
    # anything else.
    git("fetch", "--quiet", "--tags", "origin")
    local = git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}",
                allow_fail=True)
    if local is None or local.strip() != commit:
        raise InstallRefused(f"tag {tag} is {commit} on origin but "
                             f"{local.strip() if local else 'absent'} in {prod}; "
                             f"a tag must not move after release")
    notes.append(f"release {tag} = commit {commit} (origin {origin_url})")
    missing = [p for p in REQUIRED_AT_TAG
               if git("cat-file", "-e", f"{commit}:{p}", allow_fail=True) is None]
    if missing:
        raise InstallRefused(f"tag {tag} lacks files the VM units need: {', '.join(missing)}")
    _refuse_if_venv_is_stale(git, commit, tag, layout)

    dry_run = "0" if armed else "1"
    env = ip.expected_env(dry_run, layout, ENV_FILE, python)
    values = {"TAG": tag, "PYTHON": python, "PROD_DIR": prod, "DRY_RUN": dry_run,
              "STATE_DIR": layout.state_dir, "ENV_FILE": ENV_FILE, "PATH": env["PATH"],
              "LOG_DIR": layout.log_dir, "USER": SERVICE_USER, "VAULT": vault}
    expected = {SECRET_UNIT: expected_secret_service(python=python, layout=layout,
                                                     env=env, vault=vault)}
    for vj in VM_JOBS:
        expected[vj.service] = expected_job_service(vj, python=python, layout=layout, env=env)
        expected[vj.timer] = expected_timer(vj)
    rendered = {}
    for unit_file in ALL_UNIT_FILES:
        assert unit_file.startswith(UNIT_PREFIX), unit_file
        tmpl = git("show", f"{commit}:{template_path(unit_file)}")
        text = render(tmpl, values, unit_file)
        check_unit(text, unit_file, expected[unit_file])
        rendered[unit_file] = text
    # systemd's own parser on every calendar expression: a line this module
    # accepts but systemd reads differently (or rejects) must stop the install.
    # Its "Normalized form" is also what `systemctl show` reports for a loaded
    # timer (Mon..Fri, not Mon,Tue,...), so the post-reload check compares to it.
    normal = {}
    for vj in VM_JOBS:
        for expr in oncalendar(vj.job.schedule):
            r = run_cmd(["systemd-analyze", "calendar", expr])
            if r.returncode != 0:
                raise InstallRefused(f"systemd-analyze rejects {vj.timer} OnCalendar={expr!r}: "
                                     f"{(r.stderr or r.stdout).strip()}")
            m = re.search(r"Normalized form:\s*(.+)", r.stdout or "")
            if not m:
                raise InstallRefused(f"systemd-analyze gave no normalized form for {expr!r}")
            normal[expr] = m.group(1).strip()

    # Files on disk first: a drop-in written without daemon-reload is invisible
    # to `systemctl show`, and would go live at this install's own reload.
    _refuse_if_overridden_on_disk(run_cmd, layout)
    # What systemd runs now: no drop-ins, no unit loaded from another file.
    # And no job running, because a checkout or a unit change under a send is
    # never safe.
    current = {u: check_not_overridden(run_cmd, layout, u) for u in ALL_UNIT_FILES}
    _refuse_if_busy(run_cmd)
    runtime = {SECRET_UNIT: {"env": [f"PATH={env['PATH']}",
                                     f"PYTHONUNBUFFERED={env['PYTHONUNBUFFERED']}"],
                             "exec": " ".join(secret_command(python, vault))}}
    for vj in VM_JOBS:
        runtime[vj.service] = {"env": [f"{k}={v}" for k, v in env.items()],
                               "exec": " ".join([str(python), *vj.job.args])}
        runtime[vj.timer] = {"calendar": [normal[e] for e in oncalendar(vj.job.schedule)]}

    timers = [vj.timer for vj in VM_JOBS]
    enabled = [t for t in timers if run_cmd(["systemctl", "is-enabled", "--quiet", t]).returncode == 0]
    running = [t for t in timers
               if _one(systemd_show(run_cmd, t, ["ActiveState"]), "ActiveState", t) == "active"]
    secret_on = (run_cmd(["systemctl", "is-enabled", "--quiet", SECRET_UNIT]).returncode == 0
                 or _one(systemd_show(run_cmd, SECRET_UNIT, ["ActiveState"]), "ActiveState",
                         SECRET_UNIT) == "active")

    def active_now(t):
        return _one(systemd_show(run_cmd, t, ["ActiveState"]), "ActiveState", t) == "active"

    # THE END STATE IS SET BY ENABLEMENT (release-check #2, 2026-10-08): after a
    # successful --apply every enabled timer is running, read back from
    # systemd. Restarting only "what was running" let a re-run after a refusal
    # exit 0 with every timer stopped: no decide, no send, no verify line.
    # `targets` is what must be running at the end. A failure reads it back
    # and reports any that are stopped; the run never claims a state it did not read.
    run_state = {"targets": list(timers) if enable else
                 [t for t in timers if t in set(enabled) | set(running)]}
    run_state["stopped_now"] = lambda: [t for t in run_state["targets"] if not active_now(t)]
    run_state["loaded_dry_run"] = lambda: loaded_dry_run(run_cmd)

    def _refuse_if_disabled_meanwhile():
        """A timer enabled at planning but disabled now was disabled DURING this
        install, most likely halt step 4 (docs/RUNBOOK.md 8.6). The install
        must not undo a halt: no restart, and no --enable (own review pass,
        release-check #5)."""
        dropped = [t for t in enabled
                   if run_cmd(["systemctl", "is-enabled", "--quiet", t]).returncode != 0]
        if dropped:
            raise InstallRefused(
                f"{', '.join(dropped)} was disabled during this install (a halt, "
                f"docs/RUNBOOK.md 8.6 step 4?). Not starting or enabling any timer. "
                f"Re-run the installer once the halt is lifted on purpose")

    def systemctl(*args):
        r = run_cmd(["systemctl", *args])
        if r.returncode != 0:
            raise InstallRefused(f"systemctl {' '.join(args)} failed: "
                                 f"{(r.stderr or r.stdout).strip()}")

    # THE TIMERS ARE STOPPED FIRST (release-check NO-GO, 2026-10-08). Without
    # that, a 15:52 firing between the last busy look and daemon-reload would
    # start the OLD unit (say DRY_RUN=0) while this run reported DRY_RUN=1
    # loaded. With the timers stopped, no firing can start a job until the run
    # restarts them at the end. A refusal after this point leaves them stopped,
    # and says so. The restart DOES replay a slot missed meanwhile (measured
    # (b)), so it is never done inside a late window (_refuse_if_late).
    if running:
        steps.append(Step(f"systemctl stop {' '.join(running)} (no firing can start a job "
                          f"during the install; every enabled timer is started at the end)",
                          lambda: systemctl("stop", *running)))
    steps.append(Step("confirm no quantt job is running or queued",
                      lambda: _refuse_if_busy(run_cmd)))

    # -- code
    head = git("rev-parse", "HEAD").strip()
    if head != commit:
        def checkout():
            git("checkout", "--quiet", "--detach", commit)
            now = git("rev-parse", "HEAD").strip()
            if now != commit:
                raise InstallRefused(f"prod HEAD is {now} after checkout, expected {commit}")
        steps.append(Step(f"git -C {prod} checkout --detach {commit} ({tag}) as "
                          f"{SERVICE_USER}; verify HEAD", checkout))
    else:
        notes.append(f"prod clone is already at {commit}")

    # -- state
    def make_state():
        for p in (layout.state_root, layout.state_dir, layout.log_dir):
            _mkdir_owned(p, uid, gid)
    steps.append(Step(f"mkdir {layout.log_dir} (QUANTT_STATE_DIR={layout.state_dir}), "
                      f"mode 700, owner {SERVICE_USER}", make_state))

    # -- data: prod's panels are prod's own once seeded; only absent files are copied
    data_dir = prod / "data" / BOOK
    for name in ip.SEED_FILES + ip.SEED_SUPPORT:
        dest = data_dir / name
        if dest.exists():
            steps.append(Step(f"leave {dest} untouched (prod's panels are prod's own)",
                              lambda: None))
            continue
        if seed_from is None:
            raise InstallRefused(f"prod has no {dest} and --seed-from was not given: copy "
                                 f"the laptop prod's data/cef files to the VM first "
                                 f"(docs/RUNBOOK.md section 8)")
        src = Path(seed_from) / name
        if not src.is_file():
            raise InstallRefused(f"cannot seed {dest}: {src} does not exist")
        digest = ip._sha256(src)
        size = src.stat().st_size

        def seed(src=src, dest=dest, digest=digest, size=size):
            for d in (data_dir.parent, data_dir):
                if not d.exists():
                    d.mkdir()
                    os.chown(d, uid, gid)
            if dest.exists():
                print(f"  {dest} appeared since planning; left untouched")
                return
            ip._copy_verified(src, dest, digest)
            os.chown(dest, uid, gid)
            # Provenance (RUNBOOK section 8): where prod's first panels came from.
            with open(layout.seed_log, "a") as fh:
                fh.write(f"{now_utc:%Y-%m-%dT%H:%M:%SZ} seeded {dest} from {src} "
                         f"sha256={digest} bytes={size} release={tag}\n")
            os.chown(layout.seed_log, uid, gid)
        steps.append(Step(f"copy {src} -> {dest} ({size} bytes, sha256 {digest[:12]}...), "
                          f"owner {SERVICE_USER}; record it in {layout.seed_log}", seed))

    def still_clean():
        dirty = git("status", "--porcelain").strip()
        if dirty:
            raise InstallRefused(f"prod clone {prod} is dirty after seeding:\n{dirty}")
    steps.append(Step("verify prod clone is still clean (seeded data is gitignored)",
                      still_clean))

    # -- units
    def last_look():
        _refuse_if_busy(run_cmd)
        _refuse_if_overridden_on_disk(run_cmd, layout)
    steps.append(Step("confirm again, before the units change, that no quantt-cef job is "
                      "running and no drop-in is waiting on disk", last_look))
    for unit_file in ALL_UNIT_FILES:
        dest = layout.unit_path(unit_file)
        was = ""
        loaded_env = current[unit_file].get("Environment", [""])[0].split()
        old_dry = [a.split("=", 1)[1] for a in loaded_env if a.startswith("DRY_RUN=")]
        if old_dry:
            was = f"; systemd currently runs DRY_RUN={old_dry[0]}"

        def write(dest=dest, text=rendered[unit_file]):
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".installing")
            tmp.write_text(text)
            os.chmod(tmp, 0o644)
            os.replace(tmp, dest)
        dr = f" (DRY_RUN={dry_run}{was})" if unit_file.endswith(".service") and \
            unit_file != SECRET_UNIT else ""
        steps.append(Step(f"write {dest}{dr}", write))

    steps.append(Step("systemctl daemon-reload (systemd runs the new units from here on)",
                      lambda: systemctl("daemon-reload")))

    def confirm_loaded():
        for unit_file in ALL_UNIT_FILES:
            verify_loaded(run_cmd, layout, unit_file, runtime[unit_file])
    steps.append(Step("confirm from systemd that every unit is loaded from the file written, "
                      "with no drop-in, and with the expected environment, command and "
                      "calendar", confirm_loaded))

    steps.append(Step("confirm from systemd that no quantt job ran or was queued during "
                      "the install", lambda: _stop_if_a_job_ran(run_cmd, read_environ)))

    # THE KEYS (release-check #2): quantt-secret is oneshot + RemainAfterExit, so
    # unless it is restarted, /run/quantt/alpaca.env keeps the keys fetched for
    # the OLD unit (another vault, or keys since rotated) while the run reports
    # success. It is re-fetched on every apply, now, while the timers are stopped
    # and no job is busy, so restarting it (which removes and re-creates
    # /run/quantt) cannot pull the file from under a job.
    if enable:
        steps.append(Step(f"systemctl enable {SECRET_UNIT} (the keys at every boot)",
                          lambda: systemctl("enable", SECRET_UNIT)))
    if enable or secret_on:
        def refresh_keys():
            systemctl("restart", SECRET_UNIT)
            st = _one(systemd_show(run_cmd, SECRET_UNIT, ["ActiveState"]), "ActiveState",
                      SECRET_UNIT)
            if st != "active":
                raise InstallRefused(f"{SECRET_UNIT} is {st} after its restart; the keys "
                                     f"were not fetched (see its log, secret.err.log)")
            _confirm_key_file(layout, uid)
        steps.append(Step(f"systemctl restart {SECRET_UNIT} (re-fetch the keys for the unit "
                          f"just loaded, while no job can run); confirm it is active and "
                          f"{ENV_FILE} is a 0600 file owned by {SERVICE_USER} (stat only)",
                          refresh_keys))

    if enable:
        def enable_timers():
            _refuse_if_late(clock, "not restarting the timers", RESTART_REFUSE_RANGES_ET)
            _refuse_if_disabled_meanwhile()
            systemctl("enable", "--now", *timers)
        steps.append(Step(f"systemctl enable --now {' '.join(timers)} (not inside a late "
                          f"window: a restart there could replay a send slot)", enable_timers))
    else:
        def start_enabled():
            _refuse_if_late(clock, "not restarting the timers", RESTART_REFUSE_RANGES_ET)
            _refuse_if_disabled_meanwhile()
            now_enabled = {t for t in timers
                           if run_cmd(["systemctl", "is-enabled", "--quiet", t]).returncode == 0}
            run_state["targets"] = [t for t in timers if t in now_enabled | set(running)]
            if run_state["targets"]:
                systemctl("start", *run_state["targets"])
        steps.append(Step("systemctl start every enabled timer (and any that was running "
                          "before this install), not inside a late window: a restart there "
                          "could replay a send slot", start_enabled))

    def read_back():
        want = run_state["targets"]
        states = {t: _one(systemd_show(run_cmd, t, ["ActiveState"]), "ActiveState", t)
                  for t in want}
        bad = [t for t in want if states[t] != "active"]
        if bad:
            raise InstallRefused(
                f"{', '.join(f'{t} is {states[t]}' for t in bad)}: not active after the "
                f"start, so it will not fire (see `systemctl status {bad[0]}`)")
        print(f"  timers active (read back from systemd): "
              f"{', '.join(want) if want else 'none (no timer is enabled)'}")
    steps.append(Step("read back from systemd that every enabled timer is active", read_back))

    if not enable:
        notes.append(f"timers enabled now: {', '.join(enabled) or 'none'}; running now: "
                     f"{', '.join(running) or 'none'}. The run ends by starting every enabled "
                     f"timer and reading back that each is active"
                     + ("" if enabled or running else
                        " (none is enabled, so none will run: NOT enabled by this run; pass "
                        "--apply --enable)"))

    if armed:
        warnings.append(f"ARMED: units get DRY_RUN=0. A scheduled session also needs "
                        f"{layout.state_dir}/AUTO_ARMED to transmit (docs/RUNNER.md gate 2)")
    return Plan(notes, warnings, steps, rendered, run_state)


def loaded_dry_run(run_cmd: Callable) -> str:
    """`DRY_RUN=<x>` as systemd has it LOADED for the session unit, or
    `DRY_RUN UNKNOWN (<why>)`. It is read, never inferred from a file or flag."""
    unit = VM_JOBS[0].service
    try:
        env = _one(systemd_show(run_cmd, unit, ["Environment"]), "Environment", unit).split()
    except Exception as e:                       # reported as UNKNOWN, never guessed
        return f"DRY_RUN UNKNOWN ({type(e).__name__}: {e})"
    vals = [a.split("=", 1)[1] for a in env if a.startswith("DRY_RUN=")]
    return f"DRY_RUN={vals[0]}" if len(vals) == 1 else \
        f"DRY_RUN UNKNOWN (systemd reports {len(vals)} DRY_RUN values)"


def _report_stopped_timers(plan: Plan) -> None:
    """After a failed step: which timers that must be running are not, READ
    BACK from systemd. If the read fails, say so; never claim either way.

    Starting them is an order-path act (release-check #4): inside 15:52-15:58
    ET, a start replays the missed send slot (M1, measured), which means a
    late and possibly partial send. So the advice prefers re-running the
    installer, which enforces the window guard. It names the late windows, and
    the DRY_RUN systemd has LOADED, because that is what a start would run.
    """
    try:
        stopped = plan.state["stopped_now"]()
    except Exception as e:                       # reported, and the caller still fails
        print(f"timers: could not read their state back ({type(e).__name__}: {e}); "
              f"treat them as STOPPED and check `systemctl list-timers 'quantt-*'`")
        return
    if stopped:
        loaded = plan.state["loaded_dry_run"]()
        print(f"timers left STOPPED: {' '.join(stopped)}. Nothing will run until they are "
              f"started. Prefer to re-run the installer: it refuses inside the late windows. "
              f"If you start them by hand, NOT on a weekday inside 15:40-16:00 or "
              f"12:40-13:00 ET; wait until after 16:00 (13:00 on an early close). A start "
              f"there replays the missed send slot: a late, possibly partial send. "
              f"systemd has {loaded} LOADED for quantt-cef-session.service, and that is "
              f"what starting them would run "
              f"(`sudo systemctl start {' '.join(stopped)}`)")


def main(argv=None, *, layout: Layout | None = None, origin_url: str = ORIGIN_URL,
         localtime: Path = Path("/etc/localtime"), run_cmd: Callable = _real_run,
         as_user: list | None = None, euid: int | None = None,
         dont_write_bytecode: bool | None = None, user_ids: Callable = _user_ids,
         now_utc: dt.datetime | None = None, read_environ: Callable | None = None,
         clock: Callable | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True, help="release tag, already pushed to origin")
    ap.add_argument("--vault", required=True,
                    help="Azure Key Vault name holding alpaca-cef-key-id and "
                         "alpaca-cef-secret-key (no default)")
    ap.add_argument("--seed-from", type=Path, default=None,
                    help="directory holding the laptop prod's data/cef files; needed "
                         "only while prod lacks them")
    ap.add_argument("--apply", action="store_true", help="act (default: dry run)")
    ap.add_argument("--enable", action="store_true",
                    help="with --apply: enable and start the timers and the key service")
    ap.add_argument("--armed", action="store_true", help="render DRY_RUN=0 (default DRY_RUN=1)")
    ap.add_argument("--python", type=Path, default=None,
                    help="interpreter the units run (default: /home/quantt/venv/bin/python)")
    a = ap.parse_args(argv)
    if a.enable and not a.apply:
        ap.error("--enable needs --apply: enabled timers are what trade")

    layout = layout or Layout(Path("/home") / SERVICE_USER)
    try:
        lock_fd = acquire_install_lock(layout.sysroot / INSTALL_LOCK.relative_to("/"))
    except InstallRefused as e:
        print(f"REFUSED: {e}")
        return 2
    try:
        return _main_locked(a, layout, origin_url=origin_url, localtime=localtime,
                            run_cmd=run_cmd, as_user=as_user, euid=euid,
                            dont_write_bytecode=dont_write_bytecode, user_ids=user_ids,
                            now_utc=now_utc, read_environ=read_environ, clock=clock)
    finally:
        os.close(lock_fd)                        # released on success, refusal and exception


def _main_locked(a, layout: Layout, *, origin_url, localtime, run_cmd, as_user, euid,
                 dont_write_bytecode, user_ids, now_utc, read_environ, clock) -> int:
    try:
        plan = build_plan(
            tag=a.tag, vault=a.vault, layout=layout, python=a.python or layout.venv_python,
            armed=a.armed, enable=a.enable, seed_from=a.seed_from, origin_url=origin_url,
            localtime=localtime, run_cmd=run_cmd,
            as_user=as_user if as_user is not None else ["runuser", "-u", SERVICE_USER, "--"],
            euid=os.geteuid() if euid is None else euid,
            dont_write_bytecode=(sys.flags.dont_write_bytecode
                                 if dont_write_bytecode is None else dont_write_bytecode),
            user_ids=user_ids, now_utc=now_utc or dt.datetime.now(dt.timezone.utc),
            read_environ=read_environ or _read_environ,
            clock=clock or (lambda: dt.datetime.now(dt.timezone.utc)))
    except InstallRefused as e:
        print(f"REFUSED: {e}")
        return 2

    for n in plan.notes:
        print(f"note: {n}")
    for w in plan.warnings:
        print(f"WARNING: {w}")
    verb = "DOING" if a.apply else "WOULD"
    for i, s in enumerate(plan.steps, 1):
        print(f"{verb} {i}. {s.text}")
        if a.apply:
            try:
                s.run()
            except InstallRefused as e:
                alert = isinstance(e, JobDuringInstall)
                print(f"{'ALERT' if alert else 'REFUSED'} at step {i}: {e}")
                _report_stopped_timers(plan)
                return EXIT_JOB_DURING_INSTALL if alert else 2
            except BaseException:
                # Not swallowed: re-raised with its traceback. But the operator
                # must still learn that the timers may be stopped.
                print(f"ERROR at step {i}: unexpected exception (traceback follows)")
                _report_stopped_timers(plan)
                raise
    if not a.apply:
        for name, text in plan.rendered.items():
            print(f"\n----- {layout.unit_path(name)} (rendered, not written)\n{text}")
        print("\nDRY RUN: nothing was written (tags were fetched into the clone's .git). "
              "Re-run with --apply to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
