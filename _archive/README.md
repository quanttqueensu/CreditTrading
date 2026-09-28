# _archive — the record of what we did, and none of what is true now

**Nothing in this folder describes the current state of the book, the system or
the research.** Every figure here is a dated observation taken from a document
that has since been superseded. If you are about to quote one, re-measure it
(`python3 -m ops.orient`), or state it as a gap.

What is true now lives in exactly three places, and nowhere in here:

| question | owner |
|---|---|
| any number — fills, arm rate, spec, counters, panels, what prod lacks | `python3 -m ops.orient` |
| what we trade, how the system runs, what we know | `docs/SYSTEM.md` |
| which document owns which question | `docs/INDEX.md` |

## Why it is a separate folder

Before 2026-09-13 superseded documents sat beside current ones with a banner on
top. A banner tells a reader the document is stale; it does not stop an agent
that found the file by searching from quoting its body. Six documents each
claimed to be the entry point, "how the strategy works" was written six times,
and the copies disagreed about the arm rate, the vol target, breadth and which
tag prod ran. The cure is distance, not more banners.

## The wall, and its holes

`.gitignore` lists `/_archive/`. **Everything here is still tracked** — an
ignore line does not untrack a committed file, the same shape as the live
ledgers — with its history (`git log --follow`). What the line does is keep
archived bodies out of search: `rg` and the `grep` that Claude Code's shell
runs (ugrep with `--ignore-files`) both skip gitignored paths unless pointed at
them. So a search for a phrase lands on the current document, not a superseded
one. A `.ignore` file was tried first; only ripgrep reads it, and `grep -r`
walked straight through.

**The holes:** `find`, `ls`, `git grep` and `git ls-files` still see this folder,
and any tool can open a path it is given. That is why every archived `.md` opens
with a banner saying what it was and what now owns its subject, and why
`ops.doc_audit` fails if one does not. The verification is recorded in
`results/ops/ARCHIVE_WALL_2026-09-13.md`.

**The price:** a *new* file here is invisible to `git status` and skipped by
`git add -A`. Use `git mv` (which records the rename regardless) or `git add -f`.
`ops.doc_audit` fails on any file under `_archive/` that git is not tracking.

Deliberate reads still work: `rg <pattern> _archive/`, `grep -r <pattern>
_archive/`, or opening a path. Archived material is legitimate *provenance* — it
is where a number came from — and is never *authority* for what is true today.

## Rules

1. **Never delete.** The test from `ops/_archive/README.md` stands: *what does
   deleting it cost if you are wrong?* The only copy of the evidence behind a
   quoted number makes that number unfalsifiable when it goes.
2. **Mirror the original path.** `docs/PLAN.md` lives at `_archive/docs/PLAN.md`.
   A document trimmed in place leaves a dated snapshot beside its mirror path:
   `_archive/docs/RESEARCH_STATE_<date>.md`.
3. **`git mv` (or `git add -f` for a new file), and the banner in the same
   commit**, so rename detection keeps the history attached. Banner, within the
   first 45 lines:

   ```
   > **ARCHIVED <date> — not evidence of current state.** Was `docs/PLAN.md`.
   > Now owned by: `docs/SYSTEM.md` §N. Numbers: `python3 -m ops.orient`.
   ```

   A snapshot says ``Snapshot of `<path>` at `<sha>` `` in place of ``Was``.
4. **Repoint every citation in the same commit.** A work order in
   `docs/prompts/` may cite an archived file as background, spelled
   `_archive/...` and called archived. `CLAUDE.md`, `.claude/` and the canonical
   documents never cite this folder as an authority.
5. **Never create a file named `CLAUDE.md`, or a `.claude/` directory, in
   here.** Claude Code auto-loads a nested `CLAUDE.md` when it reads files in
   that subtree, which would put a superseded rulebook back in front of every
   agent that opened a path here. Snapshots of `CLAUDE.md` are named
   `CLAUDE_md_<date>.md`; archived agent-layer files go under
   `_archive/claude_layer/`.
6. **Nothing imports from here.** `ops.doc_audit` checks all of the above.

The two older archive folders, `ops/_archive/` and `scripts/_archive/`, were
folded in on 2026-09-14 and keep their inner layout: `_archive/ops/_archive/`
holds the v5 frozen spec, which is the band's revert path.
`ops/books/retired/` never moves — `IBKRBroker._foreign_book_claims` globs
`ops/books/*.json` non-recursively, and its location is what keeps a retired
book's symbols out of that check.

