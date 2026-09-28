"""Reversing a fill the broker never executed must move exactly what it should.

Pinned against the 2026-09-10 null_trader incident. The five phantoms and their
modelled prices are the real ones; a failure here reads as that incident.

THE INVARIANT WORTH KNOWING: a fill booked at `close ± slippage` that never
happened costs the book exactly its own `cost_usd`. So reversing it must move NAV
by `+cost_usd` and nothing else — which is why the tool asserts cash agreement
between nav.csv and positions.csv rather than trusting its own arithmetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.ledger import Ledger  # noqa: E402
from ops.unbook_unexecuted_fills import unbook  # noqa: E402

D = "2026-09-10"


def _book(tmp_path, booked, executed):
    """A one-day ledger with `booked` trades and `executed` broker rows."""
    state = tmp_path / "_ibkr_shadow" / "null_trader"
    state.mkdir(parents=True)
    trades, orders, pos = [], [], []
    cash, invested = 1_000_000.0, 0.0
    for tkr, side, sh, price, close in booked:
        signed = sh if side == "BUY" else -sh
        trades.append({
            "fill_date": D, "decision_date": "2026-09-09", "ticker": tkr,
            "side": side, "shares": sh, "decision_price": close,
            "close_price": close, "fill_price": price, "half_spread_bp": 1.0,
            "impact_bp": 0.0, "slip_vs_decision_bp": 0.0,
            "participation_pct": 0.1, "over_participation_cap": False,
            "notional_usd": signed * price, "cost_usd": abs(sh) * abs(price - close),
            "reason": "target", "modelled_fill_price": price, "exec_ids": ""})
        orders.append({"decision_date": "2026-09-09", "ticker": tkr,
                       "current_shares": 0.0, "target_shares": signed,
                       "delta_shares": signed, "decision_price": close,
                       "target_weight": None, "reason": "target",
                       "status": "filled", "fill_date": D})
        cash -= signed * price
        invested += signed * close
        pos.append({"date": D, "ticker": tkr, "shares": signed, "close": close,
                    "market_value": signed * close, "weight": 0.0})
    pos.append({"date": D, "ticker": "CASH", "shares": None, "close": None,
                "market_value": cash, "weight": 0.0})
    pd.DataFrame(trades).to_csv(state / "trades.csv", index=False)
    pd.DataFrame(orders).to_csv(state / "orders.csv", index=False)
    pd.DataFrame(pos).to_csv(state / "positions.csv", index=False)
    pd.DataFrame([
        {"date": "2026-09-09", "nav": 1_000_000.0, "cash": 1_000_000.0,
         "invested": 0.0, "distributions_usd": 0.0, "cost_usd": 0.0,
         "traded_usd": 0.0, "daily_return": 0.0, "decision": "target"},
        {"date": D, "nav": cash + invested, "cash": cash, "invested": invested,
         "distributions_usd": 0.0,
         "cost_usd": sum(t["cost_usd"] for t in trades),
         "traded_usd": sum(abs(t["notional_usd"]) for t in trades),
         "daily_return": 0.0, "decision": "target"},
    ]).to_csv(state / "nav.csv", index=False)
    pd.DataFrame(
        [{"recorded_utc": "x", "fill_date": D, "instrument": t, "side": "BUY",
          "qty": 1.0, "price": 1.0, "source": "ibkr_paper",
          "note": f"execId=ex-{t} orderRef='' commission=0.0"}
         for t in executed],
        # explicit columns so a book with NO executions still writes a header;
        # an empty frame writes an empty file, which read_csv cannot parse and
        # which would be indistinguishable from a corrupt one
        columns=["recorded_utc", "fill_date", "instrument", "side", "qty",
                 "price", "source", "note"],
    ).to_csv(state / "broker_fills.csv", index=False)
    return tmp_path


# the real 2026-09-10 rows: (ticker, side, shares, modelled fill, close)
PHANTOMS = [("JAAA", "SELL", 1503.0, 50.56819647621368, 50.580101013183594),
            ("LQD", "BUY", 861.0, 104.72896253001771, 104.70999908447266)]
REAL = [("SRLN", "SELL", 3918.0, 40.49682843763729, 40.51499938964844)]


def test_reverses_only_the_unexecuted(tmp_path):
    root = _book(tmp_path, PHANTOMS + REAL, executed=["SRLN"])
    rep = unbook(root, "null_trader", D, apply=True, verbose=False)

    assert {r["ticker"] for r in rep["reversed"]} == {"JAAA", "LQD"}
    lg = Ledger(state_dir=root / "_ibkr_shadow" / "null_trader")
    assert set(lg.trades["ticker"]) == {"SRLN"}, "the executed fill must survive"
    reopened = lg.orders[lg.orders["ticker"].isin(["JAAA", "LQD"])]
    assert set(reopened["status"]) == {"skipped"}
    assert reopened["fill_date"].isna().all()
    assert (lg.orders.loc[lg.orders["ticker"] == "SRLN", "status"] == "filled").all()


def test_nav_moves_by_exactly_the_reversed_cost(tmp_path):
    """The invariant. A fill that never happened cost the book its own cost_usd."""
    root = _book(tmp_path, PHANTOMS + REAL, executed=["SRLN"])
    before = pd.read_csv(root / "_ibkr_shadow/null_trader/nav.csv")
    nav0 = float(before[before.date == D].nav.iloc[0])
    reversed_cost = sum(
        abs(sh) * abs(px - cl) for _, _, sh, px, cl in PHANTOMS)

    rep = unbook(root, "null_trader", D, apply=True, verbose=False)
    assert rep["nav_after"] - nav0 == pytest.approx(reversed_cost, rel=1e-9)

    nav = pd.read_csv(root / "_ibkr_shadow/null_trader/nav.csv")
    row = nav[nav.date == D].iloc[0]
    assert row.cash + row.invested == pytest.approx(row.nav)


def test_zeroed_position_gets_no_row(tmp_path):
    """`advance` pops a flat key, so a reversal that flattens must too."""
    root = _book(tmp_path, PHANTOMS, executed=[])
    unbook(root, "null_trader", D, apply=True, verbose=False)
    pos = pd.read_csv(root / "_ibkr_shadow/null_trader/positions.csv")
    assert "JAAA" not in set(pos[pos.date == D].ticker)
    assert "LQD" not in set(pos[pos.date == D].ticker)


def test_nothing_to_do_when_every_fill_executed(tmp_path):
    root = _book(tmp_path, REAL, executed=["SRLN"])
    rep = unbook(root, "null_trader", D, apply=True, verbose=False)
    assert rep["reversed"] == []


def test_refuses_a_date_that_is_not_the_last(tmp_path):
    root = _book(tmp_path, PHANTOMS, executed=[])
    with pytest.raises(ValueError, match="LAST date"):
        unbook(root, "null_trader", "2026-09-09", apply=False, verbose=False)


def test_missing_broker_fills_raises(tmp_path):
    """Absent record and empty record license opposite actions."""
    root = _book(tmp_path, PHANTOMS, executed=[])
    (root / "_ibkr_shadow/null_trader/broker_fills.csv").unlink()
    with pytest.raises(FileNotFoundError, match="capture_fills"):
        unbook(root, "null_trader", D, apply=False, verbose=False)


def test_a_row_without_an_execid_does_not_count_as_executed(tmp_path):
    """The claim is 'the broker reports an EXECUTION', not 'a row exists'."""
    root = _book(tmp_path, PHANTOMS, executed=[])
    bf = root / "_ibkr_shadow/null_trader/broker_fills.csv"
    pd.DataFrame([{"recorded_utc": "x", "fill_date": D, "instrument": "LQD",
                   "side": "BUY", "qty": 861.0, "price": 104.7,
                   "source": "manual", "note": "hand-entered, no execId"}
                  ]).to_csv(bf, index=False)
    rep = unbook(root, "null_trader", D, apply=False, verbose=False)
    assert "LQD" in {r["ticker"] for r in rep["reversed"]}
