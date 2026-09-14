"""Every check in doc_audit must be able to FAIL. Otherwise it is decoration.

WHY THIS FILE EXISTS
--------------------
Twice in one session a test in this repo passed under the exact regression it
was written to catch: `test_panel_is_invariant_to_truncation` re-derived its
targets from the same panel it was checking, and
`test_invalid_option_transmits_nothing_at_all` exercised a validator rather
than the wiring that calls it. A document-audit tool is unusually prone to the
same fault, because "everything is fine" is its happy path and an audit that
can never say otherwise looks identical to one that has nothing to report.

So each test below constructs the defect and asserts the check SEES it, then
constructs the fix and asserts the check stops seeing it. Both directions,
every time.

`_opens_ib_socket` gets its own test for a specific reason: the hand-maintained
count in `ops/README.md` drifted because a grep for "ib_insync" matches
`ops/orient.py`, which contains that string only as a literal it searches OTHER
files for. Grep counted it as a broker module. The AST does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doc_audit as M  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "ops").mkdir()
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(M, "REPO", tmp_path)
    return tmp_path


# -- banners ---------------------------------------------------------------

def test_banner_check_fails_on_a_document_with_no_banner(fake_repo, monkeypatch):
    p = fake_repo / "docs/NOBANNER.md"
    p.write_text("# A document\n\nStraight into the body with no warning.\n")
    monkeypatch.setattr(M, "BANNERED", ["docs/NOBANNER.md"])
    rep = M.Report(); M.check_banners(rep)
    assert [f.status for f in rep.findings] == [M.DRIFT]

    p.write_text("# A document\n\n> **⚠ CORRECTED 2026-09-13 — stale.**\n\nBody.\n")
    rep = M.Report(); M.check_banners(rep)
    assert [f.status for f in rep.findings] == [M.OK]


def test_banner_must_be_near_the_top_not_merely_present(fake_repo, monkeypatch):
    """A banner 200 lines down is not a banner. CLAUDE.md records exactly this:
    PER_NAME_ARCHITECTURE's real warning sat 120 lines below the header."""
    buried = "# Doc\n" + "filler\n" * 200 + "> **⚠ CORRECTED — stale.**\n"
    (fake_repo / "docs/BURIED.md").write_text(buried)
    monkeypatch.setattr(M, "BANNERED", ["docs/BURIED.md"])
    rep = M.Report(); M.check_banners(rep)
    assert rep.findings[0].status == M.DRIFT


# -- the "no broker here" claim -------------------------------------------

def _write_broker_module(d: Path, name: str, real: bool):
    d.joinpath(name).write_text(
        "from ib_async import IB\n" if real else
        "SEARCH_FOR = 'ib_async'   # a string, not an import\n")


def test_ops_broker_check_distinguishes_assertion_from_retraction(fake_repo):
    _write_broker_module(fake_repo / "ops", "trader.py", real=True)

    (fake_repo / "ops/README.md").write_text(
        "# ops\n\n**There is no broker here.** Nothing can place an order.\n")
    rep = M.Report(); M.check_ops_broker_claim(rep)
    assert rep.findings[0].status == M.DRIFT

    (fake_repo / "ops/README.md").write_text(
        "# ops\n\n**⚠ RETRACTED 2026-09-13 — this said \"There is no broker "
        "here\" and it is false.**\n")
    rep = M.Report(); M.check_ops_broker_claim(rep)
    assert rep.findings[0].status == M.OK


def test_opens_ib_socket_is_ast_not_grep(fake_repo):
    """The exact false positive that drifted the hand-maintained count."""
    ops = fake_repo / "ops"
    _write_broker_module(ops, "real_broker.py", real=True)
    _write_broker_module(ops, "mentions_only.py", real=False)
    assert M._opens_ib_socket(ops / "real_broker.py") is True
    assert M._opens_ib_socket(ops / "mentions_only.py") is False


def test_opens_ib_socket_survives_an_unparseable_file(fake_repo):
    p = fake_repo / "ops/broken.py"
    p.write_text("def f(:\n")
    assert M._opens_ib_socket(p) is False


# -- preregs ---------------------------------------------------------------

def test_prereg_falsifier_check_fails_on_a_prereg_with_none(fake_repo):
    p = fake_repo / "results/PREREG_EMPTY.md"
    p.write_text("# Pre-registration\n\nWe will do the thing. It will work.\n")
    rep = M.Report(); M.check_prereg_shape(rep)
    assert rep.findings[0].status == M.DRIFT

    p.write_text("# Pre-registration\n\nWe will do the thing.\n\n"
                 "## Known reasons this could fail, stated in advance\n"
                 "If the holdout coefficient drops below half, abandon it.\n")
    rep = M.Report(); M.check_prereg_shape(rep)
    assert rep.findings[0].status == M.OK


def test_a_prereg_is_not_asked_for_a_reproducer(fake_repo):
    """It precedes its own run, so it cannot cite output that does not exist."""
    (fake_repo / "results/PREREG_X.md").write_text("# Prereg\n\nNo script here.\n")
    (fake_repo / "results/MEASURED_X.md").write_text("# Note\n\nNo script here.\n")
    rep = M.Report(); M.check_results_notes_have_reproducers(rep)
    by = {f.key: f for f in rep.findings}
    assert "PREREG_X.md" not in by["results_reproducers"].detail
    assert "MEASURED_X.md" in by["results_reproducers"].detail
    assert by["results_reproducers"].status == M.NOTE


# -- the severity split ----------------------------------------------------

def test_note_does_not_fail_the_gate_but_drift_does(fake_repo):
    rep = M.Report()
    rep.add("a", M.NOTE, "a standing backlog")
    assert rep.drift == [] and len(rep.notes) == 1
    rep.add("b", M.DRIFT, "a contradiction")
    assert len(rep.drift) == 1


def test_the_real_repo_has_no_drift():
    """The whole point. If this fails, a document contradicts the repo."""
    rep = M.run()
    assert not rep.drift, "\n".join(f"{f.key}: {f.detail}" for f in rep.drift)
