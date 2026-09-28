> **ARCHIVED 2026-09-28 — not evidence of current state.** Was `~/prod/QUANTT/ops/reports/weekly_book_2026-08-28.md`.
> Now owned by: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` (IBKR retired 2026-09-28; this is the prod tree's state that day). Numbers: `python3 -m ops.orient`.

# Weekly book report — week ending 2026-08-28

Book `?` — read-only roll-up of the daily runs (window 2026-08-22..2026-08-28).

## Sleeves

| sleeve | last asof | NAV | week PnL | since-inception PnL | N days | note |
|---|---|---:|---:|---:|---:|---|

**The book has not advanced yet** — no sub-ledger has a nav.csv. If the scheduler is in DRY_RUN=1 (the shipped default) this is expected: dry runs log targets without writing ledgers.

## Book rollup (last daily run)

- no book_status.json yet (no non-dry run has completed).

## Monitor (Gate S / staleness)

- no book_monitor.json yet.

## Dry-run activity this week

- none in 2026-08-22..2026-08-28.
