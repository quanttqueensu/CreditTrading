"""The runner's Alpaca client: parses strictly, pages completely, sends one kind of order once.

Each test pins a promise from `quantt/broker/alpaca.py`'s docstrings that would
rot silently: a later edit that retries the POST, defaults a missing field,
advances a time cursor one order too far, or prints the session. Hermetic
throughout: `FakeSession` stands in for `requests.Session`, a temporary .env
file stands in for the real one (which tests never read), and the root
conftest's netguard fails any test that reaches the network.
"""
import ast
import datetime as dt
import json
from pathlib import Path

import pytest
import requests

from quantt.broker import alpaca as al
from quantt.broker.alpaca_probe import MissingCredential

KEY_ID = "KEYID-must-never-appear-0123"
SECRET = "SECRET-must-never-appear-4567"
D = dt.date(2026, 9, 29)


# ------------------------------------------------------------------ fakes

class FakeResp:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """GETs are answered by `get_handler(url, params) -> FakeResp | Exception`;
    POSTs by `post_handler(url, json) -> FakeResp | Exception`. Every call is
    recorded. There is no put/patch/delete/request attribute, so any such call
    from the client fails with AttributeError."""

    def __init__(self, get_handler=None, post_handler=None):
        self.headers = {}
        self.gets, self.posts = [], []
        self._g, self._p = get_handler, post_handler

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, dict(params or {})))
        r = self._g(url, params or {})
        if isinstance(r, Exception):
            raise r
        return r

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        r = self._p(url, json)
        if isinstance(r, Exception):
            raise r
        return r


def route(table):
    """A get_handler from {path: FakeResp or callable(params)}; unknown -> 404."""
    def h(url, params):
        for base in (al.PAPER_BASE, al.DATA_BASE):
            if url.startswith(base + "/"):
                path = url[len(base):]
                break
        else:
            raise AssertionError(f"request to a non-Alpaca URL {url}")
        v = table.get(path)
        if v is None:
            return FakeResp(404, {"message": "not found"})
        return v(params) if callable(v) else v
    return h


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / "alpaca.env"
    p.write_text(f"ALPACA_CEF_KEY_ID={KEY_ID}\nALPACA_CEF_SECRET_KEY={SECRET}\n")
    return p


@pytest.fixture
def sleeps():
    return []


def client(env_file, sleeps, get=None, post=None):
    s = FakeSession(get or route({}), post)
    return al.AlpacaClient("cef", env_file, session=s, sleep=sleeps.append), s


ACCOUNT = {"id": "acct-1", "status": "ACTIVE", "currency": "USD", "multiplier": "2",
           "equity": "100000.5", "last_equity": "99999", "cash": "100000.5",
           "buying_power": "200001", "regt_buying_power": "200001",
           "initial_margin": "0", "maintenance_margin": "0",
           "long_market_value": "0", "short_market_value": "0",
           "shorting_enabled": True, "trading_blocked": False, "account_blocked": False,
           "trade_suspended_by_user": False}


def order(i, ts, cid=None, **kw):
    o = {"id": f"o{i}", "client_order_id": cid or f"cid-{i}", "status": "new",
         "symbol": "PDI", "side": "buy", "type": "market", "time_in_force": "cls",
         "submitted_at": ts, "filled_qty": "0", "qty": "10"}
    o.update(kw)
    return o


# ------------------------------------------------------ endpoints and keys

def test_a_live_or_any_non_paper_trading_endpoint_is_refused(env_file):
    for bad in ("https://api.alpaca.markets", "https://paper-api.alpaca.markets/",
                "https://paper-api.alpaca.markets.evil.com", "http://paper-api.alpaca.markets"):
        with pytest.raises(ValueError, match="paper"):
            al.AlpacaClient("cef", env_file, base_url=bad, session=FakeSession())


def test_a_non_default_data_endpoint_is_refused(env_file):
    with pytest.raises(ValueError, match="data endpoint"):
        al.AlpacaClient("cef", env_file, data_url="https://example.com", session=FakeSession())


