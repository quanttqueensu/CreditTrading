# Number consistency — every quantity this project states about itself

**Measured 2026-09-10, 11:34–11:45 ET, from the dev tree
`~/Desktop/2027/QUANTT/2027` at commit `0c81d3f`.** Prod (`~/prod/QUANTT`,
detached at `v2026.09.10.1`) was read but never written.

**Provenance labels**, as `docs/REFERENCES.md` uses them: `[V]` verified — I
re-derived or re-read the artifact myself in this session; `[S]` sourced —
read from an artifact written by someone else and not independently re-derived;
`[U]` uncertain or unsourceable.

No broker connection was opened for this note. Where broker truth is cited it
comes from `results/ops/BROKER_SNAPSHOT_2026-09-10.json`, a read-only snapshot
taken by a sibling agent at **2026-09-10 11:35:29 ET** (`readonly_connection:
true`, no order placed, modified or cancelled).

---

## 0. The finding that governs the rest

The commissioning brief for this note called the resting-orders disagreement a
case of one artifact being wrong. It is not, and neither were most of the others.

**The dominant failure mode in this repo is two artifacts answering different
questions while appearing to answer the same one.** `orders.csv` and
`_order_map.csv` are both correct. One records what the ledger decided; the
other records what was transmitted. Nothing on either file says so, so a reader
compares them, finds them different, and concludes one is broken.

That has three consequences for how the rest of this note is written:

1. **The authoritative-source table in §12 is keyed by *question*, not by
   quantity.** "What is the NAV" has no single answer and never will; "what
   does the sleeve ledger believe its NAV is" has exactly one.
2. **A right number with no provenance is still a defect.** The four-order
   table in `NEXT_2026-09-11.md` was *correct* — it traces to `_order_map.csv`.
   Its defect was that it carried no reproducing command, so the next reader
   could not tell a transcription from a fabrication, and reasonably suspected
   the latter. Every contradiction below is graded on both axes: is the number
   wrong, and can the reader tell.
3. **Stale numbers outnumber wrong ones, and they are more dangerous**, because
   a stale figure was true when written and therefore carries the author's
   full confidence. Six of the ranked contradictions in §11 are of this kind.

---

## 1. Book NAV and P&L

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| NAV **$504,573.20**, P&L **$4,573.20** | sleeve ledger | `ops/books/cef_live/_ibkr_shadow/cef_discount/nav.csv:3` | 2026-09-09 | `tail -1 ops/books/cef_live/_ibkr_shadow/cef_discount/nav.csv` | [V] |
| NAV **$504,573.20** | book status | `ops/books/cef_live/book_status.json` (`book_nav`) | 2026-09-09 | `python3 -c "import json;print(json.load(open('ops/books/cef_live/book_status.json'))['book_nav'])"` | [V] |
| NAV **$504,573.20**, PnL **$4,573.20** | session report | `ops/books/cef_live/report_2026-09-09.md:3` | 2026-09-09 | `head -3 ops/books/cef_live/report_2026-09-09.md` | [V] |
| NAV **$504,573.20**, PnL **$4,573.20** | session log | `ops/schedule/logs/cef_2026-09-09.log` (`[run_book] BOOK asof`) | 2026-09-09 21:46 | `grep "BOOK asof" ops/schedule/logs/cef_2026-09-09.log` | [V] |
| epoch **2026-09-08 at $500,000.00** | sleeve ledger | `.../nav.csv:2` (`decision=epoch`) | 2026-09-08 | as above | [V] |
| NAV **$504,573.20 at 2026-09-09**, epoch **2026-09-08 at $500,000** | work order | `docs/prompts/NEXT_2026-09-11.md:23-24` | stated 2026-09-10 | none recorded | [V] as to value |
| account **NetLiquidation 999,975.56 CAD** | broker | `results/ops/BROKER_SNAPSHOT_2026-09-10.json` (`account_values`) | 2026-09-10 11:35 ET | read the JSON | [V] |
| **no per-sleeve NAV exists at the broker** | — | — | — | — | [V] |

**Agreement: yes, on the ledger's question.** Every repo artifact that states
the CEF sleeve NAV states $504,573.20 for 2026-09-09, and `NEXT_2026-09-11.md`'s
two NAV claims are both correct. Internal arithmetic checks: cash
$500,700.55 + invested $3,872.65 = $504,573.20, and $504,573.20 / $500,000 − 1
= 0.9146%, which is the `daily_return` field.

**But they are all the same number from the same source.** `_nav_last()` in
`dashboard/server.py:721-733` reads `nav.csv`; `report.py` and
`book_status.json` are written from the same ledger object in the same session.
Five artifacts agreeing here is one measurement quoted five times, not five
measurements agreeing.

**The broker cannot corroborate it.** DUQ199038 is a single CAD-denominated
account carrying three books; it reports one `NetLiquidation` (999,975.56 CAD)
and no per-sleeve figure. The sleeve NAV is a **modelled** quantity: cash seeded
at the 2026-09-08 epoch, marked forward on panel closes. The nearest
independent cross-check available is the broker's unrealised P&L on the 17 CEF
symbols, **+$5,871.76 at 2026-09-10 11:35** — a different day and a different
basis (it runs from `averageCost`, not from the epoch), so it corroborates sign
and order of magnitude only. [V]

`CLAUDE.md` landmine 3 says `_sleeve_nav` "reads the shadow ledger, which
disagrees with the broker on all 17 positions (~$223k account-wide)". **That is
no longer true of the positions** — see §2 — which means the mechanism the
landmine names for the NAV error has been repaired without the landmine being
updated. Whether the *NAV* is still wrong is now an open question that this note
cannot close, because there is no per-sleeve broker NAV to close it against.

