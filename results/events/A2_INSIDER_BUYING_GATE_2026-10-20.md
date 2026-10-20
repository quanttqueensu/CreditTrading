# A2: insider open-market purchases in CEFs and BDCs, the zero-trial gate (2026-10-20)

**What this is.** Path A2 of the team lead's 2026-10-19 request ("zero-trial
checks on new event paths"). The question is whether a director, officer or
adviser buying a fund's shares (Form 4, code P) carries information beyond the
discount z-score the book already trades. The idea is that insiders know the
marks (BDCs above all) or know a discount action is coming.

**Zero trials.** No counter moves: CEF stays 52 and EVENTS stays 2. No strategy
P&L was formed: there are no positions, no turnover and no harness. Section 4 is
an event study, the change after a purchase minus the change on fund-days with
the same z-score in the same month.

**Holdouts.**
- **Time.** No quarterly ZIP after 2022Q4 was read. Every panel and CRSP frame
  is cut before 2023-01-01, before any window is formed, and
  `assert_pre_holdout` checks every frame that reaches a statistic. The 2023+
  data are sealed and unseen.
- **The 27-name comparison set** (`cef_universe.csv` minus the spec universe
  and NAD, NEA, NVG, NZF) is counted only. `credit_panel()` drops it before any
  z exists, and `guard_untouched()` raises if one of its names reaches a
  statistic. The families panel holds no `cef_universe.csv` fund.

**Reproduce** (every input is a local cache; nothing opens a socket or reads an
env file):

```bash
python3 scripts/events/a2_insider_buying.py all \
  --edgar-cache "<worktree>/results/events/_cache_edgar"  [--edgar-cache ... repeatable] \
  --crsp-cache  "<worktree>/results/events/_cache_crsp"
python3 -m pytest scripts/events/tests/test_a2_insider_buying.py
```

The 2026-10-20 run used two caches:
- EDGAR: `.claude/worktrees/research-edgar/results/events/_cache_edgar`, which
  holds the 80 quarterly insider data sets fetched 2026-10-19. Only 68 were
  read. The run also searched seven other worktrees' EDGAR caches for
  submissions JSON.
- CRSP: `.claude/worktrees/research-ss-expansion/results/events/_cache_crsp`
  (`dsenames`; `dsf` cut at `date < 2023-01-01`, pulled 2026-10-19).

**No bulk fetch was needed:** the insider data sets were already cached. On a
clone with no cache, the team lead's commands are in the module docstring:
`fetch` (130 EDGAR GETs, credentialed) and `pull-crsp` (R2).

**Data dates.**

| source | coverage used |
|---|---|
| SEC Insider Transactions Data Sets | 2006Q1 → 2022Q4, by filing date; last filing date 2022-12-30 |
| EDGAR master indexes (fund set; BDC 10-Q/10-K dates) | 2008Q1 → 2022Q4 |
| SEC ticker file (panel ticker → CIK) | as cached by `research-edgar` (2026-10-12 run) |
| `data/cef/` credit panel (17 touched names) | to 2022-12-30 (panel runs to 2026-10-15; cut) |
| `data/cef_families/` (164 included funds) | to 2022-12-30 (panel runs to 2026-10-09; cut) |
| CRSP `dsf` (BDCs) | to 2022-12-30 |
| submissions JSON (Form 4 acceptance times) | 55 of 208 panel CIKs cached; filings 1998–2026 (timestamps only, no returns) |

**Labels.** Every figure below was produced by the script above on 2026-10-20
and is [V] as of that run. The aggregates are in `results/events/a2_insider/`.

---

## 0. The answer

**Verdict: CLOSE at zero trials.** Gate G2 fails: insider buying adds nothing
detectable beyond the discount z-score. G4 (cost) also fails. G1 (breadth) and
G3 (the sales placebo) pass. The team lead decides.

- **Insiders do buy wide discounts. That much is the book's own signal.**
  - At the decision date, purchase events have mean z −0.35. All fund-days
    have +0.03.
  - 34.6% of purchase events have z below −1, against 23.1% of fund-days.
  - "Below NAV" is not a signal in CEFs: 86.6% of purchases were below NAV,
    but so were 80.2% of insider *sales*.
