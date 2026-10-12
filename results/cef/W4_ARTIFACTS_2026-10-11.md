# W4 — the artifact battery on the deployed signal — 2026-10-11

**Report only. Spends no trial (CEF counter stays 50). Changes no spec, no
harness default and nothing on the live path.** Item 0.6 of
`results/cef/RESEARCH_PLAN_2026-10-09.md`. The questions are the archived work
order (`git show pre-clean-slate:_archive/docs/prompts/W4_artifact_battery.md`)
plus a factor attribution.

**What it measures.** The signal the book trades: the frozen spec
`cef_discount.v7.20260928` — 13 names, `z_window` 252, the ADV filter,
`min_names`, the 4.8% band and the 1.80× gross ceiling — read through
`scripts/cef/spec.py`. It measures how much of that signal's information
coefficient (IC) and P&L survive five mechanical explanations. It tests no new
signal. Where a section rebuilds the discount another way (on the quote
midpoint, on the auction print, with the stale part of the NAV removed), only an
IC is reported. That is a decomposition, not a candidate.

**Reproduce every figure:**

```bash
python3 scripts/data/stage_crsp_w4.py                 # CRSP rows, 2004–2022 (R2 mirror)
python3 scripts/data/fetch_ff_factors.py --check-r2   # Ken French FF5 + momentum
python3 scripts/data/fetch_pastor_liquidity.py --check-r2
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py
python3 scripts/cef/w4_artifacts.py                   # the battery; ~25s, offline
```

The output of the run behind this note is `results/cef/w4/w4_artifacts_output.txt`.
Each section below names its block there (§0 … §6). Every figure in this note is
**[V]**: measured this session by that script. Literature claims carry their own
label.

**Panels** (read-only):

- `data/cef/cef_prices.parquet`: last date 2026-09-28.
- `data/cef/cef_nav.parquet`: last date 2026-09-25.
- `data/cef/cef_distributions.parquet`: last ex-date 2026-09-10.
- **Only 2005-01-03 → 2022-12-30 is used** (4,531 sessions).
- CRSP rows: staged to 2022-12-30.
- Alpaca auction prints: 2016-01-04 → 2022-12-30.
- Ken French factors: the 202608 CRSP vintage, daily to 2026-08-31, fetched
  2026-10-11.
- Pástor–Stambaugh: to 2025-12.

**Holdouts.** The 2023-01-01 time holdout is sealed: every frame is truncated
before anything is computed, `_assert_fit` checks each frame that reaches a
statistic, and the CRSP and Alpaca fetches stop at 2022-12-31. No name from the
untouched CEF set is read. The one context row that reads the four names v7
dropped (NAD, NEA, NVG, NZF) consumes nothing: they were deployed until
2026-09-28 and were never part of the untouched set.

**Conventions.** P&L comes only from `evaluate()` (`shift(2)`: decide *t*, MOC
fill at close *t+1*, earn *t+2*). The deployed policy is
`band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)`.

- **IC (H6).** Spearman between z at *t* and the return from close *t+1* to
  close *t+3*. It is computed on a non-overlapping grid (every second session),
  with at least `min_names` names; phase 0 is the headline and phase 1 the other
  half.
- **The deployed set** on date *t* is the names with a z-score and 63-day ADV
  through *t−1* of at least `min_adv_usd`, on dates with at least `min_names`
  of them. These are exactly the rows `build_targets` acts on.
- **The wide set** is every name with a z-score, without the ADV filter. It is
  reported only as context, labelled, because it is the only way to see
  2005–12. **It is not the deployed signal.**
- **P&L tables.** Gross Sharpe is the headline. The net figures at 5/15/30bp
  per unit of turnover sit beside it as the labelled real-money view. No borrow
  is charged anywhere. "flips?" is YES if gross, 5, 15 and 30bp do not all
  share a sign.

---

## The verdict

**None of the five mechanical artifacts explains a material share of the
deployed IC.** The deployed 13-name signal's IC at the traded 2-day horizon is
**−0.033 (t −1.68)** on 523 non-overlapping dates. On the other half of the
grid it is −0.039 (t −1.97). After removing each candidate artifact it is:

| artifact removed | IC |
|---|---:|
| bounce: quote midpoint for both the signal and the return | −0.031 |
| the stale part of the NAV | −0.032 (on its own sample, where z itself measures −0.031) |
| ex-date-touched name-days | −0.043 |
| crisis windows | −0.032 |

The part that survives is the thing the book trades: a price move against the
discount, mostly within two to three sessions. It is not a NAV catch-up, not a
spread artifact and not a distribution artifact.

**The finding that matters is not an artifact. It is the baseline.**
`docs/BRIEF.md` quotes IC −0.074 (t −11.6) [S, 2026-09-05]. That figure
reproduces on the fit period only for the **17-name v6 universe without the ADV
filter** (−0.078, t −11.1). The signal the book actually trades is weaker:

