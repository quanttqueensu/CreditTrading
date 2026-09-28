# HALT — benchmarks_paper

`ops/preflight.py` reads this file before every session of **benchmarks_paper** and will not arm live orders for it while this file exists. Other books see it as a WARNING and continue: an arming failure is about the symbols the failing book trades, and one book's bookkeeping must not stop another's strategy. Data collection and logging continue regardless.

Most recent halt first.

---

## 2026-09-14 17:25:10  shadow ledger desync in bench_b3_agg @ 2026-09-14

- **source**: `ibkr.place_targets`
- **state**: trading is BLOCKED for **benchmarks_paper** until this file is cleared (other books are warned, not blocked)

UnbookedExecution('2026-09-14: the broker reports 1 execution(s) that no ledger order accounts for (00012ec5.6b7cff97.01.01). The ledger cannot represent them, and booking the day without them would understate the position permanently. Reconcile with `python3 -m ops.reconcile_orders` and repair before advancing.')

0 fill(s) were transmitted to the broker but NOT recorded in the shadow sub-ledger. The ledger now understates the account. Rebuild it from /Users/simonjarvis/prod/QUANTT/ops/books/benchmarks_live/_ibkr_shadow/_desync/bench_b3_agg_2026-09-14.json (and the broker's execution history) and confirm broker.arm() returns ok before re-arming.

Traceback (most recent call last):
  File "/Users/simonjarvis/prod/QUANTT/src/deploy/broker/ibkr.py", line 1315, in place_targets
    self._shadow().place_targets(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        sleeve_name, targets, asof, market_state,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        execution_record=self._execution_record(sleeve_name, asof))
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/simonjarvis/prod/QUANTT/src/deploy/broker/simulator.py", line 134, in place_targets
    lg.advance(prices, cfg["run_spec"], cfg["costs"], target_fn,
    ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
               through=asof, start=start, verbose=self.verbose)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/simonjarvis/prod/QUANTT/ops/ledger.py", line 502, in advance
    raise UnbookedExecution(
    ...<7 lines>...
        f"repair before advancing.")
ops.ledger.UnbookedExecution: 2026-09-14: the broker reports 1 execution(s) that no ledger order accounts for (00012ec5.6b7cff97.01.01). The ledger cannot represent them, and booking the day without them would understate the position permanently. Reconcile with `python3 -m ops.reconcile_orders` and repair before advancing.

To clear once the cause is genuinely fixed:

    python3 -c "from ops.halt import clear_halt; clear_halt('what you fixed', book='benchmarks_paper')"

---

