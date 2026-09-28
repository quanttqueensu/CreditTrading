> **ARCHIVED 2026-09-28 — not evidence of current state.** Was `~/prod/QUANTT/ops/halts/HALT_benchmarks_paper_20260910_102248.md`.
> Now owned by: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` (IBKR retired 2026-09-28; this is the prod tree's state that day). Numbers: `python3 -m ops.orient`.

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