---

## 2. Positions and gross exposure

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| gross **$745,271.73**, net **+$3,872.65**, 17 names | sleeve ledger | `.../positions.csv` rows dated 2026-09-09 | 2026-09-09 | sum \|market_value\| over the 17 non-CASH rows | [V] |
| gross **$745,271.73** | book status | `ops/books/cef_live/book_status.json` (`gross_exposure`) | 2026-09-09 | read the JSON | [V] |
| **~$745k gross, dollar-neutral** | work order | `docs/prompts/NEXT_2026-09-11.md:23` | stated 2026-09-10 | none recorded | [V] as to value |
| gross **$739,229.25**, net **+$6,205.13** across the same 17 | broker | `BROKER_SNAPSHOT_2026-09-10.json` (`portfolio`) | 2026-09-10 11:35 ET | sum \|marketValue\| over the 17 | [V] |
| **share counts identical on all 17 names**, broker vs ledger | both | as above | 2026-09-10 11:35 vs 2026-09-09 close | diff the two | [V] |
| gross **$751,463**, long $375,678 / short $375,784, net −$106 | research state | `docs/RESEARCH_STATE.md:421` | **2026-07-31** (deployment day) | none recorded | [S] |
| `gross_leverage: 1.0` | frozen spec | `ops/specs/cef_discount.frozen.json` | 2026-09-06 | read the spec | [V] |
| gross **1.477× NAV** on live weights | derived | — | 2026-09-09 | §9 script | [V] |

**Agreement: yes.** The $6,042 gap between the ledger's $745,272 and the
broker's $739,229 is one day of price movement, not a disagreement — the ledger
figure is struck on the 2026-09-09 close and the broker figure at 11:35 on
2026-09-10. Every share count matches exactly.

Two things a reader should not carry away wrongly:

- **"Dollar-neutral" is a construction property, not a live measurement.** Net
  exposure was −$700.55 at the 2026-09-08 epoch (−0.09% of gross) and
  +$3,872.65 by 2026-09-09 (+0.52% of gross), purely from marks. The book is
  rebalanced to neutral, then drifts.
- **`gross_leverage: 1.0` in the frozen spec does not mean the book runs 1.0×
  gross.** It runs 1.48× NAV, because the 6% volatility target applies a scalar
  — `volscal=1.72` on the 2026-09-09 decision
  (`ops/books/cef_live/target_vs_current.csv`). `plan_diagnostics.py` measures
  the scalar's full-sample mean at **1.50**, pinned at its 2.5 cap on 5.2% of
  days. A reader who takes `gross_leverage: 1.0` at face value will size
  everything downstream 48% too small. [V]

---

## 3. Resting orders — the worked example, resolved

The question this note was commissioned around. **Both artifacts are correct
and they answer different questions.**

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| **4 orders**: JFR SELL 4,630 · MHD BUY 115 · MQY BUY 185 · NEA SELL 4,458, ids 22–25 | adapter order map — **what was transmitted** | `ops/books/cef_live/_ibkr_shadow/_order_map.csv` last 4 rows, recorded `2026-09-10T01:46:28Z` | 2026-09-09 21:46 ET | `tail -4 ops/books/cef_live/_ibkr_shadow/_order_map.csv` | [V] |
| **4 orders**, same symbols, same quantities, `PreSubmitted`, MOC, permIds 260360466–69 | broker — **what is actually resting** | `BROKER_SNAPSHOT_2026-09-10.json` (`open_orders`) | 2026-09-10 11:35 ET | read the JSON | [V] |
| **3 orders**: JFR −4,727 · MQY +169 · NEA −4,565, all `status=open`, no MHD | sleeve ledger — **what the ledger decided** | `.../orders.csv:2-4` | 2026-09-09 21:46 ET | `cat .../orders.csv` | [V] |
| **5 names re-targeted**, JFR MHD MQY NAD NEA, with weights and reasons | strategy — **what the sleeve decided** | `ops/books/cef_live/target_vs_current.csv` | 2026-09-09 21:46 ET | `cat ops/books/cef_live/target_vs_current.csv` | [V] |
| **4 orders**, quantities as transmitted | work order | `docs/prompts/NEXT_2026-09-11.md` | stated 2026-09-10 | none recorded when written | [V] as to value |
| `turnover $0`, **no order line printed** | session log | `ops/schedule/logs/cef_2026-09-09.log` | 2026-09-09 21:46 | `grep "BOOK asof" ...` | [V] |

**Agreement: the transmitted set is confirmed three ways** — adapter order map,
broker open orders, and the work order — and the ledger's three rows are a
different quantity.

### Why they differ, reproduced exactly

The two code paths convert the **same** target weights against the **same**
current positions using **two different NAV denominators**:

| ticker | px | target @ NAV $500,000 | delta | target @ NAV $504,573.20 | delta | transmitted | `orders.csv` |
|---|---:|---:|---:|---:|---:|---:|---:|
| JFR | 7.67 | −10,467 | **−4,630** | −10,563 | −4,726 | −4,630 | −4,727 |
| MHD | 11.10 | −8,741 | **+115** | −8,821 | +35 → **dust** | +115 | *absent* |
| MQY | 10.70 | −1,565 | **+185** | −1,580 | +170 | +185 | +169 |
| NAD | 11.15 | −6,513 | +37 → **dust** | −6,572 | −22 → dust | *none* | *absent* |
| NEA | 10.96 | −11,576 | **−4,458** | −11,682 | −4,564 | −4,458 | −4,565 |

