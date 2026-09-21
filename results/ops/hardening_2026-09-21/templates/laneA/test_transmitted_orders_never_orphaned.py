"""FAILING-FIRST (lane A draft): a transmitted order set must never be orphaned.

Replays 2026-09-11 / 09-14 / 09-15 on the cef_discount shadow ledger. Share counts,
prices and commissions are the incident's own (prod _order_map.csv ids 31-34, 37-40;
broker_fills.csv). Closes are SYNTHETIC-FLAT except where a fill needs one: the claim
is about OUR CODE (does the ledger represent what was sent), not about the market.
No broker, no network, tmp_path only.
"""
import os, sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np, pandas as pd, pytest

REPO = Path(os.environ.get("QUANTT_TREE", "/Users/simonjarvis/Desktop/2027/QUANTT/2027"))
sys.path.insert(0, str(REPO))
from ops.ledger import Execution, ExecutionRecord          # noqa: E402
from src.deploy.broker.simulator import Simulator          # noqa: E402
from src.deploy.sleeve import PositionTarget, LONG, SHORT  # noqa: E402

SLEEVE = "cef_discount"
EPOCH = {"AWF": 1926., "JFR": -10467., "NEA": -11576., "PDO": 7311., "PFN": 1555., "PHK": 7089.}
CLOSE = {"AWF": 9.96, "JFR": 7.60, "NEA": 10.85, "PDO": 12.36, "PFN": 6.64, "PHK": 4.36}
DAYS = pd.to_datetime(["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"])
SENT_0911 = {"JFR": +301., "PDO": -909., "PFN": +604., "PHK": +1389.}          # ids 31-34
SENT_0914 = {"AWF": -638., "JFR": +1446., "NEA": +904., "PFN": +3121.}         # ids 37-40
EXEC_0914 = [("PFN", "BUY", 604., 6.52, 3.021812, "6b7cfde6"), ("PHK", "BUY", 1389., 4.33, 6.949167, "6b7cff8e"),
             ("PDO", "SELL", 909., 12.02, 4.950061, "6b7cffdc"), ("JFR", "BUY", 301., 7.54, 1.505903, "6b7cffe0")]
EXEC_0915 = [("PFN", "BUY", 3121., 6.50, 15.614363, "6b8a9cdf"), ("AWF", "SELL", 638., 9.92, 3.446701, "6b8a9d18"),
             ("NEA", "BUY", 904., 10.51, 4.522712, "6b8a9d4f"), ("JFR", "BUY", 1446., 7.45, 7.234338, "6b8a9d6c")]


def _prices():
    rows = [{"date": d, "ticker": t, "close": c, "dividend": 0.0, "volume": 1e6} for d in DAYS for t, c in CLOSE.items()]
    return pd.DataFrame(rows)


def _seed_epoch(state):
    """Exactly what ops/reset_epoch.py writes: one nav row ON the epoch date, no orders."""
    state.mkdir(parents=True)
    inv = sum(q * CLOSE[t] for t, q in EPOCH.items())
    pd.DataFrame([{"date": "2026-09-11", "ticker": t, "shares": q, "close": CLOSE[t], "market_value": q * CLOSE[t],
                   "weight": q * CLOSE[t] / 5e5} for t, q in EPOCH.items()]).to_csv(state / "positions.csv", index=False)
    pd.DataFrame([{"date": "2026-09-11", "nav": 5e5, "cash": 5e5 - inv, "invested": inv, "distributions_usd": 0.0,
                   "cost_usd": 0.0, "traded_usd": 0.0, "daily_return": "", "decision": "epoch"}]).to_csv(state / "nav.csv", index=False)
    from ops.ledger import ORDER_COLUMNS, TRADE_COLUMNS
    pd.DataFrame(columns=ORDER_COLUMNS).to_csv(state / "orders.csv", index=False)
    pd.DataFrame(columns=TRADE_COLUMNS).to_csv(state / "trades.csv", index=False)


def _sim(tmp_path):
    _seed_epoch(tmp_path / SLEEVE)
    sim = Simulator(books_root=tmp_path, verbose=False)
    costs = {"tickers": {t: {"half_spread_bp": 10.0} for t in CLOSE}, "slippage_extra_bp": 0.0,
             "impact_coefficient": 0.5, "max_participation_pct": 100.0, "commission_usd_per_trade": 0.0}
    sim.register_sleeve(SLEEVE, "static_weights", {"rebalance": {"min_trade_usd": 517.0}}, costs, 5e5, list(CLOSE))
    return sim


def _targets(held, sent):
    want = {t: held.get(t, 0.0) + sent.get(t, 0.0) for t in set(held) | set(sent)}
    return [PositionTarget(instrument=t, side=LONG if q > 0 else SHORT, qty=q) for t, q in want.items()]


def _record(day, execs):
    rec = ExecutionRecord(source="test", covers=[pd.Timestamp(day)])
    for t, side, qty, px, comm, eid in execs:
        rec.add(Execution(t, side, qty, px, comm, eid), date=day)
    return rec


def test_first_session_on_the_epoch_date_still_records_what_was_transmitted(tmp_path):
    """2026-09-14 09:50. asof == the epoch row's date, so advance() is a NO-OP and step 4 never runs."""
    sim = _sim(tmp_path); ms = SimpleNamespace(prices=_prices())
    sim.place_targets(SLEEVE, _targets(EPOCH, SENT_0911), "2026-09-11", ms,
                      execution_record=ExecutionRecord(source="nothing", covers=[]))
    open_ = sim.ledger(SLEEVE).orders
    open_ = open_[open_["status"] == "open"] if len(open_) else open_
    assert dict(zip(open_.get("ticker", []), open_.get("delta_shares", []))) == SENT_0911, (
        "four MOC orders went to the exchange for the 2026-09-11 decision and the ledger holds no "
        "row for any of them; tomorrow their fills are unbookable by construction")


def test_the_three_session_sequence_books_every_execution(tmp_path):
    sim = _sim(tmp_path); ms = SimpleNamespace(prices=_prices())
    sim.place_targets(SLEEVE, _targets(EPOCH, SENT_0911), "2026-09-11", ms,
                      execution_record=ExecutionRecord(source="nothing", covers=[]))
    after_0914 = {t: EPOCH[t] + SENT_0911.get(t, 0.0) for t in EPOCH}
    sim.place_targets(SLEEVE, _targets(after_0914, SENT_0914), "2026-09-14", ms,
                      execution_record=_record("2026-09-14", EXEC_0914))          # raised UnbookedExecution in prod
    after_0915 = {t: after_0914[t] + SENT_0914.get(t, 0.0) for t in EPOCH}
    sim.place_targets(SLEEVE, _targets(after_0915, {}), "2026-09-15", ms,
                      execution_record=_record("2026-09-15", EXEC_0915))
    lg = sim.ledger(SLEEVE)
    assert lg.held_shares() == after_0915            # AWF 1288, JFR -8720, NEA -10672, PDO 6402, PFN 5280, PHK 8478
    booked = set(";".join(lg.trades["exec_ids"].astype(str)).split(";"))
    assert booked == {e[-1] for e in EXEC_0914 + EXEC_0915}, "every broker execution is in trades.csv exactly once"
