> **ARCHIVED 2026-09-28 — not evidence of current state.** Was `~/prod/QUANTT/README.md`.
> Now owned by: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` (IBKR retired 2026-09-28; this is the prod tree's state that day). Numbers: `python3 -m ops.orient`.

> **ARCHIVED 2026-09-28 — not evidence of current state.** Snapshot of the untracked and modified live state in `~/prod/QUANTT` (worktree detached at `v2026.09.13.4`) on the day IBKR was retired.
> Now owned by: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md`. Numbers: `python3 -m ops.orient`.

# Prod state at IBKR retirement

Copied 2026-09-28 because it is the only copy of the 2026-09-14/15 desync
evidence and of every session log since the W3 go-live, and prod is being
dismantled. Excluded on purpose: `config/` (credentials) and `data/` (a symlink
to dev's panels).

| path here | was in prod |
|---|---|
| `ops/books/` | `ops/books/` — the IBKR shadow ledgers, order maps, `_desync/` records, `_broker_archive/` post-close verdicts, dry runs |
| `ops/schedule_logs/` | `ops/schedule/logs/` — one log per job per day |
| `ops/HALT_*.md` | the three scoped halts active at retirement (cef_discount_paper, benchmarks_paper, phase0_null) — never cleared; IBKR was abandoned with them in force |
| `ops/heartbeat.json`, `ops/halts/`, `ops/reports/` | as named |

Scanned for credentials before adding: the only match was a doctor message
saying SMTP was not configured.
