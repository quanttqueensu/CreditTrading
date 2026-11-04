"""CEF trial 55 (te4): the K0-K3 report lines (quantt/session/drawdown.py `thin_stop_record`), on synthetic records.

results/cef/PREREG_THIN_TRADE_ELIGIBLE_2026-11-03.md §6.3 requires report lines for K0-K3 in the
activation release, "in report mode and tested", and the team lead's ruling of 2026-11-03 on a
short skipped at send ("accept it and label it") needs the label. Every input here is a literal:
a calendar of consecutive sessions, plan.json / send.json dicts per session, an equity series,
positions, closes and thresholds. Each test fails on the code before this commit, which has no
`thin_stop_record`.

The runner's side (plan.json carries `thin_stops` only with the key set, and the label read from
the previous session's send.json) is in tests/test_trade_eligible_runner.py.
"""
import datetime as dt
import json

import pytest

from quantt.session import drawdown as ddm

D0 = dt.date(2026, 1, 5)
CAL = [D0 + dt.timedelta(days=i) for i in range(400)]       # synthetic sessions, one a day
SESSION = CAL[300]                                          # this decide's session
ASOF = CAL[299]                                             # its as-of: the session before
LINES = {"thin_k1_episode_drawdown": 0.10, "thin_k2_max_name_frac": 0.9,
         "thin_k3_net_run": 0.25, "thin_k3_net_once": 0.8}
OK = {"status": "OK", "asof": ASOF.isoformat()}


def prev(d):
    return CAL[CAL.index(d) - 1]


def back(k):
    """The session k sessions before SESSION."""
    return CAL[300 - k]


def plan(reduced=False, *, refusals=(), execution="late_market", k3=None, key=True):
    p = {"refusals": list(refusals), "execution": execution}
    if key:
        p["thin_session"] = {"reduced": reduced}
        # A decide with the key set always records its K3 line: N/A when the session before it
        # was not a reduced one.
        p["thin_stops"] = {"K3": k3 if k3 is not None else {"verdict": ddm.NOT_APPLICABLE}}
    return p


def reader(days: dict, default="plain"):
    """read_day over `days` {session: {"plan", "send"}}; other sessions get a plan with the key
    set and nothing reduced ("plain"), the key absent ("absent"), or no plan.json ("missing")."""
    def read(d):
        if d in days:
            return {"plan": days[d].get("plan"), "send": days[d].get("send")}
        if default == "plain":
            return {"plan": plan(), "send": None}
        if default == "absent":
            return {"plan": plan(key=False), "send": None}
        return {"plan": None, "send": None}
    return read


def record(days=None, *, default="plain", dd=None, current=None, series=None, positions=None,
           closes=None, lines=None):
    return ddm.thin_stop_record(
        asof=ASOF, session_date=SESSION, drawdown=dd or OK, current=current or {"reduced": False},
        previous_session=prev, read_day=reader(days or {}, default),
        series=series if series is not None else [(ASOF, 100_000.0)],
        positions=positions or {}, closes=closes or {}, thresholds=lines or LINES)


# --------------------------------------------------------------- the episode and K0

def test_no_reduced_decision_reads_no_episode_and_nothing_applies():
    r = record()
    assert r["report_only"] is True
    assert r["episode"]["status"] == "NONE" and r["episode"]["reduced_sessions"] == []
    assert r["K0"]["verdict"] == ddm.CLEAR
    assert r["K1"]["verdict"] == r["K2"]["verdict"] == r["K3"]["verdict"] == ddm.NOT_APPLICABLE
    assert r["send_skip"]["applies"] is False


@pytest.mark.parametrize("status,want", [("HALVE", ddm.KILLED), ("KILL", ddm.KILLED),
                                         ("OK", ddm.CLEAR), ("UNMEASURED", ddm.CLEAR)])
