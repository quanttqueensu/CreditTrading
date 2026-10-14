# Pre-registration — E2: the issuer's reversal after a new convertible bond

**Date** 2026-10-13 · **Counter** EVENTS, one trial (0 → 1) · **Pass bar**
`scripts/cef/validate.py::_dsr` > 0.95 at the EVENTS N declared in decision 1
(default N = 4) · **Plan** `results/cef/RESEARCH_PLAN_2026-10-09.md` §3 row 6;
gate G3 · **Author** research agent, branch `research-prereg-c4-e2`

> **DRAFT — awaiting team-lead approval; the counter moves only in the commit that records approval.**
>
> **Nothing new has run.** No abnormal return, window sum, P&L or Sharpe was
> computed to write this, and no CRSP `ret` was read. The only measurements
> are:
>
> - counts of events and issuers per year, including the 2023–24 holdout
>   (dates and identities only);
> - a liquidity count on CRSP price × volume (levels);
> - one Alpaca snapshot's flags;
> - arithmetic on figures **already published** in
>   `results/events/REPRO_CORP_EVENTS_2026-10-11.md`.
>
> Reproducer: `python3 scripts/events/e2_feasibility.py`, run 2026-10-13,
> output `results/events/e2_feasibility_output_2026-10-13.txt`. This commit
> moves no counter, changes no spec and touches nothing on the order path.

---

## 0. The declaration in one table

| item | declared |
|---|---|
| what is tested | after a new 144A convertible, go long the issuer, hedged with SPY by its pre-event beta, from the close of day +1 to the close of day +5 (shift(2): decide day 0, earn days +2..+5) |
| events | `scripts/events/convert_issuance.py`'s event rule, unchanged; one event per issuer-day (spec B); issuer ADV ≥ the spec's `min_adv_usd` |
| fit | day 0 from 2011-01-01 to 2022-10-31: the set G3 examined. **Not out of sample** (plan row 6) |
| holdout | day 0 from 2023-01-01 to 2024-12-23, the last day 0 whose day +5 is inside CRSP: **142 liquid events** (§11). Untouched until opened once |
| named control | the straight-debt issuers, through the identical pipeline (plan row 6) |
| kills | event-level week-clustered t < 2 (plan row 6); the control earns ≥ ½ of the effect; placebo dates; per-event net ≤ 0 at 15bp one-way (plan row 6); D4; D3 |
| pass | every kill survived, `_dsr` > 0.95 at N, and all three holdout signs agree (§7) |

### 0.1 Decisions left for the team lead

Each has a stated default, so the draft is complete. Approval approves the
defaults unless a ruling says otherwise.

