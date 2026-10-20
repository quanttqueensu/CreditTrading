# A1: CEF share issuance at a premium (ATM programmes and shelf offerings), the zero-trial gate — 2026-10-20

**What this is.** The team lead asked on 2026-10-19 for the zero-trial checks on
the new event paths. Path A1: when a closed-end fund trades above NAV, its sponsor
can sell new shares into the premium. It files an N-2 shelf, then prospectus
supplements, often under an at-the-market (ATM) sales agreement. That should cap
or compress the premium. This note answers the five questions in the brief. Each
answer is either measured or marked as a stated gap. It ends with a kill gate
and its verdict.

**Verdict: FAIL.** A1 is not worth a pre-registration as a standalone EVENTS
trial on the data this desk has. It fails on count (D7), it cannot show that the
live z-score is blind to it, and its negative control cannot be formed. Most
premium funds also cannot be shorted at Alpaca today. **One finding outranks the
verdict, and it is about the live book:** 10 of the 13 deployed names have filed
offering supplements since 2020, and two more filed what look like merger
prospectuses (§2.5). PDI, PTY and PCN report large ATM
proceeds in 2025–26. In the fit period, 18.1% of the book's short name-days fell
inside a deployed name's programme episode (§5.4). Whether that helps or hurts
the shorts is **not measured here**: the brief excludes strategy P&L. §7 names
the next zero-trial step.

**Zero trials. EVENTS stays at 2 and CEF at 52.** No return or P&L of any
strategy is computed. Every premium level is dated before 2023-01-01; the
script asserts it. The 2023+ figures are EDGAR filing counts and sponsor-reported
facts, never prices. No level statistic is computed on any `cef_universe.csv`
fund: the 44 are counted only, as in the 2026-10-15 corporate-action census. So
the 27-name set is not consumed. **The one cost:** this note has looked at
2008–22 premium levels around issuance in seven families-panel events, and at
the fit-period book's short name-days by window. Anyone who writes an A1 or
issuance-filter pre-registration has seen those.

**Reproduce.** The script reads cached EDGAR indexes and cached CRSP extracts
directly. It opens no network connection and reads no credential. It never builds
`EdgarClient` (which reads `SEC_USER_AGENT` from the env file) and never calls
`crsp_events` (which reads R2).

```bash
W=".claude/worktrees"    # any worktree whose caches are complete; these were used on 2026-10-20
python3 scripts/events/a1_cef_issuance_gate.py levels \
  --edgar-cache "$W/ss-cef-events/results/events/_cache_edgar" \
  --crsp-cache "$W/research-ss-expansion/results/events/_cache_crsp" "$W/ss-cef-events/results/events/_cache_crsp" \
               "$W/research-cef-events/results/events/_cache_crsp" "$W/ss-e1-hedge/results/events/_cache_crsp" \
               "$W/trial-events-e1/results/events/_cache_crsp" "$W/research-edgar/results/events/_cache_crsp"
python3 scripts/events/a1_cef_issuance_gate.py sample ...   # same arguments: the seeded draw of §3 (to _cache_a1/)
python3 -m pytest scripts/events/tests/test_a1_cef_issuance_gate.py
```

`levels` runs the census first. Outputs:

- `results/events/a1/a1_census_2026-10-20.json` and `a1_levels_2026-10-20.json`:
  aggregates only, with no permno and no CRSP row, because CRSP is licensed and
  this repository is public;
- `a1_edgar_episodes.csv`: EDGAR facts only; a test pins its columns;
- `a1_validation_sample_2026-10-20.csv`: the hand-read sample;
- `results/events/a1/_cache_a1/` (gitignored): every row that joins CRSP.

**Order of work, for the record.** The census, the event definitions and the five
gates were committed (`5c31340`) before any premium level was computed. Two
revisions followed, each recorded in the script with its reason:

1. **Revision 1**, after the hand-read sample and before any level (§3).
2. **Revision 2**, after the first levels run. It is a data guard for vendor NAV
   basis breaks, and it changes no gate's outcome (§4.1).

**Data and as-of dates.**

