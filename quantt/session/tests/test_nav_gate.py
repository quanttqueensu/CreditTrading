"""The decide-time stale-NAV gate (quantt/session/nav_gate.py) and its place in the session.

THE RULE (team lead, 2026-10-13, redesigned the same day), and what each test pins:

  * TRIGGER: panel NAV(D) = its previous NAV row, OR = CEFConnect's NAV(D-1).
    The second is the reviewer's PDI case: 09-25 captured as 15.06 against a
    09-24 row of 15.12 (Yahoo's own stale copy), where 15.06 is CEFConnect's
    09-24 NAV and the true 09-25 NAV is 15.10;
  * RESOLUTION: CEFConnect has D and differs -> replaced through the logged
    fallback; has D and agrees -> kept;
  * UNVERIFIED (no row for D, or an error): never dropped. Before the final
    pre-send check the decide is DEFERRED (a gate-5 `data` refusal: nothing
    decided, nothing marked, the morning re-reads CEFConnect); from the final
    check the name is HELD at its current shares;
  * `report` records what `on` would do and changes nothing: the orders and the
    plan are a gate-off session's, byte for byte, apart from `nav_gate`.

Why: results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5 (28 of 73 checkable
name-days decided on NAV(D-1); 11 submitted orders sized on one), and the first
version's replay: dropping at the evening decide would have flattened the book
on 2026-10-05 (docs/REFERENCES.md §12s).

Hermetic: synthetic panels and the fallback log under tmp_path, a fake
CEFConnect (netguard refuses any socket), test_run's FakeClient for the broker.
The one real-panel test reads `data/cef/` read-only and skips without it.
"""
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from quantt.session import nav_gate as ng
from quantt.session import run as rn
from quantt.session.tests.test_run import (ASOF, BOOK, D, EVE, LATE, SPEC, FakeClient, make,
                                           targets_book, to_send_time, utc)

ET = rn.gt.ET
PREV = dt.date(2026, 9, 25)          # the trading day before ASOF (Monday 2026-09-28)
PREV2 = dt.date(2026, 9, 24)
MORNING = dt.datetime(2026, 9, 29, 9, 0, tzinfo=ET)       # backstop, before the final check
FINAL = dt.datetime(2026, 9, 29, 14, 30, tzinfo=ET)       # 16:00 close - 90 min
NOW = dt.datetime(2026, 9, 29, 2, 0, tzinfo=dt.timezone.utc)


def write_nav(path: Path, navs: dict, days=(PREV2, PREV, ASOF)) -> None:
    """navs: {ticker: (nav on days[0], days[1], days[2])}."""
    pd.DataFrame([{"date": pd.Timestamp(d), "nav": v, "ticker": t}
                  for t, vals in navs.items() for d, v in zip(days, vals)]).to_parquet(path)


class FakeCC:
    """CEFConnect: {ticker: (NAV for D-1, NAV for D)} or an exception. Mutable,
    so a test can let a row 'arrive' between two runs."""

    def __init__(self, values):
        self.values, self.calls = dict(values), []

    def __call__(self, ticker, days):
        self.calls.append((ticker, tuple(days)))
        v = self.values[ticker]
        if isinstance(v, Exception):
            raise v
        prev, d = days
        return {prev: v[0], d: v[1]}


# AAA stale copy (trigger 1), BBB genuine repeat, CCC CEFConnect has no D,
# DDD CEFConnect error, EEE moved (no trigger).
NAVS = {"AAA": (9.90, 10.00, 10.00), "BBB": (19.80, 20.00, 20.00),
        "CCC": (29.70, 30.00, 30.00), "DDD": (39.60, 40.00, 40.00),
        "EEE": (49.50, 50.00, 50.10)}
CC = {"AAA": (9.98, 10.05), "BBB": (20.00, 20.00), "CCC": (30.00, None),
      "DDD": ng.CefConnectError("DDD: ConnectionError: refused"), "EEE": (50.00, 50.10)}
UNI5 = tuple(NAVS)


@pytest.fixture
def panel(tmp_path):
    p = tmp_path / "cef_nav.parquet"
    write_nav(p, NAVS)
    return p


def _noop(res):
    """A record that writes nothing, for gate-level tests that are not about it."""


def gate_for(tmp_path, panel, cc=CC):
    return ng.PanelGate(nav_path=panel, log_path=tmp_path / "nav_fallback_log.csv",
                        lock_path=tmp_path / ".fetch.lock", reader=FakeCC(cc), lock_wait_s=1.0)


