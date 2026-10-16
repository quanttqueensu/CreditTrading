# Special-situations catalogue, half 1: corporate actions and fund/vehicle structure — 2026-10-15

**What this is.** The team lead asked on 2026-10-15 to "find all sub event driven /
special situation trading strategies systematically", for a niche-heavy event layer
beside the live CEF discount book. This is half 1 of 2. It covers **corporate
actions** and **fund and vehicle structure**. Half 2 (credit and other instruments)
is on the sibling branch `ss-catalogue-credit`.

**Zero trials.** No return or P&L of any strategy was computed. Nothing in this note
is a backtest. Counters as printed by `python3 -m ops.orient` TRIALS on 2026-10-15
[doc]: CEF 52, GAMMA 0, EVENTS 0, XASSET 4. **No counter moves.** (The
unique-angle brief's "CEF at 48" is stale; the ledger moved to 52 on 2026-10-14.)

**Holdouts.** No 2023+ market data was read. Event *counts* use CRSP to 2024-12-31
and EDGAR to 2025-12-31, as counts only (the rule in `scripts/events/crsp_events.py`).
Pre-event liquidity uses only events dated 2018-01-01..2022-12-31 and `dsf` rows
before 2023, and the script raises on a 2023+ row. No `cef_universe.csv` name had a
return computed, so the 27-name holdout is untouched.

**Every count re-runs** from `python3 scripts/events/ss_catalogue_counts.py all`
(aggregates in `results/events/ss_catalogue/`; row-level CRSP rows stay in the
gitignored `_cache_rows/`). Sources are in `docs/REFERENCES.md` §12u.

**Data dates.** CRSP: R2 WRDS mirror, CIZ tables, ends 2024-12-31, read 2026-10-15.
EDGAR: quarterly `master.gz` indexes 2008Q1–2025Q4, read through
`scripts/data/edgar_client.py` offline from the `research-edgar` worktree's cache
(fetched there 2026-10-12; closed quarters are immutable). Alpaca: paper endpoint,
`cef` key, read-only GETs, 2026-10-15 16:35–16:44 ET. **Alpaca flags are true on
that date only** (CLAUDE.md landmine 5).

---

## 0. The answer

**Swept: 52 candidates in 14 families** (§3).

| status | n | which |
|---|---:|---|
| already in the desk's graveyard (KILLED, do-not-build, PARK or dead) | 6 | A1 (tender capture, do-not-build), E5 (M7, dead), I4 (`raw-flow-z`, D1), J4 (BDC discount z, PARK), J6 (term-CEF pull-to-par, PARK), L1 (listed capital stack, PARK) |
| covered by queued work or a sprint branch (referenced, not redone) | 9 | A4, H1 (`ss-merger-arb`); D1 (plan 2d); E2 (CORE ex-cycle freeze); E4 (B3); I3 (B2); J5 (E4); J7 (`ss-cef-events`); L3 (E3) |
| closed in this note at zero trials, by a fetched rule, a measured count, borrow or capacity | 20 | A2, A3, A5, B2, B4, C2, G1, G2, H2, I1, J1, J2, J3, J8, K2, K3, M1, M2, N1, N3 |
| risk inputs, not alpha | 3 | E3, N2, and I2 as a calendar |
| open and scored | 14 | 8 for gates (below); 6 parked at a score of 2 or less (B3, D2, F2, K1, K4, L2) |

**The top 8 for zero-trial gates** (score = events × edge × feasibility, each 0–3, §2):

| rank | id | candidate | score | the zero-trial gate that could kill it | counter |
|---:|---|---|---:|---|---|
| 1 | B1 | **Spin-off index-removal sale.** S&P removes an ineligible spin-off **at the close of its first regular-way day** [V]; index funds must sell in that auction | 12 | Count the 2016–22 spin-offs that S&P announced it would remove on day 1, with ADV ≥ $1m: below 30 independent parents, D7 | EVENTS |
| 2 | C1 | **Dual-class spread** on equal cash-flow claims | 9 | On 2010–22 closes, count pairs whose daily log-ratio σ exceeds the two-leg cost grid with a half-life ≤ 10 sessions; negative control: random same-industry pairs. Fewer than 10 of the 25 pairs that are shortable on both legs today: kill | needs a ruling (no event; XASSET closed) |
| 3 | K6 | **Seasoned-offering (SEO) reversal**, E2's straight-equity sibling | 9 | EDGAR 424B count of non-overnight SEOs per year after 2014. Gustafson: 75% of 2009–14 SEOs were overnight, with "less positive" post-issue returns [V]. Under 30 a year: fold into E2 as a footnote | EVENTS |
| 4 | J9 | **Leveraged-ETF close rebalancing**: provide the other side in the closing auction | 6 | Rebalance demand L(L−1)·r·AUM from CRSP shares outstanding (pre-2023), against the underlying's close volume. Below 1% on 95% of days: kill | needs a ruling |
| 5 | K5 | **IPO lock-up expiry** | 6 | Today's Alpaca shortable/ETB share of 2025 IPOs near day 180. Under half: kill (F = 0) | EVENTS |
| 6 | G3 | **Forward-split drift** | 6 | Count ≥ 2:1 splits in the fractional-share era (2020–22: 65 events [V]) and a D4 prior. No forced loser is named: say so in any pre-registration | EVENTS |
| 7 | E1 | **Special-dividend ex-day wedge** (and the ≥ 25% due-bill ex-date rule) | 3 | The CRSP 2010–22 ex-day drop ratio on specials with ADV ≥ $1m, one number. At ≥ 0.95: kill. The desk's own tax status is a counsel question | EVENTS |
| 8 | F1 | **Open-market buyback drift** | 3 | Data cost (8-K items are not in the index) and a D4 prior. Expected to close on both | EVENTS |

**Handed over, not ranked here:** **H1** (controller freeze-outs, SC 13E-3) would
score 8. It is a sub-case of equity merger arb, so it goes to `ss-merger-arb`.

**Closed by measurement in this note** (the kind of result the brief prefers):
- **J1, ETF liquidations at NAV.** The median ETF that liquidated in 2018–22 traded
  **$36.7k a day** before its announcement window. Only 5.5% traded ≥ $1m [V].
  Dead on capacity at $100k.
- **G1, the reverse-split short.** Of 2025's 727 reverse-split symbols, 432 are still
  active and **54 are shortable** today [V].
- **A1/A2, tender and odd-lot arbitrage.** Alpaca charges **$100 per voluntary
  corporate action** [V], and the stock-tender profit "has disappeared" over
  2000–15 [V abstract].

---

## 1. What binds every row (fetched, dated)

| constraint | fact | status |
|---|---|---|
| Elections (tenders, exchange offers, rights, warrants) | Alpaca's voluntary-corporate-actions page lists Dutch auction/tender, exchange, election merger, consent, rights and warrant exercise. Notice is **by email**; "**$100 per client per voluntary corporate action**". Odd-lot tenders and appraisal are not mentioned; paper accounts are not mentioned. The page is written for broker partners; whether a Trading-API account gets the same handling is unstated | [V] page `updatedAt` 2025-09-24; Trading-API applicability [U] |
| Paper scoring | Alpaca paper credits no dividends, charges no borrow and runs no auction (CLAUDE.md landmine 1). Any dividend-sensitive row needs the third P&L line (plan 0.4) | [V] (CLAUDE.md) |
| OTC | 1,163 active OTC assets, of which **308 tradable** | [V] 2026-10-15 |
| Rights | 19 active `*.RT` symbols, all on NYSE and all tradable | [V] 2026-10-15 |
| Hedges | SPY, IWM, QQQ, MDY, IJR, all eleven sector SPDRs, XBI, HYG, LQD, PFF: shortable and ETB. **KRE and MUB: not shortable** | [V] 2026-10-15 |
| CEF index ETFs | CEFS and YYY shortable and ETB; **PCEF, FCEF and CEFD not shortable**; MCEF absent from the active list | [V] 2026-10-15 |
| Execution | MOC only (`cls`; paper `late_market`). Whole shares for shorts (CLAUDE.md rules 3, landmine 3) | rule |
| Mandate | Alpha only: every sleeve faces D4 (alpha t ≥ 3.0, factor betas ≤ 0.10) | `docs/SYSTEM.md` §5 |
| Data | Free sources only: EDGAR, the R2 mirror (CRSP to 2024-12-31), Alpaca, exchange and index-provider notices | brief |

**The capacity rule used in every row** (this note's assumption, not a desk
standard). Each name is held at 5% of book, and a position may be at most 5% of one
session's ADV (one auction). An event is then usable at book size B when its ADV is
at least B. So the "capacity" cells read **the share of 2018–22 events whose
pre-event ADV ≥ $0.1m / $1m / $10m** (`crsp_pre_event_adv.csv`). ADV is mean dollar
volume over the 20 sessions ending two sessions before the ex-date. For ETF
liquidations the window is sessions −60..−41, before a typical announcement.

## 2. Method

**Event counts.**
- **CRSP:** the CIZ `stkdistributions` and `stkdelists` tables. Codes are decoded
  from the mirror's own `metaflaginfo`; the script raises if a code it keys on is
  absent. Security type at the event date comes from an as-of join on
  `stksecurityinfohist`. One event is one (permno, ex-date).
- **EDGAR:** initial forms only, counted as unique accessions. "Fund" is the
  fetcher's own `fund_set` rule.
- **Alpaca:** `/v1/corporate-actions` per calendar window (process date).

"Independent" is approximated by **distinct issuers per year** and **distinct months
with an event**. Both are printed: clustering in time is the usual reason event
counts overstate breadth.

**The score**, coarse and stated so it can be argued with (judgement, not
measurement):

| | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **E**, independent events a year | < 3, or < 30 in the fit window | 3–10 | 10–50 | > 50, or continuous on ≥ 20 independent instruments |
| **S**, plausible edge from terms or literature | literature or terms say none is left, or no loser | small, unquantified [U], or decayed | documented ≈ ≥ 1% per event [S/V], not shown to have vanished | documented, large, recent and mechanical |
| **F**, feasibility (Alpaca, $100k, alpha only, free data) | blocked | one hard obstacle (an HTB leg, costly data, paper cannot score it) | feasible with a hedge and free data; one soft obstacle | long plus an ETB hedge (or both legs ETB), MOC-compatible, free point-in-time dates |

Ties are broken by **information per trial**: a gate that can close the idea at zero
trials ranks first.

**Why the live signal cannot see any of these.** The book's z-score ranks 13 credit
CEFs against their own 252-day discount history. It sees no equity, no ETF other
than its own names, no dated event, and nothing about another instrument's level
except through the cross-sectional mean. Every row below is therefore new
information to the book. The exceptions are E2 and E3, which act on the book's own
names and are flagged.

---

## 3. The catalogue

Column key:
- **evts/yr**: mean, with the window stated. "iss" is distinct issuers a year; "mo"
  is distinct months a year with at least one event.
- **cap**: the share of 2018–22 events usable at $0.1m / $1m / $10m (§1).
- **E·S·F**: the three scores and their product.

### A. Tender and exchange offers

| id | mechanism, and who is on the other side | event source, PIT timing | Alpaca | cap | evts/yr (independent) | terms-implied edge | hold | crowding | counter | graveyard | zero-trial gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | Issuer tender (fixed-price or Dutch): buy below the tender price, tender. Loser: holders who do not tender; prices are set "as if all investors tender" (Peyer–Vermaelen [S]) | EDGAR SC TO-I (commencement), SC TO-C | Needs an **election: $100 each** [V]; paper cannot simulate it [U] | [U] | SC TO-I by non-funds **73.5/yr** (2016–25) [V]. That is an upper bound: it also holds warrant and option exchanges and convertible puts | >9% in < 1 week in 1962–86 (L&V 1990) [V]; Dutch ≈1.36% (1994) [S]; **2000–15: "abnormal profits from tendering have disappeared"** (KZY 2020) [V] | days | high | EVENTS | **Graveyard:** "tender capture alone" (SCALING §3, do-not-build) is the CEF form; the stock form is dead by the same paper | **KILL** (literature D1 plus access) | 2·0·0 = 0 |
| A2 | Odd-lot priority: Rule 13e-4(f)(3) lets the issuer accept holders of < 100 shares before pro-ration [V]. Certainty of acceptance on ≤ 99 shares | as A1 | Election $100 against at most 99 shares | 99 shares an event | as A1 | Gross = 99 × price × premium; breakeven premium = $100 / (99 × price): **2.0% at $50 a share, 10.1% at $10** (arithmetic) | days | — | EVENTS | new | **KILL**: the fee is as large as the edge | 2·0·0 = 0 |
| A3 | Split-off exchange offer: parent shares swapped for subsidiary shares at a bonus. Loser: holders who do not tender | EDGAR SC TO-I, S-4 | Election $100 | [U] | CRSP "self tender / exchange in kind" on common stock: **6 in 2010–24** [V] | the bonus terms per offer [U] | weeks | high | EVENTS | new | **D7** (6 events in 15 years) | 0·1·0 = 0 |
| A4 | Third-party tender offers / merger arb | SC TO-T 56.8/yr non-fund (2016–25) [V] | — | — | — | — | — | — | — | **covered:** `ss-merger-arb`; general merger arb is PARK (a short put) | reference only | — |
| A5 | Mini-tenders (< 5%, below market): the loser is the holder who tenders; we cannot be the bidder | none indexed | — | — | — | — | — | — | — | — | **not a trade** | 0 |

### B. Spin-offs and holding companies

| id | mechanism, and who is on the other side | event source, PIT timing | Alpaca | cap | evts/yr | terms-implied edge | hold | crowding | counter | graveyard | zero-trial gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** | **Spin-off index-removal sale.** Since 2015-10-01, S&P adds spin-offs to the parent's indices at zero price after the close before the ex-date. An ineligible spin-off is "**removed on the first day of regular way trading using its closing price on the primary exchange**" [V]. Index funds must sell in that closing auction, and large-cap mandates must sell small spin-offs. **Loser: the forced sellers' holders**, who pay the impact. The buyer of last resort in that auction is paid | Form 10 (EDGAR 10-12B, ex-date and when-issued dates); S&P index notices (free) give the removal date in advance | **Long the spin-off MOC on the removal close; short the sector SPDR** (all ETB but KRE [V]). Of 2025's spin-offs, 14 of the 32 still active are shortable [V] (not needed for the long form) | parent: 97 / 92 / 78% (n 78) [V]; the spin-off's own ADV [U] | CRSP common-stock spin-offs **21.0/yr** (2015–24; iss 19.8, mo 9.0) [V]; EDGAR 10-12B **23.8/yr** (2015–24) [V] | S&P Global (2017): spin-offs "underperformed by more than 2% in the initial 30 days", then beat peers over 1 and 3 years [S, search summary; page 403]. CMW 1993: abnormal returns only where there was takeover activity [S]. An out-of-sample replication on 1989–95 failed [S] | 5–30 sessions | high (the Greenblatt trade) but **the removal close is mechanical** | EVENTS | neighbour of **S3-forced-flow** (WATCH: forced index flow is real and reverses; S3-wrapper died D4 on its *wrapper*). Not tested | **G-B1:** count 2016–22 spin-offs that S&P announced it would remove on day 1, with ADV ≥ $1m and distinct parents. **< 30: D7, stop.** Then measure removal-day index demand against that auction's volume. The negative control, declared now: spin-offs S&P kept | 2·2·3 = **12** |
| B2 | When-issued vs regular-way parent arbitrage | exchange WI listings | WI symbols in Alpaca's list: [U, not measured] | [U] | as B1 | [U] | days | high | EVENTS | new | **PARK** on access until a WI symbol is found tradable | 2·1·0 = 0 |
| B3 | Holdco stub: parent worth less than its listed stake. Loser: holders of the parent who ignore the stub | 13D/13G; no free holdings history | Short the subsidiary leg if ETB [U] | [U] | 82 situations in MPS 2002's sample [S]; no dated catalyst; in 30% the link was severed first [S] | path risk: returns would be 50% larger with smooth convergence [S] | months | specialist | EVENTS | **the CEF-discount well**: a structural discount with no dated exit (graveyard pattern 1's sibling) | **PARK**, D7 | 1·2·1 = 2 |
| B4 | Tracking-stock eliminations | 8-K/proxy | — | — | a handful in 15 years [U] | — | — | — | — | — | **D7** | 0 |

