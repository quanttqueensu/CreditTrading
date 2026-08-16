"""The Broker base class and the value types that cross it.

The orchestrator holds one Broker for the whole book. Because the book is N
independent sub-ledgers (§3), every method is sleeve-scoped: `sleeve_name`
selects which sub-account/sub-ledger the call refers to. The Simulator keeps
one local sub-ledger per sleeve; the IBKR adapter maps sleeve_name onto tagged
positions inside one paper account (documented in ibkr.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Fill:
    """One executed trade the broker reports back."""

    instrument: str
    side: str                 # BUY | SELL
    qty: float
    price: float
    cost_usd: float
    asof: object
    reason: str = ""
    combo_id: object = None
    kind: str = "ETF"


@dataclass
class AccountSnapshot:
    """A sleeve's marked-to-market state after a day is booked."""

    cash: float
    positions: dict           # instrument -> signed qty
    nav: float
    asof: object
    financing_usd: float = 0.0
    extras: dict = field(default_factory=dict)


class Broker(ABC):
    """The seam the orchestrator trades through. All methods sleeve-scoped."""

    @abstractmethod
    def sync_positions(self, sleeve_name) -> dict:
        """Current signed positions for `sleeve_name` (instrument -> qty)."""

    @abstractmethod
    def cash(self, sleeve_name) -> float:
        """Current cash balance for `sleeve_name`."""

    @abstractmethod
    def place_targets(self, sleeve_name, targets, asof, market_state) -> list:
        """Make `targets` true for `sleeve_name` by trading the delta vs held,
        advancing the sleeve's book one day to `asof`. Returns list[Fill]."""

    @abstractmethod
    def snapshot(self, sleeve_name, asof, market_state) -> AccountSnapshot:
        """Mark-to-market snapshot for `sleeve_name` as of `asof`."""
