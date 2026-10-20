# Muni hazard flags B1/B2: the zero-trial gate — 2026-10-20

**The question** (team lead, 2026-10-19, "zero-trial checks on new event paths"):
should the live book carry **subtract-only hazard flags** on its muni funds?

- **B1**: muni credit events (defaults, reserve-fund draws, rating downgrades) from
  MSRB EMMA continuing-disclosure notices, mapped to each fund's holdings through
  N-PORT.
- **B2**: disasters and state fiscal shocks hitting single-state or concentrated
  muni funds.

The premise: a matrix-priced muni NAV lags the news, so the discount widens on
information, and the z-score buys it. A flag would stop that trade.

**What this note is.**

- **Zero trials.** No strategy return, P&L or Sharpe was computed, and no counter
  moved. The note reads price and NAV changes around dated events, holdings, and the
  band's own turnover.
- **The 2023-01-01 time holdout is sealed.** No price or NAV return dated on or after
  2023-01-01 was read; `_assert_fit_only` raises otherwise, and a test pins it. Three
  things dated after 2023 were read, none of them a return:
  - the latest N-PORT and N-CSR holdings (2026-07-31), which the question asks for;
  - ADV eligibility from price × volume levels;
  - the repo's Alpaca probe snapshots of positions.
- **The 27-name holdout is untouched.** Only the two spec munis and the eleven spec
  taxable funds (the H12 negative control) were read.

**Reproduce.** Offline, no credentials, no network:

```bash
python3 scripts/events/fetch_fema_declarations.py --offline   # rebuilds the FEMA CSV from the cached pull
python3 scripts/events/muni_hazard_gate.py stage              # copies the 32 EDGAR documents from sibling caches
python3 scripts/events/muni_hazard_gate.py run                # everything below
```

- `fetch_fema_declarations.py` without `--offline` re-pulls OpenFEMA (public, no key;
  six requests).
- `stage` raises, naming the accession, if a document is not cached anywhere. Fetching
  one is then the team lead's EDGAR client run, which reads `SEC_USER_AGENT` from the
  env file.
- **Outputs** (tracked) are in `results/events/muni_hazard/`:
  - `summary_2026-10-20.json`;
  - `concentration_by_quarter.csv`, `state_weights_by_quarter.csv`,
    `top_issuers_latest.csv`;
  - `ncsr_state_check.csv`;
  - `b1_nport_default_flags.csv`;
  - `b2_touched_events.csv`;
  - `fema_declarations_state.csv`.
- **Gitignored:** row-level holdings and per-event price/NAV rows sit in
  `results/events/muni_hazard/_cache_holdings/`.
- **Tests:** `scripts/events/tests/test_muni_hazard_gate.py`.

**Labels.**

- **[V]**: fetched and read on 2026-10-20, or produced by the script above.
- **[S]**: sourced but not re-read.
- **[U]**: uncertain.

Sources are in `docs/REFERENCES.md` §12aw.

**Panels read, with their last dates.**

| panel | last date (MHD, MQY) | used for |
|---|---|---|
| `data/cef/cef_prices.parquet` | 2026-10-15 | prices before 2023-01-01; price × volume levels to 2026-10-15 |
| `data/cef/cef_nav.parquet` | 2026-10-14 | NAVs before 2023-01-01 |
| `data/cef/cef_distributions.parquet` | ex-date 2026-08-14 | adding distributions back on ex-dates |
| N-PORT, MHD and MQY | every quarter 2019-10-31 → 2022-10-31, and 2026-07-31 (filed 2026-09-25) | holdings |
| N-CSR, MHD and MQY | 2022-07-31 and 2026-07-31 | the second method for state weights; leverage |
| OpenFEMA declarations | 2026-10-17 (pulled 2026-10-20T15:51Z) | B2 events |

---

## 0. The answer

**Verdict: not worth building, not even in report mode. Both paths fail at zero
trials, for different reasons.**

