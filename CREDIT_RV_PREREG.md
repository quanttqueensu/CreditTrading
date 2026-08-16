# CREDIT ETF STATISTICAL ARBITRAGE — PRE-REGISTRATION

**Frozen 2026-07-28, before any return analysis of the signal.** Nothing below may be changed
after the first backtest is run. Changes require a new numbered amendment appended at the end,
each of which increments the trial counter.

Family tag: `credit_rv`. Global trial counter starts at **n = 0** for this family (the prior
book's counter died with the strategies it governed; this is a clean, separately-accounted
programme). Program selection floor for DSR: see §8.

---

## §1 MANDATE AND HARD CONSTRAINTS

From Simon, 2026-07-28, binding and verbatim in substance:

> a very unique sophisticated credit strategy that is something a fast money hedge fund would
> do / mathematical sophistication / double digit returns / **I DO NOT WANT ANY CARRY OR BETA,
> NO HOLDING, short term mispricings / edges we can find and use.**

Operationalised, and testable as pass/fail gates in §7:

| constraint | operational definition | gate |
|---|---|---|
| no carry | strategy return must not be explained by any instrument's yield or by time-in-market | `G-CARRY` |
| no beta | near-zero exposure to rates, credit, equity factors | `G-BETA` |
| no holding | median holding period short; book flat or near-flat often | `G-HOLD` |
| double digit | net return ≥ 10%/yr after all costs and financing | `G-RET` |

Locked risk parameters (Simon, AskUserQuestion 2026-07-28 ~20:00):
**vol target 12–15%, max DD tolerance ~25%, holding 1–10 days close-to-close, HARD
factor-neutral, capital $1,000,000.**

---

## §2 WHY THIS EDGE SHOULD EXIST — THE MECHANISM

Stated before testing so it cannot be retro-fitted.

The US credit ETF complex is **fragmented**: at least seven wrappers hold economically
near-identical high-yield exposure (HYG, JNK, USHY, SPHY, SHYG, SJNK, HYGH) and six hold
investment-grade (LQD, VCSH, VCIT, VCLT, IGSB, LQDH), each tracking a different index with
different inclusion rules, fees and shareholder bases.

1. **Flows arrive wrapper by wrapper.** An institution buying liquidity buys HYG; a fee-driven
   allocator buys USHY; a short-duration mandate buys SHYG. Each flow pushes *one* wrapper away
   from the complex's fair value.
2. **The correcting arbitrage is expensive and slow.** Authorised Participants close the gap by
   creating/redeeming against the underlying bonds — which cost roughly **145bp round trip in
   odd lots** and are quoted by appointment, not continuously. That cost is the **width of the
   no-arbitrage band**.
3. **Therefore dislocations of tens of basis points persist for days rather than seconds, and
   then revert.** The illiquidity of the underlying bond market — the very thing that makes
   bond-level RV untradeable for us — is what creates and sustains the ETF-level mispricing.
4. **Price discovery is asymmetric.** The liquid wrapper trades continuously while its bonds do
   not, so HYG/LQD lead and thinner wrappers lag. A lagged wrapper is a forecastable residual.
5. **Conditioning:** when dealer/AP balance-sheet capacity is constrained (stress), the band
   widens and reversion is larger. This is a *conditioning variable*, not a separate strategy.

The edge is therefore a **liquidity-provision premium inside a fragmented wrapper complex**,
not a risk premium. It is compensation for warehousing a wrapper-level imbalance for days,
hedged so that no market risk is held. This is why it can be, and must be, beta-free.

---

## §3 THE MATHEMATICS

### 3.1 Factor model

For instrument `i` on day `t`, excess return `r_i,t` (over the daily bill rate) is decomposed on
an economically-grounded factor set, **not** pure PCA:

```
r_i,t  =  α_i  +  Σ_k β_ik · F_k,t  +  ε_i,t
```

with factors, all built from tradeable instruments only:

| factor | construction | what it removes |
|---|---|---|
| `F_RATE` | IEF excess return | duration / rates level |
| `F_SLOPE` | TLT − SHY excess | curve shape |
| `F_CREDIT` | HYG excess, orthogonalised to F_RATE, F_SLOPE | the credit beta — **this is the carry factor** |
| `F_QUAL` | (HYG − LQD) excess, orthogonalised to the above | quality / down-in-credit |
| `F_EQ` | SPY excess, orthogonalised to the above | equity beta |

Betas `β_ik` are estimated on a rolling window (§4) by OLS, then shrunk toward the cluster mean
(Ledoit–Wolf style, intensity set by §4) to control estimation noise.