### C. Share classes

| id | mechanism, and who is on the other side | event source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **C1** | **Dual-class spread** on equal cash-flow rights. Gaps are created by the **more liquid class** (liquidity-demanding traders), and one-sided trades, not long-short arbitrage, close most of them (Schultz–Shive 2010 [V abstract]). Loser: the impatient trader in the liquid line | continuous; closing auctions on both lines | **42 permcos** with ≥ 2 listed common lines at 2024-12-31 [V]; at Alpaca **25 have both lines shortable and ETB** today [V] | thinner line, 2022H2: 61 / 46 / 22% (n 41) [V]; median $208k | 41–48 pairs every year-end 2010–24 [V]; continuous | "a simple trading strategy exploiting gaps ... **appears to create abnormal profits after transactions costs**" [V]; no magnitude in the abstract | days | high in mega-caps (GOOG/GOOGL), low in thin pairs | **needs a ruling**: no event, and the XASSET slate is closed | **neighbour of `pair-reversion`** (D2: costs do not diversify) **and E1** (edge survived, opportunities collapsed). **Stale-price trap**: a thin line's close can be stale; use auction prints and drop no-trade days | **G-C1:** on 2010–22 CRSP closes, per pair, σ of the daily change in the log price ratio (dividend-adjusted) and the AR(1) half-life, against two legs × the 5/15/30bp grid. Control: random same-industry pairs. **< 10 of the 25 clear, or the control reverts as fast: kill** | 3·1·3 = **9** |
| C2 | Dual-class unifications (with or without a premium to the high-vote class) | proxy (DEF 14A) | — | — | [U], a few a year | [U] | months | — | EVENTS | new | **D7** [U] | 0·1·2 = 0 |