1. **B1 fails on its source.**
   - EMMA's terms forbid exactly what B1 needs: "any data mining, crawling,
     'scraping', robot … **or any manual process**, to access, acquire, **monitor**
     or copy" the site. The lawful route is the MSRB's feed, at **$45,000 a year**
     [V].
   - The free substitute is N-PORT's own default flags. They are quarterly, public
     54–59 days after quarter-end, and tiny:
     - one new flag in 26 fit-period fund-quarters, at 0.055% of NAV;
     - 0.43% and 0.31% of NAV flagged in the latest filings [V].
2. **B2's premise does not hold for the book's funds.**
   - The two spec munis, MHD and MQY, are **national** funds:
     - 48–51 states and territories each;
     - the largest state is New York at 21–25% of NAV, 12–15% of muni holdings;
     - about 17 effective states each [V].
   - A state-level flag would cover **37% of muni name-days**, a blanket rather than a
     hazard flag [V].
   - FEMA's major-disaster declarations arrive a median **41 days** after the incident
     begins [V].
3. **No stale-mark signature, muni-specific or otherwise, at any declared or post-hoc
   cut** (§3.3).
   - On touched events the muni discount did not widen: +3.3bp ± 14.8 (2020–22,
     point-in-time holdings) and −2.4bp ± 5.8 (2005–19, proxy holdings).
   - Where "NAV follows price" looks stronger after events, the taxable control shows
     the same thing. The muni-minus-control difference has t of −0.97, 0.16, 0.62
     and 1.35. Per H12, that is not muni matrix staleness.
4. **The book barely held these names in the fit period** (§3.4).
   - MHD never cleared the spec's ADV floor in 2005–22. MQY cleared it on 11.8% of
     2020–22 sessions.
   - The most a B2 flag could have blocked is **1.11% of 2020–22 book turnover**, and
     nothing before 2020 [V].
   - Today the book is **short** both funds (probe, 2026-10-13), and a subtract-only
     flag never blocks covering a short.
5. **One correction to the repo** (§6): both BlackRock munis also lever through
   **tender option bond trusts**, not only preferred shares. MHD's preferred is
   **VMTP**, not VRDP or MFP. `docs/BRIEF.md` line 386 is corrected in place.

**What building it would take, if reopened:** §5. **Reopen triggers:** §5.3.

---

## 1. Sources and their terms (question 1)

| source | what B1/B2 needs from it | the terms, quoted | can a commercial desk automate it? | status |
|---|---|---|---|---|
| **MSRB EMMA** (continuing-disclosure and material-event notices) | dated B1 events: payment delinquencies, unscheduled reserve draws, rating changes, bankruptcy | The MSRB Website Terms of Use cover "msrb.org, its subdomain emma.msrb.org and the Electronic Municipal Market Access (EMMA®) system" ("Last Updated: January 2, 2026"). Clauses: "The Website, Content and Services are to be used solely by you for your own internal purposes." You will not "use or allow others to use any data mining, crawling, "scraping", robot or similar automated or data gathering or extraction method, or any manual process, to access, acquire, monitor or copy any portion of the Website, Content or Services, or otherwise systematically download or store Content (unless otherwise authorized by the MSRB …). (Certain data and other information on the Website is available by subscription, for a fee.)" Also barred: "perform optical character recognition (OCR) on content that is imaged" | **No, not from the website.** Even manual monitoring is barred without MSRB authorisation. `emma.msrb.org` returned **HTTP 403** to a scripted GET of its terms page on 2026-10-20. The lawful route is the paid feed (next row) or the MSRB's written permission | [V] |
| **MSRB Continuing Disclosure Subscription** | the same notices, machine-delivered | "The Continuing Disclosure Subscription Service provides a real-time data feed … delivered via computer-to-computer data streams utilizing XML files and PDFs. **The cost of an annual subscription is $45,000.**" History: "**$22,500 for a consecutive 12-month period, plus a one-time $2,000 fee** for first-time purchasers", covering documents "provided to the MSRB since June 1, 2009" | **Yes, under a subscription agreement.** The agreement's redistribution and use terms were not read [U]. The feed's CUSIP indexing, which is what maps a notice to a held bond, was not read either [U] | [V] price; [U] contract terms |
| **OpenFEMA** `DisasterDeclarationsSummaries` v2 | dated B2 events by state | Terms "Last updated January 22, 2025": "Data accessed through FEMA's API does not include controls over its end use." Users "should cite the specific API endpoint (including the version)" and the access date. Required statement: "This product uses the Federal Emergency Management Agency's OpenFEMA API, but is not endorsed by FEMA." "We may suspend your access to this website if we feel you have not complied with these terms and conditions." No rate limit is stated | **Yes**, with attribution. No key is needed. The pull here was six requests. `www.fema.gov` refused curl (403) on the terms page, so the terms were read through the fetch tool; the API itself answered | [V] (terms read through the fetch tool) |
| **SEC EDGAR**: N-PORT and N-CSR | holdings by issuer and CUSIP, the fund's own default and arrears flags, state headings | "All Government-created content on sec.gov and EDGAR public filing content are free to access and reuse." "We allow scripted access to sec.gov content … our current maximum access rate is 10 requests per second." "Please declare your user agent in request headers" (Webmaster FAQ, "Last Reviewed or Updated: Aug. 23, 2024"). Fair-access rules are already in §12g | **Yes**: the repo's `scripts/data/edgar_client.py`, with the team lead's declared contact. **The constraint is timeliness, not terms.** Only the third month of each fiscal quarter is public [V §8, §12ad], and these 28 filings landed **54–59 days** after their report dates (median 58) [V]. Monthly public N-PORT is delayed to 2027-11-17 for larger fund groups [V §12y, §12ad] | [V] |

