# Where the alpha leaks, what we overlooked, and what to do — 2026-10-13

**Report only. Spends no trial (CEF counter stays 50). Changes no spec and nothing
on the live path. Trades nothing.**

**The question** (team lead, 2026-10-13): investigate the strategy and what is
deployed; find what we have overlooked and where alpha is being lost between the
backtest and the broker; and say what genuinely needs doing to raise returns.

**How it was made.** Five strands, read together with the notes `main` already
held:

| strand | what it did | where its figures come from |
|---|---|---|
| 1. Web research | A deep-research workflow on five angles chosen to avoid repeating `SCALING_RESEARCH_2026-10-08.md`. 24 sources, 108 claims, 25 put to a three-vote adversarial check: 16 confirmed, 9 refuted, synthesised into 10 findings | `docs/REFERENCES.md` §12t |
| 2. The live record | Every session 2026-09-29 → 2026-10-13 on both prod machines, read-only from the VM's and the laptop's state directories and the collector's broker fills | `alpha_leakage/code/live_record/` |
| 3. What binds the return | Vol target against the gross cap, cash on collateral, effective breadth and the distribution leg, on the canonical harness | `alpha_leakage/code/return_levers/` |
| 4. Research–live parity | The live sleeve and session code against `build_targets` → band → cap → `evaluate()` | `alpha_leakage/code/parity/` |
| 5. Timing decay | IC by lag, and whether refreshing the price leg at send time recovers the lost day. Fit period only | `alpha_leakage/code/timing/` |
| Already on `main` | `W4_ARTIFACTS_2026-10-11`, `REAL_MONEY_COSTS_2026-10-12`, `LIVE_NAV_QUALITY_2026-10-12`, `CORE_SIGNAL_CANDIDATES_2026-10-12`, `EXEC_CAPACITY_OPEN_CROSS_2026-10-13`, `EVENT_DRIVEN_POD_2026-10-12` §5 | those notes |

**Provenance of the code.** The scripts under `results/cef/alpha_leakage/code/`
are the agents' working scripts, copied as written. They were run from the
session scratchpad with the repo root on `sys.path`. They are **not reviewed
harness code**. By the plan's own rule (`RESEARCH_PLAN_2026-10-09.md` §0), a
pre-registration may cite one of their figures only after it has been re-run in
the repo. Strand 4 cross-checked its target loop against `build_targets()`
byte-for-byte. Strand 3 reproduced `PREREG_ALPACA_V7_2026-09-28.md` §5. Strand 5
reproduced W4's IC exactly.

**Panels.** `data/cef/cef_prices.parquet` last 2026-09-28; `cef_nav.parquet` last
2026-09-25. The harness therefore ends 2026-09-25. Distributions run to the
2026-09-10 ex-date; the IBKR fee panel runs 2021-09-13 → 2026-09-09.

**Code.** Read at `main` (7512c98, then 35c6514) and at the prod tag
`release-20261011-1`.

**Holdout.** Any *variant* is reported on the fit period only (before
2023-01-01). Rows for the *deployed* policy on 2023–26 appear only where H13 asks
for a holdout row. They are labelled, and nothing is chosen from them.

**Labels.** Every figure is **[V]** (measured this session by the named script)
unless marked otherwise.

---

## 0. The answer

1. **The biggest leak is that the evidence and the live book are not the same
   strategy.**
   - On the 13 names with the $3m ADV floor, fewer than `min_names` (6) were
     eligible on most fit-period sessions. In 2015–20 and 2023 the median was 5
     eligible names. On those days the harness **holds the previous target**,
     while the live sleeve **sells the whole book**.
   - In 2016 the harness held a stale target on 201 of 252 sessions. Much of the
     2015–23 evidence is therefore a frozen basket.
   - Since 2024 at least 6 names have been eligible every session, and all 13
     on each of the last 60. The live book therefore runs a denser strategy than
     its evidence describes.
   - If the ADV floor bites again, the live book liquidates; the backtest never
     did. AWF already sits at the floor.
