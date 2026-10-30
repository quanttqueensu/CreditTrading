"""The corporate-action gate: a malformed row that cannot be ours is skipped and recorded; an acknowledged action clears.

Two team-lead rulings of 2026-10-29, answered interactively on the review of
4c63b1f (corp_actions.py, "MALFORMED ROWS" and "ACKNOWLEDGEMENTS"):

A. A corporate-action row with an empty or null required symbol used to fail
   the whole read, so under `halt` one bad row for ANY issuer refused every
   session until Alpaca fixed it. Now it is skipped, and recorded in plan.json,
   the run record and one log line naming its id and the missing field, when
   every symbol present in it is outside the book's universe. It still refuses
   when it could be ours: a present symbol is one of the universe's, which
   covers a merger with our fund on one side and the other symbol null.
B. A backfilled name change, redemption, worthless removal or partial call is
   dated by its process date, falls on the long window, and under `halt` never
   clears by itself. It clears by the team lead's recorded acknowledgement:
   `<state>/ca_acks.json`, written only by `python3 -m quantt.session ca-ack`.
   The gate clears that action id only; anything else, a new action on the
   same fund included, still halts. An unreadable file refuses.

Every test here FAILS on 4c63b1f (`git archive 4c63b1f`, this file copied
in). The two no-op tests compare with pins COMPUTED BY 4c63b1f's CODE: with no
malformed row, no acknowledgement and no backfilled action, the orders sent,
send.json, plan.json, orders.jsonl, STARTED (bar its pid) and every run record
are byte-identical to 4c63b1f. Their pins match there; they fail there only
where they assert that the new path ran (the read's keywords, the file read).

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


def _session(tmp_path, path, feed, *, acks=None):
    """(client, deps, state, out, decide exit) ready to transmit on `path`, gate
    under `halt`, armed. `feed` is what Alpaca lists and `acks` the text of
    <state>/ca_acks.json at the transmitting run. late_send: the evening decide
    runs first on the clean reference feed with no acknowledgement file, and
    the feed and the file change before the 15:53 send, as an action listed or
    acknowledged after the decide would (the send re-reads both)."""
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
    if acks is not None:
        (state / cam.ACKS_FILE).write_text(acks)
    return c, deps, state, out, decide_exit


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _outputs(tmp_path, path, *, acks=None) -> dict:
    """Hashes of everything the session(s) wrote and sent on the reference feed
    (no malformed row, nothing blocking). STARTED without its pid."""
    c, deps, state, out, decide_exit = _session(tmp_path, path, _feed(), acks=acks)
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
def test_with_no_malformed_row_and_no_ack_the_session_is_byte_identical_to_4c63b1f(tmp_path,
                                                                                    path):
    """With the reference feed (well-formed, one held-name event that blocks
    nothing) and no ca_acks.json: everything written and sent equals 4c63b1f's
    pins. The read DID take the new keywords (else the identity is vacuous):
    FAILS on 4c63b1f there, after its pins have matched."""
    got = _outputs(tmp_path, path)
    assert got == PINNED_4C63B1F[path], {k: (got[k], PINNED_4C63B1F[path].get(k))
                                         for k in got if got[k] != PINNED_4C63B1F[path].get(k)}
    plan = json.loads((tmp_path / "state" / DAY / "plan.json").read_text())
    assert plan["corporate_actions"]["status"] == cam.CLEAR
    assert [e["id"] for e in plan["corporate_actions"]["events"]] == ["rs-ccc-old"]
    assert "skipped_malformed" not in plan["corporate_actions"]
    assert "acknowledged" not in plan["corporate_actions"]
    assert RealParserClient.last_kw["skipped"] == [] and \
        set(RealParserClient.last_kw["universe"]) == set(SPEC["frozen"]["universe"])


@pytest.mark.parametrize("path", PATHS)
def test_an_ack_for_an_id_not_in_the_feed_is_harmless(tmp_path, path, monkeypatch):
    """An acknowledgement whose id the feed no longer lists changes nothing: the
    same pins. The file WAS read (FAILS on 4c63b1f, which has no reader)."""
    reads = []
    real = rn._read_ca_acks
    monkeypatch.setattr(rn, "_read_ca_acks", lambda p, b: reads.append(p) or real(p, b))
    got = _outputs(tmp_path, path, acks=_acks_text(["gone-from-the-feed"]))
    assert got == PINNED_4C63B1F[path]
    assert reads and all(p.name == cam.ACKS_FILE for p in reads)


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


# -------------------------------------------- B. acknowledgements (ruling B)

# A backfilled name change on the held name CCC: no ex or effective date, so
# its process date is its market date, inside CCC's long window [L_SET, D].
BACKFILL_NC = {"id": "nc-ccc-backfill", "old_symbol": "CCC", "new_symbol": "CCCN",
               "old_cusip": "CCC000000", "new_cusip": "CCC000001",
               "process_date": "2026-09-24"}
NEW_SPLIT_CCC = dict(OLD_SPLIT_CCC, id="rs-ccc-new", ex_date="2026-09-25",
                     process_date="2026-09-25")
ACKED_AT = "2026-09-29T13:05:00+00:00"


def _acks_text(ids, book="cef", reason="backfilled: the action predates the holding"):
    return json.dumps({"acks": [{"id": i, "reason": reason, "acked_utc": ACKED_AT, "book": book}
                                for i in ids]})


def _refusal_details(state, path="cls"):
    return [r["detail"] for r in _refusals(state, path)]


def _ca_record(state, path):
    name = "send.json" if path == "late_send" else "plan.json"
    return json.loads((state / DAY / name).read_text())["corporate_actions"]


def test_the_backfill_halts_without_an_ack_and_an_acked_id_clears(tmp_path):
    """Control, then ruling B: the backfilled name change refuses every session
    on the long window; with its id acknowledged the session sends, and the
    pair is recorded under `acknowledged` with the reason, and logged. FAILS on
    4c63b1f, which reads no acknowledgement."""
    feed = _feed({"name_changes": [BACKFILL_NC]})
    c, deps, state, out, _ = _session(tmp_path / "no_ack", "cls", feed)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert any("nc-ccc-backfill" in d and "long window" in d for d in _refusal_details(state))

    c, deps, state, out, _ = _session(tmp_path / "ack", "cls", feed,
                                      acks=_acks_text(["nc-ccc-backfill"]))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT, "".join(out)
    ca = json.loads((state / DAY / "plan.json").read_text())["corporate_actions"]
    assert ca["status"] == cam.CLEAR and ca["blocking"] == []
    assert [(a["id"], a["ack"]["reason"]) for a in ca["acknowledged"]] == [
        ("nc-ccc-backfill", "backfilled: the action predates the holding")]
    assert any("ACKNOWLEDGED, cleared for this id only" in x and "nc-ccc-backfill" in x
               for x in "".join(out).splitlines())


@pytest.mark.parametrize("path", PATHS)
def test_an_ack_clears_that_id_only_and_any_other_action_still_halts(tmp_path, path):
    """Ruling B: an ack for another id clears nothing; and with the backfill
    acknowledged, a NEW action on the same fund still refuses, naming only the
    new one. On 4c63b1f the refusal also named the acknowledged id."""
    feed = _feed({"name_changes": [BACKFILL_NC]})
    c, deps, state, out, _ = _session(tmp_path / "other", path, feed,
                                      acks=_acks_text(["some-other-id"]))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED and c.submits() == []
    assert any("nc-ccc-backfill" in d for d in _refusal_details(state, path))

    feed = _feed({"name_changes": [BACKFILL_NC], "reverse_splits": [NEW_SPLIT_CCC]})
    c, deps, state, out, _ = _session(tmp_path / "new", path, feed,
                                      acks=_acks_text(["nc-ccc-backfill"]))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED and c.submits() == []
    data = [d for d in _refusal_details(state, path) if "corporate-action gate" in d]
    assert len(data) == 1 and "rs-ccc-new" in data[0] and "nc-ccc-backfill" not in data[0]
    ca = _ca_record(state, path)
    assert [b["id"] for b in ca["blocking"]] == ["rs-ccc-new"]
    assert [a["id"] for a in ca["acknowledged"]] == ["nc-ccc-backfill"]


@pytest.mark.parametrize("text,why", [
    ("{not json", "JSONDecodeError"),
    (json.dumps({"acks": [{"id": "nc-ccc-backfill", "acked_utc": ACKED_AT, "book": "cef"}]}),
     "reason None"),
    (_acks_text(["nc-ccc-backfill"], book="other"), "book 'other'"),
    (_acks_text(["x", "x"]), "acknowledged twice"),
    (json.dumps([]), "expected"),
    ("", "JSONDecodeError"),
], ids=["not-json", "no-reason", "other-book", "duplicate", "not-an-object", "empty-file"])
@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_ack_file_refuses_even_with_nothing_blocking(tmp_path, path, text, why):
    """Ruling B: a file that cannot be read is never read as empty. With a feed
    that blocks nothing, the session still REFUSES, naming the fault. On
    4c63b1f the file was ignored and the session SENT."""
    c, deps, state, out, _ = _session(tmp_path, path, _feed(), acks=text)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED and c.submits() == []
    refusals = _refusals(state, path)
    assert any(r["gate"] == "data" and "UNMEASURED" in r["detail"] and why in r["detail"]
               for r in refusals), refusals


def test_a_dangling_link_at_the_ack_path_refuses(tmp_path):
    c, deps, state, out, _ = _session(tmp_path, "cls", _feed())
    (state / cam.ACKS_FILE).symlink_to(tmp_path / "nowhere.json")
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert any("UNMEASURED" in d and "FileNotFoundError" in d for d in _refusal_details(state))


# ------------------------------------------------------- B. the ca-ack CLI

ACK_NOW = dt.datetime(2026, 9, 29, 13, 5, tzinfo=dt.timezone.utc)
REASON = "backfilled 2016 name change; paper already holds the new symbol"


def _refused_session(tmp_path, monkeypatch, feed=None):
    """A cls session the backfill refuses, so the state dir holds the gate's
    record (its names and window) for the CLI to read the feed on."""
    c, deps, state, out, _ = _session(tmp_path, "cls", feed or _feed({"name_changes":
                                                                       [BACKFILL_NC]}))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    monkeypatch.setenv("QUANTT_STATE_DIR", str(state))
    return c, deps, state


def _ack(c, *args, now=ACK_NOW):
    return rn.ca_ack_main(["--book", "cef", *args], client=c, now=now)


def test_the_cli_acknowledges_an_id_in_the_feed_atomically_and_the_next_session_sends(
        tmp_path, monkeypatch, capsys):
    """The procedure end to end: refused -> ca-ack -> the next session sends.
    The CLI reads the feed only (no other broker call), writes through
    records.write_json_atomic, and prints what it acknowledged."""
    c, deps, state = _refused_session(tmp_path, monkeypatch)
    writes = []
    real_write = rn.rec.write_json_atomic
    monkeypatch.setattr(rn.rec, "write_json_atomic",
                        lambda p, o: writes.append(p) or real_write(p, o))
    n = len(c.calls)
    assert _ack(c, "--id", "nc-ccc-backfill", "--reason", REASON) == 0
    assert [x[0] for x in c.calls[n:]] == ["corporate_actions"]          # read-only
    assert writes == [state / cam.ACKS_FILE]
    printed = capsys.readouterr().out
    assert "ACKNOWLEDGED nc-ccc-backfill: name_change" in printed and REASON in printed
    assert "it blocked in" in printed
    acks = json.loads((state / cam.ACKS_FILE).read_text())["acks"]
    assert len(acks) == 1 and acks[0]["id"] == "nc-ccc-backfill" and acks[0]["reason"] == REASON
    assert acks[0]["acked_utc"] == ACK_NOW.isoformat() and acks[0]["book"] == "cef"
    assert acks[0]["event"]["type"] == "name_change"
    assert cam.parse_acks(json.loads((state / cam.ACKS_FILE).read_text()), "cef")
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT


def test_the_cli_refuses_an_unknown_id_and_writes_nothing(tmp_path, monkeypatch, capsys):
    c, deps, state = _refused_session(tmp_path, monkeypatch)
    assert _ack(c, "--id", "nc-ccc-typo", "--reason", REASON) == rn.EXIT_REFUSED
    assert "not in the feed" in capsys.readouterr().out
    assert not (state / cam.ACKS_FILE).exists()


def test_the_cli_refuses_a_second_ack_a_bad_reason_and_an_unreadable_file(
        tmp_path, monkeypatch, capsys):
    c, deps, state = _refused_session(tmp_path, monkeypatch)
    path = state / cam.ACKS_FILE
    assert _ack(c, "--id", "nc-ccc-backfill", "--reason", REASON) == 0
    before = path.read_bytes()
    assert _ack(c, "--id", "nc-ccc-backfill", "--reason", "again") == rn.EXIT_REFUSED
    assert "already acknowledged" in capsys.readouterr().out and path.read_bytes() == before
    for bad in ("", "   ", "two\nlines"):
        assert _ack(c, "--id", "nc-ccc-backfill", "--reason", bad) == rn.EXIT_REFUSED
    path.write_text("{not json")
    assert _ack(c, "--id", "nc-ccc-backfill", "--reason", REASON) == rn.EXIT_REFUSED
    assert path.read_text() == "{not json"                       # never rewritten as empty


def test_the_cli_refuses_without_a_gate_record_to_take_the_window_from(tmp_path, monkeypatch,
                                                                       capsys):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("QUANTT_STATE_DIR", str(state))
    c = RealParserClient(state, feed=_feed({"name_changes": [BACKFILL_NC]}),
                         key_file=_key_file(tmp_path))
    assert _ack(c, "--id", "nc-ccc-backfill", "--reason", REASON) == rn.EXIT_REFUSED
    assert "no corporate-action record" in capsys.readouterr().out
    assert c.calls == [] and not (state / cam.ACKS_FILE).exists()


def test_a_failed_rename_leaves_the_old_file_whole(tmp_path, monkeypatch, capsys):
    """Atomic: the new file is a temp file renamed over the old one; when the
    rename fails, the old file is exactly as it was."""
    c, deps, state = _refused_session(
        tmp_path, monkeypatch, _feed({"name_changes": [BACKFILL_NC],
                                      "reverse_splits": [NEW_SPLIT_CCC]}))
    path = state / cam.ACKS_FILE
    assert _ack(c, "--id", "nc-ccc-backfill", "--reason", REASON) == 0
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("rename refused")
    monkeypatch.setattr(rn.rec.os, "replace", boom)
    assert _ack(c, "--id", "rs-ccc-new", "--reason", "corrected by hand") == rn.EXIT_FAIL
    assert "was not changed" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_the_dispatcher_routes_ca_ack(monkeypatch):
    from quantt.session import __main__ as qm
    seen = []
    monkeypatch.setattr(rn, "ca_ack_main", lambda argv: seen.append(argv) or 0)
    assert qm.main(["ca-ack", "--book", "cef", "--id", "x", "--reason", "y"]) == 0
    assert seen == [["--book", "cef", "--id", "x", "--reason", "y"]]
