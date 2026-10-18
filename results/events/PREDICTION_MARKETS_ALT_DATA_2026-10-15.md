# Prediction markets and free alternative data for event signals — 2026-10-15

**The question** (team lead, 2026-10-15, special-situations sprint, job 6 of 6):
a zero-trial scan of (A) prediction markets, Kalshi above all, as a **data
source first** and possibly a hedge, and (B) free alternative data for event and
special-situation signals. The team lead approved **researching** a Kalshi
account. **No account was opened, nothing was signed up for, nothing was placed.**

**Zero trials.** No counter moves (`docs/RESEARCH_STATE.md`: CEF 52, GAMMA 0,
EVENTS 0, XASSET 4, POSITIONING 1, NPORT 1 — unchanged). Nothing here computes a
return, so neither holdout is touched: the 27-name set is consumed only by a test
that computes returns on a `cef_universe.csv` name, and the 2023 time holdout is
about returns too. The news measurement reads article **counts** for those names.
No spec, book or runner file changes.

---

## 0. The answer

**Kalshi: eligible, cheap to trade, and its data cannot be collected by us under
its published terms.**

- **Status.** A CFTC-designated contract market since 2020-11-03, clearing through
  its own registered DCO, Kalshi Klear LLC (registered 2024-08-28) [V: agent].
- **Eligibility.**
  - **Individuals:** 18 or older (the age of majority in the state of
    residence). The member agreement's restricted list names no US state
    [V: agent].
  - **Entities:** through an institutional application at
    `institutional.kalshi.com`, which asks for formation documents, an entity
    bank statement, signers' IDs and proof of address. No minimum is stated, and
    "Entity accounts include Advanced API access by default" [V: agent]. There is
    also a **data-only** institutional application.
- **Cost.**
  - **Taker fee:** round-up(0.07 × C × P × (1−P)) to the next cent, at most
    1.75¢ per $1 contract at P = 0.50.
  - **Maker fee:** 0.0175 × C × P × (1−P), on maker-fee markets only.
  - **No settlement or membership fee**; ACH is free.
  - Schedule "effective Feb 5, 2026" [V, archived copy of 2026-06-12; [U] that
    it is unchanged today].
- **Size.** A "Position Accountability Level" of **$25,000 per member** per
  contract for FED, CPI, FEDDECISION, SHUTDOWN and NBERRECSS, and $25,000 per
  strike for PAYROLLS and TNOTE [V]. Since 2024-11-27 that level is a trigger for
  exchange review, not a hard cap [V: agent]. The Fed paper below says "maximum
  exposure per market currently reaches $7 million" [V text]. **The two are not
  reconciled; both are reported.**
- **Data.**
  - The market-data API is **public and keyless**, with an archive
    (`/historical/*`, daily, hourly or minute candles) [V].
  - But the Developer Agreement limits API use to "facilitating a members own
    trading on the Exchange" and prohibits "collecting, caching, aggregating, or
    storing data … except for purposes of facilitating your own trading on
    Kalshi".
  - The Data Terms limit site data to "personal use for non-commercial purposes"
    [V].
  - **So the per-family history, liquidity and spread measurement was NOT run.**
    The probe was written, then withdrawn unrun (§2.5). History and volume below
    come from a Federal Reserve working paper. Spreads are a stated gap.

**The best two uses for this desk.** Both stop at a zero-trial monitor, and both
need Kalshi's **written data authorisation** for the Kalshi part:

1. **Event-day risk flags** on the scheduled release calendar (FOMC, CPI,
   payrolls, GDP, Treasury auctions).
   - The calendar is free, public and point-in-time by construction (§3).
   - Kalshi would add a measured "how contested is this release" at the E−2
     decision.
   - The flag is a monitor first. It becomes a rule only if a written-in-advance,
     fit-period-only gate finds the book's P&L concentrated on release days
     (§2.9b). That rule would be a CEF trial behind the team lead's §2.3 ruling.
2. **Shutdown probability as a deal-timeline input.**
   - During the 2025 shutdown "issuers filed over 900 registration statements".
   - Statements without a delaying amendment went effective "after 20 days have
     passed by operation of law" [V, SEC Corporation Finance, 2025-11-13].
   - So a market-implied shutdown probability moves the expected close dates of
     mergers, de-SPACs and (inferred, [U]) CEF N-14 reorganisations and N-2
     rights offerings. It is a timeline-risk input, not a return signal.
   - **As a feature or a hedge Kalshi is weak here.**
     - Features: D7 at 8 FOMC meetings a year, and the FOMC drift idea is
       already parked.
     - Hedge: the payoff, timing and capital basis is wide, W14-A gives a hedge
       no job, and a real-money hedge would sit against a paper book (§2.9).

**Polymarket is available to US persons today, but only through the separate,
CFTC-regulated Polymarket US** (QCX LLC d/b/a Polymarket US).
- CFTC designation 2025-07-09.
- Amended order 2025-11-24 permitting FCM intermediation.
- Direct sign-up with SSN-level KYC.
- polymarket.com itself says "Trading is blocked in the United States on
  polymarket.com. Switch to polymarket.us." [V: agent]
- Nevada obtained a restraining order and an injunction in state court [S].
  Polymarket US lists fewer macro contracts than Kalshi (§2.10).

**Top five free alternative-data sources by value** (§3), all permitting reuse:

1. **SEC EDGAR**: submissions, full text and the filing's own SEC header. It is
   the event backbone for CEF tenders (SC TO-C/I), mergers (425, N-14), proxy
   contests (PREC14A, DFAN14A), rights offerings (N-2, 424B), SPACs and merger
   arbitrage (S-4, DEFM14A, SC TO-T). "free to access and reuse".
2. **The official release calendars plus Treasury auction data**: FOMC
   (federalreserve.gov), BLS (public domain), BEA (JSON/ICS), and Fiscal Data
   auctions (11,154 rows from 1979-10-31, with announcement dates). They drive
   macro event-day flags and are point-in-time by construction.
3. **SEC ownership data sets**:
   - Form 4 (2 business days; data sets from 2006);
   - 13D/G (5 business days; structured since 2024-12-18), for activists in
     CEFs;
   - 13F (45 days; data sets from 2013Q2);
   - N-PORT (fiscal-quarter-end month, 60-day lag; data sets from 2019-10).
   They feed pod ideas N4 and N6 and the activist watch.