- **13 names with the ADV filter: −0.033 (t −1.7).** It first trades on
  2013-06-21 and has 1,047 decision dates before 2023.
- It is **not significant in any single era**.
- **Half of its summed IC comes from December–January signal dates.**

Its P&L is more significant than its rank IC: the factor alpha t is 2.9–3.2,
because the book weights by z rather than by rank. Even so, every later
"incremental to the z-score" claim should be measured against **−0.033 (rank)
or −12.8bp of 2-day return per unit z (slope, t −2.55)**, not against −0.074.

---

## Summary — the six measurements

Every figure is [V], from `scripts/cef/w4_artifacts.py`, run 2026-10-11, on the
fit period 2005-01-03 → 2022-12-30. The book is flat before 2013-06-25. P&L
rows labelled "fit" follow the harness convention and include those flat
sessions, which dilutes them. Rows labelled "live" start at the first position:
the deployed book's live gross SR is **0.96** (6.21%/yr, turnover 13.5/yr)
against 0.69 on the diluted fit row.

| # | measurement | headline | does it suggest the IC is an artifact? |
|---|---|---|---|
| 1 | **Total-return panel** (§1) | Distributions: yfinance panel, 2,318 of CRSP's 2,329 distribution days matched; panel total return vs CRSP `ret` median gap 0.003bp. Deployed gross SR **0.69 total vs 0.70 price** (live: 0.96 vs 0.96; CRSP `ret`: 0.70). Distribution leg **−11bp/yr** (sd 113bp/yr; eras −70 / +66 / −61bp/yr) | **No.** IC −0.0329 total vs −0.0313 price |
| 2 | **Bid–ask bounce** (§2) | IC on the quote midpoint, signal and return, **−0.0314 vs −0.0329** (≈5% lower). The bounce part of z has sd 0.04 against z's 1.32, and IC −0.0003. The panel close equals the NYSE closing-auction print on 96.6% of name-days, and the auction-price IC is −0.042 vs −0.037 on the same sample. Skipping a day costs **17–19% of gross SR** (0.69 → 0.57; live 0.96 → 0.78): that is signal decay, not bounce | **No.** At most ~5% of the IC |
| 3 | **Stale-NAV catch-up** (§3) | NAVs are stale in every group: NAV AC(1) +0.26 to +0.54; 44–56% of a proxy move reaches the NAV only on later days. But in the traded window the discount closes **98% through price** (price −12.3bp per unit z, NAV +0.2bp). The stale part of z has IC −0.016 / +0.011, and z without it keeps −0.032 / −0.041 (with 10 lags: +0.004 and −0.035) | **No** at the traded horizon. Over a month, 83% of discount closure is NAV, which the book never earns |
| 4 | **Where the IC lives** (§4) | Ex-dates: removing name-days touched by an ex-date gives **−0.043** (stronger). Crises: outside every window **−0.032**. **Turn of year: Dec–Jan −0.093 vs Feb–Nov −0.019 (t −0.9)**, so Dec–Jan dates (18% of dates) carry 52% of the summed IC. Volatility: concentrated in the top two quintiles. Eras: −0.022 / −0.014 / −0.057, none significant alone | **Partly.** A seasonal and volatility concentration, not a mechanical artifact. Year-end special distributions carry 18–29% of the deployed IC (§4a) |
| 5 | **P&L split** (§5) | Discount leg **+3.82%/yr** (gross SR 0.77; live +7.21%/yr, SR 1.06); NAV leg **−0.53%/yr** (SR −0.41; live −1.00%/yr); total +3.29%/yr (live +6.21%/yr). The discount leg is 116% of the total in the fit period and positive in every era | **No.** The book earns from the discount closing in price; its NAV exposure costs it |
| 6 | **Factor attribution** (§6) | FF5 + UMD, daily, 2013-06 → 2022: alpha **6.0%/yr, t 2.94**, every \|β\| ≤ 0.021, R² 0.004. Monthly with Pástor–Stambaugh LIQ_V: alpha 6.4%/yr, **t 3.22**, \|β_liq\| 0.037. At the cost grid: t 2.62 / 1.96 / 0.97 (daily, 5 / 15 / 30bp). Sadka: **not fetchable; stopped** | **Not beta.** D4 (alpha t ≥ 3.0, \|β\| ≤ 0.10): betas pass; gross alpha t is on the bar (2.94 daily, 3.08 Dimson, 3.22 monthly) and below it net of any cost |

---

## 0. The baseline: the deployed IC and its standard errors (§0)

Forward window: close *t+1* → close *t+3*. Total returns unless stated.

| set | returns | phase 0: dates, IC, t | phase 1: dates, IC, t |
|---|---|---|---|
| **DEPLOYED** | total | **523, −0.0329, −1.68** | 520, −0.0389, −1.97 |
| DEPLOYED | price | 523, −0.0313, −1.61 | 520, −0.0443, −2.22 |
| DEPLOYED | CRSP `ret` (second source) | 523, −0.0320, −1.63 | 520, −0.0381, −1.93 |
| WIDE (context) | total | 2,264, −0.0604, −7.80 | 2,263, −0.0617, −7.83 |
| v6 17 names, ADV filter (context) | price | 1,059, −0.0553, −4.34 | — |
| v6 17 names, WIDE (context) | price | 2,264, **−0.0777, −11.05** | — |

