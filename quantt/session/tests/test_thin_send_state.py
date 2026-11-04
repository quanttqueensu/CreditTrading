"""CEF trial 55 (te4): "was a reduced decision's send sent?", read from the records run.py really writes.

WHY THIS FILE (the runner owner's review of PR #55, 2026-11-04, item 10, a BLOCKER). te4 is PAPER
ONLY, and paper runs `execution.mode = late_market` (CLAUDE.md order-path rule 3's recorded
exception), so the late-market send is the only one K1-K3 will ever read. A reduced decision is
one whose targets were SENT (pre-registration §4.2), and `drawdown._send_state` decides that from
the session's own records: <D>/STARTED (the rule-2 marker, written before the first order) and
send.json (`exit`, `plan_sha`, `final`, `not_final`). The tests in test_thin_stop_lines.py hand-
write those records. If the hand-written shape differed from what `_send_planned` writes, every
K-line would count wrongly on the book it is for and every test would still pass. So here the
records are written by the REAL send (`run.run_session` in the late window, test_run's fake
client and its late-market fixtures), read back by the runner's own reader
(`run._thin_read_day`) and classified:

  late market (the case that runs)                 sent?
  ------------------------------------------------ -----------------------------------------
  SENT, every order filled                         yes
  SENT, partially filled                           yes (what filled is the account's)
  DRY (DRY_RUN=1)                                  no
  REFUSED (not armed)                              no
  NOTHING_TO_SEND (the only order skipped at send) no
  FAIL, `final` records what went (a rejection)    yes, in part (item 5: classified from final)
  FAIL, `final` records nothing (no confirm)       UNMEASURED: the orders DID reach the broker
  FAIL, `final` records nothing (all rejected)     UNMEASURED: send.json cannot tell it apart
  STARTED missing beside a SENT                    UNMEASURED
  send.json of another plan_sha                    UNMEASURED
  a later manual run's REFUSED over a SENT         UNMEASURED (STARTED beside a refused record)

  cls (the decide is the send; no send.json)       sent?
  ------------------------------------------------ -----------------------------------------
  SENT                                             yes (STARTED)
  REFUSED (not armed)                              no (no STARTED)
  FAIL after a rejection, the rest sent            yes (STARTED)
  FAIL, every order rejected                       yes: STARTED is the only per-session record
                                                   a cls run writes (drawdown.py's `sent`)

Each case is also walked through `thin_stop_record` with the plan marked reduced, so the episode
reads OPEN, NONE or UNMEASURED from the same files. On 87ad4e9 (the head the review read) the
FAIL-with-final case reads UNMEASURED where it now reads a reduced decision sent in part, and
fails here; every other row reads the same on 87ad4e9, and pins that the hand-written shape in
test_thin_stop_lines.py is the runner's.

Hermetic: test_run's FakeClient, fixed clocks, state under tmp_path; netguard refuses any socket.
"""
import datetime as dt
import json

import pytest

from ops.schedule.nyse_calendar import previous_trading_day
from quantt.broker.alpaca import OrderRejected
from quantt.session import drawdown as ddm
from quantt.session import run as rn
from quantt.session.tests.test_run import (BOOK, D, SPEC, decided, make, to_send_time)
from src.deploy.sleeve import FLAT, SHORT, PositionTarget

NEXT = dt.date(2026, 9, 30)          # the session after D: its decide reads D's records back
LINES = {"thin_k1_episode_drawdown": 0.10, "thin_k2_max_name_frac": 0.9,
         "thin_k3_net_run": 0.25, "thin_k3_net_once": 0.8}


def _state_of(state, *, reduced=True):
    """(day, sent?) for D as the runner's reader reads it; `sent?` is `_send_state`'s answer,
    or the Unmeasured raised. The plan is marked as a reduced te4 decision and the session
    before it as decided with the key absent, so `thin_stop_record`'s walk ends there."""
    path = state / D.isoformat() / "plan.json"
    plan = json.loads(path.read_text())
    if reduced:
        plan["thin_session"] = {"reduced": True}
        plan["thin_stops"] = {"K3": {"verdict": ddm.NOT_APPLICABLE}}
        path.write_text(json.dumps(plan))
    before = state / previous_trading_day(D).isoformat()
    before.mkdir(parents=True, exist_ok=True)
    (before / "plan.json").write_text(json.dumps({"refusals": []}))     # the key absent then
    day = rn._thin_read_day(state, D)
    try:
        return day, ddm._send_state(D, day)
    except ddm.Unmeasured as e:
        return day, e


