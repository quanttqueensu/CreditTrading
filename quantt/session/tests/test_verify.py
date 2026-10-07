"""`quantt/session/verify.py`: reconcile from the broker, score, write exactly one verdict line.

What these pin is the promise in ROADMAP 4.7: **silence never reads as
success**. Every path -- a clean traded day, a refused day, a holiday, a
missing record, a foreign order, a missing auction print, a run at the wrong
time, a crash -- writes exactly one line, and every path that is not clean says
FAIL and why. Hermetic: `FakeClient` returns what `quantt.broker.alpaca`
returns (same shapes, already parsed), has no `submit_order`, and one test
drives the real client over a fake HTTP session to prove the shapes match.
The root conftest's netguard fails any test that reaches the network.
"""
import ast
import csv
import datetime as dt
import inspect
import json
from pathlib import Path

import pytest

from quantt.broker import alpaca as al
from quantt.session import records as records_mod
from quantt.session import verify as vf

ET = vf.ET
D = dt.date(2026, 9, 29)          # a Tuesday
PREV = dt.date(2026, 9, 28)
NEXT = dt.date(2026, 9, 30)


def et(day, h, m=0):
    return dt.datetime.combine(day, dt.time(h, m), tzinfo=ET)


def cid(sym, leg=0, day=D):
    return f"cef-{day:%Y%m%d}-{sym}-{leg}"


def order(sym, side, qty, *, status="filled", filled=None, oid=None, c=None, ts=None):
    return {"id": oid or f"id-{sym}", "client_order_id": c or cid(sym), "status": status,
            "symbol": sym, "side": side, "type": "market", "time_in_force": "cls",
            "submitted_at": ts or "2026-09-29T12:30:00.123456789Z",
            "filled_qty": str(qty if filled is None else filled), "qty": str(qty),
            "filled_avg_price": "10.0"}


def fill(sym, side, qty, price, oid=None, i=0):
    return {"id": f"20260929::{sym}{i}", "activity_type": "FILL", "order_id": oid or f"id-{sym}",
            "symbol": sym, "side": side, "qty": str(qty), "price": str(price), "cum_qty": str(qty),
            "leaves_qty": "0", "transaction_time": "2026-09-29T20:00:00Z", "type": "fill",
            "order_status": "filled"}


class FakeClient:
    """The GET surface of AlpacaClient, returning its parsed shapes. Deliberately
    no submit_order: any attempt to transmit is an AttributeError."""

    def __init__(self, *, now=None, is_open=False, next_open=None, sessions=(PREV, D, NEXT),
                 orders=(), fills=(), positions=None, equity=100_500.0, last_equity=100_000.0,
                 prints=None):
        self.now = now or et(D, 17, 30)
        self.is_open = is_open
        self.next_open = next_open or et(NEXT, 9, 30)
        self.sessions = list(sessions)
        self._orders = list(orders)
        self._fills = list(fills)
        self._positions = dict(positions or {})
        self.equity, self.last_equity = equity, last_equity
        self.prints = dict(prints or {})          # (sym, date) -> price | Exception
        self.calls = []

    def clock(self):
        self.calls.append("clock")
        return {"timestamp": self.now, "is_open": self.is_open, "next_open": self.next_open,
                "next_close": self.next_open + dt.timedelta(hours=6, minutes=30), "raw": {}}

    def calendar(self, start, end):
        self.calls.append(("calendar", start, end))
        return [{"date": d, "open": "09:30", "close": "16:00", "raw": {}}
                for d in self.sessions if start <= d <= end]

    def orders(self, *, status, after=None, until=None, limit=500, nested=False):
        assert status == "all", "verify must ask for every status, not just open"
        self.calls.append(("orders", after, until))
        return [o for o in self._orders
                if after <= al.parse_ts(o["submitted_at"], "t") < until]

    def order_by_client_id(self, c):
        self.calls.append(("by_cid", c))
        hits = [o for o in self._orders if o["client_order_id"] == c]
        return hits[0] if hits else None

    def activities_fills(self, date):
        self.calls.append(("fills", date))
        return list(self._fills)

    def positions(self):
        self.calls.append("positions")
        return al.Positions(qty=dict(self._positions), raw=[])

    def account(self):
        self.calls.append("account")
        return {"equity": self.equity, "last_equity": self.last_equity}

    def stock_exchanges(self):
        self.calls.append("exchanges")
        return {"N": "New York Stock Exchange", "P": "NYSE Arca"}

    def primary_sip_code(self, symbol, exchanges):
        self.calls.append(("primary", symbol))
        assert exchanges == {"N": "New York Stock Exchange", "P": "NYSE Arca"}
        return "N"

    def closing_auction_prints(self, symbols, date, *, exchange_codes, condition="M"):
        assert len(symbols) == 1, "verify fetches one symbol at a time"
        assert exchange_codes == {symbols[0]: "N"}, "verify must filter to the primary exchange"
        self.calls.append(("prints", tuple(symbols), date, condition))
        v = self.prints.get((symbols[0], date))
        if v is None:
            raise al.MissingAuctionPrint(f"no print for {symbols}", symbols=list(symbols))
        if isinstance(v, Exception):
            raise v
        return {symbols[0]: {"price": v, "exchange": "N", "condition": condition, "t": "x"}}


