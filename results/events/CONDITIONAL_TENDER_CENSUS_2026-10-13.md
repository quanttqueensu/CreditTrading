# Conditional-tender census (idea N1) — 2026-10-13

**What this is.** The zero-trial first step of idea N1 in
`results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §4.3. Some CEF boards commit to a
tender near NAV if the fund's average discount over a stated window passes a
stated threshold. This note counts every such programme in US-listed CEFs and
BDCs whose windows end from 2010-01-01 to today. For each programme it records
the terms, the windows, the outcomes and the source filing. It also asks
whether the trigger could have been computed daily, ahead of time, from public
data and from our panels, and how close the live book's names came to it.

**Zero trials.** Nothing is pre-registered and no counter moves. The script
computes no return. The only market quantity it computes is a window's
**average discount** (close/NAV − 1), from our panels. It does this only to check
the panels against the sponsors' published figures and to measure how near MHD
and MQY came to their trigger. A discount level is not a return. Neither
holdout is consumed: the 27-name set is consumed only by the first test that
computes returns on a `data/cef/cef_universe.csv` name, and no performance is
measured on 2023+ data.

**Reproduce.**

```bash
export QUANTT_ENV_FILE=/abs/path/config/.env   # SEC_USER_AGENT is read from it, never printed
python3 scripts/events/conditional_tender_census.py            # EDGAR through the cache, then the network
python3 scripts/events/conditional_tender_census.py --offline  # cache only
python3 -m pytest scripts/events/tests/test_conditional_tender_census.py
```

Outputs, all under `results/events/`:

- `conditional_tender_census.csv`: one row per fund × window, tracked. Window
  averages computed on CRSP closes are blanked; a yes/no column says whether
  the panel reproduced the published figure.
- `conditional_tender_census_full.csv`: the same, with those averages.
  **Gitignored**, because CRSP is licensed and this repository is public.
- `conditional_tender_programmes.csv`: one row per programme.
- `conditional_tender_candidates.csv`: every scanned document and its
  disposition.
- `conditional_tender_summary.json`: the counts below and the gate.
- `conditional_tender_live_running_average.csv`: MHD and MQY, day by day.

The census itself (programmes, windows, exclusions, each with its quote) is
`scripts/events/conditional_tender_programmes.py`.

**Data dates.**

| source | coverage |
|---|---|
| EDGAR full indexes, through `scripts/data/fetch_edgar_events.py` | 2008-Q1 → 2026-Q4; last filing date seen **2026-10-09**; read 2026-10-13 |
| EDGAR filings cited (SC TO-C, SC TO-I, SC TO-I/A, 425, DEFA14A, N-CSR) | fetched 2026-10-13 through `scripts/data/edgar_client.py` (cache first) |
| `data/cef/` (the live 44): NAV / close | to **2026-09-25** / **2026-09-28** |
| `data/cef_families/` (C4): yfinance NAV and close; CEFConnect NAV | to **2026-10-09** |
| `data/cef_families/cef_prices_crsp.parquet` (CRSP raw close) | to **2024-12-31** |

**Labels.** Every coded fact is quoted from a filing, and the script verifies
the quote against the fetched text: **223 quotes**, all found. Those facts are
[V] as of 2026-10-13. An outcome coded `*_inferred` is [V] only for "no tender
was filed within 180 days", which the script checks against the index; the
reason is [U]. Facts taken from search summaries are marked [S]; none of them
enters a count.

---

## 0. The answer

- **40 programmes** from **20 sponsors**, covering **65 funds** and **208 fund × window rows**:
  - 2 programmes have windows ending in 2010 but were announced earlier (GFY in
    2009, Neuberger in 2009). The Delaware commitments date from 1993 and 1994.
  - **No BDC** runs one. Every BDC hit was Dutch-auction "conditional tender"
    wording.
  - **Independent groups:** **39** by sponsor × announcement date (the task's
    unit). **66** by sponsor × window end date with a known outcome (the
    stricter unit for a test). Of those 66, **47** end before 2023-01-01.
- **Triggered share.**
  - 55.1% of the 198 fund-windows with a known outcome (documented or
    index-checked).
  - 59.7% of those with a documented outcome only.
  - **53 of the 66 sponsor clusters had at least one fund trigger.**
  - This is **biased upward by the discovery route.** A triggered window leaves a
    tender on EDGAR. A non-triggered one often leaves nothing: BlackRock's 2025
    results, DWS's 2011 windows and several Delaware years are absent from
    EDGAR.
- **Computable ex ante, daily, from public data? Mostly yes in principle, rarely
  from our panels.**
  - **Window dates.** For 111 fund-windows the dates were public before the
    window opened. For 42 they were not:
    - Delaware's windows end on a Q2 date the board designates and never
      publishes in advance.
    - BlackRock announced its 2025 programme, its first 2024 quarter and its
      2026 muni programmes **after** those windows had begun.
    - NRO's 2016 window started seven months before it was announced.
  - **Metric.** 24 fund-windows use a VWAP or a 10-day run, which need
    intraday data. ZTR's 2016 agreement names "Bloomberg VWAP".
  - **Panels.** They cover at least 95% of the sessions for **109 of 185 dated
    fund-windows** (38 of 72 before 2023).
  - **The panels reproduce the sponsors' arithmetic.** For all **81** published
    averages they cover, the panel is within 0.25 percentage points (median
    0.003, maximum 0.043). That holds only after replacing yfinance closes with
    CRSP raw closes for the C4 funds.
  - **yfinance's re-based NRO close misstates NRO's discount by about 4.1
    percentage points** on every window, as `docs/REFERENCES.md` §12h predicted.
  - **Outcome check.** Every coded outcome the panels can check (109,
    including 12 of the 18 inferred non-triggers) agrees with the panel's own
    reading of the trigger.
- **The live book's exposure: MHD and MQY only, both in BlackRock's 2026 muni
  programme.**
  - Window 2026-01-01 → 09-30; trigger: an average discount above 10%.
  - Published averages: **MHD −8.17%, MQY −7.41%** [V]. The live panel gives
    −8.169% and −7.407% on 184 of 187 sessions.
  - Neither came close:
    - On the eve of its announcement, MHD would have needed −10.37% over the
      rest of the window, and MQY −10.73%.
    - The daily discount passed −10% on 5 sessions for MHD and 2 for MQY.
  - **Both programmes were adopted after the window began** (2026-02-09 and
    2026-02-23), on completion of mergers:
    - MHD absorbed MUE, BFK, BYM and BLE.
    - **MQY absorbed MYD, MQT and BKN.** That makes MQY a 2026 merger
      acquirer as well; the pod note named only MHD.
  - **BIT is in no programme.**
  - The book's other 10 names appear nowhere in the census.
- **Proposed gate (G-N1, §7): the census fails it.**
  - 66 known-outcome clusters, but only **16** are usable for a test: dates
    public before the window, a close/NAV metric, and panel coverage. Only
    **10** of those end before 2023.
  - Even with a NAV history for every dead fund, the ex-ante, close-computable
    clusters number 33. Only 21 end before 2023, and only **4** of those did
    not trigger.
  - By the pod note's own rule, below about 30 independent windows N1 is D7:
    **fold it into C1 as hygiene** (no short inside a live window near its
    threshold). Do not open an EVENTS trial.

---

## 1. How the census was built

1. **The EDGAR scan** (`discover`). From the fetcher's 2008+ CEF/BDC filing
   table, the script took every SC TO-C filed 2010+ and the first SC TO-I of
   every tender episode: **1,571 documents**.
   - Sponsors file a conditional programme's announcement and its results as
     pre-commencement communications (SC TO-C). An SC TO-I's "purpose of the
     offer" names the programme that triggered it.
   - Two rules score each document:
     - a vocabulary rule (average discount with "measurement period",
       "conditional tender" or "discount management program");
     - a sentence rule (an average discount and a threshold percentage in one
       sentence).
   - **302 documents from 81 funds** were flagged. 37 programmes have a flagged
     document from one of their own funds.
   - Each flagged fund is either in the census or in `EXCLUDED` with a reason
     (26 funds). The script raises on any fund in neither.
2. **A second channel: web search, then EDGAR.** Three programmes the scan
   could not find:
   - **DDF**: its offer documents say "more than a stated percentage
     (currently 10%)", which neither rule matches.
   - **BKT 2025 and 2026**: announced and reported only in press releases and
     annual reports.
   They were verified on EDGAR through the funds' own filings (SC TO-I and
   N-CSR) before admission.
3. **Excluded** (`conditional_tender_programmes.EXCLUDED`, `EXCLUDED_OTHER`):
   - tenders conditional only on a vote, a merger or NAV performance (IFN,
     EVG, EVY, RGT, JEQ, KF 2020, CAF);
   - open-market buyback triggers (TWN, CHN);
   - "the board would consider" (the Singapore Fund);
   - unconditional tenders inside a "discount management program" (Clough
     2017, WIA 2020, the Saba–BlackRock settlements of 2025);
   - BDC Dutch-auction wording;
   - **CXH's 2023 Bulldog standstill.** Its discount trigger decides a
     liquidity-event *proposal*, not a tender;
   - **MXF 2026.** A commentary site describes a June 2026 conditional tender,
     but no EDGAR filing was found (submissions API, 2026-10-13).
4. **Recall is not measured, only bounded.**
   - EDGAR full-text search is not used. That is the fetcher's documented
     route, and the edgar client allows only `www.sec.gov` and
     `data.sec.gov`.
   - A programme announced only in a press release, an 8-K or an annual report,
     whose fund never tendered, is found only if the web search found it.
   - Three of the 40 were found that way. **Treat the counts as a floor.**

---

## 2. The programmes

Window counts are fund × window rows. "Trig / not / other" counts outcomes:
`triggered*` / `not_triggered*` / withdrawn, waived, suspended, superseded or
unknown. Threshold is the discount magnitude. The full terms and quotes are in
`conditional_tender_programmes.csv`.

| programme | sponsor | origin | funds | announced | threshold, basis | tender | windows | trig / not / other |
|---|---|---|---|---|---|---|---|---|
| WA-GFY-2009 | Legg Mason | board (Western Asset sub-adviser) | GFY (loans) | 2009-02-04 | >10%, weekly closes, after a NAV price trigger | ≤20% at ≥98% | 1 | 1 / 0 / 0 |
| NB-2009 | Neuberger Berman | board | NBW, NBH, NBO (muni), NRO, NHS (HY) | before 2010 | >10%, daily | 5–20% at 98% | 15 | 3 / 12 / 0 |
| DWS-2010 | Deutsche | board | EEA, GF | before 2010-12 | >10% | ≤5% at 98% | 6 | 3 / 3 / 0 |
| SWZ-2011 | Swiss Helvetia | board | SWZ | before 2011-05 | >10% | ≤5% at 98% | 2 | 1 / 1 / 0 |
| LMP-SCD-2011 | Legg Mason | board | SCD | 2011-03-09 | >5%, daily closes | ≤5% at ≥98% | 3 | 3 / 0 / 0 |
| GCH-2011 | Greater China Fund | board | GCH | before 2011-08 | >10% | ≤5% | 1 | replaced mid-window by an unconditional tender |
| NOMURA-KEF-2011 | Nomura | board | KEF | 2011-06-07 | >7.5% VWAP for 10 consecutive days | ≤10% | 1 | 1 / 0 / 0 |
| MS-2011 | Morgan Stanley | board | APF, MF | 2011-04-08 | ≥10%, daily | ≤5% at 98% | 6 | 5 / 0 / 1 |
| DWS-2012 | Deutsche | board | EEA, GF, CEE | 2012-07-18 | >10% | ≤5% at 98% | 12 | 5 / 7 / 0 |
| MACQ-MGU-2012 | Macquarie | settlement (Western Investment) | MGU | 2012-10-17 | >8%, daily, **and** >25% take-up | ≤10% at **92%** | 1 | 1 / 0 / 0 |
| IRL-2012 | New Ireland Fund | board | IRL | 2012-05-10 | ≥10%, daily closes, **and** >50% take-up | ≤5% at 98% | 1 | 0 / 1 / 0 |
| EV-ETJ-2013 | Eaton Vance | board | ETJ | 2013-11-14 | >9.75%, VWAP, any month Feb–May 2014 | 10% at **96%** | 4 | 0 / 4 / 0 |
| DWS-2014 | Deutsche | board | EEA, GF, CEE | 2014 | >10%, 15 weeks | ≤5% at 98% | 3 | 2 / 1 / 0 |
| NUV-DRA-2014 | Nuveen | at IPO | DRA | 2014-09 | >10%, daily | ≤10% at 99% | 1 | 1 / 0 / 0 |
| NB-NRO-2016 | Neuberger Berman | board | NRO | 2016-07-26 | >10%, daily | ≤15%, then ≥8%, at 98% | 3 | 1 / 2 / 0 |
| ZWEIG-2016 | Virtus | settlement (Karpus) | ZTR, ZF | 2016-04-05 | >8%, **Bloomberg VWAP** | ≤5% at 98% | 4 | 3 / 0 / 1 |
| ZWEIG-DCA-2016 | Virtus | board | DCA | 2016-09-07 | not found | ≤5% | 1 | unknown |
| MFS-CXH-2017 | MFS | settlement (Karpus) | CXH (muni) | 2017-07-11 | >6%, daily closes | ≤7.5% at 98% | 1 | 1 / 0 / 0 |
| BLK-DSU-2017 | BlackRock | board | DSU (loans) | not found (first EDGAR mention 2018-03-02) | >7.5%, daily | 10% then ≥5%, at 98% | 3 | 3 / 0 / 0 |
| DEL-DDF / DGF / DEX | Delaware | prospectus (1993, 1994) / board (2018) | DDF, DGF, DEX | 2010-09-03 / 1994-02-25 / 2018-05-24 | >10% / >3% / >10%, weekly closes, **end date unpublished** | 5% at 98% (as conducted) | 3 + 1 + 4 | 7 / 1 / 0 |
| NUV-NBB-2018 | Nuveen | merger condition | NBB (taxable muni) | 2018-11-19 | any average discount (>0%), 10 days | ≤20% at **100%** | 1 | 1 / 0 / 0 |
| ABRDN-AEF-2018 | Aberdeen | settlement (City of London) | AEF | 2018-04-30 | >11%, rolling 12 months | 15% | 1 | 1 / 0 / 0 |
| EV-EIM-2019 | Eaton Vance | board | EIM (muni) | 2019-03-27 | >6%, VWAP, 120 days | ≤5% at 98% | 2 | 2 / 0 / 0 |
| HERZ-2019 | Thomas J. Herzfeld | board | CUBA, now HERZ | 2019-05-31 | >10%, each fiscal year | 5% at **97.5%** | 7 | 6 / 0 / 1 |
| EV-2021 | Eaton Vance | board, after the Saba contests | EFT, EFR, EVF (loans) | 2021-05-12 | >10%, VWAP, January–August | ≤10% at 98% | 9 | 2 / 7 / 0 |
| FT-GIM-2021 | Franklin Templeton | board | GIM (global bonds) | not found (withdrawn 2021-10-13) | ≥8% | ≤20% at 98% | 1 | withdrawn mid-window |
| TORT-2022 | Tortoise | board | TYG, NTG, TTP, NDP, TPZ | not found (first EDGAR mention 2022-08-23) | >10% | 5% at 98% | 10 | 10 / 0 / 0 |
| BLK-2024Q | BlackRock | settlement (Karpus, 2024-05-03) | 14 equity funds and MVF (muni) | 2024-05-03 | >7.5%, daily, quarterly | 2.5% at 98% | 60 | 40 / 19 / 1 |
| ZTR-2024 | Virtus | board | ZTR | 2024-03-11 | ≥12%, then 10%; 180-day windows | 10% at 98% | 2 | 2 / 0 / 0 |
| EV-EIM-2024 | Eaton Vance | settlement (Karpus) | EIM (muni) | 2024-05-06 | >7.5%, VWAP, 4 months | 5% at 98% | 2 | 2 / 0 / 0 |
| BLK-2025E | BlackRock | board | 12 equity funds | 2025-02-28 (window from 2025-01-01) | >10%, 9 months | ≥5% at 98% | 12 | 0 / 12 / 0 |
| BLK-BKT-2025, -2026 | BlackRock | board | BKT (MBS) | not found / 2025-11-14 | >7.5%, 12 weeks | ≥5% [S] | 1 + 1 | 0 / 1 / 1 (the 2026 result was not on EDGAR by 2026-10-09) |
| JOF-2025 | Nomura | board | JOF | 2025-06-06 | ≥9%, 9 months | 10% at 98% | 1 | 1 / 0 / 0 |
| BLK-2026E | BlackRock | board | 13 equity funds | 2025-11-14 | >10%, 9 months | ≥5% at 98% | 13 | 1 (BMEZ) / 12 / 0 |
| BLK-2026M | BlackRock | board, on completing mergers | MHD, MYN, MUC (2026-02-09); MQY, MYI, MUA (2026-02-23) | after the window began | >10%, 9 months | ≥5% at 98% | 6 | 0 / 6 / 0 |
| SUNAMERICA-2010 | SunAmerica | board | FGF, FGI | 2010-09-14 | >10%, VWAP, 12 weeks in 2011 and 2012 | ≤10% / 5% at 98% | 2 | superseded (the funds deregistered in 2012) |

What the terms have in common:

- The threshold is 10% in 21 of the 40 programmes; the range is 0% to 12%.
- The price is 98% of NAV in 27, and between 92% and 100% in the others.
- The tender is small: 2.5% to 20% of shares. Pro-ration is correspondingly
  severe: the median of the 21 recorded pro-ration factors is 9.93% (range
  6.38% to 37.25%), so a holder who tenders sells about a tenth of the shares
  tendered.
- Six programmes came from activist settlements: Karpus (four), City of London
  and Western Investment.
- Asset classes: equity dominates. About a dozen programmes touch credit: GFY,
  DSU and EV-2021 (loans); NB-2009, CXH, EIM, MVF and the BlackRock 2026 munis
  (muni); NBB (taxable muni); NHS (high yield); GIM (global bonds); BKT (MBS).

## 3. Counts

| measure | value |
|---|---|
| programmes / sponsors / funds | 40 / 20 / 65 |
| fund × window rows | 208 |
| outcomes | triggered 103, triggered (inferred: a tender was filed under the policy) 4, triggered then cancelled 2, not triggered 71, not triggered (inferred) 18, superseded 4, unknown 3, suspended 1, withdrawn 1, waived 1 |
| triggered share, known outcome / documented outcome only | 55.1% / 59.7% |
| independent groups: sponsor × announcement date | 39 |
| independent groups: sponsor × window end, known outcome (2010–2026 / pre-2023) | 66 / 47 |
| of which at least one fund triggered (all / pre-2023) | 53 / 36 |
| sponsors behind those clusters (all / pre-2023) | 17 / 17 |

Sponsor clusters by the year their window ended:

| year | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clusters | 4 | 7 | 6 | 5 | 6 | 2 | 1 | 3 | 3 | 3 | 3 | 1 | 3 | 3 | 7 | 6 | 3 |
| fund-windows | 12 | 14 | 9 | 9 | 9 | 2 | 1 | 3 | 3 | 3 | 4 | 1 | 9 | 9 | 51 | 31 | 22 |

**Fewer than seven independent windows a year, every year.** The 2024–26 bulge
is one sponsor (BlackRock) measuring 13–19 funds over the same weeks.

Delaware's triggered windows have no published end date, so their 7 rows
count as fund-windows but not as clusters. DEX's 2020 non-trigger is dated to
the half-year that contains it, and only for the index check and the cluster
count.

**An observation, not a finding.**

- Published averages bunch at the threshold: 22 of 117 lie within 0.5
  percentage points of it.
- Most of these are DWS's 2012–15 windows: −10.18 (triggered), −9.99 (EEA
  2014, missed by 0.0003 percentage points), −10.01, −10.15, −9.98 and so on.
- Whether that is a board managing its buybacks around a line, arbitrage
  pressure, or chance in a programme that measured three funds a year is not
  testable on these counts. It is recorded here so that nobody re-discovers it
  as a signal.

## 4. Can the trigger be computed daily, ex ante, from public data?

| requirement | count | note |
|---|---|---|
| window dates public before the window began | 111 of 208 fund-windows | 42 known to be after, 55 not shown either way. "Public" = a cited filing stating the dates dated on or before the start, or a fixed-date programme announced before it |
| ...known to be **after** the start | 42 | Delaware (end date set by the board and not published); BlackRock 2024-Q2, 2025 and the 2026 munis; NRO 2016. (Tortoise's second window is first stated on EDGAR 22 days after it began; an earlier press release may exist, so it is counted as not shown) |
| metric computable from a daily close and NAV | 184 of 208 | the other 24: 19 daily VWAP (Eaton Vance, Zweig "Bloomberg VWAP", SunAmerica), 4 monthly VWAP (ETJ), 1 ten-day VWAP run (KEF) |
| a panel covers at least 95% of the window's sessions | 109 of 185 dated | 38 of 72 before 2023; 71 of 113 after |
| panel reproduces a published average within 0.25 percentage points | **81 of 81** | median 0.003, maximum 0.043. Headline panel: CRSP raw close + yfinance NAV for 56 rows, yfinance for 21, CEFConnect daily for 2, the live panel for 2 |
| coded outcome agrees with the panel's own trigger reading | **109 of 109** | includes 12 of the 18 inferred non-triggers |

Three points matter for anyone building on this.

1. **"Average daily discount" is close/NAV, simple mean, every session.**
   Where a sponsor publishes the figure and does not specify a basis, our close
   panels reproduce it to a few thousandths of a percentage point. That holds
   for BlackRock, DWS, Neuberger, Swiss Helvetia, Aberdeen and Virtus. So the
   undefined majority of programmes is computable from closes.
2. **The C4 yfinance closes cannot be used for NRO.** They misstate its
   discount by −4.11 percentage points (median over 6 windows) because yfinance
   re-based the close but not the NAV (`docs/REFERENCES.md` §12h). CRSP's raw
   close fixes it, to 2024-12-31 only. Any N1 build needs a raw-close source
   after 2024 for re-based funds.
3. **Most dead funds have no NAV history here at all.** That covers
   Neuberger's munis, NHS, Morgan Stanley's APF and MF, GFY, MGU, IRL, KEF,
   DSU, EIM, NBB, four Tortoise funds and Herzfeld before 2026. Plan item 0.8
   (NAV history beyond the 44) is the blocker.

## 5. The live book's exposure

From `scripts/cef/spec.py` (spec `cef_discount.v7.20260928`, 13 names): **MHD
and MQY** are the only deployed names in any programme, and only in 2026.

| | MHD | MQY |
|---|---|---|
| programme | BLK-2026M, adopted **2026-02-09** on completing its merger (absorbed MUE, BFK, BYM, BLE) | BLK-2026M, adopted **2026-02-23** on completing its merger (absorbed MYD, MQT, BKN) |
| window, trigger | 2026-01-01 → 09-30; average daily discount > 10.00%; ≥5% at 98% of NAV | same |
| published average (BMEZ SC TO-C, 2026-10-01) | **−8.17%** [V] | **−7.41%** [V] |
| live panel average (184 of 187 sessions; NAV to 2026-09-25) | −8.169% | −7.407% |
| distance to trigger at the end | 1.83 percentage points | 2.59 percentage points |
| running average on the announcement eve | −7.64% | −6.73% |
| average the rest of the window needed, as known on that eve | **−10.37%** | **−10.73%** |
| lowest running average after the first 20 sessions | −8.33% | −7.41% |
| sessions with a daily discount past −10% | 5 (min −10.89%) | 2 (min −10.45%) |

- **Neither name was near its trigger once the programme existed.** From the
  announcement, each would have needed to average a discount wider than −10.3%
  for the remaining seven months. The daily discount was that wide on only 5
  (MHD) and 2 (MQY) sessions of the whole window.
- The day-by-day running average is
  `conditional_tender_live_running_average.csv`. It uses sessions ≤ t only,
  i.e. what was knowable each evening.
- Both are 2026 **merger acquirers**: MHD completed 2026-02-09 and MQY
  2026-02-23 (Forms 425 of 2026-02-10 and 2026-02-23).
  `results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §4.2 named MHD. **MQY belongs on
  the same G6 list.** Its share count changed with the reorganisation too:
  NAVs were struck at the close of 2026-02-20 and completion was announced
  2026-02-23.
