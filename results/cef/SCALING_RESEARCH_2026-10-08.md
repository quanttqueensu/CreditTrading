# Scaling the firm: how others clear 10%, and our build order — 2026-10-08

**The question** (team lead, 2026-10-08): how do real buy-side and sell-side
firms earn more than 10% a year in absolute return in CEFs, listed credit and
systematic debt? What should this desk build, in what order, to do the same,
with more signals, sleeves and asset classes, and edges that are its own?

**Scope, as the team lead set it for this research:**

- **real capital soon;**
- **in bounds:** Alpaca-listed instruments, cash bonds, futures and swaps
  through another broker, and reopening options;
- **≥10% with leverage treated as a research lever.**

**This note changes no standing decision.** `docs/SYSTEM.md` §5 still records
"paper indefinitely, no real capital planned" (2026-09-08), and the options
programme is still closed (W14, G6). §6 asks whether to record the new scope.

**Companion.** `results/cef/RESEARCH_AGENDA_2026-10-08.md` is the research
programme by product and signal family. This note adds the firm-level view:
how others make money, the return-on-capital arithmetic, a staged build order,
and new candidates.

**How it was made.**

- **A deep-research workflow.** 26 sources, 123 claims extracted, 25 put to a
  three-vote adversarial check: 15 survived, 10 were refuted and 8 were dropped
  for budget. Labels below are the verifiers' (they fetched the source). Leads
  from the search phase that were never voted on are [S].
- **One measurement:** `python3 scripts/data/term_cef_census.py` (CRSP names).
- **Sources** are in `docs/REFERENCES.md` §12c.

**Spends no trial, changes no spec, trades nothing.**

---

## 0. The answer

1. **No verified record shows anyone earning 10%+ from CEF discount capture
   alone.** The documented routes to 10%+ are two:
   - **Levered, partly hedged market exposure plus discount capture and
     corporate events.** Saba's CEFS ETF earned 11.23% a year at NAV since
     2017-03-20. The book is about two-thirds equity CEFs on a credit line, and
     it trailed the S&P 500 over every period shown [V, audited N-CSR].
   - **Heavy secured leverage.** Relative-value hedge funds earned about
     10.2–10.6% a year before fees and 7.2% after (2013–2026Q2). They ran about
     8× aggregate balance-sheet leverage, 23× on a gross-asset-weighted basis,
     financed by prime brokerage and repo [V, OFR Form PF]. Credit hedge funds
     run about 2.25×.
2. **Lasting CEF discount gains come from corporate actions that actually
   happen**: open-ending, liquidation, merger, NAV-priced tenders. An activist
   attack alone does not do it. Funds that were attacked but stayed closed-end
   gave back their excess narrowing within two years (Bradley et al., 1988–2003
   [V]). The 6–3 ruling of 2026-06-11 closed the activists' §47(b) rescission
   route [V].
3. **For us, return = Sharpe × volatility.** At the book's 6% vol target, 10%
   needs a realised Sharpe of about 1.67. The book is close to one bet. So the
   order of levers is:
   1. **breadth** (independent sleeves);
   2. **the vol target** (to be derived under W6, capped at 20%);
   3. **financing beyond Reg T**, only once a route has been priced.

   Gearing up a single bet multiplies the tail along with the return.
4. **Build order:**
   - **First, the CEF book:** make it ready for real money, add a corporate-action
     filter, then build an event-driven CEF sleeve. That sleeve covers announced
     actions, the post-IPO lifecycle, and a new candidate: the **discount
     pull-to-par on term CEFs**.
   - **Then** the independent ETF and futures sleeves.
   - **Leverage last.**

   *Updated 2026-10-09 (§7):* the targeted pass puts the **NAV-for-NAV CEF merger
   pair** first among new trials, after two zero-trial gates. Next come the
   corporate-action filter, a standalone **short TLT variance premium** (GAMMA),
   the convertible-issuance reversal and listed mandatory convertibles. The
   **term-CEF pull-to-par is parked as a sleeve** (D7). CDX, core convertible
   arbitrage and equity–CDS arbitrage are **killed on access**.
