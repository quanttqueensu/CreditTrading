"""tca.py: the daily execution row (execution-desk review 2026-10-07)."""
import csv
import datetime as dt
import json

import pytest

from quantt.session import tca
from quantt.session.tests import test_verify as tv
from quantt.session.tests.test_verify import state  # noqa: F401  (fixture)


def test_a_traded_day_writes_one_tca_row_with_fill_rate_and_signed_slippage(state):
    tv.started(state, [tv.rec("AAA", "sell", 50), tv.rec("CCC", "buy", 20)])
    v = tv.run(state, tv.traded_day())
    assert v.ok, v.reason
    rows = list(csv.DictReader((state / "tca.csv").open()))
    assert len(rows) == 1
    r = rows[0]
    assert r["n_orders"] == "2" and r["shares_ordered"] == "70" and r["shares_filled"] == "70"
    assert r["fill_rate_shares"] == "1.0000"
    # AAA sells: vwap (30*10.4 + 20*10.6)/50 = 10.48 vs A 10.5 -> (10.5-10.48)/10.5 = +19.05bp
    assert float(r["slip_bp_sell"]) == pytest.approx((10.5 - 10.48) / 10.5 * 1e4, abs=0.01)
    # CCC buy: (5.05 - 5.0)/5.0 = +100bp
    assert float(r["slip_bp_buy"]) == pytest.approx(100.0, abs=0.01)


def test_residual_is_positions_after_vs_plan_target_at_the_official_close():
    detail = {"orders": [], "positions_after": {"AAA": 90, "BBB": -50},
              "auction_prints_d": {"prices": {"AAA": 10.0, "BBB": 20.0}}}
    plan = {"targets": {"AAA": {"target": 100}, "BBB": {"target": -50}}}
    r = tca.tca_row("2026-09-29", "cef", detail, [], plan)
    assert r["residual_gross_usd"] == "100.00" and r["residual_net_usd"] == "-100.00"
    assert r["residual_names"] == "AAA:-10"


def test_a_foreign_header_refuses(tmp_path):
    (tmp_path / "tca.csv").write_text("date,other\n")
    with pytest.raises(ValueError, match="header"):
        tca.append(tmp_path / "tca.csv", {k: "" for k in tca.COLUMNS})
