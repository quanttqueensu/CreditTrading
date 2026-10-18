# CEF/BDC corporate-action census for a long, ETF-hedged event sleeve — 2026-10-15 (built 2026-10-18)

**What this is.** Special-situations sprint, job 3 of 6 (team lead, 2026-10-15).
The book cannot borrow most of the funds an event trade would short (G1a,
`results/events/G1A_SHORTABILITY_2026-10-13.md`). So the question here is which
CEF and BDC corporate actions pay a holder who is LONG the fund and hedges its
NAV beta with a liquid, shortable ETF, with no borrow on the fund. For each
event type this note gives counts per year, independent groups (sponsor ×
date), typical terms read from filings with source spans, the TERMS-IMPLIED
gross spread from price/NAV LEVELS, pro-ration, hold, ADV and the hedge ETF.
It then ranks the types and proposes zero-trial gates for the top three.

**Zero trials. The EVENTS counter stays at 0** (`docs/RESEARCH_STATE.md`). No
realised return or P&L of any event trade was computed or read. Every level
statistic uses events announced before 2023-01-01 only; later events are
counted, nothing more. `cef_universe.csv` funds (all 44) are counted and
flagged, and every level field on them is left blank. 50 such events are
counted only; the 27-name holdout is not consumed.

**Reproduce:**

```bash
export QUANTT_ENV_FILE=/abs/path/config/.env       # SEC_USER_AGENT, R2 and Alpaca keys; never printed
python3 scripts/events/cef_corp_action_census.py --today 2026-10-18 --offline   # caches only; raises on a miss
python3 -m pytest scripts/events/tests/test_cef_corp_action_census.py
```

Outputs: `results/events/cef_corp_action_census.csv` (one row per type),
`cef_corp_action_events.csv` (per event, EDGAR facts and source spans only),
`cef_corp_action_summary.json` (everything below, plus seeded term samples),
and `cef_corp_action_events_full.csv` (gitignored: it joins CRSP).

**Data and as-of dates.**

| input | as of |
|---|---|
| EDGAR fetcher tables (tender, contest and merger episodes; §12g) | last filing 2026-10-09 |
| EDGAR quarterly master indexes, extra forms (SC 13D, N-CSR/N-CSRS, 485xPOS, N-1A, 424B2/3/5, 497) | 2008-Q1 → 2026-Q4, the open quarter re-read 2026-10-18 |
| CRSP via the R2 mirror (names, delistings, distributions) | to 2024-12-31 |
| CRSP daily price and volume | rows before 2023-01-01 only (`crsp_events.daily` cannot return a later row) |
| Alpaca `GET /v2/assets/{symbol}` (paper API, cef key), 52 ETFs | 2026-10-18T22:33Z; true on that date only |
| N1 conditional-tender census | `conditional_tender_census.csv`, built 2026-10-13 |

The final build made 0 EDGAR requests (1,895 cache hits). The only network
request in today's rebuilds was the open-quarter index, plus the Alpaca reads.

---

## 0. The answer

**Ranked by (independent groups per year) × (terms-implied position spread) ×
(capacity, the median ADV).** All three terms come from 2010–2022, with the 44
excluded. The score is $k a year if every independent group were traded at
one day's median ADV.

| rank | type | groups 2010–22 | groups/yr | gross spread (position) | basis | net at 5 / 15 / 30bp per unit (units) | median ADV $m (n) | hold, days | hedge (any shortable, 2026-10-18) | score $k/yr |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Issuer tender at % of NAV | 124 | 9.54 | **+2.14%** | disc_post × E[pro-ration] 0.315 | +2.05 / +1.89 / +1.63% (1.68) | 0.42 (137) | 52 | HYG; 92.1% | 85.2 |
| 2 | Liquidation | 47 | 3.62 | +8.45% **upper bound** | disc_pre, median 84 days stale | +8.40 / +8.30 / +8.15% (1.0) | 0.13 (51) | 196 | HYG; 80.4% | 41.0 |
| 3 | Open-ending | 15 | 1.15 | +12.55% **upper bound** | disc_pre, median 63 days stale | +12.50 / +12.40 / +12.25% (1.0) | 0.24 (16) | 172 | SPY; 100% | 35.2 |
| 4 | Conditional-tender programme | 47 clusters | 3.62 | +0.66% | window average × P(trigger) 0.77 × pro-ration 0.094 | +0.56 / +0.37 / +0.08% (1.93) | 0.53 (65) | 84 (window) | HYG; 83.1% | 12.6 |
| 5 | Term / target-term termination | 14 | 1.08 | +1.05% **upper bound** | disc_pre, median 105 days stale | +1.00 / +0.90 / +0.75% (1.0) | 0.34 (19) | 93 | MUB; 52.6% | 3.8 |
| — | $ price / Dutch tender (mostly BDCs) | 10 | 0.77 | — (1 measurable) | $ price ÷ close at offer | — | 0.90 (8) | 31 | SPY; 100% | — |
| — | Rights offering | 75 | 5.77 | none | no exit above the market for a holder | — | — | — | SPY; 100% | — |
| — | Activist 13D (initial) | 230 | 17.69 | none | no stated exit price | — | — | — | HYG; 76.8% | — |
| — | Proxy contest | 80 | 6.15 | none | no stated exit price | — | — | — | MUB; 67.5% | — |

