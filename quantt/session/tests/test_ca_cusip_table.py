"""The CUSIP check: a CUSIP-format party leaves the unresolved list only on proof.

THE RULING (team lead 2026-11-09, "Build a check against our CUSIPs"). A CUSIP-format
party that matches none of the book's funds names nobody; a party matching one of
ours is that fund. THE RISK IS THE FAILURE DIRECTION: a fund's CUSIP changes on a
reverse split or reorganization (IGR's did, 2026-09-08), so a stale table could read
a real event on OUR fund as naming nobody. So these tests pin both directions, and
the second is the larger part: anything short of proof leaves the row unresolved,
naming the fund and the reason (alpaca.py, THE CUSIP CHECK, `_CaCusipTable`).

Rows are the real parser over a fake HTTP session that serves the gate's read and the
table's two reads apart, on their real shapes. The IGR dividend and split rows are as
Alpaca served them (2026-11-08); the rest are fixtures that exercise the table.
Synthetic data tests the code, never a claim about the market.

Hermetic: netguard refuses any socket; the key file holds test constants.
"""
import datetime as dt

import pytest

from quantt.broker import alpaca as al
from quantt.session import corp_actions as cam
from quantt.tests.test_alpaca_client import KEY_ID, SECRET, FakeResp, FakeSession, route

UNI = ["AAA", "CCC", "IGR"]                    # IGR is the universe fund whose CUSIP moved
POS = {"CCC": 10}
TARGETS = ["AAA"]
CLOSED = [{"client_order_id": "cef-20261020-CCC-1", "symbol": "CCC", "side": "buy",
           "status": "filled", "filled_qty": "10", "submitted_at": "2026-10-20T19:53:00Z"}]
D, A = dt.date(2026, 10, 30), dt.date(2026, 10, 29)        # Fri 10-30 as-of Thu 10-29

# AAA and CCC are fixture values with valid check digits, not claims about any security.
AAA, CCC = "00214Q104", "12811L107"
IGR_NEW, IGR_OLD = "12504G878", "12504G100"
DIVIDENDS = [
    {"id": "d-aaa", "symbol": "AAA", "cusip": AAA, "ex_date": "2026-09-15", "process_date": "2026-09-30"},
    {"id": "d-ccc", "symbol": "CCC", "cusip": CCC, "ex_date": "2026-09-15", "process_date": "2026-09-30"},
    {"id": "d-igr-old", "symbol": "IGR", "cusip": IGR_OLD, "ex_date": "2026-08-20", "process_date": "2026-08-31"},
    {"id": "d-igr-new", "symbol": "IGR", "cusip": IGR_NEW, "ex_date": "2026-09-21", "process_date": "2026-09-30"},
]
# The real IGR split row (reverse_splits, id f82ef69f), which names both CUSIPs.
IGR_SPLIT = {"ex_date": "2026-09-08", "id": "f82ef69f-igr", "new_cusip": IGR_NEW, "new_rate": 1,
             "old_cusip": IGR_OLD, "old_rate": 3, "payable_date": "2026-09-08",
             "process_date": "2026-09-08", "record_date": "2026-09-08", "symbol": "IGR"}
# The real SNTI CVR row, moved to the session date so it is inside the windows.
SPIN = {"ex_date": D.isoformat(), "id": "e34ddd44-1ed2-4b30-b668-be3f16e11dce", "new_cusip": "816CVR021",
        "new_rate": 1, "new_symbol": "816CVR021", "payable_date": "2026-11-02",
        "process_date": D.isoformat(), "record_date": D.isoformat(), "source_cusip": "816944102",
        "source_rate": 1, "source_symbol": "SNTI"}
LETTER_LED = "G29CVR019"                       # the letter-led shape on the real feed


def worthless(sym, cusip, rid="w-1"):
    return {"cusip": cusip, "id": rid, "process_date": D.isoformat(), "symbol": sym}