Reproduce with `floor(nav · |w| / price)` on the weights in
`target_vs_current.csv` and the closes in `positions.csv` dated 2026-09-09. The
**$500,000 column reproduces all four transmitted quantities exactly, and the
log's `SKIP NAD +37 @ 11.15 = $413` exactly**; the $504,573.20 column reproduces
`orders.csv` to within one share, the residual being the six-decimal rounding of
the published target weights. [V]

$500,000 is `capital_usd` from the frozen spec, which `_sleeve_nav`
(`src/deploy/broker/ibkr.py:610-621`) falls back to when the ledger's last NAV
row predates the decision — which it did, because the adapter sizes orders
*before* `run_book` advances the ledger to the decision date. Two open faults
follow from this (a transmitted order the ledger never recorded; three recorded
deltas that were never sent) and are **tracked in
`results/ops/LEDGER_DIVERGENCE_2026-09-10.md`** — not duplicated here.

The `[ibkr] arm: ARMED` line appears **twice** in the 2026-09-09 log. Four
orders were sent, not eight, so nothing doubled — but given hard rule 2, it is
worth a look. [V]

---

## 4. Trial counters

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| CEF **48**, GAMMA **0** | canonical counter table | `docs/RESEARCH_STATE.md:16-17` | corrected 2026-09-09 | `sed -n '8,20p' docs/RESEARCH_STATE.md` | [V] |
| CEF **48**, GAMMA **0** | `CLAUDE.md:117` | — | — | — | [V] agrees |
| CEF **48**, GAMMA **0** | `.claude/rules/research-harness.md:62`, `.claude/skills/harness/SKILL.md:36`, `docs/prompts/W1_inference_protocol.md:69`, `docs/prompts/NEXT_2026-09-11.md:25` | — | — | — | [V] agree |
| "counter is at 47; the band is trial 48" | `docs/SYSTEM_AND_STRATEGY.md:497-498` | — | — | — | [V] consistent |
| DSR bar **√(2 ln 48) = 2.7825** | derived | — | 2026-09-10 | `python3 -c "import math;print(math.sqrt(2*math.log(48)))"` | [V] |
| DSR bar **2.15** at N=10, DSR **0.956** | `docs/RESEARCH_AND_METHODOLOGY.md` §553 body, flagged in its own banner | 2026-07-31 | — | [S] known-stale, banner present |
| `trial_log.csv` exists for **credit_rv only** | `results/credit_rv/trial_log.csv` | — | 2026-09-10 | `find results -name "trial_log*"` | [V] |

**Agreement: yes — this is the one quantity the repo gets right everywhere.**
Seven artifacts, one value, and the one stale statement carries a correction
banner naming the right number. This is the standard the rest should meet.

Two residual defects inside `RESEARCH_STATE.md` itself:

- Its **header line 2 says "Global trial count: 156"** while its own table
  row says **LEGACY 162** (line 10). The bars differ: √(2 ln 156) = 3.178 vs
  √(2 ln 162) = 3.190. Small, but it is the canonical file disagreeing with
  itself. [V]
- Its header still says **"Last updated: 2026-07-31"** while the file contains
  2026-09-09 and 2026-09-10 amendments. `CLAUDE.md:158` already flags this.
- **There is no `trial_log.csv` for CEF.** The 48 is prose in one table,
  reconstructed once (the CEF row read 18 for five weeks). Nothing mechanical
  can detect the next drift.

---

## 5. Test count

**Read at 2026-09-10 11:36:58 ET. Another agent was adding tests while I
measured — this number moved under me during the session** (11:35:19 → 219;
11:36:58 → 235, after `src/deploy/tests/test_arm_attribution.py` was written at
11:36). Treat the figure as timestamped, not current.

| value | artifact | date measured | reproducing command | label |
|---|---|---|---|---|
| **235 passed, 1 xfailed** in 8.09s | live suite | 2026-09-10 **11:36:58 ET** | `python3 -m pytest` | [V] |
| **219 passed** | live suite | 2026-09-10 **11:35:19 ET** | same | [V] |
| **126** | `docs/prompts/NEXT_2026-09-11.md:25` | stated 2026-09-10 ~11:15 | none recorded | [V] stale |

Per-suite, at 11:36:58 [V]:

| suite | tests | `CLAUDE.md` claim | verdict |
|---|---:|---|---|
| `src/backtest/tests` | 102 | "~33% exercise `walkforward.py`" | **wrong**. `test_walkforward.py` alone is **30/236 = 12.7%**; the whole backtest suite is 43% |
| `src/deploy/tests/test_band_hold_dust.py` | 5 | "5 tests cover the live strategy" | correct for that file, but `src/deploy/tests` now totals **32 + 1 xfail** |
| `src/deploy/tests/test_halt_scope.py` | 11 | "11 cover the halt gate" | **correct** |
| `.claude/hooks/tests` | 57 | "57 cover the order-path guard" | **correct** |
| `ops/tests/test_doctor_panels.py` | 7 | "**zero** tests for the rest of `ops/`" | **wrong** — doctor has 7 |
| `scripts/cef/tests/test_spec_is_single_source.py` | 29 | not mentioned | added today, commit `666fab9` |
| `src/analysis/tests/test_l1_meanvar.py` | 8 | not mentioned | — |
| `src/deploy/tests/test_arm_attribution.py` | 16 + 1 xfail | "zero tests for `src/deploy/{portfolio,run_book,registry}.py`" | **wrong as of 11:36 today** |