**Not fetched:**

- NOAA/NHC advisories (the real-time hurricane track, the timely B2 source);
- rating agencies' Rule 17g-7 municipal histories. The repo's
  `data/agency_actions_17g7.parquet` holds corporate, financial and insurance
  classes only: no municipal row [V].

Both are [U] for terms and coverage.

---

## 2. Which spec names are munis, and how concentrated (question 2)

**MHD and MQY are the only muni funds among the 13 spec names**, read from the spec
universe × `data/cef/cef_facts.csv` [V]. Both are BlackRock **national** funds. The
four Nuveen munis left the spec on 2026-09-28. The 44-name universe's one
single-state muni, NAN (New York), is a 27-name holdout name and was not read.

**Latest N-PORT (report date 2026-07-31, filed 2026-09-25).** Weights are % of net
assets. Muni holdings run to about 169% of NAV, because bonds held in TOB trusts are
carried gross and the fund is levered.

| | MHD | MQY |
|---|---:|---:|
| muni holdings / % of NAV | 900 / 168.8% | 732 / 169.9% |
| states and territories held | 51 | 48 |
| largest state, % NAV | NY 25.1 | NY 21.1 |
| next four states, % NAV | TX 19.0, FL 10.3, CA 9.5, AL 8.8 | TX 18.6, FL 16.2, IL 11.9, CA 9.7 |
| top-5 states, share of muni holdings | 43.0% | 45.6% |
| state HHI (effective number of states) | 0.0597 (16.8) | 0.0583 (17.2) |
| issuers (CUSIP-6) | 450 | 393 |
| largest issuer, % NAV | 4.36 (Puerto Rico Sales Tax Financing Corp, PR) | 4.29 (Black Belt Energy Gas District, AL) |
| top-10 issuers, share of muni holdings | 17.6% | 15.7% |
| issuer HHI (effective number of issuers) | 0.0069 (145) | 0.0065 (154) |
| Level 3 holdings, % NAV | 0.0 | 0.0 |

**Fit period, 13 quarterly N-PORTs each (2019-10-31 → 2022-10-31).**

- **MHD**:
  - largest state 15.7–24.1% of NAV (New York or Illinois);
  - top-5 states 39–48% of muni holdings;
  - state HHI 0.046–0.062;
  - largest issuer 4.0–9.1% of NAV.
