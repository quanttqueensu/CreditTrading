# Alpaca migration — decisions, archive manifest, and what is left (2026-09-28)

**What this is.** The dated record of the team lead's decision to retire IBKR and
move QUANTT to Alpaca paper, the inventory of what the IBKR era leaves behind and
where each piece goes, and the human-only steps. True as of its date; the code
state it describes is on branch `alpaca-migration`, cut from `main` at
`db795a9`, which is tagged **`ibkr-final`**.

Inventory method: `git ls-files` (634 tracked files outside `data/` and
`_archive/`) grepped for IBKR and old-infrastructure terms, read-only, no module
imported. File:line evidence for every row is in the session that produced this
note; re-run the grep before acting on a row, because the tree moves.

---

## 1. Why now — the state measured this morning

`python3 -m ops.orient` and `python3 -m ops.doctor --quick`, 2026-09-28 ~11:00 ET:

- Last broker-confirmed fill 2026-09-15 [V]. Every session since has failed.
- **Dev moved** from `~/Desktop/2027/QUANTT/2027` to its current path. Prod's
  `.git` file and its `data` symlink still point at the Desktop path, which no
  longer exists [V] — so prod cannot see its repo or its prices (preflight:
  `MISSING cef_prices.parquet`).
- IB Gateway refused `127.0.0.1:4002` at 08:30 [V]; IBC is not installed; the
  `com.quantt.ibgateway` job last exited 78 [V].
- Three scoped halts active in prod: `cef_discount_paper`, `benchmarks_paper`,
  `phase0_null` [V].
- Laptop on battery, so sessions sleep [V].

## 2. Decisions (team lead, 2026-09-28, answered interactively)

| question | decision |
|---|---|
| Why Alpaca | Our own choice, not a competition requirement. |
| IBKR | **Flatten everything, archive all IBKR infrastructure, forget it.** |
| New system | **Fresh package, reusing parts** — not main's `src/deploy` extended, not `ng/` merged whole. |
| Books | **CEF strategy + b6 equal-weight credit benchmark.** phase0/null trader, b1/b3/b4/b5 and credit_rv retire. |
| Accounts | **One Alpaca paper account per book.** |
| Scoring | **Record both**: Alpaca paper fills are the official record; P&L at the official closing-auction print is logged beside it, labelled. D19/D20 (gross P&L only) stand. |
| Hosting | **Cloud VM.** Dev stays at its current path. |
| Alerting | **Dashboard and logs only** — hardening D3/D4 (2026-09-21) stand on the VM. |
| CEF trial counter | **48** (main) is authoritative; nextgen's 53–56 were shadow research. |
| Spec | **v7 from day one on Alpaca**, superseding hardening D14 ("v7 parked until 20 clean sessions"). New pre-registration + `/spec-change`; counter 48 → 49 in that commit. |
| `max_gross_stress` | **Re-derive on Alpaca** with the 2026-09-16 pre-registered rule; its 1.90 came from the IBKR-Canada account. Key stays off until then. |
| Capital | **$100k default** per paper account; capital and `min_trade_usd` re-sized through `/spec-change`. |

Standing and not re-decided: hardening D15 — agents never edit `CLAUDE.md`; they
draft a diff and the team lead applies it.

## 3. Done on `alpaca-migration` (2026-09-28)

| commit | what |
|---|---|
| merge `docs-cleanup` | `results/ops/LEDGER_NOOP_MORNING_2026-09-15.md` |
| merge `hardening-20260921` | root `conftest.py` safety harness, `ops/netguard.py`, `ops/session_rc.py`, hardening records |
| `6217c96` | v7 constraint **code** ported from `nextgen-20260914`, keys off. No-op proved: 250 dates, 8,500 target lines, byte-identical to `ibkr-final` (sha256 `c216f3be…`). |
| `3bca91d` | `quantt/` package + read-only paper probe (`quantt/broker/alpaca_probe.py`), 10 tests, 5 mutations caught |

Also: `git worktree prune` removed the records of four worktrees whose folders
were gone (their branches are intact).

Test suite after the merges: the only failures are launchd/schedule-clock tests
(`test_decision_age_clock.py` ×8) that read the installed plists and
`ops/schedule/*.env`; main fails a different subset of the same family
(`test_stuck_session_guard`, `test_session_uptime`, `test_dashboard_sessions_route`).
All of them test machinery this manifest archives.

## 4. Archive manifest

Destination: `_archive/<original path>` by `git mv`, banner in the same commit
(`_archive/README.md` rules 1–6). **Nothing moves until the IBKR account is flat
(§5)** — several of these are the tools a human would use to verify that.

### 4.1 IBKR broker code — archive