@pytest.fixture
def state(tmp_path):
    (tmp_path / D.isoformat()).mkdir()
    return tmp_path


def started(state, records, extra_events=()):
    """STARTED plus orders.jsonl in run.py's event format, written through
    `quantt.session.records` so the serialisation is the runner's own."""
    day = state / D.isoformat()
    assert records_mod.create_exclusive(day / "STARTED", {"session_date": D})
    for r in records:
        records_mod.append_jsonl(day / "orders.jsonl", {
            "event": "submit", "at": et(D, 8, 31), **r, "type": "market", "time_in_force": "cls"})
    for r in records:
        records_mod.append_jsonl(day / "orders.jsonl", {
            "event": "accepted", "at": et(D, 8, 31), "client_order_id": r["client_order_id"],
            "order": {}})
    for e in extra_events:
        records_mod.append_jsonl(day / "orders.jsonl", e)


def plan(state, orders=(), refusals=(), **over):
    """plan.json as run.py writes it (the fields verify reads, plus some it ignores)."""
    p = {"book": "cef", "spec_id": "x", "session_date": D, "asof": PREV, "equity": 1.0,
         "opening_session": False, "plan_sha": "0" * 64, "targets": {}, "notes": {},
         "orders": list(orders), "mode": "run",
         "refusals": [{"gate": g, "detail": d} for g, d in refusals]}
    p.update(over)
    records_mod.write_json_atomic(state / D.isoformat() / "plan.json", p)


def rec(sym, side, qty, leg=0):
    return {"client_order_id": cid(sym, leg), "symbol": sym, "side": side, "qty": qty}


def run(state, client, **kw):
    v = vf.verify_day(client, state, "cef", kw.pop("day", None), **kw)
    return vf.write_outputs(state, v)


def log_lines(state):
    return (state / "verify.log").read_text().splitlines()