- **Matched on z (same group, month and z bin), nothing is left.** Over the 21
  sessions after the fill:
  - discount narrows by **+0.15pp (t 1.09)**;
  - NAV return **−8bp (t −0.51)**;
  - price return **+9.5bp (t 0.44)**;
  - **n = 1,179 events in 198 months.**

  The second method (same fund, year and z bin) gives the opposite sign:
  −0.31pp (t −1.11). A cell fixed-effects regression, an independent
  estimator, gives +0.16pp (t 1.19) and +11bp (t 0.53).
- **The negative control scores as well as the treatment (H12).**
  - Credit, preferred and multi-asset funds are where the "confidence in the
    marks" channel should live. There the price excess is −37.5bp (t −1.57).
  - Equity families hold exchange-priced assets, so that channel cannot run
    there. They give +36.7bp (t 1.11).
  - The 17 touched credit names give −0.03pp (t −0.10).
- **Cost.** The price excess at 21 sessions is +9.5bp. Net per round trip
  (2 units of turnover):
  - −0.5bp at 5bp per unit;
  - −20.5bp at 15bp;
  - −50.5bp at 30bp.

  It is negative across the whole grid. Against the brief's 32.6bp breakeven
  per unit (65.2bp a round trip [S], not re-measured), it is further below.
- **BDCs (price only; there is no daily BDC NAV):** +99.8bp at 21 sessions
  (t 3.13). That is not an insider effect:
  - insider *sales* show +91.2bp (t 1.40): the same sign at 91% of the size,
    which fails G3's criterion;
  - 38% of BDC purchase events fall within 10 days of the fund's own 10-Q or
    10-K, against 12% of control days;
  - matched on that timing (report-only), the excess falls from +74bp
    (t 2.46) to +24bp (t 0.63).

  It is the insider trading window that opens after the quarterly report. The
  declared G5 rule flags a BDC NAV fetch. **The recommendation is not to fetch
  for A2.**
- **Counts, 2006–22, before 2023:**
  - **Fund-events** (first purchase after a 90-day gap): CEFs 4,665 (216–413
    a year), BDCs 1,508 (33–129 a year).
  - **Cluster buys** (two or more owners within 30 days): CEF 1,370, BDC 989.
  - **On the 17 touched credit names: 122 events, 1–14 a year.** That is too
    few to tilt the 13-name book.

## 1. Who is on the other side, and the graveyard

**The intended loser** is whoever sells after the Form 4 is public. Typically
that is the retail income holder selling into the discount, M1's loser
(`docs/BRIEF.md` §2). If the information story held, the reason it would
persist is the wrapper: a fixed share count and no AP, so no one is obliged to
close the gap.

**Two structural reasons it might not be information:**
- **Section 30(h)** puts CEF directors, officers, advisory board members, the
  adviser and its affiliated persons under "the same duties and liabilities"
  as section 16. That includes §16(b) disgorgement of short-swing profit
  "within any period of less than six months" (`docs/REFERENCES.md` §12ax).
  - An insider's purchase therefore expresses a view of six months or more.
    The book trades days to weeks.
- **The purchases are small.** The median qualifying purchase is $9,989 (CEF)
  and $8,920 (BDC), and about half are under $10,000 (§3). That looks like
  alignment buying, not a bet.

**Graveyard check (`/graveyard`, `docs/RESEARCH_STATE.md`).**
- **The core book's own signal in disguise.** This was the main risk, and it
  is what the data show: insiders lean towards low z (§4.1), and the
  incremental contrast is nil (§4.2).
  - An "insider tilt" on the book would therefore sit in the dead family
    "sizing up on |z| / on dislocation". Every threshold above zero lowered
    Sharpe there.
- **Pre-positioning on activist 13Ds** was rejected in
  `results/cef/SCALING_RESEARCH_2026-10-08.md`. It is excluded by
  construction: ten-percent-only filers (Saba, Bulldog, Karpus) are dropped,
  19,334 owner-rows.
- **Stale-price artefact (six of thirteen deaths).** The input is a dated
  filing, not price minus a mark. But the outcome can be contaminated.
  - In credit-like funds the NAV underperforms after purchases: −40bp,
    t −2.67, one stratum among many.
  - That is what an insider buying after a sell-off, while the NAV is still
    stale-high, would produce.
  - The price excess is also negative there, so there is nothing to trade
    either way.