| # | decision | this draft's default | the alternative, and what it changes |
|---|---|---|---|
| **1** | **N for the EVENTS bar.** EVENTS stands at 0, so the running count would make E2's N whatever its place in the queue | **N = 4, the EVENTS programme declared in plan §3 (E1–E4), fixed on approval**, as XASSET's N = 5 was. The bar then does not depend on run order: the Sharpe needed is 0.957 | the running count: N = 1 if E2 runs first, Sharpe needed 0.475 (§11.3) |
| **2** | **The holdout rule** | three signs, all positive: the event mean, the sleeve's mean P&L, and convert minus control (§7). If the fit's effect is real, P ≈ 0.83 for each of the first two (they rest on the same events) and 0.82 for the third, one at a time | a one-sided t ≥ 1.645 on the event mean: P = 0.24 at the fit's effect |
| **3** | **The cost of the SPY hedge leg.** The house grid charges every unit of turnover alike, which overcharges SPY. At 15bp on both legs, a beta of 1.19 costs about 66bp a round trip against the fit's +54bp gross | **plan row 6's kill is per event on the issuer round trip, as G3 measured it** (gross − 2 × 15bp). The sleeve's grid is still charged on all legs, and reported with whether it flips sign (H3) | rule the hedge leg's cost |
| **4** | **Whether to spend the trial now.** On the fit (already examined): P(`_dsr` > 0.95) is 0.19 at N = 4, and P(alpha t ≥ 3) is about 0.29, both at the in-sample Sharpe, which overstates the truth. The likeliest verdicts are a D4 kill on alpha t, or NEITHER (§11.3) | run as specified: the holdout read is clean evidence whatever the verdict | defer until 2025+ events can be scored (CRSP ends 2024-12-31; a second price source, Alpaca SIP bars, would be needed) to enlarge the holdout |
| **5** | Announcement timing (DG-E2-2) | the trial runs only if at least 90% of checkable events have a public headline before day 0's close | a different threshold |
| **6** | Event set | spec B (one event per issuer-day), the repro's correction | spec A, the set G3 was declared on (reported in any case) |
| **7** | Liquidity | the CEF spec's `min_adv_usd`, read through `scripts/cef/spec.py`; it removes 7.4% of fit events | no floor (reported in any case) |
| **8** | When the counter moves | in the commit that records approval (the mandated wording, and the `/prereg` skill's) | at the run (the XASSET convention) |

**The evaluation-set ruling** (`results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md`,
phase-2 item 1) **does not touch E2**. E2 is scored on its own events, and
its correlation with the book is reported, not a kill.

---

## 1. What is tested, and what is not

**Tested:** whether the issuer's stock reverses part of its issuance-day drop
over days +2..+5, as a tradable, market-hedged sleeve, with an untouched
2023–24 holdout. A pass makes E2 a candidate sleeve inside the CEF account
(plan §4). That needs:

- live detection of new converts by the evening of day 0 (§3);
- its own spec key;
- its H11 statistic (§14);
- a release.

**Not tested:**

- other windows: [+2,+5] is fixed as examined. [+1,+5] cannot be traded
  under shift(2); [+2,+20] and longer are not this trial;
- a short of the issuer: the trade is long the issuer; the only short is SPY
  (§6);
- mandatory convertibles: that is E3, gated by G4.

## 2. Mechanism, who is on the other side, what is already known, and the graveyard

**Mechanism.** Convertible arbitrageurs buy most of a new convert and short
the issuer's stock to hedge its delta, mostly around pricing. If that selling
pushes the price below value, part of the drop should reverse once the hedge
is done. The buyer of that reversal is paid by the arbitrageur's need for
immediacy. Sources:

- Duca, Dutordoir, Veld & Verwijmeren (2012): issuance-day abnormal returns
  of −1.69%, −4.59% and −9.12% by period [V abstract];
- Mitchell, Pedersen & Pulvino (2007): arbitrageurs held "up to 75%" of the
  market [V];
- both in `docs/REFERENCES.md` §12d. The mechanism text is
  `scripts/events/convert_issuance.py`'s.

**Who is on the other side:** the arbitrageurs' delta hedgers, who sell the
stock to whoever will take it that day.

**Why it is not arbitraged away** [U]:

- the edge per event is small;
- events are lumpy;
- the trade carries the issuer's whole idiosyncratic risk for four days;
- the arbitrageurs themselves are the other side.

**What is already known, stated against ourselves**
(`REPRO_CORP_EVENTS_2026-10-11.md` §2 [V there]):

1. **The fit is spent.** [+2,+5] was first computed on 2011–22 on
   2026-10-09, so no fit statistic here is out of sample. The holdout is the
   only clean evidence.
2. **The effect lives in 2010–14.** By era, week-clustered:
   - 2010–14: +1.02% (t 2.44);
   - 2015–19: +0.14% (t 0.55);
   - 2020–22: +0.69% (t 1.28).
3. **In 2020–22 the straight-debt control earns +0.52%**, almost all of the
   convert's +0.69%. Convert minus control by era: +1.53% (t 3.43), +0.55%
   (t 1.84), **+0.17% (t 0.32)**. This is the graveyard's second pattern: a
   control scoring as well as the treatment.
4. **The sign flips at 30bp one-way:** +44 / +24 / −6bp per event.
5. **Clustering:** by week, the t is 2.24 (spec A) and **2.10 (spec B)**,
   just above 2.

**Graveyard** (`/graveyard`, `docs/RESEARCH_STATE.md`):

| dead mechanism | how E2 differs, and the risk that remains |
|---|---|
| `short-pressure` (crowded hedges unwind and reverse; **the rates control scored higher**; D1) | The nearest relative. E2's pressure is mechanical and dated (a convert's pricing), not inferred from short volume. But its control has already scored as well as the treatment once (2020–22). That is why the control is a fit kill **and** a holdout condition (§7, §8) |
| `raw-flow-z` (informed and forced flow cancel when pooled; D1) | Only forced flow is selected (hedging at issuance). Informed issuance timing is the issuer's run-up before day 0 (+1.45% over [−5,−2], spec A [V there]), which lies outside the traded window |
| the stale-price pattern | Operating companies, issuer ADV ≥ $3m, CRSP closing prices. shift(3) is reported (§8) |
| S3-forced-flow (WATCH: pressure reverses; D6) | The same family of idea. E2 fires about 20–120 times a year (§11), not 4 times in 273 months |

