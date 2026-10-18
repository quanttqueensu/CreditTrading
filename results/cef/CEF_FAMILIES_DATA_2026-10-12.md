# CEF families data for trial C4 — 2026-10-12

**What this is.** The data foundation for trial C4 of
`results/cef/RESEARCH_PLAN_2026-10-09.md` §3 ("discount z-score on equity,
preferred and multi-asset CEF families (agenda B1) — needs NAV fetchers for
those families"). It builds and describes the data: which funds, their daily
price, volume and NAV history, and how far the sources agree. It is
reproduced by `python3 scripts/data/cef_families_quality.py` over the panels
that the four fetchers below build. **It tests nothing.** No discount z-score,
IC, P&L, Sharpe, correlation with the book or forward return was computed on
these funds. **Zero trials; no counter moved.**

**Holdouts.**

- No name in `data/cef/cef_universe.csv` (the deployed 13 and the 27-name
  holdout) is in any family panel. The guard
  (`cef_families_common.assert_no_universe_names`) runs before every write.
  Measured: 0 of the 177 candidates is one of the 44.
- The 2023-01-01 time holdout stays sealed for returns. The one statistic on
  changes, the lag-1 autocorrelation of NAV changes, reads 2013-01-01 to
  2022-12-31 only, and the code raises on a later window. Levels, coverage,
  repeats, volume and eligibility counts use every date. None of them is a
  return.

**Panels.** These are in `data/cef_families/`, which is gitignored and never
`data/cef/` (landmine 9; `out_path` refuses the live directory). The last
price and NAV date is **2026-10-09**. A run at 14:27 ET on 2026-10-12 dropped
that day's partial bar.

| file | source | schema | rows | funds | dates |
|---|---|---|---:|---:|---|
| `cef_prices.parquet` | yfinance | **live** `date open high low close volume ticker grp` (`grp` = family) | 925,342 | 164 | 1978-01-03 → 2026-10-09 |
| `cef_nav.parquet` | yfinance NAV symbol | **live** `date nav ticker` | 673,401 | 144 | 1998-10-26 → 2026-10-09 |
| `cef_prices_crsp.parquet` | CRSP `dsf` (R2), closing trades only; licensed, never committed | live price schema | 921,217 | 158 | 1926-01-04 → 2024-12-31 |
| `cef_nav_cefconnect.parquet` | CEFConnect, `1Y` daily and `All` weekly, `window` column | `date nav ticker close_cc discount_cc window` | 194,411 | 163 | 1996-10-18 → 2026-10-09 |
| `cef_actions.parquet` | yfinance dividends and splits of the price ticker | `date ticker dividends stock_splits` | 24,949 | 158 | to 2026-10-09 |
| `nav_flags.parquet` | the checks below, per fund-date: yfinance repeat, CEFConnect category, discount agreement | — | 673,401 | 144 | — |

The two live-schema files match `data/cef/cef_prices.parquet` and
`cef_nav.parquet` column for column and dtype for dtype, so the harness can be
pointed at them. **Nothing in the panels is corrected, filled or spliced.**
The defects below are flagged, not repaired. The C4 pre-registration has to
choose and declare its exclusions (H14).

**Rebuild** (raw responses are cached under `data/cef_families/raw/`; add
`--refresh` to re-fetch):

```bash
export QUANTT_ENV_FILE=<absolute path to the env file>   # Alpaca and R2 keys; never printed
python3 scripts/data/cef_families_universe.py        # CEFConnect fund list + Alpaca assets GET
python3 scripts/data/fetch_cef_families_yf.py        # yfinance price, volume, NAV
python3 scripts/data/fetch_cef_families_cefconnect.py
python3 scripts/data/stage_crsp_cef_families.py      # R2, read-only
python3 scripts/data/cef_families_quality.py         # writes results/cef/cef_families/*_2026-10-12.csv
```

The sources and their verification labels are in `docs/REFERENCES.md` §12h.
The methods are stated in each script's docstring.

---

## 1. The universe

**Families come from the Morningstar category that CEFConnect publishes**
(`/api/v3/DailyPricing`, field `Strategy`, read 2026-10-12T18:27Z, 359 funds).
The 2026-10-08 universe map put every equity and multi-asset fund in one
residual bucket, so a new hand classification was avoided. The mapping is
`cef_families_common.FAMILY_OF_STRATEGY`. A category it does not know raises.

| family | Morningstar categories |
|---|---|
| equity_domestic | US Equity |
| equity_global | Global Equity; Asia Equity; Emerging Market Equity; Single Country Equity |
| equity_sector | Sector Equity; Real Estate; MLP |
| equity_covered_call | Covered Call |
| preferred | Preferreds |
| multi_asset | US Allocation; Global Allocation |

**Out of scope, by stated reason** (`OUT_OF_SCOPE_STRATEGY`):

- credit and muni categories: the live book's asset class;
- convertibles: not among the C4 families as written;
- the four Commodity funds: Sprott physical-metal trusts, with no NAV symbol on
  CEFConnect.

**Inclusion rule.** A fund is in the panels only if all three hold:

- its category is one of the six families;
- it is not one of the 44;
- Alpaca lists it active and `tradable`. One read-only
  `GET /v2/assets?status=active`, cef key, 14,401 assets, read
  2026-10-12T18:27Z. The flags are true at that read only.

**Candidates and exclusions** (177 candidates, 164 included):

- 166 candidates are in the six categories on CEFConnect.
- 11 more are in the 2026-10-08 map's equity or preferred buckets but not on
  CEFConnect.
- Excluded: FXBY and BXSY, which are absent from Alpaca's active list.
- Excluded: the 11 map-only names (AKAF, BIGZ, BXMX, CHN, DIAX, FGB, JEQ, JPI,
  RVII, TEAF, TURN). They have no category and no NAV symbol from this source.
  Nine of them were also absent from Alpaca on 2026-10-08.

The Morningstar family differs from the 2026-10-08 map for 12 included funds.
Both are kept in the universe table:

- HERZ, BANX, FINS, FT, GUG and PDX: the map said taxable credit;
- ACV and GCV: the map said convertible;
- PSUS, ASA, DXYZ and PWRL: not in the map.

| family | tradable today | shortable today | sub-families |
|---|---:|---:|---|
| equity_domestic | 21 | 11 | US equity 21 |
| equity_global | 30 | 14 | global 13, Asia 8, emerging 6, single-country 3 |
| equity_sector | 45 | 32 | sector 30, real estate 10, MLP 5 |
| equity_covered_call | 21 | 15 | — |
| preferred | 15 | 10 | — |
| multi_asset | 32 | 18 | US allocation 17, global allocation 15 |
| **total** | **164** | **100** | |

**Per fund.** `results/cef/cef_families/universe_2026-10-12.csv` holds, for each
fund:

- the sponsor, as CEFConnect spells it;
- the inception date;
- the NAV symbol;
- the Alpaca flags;
- `in_cef_universe_csv`;
- the 2026-10-08 family.

**Inception check.** CEFConnect's inception date is within 31 days of the first
yfinance price for 140 of 164 funds, and of CRSP's first trade for 142 of 158.
The exceptions are funds older than yfinance's history (ADX, GAM, PEO and TY
start in 1980 on yfinance, against inceptions in 1927–29) and funds whose
history runs through a renaming. ZTR is one: CEFConnect says 2005, but CRSP
and yfinance carry it from 1988. These are listed per fund in `names_*.csv`
and are not resolved here.