def test_k0_kills_on_halve_or_kill_during_an_open_episode(status, want):
    r = record({back(5): {"plan": plan(True)}}, dd={"status": status, "asof": "x"})
    assert r["episode"]["status"] == "OPEN" and r["episode"]["reduced_sessions"] == [back(5)]
    assert r["K0"]["verdict"] == want


@pytest.mark.parametrize("k,want", [(62, "OPEN"), (63, "NONE")])
def test_an_episode_is_open_for_62_sessions_after_its_last_reduced_decision(k, want):
    """§4.2: completed 63 sessions after its last reduced decision with no new one."""
    r = record({back(k): {"plan": plan(True)}}, dd={"status": "HALVE", "asof": "x"})
    assert r["episode"]["status"] == want
    assert r["K0"]["verdict"] == (ddm.KILLED if want == "OPEN" else ddm.CLEAR)


def test_runs_fewer_than_63_sessions_apart_merge_into_one_episode():
    r = record({back(10): {"plan": plan(True)}, back(70): {"plan": plan(True)},
                back(132): {"plan": plan(True)}, back(200): {"plan": plan(True)}})
    assert r["episode"]["reduced_sessions"] == sorted([back(10), back(70), back(132)])


def test_a_missing_or_unreadable_record_reads_unmeasured_and_k0_cannot_clear_a_halve():
    for days, default in (({}, "missing"),
                          ({back(3): {"plan": None}}, "plain")):
        r = record(days, default=default, dd={"status": "HALVE", "asof": "x"})
        assert r["episode"]["status"] == ddm.UNMEASURED
        assert r["K0"]["verdict"] == ddm.UNMEASURED
        assert r["K1"]["verdict"] == ddm.UNMEASURED
    # The as-of session's own record missing: whether K2, K3 and the send label apply is unknown.
    r = record({}, default="missing")
    assert r["K2"]["verdict"] == r["K3"]["verdict"] == ddm.UNMEASURED
    assert r["send_skip"]["applies"] == ddm.UNMEASURED
    assert any("SEND SKIP" in x and "UNMEASURED" in x for x in ddm.thin_stop_lines(r))

    def bad(d):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")
    r = ddm.thin_stop_record(asof=ASOF, session_date=SESSION, drawdown=OK, current={},
                             previous_session=prev, read_day=bad, series=[], positions={},
                             closes={}, thresholds=LINES)
    assert r["episode"]["status"] == ddm.UNMEASURED and "ValueError" in r["episode"]["why"]


def test_a_session_decided_with_the_key_absent_ends_the_walk():
    r = record({back(3): {"plan": plan(key=False)}, back(5): {"plan": plan(True)}},
               dd={"status": "KILL", "asof": "x"})
    assert r["episode"]["status"] == "NONE" and r["K0"]["verdict"] == ddm.CLEAR
    assert "key absent" in r["episode"]["why"]


def test_a_refused_reduced_plan_is_not_a_reduced_decision():
    r = record({back(4): {"plan": plan(True, refusals=[{"gate": "data", "detail": "x"}])}},
               dd={"status": "HALVE", "asof": "x"})
    assert r["episode"]["status"] == "NONE"


# --------------------------------------------------------------- K1

def _k1_days():
    """Reduced decisions on the sessions 6 and 4 back: their earning days are 5 and 3 back."""
    return {back(6): {"plan": plan(True)}, back(4): {"plan": plan(True)}}


def _series(eq_by_k: dict):
    return sorted((back(k), v) for k, v in eq_by_k.items())