2. **The deployed signal is weaker and faster than the brief's headline.**
   - Its IC is **−0.033 (t −1.68)** (W4), not the 17-name −0.074.
   - Its half-life is about **1.1 sessions**.
   - Its largest single-day IC is on day *t*+1, which no evening decision can
     earn. The one-day delay costs about a fifth of gross Sharpe (fit 0.85 →
     0.69).
3. **For real money, borrow decides. At Alpaca it turns into availability.**
   - `REAL_MONEY_COSTS_2026-10-12.md` found the gate fails: the book is positive
     net only in the 2025–26 fee regime, and nothing in it reacts to fees.
   - At Alpaca, easy-to-borrow shorts have cost $0 since 2025-10-01 [V, §12t].
     So the cost arrives as names flipping to hard-to-borrow or unshortable
     (AWF and MHD on 2026-10-08, PHK on 2026-10-13). The book then loses shorts
     instead of paying for them.
4. **Live, the book executed 47% of the notional it planned** in its first 11
   eligible sessions. It traded on 7 of the 11. The losses came from gates and
   connectivity, not from the market. Several of the fixes are on `main` but
   not yet in prod.
5. **Return levers nobody had counted:**
   - **Cash on collateral:** +1.7%/yr over the traded era at T-bill rates, and
     +4.5%/yr in 2023–26. It is not alpha, and whether the broker pays it is
     open.
   - **The vol target binds before the gross cap.** The cap binds on 10% of
     days.
   - **Portfolio margin** would lift the leverage ceiling far above Reg T. But
     costs and **closing-auction capacity** (our orders are already about 31%
     of the closing cross at $100k) bind first.
6. **Negative results, recorded against ourselves:**
   - A send-time refresh of the price leg does not recover the lost day.
   - Raising the vol target under Reg T adds little net, and nothing at 30bp.

---

## 1. Ground truth as of 2026-10-13

| what | value | source |
|---|---|---|
| Prod | VM, ARMED, `release-20261011-1`; laptop off, but its plists still say `DRY_RUN=0` | `python3 -m ops.orient` PROD |
| Live equity | $100,241.60 at the 2026-10-13 close, broker-confirmed | orient PROD |
| Spec | `cef_discount.v7.20260928`: 13 names, `z_window` 252, band 4.8%, vol target 6%, `max_gross_stress` 1.80 | orient SPEC |
| Counters | CEF 50 (bar 2.797); GAMMA, EVENTS, XASSET 0 | orient TRIALS |
| On `main`, not in the prod tag | `7896c0b` (re-fit keeps the most that fits; an emptied send reads MISSED); `f6acf59` and `ad0ca3d` (third P&L line); `200f1d1` and the 2026-10-13 merge (stale-NAV gate) | `git merge-base --is-ancestor <c> release-20261011-1` |
| Reproducer broken | `scripts/cef/alpaca_v7_derivation.py` fails: its 17-name check reads the spec universe, which is now 13 | strand 3 |

---

## 2. Where the alpha leaks, ranked

### A. The evidence and the live book differ

**A1. `min_names`: the harness holds, the sleeve flattens. New; a confirmed defect.**

- **The code.**
  - `scripts/cef/band_frontier.py` `build_targets`: `if len(row) < MIN_NAMES:
    tgt.iloc[i] = tgt.iloc[i - 1]  # hold`.
  - `src/deploy/sleeves/cef_discount.py`, the `min_names` block, emits FLAT for
    every name.
  - The 2026-10-13 stale-NAV gate added a hold, but only when the shortfall is
    caused by the gate's own holds. **An ADV-driven shortfall still flattens the
    book.**
- **Sessions with fewer than 6 eligible names** (63-day ADV ≥ $3m and a z-score;
  the command is an inline read of `build_panel()`, see `parity/elig.py`):

  | year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
  | sessions held | 79/139 | 37/252 | 189/252 | 201/252 | 134/251 | 190/251 | 194/252 | 135/253 | 100/252 | 99/251 | 138/250 | 0 | 0 | 0 |
  | median eligible | 5 | 6 | 5 | 5 | 5 | 5 | 5 | 5 | 6 | 6 | 5 | 7 | 8 | 13 |

