# The event-extraction engine: design, and a prototype on 50 filings — 2026-10-15

**What this is.** Job 1 of 6 of the special-situations sprint (team lead,
2026-10-15): the design of an LLM event-extraction engine for the desk, and a
prototype that measures how well a model reads the filings it would have to
read. It builds on `results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §3 (the event
log, its record, its state machine, `events_at(t)`) and §6.1a (LLMs reading
filings), `results/events/EDGAR_EVENTS_2026-10-12.md` (the fetcher: form-level
episodes, not terms) and `results/events/CONDITIONAL_TENDER_CENSUS_2026-10-13.md`
(the bottleneck: terms buried in prose).

**Zero trials.** No return, no P&L, no signal is computed; no counter moves; no
holdout is touched (every filing read is public text; no price of any name was
read). **No LLM API was called and no API key was used**: the team lead has not
approved API spend. The prototype's extraction was done by Claude agents (this
session's model, Claude Opus 5.5) reading the filings as the stand-in for the
model; token counts are therefore estimates, not measurements (§8).

**Reproduce.**

```bash
export QUANTT_ENV_FILE=/abs/path/config/.env           # SEC_USER_AGENT and Alpaca keys; never printed
python3 scripts/events/event_engine_sample.py --offline  # the 50 filings, chosen by rule, and their text
python3 scripts/events/event_engine_reconcile.py         # pass_a + pass_b + the written decisions -> gold
python3 scripts/events/event_engine_score.py             # span checks, agreement, precision/recall, cost
python3 scripts/events/event_engine_score.py --volume    # filings a year in the frame
python3 scripts/events/event_engine_news_coverage.py           # Benzinga coverage of the sample's events (read-only GETs)
python3 -m pytest scripts/events/tests/test_event_store.py
```

The code skeleton is `scripts/events/event_store.py` (schema, time key,
point-in-time query, validation hooks, the subtract-only contract), with its
tests in `scripts/events/tests/test_event_store.py`.

**Labels.** [V] measured by the scripts above on 2026-10-15, or a page fetched
that day; [S] sourced and not re-read; [U] uncertain. Sources:
`docs/REFERENCES.md` §12z.

---

## 0. The answer

- **The design** (§1–§6, §9) has six parts:
  1. **Sources.** EDGAR is the source of record. Alpaca corporate actions are a
     structured cross-check. Alpaca news carried **none** of the sample's CEF
     events, only 2 BDC mergers [V].
  2. **Polling.** About 3,000 requests a day, far inside the SEC's 10/s, under
     a desk-wide limiter.
  3. **The schema.** One schema per event kind. Every value is a triple of
     value, exact quote and document.
  4. **The store.** Append-only and hash-chained, queried point-in-time.
  5. **Validation.** Quotes are checked deterministically, along with
     arithmetic and structured cross-checks. Two independent extractions are
     made, and their disagreement routes a filing to review.
  6. **Feeding the runner.** The engine feeds the runner's subtract-only
     contract, which acts on the event's *kind* alone, so an extraction error
     cannot add risk.
  The skeleton is `scripts/events/event_store.py`, with 29 tests (no network,
  no model).
- **The time key changes, and this corrects the pod note** (§4) [V, 50 filings]:
  - **Read acceptance from the submission header, not the submissions API.**
    The API's `acceptanceDateTime` is one UTC offset late on **23 of 50**
    filings.
  - **Publication is not acceptance after 17:30 ET.** The SEC disseminates
    most evening filings the next business day. **7 of 50** would reach a
    22:00 ET decision 8–56 hours before publication if keyed on acceptance.
  - **The key is `observed_at = max(acceptance, 06:00 ET on EDGAR's filing
    date)`.**
- **The prototype** (§7), 50 filings chosen by rule (20 tender, 20 merger, 10
  rights), read twice blind and reconciled:
  - **Kind: 100%** in both passes.
  - **Terms:** precision 0.961 / recall 0.961 (pass A) and 0.977 / 0.979
    (pass B) against the gold, on 389 gold values.
  - **Numbers, percents and flags: 100%** (123 values). Dates: 98%.
  - **Hard: closing conditions** (0.81 precision and recall; mergers 0.74);
    the rights price formula when it has two legs (0.81, a schema gap); the
    tender commencement date (0.90, a definition gap); trigger origin
    (0.93); pro-ration stated in words (precision 0.80).
  - **Collars barely occur**: 2 filings, both "no collar".
  - 14 of the 26 adjudicated cells were definition gaps in the schema, not
    reading errors.
- **Cost** (§8), estimated from characters: tokens were not counted, because
  no API key was used. Per 1,000 filings, standard / batch, prices fetched
  2026-10-15 [V]:

  | input | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
  |---|---|---|---|
  | the whole filing (mean ≈ 142k tokens) | $69 / $35 | $300 / $150 | $601 / $300 |
  | the cover only, for triage | $0.38 / $0.19 | | |

  - At 7,070 event-form filings a year in the fund set (2025), triage costs a
    few dollars a year.
  - Terms on full text by Opus cost about $0.60 a filing.
  - **Cost is not the constraint; review is.**
- **The team lead decides** (§11):
  - API spend for a measured pilot: the three models on these 50 filings,
    about $49 standard or $24 batch, plus token counting;
  - the time-key rule;
  - schema 0.2;
  - the recall bar before anything reaches the live path;
  - a desk-wide EDGAR limiter.

---

## 1. Sources: where each event first appears

**EDGAR is the source of record; everything else is a cross-check or an
earlier hint.** The fund set is the fetcher's (`fetch_edgar_events.py`: 2,367
CIKs that filed a closed-end-only form, or an N-CSR plus a Form 3/4, since
2008; 442 of them have an exchange ticker today) [V].

| event kind | first EDGAR form (announcement) | terms live in | result / settlement | structured cross-check |
|---|---|---|---|---|
| CEF tender (issuer, any class) | SC TO-C (press release); 8-K item 8.01 for BDCs | SC TO-I + exhibit (a)(1)(i) "Offer to Purchase" | SC TO-I/A final amendment (shares tendered, accepted, pro-ration, price) | our NAV panel: price = % × NAV at expiry; arithmetic of pro-ration |
| conditional-tender programme | SC TO-C, DEFA14A, 425, N-CSR shareholder letter, press release (the census found 3 of 40 only by web search) | the same document | the triggered tender (above) or nothing | the census (`conditional_tender_programmes.py`); our close/NAV panels reproduce the published averages (81 of 81, census §4) |
| CEF / BDC merger | 425 (press release, often filed the evening of the announcement and published the next business day, §4), 8-K 1.01 (BDCs), N-14 8C / N-14 (registration), PRE/DEF 14A, DEFM14A | N-14 8C Q&A, "Summary", the agreement (conditions, termination) | 425 or 8-K on completion; N-8F of the target | Alpaca corporate actions (ratio, effective date, `stock_merger` / `cash_merger`); CRSP delisting code and amount (to 2024-12-31) |
| liquidation / open-ending / term change | PRE 14A, DEFA14A, 8-K, SC TO-C (HFRO's 2021 conversion rode on its tender) | the proxy | N-8F | Alpaca `worthless_removal`, `redemption`, `cash_merger` |
| rights offering | N-2 / N-2 POSASR, then 424B (prospectus supplement); press release | 424B cover and "The Offer" | 8-K / press release (subscription results) | Alpaca `rights_distribution` (record and expiration dates) |
| activist 13D | SC 13D / 13D/A (10 p.m. cut-off; amendments within 2 business days, §12j) | Item 4 (purpose), Item 5 (holdings) | DFAN14A, PREC14A (contest), settlement 8-K or SC TO-C | none structured; the index lists it under the subject fund |
| SPAC | S-1/424B4 (trust per unit), 8-K (deadline), DEF 14A / PRE 14A (extension vote), 425 (deal) | the extension proxy; the trust account section | 8-K (redemptions, trust balance after the vote) | Alpaca `redemption`, `name_change`; SPAC frame is not the CEF fund set (ss-spac job) |
| equity M&A | 8-K 1.01 + EX-2.1, 425, DEFM14A, SC TO-T / SC 14D9 | merger agreement (Articles on consideration, conditions, termination, fees) | 8-K 2.01 | Alpaca `cash_merger`, `stock_merger`, `stock_and_cash_merger` |

**Alpaca news (Benzinga), measured [V] (`event_engine_news_coverage.py`).** For
each of the sample's 36 events, the window ran from 30 days before to 3 days
after the EDGAR acceptance:

- 31 events have a ticker today; 13 have any article tagged to that ticker in
  the window;
- **2 have an article about the event**: both are BDC mergers. Barings BDC /
  Sierra led EDGAR by 46 seconds; SLR Investment / SLR Senior by 1.25 hours;
- none of the 11 tender events, the other 13 merger events (5 of them have no
  ticker today), or the 10 rights offerings had one.

So news is **not a source for CEF events**. It is an early hint for BDC and
operating-company M&A, where a press release can lead the 425 by an hour. In
the design it is a secondary producer whose only power is the subtract-only
rule (§6): a `kind` with no terms. The pod note's "measure it before relying on
it" is answered: coverage of CEF names is thin. The measurement uses today's
tickers; a 2021 ticker that has since changed would show as a miss.

**Alpaca corporate actions** carry settlement fields only (no declaration
date, no tender type; §12k). They are a deterministic cross-check of
extracted ratios, record and expiration dates, never the event's
`observed_at`.

---

## 2. Polling cadence within SEC fair access

**The limits [V, sec.gov, fetched 2026-10-15 through the EDGAR client].**

- "Current max request rate: 10 requests/second". The page does not say
  whether that is per process, per agent or per address.
- EDGAR accepts filings "Monday through Friday, from 6:00 a.m. to 10:00 p.m., ET".
- Indexes are "updated nightly starting about 10:00 p.m., ET; the process is
  usually completed within a few hours".
- Full and quarterly indexes are "rebuilt weekly, early on Saturday mornings",
  to take in post-acceptance corrections and deletions.
- The submissions API "is updated with a typical processing delay of less than
  a second", and its bulk ZIP is republished "nightly at approximately 3:00 a.m. ET".
- **"Some filing submissions that begin after 5:30 p.m. ET—or 10:00 p.m. for
  Ownership forms 3, 4, 5—will be disseminated the next business day, showing
  up in the following business day's index."**

**Measured one evening (2026-10-15, 21:07 ET, `getcurrent` Atom feed, 400
entries, 4 requests) [V].** Ownership forms and Schedule 13D/A appeared with
that day's filing date up to 21:05 and 19:56 ET. **No other form accepted after
17:31 ET appeared**, although EDGAR accepts filings until 22:00. That fits the
sentence above, and it contradicts the pod note's assumption (§3.6) that an
evening filing "can be visible on EDGAR in the evening while its filing date
says tomorrow". It is one evening's snapshot; the live poller measures it
continuously (below).

**Volume.** Event-form filings by the fund set [V]
(`event_engine_score.py --volume`, unique accessions):

| year | whole fund set | listed today | listed, by kind |
|---|---:|---:|---|
| 2021 | 5,252 | 2,797 | current 1,038, offering 856, vote 615, merger 173, tender 102, contest 13 |
| 2025 | 7,070 | 2,864 | current 1,171, offering 621, vote 618, merger 250, tender 134, contest 69, dereg 1 |

That is about 11 filings per business day for the listed funds and 28 for the
whole set (2025 ÷ 252). It excludes Schedules 13D/13G and every filer outside
the fund set (SPACs, operating companies).

**The cadence.** Request counts are the design's own arithmetic, not
measurements:

| loop | what | when | requests/day |
|---|---|---|---|
| **discovery** | the latest-filings Atom feed (`browse-edgar?action=getcurrent`), 100 entries, filtered to the fund set's CIKs and the event forms | every 60 s, 06:00–22:00 ET, EDGAR business days | 960 |
| **fetch** | the complete submission of each matching filing | on discovery | ≈ 11–28 (the volume above) |
| **watch-list reconciliation** | `data.sec.gov/submissions/CIK…json` for the book's names, their merger counterparties and today's plan names (about 30 CIKs) | every 15 min, 06:00–22:00 ET; once more at 21:50 ET before the 22:00 decide | ≈ 2,000 |
| **universe completeness** | the daily index for the day just ended | 02:00 ET (after the nightly build) | ≈ 1 + any filings the feed missed |
| **corrections** | the quarter's full index | Saturday 08:00 ET (after the weekly rebuild) | 1–2 |

That is about 3,000 requests a day, an average of 0.05 a second. A burst is
bounded by a **desk-wide** limiter: one token bucket shared by every process
on the machine. Today `edgar_client.RateLimiter` spaces requests within one
process only, and four sprint jobs used EDGAR from one address on 2026-10-15.
This job spaced its own requests 0.5 s apart for that reason. The feed is a
browse-edgar page, not one of the documented APIs [U on its durability].
The watch-list loop and the nightly daily index make discovery complete even
if the feed changes or drops entries. Every poll records its own `first_seen_at`
per accession, which turns the dissemination question above into a measured
series within a month.

---

## 3. The extraction schema

The schema is code: `scripts/events/event_store.py` (`KINDS`, `FIELDS`,
`TRIAGE`, `SCHEMA_VERSION = "event-schema/0.1 (2026-10-15)"`).
`agent_instructions()` renders it into the instructions the prototype's
readers used (`results/events/event_engine/extraction_instructions.txt`).

**Every value is a triple**: `{"value", "span", "doc_seq"}`. `span` is the exact
quote the value was read from, and `doc_seq` is the document of the submission
it sits in. A `set` field carries one span per element. A field the filing
does not state is null. The schema asks for **stated values only**: a percent
the reader would have to compute is null, with a note, because arithmetic is
the validator's job (§5), not the model's.

**Triage** (every filing): `kind` (the eight kinds or `none`); `fund_type`
(closed-end fund, BDC, interval or tender-offer fund, open-end fund, ETF,
SPAC, operating company, REIT, unknown); `doc_role` (announcement, offer
document, amendment, final result, registration or proxy, prospectus,
ownership report, other).

| kind | terms (types in `event_store.FIELDS`) |
|---|---|
| **CEF tender** | security class; price basis (% of NAV, fixed, Dutch auction, % of market); **price % of NAV**; NAV pricing date; **size** (% of outstanding, shares); **window** (commencement, expiration); pro-ration (stated or not); **conditions** (a set of categories, each with its own span); trigger origin (conditional programme, activist settlement, board, periodic liquidity, merger-related); results: shares tendered, shares accepted, **pro-ration factor**, final price per share |
| **merger** | acquirer; targets; number of targets; **exchange basis** (NAV-for-NAV, fixed ratio, cash, cash and stock); **exchange ratio**; **cash per share**; **collar**; **conditions** (set); **expected close** (as stated); **termination (outside) date**; meeting date; record date |
| **liquidation / open-ending / term change** | action; vote required; meeting date; expected effective date |
| **rights offering** | rights per share held; **rights per new share**; **price reference** (NAV, market, lesser of, greater of, fixed); **price %**; price floor as % of NAV; **record date**; **expiration date**; transferable; over-subscription privilege; maximum new shares |
| **conditional-tender programme** | threshold %; metric (daily close, VWAP, weekly close); window start and end; tender size %; tender price % of NAV; origin |
| **activist 13D** | filer; % owned; shares owned; event date; purpose (a set: board seats, tender or buyback, liquidation, open-ending, merger, proxy contest, other) |
| **SPAC** | **trust per share**; **redemption deadline**; **extension vote**; new deadline; extension contribution per share; target |
| **equity M&A** | acquirer; target; cash per share; exchange ratio; collar; conditions (set); expected close; termination date; termination fee |

Condition categories are shared across kinds: shareholder approval,
regulatory approval, registration effective, tax opinion, listing,
financing, minimum tender, market disruption, legal injunction, RIC or tax
status, board discretion, NAV or price decline, other.

**Two schema lessons from the prototype** (§7), both fixable in version 0.2:

- **Rights pricing.** The Clough rights offerings priced at "85% of the
  reported net asset value or 95% of the market price per common share,
  whichever is higher" cannot be held by one `price_reference` and one
  `price_pct`. Pass A encoded it as market 95% with a floor of 85% of NAV,
  which gives the same price. Version 0.2 should carry two legs:
  `{reference, pct}` × 2 plus a combiner.
- **Tender size is often a "lesser of".** FS Global Credit and MSC Income cap
  their tenders at the lesser of a share count and a percentage of weighted
  average shares. Version 0.2 should allow a list of caps with a combiner.

---

## 4. Point-in-time storage keyed on publication, not filing date

**The store** (`EventStore`): append-only JSONL, one row per extracted event per
filing (`row_id = "edgar:<accession>:<n>"`), hash-chained (`prev_hash`,
`hash`), deduplicated on `row_id`. The same `row_id` with different content
raises. A correction is a **new row** with `supersedes=` and its own
`recorded_at`, so a review dated Thursday cannot change what Wednesday's
decision knew. A row cannot be recorded before it was observable (the
constructor raises).

**The time key, as measured on the 50 filings [V] (`time_keys.csv`).**

1. **Acceptance comes from the submission header, not the submissions API.**
   The header's `ACCEPTANCE-DATETIME` is Eastern wall-clock time. EDGAR's
   filing index page prints the same digits as "Accepted" on all 4 filings
   checked. The submissions API's `acceptanceDateTime` (UTC, trailing Z):
   - equals the header on **27 of 50**;
   - is **later by exactly the Eastern UTC offset** (4 h in summer, 5 h in
     winter) on **23 of 50**, a double conversion;
   - never differs by anything else.

   Independent check: under the 17:30 rule (17 CFR 232.13), the header time
   is consistent with EDGAR's filing date on 50 of 50 filings (48 strictly;
   two Clough 424B2s were accepted 31 and 45 seconds after 17:30 and kept
   their day, because the rule turns on when transmission *commences*). The
   API time is consistent on only 38 (36 without the grace).
   - Errors cluster by filing, not by agent or hour: three Eaton Vance
     results amendments were accepted two minutes apart on 2021-08-03, and the
     API is right on two of them and wrong on the third.
   - The error is always **late**, so keying on the API loses information
     rather than leaking it. But 4–5 hours late moves a 17:09 filing past the
     22:00 decide.
   - **Correction to `docs/REFERENCES.md` §12j**, which read the API time as
     UTC on the strength of one HYT Form 3 and "898 of 907 HYT filings fit UTC
     plus the cut-offs". A cut-off test cannot see an error that leaves the
     date unchanged, and the header comparison here does. The §12j row is not
     wrong for that Form 3; it is not general.
2. **Publication is not acceptance for an evening filing.** Per the SEC's own
   statement and the one evening measured (§2), a non-ownership filing accepted
   after 17:30 ET is disseminated on the next business day.
   - 7 of the 50 sample filings were accepted after their cut-off and carry the
     next business day's filing date: an SC TO-I at 17:41, two 425s at 21:00 and
     21:38, three N-14 8Cs at 18:06, 21:48 and 21:54, and an SC TO-C at 21:41 on
     a Friday.
   - Keyed on acceptance, **each would reach that evening's 22:00 ET decision 8
     to 56 hours before it was published**: lookahead.
3. **The rule** (`event_store.observed_at`):
   `observed_at = max(acceptance, 06:00 ET on EDGAR's filing date)`.
   - The filing date already encodes the cut-offs and the federal-holiday
     calendar, so the rule needs no holiday table.
   - 06:00 ET (EDGAR's opening) as the hour a held filing goes out is an
     assumption [U]; the live poller's `first_seen_at` replaces it wherever it
     exists.
   - For research: a filing dated *t* is known to *t*'s 22:00 decision; an
     evening filing is not. That is what the fetcher's docstring assumed.
4. **The decision time in research** is 22:00 ET on *t*
   (`research_decision_time`), the earliest evening slot of the runner
   (`docs/RUNNER.md`). A backtest can then only know less than the live runner
   did.
   - A decision at *t*'s **close** keyed on the filing date would leak: **29 of
     the 50** filings were accepted between 16:00 and 17:30 ET on their own
     filing date.
   - So any close-time consumer must lag the filing date by a day (the
     fetcher's docstring says so).

**Fields per row** (the pod note's §3.1 record, as built in `EventRow`):

- `row_id`, `source`, `kind`, `cik`, `symbols`, `form`, `filing_date`;
- `observed_at` (the key), `recorded_at` (when written), and `time_check` (the
  header-versus-API verdict, or `first_seen`);
- `effective_at`, `status` (EXTRACTED, UNPARSED, REVIEWED, REJECTED), `terms`,
  `triage`;
- `extraction`: method, schema version, extractor, model, prompt SHA-256;
- `confidence`, `review`, `supersedes`, `backfilled`, `raw_ref`, `prev_hash`,
  `hash`.

**The point-in-time query** (`EventStore.events_at(t)`):

- A row is visible if `observed_at ≤ t` and `recorded_at ≤ t`, with the
  supersessions recorded by *t* applied.
- Research replaying history with rows extracted in 2026 sets
  `include_backfilled=True`. Those rows are still gated on `observed_at`, are
  marked `backfilled`, and every result is reported with and without them
  (pod note §3.6).
- A runtime assertion raises `LookaheadError` if any returned row is observed
  after *t*.
- Each guard has a test that fails when the guard is removed (checked by
  mutation, 2026-10-15): header-as-UTC, no `observed_at` filter, no
  supersession time, no subtract block, acceptance as publication.

---

## 5. Validation: a span for every number, and arithmetic wherever structure exists

1. **Span check** (`verify_spans`):
   - every non-null value's quote must occur in the filing's text after
     `normalise`, which drops case, curly quotes, dashes, table separators,
     whitespace, cp1252 characters that arrived as C1 controls, and zero-width
     characters;
   - a quote that is not there is a **failure**, never dropped.
2. **Value-in-span** (`value_in_span`): the number or date must be readable off
   its own quote. This catches the model that quotes the right sentence and
   types the wrong figure.
3. **Consistency checks** (`consistency_checks`):
   - tender: accepted ≤ tendered; pro-ration = accepted ÷ tendered, to 0.1 point;
     final price = price % × NAV at expiry from **our NAV panel**, to a cent;
   - rights: the percent lies in (0, 100];
   - merger: a ratio needs a ratio-type basis.
4. **Structured cross-checks**, where structure exists:
   - Alpaca corporate actions: merger ratio and effective date; rights record
     and expiration dates;
   - CRSP delisting code and amount (completed mergers; matched filed ratios
     to 6 decimals in SCALING §7.1);
   - the conditional-tender census;
   - the header-versus-API time check (§4);
   - the 17:30 filing-date rule (`filing_date_consistent`).
5. **Dual extraction** (pod note §6.1a): a rule-based parser for the easy
   fields (price % of NAV, size %, dates on SC TO cover pages) runs beside the
   model. Disagreement goes to review, and the live path uses the more
   restrictive reading. Not built: the prototype measures how far the model
   alone gets (§7).

Measured on the prototype (§7): of 531 non-null values per pass:

- pass A had 5 quotes that were not verbatim, all in two GDV filings, where the
  reader dropped invisible cp1252 quote characters (a defect of this job's text
  renderer, §12);
- pass B had 2 values the value-in-span check rejected, and both were values
  the reconciliation also rejected (pro-ration "100" read from "all ...
  accepted");
- the gold has 0 failures.

The validator is necessary, not sufficient. It caught 2 of the 29 wrong cells.
The other 27 were classifications, condition sets and definitions, which no
quote check can see. The two-reader diff exposed 25 of the 29.

---

## 6. Feeding the runner's subtract-only consumers without lookahead

The consumer contract is `event_store.subtract_only` (pod note §2.3, still a
proposal for the team lead):

- **It acts on `kind`, not on terms.** A name with an open live-path event
  (tender, merger, liquidation, rights offering, conditional-tender programme)
  may not increase its short exposure. A sell is cut to the part that only
  flattens a long; buys and covers pass. An extraction error in a term can
  therefore never add risk. The worst a wrong `kind` does is block a short
  that was fine.
- **UNPARSED is restrictive.** A filing the extractor could not read is a row
  with `status=UNPARSED` and the form's kind, and it blocks like an event
  (pod note §3.7).
- **A stale feed blocks every new short.** If the discovery loop has not
  succeeded within its declared age (`events_fresh=False`), no order may
  increase short exposure on any name. Longs and reductions trade.
- **It never adds, grows or flips**: the function asserts it, and the tests
  check it against a plan.
- **Timing** (pod note §2.2):
  - the decide at 22:00 ET reads `events_at(decision time)`, and the event ids
    it used go into the plan record, so `plan_sha` covers them;
  - the send step re-reads `events_at(now)` and may only subtract;
  - on paper (`late_market`) that is an edit to the saved plan before 15:52;
  - on a live account it would be a confirmed cancel before 15:50, which is
    the team lead's open decision (pod note §9).
- **Terms reach sizing only after review.** An event sleeve (E1, the
  conditional-tender tracker) uses terms such as the ratio, the price % or the
  window only from rows whose `review` is `accepted` or `corrected`.

---

## 7. The prototype: 50 filings, two blind readings, one reconciliation

### 7.1 The sample, chosen by rule before reading

`event_engine_sample.py` declares the rule in its docstring.

**Frame.** The fetcher's fund set, restricted to funds with an exchange ticker
in the SEC file of 2026-10-12, with 2021 events.

**Strata:**

| stratum | rule | filings |
|---|---|---|
| T | from each 2021 tender episode, one per first-filing day: the offer document (first SC TO-I) and the final amendment | 20 |
| M | from each 2021 merger episode, one per day: the announcement and the first N-14 8C, N-14 or merger proxy | 20 |
| R | 2021 424B filings with a rights-offering phrase on the cover, one per fund | 10 |

**Two amendments, each made before any affected filing was read**, are in
the docstring:

1. M fell short (15 of 20). A second tier, funds without a ticker today, now
   fills it. This admitted four open-end fund reorganisations, from the fund
   set's known ~10% open-end false positives. They stay in the sample: kind
   `merger`, `fund_type` open-end or ETF, which triage must get right.
2. R's first keyword rule admitted ten BDC debt and shelf supplements. This
   was seen from forms and company names only. R now needs the phrase on the
   cover page. 9 of the 10 first admissions fail the new rule
   (`sample_meta.json`).

**The 50 filings:**

- **Forms:** 10 SC TO-I, 9 SC TO-I/A, 1 SC TO-C, 9 N-14 8C, 4 N-14, 7 Rule 425,
  8 424B2 and 2 424B1.
- **Kinds (gold):** 20 tender, 19 merger, 1 equity M&A (RMR Mortgage Trust, a
  former CEF that had become a REIT), 8 rights offerings, and 2 `none` (a BDC
  notes supplement and a base shelf prospectus).
- **Two readers added second events:** the Eaton Vance conditional-tender
  programme and the HFRO conversion. Only the first event is scored.

**Known limits of the sample:**

- survivorship (listed today);
- near-duplicates: three Clough rights offerings on one template, and four
  Eaton Vance tender filings;
- three event kinds absent: activist 13D, SPAC, and all but one equity M&A.

### 7.2 Two blind readings, then reconciliation

- **The readers.** Every filing was read twice by separate Claude Opus 5.5
  agents (18 batches; pass B was batched differently from pass A). They
  worked from `extraction_instructions.txt`, which is rendered from the
  schema.
- **Blindness.** No reader saw another's output. Pass B ran after pass A
  because of the subagent limit and a usage cut-off. Pass A's files were
  moved out of the readers' tree before pass B started.
- **One rule breach.** A pass-A reader's parse check globbed the shared pass-A
  folder and printed five other pass-A summaries (accession, kind, count). It
  was within pass A only.
- **The readers searched rather than read.** The harness reported about 1.5M
  tokens for pass B's 50 filings, against about 7M tokens of text [U: what the
  harness counter counts].

**Reconciliation** (`event_engine_reconcile.py`, `reconciliation.csv`):

- Each of the 24 disagreeing cells was decided against the text, with a cause
  and a reason.
- **Audit.** A merger-conditions disagreement exposed a rule. Auditing that
  field across the stratum found 2 more cells where both readers agreed and
  were both wrong: the three Nuveen agreements' §7.4, a pre-closing
  distribution in "Conditions precedent".
- **Spot check.** A seeded random 40 of the agreed non-null values were
  re-read against the text (`spot_check.csv`). **39 were right.** The one wrong
  value is the same Nuveen omission.

**The gold's rules** (for schema 0.2 to write down):

- stated values only;
- a price "equal to the net asset value" is 100% of NAV;
- "all shares were accepted" or "N/A" states no pro-ration factor;
- the commencement date is the Offer to Purchase's date unless the filing
  states another start;
- a termination right is not a closing condition;
- a required pre-closing distribution of all income is `ric_or_tax_status`;
- the record date is the vote's;
- open-end share classes are `other`, not `common`.

**The gold is adjudicated by the same model family as the readers.** Its
definitional rulings went to pass B 10 times and to pass A twice, so the
A-versus-B gap partly reflects the rules, not reading skill.

| cause of a disagreement (24 cells, plus 2 audited) | cells |
|---|---:|
| definition: the schema left the field ambiguous | 14 |
| reading: one reader missed or misread a stated value | 4 |
| judgement: a classification resting on inference | 4 |
| text conflict: the filing contradicts itself (MacKenzie's 13.3M "accepted" against $353,386.47 paid at $6) | 2 |
| both wrong (audit) | 2 |

### 7.3 Field-level agreement and accuracy [V] (`scores.json`, `field_scores.csv`)

- **A against B:** kind 100% (50 of 50). Terms: **96.1% of 585 cells**, and
  94.2% of the cells where either reader wrote a value.
- **Against the gold:**

| class (scored terms) | gold values | pass A cell accuracy | pass B cell accuracy | pooled precision / recall |
|---|---:|---:|---:|---|
| numbers (sizes, prices, ratios, share counts, rights ratios) | 66 | 1.000 | 1.000 | 1.000 / 1.000 |
| percents (price % of NAV, size %, subscription %) | 41 | 1.000 | 1.000 | 1.000 / 1.000 |
| flags (transferable, over-subscription, pro-ration stated) | 16 | 1.000 | 1.000 | 1.000 / 1.000 |
| dates (expiry, record, meeting, termination, commencement) | 69 | 0.956 | 1.000 | 0.985 / 0.978 |
| classifications (security class, price basis, exchange basis, price reference, trigger origin) | 255 incl. triage | 0.974 | 0.992 | 0.986 / 0.984 |
| pro-ration and results (factor, tendered, accepted, final price) | 45 | 0.980 | 0.980 | 0.957 / 0.989 |
| **closing conditions (sets)** | 31 | **0.875** | **0.825** | **0.806 / 0.806** |
| collars | 2 | 1.000 | 1.000 | (2 filings, both "no collar") |
| **all terms** | **389** | **0.968** | **0.983** | **0.969 / 0.970** |

**The hard fields, and why:**

- **Merger closing conditions** (0.737 on 19 merger filings). The long
  agreements list a dozen conditions in an appendix. Readers disagreed on
  whether a termination right, a listing covenant or a pre-closing
  distribution is a "condition". Both readers missed the same one in three
  Nuveen filings: a correlated error that only an audit found.
- **The rights price formula** (price reference 0.81). "85% of NAV or 95% of
  market, whichever is higher" does not fit one enum and one percent. Pass A
  encoded it as market 95% with an 85% NAV floor, which gives the same price.
  This is a schema gap.
- **The tender commencement date** (0.90). FS Global's Offer to Purchase is
  dated 22 February, but the filing implies a 1 March start. Results
  amendments state no commencement at all. This is a definition gap.
- **Trigger origin** (0.93). Whether an attached standstill agreement makes a
  tender an "activist settlement" is a judgement.
- **Pro-ration** (factor precision 0.80). Two readers wrote 100 from "all ...
  accepted". The value-in-span check flagged exactly those two. Only 4 printed
  factors occur in the sample (48.433%, 13.3642%, ...).
- **Collars** do not occur (2 "no collar" filings). The hard case, a real
  collar, is untested.

**What routes an error to review** (pooled over both passes, 29 wrong cells):

| route | wrong cells it catches | false alarms |
|---|---:|---:|
| A ≠ B | 25 (86%) | 0: every disagreement has at least one wrong side |
| the reader's own `uncertain_fields` | 16 (55%) | 109 of 125 flags |
| span and value-in-span checks | 2 (7%) | 5 (the GDV quote characters) |

### 7.4 How much text the model must see [V] (`gold_value_coverage.csv`)

The share of gold values whose every quote lies in the input:

| input | all | tender | merger | rights | input size (mean) |
|---|---:|---:|---:|---:|---|
| first 8,000 characters (the cover) | 0.57 | 0.63 | 0.40 | 0.65 | ≈ 3k tokens |
| first 20,000 | 0.74 | 0.78 | 0.54 | 0.94 | |
| first 50,000 | 0.84 | 0.91 | 0.63 | 0.94 | |
| first 120,000 | 0.91 | 0.97 | 0.75 | 1.00 | ≈ 31k tokens |
| cover + every paragraph matching the schema's vocabulary | 0.84 | 0.89 | 0.70 | 0.90 | ≈ 41k tokens (52% of the text) |
| the whole filing | 1.00 | 1.00 | 1.00 | 1.00 | ≈ 142k tokens |

- **Truncation costs recall, and mergers worst.** The conditions and the
  termination date sit in the agreement appendix. For the merger values a
  120k cut loses, the last quote of a condition set lies 162k–512k
  (normalised) characters in, with a median of 380k; termination dates lie
  374k–514k in.
- A keyword section selector is no better than a 50k prefix. A structural
  selector (the agreement's "Conditions precedent" and "Termination" articles
  by heading) is the obvious next test, not built here.
- The kind's evidence is on the cover in at least 45 of 50 filings, so
  **triage can read the cover; terms cannot.**

---

## 8. What it would cost on the Claude API

**Prices** [V], https://platform.claude.com/docs/en/about-claude/pricing,
fetched 2026-10-15. USD per million tokens, standard / Batch API (50% off,
stacking with cache discounts):

| model | input | output | cache read | batch input | batch output |
|---|---|---|---|---|---|
| `claude-haiku-5-5` (prompts ≤ 100k tokens) | 0.10 | 0.50 | 0.01 | 0.05 | 0.25 |
| `claude-haiku-5-5` (prompts > 100k tokens) | 0.50 | 2.50 | 0.05 | 0.25 | 1.25 |
| `claude-sonnet-5-5` | 2.00 | 10.00 | 0.10 | 1.00 | 5.00 |
| `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | 2.00 | 10.00 |

(The claude-api reference bundled with this agent listed Sonnet 5.5's cache
read at $0.20. The fetched page says $0.10, 0.05× base, and this note uses the
page.)

**Tokens are estimated, not counted** [S/U]. Anthropic's token counter is an
API endpoint, and no key was used. The pricing page and glossary give the
ratios: "a token represents approximately 3.5 English characters" on models
before Claude 4.7, and the newer tokenizer of Claude 4.7 and later "produces
approximately 30 percent more tokens for the same text". So characters ÷ 2.69
here.

- Filings are dense with numbers and tables, so this is more likely low than
  high.
- The first API step should be `count_tokens` on these 50 filings.

Per filing:

- **input:** the filing's text (median ≈ 90k tokens, mean ≈ 142k, max ≈
  659k; 25 of 50 exceed Haiku's 100k price step);
- **instructions:** 13,562 characters, ≈ 5.0k tokens plus the 286-token tool
  prompt, as cache reads;
- **output:** the gold JSON with its quotes, mean ≈ 1.65k tokens;
- **adaptive thinking is not included**: it cannot be switched off on Opus 5.5
  and is unmeasured. Each 1,000 thinking tokens per filing adds $20 (Opus),
  $10 (Sonnet) or $0.50 (Haiku) per 1,000 filings at standard prices.

**Per 1,000 filings of this sample's mix** (`cost_per_1000.csv`), standard /
batch:

| input sent | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|
| whole filing (≈ 142k tokens) | $69.46 / $34.73 | $300.42 / $150.21 | $600.83 / $300.42 |
| first 120,000 characters (≈ 31k) | $3.98 / $1.99 | $79.12 / $39.56 | $158.23 / $79.12 |
| cover + keyword sections (≈ 41k) | $11.72 / $5.86 | $98.95 / $49.48 | $197.90 / $98.95 |
| cover only, triage output only | **$0.38 / $0.19** | | |

**Scale.** The fund set filed 7,070 event-form filings in 2025, 2,864 of them
by listed funds [V].

- Triage of all 7,070 on covers by Haiku is about $2.7 a year.
- If every listed filing went to Opus in full, an upper bound, terms would be
  about $1,700 a year standard ($860 Sonnet).
- The 2010–2026 backfill (87,874 filings; EDGAR note §2) costs about $33 to
  triage. Its terms depend on the positive share, which is unmeasured.
- These scale the sample's mean size to a stream whose mix differs (short
  8-Ks, long N-2s) [U].

**Recommended tiering**, to be confirmed by the pilot (§11):

| tier | model | input | job | why |
|---|---|---|---|---|
| 0 | none (rules) | index row, form, CIK | drop forms and filers outside the kinds; route 13D/G on held names | free |
| 1 | **Haiku 5.5**, batch at night, standard in market hours | the cover (8k characters) | `kind`, `fund_type`, `doc_role` | the evidence is on the cover in ≥ 45 of 50; $0.38 per 1,000 |
| 2 | **Opus 5.5** for live-path kinds on held or planned names; **Sonnet 5.5** batch for research backfill | the **whole filing** (all are under 1M tokens; the largest here is ≈ 659k) | the terms, with quotes | truncation loses 25–30% of merger values; at a few hundred live-path filings a year Opus costs hundreds of dollars, not thousands |
| 2b | a second, independent extraction (the other model, or the same at another effort) | the same | diff against tier 2 | disagreement caught 86% of wrong cells here; it doubles tier 2's cost |
| 3 | human (P1 / P2) | the diff, the failed checks, condition sets | accept or correct | §9 |

**The tiering is a hypothesis.** Whether Sonnet or Haiku reads terms as well
as the Opus readers did here is **not measured**: every reader in this
prototype was Opus 5.5 working agentically, searching the document rather than
reading it whole. The pilot answers it for about $49.

---

## 9. Human review queues

| queue | what lands in it | who | deadline | what waits on it |
|---|---|---|---|---|
| **P1, live path** | a live-path kind on a held or planned name; any span or consistency failure on such a row; UNPARSED on such a name | a verifying agent reads the spans against the text, then the team lead (or a named reviewer) accepts or corrects | before the next send window (15:52 ET paper) | **terms only**: the subtract-only rule has already acted on the kind and does not wait |
| **P2, research gold** | every row a backtest will use: span failures, model-vs-rule disagreements, uncertain fields, rows with `api_offset_error` | agent first pass, human sample | before the row enters a backtest | the backtest (no unreviewed backfilled row in a headline) |
| **P3, drift** | a seeded 5% sample of accepted rows each month, re-read blind | agent + human | monthly | the extractor's continued use (pod note §6.5) |

- A review is a row (`source="review"`, its own `recorded_at`), never an edit.
- The self-flag is a useful router (§7): what the reader flagged as uncertain
  against what turned out wrong.

---

## 10. The LLM lookahead problem, as it applies here

The prototype's readers are a model whose training data runs to 2026; they
read 2021 filings. Extraction asks for **stated values with quotes**, and a
value must be found in the text, so knowledge of how a deal ended cannot enter
a term without failing the span check. It can enter a judgement call, though.
Examples here: a `trigger_origin`, or calling a "conditional" tender
"activist_settlement" from a standstill exhibit. The controls (pod note
§6.1a):

- extraction only;
- a redaction audit before any backtest uses LLM-extracted judgement fields;
- accuracy re-measured on filings dated after the model's training cutoff;
- **no LLM judgement field as a backtest feature** across the training
  period.

None of this was measured here.

---

## 11. Decisions for the team lead

1. **API spend for a measured pilot.** A key held like the desk's other
   credentials, and about **$49 at standard prices (about $24 batch)** to run
   Haiku 5.5, Sonnet 5.5 and Opus 5.5 once each over these 50 filings, full
   text, scored against this gold by `event_engine_score.py`. The figure is an
   estimate from characters and excludes thinking tokens. First call
   `count_tokens`, which replaces every estimate in §8.
   *(Decided 2026-10-19: the team lead declined the API spend and chose two
   free options instead: a rules-only baseline, and the same three models run
   as Claude Code subagents on a 120,000-character excerpt. Both are in
   `results/events/EVENT_ENGINE_PILOT_2026-10-19.md`. The excerpt cannot answer
   this item's whole-filing question for about a quarter of merger values,
   per that note's §2.2.)*
2. **The time key** (§4):
   - `observed_at = max(acceptance from the header, 06:00 ET on EDGAR's filing
     date)`, never the submissions API time and never the acceptance time
     alone;
   - research decisions at 22:00 ET;
   - the corrections to the pod note §3.6 and `docs/REFERENCES.md` §12j are
     made in this commit, dated.
3. **Schema 0.2**, before a gold set of 100 or more filings is labelled (pod
   note §6.1a):
   - two-leg rights pricing;
   - lesser-of tender caps;
   - commencement split into the offer document's date and the stated start;
   - the condition rules of §7.2 written into the field docs;
   - a share-class value for open-end funds.
4. **The bar before anything reaches the live path.** The pod note asks for a
   pre-declared recall on `kind` and the price basis. Both were 1.00 here, on
   50 filings that the readers' model had seen in training (§10). The bar
   should be measured on filings dated after the model's cutoff.
5. **A desk-wide EDGAR limiter** (one token bucket per machine), because
   several jobs share one address.
6. **Still open from the pod note §9:** whether the runner may cancel a queued
   order on an event (subtract-only on a live account).
7. **Alpaca news** is not a CEF source (§1). Keep it only as a BDC and equity
   M&A hint, or drop it.

---

## 12. What is not established

- **How any API model reads these filings.** Every reader was Claude Opus
  5.5 working as an agent with search, not a single API call. The token
  counts are estimates (§8). Thinking tokens are unmeasured.
- **Accuracy on activist 13D, SPAC, liquidation and conditional-tender
  programmes.** None was a sampled kind. Equity M&A had 1 filing.
- **Real collars and printed pro-ration factors.** There were 2 and 4 in the
  sample.
- **Independence of the two readings.** Same model, same instructions. One
  correlated error was found by audit and confirmed by the spot check (1 of 40
  agreed values wrong). The true both-wrong rate on unaudited fields is
  unknown, and 40 spot checks bound it only loosely.
- **The LLM lookahead** (§10). The readers' model was trained on text from
  after 2021.
- **When EDGAR disseminates an evening filing.** There is the SEC's sentence
  and one evening's feed. 06:00 ET on the filing date is an assumption until
  the poller logs `first_seen_at`.
- **Why the submissions API's acceptance time is late on some filings and not
  others.** Measured on 50 filings; the cause is unknown.
- **The sample's representativeness.** It covers listed funds only, with
  near-duplicate templates (Clough ×3, Eaton Vance ×4), and 2021 only.
- **The text renderer** decodes cp1252 bytes as Latin-1 (quotes become C1
  control characters). Matching tolerates it (`normalise`), but the readers
  did not always, and production should decode cp1252 at render time.

---

## 13. Files

- `scripts/events/event_store.py`: schema, time key, store, point-in-time query, validation hooks, subtract-only.
- `scripts/events/tests/test_event_store.py`: tests (no network, no model).
- `scripts/events/event_engine_sample.py`: the sampling rule (declared before reading; two amendments, both before any affected filing was read) and the text rendering.
- `scripts/events/event_engine_reconcile.py`: the gold, with every adjudication written down (raises on an undecided disagreement).
- `scripts/events/event_engine_score.py`: span checks, agreement, precision/recall, time keys, value coverage by input window, cost, `--volume`, `--spot-sample`.
- `scripts/events/event_engine_news_coverage.py`: Benzinga coverage of the sample's events.
- `results/events/event_engine/` (tracked):
  - `sample_manifest.csv`, `sample_meta.json`;
  - `extraction_instructions.txt`;
  - `pass_a/`, `pass_b/`, `gold/` (one JSON per filing);
  - `reconciliation.csv`;
  - `scores.json`, `field_scores.csv`, `field_scores_long.csv`, `spot_check.csv`;
  - `agreement_ab.csv`, `span_checks.csv`, `gold_span_offsets.csv`, `gold_value_coverage.csv`;
  - `time_keys.csv`, `cost_per_1000.csv`, `annual_volume.json`;
  - `alpaca_news_coverage.csv`, `alpaca_news_coverage.json`.
- Gitignored: `results/events/_cache_edgar/` (EDGAR responses) and `results/events/_cache_event_engine/text/` (the 50 texts; rebuilt by `event_engine_sample.py --offline`).