def nav_at(panel, ticker, day=ASOF):
    N = pd.read_parquet(panel)
    v = N.loc[(pd.to_datetime(N["date"]) == pd.Timestamp(day)) & (N["ticker"] == ticker), "nav"]
    assert len(v) == 1
    return float(v.iloc[0])


def by_ticker(res):
    return {c.ticker: c for c in res.checks}


# ------------------------------------------------------------- the trigger

def test_the_pdi_case_triggers_on_cefconnects_previous_nav_and_is_replaced(tmp_path):
    """The reviewer's case, on its own dates: Yahoo's 09-24 row (15.12) was itself
    a stale copy, so 09-25 = 15.06 does not repeat it -- but 15.06 is CEFConnect's
    09-24 NAV. The true 09-25 NAV is CEFConnect's 15.10."""
    p = tmp_path / "nav.parquet"
    write_nav(p, {"PDI": (15.12, 15.12, 15.06)},
              days=(dt.date(2026, 9, 23), dt.date(2026, 9, 24), dt.date(2026, 9, 25)))
    g = gate_for(tmp_path, p, {"PDI": (15.06, 15.10)})
    res = g.run(dt.date(2026, 9, 25), ("PDI",), ng.ON, NOW, final=False, record=_noop)
    c = by_ticker(res)["PDI"]
    assert (c.trigger, c.verdict, c.action) == (ng.TRIGGER_CC, ng.STALE_COPY, "replaced")
    assert c.cc_prev_date == dt.date(2026, 9, 24)
    assert nav_at(p, "PDI", dt.date(2026, 9, 25)) == 15.10
    assert not res.deferred


def test_a_yfinance_repeat_with_cefconnect_different_is_replaced_and_logged(tmp_path, panel):
    g = gate_for(tmp_path, panel)
    res = g.run(ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)
    c = by_ticker(res)["AAA"]
    assert (c.trigger, c.verdict, c.action) == (ng.TRIGGER_YF, ng.STALE_COPY, "replaced")
    assert res.replaced == {"AAA": 10.05} and nav_at(panel, "AAA") == 10.05
    assert nav_at(panel, "AAA", PREV) == 10.00                  # history untouched
    log = pd.read_csv(tmp_path / "nav_fallback_log.csv")
    assert list(log.columns) == ["date", "nav", "ticker", "source", "written_utc"]
    assert log[["ticker", "nav", "source"]].values.tolist() == [["AAA", 10.05,
                                                                 ng.FALLBACK_SOURCE]]
    # CEFConnect is read for every name (trigger 2 needs D-1), D-1 and D in one call.
    assert sorted(t for t, _ in g.reader.calls) == list(UNI5)
    assert {days for _, days in g.reader.calls} == {(PREV, ASOF)}
    assert by_ticker(res)["EEE"].trigger == ""                   # moved: not triggered


def test_on_records_before_it_writes_the_panel_and_never_writes_unrecorded(tmp_path, panel):
    """Execution desk 2026-10-14: the panel was written before nav_gate.csv, so a
    failed record left a replaced NAV nothing recorded. The record now runs
    first; if it fails, the panel and the fallback log are never written."""
    seen = []

    def record(res):
        seen.append((sorted(res.replaced), nav_at(panel, "AAA")))
    gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=False, record=record)
    assert seen == [(["AAA"], 10.00)]                     # recorded while AAA was unwritten
    assert nav_at(panel, "AAA") == 10.05

    write_nav(panel, NAVS)
    (tmp_path / "nav_fallback_log.csv").unlink()

    def broken(res):
        raise ng.NavGateRecordError("nav_gate.csv: cannot write")
    with pytest.raises(ng.NavGateRecordError):
        gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=False, record=broken)
    assert nav_at(panel, "AAA") == 10.00 and not (tmp_path / "nav_fallback_log.csv").exists()
    with pytest.raises(ValueError, match="needs a record"):
        gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=False)


def test_genuine_repeat_is_kept(tmp_path, panel):
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)
    c = by_ticker(res)["BBB"]
    assert (c.trigger, c.verdict, c.action) == (f"{ng.TRIGGER_YF}+{ng.TRIGGER_CC}",
                                                ng.GENUINE_REPEAT, "kept")
    assert "BBB" not in res.replaced and "BBB" not in res.hold
    assert nav_at(panel, "BBB") == 20.00


# ------------------------------------------------------------- unverified: defer, then hold