def test_every_request_goes_to_paper_or_data_hosts(env_file, sleeps):
    c, s = client(env_file, sleeps, route({"/v2/account": FakeResp(200, ACCOUNT),
                                           "/v2/clock": FakeResp(200, {
                                               "timestamp": "2026-09-29T09:00:00-04:00", "is_open": False,
                                               "next_open": "2026-09-29T09:30:00-04:00",
                                               "next_close": "2026-09-29T16:00:00-04:00"})}))
    c.account(); c.clock()
    assert all(u.startswith(al.PAPER_BASE + "/v2/") for u, _ in s.gets)


def test_keys_come_from_the_named_file_into_the_headers_only(env_file, sleeps):
    c, s = client(env_file, sleeps)
    assert s.headers == {"APCA-API-KEY-ID": KEY_ID, "APCA-API-SECRET-KEY": SECRET}
    attrs = json.dumps({k: str(v) for k, v in vars(c).items() if k != "_session"})
    assert KEY_ID not in attrs and SECRET not in attrs


def test_a_missing_key_names_the_variable_and_no_other_books_key_is_used(env_file):
    with pytest.raises(MissingCredential) as e:
        al.AlpacaClient("b6", env_file, session=FakeSession())
    msg = str(e.value)
    assert "ALPACA_B6_KEY_ID" in msg and "ALPACA_B6_SECRET_KEY" in msg
    assert KEY_ID not in msg and SECRET not in msg


def test_a_missing_key_file_raises(tmp_path):
    with pytest.raises(MissingCredential, match="does not exist"):
        al.AlpacaClient("cef", tmp_path / "nope.env", session=FakeSession())


def test_from_environment_requires_quantt_env_file(monkeypatch, env_file):
    monkeypatch.delenv("QUANTT_ENV_FILE", raising=False)
    with pytest.raises(MissingCredential, match="QUANTT_ENV_FILE"):
        al.AlpacaClient.from_environment("cef", session=FakeSession())
    monkeypatch.setenv("QUANTT_ENV_FILE", str(env_file))
    c = al.AlpacaClient.from_environment("cef", session=FakeSession())
    assert c.book == "cef"


def test_keys_never_reach_repr_or_any_error_message(env_file, sleeps):
    # Alpaca echoing a header value back in an error body is the worst case.
    echo = f"bad key {KEY_ID} / {SECRET}"
    c, s = client(env_file, sleeps,
                  route({"/v2/account": FakeResp(401, text=echo),
                         "/v2/clock": FakeResp(503, text=echo)}),
                  lambda u, j: FakeResp(403, text=echo))
    msgs = [repr(c), str(c)]
    for call in (c.account, c.clock, lambda: c.submit_order("PDI", 1, "buy", "cef-1")):
        with pytest.raises(al.AlpacaError) as e:
            call()
        msgs.append(str(e.value))
    s._p = lambda u, j: requests.ReadTimeout(f"timeout {SECRET}")
    with pytest.raises(al.AmbiguousSubmit) as e:
        c.submit_order("PDI", 1, "buy", "cef-2")
    msgs.append(str(e.value))
    blob = "\n".join(msgs)
    assert KEY_ID not in blob and SECRET not in blob
    assert "<redacted>" in blob


# --------------------------------------------------------------- parsing

def test_account_parses_every_number_and_bool(env_file, sleeps):
    c, _ = client(env_file, sleeps, route({"/v2/account": FakeResp(200, ACCOUNT)}))
    a = c.account()
    assert a["equity"] == 100000.5 and a["buying_power"] == 200001.0
    assert a["shorting_enabled"] is True and a["trading_blocked"] is False
    assert a["multiplier"] == "2" and a["raw"] == ACCOUNT


