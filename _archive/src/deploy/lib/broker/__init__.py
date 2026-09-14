"""v2 broker package: the MarginBroker (simulator twin of IBKR's single
portfolio-margin account). `ib_insync` is never imported here; an
`EXECUTION=ibkr` v2 run reuses the v1 IBKRBroker (already one paper account,
natively portfolio-margined), lazy-imported by the v1 factory."""

from .margin_broker import MarginBroker

__all__ = ["MarginBroker"]
