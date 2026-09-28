"""The Alpaca probe can only read, reads only paper, and never leaks a key.

Each test pins one property the probe's docstring promises, because each is the
kind of promise that rots silently: a later edit adds a `session.post` "just to
test an order", or a debug print of the session, and nothing else would notice.
Hermetic throughout -- a fake session stands in for `requests`, and the root
conftest's netguard would fail any test that reached the network.
"""
import ast
import json
from pathlib import Path

import pytest

from quantt.broker import alpaca_probe as ap

SECRET = "sekrit-value-that-must-never-appear"
KEY_ID = "key-id-that-must-never-appear"


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Answers GETs from a table. Has NO post/delete/patch/put attribute, so any
    such call from the probe fails with AttributeError."""

    def __init__(self, table):
        self.table = table
        self.urls = []
        self.headers = {"APCA-API-KEY-ID": KEY_ID, "APCA-API-SECRET-KEY": SECRET}

    def get(self, url, timeout):
        self.urls.append(url)
        path = url[len(ap.PAPER_BASE):]
        status, payload = self.table.get(path, (404, {"message": "not found"}))
        return FakeResp(status, payload)


def _table(universe, missing=()):
    t = {
        "/v2/account": (200, {"status": "ACTIVE", "currency": "USD", "equity": "100000"}),
        "/v2/account/configurations": (200, {"no_shorting": False}),
        "/v2/positions": (200, []),
        "/v2/orders?status=open&limit=500": (200, []),
    }
    for s in universe:
        if s not in missing:
            t[f"/v2/assets/{s}"] = (200, {"symbol": s, "tradable": True,
                                          "shortable": True, "borrow_status": "easy_to_borrow"})
    return t


def test_the_module_contains_no_verb_but_get():
    """No attribute access to post/put/patch/delete/request anywhere in the source."""
    tree = ast.parse(Path(ap.__file__).read_text())
    verbs = {"post", "put", "patch", "delete", "request", "submit_order", "cancel_order"}
    hits = [n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in verbs]
    assert hits == [], f"write-capable calls found in the probe: {hits}"


def test_every_request_goes_to_the_paper_endpoint(monkeypatch):
    monkeypatch.setattr(ap, "universe", lambda b: ["PDI", "PTY"])
    s = FakeSession(_table(["PDI", "PTY"]))
    ap.probe_book("cef", s)
    assert s.urls and all(u.startswith("https://paper-api.alpaca.markets/v2/") for u in s.urls)


def test_a_non_paper_url_is_refused():
    with pytest.raises(ValueError, match="non-paper"):
        ap._get(FakeSession({}), "@api.alpaca.markets/v2/account")


def test_a_missing_key_names_the_variable_and_substitutes_nothing():
    env = {"ALPACA_CEF_KEY_ID": KEY_ID, "ALPACA_CEF_SECRET_KEY": SECRET}
    with pytest.raises(ap.MissingCredential) as e:
        ap.load_credentials("b6", env)          # b6 unset; cef's keys must NOT be used
    msg = str(e.value)
    assert "ALPACA_B6_KEY_ID" in msg and "ALPACA_B6_SECRET_KEY" in msg
    assert SECRET not in msg and KEY_ID not in msg


def test_an_asset_alpaca_does_not_list_is_recorded_not_raised_or_invented(monkeypatch):
    monkeypatch.setattr(ap, "universe", lambda b: ["PDI", "ZZZZ"])
    snap = ap.probe_book("cef", FakeSession(_table(["PDI", "ZZZZ"], missing={"ZZZZ"})))
    assert snap["assets"]["ZZZZ"] == {"_probe": "NOT FOUND AT ALPACA (404)"}
    assert "NOT FOUND AT ALPACA" in ap.summarise(snap)


def test_a_field_alpaca_did_not_send_shows_as_absent_not_a_default(monkeypatch):
    monkeypatch.setattr(ap, "universe", lambda b: ["PDI"])
    snap = ap.probe_book("cef", FakeSession(_table(["PDI"])))
    row = [l for l in ap.summarise(snap).splitlines() if l.startswith("PDI")][0]
    assert "ABSENT" in row          # e.g. margin fields the fake did not send
    assert "False" not in row       # nothing was defaulted to a boolean


def test_any_other_http_error_raises_with_the_path(monkeypatch):
    monkeypatch.setattr(ap, "universe", lambda b: [])
    t = _table([])
    t["/v2/account"] = (401, {"message": "unauthorized"})
    with pytest.raises(RuntimeError, match=r"GET /v2/account -> HTTP 401"):
        ap.probe_book("cef", FakeSession(t))


def test_neither_key_reaches_the_snapshot_or_the_summary(monkeypatch):
    monkeypatch.setattr(ap, "universe", lambda b: ["PDI"])
    snap = ap.probe_book("cef", FakeSession(_table(["PDI"])))
    blob = json.dumps(snap) + ap.summarise(snap)
    assert SECRET not in blob and KEY_ID not in blob


def test_the_books_are_exactly_the_two_the_team_lead_kept():
    assert set(ap.BOOK_SPECS) == {"cef", "b6"}
    assert all(p.exists() for p in ap.BOOK_SPECS.values())


def test_the_cef_universe_comes_from_the_frozen_spec():
    spec = json.loads(ap.BOOK_SPECS["cef"].read_text())
    assert ap.universe("cef") == list(spec["frozen"]["universe"])
