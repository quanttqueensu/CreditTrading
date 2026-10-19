# Pre-registration — NAV tenders: buy after the announcement, tender every share, hedge NAV beta with an ETF

**Date** 2026-10-19 · **Counter** EVENTS, one trial; its number is set by the
order in which the team lead approves this and the parallel E1 merger-pair draft
(EVENTS stands at 0) · **Pass bar** `scripts/cef/validate.py::_dsr` > 0.95 at the
EVENTS N of decision 1 (default N = 6, the E1 draft's N) · **Admitted by**
`results/events/CEF_CORP_ACTION_CENSUS_2026-10-15.md` (gates NT-a…e, all pass;
`docs/REFERENCES.md` §12ab) · **Ruling** team lead, 2026-10-19: draft the
NAV-tender pre-registration today · **Author** research agent, branch
`research-navtender-prereg`

> **DRAFT — awaiting team-lead approval; the counter moves only in the commit that records approval.**
>
> **Nothing has run.** No return, P&L, spread, discount, beta or Sharpe of any
> tender fund or hedge was computed to write this, and no CRSP table was read.
> The only measurements are:
>
> - counts of events, groups and flags from tracked EDGAR-derived tables (the
>   census's per-event file, the fetcher's episode table, the N1 census);
> - the hedge ETFs' Alpaca flags already in the census summary (read
>   2026-10-18T22:33Z), and six rows of IBKR's public shortstock file (stamp
>   `#BOF|2026.10.19|10:59:08`);
> - arithmetic on the bar (`validate._dsr`, inverted) and on stated,
>   labelled assumptions.
>
> Reproducer: `python3 scripts/events/nav_tender_feasibility.py --ibkr <copy of
> usa.txt>`, run 2026-10-19, output
> `results/events/nav_tender_feasibility_2026-10-19.txt`; tests in
> `scripts/events/tests/test_nav_tender_feasibility.py`. This commit moves no
> counter, changes no spec and touches nothing on the order path.

---

## 0. The declaration in one table

