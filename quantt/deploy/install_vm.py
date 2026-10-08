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
  (systemd.timer(5)).
* A firing that passes WHILE ITS SERVICE IS STILL RUNNING is not dropped.
  MEASURED on the VM, 2026-10-07 (Ubuntu 24.04.4, systemd 255.4-1ubuntu8.17): a
  transient timer firing every minute at :00 (AccuracySec=1s, Persistent=false)
  on a 90-second job started the next run the moment the previous one exited.
  The 23:14:00 firing ran at 23:14:30. For this book that means:
    - the 15:52 send polls until 30 s before the close (`_poll_final`, 15:59:30
      for a 16:00 close);
    - the 15:55 firing then starts a session at once, which can fall inside or
      after the window;
    - that session must idle on STARTED and the Alpaca-clock send window.
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
import os
import pwd
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable

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

    def __call__(self, *args, allow_fail=False):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", HOME=str(self.home))
        r = subprocess.run([*self.as_user, "git", "-C", str(self.repo), *args],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            if allow_fail:
                return None
            raise InstallRefused(f"`git {' '.join(args)}` failed (exit {r.returncode}): "
                                 f"{r.stderr.strip()}")
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
            "Halt now with docs/RUNBOOK.md 8.6 halting step 1 or 2 (ops/HALT.md, or "
            "remove AUTO_ARMED), then find the cause")


def busy_jobs(run_cmd: Callable) -> list:
    """Job services that are running now (`systemctl is-active` state), or raise
    on a state this code does not know. The key service is not a job: it stays
    `active` by design (RemainAfterExit=yes)."""
    busy = []
    for vj in VM_JOBS:
        r = run_cmd(["systemctl", "is-active", vj.service])
        state = (r.stdout or "").strip()
        if state in BUSY_STATES:
            busy.append(f"{vj.service} is {state}")
        elif state not in IDLE_STATES:
            raise InstallRefused(f"`systemctl is-active {vj.service}` said {state!r}; cannot "
                                 f"confirm no job is running")
    return busy


def _refuse_if_busy(run_cmd: Callable) -> None:
    busy = busy_jobs(run_cmd)
    if busy:
        raise InstallRefused(
            f"{'; '.join(busy)}: never install under a running job (it could be "
            f"mid-send, and a checkout would change its code). Wait for it to finish, "
            f"or stop the timers first (docs/RUNBOOK.md section 8.6)")


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


def _mkdir_owned(path: Path, uid: int, gid: int) -> None:
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)
    os.chown(path, uid, gid)


def build_plan(*, tag: str, vault: str, layout: Layout, python: Path, armed: bool,
               enable: bool, seed_from, origin_url: str, localtime: Path,
               run_cmd: Callable, as_user: list, euid: int, dont_write_bytecode: bool,
               user_ids: Callable, now_utc: dt.datetime) -> Plan:
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

    # A timer can fire between planning and acting, so look again before the
    # first change (the checkout) and again before the units change.
    steps.append(Step("confirm no quantt-cef job is running", lambda: _refuse_if_busy(run_cmd)))

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

    def systemctl(*args):
        r = run_cmd(["systemctl", *args])
        if r.returncode != 0:
            raise InstallRefused(f"systemctl {' '.join(args)} failed: "
                                 f"{(r.stderr or r.stdout).strip()}")
    steps.append(Step("systemctl daemon-reload (systemd runs the new units from here on)",
                      lambda: systemctl("daemon-reload")))

    def confirm_loaded():
        for unit_file in ALL_UNIT_FILES:
            verify_loaded(run_cmd, layout, unit_file, runtime[unit_file])
    steps.append(Step("confirm from systemd that every unit is loaded from the file written, "
                      "with no drop-in, and with the expected environment, command and "
                      "calendar", confirm_loaded))

    if enable:
        steps.append(Step(f"systemctl enable --now {SECRET_UNIT} (fetch the keys now; "
                          f"again at every boot)", lambda: systemctl("enable", "--now", SECRET_UNIT)))
        steps.append(Step(f"systemctl enable --now {' '.join(timers)}",
                          lambda: systemctl("enable", "--now", *timers)))
    else:
        if enabled:
            notes.append(f"timers already enabled ({', '.join(enabled)}): their next "
                         f"firing runs the units written by this install")
        else:
            notes.append("timers are NOT enabled by this run (pass --apply --enable)")

    if armed:
        warnings.append(f"ARMED: units get DRY_RUN=0. A scheduled session also needs "
                        f"{layout.state_dir}/AUTO_ARMED to transmit (docs/RUNNER.md gate 2)")
    return Plan(notes, warnings, steps, rendered)


def main(argv=None, *, layout: Layout | None = None, origin_url: str = ORIGIN_URL,
         localtime: Path = Path("/etc/localtime"), run_cmd: Callable = _real_run,
         as_user: list | None = None, euid: int | None = None,
         dont_write_bytecode: bool | None = None, user_ids: Callable = _user_ids,
         now_utc: dt.datetime | None = None) -> int:
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
        plan = build_plan(
            tag=a.tag, vault=a.vault, layout=layout, python=a.python or layout.venv_python,
            armed=a.armed, enable=a.enable, seed_from=a.seed_from, origin_url=origin_url,
            localtime=localtime, run_cmd=run_cmd,
            as_user=as_user if as_user is not None else ["runuser", "-u", SERVICE_USER, "--"],
            euid=os.geteuid() if euid is None else euid,
            dont_write_bytecode=(sys.flags.dont_write_bytecode
                                 if dont_write_bytecode is None else dont_write_bytecode),
            user_ids=user_ids, now_utc=now_utc or dt.datetime.now(dt.timezone.utc))
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
                print(f"REFUSED at step {i}: {e}")
                return 2
    if not a.apply:
        for name, text in plan.rendered.items():
            print(f"\n----- {layout.unit_path(name)} (rendered, not written)\n{text}")
        print("\nDRY RUN: nothing was written (tags were fetched into the clone's .git). "
              "Re-run with --apply to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
