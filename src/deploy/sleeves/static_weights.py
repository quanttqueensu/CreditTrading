"""Static-weight benchmark books.

WHY THESE EXIST. Every strategy needs something to be measured against, and the
comparison is only honest if the benchmark is filled and accounted exactly the
way the strategy is. A benchmark that gets free fills makes any strategy look
good. So these route through the identical target -> order -> fill -> ledger path
as any signal sleeve; the only difference is that the weights are constant.

WHAT THEY ARE NOT. None of these is an alpha claim. They are the "zero skill"
reference: owning high yield, owning the bond market, owning 60/40, holding cash,
holding every credit ETF equally. If a strategy cannot beat these after costs it
has not earned its capital.

The three benchmarks that carry the most information -- duration-hedged HY carry,
the naive pair z-score and the naive raw premium/discount -- all need a SHORT leg,
which `static_weights` deliberately forbids (it does not borrow). Those continue
as shadow books under results/bench/ and are reported alongside these.
"""
from __future__ import annotations

from ..registry import register
from ..sleeve import ETF, FLAT, LONG, OK, KILL
from ..sleeve import MarketState, PositionTarget, RiskVerdict, Sleeve


@register
class StaticWeightsSleeve(Sleeve):
    """Constant long-only weights, rebalanced on a fixed cadence."""

    alloc_type = "static_weights"

    def _weights(self) -> dict[str, float]:
        return dict(self.spec.get("allocation", {}).get("weights", {}))

    def instruments(self) -> list[str]:
        return sorted(self._weights())

    def history_warmup_trading_days(self) -> int:
        # No signal to warm up. A short window is kept only so the executor has
        # prices to size against.
        return int(self.frozen.get("warmup_days", 5))

    def target_positions(self, asof, market_state: MarketState) -> list[PositionTarget]:
        w = self._weights()
        if not w:
            return []
        out = []
        for tk in sorted(w):
            wt = float(w[tk])
            if wt <= 0.0:
                out.append(PositionTarget(instrument=tk, side=FLAT, kind=ETF,
                                          reason="benchmark: zero weight"))
                continue
            out.append(PositionTarget(
                instrument=tk, side=LONG, kind=ETF, weight=wt,
                reason=f"benchmark static weight {wt:.4f}"))
        return out

    def risk_check(self, ledger_view) -> RiskVerdict:
        """OBSERVE-ONLY (standing instruction 2026-07-31). A benchmark that
        suspends itself stops being a benchmark -- the whole point is an
        unbroken reference series through every market it encounters."""
        try:
            dd = float(getattr(ledger_view, "drawdown", 0.0) or 0.0)
        except Exception:
            return RiskVerdict(OK, ["ledger drawdown unreadable; no action"])
        if abs(dd) >= 0.35:
            return RiskVerdict(OK, [
                f"WATCH: benchmark drawdown {dd:.1%}. Observe-only: NOT halted."])
        return RiskVerdict(OK, [f"benchmark drawdown {dd:.1%}"])