| item | declared |
|---|---|
| what is tested | after a fund announces an issuer tender at k% of NAV, **buy it at the close of day 0 + 1, tender every share, take k% × NAV on the accepted fraction, sell the returned residual** once the result is public and the shares are back; short the asset-class ETF by the fund's pre-event beta for the whole hold |
| events | the census's `nav_tender` rule, unchanged (listed common shares, price stated as "k% of net asset value"); the 44 `cef_universe.csv` funds excluded; a fund with a merger episode open at day 0 excluded (§1) |
| the timestamp | `observed_at` of the day-0 filing = max(the SEC header's `ACCEPTANCE-DATETIME`, 06:00 ET on EDGAR's filing date); day 0 = the first NYSE session whose 22:00 ET decision is at or after it (§4) |
| fit | day 0 ≥ 2010-01-01 and last P&L session ≤ 2022-12-30: **138 events, 123 groups by today's proxy dates; 134 and 120 without the merger-open events** (§11) |
| holdout | day 0 ≥ 2023-01-01 and last P&L session ≤ 2024-12-31 (CRSP's end): **32 events, 21 groups** by proxy. Opened once, after the fit verdict is committed |
| headline | **gross**: the per-event mean P&L (clustered by sponsor × day 0) and the tradable sleeve's annualised Sharpe; net at 5 / 15 / 30bp beside it, labelled; borrow and the election fee charged separately, labelled |
| named control | **placebo dates**: the same funds, hedges and hold lengths at dates with no tender (§8) |
| report-only twin | **the no-tender exit**: same entries, sold at the close before pricing, never elected. It splits the result into the announcement drift and the tender's own payoff (§2) |
| kills | D1 (cluster t < 2; placebo p95), D2 (net at 15bp not significant: the graveyard's bar), D4 (alpha t < 3.0 or any \|β\| > 0.10), D3 (holdout signs) |
| pass | every kill survived, `_dsr` > 0.95 at N, and both holdout signs positive |

### 0.1 Divergences from the census, stated up front

The census measured TERMS and LEVELS; this trial measures realised returns. It
departs from the census in these ways, each deliberately:

1. **The residual is marked to market, not valued at entry.** The census's
   +2.14% (median, n 97 [V there]) assumes the unaccepted 68.5% is worth what
   it cost. Here the residual is held through the lock-up and sold at the
   close of F + 1 (§5.3), so whatever the discount gives back is in the P&L.
   The census's own give-back sensitivity was +1.14% (n 79 [V there]).
2. **Each event's own pro-ration, never the median.** The census multiplied
   every slice by the median 0.315. Here π is the event's outcome, read from
   its results filing (§4.3). Nothing about π is estimated or used in sizing.
3. **Entry is later.** The census's `disc_post` compared an offer-stated NAV
   with CRSP's close on the same day. Here the decision is at 22:00 ET on day 0
   and the fill at the close of day 0 + 1 (H1). Day 0 is taken from the SEC
   header time, and for a discount programme it is moved to the filing that
   announces the triggered tender (§4.2). Both can only make day 0 later than
   the census's `ann_date`.
4. **The whole fit sample, not the 97 with a NAV level.** The trial needs no
   NAV level, so every fit event with an outcome and CRSP prices enters. The
   census's level subset is used only for the report-only mechanism slope.
5. **The hedge is costed and its route widened.** The census named an ETF and
   charged nothing for it. Here the hedge ratio is estimated (§5.2); the grid is
   charged on the hedge legs too; borrow is labelled. Availability counts
   Alpaca **or** IBKR's public file (ruling of 2026-10-19), which hedges the
   muni events through MUB at IBKR instead of leaving them unhedgeable (decision 3).
6. **Costs on every leg, plus a fixed election fee.** The census charged
   1.68 fund-leg units at 30bp. Here the grid is charged on every traded unit
   (§6), and Alpaca's $100 per election is a separate labelled line (decision 4).
7. **Periods by the last P&L session, not the announcement year.** An event
   announced in 2022 whose hold ends in 2023 is in neither period (1 such event).
8. **Merger-open events are out** (4 in the fit): they belong to E1's sample,
   and the two samples must be disjoint (§1).

---

## 1. What is tested, what is not, and the neighbours

**Tested:** whether buying a closed-end fund after its NAV tender is announced,
tendering every share and hedging its NAV beta earns a positive, significant
gross P&L per event that survives costs, is not factor exposure, and holds out
of sample. A pass makes the sleeve a candidate inside the CEF account (portfolio
framework §2.1). It would then need its own frozen-spec file, its H11 statistic
(§14), the real-money cost gate, a release and a team-lead go.

**Not tested:**

- **Pre-trigger windows of discount programmes (N1).**
  `results/events/CONDITIONAL_TENDER_CENSUS_2026-10-13.md` asked whether the
  market prices the probability that a programme's average discount will cross
  its threshold. It failed its own gate (G-N1b: 16 usable clusters; G-N1c: only
  2 non-triggers): D7, folded into C1 as hygiene, no trial. **This trial never
  holds a fund during a measurement window.** Its day 0 for a programme tender
  is the filing that announces the triggered tender, after the window has ended
  (DG-NT-1). In the fit, 26 events follow a triggered N1 window by at most 180
  days; they are a reported stratum. N1's finding that programme tenders are
  small and heavily pro-rated (median factor 9.93% [V there]) is expected to
  show in that stratum.
- **Merger-pair events (E1).** A fund with a merger episode open at day 0 is
  excluded and counted (4 fit events). A tender conditional on a merger vote
  (CXH 2026, §12k) falls in that exclusion.
- **Fixed-price and Dutch tenders** (15 events, mostly BDCs; census row 6).
- **Odd-lot priority.** Rule 13e-4(f)(3)(i) lets an issuer accept holders of
  fewer than 100 shares before pro-rating others [V, §12ai]. Positions that
  small cannot carry a $100 election fee.
- **Shorting the fund against the residual.** Rule 14e-4 makes it unlawful to
  tender in a partial tender offer unless the holder is net long the amount
  tendered "at the time of tender, and at the end of the proration period"
  [V text, §12ai]. Most of these funds cannot be borrowed anyway (G1a).
- **The 44 `cef_universe.csv` funds** (8 NAV tenders). **The 27-name holdout
  (H9) is not consumed.** The trial script asserts, by ticker and by CRSP
  permno, that no traded name is in `data/cef/cef_universe.csv`, as
  `e1_etf_hedge_gate.assert_no_universe` does. The parallel E1 draft proposes
  to consume H9; decision 12 records why that costs this trial nothing.

---

## 2. What is traded, and why participation

### 2.1 The choice

Two trades were possible around an announced tender:

- **(A) Tender participation.** Buy after the announcement, tender every share,
  receive k% × NAV on the accepted fraction π, sell the residual 1 − π after
  the result.
- **(B) The discount around the tender.** Buy after the announcement, sell
  before expiry, never tender.

**A is the trial; B is reported beside it and decides nothing.** The reasons:

1. **Only A has a contractual exit above the market.** The fund's own bid at
   k% of NAV on π of the shares is the "known level on a known date" of
   mechanism M6 (`docs/BRIEF.md` §2). The census's five gates passed on exactly
   that payoff, π × (k × NAV ÷ price − 1). No gate covers B.
2. **B has no terms-implied value at all.** Its edge would be a price path,
   the drift between the announcement and expiry. The nearest evidence is ICI's
   excess-discount path in activist-forced tenders, −1.2% before the tender to
   −0.2% during it [V, §5]. That is an average against peers, not a tradable
   return.
3. **A contains B.** A's P&L is B's (entry to the close before pricing) plus
   the tender's own contribution: the pricing-day jump on π, and the residual's
   path through the lock-up. Reporting B on the same entries splits the result
   at no extra trial. It answers the literature's question, whether tendering
   itself still pays (§2.3).
4. **B cannot be promoted from this trial.** If B is where the money is, a
   B-sleeve is its own pre-registration and its own trial, informed by this
   one's report-only row. That is stated now so the B row cannot be adopted
   after it has been seen.

**What A costs that B does not** (all in §3 and §6): a $100 election fee at
Alpaca; tendered shares locked from election until returned; Alpaca paper's
handling of a voluntary election is undocumented, so paper cannot confirm the
tender leg; and Rule 14e-4 rules out pre-selling the residual.

### 2.2 Pro-ration risk

- **π is unknown at entry and is not estimated.** The census's median is 0.315
  (114 events, 105 groups [V there]). It runs from about 0.1 for programme
  tenders (N1) to 1.0 for offers for all shares (10 fit offers are for at least
  50% of shares). Sizing never uses an estimate of π, so a miscalibrated
  pro-ration forecast cannot be sized into a position (portfolio framework §1.3).
- **The residual is the main risk, and the trial takes it deliberately.** It is
  locked from election until returned. It cannot be sold forward or hedged
  against the fund's own discount (Rule 14e-4; borrow). ICI's path says the
  discount tends to widen back after a tender (−0.2% during, −3.3% the year
  after [V, §5]). And the ETF hedge removes NAV beta, not discount: in the E1
  gate, half or more of a muni CEF's price residual over a hold was discount
  that no ETF carries [V there].
- **It is measured, not assumed.** Each event's residual tail (from the
  pricing session to F + 1) is reported per event and by era. A withdrawn or
  terminated offer is π = 0, with the whole position sold after the
  termination is public (§5.3).

### 2.3 Mechanism, who is on the other side, and the graveyard

**Mechanism.** A fund offers to buy a slice of its shares at close to NAV, while
the market price sits at a discount. Holders who tender get the slice at
k% × NAV; holders who do not tender, or who sell before expiry, leave it to
those who do. The arbitrageur is paid for holding the position through the
offer and for carrying the residual afterwards.

**Who is on the other side:** inattentive or constrained retail holders who do
not tender; holders who sell after the announcement to anyone who will take the
shares; and, after the tender, holders who sell the residual into a widening
discount [U: none of these is measured here].

**What is already known, stated against ourselves:**

- **Kadapakkam, Zhang & Yildirim** (RQFA 56(4):1475–1501, 2021; DOI
  10.1007/s11156-020-00935-4 [V abstract, §12ai and §12v]): for 2000–15,
  "abnormal profits from tendering have disappeared" in stock repurchase
  tenders. In closed-end fund tenders the profit is about 0.5%, and "these
  profits are no longer significant after adjustments for transaction costs".
  This is the census's graveyard bar ("tender capture alone: about 0.5% gross,
  not significant net, 2000–15", `SCALING_RESEARCH_2026-10-08.md` §3). The §12ab
  row asked for the primary source before a pre-registration quoted it. It was
  already in §12v; §12ai re-reads it. **Which entry window the paper uses for
  CEFs is not in the abstract [U].** The classic design (Lakonishok &
  Vermaelen 1990, §12v) buys shortly before expiry. So the report-only
  late-entry row (§10) is the like-for-like comparison.
- **The terms bound the answer from above.** +2.14% if the residual holds its
  value; +1.14% if it gives the announcement narrowing back [V there, levels
  only].

**Graveyard** (`/graveyard`, `docs/RESEARCH_STATE.md` KILLED, WATCH, CLOSED):

| dead or closed | how this differs, and the risk that remains |
|---|---|
| "tender capture alone" (SCALING §3, do not build) | The same family. The trial differs in entry (announcement + 1, not the eve of expiry), sample (2010–22, every listed NAV tender) and hedge. **Its bar is that paper's finding**: stage 3 requires the net per-event mean to be significant at 15bp, which the paper did not find (decision 5) |
| N1 conditional tenders (D7, no trial) | Never holds a fund inside a measurement window (§1) |
| E1-G1a and the E1 ETF-hedge gate (FAIL) | The same hedge weakness (discount residual), but here the discount is the bet, not the noise. In E1 the ETF replaced the acquirer short that carried the NAV-ratio tie; here no fund short exists to replace |
| the stale-price pattern (six of thirteen deaths) | P&L on CRSP closes under shift(2); entry and exit sessions with no closing trade are listed (§4.4) and reported without them |
| a control scoring as well as the treatment | The placebo dates are a kill (§8) |
| S3-forced-flow (WATCH, D6) | A different family: pressure from index rules, not an offer price |

---

## 3. Divergences from the backtest, stated up front

Everything a live sleeve would do that this trial does not:

1. **Paper cannot confirm the tender leg.** Alpaca's paper page lists what
   paper does not simulate and says nothing about corporate actions [V page;
   U what paper does with an election, §12ac]. The phase-3 "no probe orders"
   ruling (2026-09-28) rules out finding out by testing. A paper sleeve can
   hold and sell; whether it can tender is unknown. Paper also credits no
   distributions and charges no borrow (CLAUDE.md landmine 1). Decision 10.
2. **The election fee.** Alpaca charges "$100 per unique election" (fee
   schedule revised 2026-10-12 [V, §12ac]). IBKR's fee was not read: its
   corporate-action page returned HTTP 403 [U, §12ai].
3. **The election cut-off.** A broker's deadline comes before the offer's.
   Alpaca's lead time is not documented [U]. The trial assumes **3 sessions
   before expiry** (decision 6); an event whose entry fill would be later is not
   traded, and is counted.
4. **The lock-up.** Tendered shares cannot be sold until they are returned.
   Rule 13e-4(f)(5) says only "promptly" [V]. At Alpaca, cash for elected
   shares is booked "normally a week or two after the client's election" [V,
   §12ac]; the return of unaccepted shares is not documented [U]. The trial
   assumes the residual can be sold no earlier than **5 sessions after
   pricing** (decision 6).
5. **The cash from the accepted slice** earns nothing in the trial, and the
   house's weight convention charges no financing either.
6. **Day 0 from EDGAR.** A press release can precede the filing. Alpaca's news
   had no article on any CEF tender in the 36-event engine sample (§12z [V]).
   The backtest can only know less than a live reader of the wire.
7. **The hedge's availability is a snapshot.** Alpaca's flags and IBKR's file
   on one date are applied to 2010–24 (landmine 5). **The muni hedge is
   at IBKR**, which is a second account, against the 2026-10-09 ruling that
   sleeves run in one account. Decision 3.
8. **Whole shares and capacity.** Median pre-announcement ADV is $0.42m (n 137
   [V there]). A sized event at $100k capital is a large share of one close.
   The trial is capital-free (weights); capacity is reported (§10).
9. **Execution.** Paper runs `late_market` day orders 15:52–15:58 ET, not MOC
   (CLAUDE.md order rule 3). Some funds trade on NYSE American or Nasdaq; their
   auction-print line needs plan item 0.2.
10. **The account's gross cap** is shared with the CEF book live; here the
    sleeve is capped alone (§5.4).
11. **Recall.** The census's tender filter keeps listed common-share offers
    whose text states "% of net asset value". 10 offers with no price basis are
    out, and recall is not measured [U there].

---

## 4. The event, its timestamp, and the data

### 4.1 The event set

- `scripts/events/cef_corp_action_census.py::tender_events`, unchanged:
  - the fetcher's tender episodes from 2010;
  - the first SC TO-I's cover-page class must be common;
  - the offer must state that the shares are exchange-listed;
  - the price basis is the mode of "k% of net asset value".
- 206 events; 8 on the 44; 198 outside (census; re-counted 2026-10-19 [V]).
- **One position per fund.** If a second tender on the same fund is announced
  while the first is live, the second is not entered, and is counted.

### 4.2 The timestamp (the no-lookahead key)

The rules already on main, applied unchanged:

- **Acceptance comes from the submission header's `ACCEPTANCE-DATETIME`**
  (Eastern wall-clock time), never the submissions API's
  `acceptanceDateTime`. The API value was one UTC offset late on 23 of 50
  sampled filings (§12z [V]), and on 120 of 260 filings of the 13 deployed
  names (§12j correction; `results/events/edgar_acceptance_offsets/` [V]).
- **`observed_at = max(acceptance, 06:00 ET on EDGAR's filing date)`**
  (`scripts/events/event_store.py::observed_at`). EDGAR disseminates a
  non-ownership filing accepted after 17:30 ET on the next business day, and
  dates it then (§12z [V]). Seven of the engine's 50 sample filings would
  otherwise reach a 22:00 decision 8–56 hours before publication.
- **Day 0 is the first NYSE session t with `research_decision_time(t)`
  (22:00 ET on t) ≥ `observed_at`.** For research this equals EDGAR's filing
  date when that date is a session.
- **A decision at t's close keyed on the filing date would leak.** 29 of the
  50 sample filings were accepted between 16:00 and 17:30 on their own filing
  date (§12z). No consumer here acts before 22:00 ET.

**Which filing is day 0 (DG-NT-1).** It is the first filing of the tender
episode that announces a **definite** tender by this fund: an SC TO-C or SC TO-I,
or an SC TO-I/A where that is the first. That holds whether or not the price
and size are final; the offer's ordinary conditions may still apply. A filing
that announces a **programme** is not day 0 when its tender depends on a future
discount average, a future vote or a board's later discretion. Where the
episode opens with such a filing, day 0 moves to the first filing that announces
the triggered or decided tender. Each re-dating is recorded with its span. In
the fit, 25 events have an offer document more than 60 days after day 0, and 26
follow a triggered N1 window: Stage 0 reads both sets first.

### 4.3 Terms and outcomes (DG-NT-2)

From the offer and its last amendments, with spans, using the census's readers
(`parse_tender_offer`, `parse_tender_result`, and the fund-anchoring rule for
joint releases):

- the final expiration, after any extension;
- the **pricing session** X_p, the date whose NAV sets the price (the offer's
  terms; the expiry if not stated otherwise);
- the **final purchase price per share** P_final from the results filing;
- **π = accepted ÷ tendered**, with the census's second method beside it
  (offer size ÷ % of outstanding tendered; 38 of 38 agreed within 0.05 [V
  there]). Where only the second method exists, it is used, and labelled;
- the **outcome**: completed, or terminated/withdrawn (π = 0), or unread;
- the `observed_at` of the filing that reports the outcome.

**An event with an unread outcome or an unread P_final is excluded and
counted.** If more than **20%** of fit events are excluded this way, the run
halts before any return is computed, no trial is spent, and the list goes to the
team lead. The reason: exclusion conditioned on a missing results filing can
correlate with the outcome. Today 110 of the 134 eligible fit events have π read
(82%; proxy), so the gate is close and Stage 0's reading matters.

### 4.4 Prices, the hedge universe and factors

| gate | what | done when |
|---|---|---|
| **DG-NT-3** | CRSP `ret` (total return) and `dsedelist.dlret` for each fund's permno (the census's `CrspMap`) and each hedge ETF, from the start of the β window to F + 1. The **fit reader refuses any 2023+ row** (`crsp_events.daily`'s guard). The holdout reader is a separate function that runs only after the fit verdict's commit exists. A NaN `ret` inside a hold is allowed only where CRSP's next valid `ret` bridges it (`merger_pairs.bridging_check`, at most 10 missing days); it is then written as 0 explicitly and counted. Anything else raises | every fit event priced, or excluded and counted |
| **DG-NT-4** | Hedge availability on one date: Alpaca `GET /v2/assets/{symbol}` (read-only, cef paper key) and IBKR's public `usa.txt`, read the same day, with their stamps; the route rule of §5.2; IBKR fees recorded for the borrow line | every class has a route or is excluded and counted |
| **DG-NT-5** | French FF5 + UMD daily (`scripts/data/fetch_ff_factors.py`, vintage recorded); TERM = IEF − RF, HY = HYG − IEF, MUNI = MUB − IEF from CRSP | covers 2009-01 → 2024-12-31 |
| **DG-NT-6** | `compute.use_numexpr` off at import, and an assertion that no P&L is denormal-like (`scripts/events/numexpr_fault.py`) | the assertion passes |

**Quality screen** at Stage 0. Listed by event, never altered by the trial
script, and reported as a robustness row without the listed events:

- a daily `ret` with |r| > 50%;
- CRSP `prc` < 0 (no closing trade) on the entry session or on F + 1;
- an episode whose last filing is more than 60 days from the expiry. These
  are 8 in the fit: the episode may span two offers, so Stage 0 reads them by
  hand.

---

## 5. Positions, hedge, entry, exit and sizing

### 5.1 Entry (H1)

- **Decision at day 0** (22:00 ET), **fill at the close of day 0 + 1**, first
  P&L on day 0 + 2: exactly `evaluate()`'s `H.shift(2)`.
- **Condition:** day 0 + 1 is at least 3 sessions before the final expiry (the
  assumed election cut-off; decision 6). Otherwise the event is not traded, and
  is counted.
- **Weight:** each event in a group of m events announced the same day by one
  sponsor gets u_e = 1/m. The group is the independent unit (census, N1, G1c),
  so one sponsor's decision on one day is one unit of risk. On today's counts
  (§11) the largest fit group has 5 events, and 9 groups have more than one.
- **There is no entry filter.** Every eligible event is traded, whatever its
  discount at day 0. A filter would need a daily NAV that dead funds lack (plan
  item 0.8), and a threshold, which would be a parameter to choose.

### 5.2 The hedge

- **Which ETF.** It is the first ETF in the census's declared order for the
  fund's asset class (`HEDGE_ETF`, then `HEDGE_ALTERNATES`, unchanged) that
  meets two conditions:
  - it was shortable at Alpaca on DG-NT-4's read, or showed availability > 0 in
    IBKR's file that day (decision 3);
  - it has CRSP returns covering the β window and the hold.
  Otherwise the event is excluded, and counted.
  - **On today's reads**, every fit class has an Alpaca route except muni
    (11 fit events). Muni routes to MUB at IBKR, at a fee of 7.73%/yr on
    2026-10-19 [V on its stamp].
- **How much.** β̂ is the Dimson beta: the sum of the slopes on the ETF's
  same-span and previous-span returns, with an intercept. It is fitted on 252
  valid fund spans ending 42 sessions before day 0, with at least 200 spans and
  at most 10 missing days bridged. All of this is
  `scripts/events/e1_etf_hedge_gate.py::windows`, `spans` and `dimson`,
  unchanged with their constants.
  - Why Dimson: a CEF's close can lag the ETF's, and a lag-0 beta under-hedges.
  - Why the 42-session guard: it keeps activist accumulation and the pre-event
    drift out of the estimate.
  - Every input ends before day 0 (H7), and the trial asserts it.
  - No shrinkage and no clipping. The β̂ distribution is reported. β ≡ 1 and
    β ≡ 0 (unhedged) are robustness rows.
- **The hedge weight** is −β̂_e × the event's fund weight, from day 0 to F (the
  decisions). It is netted per ETF across live events into one column, as one
  order per symbol would be live.
