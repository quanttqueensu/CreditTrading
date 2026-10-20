# Is IBKR worth it? A decision note (2026-10-19)

**Team lead, 2026-10-19**, after hearing that only MHD (always), PHK and MQY (sometimes)
of the 13 spec names need IBKR, that IBKR's weekly login is manual (IBC retired) and
that the VM would need 4 GB (about USD 27 a month of a USD 100 student credit):
**"Figure out if it's worth it."**

**ZERO TRIALS. The 2023-01-01 time holdout stays sealed.** Every backtest figure
below uses data dated before 2023-01-01 only, and is a diagnostic: nothing is
adopted. No broker was connected, no credential was loaded, the VM was not read,
nothing was ordered, and no live-path code was written. The harness gained one
optional argument, `band_gross_capped(..., unshortable=None)`, whose default is the
old loop byte for byte (§1.1).

Reproduce every number:

    python3 scripts/ops/ibkr_worth_it.py          # §1; writes results/ops/ibkr_worth_it/
    python3 -m pytest scripts/ops/tests/test_ibkr_worth_it.py scripts/cef/tests/test_band_gross_capped.py

The run behind this note is `results/ops/ibkr_worth_it/ibkr_worth_it_output.txt`,
with its tables as CSV beside it. Sources fetched in this pass are in
`docs/REFERENCES.md` §12as. It builds on `results/ops/IBKR_SECOND_BROKER_2026-10-19.md`
(the design; "the IBKR note" below) and does not repeat it.

**Data as of.** Spec `cef_discount.v7.20260928`, read through `scripts/cef/spec.py`
(band 4.8%, `max_gross_stress` 1.80, ADV floor USD 3m, vol target 0.06, capital
USD 100,000). Harness panels cut at 2022-12-30 (a temporary copy; the live panels
were not modified). IBKR fees: the public file stamped `2026.10.19 10:59:08`, from
`results/ops/ibkr_second_broker/names_2026-10-19.csv`. Alpaca: the five committed
probe snapshots (2026-09-28 → 2026-10-15) and the 2026-10-18 flag read. IBKR's
historical FEE_RATE panel, pre-2023 part only (2021-09-13 → 2022-12-30).

**Labels.** [V] measured by the named script this session, or fetched and read
this session. [S] sourced from a committed note, not re-measured. [U] not verified
or not measurable from here.

---

## 0. The answer

1. **The benefit to the core book is small and statistically indistinguishable
   from zero** [V]. Take the extreme case: the three names are never lendable at
   Alpaca and always lendable at IBKR (f = 1). Then IBKR adds the following,
   2013-06 → 2022:
   - **+0.33%/yr gross** (NW t 0.26) on the deployed set, the evidence the live
     spec rests on;
   - **+0.76%/yr gross** (t 0.64) on the WIDE set, the closest fit-period
     analogue to today, when all 13 names clear the ADV floor;
   - the gain is **USD 330–760 a year** at USD 100k.
   - **It flips negative at 30bp** in both sets.
   - **At matched turnover it is +0.40%/yr on the deployed set and −0.42%/yr on
     WIDE.**
   - **After IBKR's own borrow (today's fees) and commissions, it is +0.12 and
     +0.09%/yr: USD 90–120 a year.**
   - Proving even the WIDE point estimate at t = 2 would take about 94 years of
     data.
2. **The deployed backtest has no information about MHD at all.** MHD never
   cleared the ADV floor before 2023, and MQY did on 3.7% of 2013-06 → 2022
   sessions [V]. The live
   book holds both short at 13–26% of equity each (committed snapshots, [V]).
   It is running a regime its own evidence never saw, which is why the WIDE set
   is shown.
3. **The costs are fixed, and at USD 100k they exceed the prize after IBKR's own
   costs** (on the gross paper score, see §4).
   - **VM resize: USD 26.86 a month** (B2pls_v2 [V]). The 4 GiB size is not on
     the student offer's free list [V].
   - At about USD 33 a month in all, a full USD 100 credit lasts about 3 months
     (arithmetic). After that the subscription is disabled and **the book stops**
     [V].
   - **52 manual logins a year**, plus one after every Gateway crash or reboot.
   - **About 4,650 lines to revive and four runner modules to change.**
   - **A second order path** with one-legged days on paper.
4. **The case for IBKR is option value, and it only exists if a sleeve passes.**
   - **E1:** most muni acquirers need IBKR. The pre-registration's own arithmetic
     puts P(pass at N = 6) at 0.15 at its optimistic Sharpe [U]. At real money,
     borrow at least eats the effect in 6 of 7 windows [S].
   - **NAV tenders:** IBKR is needed only for the muni hedge, on 8% of fit events,
     The approved default (decision 3) hedges them through MUB at IBKR; the
     prereg's own alternative excludes them.
   - **SPAC redemption:** live money only (paper probably cannot redeem [U]), and
     its gate has not passed [S].
