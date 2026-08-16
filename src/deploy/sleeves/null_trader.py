"""Phase 0 null trader — the workflow's mandatory first deployment.

`credit_rv_agent_workflow.md` §9 Phase 0:

    Build the DB, the IBKR connection, the order/execution/reconciliation path,
    and a random-signal trader that trades at the real strategy's cadence and
    size. Artifact: 20 sessions of the null trader with clean reconciliation,
    realistic slippage logs, and a P&L series statistically indistinguishable
    from zero minus costs. *If the null trader makes money, your fill logic or
    your P&L accounting is wrong. Fix it before writing a single signal.*

WHY THIS IS THE RIGHT THING TO DEPLOY NOW
-----------------------------------------
Two independent credit signals have now failed out of sample (credit_rv holdout
Sharpe -1.44 with NEGATIVE gross edge; E1 premium/discount OOS negative in both
its continuous and banded forms). We do not have a validated edge to route
capital against.

What we have never validated is the machinery itself. Every future strategy's
measured P&L flows through this exact path — target -> order -> fill -> ledger ->
attribution. If that path flatters fills by even a basis point, every subsequent
backtest-to-live comparison is corrupted and we would not know. The null trader
is the control experiment that settles it, and it is completely signal-agnostic:
its value does not depend on any edge existing.

Expected result: net P&L ≈ -(costs), i.e. it should lose almost exactly the
spread it crosses. Anything better than that is a bug in our favour and must be
found before it silently inflates a real strategy's numbers.

DETERMINISM
-----------
The "random" signal is a deterministic hash of (date, instrument, seed), so a
given day's book is exactly reproducible from the spec — a requirement of
workflow §1.4. It is random *across* names and days, but never random between
two runs of the same day.
"""
from __future__ import annotations

import hashlib

import numpy as np

from ..registry import register
from ..sleeve import ETF, FLAT, LONG, OK, SHORT, HALVE, KILL
from ..sleeve import MarketState, PositionTarget, RiskVerdict, Sleeve


def _unit_hash(*parts) -> float:
    """Deterministic uniform(-1, 1) from the given parts."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    # first 8 bytes -> [0,1) -> [-1,1)
    u = int.from_bytes(h[:8], "big") / float(1 << 64)
    return 2.0 * u - 1.0


@register
class NullTraderSleeve(Sleeve):
    """Random, dollar-neutral, unit-gross book at a configured turnover."""

    alloc_type = "null_trader"

    def instruments(self) -> list[str]:
        return sorted(self.frozen.get("universe", []))

    def history_warmup_trading_days(self) -> int:
        # needs no history — it is deliberately signal-free. A small window is
        # kept only so the executor has prices to size against.
        return int(self.frozen.get("warmup_days", 10))

    def target_positions(self, asof, market_state: MarketState) -> list[PositionTarget]:
        uni = list(self.frozen.get("universe", []))
        if not uni:
            return []
        seed = self.frozen.get("seed", "phase0")
        gross = float(self.frozen.get("gross_leverage", 1.0))
        min_w = float(self.frozen.get("min_abs_weight", 0.005))

        # A fresh draw every `rebalance_days` so the cadence matches the real
        # strategy's holding period rather than churning daily.
        reb = max(1, int(self.frozen.get("rebalance_days", 1)))
        epoch = np.datetime64(asof, "D").astype(int) // reb

        raw = np.array([_unit_hash(seed, epoch, t) for t in uni], dtype=float)
        n0 = np.abs(raw - raw.mean()).sum()
        if n0 < 1e-12:
            return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                   reason="null: degenerate draw") for t in uni]
        # Drop sub-threshold names FIRST, then re-neutralise and re-normalise on
        # the survivors. Filtering after neutralising would leave a small net
        # directional position, which in a control experiment is noise that
        # cannot be distinguished from a fill-logic error.
        w = (raw - raw.mean()) / n0 * gross
        keep = np.abs(w) >= min_w
        if keep.sum() < 2:
            return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                   reason="null: too few names above min weight")
                    for t in uni]
        w = np.where(keep, raw, np.nan)
        w = w - np.nanmean(w)
        w = np.nan_to_num(w, nan=0.0)
        w = w / np.abs(w).sum() * gross

        out = []
        for t, wt in zip(uni, w):
            if wt == 0.0:
                out.append(PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                          reason="null: below min weight"))
                continue
            out.append(PositionTarget(
                instrument=t,
                side=LONG if wt > 0 else SHORT,
                kind=ETF,
                weight=float(wt),
                reason=f"null trader (epoch {epoch}) w={wt:+.4f}",
            ))
        return out

    def risk_check(self, ledger_view) -> RiskVerdict:
        """OBSERVE-ONLY (standing instruction 2026-07-31). The null trader is a
        control experiment and is EXPECTED to bleed the spread; killing it on
        drawdown would end the slippage measurement it exists to produce."""
        try:
            dd = float(getattr(ledger_view, "drawdown", 0.0) or 0.0)
        except Exception:
            return RiskVerdict(OK, ["ledger drawdown unreadable; no action"])
        if abs(dd) >= 0.10:
            return RiskVerdict(OK, [
                f"WATCH: null trader drawdown {dd:.1%}. It is SUPPOSED to lose "
                f"its costs, so this is informative rather than alarming. "
                f"Observe-only: NOT halted."])
        return RiskVerdict(OK, [f"null trader drawdown {dd:.1%}"])