@pytest.mark.parametrize("field", ["equity", "last_equity", "buying_power", "shorting_enabled"])
def test_account_missing_field_raises_naming_it(env_file, sleeps, field):
    bad = {k: v for k, v in ACCOUNT.items() if k != field}
    c, _ = client(env_file, sleeps, route({"/v2/account": FakeResp(200, bad)}))
    with pytest.raises(al.UnexpectedResponse, match=field):
        c.account()


def test_account_rejects_a_null_number_and_a_string_boolean(env_file, sleeps):
    for f, v in (("equity", None), ("equity", ""), ("trading_blocked", "false")):
        c, _ = client(env_file, sleeps, route({"/v2/account": FakeResp(200, {**ACCOUNT, f: v})}))
        with pytest.raises(al.UnexpectedResponse, match=f):
            c.account()


def pos(sym, qty, side):
    return {"symbol": sym, "qty": qty, "side": side, "avg_entry_price": "10"}


def test_positions_are_signed_from_side_whichever_sign_convention_alpaca_uses(env_file, sleeps):
    raw = [pos("PDI", "100", "long"), pos("PTY", "-50", "short"), pos("NVG", "25", "short")]
    c, _ = client(env_file, sleeps, route({"/v2/positions": FakeResp(200, raw)}))
    p = c.positions()
    assert p.qty == {"PDI": 100, "PTY": -50, "NVG": -25}
    assert p.raw == raw


@pytest.mark.parametrize("row, match", [
    (pos("PDI", "-100", "long"), "negative"),
    (pos("PDI", "10.5", "long"), "whole"),
    (pos("PDI", "0", "long"), "qty 0"),
    (pos("PDI", "10", "flat"), "long\\|short"),
    ({"symbol": "PDI", "side": "long"}, "qty"),
])
def test_positions_raise_on_contradictions(env_file, sleeps, row, match):
    c, _ = client(env_file, sleeps, route({"/v2/positions": FakeResp(200, [row])}))
    with pytest.raises(al.UnexpectedResponse, match=match):
        c.positions()


def test_positions_raise_on_a_duplicate_symbol(env_file, sleeps):
    raw = [pos("PDI", "1", "long"), pos("PDI", "2", "long")]
    c, _ = client(env_file, sleeps, route({"/v2/positions": FakeResp(200, raw)}))
    with pytest.raises(al.UnexpectedResponse, match="twice"):
        c.positions()


def test_clock_parses_offsets_and_nanoseconds(env_file, sleeps):
    raw = {"timestamp": "2026-09-29T13:00:01.123456789Z", "is_open": True,
           "next_open": "2026-09-30T09:30:00-04:00", "next_close": "2026-09-29T16:00:00-04:00"}
    c, _ = client(env_file, sleeps, route({"/v2/clock": FakeResp(200, raw)}))
    k = c.clock()
    assert k["is_open"] is True
    assert k["timestamp"] == dt.datetime(2026, 9, 29, 13, 0, 1, 123456, tzinfo=dt.timezone.utc)
    assert k["next_close"].utcoffset() == dt.timedelta(hours=-4)


def test_clock_rejects_a_naive_timestamp(env_file, sleeps):
    raw = {"timestamp": "2026-09-29T13:00:01", "is_open": True,
           "next_open": "2026-09-30T09:30:00-04:00", "next_close": "2026-09-29T16:00:00-04:00"}
    c, _ = client(env_file, sleeps, route({"/v2/clock": FakeResp(200, raw)}))
    with pytest.raises(al.UnexpectedResponse, match="offset"):
        c.clock()


def test_calendar_rows_and_out_of_range_day(env_file, sleeps):
    rows = [{"date": "2026-09-29", "open": "09:30", "close": "16:00",
             "session_open": "0400", "session_close": "2000", "settlement_date": "2026-09-30"}]
    c, s = client(env_file, sleeps, route({"/v2/calendar": FakeResp(200, rows)}))
    out = c.calendar(D, D)
    assert out == [{"date": D, "open": "09:30", "close": "16:00", "raw": rows[0]}]
    assert s.gets[-1][1] == {"start": "2026-09-29", "end": "2026-09-29"}
    c, _ = client(env_file, sleeps, route({"/v2/calendar": FakeResp(200, [{**rows[0], "date": "2026-09-30"}])}))
    with pytest.raises(al.UnexpectedResponse, match="outside"):
        c.calendar(D, D)


