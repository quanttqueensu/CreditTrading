"""The decide-time stale-NAV gate (quantt/session/nav_gate.py) and its place in the session.

THE RULING (team lead, 2026-10-13: "Use CEFConnect, else drop"), and what each
test pins of it:

  * a yfinance NAV(D) that repeats NAV(D-1) while CEFConnect's D differs is a
    STALE COPY: CEFConnect's value replaces it in the panel the sleeve reads,
    logged to the fallback log as `cefconnect_stale_copy`;
  * CEFConnect has no row for D -> the name is DROPPED (the sleeve is told);
  * CEFConnect has D and agrees -> a GENUINE REPEAT, kept untouched;
  * CEFConnect cannot be read -> DROPPED, and the error is named in the record.

Why it exists: results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5 -- on the laptop's
paper sessions 28 of 73 checkable name-days were decided on NAV(D-1), and 11
submitted orders were sized on one, because `fetch_daily --require-asof`
checks a NAV's date and not its value.

Also pinned: report mode measures and changes nothing; a bug in the reader is
not a drop; the panel the sleeve read is checked to be the one the gate
certified; the gate is OFF unless the book json turns it on, and then the plan
and the sleeve call are exactly today's.

Hermetic: the panel and the fallback log live under tmp_path, CEFConnect is a
fake (netguard refuses any socket), and the broker is test_run's FakeClient.
"""
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from quantt.session import nav_gate as ng
from quantt.session import run as rn
from quantt.session.tests.test_run import ASOF, BOOK, D, SPEC, make, targets_book

PREV = dt.date(2026, 9, 25)          # the Friday before ASOF (Monday 2026-09-28)
PREV2 = dt.date(2026, 9, 24)


def write_nav(path: Path, navs: dict) -> None:
    """navs: {ticker: (nav PREV2, nav PREV, nav ASOF)}."""
    rows = [{"date": pd.Timestamp(d), "nav": v, "ticker": t}
            for t, vals in navs.items() for d, v in zip((PREV2, PREV, ASOF), vals)]
    pd.DataFrame(rows).to_parquet(path)


# AAA stale copy, BBB genuine repeat, CCC CEFConnect absent, DDD CEFConnect error,
# EEE moved (not a repeat: never sent to CEFConnect).
NAVS = {"AAA": (9.90, 10.00, 10.00), "BBB": (19.80, 20.00, 20.00),
        "CCC": (29.70, 30.00, 30.00), "DDD": (39.60, 40.00, 40.00),
        "EEE": (49.50, 50.00, 50.10)}
CC = {"AAA": 10.05, "BBB": 20.00, "CCC": None,
      "DDD": ng.CefConnectError("DDD: ConnectionError: refused"), "EEE": 50.10}
UNI5 = tuple(NAVS)
NOW = dt.datetime(2026, 9, 29, 2, 0, tzinfo=dt.timezone.utc)


class FakeCC:
    def __init__(self, values):
        self.values, self.calls = dict(values), []

    def __call__(self, ticker, day):
        self.calls.append((ticker, day))
        v = self.values[ticker]
        if isinstance(v, Exception):
            raise v
        return v


@pytest.fixture
def panel(tmp_path):
    p = tmp_path / "cef_nav.parquet"
    write_nav(p, NAVS)
    return p


def gate_for(tmp_path, panel, cc=CC):
    return ng.PanelGate(nav_path=panel, log_path=tmp_path / "nav_fallback_log.csv",
                        lock_path=tmp_path / ".fetch.lock", reader=FakeCC(cc), lock_wait_s=1.0)


def nav_at(panel, ticker, day=ASOF):
    N = pd.read_parquet(panel)
    v = N.loc[(pd.to_datetime(N["date"]) == pd.Timestamp(day)) & (N["ticker"] == ticker), "nav"]
    assert len(v) == 1
    return float(v.iloc[0])


def by_ticker(res):
    return {b.repeat.ticker: b for b in res.bindings}


# ------------------------------------------------------------- the four rulings

