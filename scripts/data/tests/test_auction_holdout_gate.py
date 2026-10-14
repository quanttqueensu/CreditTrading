"""The `--holdout` gate of `fetch_alpaca_auction_history.py` (trial C5, DG-C5-6).

WHY: PREREG_C5_OPEN_AUCTION_2026-10-13 seals the 2023-01-03 -> 2026-09-30
opening prints until C5's fit verdict is committed, so a result that the
holdout can only kill is on the record before the holdout is read. The gate is
a git check on `results/cef/c5/C5_FIT_VERDICT.json`; these tests run it against a
throwaway local repository (no network: the root conftest blocks sockets) and
check that the fetcher refuses BEFORE it builds a client.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.data import fetch_alpaca_auction_history as F


def _git(repo: Path, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README").write_text("x")
    _git(tmp_path, "add", "README")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_gate_refuses_missing_untracked_and_modified_then_passes_when_committed(tmp_path):
    repo = _repo(tmp_path)
    rel = F.FIT_VERDICT
    ok, why = F.fit_verdict_committed(repo, rel)
    assert not ok and "does not exist" in why
    (repo / rel).parent.mkdir(parents=True)
    (repo / rel).write_text('{"verdict": "x"}')
    ok, why = F.fit_verdict_committed(repo, rel)
    assert not ok and "not in HEAD" in why
    _git(repo, "add", rel.as_posix())
    _git(repo, "commit", "-q", "-m", "fit verdict")
    assert F.fit_verdict_committed(repo, rel) == (True, "committed")
    (repo / rel).write_text('{"verdict": "edited after the commit"}')
    ok, why = F.fit_verdict_committed(repo, rel)
    assert not ok and "differs from HEAD" in why


def test_holdout_fetch_refuses_before_any_client_when_uncommitted(monkeypatch):
    monkeypatch.setattr(F, "fit_verdict_committed", lambda *a, **k: (False, "test"))
    with pytest.raises(F.AuctionFetchError, match="fit verdict is not committed"):
        F.main(["--side", "open", "--holdout"])


def test_holdout_fetch_is_opening_side_only():
    with pytest.raises(F.AuctionFetchError, match="opening prints only"):
        F.main(["--side", "close", "--holdout"])
    with pytest.raises(F.AuctionFetchError, match="opening prints only"):
        F.main(["--side", "open", "--sizes", "--holdout"])