## 2. Per family

Figures are from `results/cef/cef_families/families_2026-10-12.csv` and
`breadth_2026-10-12.csv`.

- **ADV** is the sleeve's own rule, read at 2026-10-09.
- **The floor** is the spec's `min_adv_usd`, read through
  `scripts/cef/spec.py`: $3,000,000 on `cef_discount.v7.20260928`.
- **"Flagged"** is the 14 funds in §3.2–3.3.
- **"Eligible"** means a paired price and NAV that day, at least 120 paired
  observations in the trailing `z_window` (252), and ADV at or above the
  floor. It mirrors the sleeve's filters without computing a signal.

| | domestic | global | sector | covered-call | preferred | multi-asset |
|---|---:|---:|---:|---:|---:|---:|
| tradable / with a yfinance NAV | 21 / 16 | 30 / 26 | 45 / 38 | 21 / 21 | 15 / 15 | 32 / 28 |
| first paired price+NAV: earliest / median fund | 1998-10 / 2001-08 | 1998-12 / 2006-10 | 1998-11 / 2008-09 | 2004-05 / 2005-10 | 2000-05 / 2005-09 | 1998-11 / 2006-01 |
| funds with ≥ 252 paired days before 2023 | 14 | 26 | 34 | 20 | 14 | 24 |
| NAV = CEFConnect to the cent, `1Y` daily rows | 99.6% | 99.3% | 99.5% | 99.5% | 99.9% | 99.3% |
| NAV = CEFConnect to the cent, weekly rows 1998–2026 | 84.1% | 96.6% | 89.3% | 95.3% | 97.0% | 91.8% |
| discount agrees within rounding: `1Y` / weekly < 2023 / weekly ≥ 2023 | 97.0 / 79.7 / 81.6% | 99.4 / 96.7 / 93.7% | 99.5 / 76.9 / 87.3% | 99.5 / 98.3 / 88.6% | 99.97 / 98.4 / 95.1% | 98.2 / 88.7 / 85.6% |
| funds flagged (§3) | 3 | 1 | 7 | 0 | 0 | 3 |
| NAV lag-1 autocorrelation, 2013–22: median [IQR] (n) | −0.10 [−0.14, −0.09] (13) | −0.01 [−0.06, 0.02] (26) | −0.05 [−0.08, −0.04] (34) | −0.16 [−0.18, −0.11] (20) | +0.01 [−0.07, +0.23] (14) | −0.04 [−0.10, −0.00] (24) |
| median ADV63, 2026-10-09 | $1.53m | $0.61m | $2.00m | $1.93m | $1.20m | $0.90m |
| clear the floor (all tradable) | 8 | 2 | 15 | 6 | 2 | 3 |
| … with a NAV | 7 | 1 | 11 | 6 | 2 | 1 |
| … and shortable today | 5 | 0 | 8 | 6 | 2 | 1 |
| … and not flagged | **3** | **0** | **6** | **6** | **2** | **1** |
| median eligible per session, median over 2013–22 (excluding flagged) | 5.5 (3) | 1 (1) | 7 (6) | 6 (6) | 1 (1) | 1 (1) |

