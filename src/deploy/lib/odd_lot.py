"""Odd-lot corporate-bond cost model for the execution ledger (build B1).

FORCED_FLOW_PREREG.md, locked decision 1: IBKR *paper* fills on single
corporate bonds are unrealistically kind, so **every bond leg is charged the
measured odd-lot cost model in the ledger regardless of the paper fill**:

    1.45% round-trip at $25k-$100k notional      (results/S1_BOND_LEVEL.md)
    8.6%  round-trip for sub-20c (deep-discount) paper

and "these numbers may be re-measured but never reduced below fresh TRACE
evidence" — enforced here as hard floors: a config that tries to set a rate
below the measured floor raises. Re-measuring UP (worse) is allowed.

How it wires in (all ADDITIVE, default OFF):

  * A sleeve whose spec carries an ``odd_lot_cost`` block (see
    ``config_from_spec``) stamps ``leg_meta(cfg)`` onto each bond
    ``PositionTarget.meta``. Bond legs are represented as ``kind=ETF`` cash
    instruments priced off the staged close store (price per 100 par), with
    ``meta['asset']='corporate_bond'``.
  * ``DerivativesLedger._fill_order`` (src/deploy/exec_ledger.py) calls the
    ``_odd_lot_fill`` seam FIRST; it returns None for any leg without an
    ENABLED ``odd_lot_cost`` meta block, so every existing book takes the
    unchanged fill paths byte-for-byte. When enabled, the leg fills at
    ``close * (1 +/- per_side_rate)`` — charged at entry AND exit (each side
    pays half the round trip) — replacing (not stacking on) the ETF
    half-spread+impact model, which is neither measured nor meaningful for
    odd-lot bond prints.
  * IBKR/paper fills are RECORDED via ``record_broker_fill`` into a
    side-channel ``broker_fills.csv`` that no P&L path ever reads. The local
    simulated ledger (the simulator-of-record, per MarginBroker) is the only
    P&L source, and it always charges this model.

Prices are quoted per 100 par: "sub-20c" paper is ``price < 20.0``.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

# Measured floors — results/S1_BOND_LEVEL.md (TRACE odd-lot round trips).
# Never reduced except by fresh TRACE evidence, which means editing THESE
# constants with a cited re-measurement, not passing a kinder config.
FLOOR_ROUND_TRIP_PCT = 1.45
FLOOR_DEEP_DISCOUNT_ROUND_TRIP_PCT = 8.6
DEFAULT_DEEP_DISCOUNT_PRICE_THRESHOLD = 20.0   # price per 100 par ("sub-20c")

BROKER_FILLS_FILE = "broker_fills.csv"
BROKER_FILL_COLUMNS = ["recorded_utc", "fill_date", "instrument", "side",
                       "qty", "price", "source", "note"]

_NEVER_DRIVES_PNL = ("recorded for reconciliation only; never drives P&L "
                     "(FORCED_FLOW_PREREG decision 1: model cost governs)")


def config_from_spec(spec: dict) -> dict | None:
    """Read + validate a sleeve spec's ``odd_lot_cost`` block.

    Returns a normalized config dict, or None when the spec has no block or
    the block is not enabled (the DEFAULT: everything stays OFF). Raises
    ValueError on a config kinder than the measured floors.

    Spec shape::

        "odd_lot_cost": {
            "enabled": true,
            "round_trip_pct": 1.45,                  # optional, >= floor
            "deep_discount_round_trip_pct": 8.6,     # optional, >= floor
            "deep_discount_price_threshold": 20.0    # optional, per 100 par
        }
    """
    block = (spec or {}).get("odd_lot_cost")
    if not isinstance(block, dict) or not block.get("enabled"):
        return None
    rt = float(block.get("round_trip_pct", FLOOR_ROUND_TRIP_PCT))
    dd = float(block.get("deep_discount_round_trip_pct",
                         FLOOR_DEEP_DISCOUNT_ROUND_TRIP_PCT))
    thr = float(block.get("deep_discount_price_threshold",
                          DEFAULT_DEEP_DISCOUNT_PRICE_THRESHOLD))
    if rt < FLOOR_ROUND_TRIP_PCT - 1e-12:
        raise ValueError(
            f"odd_lot_cost.round_trip_pct {rt} is below the measured floor "
            f"{FLOOR_ROUND_TRIP_PCT}% (results/S1_BOND_LEVEL.md). The prereg "
            "forbids reducing it below fresh TRACE evidence; re-measure the "
            "floor constants with a cited study instead of passing a kinder "
            "config.")
    if dd < FLOOR_DEEP_DISCOUNT_ROUND_TRIP_PCT - 1e-12:
        raise ValueError(
            f"odd_lot_cost.deep_discount_round_trip_pct {dd} is below the "
            f"measured floor {FLOOR_DEEP_DISCOUNT_ROUND_TRIP_PCT}% "
            "(results/S1_BOND_LEVEL.md).")
    if thr <= 0:
        raise ValueError("deep_discount_price_threshold must be positive")
    return {"enabled": True, "round_trip_pct": rt,
            "deep_discount_round_trip_pct": dd,
            "deep_discount_price_threshold": thr}


def leg_meta(cfg: dict) -> dict:
    """The meta fragment a sleeve stamps on each bond PositionTarget so the
    execution ledger charges this model on every fill of that leg."""
    if not cfg or not cfg.get("enabled"):
        raise ValueError("leg_meta needs an ENABLED odd_lot_cost config "
                         "(config_from_spec returned None -> the model is OFF; "
                         "do not stamp bond legs)")
    return {"asset": "corporate_bond", "odd_lot_cost": dict(cfg)}


def per_side_rate(cfg: dict, price: float) -> tuple[float, str]:
    """(fractional per-side rate, tier) for a fill at ``price`` (per 100 par).

    Round trip = entry + exit, so each side pays half the round-trip
    percentage: 1.45%/2 = 0.725%/side standard, 8.6%/2 = 4.3%/side sub-20c.
    """
    thr = float(cfg.get("deep_discount_price_threshold",
                        DEFAULT_DEEP_DISCOUNT_PRICE_THRESHOLD))
    if float(price) < thr:
        return (float(cfg["deep_discount_round_trip_pct"]) / 2.0 / 100.0,
                "deep_discount")
    return float(cfg["round_trip_pct"]) / 2.0 / 100.0, "standard"


def odd_lot_fill_price(cfg: dict, delta_qty: float, close: float,
                       multiplier: float = 1.0) -> dict | None:
    """Fill price + dollar cost for trading ``delta_qty`` of a bond leg.

    Buy  (delta > 0): close * (1 + rate)
    Sell (delta < 0): close * (1 - rate)

    with ``rate = per_side_rate(cfg, close)``. Charged at entry AND exit; a
    round trip therefore pays the full ``round_trip_pct``. Returns None when
    the trade is degenerate (mirrors fills.simulated_fill_price semantics).
    """
    delta = float(delta_qty)
    price = float(close)
    mult = float(multiplier or 1.0)
    if not np.isfinite(price) or price <= 0 or delta == 0:
        return None
    rate, tier = per_side_rate(cfg, price)
    side = 1.0 if delta > 0 else -1.0
    fill_price = price * (1.0 + side * rate)
    cost_usd = abs(delta) * mult * abs(fill_price - price)
    return {"fill_price": fill_price, "cost_usd": cost_usd,
            "per_side_rate": rate, "tier": tier,
            "round_trip_pct": (float(cfg["deep_discount_round_trip_pct"])
                               if tier == "deep_discount"
                               else float(cfg["round_trip_pct"]))}


def record_broker_fill(state_dir, instrument, side, qty, price, fill_date,
                       source="ibkr_paper", note=_NEVER_DRIVES_PNL) -> Path:
    """Append one IBKR/paper fill to ``<state_dir>/broker_fills.csv``.

    Pure side-channel: nothing in the ledger, orchestrator, or reporting reads
    this file back into P&L — the simulated ledger with the model cost above
    is the only P&L source (paper bond fills are unrealistically kind).
    Atomic append (read+rewrite via temp file, same discipline as the ledger
    save())."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / BROKER_FILLS_FILE
    row = {"recorded_utc": pd.Timestamp.utcnow().isoformat(),
           "fill_date": str(pd.Timestamp(fill_date).date()),
           "instrument": str(instrument), "side": str(side),
           "qty": float(qty), "price": float(price),
           "source": str(source), "note": str(note)}
    if path.exists():
        frame = pd.read_csv(path)
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    else:
        frame = pd.DataFrame([row], columns=BROKER_FILL_COLUMNS)
    tmp = state_dir / f".{BROKER_FILLS_FILE}.tmp"
    with open(tmp, "w", newline="") as fh:
        frame.to_csv(fh, index=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path
