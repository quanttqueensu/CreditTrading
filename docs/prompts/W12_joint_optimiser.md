# W12 — The joint optimiser: derive the cost coefficient, structure the covariance, shadow it

**Reads first:** `00_BRIEF.md` §1, §5, §6.
**Lever:** TC and BR together. The joint L1 mean-variance book nets **0.90 vs
the band's 0.70 at matched turnover**, with gross 1.33 vs 1.10.
**Trials:** 0 while it shadows; **1 when promoted**. Parts A and B are
derivations and measurements and cost nothing.
**Touches the live book:** no. It computes alongside and never trades.
**Prerequisites:** W4 (the post-battery IC term structure — Part A is built on
it), W11 Part C (the turnover controller's joint variant folds in here).
**Supersedes:** P1.7, P5.1, P5.2.

---

## Paste from here

You are a quant developer on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md`, then:

1. `docs/SYSTEM_AND_STRATEGY.md` §8.1 — **why it is not deployed**: turnover
   stability 36.9% sd/mean across eras against the band's 11.9%; it loses
   2013–16 in the thin universe; letting ADV-ineligible names stay as decision
   variables puts 28% of gross in untradeable names and loses. *"Deploy after
   the band has live evidence, not before."*
2. `docs/PLAN.md` §4.5 in full (the objective, the `c_model` derivation, the
   turnover-matched table, the corrections to the naive theory) and §2.4 (the IC
   term structure: 0.040 at 1d rising to 0.103 at 42d, with IC/√h decaying on a
   31-day half-life — *"the edge is slow"*).
3. `src/analysis/l1_meanvar.py` in full: `solve`, `frictionless`,
   `lambda_for_vol`, `no_trade_slack`, `Solution` (with `d`, `kkt`, `traded`),
   `SolverError`, and the module docstring on the joint prox and **why
   soft-threshold-then-project destroys the no-trade region**.
4. `scripts/cef/joint_cost_optimiser.py` — how λ is set per date, how Σ is
   estimated (Ledoit-Wolf, 252d ending the day before, refit monthly), how
   ADV-ineligible names are CLOSED, and `_cov_window`.
   > **⚠ Before you extend it, fix its baseline.** Verified 2026-09-10, this
   > file compares against `band(..., 0.064)` at lines 395, 403, 412, 413 and
   > 560 — **the 6.4% width, superseded by 4.8% on 2026-09-06.** Every
   > "plain_band" and "inv_band" row it produces is measured against a policy
   > the book does not run. `covariance_construction.py:151` has the same bug.
   > **Read `band_width` from the frozen spec and re-run the baseline before
   > comparing anything to it**, or your comparison is against the wrong
   > reference and will not announce itself.
5. `scripts/cef/covariance_construction.py` in full: why Σ⁻¹α is the standard
   fix for a book whose variance is 65.7% one factor; **why shrinkage is
   mandatory** (an unshrunk inverse loads the worst-estimated eigenvectors and
   trades to chase them: highest gross, worst net); the Grinold alpha units;
   `COV_WINDOW = 252`, `COV_REFIT = 21`; `br_eff()`.
6. `dashboard/server.py::_decompose` — PC1 market direction 1–4%, PC2
   muni-vs-taxable 66–92%, the rest residual. **The factor structure is known a
   priori and documented.**
7. `results/cef/ALPHA_AUDIT_2026-09-05.md` (the T+1 IC column: 1d −0.053, 2d
   −0.074, 5d −0.096, 21d −0.131) and `ESTIMATOR_NOTE.md` (pooled AR(1)
   φ = 0.9722, a 24.6-day dislocation half-life).

### The objective, and what falls out of it

    max_w  w'α − (λ/2)·w'Σw − c·‖w − w_prev‖₁    s.t.  1'w = 0

The ℓ₁ term produces a no-trade region as a **consequence**: a name is left
alone unless its risk-adjusted marginal alpha `|α_i − λ(Σw)_i − ν|` clears `c`.
The region is **Σ-aware**, so a muni is not traded merely because its own z
moved if the rest of the muni block already carries the exposure. That is why it
beats the scalar band at matched turnover, and why composing Σ⁻¹α with a scalar
band does not reproduce it.

---

## Part A — Derive `c_model` instead of bisecting turnover (trial: 0)

### The problem with the current number

25.2bp was found by bisecting on turnover until the joint book matched the
band's 14.2×/yr, then rationalised with a formula. The rationale is right but
the number is **fitted to a turnover target**. A derived number would let the
objective say what turnover *should* be, which is the point of having an
objective.

### The derivation

Write the expected return of a position opened at *t* and held for its expected
life `H` in Grinold form, with `IC_H` read from the measured term structure:

    μ_i^(H) = IC_H · σ_i · √H · s_i,   s_i = −(z_i − z̄)

Interpolate `IC_H` on √h between the measured points and verify the
interpolation reproduces all four; beyond 21d use the 31-day half-life decay of
`IC_h/√h`. **Use W4's post-battery term structure. If the battery moved the IC,
`c_model` moves with it, and so does the joint book's turnover — that
sensitivity is a required row, not an afterthought.**

The single-period objective compares one period of alpha against a whole trade.
If α is **replaced** by `μ^(H)`, the whole-life expected return, the cost term
should be the whole-trade cost, `c_exec` per unit of one-way turnover, with no
correction:

    c_model = c_exec            when α_i = μ_i^(H)
    c_model = c_exec / (IC_H·√H)   keeping α in the current units σ_i·s_i

**Note this differs from the script's `c_exec/(IC·H)`**, which uses the 1-day IC
and a linear `H`. They agree only if `IC_H·√H = IC_1·H`, i.e. if IC grows
linearly in √h — which the measured term structure says is approximately true
out to ~21 days and not beyond. **Show both and the difference.**

**`H` is not free either.** The holding period depends on `c`: a larger `c`
produces a longer hold. So `H` and `c` are a fixed point:

1. start with `H₀` = the band's measured hold from `evaluate(band(T, 0.048), R)`;
2. compute `c_model(H₀)`, run the joint optimiser, measure its hold `H₁`;
3. iterate until `|H_{k+1} − H_k| < 0.5` days. **Report the sequence.**

Recalibrate λ with `lambda_for_vol` at each step so the `c = 0` solution keeps
the 6% target, and report λ's value so a reader can see it moved with the units.

### The check, stated before running

- If the fixed-point `c_model` at `c_exec` = 15bp lands **inside the measured
  plateau (10–45bp) and within ±8bp of 25.2**, the earlier number was consistent
  with the theory and the derivation replaces the bisection as the documented
  origin.
- If it lands **outside** the plateau, the earlier number was fitted, and the
  joint optimiser's advantage must be re-evaluated at the derived value before
  Part C promotes anything. Write that down.
- Repeat at `c_exec` = 5 and 30bp, and at W7 Part C's **measured per-era
  costs**. The derived `c_model` should scale linearly and the joint's turnover
  should move accordingly. **That is the behaviour a derived parameter has and a
  fitted one does not.**

Deliver `scripts/cef/derive_c_model.py` with a table of (`c_exec`, `H*`,
`IC_H*`, `c_model`, joint turn/yr, gross, net@`c_exec`, λ), a unit test
reproducing the derived `c_model` at 15bp from the stored term structure to
0.1bp, and a docstring in `joint_cost_optimiser.py` replacing the
rationalisation paragraph with the derivation. **Do not choose `H` to make the
number land on 25.2, and do not use per-name κ or per-name IC — pooled only.**

---

## Part B — Structure the covariance (trial: 0 for the measurement)

### The hypothesis

A Ledoit-Wolf estimate on 17 names and 252 days, refit monthly, moves from month
to month for reasons that are **estimation noise, and the optimiser trades on
those moves.** That is the plausible source of the joint book's turnover
instability. A **structured** covariance built from the two factors we already
know exist has far fewer free parameters (2×17 loadings + 3 factor covariances +
17 residuals = 54, against 153 in the sample covariance), a well-conditioned
inverse by construction (Woodbury), and month-to-month changes that come from
loadings drifting, which is slower.

If the hypothesis is right, the joint optimiser with structured Σ keeps its
gross and net advantage and loses most of its turnover instability. **If it is
wrong, the instability comes from the alpha, not Σ** — and that is worth knowing
before W11 Part C is relied on.

### The construction

Per estimation date (first session of each month), on the trailing 252
complete-case return rows ending the day **before**:

- Factor 1: equal-weight mean return of the eligible universe.
- Factor 2: mean return of the muni names minus mean return of the taxable ones
  (loan and hy are taxable). **Orthogonalise factor 2 against factor 1** by
  regression so the loadings are interpretable; report raw and orthogonalised.
- Loadings `B` (17×2) by OLS of each name's return on the two factors;
  residuals ε. `F` = 2×2 sample covariance of the factors; `D` = diag of
  residual variances. `Σ_struct = B·F·B' + D`.
- Third variant, **shrinkage toward the structured target**:
  `Σ_LW→struct = δ·Σ_struct + (1−δ)·S`, δ from the Ledoit-Wolf closed form for a
  general target (Ledoit & Wolf 2003 gives the single-factor case; implement the
  general-target intensity or apply sklearn's LW intensity to the residual after
  projecting out the factor part — **state which**).

Alignment: every window ends at *t−1*; assert it in code.

### The comparison

Inside `joint_cost_optimiser.py`'s loop, holding everything else fixed (signal,
α units, λ calibration, `c_model`, ADV closure, refit cadence), run four Σ
choices — Ledoit-Wolf (current), **sample (unshrunk; the known-bad control)**,
structured two-factor, LW shrunk toward structured — reporting free parameters
and condition number (median and p95 over dates), then, turnover-matched to the
band at 14.2/yr **and** at the joint's own natural turnover:

| Σ | turn/yr | gross | net@5 | net@15 | net@30 | BR_eff | PC2 share | era sd/mean of turnover | 2013–16 net@15 | names traded/session | Jaccard of the traded set |

The last column is the Jaccard similarity of the set of names with `d_i ≠ 0`
between consecutive sessions; **a stable no-trade set is what we want.** Also
plot the Frobenius change in Σ between refits for each variant, and BR_eff over
time, into `results/cef/figures/`.

**Decision rule.** The structured variants are adopted into the joint
construction if turnover sd/mean falls **below 20%** (roughly halfway to the
band's 11.9%) while net@15 at matched turnover is within 0.05 of LW's and the
2013–16 era no longer loses to the band. **If the sample covariance's
instability and the structured variant's are similar, Σ is not the source** —
write that, and W11 Part C's controller becomes the route. Nothing is swept: two
factors, one window, one refit cadence, fixed in advance. **Do not add a third
factor** — a "PIMCO" factor is tempting; it is 8 names, and it would be fit to
the same data that motivated it. **Do not refit daily. Do not drop the unshrunk
control**; its known-bad result validates the comparison.

Unit tests: `Σ_struct` is positive definite, and its Woodbury inverse matches
`np.linalg.inv` to 1e-10 on a random panel.

---

## Part C — Run it as a shadow sleeve (trial: 0 shadowing, 1 at promotion)

### Inputs per session, all with stated alignment

`z_i` the live signal (252d moments, shift 1, clip ±4); `σ_i` =
`ret.rolling(252).std().shift(1)`; Grinold `α_i = σ_i·(−(z_i − z̄))`; Σ from
Part B's chosen estimator, refit on the first session of each month and cached,
**raising** if a held name cannot be estimated; eligibility by the tick screen
(W10 Part A) with ineligible names excluded from the solve and emitted as FLAT
targets, **never left as free variables**; `w_prev` from
`market_state.holdings` at the sizing close over sleeve NAV — the same
self-correcting reference the band uses, so a missed session leaves `w_prev`
further from the optimum and the next solve closes it, with no stored target;
λ from `lambda_for_vol` so the `c = 0` solution's ex-ante vol hits the target;
`c` from Part A. `SolverError` **propagates** — a session where the shadow
cannot certify is logged as "no solve", never a fallback to the band.

Output: `PositionTarget` per name. Names with `d_i == 0` **exactly** are HOLDs
and are emitted **qty-expressed** with the held quantity (the same contract P0.1
established for the band); traded names weight-expressed; closed names FLAT.

**1. The construction behind a switch.** Spec key
`construction: "band" | "joint_l1"`, absent = band, output byte-identical
(prove with the five-day diff). Implement `joint_l1` in `cef_discount.py` as a
separate method `target_positions` dispatches to. **Note this key is shared with
W10 Part C's `two_sleeve`; agree one enum across both prompts before either
lands.**

**2. The shadow runner.** `ops/shadow_construction.py`, called from
`launch_job.py` as phase 3b **after the live sleeve has decided and regardless
of whether the session armed** — and under W3's architecture, in the **morning
session, on the same pair as the live band**, so the two are compared on
identical information. It loads the same holdings and NAV the live sleeve was
handed, runs the construction, and writes to
`ops/books/cef_live/_shadow_joint/`: `targets.csv`, `would_be_orders.csv`,
`holdings.csv` (its own evolving book, marked at the close, starting from the
live holdings on day one and then following its own orders with modelled fills
at the next close), `nav.csv` (modelled), and `diagnostics.csv` (date, lam, c,
kkt, iters, polished, n_traded, BR_eff, PC2 share, ex-ante vol,
`no_trade_slack`). **It never opens a broker connection.** Heartbeat key
`cef_shadow`.

**3. Dashboard card** "Shadow construction" on screen 2: live vs shadow on
realised turnover, BR_eff, PC2 share, cumulative modelled return (both modelled
from the same closes so the comparison is fair), and the number of no-solve
sessions. **Label the whole card MODELLED.**

**4. Pre-register the promotion criterion now**, in
`PREREG_JOINT_SHADOW_<date>.md`: promote only when (a) ≥ 40 shadow sessions;
(b) shadow turnover sd/mean over 20-session windows within 1.5× the band's over
the same windows; (c) no session where the shadow's BR_eff is below the band's
by more than 0.5; (d) zero no-solve sessions in the last 20; (e) the
thin-universe guard — the shadow holds ≥ 8 eligible names every session.
**P&L is not a criterion.** Trials +1 at promotion.

Unit test: `joint_l1` at `c = 0` reproduces `frictionless()` to 1e-10 on a fixed
panel.

## Deliverables

- `derive_c_model.py`, `structured_sigma.py` (with a `sigma_mode` argument added
  to the joint loop), `ops/shadow_construction.py`, the sleeve construction
  behind the key with its no-op proof, the shadow's files, the dashboard card,
  the two unit tests.
- `results/cef/C_MODEL_DERIVATION_<date>.md`,
  `STRUCTURED_SIGMA_<date>.md` (both tables and the figures),
  `PREREG_JOINT_SHADOW_<date>.md`.

## Do not

- Do not let the shadow write into the live ledger directory or the heartbeat's
  `cef` key.
- Do not catch `SolverError`.
- Do not tune `c`, λ, or the refit cadence on shadow P&L.
- Do not promote on P&L, and do not promote before 40 sessions.
