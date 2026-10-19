# Merger arbitrage, reconstructed so that what is left is alpha (D4) — 2026-10-19

**What this is.** The team lead's ruling of 2026-10-19 on
`results/events/MERGER_ARB_AND_IBKR_2026-10-15.md` (which found equity merger
arbitrage fails D4: an index of deals earns the deal-spread risk premium, a short
index put), verbatim: *"find a way for us to include this in some shape, maybe
reconstruct with a new angle / logic - this has alpha in it"*. This note looks for
the part of merger arbitrage that is alpha. It names one design worth a
pre-registration, and it records the angles killed and why.

**ZERO TRIALS.** No counter moves (EVENTS stays 0). No price, return, spread or
P&L of any deal was read or computed. Everything below is one of these: a count;
a date; the weekly hazard of deal completion, a statistic of outcome timing; a
borrow fee; a broker flag; a dollar volume; or arithmetic on published numbers.
**Holdouts.** No 2023+ date enters a fit-period table: every deal is censored at
2022-12-30, and `assert_fit_only` raises otherwise. Fees and flags from 2023–26 are
costs, not returns. No `cef_universe.csv` name has a return computed (the E1
section reads fees only), so the 27-name set is not consumed.

**Reproduce every number in §2–§4** (offline; committed inputs and `data/` only;
no credentials, no network):

    python3 scripts/events/merger_arb_v2_feasibility.py --today 2026-10-19
    python3 -m pytest scripts/events/tests/test_merger_arb_v2_feasibility.py

Tables are in `results/events/merger_arb_v2/`. Sources are in `docs/REFERENCES.md`
§12ae. Labels: [V] fetched and read, or reproduced by the named script;
[S] sourced, not re-read; [U] not verified.

**Data as of:**

- **The EDGAR census** (`results/events/merger_arb/edgar_deals.csv`, built
  2026-10-18 by `merger_arb_feasibility.py`): announcements 2009-12-11 → 2026-10-15.
  Only 2010–2022 is used.
- **Pending deals:** Alpaca flags read 2026-10-18; IBKR file `#BOF|2026.10.16`;
  ADV from 63 Alpaca sessions to 2026-10-16 (`pending_deals_2026-10-18.csv`). Each
  is true on its date only (landmine 5).
- **IBKR FEE_RATE panel** (`data/cef/cef_borrow_history.parquet`): to 2026-09-09.
- **Session calendar:** SPY row dates in `data/rv/etf_panel.parquet`, to 2026-10-09.

---

## 0. The answer

1. **The alpha in merger arbitrage that survives D4 is in event time, not in the
   deal premium.** Giglio & Shue (2014) find two things [V, §12ae]:
   - The hazard of a deal *completing* is hump-shaped in the weeks after
     announcement.
   - Holders under-react to the passage of time. Deals therefore earn more in
     their high-hazard weeks than in their low-hazard weeks, **with the same
     factor, downside and option-factor exposures in every window** (their
     Tables 5–7).

   A book that is **long deals in their high-hazard weeks and short deals in their
   low-hazard weeks** does two things. It differences out the deal premium. It
   also differences out the premium's crash kink, which a SPY short cannot do.
   - The published cash-deal betas give this book a market β of about **0.09**
     (0.2975 − 0.2088), inside D4's 0.10.
   - In months the market falls more than 3%, the betas give about **0.01**
     (0.4635 − 0.4518) [V inputs; the arithmetic is mine].

   This is design **MA-HZ** (§2), the only design here worth a pre-registration.
2. **The mechanism's precondition holds in our 2010–22 deals.**
   - Cash one-step mergers almost never complete in weeks 1–8. Their weekly
     completion hazard peaks at **week 13–14**, then decays.
   - The High-window hazard is 2.5–4× the Low-1 hazard: **0.045–0.072 against
     0.016–0.020 a week**, across both failure brackets and on document-dated
     deals [V, `hazard_summary.csv`].
   - But the modern hump comes **earlier than Giglio & Shue's published windows**
     (High = weeks 12–35). So a pre-registration must use a rolling rule fitted on
     earlier deals. It must not use the paper's 1970–2010 cutoffs, nor this note's
     curve, which is in-sample.
