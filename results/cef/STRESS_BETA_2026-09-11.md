# W14 Part A — stress beta of the CEF discount book

**Run 2026-09-11** by `python3 scripts/cef/stress_beta.py`. Spec `cef_discount.v6.20260906`, policy **band 4.8%**, universe 17. Trials spent: **0** on either counter — this prompt adopts nothing.

## A0 The P&L series under test

`band_frontier.evaluate(band(T, band_width), R)['pnl']` — shift(2), decide at *t*, MOC fill at *t+1*, earn the *t+2* return (H1). The `pnl` key is the extension this prompt added to the canonical harness; no second backtester was built.

| convention | scope | gross SR | ann % | vol % | turn/yr | sample |
|---|---|---:|---:|---:|---:|---|
| **total return** (used below) | full panel | 1.210 | 6.22 | 5.14 | 17.6 | 2005-01-03 .. 2026-09-10 |
| **total return** (used below) | **traded sessions only** | 1.551 | 10.19 | 6.57 | 28.8 | 2013-06-14 .. 2026-09-10 |
| price return only | full panel | 1.169 | 6.21 | 5.32 | 17.6 | 2005-01-03 .. 2026-09-10 |
| price return only | **traded sessions only** | 1.498 | 10.18 | 6.80 | 28.8 | 2013-06-14 .. 2026-09-10 |

The full-panel price-return row is the figure `band_frontier.py` publishes and `CLAUDE.md` quotes as gross **1.17**; it reproduces here at **1.169**. [V]

**The sample is not what the index says.** The panel runs from 2005-01-03, but the ADV filter lets fewer than `min_names` through until **2013-06-14**, so the book holds *nothing* — P&L exactly zero, not merely small — on 2,126 of 5,456 sessions, and there are no flat sessions after that date. **This book has never been through a credit crisis.** No 2008, no 2011. CLAUDE.md landmine 6 says "the 2411 dates before 2013 are flat"; measured here on the live band it is 2,126 sessions and the first position is 2013-06-14. Everything from A1 down is restricted to the traded sessions, and the VIX reference distribution with it — otherwise "top VIX quintile" is a threshold set by a vol state the book was never exposed to.

Landmine 6's other half checks out arithmetically: the flat rows dilute the Sharpe by √(3,330/5,456) = 0.781, and 1.210 ÷ 0.781 = 1.549 against the 1.551 measured on the traded sessions. Every headline Sharpe in this repo is a full-panel one and therefore carries that dilution.

Distribution carry on this holdings path, **full panel** so it is comparable to the recorded measurement: **+0.003%/yr**, sd 1.24%/yr, over 3,980 ex-dates. `docs/RESEARCH_STATE.md` measured −0.01%/yr, sd 1.23%/yr over 3,962 ex-dates on 2026-09-09; the panel has since extended to 2026-09-10. **[V] reproduced.** By era: 2005-09 +0.00%, 2010-14 -0.77%, 2015-19 +0.32%, 2020-22 +0.36%, 2023-26 +0.34%.


## A1 The factor panel

| factor | what it is | source | sd, on the regression sample |
|---|---|---|---:|
| `HY_XS` | HY excess, duration-hedged | HYG − rf − β₆₃·(IEF − rf), β shifted 1d | 7.66 % |
| `IG_XS` | IG excess, duration-hedged | LQD − rf − β₆₃·(IEF − rf), β shifted 1d | 5.87 % |
| `UST_XS` | rates | IEF − rf (7–10y; the tradeable proxy for “10y Treasury”) | 6.48 % |
| `SPX_XS` | equity | SPY total return − rf, from `data/rv/etf_ohlc_extended.parquet` | 17.52 % |
| `D_VIX` | Δ implied vol | VIX close, first difference, in points | 1.91 pts/day |
| `SHORTVOL` | short-ATM-straddle proxy | rebuilt from `data/vrp/marks_SPY.parquet` — see below | 4.64 % |
| `CRD_MOM` | credit momentum | sign(Σ₆₃ HY_XS as of t−1) × HY_XS_t | 7.66 % |

