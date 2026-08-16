"""The ops-ledger fill-price math, factored out so the derivatives ledger and
the simulator price a trade exactly the way `ops/ledger.py` does — without
editing `ops/ledger.py` (Principle 0.1: it stays byte-for-byte).

`ops.ledger.Ledger._simulate_fill` is long-only and does several jobs at once
(affordability trim, order-row bookkeeping, the price formula). The PRICE
FORMULA — half-spread + square-root-law impact, applied on the correct side —
is the piece the derivatives ledger needs, so it is isolated here. A unit test
(`tests/test_fills.py`) asserts this function reproduces `_simulate_fill`'s
`fill_price` and `cost_usd` to the last bit on random inputs.
"""

import math

import numpy as np

# Same fallback the ops ledger / engine use when trailing vol is unavailable.
from ops import common as _ops_common

IMPACT_VOL_FALLBACK_BP = _ops_common.IMPACT_VOL_FALLBACK_BP


def half_spread_bp(costs, ticker) -> float:
    """half_spread_bp(ticker) + global slippage_extra_bp — the per-side spread
    the ops ledger charges. KeyErrors loudly on a missing ticker, exactly like
    the ops path (a missing costs entry is a hard prerequisite, not a default)."""
    return (float(costs["tickers"][ticker]["half_spread_bp"])
            + float(costs["slippage_extra_bp"]))


def impact_bp(costs, notional, dollar_volume, vol_bp):
    """Square-root-law market impact in bp:

        impact_bp = impact_coefficient * daily_vol_bp * sqrt(participation)

    with participation = notional / dollar_volume. When dollar_volume is
    unknown (<= 0), participation is NaN and impact degrades to
    impact_coefficient * daily_vol_bp — identical to `_simulate_fill`.

    Returns (impact_bp, participation, over_participation_cap).
    """
    coef = float(costs.get("impact_coefficient", 0.0))
    vbp = float(vol_bp) if np.isfinite(vol_bp) else IMPACT_VOL_FALLBACK_BP
    participation = (notional / dollar_volume
                     if dollar_volume and dollar_volume > 0 else np.nan)
    if np.isfinite(participation):
        ibp = coef * vbp * math.sqrt(participation)
    else:
        ibp = coef * vbp
    cap = float(costs.get("max_participation_pct", 100.0)) / 100.0
    over_cap = bool(np.isfinite(participation) and participation > cap)
    return ibp, participation, over_cap


def simulated_fill_price(delta_shares, close, costs, ticker,
                         dollar_volume=0.0, vol_bp=IMPACT_VOL_FALLBACK_BP):
    """Fill price and dollar cost for trading `delta_shares` at `close`.

    Buy  (delta > 0): close * (1 + (half_bp + impact_bp)/1e4)
    Sell (delta < 0): close * (1 - (half_bp + impact_bp)/1e4)

    with impact_bp from the square-root law. This is the SAME arithmetic as
    `ops.ledger.Ledger._simulate_fill`, in the same order, so the two agree to
    the bit. `cost_usd = |delta| * |fill_price - close|`.

    Returns a dict: fill_price, cost_usd, half_spread_bp, impact_bp,
    participation_pct, over_participation_cap.
    """
    delta = float(delta_shares)
    price = float(close)
    if not np.isfinite(price) or price <= 0 or delta == 0:
        return None

    half_bp = half_spread_bp(costs, ticker)
    notional = abs(delta) * price
    ibp, participation, over_cap = impact_bp(costs, notional, dollar_volume, vol_bp)

    side = 1.0 if delta > 0 else -1.0
    fill_price = price * (1.0 + side * (half_bp + ibp) / 1e4)
    cost_usd = abs(delta) * abs(fill_price - price)
    return {
        "fill_price": fill_price,
        "cost_usd": cost_usd,
        "half_spread_bp": half_bp,
        "impact_bp": ibp,
        "participation_pct": (participation * 100.0
                              if np.isfinite(participation) else np.nan),
        "over_participation_cap": over_cap,
    }