3. **D4's alpha leg is where it is likely to fail. That would be a power failure,
   not proof of no alpha.**
   - The alpha t ≥ 3.0 bar on the 2010–22 fit window (12.77 years) needs an
     information ratio (IR) ≥ **0.84**.
   - The paper's own tests imply IRs of **0.18–0.55**, or 0.55–0.77 for small
     deals at an assumed leg correlation [U].
   - That gives **P(pass) 1–15%**, and at most **40%** in the most favourable
     small-deal case.
   - On a census rebuilt from 2001 (21.75 years, needs IR ≥ 0.64) it is
     **2–34%**, or 33–73% for small deals.
   - After the McLean–Pontiff post-publication decay, every case is **≤ 7%**
     [V, `power.csv`].
4. **It can be built at our size, and costs are not decisive.**
   - **Short leg.** Today 16 of 17 pending cash targets in weeks 1–10 are
     shortable at Alpaca. Their IBKR fee median is 0.41%/yr.
   - **Turnover.** The long-High / short-Low cash book turns over **7.8–8.5×** a
     year per unit of gross.
   - **Gross against cost.** The published cash alphas imply **174–414bp/yr** of
     gross per unit of gross. That is **20–53bp per unit of turnover**, against the
     CEF book's 32.6bp breakeven [S].
   - **Sign across the grid.** Net is positive at 5bp and 15bp. At 30bp it is
     positive on the full-sample reading, about +20 to +40bp on the late-sample
     reading, and −60 to −80bp after decay. So it **flips at 30bp** after decay
     [V, `ls_cost_drag.csv`].
5. **E1 (the CEF/BDC merger pair) is dead at IBKR as well as at Alpaca.** The
   muni effect it hedges is +167bp over a 168-session hold [S, E1 gate summary].
   - Acquirer borrow over that hold is **≥ the effect in 6 of 7** measured muni
     merger windows (median window fee 11.55%/yr).
   - At today's median IBKR muni fee (2.84%), the borrow is **196bp**.
   - Only the cheapest name (MQY, 0.83%) leaves room [V, `e1_ibkr_borrow.csv`].
   - The CEF merger lineage is closed at both brokers. The desk's CEF event
     alpha is in NAV tenders (`CEF_CORP_ACTION_CENSUS_2026-10-15.md`), not
     mergers.
6. **Twelve more angles are killed** (§3). These include:
   - the team lead's spread-against-model selection, which needs deal terms we
     cannot read;
   - index flows at closing, where the index effect has disappeared;
   - acquirer short pressure, whose published control out-earns its treatment;
   - post-break rebounds, which fail D7;
   - every option-based route.

---

## 1. What D4 asks of a merger book

**The rule.** D4 on this desk: on the daily P&L of the sleeve sized to the spec's
vol target, **alpha t ≥ 3.0 and every |β| ≤ 0.10** (OLS point estimates, HAC
errors). This is the R-D4 of `results/xasset/PREREG_XASSET_SLATE_2026-10-12.md`.

**Why an index of deals fails.** Mitchell & Pulvino's net-of-cost index has
β 0.12, and β 0.49 in months below −4% [S, §12aa]. A static SPY short zeroes the
average β but keeps the kink. Only long index puts would remove the kink, and the
options ruling does not allow them.

**The deal-spread factor, DEAL.** It is the equal-weighted daily excess return of
**every pending deal** in the same universe, in the same way:

- **Entry and exit:** from announcement + 2 sessions (H1) to resolution.
- **Cash deal:** long the target.
- **Stock deal:** long the target, short h × acquirer, with h = P_T/P_A at entry.
  This hedge ratio needs no reading of terms. It mis-hedges only by the spread
  (a few %).

DEAL is Giglio & Shue's Buy-and-Hold portfolio, and the equal-weighted analogue
of Mitchell & Pulvino's index. It is built from the same CRSP data as the sleeve.

**How β is measured.** Three regressions on the sleeve's P&L:

1. **Daily:** on [MKT − RF, DEAL − RF], with Newey-West errors (the harness's
   `nw_auto_lag`).