4. **SEC fails-to-deliver**: twice monthly, from 2004, reuse permitted. A
   crowding and squeeze check on our shorts and on SPACs. **FINRA's short-interest
   and Reg SHO files are richer, but their terms are non-commercial (§3.2), so
   they need FINRA's permission first.**
5. **OpenFIGI and the NY Fed Markets API**.
   - OpenFIGI: identifiers "may be freely reproduced", 25 requests a minute
     keyless; the entity-resolution layer of pod note §6.1c.
   - NY Fed Markets: licensed for automated "personal or business purposes";
     repo, reverse repo and SOFR.

**What this pass found wrong on the desk's own data path. These need the team
lead, and are out of this note's scope to fix.**

- **CEFConnect's terms prohibit what the live collector does** [V, quoted §3.2].
  The nightly NAV fallback, `nav_crosscheck`, the per-slot `cefconnect_arrival`
  poll and the stale-NAV gate all read CEFConnect automatically for a commercial
  purpose. The terms say content is for "personal, non-commercial use". They
  also forbid "devices (including software) that are designed to provide
  repeated automated access" and any "data mining, robots, or similar data
  gathering and extraction tools", without Nuveen's written permission.
  `docs/SYSTEM.md` §5 lists CEFConnect among the "Free channels only" NAV
  sources. **Before real capital, either get written permission or replace
  it.** Yahoo's terms (yfinance, the primary NAV source) were not checked [U].
- **FINRA's equity data terms are non-commercial** [V: agent]. The website terms
  also bar use "in conjunction with a model, algorithm, or process that is
  designed to predict trades for … a fund". The POSITIONING work and G1a used
  FINRA files. Whether "professional use" covers a trading book is a question
  for counsel.
- **EDGAR's `acceptanceDateTime` is not reliably UTC** [V, measured, §3.3]:
  - **120 of 260** recent filings of the 13 deployed names are wrong. They are
    **later** than the filing's own SEC header by exactly that date's
    ET-to-UTC offset: 4 hours in summer, 5 in winter.
  - It is per registrant: DSL, JFR, MHD, MQY, PDI and PHK are 20 of 20; AWF,
    BIT, HYT, PCN, PDO, PFN and PTY are 0 of 20.
  - 32 of the 120 put acceptance outside EDGAR's 06:00–22:00 ET hours, which is
    impossible.
  - This corrects the rule in `docs/REFERENCES.md` §12j and pod note §3.6 before
    the event layer is built on it: **take `observed_at` from the
    `<ACCEPTANCE-DATETIME>` header (Eastern time), not the JSON.**

---

## 1. Scope, rules and what was touched

| what | how | auth |
|---|---|---|
| Kalshi | Documents only: docs.kalshi.com, the developer agreement, data terms, contract-terms PDFs and fee schedule (archived), CFTC orders. **A keyless API probe was written and withdrawn unrun** once the terms were read (§2.5). One research agent made about 10 keyless API GETs (series records, `/historical/cutoff`) **before** it had read the terms. It reported that, nothing it received is used here, and nothing was stored | none |
| Alpaca/Benzinga news | `scripts/events/alpaca_news_coverage.py`, `GET /v1beta1/news` | the desk's existing `cef` paper key, through `AlpacaClient`, read-only; keys never printed. **The one authenticated read in this note.** The team lead asked for the feed to be measured, and it has no keyless form |
| EDGAR | `scripts/events/edgar_acceptance_offsets.py`, through `scripts/data/edgar_client.py` (SEC user agent from the env file, 10 req/s ceiling, cache) | none (SEC contact header only) |
| Treasury auctions | three keyless GETs to the Fiscal Data API | none |
| Everything else | terms, rulebooks and regulator pages, fetched and quoted by the author or by two research agents, each listed in `docs/REFERENCES.md` §12y | none |

**Labels.** `[V]` means fetched and read on 2026-10-15 by the note's author;
`[V: agent]` means fetched and read that day by a research agent, which quoted
the source. `[S]` means a search snippet or secondary page only. `[U]` means
uncertain. Measured figures name their script. Nothing here keys a decision on a
written number (H14).

**Graveyard and ledger, checked first** (`/graveyard`, `docs/RESEARCH_STATE.md`):

- **POSITIONING** (FINRA short interest and daily short volume): 1 trial,
  `short-pressure`, D1, where the rates control scored higher.
- **NPORT**: 1 trial, `nport-trace-nav`, D7 infeasible.
- `dealer-constraint` and `raw-flow-z` (both D1) are the nearest dead relatives
  of any flow idea.
- The 2026-10-08 agenda **parked** post-FOMC drift and the macro-announcement
  premium as D7 or D4 (`results/cef/RESEARCH_AGENDA_2026-10-08.md` §3).
- W14-A (CLOSED): the book "is not short volatility in a sense that gives a
  hedging option a job" (`docs/SYSTEM.md` §2).
- Pod note N5 (short interest as a crowding check, POSITIONING) is already
  queued.

Nothing below re-proposes a dead row as a signal.

---

## 2. Part A — prediction markets

### 2.1 Kalshi's regulatory status

