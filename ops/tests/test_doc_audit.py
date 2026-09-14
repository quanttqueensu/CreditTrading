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


# -- the archive wall ------------------------------------------------------

BANNER = ("> **ARCHIVED 2026-09-13 — not evidence of current state.** "
          "Was `{origin}`.\n> Now owned by: `docs/SYSTEM.md`.\n")


def _wall(root: Path, rows=("_archive/docs/",)):
    """A minimal archive that passes every brick of the wall."""
    (root / ".gitignore").write_text("# wall\n/_archive/\n")
    (root / "_archive/docs").mkdir(parents=True)
    (root / "_archive/README.md").write_text(
        "# index\n\n| path | was |\n|---|---|\n"
        + "".join(f"| `{r}` | x |\n" for r in rows))
    (root / "_archive/docs/OLD.md").write_text(
        BANNER.format(origin="docs/OLD.md") + "\n# Old\nBody.\n")


def _status(rep, key):
    return {f.key: f.status for f in rep.findings}[key]


def test_the_minimal_wall_passes(fake_repo):
    _wall(fake_repo)
    rep = M.Report(); M.check_archive_wall(rep)
    assert not rep.drift, [(f.key, f.detail) for f in rep.drift]


def test_archive_wall_requires_the_ignore_line(fake_repo):
    """Without it every archived body is searchable again, and nothing else
    would say so -- the folder still looks like an archive."""
    _wall(fake_repo)
    (fake_repo / ".gitignore").write_text("# wall\n# /_archive/  (commented out)\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:ignore") == M.DRIFT
    (fake_repo / ".gitignore").write_text("/_archive/\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:ignore") == M.OK


def test_an_archived_file_git_is_not_tracking_is_drift(fake_repo):
    """The ignore line hides a NEW file from `git add -A`, so an archive move
    done with plain `mv` would look finished and live on one machine."""
    import subprocess
    _wall(fake_repo)
    git = lambda *a: subprocess.run(["git", *a], cwd=fake_repo, check=True,
                                    capture_output=True)
    git("init", "-q")
    git("add", "-A")
    git("add", "-f", "_archive")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:tracked") == M.OK
    (fake_repo / "_archive/docs/NEW.md").write_text(
        BANNER.format(origin="docs/NEW.md") + "Body.\n")
    git("add", "-A")                      # the command that silently skips it
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:tracked") == M.DRIFT
    git("add", "-f", "_archive/docs/NEW.md")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:tracked") == M.OK


def test_archive_wall_requires_a_banner(fake_repo):
    """Glob is not walled, so the banner is what a reader who opens a listed
    path meets first."""
    _wall(fake_repo)
    (fake_repo / "_archive/docs/OLD.md").write_text("# Old\nStraight to the body.\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:banners") == M.DRIFT


def test_archive_banner_must_name_its_mirror_path(fake_repo):
    _wall(fake_repo)
    (fake_repo / "_archive/docs/OLD.md").write_text(
        BANNER.format(origin="docs/SOMETHING_ELSE.md") + "Body.\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:mirror") == M.DRIFT


def test_a_snapshot_must_be_of_a_document_that_still_exists(fake_repo):
    _wall(fake_repo)
    snap = ("> **ARCHIVED 2026-09-13 — not evidence of current state.** "
            "Snapshot of `docs/LIVE.md` at `abc1234`.\n")
    (fake_repo / "_archive/docs/LIVE_2026-09-13.md").write_text(snap + "Body.\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:mirror") == M.DRIFT
    (fake_repo / "docs/LIVE.md").write_text("# Live, trimmed\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:mirror") == M.OK


def test_archive_wall_rejects_a_nested_claude_md(fake_repo):
    """Claude Code auto-loads a nested CLAUDE.md for files in its subtree -- a
    verbatim snapshot under that name would re-issue a superseded rulebook."""
    _wall(fake_repo)
    (fake_repo / "_archive/CLAUDE.md").write_text(
        BANNER.format(origin="CLAUDE.md") + "old rules\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:nested_claude") == M.DRIFT
    (fake_repo / "_archive/CLAUDE.md").unlink()
    (fake_repo / "_archive/.claude/agents").mkdir(parents=True)
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:nested_claude") == M.DRIFT


def test_an_unindexed_binary_is_drift(fake_repo):
    """A PDF cannot carry a banner, so its row in the index is its only label."""
    _wall(fake_repo, rows=("_archive/docs/OLD.md",))
    (fake_repo / "_archive/docs/deck.pdf").write_bytes(b"%PDF-1.4")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:index") == M.DRIFT
    readme = fake_repo / "_archive/README.md"
    readme.write_text(readme.read_text() + "| `_archive/docs/deck.pdf` | x |\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:index") == M.OK


def test_live_code_may_not_import_from_the_archive(fake_repo):
    _wall(fake_repo)
    (fake_repo / "ops/uses_old.py").write_text("from _archive.ops import old\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:imports") == M.DRIFT
    (fake_repo / "ops/uses_old.py").write_text("PATH = '_archive/ops/old.py'  # a string\n")
    rep = M.Report(); M.check_archive_wall(rep)
    assert _status(rep, "archive:imports") == M.OK


def test_the_real_sentinel_token_exists_only_in_the_archive():
    """The wall's verification searches for this token with no path. If it is
    ever copied outside `_archive/` -- into a test, a note, this file -- that
    search stops meaning anything, so the token is read, never spelled."""
    sentinel = REPO / "_archive/ARCHIVE_WALL_SENTINEL.md"
    token = next(ln.strip() for ln in sentinel.read_text().splitlines()
                 if ln.startswith("    ") and ln.strip())
    outside = []
    for p in REPO.rglob("*"):
        rel = p.relative_to(REPO)
        if (p.is_dir() or rel.parts[0] in ("_archive", ".git", "data")
                or "__pycache__" in rel.parts or p.stat().st_size > 2_000_000):
            continue
        try:
            if token in p.read_text(errors="ignore"):
                outside.append(str(rel))
        except OSError:
            continue
    assert not outside, f"sentinel token copied outside _archive/: {outside}"


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
