"""The pathspecs in `ops/promote.sh` must actually match the paths they name.

WHY THIS TEST EXISTS
--------------------
On 2026-09-10 `ops/promote.sh` carried six pathspec exclusions so its clean-tree
gate would ask "did anyone edit prod CODE" rather than "did the book trade".
Two of the six matched NOTHING:

    ':!ops/books/*_live'     ':!ops/halts'

A git pathspec `*` does not cross `/`, and no TRACKED path is literally named
`…_live` -- the tracked paths are `ops/books/cef_live/_ibkr_shadow/…`. So the
live ledgers were never excluded and the gate REFUSED every promotion as soon as
a session wrote one. The same trap bit the INCLUSIVE pathspec that feeds the
"live state has advanced" note, in the opposite direction: it matched nothing, so
the note never fired and every promotion log silently claimed no state had moved.

This is the worst shape a defect can take in a gate: **an exclusion that matches
nothing is indistinguishable, from the outside, from one that matched and found
nothing wrong.** Four of the six exclusions did work -- the ones naming a real
single-segment path -- so the gate looked fine and read fine. Only a test that
builds a repo with the real path SHAPE can tell the two apart, which is why this
asserts against a fixture rather than re-reading the comment in the script.

Fixture shape mirrors prod: a tracked ledger file nested two levels under a
`*_live` directory, a tracked heartbeat, and an untracked scoped halt file.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
PROMOTE = REPO / "ops" / "promote.sh"


def _git(cwd, *args):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
def prodlike(tmp_path):
    """A repo shaped like prod: nested live ledgers tracked, state dirty."""
    r = tmp_path / "repo"
    (r / "ops/books/cef_live/_ibkr_shadow/cef_discount").mkdir(parents=True)
    (r / "ops/books/phase0_live/_ibkr_shadow/null_trader").mkdir(parents=True)
    (r / "ops/halts").mkdir(parents=True)
    (r / "ops/schedule/logs").mkdir(parents=True)
    _git(r.parent, "init", "--quiet", str(r))
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")

    ledger = r / "ops/books/cef_live/_ibkr_shadow/cef_discount/positions.csv"
    ledger.write_text("date,ticker,shares\n2026-09-09,JFR,100\n")
    phase0 = r / "ops/books/phase0_live/_ibkr_shadow/null_trader/nav.csv"
    phase0.write_text("date,nav\n2026-09-09,500000\n")
    (r / "ops/heartbeat.json").write_text('{"cef": "2026-09-09"}\n')
    (r / "ops/promote.sh").write_text("# code\n")
    _git(r, "add", "-A")
    _git(r, "commit", "--quiet", "-m", "seed")

    # A session ran: ledgers and heartbeat moved. Nobody touched code.
    ledger.write_text("date,ticker,shares\n2026-09-09,JFR,100\n2026-09-10,JFR,90\n")
    phase0.write_text("date,nav\n2026-09-09,500000\n2026-09-10,504573\n")
    (r / "ops/heartbeat.json").write_text('{"cef": "2026-09-10"}\n')
    (r / "ops/HALT_phase0_null.md").write_text("# HALT\n")   # untracked, scoped
    return r


def _excludes_from_script():
    """The STATE_EXCLUDES array as promote.sh actually defines it.

    Parsed from the script so the test cannot drift from the thing it guards --
    a hand-copied list here would let the script regress while this stayed green.
    """
    text = PROMOTE.read_text()
    m = re.search(r"STATE_EXCLUDES=\((.*?)\)", text, re.S)
    assert m, "STATE_EXCLUDES not found in ops/promote.sh"
    return re.findall(r"'([^']+)'", m.group(1))


def test_state_excludes_are_all_nonvacuous(prodlike):
    """Every exclusion must change the result of SOME status call.

    The bug was an exclusion that matched nothing. Pin each one individually:
    drop it from the set and the output must change, or it was doing nothing.
    """
    ex = _excludes_from_script()
    full = _git(prodlike, "status", "--porcelain", "--", ".", *ex)
    vacuous = []
    for one in ex:
        without = [e for e in ex if e != one]
        if _git(prodlike, "status", "--porcelain", "--", ".", *without) == full:
            vacuous.append(one)
    # ':!ops/HALT.md' and ':!ops/halts/**' are legitimately inert on a fixture
    # that has neither a global halt nor an archived one; only assert on the
    # patterns this fixture exercises.
    exercised = {e for e in ex if any(
        k in e for k in ("_live", "heartbeat", "HALT_"))}
    assert not (set(vacuous) & exercised), (
        f"these exclusions matched nothing despite the fixture containing such "
        f"paths: {sorted(set(vacuous) & exercised)} -- a '*' that must cross '/' "
        f"needs a trailing '/**'")


def test_gate_passes_when_only_state_moved(prodlike):
    """The real-world case the gate exists to allow: a session ran, no code edit."""
    dirty = _git(prodlike, "status", "--porcelain", "--", ".",
                 *_excludes_from_script())
    assert dirty.strip() == "", (
        f"gate would REFUSE a promotion after a normal session; unexcluded:\n{dirty}")


def test_gate_still_refuses_a_code_edit(prodlike):
    """And the case it exists to catch -- the exclusions must not swallow code."""
    (prodlike / "ops/promote.sh").write_text("# code\n# someone edited prod\n")
    dirty = _git(prodlike, "status", "--porcelain", "--", ".",
                 *_excludes_from_script())
    assert "ops/promote.sh" in dirty, (
        "a human editing prod CODE must still wedge the gate; it did not")


def test_state_moved_pathspec_counts_the_ledgers(prodlike):
    """The INCLUSIVE pathspec must see the files the exclusions hide.

    These two are mirrors of each other: the same `*_live` pattern, once to
    ignore and once to report. Measured 2026-09-10, the inclusive one returned 0
    where the corrected form returns 2, so the promotion log's "live state has
    advanced" note had never fired.
    """
    text = PROMOTE.read_text()
    m = re.search(r"STATE_MOVED=\"\$\(git -C \"\$PROD\" status --porcelain -- (.*?)\|",
                  text, re.S)
    assert m, "STATE_MOVED pathspec not found in ops/promote.sh"
    specs = re.findall(r"'([^']+)'", m.group(1))
    assert specs, "STATE_MOVED names no pathspec"
    out = _git(prodlike, "status", "--porcelain", "--", *specs)
    names = [ln[3:] for ln in out.splitlines()]
    assert any("cef_live" in n for n in names), (
        f"STATE_MOVED pathspec {specs} does not match a nested *_live ledger; "
        f"it saw {names}")
    assert any("heartbeat" in n for n in names), (
        f"STATE_MOVED pathspec {specs} missed the heartbeat; it saw {names}")