**Pooled across all six families**, the median eligible count per session,
taken as the median over 2013–2022, is **20.5, or 18.5 without the flagged
funds**. Over 2004–2012 it is 16. By year it moves between 17.5 and 26.5 over
2013–2022. It falls to 14 in 2023 and rises to 30 in 2026. The 2023 low is
liquidity: the median fund-day dollar volume fell from $1.10m in 2022 to
$0.90m. NAV coverage did not fall.

**Reference.** The deployed 13, by the same rule on the live panels, give a
**median of 5** over 2013–2022, 2 over 2004–2012 and 13 in 2026. The live
panels were read only; their last date is 2026-09-28.

**The 18 funds today** that clear the floor, are shortable and are not flagged:

| family | funds |
|---|---|
| covered-call | SPXX, ETY, BDJ, EXG, NFJ, QQQX |
| sector | UTF, DNP, NXG, KYN, HQH, IGR |
| domestic | USA, ADX, BTX |
| preferred | JPC, PTA |
| multi-asset | CSQ |

Three of them, BTX, NXG and KYN, have a yfinance NAV only from 2024-08 or
2025-01 (§4).

## 3. Source agreement (never averaged; the panel is yfinance, as the live book's is)

### 3.1 NAV levels: yfinance vs CEFConnect

- **Daily, 2025-10-13 → 2026-10-09:** 34,313 of 34,492 fund-days agree to the
  cent (99.48%). Of the 179 that do not:
  - 124 are **yfinance stale copies**: yfinance printed its own previous NAV
    while CEFConnect moved;
  - 8 are one-day date shifts;
  - 47 are unexplained.