## 3. Divergences from the backtest, stated up front

1. **Detection.** The backtest's day 0 is the first 144A trade in TRACE.
   Live, a convert must be known by day 0's evening, from a news headline
   (Alpaca's news feed is Benzinga, from 2015; REFERENCES §12k [V docs];
   coverage of our names [U]) or a filing. A missed or late detection is a
   missed event. Public dissemination of 144A trades in TRACE began only in
   2014 [S, agent; not re-read] — the reason for DG-E2-2.
2. **Paper execution** is `late_market` day orders, 15:52–15:58 ET, not MOC
   (CLAUDE.md order rule 3). Paper has no auction, credits no dividends and
   charges no borrow. The issuer's auction print needs plan item 0.2 for
   Nasdaq names, and most convert issuers are Nasdaq-listed [U: not counted].
3. **Whole shares**, and small orders: at about 15% of $100k per event
   (§5), several hundred shares.
4. **The SPY hedge** is netted across overlapping events in one SPY order.
   The backtest nets it the same way in `H`.
5. **The account's gross cap** is shared with the CEF book live; here E2 is
   capped alone.
6. **Delistings inside the window** are rare at four days. The backtest uses
   CRSP's delisting return (§4.3); live, a halted stock cannot be sold at the
   close.
7. **Shortability of SPY** is re-read live; easy to borrow on 2026-10-12.

---

## 4. Data

### 4.1 Events (unchanged from G3)

`scripts/events/convert_issuance.py::build_events`, unchanged except for the
default-preserving `d0_start` / `d0_end` arguments added for this draft's
counts:

- the default reproduces G3's 1,044 CUSIPs, 761 matched events and 500
  permnos [V, re-counted 2026-10-13];
- universe: TRACE master `cnvrb_fl='Y'`, `sub_prdct_type='CORP'`, ever 144A;
- day 0: the first 144A trade (status T or R), within 10 days of the
  master's set-up date;
- issuer: CUSIP6 → CRSP common (share codes 10/11), with a name record
  covering day 0. One event per (permno, day 0); an event within 7 calendar
  days of the same permno's previous one is dropped.

**Declared on top of G3:**

| step | rule | fit (2011-01 → 2022-10) | holdout (2023-01 → 2024-12-23) |
|---|---|---:|---:|
| matched events, spec A | G3's rule | 761 | 158 |
| **spec B** (decision 6) | one event per (CUSIP6, day 0). A multi-class issuer is one event, its notional split equally across its classes | 702 | 144 |
| **liquidity** (decision 7) | ADV ≥ `min_adv_usd` ($3,000,000 on 2026-10-13, read through `spec.py`). ADV is the mean of \|prc\| × vol over the 63 CRSP sessions ending the session before day 0, with at least 21 present. Unmeasured ADV is excluded and counted, never passed | **650** | **142** |
| beta history | ≥ 120 returns in sessions −260..−11 (§5); others excluded and counted (G3: 708 of 755 spec-A events had it [V there]) | counted at Stage 0 | counted at Stage 0 |
| window | returns present on days +1..+5 (the fill and hold days), or a CRSP delisting return (§4.3). G3 also required days up to +60, which the trade never holds; that filter is dropped and its effect counted | counted at Stage 0 | counted at Stage 0 |

- **The gap.** Day 0 from 2022-11-01 to 2022-12-31: 11 events, in neither
  fit nor holdout. They are counted and dropped.