| fact | source | status |
|---|---|---|
| Designated contract market. The application ran "December 30, 2019 through September 17, 2020"; the order is dated **2020-11-03** | CFTC order `orgkexkalshidesignation201103.pdf` (date from the file name and from the 2025 amended order's recital "on November 3, 2020") | [V] text; date [V: agent] |
| Amended order, **2025-01-17**, permitting FCM intermediation | CFTC `orgdcmkexkalshiamord250117.pdf` | [V: agent] |
| Clearing: **Kalshi Klear LLC**, a DCO registered 2024-08-28 (it moved its clearing from MIAXdx) | CFTC DCO registry; help.kalshi.com "What is Kalshi Klear" | [V: agent] |
| Courts: the Sixth Circuit (2026-09-25) held that the **sports** contracts are not swaps, so state gaming law applies; it reasoned that "swap" covers events with a "financial, economic, or commercial consequence". The CFTC has sued nine states and stayed Michigan's unwinding (2026-07-14). Restrictions found are sports geofencing; none touches economic contracts | coindesk (snippet); CFTC press release 9267-26 | [S] Sixth Circuit; [V: agent] CFTC release; "economic contracts unaffected" is an inference [U] |

### 2.2 Eligibility

- **Individuals** [V: agent]:
  - "Be 18 years or older" (help centre, updated 2026-03-10).
  - The member agreement (dated 10.1.26) requires "the age of majority in Your
    state of residence". Its restricted list names about 55 countries and no US
    state.
  - Rulebook v1.29, rule 3.1: a US or acceptable foreign bank account, and no
    OFAC listing.
- **Entities** [V: agent]:
  - "Businesses, funds, and other entities can trade on Kalshi through an
    institutional account" at `institutional.kalshi.com`.
  - Documents: formation documents, an entity bank statement, signers' ID and
    proof of address.
  - "Entity accounts include Advanced API access by default".
  - A person cannot hold both a personal and an entity account.
  - No minimum is stated (a gap). A **data-only** application exists
    (`institutional.kalshi.com/application?type=data-only`).
- **Through a broker** [V: agent]: Kalshi lists Interactive Brokers, Robinhood,
  Webull, Clear Street, Apex, Coinbase and others as carrying Kalshi products.
- **Who would hold it is the counsel question** of the pod note (§7.5): the team
  lead personally, or the future fund vehicle. Not guessed here.

### 2.3 Fees

From the fee schedule, "Last updated and effective: Feb 5, 2026". Read from the
Wayback copy of 2026-06-12, because kalshi.com answered HTTP 429 (a Vercel
checkpoint) to every automated request. So [V] as of June 2026 and [U] for
today.

| item | rule |
|---|---|
| taker | `fees = round up(0.07 x C x P x (1-P))`, "rounds to the next cent". At P = 0.50 that is 1.75¢ per $1 contract: 3.5% of the 50¢ premium, or 1.75% of notional |
| maker (markets flagged for maker fees only) | `round up(0.0175 x C x P x (1-P))`; cancelling a resting order is free |
| INX / NASDAQ100 | `round up(0.035 x C x P x (1-P))` |
| settlement, membership | "There is no settlement fee." "There is no membership fee." |
| funding | ACH free; card deposits up to 2% [V: agent] |
| conflict, unresolved | docs.kalshi.com "Fee Rounding" says fees are computed to $0.000001 and balances kept to $0.0001, against the PDF's "rounds to the next cent" [V: agent] |

### 2.4 Position limits

- The current contract terms (`assets.kalshi.com/contract_terms/<FAMILY>.pdf`,
  generated 2026-09-29) say: "The Position Accountability Level for the $1
  referred Contract shall be $25,000 per Member".
  - Read for FED and SHUTDOWN [V].
  - The same text for CPI, FEDDECISION, NBERRECSS and INX [V: agent].
  - PAYROLLS and TNOTE read "$25,000 per strike, per Member" [V: agent].
- The 2021 product certifications called it a "Position Limit". A 2024-11-27
  rule filing replaced position limits with accountability levels [V: agent].
- Rulebook v1.29 defines the level as "the level of loss that can be incurred"
  [V: agent]. So the $25,000 is a maximum loss, not a notional.
  - Above it, a participant "must refrain from increasing … or reduce" if
    instructed (rule 5.18(c)).
  - Market makers can get higher levels (rule 4.5).
- FEDS 2026-010 (§2.6) says "Kalshi's maximum exposure per market currently
  reaches $7 million" [V text]. **Not reconciled** with the $25,000 level.
  Presumably it means exemptions or higher levels; that is [U], and neither
  figure is used for anything here.

### 2.5 Terms on data: why nothing was measured

The brief allowed measurement "read-only and only if the terms allow". They do
not.

**Kalshi Developer Agreement v1.1**
(`kalshi-public-docs.s3.amazonaws.com/Kalshi-Developer-Agreement.pdf`, last
modified 2023-11-09 [V: agent]; clauses read by the author [V]):

- §1 "Accessing or using Kalshi's API shall be considered a binding acceptance
  of this Agreement."
- §3 "Use of Kalshi APIs is expressly limited to facilitating a members own
  trading on the Exchange; all other usages are disallowed and may result in
  account suspension."
- §3.1 "Collecting, caching, aggregating, or storing data or content accessed
  via the API except for purposes of facilitating your own trading on Kalshi.
  You may not share such data or content with third parties in any manner
  without prior written authorization from Kalshi."
- §4.1.1 "You must be a Member of Kalshi's Exchange".
- docs.kalshi.com says: "By continuing to use or access Kalshi's API, you are
  agreeing to be bound to our Developer Agreement" [V: agent].

**Kalshi Data Terms of Use** (`kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf`,
last modified 2024-09-11 [V: agent]; read [V]):

- "You may access content only for your personal use for non-commercial
  purposes."
- It prohibits "electronically extracting or scrubbing, scraping, compiling".
- It prohibits use in "portfolio management services".
- It prohibits use for "machine learning and/or artificial intelligence".

**What follows.** A non-member desk collecting candlesticks for research, even
keyless and throttled, is outside both documents.
- A member may store API data only to facilitate its own Kalshi trading.
  Feeding a CEF book at Alpaca is not that.
- **Every desk use of Kalshi data as data needs Kalshi's written authorisation
  first.** The route is the institutional data-only application or
  institutional@kalshi.com. This is not legal advice. Whether the kalshi.com
  versions differ from these S3 copies is [U]: kalshi.com was unreachable to
  automated fetches.

**What was done about it.**
- `scripts/events/kalshi_public_probe.py` (a keyless, path-whitelisted,
  throttled probe) was written, then **deleted unrun** once the terms were
  read. It is not in the commit.
- A research agent made about **10 keyless GETs** (series records,
  `/historical/cutoff`) **before** it had read the terms, and reported that it
  had. **None of what those calls returned is used in this note**, and nothing
  was stored.

**Legitimate routes to the same facts**, short of authorisation:
1. **CFTC Part 16.** 17 CFR 16.01(a) requires each reporting market to record
   daily volume and open interest. 16.01(e)(1) requires it be made "readily
   available to the news media and the general public without charge … no later
   than the business day following" [V, eCFR at 2026-09-01]. That is a right to
   *see* it, not a licence to collect it systematically.
2. **Published research** that had the data (§2.6).
3. **The Fed authors' promised public data.** econfutures.com is a "Launching
   Soon" placeholder on 2026-10-15, and no replication repository was found
   [V].

### 2.6 History and liquidity: what a primary source that had the data says

Diercks, Katz & Wright, *Kalshi and the Rise of Macro Markets*, FEDS 2026-010
(Federal Reserve Board, February 2026; also NBER w34702). PDF read in full by the
author [V]. Table 1, first contract per series:

| family | first contract | frequency | relevance to this book |
|---|---|---|---|
| CPI MoM | June 2021 | monthly | rates, real-yield days |
| CPI YoY / Core CPI MoM / Core CPI YoY | Nov 2022 / Jun 2022 / Dec 2022 | monthly | same |
| Unemployment rate | July 2021 | monthly | labour-data days |
| Payroll release | March 2023 | monthly | same |
| GDP growth | Q2 2021 | quarterly | growth |
| Probability of US recession | 2022 | annual | credit-cycle tail |
| **Fed funds target rate** (per meeting) | **December 2021** | per FOMC | duration, muni versus taxable |
| Fed funds rate decision | May 2023 | per FOMC | same |

Treasury yields (TNOTE), government shutdown (SHUTDOWN) and the S&P (INX) have
current contract terms [V: agent], but the paper gives no history for them. **No
credit-event family (default, spread, bankruptcy) was found** in the contract
terms the agent fetched. That is a gap, not a negative: the full series list
sits behind the API and was not read.

**Liquidity** [V text, FEDS 2026-010 §2.3]:
- "recent periods have had volumes greater than a million for several strikes";
- "the peak recently reaching close to 100 million in volume for the September
  FOMC". The units are as the paper gives them; the meeting is presumably
  September 2025 [U].
- Market making "by firms such as Susquehanna".

**Spreads: a gap.** The paper gives no number. It only notes "occasionally large
spreads on tail outcomes", and uses last trades rather than bid–ask midpoints
because midpoints "spike quite a bit more" (Appendix A) [V text].

**What the history means for this desk.**
- FOMC history starts December 2021: about 39 scheduled meetings to date, at 8
  a year. That is arithmetic on the calendar, not a fetched count [U].
- CPI starts June 2021; payrolls March 2023.
- **Any conditional-return test on them is D7** (fewer than ~250 independent
  events) for years.
- And nearly all of that history is inside the 2023+ time holdout.

### 2.7 Contract families relevant to a credit, rates and CEF book

| family | what it settles on | use here | verdict |
|---|---|---|---|
| FED / FEDDECISION | target-rate upper bound / size of move at each FOMC | uncertainty of FOMC day; muni versus taxable tilt sensitivity | licence-gated; D7 as a signal |
| CPI, core CPI | BLS print | release-day flag | same |
| PAYROLLS, unemployment | BLS print | release-day flag | same |
| TNOTE | 10-year yield level | the closest to a rates hedge; still a binary | licence-gated; hedge rejected (§2.9c) |
| SHUTDOWN | OPM operating-status notices (Source Agency: Office of Personnel Management [V]) | **deal-timeline risk** for mergers, de-SPACs, N-14/N-2 | best single use (§2.9d) |
| NBERRECSS | NBER recession determination | credit-cycle tail; settles long after the fact | context only |
| credit events | none found | — | gap |

### 2.8 Measured liquidity and spread for two or three families: NOT RUN

Not run, by the terms (§2.5). What was tried:
- the keyless public API, withdrawn on reading the terms;
- the CFTC route (Part 16), which needs a human, not a collector;
- published research (§2.6), which gives history and volume but no spread;
- the authors' public-data site, not yet live.

**To close the gap:** obtain Kalshi's written data authorisation, then run a
keyless probe like the withdrawn one. It would measure, per family:
- first market and event counts across the live and historical tiers;
- volume and open interest per event;
- the close-of-day YES spread in the 7 days before each of the last 6 settled
  events.

### 2.9 How the desk could use them, without lookahead

**The timing comes first.** Under `shift(2)` a plan decided on the evening of *t*
fills at *t+1*'s close and earns *t+2*. Releases land inside the day: CPI and
payrolls at 08:30 ET, the FOMC statement at 14:00 ET, BEA at 08:30. So:

- **Orders sent on event day E fill after the release.** They trade at prices
  that already reflect it.
- **Positions held into E carry it.** They were filled at E−1's close, so they
  were decided on the evening of E−2.
- A rule that wants less risk *through* E must act at the **E−2 decision**.
  - The release calendar is published weeks or months ahead. The FOMC page
    lists 2027 already, "tentative until confirmed at the meeting immediately
    preceding it" [V: agent]. So using the date at E−2 is not lookahead;
    record the calendar row's own `observed_at`.
  - A Kalshi price used at E−2 must come from a candle whose `end_period_ts` is
    at or before that decision time. Assert it at run time (pod note §3.6).
- **Pod note §2.3 cannot de-risk.** It may only remove or shrink orders in the
  decided set. Closing a held position would add an order. So a §2.3 flag on
  E−1 only stops the book *adding* risk into E. De-risking means changing the
  E−2 plan, which is a CEF trial.

**(a) As features** (for example, market-implied FOMC probabilities against the
book's duration or credit exposure).
- *What.* The expected change and dispersion of the post-meeting target from
  the FED ladder, at the last candle before the decision time, interacted with
  the book's muni-versus-taxable tilt.
- *Why weak.* D7 for years (§2.6), and the history sits in the 2023+ holdout.
- *Graveyard.* Post-FOMC drift is already parked (2026-10-08 agenda). A
  Kalshi-scaled exposure is a cousin of "sizing up on dislocation" and of
  regime-switching ("vol targeting already exploits it continuously").
- *Licence.* Needed before any collection.
- *Counter.* Kalshi is a new source, so on the 2026-07-31 rule it would need its
  own counter, which only the team lead opens. A CEF-book change keyed on it is
  also a CEF trial. **This note opens nothing.**

**(b) As event-day risk flags for the runner (subtract-only, pod note §2.3).**
- *What.* A `calendar` producer row in the event log (`kind = macro_release`)
  for each scheduled FOMC, CPI, payrolls, GDP and coupon-auction date, from the
  official calendars (§3).
  - Under licence, Kalshi's ladder read at E−2 would go in `terms`: the modal
    probability and the mass outside the mode. "Contested" then becomes a
    measured quantity.
- *Then.* orient EVENTS and logs only, at zero trials (pod note §3.4.5).
- *The gate, written before anything is seen.*
  - Fit period only, to 2022-12-30; the time holdout stays sealed.
  - Take the canonical harness's daily gross P&L (`evaluate()`, live band,
    `shift(2)`). Compare scheduled-release days (FOMC, CPI, payrolls) with
    other days: the variance ratio and their share of total variance.
  - **If release days carry no more than their share of variance, the flag has
    no job, and the item closes.**
  - If they do, a subtract rule is a CEF trial with the team lead's §2.3
    decision behind it.
  - Whether Kalshi's uncertainty adds to the calendar alone can only be checked
    on 2022+, almost all holdout. It is D7 now.
- *Prior.* W14-A says the book is not short volatility in a way that gives a
  hedge a job. That is reason to expect the gate to close it, and reason to run
  the gate before building anything.

**(c) As a hedge, with the basis risk stated.**
- *Instruments.* The FED/FEDDECISION ladder, TNOTE, SHUTDOWN, NBERRECSS. No
  credit-event family was found.
- *Basis risk.*
  1. **Payoff.** A binary pays $1 on a discrete outcome. The book loses
     continuously on discount and spread moves. Its sensitivity to an FOMC
     surprise has never been measured: a gap, not a number.
  2. **Timing.** FOMC, CPI and payrolls settle within hours of the release.
     NBERRECSS settles on an NBER determination that can come long after the
     fact, while the book's losses accrue daily.
  3. **Size.** The $25,000 accountability level per contract, and depth that
     was not measured (§2.8).
  4. **Capital.** Contracts are fully collateralised: the premium is paid up
     front in a separate account and does not net against Alpaca margin. The
     fee at P = 0.5 is 3.5% of premium (§2.3).
  5. **Paper against real.** The book is scored on gross Alpaca **paper** P&L
     (D19/D20), so a Kalshi hedge would be real money against a paper book.
     Kalshi's demo environment uses separate credentials and is not the real
     market (docs.kalshi.com "API Environments"), so it would prove only
     plumbing.
  6. **Entity.** Who holds it is a counsel question (§2.2).
- *Verdict.* **No hedge use now.** Revisit only if gate (b) finds event-day
  concentration *and* real capital is live.

**(d) Shutdown and deal timelines: the use that survives best.**
- During the 2025 shutdown "issuers filed over 900 registration statements".
  One filed without a delaying amendment "will become effective after 20 days
  have passed by operation of law" (Securities Act §8(a), Rule 459). The backlog
  is processed "in the order in which they were received" [V, SEC Division of
  Corporation Finance, 2025-11-13].
- That page covers Corporation Finance only (S-1, S-4, F-4, so merger arbitrage
  and de-SPACs). Whether Investment Management's N-14 and N-2 reviews (CEF
  reorganisations, rights offerings) slowed the same way is [U].
