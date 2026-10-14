# Gate G2 on free data: TLT standalone short variance — 2026-10-12 (corrected 2026-10-13)

Reproduced by `scripts/gamma/g2_spreads.py` (spread inputs),
`scripts/gamma/g2_gate.py` (G2(a) and G2(b)) and
`scripts/gamma/book_vs_shortvol.py` (G2(c)). The full command list is under
Reproducers below.

**Zero-trial gate. GAMMA stays at 0.** Trial G1 was not run, and nothing is
pre-registered. 2023+ TLT option prices enter only as spread costs, as the team
lead's 2026-10-12 ruling allows (`docs/SYSTEM.md` §5). Since 2026-10-13 no 2023+
return enters any figure here; before that, two did (the correction below).

> **CORRECTED 2026-10-13: sealed 2023 returns were touched.** This paragraph
> read "No 2023+ return statistic was formed or read." That was false, in two
> ways, and an independent review caught both:
>
> 1. **The G2(a) headline** took IV dates in 2004–22, so its last
>    non-overlapping window (IV date 2022-12-27) ran its realised vol on January
>    2023 TLT returns. The "strict window" row beside it excluded that window,
>    but the headline was the other one.
> 2. **The G2(c) re-run printed `book_vs_shortvol.py`'s labelled "2023+" block**
>    of book-versus-short-variance correlations, and it was seen (§3 said so but
>    did not quote it). The same script's second method filtered only the IV
>    date, so its last window ran to 2023-01-31.
>
> **The effect on the verdict is negligible.** On the strict window (every
> window ends by 2022-12-30), the upper bound nets **−18.9 %² (t −1.12)**
> against −18.4 (t −1.09), and the point cost **+15.2 (t 0.88)** against +16.1
> (t 0.94). The strict window is now the only window. Both scripts refuse 2023
> returns, and tests pin it (`test_g2_gate.py`, section 8).
> `docs/RESEARCH_STATE.md` records the touch for whoever opens the GAMMA holdout.

> **Corrected 2026-10-13 after an independent review.** The review confirmed
> the verdict with corrections: (a) fails under the upper-bound cost, (b)
> passes on the realised path, (c) is about 0. Each correction is marked where
> it applies:
>
> 1. **(b)'s "any-path bound" was not a bound** (§2). The demeaned and
>    not-demeaned bounds are now reported separately, and the not-demeaned one
>    exceeds 20%.
> 2. **The holdout** (above): the strict window is the headline.
> 3. **"Relaxing either convention brings the net to zero or above" had no
>    reproducer** (§1.4). Both relaxations are now rows, and only one of them
>    flips the sign.
> 4. **The delta-adjusted Roll is probably not biased down** (§1.2). Its
>    direction is now [U], and plain Roll is shown beside it.
> 5. **Two gaps were missing**: physical settlement, and Alpaca's options
>    level (Gaps).
> 6. **Smaller points**: a dormant silent fallback in the model mark, a
>    mis-dated VXTLT, and the phase-0-only t (§1.1, §1.4, §2).
>
> Every changed figure was re-run on 2026-10-13 with the scripts named, from the
> same cached inputs as 2026-10-12.

The gate is `results/cef/RESEARCH_PLAN_2026-10-09.md` §2, row G2. It passes
when:

- (a) the VXTLT 2004–22 variance-swap proxy, net of the four-leg spread, is
  positive;
- (b) a 2008 and 2020 replay of a defined-risk structure stays inside the vol
  cap;
- (c) the correlation with the book is about 0.

It kills G1 when (a) ≤ 0 or (b) breaches the cap.

The 2026-10-12 rulings set the terms:

- no paid options data;
- G2 runs "as a conservative gate: an upper-bound spread and a bounded-loss
  crash replay";
- a historical spread series replaces plan 0.10's "20 live sessions";
- 2023+ spreads and costs may be used, and 2023+ returns stay sealed.

## Verdict

| sub-gate | verdict on free data | the numbers |
|---|---|---|
| **G2(a)** premium net of spread | **FAILS as specified (the conservative upper bound). Indeterminate on the merits** | Net of the declared upper-bound cost (13.74bp of S per cycle, 1.26 vol pts), the variance-swap proxy is **−18.9 %²/month (t −1.12)**, on IV dates 2004-01-02..2022-11-25 with every window ending by 2022-12-30 (n 227). In vol points IV−RV is **+0.01 (t 0.03)**. Net of the trade-measured point cost (2.57bp, entry only) the proxy is **+15.2 %² (t 0.88)**. **The sign flips between the measured cost and the bound, at every one of the 21 start phases.** The gross proxy is itself not established in variance terms: +23.1 %², t 1.33 (start phase 0; 1.14 to 3.51 across the 21 phases; Newey–West(20) 2.33) |
| **G2(b)** 2008 / 2020 replay inside the 20% cap | **PASSES on the realised path** for the declared structure (BFLY rule), under both declared sizings. **Any-path safety is not established** for the not-demeaned measure | Zero credit, sized to the spec's 6% target, the annualised vol of cycle P&L is **7.1% / 7.2%** (2008 / 2020) on VXTLT sizing and 6.8% / 6.6% on trailing-RV sizing. Not demeaned: 12.9% / 11.7%. The worst sub-window is 16.6% (Feb–Apr 2020, three cycles). The demeaned bound is ≤ 14.0% for every BFLY window. **The not-demeaned bound √12·max(nW) exceeds 20%**: 22.2% in 2020 and 27.0% over 2004–22 (VXTLT sizing). **The CNDR rule sized on trailing RV is not cap-safe**: its demeaned bound is 48.8% in 2008 |
| **G2(c)** correlation with the book | **PASSES (about 0)**; re-run 2026-10-13 on the corrected script | Daily **−0.008 [−0.048, +0.032]** (n 2,396, 2013-06-21..2022-12-30); 21-session blocks −0.109 [−0.288, +0.076]; calendar months −0.102; short variance swap vs book **−0.131 [−0.307, +0.054] (n 114)**, every window ending by 2022-12-29 |

