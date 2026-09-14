# G6 Part B — the conditioners, and the regression that gates C3

**Run 2026-09-13** by `python3 scripts/gamma/conditioners.py`. **Trials: 0** — a regression test, not a specification. Nothing is traded and nothing is adopted.

## Declared before running

| conditioner | rule | threshold | status |
|---|---|---|---|
| **C1** VRP level | standardised trailing implied − realised spread, cheap tail | -1.0 sd, 504-session window | run |
| **C2** term structure | 1m/3m ATM implied ratio > 1.0 | 1.0 | **DECLARED, NOT RUN** — needs a term structure; IBKR serves no historical option bars (verified 9 ways, 2026-09-12) |
| **C3** CEF stress | ⅓(D̃+Ṽ+W̃) from the 17 | > 1.5, 252-session window | run |

C2 is recorded here **before any result**, per G6's own rule that all three are declared and none amended after seeing results. It is unavailable, not unpromising, and the distinction is kept.

## The target

`RV_cc(HYG)_{t+1..t+5} − IV_t`, in **annualised vol as a DECIMAL** — `load_vxhyg` divides Cboe's quote by 100, so `-0.0363` means **3.63 percentage points** of annualised vol, not 0.04. The unit is spelled out because every beta and every mean below inherits it, and a reader who takes these for percentage points is off by a factor of 100 in the direction that makes the premium look negligible. **Positive = realised exceeded what was priced**, which is the state long gamma wants. Close-to-close because that is what a once-daily hedger earns (G3 Part C). Sample 2015-04-22 .. 2026-07-23, n = 1,878, mean **-0.0363**, median **-0.0355**.

That mean is negative by construction of the premium measured in `CREDIT_BASE_RATE`: implied exceeds realised most of the time. A conditioner earns its keep only by finding the minority of days when it does not.

## The regression that decides C3

OLS, Newey–West lag 5. **The bar is not significance — it is beating C1.**

| model | n | β C1 | t | β C3 | t | R² |
|---|---:|---:|---:|---:|---:|---:|
| C1 alone | 1,374 | -0.0092 | -2.11 | — |  | 0.0581 |
| C3 alone | 1,878 | — |  | +0.0051 | +1.58 | 0.0115 |
| C1 + C3 | 1,374 | -0.0110 | -2.78 | +0.0097 | +2.42 | 0.0939 |

**Incremental R² of C3 over C1: +0.0358** (0.0581 → 0.0939).

### Is it mechanical? The target contains IV_t, and so does C1

`target = RV_fwd − IV_t` and C1 is built from IV_t (corr +0.272), so part of any fit is arithmetic rather than prediction. The honest test is whether C3 predicts **forward realised vol itself**, which contains no IV term at all:

| left-hand side | model | n | β C3 | t | R² |
|---|---|---:|---:|---:|---:|
| `RV_fwd − IV_t` (the stated target) | C3 alone | 1,878 | +0.00515 | +1.58 | 0.0115 |
| `RV_fwd − IV_t` (the stated target) | C1 + C3 | 1,374 | +0.00967 | +2.42 | 0.0939 |
| **`RV_fwd` alone — no IV term** | C3 alone | 4,851 | +0.02105 | +3.95 | 0.0471 |
| **`RV_fwd` alone — no IV term** | C1 + C3 | 1,374 | +0.02085 | +2.55 | 0.0785 |

**C3 survives that check.** Against forward realised vol with no IV term anywhere, β **+0.02105**, t **+3.95**, n = 4,851. So the in-sample result is not purely the arithmetic of subtracting IV from itself — CEF stress really does carry information about HYG's next week.

### The holdout, which is where it dies

G6's decision rule requires the full sample **and** the 2023–2026 holdout. The thresholds and windows were fixed in advance, so the holdout tests the rule rather than a fit.

| window | left-hand side | n | β C3 | t |
|---|---|---:|---:|---:|
| full sample | RV_fwd − IV_t | 1,374 | +0.00967 | +2.42 |
| full sample | RV_fwd alone | 1,374 | +0.02085 | +2.55 |
| **holdout 2023–2026** | RV_fwd − IV_t | 298 | -0.00055 | -0.20 |
| **holdout 2023–2026** | RV_fwd alone | 298 | +0.00490 | +1.69 |

**On the holdout the coefficient falls to 24% of its full-sample value** (+0.02085 → +0.00490) and t drops to **+1.69**. On the stated target it is **-0.20** — indistinguishable from nothing.

### VERDICT: C3 DOES NOT CLEAR the bar

It clears the full-sample half — beside C1 its coefficient is **+0.0097** at t **+2.42**, adding **+0.0358** of R², and it survives the no-IV-term control. **It fails the holdout**, and G6's rule requires both.

**This is the `z_window = 63` shape**, which `00_BRIEF.md` H8 calls the most instructive event in this project's history: a clean in-sample result, a plausible mechanism, and a holdout that says no. The mechanism may still be real — 2023–2026 is 298 observations of an unusually calm credit tape, and **1.8% of days** in that era had implied below realised at all (`CREDIT_BASE_RATE`), so there was almost nothing for a long-gamma timer to find. But that is an explanation, and the rule does not bend for explanations.

## By era — the rule, not a fit

| era | n | β C3 (with C1) | t | R² (C1+C3) | R² (C1) |
|---|---:|---:|---:|---:|---:|
| 2015–2019 | 641 | +0.0034 | +1.91 | 0.4744 | 0.4669 |
| 2020–2022 | 435 | +0.0160 | +2.70 | 0.0708 | 0.0030 |
| 2023–2026 | 298 | -0.0005 | -0.20 | 0.0941 | 0.0938 |

## The states as traded, and time in market

| conditioner | threshold | days on | % of sample | mean target when ON | when OFF |
|---|---:|---:|---:|---:|---:|
| C1 **(declared)** | -1.0 | 129 | 6.9% | **-0.0342** | -0.0364 |
| C1 | -0.5 | 304 | 16.2% | **-0.0280** | -0.0379 |
| C1 | -1.5 | 61 | 3.2% | **-0.0444** | -0.0360 |
| C3 **(declared)** | 1.5 | 99 | 5.3% | **-0.0233** | -0.0370 |
| C3 | 1.0 | 160 | 8.5% | **-0.0290** | -0.0370 |
| C3 | 2.0 | 62 | 3.3% | **-0.0113** | -0.0371 |

Sensitivity rows are reported and **not selected on** — the declared thresholds are the ones that count.

## Negative control: shuffled states, 20 draws

If a shuffled state series with the same on-fraction earns comparably, the gain is time-in-market rather than timing.

| conditioner | real mean target when ON | shuffled mean (20 draws) | real percentile |
|---|---:|---:|---:|
| C1 | -0.0342 | -0.0366 | 80% |
| C3 | -0.0233 | -0.0356 | 100% |

## The three components of C3, separately

Reported because an average can hide one component doing all the work and another doing none — and because C3 is the only conditioner that is ours, so it is the one worth taking apart.

| component | what | β (alone) | t | R² |
|---|---|---:|---:|---:|
| D | cross-sectional sd of discount changes | +0.0030 | +1.01 | 0.0070 |
| V | 3-session z-velocity, widening positive | +0.0040 | +1.68 | 0.0117 |
| W | fraction widening > 1 trailing-63d sd | +0.0022 | +1.08 | 0.0032 |

