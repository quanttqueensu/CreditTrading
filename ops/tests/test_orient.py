"""`ops.orient` replaces remembered numbers with measured ones. So it must not
invent one, and it must not die trying.

WHY THIS FILE EXISTS
--------------------
An orientation tool has a failure mode worse than being absent: being confidently
wrong. It is the first thing a new agent runs, its output looks authoritative,
and every number in it is about to be quoted. The two properties that matter are
therefore not "does it produce a number" but:

  1. when it CANNOT measure something, it says so by name and produces no value
     (the repo's NO SILENT FALLBACKS rule, applied to a report rather than a
     calculation);
  2. one broken section does not take the other eight down with it.

The `ib_insync` check gets the most tests because it is the one whose prescribed
recipe was provably unable to express the property it checked. `CLAUDE.md` says
to run

    grep -rn '^ *from ib_insync' ops/ src/ scripts/ | grep -v ImportError

and asserts the answer is zero. On 2026-09-11 that grep returned 5 and the true
answer was 2 — the `except ImportError:` that makes an import safe is on a
different LINE from the import, so the filter filters nothing. Three imports are
correctly guarded and two are not. `.claude/rules/live-order-path.md` says "Two
legacy scripts still import it; do not add a third", which is the reading this
check must reproduce.

NO NETWORK, NO BROKER, NO PROD TREE. The classifier tests build Python source in
`tmp_path`; the degradation tests point the module's constants at paths that do
not exist.
"""
from __future__ import annotations

import json

import pytest

from ops import orient


def _src(tmp_path, rel: str, body: str):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ------------------------------------------------- the ib_insync classifier --
class TestIbInsyncClassifier:
    def test_guarded_fallback_is_not_flagged(self, tmp_path):
        """The safe shape, as `src/deploy/broker/ibkr.py:333` writes it."""
        _src(tmp_path, "ops/x.py", "def f():\n"
                                   "    try:\n"
                                   "        from ib_async import IB, util\n"
                                   "    except ImportError:\n"
                                   "        from ib_insync import IB, util\n")
        assert orient._unguarded_ib_insync(tmp_path) == []

    def test_bare_try_without_an_ib_async_preference_is_flagged(self, tmp_path):
        """THE REAL DEFECT, and the one the grep cannot see: `try:` alone does
        not help. ib_insync still hangs on Python 3.12+; nothing falls back."""
        _src(tmp_path, "scripts/y.py", "def f():\n"
                                       "    try:\n"
                                       "        from ib_insync import IB\n"
                                       "    except ImportError:\n"
                                       "        return 1\n")
        assert orient._unguarded_ib_insync(tmp_path) == ["scripts/y.py:3"]

    def test_top_level_import_is_flagged(self, tmp_path):
        _src(tmp_path, "src/z.py", "from ib_insync import IB\n")
        assert orient._unguarded_ib_insync(tmp_path) == ["src/z.py:1"]

    def test_plain_import_statement_is_flagged_too(self, tmp_path):
        """`import ib_insync` hangs exactly the same as `from ib_insync import`,
        and a pattern written for one spelling misses the other."""
        _src(tmp_path, "src/z.py", "import ib_insync\n")
        assert orient._unguarded_ib_insync(tmp_path) == ["src/z.py:1"]

    def test_the_grep_in_claude_md_would_disagree(self, tmp_path):
        """Pins WHY this is an AST walk. Both files below match
        `^ *from ib_insync` and neither contains 'ImportError' on that line, so
        the documented grep counts 2. Exactly one is actually unsafe."""
        _src(tmp_path, "ops/good.py", "def f():\n"
                                      "    try:\n"
                                      "        from ib_async import IB\n"
                                      "    except ImportError:\n"
                                      "        from ib_insync import IB\n")
        _src(tmp_path, "ops/bad.py", "def f():\n"
                                     "    from ib_insync import IB\n")
        assert orient._unguarded_ib_insync(tmp_path) == ["ops/bad.py:2"]

    def test_syntax_error_in_one_file_does_not_hide_the_rest(self, tmp_path):
        _src(tmp_path, "ops/broken.py", "def f( :\n")
        _src(tmp_path, "ops/bad.py", "from ib_insync import IB\n")
        assert orient._unguarded_ib_insync(tmp_path) == ["ops/bad.py:1"]

    def test_matches_the_live_tree_and_the_rule_file(self):
        """Against the real repo. `.claude/rules/live-order-path.md` says two
        legacy scripts still import it; if a third appears, this fails and the
        rule file is what needs updating — deliberately, not by accident."""
        assert len(orient._unguarded_ib_insync()) == 2