> **CORRECTED 2026-10-13.** Until today this table read as follows. (a): upper
> bound −18.4 %² (t −1.09), IV−RV +0.02 (t 0.06), point cost +16.1 (t 0.94),
> gross +24.0 (t 1.39). Those were on n 228, whose last window ran on January
> 2023 returns (the holdout correction above). (b): "Any-path bound ≤ 14.0% …
> the fly cannot breach 20% on any path", and the CNDR bound "46.8% in 2008".
> (c): "identical to 2026-10-11", var-swap −0.134 [−0.310, +0.050] (n 115),
> whose last window ended 2023-01-31. The (b) bound is corrected in §2.

**Read with the plan's kill rule and the conservative ruling, G2 does not pass,
because of (a).** That is a finding about cost conventions as much as about the
market:

- the declared upper bound stacks three conservative choices;
- **relaxing the round-trip convention alone** (the upper-bound widths, held to
  expiry) brings the net to about zero: **+2.1 %² (t 0.12)**;
- **relaxing the 90th percentile alone** (the median month, full width) leaves
  it negative: **−3.8 %² (t −0.23)**;
- so only the round-trip convention flips the sign, and then the net is about 0
  (table in §1.4).

> **CORRECTED 2026-10-13.** The second bullet read "relaxing either of the two
> that are conventions brings the net back to zero or above (table in §1.4)".
> The table had no such rows, so the sentence had no reproducer. Both are now
> rows of `g2_gate.py premium`. The review computed them on the old window as
> +2.8 (t 0.16) and −3.2 (t −0.19); on the strict window they are +2.1 and −3.8.

The deciding questions are therefore two.

1. **Does a held-to-expiry structure get charged a round trip?** That is the
   team lead's call, not a measurement.
2. **What is the true regular-hours width?** No free fit-period quote exists.

§4 says what would move each.

## Reproducers

```bash
export QUANTT_ENV_FILE=".../config/.env"     # R2 + the CEF paper key; never printed
C=results/gamma/_cache_inputs                # gitignored
python3 scripts/gamma/fetch_cboe_vol_indices.py --indices VXTLT --out $C/cboe_vxtlt.parquet
python3 scripts/gamma/fetch_fred.py DGS1MO --out $C/fred_DGS1MO.parquet
python3 scripts/gamma/g2_spreads.py extract                 # R2 TLT option prints, read-only
python3 scripts/gamma/g2_spreads.py minute-bars             # TLT 1-min SIP bars, Alpaca GET
python3 scripts/gamma/g2_spreads.py coverage
python3 scripts/gamma/g2_spreads.py roll --out $C/g2_roll.parquet
python3 scripts/gamma/g2_spreads.py underlying            # in regular hours: TLT spot (GET) ...
python3 scripts/gamma/option_chain_snapshot.py alpaca --out-dir results/gamma/_cache_option_chains TLT   # ... then the chain
python3 scripts/gamma/g2_spreads.py indicative --out $C/g2_indicative.parquet
python3 scripts/gamma/g2_gate.py premium --roll $C/g2_roll.parquet --indicative $C/g2_indicative.parquet
python3 scripts/gamma/g2_gate.py replay --vol-cap 0.20
python3 scripts/gamma/book_vs_shortvol.py --vol-panel <VXTLT + VXHYG long-form parquet>  # G2(c)
python3 -m pytest scripts/gamma/tests/test_g2_gate.py
```

On 2026-10-13 the G2(c) panel was the cached VXTLT fetch of 2026-10-12 plus the
VXHYG rows of `data/gamma/cboe_vol_indices.parquet`, concatenated long-form in a
scratch file. Since 2026-10-13 none of these scripts prints a 2023+ return
statistic.

**About the TLT stock snapshot.** On 2026-10-12 the indicative snapshots were
paired with a TLT stock snapshot taken by a scratch helper in the same 10-minute
loop: a read-only `GET /v2/stocks/TLT/snapshot?feed=iex`. That GET is now the
`underlying` step of `g2_spreads.py`.

**About the 2026-10-12 snapshots.** They are in the gitignored cache. They
cannot be re-fetched, because Alpaca serves only the latest snapshot.

## Inputs and last dates [V, read 2026-10-12]

