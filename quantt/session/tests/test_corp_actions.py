"""The corporate-action gate: which actions block, and what each mode does to a session.

Alpaca paper processes no corporate actions, so a held name that splits keeps
its old share count while its price moves to the new basis
(`quantt/session/corp_actions.py`). These tests pin the window that decides
which actions block (`blocking_events`, pure), the dating of each held name
from the account's own order history (`held_since`), and the three book-json
settings end to end through `run_session` with fake deps: absent (no gate,
today's behaviour), `report` (record and send) and `halt` (refuse, naming the
event; refuse too when the feed cannot be read).

Hermetic: the client is `test_run.FakeClient` with a `corporate_actions` method
added, state lives under tmp_path, and the root conftest blocks the network.
Events are synthetic; they test the code, never a claim about the market.
"""
import datetime as dt
import json
from pathlib import Path

import pytest

from quantt.session import corp_actions as cam
from quantt.session import run as rn
from quantt.session.tests.test_run import (ASOF, BOOK, D, EVE, LATE, SPEC, FakeClient, make,
                                           to_send_time)

L = dt.date(2026, 9, 21)           # held name CCC's shares were last set (a Monday)
HELD = {"CCC": 100}
# CCC's last fill: submitted 2026-09-21 19:30 ET (23:30Z), filled at the next auction.
CLOSED = [{"id": "o1", "client_order_id": "cef-20260922-CCC-1", "symbol": "CCC",
           "side": "buy", "status": "filled", "filled_qty": "100",
           "submitted_at": "2026-09-21T23:30:00Z"}]


def ev(sym, date, *, typ="reverse_split", role="subject", process=None, other=None, i=None,
       date_field="ex_date"):
    parties = [[sym, role]] + ([list(other)] if other else [])
    return {"id": i or f"{typ}-{sym}-{date}", "type": typ, "date": date,
            "date_field": date_field, "process_date": process or date, "parties": parties}


# ---------------------------------------------------------------- the window

def test_windows_held_from_last_set_target_from_asof_both_through_the_session():
    w = cam.windows({"CCC": L}, ["AAA", "CCC"], ASOF, D)
    assert w == {"AAA": (ASOF, D), "CCC": (L, D)}


def test_a_held_name_set_after_the_asof_still_starts_at_the_asof():
    """A fill on the session morning (a person's) cannot narrow the window past
    the close every order is priced on."""
    assert cam.windows({"CCC": D}, [], ASOF, D) == {"CCC": (ASOF, D)}


def test_windows_refuse_an_asof_that_is_not_before_the_session():
    with pytest.raises(ValueError, match="before the session"):
        cam.windows({}, ["AAA"], D, D)


@pytest.mark.parametrize("date,process,blocks,why", [
    (dt.date(2026, 9, 25), None, True, "after the shares were last set, before the as-of"),
    (L, None, True, "on the day the shares were last set: the fill came after the open"),
    (L - dt.timedelta(days=1), None, False, "before the shares were last set"),
    (ASOF, None, True, "on the as-of date: close(A) on the new basis"),
    (D, None, True, "on the session date: before the fill"),
    (D + dt.timedelta(days=1), None, False, "after the fill: the next session's"),
    (L - dt.timedelta(days=5), dt.date(2026, 9, 24), True, "processed inside the window"),
])
def test_a_held_name_blocks_exactly_inside_its_window(date, process, blocks, why):
    out = cam.blocking_events([ev("CCC", date, process=process)], held={"CCC": L},
                              targets=[], asof=ASOF, session_date=D)
    assert bool(out) is blocks, why


@pytest.mark.parametrize("date,blocks", [
    (ASOF - dt.timedelta(days=1), False),    # fully in the past: close(A) and the fill agree
    (ASOF, True), (D, True), (D + dt.timedelta(days=1), False)])
def test_a_target_only_name_blocks_from_the_asof_through_the_session(date, blocks):
    out = cam.blocking_events([ev("AAA", date)], held={}, targets=["AAA"],
                              asof=ASOF, session_date=D)
    assert bool(out) is blocks


def test_calendar_days_between_the_asof_and_the_session_are_inside():
    """Friday as-of, Monday session: a Sunday process date blocks."""
    fri, mon, sun = dt.date(2026, 10, 2), dt.date(2026, 10, 5), dt.date(2026, 10, 4)
    out = cam.blocking_events([ev("AAA", mon + dt.timedelta(days=30), process=sun)],
                              held={}, targets=["AAA"], asof=fri, session_date=mon)
    assert [b["in_window"] for b in out] == [["process_date"]]


