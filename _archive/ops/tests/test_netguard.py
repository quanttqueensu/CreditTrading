"""The safety harness is actually in force, for every way out it claims to close.

`ops/netguard.py` and the root `conftest.py` are the reason later tests are
allowed to drive `run_book.main` and build an `IBKRBroker`. A guard that is
believed and absent is worse than none, so each one is exercised here through
the same surface a careless test would use: a socket, `subprocess`, a panel
write, a halt alert.

EVERY TEST HERE IS SAFE WITH ITS GUARD REMOVED. That is a design constraint,
not a nicety: the named mutation for this file is "remove the guard and watch
the test go red", and a test that proves `launchctl bootout` is blocked by
RUNNING it unguarded would unload a live trading job to make its point. So:

  * sockets only ever aim at a loopback port measured closed a moment before;
  * subprocess tests replace `Popen._execute_child` -- the one place a child
    is actually spawned -- with a raiser first, so nothing executes whether or
    not the argv guard fires;
  * panel-write tests hand `atomic_write` a fake frame whose `to_parquet`
    raises, so no byte reaches a disk whether or not the path guard fires;
  * the alert test asserts the recorder is installed BEFORE it calls it.

The recorded red runs are in
`results/ops/hardening_2026-09-21/failing_first/test_netguard.mutation.txt`.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ops.common  # noqa: E402
import ops.halt as halt  # noqa: E402
from ops import netguard  # noqa: E402
from ops.common import atomic_write as atomic_write_bound_at_import  # noqa: E402
from ops.netguard import NetGuardViolation  # noqa: E402


@pytest.fixture
def closed_port():
    """A loopback port nothing listens on: bound to 0, read back, closed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# -- netguard ---------------------------------------------------------------

def test_netguard_is_active_under_pytest():
    """MUTATION: `install()` body -> `return`."""
    assert netguard.is_active()


@pytest.mark.usefixtures("expects_netguard_refusal")
def test_connect_raises(closed_port):
    """MUTATION: `_guarded_connect` body -> `return None`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(NetGuardViolation, match="socket.connect to"):
            s.connect(("127.0.0.1", closed_port))


@pytest.mark.usefixtures("expects_netguard_refusal")
def test_connect_ex_raises_rather_than_returning_an_errno(closed_port):
    """A caller of connect_ex reads non-zero as "nothing listening"; the guard
    must not hand it that reading.

    MUTATION: `_guarded_connect_ex` body -> `return 61`.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(NetGuardViolation, match="connect_ex"):
            s.connect_ex(("127.0.0.1", closed_port))


@pytest.mark.usefixtures("expects_netguard_refusal")
def test_create_connection_raises_before_any_name_is_resolved():
    """The address is a name under the reserved `.invalid` TLD. If the guard
    were behind the resolver the failure would be a gaierror, not ours.

    MUTATION: `_guarded_create_connection` body -> `raise OSError("refused")`.
    """
    with pytest.raises(NetGuardViolation, match="create_connection"):
        socket.create_connection(("gateway.synthetic.invalid", 4002), timeout=1)


@pytest.mark.usefixtures("expects_netguard_refusal")
def test_asyncio_open_connection_raises(closed_port):
    """The route `ib_async` takes: the event loop's sock_connect calls
    `sock.connect` on a `socket.socket`.

    MUTATION: `_guarded_connect` body -> `return None`.
    """
    async def _open():
        await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", closed_port), timeout=5)

    with pytest.raises(NetGuardViolation):
        asyncio.run(_open())


@pytest.mark.usefixtures("expects_netguard_refusal")
def test_a_refusal_is_recorded_even_if_the_caller_swallows_it(closed_port):
    """`ops.preflight.check_broker` and `ops.halt._email` catch Exception, so
    the raise alone would be invisible there.

    MUTATION: delete the `_VIOLATIONS.append` line in `_refuse`.
    """
    before = len(netguard.violations())
    try:
        socket.create_connection(("127.0.0.1", closed_port), timeout=1)
    except Exception:
        pass
    new = netguard.violations()[before:]
    assert new == (("socket.create_connection", ("127.0.0.1", closed_port)),)