def _episode(state):
    """The next decide's episode, walked over the files run.py wrote (`_thin_read_day`)."""
    r = ddm.thin_stop_record(
        asof=D, session_date=NEXT, drawdown={"status": "HALVE", "asof": D.isoformat()},
        current={"reduced": False}, previous_session=previous_trading_day,
        read_day=lambda d: rn._thin_read_day(state, d), series=[(D, 100_000.0)],
        positions={}, closes={}, thresholds=LINES)
    return r["episode"], r["K0"]["verdict"]


def _late_send(tmp_path, *, armed=True, targets=None, before_send=None):
    """Decide D in the evening (late market), then run the send in the late window. Returns
    (exit, client, state, plan)."""
    kw = {} if targets is None else {"targets": targets}
    c, deps, state, plan = decided(tmp_path, **kw)
    if armed:
        (state / "AUTO_ARMED").touch()
    to_send_time(c, deps)
    deps.sleep = lambda s: None
    if before_send is not None:
        before_send(c, deps, plan)
    return rn.run_session(BOOK, SPEC, deps), c, state, plan


def _cids(plan):
    return [o["client_order_id"] for o in plan["orders"]]


def _send_json(state):
    return json.loads((state / D.isoformat() / "send.json").read_text())


# --------------------------------------------------------------- late market: sent

def test_late_market_sent_and_filled_is_sent(tmp_path):
    code, c, state, plan = _late_send(tmp_path)
    assert code == rn.EXIT_SENT and len(c.submits()) == len(plan["orders"]) == 2
    sj = _send_json(state)
    assert sj["exit"] == "SENT" and sorted(sj["final"]) == sorted(_cids(plan))
    day, st = _state_of(state)
    assert day["started"] is True
    assert st[0] is True and "exited SENT" in st[1] and "2 of the plan's 2" in st[1]
    ep, k0 = _episode(state)
    assert ep["status"] == "OPEN" and ep["reduced_sessions"] == [D] and k0 == ddm.KILLED
    assert "sent_in_part" not in ep


def test_late_market_partially_filled_is_sent(tmp_path):
    """Paper fills market `day` orders with random partials (team lead 2026-09-29). The set was
    sent; what filled is the account's, and K1-K3 read the broker's own figures."""
    def partial(c, deps, plan):
        c._lookup = lambda cid: ({**c.accepted[cid], "status": "canceled", "filled_qty": "1"}
                                 if cid in c.accepted else None)
    code, c, state, plan = _late_send(tmp_path, before_send=partial)
    assert code == rn.EXIT_SENT
    sj = _send_json(state)
    assert all(f["filled"] == 1 and f["unfilled"] > 0 for f in sj["final"].values())
    _, st = _state_of(state)
    assert st[0] is True and "unfilled at the deadline" in st[1]
    ep, _ = _episode(state)
    assert ep["status"] == "OPEN" and ep["reduced_sessions"] == [D]


# --------------------------------------------------------------- late market: not sent

@pytest.mark.parametrize("case", ["dry", "refused"])
def test_late_market_dry_or_refused_is_not_sent(tmp_path, case):
    def dry(c, deps, plan):
        deps.env["DRY_RUN"] = "1"
    code, c, state, _ = _late_send(tmp_path, armed=case == "dry",
                                   before_send=dry if case == "dry" else None)
    assert code == {"dry": rn.EXIT_DRY, "refused": rn.EXIT_REFUSED}[case] and c.submits() == []
    sj = _send_json(state)
    assert sj["exit"] == {"dry": "DRY", "refused": "REFUSED"}[case]
    assert sj["final"] == {} and sj["not_final"] == []
    day, st = _state_of(state)
    assert day["started"] is False
    assert st[0] is False and sj["exit"] in st[1]
    ep, k0 = _episode(state)
    assert ep["status"] == "NONE" and ep["reduced_sessions"] == [] and k0 == ddm.CLEAR