def asset_row(**kw):
    a = {"symbol": "PDI", "status": "active", "exchange": "NYSE", "tradable": True,
         "shortable": True, "marginable": True, "fractionable": True,
         "borrow_status": "easy_to_borrow", "easy_to_borrow": True}
    a.update(kw)
    return a


def test_asset_404_raises_asset_not_found_and_bad_types_raise(env_file, sleeps):
    c, _ = client(env_file, sleeps, route({"/v2/assets/PDI": FakeResp(200, asset_row())}))
    assert c.asset("PDI")["shortable"] is True
    with pytest.raises(al.AssetNotFound):
        c.asset("ZZZZ")
    c, _ = client(env_file, sleeps, route({"/v2/assets/PDI": FakeResp(200, asset_row(shortable="true"))}))
    with pytest.raises(al.UnexpectedResponse, match="shortable"):
        c.asset("PDI")
    c, _ = client(env_file, sleeps, route({"/v2/assets/PDI": FakeResp(200, asset_row(borrow_status="locate"))}))
    with pytest.raises(al.UnexpectedResponse, match="borrow_status"):
        c.asset("PDI")


# ----------------------------------------------------------- pagination

def orders_server(all_orders):
    """Alpaca's documented semantics: after is exclusive, asc, at most limit."""
    def h(params):
        rows = sorted(all_orders, key=lambda o: al.parse_ts(o["submitted_at"], "t"))
        if "after" in params:
            a = al.parse_ts(params["after"], "after")
            rows = [o for o in rows if al.parse_ts(o["submitted_at"], "t") > a]
        return FakeResp(200, rows[: params["limit"]])
    return h


def test_orders_page_by_time_without_skipping_an_order_that_shares_a_boundary_timestamp(env_file, sleeps):
    # limit 3: page 1 = o1,o2,o3; o3 and o4 share t3 across the page-2 boundary.
    ts = ["2026-09-29T12:00:01Z", "2026-09-29T12:00:02Z", "2026-09-29T12:00:03Z",
          "2026-09-29T12:00:03Z", "2026-09-29T12:00:04Z"]
    allo = [order(i + 1, t) for i, t in enumerate(ts)]
    c, s = client(env_file, sleeps, route({"/v2/orders": orders_server(allo)}))
    got = c.orders(status="all", limit=3)
    assert [o["id"] for o in got] == ["o1", "o2", "o3", "o4", "o5"]
    assert all(p["direction"] == "asc" and p["status"] == "all" for _, p in s.gets)


def test_orders_full_page_all_one_timestamp_raises(env_file, sleeps):
    allo = [order(i, "2026-09-29T12:00:00Z") for i in range(4)]
    c, _ = client(env_file, sleeps, route({"/v2/orders": orders_server(allo)}))
    with pytest.raises(al.UnexpectedResponse, match="all submitted at"):
        c.orders(status="all", limit=3)


def test_orders_status_has_no_default_and_is_validated(env_file, sleeps):
    c, _ = client(env_file, sleeps)
    with pytest.raises(TypeError):
        c.orders()
    with pytest.raises(ValueError):
        c.orders(status="today")
    with pytest.raises(ValueError, match="naive"):
        c.orders(status="all", after=dt.datetime(2026, 9, 29))


def test_orders_passes_nested_and_time_filters(env_file, sleeps):
    c, s = client(env_file, sleeps, route({"/v2/orders": FakeResp(200, [])}))
    c.orders(status="closed", after="2026-09-29T00:00:00-04:00",
             until="2026-09-30T00:00:00-04:00", nested=True)
    p = s.gets[0][1]
    assert p["nested"] == "true" and p["after"].startswith("2026-09-29") and p["until"].startswith("2026-09-30")