- **Weekly, 1998-10-30 → 2026-10-09:** 118,353 of 128,213 agree (92.3%). Of the
  rest:
  - 4,237 are yfinance stale copies;
  - 2,252 agree once yfinance's split factors are undone;
  - 829 are one-day shifts;
  - 2,542 are unexplained.

**Stale copies come in episodes.** The table counts the weekly fund-days on
which yfinance repeats its previous NAV while CEFConnect's moved
(`nav_flags.parquet`):

| year | stale copies | weekly fund-days compared |
|---:|---:|---:|
| 2018 | 14 | 6,171 |
| 2019 | 329 | 6,209 |
| 2020 | 482 | 6,128 |
| 2021 | 8 | 5,812 |
| 2022 | 148 | 6,331 |
| **2023** | **1,514** | 6,488 |
| **2024** | **786** | 6,520 |
| 2025 | 27 | 6,708 |

The share of yfinance NAV rows that exactly repeat the previous row tells the
same story (`nav_repeats_2026-10-12.csv`). For covered-call funds it is
5.8–7.3% in 2014–16 and 4.8% in 2022, against 14.7% in 2019 and 16.0% in 2023.

**Why it matters for C4.** A stale NAV under a moving price is precisely the
artefact that killed `single-fund-PD`. The discount then predicts the NAV's
catch-up, not a price move. It is concentrated in 2023–24, the time-holdout
years.

**Only 6 of the 144 funds agree to the cent on every compared row.** By the
standing rule ("agreement to the cent, or the name is incomplete",
`docs/SYSTEM.md` §5, 2026-09-08), 138 are incomplete over their full history.
On the daily `1Y` window, all 144 agree on at least 95% of days.

### 3.2 Discounts: yfinance vs CEFConnect's own price and NAV

This comparison is basis-free. A source that re-based both legs still gives
the right discount. The tolerance is derived: half a cent on each of the four
inputs.

**Twelve funds disagree on more than half of their pre-2023 weekly dates:**

| fund | family | median gap, pp | what differs (medians, before 2023) |
|---|---|---:|---|
| GUT | sector | 5.6 | yfinance close re-based (0.950 × CRSP raw), NAV raw |
| NRO | sector | 4.1 | close 0.954 × CRSP; NAV raw. yfinance books a 1.048 'split' (2025-01-23) |
| GAB | domestic | 3.9 | both legs re-based, by different amounts (close 0.939, NAV 0.978) |
| ZTR | multi | 3.3 | prices agree; NAV legs differ (yfinance/CEFConnect 1.050). yfinance is internally consistent at its 2012 1:4 split; attribution open |
| RIV | multi | 3.1 | close 0.955 × CRSP (yfinance 'splits' 1.016, 1.017, 1.030); NAV raw |
| SRV | sector | 28.9 | prices agree (both 20× CRSP); CEFConnect's NAV is on another basis (yfinance/CEFConnect 0.377). yfinance is consistent at its two large splits; attribution open |
| CRF | domestic | 2.3 | close 0.980 × CRSP with no split in yfinance's record; NAV raw |
| UTG | sector | 2.1 | close 0.978 × CRSP, no split recorded; NAV raw |
| CLM | domestic | 1.8 | close 0.984 × CRSP, no split recorded; NAV raw |
| GGT | sector | 1.3 | both legs re-based, by different amounts |
| BST | sector | 1.1 | close 0.988 × CRSP, no split recorded; NAV raw |
| JRI | multi | 0.6 | close 0.993 × CRSP (yfinance 'split' 1.007, 2026-02-06); NAV raw |