def test_unverified_defers_before_the_final_check_and_is_held_from_it(tmp_path, panel):
    early = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)
    c = by_ticker(early)["CCC"]
    assert (c.verdict, c.action, c.cc_d) == (ng.UNVERIFIED, "deferred", None)
    assert early.deferred and early.unverified == ["CCC", "DDD"]
    assert "has no NAV dated 2026-09-28" in early.hold["CCC"]
    assert nav_at(panel, "CCC") == 30.00                          # never written
    late = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=True, record=_noop)
    assert by_ticker(late)["CCC"].action == "held" and not late.deferred
    assert sorted(late.hold) == ["CCC", "DDD"]


def test_a_cefconnect_error_is_unverified_and_named(tmp_path, panel):
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=True, record=_noop)
    c = by_ticker(res)["DDD"]
    assert (c.verdict, c.action) == (ng.UNVERIFIED, "held")
    assert c.cc_status == "error: DDD: ConnectionError: refused"
    assert "ConnectionError: refused" in res.hold["DDD"]


def test_a_cefconnect_nav_that_is_not_a_positive_number_is_never_used(tmp_path, panel):
    res = gate_for(tmp_path, panel, {**CC, "AAA": (9.98, 0.0)}).run(
        ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)
    c = by_ticker(res)["AAA"]
    assert c.verdict == ng.UNVERIFIED and c.cc_status.startswith("error: CEFConnect NAV 0.0")
    assert nav_at(panel, "AAA") == 10.00 and not (tmp_path / "nav_fallback_log.csv").exists()


def test_a_bug_in_the_reader_is_raised_not_turned_into_a_hold(tmp_path, panel):
    with pytest.raises(KeyError):
        gate_for(tmp_path, panel, {**CC, "AAA": KeyError("NAVData")}).run(
            ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)


def test_the_final_check_is_ninety_minutes_before_the_calendar_close():
    assert ng.final_check_at(D, "16:00") == dt.datetime(2026, 9, 29, 14, 30, tzinfo=ET)
    assert ng.final_check_at(D, "13:00") == dt.datetime(2026, 9, 29, 11, 30, tzinfo=ET)


# ------------------------------------------------------------- the panel reader

def test_half_a_cent_is_the_same_nav(tmp_path):
    p = tmp_path / "nav.parquet"
    write_nav(p, {"AAA": (9.9, 10.0, 10.0000004), "BBB": (9.9, 10.0, 10.01)})
    assert [r.ticker for r in ng.repeats(pd.read_parquet(p), ASOF, ["AAA", "BBB"])] == ["AAA"]


def test_the_panel_is_never_read_past_the_asof_date(tmp_path):
    p = tmp_path / "nav.parquet"
    write_nav(p, {"AAA": (9.9, 10.0, 10.0)})
    N = pd.concat([pd.read_parquet(p),
                   pd.DataFrame([{"date": pd.Timestamp(D), "nav": 10.0, "ticker": "AAA"}])])
    assert ng.repeats(N, PREV, ["AAA"]) == []            # as of PREV it moved
    assert ng.panel_rows(N, ASOF, ["AAA"])["AAA"][1] == PREV


def test_a_duplicate_nav_row_raises(tmp_path):
    p = tmp_path / "nav.parquet"
    write_nav(p, {"AAA": (9.9, 10.0, 10.0)})
    N = pd.concat([pd.read_parquet(p),
                   pd.DataFrame([{"date": pd.Timestamp(ASOF), "nav": 10.2, "ticker": "AAA"}])])
    with pytest.raises(ValueError, match="duplicate"):
        ng.panel_rows(N, ASOF, ["AAA"])


# ------------------------------------------------------------- report mode, at the gate

def test_report_mode_records_what_on_would_do_and_changes_nothing(tmp_path, panel):
    before = panel.read_bytes()
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.REPORT, NOW, final=False)
    assert {c.ticker: c.action for c in res.triggered} == {
        "AAA": "would replace", "BBB": "would keep", "CCC": "would defer", "DDD": "would defer"}
    assert res.would_defer and not res.deferred
    assert res.replaced == {} and res.hold == {}
    assert panel.read_bytes() == before and not (tmp_path / "nav_fallback_log.csv").exists()
    final = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.REPORT, NOW, final=True)
    assert by_ticker(final)["CCC"].action == "would hold"


