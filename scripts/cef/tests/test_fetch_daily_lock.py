"""fetch_daily's panel lock: the read-modify-write of the price and NAV panels is exclusive.

WHY. Since 2026-09-29 two processes run `scripts/cef/fetch_daily.py` against the
same panels: the trading session and the nightly collector (`quantt/collect`).
Each reads both panels, fetches for minutes, then replaces them. Interleaved,
the second writer silently drops the first writer's rows. These tests pin that
the whole read-modify-write happens under the lock, that a held lock makes a
second run wait a BOUNDED time and then exit 3 naming the lock without touching
the panels, and that a free lock is taken and released.

Hermetic: every path is monkeypatched into tmp_path, the fetch body is replaced,
and no network is reached (the root conftest's netguard would refuse it).
"""
import fcntl
import os

import pytest

from scripts.cef import fetch_daily as fd


def _held_elsewhere(path) -> bool:
    """True if some other open file description holds an exclusive flock on path."""
    probe = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(probe)       # closing releases the probe's own lock, if it got one
    return False


@pytest.fixture
def paths(tmp_path, monkeypatch):
    px = tmp_path / "cef_prices.parquet"
    px.write_bytes(b"stand-in; the body that reads it is replaced")
    monkeypatch.setattr(fd, "PX_PATH", px)
    monkeypatch.setattr(fd, "LOCK_PATH", tmp_path / ".fetch.lock")
    monkeypatch.setattr(fd, "LOCK_POLL_S", 0.02)
    return tmp_path


def test_refresh_holds_the_lock_for_the_whole_read_modify_write(paths, monkeypatch):
    seen = {}

    def body(period, require_asof, nav_fallback, book):
        seen["held"] = _held_elsewhere(fd.LOCK_PATH)
        return 0

    monkeypatch.setattr(fd, "_refresh_locked", body)
    assert fd.refresh() == 0
    assert seen == {"held": True}, "the panel read/write ran without the lock held"
    assert not _held_elsewhere(fd.LOCK_PATH), "the lock was not released afterwards"


def test_a_held_lock_is_a_bounded_wait_then_exit_3_naming_it(paths, monkeypatch, capsys):
    monkeypatch.setattr(fd, "LOCK_WAIT_S", 0.2)

    def body(*a):
        raise AssertionError("the panels were read although another fetch holds the lock")

    monkeypatch.setattr(fd, "_refresh_locked", body)
    other = os.open(fd.LOCK_PATH, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(other, fcntl.LOCK_EX)
        os.write(other, b"pid 424242 since test")
        rc = fd.main(["--require-asof", "2026-09-29"])
    finally:
        os.close(other)
    out = capsys.readouterr().out
    assert rc == fd.EXIT_LOCKED == 3
    assert str(fd.LOCK_PATH) in out and "pid 424242" in out


def test_the_lock_is_free_again_after_the_holder_releases(paths, monkeypatch):
    monkeypatch.setattr(fd, "_refresh_locked", lambda *a: 4)
    other = os.open(fd.LOCK_PATH, os.O_RDWR | os.O_CREAT)
    fcntl.flock(other, fcntl.LOCK_EX)
    os.close(other)                      # a dead holder's lock goes with its fd
    assert fd.refresh() == 4             # the body's own exit code passes through


def test_no_staged_panel_still_exits_1_without_creating_a_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "PX_PATH", tmp_path / "absent.parquet")
    monkeypatch.setattr(fd, "LOCK_PATH", tmp_path / ".fetch.lock")
    assert fd.refresh() == 1
    assert not (tmp_path / ".fetch.lock").exists()