5. **Verdict: do not build the IBKR path or resize the VM now.**
   - Measure how often the plan's shorts are actually blocked: free (§5).
   - Optionally, the team lead opens the **account only** (USD 0 minimum, no
     inactivity fee [V]; USD 2,000 to margin-short [S]), so that approval time is not
     on E1's critical path.
   - Build only when a trigger in §5 fires.
   - Before any resize, measure the Gateway on the existing 1 GiB VM.
   - For real money, price Alpaca's own live hard-to-borrow locate route before
     IBKR: it exists and is unmeasured (§4).

---

## 1. Benefit to the core book, measured

### 1.1 Method

- **Harness.** Each book is built with `build_targets` →
  `band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)` → `evaluate`. This is the
  deployed policy, with decide at *t*, fill at *t*+1 and earn *t*+2.
  - Every parameter is read through `scripts/cef/spec.py`.
  - The four panels the harness reads are copied, cut before 2023-01-01, and
    `band_frontier.DATA_DIR` points at the copy (the C5 pattern). Every frame is
    asserted to end before the holdout.
- **The names.** X is **derived** from the names file, never typed: spec names
  unlendable on at least one committed record. That gives MHD, MQY and PHK.
  - The record does not say "MHD always". MHD was shortable on 4 of the 6 reads
    and unshortable on the two latest, 10-15 and 10-18.
  - HYT was refused at send on 2026-10-01 (`results/cef/ALPHA_LEAKAGE_2026-10-13.md`
    B1, [S]). No committed snapshot records that, so HYT is not in X.
- **The books compared.**
  - **base**: every name lendable every day. This is what Alpaca plus IBKR
    could hold if IBKR always lends: an upper bound on access.
  - **skip X**: X is never lendable, under **the live rule**. Gate 7 skips an
    order that opens or enlarges a short, and lets a reduction or a close
    through ("skip that name, send the rest", 2026-09-28). An existing short is
    held. In the harness this is `band_gross_capped(..., unshortable=...)`: on a
    blocked day the held weight is floored at min(yesterday's weight, 0), before
    the gross ceiling.
    - The no-op is proved two ways. The sha256 of the held book on the fit-cut
      panels is identical before and after the edit, deployed and WIDE, with
      and without the cap. A test pins `None` against a copy of the old loop.
    - Six new tests fail against the old code. Each wrong floor (0, or today's
      move) fails named tests.
  - **re-neutral X** (a policy the book does not run; report only). X's short
    target is removed, and the other names' shorts are scaled up to the same
    total. The book stays dollar-neutral at the same gross.
- **Sets.** **deployed** uses the spec's ADV floor. **WIDE** uses `min_adv=0`, the
  same rule with the floor off. WIDE is context, not the live policy. It is shown
  because all 13 names have cleared the floor on every session since 2024
  (`ALPHA_LEAKAGE_2026-10-13.md` A1, [S]), and the deployed fit period did not.
- **Conventions.**
  - **Total returns** are the headline: splits and distributions, because a
    short pays the distribution.
  - **Gross** is the headline. The 5/15/30bp grid on turnover sits beside it.
  - **IBKR borrow** at the file's fee has its own column, charged by
    `band_frontier.borrow_charge` on the X shorts only. An easy-to-borrow Alpaca
    short is free (REFERENCES §12l), so the IBKR fee is the increment.
  - **IBKR commission** has its own column: Pro Fixed on the IBKR-routed trades,
    at `CAPITAL_USD` and the broker's own marks (MHD USD 10.15 on 10-14; MQY
    10.20 and PHK 4.08 on 10-15).
  - The headline era is **2013-06 → 2022**: before 2013 the book is flat
    (landmine 8). Other eras sit beside it.

### 1.2 How often, and how much, the band wants them short

Held book, 2013-06 → 2022 [V, `holdings_freq.csv`]:

| set | name | eligible | held short | mean weight when short | share of the book's short weight |
|---|---|---:|---:|---:|---:|
| deployed | MHD | **0.0%** | 0.0% | — | 0.0% |
| deployed | MQY | 3.7% | 1.4% | −0.088 | 0.2% |
| deployed | PHK | 82.3% | 49.8% | −0.239 | 20.5% |
| WIDE | MHD | 100% | 42.5% | −0.136 | 8.4% |
| WIDE | MQY | 100% | 46.9% | −0.150 | 10.2% |
| WIDE | PHK | 100% | 48.1% | −0.165 | 11.5% |

