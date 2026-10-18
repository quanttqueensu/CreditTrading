# Equity merger arbitrage, and IBKR as a second broker: feasibility (2026-10-15, finished 2026-10-18)

**Special-situations sprint, job 5 of 6 (team lead, 2026-10-15). ZERO TRIALS.** No
spread, return or P&L of any deal was computed; nothing was opened, signed or
connected at IBKR. The job began 2026-10-15, stopped at a usage limit, and was
finished on 2026-10-18 (§C says what was kept and what changed).

Reproduce every number in part A:

    export QUANTT_ENV_FILE=/abs/path/config/.env      # SEC_USER_AGENT, R2, Alpaca cef key; never printed
    python3 scripts/events/merger_arb_feasibility.py --today 2026-10-18            # EDGAR, CRSP, Alpaca GETs, IBKR file
    python3 scripts/events/merger_arb_feasibility.py --offline --today 2026-10-18  # the same, from the caches
    python3 -m pytest scripts/events/tests/test_merger_arb_feasibility.py

Tables: `results/events/merger_arb/`. Hand readings: `scripts/events/merger_arb_readings.py`
(every quote is re-found in the fetched filing on each run, or the run raises).
Sources: `docs/REFERENCES.md` §12ss5. Labels: [V] fetched and read, [S] sourced
but not re-read, [U] not verified.

**Data as of:** EDGAR quarterly index to filing date **2026-10-16** (built
2026-10-18); SEC ticker file 2026-10-18; CRSP (R2 `dsedelist`/`dsenames`, counts
only) to 2024-12-31; Alpaca asset flags read **2026-10-18 22:29–22:35 UTC**
(a Sunday; paper endpoint, cef key, `GET /v2/assets/{symbol}` only); Alpaca daily
bars to 2026-10-16; IBKR `shortstock/usa.txt` header **`#BOF|2026.10.16|23:47:26`**
(fetched 2026-10-18 ~22:29 UTC; the file states no time zone). Borrow flags are
true on their date only (`CLAUDE.md` landmine 5).

---

## Verdicts

1. **Deal flow is not the constraint.** EDGAR shows **3,851** anchored deals with a
   US-listed target announced 2010 → 2026-10-16, about **210–270 a year** (160 in 2020),
   two-thirds cash [V, rule-based count, §A1]. **151** are pending candidates today,
   **64** of them stock-involved [V].
2. **Shortability of the acquirer is not the constraint either, for large caps.**
   Of the **25** pending stock-involved deals whose listed acquirer could be
   identified, **23** acquirers are `shortable` and `easy_to_borrow` at Alpaca, and
   22 of 25 cost ≤ 0.49%/yr in IBKR's file (median 0.41%) [V on 2026-10-18].
   The 39 others have no identifiable US-listed acquirer (foreign, private, or
   unresolved by the rules) [V].
3. **Reading the terms is a constraint.** On the frozen 20-deal sample, the regex
   reader got **every field right on 0 of 16 target deals**, and **none of the 12
   stated outside dates** (9 missed, 3 took the extension date). Worse, **4 of the
   10 "cash" picks were not a target's deal at all** (two buyers' share-issuance
   proxies, a reorganisation, a credit-agreement 8-K) [V, §A4].
4. **Alpha-only (D4): it fails on the published evidence, and a SPY short cannot
   fix the reason.** Net of costs, Mitchell & Pulvino's index manager has CAPM
   α 0.29%/month (t **2.9**, under 3.0) and β **0.12** (over 0.10); its β is **0.49**
   in months the market falls more than 4% and **0.02** otherwise: a short index
   put [V]. A static SPY short moves the *average* β, not the kink; flattening the
   down-market β needs long index puts, which the options ruling does not allow
   (§A6). **Verdict: a deal-completion and crash risk premium, D4 in costume**,
   least so for stock-for-stock deals (down-market β 0.15) [V].
5. **IBKR would unlock the six munis Alpaca cannot short today** (MHD, MQY, NAD,
   NEA, NVG, NZF: all `shortable: false` at Alpaca; all listed at IBKR at
   **0.83–5.15%/yr**, 30k–1m shares) and HTB small-cap acquirers, at a price:
   commissions (API needs IBKR **Pro**), market data at professional rates for any
   entity account, **0% short-proceeds interest on the first USD 100k**, and a
   **weekly manual re-authentication** that the unattended VM cannot do [V, part B].

---

## Part A — equity merger arbitrage

### A1. Deal counts, 2010–2026, from EDGAR