def test_k1_compounds_the_episodes_earning_days_and_trips_at_its_line():
    # earning day 5 back: 100 -> 95 (-5%); earning day 3 back: 96 -> 90.24 (-6%).
    series = _series({6: 100.0, 5: 95.0, 4: 96.0, 3: 90.24, 1: 90.0})
    r = record(_k1_days(), series=series + [(ASOF, 90.0)])
    want = 1.0 - (0.95 * 0.94)
    assert r["K1"]["earning_days"] == 2
    assert r["K1"]["drawdown"] == pytest.approx(want, abs=1e-8)
    assert r["K1"]["verdict"] == ddm.TRIPPED                       # 0.107 >= 0.10
    r = record(_k1_days(), series=series + [(ASOF, 90.0)],
               lines={**LINES, "thin_k1_episode_drawdown": 0.11})
    assert r["K1"]["verdict"] == ddm.CLEAR
    r = record(_k1_days(), series=series + [(ASOF, 90.0)],
               lines={**LINES, "thin_k1_episode_drawdown": None})
    assert r["K1"]["verdict"] == ddm.UNMEASURED and r["K1"]["drawdown"] == pytest.approx(want)


def test_k1_reads_unmeasured_on_a_missing_equity_row_and_never_reads_past_the_asof():
    r = record(_k1_days(), series=_series({6: 100.0, 5: 95.0, 4: 96.0}) + [(ASOF, 90.0)])
    assert r["K1"]["verdict"] == ddm.UNMEASURED and str(back(3)) in r["K1"]["why"]
    r = record(_k1_days(), series="no eod_equity.csv")
    assert r["K1"]["verdict"] == ddm.UNMEASURED and "no eod_equity.csv" in r["K1"]["why"]
    # A reduced decision on the as-of session earns on THIS session, after the as-of: not counted.
    r = record({back(1): {"plan": plan(True)}}, series=[(ASOF, 90.0)])
    assert r["K1"]["earning_days"] == 0 and r["K1"]["verdict"] == ddm.CLEAR
    with pytest.raises(AssertionError, match="lookahead"):
        record(_k1_days(), series=[(ASOF, 1.0), (SESSION, 1.0)])


# --------------------------------------------------------------- K2, K3

PRICES = {"A": 10.0, "B": 20.0, "C": 5.0}


def test_k2_and_k3_read_the_close_after_a_reduced_decision():
    days = {back(1): {"plan": plan(True)}}
    pos = {"A": 4000, "B": -1000, "C": 0}                  # +40k, -20k on 50k of equity
    r = record(days, positions=pos, closes=PRICES, series=[(ASOF, 50_000.0)])
    assert r["K2"]["stat"] == pytest.approx(0.8) and r["K2"]["verdict"] == ddm.CLEAR
    assert r["K3"]["net"] == pytest.approx(0.4) and r["K3"]["run"] == 1
    assert r["K3"]["verdict"] == ddm.CLEAR
    r = record(days, positions={"A": 5000, "B": -500}, closes=PRICES, series=[(ASOF, 50_000.0)])
    assert r["K2"]["stat"] == pytest.approx(1.0) and r["K2"]["verdict"] == ddm.TRIPPED
    # net exactly 0.8: AT the once line is not above it, and one close is not a run of three.
    assert r["K3"]["net"] == pytest.approx(0.8) and r["K3"]["verdict"] == ddm.CLEAR


def test_k3_trips_above_the_once_line_or_on_three_reduced_closes_in_sequence():
    pos, eq = {"A": 3000, "B": -500}, [(ASOF, 50_000.0)]    # net 20k / 50k = 0.4 > run 0.25
    above = {"net": 0.3, "verdict": ddm.CLEAR}
    below = {"net": 0.1, "verdict": ddm.CLEAR}
    na = {"verdict": ddm.NOT_APPLICABLE}
    # Two earlier reduced closes above the run line, a full session (K3 N/A) between them.
    days = {back(1): {"plan": plan(True)}, back(2): {"plan": plan(True, k3=above)},
            back(3): {"plan": plan(False, k3=na)}, back(4): {"plan": plan(True, k3=above)}}
    r = record(days, positions=pos, closes=PRICES, series=eq)
    assert r["K3"]["run"] == 3 and r["K3"]["verdict"] == ddm.TRIPPED
    days[back(4)] = {"plan": plan(True, k3=below)}
    r = record(days, positions=pos, closes=PRICES, series=eq)
    assert r["K3"]["run"] == 2 and r["K3"]["verdict"] == ddm.CLEAR
    days[back(4)] = {"plan": plan(True, k3={"verdict": ddm.UNMEASURED, "why": "x"})}
    r = record(days, positions=pos, closes=PRICES, series=eq)
    assert r["K3"]["verdict"] == ddm.UNMEASURED
    r = record({back(1): {"plan": plan(True)}}, positions={"A": 5000}, closes=PRICES, series=eq)
    assert r["K3"]["net"] == pytest.approx(1.0) and r["K3"]["verdict"] == ddm.TRIPPED


