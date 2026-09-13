"""Pin the launch_job patch against the file it edits.

`launch_job.py` is outside the repo and outside git, so nothing else in this
suite can see it drift. This test is the only thing that will notice when
someone edits the scheduler by hand and quietly breaks the anchors the patch
matches on -- which would otherwise surface as a SystemExit at 08:30 on the
morning a human ran the patcher, or worse, as a partially-applied file.

It skips when the target is absent (another machine, CI, a fresh clone) rather
than failing, because the patch's correctness against a file that is not there
is not a meaningful question.
"""
import importlib.util
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "schedule/patch_launch_job_w3am.py"


def _patcher():
    spec = importlib.util.spec_from_file_location("patch_w3am", SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source(p):
    if not p.TARGET.exists():
        pytest.skip(f"launch_job.py not on this machine ({p.TARGET})")
    return p.TARGET.read_text()


def test_every_anchor_matches_exactly_once():
    """A fuzzy match against the file that places orders is not acceptable."""
    p = _patcher()
    src = _source(p)
    if p.MARKER in src:
        pytest.skip("already applied")
    for i, (old, _new) in enumerate(p.EDITS, 1):
        assert src.count(old) == 1, f"edit {i} matched {src.count(old)} times"


def test_the_patched_file_compiles():
    p = _patcher()
    src = _source(p)
    if p.MARKER in src:
        pytest.skip("already applied")
    compile(p.build(src), "launch_job.py", "exec")


def test_the_patch_is_idempotent():
    """Applying twice must be refused by the marker, not produce a double edit."""
    p = _patcher()
    src = _source(p)
    if p.MARKER in src:
        pytest.skip("already applied")
    once = p.build(src)
    assert p.MARKER in once
    with pytest.raises(SystemExit, match="expected exactly 1"):
        p.build(once)


def test_no_decision_path_still_uses_the_calendar_date_as_the_pair():
    """The whole point of the change, asserted on the resulting source.

    `today` and `asof` diverge in the morning session. Anything that decides,
    checks data freshness, or reports what was decided must use `asof`; if one
    of them keeps `today` the ledger's fill date and the broker's disagree by a
    day and the P&L record is silently wrong.
    """
    p = _patcher()
    src = _source(p)
    out = p.build(src) if p.MARKER not in src else src
    assert '"--asof", asof, "--book"' in out, "run_book must decide on the pair"
    assert 'pf.run(job, str(REPO / cfg["book"]), asof,' in out, \
        "preflight must check freshness for the decision date"
    assert '"--asof", today, "--book"' not in out
    assert 'a.format(today=today, asof=asof,' in out


def test_the_standdown_alert_cannot_fire_on_a_morning_that_never_waited():
    """cfg['wait'] stays truthy for cef; only plan.wait says a race was run.

    Without this the 08:30 session -- which deliberately does not wait, because
    the pair published last night -- would leave nav_via None and alert
    "today's NAV was not published" every single morning, training the operator
    to ignore the one alert that means the book did not trade.
    """
    p = _patcher()
    src = _source(p)
    out = p.build(src) if p.MARKER not in src else src
    assert ('if cfg.get("wait") and (plan is None or plan.wait) and nav_via is None:'
            in out)


def test_the_plan_can_only_remove_permission_to_arm():
    """`live` is never set True by the plan, only cleared."""
    p = _patcher()
    src = _source(p)
    out = p.build(src) if p.MARKER not in src else src
    assert "if plan is not None and not plan.may_arm:\n        live = False" in out
    assert "live = True" not in out


def test_the_sleeve_is_told_which_schedule_it_belongs_to():
    """arm()'s decision-age guard is INERT without `--job`.

    The job is not derivable from the book -- preflight records that job "cef"
    maps to book "cef_discount_paper", and since the split "cef" (08:30) and
    "cef_pm" (17:30) share one book and one books-root while having different
    plists and therefore different ceilings. If this ever stops being passed,
    the guard that exists because 2026-09-10 armed 17h23m late goes quiet with
    no error at all, which is the failure shape this repo keeps paying for.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert '"--job", job,' in out


def test_the_panel_phase_is_bounded_by_the_session_ceiling():
    """"Non-fatal to the verdict" is not "non-blocking in time".

    The panel phase is the one phase explicitly allowed to fail, and it is
    still serial-blocking: it cannot stop a session by failing, only by not
    returning. The budget must be DERIVED from the session ceiling, never
    written as a literal -- a literal that stopped matching reality is the
    whole defect class here.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert "budget_min=phase_budget(reserve_min=20)" in out
    assert "def run(args, budget_min=None" in out
    assert "_session_deadline_minutes(job)" in out
    # the budget is measured from the SESSION, not from the phase
    assert "session_started = datetime.now()" in out


def test_an_underivable_ceiling_gets_no_timeout_rather_than_a_guessed_one():
    """NO SILENT FALLBACKS, in the direction that matters here.

    A guessed budget would kill a healthy session; an absent one only leaves it
    as unbounded as it is today. So `phase_budget` returns None -- and `run`
    treats None as "no timeout" -- when the ceiling cannot be derived.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert "if ceiling is None:\n            return None" in out
    assert "if budget_min is None:" in out