def test_late_market_nothing_to_send_is_not_sent(tmp_path):
    """The plan's only order opens a short, and the name stopped being shortable by the send:
    skipped (team lead 2026-09-28), nothing left, exit NOTHING_TO_SEND, no STARTED."""
    def short_only(asof, holdings, equity, opening):
        return [PositionTarget("BBB", SHORT, weight=-0.05, reason="z=+1"),
                PositionTarget("AAA", FLAT, reason="flat"),
                PositionTarget("CCC", FLAT, reason="flat")]

    def unshortable(c, deps, plan):
        c._assets = {"BBB": {"shortable": False}}
    code, c, state, plan = _late_send(tmp_path, targets=short_only, before_send=unshortable)
    assert code == rn.EXIT_NOTHING and c.submits() == [] and len(plan["orders"]) == 1
    sj = _send_json(state)
    assert sj["exit"] == "NOTHING_TO_SEND" and len(sj["skipped"]) == 1
    _, st = _state_of(state)
    assert st[0] is False and "NOTHING_TO_SEND" in st[1]
    assert _episode(state)[0]["status"] == "NONE"


# --------------------------------------------------------------- late market: FAIL

def test_late_market_fail_whose_final_records_what_went_is_sent_in_part(tmp_path):
    """Items 5 and 10: a rejection skips its symbol and the rest go (team lead 2026-09-28), so
    the send exits FAIL with the rest in `final`. Classified from `final`: sent, in part, and
    the episode names it. Fails on 87ad4e9, which read every FAIL UNMEASURED."""
    def reject_bbb(c, deps, plan):
        cid = next(x for x in _cids(plan) if "-BBB-" in x)
        c._submit = {cid: OrderRejected("403", status=403, client_order_id=cid)}
    code, c, state, plan = _late_send(tmp_path, before_send=reject_bbb)
    assert code == rn.EXIT_FAIL and len(c.accepted) == 1
    sj = _send_json(state)
    assert sj["exit"] == "FAIL" and list(sj["final"]) == list(c.accepted)
    _, st = _state_of(state)
    assert st[0] is True and "FAIL after part of the set went" in st[1]
    assert "1 of the plan's 2" in st[1]
    ep, k0 = _episode(state)
    assert ep["status"] == "OPEN" and ep["reduced_sessions"] == [D] and k0 == ddm.KILLED
    assert list(ep["sent_in_part"]) == [D.isoformat()]


@pytest.mark.parametrize("how", ["noconfirm", "all_rejected"])
def test_late_market_fail_whose_final_records_nothing_is_unmeasured(tmp_path, how):
    """`final` records only orders the confirm read found. When it found none, orders may have
    reached the broker anyway ("noconfirm": both POSTs were accepted), and send.json cannot
    tell that apart from a send whose every order was rejected: UNMEASURED, never NOT SENT."""
    def fail(c, deps, plan):
        c._submit = {cid: ("noconfirm" if how == "noconfirm"
                           else OrderRejected("422", status=422, client_order_id=cid))
                     for cid in _cids(plan)}
    code, c, state, plan = _late_send(tmp_path, before_send=fail)
    assert code == rn.EXIT_FAIL and len(c.submits()) == 2
    sj = _send_json(state)
    assert sj["exit"] == "FAIL" and sj["final"] == {} and sj["not_final"] == []
    _, st = _state_of(state)
    assert isinstance(st, ddm.Unmeasured) and "FAIL" in str(st) and "record no order" in str(st)
    ep, k0 = _episode(state)
    assert ep["status"] == ddm.UNMEASURED and k0 == ddm.UNMEASURED


# --------------------------------------------------------------- late market: records disagree

def test_late_market_sent_with_started_missing_is_unmeasured(tmp_path):
    code, _, state, _ = _late_send(tmp_path)
    assert code == rn.EXIT_SENT
    (state / D.isoformat() / "STARTED").unlink()
    _, st = _state_of(state)
    assert isinstance(st, ddm.Unmeasured) and "no STARTED" in str(st)
    assert _episode(state)[0]["status"] == ddm.UNMEASURED


def test_late_market_send_of_another_plan_sha_is_unmeasured(tmp_path):
    code, _, state, _ = _late_send(tmp_path)
    assert code == rn.EXIT_SENT
    f = state / D.isoformat() / "send.json"
    f.write_text(json.dumps({**json.loads(f.read_text()), "plan_sha": "0" * 64}))
    _, st = _state_of(state)
    assert isinstance(st, ddm.Unmeasured) and "plan_sha" in str(st)


