"""The ledger books what the BROKER executed, not what the sleeve intended.

WHY THIS FILE EXISTS
--------------------
On 2026-09-10 `null_trader` closed fourteen orders as `filled`. Five of them —
EMB +57, HYG +605, JAAA -1503, JNK +420, LQD +861 — had ZERO executions at the
broker and nothing resting, and the other nine each disagreed with the broker by
1 to 5 shares. The day's nav.csv row charged cost_usd $291.68 and traded_usd
$941,272 against that. The invented 1,503-share JAAA short is what
`ops/HALT_phase0_null.md` exists for.

The cause was one argument: `IBKRBroker.place_targets` handed the shadow ledger
the sleeve's TARGETS and never its fills, so `Ledger.advance` filled every
pending order at the next close by construction and could not tell a rejected
order from an executed one.

Every share count below is from that incident. A failure here reads as the
incident it is, not as an abstract assertion about a round number.

NO BROKER, NO NETWORK, NO LIVE LEDGERS. Everything runs against `tmp_path` and a
hand-built `ExecutionRecord`. Nothing here touches `ops/books/*_live/`, which
holds the only record of real fills this desk has.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.ledger import (Execution, ExecutionRecord, ExecutionRecordGap,  # noqa: E402
                        Ledger, NoCommissionReport, TRADE_COLUMNS)

D = pd.Timestamp("2026-09-10")


# -- fixtures -------------------------------------------------------------

def _costs(ticker, half_spread_bp=1.0):
    return {"tickers": {ticker: {"half_spread_bp": half_spread_bp}},
            "slippage_extra_bp": 0.0, "impact_coefficient": 0.5,
            "max_participation_pct": 100.0, "commission_usd_per_trade": 1.0}


def _order(ticker, delta, decision_price):
    return {"decision_date": pd.Timestamp("2026-09-09"), "ticker": ticker,
            "current_shares": 0.0, "target_shares": float(delta),
            "delta_shares": float(delta), "decision_price": decision_price,
            "target_weight": np.nan, "reason": "target", "status": "open",
            "fill_date": pd.NaT}


def _frames(ticker, close, volume=5_000_000.0):
    idx = pd.DatetimeIndex([D])
    return (pd.Series({ticker: close}),
            pd.DataFrame({ticker: [volume]}, index=idx),
            pd.DataFrame({ticker: [80.0]}, index=idx))


def _ledger(tmp_path, record=None):
    lg = Ledger(state_dir=tmp_path / "book")
    lg.execution_record = record
    return lg


def _record(*executions, covers=(D,), source="test"):
    rec = ExecutionRecord(source=source, covers=covers)
    for e in executions:
        rec.add(e, date=D)
    return rec


# -- 1. the incident: an order the broker never executed -------------------

@pytest.mark.parametrize("ticker,delta,price", [
    ("JAAA", -1503.0, 50.59),          # the phantom short HALT_phase0_null.md exists for
    ("LQD", 861.0, 105.31),
    ("HYG", 605.0, 78.98),
    ("JNK", 420.0, 95.04),
    ("EMB", 57.0, 94.17),
])
def test_no_execution_books_nothing(tmp_path, ticker, delta, price, capsys):
    """The five 2026-09-10 phantoms. No execution -> no fill, and it says so."""
    close, vol, vol_bp = _frames(ticker, price)
    lg = _ledger(tmp_path, _record())          # broker executed nothing at all
    fill = lg._broker_fill(_order(ticker, delta, price), D, close, vol, vol_bp,
                           _costs(ticker), cash=1e9)
    assert fill is None, (
        f"{ticker} {delta:+.0f} had no execution at the broker; booking any "
        f"fill for it is the 2026-09-10 phantom")
    out = capsys.readouterr().out
    assert "NO EXECUTION" in out and ticker in out, (
        "a phantom must be visible in the session log, not only in the CSV")


# -- 2. the quantity is the broker's, not the order's ----------------------

def test_books_executed_quantity_not_intended(tmp_path):
    """BKLN 2026-09-10: ordered +2,905, broker executed +2,904."""
    close, vol, vol_bp = _frames("BKLN", 20.59)
    rec = _record(Execution("BKLN", "BUY", 2904.0, 20.60, 1.20, "ex-bkln-1"))
    lg = _ledger(tmp_path, rec)
    fill = lg._broker_fill(_order("BKLN", 2905.0, 20.59), D, close, vol, vol_bp,
                           _costs("BKLN"), cash=1e9)
    assert fill["shares"] == 2904.0
    assert fill["row"]["shares"] == 2904.0
    assert fill["row"]["exec_ids"] == "ex-bkln-1"


def test_partial_fill_across_several_executions(tmp_path):
    """A real order fills in pieces; the row is their VWAP and every execId."""
    close, vol, vol_bp = _frames("SRLN", 40.515)
    rec = _record(
        Execution("SRLN", "SLD", 2000.0, 40.50, 2.00, "ex-a"),
        Execution("SRLN", "SLD", 1918.0, 40.49, 1.92, "ex-b"))
    lg = _ledger(tmp_path, rec)
    fill = lg._broker_fill(_order("SRLN", -3920.0, 40.52), D, close, vol, vol_bp,
                           _costs("SRLN"), cash=1e9)
    assert fill["shares"] == -3918.0
    expected_vwap = (40.50 * 2000 + 40.49 * 1918) / 3918
    assert fill["fill_price"] == pytest.approx(expected_vwap)
    assert fill["row"]["side"] == "SELL"
    assert set(fill["row"]["exec_ids"].split(";")) == {"ex-a", "ex-b"}
    assert fill["commission_usd"] == pytest.approx(3.92)


# -- 3. the price is the broker's, and the model is kept beside it ---------

def test_fill_price_is_real_and_modelled_is_kept(tmp_path):
    """The team lead's 2026-09-10 decision: real price drives P&L.

    `modelled_fill_price` must still be written and must still be the
    COUNTERFACTUAL, because `capture_fills.slippage_report` measures realised
    against it. If it ever equals `fill_price` on a real row, kill rule (b)
    reports 1.00x forever and can never trip.
    """
    close, vol, vol_bp = _frames("LQD", 104.71)
    rec = _record(Execution("LQD", "BUY", 861.0, 104.85, 1.00, "ex-lqd"))
    lg = _ledger(tmp_path, rec)
    row = lg._broker_fill(_order("LQD", 861.0, 105.31), D, close, vol, vol_bp,
                          _costs("LQD"), cash=1e9)["row"]

    assert row["fill_price"] == 104.85, "P&L must use the broker's own price"
    assert row["modelled_fill_price"] != row["fill_price"], (
        "the modelled price must stay a counterfactual — kill rule (b)'s "
        "denominator dies the moment these two are equal by construction")
    # the model charges a half-spread above the close on a buy
    assert row["modelled_fill_price"] > row["close_price"]
    # realised total goes in half_spread_bp; a real fill does not decompose
    assert row["half_spread_bp"] == pytest.approx(
        (104.85 / 104.71 - 1.0) * 1e4)
    assert np.isnan(row["impact_bp"]), (
        "impact is not observable in a real fill; 0.0 would claim there was none")


def test_row_matches_the_trade_schema(tmp_path):
    close, vol, vol_bp = _frames("HYG", 78.74)
    rec = _record(Execution("HYG", "BUY", 605.0, 78.75, 0.60, "ex-hyg"))
    lg = _ledger(tmp_path, rec)
    row = lg._broker_fill(_order("HYG", 605.0, 78.98), D, close, vol, vol_bp,
                          _costs("HYG"), cash=1e9)["row"]
    assert set(row) == set(TRADE_COLUMNS)


# -- 4. what it refuses to guess ------------------------------------------

def test_uncovered_date_raises_rather_than_skipping(tmp_path):
    """A ledger behind the account cannot be caught up from ib.fills().

    Booking `skipped` here would assert that nothing traded that day, which we
    do not know; booking a simulated fill rebuilds the original fault.
    """
    close, vol, vol_bp = _frames("NEA", 10.96)
    rec = _record(covers=(pd.Timestamp("2026-09-11"),))
    lg = _ledger(tmp_path, rec)
    with pytest.raises(ExecutionRecordGap) as e:
        lg._broker_fill(_order("NEA", -4565.0, 10.96), D, close, vol, vol_bp,
                        _costs("NEA"), cash=1e9)
    assert "rebuild_ledger" in str(e.value)


def test_missing_commission_raises(tmp_path):
    """No invented cost. `commission_usd_per_trade` is a config guess and must
    never be charged against a real trade and reported as realised."""
    close, vol, vol_bp = _frames("PDI", 15.27)
    rec = _record(Execution("PDI", "BUY", 100.0, 15.30, None, "ex-pdi"))
    lg = _ledger(tmp_path, rec)
    with pytest.raises(NoCommissionReport) as e:
        lg._broker_fill(_order("PDI", 100.0, 15.27), D, close, vol, vol_bp,
                        _costs("PDI"), cash=1e9)
    assert "ex-pdi" in str(e.value)


def test_round_trip_inside_one_day_raises(tmp_path):
    """Executions that net to zero cannot be one trade row. Say so, don't book 0."""
    close, vol, vol_bp = _frames("MHD", 11.10)
    rec = _record(Execution("MHD", "BUY", 500.0, 11.11, 0.5, "ex-1"),
                  Execution("MHD", "SLD", 500.0, 11.09, 0.5, "ex-2"))
    lg = _ledger(tmp_path, rec)
    with pytest.raises(ValueError, match="net to zero"):
        lg._broker_fill(_order("MHD", 500.0, 11.10), D, close, vol, vol_bp,
                        _costs("MHD"), cash=1e9)


# -- 5. the simulated path is untouched -----------------------------------

def test_simulated_path_is_unchanged(tmp_path):
    """`execution_record = None` must behave exactly as it did before.

    Every backtest, every research script and every sim-path book takes this
    branch. The two new columns are additive and `modelled_fill_price` equals
    `fill_price` here by construction.
    """
    close, vol, vol_bp = _frames("NAD", 11.15)
    lg = _ledger(tmp_path, None)
    fill = lg._simulate_fill(_order("NAD", 1000.0, 11.15), D, close, vol,
                             vol_bp, _costs("NAD"), cash=1e9)
    row = fill["row"]
    assert row["modelled_fill_price"] == row["fill_price"]
    assert row["exec_ids"] == ""
    assert fill["commission_usd"] is None, (
        "the simulator has no broker commission; advance() must fall back to "
        "the configured per-trade charge EXPLICITLY, never via a dict default")
    assert set(row) == set(TRADE_COLUMNS)
    # the modelled arithmetic itself is unchanged: buy fills a half-spread up
    assert row["fill_price"] == pytest.approx(
        11.15 * (1.0 + (1.0 + row["impact_bp"]) / 1e4))