| input | span / rows | last date |
|---|---|---|
| Cboe VXTLT (fetched 2026-10-12) | 5,717 rows from 2004-01-02 (the same count as 2026-10-11) | 2026-10-09 |
| `data/rv/etf_panel.parquet` TLT (`close` is unadjusted: close/close₋₁ − 1 equals `ret_px` to 2.5e-8) | from 2002-07-30 | 2026-10-09 |
| FRED DGS1MO | 6,300 rows | 2026-10-08 |
| R2 TLT option prints: single-leg codes, 09:30–16:00 ET, 10–60 DTE | **4,310,275 prints, 652 sessions**, 2023-11-01..2026-07-10 | 2026-07-10 |
| Alpaca TLT 1-minute SIP bars (raw) | 476,328 bars | 2026-07-10 |
| Alpaca indicative TLT option chain | 9 snapshots, 14:43–15:54 ET on 2026-10-12; 8 paired with a TLT quote (the first had no stock snapshot before it and is reported, not used) | 2026-10-12 |
| CEF book (G2(c)) | first position 2013-06-21 | prices 2026-09-28 / NAV 2026-09-25 |

**R2 misses month-end sessions.** In **21 of the 32 complete months** R2 lacks
the month's last NYSE session (`g2_spreads.py coverage`). No other session is
missing, and 2026-07 ends on 07-10. A spread estimate is biased by this only if
month-end spreads differ, which cannot be checked here.

**2026-10-12 was a SIFMA full bond-market close (Columbus Day)** [S, SIFMA
press release of 2026-09-29, via search]. Equity and option markets were open.
The cash Treasury market a TLT market maker hedges in was shut, so today's
widths may not be typical. This does not move the upper bound: on every leg,
the trade-based term is larger than the indicative one.

## 1. G2(a): the premium net of spread

### 1.1 Spread input (i): Alpaca's free `indicative` feed

Alpaca: "Indicative Pricing Feed is a free derivative of the original OPRA
feed … the quotes are not actual OPRA quotes, they're just indicative
derivatives" [V, docs, read 2026-10-12]. **Treat it as indicative, not as an
NBBO.** The quoting venue code changed between snapshots, and a leg's width
jumped from $0.01 to $0.06 and back within ten minutes, which suggests
single-venue quotes [U].

The declared structure on 2026-10-12:

- the 2026-11-20 monthly expiry (39 DTE);
- spot $77.94–$78.00;
- K 78 ATM, 74 put wing, 82 call wing.

| leg | median width | in bp of S | widest seen |
|---|---|---|---|
| ATM call 78 | $0.02 | 2.56 | $0.05 (6.4bp) |
| ATM put 78 | $0.015 | 1.92 | $0.06 (7.7bp) |
| call wing 82 | $0.015 | 1.92 | $0.06 (7.7bp) |
| put wing 74 | $0.01 | 1.28 | $0.05 (6.4bp) |

The fly's net vega from the snapshot's own greeks is $0.0905 a share per vol
point (median 0.001161 per $1 of S over the 8 paired snapshots [V, re-run
2026-10-13, `g2_gate.py premium`]). Black–Scholes at the latest VXTLT published
before 2026-10-12, the **2026-10-09 close (14.64)**, and 30 days gives 0.001163
[V, same run]. **The two conversions agree.**

> **CORRECTED 2026-10-13.** This read "Black–Scholes at that day's VXTLT
> (14.64)". 14.64 is the 2026-10-09 close: the cache was fetched at 18:47 UTC on
> 2026-10-12, before that day's value existed. The check is now printed by
> `g2_gate.py premium`, which names the VXTLT date it uses. The $0.0905 a share
> was not re-derived.

### 1.2 Spread input (ii): R2 trade prints and Roll (1984)

R2 holds trades only. The estimator is Roll's:
s = 2√(−cov(Δpₜ, Δpₜ₋₁)), pooled by month and leg bucket. The buckets are 20–45
DTE and moneyness against the previous session's close: ATM 0.99–1.01; put wing
0.93–0.97, puts; call wing 1.03–1.07, calls. Sweeps are collapsed: prints that
share a contract and a millisecond become one trade.

**Its biases, stated before reading it:**

- **Biased down by persistent order flow.** With trade-sign autocorrelation ρ,
  Roll returns s(1−ρ). The derivation is in `roll_bias_factor`, and a
  simulation test pins it. Choi, Salandro & Shastri (1988) treat the
  serially-dependent case. Tick-test sign autocorrelation runs 0.32–0.61 here
  (median 0.38 ATM).
- **Noisy where the underlying moves between trades.** Plain Roll is undefined
  (positive covariance) in 9 of 33 ATM months. The **delta-adjusted** variant
  subtracts delta × the TLT minute-VWAP change first. It is our adaptation, and
  it is defined in 33/33 ATM months, 33/33 call-wing months and 32/33 put-wing
  months. **The direction of its bias is [U]** (corrected 2026-10-13; below).
- **A persistence-corrected version** divides by (1 − ρ̂). The tick rule gives a
  zero tick the previous sign, which overstates ρ, so the correction is **biased
  up**. It is used only inside the upper bound.

