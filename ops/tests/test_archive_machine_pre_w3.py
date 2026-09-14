"""The machine-side archive must never move what launchd runs, or move early.

It operates on ~/Library, outside every other guard in this repo, so each
refusal it makes is pinned here against a fake home in tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import archive_machine_pre_w3 as am  # noqa: E402

PRE_W3 = ("PID\tStatus\tLabel\n-\t0\tcom.quantt.cef.daily\n"
          "-\t0\tcom.quantt.awake\n65356\t0\tcom.quantt.ibgateway\n")
W3_LIVE = PRE_W3 + "-\t0\tcom.quantt.cef_pm\n"


def _home(tmp_path):
    support, agents = tmp_path / "quantt", tmp_path / "LaunchAgents"
    support.mkdir()
    agents.mkdir()
    for n in ("launch_job.py", "launch_job.py.bak-20260913-212735"):
        (support / n).write_text(n)
    for n in ("com.quantt.cef.daily.plist", "com.quantt.cef.daily.plist.bak-20260913",
              "com.quantt.book.daily.plist", "com.quantt.cef_pm.plist",
              "com.quantt.awake.plist", "com.quantt.ibgateway.plist"):
        (agents / n).write_text(n)
    return support, agents


def test_dry_run_moves_nothing(tmp_path):
    support, agents = _home(tmp_path)
    assert am.main([], support=support, agents=agents, listing=W3_LIVE) == 0
    assert (support / "launch_job.py.bak-20260913-212735").exists()


def test_apply_refuses_until_w3_is_loaded(tmp_path):
    """The .bak is the evening scheduler's rollback copy."""
    support, agents = _home(tmp_path)
    assert am.main(["--apply"], support=support, agents=agents,
                   listing=PRE_W3) == 2
    assert (support / "launch_job.py.bak-20260913-212735").exists()


def test_apply_moves_backups_and_unloaded_plists_only(tmp_path):
    support, agents = _home(tmp_path)
    assert am.main(["--apply"], support=support, agents=agents,
                   listing=W3_LIVE) == 0
    left = sorted(p.name for p in agents.iterdir())
    assert left == ["com.quantt.awake.plist", "com.quantt.cef.daily.plist",
                    "com.quantt.cef_pm.plist", "com.quantt.ibgateway.plist"]
    assert (support / "launch_job.py").exists()
    [dest] = list((support / "_archive").iterdir())
    manifest = (dest / "MANIFEST.txt").read_text()
    assert "restore: mv" in manifest and "book.daily" in manifest
    assert (dest / "quantt" / "launch_job.py.bak-20260913-212735").exists()


def test_an_unreadable_launchctl_refuses_rather_than_treating_all_as_unloaded():
    with pytest.raises(RuntimeError, match="no labels"):
        am.loaded_labels("PID\tStatus\tLabel\n")
