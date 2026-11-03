"""CEF trial 55 (te4) in the runner: the paper declaration, the endpoint check, K0, and the gross pin.

results/cef/PREREG_THIN_TRADE_ELIGIBLE_2026-11-03.md (approved 2026-11-03, PAPER ONLY), §1.2,
§1.3 items 5-6, §6.3, and the owner's terms in its "Approval" section. What the runner does is in
quantt/session/run.py, the `_thin_*` functions and `thin_rule_for`; the key-absent no-op is
tests/test_trade_eligible_noop.py.

Every test here sets the key (`TE4_SPEC`: the fixture spec of the no-op pins with
`below_min_names = "trade_eligible"` and floor 4, in memory) and each FAILS on the code before
this commit (29ba857), where the runner passes no declaration and the sleeve refuses every
decide under the key ("PAPER ONLY ... account=None"): the session is a FAIL there, whatever the
endpoint, the drawdown or the panel. The tests that must refuse also check WHERE they refuse
(before any sleeve is built), which the old code's refusal is not.

THE GROSS PIN (the owner's term 3: "a test pins that no drawdown status can increase gross").
On the thin panel at 5 and 4 eligible names and on the complete panel (12 eligible), flat and
held books, under every drawdown record (OK, HALVE, KILL, a stale series, no series), the
projected gross after the plan (sum over names of |target shares x as-of close|):
  * under any status but OK is at most the gross under OK, and equals the key-absent session's;
  * with the key absent it is the same under every status (report mode acts on nothing);
  * on a full session it is the key-absent session's under EVERY status, orders and targets
    included (K0 never touches a session the reduced build would not run on).

Hermetic: test_run's FakeClient (with `trading_endpoint` set where the key needs it), fixed
clocks, the refresh a fixture, no CEFConnect, netguard refuses any socket.
"""
import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from quantt.broker import alpaca
from quantt.session import nav_gate as ng
from quantt.session import run as rn
from quantt.session.tests import test_missing_nav_hold as M
from quantt.session.tests import test_trade_eligible_noop as N
from quantt.session.tests.test_combine_noop import SYN_SPEC, _client
from quantt.session.tests.test_run import BOOK

LIVE = "https://api.alpaca.markets"           # Alpaca's live trading host: what must refuse
STATUSES = ("ok", "halve", "kill", "stale", "absent")


def te4(spec: dict, floor: int = 4) -> dict:
    s = copy.deepcopy(spec)
    s["frozen"].update(below_min_names="trade_eligible", below_min_names_floor=floor)
    return s


TE4_SPEC = te4(N.THIN_SPEC)


class _Spy:
    """deps.targets, recording every call's keywords."""

    def __init__(self, spec):
        self.spec, self.calls = spec, []

    def __call__(self, a, h, eq, op, **kw):
        self.calls.append(dict(kw))
        return rn.sleeve_targets(self.spec, rn.spec_params(self.spec)["capital_usd"], a, h, eq,
                                 op, **kw)