def test_a_held_acquirer_in_a_stock_merger_blocks_and_so_does_the_acquiree():
    """BE CONSERVATIVE: the acquirer's count does not change, but its price can
    jump on the deal's terms. Both sides of one merger block, each named."""
    m = ev("CCC", D, typ="stock_merger", role="acquiree", other=("AAA", "acquirer"),
           date_field="effective_date")
    out = cam.blocking_events([m], held={"CCC": L}, targets=["AAA"], asof=ASOF, session_date=D)
    assert [(b["symbol"], b["role"], b["held"]) for b in out] == [
        ("AAA", "acquirer", False), ("CCC", "acquiree", True)]
    only_acq = cam.blocking_events([m], held={"AAA": L}, targets=[], asof=ASOF, session_date=D)
    assert [(b["symbol"], b["role"]) for b in only_acq] == [("AAA", "acquirer")]


def test_an_event_naming_none_of_our_names_never_blocks():
    m = ev("XYZ", D, typ="stock_merger", role="acquiree", other=("QRS", "acquirer"))
    assert cam.blocking_events([m], held={"CCC": L}, targets=["AAA"], asof=ASOF,
                               session_date=D) == []


def test_a_held_name_with_no_date_raises_rather_than_assume_one():
    with pytest.raises(ValueError, match="CCC"):
        cam.windows({"CCC": None}, [], ASOF, D)


# ------------------------------------------------ when the shares were last set

def test_held_since_is_the_et_submission_date_of_the_last_fill():
    closed = CLOSED + [
        # 2026-09-25 02:30Z is 2026-09-24 22:30 ET: an evening cls send
        {"client_order_id": "b", "symbol": "CCC", "filled_qty": "5",
         "submitted_at": "2026-09-25T02:30:00Z"},
        {"client_order_id": "c", "symbol": "CCC", "filled_qty": "0",          # expired, unfilled
         "submitted_at": "2026-09-27T19:52:00Z"},
        {"client_order_id": "d", "symbol": "AAA", "filled_qty": "3",
         "submitted_at": "2026-09-26T19:52:00Z"}]
    assert cam.held_since(closed, ["CCC"]) == {"CCC": dt.date(2026, 9, 24)}


def test_held_since_raises_for_a_held_name_with_no_fill_or_a_bad_order():
    with pytest.raises(ValueError, match=r"\['BBB'\]"):
        cam.held_since(CLOSED, ["BBB", "CCC"])
    with pytest.raises(ValueError, match="filled_qty"):
        cam.held_since([{"client_order_id": "x", "symbol": "CCC", "filled_qty": "lots",
                         "submitted_at": "2026-09-21T23:30:00Z"}], ["CCC"])


def test_check_with_nothing_held_or_targeted_is_clear_and_reads_nothing():
    calls = []
    rec = cam.check(lambda *a: calls.append(a) or [], [], {}, [], ASOF, D, cam.HALT)
    assert rec["status"] == cam.CLEAR and calls == []


def test_check_asks_for_the_padded_union_of_the_windows():
    calls = []
    cam.check(lambda *a: calls.append(a) or [], CLOSED, HELD, ["AAA"], ASOF, D, cam.REPORT)
    pad = dt.timedelta(days=cam.QUERY_PAD_DAYS)
    assert calls == [(["AAA", "CCC"], L - pad, D + pad)]


def test_refusal_text_names_the_event_and_unmeasured_never_reads_clear():
    b = cam.check(lambda *a: [ev("CCC", D, i="split-1")], CLOSED, HELD, [], ASOF, D, cam.HALT)
    text = cam.refusal_text(b)
    assert "CCC" in text and "reverse_split" in text and "split-1" in text and "held" in text
    u = cam.unmeasured_record(cam.HALT, ASOF, D, "AlpacaHTTPError: 503")
    assert "UNMEASURED" in cam.refusal_text(u) and "503" in cam.refusal_text(u)
    clear = cam.check(lambda *a: [], CLOSED, HELD, [], ASOF, D, cam.HALT)
    assert cam.refusal_text(clear) is None


# ------------------------------------------------------------ the book setting

def _book(tmp_path, block):
    b = tmp_path / "book.json"
    body = {"book_id": "x"}
    if block is not None:
        body["corporate_actions"] = block
    b.write_text(json.dumps(body))
    return rn.Book("cef", "cef", Path("s"), b)


def test_the_setting_absent_is_no_gate_and_a_bad_one_raises(tmp_path):
    assert rn.corporate_actions_for(_book(tmp_path, None)) is None
    assert rn.corporate_actions_for(_book(tmp_path, {"mode": "report"})) == "report"
    assert rn.corporate_actions_for(_book(tmp_path, {"mode": "halt"})) == "halt"
    for bad in ({"mode": "on"}, {"mode": "HALT"}, {}, "halt"):
        with pytest.raises(rn.SessionError, match="corporate_actions"):
            rn.corporate_actions_for(_book(tmp_path, bad))
    assert rn.Deps(client=None, env={}, refresh=None, closes=None, navs=None, targets=None,
                   halts=None).corp_actions is None


