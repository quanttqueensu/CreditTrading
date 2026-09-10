"""One book's bookkeeping must not stop another book's strategy.

THE INCIDENTS THESE TESTS PIN. `arm()` refuses when a symbol's attribution is
ambiguous, and that refusal wrote the GLOBAL `ops/HALT.md`, which preflight
treats as a hard gate for every book. Twice in two days a small book stopped
the $500k strategy over its own missing ledger row:

  * 2026-09-09 09:37  phase0 (the $310k null-trader control) could not attribute
    JNK — it had sold all 961 shares the day before, and a ledger cannot say
    "I own NONE of this", so the account's remaining 26 (bench_b6's) looked
    unexplained. Global halt.
  * 2026-09-09 17:25  bench_b6 (a $20k benchmark) could not attribute ANGL —
    its own 87-share MOC fill landed after its ledger was re-seeded without it.
    Global halt, cleared by hand at 17:27 only because someone was watching;
    otherwise it would have blocked the CEF session at 22:45.

`arm()` only ever refuses on symbols the book being armed trades, so an arming
failure is inherently that book's problem. Since 2026-09-10 it writes
`ops/HALT_<book>.md`, which blocks that book and reaches every other book as a
NON-BLOCKING warning — visible on every session, so a book left halted for a
week is still noticed, but unable to stop a strategy over a symbol the strategy
does not trade.

The global file keeps its old meaning exactly: a human halt, or a fault nobody
can attribute, blocks everything.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import halt as halt_mod          # noqa: E402
from ops import preflight                 # noqa: E402

STRATEGY = "cef_discount_paper"
BENCH = "benchmarks_paper"


@pytest.fixture
def halt_dir(tmp_path, monkeypatch):
    """Point every halt path at a temp dir. The real ops/ is never touched."""
    ops = tmp_path / "ops"
    ops.mkdir()
    monkeypatch.setattr(halt_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(halt_mod, "HALT_PATH", ops / "HALT.md")
    monkeypatch.setattr(halt_mod, "HALT_ARCHIVE", ops / "halts")
    monkeypatch.setattr(halt_mod, "alert", lambda **kw: {})
    return ops


def _write(book=None, reason="test halt"):
    return halt_mod.write_halt(reason=reason, detail="d", source="test",
                               book=book)


# -- the scope itself -----------------------------------------------------

def test_scoped_halt_blocks_only_its_own_book(halt_dir):
    _write(book=BENCH)
    assert halt_mod.read_halt(BENCH) is not None, "must block its own book"
    assert halt_mod.read_halt(STRATEGY) is None, "must NOT block another book"
    assert halt_mod.read_halt() is None, "must not look like a global halt"


def test_global_halt_still_blocks_everything(halt_dir):
    """The pre-2026-09-10 contract, unchanged."""
    _write(book=None)
    assert halt_mod.read_halt() is not None
    assert halt_mod.read_halt(STRATEGY) is not None
    assert halt_mod.read_halt(BENCH) is not None


def test_global_wins_over_scoped(halt_dir):
    """A global halt outranks a scoped one for the book that has both."""
    _write(book=BENCH, reason="bench problem")
    _write(book=None, reason="global problem")
    active = halt_mod.read_halt(BENCH)
    assert active["reason"] == "global problem"
    assert active["scope"] == "global"


def test_scoped_file_is_named_and_greppable(halt_dir):
    p = _write(book=BENCH)
    assert p.name == f"HALT_{BENCH}.md"
    assert p.parent == halt_dir
    assert BENCH in p.read_text()
    # `ls ops/HALT*.md` must show global and scoped halts together
    assert p in list(halt_dir.glob("HALT*.md"))


# -- what other books are told -------------------------------------------

def test_other_books_are_warned_not_blocked(halt_dir):
    _write(book=BENCH)
    others = halt_mod.other_book_halts(STRATEGY)
    assert [h["book"] for h in others] == [BENCH]
    assert halt_mod.other_book_halts(BENCH) == [], "not warned about itself"


def test_preflight_blocks_the_halted_book(halt_dir):
    _write(book=BENCH)
    checks = preflight.check_halt(BENCH)
    blocking = [c for c in checks if not c.ok and c.blocking]
    assert len(blocking) == 1 and blocking[0].name == "halt"


def test_preflight_only_warns_the_other_book(halt_dir):
    _write(book=BENCH)
    checks = preflight.check_halt(STRATEGY)
    assert not [c for c in checks if not c.ok and c.blocking], \
        "another book's halt must never block this one"
    warns = [c for c in checks if not c.ok and not c.blocking]
    assert len(warns) == 1 and BENCH in warns[0].name
    # and the halt check itself passes
    assert [c for c in checks if c.name == "halt"][0].ok


def test_preflight_with_no_book_is_global_only(halt_dir):
    """Callers that pass no book keep the old behaviour."""
    _write(book=BENCH)
    assert [c for c in preflight.check_halt() if not c.ok and c.blocking] == []
    _write(book=None)
    assert len([c for c in preflight.check_halt() if not c.ok and c.blocking]) == 1


# -- clearing -------------------------------------------------------------

def test_clearing_global_does_not_clear_a_scoped_halt(halt_dir):
    """Clearing "the halt" must not silently unblock a book nobody looked at."""
    _write(book=BENCH)
    _write(book=None)
    assert halt_mod.clear_halt("fixed the global one") is True
    assert halt_mod.read_halt() is None
    assert halt_mod.read_halt(BENCH) is not None, "scoped halt must survive"


def test_clearing_a_scoped_halt_unblocks_only_that_book(halt_dir):
    _write(book=BENCH)
    assert halt_mod.clear_halt("fixed bench", book=BENCH) is True
    assert halt_mod.read_halt(BENCH) is None
    archived = list((halt_dir / "halts").glob(f"HALT_{BENCH}_*.md"))
    assert len(archived) == 1, "a cleared halt is archived, never deleted"
    assert "fixed bench" in archived[0].read_text()


def test_clearing_nothing_is_not_an_error(halt_dir):
    assert halt_mod.clear_halt("nothing to do") is False
