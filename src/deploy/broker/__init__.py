"""Broker abstraction: the single seam the orchestrator talks to.

`EXECUTION={simulator|ibkr}` selects the implementation. The sleeve produces
`PositionTarget`s; the broker turns the desired book into fills and reports
positions/cash back. `ib_insync` is imported ONLY inside `IBKRBroker.connect()`,
so importing this package (or running the simulator) needs no broker SDK.
"""

from .base import Broker, Fill, AccountSnapshot
from .simulator import Simulator, DryRunBroker

__all__ = ["Broker", "Fill", "AccountSnapshot", "Simulator", "DryRunBroker",
           "make_broker"]


def make_broker(execution, **kwargs):
    """Factory: 'simulator' -> Simulator, 'ibkr' -> IBKRBroker (lazy import of
    the adapter module so the simulator path never touches ib_insync)."""
    execution = (execution or "simulator").lower()
    if execution == "simulator":
        return Simulator(**kwargs)
    if execution == "ibkr":
        from .ibkr import IBKRBroker
        return IBKRBroker(**kwargs)
    raise ValueError(f"unknown EXECUTION {execution!r} (use 'simulator' or 'ibkr')")