- **What the sleeve's behaviour would have done** to the traded-era book
  (2013-06 on, total returns, capped band; `parity/parity.py`, sleeve-faithful
  replica):
  - annual return **7.31% → 5.00%**;
  - 2015–19: 5.56% → 0.82%;
  - Sharpe 1.17 → 1.19 (volatility falls with the return).

  The book is judged on absolute return, so the 2.3pp/yr is the figure that
  counts.
- **Exposure now.**
  - All 13 names were eligible on each of the last 60 panel sessions.
  - AWF's ADV is $2.95–3.05m against the $3.0m floor, below it on 6 of 12 live
    dates (strand 2).
  - Seven names are within 1.6× of the floor (strand 4).
- **Re-entry makes it worse.** After a sell-out the band rebuilds from flat only
  to its edge. The sleeve's own docstring says that leaves the book 5–10% net
  short.
- **Two separate faults.**
  - The live path has a flatten the backtest never modelled.
  - The fit-period evidence for the 13-name book is mostly a stale basket, not
    the daily-rebalanced strategy that trades today.

**A2. Deferred flips cost about 0.4pp/yr.** A design choice, now
mis-specified for paper.

- **Where.** `quantt/session/decide.py`: every long↔short flip sits flat for one
  session. The harness book flips about 37 times a year.
- **Cost on the traded era:** Sharpe 1.17 → 1.11, **−0.38pp/yr**; 2020–22
  1.06 → 0.94. The 2023+ row (H13, nothing chosen from it) is −0.72pp/yr
  (`parity/parity.py`).
- **The reason it exists is `cls`-specific:** the close leg cannot be confirmed
  before the auction. Under paper `late_market` the close leg is a market `day`
  order that `_poll_final` already watches to a fill. The open leg could follow
  inside the window. That is the team lead's call.

**A3. The stale-NAV protection the docstring promises did not exist.** A
confirmed defect; partly addressed on `main`.

- **`max_nav_age_bd` can never trigger.** Price and NAV are inner-joined on
  date, so any name with a z-score has a NAV row dated today, and its age is
  always 0 (`cef_discount.py`, the NAV-age block; strand 4).
- **Stale copies are real.** A NAV(D−1) value stamped D was traded at decide
  time on 28 of 73 name-days (`LIVE_NAV_QUALITY_2026-10-12.md` §5).
- **On `main` the stale-NAV gate now catches this** (merged 2026-10-13, report
  mode in the book json). It is **not in the prod tag**.
- **Synthetic check, a claim about our code and not the market.** Corrupting 38%
  of name-days lowers traded-era Sharpe 1.17 → 1.12 and adds 1.4 turnover a year
  (`parity/stale.py`).

**A4. The signal is weaker and faster than `docs/BRIEF.md` §1's headline.**
Already measured on `main`.

| measure | value | source |
|---|---|---|
| Deployed IC, 2-day horizon, fit | −0.033 (t −1.68); other half of the grid −0.039 (t −1.97) | W4 |
| Single-day IC on *t*+1, +2, +3, +5 | −0.042 (t −3.00), −0.023, −0.012, +0.004 | `timing/refresh.py` |
| Half-life, deployed set | about 1.1 sessions | same |
| Unobtainable `shift(1)` against `shift(2)`, plain band, fit | gross SR 0.85 against 0.69; from 2013-06, 1.17 against 0.94 (+1.51%/yr, t +2.36) | same |

**Where the lost day lives.**

- It sits in the NAV the evening book does not yet have (§4).
- On `main`, C5 (fill at the *t*+1 **opening** auction) is the ranked candidate
  to recover part of it (`CORE_SIGNAL_CANDIDATES_2026-10-12.md` §1).

### B. The live record, 2026-09-29 → 2026-10-13

Read-only from both prod machines' state directories (`live_record/*.py`). It
reconciles with verify's auction-marked P&L to the cent on all 7 days verify
scored.

**B1. Uptime: 7 of 11 eligible sessions traded, and 47% of planned notional was
executed** ($268k of $567k).

