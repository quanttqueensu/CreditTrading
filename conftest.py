"""Suite-wide safety harness. Every test in every testpath runs under this.

WHY THIS EXISTS
---------------
`python3 -m pytest` is the safest-looking command in the repo, and it has
already reached for the order path once: `scripts/audit/moc_routing_test.py`
opens a live broker connection at import and a bare collection imported it
(`pytest.ini` tells that story). Scoping collection fenced off that one file.
Before 2026-09-21 nothing fenced off the general case: there was no conftest
at the root, so whether a test could touch the world depended on each author
remembering not to. What a test process on this machine can reach when one
forgets:

  * a socket to anything (`ops.preflight.check_broker` probes the configured
    gateway port; `ops.halt._email` speaks SMTP);
  * a real macOS notification, a spoken phrase and a real email, because
    `ops.halt.write_halt` and `clear_halt` call `alert()`;
  * launchd, through `launchctl`, and a live session, through a child process
    running `launch_job.py` or `src.deploy.run_book`;
  * THIS MACHINE's `~/Library/LaunchAgents`, so a verdict changes when the
    installed schedule does and no code has;
  * a price panel. `~/prod/QUANTT/data` is a symlink into the main dev tree's
    `data/`, so a fetcher's write path called with the module's default
    target rewrites what the live sleeve prices from.

MEASURED 2026-09-21, the first full run under this file. No existing test
tripped netguard, the subprocess guard or the panel-write guard, and none
reached the alert recorder: every author had remembered. The exception was
LaunchAgents. With `ops.doctor.AGENTS` pointed at an empty directory,
`src/deploy/tests/test_decision_age_clock.py` went from three failures to
eight -- five tests had been passing only because of what happened to be
installed here -- and two tests that read the installed schedule on purpose
took their own `pytest.skip` branch: the red one in
`ops/tests/test_stuck_session_guard.py` and a green one in
`ops/tests/test_session_deadline.py`. Making those hermetic is hardening step
2.1.1 (WS1), with explicit fixture plists; it is not done by loosening item 6
below.

The hardening workstreams that follow this one add tests that drive
`run_book.main` and construct `IBKRBroker`. They are only allowed to because
this file makes the dangerous outcomes impossible rather than unlikely.

WHAT IS INSTALLED, AND WHEN
---------------------------
At IMPORT of this file -- before collection imports a single test module,
because the incident this descends from happened during collection:

  1. `ops.netguard.install()`: no connection opens, to any destination.
  2. `ops.common.atomic_write` is wrapped so a target under a live panel
     directory raises `PanelWriteGuard`. At import, so that a later
     `from ops.common import atomic_write` in a fetcher binds the WRAPPER; a
     fixture would run after those names were already bound to the real one.
  3. `subprocess.run/call/check_call/check_output/Popen` are wrapped to raise
     `SubprocessGuardViolation` on any `launchctl` verb other than
     list/print/print-disabled, and on any argv naming `launch_job.py` or
     `src.deploy.run_book` (the three things that can start a live session
     from a child process, where netguard cannot see).
  4. `ops.halt.alert` is replaced by a recorder (`ALERTS`). Nothing a test
     does notifies, speaks or emails. The recorder's return value is
     deliberately never `True` for any channel, so no code under test can read
     a recorded alert as a delivered one.

In the session-scoped autouse fixture -- the parts that need a tmp dir or
should be undone at the end:

  5. EXECUTION=simulator and IBKR_PORT=<a port measured closed>. A second
     layer under netguard: if some path does build a broker config from the
     environment, it is pointed at nothing.
  6. `ops.doctor.AGENTS` points at an EMPTY directory, so a test that has not
     supplied its own fixture plist gets "no plist installed" (in
     `ops.decision_age`, DecisionAgeUnknown) instead of a verdict that depends
     on this machine's schedule.
  7. Asserts 1-4 are still in force.

At session start and finish the three live CEF panels are hashed; a change
fails the run (see `pytest_sessionfinish`).

IF A TEST BREAKS UNDER THIS
---------------------------
Make the test hermetic. Do not widen a guard, add an allowlist, or add an
off switch. The single sanctioned opt-out is the `real_alert` fixture, and it
installs its own subprocess and SMTP stubs before it hands the real `alert`
back, so it cannot be used to reach a person.

WHAT THIS IS NOT
----------------
A sandbox. `os.system`, `os.exec*`, `os.posix_spawn`, a write that does not go
through `atomic_write`, and anything in a C extension are not covered. It
catches the honest mistake, which is the only kind this repo has made.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pwd
import shlex
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import netguard  # noqa: E402

# 1. FIRST, before ops.common drags in numpy/pandas and everything after it.
netguard.install()

import ops.common as _common  # noqa: E402
import ops.halt as _halt  # noqa: E402


class HarnessMisconfigured(RuntimeError):
    """The harness could not establish what it is supposed to protect."""


class PanelWriteGuard(RuntimeError):
    """A test tried to `atomic_write` into a live panel directory."""


class SubprocessGuardViolation(RuntimeError):
    """A test tried to start a child process that can reach the order path."""


# ---------------------------------------------------------------------------
# What is protected
# ---------------------------------------------------------------------------

def _real_home() -> Path:
    """The account's home from the password database, NOT from $HOME.

    The plan's hermeticity check (R9) runs part of this suite under
    `env HOME=<scratch>/emptyhome`. `Path.home()` follows $HOME, so under that
    run a guard built on it would protect `<scratch>/emptyhome/prod/QUANTT`
    and leave the real prod tree open.
    """
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _main_worktree(repo: Path):
    """The repo's MAIN working tree, whose `data/` prod prices from.

    Prod's `data` is a symlink into the main dev tree (CLAUDE.md, landmine 9),
    so that directory must be guarded from whichever worktree the suite runs
    in. A linked worktree's `.git` is a FILE reading
    `gitdir: <main>/.git/worktrees/<name>`; the main tree's `.git` is a
    directory. Read from the file rather than by running `git`, so this costs
    no subprocess at import and works with git absent.

    Returns None only when there is no `.git` at all (a `git archive` export,
    which the plan's no-op proofs run tests inside). That case is STATED in
    the run header, not hidden: this tree's own `data/` is still guarded
    through its resolved path, so an export whose `data` is a symlink to the
    dev panels is covered. A `.git` that exists and cannot be read as either
    shape raises.
    """
    dotgit = repo / ".git"
    if dotgit.is_dir():
        return repo
    if not dotgit.exists():
        return None
    text = dotgit.read_text().strip()
    if not text.startswith("gitdir:"):
        raise HarnessMisconfigured(
            f"{dotgit} is a file but does not start with 'gitdir:'; cannot "
            f"locate the main working tree whose data/ must be guarded")
    gitdir = Path(text.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = repo / gitdir
    parts = gitdir.parts
    if ".git" not in parts:
        raise HarnessMisconfigured(
            f"{dotgit} names gitdir {gitdir}, which has no '.git' component; "
            f"cannot locate the main working tree whose data/ must be guarded")
    return Path(*parts[:parts.index(".git")])


MAIN_TREE = _main_worktree(REPO)
PROD_TREE = _real_home() / "prod" / "QUANTT"

# Each root is held both as written and resolved: prod's data/ is a symlink,
# and a target can arrive in either spelling.
_ROOTS_AS_WRITTEN = [REPO / "data", PROD_TREE]
if MAIN_TREE is not None:
    _ROOTS_AS_WRITTEN.append(MAIN_TREE / "data")
GUARDED_WRITE_ROOTS = tuple(dict.fromkeys(
    Path(p) for root in _ROOTS_AS_WRITTEN
    for p in (os.path.abspath(root), os.path.realpath(root))))

PANEL_NAMES = ("cef_prices.parquet", "cef_nav.parquet",
               "cef_distributions.parquet")


def _panel_paths() -> tuple:
    """The live CEF panels to hash: this tree's and the main tree's, de-duped
    by resolved path (they are the same files when this IS the main tree)."""
    trees = [REPO] + ([MAIN_TREE] if MAIN_TREE is not None else [])
    seen = {}
    for tree in trees:
        for name in PANEL_NAMES:
            p = Path(os.path.realpath(tree / "data" / "cef" / name))
            seen.setdefault(p, None)
    return tuple(seen)


# ---------------------------------------------------------------------------
# 2. atomic_write
# ---------------------------------------------------------------------------

_REAL_ATOMIC_WRITE = _common.atomic_write


def _refuse_guarded_target(path) -> None:
    spellings = {Path(os.path.abspath(path)), Path(os.path.realpath(path))}
    for target in spellings:
        for root in GUARDED_WRITE_ROOTS:
            if target == root or root in target.parents:
                raise PanelWriteGuard(
                    f"atomic_write target {str(path)!r} resolves under "
                    f"{root}, a live panel directory (prod's data/ is a "
                    f"symlink into the main dev tree). A test writes to "
                    f"tmp_path; monkeypatch the module's path constants.")


@functools.wraps(_REAL_ATOMIC_WRITE)
def _guarded_atomic_write(frame, path, *args, **kwargs):
    _refuse_guarded_target(path)
    return _REAL_ATOMIC_WRITE(frame, path, *args, **kwargs)


_common.atomic_write = _guarded_atomic_write


# ---------------------------------------------------------------------------
# 3. subprocess
# ---------------------------------------------------------------------------

LAUNCHCTL_READ_ONLY_VERBS = frozenset({"list", "print", "print-disabled"})
FORBIDDEN_ARGV_SUBSTRINGS = ("launch_job.py", "src.deploy.run_book",
                             "src/deploy/run_book.py")


def _argv_tokens(args) -> list:
    """Flatten whatever subprocess was given into a list of shell words.

    `args` may be a string (shell=True), a sequence, bytes or PathLike
    entries. A token that itself contains whitespace is split again, so
    `["sh", "-c", "launchctl bootout gui/501/x"]` is seen for what it runs.
    """
    if isinstance(args, (str, bytes, os.PathLike)):
        args = [args]
    out = []
    for a in args:
        text = os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a)
        try:
            words = shlex.split(text)
        except ValueError:
            # Unbalanced quotes: shlex cannot say where the words end. Split on
            # whitespace and drop the quote characters, so `'launchctl` still
            # reads as launchctl. More tokens than shlex would give, which can
            # only make the check below refuse more, not less.
            words = [w.strip("'\"") for w in text.split()]
        out.extend(words or [text])
    return out


def _check_argv(args) -> None:
    tokens = _argv_tokens(args)
    for tok in tokens:
        for needle in FORBIDDEN_ARGV_SUBSTRINGS:
            if needle in tok:
                raise SubprocessGuardViolation(
                    f"subprocess argv names {needle!r} ({tokens!r}). That "
                    f"starts a live session from a child process, where "
                    f"netguard cannot see. Call the function in-process "
                    f"under the harness, or stub subprocess.")
    for i, tok in enumerate(tokens):
        if os.path.basename(tok) != "launchctl":
            continue
        verb = tokens[i + 1] if i + 1 < len(tokens) else None
        if verb not in LAUNCHCTL_READ_ONLY_VERBS:
            raise SubprocessGuardViolation(
                f"subprocess would run `launchctl {verb}` ({tokens!r}). Only "
                f"{sorted(LAUNCHCTL_READ_ONLY_VERBS)} are allowed under test: "
                f"every other verb changes what launchd runs on this machine, "
                f"and what launchd runs is what trades.")


def _args_of(a, kw):
    if a:
        return a[0]
    if "args" in kw:
        return kw["args"]
    raise SubprocessGuardViolation(
        "subprocess called with no args; the harness cannot check what it "
        "would run")


def _guard_function(real):
    @functools.wraps(real)
    def guarded(*a, **kw):
        _check_argv(_args_of(a, kw))
        return real(*a, **kw)
    guarded._quantt_guarded = True
    return guarded


class _GuardedPopen(subprocess.Popen):
    """A subclass, not a function, so `isinstance(p, subprocess.Popen)` and
    subclassing keep working for whatever imports it after us. run/call/
    check_call/check_output all construct `Popen` by its module-global name,
    so this also sits under them; they are wrapped as well because a test may
    stub `Popen` alone."""
    _quantt_guarded = True

    def __init__(self, *a, **kw):
        _check_argv(_args_of(a, kw))
        super().__init__(*a, **kw)


_SUBPROCESS_FUNCTIONS = ("run", "call", "check_call", "check_output")


def _install_subprocess_guard() -> None:
    for name in _SUBPROCESS_FUNCTIONS:
        real = getattr(subprocess, name)
        if not getattr(real, "_quantt_guarded", False):
            setattr(subprocess, name, _guard_function(real))
    if not getattr(subprocess.Popen, "_quantt_guarded", False):
        subprocess.Popen = _GuardedPopen


_install_subprocess_guard()


# ---------------------------------------------------------------------------
# 4. ops.halt.alert
# ---------------------------------------------------------------------------

_REAL_ALERT = _halt.alert
ALERTS: list = []
_RECORDED = "recorded by the test harness, not delivered"


def _recording_alert(subject: str, body: str = "", speak: str = "") -> dict:
    """Stands in for `ops.halt.alert` for the whole run.

    Same signature and the same keys in the return value, so callers that read
    `delivered.get("email")` (ops.verify_session) keep working -- but no
    channel is ever `True`, because nobody was told anything.
    """
    ALERTS.append({"subject": subject, "body": body, "speak": speak})
    out = {"notification": _RECORDED, "email": _RECORDED}
    if speak:
        out["speech"] = _RECORDED
    return out


_halt.alert = _recording_alert


def _tripwires_in_force() -> list:
    """Names of any import-time guard that is no longer in place."""
    missing = []
    if not netguard.is_active():
        missing.append("ops.netguard")
    if _common.atomic_write is not _guarded_atomic_write:
        missing.append("ops.common.atomic_write wrapper")
    for name in _SUBPROCESS_FUNCTIONS + ("Popen",):
        if not getattr(getattr(subprocess, name), "_quantt_guarded", False):
            missing.append(f"subprocess.{name} guard")
    return missing


# ---------------------------------------------------------------------------
# 5-7. the session fixture
# ---------------------------------------------------------------------------

IBKR_DEFAULT_PORTS = frozenset({4001, 4002, 7496, 7497})


def _a_closed_port() -> int:
    """A loopback port that was free a moment ago: bind to 0, read it, close.

    Measured, not chosen: any literal written here is a guess about what this
    machine listens on. bind() is not connect(), so netguard allows it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    if port in IBKR_DEFAULT_PORTS:
        raise HarnessMisconfigured(
            f"the kernel handed back {port}, an IBKR default port; refusing "
            f"to point IBKR_PORT at it")
    return port


@pytest.fixture(scope="session", autouse=True)
def _quantt_safety_harness(tmp_path_factory):
    missing = _tripwires_in_force()
    if missing:
        raise HarnessMisconfigured(
            f"safety harness not in force at session start: {missing}")
    if _halt.alert is not _recording_alert:
        raise HarnessMisconfigured(
            "ops.halt.alert is not the recorder at session start")

    import ops.doctor as doctor

    empty_agents = tmp_path_factory.mktemp("empty_LaunchAgents")
    mp = pytest.MonkeyPatch()
    mp.setenv("EXECUTION", "simulator")
    mp.setenv("IBKR_PORT", str(_a_closed_port()))
    mp.setattr(doctor, "AGENTS", empty_agents)
    try:
        yield
    finally:
        mp.undo()


# index into netguard.violations() -> the test it happened in, and whether
# that test had said it was going to trip the guard on purpose.
_REFUSED_IN: dict = {}


@pytest.fixture
def expects_netguard_refusal():
    """Declares that this test trips netguard ON PURPOSE (the tests of the
    guard itself). Its refusals are left out of the end-of-run report, so that
    report is empty on a healthy run and every line in it means something."""


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    start = len(netguard.violations())
    yield
    expected = "expects_netguard_refusal" in getattr(item, "fixturenames", ())
    for i in range(start, len(netguard.violations())):
        _REFUSED_IN[i] = (item.nodeid, expected)


@pytest.fixture
def harness():
    """This module, so a test can name `harness.PanelWriteGuard`, read
    `harness.ALERTS`, etc. without importing `conftest` by name (which breaks
    the day a second top-level conftest exists)."""
    return sys.modules[__name__]


@pytest.fixture
def alerts():
    """The alerts recorded DURING this test (the run-wide list is
    `harness.ALERTS`)."""
    start = len(ALERTS)

    class _View:
        def __iter__(self):
            return iter(ALERTS[start:])

        def __len__(self):
            return len(ALERTS) - start

        def __getitem__(self, i):
            return ALERTS[start:][i]

    return _View()


@pytest.fixture
def real_alert(monkeypatch):
    """Opt out of the alert recorder -- for a test OF `ops.halt.alert` itself.

    Usable only with the delivery channels stubbed, and that is enforced by
    construction rather than by asking: this fixture replaces the `subprocess`
    name inside `ops.halt` (osascript, say) and `smtplib.SMTP` with recorders
    BEFORE it puts the real `alert` back. Returns the record:
    `.commands` is every argv the real code tried to run, `.emails` every
    message it tried to send.
    """
    import smtplib
    import types

    rec = types.SimpleNamespace(commands=[], emails=[])

    def _run(argv, *a, **kw):
        rec.commands.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    class _SMTP:
        def __init__(self, host, port, timeout=None):
            self.where = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            rec.emails.append(msg)

    monkeypatch.setattr(_halt, "subprocess", types.SimpleNamespace(run=_run))
    monkeypatch.setattr(smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(_halt, "alert", _REAL_ALERT)
    return rec


# ---------------------------------------------------------------------------
# The panel hash, and the run header
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_panels() -> dict:
    return {p: _sha256(p) for p in _panel_paths() if p.exists()}


def _panel_changes(before: dict, after: dict) -> list:
    """One line per panel whose bytes differ between two `_hash_panels()`
    readings: changed, vanished, or created. Pure, so it can be tested without
    touching a panel."""
    changes = []
    for path, was in before.items():
        now = after.get(path)
        if now != was:
            changes.append(f"{path}: {was[:16]} -> "
                           f"{now[:16] if now else 'MISSING'}")
    for path, now in after.items():
        if path not in before:
            changes.append(f"{path}: absent at start -> {now[:16]} "
                           f"(created during the run)")
    return changes


_PANEL_HASHES_AT_START: dict = {}
_PANEL_CHANGES: list = []


def pytest_sessionstart(session):
    _PANEL_HASHES_AT_START.clear()
    _PANEL_HASHES_AT_START.update(_hash_panels())


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Fail the run if a live panel changed while it was running.

    The write guard covers `atomic_write`; this covers every other way a file
    can change (a bare `to_parquet`, a child process, a fetcher imported by
    mistake). It cannot tell a test's write from a SCHEDULED fetch that
    happened to land during the run -- the launchd jobs legitimately refresh
    the price and NAV panels -- so the message says to check for one. Failing
    on a coincidence is the cheap error; passing over a test that rewrote what
    the sleeve prices from is not.
    """
    _PANEL_CHANGES[:] = _panel_changes(_PANEL_HASHES_AT_START, _hash_panels())
    if _PANEL_CHANGES:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_report_header(config):
    main = (str(MAIN_TREE) if MAIN_TREE is not None else
            "NOT DERIVABLE (no .git here): only this tree's data/ and prod "
            "are write-guarded")
    hashed = ", ".join(f"{p.name}={h[:16]}"
                       for p, h in _PANEL_HASHES_AT_START.items())
    # Measured here, not asserted: the header must not say "on" from memory.
    missing = _tripwires_in_force()
    return [
        f"quantt harness: netguard active={netguard.is_active()}; "
        f"alert recorder installed={_halt.alert is _recording_alert}; "
        f"import-time guards missing={missing or 'none'}",
        f"quantt harness: main tree {main}; write-guarded roots "
        f"{[str(r) for r in GUARDED_WRITE_ROOTS]}",
        f"quantt harness: panels hashed at start: "
        f"{hashed or 'NONE PRESENT (nothing to compare at finish)'}",
    ]


def _unexpected_refusals() -> list:
    """(entry_point, address, where) for every refusal NOT made by a test that
    declared `expects_netguard_refusal`. A refusal with no test on record
    happened during collection or in a fixture, and says so."""
    nowhere = ("outside any test (collection or a fixture)", False)
    out = []
    for i, (what, address) in enumerate(netguard.violations()):
        where, expected = _REFUSED_IN.get(i, nowhere)
        if not expected:
            out.append((what, address, where))
    return out


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    if _PANEL_CHANGES:
        tr.section("LIVE PANEL CHANGED DURING THE TEST RUN", sep="!")
        for line in _PANEL_CHANGES:
            tr.write_line(line)
        tr.write_line(
            "The run is FAILED. Either a test wrote a live panel, or a "
            "scheduled fetch landed during the run: check ops/schedule/logs "
            "in both trees for a fetch in this window before re-running.")
    unexpected = _unexpected_refusals()
    if unexpected:
        tr.section("netguard: connection attempts refused during this run")
        for what, address, where in unexpected:
            tr.write_line(f"{what} -> {address!r}   in {where}")
        tr.write_line(
            "Each was blocked. One whose test still passed was swallowed by "
            "the code under test: that test is reading 'refused' as 'nothing "
            "listening' and should stub the probe instead.")
