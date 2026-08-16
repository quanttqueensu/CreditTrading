# Niche Edge and Execution Research

**31 July 2026 · credit closed-end fund programme**

Three questions, driven by the fact that live slippage came in at **0.94% per
rebalance against a modelled 0.10%** — 9.4× — which makes execution research
worth as much as signal research right now.

1. Can we cut trading cost without losing the edge?
2. Is there a niche signal inside CEFs we are not capturing?
3. Is there a second, *uncorrelated* sleeve? (Two uncorrelated 0.8s beat one 1.0.)

All work stays medium-frequency: nothing below a 5-day holding period.

---

## 1. EXECUTION — three levers tested one at a time

Baseline is the validated point-in-time engine: net Sharpe 0.82, 24.2 turns/yr,
265bp/yr modelled cost.

| lever | gross SR | net SR | CAGR | maxDD | turn/yr | cost bp |
|---|---|---|---|---|---|---|
| **baseline** hold 5d | 1.26 | 0.82 | 4.85% | −12.0% | 24.2 | 265 |
| no-trade band 0.01 | 1.27 | 0.83 | 4.93% | −12.0% | 23.9 | 261 |
| no-trade band 0.05 | 1.10 | 0.74 | 4.38% | −12.8% | 20.0 | 219 |
| hold 10d | 0.78 | 0.47 | 2.62% | −12.8% | 16.6 | 182 |
| hold 21d | 0.49 | 0.27 | 1.39% | −14.7% | 11.4 | 127 |
| **price-weighted, hold 5d** | **1.37** | **0.98** | **5.87%** | −13.1% | 24.8 | 215 |

### 1a. The no-trade band does almost nothing

Only trading when a position moves materially barely helps (0.82 → 0.83 at a 1%
band) and hurts beyond that. The reason is visible in the weights: the signal
reshuffles the whole cross-section each period rather than nudging individual
legs, so a per-leg band rarely binds. **Rejected.**

### 1b. Holding longer destroys the edge — this is the important constraint

Net Sharpe falls 0.82 → 0.47 → 0.27 → 0.09 as the hold goes 5 → 10 → 21 → 42
days. The signal decays fast.

That is uncomfortable given a 9.4× slippage overrun: we need frequency, and
frequency is exactly what is expensive. **It also means the market-on-close fix
is not optional.** If MOC does not bring realised cost near modelled, this
strategy cannot be traded at the only frequency at which it works. That single
question outranks everything else in this document.

### 1c. Price-weighting is the real execution win — and it is not only execution

Weighting positions by price improves net Sharpe **0.82 → 0.98** and cuts
modelled cost 265 → 215bp.

The cost logic is sound: a one-cent spread on a $4 fund is 25bp, on a $16 fund
6bp, so tilting toward higher-priced funds genuinely reduces cost per unit of
exposure.

**But we checked whether it was a disguised bet, and it partly is:**

| weighting | gross SR | net SR |
|---|---|---|
| equal | 1.26 | 0.82 |
| 1/half-spread | 1.37 | 0.98 |
| **price directly** | **1.36** | **0.97** |
| sqrt(dollar ADV) | 1.29 | 0.87 |
| sqrt(ADV) ÷ price | 1.03 | 0.57 |

1/spread and price are the same thing arithmetically (`half_spread = tick/price`)
and score identically. Dividing the price component back out of ADV **destroys**
the effect (0.57). So it is the price level, not dollar depth.

And **gross** Sharpe improves too (1.26 → 1.36), which a pure cost saving cannot
explain. Higher-priced credit CEFs genuinely revert better. A plausible reason:
low-priced CEFs are typically the ones that have eroded capital through
return-of-capital distributions, so price level proxies for fund health.

**The carry/beta test says it is still alpha, not a risk premium:**

| | alpha | t | R² | factor limits |
|---|---|---|---|---|
| equal-weight | +5.26%/yr | +3.62 | 0.004 | 5/5 pass |
| **price-tilted** | **+6.33%/yr** | **+4.36** | 0.003 | **5/5 pass** |