**How to read it.** The gross column is the headline. The cost grid beside it
charges each fund-leg trading unit 5, 15 or 30bp: entry, plus the sale of
whatever a tender does not accept. No row changes sign across the grid. The
conditional-tender row comes to +0.08% at 30bp, close to zero. Borrow on the
fund is zero by design (long only). The hedge leg's cost and borrow are not
charged; they are a stated gap (§7).

**Rows 2, 3 and 5 are not like-for-like with row 1.** A dead fund's daily NAV
is not held anywhere in this repository (plan item 0.8). So their spread uses
the last fiscal period-end discount before the announcement, which is stale
and an UPPER bound on what an entry after the announcement could capture. Row
1's spread uses a NAV dated on or after the announcement. The tender rows show
how much an announcement closes: disc_pre median −10.18% (n 115) against
disc_post median −8.30% (n 97). A whole-position exit at NAV should close
more, but how much is UNMEASURED.

**Proposed zero-trial gates (G1c style) for the top three, and the result:**

| gate | value | result |
|---|---|---|
| NT-a: independent groups 2010–22 (sponsor × date, 44 excluded) ≥ 30 | 124 | **PASS** |
| NT-b: groups whose terms-implied spread is measurable ≥ 30 | 82 | **PASS** |
| NT-c: median position spread net of 1.68 units × 30bp > 0 (on disc_post) | +163bp | **PASS** |
| NT-d: share of events with a shortable same-exposure ETF at Alpaca on the read date > 0.5 | 0.921 | **PASS** |
| NT-e: groups with a measured pro-ration ≥ 30 | 105 | **PASS** |
| LQ-a: independent groups ≥ 30 | 47 | **PASS** |
| LQ-b: groups with a measurable spread ≥ 30 | 40 | **PASS** |
| LQ-c: net spread > 0 on a post-announcement level | 815bp on disc_pre (upper bound) | **FAIL** by construction: no post-announcement level exists for dead funds |
| LQ-d: hedgeable share > 0.5 | 0.804 | **PASS** |
| OE-a: independent groups ≥ 30 | 15 | **FAIL** |
| OE-b: measurable groups ≥ 30 | 14 | **FAIL** |
| OE-c: net spread > 0 on a post-announcement level | 1,225bp on disc_pre (upper bound) | **FAIL** by construction |
| OE-d: hedgeable share > 0.5 | 1.0 | **PASS** |

**Verdicts.**

- **NAV tenders: feasible for one pre-registered EVENTS test, with the
  graveyard's figure as the bar.** All five gates pass. Passing does not
  contradict `SCALING_RESEARCH_2026-10-08.md` §3, "Do not build: tender capture
  alone, about 0.5% gross, not significant net, 2000–15" (see §6). The
  terms-implied +2.14% assumes the unaccepted 68.5% of the position is worth
  what it cost. If instead it gives the announcement narrowing back, the
  terms-implied figure falls to +1.14% (n 79, a level-only sensitivity, §2).
  A pre-registration would name the residual's fate as its main risk.
- **Liquidations: D7 on available data.** There are enough events (47
  groups), but the spread that matters, the discount an entry after the
  announcement pays, cannot be measured without dead-fund daily NAV (plan item
  0.8). The upper bound (+8.45%) is not evidence.