> **CORRECTED 2026-10-13.** The delta-adjusted bullet read "It removes noise,
> not bias", which implied the adjusted series shares plain Roll's downward
> persistence bias and nothing else. If so, it would scatter around plain Roll.
> It does not. In the months where both are defined, the adjusted estimate is
> above plain Roll in **20 of 24 ATM, 24 of 29 call-wing and 19 of 25 put-wing
> months**, with median ratios **1.36 / 1.11 / 1.25** [V, `g2_gate.py premium`,
> 2026-10-13].
>
> One candidate cause [U]: the minute VWAP stands in for TLT's price at the
> trade. The stand-in's error enters the price change with negative
> autocovariance, which Roll reads as spread. Persistence still pulls the
> estimate down, so the net direction is **[U]**.
>
> Plain Roll is now shown beside the adjusted series: a point cost of **2.05bp
> of S**, net **+16.8 %² (t 0.98)**, against the adjusted series' 2.57bp and
> +15.2 (§1.4). If the adjusted series is biased up, the upper bound built on
> it is more conservative, not less.

| leg bucket (2023-11..2026-07) | plain Roll median ($; months defined) | plain Roll median, bp of S | delta-adj. median ($) | delta-adj. median, bp of S | delta-adj. p90 ($) | corrected delta-adj. median, bp of S | corrected delta-adj. p90 ($) | corrected p90, bp of S |
|---|---|---|---|---|---|---|---|---|
| ATM | 0.0103 (24/33) | 1.18 | 0.0137 | 1.57 | 0.0265 | 2.54 | 0.0403 | 4.40 |
| call wing | 0.0076 (29/33) | 0.88 | 0.0092 | 1.02 | 0.0134 | 1.76 | 0.0241 | 2.57 |
| put wing | 0.0079 (25/33) | 0.86 | 0.0091 | 0.98 | 0.0110 | 1.78 | 0.0219 | 2.36 |

*Added 2026-10-13: the two plain-Roll and corrected-median bp columns, from
`g2_gate.py premium`. The dollar columns are from `g2_spreads.py roll`
(2026-10-12) and were not re-run.*

*Dollar columns are medians and percentiles of monthly dollar estimates. The
bp columns convert each month at that month's median TLT close and then take
the statistic, so they do not equal the dollar column divided by one price.*

**April 2025**, the month of the tariff-driven Treasury sell-off, is the widest
month on every leg: delta-adjusted $0.031 ATM and $0.035 on the wings.

### 1.3 Spread input (iii): free APIs with real quotes

**Nothing was signed up for.**

| source | real quotes? | history | what the team lead would have to do |
|---|---|---|---|
| **Theta Data, FREE tier** | Yes: the EOD report carries "the last NBBO reported by OPRA at the time of report generation" (17:15 ET), so **post-close**, an upper bound on regular-hours width [S] | "1 year of free historical EOD … data for US stocks and options" [V, docs]. The same page's table lists FREE first access as 2023-06-01; "bid/ask … may not be available prior to 2023-12-01" [S] | Create a Theta Data account; install and run the **Theta Terminal** (Java), which "must be running" to access any data [V]. Rate limit 20 or 30 requests a minute (the page contradicts itself). Whether a login is required is not stated on the docs page [U] |
| **Tradier developer sandbox** | Options "Delayed", "industry-standard 15 minutes"; Greeks "Not Available" in the sandbox [V, docs.tradier.com] | **None documented**: live delayed quotes only, so it serves forward confirmation, not a historical series | Open a Tradier account to get a sandbox token. The FAQ says "All Tradier Brokerage account holders can create a paper trading account" [V]; a 2019 launch article says no funded account is needed [S] |
| DoltHub `post-no-preference/options` (public SQL API, **no account**) | EOD bid/ask with greeks | from about 2019 for many names | **None. It has no TLT rows** on six dates sampled 2020–2026 (SPY is present) [V negative, queried 2026-10-12] |

No free source holds TLT option quotes for the 2004–22 fit period. The ruling's
"historical fit-period spread series" therefore cannot be built from free data.
2023+ spreads stand in as the forward cost, which is the cost a trade would pay.
**2004–22 spreads were probably wider.** TLT's quoting-increment history was
not checked [U].

### 1.4 The structure's cost and the net premium

**The structure** is Cboe's BFLY rule on TLT:

- short the monthly ATM put and call, long the 5%-OTM put and call;
- held to the next standard expiry [S, Cboe Insights].

**The conversion.**

- A cost in dollars becomes **bp of S** at the TLT price of the month it was
  measured in.
- It becomes **vol points** through the fly's net vega: Black–Scholes at
  σ = VXTLT_t and T = 30/365, at each fit date.
- It becomes **variance points** as 2·IV_t × the vol-point cost.

**The package-versus-legs gap is unmeasured.** A complex order may fill inside
the sum of the leg widths; nothing free measures that. Every row below prices
four separate legs.

**The upper bound was declared in `g2_gate.py` before the net table was
computed**, but after the leg tables above had been seen. The delta-adjusted
variant was added after plain Roll's undefined months had been seen. That is a
noise fix and selects no outcome. The plain-Roll row and the two relaxation
rows were added on 2026-10-13, after every result here had been seen, at an
independent reviewer's request. They change no declared rule: the gate still
reads the UPPER BOUND row.