def test_k2_k3_unmeasured_without_equity_a_close_or_a_line_and_n_a_after_a_full_session():
    days = {back(1): {"plan": plan(True)}}
    r = record(days, positions={"A": 1}, closes=PRICES, series=[(back(2), 1.0)])
    assert r["K2"]["verdict"] == r["K3"]["verdict"] == ddm.UNMEASURED
    r = record(days, positions={"Z": 1}, closes=PRICES, series=[(ASOF, 1.0)])
    assert "Z" in r["K2"]["why"]
    r = record(days, positions={"A": 1}, closes=PRICES, series=[(ASOF, 1.0)],
               lines={**LINES, "thin_k2_max_name_frac": None, "thin_k3_net_once": None})
    assert r["K2"]["verdict"] == r["K3"]["verdict"] == ddm.UNMEASURED
    assert r["K2"]["stat"] == pytest.approx(10.0)
    r = record({back(1): {"plan": plan(False)}}, positions={"A": 1}, closes=PRICES)
    assert r["K2"]["verdict"] == r["K3"]["verdict"] == ddm.NOT_APPLICABLE


# --------------------------------------------------------------- the send-time skip label

def test_the_send_time_skip_after_a_reduced_decision_is_labelled():
    skipped = ["cef-20260105-PDI-x: PDI shortable=False at send; skipped, the rest go"]
    r = record({back(1): {"plan": plan(True), "send": {"skipped": skipped}}})
    assert r["send_skip"] == {"session": ASOF, "applies": True, "skipped_at_send": skipped,
                              "lost_short": True}
    r = record({back(1): {"plan": plan(True), "send": {"skipped": []}}})
    assert r["send_skip"]["lost_short"] is False
    r = record({back(1): {"plan": plan(True), "send": None}})
    assert r["send_skip"]["lost_short"] == ddm.UNMEASURED
    r = record({back(1): {"plan": plan(True), "send": {"exit": "SENT"}}})
    assert r["send_skip"]["lost_short"] == ddm.UNMEASURED
    r = record({back(1): {"plan": plan(True, execution=None), "send": None}})
    assert r["send_skip"]["applies"] is False and "cls" in r["send_skip"]["why"]
    r = record({back(1): {"plan": plan(False), "send": {"skipped": skipped}}})
    assert r["send_skip"]["applies"] is False


def test_the_lines_render_every_stop():
    days = {back(1): {"plan": plan(True), "send": {"skipped": ["x"]}}}
    lines = ddm.thin_stop_lines(record(days, positions={"A": 100}, closes=PRICES))
    text = "\n".join(lines)
    for word in ("episode OPEN", "K0", "K1", "K2", "K3", "SEND SKIP", "report only"):
        assert word in text, word
    assert ddm.thin_stop_lines(ddm.thin_unmeasured_record(ASOF, "boom")) == [
        "  TE4 STOPS (report only): UNMEASURED: boom"]


# --------------------------------------------------------------- in the session (run.py)

def _prior_session(state, d, plan_, send=None):
    day = state / d.isoformat()
    day.mkdir(parents=True, exist_ok=True)
    (day / "plan.json").write_text(json.dumps(plan_))
    if send is not None:
        (day / "send.json").write_text(json.dumps(send))