- **After 2024-12-23**, events are not used: CRSP ends.
- **The control** is the identical pipeline on `cnvrb_fl='N'` (straight 144A
  debt): fit 1,599 spec-B events, 1,415 liquid (10 with unmeasured ADV);
  holdout 138 and 133.
- **The 27-name holdout is not consumed.** Issuers are operating companies;
  the trial script asserts that none is in `data/cef/cef_universe.csv`, as
  G3's script does.

### 4.2 Returns and the hedge (H15)

- **Issuer and SPY:** CRSP `dsf.ret`, the total return with distributions on
  their ex-dates. SPY is permno 84398, asserted from `dsenames` over the
  whole span. The short SPY leg pays SPY's distributions inside `ret`.
- **A missing return on a held day** is replaced by CRSP's delisting return
  if the issuer delisted that day. Otherwise the event is excluded and
  counted (§4.1). Nothing is filled with zero.

### 4.3 Data gates (zero trials; any failure halts before a return is computed)

| gate | what | done when |
|---|---|---|
| **DG-E2-1** | Stage CRSP `ret` (and `dsedelist.dlret`) for issuers and SPY, 2010-01 → 2024-12-31, to the gitignored cache. **The fit reader refuses any 2023+ date**, as G3's `add_windows` does; the holdout reader is a separate function that runs only after the fit verdict's commit exists | both readers pass their guards; events re-counted against §11 and printed beside it (H14) |
| **DG-E2-2** | **Announcement timing (decision 5).** For events from 2015 on, read Alpaca news (Benzinga) for the issuer's symbol over days −5..+1, keep headlines naming a convertible offering, and record the first timestamp | **at least 90% of the events with any such headline have one before 16:00 ET on day 0.** Otherwise the trial does not run, no trial is spent, and the timing distribution goes to the team lead. Events from 2011–14 cannot be checked from this source, and that is stated as an untested assumption |
| **DG-E2-3** | French FF5 + UMD daily (`scripts/data/fetch_ff_factors.py`), vintage recorded | covers 2010-01 → 2024-12-31 |
| **DG-E2-4** | `compute.use_numexpr` off at import, and an assertion that no P&L or window sum is denormal-like. The panel is thousands of sessions × hundreds of permnos, above pandas' 1,000,000-cell numexpr threshold, and broadcast arithmetic was wrong there on this laptop (`scripts/events/numexpr_fault.py`) | the assertion passes |

**Quality screen** at Stage 0, listed by event, never altered by the trial
script:

- a window return with \|r\| > 50%;
- an issuer whose CRSP `prc` < 0 (no closing trade) on day +1 or day +5, the
  fill days;
- events whose day 0 falls on a CRSP non-session.

---

## 5. Positions, sizing and execution

**Decision and holding (H1).** For each event *e*, day 0 is the first CRSP
session on or after its first 144A trade. The position is decided after day
0's close:

| sessions (relative to day 0) | `H` for the issuer | `H` for SPY |
|---|---|---|
| 0, 1, 2, 3 | + u · sₑ | − u · sₑ · β̂ₑ |
| 4 onward | 0 | 0 |

`evaluate(H, R)` applies `H.shift(2)`:

- the position is bought at day +1's close;
- it earns days +2, +3, +4 and +5;
- it is sold at day +5's close, decided at day +4.

This is exactly G3's [+2,+5]. sₑ is 1 over the event's number of share
classes; u is the per-event notional (below).

**The hedge.** β̂ₑ is G3's beta-adjusted estimator
(`convert_issuance.beta_adjusted`): the slope of an OLS fit, with intercept,
of the issuer's `ret` on SPY's over sessions −260..−11, at least 120
present. Every input ends at day −11, before the pre-issue run-up and the
event (H7). No intercept is subtracted from the abnormal return. No shrinkage.
Market-adjusted (β ≡ 1, G3's own statistic) is reported beside it.

**Sizing to the spec's vol target** (ruling 4 of 2026-10-12, the XASSET P5
rule):