- **"A control group scoring as well as the treatment" (the second pattern).**
  It applies: the equity families beat the credit-like funds (§4.4).
- **The literature points the same way.** The one peer-reviewed CEF study
  found is Andriosopoulos, Steliaros and Thomas (2015). On UK CEF director
  purchases they find a positive price response, and "most of the initial
  price responses and trading volumes dissipate over the following 15 days". They read it as retail attention, not
  information. A Missouri dissertation reportedly reads US CEF insider trading
  as discount-reversion trading; it is [S], and the repository refused the
  request.

## 2. Rules, fixed before any outcome

All rules are in the module docstring (`scripts/events/a2_insider_buying.py`),
written before the mechanism part first ran.

**Inherited unchanged** from the 2026-10-19 census
(`scripts/events/ssx/ssx_ins_insider_census.py` on the unmerged
`research-ss-expansion` branch; ported, not re-chosen):
- **Purchase:** original Form 4, code P, acquired, shares > 0, price > 0,
  trade date within 365 days of filing, equity title.
- **Owner classes:** DO, adviser and other_person qualify. Ten-percent-only
  holders and other entities are excluded.
- **Fund-event:** the first qualifying filing after a 90-day gap. Variants:
  at least $10k per purchase, and at least two owners within 30 days.
- **Fund set:** the repo's CEF/BDC rule. BDC means it filed N-54A/C, or files
  10-K without N-CSR.

**New:**
- **Sales placebo:** code S through the same pipeline.
- **Sweep flag:** the triggering owner filed in three or more funds within
  ±5 days.
- **Timing:** decide at t, the first session on or after the filing date; fill
  at the close of t+1; earn from there (`shift(2)`). The "late" row decides at
  t+1.
- **Horizons:** 5, 21 and 63 sessions; **primary 21**.
- **z:** the sleeve's own formula, with the window read from the spec. Bins
  are fixed, not estimated.
- **Controls:** fund-days with no qualifying P or S filing from 63 sessions
  before to 66 sessions after.
- **Method 1:** cell = (group, year-month, z bin). **Method 2:** cell = (fund,
  year, z bin).
- **Errors:** clustered by year-month.
- **The gate:** §6.

**Census cross-check.** This code path reproduces the 2026-10-19 census exactly:

| | 2010 | 2013 | 2016 | 2020 | 2022 |
|---|---:|---:|---:|---:|---:|
| CEF events | 295 | 348 | 264 | 261 | 250 (census 260) |
| BDC events | 56 | 77 (census 79) | 114 (census 115) | 113 | 124 (census 125) |

The small gaps come from the fund set: it uses indexes only to 2022Q4 here,
against 2025Q4 there.

## 3. Counts, 2006–2022

**All Form 4 code-P purchases on fund issuers** (`a2_qualifying_diag.json`).
- 52,716 transactions; 50,245 on original Form 4s; 39,095 qualifying.
- Owner-rows on equity titles:

  | owner class | rows | used? |
  |---|---:|---|
  | DO | 32,158 | yes |
  | ten-percent-only | 19,334 | excluded |
  | adviser | 6,269 | yes |
  | other_person | 4,341 | yes |
  | other_entity | 657 | excluded |

- 1,059 rows were dropped for a trade date outside the window.

**By year** (`a2_counts_by_year_kind.csv`):
- **trans:** qualifying purchase transactions;
- **events:** fund-events;
- **≥$10k / 2+ own:** the declared variants;
- **sweep:** the triggering owner bought three or more funds within ±5 days;
- **listed:** the symbol as filed links to CRSP at the event date;
- **sales:** sale events (the placebo).

