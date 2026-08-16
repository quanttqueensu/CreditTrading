"""The sleeve interface — the one contract every strategy in the book obeys.

A sleeve is deterministic and frozen-param. Given a date and a `MarketState`
(prices deep enough for its warmup, its OWN sub-ledger holdings, and — for
options — mark/greeks callbacks) it emits a **target book** for `asof`: the
list of `PositionTarget`s the executor must make true by trading at the NEXT
close. The executor diffs the target against holdings and trades the delta;
the sleeve never places an order itself and never sees a sibling sleeve's book.

Every number a sleeve uses comes from its `frozen_spec.json` (`spec["frozen"]`
/ `spec["risk"]`). This file invents no parameters — it only defines the shape.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

# Risk-check verdict vocabulary, shared with risk.py and portfolio.py.
OK, HALVE, KILL = "OK", "HALVE", "KILL"

# Position sides and instrument kinds.
LONG, SHORT, FLAT = "LONG", "SHORT", "FLAT"
ETF, EQUITY, OPTION = "ETF", "EQUITY", "OPTION"
# FUTURES added 2026-07-21 (REFINE_ARCHITECTURE.md §0.2 Edit 1 — the ONE
# enumerated additive whitelist widen). No v1 sleeve constructs a FUTURES
# target; every v1 branch keyed on ETF/EQUITY/OPTION is untouched. v2's
# expression layer (src/deploy/v2/expression.py) is the only producer.
FUTURES = "FUTURES"


@dataclass(frozen=True)
class PositionTarget:
    """One line of a sleeve's desired book for `asof`.

    Exactly one of `qty` / `weight` is set (XOR). `qty` is a SIGNED target
    quantity (shares or contracts); `weight` is a fraction of THIS sleeve's
    capital. Legs sharing a `combo_id` fill atomically (a straddle's two legs).
    `meta` carries the option descriptors (underlier/expiry/strike/opt_type/
    multiplier) the derivatives ledger needs.
    """

    instrument: str
    side: str                      # LONG | SHORT | FLAT
    kind: str = ETF                # ETF | EQUITY | OPTION | FUTURES
    qty: float | None = None       # signed target qty (shares/contracts); XOR weight
    weight: float | None = None    # target weight of THIS sleeve's capital; XOR qty
    reason: str = ""               # persisted to orders.csv
    combo_id: str | None = None    # legs sharing this fill atomically
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.side not in (LONG, SHORT, FLAT):
            raise ValueError(f"PositionTarget.side must be LONG/SHORT/FLAT, got {self.side!r}")
        if self.kind not in (ETF, EQUITY, OPTION, FUTURES):
            raise ValueError(
                f"PositionTarget.kind must be ETF/EQUITY/OPTION/FUTURES, got {self.kind!r}")
        has_qty = self.qty is not None
        has_w = self.weight is not None
        if self.side == FLAT:
            # FLAT means "hold nothing"; a stray qty/weight would be ambiguous.
            if has_qty and float(self.qty) != 0.0:
                raise ValueError("FLAT target must not carry a non-zero qty")
            if has_w and float(self.weight) != 0.0:
                raise ValueError("FLAT target must not carry a non-zero weight")
            return
        if has_qty == has_w:
            raise ValueError(
                f"PositionTarget for {self.instrument!r} must set exactly one of "
                f"qty / weight (got qty={self.qty}, weight={self.weight})")
        # Sign sanity: a LONG cannot carry a negative qty, a SHORT a positive one.
        if has_qty:
            q = float(self.qty)
            if self.side == LONG and q < 0:
                raise ValueError(f"LONG {self.instrument} has negative qty {q}")
            if self.side == SHORT and q > 0:
                raise ValueError(f"SHORT {self.instrument} has positive qty {q}")

    def signed_qty(self) -> float | None:
        """The qty with its side sign applied, or None if weight-expressed."""
        if self.qty is None:
            return None
        q = abs(float(self.qty))
        return -q if self.side == SHORT else (0.0 if self.side == FLAT else q)


@dataclass
class LegGreeks:
    """Everything the delta hedge / rate-beta needs for one leg, in one object.

    `price` is the mark (same number `mark_fn` returns). `delta` is per-leg
    dPrice/dUnderlier (forward Black delta for an option). The forward inputs
    (F, K, T, sigma, df) are exposed so the short-vol sleeve can re-derive the
    net straddle delta exactly as `scripts/vrp/c2b_sleeve.run_cycle` does.
    """

    price: float
    delta: float | None = None
    F: float | None = None
    K: float | None = None
    T: float | None = None
    sigma: float | None = None
    df: float | None = None


@dataclass
class MarketState:
    """What a sleeve is handed on `asof`.

    `prices` is the ops tidy price store (columns date/ticker/close/dividend/
    volume/...), guaranteed at least `sleeve.history_warmup_trading_days()`
    bars deep before `asof`. `holdings` is THIS sleeve's own sub-ledger signed
    positions (option legs keyed by leg-id) — never a sibling's. `mark_fn` and
    `greeks_fn` are the ONLY option-math seam (short-vol / overlay); both return
    None beyond the last available mark so the sleeve reports INSUFFICIENT_MARKS
    rather than inventing a price.
    """

    asof: pd.Timestamp
    prices: pd.DataFrame
    holdings: dict = field(default_factory=dict)
    mark_fn: "callable | None" = None
    greeks_fn: "callable | None" = None
    events: "pd.DataFrame | None" = None
    extras: dict = field(default_factory=dict)


@dataclass
class RiskVerdict:
    """A sleeve's self-grade for the current run. `status` is OK/HALVE/KILL."""

    status: str
    reasons: list = field(default_factory=list)

    def __post_init__(self):
        if self.status not in (OK, HALVE, KILL):
            raise ValueError(f"RiskVerdict.status must be OK/HALVE/KILL, got {self.status!r}")


class Sleeve(ABC):
    """Base class for every sleeve. Concrete sleeves live in src/deploy/sleeves/.

    A subclass sets the class attribute `alloc_type` (matching
    `allocation.type`), declares its instruments and warmup depth, emits a
    target book from `target_positions`, and self-grades via `risk_check`.
    """

    alloc_type: str = ""

    def __init__(self, spec: dict, capital_usd: float):
        self.spec = spec
        self.capital_usd = float(capital_usd)
        self.frozen = spec.get("frozen", {})    # read-only frozen params
        self.risk = spec.get("risk", {})        # kill/halve criteria

    @abstractmethod
    def instruments(self) -> list[str]:
        """Tickers / underliers to keep priced for this sleeve."""

    def history_warmup_trading_days(self) -> int:
        """How many TRADING-day bars of history must precede `asof` in
        `market_state.prices`. Calendar-only sleeves return 0; the rate-beta
        overlay returns 63 + buffer."""
        return 0

    @abstractmethod
    def target_positions(self, asof, market_state: MarketState) -> list[PositionTarget]:
        """The desired book for `asof` — what the executor must make true by
        trading at the next close (T+1 fill convention). Diffs vs holdings are
        the executor's job."""

    @abstractmethod
    def risk_check(self, ledger_view) -> RiskVerdict:
        """Read the sub-ledger's nav/dd/returns and return OK/HALVE/KILL."""