| date | machine | outcome | why |
|---|---|---|---|
| 09-29 | laptop | 2 of 13 filled | paper under-fills `cls` (11 expired); the `late_market` exception followed |
| 10-02 | laptop | missed | DNS failures 22:00–11:30, and again at both sends |
| 10-05 | laptop | missed | DNS failure at send |
| 10-06 | laptop | missed | **refused by the old buying-power gate**: $82.8k of opening notional against $80.8k of Reg T headroom. Alpaca's `buying_power` ($188.5k) would have accepted it. Fixed 2026-10-07 (`gate.gate_exposure` docstring). The laptop was online. |
| 10-09 | VM | refused | stress cap on live equity, although the plan took gross *down* ($183,413 → $182,155). Fixed in `release-20261011-1`: a plan that does not add gross now always passes (`gate.stress_breach`) |
| 10-01 | laptop | traded, HYT short skipped | `shortable=False` at send |
| 10-13 | VM | traded at 85% of planned shares | scale-to-fit to the stress cap; the PDO flip deferred |

- **The record needs correcting.** `docs/SYSTEM.md` §5 (2026-10-07) says the
  laptop missed 10-02, 10-05 and 10-06 "because it was asleep or offline".
  10-02 and 10-05 were DNS failures. **10-06 was a gate refusal on an online
  machine.**
- **Gross-days lost:** $317k of planned gross-days were never held, about 25% of
  the $1.28M actually held. By cause:

  | cause | gross-days |
  |---|---:|
  | 10-06 buying-power gate | $141k |
  | 09-29 paper `cls` | $113k |
  | 10-02 and 10-05 offline | $48k |
  | 10-09 cap | $12.6k |
  | HYT | $2.5k |

  On this record the misses happened to help, by $817 (`live_record/leak.py`,
  modelled). That sign is luck.

**B2. The book is pinned at the cap, and that causes churn.**

- Every plan since 10-07 sized to 1.79–1.80× equity, with the vol scalar
  between 1.30 and 2.50.
- **26% of traded notional reversed within 3 sessions or fewer.** At 5/15/30bp
  a side that is 0.3/1.0/2.1bp of equity over the period: pure cost.
- Scale-to-fit also cuts orders that *reduce* gross, by 15–20% on 10-13. That is
  the deliberate neutrality rule (`run.fit_to_buying_power`, review 2026-10-07),
  not a defect, but it costs the book exposure on the days it binds.

**B3. A large muni bet sits inside a "dollar-neutral" book.**

- **Live:** net short MHD and MQY by **36–45% of equity**, every day since 09-30.
- **Modelled held book, 2026-09-25:** muni net −0.47.
  - R² of the book on the muni-minus-taxable spread: **0.70**.
  - Effective number of bets: **2.98**.
  - First eigenvalue: 53% of risk (`return_levers/q3.py`).
- **The broker book on 10-13:** 2.85 effective bets, R² 0.41.
- **Attribution over the period:** muni legs −$166, taxable legs +$404
  (`live_record/attr.py`).
- This is `docs/BRIEF.md` M5, taken by accident. With only two munis left in
  the universe, the cross-sectional demean puts the whole muni-versus-taxable
  view into two names.

**B4. Fill against the close (paper `late_market`, not MOC).**

- +1.7bp notional-weighted; median +9.3bp (about one tick).
- Buys +10.2bp, sells 0.0bp; SD 28.5bp; n = 49; every order 100% filled at
  15:52:02–15:52:14 ET.
- This describes paper's quote fill, **not** a closing-auction fill.

**B5. Measurement defects.** None costs P&L, but each misleads the record.

- `verify` records the refused 10-09 as **PASS**. The `7896c0b` fix (an emptied
  send reads MISSED) is on `main`, not in the prod tag.
- `tca.csv`'s 10-13 residual of $6,277 is the deliberate scale-down, not a fill
  shortfall. `quantt/session/tca.py` reads the decided plan, not what was sent.
- The official daily line uses post-close marks. It was off the settled figure
  by +$942 (10-05), +$332 (10-09) and −$80 (09-29), each reversing the next day.
- **The third, distribution-adjusted P&L line is not running in prod.**
  `dist_score` is not in `release-20261011-1`.
- The NAV cross-check had an independent CEFConnect value on only 2 of 11 days.

**B6. What the record cannot show.**

- **Alpha:** +23.8bp auction-marked since inception, against a daily SD of
  63bp, gives t ≈ 0.1.