| year | CEF trans | CEF funds | CEF events | ≥$10k | 2+ own | sweep | listed | sales | BDC trans | BDC funds | BDC events | ≥$10k | 2+ own | listed | sales |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2006 | 1,340 | 162 | 254 | 171 | 80 | 61 | 248 | 77 | 228 | 19 | 33 | 24 | 18 | 31 | 17 |
| 2007 | 1,630 | 283 | 413 | 272 | 146 | 180 | 404 | 79 | 808 | 31 | 66 | 54 | 44 | 60 | 18 |
| 2008 | 2,349 | 267 | 312 | 211 | 113 | 103 | 308 | 70 | 1,233 | 30 | 63 | 54 | 43 | 60 | 19 |
| 2009 | 1,241 | 157 | 211 | 124 | 60 | 63 | 206 | 96 | 630 | 28 | 49 | 33 | 32 | 41 | 16 |
| 2010 | 1,338 | 218 | 295 | 170 | 53 | 118 | 288 | 71 | 386 | 29 | 56 | 39 | 32 | 49 | 17 |
| 2011 | 892 | 200 | 273 | 173 | 85 | 118 | 262 | 51 | 549 | 40 | 75 | 60 | 48 | 71 | 16 |
| 2012 | 1,119 | 187 | 254 | 168 | 80 | 82 | 245 | 93 | 702 | 41 | 76 | 66 | 47 | 70 | 22 |
| 2013 | 1,340 | 239 | 348 | 259 | 127 | 109 | 341 | 76 | 862 | 47 | 77 | 66 | 48 | 65 | 19 |
| 2014 | 1,002 | 198 | 268 | 208 | 77 | 80 | 261 | 110 | 1,298 | 55 | 119 | 110 | 87 | 106 | 17 |
| 2015 | 3,812 | 208 | 304 | 249 | 92 | 68 | 287 | 95 | 1,373 | 62 | 129 | 113 | 89 | 111 | 15 |
| 2016 | 1,506 | 194 | 264 | 180 | 69 | 102 | 244 | 91 | 1,109 | 58 | 114 | 91 | 68 | 91 | 17 |
| 2017 | 766 | 175 | 249 | 163 | 59 | 62 | 223 | 117 | 816 | 54 | 109 | 94 | 80 | 85 | 17 |
| 2018 | 804 | 187 | 253 | 205 | 59 | 41 | 215 | 85 | 968 | 60 | 106 | 95 | 71 | 76 | 12 |
| 2019 | 716 | 204 | 240 | 157 | 65 | 87 | 212 | 91 | 640 | 54 | 98 | 88 | 60 | 73 | 12 |
| 2020 | 958 | 202 | 261 | 206 | 77 | 61 | 225 | 91 | 1,426 | 64 | 113 | 101 | 83 | 89 | 13 |
| 2021 | 876 | 162 | 216 | 161 | 66 | 58 | 164 | 92 | 1,358 | 58 | 101 | 87 | 59 | 66 | 12 |
| 2022 | 789 | 168 | 250 | 158 | 62 | 61 | 211 | 74 | 2,021 | 67 | 124 | 113 | 80 | 80 | 9 |
| **2006–22** | 22,478 | | **4,665** | 3,235 | **1,370** | 1,454 | 4,344 | 1,459 | 16,407 | | **1,508** | 1,288 | **989** | 1,224 | 268 |

**In our panels** (`a2_counts_our_sets_by_year.csv`; base rule, 2006–22):

| set | events | a year | ≥$10k | 2+ owners |
|---|---:|---|---:|---:|
| 17 touched credit names | 122 | 1–14 | 105 | 17 |
| 27 untouched credit names (**count only**) | 179 | 5–20 | 134 | 57 |
| families panel (164 funds) | 1,498 | 69–130 | 1,093 | 459 |
| fund set outside our panels | 4,389 | | | |

**Sizes** (`a2_sizes.csv`):

| | p10 | p50 | p90 | share under $10k |
|---|---:|---:|---:|---:|
| CEF, per qualifying purchase | $1,569 | $9,989 | $99,885 | 50.1% |
| BDC, per qualifying purchase | $420 | $8,920 | $157,080 | 52.3% |
| CEF, per fund-event (its 30-day set) | $2,250 | $20,000 | $223,736 | 30.8% |
| BDC, per fund-event | $5,436 | $65,949 | $1,045,270 | 16.0% |

**Cross-fund dependence.** 31% of CEF events (1,454 of 4,665) are sweeps: one
trustee buying across a fund complex within days. Independent bets are
therefore fewer than events.

## 4. The mechanism check (descriptive; no strategy P&L)

**The sample.** 1,247 purchase events have a finite z at the decision date
(`a2_mech_summary.json`):
- 115 on the 17 touched credit names (7 dropped: no row or no z);
- 1,132 on the families panel (119 dropped).