2. **Monthly, piecewise:** MKT split at −4% months (Mitchell & Pulvino's kink), to
   give β_down.
3. **Reported only:** the French factors SMB, HML, UMD and short-term reversal.

The Agarwal–Naik option factors that Giglio & Shue use are not in our data [U].

**What passes D4.** A book whose legs carry the **same** DEAL and kink exposure,
so that their difference carries none. Giglio & Shue test exactly this and find
the exposures flat in event time:

- **Their Table 6:** betas regressed on the event-week hazard are insignificant.
- **Their Table 5 Panel B:** High > Low 1 market beta, p 0.12 (cash).

That is the logic of MA-HZ. A selection model that ranks deals by completion
probability has no such guarantee: risky deals carry more DEAL beta (Baker &
Savaşoğlu: returns rise with completion risk [S, §12aa]). Its β-neutral weights
would have to be estimated deal by deal, and they are estimated worst exactly
where it matters, on deals with no history.

---

## 2. Design MA-HZ: event-time hazard, long-High / short-Low, inside the deal cross-section

### 2.1 Mechanism, and who loses

**The mechanism.** After a merger announcement, the probability that the deal
completes *this week* is not constant. It is near zero for the first two months,
while proxies, votes and approvals run. It peaks, then decays for deals still
open, which are the troubled ones. Giglio & Shue find that prices behave as
though holders believed a flatter hazard. They estimate the market's implied
hazard has "approximately 25 percent less variation" than the true one [V]. So:

- in the low-hazard weeks, holders over-estimate completion and are disappointed
  on average;
- in the high-hazard weeks, they under-estimate it and are surprised upward.

**The loser.** In the paper's words, "a subset of investors, possibly small retail
investors, are boundedly rational and generate the mispricing" [V]. They are
holders who do not update on the *absence* of news. Two kinds pay:

- the early-entering arb or holder who pays a near-completion price in week 3;
- the seller who exits in week 15 at a price that does not yet reflect that most
  surviving deals are about to close.

**Why it persists.** It is a limit to arbitrage that the paper measures (Table 8)
[V]:

- **Small cash targets:** High-hazard alpha 113bp/month (s.e. 24).
- **Large cash targets:** 20bp (s.e. 21), not significant.
- **Low-spread deals:** 5bp. **High-spread deals:** 80bp.

Arbitrage capital that must deploy millions per deal cannot harvest small deals;
a $100k–$5m book can (§2.3, capacity). A traditional AP mechanism is irrelevant here: these
are single stocks, and the scarce resource is attention and small-deal capacity.

**Not a stale-price artefact** (graveyard pattern 1). The trade is close-to-close
on the target's own executable price (shift(2)). There is no NAV or mark in it.
Giglio & Shue purge the last-day gap between the last trade and the consideration.
Their cash High-hazard alpha falls to 37bp, and their High > Low test still gives p 0.004 [V].

### 2.2 Where it must be strong, and where it must be absent

**Strong** in small, illiquid, high-spread one-step cash deals. Also strong in
stock deals, but our stock universe is not usable yet (§2.3).

**Absent, the negative control (H12): tender offers.** Their expiry date is
published, so the passage of time is salient. Giglio & Shue exclude them for that
reason: "the information content of the passage of time near and beyond the
expiration date is likely to be obvious to market participants" [V]. Our tender
offers have a completely different clock:

- their hazard peaks at **week 7**;
- only 14–33% of the cash High weeks are above their mean.

The control therefore applies the **same rule** (windows from the prior-data
hazard) to tenders. The mechanism predicts no High − Low spread there.

**Weaker** in large, liquid deals. That gradient is a reported check, not a kill.

### 2.3 Zero-trial measurements

**Universe, announcements 2010-01-01 → 2022-12-31** [V, `universe_by_year.csv`]:

| universe | deals | announcement from a document / from d0 (an upper bound) |
|---|---:|---|
| CASH_1STEP (cash, not a tender) | **1,251** | 863 / 388 |
| STOCK_1STEP (stock, not a tender, acquirer identified) | 256 | 252 / 4 |
| TENDER_CASH (the negative control) | 588 | 497 / 91 |
| excluded: mixed, unsplit, conflict / no acquirer / target registered or ambiguous | 780 / 33 / 81 | |

**The stock universe is conditioned on the outcome. Do not use it as built.**
Among 2010–20 `stock`-class deals, an acquirer was identified for 93.3% of those
that completed (235 of 252), but only 58.3% of those that did not (7 of 12)
[V, `acquirer_identification_bias.csv`]. STOCK_1STEP, which requires an
acquirer, therefore keeps almost no failures: 3 not completed in 2010–20. That
is survivorship. A pre-registration either re-identifies acquirers for failed
deals or runs **cash only**.

**The completion hazard, 2010–22, censored at 2022-12-30** [V,
`hazard_weekly.csv`, `hazard_summary.csv`]. A failed deal has no date in the
census, so two brackets are reported. **A** removes it at its last anchor filing
(early); **B** keeps it to week 52 (late).

| universe | bracket | deals | peak week | mean weekly hazard: GS High weeks | GS Low-1 weeks | GS High weeks above the mean | GS Low weeks below it |
|---|---|---:|---:|---:|---:|---:|---:|
| CASH_1STEP | A | 1,251 | 14 | 0.069 | 0.020 | 67% | 68% |
| CASH_1STEP | B | 1,251 | 14 | 0.045 | 0.018 | 62% | 74% |
| CASH_1STEP, document-dated | A / B | 863 | 13 / 13 | 0.072 / 0.048 | 0.018 / 0.016 | 71% / 67% | 68% / 84% |
| STOCK_1STEP (biased, above) | A / B | 256 | 31 / 31 | 0.071 / 0.068 | 0.009 / 0.009 | 84% / 80% | 93% / 88% |
| TENDER_CASH (control) | A / B | 588 | 7 / 7 | 0.045 / 0.025 | 0.102 / 0.088 | 25% / 29% | 69% / 74% |

**The cash curve in four-week blocks** (bracket A, deals at risk in brackets):

| weeks | 1–4 | 5–8 | 9–12 | 13–16 | 17–20 | 21–24 | 25–28 | 29–32 | 33–36 | 37–40 | 41–44 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hazard (at risk) | 0.001 (1,251) | 0.015 (1,163) | 0.081 (1,035) | 0.103 (704) | 0.084 (444) | 0.050 (306) | 0.062 (247) | 0.044 (190) | 0.059 (158) | 0.062 (123) | 0.045 (92) |

**Reading.** The hump is there, and the precondition holds. But in 2010–22 it
peaks at weeks 9–20 for cash deals, against Giglio & Shue's peak near week 20 and
their High window of weeks 12–35. Their cutoffs would put weeks 9–11 (high
hazard) in Low 1 and weeks 21–35 (decaying) in High.

**This curve is now seen.** A pre-registration cannot pick windows from it; §2.6
item 4 says what it must do instead. Dating by d0 does not explain the early peak:
document-dated deals peak at week 13.

**Breadth: deals in each window at month-ends, 2010–2022** (156 months)
[V, `breadth_monthly.csv`]:

| universe, bracket | Low 1: median (p10–p90) | High: median (p10–p90) | Low 2: median | months with < 5 in High |
|---|---|---|---|---:|
| CASH_1STEP, A | 17 (10–22) | 11 (7–16) | 1 | 5 |
| CASH_1STEP, B | 18 (11.5–24) | 17 (11.5–24) | 4 | 4 |
| STOCK_1STEP, A or B | 5 (1–8.5) | 3 (0–7) | 0 | 112–116 |

Cash has breadth (D7 is not the constraint: 1,251 deals, about 11–17 at a time in
High). The stock leg alone does not.

**Turnover and the cost grid, from dates alone** [V, `turnover.csv`,
`ls_cost_drag.csv`]. Each deal holds one unit while in its window.

- **Free exits.** A completion exits free: the cash is paid, or the target
  converts into the acquirer and closes the short.
- **Paid exits.** A window end or a failure is paid.
- **The High leg** exits free in 615 of 772 positions (bracket A).
- **The Low-1 leg** pays almost every exit (998 of 1,236), because the window
  closes before the deal does.

| book (½ long High, ½ short Low 1 + Low 2) | turns/yr per unit gross | drag at 5 / 15 / 30bp (bp/yr) |
|---|---:|---|
| CASH_1STEP, A | 8.51 | 42.5 / 127.6 / 255.3 |
| CASH_1STEP, B | 7.82 | 39.1 / 117.2 / 234.5 |

**Gross beside the drag.** This is arithmetic on Giglio & Shue's cash alphas, High
minus Low 1, per unit of total gross. It is not our gross:

- **414bp/yr** on the full sample (64 − (−5) bp/month);
- **276** on the late sample (43 − (−3));
- **174** at the 0.42 post-publication keep.

Per unit of turnover that is 49–53 / 32–35 / 20–22bp, against the CEF book's
32.6bp breakeven [S, `CLAUDE.md` order-path rule 3]. **Gross headline positive;
net positive at 5 and 15bp in every case; at 30bp positive on the full and late
readings and negative after decay. The sign flips across the grid under decay.**

Their own cost simulations (Table 9, pooled cash and equity) move the same way
[V]:

| | High alpha | High > Low (p) |
|---|---|---|
| no costs | 91bp/month | 0.0015 |
| after Method 1 (price impact) | 35bp | 0.0000 |
| after Method 2 (bid-ask) | −11bp | 0.0025 |

So the spread survives costs while the absolute alpha may not. Our book is long
**and** short in event time; it does not need the absolute alpha.

**Today's pending deals, by window** (as of 2026-10-16; flags and fees read
2026-10-18) [V, `pending_by_window_2026-10-19.csv`]:

| universe | window | deals | target shortable at Alpaca | target IBKR fee median (max), %/yr | target ADV median | ADV ≥ $2m (fits $100k at 5%) |
|---|---|---:|---|---|---:|---:|
| CASH_1STEP | Low 1 (the short leg) | 17 | **16/17** | 0.41 (25.25) | $29.6m | 17 |
| CASH_1STEP | High (the long leg) | 23 | 14/23 | 0.72 (26.94) | $2.8m | 13 |
| CASH_1STEP | Low 2 (short) | 7 | 3/7 | 0.51 (82.73) | $2.7m | 4 |
| STOCK_1STEP | Low 1 / High | 7 / 4 | 7/7 / 4/4 (acquirers 7/7 / 4/4) | 0.41 / 0.41 | $8.6m / $48.4m | 5 / 4 |
| TENDER_CASH | Low 1 / High | 4 / 3 | 3/4 / 2/3 | 0.50 / 0.37 | $4.2m / $5.5m | 2 / 2 |

The short leg is buildable at Alpaca. IBKR adds little here; the HTB tail (fees up
to 83%) sits in Low 2's stale deals. 89 of the 92 classified pending deals match a census row and take its
announcement date (its document's where one was found); the other 3 use d0.

**Capacity.**

- **$100k book:** 10–20 positions a leg, at $2.5–5k each. Every Low-1 target
  absorbs that in one session at the desk's 5% participation convention, as do
  17 of 23 High targets.
- **$5m book:** $125–250k a position. The small High-leg deals, where the effect
  lives, need several sessions to enter.

So capacity binds in the low millions. That is the same limit that keeps the
effect alive.

**Power: D4's alpha leg** [V, `power.csv`; the arithmetic is
`scripts/xasset/slate_feasibility.py`'s `p_alpha_t`; IR = Φ⁻¹(1 − p)/√years from
each published one-sided test]:

- **Upper bounds.** These treat the whole Sharpe as alpha, so they bound P(D4).
- **Not our sleeve.** A composite test statistic is not our sleeve's IR; the
  figures show what the published evidence can support.
- **The window.** It starts at the first P&L a week-12 position can earn under
  H1. On the 2010 census that is 2010-03-24, giving 3,217 sessions (12.77 yr) to
  2022-12-30.

| published input (Giglio & Shue) | IR | P(α t ≥ 3), 2010–22 (needs 0.84) | P(α t ≥ 3), 2001–22 (needs 0.64) | P after ×0.42 decay, 2010 / 2001 |
|---|---:|---:|---:|---|
| cash, High > Low, 1970–2010 (Table 3, p 0.0084) | 0.37 | 0.048 | 0.104 | 0.007 / 0.012 |
| equity, High > Low, 1970–2010 (Table 3, p 0.0002) | 0.55 | 0.153 | 0.337 | 0.015 / 0.028 |
| cash, High > Low, 1991–2010, early cutoffs (Table 4A, p 0.2077) | 0.18 | 0.009 | 0.016 | 0.003 / 0.004 |
| cash + equity, 1991–2010 (Table 4A, p 0.0271) | 0.43 | 0.072 | 0.161 | 0.009 / 0.016 |
| cash, small targets, High − Low 1 (Table 8), legs ρ = 0 [U] | 0.55 | 0.149 | 0.329 | 0.015 / 0.027 |
| the same, ρ = 0.5 [U] | 0.77 | 0.405 | 0.726 | 0.033 / 0.069 |