- **Open-endings: D7.** 1.15 groups a year is too few, whatever the spread.
- **Conditional tenders** (rank 4) are covered by the N1 census's own gates
  (`CONDITIONAL_TENDER_CENSUS_2026-10-13.md`). In this census's terms, 23
  usable groups (< 30) and +0.08% net at 30bp: below the bar here too.
- **Rights offerings, activist 13Ds and proxy contests** have counts (5.8,
  17.7 and 6.2 groups a year) but no stated exit price, so no terms-implied
  spread exists. Any edge in them is a realised-return question, which is a
  trial.

**One finding beyond the brief: no muni ETF is shortable at Alpaca.** On
2026-10-18, MUB, VTEB, TFI, HYD and SUB all read `shortable: false,
borrow_status: hard_to_borrow`. The only shortable rates hedge for a muni
event is IEF, a Treasury duration hedge whose basis to munis is exactly the
muni/Treasury ratio (mechanism M4 in the brief). Muni events are 8% of NAV
tenders, 20% of liquidations and 47% of term terminations: munis are the
only class with no shortable ETF, so these are one minus the hedgeable shares
in §5.

---

## 1. Where each type comes from (one structural source each)

| type | count from | terms from | announcement date | exit |
|---|---|---|---|---|
| NAV tender | the fetcher's tender episodes 2010+ (1,133). The first SC TO-I of each is read for its cover-page class, listing ("traded on the NYSE" or a ticker), price basis (the MODE of "k% of net asset value") and size | the offer (k, size, shares sought, expiry, a NAV on a named date) and the last SC TO-I/A (pro-ration) | first EDGAR filing of the episode (all 97 rows with disc_post were announced by an SC TO-C, 96, or an SC TO-I/A, 1: where the SC TO-I is the first filing, its NAV is always dated before it) | the tender's pricing date (expiry + 1) |
| $ / Dutch tender | same episodes, basis "$X per share" or "not greater than $H nor less than $L" | same | same | same |
| liquidation, term termination, open-ending | CRSP delistings 2010–2024 of share-code 14/44 permnos: code 4xx, or 2xx/3xx/5xx with no successor permno (119). Each is matched to an EDGAR CIK by name (112 matched) and its Form N-8F read (86): the checked box, the board-vote date, the distribution dates, the surviving fund | "whole position at NAV" (fees not read) | N-8F board-vote date where it precedes delisting; else the first proxy/8-K/merger filing in the 500 days before (the hold from it is an upper bound) | last distribution, or delisting |
| conditional tender | `conditional_tender_census.csv` (N1, 2026-10-13), not re-derived | threshold, price (% NAV), published window average | programme announcement; clusters are sponsor × window end | the tender, if triggered |
| rights offering | CRSP distribution code 45xx: first digit 4 is "subscription rights", second digit 5 is "same issue of common stock" (CRSP coding guide §6.2, §12ss3). 98 events; 94.9% have a 424B*/497 by the fund within 60 days | the prospectus: subscription formula, NAV floor, ratio, transferability (77 read) | (CRSP ex-date; not published) | — |
| activist 13D | initial SC 13D on a fetcher-set CIK whose filer is a known CEF activist (`ACTIVIST_RE`). A second 13D by the same activist on the same fund within 365 days is the same campaign. Banks filing as preferred holders are excluded | — | the 13D filing | — |
| proxy contest | the fetcher's contest episodes (264) where the target was listed | — | first contest filing | — |

**Exclusions, counted.** Of 1,133 tender episodes: 692 not exchange-listed
(interval or private funds), 110 preferred-share tenders, 87 with
communications only, 13 third-party (SC TO-T), 10 with no price basis. That
leaves 206 NAV tenders and 15 $/Dutch tenders. Of the 119 CRSP exits: 65
liquidations, 24 term terminations, 18 open-endings, 11 unresolved and 1
merger into an unlisted fund. An open-ending is an N-8F "Merger" whose named
survivor is an open-end series; an interval or private survivor is not one.
Every open-ending's parsed survivor was reviewed on 2026-10-18 (series of
Salient MF Trust, Westcore Trust, AB Bond Fund, Morgan Stanley Institutional
Fund, Columbia Funds Series Trust I; UBS Total Return Bond Fund; and others).