def _client(tmp_path, gate_feed, *, dividends=DIVIDENDS, lookback=(IGR_SPLIT,),
            div_error=None, nd_error=None):
    """The real AlpacaClient over a session serving each of the three reads."""
    kf = tmp_path / "alpaca-test.env"              # test constants, never config/.env
    kf.write_text(f"ALPACA_CEF_KEY_ID={KEY_ID}\nALPACA_CEF_SECRET_KEY={SECRET}\n")

    def handler(p):
        types = p.get("types")
        if types == "cash_dividend":
            if div_error is not None:
                return FakeResp(*div_error)
            return FakeResp(200, {"corporate_actions": {"cash_dividends": list(dividends)},
                                  "next_page_token": None})
        if nd_error is not None and p.get("start", "") < "2025":
            return FakeResp(*nd_error)
        if p.get("start", "") < "2025":              # the table's non-dividend read
            return FakeResp(200, {"corporate_actions": {"reverse_splits": list(lookback)},
                                  "next_page_token": None})
        return FakeResp(200, {"corporate_actions": gate_feed, "next_page_token": None})

    return al.AlpacaClient("cef", kf, session=FakeSession(route({"/v1/corporate-actions": handler})),
                           sleep=lambda s: None)


def _check(tmp_path, gate_feed, mode=cam.HALT, **kw):
    """`corp_actions.check` over the real parser, a book holding CCC and targeting AAA."""
    return cam.check(_client(tmp_path, gate_feed, **kw).corporate_actions, CLOSED, POS, TARGETS,
                     A, D, mode, universe=UNI)


# ------------------------------------------------- proved foreign: it resolves


def test_a_foreign_cusip_resolves_and_is_recorded_not_dropped(tmp_path):
    """The SNTI CVR row: `816CVR021` is none of ours, the table proves it, and the row
    moves from `unresolved` to `foreign_cusip_rows`. It blocks nothing."""
    rec = _check(tmp_path, {"spin_offs": [SPIN]})
    assert rec["status"] == cam.CLEAR and rec["blocking"] == [] and "unresolved" not in rec
    (k,) = rec["foreign_cusip_rows"]
    assert k["id"] == SPIN["id"] and k["foreign_cusips"] == [
        {"field": "new_symbol", "role": "new", "cusip": "816CVR021"}]
    assert rec["cusip_table"]["status"] == "PROVED" and rec["cusip_table"]["cusips"] == 4
    assert any("proved foreign" in line for line in cam.lines(rec))


def test_a_letter_led_cusip_takes_the_same_path_as_a_digit_led_one(tmp_path):
    """Until this check a letter-led CUSIP passed as a ticker and was dropped in silence
    while a digit-led one was a missing party. One path now, by shape: recorded."""
    row = worthless(LETTER_LED, LETTER_LED)
    rec = _check(tmp_path, {"worthless_removals": [row]})
    assert rec["status"] == cam.CLEAR and "unresolved" not in rec
    assert [c["cusip"] for k in rec["foreign_cusip_rows"] for c in k["foreign_cusips"]] == [LETTER_LED]


def test_a_letter_led_cusip_is_not_proved_foreign_when_the_table_cannot_be_read(tmp_path):
    """The same row with the table down: unresolved, like a digit-led one. On the old code
    it passed as a ticker named nobody's, and could never be unresolved."""
    rec = _check(tmp_path, {"worthless_removals": [worthless(LETTER_LED, LETTER_LED)]},
                 div_error=(500, {"message": "down"}))
    assert rec["status"] == cam.BLOCKING
    (u,) = rec["unresolved"]
    assert LETTER_LED in u["saw"]["symbol"] and "CUSIP table could not be read" in u["saw"]["symbol"]


# ----------------------------------- ours: the party is that fund, and it blocks


def test_our_cusip_is_that_fund_and_blocks(tmp_path):
    """A party carrying CCC's CUSIP is CCC: named, and it blocks, on CCC's own window and,
    as before this check, as a row not proved foreign (rule 4)."""
    rec = _check(tmp_path, {"worthless_removals": [worthless(CCC, CCC)]})
    assert rec["status"] == cam.BLOCKING
    ccc = [b for b in rec["blocking"] if b["symbol"] == "CCC" and "unresolved" not in b]
    assert ccc and ccc[0]["role"] == "subject"
    (u,) = rec["unresolved"]
    assert "CUSIP of our fund CCC" in u["saw"]["symbol"] and "foreign_cusip_rows" not in rec