def fill(i, **kw):
    a = {"id": f"20260929::{i:04d}", "activity_type": "FILL", "order_id": "o1", "symbol": "PDI",
         "side": "buy", "qty": "1", "price": "10", "cum_qty": "1", "leaves_qty": "0",
         "transaction_time": "2026-09-29T20:00:00Z", "type": "fill", "order_status": "filled"}
    a.update(kw)
    return a


def test_fills_page_with_the_last_id_as_page_token_until_a_short_page(env_file, sleeps):
    allf = [fill(i) for i in range(130)]

    def h(params):
        start = 0
        if "page_token" in params:
            start = [a["id"] for a in allf].index(params["page_token"]) + 1
        return FakeResp(200, allf[start: start + params["page_size"]])
    c, s = client(env_file, sleeps, route({"/v2/account/activities/FILL": h}))
    got = c.activities_fills(D)
    assert [a["id"] for a in got] == [a["id"] for a in allf]
    assert s.gets[1][1]["page_token"] == allf[99]["id"]
    assert all(p["date"] == "2026-09-29" for _, p in s.gets)


def test_fills_reject_an_unknown_type(env_file, sleeps):
    c, _ = client(env_file, sleeps, route({"/v2/account/activities/FILL": FakeResp(200, [fill(1, type="bust")])}))
    with pytest.raises(al.UnexpectedResponse, match="fill\\|partial_fill"):
        c.activities_fills(D)


# ------------------------------------------------ GET retry, 404 semantics

def test_get_retries_429_and_5xx_then_succeeds(env_file, sleeps):
    seq = [FakeResp(429, text="slow"), FakeResp(503, text="down"),
           requests.ConnectionError("reset"), FakeResp(200, ACCOUNT)]
    c, s = client(env_file, sleeps, lambda u, p: seq.pop(0))
    assert c.account()["equity"] == 100000.5
    assert len(s.gets) == 4 and sleeps == list(al.GET_BACKOFF_S[:3])


def test_get_retries_are_bounded(env_file, sleeps):
    c, s = client(env_file, sleeps, lambda u, p: FakeResp(503, text="down"))
    with pytest.raises(al.AlpacaHTTPError, match="after 5 attempts"):
        c.account()
    assert len(s.gets) == len(al.GET_BACKOFF_S) + 1


def test_a_4xx_get_is_not_retried(env_file, sleeps):
    c, s = client(env_file, sleeps, lambda u, p: FakeResp(401, text="unauthorized"))
    with pytest.raises(al.AlpacaHTTPError, match="HTTP 401"):
        c.account()
    assert len(s.gets) == 1 and sleeps == []


def test_order_by_client_id_404_is_none_every_other_failure_raises(env_file, sleeps):
    o = order(1, "2026-09-29T12:00:00Z", cid="cef-20260929-PDI-0")
    c, s = client(env_file, sleeps, route({"/v2/orders:by_client_order_id": FakeResp(200, o)}))
    assert c.order_by_client_id("cef-20260929-PDI-0") == o
    assert s.gets[0][1] == {"client_order_id": "cef-20260929-PDI-0"}
    c, _ = client(env_file, sleeps, route({}))
    assert c.order_by_client_id("cef-20260929-PDI-0") is None
    for status in (401, 500):
        c, _ = client(env_file, sleeps, route({"/v2/orders:by_client_order_id": FakeResp(status, text="x")}))
        with pytest.raises(al.AlpacaHTTPError):
            c.order_by_client_id("cef-20260929-PDI-0")
    c, _ = client(env_file, sleeps, route({"/v2/orders:by_client_order_id": FakeResp(200, {**o, "client_order_id": "other"})}))
    with pytest.raises(al.UnexpectedResponse, match="asked for"):
        c.order_by_client_id("cef-20260929-PDI-0")


# ---------------------------------------------------------------- submit