| input | coverage |
|---|---|
| EDGAR quarterly `master.gz`, 76 quarters (cached in `ss-cef-events`) | 2008-Q1 → 2026-Q4; last filing seen **2026-10-16** |
| SEC ticker file (CIK → ticker today) | fetched 2026-10-13T22:30Z |
| CRSP `dsf` (prc, vol, shrout, cfacpr), unioned from 12 cached extracts; `dsenames`, `dsedelist`, `dsedist` | daily rows to **2022-12-30**; names to 2024-12-31. 847 share-code 14/44 permnos with rows from 2008. Overlapping rows agree (the script raises otherwise) |
| CEF-families panel: CRSP close and vendor NAV (`data/cef_families/`) | panel to 2026-10-09; **used to 2022-12-30** |
| Alpaca `GET /v2/assets` (all active US equities, cef paper key) | `data/cef_families/raw/alpaca_assets_active_2026-10-12.json`, read 2026-10-12T18:27Z; true on that date only |
| Committed Alpaca probe, the deployed 13 | `results/ops/alpaca_probe/2026-10-15_cef.json`, 2026-10-15T20:01Z |
| CEFConnect daily pricing (premium today) | `data/cef_families/raw/cefconnect_dailypricing_2026-10-12.json`, as of 2026-10-09 |
| IBKR borrow fees (FEE_RATE bars) | `data/cef/cef_borrow_history.parquet`, 2021-09-13 → 2026-09-09; **used to 2022-12-30** |
| Cached EDGAR filing texts (other worktrees' `_cache_edgar`) | read locally; accessions in `docs/REFERENCES.md` §12av |

**Labels.** [V] means re-run by this note's script or read in the cited document.
[S] means sourced but not re-read. [U] means unknown. Sources are in
`docs/REFERENCES.md` §12av.

---

## 0. The answer

| question | answer |
|---|---|
| 1. Who loses, and is it dead already? | The buyer of the marginal share at a premium. That is mostly retail, buying on the distribution rate; only the sponsor can create shares. The literature finds issuers are funds with high premiums, with negative announcement and three-year returns; one paper reads it as managers timing issues to exploit mean reversion [V abstracts, paraphrased]. **That is M1 again**: in the level sample the median issuer sits at **live z +2.02** on the event date, so the core book already reads it as a short. A1 is new only if issuance changes the path *given* z. That comparison cannot be formed on this data (§4). Rights offerings (2d/N9) and K6 are different mechanisms, but rights offerings contaminate any naive count (§3) |
| 2. How many? | **33 programme events** (31 funds), 2008–22: listed registered CEFs, CRSP-confirmed, at least 4 supplements. The broad set has 78 events in 60 funds; 4 of 15 hand-read confirmed episodes were rights offerings. There are 1–8 programme events a year (§2.3). Of the 44, programme events touch DHY, EFR, EFT and PDI; of the deployed 13, PDI only. 12 are in the families panel and 17 are outside both NAV panels. The CRSP-only method finds 372 beyond-DRIP issuance quarters in 156 funds; 251 of them (84 funds) are EDGAR-confirmed |
| 3. Mechanism at zero trials | 7 programme events have a full premium path. The premium is **+10.87% at the event** (IQR 6.49–12.26), up from +4.60% 63 sessions before, and **+2.96% 21 sessions after**. 6 of 7 are lower at +63. **No event has three premium- and z-matched controls**, so the issuance-beyond-z difference is unmeasured, and the placebo has nothing to compare against. **D7** |
| 4. Feasibility | **Shortable at Alpaca:** 15 of the 25 programme funds still listed (2026-10-12); **8 of the 25 CEFs at a premium today**; 12 of the 13 deployed (2026-10-15, MHD not). **Borrow in deployed programme windows, 2021-09 → 2022-12:** median 11.6–44.7%/yr (IBKR). **Capacity:** median event-fund ADV $2.48m; 28.6% clear the spec's ADV filter. **Counter:** a standalone sleeve is EVENTS; an issuance-aware filter on the live book's shorts is CEF |
| 5. Gate | **FAIL**: G-A1-1 (D7), G-A1-3 (not computable), G-A1-4 (no comparison) fail. G-A1-2 (identity 7 of 7 at a premium) and G-A1-5 (60% shortable) pass (§6) |

---

## 1. Mechanism, the loser, and the graveyard (question 1)

**The mechanism.**

- **The legal floor.** Section 23(b) of the 1940 Act bars a registered closed-end
  fund from selling its common shares below current NAV, exclusive of
  commissions and measured within 48 hours of the sale. The exceptions are
  offerings to existing holders (rights offerings), majority-holder consent,
  conversions, certain warrants and SEC permission [V, 15 U.S.C. 80a-23(b)].
  Nuveen's JFR describes its programme as selling "at a net price at or above the
  Fund's NAV per common share" [V, N-CSR 2026-10-06].
- **What an ATM is.** It sells new shares into the exchange through an agent, in
  transactions "deemed to be 'at the market' as defined in Rule 415", from time
  to time [V, the ATM covers read in §3].
- **What follows for the bar's point 2.** An ATM is a **one-sided authorised
  participant**: creation only, only above NAV, at the sponsor's discretion.
  `docs/BRIEF.md` §2 and the frozen spec rest the book on "a fixed share count
  and no authorised participants". For a fund running an ATM, that holds on the
  discount side and fails on the premium side.
- **Where the AP mechanism killed the trade in ETFs**, the creation was two-sided
  and arbitraged to the tick. Here it is one-sided, discretionary and slow. ATM
  sales are a fraction of ADV, and the sponsor stops when the premium falls below
  costs. So it can compress a premium, but it cannot pin it. It also cannot touch
  a discount at all.
- **DRIPs issue at a premium too.** When the price is at or above NAV, plans issue
  new shares at "the greater of (i) NAV per common share on that date or (ii) 95%
  of the market price" [V, two cached N-14 8C plan descriptions]. That is a slow,
  automatic version of the same thing, and §2.1 bounds it out.

**Who loses, and why they persist.**

- **The loser is the buyer of the marginal share.** That share is newly created at
  a premium to NAV; the premium is what the buyer pays for NAV. It is the retail
  income buyer of M1, who screens on distribution rate. Only the sponsor can
  create shares, so the buyer has no arbitrage of their own.
- **The sponsor's incentive is assets.**
  - Guggenheim's board was told the ATM programmes "benefitted the Funds by
    allowing the issuance of shares above NAV, leading to NAV accretion" [V, GOF
    N-14 8C 2021].
  - Mexico Fund's adviser noted that issuance at a premium under its Equity Shelf
    Program raises its performance-adjusted fee [V, DEF 14A 2014].
  - Tortoise waived six months of fees on ATM proceeds [V, DEF 14A 2012].
  - Nuveen's distributor earned $882,933 on JFR's at-the-market offerings in one
    fiscal year [V, PRE 14A 2014].
