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
    for side in ("open", "close"):
        with pytest.raises(F.AuctionFetchError, match="fit verdict is not committed"):
            F.main(["--side", side, "--holdout"])


def test_holdout_fetch_takes_no_sizes():
    with pytest.raises(F.AuctionFetchError, match="no --sizes"):
        F.main(["--side", "open", "--sizes", "--holdout"])


def test_crsp_holdout_stage_refuses_before_any_query_when_uncommitted(monkeypatch):
    from scripts.data import stage_crsp_w4 as S
    monkeypatch.setattr(F, "fit_verdict_committed", lambda *a, **k: (False, "test"))
    with pytest.raises(S.StageError, match="fit verdict is not committed"):
        S.main(["--holdout"])


def test_cefconnect_closes_refuse_when_uncommitted_and_parse_keeps_prices(monkeypatch):
    from scripts.data import fetch_cefconnect_closes as CC
    monkeypatch.setattr(F, "fit_verdict_committed", lambda *a, **k: (False, "test"))
    with pytest.raises(CC.CloseFetchError, match="fit verdict is not committed"):
        CC.main([])
    rows = [{"DataDate": "2025-03-07T00:00:00", "NAVData": None, "Data": 10.5, "DiscountData": None},
            {"DataDate": "2025-03-14T00:00:00", "NAVData": 11.0, "Data": 10.6, "DiscountData": -3.6}]
    d = CC.parse({"rows": rows}, "PDI", "All")
    assert list(d.close_cc) == [10.5, 10.6] and d.ticker.eq("PDI").all() and d.window.eq("All").all()
    with pytest.raises(CC.CloseFetchError, match="share a date"):
        CC.parse({"rows": rows + rows[:1]}, "PDI", "All")
