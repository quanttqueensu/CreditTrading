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


# --- the wall-clock session deadline (patch edit 16) ------------------------
#
# THE INCIDENT, read off ~/prod/QUANTT/ops/schedule/logs/cef_2026-09-11.log:
# launchd start 17:15:05, today's NAV published 22:00:52, then nothing until
# 07:09:11 the NEXT MORNING, when the panel phase resumed and the session ran
# preflight, run_book and capture as though it were still the evening. It
# transmitted nothing only because the same-day guard -- which exists to answer
# a completely different question -- happened to say no.
#
# The subprocess budget cannot see this: its timeout is monotonic, and on
# Darwin the monotonic clock stops with the box (measured 2026-09-13 on this
# machine: 3617h of wall clock since boot against 1232h of monotonic). These
# tests pin the other half.

def test_the_deadline_is_checked_at_every_boundary_before_the_trade_phase():
    """Four boundaries, and the last one is the only one that matters.

    Phases 1, 1b and 2 are read-only -- standing down there is tidiness. The
    check before phase 3 is the load-bearing one: nothing has been transmitted
    yet, and an MOC entered after 15:50 ET cannot be cancelled at all, not even
    to correct a legitimate error. A session that has lost track of what time it
    is must not reach place_targets.
    """
    p = _patcher()
    out = p.build(_source(p))
    for phase in ("1. REFRESH", "1b. PANELS", "2. PREFLIGHT", "3. TRADE"):
        assert f'if stood_down_late("{phase}"):' in out
    assert out.count("return LATE_RC") == 4
    assert out.index('stood_down_late("3. TRADE")') < \
        out.index('args = [PY_BIN, "-u", "-m", "src.deploy.run_book"')


def test_capture_is_never_gated_by_the_deadline():
    """Phase 4 is the one phase whose failure policy is "always".

    `ib.fills()` serves the CURRENT TWS session only and IB's 03:00 restart
    empties it, so a fill not captured today is gone for good. A late session
    reaches phase 4 only by having been late during phase 3 -- i.e. after it may
    already have transmitted -- which is precisely when capture matters most.
    Standing down here would have the guard destroy the same record the incident
    it guards against destroys.

    This test exists to stop a future reader "completing the set".
    """
    p = _patcher()
    out = p.build(_source(p))
    i = out.index("rc = run(args, env=env)")
    j = out.index("ops.capture_fills")
    assert "stood_down_late" not in out[i:j]


def test_the_budget_and_the_deadline_read_ONE_derivation():
    """Two derivations drift, and this one is judged from outside as well.

    `ops/doctor.py::_session_deadline_minutes` is what the stuck-session guard
    compares `ps -o etime=` against. If the session computed its own ceiling a
    second way, the guard watching from outside and the session judging itself
    could disagree about whether it is late -- and the whole defect class here
    is a literal that stopped matching the schedule it described.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert out.count("_doc._session_deadline_minutes(job)") == 1
    assert out.count("def session_ceiling()") == 1
    assert "ceiling = session_ceiling()" in out


def test_the_stand_down_writes_no_durable_halt():
    """A stand-down is a SKIPPED SESSION, not a fault.

    A halt file is durable, blocks every later fire and needs a human to clear
    it, so one late night would become an outage -- the failure this desk has
    already had twice in two days, from two small books stopping the $500k
    strategy over their own bookkeeping. The beat records it and the alert says
    it; the next scheduled fire runs normally.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert "write_halt" not in out
    assert 'halt_mod.beat(job, "stood_down_late"' in out
    assert "halt_mod.alert(" in out


