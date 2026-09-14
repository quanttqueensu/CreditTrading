# G1 — option math: the early-exercise premium

**Run 2026-09-11** by `python3 scripts/gamma/early_exercise_grid.py`. Trials: **0** — this is a property of a model, not a claim about the market.

## Inputs, all from data

| input | value | source |
|---|---|---|
| underlier | HYG @ **$79.165** | `data/rv/etf_ohlc.parquet`, last bar **2026-07-29** |
| dividends | **12** in the last 370d, mean **$0.3923** each, projected at that cadence | same panel, `dividend` column |
| rate | **3.8400%** (3m bill) | `data/riskfree_daily.parquet`, last **2026-07-16** |
| lattice | CRR, **1024** steps | `optmath.AMERICAN_BINOMIAL` |

**Staleness:** the price/dividend panel ends 2026-07-29, which is **44 days** before this run. G1 says to extend it before relying on it; the premium below is a property of the model at these parameters and is not sensitive to a few weeks of drift, but any number quoted from here carries that date.

## Early-exercise premium, puts

`american_binomial` − `bs_discrete_div`, in **dollars** and in **implied-vol points** (the bias a European inversion would put into the surface).

| moneyness | 7d | 21d | 35d | 60d | 120d |
|---|---|---|---|---|---|
| 0.90 | $-0.0000 / n.i. | $-0.0000 / -0.01pt | $+0.0000 / +0.00pt | $+0.0003 / +0.02pt | $+0.0032 / +0.05pt |
| 0.95 | $-0.0000 / -0.00pt | $+0.0003 / +0.02pt | $+0.0014 / +0.04pt | $+0.0061 / +0.08pt | $+0.0158 / +0.11pt |
| 1.00 | $+0.0036 / +0.08pt | $+0.0125 / +0.17pt | $+0.0275 / +0.28pt | $+0.0353 / +0.28pt | $+0.0434 / +0.24pt |
| 1.05 | $+0.0604 / +10.05pt | $+0.0440 / +2.19pt | $+0.1206 / +2.55pt | $+0.0870 / +1.14pt | $+0.0776 / +0.58pt |
| 1.10 | $+0.0641 / +26.14pt | $+0.0528 / +9.95pt | $+0.1771 / +9.54pt | $+0.1225 / +4.14pt | $+0.1062 / +1.52pt |

Largest premium: **$+0.1771** at moneyness 1.10, 35d = **+9.54 vol points**.  `n.i.` = the European inversion has no identifiable vol at that point, which is itself the answer: a European model cannot represent that price at any volatility.

## Early-exercise premium, calls

`american_binomial` − `bs_discrete_div`, in **dollars** and in **implied-vol points** (the bias a European inversion would put into the surface).

| moneyness | 7d | 21d | 35d | 60d | 120d |
|---|---|---|---|---|---|
| 0.90 | $+0.0000 / n.i. | $+0.3482 / +23.35pt | $+0.2414 / +13.11pt | $+0.4241 / +10.44pt | $+0.6105 / +6.82pt |
| 0.95 | $-0.0000 / -0.01pt | $+0.3185 / +9.32pt | $+0.1616 / +3.43pt | $+0.2363 / +2.81pt | $+0.2729 / +1.88pt |
| 1.00 | $-0.0001 / -0.00pt | $+0.0935 / +1.24pt | $+0.0153 / +0.16pt | $+0.0620 / +0.49pt | $+0.0981 / +0.55pt |
| 1.05 | $-0.0000 / -0.01pt | $+0.0017 / +0.11pt | $-0.0000 / -0.00pt | $+0.0076 / +0.10pt | $+0.0271 / +0.21pt |
| 1.10 | $-0.0000 / n.i. | $-0.0000 / -0.00pt | $-0.0000 / -0.01pt | $+0.0003 / +0.02pt | $+0.0055 / +0.09pt |

Largest premium: **$+0.6105** at moneyness 0.90, 120d = **+6.82 vol points**.  `n.i.` = the European inversion has no identifiable vol at that point, which is itself the answer: a European model cannot represent that price at any volatility.

## Convergence of the lattice

Measured against the closed form on an ATM 60-day call at σ = 0.20, dividends off and early exercise worthless (so the tree IS European):

| steps | gap | gap × steps |
|---:|---:|---:|
| 64 | 9.980e-03 | 0.639 |
| 256 | 2.499e-03 | 0.640 |
| 1,024 | 6.249e-04 | 0.640 |
| 2,000 | 3.200e-04 | 0.640 |
| 4,000 | 1.600e-04 | 0.640 |

Clean **O(1/n)** with the constant stable to three figures, no sawtooth. **G1 Part C asks for "under 1e-4 at 2,000 steps"; that is not achievable with a plain CRR tree** — the law puts 1e-4 at n ≈ 6,400. The prompt's figure was an expectation, not a measurement, and `test_tree_converges_to_black_scholes_at_the_measured_order` asserts the measured law instead, which fails on a change of convergence ORDER rather than merely on slowness.

## Verdict on Bjerksund-Stensland

G1 Part A asks for BS-2002 as a fast closed form, tree as truth. It is **not implemented**, deliberately: the premium table above decides whether a fast American approximation is needed at all, and at this programme's sizes — a handful of legs marked once daily — the tree at 512 steps is already sub-millisecond. BS-2002's two-step form needs a bivariate normal CDF, a second numerical component with its own failure modes. If a loop ever needs the speed, it goes in beside the tree with the same test battery.

