# F2 — Four mechanisms, seventeen parameter sets: group forms with fund-level shrinkage

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `00_BRIEF.md` §1, §2 (M4), §3, §5.
**Lever:** IC, via a fair value that knows what kind of fund it is looking at and
how much that particular fund's own history can be trusted.
**Trials:** **4 on the CEF counter — one per group form, not one per fund.**
That is the whole point of the hierarchy: seventeen funds, four hypotheses.
**Touches the live book:** after the 27-name check and pre-registration.
**Prerequisites:** W1 (the holdout protocol and the shrinkage helper), **W4 (the
surviving IC — if the battery moved it, every expected-return number here moves
with it)**, F1 (the characteristics panel and, critically, its coverage table).
**Supersedes W10 Part D**, which is the special case of this prompt with every
shrinkage weight set to zero. W10's Parts A, B, C, E and F stand unchanged.

---

## Paste from here

You are a quant researcher on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md`, `results/cef/ARTIFACT_BATTERY_<date>.md` (W4) and
`results/cef/CHARACTERISTICS_COVERAGE_<date>.md` (F1) before anything else.
Then:

1. `docs/PER_NAME_ARCHITECTURE.md` in full, and `scripts/cef/per_name_resolution.py`
   in full. **Corrected 2026-09-10. This read: "`scripts/cef/ou_score.py:198`
   — the script recording the per-name κ failure this prompt must not repeat —
   baselines against `band(T, 0.064)`, the 6.4% width superseded on
   2026-09-06."** **Fixed 2026-09-10** (`0b74658`, `9409762`, `666fab9`): all five scripts now import `BAND_WIDTH` from `scripts/cef/spec.py`, which reads the frozen spec, and tests hold it shut. `ou_score.py` now carries no `0.064` at all.
   Its published comparison table was nonetheless produced against the retired
   width, so **re-run it at the live width before quoting its numbers** — which
   does not overturn its verdict (κ lost at every setting, including against
   the calendar). **Note two things about that script that the document does not say:
   it writes no files — it prints to stdout only — and its `eb()` function
   returns shrinkage weights but never applies them.** The only place in the
   repo that actually applies empirical-Bayes shrinkage is
   `scripts/cef/ou_score.py::shrink`.
2. `docs/PLAN.md` §4.1, the withdrawal, in full. This is the prior failure this
   prompt must explain rather than repeat:

   | construction | gross | net@15bp |
   |---|---:|---:|
   | pooled κ | **1.20** | **0.70** |
   | shrunk per-name κ | 1.11 | 0.49 |
   | raw per-name κ | 0.94 | 0.35 |

   *"Per-name estimation lost outright, and empirical-Bayes shrinkage recovered
   only part of the loss."* And the reason, measured: regressing log σ_d on
   log κ across the 17 gives a slope of **−0.463 against OU theory's −0.500**,
   so **the live z-score already carries κ^(1/2) in its denominator.**
   Multiplying by (1−φ^h) took the tilt from κ^0.5 to κ^1.5 and over-weighted
   fast reverters.
3. `results/cef/ESTIMATOR_NOTE.md` — the Kalman lost to a plain rolling window,
   and the 63-day window then failed its holdout on turnover.

---

## The reconciliation, stated before any code is written

There is a real tension here and it must be resolved on paper first, or this
prompt will reproduce the 2026-09-06 failure with a longer story.

**The case for per-fund parameters is stronger than the repo currently
credits, on two independent grounds.**

*Theory.* Pesaran & Smith (1995, *J. Econometrics* 68:79–113) show that when
the true model has heterogeneous autoregressive coefficients and you impose a
common one, the pooled estimator is not merely finite-sample biased — it is
**inconsistent as T → ∞**, because each entity's deviation from the common
coefficient enters a composite error that stays correlated with the lagged
dependent variable no matter how much data accumulates. Our parameter is
exactly such a coefficient. So "pooling is fine because we have 5,000
observations per fund" is not a defence.

*Evidence, in CEFs specifically.* **Patro, Piccotti & Wu (2014), "Exploiting
Closed-End Fund Discounts"** — 377 US CEFs, Aug 1984 to Dec 2011, monthly,
per-fund ADF with a 10,000-replication bias correction under a random-walk null
— find the reversion coefficient ranges from **−0.002 to −0.541 across 334
funds**. That is not a modest spread; it is two orders of magnitude. And they
report the horse race this desk wants: **strategies that exploit the per-fund
heterogeneity earn Sharpe 1.86–1.92 against 1.52 for a naive strategy that
treats funds homogeneously and sorts only on the sign of the premium**, with the
paper stating plainly that *"taking into account the heterogeneity in CEF mean
reversion speeds substantially improves trading strategy returns over the
benchmark model."*

**Two caveats that keep this honest.** Their work is **monthly**, and their
full-sample bias-adjusted half-life is **7.7 months** — so it supports the
*existence* of exploitable heterogeneity, not its presence at our two-day
horizon. And their strategy Sharpes are gross of the costs that decide
everything for us. Cite it as the reason to run this prompt, not as the reason
to expect it to succeed.

**The case against putting them in the score is also real, and it is
measured.** The z-score's denominator is the fund's own trailing discount
standard deviation, and for an OU process the stationary variance is σ²/2κ, so
σ_d ∝ σ/√κ. The score therefore *already* contains κ^(1/2). Adding κ again is
not supplying a missing term; it is double-counting one.

**Both are true, and they resolve cleanly:**

> Per-fund parameters belong wherever the construction is currently blind to
> them, and nowhere else. The score is not blind to κ — it carries κ^(1/2)
> already. The **fair value** is blind to everything except the fund's own
> trailing mean. The **policy layer** — band width, holding period, sizing — is
> blind to all of it. That is where per-fund goes.

So this prompt changes **θ_i, the fair value**, and hands per-fund κ and σ_w to
W11's policy layer. **It does not touch the score's κ exponent.** If you find
yourself adding a κ term to the numerator of the z-score, stop: that experiment
has been run, it cost 1.20 → 0.94, and the trials were released on the
condition it not be repeated.

---

## Part A — Redo the resolution table properly (trial: 0)

The measured table in `PER_NAME_ARCHITECTURE.md` §2 is the foundation of every
per-fund claim in this repo:

| parameter | spread | mean w | names w>0.5 | group R² | resolution |
|---|---|---:|---:|---:|---|
| κ (reversion rate) | 0.017–0.057 | 0.86 | 17/17 | 0.12 | PER-NAME |
| σ_d (discount vol) | 2.88–11.40 | 0.96 | 17/17 | 0.24 | PER-NAME |
| σ_P (price vol) | 0.132–0.283 | 0.68 | 14/17 | **0.51** | GROUP |

**Those weights were computed with a method-of-moments estimator for τ²:**

```python
tau2 = max(0.0, float(np.var(theta[ok], ddof=1)) - float(np.mean(se[ok] ** 2)))
w = np.where(ok, tau2 / (tau2 + se ** 2), np.nan)
```

With N = 17 groups, τ̂² is itself estimated on very few degrees of freedom, and
a plug-in point estimate is exactly what Gelman (2006, *Bayesian Analysis*
1(3)) warns against — the recommended alternative is a weakly-informative prior
on τ (half-Cauchy or half-Normal) rather than a moment estimator. The
truncation at zero also silently converts "we cannot tell" into "full pooling"
with no uncertainty attached.

**Which cross-sectional variance belongs in the numerator is not ambiguous, and
it is worth deriving here because getting it wrong is silent.** By the law of
total variance, the observed spread of the *estimates* overstates the spread of
the *parameters*:

    Var(θ̂_i across i) = E[Var(θ̂_i | θ_i)] + Var(E[θ̂_i | θ_i]) = E[se_i²] + τ²
    ⇒  τ² = Var(θ̂_i across i) − E[se_i²]        ← always the bias-corrected one

which is exactly what `tau2 = Var(θ̂) − mean(se²)` subtracts off. **Use the raw
variance and you systematically over-weight each fund's own noisy estimate.**

Simulated at N = 17 over 4,000 replications, MSE of the shrunk estimate (lower
is better):

| true heterogeneity | raw τ² | **corrected τ²** | full pooling | unpooled | τ̂² hit 0 |
|---|---:|---:|---:|---:|---:|
| strong | 0.0385 | 0.0387 | 0.3389 | 0.0434 | 0% |
| moderate | 0.0657 | **0.0625** | 0.0930 | 0.1429 | 15% |
| weak | 0.0886 | **0.0462** | 0.0371 | 0.2816 | 48% |
| none (null) | 0.0795 | **0.0280** | 0.0161 | 0.2805 | 55% |

Three readings, and the third is the one that should shape the note:

1. **Corrected beats raw wherever the signal is weak** — a tie when
   heterogeneity is strong, a large win when it is not, which is the regime 17
   credit CEFs are most likely in.
2. **Both shrinkage variants beat unpooled everywhere.** That is the formal
   version of why the 2026-09-06 per-name κ attempt lost.
3. **Where heterogeneity is weak or absent, full pooling beats both.** Shrinkage
   is insurance, not free: it costs a little against pure pooling when there is
   nothing to find, and protects heavily when there is. **Say that plainly
   rather than presenting shrinkage as strictly dominant.**

And the column that justifies the prior: **even when heterogeneity is real, the
moment estimator truncates τ̂² to zero 15–48% of the time at N = 17.** That is
the noise a weakly-informative prior on τ exists to handle, and it is why this
part must report a posterior rather than ship a point estimate.

(The same question is live in the classic finance application — Vasicek (1973)
beta shrinkage uses a cross-sectional variance in this exact position, and
whether it is raw or bias-corrected could not be confirmed from the source,
which is paywalled. It does not matter: the derivation above settles what the
*right* quantity is regardless of what Vasicek did.)

**Redo it.** For each of κ, σ_d, σ_P, σ_w:

1. Estimate per fund with a **bias correction applied before pooling.** The
   AR(1) coefficient has small-sample bias E[φ̂] − φ ≈ **−(1+3φ)/T** (Kendall
   1954; Marriott & Pope 1954), and our funds have very unequal history — from
   1,407 paired observations (PDO) to 6,993 (MQY, MHD). **Uncorrected, that bias
   is a function of T, so it injects a spurious, history-length-driven component
   into the cross-fund spread and inflates τ̂².** Correct with Kendall's
   analytic form, and cross-check with a bootstrap; near a unit root, prefer
   indirect inference (Gouriéroux, Monfort & Renault 1993).
2. Estimate τ² **hierarchically**, with a half-Cauchy prior on τ, and report
   the full posterior for τ — not a point estimate. Where the posterior for τ
   includes zero comfortably, say so; that is the honest reading of "we cannot
   distinguish these funds".
3. Recompute `w_i = τ²/(τ² + se_i²)` from the posterior mean, and **report how
   much the weights moved** against the published table. If κ's mean weight
   falls materially below 0.86 under a proper prior, the per-name claim in
   `PER_NAME_ARCHITECTURE.md` is weaker than recorded and every downstream
   prompt that leans on it must be told.

**The data budget, derived and pre-registered before any of this runs.** For a
half-life h = ln2/κ, the delta-method sensitivity is
`dh/dφ = ln2 / [φ·(ln φ)²]`, which diverges as φ → 1. At the pooled 25-day
half-life, φ = exp(−ln2/25) = 0.9727 and dh/dφ ≈ **927**. Requiring
SE(h)/h ≤ 20% needs SE(φ) ≤ 0.0054, and with Var(φ̂) ≈ (1−φ²)/T that needs
**T ≥ 1,854 observations, about 7.4 years** — and that is the *optimistic*
bound, ignoring the Kendall bias and the strong right-skew of the half-life
estimator, which realistically multiply it by 2–4×.

**The rule is the derivation, not the table.** Recompute the required T from
the half-life you actually measure — it is highly sensitive, since `dh/dφ`
diverges as φ→1 — and recompute each fund's paired-observation count from the
current panel, which grows daily and will have moved. What must not change is
that the threshold is fixed **before** fitting and applied without exception.

For scale, the counts as they stood on 2026-09-09:

| fund | paired obs | years | clears 1,854? |
|---|---:|---:|---|
| **PDO** | **1,407** | **5.6** | **no** |
| DSL | 3,362 | 13.3 | yes, marginal on the realistic bound |
| BIT | 3,402 | 13.5 | yes, marginal |
| PDI | 3,592 | 14.3 | yes, marginal |
| PFN … MHD | 4,854–6,993 | 19.3–27.8 | yes |

On that snapshot PDO fell short of even the optimistic bound and DSL, BIT and
PDI sat close to it — but **which funds fail is an output of the rule, not an
input to it.** Write the rule into the pre-registration *before* fitting: any
fund below the bound is shrunk to the group value with `w_i` forced to zero and
is **never reported unpooled**. Then apply it to whatever the panel says on the
day, and list which funds it caught. A decision made on sample size is
defensible; a list of funds copied from this document is not.

---

## Part B — Four group forms (trials: 1 per group tested, up to 4)

The model. For fund *i* in group *g(i)*, on a trailing 504-session window
ending *t−1*, refit monthly:

    d_i,s = a_i + b_i' x_{g(i),s−1} + e_i,s
    b_i   = w_i · b̂_i + (1 − w_i) · b_g          (shrunk within group)
    θ_i,t = â_i + b_i' x_{g(i),t−1}               (conditional fair value)
    u_i,t = d_i,t − θ_i,t                          (conditional dislocation)
    z_i,t = u_i,t / sd_{252}(u_i)  clipped ±4      (own sd, shift 1)

**The mean is already removed by θ. Do not demean again with a rolling mean, or
you have rebuilt the live signal plus noise.** Everything downstream — the
cross-sectional step, normalisation, vol scalar, band — is unchanged in this
prompt; F3 changes it.

Fit this as **one hierarchical model per group**, not as *n_g* separate
regressions: `b_i ~ N(b_g, Σ_b)` with a weakly-informative prior on Σ_b,
estimated by REML or full Bayes. That is what makes each group **one
hypothesis** rather than *n_g* of them.

### The conditioners, pre-declared per group, written down before running

**muni — and it is two mechanisms, not one.** Verified 2026-09-09: the six muni
names are four Nuveen (NAD, NEA, NVG, NZF) and **two BlackRock (MQY, MHD)**.
Nuveen munis lever through tender option bond trusts whose floaters reset to
the **SIFMA Municipal Swap Index** (tax-exempt, weekly reset published
Wednesdays by 4pm ET, structurally below taxable short rates). BlackRock munis
lever predominantly through **preferred shares** (VRDP/MFP/RVMTP), a different
reset mechanism with a different sensitivity to the same rate move. So:

- shared: muni/Treasury relative value = 21-day return of MUB minus IEF (fetch
  MUB and PZA into the panel via `refresh_market_feeds.py` with a source note —
  the ETF panel has no muni ETF today); tax-season dummy, November–January;
  group NAV momentum, trailing 63-day mean NAV return.
- **leverage cost, by structure, from F1's `leverage_type`:** 63-day change in
  **SIFMA** for the TOB-levered names; the appropriate preferred-reset
  benchmark for the BlackRock names. **A fund whose structure F1 could not
  establish gets `unknown` and is pooled explicitly in code.** SOFR is a
  fallback for either and must be labelled as one wherever it is used.

**multi** (8 in the 17: PDI, PTY, PDO, PCN, PHK, PFN are PIMCO; DSL DoubleLine;
BIT BlackRock — state that the group is mostly one family): financing = 63-day
change in a taxable repo/SOFR rate, since PIMCO funds run reverse repo at
18–42% of managed assets and roughly 6.3% effective cost; family co-movement =
mean z of the *other* PIMCO funds, excluding the name itself; premium
persistence = the group's trailing 252-day mean premium; distribution coverage
= F1's `roc_share_ttm` and its change, **if and only if F1's coverage table
says it exists for enough of the group** — a field present for PIMCO and absent
for DoubleLine is a sponsor-selection device, not a regressor.

**A note on the asset-class ordering, because it is not settled and one of this
prompt's group forms depends on it.** Ji & Kim (2013, *Applied Economics*
45(32)) state in their abstract — verified — that *"equity-based funds converge
to the steady-state level faster than fixed income funds."* Patro, Piccotti & Wu
(2014), read in full, find the **opposite**: *"funds investing in fixed-income
securities have faster speeds of reversion than funds investing in equities"*,
with Table III mean β of −0.121 for equity against −0.136 for fixed income.
Samples, periods and methods differ (UK+US vs US-only), so neither is
necessarily wrong. **The desk's entire universe is fixed-income, so this does
not change what we trade — but it does mean no prompt may assert a prior about
where reversion should be faster.** Let the shrinkage weights answer it.

**hy** (2 in the 17: HYT BlackRock, AWF AllianceBernstein; 4 in the 27): credit
spread = 21-day HYG minus LQD; credit sentiment = 21-day HYG return; equity vol
= 21-day change in VIX. **With n = 2 this group cannot support meaningful
within-group shrinkage** — τ² is estimated from two points. Fit it, report it,
and treat its per-fund weights as decorative: force `w_i = 0` and say so.

**loan** (1 in the 17; 6 in the 27): SOFR level and 63-day change; 21-day BKLN
or SRLN return. **n = 1 in the live universe — no group statistics on a
singleton.** Estimate on the six loan names in the 27; JFR inherits the pooled
treatment, explicitly in code.

Every conditioner carries a **stated sign expectation** written down in the
pre-registration. A fitted coefficient with the wrong sign is a flag, reported,
never silently used.

Alignment assertions on every window and lag; θ for date *t* uses data to
*t−1*; assert it at runtime. Report the fitted `b_g`, the spread of `b_i`
around it, the shrinkage weights, and the R² of the conditioners in explaining
the discount **level** per group. **If that R² is under 5%, the conditioner set
is weak and the result will be noise — say so before the IC test, not after.**

### The tests

1. **The 27 first**, under W10 Part A's rules. The 27 include an **emd** group
   (EDD, EMD, EDF, TEI, MSD) which gets no conditioners and is the negative
   control receiving pooled treatment. Per group: IC of the conditional z
   against the live z, 2d/T+1, non-overlapping, by era, with the difference and
   its SE **clustered by date** (W4 Part E). Recorded before the 17 are touched.
2. **The 17**, the same table, then the harness turnover-matched with the
   conditional level applied only to groups that passed on the 27.
3. **The wrong-conditioner control:** feed each group the *other* groups'
   conditioners. If the IC improvement is similar, the gain is from a smoother
   level rather than from information, and the claim fails.
4. **The shrinkage control, which is the point of this prompt:** run each group
   three ways — fully pooled slopes (`w_i = 0`, i.e. W10 Part D), fully
   unpooled (`w_i = 1`), and shrunk. Report all three. **The literature's
   expectation is that shrinkage wins out of sample even where a heterogeneity
   test rejects pooling** (Baltagi & Griffin 1997; Baltagi, Bresson & Pirotte
   2000), and the repo's own κ result is a case of unpooled losing badly. If
   unpooled beats shrunk here, something is wrong with the shrinkage
   implementation — check it before believing it.
5. **Is the heterogeneity real at all?** Report the Swamy statistic
   `S = Σ_i (b̂_i − b̄)' Σ̂_i⁻¹ (b̂_i − b̄) ~ χ²(K(N−1))` per group, and the
   posterior for τ. **But do not decide on it** — decide on test 4's
   out-of-sample comparison. A rejection establishes τ² > 0; it says nothing
   about whether the per-fund point estimates are precise enough to be useful.