**Method (the script's docstring is the full statement).** EDGAR's quarterly
index lists a filing under every party with no role, so a TARGET is a filer of a
target-only form: DEFM14A/PREM14A, DEFM14C/PREM14C (merger proxy or information
statement) or SC 14D9/SC14D9C (response to a tender offer). Its deal date `d0`
walks back through its 425 / SC TO-T / SC TO-C filings. **Stock-involved** = a Rule
425 lists the target (425 covers communications in deals offering registered
securities); **cash / stock / mixed** within that = the consideration language of
the target's own announcement 8-K item 1.01 (or 425, or SC 14D9), by a rule
written before any scoring. Where structure and text disagree the deal is a
`conflict_*`, never forced. Excluded and counted: closed-end funds and BDCs
(8,258 fund CIKs), blank checks (SIC 6770 **or a SPAC name** at the anchor: 350, of
which 128 by name only), never-listed targets (635). Completed = a Form 25/25-NSE
within two years of the last anchor.

Deals by year of `d0` (in scope: listed target, not a fund or blank check):

| year | deals | cash | stock | mixed | stock-involved, unsplit | conflict | completed | tender offers |
|---|---|---|---|---|---|---|---|---|
| 2010 | 255 | 192 | 12 | 10 | 23 | 18 | 220 | 80 |
| 2011 | 221 | 155 | 12 | 11 | 33 | 10 | 191 | 76 |
| 2012 | 211 | 149 | 7 | 16 | 23 | 16 | 189 | 59 |
| 2013 | 210 | 154 | 15 | 11 | 24 | 6 | 189 | 57 |
| 2014 | 230 | 127 | 30 | 21 | 33 | 19 | 194 | 59 |
| 2015 | 244 | 129 | 25 | 26 | 38 | 26 | 214 | 59 |
| 2016 | 266 | 170 | 27 | 26 | 26 | 17 | 231 | 66 |
| 2017 | 252 | 167 | 31 | 15 | 27 | 12 | 214 | 66 |
| 2018 | 249 | 134 | 43 | 19 | 38 | 15 | 218 | 40 |
| 2019 | 223 | 131 | 33 | 14 | 28 | 17 | 199 | 40 |
| 2020 | 160 | 100 | 29 | 7 | 20 | 4 | 135 | 40 |
| 2021 | 262 | 146 | 46 | 20 | 29 | 21 | 225 | 36 |
| 2022 | 211 | 145 | 23 | 9 | 20 | 14 | 182 | 45 |
| 2023 | 210 | 138 | 36 | 3 | 21 | 12 | 187 | 47 |
| 2024 | 222 | 156 | 30 | 9 | 14 | 13 | 186 | 29 |
| 2025 | 243 | 158 | 43 | 8 | 21 | 13 | 192 | 47 |
| 2026 (to 10-16) | 182 | 124 | 13 | 15 | 13 | 17 | 95 | 25 |

`edgar_final_class_by_year.csv`, `edgar_deals_by_year.csv` [V, rule-based]. 2010–2025:
3,669 deals, of which cash 2,351, stock 442, mixed 225, stock-involved unsplit
(no consideration phrase found) 418, conflict 233.

**Second method, and what it says about the counts.**

* **CRSP merger delistings** of US common (share code 10/11, NYSE/AMEX/Nasdaq) by
  delisting year run 108 (2020) to 200 (2016), **2,501 in 2010–2024**
  (`crsp_merger_delistings_by_year.csv`) [V, counts]. EDGAR's completed count over
  the same announcement years is 2,974: EDGAR also holds ADRs, other share codes
  and targets delisted for other reasons within two years.
* **Deal-level match:** 2,303 of 2,896 EDGAR deals completed by 2024 match a CRSP
  merger delisting within ±15 days with a name score ≥ 0.85 (the repo's
  `edgar_merger_dates` matcher). Of matched deals, EDGAR **cash** falls on CRSP
  code 233 in 1,459 of 1,545 (94%), **stock** on 231 in 227 of 280 (81%), **mixed**
  on 241 in 146 of 171 (85%) (`edgar_vs_crsp_confusion.csv`) [V]. **CRSP's
  definitions of 231/233/241 could not be fetched** (the WRDS and crsp.org guides
  404'd or were not public) [U]; the concentration is consistent with
  stock / cash / mixed respectively, and that reading is the author's.
* **Known contamination of the anchor set.** A merger proxy is a target form most
  of the time, not always: in the frozen sample, 2 of 10 recent cash-class
  "deals" were BUYERS asking holders to approve a share issuance, 1 was a
  reorganisation, and 1 had picked the wrong 8-K (§A4). 182 in-scope targets
  themselves registered shares in the window (51 not completed), flagged
  `target_registered` [V]. Using the announcement 8-K's date instead of `d0`
  would move 60 deals across a year boundary [V]. **Treat the cash column as an
  upper bound**; the 4-of-10 figure is a sample of ten, not a rate.

### A2. Controller freeze-outs (SC 13E3), the sub-case handed over

A Rule 13e-3 transaction is a purchase, tender offer or proxy solicitation **by
the issuer or an affiliate** (a person controlling, controlled by or under common
control with it) that is reasonably likely to, or has the purpose to, deregister
the class or take it off its exchange (17 CFR 240.13e-3(a), eCFR point-in-time
2026-09-01) [V]. The filing is Schedule 13E-3 (EDGAR form `SC 13E3`).

| | 2010–2024 |
|---|---|
| SC 13E3 accessions (all filers, listed or not) | 751 (26–95 a year) |
| in-scope deals whose target is on an SC 13E3 in its window | 253 (6–31 a year; 31 in 2024) |
| … of which cash / stock-involved / other | 216 / 30 / 7 |
| … of which tender offers | 74 |
| … completed (25/25-NSE within two years) | 237 of 253 (**94%**), against 2,974 of 3,426 (87%) for all in-scope deals |

`freeze_out_by_year.csv` [V, counts]. The index cannot say which CIK on an SC 13E3
is the issuer and which the affiliate, so an accession is counted once and a deal
is flagged when its target is on one. **A flagged deal is a controller freeze-out
OR a management/sponsor buyout with rolled management equity; EDGAR's index does
not separate them** [V for the limitation]. Completion is a count, not a return.
Nothing here was read about deal protections (special committees,
majority-of-minority conditions) or Delaware law; none of that is claimed.

### A3. Today's pending deals, and whether the short leg can be built

**Pending candidate** = in scope, not completed, `d0` within 548 days of the index
date, target listed today and `active` at Alpaca, and no 8-K item 1.02 by the
target naming a merger agreement after `d0`. Recent stock deals often have no
target proxy yet, so recent 425 components with no anchored member are added,
with **roles by registration**: the member that filed an S-4/F-4 is the acquirer,
the other the target (the 425 header's "subject company" is often the issuer
itself; the header rule this replaced listed PNC, Amazon and Palo Alto Networks
as targets). Blank checks, split-off exchange offers (a member filed SC TO-I) and
ambiguous components are skipped or left unresolved, and counted
(`pending_funnel_2026-10-18.json`).

| pending candidates, 2026-10-18 | n |
|---|---|
| all | 151 (anchored 119; from 425s 32) |
| cash (no 425), plus 8 where the text reads stock or mixed (`conflict_cash_*`) | 79 + 8 |
| stock-involved (stock 28, mixed 8, unsplit 26, stock/cash conflict 2) | 64 |
| … with a US-listed acquirer identified | **25** |
| … whose last 425 by either party is over 180 days old (`stale`, still undelisted) | 12 of 64 |

**The acquirer leg on 2026-10-18** (`pending_deals_2026-10-18.csv`):

* **Alpaca:** 23 of 25 acquirers `shortable: true` and `easy_to_borrow: true`; the
  two that are not (ABTC, NDRA) are small caps in 425-pair deals [V on date].
* **IBKR file:** all 25 listed. Fee median **0.41%/yr**, 22 of 25 ≤ 0.49%;
  JMSB 1.08%, ABTC 2.92%, NDRA 3.39% [V on the file's stamp].
* **Every listed acquirer with a 425 in the last 120 days** (47, paired or not;
  `live_acquirers_2026-10-18.csv`): 35 shortable and ETB at Alpaca (IBKR median
  0.41%, max 2.49%); **12 not shortable at Alpaca**, of which IBKR lists 10, at
  0.42% (LAB, 5.4m shares: GC at IBKR, HTB at Alpaca) to **107.7%** (INM) [V].
  At Alpaca, `shortable` and `easy_to_borrow` were never different on any of
  291 symbols read; whether paper `shortable` simply mirrors ETB is [U].

So for the deals an arbitrage book would actually trade (large-cap stock
acquirers), borrow is general collateral at both brokers. Where it is not, the
target is usually a micro-cap reverse merger with no spread worth reading.

### A4. The deal-term reading problem (frozen sample of 20)

**Sample (declared by rule before reading; frozen in commit `f024f2a` before any
reading was written):** among in-scope deals announced on or after 2026-01-01
whose document is the target's own 8-K item 1.01, the 10 most recent cash and the
10 most recent stock-involved, by `d0`. Each document was read by hand; each
stated term carries a verbatim quote that the run re-finds in the filing. The
machine column is `machine_terms` (regexes in the script).

| field (16 target deals) | agree | machine missed | machine wrong | n |
|---|---|---|---|---|
| consideration class | 14 | 2 | 0 | 16 |
| cash per share | 13 | 1 | 2 | 16 |
| exchange ratio | 13 | 3 | 0 | 16 |
| collar | 15 | 1 | 0 | 16 |
| CVR | 16 | 0 | 0 | 16 |
| **outside date** | 4 | **9** | **3** | 16 |
| HSR condition | 15 | 1 | 0 | 16 |
| other regulatory condition | 10 | 6 | 0 | 16 |
| "no financing condition" stated | 15 | 1 | 0 | 16 |
| target vote | 13 | 3 | 0 | 16 |
| termination fee | 10 | 6 | 0 | 16 |

`deal_term_scores_2026-10-18.csv`, per deal `deal_term_scores_by_deal_2026-10-18.csv` [V].
"Agree" includes both-absent: the 4 outside-date agreements are the 4 8-Ks that
state no date. **No deal had all eleven fields right** (1 to 5 wrong each).

What made them hard, each quoted in the readings file:

* **Not a target at all (4 of the 10 cash picks):** Victory Capital and Swarmer are
  buyers whose proxies approve share issuances; NovaGold is a 1-for-1 holdco
  arrangement; MarineMax's wide-window 8-K 1.01 is a credit facility.
* **Dates:** extensions read as the outside date (Baldwin, Weave, Sanara); dates
  printed before their defined term (EFSI, BioLife); relative dates ("six months
  after the date of the Merger Agreement", "within one year"); dates only "as
  defined in the Merger Agreement" (Mistras).
* **Consideration:** a fee read as the price (Bowman: "$26,861,672 in cash");
  two cash legs from two payers (Cherry Hill, $0.41 + $0.52); a ratio with one
  decimal (Centerspace "3.8"); ratios before their defined term (EFSI, TriCo);
  a **fixed-value collar** whose hedge ratio moves with the acquirer's 10-day VWAP
  (Iridium/Rocket Lab, 0.4000 to 0.2400 between $67.50 and $112.50); a
  non-transferable CVR (SoundThinking); a "mixed" deal whose stock leg is about
  $2 of $35 (Sanara).
* **Conditions:** HSR printed with non-breaking hyphens (Weave); antitrust and
  FDI named without HSR (Synaptics, with a $320m regulatory reverse fee); four
  bank regulators (TriCo).

**Conclusion:** the counts can be automated; the terms a position is sized on
cannot, at the level of a regex. A trial would need a human (or a verified
reader) per deal, and an outside date read from Exhibit 2.1, not from the 8-K.

### A5. The literature

| finding | source | status |
|---|---|---|
| 4,750 mergers 1963–1998. Risk-arbitrage index manager (RAIM), **net of commissions and price impact**: CAPM α **0.29%/month (s.e. 0.10)**, β **0.1232 (0.0236)**; FF3 α 0.27% (0.11), β 0.1052. Ignoring costs (VWRA): α 0.74% (0.13), β 0.054. Piecewise (kink at −4%): RAIM β **0.4920** below, **0.0167** above, intercept 0.53%/month. Cash deals β 0.7745 below / 0.1024 above; **stock deals 0.1528 / −0.0766** (1975–98). HFR merger-arb funds 1990–98: 0.5985 / 0.1042. Contingent-claims excess return **4%/yr** after costs; against actual index put prices (1987–96) about **29bp/month (3.5%/yr)**. Deal failure rises after market falls (a 5% decline raises failure probability by 2.25 points; hostile +12.8). "Risk arbitrage is akin to writing uncovered index put options" | Mitchell & Pulvino (2001), *JF* 56(6):2135–2175, Tables III–VI, VIII, §E | [V] read |
| 1,901 offers 1981–1996: abnormal return **0.6–0.9%/month**; market β **0.22–0.37** (value-weighted market model α 0.78, p 0.02, β 0.30); a $0.04–0.05/share cost cuts the intercepts by under 0.1%/month; returns rise with completion risk and target size | Baker & Savaşoğlu (2002), *JFE* 64:91–115, abstract, Table 3 | [V] |
| The spread fell **by more than 400bp since 2002**; median first-day spread of successful deals 6.39% (1990–95), 4.62% (1996–2001), **1.91% (2002–07)**; median monthly merger-arb hedge-fund returns 96, 99, **51bp** | Jetley & Ji (2010), *FAJ* 66(2):54–68 | [V] |
| Nearly half of a stock acquirer's negative announcement return is arbitrage short-selling pressure (2,130 mergers 1994–2000) | Mitchell, Pulvino & Stafford (2004), *JF* 59(1) abstract | [V] abstract |
| Median annualised spread of **stock** deals reached **14.2%** in the week of 6–10 Oct 2008 against a 2005–Mar 2010 mean of 2.1% (s.d. 0.78%); 10.7% after Oct 1987 | Mitchell & Pulvino, "Arbitrage crashes and the speed of capital", NBER draft rev. 2010-05-17, §7.1 (published *JFE* 2012; published text not re-read) | [V] draft / [S] journal |
| 1994–2012, 228 months, **no transaction costs**: naive value-weighted risk arbitrage α **0.89%/month (s.e. 0.16)**, β_MKT **0.32**; hedge funds beat it by 0.30%/month by managing downside risk, not by picking deals | Cao, Goldie, Liang & Petrasek (2016), *JFQA* 51(3):929–957, Table 5 (read from a copy hosted by Tsinghua PBCSF) | [V] |
| Target option prices forecast deal outcomes; merger arb has low volatility and a high Sharpe ratio when deals are likely to succeed | Van Tassel (2016), NY Fed Staff Report 761 | [V] abstract only |

Not used: a 2000–2020 vendor study summarised by Alpha Architect (secondary, no
primary text found) and student theses.

### A6. Against the alpha-only rule (D4: alpha t ≥ 3.0, |β| ≤ 0.10)

* **Net of costs it fails both legs, narrowly:** RAIM t = 0.29/0.10 = **2.9**,
  β 0.12; FF3 t ≈ 2.5, β 0.105 (MP2001) [V inputs, division mine]. Later samples
  carry more linear beta: 0.22–0.37 (BS2002), 0.32 (CGLP 2016, gross) [V].
* **Gross of costs it can pass linear D4** (VWRA: t ≈ 5.7, β 0.054) and still be a
  short put (VWRA down-market β 0.4757) [V]. **A linear D4 test is the wrong
  test for this payoff**; any pre-registration must also state the down-market
  (piecewise) β, and our 2010–2026 window has few months below −4%, so that
  estimate will be imprecise.
* **A SPY short cannot neutralise it.** Sized to the full-sample β (0.12), it
  leaves about **+0.37** in months below −4% and about **−0.11** otherwise
  (0.49 − 0.12; 0.02 − 0.12: arithmetic on MP2001's coefficients) [V inputs]. It
  zeroes the regression β and keeps the crash. SPY was shortable and ETB at
  Alpaca on 2026-10-12 (§12r) [V on that date].
* **A short put needs options to undo:** a long index put (or put spread). At
  Alpaca, buying puts is Level 2 and spreads Level 3 [V]; but options are open on
  this desk only through one pre-registered **short**-premium test (team lead,
  2026-10-09, `docs/SYSTEM.md` §5). A long-put hedge would need a ruling, and MP2001
  compared risk arbitrage with selling actual index puts (1987–96) and still found
  about 29bp/month (3.5%/yr) of excess: roughly what a put-hedged book would keep
  before option costs [V figure; the reading is the author's].
* **Least beta where the short leg does the hedging:** stock-for-stock deals
  (down-market β 0.15, MP2001 Table VI) and large-cap acquirers, the set where
  borrow is general collateral (§A3). Cash deals, where financing and failure
  risk rise in a crash, are the put.

**Verdict:** under the 2026-10-09 "alpha only" ruling, equity merger arbitrage
as an index (all deals) is a **risk premium in costume (D4)**. A stock-only,
acquirer-hedged, hand-read variant is the only version with a case, and it has
not been tested here (a test is an EVENTS trial).

### A7. Capacity at $100k – $5m

Pending deals that absorb a position of X in one session at the desk's 5%
participation guard (`scripts/cef/plan_diagnostics.py`, `adv`: a convention,
not a measured impact threshold), on each name's median dollar volume over its
last 63 Alpaca sessions to 2026-10-16 (`capacity_2026-10-18.csv`) [V]:

| position per deal | ADV needed | cash deals fitting (of 79) | stock deals: acquirer shortable+ETB (of 64) | stock deals fitting both legs |
|---|---|---|---|---|
| $10k | $0.2m | 60 | 23 | 23 |
| $25k | $0.5m | 57 | 23 | 22 |
| $50k | $1m | 54 | 23 | 21 |
| $100k | $2m | 52 | 23 | 20 |
| $250k | $5m | 43 | 23 | 18 |
| $500k | $10m | 36 | 23 | 17 |

A $100k book in 10–20 deals ($5–10k each) or a $5m book in 20 deals ($250k each)
both fit, in one session, in 40–80 deals. **Capacity at this size is set by how
many deals are live and readable, not by ADV**; the cash column overstates
(§A1's contamination), and one session is the wrong unit for a position held for
months.

---

## Part B — IBKR as a second broker (documents and public files only)

Nothing was opened, signed up for or connected to; no IBKR login, API or TWS was
used. Pages fetched 2026-10-18; URLs and status in `docs/REFERENCES.md` §12ss5.
Any IBKR code ever revived must use `ib_async`, never bare `ib_insync`
(`CLAUDE.md` landmine 10).

### B1. Accounts and minimums

* **Individual, joint, trust, IRA, UGMA/UTMA** for individuals; **small business**
  accounts "for corporations, LLCs, partnerships and operating businesses";
  advisor, hedge-fund and proprietary-trading-firm structures [V].
* **Minimum equity: cash none; margin USD 2,000 to open; portfolio margin USD
  110,000** "along with jurisdictional and risk-based approval" [V]. Ages 18–20:
  cash account and options Level 1 only [V]. What happens to a PM account that
  falls below USD 110,000 is not on the page [U].

### B2. Reg T vs portfolio margin

* IBKR: margin accounts "allow borrowing and short selling with a $2,000 minimum
  equity"; "Portfolio Margin uses real-time risk-based calculations" and needs
  USD 110k and approval [V]; in IBKR's institutional table corporations and
  hedge funds are PM-eligible "Yes", advisors "Yes (if qualified)" [V]. PM's offsets are what a hedged pair needs; the team lead's
  2026-10-09 ruling keeps Reg T for now with PM a research item (`docs/SYSTEM.md` §5).
* The **Pre-Borrow Program is for PM accounts only** [V]; the page still says a
  short "settles on T+3", which is stale (US settlement is T+1 since 2024-05-28,
  §12b line 511 [V]): the page is old even where it is accurate.

### B3. Borrow, locates and fees

* **Availability:** a Client Portal shortable search ("updates periodically
  throughout the day") and the public `shortstock/usa.txt` file; "IBKR does not
  accept short sale orders for US stocks that are not eligible for DTC continuous
  net settlement (CNS) and all short sale orders are subject to approval by IBKR"
  [V]. US: 19,988 shortable of 24,184 listed for trading on the page's day [V].
* **How a locate is obtained** for an ordinary (non-PM) short: IBKR's knowledge-base
  article (node 240, Reg SHO) redirects to a host that returned HTTP 403 [U]. The
  2026-09 record that recall terms are contractual, not Reg SHO, stands (§3, line 108) [U].
* **Fees:** borrow fee = market value × rate / 360 on 102% collateral (§4, line 118)
  [V]. **Short-sale proceeds interest (IBKR Pro, USD): 0% on the first USD 100,000;
  2.630% (BM − 1.25%) on 100k–1m; 3.380% (BM − 0.5%) on 1m–3m; 3.630% (BM −
  0.25%) above;** accounts with NAV under USD 100k are paid proportionally less [V,
  2026-10-18]. These tiers were 2.380 / 3.130 / 3.380% on 2026-09-09 (§3, line 105):
  the same spreads to a benchmark 25bp higher, a dated change, not an error.
* **Our CEF names today** (`cef_names_borrow_2026-10-18.csv`) [V on date]:

| name | Alpaca shortable / ETB | IBKR fee %/yr | IBKR available |
|---|---|---|---|
| AWF | yes / yes | 0.81 | 600,000 |
| BIT | yes / yes | 0.93 | 200,000 |
| DSL | yes / yes | 0.41 | 1,100,000 |
| HYT | yes / yes | 0.47 | 3,600,000 |
| JFR | yes / yes | 1.81 | 1,200,000 |
| PCN | yes / yes | 0.58 | 2,200,000 |
| PDI | yes / yes | 0.25 | > 10,000,000 |
| PDO | yes / yes | 0.41 | 2,200,000 |
| PFN | yes / yes | 0.40 | 1,500,000 |
| PHK | yes / yes | 0.58 | 2,800,000 |
| PTY | yes / yes | 1.25 | 6,700,000 |
| **MHD** | **no / no** | 2.49 | 1,000,000 |
| **MQY** | **no / no** | 0.83 | 85,000 |
| **NAD** | **no / no** | 5.15 | 200,000 |
| **NEA** | **no / no** | 2.46 | 850,000 |
| **NVG** | **no / no** | 4.24 | 30,000 |
| **NZF** | **no / no** | 3.20 | 200,000 |

### B4. Options permissions

* **IBKR, four levels:** 1 covered calls; 2 adds long calls/puts, long
  straddles/strangles, protective positions; 3 adds "options strategies that have
  limited maximum potential loss such as short puts and short, long or unbalanced
  butterflies"; 4 "all options strategies" [V]. This verifies §6, line 188 [S], with
  one nuance: IBKR puts **short puts in Level 3**.
* **Alpaca, levels 0–3:** 1 covered call and cash-secured put; 2 adds buying calls
  and puts; 3 adds call and put spreads; no uncovered short options (§12d, line 578)
  [V, re-read 2026-10-18]. A long index-put hedge is available at Alpaca today;
  what IBKR adds is margined short premium (Level 3/4).

### B5. Market data, especially OPRA

* **OPRA Top of Book (L1): USD 1.50/month non-professional, waived at USD 20 of
  monthly commissions; USD 32.75 professional.** Equities L1: NYSE (Network A)
  1.50 / 45.00, Network B 1.50 / 25.00, Nasdaq 1.50 / 25.00. Snapshot bundle USD
  10 base, waived at USD 30 of commissions; the "US Equity and Options Add-On
  Streaming Bundle" 4.50 / 125.00, whose footnotes say it includes the three tapes
  and OPRA and requires the snapshot bundle [V; the footnote-to-row mapping is by
  footnote number, S].
* **An entity is professional.** IBKR's definition: a non-professional subscriber
  is "any natural person (the definition of a natural person excludes
  corporations, trusts, organizations, institutions and partnership accounts)"
  [V]. A small-business account would pay the professional column: about USD 128
  a month for L1 on the three tapes and OPRA (45 + 25 + 25 + 32.75, arithmetic).
* **CORRECTION to `docs/REFERENCES.md` §6, line 190** ("OPRA … ~$10/month for
  non-professionals, waived at $30 monthly commissions", [S]): on 2026-10-18 the
  OPRA line is USD 1.50 (waived at USD 20); USD 10 / USD 30 is the US Securities
  Snapshot and Futures Value Bundle. Recorded in §12ss5.
* Paid options data is "None" by the team lead's 2026-10-12 ruling; OPRA at IBKR
  would be a paid feed and needs a ruling.

### B6. API: TWS / IB Gateway

* Needs **a funded and opened IBKR Pro account** (not Lite), the current TWS or IB
  Gateway, and Python ≥ 3.11 for the official client [V]. "If a certain feature or
  operation is not available in the TWS, it will not be available on the API side" [V].
* **2FA is required for all users**; supported for API logins: IB Key, smartphone
  apps, SMS, DSC+ [V].
* **Weekly re-authentication:** "The weekly authentication cycle starts on every
  Monday" and a soft-token failure "means you need to manually login again" [V].
  Daily: choose "Auto restart" [V]. **An unattended VM cannot satisfy a weekly
  manual 2FA login**; the Web API and FIX alternatives were not evaluated [U].
* **Pacing:** market data lines / 2 requests per second, 50 by default; over the
  limit TWS paces or rejects (error 100, session dropped after three) [V].
* **One username, one trading application at a time**; extra usernames can be
  added; a paper session sharing data with a live user logged into Client Portal
  receives no market data [V].
* **Order IDs are client-managed, strictly increasing, persistent between
  sessions**, resettable only with no active API orders [V]. **"Maintain and
  resubmit orders when connection is restored" is on by default**: orders
  received while connectivity is lost are resubmitted on reconnect [V] (see B8).
* MOC: IBKR's MOC page restates NYSE's 15:50 ET entry and cancel cutoff and
  Nasdaq's 15:55 [V].

### B7. Paper trading

* Needs an approved, funded live account (or a free trial); new individual
  holders get one automatically; USD 1,000,000 of paper equity; permissions and
  data subscriptions mirror the live account [V, ibkrguides, "Last updated on
  January 30, 2026"].
* Limits: no VWAP, **Auction**, RFQ or Pegged-to-Market orders; fills "simulated
  from the top of the book"; no penny option fills; the remainder of a partly
  filled exchange-directed market order is rejected [V]. Whether paper MOC orders
  fill at the official close was not stated [U]. Paper option P&L proves nothing
  (`docs/BRIEF.md` §3).

### B8. Can one book run across Alpaca and IBKR?

Yes, but only as two accounts that never meet, routed **by symbol**, and with
margin lost on anything split.

1. **Margin does not cross brokers.** Each broker margins its own account; a long
   at Alpaca cannot carry a short at IBKR, so a pair split across brokers is two
   naked legs, and PM offsets apply only inside the IBKR account (reasoning; no
   source needed beyond two legal entities). Each account needs its own gross and
   stress caps; `max_gross_stress` is a book number and would have to be split.
2. **Wash sales are the taxpayer's, across accounts; brokers report only within
   one.** Form 1099-B box 1g: a broker *must* report a disallowed loss only "if
   both the sale and purchase transactions occur in the same account with respect
   to covered securities with the same CUSIP" [V]. Publication 550: the rule
   applies to the taxpayer (including "a corporation you control") and to short
   sales [V]. A two-broker book must compute its own cross-account wash sales;
   neither 1099-B will.
3. **Alpaca's wash-trade check sees only Alpaca.** It rejects (HTTP 403) a
   customer's order that "could potentially interact" with another of their open
   orders; the page does not say whether "customer" means account [U]. Nothing
   stops a buy at IBKR and a sell at Alpaca in the same closing auction. That is
   no change in beneficial ownership: FINRA 5210.02 treats unintentional
   same-firm self-trades as generally bona fide [V opening clause; S rest], and
   Exchange Act §9(a)(1) prohibits such trades when done to create a false
   appearance of trading [V]. **Design rule: each symbol is assigned to one
   broker per session and netted there; never opposite sides at two brokers.**
4. **Idempotency (order-path rule 2) for two brokers.** Today's gate refuses on a
   `STARTED` marker, an Alpaca order with today's `cef-<date>-` prefix, or any open
   `cls` order (`docs/RUNNER.md` gate 6). Across two brokers it must become: one
   `STARTED` per (book, date) **and** per broker, written before that broker's
   first order; the refusal checks **both** brokers' open orders for the date
   before sending to **either**; IBKR has no Alpaca-style `client_order_id`, so the
   runner must tag IBKR orders itself and list them (the open-orders feed exists
   [V]; the tag field, `orderRef`, was not read in IBKR's docs [U]); and the
   default **resubmit-on-reconnect** setting means an order sent before a
   disconnect may still go: the runner must reconcile open orders before any
   retry, or turn the setting off. MOC orders cannot be cancelled after 15:50, so
   there is no cross-broker undo: **route both legs of a pair to the same broker**,
   and send the leg likelier to fail (the hard-to-borrow short) first.

### B9. What a second broker would unlock

* **Muni CEF shorts:** the six munis above, shortable at IBKR and not at Alpaca on
  2026-10-18; this is also E1-G1a's failing leg (`results/events/G1A_SHORTABILITY_2026-10-13.md`).
* **HTB acquirers:** 10 of the 12 live acquirers Alpaca will not short (§A3), at
  0.42–107.7%/yr.
* **Margin:** portfolio margin from USD 110k, and pre-borrow (PM only).
* **Options:** margined short premium (IBKR Level 3/4) and an OPRA NBBO feed;
  neither is needed for a long-put hedge, which Alpaca Level 2 allows.
* **Futures and swaps "through another broker"**, in bounds since 2026-10-09; not
  researched here.

---

## Decisions for the team lead

1. **Merger arbitrage:** close it under the alpha-only rule (recommended), or
   authorise one pre-registered EVENTS trial restricted to stock-for-stock,
   large-cap-acquirer deals, hand-read, with D4 stated on the down-market β as
   well as the linear one.
2. **A long-put hedge** for any short-put-like sleeve is outside the 2026-10-09
   options ruling (short premium only). Rule on it only if (1) proceeds.
3. **IBKR:** do not open it for merger arbitrage. If the muni shorts are wanted,
   decide **individual vs entity** (market data professional for any entity),
   **Reg T vs PM** (USD 110k), and **how prod authenticates** (weekly manual 2FA vs
   an unevaluated Web API / FIX route).
4. **OPRA at IBKR** is a paid feed against the 2026-10-12 "no paid options data"
   ruling (USD 1.50 non-pro, waived at USD 20 commissions; USD 32.75 pro).

---

## C. Provenance: what was kept from the 2026-10-15 session, what changed

**Kept:** the EDGAR deal-assembly rules (anchors, chain, union-find joint proxies,
non-registrant target rule, two-year completion, listed test), the consideration
classifier and its tests (including the cash-in-lieu strike-out, checked to fail
without it), the CRSP cross-check, the 20-deal sample **rule** and the readings
file's verify-every-quote design; the closed-quarter EDGAR indexes it had copied
and cross-checked against a second cache (67 of 67 identical).

**Changed or added on 2026-10-18:** the pending-deal role rule (header subject →
registration; checked to fail against the old rule), with name-confirmed pairing
of lone targets and acquirers; SPAC-name and split-off (SC TO-I) exclusions;
day-fresh submissions for pending deals; Alpaca class-share symbols; IBKR
duplicate rows reported instead of dropped; the 13E-3, capacity and
live-acquirer tables; the frozen sample and all twenty readings (none had been
written); role-aware, deal-level scoring. Every literature figure and IBKR term
was re-fetched and re-read on 2026-10-18 (the earlier session's downloads did not
survive). The note is dated 2026-10-15 because the brief names it so; the data
are as of 2026-10-16/18.