**Agreement: no.** `NEXT_2026-09-11.md`'s 126 is stale by 109 tests, and
`CLAUDE.md`'s coverage breakdown is stale in four of six rows. `CLAUDE.md`'s
*conclusion* — that a green suite says little about the order path — survives
its own numbers: 57 of 236 still test the guard rather than the adapter.

---

## 6. Session and arming counts

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| **armed on 3 of 26 sessions** | `CLAUDE.md:16`, `docs/prompts/00_BRIEF.md:384`, `docs/SYSTEM_AND_STRATEGY.md:37,277,479`, `docs/prompts/W3_session_architecture.md:5`, `docs/prompts/W9_dashboard.md:144`, `.claude/skills/next-task/SKILL.md:30` | undated in all eight | none recorded | [V] **stale** |
| **5 of 29** sessions reached `ARMED`: 08-31, 09-01, 09-04, 09-08, 09-09 | session logs | `ops/schedule/logs/cef_*.log` | 2026-07-31 → 2026-09-09 | `grep -lE "^\[.*\] ARMED:" ops/schedule/logs/cef_*.log \| wc -l` | [V] |
| "the book armed on **09-01, 02, 03, 04, 08 and 09**" | `docs/INFRASTRUCTURE.md:14` (its own 2026-09-10 correction banner) | 2026-09-10 | none recorded | [V] **wrong** |
| **294** broker-confirmed executions, 3 fill dates (07-31: 257, 09-01: 19, 09-08: 18) | `.../broker_fills.csv` | last row 2026-09-08 | `wc -l` and group by `fill_date` | [V] |
| **294** | `CLAUDE.md:156`, `docs/RESEARCH_AND_METHODOLOGY.md:15` | — | — | [V] agree |
| **22 of 24 ledger trade dates are modelled** | `CLAUDE.md:122`, `docs/SYSTEM_AND_STRATEGY.md:159,283`, `.claude/hooks/book_state.py:65`, 3 skills, 2 agents | — | — | [V] **true, but of an archive** |
| 24 distinct fill dates, 397 rows | pre-epoch archive | `.../_pre_epoch_cef_discount_20260907_155225/trades.csv` | 2026-07-31 → 2026-09-03 | group by `fill_date` | [V] |
| **0 rows** | **live** `.../cef_discount/trades.csv` | header-only since the 2026-09-08 re-epoch | `wc -l` | [V] |
| 21 consecutive silent dry-runs, 08-03 → 08-28 | session logs | all `ok_not_armed`, reason `nothing listening on 127.0.0.1:4002` | — | `grep "NOT ARMED" ops/schedule/logs/cef_2026-08-*.log` | [V] confirmed |

**Agreement: no.**

- **"3 of 26" is stale.** By the logs' own `ARMED:` line it is **5 of 29** as of
  2026-09-09. It is repeated verbatim in eight places, none of which dates it.
  If "armed" is read instead as "produced broker-confirmed fills", the answer is
  **3 of 29** — and 2026-07-31, one of those three, shows `ok_not_armed` in its
  own session log, because that day's 257 fills were placed outside the
  scheduled session. So "3" and "5" are both defensible and the docs say which
  neither.
- **`INFRASTRUCTURE.md`'s correction banner is itself wrong.** Added 2026-09-10
  to fix stale figures, it lists 09-02 and 09-03 as armed — both are
  `ok_not_armed` with `[FAIL] broker: nothing listening on 127.0.0.1:4002` —
  and omits 08-31, which armed and transmitted 17 orders.
- **"22 of 24" is true only against an archive.** The live `trades.csv` has been
  header-only since the 2026-09-08 re-epoch. An agent following the claim to the
  live ledger finds zero trade dates and no way to tell whether that is the
  epoch or a fault.

---

## 7. Strategy parameters — `band_width` and the retired 6.4% literal

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| `band_width` **0.048** | frozen spec — **the authority** | `ops/specs/cef_discount.frozen.json` | frozen 2026-09-06 | `python3 -c "import json;print(json.load(open('ops/specs/cef_discount.frozen.json'))['frozen']['band_width'])"` | [V] |
| `BAND_WIDTH = float(frozen("band_width"))` | single reader | `scripts/cef/spec.py:130` | added 2026-09-10 `0b74658` | read it | [V] |
| **"Four analysis scripts baseline against `band(T, 0.064)`"** | `CLAUDE.md:161` | stated ≤ 2026-09-10 | — | [V] **no longer true** |
| `joint_cost_optimiser.py` | imports `BAND_WIDTH` at line 93, uses it at 400/408/417/418/565 | fixed 2026-09-10 `666fab9` | `grep -n BAND_WIDTH scripts/cef/joint_cost_optimiser.py` | [V] |
| `covariance_construction.py` | imports at 59, uses at 156 | fixed 2026-09-10 `9409762` | same | [V] |
| `ou_score.py` | imports at 56, uses at 201 | fixed 2026-09-10 `9409762` | same | [V] |
| `borrow_impact.py` | imports at 37, uses at 105/117; **retains `band(T, 0.064)` at line 106** as a labelled comparison row | fixed 2026-09-10 `9409762` | same | [V] |
| `rebalance_days: 2` present but **inert** while `band_width` is set | frozen spec `_rebalance_days_note` | 2026-09-06 | read the spec | [V] |
| `min_trade_usd` **517.0** | frozen spec `rebalance` | derived 2026-09-08 | read the spec | [V] |
| spec id **`cef_discount.v6.20260906`** | frozen spec | 2026-09-06 | read the spec | [V] |
| spec id **`cef_discount.v5.20260731`** | `docs/INFRASTRUCTURE.md:171` | stale | — | [V] **contradicted by its own banner at line 10** |
| broker port **4002** | frozen infra + preflight PASS in every armed log | 2026-09-01 onward | `grep broker ops/schedule/logs/cef_2026-09-09.log` | [V] |
| broker port **7497** | `docs/INFRASTRUCTURE.md` | **corrected** — no occurrence of 7497 outside the banner remains | `grep -n 7497 docs/INFRASTRUCTURE.md` | [V] fixed |

