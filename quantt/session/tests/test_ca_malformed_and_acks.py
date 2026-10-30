"""The corporate-action gate: a malformed row that cannot be ours is skipped and recorded.

A team-lead ruling of 2026-10-29, answered interactively on the review of
4c63b1f (AlpacaClient.corporate_actions, "MALFORMED ROWS"):

A. A corporate-action row with an empty or null required symbol used to fail
   the whole read, so under `halt` one bad row for ANY issuer refused every
   session until Alpaca fixed it. Now it is skipped, and recorded in plan.json,
   the run record and one log line naming its id and the missing field, when
   every symbol present in it is outside the book's universe. It still refuses
   when it could be ours: a present symbol is one of the universe's, which
   covers a merger with our fund on one side and the other symbol null.

Every test here FAILS on 4c63b1f (`git archive 4c63b1f`, this file copied
in). The no-op test compares with pins COMPUTED BY 4c63b1f's CODE: with no
malformed row, the orders sent, send.json, plan.json, orders.jsonl, STARTED
(bar its pid) and every run record are byte-identical to 4c63b1f. Its pins
match there; it fails there only where it asserts the new keywords were used.

HOW THE PINS WERE MADE (2026-10-29). `_outputs` run on this worktree while it
was exactly 4c63b1f (clean), under PYTHONHASHSEED unset, 0 and 1: identical
every time. Re-derive only after a deliberate change to what a session writes,
by running `_outputs` on the commit before that change; never edit by hand.

Hermetic. The broker is test_corp_actions.CAClient (test_run.FakeClient plus
the corporate-action read) whose `corporate_actions` is the REAL
`AlpacaClient.corporate_actions` parser over a fake HTTP session, so the rows
go through the code prod runs. Its key file is a temporary file holding test
constants, never config/.env; netguard refuses any socket. The rows are the
reference's examples (test_alpaca_client.CA_REFERENCE) and synthetic rows
built from its field lists: they test the code, never a claim about the market.
"""
import datetime as dt
import hashlib
import json

import pytest

from quantt.broker import alpaca as al
from quantt.session import corp_actions as cam
from quantt.session import run as rn
from quantt.session.tests.test_corp_actions import CLOSED, HELD, L_SET, CAClient
from quantt.session.tests.test_run import BOOK, D, EVE, LATE, SPEC, make, to_send_time
from quantt.tests.test_alpaca_client import (CA_REFERENCE, KEY_ID, SECRET, FakeResp,
                                             FakeSession, route)

DAY = D.isoformat()
PATHS = ("late_send", "cls")
# A well-formed action on a held name, before its shares were last set: in the
# record's events, blocking nothing (test_corp_actions, the same date).
OLD_SPLIT_CCC = {"ex_date": (L_SET - dt.timedelta(days=3)).isoformat(), "id": "rs-ccc-old",
                 "new_rate": 1, "old_rate": 2, "process_date": (L_SET - dt.timedelta(days=3))
                 .isoformat(), "symbol": "CCC", "cusip": "CCC000000"}


def _feed(extra=None):
    """CA_REFERENCE plus the old CCC split, plus `extra` {key: [rows]}."""
    ca = {k: list(v) for k, v in CA_REFERENCE.items()}
    ca["reverse_splits"] = ca["reverse_splits"] + [OLD_SPLIT_CCC]
    for k, rows in (extra or {}).items():
        ca[k] = ca.get(k, []) + rows
    return ca


class RealParserClient(CAClient):
    """CAClient whose corporate-action read is the real AlpacaClient parser over
    a fake HTTP session serving `feed` (one page). `feed` may be replaced
    between sessions."""

    def __init__(self, state, *, feed, key_file, **kw):
        super().__init__(state, **kw)
        self.feed = feed
        session = FakeSession(route({"/v1/corporate-actions": lambda p: FakeResp(
            200, {"corporate_actions": self.feed, "next_page_token": None})}))
        self._real = al.AlpacaClient("cef", key_file, session=session, sleep=lambda s: None)

    last_kw = None             # the keywords of the latest read, for the no-op test

    def corporate_actions(self, symbols, start, end, **kw):
        self.ca_at = len(self.calls)
        self.calls.append(("corporate_actions", tuple(symbols), start, end))
        RealParserClient.last_kw = kw
        return self._real.corporate_actions(symbols, start, end, **kw)