- **After pricing** the hedge stays on the full original notional until F.
  The trial does not shrink it by π, because π is not public until the results
  filing. Over those few sessions it carries a naked ETF short of
  π × β̂ × weight. A live trader would carry the same exposure.

### 5.3 The tender and the exit

| sessions (relative to the event) | fund column: return written into R, per unit of original notional | hedge |
|---|---|---|
| day 0 + 2 … X_p − 1 | CRSP `ret` | −β̂ × ETF `ret` |
| **X_p** (pricing) | π × (P_final ÷ close(X_p − 1) − 1) + (1 − π) × `ret`(X_p) | −β̂ × ETF `ret` |
| X_p + 1 … F + 1 | (1 − π) × `ret` (only the residual is exposed) | −β̂ × ETF `ret` |

- **F = the later of** the session of the outcome filing's `observed_at` and
  X_p + 5 sessions (decision 6). The residual is sold at the close of F + 1
  (decided at F).
- **A terminated or withdrawn offer:** π = 0, X_p is not used, and F = the
  later of the termination filing's session and that session + 5.
- **Distributions** come with CRSP's total return; accepted shares are taken
  to receive P_final only.
- **π and P_final enter R, never H.** They are realised outcomes on X_p, so
  writing them into that session's return is not lookahead. No decision row
  (H) depends on them; F depends only on a filing's `observed_at`.