def test_still_holds_catches_a_fetch_that_wrote_the_stale_copy_back(tmp_path, panel):
    g = gate_for(tmp_path, panel)
    res = g.run(ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)
    assert g.still_holds(res) == []
    write_nav(panel, NAVS)                       # a later yfinance fetch: AAA stale again
    assert any("AAA" in x for x in g.still_holds(res))
    write_nav(panel, {**NAVS, "AAA": (9.90, 10.00, 10.05), "EEE": (49.5, 50.0, 50.0)})
    assert [x.split(":")[0] for x in g.still_holds(res)] == ["EEE"]   # a new, unjudged repeat


def test_the_csv_records_every_triggered_name_and_a_run_with_none(tmp_path, panel):
    path = tmp_path / ng.CSV_NAME
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ON, NOW, final=False, record=_noop)
    ng.append_csv(path, res, run="r1-run", session_date=D, written_utc=NOW)
    p2 = tmp_path / "moved.parquet"
    write_nav(p2, {"EEE": NAVS["EEE"]})
    none = gate_for(tmp_path, p2).run(ASOF, ("EEE",), ng.ON, NOW, final=False, record=_noop)
    ng.append_csv(path, none, run="r2-run", session_date=D, written_utc=NOW)
    rows = pd.read_csv(path, keep_default_na=False)
    assert tuple(rows.columns) == ng.CSV_COLUMNS
    assert rows[["run", "ticker", "verdict", "action"]].values.tolist() == [
        ["r1-run", "AAA", "stale_copy", "replaced"], ["r1-run", "BBB", "genuine_repeat", "kept"],
        ["r1-run", "CCC", "unverified", "deferred"], ["r1-run", "DDD", "unverified", "deferred"],
        ["r2-run", "", "no_trigger", "none"]]
    assert rows.loc[2, "cc_d"] == "" and rows.loc[3, "cc_status"].startswith("error: DDD")
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n")
    with pytest.raises(ng.NavGateRecordError, match="moved aside"):
        ng.append_csv(bad, res, run="r3", session_date=D, written_utc=NOW)
    assert not bad.exists()
    (aside,) = tmp_path.glob("bad.csv.*.unreadable")
    assert aside.read_text() == "a,b\n"                  # kept whole, never mixed


# ------------------------------------------------------------- in the session

UNI3 = {"AAA": NAVS["AAA"], "BBB": NAVS["BBB"], "CCC": NAVS["CCC"]}
CC3 = {k: CC[k] for k in UNI3}


def session(tmp_path, mode, cc=CC3, targets=None, clock=EVE, **kw):
    """test_run's late-market session with the gate wired on a tmp panel."""
    kw.setdefault("execution", LATE)
    c, deps, state, seen, out = make(tmp_path, clock_ts=clock, now_utc=utc(clock), **kw)
    p = tmp_path / "cef_nav.parquet"
    write_nav(p, UNI3)
    deps.stale_nav = mode
    deps.nav_gate = gate_for(tmp_path, p, cc)
    calls = []

    def rec_targets(*a, **k):
        calls.append((a, k))
        return (targets or targets_book)(*a)
    deps.targets = rec_targets
    return c, deps, state, calls, out, p


def plan_of(state):
    return json.loads((state / D.isoformat() / "plan.json").read_text())


def test_gate_off_the_plan_and_the_sleeve_call_are_unchanged(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, execution=LATE)
    assert deps.stale_nav is None and deps.nav_gate is None
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    assert "nav_gate" not in plan_of(state)
    assert len(seen.targets) == 1 and len(seen.targets[0]) == 4
    assert not (state / ng.CSV_NAME).exists() and "NAV GATE" not in "".join(out)


def test_an_evening_with_an_unverified_name_defers_the_decide(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ON)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_REFUSED
    plan = plan_of(state)
    assert plan["status"] == "refused"
    (r,) = plan["refusals"]
    assert r["gate"] == "data" and "deferred" in r["detail"] and "CCC" in r["detail"]
    assert not (state / D.isoformat() / "DECIDED").exists()      # the next slot is free
    (args, kw), = calls                                           # the held plan, shown
    assert kw["nav_hold"] == {"asof": ASOF, "names": {"CCC": plan["nav_gate"]["checks"][2]
                                                      and kw["nav_hold"]["names"]["CCC"]}}
    assert nav_at(p, "AAA") == 10.05                              # the stale copy is fixed now
    assert plan["nav_gate"]["deferred"] is True
    # A deferred plan can never be approved or sent.
    with pytest.raises(rn.SessionError, match="not a decided"):
        rn.load_decided_plan(state / D.isoformat(), D)