**The bias cannot be recovered from yfinance's own split record.** For eight of
the twelve (GUT, NRO, RIV, CRF, UTG, CLM, BST, JRI), yfinance's close is
back-adjusted while its NAV symbol is not, so
**the yfinance discount is biased before each event**. For CLM, CRF, UTG, BST
and GUT, the record shows no event at all.

**Twelve more funds are episodic** (50–95% agreement): GGZ, KF, TDF, AIO, BCX,
BMEZ, BUI, DNP, EMO, PEO, TYG and GLV.

**On the weekly rows from 2023 on, 89 of 144 funds are episodic.** That is the
stale-copy episode in §3.1.

### 3.3 Split basis

At every split yfinance records, the close/NAV ratio is compared over the 20
paired sessions either side (`splits_2026-10-12.csv`). There are 40 events:
14 on one basis, 2 mismatched, 17 too small for the test, and 7 without a
paired NAV on both sides.

- **IAF (1:3 reverse split, 2025-10-23)** and **AWP (1:3, 2026-02-09)**: the
  yfinance close is re-based ×3 and the NAV is not. Their whole pre-split
  history reads as a premium of +170% and +207%: 5,192 of 5,434 and 4,721 of
  4,890 paired days show |discount| > 50%.
- CEFConnect's weekly history for both funds starts only at or just before the
  split (2025-10-31 and 2026-02-06), so the discount check could not see this. This is the case the split test exists for.
- Other large-factor events (reverse splits at TYG, SRV, KF, ZTR, CLM, CRF, BTO
  and others; forward splits at ADX and PEO) show price and NAV on one basis.
- Factors below 1.25, which are rights offerings and share distributions,
  cannot be seen by this test. §3.2 covers them.

### 3.4 Prices: yfinance vs CRSP, to 2024-12-31

Comparisons cover 843,465 fund-days:

| category | fund-days | share |
|---|---:|---:|
| agree raw within $0.005 | 698,697 | 82.8% |
| agree after undoing yfinance's split factors | 93,818 | 11.1% |
| disagree | 50,950 | 6.0% |

Most disagreements are the re-based funds of §3.2: CRF, GAB, GGT, GUT, CLM,
GLV, UTG and BST. HERZ and BTX are the others; neither has usable pre-2025 NAV.

Two further counts:

- **2,356 yfinance bars fall on CRSP no-trade days.** CRSP's `prc` < 0 there:
  there was no closing trade. yfinance prints a bar on those days. The largest
  counts are GRF 621, FUND 484, RCG 369 and CRF 300.
- **8,367 yfinance bars fall on dates the fund's permno has no CRSP row.**

**Volume.** yfinance volume / CRSP volume has a median by fund of 1.000 (148
funds, range 0.9995–1.0039), so the ADV figures do not depend on the source.

**CRSP mapping.**

- 158 of 164 funds map. The other six (BPRE, CFND, PSUS, PWRL, RVI, VCX) listed
  after CRSP ends.
- *Corrected 2026-10-15:* **BTX is mis-mapped.** Its current permno here, 76963,
  is a biotech (NTN Buzztime → Brooklyn Immunotherapeutics → Eterna, share code
  11) that used the ticker in 2021–22. yfinance's BTX history is the former BIGZ,
  CRSP permno 20674 (share code 44), which matches 947 of 948 closes. The files
  in `data/cef_families/` were not rebuilt; trial C4 carries the override
  (`docs/REFERENCES.md` §12h, correction row).
- A fund maps to its **current** permno, and then that permno's whole history
  is taken.
- The plain date-range join of the live cross-check would have tied STEW's
  1980–93 bars to Stewart Sandwiches and RCG's to eResource Capital. Both have
  share codes 10/11 and are refused. The same join would have tied AEF's and
  CRF's bars to other funds that once used those tickers.
- QQQX's pre-2014 rows come from its reorganised predecessor permno (1,991
  rows). They are counted per fund, so the pre-registration can decide whether
  to use them.