### D. Rights offerings

| id | mechanism, and who is on the other side | event source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 | CEF rights: the premium turns into a discount over the offering; worse with affiliated soliciting dealers (KWZ 2002, 120 offerings 1988–98 [V abstract]). Negative returns during the offer with a weak rebound (Lin 2000 [S]). Loser: holders who neither subscribe nor sell | N-2/424B; the CRSP rights record | Short the CEF where shortable; **Reg M Rule 105** check (pod N9) | 98 / 72 / 7% (n 46) [V] | **CRSP CEF rights 2010–24: 100** (6.7/yr; mo 4.7/yr) [V]. Plan 2d's "count post-2010 first; below about 100 it is D7" lands **exactly at the line** | as cited | the subscription period | specialist | EVENTS | **covered: plan 2d** (the count is supplied here) | 2d's own gate | (1·2·2 = 4) |
| D2 | Transferable rights in operating companies: rights sell below intrinsic when holders do not participate. Participation averages only 64%, and nonparticipants transfer about 7% of the offering (Holderness–Pontiff 2016 [V]) | 424B / S-3; Alpaca `rights_distribution` | `*.RT` tradable [V]. Exercising costs $100. Of 2025's rights issuers, 15 of the 30 still active are shortable [V] | 83 / 61 / 26% (n 23) [V] | CRSP common-stock rights 8.0/yr (2010–24) [V]; Alpaca 20 (2024), 36 (2025) [V] | 7% of the offering moves across holders [V]; the per-trade edge is [U] | 1–3 weeks | low | EVENTS | new | **PARK**: D7-ish, and exercise needs an election | 1·2·1 = 2 |