6. **Post-cut behaviour:** the mean conditional z of cut funds at t+21, t+63,
   t+126 after a distribution cut, against the live z's −0.286 / −0.341. A
   conditional level that still reads cut funds as cheap for six months has not
   solved the thing the Kalman was built for.

### Decision rule, per group, committed before running

Adopt a group's conditional level if, on the 27, its IC beats the live IC by
more than 2 SE (clustered) and the wrong-conditioner control does not; the same
sign holds on the 17; the whole-book harness shows net@15 and net@30 not worse
at matched turnover; and the **2023–2026 holdout row agrees in sign**. Adopt
the **shrunk** variant unless the pooled variant is within 0.02 Sharpe, in
which case take pooled — fewer moving parts wins ties.

**Each group tested is one trial regardless of outcome.** Groups that fail keep
the rolling mean. Spec key `level_model: {"muni_tob": "conditional_v1",
"muni_pref": ..., "multi": ..., "hy": ..., "loan": ...}`, absent = rolling
mean, no-op proven byte-for-byte.

---

## Part C — Hand the policy parameters to W11 (trial: 0)

Two per-fund quantities that W11's band work needs and that **nothing in the
repo currently computes**:

- **σ_w,i**, the daily volatility of the fund's own frictionless *target-weight*
  series, and **κ_w,i**, its AR(1) reversion. `PER_NAME_ARCHITECTURE.md` §4's
  tier box names σ_w,i, but `per_name_resolution.py` computes only κ, σ_d and
  σ_P. Build it from `build_targets()`, per fund, with block-bootstrap SEs and
  the same Kendall correction as Part A.