def run(work: Path, spec, holdings: dict, eod: str, *, endpoint=alpaca.PAPER_BASE,
        drawdown="report", now=None, execution=None, armed=False, key=None, sleeves=None,
        client_attrs=None):
    """One session as M._session builds it, with the drawdown mode, the client's endpoint
    (None: the attribute is absent) and the combiner's sleeves as arguments, and the sleeve
    call spied on. A flat book has a filled order in its history (not an opening session).
    Returns (exit, state, client, spy)."""
    from ops.schedule.nyse_calendar import previous_trading_day
    from src.deploy.sleeves import cef_discount as cefmod
    state = work / "state"
    N.write_eod(state, eod)
    if key is not None:
        prev = previous_trading_day(M.SESSION)
        M._write_priors(state, {prev: M._prior_plan(prev)})
    if armed:
        (state / "AUTO_ARMED").touch()
    uni = rn.spec_params(spec)["universe"]
    closes = {s: v[0] for s, v in rn.last_closes(cefmod.PX_PATH, M.ASOF, uni).items()}
    now = now or M.EVE
    c = _client(state, holdings, closes, now)
    if not holdings:
        c._closed = list(N.FILLED_BEFORE)
    if endpoint is not None:
        c.trading_endpoint = endpoint
    for k, v in (client_attrs or {}).items():
        setattr(c, k, v)
    spy = _Spy(spec)
    deps = rn.Deps(
        client=c, env={"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0"},
        refresh=lambda a, t: rn.RefreshResult(exit=0, tail="fixture"),
        closes=lambda a, u: rn.last_closes(cefmod.PX_PATH, a, u),
        navs=lambda a, u: rn.last_navs(cefmod.NAV_PATH, a, u),
        history=lambda a, u, r: rn.close_history(cefmod.PX_PATH, a, u, r),
        targets=spy, halts=lambda: [], utcnow=lambda: now.astimezone(dt.timezone.utc),
        out=M._Quiet(), execution=execution or M.LATE_SCALE, stale_nav=ng.REPORT,
        nav_gate=ng.PanelGate(nav_path=cefmod.NAV_PATH, reader=M._refused),
        drawdown=drawdown, sleeves=sleeves)
    if key is not None:
        deps.missing_nav, deps.missing_nav_max_sessions = key, M.MAX_SESSIONS
    return rn.run_session(BOOK, spec, deps), state, c, spy


def last_run(state: Path) -> dict:
    runs = sorted(state.rglob("runs/*.json"))
    return json.loads(runs[-1].read_text())


def gross(plan: dict, state_closes: dict) -> float:
    """Projected gross after the plan: sum of |target shares x as-of close|."""
    return sum(abs(t["target"]) * state_closes[s] for s, t in plan["targets"].items())


def closes_of(spec) -> dict:
    from src.deploy.sleeves import cef_discount as cefmod
    uni = rn.spec_params(spec)["universe"]
    return {s: v[0] for s, v in rn.last_closes(cefmod.PX_PATH, M.ASOF, uni).items()}


@pytest.fixture
def books(tmp_path, monkeypatch):
    return N.thin_books(tmp_path / "books", monkeypatch)


# --------------------------------------------------------------- the paper declaration

def test_the_runner_declares_paper_and_passes_k0_to_the_sleeve(tmp_path, monkeypatch, books):
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    code, state, _, spy = run(tmp_path / "r", TE4_SPEC, bk["held"], "ok")
    assert code == rn.EXIT_PLANNED
    assert spy.calls == [{"account": "paper", "thin_rule": {"stop": None}}]
    ts = M._plan(state)["thin_session"]
    assert ts["reduced"] is True and ts["stopped_by"] is None and ts["decided"] is True
    assert (ts["eligible"], ts["eligible_names"]) == (5, list(N.THIN_ELIGIBLE[:5]))
    assert (ts["rule"], ts["floor"], ts["min_names"]) == ("trade_eligible", 4, 6)
    assert ts["k0"] == {"status": "OK", "asof": M.ASOF.isoformat(), "stop": None}


def test_a_non_paper_endpoint_refuses_before_any_sleeve_is_built(tmp_path, monkeypatch, books):
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    code, state, c, spy = run(tmp_path / "live", TE4_SPEC, bk["held"], "ok", endpoint=LIVE)
    assert code == rn.EXIT_FAIL
    err = last_run(state)["error"]
    assert "SessionError" in err and "trade_eligible" in err and LIVE in err
    assert spy.calls == [] and not c.accepted
    assert not (state / M.SESSION.isoformat() / "plan.json").exists()
    # The check is what refuses: the same session with the check's reference moved to that
    # endpoint (in this test only) builds the sleeve and plans.
    monkeypatch.setattr(alpaca, "PAPER_BASE", LIVE)
    code, _, _, spy = run(tmp_path / "moved", TE4_SPEC, bk["held"], "ok", endpoint=LIVE)
    assert code == rn.EXIT_PLANNED and spy.calls


def test_a_client_that_names_no_endpoint_refuses(tmp_path, monkeypatch, books):
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    code, state, _, spy = run(tmp_path / "r", TE4_SPEC, bk["held"], "ok", endpoint=None)
    assert code == rn.EXIT_FAIL and spy.calls == []
    assert "trading_endpoint" in last_run(state)["error"]