The proxy is VXTLT 2004–22, the non-overlapping sample: IV dates
2004-01-02..2022-11-25, **n 227, every window ending by 2022-12-30** (the last
ends 2022-12-27). Gross: IV−RV **+1.265** vol pts (t 4.09); variance-swap proxy
**+23.1 %²** (t 1.33). All figures in this section are [V], re-run 2026-10-13
with `g2_gate.py premium`.

| cost rule (per cycle) | bp of S | vol pts | IV−RV net (t) | var-swap net %² (t) |
|---|---:|---:|---|---|
| gross | 0 | 0 | +1.265 (4.09) | +23.1 (1.33) |
| point, held to expiry: delta-adj. Roll median, half spread, entry only | 2.57 | 0.24 | +1.030 (3.35) | +15.2 (0.88) |
| *point, held to expiry: **plain** Roll median, half spread, entry only (added 2026-10-13)* | 2.05 | 0.19 | +1.078 (3.50) | +16.8 (0.98) |
| point, round trip: full effective spread | 5.15 | 0.47 | +0.794 (2.60) | +7.3 (0.43) |
| indicative median, held to expiry (half width) | 3.85 | 0.35 | +0.913 (2.98) | +11.3 (0.66) |
| indicative median, round trip (full width) | 7.70 | 0.70 | +0.562 (1.85) | −0.4 (−0.03) |
| **UPPER BOUND (declared)**: per leg the larger of indicative median and corrected-Roll p90, full width on all four legs | **13.74** | **1.26** | **+0.009 (0.03)** | **−18.9 (−1.12)** |
| *relax (1) only, the round trip: upper-bound widths, held to expiry (half width) (added 2026-10-13)* | 6.87 | 0.63 | +0.637 (2.09) | **+2.1 (0.12)** |
| *relax (2) only, the 90th percentile: per leg the larger of indicative median and corrected-Roll **median**, full width (added 2026-10-13)* | 8.81 | 0.81 | +0.459 (1.51) | **−3.8 (−0.23)** |
| stress: widest indicative quote seen, full width | 28.23 | 2.58 | −1.316 (−4.39) | −63.1 (−3.73) |

> **CORRECTED 2026-10-13.** Until today the main rows of this table were on
> n 228, IV dates to 2022-12-27, so the last window ran on January 2023 returns.
> They read:
>
> | row | IV−RV net (t) | var-swap net %² (t) |
> |---|---|---|
> | gross | +1.282 (4.16) | +24.0 (1.39) |
> | point | +1.046 (3.41) | +16.1 (0.94) |
> | point, round trip | +0.809 (2.66) | +8.1 (0.48) |
> | indicative, half | +0.929 (3.04) | +12.1 (0.71) |
> | indicative, full | +0.575 (1.90) | +0.3 (0.02) |
> | upper bound | +0.019 (0.06) | −18.4 (−1.09) |
> | stress | −1.313 (−4.40) | −63.1 (−3.75) |
>
> A "strict window" row (gross +23.1, upper bound −18.9) sat below them; it is
> now the whole table. The indicative full-width row changes sign, from +0.3 to
> −0.4, and is about 0 on either window.

**Robustness to the start phase** (added 2026-10-13). The t above takes start
phase 0 only. The review reported the gross t at 1.19 to 3.60 across the 21
phases on the old window, Newey–West(20) 2.36 (the review's figures; the old
window is no longer computed). Re-run on the strict window:

| var-swap proxy | t, phase 0 | t across 21 phases (median) | mean across phases, %² | Newey–West(20) t, overlapping daily (n 4,750) | sign across 21 phases |
|---|---|---|---|---|---|
| gross | 1.33 | 1.14 to 3.51 (1.66) | +19.4 to +34.5 | 2.33 | positive in 21 |
| net of the point cost | 0.88 | 0.69 to 2.58 (1.20) | +11.7 to +25.6 | 1.61 | positive in 21 |
| net of the upper bound | −1.12 | −1.69 to −0.93 (−1.22) | −21.4 to −12.6 | −1.48 | negative in 21 |

**The net sign does not depend on the phase.** The gross t is phase-sensitive:
the headline phase sits near the bottom of its range.

**Break-even structure cost:**

- IV−RV: 13.84bp of S, or 3.46bp per leg;
- variance-swap proxy: **7.55bp of S, or 1.89bp per leg**.

The declared upper bound (13.74bp) sits at the IV−RV break-even. It is 1.8×
the variance-swap break-even. *(Until 2026-10-13, on the old window: 13.95 / 3.49
and 7.78 / 1.94.)*

**The upper bound stacks three choices:**

1. **Round trip on all four legs.** The structure is declared held to expiry,
   when only the entry half-spread is paid, plus exercise handling on at most
   two legs.