def test_the_morning_backstop_re_verifies_and_decides_once_cefconnect_has_the_row(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ON)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_REFUSED
    to_send_time(c, deps, MORNING)                 # 09:00 ET: still before the final check
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_REFUSED
    deps.nav_gate.reader.values["CCC"] = (30.00, 30.02)           # CEFConnect publishes D
    to_send_time(c, deps, MORNING + dt.timedelta(minutes=30))
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_PLANNED
    plan = plan_of(state)
    assert plan["status"] == "decided" and plan["refusals"] == []
    assert plan["nav_gate"]["replaced"] == ["CCC"] and nav_at(p, "CCC") == 30.02
    assert calls[-1][1] == {}                                     # nothing held
    assert (state / D.isoformat() / "DECIDED").exists()
    to_send_time(c, deps, FINAL)                                  # later slots idle
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_IDLE


def test_from_the_final_check_an_unverified_name_is_held_and_the_day_decides(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ON, clock=FINAL)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_PLANNED
    plan = plan_of(state)
    assert plan["status"] == "decided" and plan["nav_gate"]["held"] == ["CCC"]
    (args, kw), = calls
    assert list(kw["nav_hold"]["names"]) == ["CCC"] and kw["nav_hold"]["asof"] == ASOF


def test_a_deferral_under_dry_run_is_refused_never_dry_done(tmp_path):
    """DRY_DONE would idle every later slot behind a dry run; a deferral must not."""
    c, deps, state, calls, out, p = session(tmp_path, ng.ON, execution={"mode": "cls"},
                                            env={"DRY_RUN": "1"})
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_REFUSED
    assert not (state / D.isoformat() / "DRY_DONE").exists() and c.submits() == []


def test_report_mode_leaves_the_orders_and_the_plan_unchanged(tmp_path):
    """Same session, same CEFConnect, gate off and in report mode: identical
    exit, orders, plan_sha and plan.json apart from the added `nav_gate`, on an
    evening where `on` would have deferred."""
    c0, d0, s0, seen, out0 = make(tmp_path / "off", clock_ts=EVE, now_utc=utc(EVE),
                                  execution=LATE)
    write_nav(tmp_path / "off" / "cef_nav.parquet", UNI3)
    c1, d1, s1, calls, out1, p = session(tmp_path / "rep", ng.REPORT)
    before = p.read_bytes()
    assert rn.run_session(BOOK, SPEC, d0, scheduled=True) == rn.EXIT_PLANNED
    assert rn.run_session(BOOK, SPEC, d1, scheduled=True) == rn.EXIT_PLANNED
    off, rep = plan_of(s0), plan_of(s1)
    g = rep.pop("nav_gate")
    assert rep == off
    assert g["would_defer"] is True and g["deferred"] is False
    assert [c["action"] for c in g["checks"] if c["trigger"]] == [
        "would replace", "would keep", "would defer"]
    assert calls[0][1] == {} and p.read_bytes() == before


@pytest.mark.parametrize("content", ["", "a,b\n"], ids=["empty", "old_header"])
def test_a_bad_nav_gate_csv_never_stops_a_report_mode_session(tmp_path, content):
    """Release-check 2026-10-13: an empty nav_gate.csv (a reboot or kill before the
    first flush) or one with another header ended every decide in EXIT_FAIL, with
    no plan, until someone deleted it -- in report mode, which promises it never
    stops the session. Now the run records UNMEASURED and decides as without the
    gate; the file is moved aside whole, and the next decide starts a new one."""
    c, deps, state, calls, out, p = session(tmp_path, ng.REPORT, clock=FINAL)
    (state / ng.CSV_NAME).write_text(content)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    plan = plan_of(state)
    assert plan["status"] == "decided" and plan["orders"]
    assert "nav_gate.csv" in plan["nav_gate"]["unmeasured"]
    assert "UNMEASURED: recording failed" in "".join(out)
    (aside,) = state.glob("nav_gate.csv.*.unreadable")
    assert aside.read_text() == content
    (state / D.isoformat() / "plan.json").unlink()      # decide again: a new file
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    assert "unmeasured" not in plan_of(state)["nav_gate"]
    assert tuple(pd.read_csv(state / ng.CSV_NAME).columns) == ng.CSV_COLUMNS