- **Deployed, full fit 2005–22:** MHD eligible on 0.0% of sessions, MQY on 2.0%,
  PHK on 90.4%.
- **On the deployed set the band's short in these names is PHK, and only PHK.**
  On WIDE, the three together carry 30% of the short book.
- **Live, by contrast** (the committed probe snapshots, [V], positions ÷ equity):

  | date | MHD | MQY | PHK |
  |---|---:|---:|---:|
  | 10-10 | −19.4% | −25.8% | +16.5% |
  | 10-13 | −14.9% | −20.9% | +15.6% |
  | 10-14 | −14.8% | −13.0% | +15.3% |
  | 10-15 | flat | −13.3% | +19.9% |

  The live book matches the WIDE pattern, not the deployed one.

### 1.3 What their shorts earn in the base book

Gross P&L of each name's short leg, total returns, %/yr of capital, NW t (5 lags),
2013-06 → 2022 [V, `short_leg_pnl.csv`]:

| set | MHD | MQY | PHK | sum |
|---|---|---|---|---:|
| deployed | 0 (never held) | +0.131 (t 0.95) | +0.249 (t 0.20) | +0.379 |
| WIDE | **+0.509 (t 1.30)** | +0.122 (t 0.24) | +0.150 (t 0.17) | +0.781 |

- **By era, the PHK short is unstable.** On the deployed set it earned +1.37%/yr
  in 2015–19 and −0.35%/yr in 2020–22.
- **MHD on WIDE is the only short leg with a t above 1**, and it has one in
  every era but 2015–19.

### 1.4 With and without

Benefit of access = base minus the without-book, %/yr of capital, total returns,
2013-06 → 2022 [V, `benefit.csv`]. The sign is positive when access helps.

| without-book | gross (NW t) | @5 | @15 | @30 | flips | turnover gap | turnover-matched gross (t) | alpha vs EW (t) | price returns | after IBKR borrow + commission |
|---|---|---:|---:|---:|---|---:|---|---|---:|---:|
| deployed, skip all three | **+0.326 (0.26)** | +0.267 | +0.149 | −0.028 | YES | −8.7% | +0.399 (0.32) | +0.643 (0.52) | +1.695 | **+0.118** |
| deployed, skip MQY | +0.131 (0.95) | +0.123 | +0.109 | +0.087 | no | −1.1% | matched | +0.137 (0.99) | +0.146 | +0.121 |
| deployed, skip PHK | +0.195 (0.16) | +0.143 | +0.040 | −0.115 | YES | −7.7% | +0.250 (0.20) | +0.507 (0.41) | +1.549 | −0.003 |
| WIDE, skip all three | **+0.760 (0.64)** | +0.520 | +0.039 | −0.683 | YES | −15.5% | **−0.420 (−0.36)** | +1.182 (1.05) | +2.356 | **+0.089** |
| WIDE, skip MHD | +0.562 (1.42) | +0.479 | +0.312 | +0.062 | no | −5.4% | +0.210 (0.53) | +0.646 (1.66) | +0.884 | +0.320 |
| WIDE, skip MQY | +0.116 (0.23) | +0.011 | −0.198 | −0.512 | YES | −6.7% | −0.343 (−0.66) | +0.238 (0.48) | +0.485 | −0.125 |
| WIDE, skip PHK | +0.028 (0.03) | −0.033 | −0.154 | −0.337 | YES | −3.9% | matched | +0.244 (0.28) | +0.927 | −0.161 |
| deployed, re-neutral (not run live) | +0.915 (0.69) | +1.018 | +1.225 | +1.536 | no | +15.4% | +0.906 (0.68) | +1.068 (0.80) | +0.897 | — |
| WIDE, re-neutral (not run live) | +0.217 (0.17) | +0.586 | +1.324 | +2.432 | no | +23.7% | +1.446 (1.16) | +0.138 (0.11) | −0.396 | — |

**How to read the columns.**
- **@5 / @15 / @30** charge each book's own turnover at that rate, so they include
  the cost of the base book's extra trading.
- **"Turnover-matched"** compares the without-book with a base book whose band
  width was bisected on turnover alone to match it (H2).
- **"Alpha vs EW"** is the intercept of the difference on the equal-weight total
  return of the spec names (HAC, 5 lags).
- **"After IBKR"** is the gross figure less the X shorts' borrow at today's file
  fee and the IBKR commission on their trades.

What the table says:

- **Every gross benefit in the table has |t| < 1.5, and the headline pair has
  t < 0.7.** None is evidence. The strongest single cell anywhere in the output
  is WIDE, skip all three, full fit 2005–22: alpha vs EW +1.83%/yr at t 2.40.
  Its raw gross is +1.04%/yr at t 1.24, it is one of 40 rows of the difference
  table, and it is on the context set, not the deployed one. At the measured t, reaching t = 2 would take about **94 years**
  (WIDE) and **570 years** (deployed). That is 9.57 × (2/t)², arithmetic. **The
  live record can never settle this, so the decision has to rest on the bound
  against the costs.**
- **Two methods agree on the size.** The f = 1 book difference (+0.326, +0.760)
  sits beside the summed short legs of §1.3 (+0.379, +0.781). That holds in every
  era but deployed 2020–22, where both are near zero (+0.07 against −0.03) [V,
  the CROSS-CHECK block of the output].
- **Without IBKR the book is not dollar-neutral.**
  - Skipping all three leaves it net long: **+0.16** of equity on deployed and
    **+0.21** on WIDE, against +0.04 and +0.00 for base.
  - Its beta to the equal-weight universe rises to **0.09** and **0.07**.
  - That is inside D4's 0.10, but it is beta, not alpha.
  - The alpha column strips it, and is larger than the raw gross (+0.64 and
    +1.18) because the net long earned positive beta.
- **On the deployed set, blocking PHK raises the gross Sharpe** (0.95 to 1.02).
  Volatility falls more than return. The PHK short adds risk faster than it adds
  P&L.
- **Re-neutralising is no cheaper remedy.**
  - On the deployed set it loses more than skipping, gross and at every cost.
  - On WIDE it loses less gross, but trades 24% more, and so loses more from
    5bp up.
  - It is a policy change (a CEF trial) in any case. Recorded as a negative
    result.
- **A paper artefact, flagged so nobody reads paper P&L as evidence.**
  - On **price returns**, which is how Alpaca paper scores because paper books
    no dividends [V docs, `CLAUDE.md` landmine 1], access looks worth
    **+1.70%/yr** (deployed) and **+2.36%/yr** (WIDE).
  - That is 3–5 times the total-return figure. The difference is the
    distributions these high-payout shorts would owe and paper never charges.
  - Whether IBKR paper charges payment in lieu is [U] (the IBKR note, R6). The
    third, distribution-adjusted P&L line is the honest one.

### 1.5 Scaling with f, the share of sessions a name is blocked

Section 7 of the output blocks the three names in random episodes: blocks of L
sessions, each blocked with probability f, 10 seeds. These are synthetic flags, a
claim about how the **policy** responds, not about Alpaca. Ratio = benefit(f, L) ÷
(f × benefit(1)), 2013-06 → 2022 [V, `episodes.csv`]:

| set | f = 0.25, L = 5 | f = 0.25, L = 21 | f = 0.5, L = 5 | f = 0.5, L = 21 |
|---|---|---|---|---|
| WIDE | 0.38 [−0.38, 1.89] | 0.76 [−0.34, 2.25] | 0.61 [−0.05, 1.22] | 0.70 [−0.57, 2.23] |
| deployed | −1.60 | −0.59 | −0.91 | −2.12 |

- **On WIDE the mean ratio is below 1 in all four cells.** An existing short
  survives an episode, so the loss is less than proportional. So **f × benefit(1)
  is an upper bound on average**, and §4 uses it as the generous case.
- **On the deployed set** the f = 1 benefit (t 0.26) is too small for the ratio
  to mean anything: its sign moves with the timing of the episodes.

### 1.6 The borrow regime decides the sign at real money

The base book's X shorts were charged at IBKR's **historical** daily FEE_RATE.
This is the only pre-2023 fee record: 2021-09-14 → 2022-12-30, with coverage of
98.1% (deployed) and 98.3% (WIDE) [V, `borrow_sensitivity.csv`].

| | deployed | WIDE |
|---|---:|---:|
| borrow at the historical fee, %/yr | **1.71** | **2.50** |
| the same window at today's file fee, %/yr | 0.05 | 0.13 |
| median fee in the window, %/yr | MHD 23.21, MQY 19.10, PHK 37.81 | (same) |

- **In the 2021–22 fee regime, borrowing these three through IBKR cost about
  2–5 times the f = 1 benefit** (against the headline era or 2020–22).
- **Today's fees** (MHD 2.57, MQY 1.84, PHK 0.57%/yr) leave a small positive
  margin. The fee moves fast: MQY's doubled in one session (the IBKR note §1).