The sales placebo has 450 events. The control pool is 406,017 of 597,394
fund-days. The panel's last date used is 2022-12-30.

### 4.1 Is it the z-score in disguise? (`a2_mech_zdist.csv`)

| set | n | mean z | median z | z < −1 | z < −2 | z > +1 |
|---|---:|---:|---:|---:|---:|---:|
| all fund-days | 597,394 | +0.03 | −0.01 | 23.1% | 5.3% | 25.1% |
| purchase events | 1,247 | **−0.35** | −0.39 | **34.6%** | 10.7% | 18.7% |
| sales events | 450 | +0.09 | +0.06 | 22.7% | 5.3% | 23.8% |
| purchase events, touched credit | 115 | −0.37 | −0.54 | 40.0% | 10.4% | 20.0% |

**Insiders buy when the discount is wide against its own year, and sell when
it is not.**
- That is the z-score's own information, so the contrast below holds z fixed.
- "Bought below NAV" (86.6% of purchase events; median premium −10.2% at the
  trade) is not informative: 80.2% of sales were also below NAV.

### 4.2 The incremental contrast (`a2_mech_main.csv`)

Event minus control cell mean. Discount change in pp (+ is narrowing); NAV and
price total returns in bp. Windows run from the fill close, t+1. Errors are
clustered by month.

| sample | method | n | months | Δdisc 5 | Δdisc **21** | Δdisc 63 | NAV 21 | price 5 | price **21** | price 63 | late Δdisc 21 | late price 21 |
|---|---|---:|---:|---|---|---|---|---|---|---|---|---|
| **purchases** | m1 group×month×z | 1,179 | 198 | +0.14 (1.43) | **+0.15 (1.09)** | +0.32 (1.68) | −8 (−0.51) | +24 (1.22) | **+9 (0.44)** | +33 (1.31) | +0.14 (1.05) | +6 (0.28) |
| purchases | m2 fund×year×z | 563 | 172 | −0.02 (−0.12) | **−0.31 (−1.11)** | −0.07 (−0.19) | −43 (−0.98) | −9 (−0.23) | −63 (−1.10) | −2 (−0.02) | −0.27 (−1.09) | −52 (−0.99) |
| purchases ≥$10k | m1 | 831 | 190 | +0.16 (1.35) | +0.13 (0.89) | +0.34 (1.60) | −9 (−0.54) | +10 (0.61) | +13 (0.63) | +28 (0.97) | +0.12 (0.86) | +24 (0.92) |
| purchases, 2+ owners | m1 | 288 | 125 | +0.19 (0.87) | +0.37 (1.35) | +0.38 (0.86) | +6 (0.20) | +23 (0.79) | +57 (1.49) | +43 (0.78) | +0.06 (0.15) | +26 (0.69) |
| **sales placebo** | m1 | 428 | 169 | −0.04 (−0.31) | **−0.12 (−0.54)** | −0.17 (−0.54) | +35 (1.47) | +9 (0.44) | +31 (1.03) | −35 (−0.82) | −0.12 (−0.49) | +10 (0.36) |

Cells: mean (t). The full grid, with control means and the count of events
without a control cell, is in the CSV. **Method 2 loses 673 events that have
no same-fund, same-year, same-z control.** It is the weaker estimator, but it
is the declared second method, and its sign disagrees.

**Double-checked** (`a2_crosscheck.json`):
1. **A raw recomputation from the parquet files** reproduces the module's
   21-session discount change and price return to 1.6e-14pp and 7.8e-12bp.
   It uses 40 seeded random events, on each fund's own rows, with none of the
   frame code.
2. **A cell fixed-effects regression**, a different weighting of the same
   contrast, gives:
   - discount: **+0.162pp, t 1.19** (n 1,236 events);
   - price: **+11.3bp, t 0.53**;
   - NAV: −7.1bp, t −0.44;
   - sales placebo: −0.13pp, t −0.58.

   The two estimators agree.

### 4.3 When does it move? (`a2_mech_profile.csv`)

The discount change from the decision close t to t+k, as event minus cell
(method 1, purchases):