def _key_file(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "alpaca-test.env"            # test constants, never config/.env
    p.write_text(f"ALPACA_CEF_KEY_ID={KEY_ID}\nALPACA_CEF_SECRET_KEY={SECRET}\n")
    return p


def _session(tmp_path, path, feed):
    """(client, deps, state, out, decide exit) ready to transmit on `path`, gate
    under `halt`, armed. `feed` is what Alpaca lists at the transmitting run.
    late_send: the evening decide runs first on the clean reference feed, and
    the feed changes before the 15:53 send, as an action listed after the
    decide would (the send re-reads it)."""
    c = RealParserClient(tmp_path / "state", feed=feed if path == "cls" else _feed(),
                         key_file=_key_file(tmp_path), positions=HELD, closed=CLOSED)
    kw = {"execution": LATE, "now_utc": EVE.astimezone(dt.timezone.utc)} \
        if path == "late_send" else {}
    if path == "late_send":
        c._clock = EVE
    c, deps, state, _, out = make(tmp_path, client=c, **kw)
    deps.corp_actions = cam.HALT
    (state / "AUTO_ARMED").touch()
    decide_exit = None
    if path == "late_send":
        decide_exit = rn.run_session(BOOK, SPEC, deps)
        assert decide_exit == rn.EXIT_PLANNED, "".join(out)
        c.feed = feed
        to_send_time(c, deps)
    return c, deps, state, out, decide_exit


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _outputs(tmp_path, path) -> dict:
    """Hashes of everything the session(s) wrote and sent on the reference feed
    (no malformed row, nothing blocking). STARTED without its pid."""
    c, deps, state, out, decide_exit = _session(tmp_path, path, _feed())
    code = rn.run_session(BOOK, SPEC, deps)
    day = state / DAY
    started = json.loads((day / "STARTED").read_text())
    started.pop("pid")
    got = {"decide_exit": decide_exit, "exit": code,
           "sent": _sha(json.dumps([[o["client_order_id"], o["symbol"], o["side"], o["qty"],
                                     o["time_in_force"]] for o in c.accepted.values()]).encode()),
           "plan_json": _sha((day / "plan.json").read_bytes()),
           "orders_jsonl": _sha((day / "orders.jsonl").read_bytes()),
           "started": _sha(json.dumps(started, sort_keys=True).encode()),
           "runs": {p.name: _sha(p.read_bytes()) for p in sorted((day / "runs").iterdir())}}
    if path == "late_send":
        got["send_json"] = _sha((day / "send.json").read_bytes())
    assert str(tmp_path) not in "".join(p.read_text() for p in day.rglob("*") if p.is_file())
    return got


# PINNED 2026-10-29 on 4c63b1f (module docstring: how, and how to re-derive).
PINNED_4C63B1F = {
    "late_send": {
        "decide_exit": 6, "exit": 0,
        "orders_jsonl": "f6b2e3aa52ef01e3f2576f2c28dbc938461cc54eb9fd6027747ab473fa2ffce9",
        "plan_json": "54c7cdf4c165a5467b4690d1923c01419892f13dd2480e2bfa0959454df51dcc",
        "runs": {   # the evening DECIDE's record, then the SEND's
            "20260929T020000Z-run.json":
                "45c5f921d453636409a71a2b0673e80abb4ae91cb84c6e4d8d90e269efe19b30",
            "20260929T195300Z-run.json":
                "56edd61c8c6f8483012ab6b083d7f54c3e6784a5b7e653e47e6ca77a6d62a94b"},
        "send_json": "62ffe6f1e8cd89e21d5326656099fc92213cbeb4f6badf39b75f9865d8e277c8",
        "sent": "6c86cc494564dd5ccc3467b7823c14954dbaf752588fc62b092fdc8c3c797b55",
        "started": "d6fe7307ef73c5c08447a052e8600eda75af24fe1e5550124bba46f729d0cf24"},
    "cls": {
        "decide_exit": None, "exit": 0,
        "orders_jsonl": "7f67e3d846b0162c98d67881026cdb793f4d9cefa677bccfecc5f1acc2ef4ac7",
        "plan_json": "b7e3fc4fbb027a734c7e74c704298650d9ed7655b898ae9362754fd5926df305",
        "runs": {
            "20260929T123000Z-run.json":
                "50aa67d402394c2fabcff5127380d44d4ebd7c75b2298e683283af188f502f4d"},
        "sent": "022ad3f4f3da8d912ef0949fe203fc18a9c201a31f67e986a968015abce68a09",
        "started": "20108e86665c9897e9f2bacebbb84d2fb92cd10fe2765cfdafcb0ab3abbc7094"},
}


# ------------------------------------------- no malformed row, no ack: a no-op

@pytest.mark.parametrize("path", PATHS)
def test_with_no_malformed_row_the_session_is_byte_identical_to_4c63b1f(tmp_path,
                                                                                    path):
    """With the reference feed (well-formed, one held-name event that blocks
    nothing): everything written and sent equals 4c63b1f's
    pins. The read DID take the new keywords (else the identity is vacuous):
    FAILS on 4c63b1f there, after its pins have matched."""
    got = _outputs(tmp_path, path)
    assert got == PINNED_4C63B1F[path], {k: (got[k], PINNED_4C63B1F[path].get(k))
                                         for k in got if got[k] != PINNED_4C63B1F[path].get(k)}
    plan = json.loads((tmp_path / "state" / DAY / "plan.json").read_text())
    assert plan["corporate_actions"]["status"] == cam.CLEAR
    assert [e["id"] for e in plan["corporate_actions"]["events"]] == ["rs-ccc-old"]
    assert "skipped_malformed" not in plan["corporate_actions"]
    assert RealParserClient.last_kw["skipped"] == [] and \
        set(RealParserClient.last_kw["universe"]) == set(SPEC["frozen"]["universe"])


# ------------------------------------------------ A. malformed rows (ruling A)

# Built from the reference's own rows: an unrelated merger whose acquirer is
# null, and the same shape with our names on one side.
UNRELATED_NULL_ACQUIRER = dict(CA_REFERENCE["stock_mergers"][0], id="sm-null-acquirer",
                               acquirer_symbol=None)
OURS_NULL_ACQUIRER = dict(UNRELATED_NULL_ACQUIRER, id="sm-ccc-null", acquiree_symbol="CCC")
OURS_EMPTY_ACQUIREE = dict(UNRELATED_NULL_ACQUIRER, id="sm-ccc-acquirer",
                           acquirer_symbol="CCC", acquiree_symbol="")
# A reorganization of a TARGETED name whose stock leg has neither ticker nor CUSIP.
OURS_REORG_BAD_LEG = {"id": "reorg-aaa-bad-leg", "symbol": "AAA", "cusip": "AAA000000",
                      "effective_date": "2023-09-01", "process_date": "2023-09-01",
                      "stock_movements": [{"symbol": None, "new_rate": 1, "source_rate": 1}]}


def _refusals(state, path):
    """The transmitting run's refusals: send.json (late send) or plan.json (cls)."""
    name = "send.json" if path == "late_send" else "plan.json"
    return json.loads((state / DAY / name).read_text())["refusals"]


def _transmit(tmp_path, path, feed):
    c, deps, state, out, decide_exit = _session(tmp_path, path, feed)
    n = len(out)
    code = rn.run_session(BOOK, SPEC, deps)
    return c, state, "".join(out[n:]), decide_exit, code


def _gate_records(state, path):
    """The corporate-action record in every file the transmitting run wrote:
    plan.json (cls) or send.json (late), and that run's record."""
    day = state / DAY
    runs = sorted((day / "runs").iterdir())
    files = [day / ("send.json" if path == "late_send" else "plan.json"), runs[-1]]
    return {f.name: json.loads(f.read_text())["corporate_actions"] for f in files}


@pytest.mark.parametrize("path", PATHS)
def test_a_malformed_row_for_unrelated_issuers_is_skipped_and_recorded(tmp_path, path):
    """Ruling A: every symbol present (LSI) is outside the universe, so the row
    is skipped, the session sends, and the row is in plan.json or send.json, the
    run record and ONE log line naming its id and the missing field. On
    4c63b1f the read raised and the session was REFUSED."""
    feed = _feed({"stock_mergers": [UNRELATED_NULL_ACQUIRER]})
    c, state, log, decide_exit, code = _transmit(tmp_path, path, feed)
    assert code == rn.EXIT_SENT, log
    assert decide_exit in (None, rn.EXIT_PLANNED)
    want = [{"id": "sm-null-acquirer", "type": "stock_merger", "missing": ["acquirer_symbol"],
             "present": [["LSI", "acquiree"]],
             "cusips": {"acquiree_cusip": "53223X107", "acquirer_cusip": "30225T102"},
             "dates": {"effective_date": "2023-07-20", "process_date": "2023-07-20"}}]
    for name, ca in _gate_records(state, path).items():
        assert ca["status"] == cam.CLEAR and ca["skipped_malformed"] == want, name
    skipped = [x for x in log.splitlines() if "SKIPPED a malformed row" in x]
    assert len(skipped) == 1 and "sm-null-acquirer" in skipped[0] \
        and "acquirer_symbol null or empty" in skipped[0], log


@pytest.mark.parametrize("key,row,ours", [
    ("reorganizations", OURS_REORG_BAD_LEG, "AAA"),
    ("stock_mergers", OURS_NULL_ACQUIRER, "CCC"),
    ("stock_mergers", OURS_EMPTY_ACQUIREE, "CCC"),
], ids=["reorg-of-ours-bad-leg", "ours-acquiree-null-acquirer", "ours-acquirer-empty-acquiree"])
@pytest.mark.parametrize("path", PATHS)
def test_a_malformed_row_that_could_be_ours_refuses(tmp_path, path, key, row, ours):
    """Ruling A: a present symbol is ours, so the row is never skipped. That
    covers a merger with our fund on one side and the other symbol null or
    empty. Under `halt`: REFUSED, nothing sent, the refusal names our symbol.
    On 4c63b1f the session refused too, but without saying the row could be
    ours (the assertion on that sentence fails there)."""
    c, state, log, decide_exit, code = _transmit(tmp_path, path, _feed({key: [row]}))
    assert code == rn.EXIT_REFUSED and c.submits() == []
    refusal = [r for r in _refusals(state, path) if r["gate"] == "data"]
    assert len(refusal) == 1 and "UNMEASURED" in refusal[0]["detail"]
    assert f"names ['{ours}'], in the book's universe, so it could concern one of ours" \
        in refusal[0]["detail"], refusal
