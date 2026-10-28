# Ex-date drift (EVENTS trial 3): Stage 0 CLEAR (2026-10-28), k committed; `open` waits on French's next vintage and the team lead

**Date** 2026-10-27 · **Pre-registration** `results/events/PREREG_EXDATE_DRIFT_2026-10-26.md`
(approved 2026-10-27 with every recommended answer: part (b) is EVENTS trial 3 at N = 7; part (a)
withdrawn) · **Counter** EVENTS 3, unchanged (it moved on approval) · **Branch** `exdrift-stage0`,
cut from `simon` at `66ec3df` · **Author** research agent

**Reproducer:** `python3 scripts/events/exdrift_trial.py stage0` (offline once the caches of §6
exist; exit 2 = halted). Outputs, all tracked, with dates, counts, presence and flags only:

| file | holds |
|---|---|
| `results/events/exdrift/exdrift_stage0_output_2026-10-27.txt` | the run's printed record |
| `results/events/exdrift/exdrift_stage0_2026-10-27.json` | gate statuses, counts, coverage, the identity table |
| `results/events/exdrift/exdrift_stage0_flags_2026-10-27.csv` | 843 flags, final (657 at the first 2026-10-28 run; 587 on 2026-10-27), keyed `(check, ticker, date)` |
| `results/events/exdrift/exdrift_stage0_rulings_2026-10-27.csv` | the team lead's rulings, one per flag (2026-10-28) |
| `results/events/exdrift/exdrift_sponsor_declarations_2026-10-28.csv` | DG-X2's declaration table: one row per ex-date, with its release's URL, sha, fetch time and three quotes |
| `results/events/exdrift/exdrift_release_sources_2026-10-28.csv` | the 195 releases and how each was found |
| `results/events/exdrift/exdrift_k_2026-10-27.json` | `fit-k`'s output: k and the cap-binding share (fit only) |
| `results/events/exdrift/exdrift_sponsor_notices_2026-10-28.csv` | the verified sponsor notices DG-X2 checks Alpaca against (quotes re-found offline on every run) |
| `results/events/exdrift/EXDRIFT_STAGE0_RULINGS_PROPOSAL_2026-10-28.md` | **the rulings proposal**, one recommendation per flag class |
| `results/events/exdrift/exdrift_fit_descriptive_2026-10-27.csv` | the DG-X7 identity table (fit only) |
| `results/events/exdrift/noop_fetch_cef_distributions_output.txt` | the no-op proof for the fetcher change (§2) |

Tests: `python3 -m pytest scripts/events/tests/test_exdrift_trial.py
scripts/events/tests/test_fetch_exdrift_corp_actions.py scripts/events/tests/test_fetch_exdrift_mub.py
scripts/data/tests/test_fetch_cef_distributions_out.py` (synthetic data and fake clients only).