Better alpha, better t, still market-neutral. **Adopt**, with the caveat that part
of the gain is a fund-quality proxy rather than pure execution, and it should be
re-examined if the fund mix changes materially.

---

## 2. SEASONALITY — the classic CEF anomaly, and it is alive

Average daily change in the discount, pooled across 44 credit CEFs, by month:

| month | bp/day | |
|---|---|---|
| **January** | **+7.71** | discounts narrow hard |
| September | −4.74 | discounts widen |
| all others | −0.88 | |

January versus the rest: **t = +11.75, p = 0.000.**

The textbook mechanism is tax-loss selling: retail dumps losing CEFs into the year
end for the deduction, discounts widen, and the pressure unwinds in January. CEFs
are held overwhelmingly by retail, so this force acts here and essentially nowhere
else in credit.

**Our deployed strategy cannot capture any of it.** The book is dollar-neutral and
cross-sectional, so a move that hits every fund at once cancels between the long
and short legs. That is what makes this worth trading separately rather than
folding in.

---

## 3. THE SECOND SLEEVE — a hedged January basis trade

**Construction.** Long an equal-weight basket of liquid credit CEFs, short a
credit-ETF basket (HYG/LQD/JNK/EMB) at a rolling 252-day hedge ratio. Held in
January only. **Two trades a year.**

| | |
|---|---|
| January hedged basis | **+11.71bp/day, t = 3.99** |
| Sharpe while on | 2.94 |
| Hit rate | 61% of days, **20/23 Januaries** |
| Mean January | +2.43% (median +1.99%) |
| Net of 60bp round-trip costs | +1.75%/yr |
| **Correlation with the deployed strategy** | **−0.001** |

December is the other half of the mechanism: **−8.72bp/day, t = −3.24.** The
selling pressure and its reversal are both visible.

### Robustness — three ways it could be fake, all tested

**Is it the discount, or just a January bond rally?**

| January, per day | | |
|---|---|---|
| price − NAV (the discount closing) | **9.66bp** | **t = 4.06** |
| NAV alone (the bonds) | 3.11bp | t = 2.72 |
| credit ETF hedge alone | 1.77bp | t = 0.95 |

The discount is the dominant term and the credit hedge is insignificant. There is
a smaller genuine NAV effect too, which the trade also picks up — worth stating
rather than claiming the whole move is discount.

**Is it unremoved leverage?** No. Deliberately over-hedging still leaves it
significant: 1.0× → +10.77bp (t 3.94), 1.5× → +9.88 (t 3.16), 2.0× → +8.99
(t 2.42). Median estimated beta is 0.91.

**Is it one outlier?** 2009 returned +19.0%. Removing it makes the result
*stronger*, because 2009 was mostly variance:

| sample | mean | median | positive | t |
|---|---|---|---|---|
| all years | +2.43% | +1.99% | 20/23 | 2.77 |
| **ex-2009** | +1.67% | +1.65% | 19/22 | **3.57** |
| ex-crisis 08–09 | +1.45% | +1.30% | 18/21 | 3.36 |
| 2013 onward | +1.35% | +1.65% | 11/14 | 2.29 |
| 2019 onward | +1.23% | +1.65% | 7/8 | 1.55 |

By year: 2023 +3.7%, 2024 +2.4%, 2025 +1.0%, 2026 +0.7%. Still working, though
the magnitude has shrunk — consistent with a real effect being gradually competed,
not with a dead one.

### What it is worth in the portfolio

On the conservative ex-crisis sample: **mean +1.45%/yr, sd 1.97%, annual Sharpe
0.73.**

```
deployed 0.82  +  seasonal 0.73  at correlation 0.00  ->  combined 1.10
```

That is a bigger improvement than we could plausibly get by making the main
strategy better, which is the entire argument for hunting orthogonal sleeves
rather than better ones. It also holds capital roughly one month a year, so it
barely competes for margin with the daily book for the other eleven.

**September is the mirror trade** (short the basis, −6.59bp/day, t −2.32) but it
is weaker and we have not robustness-tested it. Not proposed.

