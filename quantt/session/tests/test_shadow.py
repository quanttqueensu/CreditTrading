"""shadow.py: the MODELLED intended-book score. Hermetic: fake prints, tmp state."""
import csv
import datetime as dt
import json

import pytest

from quantt.session import shadow as sh

D, P = dt.date(2026, 9, 30), dt.date(2026, 9, 29)
NOW = dt.datetime(2026, 9, 30, 21, 30, tzinfo=dt.timezone.utc)


def plan(state, day, targets, refusals=()):
    d = state / day.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(json.dumps({
        "session_date": day.isoformat(),
        "targets": {s: {"current": 0, "target": q, "kind": "weight", "reason": "t"}
                    for s, q in targets.items()},
        "refusals": [{"gate": g, "detail": "x"} for g in refusals]}))


def prices(table):
    def fetch(symbols, d):
        px = table.get(d, {})
        return ({s: px[s] for s in symbols if s in px},
                {s: "MissingAuctionPrint" for s in symbols if s not in px})
    return fetch


def rows(state):
    with (state / "shadow.csv").open() as fh:
        return list(csv.DictReader(fh))


def test_first_day_uses_the_previous_plans_intended_book(tmp_path):
    # 2026-09-29: 13 orders, paper filled 2 -- the shadow holds the whole intention
    plan(tmp_path, P, {"AAA": 100, "BBB": -50})
    fetch = prices({P: {"AAA": 10.0, "BBB": 20.0}, D: {"AAA": 10.5, "BBB": 19.0}})
    r = sh.run_day(None, tmp_path, D, fetch=fetch, prev=P, now_utc=NOW)
    assert r["shadow_pnl_usd"] == f"{100 * 0.5 + (-50) * (-1.0):.2f}"      # 100.00
    assert r["label"] == sh.LABEL and "not broker evidence" in r["label"]
    assert json.loads(r["book_in_json"]) == {"AAA": 100, "BBB": -50}


def test_book_advances_to_the_days_plan_and_carries_without_one(tmp_path):
    plan(tmp_path, P, {"AAA": 100})
    plan(tmp_path, D, {"AAA": 40, "CCC": 10})
    fetch = prices({P: {"AAA": 10.0}, D: {"AAA": 11.0}})
    r = sh.run_day(None, tmp_path, D, fetch=fetch, prev=P, now_utc=NOW)
    assert json.loads(r["book_out_json"]) == {"AAA": 40, "CCC": 10}
    nxt = dt.date(2026, 10, 1)
    fetch2 = prices({D: {"AAA": 11.0, "CCC": 5.0}, nxt: {"AAA": 12.0, "CCC": 5.5}})
    r2 = sh.run_day(None, tmp_path, nxt, fetch=fetch2, prev=D, now_utc=NOW)
    assert r2["shadow_pnl_usd"] == "45.00"                              # 40*1 + 10*0.5
    assert r2["book_out_source"].startswith("carried")                  # no plan on 10-01


def test_a_data_refused_plan_is_carried_but_a_dry_one_counts(tmp_path):
    assert sh.intended_book({"targets": {"A": {"target": 5}},
                             "refusals": [{"gate": "data"}]}) is None
    assert sh.intended_book({"targets": {"A": {"target": 5}},
                             "refusals": [{"gate": "dry_run"}, {"gate": "arming"}]}) == {"A": 5}
    assert sh.intended_book({"targets": {}, "refusals": []}) is None


def test_a_missing_print_makes_the_day_unmeasured_never_substituted(tmp_path):
    plan(tmp_path, P, {"AAA": 100, "BBB": -50})
    fetch = prices({P: {"AAA": 10.0, "BBB": 20.0}, D: {"AAA": 10.5}})
    r = sh.run_day(None, tmp_path, D, fetch=fetch, prev=P, now_utc=NOW)
    assert r["shadow_pnl_usd"] == "UNMEASURED" and "BBB" in r["unmeasured"]


def test_rerun_for_the_same_day_refuses_rather_than_advancing_twice(tmp_path):
    plan(tmp_path, P, {"AAA": 100})
    fetch = prices({P: {"AAA": 10.0}, D: {"AAA": 11.0}})
    sh.run_day(None, tmp_path, D, fetch=fetch, prev=P, now_utc=NOW)
    with pytest.raises(sh.ShadowError, match="already scored"):
        sh.run_day(None, tmp_path, D, fetch=fetch, prev=P, now_utc=NOW)
    assert len(rows(tmp_path)) == 1


def test_no_book_no_plan_scores_zero_with_nothing_fetched(tmp_path):
    called = []
    r = sh.run_day(None, tmp_path, D, fetch=lambda s, d: called.append(d) or ({}, {}),
                   prev=P, now_utc=NOW)
    assert r["shadow_pnl_usd"] == "0.00" and called == []


def test_a_foreign_header_refuses(tmp_path):
    (tmp_path / "shadow.csv").write_text("date,something_else\n")
    plan(tmp_path, P, {})
    with pytest.raises(sh.ShadowError, match="header"):
        sh.run_day(None, tmp_path, D, fetch=prices({}), prev=P, now_utc=NOW)


def test_record_error_leaves_a_row_saying_why(tmp_path):
    sh.record_error(tmp_path, D, P, "AlpacaHTTPError: boom", NOW)
    r = rows(tmp_path)[0]
    assert r["shadow_pnl_usd"] == "UNMEASURED" and "boom" in r["unmeasured"]


def test_a_shadow_failure_never_changes_the_verify_verdict(tmp_path, monkeypatch):
    from quantt.session import verify as vf
    monkeypatch.setenv("QUANTT_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(vf, "_make_client", lambda book: object())
    monkeypatch.setattr(vf, "verify_day", lambda *a, **k: vf.Verdict(
        date=D, book="cef", ok=True, reason="fine"))

    def boom(*a, **k):
        raise sh.ShadowError("no prints")
    monkeypatch.setattr(sh, "run_day", boom)
    assert vf.main(["verify", "--book", "cef"]) == 0            # PASS stays PASS
    r = rows(tmp_path)[0]
    assert r["date"] == D.isoformat() and "no prints" in r["unmeasured"]


def test_a_plan_refused_at_send_is_carried_not_intended(tmp_path):
    plan(tmp_path, P, {"AAA": 100})
    plan(tmp_path, D, {"AAA": 999})
    p = json.loads((tmp_path / D.isoformat() / "plan.json").read_text())
    p.update(execution="late_market", status="decided")
    (tmp_path / D.isoformat() / "plan.json").write_text(json.dumps(p))
    (tmp_path / D.isoformat() / "send.json").write_text(json.dumps(
        {"refusals": [{"gate": "halt", "detail": "manual"}], "exit": "REFUSED"}))
    r = sh.run_day(None, tmp_path, D, fetch=prices({P: {"AAA": 10.0}, D: {"AAA": 11.0}}),
                   prev=P, now_utc=NOW)
    assert json.loads(r["book_out_json"]) == {"AAA": 100} and r["book_out_source"].startswith("carried")