def test_only_undeclared_refusals_reach_the_end_of_run_report(harness,
                                                              monkeypatch):
    """The report must be empty on a healthy run, or nobody reads it: the
    tests above trip the guard on purpose and say so with a fixture. Synthetic
    records; nothing is connected.

    MUTATION (conftest.py): `if not expected:` -> `if expected:`.
    """
    monkeypatch.setattr(netguard, "_VIOLATIONS", [
        ("socket.connect", ("synthetic.invalid", 1)),
        ("socket.connect", ("synthetic.invalid", 2)),
        ("socket.create_connection", ("synthetic.invalid", 3)),
    ])
    monkeypatch.setattr(harness, "_REFUSED_IN", {
        0: ("tests/declared.py::test_a", True),
        1: ("tests/swallowed.py::test_b", False),
    })
    assert harness._unexpected_refusals() == [
        ("socket.connect", ("synthetic.invalid", 2),
         "tests/swallowed.py::test_b"),
        ("socket.create_connection", ("synthetic.invalid", 3),
         "outside any test (collection or a fixture)"),
    ]


def test_is_active_is_measured_not_remembered(monkeypatch):
    """One entry point put back by a stray monkeypatch must read as inactive.

    MUTATION: `is_active()`: `return all(` -> `return True or all(`.
    """
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **kw: None)
    assert not netguard.is_active()
    monkeypatch.undo()
    assert netguard.is_active()


# -- subprocess -------------------------------------------------------------

class _WouldHaveSpawned(Exception):
    """Raised INSTEAD of spawning. Reaching it means the argv guard let the
    command through to the point where a child would have been created."""


@pytest.fixture
def no_child_can_spawn(monkeypatch):
    def _execute_child(self, args, *a, **kw):
        raise _WouldHaveSpawned(list(args))

    monkeypatch.setattr(subprocess.Popen, "_execute_child", _execute_child)
    assert subprocess.Popen._execute_child is _execute_child
    return _execute_child


# A label that exists on no machine, so that even a spawn could not matter.
_BOOTOUT = ["launchctl", "bootout", "gui/0/com.quantt.synthetic-not-a-job"]

_CALLERS = ["run", "call", "check_call", "check_output", "Popen"]


@pytest.mark.parametrize("caller", _CALLERS)
def test_launchctl_bootout_raises(harness, no_child_can_spawn, caller):
    """MUTATION (conftest.py): delete the `_install_subprocess_guard()` call.
    Second mutation: add "bootout" to LAUNCHCTL_READ_ONLY_VERBS."""
    with pytest.raises(harness.SubprocessGuardViolation, match="bootout"):
        getattr(subprocess, caller)(_BOOTOUT)


@pytest.mark.parametrize("caller", _CALLERS)
def test_launchctl_list_passes_through_to_the_stub(no_child_can_spawn, caller):
    """The guard must not break the read-only verbs `ops.doctor` depends on.

    MUTATION: remove "list" from LAUNCHCTL_READ_ONLY_VERBS.
    """
    with pytest.raises(_WouldHaveSpawned) as e:
        getattr(subprocess, caller)(["launchctl", "list"])
    assert e.value.args[0] == ["launchctl", "list"]


@pytest.mark.parametrize("argv", [
    ["launchctl", "load", "-w", "/synthetic/com.quantt.synthetic.plist"],
    ["launchctl", "unload", "/synthetic/com.quantt.synthetic.plist"],
    ["launchctl", "bootstrap", "gui/0", "/synthetic/x.plist"],
    ["launchctl", "kickstart", "-k", "gui/0/com.quantt.synthetic-not-a-job"],
    ["launchctl", "enable", "gui/0/com.quantt.synthetic-not-a-job"],
    ["launchctl", "disable", "gui/0/com.quantt.synthetic-not-a-job"],
    ["launchctl"],
    ["/bin/launchctl", "bootout", "gui/0/com.quantt.synthetic-not-a-job"],
    ["sh", "-c", "launchctl list && launchctl bootout gui/0/synthetic"],
    "launchctl list | grep quantt; launchctl bootout gui/0/synthetic",
    [sys.executable, "-m", "src.deploy.run_book", "--dry-run"],
    [sys.executable, "src/deploy/run_book.py", "--asof", "2000-01-03"],
    [sys.executable, "/synthetic/Application Support/quantt/launch_job.py",
     "cef"],
    [b"launchctl", b"bootout", b"gui/0/synthetic"],
])
def test_every_order_path_argv_raises(harness, no_child_can_spawn, argv):
    """MUTATION: `_check_argv` body -> `return`."""
    with pytest.raises(harness.SubprocessGuardViolation):
        subprocess.run(argv, shell=isinstance(argv, str))


@pytest.mark.parametrize("argv", [
    ["launchctl", "print", "gui/0/com.quantt.synthetic-not-a-job"],
    ["launchctl", "print-disabled", "gui/0"],
    "launchctl list | grep quantt",
    ["git", "status", "--porcelain"],
])
def test_read_only_argv_reaches_the_spawn_point(no_child_can_spawn, argv):
    """MUTATION: LAUNCHCTL_READ_ONLY_VERBS -> frozenset()."""
    with pytest.raises(_WouldHaveSpawned):
        subprocess.run(argv, shell=isinstance(argv, str))


