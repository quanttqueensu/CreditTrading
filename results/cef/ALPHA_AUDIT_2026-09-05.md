# Independent audit of the cheap/rich signal — 2026-09-05

Re-derived from `data/cef/cef_prices.parquet` + `cef_nav.parquet` for the 17
frozen names. 6,989 days, 1998-11-18 to 2026-09-02. Not a replication of
`scripts/cef/validate.py`; an independent build.

## Verdict

There is a real edge, it is distinct from price reversal, it is not credit beta,
and it is not carried by one name. **Whether it is harvestable is entirely a
question of execution cost: breakeven is 32.6bp per unit turnover.**

## Information coefficient (Spearman, non-overlapping)

Expected sign NEGATIVE (high z = rich = underperforms).

| horizon | traded at close t (LOOKAHEAD) | traded at close t+1 (REAL) |
|---|---|---|
| 1d  | −0.077 (t −17.5) | −0.053 (t −12.1) |
| 2d  | −0.101 (t −15.8) | −0.074 (t −11.6) |
| 5d  | −0.126 (t −12.1) | −0.096 (t −9.4) |
| 21d | −0.146 (t −6.6)  | −0.131 (t −6.1) |

The sleeve rebalances every 2 days and executes T+1, so the operative cell is
**−0.074, t −11.6, 57.9% of periods correctly signed**.

**Lookahead is present but not load-bearing.** These funds publish NAV after the
close, so a discount using same-day NAV is not knowable at that close. Lagging
execution by one day costs ~31% of the 1d IC and only ~10% of the 21d IC. The
edge is not an artefact of the timing.

## Confounds

- **Price reversal control**: the identical construction on a z-score of log
  price gives IC −0.046 (t −6.7) versus the discount's −0.074 (t −11.6). The two
  IC series correlate 0.575. Reversal explains part of it; the discount adds
  genuine incremental information.
- **Beta**: regressed on the equal-weighted universe — beta **+0.013**, R²
  **0.0008**, alpha +17.7%/yr. Not credit beta in disguise.
- **Concentration**: leave-one-out gross Sharpe spans 2.23 (without PFN) to 2.93
  (without PHK) against 2.49 for the full universe. No single fund carries it;
  PHK actively hurts.

## Economics (2-day rebalance, dollar-neutral, 6% vol target, T+1)

| | ann return | vol | Sharpe | max DD |
|---|---|---|---|---|
| gross | 17.68% | 6.11% | **2.90** | −7.1% |
| net @ 5bp | 14.97% | 6.09% | 2.46 | −8.0% |
| net @ 15bp | 9.55% | 6.09% | 1.57 | −10.3% |
| net @ 30bp | 1.43% | 6.17% | 0.23 | −33.9% |
| net @ 50bp | −9.40% | 6.44% | −1.46 | −93.1% |

Turnover averages 21.5% of gross per day — **54x annualised**. That is what makes
cost decisive.

**Breakeven 32.6bp** full sample, **28.9bp** for 2021-2026.

**Where realised cost actually sits is NOT yet knowable and nothing here should
be read as measuring it.** There has been exactly one MOC session (2026-09-01,
15 fills). Its 3.4bp is a single observation whose dispersion was ±25bp per
fill, much of it penny-rounding on $4-12 names; treating it as an estimate of a
cost that must hold over 54x annual turnover would be false precision.

The breakeven number is a different kind of quantity and does stand: it derives
from turnover and gross return, both measured over 27 years, and is a property
of the strategy rather than of the fill data. So the threshold is known; which
side of it the book sits on is an open question requiring many more sessions.

The only cost figure with real weight so far is the counterexample: the
2026-07-31 overnight market orders realised 100.5bp, comfortably past breakeven
in the wrong direction. That is why execution method was changed, and it is
evidence about a method that is no longer used.

## Stability

| period | mean IC | t | % correctly signed |
|---|---|---|---|
| 1998-2004 | −0.094 | −3.73 | 56.1% |
| 2005-2010 | −0.086 | −6.78 | 58.7% |
| 2011-2015 | −0.091 | −6.79 | 62.2% |
| 2016-2020 | −0.047 | −3.68 | 55.0% |
| 2021-2026 | −0.064 | −4.67 | 56.2% |

Present in every period, roughly a third weaker since 2016. Gross Sharpe for
2021-2026 alone is 2.85 — the decay is in the IC, not yet in the economics.

## What this audit does NOT establish

1. **Survivorship.** The panel contains only funds alive today. Every CEF that
   closed or merged across 27 years is absent. This biases the result upward by
   an amount these files cannot measure. PDO has 1,402 days of history; MHD has
   6,989 — the panel is badly unbalanced.
2. **This is a straight full-sample backtest**, not walk-forward. The z-window,
   vol target and rebalance cadence were all chosen with sight of this data.
   `RESEARCH_STATE.md` reports 9/9 purged walk-forward blocks positive; that was
   not re-run here.
3. A gross Sharpe of 2.90 on a 17-name book should be treated as an upper bound,
   not an expectation.