### E. Dividends and ex-dates

| id | mechanism, and who is on the other side | event source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **E1** | **Special-dividend ex-day wedge.** The ex-day drop is consistent with taxes on the marginal holder (Elton–Gruber–Blake 2005, taxable vs non-taxable CEFs [S]). For distributions **≥ 25% of value the ex-date is the business day after the payable date** (FINRA 11140(b)(2) [V, 2000 notice]), with due bills: a known source of vendor errors (C4 found yfinance mis-scaling distributions [V, trial-c4]). Loser: holders on the wrong side of the tax wedge, if the desk is tax-advantaged relative to them [U] | the declaration (8-K or press release); Alpaca `cash_dividend` with `special` | Long cum, sell ex, short the sector ETF. **Paper credits no dividends** [V], so score it on the third P&L line (0.4). The desk's tax status is **a counsel question** (pod §7.5) | common stock: 92 / 74 / 44% (n 749) [V] | CRSP specials: **common 191.9/yr** (2015–24; iss 144.6; every month); **CEF 61.7/yr** [V]. Alpaca `special` flag against CRSP SD rows (all types): 452 vs 415 (2023), 341 vs 390 (2024); the sources agree within about 13% [V] | the drop-ratio wedge [U] | 2 sessions | moderate | EVENTS | **CORE-a CLOSED**: around CEF specials the deployed z reads funds rich and is right, so **restrict E1 to common stock** | **G-E1:** the CRSP 2010–22 median ex-day drop ratio on specials with ADV ≥ $1m, with a CI. **≥ 0.95: kill.** One number | 3·1·1 = **3** |
| E2 | The CEF ex-date window inside the live book. The caller says C4's review found about a third of C4's P&L in the ex-date window [U: **not found** in `results/cef/C4_RESULT_2026-10-14.md` at trial-c4 a8d7807]. W4 found no material ex-date artifact in the deployed IC [V, CLOSED table] | CEF distribution calendar | — | — | monthly × names | — | — | — | CEF | **covered**: the "ex-cycle freeze", an open proposal in `results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md` | route there; reconcile the C4 claim first | (CEF) |
| E3 | **Record-date borrow recall in muni-CEF shorts.** Speculative [U]: a payment in lieu of an exempt-interest dividend is not exempt to the lender (fund filings [S]), so lenders of muni CEFs have a monthly reason to recall before record dates. Loser: our shorts (recall and buy-in) | our daily probe snapshots | `borrow_status` daily [V] | — | 12 × names a year | risk, not alpha | — | — | none (0 trials) | new; sibling of N7 | Count `borrow_status` flips by days-to-record-date once ≥ 3 months of snapshots exist (`results/ops/alpaca_probe/`) | risk |
| E4 | DRIP purchases on payable dates | — | — | — | — | — | — | — | EVENTS | **covered: B3** | — | — |
| E5 | Managed-distribution policy changes as a signal | — | — | — | — | — | — | — | — | **dead: M7** (failed twice) | do not rebuild | — |