The last row is the BRIEF's −0.074 (t −11.6), reproduced on 2005–22. **The gap
between it and the deployed −0.033 is the universe and the ADV filter, not an
artifact.** Dropping the four munis costs about a fifth of the wide IC
(−0.078 → −0.064, both on price returns). The ADV filter removes 2005 → mid-2013 entirely and halves
it again.

**By era** (DEPLOYED, phase 0; with the Fama–MacBeth slope in bp of 2-day return
per unit z):

| era | dates | IC | t | t (NW) | slope bp/z | t |
|---|---:|---:|---:|---:|---:|---:|
| 2005–09 | 0 | — | — | — | — | — |
| 2010–14 (from 2013-06) | 138 | −0.0216 | −0.55 | −0.49 | −3.0 | −0.78 |
| 2015–19 | 176 | −0.0137 | −0.38 | −0.34 | −11.6 | −1.24 |
| 2020–22 | 209 | −0.0565 | −1.99 | −2.22 | −20.3 | −2.15 |
| fit 2005–22 | 523 | **−0.0329** | −1.68 | −1.60 | **−12.8** | **−2.55** |

On the wide set the IC is −0.050 / −0.093 / −0.036 / −0.064 by era, all with
|t| ≥ 2.6. The brief's "present in every sub-period" is true of the wide set. It
is **not shown for the deployed set**, whose eras are 1.5–4 years long and none
of which is individually significant.

**Standard errors (work-order Part E).** The same data, one estimate, several
standard errors:

| estimate | method | t |
|---|---|---:|
| mean IC −0.0329 | one IC per date (date-clustered) | −1.68 |
| | Newey–West (5) | −1.60 |
| | moving-block bootstrap (20 dates, 2,000 reps); 95% CI [−0.073, +0.015] | −1.45 |
| pooled slope −6.74bp per unit z, 3,458 name-dates | naive iid (dof n−1−523, the date means absorbed) | −2.74 |
| | clustered by date, G/(G−1); 5% critical value 1.96 | −2.92 |
| | clustered by name, 12 clusters, G/(G−1); **5% critical value t(11) = 2.20** | −2.26 |
| | two-way, date × name; **5% critical value t(11) = 2.20** | **−2.10** |

All windows are non-overlapping. The small-sample corrections (residual
degrees of freedom, G/(G−1), a t(G−1) reference for 12 name clusters) were added
after an independent code review on 2026-10-11; the first run printed
−2.98 / −2.92 / −2.36 / −2.19 without them.

**The rank IC and the linear slope disagree on significance.** The rank IC has
t ≈ −1.7. The slope is significant clustered by date (−2.92) but **not at 5%
two-way** (−2.10 against 2.20), and only just by name. The book's weights are
linear in z, so the slope is the closer analogue of what it earns. Both are
reported; neither is preferred silently. On any of them the deployed signal's
2-day predictive content is marginal on its own.

## 1. The total-return panel (§1)