**Independent groups** are sponsor × announcement date, as in G1c and N1. The
sponsor is read from the fund name (`SPONSORS`). An unrecognised name is its
own sponsor, which can only overstate the groups. The unrecognised share is
38.8% for NAV tenders (many single-fund sponsors, such as country funds). The
stricter sponsor × month count is 122 against 124.

## 2. By type, per year, and the figures behind the rank

**Events per year** (announcement year; all funds, so the 44 are included in
these counts. Exits and rights come from CRSP, which ends 2024-12-31, so their
2025–26 cells are zero by construction. Conditional tenders are counted as
sponsor × window-end clusters):

| year | NAV tender | cond. tender | liquidation | term | open-end | $/Dutch | rights | activist 13D | contest |
|---|---|---|---|---|---|---|---|---|---|
| 2010 | 8 | 4 | 2 | 1 | 3 | 0 | 5 | 38 | 9 |
| 2011 | 10 | 8 | 3 | 0 | 4 | 0 | 4 | 28 | 21 |
| 2012 | 16 | 6 | 4 | 0 | 0 | 0 | 6 | 11 | 3 |
| 2013 | 8 | 5 | 2 | 0 | 0 | 0 | 6 | 14 | 3 |
| 2014 | 11 | 6 | 3 | 0 | 0 | 1 | 6 | 24 | 3 |
| 2015 | 5 | 2 | 5 | 0 | 5 | 0 | 3 | 29 | 10 |
| 2016 | 6 | 1 | 3 | 0 | 1 | 0 | 0 | 20 | 5 |
| 2017 | 17 | 3 | 9 | 0 | 0 | 3 | 7 | 32 | 10 |
| 2018 | 8 | 3 | 5 | 3 | 1 | 1 | 7 | 9 | 16 |
| 2019 | 17 | 3 | 3 | 2 | 0 | 1 | 7 | 29 | 21 |
| 2020 | 15 | 4 | 6 | 3 | 0 | 2 | 6 | 22 | 27 |
| 2021 | 14 | 1 | 6 | 6 | 1 | 0 | 14 | 9 | 3 |
| 2022 | 11 | 3 | 0 | 4 | 1 | 2 | 11 | 14 | 6 |
| 2023 | 13 | 3 | 2 | 2 | 1 | 2 | 6 | 64 | 21 |
| 2024 | 32 | 7 | 2 | 2 | 0 | 2 | 10 | 44 | 39 |
| 2025 | 9 | 6 | 0 | 0 | 0 | 1 | 0 | 9 | 7 |
| 2026 | 6 | 3 | 0 | 0 | 0 | 0 | 0 | 8 | 10 |
| **2010–26, sum** | **206** | **68** | **55** | **23** | **17** | **15** | **98** | **404** | **214** |
| all events (incl. announced before 2010 or undated) | 206 | 208 fund-windows | 65 | 24 | 18 | 15 | 98 | 441 | 214 |
| 2010–22, 44 excluded: groups | 124 | 47 | 47 | 14 | 15 | 10 | 75 | 230 | 80 |

The 2025–26 activist counts are far below 2023–24. Whether that is real or a
gap in this read (for example, a change in how EDGAR files Schedules 13D) was
not investigated [U].

**NAV tenders, pre-2023, 44 excluded (146 events, 139 outside the 44).**

| quantity | value | n |
|---|---|---|
| price, % of NAV | median 98.0 (IQR 98.0–98.5) | — |
| size, % of shares | median 15.0 | — |
| pro-ration (accepted ÷ tendered) | **median 0.315** | 114 events, 105 groups |
| disc_post: offer-stated NAV dated on or after the announcement vs CRSP's close that day | median −8.30% | 97 |
| disc_navdate: the same at any date (sensitivity) | median −8.37% | 130 |
| disc_pre: last period-end before the announcement | median −10.18% | 115 |
| accepted-slice spread, k × NAV ÷ price − 1, on disc_post | median +6.79% | 97 |
| position spread = pro-ration × slice (residual valued at entry) | **median +2.14%** | 97 (82 groups) |
| position spread on disc_navdate (sensitivity) | +2.13% | — |
| position spread if the residual gives the narrowing back to disc_pre (sensitivity) | +1.14% | 79 |
| hold, announcement → pricing date (expiry + 1) | median 52 days | — |
| ADV, median $ volume over the 63 CRSP sessions before the announcement | $0.42m | 137 |