def echo_ok(url, j):
    return FakeResp(200, {**j, "id": "ord-1", "status": "accepted", "filled_qty": "0",
                          "submitted_at": "2026-09-29T13:00:00Z"})


def test_submit_sends_exactly_one_market_cls_whole_share_order(env_file, sleeps):
    c, s = client(env_file, sleeps, post=echo_ok)
    o = c.submit_order("PDI", 37, "sell", "cef-20260929-PDI-0")
    assert o["id"] == "ord-1"
    assert s.posts == [(al.PAPER_BASE + "/v2/orders",
                        {"symbol": "PDI", "qty": "37", "side": "sell", "type": "market",
                         "time_in_force": "cls", "client_order_id": "cef-20260929-PDI-0"})]


@pytest.mark.parametrize("sym, qty, side, cid", [
    ("PDI", 0, "buy", "c1"), ("PDI", -5, "sell", "c1"), ("PDI", 10.0, "buy", "c1"),
    ("PDI", 2.5, "buy", "c1"), ("PDI", True, "buy", "c1"), ("PDI", "10", "buy", "c1"),
    ("PDI", 1, "sell_short", "c1"), ("pdi", 1, "buy", "c1"), ("PDI", 1, "buy", ""),
    ("PDI", 1, "buy", "x" * 129), ("PDI", 1, "buy", "cef 2026"),
])
def test_submit_refuses_bad_input_before_sending_anything(env_file, sleeps, sym, qty, side, cid):
    c, s = client(env_file, sleeps, post=echo_ok)
    with pytest.raises(ValueError):
        c.submit_order(sym, qty, side, cid)
    assert s.posts == []


def test_submit_refuses_a_non_paper_base_even_if_tampered_after_construction(env_file, sleeps):
    c, s = client(env_file, sleeps, post=echo_ok)
    c._base = "https://api.alpaca.markets"
    with pytest.raises(ValueError, match="non-paper"):
        c.submit_order("PDI", 1, "buy", "cef-1")
    assert s.posts == []


@pytest.mark.parametrize("exc", [requests.ReadTimeout("read timed out"),
                                 requests.ConnectionError("connection reset"),
                                 FakeResp(502, text="bad gateway"),
                                 FakeResp(200, ValueError("not json"), text="<html>")])
def test_an_ambiguous_submit_raises_once_and_is_never_retried(env_file, sleeps, exc):
    c, s = client(env_file, sleeps, post=lambda u, j: exc)
    with pytest.raises(al.AmbiguousSubmit) as e:
        c.submit_order("PDI", 5, "buy", "cef-20260929-PDI-0")
    assert len(s.posts) == 1 and sleeps == [] and s.gets == []
    assert e.value.client_order_id == "cef-20260929-PDI-0"
    assert "do NOT resend" in str(e.value) and "order_by_client_id" in str(e.value)


@pytest.mark.parametrize("status", [403, 422, 429])
def test_a_4xx_submit_is_a_rejection_and_is_not_retried(env_file, sleeps, status):
    c, s = client(env_file, sleeps, post=lambda u, j: FakeResp(status, {"code": 40010001,
                                                                     "message": "client_order_id must be unique"}))
    with pytest.raises(al.OrderRejected) as e:
        c.submit_order("PDI", 5, "buy", "cef-1")
    assert e.value.status == status and len(s.posts) == 1 and sleeps == []


@pytest.mark.parametrize("field, value", [("time_in_force", "day"), ("type", "limit"),
                                          ("qty", "5.5"), ("side", "sell"),
                                          ("client_order_id", "other"), ("id", None)])
def test_an_accepted_order_that_echoes_something_else_raises_but_says_it_exists(env_file, sleeps, field, value):
    c, s = client(env_file, sleeps, post=lambda u, j: FakeResp(200, {**echo_ok(u, j)._payload, field: value}))
    with pytest.raises(al.SubmitResponseInvalid, match="ACCEPTED") as e:
        c.submit_order("PDI", 5, "buy", "cef-1")
    assert field in str(e.value) and len(s.posts) == 1