5. **Do not build:**
   - **a sleeve on published bond factors** (most fail replication);
   - **the Treasury cash-futures basis**, which lives on repo access that
     disappears exactly when the basis gaps;
   - **pre-positioning on activist attacks.**

---

## 1. How firms actually earn it

These are firm lessons, not signals.

| route | who | documented result | leverage and financing | what transfers to us |
|---|---|---|---|---|
| Fund-of-CEF activism | Saba, CEFS ETF | NAV return: 11.23%/yr since inception, 13.53% over 5 years, 10.17% in FY2025. S&P 500: 14.86%, 15.28%, 15.00%. Bought CEFs at an average 10.30% discount and sold at 5.30%, "aided by … tenders, liquidations, and open-end conversions". $348.4M net assets [V] | credit line (collateral pledged = 17.6% of net assets); short S&P, Russell and Treasury futures as hedges [V] | **Hedge NAV beta with futures**, not with ETFs we cannot short. Concentrate where corporate actions are coming |
| Fund-of-CEF activism | Bulldog, SPE | 2025 NAV return 11.59%; about 51% CEFs and 18% SPACs; 2022 tender at 97% of NAV [S, search summary; the audited table was not retrieved] | — | The NAV-priced tender is the exit |
| Settlements | Saba with BlackRock (Jan 2025) | BIGZ to tender for 50% and BMEZ for 40%, both at 99.5% of NAV; Saba agreed to a 3-year standstill [S] | — | These are the dated events an event layer trades **after** they are announced |
| Activist footprint | Saba, Karpus, Bulldog | Held stakes in 44% of CEFs at end-2024. Of 44 forced tenders (2015 to June 2023), the activist exited within a year in 75% and within 3 months in 48% [V, ICI, an industry lobby] | — | The counterparty set is large; the exit is usually a tender near NAV |
| Relative value | large hedge funds (OFR Form PF) | 7.24%/yr net, 10.2–10.6%/yr gross, 2013Q1–2026Q2. Only 2 of 13 calendar years cleared 10% net (gross-asset-weighted) [V] | GAV/NAV 8.1× aggregate, 23.3× gross-asset-weighted; secured borrowing 5.47× NAV; prime brokerage plus repo [V] | 10% gross is a leverage outcome a small firm cannot copy |
| Credit hedge funds | (OFR) | — | about 2.25× GAV/NAV [V] | Credit books run modest leverage |
| Quant credit | industry (eVestment, via IFRE) | Industry assets fell 27% in 2022 to $52bn. Funds averaged −15% in 2022, when transaction costs more than doubled, then about +10% in 2023 [V page; vendor and sell-side quotes; the year is inferred] | — | **The cost regime dominates live P&L.** Robeco has run live since 2015 but publishes no numbers [V] |
| Treasury basis | levered hedge funds | $260–352bn in 2023–24 (TRACE proxy); "typically highly leveraged" [V, Fed FEDS note] | repo; margin and rollover risk | The Fed note says rapid unwinds contributed to the March 2020 stress. The OFR WP says the unwind was "likely a consequence rather than the primary cause". **The sources disagree; both are reported** |
| Sell side, CEF IPOs | underwriters | Stabilise at the offer price: over 90% of first-day trades print at the offer [V via verifier]. IPOs then underperform seasoned matches: −8.52% at 6 months, −11.05% at 1 year, 84% underperform, 1986–2013 [V, Shao & Ritter] | — | **A predictable sell-side flow to trade against** (§3, stage 2b) |
| Sell side, rights offerings | dealer-managers | Negative returns during the subscription period and a weak rebound; same-sector peers fall at the announcement [S, abstracts about 25 years old] | — | Candidate, stage 2d |

**What the record does not cover** (gaps, not negatives):

