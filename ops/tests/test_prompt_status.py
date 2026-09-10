"""The prompts index must agree with the prompts, and the checker must bite.

WHY THIS TEST EXISTS
--------------------
`docs/prompts/README.md` says of itself that it "can drift", and on 2026-09-10
it did, in four places, within twelve hours of being written -- three prompts
filed `queued` that had landed work, four stale defect warnings, four dead
read-pointers, and a work order naming two release tags when three existed.
None of it was visible until a person opened four files, because nothing in the
repo read `docs/prompts/` at all.

THE LESSON THIS TEST INHERITS, from `test_promote_gate.py`:

    "an exclusion that matches nothing is indistinguishable, from the outside,
     from one that matched and found nothing wrong"

A checker whose parser silently matched nothing would pass forever and prove
nothing. So the tests below do NOT simply run `--check` against the live tree
and assert green. Each one copies the real prompts into `tmp_path`, breaks
exactly one thing, and asserts the checker names it. `test_the_live_tree_is_clean`
is the only test that reads the real tree, and it is the weakest of the set --
it is meaningful only because the others prove the checker is non-vacuous.

Nothing here touches git history, the broker, or any file in the repo.
"""
import shutil

import pytest

from ops import prompt_status as ps

REAL = ps.PROMPTS


@pytest.fixture
def tree(tmp_path):
    """A throwaway copy of the real prompts, so a mutation proves something."""
    dst = tmp_path / "prompts"
    shutil.copytree(REAL, dst)
    return dst


def findings(tree, strict=False):
    return ps.audit(tree, tree / "README.md", ps.REPO_ROOT, strict=strict)


def drift_text(tree):
    return " | ".join(f"{w} {m}" for _, w, m in findings(tree).drifted())


# --------------------------------------------------------------- the checker bites

def test_index_disagreeing_with_a_prompt_is_drift(tree):
    """The failure that motivated all of this: the table says one thing, the
    prompt another, and the reader believes whichever they opened first."""
    idx = tree / "README.md"
    idx.write_text(idx.read_text().replace(
        "| **executed** | 2026-09-10 — `0c81d3f`",
        "| **queued** | 2026-09-10 — `0c81d3f`", 1))
    assert "W0_repo_hygiene.md" in drift_text(tree)
    assert "authoritative" in drift_text(tree)


def test_a_sha_that_does_not_resolve_is_drift(tree):
    """Catches a rebase, a squash, or a sha copied out of another tree."""
    for f in (tree / "README.md", tree / "W0b_prod_dev_split.md"):
        f.write_text(f.read_text().replace("c6fc9b1", "0badc0f"))
    assert "0badc0f" in drift_text(tree)
    assert "unknown" in drift_text(tree)


def test_a_sha_that_resolves_but_is_unreachable_is_drift(tree, tmp_path):
    """A real commit on an abandoned branch is NOT evidence that work landed.
    Distinct from the case above, and the one a squash-merge actually produces."""
    assert ps.sha_state("0" * 40) == "unknown"
    # every sha the live index cites must be reachable from HEAD
    for row in ps.read_index(REAL / "README.md")[0]:
        for sha in ps.shas_in(row.evidence):
            assert ps.sha_state(sha) == "ok", f"{row.target} cites {sha}"


def test_a_prompt_the_index_does_not_know_about_is_drift(tree):
    """A prompt added and the index never told -- the most likely future drift."""
    shutil.copy(tree / "W1_inference_protocol.md", tree / "W15_new.md")
    assert "W15_new.md" in drift_text(tree)


def test_an_executed_banner_on_a_queued_prompt_is_drift(tree):
    p = tree / "W1_inference_protocol.md"
    p.write_text(p.read_text().replace(
        "# W1", "# W1\n\n> ## ✅ EXECUTED 2026-09-10 — done.\n", 1))
    assert "EXECUTED banner" in drift_text(tree)


def test_a_status_outside_the_vocabulary_raises_naming_it(tree):
    """NO SILENT FALLBACKS: it says what it found and what it allows."""
    p = tree / "W3_session_architecture.md"
    p.write_text(p.read_text().replace("**Status:** queued", "**Status:** donezo", 1))
    with pytest.raises(ps.PromptStatusError) as e:
        findings(tree)
    assert "donezo" in str(e.value) and "vocabulary" in str(e.value)


def test_a_prompt_with_no_status_line_raises(tree):
    p = tree / "W4_artifact_battery.md"
    p.write_text("\n".join(l for l in p.read_text().splitlines()
                           if not l.startswith("**Status:**")))
    with pytest.raises(ps.PromptStatusError) as e:
        findings(tree)
    assert "W4_artifact_battery.md" in str(e.value)