| k | −22 | −6 | −1 | +1 (fill) | +6 | +22 | +64 |
|---|---|---|---|---|---|---|---|
| excess, pp (t) | +0.04 (0.46) | −0.05 (−0.39) | −0.11 (−1.34) | −0.03 (−0.69) | +0.09 (0.89) | +0.11 (0.75) | +0.28 (1.44) |

Nothing is significant at any lag. The same-z control already explains the
run-up into the purchase. Nothing is lost between the decision and the fill.

### 4.4 Negative controls (H12) (`a2_mech_strata.csv`)

21 sessions, method 1. The marks channel predicts credit-like > equity, below
NAV > at/above NAV, and purchases > 0 > sales.

| stratum | n | Δdisc pp (t) | NAV bp (t) | price bp (t) |
|---|---:|---|---|---|
| credit-like (17 credit, preferred, multi-asset) | 432 | +0.03 (0.20) | **−40 (−2.67)** | **−38 (−1.57)** |
| of which the 17 touched credit names | 108 | −0.03 (−0.10) | −14 (−0.52) | −14 (−0.34) |
| **equity families (the control: exchange-priced NAV)** | 747 | +0.22 (1.07) | +10 (0.40) | **+37 (1.11)** |
| bought below NAV at the trade | 1,029 | +0.27 (1.97) | −5 (−0.28) | +24 (1.15) |
| bought at or above NAV | 150 | −0.65 (−1.34) | −33 (−0.80) | −94 (−1.76) |
| adviser involved | 56 | −0.03 (−0.06) | −122 (−1.80) | −82 (−1.00) |
| sweep (complex-wide trustee round) | 442 | +0.35 (2.02) | −19 (−0.74) | +21 (0.62) |
| sales placebo, sweep | 116 | +0.49 (1.56) | +47 (0.97) | +98 (1.64) |
| z(t) < −1 | 410 | +0.34 (1.36) | −34 (−1.19) | +2 (0.05) |

**Reading.**
- The control (equity) scores better than the treatment (credit-like), on
  price and on NAV.
- The one stratum near t 2, sweeps, has a sales twin of the same sign and
  larger size. It is the timing of trading windows across a fund complex, not
  information.
- Adviser purchases, the most informed owner class, are negative (n 56).

Eras, from the same CSV (Δdisc, pp (t)):

| era | Δdisc pp (t) |
|---|---|
| 2006–09 | +0.29 (0.68) |
| 2010–14 | +0.36 (1.61) |
| 2015–19 | −0.04 (−0.32) |
| 2020–22 | −0.03 (−0.11) |

Whatever there is, it has gone since 2015.

### 4.5 BDCs: price only (`a2_bdc_main.csv`, `a2_bdc_summary.json`)

BDCs publish NAV quarterly, so there is no daily discount and no z. The
contrast is the event minus same-month BDC-days with the same trailing
63-session return bin, on CRSP total returns.
- **Linking:** 1,224 of 1,508 purchase events link to a CRSP permno by the
  symbol as filed, and 1,043 are usable at 21 sessions.
- **Gap:** 13 linked permnos (113 purchase and 59 sale events) are absent from
  the cached extract. See §7.

| sample | method | n | months | price 5 | price **21** | price 63 | late 21 |
|---|---|---:|---:|---|---|---|---|
| BDC purchases | m1 month×return bin | 1,043 | 185 | +40 (2.86) | **+100 (3.13)** | +203 (2.94) | +77 (2.21) |
| BDC purchases | m2 fund×year×bin | 265 | 120 | −55 (−0.88) | −43 (−0.35) | +12 (0.06) | −33 (−0.27) |
| **BDC sales placebo** | m1 | 182 | 116 | −16 (−0.34) | **+91 (1.40)** | +72 (0.68) | +67 (0.94) |

By era (purchases, m1, 21 sessions):

| era | price bp (t) | n |
|---|---|---:|
| 2006–09 | +427 (2.60) | 135 |
| 2010–14 | +26 (0.63) | 302 |
| 2015–19 | +34 (1.08) | 394 |
| 2020–22 | +119 (1.71) | 212 |

The mean is carried by the crisis rebound. The median excess is +23bp.