- CRSP adds 77,752 fund-days before yfinance's first bar, almost all before
  1998, when no NAV exists. **CRSP therefore does not extend any discount
  history.**

**Since 2025.** The only independent price check is CEFConnect's daily close:
36,533 of 37,037 fund-days agree (98.6%).

## 4. Coverage and gaps

**Price.** Inside each fund's own span there are no missing sessions (at most
1). A session is a date on which at least 10 funds trade. That definition only
binds from the 1980s, so yfinance bars from 1978–1990 on dates with fewer funds
are counted separately (`px_dates_not_sessions`). One yfinance row had no
close or volume and was dropped and counted.

**NAV.** Inside each fund's span, sessions with a price but no NAV number at
most 7. The longest run is 6 (PGP). Some funds have NAV rows before their
first yfinance price: DMA 1,896, HPI 233.

**20 tradable funds have no usable daily NAV:**

| family | funds |
|---|---|
| domestic | CET, CFND, GRF, HERZ, PSUS |
| global | JOF, MXF, RVI, TWN |
| sector | ASA, BPRE, DXYZ, MEGI, PWRL, VCX |
| sector, refused | BANX: XBANX returns BANX's market price on 98.3% of paired dates, while CEFConnect shows a monthly NAV |
| multi-asset | BCAT, ECAT, PDX, RCG |

Several are liquid: DXYZ ($31.0m ADV), VCX ($19.4m), BCAT ($13.6m), PSUS
($12.6m), BPRE ($11.3m) and ECAT ($8.1m). CEFConnect shows only quarter-end NAVs
for CFND, RVI and DXYZ, and nothing for VCX. These funds cannot carry a daily
discount from any free source found.

**Ten funds have a yfinance NAV only from 2024-08 or 2025-01**, although
CEFConnect's weekly history goes back years: IGA, BTX, SPE, BSTZ, NXG, GUG,
HGLB, TBLD, NPFD and KYN.

## 5. NAV staleness: is the "stale-NAV control" real?

The lag-1 autocorrelation of daily NAV total-return changes, 2013–2022, is in
the §2 table.

| | median | IQR |
|---|---:|---|
| deployed 13, same method (12 with enough history; PDO too short) | **+0.34** | [+0.29, +0.42] |
| equity families (four medians) | −0.16 to −0.01 | — |
| multi-asset | −0.04 | — |
| preferred | +0.01 | upper quartile +0.23 (JPC +0.19 and PTA +0.32 are among the higher) |

The share of zero NAV changes tells the same story: 5–8% for the equity
families, 10% for preferred, 16% for the deployed 13. Adding distributions back
changes no family median by more than 0.012.

So, measured on the vendor series:

- **Domestic, sector and covered-call NAVs are not smoothed.** They can serve as
  the stale-NAV control for W4/W13.
- **Preferred NAVs are partly smoothed.**
- **Global funds need care.** Their NAVs are struck at foreign closes, hours
  before the US close that prices the shares. Lag-1 autocorrelation within the
  NAV cannot see that asynchrony. A discount between a 16:00 ET price and an
  Asian-close NAV is the `single-fund-PD` structure: the price correctly leads
  a stale NAV. That is a structural point, not measured here [S: graveyard,
  `docs/RESEARCH_STATE.md`].
- **Vendor stale copies (§3.1)** are a separate, episodic staleness that this
  autocorrelation does not isolate.

## 6. Is C4 worth its trial? (breadth only; nothing here measures an edge)

**Pooled, yes on breadth.** One cross-section across the six families, each
fund ranked against its own history as the live signal does, has a median of
about 18 eligible funds per session over 2013–2022 once the flagged funds are
dropped. The deployed 13 have 5 by the same rule. Today 18 funds are liquid,
shortable and unflagged.

**Per family, no.** The spec's `min_names` is 6 (read through `spec.py`,
2026-10-12). Covered-call and sector sit at that level. Without the flagged funds, domestic, global,
multi-asset and preferred sit at or below 3 over 2013–2022. Six per-family
trials would also cost six counts on CEF, against one pooled.

