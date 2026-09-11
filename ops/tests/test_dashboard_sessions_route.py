"""`/api/sessions` must render, must never 500, and must not add an order path.

WHY THIS FILE IS IN ops/tests AND NOT dashboard/tests
-----------------------------------------------------
`pytest.ini` scopes collection deliberately and says, in its own comment, not to
widen `testpaths` — because one file matching the default discovery pattern
(`scripts/audit/moc_routing_test.py`) opens a live broker socket AT IMPORT and
transmits an order to the closing auction. Adding a directory to `testpaths` to
hold two tests is not worth reopening that. `ops/tests/` already holds the tests
for `ops/promote.sh`, which is not a Python module either.

WHAT IS BEING PROTECTED
-----------------------
Two things, and the first one is the repo's hardest invariant:

1. **The dashboard is read-only.** Exactly one non-GET route exists,
   `POST /api/connect`, which starts IB Gateway and nothing else. Until now that
   was asserted only in prose, in four documents. It is now asserted against
   Flask's own URL map, which is the thing that is actually true at runtime — a
   grep for `@app.post` would miss `@app.route(..., methods=[...])`, and that is
   exactly how a second mutating route would arrive: not deliberately.

2. **A panel must degrade, not disappear.** The underlying-file-missing case is
   the one that will actually happen: the prod worktree can be absent, the log
   directory can be empty, `session_uptime` can raise on a log shape nobody has
   seen. Every one of those must come back as a 200 with a reason the page can
   render, because a 500 takes the tab down — and the tab it takes down is the
   one that tells the operator the book is not trading.

Nothing here starts a server, binds a port, or opens a socket. Flask's test
client dispatches in-process.
"""
from __future__ import annotations

import json

import pytest

from dashboard import server as srv


@pytest.fixture
def client():
    srv.app.config.update(TESTING=True)
    # The route is cached for 120s; a stale entry from another test would make
    # these assertions pass for the wrong reason.
    srv._cache.pop("sessions", None)
    c = srv.app.test_client()
    yield c
    srv._cache.pop("sessions", None)


# ----------------------------------------------------------- the invariant ---
def test_exactly_one_mutating_route_and_it_is_api_connect():
    mutating = {str(r.rule): sorted(r.methods - {"GET", "HEAD", "OPTIONS"})
                for r in srv.app.url_map.iter_rules()
                if r.methods - {"GET", "HEAD", "OPTIONS"}}
    assert mutating == {"/api/connect": ["POST"]}, (
        "The dashboard is read-only by design: exactly one non-GET route. "
        f"Found {mutating}. A new mutating route is a decision for the team "
        "lead, not a refactor.")


def test_the_sessions_route_accepts_nothing_but_get(client):
    assert client.get("/api/sessions").status_code == 200
    for verb in ("post", "put", "patch", "delete"):
        assert getattr(client, verb)("/api/sessions").status_code == 405


# ------------------------------------------------------------- the payload ---
def test_the_route_returns_the_measurement_and_names_both_trees(client):
    r = client.get("/api/sessions")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True, d.get("reason")
    # Both trees named, whether or not each is present. Reading one undercounts.
    assert len(d["trees"]) == 2
    assert d["n_armed"] + d["n_missed"] == d["n_eligible"]
    assert d["n_clean"] <= d["n_armed"]
    assert d["reproducer"].startswith("python3 -m ops.session_uptime")
    assert d["target_definition"]
    for s in d["sessions"]:
        assert s["outcome"] in ("armed", "blocked", "no_log", "indeterminate")
        if s["outcome"] != "armed":
            assert s["reason"], f"{s['date']} reported with no reason"


def test_the_payload_carries_no_nan_token(client):
    """Python's json emits a bare NaN that a browser's JSON.parse rejects
    outright, and Flask's jsonify produces it silently. One NaN anywhere blanks
    the whole page, which has happened before."""
    raw = client.get("/api/sessions").get_data(as_text=True)
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw)           # what the browser does, and the real assertion


def test_today_is_reported_separately_from_the_rate(client):
    """"Has tonight's session armed?" is not answerable from a window that ends
    yesterday, and an absent log today is not a miss — the job has not run."""
    t = client.get("/api/sessions").get_json()["today"]
    assert t["state"] in ("armed", "blocked", "no_log", "indeterminate",
                          "not_yet", "closed")
    assert t["note"]


# ------------------------------------------------- degrade, never disappear ---
def test_a_crash_in_the_measurement_is_a_reason_not_a_500(client, monkeypatch):
    from ops import session_uptime as su

    def boom(*a, **k):
        raise RuntimeError("log shape nobody has seen")
    monkeypatch.setattr(su, "measure", boom)
    r = client.get("/api/sessions")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is False
    assert "log shape nobody has seen" in d["reason"]


def test_no_logs_anywhere_says_so_rather_than_printing_zero_percent(
        client, monkeypatch, tmp_path):
    """The case that will actually happen: a fresh machine, or a promotion that
    moved the tree. `0 of 0` and `0 of 29` look alike in a headline."""
    from ops import session_uptime as su
    empty = tmp_path / "empty"
    (empty / su.LOG_SUBDIR).mkdir(parents=True)
    monkeypatch.setattr(su, "REPO", empty)
    monkeypatch.setattr(su, "PROD_TREE", tmp_path / "gone")
    d = client.get("/api/sessions").get_json()
    assert d["ok"] is False
    assert "no cef_*.log" in d["reason"]


def test_a_missing_prod_tree_makes_the_rate_incomplete_not_smaller(
        client, monkeypatch, tmp_path):
    """The bifurcation defect, through the route. An undercounted denominator
    flatters the rate; the panel has to say the number is a lower bound."""
    from ops import session_uptime as su
    monkeypatch.setattr(su, "PROD_TREE", tmp_path / "no-prod-here")
    d = client.get("/api/sessions").get_json()
    assert d["ok"] is True
    assert d["complete"] is False
    assert any("no-prod-here" in r for r in d["incomplete_reasons"])
    assert [t["present"] for t in d["trees"]] == [True, False]