- So a market-implied shutdown probability is a **timeline-risk input** for
  deal-spread arithmetic (expected days to close) in the merger-arb and SPAC
  jobs, and an expected-delay flag for CEF events in the event log.
  - The SHUTDOWN contract settles on OPM's operating-status notices [V, contract
    terms].
  - It is a monitor at zero trials, licence-gated, and not a return signal.

### 2.10 Polymarket, and IBKR's ForecastEx

**Polymarket for US persons: yes, through Polymarket US; no, on polymarket.com.**

| fact | source | status |
|---|---|---|
| Bought QCX LLC (exchange) and QC Clearing LLC (clearing house), announced 2025-07-21, reported price $112M | press report (mondovisione) | [S] |
| QCX designated a contract market 2025-07-09; the order barred FCM intermediation | CFTC `orgdcmqcexorderofd250709.pdf` | [V: agent] |
| Amended order 2025-11-24 to "QCX LLC d/b/a Polymarket US": the FCM bar "vacated and superseded" | CFTC "Polymarket US Amended Order of Designation" | [V: agent] |
| No-action letter 25-48 (2025-12-11): "Polymarket US is a designated contract market ('DCM') and Polymarket Clearing is a derivatives clearing organization ('DCO')" | CFTC Letter 25-48 | [V: agent] |
| US app opened to waitlisted users 2025-12-03 (sports first); waitlist removed on iOS 2026-05-12 | The Block; Covers | [S] |
| Lists "sports …, politics, crypto, economics, weather, tech, and culture"; sign-up with SSN-level KYC; institutional REST, gRPC and FIX APIs | docs.polymarket.us | [V: agent] |
| polymarket.com: "Trading is blocked in the United States on polymarket.com. Switch to polymarket.us."; the US is "Close-Only on Frontend and API" | polymarket.com/tos; docs.polymarket.com geoblock page | [V: agent] |
| Nevada: a state-court restraining order (2026-01-29) and preliminary injunction (about 2026-06-01) | trade press | [S] |
| Minimum age, excluded states, and Polymarket's data terms | not read | gap |