**What the pre-registration must decide before it runs** (none of it is
decided here):

1. Exclude the 14 flagged funds, or their flagged dates. `nav_flags.parquet`
   and `names_*.csv` carry both, and the script re-measures them.
2. Treat yfinance stale-copy rows, which are concentrated in 2019–20 and
   2023–24. Mask them, or report the result with and without them.
3. Decide whether global funds belong in the pooled cross-section at all, given
   the asynchrony in §5. The alternative is to run them as a labelled negative
   control.
4. Survivorship. CEFConnect lists only live funds, so every count above
   includes only funds alive on 2026-10-12. Dead funds have no NAV in any
   source here. The bias runs toward funds that did not liquidate or merge.
5. Distributions. Equity and covered-call CEFs pay large managed
   distributions, so the third (distribution-adjusted) P&L line (plan 0.4) is
   the relevant paper score.
6. The kill test "correlation with the book ≥ 0.5" is a return statistic. It
   was not computed.

## 7. Gaps, and what is not established

- **No independent raw NAV history.** CEFConnect's history is weekly and
  restated (REFERENCES §12h), and CRSP MF does not hold CEFs (`docs/DATA.md`
  §6). The N-CSR/N-PORT route is plan item 0.8. It is now unblocked by the
  2026-10-12 SEC user-agent ruling, but it is not built.
- **No independent price check for 2025–26** except CEFConnect's daily close.
  Alpaca SIP bars (`scripts/rv/alpaca_daily.py`) would add one; not done.
- **Borrow** is today's flag only. The collector's daily `borrow_snapshot`
  reads Alpaca's whole asset list, so a history for these symbols has been
  accumulating since 2026-10-09 (`docs/DATA.md` §5).
- **Distributions** come from yfinance only, which is incomplete against CRSP
  on the live 13 (REFERENCES §8). They are used here only in the staleness
  measure, beside its raw-NAV twin.
- **Bid–ask spreads** of these funds were not measured here.
- **Not measured, but implied for the live book (flag for the team lead,
  [U]).** The same vendor feeds `data/cef/cef_nav.parquet`. Its repeat share for
  the deployed 13 rises from 10.1% (2022) to 22.2% (2023) and 26.3% (2024).
  Credit NAVs genuinely repeat more often, so this alone proves nothing. A
  CEFConnect weekly check of the 13, like §3.1, would settle whether the 2023–24
  stale-copy episode is in the live panel and in the W4 baseline. Separately,
  `data/cef/cef_splits.parquet` books a 1.029 'split' for BIT on 2025-08-19. §3.2
  shows that yfinance re-bases the close for such events and not the NAV. Whether
  BIT's live discount before that date is biased has not been checked.
  *Measured later on 2026-10-12* (`results/cef/LIVE_NAV_QUALITY_2026-10-12.md`):
  the 2023–24 episode is in the live panel (201 of 649 weekly fund-days in
  2023); BIT's close is not re-based (the event is a rights offering, and the
  panel is raw on both legs).

## 8. Graveyard check

**Relevant deaths:**

- `single-fund-PD` (the discount was NAV staleness, not dislocation): §3.1 and
  §5 locate where that risk lives in these data.
- The "stale-price artifact" pattern: yfinance bars on CRSP no-trade days, §3.4.

**What C4 is not:** C4 is not a rebuilt dead mechanism. It is the live signal on
new funds, already on the plan.

**Distribution data:** used here only as a staleness input, never as a signal.

---

*Tables:* `results/cef/cef_families/{universe,names,families,breadth,splits,nav_repeats,staleness_ref13}_2026-10-12.csv`.
*Sources:* `docs/REFERENCES.md` §12h.
*Code:* `scripts/data/cef_families_*.py`, `fetch_cef_families_*.py`, `stage_crsp_cef_families.py`.
*Tests:* `scripts/data/tests/test_cef_families.py`.