- **raw sleeve:** u = 1, one unit of issuer notional per event;
- **sized sleeve:** k × raw, with k = `vol_target_annual` / σ_fit.
  `vol_target_annual` is read through `spec.py` (0.06 on 2026-10-13). σ_fit
  is the raw sleeve's annualised daily gross P&L vol over the fit window,
  from its first position. k is one constant, frozen for the holdout and for
  live;
- **tradable sleeve:** the sized sleeve with the spec's `max_gross_stress`
  (1.80 on 2026-10-13) applied row by row through `_cap_gross`, the sleeve's
  own operator. The cap binds on busy weeks (up to 13 events in one week in
  G3); its binding share is reported;
- **D4's betas are read at the vol target:** each is multiplied by
  `vol_target_annual` / σ of the tradable sleeve over the fit.

**Turnover** is Σ\|ΔH\| over both legs, with SPY netted across overlapping
events.

**No new backtester.** `H` is a sessions × permnos frame built from the event
table, and `evaluate`, `_stats`, `fit_only` and `borrow_charge` come from
`scripts/cef/band_frontier.py` unchanged.

## 6. Costs, borrow and shorting

- **Gross is the headline.** On the sleeve, net is shown at 5, 15 and 30bp
  per unit of one-way turnover on all legs (`band_frontier._stats`), labelled,
  with whether the sign flips (H3). That overcharges SPY (decision 3).
- **Per event** (plan row 6's kill): gross β̂-adjusted CAR[+2,+5] − 2 × c,
  the issuer round trip, at c = 5, 15 and 30bp. G3 measured +44 / +24 / −6bp
  on spec A, market-adjusted.

**Borrow, charged separately and labelled (H4):**

- **The only short is SPY.** On 2026-10-12 it was `shortable` and
  `easy_to_borrow` on the cef paper key [V, §11].
- **Alpaca's live terms:** an easy-to-borrow short pays no borrow fee (Fee
  Schedule, revised 2026-10-01; REFERENCES §12l [V]). The borrow column is
  `borrow_charge(H, fee_pct)` with SPY at 0 on that basis. That is one
  snapshot applied to 14 years, a counterfactual, and it says so.
- **No SPY fee history** is in the repo for any broker. The mean SPY short
  notional is printed, so any rate can be applied.

**Can the issuer be shorted on Alpaca, and how is borrow charged?** E2 never
shorts the issuer.

- **On 2026-10-12,** 126 tickers belonged to liquid holdout issuers (CRSP
  ticker at day 0). Of those, 116 were listed and tradable, and **115 were
  shortable and easy to borrow** [V, `e2_feasibility.py` §3; true on that
  date only, landmine 5].
- **If a variant ever shorts an issuer,** Alpaca's live terms are:
  - easy to borrow: no fee;
  - hard to borrow: a locate fee per share, quoted at request and
    non-refundable, plus a daily fee on 102% of the prior close, actual/360,
    every calendar day, at a rate Alpaca does not publish (REFERENCES §12l
    [V]). The locate endpoint "is not available in paper trading".
- **The paper account charges no borrow at all** (CLAUDE.md landmine 1).
- **Whether a new issuer is harder to borrow in issuance week,** when
  arbitrageurs are borrowing it, is [U]. No historical issuer borrow series
  exists here.

## 7. Windows, eras and the holdout

**Fit.** Day 0 from 2011-01-01 to 2022-10-31; the sleeve's sessions run from
its first position to 2022-12-30 (3,020 sessions, 12.0 years, on the NYSE
calendar).

**Eras (H5).** 2010–14 (events from 2011), 2015–19 and 2020–22, each with its
event count, event t and sleeve turnover sd/mean. 2023–24 is the holdout.

**Holdout.** Day 0 from 2023-01-01 to 2024-12-23: 142 liquid convert events
and 133 liquid control events [V counts]. It is opened **once**, after the fit
verdict is committed, whatever that verdict. k and β̂'s rule are frozen. β̂
rolls (H13 allows a rolling estimator).

**The holdout rule (declared now; decision 2).** PASS only if all three hold.
Otherwise KILL (D3):

1. the mean β̂-adjusted CAR[+2,+5] over holdout events is > 0;
2. the tradable sleeve's mean daily gross P&L over the holdout is > 0;
3. the holdout convert mean exceeds the holdout control mean.