`src/deploy/broker/ibkr.py`, `src/deploy/run_book.py`, `ops/account_audit.py`,
`ops/cancel_open_orders.py`, `ops/capture_fills.py`, `ops/reconcile_orders.py`,
`ops/reset_epoch.py`, `ops/switch_broker.py`, `ops/verify_session.py`,
`ops/pending_orders.py`, `ops/rebuild_ledger.py`, `ops/preflight.py`,
`ops/doctor.py`, `ops/unbook_unexecuted_fills.py`, `deploy/ibgw/**`,
`ops/schedule/{cef,cef_pm,benchmarks,phase0}.env`.
`src/deploy/broker/__init__.py` loses its `ibkr` branch. `requirements.txt`
loses `ib_async`/`ib_insync`. `dashboard/server.py` loses `_probe_broker`,
`_ibc_running`, `/api/connect`, `_portfolio`, and the reconcile imports.

**Concepts to rebuild in `quantt/`, not port**: the pending-order refusal (a
second armed run doubles the book — still true at Alpaca, which dedupes only an
*active* `client_order_id`), post-close verification, pre-trade gate, cancel-all.

### 4.2 Old run infrastructure — archive

`ops/schedule/**` except `nyse_calendar.py` (plists, renderers,
`patch_launch_job_w3am.py`, backup launchd, weekly report), `ops/promote.sh`,
`ops/archive_machine_pre_w3.py`, `ops/session_plan.py`, `ops/session_uptime.py`,
`ops/decision_age.py`, `ops/heartbeat.json`, `ops/halts/*`, `ops/reports/*`.

**Reusable as is or with small edits**: `ops/netguard.py`, `ops/halt.py` (drop
SMTP per D3/D4), `ops/common.py` (`atomic_write`, spec loader — its top-level
`src.backtest.engine` import comes along), `ops/ledger.py` core (review its
IBKR-shaped `execId` fields), `ops/schedule/nyse_calendar.py`,
`src/deploy/broker/base.py` (the `Broker` seam), `src/deploy/broker/simulator.py`,
`src/deploy/{portfolio,exec_ledger,fills,risk,report}.py`, `ops/session_rc.py`
(the rc table idea). `ops/orient.py`, `ops/doc_audit.py`, `ops/prompt_status.py`
are adapted, not archived — they are how agents know anything.

### 4.3 Books and specs

- **Archive**: `ops/books/phase0_book.json`, `ops/books/phase0_live/**`,
  `ops/books/benchmarks_live/**`, `ops/books/cef_live/**` (the IBKR shadow
  ledger — history; the Alpaca book starts a new epoch), `ops/books/_dryruns/**`,
  `ops/books/_recovered_dryruns/**`, `ops/books/dryrun_*.json`,
  `ops/books/book_status_dryrun.json`; specs `null_trader`, `credit_rv`,
  `bench_b1_hyg`, `bench_b3_agg`, `bench_b4_60_40`, `bench_b5_shy`.
- **`ops/books/retired/`** "must not move" (CLAUDE.md landmine 7) only because
  `IBKRBroker._foreign_book_claims` globs `ops/books/*.json`. That reader is
  archived with IBKR, so the constraint dies with it; move it in the same commit
  and drop the landmine in the CLAUDE.md draft.
- **Keep**: `ops/specs/cef_discount.frozen.json`,
  `ops/specs/bench_b6_ew_credit.frozen.json`. `ops/books/benchmarks_book.json`
  is replaced by a b6-only book; `cef_discount_book.json` loses its "IBKR paper
  account" description.
- **Prod's untracked state** (`~/prod/QUANTT`: halt files, schedule logs,
  `_desync/` records, live ledgers) is copied into `_archive/prod_state_2026-09-28/`
  with `git add -f` before prod is dismantled — it is the only copy of the
  09-14/09-15 incident evidence.

### 4.4 Tests

Archive with their subjects (`ops/tests/`): `test_archive_machine_pre_w3`,
`test_capture_fills_*`, `test_decision_age_wiring`, `test_doctor_*`,
`test_patch_launch_job`, `test_preflight_checks`, `test_promote_gate`,
`test_session_deadline`, `test_session_plan`, `test_session_uptime`,
`test_stuck_session_guard`, `test_unbook_unexecuted_fills`,
`test_verify_session`, `test_w3_morning_execution_gap`,
`test_dashboard_sessions_route`. `src/deploy/tests/`: `test_arm_attribution`,
`test_arm_called_once`, `test_decision_age_clock`, `test_ledger_behind_guard`,
`test_null_trader_winddown`, `test_option_order_path`, `test_order_map_key`,
`test_order_path_noop_for_shares`, `test_pending_orders_guard`.
Split: `test_band_hold_dust` (keep the sleeve/exec_ledger half).
Adapt: `test_netguard`, `test_doc_audit`, `test_orient`, `test_halt_*`,
`test_session_rc`, `.claude/hooks/tests/*`.
Keep: `test_group_cap`, `test_cef_spec_required_keys`, `test_real_fill_booking`,
`test_registry_unimplemented`, `scripts/cef/tests/*`, `src/backtest/tests/*`,
`src/analysis/tests/*`, `quantt/tests/*`.

### 4.5 Scripts

