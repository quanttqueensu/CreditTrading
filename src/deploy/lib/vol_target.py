"""H2 — book-level vol-target overlay and the risk/return frontier.

REFINE_ARCHITECTURE.md §3. Scale the whole assembled book toward a target
annual vol. Applied in the orchestrator AFTER netting, BEFORE the leverage
clamp. The credit base collateral scales WITH the book (it is the lever); the
short-vol sleeve is NEVER scaled up (frozen PAPER_NO_CAPITAL — more yield =
more crash).

The dial is `book_spec['vol_target']['annual_vol_target']`. The DELIVERABLE is
the frontier `sweep_frontier` writes to results/refine/vol_target_frontier.csv;
because leverage scales daily P&L linearly, vol and return scale with k and the
Sharpe is invariant — the frontier is the honest leverage line, each point
tagged with the dollar loss its sizing would take in each pre-registered stress
window. The recommended deploy point is the largest target whose worst stress
month stays within `stress_drawdown_budget_usd` (recommend, never silently pick
Simon's risk).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Pre-registered stress windows (REFINE_ARCHITECTURE §3). Each is a calendar
# span; the loss is the peak-to-trough of the book NAV inside it.
STRESS_WINDOWS = {
    "gfc_2008":     ("2008-09-01", "2008-11-30"),
    "volmageddon":  ("2018-02-01", "2018-02-28"),
    "covid":        ("2020-02-19", "2020-03-23"),
    "rateshock_22": ("2022-08-01", "2022-10-31"),
}


class VolTargetOverlay:
    """Scale the book to a target annual vol from its trailing realized vol."""

    def __init__(self, annual_vol_target: float, vol_window_days: int = 63,
                 k_max: float | None = None, floor_vol: float = 0.005,
                 min_obs: int = 20):
        self.annual_vol_target = float(annual_vol_target)
        self.vol_window_days = int(vol_window_days)
        self.k_max = None if k_max is None else float(k_max)
        self.floor_vol = float(floor_vol)
        self.min_obs = int(min_obs)

    def realized_book_vol(self, book_nav: pd.Series) -> float:
        """Annualized trailing-window vol of the book NAV's daily returns."""
        nav = pd.Series(book_nav).astype(float).dropna()
        if len(nav) < self.min_obs + 1:
            return np.nan
        rets = nav.pct_change().dropna().iloc[-self.vol_window_days:]
        if len(rets) < self.min_obs:
            return np.nan
        return float(rets.std(ddof=1) * math.sqrt(TRADING_DAYS))

    def scale_factor(self, book_nav: pd.Series) -> float:
        """k = target / max(realized, floor), clipped to [0, k_max]. Returns
        1.0 on cold start (too little history to measure vol)."""
        rv = self.realized_book_vol(book_nav)
        if not np.isfinite(rv):
            return 1.0
        k = self.annual_vol_target / max(rv, self.floor_vol)
        if self.k_max is not None:
            k = min(k, self.k_max)
        return float(max(0.0, k))

    def apply(self, legs, k, no_scale_up_kinds=("OPTION",)):
        """Multiply each risky leg's signed qty by k (integer-round FUTURES and
        OPTION contracts, floor share magnitude). Legs whose kind is in
        `no_scale_up_kinds` are never scaled ABOVE 1.0 (short-vol frozen)."""
        from ..sleeve import FLAT, FUTURES, OPTION, PositionTarget, LONG, SHORT
        out = []
        for lg in legs:
            if lg.side == FLAT or lg.qty is None:
                out.append(lg)
                continue
            kk = min(k, 1.0) if lg.kind in no_scale_up_kinds else k
            signed = lg.signed_qty() * kk
            if lg.kind in (FUTURES, OPTION):
                q = float(round(signed))
            else:
                q = float(math.copysign(math.floor(abs(signed)), signed))
            if abs(q) < 1e-12:
                out.append(PositionTarget(instrument=lg.instrument, side=FLAT,
                                          kind=lg.kind, qty=0.0,
                                          reason=f"[volscale k={kk:.3f}->0] {lg.reason}",
                                          combo_id=lg.combo_id, meta=dict(lg.meta)))
                continue
            side = SHORT if q < 0 else LONG
            out.append(PositionTarget(instrument=lg.instrument, side=side,
                                      kind=lg.kind, qty=q,
                                      reason=f"[volscale k={kk:.3f}] {lg.reason}",
                                      combo_id=lg.combo_id, meta=dict(lg.meta)))
        return out