@pytest.mark.parametrize("content", ["", "a,b\n"], ids=["empty", "old_header"])
def test_a_bad_nav_gate_csv_stops_an_on_mode_session_naming_the_file(tmp_path, content):
    """Under `on` the gate acts, and acting without its record breaks H14: the
    session does not decide, and says which file. The file is moved aside, so the
    next slot decides with a new one."""
    c, deps, state, calls, out, p = session(tmp_path, ng.ON, clock=FINAL)
    (state / ng.CSV_NAME).write_text(content)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert "nav_gate.csv" in "".join(out) and "not deciding without its record" in "".join(out)
    assert not (state / D.isoformat() / "plan.json").exists() and c.submits() == []
    # Record first (2026-10-14): the stale copy the gate would have replaced is
    # still in the panel, and nothing was logged as written from CEFConnect.
    assert nav_at(p, "AAA") == 10.00 and not (tmp_path / "nav_fallback_log.csv").exists()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    assert plan_of(state)["status"] == "decided"


def test_the_send_path_never_imports_scripts_or_yfinance():
    """Release-check 2026-10-13: default_deps imported scripts.cef.fetch_daily on
    every run, the 15:52 send included, loading yfinance and a process-wide
    warnings filter -- scripts/ on the send path, where a failed import between
    decide and send would stop a decided plan. In a fresh interpreter (this
    process has long since imported both): the deployed book's own default_deps
    (gate in report mode, broker client faked), then a late-market send exactly
    as the send tests run it. Neither module may be loaded."""
    import subprocess
    import sys
    code = r"""
import json, sys, tempfile, pathlib
import ops.netguard; ops.netguard.install()
from quantt.broker import alpaca
from quantt.session import run as rn
from quantt.session.tests import test_run as tr
tmp = pathlib.Path(tempfile.mkdtemp())
c, deps, state, plan = tr.decided(tmp)
alpaca.AlpacaClient.from_environment = staticmethod(lambda name: c)
book = rn.BOOKS["cef"]
real = rn.default_deps(book, rn.load_spec(book.spec_path),
                       {"QUANTT_ENV_FILE": "unused", "QUANTT_STATE_DIR": str(state)})
deps.stale_nav, deps.nav_gate = real.stale_nav, real.nav_gate
(state / "AUTO_ARMED").touch()
tr.to_send_time(c, deps)
code = rn.run_session(tr.BOOK, tr.SPEC, deps)
print(json.dumps({"code": code, "mode": real.stale_nav, "gate": real.nav_gate is not None,
                  "yfinance": "yfinance" in sys.modules,
                  "fetch_daily": "scripts.cef.fetch_daily" in sys.modules}))
"""
    r = subprocess.run([sys.executable, "-c", code], cwd=rn.REPO, capture_output=True,
                       text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["code"] == rn.EXIT_SENT and got["gate"], got
    assert got["yfinance"] is False and got["fetch_daily"] is False, got


def test_the_session_fails_if_the_panel_changed_under_the_sleeve(tmp_path):
    def restore_stale(*a):
        write_nav(tmp_path / "cef_nav.parquet", UNI3)
        return targets_book(*a)
    c, deps, state, calls, out, p = session(tmp_path, ng.ON, cc={**CC3, "CCC": (30.0, 30.0)},
                                            targets=restore_stale)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert "changed between the stale-NAV gate" in "".join(out)


def test_a_gate_error_fails_the_session_in_on_mode_and_is_recorded_in_report_mode(tmp_path):
    boom = {**CC3, "AAA": KeyError("NAVData")}           # a bug, not a CEFConnect error
    c, deps, state, calls, out, p = session(tmp_path / "on", ng.ON, boom)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL and calls == []
    c, deps, state, calls, out, p = session(tmp_path / "rep", ng.REPORT, boom)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    assert plan_of(state)["nav_gate"]["unmeasured"].startswith("KeyError")


def test_the_gate_does_not_run_on_a_refresh_that_failed(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ON)
    deps.refresh = lambda asof, t: rn.RefreshResult(exit=4, tail="INCOMPLETE")
    before = p.read_bytes()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert "not_run" in plan_of(state)["nav_gate"] and p.read_bytes() == before
    assert deps.nav_gate.reader.calls == []


def test_a_mode_without_a_gate_wired_raises(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, execution=LATE)
    deps.stale_nav = ng.ON
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert "no NAV gate wired" in "".join(out)


# ------------------------------------------------------------- the book json switch

@pytest.mark.parametrize("data, want", [(None, None), ({"stale_nav": "report"}, "report"),
                                        ({"stale_nav": "on", "_stale_nav_note": "x"}, "on")])
def test_stale_nav_setting_absent_is_off(tmp_path, data, want):
    book = {"book_id": "b"} if data is None else {"book_id": "b", "data": data}
    path = tmp_path / "book.json"
    path.write_text(json.dumps(book))
    assert rn.stale_nav_for(rn.Book("cef", "cef", Path("x"), path)) == want


@pytest.mark.parametrize("data", [{"stale_nav": "cefconnect_else_drop"}, {"stale_nav": None},
                                  {}, "on"])
def test_stale_nav_setting_that_is_not_a_mode_raises(tmp_path, data):
    path = tmp_path / "book.json"
    path.write_text(json.dumps({"book_id": "b", "data": data}))
    with pytest.raises(rn.SessionError):
        rn.stale_nav_for(rn.Book("cef", "cef", Path("x"), path))


def test_the_released_book_runs_the_gate_in_report_mode():
    """The release setting (team lead 2026-10-13: report first, `on` after a
    measured week). Changing it is a reviewed book-json edit; this test moves
    with it."""
    assert rn.stale_nav_for(rn.BOOKS["cef"]) == ng.REPORT


# ------------------------------------------------------------- the real panel, report mode

def _real_panel_ready():
    from src.deploy.sleeves import cef_discount as cefmod
    return cefmod.PX_PATH.exists() and cefmod.NAV_PATH.exists()


# The two stale copies the laptop panel held for 2026-09-25 when it was captured on
# 2026-09-28 (results/cef/LIVE_NAV_QUALITY_2026-10-12.md §1, "the two exceptions";
# docs/REFERENCES.md §12n, and §12s for CEFConnect's values): PDI 15.06 --
# CEFConnect's 09-24 NAV; the true 09-25 NAV is 15.10, the reviewer's case for the
# second trigger -- and DSL 11.11, its 09-24 value (true 11.10). Yahoo has since
# corrected both, and the 2026-10-15 refresh of the dev panels took the
# corrections in, so the test injects them into its own copy.
INJECTED_STALE_COPIES = {("PDI", dt.date(2026, 9, 25)): 15.06,
                         ("DSL", dt.date(2026, 9, 25)): 11.11}


def _real_panels_with_the_documented_copies(tmp_path, monkeypatch):
    """Copy the real panels into tmp_path, put the documented stale copies back,
    and point the sleeve at the copies. Each injection must hit exactly one
    existing row, and PDI's previous row must still differ from 15.06 (else the
    case would fire the first trigger, not the second): a wrong date or ticker,
    or a panel that no longer has the row, fails here, loudly."""
    import shutil
    from src.deploy.sleeves import cef_discount as cefmod
    px, nav = tmp_path / "cef_prices.parquet", tmp_path / "cef_nav.parquet"
    shutil.copyfile(cefmod.PX_PATH, px)
    N = pd.read_parquet(cefmod.NAV_PATH)
    d = pd.to_datetime(N["date"]).dt.normalize()
    for (tk, day), v in INJECTED_STALE_COPIES.items():
        hit = (N["ticker"] == tk) & (d == pd.Timestamp(day))
        assert hit.sum() == 1, f"no single {tk} NAV row dated {day} to inject into"
        N.loc[hit, "nav"] = v
    N.to_parquet(nav)
    got = pd.read_parquet(nav)
    gd = pd.to_datetime(got["date"]).dt.normalize()
    for (tk, day), v in INJECTED_STALE_COPIES.items():
        assert got.loc[(got["ticker"] == tk) & (gd == pd.Timestamp(day)), "nav"].tolist() == [v]
    prev = got.loc[(got["ticker"] == "PDI") & (gd == pd.Timestamp(2026, 9, 24)), "nav"].tolist()
    assert len(prev) == 1 and ng.differs(prev[0], 15.06), \
        f"PDI's 2026-09-24 row is {prev}: the second-trigger case needs it to differ from 15.06"
    monkeypatch.setattr(cefmod, "PX_PATH", px)
    monkeypatch.setattr(cefmod, "NAV_PATH", nav)
    monkeypatch.setattr(cefmod, "GRP_PATH", px)
    return px, nav


@pytest.mark.skipif(not _real_panel_ready(), reason="real CEF panels absent (data/ is "
                                                     "gitignored); the synthetic tests still run")
def test_real_sleeve_on_the_real_panel_report_mode_is_byte_identical(tmp_path, monkeypatch):
    """The no-op proof for the release setting: the live spec, the real sleeve and
    a copy of the real panels, decided as of 2026-09-25 on a held book, with the
    two stale copies that date held when the laptop captured it put back
    (INJECTED_STALE_COPIES): the reviewer's PDI case and DSL's 11.11. Gate off and
    gate in report mode give the same exit, orders, plan_sha and plan.json apart
    from `nav_gate`. CEFConnect is a fixture that makes every branch fire
    (replace, keep, defer); its numbers are test inputs, not data. The real
    panels are read only and must come out byte-identical; so must the copy,
    which report mode never writes. The test proves the same thing whether or
    not Yahoo has corrected the rows since (2026-10-15: it had)."""
    from src.deploy.sleeves import cef_discount as cefmod
    real = {f: f.read_bytes() for f in (cefmod.PX_PATH, cefmod.NAV_PATH)}
    (tmp_path / "panels").mkdir()
    _real_panels_with_the_documented_copies(tmp_path / "panels", monkeypatch)
    spec = json.loads((rn.REPO / "ops/specs/cef_discount.frozen.json").read_text())
    p = rn.spec_params(spec)
    asof = dt.date(2026, 9, 25)
    eve = dt.datetime(2026, 9, 25, 22, 0, tzinfo=ET)
    uni = p["universe"]
    day1 = rn.sleeve_targets(spec, p["capital_usd"], asof, {}, p["capital_usd"], True)
    closes = {s: v[0] for s, v in rn.last_closes(cefmod.PX_PATH, asof, uni).items()}
    # Half the day-one book, so the band has trades to make and holds to keep.
    held = {t.instrument: int(0.5 * p["capital_usd"] * float(t.weight) / closes[t.instrument])
            for t in day1 if t.weight}
    held = {s: q for s, q in held.items() if q}
    cc = {s: (10.0, 10.0) for s in uni}                       # no trigger for most names
    cc.update({"PDI": (15.06, 15.10), "DSL": (11.11, None), "BIT": (None, None)})

    def one(sub, mode):
        state = tmp_path / sub / "state"
        state.mkdir(parents=True)
        client = FakeClient(state, positions=held, clock_ts=eve)
        client.long_mv = sum(q * closes[s] for s, q in held.items() if q > 0)
        client.short_mv = sum(q * closes[s] for s, q in held.items() if q < 0)
        client.maint = 0.5 * (client.long_mv - client.short_mv)     # fixture, not a measurement
        deps = rn.Deps(
            client=client, env={"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0"},
            refresh=lambda a, t: rn.RefreshResult(exit=0, tail="fixture"),
            closes=lambda a, u: rn.last_closes(cefmod.PX_PATH, a, u),
            navs=lambda a, u: rn.last_navs(cefmod.NAV_PATH, a, u),
            targets=lambda a, h, eq, op, **kw: rn.sleeve_targets(spec, p["capital_usd"], a, h,
                                                                 eq, op, **kw),
            halts=lambda: [], utcnow=lambda: eve.astimezone(dt.timezone.utc),
            out=type("O", (), {"write": lambda s, x: None, "flush": lambda s: None})(),
            execution={**LATE, "bp_shortfall": "scale"},
            stale_nav=mode,
            nav_gate=None if mode is None else ng.PanelGate(
                nav_path=cefmod.NAV_PATH, log_path=tmp_path / sub / "log.csv",
                lock_path=tmp_path / sub / ".lock", reader=FakeCC(cc)))
        code = rn.run_session(BOOK, spec, deps)
        return code, json.loads((state / "2026-09-28" / "plan.json").read_text())

    before = cefmod.NAV_PATH.read_bytes()                 # the injected copy
    c_off, off = one("off", None)
    c_rep, rep = one("rep", ng.REPORT)
    assert cefmod.NAV_PATH.read_bytes() == before         # report mode wrote nothing
    assert all(f.read_bytes() == b for f, b in real.items()), "a real panel changed"
    g = rep.pop("nav_gate")
    assert c_rep == c_off and rep == off
    assert c_off == rn.EXIT_PLANNED and off["status"] == "decided"
    assert off["orders"] and off["plan_sha"] == rep["plan_sha"]
    assert any("band hold" in t["reason"] for t in off["targets"].values())
    acts = {c["ticker"]: (c["trigger"], c["action"]) for c in g["checks"] if c["trigger"]}
    assert acts["PDI"] == (ng.TRIGGER_CC, "would replace")      # the reviewer's case
    assert acts["DSL"][1] == "would defer"                       # 11.11 = 11.11, no D row
    assert g["would_defer"] is True