- **h\*_i**, the derived per-name band, `h*_i = (3·c_i·σ_w,i² / 2·κ_w,i)^(1/3)`.
  **No code in the repo computes this.** The table in
  `PER_NAME_ARCHITECTURE.md` §4 is prose, covers only 7 of 17 names, and its
  half-lives disagree with `docs/PLAN.md` §4.1 (the doc says PHK 24.6 and DSL
  12.3; PLAN says PHK 41.9 and DSL 11.9) and its tick figures disagree with
  both `config/costs.yaml` and PLAN §4.1. **Two different estimation windows
  are evidently in play and no document says which produced the table.**
  Resolve it, compute all 17, and write the reconciliation into the note.

Apply Part A's gate: if σ_w,i's EB weight is below 0.7, W11's per-name band must
use the shrunk values; below 0.5, the per-name band variant does not run at all
and W11 runs the conviction variant only. **Write the gate's outcome into
W11's note, not just this one.**

## Deliverables

- `scripts/cef/hierarchical_level.py` (the four group forms, the shrinkage, the
  five tests) and `scripts/cef/per_name_dynamics.py` (σ_w, κ_w, h*, the gate).
- An extension to `per_name_resolution.py` that **writes files** —
  `results/cef/per_name_resolution.csv` and `.json` — rather than printing, and
  that applies its own shrinkage weights instead of only reporting them.