**Agreement: the parameter, yes; the warnings about it, no.** `band_width` is
0.048 everywhere it is read from, and all four named scripts now read it from
the spec — **`CLAUDE.md:161` and the `docs/INFRASTRUCTURE.md` port warning in
`CLAUDE.md:155` both describe faults that were repaired earlier today.** A
warning that outlives its fault teaches the reader to discount the warnings.

The remaining live defect is inside `INFRASTRUCTURE.md`: its banner (line 10)
says v6 and its body (line 171) says v5. A reader who skips banners — which is
what a `grep` does — gets the wrong answer.

---

## 8. Universe size

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| **17** names (AWF BIT DSL HYT JFR MHD MQY NAD NEA NVG NZF PCN PDI PDO PFN PHK PTY) | frozen spec — **the authority** | `ops/specs/cef_discount.frozen.json` `frozen.universe` | 2026-09-06 | `python3 -c "import json;print(len(json.load(open('ops/specs/cef_discount.frozen.json'))['frozen']['universe']))"` | [V] |
| **17** positions | sleeve ledger `positions.csv`, both dates | 2026-09-08, 2026-09-09 | count non-CASH rows | [V] |
| **17** rows | `target_vs_current.csv` | 2026-09-09 | `wc -l` | [V] |
| "all **17** deployed ticker(s) priced" | preflight | `ops/schedule/logs/cef_2026-09-09.log` | 2026-09-09 | read the log | [V] |
| **17** CEF symbols in a 34-symbol account | broker | `BROKER_SNAPSHOT_2026-09-10.json` | 2026-09-10 11:35 | read the JSON | [V] |
| **42** tickers | `config/costs.yaml` `tickers` | — | `python3 -c "import yaml;print(len(yaml.safe_load(open('config/costs.yaml'))['tickers']))"` | [V] |
| **17** CEFs | `docs/prompts/NEXT_2026-09-11.md:23`, `CLAUDE.md:14` | — | — | [V] agree |

**Agreement: yes.** `costs.yaml`'s 42 is not a contradiction — it is a cost
table spanning every instrument any book might trade, and the universe is not
defined there. Worth stating explicitly, because 42 vs 17 looks like a
disagreement to a reader who does not know that.

The 17 CEF tickers are held by the CEF book **alone**; the other two books in
DUQ199038 hold ETFs (AGG ANGL BKLN EMB HYG IEF IGSB JNK LQD SHY SHYG SJNK SPHY
SRLN USHY VCIT VCSH). Landmine 7's ban on attributing a symbol from the account
net still binds as a rule, but on these 17 names today the account net and the
sleeve coincide. [V]

---

## 9. IC, transfer coefficient, effective breadth

| value | artifact | file:line | date measured | reproducing command | label |
|---|---|---|---|---|---|
| IC **−0.074**, t **−11.6** | `CLAUDE.md:8`, `docs/prompts/00_BRIEF.md:23,63` | undated | — | [V] reproduces |
| IC **−0.0747**, t **−11.68** | `docs/PLAN.md:729` | 2026-09-06 | `python3 scripts/cef/plan_diagnostics.py` | [S] |
| IC **−0.0747**, t **−11.69**, n = 2,951 non-overlapping 2-day periods | **re-run today** | — | 2026-09-10 11:40, panel to 2026-09-09 | `python3 scripts/cef/plan_diagnostics.py` | [V] |
| TC **~37%** = 0.43 / 1.16 | `CLAUDE.md:13`, `docs/prompts/00_BRIEF.md:40,376` | undated | `scripts/cef/band_frontier.py` | [S] |
| band 4.8%: gross SR **1.17**, net@15bp **0.67**, turn/yr **17.6**, hold 12.6d | **re-run today** | — | 2026-09-10 11:40, sample 2005-01-03 → 2026-09-09 (5,455 days) | `python3 scripts/cef/band_frontier.py` | [V] |
| band net@15bp **0.66** pre-borrow, **~0.43** after | `CLAUDE.md:154`, `docs/PLAN.md` banner | 2026-09-06 | same | [V] drifted to 0.67 |
| effective breadth **1.17** today, 2.24 historical | `CLAUDE.md:14`, `docs/prompts/00_BRIEF.md:32,382`, `docs/PER_NAME_ARCHITECTURE.md:14` | undated | `/api/factors` | [V] **stale** |
| effective breadth **1.29** on live weights | **re-derived today** | — | weights of 2026-09-09, panel to 2026-09-09 | §9 script below | [V] |
| effective breadth **2.24** of 17, historical sleeve weights, 1,427 days | **re-run today** | — | 2026-09-10 | `python3 scripts/cef/plan_diagnostics.py` | [V] |
| PC2 = **92.5%** of current book variance | `CLAUDE.md:15`, `00_BRIEF.md:32,67`, `PER_NAME_ARCHITECTURE.md:192` | ~2026-09-09 | `/api/factors` | [V] **stale** |
| PC2 = **87.8%** on live weights | **re-derived today** | — | 2026-09-09 | §9 script below | [V] |
| PC2 = **65.7%** historical | `docs/PLAN.md` | 2026-09-06 | `plan_diagnostics.py` | [V] reproduces as 65.8% today |