- On paper the borrow decides nothing (D19/D20), but it decides the real-money
  sign.

### 1.7 What the live record can and cannot tell us (no VM read)

**It can tell us:**
- The live book wants MHD and MQY short, at 13–26% of equity each, on the
  committed snapshots of 10-10 → 10-15 [V].
  - It has been net short munis by 36–45% of equity every day since 09-30
    (`ALPHA_LEAKAGE_2026-10-13.md` B3, [S]).
  - This is the WIDE regime. The deployed backtest never saw it.
- The flags move. The reads were:
  - 09-28: all shortable;
  - 10-10 and 10-13: PHK unshortable, while the book was **long** PHK, so it
    cost nothing;
  - 10-15: MHD unshortable, after the book's MHD short had left between the
    10-14 and 10-15 snapshots. Why it left is [U];
  - 10-18: MHD and MQY unshortable. The MQY short of −1,298 can be held but not
    enlarged.
- The one recorded refused short is HYT on 10-01. It lost USD 2.5k of
  gross-days, out of USD 1.28M held (`ALPHA_LEAKAGE` B1, [S]).

**It cannot tell us:**
- **A rate f.** There are six reads in three weeks, and the collector does not yet
  record flags daily (step A5 of the IBKR note).
- **Whether the plan wanted an MHD short on the blocked days.** That is in the VM's
  `<state>/<D>/plan.json` and `send.json`, which gate 7 annotates. Not read here.
- **Whether IBKR would have lent at order time.** The file is indicative (the IBKR
  note, R5).
- **Any P&L value.**
  - The whole book's alpha since inception has t ≈ 0.1 (`ALPHA_LEAKAGE` B6, [S]).
  - Its muni legs lost USD 166 over 09-29 → 10-13 ([S], modelled).
  - At the effect sizes of §1.4, no live record of any plausible length
    separates the benefit from zero.

---

## 2. Option value: what IBKR would enable only if a trial passes

None of this has value unless the named trial passes. The probabilities below are
the pre-registrations' own arithmetic, labelled as they label them. None is
estimated here.

| use | what IBKR adds | does it pass? (the document's own figures) | value at real money |
|---|---|---|---|
| **E1**, EVENTS trial 1 (running), the NAV-for-NAV muni merger pair. Both legs go to IBKR when Alpaca will not lend the acquirer | 2026-10-13 flags, historical muni deals: Alpaca could short the acquirer in **16 of 57** (28%); IBKR's file listed **41 of 57** (72%) [S, G1a]. So IBKR adds **25–41 of 57 deals** (arithmetic; 25 if every Alpaca name is in IBKR's file). Deal flow: 49 muni groups over 2010–22, about 3.8 a year, and 3 groups in 2023–24 [S, the E1 prereg] | P(pass at N = 6) **0.15 at a true Sharpe of 0.67, 0.02 at 0.40**; P(D4 alpha t ≥ 3) 0.28 at 0.67. "The likeliest verdicts are a D4 kill on alpha t, or NEITHER" [U, prereg §11]. Admission falsifier: fewer than 3 groups in 24 months shelves it | **About nil.** Acquirer borrow over the hold is at least the +167bp effect in **6 of 7** muni windows; 196bp at today's median IBKR muni fee [S, `MERGER_ARB_V2_2026-10-19.md` §0.5]. Amendment 1 judges E1 on P&L with fees ignored, so E1 can pass on paper and still be worthless at real money |
| **NAV tenders**, EVENTS trial 2 | Only the muni hedge, MUB at IBKR at 7.73%/yr: **11 of 138** fit events (8%), 8 of 32 holdout [S, prereg §11.1]. That is decision 3's default, approved with the trial; its alternative excludes muni events and runs in one account | P(pass at N = 6) **0.02 / 0.38 / 0.99 at Sharpe 0.4 / 0.9 / 1.6** [U, prereg §11.2 assumptions] | The muni slice's hedge pays 7.73%/yr. Elections are manual at either broker |
| **SPAC redemption** | The only documented redemption channel, with a manual election per SPAC at USD 100 [S, `SPAC_IBKR_2026-10-19.md`] | **Gate not passed.** Paper redemption is [U], "probably no". Each election is a manual Client Portal action | Live money only. 53–64 manual elections a year if all 21 slots are held [S] |

**Scale for E1, if it passes, at the prereg's own scale Sharpe.** This is
arithmetic on [U] inputs, and the prereg says the input overstates.

- A sleeve at the spec vol target earns about 0.67 × 0.06 ≈ **4%/yr gross on
  paper**.