**Where distributions come from.** `data/cef/cef_distributions.parquet` comes
from yfinance `Ticker.actions` (`scripts/fetch_cef_distributions.py`). The
harness adds them with `total_returns()`: *r* = (1+*r*ₚₓ)·*k* − 1 + *D*/*P*ₜ₋₁ on
the ex-date. It raises if an ex-date fails to reach the yield matrix. There are
no splits before 2023 on these names.

**How complete they are**, checked against CRSP (an independent source,
`ret − retx` on each day) over 2005–22 on name-days both sources price:

- **2,318 of CRSP's 2,329 distribution days match** a panel ex-date, with a
  median yield gap of 0.00–1.8bp by name.
- **11 CRSP distributions are missing from the panel.** Three are large
  year-end specials: PFN 2012-12-26 (≈432bp of price), PTY 2011-12-28 (≈374bp)
  and PCN 2012-12-26 (≈119bp). The rest are 24–80bp, mostly in 2005.
- **8 panel ex-dates have no CRSP distribution.** Four are capital-gain
  specials that CRSP books inside `retx`, so the two sources' total returns
  agree to the basis point. Four (AWF 2007-12-05, BIT 2016-12-08,
  BIT 2017-12-11, PHK 2005-12-21) are panel distributions CRSP does not show
  on that day.
- **The panel's total return against CRSP `ret`**: median gap 0.003bp, p99
  2.98bp, more than 5bp on 0.26% of 48,237 name-days.
- The gaps do not move the deployed P&L: on CRSP `ret` the table below
  matches the panel to two decimals.

**What total returns move** (deployed policy):

| convention | era | gross SR | ann % | vol % | turn/yr | net@5 | net@15 | net@30 | flips? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| price | 2010–14 | 0.90 | 2.94 | 3.27 | 5.2 | 0.82 | 0.66 | 0.43 | no |
| price | 2015–19 | 0.72 | 5.04 | 7.01 | 7.8 | 0.66 | 0.55 | 0.39 | no |
| price | 2020–22 | 1.08 | 7.10 | 6.55 | 21.5 | 0.92 | 0.59 | 0.10 | no |
| price | **fit** | **0.70** | 3.40 | 4.88 | 7.2 | 0.62 | 0.48 | 0.26 | no |
| **total** | 2010–14 | 0.72 | 2.24 | 3.12 | 5.2 | 0.63 | 0.47 | 0.22 | no |
| **total** | 2015–19 | 0.84 | 5.70 | 6.83 | 7.8 | 0.78 | 0.66 | 0.49 | no |
| **total** | 2020–22 | 1.02 | 6.49 | 6.36 | 21.5 | 0.85 | 0.51 | 0.01 | no |
| **total** | **fit** | **0.69** | 3.29 | 4.73 | 7.2 | 0.62 | 0.47 | 0.24 | no |
| total, CRSP `ret` | fit | 0.70 | 3.29 | 4.73 | 7.2 | 0.62 | 0.47 | 0.24 | no |
| price | live 2013-06 → 2014 | 1.63 | 9.64 | 5.91 | 16.3 | 1.49 | 1.22 | 0.80 | no |
| price | **live 2013-06 → 2022** | **0.96** | 6.43 | 6.70 | 13.5 | 0.86 | 0.66 | 0.36 | no |
| total | live 2013-06 → 2014 | 1.30 | 7.33 | 5.65 | 16.3 | 1.15 | 0.86 | 0.43 | no |
| total | **live 2013-06 → 2022** | **0.96** | 6.21 | 6.50 | 13.5 | 0.85 | 0.64 | 0.33 | no |

Era turnover sd/mean is 62% across the three eras that have a book, but that is
mostly the flat sessions diluting 2010–14. With 2010–14 on live sessions only it
is **37%**.

The distribution leg (total minus price P&L, on the deployed holdings path)
averages **−11bp/yr** with sd 113bp/yr. By era it is −70.5, +66.5 and −61.4bp/yr.
The earlier 17-name estimate (−0.01%/yr, sd 1.23%/yr, `docs/REFERENCES.md` §9,
2026-09-09) was a different book and window; the two agree in kind. **The legs'
yields roughly net out. In any one era the term is the size of the 15bp cost
line, and its sign alternates.** Nothing flips sign across the grid in any
convention. 2020–22 sits at +0.01 at 30bp on total returns.

**Ex-date arithmetic: a correction to `docs/BRIEF.md` §3.** The brief predicts
the discount changes on the ex-date by *d*·*D*/(*N*−*D*), about +0.05pp on
average here, and that the price falls slightly less than the distribution
(Bali & Hite 1998, [S]). Measured on 2,326 ex-dates:

- the discount **falls 0.167pp** on the ex-date (median −0.081pp), against
  +0.008pp on other days;
- it keeps falling, **−0.306pp on the next session** (median −0.169pp) and
  −0.197pp on the one after;
- the price drops **1.04×** the distribution (median), the NAV 0.92×.

So prices of these funds keep falling for two sessions after the ex-date, by
more than the cash. The slope of the ex-date change on the arithmetic term is
−0.26, not +1. **This is a post-ex-date price pattern, not arithmetic.** It is
recorded as a measured observation and is not tested as a signal here.

## 2. Bid–ask bounce (§2)

**IC by single forward day** (DEPLOYED, every session, Newey–West t):

| day | t+1 (infeasible) | t+2 | t+3 | t+4 | t+5 | t+6 |
|---|---:|---:|---:|---:|---:|---:|
| IC | **−0.042** | −0.023 | −0.012 | −0.000 | +0.004 | +0.010 |
| t (NW) | −3.00 | −1.58 | −0.88 | −0.01 | 0.28 | 0.73 |

**Two-day windows** (phase 0 / phase 1):

| window | entry | IC |
|---|---|---|
| [t+1, t+2] | close t (infeasible) | −0.067 / −0.052 |
| **[t+2, t+3]** | **close t+1 (deployed)** | **−0.033 / −0.039** |
| [t+3, t+4] | close t+2 (skip a day) | −0.029 / −0.012 |

**Skip-a-day P&L.** The same book filled one session later (`evaluate(H.shift(1), R)`, total returns):

| era | gross SR | ann % | turn/yr | net@5 | net@15 | net@30 | flips? |
|---|---:|---:|---:|---:|---:|---:|---|
| 2010–14 | 0.50 | 1.57 | 5.0 | 0.42 | 0.26 | 0.02 | no |
| 2015–19 | 0.77 | 5.27 | 8.0 | 0.71 | 0.60 | 0.42 | no |
| 2020–22 | 0.76 | 5.04 | 21.4 | 0.60 | 0.27 | **−0.21** | **YES** |
| **fit** | **0.57** | 2.74 | 7.2 | 0.50 | 0.35 | 0.12 | no |