**The straddle proxy is REBUILT, not read.** `src/deploy/lib/attribution.py` sources it from `results/vrp/refute_tail_ledger_SPY.csv`, which **does not exist** — nor does `results/vrp/`, nor the script that wrote it. W14 permits rebuilding the single series and saying which; this is that. It is **gross** of option transaction costs where the original was net, so it is a slightly stronger vol exposure than the tradeable version. 2,742 days 2014-06-03..2026-07-10 (16 skipped for want of a two-sided mark on both days), median 31 DTE, mean +1.57%/yr on notional, sd 4.64%, skew **-4.50**. Requiring both legs quotable leaves a strike grid skewed below the forward, so the selected straddle carries a mean delta of +0.0186 (F > K on 79% of days) rather than 0; the Black–Scholes hedge computed from the panel's own IV removes it.

**Cross-check (recomputed a second way).** The same exposure from G0_BRIEF's identity ½(σ²_imp·Δt − r²), using the VRP panel's constant-maturity IV at *t−1* and SPY's return at *t* — no marks, no pricer, no delta: correlation with the traded-straddle series is **0.671** over 2,742 common days. The two agree.

**VIX provenance, and a disagreement not averaged away.** Primary `data/vrp/vix_daily.parquet` (2014-01-02..2026-07-20); dates before 2014-01-02 come from `data/forced_flow2/raw/vix_daily.parquet` (1996-01-02..2025-12-30), which is the only series here that reaches 2008. On their 3,017-day overlap they differ by more than 0.01 on **8 days** (max 0.98): 2014-08-29, 2014-10-15, 2014-12-01, 2014-12-03, 2014-12-05, 2014-12-09, 2021-08-11, 2021-10-01. Neither was edited and they were not averaged; the primary is used wherever it exists. The 8 days are 0.3% of the overlap and none is a drawdown window boundary below.

**[U] Neither `data/vrp/*` panel has a fetcher in this repo** — the builders are gone and `docs/REFERENCES.md` carries no entry for them. `data/vrp/_extract_SPY.log` records a month-by-month extraction. Everything below that rests on SPY options inherits that gap.

## A2 Factor regression of daily book P&L