def stress_month_loss(book_nav_replay: pd.Series,
                      stress_windows: dict | None = None) -> dict:
    """Peak-to-trough dollar loss the given NAV path takes inside each
    pre-registered stress window (0.0 if the window is outside the sample)."""
    windows = stress_windows or STRESS_WINDOWS
    nav = pd.Series(book_nav_replay).astype(float).dropna()
    nav.index = pd.to_datetime(nav.index)
    out = {}
    for name, (lo, hi) in windows.items():
        seg = nav.loc[(nav.index >= pd.Timestamp(lo)) & (nav.index <= pd.Timestamp(hi))]
        if len(seg) < 2:
            out[name] = 0.0
            continue
        trough = float((seg - seg.cummax()).min())
        out[name] = trough
    return out


def sweep_frontier(base_daily_returns: pd.Series, base_capital: float,
                   vol_grid, stress_windows: dict | None = None,
                   out_csv: str | None = None) -> pd.DataFrame:
    """The H2 frontier from a k=1 book daily-RETURN series.

    Leverage scales daily P&L linearly, so at target vol v the scale is
    k = v / realized_vol(base) and every point shares the base Sharpe. Each row:
    target_vol, k, realized_vol, ann_ret, sharpe, maxDD, and the stress-window
    dollar loss (scaled by k on `base_capital`). Deterministic — MDE n/a (a
    sizing transform of a fixed return stream, no new sampling).
    """
    r = pd.Series(base_daily_returns).astype(float).dropna()
    r.index = pd.to_datetime(r.index)
    if len(r) < 20:
        raise ValueError("need >= 20 daily returns to build the frontier")
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    base_vol = sd * math.sqrt(TRADING_DAYS)
    sharpe = (mu / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else np.nan
    nav = base_capital * (1.0 + r).cumprod()
    base_stress = stress_month_loss(nav, stress_windows)
    rows = []
    for v in vol_grid:
        v = float(v)
        k = v / base_vol if base_vol > 0 else np.nan
        rk = r * k
        navk = base_capital * (1.0 + rk).cumprod()
        dd = float((navk / navk.cummax() - 1.0).min())
        row = {"target_vol_pct": v * 100.0, "k": k,
               "realized_vol_pct": v * 100.0,
               "ann_ret_pct": mu * k * TRADING_DAYS * 100.0,
               "sharpe": sharpe, "maxDD_pct": dd * 100.0}
        worst = 0.0
        for name, loss in base_stress.items():
            row[f"{name}_usd"] = loss * k
            worst = min(worst, loss * k)
        row["worst_stress_usd"] = worst
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["sample"] = (str(r.index.min().date()), str(r.index.max().date()),
                           len(r))
    if out_csv:
        out.to_csv(out_csv, index=False)
    return out


def recommend_point(frontier: pd.DataFrame, stress_budget_usd: float) -> dict:
    """The largest target vol whose worst stress loss stays within the declared
    drawdown budget. Recommends, does not pick — returns the row + rationale."""
    budget = -abs(float(stress_budget_usd))
    ok = frontier[frontier["worst_stress_usd"] >= budget]
    if ok.empty:
        r = frontier.iloc[0]
        return {"target_vol_pct": float(r["target_vol_pct"]), "k": float(r["k"]),
                "within_budget": False,
                "note": "even the lowest grid point breaches the stress budget"}
    r = ok.sort_values("target_vol_pct").iloc[-1]
    return {"target_vol_pct": float(r["target_vol_pct"]), "k": float(r["k"]),
            "worst_stress_usd": float(r["worst_stress_usd"]),
            "within_budget": True,
            "note": f"largest target vol with worst stress >= ${budget:,.0f}"}