- Two dropped names are touched. **EFT and EFR**, both in the 27-name
  comparison set, were in EV-2021. EFT triggered in 2023; EFR never did.
  Only their discount levels were read here (the live panel). No return was
  computed, so the set is not consumed.
- **Not measured here:** what the book held in MHD and MQY during the window.
  That needs broker-confirmed positions (Alpaca from 2026-09-29; earlier IBKR
  records at tag `pre-clean-slate`), and it is the pod note's §4.2 check (b).

## 6. Graveyard and research-state check

- `.claude/skills/graveyard/SKILL.md` and `docs/RESEARCH_STATE.md` hold no
  tender or event entry, so nothing here re-runs a killed idea.
- `results/cef/SCALING_RESEARCH_2026-10-08.md` lists, under "do not build":
  - "tender capture alone" (about 0.5% gross, not significant net);
  - "pre-positioning on activist attacks".
  N1 is neither. The rule is published, so nothing is guessed, and positioning
  would come before the trigger, not after the announcement.
- **The census adds a reason for caution the SCALING note did not have.**
  - Tenders are small (2.5–20%) and heavily pro-rated (median factor 9.93%).
  - Most programmes have a single sponsor-wide window per year.
  - The counterparty the pod note named, holders who do not track the rule, is
    real, but the prize per window is a few percent of the float.

