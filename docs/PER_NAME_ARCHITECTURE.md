# Per-name architecture — at what resolution should funds differ?

**2026-09-07.** Reproduce: `scripts/cef/per_name_resolution.py`.

The goal is to treat each fund as its own instrument. This document establishes
**at what resolution that is estimable**, which is a different question from
whether the funds differ. They obviously differ. The question is whether we can
measure how without fitting noise.

---

## 1. The constraint that makes this hard

Seventeen names, and effective breadth of **1.17–2.24** (`/api/factors`,
`docs/PLAN.md` §4.2). Seventeen independent parameter sets fitted on ~2
effective bets is the `z_window=63` failure seventeen times over.

**This is not hypothetical — it has already been measured here.** From
`scripts/cef/ou_score.py`:

| construction | gross | net@15bp |
|---|---:|---:|
| pooled κ | **1.20** | **0.70** |
| shrunk per-name κ | 1.11 | 0.49 |
| **raw per-name κ** | **0.94** | **0.35** |

Per-name estimation lost outright, and empirical-Bayes shrinkage recovered only
part of the loss. Any per-name architecture has to explain why it will not
reproduce that result.

---

## 2. What is actually estimable

For each parameter, decompose the cross-name spread into signal and estimation
noise. With $\tau^2 = \mathrm{Var}(\hat\theta) - \mathbb{E}[se^2]$, the
empirical-Bayes weight $w_i = \tau^2/(\tau^2 + se_i^2)$ is the share of the
observed spread that is **real**. Separately, the $R^2$ of asset-group
membership says whether the differences are *structural* rather than idiosyncratic.

| parameter | spread | mean w | names w>0.5 | group R² | resolution |
|---|---|---:|---:|---:|---|
| **κ** (reversion rate) | 0.017–0.057 | **0.86** | 17/17 | 0.12 | **PER-NAME** |
| **σ_d** (discount vol) | 2.88–11.40 | **0.96** | 17/17 | 0.24 | **PER-NAME** |
| σ_P (price vol) | 0.132–0.283 | 0.68 | 14/17 | **0.51** | **GROUP** |

**The per-name differences in κ and σ_d are overwhelmingly real** — 86–96% signal,
every single name above the 0.5 threshold. Group membership explains only 12–24%
of them, so they are idiosyncratic: *muni vs taxable does not capture it*.

**Price volatility is the opposite.** R² = 0.51 means half its cross-name spread
is explained by asset group alone, so per-name estimation there adds parameters
without adding information. σ_P belongs at group level.

---

## 3. The principle that resolves the contradiction

The parameters are estimable (§2) and yet using them lost (§1). Both are true,
and the reconciliation is exact:

> For an OU process the stationary variance is $\sigma^2/2\kappa$, so
> $\sigma_d \propto \sigma/\sqrt{\kappa}$. **The z-score already contains
> $\kappa^{1/2}$ in its denominator** — measured slope of $\log\sigma_d$ on
> $\log\kappa$ is **−0.463** against theory's −0.500 (`docs/PLAN.md` §4.1).

Per-name κ was never missing from the signal. Applying it again took the tilt
from $\kappa^{0.5}$ to $\kappa^{1.5}$ and over-weighted fast reverters.

**The principle, therefore:**

> **Apply per-name parameters where they are ABSENT, never where they are
> already implicit. Derive per-name POLICY from per-name MEASUREMENT; never fit
> per-name weights to per-name P&L.**

A derived parameter costs no trials, because nothing is searched. A fitted one
costs a trial per name and raises the deflated-Sharpe bar for everything.

Where are they absent? **The policy layer.** The signal already knows each fund's
κ and σ_d. The *trading rule* knows nothing about any of them: one band width,
one holding period, one cost assumption for all seventeen.

---

## 4. The architecture

Three tiers, assigned by §2 rather than by taste.

