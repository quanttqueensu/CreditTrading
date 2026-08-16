"""Concrete sleeves. Importing this package registers each one with the registry.

`registry.build_sleeve` imports this module inside a try/except, so a sleeve that
fails to import degrades to the registry's clear "not implemented" error rather
than breaking the whole orchestrator.
"""

from . import credit_rv    # noqa: F401  (registers CreditRVSleeve)
from . import null_trader  # noqa: F401  (registers NullTraderSleeve — Phase 0)

__all__ = ["credit_rv", "null_trader"]
from . import static_weights  # noqa: F401,E402
from . import cef_discount   # noqa: F401  (registers CEFDiscountSleeve)
