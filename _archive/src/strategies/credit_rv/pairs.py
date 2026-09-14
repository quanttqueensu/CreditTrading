"""Credit RV — cluster-pair implementation.

Why this exists
---------------
The general implementation (``book.py``) neutralises each dislocated name against
a six-leg synthetic factor hedge (IEF/TLT/SHY/HYG/LQD/SPY).  Measured over the IS
sample that hedge generated **$1.39bn of turnover on a $1m book (116x/yr)**, of
which HYG and LQD alone were 44% — more cost than the signal earned.

A cluster peer is a strictly better hedge than a synthetic one.  HYG and JNK hold
overlapping portfolios of the same high-yield bonds: their rate duration, spread
duration and equity sensitivity are near-identical, so the pair is factor-matched
*by construction* rather than by estimation.  That means

  - 2 legs per trade instead of 7,
  - no beta estimation error entering the hedge,
  - no re-hedging turnover when betas drift,
  - and the residual traded is the near-arbitrage of prereg §3.4, not the diluted
    complex-wide residual.

The trade: when a cluster member's within-cluster s-score exceeds the entry
threshold, take it against the equal-weighted basket of its remaining peers,
dollar-matched.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .signal import CLUSTERS


@dataclass
class PairConfig:
    capital: float = 1_000_000.0
    vol_target: float = 0.13
    max_gross: float = 6.0
    s_entry: float = 2.00
    s_exit: float = 0.50
    s_stop: float = 3.50
    max_halflife: float = 10.0
    min_ar_r2: float = 0.05
    edge_margin: float = 3.0
    edge_horizon_days: float = 5.0
    cov_window: int = 120
    cov_shrink: float = 0.05
    vol_scale_cap: float = 8.0
    max_pair_risk_share: float = 0.60
    no_trade_band_nav: float = 0.02
    financing_spread_bp: float = 150.0
    short_borrow_bp: float = 50.0
    impact_coef: float = 1.0
    max_participation: float = 0.02
    min_adv_usd: float = 5e6
    clusters: dict = field(default_factory=lambda: dict(CLUSTERS))


def simulate_pairs(
    s_cluster: pd.DataFrame,
    halflife: pd.DataFrame,
    ar_r2: pd.DataFrame,
    sigma_eq: pd.DataFrame,
    kappa: pd.DataFrame,
    excess_returns: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    half_spread_bp: dict[str, float],
    rf_daily: pd.Series,
    cfg: PairConfig,
    exec_lag: int = 1,
    spread_mult: float = 1.0,
) -> dict:
    dates = s_cluster.index
    cols = [c for c in s_cluster.columns]
    pos = {c: i for i, c in enumerate(cols)}
    N = len(cols)

    rx = excess_returns.reindex(index=dates, columns=cols)
    rx_v = rx.values
    hs = np.array([half_spread_bp.get(c, 5.0) for c in cols]) * spread_mult / 1e4
    rt_cost = 2.0 * hs
    adv = np.nan_to_num(dollar_volume.reindex(index=dates, columns=cols).values, nan=0.0)
    day_vol_bp = (rx.rolling(60, min_periods=20).std() * 1e4).fillna(50.0).values

    sv = s_cluster.values
    hl = halflife.reindex(columns=cols).values
    r2 = ar_r2.reindex(columns=cols).values
    se = sigma_eq.reindex(columns=cols).values
    kp = kappa.reindex(columns=cols).values
    with np.errstate(over="ignore", invalid="ignore"):
        rev_frac = 1.0 - np.exp(-np.clip(kp, 0, None) * cfg.edge_horizon_days / 252.0)
    edge_unit = np.abs(se) * rev_frac

    # cluster membership as index lists
    cl = {name: [pos[t] for t in members if t in pos]
          for name, members in cfg.clusters.items()}
    cl = {k: v for k, v in cl.items() if len(v) >= 2}

    held = np.zeros(N)
    open_pair: dict[str, tuple[int, list[int], float, int]] = {}   # cluster -> (leg, peers, dir, entry_i)
    pending: list[tuple[int, np.ndarray]] = []
    prev_target = np.zeros(N)

    nav = cfg.capital
    recs, trades = [], []
    hold_lengths: list[int] = []
    cost_by_leg = np.zeros(N)
    turn_by_leg = np.zeros(N)
    w_hist = np.zeros((len(dates), N))

    for i, d in enumerate(dates):
        # ---- fills land -------------------------------------------------
        newly = [w for (fi, w) in pending if fi == i]
        pending = [(fi, w) for (fi, w) in pending if fi != i]
        spread_cost = impact_cost = 0.0
        if newly:
            tgt = newly[-1]
            notional = np.abs(tgt - held) * nav
            spread_cost = float((notional * hs).sum())
            with np.errstate(divide="ignore", invalid="ignore"):
                part = np.where(adv[i] > 0, notional / adv[i], 0.0)
            part = np.nan_to_num(part, nan=0.0, posinf=0.0)
            ib = cfg.impact_coef * np.nan_to_num(day_vol_bp[i], nan=50.0) * np.sqrt(
                np.clip(part, 0, None))
            impact_cost = float((notional * ib / 1e4).sum())
            cost_by_leg += notional * hs + notional * ib / 1e4
            turn_by_leg += notional
            nav -= (spread_cost + impact_cost)
            held = tgt.copy()

        # ---- P&L on what is held ---------------------------------------
        r = np.nan_to_num(rx_v[i], nan=0.0)
        gross_pnl = float(held @ r) * nav
        gross = float(np.abs(held).sum())
        short = float(np.abs(np.minimum(held, 0)).sum())
        borrow = nav * short * cfg.short_borrow_bp / 1e4 / 252.0
        fin = nav * max(gross - 1.0, 0.0) * cfg.financing_spread_bp / 1e4 / 252.0
        nav += gross_pnl - borrow - fin + nav * float(rf_daily.get(d, 0.0))

        # ---- form target from information through close(t) --------------
        s_i, hl_i, r2_i, eu_i, adv_i = sv[i], hl[i], r2[i], edge_unit[i], adv[i]

        # close finished pairs
        for cname in list(open_pair):
            leg, peers, direction, e0 = open_pair[cname]
            s_leg = s_i[leg]
            if (not np.isfinite(s_leg)) or abs(s_leg) <= cfg.s_exit or abs(s_leg) >= cfg.s_stop:
                hold_lengths.append(i - e0)
                trades.append({"cluster": cname, "ticker": cols[leg], "entry": e0,
                               "exit": i, "days": i - e0, "dir": direction})
                del open_pair[cname]

        # open new pairs: the most dislocated qualifying member of each cluster
        for cname, members in cl.items():
            if cname in open_pair:
                continue
            best, best_abs = None, cfg.s_entry
            for j in members:
                sj = s_i[j]
                if not np.isfinite(sj) or abs(sj) < best_abs or abs(sj) >= cfg.s_stop:
                    continue
                if not (np.isfinite(hl_i[j]) and 0 < hl_i[j] <= cfg.max_halflife):
                    continue
                if not (np.isfinite(r2_i[j]) and r2_i[j] >= cfg.min_ar_r2):
                    continue
                peers = [k for k in members if k != j and adv_i[k] >= cfg.min_adv_usd]
                if not peers or adv_i[j] < cfg.min_adv_usd:
                    continue
                # economic gate: expected reversion must clear BOTH legs' costs
                cost_rt = rt_cost[j] + float(np.mean(rt_cost[peers]))
                if not np.isfinite(eu_i[j]) or abs(sj) * eu_i[j] < cfg.edge_margin * cost_rt:
                    continue
                best, best_abs = (j, peers), abs(sj)
            if best is not None:
                j, peers = best
                open_pair[cname] = (j, peers, -np.sign(s_i[j]), i)

        # ---- weights: risk parity across live pairs, then vol target ----
        raw = np.zeros(N)
        if open_pair:
            units = {}
            for cname, (leg, peers, direction, _) in open_pair.items():
                spread_ret = rx_v[max(0, i - 59):i + 1, leg] - np.nanmean(
                    rx_v[max(0, i - 59):i + 1][:, peers], axis=1)
                sd = float(np.nanstd(spread_ret))
                units[cname] = 1.0 / sd if sd > 1e-8 else 0.0
            tot = sum(units.values())
            if tot > 0:
                for cname, (leg, peers, direction, _) in open_pair.items():
                    u = min(units[cname] / tot, cfg.max_pair_risk_share)
                    raw[leg] += direction * u
                    for k in peers:
                        raw[k] -= direction * u / len(peers)

        hist = rx_v[max(0, i - cfg.cov_window + 1): i + 1]
        S = _shrunk_cov(hist, cfg.cov_shrink)
        pv = float(np.sqrt(max(raw @ S @ raw, 1e-18)) * np.sqrt(252))
        scale = min(cfg.vol_target / pv, cfg.vol_scale_cap) if pv > 1e-12 else 0.0
        w = raw * scale
        g = np.abs(w).sum()
        if g > cfg.max_gross:
            w *= cfg.max_gross / g

        # participation cap and no-trade band
        trade_notional = np.abs(w - held) * nav
        capn = np.where(adv_i > 0, adv_i * cfg.max_participation, 0.0)
        has_vol = adv_i > 0
        over = has_vol & (trade_notional > capn)
        if over.any():
            w = np.where(over, held + np.sign(w - held) * capn / max(nav, 1.0), w)
        w = np.where(~has_vol, held, w)
        w = np.where(np.abs(w - held) < cfg.no_trade_band_nav, held, w)

        prev_target = w
        if i + exec_lag < len(dates):
            pending.append((i + exec_lag, w.copy()))

        w_hist[i] = held
        recs.append({"date": d, "nav": nav, "gross_pnl": gross_pnl,
                     "spread_cost": spread_cost, "impact_cost": impact_cost,
                     "borrow_cost": borrow, "fin_cost": fin, "gross": gross,
                     "n_pos": int((np.abs(held) > 1e-6).sum()),
                     "n_pairs": len(open_pair)})

    out = pd.DataFrame(recs).set_index("date")
    out["ret"] = out["nav"].pct_change().fillna(0.0)
    return {
        "path": out,
        "weights": pd.DataFrame(w_hist, index=dates, columns=cols),
        "trades": pd.DataFrame(trades),
        "cost_by_leg": pd.Series(cost_by_leg, index=cols),
        "turnover_by_leg": pd.Series(turn_by_leg, index=cols),
        "median_hold": float(np.median(hold_lengths)) if hold_lengths else np.nan,
    }


def _shrunk_cov(R: np.ndarray, shrink: float) -> np.ndarray:
    n_col = R.shape[1]
    S = np.eye(n_col) * 1e-4
    have = np.isfinite(R).sum(axis=0) >= max(20, int(0.5 * R.shape[0]))
    if have.sum() < 2:
        return S
    sub = R[:, have]
    rows = np.isfinite(sub).all(axis=1)
    if rows.sum() < 20:
        return S
    C = np.cov(sub[rows], rowvar=False)
    C = (1 - shrink) * C + shrink * np.diag(np.diag(C))
    ix = np.where(have)[0]
    S[np.ix_(ix, ix)] = C
    return S
