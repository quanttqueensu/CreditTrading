# QUANTT CEF book: halted -> reliably trading in prod. FINAL plan (draft revised against three critiques)

Finalised Mon 2026-09-21 ~10:10 EDT. This session was read-only: no tracked file, data/, prod, LaunchAgents or Application Support file was changed and no broker socket was opened. NEW = a file this plan creates. Finding ids (A1, C8v...) refer to the audit findings. [V] verified, [S] sourced, [U] uncertain. Anything not measured is UNMEASURED.

## P. Read first

### P.1 State re-measured by the finaliser (command -> result)
- `date` -> Mon Sep 21 09:58 EDT 2026. **Today is a trading day, not Sunday.**
- `launchctl print-disabled gui/$(id -u) | grep quantt` -> `com.quantt.ibgateway => disabled`; `launchctl list` shows 11 quantt labels, none ibgateway; `lsof -iTCP:4002 -sTCP:LISTEN` -> nothing.
- `ls ~/prod/QUANTT/ops/HALT*.md` -> benchmarks_paper, cef_discount_paper, phase0_null. `git -C ~/prod/QUANTT describe --tags` -> v2026.09.13.4.
- `tail _capture_log.csv` -> last row 2026-09-18T22:39:54. No row for 09-21.
- Panels: cef_prices and cef_nav last date 2026-09-18 (pandas read). spec_id cef_discount.v6.20260906, order_type MOC, 17 names.
- Live state is TRACKED: `git ls-files` -> ops/books/cef_live 30, benchmarks_live 73, phase0_live 20, _dryruns 18, ops/heartbeat.json, ops/halts/*. `git diff --name-only v2026.09.13.4..HEAD -- ops/books ops/heartbeat.json ops/halts` -> empty. Prod has 36 ` M` tracked state files.
- No conftest.py exists anywhere (root, ops/tests, src/deploy/tests, scripts/cef/tests).
- `ops/ledger.py` save() rebuilds manifest.json with only version/written_utc/files (lines 359-366): epoch* keys and anything a tool adds are erased by the next save. No live code reads the manifest epoch keys (grep); the epoch is identified by the nav.csv row with decision=epoch.
- nextgen `ng/ops/repair_legacy_ledger.py:349` requires schema `ng.broker_state.v1`; the prod `_broker_archive/*/broker_*.json` files have keys measured_et, auction, client_id, positions, resting, executions and no schema. Snapshots exist for 09-14..09-17; 09-18 has only a verdict with status UNVERIFIED; 09-14..09-17 verdicts are FAIL.
- nextgen has 0 files under ops/src/dashboard importing ng.
- `preflight.run(job, book_path, asof, want_live, notify)` has no books-root; `main` returns 1 whenever --no-live. Launcher JOBS holds the only job->root map (lines 125-166) and calls `pf.run` at 549.
- run_book returns 3 (arm refused; also writes a halt), 4, 5, 6. `--job` default None. `place_targets` has no `now` parameter; `recorded_utc` uses utcnow (ibkr.py:2093); `_append_capture_log` uses datetime.now (capture_fills.py:228).
- Prod envs: cef/benchmarks/phase0 DRY_RUN=0 EXECUTION=ibkr; cef_pm DRY_RUN=1.
- `scripts/fetch_cef_distributions.py` is module-level code (fetch loop line 56, atomic_write lines 114/117/184/250, no main). `scripts/cef/fetch_daily.py` writes module-constant paths under REPO/data/cef.
- Unpushed commits (`git rev-list --count <b> --not --remotes=origin`): main 17, nextgen-20260914 33, docs-cleanup 18, promote-align-20260911 1. `/Volumes` holds only Macintosh HD: **no external volume is mounted**.
- orient: doc-audit 0 DRIFT, prompt_status 0 DRIFT rc 0; the 2 unguarded ib_insync imports are scripts/rv (research, parked).

### P.2 Corrections to the brief
1. It is Monday; the 08:30 cef fire already ran and was blocked; the 12:00, 16:20, 17:25 and 17:30 fires are still to come today.
2. The 09-14 ledger did not refuse: `advance()` was a silent no-op because epoch date == asof (A1, A9).
3. Four tests are red, not three (D2); all stale and machine-dependent.
4. The benchmarks halt is the same defect class and touches all five sleeves (A5).
5. session_uptime's dev/prod disagreement is the `cef_*.log` glob matching `cef_pm_*.log` (B5).

### P.3 Hard lines
AGENT work: dev repo only, in worktrees under `~/Desktop/2027/QUANTT/wt/`, never the order path.
- The main dev tree **stays on `main` and is never switched**: its data/ is prod's panel. All integration and full-suite runs happen in `wt/integration`, which has no data/.
- Agents never write under data/, ~/prod/QUANTT, ~/Library/Application Support/quantt, ~/Library/LaunchAgents.
- Agents never `git add` anything under ops/books/, ops/heartbeat.json or ops/halts/; if dirty in a worktree, `git restore` them. Test fixtures live under `*/tests/fixtures/`. Never pass `--books-root` to an in-tree `*_live` directory.
- Agents never run: `python3 -m src.deploy.run_book` as a CLI, launch_job.py, ops/promote.sh, clear_halt, reset_epoch, rebuild_ledger, capture_fills, verify_session, reconcile_orders --check-broker, any `--apply` against a live root, any launchctl verb other than list/print/print-disabled, anything under scripts/audit/, the fetchers against the real data/.
- Agents may call `run_book.main` (with or without --dry-run) and construct `IBKRBroker` **only inside pytest under the WS0 conftest or inside ops/rehearsal.py**, with `ops.netguard` asserted active, and for EXECUTION=ibkr only with `src.deploy.run_book.make_broker` patched to the stub-ib broker and the patch asserted hit.
- The unrefactored `scripts/fetch_cef_distributions.py` is never imported or run by an agent.
- Agents do not change permission settings or CLAUDE.md. The settings diff is drafted by an agent and applied by the team lead.
HUMAN-ONLY: anything opening a broker socket, ops/promote.sh, clear_halt/write_halt in prod, replay_ledger --apply on prod, the launcher patch --apply, launchctl, sudo, credentials, git push, git tag, running fetchers that write data/. Written as `! <command>`.
Unchanged: MOC stays; DRY_RUN=1 always wins; dashboard keeps exactly one non-GET route; research never writes live panels; no spec change, no strategy feature, no trial spent.

### P.4 Scope rule
A control is must-have only if its absence can cause a wrong order, a lost record or an unnoticed outage. Everything else is parked (section E). Findings marked added-by-verifier-single-source or unverified-below-threshold are verify-first (section F): reproduce with the failing test first; if it does not reproduce, stop and report.

### P.5 Protocols
**Failing-first (regression tests of existing behaviour).** Two commits. Commit 1 adds the test marked `@pytest.mark.xfail(strict=True, reason="HARDENING-RED: <finding>")`; it must reach the defect through existing surface only (on-disk orders.csv, `ib.placed`, raised exception type). Run `python3 -m pytest <file> --runxfail -q`; save the output plus `git rev-parse HEAD` to `results/ops/hardening_2026-09-21/failing_first/<test>.txt`. The recorded failure line must be the named assertion, never ImportError/AttributeError. Commit 2 makes the change and removes the marker. The suite is green at every commit and red is reproducible at commit 1. For tests touching files that differ between tag and main (cef_discount.py, l1_meanvar.py, reconcile_orders.py), also run the test file copied into a `git archive v2026.09.13.4` export.
**New-tool tests (no old behaviour exists).** Replace failing-first with a named mutation per test, recorded in the same directory: delete the `record_orders` call -> orphan test red; delete the `covers_date` loop -> C8v test red; make replay skip the capture check -> "removed capture row raises" red; etc.
**No-op proof, sim path.** NEW `ops/noop_proof.py` (never imported by live code). `git archive v2026.09.13.4 | tar -x -C <scratch>/base`; `ln -s <dev>/data <scratch>/base/data` (read only). Run `python3 -B <cand>/ops/noop_proof.py --tree <scratch>/base --out <scratch>/noop/base --from <d0> --to <d1> --book ops/books/cef_discount_book.json` and the same with `--tree <cand>`. The driver puts --tree first on sys.path, asserts imported module paths resolve under --tree, installs netguard and the data-write guard, runs PortfolioOrchestrator + Simulator (execution_record=None). Compare positions/nav/trades/orders.csv with `cmp`; compare manifest.json as parsed JSON with `written_utc` removed (stated, because save() stamps the wall clock). Mutation control: a one-line change to `_make_orders` in a throwaway copy must make `cmp` fail. Save both outputs with shas.
**No-op proof, sleeve.** Same driver, `--sleeve-targets`: baseline vs candidate targets over the full 2013+ panel under carried holdings. Report three numbers: dates identical; dates where candidate raises SleeveCannotDecide and baseline emitted FLAT; any other difference (must be 0). Expected-difference controls with holdings forced on the NaN-close dates the findings list (2026-02-12, 02-13, 02-18, 03-18; re-measure at run time, H14): baseline FLATs a held name, candidate raises naming it. The measured raise frequency goes into decision D8.
**Evidence.** Governance artefacts go in tracked `results/ops/hardening_2026-09-21/` (never /private/tmp). Humans tee command output to `~/prod-backups/rearm/`; an agent copies it in.

### P.6 Return-code table (owned by NEW `ops/session_rc.py`, created in WS0; every workstream imports it, none invents a code)
| rc | raised by | can an order have left? | in NON_TRANSMITTING_RCS |
|---|---|---|---|
| 0 | success | yes | n/a |
| 1 | any unhandled exception, ShadowLedgerDesync, or any refusal when `n_placed > 0` | yes/unknown | no |
| 2 | argparse: --job missing for ibkr non-dry-run | no, but unreachable from the launcher | no (fail closed) |
| 3 | arm refused (existing; also writes a halt) | no, arm precedes every place_targets | yes, only if its two tests pass |
| 4 | DecisionTooOld (existing) | no | yes |
| 5, 6 | OrdersAlreadyPending / PendingStateUnknown (existing) | possible in a multi-sleeve book | no, stays "armed", the safe direction |
| 7 | pre-transmit ledger/NAV refusal (ShadowLedgerBehind, BookingWouldFail, SleeveNavUnknown) and `n_placed == 0` | no | yes |
| 8 | SleeveCannotDecide and `n_placed == 0` | no | yes |
| 9 | DRY_RUN=1 visible to an ibkr non-dry-run call | no, returns before make_broker | yes |
| 10 | halt active | no | yes |
fetch_daily keeps 0/1/4 and gains 14 = "vendor returned nothing / no network"; the launcher uses 124 for a budget kill.
For every rc in the set, two tests: (i) run_book returns it only with `ib.placed == []`; (ii) with a stub whose placeOrder succeeds once then raises, or whose second sleeve refuses, run_book never returns an in-set rc. One parametrised session_plan case per rc with a launcher-shaped beat (status=failed, armed=True, pair_date=asof, rc=X) states the expected `plan('cef', 12:00).may_arm`.

### P.7 Calendar labels
Day 0 = today. P = promotion day (trading day, promote 12:30-14:30 ET). S = next trading day after P = shadow morning with halt on; repair on S afternoon through S-1; preview S evening; clear between 23:40 S and 08:15 A. A = S+1 = first armed morning, asof = S, ledger last_date = S-1, so the first live advance walks exactly one bar. A+1 = the session the incident broke.
If re-arm slips by one or more trading days after the repair: re-run `replay_ledger --through <new A-2>` (incremental, tested in 2.5.1), re-run reconcile, re-run the preview, re-sign.

## Phase 0 - Freeze line (depends: nothing)

**0.1 [AGENT] Integration worktree, branch, freeze record.**
- Do: `git -C ~/Desktop/2027/QUANTT/2027 worktree add ~/Desktop/2027/QUANTT/wt/integration -b hardening-20260921 main`.
- Files NEW: `results/ops/hardening_2026-09-21/FREEZE.md` (scope rule, must-have list, parked list, rc table, decisions D1-D20 with signature lines); `.../templates/` holding copies of the auditor scratch templates the plan leans on (laneA/replay2.py, laneA_v3/verify*.py, laneC/e2e.py, laneC/flat.py, laneC_verify/vanish.py, mintrade.py, g_first_session.py, g_account.py, g_recon.py, noop_diff.py); `.../failing_first/`; `.../evidence/`. Add the new files to docs/INDEX.md. After the team lead signs, the agent copies the signed decisions verbatim into docs/SYSTEM.md section 5.
- Proof: `python3 -m ops.doc_audit --check` and `python3 -m ops.prompt_status --check` exit 0 (both exit 0 today, so this is a regression check; the implementer reads ops/doc_audit.py and registers the new notes if it keeps a registry).
- Reversible: remove worktree, delete branch.

**0.2 [AGENT] WS0 - suite-wide safety harness. Merges first; no other workstream branches before it is on hardening.**
- Files NEW: `ops/netguard.py`; root `conftest.py`; `ops/tests/test_netguard.py`; `ops/session_rc.py` (P.6 constants and table only); `ops/tests/test_session_rc.py`.
- `netguard.install()` replaces `socket.socket.connect`, `connect_ex` and `socket.create_connection` with a raiser (NetGuardViolation) for every destination; `is_active()`.
- Root conftest (applies to all seven testpaths): at import, wraps `ops.common.atomic_write` so a target resolving under the main dev tree's data/ or under ~/prod raises PanelWriteGuard (at import so later `from ops.common import atomic_write` binds the wrapper); session fixture installs netguard, sets EXECUTION=simulator and IBKR_PORT to a closed port, points `ops.doctor.AGENTS` at an empty tmp dir, replaces `ops.halt.alert` with a recorder (opt-out fixture `real_alert` only with smtplib and subprocess stubbed), wraps subprocess.run/call/check_call/check_output/Popen to raise on any launchctl verb other than list/print/print-disabled and on argv naming launch_job.py or src.deploy.run_book; `pytest_sessionstart/finish` hash data/cef/{cef_prices,cef_nav,cef_distributions}.parquet when present and fail the session if a hash changed.
- Tests: connect, connect_ex, create_connection and `asyncio.open_connection` all raise; `launchctl bootout` raises and `launchctl list` passes to a stub; atomic_write under real data/ raises; alert recorder records. Mutation: remove install() -> tests red.
- Verify-first: some existing test may need a local socket; the implementer finds out by running the suite and makes that test hermetic rather than widening the guard.
- Reversible: git revert.

**0.3 [AGENT drafts, TEAM LEAD applies] Permission allowlist (E5; F7v deny rules).**
- Agent writes `results/ops/hardening_2026-09-21/settings_proposed.json` = the current working copy (which already removes `python3 scripts/*` and `python3 -c *`) plus one deny rule per verb and per tool (rules are globs with no alternation): `python3 scripts/audit/*`; `python3 -m src.deploy.run_book*`; `*launch_job.py*`; `launchctl load*`, `unload*`, `bootstrap*`, `bootout*`, `kickstart*`, `enable*`, `disable*`; `python3 -m ops.reset_epoch*`, `ops.rebuild_ledger*`, `ops.cancel_open_orders*`, `ops.switch_broker*`, `ops.unbook_unexecuted_fills*`, `ops.capture_fills*`, `ops.verify_session*`; `*reconcile_orders*--check-broker*`; `*replay_ledger*--apply*`; `*patch_launch_job*--apply*`; `python3 scripts/cef/stage_cef.py*`; `python3 scripts/fetch_cef_distributions.py*`; `python3 scripts/cef/fetch_daily.py*`; `*clear_halt*`. Narrow the preflight allow to invocations containing --no-live; if the rule syntax cannot express that, remove the allow so every preflight run asks.
- Test NEW `.claude/hooks/tests/test_settings_order_path.py`: enumerates each forbidden command string; green against the proposed file; xfail-strict (HARDENING-RED) against the actual `.claude/settings.json` until H9.
- Verify-first [U]: the human's own `! ` lines are not tool calls; if deny rules turn out to block them, the human uses a separate terminal.

**0.4 [AGENT] Docs-only hygiene.** In wt/integration: (a) read, then `git cherry-pick 687936e` (results/ops/LEDGER_NOOP_MORNING_2026-09-15.md, E7); if it says the ledger "refused", amend to the no-op mechanism. (b) Reconcile the CEF counter in docs/RESEARCH_STATE.md with nextgen (E6): walk `git log -p nextgen-20260914 -- docs/RESEARCH_STATE.md`, one line per increment citing the commit; write only what the walk shows. (c) `/incident` record with the corrected root cause, naming guards 2.2.1-2.2.4. Proof: doc_audit and prompt_status --check exit 0.

**0.5 [AGENT] Release gate (E1, E3).** NEW `ops/release_check.sh <prod_tag>`, `ops/tests/test_release_check.py`, `ops/tests/test_no_ng_imports.py`. The script prints which check refused and exits non-zero unless: (1) `python3 -m pytest` exits 0; (2) `git diff --name-only <tag>..HEAD -- ops/specs/` empty; (3) spec_id equals the value at <tag>; (4) no file under ops/, src/, dashboard/ imports ng, and `test ! -e ng`; (5) `git status --porcelain` empty; (6) doc_audit and prompt_status --check exit 0; (7) `git diff --name-only <tag>..HEAD -- ops/books ops/heartbeat.json ops/halts` empty (keeps E2 dormant under the old promote.sh); (8) no nextgen-only commit reachable: if ref nextgen-20260914 or origin/nextgen-20260914 exists, `git rev-list <ref> --not main` has no member in `git rev-list HEAD`; if neither ref exists print `nextgen reachability NOT CHECKED` and fail unless `--no-nextgen-ref`; (9) `grep -rn "HARDENING-RED" --include='*.py'` finds no remaining xfail; (10) the sleeve and sim no-op proofs of P.5 pass when data/ is reachable, else print UNMEASURED and fail.
- Tests: one fixture repo per check (spec diff, changed spec_id, an `import ng`, dirty tree, failing audit stub, committed ledger edit, failing test); each asserts the refusing line. No collected test depends on a local-only branch. One-off evidence run against nextgen-20260914: checks 2 and 3 fail, check 4's import half passes (measured 0 imports), `test ! -e ng` fails.

**0.6 [HUMAN] Get everything off this disk (E4, E5v).** See H5. Parking nextgen means pushing it, never merging it.

## Phase 1 - Restore points and state-repair preparation

**1.1 [HUMAN, TODAY before 16:00 ET] Gateway back under launchd (B1, E4v, F9v).** H1. Until promotion the three HALT files are the only lock on three DRY_RUN=0 books, so their presence is a precondition. Unblocks today's 16:20 and 17:30 captures (09-21 becomes a covered day) and every promotion (promote.sh:240 runs the full doctor).

**1.2 [HUMAN] Read-only broker truth before any repair (A2, C2).** H2. Source confirmed read-only by the verifier (readonly=True, positions() only). Expected divergence on exactly six names: AWF -638, JFR +1747, NEA +904, PDO -909, PFN +3725, PHK +1389. Anything else: stop; the repair premise is wrong and the team lead chooses between replay and a fresh epoch.

**1.3 [HUMAN + AGENT] Restore points.** H8: `ops/backup_state.sh` (exit 0 or 2 acceptable, promote.sh:171-181), then copy the archive **and** `~/Library/Application Support/quantt/launch_job.py` and `~/Library/LaunchAgents/com.quantt.*.plist` off the volume; record `shasum -a 256` of the launcher and plists in FREEZE.md now and again before and after the launcher patch. Never copy config/.env or the IBC config. No external volume is mounted today, so the team lead must attach one or name a private remote (D19). AGENT restore drill (reads prod only): `tar -xzf <archive> -C <scratch>/restore && diff -rq <scratch>/restore/ops/books/cef_live ~/prod/QUANTT/ops/books/cef_live` -> no differences. A real restore names only ops/books/cef_live, benchmarks_live, phase0_live, ops/heartbeat.json and HALT files, never ops/books whole (promote.sh:212-216).

**1.4 [AGENT] Freeze the rehearsal input.** `cp -R ~/prod/QUANTT/ops/books/cef_live <scratch>/rehearsal/input_<stamp>/cef_live`; write `shasum -a 256` of every file into the evidence directory. Only this copy is ever mutated.

**1.5 [HUMAN, after WS4a merges; outside session windows; books halted] Refresh the distribution panel (F6, G3, G7v).** H11. Scratch first: the refactored fetcher writes to `--out-dir`; an agent compares all four outputs (distributions, splits, dist_features, facts) against the live files for the 17 names: no ticker lost, row counts never fall, last ex_date never moves back, September rows present or the gap named as UNMEASURED. Only then does the human copy into data/cef after backing the four files up. Verified so far: NEA, JFR, HYT ex 09-15; PDI, PFN, PHK, PDO ex 09-11 (the epoch date, so not an in-epoch miss); the rest [U]. Keep the diff as the source note for docs/REFERENCES.md.

**1.6 [TEAM LEAD] Epoch mark convention (G6v, verify-first).** D2. The repair tool carries both options; both NAV classes are reported until chosen.

**1.7 [HUMAN daily until re-arm] Coverage watch.** H7 after 16:21 ET each trading day. Any day without a capture row at or after 16:00 ET with unattributed 0 is added to `evidence/uncovered_days.txt` and needs `--attest-no-trade` at the repair.

## Phase 2 - Code fixes (all AGENT, worktrees off hardening after WS0)

### WS1 - schedule truth
**2.1.1 Hermetic schedule tests (D2, B9v).** Files: `src/deploy/tests/test_decision_age_clock.py`, `ops/tests/test_stuck_session_guard.py`; explicit fixture plists (not autouse): evening 17:15 keeps the literal history (17h23m, the 00:30 boundary, Saturday 07:09); morning [(8,30),(12,0)] gets the new cases; cover the tests that pass by accident (e.g. test_a_normal_evening_session_arms). With the root conftest's empty AGENTS, an un-fixtured read raises DecisionAgeUnknown instead of reading the machine. No production change. Proof: both files pass, and pass again under `env HOME=<scratch>/emptyhome`.
**2.1.2 The 12:00 retry can arm (B2, C4, D1).** `ops/doctor.py` NEW `_plist_start_minutes_all(job)` (dedupe (Hour,Minute) over the interval dicts; keep `_plist_start_minutes`); `ops/decision_age.py::session_start` takes the latest scheduled start at or before now on the session day. Condition (A) untouched. Docstring: an 08:30 process hung past 12:00 is caught by the launcher's stood_down_late. Failing-first: `test_the_noon_retry_is_inside_its_own_window` (12:09 arms; 10:31 and 14:01 refuse); hung-08:30 pin; `now < session start` pin. Ships only in the same tag as WS2 and 2.1.3 (C4 sequencing).
**2.1.3 A stand-down never erases today's armed beat; a non-transmitting failure is not armed (B3, C7v, C7a).** `ops/halt.py::beat` carries `last_armed {status, at, date, session_date, pair_date}` for CEF_JOBS only, replaced only by another armed beat, refused without a session_date, never stored from a beat whose rc is in NON_TRANSMITTING_RCS; `ops/session_plan.py::_armed_beats` yields last_armed and excludes `status=='failed' and detail.rc in session_rc.NON_TRANSMITTING_RCS`; `ops/verify_session.py::decision_check` accepts last_armed with session_date == prev_pair and status ok (the 09-15 failed morning must still FAIL). Failing-first in `ops/tests/test_halt_beat_session_date.py`, `ops/tests/test_session_plan.py`: replay the literal 09-14 beat sequence -> `decided_today == 'cef'`, `plan('cef_pm').mode == CAPTURE_ONLY`, decision_check PASS; the P.6 per-rc cases.

### WS2 - ledger and order integrity (one unit: C1 without C8v is worse than today; A1 without A6v stalls forever)
**2.2.0 Clock seam.** NEW `ops/clock.py::now_et()`, default wall clock; `set_for_test(ts)` raises unless `ops.netguard.is_active()`, so the clock can only be faked in a process that cannot open a socket. Used by `_refuse_if_orders_pending`, `_coverage_for`, `_refuse_if_ledger_is_behind`, `_execution_record`, `_record_order_attribution` (recorded_utc), `capture_fills._append_capture_log`, `arm()`. Tests: default equals wall clock; set_for_test without netguard raises; positive control in the harness: with the seam on the wall clock, simulated day 2 raises OrdersAlreadyPending (proves the guard is exercised, not bypassed). Live behaviour unchanged, proved by the sim no-op.
**2.2.1 Write-ahead order rows (A1, C1, A9).** `ops/ledger.py` NEW `Ledger.record_orders(asof, rows)`: appends open ORDER_COLUMNS rows, decision_date=asof, order id inside `reason` (no new column), persisted through save(), idempotent on (decision_date, ticker, reason); `advance()` step 4 skips `_make_orders` when execution_record is not None. `src/deploy/broker/simulator.py` NEW `record_transmitted`. `src/deploy/broker/ibkr.py::place_targets`: before the first placeOrder write every row for singles and combos as open; stamp orderId after each placeOrder (a never-sent row closes `skipped` next day, the safe direction); NEW counter `n_placed`; print the advance summary (n_days, NO-OP, STOPPING) unconditionally on the real-fill path. No spec or book key: branch on `execution_record is not None`. Never raise after placeOrder for a map/orders mismatch: build both from one list and alert. Failing-first, driven through IBKRBroker with a stub ib (reuse `_IbInsync` from test_option_order_path.py:132 and the StubIB shape of laneC/e2e.py; the auditors' draft test is rewritten): NEW `src/deploy/tests/test_transmitted_orders_never_orphaned.py`, `test_two_session_replay.py`, literal quantities of order-map ids 31-34 and 37-40: (1) epoch on D, session asof=D -> open orders {JFR +301, PDO -909, PFN +604, PHK +1389} (today {}); (2) D, D+1, D+2 with the 8 real executions -> no UnbookedExecution, held AWF 1288, JFR -8720, NEA -10672, PDO 6402, PFN 5280, PHK 8478, every execId once in trades.csv; (3) post-transmit raise: the stub gains a commission-less execution between the dry advance and the real advance (a real same-day race) -> `ib.placed` non-empty, desync record lists the orders, every write-ahead row on disk with its order id, the next session books them; this test must still pass after 2.2.4; (4) AGG: ledger 206, adapter SELL 2, next-day execution booked; (5) adapter delta $520 vs ledger-derived $510 -> still booked. Tests that pin old behaviour and must change: `ops/tests/test_w3_morning_execution_gap.py`, `src/deploy/tests/test_ledger_behind_guard.py`. Sim no-op proof (P.5).
**2.2.2 An uncovered day always raises (C8v, verify-first).** `Ledger.advance`: with a record, check `covers_date(d)` for every walked day before step 2, else ExecutionRecordGap, nothing written. NEW `ops/tests/test_ledger_uncovered_day.py` (today returns with new nav rows and 0 trades); companion: record None byte-identical.
**2.2.3 Multi-day coverage from the durable record (A6v, C7b, verify-first).** `ibkr.py::_coverage_for/_execution_record`: for every panel bar d in (last_date, asof], ask `capture_fills.capture_covers(books_root, d)`; if it vouches, load `captured_executions(state, d)` and add d to covers. `_refuse_if_ledger_is_behind` uses the same function, refuses only when a bar in the gap is not vouched for, and names `ops.replay_ledger`. Never `_make_orders` for a bar before `through`. NEW `src/deploy/tests/test_multi_bar_catch_up.py`: (a) 3-bar gap with a booked execution proceeds (today ExecutionRecordGap after placing); (b) one capture row removed -> refuses with `ib.placed == []`; (c) one missed session with open transmitted rows proceeds (today ShadowLedgerBehind); (d) 2-bar and 3-bar gaps of halted no-order days with genuine capture rows book zero executions on the intermediate days and write the armed day's rows. Replace test_skipped_session_refuses and test_no_open_orders_never_refuses.
**2.2.4 Every booking exception is raised before the first order (A3, C2).** NEW `ops/ledger_check.py::dry_advance(state_dir, ...)`: copies the sleeve state to a temp dir and advances the copy; also refuses when any walked day before asof is uncovered or when broker_fills.csv holds a post-last_date execId absent from trades.csv. `ibkr.py` NEW `_refuse_if_booking_would_fail`, called right after `_refuse_if_orders_pending`, before the transmit lock. Same-day branch builds the record twice (never reuse a live ib.fills() snapshot) and has its own test using the clock seam. Preflight: NEW blocking check `ledger` in `ops/preflight.py::run`, durable record only; NEW `ops/live_roots.py::LIVE_ROOTS` (job -> books root) with a test that each equals the launcher JOBS root (skips when the launcher is absent); `run(..., books_root=None)` resolves through LIVE_ROOTS, unknown job raises; CLI gains `--books-root`; the --no-live exit code is left alone. Failing-first NEW `src/deploy/tests/test_refuse_before_transmit.py` (frozen epoch ledger, 4 unbooked executions, asof D+4 -> raises with `ib.placed == []`; NoCommissionReport variant; on-disk files and manifest byte-identical after the dry advance); `ops/tests/test_preflight_checks.py::test_ledger_check_blocks_when_dry_advance_raises`.
**2.2.5 A pre-transmit refusal is a clean stand-down (A3, C7a).** `src/deploy/run_book.py` beside the rc 4/5/6 handlers: catch ShadowLedgerBehind and the new refusals, print, `ops.halt.alert`, no halt, return 7 only when `n_placed == 0`, else 1. NEW `src/deploy/tests/test_run_book_refusal_rc.py` (P.6 pair for rc 3, 4, 7).
**2.2.6 Desync record lists the orders (A8v, A7, C13a, verify-first).** `_record_desync` receives `placed`; writes `transmitted_orders [{order_id, instrument, action, qty, order_type}]`; text leads with "N order(s) were TRANSMITTED (ids ...)", names the scoped halt file, points to ops.replay_ledger, warns against rebuild_ledger on an epoch'd book. NEW `src/deploy/tests/test_desync_records_orders.py`.
**2.2.7 reconcile_orders never says "agree" about a skipped check (A6, C13b, verify-first).** `ops/reconcile_orders.py::run`: without --check-broker print `orders OK; ledger-vs-account NOT CHECKED`; a transmitted order-map row at or after the epoch with no ledger row -> problems, exit 1; orders section compares the order map with broker executions. NEW `ops/tests/test_reconcile_orders.py`. Must-have because the runbook leans on this tool.
**2.2.8 String sweep.** NEW test asserting no user-facing string in src/deploy/run_book.py, ops/ledger.py, ops/reconcile_orders.py, ops/doctor.py, ops/capture_fills.py, docs/INFRASTRUCTURE.md, .claude/README.md recommends rebuild_ledger or reset_epoch for an epoch'd book.

### WS3 - order-path safety (branches from the WS2 tip)
**2.3.1 Every leg of an MOC sleeve is MOC (C3, hard rule 3).** `ibkr.py::place_targets/_order`: resolve order type once per sleeve from `self._sleeves[name]["spec"]["frozen"]["order_type"]`; apply to every non-option, non-bond, non-combo leg including sleeve FLATs, the held-but-unmentioned flatten (~1227) and the kill-switch flatten (portfolio.py:186). Absent key = today's MKT. No meta stamped on FLAT targets. **Keep `test_sell_side_share_order_is_unchanged` untouched.** NEW tests through place_targets with a registered sleeve: sleeve FLAT -> MOC; held-but-unmentioned -> MOC; kill-switch flatten via PortfolioOrchestrator -> MOC; the same three on a spec with no order_type stay MKT. Each MOC case seen failing with 'MKT' first.
**2.3.2 DRY_RUN=1 and the halt win below the launcher (C5, C6v verify-first, hard rule 4).** `run_book.main` before make_broker, when execution == ibkr and not --dry-run: (a) DRY_RUN=1 -> print why, run nothing, write nothing, return 9 (not a DryRunBroker run, which would write a flat book_status.json into the live root); (b) `ops.halt.read_halt(book_id)` active -> print, return 10; (c) --job required. NEW `src/deploy/tests/test_dry_run_always_wins.py`, `test_run_book_respects_halt.py`: patch `src.deploy.run_book.make_broker` (the name run_book calls) to raise AssertionError and assert it was not reached; assert the books-root is byte-unchanged.
**2.3.3 Margin gate fails closed (G2, C9, F8); it is the only automated risk gate (G8v).** `ops/preflight.py::check_margin`: when check_broker passed and want_live, an exception or non-finite Cushion/NetLiquidation/GrossPositionValue -> ok=False, blocking=True, "margin UNMEASURED - not arming"; `math.isfinite`; one bounded retry with a fresh client id (contention unproven); --no-live -> ok=False non-blocking; floor stays 0.10. NEW `ops/tests/test_margin_fail_closed.py` (TimeoutError, missing Cushion, 0.09 block; 0.175 passes). The 12:00 retry recovers an unreadable morning.
**2.3.4 No silent NAV fallback on a funded sleeve (G5, C10).** `ibkr.py::_sleeve_nav`, `portfolio.py:175`: once a ledger dir with a manifest exists, unreadable/empty/non-positive NAV raises SleeveNavUnknown; capital fallback only for a never-funded sleeve and it prints; every armed log prints `sizing NAV $X as of <date> (source: shadow ledger)`. Outcome rc 7, never a halt. NEW `src/deploy/tests/test_sleeve_nav_no_fallback.py`.
**2.3.5 Second lock for the deferred books (D16).** RC sets DRY_RUN=1 in `ops/schedule/benchmarks.env` and `phase0.env` (tracked, reaches prod through the tag). NEW `ops/tests/test_deferred_books_locked.py`; Phase 8 flips it in its own tag. Verify-first: check no test or doc_audit rule pins those values.

### WS4a - fetchers (independent files; merges early so H11 can run)
**2.4.2 fetch_daily (F1, F2, B7v, D4v, F8v).** `scripts/cef/fetch_daily.py::refresh`: drop non-finite or non-positive close/NAV rows before the concat; completeness = close finite >0, volume >0, NAV finite >0 for every deployed name, INCOMPLETE names ticker and field, rc 4; prove completeness on disk before any network call and return 0 when complete (the morning case); when fetching, deployed names first, count and print `fetched px a/b nav c/d`, abort rc 14 once the first K deployed names all fail, print "NAV freshness NOT EVALUATED" when nothing was fetched. Every test monkeypatches PX_PATH, NAV_PATH, OUT to tmp_path and asserts the real files' sha unchanged. NEW `scripts/cef/tests/test_fetch_daily_completeness.py`, `test_fetch_daily_offline.py`, `test_fetch_daily_counts.py`. `fetch_borrow_rates.py`: REBATE_RATE opt-in (verify-first).
**2.4.3 Distribution fetcher (F6, G3, G7v).** Commit A, pure refactor: move top-level code into `main(argv, fetch_fn=..., out_dir=...)` behind `if __name__ == "__main__"`. Failing-first is an **AST test** (module has only imports, defs, constants and the main guard at top level) so nothing is executed against old code; an import test follows only after the AST test passes. Commit B: merge forward (concat, drop_duplicates on ticker/ex_date keep last); build all four frames in memory, validate all, write nothing if any universe name is missing, shrank or moved its last ex_date back, naming tickers; `--out-dir`. NEW `scripts/cef/tests/test_distributions_merge_forward.py` with a fake fetch_fn and tmp out_dir.

### WS4b - sleeve (after WS3; live-path, no-op proof)
**2.4.1 A missing input is never a liquidation (F1, D3v, D3, C3 item 3).** `src/deploy/sleeves/cef_discount.py`: value a held name at its own last valid close (`px[tk].ffill().iloc[-1]`); a held name with non-finite z or absent from px.columns raises NEW SleeveCannotDecide naming ticker, date, input; the four whole-book branches raise when any holding is non-zero; a flat book keeps today's FLAT list. `portfolio.py::advance` and `run_book.py`: live -> skip place_targets entirely and re-raise -> rc 8 with alert, no halt (never call place_targets with an empty list); dry-run/replay -> log the day and hold. `run_book.py::_cef_px` raises if the distributions file is absent (keeps fillna(0.0) for non-ex-dates). NEW `src/deploy/tests/test_cef_missing_pair_never_flattens.py`, `test_cef_px_requires_distributions.py`. Sleeve no-op proof of P.5 including the expected-difference controls.

### WS8a - repair tool, cross-check, preview
**2.5.1 NEW `ops/replay_ledger.py` (A2).** `--books-root` and `--sleeve` required; `--through`; dry-run default; `--apply`; `--attest-no-trade <date> --reason`; `--remark-epoch-at-panel-close`; `--accept-stale-distributions "<reason>"`. Guards on --apply: inside ~/prod requires `--allow-prod` and the book's scoped halt ACTIVE ("halt the book first"), no com.quantt session pid in `launchctl list`, no order-map row headed for an unclosed auction; inside any other git work tree always refuses; scratch roots need no halt. Steps: back up the sleeve dir to `_ibkr_shadow/_prereplay_<sleeve>_<stamp>/`; record_orders for each post-epoch order-map row without a ledger row (decision price = panel close on asof, reason `order_map id=N`); advance one trading day at a time, record from `captured_executions(state, day)` covering [day] only if `capture_covers` vouches, else raise; prices, costs and run_spec built exactly as the orchestrator builds them (book_price_loader with the distribution join, config/costs.yaml, min_trade_usd from the spec); assert per instrument epoch + sum of signed executions == held_shares and every post-epoch execId in exactly one trade row; refuse a sleeve with a contested symbol; refuse --apply when a held name's last ex_date is more than 35 calendar days before --through unless accepted with a reason. The epoch is found from the nav.csv decision=epoch row. **Attestations, the epoch-mark choice, the manifest's epoch* keys and the source shas go to NEW append-only `_replay_log.jsonl` beside the ledger, which save() never touches.** Tests NEW `ops/tests/test_replay_ledger.py` (incident fixture): dry run changes no hash; apply through 09-17 gives the 17-name table of finding A2, 8 trades, nav rows 09-14..09-17, byte-identical backup; naive 4-row injection re-raises on 09-15; removed capture row raises; second apply is a no-op; **apply through D then through D+2 extends without re-booking execIds and refuses if an in-between day is uncovered and unattested**; after apply with an attestation, one ordinary advance()+save() leaves the attestation, reason and epoch keys readable; attestation refused when an order-map row targets that auction; guards refuse as listed.
**2.5.2 Independent cross-check (replaces the nextgen cross-check, which its schema check refuses).** NEW `ops/crosscheck_positions.py`, read-only: epoch positions.csv + sum of signed broker_fills.csv executions by execId, compared name by name with (a) the replay output and (b) each day's `_broker_archive/<date>/broker_*.json` positions for 09-14, 09-15, 09-16, 09-17 (no 09-18 snapshot exists). Must match 17 of 17, exact. The snapshots are the independent evidence. The nextgen `--check` is optional and informational only; if used, the archive is converted by a scratch-only adapter, labelled converted, never committed.
**2.5.3 NEW `ops/preview_orders.py`, read-only (G1) - the re-arm gate.** Inputs: sleeve class of the tree it runs in, held shares from the repaired ledger, the ledger's sizing NAV, panel asof, optional `--broker-snapshot`. Applies `ibkr._resolve_qty`. Header: `git describe`, HEAD sha, spec_id, ledger last_date, sizing NAV with date, sha256 of the three panels; refuses if the tree is not exactly at a tag (tests pass `--allow-untagged`), if the pair for asof is not value-complete, or if ledger holdings differ from the snapshot (prints the divergence, no clean table). Prints per-name side, quantity, order type, notional, % NAV, post-trade gross and net, long-to-short flips. Tests NEW `ops/tests/test_preview_orders.py`: preview equals what stub-IB place_targets transmits, name/side/quantity; a one-name holdings divergence is flagged and refused.

### WS8b - harness and multi-session test (2.5.4, Phase 4.0)
**2.5.4 NEW `src/deploy/tests/test_live_path_multi_session.py` (A4).** IBKRBroker with stub ib under the clock seam, transmit lock released explicitly between sessions: epoch seed; morning D; real `capture_fills.capture()` against the stub's fills(); morning D+1; no-order day; two non-armed days then an armed session; one missed session with open rows. After each step: ledger positions == stub account, no halt, every execId booked once, every leg MOC. Fails today at step 2. `test_every_halting_exception_is_tested`: each halting exception must appear inside a `pytest.raises` in a test that reaches it through place_targets or advance.

## Phase 3 - Infrastructure hardening
**3.1 [HUMAN today] Alert transport on, prod only (B4, F3).** H3. Not in dev: a dev-side alert during the first armed morning could prompt a wrong cancel. Expect about 5 NOT TRADING emails a day until halts clear (F3).
**3.2 [AGENT WS5] Delivery on demand; watchdog truth (F3, B8v, F4, B7).** `ops/halt.py` NEW `main()` `--test-alert [--no-speech]` (exit 0 only if email True; writes `ops/schedule/logs/alert_receipt.json` in the sending tree, a path promote.sh's STATE_EXCLUDES already covers; add a promote-gate test that it never counts as dirty code); NEW `all_active_halts()`. `ops/doctor.py::failures()` gains one line per active halt with age, the last verify beat when not ok or email_delivered false, cef_pm and verify in the heartbeat list, email-unconfigured FAIL in failures() only (never in doctor.main(), which would make promote.sh roll back over an untracked file); staleness = expected to have fired by now and no beat dated today. NEW `ops/tests/test_alert_delivery.py`, `test_watchdog_sees_scoped_halts.py`.
**3.3 [AGENT WS5] A failed fill capture alerts (F5).** `ops/capture_fills.py::main`: any exception or non-zero result calls `ops.halt.alert("fill capture FAILED ...")` before returning non-zero; no automatic retry. NEW `ops/tests/test_capture_failure_alerts.py`.
**3.4 [AGENT WS5] Doctor sees this week's machine faults (B1, B6, F6).** check_ibc FAILs when com.quantt.ibgateway is disabled or absent from launchctl list, remedy text `enable` then `bootstrap`, ps read moved onto `_cmd`; NEW WARN-only check_reboot_survival; per-held-name distribution staleness WARN. NEW `ops/tests/test_doctor_ibgateway.py`, `test_doctor_reboot.py`, `test_doctor_distributions.py`.
**3.5 [AGENT WS5, verify-first] Dashboard (F10).** `api_connect` (still the only non-GET route): probe first, 409 when the gateway answers, refuse 09:25-17:45 ET on trading days unless the probe fails, require X-Requested-With. `api_verify` passes notify=False. **Every test monkeypatches `dashboard.server.subprocess.run` with a recorder before the first POST and asserts on recorded argv, never machine state**; failing-first evidence is "the recorder saw bootout where none was expected". WS0's launchctl guard is the backstop.
**3.6 [AGENT writes WS9; HUMAN applies after promotion] Launcher patch.** NEW `ops/schedule/patch_launch_job_hardening.py`: dry-run default, `--target`, anchors matching exactly once, `.bak-<stamp>`; `--apply` on the default target refuses when PYTEST_CURRENT_TEST is set or stdin is not a tty; tests always pass `--target tmp`. Contents: (a) NEW pure function `_human_halt(process_env, file_env)`, capturing the process DRY_RUN before the file env is merged; (b) refresh gets `budget_min=phase_budget(reserve_min=30)`, rc 124 -> refresh_ok False; (c) a refresh stand-down alerts and lands in the beat's blockers; (d) watchdog print carries a timestamp. Rules: the patch calls nothing absent from the promoted tag **or from the rollback target**; `halt_mod.beat()` stays ahead of any new report-phase code. Tests NEW `ops/tests/test_patch_launch_job_hardening.py`: apply to a temp copy, exec only `_human_halt`, assert the truth table (proc 1, file 0) True; (0,1) True; (unset, unset) True; (0,0) False; the env handed to the run_book subprocess carries DRY_RUN=1 when either source said 1.
**3.7 [AGENT WS6] Definition of done becomes measurable (B5).** `ops/session_uptime.py`, `.claude/hooks/book_state.py:318`: exact-name filter, raise on job mismatch; key sessions on the auction date (cef_<D> -> D; cef_pm_<D> -> next_trading_day(D)); widen RE_GUARD; "two logs, same tree" wording; **clean = armed + book run ok + status ok + no DESYNC or REFUSE-to-book line + verifier verdict status exactly PASS (absent, UNVERIFIED and FAIL are not clean)**. Tests: `test_the_evening_jobs_log_is_not_the_morning_jobs_verdict`; the 09-14 shape with the REFUSE line is not clean; the 09-17 (FAIL) and 09-18 (UNVERIFIED) verdict shapes are not clean.
**3.8 [TEAM LEAD decides D3, then AGENT WS5] Off-machine dead-man (B6).** The 16:20 verifier and the morning preflight GET a URL from config/.env; best-effort, 3 s timeout, never able to change an rc; no URL -> WARN line. In repo code (verify_session.py, preflight.py). NEW `ops/tests/test_deadman_ping.py` (uses the `real`-network opt-out only with urlopen stubbed).
**3.9 [HUMAN] Machine.** H6; confirm `pmset -g | grep -i sleepdisabled` prints 1 and AC power; planned restarts with `sudo fdesetup authrestart`; after an unplanned reboot a human must log in. The cause of the 08:30 DNS outages and of the two reboots is UNMEASURED.
**3.10 [AGENT WS7] promote.sh hardening (E2, E4v, E5v, E6v).** `ops/promote.sh`, NEW `ops/restore_state.sh`, `ops/tests/test_promote_gate.py`: (a) doctor from the current prod tree before the checkout, exit 2 with HEAD untouched; (b) guard 1b over every loaded com.quantt.* row with a numeric pid except dashboard, awake, ibgateway; (c) `git ls-remote --exit-code --tags origin` and peeled-sha compare; (d) after forward checkout refuse on unmerged paths or `^<<<<<<< ` under ops/books/*_live; (e) rollback: first verify the archive exists and `tar -tzf` lists every allow-listed path (else refuse to roll back and write ops/HALT.md), then `git checkout -f --detach "$PREV"`, restore only allow-listed paths, extract the archive to a temp dir and `diff -rq` against the restored paths, assert no unmerged paths, no markers, describe == $PREV, else write ops/HALT.md with a plain-shell fallback and exit 3; never the `--merge` rollback; refuse to start if any com.quantt job is scheduled to fire within the smoke budget; (f) the clock guard learns the morning window from the cef plist starts plus the 120-minute ceiling. Rule recorded in docs/SYSTEM.md 4.1: a ledger repair is applied in prod to prod's files, never committed in dev. Prod's **old** promote.sh runs the RC promotion, so 5.3 carries these checks by hand.

## Phase 4 - End-to-end rehearsal (no possibility of transmitting)
**4.0 [AGENT WS8b] NEW `ops/rehearsal.py`**, never imported by live code. At start: refuses unless --root is outside data/ and `git -C <root> rev-parse --is-inside-work-tree` fails (covers wt/* and nextgen); installs netguard (connect, connect_ex, create_connection); replaces subprocess.Popen and friends with a raiser (a monkeypatch does not reach children); patches `ops.halt.REPO_ROOT`, HALT_PATH, HALT_ARCHIVE, HEARTBEAT_PATH under --root (scoped halts are built from REPO_ROOT, halt.py:74) and replaces alert with a recorder; injects the stub ib, never imports ib_async; sets the clock seam per simulated day; releases the transmit lock between sessions; reads data/ read-only and never calls a fetcher; snapshots `git -C <dev> status --porcelain` and `ls <dev>/ops/HALT*.md` before and asserts them unchanged after. Tests NEW `ops/tests/test_rehearsal_guards.py`: root inside any work tree refused; socket and asyncio attempts raise; the real `write_halt(book='cef_discount_paper')` lands under --root only; subprocess use raises; the wall-clock positive control of 2.2.0.
Per simulated day the harness runs the launcher-shaped sequence in-process: `session_plan.plan()` with the day's beats -> `preflight.run(..., books_root=<root>, want_live=False)` -> `run_book.main` **live branch** with make_broker patched to the stub-ib IBKRBroker (patch asserted hit) -> assert write-ahead rows == stub.placed -> `halt.beat()` with launcher-shaped detail -> at the next panel close the stub fills each MOC at the panel close (SYNTHETIC executions, commission from config/costs.yaml; they test our code, not the market) -> the real `capture_fills.capture()` reads the stub's fills() under the simulated clock -> verify_session's checks against the stub account. Per-day asserts: ledger held == stub account; no halt recorded; every synthetic execId once in trades.csv; NAV rows contiguous; every leg MOC; socket attempts 0; `_replay_log.jsonl` contents still readable.

| # | Rehearsal | Command | Expected | Proves | Cannot prove |
|---|---|---|---|---|---|
| R1 | Incident regression | `python3 -m pytest src/deploy/tests/test_two_session_replay.py src/deploy/tests/test_transmitted_orders_never_orphaned.py ops/tests/test_ledger_uncovered_day.py src/deploy/tests/test_multi_bar_catch_up.py src/deploy/tests/test_refuse_before_transmit.py -q` | pass; red evidence for each in failing_first/ | the 09-11/14/15 sequence books all 8 executions with no halt; a frozen ledger refuses before transmitting; write-ahead survives a post-transmit raise | anything about IBKR |
| R2 | Repair on the frozen copy | `python3 -m ops.replay_ledger --books-root <scratch>/rehearsal/run1/cef_live --sleeve cef_discount --through 2026-09-17`, then `--apply` | dry run changes no hash; apply gives the A2 table, 8 execIds once each, byte-identical backup, replay log written; both NAV classes reported | the repair works on the real files | that the account still holds those positions (H17) |
| R3 | Independent cross-check | `python3 -m ops.crosscheck_positions --books-root <scratch>/rehearsal/run1/cef_live --sleeve cef_discount` | 17 of 17 exact on each of 09-14..09-17 against the broker snapshots | two independent sources agree | 09-18 onward (no snapshot) |
| R4a | Incident-shaped multi-day run | harness from the frozen copy with post-epoch rows stripped from broker_fills.csv, _order_map.csv, _capture_log.csv (in scratch), stub seeded from epoch positions, sessions asof 09-11 (== last_date) through the panel's last date | per-day asserts hold | the literal first-session shape and following days on real state and real closes | real fills |
| R4b | Full pattern on a scratch epoch | harness builds an epoch about 20 panel dates back under --root (holdings = the sleeve's own target from flat, SYNTHETIC state) and runs: skip day, no-order day, two non-armed days then armed, one removed capture row | per-day asserts; the removed-capture morning refuses with `ib.placed == []` | multi-bar catch-up and refusal on real closes | - |
| R4c | Repaired copy forward | harness on the R2 output over whatever panel dates exist after --through; report how many there were | per-day asserts | continuity from the repaired state | little when only one bar exists |
| R5 | run_book gates | `python3 -m pytest src/deploy/tests/test_dry_run_always_wins.py src/deploy/tests/test_run_book_respects_halt.py src/deploy/tests/test_run_book_refusal_rc.py -q` | pass | hard rule 4 and the halt hold below the launcher; rc semantics | the launcher's own env merge (3.6 truth table, then H14 by hand) |
| R6 | Preflight ledger control pair | harness calls `preflight.run` with books_root | frozen input copy -> `[FAIL] ledger` naming the 4 unbooked 09-14 execIds (the 09-15 morning, caught); repaired copy -> `[PASS] ledger`; both lines recorded | the new gate discriminates | margin and broker, skipped by design |
| R7 | No-op proofs | P.5, both | cmp identical; mutation control differs; sleeve report's "other difference" = 0 | sim path and sleeve unchanged where they should be | - |
| R8a | Full suite, integration worktree | `python3 -m pytest` after every merge | exit 0 | no regression, hermetic | data-dependent tests may skip |
| R8b | Full suite, main dev tree, once at RC after ff-merge | `python3 -m pytest` | exit 0; session-finish panel hashes unchanged | data-dependent tests too | "a green suite says little about the code that places orders", hence R1-R6 |
| R9 | Hermeticity | `env HOME=<scratch>/emptyhome python3 -m pytest src/deploy/tests/test_decision_age_clock.py ops/tests/test_stuck_session_guard.py -q` | exit 0 | no verdict depends on the installed plist | - |
| R10 | Doctor | agent: `cd ~/prod/QUANTT && PYTHONDONTWRITEBYTECODE=1 python3 -B -m ops.doctor --quick`; human: full | no FAIL; human run exits 0 (run from prod; dev false-FAILs, B10) | the machine can run unattended now | tomorrow's reboot (3.8) |
| R11 | Docs | `python3 -m ops.doc_audit --check && python3 -m ops.prompt_status --check && python3 -m ops.orient` | exit 0, 0 DRIFT | documents still true | - |
| R12 | Promotion mechanics | `python3 -m pytest ops/tests/test_promote_gate.py -q` | pass incl. 3.10 cases | gate and rollback logic | the real promotion, run by the old script |
| R13 | Release gate | `ops/release_check.sh v2026.09.13.4` | exit 0 | frozen: specs and live state unchanged, no ng, clean, green, no HARDENING-RED left | - |
| R14 | Shadow morning in prod, halt on (HUMAN observes) | none; the scheduled 08:30 fire | bounded refresh; blockers are exactly `[FAIL] halt` and `[FAIL] ledger` (frozen ledger, names the unbooked execIds); numeric `margin: cushion`; NOT TRADING email on the phone; dry run; dead-man ping if D3 | promoted code runs under launchd with the real env, gateway, network, alert transport; the ledger gate FAILs correctly in prod | transmit and booking; the dry-run's held= is still the fossil _dryruns ledger (G1), use the preview |

**Stage coverage (every link of the session path; "first live" = only a watched live morning proves it)**
| Link | Covered by | Admitted gap |
|---|---|---|
| launchd -> launch_job.py (env merge, phases, budgets) | 3.6 text tests + `_human_halt` truth table; R14 for the not-armed path | the launcher's armed argv path: first live |
| session_plan.plan + pair/today guards | R4 every day; 2.1.3 tests | - |
| refresh fetch_daily | 2.4.2 tests with fake vendor; R14 | real vendor behaviour: R14 and first live |
| preflight.run | R6, R4 (want_live False), R14 | broker and margin checks live: R14 numeric margin |
| run_book.main live branch (gates, arm, rc handlers) | R4 with make_broker patched, R5 | real make_broker, from_env, ib_async handshake: first live |
| arm() attribution and decision age | 2.1.2 tests, R4 against stub positions | real ib.positions(): first live |
| sleeve decide + orchestrator | R4 on real panel, R7 | - |
| sizing, pre-transmit refusals, write-ahead | R1, R4, 2.5.3 | - |
| placeOrder / broker acceptance, short locates | nothing | first live (C11 parked: human reads TWS status) |
| post-transmit advance / booking | R1, R4 with synthetic fills | real commissionReports: second live morning |
| halt.beat / last_armed | R4, 2.1.3 | - |
| capture_fills.capture | R4 against stub fills() | real ib.fills() shape and client ids: first live 16:20 |
| verify_session | R4 checks against stub | real 16:20 run after the 12:00 beat: first live |
| multi-day catch-up | R1, R4b | - |
| alert delivery | 3.2 tests with smtplib stub; H3; R14 | launchd-context delivery: R14 |
| promote / rollback | R12 | the RC promotion itself (old script): H13 post-checks |

**What only watched live mornings can prove (checklist for A and A+1):** IBKR accepts each MOC including short sells (available_shares is NaN for every name in cef_borrow.csv, so locate is UNMEASURED); no silent rejection (transmission is fire-and-forget, C11 parked, human reads TWS before 15:30); the stamped orderId matches IBKR's; perm_id still 0 (C8 parked); next-morning booking with real commissionReports; verifier PASS after the 12:00 beat; email from the launchd context; the 08:30 network; numeric margin under real client-id traffic; the 12:00 retry arming (seen only on a failed morning); distribution cash against the IBKR statement including payment-in-lieu; the launcher's armed path and the real broker factory.

## Phase 5 - Release candidate, tag, promotion
**5.1 [AGENT] Integrate** in the merge order of section A inside wt/integration; R8a after every merge; review each diff with `/code-review` and subagents quant-reviewer (no-op proofs), execution-trader (WS2, WS3), ops-watchdog (WS5, WS6). Human pushes hardening after each merge (H10). When R1-R13 are green: in the main dev tree `git merge --ff-only hardening-20260921` (touches tracked files only, never data/), then R8b. The tag is cut from main ("Never cut a tag off the prod tag", SYSTEM.md 4.1).
**5.2 [AGENT proposes, HUMAN runs] Tag and push.** H12.
**5.3 [HUMAN] Promote.** H13 with preconditions and post-checks. On `SMOKE FAILED ... rolling back`: `! git -C ~/prod/QUANTT describe --tags` must print v2026.09.13.4; if not, write the global halt (7.2 commands, shell fallback if the import fails), restore the named *_live paths from the H8/H13 archive by hand.
**5.4 [HUMAN] Launcher patch** H14, then doctor from prod.

## Phase 6 - Re-arm (CEF only; benchmarks and phase0 halts stay). Precondition: D7 signed.
**6.1 [HUMAN, day P after promotion] Dry-run the repair on prod** (writes nothing): proves the tool on prod state. H13b.
**6.2 [HUMAN, day S] Shadow morning (R14, D1).** H15. Cost: one trading day.
**6.3 [HUMAN, day S 12:30-16:00 ET] Repair through S-1, once.** H16. Preconditions: H11 done and diffed, D2 decided, no session pid, every day from the epoch to S-1 covered or attested (evidence/uncovered_days.txt). Read the dry-run table against R2 and R3, then `--apply`. Expected: the A2 table unless H2 showed otherwise, 8 execIds booked, a `_prereplay_` backup, replay log written. Reversible: restore that backup directory.
**6.4 [HUMAN] Reconcile against the broker** H17: 0 divergent on 17 names, else stop. `_attribution.json` is inert while the ledger is non-empty (G11b).
**6.5 [HUMAN] Evening check** H18: `cef_pm_<S>.log` preflight shows `[PASS] ledger` (and `[FAIL] halt`). If ledger FAILs after the repair: stop, do not clear.
**6.6 [HUMAN runs from prod, TEAM LEAD signs] Preview and margin** H19, about 22:45 ET after cef_pm writes pair S. The team lead signs the header (tag, sha, spec_id, last_date, sizing NAV, panel shas) and the table. For scale only, never reuse: the auditors measured 12 orders, $348,765, 69.75% of NAV for asof 09-18, driven by that day's panel. **Mandatory TWS what-if** on the basket; record initial margin, maintenance margin, post-trade cushion. Below 0.13 (G4's proposed alert level; D6) -> contingency 7.4 before clearing.
**6.7 [HUMAN] Clear the CEF halt: checked block, 23:40 S to 08:15 A only** H20. After 08:15, wait a day: the launcher reads the halt at the preflight boundary, which was as late as 09:50 on slow mornings, so a mid-morning clear arms the in-flight fire.
**6.8 [HUMAN watches, AGENT reads logs] First armed morning A** H21. Expected in `cef_<A>.log` in order: refresh "pair already complete on disk"; preflight all PASS with numeric cushion; `sizing NAV $... as of <S-1> (source: shadow ledger)` equal to the preview to the cent; `ARMED:`; the write-ahead line listing N rows; N placeOrder lines, all MOC, equal to the signed preview on name, side and quantity; `[shadow] ... advance through <S>: n_days=1`; `book run ok`; `done status=ok`. Compare by 10:30 ET.
**6.9 [HUMAN watches] Second morning A+1** H22: `booked N execution(s) from broker_fills.csv`, no DESYNC, no halt file, trades.csv gains N rows with execIds, reconcile 0 divergent. Only then is re-arm done and the 20-session clock started at A. AGENT: `/fill-audit` on the first fills; `/morning-brief` before each of the first five mornings.
**6.10** cef_pm stays RUNG-0 (DRY_RUN=1) through the acceptance window (D12).

## Phase 7 - Acceptance and rollback
**7.1 Acceptance**: section D, measured daily with `python3 -m ops.session_uptime --since <A> --target 20`.
**7.2 Rollback order: halt, launcher .bak, code.** `! cd ~/prod/QUANTT && python3 -c "from ops.halt import write_halt; write_halt('manual stop: rolling back <tag>', source='human', book='cef_discount_paper')"`; then copy `launch_job.py.bak-<stamp>` back; then `! ~/prod/QUANTT/ops/promote.sh v2026.09.13.4`. **Never clear_halt while `git describe` prints v2026.09.13.4: that tag is the defect**, and a ledger holding write-ahead rows under old code behaves like the pre-fix guard. Global halt (failed rollback, unknown tree): `! cd ~/prod/QUANTT && python3 -c "from ops.halt import write_halt; write_halt('promotion rollback failed: prod at unknown tag', source='human')"`; if the import fails: `! printf '# HALT\n%s human: promotion rollback failed\n' "$(date)" > ~/prod/QUANTT/ops/HALT.md` (verify-first: the implementer confirms `_parse_halt` treats any existing HALT.md as active). Ledger rollback: restore `_prereplay_cef_discount_<stamp>/` or the named *_live paths from a state archive, never ops/books whole; then reconcile --check-broker.
**7.3 Stop conditions.** Cancel in TWS **by 15:30 ET** (15:50 is the hard NYSE limit) and write the scoped halt when: a transmitted order differs from the signed preview on name, side or quantity; any non-MOC order type on a CEF leg; the armed log's sizing NAV differs from the preview; an order Inactive or Cancelled with an error. Cancelled write-ahead rows close as `skipped` on the next advance. Write the scoped halt the same day and run `/incident` when: ShadowLedgerDesync; verifier FAIL on fills, positions or one_set_per_auction; `margin: skipped` or a non-numeric cushion in an armed log; cushion below 0.10; a trading day with no 16:20 verifier email by 17:00 ET (the expected daily message; while halted, the per-fire NOT TRADING emails) or a missed dead-man ping.
**7.4 Margin contingency and deadlock exit (G4).** If the what-if or a live cushion is too low, the book cannot de-gross itself (preflight blocks gross-reducing sessions too). No new code: an agent tabulates, read-only, per-sleeve null_trader quantities from the phase0 ledger against the H2 broker read and flags contested symbols (HYG, LQD and the rest) with the quantity attributable to each book; the human named in D6 flattens those quantities by hand in TWS (recommended MOC), never the account net (landmine 7); the phase0 halt stays on and the ledger consequence is recorded as a known divergence for Phase 8.
**7.5 Armed day, capture lost.** Alert from 3.3 fires -> the later scheduled captures are the first remedy; before the nightly gateway restart the human may run the capture by hand (opens a read-only broker socket). If every capture is lost: write the scoped halt; later mornings refuse before transmitting (correct). The exit is a team-lead decision (D17): either a statement-ingest mode for replay_ledger, built only once a real IBKR Flex/Activity export exists to define the parser (H23 supplies the first sample), or a fresh epoch. rebuild_ledger and reset_epoch stay forbidden on cef without that decision.

## Phase 8 - Deferred books (after A+1; not part of "deployed")
8.1 Benchmarks (A5): stay halted and DRY_RUN=1 until the RC is live (D7, D16). Then on a scratch copy first: re-seed b3, b4, b5 from the broker (solely owned symbols), reconcile to the broker snapshot, named test `ops/tests/test_benchmark_reseed.py`; b1 and b6 (contested HYG) need ledger count plus order-map-attributed executions, which no tool does today; reset_epoch opens a socket even in dry run and hard-codes epoch_reason (A10); b4 needs a local SPY close; C8 attribution keys fixed first. Un-halt criterion: reconcile --check-broker 0 divergent per sleeve and the multi-session test passing for a multi-sleeve book. 8.2 phase0 retirement (A7v, A8, G4, G11): the 09-13 note cannot run as written (11 never-transmitted open rows make the guard refuse; gross_leverage still 1.0; LQD disposition unrecorded); needs a tool mode closing never-transmitted rows as skipped, or 7.4's by-hand flatten; timing D6.

## A. Workstreams (each in its own worktree under ~/Desktop/2027/QUANTT/wt/<id>, branching from hardening after WS0)
| Merge | ID | Scope | Depends |
|---|---|---|---|
| 1 | WS0 | netguard, root conftest, session_rc, freeze record, release gate, settings proposal, docs hygiene | - |
| 2 | WS1 | hermetic schedule tests, noon retry, armed-beat carry, non-transmitting rcs | WS0 |
| 3 | WS4a | fetch_daily, fetch_borrow_rates, distributions fetcher | WS0 |
| 4 | WS2 | clock seam, write-ahead, coverage, refuse-before-transmit, rc 7, desync, reconcile, preflight ledger check | WS0 |
| 5 | WS3 | MOC exits, DRY_RUN/halt/--job, margin, NAV, deferred-book lock | WS2 merged |
| 6 | WS4b | sleeve cannot-decide, _cef_px | WS3 merged |
| 7 | WS5 | alerts, watchdog, doctor, capture alert, dashboard, dead-man | WS1, WS3 merged |
| 8 | WS6 | session_uptime, book_state | WS0 |
| 9 | WS7 | promote.sh, restore_state.sh | WS0 |
| 10 | WS8a | replay_ledger, crosscheck_positions, preview_orders | WS2 API; WS3 for preview |
| 11 | WS8b | rehearsal harness, multi-session test, noop_proof | WS2, WS3, WS4b |
| 12 | WS9 | launcher patch tool | session_rc (WS0), WS5 alert names |
Parallel after WS0: WS1, WS2, WS4a, WS6, WS7, WS9 skeleton; WS8a when record_orders is fixed; WS3 after WS2; WS5 after WS1. Collisions: ibkr.py WS2->WS3; run_book.py WS2->WS3->WS4b; portfolio.py WS3->WS4b; preflight.py WS2->WS3->WS5; halt.py, doctor.py, verify_session.py WS1->WS5; capture_fills.py WS2->WS5. Gates: R8a after each merge; R1-R13 after the last. Every session starts with `python3 -m ops.orient` and docs/SYSTEM.md.

## B. Human runbook
See the structured runbook (H1-H23) delivered with this plan; it is in execution order with precondition and expected output for every line.

## C. Decisions only the team lead can make
D1 shadow morning (yes). D2 epoch mark: re-mark at the panel close, shares unchanged, NAV $500,000, removing a phantom -$2,089.47 on the first booked day (G6v), or keep broker marks; never silently. D3 off-machine dead-man (yes). D4 preflight blocks on unconfigured email (no). D5 automatic macOS installs off (yes; two updates pending). D6 phase0 timing, the 0.13 what-if threshold, and the named person who de-grosses by hand. D7 benchmarks stay halted until after A+1, a temporary departure from "keep the five benchmarks" (accept; signed precondition of Phase 6). D8 cannot-decide: raise (recommended) vs per-name HOLD, decided with the measured raise frequency from P.5. D9 fetch_daily skips when the pair is value-complete on disk (yes). D10 noon-retry clock in repo now (yes). D11 pre-trade gross cap (park; the signed preview substitutes). D12 cef_pm RUNG-0 through the window (yes). D13 accept the strategy's own first order set (yes; staging is a strategy change). D14 nextgen and spec v7 parked and pushed, never merged. D15 CLAUDE.md wording (landmine 3 first half, "dollar-neutral by construction"): the team lead edits. D16 DRY_RUN=1 in benchmarks.env and phase0.env in the RC (yes). D17 lost-capture exit: statement-ingest tool once a sample exists, or fresh epoch. D18 apply settings_proposed.json. D19 off-disk backup destination (no external volume is mounted). D20 timing criterion and verifier strictness: launch-to-trade at most 30 minutes on complete-pair mornings (proposed; healthy mornings measured 0.7-9.2 [S]); UNVERIFIED verifier days break the streak (recommended strict).

## D. Numeric acceptance criteria for "deployed" (command; threshold; action on failure)
1. `python3 -m pytest` exits 0 at the promoted tag in wt/integration and in the main tree; R9 exits 0. Fail: no tag.
2. `ops/release_check.sh v2026.09.13.4` exits 0; spec_id still cef_discount.v6.20260906. Fail: no tag.
3. Repair: 8 of 8 post-epoch execIds each in exactly 1 trades.csv row; `ops.crosscheck_positions` 17 of 17 exact on each of 09-14..09-17 against the broker snapshots; `reconcile_orders --check-broker` 0 divergent on 17 of 17. Fail: do not clear.
4. First armed session: transmitted set == signed preview on (name, side, quantity), 0 differences; write-ahead open rows == order-map rows for that asof; 100% MOC; every fill's execution time converted to America/New_York is at or after 15:59:00 (findings: all 45 prior CEF fills printed 15:59 ET), checked with /fill-audit. Fail: 7.3.
5. Second session: 100% of the prior day's executions booked, 0 halt files, reconcile 0 divergent. Fail: halt, /incident.
6. `grep -c "margin: skipped" cef_<date>.log` = 0 and a numeric cushion >= 0.10 in every armed log. Fail: halt.
7. `grep -c "email: not configured"` = 0 in every log after H3; test alert received off-machine; dead-man pinged each trading day if D3. Fail: streak resets; fix before the next session.
8. Launch-to-trade boundary at most 30 minutes on complete-pair mornings (D20), never beyond the 120-minute ceiling. Fail: streak resets.
9. **Definition of done:** `python3 -m ops.session_uptime --since <A> --target 20` exits 0: 20 consecutive eligible sessions armed and clean (3.7 definition, verifier PASS required), with 0 halts, 0 ShadowLedgerDesync, 0 non-MOC CEF orders, 0 uncovered days (capture row at or after 16:00 ET, unattributed 0, on 20 of 20).
10. Only broker-confirmed fills count; modelled and rehearsal sessions count for nothing.
Streak resets only: a non-armed eligible day with a named alerted reason (rc 4/7/8, margin UNMEASURED at both fires, vendor rc 14), verifier UNVERIFIED, criterion 7 or 8 miss. Halt and 7.2/7.3: any 7.3 condition.

## E. Parked (nothing here blocks re-arm)
A10 reset_epoch --reason and offline dry run. B10 doctor job list and dev false FAILs. B11/F12 atomic heartbeat and flock (first item after re-arm). B12 awake expiry. C7v order-map-backed guards (B3's carry is used instead). C8 perm_id and client-id keys (required before benchmarks or phase0). C11 order acknowledgement wait and G9's verifier retry (first candidates after acceptance; until then the human reads TWS status). C12 early-close table. C14 remaining fallbacks. D4 one-share rounding (cannot halt after 2.2.1), D5-D8. E3's tag-annotation requirement. F7/F7v panel manifest and atomic_write shrink guard: the wrong-order path is closed by 2.4.1 and 2.4.2, the dev-tree rewrite path by the 0.3 deny rules and the WS0 data guard; only availability remains. F8 API-level broker probe. F9 signal-date assert. F11. Scheduling the distributions fetcher. G1(b) DryRunBroker holdings source. G6 gross cap. G7/G8v drawdown governance stays deliberately off pending W6 Part A; do not rename kill_drawdown (the /100 trap would arm a kill at -0.18%). G9 track_record.py. G10 wording. G11 _attribution.json. Porting the nextgen repair tool. Moving data/ out of the symlink. The 2 unguarded ib_insync imports in scripts/rv. Statement-ingest for replay_ledger (D17).

## F. Verify-first register
Single-source verifier additions: A6v, A7v, A8v, B7v, B8v, B9v, C6v, C7v, C8v, D3v, D4v, E4v, E5v, E6v, F7v, F8v, F9v, G6v, G7v, G8v. Below threshold: A6-A10, B7-B12, C6-C14, D3-D8, E4-E8, F7-F12, G6-G11. Added by this revision: permission-rule glob syntax and whether deny rules touch `! ` lines; whether any existing test needs a socket; whether any test or audit pins the benchmarks/phase0 env values; `_parse_halt` on a hand-written HALT.md; alert_receipt.json under STATE_EXCLUDES; whether a TWS what-if works off-hours [U]. Still UNMEASURED and never relied on: current broker positions until H2; true sleeve NAV; cause of the 08:30 DNS outages and of the reboots; who disabled ibgateway; whether reqAllOpenOrders sees other client ids; IBKR paper's treatment of a late MOC; short-sale availability; September ex-dates for the unfetched names; how a session reads a ledger containing conflict markers; correctness of the nextgen repair tool.

## G. Paths
Dev `/Users/simonjarvis/Desktop/2027/QUANTT/2027` (main, db795a9; never switched). Integration worktree `/Users/simonjarvis/Desktop/2027/QUANTT/wt/integration` (NEW). Prod `/Users/simonjarvis/prod/QUANTT` (v2026.09.13.4). Nextgen `/Users/simonjarvis/Desktop/2027/QUANTT/nextgen`. Launcher `/Users/simonjarvis/Library/Application Support/quantt/launch_job.py`. Auditor scratch `/private/tmp/claude-501/-Users-simonjarvis-Desktop-2027-QUANTT-2027/3c74bdb2-5b02-4396-b033-786c957c35ef/scratchpad/` (copied to results/ops/hardening_2026-09-21/templates/ in 0.1). Human outputs `~/prod-backups/rearm/`.
Live-path files changed: ops/ledger.py, ops/clock.py (NEW), ops/ledger_check.py (NEW), ops/live_roots.py (NEW), ops/session_rc.py (NEW), src/deploy/broker/ibkr.py, src/deploy/broker/simulator.py, src/deploy/run_book.py, src/deploy/portfolio.py, src/deploy/sleeves/cef_discount.py, ops/preflight.py, ops/halt.py, ops/session_plan.py, ops/decision_age.py, ops/doctor.py, ops/verify_session.py, ops/capture_fills.py, ops/reconcile_orders.py, scripts/cef/fetch_daily.py, ops/schedule/benchmarks.env, ops/schedule/phase0.env. Other NEW: conftest.py, ops/netguard.py, ops/replay_ledger.py, ops/crosscheck_positions.py, ops/preview_orders.py, ops/rehearsal.py, ops/noop_proof.py, ops/release_check.sh, ops/restore_state.sh, ops/schedule/patch_launch_job_hardening.py, and the tests named in each step.

---

# Appendix 1 - Human runbook (H1-H23), structured
*Every line is run by the team lead with the `! ` prefix or in a separate terminal. No agent runs any of these.*

## H1 - TODAY (Mon 2026-09-21) before 16:00 ET

- **Why:** No gateway means no fill capture (09-21 becomes an uncovered day needing attestation) and every promotion rolls back at the doctor smoke step.
- **Check first:** ! pmset -g batt  shows 'AC Power'; ! ls ~/prod/QUANTT/ops/HALT*.md  lists all three files (benchmarks_paper, cef_discount_paper, phase0_null) - stop if any is missing, because all three job envs say DRY_RUN=0 EXECUTION=ibkr and the halt files are the only lock once the gateway is up
- **Command:** ! launchctl enable gui/$(id -u)/com.quantt.ibgateway && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.quantt.ibgateway.plist   # wait ~90 s, then: ! cd ~/prod/QUANTT && python3 -m ops.doctor
- **Expected:** [PASS] broker 127.0.0.1:4002, [PASS] ibc IBC is managing the gateway, exit 0 ([WARN] alerts acceptable until H3). If bootstrap says already loaded: ! launchctl kickstart -k gui/$(id -u)/com.quantt.ibgateway. If doctor prints 'IBC ... NO CREDENTIALS': fix the IBC config yourself (agents never read ~/ibc), re-run doctor. Once a book is live never kickstart or bootout between 16:00 ET and that day's capture row.

## H2 - Today, after H1

- **Why:** Read-only broker truth (readonly=True, positions() only) before anything is repaired; this is the before-picture.
- **Check first:** H1 doctor exit 0
- **Command:** ! mkdir -p ~/prod-backups/rearm && cd ~/prod/QUANTT && python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json --books-root ops/books/cef_live --check-broker --client-id 137 | tee ~/prod-backups/rearm/H2_reconcile_before.txt   # informational repeats: --book ops/books/phase0_book.json --books-root ops/books/phase0_live ; --book ops/books/benchmarks_book.json --books-root ops/books/benchmarks_live
- **Expected:** Divergence on exactly six CEF names: AWF -638, JFR +1747, NEA +904, PDO -909, PFN +3725, PHK +1389. Any other divergence: STOP, the repair premise is wrong; team lead chooses replay vs fresh epoch. phase0: the 12 ledger symbols and no JAAA.

## H3 - Today

- **Why:** Every alert since go-live went nowhere; the SMTP path has never been exercised on this machine.
- **Check first:** none
- **Command:** Put a Google App Password in ALERT_SMTP_PASS in ~/prod/QUANTT/config/.env ONLY (not dev), chmod 600, never paste it elsewhere. Then: ! cd ~/prod/QUANTT && python3 -c "from ops.halt import alert; print(alert('QUANTT alert test','delivery test'))"
- **Expected:** {'notification': True, 'email': True} and the message arrives on a device that is not the Mac. Expect about 5 NOT TRADING emails a day until halts clear.

## H4 - Today, after agent steps 0.1-0.5 are committed

- **Why:** 52+ local-only commits, the incident diagnosis and all fix work sit on one disk.
- **Check first:** git -C ~/Desktop/2027/QUANTT/wt/integration status --short is empty
- **Command:** ! cd ~/Desktop/2027/QUANTT/2027 && git push origin main --tags && git push -u origin nextgen-20260914 docs-cleanup promote-align-20260911 hardening-20260921
- **Expected:** git ls-remote --heads origin lists five heads; git rev-list --count hardening-20260921 --not --remotes=origin prints 0. Repeat '! git push origin hardening-20260921' after every workstream merge.

## H5 - Today (after D5)

- **Why:** Two macOS updates are pending; an unattended reboot stops every job silently.
- **Check first:** D5 decided
- **Command:** ! sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticallyInstallMacOSUpdates -bool false ; ! pmset -g | grep -i sleepdisabled
- **Expected:** defaults read shows 0; SleepDisabled 1. Planned restarts: sudo fdesetup authrestart. After any unplanned reboot a human must log in (FileVault on, no auto-login).

## H6 - Today after 16:21 ET and every trading day until re-arm

- **Why:** capture_covers vouches for a day only with such a row; after the fixes an uncovered day refuses before transmitting.
- **Check first:** H1
- **Command:** ! tail -3 ~/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/_capture_log.csv
- **Expected:** A row dated today at or after 16:00 ET with unattributed 0. If none: tell the agent to add the date to evidence/uncovered_days.txt; it will need --attest-no-trade at H16.

## H7 - Today, after H1

- **Why:** Restore points must include the one unversioned order-path file (the launcher) and must not live only on the prod disk.
- **Check first:** An off-disk destination exists (D19: /Volumes shows no external volume today)
- **Command:** ! cd ~/prod/QUANTT && ops/backup_state.sh ; then ! cp ~/prod-backups/state_<stamp>.tgz "$HOME/Library/Application Support/quantt/launch_job.py" ~/Library/LaunchAgents/com.quantt.*.plist <off-disk>/ ; ! shasum -a 256 "$HOME/Library/Application Support/quantt/launch_job.py" ~/Library/LaunchAgents/com.quantt.*.plist | tee ~/prod-backups/rearm/launcher_sha_before.txt
- **Expected:** 'wrote ...state_<stamp>.tgz' (exit 0 or 2 acceptable). Never copy config/.env or the IBC config. Agent then runs the read-only restore drill (diff -rq shows no differences).

## H8 - When the agent delivers results/ops/hardening_2026-09-21/settings_proposed.json

- **Why:** Agents may not change permission settings; HEAD's allowlist pre-authorises 'python3 scripts/*', which covers the live MOC routing probe.
- **Check first:** Read the diff yourself: it only removes allows and adds one deny rule per verb/tool
- **Command:** ! cd ~/Desktop/2027/QUANTT/wt/integration && cp results/ops/hardening_2026-09-21/settings_proposed.json .claude/settings.json && git add .claude/settings.json && git commit -m 'Apply order-path deny rules (team lead)'   # then tell the agent to remove the HARDENING-RED marker in test_settings_order_path.py
- **Expected:** python3 -m pytest .claude/hooks/tests -q passes after the agent's follow-up commit. If deny rules block your own '! ' lines, run human steps in a separate terminal.

## H9 - After WS4a (merge-forward fetcher) is merged; outside 08:15-12:30 and 16:15-23:35 ET; books halted

- **Why:** The ledger books $0 for every missing ex-date; today's fetcher is a whole-panel rewrite that silently drops failed tickers into the file prod reads.
- **Check first:** ! grep -c drop_duplicates ~/Desktop/2027/QUANTT/wt/integration/scripts/fetch_cef_distributions.py prints >=1 and git log -1 --format=%s -- that file names the 2.4.3 commit; ! launchctl list | grep quantt shows '-' pid on every session job
- **Command:** ! cd ~/Desktop/2027/QUANTT/wt/integration && python3 scripts/fetch_cef_distributions.py --out-dir ~/prod-backups/rearm/dist_scratch   # agent compares all four files for the 17 names; only if it passes: ! B=~/prod-backups/dist_$(date +%Y%m%d_%H%M) && mkdir -p $B && cd ~/Desktop/2027/QUANTT/2027 && cp data/cef/cef_distributions.parquet data/cef/cef_splits.parquet data/cef/cef_dist_features.parquet data/cef/cef_facts.csv $B/ && cp ~/prod-backups/rearm/dist_scratch/* data/cef/
- **Expected:** Exit 0 with a per-ticker 'kept N, added M' report; agent check: no ticker lost, row counts never fall, last ex_date never moves back, September rows present or the gap named UNMEASURED. On any failure restore with cp $B/* data/cef/.

## H10 - RC ready: R1-R13 green and ops/release_check.sh v2026.09.13.4 exits 0

- **Why:** Prod only ever runs a commit origin holds under that tag.
- **Check first:** main fast-forwarded to hardening; R8b green in the main tree
- **Command:** ! cd ~/Desktop/2027/QUANTT/2027 && git tag -a v2026.09.<DD>.1 -m 'hardening: ledger integrity, MOC exits, fail-closed gates' && git push origin main --tags
- **Expected:** git ls-remote --tags origin | grep v2026.09.<DD>.1 prints the tag

## H11 - Day P, a trading day, start between 12:30 and 14:30 ET

- **Why:** The OLD promote.sh runs this promotion: its checkout --merge returns 0 with conflict markers and its rollback is unchecked, so its missing checks are done by hand.
- **Check first:** (a) cd ~/prod/QUANTT && python3 -m ops.doctor exits 0; (b) launchctl list | grep quantt shows '-' pid for every job except dashboard, awake, ibgateway - in particular cef_pm and verify.cef, which the old guard cannot see; (c) no job fires within the smoke budget (verify.cef fires 16:20); (d) tag on origin; (e) a fresh ops/backup_state.sh archive copied off-disk; (f) network up (the smoke runs fetch_daily)
- **Command:** ! ~/prod/QUANTT/ops/promote.sh v2026.09.<DD>.1   # then post-checks: ! git -C ~/prod/QUANTT diff --name-only --diff-filter=U ; ! grep -rl '^<<<<<<< ' ~/prod/QUANTT/ops/books/*_live ~/prod/QUANTT/ops/heartbeat.json
- **Expected:** promotions.log ends 'PROMOTED v2026.09.<DD>.1 (was v2026.09.13.4)', smoke log all PASS, both post-checks print nothing. On 'SMOKE FAILED ... rolling back': git -C ~/prod/QUANTT describe --tags must print v2026.09.13.4; if not, or if a post-check prints anything: write the global halt (step 22 commands) and restore the named *_live paths from the archive by hand.

## H12 - Right after step 11

- **Why:** DRY_RUN=1 must win from either source; the refresh gets a time budget; a refresh stand-down alerts.
- **Check first:** No session pid; shasum of the launcher matches launcher_sha_before.txt
- **Command:** ! cd ~/prod/QUANTT && python3 ops/schedule/patch_launch_job_hardening.py   # dry run, read the diff ; then ... --apply ; then ! python3 -m ops.doctor ; ! grep -n '_human_halt' "$HOME/Library/Application Support/quantt/launch_job.py" ; ! shasum -a 256 "$HOME/Library/Application Support/quantt/launch_job.py" | tee ~/prod-backups/rearm/launcher_sha_after.txt
- **Expected:** Doctor exits 0 with [PASS] entrypoint and [PASS] decision-age; grep shows the OR-merge function; a .bak-<stamp> exists. Rollback: copy the .bak back.

## H13 - Day P, after step 12

- **Why:** Proves the promoted tool on prod state without writing; the single apply happens on day S.
- **Check first:** No session pid
- **Command:** ! cd ~/prod/QUANTT && python3 -m ops.replay_ledger --books-root ops/books/cef_live --sleeve cef_discount --through <P-1> --allow-prod | tee ~/prod-backups/rearm/replay_dryrun_P.txt   # NO --apply
- **Expected:** Dry-run table equals rehearsal R2/R3 output; no file hash changes.

## H14 - Day S (next trading day), 08:30-12:15 ET, halt still on

- **Why:** Shadow morning (D1): the promoted code under launchd with the real env, gateway, network and alert transport, before an uncancellable MOC.
- **Check first:** none
- **Command:** Watch ~/prod/QUANTT/ops/schedule/logs/cef_<S>.log and your phone
- **Expected:** Bounded refresh; blockers exactly [FAIL] halt and [FAIL] ledger (names the unbooked execIds); numeric 'margin: cushion'; NOT TRADING email received; dry run; dead-man ping if D3.

## H15 - Day S, 12:30-16:00 ET

- **Why:** Single repair, through S-1, so the first armed advance (asof S) walks exactly one bar.
- **Check first:** Step 9 done and diffed; D2 decided; no session pid; every day from the epoch to S-1 has a capture row or is listed for attestation
- **Command:** ! cd ~/prod/QUANTT && python3 -m ops.replay_ledger --books-root ops/books/cef_live --sleeve cef_discount --through <S-1> --allow-prod [--attest-no-trade <date> --reason '<gateway down, book halted, no orders>' per uncovered day] [--remark-epoch-at-panel-close per D2]   # read the table against R2/R3, then repeat with --apply
- **Expected:** The 17-name table of finding A2 (unless step 2 showed otherwise), 8 execIds booked once each, a _prereplay_cef_discount_<stamp>/ backup, _replay_log.jsonl written. Reversible: restore that backup directory. Never run ops.rebuild_ledger or ops.reset_epoch on cef.

## H16 - Day S, immediately after step 15

- **Why:** The account is the fact; the ledger is a reconstruction.
- **Check first:** Gateway up
- **Command:** ! cd ~/prod/QUANTT && python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json --books-root ops/books/cef_live --check-broker --client-id 137 | tee ~/prod-backups/rearm/H17_reconcile_after.txt
- **Expected:** 0 divergent rows on the 17 CEF names, exit 0. Any divergence: STOP, do not clear the halt.

## H17 - Day S, after ~17:40 ET

- **Why:** The new gate must pass in prod, under launchd, on the repaired ledger before the halt is cleared.
- **Check first:** Step 16 passed
- **Command:** ! grep -n 'ledger\|halt' ~/prod/QUANTT/ops/schedule/logs/cef_pm_<S>.log | head
- **Expected:** [PASS] ledger and [FAIL] halt. If ledger FAILs after the repair: STOP.

## H18 - Day S, ~22:45 ET after cef_pm writes pair S

- **Why:** Nothing else previews the first armed order set; the scheduled dry-run sizes from a fossil ledger. The preview must run from prod at the tag, not from dev.
- **Check first:** Steps 16-17 passed
- **Command:** ! cd ~/prod/QUANTT && PYTHONDONTWRITEBYTECODE=1 python3 -B -m ops.preview_orders --books-root /Users/simonjarvis/prod/QUANTT/ops/books/cef_live --book /Users/simonjarvis/prod/QUANTT/ops/books/cef_discount_book.json --asof <S> --broker-snapshot /Users/simonjarvis/prod/QUANTT/ops/books/cef_live/_broker_archive/<S>/broker_<ts>.json --out ~/prod-backups/rearm/preview_<S>.md   # then a MANDATORY TWS what-if on the basket: record initial margin, maintenance margin, post-trade cushion
- **Expected:** Header shows the RC tag, HEAD sha, spec_id cef_discount.v6.20260906, last_date S-1, sizing NAV with date, three panel shas; a per-name table. Team lead signs header and table. What-if cushion below 0.13 (D6): run contingency 7.4 before clearing.

## H19 - Between 23:40 ET on S and 08:15 ET on A ONLY (after 08:15: wait a day)

- **Why:** The launcher reads the halt at the preflight boundary (as late as 09:50 on slow mornings), so a mid-morning clear would arm the in-flight fire.
- **Check first:** All must hold: launchctl list | grep quantt shows '-' for cef.daily and cef_pm; grep ^DRY_RUN ~/prod/QUANTT/ops/schedule/cef_pm.env prints DRY_RUN=1; grep -c FORCE_TRADE ~/prod/QUANTT/ops/schedule/cef.env prints 0; git -C ~/prod/QUANTT describe --tags equals the RC tag; grep _human_halt on the launcher shows the OR-merge; python3 -m ops.doctor exits 0; a FRESH reconcile --check-broker shows 0 divergent; every entry in ops/HALT_cef_discount_paper.md read against that broker output; preview signed; H3 email works
- **Command:** ! cd ~/prod/QUANTT && python3 -c "from ops.halt import clear_halt; clear_halt('ledger replayed through <S-1> with ops.replay_ledger on tag v2026.09.<DD>.1; reconcile --check-broker 0 divergent on 17 names; A1/A6v/C8v/C3 fixes promoted', book='cef_discount_paper')"
- **Expected:** [halt] cleared ops/HALT_cef_discount_paper.md -> ops/halts/HALT_cef_discount_paper_<ts>.md and a 'halt cleared' email. Never clear while describe prints v2026.09.13.4.

## H20 - Day A: 08:20 ET, then 08:30-16:21

- **Why:** First armed morning; only this proves broker acceptance, short locates and the launcher's armed path.
- **Check first:** ! shasum -a 256 ~/Desktop/2027/QUANTT/2027/data/cef/cef_prices.parquet ~/Desktop/2027/QUANTT/2027/data/cef/cef_nav.parquet ~/Desktop/2027/QUANTT/2027/data/cef/cef_distributions.parquet equals the preview header; if changed, re-write the scoped halt (step 22 command) and stand down a day
- **Command:** Watch ~/prod/QUANTT/ops/schedule/logs/cef_<A>.log; compare with the signed preview by 10:30 ET; read order status in TWS before 15:30 ET; after 16:21: ! tail -2 ~/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/_capture_log.csv
- **Expected:** In order: 'pair already complete on disk'; preflight all PASS with numeric cushion; 'sizing NAV $... as of <S-1> (source: shadow ledger)' equal to the preview to the cent; ARMED; write-ahead line with N rows; N placeOrder lines all MOC equal to the preview on name, side, quantity; 'advance through <S>: n_days=1'; 'book run ok'; 'done status=ok'. TWS: every order Submitted/PreSubmitted, MOC. 16:20 verifier PASS on decision, fills, positions, one_set_per_auction. Capture row at or after 16:00 ET with n_executions=N, unattributed=0. Any mismatch on name/side/quantity, non-MOC type, NAV mismatch or Inactive order: cancel in TWS by 15:30 ET and write the scoped halt.

## H21 - Day A+1, 08:30, then after the session

- **Why:** This is the session the incident broke.
- **Check first:** none
- **Command:** Watch cef_<A+1>.log; then the step 16 reconcile command
- **Expected:** 'booked N execution(s) from broker_fills.csv'; no DESYNC; no halt file; trades.csv gains N rows with execIds; reconcile 0 divergent. Only now is re-arm done; the 20-session clock starts at A.

## H22 - Any stop condition (7.3), rollback, or failed promotion

- **Why:** The old tag is the defect; a halt is the only safe state while prod sits on it.
- **Check first:** none - halt first, always
- **Command:** Scoped: ! cd ~/prod/QUANTT && python3 -c "from ops.halt import write_halt; write_halt('manual stop: <reason>', source='human', book='cef_discount_paper')"  | Global: ! cd ~/prod/QUANTT && python3 -c "from ops.halt import write_halt; write_halt('promotion rollback failed: prod at unknown tag', source='human')"  | if the import fails: ! printf '# HALT\n%s human: promotion rollback failed\n' "$(date)" > ~/prod/QUANTT/ops/HALT.md  | code rollback order: halt, copy launch_job.py.bak-<stamp> back, then ! ~/prod/QUANTT/ops/promote.sh v2026.09.13.4
- **Expected:** ls ~/prod/QUANTT/ops/HALT*.md shows the file; preflight blocks the next fire. An MOC cannot be cancelled after 15:50 ET; cancel by hand in TWS by 15:30.

## H23 - After step 21, then monthly

- **Why:** External authority for the track record; defines the parser for the lost-capture exit.
- **Check first:** Credentialed IBKR login
- **Command:** Pull the IBKR Activity or Flex statement for the period and keep the export
- **Expected:** Dividend and payment-in-lieu lines match the ledger's distributions_usd (G3, G9). The export is also the first real sample for a statement-ingest recovery tool (D17).

---

# Appendix 2 - Decisions only the team lead can make

**D1. Spend one trading day on a shadow morning (promoted code, halt on) before clearing the halt?**

- Options: yes / no
- Recommendation: Yes. One day against an uncancellable MOC; it is also the only in-prod proof that the new ledger gate FAILs correctly and that email arrives from launchd.
- Decision / signature / date: ______

**D2. Epoch mark convention (G6v, single-source, verify-first).**

- Options: re-mark the 09-11 epoch row at the panel close (shares unchanged, NAV $500,000), removing a phantom -$2,089.47 on the first booked day / keep broker live marks
- Recommendation: Re-mark at the panel close. Report both NAV classes until chosen; never pick silently; the choice is recorded in _replay_log.jsonl.
- Decision / signature / date: ______

**D3. An off-machine dead-man service (new external dependency).**

- Options: yes / no
- Recommendation: Yes. It is the only control for a dead Mac and the only standing proof that alerts deliver.
- Decision / signature / date: ______

**D4. Should preflight block arming when email is unconfigured?**

- Options: block / FAIL in doctor.failures() only
- Recommendation: Do not block. FAIL in doctor.failures() plus the dead-man; a preflight block checks presence, not deliverability, and adds a non-market reason to lose a session.
- Decision / signature / date: ______

**D5. Turn off automatic macOS installs, update by hand on Saturdays, use fdesetup authrestart for planned reboots.**

- Options: see question
- Recommendation: Yes. Two updates are pending now.
- Decision / signature / date: ______

**D6. phase0 retirement timing, the what-if threshold, and who de-grosses by hand if the cushion falls below 0.10.**

- Options: retire before re-arm / right after A+1; threshold 0.13 (G4's proposed level) or another
- Recommendation: Make the TWS what-if mandatory at the preview. If the projected cushion is under 0.13, run contingency 7.4 (by-hand flatten of per-sleeve phase0 quantities, never the account net) before clearing; otherwise retire right after A+1. Name the person now.
- Decision / signature / date: ______

**D7. Benchmarks stay halted until after A+1 (temporary departure from 'keep the five benchmarks').**

- Options: see question
- Recommendation: Accept and sign; it is a precondition of Phase 6. Un-halt condition: RC live, re-seed done on a scratch copy first, reconcile 0 divergent per sleeve.
- Decision / signature / date: ______

**D8. Sleeve cannot-decide: raise (no-trade day) or per-name HOLD in shares?**

- Options: see question
- Recommendation: Raise (fail closed). Decide with the measured raise frequency the sleeve no-op proof reports; a per-name HOLD re-normalises the rest of the book around the gap.
- Decision / signature / date: ______

**D9. fetch_daily when the pair is value-complete on disk: skip the fetch, or stand down when the vendor returns nothing?**

- Options: see question
- Recommendation: Skip when value-based completeness passes, say so in the log, and use rc 14 only when a fetch was needed and returned nothing.
- Decision / signature / date: ______

**D10. Noon-retry clock: plist-derived in the repo now, or launcher-passed --session-start?**

- Options: see question
- Recommendation: In the repo now; the launcher variant later, once launcher patches are testable on this machine.
- Decision / signature / date: ______

**D11. A pre-trade gross cap inside the freeze?**

- Options: see question
- Recommendation: Park. The signed preview (exact on name, side, quantity, NAV to the cent) is the substitute.
- Decision / signature / date: ______

**D12. cef_pm stays RUNG-0 (DRY_RUN=1) through the 20-session window?**

- Options: see question
- Recommendation: Yes. Do not change decision paths while measuring.
- Decision / signature / date: ______

**D13. The first order set may be large. Accept the strategy's own signal or stage it?**

- Options: see question
- Recommendation: Accept. Staging is a strategy change; the preview sign-off and the what-if are the controls.
- Decision / signature / date: ______

**D14. nextgen and spec v7.**

- Options: see question
- Recommendation: Parked and pushed, never merged. Eligible after 20 clean sessions through /spec-change and /prereg.
- Decision / signature / date: ______

**D15. CLAUDE.md wording (landmine 3's first half no longer matches the code; 'dollar-neutral by construction' is true of the target, not the held book).**

- Options: see question
- Recommendation: The team lead edits. Agents do not change CLAUDE.md.
- Decision / signature / date: ______

**D16. Ship DRY_RUN=1 in ops/schedule/benchmarks.env and phase0.env with the RC as a second lock on the deferred books?**

- Options: see question
- Recommendation: Yes. After the gateway is back, a single hand-cleared file is otherwise the only lock on two books known to transmit and then halt. Phase 8 flips it in its own tag.
- Decision / signature / date: ______

**D17. Exit when every capture is lost on an armed day.**

- Options: build a statement-ingest mode for replay_ledger once a real IBKR Flex/Activity export exists / fresh epoch
- Recommendation: Decide in advance; until a real export exists no parser can be written honestly, so the default exit is a fresh epoch decided by the team lead. Pull the first statement at H23 to make the tool possible.
- Decision / signature / date: ______

**D18. Apply the agent-drafted settings_proposed.json (order-path and panel-writer deny rules)?**

- Options: see question
- Recommendation: Yes, after reading the diff. Agents may not change permission settings; HEAD's allowlist still pre-authorises 'python3 scripts/*'.
- Decision / signature / date: ______

**D19. Where does the off-disk copy go? No external volume is mounted today and ~/prod-backups shares the prod disk.**

- Options: attach an external volume / a private remote or cloud location
- Recommendation: Name one today; H7's copy of the state archive, launcher and plists depends on it.
- Decision / signature / date: ______

**D20. Timing criterion and verifier strictness for the 20-session bar.**

- Options: launch-to-trade <= 30 min on complete-pair mornings (proposed) or another bound; UNVERIFIED verifier day breaks the streak (strict) or may be re-verified by a human reconcile
- Recommendation: Confirm 30 minutes; keep strict (verdict must be exactly PASS). The verifier retry is the first parked item to take up after acceptance if UNVERIFIED days recur.
- Decision / signature / date: ______

---

# Appendix 3 - Residual risks

- Until the RC is promoted, prod runs the defective tag with DRY_RUN=0 on three books; after H1 brings the gateway up, the three untracked HALT files are the only lock. Nobody may run clear_halt before H19; there is no cheap second lock because the launcher lets the env file override the shell and editing prod's env files would make promote.sh refuse.
- The RC promotion is executed by prod's OLD promote.sh (checkout --merge returns 0 with conflict markers; unchecked rollback; guard blind to cef_pm and verify.cef). It stays safe only while release_check 7 holds (no tracked live-state diff) and the human does the H11 preconditions and post-checks by hand.
- Broker acceptance of the first order set is unrehearsable: short locates are UNMEASURED (available_shares is NaN for every name), transmission is fire-and-forget (C11 parked), perm_id is still 0. Mitigation is human: compare by 10:30 ET, read TWS status, cancel by 15:30 ET.
- The launcher is never executed by an agent. Its armed argv path and the patched env merge are proved only by text-level tests, the _human_halt truth table, the shadow morning's not-armed path, and the first live morning.
- New fail-closed gates (ledger check, margin UNMEASURED, SleeveCannotDecide, vendor rc 14, NAV unknown) convert wrong-order risks into no-trade days. With cef_pm at RUNG-0 the book has two arming chances a day (08:30, 12:00); a network or account-read outage spanning both loses the session and resets the 20-session streak. The cause of the 08:30 DNS outages is UNMEASURED.
- Several fixes rest on single-source, verify-first findings (A6v, C8v, C6v, G6v, G7v and others). If one does not reproduce, the implementing agent stops and reports, and the plan's dependency chain (notably WS2 as one unit) must be re-examined rather than patched around.
- Margin: the cushion arithmetic is [U] (uniform 41.3% rate, base currency apparently non-USD). If the what-if shows too little headroom, the only no-code remedy is a by-hand flatten of phase0 quantities taken from a ledger its own halt calls an overclaim; the H2 broker read and per-sleeve tabulation reduce but do not remove that risk.
- Distribution data: only 7 of 17 names' September ex-dates are verified. If the vendor fetch is incomplete, the replayed NAV carries a named gap (accepted with a recorded reason) and sizing is off by a small, unmeasured amount until the panel is complete; distributions can be re-booked later from fills plus the panel.
- All work is on one machine with no off-disk backup destination mounted today (D19). Until H4 and H7 complete, a disk loss takes the code, the fix branches, the live ledgers and every backup.
- The clock seam and netguard add two new modules under ops/ that live code imports (ops.clock). The seam is unsettable without an active socket kill-switch, but this is a new live-path import and needs the sim no-op proof and review like any other live-path change.
- Rehearsal fills are synthetic (panel close, modelled commission). They test our code, not the market; real commissionReport shapes, fill timing and capture attribution by client id are first seen at the A 16:20 capture and the A+1 booking.
- benchmarks_paper and phase0_null remain halted with broken ledgers for the whole window; the promoted ledger check will FAIL on them at every fire and add to daily NOT TRADING email volume, which may train the operator to skim alerts until Phase 8.

---

# Appendix 4 - Critic issues not adopted, and why

- Completeness (should-fix): 'add replay_ledger --executions-from <IBKR Flex/Activity CSV>'. Not built now. No statement export has been fetched, so writing a parser would mean inventing a format (data rule). Adopted instead: the critic's own fallback - Phase 7.5 documents the armed-day-capture-lost path, states that the only exit today is a team-lead decision (D17: fresh epoch, or the ingest tool once H23 supplies a real sample), and the tool is parked with that trigger.
- Completeness (must-fix 3, fix detail): the 6.1a/6.1b split with an --apply on day X and a second incremental --apply. The defect is adopted, the remedy is the order-path critic's: shadow morning first, then ONE apply on day S through S-1, so the first armed advance walks exactly one bar. Day P gets a dry run only (writes nothing) to prove the tool on prod state. The incremental-extension test and a slip rule are kept because a re-arm delay makes a second apply necessary.
- Completeness (nit): require a 'release_check: PASS <sha>' line in the tag annotation inside promote.sh. Not adopted: the line is hand-forgeable, the RC promotion is run by the old promote.sh anyway, and a bug in the exemption logic would block the emergency rollback promotion. release_check.sh plus the H11 preconditions are the gate during the freeze. The morning clock window (3.10f) from the same nit is adopted.
- Test-rigour (must-fix 3, procedure detail): 'git worktree add <scratch>/base v2026.09.13.4' for the baseline. Replaced by 'git archive v2026.09.13.4 | tar -x' into scratch: earlier /private/tmp worktrees went prunable, a worktree adds repo metadata, and the rehearsal/root rule refuses any path inside a git work tree. Everything else in that must-fix (driver script, parsed-JSON manifest compare without written_utc, mutation control, saved shas) is adopted.
- Test-rigour (should-fix, R6): 'define exit semantics for --no-live'. Took the critic's other option: R6 calls preflight.run directly with books_root as a FAIL/PASS control pair, and the CLI gains --books-root, but the --no-live exit code is left unchanged to avoid altering a command the /preflight skill and CLAUDE.md already document.
- Order-path (should-fix, settings): the agent does not write deny rules into .claude/settings.json at all, even as a commit for review. It drafts settings_proposed.json and a test; the team lead applies it (H8/D18). This is stricter than the critic asked, because no agent message can authorise a permission change.
- Draft items dropped because a critic showed them unworkable: the nextgen repair tool as acceptance criterion 3 (its schema check refuses the archive; now informational only), R4 as '--from <through+1> --days N' (only one panel bar exists after 09-17), flipping test_sell_side_share_order_is_unchanged (the MKT pin is kept), forcing the DryRunBroker branch under DRY_RUN=1 (would write a flat book_status.json into the live root), setting ALERT_SMTP_PASS in the dev tree, and switching the main dev tree to the hardening branch.

---

# Appendix 5 - Provenance

Produced 2026-09-20/21 by a read-only 19-agent workflow (run wf_22ea60eb-270): seven audit lanes, one adversarial verifier per lane, a planner, three critics, a finaliser. 95 findings survived (8 blocker, 34 high); 0 were refuted. Findings with their evidence and verifier verdicts: FINDINGS.json. The three critiques in full: CRITIQUES.json. Nothing in this directory has been executed.
