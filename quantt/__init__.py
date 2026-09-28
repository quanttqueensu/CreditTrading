"""QUANTT on Alpaca: the fresh run package that replaces the IBKR-era `src/deploy`
live path and `ops/` run tooling.

Decided by the team lead 2026-09-28: flatten and archive everything IBKR, build
a fresh package that REUSES parts (the CEF sleeve, the frozen-spec machinery, the
research harness, the price/NAV fetchers) rather than extending the old live
path, one Alpaca paper account per book, prod on a cloud VM. The old code is
tagged `ibkr-final`.

Nothing in this package may open a network connection at import time: its tests
are collected by pytest (see `pytest.ini`) and run under `ops.netguard`.
"""