**ForecastEx** (Interactive Brokers):
- A CFTC DCM and DCO since 2024-06-25, accessed only through FCMs [V: agent].
- It lists jobless claims, unemployment rate, payrolls, CPI, fed funds target,
  GDP, national debt and others [V: agent].
- Its data terms were not read. The desk retired IBKR on 2026-09-28.

---

## 3. Part B — free alternative data

### 3.1 Inventory

"PIT" says whether a backtest can know what was known on a date. The "serves"
column covers: **CEF** (CEF events: tenders, mergers, rights, activists, NAV),
**SPAC**, **MA** (merger arbitrage) and **MACRO** (event days).

| source | URL / endpoint | history | latency | terms | PIT | serves | status here |
|---|---|---|---|---|---|---|---|
| **EDGAR submissions, full text, filing header** | `data.sec.gov/submissions/CIK##########.json`; `efts.sec.gov/LATEST/search-index`; `/Archives/edgar/data/{cik}/{acc}/{acc}.txt` | full EDGAR era | the submissions API updates with a delay "of less than a second"; filings after 17:30 ET (22:00 for 13D/G and Forms 3/4/5) are dated the next business day | **reuse permitted**: "free to access and reuse"; 10 requests/second, declared user agent | **the SEC header's `<ACCEPTANCE-DATETIME>` (ET) is the anchor. The JSON `acceptanceDateTime` is 4–5 h late for some registrants (§3.3)** | CEF, SPAC, MA | live in research (`fetch_edgar_events.py`) |
| **Form 4 / insider data sets** | `sec.gov/data-research/sec-markets-data/insider-transactions-data-sets` | Jan 2006 → Sep 2026, quarterly | Form 4 due "before the end of the second business day" | reuse permitted | filing header per filing; quarterly sets are as-filed | CEF (holders above 10% file Form 4), MA, SPAC (sponsor sales) | not built |
| **13D/G** | submissions API by form `SCHEDULE 13D`, `SCHEDULE 13D/A` | full era; structured XML from 2024-12-18 | 13D within 5 business days; amendments within 2 | reuse permitted | header time | CEF activism, MA | read ad hoc (§12j/§12k) |
| **13F data sets** | `sec.gov/data-research/sec-markets-data/form-13f-data-sets` | 2013Q2 →; 3-month windows since March 2024 | 45 days after quarter-end (confidential treatment up to 1 year) | reuse permitted | as-filed; known on filing date | CEF ownership (N4 overlap) | not built |
| **N-PORT data sets** | `sec.gov/data-research/sec-markets-data/form-n-port-data-sets` | Oct 2019 → Sep 2026, quarterly | public for the fiscal-quarter-end month, 60-day delay. Monthly public reporting postponed to **2027-11-17** (larger groups); a 2026-02-18 proposal would keep it quarterly | reuse permitted | as-filed | CEF leverage, asset coverage (N6), fund-of-CEF flow (N4) | NPORT counter 1 (`nport-trace-nav` D7) |
| **SEC fails-to-deliver** | `sec.gov/data-research/sec-markets-data/fails-deliver-data` (`cnsfails{YYYYMM}{a,b}.zip`) | from Feb 2004 (before 2008-09-16 only fails of 10,000+ shares) | twice monthly, about two weeks after each half-month; "We cannot guarantee that the data will be posted by a particular date" | reuse permitted | no posting date: use a conservative one | CEF shorts' crowding, SPAC squeezes | not built |
| **FINRA short interest** | `api.finra.org/data/group/otcMarket/name/consolidatedShortInterest`; files `cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv` | grid and API "five rolling years"; files from 2017-12-29 (earlier 403, §12p) | published the **7th business day** after settlement (2026: Sep 30 → Oct 9; Oct 15 → Oct 26) | **non-commercial only; bans robots and scraping, and use in a model "designed to predict trades for … a fund"**; the API needs a credential | revisions overwrite ("Only the most recent data is made available"); use the publication calendar | CEF crowding (N5), SPAC | POSITIONING counter 1; **needs FINRA's permission** |
| **FINRA Reg SHO daily short volume** | `cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt` | from 2018-08-01 | same day, by 18:00 ET | non-commercial (website terms; whether they cover the cdn host is [U]) | **originals kept; corrections marked "Updated"** | as above | `short-pressure` D1; **needs permission** |
| **Short-position reporting (Rule 13f-2 / Form SHO)** | — | — | exempt **until 2028-01-02**; first reports due 14 days after January 2028 | — | — | — | not live; FINRA's more-frequent short-interest proposal SR-FINRA-2026-012 **withdrawn** |
| **FRED / ALFRED** | `fred.stlouisfed.org/graph/fredgraph.csv?id=` (keyless) | per series | per series | public-domain series fine; **commercial use otherwise needs the Bank's consent**; ICE BofA series need ICE's written permission and now carry only 3 years | **ALFRED vintages** give what was known on a date | MACRO | in use (DGS3MO, SOFR, DFF); each series' FRED copyright label not checked here [U] |
| **Treasury auctions (Fiscal Data)** | `api.fiscaldata.treasury.gov/.../od/auctions_query`; `.../od/upcoming_auctions` | **11,154 rows; first auction 1979-10-31** [V, measured] | rows appear at announcement (`announcemt_date`) and results fill in place | **open**: "free, without restriction … commercial purposes"; no key | announcement date known; results without a time of day (overwritten in place) | MACRO (coupon-auction days) | measured here |
| **Release calendars** | FOMC `federalreserve.gov/monetarypolicy/fomccalendars.htm`; BLS `bls.gov/schedule/news_release/`; BEA `apps.bea.gov/API/signup/release_dates.json`, ICS | 2027 FOMC dates already listed | dates fixed ahead; FOMC "tentative until confirmed" | BLS "public domain"; Fed and BEA are government pages (terms not separately read) | **PIT by construction**: store each calendar row with its own observed date | MACRO | not built |
| **NY Fed Markets API** | `markets.newyorkfed.org/api/...` | per series | daily | **"use, copy, and distribute … for your personal or business purposes … manually or through an automated process"** | no vintages; revisions possible | MACRO (funding stress) | not built |
| **CFTC Commitments of Traders** | `publicreporting.cftc.gov` (Socrata) | legacy from 1986; TFF from 2006-06-13 | Friday 15:30 ET for Tuesday's data | government work (terms not read [S]) | publication day known | MACRO (Treasury futures positioning) | not built |
| **FTC HSR early-termination notices** | `ftc.gov/legal-library/browse/early-termination-notices` (API endpoint exists) | 28,163 records | "soon after the parties are notified" | API key and terms [U] | notice date | MA | not built |
| **OpenFIGI** | `api.openfigi.com` | — | — | identifiers "may be freely reproduced …"; 25 requests a minute keyless | — | entity resolution for all (pod §6.1c) | not built |
| **Wikimedia pageviews** | `wikimedia.org/api/rest_v1/metrics/pageviews/...` | from 2015-07-01 | daily | **CC0**; user agent required | stable | SPAC and MA attention (weak) | not built |
| **Alpaca/Benzinga news** | `data.alpaca.markets/v1beta1/news` | from 2015 | streaming | Alpaca market-data terms (the text is not committed: public repo) | `created_at` (UTC) | **CEF: no** (§3.4); BDC mergers partial | measured here |
| **CEFConnect** | `cefconnect.com/api/v3/pricinghistory/{T}/1Y` | daily 1Y; weekly from 1998 | evening | **PROHIBITED** for automated or commercial use without Nuveen's written permission (§3.2) | per-row `DataDate` | CEF NAV | **on the live path today** |
| **Sponsor press releases on wires** | PR Newswire, Business Wire, GlobeNewswire | — | minutes | **PR Newswire bans robots and is non-commercial**; Business Wire and GlobeNewswire terms unreadable (403) | wire timestamp | CEF, MA | use EDGAR instead (§3.5) |
| **Reddit** | Data API | — | — | **commercial use needs a separate agreement; scraping prohibited** | — | — | excluded |
| **StockTwits** | — | — | — | every page 403; unknown | — | — | treat as unavailable |