def test_the_deployed_book_sets_halt():
    """Team lead 2026-10-28: a HALT guard for the paper runner."""
    assert rn.corporate_actions_for(rn.BOOKS["cef"]) == cam.HALT


# ------------------------------------------------------------- run_session

class CAClient(FakeClient):
    """test_run.FakeClient plus Alpaca's non-dividend corporate-action read."""

    def __init__(self, state, *, events=(), ca_error=None, **kw):
        super().__init__(state, **kw)
        self.events = list(events)
        self.ca_error = ca_error

    def corporate_actions(self, symbols, start, end):
        self.calls.append(("corporate_actions", tuple(symbols), start, end))
        if self.ca_error is not None:
            raise self.ca_error
        return [e for e in self.events if any(s in symbols for s, _ in e["parties"])]


def run(tmp_path, mode, *, events=(), ca_error=None, positions=None, closed=None,
        armed=True, **kw):
    c = CAClient(tmp_path / "state", events=events, ca_error=ca_error,
                 positions=HELD if positions is None else positions,
                 closed=CLOSED if closed is None else closed, **kw.pop("ck", {}))
    c, deps, state, seen, out = make(tmp_path, client=c, **kw)
    deps.corp_actions = mode
    if armed:
        (state / "AUTO_ARMED").touch()
    return c, deps, state, out


def plan_of(state):
    return json.loads((state / D.isoformat() / "plan.json").read_text())


def test_halt_refuses_a_held_name_split_on_the_session_date_with_zero_transmits(tmp_path):
    c, deps, state, out = run(tmp_path, cam.HALT, events=[ev("CCC", D, i="split-1")])
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    assert not (state / D.isoformat() / "STARTED").exists()
    plan = plan_of(state)
    data = [r["detail"] for r in plan["refusals"] if r["gate"] == "data"]
    assert len(data) == 1 and "CCC" in data[0] and "split-1" in data[0]
    assert plan["corporate_actions"]["status"] == cam.BLOCKING
    assert "CORPORATE ACTIONS (halt): BLOCKING" in "".join(out)


def test_halt_refuses_a_target_only_acquiree(tmp_path):
    m = ev("AAA", D, typ="stock_merger", role="acquiree", other=("ZZZ", "acquirer"),
           date_field="effective_date", i="merger-1")
    c, deps, state, out = run(tmp_path, cam.HALT, events=[m])
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    assert "AAA (target) is the acquiree" in plan_of(state)["refusals"][0]["detail"]


def test_halt_sends_when_the_only_action_is_before_the_shares_were_last_set(tmp_path):
    c, deps, state, out = run(tmp_path, cam.HALT, events=[ev("CCC", L - dt.timedelta(days=3))])
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert len(c.submits()) == 3                       # BBB, AAA, and CCC flattened
    rec = plan_of(state)["corporate_actions"]
    assert rec["status"] == cam.CLEAR and len(rec["events"]) == 1 and rec["blocking"] == []


def test_report_records_the_blocking_event_and_sends(tmp_path):
    c, deps, state, out = run(tmp_path, cam.REPORT, events=[ev("CCC", D, i="split-1")])
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert len(c.submits()) == 3
    plan = plan_of(state)
    assert plan["refusals"] == []
    assert plan["corporate_actions"]["status"] == cam.BLOCKING
    assert plan["corporate_actions"]["blocking"][0]["id"] == "split-1"
    assert "CORPORATE ACTIONS (report): BLOCKING" in "".join(out)
    assert "report mode: nothing refused" in "".join(out)


def test_report_changes_nothing_that_trades(tmp_path):
    """Report mode, with a blocking event, against the key absent: the same exit,
    the same orders sent, and plan.json identical once `corporate_actions` is removed."""
    event = [ev("CCC", D)]
    c0, d0, s0, _ = run(tmp_path / "off", None, events=event)
    c1, d1, s1, _ = run(tmp_path / "report", cam.REPORT, events=event)
    assert rn.run_session(BOOK, SPEC, d0) == rn.run_session(BOOK, SPEC, d1) == rn.EXIT_SENT
    assert c0.submits() == c1.submits()
    p0, p1 = plan_of(s0), plan_of(s1)
    assert "corporate_actions" not in p0
    p1.pop("corporate_actions")
    assert p0 == p1