## Index

Every archived file, or a directory containing it, has a row. **The last column
is the reason this folder exists**: what the document is wrong *about*, in
substance, so that a reader who does open it knows which sentence not to copy.

| path | was | archived | now owned by | what it is wrong about |
|---|---|---|---|---|
| `_archive/ARCHIVE_WALL_SENTINEL.md` | — (new) | 2026-09-13 | — | Nothing. It carries a token that exists nowhere else in the repo, so a search that returns it has crossed the wall. |
| `_archive/docs/HOW_WE_GOT_HERE.md` | `docs/HOW_WE_GOT_HERE.md` | 2026-09-13 | `docs/SYSTEM.md`; `docs/RESEARCH_STATE.md` | A narrative of the summer, correct as of 2026-07-31 and deliberately never updated. Everything it calls current predates the no-trade band, the `shift(2)` correction and every broker-confirmed session after 07-31. It sends readers to `SYSTEM_AND_STRATEGY.md` for current state, which is itself archived. |
| `_archive/docs/SUMMER_2026_SUMMARY.md` | `docs/SUMMER_2026_SUMMARY.md` | 2026-09-13 | `docs/SYSTEM.md` | The 2026-08-16 progress summary. Its broker endpoint is the port that **caused** 21 silent dry-run sessions, its strategy section is the retired 2-day calendar, and its Sharpe figures are scored at `shift(1)`. |
| `_archive/docs/PROJECT_INTRO.md` | `docs/PROJECT_INTRO.md` | 2026-09-13 | `docs/SYSTEM.md` | A two-page recruiting introduction as issued 2026-08-16. Its timeline, status and strategy description are as of that date; the trading policy changed three weeks later. |
| `_archive/docs/recruiting-page.html` | `docs/recruiting-page.html` | 2026-09-13 | — | An "open roles 2026/27" web page. Referenced by nothing. Its reading list starts with a document that is now archived. |
| `_archive/docs/pdf/` | `docs/pdf/` | 2026-09-13 | — | PDFs of INFRASTRUCTURE, PROJECT_INTRO and the summer summary, built 2026-08-16 — **before** the correction banners, so the Infrastructure PDF still gives the broker port that caused the silent dry runs. Never read a PDF here for any fact. |
| `_archive/docs/build_pdfs.py` | `docs/build_pdfs.py` | 2026-09-13 | — | The pandoc + headless-Chrome builder for those PDFs (with `template.html` and `print.css`). Two of its three sources are archived; it will not run from here without editing its paths. |
| `_archive/docs/template.html` | `docs/template.html` | 2026-09-13 | — | Pandoc template for `build_pdfs.py`. |
| `_archive/docs/print.css` | `docs/print.css` | 2026-09-13 | — | Print stylesheet for `build_pdfs.py`. |
| `_archive/docs/handoffs/HANDOFF_2026-09-10.md` | `docs/handoffs/HANDOFF_2026-09-10.md` | 2026-09-13 | — | An overnight session handoff. Every "status" in it is 2026-09-10 10:40 ET: branch names, halts, what main was at. |
| `_archive/docs/prompts/NEXT_2026-09-11.md` | `docs/prompts/NEXT_2026-09-11.md` | 2026-09-13 | `docs/prompts/README.md` | The work order for one day. It names prod's tag and a book NAV as of 2026-09-10, and named two release tags when three existed. The day has passed. |
| `_archive/docs/prompts/_superseded/` | `docs/prompts/_superseded/` | 2026-09-13 | the W/F/G work orders | The original P-series prompts, consolidated into W/F/G on 2026-09-09. Their own README lists two claims now known to be wrong (an ex-distribution date "moves price and not NAV"; a SOFR leverage-cost conditioner for SIFMA-reset munis). P-numbers are not live identifiers. |
| `_archive/results/ACADEMIC_REPORT_2026-07-31.md` | `results/ACADEMIC_REPORT_2026-07-31.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` | The "thirteen mechanisms" report on the credit-ETF programme that preceded the CEF book. Correct as a record of those kills; says nothing about the CEF strategy as traded. |
| `_archive/results/OVERNIGHT_REPORT_2026-07-30.md` | `results/OVERNIGHT_REPORT_2026-07-30.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` | The 2026-07-30 overnight write-up of the forced-flow / ETF work. Pre-CEF. |
| `_archive/results/journal/` | `results/journal/` | 2026-09-13 | `docs/RESEARCH_STATE.md` | Checkpoint journal for that overnight run. |
| `_archive/notebooks/` | `notebooks/` | 2026-09-13 | — | R2/TRACE research notebooks from the fallen-angel programme, which is dead. They read data sources this repo no longer stages. |
| `_archive/docs/PLAN.md` | `docs/PLAN.md` | 2026-09-13 | `docs/SYSTEM.md` §2–§3; `scripts/cef/plan_diagnostics.py` | Its headline **0.10** net Sharpe is the **retired calendar policy's**, not the band's, and it calls 0.10 "the live configuration's true net Sharpe" in bold. Its capture conclusion ("2 sessions captured out of 25") was false: `launch_job.py` phase 4 captures unconditionally. Its "Drop PHK" item is contradicted by `PER_NAME_ARCHITECTURE.md`. Its §-numbered measurements are still the evidence several work orders cite, and `plan_diagnostics.py` reproduces them. |
| `_archive/docs/SYSTEM_AND_STRATEGY.md` | `docs/SYSTEM_AND_STRATEGY.md` | 2026-09-13 | `docs/SYSTEM.md`; §7 in `docs/RESEARCH_STATE.md` | The cold-reader overview as of 2026-09-06. Its arm rate, fill counts, "real capital expected this year", "we target 6%" framing, "effective breadth is 2.24" heading and "8/9 walk-forward, gross 1.23 → 1.75 out of sample" all rotted or were withdrawn; its own correction banner lists four. Its §7 graveyard was still true and moved verbatim to `docs/RESEARCH_STATE.md`. |
| `_archive/docs/RESEARCH_AND_METHODOLOGY.md` | `docs/RESEARCH_AND_METHODOLOGY.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` (D1–D7); `docs/prompts/00_BRIEF.md` §5 | Dated 2026-07-31. It describes a 5-day rebalance, says "zero live fills", and keys its deflated-Sharpe discussion to a trial count long superseded. Its D1–D7 failure taxonomy was sound and moved verbatim to `docs/RESEARCH_STATE.md`. |
| `_archive/docs/PER_NAME_ARCHITECTURE.md` | `docs/PER_NAME_ARCHITECTURE.md` | 2026-09-13 | `perfund/F2`, `perfund/F3` | **Three of its seven derived bands rest on fewer observations than this repo's identification budget allows — do not deploy those three.** Its PHK half-life is flagged wrong in place and disagrees with `PLAN.md` §4.1. The table was always illustrative, not deployable. |
| `_archive/docs/EXIT_RESEARCH_2026-09-07.md` | `docs/EXIT_RESEARCH_2026-09-07.md` | 2026-09-13 | `docs/prompts/W11_trading_policy.md` | A dated exit / holding-period study (`scripts/cef/exit_study.py`), filed in `docs/` rather than `results/`. Carries a ⛔ correction in its body. |
| `_archive/docs/E1_PREREG.md` | `docs/E1_PREREG.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` | Pre-registration for E1, a killed pre-CEF strategy. Correct as a record of what was committed in advance. |
| `_archive/docs/CREDIT_RV_PREREG.md` | `docs/CREDIT_RV_PREREG.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` | Pre-registration for credit_rv, killed at its sealed holdout. `src/strategies/credit_rv/` still cites it by section; that code is research, not the CEF book. |
| `_archive/ops/README.md` | `ops/README.md` | 2026-09-13 | `docs/SYSTEM.md` §4 | The July ops simulator description. **"There is no broker here" is false** — several `ops/` modules import an IB client and some transmit. It uses the pre-2026-08-31 repo path and names `ops/state/`, `ops/spec/` and `state/`, none of which exist. |
| `_archive/ops/schedule/README.md` | `ops/schedule/README.md` | 2026-09-13 | `docs/SYSTEM.md` §4.2 | The July launchd setup. Launchd runs `launch_job.py`, not these shell wrappers; the path it uses is pre-2026-08-31, and the schedule it describes is two architectures old. |
| `_archive/ops/AUTOMATION.md` | `ops/AUTOMATION.md` | 2026-09-13 | `docs/SYSTEM.md` §4.2, §4.6 | The TWS-era unattended-operation runbook, written before the prod/dev split and the morning schedule, and the only superseded document here that never carried a banner. |
| `_archive/docs/RESEARCH_STATE_2026-09-14.md` | snapshot of `docs/RESEARCH_STATE.md` | 2026-09-14 | `docs/RESEARCH_STATE.md` | The full file before it was trimmed to the ledger. It has two ages and no single "as of": a header dated 2026-07-31 over amendments from September. Its DEPLOYED section is a 2026-07-31 broker snapshot; its QUEUE and DATA INVENTORY are July's; its header trial total disagrees with its own table. The W14 Part A and G6 write-ups in it are sound and dated; their results notes are the evidence. |
| `_archive/docs/prompts/00_BRIEF_2026-09-14.md` | snapshot of `docs/prompts/00_BRIEF.md` | 2026-09-14 | `docs/prompts/00_BRIEF.md`; `docs/SYSTEM.md` §5; `docs/prompts/README.md` | The brief before its scoreboard lost its "live today" column and §6–§8 moved out. Its scoreboard arm rate ("3 of 26") disagreed with three other documents; §7 lists gamma as hedge overlay plus timed sleeve, which W14 Part A and G6 later closed; §8 lists W0 and W0b as to-do after both were executed. |
| `_archive/docs/INFRASTRUCTURE_2026-09-14.md` | snapshot of `docs/INFRASTRUCTURE.md` | 2026-09-14 | `docs/SYSTEM.md`; `docs/INFRASTRUCTURE.md` | The 2026-08-16 technical reference before its overview, strategy, schedule and open-issues parts moved out. Its overview says the book "targets 6% annualised volatility"; §3.4 shows the retired 2-day rebalance with no band row; §6.1 is the evening schedule; §8's "no trading since 1 August" was long false; §2.4's expected Sharpes were `shift(1)` figures. |
| `_archive/CLAUDE_md_2026-09-14.md` | snapshot of `CLAUDE.md` | 2026-09-14 | `CLAUDE.md`; `docs/SYSTEM.md`; this index | The agent brief before it was cut to rules. Named `CLAUDE_md` so Claude Code never auto-loads it. Most of its length was incident narrative and dated figures: a prod tag two promotions stale; "prod has none of this" after prod had it; "the session architecture is still the evening one" after W3; `walkforward.py` "on no live path" when `ops/common.py` reaches it; a hooks directory described as the enforcement layer with no blocking hook in it. Its hard rules survive in substance in the new file. |
| `_archive/README_md_2026-09-14.md` | snapshot of `README.md` | 2026-09-14 | `README.md`; `docs/SYSTEM.md` | The human entry point before it was cut to pointers. Its "Status" block gave 294 fills and "5 of 29" armed as of 2026-09-10; it sent new readers to four historical documents first, named a `docs/_superseded/` that never existed, cited INFRASTRUCTURE sections by the wrong numbers, and ran `validate.py` without the `--trials` it now requires. |
| `_archive/ops/_archive/` | `ops/_archive/` | 2026-09-14 (folded in) | `_archive/README.md` | The operations archive before there was one archive. Holds the **v5 frozen spec, which is the band's revert path and half of its pre-registration — never delete it**; the one-off `fix_bench_b6_angl_20260909.py` that mutated a fill file; and the pre-W3 scheduling layer (`schedule_pre_w3_2026-09-13/`: shell wrappers, `install.sh`, book plists). The wrappers still transmit if run — they are archived, not disarmed. Its own README explains each. |
| `_archive/scripts/_archive/` | `scripts/_archive/` | 2026-09-14 (folded in) | `_archive/README.md` | `cef_sleeve.py` and `cef_sleeve_v2.py`, the research sleeves that produced parquets still cited in `results/cef/`. Superseded by `src/deploy/sleeves/cef_discount.py`. |
| `_archive/scripts/disp/`, `_archive/results/disp/` | `scripts/disp/`, `results/disp/` | 2026-09-14 | `docs/RESEARCH_STATE.md` KILLED (single-fund-PD) | The premium/discount dispersion scan. Its "dispersion is large" finding is real and its conclusion is not a trade: the dispersion was NAV staleness, not dislocation. |
| `_archive/scripts/leadlag/`, `_archive/results/leadlag/` | `scripts/leadlag/`, `results/leadlag/` | 2026-09-14 | KILLED (leadlag) | Lead-lag between thin and liquid wrappers. The huge raw t-statistics were measured on (H+L)/2, not a transactable price, and the Treasury control scored higher than credit. |
| `_archive/scripts/ou/`, `_archive/results/ou/` | `scripts/ou/`, `results/ou/` | 2026-09-14 | KILLED (pair-reversion) | Within-class pair reversion. Gross combination looked good; costs do not diversify, net went negative, and the vol mandate needed leverage far beyond Reg T. `capacity_frontier.py` reads `config/futures_specs.yaml`, which stays live-adjacent in `config/`. |
| `_archive/scripts/s4/`, `_archive/results/s4/` | `scripts/s4/`, `results/s4/` | 2026-09-14 | KILLED (dealer-constraint) | Primary-dealer inventory as a credit predictor. No credit name significant at any horizon; the UST control showed the same magnitude. |
| `_archive/scripts/positioning/short_pressure.py`, `_archive/results/positioning/` | `scripts/positioning/short_pressure.py`, `results/positioning/` | 2026-09-14 | KILLED (short-pressure) | FINRA short-volume reversal. The rates control scored higher than credit. `scripts/positioning/stage_positioning.py` stays: a queued work order (F1) uses the panel it stages. |
| `_archive/results/s1/`, `_archive/scripts/holdings/build_union_panel.py`, `_archive/scripts/holdings/measure_staleness.py` | `results/s1/`, `scripts/holdings/…` | 2026-09-14 | KILLED (S1-as-specified) | Per-bond staleness from cross-issuer price disagreement — every issuer buys from the same vendor, so the input carries no information. The holdings *collectors* (`ingest_holdings.py`, `fetch_nav_multi.py`) stay: launchd's collect job runs them. |
| `_archive/scripts/rv/` | `scripts/rv/` (28 research scripts) | 2026-09-14 | KILLED (credit_rv) | The credit_rv diagnostics, sweeps, in-sample/pairs/optimiser runs and its holdout test. **Not archived, because live or kept code depends on them:** `stage_ohlc*.py`/`stage_universe.py` (produce `data/rv/etf_ohlc.parquet`, read by ops tools), `build_cost_model.py` (writes `config/costs.yaml`), `fetch_ibkr_spreads.py`, and `measure_rth_liquidity.py`/`probe_ibkr_spreads.py` (the reproducers behind the live cost model's assumptions). `results/credit_rv/` also stays: its measured spread files feed `build_cost_model.py` and the WATCH-listed E1 scripts. |
| `_archive/scripts/fetch/` | `scripts/fetch/` (8 scripts) | 2026-09-14 | `docs/INFRASTRUCTURE.md` §2.3 (the rebuild that still works) | Forced-flow-era fetch helpers and panel builders (`_setup.py`, `build_a0_data.py`, `p1_build_bond_day_panel.py`, fund-flow and share-count fetchers). `_setup.py` imports modules that no longer exist, and two of them hardcode a `REPO/archive/calendar-premia-v2` path from a retired project. |
| `_archive/scripts/ops/migrate_trades_modelled_price.py` | `scripts/ops/…` | 2026-09-14 | — | A one-off ledger migration, already applied. Re-running it against a current ledger would rewrite modelled prices that later code depends on. |
| `_archive/scripts/build_events_deploy.py` | `scripts/build_events_deploy.py` | 2026-09-14 | — | The FOMC event-calendar builder for a retired calendar-premia project; hardcodes that project's `archive/` path. |
| `_archive/ops/daily_run.py`, `_archive/ops/weekly_report.py`, `_archive/ops/monitor.py`, `_archive/ops/portfolio_monitor.py`, `_archive/ops/smoke_test.py` | `ops/…` | 2026-09-14 | `docs/SYSTEM.md` §4 | The July v1 operations loop: a standalone daily runner, a monitor, a portfolio monitor, a weekly report and a smoke test. Nothing imports them and launchd runs none of them — the weekly job runs `ops/schedule/weekly_book_report.py`. They read an `ops/spec/frozen_spec.json` that does not exist. `.claude/settings.json` still allowlists two of them by path; that entry is inert. |
| `_archive/ops/cleanup_20260910.sh` | `ops/cleanup_20260910.sh` | 2026-09-14 | — | A one-off repo-hygiene script from W0, already run; its targets are gone. |
| `_archive/src/deploy/run_daily.py`, `_archive/src/deploy/lib/broker/`, `_archive/src/deploy/lib/expression.py`, `_archive/src/deploy/lib/financing.py`, `_archive/src/deploy/lib/futures.py`, `_archive/src/deploy/lib/kill_aware_backtest.py`, `_archive/src/deploy/lib/margin.py`, `_archive/src/deploy/lib/netting.py`, `_archive/src/deploy/lib/portfolio_v2.py`, `_archive/src/deploy/lib/run_book_v2.py` | `src/deploy/…` | 2026-09-14 | `src/deploy/run_book.py`, `src/deploy/portfolio.py` | The "v2 refine-cycle" portfolio-margin stack (REFINE_PREREG 2026-07-21) that was never deployed: a margin-broker simulator, netting, futures expression, financing, a kill-aware backtest, and v2 run_book/portfolio. `portfolio_v2` imports a module that does not exist. `src/deploy/lib/vol_target.py`, `attribution.py`, `option_spread_model.py`, `odd_lot.py` and `optmath.py` stay: work orders or the live path use them. `src/deploy/risk.py` comments still describe v2 netting order; they describe this archived code. |
| `_archive/src/strategies/credit_rv/book.py`, `_archive/src/strategies/credit_rv/book_opt.py`, `_archive/src/strategies/credit_rv/pairs.py`, `_archive/src/strategies/credit_rv/trials.py`, `_archive/src/strategies/credit_rv/optimizer.py` | `src/strategies/credit_rv/…` | 2026-09-14 | KILLED (credit_rv) | credit_rv's book construction, pairs and trial-accounting modules, used only by its archived research scripts. **Still live:** `signal.py` (imported by the registered `credit_rv` sleeve) and `costs.py`, which despite its folder is the general cost model `ops/preflight.py` uses. |
| `_archive/docs/prompts/W0_repo_hygiene.md`, `_archive/docs/prompts/W0b_prod_dev_split.md`, `_archive/docs/prompts/W0c_repo_coherence.md` | `docs/prompts/W0*.md` | 2026-09-14 | `docs/SYSTEM.md` §4.1; `docs/INDEX.md` | Executed work orders (repo hygiene 2026-09-10; the prod/dev split; the coherence pass). Their "current state" blocks — prod paths not yet existing, dangling references to fix, a queue to follow — describe the repo before they ran. W0c's one open item was pushing `main` to origin. |
| `_archive/docs/prompts/W14_options.md` | `docs/prompts/W14_options.md` | 2026-09-14 | `docs/RESEARCH_STATE.md` CLOSED (W14-A) | The options work order. Part A is done (the book is not short volatility in a way a hedge could use) and its own gate closed Part B; Part C waited on a credit option surface that the closed gamma programme was to build. It reads as "in progress" and is not. |
| `_archive/docs/prompts/gamma/` | `docs/prompts/gamma/` | 2026-09-14 | `docs/RESEARCH_STATE.md` CLOSED (G6), KILLED (gamma-timing-C3); `docs/SYSTEM.md` §5 | The credit-gamma programme: `G0_BRIEF` and `G1`–`G7`. G1 (option maths) and G4 Part A (order-path defects) delivered code that stays; G6 measured that no declared conditioner times credit gamma, so G7 does not run and the GAMMA counter stays at zero. The "queued" statuses on G2/G3/G5 are moot, not pending. |
| `_archive/results/cef/FIRST_BAND_SESSIONS.md` | `results/cef/FIRST_BAND_SESSIONS.md` | 2026-09-14 | `broker_fills.csv`; `ops/verify_session.py` | A per-session running record of the band's first live sessions, last appended 2026-09-10. Every session in it predates the 2026-09-11 epoch reset and the morning schedule, so it is not the start of the clean track record; the broker's own record and the daily verifier replaced it. |
| `_archive/results/ops/BACKUP_SCHEDULE_2026-09-10.md` | `results/ops/…` | 2026-09-14 | `com.quantt.backup.daily` | Says "PREPARED, NOT INSTALLED". The job has since been installed and loaded; the note's pending step is done. |
| `_archive/results/ops/DEAD_ENTRY_AUDIT_2026-09-10.md` | `results/ops/…` | 2026-09-14 | — | A completed audit of dead directory scans on the live path, against a prod tag and layout that have both moved on. |
| `_archive/results/ops/HALT_PHASE0_ATTRIBUTION_2026-09-10.md` | `results/ops/…` | 2026-09-14 | `results/ops/LEDGER_DIVERGENCE_2026-09-10.md`, `results/ops/LQD_ATTRIBUTION_2026-09-10.md` | **Its LQD row is wrong and asks for a decision that would transmit an order** — LQD was a phantom fill, not an unattributed position. Superseded the same evening by the two notes named. |
| `_archive/results/ops/PROMOTION_DEADLOCK_2026-09-10.md` | `results/ops/…` | 2026-09-14 | `docs/SYSTEM.md` §4.1 | The four-layer promotion deadlock of 2026-09-10. Resolved: prod was reunified onto `main` and promoted through the gate on 2026-09-13. |
| `_archive/results/ops/REPO_HYGIENE_2026-09-10.md` | `results/ops/…` | 2026-09-14 | — | W0's output note. Its "what is still wrong" lists describe the repo before W0, W0c and the 2026-09-14 cleanup. |
| `_archive/results/ops/NUMBER_CONSISTENCY_2026-09-10.md` | `results/ops/…` | 2026-09-14 | `docs/SYSTEM.md` §0; `ops.orient` | Every figure the project stated about itself, as of 2026-09-10 11:45 — all of them since re-measured or moved. Its §12 (which artifact answers which question) was the useful part and lives on, without figures, as `docs/SYSTEM.md` §0. |
| `_archive/results/credit_rv/_smoketest/` | `results/credit_rv/_smoketest/` | 2026-09-14 | — | Smoke-test output labelled NOT REAL DATA. |

### 2026-09-28 — IBKR retired, move to Alpaca

Team lead's decision and the full inventory: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md`.
Everything below ran, or described, the IBKR paper book. **What every row is wrong about:
it assumes an IBKR account, an IB Gateway on this Mac, launchd, and a detached prod
worktree at `~/prod/QUANTT` — none of which is part of the system any more.** The
Alpaca system is being built in `quantt/`. `ibkr-final` tags the last commit before any
of this moved.

| path | was | archived | now owned by | what it is wrong about |
|---|---|---|---|---|
| `_archive/src/deploy/` | `src/deploy/broker/ibkr.py`, `src/deploy/run_book.py`, IBKR-path tests (`src/deploy/tests/…`) | 2026-09-28 | `quantt/` (being built) | `IBKRBroker` (arm, shadow ledger, MOC placement, fill capture) and the daily runner that drove it. The arm-from-positions, pending-order refusal and one-arm-per-session lessons are real and must be rebuilt for Alpaca; the code is not. |
| `_archive/ops/account_audit.py`, `_archive/ops/cancel_open_orders.py`, `_archive/ops/capture_fills.py`, `_archive/ops/reconcile_orders.py`, `_archive/ops/reset_epoch.py`, `_archive/ops/switch_broker.py`, `_archive/ops/verify_session.py`, `_archive/ops/pending_orders.py`, `_archive/ops/rebuild_ledger.py`, `_archive/ops/unbook_unexecuted_fills.py`, `_archive/ops/flatten_ibkr_account.py` | `ops/…` | 2026-09-28 | the manifest | IBKR broker tools. `flatten_ibkr_account.py` sent the final 34 MOC orders on 2026-09-28 (left at PendingSubmit, abandoned by decision). |
| `_archive/ops/preflight.py`, `_archive/ops/doctor.py`, `_archive/ops/decision_age.py`, `_archive/ops/session_plan.py`, `_archive/ops/session_uptime.py`, `_archive/ops/archive_machine_pre_w3.py`, `_archive/ops/promote.sh`, `_archive/ops/backup_state.sh`, `_archive/ops/sync_dev_data.sh` | `ops/…` | 2026-09-28 | the manifest | The session gate, machine health check and prod/dev promotion for launchd on this Mac. `deployed_tickers` moved to `ops/common.py`. |
| `_archive/ops/prompt_status.py`, `_archive/ops/gamma_status.py` | `ops/…` | 2026-09-28 | `docs/RESEARCH_STATE.md` (counters, read by `ops.orient`) | Work-order and options-programme status readers; their subjects were archived with them. |
| `_archive/ops/orient_2026-09-28.py` | snapshot of `ops/orient.py` | 2026-09-28 | `ops/orient.py` | The IBKR-era readout: prod tree, halts, fills, uptime. |
| `_archive/ops/schedule/` | `ops/schedule/` (all but `nyse_calendar.py`) | 2026-09-28 | the manifest | launchd plists, env files with IBKR client ids, renderers, the `launch_job.py` patcher, the weekly report. The jobs were unloaded 2026-09-28. |
| `_archive/ops/tests/` | `ops/tests/…` for the files above | 2026-09-28 | — | Tests of archived modules. `test_orient_2026-09-28.py` and `test_netguard.py` are pre-trim snapshots of live files. |
| `_archive/conftest.py.archived-2026-09-28` | snapshot of `conftest.py` | 2026-09-28 | `conftest.py` | The harness before its `ops.doctor` patch was removed. Renamed so pytest can never load it. |
| `_archive/deploy/ibgw/` | `deploy/ibgw/` | 2026-09-28 | — | IB Gateway + IBC setup. |
| `_archive/dashboard/` | `dashboard/` | 2026-09-28 | nothing yet (team lead: rebuild fresh later) | The read-only monitor on :8787, built on the IBKR shadow ledger and a live IB socket. |
| `_archive/scripts/audit/`, `_archive/scripts/ops/`, `_archive/scripts/cef/` | `scripts/audit/moc_routing_test.py`, `scripts/audit/live_pnl_attribution.py`, `scripts/ops/reconcile_attribution.py`, `scripts/cef/fetch_borrow_rates.py`, `scripts/cef/fetch_borrow_history.py`, `scripts/cef/reconcile_prices.py` | 2026-09-28 | — | IBKR probes and IBKR-sourced borrow/price feeds. The two `scripts/audit/` files **connect to a broker at import** — never import them. |
| `_archive/docs/prompts/` (the W1–W15, perfund F1–F3 orders and `README.md` added 2026-09-28) | `docs/prompts/` | 2026-09-28 | nothing live (team lead: archive them all); theory and harness rules moved to `docs/BRIEF.md` | Work orders for the IBKR system and its research queue. Research ideas in them are provenance for new Alpaca-era orders, not a queue. |
| `_archive/claude_layer/` | `.claude/agents/ops-watchdog.md`, `.claude/agents/dashboard-designer.md`, `.claude/skills/{book-status,preflight,incident,dashboard-ui,fill-audit}/`, `.claude/rules/{live-order-path,dashboard}.md`, `.claude/hooks/tests/test_book_state_trees.py`, and `*_2026-09-28` snapshots of the three hooks | 2026-09-28 | `CLAUDE.md`; `.claude/hooks/` | The agent layer for the IBKR run: launchd diagnosis, the preflight gate, incident write-ups against the prod tree, fill audits on `broker_fills.csv`. |
| `_archive/prod_state_2026-09-28/` | `~/prod/QUANTT/ops/` (untracked live state) | 2026-09-28 | the manifest | The prod tree's ledgers, session logs, three uncleared halts and post-close verdicts at retirement. Its own `README.md` says what each part is. |
| `_archive/CLAUDE_md_2026-09-28.md`, `_archive/README_md_2026-09-28.md`, `_archive/docs/SYSTEM_2026-09-28.md`, `_archive/docs/INDEX_2026-09-28.md`, `_archive/docs/INFRASTRUCTURE_2026-09-28.md` | snapshots of `CLAUDE.md`, `README.md`, `docs/SYSTEM.md`, `docs/INDEX.md`, `docs/INFRASTRUCTURE.md` | 2026-09-28 | the live files | The documents as they stood before the IBKR sections were rewritten for Alpaca. Every run instruction in them (prod tree, launchd, preflight, halts in prod, the dashboard) describes a retired system. |
| `_archive/ops/books/` (everything moved 2026-09-28: `*_live/`, `_dryruns/`, `_recovered_dryruns/`, `retired/`, `benchmarks_book.json`, `phase0_book.json`, the dry-run JSONs) | `ops/books/…` | 2026-09-28 | the manifest; `ops/books/cef_discount_book.json` stays live | The IBKR books' dev-tree ledgers, order maps and dry runs. `retired/` "must not move" only because `IBKRBroker._foreign_book_claims` globbed `ops/books/*.json`; that reader went with IBKR. Prod's own copies are in `_archive/prod_state_2026-09-28/`. |
| `_archive/ops/specs/` (`null_trader`, `credit_rv`, `bench_b1_hyg`, `bench_b3_agg`, `bench_b4_60_40`, `bench_b5_shy` `.frozen.json`) | `ops/specs/…` | 2026-09-28 | `ops/specs/cef_discount.frozen.json`, `ops/specs/bench_b6_ew_credit.frozen.json` | Specs of the books retired 2026-09-28 (team lead: keep the CEF book and b6 only). |
