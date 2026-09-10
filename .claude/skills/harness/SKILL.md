---
name: harness
description: How to run a backtest or policy comparison correctly in this repo — the canonical evaluate(), the shift(2) convention, turnover matching, the cost grid, eras, and the reporting template. Use before writing any backtest, signal evaluation, or policy comparison, and when a result needs to be comparable to existing numbers.
---

# The research harness

**Do not build a new backtester.** Use the canonical one and extend it visibly.

```python
from scripts.cef.band_frontier import build_targets, band, calendar, evaluate

T, R  = build_targets()        # frictionless daily targets as the sleeve builds them
H_live = band(T, 0.048)        # the live policy
H_old  = calendar(T, 2)        # the previous configuration
res    = evaluate(H, R)        # applies H.shift(2): decide t, MOC fill t+1, earn t+2
```

`evaluate()` in `scripts/cef/band_frontier.py` is the reference implementation of
the execution convention. Anything scored differently is **not comparable to any
number in this repo**.

## The rules, condensed

| # | rule |
|---|---|
| **H1** | Execution is **`shift(2)`**. Decide *t*, MOC fill *t+1*, earn *t+2*. |
| **H2** | **Turnover-matched comparisons only** — match turn/yr within 5%, compare there. |
| **H3** | **Cost grid 5/15/30bp** on every table. The answer must not flip sign across it. |
| **H4** | **Borrow charged separately and labelled.** One day of fees on 21 years of history is a counterfactual — say so at the top of the table. |
| **H5** | **Eras** 2005–09, 2010–14, 2015–19, 2020–22, 2023–26. Report era turnover sd/mean. |
| **H6** | **IC** = Spearman(signal *t*, forward 2-day return from *t+2*), **non-overlapping**, expected negative, SEs **clustered by date**. |
| **H7** | **No lookahead.** State the alignment in a comment; assert it at runtime. |
| **H8** | **No sweeping and picking.** Derive, then verify it lands on a plateau. |
| **H9** | **The 27 untouched names** are the comparison set. Trading one consumes it. |
| **H10** | **Count trials** — CEF (48) or GAMMA (0), each with its own √(2 ln N) bar. |
| **H11** | **Pre-register** before the session that trades it. |
| **H12** | **Negative controls.** Test where the mechanism *cannot* operate. |
| **H13** | **Time holdout** — fit before 2023-01-01, report a 2023–26 holdout row. |
| **H14** | **No decision rule keys on a number written in a document.** Re-measure. |
| **H15** | **Total returns.** If the distribution panel cannot cover a name-date, **raise**. |

## Why each convention exists

**`shift(2)`** — the signal needs the fund's NAV, which does not exist until after
the close, so the decision is necessarily made in the evening and the earliest
possible fill is the *next* closing auction. `validate.py` once used `shift(1)`,
entering at day *t*'s close on day *t*'s NAV: gross SR 1.26 → 0.95, net at hold=5
**0.82 → 0.51**.

**Turnover matching** — a construction that trades more looks better gross and
worse net. Neither is the point. The band beat the calendar at *matched* turnover
on *both*, which is what made it a real result.

**The cost grid** — cost is the input we do not know (n=1 for the live method,
dispersion ±93.8bp). Prefer the policy least sensitive to it. Every calendar
configuration goes negative at 30bp; bands ≥4.8% never do. That robustness
argument, not an argmax, is why the band is live.

**Deriving, not sweeping** — the band width came from the cube-root law
`h* = (3cσ_w²/2κ_w)^(1/3)` on measured target-weight dynamics: 4.26% at 15bp,
4.85% at 22bp, and the scaling verifies exactly (`h(30)/h(15) = 1.260` vs
`2^(1/3) = 1.2599`). **6.4% topped the swept column and was deliberately not
chosen.** `z_window = 63` was chosen the other way and failed out of sample.

**Pre-2013 is thin** — 2411 dates are flat because fewer than `min_names` clear the
ADV filter. Full-sample turnover is diluted ~44% and Sharpes depressed by
√(3041/5452). This applies to every row equally, but know it before quoting.

## Reporting template

Every comparison table carries:

```
policy            gross SR   turn/yr   net@5bp   net@15bp   net@30bp
--------------------------------------------------------------------
reference          x.xx       xx.x      x.xx      x.xx       x.xx
candidate          x.xx       xx.x      x.xx      x.xx       x.xx      <- matched
```

plus an era block (five rows, with turnover sd/mean), a fit row and a **2023–26
holdout row**, and a one-line note naming the panel and **its last date**. Borrow,
if charged, gets its own labelled column and a counterfactual caveat.

## Before you publish a number

- Which counter did this spend, and what is that counter's bar now?
- Does it survive the negative control?
- Does it survive the holdout?
- Is the panel current? *Stale is a form of wrong.*
- Can someone reproduce it from the script you named? Run `/repro` on your own
  result before you believe it.