On live sessions (2013-06 → 2022) skip-a-day is 0.78 / 0.68 / 0.48 / 0.17,
against the deployed 0.96 / 0.85 / 0.64 / 0.33. The deployed book's fit figures
are 0.69 / 0.62 / 0.47 / 0.24. One more day of delay costs 17–19% of gross SR,
and 2020–22 flips at 30bp.

**Quote midpoint.** The closing bid and ask come from CRSP and exist on 100% of
the name-days the panel prices. The common sample is the same DEPLOYED dates
and names throughout:

| signal / forward return | IC | t |
|---|---:|---:|
| z(close) / close-to-close (deployed) | −0.0329 | −1.68 |
| z(close) / mid-to-mid | −0.0315 | −1.61 |
| z(mid) / close-to-close | −0.0325 | −1.66 |
| **z(mid) / mid-to-mid (no bounce anywhere)** | **−0.0314** | −1.61 |
| infeasible [t+1,t+2]: z(close) / close | −0.0672 | −3.42 |
| infeasible [t+1,t+2]: **z(mid) / mid** | **−0.0639** | −3.27 |
| the bounce part alone, z(close) − z(mid) | −0.0003 | −0.02 |

On the wide set the midpoint IC tracks the close IC in every era (fit −0.0594
vs −0.0604).

**The closing auction.** Alpaca SIP, NYSE prints, 2016–22:

- a print exists on 94.3% of panel name-days;
- the panel close equals it within $0.005 on **96.6%** of them (median gap
  where not: 10.8bp);
- IC on auction prices for both signal and return is −0.042 / −0.051, against
  −0.037 / −0.050 on closes, on the identical 273-date sample.

**Spreads.** Median quoted half-spreads on deployed name-days are 4–12bp (CRSP);
Corwin–Schultz gives 0.5–16bp, with corr 0.64 across names. The cross-section of
12 per-name ICs on half-spread has slope −0.0002 per bp (t −0.05) on quoted
spreads and −0.0023 (t −0.93) on Corwin–Schultz. Bounce would make the IC most
negative where spreads are widest. **It does not.** Daily return AR(1) is
negative for most names on closes, and almost as negative on midpoints, so the
reversal is not bounce.

**Bounce is at most ~5% of the IC, in the signal or in the return.** The
striking number is a different one: **the largest single-day IC is on day t+1,
the day no book decided at t can earn**, and it survives on midpoints (−0.064
vs −0.067). Half the signal's two-day predictive content is gone before the
first possible fill. That is a TC problem (the NAV arrives after the close), not
an artifact.

## 3. Stale-NAV catch-up (§3)

**NAV staleness exists, in every group** (2005–22):

| group | names | NAV AC(1) [block-bootstrap 95%] | lag-sum / total proxy loading |
|---|---|---|---:|
| muni | MHD, MQY | +0.538 [+0.433, +0.561] | 0.55 |
| loan | JFR | +0.444 [+0.322, +0.534] | 0.44 |
| hy | AWF, HYT | +0.333 [+0.206, +0.396] | 0.53 |
| multi | 8 names | +0.263 [+0.148, +0.353] | 0.56 |

Price AC(1) is −0.12 to +0.10 for every name. The lead–lag regressions put
each NAV's total return on its proxies at lags 0–3, from CRSP: MUB (muni), HYG
(hy), BKLN (loan), HYG and LQD (multi), with HAC(5). Every name has a
significant lag sum, t 3.7 to 12.3. The ordering the brief predicted (muni >
loan > multi > hy) holds for muni and loan only: HY is not the clean negative
control it was meant to be, because HY CEF NAVs also lag HYG. Two NAVs look
noisy rather than stale: PCN has AC(1) −0.08 and PFN +0.06, with an unchanged
NAV on 28% of PFN's sessions.

**But the traded window does not earn the catch-up.** The forward change in the
discount per unit z (Fama–MacBeth, DEPLOYED, log total returns) splits exactly
into a price leg and a NAV leg:

| window | price bp (t) | NAV bp (t) | discount bp (t) | price share |
|---|---:|---:|---:|---:|
| t+1 only (unearned) | −8.6 (−3.9) | +0.9 (1.0) | −9.5 (−5.3) | 0.91 |
| **[t+2, t+3] deployed** | **−12.3 (−2.6)** | **+0.2 (0.1)** | −12.5 (−3.1) | **0.98** |
| [t+2, t+6] | −12.6 (−1.6) | −1.5 (−0.2) | −11.0 (−1.0) | 1.14 |
| [t+2, t+11] | −42.9 (−1.9) | −19.3 (−0.6) | −23.6 (−1.1) | 1.82 |
| [t+2, t+22] | −9.0 (−0.4) | **+43.8 (2.9)** | −52.7 (−2.0) | 0.17 |