2. **The 90th-percentile month**, not the median.
3. **A persistence correction biased up**, applied to a delta-adjusted series
   whose own bias direction is [U] (§1.2; corrected 2026-10-13 from "an
   estimator biased up").

The two relaxation rows show what (1) and (2) cost. Relaxing (1) alone takes
the net to about zero; relaxing (2) alone leaves it negative.

**The 5/15/30bp grid, translated (our translation).** The CEF grid charges a
one-way cost per unit of notional traded. Here that becomes a one-way cost of
5/15/30bp of the **underlying's** notional per leg: four legs, entry only, the
structure held to expiry.

| per leg, one way | bp of S | vol pts | IV−RV net (t) | var-swap net %² (t) |
|---|---:|---:|---|---|
| 5bp | 20 | 1.83 | −0.564 (−1.88) | −38.0 (−2.25) |
| 15bp | 60 | 5.49 | −4.221 | −160.1 |
| 30bp | 120 | 10.97 | −9.707 | −343.3 |

*Re-run 2026-10-13 on the strict window. Until then, on the old window: −0.557
(−1.86) / −37.7 (−2.25); −4.234 / −161.1; −9.751 / −346.3.*

- **The sign flips across the grid**, and already at its first step.
- The grid sits far above what TLT options cost. The measured one-way
  half-spread is about 0.6bp a leg, and the indicative half width about 1bp.
  Read the grid as a stock-cost scale that does not transfer to options, not
  as an estimate.

### 1.5 Why the proxy probably flatters the fly

VXTLT is a VIX-methodology strip that includes the OTM wings. On the 2023+
dates where both exist it sits about 1.46 pts **above** ATM IV. That is a level
gap, from `REPRO_TLT_VRP_2026-10-11.md` §1, and no return statistic.

An iron fly **sells** at the money and **buys** the wings. Its gross premium
per unit of net vega is therefore probably below the strip's. No free pre-2023
data can measure it: VXTLT is one number a day. This is one more reason not to
read the point-estimate rows as a pass.

## 2. G2(b): the bounded-loss replay

**Method** (`g2_gate.py replay`).

- **Cycles.** Monthly cycles run from one standard expiry to the next (the
  third Friday, or the session before it, e.g. Good Friday 2008-03-21 →
  03-20), on TLT's unadjusted closes. There are 226 cycles from 2004-02-20, and
  **only cycles settled by 2022-12-30 are counted**; the cycle entered
  2022-12-16 settles on a sealed 2023 close.
- **Zero credit.** A short fly owes min(|S_T − K₀|, 0.05·K₀) at expiry, so only
  TLT prices are needed.
- **Sizing** is set to `VOL_TARGET` = 0.06, read through `scripts/cef/spec.py`.
  The ex-ante annualised sd of the cycle's zero-credit P&L equals 6% of
  capital. Two declared vols are used, both from the session **before** entry
  (asserted, and tested):
  - **I**: VXTLT;
  - **R**: trailing 63-session realised vol, the window the live sleeve uses.
- **The cap** is 20%, from `docs/SYSTEM.md` §5. It is a required argument, not
  a default.

**Two path bounds** (corrected 2026-10-13). With zero credit, every cycle's
P&L lies in [−max(nW), 0]. Two bounds follow, one for each printed measure:

- **demeaned**: the population sd is at most max(nW)/2 (Popoviciu). The
  printed vol is a *sample* sd (ddof = 1), which can be larger by √(n/(n−1)).
  So the bound is **√12 · max(nW)/2 · √(n/(n−1))**;
- **not demeaned**: the rms is at most max(nW), so the bound is
  **√12 · max(nW)**. This one also holds with any credit.

| BFLY rule | window | cycles | vol (sd·√12) | not demeaned | bound, demeaned | bound, not demeaned | worst cycle | most at risk (nW) | contracts at $100k |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| sized on VXTLT | 2008 | 12 | **7.1%** | 12.9% | 10.1% | 19.2% | −5.56% | 5.56% | 11.1 |
| | 2008-09..2009-02 | 6 | 9.5% | 15.1% | 10.5% | 19.2% | −5.56% | 5.56% | 10.3 |
| | 2020 | 12 | **7.2%** | 11.7% | 11.6% | **22.2%** | −6.41% | 6.41% | 6.3 |
| | 2020-02..2020-04 | 3 | 10.5% | 16.6% | 13.6% | **22.2%** | −6.41% | 6.41% | 7.1 |
| | 2004–22 (fit) | 226 | 5.9% | 10.7% | 13.5% | **27.0%** | −6.41% | 7.79% | 9.5 |
| sized on trailing 63d RV | 2008 | 12 | 6.8% | 12.6% | 10.2% | 19.6% | −5.15% | 5.66% | 11.0 |
| | 2020 | 12 | 6.6% | 11.4% | 10.7% | **20.6%** | −5.48% | 5.94% | 6.8 |
| | 2004–22 (fit) | 226 | 6.0% | 10.9% | 14.0% | **28.0%** | −6.04% | 8.09% | 9.8 |

*[V], `g2_gate.py replay --vol-cap 0.20`, re-run 2026-10-13. The realised
columns are unchanged from 2026-10-12.*

**Every BFLY window is inside the 20% cap on the realised path**, demeaned and
not. The 6% target is hit on average: 5.9–6.0% over 2004–22. The demeaned
bound is inside for every window (at most 14.0%). **The not-demeaned bound is
not**: it exceeds 20% in 2020 on both sizings, and over 2004–22. So the realised
path passes, and **any-path safety is not established for the not-demeaned
measure.** The gate as written reads the replay, that is, the realised path.

> **CORRECTED 2026-10-13.** This section claimed one "any-path bound",
> √12 · max(nW)/2, and said every BFLY window was inside "on the bound". Its
> column read 9.6 / 9.6 / 11.1 / 11.1 / 13.5% (VXTLT sizing) and 9.8 / 10.3 /
> 14.0% (RV sizing). The Verdict said the fly "cannot breach 20% on any path".
> The review showed three errors:
>
> 1. **That bound is for a population sd.** The printed vol is a sample sd, which
>    can exceed it. CNDR sized on VXTLT in Feb–Apr 2020 printed a vol of 10.3%
>    against a "bound" of 10.2%.
> 2. **It does not bound the not-demeaned column at all.** That column is bounded
>    only by √12 · max(nW): 22.2% for BFLY in 2020 and 27.0% over 2004–22.
> 3. **"A range of exactly W whatever the credit C" holds per cycle only.** With
>    a credit that varies by cycle, different cycles' P&Ls do not share one
>    interval.
>
> The realised figures and the realised-path verdict do not change.

**The worst cycle** was entered 2020-03-20 (TLT 159.43 → 167.81, beyond the
wing): −6.41% of capital, the full wing.

**The second published rule, Cboe's CNDR** (short about 0.20-delta, long about
0.05-delta, deltas at VXTLT), is replayed so that a pre-registration cannot
choose it later without this on record.