**Do reproducing scripts exist and still run? Yes, for two of the three.**

- **IC −0.074**: `scripts/cef/plan_diagnostics.py` ran clean today (rc=0, 15s)
  and printed IC −0.0747, t −11.69. **Reproducible.** [V]
- **TC ~37%**: `scripts/cef/band_frontier.py` ran clean today (rc=0, 9s) and
  printed gross 1.17 / net@15bp 0.67 for the live band. 0.43/1.17 = **36.8%**,
  so ~37% holds. The *borrow* half of it (0.43) is a **single measurement taken
  on 2026-09-06** and applied to 21 years, per `.claude/rules/documents.md`; the
  borrow panel did **not** refresh on 2026-09-09 (`fetch_borrow_rates.py` died
  with HTTP 404). **Reproducible, conditional on a one-off borrow figure.** [V]
- **Effective breadth 1.17**: the documented figure comes from the dashboard's
  `/api/factors`, which prefers **broker** positions and falls back to the
  ledger. It is not a script, it is an endpoint, and it recomputes on every
  call — so the published 1.17 is a **screenshot of a moving number with no
  stored date**. Re-deriving it today with the identical maths gives **1.29**.
  **Reproducible only in the sense that the method survives; the published
  value does not.** [V]

Reproduction of the breadth figure, no broker connection (the snapshot confirms
broker and ledger share counts are identical today, so the fallback path gives
the same answer as the live path):

```
# weights: ledger positions.csv @2026-09-09 × panel closes ÷ NAV 504,573.20
# maths:   dashboard/server.py::_decompose — LedoitWolf covariance, 252d window
# result:  247 clean joint returns; PC1..PC4 = 2.1 / 87.8 / 0.1 / 0.1 %
#          br_eff 1.29; sqrt(n/br) overstatement 3.63; gross(w) 1.477
```

**A trap worth naming: `1.17` is simultaneously the live band's gross Sharpe and
the claimed effective breadth.** Both appear within seven lines of each other in
`CLAUDE.md` (lines 13–14) and within ten in `00_BRIEF.md` (lines 32–40). They
are unrelated quantities. Anyone grepping `1.17` will find both.

---

## 10. Where prod and dev stand

| value | artifact | date measured | reproducing command | label |
|---|---|---|---|---|
| prod detached at **`v2026.09.10.1`** (`2a7c486`) | git | 2026-09-10 | `git -C ~/prod/QUANTT describe --tags` | [V] |
| dev at `0c81d3f`, branch `cleanup/2026-09-10-prompts-and-hygiene` | git | 2026-09-10 11:35 | `git worktree list` | [V] |
| **all seven** cef ledger files byte-identical, dev vs prod | filesystem | 2026-09-10 | `diff` each | [V] |
| `~/prod/QUANTT/ops/schedule/logs/` is **empty** | filesystem | 2026-09-10 | `ls ~/prod/QUANTT/ops/schedule/logs/` | [V] |
| the 2026-09-09 session ran from **dev** | session log's own absolute paths | 2026-09-09 | `grep Desktop ops/schedule/logs/cef_2026-09-09.log` | [V] |
| "2026-09-10 was the first end-to-end session on the prod tree" | `docs/prompts/NEXT_2026-09-11.md:44` | stated 2026-09-10 11:15 | — | [V] **anticipatory** |
| no active halts | filesystem | 2026-09-10 | `ls ops/HALT*.md` → none | [V] |
| heartbeat: `benchmarks` **failed** rc=3, `watchdog` **stale** | `ops/heartbeat.json` | 2026-09-09 17:25 / 19:30 | read the JSON | [V] |

**Agreement: partly.** `NEXT_2026-09-11.md`'s §0 state block is written in the
past tense about a session that had not yet run when it was written. Its own
verification command, `grep -c . ops/schedule/logs/cef_2026-09-10.log` run in
`~/prod/QUANTT`, **cannot succeed** — that directory is empty and the file does
not exist. The prompt tells the reader to "stop and say so" if the checks
disagree, which is the right instinct pointed at a check that must fail.

---

## 11. Contradictions, ranked

Worst = most likely to be read as fact by a future session and acted on.
"Wrong" and "unprovenanced" are graded separately.