Archive: `scripts/audit/moc_routing_test.py` and `live_pnl_attribution.py`
(both **connect at import** — never import to move them; `git mv` only),
`scripts/ops/reconcile_attribution.py`, `scripts/cef/fetch_borrow_rates.py`
(its IBKR source is dead since 2026-09-09), `scripts/cef/fetch_borrow_history.py`,
`scripts/cef/reconcile_prices.py`, `scripts/rv/*ibkr*`,
`scripts/rv/measure_rth_liquidity.py`, and the credit_rv research with its book.
Keep: `scripts/cef/*` research and fetchers, `scripts/fetch_cef_distributions.py`,
`scripts/holdings/fetch_nav_multi.py`. `scripts/cef/validate.py` and
`open_holdout.py` import `src.strategies.credit_rv.costs.SCENARIOS`; that module
must be kept (or its constants moved) before credit_rv is archived.

### 4.6 Documents and the agent layer

Rewrite for Alpaca: `docs/SYSTEM.md` §4 (and §5 gains a 2026-09-28 table from
§2 here), `docs/INFRASTRUCTURE.md` §5–6, `docs/INDEX.md`, `README.md`.
Agent layer: `.claude/rules/live-order-path.md`, `.claude/agents/ops-watchdog.md`,
skills `incident`, `preflight`, `book-status` (heavy), `fill-audit`,
`morning-brief`, `dashboard-ui`, `next-task` (light), `.claude/hooks/book_state.py`
(`SHADOW_SUBDIR` points at `cef_live/_ibkr_shadow`). Old copies go to
`_archive/claude_layer/`.
`CLAUDE.md`: **draft a diff only** (hardening D15) at
`results/ops/ALPACA_CLAUDE_md_proposed.diff`; the team lead applies it.
`.claude/settings.json` carries `~/ibc/**` and `~/prod/QUANTT` permissions and
is the team lead's to edit.

### 4.7 Outside the repo — human only

`~/Library/Application Support/quantt/launch_job.py`,
`~/Library/LaunchAgents/com.quantt.*.plist` (12 loaded jobs),
`~/prod/QUANTT` (worktree, detached at `v2026.09.13.4`), `~/ibc/`, `~/Jts/`,
`~/prod-backups`, `dashboard/QUANTT Dashboard.command` (stale Desktop path).

## 5. Human-only steps, in order

Each of these can transmit an order or change what the scheduler runs
(CLAUDE.md order-path rule 1). Agents propose; the team lead runs them with `!`.

1. **Unload every `com.quantt.*` launchd job** so nothing fires during the
   migration (`launchctl bootout gui/$(id -u)/com.quantt.<job>` each).
2. **Bring IB Gateway up and log in by hand** — the flatten needs it.
3. **Flatten the whole IBKR paper account with MOC orders**, not market orders
   (order-path rule 3). Everything goes, so the account net is the target — the
   one time "take a symbol from the account net" is correct. Tool:
   `ops/flatten_ibkr_account.py` (agent-written, tested against a fake broker,
   never run). Dry run first — it connects read-only and prints the plan:
   `python3 -m ops.flatten_ibkr_account`, then
   `python3 -m ops.flatten_ibkr_account --transmit --account <id it printed>`
   before 15:40 ET. It refuses a second send the same day, any open order at
   the broker, non-stock/non-USD/fractional positions, and `DRY_RUN=1`.
4. **Verify flat at the broker** the next morning
   (`python3 -m ops.flatten_ibkr_account --verify`, read-only, exit 0 = flat),
   then snapshot the final account and fills into `_archive/`.
5. Create the two Alpaca paper accounts (CEF, b6) at $100k, and put
   `ALPACA_CEF_KEY_ID`, `ALPACA_CEF_SECRET_KEY`, `ALPACA_B6_KEY_ID`,
   `ALPACA_B6_SECRET_KEY` in `config/.env`. Then
   `python3 -m quantt.broker.alpaca_probe --check-keys` (prints SET/NOT SET),
   then `python3 -m quantt.broker.alpaca_probe`.
6. Regenerate the Alpaca key ID pasted into the 2026-09-28 session transcript.

## 6. Next agent work, once §5.5 has run

1. Read the probe snapshot: which of the 17 CEFs are tradable, shortable, ETB/HTB.
   **This can change the strategy** (an HTB or untradable name is a universe
   question for the team lead, not an adapter detail).
2. Re-derive `max_gross_stress` and `min_trade_usd` on Alpaca; one `/spec-change`
   to v7-Alpaca at $100k with its pre-registration; counter 48 → 49.
3. Order-path behaviour probes on paper (human-run): `cls` accepted?; paper MOC
   fill price vs `/v2/stocks/auctions`; long→short flip in one order; opposite-side
   orders in one symbol; `client_order_id` reuse after fill.
4. Design and build the `quantt` adapter, reconciliation from
   `/v2/account/activities` + `trade_updates`, dual scoring, and the VM runner.