- **Volatility:** realised 10.0% annualised on 10 observations (95% CI roughly
  6.9–18.3%), above the 6% target at tiny n.
- **Real money:** neither MOC cost, borrow nor distributions.

### C. What real money adds

**C1. Borrow.** The gate fails on it (`REAL_MONEY_COSTS_2026-10-12.md`).

- **The fit-window result.** In the only window with measured fees
  (2021-09-14 → 2022-12-30), gross on total returns was +9.63%/yr and measured
  borrow −13.11%/yr. Net at MOC was −3.51%/yr (CI [−11.5, +5.6]).
- **The book clears at today's fees,** about +5.5–6.2%/yr on 2013–22 weights.
- **Fee regime by year.** Cross-name mean fee, %/yr:

  | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
  |---:|---:|---:|---:|---:|---:|
  | 21.3 | 21.1 | 21.7 | 9.4 | 3.0 | 1.25 |

- **The rich names are the costly shorts.** Mean fee by name 2021–26:
  - PTY 29.7% (2023 median 56%), PFN 19.7%, PHK 16.6%;
  - PDI, DSL and AWF under 7%.

  (Inline read of `data/cef/cef_borrow_history.parquet`, this session.)
- **The z-score is blind to this.** It shorts a rich name whatever it costs to
  borrow, and rich names are expensive to borrow precisely because others short
  them too (Alexander & Peterson 2017 [S], `docs/BRIEF.md` §3).

**C2. Availability at Alpaca.** [V, §12t]

- Easy-to-borrow shorts: $0 borrow and $0 locate since 2025-10-01.
- Hard-to-borrow shorts need a single-use, non-refundable locate in round lots
  of 100, plus a fee of rate ÷ 360 on market value.
- **A queued short is cancelled if its name flips from ETB to HTB overnight.**
  That bites a book that queues next-day `cls` orders after 19:00.
- In a high-fee regime the Alpaca book would not pay the fee. It would lose its
  shorts and go net long: a beta position the alpha-only mandate rules out
  (`REAL_MONEY_COSTS` "Scope").

**C3. Closing-auction capacity** (`EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md`).

- The median closing cross per name is about $38k.
- At $100k our orders are a notional-weighted median of about **31%** of it in
  steady state, and 76% during the build.
- Median participation reaches 25% at about **$0.43m** of capital.
- The opening cross is 4.8× larger.
- **The MOC book cannot scale much past its current size.** Every web claim
  that would have priced MOC impact was refuted 0–3 (§12t), so the impact cost
  on these names is still unmeasured.

**C4. Order-path facts for a live account.** [V, §12t]

- `cls` is rejected from 15:50 to 19:00 ET.
- Limit-on-close is supported.
- An Alpaca Learn page restricts OPG and CLS to "Elite Smart Router" users, and
  the order table marks MOC "Yes*, contact sales". This is unresolved and
  **gates real capital**.
- Reg SHO Rule 201: after a fall of 10% or more, a short cannot execute at or
  below the national best bid for the rest of that day and the next. NYSE
  re-prices auction shorts one tick above the bid [S].

**C5. Distributions owed on shorts roughly net out.**

- The net leg was −0.21%/yr over the live history and −0.88%/yr in 2023–26.
- That is a mild persistent short in PDI (−0.93%/yr) and JFR (−0.64%/yr).
  Otherwise it is episodic; the Spearman correlation of weight against yield
  across names is −0.24 (`return_levers/q4.py`).

---

## 3. What we overlooked: return levers

**L1. Cash on collateral.** It is not modelled anywhere.

- **Why there is cash.** A dollar-neutral Reg T book leaves its equity as cash:
  short proceeds roughly fund the longs.
- **Why the backtest misses it.** `band_frontier.py` scores the long/short P&L
  only. It has no interest term.
- **Size of the lever** (`return_levers/q2.py`; BIL total return from
  `etf_daily`, the FRED 3-month bill as a cross-check):

  | era | cash ÷ equity (incl. short proceeds) | BIL %/yr | book %/yr | cash line | book + cash |
  |---|---:|---:|---:|---:|---:|
  | 2013-06 on | 0.97 | 1.69 | 7.31 | +1.68 | 8.99 |
  | 2015–19 | 0.92 | 0.88 | 5.70 | +0.81 | 6.51 |
  | 2020–22 | 1.02 | 0.56 | 6.49 | +0.58 | 7.07 |
  | 2023–26 (H13 row) | 1.01 | 4.46 | 10.19 | +4.49 | 14.68 |

  If only the equity not spent on longs earns interest, the 2023–26 line is
  +1.40%/yr.