```
POOLED      the estimator itself           z-window 252, clip +/-4,
            (one number for the book)      cross-sectional demean, dollar-neutral

GROUP       structural differences         sigma_P (R^2 0.51)
            muni / multi / hy / loan       borrow regime, buyer base, tax
                                           treatment, leverage mechanics

PER-NAME    idiosyncratic and estimable    kappa_i, sigma_d,i, sigma_w,i
            (w = 0.86-0.96)                tick cost, ADV, borrow fee,
                                           borrow availability
```

Then the policy layer is **derived** from the per-name tier:

$$h^*_i=\Big(\tfrac{3\,c_i\,\sigma_{w,i}^2}{2\,\kappa_{w,i}}\Big)^{1/3}$$

the same cube-root law that set the current single 4.8% band, evaluated with
**that fund's own** measured target-weight volatility, reversion rate and tick
cost. Zero fitted parameters.

| ticker | grp | half-life | tick bp | **derived band** | vs 4.8% |
|---|---|---:|---:|---:|---:|
| PHK | multi | 24.6 | 22.22 | **7.35%** | +2.55 |
| HYT | hy | 9.2 | 12.09 | 4.73% | −0.07 |
| DSL | multi | 12.3 | 9.51 | 4.43% | −0.37 |
| NAD | muni | 17.5 | 8.73 | 3.72% | −1.08 |
| PDO | multi | 8.8 | 7.80 | 2.44% | −2.36 |
| MQY | muni | 6.1 | 9.20 | 1.68% | −3.12 |
| MHD | muni | 8.7 | 8.91 | **1.07%** | −3.73 |

**Range 1.07%–7.35%, a 6.9× spread** where we currently apply one number.

> **⚠ AMENDED 2026-09-09 — this table is illustrative, not reproducible. Four
> things a reader must know before using it:**
>
> 1. **No code in this repo computes it.** Grepping for the cube-root law
>    returns only prose — in this file, in `PREREG_BAND_2026-09-06.md`, and in
>    a warning comment in `band_frontier.py`. `per_name_resolution.py` computes
>    κ, σ_d and σ_P and **does not compute `σ_w,i` at all**, which is the
>    numerator of the formula above. `F2_group_forms_fund_params.md` Part C
>    builds it.
> 2. **Only 7 of the 17 names are listed.** The other ten have no published
>    derived band.
> 3. **The half-lives do NOT disagree with `docs/PLAN.md` §4.1 — they are
>    different quantities, and an earlier version of this amendment got that
>    wrong.** Verified 2026-09-10 by recomputation: this table's column is the
>    **target-weight** half-life (κ_w), the correct input to the cube-root law;
>    PLAN §4.1's column is the **discount** half-life (κ_d). Six of the seven
>    rows reproduce exactly once you know which is which — recomputed κ_w gives
>    HYT 9.3, DSL 12.3, NAD 17.5, PDO 8.9, MQY 5.9 against the table's 9.2,
>    12.3, 17.5, 8.8, 6.1.
>
>    **PHK is the exception, and it is a real error.** The table's 24.6 is the
>    *pooled* discount half-life (φ = 0.9722); PHK's own κ_w is ≈ 37.0. PHK's
>    row is the one this section's whole argument rests on. **Label the column,
>    and fix PHK.**
>
> 4. **The tick figures are three different quantities, not a dispute.** PLAN
>    §4.1's 10.65bp is a *half*-tick on $4.69; this table's 22.22bp is a *full*
>    tick on $4.51; `config/costs.yaml`'s 25.77bp is **1.25× the full tick** on
>    $4.85 — and that 1.25 multiplier holds for all 17 CEFs. **The ledger charges
>    25.77**, i.e. 2.4× what PLAN's prose implies. None of the three documents
>    states its convention. Define it once and make all three cite it.
>
> 5. **Three of the seven bands rest on fewer observations than this repo's own
>    identification budget allows.** `docs/REFERENCES.md` sets the bound at
>    T ≥ ~1,854 paired observations for a 25-day half-life at ±20%. Non-zero
>    target-weight observations available: **MHD ≈130, MQY ≈365, PDO ≈1,286**.
>    MHD gets the *narrowest* band in the table (1.07%, a 4.5× tightening against
>    the live 4.8%) off roughly 130 observations. **Do not deploy those three.**
> 4. **The empirical-Bayes weights in §2 were computed with a method-of-moments
>    estimator for τ²**, which with N = 17 is unreliable and truncates "we
>    cannot tell" to "full pooling" without attaching uncertainty.
>    `F2` Part A redoes them under a weakly-informative prior and reports how
>    far they move.
>
> Until F2 lands, treat the table as a **motivating illustration** of the spread
> per-name bands could have, not as parameters to deploy.

