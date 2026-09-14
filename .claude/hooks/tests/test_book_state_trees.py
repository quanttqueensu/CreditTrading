"""`book_state` feeds an agent's first impression. It read the wrong tree.

WHY THIS FILE EXISTS
--------------------
`book_state.collect()` is the single reader behind the SessionStart banner, the
status line, `/book-status`, `/morning-brief`, `/next-task`, `/incident` and the
`ops-watchdog` seat — seven surfaces, one read. Until 2026-09-11 it resolved
every path against the tree it was RUNNING in (dev) while the scheduler writes
all of them in `~/prod/QUANTT`. It did not fail; it reported a clean book.

Measured on 2026-09-11, the day this was fixed:

    ls ops/HALT*.md                 -> no matches          (dev)
    ls ~/prod/QUANTT/ops/HALT*.md   -> HALT_phase0_null.md (ACTIVE)

and the banner printed no halt line at all. Halt files are UNTRACKED, so dev is
not merely stale — a halt never arrives there by any promotion, ever. That halt
is what stands between the phantom 1,503-share JAAA short and an armed session,
so "the monitor cannot see it" is a trading fault wearing a reporting costume.

Three separate defects, one per test class below:

  1. scoped halts (`ops/HALT_<book>.md`) were not read AT ALL. `ops/halt.py:46`
     has had `scoped_path(book)` since 2026-09-10; this reader never learned.
  2. every live path was resolved against dev only.
  3. the "reason" shown was the file's boilerplate header rather than its most
     recent entry, so every halt rendered as the same generic sentence.

NO PROD TREE, NO NETWORK, NO LIVE STATE. Every test builds both trees inside
`tmp_path` and repoints the module constants. Nothing here reads the real
`~/prod/QUANTT` or `ops/books/*_live/`, whose contents are the only record of
294 real executions.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]


def _load():
    """Fresh module object per test — the constants are patched in place."""
    spec = importlib.util.spec_from_file_location(
        "book_state_undertest", HOOKS / "book_state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(root: Path, name: str) -> Path:
    """A minimal worktree: just the directories the reader globs."""
    t = root / name
    (t / "ops").mkdir(parents=True, exist_ok=True)
    (t / "ops/schedule/logs").mkdir(parents=True, exist_ok=True)
    return t


def _halt_file(tree: Path, book: str | None, when: str, reason: str) -> Path:
    """Byte-for-byte the shape `ops/halt.py:write_halt` produces."""
    path = tree / "ops" / ("HALT.md" if book is None else f"HALT_{book}.md")
    scope = ("trading is BLOCKED until this file is cleared" if book is None
             else f"trading is BLOCKED for **{book}** until this file is "
                  "cleared (other books are warned, not blocked)")
    header = (f"# HALT — {book or 'automated trading is blocked'}\n\n"
              "`ops/preflight.py` reads this file before every scheduled "
              "session and will not arm live orders while it exists. Data "
              "collection and logging continue regardless.\n\n"
              "Most recent halt first.\n\n---\n\n")
    path.write_text(f"{header}## {when}  {reason}\n\n"
                    f"- **state**: {scope}\n\n---\n\n")
    return path


@pytest.fixture
def two_trees(tmp_path, monkeypatch):
    """dev == where we are running; prod == where the scheduler writes."""
    dev, prod = _tree(tmp_path, "dev"), _tree(tmp_path, "prod")
    mod = _load()
    monkeypatch.setattr(mod, "REPO", dev)
    monkeypatch.setattr(mod, "PROD_TREE", prod)
    return mod, dev, prod


# ----------------------------------------------------- 1. the scoped halt --
class TestScopedHaltInProd:
    def test_prod_scoped_halt_is_seen_when_dev_has_none(self, two_trees):
        """THE LIVE DEFECT, reproduced exactly: dev clean, prod halted."""
        mod, dev, prod = two_trees
        _halt_file(prod, "phase0_null", "2026-09-10 16:04:42",
                   "LQD $89,841.18 unattributed")
        assert not list((dev / "ops").glob("HALT*.md")), "dev must be clean"

        h = mod.halted()
        books = [s["book"] for s in h["scoped"]]
        assert books == ["phase0_null"], (
            "a halt active in prod was invisible — the exact failure of "
            "2026-09-11, when the SessionStart banner read clean")
        assert h["scoped"][0]["tree"] == str(prod.resolve())

    def test_scoped_halt_does_not_raise_the_global_flag(self, two_trees):
        """`active` keys the status line. A $20k book must not paint it red.

        That is the same mistake scoped halts were invented to prevent: two
        small books stopped the $500k strategy over their own bookkeeping in
        two days. Widening `active` here would re-create it in the monitor.
        """
        mod, _dev, prod = two_trees
        _halt_file(prod, "phase0_null", "2026-09-10 16:04:42", "bookkeeping")
        h = mod.halted()
        assert h["active"] is False
        assert h["scoped"], "but it must still be REPORTED, by name"

    def test_global_halt_does_raise_it(self, two_trees):
        mod, _dev, prod = two_trees
        _halt_file(prod, None, "2026-09-11 09:00:00", "human halt")
        h = mod.halted()
        assert h["active"] is True
        assert "human halt" in h["reason"]

    def test_same_book_halted_in_both_trees_is_reported_once(self, two_trees):
        """Prod wins; the book must not appear twice in the banner."""
        mod, dev, prod = two_trees
        _halt_file(prod, "cef_discount", "2026-09-11 10:00:00", "from prod")
        _halt_file(dev, "cef_discount", "2026-09-01 10:00:00", "from dev")
        scoped = mod.halted()["scoped"]
        assert len(scoped) == 1
        assert scoped[0]["reason"] == "from prod"


# ------------------------------------------------- 2. every live path read --
class TestBothTreesAreRead:
    def test_newest_log_wins_across_trees(self, two_trees):
        """dev's newest was cef_2026-09-09 while prod had cef_2026-09-10."""
        mod, dev, prod = two_trees
        (dev / "ops/schedule/logs/cef_2026-09-09.log").write_text(
            "ARMED: 17 orders\nstatus=ok\n")
        (prod / "ops/schedule/logs/cef_2026-09-10.log").write_text(
            "[FAIL] broker: nothing listening\nstatus=ok_not_armed\n")
        t = mod.todays_log()
        assert t["date"] == "2026-09-10"
        assert t["tree"] == str(prod.resolve())
        assert t["armed"] is False
        assert t["blockers"], "a blocker in prod's log must reach the banner"

    def test_prod_preferred_for_the_same_session_date(self, two_trees):
        mod, dev, prod = two_trees
        for tree, txt in ((dev, "status=stale-dev\n"),
                          (prod, "ARMED: 17 orders\nstatus=ok\n")):
            (tree / "ops/schedule/logs/cef_2026-09-10.log").write_text(txt)
        assert mod.todays_log()["armed"] is True

    def test_heartbeat_comes_from_prod(self, two_trees):
        mod, dev, prod = two_trees
        (dev / "ops/heartbeat.json").write_text(
            json.dumps({"cef": {"status": "ok", "date": "2026-09-01"}}))
        (prod / "ops/heartbeat.json").write_text(
            json.dumps({"cef": {"status": "broker_down", "date": "2026-09-11"}}))
        assert mod.heartbeat()["cef"]["status"] == "broker_down"

    def test_dev_only_machine_still_works(self, tmp_path, monkeypatch):
        """A fresh clone with no prod tree must degrade, not vanish."""
        dev = _tree(tmp_path, "dev")
        mod = _load()
        monkeypatch.setattr(mod, "REPO", dev)
        monkeypatch.setattr(mod, "PROD_TREE", tmp_path / "nope")
        _halt_file(dev, "cef_discount", "2026-09-11 09:00:00", "local halt")
        assert mod.live_trees() == [dev.resolve()]
        assert mod.halted()["scoped"][0]["reason"] == "local halt"