### F. Buybacks

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **F1** | Open-market buyback drift: the firm buys from sellers who under-react. Peyer–Vermaelen (2009) reject that the anomalies have disappeared [S] | 8-K item 8.01 or a press release. **The EDGAR index carries no item numbers**: the submissions API per CIK is needed | long + ETF short: fine | [U] | hundreds [U] | long-horizon drift [S]; loads on value and size by construction [U] | months | high | EVENTS | new | **G-F1:** price the data build (CIK crawl), plus a D4 prior from the published factor loadings. Expected to close | 3·1·1 = **3** |
| F2 | ASR: the bank's hedge purchases support the price; announcement CARs are positive (BKT 2011 [S]; King–Teague [S]) | 8-K | fine | [U] | [U] | [S], magnitude [U] | weeks | — | EVENTS | new | **PARK** | 1·1·1 = 1 |

### G. Splits

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 | Reverse-split drift (short): "statistically significant negative abnormal returns over the three-year period" for > 1,600 firms, which are hard to short (KKR 2008 [V]) | 8-K; Alpaca `reverse_split` | **2025: 727 symbols, 432 still active, 54 shortable** [V] | 82 / 33 / 10% (n 633) [V] | CRSP common **206.4/yr** (2015–24), rising: 448 (2023), 466 (2024) [V] | as cited | months | — | EVENTS | new | **KILL on borrow** (measured) | 3·2·0 = 0 |
| G2 | Odd-lot cash-out via a reverse-then-forward split | proxy / 13E-3 | one account | tiny | [U] | the cash-out premium on < N shares | — | — | — | — | **KILL** (capacity; it needs many accounts) | 0 |
| **G3** | Forward-split drift: 7.93% first-year excess on 1,275 two-for-one splits (IRS 1996 [S]). **No forced loser**: it is under-reaction. Fractional shares (about 2019–20 onward) remove the price-level motive [U] | the split announcement (8-K / press) | liquid; ETB likely | 96 / 83 / 70% (n 84) [V] | CRSP ≥ 2:1 common **22.6/yr** (2015–24; mo 9.7) [V]; 2020–22: 13 + 28 + 24 = 65 [V] | 7.93% (1975–90 sample) [S] | months | high | EVENTS | new | **G-G3:** the regime count (65 in 2020–22) and a D4 prior. A pre-registration must state that no loser is named | 2·1·3 = **6** |