**What this means, stated before anything runs** (the XASSET convention):

- **2010 census:** at every published reading P(pass) is below one half. The
  late-sample cash reading, the one closest to our era, gives 1%.
- **What a fail would say.** It would not distinguish "no alpha" from "13 years
  cannot show it".
- **What a pass would say.** It would be informative.
- **The DSR bar is not the binding constraint.** The EVENTS deflated-Sharpe bar at
  N = 1 needs only SR 0.46 (2010) or 0.35 (2001).
- **The 2001 census** is a data build of zero trials (§2.6). It roughly doubles
  P(pass). But 2001–10 sits inside Giglio & Shue's own sample, so only 2011–22 is
  new evidence.

### 2.3b D1–D7 pre-screen (before any trial)

| code | reading for MA-HZ | evidence |
|---|---|---|
| D1 | not tested here; the published High > Low tests pass at 1970–2010 and, for cash, not at 1991–2010 (p 0.21) | Giglio & Shue Tables 3, 4A [V] |
| D2 | live risk: net positive at 5 and 15bp; at 30bp negative under the post-publication keep | `ls_cost_drag.csv` [V]; Table 9 [V] |
| D3 | live risk: published 2013; the modern cash hump peaks earlier than the paper's windows | `hazard_summary.csv` [V] |
| D4 | β legs pass by construction on the published betas (0.09 linear, 0.01 down; SPY overlay for the first); **the alpha leg is power-limited** | Tables 5–7 [V]; `power.csv` [V] |
| D5 | if it passed all else at the published IRs (about 0.2–0.55), it would be inventory | — |
| D6 | not a regime sleeve; breadth is steady (cash High leg 7–16 deals at the 10th–90th percentile of month-ends, bracket A) | `breadth_monthly.csv` [V] |
| D7 | not binding on deals (1,251 cash one-step); 156 fit months; binding only for the stock leg | `universe_by_year.csv`, `breadth_monthly.csv` [V] |

### 2.4 Construction (for the pre-registration to fix, not here)

**Book.** Cash one-step deals; equal weight within each leg; long High, short
Low 1 ∪ Low 2; dollar-neutral.

**Hedge.** A SPY overlay sized by a market β estimated on prior data only. The
published linear β of 0.09 is too close to 0.10 to leave unhedged. SPY was
shortable and ETB on 2026-10-12 [S, §12r].

**Windows.** From the completion hazard estimated each month on deals resolved
**strictly before** that month: expanding, with the paper's above/below-the-mean
rule, the cutoff week left out, and a 2001–09 burn-in.

**Returns.** Cash deals need no deal terms: the position is the target. That
sidesteps the reading problem that killed the earlier note's term reader (0 of 16
deals read right). Returns come from CRSP total returns.

**Harness.** Targets go through `band_frontier.evaluate()` (shift(2)); no new
backtester. Cost grid 5/15/30bp beside gross, with a measured column: CRSP's
closing bid/ask half-spread per target per day, the fit period only. Borrow on
the short leg is charged from IBKR FEE_RATE where it exists (2021-09 on);
otherwise it is labelled an assumption (H4).

**Exits.** Giglio & Shue exit a deal whose target trades above the offer. We
cannot without terms, so a pre-registered deviation keeps it.

### 2.5 What would falsify it (the trial's kill list, in order)