- IBKR enables 44–72% of its muni deals, so roughly **1.8–2.9%/yr**, or USD
  1,800–2,900 a year at USD 100k. That is about 2–9 times the core book's f = 1
  prize.
- Weighted by the prereg's 0.15 it is a few tenths of a percent a year, the
  same order as the core book.
- **E1's value is concentrated in its PASS branch.** That is why the trigger in §5
  is the verdict, not this expectation.

---

## 3. Costs, every one fetched or measured

| item | amount | status | source |
|---|---|---|---|
| VM resize to 4 GiB (Standard_B2pls_v2, Linux, canadacentral) | **USD 0.0368/h, USD 26.86 a month** at 730 h; today's B2pts_v2 is 0.0092/h | [V] 2026-10-19T20:42Z | Azure Retail Prices API (§12as) |
| Is it free on the student offer? | **No.** "750 hours each of B1s, B2pts v2 (Arm-based), and B2ats v2 (AMD-based)"; B2pls v2 is not listed | [V] 2026-10-19 | azure.microsoft.com/free/students (§12as) |
| What the resize does to the credit | Today: the VM is free; disk USD 2.64 and IP USD 3.65 a month come from credit, about USD 6.3 a month in all. After the resize, about **USD 33.15 a month**. A full USD 100 then lasts about **3.0 months** instead of the offer's 12. The remaining balance was not read [U] | arithmetic on [V] prices (`docs/RUNBOOK.md` §8.7, 2026-10-07; this pass) | "If you don't [move to pay as you go], your subscription and products will be disabled" [V]. **A disabled subscription stops the VM, and the book** (RUNBOOK §8.7) |
| Does the Gateway need 4 GiB? | IBKR recommends 4,000 MB for API users. The VM has 1 GiB plus 2 GB of swap. Whether the Gateway fits is **unmeasured** | [V] doc; [U] fit | the IBKR note §2.9; step A9 |
| IBKR account | Individual Pro: **account minimum USD 0.00, inactivity fee USD 0.00**. Margin (needed to short): **USD 2,000** minimum equity. The API needs a funded Pro account. Whether less funding suffices for paper-only API use is [U] | [V] 2026-10-19 (minimums, fees); [S] §12aa (USD 2,000; API) | IBKR required-minimums page (§12as); §12aa |
| Commissions at our ticket sizes (IBKR-routed trades, f = 1, 2013-06 → 2022) | deployed: MQY 2.9 orders a year, USD 8; PHK 22.7 orders, USD 127. WIDE: MHD 52.5 orders, USD 89; MQY 57.3, USD 106; PHK 44.9, USD 142. **About USD 135 (deployed) or USD 337 (WIDE) a year.** Median 5–12bp an order; the USD 1 minimum binds on 18–55% of orders. Alpaca charges none | [V] schedule re-read 2026-10-19; [V] trades | `commissions.csv`; Pro Fixed USD 0.005 a share, min 1.00, max 1% (§12as) |
| Borrow at IBKR (f = 1) | today's fees: **0.07%/yr (deployed), 0.33%/yr (WIDE)**; at 2021–22 fees **1.71 / 2.50%/yr** | [V] | §1.6 |
| Market data | **None needed.** NYSE L1 if ever wanted: USD 1.50 a month non-professional, 45.00 professional | [S] §12aa, 2026-10-18 | the IBKR note §2.10 |
| The team lead's time | **52 weekly two-factor logins a year**, plus one after every mid-week Gateway crash or VM reboot (count [U]). Minutes per login [U]. Per event: SPAC elections are manual Client Portal actions at USD 100 each, 53–64 a year at full use [S]. NAV-tender elections are manual too | [V] cycle (§12af); [U] minutes | IBKR "weekly authentication"; SPAC note |
| Engineering | Revive about **4,650 lines** at tag `pre-clean-slate`: adapter 2,144, pending-order guard 241, fills 586, flatten 304, cancel 113, switch 276, borrow fetchers 425, tests 561. Change `decide`/`gate`/`run`/`verify` (3,782 lines today) and prove the Alpaca-only path byte-identical. New `route`, `ibkr`, probe, Flex and deploy units. Hours [U] | [V] `git show … \| wc -l`, `wc -l` | the IBKR note §3–4 |
| The precedent for a new order path here | The Alpaca runner was first committed 2026-09-28. Over the next three weeks it drew **38 non-merge commits** to `quantt/` (29 in `session`/`broker`). In its first 11 eligible sessions, 4 traded nothing and 47% of planned notional was executed | [V] `git log`; [S] ALPHA_LEAKAGE B1 | |
| Operational risk of two brokers | **One-legged days on paper.** The IBKR MOC commits before 15:50; Alpaca's paper leg goes at 15:52–15:58 (R9). **A missed login** leaves IBKR shorts unmanageable and blocks new ones (R1, R13). **Reconciliation** needs a union of positions, two fill sources and Flex (§2.13). **Margin does not cross brokers** (R10). **Settings reset** on an upgrade (R11). **Wash sales** across brokers are ours to compute at live (§2.13) | [S] | the IBKR note §2, §5 |