def scores(state):
    with (state / "scores.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def traded_day(**over):
    """Held AAA +100 and BBB -50 into D; bought 20 CCC (new) and sold 50 AAA."""
    kw = dict(
        orders=[order("AAA", "sell", 50), order("CCC", "buy", 20)],
        fills=[fill("AAA", "sell", 30, 10.4, i=0), fill("AAA", "sell", 20, 10.6, i=1),
               fill("CCC", "buy", 20, 5.05)],
        positions={"AAA": 50, "BBB": -50, "CCC": 20},
        prints={("AAA", D): 10.5, ("BBB", D): 19.0, ("CCC", D): 5.0,
                ("AAA", PREV): 10.0, ("BBB", PREV): 20.0},
    )
    kw.update(over)
    return FakeClient(**kw)


# ------------------------------------------------------------ clean traded day

def test_a_clean_traded_day_passes_with_both_pnls_and_one_line(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    v = run(state, traded_day())
    assert v.ok, v.reason
    lines = log_lines(state)
    assert len(lines) == 1
    assert lines[0].startswith("2026-09-29 PASS cef traded 2 order(s), 2 filled")
    # hold: AAA 100*(10.5-10) = 50; BBB -50*(19-20) = 50
    # fill: AAA sells -30*(10.5-10.4) - 20*(10.5-10.6) = -3 + 2 = -1; CCC +20*(5.0-5.05) = -1
    assert v.score.auction_hold_pnl == pytest.approx(100.0)
    assert v.score.auction_fill_pnl == pytest.approx(-2.0)
    assert v.score.alpaca_equity_change == pytest.approx(500.0)
    row, = scores(state)
    assert row["verdict"] == "PASS" and row["auction_pnl_usd"] == "98.00"
    assert row["alpaca_equity_change_usd"] == "500.00"
    assert "gross" in row["cost_basis"] and "no borrow" in row["cost_basis"]
    rj = json.loads((state / D.isoformat() / "reconcile.json").read_text())
    assert rj["held_into_close"] == {"AAA": 100, "BBB": -50}
    assert {o["status"] for o in rj["orders"]} == {"filled"}


def test_the_book_held_into_the_close_is_positions_minus_the_days_fills(state):
    # A long closed out today: after = flat, but it was held into the close.
    started(state, [rec("AAA", "sell", 100)])
    c = FakeClient(orders=[order("AAA", "sell", 100)], fills=[fill("AAA", "sell", 100, 10.5)],
                   positions={}, prints={("AAA", D): 10.5, ("AAA", PREV): 10.0})
    v = run(state, c)
    assert v.ok, v.reason
    assert v.detail["held_into_close"] == {"AAA": 100}
    assert v.score.auction_pnl == pytest.approx(50.0)


def test_a_second_run_appends_a_second_line_never_rewrites(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    run(state, traded_day())
    run(state, traded_day())
    assert len(log_lines(state)) == 2
    assert len(scores(state)) == 2


# -------------------------------------------------- the broker disagrees -> FAIL

def test_a_recorded_order_alpaca_does_not_have_fails(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20), rec("ZZZ", "buy", 5)])
    v = run(state, traded_day())
    assert not v.ok
    assert "cef-20260929-ZZZ-0: submitted per orders.jsonl but Alpaca has no such order" in v.reason
    assert log_lines(state)[0].startswith("2026-09-29 FAIL cef ")


@pytest.mark.parametrize("status,filled", [("partially_filled", 30), ("canceled", 0),
                                           ("expired", 0), ("rejected", 0), ("new", 0)])
def test_an_order_not_fully_filled_fails_naming_its_status(state, status, filled):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    fills = [fill("CCC", "buy", 20, 5.05)] + ([fill("AAA", "sell", filled, 10.4)] if filled else [])
    c = traded_day(orders=[order("AAA", "sell", 50, status=status, filled=filled),
                           order("CCC", "buy", 20)],
                   fills=fills, positions={"AAA": 100 - filled, "BBB": -50, "CCC": 20})
    v = run(state, c)
    assert not v.ok
    assert f"AAA cef-20260929-AAA-0: status {status}, filled {filled}/50" in v.reason


def test_filled_status_with_short_filled_qty_fails(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day(orders=[order("AAA", "sell", 50, filled=49), order("CCC", "buy", 20)],
                   fills=[fill("AAA", "sell", 49, 10.4), fill("CCC", "buy", 20, 5.05)],
                   positions={"AAA": 51, "BBB": -50, "CCC": 20})
    assert "status filled, filled 49/50" in run(state, c).reason


def test_an_order_at_alpaca_that_differs_from_the_record_fails(state):
    started(state, [rec("AAA", "sell", 40), rec("CCC", "buy", 20)])
    v = run(state, traded_day())
    assert not v.ok and "qty 50 vs recorded 40" in v.reason


def test_a_runner_order_at_alpaca_missing_from_the_record_fails(state):
    started(state, [rec("AAA", "sell", 50)])
    v = run(state, traded_day())
    assert not v.ok
    assert "at Alpaca but not in orders.jsonl: ['cef-20260929-CCC-0']" in v.reason


def test_a_foreign_order_in_the_account_fails(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    c._orders.append(order("DDD", "buy", 1, c="manual-1", oid="id-manual"))
    v = run(state, c)
    assert not v.ok and "not placed by the runner: ['manual-1']" in v.reason


def test_a_foreign_order_the_evening_before_is_in_the_window(state):
    """cls after 19:00 ET is queued into the next day's auction [V], so the
    evening before D belongs to D's reconcile."""
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    c._orders.append(order("DDD", "buy", 1, c="manual-eve", oid="id-eve",
                           ts="2026-09-28T23:30:00Z"))      # 19:30 ET on PREV
    assert "manual-eve" in run(state, c).reason


def test_yesterdays_runner_orders_are_not_foreign(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    c._orders.insert(0, order("AAA", "buy", 7, c=cid("AAA", day=PREV), oid="id-y",
                              ts="2026-09-28T12:30:00Z"))
    v = run(state, c)
    assert v.ok, v.reason


def test_the_next_auctions_evening_orders_are_not_foreign(state):
    """The runner decides from 22:00 ET for the next auction (team lead
    2026-09-29); a verify re-run late on D sees those orders and they are ours."""
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    c._orders.append(order("AAA", "buy", 7, c=cid("AAA", day=dt.date(2026, 9, 30)),
                           oid="id-next", ts="2026-09-30T02:00:00Z"))   # 22:00 ET on D
    v = run(state, c)
    assert v.ok, v.reason


def test_fills_that_do_not_sum_to_filled_qty_fail(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day(fills=[fill("AAA", "sell", 30, 10.4), fill("CCC", "buy", 20, 5.05)],
                   positions={"AAA": 70, "BBB": -50, "CCC": 20})
    v = run(state, c)
    assert not v.ok
    assert "filled_qty 50, the day's FILL activities sum to 30" in v.reason


def test_a_fill_for_an_order_the_runner_did_not_place_fails(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    c._fills.append(fill("EEE", "buy", 3, 7.0, oid="id-ghost"))
    c._positions["EEE"] = 3
    c.prints[("EEE", D)] = 7.0
    v = run(state, c)
    assert not v.ok and "order id-ghost, which is not one of the runner's orders" in v.reason


def test_started_without_orders_jsonl_fails(state):
    (state / D.isoformat() / "STARTED").write_text("x")
    v = run(state, FakeClient())
    assert not v.ok and "STARTED exists but orders.jsonl does not" in v.reason


def test_a_malformed_orders_jsonl_fails_but_still_reconciles(state):
    (state / D.isoformat() / "STARTED").write_text("x")
    (state / D.isoformat() / "orders.jsonl").write_text(
        '{"event": "submit", "client_order_id": "x"}\n')
    v = run(state, traded_day())
    assert not v.ok
    assert "(submit) lacks ['symbol', 'side', 'qty']" in v.reason
    assert "at Alpaca but not in orders.jsonl" in v.reason
    assert v.score is not None


# ------------------------------------------------------------- no-trade days

def test_a_refused_day_passes_saying_why_and_still_scores_the_held_book(state):
    plan(state, orders=[rec("AAA", "sell", 5)], refusals=[("dry_run", "DRY_RUN is '1', not '0'")])
    c = FakeClient(positions={"AAA": 100}, prints={("AAA", D): 10.5, ("AAA", PREV): 10.0})
    v = run(state, c)
    assert v.ok, v.reason
    assert log_lines(state) == [
        "2026-09-29 PASS cef no trade: refused: [dry_run] DRY_RUN is '1', not '0'; alpaca equity chg "
        "+500.00 USD (official, gross); auction-marked +50.00 USD (gross)"]
    assert scores(state)[0]["traded"] == "False"


def test_an_empty_plan_passes(state):
    plan(state)
    v = run(state, FakeClient())
    assert v.ok and "no trade: the plan had no orders" in v.reason


def test_no_started_and_no_plan_fails(state):
    v = run(state, FakeClient())
    assert not v.ok
    assert "no STARTED and no plan.json: the session left no record" in v.reason
    assert len(log_lines(state)) == 1


def test_no_day_directory_at_all_fails(tmp_path):
    v = run(tmp_path, FakeClient())
    assert not v.ok and "left no record" in v.reason
    assert len(log_lines(tmp_path)) == 1


def test_a_plan_with_orders_and_no_refusal_but_no_started_fails(state):
    plan(state, orders=[rec("AAA", "sell", 5)])
    v = run(state, FakeClient())
    assert not v.ok and "stopped between deciding and recording" in v.reason


def test_a_plan_missing_its_fields_fails(state):
    (state / D.isoformat() / "plan.json").write_text(json.dumps({"session_date": D.isoformat()}))
    v = run(state, FakeClient())
    assert not v.ok
    assert "plan.json lacks ['book', 'mode', 'orders', 'refusals']" in v.reason


def test_a_plan_for_another_day_fails(state):
    plan(state, refusals=[("halt", "x")], session_date=PREV)
    assert "not 'cef' '2026-09-29'" in run(state, FakeClient()).reason


def test_orders_at_alpaca_without_started_fail(state):
    plan(state, refusals=[("dry_run", "DRY_RUN")])
    c = traded_day()
    v = run(state, c)
    assert not v.ok and "no STARTED, yet Alpaca holds" in v.reason


# ---------------------------------------------------- missing auction prints

def test_a_held_name_without_a_print_is_unmeasured_and_the_day_fails(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    del c.prints[("BBB", D)]
    v = run(state, c)
    assert not v.ok
    assert "UNMEASURED BBB: D print: MissingAuctionPrint" in v.reason
    row, = scores(state)
    assert row["auction_pnl_usd"] == "UNMEASURED"
    assert row["alpaca_equity_change_usd"] == "500.00"      # Alpaca's number is still reported
    per = {r["symbol"]: r for r in json.loads(row["per_symbol_json"])}
    assert per["AAA"]["auction_pnl"] is not None and per["BBB"]["auction_pnl"] is None


def test_disagreeing_exchanges_are_a_named_gap(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()
    c.prints[("BBB", PREV)] = al.AmbiguousAuctionPrint("BBB prints disagree")
    v = run(state, c)
    assert not v.ok and "BBB: previous-session print: AmbiguousAuctionPrint" in v.reason


def test_a_missing_exchange_table_is_every_names_gap(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    c = traded_day()

    def boom():
        raise al.UnexpectedResponse("GET /v2/stocks/meta/exchanges: bad")
    c.stock_exchanges = boom
    v = run(state, c)
    assert not v.ok and "exchange-code table: UnexpectedResponse" in v.reason
    assert not any(x[0] == "prints" for x in c.calls if isinstance(x, tuple))


def test_the_condition_is_passed_through(state):
    plan(state, refusals=[("halt", "x")])
    c = FakeClient(positions={"AAA": 1}, prints={("AAA", D): 1.0, ("AAA", PREV): 1.0})
    run(state, c, condition="6")
    assert {x[3] for x in c.calls if x[0] == "prints"} == {"6"}
    assert scores(state)[0]["auction_condition"] == "6"


# ------------------------------------------------------- when it may run

@pytest.mark.parametrize("kw,why", [
    (dict(now=et(NEXT, 17, 30), next_open=et(dt.date(2026, 10, 1), 9, 30)), "must run on 2026-09-29"),
    (dict(now=et(D, 14, 0), is_open=True), "still open"),
    (dict(now=et(D, 8, 0), next_open=et(D, 9, 30)), "has not opened yet"),
])
def test_a_run_outside_the_window_fails_with_one_line_and_reads_nothing_else(state, kw, why):
    plan(state, refusals=[("halt", "x")])
    c = FakeClient(**kw)
    v = run(state, c, day=D)
    assert not v.ok and why in v.reason
    assert len(log_lines(state)) == 1
    assert not (state / "scores.csv").exists()
    assert "account" not in c.calls and "positions" not in c.calls


def test_a_run_just_after_midnight_utc_is_still_d_in_new_york(state):
    plan(state, refusals=[("halt", "x")])
    c = FakeClient(now=dt.datetime(2026, 9, 30, 1, 0, tzinfo=dt.timezone.utc))  # 21:00 ET on D
    v = run(state, c)
    assert v.ok, v.reason
    assert v.date == D


def test_a_holiday_passes_and_a_holiday_with_started_fails(tmp_path):
    hol = dt.date(2026, 11, 26)
    c = FakeClient(now=et(hol, 17, 30), sessions=[dt.date(2026, 11, 25), dt.date(2026, 11, 27)])
    v = run(tmp_path, c)
    assert v.ok and "not a trading day" in v.reason
    (tmp_path / hol.isoformat()).mkdir()
    (tmp_path / hol.isoformat() / "STARTED").write_text("x")
    v = run(tmp_path, c)
    assert not v.ok and "STARTED exists" in v.reason
    assert len(log_lines(tmp_path)) == 2


# ------------------------------------------------------------- CLI and writing

def test_main_without_a_state_dir_exits_2_and_writes_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("QUANTT_STATE_DIR", raising=False)
    assert vf.main(["verify", "--book", "cef"]) == 2
    assert "QUANTT_STATE_DIR" in capsys.readouterr().err


def test_main_turns_any_crash_into_a_fail_line(monkeypatch, state):
    monkeypatch.setenv("QUANTT_STATE_DIR", str(state))

    def boom(book):
        raise al.MissingCredential("QUANTT_ENV_FILE is not set:\nsecond line")
    monkeypatch.setattr(vf, "_make_client", boom)
    assert vf.main(["verify", "--book", "cef", "--date", "2026-09-29"]) == 1
    assert log_lines(state) == ["2026-09-29 FAIL cef verify error: MissingCredential: "
                                "QUANTT_ENV_FILE is not set: second line"]


def test_main_passes_through_and_returns_0_on_pass(monkeypatch, state):
    monkeypatch.setenv("QUANTT_STATE_DIR", str(state))
    plan(state, refusals=[("halt", "x")])
    monkeypatch.setattr(vf, "_make_client", lambda book: FakeClient())
    assert vf.main(["--book", "cef"]) == 0
    assert log_lines(state)[0].startswith("2026-09-29 PASS cef no trade")


def test_a_scores_file_with_foreign_columns_turns_the_day_to_fail(state):
    plan(state, refusals=[("halt", "x")])
    (state / "scores.csv").write_text("a,b\n1,2\n")
    v = run(state, FakeClient())
    assert not v.ok and "could not write verify records" in v.reason
    assert (state / "scores.csv").read_text() == "a,b\n1,2\n"
    assert len(log_lines(state)) == 1


def test_a_long_reason_is_capped_on_one_line():
    v = vf.Verdict(date=D, book="cef", ok=False, reason="x\n" * 5000)
    line = v.line()
    assert "\n" not in line and "truncated; see 2026-09-29/reconcile.json" in line


def test_verify_never_transmits():
    """Read-only by contract: no submit_order, no POST/DELETE/PATCH anywhere in the module."""
    tree = ast.parse(inspect.getsource(vf))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (attrs | names) & {"submit_order", "post", "delete", "patch", "put", "request"}


# ------------------------------------------- end to end through the real client

def test_end_to_end_through_the_real_client_shapes(state, tmp_path):
    """The fake above mirrors the client's return shapes; this proves it, by
    driving the real AlpacaClient over a fake HTTP session with Alpaca-shaped
    JSON. No POST handler exists: a transmit would raise."""
    import requests  # noqa: F401  (the client imports it inside methods)

    class Resp:
        def __init__(self, status, payload):
            self.status_code, self._p, self.text = status, payload, json.dumps(payload)

        def json(self):
            return self._p

    o_aaa = order("AAA", "sell", 50)
    routes = {
        "/v2/clock": {"timestamp": "2026-09-29T17:30:00.123456789-04:00", "is_open": False,
                      "next_open": "2026-09-30T09:30:00-04:00",
                      "next_close": "2026-09-30T16:00:00-04:00"},
        "/v2/calendar": [{"date": "2026-09-28", "open": "09:30", "close": "16:00"},
                         {"date": "2026-09-29", "open": "09:30", "close": "16:00"}],
        "/v2/orders": [o_aaa],
        "/v2/orders:by_client_order_id": o_aaa,
        "/v2/account/activities/FILL": [fill("AAA", "sell", 50, 10.4)],
        "/v2/positions": [{"symbol": "AAA", "qty": "50", "side": "long"}],
        "/v2/account": {"id": "a", "status": "ACTIVE", "currency": "USD", "multiplier": "2",
                        "equity": "100100", "last_equity": "100000", "cash": "1",
                        "buying_power": "1", "regt_buying_power": "1", "initial_margin": "0",
                        "maintenance_margin": "0", "long_market_value": "0",
                        "short_market_value": "0", "shorting_enabled": True,
                        "trading_blocked": False, "account_blocked": False,
                        "trade_suspended_by_user": False},
    }

    routes["/v2/stocks/meta/exchanges"] = {"N": "New York Stock Exchange", "P": "NYSE Arca"}
    routes["/v2/assets/AAA"] = {"symbol": "AAA", "status": "active", "exchange": "NYSE",
                                "tradable": True, "shortable": True, "marginable": True,
                                "fractionable": True}

    def auctions(params):
        day = params["start"][:10]     # "YYYY-MM-DDT04:00:00Z": the ET day starts 04:00Z in EDT
        assert params["end"] == f"{day}T20:30:00Z", params   # never a bare date (Basic-plan 403)
        px = {"2026-09-29": 10.5, "2026-09-28": 10.0}[day]
        return {"auctions": {"AAA": [{"d": day, "o": [], "c": [
            {"t": f"{day}T20:00:00Z", "x": "N", "p": px, "c": "M"},
            {"t": f"{day}T20:00:00Z", "x": "P", "p": px + 0.07, "c": "M"},   # another venue
            {"t": f"{day}T20:00:00Z", "x": "N", "p": px + 0.01, "c": "6"}]}]},
            "next_page_token": None}

    class Sess:
        headers = {}
        posts = []

        def get(self, url, params=None, timeout=None):
            for base in (al.PAPER_BASE, al.DATA_BASE):
                if url.startswith(base):
                    path = url[len(base):]
            if path == "/v2/stocks/auctions":
                return Resp(200, auctions(params))
            return Resp(200, routes[path])

    env = tmp_path / "k.env"
    env.write_text("ALPACA_CEF_KEY_ID=k\nALPACA_CEF_SECRET_KEY=s\n")
    client = al.AlpacaClient("cef", env, session=Sess(), sleep=lambda s: None)
    started(state, [rec("AAA", "sell", 50)])
    v = run(state, client)
    assert v.ok, v.reason
    assert v.detail["held_into_close"] == {"AAA": 100}
    # hold 100*(10.5-10.0)=50; fill -50*(10.5-10.4)=-5
    assert v.score.auction_pnl == pytest.approx(45.0)
    assert v.score.alpaca_equity_change == pytest.approx(100.0)
    assert not hasattr(Sess, "post")


# ------------------------------------------------- run.py's record format

def test_a_rejected_submit_is_named_with_the_runners_own_error(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    day = state / D.isoformat()
    records_mod.append_jsonl(day / "orders.jsonl", {
        "event": "submit", "at": et(D, 8, 32), **rec("ZZZ", "buy", 5)})
    records_mod.append_jsonl(day / "orders.jsonl", {
        "event": "error", "at": et(D, 8, 32), "client_order_id": cid("ZZZ"),
        "error": "OrderRejected: HTTP 403"})
    v = run(state, traded_day())
    assert not v.ok
    assert "cef-20260929-ZZZ-0: submitted per orders.jsonl but Alpaca has no such order" in v.reason
    assert "error: OrderRejected: HTTP 403" in v.reason


def test_an_event_for_an_id_never_submitted_is_a_record_error(state):
    started(state, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)],
            extra_events=[{"event": "confirm", "client_order_id": cid("QQQ"), "ok": True}])
    v = run(state, traded_day())
    assert not v.ok and "event 'confirm' for cef-20260929-QQQ-0, which has no submit line" in v.reason


def test_two_different_submits_under_one_id_are_a_record_error(state):
    started(state, [rec("AAA", "sell", 50), rec("AAA", "sell", 60), rec("CCC", "buy", 20)])
    v = run(state, traded_day())
    assert not v.ok and "submitted as both" in v.reason


def test_a_preview_only_day_fails(state):
    plan(state, orders=[rec("AAA", "sell", 5)], mode="preview")
    v = run(state, FakeClient())
    assert not v.ok and "only a --preview ran" in v.reason


def test_a_refusal_not_in_runs_shape_is_a_record_error(state):
    plan(state, refusals=[("halt", "x")])
    p = json.loads((state / D.isoformat() / "plan.json").read_text())
    p["refusals"] = ["halt"]
    (state / D.isoformat() / "plan.json").write_text(json.dumps(p))
    v = run(state, FakeClient())
    assert not v.ok and "is not {'gate': str, 'detail': str}" in v.reason


def test_late_market_days_are_explained_by_the_send_record():
    from quantt.session.verify import late_no_trade_reason as why
    plan = {"book": "cef", "session_date": D.isoformat(), "mode": "run", "execution": "late_market",
            "status": "decided", "orders": [{"x": 1}], "refusals": [], "send_window": ["a", "b"]}
    ok, prob = why(plan, {"refusals": [{"gate": "dry_run", "detail": "DRY_RUN is '1'"}],
                          "exit": "DRY"}, D, "cef")
    assert prob is None and "refused at send: [dry_run]" in ok
    ok, prob = why(plan, None, D, "cef")
    assert ok is None and "no send ran" in prob                 # asleep: FAIL, said plainly
    ok, prob = why(dict(plan, orders=[]), None, D, "cef")
    assert prob is None
    refused = dict(plan, status="refused", refusals=[{"gate": "data", "detail": "stale"}])
    ok, prob = why(refused, None, D, "cef")
    assert prob is None and "[data]" in ok


def test_a_short_sale_fill_reported_as_sell_short_scores_as_a_sell(tmp_path):
    """Measured 2026-09-30/10-01: Alpaca's FILL activity says "sell_short" for a
    fill that opens a short, while the order says "sell". Verify crashed on it."""
    a, b = tmp_path / "a", tmp_path / "b"
    for st in (a, b):
        (st / D.isoformat()).mkdir(parents=True)
        started(st, [rec("AAA", "sell", 50), rec("CCC", "buy", 20)])
    plain = run(a, traded_day())
    state = b
    c = traded_day(fills=[fill("AAA", "sell_short", 30, 10.4, i=0),
                          fill("AAA", "sell", 20, 10.6, i=1), fill("CCC", "buy", 20, 5.05)])
    v = run(state, c)
    assert v.ok, v.reason
    assert v.score.auction_pnl == plain.score.auction_pnl


def test_an_unknown_fill_side_still_raises():
    from quantt.session.verify import parse_fill
    with pytest.raises(ValueError, match="buy|sell"):
        parse_fill(fill("AAA", "buy_to_cover", 1, 10.0))