---

## 4. RECOMMENDATIONS

**Adopt now:**

1. **Price-weight the live sleeve.** Net Sharpe 0.82 → 0.98, alpha t 3.62 → 4.36,
   modelled cost −19%, still 5/5 on factor limits. Defensible on cost grounds
   before any alpha argument.

**Do not adopt:**

2. **No-trade bands** — no benefit, the signal reshuffles rather than nudges.
3. **Longer holds** — halving turnover roughly halves the Sharpe. The edge is
   genuinely short-horizon.

**Build next, pending live evidence:**

4. **The January basis sleeve.** Uncorrelated (−0.001), robust to outlier removal,
   robust to over-hedging, mechanism confirmed in both December and January, and
   two trades a year makes it almost free to run. Next January is five months
   away, so there is ample time to pre-register it properly rather than rush it.

**The question that outranks all of the above:**

5. **Does market-on-close fix the 0.94% slippage?** The hold-period table shows the
   edge lives at 5 days and dies by 21. So we cannot trade our way out of a cost
   problem by slowing down — if realised cost stays near 1% per rebalance, this
   strategy is uneconomic at the only frequency where it works. **Monday's closing
   auction fills answer this**, and no further signal research should be prioritised
   above reading them.

---

## 5. DISTRIBUTION EVENTS — tested, and it is a null (D1)

**11,988 distribution events across all 44 funds, 1987-2026**, with exact-day
price joins, were staged and tested. After screening out 269 special/off-cycle
payments (which the raw `is_cut`/`is_raise` flags misclassify) and one BIT split
artifact, and restricting to liquid funds: **299 cuts, 276 raises.**

**Hypothesis:** CEFs are held for income by retail investors who screen on
headline yield, so a distribution cut removes the fund from its own holder base's
buy lists. That selling is about the payout, not the portfolio, so the discount
should widen and then revert.

**Result: it does not happen.** Measured against an unchanged-distribution control
group (which captures the ordinary mechanical ex-date effect), cuts move the
discount by +10 to +29bp -- *narrowing*, the opposite of the hypothesis -- and the
move is not monotone in the size of the cut:

| cut size quartile | median cut | discount change 20d |
|---|---|---|
| Q1 biggest | -56.5% | +21.2bp |
| Q2 | -16.2% | +6.0bp |
| Q3 | -6.7% | **-22.5bp** |
| Q4 smallest | -3.9% | +4.4bp |

Dose-response slope is -1.34bp per 1% of cut at **t = -1.77** -- wrong sign for
the thesis and not significant.

Raises look stronger at +106bp by day 40 (t 3.85), but the discount was already
widening *before* the event (-79bp at k=-10, t -4.18). That pre-event drift means
what follows is ordinary mean reversion, which our main strategy already trades.
There is no separate edge here.

**Verdict: D1.** Recorded so it is never re-tested without new data.

**One useful by-product.** The staging run confirmed our price series is RAW, not
dividend-adjusted: ex-date moves cluster at -1x the distribution paid. Had it been
adjusted, every historical discount would have been distorted and the live
strategy would rest on bad data. Worth having checked.

**Also learned:** yfinance classifies all 44 CEFs as equities, so fund size,
expense ratio and category are unavailable for the entire universe. The only
structural facts obtainable are `debtToEquity` (a real leverage proxy, present for
29 of 44 -- the Nuveen munis cluster at 66-72) and `priceToBook` (effectively a
discount snapshot, 32 of 44). **Leverage is untested and is the most promising
remaining structural variable.**

---

## 6. STILL OPEN
- **Activist involvement.** Saba and Bulldog campaign to force discounts closed.
  Public 13D filings would date the events. Not staged.
- **Rights offerings, tender offers, fund mergers and open-endings** — all
  mechanically move a discount to zero on a known date. Not staged.
- **September mirror trade** — measured, not robustness-tested.

Trial counter on this data source: **10 → 16.** The deflated-Sharpe bar rises with
each, which is why this document stops at recommendations rather than continuing
to search.