PHK receives the *widest* band because its tick is 22.22bp on a $4.50 share —
68% of the 32.6bp breakeven in a single minimum increment. The economics say
leave it alone, which is a better answer than the exclusion `docs/PLAN.md` §4.1
has been circling: **an expensive name is not a bad name, it is a slow one.**

---

## 5. Market structure by group

The group tier is not a statistical convenience; the four groups are different
instruments with different holders.

| group | n | holders / structure | consequence |
|---|---:|---|---|
| **muni** | 6 | tax-sensitive retail; leverage via tender-option bonds; state-specific | December tax-loss selling and a documented January reversal (`docs/EXIT_RESEARCH_2026-09-07.md` §4). **Also where the borrow bill lives** — NAD 9.98%, NVG 4.23%, NEA 3.06% |
| **multi** | 8 | PIMCO-dominated; distribution-driven retail flows; large persistent premiums | PHK +22.6%, PTY +13.9%. Premium does **not** predict borrow cost here — measured, PHK borrows at 1.06% |
| **hy** | 2 | credit-beta sensitive | HYT is the single most expensive borrow in the book at 10.56% |
| **loan** | 1 | floating rate, different duration | n=1: no group statistics are possible, and none should be claimed |

Two cross-cutting facts already measured elsewhere and confirmed per-name here:
**PC2 (92.5% of current book variance) is the muni group**, and the same names
carry 91% of the borrow cost. Concentration and financing are one trade.

> **Clarified 2026-09-09.** The 92.5% here and the **65.7%** in `docs/PLAN.md`
> §4.2 and `SYSTEM_AND_STRATEGY.md` §6.1 are not in conflict — they measure
> different periods. 65.7% is the historical average over the backtest; 92.5% is
> today's live book, which is unusually concentrated. Quote the period whenever
> quoting the number; a reader who sees both without it will reasonably conclude
> one is wrong.

---

## 6. What this does NOT license

1. **No per-name signal weights.** §1 and §3. The score stays pooled.
2. **No per-name P&L fitting.** Every per-name number above is *measured from its
   own time series* (κ, σ, tick, borrow), never selected because it improved a
   backtest column.
3. **No per-name universe filtering.** Every |z| threshold lowers portfolio Sharpe
   (0.81 → 0.40 → 0.29 → 0.27) because it destroys the breadth we cannot spare.
   Differentiate the *holding period*, keep every name.
4. **No group statistics on n=1.** The loan group has one member. It inherits the
   pooled value, and this must be explicit in code rather than silently averaged.

---

## 7. Implementation path

**Phase A — per-name band (1 trial).** `band_width` becomes a per-ticker map in
the frozen spec, populated from §4. The sleeve change is small: the band already
reads a scalar, and a dict lookup with a pooled fallback preserves current
behaviour exactly when the map is absent. Backtest against the single-band
baseline at matched turnover before deploying — the derivation is principled but
it has **not** been shown to beat 4.8% on the panel yet, and that test is the
whole point.

**Phase B — group-level σ_P** in the vol scalar, replacing the book-wide 63-day
estimate.

**Phase C — per-name borrow in the score's cost term**, once the borrow panel has
enough sessions that a rate is a rate and not a snapshot
(`results/cef/BORROW_NOTE_2026-09-06.md` — the panel starts 2026-09-06).

Phase A is the only one that changes the live book, and it is gated on a backtest
that has not been run.