Pro-ration method mix: 62 accepted ÷ tendered; 26 self-checking results-table
rows (8 by ticker); 7 stated factors; 9 shares sought ÷ shares tendered
(oversubscribed offers that print no accepted count); 5 fund-anchored counts
in joint releases; 5 "all accepted". Stated gaps: 10 joint releases with no
fund-anchored statement, 1 filing that contradicts itself (IRL 2017), 4 with
nothing found, and 10 with no final amendment.

**Liquidations (51 events 2010–22, 47 groups).** disc_pre median −7.79% (n 43,
median 84 days stale). Upper-bound spread +8.45%. Hold 196 days, ADV $0.13m.
Announcement basis among usable rows: 29 N-8F board-vote dates and 14 first
proxy/8-K filings.

**Open-endings (16, 15 groups).** disc_pre −11.15% (n 15, 63 days stale).
Upper bound +12.55%. Hold 172 days, ADV $0.24m. 13 of 15 usable rows are dated
by the N-8F board vote.

**Term terminations (19, 14 groups).** disc_pre −1.04% (n 13, 105 days stale).
Upper bound +1.05%. Hold 93 days, ADV $0.34m. Term funds stand near NAV before
the announcement. That is consistent with the 2026-10-11 re-run
(`REPRO_CEF_EVENTS_2026-10-11.md` §3: modern term funds' price against
terminal value 24 months out, median +0.20%).

**Conditional tenders (N1).** 208 fund-windows, 79 ending before 2023, in 47
sponsor × window-end clusters. Eight windows are on the 44 (EFR, EFT, MHD and
MQY) and are counted only. Two of them, EFR and EFT on 2022-08-31, end before
2023, but their cluster still counts through EVF, so the cluster count is 47
with or without the 44. Threshold median 10%, price median 98% of
NAV. Slice spread at the published window average: median +9.21% (n 26, 23
groups). P(a cluster triggers) 0.766, outside the 44. Pro-ration median 0.094
(n 18). Expected position spread +0.66%; window median 84 days; ADV $0.53m (n
65).

**$/Dutch tenders (15; 10 groups 2010–22).** Mostly BDCs and operating
companies (Great Elm, SuRo/Sutter Rock, CalFirst). One measurable spread, and
it is negative (a tender below the market). Pro-ration median 0.91 (n 5). Too
few to rank.

**Rights offerings (98; 75 groups).** Of 78 pre-2023 events outside the 44,
the subscription formula was read in 28 (median 90% of the market price) and a
NAV floor in 21 (median 80% of NAV). 61 are transferable, 13 not. A holder's exit is never above the market, and a long holder carries the
subscription-period decline. There is no terms-implied gain, so this type is
not a long-and-hedge candidate.

## 3. Typical terms, with source spans

A seeded random sample (seed 20261018, `terms_sample` in the summary JSON) of
pre-2023 events outside the 44. Each quote is the span the parser read from
the named filing.

| type | fund, announced | filing | quoted |
|---|---|---|---|
| NAV tender | Malaysia Fund, 2011-05-10 | SC TO-I 0001104659-11-028216 | "… by $12.23 (98.5% of the net asset value per share of $12.42 as of the close of ordinary trading on the New York Stock Exchange on May 6, 2011" ; "to purchase for cash up to 15% of its outstanding Shares, or 1,331,345 …" |
| NAV tender result | Malaysia Fund | SC TO-I/A 0001104659-11-067702 | "A total of 2,042,722 shares were properly tendered …" → accepted ÷ tendered 0.185 |
| NAV tender | BlackRock Debt Strategies (DSU), 2020-03-02 | SC TO-I 0001193125-20-076104 | "based upon a price of $10.94 (98% of the net asset value per share on March 11, 2020)"; "Offer to Purchase Up to 5% of the Issued and Outstanding Shares" |
| NAV tender result | DSU | SC TO-I/A 0001193125-20-110702 | "2. 17,034,684 Shares of the Fund were validly tendered …" → 0.145 |
| NAV tender (joint release) | Advent Claymore Convertible (AVK), 2017-05-01 | SC TO-I/A 0001219120-17-000006 | the fund's own Rule 13e-4(c)(4) block: "8,775,224 Common Shares of the Fund were validly tendered …" → 0.403, fund-anchored |
| liquidation | Thai Capital Fund, 2013-04-03 | N-8F 0001104659-13-080589 | "o Merger x Liquidation o Abandonment of Registration"; "date on which the board vote took place: April 3, 2013"; distributions "August 23, 2013, September 30, 2013" |
| liquidation | Western Asset Inflation Management, 2014-01-17 | N-8F 0001193125-16-742917; N-CSRS 0001193125-14-071775 | "¨ Merger x Liquidation"; period-end "$17.82 (NAV) -8.71 %† $16.93 (Market Price)" |
| term termination | BlackRock New York Municipal 2018 Term Trust, 2018-11-15 | N-8F 0001341004-19-000027 | "[X] Liquidation"; "final liquidating distribution pursuant to the Fund's Plan of Liquidation on December 28, 2018" |
| open-ending | Fort Dearborn Income Securities, 2015-12-03 | N-8F 0001137439-16-000512 | "[X] Merger"; survivor "UBS Total Return Bond Fund"; period-end "Net asset value $ 14.98 … Market price $ 14.10" |
| rights | Western Asset High Income Fund II | 424B 0001193125-22-100375 | "92.5% of the average of the last reported sales price … If, however, the Formula Price is less than 90% of the net asset value …"; "one new share of Common Stock for every three Rights held"; transferable |
| activist 13D | ClearBridge MLP & Midstream Total Return, 2022-09-26 | SC 13D 0001062993-22-019929 | filer Saba Capital Management, L.P. |