### 5.4 Sizing (vol target, gross cap)

- **Raw sleeve:** u_e per event (§5.1), hedge −β̂ u_e.
- **Sized sleeve:** k × raw. k = `vol_target_annual` ÷ σ_active, where
  `vol_target_annual` is read through `scripts/cef/spec.py` (0.06 today) and
  σ_active is the raw sleeve's annualised daily gross P&L vol **on fit
  sessions with at least one live event**. k is one constant, frozen for the
  holdout and live.
  - Why "active": counting idle sessions would inflate every event's size to
    fill a budget the sleeve cannot use. That is sizing on opportunity count,
    which the portfolio framework (§2.2, §2.8: "No K_min top-up") rules out.
  - The sleeve runs below its budget when events are few, by design.
- **The gross cap applies at entry only.** Tendered shares cannot be sold to
  make room, so a live event is never cut.
  - An entering event or group takes the lesser of its sized weight and the
    room left under `max_gross_stress` (1.80 today, read through `spec.py`).
    The room is counted as fund plus |hedge| gross on its decision day.
  - With no room, the event is not entered, and is counted.
  - The share of events entered below their sized weight is reported.
- **D4's betas are read at the vol target:** each is multiplied by
  `vol_target_annual` ÷ σ of the tradable sleeve over the fit.