Condition 3 is there because the control already matched the treatment in
2020–22 (§2).

**Power, by arithmetic on the published fit figures** [`e2_feasibility.py`
§4]:

- if the fit's effect is real (+0.54%), P(1) = 0.83 and P(3) = 0.82;
- at half the effect, P(1) = 0.68;
- at 2015–19's +0.14%, P(1) = 0.60;
- if convert minus control is 2020–22's +0.17%, P(3) = 0.59;
- the three conditions are correlated, so their joint probability is not the
  product.

**The holdout can kill; it can never rescue a failed fit.**

## 8. Inference and controls

| quantity | method |
|---|---|
| **event level** (plan row 6) | mean β̂-adjusted CAR[+2,+5] over liquid spec-B fit events; **t clustered by calendar week of day 0** (CR1, `convert_issuance.cluster_t`, G3's declared statistic). Beside it: clustered by date, plain, and a week-cluster bootstrap (10,000 draws of weeks, seed 20261013) |
| **sleeve headline** | annualised gross Sharpe of the tradable sleeve's daily P&L over the fit |
| **HAC t** | Newey–West (Bartlett), **L = 21**, `scripts/cef/w4_artifacts.py::nw_t`. L = 4 (G3's calendar-time NW) and the Newey–West (1994) automatic lag are printed |
| **bootstrap** | stationary bootstrap, **mean block 21, 10,000 resamples, seed 20261013**, CIs for the sleeve's mean and Sharpe; mean block 63 and `w4_artifacts.block_boot_t` as second methods. The stationary-bootstrap helper is shared with C4's |
| **the bar** | `validate._dsr(obs, T, skew, kurt, N)` on the fit-window gross series; **PASS > 0.95**, N per decision 1 |
| beside it, never deciding | SR·√years against √(2 ln N); G3's calendar-time portfolio (equal weight across active events); spec A and market-adjusted versions |

**Controls:**

| stage | control | rule | why |
|---|---|---|---|
| **2** | **Straight-debt issuers** (plan row 6): the identical events, filters, hedge and window on `cnvrb_fl='N'`. The comparison is per event, which matches turnover by construction (one round trip each). Its sleeve is sized with its own k | **KILL** (not hedging pressure) if the control's mean β̂-adjusted CAR[+2,+5] is ≥ ½ × the convert's, same sign, on the fit. Reported beside it: convert − control with week-clustered t (`convert_issuance.diff_test`), by era | Straight debt draws no delta hedging (H12), named by G3 before it ran |
| **3** | **Placebo dates.** Each event's day 0 is replaced by a date drawn uniformly from the same issuer's fit-period CRSP sessions, at least 60 sessions from any of its real convert events, with β̂ history available. Same u, k, hedge and cap. 1,000 draws, seed 20261013 | **KILL D1** if the real sleeve's gross Sharpe is at or below the placebo's 95th percentile | Same issuers and exposure, no issuance: tests whether the timing carries the return |
| reported | **shift(3)**: `evaluate(H.shift(1), R)`, earning days +3..+6 | no kill | The pressure is short-lived by mechanism, so one day's delay is expected to cost; that is decay, not staleness |
| reported | **mechanism slope**: the event's [+2,+5] CAR on its [−1,0] CAR, week-clustered | no kill | Hedging pressure predicts that a larger drop reverses more: a negative slope |

**Comparisons are turnover-matched by construction (H2):** control and
treatment per event, and the placebo with the same events and notional.

## 9. Regressions

OLS with statsmodels HAC covariance (maxlags 21). The P&L is a self-financing
long-short return, so no risk-free rate is subtracted.

| regression | role | specification |
|---|---|---|
| **R-D4** | **decision** | daily tradable gross P&L on French **Mkt-RF, SMB, HML, RMW, CMA, UMD**, contemporaneous (the issuers clear a $3m ADV floor). **Pass: alpha t ≥ 3.0, and every \|β\| ≤ 0.10 at the vol target** |
| R-DIM | reported | the same with each factor also at *t*−1 (Dimson), betas summed |
| R-CAPM | reported | Mkt-RF alone: the residual market exposure the β̂ hedge leaves |
| R-BOOK | reported | on the deployed CEF book's daily P&L (`scripts/xasset/book_profile.py`): correlation and beta, **never a kill** (plan row 6 names none) |

## 10. Robustness: reported, never chosen from, and none of it rescues a failed headline

- spec A; market-adjusted (β ≡ 1); no liquidity floor;
- the +60-day completeness filter restored (G3's sample);
- the issuer-day collapse undone;
- per-era rows with turnover sd/mean;
- calendar-year sign share;
- leave-one-year-out minimum, median and maximum;
- the raw (uncapped) sleeve;
- bootstrap mean block 63; NW automatic lag;
- the sleeve grid with SPY charged at 5bp at every point (decision 3);
- **capacity:** the sleeve capital at which the median event's entry order
  reaches 1% of the issuer's 63-session ADV, and participation at $1m, $10m
  and $100m.

## 11. Feasibility, measured today (zero trials)

`QUANTT_ENV_FILE=… python3 scripts/events/e2_feasibility.py`, run 2026-10-13:

- the event caches are `convert_issuance.py`'s R2 pulls (TRACE to 2025-12-04,
  CRSP names to 2024-12-31);
- one R2 pull of CRSP `prc` and `vol` (no `ret`) for 1,198 issuers,
  2010-06-01 → 2024-12-31;
- the Alpaca active-asset snapshot of 2026-10-12T18:27Z (cef paper key);
- every figure is [V] by that script unless labelled.

### 11.1 Events

| | fit, spec A | fit, spec B | **fit, liquid** | holdout, spec A | holdout, spec B | **holdout, liquid** | weeks with an event (fit / holdout) |
|---|---:|---:|---:|---:|---:|---:|---:|
| convert | 761 | 702 | **650** | 158 | 144 | **142** | 332 / 65 |
| control | 1,650 | 1,599 | 1,415 | 140 | 138 | 133 | 510 / 72 |

- **Liquid convert events per year:** 2011 34, 2012 19, 2013 53, 2014 37,
  2015 37, 2016 30, 2017 50, 2018 72, 2019 56, 2020 118, 2021 116, 2022 39
  (including the 11 gap events), 2023 61, 2024 81.
- **Median issuer ADV:** $25.6m in the fit, $50.6m in the holdout.
- **G3's spec-B n of 696** is after its windows (which needed days up to
  +60). The 702 here is before any window.

### 11.2 Alpaca (2026-10-12; true on that date only)

- **SPY:** tradable, shortable, easy to borrow.
- **Holdout liquid issuers** (126 CRSP tickers): 116 listed and tradable, 115
  shortable and easy to borrow.

### 11.3 The bar and its power

Fit: 3,020 sessions (12.0 years).

- **Inputs, from the published fit figures** (REPRO_CORP_EVENTS §1 and its
  run log [V there]): G3's calendar-time portfolio has a Newey–West t of
  2.45, which implies an annual Sharpe of about **0.71**. That is in sample,
  on windows already examined, so it **overstates** the true value.
- Required Sharpe from `validate._dsr` (skew 0, kurtosis 3), reusing
  `scripts/xasset/slate_feasibility.py`:

| N | Sharpe needed | P(pass) at 0.71 | P(pass) at 0.36 |
|---:|---:|---:|---:|
| 1 | 0.475 | 0.79 | 0.34 |
| 2 | 0.816 | 0.35 | 0.06 |
| 3 | 0.904 | 0.25 | 0.03 |
| **4 (default)** | **0.957** | **0.19** | 0.02 |

- **D4:** at a true t of 2.45, P(alpha t ≥ 3.0) ≈ 0.29.
- **Per-event dispersion** (spec B, fit): sd 5.96% convert, 5.40% control;
  week-cluster design effects 1.30 and 1.25 (= \|mean\| × √n / plain t, from
  the published figures).

**What a result means, stated before it exists:**

- a **PASS** would be strong evidence, against the odds;
- the likeliest verdicts are a **D4 kill on alpha t**, or **NEITHER** at
  N = 4;
- a **holdout fail is informative**: the sign rules have power of about 0.8
  if the fit's effect is real;
- a **holdout pass is weak evidence on its own**: a sign rule passes about
  half the time under the null.

## 12. The order of evaluation (the exact kill tests)

| stage | statistic | rule | if it fails |
|---|---|---|---|
| 0 | DG-E2-1…4; the quality screen; event counts by filter; k, cap-binding share, turnover | a gate fails | **no trial spent**: fixed, or referred to the team lead |
| — | **the trial is spent from here** | — | — |
| 1 | event-level mean β̂-adjusted CAR[+2,+5], week-clustered t (fit, liquid, spec B) | t ≥ 2.0 (plan row 6) | **KILL D1** |
| 2 | straight-debt control (§8) | control mean < ½ × convert mean | **KILL** (not hedging pressure) |
| 3 | placebo dates (§8) | real gross Sharpe > placebo p95 | **KILL D1** |
| 4 | per-event net at 15bp one-way (§6) | > 0 (plan row 6) | **KILL D2** |
| 5 | R-D4 | alpha t ≥ 3.0 and every \|β\| ≤ 0.10 at the vol target | **KILL D4** |
| 6 | the bar: `_dsr` at N | > 0.95 | **NEITHER**: real at most, below the bar; no sleeve and no re-test on these data. The team lead rules WATCH or D5 |
| 7 | the fit verdict is committed | — | — |
| 8 | the holdout rule (§7) | all three signs > 0 | **KILL D3** |
| — | the sleeve's 5 / 15 / 30bp grid, all legs | reported, with whether it flips sign | — |

**Every statistic of every stage is computed and reported, whatever the
verdict.** The verdict is the first failing rule in this order. A PASS needs
stages 1–6 and 8. These kill rules are pre-committed and are not softened
later.

## 13. What we expect [U]

| stage | expectation |
|---|---|
| 1 | Passes narrowly or fails narrowly. G3's spec-B week t was 2.10 on all events; the liquid, β̂-hedged version is unmeasured |
| 2 | Passes on the full fit, where the control is −0.17% against +0.54% |
| 4 | Passes if the fit's mean holds (about +24bp) |
| 5 | Most likely kills: alpha t ≥ 3 needs more than the fit has shown |
| holdout | Somewhere between G3's 2015–19 and 2020–22 rows |

Being wrong here is fine and is the point.

## 14. What would falsify it once trading on paper (H11)

Stated now, for an E2 sleeve that passed and was released:

- **Fidelity, per event.** Each live event's decision date, entry (day +1
  late window on paper), exit (day +5) and hedge ratio must match the
  declared rule run on the same data. A difference halts the sleeve as a bug.
  A missed detection is logged and counted, never back-filled.