## 4. Checks: second methods, and the defects they found

Each figure that drives the rank was checked against an independent number or
re-read by hand. Five defects in the predecessor's draft (2026-10-15) were
found this way and fixed, each with a test that fails against the old code.

1. **disc_post was partly a pre-announcement level.** 33 of 130 offer NAVs
   were dated before the episode's first filing (by up to 25 days). disc_post
   now requires a NAV dated on or after the announcement (97 rows). The
   any-date figure is kept as a sensitivity, and it barely moves the answer
   (+2.13% against +2.14%).
2. **Pro-ration was read in 80 of 129 result filings, and joint releases were
   misattributed.** The missed phrasings were decimal percentages inside the
   sentence, "N of those Common Shares were accepted", "accepted for purchase
   all shares properly tendered" and results tables. In joint releases VLT got
   VTA's numbers, GF got EEA's tendered count, and IDE got IGA's table row. Now
   114 are read. In a release that names another fund's ticker, only a
   fund-anchored statement is believed; the rest are stated gaps. **Second
   method:** offer size (% of shares) ÷ % of outstanding tendered, capped at 1,
   uses different numbers from the same two filings. It agrees within 0.05 on
   **38 of 38** rows where both exist (median absolute difference 0.0002).
3. **Offer sizes mis-parsed**: a tax rate "(20%)" (JPT 2022), bytes of a
   uuencoded image (IRL 2012) and a mode tie broken by the smaller value (IRL
   2012: 15% read as 5%). Binary attachments are now stripped, a parenthetical
   percent needs a share count before it, and ties go to the first statement
   in the document.
4. **The period-end NAV reader misread table layouts.** In Nuveen's two-fund
   share table it read JMF's share price as JMLP's NAV (−32.1% instead of
   −9.8%). In Tortoise's highlights it took the previous column of the price
   row (+17.7% instead of −16.1%). It also read price-change sentences and
   total returns as NAV-beside-price. After three fixes, of 203 discounts read
   before, 147 are unchanged, 46 changed and 10 are now refused. Every
   remaining pair and sentence read (35), every column-table read (31) and a
   13-row sample of row reads were checked against their spans. The medians
   that drive the rank moved little (liquidation upper bound +8.40% → +8.45%).
5. **Conditional-tender trigger share** included universe funds' window
   outcomes, which are read from the discount level. It is now computed
   outside the 44, and the value is unchanged at 0.766.

**Price leg of disc_post.** 23 offers print a market price for their NAV
date. 21 agree with CRSP's close to the cent. CRSP stores a no-trade day as a
negative bid/ask average, and `crsp_events.daily` takes its magnitude, so a
"close" can be a midpoint. One of the two disagreements (GGO 2021) carries a
half cent in CRSP, which marks one. **CRSP
codes:** the meanings of distribution code 45xx and delisting codes 4xx, 205,
505 and 588 were read in the CRSP coding guide (§12ss3). The 331/332 codes
CRSP uses for some of these exits are not in that 1999 edition [U].