def test_the_key_without_risk_drawdown_fails_at_session_start(tmp_path, monkeypatch, books):
    """The owner's answer 4: loud and closed, at the decide and at the late SEND alike."""
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    for label, now in (("decide", M.EVE), ("send", M.SEND)):
        code, state, c, spy = run(tmp_path / label, TE4_SPEC, bk["held"], "ok", drawdown=None,
                                  now=now, armed=True)
        assert code == rn.EXIT_FAIL and spy.calls == [] and not c.accepted, label
        err = last_run(state)["error"]
        assert "risk.drawdown" in err and "trade_eligible" in err, label
    # Key absent, the same book json is today's session.
    code, _, _, spy = run(tmp_path / "absent", N.THIN_SPEC, bk["held"], "ok", drawdown=None)
    assert code == rn.EXIT_PLANNED and spy.calls == [{}]


def test_a_combined_book_with_the_key_fails_and_a_combined_sleeve_with_it_refuses(
        tmp_path, monkeypatch, books):
    from quantt.session import combine as cmb
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    # The book spec sets it: refused at session start.
    sp = tmp_path / "plain.frozen.json"
    sp.write_text(json.dumps(N.THIN_SPEC))
    bj = tmp_path / "book.json"
    bj.write_text(json.dumps({"book_id": "t", "sleeves": [
        {"name": "cef_discount", "enabled": True, "spec_path": sp.name, "risk_budget": 1.0}]}))
    sleeves = cmb.load_sleeves(bj, sp, tmp_path, rn._sleeve_target_fn)
    code, state, c, spy = run(tmp_path / "book", TE4_SPEC, bk["held"], "ok", sleeves=sleeves)
    assert code == rn.EXIT_FAIL and spy.calls == [] and not c.accepted
    assert "combined book" in last_run(state)["error"]
    # Only a sleeve's own spec sets it: the combiner builds it (construction checks only the
    # declaration's value) and the sleeve refuses at its decide, because the combiner passes no
    # declaration. Nothing is sent.
    tp = tmp_path / "te4.frozen.json"
    tp.write_text(json.dumps(TE4_SPEC))
    bj.write_text(json.dumps({"book_id": "t", "sleeves": [
        {"name": "cef_discount", "enabled": True, "spec_path": tp.name, "risk_budget": 1.0}]}))
    sleeves = cmb.load_sleeves(bj, tp, tmp_path, rn._sleeve_target_fn)
    code, state, c, _ = run(tmp_path / "sleeve", N.THIN_SPEC, bk["held"], "ok", sleeves=sleeves)
    assert code == rn.EXIT_FAIL and not c.accepted
    assert "PAPER ONLY" in last_run(state)["error"]


def test_the_callers_that_build_without_deciding_still_work_with_the_key_set(
        tmp_path, monkeypatch):
    """The owner's answer 1: run.py's spec_panel, ops/common.py's deployed_tickers and
    combine.py's load_sleeves build the sleeve every session without deciding, and must keep
    working with the key set. The one of them whose callable decides (the combiner's) passes no
    declaration, so it refuses rather than decide by default; the runner's own call passes it
    explicitly (test above)."""
    from ops.common import deployed_tickers
    from quantt.session import combine as cmb
    from src.deploy.registry import build_sleeve
    base, _ = N.thin_books(tmp_path / "b", monkeypatch)
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    from src.deploy.sleeves import cef_discount as cefmod
    assert rn.spec_panel(TE4_SPEC) == rn.Panel(cefmod.PX_PATH, cefmod.NAV_PATH)
    bj = tmp_path / "inline.json"
    bj.write_text(json.dumps({"sleeves": [{"name": "core", "spec": TE4_SPEC,
                                           "capital_usd": 100_000.0}]}))
    assert deployed_tickers(bj) == {"core": list(TE4_SPEC["frozen"]["universe"])}
    tp = tmp_path / "te4.frozen.json"
    tp.write_text(json.dumps(TE4_SPEC))
    bj.write_text(json.dumps({"book_id": "t", "sleeves": [
        {"name": "core", "enabled": True, "spec_path": tp.name, "risk_budget": 1.0}]}))
    (entry,) = cmb.load_sleeves(bj, tp, tmp_path, rn._sleeve_target_fn, panel_of=rn.spec_panel)
    assert entry.universe == tuple(sorted(TE4_SPEC["frozen"]["universe"]))
    with pytest.raises(ValueError, match="PAPER ONLY"):
        entry.targets(M.ASOF, {}, 100_000.0, False)
    # Declared but without the extra: still refused (the sleeve's `_thin_rule`).
    with pytest.raises(ValueError, match="thin_rule"):
        rn.sleeve_targets(TE4_SPEC, 100_000.0, M.ASOF, {}, 100_000.0, False, account="paper")
    assert build_sleeve(TE4_SPEC, 0.0).instruments() == list(TE4_SPEC["frozen"]["universe"])


