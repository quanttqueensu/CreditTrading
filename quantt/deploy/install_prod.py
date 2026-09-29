"""Install (or update) the laptop prod clone of the Alpaca runner at a release tag.

    python3 -m quantt.deploy.install_prod --tag v2026.09.29.1 --env-file ~/.config/quantt/alpaca.env
    python3 -m quantt.deploy.install_prod --tag v2026.09.29.1 --env-file ... --apply
    python3 -m quantt.deploy.install_prod --tag v2026.09.29.1 --env-file ... --apply --load

WHY THIS EXISTS
---------------
Prod runs on this Mac until a VM exists (team lead, 2026-09-28), and the rule
for prod (docs/ROADMAP.md phase 6) is that it is THIS REPOSITORY AT A TAG AND
NOTHING ELSE. The IBKR-era prod tree broke that rule in the ways the rule now
forbids: its `data/` was a symlink into the dev tree, so a research script
could rewrite what the live sleeve priced from (CLAUDE.md landmine 9, and the
panel-write guard in the root conftest), and its schedule lived in hand-edited
plists nobody could diff against anything. This script is the only way the new
prod gets built, so every property of prod is something a reader can check
against a tag:

  * the code is a `git clone` of `origin`, checked out DETACHED at the tag, and
    the install refuses if that clone has any local modification -- a
    hand-edit in prod is exactly the thing that must never survive an update;
  * the tag must be on `origin`, and must be the SAME commit as this dev
    repo's tag of that name -- a tag moved after release would otherwise make
    the dev tree and prod disagree about what "v..." means;
  * the launchd plists are rendered from the templates AT THE TAG (read with
    `git show <commit>:<path>`, not from this working tree), then re-parsed
    and checked key by key, so the installed schedule is a function of the
    release and nothing else;
  * the price/NAV panels are COPIED, never symlinked, and only when prod does
    not already have them: from the first session on, prod's panels are
    prod's own (fetch_daily appends to them), and a re-install must not
    overwrite a newer prod panel with an older dev one.

DRY RUN BY DEFAULT
------------------
Without `--apply` it performs every read-only check (including a read-only
`git ls-remote` of origin) and prints exactly the steps `--apply` would take,
plus the full rendered plists. `--apply` executes those same steps: the dry
run and the real run are built by one function, so what was reviewed is what
runs. `--load` (only with `--apply`) additionally (re)loads the two jobs into
launchd; writing a plist and loading it are separate acts on purpose, because
a loaded job is what trades.

WHAT IT NEVER DOES
------------------
* Reads, prints or copies a credential. `--env-file` is required and checked
  for existence and permissions with `stat` only; its path, not its contents,
  goes into the plist as QUANTT_ENV_FILE, which `quantt.session` loads with
  `dotenv_values` at run time.
* Touches the retired IBKR prod: `~/prod/QUANTT` and the old `com.quantt.*`
  plists. It never lists `~/Library/LaunchAgents`; it writes only the two
  files whose labels start `com.quantt.alpaca.`, and refuses a layout that
  would land on the old tree.
* Transmits anything. It does not import `quantt.session` and has no broker
  code. Arming (`--armed`, DRY_RUN=0 in the plists) is necessary but NOT
  sufficient for a scheduled order: the runner also needs `AUTO_ARMED` in the
  state dir (docs/RUNNER.md gate 2), which the team lead creates after the
  first interactive go.

TIMEZONE
--------
launchd's StartCalendarInterval is LOCAL wall-clock time. The schedule is
written in US/Eastern, so the machine's zone is measured (`/etc/localtime`)
and anything but America/New_York is refused. MEASURED 2026-09-28: this Mac is
set to America/Toronto. Toronto keeps Eastern time with the same DST rules
today, but "today" is an assumption about the future, so it is not accepted
silently: `--accept-timezone America/Toronto` is an explicit override that
must name the measured zone, and it is honoured only if that zone's UTC offset
equals New York's at every hour of the next two years (checked against the
system tz database at install time). The alternative is to set the system
zone to America/New_York (a team-lead action, needs sudo).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
BOOK = "cef"
REQUIRED_TZ = "America/New_York"
LABEL_PREFIX = "com.quantt.alpaca."

# Monday..Friday in launchd's numbering (`man launchd.plist`: "0 and 7 are
# Sunday"). The runner, not the schedule, knows NYSE holidays: a job that
# fires on a holiday is refused by the runner's calendar check, which is
# cheaper to get right in one place than in a plist.
WEEKDAYS = (1, 2, 3, 4, 5)

# The data files the live path READS from data/cef, found by reading the code
# (2026-09-28), not assumed:
#   src/deploy/sleeves/cef_discount.py:72-73  PX_PATH, NAV_PATH (GRP_PATH is PX_PATH)
#   scripts/cef/fetch_daily.py:46-47         PX_PATH, NAV_PATH (read, then appended)
# fetch_daily also names `nav_fallback_log.csv`, but only APPENDS to it (header
# written when absent), so it is not seeded: prod's fallback log records prod's
# fallbacks. `test_seed_files_match_the_live_code` re-reads both sources and
# fails if either starts naming another file, forcing this list to be decided
# again rather than silently going stale.
SEED_FILES = ("cef_prices.parquet", "cef_nav.parquet")
SEED_WRITE_ONLY = ("nav_fallback_log.csv",)
# Not read by the live path, but needed in prod all the same, and seeded the
# same way (copied once, only when absent, then prod's own):
#   cef_universe.csv         scripts/fetch_cef_distributions.py reads it; the
#                            nightly collector (quantt.collect) runs that script
#                            and asks Alpaca for every universe ticker's close.
#   cef_distributions.parquet, cef_splits.parquet
#                            scripts/cef/tests read them; RUNBOOK 2.3 requires
#                            the prod clone's own pytest to be clean before its
#                            jobs are loaded. MEASURED 2026-09-28: without them
#                            5 tests failed in the prod clone (FileNotFoundError).
SEED_SUPPORT = ("cef_universe.csv", "cef_distributions.parquet", "cef_splits.parquet")

# What the scheduled command needs at the tag. Checked BEFORE anything is
# written: a plist pointing at a tag with no `quantt/session` would fail at
# 08:30 with an ImportError, and the first person to learn of it would be
# whoever reads the log.
REQUIRED_AT_TAG = (
    "quantt/session/__main__.py",
    "quantt/collect/__main__.py",
    "scripts/fetch_cef_distributions.py",
    "src/deploy/sleeves/cef_discount.py",
    "scripts/cef/fetch_daily.py",
    "ops/books/cef_discount_book.json",
    "ops/specs/cef_discount.frozen.json",
    "ops/halt.py",
)

# macOS privacy (TCC) folders. The 2026-07-31 IBKR session died under launchd
# with exit 126, `getcwd: Operation not permitted`, because its job touched a
# protected folder (ops/halt.py docstring). This dev repo lives in ~/Downloads.
# Whether THIS interpreter may read a file there under launchd has not been
# measured, so a key file or interpreter there is a loud warning, not a
# refusal; the first DRY_RUN session proves it either way (docs/RUNBOOK.md).
TCC_PROTECTED = ("Desktop", "Documents", "Downloads")

TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class InstallRefused(RuntimeError):
    """The install cannot proceed safely. The message names what is wrong."""


@dataclass(frozen=True)
class Job:
    label: str
    template: str          # repo-relative path, read AT THE TAG
    args: tuple            # ProgramArguments after the interpreter
    schedule: tuple        # StartCalendarInterval dicts, exactly as installed
    log_stem: str


def _weekdays_at(*times) -> tuple:
    return tuple({"Weekday": wd, "Hour": h, "Minute": m} for wd in WEEKDAYS for (h, m) in times)


# Every 30 minutes, every day. A launchd dict with only "Minute" fires every
# hour at that minute (`man launchd.plist`: omitted keys are wildcards).
EVERY_HALF_HOUR_AT_00_30 = ({"Minute": 0}, {"Minute": 30})
EVERY_HALF_HOUR_AT_10_40 = ({"Minute": 10}, {"Minute": 40})

JOBS = (
    # The session tries every 30 minutes and decides for itself whether this is
    # a slot (evening 22:00-01:00 ET after the as-of close, morning 06:00-15:15
    # ET backstop) and whether the day is already done -- team lead 2026-09-29:
    # "we dont have to do it at 830 why have it a hard time - should be
    # flexible". Until then it ran at 08:30 and 12:00, and the 08:30 run of
    # 2026-09-29 died on a DNS failure as the machine woke. The windows live
    # in quantt/session/run.py (one place, tested), not in this schedule.
    # Plus two firings inside the late-market send window (paper execution, team
    # lead 2026-09-29: market orders 8 to 2 minutes before the close), on
    # weekdays, for a 16:00 close (15:52, 15:55) and a 13:00 early close
    # (12:52, 12:55). The runner sends only inside the window computed from
    # the calendar close; every other firing idles.
    Job("com.quantt.alpaca.cef.session",
        "quantt/deploy/templates/com.quantt.alpaca.cef.session.plist.tmpl",
        ("-m", "quantt.session", "run", "--book", BOOK, "--scheduled"),
        EVERY_HALF_HOUR_AT_00_30 + _weekdays_at((15, 52), (15, 55), (12, 52), (12, 55)),
        "session"),
    # 17:30: after the close and the auction prints; read-only reconcile + verdict.
    Job("com.quantt.alpaca.cef.verify",
        "quantt/deploy/templates/com.quantt.alpaca.cef.verify.plist.tmpl",
        ("-m", "quantt.session", "verify", "--book", BOOK),
        _weekdays_at((17, 30)), "verify"),
    # The nightly data collector (read-only at Alpaca): it works out the latest
    # data day itself and idles once that day is complete, so it can simply
    # run every 30 minutes; offset 10 minutes from the session so the two
    # rarely contend for the panel lock.
    Job("com.quantt.alpaca.cef.collect",
        "quantt/deploy/templates/com.quantt.alpaca.cef.collect.plist.tmpl",
        ("-m", "quantt.collect", "--book", BOOK),
        EVERY_HALF_HOUR_AT_10_40, "collect"),
)


@dataclass(frozen=True)
class Layout:
    """Every path prod uses, derived from one home directory.

    `home` is a parameter so tests build the whole layout under tmp_path and
    never reach the real ~/Library or ~/prod.
    """
    home: Path

    @property
    def prod_dir(self) -> Path:
        return self.home / "prod" / "quantt-alpaca"

    @property
    def state_dir(self) -> Path:
        return self.home / "quantt_state" / BOOK

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def agents_dir(self) -> Path:
        return self.home / "Library" / "LaunchAgents"

    @property
    def old_prod(self) -> Path:
        return self.home / "prod" / "QUANTT"

    def plist_path(self, job: Job) -> Path:
        return self.agents_dir / f"{job.label}.plist"


# -- small helpers ----------------------------------------------------------

def _git(args, cwd=None, *, allow_fail=False):
    """Run git. Raises InstallRefused with git's stderr on failure.

    GIT_TERMINAL_PROMPT=0: a credential prompt inside an install would hang
    with no one to answer it; failing loudly is the better outcome.
    """
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True, env=env)
    if r.returncode != 0:
        if allow_fail:
            return None
        raise InstallRefused(f"`git {' '.join(args)}` failed "
                             f"(exit {r.returncode}): {r.stderr.strip()}")
    return r.stdout


def _real_launchctl(args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _under(path: Path, root: Path) -> bool:
    """True if `path` is `root` or inside it, compared case-insensitively.

    Case-insensitive because APFS is by default: `~/prod/quantt` and
    `~/prod/QUANTT` are the same directory on this Mac.
    """
    p = os.path.abspath(path).casefold().rstrip("/")
    r = os.path.abspath(root).casefold().rstrip("/")
    return p == r or p.startswith(r + "/")


# -- timezone ---------------------------------------------------------------

def system_timezone(localtime: Path = Path("/etc/localtime")) -> str:
    """The zone name the OS is set to, read from the /etc/localtime symlink.

    Not `time.tzname` (gives "EST"/"EDT", which Toronto and New York share) and
    not $TZ (launchd jobs do not inherit this shell's environment).
    """
    try:
        target = os.readlink(localtime)
    except OSError as e:
        raise InstallRefused(f"cannot read the system timezone from {localtime}: {e}") from e
    marker = "zoneinfo/"
    if marker not in target:
        raise InstallRefused(f"{localtime} -> {target!r} does not name a zoneinfo zone")
    return target.split(marker, 1)[1]


def offset_mismatches(zone: str, start_utc: dt.datetime, hours: int,
                      ref: str = REQUIRED_TZ) -> list:
    """UTC instants in [start, start+hours) where `zone` and `ref` differ in offset."""
    a, b = ZoneInfo(zone), ZoneInfo(ref)
    out = []
    t = start_utc.replace(minute=0, second=0, microsecond=0)
    for _ in range(hours):
        if t.astimezone(a).utcoffset() != t.astimezone(b).utcoffset():
            out.append(t)
        t += dt.timedelta(hours=1)
    return out


def check_timezone(detected: str, accept: str | None, now_utc: dt.datetime) -> str:
    """Return a note on the zone, or raise. See the module docstring."""
    if detected == REQUIRED_TZ:
        return f"system timezone {detected}"
    if accept is None:
        raise InstallRefused(
            f"system timezone is {detected}, not {REQUIRED_TZ}; the launchd "
            f"schedule is local wall-clock time written in US/Eastern. Either "
            f"set the system zone to {REQUIRED_TZ} (team lead: `sudo systemsetup "
            f"-settimezone {REQUIRED_TZ}`) or pass --accept-timezone {detected} "
            f"to accept it after an offset-equivalence check")
    if accept != detected:
        raise InstallRefused(
            f"--accept-timezone {accept} does not match the measured system "
            f"timezone {detected}")
    hours = 24 * 731
    bad = offset_mismatches(detected, now_utc, hours)
    if bad:
        raise InstallRefused(
            f"{detected} differs from {REQUIRED_TZ} at {len(bad)} hour(s) in the "
            f"next two years, first at {bad[0].isoformat()}; not accepted")
    return (f"system timezone {detected}, accepted by --accept-timezone: UTC "
            f"offset equals {REQUIRED_TZ} at every hour of the next {hours} "
            f"hours (checked {now_utc:%Y-%m-%d})")


# -- credentials file: metadata only ----------------------------------------

def check_env_file(path: Path, layout: Layout) -> list:
    """Warnings about the key file, or raise. NEVER opens the file.

    Only `stat` is used: existence, type, owner and mode. Mode 600 or stricter
    is expected (no group/other bits); anything looser is a warning, as the
    build contract asks, because refusing would not make the keys private --
    only the team lead's chmod does that.
    """
    if not path.is_absolute():
        raise InstallRefused(f"--env-file must be an absolute path, got {path}")
    if not path.exists():
        raise InstallRefused(f"--env-file {path} does not exist")
    if not path.is_file():
        raise InstallRefused(f"--env-file {path} is not a regular file")
    if _under(path, layout.prod_dir):
        raise InstallRefused(
            f"--env-file {path} is inside the prod clone {layout.prod_dir}; prod is "
            f"the repo at a tag and nothing else, so keys live outside it")
    warnings = []
    st = path.stat()
    if st.st_mode & 0o077:
        warnings.append(f"--env-file {path} has mode {oct(st.st_mode & 0o777)}; "
                        f"expected 600 or stricter (team lead: chmod 600 <file>)")
    if st.st_uid != os.getuid():
        warnings.append(f"--env-file {path} is owned by uid {st.st_uid}, not "
                        f"this user ({os.getuid()})")
    for d in TCC_PROTECTED:
        if _under(path, layout.home / d):
            warnings.append(
                f"--env-file {path} is under ~/{d}, a macOS privacy-protected "
                f"folder; a launchd job may be refused access (2026-07-31 exit "
                f"126). Prove it with the first DRY_RUN session, or move the "
                f"file, e.g. to ~/.config/quantt/")
    return warnings


# -- git facts --------------------------------------------------------------

def validate_tag(tag: str) -> None:
    if not TAG_RE.match(tag):
        raise InstallRefused(f"tag {tag!r} is not a plain tag name")


def remote_tag_commit(url: str, tag: str) -> str:
    """The commit `refs/tags/<tag>` names on `url`, peeled for annotated tags."""
    out = _git(["ls-remote", "--tags", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"])
    refs = {}
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        refs[ref] = sha
    peeled = refs.get(f"refs/tags/{tag}^{{}}")
    plain = refs.get(f"refs/tags/{tag}")
    if plain is None:
        raise InstallRefused(f"tag {tag} is not on origin ({url}); push it first "
                             f"(`git push origin {tag}`)")
    return peeled or plain


def local_tag_commit(repo: Path, tag: str):
    out = _git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"],
               cwd=repo, allow_fail=True)
    return out.strip() if out else None


def missing_at_commit(repo: Path, commit: str, paths) -> list:
    return [p for p in paths
            if _git(["cat-file", "-e", f"{commit}:{p}"], cwd=repo, allow_fail=True) is None]


def inspect_clone(prod_dir: Path, origin_url: str) -> str:
    """"absent", or "present" for a clean clone of `origin_url`; raise otherwise.

    `git status --porcelain` lists modified tracked files AND untracked files
    that are not gitignored. Either one in prod is a thing that is not the
    release, and an update would carry it forward, so the install stops and
    names it. `data/` is gitignored, so the seeded panels do not trip this.
    """
    if not prod_dir.exists():
        return "absent"
    if not (prod_dir / ".git").is_dir():
        raise InstallRefused(f"{prod_dir} exists but is not a git clone; "
                             f"refusing to write into it")
    url = _git(["remote", "get-url", "origin"], cwd=prod_dir).strip()
    if url != origin_url:
        raise InstallRefused(f"{prod_dir} is a clone of {url!r}, not of this "
                             f"repo's origin {origin_url!r}")
    dirty = _git(["status", "--porcelain"], cwd=prod_dir).strip()
    if dirty:
        raise InstallRefused(f"prod clone {prod_dir} has local modifications; "
                             f"refusing to update over them:\n{dirty}")
    return "present"


# -- plists -----------------------------------------------------------------

def render(template_text: str, values: dict) -> str:
    """Substitute ${NAME} placeholders, XML-escaping every value.

    `Template.substitute` (not `safe_substitute`) so a placeholder with no
    value raises rather than shipping a literal "${ENV_FILE}" to launchd.
    """
    try:
        return Template(template_text).substitute(
            {k: escape(str(v)) for k, v in values.items()})
    except KeyError as e:
        raise InstallRefused(f"template placeholder {e} has no value") from e
    except ValueError as e:
        raise InstallRefused(f"template is malformed: {e}") from e


def expected_env(dry_run: str, layout: Layout, env_file: Path, python: Path) -> dict:
    return {
        "DRY_RUN": dry_run,
        "QUANTT_STATE_DIR": str(layout.state_dir),
        "QUANTT_ENV_FILE": str(env_file),
        # launchd starts jobs with a minimal PATH; the interpreter's own bin
        # first so any `python3` a child process resolves is this one.
        "PATH": f"{python.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
    }


def check_rendered(text: str, job: Job, *, python: Path, layout: Layout,
                   env: dict) -> dict:
    """Parse a rendered plist and check every load-bearing key, or raise.

    The template is read at the TAG, so this is what stops an edited template
    (a changed time, a dropped DRY_RUN key, a different command) from being
    installed without anyone deciding it. Returns the parsed dict.
    """
    try:
        d = plistlib.loads(text.encode())
    except Exception as e:
        raise InstallRefused(f"{job.label}: rendered plist does not parse: {e}") from e
    problems = []

    def want(key, value):
        if d.get(key) != value:
            problems.append(f"{key} is {d.get(key)!r}, expected {value!r}")

    if not job.label.startswith(LABEL_PREFIX):
        problems.append(f"label {job.label} does not start {LABEL_PREFIX}")
    want("Label", job.label)
    want("ProgramArguments", [str(python), *job.args])
    want("WorkingDirectory", str(layout.prod_dir))
    want("EnvironmentVariables", env)
    want("RunAtLoad", False)
    want("StandardOutPath", str(layout.log_dir / f"{job.log_stem}.out.log"))
    want("StandardErrorPath", str(layout.log_dir / f"{job.log_stem}.err.log"))
    sched = d.get("StartCalendarInterval")
    key = lambda x: sorted(x.items())
    got = None
    if isinstance(sched, list) and all(isinstance(x, dict) for x in sched):
        got = sorted((key(x) for x in sched))
    exp = sorted(key(x) for x in job.schedule)
    if got != exp:
        problems.append(f"StartCalendarInterval is {sched!r}, expected {list(job.schedule)!r}")
    extra = set(d) - {"Label", "ProgramArguments", "WorkingDirectory",
                      "EnvironmentVariables", "RunAtLoad", "StandardOutPath",
                      "StandardErrorPath", "StartCalendarInterval"}
    if extra:
        problems.append(f"unexpected keys {sorted(extra)}")
    if problems:
        raise InstallRefused(f"{job.label}: rendered plist fails its checks: "
                             + "; ".join(problems))
    return d


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
    rendered: dict       # label -> plist text


def _copy_verified(src: Path, dest: Path, digest: str) -> None:
    """Copy via a temp name, check the bytes, then rename into place.

    A half-copied parquet under the real name would be read by the sleeve as
    a panel; the rename makes the file appear whole or not at all.
    """
    tmp = dest.with_name(dest.name + ".installing")
    shutil.copyfile(src, tmp)
    got = _sha256(tmp)
    if got != digest:
        tmp.unlink()
        raise InstallRefused(f"copy of {src} -> {tmp} has sha256 {got}, "
                             f"source had {digest}")
    os.replace(tmp, dest)


def build_plan(*, tag: str, env_file: Path, layout: Layout, dev_repo: Path,
               python: Path, armed: bool, load: bool, accept_timezone,
               now_utc: dt.datetime, localtime: Path,
               launchctl: Callable = _real_launchctl) -> Plan:
    """Do every read-only check, then return the steps an install would take.

    Everything that can refuse, refuses HERE, before any step runs: a refusal
    halfway through an install would leave prod in a state no tag describes.
    The steps re-check the few facts that could change between plan and run
    (the checked-out commit, a panel appearing) at the moment they act.
    """
    notes, warnings, steps = [], [], []

    for p in (layout.prod_dir, layout.state_dir):
        if _under(p, layout.old_prod) or _under(layout.old_prod, p):
            raise InstallRefused(f"{p} overlaps the retired IBKR prod "
                                 f"{layout.old_prod}; it is never touched")

    notes.append(check_timezone(system_timezone(localtime), accept_timezone, now_utc))
    warnings += check_env_file(env_file, layout)

    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise InstallRefused(f"--python {python} is not an absolute path to an "
                             f"executable file")
    for d in TCC_PROTECTED:
        if _under(python, layout.home / d):
            warnings.append(f"interpreter {python} is under ~/{d} (macOS "
                            f"privacy-protected); launchd may be refused")

    validate_tag(tag)
    origin_url = _git(["remote", "get-url", "origin"], cwd=dev_repo).strip()
    commit = remote_tag_commit(origin_url, tag)
    local = local_tag_commit(dev_repo, tag)
    if local is None:
        raise InstallRefused(f"tag {tag} is on origin but not in this repo "
                             f"({dev_repo}); `git fetch --tags origin` first")
    if local != commit:
        raise InstallRefused(f"tag {tag} is {commit} on origin but {local} here; "
                             f"a tag must not move after release")
    notes.append(f"release {tag} = commit {commit} (origin {origin_url})")
    missing = missing_at_commit(dev_repo, commit,
                                list(REQUIRED_AT_TAG) + [j.template for j in JOBS])
    if missing:
        raise InstallRefused(f"tag {tag} lacks files the scheduled jobs need: "
                             f"{', '.join(missing)}")

    dry_run = "0" if armed else "1"
    env = expected_env(dry_run, layout, env_file, python)
    rendered = {}
    for job in JOBS:
        tmpl = _git(["show", f"{commit}:{job.template}"], cwd=dev_repo)
        text = render(tmpl, {"TAG": tag, "PYTHON": python, "PROD_DIR": layout.prod_dir,
                             "DRY_RUN": dry_run, "STATE_DIR": layout.state_dir,
                             "ENV_FILE": env_file, "PATH": env["PATH"],
                             "LOG_DIR": layout.log_dir})
        check_rendered(text, job, python=python, layout=layout, env=env)
        rendered[job.label] = text

    # launchd holds the definition it loaded; the file on disk is not re-read
    # until the job is booted out and bootstrapped again. A changed plist on
    # disk for a loaded job without --load would make the file say one thing
    # (say DRY_RUN=1) while launchd runs another (DRY_RUN=0). Refused.
    domain = f"gui/{os.getuid()}"
    loaded = {}
    for job in JOBS:
        loaded[job.label] = launchctl(["print", f"{domain}/{job.label}"]).returncode == 0
        dest = layout.plist_path(job)
        changed = not dest.exists() or dest.read_text() != rendered[job.label]
        if loaded[job.label] and changed and not load:
            raise InstallRefused(
                f"{job.label} is loaded in launchd and its plist would change; "
                f"launchd would keep running the old definition. Re-run with "
                f"--apply --load, or stop it now with the halt file "
                f"(docs/RUNBOOK.md)")

    # -- code
    state = inspect_clone(layout.prod_dir, origin_url)
    prod = layout.prod_dir
    if state == "absent":
        steps.append(Step(f"git clone {origin_url} {prod}",
                          lambda: (prod.parent.mkdir(parents=True, exist_ok=True),
                                   _git(["clone", "--no-checkout", origin_url, str(prod)]))))
    else:
        steps.append(Step(f"git -C {prod} fetch --tags origin (clean clone of origin)",
                          lambda: _git(["fetch", "--tags", "origin"], cwd=prod)))

    def checkout():
        _git(["checkout", "--quiet", "--detach", commit], cwd=prod)
        head = _git(["rev-parse", "HEAD"], cwd=prod).strip()
        if head != commit:
            raise InstallRefused(f"prod HEAD is {head} after checkout, expected {commit}")
    steps.append(Step(f"git -C {prod} checkout --detach {commit}  ({tag}); verify HEAD",
                      checkout))

    # -- data
    data_dir = prod / "data" / "cef"
    for name in SEED_FILES + SEED_SUPPORT:
        src, dest = dev_repo / "data" / "cef" / name, data_dir / name
        if dest.exists():
            steps.append(Step(f"leave {dest} untouched (prod already has it; prod's "
                              f"panels are prod's own)", lambda: None))
            continue
        if not src.is_file():
            raise InstallRefused(f"cannot seed {dest}: source {src} does not exist")
        digest = _sha256(src)

        def seed(src=src, dest=dest, digest=digest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                print(f"  {dest} appeared since planning; left untouched")
                return
            _copy_verified(src, dest, digest)
        steps.append(Step(f"copy {src} -> {dest} ({src.stat().st_size} bytes, "
                          f"sha256 {digest[:12]}...)", seed))

    steps.append(Step(f"verify prod clone is still clean (seeded data is gitignored)",
                      lambda: inspect_clone(prod, origin_url)))

    # -- state
    steps.append(Step(f"mkdir -p {layout.log_dir} (QUANTT_STATE_DIR={layout.state_dir}, mode 700)",
                      lambda: [p.mkdir(mode=0o700, parents=True, exist_ok=True)
                               for p in (layout.state_dir, layout.log_dir)]))

    # -- plists
    for job in JOBS:
        dest = layout.plist_path(job)

        def write(dest=dest, text=rendered[job.label]):
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".installing")
            tmp.write_text(text)
            os.replace(tmp, dest)
        was = ""
        if dest.exists():
            old = plistlib.loads(dest.read_bytes()).get("EnvironmentVariables", {}).get("DRY_RUN")
            was = f", replacing DRY_RUN={old}"
        steps.append(Step(f"write {dest} (DRY_RUN={dry_run}{was})", write))

    # -- launchd
    if load:
        for job in JOBS:
            dest = layout.plist_path(job)

            def reload(job=job, dest=dest, was_loaded=loaded[job.label]):
                if was_loaded:
                    r = launchctl(["bootout", f"{domain}/{job.label}"])
                    if r.returncode != 0:
                        raise InstallRefused(f"launchctl bootout {job.label} failed: "
                                             f"{r.stderr.strip()}")
                r = launchctl(["bootstrap", domain, str(dest)])
                if r.returncode != 0:
                    raise InstallRefused(f"launchctl bootstrap {dest} failed: "
                                         f"{r.stderr.strip()}")
            steps.append(Step(("launchctl bootout + bootstrap " if loaded[job.label]
                               else "launchctl bootstrap ") + f"{domain} {dest}", reload))
    else:
        notes.append("plists are written but NOT loaded (pass --load to load them)")

    if armed:
        warnings.append("ARMED: plists get DRY_RUN=0. A scheduled session also "
                        f"needs {layout.state_dir}/AUTO_ARMED to transmit "
                        f"(docs/RUNNER.md gate 2)")
    return Plan(notes, warnings, steps, rendered)


def main(argv=None, *, layout: Layout | None = None, dev_repo: Path = REPO,
         localtime: Path = Path("/etc/localtime"),
         launchctl: Callable = _real_launchctl, now_utc: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True, help="release tag, already pushed to origin")
    ap.add_argument("--env-file", required=True, type=Path,
                    help="absolute path of the Alpaca key file; never read here")
    ap.add_argument("--apply", action="store_true", help="act (default: dry run)")
    ap.add_argument("--load", action="store_true",
                    help="with --apply: (re)load both jobs into launchd")
    ap.add_argument("--armed", action="store_true",
                    help="render DRY_RUN=0 (default DRY_RUN=1)")
    ap.add_argument("--accept-timezone", default=None, metavar="ZONE",
                    help="accept a non-New_York system zone, named exactly, if "
                         "its offsets equal New York's for two years")
    ap.add_argument("--python", type=Path, default=Path(sys.executable),
                    help="interpreter the jobs run (default: this one)")
    a = ap.parse_args(argv)
    if a.load and not a.apply:
        ap.error("--load needs --apply: loading is what makes a job run")

    layout = layout or Layout(Path.home())
    try:
        plan = build_plan(tag=a.tag, env_file=a.env_file, layout=layout,
                          dev_repo=dev_repo, python=a.python, armed=a.armed,
                          load=a.load, accept_timezone=a.accept_timezone,
                          now_utc=now_utc or dt.datetime.now(dt.timezone.utc),
                          localtime=localtime, launchctl=launchctl)
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
        for label, text in plan.rendered.items():
            print(f"\n----- {layout.agents_dir / (label + '.plist')} (rendered, not written)\n{text}")
        print("\nDRY RUN: nothing was written. Re-run with --apply to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