def test_the_module_has_no_cancel_replace_or_generic_request_path():
    tree = ast.parse(Path(al.__file__).read_text())
    verbs = {"put", "patch", "delete", "request", "cancel_order", "replace_order"}
    hits = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in verbs]
    assert hits == []
    posts = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "post"]
    assert len(posts) == 1, "exactly one POST call site: submit_order"


def test_submit_order_payload_has_no_tif_or_type_parameter():
    import inspect
    params = set(inspect.signature(al.AlpacaClient.submit_order).parameters)
    assert params == {"self", "symbol", "qty", "side", "client_order_id"}


# ------------------------------------------------------ auction prints

def auction_body(rows, token=None):
    return FakeResp(200, {"auctions": rows, "next_page_token": token})


def day(prints, d="2026-09-29"):
    return {"d": d, "o": [], "c": prints}


def pr(x, p, c="M", t="2026-09-29T20:00:00Z"):
    return {"t": t, "x": x, "p": p, "s": 100, "c": c}


def test_auction_returns_the_official_close_not_the_closing_trade(env_file, sleeps):
    body = auction_body({"PDI": [day([pr("N", 18.51, "6"), pr("N", 18.50, "M")])]})
    c, s = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    out = c.closing_auction_prints(["PDI"], D, exchange_codes={"PDI": "N"})
    assert out["PDI"]["price"] == 18.50 and out["PDI"]["condition"] == "M"
    url, params = s.gets[0]
    assert url == al.DATA_BASE + "/v2/stocks/auctions"
    # Timestamps, never a bare date: end=<date> means "up to now" at Alpaca and
    # the Basic plan 403s any SIP query touching the last 15 minutes (2026-09-28).
    # 2026-09-29 is EDT (UTC-4): 00:00 ET = 04:00Z, 16:30 ET = 20:30Z.
    assert params["feed"] == "sip"
    assert params["start"] == "2026-09-29T04:00:00Z" and params["end"] == "2026-09-29T20:30:00Z"


def test_auction_window_follows_the_ny_clock_in_winter(env_file, sleeps):
    """EST (UTC-5) shifts the window an hour; a fixed UTC end would cut the auction."""
    w = dt.date(2026, 12, 1)
    body = auction_body({"PDI": [day([pr("N", 18.50, "M", t="2026-12-01T21:00:00Z")], d="2026-12-01")]})
    c, s = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    c.closing_auction_prints(["PDI"], w, exchange_codes={"PDI": "N"})
    _, params = s.gets[0]
    assert params["start"] == "2026-12-01T05:00:00Z" and params["end"] == "2026-12-01T21:30:00Z"


def test_auction_missing_symbols_raise_by_name_and_no_bar_close_is_used(env_file, sleeps):
    body = auction_body({"PDI": [day([pr("N", 18.5)])], "PTY": [day([pr("N", 14.0, "6")])]})
    c, s = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    with pytest.raises(al.MissingAuctionPrint) as e:
        c.closing_auction_prints(["PDI", "PTY", "NVG"], D,
                                 exchange_codes={"PDI": "N", "PTY": "N", "NVG": "N"})
    assert e.value.symbols == ["NVG", "PTY"]
    assert all("bars" not in u for u, _ in s.gets)


def test_auction_only_the_primary_exchange_counts(env_file, sleeps):
    body = auction_body({"PDI": [day([pr("N", 18.50), pr("P", 18.49)])]})
    c, _ = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    assert c.closing_auction_prints(["PDI"], D, exchange_codes={"PDI": "P"})["PDI"]["price"] == 18.49
    assert c.closing_auction_prints(["PDI"], D, exchange_codes={"PDI": "N"})["PDI"]["price"] == 18.50