@pytest.mark.parametrize("eod,k0", [("ok", ddm.CLEAR), ("halve", ddm.KILLED)])
def test_the_next_decide_labels_a_short_skipped_at_the_reduced_sessions_send(
        tmp_path, monkeypatch, eod, k0):
    """The team lead's ruling (2026-11-03): a short skipped at the late SEND after a reduced
    decision is accepted and labelled. The send path is unchanged; the next decide reads that
    session's plan.json and send.json and records the label, with K0 and K2/K3 on its close."""
    from quantt.session import run as rn
    from quantt.session.tests import test_missing_nav_hold as M
    from quantt.session.tests import test_trade_eligible_noop as N
    from quantt.session.tests.test_trade_eligible_runner import TE4_SPEC, run
    base, bk = N.thin_books(tmp_path / "b", monkeypatch)
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    state = tmp_path / "r" / "state"
    skipped = ["cef-20260925-SYD-1: SYD shortable=False at send; skipped, the rest go"]
    _prior_session(state, M.ASOF, {"refusals": [], "execution": "late_market",
                                   "thin_session": {"reduced": True},
                                   "thin_stops": {"K3": {"verdict": ddm.NOT_APPLICABLE}}},
                   {"skipped": skipped, "exit": "SENT"})
    _prior_session(state, dt.date(2026, 9, 24), {"refusals": []})        # the key absent then
    code, state, _, _ = run(tmp_path / "r", TE4_SPEC, bk["held"], eod)
    assert code == rn.EXIT_PLANNED
    plan = M._plan(state)
    st = plan["thin_stops"]
    assert st["report_only"] is True
    assert st["send_skip"] == {"session": "2026-09-25", "applies": True,
                               "skipped_at_send": skipped, "lost_short": True}
    assert st["episode"]["status"] == "OPEN" and st["episode"]["reduced_sessions"] == ["2026-09-25"]
    assert st["K0"]["verdict"] == k0
    assert plan["thin_session"]["stopped_by"] == (None if eod == "ok" else "K0")
    # K2/K3 on the 09-25 close: measured (the spec sets no line, so their verdicts are UNMEASURED).
    assert isinstance(st["K2"]["stat"], float) and isinstance(st["K3"]["net"], float)
    assert st["K2"]["verdict"] == st["K3"]["verdict"] == ddm.UNMEASURED
    assert st["K1"]["earning_days"] == 0              # 09-25's earning day is 09-28, after the as-of
    run_rec = json.loads(sorted((state / "2026-09-28" / "runs").glob("*.json"))[-1].read_text())
    assert run_rec["thin_stops"] == st


def test_with_the_key_set_every_decide_carries_the_lines_and_a_failure_is_recorded(
        tmp_path, monkeypatch):
    from quantt.session import run as rn
    from quantt.session.tests import test_missing_nav_hold as M
    from quantt.session.tests import test_trade_eligible_noop as N
    from quantt.session.tests.test_trade_eligible_runner import TE4_SPEC, run
    base, bk = N.thin_books(tmp_path / "b", monkeypatch)
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    code, state, _, _ = run(tmp_path / "plain", TE4_SPEC, bk["held"], "ok")
    st = M._plan(state)["thin_stops"]
    # No earlier record in this state dir: the episode walk names the missing plan.json.
    assert st["episode"]["status"] == ddm.UNMEASURED and "no plan.json" in st["episode"]["why"]
    assert code == rn.EXIT_PLANNED

    def boom(**kw):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(ddm, "thin_stop_record", boom)
    code, state, _, _ = run(tmp_path / "boom", TE4_SPEC, bk["held"], "ok")
    assert code == rn.EXIT_PLANNED                    # report only: the session goes on
    assert M._plan(state)["thin_stops"] == {"report_only": True, "asof": "2026-09-25",
                                            "unmeasured": "RuntimeError: synthetic"}
