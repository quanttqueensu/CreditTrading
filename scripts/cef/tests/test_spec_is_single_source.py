"""Guard: analysis baselines must not hardcode the band width.

WHY THIS TEST EXISTS
--------------------
On 2026-09-10 four analysis scripts were found baselining against
`band(T, 0.064)` -- the 6.4% width that was DELIBERATELY NOT CHOSEN on
2026-09-06, because it topped a swept column and picking the argmax of a sweep
is how `z_window=63` was selected and failed out of sample.

Nothing errored. Nothing looked wrong. The scripts simply measured every result
against a book that does not exist, off by the difference between two policies
-- which is the size of the effects those scripts were written to detect. All
four are named in prompts as things an agent should extend, so the error was
positioned to propagate into new work indefinitely.

That failure is invisible to every other check in this repo.

WHY THIS TEST IS NARROW, AND WHY THE FIRST VERSION OF IT WAS WRONG
------------------------------------------------------------------
The obvious implementation -- flag any literal equal to a spec value -- does not
work, and failing it taught the lesson worth recording here. `z_window` is 252
and there are 252 trading days in a year, so `np.sqrt(252)` matches on value and
is completely unrelated. `vol_target_annual` is 0.06 and so are plenty of other
sixes. A value-equality check cannot distinguish two quantities that happen to
share a number, and a test with false positives gets deleted rather than fixed.

So this checks the one thing it can defend precisely: the ARGUMENT POSITION of a
`band()` / `band_hard_exit()` call. That is where the bug actually lived, it is
unambiguous, and it stays true regardless of what the spec value becomes.

WHAT IT DELIBERATELY ALLOWS
---------------------------
A *sweep* that varies the width on purpose -- characterising the policy class is
legitimate research and H8 permits it explicitly. A sweep is recognised as a
name (`for b in BAND_SWEEP`) or a comprehension over a collection, not a bare
literal at the call site.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CEF = REPO / "scripts/cef"

BAND_FUNCS = {"band", "band_hard_exit"}

# spec.py is the single reader and necessarily names the value.
EXEMPT = {"spec.py"}

# These read the frozen spec directly for reasons other than a research
# baseline (live-ledger reconciliation, holdout bookkeeping, borrow fetching).
# Converting them is tracked in the W0 hygiene note, not enforced here -- this
# test guards the analysis baselines, which is where the silent-wrong-answer
# bug lives.
KNOWN_DIRECT_READERS = {
    "dust_check.py", "open_holdout.py", "reconcile_prices.py",
    "fetch_borrow_rates.py", "fetch_borrow_history.py",
}

# The scripts converted on 2026-09-10. If one of these starts reading the spec
# JSON directly again, the single-reader property has been lost.
CONVERTED = {
    "band_frontier.py", "covariance_construction.py",
    "ou_score.py", "borrow_impact.py",
}


def _scripts() -> list[Path]:
    return sorted(p for p in CEF.glob("*.py")
                  if p.name not in EXEMPT and not p.name.startswith("_"))


@pytest.mark.parametrize("name", sorted(CONVERTED))
def test_converted_scripts_do_not_read_the_spec_directly(name):
    """Regression guard on the 2026-09-10 conversion.

    spec.py exists so there is exactly one place that knows how to read the
    frozen spec, and exactly one place that raises when a key is missing.
    """
    path = CEF / name
    if not path.exists():
        pytest.skip(f"{name} no longer exists")
    assert "cef_discount.frozen.json" not in path.read_text(), (
        f"{name} reads the frozen spec directly again. Import from "
        "scripts/cef/spec.py instead -- a second reader is a second place for a "
        "default to creep in and a second place to forget when the spec moves.")


def _band_literal_calls(tree: ast.AST) -> list[tuple[int, float]]:
    """(lineno, value) for every band()/band_hard_exit() called with a bare float."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if fname not in BAND_FUNCS:
            continue
        for arg in node.args[1:]:                 # arg 0 is the target frame
            if isinstance(arg, ast.Constant) and isinstance(arg.value, float):
                found.append((node.lineno, arg.value))
    return found


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_band_width_is_not_a_bare_literal(path: Path):
    """A band() baseline must take its width from the spec, not a literal.

    The width is a live trading parameter. A script that names it directly is
    pinned to whatever the width was on the day it was written, and says nothing
    about it when that stops being true.
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        pytest.skip(f"{path.name} does not parse")

    src = path.read_text().splitlines()
    offenders = []
    for lineno, value in _band_literal_calls(tree):
        line = src[lineno - 1].strip()
        # A row that labels its own width in the same statement is an explicit,
        # honest comparison point, not a silent baseline. Two forms count:
        # a literal label ("band 6.4%"), and a generated one (_lab_band(0.064)),
        # which is better because the label cannot drift from the value.
        if f"{value * 100:.1f}%" in line:
            continue
        if f"_lab_band({value}" in line.replace(" ", ""):
            continue
        offenders.append(f"line {lineno}: band(..., {value}) -- {line[:80]}")

    assert not offenders, (
        f"{path.name} hardcodes a band width at a call site:\n  "
        + "\n  ".join(offenders)
        + "\n\nImport BAND_WIDTH from scripts/cef/spec.py so the baseline follows "
          "the live book. If this is a deliberate comparison point, label the "
          "width in the same statement (e.g. \"band 6.4%\") so a reader can see "
          "it is not the live policy."
    )


def test_spec_module_raises_rather_than_defaulting():
    """No silent fallbacks, applied to the spec reader itself.

    A default here would reintroduce the bug this module exists to remove, one
    layer down: the script would run, produce a number, and the number would be
    against a policy nobody deployed.
    """
    import sys
    sys.path.insert(0, str(CEF))
    import spec as spec_mod

    with pytest.raises(spec_mod.SpecError) as exc:
        spec_mod.frozen("a_key_that_does_not_exist")
    assert "a_key_that_does_not_exist" in str(exc.value), (
        "SpecError must name the missing key -- 'raise, naming what was missing'")


def test_live_policy_label_tracks_the_spec():
    """The LIVE label must be derived, not asserted.

    Three scripts marked "calendar 2d (LIVE)" for four days after the band
    replaced it, and PLAN.md carries the same claim in five tables. A label that
    can go stale silently is the same bug as a hardcoded baseline, one layer up.
    """
    import sys
    sys.path.insert(0, str(CEF))
    import spec as spec_mod

    if spec_mod.BAND_IS_LIVE:
        assert spec_mod.LIVE_POLICY.startswith("band"), spec_mod.LIVE_POLICY
        assert f"{spec_mod.BAND_WIDTH:.1%}" in spec_mod.LIVE_POLICY
    else:
        assert spec_mod.LIVE_POLICY.startswith("calendar"), spec_mod.LIVE_POLICY