- **Sized on VXTLT, it is inside on the realised path**: 2008 5.7%, 2020 6.9%.
  The demeaned bound is at most 12.4% (Feb–Apr 2020, where the realised 10.3%
  had exceeded the old "bound" of 10.2%). The not-demeaned bound is 20.3% in
  2020.
- **Sized on trailing RV, its bounds breach: demeaned 48.8% in 2008 and 22.0%
  in 2020** (not demeaned: 93.5% and 42.1%). The cycle entered 2008-09-19 had
  VXTLT 28.1% against a trailing RV of 12.6%. Its strikes were set wide by the
  high VXTLT, while its size came from the low RV, which put **27% of capital**
  at risk in one cycle. The path did not hit it, so realised vol stayed inside
  (8.0%). **A condor sized on trailing realised vol is not cap-safe by
  construction.**

*Corrected 2026-10-13: these bullets read "bound ≤ 10.2%" and "46.8% in 2008
and 21.0% in 2020", the old single bound. The 2008-09-19 figures were not
re-derived.*

**What the vol test does not see.**

- **Repeated full-wing losses look like low vol.** The fly lost the whole wing
  in four consecutive cycles (Oct 2008 – Jan 2009) and three (Jan – Mar 2020).
  Equal losses have a small sd, which is why the not-demeaned column is shown.
- **Zero-credit cumulative loss** is a bound that ignores all premium income:
  −37.9% in 2008 and −32.9% in 2020. That is above the spec's
  `risk.kill_drawdown` (0.18), but it is not a drawdown estimate.
- **A labelled model cross-check.** It marks the fly daily at Black–Scholes
  with flat vol = that day's VXTLT: no skew, European, *with* model credit. It
  gives daily-P&L vol of 7.5% (2008), 6.8% (2020) and 9.9% (Feb–Apr 2020), and
  maximum drawdowns of −5.9% and −6.1%. Flat vol misprices crash wings, so this
  is a second look, not the gate. It no longer substitutes the entry vol for a
  missing VXTLT: it raises (corrected 2026-10-13; the substitute was dormant,
  and the figures are unchanged).
- **Assignment at expiry, which the replay settles in cash** (added 2026-10-13).
  TLT options settle in shares [U; Gaps]. When 0.95·K₀ < S_T < 1.05·K₀ and
  S_T ≠ K₀, one short ATM leg is in the money and its wing is not. Each fly
  then becomes 100 shares: short if the call is assigned, long if the put is.
  That stock is held from Friday's close until it can be traded out.
  - In the replay this happens in **189 of 226 cycles** (short 91, long 98).
  - The stock left is a **median 106% of capital (maximum 150%)** on VXTLT
    sizing, and 108% (166%) on RV sizing. That is about $106k of TLT at $100k
    of capital, carried over a weekend.
  - It is not in the replay P&L, and not in the entry-only cost.

  [V], `g2_gate.py replay`, 2026-10-13.
- **Also unseen:**
  - early assignment of a short American leg (TLT distributes monthly);
  - pin risk;
  - the integer contract count at $100k (6–11 flies).

## 3. G2(c): correlation with the book

`book_vs_shortvol.py` was re-run on 2026-10-12, and again on 2026-10-13 after
the holdout correction. The panel was the 2026-10-12 VXTLT fetch plus
`data/gamma`'s VXHYG. The book is the v7 band at 0.048, gross-capped at 1.8, on
total returns, `shift(2)`. The first three rows are identical to
`REPRO_TLT_VRP_2026-10-11.md` §2. The fourth now stops before 2023:

| construction (2013-06-21..2022-12-30) | ρ [95% CI] |
|---|---|
| daily short-variance leg | −0.008 [−0.048, +0.032] (n 2,396) |
| 21-session blocks | −0.109 [−0.288, +0.076] (n 114) |
| calendar months | −0.102 (n 114) |
| short 30d variance swap vs book over t+1..t+21, every window ending by 2022-12-30 | **−0.131 [−0.307, +0.054] (n 114**; IV dates 2013-06-21..2022-11-29, last window ends 2022-12-29) |

