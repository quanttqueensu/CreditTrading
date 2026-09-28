"""Concrete sleeves. Importing this package registers each one with the registry.

Since the 2026-09-28 clean slate: the CEF strategy and the static-weights
benchmark (b6) only.
"""

from . import static_weights  # noqa: F401  (registers StaticWeightsSleeve)
from . import cef_discount    # noqa: F401  (registers CEFDiscountSleeve)
