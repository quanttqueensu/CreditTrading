# TLT variance premium and implied-vol build: SCALING §7 re-run — 2026-10-11

**Report only. Spends no trial: GAMMA stays at 0, XASSET at 0. No
pre-registration, no strategy test, no option position formed or scored.**
Research plan item 0.9 (`results/cef/RESEARCH_PLAN_2026-10-09.md`), for
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.1 row 3 (standalone short TLT
variance), the HYG figures of row 10, and the VXHYG defects of §7.4.

The figures under test were measured on 2026-10-08/09 by a desk agent whose
scratch scripts died with its session. Its code was recovered from its
transcript as provenance only and rebuilt as repo scripts. Its printed numbers
are what is checked here, not evidence.

**Data status, stated once and applied throughout.** The team lead's 2026-10-09
ruling (`docs/SYSTEM.md` §5) is: fit and decide on Cboe VXTLT 2004–2022, and
"the 2023+ strike data is the GAMMA holdout, opened once for the defined-risk
version". (SCALING §7.2 item 5 still lists that as open; `SYSTEM.md` records it
as ruled.) So the **main reading is VXTLT 2004–22**. Every 2023+ figure below
is labelled, is a re-computation of a number SCALING already printed, and
carries **no inference**. The tick-built series used no fitted parameter and
chose nothing.

## Reproducers

```bash
export QUANTT_ENV_FILE=".../config/.env"          # R2 and the Alpaca CEF paper key; never printed
C=results/gamma/_cache_inputs                     # gitignored (results/**/_cache_*)
python3 scripts/gamma/fetch_cboe_vol_indices.py --indices VXTLT VXHYG VXLQD VIX --out $C/cboe_vol_indices.parquet
python3 scripts/gamma/fetch_fred.py DGS1MO --out $C/fred_DGS1MO.parquet
python3 scripts/gamma/tlt_atm_iv.py extract       # R2 TLT option ticks -> per-month cache (read-only)
python3 scripts/gamma/tlt_atm_iv.py build         # 30-day ATM IV, 2023-11..2026-07
python3 scripts/gamma/tlt_atm_iv.py volume        # contracts per session from the same ticks
python3 scripts/gamma/tlt_atm_iv.py volume-check --day 2026-07-09   # R2 vs Alpaca bars, GET only
python3 scripts/gamma/vrp_summary.py --vol-panel $C/cboe_vol_indices.parquet
#   add --etf-panel data/rv/etf_panel.parquet.pre-20261011.bak for the 2026-07-28 panel the original read
python3 scripts/gamma/book_vs_shortvol.py --vol-panel $C/cboe_vol_indices.parquet
python3 scripts/gamma/option_chain_snapshot.py cboe   --out-dir results/gamma/_cache_option_chains TLT HYG
python3 scripts/gamma/option_chain_snapshot.py alpaca --out-dir results/gamma/_cache_option_chains TLT HYG
python3 scripts/gamma/option_chain_snapshot.py stats  --out-dir results/gamma/_cache_option_chains
```

`fetch_cboe_vol_indices.py` is the archived fetcher restored from tag
`pre-clean-slate` and extended (VXTLT, VXLQD, VIX; gap reporting). The other
scripts are new. `data/gamma/` and `data/vrp/` were read, never written.

## Inputs and last dates [V, read 2026-10-11]