def test_stale_copy_is_replaced_from_cefconnect_and_logged(tmp_path, panel):
    g = gate_for(tmp_path, panel)
    res = g.run(ASOF, UNI5, ng.ACT, NOW)
    b = by_ticker(res)["AAA"]
    assert (b.verdict, b.action, b.cefconnect_status) == (ng.STALE_COPY, "replaced", "present")
    assert res.replaced == {"AAA": 10.05}
    assert nav_at(panel, "AAA") == 10.05                       # what the sleeve now reads
    assert nav_at(panel, "AAA", PREV) == 10.00                 # history untouched
    log = pd.read_csv(tmp_path / "nav_fallback_log.csv")
    assert list(log.columns) == ["date", "nav", "ticker", "source", "written_utc"]
    assert log[["ticker", "nav", "source"]].values.tolist() == [["AAA", 10.05,
                                                                 ng.FALLBACK_SOURCE]]
    # Only repeats are sent to CEFConnect: EEE moved, so it is never asked.
    assert sorted(t for t, _ in g.reader.calls) == ["AAA", "BBB", "CCC", "DDD"]


def test_cefconnect_absent_drops_the_name(tmp_path, panel):
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ACT, NOW)
    b = by_ticker(res)["CCC"]
    assert (b.verdict, b.action, b.cefconnect_status) == (ng.UNVERIFIED, "dropped", "absent")
    assert "CCC" in res.dropped and "has no NAV dated 2026-09-28" in res.dropped["CCC"]
    assert nav_at(panel, "CCC") == 30.00                       # never written


def test_genuine_repeat_is_kept(tmp_path, panel):
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ACT, NOW)
    b = by_ticker(res)["BBB"]
    assert (b.verdict, b.action, b.cefconnect_nav) == (ng.GENUINE_REPEAT, "kept", 20.00)
    assert "BBB" not in res.dropped and "BBB" not in res.replaced
    assert nav_at(panel, "BBB") == 20.00


def test_cefconnect_error_drops_the_name_and_names_the_error(tmp_path, panel):
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ACT, NOW)
    b = by_ticker(res)["DDD"]
    assert (b.verdict, b.action) == (ng.UNVERIFIED, "dropped")
    assert b.cefconnect_status == "error: DDD: ConnectionError: refused"
    assert "ConnectionError: refused" in res.dropped["DDD"]
    assert res.to_dict()["bindings"][3]["cefconnect_status"].startswith("error: DDD")


# ------------------------------------------------------------- edges of the rule

def test_a_cefconnect_nav_that_is_not_a_positive_number_is_unverified_never_written(
        tmp_path, panel):
    res = gate_for(tmp_path, panel, {**CC, "AAA": 0.0}).run(ASOF, UNI5, ng.ACT, NOW)
    b = by_ticker(res)["AAA"]
    assert b.verdict == ng.UNVERIFIED and b.cefconnect_status.startswith("error: CEFConnect NAV 0.0")
    assert nav_at(panel, "AAA") == 10.00 and not (tmp_path / "nav_fallback_log.csv").exists()


def test_a_bug_in_the_reader_is_raised_not_turned_into_a_drop(tmp_path, panel):
    with pytest.raises(KeyError):
        gate_for(tmp_path, panel, {**CC, "AAA": KeyError("NAVData")}).run(
            ASOF, UNI5, ng.ACT, NOW)


def test_half_a_cent_is_the_same_nav(tmp_path):
    p = tmp_path / "nav.parquet"
    write_nav(p, {"AAA": (9.9, 10.0, 10.0000004), "BBB": (9.9, 10.0, 10.01)})
    reps = ng.repeats(pd.read_parquet(p), ASOF, ["AAA", "BBB"])
    assert [r.ticker for r in reps] == ["AAA"]          # float32 noise is a repeat; a cent is not


def test_repeats_never_read_past_the_asof_date(tmp_path):
    p = tmp_path / "nav.parquet"
    write_nav(p, {"AAA": (9.9, 10.0, 10.0)})
    N = pd.concat([pd.read_parquet(p),
                   pd.DataFrame([{"date": pd.Timestamp(D), "nav": 10.0, "ticker": "AAA"}])])
    # As of PREV the name moved (9.9 -> 10.0); the later rows must not make it a repeat.
    assert ng.repeats(N, PREV, ["AAA"]) == []
    assert [r.prev_date for r in ng.repeats(N, ASOF, ["AAA"])] == [PREV]


def test_a_duplicate_nav_row_raises(tmp_path):
    p = tmp_path / "nav.parquet"
    write_nav(p, {"AAA": (9.9, 10.0, 10.0)})
    N = pd.concat([pd.read_parquet(p),
                   pd.DataFrame([{"date": pd.Timestamp(ASOF), "nav": 10.2, "ticker": "AAA"}])])
    with pytest.raises(ValueError, match="duplicate"):
        ng.repeats(N, ASOF, ["AAA"])