| # | contradiction | value A | value B | why it ranks here |
|---:|---|---|---|---|
| **1** | **Effective breadth** | **1.17** — `CLAUDE.md:14`, `00_BRIEF.md:32,382`, `PER_NAME_ARCHITECTURE.md:14`, all undated | **1.29** re-derived 2026-09-10 on the live weights | `00_BRIEF.md` calls breadth "the biggest hole in the strategy" and W10 is scoped against it. It is a *live* quantity published without a date, so it reads as current and is not. Every `IR = IC·TC·√BR` sum in the repo uses it. |
| **2** | **Armed-session count** | **3 of 26** — eight documents, none dated | **5 of 29** by the logs' own `ARMED:` line, 2026-09-09 | Repeated more times than any other figure here and dated in none of them. It is the headline uptime metric, the justification for W3, and it is the kind of number a reader assumes is maintained because it is quoted so often. |
| **3** | **`INFRASTRUCTURE.md`'s own correction banner** | "armed on 09-01, **02, 03**, 04, 08 and 09" (line 14) | 09-02 and 09-03 are `ok_not_armed`, broker refused; 08-31 armed and is omitted | A banner added *yesterday to correct stale numbers* states wrong ones. It carries maximum authority precisely because it is a correction, and it is the one place a careful reader will trust without checking. |
| **4** | **PC2 variance share** | **92.5%** — `CLAUDE.md:15`, `00_BRIEF.md:32,67`, `PER_NAME_ARCHITECTURE.md:192` | **87.8%** re-derived 2026-09-10 | Same defect as #1 and it travels with it. `PER_NAME_ARCHITECTURE.md:195` already had to disambiguate 92.5 from 65.7 — the file knows the number is period-dependent and still publishes it undated. |
| **5** | **Test count** | **126** — `NEXT_2026-09-11.md:25` | **235 passed, 1 xfailed** at 2026-09-10 11:36:58 ET | Sits in a "verify, do not assume" state block whose instruction is to *stop* if reality disagrees. A next session that follows the instruction stops on a number that was merely never updated. |
| **6** | **`CLAUDE.md`'s test-coverage breakdown** | "~33% walkforward · 5 strategy · **zero** for the rest of `ops/` · zero for `src/deploy/{portfolio,run_book,registry}`" | walkforward is 12.7%; `ops/tests` has 7; `test_arm_attribution.py` has 16+1 | Four of six rows wrong. The conclusion still holds, which is what makes it survive unaudited. |
| **7** | **`CLAUDE.md:161` — four scripts hardcode 6.4%** | "read `band_width` from the frozen spec; never edit the literal" | all four now import `BAND_WIDTH` from `scripts/cef/spec.py` (commits `0b74658`, `9409762`, `666fab9`, today) | A warning outliving its fault. Costs a reader time and, repeated, trains them to skim the warnings that still bite. |
| **8** | **`CLAUDE.md` landmine 3 — ledger disagrees with broker on all 17 positions** | "~$223k account-wide" | **all 17 share counts identical**, broker read 2026-09-10 11:35 | The mechanism the landmine blames for wrong NAV is gone. Whether NAV is still wrong is now unknown, and the landmine's confident wrongness makes it *less* likely anyone checks. |
| **9** | **`INFRASTRUCTURE.md` spec version** | banner line 10: **v6.20260906** | body line 171: **`cef_discount.v5.20260731`** | Same file, two answers. A `grep` for the spec id finds the wrong one, because banners are not what greps return. |
| **10** | **"22 of 24 ledger trade dates are modelled"** | true of `_pre_epoch_cef_discount_20260907_155225/trades.csv` (24 dates, 397 rows) | the **live** `trades.csv` is header-only since the 2026-09-08 re-epoch | Quoted in eight places including `book_state.py` and three skills. An agent checking it against the live ledger finds nothing and cannot tell an epoch from a fault. |
| **11** | **`RESEARCH_STATE.md` internal** | header line 2: "Global trial count: **156**" | table line 10: LEGACY **162** | The canonical trial file disagreeing with itself. Bars 3.178 vs 3.190 — immaterial today, but it is the file everything else defers to. |
| **12** | **Band net Sharpe** | **0.66** @15bp — `CLAUDE.md:154`, `PLAN.md` banner, 2026-09-06 | **0.67** re-run 2026-09-10 on a panel four sessions longer | Benign drift, listed for completeness. It is evidence the reproduction works, not that anything is wrong. |
| **13** | **Resting orders — the commissioning example** | `orders.csv`: 3 rows, JFR −4,727 / MQY +169 / NEA −4,565 | `_order_map.csv` + broker: 4 orders, JFR −4,630 / MHD +115 / MQY +185 / NEA −4,458 | **Both correct, different questions.** Ranks low as a *contradiction* and high as a *lesson*. The real defect was that `NEXT_2026-09-11.md` published the right numbers with no reproducing command, so a reader could not distinguish transcription from invention — and reasonably assumed the worse. Now resolved in `NEXT_2026-09-11.md` (`ad85a59`) and `results/cef/FIRST_BAND_SESSIONS.md`; faults tracked in `results/ops/LEDGER_DIVERGENCE_2026-09-10.md`. |

### Proposed correction, one line each

1. Replace `1.17` with "1.29 (2026-09-09 weights); re-measure via `/api/factors`, and state the date with the number".
2. Replace "3 of 26" with "5 of 29 armed, 3 with broker-confirmed fills, as of 2026-09-09" and say which definition is meant.
3. Correct the `INFRASTRUCTURE.md` banner list to 08-31, 09-01, 09-04, 09-08, 09-09.
4. Replace `92.5%` with "87.8% (2026-09-09 weights)" and date it wherever it appears.
5. Delete the `tests 126` line from `NEXT_2026-09-11.md` §0 and replace it with the command, not the answer.
6. Replace `CLAUDE.md`'s coverage breakdown with today's per-suite table, or with the command that regenerates it.
7. Rewrite `CLAUDE.md:161` as a *rule* — "analysis scripts import `BAND_WIDTH` from `scripts/cef/spec.py`; `test_spec_is_single_source.py` enforces it" — not as a list of offenders.
8. Rewrite landmine 3 to say the positions now agree and that the per-sleeve NAV has no broker cross-check.
9. Change `INFRASTRUCTURE.md:171` to `cef_discount.v6.20260906`.
10. Add "(pre-epoch archive `_pre_epoch_cef_discount_20260907_155225`)" to every "22 of 24" citation.
11. Change `RESEARCH_STATE.md`'s header to "Global trial count: 162" or drop the header figure and defer to the table.
12. No action; the drift is the reproduction working.
13. No further action — resolved. Adopt §12 below so the next one is caught by shape rather than by luck.

