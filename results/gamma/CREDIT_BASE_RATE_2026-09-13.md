# G6 Part A — the credit variance risk premium, on our own data

**Run 2026-09-13** by `python3 scripts/gamma/credit_base_rate.py`. **Trials: 0** — this is a base rate, not a specification.

## Inputs

| series | what | coverage | source |
|---|---|---|---|
| VXHYG | HYG ETF option implied vol, 30d VIX methodology | 2015-04-22 .. **2026-09-11** (1,913) | Cboe, `scripts/gamma/fetch_cboe_vol_indices.py` |
| HYG | close-to-close returns | 2007-04-12 .. **2026-07-30** (4,856) | `data/rv/etf_ohlc_extended.parquet` |

**The two panels do not end together.** HYG's is **43 days** behind VXHYG's, so every ratio below ends at **2026-07-30**, not at VXHYG's last date. `ops/doctor.py` flags the ETF panel as stale and names this exact consumer. Refreshing it extends the sample; it does not change the base rate over eleven years.

## The two ratios, and why they are not the same number

| ratio | n | mean | p5 | p25 | **median** | p75 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| implied ÷ **trailing** realised variance (`rich_ratio`) | 1,883 | 3.453 | 0.909 | 1.757 | **2.793** | 4.205 | 7.498 |
| implied ÷ **forward** realised variance (the VRP itself) | 1,862 | 3.661 | 0.733 | 1.854 | **2.986** | 4.562 | 8.192 |

**Read the second row, not the first, for what a long-gamma book pays.** Buying and delta-hedging HYG gamma loses when implied exceeds subsequent realised, and the median says it does so by a factor of **2.99** in variance — i.e. about **1.73x in vol terms**. That is the headwind, and it is before any spread, commission or hedge cost.

The first row is the ex-ante INDICATOR — implied against *recent* realised, knowable at the decision. Median **2.79**. It is what `C1` conditions on; it is not a payoff. **`G0_BRIEF` §2 describes the repo's SPY column as "implied to *forward* realised" and it is trailing** — reverse-engineered exactly against `data/vrp/vrp_series.parquet` (`impl_var / rv_trail`, max error 0.0). The medians it quotes, 1.32 and 1.55, are the trailing figures.

## Credit against equity, on the identical construction

The number above is only interpretable beside the equity benchmark this repo already carries, computed the same way from `data/vrp/vrp_series.parquet`:

| underlier | median implied | median forward realised | vol ratio | **variance ratio** |
|---|---:|---:|---:|---:|
| **HYG** (credit) | 7.78% | 4.68% | 1.66x | **2.77x** |
| SPY (equity) | 14.02% | 12.40% | 1.13x | **1.28x** |

**Credit gamma is more than twice as expensive as equity gamma** — 2.77x against 1.28x in variance. HYG's implied vol sits near 7.8% while it delivers about 4.7%; SPY's two numbers are far closer together. The mechanism is not mysterious — a credit ETF's implied vol prices jump and default risk that realised vol almost never delivers — but the SIZE of it is the single most important number for this programme, and it was unmeasured until today.

## The prompt predicted this, and the prediction holds

`G6` Part A states the prior in advance, from primary sources: *"the prior is that credit's VRP is real and probably larger than equity's, not smaller"* — citing Wang, Zhou & Zhou (FEDS 2011-02, 382 firms, 2001–2008), whose central finding is that **mean VRP rises monotonically with credit risk, from 7 at AAA to 82 at CCC**, and Kita & Tortorice (2021) that the smirk *"is more pronounced in the credit market than in the equity market"*.

HYG is a **high-yield** basket, so that literature predicts a large premium, and the measurement agrees: **2.77x against equity's 1.28x.** This is a prior stated before the data was fetched and confirmed by it — worth recording as such, because the opposite result would have been the more interesting one and would have pointed at a bug in the surface or the estimator rather than at an edge (G6 Part A says exactly that).

## How often is credit gamma actually cheap?

The fraction of days on which implied was BELOW subsequent realised — i.e. long gamma would have paid:

| window | days | implied < forward realised |
|---|---:|---:|
| full sample | 1,862 | **9.1%** |
| 2015–2019 | 1,145 | **10.0%** |
| 2020–2022 | 435 | **11.5%** |
| 2023–2026 | 282 | **1.8%** |

## By era

| era | n | median `rich_ratio` | median VRP (fwd) | median VXHYG |
|---|---:|---:|---:|---:|
| 2015–2019 | 1,145 | 2.744 | 2.853 | 8.08 |
| 2020–2022 | 435 | 2.845 | 3.472 | 8.91 |
| 2023–2026 | 303 | 2.769 | 3.221 | 6.64 |

## What this means for the programme

A systematic long-gamma credit book pays the second row every day it is on. At a median variance ratio of **2.99** the conditioner has to do real work: `G6`'s decision rule requires a candidate to beat **C1**, not merely to beat always-on, and this is the size of the hole always-on starts in.

Days on which long gamma would have paid: **9.1%** of the sample. A conditioner is useful only if it selects them at a rate materially above that base rate — which is the null `C1` and `C3` are tested against, and it is stated here BEFORE either is run.