> **2026-10-28, later: the team lead's rulings applied; Stage 0 CLEAR; `fit-k` run. The test set is NOT opened.**
>
> **The rulings** (team lead, 2026-10-28, answered interactively on
> `results/events/exdrift/EXDRIFT_STAGE0_RULINGS_PROPOSAL_2026-10-28.md`):
> - **"Accept all"**: every recommended ruling in rows 2–17, including the go on `fit-k` (R9).
> - **Declarations (row 1): sponsor releases.** "Build a verified declaration table from the
>   sponsors' own monthly distribution releases (PIMCO, BlackRock, Nuveen, DoubleLine,
>   AllianceBernstein) for every test event. Keep each quote, its URL and fetch time, so it can be
>   re-checked. A fund or event whose release cannot be found is excluded and counted, never
>   guessed."
>
> The rulings file holds all 843 flags, `ruled_by` "team lead", `ruled_on` 2026-10-28. It was
> written by `exdrift_trial.py apply-rulings` from the class table `CLASS_RULINGS`.
>
> **The declaration table** is `exdrift_sponsor_declarations_2026-10-28.csv`. It was built by
> `scripts/events/fetch_exdrift_sponsor_releases.py fetch` + `build`.
> - **195 releases**: PIMCO 48, BlackRock 43, DoubleLine 45, AllianceBernstein 48, Nuveen 11.
>   Each one's source and discovery method is in `exdrift_release_sources_2026-10-28.csv`.
> - Every quote is re-found offline on every run.
> - Coverage of the test events, by R4 (a declaration dated e−1 passes):
>
> | sponsor | declared by e−1 | declared late | no release found (excluded) |
> |---|---:|---:|---:|
> | PIMCO | 270 | 0 | 0 |
> | BlackRock | 177 | 0 | 2 (BIT, HYT 2024-01-11: no January 2024 release is carried by any host reached) |
> | DoubleLine | 45 | 0 | 0 |
> | AllianceBernstein | 48 | 0 | 0 |
> | **Nuveen** | **42** | 0 | **184** |
>
> - **Leads.** Declarations precede the ex-date by 4 to 74 sessions (median 8). None falls on e−1.
>   The long leads are BlackRock's quarterly releases of 2026.
> - **Nuveen.** Nuveen's release of 2019-10-02 says that from about 2019-11-01 it stopped announcing
>   distributions by press release and posts them on nuveen.com [V]. Its wire releases since then
>   come only in months with changes: 11 found for the test window. nuveen.com and CEFConnect answer
>   scripted requests with a "request blocked" page, and no block was worked around.
> - **So 184 of the 226 Nuveen events are excluded, under the ruling.** That is most of NAD, NEA,
>   NVG, NZF and JFR.
> - Alpaca's announcement `declaration_date` contradicts the sponsor table on all 593 events where
>   both exist.
>
> **Reading R10** (new; it applies the ruling's own words, and is for the team lead to confirm
> before `open`). In the H-E declared calendar, a basket fund whose ex-date in [e+1, e+8] has no
> release found is excluded from that event's basket and counted (1,210 legs). Keeping those legs
> would assume they were undeclared, and their run-up would sit on the hold rows.
>
> **The eligible set, as ruled.** Dates only. Rules 1–5, the X4 cells filled from Alpaca, R10:
> - **545 events** (511 on the 13) on 133 dates in 46 months;
> - 186 excluded for declarations and 37 for a basket of fewer than 3;
> - beside: 575 with the no-release basket legs kept, and 531 with the X4 cells not filled.
>
> **Gates:** DG-X1 FLAGGED (ruled); DG-X2 FLAGGED (186, ruled); DG-X3 PASS; DG-X4 FLAGGED (ruled);
> DG-X5 FLAGGED (ruled); DG-X6 FLAGGED (ruled: wait); DG-X7 PASS (identity; k committed); DG-X8
> PASS. **STAGE 0: CLEAR**, meaning every gate passes or is flagged with every flag ruled.
>
> **`fit-k`** (fit 2005–22 only, committed in its own commit before anything else:
> `exdrift_k_2026-10-27.json`):
> - The raw H-E sleeve has 3,000 events (9 removed by rule 2) and σ_active 36.40%/yr on 1,351
>   active sessions.
> - **k = 0.1648** (= `spec.VOL_TARGET` 0.06 ÷ σ_active).
> - **The cap-binding share is 0**: `_cap_gross` at `spec.MAX_GROSS_STRESS` 1.8 binds on 0 of 1,351
>   decision rows. The raw sleeve's largest gross after netting is 10.67, so its sized maximum is
>   1.758. That was checked on positions only.
> - No mean, Sharpe or t was formed.
>
> **What still blocks `open`** (it refuses on each in code, or by the team lead's instruction):
> 1. **The X6 ruling's wait.** French's daily factors end 2026-09-30 (vintage 202609), and the test
>    window runs to 2026-10-06. `open_preconditions` re-measures this and refuses today.
> 2. **The team lead sees this final Stage 0 state first** (instruction of 2026-10-28). That
>    includes R10, and the Nuveen exclusions, which take most of the 4 munis out of the test.
> 3. **The `open` stage itself is a stub.** It is written and reviewed after the team lead's go,
>    and run once.
>
> No 2023+ return, P&L, price change or NAV change was computed. EVENTS stays 3.
>
> ---
>
> **2026-10-28: re-run on the team lead's Alpaca fetch** (`run_exdrift_ca.sh`, fetched
> 2026-10-27T21:38:45Z: v1 801 records; announcements 785 rows, every window HTTP 200; the 24 flagged
> bars). `python3 scripts/events/exdrift_trial.py notices` then `stage0`, offline.
>
> | gate | now | in one line |
> |---|---|---|
> | DG-X1 | **FLAGGED** (32) | Every one of the 769 yfinance ex-dates from 2023-01-01 to the frozen end is on Alpaca, and Alpaca has none that yfinance lacks. 737 amounts agree within $0.001 (254 exactly). **The 32 that do not are all BIT, 2023-01-12 → 2025-08-15**, every ex-date before BIT's 2025-08-19 split record: yfinance 0.1205 against Alpaca 0.1237, after which they agree. The cause is [U] (a restated yfinance history is the likely one) |
> | DG-X2 | **FAIL** | **Alpaca's announcement `declaration_date` is not a declaration date.** PIMCO's own release, dated "NEW YORK, NY, October 1, 2025", declares the distributions with ex-date 2025-10-14 for PCN, PTY, PHK, PFN, PDI and PDO. Alpaca gives 2025-10-12, a Sunday, for all six. Over all 785 announcements the field sits 1–3 weekdays before the record date (2 weekdays on 688), and after it on 6: it is derived from the record date. **On that field 32 events would be "declared late" and excluded.** That count is printed and not flagged, because the field is invalid. One class flag, `X2_source_invalid` |
> | DG-X3 | **PASS** | All 768 events have one Alpaca record date. Every one fits its regime row of §4.2: T+2, record = the session after ex; T+1 from 2024-05-28, record = ex. The announcements' record dates equal v1's on all 785 |
> | DG-X4 | **FLAGGED** (25) | **All 24 `X4_no_bar` cells have an Alpaca raw SIP bar with a close and volume > 0** (presence only). The BIT split flag is unchanged |
> | DG-X5 | **FLAGGED** (589) | 552 repeats on e+1..e+3, as before. **New check, `X5_nav_repeat_on_e` (37 events, 2023–25):** NAV(e) = NAV(e−1) on the ex-date itself. That is a stale cum-distribution NAV, which moves the distribution's NAV drop onto hold row e+1. The fit rate on the same test is 98 of 3,197 (0.031); the test's is 37 of 768 |
> | DG-X6 | FLAGGED (1) | unchanged: the French factors miss 4 sessions |
> | DG-X7, DG-X8 | IDENTITY PASS, k pending; PASS | unchanged |
>
> **The eligible set on the realised calendar.** Rule 1's declaration test cannot run, so this is
> not yet the declared set. Dates only.
> - The 24 cells filled from Alpaca: **729 events** (548 on the 13) on 135 dates.
> - The 24 cells not filled: **705** (532), with the 24 events lacking a bar excluded.
> - Both exclude 39 events whose H-E basket has fewer than 3 funds.
>
> The proposal for every flag class is `results/events/exdrift/EXDRIFT_STAGE0_RULINGS_PROPOSAL_2026-10-28.md`.
> **No 2023+ return, P&L, price change or NAV change was computed.** EVENTS stays 3.
>
> *The banner below is the 2026-10-27 record, before the Alpaca run. Its DG-X1, X2 and X3 rows
> and the flag count are superseded by the table above.*
>
> **Status (2026-10-27): HALTED in Stage 0.** Three gates wait on one credentialed run by the team lead
> (DG-X1's second source, DG-X2, DG-X3: §5). Three gates are FLAGGED and wait on rulings
> (DG-X4, DG-X5, DG-X6). DG-X7's identity gate PASSES. k and the cap-binding share are not
> formed (reading R9). DG-X8 PASSES.
>
> - **No 2023+ return, P&L, price change or NAV change was computed, printed or written.** From
>   2023 on, Stage 0 read ex-dates, amounts, the session calendar, the presence of a close, a NAV
>   and a volume, and two equality tests (volume = 0, NAV(D) = NAV(D−1)). The spike-and-revert
>   guard forms close ratios inside `data_guards`, and only its flag keys leave it (§1, DG-X4).
> - **No fit statistic beyond the identity gate.** The fit was read only to reproduce two
>   published figures.
> - **The test set is not opened.** `open` refuses until Stage 0 is CLEAR, and `fit-k` refuses
>   until every flag is ruled (§4).
> - **The 27 sealed names were never loaded.** Every panel read passes a parquet filter on the 17,
>   and every frame is asserted; the distribution refresh fetched only the 17.

## 1. The gates

| gate | status | what was found | what clears it |
|---|---|---|---|
| **DG-X1** distributions | **AWAITING TEAM LEAD** | **The refresh is done, outside `data/`** (§2). 4,616 rows for the 17, last ex-date 2026-10-15 (the price panel's last session). On the overlap with `data/cef/cef_distributions.parquet` every ex-date and amount is identical (3,831 fit rows, 752 from 2023 on). It adds 33 ex-dates, 2026-09-11 → 2026-10-15. Every ex-date is a session. **The second source is not read yet**: CRSP needs a credential and its ret − retx is a return; `fetch_sponsor_notices.py` covers none of the 17; CEFConnect blocked the scripted request (reading R2) | the team lead's run (§5); then every 2023+ ex-date and amount is compared with Alpaca's (`X1_*` flags) |
| **DG-X2** declarations | **AWAITING TEAM LEAD** | No tracked panel holds a declaration date. Alpaca's deprecated `/v2/corporate_actions/announcements` carries one; whether it still answers is [U] | the same run. **If the endpoint refuses every window, DG-X2 FAILS** and the team lead rules on another declaration source |
| **DG-X3** record dates | **AWAITING TEAM LEAD** | Alpaca's `/v1/corporate-actions` carries the record date; the regime arithmetic of §4.2 (T+2: record = the session after ex; T+1 from 2024-05-28: record = ex) is coded and tested | the same run |
| **DG-X4** bars | **FLAGGED** (25) | **24 `X4_no_bar`:** the event fund has no close on its own ex-date e, on 2026-02-12 (PCN, PDI, PDO, PFN, PHK, PTY), 2026-02-13 (BIT, HYT, JFR, NAD, NEA, NVG, NZF), 2026-02-18 and 2026-03-18 (DSL), and 2026-09-15 (BIT, HYT, JFR, MHD, MQY, NAD, NEA, NVG, NZF). **These 24 cells are every missing close in the 17's 2023+ panel, and every one is on the fund's own ex-date** (each row is present with volume 0 and no close). **1 `X4_split`:** BIT 2025-08-19, factor 1.029. The split-basis guard classes it `undecidable` from the factor alone (\|ln k\| = 0.029 ≤ 2τ = 0.280), so it cannot raise there; rule 3 masks BIT's returns within ±5 sessions (R1), which removes one event. The spike-and-revert guard finds **0** hits and **0** unreverted jumps in the test window. No zero-volume fill day has a close. The panel's sessions equal `ops/schedule/nyse_calendar.py`'s | a ruling per flag. The same run fetches Alpaca's raw SIP bar on each `X4_no_bar` cell, so "fill from a second source" (C4's precedent, 2026-10-14) can be ruled without another run |
| **DG-X5** NAV | **FLAGGED** (552) | NAV is present on e..e+3 for every event (0 `X5_nav_missing`). **552 `X5_nav_repeat`** on the event fund's rows e+1..e+3: 552 of 2,304 cells (0.240). On the same rows in the fit: 1,758 of 9,600 (0.183); by fit era 0.170 / 0.165 / 0.212 / 0.179. By test year 0.223 / 0.263 / 0.243 / 0.225 (2023–26). Basket funds' rows, counted not flagged: 0.240. **The test rate is above every fit era's.** `docs/DATA.md` (correction of 2026-10-12) records Yahoo serving a NAV dated D that carries D−1's value | a class ruling (reading R6). A stale NAV moves the NAV leg towards zero, which is towards PASSING stage 3, so it biases the test for the trade |
| **DG-X6** factors | **FLAGGED** (1) | Test window for the factors: 2023-01-13 → 2026-10-06 (935 sessions, the first event's first return row to the last event's e+3). **French FF5 + UMD** (vintage 202609, fetched 2026-10-27) end 2026-09-30: **4 sessions uncovered**, 2026-10-01 → 10-06. IEF and HYG in `data/etf_daily.parquet` cover it (to 2026-10-09). **MUB:** absent from `etf_daily`; the new fetcher (`scripts/events/fetch_exdrift_mub.py`, yfinance) covers every session, as do its IEF and HYG copies. Source note: `docs/REFERENCES.md` §12az | a ruling on the 4 French sessions (reading R8) |
| **DG-X7** identity | **IDENTITY PASS; k PENDING** | §3. r6 and H-E's dispersion reproduce on the fit. k and the cap-binding share are fit P&L, which this run's brief forbade (R9) | `fit-k`, after the rulings |
| **DG-X8** numexpr | **PASS** | `compute.use_numexpr` is off at import. `numexpr_fault.run()` here: numexpr 2.10.1 returns wrong cells with the option on; the numpy path is clean. The denormal assertion runs on the identity gate's per-event series | — |

## 2. DG-X1: the refresh, and the change to the live-path fetcher

`scripts/fetch_cef_distributions.py` could only write `data/cef/` and fetched every
`cef_universe.csv` name, the 27 sealed ones among them. It is on the live path: the nightly
collector runs it bare. So it gained two options, **both off by default**:

- `--out DIR` writes only the actions panels, and only to DIR. A DIR inside `data/` is refused.
  The features and facts sections are skipped, because both write into `data/cef/`.
- `--tickers A,B,...` fetches only those names, each of which must be in `cef_universe.csv`. It is
  refused without `--out`, because the live panels are replaced whole.

**The no-op is proved byte for byte.** `results/events/exdrift/noop_fetch_cef_distributions.py`
runs the file as it stood at `66ec3df` (taken from git) and the edited file, each in its own
temporary tree, on one fake yfinance with the clock frozen. All seven files and all 17 printed
lines are identical: PASS. The tests pin the default outputs and the refusals. They fail against
the old file, which has no `main` and ignores every argument.

The refresh: `python3 scripts/fetch_cef_distributions.py --out
results/events/exdrift/_cache_exdrift/dist_refresh_2026-10-27 --tickers <the 17>`, run
2026-10-27 20:56 UTC. It is gitignored.

## 3. DG-X7: the identity gate (fit 2005-01-01 → 2022-12-30 only)

| figure | reproduced | published | tolerance | |
|---|---:|---:|---:|---|
| r6 events (the 17, 2005–22) | 3,226 | 3,226 | exact | PASS |
| r6 CAR(+1..+3) | −20.4542bp | −20.454bp | 0.001 | PASS |
| r6 month-clustered t | −6.7655 | −6.765 | 0.001 | PASS |
| H-E per-event sd | 150.280bp | 150.3bp | 0.05 | PASS |

Printed beside it, not gated: 216 months; H-E 3,226 events with a fund return, 3,009 traded,
6.7% with a basket of fewer than 3, median basket 12; sd of monthly means 41.45bp (published
41.4). **The refreshed panel's fit rows are identical to `data/`'s, so the gate holds on the panel
the trial will use.** The fit was read through parquet filters at 2022-12-30. The table is
`exdrift_fit_descriptive_2026-10-27.csv`. No H-E mean was computed.

## 4. The test set, re-measured (dates only; H14: these counts decide nothing)

| | events | on the 13 | dates | months | H-E ≥ 3 (calendar) | on the 13 |
|---|---:|---:|---:|---:|---:|---:|
| pre-registration §5.1 | 752 | 575 | 169 | 45 | 714 | 537 |
| `data/` panel, re-counted | 751 | 574 | 169 | 45 | 713 | 536 |
| **refreshed panel, to the frozen end** | **768** | **587** | **173** | **46** | **729** | **548** |

- **The one-event difference is rule 3**, under reading R1: a BIT event whose hold rows lie
  within 5 sessions of BIT's 2025-08-19 split record. No event is excluded by rule 2.
- **The test set's end is frozen at ex-date 2026-10-12** (R7). That is the earlier of the refreshed
  panel's last ex-date (2026-10-15) and the session 3 before the price panel's last (2026-10-15).
  The last event in the set has e = 2026-10-01.
- By year: 205 / 205 / 204 / 154 (2023–26). T+2: 290; T+1: 478.
- The basket column here needs a bar on e..e+3 and no split-masked row, and it uses every known
  ex-date. The declared-at-e−1 calendar waits on DG-X2.

**The block.**
- `fit-k` calls `require_stage0_rulings_only`. That runs `data_guards.require_stage0_rulings` on
  the committed flag table and the rulings file.
- `open` also calls `require_stage0_clear`. It needs the committed record to say `CLEAR` and a
  committed k.
- Both refuse, naming what is missing. Both are stubs that raise after the block. They are
  written and reviewed once Stage 0 clears.

## 5. What the team lead runs, and what needs a ruling

**One credentialed run** (read-only GETs on the cef paper key; it prints no key). From the main
checkout's root:

```
! bash .claude/worktrees/exdrift-stage0/run_exdrift_ca.sh
```

- The wrapper sits at the worktree root and is excluded from git (`info/exclude`). It sets
  `QUANTT_ENV_FILE` to `config/.env` and runs `fetch_exdrift_corp_actions.py --bars-for
  <the flag table>`.
- It makes about 295 GETs, paced at 0.35s, so it takes about 2 minutes:
  - Alpaca `/v1/corporate-actions` for the 17 from 2023-01-01;
  - the announcements endpoint, per symbol, in windows of at most 90 days;
  - raw SIP bars on the 24 `X4_no_bar` cells.
- Its output goes to the gitignored `_cache_exdrift/`. An agent then re-runs `stage0` offline.
  That adds the `X1_*`, `X2_*` and `X3_*` flags and rewrites the still-blank rulings form.

**Rulings** (each flag has a `recommended` column in the flag table):

| flags | recommended |
|---|---|
| 24 `X4_no_bar` | fill the close from Alpaca's raw SIP bar where it has one (C4, 2026-10-14); otherwise exclude the event and count it. Never fill with zero (rule 4) |
| `X4_split` BIT 2025-08-19 (1.029) | confirm it is not a change to the close's share basis. Rule 3 already keeps it out of every event and basket |
| 552 `X5_nav_repeat` | the test rate is above every fit era's. Before a class ruling, check the flagged cells against a second NAV source (CEFConnect, as the stale-NAV gate does), and rule each stale copy "excluded from the NAV leg, counted" |
| `X6_FF6_uncovered` | wait for French's 202610 vintage and run R-D4 on the whole window (recommended), or run it on the covered sessions and print the 4 |
| R1–R9 | the implementation readings, in `READINGS` of `exdrift_trial.py` and in the flag table. R9 asks for a go on `fit-k` |
| `X1_*`, `X2_*`, `X3_*` | after the run |

**Outside this trial, for the team lead's information.**
- **The 24 missing closes sit exactly on ex-dates** (`docs/REFERENCES.md` §12az). That points to a
  defect in how the daily price fetch handles an ex-date in 2026. The cause is [U]. *Updated
  2026-10-28:* they are yfinance's rows for an "out-of-range" dividend (NaN OHLC, volume 0), kept by
  `scripts/cef/fetch_daily.py`, the live path. See the rulings proposal's last section.
- The panel read here is this checkout's `data/`, through 2026-10-15. Whether prod's panel on the
  VM has the same gaps was not checked.
- `python3 -m ops.doc_audit --check` reports one DRIFT that predates this branch: `docs/SYSTEM.md`
  points to `results/events/_cache_r7_r2_pull/`, which this checkout does not hold. It was
  present at `66ec3df`.

## 6. Inputs and their provenance (no credential was read)

| input | source | label |
|---|---|---|
| prices, NAVs, distributions to 2026-10-15 | this checkout's `data/` (a symlink to the main tree), read-only | [V] dates |
| refreshed distributions | §2, yfinance, 2026-10-27 | [V] |
| French FF5 + UMD | `scripts/data/fetch_ff_factors.py`, 2026-10-27, vintage 202609 | [V] |
| MUB, IEF, HYG (yfinance) | `scripts/events/fetch_exdrift_mub.py --symbols MUB,IEF,HYG`, 2026-10-27T21:02:49Z | [V] dates |
| IEF, HYG | `data/etf_daily.parquet`, dates only | [V] dates |
| Alpaca corporate actions and bars | not yet fetched (§5) | — |

**Trial accounting.**
- EVENTS stays at 3, and CEF at 52. `docs/RESEARCH_STATE.md` is not changed by this run.
- The 2023-01-01 time holdout is not opened.
- The 27 names are not consumed.
