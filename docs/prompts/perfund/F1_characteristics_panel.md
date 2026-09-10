# F1 — The per-fund characteristics panel: what is knowable about each fund, and when

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `00_BRIEF.md` §3 (how these instruments trade), §5 (harness),
§6 (house rules).
**Lever:** none directly. This is the data foundation without which F2 and F3
are fiction — a per-fund model needs per-fund facts, and today the repo has
almost none.
**Trials:** 0. Building a data panel evaluates no specification.
**Touches the live book:** no. Nothing here enters the sleeve.
**Run before F2.** F2's group forms consume this panel; F3 consumes F2.
**New 2026-09-09.**

---

## Paste from here

You are a data engineer on the QUANTT credit closed-end-fund book. Read
`docs/prompts/00_BRIEF.md`, then:

1. `data/cef/cef_facts.csv` — and understand what it is not. It has 46 columns
   for 44 funds, and **`totalExpenseRatio`, `annualReportExpenseRatio`,
   `netExpenseRatio`, `netAssets`, `totalAssets`, `fundFamily`, `category`,
   `legalType`, `fundInceptionDate` and `navPrice` are 100% null.** `sector`
   and `industry` are constant across all 44 rows and carry zero information.
   It has **no date column**, and it is a single yfinance snapshot taken
   2026-07-31 (check the mtime and `data/cef/_raw_info.json`). Any model that
   uses its `debtToEquity` or `marketCap` against a 27-year panel is committing
   a look-ahead error. **Treat this file as a bootstrap, not a source.**
2. `scripts/nport/fetch_nport.py` and `scripts/nport/parse_nport.py` — the repo
   already fetches and parses N-PORT for ETFs by series ID. CEFs are
   single-series, so the CEF path is *simpler*: CIK plus form type is enough.
   Extend these; do not write a second N-PORT parser.
3. `scripts/positioning/stage_positioning.py` — FINRA consolidated short
   interest and Reg SHO daily short volume already work. Extending them to the
   44 CEF tickers is a one-line change to the ticker list.
4. `scripts/build_spreads.py` — FRED is already wired, **including the known
   trap that the keyless CSV endpoint silently truncates licensed ICE BofA
   (`BAML*`) series to about three years regardless of the `cosd` parameter**.
   Reuse its solution; do not rediscover the truncation.
5. `docs/prompts/W3_session_architecture.md` Part B for the verified sponsor
   map, and `W10_breadth_and_groups.md` Part D for why leverage *type* is a
   required control rather than a nice-to-have.

---

## The principle that governs every field in this panel

**Every characteristic is stamped with the date it became knowable, not the
date it describes.** A fund's leverage ratio as of its 2024-04-30 fiscal period
was not knowable until the N-PORT filing appeared around 2024-06-24. A model
that uses the April value in May has looked ahead by seven weeks, and the
resulting backtest is worthless in a way that no amount of turnover-matching
will reveal.