## 5. Hedges at Alpaca (read 2026-10-18)

Each event's asset class, read from its name, maps to one primary ETF and
declared alternates on the same exposure. All were read at Alpaca on one date
(`HEDGE_ETF`, `HEDGE_ALTERNATES`, written before any alternate was read). The
first shortable one is the hedge named.

| class | primary | alternates | shortable on 2026-10-18 |
|---|---|---|---|
| muni | MUB | VTEB, TFI, HYD, SUB | **none** (all `hard_to_borrow`); IEF (duration only) is shortable |
| high yield | HYG | JNK, USHY | all |
| loans | BKLN | SRLN | both |
| multi-sector | AGG | BND | both |
| EM debt | EMB | VWOB, PCY | all |
| preferred, convertible, MLP, REIT, utilities | PFF, CWB, AMLP, VNQ, XLU | PGX, ICVT, MLPA, IYR/XLRE, VPU | all |
| equity regions and sectors | SPY, VGK, EEM, FXI, EWJ, EWY, EWT, INDA, ILF, ACWI, XLV | IVV/VOO, IEUR/EZU, VWO/IEMG, MCHI, BBJP, FLKR, FLTW, EPI, FLLA, VT, IBB | all but FLLA |

Hedgeable share, primary or alternate: NAV tenders 92.1%, liquidations
80.4%, term terminations 52.6%, conditional tenders 83.1%, open-endings 100%.
Every shortable symbol read `easy_to_borrow`. Whether any ETF hedges its fund
well is a return question and is not asked here.

## 6. Graveyard and research-state check

`.claude/skills/graveyard/SKILL.md` and `docs/RESEARCH_STATE.md` (KILLED,
WATCH, CLOSED) hold no corporate-action event sleeve, and nothing here re-runs
a killed test. Four neighbours bind the reading:

- **"Tender capture alone: about 0.5% gross, not significant net, 2000–15"**
  (`results/cef/SCALING_RESEARCH_2026-10-08.md` §3, "Do not build", cited
  there as "§12 [V]"). The NAV-tender row is that idea's terms-implied cousin.
  A zero-trial census cannot overturn a realised-return finding. A terms
  figure of +2.14% (or +1.14% with give-back) against a realised 0.5% is what
  the residual's give-back, timing and costs would have to explain. A row
  carrying this figure was not found in `docs/REFERENCES.md` on 2026-10-18
  [S].
- **ICI on activist-forced tenders** (`docs/REFERENCES.md` §5 [V]): the excess
  discount runs −1.2% before the tender, −0.2% during and −3.3% the year
  after. This is the give-back the sensitivity row prices.
- **G1a** (`RESEARCH_STATE.md`, CLOSED): muni shorts are not available at
  Alpaca, so the merger pair's short leg fails for munis. §5 finds the same
  wall for muni ETF hedges.
- **The term-CEF pull-to-par** was PARKED as a sleeve (D7, about 47 events;
  `SCALING_RESEARCH` §7). The term-termination row agrees: 14 groups, and term
  funds trade near NAV before termination is announced.

## 7. Gaps (stated, not filled)

- **Post-announcement discounts for dead funds** (liquidations,
  open-endings, terms): UNMEASURED. There is no dead-fund daily NAV (plan item
  0.8). It is the one number that would turn LQ-c from "fails by construction"
  into a measurement.
- **The hedge leg is not costed.** No ETF spread, no borrow fee: Alpaca paper
  charges none, and the live fee was not read. Hedge ratio and quality are a
  return question.
- **Voluntary corporate-action fees.** Tendering shares through Alpaca may
  cost "$100 per client per voluntary corporate action" (§12 row, [U] whether
  it applies to Trading API accounts). Against a median position of one day's
  ADV ($0.42m) it is about 2bp; it is not charged here.
- **Capacity is one day's ADV per event.** That is a proxy. A tender's
  accepted slice can exceed it, and the residual has to be sold into it.
- **Recall is not measured.** The NAV-tender filter keeps listed common-share
  offers whose text states a "% of net asset value". 10 offers with no price
  basis are excluded. Activist recall depends on `ACTIVIST_RE`, a judgement
  list.
- **Exit dating.** 14 of 43 usable liquidations are dated by the first proxy
  or 8-K in the 500 days before delisting, which may be a routine filing; for
  those, the hold is an upper bound and disc_pre is staler than it need be.