def test_a_superseded_cusip_of_ours_still_blocks_and_names_the_fund(tmp_path):
    """IGR's pre-split CUSIP (12504G100): the failure direction the ruling names. IGR is in
    the universe, its old CUSIP is held in the table, and a row carrying it is IGR's."""
    rec = cam.check(_client(tmp_path, {"worthless_removals": [worthless(IGR_OLD, IGR_OLD)]}).corporate_actions,
                    CLOSED + [{"client_order_id": "cef-20261020-IGR-1", "symbol": "IGR", "side": "buy",
                               "status": "filled", "filled_qty": "5",
                               "submitted_at": "2026-10-20T19:53:00Z"}],
                    {"CCC": 10, "IGR": 5}, TARGETS, A, D, cam.HALT, universe=UNI)
    assert rec["status"] == cam.BLOCKING
    assert any(b["symbol"] == "IGR" and "unresolved" not in b for b in rec["blocking"])
    (u,) = rec["unresolved"]
    assert "CUSIP of our fund IGR" in u["saw"]["symbol"]


def test_a_cusip_sharing_a_funds_issuer_base_stays_unresolved_naming_it(tmp_path):
    """A new CUSIP after a reverse split keeps the issuer base; the table may not have seen
    it yet. It stays unresolved, naming the fund it may be."""
    rec = _check(tmp_path, {"worthless_removals": [worthless("12504G886", "12504G886")]})
    assert rec["status"] == cam.BLOCKING
    (u,) = rec["unresolved"]
    assert "issuer base of our fund IGR" in u["saw"]["symbol"]


def test_a_row_naming_our_ticker_beside_a_foreign_cusip_stays_unresolved(tmp_path):
    """Rule 4: a row that names one of ours by ticker is never moved to resolved, even
    though its CUSIP-format party, on its own, would be proved foreign."""
    row = {**SPIN, "source_symbol": "AAA", "source_cusip": AAA}
    rec = _check(tmp_path, {"spin_offs": [row]})
    assert rec["status"] == cam.BLOCKING and "foreign_cusip_rows" not in rec
    (u,) = rec["unresolved"]
    assert "also names our fund AAA" in u["saw"]["new_symbol"] or "CUSIP of our fund" in u["saw"]["new_symbol"]


def test_a_row_whose_own_cusip_field_is_ours_stays_unresolved(tmp_path):
    """Rule 4 again, through a CUSIP field that is not the party: `source_cusip` is CCC's."""
    row = {**SPIN, "source_cusip": CCC}
    rec = _check(tmp_path, {"spin_offs": [row]})
    assert rec["status"] == cam.BLOCKING and "foreign_cusip_rows" not in rec
    (u,) = rec["unresolved"]
    assert "CUSIP of our fund CCC" in u["saw"]["new_symbol"]


# -------------------------------- not proved: it stays unresolved, named, never "not ours"


def test_a_missing_fund_cusip_stays_unresolved_and_names_the_fund(tmp_path):
    """IGR has no CUSIP in the lookback: nothing can be proved foreign, so the CVR row stays
    unresolved, naming IGR, and blocks. Never read as `not ours`."""
    rec = _check(tmp_path, {"spin_offs": [SPIN]}, dividends=[d for d in DIVIDENDS if d["symbol"] != "IGR"],
                 lookback=())
    assert rec["status"] == cam.BLOCKING and "foreign_cusip_rows" not in rec
    (u,) = rec["unresolved"]
    assert "no CUSIP read for IGR" in u["saw"]["new_symbol"]
    assert rec["cusip_table"]["status"] == "NOT_PROVED"
    assert any("CUSIP TABLE NOT PROVED" in line and "IGR" in line for line in cam.lines(rec))


@pytest.mark.parametrize("which", ["dividends", "non-dividend"])
def test_a_failed_read_stays_unresolved_and_names_the_read(tmp_path, which):
    kw = {"div_error": (500, {"message": "boom"})} if which == "dividends" else {"nd_error": (500, {"message": "boom"})}
    rec = _check(tmp_path, {"spin_offs": [SPIN]}, **kw)
    assert rec["status"] == cam.BLOCKING and "foreign_cusip_rows" not in rec
    (u,) = rec["unresolved"]
    assert "CUSIP table could not be read" in u["saw"]["new_symbol"] and "AlpacaHTTPError" in u["saw"]["new_symbol"]
    assert rec["cusip_table"]["status"] == "NOT_PROVED"