# ------------------------------------------------------ 3. the reason line --
class TestHaltReasonIsTheEntry:
    def test_reason_is_the_entry_not_the_boilerplate(self, two_trees):
        """Every halt used to render as the same sentence about halt files."""
        mod, _dev, prod = two_trees
        p = _halt_file(prod, "phase0_null", "2026-09-10 16:04:42",
                       "LQD $89,841.18 unattributed")
        r = mod._halt_reason(p)
        assert r["reason"] == "LQD $89,841.18 unattributed"
        assert r["when"] == "2026-09-10 16:04:42"
        assert "preflight.py" not in r["reason"], (
            "this is the header, not the halt — what the banner printed "
            "until 2026-09-11")

    def test_hand_written_halt_without_an_entry_still_reads(self, two_trees):
        """A human can write this file by hand; it has no `## ` heading."""
        mod, _dev, prod = two_trees
        (prod / "ops/HALT.md").write_text(
            "# HALT\n\nStopped by hand pending the 09-10 reconcile.\n")
        assert "Stopped by hand" in mod.halted()["reason"]


# ------------------------------------------------------- the hook contract --
class TestNeverBreaksItsConsumers:
    def test_heartbeat_values_are_all_dicts(self, two_trees):
        """`session_context.py` calls `v.get("status")` on every value.

        A bare string smuggled in beside the jobs — a tree name, say — is an
        AttributeError in the SessionStart hook, i.e. the banner disappears
        silently. Caught in review on 2026-09-11 before it shipped.
        """
        mod, _dev, prod = two_trees
        (prod / "ops/heartbeat.json").write_text(
            json.dumps({"cef": {"status": "ok", "date": "2026-09-11"}}))
        assert all(isinstance(v, dict) for v in mod.heartbeat().values())

    def test_collect_never_raises_on_an_empty_machine(self, tmp_path,
                                                      monkeypatch):
        """A monitor that dies on a missing file is the failure it exists to
        catch. Every field degrades to None with a reason instead."""
        mod = _load()
        monkeypatch.setattr(mod, "REPO", tmp_path / "gone")
        monkeypatch.setattr(mod, "PROD_TREE", tmp_path / "also-gone")
        s = mod.collect()
        assert s["halt"]["active"] is False
        assert s["fills"]["date"] is None
        assert json.dumps(s), "collect() must stay JSON-serialisable"

    def test_collect_reports_which_trees_it_read(self, two_trees):
        """'Which tree said this' went unasked for a day. Now it is in the
        payload, so a reader cannot fail to ask it."""
        mod, dev, prod = two_trees
        t = mod.collect()["trees"]
        assert t["read"] == [str(prod.resolve()), str(dev.resolve())]
        assert t["prod_present"] is True
        assert t["running_in"] == str(dev)