OLS, Newey–West lag 5 (the prompt's lag; `src/deploy/lib/attribution.py` uses 10 — not interchangeable). Book P&L is total-return, shift(2).

Sample **2014-06-03 .. 2026-07-10**, n = 2,742. Full-model R² = **0.036**. Alpha +10.09%/yr (t +5.05).

| factor | β | t (NW5) | univariate R², own sample |
|---|---:|---:|---:|
| `HY_XS` | -0.01076 | -0.24 | 0.0110 |
| `IG_XS` | +0.03098 | +0.51 | 0.0094 |
| `UST_XS` | -0.03487 | -1.20 | 0.0029 |
| `SPX_XS` | +0.03005 | +1.27 | 0.0195 |
| `D_VIX` | -0.00009 | -0.69 | 0.0236 |
| `SHORTVOL` | +0.10503 | +1.34 | 0.0190 |
| `CRD_MOM` | -0.04021 | -1.18 | 0.0037 |

**β on ΔVIX = -0.000092 per VIX point** (t -0.69), which on the $500,000 book (`capital_usd`, read from the frozen spec) is **$-46 per VIX point** per day. Univariate: β -0.000343, t -2.80, R² 0.0236.

Price-return convention, same window, as the robustness the convention correction exists to provide:
β_ΔVIX -0.000100 (t -0.73), R² 0.034 — the convention does not move the verdict.

### The same regression without the straddle leg, over every date the book traded

`SHORTVOL` begins 2014-06 and is the only factor that binds the window short. Dropping it — and keeping ΔVIX, which the splice carries back further — costs the E1 comparability but buys back the book's first year. If β_ΔVIX moved between the two, the headline would be a statement about the window rather than about the book.

Sample 2013-06-14 .. 2026-07-16, n = 3,291, R² 0.027. **β_ΔVIX = -0.000247 (t -1.93)** = $-124 per VIX point, against -0.000092 (t -0.69) on the full set. Same sign, and 2.7× the magnitude — the longer window is the less favourable of the two for this prompt's conclusion, and it is still short of the gate's |t| ≥ 2.5 bar. The verdict does not turn on which window is read; it is stated on the prompt's own window, which is the full set.

**The univariate and multivariate ΔVIX betas differ and that is the interesting part.** Alone, ΔVIX loads -0.000343 at t -2.80; beside the credit, equity and straddle legs it falls to -0.000092 at t -0.69. Whatever ΔVIX picks up on its own is already carried by the tradeable legs — which is precisely the case in which buying volatility is the wrong instrument for it.

### By era, and fit vs holdout (H5, H13)

| window | n | β ΔVIX | t | β SHORTVOL | t | β HY_XS | t | R² |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full | 2,742 | -0.00009 | -0.69 | +0.105 | +1.34 | -0.011 | -0.24 | 0.036 |
| 2005-09 | — | UNMEASURED | | | | | | only 0 complete rows — too few to regress |
| 2010-14 | — | UNMEASURED | | | | | | only 133 complete rows — too few to regress |
| 2015-19 | 1,139 | +0.00002 | +0.10 | -0.011 | -0.10 | +0.114 | +2.36 | 0.008 |
| 2020-22 | 686 | -0.00020 | -0.99 | +0.108 | +0.92 | -0.040 | -0.51 | 0.108 |
| 2023-26 | 784 | -0.00021 | -1.20 | +0.190 | +1.90 | -0.257 | -2.24 | 0.094 |
| fit <2023 | 1,958 | -0.00008 | -0.49 | +0.083 | +0.87 | +0.028 | +0.56 | 0.036 |
| holdout 2023+ | 784 | -0.00021 | -1.20 | +0.190 | +1.90 | -0.257 | -2.24 | 0.094 |

### The same question without a regression

A t-statistic on a daily beta is a weak instrument for a tail claim, so here is the non-parametric version of the same question: what does the book actually do on the days volatility jumps?

| ΔVIX bucket | sessions | mean book P&L, bp/day | t | next 21 earned sessions, % |
|---|---:|---:|---:|---:|
| largest 5% ΔVIX (vol spikes) | 165 | -7.90 | -1.45 | +1.38 |
| largest 1% ΔVIX | 33 | -33.62 | -1.60 | +1.98 |
| all sessions | 3,293 | +4.00 | +5.54 | +0.84 |

**The book does lose on vol-spike days — and gets it back.** On the largest 5% of ΔVIX days it earns -7.90bp against +4.00bp unconditionally, a swing of -11.90bp; on the largest 1%, -33.62bp, which is $-1,681 on the $500,000 book and about 0.8 daily standard deviations (41.4bp). Neither is statistically distinguishable from zero (t -1.45, -1.60) at these sample sizes, so the daily loss is real in sign and weak in evidence.

The column on the right is the part that matters for a hedge. Over the 21 sessions a decision on a top-5% ΔVIX day actually earns (*t+2*..*t+22*, the shift(2) convention) the book makes **+1.38%** against +0.84% unconditionally, and **+1.98%** after a top-1% day. The shock costs roughly 34bp on the day and pays back several times that over the following month. **A convexity overlay bought to remove the first number is short the second one**, because it is sized and carried across the whole period, not just the spike.

**β on ΔHYG-IV: UNMEASURED.** No HYG option data exists anywhere in this repo — `data/vrp/atm_iv_daily.parquet` and the marks files carry SPY and QQQ only. Extracting a credit surface is `gamma/G2`. Until it lands the credit-specific half of this question cannot be answered, and ΔVIX stands in for it with the basis measured in A5.

## A3 Drawdown coincidence

Book P&L on dates it both traded and has a VIX observation: 2013-06-14 .. 2026-07-20, 3,293 sessions. Percentiles are taken within THAT window (a retrospective description, not a decision rule); the point-in-time expanding percentile is shown beside it, and the peak VIX inside each window beside that — because a window that *begins* before a spike and contains it scores low on the gate's own statistic and high on the one the mechanism actually predicts.

### all traded sessions — ten worst non-overlapping 21-session windows

Top VIX quintile in this window is VIX ≥ **21.77**.

| # | start | end | P&L % | VIX at start | pct (full) | pct (PIT) | peak VIX | peak pct | start in top q? | peak in top q? | worst single name | its share |
|---:|---|---|---:|---:|---:|---:|---:|---:|:---:|:---:|---|---:|
| 1 | 2017-09-22 | 2017-10-20 | -4.39 | 9.59 | 0.01 | 0.01 | 10.33 | 0.03 | no | no | PHK -3.89% | 88% |
| 2 | 2015-07-22 | 2015-08-19 | -4.39 | 12.12 | 0.11 | 0.11 | 15.60 | 0.45 | no | no | PHK -2.69% | 61% |
| 3 | 2020-02-19 | 2020-03-18 | -3.98 | 14.38 | 0.34 | 0.56 | 82.69 | 1.00 | no | **YES** | PHK -8.37% | 211% |
| 4 | 2025-09-19 | 2025-10-17 | -3.55 | 15.45 | 0.44 | 0.46 | 25.31 | 0.89 | no | **YES** | DSL -0.71% | 20% |
| 5 | 2025-10-23 | 2025-11-20 | -3.25 | 17.30 | 0.59 | 0.60 | 26.42 | 0.91 | no | **YES** | DSL -0.94% | 29% |
| 6 | 2018-05-14 | 2018-06-12 | -3.12 | 12.93 | 0.20 | 0.37 | 17.02 | 0.57 | no | no | PTY -3.26% | 105% |
| 7 | 2026-01-27 | 2026-02-25 | -3.10 | 16.35 | 0.52 | 0.53 | 21.77 | 0.80 | no | **YES** | NVG -1.55% | 50% |
| 8 | 2018-08-16 | 2018-09-14 | -2.99 | 13.45 | 0.25 | 0.47 | 14.88 | 0.39 | no | no | PDI -1.47% | 49% |
| 9 | 2021-06-18 | 2021-07-19 | -2.97 | 20.70 | 0.76 | 0.80 | 22.50 | 0.82 | no | **YES** | DSL -1.97% | 66% |
| 10 | 2018-03-12 | 2018-04-10 | -2.94 | 15.78 | 0.46 | 0.74 | 24.87 | 0.88 | no | **YES** | PTY -1.69% | 58% |

**0 of 10 START in the top VIX quintile** — the gate's own statistic. **6 of 10 CONTAIN a top-quintile VIX** at some point, which is the friendlier reading and still short of 7. Overlapping selection gives 0 of 10 on the start test and collapses onto 5 distinct months — which is why the non-overlapping census is the one the gate reads.

**The drawdowns are single-name events.** Across the ten windows the worst single fund accounts for a median 60% of the loss — **PHK** leads 3, **DSL** leads 3, **PTY** leads 2, **NVG** leads 1, **PDI** leads 1. That is not a shape an index option can hedge, and it is the same concentration the book's effective breadth of ~1.2 against 17 nominal names already says (`00_BRIEF.md` §1).

**Read window 3 carefully.** 2020-02-19..2020-03-18 is the window with the highest peak VIX in the table (82.69). The book lost -3.98% — but **PHK alone lost -8.37%, so the other 16 names together made +4.39%.** In the single genuine credit vol event this book has ever traded, everything except one premium fund was being paid by the reversion. A put on HYG would have bought protection against the part that was working.

### 2014+ (single-source VIX) — ten worst non-overlapping 21-session windows

Top VIX quintile in this window is VIX ≥ **22.05**.

| # | start | end | P&L % | VIX at start | pct (full) | pct (PIT) | peak VIX | peak pct | start in top q? | peak in top q? | worst single name | its share |
|---:|---|---|---:|---:|---:|---:|---:|---:|:---:|:---:|---|---:|
| 1 | 2017-09-22 | 2017-10-20 | -4.39 | 9.59 | 0.01 | 0.01 | 10.33 | 0.03 | no | no | PHK -3.89% | 88% |
| 2 | 2015-07-22 | 2015-08-19 | -4.39 | 12.12 | 0.11 | 0.14 | 15.60 | 0.44 | no | no | PHK -2.69% | 61% |
| 3 | 2020-02-19 | 2020-03-18 | -3.98 | 14.38 | 0.33 | 0.55 | 82.69 | 1.00 | no | **YES** | PHK -8.37% | 211% |
| 4 | 2025-09-19 | 2025-10-17 | -3.55 | 15.45 | 0.43 | 0.45 | 25.31 | 0.88 | no | **YES** | DSL -0.71% | 20% |
| 5 | 2025-10-23 | 2025-11-20 | -3.25 | 17.30 | 0.58 | 0.59 | 26.42 | 0.90 | no | **YES** | DSL -0.94% | 29% |
| 6 | 2018-05-14 | 2018-06-12 | -3.12 | 12.93 | 0.20 | 0.40 | 17.02 | 0.56 | no | no | PTY -3.26% | 105% |
| 7 | 2026-01-27 | 2026-02-25 | -3.10 | 16.35 | 0.50 | 0.52 | 21.77 | 0.79 | no | no | NVG -1.55% | 50% |
| 8 | 2018-08-16 | 2018-09-14 | -2.99 | 13.45 | 0.25 | 0.48 | 14.88 | 0.38 | no | no | PDI -1.47% | 49% |
| 9 | 2021-06-18 | 2021-07-19 | -2.97 | 20.70 | 0.75 | 0.78 | 22.50 | 0.82 | no | **YES** | DSL -1.97% | 66% |
| 10 | 2018-03-12 | 2018-04-10 | -2.94 | 15.78 | 0.45 | 0.74 | 24.87 | 0.87 | no | **YES** | PTY -1.69% | 58% |

**0 of 10 START in the top VIX quintile** — the gate's own statistic. **5 of 10 CONTAIN a top-quintile VIX** at some point, which is the friendlier reading and still short of 7. Overlapping selection gives 0 of 10 on the start test and collapses onto 5 distinct months — which is why the non-overlapping census is the one the gate reads.

**The drawdowns are single-name events.** Across the ten windows the worst single fund accounts for a median 60% of the loss — **PHK** leads 3, **DSL** leads 3, **PTY** leads 2, **NVG** leads 1, **PDI** leads 1. That is not a shape an index option can hedge, and it is the same concentration the book's effective breadth of ~1.2 against 17 nominal names already says (`00_BRIEF.md` §1).


## A4 Conditional IC by VIX tercile at signal time

Spearman(z at *t*, forward 2-day return from *t+2*), non-overlapping, date-clustered SE (H6). Expected sign is **negative** — a high z is a rich fund the book shorts.

| VIX tercile | VIX range | mean IC | t | dates |
|---|---|---:|---:|---:|
| low | 9.2–14.3 | -0.0392 | -2.88 | 549 |
| mid | 14.3–18.6 | -0.0417 | -2.95 | 549 |
| high | 18.6–75.9 | -0.0936 | -6.27 | 549 |

**IC ratio high ÷ low = 2.39.** A ratio above 1 means the signal works BETTER in stress; it is only interpretable while both ICs carry the expected negative sign, and this function refuses to print one when they do not.

By group (the four mechanisms the book actually holds):

| group | names | low-vol IC | high-vol IC | ratio |
|---|---:|---:|---:|---:|
| hy | 2 | UNMEASURED | UNMEASURED | a cross-sectional IC needs ≥5 names on the date |
| loan | 1 | UNMEASURED | UNMEASURED | a cross-sectional IC needs ≥5 names on the date |
| multi | 8 | -0.0625 | -0.0873 | 1.40 |
| muni | 6 | -0.0835 | -0.1083 | 1.30 |

### Forward 21-day book P&L after a top-decile VIX day

VIX top decile **within the traded sample** is ≥ 26.07. Deciding on such a day, the 21 sessions the decision actually earns (*t+2*..*t+22*, per shift(2)) return **+1.60%** on average (330 entries) against **+0.84%** unconditionally (3,308). Difference **+0.76pp** per 21 sessions.

## A5 Basis — the ceiling on what an HYG overlay could remove

Book P&L on HYG excess return alone: β +0.0933 (t +2.41), **R² = 0.0126** over 3,291 days. That is the ceiling on how much of this book's variance any HYG instrument can address.


On one common sample, so the four are comparable, HYG explains **less** of this book than the equity index does:

| regressor (univariate) | β | t (NW5) | R² |
|---|---:|---:|---:|
| HYG excess return | +0.10325 | +2.42 | 0.0155 |
| SPY excess return | +0.06081 | +2.79 | 0.0246 |
| ΔVIX | -0.00038 | -2.85 | 0.0289 |
| short-straddle proxy | +0.20174 | +2.19 | 0.0190 |

n = 2,742. **The only credit-volatility instrument this account can reach is the weakest of the four.** That is the basis problem stated as a number rather than as an anecdote, and it would still bind even if Part A's gate had passed.

**Book P&L on ΔHYG-IV: UNMEASURED** — see A2. The prompt asks for this number explicitly and it cannot be produced without `gamma/G2`.

For scale, the two legs are not the same instrument: in March 2020 CEF discounts widened by more than 1,600bp while HYG's own average absolute premium/discount to NAV rose only from 0.21% to 1.06% (`00_BRIEF.md` §3 — **[S]**, not re-fetched here).

**`rich_ratio` for credit: UNMEASURED.** `data/vrp/vrp_series.parquet` carries it for SPY and QQQ only; the credit figure is `gamma/G6`'s deliverable. SPY's median over 2014-06-03..2026-07-10 is 1.297 — equity, not credit, and it is not a substitute.

## A6 What Part A implies for Part C — measured, no trial spent

Part C asks whether the band width and the vol target should know what volatility is doing. It costs **1 CEF trial** and it is **blocked**: its input is HYG ATM implied vol from `gamma/G2`'s surface, which does not exist, and substituting VIX would be running the prompt's own negative control as the treatment. What can be measured today at zero cost is whether the LIVE spec already behaves differently across vol states — a description of the current policy, not a specification.

| VIX tercile at *t* | sessions | gross SR | ann % | turn/yr | net@5 | net@15 | net@30 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **all traded sessions (baseline)** | 3,293 | 1.53 | 10.08 | 29.0 | 1.31 | 0.87 | 0.21 |
| low | 1,101 | 1.46 | 9.52 | 30.4 | 1.22 | 0.76 | 0.06 |
| mid | 1,094 | 1.72 | 9.26 | 23.6 | 1.50 | 1.06 | 0.41 |
| high | 1,098 | 1.50 | 11.48 | 33.2 | 1.29 | 0.85 | 0.20 |


**The baseline row is the only honest comparator here**, and it is not the repo's headline net@15 of 0.67 / turn 17.6 — those are FULL-PANEL figures diluted by the 2,126 flat sessions. Against the traded-session baseline (turn 29.0, net@15 0.87) the **mid** tercile is +0.19 and the **high** tercile trades 1.14× baseline, not 1.88×. Read against the wrong baseline this table shows a state effect that is mostly the dropped flat sessions running in reverse.

With that said: the **high** tercile earns the most gross (11.48%/yr) and the **mid** tercile keeps the most net@15 (1.06 against 0.85), because the high-vol tercile also trades the most (33.2 turn/yr against 30.4 low and 23.6 mid). **That gap is a transfer-coefficient problem, not a convexity one**, and it is exactly what a state-scaled band would attack.

Cost grid 5/15/30bp (H3); borrow is charged separately and is not in these columns (H4). Turnover here is the band's own, conditioned on the state — not a matched comparison, because there is no alternative policy in this table to match against (H2 applies to comparisons).

The cube-root law says the no-trade half-width should scale as `σ_w^(2/3)`. Measured on this book's own target weights, the trailing 63-session sd of daily target changes in the top VIX tercile against the bottom is:

σ_w low-vol **0.02755**, high-vol **0.02894**, ratio **1.05×** → the cube-root law implies a band **1.03×** wider in stress, i.e. 4.8% → **5.0%**. That is the size of the effect Part C would be chasing. It is derived from the law and the measured ratio, not swept (H8), and it is recorded here so that Part C cannot later pick a width and call it derived.

## A7 Verdict

| quantity the prompt asks for | value |
|---|---|
| β_ΔVIX (t, NW5), prompt's factor set | **-0.000092** (t -0.69) = $-46 per VIX point |
| β_ΔVIX, longest window (no straddle leg) — the least favourable reading | -0.000247 (t -1.93) = $-124 per VIX point |
| β_ΔHYG-IV | **UNMEASURED** — no credit surface exists (`gamma/G2`) |
| worst-10 windows starting in top VIX quintile | **0/10** (the gate's statistic); 6/10 contain a top-quintile VIX |
| IC ratio, high-vol ÷ low-vol tercile | **2.39** |
| credit `rich_ratio` (G6) | **UNMEASURED** — SPY/QQQ only |

**The gate.** Part B opens only on β_ΔVIX < 0 with |t| ≥ 2.5 (FAIL: β -0.000092, |t| 0.69) **AND** ≥ 7 of 10 drawdown windows in the top VIX quintile (FAIL: 0/10).

### PART B IS CLOSED

### What the gate does NOT say

The gate reads ΔVIX. Two readings in this note point the other way and are stated here rather than left in a table:

* **`SHORTVOL` loads +0.105 (t +1.34) full sample and +0.190 (t +1.90) on the 2023-26 holdout.** A POSITIVE loading on a *short*-straddle return is the short-vol sign. It is the only tradeable vol factor in the panel and the holdout reading is the only |t| > 2 vol number in the era table.
* **Univariate ΔVIX is -0.000343 at t -2.80**, which clears the gate's own |t| ≥ 2.5 bar on its own. The gate is specified on the full factor set and is read that way, but a reader should know the verdict is specification-dependent in that one respect.

So the correct statement is narrower than "no vol exposure", and is the one below.

### The sentence

**The book carries a mild short-volatility exposure, and it is not the kind an option can profitably hedge.** It loses on the day volatility jumps (-7.90bp on the top-5% ΔVIX days against +4.00bp unconditionally, -33.62bp on the top 1%), but that loss is about 0.8 daily standard deviations, is not statistically distinguishable from zero (t -1.60), and is recovered several times over in the following month (+1.98% over the next 21 sessions against +0.84% unconditionally). Its ten worst 21-session windows do not start in high-vol states — 0 of 10 in the top VIX quintile, and the two worst begin at the 1% and 11% percentiles of VIX and are 88% and 61% attributable to one fund, PHK. And the signal is **2.39× stronger** in the high-vol tercile (IC -0.0936 against -0.0392), so the P&L a hedge would protect is the P&L the strategy exists to earn. **The exposure is real and small; the hedge is what does not pay.**

The mechanism in the prompt is half right: the book *is* at full size when the shock lands and it *does* lose on the widening. What the mechanism got wrong is the sign of what comes next — the reversion arrives fast enough, and large enough, that the shock is the book's best entry rather than its worst. Buying convexity would sell that.

A hedge that pays in states where the book does not lose is a pure carry cost. The honest answer is **Part C** (options as information — band width and vol target conditioned on implied vol, no option traded, 1 CEF trial) plus the standalone `gamma/` programme on its own counter — and note from A6 that the high-vol tercile earns 11.48%/yr gross but keeps only 0.85 net@15 against the mid tercile's 1.06, because it trades 1.41× as much. That is a transfer-coefficient problem, which is the lever this desk already knows is the largest one.

### What would reverse this

Stated now, before anyone looks again (H14 — re-measure, never quote this file): Part B re-opens if a re-run of this script clears BOTH gate conditions, or if `gamma/G2`'s HYG surface lands and β_ΔHYG-IV is negative with |t| ≥ 2.5 where β_ΔVIX was not — that would say the exposure is credit-vol specific and the equity index was simply the wrong instrument to look through. The basis R² in A5 is the prior on how likely that is, and it is small. The other reversal is a sample one: this book has never traded a credit crisis, so the census above is a statement about 2013–2026 and nothing else.