def test_the_key_absent_reads_nothing_and_records_nothing(tmp_path):
    """No-op guard for the default: with the key absent the session never calls
    the read (FakeClient has no such method, so a call would FAIL the run) and
    plan.json carries no `corporate_actions`."""
    c, deps, state, seen, out = make(tmp_path, positions=HELD, closed=CLOSED)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert not any(x[0] == "corporate_actions" for x in c.calls)
    assert "corporate_actions" not in plan_of(state)
    assert "CORPORATE ACTIONS" not in "".join(out)


def test_halt_refuses_when_the_feed_cannot_be_read_and_names_the_error(tmp_path):
    from quantt.broker.alpaca import AlpacaHTTPError
    err = AlpacaHTTPError("GET /v1/corporate-actions failed after 5 attempts; last: HTTP 503",
                          status=503)
    c, deps, state, out = run(tmp_path, cam.HALT, ca_error=err)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    plan = plan_of(state)
    detail = plan["refusals"][0]["detail"]
    assert plan["refusals"][0]["gate"] == "data"
    assert "UNMEASURED" in detail and "AlpacaHTTPError" in detail and "HTTP 503" in detail
    assert plan["corporate_actions"]["status"] == cam.UNMEASURED


def test_report_records_a_failed_read_as_unmeasured_never_clear_and_sends(tmp_path):
    from quantt.broker.alpaca import UnexpectedResponse
    c, deps, state, out = run(tmp_path, cam.REPORT, ca_error=UnexpectedResponse("bad shape"))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    rec = plan_of(state)["corporate_actions"]
    assert rec["status"] == cam.UNMEASURED and "bad shape" in rec["why"]
    assert "UNMEASURED: UnexpectedResponse: bad shape" in "".join(out)


def test_halt_refuses_a_held_name_the_order_history_cannot_date(tmp_path):
    c, deps, state, out = run(tmp_path, cam.HALT, closed=[])
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    assert "UNMEASURED" in plan_of(state)["refusals"][0]["detail"]
    assert not any(x[0] == "corporate_actions" for x in c.calls)


# ------------------------------------------------------- late-market decide / send

def test_late_decide_under_halt_is_refused_not_decided(tmp_path):
    c, deps, state, out = run(tmp_path, cam.HALT, events=[ev("CCC", D)], execution=LATE,
                              ck={"clock_ts": EVE})
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    plan = plan_of(state)
    assert plan["status"] == "refused" and c.submits() == []
    assert any(r["gate"] == "data" and "CCC" in r["detail"] for r in plan["refusals"])


def test_late_send_under_halt_refuses_an_action_listed_after_the_decide(tmp_path):
    """The evening decide saw nothing; by 15:53 Alpaca lists a split effective
    today. The send re-reads and refuses: zero transmits, the reason in send.json."""
    c, deps, state, out = run(tmp_path, cam.HALT, execution=LATE, ck={"clock_ts": EVE})
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    c.events = [ev("CCC", D, i="late-listed")]
    to_send_time(c, deps)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    send = json.loads((state / D.isoformat() / "send.json").read_text())
    assert any(r["gate"] == "data" and "late-listed" in r["detail"] for r in send["refusals"])
    assert send["corporate_actions"]["status"] == cam.BLOCKING
    assert ("orders", "closed", None) in c.calls[-40:]           # a fresh history read


def test_late_send_under_report_records_and_sends(tmp_path):
    c, deps, state, out = run(tmp_path, cam.REPORT, execution=LATE, ck={"clock_ts": EVE})
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    c.events = [ev("CCC", D, i="late-listed")]
    to_send_time(c, deps)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert len(c.submits()) == 3
    send = json.loads((state / D.isoformat() / "send.json").read_text())
    assert send["refusals"] == [] and send["corporate_actions"]["status"] == cam.BLOCKING


def test_late_send_under_halt_refuses_when_the_history_read_fails(tmp_path):
    c, deps, state, out = run(tmp_path, cam.HALT, execution=LATE, ck={"clock_ts": EVE})
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    to_send_time(c, deps)
    real = c.orders

    def orders(*, status, after=None, **kw):
        if status == "closed":
            raise ConnectionError("history unreachable")
        return real(status=status, after=after, **kw)
    c.orders = orders
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    send = json.loads((state / D.isoformat() / "send.json").read_text())
    assert "history unreachable" in send["refusals"][0]["detail"]


def test_late_send_with_the_key_absent_writes_the_same_send_json_keys(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, execution=LATE, positions=HELD,
                                     closed=CLOSED)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    to_send_time(c, deps)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    send = json.loads((state / D.isoformat() / "send.json").read_text())
    assert "corporate_actions" not in send
    assert sum(1 for x in c.calls if x[:2] == ("orders", "closed")) == 1   # the decide's only