def test_a_split_inside_the_lookback_that_names_no_cusip_stays_unresolved(tmp_path):
    """IGR's split row with its CUSIPs blanked: the table cannot confirm it covers the
    change, so nothing is proved foreign. Names IGR and the row."""
    split = {**IGR_SPLIT, "new_cusip": None, "old_cusip": None}
    rec = _check(tmp_path, {"spin_offs": [SPIN]}, lookback=(split,))
    assert rec["status"] == cam.BLOCKING and "foreign_cusip_rows" not in rec
    (u,) = rec["unresolved"]
    assert "IGR: reverse_split" in u["saw"]["new_symbol"] and "cannot confirm" in u["saw"]["new_symbol"]


def test_an_unreadable_cusip_on_a_funds_row_stays_unresolved(tmp_path):
    rows = [*DIVIDENDS, {"id": "d-bad", "symbol": "AAA", "cusip": "NOT-A-CUSIP"}]
    rec = _check(tmp_path, {"spin_offs": [SPIN]}, dividends=rows)
    assert rec["status"] == cam.BLOCKING and "foreign_cusip_rows" not in rec
    assert "unreadable CUSIP" in rec["unresolved"][0]["saw"]["new_symbol"]


def test_a_cusip_no_field_of_its_row_corroborates_stays_unresolved(tmp_path):
    row = {**SPIN, "new_cusip": "98212B103"}          # a different, valid CUSIP
    rec = _check(tmp_path, {"spin_offs": [row]})
    assert rec["status"] == cam.BLOCKING and "corroborates" in rec["unresolved"][0]["saw"]["new_symbol"]


def test_a_row_older_than_the_tables_coverage_stays_unresolved(tmp_path):
    """A backfill: processed inside (as-of, session] but dated before the table reaches."""
    row = {**SPIN, "ex_date": "2019-01-02", "process_date": D.isoformat()}
    rec = _check(tmp_path, {"spin_offs": [row]})
    assert "foreign_cusip_rows" not in rec
    assert "before the table's coverage" in rec["unresolved"][0]["saw"]["new_symbol"]


# ------------------------------------------------------------- the table itself


def test_the_table_reads_every_fund_every_cusip_over_the_stated_lookback(tmp_path):
    c = _client(tmp_path, {"spin_offs": [SPIN]})
    skipped = []
    start, end = dt.date(2026, 9, 28), dt.date(2028, 10, 30)
    c.corporate_actions(UNI, start, end, universe=UNI, skipped=skipped, rows={})
    table = next(k["cusip_table"] for k in skipped if "cusip_table" in k)
    assert table["lookback_days"] == al.CUSIP_TABLE_LOOKBACK_DAYS and table["funds"] == 3
    assert table["from"] == (start - dt.timedelta(days=al.CUSIP_TABLE_LOOKBACK_DAYS)).isoformat()
    # Both of IGR's CUSIPs are held: the old one from before its split and the new one.
    t = al._CaCusipTable(c, UNI, start, end); t.load()
    assert t.by_cusip[IGR_OLD] == "IGR" and t.by_cusip[IGR_NEW] == "IGR" and not t.reasons


@pytest.mark.parametrize("value,ok", [
    ("816CVR021", True), ("G29CVR019", True), ("12504G878", True),
    ("816CVR022", False), ("AAA", False), ("USU67540AA98", False), (None, False), (9, False)])
def test_cusip_format_needs_the_shape_and_the_check_digit(value, ok):
    assert al._ca_cusip_format(value) is ok


def test_a_universe_ticker_is_never_read_as_a_cusip_while_a_foreign_one_is(tmp_path):
    """A universe name that happens to look CUSIP-format is a ticker, never a CUSIP, in
    the same read that takes another letter-led value down the CUSIP path."""
    row1 = worthless("G29CVR019", "G29CVR019", "w-universe")
    row2 = worthless("N19ESC016", "N19ESC016", "w-foreign")
    # The table needs a CUSIP for every universe fund, this oddly named one included.
    c = _client(tmp_path, {"worthless_removals": [row1, row2]}, dividends=[
        *DIVIDENDS, {"id": "d-odd", "symbol": "G29CVR019", "cusip": AAA, "process_date": "2026-09-30"}])
    sk = []
    got = c.corporate_actions(["G29CVR019"], D, D, universe=["G29CVR019", *UNI], skipped=sk, rows={})
    assert [(e["id"], e["parties"]) for e in got] == [("w-universe", [["G29CVR019", "subject"]])]
    assert [k["id"] for k in sk if "foreign_cusips" in k] == ["w-foreign"]