**Report-only diagnostic, designed after seeing the rows above. It can neither
rescue nor kill** (`a2_bdc_filing_window_REPORT_ONLY.csv`; from 2008-04, when
the indexes start). Days since the BDC's own last 10-Q or 10-K:

| | ≤10 days | 11–30 | 31–60 | >60 |
|---|---:|---:|---:|---:|
| BDC purchase events (n 1,003) | **37.7%** | 30.1% | 22.1% | 10.1% |
| BDC sale events (n 164) | 31.7% | 29.9% | 28.0% | 10.4% |
| control BDC-days | 11.8% | 21.2% | 30.4% | 36.5% |

| contrast (21-session price, m1) | purchases | sales |
|---|---|---|
| m1 as above, 2008-04 on | +74bp (t 2.46) | +17bp (t 0.26) |
| m1 plus the filing-window bucket | **+24bp (t 0.63)** | −43bp (t −0.59) |

- Control days of their own within 10 days of a report earn +24bp over the
  month (t 0.77).
- **BDC insiders trade in the window after the quarterly report.** Matched on
  that window, the purchase excess is a third of its size and insignificant.
  The BDC row is a calendar artefact, not insider information.

## 5. Feasibility

**Long-only.** Buying the fund needs no borrow. A hedge would need a short
(CEFS or YYY for taxable, nothing clean for munis; MUB is not shortable at
Alpaca per the 2026-10-19 census [S]). Not built, because the gate closes.

**Timing.**
- **The deadline.** Form 4 is due before the end of the second business day
  after the trade (§16(a)(2)(C)). Forms 3, 4 and 5 transmitted by 22:00 ET are
  filed that day (Reg S-T 232.13(a)(4)). The book decides 22:00–01:00 ET
  (`docs/RUNNER.md`). So **a Form 4 dated f is available to the evening
  decision of f**, and `shift(2)` from that decision is executable.
- **The lag from trade to filing** (`a2_feasibility_lag.csv`):
  - 89.3% of qualifying purchases are filed within 2 business days;
    median 1, p90 3.
  - BDCs in 2010–14 are the outlier: 67% within 2 days, p90 22.
- **Acceptance times** (`a2_feasibility.json`; 6,610 Form 4s on the 55 panel
  CIKs with cached submissions JSON). The JSON value is either UTC or 4–5
  hours late (`results/events/edgar_acceptance_offsets/`), so two readings
  bound the true time:

  | reading | after the 16:00 close | after 22:00 |
  |---|---:|---:|
  | latest possible | 51% (3,370) | 357 |
  | earliest possible | 14% (905) | 2 |

  The JSON filing date equals the acceptance's ET date for 98.0%.
- **Late decisions cost nothing:** deciding a day late changes the 21-session
  discount excess from +0.15pp to +0.14pp (§4.2). There is nothing there to
  lose either way.

**Capacity** (pre-event 63-session ADV, panel events):

| measure | value |
|---|---|
| median ADV | $1.41m (p10 $0.31m, p90 $4.56m) |
| ADV ≥ $1m | 63.9% of events |
| ADV ≥ the spec's `min_adv_usd` ($3m, read through `scripts/cef/spec.py`) | 22.1% of events, 4–32 a year |
| a 10% clip of the spec's $100k capital | 0.7% of median ADV |

Capacity does not bind at this book size. The spec's liquidity floor does.

**Which counter.**
- **As a tweak to the live book** (a tilt on names with recent insider
  buying), it changes the CEF sleeve: a CEF trial at N = 53, bar
  √(2 ln 53) = 2.82. It would have 1–14 events a year on the touched names,
  which is D7 on its own.
- **As a standalone event sleeve** across the families and BDCs, it is an
  EVENTS trial, or a new-source ruling for the insider data sets as the
  2026-10-19 census proposed. The team lead's ruling either way.

**Neither is proposed:** the gate closes first.

## 6. The gate and the verdict (`a2_gate.json`)

Declared in the module docstring before any outcome.