### H. Going private, squeeze-outs, appraisal

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | Controller freeze-out bumps: minority holders receive more than their pro-rata share of surplus, and bids are renegotiated (BLL 2006 [S]). Loser: the controller | EDGAR SC 13E3 | long target + sector short | [U] | SC 13E3 non-fund **42.2/yr** (2016–25) [V], an upper bound (includes go-dark reverse splits) | [S] | months | specialist | EVENTS | **covered: `ss-merger-arb`**; general merger arb is PARK (a short put) | hand over | (2·2·2 = 8) |
| H2 | Appraisal arbitrage. Since 2016, DGCL §262(g) dismisses listed-share appraisals below 1% or $1m unless short-form [S] | proxy | needs a record-holder demand and a multi-year lock-up; no Alpaca route [U] | — | — | — | years | — | — | — | **KILL on access** | 0 |

### I. Index events

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| I1 | S&P 500 adds and deletes | S&P press, after the close | ETB | high | ~20–30 [U] | additions 7.6% (1990s) → **0.8%** in the last decade; deletions **−0.6%** (2010–20) [V, NBER w30748]. A secondary summary says 7.4% and 0.1% [S]; NBER is used | 1–5 sessions | extreme | EVENTS | new | **KILL**: the effect is about gone and is announced after the close, so we fill a session late | 2·0·3 = 0 |
| I2 | Russell reconstitution, **now semi-annual**: December 2026 rank day 30 Oct, preliminary lists 13 Nov, lockdown 30 Nov, effective after the close on **11 Dec 2026**; "reviews held in June and December" [V] | FTSE Russell | ETB | high | **2 dates/yr**, so independent groups = 2 | [U] | days | extreme | — | new; **a regime change** (the first December recon in decades) that a rolling estimator could read as signal | **D7 as a sleeve; keep as a risk calendar.** Whether any of our CEFs is Russell-eligible is [U] | 0 |
| I3 | Fund-of-CEF index reconstitution (PCEF, YYY, CEFS) | N-PORT | **PCEF not shortable; CEFS and YYY ETB** [V] | — | [U] | — | — | — | NPORT | **covered: B2** | — | — |
| I4 | ETF creation/redemption flows | — | — | — | — | — | — | — | — | **dead: `raw-flow-z`** (D1); continuous form queued as N4 | — | — |

### J. Fund and vehicle structure

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| J1 | ETF liquidation at NAV: buy below NAV, receive cash. Loser: holders who sell into a thin book | issuer notice; CRSP delisting (GLI) | mandatory action [U] | **31 / 6 / 1%** (n 561); median **$36.7k** [V] | CRSP ETF liquidations **124.8/yr** (2015–24), 217 (2023), 165 (2024) [V] | at most the spread [U] | 2–6 weeks | — | EVENTS | new | **KILL on capacity (measured)** | 3·1·0 = 0 |
| J2 | Interval and tender-offer funds (quarterly NAV repurchases) | EDGAR N-23C3A | **not exchange-traded: no Alpaca route** | — | N-23C3A filers: **16 (2010) → 140 (2025)** [V]; fund SC TO-I 401/yr (2016–25) [V] | — | — | — | — | — | **KILL on access**; note the growth (it competes for the same retail credit buyer) | 0 |
| J3 | Non-traded REIT/BDC listings: long-locked holders sell after listing. Pre-listing returns of 6.3%/yr against 11.6% for traded REITs (HMM [S]) | 8-A12B, S-11 | HTB at listing [U] | [U] | S-11 21.6/yr (2016–25) [V] counts registrations, not listings; listings a few a year [U] | [U] | weeks | low | EVENTS | new | **D7** [U] | 0·1·1 = 0 |
| J4 | BDC NAV events (co-held loan marks; BDC discount z) | 10-Q | — | — | — | — | — | — | — | **PARK / TEST after a data build** (SCALING §7.1 rows 6, 11) | — | — |
| J5 | CEF IPO lifecycle | — | — | — | — | — | — | — | — | **covered: E4 (G7)** | — | — |
| J6 | Term-CEF pull-to-par | — | — | — | — | — | — | — | — | **PARK (2c, D7)** | — | — |
| J7 | CEF open-ending, liquidation, conversion; CRSP CEF liquidations 7.1/yr, mergers 17.9/yr (2015–24) [V] | — | — | — | — | — | — | — | — | **covered: `ss-cef-events`** | — | — |
| J8 | ETN issuance suspension: the premium collapses when issuance resumes or the note is called. Loser: buyers at the premium | issuer notice | ETNs at a premium are usually HTB [U] | [U] | a handful a year [U] | [U] | weeks | — | EVENTS | new | **D7** [U] | 0 |
| **J9** | **Leveraged-ETF close rebalancing.** A daily-reset L× fund must trade L(L−1)·r·AUM at the close (a derivation, not a fetched figure). LETF rebalancing induces end-of-day momentum that "quickly revert[s] at the next day's open" (Barbon et al. [S]). **Loser: the LETF's holders**, who pay the impact. **We sell MOC into up-day demand and buy back at the next close** | daily; computable by the close from the day's return and published AUM | SPY, QQQ, IWM ETB [V]; MOC-compatible (rule 3) | high | every large-move day; independent groups = days (dozens a year) [U] | [S], magnitude [U] | 1 session | high (liquidity providers) | **needs a ruling** (not an event; XASSET closed) | neighbour of X2 (D1) and X3 (D4), the calendar flows; C5 (the open fill) died as session drift, so **declare the session-drift control in advance** | **G-J9:** predicted demand from CRSP LETF shares outstanding (pre-2023) against the underlying's close volume. **< 1% on 95% of days: kill** | 3·1·2 = **6** |