**Projecting out `F_CREDIT` is what makes the book carry-free**: credit carry is the expected
return of the credit factor, so a position with zero loading on it earns no carry by
construction. This is a mathematical identity, not an empirical hope, and §7 `G-CARRY` tests it.

### 3.2 Residual as an Ornstein–Uhlenbeck process

Define the cumulative residual (the instrument's "relative cheapness path"):

```
X_i,t  =  Σ_{τ ≤ t, τ > t-W} ε_i,τ
```

Model it as mean-reverting:

```
dX_i  =  κ_i (m_i − X_i) dt  +  σ_i dW
```

Estimated by AR(1) on the residual path, `X_{t+1} = a + b·X_t + ζ`, giving

```
κ_i = −ln(b)·252      half-life  τ½ = ln2 / κ_i        (trading days)
m_i = a/(1−b)         σ_eq,i = sd(ζ) / sqrt(1 − b²)
```

### 3.3 The s-score

```
s_i,t  =  (X_i,t − m_i) / σ_eq,i
```

`s` is the number of equilibrium standard deviations an instrument sits away from its
factor-implied fair value. **Positive `s` = rich = short it. Negative `s` = cheap = buy it.**

### 3.4 Two-level residual — the credit-specific extension

The generic cross-sectional residual (§3.2) is the first level. Credit adds a second, sharper
one that equities do not have: **wrapper clusters holding near-identical assets.**

Clusters are declared *a priori* by economic content, never by fitting:

- `HY_BROAD` = {HYG, JNK, USHY, SPHY}
- `HY_SHORT` = {SHYG, SJNK}
- `IG_BROAD` = {LQD, VCIT}
- `IG_SHORT` = {VCSH, IGSB}
- `FALLEN`   = {ANGL, FALN}
- `LOANS`    = {BKLN, SRLN}

Within a cluster, define the within-cluster residual `ε^C` as the instrument's return minus the
equal-weighted cluster return, and run the identical OU machinery to get `s^C_i,t`. Because
cluster members hold overlapping bonds, `s^C` is much closer to a true arbitrage than `s`.

The traded signal is a **weighted combination** of the two levels, weight `θ` fixed in §4:

```
S_i,t  =  θ · s^C_i,t  +  (1 − θ) · s_i,t      (s^C = 0 for instruments with no cluster peer)
```

### 3.5 Mean-reversion admissibility filter — what enforces "no holding"

An instrument is **only tradeable on day t** if its estimated reversion is fast enough to close
inside the mandated horizon:

```
trade i  only if   κ_i > 0   AND   τ½(i) ≤ 10 trading days   AND   R²  of the AR(1) ≥ R²_min
```

This is the mathematical enforcement of "no holding": a slow-reverting name is by definition a
position you would have to *hold*, and is excluded regardless of how attractive `s` looks.

### 3.6 Portfolio construction — hard neutrality

Raw target weights from the signal, with a dead-band so we do not trade noise:

```
w̃_i  =  −S_i,t · 1{ |S_i,t| ≥ s_entry }   (sign: short the rich, buy the cheap)
```

Then **project onto the factor-null space** so the book carries no factor exposure. With `B` the
`N×K` matrix of betas:

```
w  =  ( I − Bᵀ (B Bᵀ)⁻¹ B ) w̃            (exposure-neutral)
w  ←  w − mean(w)                          (dollar-neutral)
```

Then scale to the vol target using the residual covariance `Σ_ε`:

```
σ_p = sqrt( wᵀ Σ w ) ,   w ← w · (σ*/σ_p) ,   subject to  Σ|w_i| ≤ L_max
```

`Σ` uses de-smoothed, Ledoit–Wolf-shrunk covariance. Gross leverage is capped at `L_max` (§4)
and by IBKR portfolio-margin requirement, whichever binds first.

---

## §4 FROZEN PARAMETERS

Chosen from theory and standard practice **before** any performance was observed. Each variant
tested counts as a trial (§8).

| parameter | value | basis |
|---|---|---|
| beta estimation window `W_β` | 120 trading days | ~6 months; standard for factor betas |
| residual/OU window `W_X` | 60 trading days | must be several multiples of the 10-day max half-life |
| shrinkage intensity | Ledoit–Wolf, computed, not chosen | no free parameter |
| `θ` (cluster vs complex weight) | 0.60 | cluster residual is the cleaner arbitrage; majority weight, not all, since not every name has a peer |
| `s_entry` | 1.25 | Avellaneda–Lee use 1.25 for the equity analogue |
| `s_exit` | 0.50 | ditto |
| `s_stop` | 3.00 | beyond this, treat as regime break not mispricing |
| `τ½` max | 10 days | the mandate's horizon ceiling |
| AR(1) `R²_min` | 0.05 | rejects paths with no reliable reversion |
| vol target `σ*` | 13% | midpoint of the mandated 12–15% |
| `L_max` gross | 6.0× | ceiling; actual leverage set by vol target, usually below |
| max weight per name | 15% of equity | concentration control |
| execution lag | signal from close `t`, **fill at close `t+1`** | no same-day fills; enforced by the engine's guard |
| capital | $1,000,000 | Simon |

---

## §5 UNIVERSE AND DATA

`data/rv/etf_panel.parquet`, 30 tickers, PIT total returns (split bug documented and fixed).
Tradeable set = the credit instruments; `IEF/TLT/SHY/SPY` serve as factor legs and hedges;
`BIL` is the cash/financing benchmark. An instrument enters the tradeable set only once it has
`W_β + W_X` days of history, so young ETFs (JAAA 2020-10, JBBB 2022-01) join late and
automatically.

**Liquidity screen:** an instrument is tradeable on day `t` only if its trailing 21-day median
dollar volume ≥ $5M and our intended trade ≤ 2% of it.

---

## §6 SAMPLE SPLIT AND THE HOLDOUT RULE

- **In-sample (IS):** inception → **2023-12-31**. All development, all parameter reading, all
  refutation happens here.
- **Holdout (OOS):** **2024-01-01 → 2026-07-28**. **Opened exactly once**, at the end, after IS
  work is complete and frozen. If it is opened, that fact and its result are recorded whether
  favourable or not. No parameter may be changed after opening it. A second read requires
  explicit authorisation and must be declared non-decisional.

---

## §7 GATES — what must be true to deploy

| gate | test | bar |
|---|---|---|
| `G-CARRY` | regress strategy returns on each instrument's carry proxy and on gross exposure | no significant loading; return not explained by time-in-market |
| `G-BETA` | regress net strategy returns on F_RATE, F_SLOPE, F_CREDIT, F_QUAL, F_EQ, and on HYG/LQD/SPY directly | every |t| < 2.0; total R² < 0.10 |
| `G-HOLD` | median holding period; fraction of days at reduced gross | median ≤ 10 days |
| `G-RET` | net CAGR after spreads, impact, commissions, financing, at the vol target | ≥ 10%/yr IS |
| `G-SHARPE` | net Sharpe, IS | ≥ 0.80 |
| `G-DSR` | Deflated Sharpe at the family trial count | > 0.95 |
| `G-DD` | max drawdown | ≤ 25% |
| `G-COST` | net Sharpe with all half-spreads **doubled** | still ≥ 0.50 |
| `G-LAG` | net Sharpe with fills delayed one further day (t+2) | still positive; degradation reported |
| `G-CONC` | drop the best 5 days, and the single best instrument | edge survives both |
| `G-WF` | walk-forward, re-estimating on expanding window | positive in ≥ 60% of periods |

A gate that fails is reported as failed. Gates are not renegotiated after the fact.

---

## §8 TRIAL ACCOUNTING

Every distinct configuration evaluated against returns — parameter set, universe variant,
filter, signal variant — is one trial, logged to `results/credit_rv/trial_log.csv` with its
Sharpe, at the time it is run, whether or not it is kept. The Deflated Sharpe Ratio is computed
against the running count `N`. **Searching harder mechanically raises the bar.** Trial budget
for this programme: **60**. Exceeding it requires a written amendment.

---

## §9 KILL RULES (pre-committed, for live operation)

1. Rolling 60-day realized Sharpe < −0.5 → halve gross.
2. Rolling 120-day net P&L below the 5th percentile of the IS bootstrap → flat, review.
3. Realized vol > 1.5× target for 10 consecutive days → de-lever to target.
4. Any single name > 20% of equity → forced trim (breach of §4 limit).
5. Median realized half-life of closed trades > 15 days for a month → the reversion premise has
   broken; flat and re-derive.

---

## §10 DECLARED PRIOR KILLS — not to be re-litigated

From earlier programmes, still binding: ETF NAV-discount timing forms (M4, permanently
re-killed on concentration), aggregate TRACE sell-imbalance (M1, OAS-explained), bond-level
odd-lot forms (cost-infeasible at 145bp RT), BKLN as a *carry* holding (correlation 0.789 to
the credit core). BKLN/SRLN appear here only as **RV legs inside the loans cluster**, which is a
different use and is declared as such.

---

*Frozen 2026-07-28 before first backtest. Amendments append below.*

---

# AMENDMENT 1 — 2026-07-28, after IS signal diagnostics, before any tuned backtest

Derived from in-sample diagnostics only (`scripts/rv/diag_ic.py`, `scripts/rv/diag_edge.py`);
the holdout remains sealed. Both diagnostics are logged as trials.

## A1.1 Signal has information — recorded before changing anything

Information coefficient between `s` and the **forward residual** return, IS 2012-01→2023-12:

| horizon | IC | t | median-split spread |
|---|---|---|---|
| 1d | −0.0805 | −12.76 | 1.51bp |
| 3d | −0.0806 | −12.87 | 2.62bp |
| 5d | −0.0757 | −11.94 | 3.26bp |
| 10d | −0.0761 | −12.02 | 4.39bp |
| 20d | −0.0820 | −12.76 | 7.24bp |

Sign is correct throughout (rich → negative forward residual). The signal carries real
information; the original configuration failed on **cost**, not on predictive power.

## A1.2 CHANGE: `s_entry` 1.25 → 2.00

Per-trade economics by |s| bucket (h=5, IS): the edge is **absent below 2.0** and large above
it — 0.87bp gross at |s|∈[1.25,1.5) versus 16.10bp at |s|∈[2.0,2.5) (t=4.2).

**This is a prediction of §2's mechanism, not a data-mined threshold.** The no-arbitrage band
is set by the cost of the correcting AP arbitrage — roughly 145bp round trip in the underlying
bonds. Deviations inside that band have no economic force pulling them back and should show no
reversion; only deviations large enough to make AP arbitrage profitable revert. The data shows
exactly that discontinuity. The 1.25 threshold is Avellaneda–Lee's equity-market value, where
the correcting arbitrage is cheap and the band is therefore narrow; importing it into credit
was the error.

`s_exit` stays 0.50, `s_stop` rises 3.00 → 3.50 so a trade entered at 2.0 is not stopped by
ordinary noise before it can revert.

## A1.3 CHANGE: cost-admissibility filter on the tradeable set

An instrument is admissible only if its **round-trip cost clears the expected edge with a 3×
margin**:

```
2 × half_spread_bp  ≤  E[edge] / 3      with E[edge] = 14bp (pooled |s|≥2, h=5)
⇒  half_spread_bp ≤ 2.35bp
```

This is an **economic admissibility rule evaluated on the cost model, not a selection on
realized performance.** It is deliberately specified as a formula over the cost table so that it
cannot be tuned to keep favourable names: it excludes ANGL (5.2bp) and SRLN (2.2bp is admissible)
regardless of the fact that both scored well in-sample, and excludes SJNK/FALN/PFF/BKLN/JBBB/
SPHY/SHYG/HYGH/LQDH on cost alone.

**Explicitly NOT done:** no instrument is selected or dropped on its in-sample P&L. The
per-instrument table in `diag_edge.py` is recorded as a diagnostic and is *not* used for
selection — several of its entries (SRLN n=104, ANGL n=145, LQDH n=11) are far too thin to
select on, and doing so would be precisely the overfitting §8 exists to prevent.

## A1.4 CHANGE: concentrated sizing

At `s_entry = 2.0` opportunities are rare (~0.2 qualifying names/day IS), so the book is **flat
or near-flat most of the time** — which is the mandate's "no holding" property, arrived at
structurally rather than by constraint. Consequently the book must take **few, large positions**
rather than many small ones: `max_risk_share` 0.25 → 0.60, and the vol target sets leverage.

## A1.5 CHANGE: turnover controls (implementation defects found)

- no-trade band was expressed relative to each leg's own target, so legs near zero always
  traded. Now an **absolute** band in NAV terms.
- participation cap produced `sign(·)×inf → NaN` when a name had no volume; now guarded.
- hedge legs re-solved daily regardless of drift; now re-hedged only when net factor exposure
  exceeds tolerance.

## A1.6 Horizon

h=5 is the peak net horizon (+11.90bp at |s|∈[2.0,2.5) versus +5.97 at h=3 and +6.91 at h=10)
and is consistent with the measured median half-life of 4.0 days. Inside the mandated 1–10 day
window. No change to the `τ½ ≤ 10d` admissibility filter.

*Everything above is IS-derived. Holdout 2024-01-01→2026-07-28 remains unopened.*