- **The literature agrees on direction** (abstracts only; full texts not read):
  - **Akhigbe & Madura (2001), seasoned public and rights offerings by CEFs.** Funds are
    more likely to offer when at a relatively high premium and liquid. The
    valuation effect is significantly negative on average, and negative over the
    three years after.
  - **Higgins, Howton & Howton (2003).** Announcement returns are negative and
    significant, but smaller than for industrial SEOs. Issuers had higher
    pre-issue returns and premiums, and lower three-year returns, than
    non-issuers. The authors read this as managers timing their issues to exploit
    mean reversion in fund returns (the fetch tool's paraphrase of the abstract).

  Neither abstract mentions at-the-market programmes, and neither sample period
  was read [U].

**The graveyard check.**

| neighbour | how A1 differs, or why it does not |
|---|---|
| **M1, the live discount z-score** | **This is the binding problem.** Issuers issue when rich: the level sample's median live z on the event date is +2.02 (n 7, §4). The core book shorts exactly that. Timing issues to exploit mean reversion is M1 seen from the sponsor's side. A1 adds information only if issuance moves the path beyond what the premium and z already predict. That needs a z-matched control, and §4 could form none. **Until it is formed, A1 is at best a re-parameterisation of M1** (the bar's point 3) |
| **Rights offerings (plan 2d, pod N9)** | A different instrument: shares offered to existing holders below the market, often below NAV, through a subscription period. It is excluded here by CRSP 45xx and by the programme rule. **But CRSP does not code them all**: 4 of 15 hand-read "issuance" events were rights offerings (§3) |
| **K6, the SEO reversal** (corporate catalogue) | K6 is the overnight, discounted, underwritten offering of an operating company, with a dated price-pressure reversal. An ATM has no offer discount and no single date; it sells into the market over months. The *announcement-day* variant of A1 (short at the first supplement) is K6's and E2's sibling. It would be judged like E2, whose convertible analogue decayed to +0.17% (t 0.3) in 2020–22 [S, the corporate catalogue's K6 row] |
| **E4, the CEF IPO lifecycle** | The IPO is the extreme case of issuance at a premium, with the sales load. A1 is its seasoned analogue; the same buyers lose |
| **Graveyard pattern 1: price minus a stale mark** | The premium that triggers issuance is price minus NAV, and a credit fund's NAV can be stale (M2). A premium spike the sponsor sells into could partly be NAV catching up. The z-matched control was the defence, and it is missing. **Treat the §4 path as possibly stale-price-contaminated** |
| **Graveyard pattern 2: a control that scores as well** | Named before the levels: same-date, premium- and z-matched non-issuers (H12), plus a placebo on the same fund a year earlier. Neither could be formed at the needed size |

---

## 2. Counts (question 2)

### 2.1 Two methods, one join

The method is in the script's docstring; it is summarised here.

- **E (EDGAR).** Every listed registered CEF and its offering filings from the
  quarterly indexes. Shelf forms are N-2, N-2/A, N-2ASR, N-2 POSASR, N-2MEF and
  POS 8C. Supplements are 424B1–B8 and, before the 2020 reform, Rule 497. A
  listed registered CEF is a CRSP share-code 14/44 permno linked to a CIK that
  files N-CSR and is not a BDC.
  - Supplements group into episodes, split by a silence of more than 365 days.
  - The IPO year is dropped.
- **C (CRSP).** A seasoned quarter whose raw `shrout` rose at least 2%, with:
  - no split, no CRSP merger into the fund, and no 45xx rights distribution near it;
  - growth **beyond what a DRIP could produce**: four-quarter growth above the
    four-quarter distribution yield ÷ 0.95. That is the 100%-participation
    ceiling from the plan terms in §1.
- **The join.** An E episode is *confirmed* if a C quarter falls in its first five
  quarters. It is *rights* if a CRSP 45xx ex-date lies within 120 days.
- **Revision 1 (§3)** adds "registered at the time" and the programme rule.

| fund set (CRSP 14/44 permnos with rows from 2008) | n |
|---|---:|
| all | 847 |
| registered CEFs (N-CSR filers, not BDCs) | **751** (749 CIKs) |
| BDCs (N-54A, or 10-K/10-Q without N-CSR) | 58 |
| N-CSR and BDC forms both (converted; excluded) | 4 |
| not linked to a CIK (excluded) | 34 |
| linked by today's ticker / by name | 382 / 431 |

### 2.2 EDGAR episodes (listed registered CEFs)

| | n |
|---|---:|
| supplements 2008-01 → 2026-10-16 (IPO year included) | 3,782 |
| dropped as the IPO's | 297 |
| episodes, all years | 709 |
| episodes dated before 2023 | **516**: confirmed 80, rights 58, unconfirmed 350, window runs past CRSP 28 |
| episodes 2023 → 2026-10-16 (count only) | 33 / 46 / 53 / 61 |
| pre-2023 episodes left-censored (start in 2008) | 13 |

The 2020 offering reform (effective 2020-08-01 [V]) shows in the forms. Rule 497
carried almost every supplement to 2019 (37–213 a year; two under 424B in 2019).
424B carried 82 in 2020 and 300–349 a year in 2021–22, while 497 fell to 11 in
2022 [V, `supplements_by_year_rule`]. That the reform moved CEF supplements from
Rule 497 to Rule 424 is read off these counts; the release's text was not read
[U].

**"Unconfirmed" is mostly not A1**, but not all of it.

- It holds preferred-share and note offerings, unused shelves, merger
  prospectuses (after 2020 a merger's final prospectus is a 424B3) and rights
  offerings that CRSP did not code.
- It also holds real ATMs that the 100%-participation DRIP ceiling hides. The
  ceiling is generous, so a modest ATM in a high-yield fund stays under it.
  PTY's 2018–20 and PFN's 2018–22 episodes (9 and 15 supplements) are examples:
  unconfirmed here, yet clearly programmes.
- **Recall is therefore below 100%** and is not measured [U].

### 2.3 A1 events by year, 2008–22

| year | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|
| **programme** (≥ 4 supplements; primary) | 1 | 8 | 1 | 2 | 3 | 4 | 1 | 1 | 1 | 2 | 1 | 5 | 1 | 1 | 1 | **33** (31 funds, 33 sponsor-month groups) |
| broad (confirmed, registered at the time) | 2 | 16 | 4 | 6 | 6 | 11 | 1 | 2 | 4 | 7 | 2 | 5 | 2 | 8 | 2 | 78 (60 funds, 73 groups) |
| C quarters, beyond DRIP (CRSP only) | 24 | 19 | 33 | 19 | 22 | 35 | 21 | 12 | 11 | 22 | 28 | 23 | 40 | 35 | 28 | 372 (156 funds) |
| of which EDGAR-confirmed | 3 | 10 | 24 | 12 | 14 | 28 | 13 | 5 | 4 | 13 | 20 | 17 | 33 | 33 | 22 | 251 (84 funds) |

Why 372 C quarters and 251 confirmed ones sit beside only 33 programme events:

- one programme spans many C quarters (GOF's runs 2012–22);
- C counts quarters, not decisions.

The C → EDGAR confirmation rate (251 of 372, 67%) is the cross-check between the
two methods. The unconfirmed quarters are led by internally managed equity funds
with no offering filings: Adams Express, Adams Natural Resources, Eagle Capital
Growth and Central Securities. Year-end distributions paid in new shares would
explain them [U, not read].

### 2.4 Membership

| set | programme events (funds) | broad events (funds) |
|---|---|---|
| `cef_universe.csv` (the 44; counted only) | 4 (DHY, EFR, EFT, PDI) | 10 (DHY, EFR, EFT, HYT, JFR, MSD, NEA, PDI, PTY) |
| deployed 13 | 1 (PDI, 2019-11) | 5 (HYT 2013, JFR 2013, PDI 2017 and 2019, PTY 2017) |
| families panel (has NAV; the level sample) | 12 (11 funds) | 29 (19 funds) |
| outside both panels: **no NAV in this repository** | 17. Still listed: ECC, GBAB, GOF, HERZ, NDMO, NMI, NMZ, OCCI, OXLC, XFLT | 39 |

### 2.5 The deployed names since 2020 (EDGAR facts; 2023+ is a count only)

**Supplement episodes from 2020 exist for 12 of the 13 deployed names.**

| name | episodes from 2020: first → last (supplements) |
|---|---|
| PCN | 2020-12-03 → 2024-08-20 (10); 2025-12-17 → 2026-06-24 (4) |
| HYT | 2022-02-10 → 2026-01-05 (13) |
| PHK | 2022-06-01 → 2025-04-15 (6); 2026-06-24 (1) |
| PTY | 2022-03-30 (1); 2023-09-26 → 2025-06-06 (5); 2026-06-24 → 2026-09-25 (3) |
| PDI | 2023-09-29 (1); 2024-12-20 → 2026-09-25 (3); its 2019-11-08 → 2022-06-23 programme (12) is in §2.3 |
| BIT | 2022-05-03 → 2023-01-03 (3); 2024-12-23 → 2026-04-08 (5) |
| DSL | 2020-09-30 → 2021-04-27 (2); 2023 (3); 2026 (2) |
| JFR | 2023-03-31 (1); 2025-01-10 → 2025-02-11 (2) |
| PFN | its 2018-09-10 → 2024-08-20 episode (15); 2026-06-24 (1) |
| PDO | 2023-02-09 (1); 2025-12-18 (1) |
| MHD, MQY | 2020-11-03 and 2025-09 single 424B3s: probably merger prospectuses, not offerings [U] |
| AWF | none |

The sponsors' own reports confirm that the programmes are large and current [V,
cached N-CSR/N-CSRS]. These are facts the funds report, not prices.

| fund | ATM net proceeds | DRIP issuance, same period |
|---|---|---|
| **PDI** | **$1,354.7m** in the year to 2025-06-30; **$763.3m** in the six months to 2025-12-31 | — |
| **PTY** | $376.1m (year to 2025-06-30); $311.7m (year to 2026-06-30) | $30.8m / $37.7m |
| **PCN** | $114.9m / $98.5m | $9.1m / $10.0m |

- **DSL:** a 2026 distribution agreement for up to $356,829,854 of ATM sales.
- **BIT:** up to 19,000,000 shares.
- **JFR:** an "equity shelf program".

---

## 3. Precision: the hand-read sample, and revision 1

A seeded draw (`SAMPLE_SEED` 20261020) took 15 of the 80 confirmed pre-2023
episodes, before revision 1. Each first supplement's cover was read through
WebFetch on 2026-10-20 (`a1_validation_sample_2026-10-20.csv`, with the decisive
phrase).

| reading | n | ≥ 4 supplements |
|---|---:|---:|
| ATM programme (a sales agreement, "at the market" under Rule 415) | 8 | 5 |
| equity shelf, base prospectus | 1 | 1 |
| shelf base prospectus, method left open (the fund's next episode was a rights offering) | 1 | 0 |
| **rights offering that CRSP had not coded 45xx** (STEW 2008, CLM 2011, ASG 2018, BXSY 2017) | **4** | 0 |
| former fund, by then an operating REIT, in an underwritten offering | 1 | 0 |

**Precision of the broad definition: 9 of 15 (60%)** are ATM or shelf. Every one
of the six episodes with at least four supplements is ATM or shelf, against 3 of
the 9 smaller ones.

**Revision 1**, made before any level was computed:

- the CIK must have filed an N-CSR/N-CSRS within two years before the episode (or
  one after);
- the level check's primary set is the **programme** episodes (≥ 4 supplements);
- the broad set is reported as a sensitivity that rights offerings contaminate.

**The programme label reads the episode's later filings.** It is an ex-post label,
fit for description and not for trading. A tradable rule must classify the first
supplement's cover, ex ante. The covers state "at the market" plainly, so that is
a text rule, not a judgement. Six of six is a small sample: the programme set's
precision is **not established** [U].

---

## 4. The mechanism check: premium levels around events (question 3)

**Design**, fixed before any level (script docstring):

- **Sample.** Families-panel events only: no daily NAV exists outside it except
  for the 44, which are counted only.
- **The event.** τ0 is the first paired session on or after the first supplement.
- **The premium.** `100(P − NAV)/NAV` from the CRSP close and the panel NAV.
  The live z-score is mirrored from `cef_discount.py`: z_window 252 read from the
  spec, `min_periods` 120, `shift(1)`.
- **Controls.** Same-date families funds within 2.5 premium points and 0.5 z,
  clean of any offering episode within a year and of any C quarter within four.
- **The comparison.** D = the event's premium change minus the controls' median
  change.
- **The placebo.** The same fund 252 sessions earlier.

### 4.1 Revision 2: a basis guard (after the first run)

**The defect.** The first run read SRV at −98%, and CRF, CLM and ZTR at −70% to
−77%, against NAV. These are vendor NAVs re-based at reverse splits, set against
CRSP's raw close (`results/cef/CEF_FAMILIES_DATA_2026-10-12.md` §3.2–3.3).

**The guard** drops any pair whose price/NAV lies outside the census's own
`PAIR_RATIO` (0.5, 1.5). That removed 22,422 pairs in 21 funds.

**Its effect on the primary sample:**

| | before the guard | after |
|---|---|---|
| events with a full path | 8 (SRV at −98.4% among them) | 7 |
| share at or above NAV | 0.875 | 1.0 |

**No gate's outcome moved:** no primary event has three controls either way.

### 4.2 Results (primary: programme events in the families panel)

| step | events |
|---|---:|
| programme events in the families panel | 12 |
| no panel / no full path before 2023 | 2 / 3 |
| **with a full premium path** | **7** (6 funds, 7 groups, 2009-02 → 2019-09) |
| **with ≥ 3 matched controls** | **0** (each had 0 or 1) |

| offset (sessions) | −63 | −21 | **0** | +21 | +63 | +126 |
|---|---|---|---|---|---|---|
| median premium, % (n 7) | 4.60 | 5.85 | **10.87** | 2.96 | 2.97 | 3.19 |
| IQR | 0.18–8.59 | 3.46–13.48 | 6.49–12.26 | 0.18–13.28 | 1.34–5.29 | 0.19–3.99 |

**Reading the path:**

- **At the event:** all 7 are at a premium, and the median live z is +2.02.
- **After it:** 6 of 7 are lower at +63. The fund's own premium sd over
  [+1, +126] is 0.773× its sd over [−126, −1] (median).
- **What the path says:** issuance is dated at a premium spike, and the spike goes
  away. **It cannot say why.** A z of +2 predicts reversion on its own; that is
  M1, and the book already trades it. The control that would separate issuance
  from M1 could not be formed: premium funds within 2.5 points and 0.5 z on the
  same day are rare in the equity, preferred and multi-asset panel.
- **Placebo:** n 3, D63 median −197bp. Uninterpretable with no event D.
- **Broad sensitivity** (rights-contaminated): 16 events with a path, 3 with
  controls (D63 median −256bp, n 3). Too few to read.

**Ex-ante power, had the design formed.** The primary set is 33 events in 15
years. Even with NAV for every one, the 30-group bar needs nearly all of them to
find three matched controls, and the families panel found them for none. **D7 on
this data, whatever the true effect.**

---

## 5. Feasibility (question 4)

### 5.1 Shortable at Alpaca

| set | read | active | shortable (and ETB) |
|---|---|---:|---:|
| programme-event funds still listed (25 of 31) | 2026-10-12 | 25 | **15** (60%). Not: ECC, EFT, HERZ, IAF, IIF, MXF, NMI, NMZ, OCCI, TYG |
| broad-event funds still listed (44 of 60) | 2026-10-12 | 43 | 27 (63%) |
| **every CEF at a premium on CEFConnect, 2026-10-09** | 2026-10-12 | 25 of 359 at a premium; 25 active | **8 (32%)** |
| the deployed 13 | 2026-10-15 probe | 13 | 12 (MHD not) |

**The IBKR public short-stock file was retired on 2026-09-09** (`docs/BRIEF.md`
§3), so it was not available. IBKR is waiting for a trigger (`docs/SYSTEM.md` §5,
2026-10-20).

### 5.2 Borrow where it matters

IBKR fee medians, %/yr, 2021-09-13 → 2022-12-30, for deployed names inside and
outside their programme windows.

| name | inside | outside |
|---|---:|---:|
| PHK | **44.7** | 5.5 |
| PFN | 28.7 | — |
| PTY | — | 24.1 |
| HYT | 23.6 | 15.2 |
| PCN | 19.2 | — |
| PDI | 11.6 | 8.7 |

**Borrow is dearest exactly when the sponsor is issuing:** both happen when the
fund is rich. At 20–45%/yr, a 63-session short pays about 5–11% in fees
(arithmetic: fee × 63/252). Paper charges
no borrow (`CLAUDE.md` landmine 1); real money would.

### 5.3 Capacity

| measure | value |
|---|---|
| median event-fund ADV (63 sessions before τ0, primary set) | **$2.48m** |
| events clearing the spec's `min_adv_usd` ($3m, read from the spec) | 28.6% |
| the book's gross per name, from the spec (capital × max gross stress ÷ 13) | $13,846 |
| that position as a share of the median event ADV | 0.56% |

**Capacity at our size is not the constraint; count, borrow and access are.**

### 5.4 Which counter

| version | counter |
|---|---|
| a standalone sleeve that shorts issuers | **EVENTS**, judged at the shared N = 6 bar of 1.893 (`docs/RESEARCH_STATE.md`) |
| an issuance-aware rule on the live book's shorts (block, cap or prefer shorts in a name running a programme) | **CEF** (`docs/SYSTEM.md` §5: changes to the live CEF book stay on CEF), judged at its N |

**How often would the filter bind?** Counted on the fit-period book (harness
`band_gross_capped`, spec v7, 2013-06-21 → 2022-12-30). These are name-days, not
returns.

| windows (first → last supplement, deployed names) | short name-days inside | share of all 9,285 |
|---|---:|---:|
| any offering episode | 1,820 | 19.6% |
| **programme episodes** (PCN 523, PFN 349, PTY 317, PDI 201, PHK 148, HYT 93, JFR 50) | **1,681** | **18.1%** |
| broad A1 events | 252 | 2.7% |

So a filter would bind often, but mostly on **one cluster**: PIMCO and BlackRock
windows in 2018–22, plus one Nuveen window in 2016–17; seven windows in all. As independent observations that is D7.

---

## 6. The gate and its verdict (question 5)

The gates were committed in `5c31340` before any level was computed. They run on
the primary set.

| gate | rule | measured | result |
|---|---|---|---|
| G-A1-1 (D7) | independent groups (sponsor × month) with ≥ 3 controls ≥ 30 | 0 (7 events with a path) | **FAIL** |
| G-A1-2 (identity) | share of events at or above NAV at τ0 ≥ 0.80 | 1.0 (7 of 7) | pass |
| G-A1-3 (mechanism) | median D63 ≤ −60bp (2 units × the grid's 30bp) and ≥ 60% negative | not computable: no event has controls | **FAIL** |
| G-A1-4 (negative control) | \|placebo D63\| < ½ \|event D63\| | no event D | **FAIL** |
| G-A1-5 (access) | share of still-listed event funds shortable at Alpaca ≥ 0.50 | 0.60 (15 of 25) | pass |

**Verdict: FAIL. A1 is not worth a pre-registration as a standalone EVENTS
trial.** Recorded reasons, in order of weight:

1. **D7:** 33 programme events in 15 years, and the matched design forms for none
   of the 7 measurable ones.
2. **Not provably beyond M1:** issuers are rich on the live z (median +2.02) when
   they issue.
3. **Access and borrow against a real-money version:** 8 of 25 premium funds are
   shortable today, and fees reach 20–45%/yr in issuance windows.

**What would reverse it:** a z-matched comparison over at least 30 independent
programme events (§7) that shows issuers' premiums compressing beyond M1 by more
than a round trip at 30bp.

---

## 7. What a pre-registration would need

This is not proposed now. For the record, and in order of cost:

1. **The live-book question first; it is cheaper and nearer.** This is a G6-style
   zero-trial measurement: the fit-period P&L of the book's shorts inside versus
   outside deployed programme windows, and the turnover a block would add, as
   `g6_corporate_action_shorts.py` did for tenders and mergers.
   - It computes the book's P&L on the 13 deployed names, which this brief
     excluded, so it needs the team lead's go.
   - **Kill line, re-measured at run time:** if the in-window short P&L a year is
     smaller than the filter's added turnover × 5bp, the filter is immaterial.
   - It is still D7 (seven windows, one sponsor cluster). The answer would rest
     on the 2023+ period, the time holdout, which is where the large programmes
     are (§2.5). **Opening it is the trial.**
2. **An ex-ante classifier.** Read each episode's first supplement cover for "at
   the market" or a sales agreement, replacing the ex-post ≥ 4 rule.
   - That needs about 709 first-supplement documents from EDGAR, a bulk fetch
     this note did not make.
   - The client exists (`scripts/data/edgar_client.py`, `SEC_USER_AGENT` from the
     team lead's env file). The reader does not; it would be a new
     `--classify-covers` stage in this script, unwritten.
3. **NAV for the 17 programme events outside both panels.** GOF, OXLC, ECC, NMZ,
   XFLT, OCCI, GBAB, NMI, NDMO and HERZ are listed; the rest are dead funds.
   - CEFConnect's long window is weekly (`fetch_cef_families_cefconnect.py`
     docstring), and its terms are an open question
     (`results/ops/CEFCONNECT_TERMS_OPTIONS_2026-10-19.md`).
   - Dead-fund daily NAV is plan item 0.8, still not held.
   - **No fetch command is given, because no script takes these tickers.**
4. **A control pool wide enough to match a fund at +10% and z +2 on the same
   day:** every CEF with a daily NAV, not one family panel.
5. **Borrow measured, not modelled at zero,** before any real-money version (the
   C4 ruling's condition).

---

## 8. What is not established

- **The recall of both methods.**
  - The DRIP ceiling assumes 100% participation, so it hides modest ATMs in
    high-yield funds; PTY 2018–20 and PFN 2018–22 are examples.
  - The index starts in 2008-Q1.
- **The precision of the programme set:** 6 of 6 on a draw of 15.
- **Whether MHD's and MQY's 2020 and 2025 424B3s are merger prospectuses** (they
  look it; not read).
- **Sponsor recognition** for independent groups: 36% of programme events have an
  unrecognised sponsor, each counted as its own group. That can only overstate
  the group count.
- **The literature** was read as abstracts, through IDEAS. Neither paper's sample
  or numbers were read.
- **Survivorship:** the families panel is today's live funds. Dead issuers have no
  NAV here.
- **Whether ATM issuance relieves borrow** (more float) or merely coincides with
  dear borrow (crowded shorts at a premium): §5.2 shows the coincidence, not a
  cause.