## 7. The proposed zero-trial gate (G-N1), and the counter

Written in the style of G1c (`results/cef/RESEARCH_PLAN_2026-10-09.md` §2), for
the team lead. **A proposal, not a ruling.** If ratified, the trial would sit on
**EVENTS** (pod note §9 item 5; `docs/RESEARCH_STATE.md`, EVENTS opened at 0 on
2026-10-09). The unit is the **sponsor × window-end cluster**, because one
sponsor's funds measured over the same weeks share one market.

| gate | measure | passes when | census today | verdict |
|---|---|---|---|---|
| G-N1a | clusters with a known outcome (documented, or checked against the index) | ≥ 30 | 66 (47 pre-2023) | **pass** |
| G-N1b | **usable** clusters: dates public before the window, close/NAV metric, a panel covering ≥ 95% of sessions | ≥ 30 | 16 | **fail** |
| G-N1c | usable clusters on each side (triggered / not), the built-in control | ≥ 10 each | 14 / 2 | **fail** |
| G-N1d | G-N1b and G-N1c on clusters ending before 2023-01-01 alone (fit without opening the time holdout) | ≥ 30, and ≥ 10 each | 10; 8 / 2 | **fail** |

The census **does not pass**.

- **The binding constraint is not the data.** Even if plan 0.8 supplied a NAV
  history for every dead fund, the clusters that are ex ante and
  close-computable number 33, of which 21 end before 2023. Only **4** of those
  did not trigger.