| # | stage | kill if |
|---|---|---|
| K1 | mechanism | the rolling hazard's High-window mean is not above its Low-window mean (it is above here: 0.045–0.072 against 0.016–0.020, but the trial re-measures it) |
| K2 | D1 | the L/S gross alpha on [MKT, DEAL] ≤ 0, or its HAC t < 1.96 |
| K3 | H12 control | the same rule on **TENDER_CASH** earns ≥ ½ of the one-step L/S gross |
| K4 | D4 | alpha t < 3.0, or any of \|β_MKT\|, \|β_DEAL\|, \|β_MKT,down\| (MKT < −4% months) > 0.10 |
| K5 | bar | `_dsr` < 0.95 at EVENTS N = 1 |
| K6 | D2 (label, as C4) | net ≤ 0 at 15bp on the measured-spread column, or a sign flip across 5/15/30 |
| K7 | gradient (report) | an effect concentrated in large deals contradicts the limits-to-arbitrage story; written up, not a kill |
| K8 | holdout | 2023-01-01 → opened once, after K1–K6; the fit's sign must hold |

**Trial cost.** EVENTS 0 → 1. The design cannot close itself on a derived budget
of zero, but §2.6 item 1 can close it before the trial.

### 2.6 What a pre-registration would need from the team lead

1. **A zero-trial data build, run with the team lead's R2 access** (agents do not
   load `config/.env`). It needs:
   - CRSP daily `ret`, `prc`, bid/ask and `shrout` for the census targets,
     2001–2022;
   - the EDGAR census extended to 2001, with the same rules, and failure dates
     read from target 8-K item 1.02 bodies;
   - SPY and the French factors.

   **Cheapest kill, still zero trials.** Measured half-spread × this note's
   turnover against the late-sample gross. If the measured drag reaches the gross
   implied by the published late-sample alphas, D2 is predicted and the trial
   should not be spent. Re-measured at run time, never keyed on this note (H14).
2. **Accept the power.** On a 2010 census, P(D4 pass) is about 1–15% at the
   published effect. On a 2001 census it is 2–34%, or up to 73% at the most
   favourable small-deal reading. A fail is not informative.
3. **Rule on the fit window.** D4 on 2001–22 for power, plus a pre-declared
   condition on 2011–22 alone, after the paper's sample: the fit's sign, and at
   least 0.42× the 2001–10 estimate.
4. **Rule on the window rule.** It must be the rolling prior-data hazard, not
   Giglio & Shue's cutoffs. This note has seen the 2010–22 curve, which peaks
   earlier than theirs.
5. **Rule on the universe.** Cash only (recommended), unless the stock universe's
   outcome bias is fixed first. Then choose either all one-step cash deals, or
   the paper's small half (within-year median target size): more power and higher
   cost. One primary, declared.
6. **Broker.** None new. The short leg is Alpaca-shortable today. IBKR is not
   needed for MA-HZ.

---

## 3. Angles killed, and why