| input | rows / span | last date |
|---|---|---|
| Cboe VXTLT (fetched 2026-10-11) | 5,717 rows from 2004-01-02 | 2026-10-09 |
| Cboe VXHYG (fetched 2026-10-11) | 1,933 rows from 2015-04-22, after dropping the named defect | 2026-10-09 |
| `data/gamma/cboe_vol_indices.parquet` VXHYG (fetched 2026-09-12) | 1,913 rows; **identical** to today's fetch on all 1,913 common days | 2026-09-11 |
| FRED DGS1MO | 6,300 rows from 2001-07-31 | 2026-10-08 |
| `data/rv/etf_panel.parquet` TLT, HYG `ret_total` (no fetcher on `main`; plan item 0.1) | from 2002-07-30 / 2007-04-11 | **2026-07-28** when these runs were made. **Rebuilt by another session at 16:01 the same day to 2026-10-09** (plan item 0.1); the old file is kept as `etf_panel.parquet.pre-20261011.bak`. The two are identical on every common date for TLT, HYG, AGG and SPY. So every 2004–22 figure below is identical on both, and only 2023+ figures move (stated where they do) |
| CRSP `dsf` TLT (permno 89468), HYG (91933), via R2 | — | 2024-12-31 |
| R2 TLT option ticks | 2023-11 .. 2026-07 | 2026-07-10 |
| CEF book: `data/cef/cef_prices.parquet` / `cef_nav.parquet` | book's first position 2013-06-21 | 2026-09-28 / **2026-09-25** |

## The reproduction table

