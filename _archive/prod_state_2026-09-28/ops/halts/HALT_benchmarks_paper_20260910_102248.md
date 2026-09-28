# HALT — benchmarks_paper

`ops/preflight.py` reads this file before every session of **benchmarks_paper** and will not arm live orders for it while this file exists. Other books see it as a WARNING and continue: an arming failure is about the symbols the failing book trades, and one book's bookkeeping must not stop another's strategy. Data collection and logging continue regardless.

Most recent halt first.

---

## 2026-09-10 10:22:47  DRILL — bench_b6 could not attribute ANGL

- **source**: `drill`
- **state**: trading is BLOCKED for **benchmarks_paper** until this file is cleared (other books are warned, not blocked)

simulated replay of 2026-09-09 17:25

To clear once the cause is genuinely fixed:

    python3 -c "from ops.halt import clear_halt; clear_halt('what you fixed', book='benchmarks_paper')"

---



CLEARED 2026-09-10 10:22:48: drill over
