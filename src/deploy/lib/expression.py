"""Expression registry (H3): signal -> {ETF | FUTURES} PositionTarget rewrite.

REFINE_ARCHITECTURE.md §2.3. A sleeve emits its ETF PositionTargets VERBATIM
(the frozen v1 signal); ``Expression.rewrite`` swaps only the instrument when
the v2 book spec says so:

    book_v2.json sleeve block:  {"expression": {"mode": "FUTURES",
                                                "instrument": "ZN"}}

Frozen mapping (REFINE_PREREG H3): EOM IEF -> ZN; FOMC IEF -> ZN (1 contract);
overlay short IEF -> ZN or ZF (spec-chosen, DV01-matched). The credit base and
short-vol sleeves are never rewritten (ETF/option only). ``mode: "ETF"`` (or
no expression block) returns the targets UNCHANGED — the A/B null leg is one
flag.

The rewrite is stateless and per-target: it cannot change WHICH days a sleeve
is long/flat (the frozen signal), only the instrument that expresses it.
"""

from __future__ import annotations

import pandas as pd

from ..sleeve import FLAT, FUTURES, LONG, SHORT, PositionTarget
from .futures import (ETF_DURATION_YEARS, FuturesInstrument, duration_to_contracts,
                      etf_target_dv01, load_futures_specs)

# Only these source instruments are duration legs eligible for rewrite; a
# sleeve's non-duration legs (LQD credit leg, BIL cash, option legs) always
# pass through untouched.
REWRITABLE_ETFS = tuple(ETF_DURATION_YEARS)


class Expression:
    """Per-sleeve expression switch.

    ``config`` maps sleeve_name -> {"mode": "ETF"|"FUTURES",
    "instrument": "ZN"|"ZF"|"ZB", ["source": "IEF"]}. Unlisted sleeves and
    mode=="ETF" are identity. ``specs`` defaults to the frozen
    ``config/futures_specs.yaml`` table.
    """

    def __init__(self, config: dict | None = None,
                 specs: dict[str, FuturesInstrument] | None = None):
        self.config = dict(config or {})
        self.specs = specs or load_futures_specs()

    # -- helpers -----------------------------------------------------------

    def _sleeve_conf(self, sleeve_name: str) -> dict | None:
        c = self.config.get(sleeve_name)
        if not c or str(c.get("mode", "ETF")).upper() != "FUTURES":
            return None
        code = c.get("instrument")
        if code not in self.specs:
            raise KeyError(
                f"expression for {sleeve_name!r} names instrument {code!r} "
                f"not in the frozen contract table {sorted(self.specs)}")
        return {"instrument": code, "source": c.get("source", "IEF")}

    @staticmethod
    def _last_close(market_state, ticker: str) -> float | None:
        prices = getattr(market_state, "prices", None)
        if prices is None or len(prices) == 0:
            return None
        df = prices[prices["ticker"] == ticker]
        if df.empty or "close" not in df.columns:
            return None
        s = df.sort_values("date")["close"].dropna()
        return float(s.iloc[-1]) if len(s) else None

    # -- the rewrite -------------------------------------------------------

    def rewrite(self, sleeve_name: str, targets: list[PositionTarget], asof,
                capital_usd: float, market_state) -> list[PositionTarget]:
        """Rewrite the sleeve's duration-ETF targets to DV01-matched futures
        targets; everything else (and mode=ETF) passes through unchanged."""
        conf = self._sleeve_conf(sleeve_name)
        if conf is None:
            return targets

        inst = self.specs[conf["instrument"]]
        source = conf["source"]
        out = []
        for t in targets:
            if t.instrument != source or t.kind != "ETF":
                out.append(t)               # non-duration legs pass through
                continue
            if t.side == FLAT:
                out.append(PositionTarget(
                    instrument=inst.code, side=FLAT, kind=FUTURES, qty=0.0,
                    reason=f"[{source}->{inst.code}] {t.reason}",
                    meta={"expressed_from": source, "sleeve": sleeve_name}))
                continue

            # Resolve the ETF-notional the frozen signal asked for.
            if t.weight is not None:
                notional = abs(float(t.weight)) * float(capital_usd)
            else:
                px = self._last_close(market_state, source)
                if px is None or not px > 0:
                    raise ValueError(
                        f"cannot resolve {source} notional for {sleeve_name} on "
                        f"{pd.Timestamp(asof).date()}: qty-expressed target but "
                        f"no {source} close in market_state.prices")
                notional = abs(float(t.qty)) * px

            dv01 = etf_target_dv01(notional, source)
            n = duration_to_contracts(1.0, capital_usd, dv01, inst, source)
            resid = dv01 - n * inst.dv01_per_contract
            reason = (f"[{source}->{inst.code}] DV01 ${dv01:,.0f}/bp -> "
                      f"{n} x {inst.code} (dv01/ct ${inst.dv01_per_contract:.0f}, "
                      f"residual ${resid:+,.0f}/bp NOT traded) | {t.reason}")
            meta = {"expressed_from": source, "sleeve": sleeve_name,
                    "multiplier": inst.multiplier,
                    "initial_margin_usd": inst.initial_margin_usd,
                    "target_dv01_usd": dv01, "residual_dv01_usd": resid}
            if n == 0:
                out.append(PositionTarget(
                    instrument=inst.code, side=FLAT, kind=FUTURES, qty=0.0,
                    reason=("GRANULARITY: target rounds to 0 contracts — "
                            + reason),
                    meta=meta))
                continue
            side = SHORT if t.side == SHORT else LONG
            qty = float(-n if side == SHORT else n)
            out.append(PositionTarget(
                instrument=inst.code, side=side, kind=FUTURES, qty=qty,
                reason=reason, combo_id=t.combo_id, meta=meta))
        return out