### K. Listings, names, IPO and offering lifecycle

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| K1 | OTC → exchange uplisting: index and institutional eligibility | EDGAR 8-A12B by existing reporters [U] | **pre-uplisting leg mostly OTC: 308 of 1,163 tradable** [V] | [U] | [U] | [U] | weeks | — | EVENTS | new | **PARK** (data and access) | 1·1·1 = 1 |
| K2 | Delisting to OTC: forced institutional and index selling; spreads about triple and volatility doubles after delisting (MOP 2008 [S]) | EDGAR 25-NSE; CRSP GDR | short before: usually HTB; after: OTC | — | CRSP common stock dropped **116.5/yr** (2015–24), 211 (2023), 298 (2024) [V] | [S] | — | — | — | new | **KILL on access** | 0 |
| K3 | Name and ticker changes; ticker confusion (Rashes 2001: deviations reverse within days [S]) | Alpaca `name_change` 670 (2025) [V] | micro-caps, HTB | — | — | no forced flow | — | — | — | new | **KILL** (no loser at scale) | 0 |
| K4 | Post-bankruptcy equity: creditors handed equity they cannot hold. Large positive excess returns in the 200 days after emergence (EAA 1999 [S]); a 2021 re-examination exists [S] | 8-K / plan; often OTC first | mixed | [U] | [U] | [S] | months | specialist | EVENTS | new; **overlaps half 2** (`ss-catalogue-credit`) | route to half 2 | 1·2·1 = 2 |
| **K5** | **IPO lock-up expiry:** a contractual release of insider supply on a date known from the prospectus. 3-day AR about −1.5% and volume +40% (Field–Hanka 2001, 1,948 lock-ups 1988–97 [S]). Loser: holders through the date | 424B4 lock-up terms (EDGAR) | **the short leg is the question**: recent IPOs are often HTB [U] | [U] | 424B4 by non-funds 541.6/yr (2016–25) [V], which includes follow-ons; IPOs alone [U] | −1.5% over 3 days [S], 1988–97 | 3–5 sessions | high | EVENTS | new | **G-K5:** today's Alpaca shortable/ETB share of 2025 IPOs near day 180. **Under half: kill** | 3·2·1 = **6** |
| **K6** | **SEO reversal.** Non-overnight issuers fall 2.5% before issue and recover within 7 sessions. But **75% of 2009–14 SEOs were overnight** (27% in 2000–08), and their post-issue returns are "less positive" and unrelated to size (Gustafson 2018 [V]). Offer discount averages 2.2% (Corwin 2003 [S]). Loser: the issuer and selling holders | 424B2/B4/B5/B7 filing time (EDGAR); "overnight" read from the filing timestamp | long issuer + SPY/sector short, ETB [V] | [U] | hundreds [U] | per the abstract; **E2's convert analogue decayed to +0.17% (t 0.3) in 2020–22** [V, repo] | 1–7 sessions | moderate | EVENTS | **E2's sibling**: E2's windows are already looked at; do not call 2011–22 out of sample | **G-K6:** count non-overnight SEOs per year after 2014. **< 30/yr: fold into E2 as a footnote** | 3·1·3 = **9** |

### L. Preferreds and convertibles

| id | mechanism, and who is on the other side | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | Preferred calls; shorting preferreds above their call price (negative yield-to-call). Loser: yield-screening retail | Alpaca `partial_call`: 58 (2026 YTD) [V] | 69 of 626 preferreds shortable (SCALING row 9) [S] | — | — | [U] | — | — | — | **PARK** (listed capital stack: CRSP holds no preferreds) | — | — |
| L2 | Forced-conversion convertible calls: the common falls at the call (Mikkelson 1981 [S, via the 1985 chapter]) | 8-K / press | ETB likely | [U] | [U] | [S] | days | — | EVENTS | new; an E2 sibling | **PARK** (dates need text) | 1·1·2 = 2 |
| L3 | Listed mandatory convertibles | — | — | — | — | — | — | — | — | **covered: E3 (G4)** | — | — |

### M. Trusts and liquidations

| id | mechanism | source | Alpaca | cap | evts/yr | edge | hold | crowding | counter | graveyard | gate / verdict | E·S·F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | Royalty-trust termination: the trustee sells the royalty and units converge to the sale value | 8-K | small, HTB [U] | [U] | a few a year [U] | [U] | months | — | EVENTS | new | **D7** | 0 |
| M2 | Partial liquidations and liquidating trusts | CRSP | — | 100 / 67 / 22% (n 9) [V] | CRSP common stock **1.7/yr** (2015–24) [V] | terms-implied | months | — | EVENTS | new | **D7** (measured) | 0 |

### N. Other structural flows