---

## 4. The arithmetic: when would it pay?

Let:

- **B₁** = the f = 1 gross benefit (§1.4);
- **V₁** = IBKR borrow plus commission at f = 1 (§3);
- **F** = the fixed annual cost (VM resize USD 322 a year, or 0 if the Gateway is
  measured to fit on the existing VM; the team lead's time and engineering are
  left out because they are unmeasured);
- **K** = capital;
- **f** = the share of sessions on which a wanted short is blocked.

By §1.5 the benefit is at most about f·B₁·K, so these are generous.

| scoring | set | B₁ | V₁ | prize at USD 100k, f = 1 | break-even f against a USD 322 resize |
|---|---|---:|---:|---:|---|
| paper (gross; D19/D20 charge no borrow) | deployed | 0.33% | not charged | USD 326 a year | f ≥ 0.99 |
| paper | WIDE | 0.76% | not charged | USD 760 a year | f ≥ 0.42 |
| real money, today's IBKR fees | deployed | 0.33% | 0.21% | USD 118 a year | **never** (f would need 2.7) |
| real money, today's IBKR fees | WIDE | 0.76% | 0.67% | USD 89 a year | **never** (f would need 3.6) |
| real money, 2021–22 fees | either | 0.33–0.76% | ≥ 1.7% borrow alone | **negative** | never |

- **Every prize is a point estimate with t < 0.7.**
- **If the Gateway fits the existing VM (F = 0),** the dollar test passes for any
  f > 0 at today's fees. What is bought is then at most USD 90–120 a year at
  real money, or USD 330–760 on the paper score, for 52 logins a year, a second
  order path and the risks of §3.
- **Real money scales the prize, and the fixed cost stays the same.** At f = 1 and
  today's fees, the dollar test against the resize passes from about **USD
  270k–360k** of capital (F ÷ (B₁ − V₁), arithmetic).
  - The book's closing-auction footprint reaches a 25% median participation at
    about USD 0.43m (`EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md`, [S]).
  - At real money there is a route that needs no second broker. Alpaca has
    offered hard-to-borrow shorting to Trading API users since 2026-06-24: a
    per-share locate plus a daily fee [S, REFERENCES §12t and §12l, [V] there].
  - The locate endpoint "is not available in paper trading", and no per-name
    rate is published [S, §12l]. **So for real money, price that route before
    building IBKR.**

---

## 5. Verdict, triggers and sequencing

**Verdict.**
- **For the core book alone, IBKR does not pay at USD 100k.**
  - After IBKR's own borrow and commissions the prize is USD 90–120 a year at
    f = 1. It never covers the resize.
  - On the gross paper score the prize is USD 330–760 a year at f = 1. It
    would cover the resize only if the names were blocked on more than 42%
    (WIDE) or 99% (deployed) of sessions.
  - Either way it is a point estimate with t < 0.7, bought with 52 logins a
    year and a second order path.
  - The VM resize as specified would also put **the whole book's survival** on
    a credit that lasts about three months.
- The decision is made on the bound, not on the evidence. The evidence cannot
  separate the benefit from zero.

**The binding constraint** is the fixed cost against a sub-USD-1k, t < 1 prize.
Above all it is the student credit: a 4 GiB VM turns a 12-month runway into
about 3 months.

**Triggers. Open the automated IBKR path when one of these fires, not before.**
Each is an event, or a computation re-run at that time (H14). None keys on a
number written here.