# ------------------------------------------------------ honest degradation --
class TestNeverInventsAndNeverDies:
    def test_a_broken_section_is_named_not_skipped(self, monkeypatch):
        def boom():
            raise RuntimeError("panel fetch exploded")
        monkeypatch.setattr(orient, "panels", boom)
        monkeypatch.setattr(orient, "SECTIONS",
                            [("PANELS", boom), ("TRIALS", orient.trials)])
        d = orient.collect(run_tests=False)
        assert "UNMEASURED" in d["sections"]["PANELS"]
        assert "panel fetch exploded" in d["sections"]["PANELS"]["UNMEASURED"]
        assert "UNMEASURED" not in d["sections"]["TRIALS"], (
            "one broken section must not take the others down")

    def test_missing_counter_table_raises_rather_than_defaulting(self,
                                                                 tmp_path,
                                                                 monkeypatch):
        """A trial counter that quietly reads 0 would lower the deflated-Sharpe
        bar to nothing and turn every FAIL into a PASS. It must refuse."""
        monkeypatch.setattr(orient, "RESEARCH_STATE", tmp_path / "gone.md")
        with pytest.raises(orient.Unmeasured):
            orient.trials()

    def test_changed_counter_table_format_raises(self, tmp_path, monkeypatch):
        f = tmp_path / "RESEARCH_STATE.md"
        f.write_text("| counter | source | trials |\n| CEF | discounts | 48 |\n")
        monkeypatch.setattr(orient, "RESEARCH_STATE", f)
        with pytest.raises(orient.Unmeasured, match="table format changed"):
            orient.trials()

    def test_missing_panel_is_reported_as_a_gap_with_its_path(self, tmp_path,
                                                             monkeypatch):
        monkeypatch.setattr(orient, "PANELS", {"cef_prices": tmp_path / "no.parquet"})
        p = orient.panels()["panels"]["cef_prices"]
        assert p["last"] is None and "missing" in p["error"]

    def test_collect_is_json_serialisable(self):
        d = orient.collect(run_tests=False)
        assert json.loads(json.dumps(d, default=str))["sections"]

    def test_render_survives_a_fully_unmeasured_readout(self, monkeypatch,
                                                        capsys):
        """The empty-machine case: nothing measurable, and it must still print
        a readout rather than traceback."""
        def boom():
            raise RuntimeError("nothing here")
        monkeypatch.setattr(orient, "SECTIONS",
                            [(n, boom) for n, _ in orient.SECTIONS])
        orient.render(orient.collect(run_tests=False))
        out = capsys.readouterr().out
        assert out.count("UNMEASURED") == len(orient.SECTIONS)


# --------------------------------------------------------- derived, not copied --
class TestDerivedFigures:
    def test_dsr_bar_is_computed_from_the_counter(self, tmp_path, monkeypatch):
        """sqrt(2 ln N) is DERIVED here because it was wrong in three documents
        at once when it was written out by hand (2.15 at N=10 left standing
        while the counter read 48, where the bar is 2.783)."""
        import math
        f = tmp_path / "RESEARCH_STATE.md"
        f.write_text("| **CEF** | **discounts** | **48** |\n"
                     "| **GAMMA** | **options** | **0** |\n")
        monkeypatch.setattr(orient, "RESEARCH_STATE", f)
        c = orient.trials()["counters"]
        assert c["CEF"]["trials"] == 48
        assert c["CEF"]["dsr_bar"] == round(math.sqrt(2 * math.log(48)), 3)
        assert c["GAMMA"]["dsr_bar"] is None, "no bar is defined at N<=1"

    def test_counter_is_labelled_as_a_citation_not_a_measurement(self):
        """The only document-sourced figure in the tool, and it must say so."""
        t = orient.trials()
        assert "[doc" in t["reproducer"]
        assert "RESEARCH_STATE" in t["source"]


# ----------------------------------------------------- measured, not written --
class TestTreeDelta:
    """`prod lacks` replaced a sentence ("prod is detached at v2026.09.10.1")
    that was wrong within a day in three documents. It must count exactly, in
    both directions, from git alone."""

    def _repo(self, tmp_path):
        import subprocess
        def git(*a):
            return subprocess.run(["git", *a], cwd=tmp_path, check=True,
                                  capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        for name in ("base", "fix one", "fix two"):
            (tmp_path / "f.txt").write_text(name)
            git("add", "f.txt")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name)
        return git

    def test_counts_what_prod_lacks_and_names_it(self, tmp_path):
        git = self._repo(tmp_path)
        prod = git("rev-parse", "HEAD~2")
        d = orient.tree_delta(prod, "HEAD", cwd=tmp_path)
        assert d["prod_lacks"] == 2 and d["dev_lacks"] == 0
        assert [s.split(" ", 1)[1] for s in d["newest"]] == ["fix two", "fix one"]

    def test_a_prod_commit_dev_lacks_is_reported(self, tmp_path):
        """A hotfix cut off the prod tag: promoting dev would drop it."""
        git = self._repo(tmp_path)
        git("checkout", "-q", "-b", "hotfix", "HEAD~1")
        (tmp_path / "g.txt").write_text("hotfix")
        git("add", "g.txt")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "hotfix")
        prod = git("rev-parse", "HEAD")
        git("checkout", "-q", "-")
        d = orient.tree_delta(prod, "HEAD", cwd=tmp_path)
        assert d["dev_lacks"] == 1 and d["prod_lacks"] == 1

    def test_an_unknown_sha_is_unmeasured_not_zero(self, tmp_path):
        self._repo(tmp_path)
        with pytest.raises(orient.Unmeasured):
            orient.tree_delta("deadbeef", "HEAD", cwd=tmp_path)


class TestSpecFields:
    def test_vol_target_is_read_from_the_spec(self):
        f = orient.spec_fields({"frozen": {"vol_target_annual": 0.11}})
        assert f["vol_target_annual"] == 0.11 and f["vol_target_absent"] is False

    def test_absent_vol_target_is_absent_not_the_code_default(self, capsys):
        """The sleeve has a code default for this key. Printing it here would
        make a code constant read as a governance decision."""
        f = orient.spec_fields({"frozen": {"band_width": 0.048}})
        assert f["vol_target_annual"] is None and f["vol_target_absent"] is True
        d = {"measured_at": "t", "sections": {
            n: {"UNMEASURED": "not under test"} for n, _ in orient.SECTIONS}}
        d["sections"]["SPEC"] = {**f, "status": "X", "min_trade_usd": 1,
                                 "capital_usd": 1}
        orient.render(d)
        out = capsys.readouterr().out
        assert "ABSENT from the frozen spec" in out
        assert "0.06" not in out