def test_a_later_manual_run_refused_over_a_sent_set_is_unmeasured(tmp_path):
    """After a SENT, a manual run in the window is refused (STARTED exists: no set twice,
    rule 2) and its send.json replaces the SENT one. STARTED beside a REFUSED record: whether
    the set went is not established from send.json, so UNMEASURED, never NOT SENT."""
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    to_send_time(c, deps)
    deps.sleep = lambda s: None
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert _send_json(state)["exit"] == "REFUSED"
    _, st = _state_of(state)
    assert isinstance(st, ddm.Unmeasured) and "STARTED" in str(st)


# --------------------------------------------------------------- cls

def _cls(tmp_path, *, armed=True, submit=None):
    c, deps, state, _, _ = make(tmp_path, submit=submit or {})
    if armed:
        (state / "AUTO_ARMED").touch()
    return rn.run_session(BOOK, SPEC, deps), c, state


@pytest.mark.parametrize("case,want_exit,want", [
    ("sent", rn.EXIT_SENT, True),
    ("refused", rn.EXIT_REFUSED, False),
    ("one_rejected", rn.EXIT_FAIL, True),
    ("all_rejected", rn.EXIT_FAIL, True),
])
def test_cls_is_sent_exactly_when_a_set_started(tmp_path, case, want_exit, want):
    """cls writes no send.json: STARTED (before the first order) is the one per-session record
    of the set, so a set that began counts as sent, whatever then failed (drawdown.py's
    `sent`; its run record says what went). Not a mode te4 trades in: paper is late_market."""
    rej = lambda cid: OrderRejected("422", status=422, client_order_id=cid)
    submit = {"one_rejected": {"cef-20260929-BBB-1": rej("cef-20260929-BBB-1")},
              "all_rejected": {c: rej(c) for c in ("cef-20260929-BBB-1",
                                                   "cef-20260929-AAA-1")}}.get(case)
    code, c, state = _cls(tmp_path, armed=case != "refused", submit=submit)
    assert code == want_exit
    day, st = _state_of(state, reduced=False)
    assert day["send"] is None and "execution" not in day["plan"]
    assert day["started"] is want and st[0] is want and "cls" in st[1]


# --------------------------------------------------------------- shapes the runner cannot reach

A, B = "cef-20260929-AAA-1", "cef-20260929-BBB-1"
FILLED = {"status": "filled", "filled": 10, "unfilled": 0, "filled_avg_price": "10.0"}


def _day(exit_, *, started, final=None, not_final=(), extra=None):
    plan = {"execution": "late_market", "plan_sha": "s", "refusals": [],
            "orders": [{"client_order_id": A}, {"client_order_id": B}]}
    send = {"plan_sha": "s", "exit": exit_, "skipped": [], "final": dict(final or {}),
            "not_final": list(not_final), **(extra or {})}
    return {"plan": plan, "send": send, "started": started}


@pytest.mark.parametrize("day,want", [
    # Accepted and confirmed, still working at the poll's deadline: sent.
    (_day("SENT", started=True, not_final=[A, B]), True),
    (_day("FAIL", started=True, not_final=[A]), True),
    # Records that contradict themselves or the plan: UNMEASURED, naming the record.
    (_day("SENT", started=True), "record no order"),
    (_day("SENT", started=True, final={"cef-20260929-ZZZ-1": FILLED}), "does not hold"),
    (_day("DRY", started=False, final={A: FILLED}), "contradicts itself"),
    (_day("PREVIEW", started=False), "not one a send writes"),
    (_day("SENT", started=True, final={A: FILLED}, extra={"final": None}), "no `final`"),
    (_day("SENT", started=True, final={A: FILLED}, extra={"not_final": None}), "no `not_final`"),
    (_day("FAIL", started=False, final={A: FILLED}), "no STARTED"),
])
def test_records_the_runner_does_not_write_are_never_guessed(day, want):
    """Shapes `_send_planned` does not write, each read as what it says or UNMEASURED, naming
    the record: never SENT or NOT SENT by default. On 87ad4e9 (which read no `final`) the SENT
    with nothing recorded, the stray order and the missing fields read SENT, and the DRY that
    records a fill read NOT SENT; they fail there."""
    if want is True:
        assert ddm._send_state(D, day)[0] is True
    else:
        with pytest.raises(ddm.Unmeasured, match=want):
            ddm._send_state(D, day)
