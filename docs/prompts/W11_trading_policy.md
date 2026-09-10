# W11 — The policy layer: per-name bands, conviction, a turnover controller, a cost tilt

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `00_BRIEF.md` §1 (TC is the highest-value work per hour), §5.
**Lever:** TC — the holding period decided by the signal and by each fund's own
dynamics instead of by one constant, and net Sharpe made robust to being wrong
about cost.
**Trials:** 2 on the **CEF** counter. Parts A and B are **one** pre-declared
six-cell grid = 1 trial. Part C (turnover controller) = 1. Part D (the cost
tilt) folds into the grid as a seventh declared cell, not a separate trial —
**declare it before running or it costs its own.**
**Prerequisites:** W1, W4 (the surviving IC and the total-return convention),
W7 Part C (per-name, per-era costs — the bands below should be derived from
measured spreads, not only from the one-cent tick).
**Supersedes:** P5.7, P6.5, P5.3, P1.8.

---

## Paste from here

You are a quant researcher on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md`, then:

1. `docs/EXIT_RESEARCH_2026-09-07.md` in full. The measured optimum of expected
   return per unit time, net of a 30bp round trip, by entry |z|:

   | entry \|z\| | optimal hold | net bp/day | n |
   |---|---:|---:|---:|
   | 0.5–1.0 | 60d | +0.02 | 1,140 |
   | 1.0–1.5 | 60d | +0.38 | 1,129 |
   | 1.5–2.0 | 8d | +2.31 | 909 |
   | 2.0–2.5 | 5d | +6.01 | 624 |
   | 2.5–4.0 | 2d | +12.31 | 375 |

   *"Optimal holding period shortens as conviction rises"*; a stop-loss destroys
   value (adverse moves have the highest forward return, t 9.4).
2. `docs/PLAN.md` §3.1 — **every |z| threshold lowers portfolio Sharpe** (0.81 →
   0.40 → 0.29 → 0.27). Per-name alpha and portfolio Sharpe are different
   objects: **conviction may change the holding period, never the membership.**
3. `docs/PER_NAME_ARCHITECTURE.md` §3–§4 and §7 Phase A: the cube-root law
   `h* = (3·c_i·σ_w,i² / 2κ_w,i)^(1/3)` evaluated with each fund's own measured
   target-weight volatility, reversion rate and tick cost gives bands from 1.07%
   (MHD) to 7.35% (PHK) — *"a 6.9× spread where we currently apply one
   number"* — derived with zero fitted parameters and **not yet shown to beat
   4.8% on the panel**. The resolution table:

   | parameter | mean EB weight w | group R² | resolution |
   |---|---:|---:|---|
   | κ (reversion rate) | 0.86 | 0.12 | per-name |
   | σ_d (discount vol) | 0.96 | 0.24 | per-name |
   | σ_P (price vol) | 0.68 | **0.51** | **group** |

4. `results/cef/ESTIMATOR_NOTE.md` "HOLDOUT OPENED — THE CHANGE FAILED": the
   signal generalised (gross 1.23 → 1.75 out of sample); **turnover did not**
   (45.3×/yr in sample → 102.6× in the holdout, 2.3×), and costs consumed 117%
   of gross. *"A configuration chosen on net Sharpe is implicitly chosen on a
   turnover estimate. Turnover is far less stable out of sample than the signal
   is."*
5. `results/cef/PREREG_BAND_2026-09-06.md` (how 4.8% was derived; the plateau
   4.8–9.6%), `scripts/cef/band_frontier.py::band()`, `exit_study.py`,
   `per_name_resolution.py`.
6. `results/cef/research/NICHE_EDGE_RESEARCH.md` §1c and §4 item 1 — the price
   tilt, measured 2026-07-31 in the 5-day-hold era: net Sharpe 0.82 → 0.98,
   gross 1.26 → 1.36, modelled cost 265 → 215bp/yr, alpha t 3.62 → 4.36, 5/5
   factor limits, marked **Adopt** "with the caveat that part of the gain is a
   fund-quality proxy rather than pure execution". **Never deployed.**

### The theory this whole prompt rests on, and its limits

Constantinides (1986, JPE 94:842) shows that under proportional transaction
costs the optimal policy is a **no-trade region** around the frictionless
target, that the welfare loss from the friction is only second-order even
though optimal trading frequency falls sharply, and that the asymptotically
optimal bandwidth scales as **cost^(1/3)** — the cube-root rule the band's
pre-registration already uses. Davis & Norman (1990) give the same object as a
free-boundary wedge around the Merton line with trading only at the boundaries.
Leland (1985) offers the alternative of an adjusted volatility, and Kabanov &
Safarian (1997) showed the limiting hedging error under Leland's strategy is
non-zero, contradicting the original convergence claim — **so use the no-trade
region, not a vol adjustment, and cite why.** These results are asymptotic and
single-asset; our book is 17 correlated names, which is exactly why W12's
Σ-aware no-trade region can beat a scalar band, and why nothing here is allowed
to be swept into agreement.

---

## Part A — The band becomes a vector (in the grid; no separate trial)

### Why the policy layer is the right place for per-name treatment

The z-score already carries each fund's κ^(1/2) in its denominator (the OU
stationary-variance argument), which is why adding κ to the *score*
double-counted and lost. **The trading rule carries nothing**: one width, one
implied holding period, for a $4.50 fund with a 22bp tick and a 56-day
half-life and for a $15 fund with a 6.5bp tick and a 23-day half-life — and for
a name at |z| = 3 that will converge in days and one at |z| = 0.7 that needs two
months to clear the spread. Policy derived from measurement costs no trials.

**Variant A, conviction (per signal):**

    b_i,t = b₀ · (h*(|z_i,t|) / h̄)^(1/3)

with `b₀` = 4.8%, `h̄` the live band's **measured** hold from the harness, and
`h*(·)` the step function from the exit study above (or its monotone smooth —
fit an isotonic decreasing function through the five points; state which).
Because `h*` is 60d below |z| = 1.5 and 2–8d above, this **widens** the band on
weak signals (hold longer, trade less) and **narrows** it on strong ones
(harvest and release). `|z_i,t|` is the current signal, so as a position
converges its band widens and it is left alone — the intended behaviour. Clip to
[1.0%, 12.8%], the evaluated range.

**Variant B, per-name structure:**

    b_i = (3·c_i·σ_w,i² / 2·κ_w,i)^(1/3)

with `c_i` the name's half-spread — **use W7 Part C's Corwin–Schultz estimate
where it and the one-cent tick disagree by more than 2×, and say which you
used per name** — and `σ_w,i`, `κ_w,i` the daily volatility and AR(1) reversion
of the name's *target-weight* series, estimated on a trailing 504-session window
ending the day before, refit monthly, empirical-Bayes shrunk toward the pooled
values. Report raw and shrunk. Clip as above.

**Variant C:** A's factor applied to B's base.

**The gate on Variant B, and it is owned elsewhere.**
`σ_w,i` and `κ_w,i` — the volatility and AR(1) reversion of each fund's own
*target-weight* series — are **not computed anywhere in this repo today**;
`per_name_resolution.py` computes κ, σ_d and σ_P only. **`perfund/F2` Part C
builds them**, with the Kendall small-sample bias correction and the
pre-registered observation budget (a 25-day half-life needs ≥ ~1,854 paired
observations for ±20% precision, and **PDO has 1,407**), and it hands the gate
here: **if the EB weight w < 0.7 the per-name band uses the shrunk values; if
w < 0.5 the per-name band is not estimable and Variant B does not run at all.**
Consume F2's `results/cef/PER_NAME_DYNAMICS_<date>.md` rather than re-deriving
it, and record which funds were shrunk to the pooled value and why.

**The harness generalisation — and a bug you must fix first.**
`scripts/cef/band_frontier.py::band()` is written for a scalar `b` and is
**broken for a vector**, verified 2026-09-09:

```python
cur[mv] = A[i][mv] - np.sign(gap[mv]) * b      # line 96
```

`mv = np.abs(gap) > b` broadcasts a vector `b` correctly, and `np.sign(gap[mv])`
has length `mv.sum()`, but `b` still has length `n_cols`. Passing
`np.array([0.01, 0.05, 0.20])` to a 3-column frame raises
`ValueError: operands could not be broadcast together with shapes (2,) (3,)`.
The one case where it does **not** raise is the degenerate one where every name
breaches on every date — so it can silently return a wrong-but-plausible answer
rather than failing. **The same line is duplicated at
`scripts/cef/joint_cost_optimiser.py:305` inside `band_hard_exit`; fix both.**

The fix is `* b[mv]`. Generalise to `band(T, B)` where `B` is a scalar, a
per-name Series, or a DataFrame of widths aligned to `T`. Then prove
equivalence three ways before using it: `band(T, 0.048)` must be byte-identical
to `band(T, Series(0.048))` and to `band(T, DataFrame(0.048))`, and a
regression test must reproduce **whatever the live scalar band produces on the
current harness at the time you make the change** — capture those numbers first,
then assert the generalised function reproduces them exactly.

**Do not pin the historically published figures into the test.** W4's
total-return correction changes the return series, so gross, net and turnover
all move; a test asserting the old numbers would fail by design and would then
be "fixed" by someone loosening it. The invariant that matters is *scalar and
vector forms agree*, not any particular level. **Write the failing-vector test
first, so the bug cannot come back.**

---

## Part B — Group-level price vol in the weights (in the grid)

The live weights are `w_i ∝ s_i` in score units. In return units the Grinold
weight for a diagonal risk model is `w_i ∝ α_i/σ_i² = IC·σ_i·s_i/σ_i² =
IC·s_i/σ_i`: a name's weight should scale **inversely with its price
volatility**, so a z = −2 PIMCO fund at 21% vol and a z = −2 muni at 12% vol
carry equal *risk*, not equal dollars. Today the dollar-equal book puts nearly
twice the risk into the multi name.

Three variants: `vol_scaling: "none"` (live); `"group"` with the group's
trailing 252-day mean price vol (shift 1, refit monthly); `"name"` per name —
**which the resolution table predicts should be worse than group** (more
parameters, no more information), and which is therefore a control row outside
the grid, not a candidate.

Note the interaction with W10 Part C: group vol scaling changes the implied
between/within mix (munis get more dollars per unit z). Report the implied
between share under each variant. **Do not estimate group statistics for the
loan group (n = 1); it inherits pooled, explicitly in code.**

### The grid — one trial, six cells, declared before running

{`none`, `group`} × {scalar band, conviction band, per-name band}, all
turnover-matched to 17.6×/yr, one table. **Do not run the 3×3 and do not add
cells.** The name-level vol scaling and Part D's tilt-only row are controls
outside the grid.

| policy | turn/yr | hold | gross | net@5 | net@15 | net@30 | net of borrow | era sd/mean | 2013–16 net@15 | fit | holdout |
|---|---|---|---|---|---|---|---|---|---|---|---|
| band 4.8%, no vol scaling (live) | *re-measure* | | | | | | | | | | |

**Fill the baseline row by running it, not by copying it.** The figures the repo
has published for the live band (gross ≈1.16, turn ≈17.6, net@15 ≈0.66) were
computed on the price-return convention W4 replaces; every one of them moves.
Re-measure the baseline on the same harness, same day, same convention as the
variants, or the comparison is against a book that no longer exists.

Each variant at its natural turnover **and** rescaled to match 17.6×/yr within
5%; report both rows. Plus: the distribution of realised holding periods by |z|
bucket under the conviction band — **it should reproduce the exit study's
optimum, which is the sanity check** — and PHK's realised turnover under the
per-name band, which should fall about 4×.

**Decision rule, committed before running.** Adopt the cell that improves net@15
**and** net@30 by ≥ 0.05 at matched turnover, with gross not lower by more than
0.03, era sd/mean of turnover not worse than the band's by more than 5 points,
and the holdout row agreeing in sign. **Ties go to the simpler cell** (fewer
per-name parameters; between conviction and per-name, prefer per-name, because
it uses no signal-dependent width). If no cell clears, keep 4.8% and record it.

Spec keys `band_policy: "scalar" | "conviction" | "per_name" | "both"` and
`vol_scaling: "none" | "group"`, absent = live, no-op proven. Readouts over 40
armed sessions: realised holding period by name and by |z| bucket, and realised
risk share by group. **Not P&L.**

---

## Part C — Turnover targeting (trial: 1)

### The idea

Vol targeting exists because volatility does not generalise; it cut the worst
drawdown from −27% to −12%. **Nothing analogous exists for turnover, and
turnover is the quantity that actually failed a holdout.** Turnover targeting:
measure trailing realised turnover, adjust the trading-cost knob so expected
turnover hits a **budget** τ*. Then, whatever the true cost is, the book trades
a known amount, and net Sharpe at any cost level is gross minus a known drag —
**the sign can no longer flip inside a plausible cost range, because the
turnover is pinned.**

Two knobs, one controller each: the band width `b_t` (live construction) and
the cost coefficient `c_t` (inside W12's joint construction).

### The controller, derived not tuned

With `τ̂_t` the trailing 63-session realised turnover (annualised, one-way, the
harness definition) and τ* the budget:

    log b_{t+1} = log b_t + g·(log τ̂_t − log τ*)

The gain `g` is derived from the measured turnover-to-width elasticity
`ε = ∂log τ / ∂log b` (measure it from the band frontier across widths 1.6%,
2.4%, 4.8%, 6.4%, 9.6%) and the window W = 63: a first-order controller with
correction half-life equal to the window has `g = −(1 − 2^(−1/W))/ε`. **Show the
arithmetic; do not sweep g.** Bounds: `b ∈ [2.4%, 9.6%]` (the measured
plateau's edges), `c ∈ [5, 60]`bp. Log every update and every bound hit.

**τ\* is derived from the plateau, not from the argmax.** The frontier shows
net@15 flat from 4.8% to 9.6% (17.6 to 9.8×/yr) and net@30 positive only from
4.8% up. The budget is the turnover at the **lower edge of the cost-robust
plateau**, 17.6×/yr — which is also the live band's expectation. State that it
is a choice on the plateau and why the lower edge: it keeps the most gross
while never flipping sign at 30bp.

Start: `b₀` = 4.8%, `τ̂` seeded from the harness on the first 63 sessions (no
lookahead; it uses only past turnover).

### The tests

1. **Full sample.** Fixed band 4.8% vs turnover-targeted band; fixed `c` vs
   targeted `c` in the joint optimiser. Report gross, turn/yr, hold,
   net@5/15/30, net of borrow, by era, fit and holdout, and era sd/mean of
   turnover. The claim: sd/mean falls materially (target below 8% for the band
   variant, below 15% for the joint), gross within 0.05, net@30 never negative.
2. **The cost-misestimation experiment — the point of the prompt.** Suppose we
   believe cost is 15bp and it is really 30bp. Under a fixed width derived at
   15bp (4.26% per the cube-root law) net@30 is around +0.1; under the
   controller the turnover is pinned regardless of the belief, and net@30 is
   gross minus 30bp × 17.6. Tabulate net@{5,15,30} for the fixed and targeted
   constructions **under each belief** {5, 15, 30}. **The targeted column should
   be flat across beliefs. That flatness is the deliverable.**
3. **The z_window = 63 counterfactual.** Rebuild the 2024-01+ holdout run with
   `z_window=63, rebalance_days=2` — the configuration that failed — but with
   the controller wrapped around a band instead of the calendar. The holdout is
   spent as a *selection* device; this is a **diagnostic, not a selection**, and
   it must be labelled so: "would the controller have caught the turnover
   blow-up?" Report turnover and net. **Do not then adopt z_window=63 on the
   strength of it**; that would be the same mistake with a longer story.
4. **Stability of the controller itself:** plot `b_t`; count bound hits; confirm
   it does not oscillate (autocorrelation of `Δlog b_t` near zero or slightly
   negative).

**Decision rule.** Adopt the band variant if test 1's stability improves as
stated, test 2's targeted column is flat within 0.1 Sharpe, gross at matched
turnover is within 0.05 of the fixed band, and the holdout agrees. Spec block
`band_controller: {...}`, absent = fixed width, no-op proven. **The readout is
realised turnover's variance over 20-session windows, not P&L.** The joint
variant is adopted into W12's shadow construction on the same evidence **without
a separate trial**, since the shadow does not trade.

In live use the controller reads W7's broker-fill turnover series and **holds
`b` fixed when fewer than 20 armed sessions exist.**

---

## Part D — The cost tilt, revisited (declared as the grid's seventh cell)

### The mechanism, in two parts that must be separated

**Cost.** A one-cent spread is 22bp on PHK at $4.50 and 6.5bp on PDI at $15.33.
Equal z-weights spend a third of the edge on the minimum increment in the
cheapest names. Tilting exposure toward high-priced names cuts cost per unit
exposure with no change to the signal. **This is TC.**

**Fund health.** Gross Sharpe also rose (1.26 → 1.36), which cost cannot
explain. Low-priced CEFs are typically those that have eroded NAV through
return-of-capital distributions — and ICI's 2023 figures put **20% of all
traditional-CEF distributions in return of capital**, so this is a large, real
phenomenon, not a rounding error. The price level proxies for capital erosion,
and eroded funds revert worse. **This is a weak M8 alpha and also a confound:**
a price tilt might be a long-quality bet in disguise. The July note checked the
carry/beta factors (5/5 pass, R² 0.003); it did **not** check a CEF-internal
price factor.

### One derived form

    w_i ∝ −(z_i − z̄)·g_i,    g_i = (1/hs_i) / median_j(1/hs_j),    hs_i = 0.005/P_i

then demean again (the tilt breaks dollar-neutrality), normalise, vol-scale,
min-weight, band, exactly as today. `g` is the inverse half-spread normalised to
a median of 1, so the tilt is scale-free and the units of z are unchanged.
**Do not also test `g = P_i`, `√P_i`, or capped variants** — the July note
already showed price and 1/hs are arithmetically the same thing. One form,
derived from the cost mechanism. Where W7 Part C's measured spread disagrees
materially with the tick, run the tilt on the measured spread as the primary and
the tick as the control.

### Separating cost from health — three rows, all on the 17

- **(a) Tilt the execution only:** weights unchanged, but turnover charged at
  the tilted cost. Isolates the cost part.
- **(b) Factor-adjust:** regress the tilted-minus-untilted daily return on a
  "high price minus low price" CEF factor (equal-weight top-third by price minus
  bottom-third, dollar-neutral, monthly rebalanced). The alpha of the difference
  after that factor is the part that is not a price bet.
- **(c) Negative control:** tilt by a **random permutation** of `g` across names,
  10 draws. If permuted tilts help, the gain is concentration, not cost.

**The PHK question answers itself.** Report PHK's weight under the tilt — it
should fall by roughly the ratio of its tick to the median, about 4× — and the
leave-one-out Sharpe with it kept at that weight. If the tilt achieves what
exclusion would without excluding, the four-measure case against PHK is closed
by construction rather than by a universe edit.

**Decision rule.** Adopt if the 27 show the same sign of improvement; net@15 and
net@30 on the 17 improve at matched turnover; **the factor-adjusted alpha in (b)
is at least half the raw improvement** (the tilt is not merely a price bet); the
permuted control is materially worse; and the holdout agrees in sign. Spec key
`weight_tilt: "inverse_half_spread"`, absent = off. Falsifier: realised cost per
unit turnover, from W7, not lower than before within 40 sessions.

---

## Deliverables

- `scripts/cef/band_vector.py` (the three band variants and the generalised
  `band`), `resolution_grid.py` (the six-cell grid, importing it),
  `turnover_targeting.py`, `tick_tilt.py`; the `per_name_resolution.py`
  extension and its gate.
- The sleeve changes behind `band_policy`, `vol_scaling`, `band_controller`,
  `weight_tilt`, each defaulting to live behaviour with the no-op proved
  byte-for-byte.
- `results/cef/RESOLUTION_GRID_<date>.md` (Parts A, B, D as one table),
  `TURNOVER_TARGETING_<date>.md`, and the pre-registrations for whatever is
  adopted, with the trial counter bumped by **2 at most** and itemised.

## Do not

- Do not filter names by |z|; membership is untouched.
- Do not build a stop-loss; it was measured and it destroys value.
- Do not put κ, σ_d, or any per-name parameter into the score.
- Do not sweep `b₀`, the clip range, the shrinkage, `g`, `W`, or τ*.
- Do not run more cells than the seven declared.
- Do not let the controller read realised turnover from modelled sessions in
  live operation.
- Do not choose the grid's winner on gross, or on any single cost column.
