"""The twin's verify, compare and ledger view, after a send on the 2026-11-27 early close."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from quantt.session import records as rec
from quantt.twin import compare, ledger_view, run, verify
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_send import PRINTS, S, armed, world_and_books

FILLS = {"PDI": 20.01, "NAD": 11.99, "IWM": 229.9, "OLD": 5.0, "MHD": 11.02}


def sent_and_filled(tmp_path, **kw):
    st, w, mk, d, out = world_and_books(tmp_path, **kw)
    armed(st)
    assert run.send(d) == 0, out.getvalue()
    w.fill_all_at(FILLS, F.et(2026, 11, 27, 12, 59, 50))
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    return st, w, mk, d, out


def alpaca_record(st, book, fills, orders):
    """A book's own verify record for the same session (core/C4 reconcile.json, events verify.json)."""
    day = rec.day_dir(st[book], S)
    name = "verify.json" if book == "events" else "reconcile.json"
    rec.write_json_atomic(day / name, {"orders": orders, "fills": [
        {"id": f"f{i}", "symbol": s, "side": side, "qty": str(q), "price": str(p), "order_id": f"o{i}"}
        for i, (s, side, q, p) in enumerate(fills)]})


def test_verify_books_reconciles_and_scores_after_an_early_close(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path, legacy={"OLD": 10})
    alpaca_record(st, "cef", [("PDI", "buy", 20, 20.05), ("NAD", "sell", 50, 11.95)],
                  [{"qty": 20, "filled_qty": "20"}, {"qty": 50, "filled_qty": "50"}])
    assert verify.verify(d) == 0, out.getvalue()
    v = json.loads((st["twin"] / "2026-11-27" / "verify.json").read_text())
    assert v["ledger_applied"] and v["ok"]
    view = ledger_view(st["twin"])
    assert view["cef"]["shares"] == {"NAD": -50, "PDI": 100}
    assert view["c4"]["shares"] == {"MHD": 30, "NAD": 20}
    assert view["events/specdiv_wait"]["shares"] == {"IWM": -10, "PDI": 5}
    assert view["legacy"]["shares"] == {}
    tot = {}
    for r in view.values():
        for s, q in r["shares"].items():
            tot[s] = tot.get(s, 0) + q
    assert {s: q for s, q in tot.items() if q} == w.positions
    # crossed NAD shares (C4's +20 against the core's -50) are counted apart, never scored
    assert v["scores"]["c4"]["crossed_shares"] == 20 and v["scores"]["cef"]["crossed_shares"] == 20
    # the Alpaca book is scored against the same official close
    a = v["alpaca"]["cef"]
    want = (20 * 20.0 * (20.05 - 20.0) / 20.0 * 1e4 + 50 * 12.0 * (12.0 - 11.95) / 12.0 * 1e4) / (20 * 20.0 + 50 * 12.0)
    assert a["full"] == 2 and abs(a["bp"] - want) < 1e-9


def test_compare_prints_the_table_after_one_session_with_no_standard_error(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path)
    alpaca_record(st, "cef", [("PDI", "buy", 20, 20.05)], [{"qty": 20, "filled_qty": "20"}])
    assert verify.verify(d) == 0
    txt = compare.render(st["twin"], aggregates=False)
    assert "2026-11-27 cef" in txt and "SE none (fewer than two sessions)" in txt
    assert "double sends 0" in txt and "reconciled 1/1" in txt
    agg = compare.render(st["twin"], aggregates=True)
    assert "2026-11-27 cef" not in agg and "TALLY" in agg
    assert "events/specdiv_wait" in agg                       # the per-sleeve line
    t = compare.tally(compare.read_rows(st["twin"]))["cef"]
    assert t["both_traded"] == 1 and t["paired_sessions"] == 1 and t["paired_diff_se_bp"] is None


def test_a_foreign_execution_fails_the_day_and_books_nothing(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path)
    import types
    w.executions.append(types.SimpleNamespace(
        execution=types.SimpleNamespace(execId="X1", side="BOT", shares=1.0, price=5.0, permId=424242, orderId=1,
                                        clientId=0, orderRef="", acctNumber=F.ACCOUNT, time=None),
        contract=types.SimpleNamespace(symbol="ZZZ", localSymbol="ZZZ", secType="STK", currency="USD"),
        commissionReport=None, time=None))
    w.positions["ZZZ"] = 1
    before = (st["twin"] / "ledger.json").read_text()
    assert verify.verify(d) == 1
    assert "FOREIGN" in out.getvalue()
    assert (st["twin"] / "ledger.json").read_text() == before


def test_verify_must_run_on_the_session_day(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path)
    mk.now = F.et(2026, 11, 30, 9, 0)
    assert verify.verify(d, date=S) == run.EXIT_REFUSED
    assert "current day's executions only" in out.getvalue()


def test_verify_before_the_close_is_refused(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path)
    mk.now = F.et(2026, 11, 27, 12, 55)
    assert verify.verify(d) == run.EXIT_REFUSED


def test_verify_is_idempotent(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path)
    assert verify.verify(d) == 0
    led = (st["twin"] / "ledger.json").read_text()
    assert verify.verify(d) == 0
    assert (st["twin"] / "ledger.json").read_text() == led
    assert len(compare.read_rows(st["twin"])) == 3


def test_a_dry_day_books_nothing_and_says_why(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, dry_run="1")
    assert run.send(d) == run.EXIT_DRY
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 0
    assert "not sent by choice" in (st["twin"] / "verify.log").read_text()
    assert compare.tally(compare.read_rows(st["twin"]))["cef"]["both_traded"] == 0


def test_a_missed_session_fails_verify(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.reachable = False
    assert run.send(d) == run.EXIT_REFUSED
    w.reachable = True
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1
    assert "MISSED" in (st["twin"] / "verify.log").read_text()


def test_status_carries_aggregates_only(tmp_path):
    st, w, mk, d, out = sent_and_filled(tmp_path)
    assert verify.verify(d) == 0
    s = (st["twin"] / "status.json").read_text()
    assert F.ACCOUNT not in s
    for sym in PRINTS:
        assert f'"{sym}"' not in s, f"{sym} crossed into status.json"
    d_ = json.loads(s)
    assert d_["gateway"]["logged_in"] is True and d_["last_verify"]["ok"] is True and "cef" in d_["tally"]


def test_ledger_view_raises_naming_what_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="ledger.json"):
        ledger_view(tmp_path)
    (tmp_path / "ledger.json").write_text(json.dumps({"version": 2}))
    with pytest.raises(Exception, match="version-1"):
        ledger_view(tmp_path)
