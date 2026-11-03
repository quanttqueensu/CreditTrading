"""C4's first armed session must be an opening session, or the runner refuses it (release-check of 336df9d, R1).

WHY. The runner trades a book's first session to FULL target only when
`run.is_opening_session` is True: no position and no order in the account's
history EVER filled (team lead 2026-09-28). C4 arms on the spare paper account,
which the research loop may also trade (CLAUDE.md rule 1's 2026-10-27 exception).
The loop's past fills there, even ones since flattened, would make C4's first
session open from flat at the band EDGE: 28-42% of target and net long +4.7% to
+11.1% (the release-check's measurement on data/cef_families to 2026-10-09, spec v4).
Until this file the only guard was a person reading checklist step 6. Now
`run.first_session_check` / `first_session_gate` (OPENING_REQUIRED_BOOKS) make it a
gate: ARMED, a non-opening first session is refused before any order, as gate 2
(`arming`), naming the fills it found; UNARMED, it is recorded and printed only. The
gate is spent once the account holds a fill with the book's own prefix (`c4-`), and
the core is not listed.

Each test below fails on f7f7be5 (no such gate: the armed send transmits, and no
plan or send record carries `first_session`).

Hermetic: test_c4_book's generated 74-fund panel under tmp_path (its `c4_world`),
test_run's FakeClient for the broker, netguard on; data/ is never written.
"""
import datetime as dt
import json

from quantt.session import run as rn
from quantt.session.tests.test_c4_book import EVE, SEND, SESSION, _c4, _spec, c4_world  # noqa: F401
from quantt.session.tests.test_run import FakeClient

# Two fills the research loop made in the shared account, both since flattened, and
# a cancel: a history like the one the arming read cannot see in positions.
LAB_FILLS = [
    {"id": "f1", "client_order_id": "lab-20260921-ADX-1", "symbol": "ADX", "side": "buy",
     "status": "filled", "filled_qty": "10", "submitted_at": "2026-09-21T19:53:00Z"},
    {"id": "f2", "client_order_id": "lab-20260924-ADX-2", "symbol": "ADX", "side": "sell",
     "status": "filled", "filled_qty": "10", "submitted_at": "2026-09-24T19:54:00Z"},
    {"id": "c1", "client_order_id": "lab-20260924-EVT-1", "symbol": "EVT", "side": "buy",
     "status": "canceled", "filled_qty": "0", "submitted_at": "2026-09-24T19:55:00Z"},
]


def _client(state, now, closed):
    class C(FakeClient):
        # **kw: main's corporate-action read passes `universe`, `skipped` (and `rows`).
        def corporate_actions(self, symbols, start, end, **kw):
            return []
    return C(state, clock_ts=now, closed=list(closed))


def _session(state, now, monkeypatch, *, closed=(), armed: bool):
    """One C4 run built by default_deps from its book json on the fixture panel:
    the evening decide at EVE or the late-market send at SEND. Armed: DRY_RUN=0 and
    AUTO_ARMED in C4's state dir. Returns (exit, client)."""
    from quantt.broker import alpaca
    c = _client(state, now, closed)
    monkeypatch.setattr(alpaca.AlpacaClient, "from_environment",
                        classmethod(lambda cls, name, **kw: c))
    spec = _spec()
    deps = rn.default_deps(_c4(), spec, {"QUANTT_ENV_FILE": "unused"})
    deps.env = {"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0" if armed else "1"}
    if armed:
        (state / "AUTO_ARMED").touch()
    deps.refresh = lambda a, t: rn.RefreshResult(exit=0, tail="fixture")
    deps.halts = lambda: []
    deps.utcnow = lambda: now.astimezone(dt.timezone.utc)
    deps.out = type("Quiet", (), {"write": lambda self, s: None, "flush": lambda self: None})()
    return rn.run_session(_c4(), spec, deps), c


def _state(tmp_path):
    state = tmp_path / "quantt_state" / "c4"
    state.mkdir(parents=True)
    return state


def _read(state, name):
    return json.loads((state / SESSION / name).read_text())