# --------------------------------------------------------------- K0

@pytest.mark.parametrize("eod", ["halve", "kill", "stale", "absent"])
@pytest.mark.parametrize("n", [5, 4])
def test_k0_flattens_a_reduced_session_unless_the_drawdown_reads_ok(tmp_path, monkeypatch,
                                                                     books, n, eod):
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, n)
    for book in ("held", "flat"):
        code, state, c, spy = run(tmp_path / book, TE4_SPEC, bk[book], eod)
        assert code == (rn.EXIT_PLANNED if book == "held" else rn.EXIT_NOTHING), (book, code)
        plan = M._plan(state)
        ts = plan["thin_session"]
        assert ts["k0"]["status"] == N.EOD_STATUS[eod]
        assert ts["k0"]["stop"]["by"] == "K0"
        assert spy.calls == [{"account": "paper", "thin_rule": {"stop": ts["k0"]["stop"]}}]
        assert ts["stopped_by"] == "K0" and ts["reduced"] is False
        assert {t["target"] for t in plan["targets"].values()} == {0}       # every name FLAT
        assert all("reduced build stopped by K0" in t["reason"] for t in plan["targets"].values())
        assert not c.accepted


@pytest.mark.parametrize("n", [5, 4])
def test_at_ok_the_reduced_book_is_built_on_both_sides(tmp_path, monkeypatch, books, n):
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, n)
    for book in ("held", "flat"):
        code, state, _, _ = run(tmp_path / book, TE4_SPEC, bk[book], "ok")
        assert code == rn.EXIT_PLANNED
        plan = M._plan(state)
        assert plan["thin_session"]["reduced"] is True
        tg = {s: t["target"] for s, t in plan["targets"].items() if s in N.THIN_ELIGIBLE[:n]}
        assert any(v > 0 for v in tg.values()) and any(v < 0 for v in tg.values()), tg


def test_below_the_floor_k0_records_no_stop_on_the_build(tmp_path, monkeypatch, books):
    """At 3 eligible (under the floor) no reduced build could run, so `stopped_by` stays None
    even when K0 passes a stop: only a stop that removed a build is recorded as one."""
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 3)
    code, state, _, _ = run(tmp_path / "r", TE4_SPEC, bk["held"], "halve")
    ts = M._plan(state)["thin_session"]
    assert code == rn.EXIT_PLANNED
    assert ts["k0"]["stop"]["by"] == "K0" and ts["stopped_by"] is None and not ts["reduced"]
    assert ts["eligible"] == 3


def test_k0_reads_only_an_exact_ok():
    assert rn._thin_k0_stop({"status": "OK", "asof": "x"}) is None
    for status in ("HALVE", "KILL", "UNMEASURED", "ok", " OK", None, 0, True):
        stop = rn._thin_k0_stop({"status": status, "asof": "x"})
        assert stop["by"] == "K0" and repr(status) in stop["why"], status
    with pytest.raises(rn.SessionError, match="no drawdown record"):
        rn._thin_k0_stop(None)