def test_report_mode_measures_the_same_and_changes_nothing(tmp_path, panel):
    before = panel.read_bytes()
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.REPORT, NOW)
    assert {t: b.verdict for t, b in by_ticker(res).items()} == {
        "AAA": ng.STALE_COPY, "BBB": ng.GENUINE_REPEAT, "CCC": ng.UNVERIFIED,
        "DDD": ng.UNVERIFIED}
    assert {b.action for b in res.bindings} == {ng.REPORT_ACTION}
    assert res.replaced == {} and res.dropped == {}
    assert panel.read_bytes() == before and not (tmp_path / "nav_fallback_log.csv").exists()


def test_still_holds_catches_a_fetch_that_wrote_the_stale_copy_back(tmp_path, panel):
    g = gate_for(tmp_path, panel)
    res = g.run(ASOF, UNI5, ng.ACT, NOW)
    assert g.still_holds(res) == []
    write_nav(panel, NAVS)                       # a later yfinance fetch: AAA stale again
    bad = g.still_holds(res)
    assert bad and all("AAA" in x for x in bad)


def test_the_csv_records_every_binding_and_a_run_with_none(tmp_path, panel):
    path = tmp_path / ng.CSV_NAME
    res = gate_for(tmp_path, panel).run(ASOF, UNI5, ng.ACT, NOW)
    ng.append_csv(path, res, run="r1-run", session_date=D, written_utc=NOW)
    p2 = tmp_path / "moved.parquet"
    write_nav(p2, {"AAA": (9.9, 10.0, 10.1)})
    none = gate_for(tmp_path, p2).run(ASOF, ("AAA",), ng.ACT, NOW)
    ng.append_csv(path, none, run="r2-run", session_date=D, written_utc=NOW)
    rows = pd.read_csv(path, keep_default_na=False)
    assert tuple(rows.columns) == ng.CSV_COLUMNS
    assert rows[["run", "ticker", "verdict", "action"]].values.tolist() == [
        ["r1-run", "AAA", "stale_copy", "replaced"], ["r1-run", "BBB", "genuine_repeat", "kept"],
        ["r1-run", "CCC", "unverified", "dropped"], ["r1-run", "DDD", "unverified", "dropped"],
        ["r2-run", "", "no_repeat", "none"]]
    assert rows.loc[2, "cefconnect_status"] == "absent"
    assert rows.loc[3, "cefconnect_status"].startswith("error: DDD")
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n")
    with pytest.raises(ValueError, match="columns"):
        ng.append_csv(bad, res, run="r3", session_date=D, written_utc=NOW)


# ------------------------------------------------------------- in the session

UNI3 = {"AAA": NAVS["AAA"], "BBB": NAVS["BBB"], "CCC": NAVS["CCC"]}


def session(tmp_path, mode, cc=CC, targets=None):
    """test_run's session with the gate wired on a tmp panel of AAA/BBB/CCC."""
    c, deps, state, seen, out = make(tmp_path)
    p = tmp_path / "cef_nav.parquet"
    write_nav(p, UNI3)
    deps.stale_nav = mode
    deps.nav_gate = gate_for(tmp_path, p, cc)
    calls = []

    def rec_targets(*a, **kw):
        calls.append((a, kw))
        return (targets or targets_book)(*a)
    deps.targets = rec_targets
    return c, deps, state, calls, out, p


def plan_of(state):
    return json.loads((state / D.isoformat() / "plan.json").read_text())


def test_gate_off_the_plan_and_the_sleeve_call_are_unchanged(tmp_path):
    """The default (no `data` block in the book json): nothing new is recorded,
    and the sleeve is called with exactly the four arguments it had before."""
    c, deps, state, seen, out = make(tmp_path)
    assert deps.stale_nav is None and deps.nav_gate is None
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    assert "nav_gate" not in plan_of(state)
    assert len(seen.targets) == 1 and len(seen.targets[0]) == 4
    assert not (state / ng.CSV_NAME).exists()
    assert "NAV GATE" not in "".join(out)


