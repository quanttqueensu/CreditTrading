"""Credit RV — portfolio construction and simulation.

Implements CREDIT_RV_PREREG.md §3.6 and §4.

Timing contract (non-negotiable, mirrors the engine's guard):
    signal computed from data through close(t)
      -> target weights for close(t)
      -> FILLED at close(t+1)
      -> P&L accrues on the position actually held
There is no path by which a return on day t influences a position earning it.

Design notes that differ from a naive s-score book, each for a measured reason:

1. STICKY DISCRETE POSITIONS.  Tracking `-s` continuously produced 87x/yr one-way
   turnover and 4.9%/yr of cost drag, which buried the edge.  A position is opened
   at a fixed risk-parity unit when |s| crosses `s_entry`, held while the trade is
   alive, and closed on reversion (|s| < s_exit), stop (|s| > s_stop) or when the
   name stops qualifying.  Size is refreshed only when it drifts outside a
   no-trade band.

2. RISK-PARITY UNITS.  Each open name is sized inversely to its own residual vol
   so every position contributes equal risk, rather than equal dollars.

3. CHEAP EXPLICIT HEDGES.  Rather than re-projecting every credit leg daily
   (which regenerates turnover in 3-6bp instruments), the book's net factor
   exposure is neutralised with the liquid factor legs (IEF, TLT, SHY, HYG, LQD,
   SPY at 0.5-1.1bp).  Same hard neutrality, a fraction of the cost.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import CostModel

HEDGE_LEGS = ["IEF", "TLT", "SHY", "HYG", "LQD", "SPY"]


@dataclass
class BookConfig:
    capital: float = 1_000_000.0
    vol_target: float = 0.13
    max_gross: float = 6.0
    max_risk_share: float = 0.60    # A1.4: few, large positions - opportunities are rare
    cov_window: int = 120
    cov_shrink: float = 0.20
    resid_vol_window: int = 60
    financing_spread_bp: float = 150.0
    short_borrow_bp: float = 50.0
    impact_coef: float = 1.0
    max_participation: float = 0.02
    vol_scale_cap: float = 8.0
    # Amendment 2: per-trade economic admissibility. A trade is taken only if its
    # OU-implied expected reversion clears its own round-trip cost by this margin.
    edge_margin: float = 3.0
    edge_horizon_days: float = 5.0
    rebalance_every: int = 1        # trade only every k-th day (turnover control)
    no_trade_band_nav: float = 0.01  # A1.5: ABSOLUTE band, in NAV units
    hedge_tol: float = 0.02          # re-hedge only if |net exposure| exceeds this
    hedge_legs: list[str] = field(default_factory=lambda: list(HEDGE_LEGS))
    cost_model: CostModel | None = None   # None -> legacy path


def solve_hedge(net_exposure: np.ndarray, Bh: np.ndarray,
                net_dollar: float = 0.0) -> np.ndarray:
    """Hedge-leg weights that cancel factor exposure AND dollar imbalance.

    Solves, in least squares,

        Bhᵀ h = -net_exposure          (K rows: zero factor exposure)
        1ᵀ  h = -net_dollar            (1 row : zero net dollars)

    Putting the dollar constraint HERE rather than demeaning the whole weight
    vector matters a great deal in practice: `w -= w.mean()` gives every one of
    the ~28 columns a small non-zero weight, so every instrument trades at every
    rebalance and the book pays spread on names it has no view about.  Absorbing
    the imbalance in the six liquid hedge legs (0.5-1.1bp) confines turnover to
    instruments that are cheap to trade.
    """
    ok = np.isfinite(Bh).all(axis=1)
    if ok.sum() == 0:
        return np.zeros(Bh.shape[0])
    h = np.zeros(Bh.shape[0])
    A = np.vstack([Bh[ok].T, np.ones((1, int(ok.sum())))])   # (K+1) x H
    rhs = np.concatenate([-net_exposure, [-net_dollar]])
    sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    h[ok] = sol
    return h


def shrunk_cov(R: np.ndarray, shrink: float) -> np.ndarray:
    """Covariance over the columns that actually have data in this window.

    An earlier version did ``R = R[np.isfinite(R).all(axis=1)]`` - dropping every
    ROW containing any NaN.  Because young ETFs (JAAA from 2020, JBBB from 2022)
    are NaN for most of the sample, that emptied every window and silently fell
    back to ``np.eye * 1e-4``.  The whole book was then sized by an identity
    matrix: the hedge legs earned no diversification credit, ex-ante vol was ~2.9x
    realised, and the vol target held gross near 0.9x instead of levering.

    Columns absent from the window get a large placeholder variance and zero
    covariance, so the optimiser will not take risk it cannot measure.
    """
    n_col = R.shape[1]
    S = np.eye(n_col) * 1e-4
    have = np.isfinite(R).sum(axis=0) >= max(20, int(0.5 * R.shape[0]))
    if have.sum() < 2:
        return S
    sub = R[:, have]
    rows = np.isfinite(sub).all(axis=1)
    if rows.sum() < 20:
        return S
    sub = sub[rows]
    C = np.cov(sub, rowvar=False)
    C = (1 - shrink) * C + shrink * np.diag(np.diag(C))
    ix = np.where(have)[0]
    S[np.ix_(ix, ix)] = C
    return S


def simulate(
    s_blend: pd.DataFrame,
    mask: pd.DataFrame,
    betas: dict,
    excess_returns: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    half_spread_bp: dict[str, float],
    rf_daily: pd.Series,
    cfg: BookConfig,
    s_entry: float = 1.25,
    s_exit: float = 0.50,
    s_stop: float = 3.00,
    exec_lag: int = 1,
    spread_mult: float = 1.0,
    sigma_eq: pd.DataFrame | None = None,
    kappa: pd.DataFrame | None = None,
) -> dict:
    CM = cfg.cost_model
    dates = s_blend.index
    sig_cols = list(s_blend.columns)
    hedges = [h for h in cfg.hedge_legs if h in excess_returns.columns]
    all_cols = sig_cols + [h for h in hedges if h not in sig_cols]
    hedge_pos = [all_cols.index(h) for h in hedges]
    N = len(all_cols)

    rx = excess_returns.reindex(index=dates, columns=all_cols)
    rx_v = rx.values
    hs = np.array([half_spread_bp.get(c, 5.0) for c in all_cols]) * spread_mult / 1e4
    adv = dollar_volume.reindex(index=dates, columns=all_cols).values

    # residual vol per name for risk-parity units
    resid_vol = rx[sig_cols].rolling(cfg.resid_vol_window, min_periods=30).std().values
    # per-instrument daily vol in bp for the square-root impact law. A hardcoded
    # 100bp overstates credit ETFs (HYG ~68bp/day, LQD ~44bp/day) by ~2.5x.
    day_vol_bp_arr = (rx.rolling(60, min_periods=20).std() * 1e4).fillna(50.0).values

    # --- Amendment 2: OU-implied expected edge, in return units, per name-day.
    #     E[reversion over h] = |s| * sigma_eq * (1 - exp(-kappa*h/252))
    #     Trade only if that clears edge_margin x round-trip cost.
    sig_hs = np.array([half_spread_bp.get(c, 5.0) for c in sig_cols]) * spread_mult / 1e4
    rt_cost = 2.0 * sig_hs
    if sigma_eq is not None and kappa is not None:
        se = sigma_eq.reindex(index=dates, columns=sig_cols).values
        kp = kappa.reindex(index=dates, columns=sig_cols).values
        with np.errstate(over="ignore", invalid="ignore"):
            rev_frac = 1.0 - np.exp(-np.clip(kp, 0, None) * cfg.edge_horizon_days / 252.0)
        exp_edge_unit = np.abs(se) * rev_frac          # per unit of |s|
    else:
        exp_edge_unit = None

    held = np.zeros(N)
    open_dir = np.zeros(len(sig_cols))     # -1/0/+1 : the live trade direction
    entry_day = np.full(len(sig_cols), -1)
    pending: list[tuple[int, np.ndarray]] = []
    prev_target = np.zeros(N)

    nav = cfg.capital
    recs, trades = [], []
    cost_by_leg = np.zeros(N)
    turn_by_leg = np.zeros(N)
    w_hist = np.zeros((len(dates), N))
    hold_lengths: list[int] = []

    for i, d in enumerate(dates):
        # ---------------- 1. fills land -------------------------------------
        newly = [w for (fi, w) in pending if fi == i]
        pending = [(fi, w) for (fi, w) in pending if fi != i]
        spread_cost = impact_cost = 0.0
        if newly:
            tgt = newly[-1]
            trade = tgt - held
            notional = np.abs(trade) * nav
            spread_cost = float((notional * hs).sum())
            dvb = np.nan_to_num(day_vol_bp_arr[i], nan=50.0)
            if CM is not None:
                impact_bp = CM.impact_bp(notional, adv[i], dvb)
            else:
                with np.errstate(divide="ignore", invalid="ignore"):
                    part = np.where(adv[i] > 0, notional / adv[i], 0.0)
                part = np.nan_to_num(part, nan=0.0, posinf=0.0)
                impact_bp = cfg.impact_coef * dvb * np.sqrt(np.clip(part, 0, None))
            impact_cost = float((notional * impact_bp / 1e4).sum())
            cost_by_leg += notional * hs + notional * impact_bp / 1e4
            turn_by_leg += notional
            nav -= (spread_cost + impact_cost)
            held = tgt.copy()

        # ---------------- 2. P&L on what is actually held --------------------
        r = np.nan_to_num(rx_v[i], nan=0.0)
        gross_pnl = float(held @ r) * nav
        gross = float(np.abs(held).sum())
        long_n = float(np.clip(held, 0, None).sum()) * nav
        short_n = float(np.abs(np.minimum(held, 0)).sum()) * nav
        rf_d = float(rf_daily.get(d, 0.0))
        if CM is not None:
            fin_cost, cash_yield = CM.financing_daily(nav, long_n, short_n, rf_d * 252.0)
            borrow_cost = 0.0        # folded into fin_cost by the model
        else:
            short = short_n / max(nav, 1.0)
            borrow_cost = nav * short * cfg.short_borrow_bp / 1e4 / 252.0
            fin_cost = nav * max(gross - 1.0, 0.0) * cfg.financing_spread_bp / 1e4 / 252.0
            cash_yield = nav * rf_d
        nav += gross_pnl - borrow_cost - fin_cost + cash_yield

        # ---------------- 3. form new target from info through close(t) ------
        s = s_blend.iloc[i].values.astype(float)
        m = mask.iloc[i].values.astype(bool)
        B = betas.get(d)

        if B is None or (i % cfg.rebalance_every != 0):
            w_new = prev_target.copy()
        else:
            # --- state machine on each signal name (this is what makes it sticky)
            for j in range(len(sig_cols)):
                sj, alive = s[j], open_dir[j] != 0.0
                if alive:
                    close = (not np.isfinite(sj)) or (abs(sj) <= s_exit) \
                        or (abs(sj) >= s_stop) or (not m[j])
                    if close:
                        if entry_day[j] >= 0:
                            hold_lengths.append(i - entry_day[j])
                            trades.append({"ticker": sig_cols[j], "entry": entry_day[j],
                                           "exit": i, "days": i - entry_day[j],
                                           "dir": open_dir[j]})
                        open_dir[j], entry_day[j] = 0.0, -1
                elif m[j] and np.isfinite(sj) and abs(sj) >= s_entry and abs(sj) < s_stop:
                    # economic gate: does this trade pay for its own execution?
                    if exp_edge_unit is not None:
                        e = abs(sj) * exp_edge_unit[i, j]
                        if not np.isfinite(e) or e < cfg.edge_margin * rt_cost[j]:
                            continue
                    open_dir[j] = -np.sign(sj)      # short the rich, buy the cheap
                    entry_day[j] = i

            # --- risk-parity units on the open set
            raw = np.zeros(N)
            rv = resid_vol[i]
            live = open_dir != 0.0
            if live.any():
                inv = np.where((rv > 1e-8) & np.isfinite(rv), 1.0 / rv, 0.0)
                inv = np.where(live, inv, 0.0)
                if inv.sum() > 0:
                    units = inv / inv.sum()
                    cap = cfg.max_risk_share
                    units = np.minimum(units, cap)
                    if units.sum() > 0:
                        units = units / units.sum()
                    raw[:len(sig_cols)] = open_dir * units

            # --- hard factor neutralisation via the cheap hedge legs
            Bfull = B.reindex(all_cols).values
            sig_exposure = np.nan_to_num(
                raw[:len(sig_cols)] @ np.nan_to_num(Bfull[:len(sig_cols)]))
            w = raw.copy()
            # residual exposure of the CURRENTLY HELD hedge book
            cur_hedge = held[hedge_pos]
            resid_exp = sig_exposure + np.nan_to_num(cur_hedge @ Bfull[hedge_pos])
            sig_dollar = float(raw[:len(sig_cols)].sum())
            if np.abs(resid_exp).max() > cfg.hedge_tol or not live.any():
                h = solve_hedge(sig_exposure, Bfull[hedge_pos], net_dollar=sig_dollar)
            else:
                h = cur_hedge                       # inside tolerance: leave it alone
            for k, hp in enumerate(hedge_pos):
                w[hp] += h[k]

            # --- vol target on the composed book
            hist = rx_v[max(0, i - cfg.cov_window + 1): i + 1]
            S = shrunk_cov(hist, cfg.cov_shrink)
            pv = float(np.sqrt(max(w @ S @ w, 1e-18)) * np.sqrt(252))
            scale = min(cfg.vol_target / pv, cfg.vol_scale_cap) if pv > 1e-12 else 0.0
            w = w * scale

            g = np.abs(w).sum()
            if g > cfg.max_gross:
                w *= cfg.max_gross / g

            # --- participation cap
            trade_notional = np.abs(w - held) * nav
            advi = np.nan_to_num(adv[i], nan=0.0, posinf=0.0)
            capn = np.where(advi > 0, advi * cfg.max_participation, 0.0)
            has_vol = advi > 0
            over = has_vol & (trade_notional > capn)
            if over.any():
                step = np.sign(w - held) * capn / max(nav, 1.0)
                w = np.where(over, held + step, w)
            # a name with no volume that day simply cannot be traded
            w = np.where(~has_vol, held, w)

            # --- no-trade band, ABSOLUTE in NAV units (A1.5). A relative band
            #     divided by each leg's own target, so legs near zero always traded.
            keep = np.abs(w - held) < cfg.no_trade_band_nav
            w = np.where(keep, held, w)

            w_new = w

        prev_target = w_new
        if i + exec_lag < len(dates):
            pending.append((i + exec_lag, w_new.copy()))

        w_hist[i] = held
        recs.append({"date": d, "nav": nav, "gross_pnl": gross_pnl,
                     "spread_cost": spread_cost, "impact_cost": impact_cost,
                     "borrow_cost": borrow_cost, "fin_cost": fin_cost,
                     "cash_yield": cash_yield, "gross": gross,
                     "n_pos": int((np.abs(held) > 1e-6).sum()),
                     "n_open": int(live.sum()) if B is not None else 0,
                     "on_risk": bool(gross > 1e-6)})

    out = pd.DataFrame(recs).set_index("date")
    out["ret"] = out["nav"].pct_change().fillna(0.0)
    return {
        "path": out,
        "cost_by_leg": pd.Series(cost_by_leg, index=all_cols),
        "turnover_by_leg": pd.Series(turn_by_leg, index=all_cols),
        "weights": pd.DataFrame(w_hist, index=dates, columns=all_cols),
        "trades": pd.DataFrame(trades),
        "median_hold": float(np.median(hold_lengths)) if hold_lengths else np.nan,
    }


def stats(path: pd.DataFrame, rf_daily: pd.Series, median_hold: float = np.nan) -> dict:
    r = path["ret"]
    n = len(r)
    if n < 20 or r.std() == 0:
        return {"cagr": np.nan, "vol": np.nan, "sharpe": np.nan, "maxdd": np.nan}
    yrs = n / 252.0
    cagr = (path["nav"].iloc[-1] / path["nav"].iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    rf = rf_daily.reindex(r.index).ffill().fillna(0.0)
    ex = r - rf
    dd = path["nav"] / path["nav"].cummax() - 1
    return {
        "cagr": float(cagr), "vol": float(vol),
        "sharpe": float(ex.mean() / ex.std() * np.sqrt(252)) if ex.std() > 0 else np.nan,
        "maxdd": float(dd.min()), "n_days": int(n),
        "avg_gross": float(path["gross"].mean()),
        "avg_n_pos": float(path["n_pos"].mean()),
        "median_hold_days": float(median_hold),
        "cost_drag_pct_yr": float((path["spread_cost"] + path["impact_cost"]).sum()
                                  / path["nav"].mean() / yrs * 100),
        "fin_drag_pct_yr": float((path["fin_cost"] + path["borrow_cost"]).sum()
                                 / path["nav"].mean() / yrs * 100),
    }