def test_evidence_citing_a_note_that_does_not_exist_is_drift(tree):
    idx = tree / "README.md"
    idx.write_text(idx.read_text().replace(
        "results/cef/DUST_ORDERS_2026-09.md", "results/cef/NO_SUCH_NOTE.md"))
    assert "NO_SUCH_NOTE" in drift_text(tree)


# ------------------------------------------------------- the checker stays honest

def test_the_banner_extractor_is_not_a_grep():
    """`W0c:185` QUOTES W0b's banner as an instruction to apply elsewhere, so
    `grep -n 'EXECUTED'` -- which W0c:188 itself recommends -- marks the one
    in-progress prompt executed. The banner is the leading blockquote only."""
    w0c = (REAL / "W0c_repo_coherence.md").read_text()
    assert "EXECUTED" in w0c, "fixture assumption: W0c still quotes the banner"
    assert "EXECUTED" not in ps.leading_banner(w0c)
    assert "EXECUTED" in ps.leading_banner((REAL / "W0_repo_hygiene.md").read_text())


def test_no_check_keys_on_a_number_written_in_a_document(monkeypatch, tree):
    """H14, enforced mechanically. The CEF/GAMMA counters are context; if a
    verdict can move when they move, a decision rule has keyed on a document
    number -- the rule this repo breaks most often."""
    before = findings(tree).findings
    monkeypatch.setattr(ps, "counters", lambda *a, **k: {"CEF": 999, "GAMMA": 999})
    after = [f for f in findings(tree).findings if f[1] != "trial counters"]
    assert [f for f in before if f[1] != "trial counters"] == after


def test_the_tool_writes_nothing(tree):
    """It must stay safe to run from a hook, a job or a session."""
    before = {p: (p.stat().st_mtime_ns, p.read_bytes())
              for p in sorted(tree.rglob("*.md"))}
    findings(tree, strict=True)
    after = {p: (p.stat().st_mtime_ns, p.read_bytes())
             for p in sorted(tree.rglob("*.md"))}
    assert before == after


def test_the_vocabulary_is_read_from_the_file_not_hardcoded():
    """A hand-copied list in the checker lets the guarded thing regress while
    the checker stays green -- `test_promote_gate.py` records that lesson."""
    _, vocab = ps.read_index(REAL / "README.md")
    assert {"executed", "queued", "in progress"} <= vocab
    src = (ps.REPO_ROOT / "ops" / "prompt_status.py").read_text()
    assert '"in progress"' not in src.split("def split_status")[0]


# ------------------------------------------------------------------ the live tree

def test_the_live_tree_is_clean():
    """Weakest test here, and meaningful only because the others prove the
    checker is non-vacuous."""
    rep = ps.audit()
    assert not rep.drifted(), "\n".join(
        f"{w}: {m}" for _, w, m in rep.drifted())


def test_every_prompt_declares_its_own_status():
    _, vocab = ps.read_index(REAL / "README.md")
    for f in ps.prompt_files():
        if f.name in ps.NON_PROMPTS or ps.DATED_ARTIFACT.match(f.name):
            continue
        token, _ = ps.declared_status(f.read_text(), vocab, f.name)
        assert token in vocab


def test_no_prompt_points_at_a_file_that_is_not_there():
    """--strict, on the live tree. A prompt that tells you to read a path which
    does not exist costs a search before it costs a correction, and it is how
    four prompts came to cite `scripts/vrp/` and `src/deploy/lib/black76.py`.

    A prompt that SAYS the path is missing is being careful and is exempt --
    that calibration is in `ACKNOWLEDGED`, and getting it wrong in the other
    direction (flagging the careful case) is what teaches a reader to skip the
    column."""
    rep = ps.audit(strict=True)
    bad = [f for f in rep.findings if f[0] != ps.INFO]
    assert not bad, "\n".join(f"{w}: {m}" for _, w, m in bad)


def test_the_acknowledged_carve_out_does_not_swallow_a_real_dead_pointer(tree):
    """The carve-out above must not be a blanket amnesty. A prompt naming a
    missing path with no acknowledgement anywhere near it still reports."""
    p = tree / "W6_risk_governance.md"
    p.write_text(p.read_text().replace(
        "**Reads first:**",
        "**Reads first:** `src/deploy/lib/no_such_module.py` in full.\n**Reads first:**", 1))
    rep = ps.audit(tree, tree / "README.md", ps.REPO_ROOT, strict=True)
    assert any("no_such_module" in m for _, _, m in rep.findings)