def test_a_data_refusal_records_the_rule_and_k0_but_no_sleeve_answer(tmp_path, monkeypatch, books):
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    from src.deploy.sleeves import cef_discount as cefmod
    import pandas as pd
    nav = pd.read_parquet(cefmod.NAV_PATH)
    nav = nav[~((pd.to_datetime(nav["date"]) == pd.Timestamp(M.ASOF)) & (nav["ticker"] == "SYA"))]
    nav.to_parquet(cefmod.NAV_PATH)
    code, state, _, spy = run(tmp_path / "r", TE4_SPEC, bk["held"], "ok")
    assert code == rn.EXIT_REFUSED and spy.calls == []
    ts = M._plan(state)["thin_session"]
    assert ts["decided"] is False and ts["eligible"] is None and ts["reduced"] is False
    assert ts["k0"]["status"] == "OK"


def test_with_a_missing_nav_hold_the_reduced_build_never_runs_and_the_day_is_refused(
        tmp_path, monkeypatch, books):
    """§7.7 / Q10 at the runner: at the final check, a held fund out of the cross-section
    leaves the other four eligible; the sleeve takes today's min_names path with its tag, and
    the runner refuses the day as without the key (never a reduced book beside a hold)."""
    base, bk = books
    N.thin_panel(base, tmp_path / "p", monkeypatch, 5)
    from src.deploy.sleeves import cef_discount as cefmod
    import pandas as pd
    nav = pd.read_parquet(cefmod.NAV_PATH)
    nav = nav[~((pd.to_datetime(nav["date"]) == pd.Timestamp(M.ASOF)) & (nav["ticker"] == "SYE"))]
    nav.to_parquet(cefmod.NAV_PATH)
    code, state, c, _ = run(tmp_path / "r", TE4_SPEC, bk["held"], "ok", key=M.HOLD,
                            now=M.FINAL)
    assert code == rn.EXIT_REFUSED and not c.accepted
    plan = M._plan(state)
    ts = plan["thin_session"]
    assert ts["holds"] is True and ts["reduced"] is False and ts["stopped_by"] is None
    assert plan["missing_nav"]["action"] == "refused"


# --------------------------------------------------------------- the gross pin

def _gross_case(work: Path, mp, base, holdings, panel: str, spec, eod: str) -> tuple:
    if panel == "full":
        M._scenario_panel(base, work / "panel", mp, M.ASOF)
    else:
        N.thin_panel(base, work / "panel", mp, int(panel))
    code, state, _, _ = run(work / "run", spec, holdings, eod)
    plan = M._plan(state)
    return code, plan, gross(plan, closes_of(spec))


@pytest.mark.parametrize("panel", ["5", "4", "full"])
def test_no_drawdown_status_can_increase_gross(tmp_path, monkeypatch, books, panel):
    base, bk = books
    for book, holdings in bk.items():
        got = {}
        for rule, spec in (("absent", N.THIN_SPEC), ("te4", TE4_SPEC)):
            for eod in STATUSES:
                got[(rule, eod)] = _gross_case(tmp_path / f"{book}_{rule}_{eod}", monkeypatch,
                                               base, holdings, panel, spec, eod)
        g = {k: v[2] for k, v in got.items()}
        # Key absent: report mode acts on nothing, so every status gives one book.
        assert len({g[("absent", s)] for s in STATUSES}) == 1, (book, g)
        for s in STATUSES:
            assert g[("te4", s)] <= g[("te4", "ok")] + 1e-9, (book, s, g)
            if s != "ok":
                assert g[("te4", s)] == g[("absent", s)], (book, s, g)
        if panel == "full":
            # K0 never touches a full session: the plan is the key-absent one under every status.
            for s in STATUSES:
                a, t = got[("absent", s)][1], got[("te4", s)][1]
                assert t["orders"] == a["orders"] and t["targets"] == a["targets"], (book, s)
                assert t["thin_session"]["reduced"] is False
                assert t["thin_session"]["stopped_by"] is None
            assert g[("te4", "ok")] > 0
        else:
            assert g[("te4", "ok")] > 0 and g[("te4", "halve")] == 0, (book, g)