| figure in SCALING §7 | original (2026-10-08/09) | re-run (2026-10-11) | verdict |
|---|---|---|---|
| TLT IV−RV, VXTLT 2004–22 | +1.23 vol pts | **+1.226** (all 4,771 IV dates) | **reproduced** |
| … its t, non-overlapping | 4.16 | **4.160** (n 228); the non-overlapping **mean is +1.282**, not +1.23 | **reproduced; label corrected**: the note paired the all-days mean with the non-overlapping sample's t |
| TLT IV−RV from R2 ticks (2023+, **holdout, description only**) | +1.63 | **+1.632** (n 525, 2023-11-01..2026-06-25; 533 sessions built, 111 skipped, identical to the original's counts) | **reproduced** (2023+, no inference). On the rebuilt panel (to 2026-10-09) the 8 IV dates 2026-06-26..07-10 gain a complete forward window: **+1.610, n 533** |
| Book correlation, daily (to 2022) | −0.01 | **−0.008** (n 2,396, 2013-06-21..2022-12-30; 95% CI −0.048..+0.032) | **reproduced** |
| Book correlation, monthly (to 2022) | −0.11 | **−0.109** (n 114 21-session blocks; CI −0.288..+0.076); calendar months −0.102 | **reproduced** |
| TLT options volume | "about 1.1m contracts a day" | 2026-10-08 snapshot not re-fetchable. **2026-10-09: 996,457 (Cboe) / 1,040,649 (Alpaca)**. But R2's complete tick history gives **median 424,772 a session, IQR 324,766–571,492 (2023-11..2026-07, 652 sessions)**; 2026 to July: median 476,501 | **corrected**: 1.0–1.1m is what 2026-10-08/09 traded, above the 75th percentile of the tick history. A typical session is about 0.4–0.5m |
| TLT near-ATM width | about 0.28 vol pts | **0.26 vol pts**, $0.02, 1.8% of mid (Cboe, session 2026-10-09, post-close); Alpaca indicative $0.0245, 1.9% of mid | **reproduced in kind** (one post-close session each) |
| Tail: "March 2020 −44.7 pts" | −44.7 | **−44.746**: the IV of **2020-02-21** against the realised vol of the 21 sessions after it (2020-02-24..2020-03-23) | **reproduced; label made precise** |
| HYG premium "larger" (VXHYG pre-2023) | +3.34 pts, variance ratio 3.31, t 5.35 | **+3.336, 3.309, t 5.353** (n 1,580; 2015-04-22..2021-09-23) | **reproduced** |
| HYG book correlation | +0.09 daily, +0.12 monthly; book −8.1bp vs +2.0bp on the leg's worst 5% of days | **+0.091** (CI +0.042..+0.140), **+0.118** (21-session blocks), **−8.1bp vs +2.0bp** | **reproduced**; the monthly figure **flips sign** on calendar months (−0.109), so only the daily one is robust |
| HYG post-close width | about 60% of mid | 2026-10-08 (original): 58.7% Cboe / 61.1% Alpaca. **2026-10-09: 69.8% Cboe / 65.3% Alpaca**; 1-month straddle 62.0% of mid | **reproduced in kind**: 60–70% of mid, post-close, varying by day |
| VXHYG corrupt row 2017-10-30 | present | **still upstream on 2026-10-11 (−19,738,470.0)**, dropped by name in `KNOWN_BAD` | **reproduced** |
| VXHYG has no rows 2021-09-24 to 2025-05-14 | present | **last row before 2021-09-23, first after 2025-05-15 (1,330 calendar days)** | **reproduced**; the archived G6 "2023–26" HYG era really is 2025-05 onward |

Every figure reproduced to the printed precision, from independent re-fetches
of the Cboe CSVs and FRED and a fresh R2 extraction. Two were corrected:
the volume statement and the mean/t pairing. Two labels were made precise.

## 1. TLT: implied minus forward realised vol, 2004–22 (the main reading)

`scripts/gamma/vrp_summary.py`. IV is VXTLT at t. RV is the realised vol of
TLT log total returns over sessions t+1..t+21, annualised on 252. VXTLT is a
VIX-methodology index that includes the OTM wings, so it sits above at-the-money
IV by the skew (about 1.46 pts on the 2023+ dates where both exist).

| window | n | IV / RV mean % | IV−RV mean (median) | IV²/RV² median | % days IV<RV | non-overlapping n, mean, t | t over the 21 phases (min / median / max) | Newey-West(20) t |
|---|---:|---|---|---:|---:|---|---|---:|
| **2004-01..2022-12 (fit)** | 4,771 | 14.45 / 13.22 | **+1.23 (+1.44)** | 1.27 | 28.4 | 228, +1.28, **4.16** | 3.79 / 4.40 / 5.75 | 5.67 |
| strict: no 2023 return in any window (IV dates to 2022-11-30) | 4,750 | 14.41 / 13.19 | +1.22 (+1.44) | 1.27 | 28.5 | 227, +1.27, 4.09 | 3.77 / 4.37 / 5.68 | 5.63 |
| same, RV from CRSP instead of `etf_panel` | 4,771 | 14.45 / 13.22 | +1.23 | 1.27 | 28.5 | 228, +1.28, 4.16 | 3.79 / 4.40 / 5.75 | 5.67 |
| *2023-01..2026-06, VXTLT (labelled; no inference)* | 873 | 16.26 / 13.64 | +2.62 | 1.53 | 22.6 | 42, +3.02, 6.97 | — | — |
| *2023-11..2026-06, R2 tick ATM (GAMMA holdout; description only)* | 525 | 14.04 / 12.40 | +1.63 (+1.74) | 1.32 | 25.9 | 25, +2.19, 3.73 | — | — |

- **The two realised-vol sources agree.** `etf_panel` and CRSP give a
  correlation of 0.99999 over 4,783 dates, with a maximum difference of 0.37 vol
  pts. Every statistic matches to the printed precision.
- **The vol-point t is not a fragile choice of phase.** Starting the
  non-overlapping sample on any of the 21 possible days gives t between 3.79
  and 5.75.
- **The tick build checks out against VXTLT.** On 533 common dates the level
  correlation is 0.981 and the daily-change correlation 0.869, as the original
  found.
- **Episodes, IV−RV minima.** 2008-Q4 −13.5; March 2020 **−44.7** (IV date
  2020-02-21); 2022 −4.8.

## 2. G2 readings without regular-hours spread data

G2 (plan §2) has three parts: (a) a VXTLT 2004–22 variance-swap proxy, net of
the measured four-leg regular-hours spread from item 0.10, is positive; (b) a
replay of 2008 and 2020 for a defined-risk structure stays inside the vol cap;
(c) the correlation with the book is about 0. **G2 cannot be passed or failed
today**: item 0.10 waits on the team lead's OPRA decision.

### G2(a): only the gross half is measurable, and it is weaker than the vol-point t suggests

VXTLT² is approximately the strike of a 30-day variance swap. So VXTLT_t² −
RV²(t+1..t+21) is the gross P&L of a short variance swap held 21 sessions, in
variance points (%²). Non-overlapping, 2004–22 [V, re-run]:

| window | n | mean %² | t | t over the 21 phases (min / median / max) | median %² | % positive | worst %² (IV date) | skew |
|---|---:|---:|---:|---|---:|---:|---|---:|
| **2004–22** | 228 | **+24.0** | **1.39** | 1.19 / 1.69 / 3.60 | +32.6 | 72.4 | −3,284 (2020-02-26) | −9.2 |
| 2004–09 | 72 | +26.2 | 1.50 | 1.49 / 2.11 / 3.45 | +26.5 | 76.4 | −606 (2008-11-11) | −0.3 |
| 2010–14 | 60 | +16.0 | 0.73 | 0.36 / 0.72 / 1.19 | +34.3 | 70.0 | −887 (2011-08-03) | −2.4 |
| 2015–19 | 60 | +24.9 | 2.78 | 2.11 / 2.77 / 3.34 | +38.0 | 73.3 | −180 (2019-08-09) | −0.7 |
| 2020–22 | 36 | +13.5 | 0.14 | 0.14 / 0.57 / 2.61 | +128.0 | 72.2 | −3,271 (2020-03-04) | −5.5 |

- **The gross proxy is positive in every era.** The question (a) asks of a net
  figure cannot be answered: no regular-hours four-leg spread exists.
- **In variance terms the premium is not established: t 1.39 over 2004–22.**
  Across the 21 start phases t runs 1.19–3.60 (median 1.69), against 3.79–5.75
  (median 4.40) in vol points. The difference is the tail: a short variance
  position loses the square of the realised move, and one month (IV date
  2020-02-26) costs as much as 137 average months. A defined-risk structure caps
  that tail. How much of the premium survives the cap depends on the wings, a
  pre-registration choice not made here, and is not measured.
- **The budget a cost must fit inside.** Gross, the premium is about +1.2 to
  +1.3 vol pts a month at the money. On the variance swap it is +24 %², about
  0.8 vol pts of vega notional at the mean strike (an approximation).
- **The only width measured is one at-the-money contract after the close.**
  Its full quoted width was 0.26 vol pts on 2026-10-09 and 0.28 on 2026-10-08.
  That is an upper bound on regular-hours width, from one session each. A
  four-leg cost cannot be built from it: wing strikes and wing vegas are
  structure choices.

**Missing for G2(a):**
1. At least 20 sessions of regular-hours NBBO on the candidate four-leg
   structures (0.10).
2. The structure itself (tenor, wing width, exit rule), from the
   pre-registration.
3. A skew history before 2023 for the wings. VXTLT is a single number; strike
   data starts 2023-11, inside the holdout.

### G2(c): measured in full, and it is about 0

Book: the v7 band 0.048, gross-capped at 1.8 (both read from the spec), on
total returns, `evaluate()` P&L, i.e. `shift(2)`. Short-vol leg:
0.5·(VXTLT_{t−1}²/252 − r_t²), with IV known at the previous close.

| window | daily ρ [95% CI] | 21-session blocks ρ [CI] (n) | calendar months ρ | short var-swap vs book over t+1..t+21 (non-overlapping) |
|---|---|---|---|---|
| **2013-06-21..2022-12-30** | **−0.008** [−0.048, +0.032] | **−0.109** [−0.288, +0.076] (114) | −0.102 | **−0.134** [−0.310, +0.050] (n 115) |
| *2023-01..2026-07 (labelled)* | −0.026 [−0.091, +0.040] | +0.029 (42) | +0.050 | — |

- **Every interval includes zero, under three constructions.** On the fit data,
  G2(c)'s "about 0" holds.
- **On the leg's worst 5% of days the book is roughly flat:** −0.6bp, against
  +2.4bp on average.
- **HYG is the contrast.**
  - Its daily ρ is +0.091 [+0.042, +0.140], an interval that excludes zero.
  - On HYG-leg's worst 5% of days the book averages −8.1bp, against +2.0bp.
  - Row 10's "the book loses on the same days" therefore reproduces on the
    daily data.
  - Its monthly sign does not: +0.118 on 21-session blocks, −0.109 on
    calendar months.

### G2(b): not measured

A replay of 2008 and 2020 needs a structure and a way to price its wings before
2023. That is a pre-registration choice, and this pass makes none. What is on
record is the unhedged tail: −13.5 vol pts (2008-Q4) and −44.7 (March 2020) in
IV−RV, and −606 and −3,284 %² on the variance-swap proxy.

## 3. Liquidity

| | TLT | HYG |
|---|---|---|
| contracts, session 2026-10-08 (original; Cboe / Alpaca) | 1,115,328 / 1,129,264 | 230,971 / 378,675 (sources disagreed) |
| contracts, session 2026-10-09 (re-run; Cboe / Alpaca) | **996,457 / 1,040,649** | **319,811 / 319,102** (agree) |
| contracts per session, R2 ticks 2023-11..2026-07 (*2023+, description only*) | **median 424,772**, IQR 324,766–571,492; yearly medians 356k (2023 Nov–Dec), 370k (2024), 453k (2025), 477k (2026 to July) | not in R2 |
| open interest, 2026-10-09 (Cboe) | 14.37m | 10.38m |
| near-ATM 1-month width, post-close 2026-10-09 (Cboe) | $0.02, 1.8% of mid, **0.26 vol pts** | $0.45, **69.8% of mid**, 5.2 vol pts |
| 1-month ATM straddle width, % of straddle mid | 2.1% | 62.0% |

- **Is R2's tick history complete?** If R2 were missing trades, the 425k median
  would understate. The check (`tlt_atm_iv.py volume-check`) compares R2's
  per-contract volume with Alpaca's daily option bars on the 100 most-traded
  contracts:
  - 2026-07-09: R2 534,430 against Alpaca 539,066; median per-contract ratio
    1.002.
  - 2024-06-12: 402,720 against 405,955; ratio 1.006.

  The low median is therefore the market, not missing ticks [V, two sessions
  checked].
- **The Cboe delayed-quote JSON has an undocumented source [U].** Whether it
  carries Cboe's own book or the consolidated NBBO is not documented. Taken
  during regular hours it might be a cheap partial path towards 0.10. That is
  untested, and so is the licence.

## 4. Data findings

- **VXHYG.**
  - The named defect is still published (2017-10-30 = −19,738,470.0).
  - The 1,330-day hole is real.
  - The panel fetched 2026-09-12 is identical to today's on every common day,
    so there has been no silent revision.
- **VXLQD has the same kind of hole:** no rows from 2022-11-08 to 2025-07-13.
- **VIXHY and VIXIG no longer download** (HTTP 403 / S3 AccessDenied on
  2026-10-09 and 2026-10-11). On 2026-09-12 they served 3,681 and 3,674 rows.
  The copy in `data/gamma/cboe_vol_indices.parquet` is now the only one. The
  fetcher's docstring says so, and a bare run raises on them.
- **The trade-condition map in the tick build is [U].** It is read as
  Polygon/Massive IDs and was not re-verified (the reference endpoint needs a
  key). It decides which prints are single-leg.

## 5. Deviations from the scratch method

- **None in any statistic.** The method was re-implemented from the
  transcript, and every count and figure matches.
- **Added as robustness:**
  - t over all 21 phases, and a Newey-West t;
  - the variance-swap proxy, by era;
  - the strict no-2023 window;
  - the CRSP second source for realised vol;
  - Fisher intervals, calendar months, and the variance-swap construction for
    the book correlation;
  - the R2 completeness check.

  None of them chooses a parameter.

## Gaps

- **Regular-hours four-leg spreads (0.10).** The OPRA feed returned 403 ("OPRA
  agreement is not signed") on 2026-10-09; the decision is the team lead's.
- **Volume on 2026-10-08 itself, and how it was distributed.** Alpaca's
  snapshot and Cboe's JSON serve the latest session only.
- **No HYG strike history anywhere** (R2 has no HYG options), and VXHYG covers
  neither 2008 nor 2021-09..2025-05.
- **`etf_panel.parquet` has no fetcher on `main`** (item 0.1). The CRSP second
  source covers TLT and HYG only to 2024-12-31.
- **Alpaca paper option fill realism is untested [U].**
