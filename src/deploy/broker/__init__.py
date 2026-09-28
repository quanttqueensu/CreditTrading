"""Broker abstraction: the single seam the orchestrator talks to.

`EXECUTION=simulator` selects the only implementation left here. The sleeve
produces `PositionTarget`s; the broker turns the desired book into fills and
reports positions/cash back.

IBKR RETIRED 2026-09-28 (team lead; results/ops/ALPACA_MIGRATION_MANIFEST_
2026-09-28.md). `IBKRBroker` is at `_archive/src/deploy/broker/ibkr.py` and is
never imported. The Alpaca broker is being built in the `quantt/` package.
"""

from .base import Broker, Fill, AccountSnapshot
from .simulator import Simulator, DryRunBroker

__all__ = ["Broker", "Fill", "AccountSnapshot", "Simulator", "DryRunBroker",
           "make_broker"]


def make_broker(execution, **kwargs):
    """Factory: 'simulator' -> Simulator. 'ibkr' raises: that broker is archived,
    and a stale `EXECUTION=ibkr` must fail loudly, never fall back to the
    simulator and report modelled fills as if they were the broker's."""
    execution = (execution or "simulator").lower()
    if execution == "simulator":
        return Simulator(**kwargs)
    if execution == "ibkr":
        raise ValueError("EXECUTION=ibkr: the IBKR broker was retired 2026-09-28 "
                         "(_archive/src/deploy/broker/ibkr.py). Nothing replaces it here.")
    raise ValueError(f"unknown EXECUTION {execution!r} (use 'simulator')")