- **MQY**:
  - largest state 13.0–18.3% (California, then New York);
  - top-5 states 40–49%;
  - state HHI 0.055–0.067;
  - largest issuer 3.5–4.9%.
- Puerto Rico ran **3.2–6.2% of NAV**, mostly the restructured sales-tax (COFINA)
  bonds. None was flagged as in default [V; `concentration_by_quarter.csv`,
  `b1_nport_default_flags.csv`].

**How the state was read, and checked.** N-PORT has **no state field**. The script
parses the CUSIP-style issuer description in `title` (for example "HOUSTON TX ARPT SYS
REVENUE") and the `name` field. In order:

1. the last upper-case USPS code;
2. a CUSIP-era abbreviation (CALIF, TEX);
3. a state name at the start;
4. a 37-pattern geographic map for tender-option-bond rows, whose title is a plain
   issuer name;
5. a state name anywhere, then the state of the same CUSIP-6 elsewhere.

Rows that none of these parse are reported **UNPARSED**, never assigned. "TENDER
OPTION BOND TRUST RECEIPTS / CTFS VARIOUS STATES" is up to 10.8% of MHD's NAV in two
2020 filings. In the latest filings nothing is unparsed.

**Second method.** The fund's own N-CSR state headings, at the same dates. Over 194
state rows (two funds × 2022-07-31 and 2026-07-31), the two differ by a **mean of
0.08pp** and **at most 2.54pp** (MQY Alabama, 2026). The fund totals differ by the
same 2.6pp, so this is a holdings difference, not a parse error [V;
`ncsr_state_check.csv`].

**What the parse cannot see.** Conduit issuers are mapped to the issuer's state, not
the project's. Examples are Wisconsin's Public Finance Authority and New Hampshire's
National Finance Authority. The N-CSR does the same, so the check cannot catch it.
There is no county field, so a declaration's designated counties cannot be matched to
bonds.

---

## 3. Historical incidence and the stale-mark test, before 2023 (question 3)

### 3.1 B1: credit events among the holdings

The only free, dated-enough source here is N-PORT's per-holding `isDefault` and
`areIntrstPmntsInArrs` flags, which the fund sets itself.

| | MHD | MQY |
|---|---|---|
| fund-quarters flagging any holding, 2019-10 → 2022-10 | 7 of 13 (one bond) | 0 of 13 |
| new flags in the fit period | 1: Stevens Plantation CDD (FL), first flagged 2021-04-30, at 0.055% of NAV | 0 |
| most flagged at once, fit period | 0.078% of NAV | 0 |
| latest filing (2026-07-31) | 6 flagged, 0.43% of NAV | 4 flagged, 0.31% of NAV |

**Incidence is negligible.** A default can only be dated to the quarter, and arrives
54–59 days after it. N-PORT's `fairValLevel` is 2 on every one of 16,752 muni rows,
so Level 3 cannot serve as a distress proxy either. That is the same degeneracy the
NPORT counter's HYG work found (`docs/RESEARCH_STATE.md`, nport-trace-nav).

**Not measured: dated muni credit events before 2023.** That needs EMMA's history
(§1: $22,500 a year) or the agencies' 17g-7 muni files (not fetched). The largest
single-issuer risk in the books is about 4.3% of NAV in one name, so a 20% mark-down
on it would move NAV by about 0.9%. That is arithmetic on §2's table, not a measured
event.

### 3.2 B2: declarations touching the funds' states

**Events.** One event is one (incidentId, state) from OpenFEMA, dated at its
**earliest** declaration of any type: DR (major disaster), EM (emergency) or FM (fire
management). COVID-19 ("Biological": 112 fund-event rows, 17 touched) is excluded as
a national event.

**Exposure.** The fund's net-asset weight in that state, from the latest N-PORT
**filed strictly before** the declaration (tested).

- Before the first N-PORT filing (2019-12-24) there are no point-in-time holdings.
  Those events use the 2019-10-31 weights and are labelled **proxy**.
- "Touched" means at least 5% of NAV. The derivation is in the script's docstring: one
  cent of NAV is about 9bp on an $11 fund.

**Timeliness.** Lags are declaration date minus incident begin date, over all
2000–2026 declarations, by type:

| type | median | IQR |
|---|---:|---:|
| DR, major disaster | 41 days | 18–67 |
| EM, emergency | 6.5 days | 1–43 |
| FM, fire management | 1 day | 0–1 |
| hurricanes, DR | 8 days | — |
| hurricanes, EM | 2 days | — |

**A flag keyed on major-disaster declarations fires weeks after the news.**

| fund, basis | events (incident × state) | <2% NAV | 2–5% | 5–10% | ≥10% | touched (≥5%) | in a top-10-issuer state |
|---|---:|---:|---:|---:|---:|---:|---:|
| MHD, point-in-time 2019-12-24 → 2022 | 327 | 174 | 75 | 26 | 52 | **78** | 31 |
| MQY, point-in-time | 327 | 183 | 59 | 9 | 76 | **85** | 36 |
| MHD, proxy 2005 → 2019-12-23 | 1,747 | 984 | 303 | 54 | 406 | 460 | 470 |
| MQY, proxy | 1,747 | 1,027 | 249 | 17 | 454 | 471 | 285 |

- Point-in-time, each fund was touched **20–35 times a year**.
- **94 of the 163 touched rows are fire-management grants** (FM only): single
  wildfires in California, Texas and Florida. By incident type: fire 102, hurricane
  31, other 30.
- The largest point-in-time exposures were state-wide weather in big states:
  - Isaias in New York (24.1% of MHD's NAV, but a DR declared 2020-10-02, two months
    after the storm);
  - the 2020 California wildfires (18.3% of MQY);
  - Henri and Ida in New York (17.6% of MHD);
  - Laura in Texas (15.7% of MQY).

  See `b2_touched_events.csv`.

### 3.3 The stale-mark signature

**Fixed in the script's docstring before any outcome was read.**

- **Gap.** Log price total return minus log NAV total return, with distributions
  added back to both on the ex-date.
- **News window.** close(t0−3) → close(t0+1).
- **Catch-up window.** close(t0+1) → close(t0+6).
- **The signature.** The discount widens over the news window (gap < 0), and the
  NAV's later move follows it. That is a positive slope of NAV catch-up on the
  news-window gap, larger on events than on baseline anchors.
- **Baseline.** Every 9th session, at least 10 sessions from any event anchor, over
  the same span.
- **Negative control (H12).** The 11 taxable spec funds at the same anchors.

Mean gaps are in bp ± SE. Slopes use HC1 standard errors, which are optimistic for
the control: its eleven names share dates.

| cut | n event (base) | event gap | base gap | event − base gap | catch-up slope: event − base | same, taxable control | **muni − control** |
|---|---:|---:|---:|---:|---:|---:|---:|
| **declared**, point-in-time, 2020-01-07 → 2022-11-21 | 132 (49) | +3.3 ± 14.8 | −46.5 ± 30.1 | +49.8 (t 1.48) | −0.45 (t −1.49) | −0.14 (t −1.43) | −0.31 (t **−0.97**) |
| **declared**, proxy, 2005-02-01 → 2019-12-19 | 696 (224) | −2.4 ± 5.8 | −6.8 ± 10.2 | +4.3 (t 0.37) | +0.12 (t 1.40) | +0.105 (t 2.63) | +0.015 (t **0.16**) |
| post hoc, news-anchored weather, point-in-time | 30 (89) | +9.4 ± 33.5 | −8.7 ± 16.5 | +18.1 (t 0.48) | +0.34 (t 2.07) | +0.24 (t 4.74) | +0.11 (t **0.62**) |
| post hoc, news-anchored weather, proxy | 68 (691) | −7.2 ± 16.2 | −3.2 ± 6.3 | −4.0 (t −0.23) | +0.10 (t 0.41) | −0.25 (t −3.46) | +0.35 (t **1.35**) |

**Reading.**

- **The muni discount did not widen on touched events** at any cut. The minimum
  detectable mean gap at 80% power is **51bp** (declared, point-in-time), **16bp**
  (declared, proxy) and 56–80bp (post hoc). So effects below those sizes are not
  excluded.
- **The one positive muni slope difference** (post hoc, point-in-time, t 2.07) **is
  matched by the taxable control** (t 4.74). Taxable funds hold no state munis, so
  the pattern is not matrix staleness of muni NAVs. It is what event-season sessions
  look like for every CEF NAV.
- **The post-hoc rows were added after the first run** and are labelled so in the
  script (`POSTHOC_*`). The cut keeps weather events whose earliest declaration
  came within seven days of the incident, excludes FM, and anchors at the incident
  begin date.
  - It answers a descriptive question the declared test cannot, because DR
    declarations come weeks late.
  - The incident begin date is not knowable on its own date for a DR-only event, so
    the cut is not a flag design.
- **Proxy rows use 2019 holdings for 2005–19 events.** State weights moved by up to
  about 8pp across 2019–26 (NY 16.8 → 25.1% for MHD). They describe; they decide
  nothing.

### 3.4 How much of the book a flag could ever touch

From `band(T, BAND_WIDTH)` on `build_targets()`, fit period. Returns are not read.

| quantity | value |
|---|---|
| sessions on which MHD clears the spec's `min_adv_usd` | **0%** in every era 2005–22; 16.4% in 2023–26 (price × volume levels only) |
| sessions on which MQY clears it | 0% 2005–19; **11.8%** 2020–22; 31.8% 2023–26 (levels only) |
| muni share of book turnover | 0 before 2020; **4.04%** in 2020–22 |
| muni name-days a declared B2 flag would cover (t0 … t0+5, touched) | **37.0%** (2019-12-24 → 2022), 38.0% (proxy) |
| flagged muni turnover, share of book turnover, 2020–22 | 2.70% |
| **flagged turnover that opens or grows a muni long** (what a subtract-only flag blocks), share of book turnover | **1.11%** (2020–22); 0 before |
| MQY in 2020–22 | long 19.0% of sessions, short 4.5%; turnover 2.58 units, of which 0.87 opened or grew a long |
| live, on its date only | short MHD 1,450 sh and MQY 2,105 sh (probe 2026-10-13); short MQY 1,298 sh (2026-10-15) [V: `results/ops/alpaca_probe/`] |

The catalogue's §5 gate (b), written 2026-10-15, asks whether event days carry more
than their share of sessions in turnover. Here 67% of muni turnover fell on the 37% of
muni name-days flagged. **But that sample is one fund on about 90 eligible sessions:
D7.**

---

## 4. Design-level spec of a report-only flag (question 4)

Recorded so that a reopening starts from a design, not from scratch. It mirrors the
stale-NAV gate's `report` mode (`docs/RUNNER.md`, "As built (2026-10-13)").

| element | specification |
|---|---|
| **Key** | `ops/books/cef_discount_book.json` → `"data": {"muni_hazard": "report"}`. Absent means off. `report` changes nothing; `on` applies the rule. The spec-level change is a CEF trial with a byte-for-byte no-op proof (`/spec-change`) |
| **Which names** | Spec universe × `cef_facts.csv` group `muni`, re-read at run time (H14), never a hard-coded list |
| **Holdings input** | The latest N-PORT whose **EDGAR acceptance time precedes the decide** (`exposure_asof` is the tested rule), parsed by `parse_state`. Each annual or semiannual N-CSR re-checks the parse (`ncsr_check`). If the newest usable filing is older than one quarter plus 60 days, the check is UNMEASURED and names the filing |
| **B2 events** | OpenFEMA v2, pulled each evening before the decide. The pull's `rundate` and SHA-256 are recorded, as the fetcher does. Earliest declaration per (incidentId, state). A declaration dated D counts at D's decide **only if the pull that saw it ran before the decide**. Each row records the fetch time, so there is no lookahead from FEMA's later edits (`lastRefresh`). Designated areas are never used: they are added after the declaration and are not dated |
| **B1 events** | Only with the MSRB feed (§1). Notices matched to held CUSIP-9s by the feed's index [U: not read]. Without it, N-PORT default and arrears flags are written as a quarterly report row, **never a timing flag** |
| **Trigger** | Fund weight in the declared state ≥ a threshold derived from tick size and a measured state-shock size. The 5% here is a declared placeholder, not a derivation from data. Or a B1 notice on a holding above a weight floor |
| **What it subtracts** | On a flagged (fund, D) for k sessions, the plan **may not open or grow a long** in that fund. A blocked increase keeps the current shares (as the NAV gate's hold does): no order in that name, never a target of zero, never an order added elsewhere. **Covering a short or cutting a long stays allowed.** k comes from a measured NAV catch-up horizon; this note measured none, so there is no k to adopt |
| **Records** | `plan.json` → `muni_hazard`, holding the mode, filing used, events seen, fetch times, per-name verdict, and what `on` would block. `<state>/muni_hazard.csv` gets one row per check, written **before** anything else (record first). The session log gets one `MUNI HAZARD` line |
| **Failure behaviour** | No silent fallback, ever. In `report`, an error (FEMA down, EDGAR document missing, parse below a declared coverage) is recorded **UNMEASURED** with its named cause and never stops the session. In `on`, UNMEASURED **fails closed in the subtract direction only**: no long may be opened or grown in a muni name that day, and nothing else changes. An unreadable record file is moved aside, as the NAV gate's is |
| **Proof** | With the key absent, orders, `plan_sha` and `plan.json` are byte-identical to today's, as `quantt/session/tests/test_nav_gate.py` proves for the NAV gate. Tests pin: filing strictly before the decide; a FEMA row fetched after the decide is not seen; UNMEASURED never adds an order |
| **Trial accounting** | Report mode: zero trials. `on`: CEF +1, pre-registered, judged by what it removes (turnover and the adverse move of blocked trades), never by a new return claim |

---

## 5. The gate and the verdict (question 5)

**The criteria below were written after the measurement.** They mirror the catalogue's
§5 gate (written 2026-10-15, before it). It reads: "It ends the discussion if
event-day NAV response is not lower than on matched days, **or** event days carry no
more than their share of sessions in turnover."

| gate | B1 | B2 |
|---|---|---|
| **G1, source.** A timely event source a commercial desk may automate at no cost | **FAIL.** EMMA bars automation and monitoring. The feed is $45,000 a year. N-PORT is quarterly and 54–59 days late | **Partly.** OpenFEMA is free and automatable. DR declarations lag a median 41 days; EM (6.5) and FM (1) are timelier |
| **G2, premise.** The book's muni funds are single-state or concentrated | — | **FAIL.** National: about 17 effective states, largest 21–25% of NAV |
| **G3, signature.** A muni-specific stale-mark signature on events (catalogue §5 (a)) | not measurable (no dated events) | **FAIL.** No discount widening. Muni − control slope t −0.97, 0.16, 0.62, 1.35 |
| **G4, reach.** The flag would remove material, targeted turnover (catalogue §5 (b)) | — | **FAIL as a targeted flag** (37% of muni name-days flagged). At most 1.11% of 2020–22 book turnover, on a D7 sample |

**Verdict: do not build B1 or B2, in report mode or otherwise.** Recommend recording it
CLOSED at zero trials (a row is proposed in `docs/RESEARCH_STATE.md`). The team lead
rules.

The muni-wide channel the premise is really about is better served by the macro-day
flag. A rate-news day moves every muni NAV at once, and that is where the book's
muni-versus-taxable risk sits. That flag is
`results/events/SPECIAL_SITUATIONS_CATALOGUE_CREDIT_2026-10-15.md` §5, not built.

### 5.1 What building it would take anyway

- **B2 in report mode.** The fetcher (`scripts/events/fetch_fema_declarations.py`) and
  the holdings parse and its check (`scripts/events/muni_hazard_gate.py`) exist and are
  tested. The remaining work:
  - a `quantt/session/` step like `nav_gate.py`;
  - its records and tests;
  - the byte-identity proof.

  That is days of work, but the report would flag 37% of muni name-days and measure
  nothing this note has not.
- **B1.** A procurement and a parsing project:
  - the MSRB feed ($45,000 a year, plus $22,500 for each 12 months of history and
    $2,000 once);
  - reading its subscription agreement;
  - parsing XML indexes and PDFs to held CUSIPs (OCR of imaged PDFs is barred on the
    website; whether the feed agreement allows it is [U]);
  - holdings that are 2–5 months stale until monthly public N-PORT arrives
    (2027-11-17 for larger groups).

### 5.2 What this note does not establish

- That state shocks never move these NAVs. The minimum detectable effects are
  16–80bp per window.
- Anything about **single-state** muni CEFs. None is in the spec; NAN is a holdout
  name and was not read.
- B1's dated incidence before 2023 (EMMA or 17g-7 municipal history: not fetched).
- County-level exposure (N-PORT carries no county).
- Whether the 2021-04 jump in reported holdings (MHD 293 → 882 muni holdings) is a reporting
  change; it is treated as one. The same goes for the low muni totals in the
  2020-10-31 filings (116–118% of NAV against about 150–169%). Both are unexplained
  [U].
- NAV quality: the panel is Yahoo-sourced, and stale copies exist
  (`results/cef/LIVE_NAV_QUALITY_2026-10-12.md`). Stale copies would, if anything,
  manufacture a lag signature, and none was found.

### 5.3 Reopen triggers (H14: re-measure, never key on the figures here)

Re-run `python3 scripts/events/muni_hazard_gate.py run` if any of these happens:

1. **A concentrated muni fund enters the spec.** That is a single-state fund, or one
   whose largest state's weight, measured by the same parse, is large enough for a
   state shock to move NAV by more than a tick.
2. **The desk buys the MSRB feed** for another reason.
3. **Monthly public N-PORT starts** (compliance 2027-11-17 for larger groups,
   `docs/REFERENCES.md` §12ad).
4. **The book holds muni longs for long stretches.** Today it is short both; re-measure
   the long share from the band, not from this note.

---

## 6. A correction to the repo: BlackRock muni leverage

`docs/BRIEF.md` line 386 (the sponsor table, "Verified 2026-09-09 against
`cef_facts.csv`") read **"MQY, MHD (muni, preferred: VRDP/MFP)"**. Line 134 says only
the Nuveen munis use tender option bond trusts.

**The funds' own annual report says otherwise.** The N-CSR for the year to 2026-07-31
(accession 0001193125-26-413740, Statements of Assets and Liabilities) shows:

| fund | TOB trust certificates | preferred shares | net assets |
|---|---:|---:|---:|
| MHD | $852,392,605 | **VMTP** $717,800,000 (no VRDP) | $2,182,763,211 |
| MQY | $476,885,780 | VRDP $847,356,011 | $1,814,141,828 |

- MQY's 2022-07-31 N-CSR (0001193125-22-258205) shows TOB $210,678,835 and VRDP
  $450,177,989, against net assets of $1,017,460,656.
- MHD's 2022 report is a four-fund combined statement. Every column in it shows both
  TOB certificates and VMTP shares; the column-to-fund mapping was not extracted.

**So both BlackRock munis lever through TOB trusts as well as preferred. MHD's
preferred is VMTP, not VRDP or MFP.** Whether their TOB floaters reset to SIFMA, as
the Nuveen description says, is not read here [U]. Corrected in place in
`docs/BRIEF.md`, and recorded in `docs/REFERENCES.md` §12aw. This matters for M4,
which models a SIFMA-linked leverage cost: it may apply to the BlackRock pair too.

---

## 7. Sources

`docs/REFERENCES.md` §12aw, added in the same commit as this note.