- A test of "does the market price the trigger probability?" needs both
  outcomes. The fit period has too few non-triggers to supply the control.
- By the pod note's rule, N1 is **D7 as a sleeve.**

What follows, as the pod note already provided:

1. **Fold N1 into C1 as hygiene**, with no trial: the book does not short a
   fund inside a live measurement window near its threshold.
   - "Near" should be measured, not written here (H14). At decision time,
     compute the average the rest of the window would need, as §5 does. If it
     is within a stated distance of the fund's recent daily range, the short is
     refused; otherwise it is allowed.
   - The event-log producer for this is
     `scripts/events/conditional_tender_census.py::running_average`, run
     against a live programme list.
2. **Keep the census current.** A new programme (a 2027 BlackRock renewal, a
   new settlement) is an SC TO-C or a 425 that the scan flags. Re-run the
   script; the gate can be re-read at any time.
3. **Re-open N1 only if** a re-run shows ≥ 30 usable clusters with ≥ 10
   non-triggers before 2023. That would need many more programmes than exist;
   the count of non-triggered windows is the thing to watch.

## 8. What is not established, and the gaps

- **Recall.** Measured only against a web search. Programmes that never
  tendered and never filed an SC TO-C can be missing, and that error inflates
  the triggered share.
- **Window dates not found:**
  - Tortoise's first 2022 window start;
  - the Zweig 2016 windows (except ZTR's ending 2017-03-17);
  - CXH's start;
  - Delaware's end dates (unpublished by design);
  - GIM's window;
  - the second windows of Swiss Helvetia and the Malaysia Fund (MF);
  - SunAmerica's windows (never set);
  - NHS's second window (the 2011 release calls 2011-07 its third).
- **Outcomes not found:**
  - MF's second window;
  - DCA's conditional tender;
  - BKT 2026 (the window ended 2026-09-30; no filing in the index through
    2026-10-09).
- **Inferred outcomes.** 18 non-triggers and 4 Herzfeld triggers rest on
  filing behaviour, not a statement. The panels confirm 12 of the 18.
- **BlackRock 2025 programme.** The outcome is [V] from the annual reports
  (N-CSR 2026-03-05). The per-fund averages were seen only in search
  summaries [S] and are not coded.
- **Announcement dates are upper bounds where only an EDGAR filing date is
  known** (NRO 2016). A press release can precede the filing.
- **No return statistic, by design.** Whether any of this was tradable is
  unknown.

## 9. Sources

Every filing cited is in `docs/REFERENCES.md` §12o, with its accession. The
quotes themselves live in `scripts/events/conditional_tender_programmes.py`,
and the script re-verifies them on every run.