- At the traded horizon the discount closes through price: 98%.
- **Over a month, 83% of the discount closure is the NAV catching up**, which a
  price book never earns.
- IC of z against the forward NAV return over [t+2, t+3] is +0.036 (t 1.76),
  the catch-up sign, but small.

**The decisive split.** For each name, a lead–lag model is refitted every
January on data strictly before it. It gives the NAV move still owed at *t*
from proxy moves already seen. In z units that is the "stale part" of z. On the
common sample (about 318 grid dates per phase):

| | IC phase 0 | IC phase 1 |
|---|---:|---:|
| z (deployed) | −0.031 | −0.043 |
| the stale part of z | −0.016 | +0.011 |
| **z minus its stale part** | **−0.032** | **−0.041** |

The stale part has sd 0.14 z against z's 1.34 (corr +0.21). In a regression on
both, z keeps −20.2bp per unit (t −2.24) and the stale part is insignificant
(t −0.59).

**That size is a lower bound.** The model stops at three lags while NAV AC(3)
is still 0.15–0.36 for most names, and it captures only the staleness the
proxies explain (R² 0.15 for PCN and PFN). With lags 0–10, a sensitivity from
which nothing is chosen, the stale part's sd doubles to 0.29 z. Its IC is
+0.004 (t 0.16), and z minus it is −0.035 (t −1.39), against −0.031 for z on
the same sample. **On either length, none of the deployed IC is stale-NAV
catch-up.**

**Bond-market holidays.** Columbus and Veterans Day (observed on Monday when
the 11th is a Sunday) fall on NYSE sessions 34 times in 2005–22. The first run
missed the three Sunday-observed Veterans Days; the review caught it.

- The NAV is unchanged on 42% of name-days on those days, against 17.5%
  otherwise.
- The absolute discount change is 1.17pp against 0.71pp.
- The change partly persists into the next session (corr +0.14); it does not
  reverse.
- Dropping those days and the next session moves the every-session IC from
  −0.036 to −0.034.

They are a real NAV artifact, but too rare to matter to the IC. **No panel rule
is proposed**, because it would be a change under `data/` and that is the team
lead's call (`docs/DATA.md` §6).

## 4. Where the IC lives (§4)

**Ex-dates.** 18.8% of deployed name-days have an ex-date somewhere in
*t*…*t+3*.

| set | all name-days | untouched only |
|---|---:|---:|
| DEPLOYED | −0.033 | **−0.043** (t −1.92) |
| WIDE | −0.060 | −0.058 (t −6.37) |

Removing touched name-days does not weaken the IC. The pooled slope is −3.3bp
per unit z (t −0.62) on touched name-days and **−7.7bp (t −3.21) on untouched**
ones. Muni touched name-days are the exception, at −91bp (t −3.25), but muni
is barely in the deployed set: MHD never clears the ADV filter before 2023, and
MQY appears on 43 grid dates.

