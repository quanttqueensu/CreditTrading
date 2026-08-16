"""A2 — VIX-keyed SPY option half-spread model (replaces the flat $0.02 floor).

WHY. The frozen VRP cost model (`data/vrp/costs_vrp.yaml`) charges a flat
$0.02/share half-spread per option leg-crossing. That number is an ASSUMED
floor (2x the $0.01 tick — the R2 option data is trades-only, no bid/ask
exists), and it is regime-blind: it charges Feb-2018 and Mar-2020 crossings the
same as a VIX-12 afternoon. REFINE_PREREG A2 requires a realistic model with
crisis widening before any short-vol number is read at face value.

CALIBRATION (documented, cited in results/refine/SHORTVOL_ACCURACY.md):

  * Calm regime. SPY is the penny-pilot poster child: published practitioner
    references put ATM SPY quotes at $0.01–$0.05 wide in normal tape
    (optionstradingiq.com "Options Bid Ask Spread"; a live CBOE delayed-quote
    sample pulled 2026-07-21 showed the ATM SPY call quoted $0.20/$0.21 —
    $0.01 wide — with VIX ~16). Half-spread <= $0.025. We KEEP the frozen
    $0.02 half-spread as the calm-regime value — it is already conservative
    (2-4x the observed calm half-spread) and keeping it means the model never
    reports a cheaper-than-frozen cost in a calm regime.

  * Crisis regime. Trades-only data cannot measure the crisis spread, and no
    free OPRA/CBOE historical quote archive is autonomously reachable (a live
    IB gateway would be required — flagged residual). The pre-registered
    stress range (REFINE_PREREG A2) is $0.50–$2.00 FULL spread in crisis;
    published accounts of Feb/Mar-2020 (VIX 14 -> 85) document severe SPY
    option spread widening as liquidity providers pulled quotes. We anchor:
    full spread $0.50 at VIX 40 (Volmageddon peak / early COVID) and $2.00 at
    VIX 80+ (COVID peak), linear in VIX between anchors, capped beyond.

MODEL.  half_spread(VIX) in $/share, per leg-crossing:

    VIX <= 20         : $0.02                        (frozen floor, calm)
    20 < VIX <= 40    : linear  $0.02 -> $0.25
    40 < VIX <= 80    : linear  $0.25 -> $1.00
    VIX > 80          : $1.00                        (cap)

  i.e. FULL spreads $0.04 / $0.50 / $2.00 at VIX 20/40/80 — the top two are
  exactly the pre-registered crisis range. A `stress` multiplier scales the
  whole curve (report 1x and 2x; the flat-floor 1x/2x/3x sweep remains in the
  frozen engine).

This module only prices leg-crossings; it changes NO frozen signal parameter.
The hedge leg keeps its 0.5bp half-spread (SPY shares stayed penny-wide even
in Mar-2020 relative to option quotes; a crisis multiple on 0.5bp is noise at
this book size and is covered by the 2x stress row).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
VIX_PATH = REPO / "data" / "vrp" / "vix_daily.parquet"

# (VIX, half-spread $/share) anchors — see module docstring for provenance.
VIX_ANCHORS = np.array([20.0, 40.0, 80.0])
HS_ANCHORS = np.array([0.02, 0.25, 1.00])
HS_FLOOR = 0.02          # calm-regime half-spread == the frozen floor
HS_CAP = 1.00            # $2.00 full spread cap (pre-registered crisis top)


def half_spread(vix, stress: float = 1.0) -> float | np.ndarray:
    """$/share option half-spread per leg-crossing at a given VIX level."""
    v = np.asarray(vix, dtype=float)
    hs = np.interp(v, VIX_ANCHORS, HS_ANCHORS, left=HS_FLOOR, right=HS_CAP)
    hs = hs * float(stress)
    return float(hs) if np.isscalar(vix) or getattr(vix, "ndim", 1) == 0 else hs


class VixKeyedSpread:
    """half-spread as a function of DATE, via the on-disk VIX series
    (nearest prior close — no look-ahead)."""

    def __init__(self, vix_path=VIX_PATH, stress: float = 1.0):
        v = pd.read_parquet(vix_path)
        v["date"] = pd.to_datetime(v["date"]).dt.date
        self.vix = v.sort_values("date").set_index("date")["vix"].astype(float)
        self.stress = float(stress)

    def vix_at(self, d) -> float:
        d = pd.Timestamp(d).date()
        s = self.vix[self.vix.index <= d]
        if s.empty:
            raise ValueError(f"no VIX on or before {d}")
        return float(s.iloc[-1])

    def __call__(self, d) -> float:
        return half_spread(self.vix_at(d), stress=self.stress)


def remark_cycles(cycles: pd.DataFrame, spread_fn, flat_floor: float = 0.02,
                  legs: int = 2, mult: int = 100) -> pd.DataFrame:
    """Re-mark a frozen cycle table (engine output or the published c2b CSV)
    from the flat floor to per-crossing half-spreads.

    Option costs in the frozen path are ADDITIVE and path-independent (no stop,
    no richness gate — both FROZEN OFF), so re-marking is exact arithmetic:

        adj_net = net_pnl_unit
                  + legs*mult*flat_floor*2            (remove entry+exit floor)
                  - legs*mult*(hs(entry) + hs(exit))  (charge modeled spreads)

    Uses `net_pnl_unit_raw` when present (engine output, unrounded).
    Returns a copy with hs_entry/hs_exit/net_adj/ret_adj columns.
    """
    out = cycles.copy()
    base = out["net_pnl_unit_raw"] if "net_pnl_unit_raw" in out else out["net_pnl_unit"]
    out["hs_entry"] = [spread_fn(d) for d in out["entry"]]
    out["hs_exit"] = [spread_fn(d) for d in out["exit"]]
    per_leg = legs * mult
    out["opt_cost_flat"] = 2 * per_leg * flat_floor
    out["opt_cost_model"] = per_leg * (out["hs_entry"] + out["hs_exit"])
    out["net_adj"] = base + out["opt_cost_flat"] - out["opt_cost_model"]
    out["ret_adj"] = out["net_adj"] / out["notional"]
    return out


def breakeven_flat_half_spread(cycles: pd.DataFrame, flat_floor: float = 0.02,
                               legs: int = 2, mult: int = 100) -> float:
    """The flat per-crossing half-spread ($/share) at which the MEAN net
    per-cycle P&L is zero: hs* = (mean(net) + 2*legs*mult*floor) / (2*legs*mult)."""
    base = cycles["net_pnl_unit_raw"] if "net_pnl_unit_raw" in cycles else cycles["net_pnl_unit"]
    gross_of_opt = float(base.mean()) + 2 * legs * mult * flat_floor
    return gross_of_opt / (2 * legs * mult)


def breakeven_stress_multiplier(cycles: pd.DataFrame, spread_fn_factory,
                                lo: float = 0.1, hi: float = 60.0,
                                tol: float = 1e-4) -> float | None:
    """The multiplier on the VIX-keyed curve at which mean net-adj = 0
    (bisection; None if even `hi` leaves the mean positive)."""
    def mean_at(s):
        fn = spread_fn_factory(s)
        return float(remark_cycles(cycles, fn)["net_adj"].mean())
    if mean_at(hi) > 0:
        return None
    a, b = lo, hi
    for _ in range(200):
        mid = 0.5 * (a + b)
        if mean_at(mid) > 0:
            a = mid
        else:
            b = mid
        if b - a < tol:
            break
    return 0.5 * (a + b)