| angle | who would lose | graveyard check | verdict and the number that decides it |
|---|---|---|---|
| **(i) Spread-implied against modelled completion** (regulatory status, second request, financing, hostile, collar, acquirer type), long rich-probability / short poor | arbs who price risk with a cruder model | new | **Infeasible (D7 for want of reading), and no β-neutral guarantee.** The implied probability needs the offer terms. The regex reader was right on all fields for 0 of 16 deals and on none of 12 outside dates; second requests and financing are in prose [S, §12aa]. A fitted completion model over about 1,250 deals is a model-selection trial. DEAL β rises with risk (Baker & Savaşoğlu), so neutrality needs per-deal β estimates on deals with no history. Its one machine-observable, published, β-flat special case is event time: MA-HZ |
| (i-b) Small deals long, a merger ETF short | none | S3-wrapper pattern | **D4 in costume.** It is the small-deal premium (cash B&H small 69bp against large 0bp a month, Table 8 [V]); DEAL β about 1 |
| **(ii-a) Index deletion / addition at closing** | index funds that must trade at the close | S3-forced-flow (WATCH) family | **D3 and no data.** A cash target is held to delisting and paid in cash, so there is no forced trade. The stock "hidden addition" run-up was 3.36% (t 5.20, N 166) in 1994–2000 (MPS Table IV [V]). But the S&P addition effect fell from 7.6% in the 1990s to **0.8%** in 2010–20 (Greenwood & Sammon [V]). The repo has no index-membership history |
| **(ii-b) Acquirer short pressure** (be long the stock-deal acquirer the arbs short) | arbs paying for immediacy | "short-pressure" (D1); graveyard pattern 2 | **Loses to its own control on the published numbers.** Fixed-ratio stock acquirers fall 2.73% at announcement (t −10.57) but finish [A−20, C+20] at +0.41% (t 0.38). **Cash** acquirers, which arbs do not short, finish at **+5.58% (t 4.92)** (MPS Table II [V]). The control out-earns the treatment |
| (ii-c) Floating-ratio pricing-period pressure | arbs shorting daily in the pricing period | — | **D7, and pricing dates need reading.** −3.18% (t −2.79) then +2.53% (t 2.09), **N = 59** in seven years (MPS [V]) |
| (ii-d) Completion against the announced timeline | holders anchored on "expected to close in Qx" | — | **Reading-bound.** Giglio & Shue's lawyers judge projected dates of "limited informativeness" [V]. It is MA-HZ with a deal-specific clock: an upgrade once a verified reader exists, not a second design |
| (ii-e) Post-break rebound (arbs forced to dump) | arbs over risk limits | S3-forced-flow family | **D7, and the D4 set would need short-term reversal.** At most **218** not-completed cash one-step and tender deals were announced 2010–20, about 20 a year, and that bucket also holds survivors [V, `not_completed_by_year.csv`]. Failure dates are not in the census. A rebound is short-term reversal, a known factor |
| (ii-f) Timing the deal factor by arbitrage capital (spreads blow out in crashes) | arbs forced out | — | **D4 by definition.** It times DEAL itself |
| **(iii-a) E1 at IBKR** (long muni target, short acquirer) | target retail holders; arbs pay the lenders | E1 lineage (G1a, ETF gate) | **D2 by borrow** [V, `e1_ibkr_borrow.csv`]. Muni effect +167bp over 168 sessions (243.5 calendar days) [S, E1 gate summary]. Borrow over the hold is ≥ the effect in **6 of 7** windows; the window-mean fee median is 11.55%. At today's median IBKR fee (2.84%) it is **196bp**; only MQY (0.83%, 57bp) leaves room. The acquirer is not always the expensive one: MQY and MHD paid less during their windows (4.53%, 3.19%) than in the 120 sessions before (14.17%, 6.26%) |
| (iii-b) E1 hedged with a basket of uncrowded CEFs at IBKR | — | E1 ETF gate | **Killed by the ETF gate's own logic.** Outside the deal, the residual is the target's discount, about 650–790bp against an effect dispersion of 336bp [S, `E1_ETF_HEDGE_GATE_2026-10-15.md`]. A basket does not carry the acquirer's NAV tie |
| (iii-c) BDC NAV-for-NAV mergers | — | — | **D7**: 3 deals in the 2010–22 CRSP sample [S, EDGAR events §3] |
| (iii-d) CEF acquirer discount pressure | arbs short the acquirer | — | **No mechanism evidence, and D7.** Window fees are not systematically above pre-window fees (above). The live book's longs in acquirer windows lost 103bp over 4 windows [S, EDGAR events §4] |
| (x) Option-implied completion odds (Van Tassel) | — | options closed except one short-premium test | **Out of bounds**: no single-name option data, and paid options data is ruled out |

---

## 4. What this note saw, and gaps

**Seen** (so a pre-registration cannot choose from it):

- the 2010–22 completion-hazard curves for cash, stock and tender deals;
- not-completed counts by year to 2020;
- no price, return or spread of any deal.

**Gaps:**

- **Failure dates.** They are bracketed (A/B), not read.
- **Stock universe.** Its outcome bias is measured, not fixed.
- **Giglio & Shue's equity windows** are by analogy [U].
- **Small-deal ρ.** The leg correlation for the small-deal IR is assumed [U].
- **Composite tests.** Their test statistics are not our sleeve's IR.
- **Table 4 assignment.** The assignment of the late High > Buy&Hold p (0.12055)
  to Table 4 Panel A is read from a garbled text layout [S]. It feeds one power
  row only.
- **Breakeven.** The 32.6bp breakeven is the CEF book's [S]. Large targets cost
  less and small ones more; CRSP bid/ask will measure it.
- **Our E1 effect is pre-2023, and its fees are 2021–26:** the periods differ.
