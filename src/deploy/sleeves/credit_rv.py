"""Credit ETF relative-value sleeve — the bounce-free configuration.

WHAT THIS TRADES, AND WHY IT IS SHAPED THIS WAY
-----------------------------------------------
Phase 0 (`results/credit_rv/FINDINGS.md` §8e) established two things that dictate
every choice below.

1. **The signal must be built on the (H+L)/2 mid, not the close.** The 2x2 there
   is unambiguous: a close-built signal predicting mid-to-mid returns scores
   Sharpe -0.41. It does not forecast fair value; it forecasts the reversal of its
   own bid-ask bounce. Only the mid-built signal survives, and (H+L)/2 for day t is
   known at that day's close, so it is still computable in time to trade.

2. **The machinery must stay out of the way.** §8d showed the original book
   (state machine, admissibility mask, risk-parity units, no-trade band) cut the
   pure signal from Sharpe 4.26 to 0.56, with the mask alone responsible for
   4.26 -> 1.79 because it filtered on the complex residual's half-life while the
   traded signal was 60% the cluster residual. So this sleeve holds `w ∝ -s`,
   factor-neutralised, and does nothing else. No mask, no hysteresis, no bands.

Turnover control is a single EWMA smoother on the weight vector. That is the one
knob that matters: the book earns ~1.2bp per unit of turnover, so the smoothing
constant sets whether it clears its own spread.

EXECUTION CONVENTION
--------------------
Signal from `asof`'s (H+L)/2; the orchestrator makes the target true by trading at
the NEXT close. That is the T+1 convention the backtest used (`ret_close` indexed
at j+1), so the live book and the backtest are the same experiment.

Every parameter comes from `spec["frozen"]`. This module invents nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..registry import register
from ..sleeve import ETF, FLAT, LONG, OK, KILL, HALVE
from ..sleeve import MarketState, PositionTarget, RiskVerdict, Sleeve, SHORT

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.strategies.credit_rv.signal import SignalConfig, compute_signals  # noqa: E402


@register
class CreditRVSleeve(Sleeve):
    """Factor-neutral cross-sectional RV on the credit ETF complex."""

    alloc_type = "credit_rv_statarb"

    # ---------------------------------------------------------------- shape ---
    def instruments(self) -> list[str]:
        """Traded names plus the factor legs needed to build and neutralise."""
        from src.strategies.credit_rv.signal import FACTOR_LEGS

        legs = set()
        for lo, hi in FACTOR_LEGS.values():
            legs.add(lo)
            if hi:
                legs.add(hi)
        return sorted(set(self.frozen.get("universe", [])) | legs)

    def history_warmup_trading_days(self) -> int:
        """beta window + residual window + EWMA burn-in, with headroom.

        `compute_signals` produces its first row at `w_beta + w_resid`; the EWMA
        needs several multiples of its span on top before the weight vector is
        representative rather than a transient.
        """
        f = self.frozen
        return int(f.get("w_beta", 120) + f.get("w_resid", 60)
                   + 5 * f.get("smooth", 20) + 40)

    # --------------------------------------------------------------- signal ---
    def _panel(self, prices: pd.DataFrame, asof) -> tuple:
        """Mid-return / dollar-volume panels from the ops price store.

        The mid is (high+low)/2. If the store has no high/low for a name — rows
        written before that column pair was added — the name is dropped rather
        than silently falling back to the close, because a close-built signal is
        precisely the contaminated one Phase 0 rejected.
        """
        p = prices[prices["date"] <= pd.Timestamp(asof)].copy()
        if "high" not in p.columns or "low" not in p.columns:
            return None, None, "price store has no high/low columns"

        p["mid_hl"] = (p["high"].astype(float) + p["low"].astype(float)) / 2.0
        wide_mid = p.pivot(index="date", columns="ticker", values="mid_hl").sort_index()
        wide_div = (p.pivot(index="date", columns="ticker", values="dividend")
                    .sort_index().reindex_like(wide_mid).fillna(0.0))

        # a name with no usable range history cannot carry a bounce-free signal
        usable = [c for c in wide_mid.columns if wide_mid[c].notna().sum() >= 60]
        wide_mid = wide_mid[usable]
        wide_div = wide_div[usable]
        if wide_mid.shape[1] < 8:
            return None, None, f"only {wide_mid.shape[1]} names with high/low history"

        ret_mid = (wide_mid + wide_div) / wide_mid.shift(1) - 1.0
        dv = (p.assign(dv=p["close"] * p["volume"])
              .pivot(index="date", columns="ticker", values="dv")
              .sort_index().reindex(columns=usable))
        return ret_mid, dv, ""

    def _weights(self, asof, market_state: MarketState):
        """Target weight per name. Returns (Series | None, note)."""
        f = self.frozen
        ret_mid, dv, err = self._panel(market_state.prices, asof)
        if ret_mid is None:
            return None, err

        rf = market_state.extras.get("rf_daily")
        if rf is None:
            rf = pd.Series(0.0, index=ret_mid.index)
        rf = pd.Series(rf).reindex(ret_mid.index).ffill().fillna(0.0)

        universe = [t for t in f.get("universe", []) if t in ret_mid.columns]
        if len(universe) < int(f.get("min_names", 6)):
            return None, f"universe collapsed to {len(universe)} names"

        cfg = SignalConfig(
            w_beta=int(f.get("w_beta", 120)),
            w_resid=int(f.get("w_resid", 60)),
            theta=float(f.get("theta", 0.60)),
            tradeable=universe,
        )
        sig = compute_signals(ret_mid, rf, dv, cfg)
        S = sig["s_blend"]
        if S.empty:
            return None, "signal panel empty (insufficient history)"

        # Replay the EWMA from the start of available signal so today's weight
        # carries the same smoothing state the backtest had. Cheap: one pass.
        cols = list(S.columns)
        betas = sig["betas"]
        smooth = int(f.get("smooth", 20))
        alpha = 2.0 / (smooth + 1.0) if smooth > 1 else 1.0
        max_w = float(f.get("max_weight_per_name", 0.35))

        prev = None
        for d in S.index:
            B = betas.get(d)
            if B is None:
                continue
            s = S.loc[d].values.astype(float)
            ok = np.isfinite(s)
            if ok.sum() < 4:
                continue
            w = np.zeros(len(cols))
            w[ok] = -s[ok]
            w[ok] -= w[ok].mean()
            Bv = B.reindex(cols).values
            good = ok & np.isfinite(Bv).all(axis=1)
            if good.sum() < int(f.get("min_names_neutral", 7)):
                continue
            Bk, wk = Bv[good], w[good]
            # residualise the weight vector against the factor betas -> the book
            # carries no rates / credit / quality / equity exposure by construction
            wk = wk - Bk @ np.linalg.solve(
                Bk.T @ Bk + 1e-10 * np.eye(Bk.shape[1]), Bk.T @ wk)
            w = np.zeros(len(cols))
            w[good] = wk - wk.mean()
            n = np.abs(w).sum()
            if n < 1e-12:
                continue
            w /= n
            if prev is not None and smooth > 1:
                w = alpha * w + (1 - alpha) * prev
                n = np.abs(w).sum()
                w = w / n if n > 1e-12 else w
            prev = w

        if prev is None:
            return None, "no admissible signal day in history"

        w = pd.Series(prev, index=cols)
        w = w.clip(-max_w, max_w)
        n = w.abs().sum()
        if n < 1e-12:
            return None, "degenerate (all-zero) weight vector"
        w = w / n * float(f.get("gross_leverage", 1.0))
        return w, ""

    # --------------------------------------------------------------- targets ---
    def target_positions(self, asof, market_state: MarketState) -> list[PositionTarget]:
        w, note = self._weights(asof, market_state)
        if w is None:
            # Never guess. An unavailable signal means hold nothing, and say why.
            return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                   reason=f"credit_rv: no signal ({note})")
                    for t in self.frozen.get("universe", [])]

        min_w = float(self.frozen.get("min_abs_weight", 0.005))
        out = []
        for t in self.frozen.get("universe", []):
            wt = float(w.get(t, 0.0))
            if not np.isfinite(wt) or abs(wt) < min_w:
                out.append(PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                          reason="credit_rv: below min weight"))
                continue
            out.append(PositionTarget(
                instrument=t,
                side=LONG if wt > 0 else SHORT,
                kind=ETF,
                weight=abs(wt) if wt > 0 else -abs(wt),
                reason=f"credit_rv s_blend w={wt:+.4f}",
            ))
        return out

    # ------------------------------------------------------------------ risk ---
    def risk_check(self, ledger_view) -> RiskVerdict:
        """Drawdown-based kill, per the sleeve's own sub-ledger."""
        reasons = []
        try:
            dd = float(getattr(ledger_view, "drawdown", 0.0) or 0.0)
        except Exception:
            return RiskVerdict(OK, ["ledger drawdown unreadable; no action"])

        kill_dd = float(self.risk.get("kill_drawdown", 0.25))
        halve_dd = float(self.risk.get("halve_drawdown", 0.15))
        if abs(dd) >= kill_dd:
            reasons.append(f"drawdown {dd:.1%} breached kill {kill_dd:.0%}")
            # observe-only (standing instruction 2026-07-31): report, never halt
            return RiskVerdict(OK, ["WATCH (would have KILLed): " + r for r in reasons])
        if abs(dd) >= halve_dd:
            reasons.append(f"drawdown {dd:.1%} breached halve {halve_dd:.0%}")
            return RiskVerdict(OK, ["WATCH (would have HALVEd): " + r for r in reasons])
        return RiskVerdict(OK, [f"drawdown {dd:.1%} within limits"])
