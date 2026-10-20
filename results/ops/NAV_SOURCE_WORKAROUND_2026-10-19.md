# NAV source: legitimate workarounds — 2026-10-19

**A follow-up to `results/ops/CEFCONNECT_TERMS_OPTIONS_2026-10-19.md` (REFERENCES §12ad).
Team lead, 2026-10-19: send the Nuveen letter, keep the live path and the stale-NAV gate
(`report`) unchanged for now, "or find a workaround". This note looks for routes whose
terms, read and quoted, permit this desk's use. It does not look for ways around terms.
Zero trials. No live-path code changed; one offline reader was added under `scripts/`.
Nothing was signed up for, logged into, or called with a key.** Branch
`ops-nav-workaround`, from main 6096ef9 (worktree HEAD 4a399e9). Live-path line numbers
are as of 4a399e9. Every external claim is in `docs/REFERENCES.md` §12ar.

**Reproduce.** The one set of counts, Tiingo's ticker list (§2), comes from
`python3 scripts/ops/nav_vendor_coverage.py --zip <hand-downloaded copy> --since 2026-10-01`
(offline by design; §8). Everything else is a page or file read, listed in §8.

**This is not legal advice.** It quotes published terms and says what our code does.
Whether a use is permitted is for the data owner, or a lawyer, to say. Every
"may we?" below is written as a question to put to the owner, never as a conclusion.

Fetches were made between 20:30 and 20:50 UTC on 2026-10-19 unless a row says
otherwise. Raw pages and files were kept in session scratch only, never committed: the
repository is public and the pages are vendor content. Labels: **[V]** read today on
the owner's own page or file, or in our own code; **[V: WebFetch]** quoted through
WebFetch's summariser, not the raw page; **[S]** sourced, not re-read (for example a
search-engine snippet of an owner's page that renders only in a browser); **[U]** not
established, with what was tried.

---

## 0. Read this first

1. **The binding licence is upstream: Nasdaq Fund Network (NFN).** NFN's data policy
   (v2.7, 2024-04-22) defines its "Information" to include "Net Asset Values" for
   "Funds", and "Funds" to include "closed end mutual funds". It defines a "Recipient"
   as "Any natural person, proprietorship, corporation, partnership, or other entity
   whatever that has access to Information". §6 then says: "In no event shall a
   Distributor or Recipient use the information ... for any trading, advisory or
   marketing purposes" [V]. The same policy says NFN's licence "does not include the
   right to create Derived Data unless otherwise approved by Nasdaq in writing" [V]. A
   discount is derived data.
2. **The paid vendors found carry CEF NAVs from NFN.** Tiingo's public ticker list has
   all 13 NAV symbols (`X<TK>X`) under the exchange code **`NMFQS`**, which is NFN's old
   name (the Mutual Fund Quotation Service) [V]. Cannon Valley Research, Intrinio's
   source for fund NAVs, says it works "in partnership with NASDAQ Fund Network" [V].
   IBKR's "US Mutual Funds" subscription appears to be NFN's dissemination service as
   well [S]. **So buying a feed does not, on its own, cure the trading-use clause.**
   Whether a vendor's contract passes §6 on to its customers is [U], and it is the
   question to ask first.
3. **No broker route is clean yet.** IBKR lists "US Mutual Funds" market data, "Fee
   Waived" for both non-professional and professional users [V]. Whether it carries the
   13 NAV symbols, and whether it reaches the API, are [U]. IBKR's API "ETF Nav" ticks
   are IBKR's own calculation from an ETF's holdings, not a fund's published NAV [V].
   Alpaca covers "US Stocks & ETFs" only [V].
4. **Every non-professional or personal-use definition found turns on a natural person
   using the data for personal, non-business purposes.** At least five sources name
   groups, associations or organisations as outside it. One offers academic pricing
   (EODHD); NFN invites enquiries about "fee exempt" use cases. The same definitions
   govern the market data the book **already** takes from Alpaca (§3.3). Whose name
   and whose capital the real-money account will use decides the answer everywhere.
5. **The stale-NAV gate could detect stale copies without CEFConnect, but it could not
   correct them** (§4). Ex-dates, an external proxy and the bond-market calendar are
   enough to flag the stale copies that do the most harm. A flagged name could only be
   held, never given a corrected NAV. None of this touches the primary source, Yahoo.
6. **Recommendation (§5).** Alongside the Nuveen letter, send two more free letters now:
   to Nasdaq NFN, whose answer decides whether any paid feed or IBKR can be used for
   trading; and to PIMCO and BlackRock, who between them sponsor 10 of the 13 names. Buy
   nothing until Nasdaq answers. Commission the CEFConnect-free gate design as a research
   measurement only. **This refines recommendation 3 of the CEFConnect brief**, which
   proposed a one-month EODHD trial in parallel with the NFN enquiry (§6).

