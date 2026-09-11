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
    (r / "ops/books/_dryruns/phase0").mkdir(parents=True)
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
    dry = r / "ops/books/_dryruns/phase0/book_status_dryrun.json"
    dry.write_text('{"asof": "2026-09-09"}\n')
    (r / "ops/promote.sh").write_text("# code\n")
    _git(r, "add", "-A")
    _git(r, "commit", "--quiet", "-m", "seed")

    # A session ran: ledgers and heartbeat moved. Nobody touched code.
    ledger.write_text("date,ticker,shares\n2026-09-09,JFR,100\n2026-09-10,JFR,90\n")
    phase0.write_text("date,nav\n2026-09-09,500000\n2026-09-10,504573\n")
    (r / "ops/heartbeat.json").write_text('{"cef": "2026-09-10"}\n')
    (r / "ops/HALT_phase0_null.md").write_text("# HALT\n")   # untracked, scoped
    # ...and a session that did NOT arm wrote its dry-run artefacts. That is the
    # COMMON case -- the CEF book armed on 5 of 29 sessions -- and until
    # 2026-09-11 these were the files that refused the promotion even after the
    # `/**` fix, measured against prod: two dirty lines, both under _dryruns.
    dry.write_text('{"asof": "2026-09-10"}\n')
    (r / "ops/books/_dryruns/phase0/dryrun_2026-09-10.json").write_text("{}\n")
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
        k in e for k in ("_live", "_dryruns", "heartbeat", "HALT_"))}
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


# --------------------------------------------------------------------------
# The session window, and the guard that does not trust a clock.
#
# WHY. Until 2026-09-10 the window end was the literal `2230`, while
# `ops/schedule/cef.env` had carried `NAV_DEADLINE=23:30` since 09-08. So for a
# full hour every trading night the gate said "not in the session window" while
# the cef session was still polling for NAV and had not placed its orders --
# and a promotion there checks out a different tag under a running session.
# Measured that evening: the 17:15 run logged `deadline 23:30, poll every
# 900s`. The two numbers lived in different files and nothing compared them.
# --------------------------------------------------------------------------

WINDOW_SNIPPET = r"""
CEF_ENV="$1"
NAV_DEADLINE="$(sed -n 's/^NAV_DEADLINE=//p' "$CEF_ENV" | tr -d ' \r' | tail -1)"
case "$NAV_DEADLINE" in
  [0-2][0-9]:[0-5][0-9]) : ;;
  *) echo "REFUSED-UNPARSEABLE"; exit 2 ;;
esac
WINDOW_END="${NAV_DEADLINE%%:*}${NAV_DEADLINE##*:}"
HHMM="$2"
if [ "$HHMM" -ge 1630 ] && [ "$HHMM" -le "$WINDOW_END" ]; then
  echo "REFUSED-INSIDE-WINDOW $WINDOW_END"
else
  echo "ALLOWED $WINDOW_END"
fi
"""


def _window(tmp_path, deadline_line, hhmm):
    env = tmp_path / "cef.env"
    env.write_text(f"# comment\n{deadline_line}\nNAV_POLL_SECONDS=900\n")
    snip = tmp_path / "w.sh"
    snip.write_text(WINDOW_SNIPPET)
    return subprocess.run(["bash", str(snip), str(env), str(hhmm)],
                          capture_output=True, text=True).stdout.strip()


def test_window_end_is_derived_from_nav_deadline_not_a_literal(tmp_path):
    """22:45 is INSIDE the window when the deadline is 23:30. It used to be outside."""
    assert _window(tmp_path, "NAV_DEADLINE=23:30", 2245) == "REFUSED-INSIDE-WINDOW 2330"
    assert _window(tmp_path, "NAV_DEADLINE=23:30", 2330) == "REFUSED-INSIDE-WINDOW 2330"
    assert _window(tmp_path, "NAV_DEADLINE=23:30", 2331).startswith("ALLOWED")
    assert _window(tmp_path, "NAV_DEADLINE=23:30", 1629).startswith("ALLOWED")
    assert _window(tmp_path, "NAV_DEADLINE=23:30", 1630) == "REFUSED-INSIDE-WINDOW 2330"


def test_window_follows_the_deadline_when_it_moves(tmp_path):
    """Change the deadline and the window changes with it -- the point of deriving."""
    assert _window(tmp_path, "NAV_DEADLINE=21:30", 2245).startswith("ALLOWED")
    assert _window(tmp_path, "NAV_DEADLINE=23:30", 2245) == "REFUSED-INSIDE-WINDOW 2330"


def test_an_unparseable_deadline_refuses_rather_than_defaulting(tmp_path):
    """NO SILENT FALLBACKS. A default here would rebuild the exact defect."""
    assert _window(tmp_path, "NAV_DEADLINE=", 2245) == "REFUSED-UNPARSEABLE"
    assert _window(tmp_path, "NAV_DEADLINE=half past eleven", 2245) == "REFUSED-UNPARSEABLE"
    assert _window(tmp_path, "# NAV_DEADLINE absent entirely", 2245) == "REFUSED-UNPARSEABLE"


def test_promote_sh_derives_the_window_and_does_not_carry_the_old_literal():
    """Pin it in the real script, not just in the snippet above."""
    src = PROMOTE.read_text()
    assert "NAV_DEADLINE" in src, "the window end must be derived from cef.env"
    assert 'WINDOW_END="${NAV_DEADLINE%%:*}${NAV_DEADLINE##*:}"' in src
    assert '-le 2230' not in src, "the 2230 literal is the defect; it must not return"


def test_promote_sh_refuses_while_a_session_process_is_live():
    """The clock is a proxy; a live pid is the question itself, and --force
    must not bypass it."""
    src = PROMOTE.read_text()
    assert "com.quantt.$job.daily" in src
    assert "is RUNNING (pid" in src
    guard = src.split("# 1b.", 1)[1].split("# 2.", 1)[0]
    assert "FORCE" not in guard, (
        "--force exists for the clock, never for a running session")


def test_a_session_that_did_not_arm_does_not_wedge_the_gate(prodlike):
    """The case that made the `/**` fix worth nothing in practice.

    `ops/books/_dryruns/` holds 18 TRACKED files in this repo and a NOT-ARMED
    session rewrites them. The book has armed on 5 of 29 sessions, so the usual
    outcome of an evening is a dirty _dryruns and a clean everything else. Until
    2026-09-11 the gate counted those, so the corrected pathspecs had merely
    moved the refusal from the live ledgers to the dry-run output. Measured
    against prod that day: 0 dirty under the live-ledger excludes alone, 2 once
    _dryruns was counted -- both dry-run artefacts.

    Producing a dry run is not a human editing production, which is the only
    thing this gate is meant to catch.
    """
    dirty = _git(prodlike, "status", "--porcelain", "--", ".",
                 *_excludes_from_script())
    assert "_dryruns" not in dirty, (
        f"a NOT-ARMED session wedges the gate; unexcluded:\n{dirty}")