| id | mechanism | source | Alpaca | evts/yr | verdict | E·S·F |
|---|---|---|---|---|---|---|
| N1 | Redomicile changing index eligibility | proxy | ETB | a few [U] | **D7** | 0 |
| N2 | Proxy record-date vote recalls raise borrow | proxy record dates | `borrow_status` | [U] | **risk input** with E3 | risk |
| N3 | Chapter 11 equity ("Q" names) and worthless removals: short the residual retail bid | Alpaca `worthless_removal` 131 (2024), 146 (2025) [V] | OTC or not shortable | — | **KILL on access** | 0 |

---

## 4. Ranking (open candidates only)

| rank | id | E | S | F | score | information per trial |
|---:|---|---:|---:|---:|---:|---|
| 1 | B1 spin-off index-removal sale | 2 | 2 | 3 | 12 | a count from free notices; can close at zero trials |
| 2 | C1 dual-class spread | 3 | 1 | 3 | 9 | a dispersion-vs-cost count; decisive at zero trials |
| 3 | K6 SEO reversal | 3 | 1 | 3 | 9 | a composition count; leans on E2's pre-registration |
| 4 | J9 LETF close rebalancing | 3 | 1 | 2 | 6 | a demand-vs-volume ratio; zero trials |
| 5 | K5 IPO lock-up expiry | 3 | 2 | 1 | 6 | one day of shortability reads |
| 6 | G3 forward-split drift | 2 | 1 | 3 | 6 | a count plus a D4 prior; no named loser |
| 7 | E1 special-dividend ex-day | 3 | 1 | 1 | 3 | one drop-ratio number |
| 8 | F1 buyback drift | 3 | 1 | 1 | 3 | a data-cost estimate plus a D4 prior |
| — | B3 holdco stub, D2 operating-company rights, K4 post-bankruptcy equity, L2 convertible calls | | | | 2 each | PARK |
| — | F2 ASR, K1 uplisting | | | | 1 each | PARK |

**A labelled caution on the scores.** E, S and F are coarse judgements. S is the
weakest axis: several cells rest on 1970s–90s samples or search summaries [S]. The
point of the gates is to replace S with a fetched number before any trial is spent.

**What would make the top three uninteresting.**
- **B1:** fewer than 30 day-one removals since 2015. Or the removal close showing no
  pressure, because liquidity providers pre-position on the announced date.
- **C1:** the random-pair control reverting as fast as the dual-class pairs. That is
  pair-reversion's lesson, repeated.
- **K6:** the overnight share near 100% after 2014. Then the effect Gustafson finds
  lives only in a vanishing subsample.

---

## 5. Cross-source disagreements (reported, not averaged)

1. **Spin-offs, 2024.** CRSP shows **10** common-stock spin-offs. Alpaca returns
   **48** `spin_off` rows. Read row by row, Alpaca's type also carries CVR and
   warrant distributions (8 rows) and backfilled events (14 rows with ex-dates in
   2021–22). After those filters it is **28**, of which 22 have a source listed today
   [V]. For 2023: CRSP 26 against Alpaca's filtered 35 [V].
   - **Used:** CRSP for the 2010–24 rate (20.3/yr), cross-checked by EDGAR 10-12B
     (23.8/yr, 2015–24). The two multi-year rates agree; the single-year gap is open [U].
2. **Greenwood–Sammon.** The NBER abstract reads additions 0.8% and deletions −0.6%
   [V]. A secondary summary reads 7.4% and 0.1% [S]. **NBER used.**
3. **Alpaca's corporate-actions history is thin before 2020.** For example, 1 spin-off
   in 2017 and 2 name changes in 2017–18 [V]. **Alpaca is not used for any pre-2020
   rate.**
4. **EDGAR renamed Schedule 13D** to `SCHEDULE 13D` from 2024Q4 [V, index rows]. The
   2025 `SC 13D` column is not comparable.
5. **The FINRA 11140 text is from a 2000 notice** (T+3 era). The ≥ 25% rule was
   repeated in a 2023 issuer release [S]. The < 25% branch's "second business day
   before record" predates T+1 and is superseded in practice [U].

## 6. What is not established

- Every **S** cell is literature or terms, never a backtest. Most rest on old samples.
- **Alpaca's handling of voluntary actions for a Trading-API account**, and whether
  paper simulates any of them [U]. Ask Alpaca support before any election-dependent
  row is reopened.
- **The desk's tax status** (E1) and **firm structure**: counsel (pod §7.5).
- **Spin-off and IPO liquidity of the new security itself**: not measured here (only
  the parent's).
- **E3, the record-date recall**, is a labelled speculation until the probe snapshots
  cover three months.

## 7. Reproduce

```bash
export QUANTT_ENV_FILE=/abs/path/config/.env          # never printed
python3 scripts/events/ss_catalogue_counts.py crsp     # R2 mirror, ~1 min
python3 scripts/events/ss_catalogue_counts.py edgar    # or: --offline --edgar-cache <worktree>/results/events/_cache_edgar
python3 scripts/events/ss_catalogue_counts.py alpaca   # read-only GETs, ~2 min; flags true on the day only
```