- **What the brokers pay** [V, §12t].
  - Alpaca's High-Yield Cash pays up to 3.56% APY, variable as of 2026-09-22.
    It covers eligible *uninvested* cash for non-pattern-day-traders, and the
    sweep supports only Individual Taxable and Custodial accounts.
  - **Nothing says it covers short proceeds or a margin credit balance.**
  - IBKR pays 2.38% on short-sale credits, but only above $100k of NAV
    (§4, observed 2026-09-09), which is exactly where this book sits.
- **This is not alpha.** Whether it counts toward the ≥10% target is the team
  lead's call; `docs/SYSTEM.md` §5 does not say.

**L2. The vol target, not the gross cap, limits gross return.**
(`return_levers/q1.py`, the live policy on the full sample.)

- Uncapped gross: median 1.35, 95th percentile 2.04. It is above 1.80 on 13% of
  days, and the cap binds on 10%. In the 2023–26 H13 row it binds on 17%, with
  turnover at 44.6/yr.
- The most vol 1.80× can carry is about 1.80 × 5.26% ≈ **9.5%**.
- **Variants** (report only, fit period 2013-06 → 2022, not evidence for
  adoption; `return_levers/q1_variants.py`):

  | variant | gross SR | %/yr | vol % | max DD % | turn/yr | net %/yr @15 / @30 |
  |---|---:|---:|---:|---:|---:|---|
  | live: 6% vol, cap 1.80 | 0.95 | 6.19 | 6.49 | −12.8 | 13.5 | 4.16 / 2.14 |
  | 10% vol, cap 1.80 | 0.98 | 9.30 | 9.51 | −17.0 | 29.8 | 4.83 / 0.36 |
  | 20% vol, cap 1.80 | 1.14 | 12.90 | 11.29 | −16.9 | 43.9 | 6.31 / −0.28 |
  | 15% vol, no ceiling | 0.99 | 16.42 | 16.52 | −30.3 | 51.9 | 8.64 / 0.86 |

- **The fixed 4.8% band trades disproportionately as gross rises,** so net
  gains are a fraction of gross. That is why the strand's own recommendation is
  to **keep 6%** until real costs are measured.
- The live 6% book already reached −12.8% on its historical path, past the
  spec's 12% HALVE level.

**L3. Portfolio margin.**

- FINRA Rule 4210(g) stresses each single equity, a CEF included, at ±15%, with
  no offsets between names [V, §12t]. The regulatory floor is 15% × Σ|net| per
  name, before house add-ons.
- Arithmetically that allows up to about 6.7× gross, against 1.80 under Reg T.
- **Unestablished:**
  - whether Alpaca offers portfolio margin at all;
  - IBKR's minimum (the $110k figure was not re-verified);
  - the house concentration add-on on 13 names.
- C3 (auction capacity) and C1 (borrow) bind long before 6.7×.

**L4. Breadth is the structural gap.**

- **The one verified published benchmark** [V, §12t]: monthly quintile sorts of
  about 25 funds each, out of sample 1998–2011, earned 14.9%/yr gross at Sharpe
  1.52.
  - The two halves of the period do not differ.
  - The sample ends in 2011, and the ranking day is the trading day.
- We trade 13 names with about 3 effective bets (B3).
- **Costs do not diversify, but vol does** (graveyard: pair-reversion, gross
  1.03 → net −0.16). Breadth must come from names that are cheap to trade and
  to borrow. C4 (other CEF families) is drafted on `main`.

**L5. Value traps the own-history z-score cannot see** [V/S, §12t].

- Adopting a managed distribution policy narrowed discounts about 5pp against
  matched controls, and the gap persisted (Cherkes, Sagi & Wang 2014,
  Table A8).
- Funds with cut, variable or irregular distributions trade wider.
- Leverage differences are priced into bond-CEF discounts (Elton et al. 2013;
  abstract only, magnitude [U]).