def test_auction_agreeing_non_primary_prints_are_not_the_auction(env_file, sleeps):
    # Review 2026-09-28: the primary (N) had no auction print; Arca and Nasdaq
    # agree. The first build returned their price as "the official close".
    body = auction_body({"PDI": [day([pr("P", 18.49), pr("Q", 18.49)])]})
    c, _ = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    with pytest.raises(al.MissingAuctionPrint) as e:
        c.closing_auction_prints(["PDI"], D, exchange_codes={"PDI": "N"})
    assert e.value.symbols == ["PDI"]


def test_auction_requires_a_primary_code_for_every_symbol(env_file, sleeps):
    c, s = client(env_file, sleeps, route({}))
    with pytest.raises(TypeError):
        c.closing_auction_prints(["PDI"], D)
    with pytest.raises(ValueError, match="no primary-exchange SIP code for \\['PTY'\\]"):
        c.closing_auction_prints(["PDI", "PTY"], D, exchange_codes={"PDI": "N"})
    assert s.gets == []


def test_auction_two_primary_prices_are_ambiguous(env_file, sleeps):
    body = auction_body({"PDI": [day([pr("N", 18.50), pr("N", 18.52)])]})
    c, _ = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    with pytest.raises(al.AmbiguousAuctionPrint, match="PDI"):
        c.closing_auction_prints(["PDI"], D, exchange_codes={"PDI": "N"})


def test_primary_sip_code_maps_nyse_through_the_live_exchange_table(env_file, sleeps):
    c, s = client(env_file, sleeps, route({
        "/v2/stocks/meta/exchanges": FakeResp(200, {"N": "New York Stock Exchange",
                                                    "P": "NYSE Arca", "V": "IEX"}),
        "/v2/assets/PDI": FakeResp(200, asset_row())}))
    ex = c.stock_exchanges()
    assert s.gets[0][0] == al.DATA_BASE + "/v2/stocks/meta/exchanges"
    assert c.primary_sip_code("PDI", ex) == "N"


@pytest.mark.parametrize("exch,table,match", [
    ("ARCA", {"N": "New York Stock Exchange"}, "no verified SIP name"),
    ("NYSE", {"P": "NYSE Arca"}, "0 SIP codes"),
    ("NYSE", {"N": "New York Stock Exchange", "X": "New York Stock Exchange"}, "2 SIP codes"),
])
def test_primary_sip_code_refuses_to_guess(env_file, sleeps, exch, table, match):
    c, _ = client(env_file, sleeps, route({"/v2/assets/PDI": FakeResp(200, asset_row(exchange=exch))}))
    with pytest.raises(al.UnmappedExchange, match=match):
        c.primary_sip_code("PDI", table)


@pytest.mark.parametrize("body", [{}, [], {"stock_exchanges": {"N": "x"}}, {"N": ""}])
def test_stock_exchanges_strict_shape(env_file, sleeps, body):
    c, _ = client(env_file, sleeps, route({"/v2/stocks/meta/exchanges": FakeResp(200, body)}))
    with pytest.raises(al.UnexpectedResponse):
        c.stock_exchanges()


def test_auction_pages_on_next_page_token(env_file, sleeps):
    pages = {None: auction_body({"PDI": [day([pr("N", 18.5)])]}, token="tok1"),
             "tok1": auction_body({"PTY": [day([pr("N", 14.0)])]})}
    c, s = client(env_file, sleeps, route({"/v2/stocks/auctions": lambda p: pages[p.get("page_token")]}))
    out = c.closing_auction_prints(["PTY", "PDI"], D, exchange_codes={"PDI": "N", "PTY": "N"})
    assert {k: v["price"] for k, v in out.items()} == {"PDI": 18.5, "PTY": 14.0}
    assert len(s.gets) == 2


def test_auction_a_different_day_raises(env_file, sleeps):
    body = auction_body({"PDI": [day([pr("N", 18.5)], d="2026-09-28")]})
    c, _ = client(env_file, sleeps, route({"/v2/stocks/auctions": body}))
    with pytest.raises(al.UnexpectedResponse, match="not the requested"):
        c.closing_auction_prints(["PDI"], D, exchange_codes={"PDI": "N"})