def test_session_drops_unverified_names_through_the_sleeve_and_records_it(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ACT)
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    (args, kw), = calls
    assert args[0] == ASOF
    assert kw["nav_unverified"]["asof"] == ASOF
    assert list(kw["nav_unverified"]["names"]) == ["CCC"]
    assert nav_at(p, "AAA") == 10.05                   # replaced before the sleeve read
    g = plan_of(state)["nav_gate"]
    assert g["mode"] == ng.ACT and g["replaced"] == ["AAA"] and g["dropped"] == ["CCC"]
    assert [b["ticker"] for b in g["bindings"]] == ["AAA", "BBB", "CCC"]
    rows = pd.read_csv(state / ng.CSV_NAME, keep_default_na=False)
    assert rows["ticker"].tolist() == ["AAA", "BBB", "CCC"]
    assert rows["run"].str.endswith("-preview").all()
    assert "NAV GATE (cefconnect_else_drop)" in "".join(out)


def test_session_with_nothing_unverified_calls_the_sleeve_as_before(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ACT, {**CC, "CCC": 30.00})
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    (args, kw), = calls
    assert kw == {} and len(args) == 4
    assert plan_of(state)["nav_gate"]["dropped"] == []


def test_session_fails_if_the_panel_changed_under_the_sleeve(tmp_path):
    """A fetch between the gate and the sleeve's read (the collector runs every 30
    minutes) wrote yfinance's stale copy back: the session must not decide on it."""
    def restore_stale(*a):
        write_nav(tmp_path / "cef_nav.parquet", UNI3)
        return targets_book(*a)
    c, deps, state, calls, out, p = session(tmp_path, ng.ACT, targets=restore_stale)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert c.submits() == []
    assert "changed between the stale-NAV gate" in "".join(out)


def test_report_mode_records_but_drops_nothing(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.REPORT)
    before = p.read_bytes()
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    (args, kw), = calls
    assert kw == {}
    assert p.read_bytes() == before
    g = plan_of(state)["nav_gate"]
    assert g["mode"] == ng.REPORT and g["dropped"] == [] and len(g["bindings"]) == 3


def test_a_gate_error_fails_the_session_in_act_mode_and_is_recorded_in_report_mode(tmp_path):
    boom = {**CC, "AAA": KeyError("NAVData")}           # a bug, not a CEFConnect error
    c, deps, state, calls, out, p = session(tmp_path / "act", ng.ACT, boom)
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_FAIL
    assert calls == []                                   # never decided
    c, deps, state, calls, out, p = session(tmp_path / "rep", ng.REPORT, boom)
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    assert plan_of(state)["nav_gate"]["unmeasured"].startswith("KeyError")
    assert "NAV GATE (report): UNMEASURED: KeyError" in "".join(out)


def test_the_gate_does_not_run_on_a_refresh_that_failed(tmp_path):
    c, deps, state, calls, out, p = session(tmp_path, ng.ACT)
    deps.refresh = lambda asof, t: rn.RefreshResult(exit=4, tail="INCOMPLETE")
    before = p.read_bytes()
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    assert "not_run" in plan_of(state)["nav_gate"] and p.read_bytes() == before
    assert deps.nav_gate.reader.calls == []


def test_a_mode_without_a_gate_wired_raises(tmp_path):
    c, deps, state, seen, out = make(tmp_path)
    deps.stale_nav = ng.ACT
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_FAIL
    assert "no NAV gate wired" in "".join(out)


# ------------------------------------------------------------- the book json switch

@pytest.mark.parametrize("data, want", [
    (None, None),
    ({"stale_nav": "report"}, "report"),
    ({"stale_nav": "cefconnect_else_drop", "_stale_nav_note": "x"}, "cefconnect_else_drop"),
])
def test_stale_nav_setting_absent_is_off(tmp_path, data, want):
    book = {"book_id": "b"} if data is None else {"book_id": "b", "data": data}
    path = tmp_path / "book.json"
    path.write_text(json.dumps(book))
    assert rn.stale_nav_for(rn.Book("cef", "cef", Path("x"), path)) == want


@pytest.mark.parametrize("data", [{"stale_nav": "drop"}, {"stale_nav": None}, {}, "on"])
def test_stale_nav_setting_that_is_not_a_mode_raises(tmp_path, data):
    path = tmp_path / "book.json"
    path.write_text(json.dumps({"book_id": "b", "data": data}))
    with pytest.raises(rn.SessionError):
        rn.stale_nav_for(rn.Book("cef", "cef", Path("x"), path))


def test_the_real_book_json_parses():
    """Whatever the deployed book says, it must be a mode or absent."""
    assert rn.stale_nav_for(rn.BOOKS["cef"]) in (None, *ng.MODES)
