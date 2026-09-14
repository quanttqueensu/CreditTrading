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


# -- which ops modules reach the broker -----------------------------------

def _write_broker_module(d: Path, name: str, real: bool):
    d.joinpath(name).write_text(
        "from ib_async import IB\n" if real else
        "SEARCH_FOR = 'ib_async'   # a string, not an import\n")


def test_ops_broker_modules_lists_real_importers_only(fake_repo):
    """The README whose "There is no broker here" this used to police is
    archived; the measurement survives, and must still not count a mention."""
    _write_broker_module(fake_repo / "ops", "trader.py", real=True)
    _write_broker_module(fake_repo / "ops", "orient_like.py", real=False)
    rep = M.Report(); M.check_ops_broker_modules(rep)
    assert "trader.py" in rep.findings[0].detail
    assert "orient_like.py" not in rep.findings[0].detail


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


# -- the manifest ----------------------------------------------------------

def _manifest(root: Path, rows: str):
    (root / "docs/INDEX.md").write_text(
        "# Index\n\n## Roles\n\n| role | meaning |\n|---|---|\n"
        "| **canonical** | owns a question |\n| **work-order** | a prompt |\n"
        "| **manifest** | this |\n\n## The index\n\n"
        "| path | role | owns | checked by |\n|---|---|---|---|\n"
        "| `docs/INDEX.md` | manifest | the index | x |\n" + rows)


def test_an_unregistered_document_is_drift(fake_repo):
    """The seventh 'how the system works' document starts life exactly like this."""
    _manifest(fake_repo, "| `docs/SYSTEM.md` | canonical | how it runs | x |\n")
    (fake_repo / "docs/SYSTEM.md").write_text("# System\n")
    (fake_repo / "docs/ANOTHER_OVERVIEW.md").write_text("# How it all works\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:unregistered") == M.DRIFT
    assert "ANOTHER_OVERVIEW" in {f.key: f.detail for f in rep.findings}["manifest:unregistered"]
    (fake_repo / "docs/ANOTHER_OVERVIEW.md").unlink()
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:unregistered") == M.OK


def test_results_and_archive_need_no_row(fake_repo):
    _manifest(fake_repo, "")
    (fake_repo / "results/NOTE_2026-09-13.md").write_text("# dated\n")
    (fake_repo / "_archive/docs").mkdir(parents=True)
    (fake_repo / "_archive/docs/OLD.md").write_text("# old\n")
    (fake_repo / "ops/HALT_book.md").write_text("# halt\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:unregistered") == M.OK


def test_a_ghost_row_is_drift(fake_repo):
    _manifest(fake_repo, "| `docs/MOVED_AWAY.md` | canonical | x | x |\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:ghosts") == M.DRIFT


def test_an_unknown_role_is_drift(fake_repo):
    _manifest(fake_repo, "| `docs/A.md` | authoritative-ish | x | x |\n")
    (fake_repo / "docs/A.md").write_text("# A\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:roles") == M.DRIFT


def test_one_question_two_owners_is_drift(fake_repo):
    _manifest(fake_repo, "| `docs/A.md` | canonical | how it runs | x |\n"
                         "| `docs/B.md` | canonical | How it runs | x |\n")
    (fake_repo / "docs/A.md").write_text("# A\n")
    (fake_repo / "docs/B.md").write_text("# B\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:owners") == M.DRIFT


def test_exact_row_beats_glob_and_two_globs_are_ambiguous(fake_repo):
    (fake_repo / "docs/prompts/sub").mkdir(parents=True)
    (fake_repo / "docs/prompts/README.md").write_text("# index\n")
    (fake_repo / "docs/prompts/sub/W1.md").write_text("# w1\n")
    _manifest(fake_repo, "| `docs/prompts/README.md` | canonical | queue | x |\n"
                         "| `docs/prompts/**/*.md` | work-order | — | x |\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:unregistered") == M.OK
    assert _status(rep, "manifest:ambiguous") == M.OK
    _manifest(fake_repo, "| `docs/prompts/**/*.md` | work-order | — | x |\n"
                         "| `docs/prompts/sub/*.md` | work-order | — | x |\n")
    rep = M.Report(); M.check_manifest(rep)
    assert _status(rep, "manifest:ambiguous") == M.DRIFT


