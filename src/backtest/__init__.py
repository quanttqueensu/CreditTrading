"""QUANTT backtest harness (Phase 2) — the common machinery every strategy
in Phases 3-6 runs through.

Modules
-------
engine       daily vectorized backtest: T+1 execution, costs from
             config/costs.yaml, cash at the risk-free rate.
guard        look-ahead protection: assert_lagged (hard check the engine
             runs) and shift_test (the delayed-signal artifact test).
tearsheet    the standard metric set + Markdown rendering. Every strategy
             reports the same numbers the same way.
walkforward  expanding-window runner. Parameters are fitted on truncated
             history and applied strictly after their fit window.

Typical use
-----------
    from src.backtest import engine, guard, tearsheet as ts

    costs = engine.load_costs()
    rets, rf = engine.load_panel(tickers=["HYG", "BIL"])
    weights = ...                                   # row t uses data <= t
    info = pd.Series(weights.index, index=weights.index)

    res = engine.run_backtest(weights, rets, costs, rf=rf, info_dates=info)
    print(ts.to_markdown(ts.tearsheet(res)))
    guard.shift_test(weights, rets, costs, rf=rf, info_dates=info)

Note on the namespace: this package deliberately exposes the four SUBMODULES
rather than re-exporting their functions flat. ``tearsheet`` is both a module
and its main function, so a flat re-export would shadow the module and break
the documented ``from src.backtest import tearsheet as ts`` idiom. Always
reach through the module (``engine.run_backtest``, ``ts.tearsheet``); it also
makes provenance obvious when a call is quoted in a results memo.

House rules enforced here (BUILD_PLAN.md / PREREGISTRATION.md): costs come
from config, never hardcoded; walk-forward only; every output prints its
sample start/end and N.
"""

from . import engine, guard, tearsheet, walkforward

__all__ = ["engine", "guard", "tearsheet", "walkforward"]