Sources and quotes for every row are in `docs/REFERENCES.md` §12y. Rows not
marked measured are [V: agent] unless the row says [S] or [U].

### 3.2 Terms that bind the desk today

- **CEFConnect** (`cefconnect.com/footer/legal.aspx`, "last updated on June 5,
  2013"; read by the author [V]):
  - "All Content is solely for your personal, non-commercial use or that of your
    clients. Accordingly, you may not copy, reproduce, … reuse, … or use for any
    commercial or unlawful purpose any Content … without Nuveen's express
    written permission."
  - Users may not "use devices (including software) that are designed to provide
    repeated automated access to the Web Site/Mobile Apps other than those made
    generally available by Nuveen; deep link or employ software or any automatic
    device, technology or algorithm, to 'crawl', 'scrape', search or monitor the
    Web Site/Mobile Apps".
  - Nor may they "make use of any data mining, robots, or similar data gathering
    and extraction tools".
  - The site says its data "are supplied by the service provider, Morningstar".
    `docs/REFERENCES.md` §8 already avoids Morningstar's own pages for the same
    reason.
  - **The desk reads CEFConnect automatically in four places**: the collector's
    NAV fallback, `nav_crosscheck`, the `cefconnect_arrival` poll and the
    stale-NAV gate (`docs/DATA.md`). A fifth is the C4 research build.
  - **This is the team lead's decision**: seek written permission, or replace
    CEFConnect with a licensed or sponsor-first-party NAV. Nothing is changed
    here.
- **FINRA** [V: agent]:
  - Website terms: "ONLY for your own non-commercial personal or professional
    use"; no "data mining, scraping or harvesting tools (including robots)";
    clause (m), no use "in conjunction with a model, algorithm, or process that
    is designed to predict trades for or within an individual portfolio, fund,
    or other investment vehicle".
  - API equity terms: "only for Developer's non-commercial personal or
    professional use".
  - The desk's POSITIONING trial and the G1a gate read FINRA files. Whether a
    research desk is "professional use" is counsel's question.
- **FRED** [V: agent, quotes via WebFetch]:
  - Personal, non-commercial use, except series marked "Public Domain" or
    "Copyrighted: Citation required", which "may be used for internal commercial
    uses".
  - "Copyrighted: Pre-approval required" series (ICE BofA) need the holder's
    written permission. REFERENCES §8 already caches ICE data gitignored, as
    licensed.
- **Yahoo (yfinance)**, the live NAV's primary source: **terms not checked in
  this pass** [U]. Flagged so it is checked with CEFConnect, not after.

### 3.3 EDGAR's `acceptanceDateTime` is late for some registrants (measured)

`python3 scripts/events/edgar_acceptance_offsets.py`, the 13 deployed names, 20
latest filings each, 260 filings with SEC-header acceptance times from
2025-08-22 to 2026-10-14. It compares the submissions JSON (taken as UTC) with
the `<ACCEPTANCE-DATETIME>` line of the filing's own SEC header (Eastern time,
converted with America/New_York's rules). Output in
`results/events/edgar_acceptance_offsets/`. [V, measured 2026-10-15]

| result | count |
|---|---|
| JSON equals the header (true UTC) | 140 |
| JSON 4 h later (all on EDT dates) | 95 |
| JSON 5 h later (all on EST dates) | 25 |
| late by exactly the date's own UTC offset | 120 of 120 |
| JSON earlier than the header | 0 |
| late JSON that, read as UTC, falls outside EDGAR's 06:00–22:00 ET hours (impossible) | **32 of 120** (0 of the 140 others) |

- **It is per registrant, not per filing.**
  - DSL, JFR, MHD, MQY, PDI and PHK: 20 of 20 late.
  - AWF, BIT, HYT, PCN, PDO, PFN and PTY: 0 of 20.
  - It is not per filing agent, form or hour.
- On five filings checked by hand, the filing index page's "Accepted" time
  equals the header every time.
- The pattern is what a second ET-to-UTC conversion would produce. That is an
  interpretation, [U].
- **What it changes.**
  - REFERENCES §12j recorded the JSON as UTC from HYT (898 of 907 consistent);
    HYT is one of the seven consistent names.
  - The event layer's `observed_at` (pod note §3.6) should take the SEC header,
    or the index page, and keep the JSON only as a cross-check that raises on
    disagreement.
  - A late JSON never causes lookahead. It can push a 17:00–22:00 ET filing past
    the evening decision, and so cost the book a day on exactly the filings
    (tenders, mergers) the eligibility layer exists for.
  - No code reads the field yet (`grep`, 2026-10-15).

### 3.4 Alpaca/Benzinga news, measured on our names

**Why.** The pod note listed Alpaca news as an event-log producer, guessed its
CEF coverage was "probably thin", and asked for it to be measured on the 44 names
(`results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §3.3).

**How.** `python3 scripts/events/alpaca_news_coverage.py` (`--offline` re-runs
from the cache), window 2015-01-01 → 2026-10-14. Outputs are in
`results/events/news_coverage/` and hold **counts, dates and ids only**; the
headlines are Benzinga's text, and this repository is public.

**Per name** (the 44 `cef_universe.csv` names) [V, measured 2026-10-15]:

| | value |
|---|---|
| names with at least one article | 44 of 44 |
| articles per name, median (min–max) | 44 (17–79) |
| of which **specific** (tagged with ≤ 3 tickers), median (min–max) | 6 (0–20) |
| distinct articles across all 44 names | 694 |
| keyword hits across the 1,860 name-articles | distribution 285, merger 6, activist 4, rights 1, **tender 0** |
| names with any article dated 2024 or later | 15 of 44 |
| control: HYG, all-time (specific) | 201 (115) |
| control: BKLN | 19 (8) |
| feed-alive control: AAPL, September 2026 alone | 252 (150) |

**Per year, all 44 names** (`universe_by_year.csv`):

| year | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| distinct articles | 12 | 10 | 16 | 90 | 37 | 76 | 179 | 160 | 91 | 14 | 6 | 3 |
| specific name-articles | 11 | 10 | 10 | 12 | 0 | 20 | 75 | 68 | 75 | 12 | 1 | 1 |

**Against the EDGAR event record.** The sample is every CEF/BDC episode in
`results/events/edgar_cef_bdc_episodes.csv` (the 2026-10-12 EDGAR fetcher) whose
first filing is on or after 2016-01-01 and whose fund still has a ticker: 458
episodes. The test: is there an article tagged with the ticker from 7 days before
to 3 days after the first filing, and does one name the event?

| kind (first forms) | episodes | any article in window | event-relevant article | relevant: before EDGAR / same day / after | in the 44: episodes / relevant |
|---|---|---|---|---|---|
| tender (SC TO-C, SC TO-I) | 201 | 14 | **3** | 1 / 2 / 0 | 26 / 0 |
| merger (425, N-14) | 150 | 29 | **17** | 4 / 13 / 0 | 26 / 1 |
| contest (PREC14A, DFAN14A) | 107 | 4 | **1** | 1 / 0 / 0 | 10 / 1 |

- Eleven of the 17 merger hits are BDC tickers (TCPC, BBDC, OCSL, SLRC, GBDC,
  CGBD, GSBD, CCAP, OBDC, LIEN, EQS). Six are CEFs (SOR, MMU, NZF, TYG, KYN,
  KIO). That split is a reading of the tickers [U].
- Of the 21 relevant hits, 15 fell on the day of the fund's first EDGAR filing
  and 6 fell 1–7 days before it. Whether another party's filing came earlier
  was not checked.

**Verdict.**
- **The feed does not cover closed-end funds as event news, and it has covered
  them less every year since 2022.** The 2018–2023 bulk was multi-ticker lists.
  It saw 3 of 201 tenders, and in 2024–26 it carried 23 articles across all 44
  names.
- **Do not build the event log's news producer for CEFs.** BDC mergers are
  partly covered, which matters only if a BDC sleeve is ever pre-registered.

**Limits.**
- Offsets are in New York calendar days from the EDGAR filing **date**.
- `ticker_now` is today's ticker: renamed funds are missed and merged-away funds
  are absent. Both bias coverage **down**, mostly for old events, yet 2024–26 is
  the thinnest period of all.
- Keyword relevance is crude, so it is shown beside the any-article count.
- Benzinga tags the tickers itself; an untagged article is invisible to a symbol
  query.

### 3.5 Sponsor press releases: use EDGAR, not the wires

- Registered funds file no 8-K. Rule 13a-11(b) excludes "investment companies
  required to file reports pursuant to § 270.30a-1" [V: agent, eCFR].
- CEF events reach EDGAR as other forms instead:
  - SC TO-C / SC TO-I, with the press release attached as EX-99.(A)(5);
  - 425 and N-14;
  - DEFA14A / DFAN14A;
  - N-2 and 497 (rights offerings).
- EDGAR full-text search, Jul 1 → Oct 14 2026 [V: agent]:
  - 415 SC TO-I / SC TO-I/A hits (agent's query, not limited to "closed-end");
  - for "closed-end": 46 DEFA14A, 28 N-14, 15 425 and 9 DFAN14A.
- The wires add minutes at best, and their terms are restrictive or unreadable.
  §3.4 shows the one wire we can query sees almost nothing.
- Full-text search returned no 13D hits for "closed-end fund". Structured 13Ds
  may not be text-indexed [U]. Use the submissions API by form type.

### 3.6 Top five by value for this desk

Ranked by event types served × point-in-time quality × terms × marginal cost to
the desk:

1. **EDGAR filings and the filing header.** Every CEF, SPAC and merger-arb event
   type. Reuse permitted. The header gives an exact `observed_at` (§3.3).
   Already partly built.
2. **Official release calendars and Treasury auctions.** Macro event days.
   Open terms; point-in-time by construction; trivial to build. It is the free
   half of use 1.
3. **SEC ownership data sets** (Form 4, 13D/G, 13F, N-PORT).
   - Activist accumulation in CEFs: a holder above 10% is a Section 16 insider
     and files Form 4 within 2 business days. Pod N4 and N6 inputs.
   - Reuse permitted; lags stated above.
   - N-PORT sits next to a D7 death (`nport-trace-nav`), so it is risk input
     only.
4. **SEC fails-to-deliver.** Crowding on our shorts and SPAC squeezes;
   permitted, unlike FINRA's richer files. Anything signal-like sits in
   `short-pressure`'s (D1) shadow and goes on POSITIONING.
5. **OpenFIGI and the NY Fed Markets API.** Entity resolution, which the event
   log needs before anything else (pod §6.1c), and funding-stress context.
   Licences permit automated business use.

**Deliberately not in the five:**
- CEFConnect: prohibited.
- FINRA: non-commercial terms.
- Benzinga: no CEF coverage.
- Kalshi: licence-gated (§2.5).
- Reddit: needs an agreement. StockTwits: unknown.
- Wikimedia pageviews: permitted but weak.

---

## 4. What this changes, and the next steps (none spends a trial)

| # | step | owner | cost |
|---|---|---|---|
| 1 | Decide CEFConnect: written permission from Nuveen, or a replacement NAV source. Check Yahoo's terms at the same time | **team lead** (live path; standing decision §5 "Free channels only") | 0 trials |
| 2 | Event layer: take `observed_at` from the SEC header, cross-check the JSON, raise on disagreement; correct REFERENCES §12j (done in this commit) | the event-engine job | 0 trials |
| 3 | If Kalshi is wanted as data: apply for written data authorisation (institutional data-only route) **before** any collection; then measure history, volume and spread per family (§2.8) | **team lead** (account/legal) | 0 trials |
| 4 | Build the release-calendar producer (FOMC, BLS, BEA, Treasury) as orient and log rows | production | 0 trials |
| 5 | Run gate 2.9(b), fit period only: do release days carry more than their share of the book's daily P&L variance? If not, close the flag | research | 0 trials (descriptive; a rule after it is a CEF trial) |
| 6 | FINRA: counsel's reading of "professional use", or FINRA's permission, before POSITIONING spends again | **team lead** | 0 trials |
| 7 | Do not build a Benzinga producer for CEFs | — | — |

---

## 5. Reproducers

- `python3 scripts/events/alpaca_news_coverage.py [--offline]` (needs
  `QUANTT_ENV_FILE`; cache `results/events/_cache_news/`, gitignored).
- `python3 scripts/events/edgar_acceptance_offsets.py [--offline]` (needs
  `QUANTT_ENV_FILE` for the SEC user agent; cache under the EDGAR client's
  gitignored cache).
- Tests: `scripts/events/tests/test_alpaca_news_coverage.py`,
  `scripts/events/tests/test_edgar_acceptance_offsets.py`.
- Everything else is a quoted document: `docs/REFERENCES.md` §12y.