- `results/cef/RESOLUTION_REDONE_<date>.md` (Part A: the corrected table, the τ
  posteriors, the data-budget rule, and how far the weights moved),
  `results/cef/GROUP_FORMS_<date>.md` (Part B: the 27 first, then the 17),
  `results/cef/PER_NAME_DYNAMICS_<date>.md` (Part C, including the half-life and
  tick reconciliation).
- Per-group pre-registrations for whatever is adopted; the CEF counter bumped by
  the number of groups actually tested, itemised.

## Do not

- Do not put κ, σ_d, or any per-fund parameter into the **score**. That
  experiment cost 1.20 → 0.94 and its trials were released on condition it not
  be repeated.
- Do not fit a per-fund reversion parameter for a fund below the pre-registered
  observation bound. PDO is below it.
- Do not use the moment estimator for τ² and call the weights final.
- Do not report a per-fund coefficient for the hy group as if it were
  estimated; n = 2.
- Do not estimate group statistics for the loan group in the 17; n = 1.
- Do not select which funds "work" after fitting. A hierarchical model is one
  hypothesis **only if nothing is filtered on afterwards** (Gelman, Hill &
  Yajima 2012); cherry-picking funds from its output is multiple testing again
  and needs its own correction.
- Do not add a conditioner after seeing a result.