### 5.5 No new backtester

The event table becomes:

- `H`: sessions × (one column per event, plus one per hedge ETF);
- `R`: CRSP `ret`, with §5.3's tender session written into each event's
  column;
- `Q`: the notional actually traded each session.

Then each piece is existing code, unchanged:

| what | code |
|---|---|
| daily P&L under shift(2) | `scripts/cef/band_frontier.py::evaluate(H, R)` |
| gross and the 5/15/30 nets | `band_frontier._stats(pnl, Q.abs().sum(axis=1))`. Q equals \|ΔH\| everywhere except each event's exit row, where the fund leg trades (1 − π) of the position, because the tender takes π without a trade. That is the one place `evaluate()`'s own turnover would overcharge. So `_stats` gets Q, and its formula is unchanged |
| borrow | `band_frontier.borrow_charge(H_hedge, fee_pct)`: shift(2), 102% collateral, actual/360 |
| fit window | `band_frontier.fit_only` and `HOLDOUT_START` |
| the bar | `validate._dsr`; `nw_t` and `stationary_boot` from `scripts/cef/w4_artifacts.py` |
| per-event inference | `convert_issuance.cluster_t` (CR1) |
| hedge ratio | `e1_etf_hedge_gate.windows`, `spans`, `dimson` |
| day 0 | `event_store.observed_at` and `research_decision_time` |
| terms | `cef_corp_action_census.parse_tender_offer`, `parse_tender_result`, `groups`, `HEDGE_ETF` |

New code is one trial script, `scripts/events/nav_tender_trial.py`, written
after approval. It builds H, R, Q and the event table, and extends the result
reader to terminations and P_final, with tests. It asserts:

- that the per-event P&Ls sum to `evaluate(H_raw, R)["pnl"].sum()`;
- that R is finite wherever `H.shift(2)` is non-zero, raising and naming the
  event and the date. `evaluate()` treats a NaN return on a held day as 0,
  which would be a silent fallback.

---

## 6. Costs, borrow and the election fee

- **Gross is the headline.** Net is shown beside it at 5, 15 and 30bp per unit
  of Q, on every leg, labelled, with whether the sign flips across the grid
  (H3). Charging the ETF legs at the same rate as a thin CEF overcharges them;
  a row with the ETF legs at 5bp throughout is reported.
- **Per event, raw units:** net = gross − c × (1 + (1 − π) + 2|β̂|). That
  covers fund entry, the residual sale, and the hedge in and out.
- **Borrow, separately and labelled (H4).** The only shorts are ETFs.
  - Alpaca easy-to-borrow shorts pay no fee (§12l [V]).
  - An IBKR-routed hedge is charged IBKR's file fee on DG-NT-4's date, through
    `borrow_charge`. MUB read 7.73%/yr on 2026-10-19 [V on its stamp].
  - One day's fees applied to 2010–24 is a counterfactual, and the table
    says so.
- **The election fee, separately and labelled.** $100 per event (Alpaca, §12ac
  [V]), converted to a return at the event's dollar notional: its tradable
  weight × the spec's `capital_usd` ($100,000 today). It is charged on the
  pricing session.
  - It is also reported at $1m capital, because the real-capital size is open.
  - It is not part of the 5/15/30 grid. Whether it enters stage 3's kill is
    decision 4.
  - It applies to A only; B pays none.

---

## 7. The sample: fit, gap, holdout, sealed sets and eras

| period | rule | events / groups (proxy, 2026-10-19) |
|---|---|---:|
| **fit** | day 0 ≥ 2010-01-01; last P&L session (F + 1) ≤ 2022-12-30 | 138 / 123; **134 / 120** without the 4 merger-open events |
| gap | day 0 < 2023-01-01, F + 1 later | 1 / 1, in neither period |
| **holdout** | day 0 ≥ 2023-01-01; F + 1 ≤ 2024-12-31 (CRSP's last row) | 32 / 21 |
| after CRSP | day 0 ≥ 2023-01-01; F + 1 > 2024-12-31 | 27 / 17, unused unless decision 8 extends the holdout |

- **The proxy.** F uses the episode's last EDGAR filing date for the results
  date (median 6 days after the parsed expiry) and the parsed expiry for X_p.
  Stage 0 re-dates every event from its own filings, and prints the re-dated
  counts beside these (H14).
- **The 2023-01-01 time holdout** is opened once, after the fit verdict is
  committed, whatever that verdict.
  - Nothing is chosen with sight of it: k, the β rule, the hedge order, the
    lags and every threshold are fixed now or on the fit.
  - β̂ rolls on the holdout (H13 allows a rolling estimator).
- **H9, the 27 names:** not consumed (§1).
- **The CRSP fit reader refuses 2023+ rows.** The holdout reader runs only
  after the fit verdict's commit exists.
- **Eras (H5):** 2010–14, 2015–19 and 2020–22 (fit); 2023–24 (holdout). Each
  row gives events, groups, the per-event mean and t, the sleeve Sharpe, and
  turnover sd/mean. Fit events by year: 2010 8, 2011 10, 2012 15, 2013 8,
  2014 9, 2015 5, 2016 6, 2017 17, 2018 8, 2019 16, 2020 14, 2021 12, 2022 10.

---

## 8. Inference and controls

| quantity | method |
|---|---|
| **per-event level** | the mean of the per-event gross P&L in raw units over the fit, with a **t clustered by group** (sponsor × day 0; CR1, `cluster_t`). Beside it: plain t, and a group bootstrap (10,000 draws of groups, seed 20261019) |
| **sleeve headline** | the annualised gross Sharpe of the tradable sleeve's daily P&L, from the first P&L session to 2022-12-30 (T = 3,264 sessions on today's first day 0), idle sessions included |
| **HAC t** | Newey–West (Bartlett), L = 21, `w4_artifacts.nw_t`; the Newey–West (1994) automatic lag printed beside it |
| **bootstrap** | stationary bootstrap, mean block 21, 10,000 resamples, seed 20261019 (`w4_artifacts.stationary_boot`); mean block 63 as a second method |
| **the bar** | `validate._dsr(obs, T, skew, kurt, N)` on the fit-window gross series; **PASS > 0.95**, N per decision 1 |
| beside it, never deciding | SR·√years against √(2 ln N) |