def test_armed_c4_with_past_fills_in_its_account_is_refused_before_any_order(
        c4_world, monkeypatch, tmp_path):
    """The loop's two flattened fills make C4's first session open at the band edge.
    Armed, the 15:52 send refuses it (gate `arming`), naming the count and the newest
    fill's date, and sends nothing. On f7f7be5 it sent the band-edge book."""
    state = _state(tmp_path)
    code, _ = _session(state, EVE, monkeypatch, closed=LAB_FILLS, armed=True)
    assert code == rn.EXIT_PLANNED                      # the decide: arming is the send's
    plan = _read(state, "plan.json")
    assert plan["opening_session"] is False
    assert plan["first_session"]["action"] == "refused" and plan["first_session"]["armed"]
    code, c = _session(state, SEND, monkeypatch, closed=LAB_FILLS, armed=True)
    assert code == rn.EXIT_REFUSED and c.submits() == []
    assert not (state / SESSION / "STARTED").exists()
    send = _read(state, "send.json")
    (r,) = [r for r in send["refusals"] if "first armed session" in r["detail"]]
    assert r["gate"] == "arming"
    assert "2 filled order(s)" in r["detail"] and "2026-09-24" in r["detail"]
    assert "'lab'" in r["detail"]
    fs = send["first_session"]
    assert (fs["filled_orders"], fs["newest_fill_date"], fs["action"]) == (2, "2026-09-24", "refused")


def test_unarmed_c4_with_past_fills_only_reports(c4_world, monkeypatch, tmp_path):
    """The dry sessions: the same history is recorded and printed, never refused. The
    send is DRY as before (dry_run and arming only, no first-session refusal)."""
    state = _state(tmp_path)
    code, _ = _session(state, EVE, monkeypatch, closed=LAB_FILLS, armed=False)
    assert code == rn.EXIT_PLANNED
    fs = _read(state, "plan.json")["first_session"]
    assert (fs["opening"], fs["armed"], fs["action"], fs["filled_orders"]) == \
        (False, False, "reported", 2)
    code, c = _session(state, SEND, monkeypatch, closed=LAB_FILLS, armed=False)
    assert code == rn.EXIT_DRY and c.submits() == []
    send = _read(state, "send.json")
    assert not any("first armed session" in r["detail"] for r in send["refusals"])
    assert send["first_session"]["action"] == "reported"


def test_armed_c4_on_a_fresh_account_opens_at_full_target_and_sends(
        c4_world, monkeypatch, tmp_path):
    """A never-traded account: an opening session, the gate clear, the send goes."""
    state = _state(tmp_path)
    code, _ = _session(state, EVE, monkeypatch, armed=True)
    assert code == rn.EXIT_PLANNED
    plan = _read(state, "plan.json")
    assert plan["opening_session"] is True and plan["first_session"]["action"] == "clear"
    code, c = _session(state, SEND, monkeypatch, armed=True)
    assert code == rn.EXIT_SENT and c.submits(), _read(state, "send.json")["refusals"]
    assert _read(state, "send.json")["first_session"]["action"] == "clear"


def test_the_gate_is_spent_once_c4_has_its_own_fill():
    """After C4's own first session, its fills make every later session non-opening by
    design; the gate reads nothing then. A lab fill beside it changes nothing."""
    own = {"client_order_id": "c4-20260929-ADX-1", "symbol": "ADX", "filled_qty": "3",
           "submitted_at": "2026-09-29T19:53:00Z"}
    assert rn.first_session_check(_c4(), {"ADX": 3}, [*LAB_FILLS, own]) is None
    got = rn.first_session_check(_c4(), {}, LAB_FILLS)
    assert got["opening"] is False and got["filled_orders"] == 2
    assert rn.first_session_check(_c4(), {}, [])["opening"] is True


def test_the_core_is_unaffected():
    """The core is not in OPENING_REQUIRED_BOOKS: whatever its account holds, the gate
    reads nothing and records nothing, so its plan.json and send.json carry no new key
    (the core's session pins, test_panels_noop / test_combine_noop / test_missing_nav_hold
    / test_sizing_multiplier_noop, pass unchanged)."""
    assert rn.OPENING_REQUIRED_BOOKS == {"c4"}
    core = rn.BOOKS["cef"]
    assert rn.first_session_check(core, {}, LAB_FILLS) is None
    assert rn.first_session_gate(core, None, True) == (None, None, [])