---

## 1. Broker-provided data

### 1.1 IBKR (being opened as a second broker, equities only)

| question | finding | status |
|---|---|---|
| Does IBKR sell fund NAV data? | The market-data pricing page lists **"US Mutual Funds"**, United States, **"Fee Waived"** in both the non-professional and the professional column. Footnote 21: "These services can trigger Hosted Solutions fees." | [V] |
| What is its source? | An IBKR knowledge-base table, seen only as a search snippet, lists a "Nasdaq MFDS Exchange Access Fee", USD 150, against "US Mutual Funds (P, L1)" and "US Mutual Funds (NP, L1)". MFDS is Nasdaq's Mutual Fund Dissemination Service, which carries NFN/MFQS prices. The article (`ibkr.info/article/1852`) renders only in a browser and was not read. Who pays the access fee is not established | [S] snippet; [U] who pays |
| Does it carry the 13 CEF NAV symbols? | IBKR's public product search (the unauthenticated JSON behind its "Products and Exchange Search" page) returns nothing for XJFRX, XDSLX, XPTYX or XNADX, with types STK, ETF, IND and FUND requested. It returns JFR as a stock. **It also returns nothing for VINIX**, which IBKR's own API docs use as the FUND example, so the search does not cover FUND contracts at all. The test is uninformative | [V] the search; [U] coverage |
| Is it available through the API? | "IBKR allows for free on-platform data; however, data on the API is considered off-platform." Some free bundles are TWS-only. API market data also needs the "Market Data API Acknowledgement" signed in Client Portal. Whether "US Mutual Funds" reaches the API is not stated | [V] docs; [U] for this product |
| The ETF NAV ticks | Tick 96, "ETF Nav Last" (generic tick 577): "For ETFs: Calculation is based on prices of ETF's underlying securities. For NextShares: Value is provided by NASDAQ". Tick 97 is "Frozen Nav Last for NASDAQ-listed ETFs". Nothing names closed-end funds. These are not a CEF's published NAV | [V] |
| Mutual-fund contracts | `secType = "FUND"`, `exchange = "FUNDSERV"` (example VINIX). Whether an `X<TK>X` NAV symbol resolves as a FUND or IND contract can be tested only with a logged-in session | [V] docs; [U] |
| Non-professional status | "A 'Non-professional Subscriber' is any natural person (the definition of a natural person excludes corporations, trusts, organizations, institutions and partnership accounts) ..." The docs add: "By default, organizations such as corporations, limited liability companies, partnerships and any account where the data is used for more than personal investment purposes is deemed to be professional", and "By default, all users are classified as Professional Market Data users." | [V] |
| Use in our own automated trading | Nothing found in IBKR's pages forbids a non-professional from using Level 1 data in their own automated trading. The exchange agreements license non-professional data "only for personal use" (Nasdaq) and "solely for his/her personal, non-business use" (NYSE) (§1.2). **For fund NAVs, NFN §6 applies to any Recipient whatever the channel** (§0.1) | [V] text; [U] how IBKR or Nasdaq read it |
| Other conditions | Data is per username; a paper username sees data only if the live username shares it. Market data is "turned off" for accounts under USD 500 equity | [V] |