**Controls:**

| stage | control | rule | why |
|---|---|---|---|
| **2** | **Placebo dates.** Each real event's day 0 is replaced by a date drawn uniformly from the same fund's fit sessions, subject to: no tender episode of that fund (any class) within 126 sessions; no merger or contest episode open; a β history; and the real event's hold length fitting inside the fit. The exit is a plain sale (π = 0, no fee), with the same u, ETF and β rule (β re-estimated at the placebo date). 1,000 draws, seed 20261019 | **KILL D1** if the real per-event gross mean is at or below the placebo distribution's 95th percentile | Same funds and exposure, no tender. A hedged CEF held for six weeks has its own drift (carry, discount reversion); the tender must beat it |
| reported | **the no-tender twin (B):** same entries, sold at the close of X_p − 1, never elected | no kill (§2.1) | splits A into the announcement drift and the tender's own payoff (A − B), each with its own cluster t |
| reported | **late entry:** enter at the close 5 sessions before the cut-off, tender, same exit | no kill | the classic tendering-profit window (Lakonishok & Vermaelen; Kadapakkam et al.'s comparison, §2.3) |
| reported | **mechanism slope:** per-event P&L on the terms-implied slice spread at day 0, on the subset with an offer-stated NAV dated on or after day 0 (the census's `disc_post` rows) | no kill | the tender predicts a larger gain where the offer sits further above the price: a positive slope |
| reported | **shift(3):** `evaluate(H.shift(1), R)` | no kill | one day's delay should cost little if the edge is the tender, not the announcement-day price |

Turnover is matched by construction (H2): the placebo and the twins trade the
same events, at the same notional, once in and once out.

## 9. Regressions

OLS with statsmodels HAC covariance (maxlags 21), on the tradable sleeve's daily
gross P&L. The P&L is a self-financing long-short return, so no risk-free rate
is subtracted.

| regression | role | specification |
|---|---|---|
| **R-D4** | **decision** | French **Mkt-RF, SMB, HML, RMW, CMA, UMD**, **TERM** = IEF − RF, **HY** = HYG − IEF, **MUNI** = MUB − IEF. Each enters at t and t − 1 (Dimson), and the betas are summed: a CEF's close can carry its beta a day late. This is C4's R-D4 plus MUNI. **Pass: alpha t ≥ 3.0, and every summed \|β\| ≤ 0.10 at the vol target** |
| R-0 | reported | the contemporaneous-only version |
| R-BOOK | reported | correlation and beta with the deployed CEF book's daily P&L (`scripts/xasset/book_profile.py`); **never a kill** |

## 10. Robustness: reported, never chosen from, and none of it rescues a failed headline

- One unit per event instead of per group.
- β ≡ 1; β ≡ 0 (unhedged); ETF legs at 5bp.
- **Alpaca-only hedges.** Muni events are dropped, and separately, hedged with
  IEF (duration only).
- **Credit classes only**: high yield, loans, muni, multi-sector, preferred,
  EM debt and convertible. Today that is 66 fit events and 62 groups, before
  the merger-open exclusions.
- The quality-screen events removed (§4.4).
- **The residual lag** at the outcome filing only (no 5-session floor), and at
  10 sessions.
- Strata, each with its count:
  - day-0 form;
  - programme tenders (the 26);
  - offers for at least 50% of shares;
  - re-dated events;
  - the second-method π.
- Per era, with turnover sd/mean; calendar-year sign share;
  leave-one-group-out minimum, median and maximum; the share of P&L from the
  largest group.
- The uncapped sized sleeve, and the share of events entered below their size.
- **Capacity.**
  - The capital at which the median event's entry reaches 1% and 5% of its
    63-session ADV.
  - Participation at $100k, $1m and $10m.
  - The election fee in basis points at each.

## 11. Feasibility, measured today (zero trials)

`python3 scripts/events/nav_tender_feasibility.py --ibkr <usa.txt>`, run
2026-10-19. Inputs: tracked EDGAR-derived tables (last filing 2026-10-09), the
census's Alpaca read (2026-10-18), and IBKR's file (`#BOF|2026.10.19|10:59:08`).
Every figure is [V] by that script, as of today's proxy dates.

### 11.1 Events

| period | events | groups | merger open | π read | offer > 60 days after day 0 | after a triggered N1 window | episode far from expiry | hedge at IBKR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fit | 138 | 123 | 4 | 114 | 25 | 26 | 8 | 11 |
| gap | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| holdout | 32 | 21 | 0 | 18 | 4 | 11 | 1 | 8 |
| after CRSP | 27 | 17 | 0 | 24 | 1 | 17 | 10 | 6 |

- No event lacks a hedge route on today's reads, once IBKR's file is
  admitted. Without it, the 11 fit muni events have none.
- Day-0 forms in the fit: SC TO-C 113, SC TO-I 24, SC TO-I/A 1.
- Fit asset classes:
  - high yield 46;
  - US equity 17; Europe 15; muni 11; EM equity 9; MLP 7; global equity 6;
  - loans, China, India and multi-sector 4 each;
  - Korea, Latin America and sector 3 each;
  - Taiwan and preferred 1 each.
- **The holdout's π is read for only 18 of 32.** The 20% exclusion gate
  (§4.3) applies there too. If it fails on the holdout, the holdout halts and
  is reported; the fit verdict stands.

### 11.2 The bar and its power

T = 3,264 P&L sessions: first day 0 2010-01-12, first P&L 2010-01-14, to
2022-12-30. The Sharpe at which `_dsr` = 0.95 (skew 0, kurtosis 3), and the
probability of passing at three true Sharpes, use
`scripts/xasset/slate_feasibility.py`'s helpers, which invert `_dsr` itself:

| N | √(2 ln N) | Sharpe needed | P(pass) at 0.4 | at 0.9 | at 1.6 |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 0.457 | 0.42 | 0.94 | 1.00 |
| 2 | 1.177 | 0.785 | 0.08 | 0.66 | 1.00 |
| 3 | 1.482 | 0.869 | 0.05 | 0.54 | 1.00 |
| 4 | 1.665 | 0.920 | 0.03 | 0.47 | 0.99 |
| 5 | 1.794 | 0.956 | 0.02 | 0.42 | 0.99 |
| **6 (default)** | **1.893** | **0.984** | **0.02** | **0.38** | **0.99** |

**D4:** alpha t ≥ 3 needs an annual information ratio of 0.834. P(alpha t ≥ 3)
is 0.06 at an IR of 0.4 and 0.59 at 0.9.

**Where 0.4, 0.9 and 1.6 come from [U, assumptions, not measurements].**

- A sleeve of about 10 events a year has a Sharpe of roughly √10 × μ/s.
- **Three anchors for μ:**
  - 0.5%: Kadapakkam et al.'s CEF figure, a different window;
  - +1.14%: the census's give-back level;
  - +2.14%: the census's generous level.
- **The anchor for s, the per-event sd: about 4%.** This is the E1 gate's
  hedged residual over a hold (641–829bp over its holds [V there]), scaled by
  √(hold ratio) to the tender's hold: about 52 calendar days, plus the
  residual lag.
- **None of these is an input to any rule (H14).**

**The per-event test at G = 120 groups** (P(cluster t ≥ 2), one event per group):

| μ | s = 3% | s = 4% | s = 6% |
|---|---:|---:|---:|
| 0.5% | 0.43 | 0.26 | 0.14 |
| 1.14% | 0.98 | 0.87 | 0.53 |
| 2.14% | 1.00 | 1.00 | 0.97 |

- **Clusters needed.** The portfolio framework's N_clusters = 7.85 (s/μ)² is
  502 at 0.5%/4%, 97 at 1.14%/4% and 27 at 2.14%/4%.
- **The holdout sign rule** has 21 groups. P(holdout mean > 0) is 0.72 at
  0.5%/4% and 0.90 at 1.14%/4%.
- **D7.** 120 groups is below the legend's "about 250 independent trades" for
  a claim about a **policy**. The trial's decision claim is about a **mean** per
  event, which the framework (§1.4) sizes by N_clusters, not by 250. The
  sleeve's Sharpe is therefore an estimate with a wide error, and the live
  statistic runs in events (§14).

## 12. The order of evaluation (the exact kill tests)

| stage | statistic | rule | if it fails |
|---|---|---|---|
| 0 | DG-NT-1…6; the quality screen; counts by filter, re-dated beside §11; k; the cap-binding share | a gate fails, or more than 20% of fit events have an unread outcome | **no trial spent**: fixed, or referred to the team lead |
| — | **the trial is spent from here** | — | — |
| 1 | per-event mean gross P&L, cluster t by group (fit) | t ≥ 2.0 | **KILL D1** |
| 2 | placebo dates (§8) | real mean > placebo p95 | **KILL D1** (the tender's timing does not carry the return) |
| 3 | per-event mean net at 15bp, every leg (§6), cluster t by group | **t ≥ 2.0**: significant after costs, which the graveyard paper did not find (decision 5) | **KILL D2** (reproduces "not significant net") |
| 4 | R-D4 | alpha t ≥ 3.0, and every summed \|β\| ≤ 0.10 at the vol target | **KILL D4** |
| 5 | the bar: `_dsr` at N | > 0.95 | **NEITHER**: real at most, below the bar. No sleeve, and no re-test on these data. The team lead rules WATCH or D5 |
| 6 | the fit verdict is committed | — | — |
| 7 | holdout, opened once: (a) mean per-event gross P&L > 0; (b) the tradable sleeve's mean daily gross P&L > 0 | both | **KILL D3** |
| — | the 5 / 15 / 30bp grid, all legs; borrow; the election fee at $100k and $1m | reported, with whether each flips the sign | — |

**Every statistic of every stage is computed and reported, whatever the
verdict.** The verdict is the first rule that fails, in this order. A PASS needs
stages 1–5 and 7. **These kill rules are stated in advance, are pre-committed
and are not softened later.** The holdout can kill; it can never rescue a failed
fit.

## 13. What we expect [U]

| stage | expectation |
|---|---|
| 1 | Passes if the per-event mean is near the census's give-back level (+1.14%), and fails near the paper's 0.5% |
| 2 | The placebo has a positive mean of its own (CEF carry against an ETF). The margin is unknown |
| 3 | **The likeliest kill.** Round-trip costs at 15bp on 1 + (1 − π) + 2β units are about 50bp per event (at π ≈ 0.3 and β ≈ 0.8), a large share of a mean between 0.5% and 1.1% |
| 4 | Alpha t ≥ 3 needs an IR of 0.83: likely to fail unless the mean is near the generous level |
| 5 | NEITHER at N = 6 is likely if stages 1–4 pass narrowly |
| B row | Most of A's return comes before pricing (the announcement drift), with A − B small. That is the paper's finding restated |

Being wrong here is fine, and is the point.

## 14. What would falsify it once trading (H11)

Stated now, for a sleeve that passed and was released, following the portfolio
framework's event-sleeve row (§4.1). **An event sleeve's horizon is in resolved
events, not sessions, and may be years.**

- **Only broker-confirmed elections count.** An event whose tender was not
  executed at a broker (a paper election, if paper cannot do it) is recorded
  as **modelled, not evidence**, and does not count toward the statistic below
  (CLAUDE.md research rules).
- **The kill rule:** reverse the sleeve if the mean net P&L per resolved,
  broker-confirmed event is below zero, read at N_clusters = 7.85 (s/μ)²
  resolved groups. μ and s are re-measured from the fit and holdout on the read
  date. **No threshold or count is written here as a number (H14).**
- **Fidelity, per event.** Each live event's day 0, entry, election, π,
  P_final and exit must match the declared rule run on the same filings. A
  mismatch halts the sleeve as a bug.
- **Pause (not kill):** a live drawdown beyond the fit's worst, re-measured,
  stops new entries; live events run to their exits.

## 15. Trial accounting

- **EVENTS today: 0 trials** (`docs/RESEARCH_STATE.md` counter table, read
  2026-10-19 [V]). On approval it moves by one, in the commit that records the
  approval, not in this commit.
  - **The trial's number is set by the order in which the team lead approves
    this draft and the parallel E1 merger-pair draft.** E2's draft of
    2026-10-13 is also unapproved.
  - N for the bar is decision 1.
- **`docs/RESEARCH_STATE.md` changed in this commit: no.** No other counter
  moves.
- **Sealed sets.** H9 (the 27 names) is not consumed. The 2023-01-01 holdout
  stays sealed until the fit verdict is committed. No CRSP 2023+ row was read
  for this draft.
- **Zero-trial script:** `scripts/events/nav_tender_feasibility.py`, with
  tests. **Trial script (after approval):** `scripts/events/nav_tender_trial.py`
  (§5.5).

## 16. Decisions for the team lead

Each has a stated default, so the draft is complete as written. Approval
approves the defaults unless a ruling says otherwise.

1. **N for the EVENTS bar.**
   - **Default N = 6, fixed on approval: the same N the parallel E1 draft
     proposes** (branch `research-e1-prereg`): plan §3's E1–E4 plus the two
     tests named on 2026-10-19. The bar is √(2 ln 6) = 1.893, and a Sharpe of
     0.984 is needed over this fit (P(pass) 0.38 at a true 0.9).
   - **One N for every EVENTS trial approved from this programme**, so that
     the bar does not depend on the order of approval, which sets only the
     trial numbers. E2's draft of 2026-10-13 proposed N = 4 before either
     2026-10-19 test existed; it should move to 6 as well.
   - *Alternatives:* the running count, where N equals the trial's number
     (0.457 needed at N = 1, 0.785 at N = 2); N = 5 (0.956); or N = 3, the
     three drafted tests (0.869).
2. **What is traded.**
   - **Default: tender participation (A).** The no-tender twin (B) and the
     late-entry row are reported only, and B can never be promoted from this
     trial (§2.1).
   - *Alternative:* B as the headline. That has no election fee and paper can
     run it, but it is a different hypothesis, and no census gate covers it.
3. **The muni hedge.**
   - **Default: MUB through IBKR's public file**, under the 2026-10-19 ruling
     that the file is admissible for any hedge leg. Its fee (7.73%/yr on
     2026-10-19) goes in the borrow line. This accepts a second account for
     11 fit events.
   - *Alternatives:*
     - exclude muni events (the trial then runs in one account);
     - hedge them with IEF at Alpaca (duration only);
     - re-order the muni list so VTEB, at 3.00%/yr at IBKR on 2026-10-19,
       comes first. That would be chosen on today's fee, so it must be decided
       before Stage 0.
4. **The election fee in the kill.**
   - **Default: reported beside the grid** at $100k and $1m capital, and not
     part of stage 3. The fee is fixed per election, so its weight depends on
     a capital size not yet set.
   - *Alternative:* charge it in stage 3 at the spec's `capital_usd`.
5. **The graveyard bar at stage 3.**
   - **Default: the per-event net mean at 15bp must have a cluster t ≥ 2.0.**
     The paper found CEF tendering profits "no longer significant after
     adjustments for transaction costs".
   - *Alternative:* net mean > 0 (E2's rule). It passes more easily, and does
     not answer the paper.
6. **The broker mechanics not documented.**
   - **Default:** the election cut-off is 3 sessions before expiry; the
     residual is sold no earlier than 5 sessions after pricing (§3).
   - *Alternative:* 1 session and the outcome filing alone. Both are reported
     as robustness either way.
7. **Asset classes.**
   - **Default: every class with a hedge route** (134 events, 120 groups).
     Equity CEFs are corporate actions on the EVENTS source.
   - *Alternative:* credit classes only (66 events, 62 groups, counted before
     the 4 merger-open exclusions). That halves the sample. It is reported in
     any case.
8. **The holdout's end.**
   - **Default: 2024-12-31, CRSP's last row** (32 events, 21 groups by proxy).
     There is one price source with total returns, and no distribution
     reconciliation.
   - *Alternative:* extend to 2026-09-30 with Alpaca daily bars and a declared
     distribution source (about 27 more events, 17 groups). That needs a data
     gate of the kind C4's amendments built, and a fixed end date set now.
9. **Weighting.**
   - **Default: one unit per group (1/m per event).**
   - *Alternative:* one unit per event (reported in any case).
10. **Where a passed sleeve trades.**
    - **Default: only on an account that can make real elections**, after the
      real-money cost gate. Meanwhile it runs on paper as B (no election),
      labelled. The tender leg is "modelled, not evidence" until confirmed.
    - *Alternative:* paper with the tender leg modelled. That builds no H11
      record (§14).
11. **Whether to spend the trial now.**
    - **Default: run as specified.** The census gates passed; the per-event
      test has power of about 0.87 if the give-back level is true and s is
      4% (§11.2);
      and a stage-3 kill would settle the "tender capture" question on 2010–22
      data.
    - *Alternative:* defer until decision 8's extension data exist, which
      would add about 17 holdout groups.
12. **The 27-name set (H9), and the order against E1.**
    - **This trial does not want H9.** It excludes all 44
      `cef_universe.csv` funds whatever the order of approval. Its holdout is
      the 2023-01-01 time holdout (32 events, 21 groups by proxy; §7), with or
      without H9.
    - **What it would lose if E1 consumes H9 first: nothing.** The E1 draft
      proposes the never-priced deals on the 27 as its holdout, which consumes
      the set. Then the 44's NAV tenders could join this sample without
      consuming anything. There are 8: 7 in the fit and 1 in the holdout (EFT,
      2023-09-01). 2 are on the original 17 (NVG and NZF, 2014-08-08); the other
      6 are on the 27 (HIO 2020, VVR 2019, EFR and EFT 2021, EFT 2023, and a
      2012 equity fund with no ticker today). Adding them after approval would
      make this sample depend on the approval order, so they stay out.
    - **The conflict to avoid:** if this trial included the 44 and ran before
      E1, it would consume H9 and take away E1's proposed holdout.
    - **Default: the 44 stay excluded, fixed now.**
    - *Alternative:* include the 44's 8 events. That is free only if E1 has
      already consumed H9, and it must be decided before Stage 0.