def test_glob_double_star_spans_zero_or_more_directories():
    rx = M._glob_re("docs/prompts/**/*.md")
    assert rx.match("docs/prompts/W1.md")
    assert rx.match("docs/prompts/gamma/G1.md")
    assert not rx.match("docs/other/W1.md")
    assert not M._glob_re(".claude/rules/*.md").match(".claude/rules/sub/x.md")


# -- entry points and pointers ---------------------------------------------

def test_entry_file_must_point_at_orient_and_system(fake_repo):
    (fake_repo / "CLAUDE.md").write_text("Run `python3 -m ops.orient`.\n")
    (fake_repo / "README.md").write_text("`python3 -m ops.orient`, then `docs/SYSTEM.md`.\n")
    rep = M.Report(); M.check_entry_points(rep)
    assert _status(rep, "entry:CLAUDE.md") == M.DRIFT
    assert _status(rep, "entry:README.md") == M.OK
    (fake_repo / "CLAUDE.md").write_text("`python3 -m ops.orient` then `docs/SYSTEM.md`\n")
    rep = M.Report(); M.check_entry_points(rep)
    assert _status(rep, "entry:CLAUDE.md") == M.OK


def test_a_seventh_front_door_is_drift(fake_repo):
    for f in ("CLAUDE.md", "README.md"):
        (fake_repo / f).write_text("ops.orient docs/SYSTEM.md\n## Start here\n")
    (fake_repo / "docs/PROJECT_INTRO.md").write_text("# Intro\n\n**Start here.**\n")
    rep = M.Report(); M.check_entry_points(rep)
    assert _status(rep, "entry:others") == M.DRIFT
    (fake_repo / "docs/PROJECT_INTRO.md").write_text("# Intro\n\nSee README.md.\n")
    rep = M.Report(); M.check_entry_points(rep)
    assert _status(rep, "entry:others") == M.OK


def test_a_dead_pointer_in_an_owner_document_is_drift(fake_repo, monkeypatch):
    monkeypatch.setattr(M, "POINTER_SCOPE", ("docs/SYSTEM.md",))
    (fake_repo / "ops/real.py").write_text("")
    (fake_repo / "docs/SYSTEM.md").write_text(
        "Run `python3 -m ops.real`, read `docs/GONE.md` and `_archive/docs/X.md`.\n")
    rep = M.Report(); M.check_pointers(rep)
    detail = {f.key: f.detail for f in rep.findings}["pointers:docs/SYSTEM.md"]
    assert _status(rep, "pointers:docs/SYSTEM.md") == M.DRIFT
    assert "docs/GONE.md" in detail and "_archive/docs/X.md" in detail
    assert "ops.real" not in detail
    (fake_repo / "docs/SYSTEM.md").write_text("Run `python3 -m ops.real`.\n")
    rep = M.Report(); M.check_pointers(rep)
    assert _status(rep, "pointers:docs/SYSTEM.md") == M.OK


def test_runtime_artefacts_placeholders_and_panels_are_not_dead(fake_repo, monkeypatch):
    """Halts live in prod, ledgers are session output, data/ is gitignored, and
    `<book>` is a placeholder. None is a pointer into this tree."""
    monkeypatch.setattr(M, "POINTER_SCOPE", ("docs/SYSTEM.md",))
    (fake_repo / "docs/SYSTEM.md").write_text(
        "`ops/HALT_phase0.md` `ops/books/cef_live/x.csv` `data/cef/p.parquet` "
        "`ops/books/<book>/_order_map.csv` `config/.env`\n")
    rep = M.Report(); M.check_pointers(rep)
    assert _status(rep, "pointers:docs/SYSTEM.md") == M.OK


def test_a_missing_module_command_is_dead(fake_repo, monkeypatch):
    monkeypatch.setattr(M, "POINTER_SCOPE", ("docs/SYSTEM.md",))
    (fake_repo / "docs/SYSTEM.md").write_text("`python3 -m ops.no_such_tool --check`\n")
    rep = M.Report(); M.check_pointers(rep)
    assert _status(rep, "pointers:docs/SYSTEM.md") == M.DRIFT


# -- citing the archive ------------------------------------------------------

