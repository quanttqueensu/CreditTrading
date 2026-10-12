"""The parts of plan item 0.5's script that can be wrong silently, on synthetic input.

WHY THESE. The figures depend on panels and account records that are not in the
repository. What can rot unnoticed is: reading the same fill twice from two
copies of the records (the laptop's and the VM's state both hold 2026-10-07),
counting a fill from another day because a folder holds a late snapshot,
mis-parsing the slippage verify recorded, mis-stating the regulatory fee, and
scoring a MEASURED borrow proxy on a window where it has no data. Each test is
a statement about the code, never about the market (CLAUDE.md data rules).
"""
from __future__ import annotations

import json

import pytest

from scripts.cef import real_money_costs as rmc


def _fill(fid, day, sym="AAA", side="buy", qty="10", price="9.99"):
    return {"id": fid, "order_id": "o-" + fid, "symbol": sym, "side": side, "qty": qty,
            "price": price, "transaction_time": f"{day}T19:52:03.000000Z"}


def _state(root, day, fills, verdict=None, execution="late_market", account_fills=None):
    d = root / day
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"execution": execution}))
    rec = {"fills": fills}
    if verdict:
        rec["verdict"] = verdict
    (d / "reconcile.json").write_text(json.dumps(rec))
    if account_fills is not None:
        a = root / "data" / day
        a.mkdir(parents=True)
        (a / "account.json").write_text(json.dumps({"date": day, "fills": account_fills}))


def test_records_are_deduplicated_across_copies_and_sources(tmp_path):
    lap, vm = tmp_path / "lap", tmp_path / "vm"
    f1, f2 = _fill("1", "2026-10-07"), _fill("2", "2026-10-07", side="sell_short")
    _state(lap, "2026-10-07", [f1, f2], account_fills=[f1, f2])
    _state(vm, "2026-10-07", [f1, f2])
    F, modes, _ = rmc.read_records([lap, vm])
    assert len(F) == 2, "one fill read from three places must count once"
    assert modes["2026-10-07"] == "late_market"


def test_a_fill_from_another_day_is_not_counted(tmp_path):
    st = tmp_path / "s"
    _state(st, "2026-10-08", [_fill("1", "2026-10-08"), _fill("9", "2026-10-07")])
    F, _, _ = rmc.read_records([st])
    assert list(F.fill_id) == ["1"]


def test_verify_slippage_is_parsed_with_its_sign(tmp_path):
    st = tmp_path / "s"
    _state(st, "2026-10-08", [_fill("1", "2026-10-08")],
           verdict="2026-10-08 PASS cef traded 8 order(s); fill vs auction +15.8bp (+ = worse)")
    _state(st, "2026-10-09", [_fill("2", "2026-10-09")],
           verdict="2026-10-09 PASS cef traded; fill vs auction -17.9bp (+ = worse)")
    _, _, rec = rmc.read_records([st])
    assert rec == {"2026-10-08": 15.8, "2026-10-09": -17.9}


def test_a_plan_without_the_paper_exception_is_cls(tmp_path):
    st = tmp_path / "s"
    _state(st, "2026-09-29", [_fill("1", "2026-09-29")], execution=None)
    _, modes, _ = rmc.read_records([st])
    assert modes["2026-09-29"] == "cls"


def test_no_records_raises(tmp_path):
    with pytest.raises(ValueError, match="no fills"):
        rmc.read_records([tmp_path])


def test_regulatory_fee_arithmetic():
    # SEC fee on half the turnover, CAT on every share at $10: 0.103 + 0.003 bp
    bp = rmc.reg_fee_bp(0.5, 10.0)
    assert bp == pytest.approx(0.5 * 0.0000206 * 1e4 + 0.000003 / 10.0 * 1e4)
    assert rmc.reg_fee_bp(0.0, 10.0) == pytest.approx(0.003)


def test_measured_proxies_are_scored_only_on_their_window():
    assert rmc.in_domain("P0", "measured-borrow window")
    assert not rmc.in_domain("P0", "live fit 2013-06..2022")
    assert not rmc.in_domain("P0+", "2015-19")
    assert rmc.in_domain("P3", "2015-19")