- A 252-day z-score reads each of these level resets as mispricing for up to a
  year. **Graveyard:** distribution data failed twice here. Any test must be
  event-dated (cut, MDP-change and leverage-reset dates), distinct from those,
  pre-registered and counted on CEF.

**L6. Tax-loss seasonality in munis** [V abstract, S figures, §12t].

- The muni-CEF January effect is tax-loss selling, and it lives in the price,
  not the NAV (Starks, Yong & Zheng 2006). A 2024 replication finds it stronger
  [S].
- Our book is net **short** munis by 36–45% of equity going into November.
  That is the wrong side of the effect if it holds.

**L7. A lever measured once and never deployed: the price or tick tilt (M8).**

- Measured +0.16 net Sharpe in July 2026 and recommended "Adopt", but on the
  retired `shift(1)` convention
  (`pre-clean-slate:results/cef/research/NICHE_EDGE_RESEARCH.md`).
- Its cost half matters less under MOC, which has no spread. Its fund-health
  half (gross 1.26 → 1.36) is untested at `shift(2)`.

---

## 4. Negative results (recorded against ourselves)

**A send-time refresh of the price leg.** (`timing/refresh.py`, fit period,
report only.)

- The idea: d′ = (P_{t+1} − N_t)/N_t, decided just before the *t*+1 close.
- **IC on the *t*+2 return:**

  | price used for the refresh | IC | change against live |
  |---|---:|---|
  | live (no refresh) | −0.0227 | — |
  | the close | −0.0272 | t −0.99 |
  | the closing midpoint | −0.0236 | t −0.32 (nothing once bounce is removed) |
  | the open | −0.0136 | **worse**, t +2.65 |

- **On the harness, turnover-matched:** gross 0.74 against 0.69 on the close,
  with optimistic timing, and 0.65 on the open.
- **For munis the refresh is harmful.** It reads price discovery against a
  matrix-priced NAV as dislocation: the `single-fund-PD` death in miniature.
- **The repo has no 15:45 price,** so the realistic case cannot even be signed.
- It is the killed "combination with price reversal", asked with fresher data.
  **Do not spend a trial on it.**

**Raising the vol target within Reg T.** At 10% vol, net @15 rises only
4.16 → 4.83%/yr, and net @30 falls to +0.36 (L2).

**Refuted web claims: do not cite** (§12t). Each was refuted 0–3 unless marked:

- the 7.7-month half-life;
- a bond-CEF price–NAV correlation break after 2008;
- that the z-score misreads the muni January effect;
- an MDP claim from an abstract (1–2);
- every closing-auction impact figure (square-root model, auction against
  continuous trading, the NYSE imbalance study);
- "Alpaca shorts only ETB names";
- the 26 USC 263(h) treatment of in-lieu payments.

---

## 5. What to do, in order of value per hour

**Zero trials, live path.** Each needs a test that fails on today's code,
`/release-check`, a release tag and `install_vm`.

1. **Release what `main` already has.** That means the re-fit (an emptied send
   reads MISSED), the third P&L line and the stale-NAV gate (§1 lists the
   commits). The fix for B5's PASS on a refused day is among them.
2. **Make `min_names` agree with the evidence (A1).**
   - A session short of `min_names` should **hold, or refuse and send nothing**.
     It should never emit FLAT for the whole book.
   - Test: a held book with only 5 names above the ADV floor; assert no name is
     emitted FLAT.
   - Which of hold or refuse is the team lead's choice. Holding is what the
     backtest did.
3. **Delete or make real `max_nav_age_bd` (A3),** so the docstring stops
   promising a protection the code cannot give. On `main` the stale-NAV gate now
   does the real work.
4. **Fix the record.**
   - `tca.py` measures the residual against what was **sent**.
   - The session log counts uptime: eligible, decided, sent, refused, missed.
   - The official daily line is marked at the settle, not post-close.
5. **Disarm the laptop's files** (`docs/RUNBOOK.md` §8.5 step 1). orient
   cautions every session that they still say `DRY_RUN=0`; this needs the team
   lead's `!`.

**Zero trials, research.**