def test_an_unmarked_archive_citation_in_an_owner_document_is_drift(fake_repo):
    """Reads exactly like a live citation, which is the whole danger."""
    (fake_repo / "CLAUDE.md").write_text(
        "Rules.\n\nFor the capture numbers see `_archive/docs/PLAN.md` §3.\n")
    rep = M.Report(); M.check_archive_citations(rep)
    assert _status(rep, "archive:citations") == M.DRIFT
    (fake_repo / "CLAUDE.md").write_text(
        "Rules.\n\nThe archived `_archive/docs/PLAN.md` §3 has the old numbers.\n")
    rep = M.Report(); M.check_archive_citations(rep)
    assert _status(rep, "archive:citations") == M.OK


def test_archive_citation_rules_reach_the_agent_layer(fake_repo):
    (fake_repo / ".claude/skills/x").mkdir(parents=True)
    (fake_repo / ".claude/skills/x/SKILL.md").write_text("Read `_archive/ops/AUTOMATION.md`.\n")
    rep = M.Report(); M.check_archive_citations(rep)
    assert _status(rep, "archive:citations") == M.DRIFT


def test_prompts_other_archive_folders_and_the_index_are_exempt(fake_repo):
    """Work orders may read archived studies; ops/_archive is a different
    folder; the archive's own README is the right thing to point at."""
    (fake_repo / "docs/prompts").mkdir()
    (fake_repo / "docs/prompts/W1.md").write_text("Read `_archive/docs/PLAN.md` §7.1.\n")
    (fake_repo / "docs/SYSTEM.md").write_text(
        "Revert path: `ops/_archive/cef_discount.v5.20260731.frozen.json`.\n"
        "Rules: `_archive/README.md`.\n")
    rep = M.Report(); M.check_archive_citations(rep)
    assert _status(rep, "archive:citations") == M.OK


def test_code_citing_a_moved_document_is_a_note_never_drift(fake_repo):
    """The frozen spec and the live sleeve cite documents in comments and cannot
    be edited casually. Visible backlog, not a failing gate."""
    (fake_repo / "src").mkdir()
    (fake_repo / "_archive/docs").mkdir(parents=True)
    (fake_repo / "_archive/docs/PLAN.md").write_text("old\n")
    (fake_repo / "src/sleeve.py").write_text("# see docs/PLAN.md Part 2\n")
    rep = M.Report(); M.check_code_doc_pointers(rep)
    f = rep.findings[0]
    assert f.status == M.NOTE and "now _archive/" in f.detail
    assert not rep.drift
    (fake_repo / "src/sleeve.py").write_text("# see _archive/docs/PLAN.md Part 2 (archived)\n")
    rep = M.Report(); M.check_code_doc_pointers(rep)
    assert rep.findings[0].status == M.OK


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


# -- spec ids --------------------------------------------------------------

def test_an_old_spec_id_standing_alone_is_drift_anywhere_a_reader_starts(fake_repo, monkeypatch):
    (fake_repo / "ops/specs").mkdir()
    (fake_repo / "ops/specs/cef_discount.frozen.json").write_text(
        '{"spec_id": "cef_discount.v6.20260906"}')
    (fake_repo / "docs/SYSTEM.md").write_text("The sleeve runs cef_discount.v5.20260731.\n")
    rep = M.Report(); M.check_spec_id(rep)
    assert _status(rep, "spec_id:docs/SYSTEM.md") == M.DRIFT
    (fake_repo / "docs/SYSTEM.md").write_text(
        "cef_discount.v6.20260906 replaced cef_discount.v5.20260731.\n")
    rep = M.Report(); M.check_spec_id(rep)
    assert _status(rep, "spec_id:docs/SYSTEM.md") == M.OK


def test_a_spec_id_inside_a_filename_is_not_a_claim(fake_repo):
    (fake_repo / "ops/specs").mkdir()
    (fake_repo / "ops/specs/cef_discount.frozen.json").write_text(
        '{"spec_id": "cef_discount.v6.20260906"}')
    (fake_repo / "docs/SYSTEM.md").write_text(
        "Revert path: `ops/_archive/cef_discount.v5.20260731.frozen.json`.\n")
    rep = M.Report(); M.check_spec_id(rep)
    assert _status(rep, "spec_id:docs/SYSTEM.md") == M.OK