**Every interval includes 0.** [V], re-run 2026-10-13.

> **CORRECTED 2026-10-13.** The fourth row read −0.134 [−0.310, +0.050]
> (n 115). The script filtered only the IV date t ≤ 2022-12-31, so its last
> window ran to 2023-01-31. Now it keeps only windows whose last session is on
> or before 2022-12-30, and it refuses a bound in 2023+.
>
> This paragraph also read: "The script also prints 2023+ rows. They are return
> statistics, sealed under the 2026-10-12 ruling, and are **not quoted here**."
> They were not quoted, but they were printed and seen on 2026-10-12. That is a
> touch of the sealed holdout, recorded at the top of this note and in
> `docs/RESEARCH_STATE.md`. Since 2026-10-13 the script prints no 2023+ row.

## 4. What would change the answer

| question | free route | what it changes |
|---|---|---|
| **The true width** (the trade-based term dominates the upper bound on every leg) | **Theta Data's free EOD NBBO** (team lead: create an account and run the Theta Terminal; about a year of history, post-close) | It replaces a trade-based estimator with a quoted NBBO. On the 2026-10-12 indicative widths, a full-width round trip nets **−0.4 %²** (t −0.03) and a half-width entry **+11.3 %²**. So even a real NBBO leaves (a) near zero under a round-trip charge |
| **The convention** (round trip vs held to expiry) | none: a ruling | Charged at entry only, the proxy is positive at every measured width: +11.3 to +16.8 %², and +2.1 at the upper-bound widths. It is negative only on the stress row. **This is the only convention whose relaxation flips the sign** (§1.4) |
| **The premium itself** | none free before 2023 | The gross proxy is t 1.33 in variance terms (1.14 to 3.51 across start phases; Newey–West(20) 2.33). No cost result can make it significant |

*Corrected 2026-10-13 to the strict window. This table read +0.3 (t 0.02) and
+12.1, "+12.1 to +16.1 %²", and t 1.39.*
| **Forward confirmation** | Tradier sandbox (account needed): 15-minute-delayed real quotes in regular hours | Confirmation only, as the ruling says |

**The single additional free source most likely to settle the data half of
(a) is Theta Data's free tier**, which needs the team lead to open an account
and run the Theta Terminal. The convention half is a ruling.

## 5. Graveyard

This is not W14-A or G6.

- **W14-A** asked whether the **book** is short volatility in a way a **hedging
  option** could fix. It found no, and a hedge overlay was closed.
- **G6** asked whether **long credit (HYG) gamma** could be **timed** by a
  conditioner. It found no.
- **G1 is untimed, standalone, short the premium, on rates (TLT).** It has no
  hedge role and no conditioner. G6's finding that long gamma costs more in
  variance than it earns is the premium's existence seen from the other side.
- G2(c) confirms TLT's leg is uncorrelated with the book. HYG's is not (daily
  +0.091 [+0.042, +0.140]), which is why HYG stays parked.
- **The graveyard's most common cause of death**, a stale-price artefact, does
  not apply: the premium is IV against forward realised returns on
  exchange-traded closes, and the replay uses closes only.

## Gaps

- **There is no regular-hours NBBO** for any TLT option leg, at any date, from
  a free source.
- **The package-versus-legs fill gap** is unmeasured.
- **The R2 condition-code map is [U]** (as in `tlt_atm_iv.py`).
- **R2 misses month-end sessions** in 21 of 32 complete months.
- **The indicative feed's construction is undocumented** beyond "derivative".
  Venue codes vary between snapshots [U].
- ~~**`book_vs_shortvol.py` prints sealed 2023+ rows**, labelled. It should
  stop doing so under the 2026-10-12 ruling.~~ **Closed 2026-10-13**: it no
  longer prints them, and its second method no longer runs a window into 2023.
  They were printed and seen once, on 2026-10-12 (top of this note).
- **The replay ignores** early assignment, pin risk, integer contracts and
  daily marks, apart from the labelled model cross-check.
- **Physical settlement is not in the replay or the cost** [U] (added
  2026-10-13). TLT options are American and settle in shares; this was not
  re-read from the OCC or Cboe contract specification.
  - An expiry between the wings leaves ±100 shares per fly (§2). In the replay
    that is 189 of 226 cycles, a median 106% of capital in TLT stock over a
    weekend.
  - It is charged nowhere: not the weekend gap, not the stock spread to unwind,
    not the margin.
  - How Alpaca handles expiry is also [U]: automatic exercise, any
    do-not-exercise or close-out practice, and whether paper simulates
    assignment at all.
- **Alpaca's options trading level and multi-leg orders on the paper account
  are unsourced** [U] (added 2026-10-13).
  - Unknown whether the paper account is approved at the level a short iron
    fly needs.
  - Unknown whether a four-leg order can be sent as one package or must go
    as legs.
  - The package-versus-legs fill gap (above) depends on the second.
- **No fly-specific premium** (ATM sold against wings bought) is measurable
  before 2023.