def test_the_stand_down_is_distinguishable_from_a_crash():
    """The two want opposite responses from whoever reads the beat.

    A crash wants someone to read a traceback; a stand-down wants someone to
    stop the machine sleeping. So the status is its own string, `late` is
    explicit, and the detail carries the arithmetic that produced the verdict
    rather than only its conclusion. `failed` still exists, separately.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert '"stood_down_late"' in out and '"late": True' in out
    assert '"this_fire_armed": False' in out
    assert '"elapsed_min"' in out and '"ceiling_min"' in out
    assert '"failed"' in out


def test_the_deadline_uses_the_wall_clock_and_not_a_monotonic_counter():
    """The one property the subprocess budget does NOT have.

    `time.monotonic()` on Darwin is mach_absolute_time() and does not advance
    across system sleep -- measured on this machine 2026-09-13, 3617h of wall
    clock since boot against 1232h of monotonic. A session that slept HAS burned
    its window: the auction it meant to trade into has been and gone. Asserted
    on the AST, not on the text, so the explanatory prose above may keep saying
    "monotonic" while no code path may call it.
    """
    import ast
    p = _patcher()
    out = p.build(_source(p))
    assert "(datetime.now() - session_started)" in out
    called = [n.attr for n in ast.walk(ast.parse(out))
              if isinstance(n, ast.Attribute)
              and n.attr in ("monotonic", "monotonic_ns", "perf_counter")]
    assert called == [], f"the session deadline must not read a stopped clock: {called}"


def test_the_stand_down_never_erases_todays_armed_beat():
    """Both directions are a real, dated defect, which is why `carry` exists.

    armed=False would blind two guards at once -- launch_job's same-day guard
    and session_plan's TODAY guard -- and let the evening fallback transmit a
    second order set into the same auction, which is the doubling hazard the
    whole file is shaped around.

    armed=True in a beat FILED the next morning is the 2026-09-10 defect with
    the opposite sign: `date` is the day the beat was filed, so tomorrow's
    session reads it as "today already armed" and refuses itself. One power
    event, two lost sessions (ops/halt.py::beat).

    So it is carried only when this beat lands on the same calendar day as the
    armed beat it replaces -- and `pair_date` follows it, because a pair carried
    without its arm is the fail-closed branch of pair_already_decided().
    """
    p = _patcher()
    out = p.build(_source(p))
    assert ('carry = bool(pdetail.get("armed")) and str(prior.get("date")) '
            '== filed') in out
    assert '"armed": carry,' in out
    assert '"pair_date": pdetail.get("pair_date") if carry else None,' in out


def test_an_underivable_ceiling_leaves_the_deadline_inert_but_says_so():
    """NO SILENT FALLBACKS, in both directions.

    Never a guessed ceiling: that would kill healthy sessions. But never a
    silent None either -- an unannounced None disarms BOTH the phase budgets and
    the wall-clock deadline, and `cef_pm` has no installed plist until
    render_cef_plists.py has run, which is exactly the window in which this
    would otherwise go quiet.
    """
    p = _patcher()
    out = p.build(_source(p))
    assert "NO SESSION CEILING" in out
    assert "        if ceiling is None:\n            return False" in out


# --- helpers, beside the existing _patcher/_source -------------------------

def _built(p):
    src = _source(p)
    return p.build(src) if p.MARKER not in src else src


def _retarget(src, repo):
    """The installed file, with its one boundary line pointed somewhere else.

    Rewriting REPO rather than synthesising a launch_job.py on purpose: build()
    demands every anchor match exactly once, so a hand-written stand-in would be
    testing a file the patch does not edit.
    """
    lines = src.splitlines(True)
    for i, line in enumerate(lines):
        if line.startswith("REPO = Path("):
            lines[i] = f'REPO = Path("{repo}")\n'
            return "".join(lines)
    raise AssertionError("the installed launch_job.py has no REPO line")


def _fake_target(p, tmp_path, provide):
    """A launch_job.py pointed at a tree that supplies exactly `provide`.

    Empty files: the check is deliberately filesystem-only -- it must never
    import prod's code to find out what prod has -- so empty files are a
    faithful stand-in and a tree full of real ones would not be.
    """
    repo = tmp_path / "tree"
    (repo / "ops").mkdir(parents=True)
    for name in sorted(provide):
        parts = name.split(".")
        here, there = p.SOURCE_REPO.joinpath(*parts), repo.joinpath(*parts)
        if here.with_suffix(".py").is_file():
            there.parent.mkdir(parents=True, exist_ok=True)
            there.with_suffix(".py").write_text("")
        else:
            there.mkdir(parents=True, exist_ok=True)
            (there / "__init__.py").write_text("")
    tgt = tmp_path / "launch_job.py"
    tgt.write_text(_retarget(_source(p), repo))
    return tgt, repo


# --- the tests --------------------------------------------------------------

def test_the_required_modules_are_read_out_of_the_built_output():
    """What the patch makes the scheduler need, taken from the patch's output.

    ops.session_plan is the one that matters: W3 Part A put it on the session
    path unguarded, and it is a promotion artifact. pandas is not -- it is an
    environment dependency, and a tree is not "behind" for lacking it.
    """
    p = _patcher()
    req = p.repo_imports(_built(p))
    assert "ops.session_plan" in req
    assert "ops" in req
    for env_dep in ("pandas", "datetime", "subprocess", "pathlib"):
        assert env_dep not in req


def test_the_module_list_is_derived_from_the_text_not_kept_by_hand():
    """The anti-rot property, which is the whole reason this is an AST walk.

    src.deploy.run_book is invoked as a subprocess by the patched output, never
    imported by it, so it must be absent from the real list -- and present the
    moment a snippet actually imports it. A constant list would fail one of
    these two halves, whichever way it was written.
    """
    p = _patcher()
    assert "src.deploy.run_book" not in p.repo_imports(_built(p))
    got = p.repo_imports("from src.deploy import run_book\nimport pandas\n")
    assert "src.deploy.run_book" in got
    assert "pandas" not in got


def test_apply_refuses_when_the_target_tree_lacks_a_module(tmp_path, capsys,
                                                          monkeypatch):
    """The incident this guard exists for, rehearsed.

    Prod is detached at a tag and does not get ops/session_plan.py until someone
    promotes; launch_job.py is outside git and takes effect on the next fire.
    Patch-before-promote therefore produces a scheduler that compiles, passes
    doctor, and dies at `from ops import session_plan` at 08:30 with the book
    already committed to a session it cannot run.
    """
    p = _patcher()
    out = _built(p)
    req = p.repo_imports(out)
    assert "ops.session_plan" in req
    tgt, repo = _fake_target(p, tmp_path,
                             [m for m in req if m != "ops.session_plan"])
    before = tgt.read_bytes()
    monkeypatch.setattr("sys.argv", ["patch", "--apply", "--target", str(tgt)])

    rc = p.main()

    err = capsys.readouterr().err
    assert rc == p.EXIT_MISSING_MODULE and rc != 0
    assert tgt.read_bytes() == before, "refusing must not half-write the target"
    assert not list(tmp_path.glob("*.bak-*")), \
        "no backup for a write that never happened"
    assert "ops.session_plan" in err
    assert str(repo / "ops/session_plan.py") in err
    assert "promote" in err.lower(), "name the promotion that would supply it"


def test_apply_proceeds_when_the_target_tree_has_everything(tmp_path):
    """The guard must be a precondition, not a blanket refusal.

    Called directly rather than through main(): main() would go on to shell out
    to `ps` and then actually write, and a test that depends on whether a cef
    session happens to be running on this machine is a test that flakes at 08:30.
    """
    p = _patcher()
    out = _built(p)
    tgt, _ = _fake_target(p, tmp_path, p.repo_imports(out))
    assert p.check_target_tree_has_imports(tgt, tgt.read_text(), out) == 0


def test_review_mode_is_unchanged_by_the_precondition(tmp_path, capsys,
                                                      monkeypatch):
    """Reading the diff is how you decide to promote; it must keep working.

    Same incomplete tree that makes --apply refuse. Default mode still prints
    the full diff, exits 0, touches nothing and says nothing on stderr -- so the
    guard cannot train anyone to stop running the review step.
    """
    p = _patcher()
    req = p.repo_imports(_built(p))
    tgt, _ = _fake_target(p, tmp_path,
                          [m for m in req if m != "ops.session_plan"])
    before = tgt.read_bytes()
    monkeypatch.setattr("sys.argv", ["patch", "--target", str(tgt)])

    rc = p.main()

    cap = capsys.readouterr()
    assert rc == 0
    assert tgt.read_bytes() == before
    assert "diff only" in cap.out
    assert "from ops import session_plan" in cap.out
    assert cap.err == ""


def test_a_target_whose_repo_cannot_be_read_is_refused_not_guessed():
    """NO SILENT FALLBACKS, in the direction that matters.

    Defaulting to "probably prod" or "probably this tree" would make the guard
    answer a question it cannot answer. Unverifiable means refuse, naming what
    was missing.
    """
    p = _patcher()
    stripped = "".join(l for l in _source(p).splitlines(True)
                       if not l.startswith("REPO = Path("))
    with pytest.raises(SystemExit, match="REPO"):
        p.target_repo(stripped)


def test_a_repo_with_no_ops_is_refused(tmp_path):
    """doctor FAILs on this too ("REPO=... has no ops/ - nothing will run").

    Reported as its own refusal rather than as four missing modules, because
    "the tree is not a checkout" and "the tree is one promotion behind" have
    different remedies and a human should not have to tell them apart.
    """
    p = _patcher()
    empty = tmp_path / "empty"
    empty.mkdir()
    src = _retarget(_source(p), empty)
    assert p.check_target_tree_has_imports(
        tmp_path / "launch_job.py", src, _built(p)) == p.EXIT_MISSING_MODULE


# =========================================================================
# LIMIT C (2026-09-13): the refusal asks BOTH questions.
#
# What these replace asked ONE question, keyed on `prior["date"]` -- the day the
# beat was FILED, not the decision it was about -- and asked it of one job. On
# 2026-09-10 a session started 17:15, the Mac slept, and the beat landed 10:38:32
# on 09-11 for a decision about 09-10. The date-keyed test then refused the 09-11
# session, and a pair-keyed test would have been blind to yesterday evening's
# fallback entirely. Neither question is sufficient alone.
#
# These assert on the BUILT TEXT, not on behaviour, and that is not laziness:
# launch_job.py is outside the repo, outside git, and its main() runs a live
# session, so it cannot be imported. The built source is the only artefact that
# exists before a human runs --apply, and the failure being guarded against is a
# guard that quietly stops asking one of its two questions.
# =========================================================================

def _guard_block(out):
    """Just the two-question guard, sliced out of the built scheduler."""
    assert out.count("THE TWO-QUESTION GUARD") == 1
    return out.split("THE TWO-QUESTION GUARD")[1].split("-- 3. TRADE")[0]


def test_the_refusal_asks_both_questions():
    """BOTH, never one replacing the other.

    Keying only on the pair reopens the double-transmit hole: two fires with
    different decision dates reaching the trade phase before the 15:50 ET
    freeze put two order sets into the SAME auction, and `arm()` cannot see the
    first (`grep -n reqOpenOrders src/deploy/broker/ibkr.py` returns nothing).
    Keying only on the date is what LIMIT C is.
    """
    out = _built(_patcher())
    assert out.count("session_plan.pair_already_decided(beats_now, asof)") == 1
    assert out.count("session_plan.decided_today(beats_now,") == 1
    assert "PAIR GUARD:" in out and "TODAY GUARD:" in out


def test_the_cef_guard_reads_every_beat_and_not_just_this_jobs():
    """The fire it has to catch is the OTHER one.

    Yesterday evening's fallback files under `cef_pm`; this morning is `cef`.
    `last_beat(job)` cannot see across that, and the two cef fires share one
    book, so the blind spot is the whole reason all_beats() exists.
    """
    out = _built(_patcher())
    assert "beats_now = halt_mod.all_beats()" in out
    guard = _guard_block(out)
    cef_branch = guard.split("if plan is not None:")[1].split("\n        else:")[0]
    assert "last_beat" not in cef_branch
    assert "pair_already_decided" in cef_branch and "decided_today" in cef_branch


def test_the_non_cef_books_keep_the_single_job_date_test():
    """They record no decision date at all.

    The live `benchmarks` beat of 2026-09-10 carries armed=True with no
    pair_date, so asking it the PAIR question takes the fail-closed branch of
    pair_already_decided() on every fire and never opens again. phase0 and
    benchmarks keep the guard they had.
    """
    out = _built(_patcher())
    other = _guard_block(out).split("\n        else:")[1]
    assert "prior = halt_mod.last_beat(job)" in other
    assert 'str(prior.get("date")) == today' in other
    assert "session_plan.pair_already_decided" not in other
    assert "session_plan.decided_today" not in other


def test_the_today_question_is_asked_of_a_session_that_crossed_midnight():
    """`today` is bound at process start and a slept session has two dates.

    On 2026-09-10 `today` was still 2026-09-10 while the order went out on
    09-11. Asking only the start date asks about the wrong day. On a normal day
    the two are equal and the list has one entry, so this adds no refusal.
    """
    out = _built(_patcher())
    assert 'guard_now_date = f"{datetime.now():%Y-%m-%d}"' in out
    assert "if guard_now_date != today:" in out
    assert "guard_dates.append(guard_now_date)" in out


def test_the_guard_can_only_remove_permission_to_arm():
    """Preflight, the human halt and the refresh remain the things that grant."""
    guard = _guard_block(_built(_patcher()))
    assert "live = False" in guard
    assert "live = True" not in guard


def test_the_guard_still_runs_after_the_nav_wait_and_not_in_the_plan():
    """The plan is computed in phase 0; on 2026-09-10 the NAV wait ran 17h23m.

    So a plan computed at 17:15 was acted on at 10:38 the next morning against
    a heartbeat that had moved under it. This is the only read of the heartbeat
    taken immediately before the order goes out, and folding it back into the
    plan -- which looks like a tidy simplification -- deletes that fresh read.
    """
    out = _built(_patcher())
    assert out.index("-- 0. THE SESSION PLAN") \
        < out.index("-- 2. PREFLIGHT") \
        < out.index("THE TWO-QUESTION GUARD") \
        < out.index("-- 3. TRADE")


def test_the_dry_run_record_names_which_question_refused():
    """"already traded today" said the same thing for a pair and a date hit.

    The dry-run line is the only durable record of a day the book did not
    trade, and it could not tell the two refusals apart. The old literal is
    DELETED rather than kept as a fallback: `same_day_block` is set only inside
    `if guard_reason:`, so a fallback would be unreachable, and an unreachable
    default on the order path is the exact shape the no-silent-fallback rule
    exists to stop.
    """
    out = _built(_patcher())
    assert "why = (guard_reason if same_day_block" in out
    assert '"already traded today (same-day guard)"' not in out


def test_the_beat_records_which_guard_fired():
    """For the operator and for ops/orient.py. Alongside `armed`, not instead.

    Purely additive: the only readers of a beat are ops/doctor.py and
    ops/preflight.py, and both read only `date` and `status`.
    """
    out = _built(_patcher())
    assert 'detail["guard"] = guard_reason' in out
    assert 'detail["guard_blocker"] = guard_blocker_job' in out


def test_a_blocked_beat_carries_the_BLOCKING_beats_pair_forward():
    """A latent lockout the two-question guard creates, closed here.

    `detail["armed"]` is `live or same_day_block`, so a guarded re-run still
    writes armed=True. Once the guard can be tripped by the OTHER cef fire,
    `last_beat(job)` returns THIS job's previous beat, whose pair may be days
    old or None -- and a None there is an armed beat with no decision date,
    i.e. the fail-closed branch of pair_already_decided(), i.e. every later
    fire refused until a human intervenes. Only the blocking beat is correct.
    """
    out = _built(_patcher())
    assert "blocked_by = halt_mod.all_beats().get(guard_blocker_job) or {}" in out
    assert 'blocked_by.get("session_date")' in out
    assert "(halt_mod.last_beat(job) or {})\n" not in out


def test_force_trade_still_bypasses_the_guard_and_only_a_human_can_set_it():
    """The escape hatch is unchanged, and it is still read from the job env."""
    guard = _guard_block(_built(_patcher()))
    assert 'if live and env.get("FORCE_TRADE") != "1":' in guard


def test_the_guard_reports_a_blocker_exactly_when_it_reports_a_reason():
    """`guard_blocker_job` is truthy iff `guard_reason` is, by construction.

    The beat's carry-forward indexes all_beats() by `guard_blocker_job`, so a
    reason without a blocker would look up None, get {}, and write pair_date
    None onto an armed beat -- the lockout above. Asserted structurally: every
    assignment to guard_reason sits inside a branch that has just confirmed
    guard_blocker_job is truthy, and the TODAY loop breaks only on a hit.
    """
    guard = _guard_block(_built(_patcher()))
    assert guard.count("guard_reason = None") == 1    # the initialiser
    assert guard.count("guard_reason = (") == 3       # PAIR, TODAY, non-cef
    assert guard.count("if guard_blocker_job:") == 2  # PAIR and TODAY
    assert "guard_blocker_job = job" in guard         # the non-cef branch
    assert "if guard_reason:" in guard


def test_the_patched_file_still_compiles():
    compile(_built(_patcher()), "launch_job.py", "exec")