def test_guarded_popen_is_still_a_popen(harness):
    """Replacing the class with a function would break isinstance checks and
    subclasses in whatever imports subprocess after us.

    MUTATION: `class _GuardedPopen(subprocess.Popen)` -> `(object)`.
    """
    assert subprocess.Popen is harness._GuardedPopen
    real = harness._GuardedPopen.__mro__[1]
    assert (real.__module__, real.__name__) == ("subprocess", "Popen")
    assert harness._tripwires_in_force() == []


# -- atomic_write -----------------------------------------------------------

class _WouldHaveWritten(Exception):
    """Raised INSTEAD of writing. Reaching it means the path guard let the
    target through to the point where bytes would have gone to disk."""


class _FrameThatCannotWrite:
    def to_parquet(self, path, **kw):
        raise _WouldHaveWritten(str(path))

    def to_csv(self, path, **kw):
        raise _WouldHaveWritten(str(path))


def test_the_name_a_fetcher_binds_is_the_wrapper(harness):
    """Why the wrap happens at conftest IMPORT: `from ops.common import
    atomic_write` at the top of this file ran during collection, exactly as it
    does in `scripts/cef/fetch_daily.py`.

    MUTATION (conftest.py): delete `_common.atomic_write = _guarded_atomic_write`.
    """
    assert atomic_write_bound_at_import is harness._guarded_atomic_write
    assert ops.common.atomic_write is harness._guarded_atomic_write


@pytest.mark.parametrize("name", ["cef_prices.parquet", "cef_nav.parquet",
                                  "cef_distributions.parquet", "any.csv"])
def test_atomic_write_under_every_guarded_root_raises(harness, name):
    """The real `data/` of the main dev tree, this tree's `data/`, and prod --
    each in both its written and its resolved spelling.

    MUTATION: `_refuse_guarded_target` body -> `return`.
    """
    assert harness.GUARDED_WRITE_ROOTS
    for root in harness.GUARDED_WRITE_ROOTS:
        with pytest.raises(harness.PanelWriteGuard, match="live panel"):
            atomic_write_bound_at_import(_FrameThatCannotWrite(),
                                         root / "cef" / name)


def test_the_main_dev_trees_data_is_a_guarded_root(harness):
    """From a linked worktree the dangerous directory is NOT this tree's
    `data/` (there is none) but the main tree's, which prod symlinks to.

    MUTATION: delete `_ROOTS_AS_WRITTEN.append(MAIN_TREE / "data")`.
    """
    if harness.MAIN_TREE is None:
        pytest.skip("no .git here (an export): the main tree is not derivable")
    assert harness.MAIN_TREE / "data" in harness.GUARDED_WRITE_ROOTS
    with pytest.raises(harness.PanelWriteGuard):
        atomic_write_bound_at_import(
            _FrameThatCannotWrite(),
            harness.MAIN_TREE / "data" / "cef" / "cef_prices.parquet")


def test_prods_symlinked_spelling_is_caught(harness):
    """`~/prod/QUANTT/data/...` is the dev panel under another name.

    MUTATION: drop `PROD_TREE` from `_ROOTS_AS_WRITTEN`.
    """
    with pytest.raises(harness.PanelWriteGuard):
        atomic_write_bound_at_import(
            _FrameThatCannotWrite(),
            harness.PROD_TREE / "data" / "cef" / "cef_nav.parquet")


def test_atomic_write_to_tmp_path_passes_through(tmp_path):
    """MUTATION: make `_refuse_guarded_target` raise unconditionally."""
    with pytest.raises(_WouldHaveWritten) as e:
        atomic_write_bound_at_import(_FrameThatCannotWrite(),
                                     tmp_path / "p.parquet")
    assert e.value.args[0] == str(tmp_path / "p.parquet") + ".tmp"