| gate | rule | measured | result |
|---|---|---|---|
| G1 breadth | ≥ 50 usable events a year, 2010–22 mean | 72.5 | pass |
| **G2 incremental to z** | method-1 Δdisc(21) > 0 with t ≥ 2.0, and method 2 the same sign | +0.15pp, t 1.09; method 2 −0.31pp | **FAIL → kill** |
| G3 sales placebo | not the same sign at ≥ ½ the size | −0.12pp against +0.15pp | pass |
| G4 cost | price excess(21) ≥ 2 × 15bp | +9.5bp; net −0.5 / −20.5 / −50.5bp at 5 / 15 / 30bp | fail (D2) |
| G5 BDC (descriptive) | price excess(21) > 0, t ≥ 2.0 → recommend a BDC NAV fetch | +99.8bp, t 3.13 | rule fires; **but** the BDC sales placebo is +91bp, the same sign at 91%, which is G3's fail criterion; and §4.5's filing-window match removes it |

**Verdict: CLOSE at zero trials. A2 adds nothing beyond the discount z-score.**
The negative control (equity families) scores better than the treatment
(credit-like funds), and the BDC price effect is the post-report insider
trading window.
- **Recommended:** add a row to CLOSED. Do not fetch BDC NAVs for A2. Do not
  propose a CEF tilt or an EVENTS trial.
- **What would reopen it:** a reason to expect information in a subset that
  this note did not define in advance. Any such subset (adviser purchases
  only, n 56; cluster buys, +57bp at t 1.49) would be chosen after seeing
  these tables. It would need its own pre-registration and data from 2023 on
  (the sealed holdout), which nothing here has seen.

**Information per trial.** This cost no trial and closes the path. The
alternative was an EVENTS or CEF trial spent on a contrast whose fit-period t
is about 1.1.

## 7. Gaps (stated, not filled)

- **BDC NAVs.** Not fetched. The SEC Financial Statement Data Sets are cached
  for one quarter only (2022Q1). A BDC discount contrast would need them, and
  §4.5 says it is not worth it for A2.
- **13 BDC permnos are missing from the borrowed CRSP extract.** That is 113 of
  1,224 linked purchase events and 59 of 246 sale events. The team lead's
  `pull-crsp` would add them, so a fresh run's BDC rows can differ. The CEF
  verdict does not use them.
- **Acceptance times** are cached for 55 of 208 panel CIKs, in recent blocks
  only. The timing conclusion rests on Reg S-T and the decision window, not on
  this sample.
- **Symbol links.** Panel funds map to CIKs through today's SEC ticker file.
  All 17 touched names, all 27 untouched names and all 164 included family
  funds map. A fund whose CIK changed in a reorganisation would lose its
  earlier events; not measured.
- **Code P includes "private" purchases** (readme §6.2): rights-offering
  subscriptions or placements can sit inside it. The census's $10k-floor and
  2-owner variants are reported. A single-price filter was not applied to
  funds.
- **Independence.** 31% of CEF events are cross-fund sweeps. Month clustering
  covers common shocks within a month, not a trustee's sweep across fund
  families as a single bet.
- **The Missouri dissertation** (hdl 10355/4400) is [S]. Its page answered 403
  and 500 on 2026-10-20.

## 8. Files

- `scripts/events/a2_insider_buying.py`. Parts:
  - `fundset`, `extract`, `events`, `counts`, `mechanism` (with the
    cross-check), `bdc` (with the report-only window diagnostic),
    `feasibility`, `gate`, `all`;
  - **team lead only:** `fetch` (EDGAR) and `pull-crsp` (R2).
- `scripts/events/tests/test_a2_insider_buying.py`: synthetic frames and
  in-memory ZIPs only.
- **Tracked aggregates**, `results/events/a2_insider/`:
  - `a2_gate.json`, `a2_crosscheck.json`;
  - `a2_mech_*.csv` / `.json`;
  - `a2_bdc_*`;
  - `a2_counts_*.csv`, `a2_sizes.csv`;
  - `a2_feasibility*`;
  - `a2_fundset_summary.json`, `a2_extract_by_quarter.csv`,
    `a2_qualifying_diag.json`, `a2_panel_cik_map.csv`.
- **Gitignored** (`results/events/a2_insider/_cache_a2/`): the row-level
  Form 4 tables, event tables, `mech_events.parquet` and
  `bdc_events_crsp_LICENSED.parquet` and `bdc_permnos_missing_from_dsf_LICENSED.json`
  (CRSP-derived; never tracked).
- **Sources:** `docs/REFERENCES.md` §12ax.