So the panel has **two dates on every row**: `period_end` (what the value
describes) and `known_at` (the filing or publication timestamp). Every join
into the harness is on `known_at`, never on `period_end`. Write
`assert_no_peek`-style guards (W1's helper) into the panel builder, and make
the builder **raise** when a row is requested before its `known_at`.

State the lag explicitly per field in the panel's own documentation, because
the lags are very different: N-PORT is ~55–60 days, N-CSR is months, FINRA
short interest is ~7 business days, FRED is next-day, SIFMA is same-week.

---

## Part A — N-PORT: the structured core

**Access pattern, all free and keyless:**

1. `https://www.sec.gov/files/company_tickers.json` → ticker to CIK. Static
   JSON, daily-updated, 10,407 entries; all 44 CEF CIKs resolve. Cache it.
2. `https://data.sec.gov/submissions/CIK##########.json` → the fund's complete
   filing history in one call, including every NPORT-P accession with its
   filing date. **This one call is also the corporate-action monitor** (Part D).
3. `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/primary_doc.xml`
   → the filing itself.

Send a descriptive `User-Agent` with a contact address, as SEC requires, and
respect their rate guidance.

**What NPORT-P actually contains** — these are structured XML fields, not prose,
and they are the reason this part is worth doing at all:

*Fund level (`fundInfo`):*
- `totAssets`, `totLiabs`, `netAssets` — leverage ratio falls straight out.
- **`liquidPref`** — preferred-share liquidation preference. This is the
  preferred-leverage stack read directly rather than inferred. (NAD's most
  recent filing shows $1.6026bn.)
- `amtPay{OneYr,AftOneYr}{BanksBorr,CtrldComp,OthAffil,Other}` — borrowings by
  maturity bucket and counterparty type, which distinguishes a credit facility
  from other liabilities.
- **`curMetrics/intrstRtRiskdv01` and `dv100`** — DV01 and DV100 by currency.
  **This is an effective-duration measure, disclosed, per fund, per quarter.**
  The desk currently has no duration measure at all.
- **`creditSprdRiskInvstGrade` and `creditSprdRiskNonInvstGrade`** — spread
  duration split into IG and non-IG. This is a credit-quality mix measure,
  disclosed, and it is exactly the control a group-specific fair-value model
  needs.

*Holding level:*
- `cusip`, `isin`, `balance`, `units`, `curCd`, `valUSD`, `pctVal`,
  `payoffProfile`, `assetCat`, `issuerCat`, `invCountry`.
- **`fairValLevel`** (1 / 2 / 3) — the ASC 820 hierarchy. **The Level 2 and
  Level 3 shares are a direct, disclosed measure of how matrix-priced a fund's
  NAV is**, which is the single most important input to W13's stale-NAV work
  and to the artifact battery. Compute `pctVal`-weighted Level 2 and Level 3
  shares per fund per period.
- `debtSec/{maturityDt, couponKind, annualizedRt, isDefault}` — maturity
  profile, fixed vs floating, and default flags.

**Coverage and its limits, to state in the note:** N-PORT is public from about
2019, only the third month of each fiscal quarter is public, and it arrives
~55–60 days after period end. So this panel is **quarterly, from 2019, with a
two-month lag**. That is roughly 28 observations per fund. It cannot support a
27-year backtest, and any model that conditions on it is implicitly a
2019-onward model. **Say that in the panel's docstring and in every note that
uses it** — do not let a quarterly, 7-year, lagged panel silently become a
regressor in a 27-year study.

**Do not** attempt to use SEC's XBRL `frames` API or the Financial Statement
Data Sets for this. CEFs do not file 10-K/10-Q XBRL; those endpoints return
nothing and the failure is silent.

---

## Part B — N-CSR: the prose fields

Leverage **type** and the reset benchmark, and the expense ratios, exist only
as prose and tables in the N-CSR shareholder report. There is no structured
field. Use EDGAR full-text search
(`https://efts.sec.gov/LATEST/search-index?q=...&forms=N-CSR&ciks=...`) to
locate the right exhibit, then parse.

Two fields, both semi-annual and months-lagged:

1. **Leverage type and benchmark**, from "Notes to Financial Statements →
   Leverage". The target vocabulary is closed: `tob` (tender option bonds),
   `preferred_vrdp`, `preferred_mfp`, `preferred_rvmtp`, `preferred_arps`,
   `reverse_repo`, `credit_facility`, `none`. Record the reset benchmark
   separately (`sifma`, `sofr`, `obfr`, `fixed`, `auction`). **A fund whose
   structure cannot be established from a filing gets `unknown` and inherits
   pooled treatment explicitly in code — never a guessed default.**
2. **Expense ratio, including and excluding interest expense**, from the
   Financial Highlights table. **The distinction is not cosmetic for these
   funds:** a levered fund's headline expense ratio includes its financing
   cost, so comparing a 30%-levered muni fund's total expense ratio to an
   unlevered fund's is comparing two different things. Capture both, and if
   only one is disclosed, record which.

Parsing prose is brittle. Write the parser so that a parse failure **raises with
the accession number and the text it could not parse**, and keep a fixture of
one filing per sponsor in the test suite so a layout change is caught by a test
rather than by a silently empty column.

---

## Part C — Distributions, coverage, and the return-of-capital signal

**There is no EDGAR form for Section 19(a) notices** — verified against a
fund's complete 30-year form census. They exist only on sponsor sites and wire
services. This is the single most annoying gap in the panel and also one of the
more valuable fields, because the ROC share of a distribution is the
best-lead-time warning the sector offers (see W10 Part E and F2's event list).

Routes, in order of preference:

1. **Wire services.** 19a-1 notices are routinely issued as press releases
   through GlobeNewswire and Business Wire, which are not bot-protected. Try
   this first; it is more reliable than the sponsors' own sites.
2. **Sponsor pages.** Nuveen's distribution and 19(a) pages return HTTP 200 but
   are client-rendered single-page apps — the raw HTML has no PDF links, so a
   headless browser or a reverse-engineered XHR endpoint is required.
   BlackRock's CEF pages are the same shape. **PIMCO actively blocks automated
   fetches (HTTP 403 to both curl and a plain fetcher, verified 2026-09-09)** —
   do not build against pimco.com directly, and do not attempt to evade the
   block; use the wire route.
3. If neither works for a sponsor, record the field as unavailable for that
   sponsor and **say so in the panel's coverage table**. A field that exists for
   PIMCO and not for Nuveen is a field that cannot be used in a cross-sectional
   model without introducing sponsor selection.

Fields: declared amount, ex-date, record date, pay date, frequency, and the
19(a) composition split (net investment income / short-term gains / long-term
gains / **return of capital**). Derive `roc_share_ttm` and its trailing change.

The forward ex-date and **record date** calendar this produces is consumed by
three other prompts: W4 Part A (the distribution term in returns), W8 Part D
(recall pressure clusters before record dates), and W9's event calendar.
**Never infer an ex-date from cadence** — a monthly payer that skips a month is
precisely the event that matters.

---

## Part D — Ownership, events, and the activist watch

**Corporate-action monitoring is one call per fund per day.** Poll
`data.sec.gov/submissions/CIK##########.json` and diff the form list against
yesterday's snapshot. New form types worth alerting on, all verified present in
real CEF filing histories: `N-14` / `N-14 8C` (mergers — Nuveen alone has filed
395 reorganisation documents), `N-23C-2` (preferred-share redemption notices),
`SC TO-I` (issuer self-tender), `N-2` (rights offering / shelf), `N-CEN`
(annual census), `SC 13D` / `SC 13G` and their amendments.

**Activist ownership.** Two working routes, both free:
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={fund_cik}&type=SC+13&output=atom`
lists filings where the fund is the *subject*; EDGAR full-text search also
indexes subject-company CIKs. Record filer name, date, percentage held, and
whether it is a 13D (control intent) or 13G (passive).

**This matters more than it used to.** Saba, Karpus and Bulldog drove about 90%
of 2023 CEF activist actions and held stakes in roughly 44% of all traditional
CEFs at end-2024; Saba alone filed 13Ds against at least 18 named CEFs in
2023–24, including muni and credit names. And the SEC's rule of 10 October 2023
shortened the initial Schedule 13D deadline from 10 calendar days to **5
business days**, with amendments due in 2 business days — so the stealth
accumulation window narrowed and the filing-day jump now dominates any
pre-filing drift.

Two things follow, and both belong in the panel rather than in someone's head:
a per-fund `activist_holder` / `pct_held` / `first_13d_date` field, and a
standing **risk flag** — this desk shorts rich funds, and a 13D on a name you
are short is a jump-to-NAV risk with at most five business days of warning.

**Institutional ownership percentage is not published free** by any source
found. It can be computed in-house from 13D/G/13F share counts against N-PORT
shares outstanding; treat that as optional and lower priority.

---

## Part E — Reference series

- **FRED, keyless CSV** (`fred.stlouisfed.org/graph/fredgraph.csv?id={SID}`):
  SOFR, `DFF` (EFFR), HY OAS `BAMLH0A0HYM2`, IG OAS `BAMLC0A0CM`, `DGS3MO`,
  `DGS2`, `DGS10`. **The `BAML*` series truncate to ~3 years on the keyless
  endpoint** — `build_spreads.py` already solves this; reuse its path. `DGS*`
  are not truncated.
- **SIFMA Municipal Swap Index**, weekly, reset Wednesday and published
  Thursday, free from sifma.org. **Required by F2's Nuveen-muni group form.**
  Budget a manual step to pin the current history file's URL, then automate.
- **FINRA short interest** (consolidated, twice monthly, ~7 business days lag)
  and **Reg SHO daily short volume** — both already implemented in
  `stage_positioning.py`; add the CEF tickers.
- **A free AAA muni yield curve or muni/Treasury ratio was not found on FRED.**
  It must be computed in-house from a muni ETF (MUB/PZA, which W10 Part D
  fetches anyway) against a duration-matched Treasury series, and labelled as a
  proxy rather than the real ratio.
- **MSRB EMMA bulk historical trade data has historically required a data
  licence.** Do not scrape it. If muni trade data is wanted later, that is a
  legal question first and an engineering question second.

---

## The output

`data/cef/cef_characteristics.parquet`, one row per `(ticker, period_end)`:

```
ticker, period_end, known_at, source, source_url,
  net_assets, total_assets, total_liabs, liquid_pref,
  leverage_ratio, leverage_type, leverage_benchmark,
  borrowings_banks_1y, borrowings_banks_gt1y,
  dv01, dv100, spread_dur_ig, spread_dur_nonig,
  level1_share, level2_share, level3_share,
  pct_floating, pct_defaulted, wtd_avg_maturity,
  expense_ratio_incl_interest, expense_ratio_ex_interest,
  dist_amount, dist_frequency, roc_share_ttm, roc_share_delta,
  short_interest, days_to_cover,
  activist_holder, activist_pct, first_13d_date,
  sponsor
```

plus `data/cef/cef_events.csv` (one row per dated corporate action, with
`form_type`, `filed_at`, `effective_date`, `detail`, `source_url`) and
`data/cef/cef_declared.csv` (the forward distribution calendar with ex- and
record dates).

**And a coverage table, which is the most important deliverable in this
prompt.** For every field × fund: first available date, last available date,
number of observations, and the median lag between `period_end` and `known_at`.
`results/cef/CHARACTERISTICS_COVERAGE_<date>.md` leads with it. **F2 must read
that table before choosing which fields to condition on**, because a field
present for six funds and absent for eleven is not a cross-sectional regressor
— it is a sample-selection device.

## Build order

Tier 1, near-zero marginal effort because the machinery already exists:
FINRA short interest and short volume; FRED reference series; N-PORT holdings,
leverage and the risk metrics; CEFConnect NAV staleness detection (the endpoint
already returns a per-row `DataDate` — W3 adds the check that it actually
advances).

Tier 2, EDGAR-native and high value: the corporate-action watchlist and the
13D/13G monitor.

Tier 3, prose parsing: leverage type and expense ratios from N-CSR.

Tier 4, hardest and lowest priority: sponsor 19(a)/UNII scraping and the
muni-specific series.

**Do not block F2 on Tier 3 or 4.** Ship Tiers 1–2, publish the coverage table,
and let F2 condition on what exists.

## Do not

- Do not join any characteristic on `period_end`. Every join is on `known_at`.
- Do not use `cef_facts.csv` for anything that enters a model; it is an undated
  snapshot with the most valuable columns empty.
- Do not fill a missing characteristic with a group mean, a median, a
  forward-fill beyond a stated horizon, or a value from a later filing.
  A missing field is missing and the row says so.
- Do not scrape a source that blocks automated access or requires a licence.
  Record the gap instead.
- Do not let a 2019-onward quarterly panel become a regressor in a 27-year
  study without that being stated in the note and in the code.