- **Reversal after 40 live events.** That is about six to eight months at
  2023–24's rate of 61–81 liquid events a year. Reverse if the mean live
  per-event P&L (official fills, issuer and hedge legs) is below the **5th
  percentile of the trial's own 40-event means**. That percentile is
  re-measured on the read date by resampling fit and holdout events by week.
  **No threshold is written here as a number (H14).**
- **At any time:** reverse if the live drawdown exceeds the fit's worst,
  re-measured.

## 15. Trial accounting

- **EVENTS today: 0 trials** (orient TRIALS, 2026-10-13 [V]). On approval:
  **0 → 1**, in the commit that records the team lead's approval (decision
  8), not in this commit. N for the bar is decision 1 (default 4).
- **`docs/RESEARCH_STATE.md` changed in this commit: no.** No other counter
  moves. The 27-name holdout is not consumed. The 2023–24 holdout stays
  untouched until E2's fit verdict is committed.
- **Zero-trial script:** `scripts/events/e2_feasibility.py`, with tests in
  `scripts/events/tests/test_e2_feasibility.py`. `build_events` gained
  default-preserving `d0_start` / `d0_end` arguments; the default re-counts
  G3's 1,044 / 761 / 500 exactly.
- **Trial script (after approval):** `scripts/events/e2_convert_reversal.py`,
  building `H` from `convert_issuance.build_events` and scoring it with
  `band_frontier.evaluate`. There is no new backtester.