**Verdict on IBKR.** It may be the cheapest delivery route for NFN NAVs, because the
subscription is waived. It is not a licence to trade on them: §6 comes with the data.
Test once the account is open (read-only, after the team lead's login): resolve
`XJFRX` as FUND and IND; request one snapshot; record whether a value arrives, its
time and its date. Do this only after Nasdaq has answered §5's question.

### 1.2 Alpaca (documentation only)

| question | finding | status |
|---|---|---|
| Coverage | "Securities coverage: US Stocks & ETFs" on both Trading API plans. Basic is "Free" (IEX real time); Algo Trader Plus is "$99 / month" (all US exchanges). "Our data sources are directly fed by the CTA ... and the UTP ..." No page mentions fund NAVs (About Market Data, updatedAt 2026-10-06). The asset list held no `X???X` symbol on 2026-10-12 (§12ad) | [V] |
| Who the Trading API is for | "Trading API: For individual traders using Alpaca's trading platform directly"; "If you're a business integrating Alpaca as your backend brokerage provider, you're using the Broker API." | [V] |
| The data terms | Customer Agreement (V26.2026.07) §30: "AlpacaDB, Inc. provides market data to non-professional Alpaca customers. The terms 'non-professional' and 'nonprofessional' are defined within both the NASDAQ OMX Global Subscriber Agreement as well as the NYSE Market Data Display Services Agreement, and are incorporated by reference." Also: "I agree not to reproduce, distribute, sell or commercially exploit the market data in any manner without written consent from Alpaca." | [V] |
| NYSE definition (Alpaca's copy, "Last Update: March 4, 2013") | "'Nonprofessional Subscriber' means any natural person who receives market data solely for his/her personal, non-business use and who is not a 'Securities Professional.'" Its questionnaire asks, among others: "H. Do you use the capital of any other individual or entity in the conduct of your trading?" "I. Do you conduct trading for the benefit of a corporation, partnership, or other entity?" "J. Have you entered into any agreement to share the profit of your trading activities or receive compensation for your trading activities?" | [V] |
| Nasdaq definition (Alpaca's copy, "Version 2013.1") | Non-professional: "Any natural person who is NOT" registered with a regulator, an investment adviser, or employed by an exempt bank in a registrable role. "For Non-Professional or Private Subscriber, the Information is licensed only for personal use." "All subscribers are deemed Professional or Business unless they are qualified as Non-Professional or Private Subscriber." | [V] |

**Verdict on Alpaca.** No NAV, so no workaround here for the NAV itself. Alpaca's data
is the natural input for the CEFConnect-free gate triggers in §4: closes of proxy ETFs
and the corporate-action ex-dates, which the book already reads. The non-professional
question in §3 applies to that use too.

---

## 2. Free or cheap APIs

Coverage was read only from documentation or public pages, never with a key. The 13
names are `scripts/cef/spec.py` `UNIVERSE`, read 2026-10-19.

| source | the 13 NAV symbols? | timeliness | price (published) | the terms clause that matters | upstream |
|---|---|---|---|---|---|
| **NFN direct** (Nasdaq Fund Network Data Service, delivered through the Nasdaq Data Link streaming API) | Instrument code "C", "Mutual Fund – Closed End". "For closed-end mutual funds the NFN directory also relays the primary listing Market Identification Code (MIC) and trading symbol" [V]. Per-fund registration is [U] | Summary "spins" at 8:05 a.m., 6:05, 6:25 and 6:45 p.m., and "8:00 p.m., ET (Final)". Every valuation carries an **Entry Date**; a date "earlier than the current business date" is a correction, and Reporting Type "C" is a "Previous day fund price correction" [V]. That is the field the stale-copy problem needs | "the price list published on NasdaqTrader", not fetched (bot challenge) [U]. "To enquire about specific use cases that may be fee exempt, please contact your Nasdaq sales representative" [V] | §6 trading ban; Derived Data needs written approval; "Use of NFN Data to for validation or confirmation of any field ... must be licensed accordingly"; "Non Display always requires the Recipient to License directly with Nasdaq"; purge on termination [V] | itself |
| **Tiingo** | **All 13 listed**, `X<TK>X`, exchange **`NMFQS`**, assetType "Mutual Fund" [V]. Public file `supported_tickers.zip`, inner CSV stamped 2026-10-19 06:05 (no time zone), 109,072 rows | "Mutual Fund NAVs are available after 12 AM EST" [V: WebFetch]. The file's `endDate` ("The latest date we have price data available") was **2026-10-15 (Thursday) for 10 of the 13** and 2026-10-16 for AWF, MHD and MQY. Across the 392 `X???X` symbols ending on or after 2026-10-01: 194 at 10-16, 192 at 10-15, 6 at 10-13 [V]. So on Monday morning about half lacked Friday's NAV; whether `endDate` lags the API is [U] | $30/month individual; **$50/month ($499/year) "internal commercial use"**; Start-up, Enterprise and Institutional "start at $250 per month" [V] | ToS (last updated 2026-10-06) §7.3: "All data via the API is for internal consumption only. If you are an individual, you may sign up for an Individual plan; however, if you are representing an organization or business, you must sign up for a Commercial plan." §1.6(a): Starter and **trial** plans may not "retain Tiingo Data in any persistent or durable storage". §1.6(b): on a paid plan's end, delete everything "including ... backups". §1.6(c): "trading signals" are permitted derived products if they do not expose the data; a ratio of a Tiingo price with a public figure may be kept only "while a Paid Plan remains active". Nothing on trading use [V] | **NFN** (by its own exchange code) |
| **EODHD** | **All 13 have public pages** (`/financial-summary/X<TK>X.US`), each showing a value "as of October 16, 2026" when read at 20:38Z. The value sits in an element with id `adjustedClose` and has four decimals, so it is an **adjusted** series, not the published NAV. Whether the raw NAV is served is [U] | "US mutual funds ... update only the next morning, starting at 3-4 am ET and usually ending at 5-6 am ET" (§12ad) [S] | Commercial "Internal use / Single-company use" **$399.00/month** ($3,990/year), with a trial button; "Students get a 50% discount for 12 months on all subscriptions for educational purposes" [V] | Professional User includes anyone using the data "As part of a business activity, or On behalf of a group, organization, or any other individual or business"; prices "are indicative and not appropriate for trading purposes" [V] | [U]. Its pages say "We are not using exchanges data feeds for the pricing data", but its NAV symbols are NFN-shaped |
| **Financial Modeling Prep** | Docs list a "Mutual Fund Price Quotes API"; no mention of NAV or closed-end funds. The public summary page for XJFRX needs a login [V] | [U] | Personal plans $0, $29, $69, $139 a month; commercial plans ("Build", "Grow" — "internal usage") render only in a browser [U] | ToS (last updated 2023-08-01) §2.2.1: "In no event may the Customer use this licence on behalf of a company, partnership, organization, group, entity or any other third party." "Displaying or redistributing data sourced from FMP requires a specific Data Display and Licensing Agreement" [V] | [U] |
| **Alpha Vantage** | Docs cover "stocks, ETFs, and mutual funds"; no mention of NAV or closed-end funds. A symbol search needs a key, so it was not run [V] | [U] | Premium from "$49.99/month" (75 requests a minute) [V]. Commercial use is by agreement ("premium@alphavantage.co") | Terms PDF (modified 2026-08-27) §2(a): commercial use includes "using the Alpha Vantage Platform as or on behalf of a corporation, firm, partnership, trust or any other association and not as an individual" [V] | [U] |
| **Nasdaq Data Link** | Carries NFN's data service (row 1); "connecting to the API does require credentials, which are provided by Nasdaq during an on-boarding process" [V] | as NFN | [U] | as NFN | NFN |
| **Massive (formerly Polygon)** | The docs index lists Stocks, Options, Futures, Indices, Forex, Crypto, Economy, Alternative and Partners. No fund or NAV product [V]. Whether its stocks feed carries `X<TK>X` is [U] | — | Individual plans e.g. "$199 /month Individual use only" [V] | "Massive for Individuals Terms of Service apply to your personal, individual, and non-business use" [V] | — |
| **Intrinio** | "Mutual Fund Data": "Holdings, NAVs, and analytics for closed and open-end mutual funds"; "Source Cannon Valley Research"; "Enterprise Only"; "Are net asset values (NAVs) included? Yes, however a separate license is required" [V] | "Update Frequency Daily" [V]; time [U] | quote only [V] | [U] (not read) | Cannon Valley Research: "in partnership with NASDAQ Fund Network" [V] |
| **CEFA** (cefa.com) | Shows CEF data | — | free site | "All of the closed-end fund and interval fund performance information contained on this website was supplied by Lipper ... Any copying, republication or redistribution of LSEG Lipper content, including by caching, framing or similar means, is expressly prohibited without the prior written consent of LSEG Lipper." [V] | LSEG Lipper |
| **Enterprise** (Morningstar, LSEG Lipper, Bloomberg, FactSet, ICE) | not checked | — | unpublished [U] | not read [U] | Possibly not NFN, since Morningstar supplies CEFConnect and Lipper supplies CEFA [U] |

**What this table settles.**
- Two cheap vendors list all 13 NAV symbols. Before today both were [U].
- The cheapest commercial licence found is **Tiingo's Commercial plan**, $50 a month.
  The CEFConnect brief said EODHD's was the cheapest (§6).
- Every source whose upstream could be traced leads back to NFN or to a terms-restricted
  collector (Morningstar, Lipper). None found grants trading use in terms.
- Tiingo's trial plan forbids persisting data. A trial measuring timeliness would have to
  record only arrival times and match flags, never the values. Whether even that counts
  as a derived product is [U].

---

## 3. Could the desk qualify as non-commercial or educational?

### 3.1 The definitions, quoted

| source | definition or clause | what it turns on |
|---|---|---|
| Yahoo (§12ad) | "Unless otherwise expressly stated, you may not access or reuse the Services ... for any commercial purpose"; no definition of commercial found [U] | commercial purpose, undefined |
| CEFConnect / Nuveen (§12ad) | "solely for your personal, non-commercial use or that of your clients" | personal, non-commercial |
| PIMCO (§12ad) | "on an occasional basis for personal, scholarly, research or non-commercial purposes", and no scraping without written permission | the only "scholarly, research" wording found, but limited to occasional access |
| NFN | Recipient: "Any natural person, proprietorship, corporation, partnership, or other entity whatever"; §6 bars "any trading ... purposes" | **no carve-out at all**; fee exemptions by enquiry |
| NYSE (via Alpaca) | "any natural person who receives market data solely for his/her personal, non-business use"; questions H, I and J above | natural person; whose capital; for whose benefit; profit sharing |
| Nasdaq (via Alpaca) | natural person not registered or advising; "licensed only for personal use" | natural person; personal use |
| IBKR | natural person, excluding "corporations, trusts, organizations, institutions and partnership accounts"; professional if "used for more than personal investment purposes" | natural person; personal investment |
| Alpaca | "provides market data to non-professional Alpaca customers"; Trading API "For individual traders" | the two definitions above |
| Tiingo | individual plan for "an individual"; "if you are representing an organization or business, you must sign up for a Commercial plan" | individual vs organisation |
| EODHD | Professional includes use "On behalf of a group, organization, or any other individual or business"; student discount "for educational purposes" | group; educational purpose |
| FMP | personal licence never "on behalf of a company, partnership, organization, group, entity" | group |
| Alpha Vantage | commercial if "on behalf of a corporation, firm, partnership, trust or any other association and not as an individual" | association |
| Massive | Individual Use is "personal, individual, and non-business use" | non-business |

**Reading across.** No source found offers a category made for a student team that
trades. The words that recur, "group", "association", "organization" and "business",
are the ones a team may trigger. "Educational" appears only as a discount condition
(EODHD), and "scholarly, research" only with "occasional" access (PIMCO). Real money
makes "non-business" harder to claim; a paper account makes it easier. That is an
observation, not a conclusion.

### 3.2 The facts every provider will need

Have these written down before any letter goes. Most answers turn on them.

1. In whose name the real-money account will be held: an individual student, several
   individuals, a student club, the university, or another entity.
2. Whose capital it is (NYSE question H), and for whose benefit the trading is (question I).
3. Whether anyone shares profit or receives compensation (question J).
4. Whether anyone involved is registered or works in a registrable role.
5. That the software is in a public repository and the data are never stored in it.
6. That the account is paper today, with real money planned.

### 3.3 The questions to put (not conclusions)

- **To Nasdaq NFN:** does §6 bar a Recipient from using closed-end fund NAVs, received
  through a licensed distributor, to decide trades in those funds' listed shares for its
  own account? Is there a licence or a written waiver for that use, and at what price?
  Is there a fee-exempt or academic arrangement for a university student team? Does
  computing a discount (NAV against our own price) need Derived Data approval?
- **To Alpaca, and to IBKR once the account exists:** given the facts in §3.2, is the
  account's user a non-professional subscriber? This governs the prices, auction prints
  and corporate actions the book already reads, not only a NAV.
- **To Tiingo:** are CEF NAVs (exchange code `NMFQS`) delivered subject to NFN's §6, and
  does the Commercial plan permit using them in our own trading decisions? Is a student
  team "an organization"?
- **To EODHD:** what is the upstream of the `X<TK>X.US` series? Is the raw NAV served?
  Does "not appropriate for trading purposes" exclude this use? Does the student
  discount ("for educational purposes") cover a team trading a paper account, or a
  real-money one?
- **To PIMCO and BlackRock** (and DoubleLine and AllianceBernstein): may we read the
  daily NAV of the named funds automatically once a day for internal use? Do you
  offer a daily NAV file or e-mail list instead?

---

## 4. Reducing dependence: what could run on a source we may already use

**Design only. No code, no live change.** "A source we may use" here means Alpaca's data
under the customer agreement (subject to §3.3's question), our own captured panel, and
public calendars. Every design below **removes CEFConnect, not Yahoo.** The estimate
starts from the panel's previous NAV, and that value comes from Yahoo.

### 4.1 Per live use

The uses are L1–L4 as inventoried in
`results/ops/CEFCONNECT_TERMS_OPTIONS_2026-10-19.md` §1.1.

| use | what it needs | CEFConnect-free replacement | what is lost |
|---|---|---|---|
| L1 missing-NAV fill (`quantt/session/run.py:525` passes `--nav-fallback cefconnect`; `scripts/cef/fetch_daily.py:137`) | the NAV value | **None supplies a value.** Instead, treat a name with no NAV(D) as the gate already treats an unverified one: defer, then hold at its current shares from the final check | that name does not trade that day. Today a missing NAV with no fill makes `fetch_daily` exit 4 and the whole decide refuse |
| L2 gate trigger (2), `cc_prev` (`quantt/session/nav_gate.py:153`) | a second opinion that NAV(D) is really NAV(D−1) | triggers (a)–(c) in §4.2 | the PDI 2026-09-25 case (Yahoo's previous row was itself a copy) is caught only if the proxy moved differently on the two days |
| L2 gate resolution (`judge`, `nav_gate.py:286`) | the true NAV(D) | **none.** `on` would hold every flagged name and never replace a value | the gate's `cefconnect_stale_copy` replacement |
| L3 collector `nav_crosscheck` (`quantt/collect/collect.py:316`) | an independent NAV | a report-only plausibility flag: the panel's NAV change against the proxy estimate | the cent-level check. Only gross errors would remain visible |
| L4 collector `cefconnect_arrival` (`collect.py:658`) | CEFConnect's posting time | none needed | it exists only to time CEFConnect. Keep it while the Nuveen question is open, because a yes from Nuveen makes the arrival times matter (CEFConnect brief §5) |

### 4.2 Detecting a stale copy without a referee

The harm from a stale copy is the NAV move it skipped. A detector that fires when the
skipped move is large relative to its own noise therefore finds the harmful copies
first. Three triggers, none needing a second NAV source:

- **(a) Ex-date repeat.** On the ex-date "NAV drops too" by about the distribution
  (`docs/BRIEF.md` §3). Alpaca's corporate actions already list the book's ex-dates
  weeks ahead (`docs/DATA.md` §2). A NAV(D) equal to NAV(D−1) on a fund's own ex-date
  is suspect. It is cheap, but it covers only ex-dates: for a monthly payer, about 12
  of some 252 sessions a year.
- **(b) Proxy-implausible repeat.** Fix one proxy ETF per sleeve in advance from the
  fund's mandate (for example high yield, loans, munis), and do not sweep the choice. Fit
  each fund's NAV return on the proxy's close-to-close return, with the slope and the
  residual spread estimated only from dates strictly before D (state and assert this). A
  repeat is suspect when the predicted move is large against the residual spread. A
  shift test compares the reported change with the proxy's move on D and on D−1.
- **(c) Calendar exemption.** On a bond-market holiday when the NYSE trades (Columbus
  Day, Veterans Day; `docs/BRIEF.md` §3) a repeat is expected. Never flag on those days.

**What it would catch.** Repeats on days the asset class moved, which are the large
discount errors. Any ex-date repeat. Gross errors (a wrong fund, a decimal slip, an
unadjusted split) as L3 flags.

**What it would not catch.**
- Stale copies on quiet days. Their discount error is small, but every name's z moves
  with the cross-section.
- Fund-specific NAV moves that the proxy does not see: credit events, rights offerings
  (BIT 2025-08-19, §12n), tenders, leverage changes.
- Muni funds are matrix-priced and smooth. A genuine muni repeat on a day MUB moved is
  plausible, so (b) would hold some genuine repeats. AWF also carries currency moves.
- A wrong value that moves. And it can never say which of two values is right.

**Its cost.** False holds cluster on volatile days, when discounts move most. That
would bias live results against the backtest, so every hold must be recorded.

**Before any code: a research measurement** (scripts only, not the live path; it uses no
trial, because it decides no trade). On the 16 daily stale copies in the 2025-10-13 →
2026-09-25 window (§12n) and the 28 decide-time stale name-days on the laptop
(`results/cef/LIVE_NAV_QUALITY_2026-10-12.md` §5), measure the share each trigger catches.
Measure too how many genuine repeats it would have held: about a fifth of NAV rows repeat
genuinely (same note, §1). If (a) and (b) together catch most decide-time stale copies
and hold few genuine repeats, propose `on` as hold-only on these triggers. If not, the
gate needs a licensed referee. No threshold is written here (H14): the cut-off would be
derived from the measured residual spread at run time. Two caveats. The samples are
small (16 and 28). And the calibration history is the Yahoo and CEFConnect panel, whose
terms are the subject of this note.

---

## 5. Ranked shortlist

| rank | route | cost | what changes on the live path | risks | evidence |
|---|---|---|---|---|---|
| 1 | **Ask Nasdaq NFN** (draft §5.2) | $0 to ask | nothing now. A yes opens rank 4, the IBKR route, or NFN direct, whose dated entries and typed corrections fix the stale-copy problem at source | refusal; an unpublished price; Derived Data approval may also be needed | §6 and definitions [V]; vendor upstreams [V]/[S] |
| 2 | **Ask the sponsors**: PIMCO (PCN, PDI, PDO, PFN, PHK, PTY) and BlackRock (BIT, HYT, MHD, MQY) first, then DoubleLine (DSL) and AllianceBernstein (AWF). JFR is Nuveen's, covered by the Nuveen letter | $0; four letters | nothing now. A yes gives first-party NAVs: the best referee for L2–L3, and possibly the primary | four or five answers needed; PIMCO and AB fund pages not found (§12ad); posting times undocumented | terms [V] (§12ad) |
| 3 | **The Nuveen letter** (already decided) | $0 | keeps L2–L4 as built | as in the CEFConnect brief | §12ad |
| 4 | **A licensed vendor, only after rank 1 answers.** Tiingo first: $50/month, all 13 listed, NAVs "after 12 AM EST" | $50 a month or $499 a year, plus engineering | a licensed fetcher for the primary and the referee | §6 upstream; in the list stamped Monday 06:05, 10 of the 13 still ended on Thursday; trial data may not be stored; on cancellation all data must be deleted, and its P/E example says a ratio built on a Tiingo price may be kept only while a plan is paid, which reads on a discount panel | [V] list, ToS; [U] timing |
| 5 | **The CEFConnect-free gate** (§4): a measurement first, then code only on the team lead's say-so | engineering | L1 hold-on-missing; L2 triggers (a)–(c); L3 plausibility flag; `on` becomes hold-only | false holds on volatile days; cannot correct a value; leaves Yahoo in place | design only |
| 6 | **Enterprise feeds** (Morningstar, LSEG Lipper, Bloomberg, FactSet, ICE), if NFN refuses | unpublished | as rank 4 | cost unknown; terms unread | [U] |

**Not routes:** anything that changes how we look to a site (user agent, timing, address)
rather than what we are permitted to do. University-licensed terminals or the WRDS mirror
on the live path: their licences were not read, and `docs/DATA.md` §1 already keeps R2
off it.

### 5.1 Recommendation

1. **Now, at no cost:** send ranks 1 and 2 with the Nuveen letter. The Nasdaq answer
   comes first in importance: it decides whether money spent on any feed, or the IBKR
   route, buys data we may trade on.
2. **Keep the live path and the gate in `report`**, as ruled. Nothing in this note
   changes that.
3. **Buy nothing until Nasdaq answers.** Then Tiingo's Commercial plan is the cheapest
   test. Under its terms the test records only arrival times and agreement flags, not
   values, unless the plan is paid.
4. **Commission rank 5 as a measurement only.** If it works, the gate stops depending on
   CEFConnect whatever Nuveen says.
5. **Before real capital,** the primary NAV source has to be one whose owner has said yes
   in writing. The CEFConnect brief reached the same conclusion; this note adds that
   paying a vendor is not by itself that yes.

### 5.2 Draft enquiry to Nasdaq Fund Network

The team lead sends it from their own address. Bracketed items are theirs. It names no
account, server or vault.

> **To:** nasdaqfundnetwork@nasdaq.com
> **Subject:** NFN data for 13 closed-end funds: §6 trading use, licensing, and a student team
>
> We are [a university student team] running a small systematic research book in 13
> US-listed closed-end funds: AWF, BIT, DSL, HYT, JFR, MHD, MQY, PCN, PDI, PDO, PFN, PHK
> and PTY. It trades a broker paper account today; real money is planned [in an account
> held by …]. Each evening our software compares each fund's NAV with its market price.
>
> Your NFN Data Policies and Procedures (version 2.7, 22 April 2024), §6, say that "In no
> event shall a Distributor or Recipient use the information ... for any trading,
> advisory or marketing purposes."
>
> 1. Does §6 apply to a Recipient who receives these funds' daily NAVs through a
>    licensed distributor (a broker's market-data service or a data API) and uses them
>    to decide trades in the funds' listed shares for its own account?
> 2. If so, is there a licence or a written waiver for that use, and at what price? We
>    need one NAV per fund per day, non-display, on one server, with no redistribution.
> 3. Is computing a discount from the NAV "Derived Data" needing your written approval?
> 4. Your policy says "To enquire about specific use cases that may be fee exempt,
>    please contact your Nasdaq sales representative." Is there an academic or
>    fee-exempt arrangement for a student team?
> 5. Are the values distributed under symbols of the form X<TICKER>X (for example
>    XJFRX) NFN data?
>
> If this is the wrong address, please tell us whom to write to.
>
> [Name] · [e-mail]

A sponsor letter can follow §4 of the CEFConnect brief: change the addressee, the funds
and the quoted terms clause (§12ad), and add: "Do you offer a daily NAV file or e-mail
list we may use instead?"

### 5.3 Decisions for the team lead

1. **Send the §5.2 enquiry to Nasdaq**, from your address? It replaces the CEFConnect
   brief's "Nasdaq NFN enquiry" with a fuller one.
2. **Send sponsor letters**: PIMCO and BlackRock now, then DoubleLine and AB?
3. **Hold any data purchase until Nasdaq answers?** That revises the CEFConnect brief's
   recommendation 3, a one-month EODHD trial in parallel.
4. **Commission the §4 measurement** (research only, zero trials)?
5. **Write down the §3.2 facts** for the real-money account, in particular whose name
   and whose capital. Every provider's answer depends on them, including Alpaca's for
   the market data the book uses today.

---

## 6. Corrections and updates to the record (2026-10-19)

- `results/ops/CEFCONNECT_TERMS_OPTIONS_2026-10-19.md` §5, recommendation 3 (lines
  376–377 before this commit) said "EODHD's
  commercial internal-use plan is the cheapest published commercial licence found". Its
  own §3.4 table (line 273) shows Tiingo's Commercial plan at $50/month ($499/year) against
  EODHD's $399/month. Tiingo's ToS §7.3 makes that plan the one "an organization or
  business" must use. **Corrected there in place, dated.**
- The same brief's §3.4 Tiingo row and §6 item "Whether EODHD or Tiingo carry CEF NAVs
  (`X<TK>X`), and from which upstream" were [U]. **Answered:** both list all 13. Tiingo
  labels them `NMFQS` (NFN); EODHD's upstream is still [U], and its public value is an
  adjusted series. Noted there, dated.
- `docs/REFERENCES.md` §12ad: the Tiingo and EODHD rows' "[U] CEF NAV coverage" now
  point to §12ar.

## 7. Could not verify

- Whether IBKR's "US Mutual Funds" carries the 13 NAV symbols, reaches the API, and
  comes from NFN. Tried: IBKR's pricing page, its docs, its public product search
  (which does not cover FUND), and the knowledge-base article (browser-only; seen as a
  search snippet).
- Who pays IBKR's "Nasdaq MFDS Exchange Access Fee", and what "Hosted Solutions fees"
  would mean for a single account.
- NFN's price list (nasdaqtrader.com serves a bot challenge), and whether each of the 13
  funds is registered with NFN and reports by 8:00 p.m. ET.
- Whether Tiingo's `endDate` lags its API, and so its real NAV timing.
- EODHD's NAV upstream, and whether it serves the raw NAV.
- FMP's and Alpha Vantage's coverage of `X<TK>X` (needs a key), and FMP's commercial
  prices (browser-only).
- Whether Yahoo's `X<TK>X` values come from NFN.
- How the vendors' contracts treat NFN's §6, and how Nasdaq reads it.
- The terms of LSEG Lipper, Morningstar data feeds, Bloomberg, FactSet and ICE.
- The WRDS and university-terminal licences (flagged in §5, not researched).
- Anything legal.

## 8. Reproduce

The Tiingo counts in §2 are reproduced by
`python3 scripts/ops/nav_vendor_coverage.py --zip <path> --since 2026-10-01`, which reads
a local copy and opens no socket. There is deliberately no fetcher: Tiingo's ToS forbids
software that would "scrape" or download data "from any web pages contained in the
Website", so a person downloads the file its documentation offers, once, by hand, and
never commits it. Everything else is a page or file read, each a single manual request.

- **IBKR.** `https://www.interactivebrokers.com/en/pricing/market-data-pricing.php`
  (row "US Mutual Funds", footnote id `d-twenty-one`). Docs with `.md` appended under
  `https://www.interactivebrokers.com/docs/`:
  `general/market-data-subscriptions/{professional-vs-non-professional,tws-data-vs-api-data,compliance-requirements-for-api-market-data/market-data-api-acknowledgement}`,
  `tws-api/doc/md/streaming-data` (ticks 96–97), `tws-api/contracts/mutual-funds`. The
  product search is `POST https://www.interactivebrokers.com/webrest/search/products-by-filters`
  with `productSymbol` set and `productType` `["STK","FUND","IND","ETF"]`.
- **Alpaca.** `https://docs.alpaca.markets/us/docs/about-market-data-api.md`; from
  `https://alpaca.markets/disclosures`, `AcctAppMarginAndCustAgmt.pdf` §30,
  `NASDAQ+OMX+Global+Subscriber+Agreement.pdf` and
  `NYSE+Market+Data+Display+Services+Agreement.pdf` (`pdftotext -layout`).
- **NFN.** The policy PDF (sha256 e5409dbd…, as in §12ad) and
  `https://m.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NFNDS_NCDS.pdf`
  (sha256 fe746f75…). Both reachable only through WebFetch; `pdftotext -layout`.
- **Tiingo.** `https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip`
  (the copy read on 2026-10-19: zip sha256 e6deaaf8…), then the script above.
  `https://app.tiingo.com/tos`;
  `https://www.tiingo.com/about/pricing` and `/documentation/end-of-day` (WebFetch).
- **EODHD.** `https://eodhd.com/financial-summary/X<TK>X.US` for the 13;
  `/financial-apis/terms-conditions`, `/commercial-pricing`, `/pricing`, `/lp/universities`.
- **Others.** `https://site.financialmodelingprep.com/{terms-of-service,pricing-plans,developer/docs}`;
  `https://www.alphavantage.co/{terms_of_service,premium,documentation}/` (the terms URL
  serves a PDF); `https://massive.com/{legal/terms,pricing,docs}`;
  `https://intrinio.com/products/mutual-fund-data`; `https://www.cannonvalleyresearch.com/`;
  `https://www.cefa.com/legal-info/`.