**Year-end special distributions** (*D*/*P* > 2%, 34 in 2005–22). Removing
3 sessions before to *W* after each special — *W* = 5 / 10 / 21, a sensitivity,
nothing chosen — moves the DEPLOYED IC from −0.033 to −0.027 / −0.026 /
−0.023. That is 18–29% of it. The WIDE IC does not move (−0.060 →
−0.061 / −0.060 / −0.061). On the deployed book, part of the IC is the
discount's jump around a large special (§1 arithmetic, plus the post-ex price
drift) reverting.

**Crises** (signal date inside the window):

| set | window | dates | IC |
|---|---|---:|---:|
| DEPLOYED | GFC 2008-09 → 2009-03 | 0 | — (book did not exist) |
| DEPLOYED | COVID 2020-02-20 → 04-30 | 25 | −0.045 |
| DEPLOYED | March 2020 | 11 | −0.116 |
| DEPLOYED | **outside every window** | 498 | **−0.032** (t −1.60) |
| WIDE | GFC | 73 | −0.126 |
| WIDE | outside every window | 2,166 | −0.058 (t −7.37) |

The crises are strong but rare. The windows hold 5% of the deployed dates and
about 7% of the summed IC; outside them the mean IC barely moves.

**Turn of year** (signal dated December or January):

| set | Dec–Jan: dates, IC, t | Feb–Nov: dates, IC, t |
|---|---|---|
| **DEPLOYED** | 96, **−0.093**, −1.95 | 427, **−0.019**, −0.90 |
| WIDE | 370, −0.072, −3.76 | 1,894, −0.058, −6.86 |

The DEPLOYED Dec–Jan dates are 18% of the dates and carry
96 × 0.093 / (523 × 0.033) = **52% of the summed IC**. On the wide set the
share is 20% of the IC on 16% of the dates, nearly proportional.

By group, the pooled slope is concentrated in **multi** (PIMCO-heavy: −16.6bp,
t −2.95, Dec–Jan; −5.6bp, t −1.91, Feb–Nov), not in muni. So it is **not** the
Starks–Yong–Zheng municipal tax-loss seasonal [S]: the deployed book holds
almost no muni. It overlaps with the year-end specials above: excluding them
leaves Dec–Jan at −0.063 / −0.059 / −0.045 against Feb–Nov −0.019.

**Volatility state** (quintile of trailing 63-session realised vol of the
equal-weight 13-name index, known at *t*):

| set | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---:|---:|---:|---:|---:|
| DEPLOYED | +0.066 | −0.012 | −0.017 | **−0.133** (t −3.07) | −0.069 |
| WIDE | −0.012 | −0.022 | −0.069 | −0.097 | −0.095 |

The IC lives in volatile states, consistent with the "2.39× stronger in stress"
VIX-tercile row in `docs/REFERENCES.md` §9 (2026-09-11). It is not confined to
the named crisis windows.

**By era**: §0.

## 5. The P&L split: NAV leg and discount leg (§5)

The price total return equals the NAV total return plus (price TR − NAV TR). The
first leg is what the book's long–short fund portfolios earned at NAV; the
second is the discount closing or widening in price. They add exactly (max
difference 7e−18). Costs belong to the traded total, so the grid is meaningful
on the total row only.

| leg | era | gross SR | ann % | vol % |
|---|---|---:|---:|---:|
| **total** | 2010–14 / 2015–19 / 2020–22 | 0.72 / 0.84 / 1.02 | 2.24 / 5.70 / 6.49 | 3.1 / 6.8 / 6.4 |
| **total** | fit | **0.69** | **3.29** | 4.73 |
| NAV leg | 2010–14 / 2015–19 / 2020–22 | −1.21 / −0.01 / −0.37 | −1.46 / −0.02 / −0.72 | 1.2 / 1.5 / 1.9 |
| NAV leg | fit | **−0.41** | **−0.53** | 1.28 |
| discount leg | 2010–14 / 2015–19 / 2020–22 | 1.09 / 0.82 / 1.06 | 3.69 / 5.72 / 7.20 | 3.4 / 7.0 / 6.8 |
| discount leg | fit | **0.77** | **3.82** | 4.96 |
| total | live 2013-06 → 2022 | 0.96 | 6.21 | 6.50 |
| NAV leg | live 2013-06 → 2022 | −0.57 | −1.00 | 1.76 |
| discount leg | live 2013-06 → 2022 | 1.06 | 7.21 | 6.82 |

On the total, at 5 / 15 / 30bp: 0.62 / 0.47 / 0.24 (fit). It does not flip.

- The discount leg is +1.16 of the total's return in the fit period (+1.65,
  +1.00, +1.11 by era).
- The NAV leg is −0.16 of it.
- The legs correlate −0.30 on live days.
- By group, the fit-period total is +2.20%/yr from multi, +0.65% from hy,
  +0.40% from loan and +0.04% from muni. Multi's NAV leg is −0.75% and its
  discount leg +2.95%.

**Read with §3.** A NAV that catches up toward the price adds equally to the
discount leg and subtracts from the NAV leg, so the split overstates price-driven
closure by roughly the NAV leg's loss. Even on that reading the total, which is
all price, is positive in every era.

## 6. Factor attribution (§6)

**Factors**:

- Ken French FF5 (2×3) + momentum, the 202608 CRSP vintage, fetched 2026-10-11;
- Pástor–Stambaugh traded LIQ_V, monthly, to 2025-12, fetched 2026-10-11.

Both are cross-checked against the R2 WRDS mirror and reported, not averaged
(`docs/REFERENCES.md` §8). The P&L is the deployed total-return P&L from its
first position (2013-06-25). It is a self-financing long–short return, so no
risk-free rate is subtracted. Net series charge cost × turnover on the fill day.

**Daily, FF5 + UMD, HAC(5)** (alpha in %/yr):

| window | n | alpha | t | mktrf | smb | hml | rmw | cma | umd | R² | α@5 (t) | α@15 (t) | α@30 (t) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 2013-06 → 2014 | 384 | 6.42 | 1.41 | 0.055 | −0.019 | 0.010 | 0.002 | −0.154 | −0.090 | 0.018 | 5.64 (1.25) | 4.07 (0.92) | 1.72 (0.39) |
| 2015–19 | 1,258 | 5.74 | 1.94 | −0.008 | −0.020 | −0.046 | −0.033 | −0.001 | −0.049 | 0.006 | 5.35 (1.81) | 4.55 (1.54) | 3.36 (1.13) |
| 2020–22 | 756 | 6.21 | 1.87 | 0.030 | −0.025 | 0.035 | −0.037 | 0.016 | 0.014 | 0.023 | 5.14 (1.55) | 2.99 (0.91) | −0.24 (−0.07) |
| **all live** | 2,398 | **6.03** | **2.94** | 0.020 | −0.010 | 0.010 | −0.020 | 0.021 | −0.001 | 0.004 | 5.35 (2.62) | 4.00 (1.96) | 1.97 (0.97) |

No beta t exceeds 1.01 in the full window.

**Dimson** (factors at *t* and *t−1*, summed betas): alpha 6.41%/yr, t 3.08.
Every summed |β| is ≤ 0.044 over the full window.

**Monthly, FF5 + UMD + LIQ_V, HAC(3)** (114 months from 2013-07): alpha
**6.44%/yr, t 3.22**, net 5.72 (2.91) / 4.27 (2.22) / 2.11 (1.10) at
5 / 15 / 30bp. LIQ_V β −0.037 (t −0.77); UMD β −0.082 (t −1.76); R² 0.046.
By era: 9.88 (2.35; 18 months for 8 parameters, so it means little), 4.37 (1.57), 8.18 (2.75).

**An addition, outside the work order.** Because this is a credit book, the
regression was rerun with HYG−IEF, IEF−rf and MUB−IEF (CRSP total returns)
beside FF5 + UMD. Alpha is 5.88%/yr (t 2.87). Credit β −0.02 (t −0.56),
rates +0.08 (1.43), muni-over-Treasury +0.14 (1.99); in 2020–22 the
muni-over-Treasury β is +0.19 (t 2.27).

**Sadka: not fetchable, stopped.** No free public source was found: it is
distributed through WRDS's licensed liquidity bundle. The desk's R2 WRDS copy
ends in 2008-12, before the book's first position, so it could not attribute
this P&L in any case. No other liquidity measure was substituted.

**Against D4** (alpha t ≥ 3.0 with every |β| ≤ 0.10): **the betas pass with
room to spare.** The gross alpha t sits on the bar: 2.94 daily, 3.08 Dimson,
3.22 monthly. At 5bp and above it falls below the bar. The book is not a factor
premium in costume. Its alpha is real gross but thin, and nine and a half
years is short.

---

## What this changes

1. **The IC baseline for every "incremental to the z-score" test** is the
   deployed set's:
   - IC −0.033 (phase 0) / −0.039 (phase 1);
   - slope −12.8bp per unit z (Fama–MacBeth) or −6.7bp (pooled);
   - fit period, from 2013-06.

   It is not the BRIEF's −0.074. A candidate scored on the wide or 17-name set
   is not comparable to the book. **`docs/BRIEF.md` §1 and §3 carry dated
   pointers to this note.**
2. **The decision lag is the largest loss of IC, and it is not an artifact.**
   The t+1 IC (−0.042) exceeds t+2 and t+3 combined, and survives on
   midpoints. Only a book that could act at close *t*, before *t*'s NAV is
   published, could earn it. That needs an intraday NAV nowcast (W13 / C3, a
   counted trial); no change to the session schedule can do it, because every
   schedule decides on *t*'s NAV and fills at *t+1*.

   > **Corrected 2026-10-12** (`results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md`
   > §1, `python3 scripts/cef/core_signal_decomp.py t1`). The t+1 IC is not in
   > the overnight gap (+0.005). It is in the **t+1 session**, open to close
   > (−0.041, t −3.08), and it survives on the NYSE opening-auction print
   > (−0.046, t −2.85, 2016–22). A book that decides on *t*'s NAV in the evening
   > and fills at the **t+1 opening auction** can reach it, without a nowcast.
   > That is an execution change: it needs order-path rule 3 amended, and it is a
   > counted CEF trial. The sentence above holds only for the overnight part.
3. **C2 and C3 inherit these facts**:
   - The turn-of-year concentration sits in multi and in year-end specials. A
     corporate-action or special-distribution conditioner (C1, G6) should
     declare it as a negative control before running.
   - The stale-NAV correction (C3) starts from "the stale part of z carries no
     price IC at the traded horizon". Its case has to be a TC or timing gain,
     not a cleaner IC.
4. **H15** (returns are total returns) is satisfied by `total_returns()`, which
   already raises on a missing ex-date. Making it `evaluate`'s default would move
   every stored baseline at once. That is a separate decision and is not taken
   here.

## Gaps

- **Sadka**: no free source, and the licensed copy ends in 2008. Not measured.
- **The deployed signal has 1,047 decision dates before 2023**, all after
  2013-06. Every deployed-set figure has wide errors (the bootstrap 95% CI on
  the IC spans zero). The wide set is the only view of 2005–12 and of the GFC,
  and it is not the book.
- **Muni is untestable on the deployed set**: MHD never clears the ADV filter
  before 2023, and MQY appears on 43 grid dates. The mechanism the brief
  expected to be strongest (muni stale NAV, muni tax-loss selling) cannot be
  seen in the book that trades.
- **Auction prints exist only from 2016**, through Alpaca. 2005–15 has CRSP
  closes and quotes but no auction record.
- **Survivorship**: the panel holds only funds alive today. Unmeasured, as
  before.
- **The time holdout (2023+) was not opened.** Nothing here says how any of
  these shares behaves after 2022.