1. **E1 commits a PASS verdict,** holdout included, and a live muni deal's
   acquirer reads not lendable at Alpaca and listed at IBKR at the decide (the
   prereg's own routing condition).
   - Build the IBKR leg for E1's pairs.
   - Then decide separately whether the core book's blocked shorts should ride
     on it. Once the account exists, that marginal case is the after-IBKR
     column of §1.4 alone: positive at today's fees, negative at 2021–22's.
2. **The NAV-tender trial commits a PASS** and its live sleeve keeps the approved
   decision 3 default (the muni hedge through MUB at IBKR), rather than a
   ruling to exclude the muni events.
3. **SPAC gate G-SPAC passes and real capital is committed to it.** This needs
   the account and Client Portal only. Elections are manual, so no Gateway is
   needed.
4. **The core book on its own.** Re-run `python3 scripts/ops/ibkr_worth_it.py`
   with a measured f and the IBKR file and Azure price of the day. Open only if
   f̂ × (B̂₁ − V̂₁) × capital exceeds F̂, **and** the team lead judges the
   remainder worth 52 logins a year.
   - f̂ comes from gate-7 skips counted in `send.json`, or from the collector's
     daily flags.
   - For real money, first price Alpaca's live hard-to-borrow locate for the
     same names.
   - Under today's inputs this does not fire at USD 100k.
5. **A v8 proposal to re-admit NAD, NEA, NVG and NZF.** Alpaca has never lent
   them. That is a CEF trial first (`/prereg`, `/spec-change`), and IBKR follows
   only if it passes.

**The cheapest sequencing.**

| step | who | cost | when |
|---|---|---|---|
| S0. **Measure f.** Count the gate-7 skips for `shortable: false` in the VM's `send.json` since 2026-09-29: one read-only pass the team lead authorises (agents do not ssh). Commit the daily flag read the collector would make (the IBKR note's step A5, live-path code, needs a go) | team lead and agent | free | now |
| S1. **Account only, optional.** Individual Pro, USD base, margin. No inactivity fee, USD 0 minimum, USD 2,000 for margin [V]. No VM resize, no Gateway, no code. Worth doing only to take the account approval time ([U], the long pole) off E1's path | team lead | the team lead's time; at least USD 2,000 of their own money parked | when E1's fit verdict is in, or now if the team lead prefers |
| S2. **Build against a stub.** Steps A2–A6 of the IBKR note (no account, nothing transmits) | agent | engineering | when a trigger fires |
| S3. **Measure the Gateway on the existing 1 GiB VM** in shadow (A9): resident memory and swap during a decide | agent and team lead | free | after S2 |
| S4. **Resize only if S3 says so,** and only after the team lead has moved the subscription to pay-as-you-go or accepted the shorter runway | team lead (`!`) | USD 26.86 a month | after S3 |
| Alternative to S2–S4 for E1's few legs: **the team lead enters the pair's MOC orders by hand** in IBKR's own app, from the plan the runner prints. No Gateway and no resize. It costs a manual step per entry and exit, a missed entry is never back-filled (E1 prereg §12), and positions are reconciled from Flex | team lead | a few manual tickets a year | if E1 passes and the team lead prefers it to S2–S4 |

**What would change this verdict:**
- a trigger in the list above;
- **S3 showing the Gateway fits the 1 GiB VM**, which removes the resize and the
  credit risk but not the logins or the second order path;
- **capital** of several hundred thousand dollars, with IBKR fees still near
  today's;
- a measured f with WIDE's B₁ re-run holding up;
- Alpaca's live hard-to-borrow locate turning out unavailable, or dearer than
  IBKR, for these names.

**The downside if this verdict is wrong** (IBKR was worth it):
- The book forgoes at most about USD 330–760 a year on the paper score.
- On blocked days it carries **+0.16 to +0.21 of equity net long** (beta to the
  equal-weight universe about 0.07–0.09), under the live skip rule. That is
  residual, not deliberate, beta (§1.4).
- If E1 passes, the account's approval time delays its start. S1 removes that.

**The downside the other way** (opening and resizing now):
- A resize on the student credit **stops the book** in about three months unless
  billing is changed. That is the one outcome this desk must not risk.
- It adds a second order path with this shop's own record of a three-week
  defect tail (§3).

---

## 6. What was not measured, and the negative results

**Not measured:**
- the 2023+ benefit (the holdout is sealed);
- the actual rate f;
- whether IBKR lends at order time;
- the Gateway's memory on our VM;
- the remaining Azure credit;
- the team lead's minutes per login;
- engineering hours;
- the price of Alpaca's live hard-to-borrow locate;
- HYT as a fourth name. HYT's IBKR fee is 0.47% today. Adding it would enlarge
  B₁ and V₁ by amounts not measured.

**Negative results, recorded against ourselves:**
- **MHD's short has no fit-period evidence on the deployed spec.** Its whole
  value case rests on the WIDE context set.
- **Re-neutralising** a blocked short is not a cheaper substitute for IBKR (§1.4).
- **The paper score would overstate IBKR's value 3–5 times** through the
  distributions it never charges (§1.4).

**A data caveat:** MHD's 2017-06-21 panel close is 3c off the NYSE print
(`results/cef/C5_RESULT_2026-10-14.md` §1). On a weight near 0.1 that is about
2bp once, which is immaterial here.
