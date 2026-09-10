---
paths:
  - "scripts/**"
  - "src/backtest/**"
  - "src/analysis/**"
  - "src/strategies/**"
  - "notebooks/**"
---

# The research harness — H1 to H15

These are the rules every research prompt in `docs/prompts/` inherits. A result
that breaks one of them is not comparable to any number in this repo.

**Do not build a new backtester.** Use the canonical one and extend it visibly:

```python
from scripts.cef.band_frontier import build_targets, band, calendar, evaluate
T, R = build_targets()          # frictionless daily targets as the sleeve builds them
H_live = band(T, 0.048)         # the live policy
H_old  = calendar(T, 2)         # the previous configuration
res    = evaluate(H, R)         # applies H.shift(2)
```

**H1. Execution convention is `shift(2)`.** Decide at *t*, MOC fill at *t+1*, earn
the *t+2* return. `validate.py` once used `shift(1)` — entering at day *t*'s close
on day *t*'s NAV, which publishes after that close. Cost: gross SR 1.26 → 0.95, net
SR at hold=5 0.82 → 0.51.

**H2. Turnover-matched comparisons only.** Find the band width or cost coefficient
that matches the reference's turn/yr within 5%, and compare there.

**H3. Cost grid 5 / 15 / 30bp** on every table, plus the measured per-name per-era
column where it exists. **The answer must not flip sign across the grid.**

**H4. Borrow is charged separately and labelled.** One day of measured fees applied
to 21 years of history is a counterfactual, not a backtest. Say so at the top of the
table. Borrow scales with *holdings*, not turnover — trading less does not reduce it.

**H5. Eras: 2005–09, 2010–14, 2015–19, 2020–22, 2023–26.** Pre-2013 is thin (2411
dates flat). Report era turnover sd/mean.

**H6. IC** is Spearman between the signal at *t* and the forward 2-day return
starting *t+2*, **non-overlapping**, expected negative, standard errors **clustered
by date**, never naive.

**H7. No lookahead.** Every estimated quantity uses data strictly before the date it
is used on. State the alignment in a comment. Assert it at runtime.
`src/backtest/guard.py` exists for this.

**H8. No sweeping and picking.** Derive parameters, then check they land on a
plateau. `z_window = 63` was chosen as the argmax of a swept column on 2005–2023
with the holdout sealed; the holdout was opened hours later and it failed
(gross 1.75, **net −0.298**). Reverted to 252. The band width was derived from the
cube-root law `h* = (3cσ_w²/2κ_w)^(1/3)` and 6.4% — which topped the swept column —
was deliberately not chosen.

**H9. The 27 untouched names** are the comparison set. Any specification change is
run on them once, on the combined spec, before promotion. **Trading any of them
consumes the set.**

**H10. Count trials.** Two counters, each with its own √(2 ln N) bar: **CEF (48)**
and **GAMMA (0)**. Say which one you increment. The combined book is judged on the
joint record.

**H11. Pre-register before the session that trades it.**
`results/cef/PREREG_BAND_2026-09-06.md` is the shape. Every adoption names the live
statistic and horizon that would reverse it. Use `/prereg`.

**H12. Negative controls.** If a mechanism says an effect lives in munis, test it in
HY too. If it is equally strong where the mechanism cannot operate, it is not what
you think. The Treasury control killed `leadlag`; the CEF sector's own group returns
were the sharp control that *confirmed* the discount alpha.

**H13. Time holdout.** Every estimated quantity is fitted on data before
**2023-01-01**; every table shows a fit row and a 2023–2026 holdout row. Rolling
estimators are fine on the holdout; *choosing* anything with sight of 2023–26 is not.

**H14. No decision rule may key on a number written in a document.** Every figure in
the docs is a starting observation with a date and a method. The test: *could this
rule still be executed correctly by someone who deleted every number from the
document?* If not, it rests on a number instead of a method.

**H15. Returns are total returns.** If the distribution panel cannot cover a
name-date, the harness **raises**; it never falls back to price returns silently.

## The failure taxonomy

Verdicts are D1–D7 (`docs/RESEARCH_AND_METHODOLOGY.md` §2.2). The common ones here:

- **D1** — no gross edge before costs.
- **D2** — gross edge positive, net ≤ 0. Any D2 reached on full-sample costs must be
  re-opened: modern-era cost is 1.73bp/trade against a full-sample 6.36bp, and
  charging 2007 illiquidity to a 2024 signal manufactures a fake obstacle.
- **D4** — it is a risk premium in costume. Alpha *t* must clear 3.0 with factor
  betas ≤ 0.10.
- **D6** — real but conditional; needs a regime gate and sizing to fraction-of-time-on.
- **D7** — infeasible on the available data.

## What "finding alpha" means here

Three distinct jobs. Say which one you are doing:

1. **Raise BR** without lowering IC — make seventeen names more than one bet.
   Effective breadth is **1.17** today because 92.5% of variance is muni-vs-taxable.
   This is the biggest hole in the strategy.
2. **Raise TC** — trade less, trade cheaper, short what can be borrowed, size to the
   right volatility, never send an order the strategy did not ask for, and measure
   execution fast enough to act on it. TC is ~37% against a typical 0.3–0.8. This is
   the highest value per hour.
3. **Add a new IC source** only where a *mechanism* says one should exist and the
   current signal is provably blind.

Cost converges ~60× faster than Sharpe: at ~15 fills/session, 60 sessions gives
SE ≈ 0.84bp against a 32.6bp breakeven. Measure what converges fast.