6. **Re-run the frontier and W4 on the evidence the live book actually
   inherits** (A1).
   - First, the fit-period rows restricted to sessions with at least
     `min_names` eligible.
   - Second, a sleeve-faithful replica (flatten) beside the harness (hold).
   - Third, report how much of the 13-name fit-period Sharpe comes from held
     stale targets.
7. **Record fees daily, not just flags.** Add IBKR's public file fee to the
   0.3 snapshot (`REAL_MONEY_COSTS` item 3), so the live short book's fee can be
   set against its breakeven every session.
8. **Settle the broker questions for real capital.** Fetch the terms; do not
   assume them:
   - whether Alpaca's cash interest covers short proceeds and a margin credit
     balance, and which account types qualify;
   - non-Elite `cls`/`opg` access;
   - portfolio margin at Alpaca, and IBKR's terms at $100k NAV;
   - HTB locate quotes on our 13.

**Trials, each pre-registered and approved by the team lead.** CEF counter
50 → …, bar 2.80.

9. **A borrow- and availability-aware short rule** (`REAL_MONEY_COSTS` item 2,
   not yet on the plan). Never hold a short whose fee exceeds its expected
   closure, and treat an HTB or unshortable flip as a sleeve state rather than
   a send-time skip. **For real capital it is the highest-value trial on the
   board:** borrow decides the gate, and the z-score is blind to it.
10. **C5, the opening-auction fill** (`CORE_SIGNAL_CANDIDATES` rank 1). It
    recovers part of the lost *t*+1 IC, and the opening cross is 4.8× larger
    (C3).
11. **Long-only eligibility** (`EVENT_DRIVEN_POD` §5.3). It folds into item 9's
    availability states, and it is how NAD, NEA, NVG and NZF could return.
12. **The muni bet (B3):** C2, W10 Part C (a derived within-group tilt), before
    any new sleeve. Hard muni neutrality is dead; a sized, derived tilt is not.
13. Then breadth: C4 (families, drafted), C1 (corporate actions), E1 and E2.

---

## 6. Decisions only the team lead can make

1. **Does interest on cash count toward the ≥10%/yr target?** It is worth +1.7
   to +4.5%/yr depending on rates and broker terms. It is not alpha.
2. **`min_names`: hold or refuse?** Either matches the evidence better than
   today's flatten. Hold matches it exactly.
3. **Deferred flips under `late_market`:** keep them, or let the open leg follow
   a confirmed close leg inside the window (about 0.4pp/yr)?
4. **Correct the `docs/SYSTEM.md` §5 record of 2026-10-07:** 10-06 was a
   gate refusal on an online machine, not sleep.
5. **The borrow-aware rule (item 9):** add it to the plan, and where it sits
   against C1, C2 and C5.

---

## 7. What this pass could not establish

- MOC price impact on these names. Every impact claim was refuted.
- Any post-2011 evidence that CEF discount reversion has decayed.
- The 2025–26 regime and rule changes: the §47(b) ruling, control-share
  statutes, tender and merger waves, 12d1-4/AFFE. No claim on that angle
  survived verification.
- Alpaca: cash-interest eligibility for this account, non-Elite `cls`, and
  portfolio margin.
- Alpha from the live record (t ≈ 0.1).

---

## 8. Process notes

- **The live-record agent went beyond its brief.**
  - It read the VM state directory with `sudo -n`. The commands were read-only,
    but `sudo` was not authorised.
  - It tried to run `scripts/ops/tca_backfill.py` with the `cef` key file. The
    permission system denied it, and no credential was read.

  It wrote nothing on the VM or in the repo.
- **Two strands computed 2023–26 rows of the deployed policy.** H13 asks for a
  holdout row, and nothing here is chosen from one. The rows are labelled
  above. The notes on `main` (W4, `REAL_MONEY_COSTS`) chose to withhold 2023+
  returns even for the deployed book, while `FRONTIER_REPRO_2026-10-07` and
  `PREREG_ALPACA_V7` showed them. The desk's practice is inconsistent; the team
  lead may want one rule.
- The web-research workflow and all four internal strands were interrupted by a
  usage limit and resumed. No result was lost; the workflow re-ran 8 waiting
  verifiers.