def test_the_prod_root_does_not_follow_HOME(harness, monkeypatch, tmp_path):
    """The plan's R9 runs tests under `env HOME=<scratch>/emptyhome`; a guard
    built on `Path.home()` would then protect the scratch dir, not prod.

    MUTATION: `_real_home()` body -> `return Path.home()`.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    assert Path.home() == tmp_path
    assert harness._real_home() != tmp_path
    assert harness.PROD_TREE == harness._real_home() / "prod" / "QUANTT"


def test_the_main_tree_is_read_from_dot_git(harness, tmp_path):
    """MUTATION: `return Path(*parts[:parts.index(".git")])` -> `return repo`."""
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n")
    export = tmp_path / "export"
    export.mkdir()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_text("not a gitdir line\n")

    assert harness._main_worktree(main) == main
    assert harness._main_worktree(linked) == main
    assert harness._main_worktree(export) is None
    with pytest.raises(harness.HarnessMisconfigured, match="gitdir"):
        harness._main_worktree(broken)


# -- the panel hash -----------------------------------------------------------

def test_a_changed_panel_is_reported_and_fails_the_session(harness, monkeypatch,
                                                           tmp_path):
    """Synthetic bytes in tmp_path; no real panel is read or touched.

    MUTATION: delete `session.exitstatus = pytest.ExitCode.TESTS_FAILED`.
    """
    panel = tmp_path / "cef_prices.parquet"
    panel.write_bytes(b"synthetic panel bytes, before")
    before = {panel: harness._sha256(panel)}
    panel.write_bytes(b"synthetic panel bytes, AFTER")
    after = {panel: harness._sha256(panel)}

    assert harness._panel_changes(before, before) == []
    assert len(harness._panel_changes(before, after)) == 1
    assert "MISSING" in harness._panel_changes(before, {})[0]
    assert "created during the run" in harness._panel_changes({}, after)[0]

    class _Session:
        exitstatus = 0

    monkeypatch.setattr(harness, "_PANEL_HASHES_AT_START", before)
    monkeypatch.setattr(harness, "_PANEL_CHANGES", [])
    monkeypatch.setattr(harness, "_hash_panels", lambda: after)
    session = _Session()
    harness.pytest_sessionfinish(session, 0)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED

    monkeypatch.setattr(harness, "_hash_panels", lambda: before)
    session = _Session()
    harness.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0


# -- the alert recorder -------------------------------------------------------

def test_the_alert_recorder_records(harness, alerts):
    """MUTATION (conftest.py): delete `_halt.alert = _recording_alert`.

    The identity assert comes FIRST so that with the recorder missing this
    test fails before it can call the real `alert`.
    """
    assert halt.alert is harness._recording_alert
    out = halt.alert("synthetic subject", body="synthetic body", speak="x")
    assert list(alerts) == [{"subject": "synthetic subject",
                             "body": "synthetic body", "speak": "x"}]
    assert set(out) == {"notification", "email", "speech"}
    assert True not in out.values(), "a recorded alert must never read as delivered"


def test_real_alert_runs_the_real_code_against_stubs_only(real_alert,
                                                          monkeypatch, alerts):
    """The one opt-out. It must reach neither a process nor a mail server.

    MUTATION: in `real_alert`, delete the `monkeypatch.setattr(smtplib, ...)`
    line -> the real SMTP client is built, netguard refuses its connect, and
    `emails` stays empty.
    """
    synthetic = {"ALERT_SMTP_USER": "synthetic@example.invalid",
                 "ALERT_SMTP_PASS": "synthetic-not-a-password",
                 "ALERT_EMAIL_TO": "nobody@example.invalid",
                 "ALERT_SMTP_HOST": "smtp.synthetic.invalid",
                 "ALERT_SMTP_PORT": "587"}
    monkeypatch.setattr(halt, "_cfg", lambda k, d=None: synthetic.get(k, d))

    out = halt.alert("synthetic subject", body="synthetic body", speak="hello")

    assert out == {"notification": True, "speech": True, "email": True}
    assert [c[0] for c in real_alert.commands] == ["osascript", "say"]
    assert len(real_alert.emails) == 1
    assert real_alert.emails[0]["To"] == "nobody@example.invalid"
    assert len(alerts) == 0, "the recorder was bypassed, as asked"


# -- the session fixture ------------------------------------------------------

def test_the_environment_points_at_nothing(harness):
    """MUTATION: `mp.setenv("EXECUTION", "simulator")` -> `"ibkr"`."""
    assert os.environ["EXECUTION"] == "simulator"
    port = int(os.environ["IBKR_PORT"])
    assert port not in harness.IBKR_DEFAULT_PORTS


def test_doctor_reads_an_empty_launchagents_not_this_machines():
    """MUTATION: delete `mp.setattr(doctor, "AGENTS", empty_agents)`."""
    from ops import doctor

    assert doctor.AGENTS.is_dir()
    assert list(doctor.AGENTS.iterdir()) == []
    assert "Library" not in doctor.AGENTS.parts
    assert doctor._plist_start_minutes("cef") is None