- the audited returns of Karpus, City of London, 1607, Matisse, RiverNorth,
  Almitas and RVP;
- firm structure, registration, prime-brokerage terms and fees for a small firm;
- portfolio margin, futures-implied financing and box spreads;
- CDX access;
- BDC and CLO-equity alpha (both FAJ 2024 claims were refuted);
- real borrow fees on CEFs and BDCs.

**I will not guess any of these.** §6 asks which to research next.

---

## 2. The return-on-capital arithmetic

| vol target | Sharpe needed for 10%/yr |
|---:|---:|
| 6% (today's spec) | 1.67 |
| 10% | 1.00 |
| 15% | 0.67 |
| 20% (the standing cap) | 0.50 |

*Arithmetic.*

- **Breadth:** N independent sleeves of equal Sharpe combine to about √N times
  that Sharpe. The book's daily P&L correlates with HYG, TLT, IEF, LQD and SPY
  at ≤0.04 (agenda §2, `scripts/xasset/book_profile.py`).
- **Leverage today:** the spec's `max_gross_stress` is 1.80, derived from Reg T
  50% margin (`docs/SYSTEM.md` §5). No claim about any route beyond Reg T
  survived verification [gap].
- **Real money costs things paper does not show.** Alpaca paper charges no
  borrow, credits no dividends and runs no auction [V]. On a real account the
  book pays:
  - **borrow**, measured once at 1.22%/yr, about 0.23 Sharpe (2026-09-06, [S]);
  - **distributions on its shorts:** the book has recently been net short yield,
    at a distribution leg of −0.6% to −0.9%/yr (agenda §2);
  - **real closing-auction fills.** The paper-only `late_market` exception must
    never apply to live money (CLAUDE.md order-path rule 3).

  Stock-market evidence puts the costliest-to-short quintile at about 411bp/yr
  [S, a different market]. The only real source for CEF borrow is our own
  broker's borrow data.

---

## 3. Build order for a firm with real capital

**Stage 1: make the CEF book ready for real money.** No new risk.

| # | item | trials | kill or gate |
|---|---|---|---|
| 1a | Track 0 infrastructure and W4 (agenda §4) | 0 | — |
| 1b | **A real-money cost model.** Daily borrow rates by name from the real broker, distributions owed on shorts, MOC auction fills. Re-run `band_frontier.py` with measured borrow | 0 (a re-measurement) | **The gate for deploying real capital at all.** If the book is not positive after measured borrow and fills, real capital waits |
| 1c | **A corporate-action filter.** Never be short a fund under an announced NAV tender, liquidation, open-ending or merger. The current z-score reads an announcement-driven narrowing as "rich", so the book can short a price that the announcement pins near NAV [inference] | 1 (it changes the live policy) | A frozen-spec key that defaults off, with a byte-for-byte no-op proof (`/spec-change`); pre-registered |

**Stage 2: an event-driven CEF sleeve** (new IC that is idiosyncratic per fund,
so it adds breadth).

| # | sleeve | counterparty | evidence | kill test (pre-2023 data) |
|---|---|---|---|---|
| 2a | **Announced corporate actions.** Long from announcement to completion, allowing for pro-ration | holders who sell before the event, from liquidity need, inattention or mandate [U] | Durable narrowing comes at realised exits (Bradley et al. [V]); CEFS credits named tenders and liquidations [V]; tenders near NAV are the usual exit (ICI [V]) | Matched-adjusted return from announcement to completion, after pro-ration and the 5/15/30bp grid, must be positive. **Needs an EDGAR fetcher** (SC TO-I/TO-C, N-14, DEF/PRE 14A, 8-K) |
| 2b | **The CEF IPO lifecycle pair.** Short new IPOs after day 45 (once stabilisation ends); long seasoned matches | retail placed by broker distribution; underwriters who support the price at the offer | Shao & Ritter (CFR 2018) [V]: −8.52% at 6 months, 84% underperform, similar in all three subperiods to 2013 | The 6-month abnormal return on 2014–22 IPOs must be negative after the cost grid **and measured borrow**. The name must be shortable on the entry date. Dead if the effect lives only inside the stabilisation window |
| 2c | **Discount pull-to-par on term CEFs.** *New; not from the literature.* A term or target-term CEF is meant to liquidate, or tender at NAV, on a known date, so its discount should converge towards zero | holders who do not price the termination; yield-screening retail | **CORRECTED 2026-10-09 by the targeted pass (§7):** this row first said such a fund "liquidates or tenders at NAV on a known date". That overstates it. Boards can extend the term by 6–24 months, and votes can remove it with no tender (DMO 2019, XFLT 2024). **JPT did not terminate in 2022:** it tendered at NAV, dropped its term on 2022-02-28, and merged in 2023-11. **PDO, a deployed name, has a term:** dissolution on or about 2033-01-27 [V, 424B1]. The measured result is in §7 | **Verdict: PARK as a sleeve (D7, about 47 events). Fold the term and tender dates into the 2a event layer and the 1c filter** |
| 2d | **The rights-offering window.** Short the issuer and its sector peers through subscription | holders who must subscribe or sell their rights; dealer-managers | [S] abstracts about 25 years old, no magnitudes | Count post-2010 offerings first; below about 100 it is D7 |

**Stage 3: independent sleeves** (agenda Tracks A and B): trend and pension
rebalancing on ETFs, month-end Treasury extension, other CEF families, DRIP
buying, fund-of-CEF index reconstitution. **Futures change the picture here.**
Treasury and equity-index futures can hedge the book's group betas and carry the
trend leg. That gets round the ETF shortability problem (no muni ETF is
shortable at Alpaca), and it is what CEFS does [V].

**Stage 4: leverage and financing,** only after at least two independent
sleeves pass. Derive the vol target (W6, cap 20%). Price a route beyond Reg T:
portfolio margin, futures-embedded financing or box spreads [all gaps]. Choose
the broker or brokers. Return on capital rises mainly through the vol target and
breadth, not through 8–23× balance-sheet leverage we cannot finance.

**Stage 5: a second, targeted research pass** on the gaps (§6, question 5). *Done 2026-10-09 for eight topics: §7.*

**Do not build:**

| idea | why |
|---|---|
| Cash-bond factor sleeve | most published factors fail replication (Dick-Nielsen et al. [S]; Dickerson et al. [V], §12); cost claims refuted; quant credit lost 15% in the 2022 cost shock [V] |
| Treasury cash-futures basis | crowded and repo-financed; a small desk is the last to be financed and the first to be cut, just when the basis gaps [V, Fed and OFR] |
| Pre-positioning on activist attacks | we will never hold a 13D-sized stake; surviving targets give the narrowing back by t+2 [V]; the 2026 ruling closed §47(b) [V] |
| Tender capture alone | about 0.5% gross, not significant net, 2000–15 (§12 [V]) |
| A structural short of high-leverage, high-premium CEFs (e.g. CLO equity) | **PARK.** Dam, Davies & Moon [V abstract]: leverage causes premia in *equity* CEFs, and investors just get more volatility. Borrow on CLO-equity CEFs is unmeasured and a different market. Revisit in stage 5 |

---

## 4. Contradictions found and reported, not resolved

- **Bradley, Brav, Goldstein & Jiang.** The morning's pass recorded the
  targeting probit (+0.66pp attack probability per 1pp of discount) and an
  equity-only sample as [V], from the December 2008 manuscript. This pass
  **refuted 0–3** claims citing the same +0.66pp figure from the 2006 Wharton
  working-paper version, and left open whether bond and muni CEFs are in the
  sample. `docs/REFERENCES.md` §12 now marks the row as contested. Do not key
  any decision on either figure.
- **The March 2020 Treasury basis.** The Fed's FEDS note says rapid unwinds
  contributed to the stress; the OFR working paper says they were likely a
  consequence. Both are reported.
- **Relative-value GNE/NAV of 31.6×.** Refuted 0–3 as a standalone claim, though
  a verifier quoted the same ratio. Treat it as contested and do not use it.

---

## 5. What this pass could not establish

- **Most of the angles asked for returned nothing verified.** The audited returns
  of named specialists other than Saba; systematic debt implementation costs;
  Treasury futures; CDX; BDC and CLO equity; preferreds; convertibles; options;
  regulatory artifacts (Rule 12d1-4, §18, VRDP resets, Rule 2a-5); capacity
  against ADV; real borrow fees; the LTCM, 2008 and 2020 failure histories.
- **The evidence is old, or from other markets.** Bradley et al. is 1988–2003
  and Shao & Ritter ends in 2013. CEFS is two-thirds equity and its attribution
  covers one year. The OFR series covers only large funds and classifies
  strategy by the funds' own report.
- **None of the stage-2 sleeves has been run on the harness.**

---

## 6. Questions for the team lead

1. **Record the new scope?** Should "real capital soon" (and the instrument and
   leverage scope) become a dated decision in `docs/SYSTEM.md` §5? It overturns
   2026-09-08's "paper indefinitely" and reopens options. If yes:
   - roughly when, with how much, and at which broker or brokers?
   - Real money also switches off the paper `late_market` exception and makes
     stage 1b the deployment gate.
2. **The holdout.** Stages 2a–2d trade CEFs outside the deployed 13. Accept
   consuming the sealed comparison set, or test only on names outside
   `cef_universe.csv` and only before 2023?
3. **Counters.** EDGAR-based events and the CEF-IPO and term-CEF sleeves are new
   data sources. A new EVENTS counter, or CEF (bar 2.80)?
4. **Leverage regime.** Reg T, portfolio margin or a futures account? What gross
   cap and what vol target (W6)? Is the 10% gross or net of costs and borrow?
5. **The next targeted research pass.** Which first?
   - (a) the specialists' audited returns (N-CSR, 13F);
   - (b) futures financing, portfolio margin and box spreads;
   - (c) term-CEF N-2 terms;
   - (d) BDC and CLO-equity NAV against price;
   - (e) CDX through a futures broker;
   - (f) options (credit-ETF variance, CEF and BDC put-writing).

The agenda's open rulings still stand: the counter for the ETF slate, where a
sleeve lives, deliberate beta, the dividend-crediting P&L line, other CEF
families and live sources.

---

## 7. The targeted pass, 2026-10-09: eight topics

On 2026-10-08 the team lead chose eight topics for a second pass: CDX, options,
capital-structure arbitrage, convertible arbitrage, merger arbitrage, BDC and
CLO-equity NAV against price, term-CEF terms, and the specialists' audited returns.

Six desk agents covered them, each with fetched sources and descriptive,
zero-trial measurements. Every return-based statistic is pre-2023, and none uses
a holdout name. Their scratch scripts are under the session scratchpad and are
**not in the repo**. So every figure below is an agent measurement of
2026-10-08/09 and must be **re-run in the repo before a pre-registration rests on
it**. Sources are in `docs/REFERENCES.md` §12d.

### 7.1 Verdicts, ranked by information per trial

| # | idea | the result | verdict |
|---|---|---|---|
| 1 | **NAV-for-NAV CEF merger pair** (long target, short acquirer, to completion) | Target holders receive acquirer shares at the closing NAV ratio. CRSP delisting amounts match the filed ratios to 6 decimals [V]. On 168 deals in 2010–22 with no universe name, the pair earned **+129bp median over the last 63 days, against +25bp for the same pairs a year earlier**. Munis: +148 vs −43; equity CEFs: +36 vs +214, where the control wins. **But:** entering at announcement gives a median of only +35bp (N=36 events in 12 groups), below the 32.6bp-per-unit breakeven. 26 of 59 historical acquirers, mostly munis, are not shortable today, and capacity is about $0.5m per deal | **TEST first**, after two zero-trial gates: (a) borrow on today's acquirers; (b) can the sign of the spread be known at announcement from N-CSR/N-PORT NAVs? |
| 2 | **Corporate-action filter** (stage 1c) | Deployed or universe names were the **acquirer in 44 stock mergers in 2010–22**. The live z-score cannot see a pinned ratio, nor PDO's term | **BUILD-FIRST** (1 CEF trial, `/spec-change`) |
| 3 | **Standalone short TLT variance premium** (defined-risk on Alpaca, untimed, not a hedge) | IV−RV +1.23 vol pts, t 4.16 non-overlapping (VXTLT 2004–22); +1.63 from R2 ticks 2023–26. Book correlation −0.01 daily, −0.11 monthly. TLT options trade about 1.1m contracts a day, about 0.28 vol pts wide. Tails: March 2020 −44.7 pts. Alpaca allows **no uncovered shorts**, so only iron flies and condors. This is the "short premium" remainder that the G6 pre-registration named as untested, so it is not a rerun of W14-A or G6 | **TEST** (GAMMA counter, which is at 0). Reopening needs the six conditions in §7.2 |
| 4 | **Buying the stock after a convertible issue** (arbitrage hedging pressure reverses) | 755 events 2011–22: [−1,0] −4.41% against −0.64% for straight-debt issuers. Days +2..+5 **+0.54% (t 2.6)** against −0.17%. That nets about +44/+24/**−6**bp on the 5/15/30 grid. **The windows have already been looked at**: a pre-registration must keep them and cannot call 2011–22 out of sample. **Re-run 2026-10-11** (`results/events/REPRO_CORP_EVENTS_2026-10-11.md` §2): every figure reproduces (`scripts/events/convert_issuance.py`). The t of 2.6 was plain; clustered by week it is **2.24** (G3 passes, narrowly). By era the edge over the control is +1.53% (t 3.4) in 2010–14, +0.55% (t 1.8) in 2015–19 and **+0.17% (t 0.3) in 2020–22**, where the straight-debt control earns +0.52% | **TEST** (new source; TRACE flag × CRSP) |
| 5 | **Listed mandatory convertibles, hedged with the common** | 24 listed, 12 clear the volume floor, 7 are both liquid and shortable. Hedged residual vol 6–14%. Cheapness is unmeasured. **Re-run 2026-10-11** (`results/events/REPRO_CORP_EVENTS_2026-10-11.md` §4): 24, 12 and 6–14% reproduce (`scripts/events/mandatory_census.py`). With the flags of 2026-10-11, **6** are liquid and shortable (8 on the sleeve's own ADV rule, under which 19 clear). G4: 16–21 mandatories with 2016–22 history are measurable, below 30; the full census needs EDGAR (0.7) | **TEST** (count N≥30 first) |
| 6 | **Co-held loan marks across BDCs** (an early reporter's marks predict a later reporter's fund-specific NAV surprise) | The release-day reaction is 0.46× the fund-specific surprise (corr +0.28, t 4.0; no drift). The perfect-foresight ceiling is about 43bp per event. Speculative. **Re-run 2026-10-11: could not re-run** (`results/events/REPRO_CORP_EVENTS_2026-10-11.md` §5). The agent typed the NAVs in by hand from WebFetch reads; a fetcher needs the SEC user-agent (0.7). The t is not clustered by quarter. G5: one pre-2023 10-Q schedule (ARCC) carries no loan identifier | **TEST**, but only after an expensive data build (10-Q schedules) |
| 7 | Term-CEF pull-to-par | All 19 modern credit term funds that terminated before 2023 paid out NAV (CRSP code 450). But price already sat near terminal value 24 months out, and the beta-adjusted excess was about 0 (−0.07%/yr at 24m, +0.22%/yr at 12m). The 1990s cohort did better (+1.8%/yr), against poor peer matches. Target misses are in loan and HY: JCO $8.02 and EFL $8.66 against $9.85. Live 2026-10-08: FTHY −4.7% (2027-08) and DTF −5.1% (2028-03) are outside the holdout. BSL and BGB are holdout names | **PARK** as a sleeve (D7); event-layer input |
| 8 | General merger arbitrage | MNA 2.16%/yr at 8.0% vol, 2010–22; beta 0.32 in down months against 0.12 in up months: a short put | **PARK** (D4/D5) |
| 9 | Listed capital stack (preferreds and baby bonds against common) | Only 69 of 626 are shortable on Alpaca; **CRSP holds no preferreds**, so there is no history | **PARK** |
| 10 | HYG variance premium; index short-vol overlay | HYG's premium is larger, but the book loses on the same days and post-close spreads are about 60% of mid. The index overlay adds equity beta to the book's mild existing short-vol exposure | **PARK** |
| 11 | BDC discount z-score; CLO-equity NAV-estimate release | The BDC level is 88% persistent between funds. Its point-in-time NAV starts only 2022-08 (Inline XBRL). The CLO sample is D7 and mostly inside the holdout. **Re-run 2026-10-11** (`results/events/REPRO_CORP_EVENTS_2026-10-11.md` §5): the 88% could not be re-run (same reason as row 6). The 2022-08 start is confirmed for short-form-eligible BDCs (others 2023-02); ARCC's first XBRL NAV was filed 2022-10-25 | **PARK** |
| 12 | **CDX** (index, options, basis, intrinsic skew) | The premia are real (CDX short-straddle Sharpe 1.74 [V]; intrinsic arbitrage 2.34 gross [V]), but access needs a bank clearing member and SEF onboarding, with $5–25mm minimum clips (CDX options about $100mm). All 33 ICE Clear Credit participants are dealers or banks [V]. Listed IBHY/IBIG futures are about $140–180k per contract | **KILL (access)**. Listed credit futures are a later hedge option at scale |
| 13 | Core OTC convertible arbitrage | HFRI 5.13%/yr at 4.37% vol over 2013–22, on 4–6× leverage (−34% in 2008). New converts are 144A: qualified-institutional buyers only, **$100M** of securities. Median TRACE trade $1–2MM par | **KILL now; revisit as a qualified institutional buyer with prime-brokerage financing** |
| 14 | Equity–CDS capital-structure arbitrage | Security-based swaps with a non-eligible contract participant (under $10m of assets) are unlawful off-exchange [V statute]. Duarte, Longstaff & Yu: t 1.70, and convergence "for only a small fraction" [V] | **KILL** |
| 15 | Perpetual convertible preferreds; BDC NAV nowcast from loan indices; shorting the CLO-equity premium; CEF/BDC put-writing | Premium to parity 36–907%: it is rate exposure. Public loan moves carry only the common, already-priced part of the NAV change. ECC and OXLC are not shortable and owe 11–17% a year in distributions. PDI is not optionable | **KILL** |

### 7.2 What would justify reopening options

Reopening options is justified only if **all** of these hold. Each must be
re-measured at run time (H14):

1. It is a standalone short premium, untimed, with no hedge role, pre-registered
   on GAMMA.
2. Its correlation with the book stays about zero. TLT's does; HYG's does not.
3. At least 20 sessions of measured regular-hours spreads show the four-leg cost
   below the premium.
4. The defined-risk Alpaca version survives a replay of 2008 and 2020 inside the
   vol cap.
5. The team lead rules whether 2023+ data, which holds all TLT strike history,
   counts as fit data or as the GAMMA holdout.
6. The real-money account is approved for options level 3.

### 7.3 What the specialists actually earn (audited and filed)

- **No audited record shows 10%+ a year from credit-CEF discount capture.**
- **The records at or above 10%** come from equity-heavy books, all of which
  trailed the S&P 500:
  - MDCEX: 13.08% over 5 years, 11.39% over 10 [V];
  - SPE: 10.07% over 5 years at NAV [V];
  - CEFS (§1).
- **The closest analogue to our book is MDFIX** (bond and muni CEFs): 8.72% over
  5 years, with a window starting at the COVID trough. Matisse credits discount
  capture with **+147bp** in its last year [V].
- **The one record that hedges its beta is BRW** (Saba): 9.27%/yr since 2021 at
  about 12% vol [V].
- **Most of this is beta.** On monthly market returns, SPX plus HY explain
  R² 0.44–0.88. The intercept (return beyond beta) is negative for 15 of 17
  vehicles [V, agent's CRSP regressions].
- **Specialists hold our names:**
  - RiverNorth holds **11 of our 13** (13F 2026Q2).
  - Karpus filed a 13G showing **11.03% of MHD**; specialists hold about 18.5% of
    MHD in total.
  - The only activist 13D on our 13 since 2015 is Saba on JFR (2020–21). It ended
    in open-market sales.
  - JPMorgan holds 100% of MHD's VMTP preferred, deposited into a TOB trust on
    2026-06-02.
- **The lesson stands:** hedge NAV beta with futures, and get 10% from breadth and
  the vol target, not from a specialist template.

### 7.4 Corrections and data findings from this pass

- **Suhonen (FAJ 2024).** The scaling pass recorded its two BDC claims as refuted.
  The abstract **says them verbatim**: "the alpha of BDCs is zero on a
  market-value basis but a statistically significant 2.74% per annum based on net
  asset value (NAV) valuations". `docs/REFERENCES.md` §12c is corrected visibly.
- **Term-CEF row 2c**, corrected above. Also, `scripts/data/term_cef_census.py`'s
  name filter misses several groups:
  - funds with abbreviated names (TM, TGT, TRGT, DEF OPP, DEFINED);
  - 19xx-dated names;
  - funds with a tender-for-NAV clause but no term marker in the name. These
    include PDO, PAXS, PDX, DLY, WDI, NPCT, NPFD, NDMO, NMCO, PTA, MIO, the RMI
    family, SDHY, TBLD, XFLT and FINS.

  Its docstring now says so.
- **MQY shares outstanding: the sources disagree.**
  - `data/cef/cef_facts.csv` (yfinance, 2026-09-11) says 71.8m.
  - RiverNorth's 13G (5.25% = 7.90m shares, 2026-03-31) implies about 150.5m.
  - Not resolved. Nothing on the live path reads `cef_facts.csv`.
- **The VXHYG file has defects.** It has a corrupt row on 2017-10-30 and **no
  rows from 2021-09-24 to 2025-05-14**. The archived G6 "2023–2026" HYG era is
  therefore really 2025-05 onward.
- **The suspected pandas rolling-sum fault does not reproduce on the live
  inputs.** One agent saw rolling sums return values around 1e-316 in its own
  event-study code. Re-checked 2026-10-09 on the repo's discount panel (pandas
  2.3.3, bottleneck 1.4.2):
  - rolling(252) mean and std, and rolling sums, are identical with bottleneck on
    and off;
  - no value is denormal-like;
  - the result matches an independent numpy loop to 5e-15.

  **Corrected 2026-10-11** (`results/events/REPRO_CORP_EVENTS_2026-10-11.md` §3). The fault is real, and it was not
  the agent's code. Re-running the agent's original pandas lines reproduces its
  corrupted run exactly. The cause is numexpr 2.10.1 (with numpy 2.3.4) on the
  laptop: pandas hands it frame arithmetic above 1,000,000 cells, and it gets
  **broadcast** operations wrong. Affected: `df.sub(s, axis=0)`,
  `df - df.mean()`, `df.div(rowsum, axis=0)`. The check above passed because
  the discount panel is under 1e6 cells and rolling reductions do not broadcast.
  The live sleeve's frames (about 71k cells) are below the threshold.
  `python3 scripts/events/numexpr_fault.py` tests an environment.
