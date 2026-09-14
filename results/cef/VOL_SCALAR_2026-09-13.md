# The volatility scalar, measured over its whole history

**Run 2026-09-13** by `python3 scripts/cef/vol_scalar_history.py`. **Trials: 0** — a measurement. Nothing is adopted and no spec key moves.

Spec `cef_discount.v6.20260906`, `vol_target_annual` **0.06**, capital **$500,000**, `max_gross_exposure_usd` **$1,300,000**. Panel 2013-06-14 .. 2026-09-11, 3,046 decision dates.

## The question

The 2026-09-11 session printed `volscal=1.58` and gross **$813,682**. The frozen spec's `sizing_note` says:

> $500k against a $730k-equivalent paper account. At the current 1.5x volatility scalar that is ~$750k gross = ~$514k CAD initial margin, which fits alongside the Phase 0 null trader (~$438k CAD) inside $958k available funds. Raise only after live slippage is measured.

So: was **1.5x** ever a bound?

## The scalar's distribution

| statistic | trailing realised vol `rv` | scalar |
|---|---:|---:|
| min | 0.0000 | 0.285 |
| p5 | 0.0268 | 0.627 |
| p25 | 0.0365 | 0.994 |
| median | 0.0451 | 1.330 |
| p75 | 0.0603 | 1.642 |
| p95 | 0.0957 | 2.230 |
| max | 0.2104 | 2.500 |
| mean | 0.0518 | 1.345 |

- At the **2.5 cap**: 75 of 3,046 dates (**2.5%**)
- At the **0.2 floor**: 0 (**0.0%**)
- **Above 1.5**: 1,115 (**36.6%**) — the note's figure is not a ceiling the scalar respects

## By year

| year | n | median scalar | max | % of days > 1.5 | % at the 2.5 cap |
|---|---:|---:|---:|---:|---:|
| 2013 | 129 | 0.88 | 1.54 | 1.6% | 0.0% |
| 2014 | 215 | 1.28 | 1.64 | 15.8% | 0.0% |
| 2015 | 63 | 1.08 | 1.75 | 7.9% | 0.0% |
| 2016 | 203 | 1.40 | 2.27 | 40.9% | 0.0% |
| 2017 | 251 | 1.87 | 2.50 | 69.3% | 19.5% |
| 2018 | 251 | 1.58 | 2.50 | 57.0% | 5.2% |
| 2019 | 252 | 1.41 | 2.34 | 36.5% | 0.0% |
| 2020 | 253 | 0.93 | 2.50 | 27.7% | 1.2% |
| 2021 | 252 | 1.27 | 2.50 | 28.6% | 0.4% |
| 2022 | 251 | 1.10 | 1.82 | 17.5% | 0.0% |
| 2023 | 250 | 1.04 | 1.75 | 7.6% | 0.0% |
| 2024 | 252 | 1.55 | 2.36 | 63.9% | 0.0% |
| 2025 | 250 | 1.57 | 2.50 | 51.6% | 3.6% |
| 2026 | 174 | 1.50 | 2.37 | 50.0% | 0.0% |

## The last 10 decision dates

| date | rv (ann.) | scalar | names | target gross |
|---|---:|---:|---:|---:|
| 2026-08-28 | 0.0364 | **1.65** | 17 | $824,913 |
| 2026-08-31 | 0.0377 | **1.59** | 17 | $795,517 |
| 2026-09-01 | 0.0389 | **1.54** | 17 | $770,486 |
| 2026-09-02 | 0.0394 | **1.52** | 17 | $760,730 |
| 2026-09-03 | 0.0397 | **1.51** | 17 | $756,001 |
| 2026-09-04 | 0.0368 | **1.63** | 17 | $814,849 |
| 2026-09-08 | 0.0382 | **1.57** | 17 | $785,193 |
| 2026-09-09 | 0.0348 | **1.72** | 17 | $860,970 |
| 2026-09-10 | 0.0370 | **1.62** | 17 | $811,822 |
| 2026-09-11 | 0.0379 | **1.58** | 17 | $792,242 |

## The answer

**The scalar is doing exactly what it was specified to do.** On the last decision date the sleeve's own trailing 63-day realised vol was **3.79%** annualised against a **6%** target, so the scalar is 0.06/0.0379 = **1.58**. A quiet tape produces a low `rv`, a low `rv` produces a high scalar, and that is the mechanism, not a fault in it.

**1.5 was never a bound.** It appears once, inside `sizing_note`, as a description of the scalar on the afternoon that note was written, used to derive a margin figure. It is not a key, nothing reads it, and no code path compares against it. The scalar has exceeded 1.5 on **36.6%** of all decision dates in the panel.

**The real bound is `max_gross_exposure_usd` = $1,300,000**, and at the measured gross of $813,682 the book is at **63%** of it. The cap that binds the scalar itself is the `np.clip(..., 0.2, 2.5)` in `cef_discount.py:198`, which the scalar has reached on 2.5% of dates.

**Where the extra gross comes from.** Target gross is capital x scalar = $500,000 x 1.58 = **$792,242**. The session reported **$813,682**, about +2.7% against that. That gap is the **no-trade band**, not the scalar: at `band_width` 0.048, a position inside the band is left alone, so held gross drifts with prices between trades instead of being marked back to target every session. A band that never let gross drift would be a band that always traded, which is the cost this book is built to avoid.

## What this does NOT say

It does not say the sizing is right. Two things are worth a separate look, and neither is decided here:

1. **The 2.5 cap binds on 2.5% of dates.** Where it binds, the book is NOT running at its vol target — it is running below it, by construction. Whether that is the intended behaviour in the calmest regimes is a question for a pre-registration, not for this script.
2. **`rv` is measured on TODAY's weights applied to the last 63 days**, not on the book's own realised P&L. Those differ whenever the weight vector turns over. It is not lookahead — every input precedes the decision — but it is not the traded book's volatility either, and the distinction should be stated wherever this number is quoted.