---

## 12. Which artifact is authoritative for which question

**This is the durable output.** Rows are keyed by *question*, not by quantity,
because most of the contradictions above were two artifacts answering different
questions. Quote the artifact that answers the question you are actually asking,
name it inline, and date it.

| question | authoritative artifact | why it, and not the others |
|---|---|---|
| **What is resting at the broker right now?** | `ib.reqAllOpenOrders()` — one read-only connection | The only source that can say an order is still working. Nothing in the repo can. |
| **What was transmitted, and when?** | `ops/books/<book>/_ibkr_shadow/_order_map.csv` | Written by the adapter **at placement**, carries the IBKR `orderId`. An order id is not reconstructible after the fact. |
| **What did the strategy decide, and why?** | `ops/books/<book>/target_vs_current.csv` | Carries target weights, the z-score and the band/hold reason per name. The only artifact that records *why*. |
| **What does the sleeve ledger believe it did?** | `.../cef_discount/orders.csv` | The ledger's own step from **its** position and **its** NAV. Legitimately differs from the order map — see §3. Never cite it for what was sent. |
| **What actually filled?** | `.../cef_discount/broker_fills.csv` | Broker-confirmed executions with `execId` and commission. **The only evidence of a fill.** `trades.csv` contains modelled fills. |
| **What is actually held?** | broker `ib.positions()` / `ib.portfolio()` | Three books share DUQ199038 — never attribute a symbol from the account net (landmine 7). Today the 17 CEFs are the CEF book alone; that is a fact to re-check, not to assume. |
| **What does the ledger believe is held?** | `.../cef_discount/positions.csv` | Marked on panel closes, not broker marks. Agrees exactly with the broker as of 2026-09-10 11:35 — verify, do not assume. |
| **What is the sleeve NAV / P&L?** | `.../cef_discount/nav.csv` | Modelled, epoch-seeded. `book_status.json`, `report_*.md`, the log's `BOOK asof` line and the dashboard all restate it — they are not corroboration. |
| **What is the account worth?** | broker `NetLiquidation` | CAD, whole account, all three books. Not comparable to a sleeve NAV without an FX and an attribution step. |
| **What are the live strategy parameters?** | `ops/specs/cef_discount.frozen.json` | Named as the authority by `INFRASTRUCTURE.md`'s own banner. `band_width` 0.048, universe 17, spec `v6.20260906`. Prose about parameters is always downstream. |
| **What width do analysis scripts baseline against?** | `scripts/cef/spec.py` (`BAND_WIDTH`, `LIVE_POLICY`) | Single reader over the frozen spec, enforced by `scripts/cef/tests/test_spec_is_single_source.py` (**27** tests, re-counted 2026-09-10 evening; this said 29). |
| **How many trials have been spent?** | `docs/RESEARCH_STATE.md` counter table (**not** its prose, **not** its header) | Declared canonical by `.claude/rules/documents.md`. CEF 48, GAMMA 0. The header's 156 vs the table's 162 is a known defect. |
| **How many tests pass?** | `python3 -m pytest`, run now | Moved by 16 during the 100 seconds I spent measuring it. Never quote a stored count. |
| **Did a session arm, and why not?** | `ops/schedule/logs/cef_<date>.log` — the `ARMED:` / `NOT ARMED ->` line | `heartbeat.json` carries only the last beat per job. The log carries the blocker text. |
| **What is the current operational state?** | `ops/heartbeat.json` + `ls ops/HALT*.md` | Global `HALT.md` blocks every book; `HALT_<book>.md` blocks one and warns the rest. Neither exists as of 2026-09-10 11:45. |
| **Is the gross Sharpe / net / turnover figure current?** | `python3 scripts/cef/band_frontier.py`, re-run | Prints the live policy read from the spec and the sample end date in its header. Any stored Sharpe is a dated observation. |
| **Is the IC current?** | `python3 scripts/cef/plan_diagnostics.py`, re-run | Reproduces IC, kappa, PCA, ADV and the vol scalar in 15s. |
| **What is the effective breadth?** | `/api/factors`, or `_decompose` re-run on today's weights | A *live* quantity. There is no stored value with a date attached, and every published figure is a screenshot. |
| **What is running in production?** | `git -C ~/prod/QUANTT describe --tags`, and the absolute paths inside the session log | The dev tree reaches nothing. A log's own paths are the only proof of which tree ran a session. |

### The rule this implies

Three habits would have prevented every contradiction in §11:

1. **A stated number carries its date and its command, or it is not stated.**
   Not "effective breadth 1.17" but "1.29 (2026-09-09 weights, `/api/factors`)".
   `results/cef/FIRST_BAND_SESSIONS.md` is the model — it opens with a table of
   which artifact answers which question, then labels every figure `[V]`/`[S]`.
2. **A correction banner is a claim like any other and must be re-derived before
   it is written.** `INFRASTRUCTURE.md`'s banner is wrong about arming, and it is
   wrong *because* correcting felt like verifying.
3. **Prefer publishing the command to publishing the answer.** `NEXT_2026-09-11.md`
   §0 would have survived contact with reality if it had said
   `python3 -m pytest -q | tail -1` instead of `tests 126`. H14 already says no
   decision rule may key on a number in a document; this extends it — a *state
   block* should not contain numbers at all, only the commands that produce them.
