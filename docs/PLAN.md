# PLAN — maximising what we extract from the CEF discount edge

**QUANTT credit programme · written 6 September 2026 · revised same day**

The alpha is established. This document does not re-test it. The question here is
narrower and more useful: **we generate a gross Sharpe near 1.2–1.75 and keep
about 0.33 of it. Where does the other two-thirds go, and how much can we get
back?**

Every number below is measured from `data/cef/` in the course of writing this.
Reproduction: `scripts/cef/plan_diagnostics.py` and §8.2.

---

## Part 0 — The objective

### 0.1 What is settled, and is not re-opened here

| evidence | source |
|---|---|
| IC −0.074, t −11.6 at the operative 2d/T+1 cadence, 27 years | `ALPHA_AUDIT_2026-09-05.md` |
| Present in **every** sub-period, 1998→2026 | same |
| Beta +0.013, R² 0.0008 — not credit risk in costume | same |
| Leave-one-out Sharpe 2.23–2.93 — no single name carries it | same |
| Purged walk-forward **9/9 blocks positive** | `RESEARCH_STATE.md` |
| Block bootstrap, 5,000 draws, **P(SR≤0) = 0.000%** | same |
| Test 7: alpha t 3.11, R² 0.005, 5/5 factor limits | same |
| **Gross Sharpe 1.23 in-sample → 1.75 out-of-sample** | `ESTIMATOR_NOTE.md` |

That last row is the important one. When the 2024+ holdout was opened, the signal
did not merely hold up — it got **stronger** out of sample. The mechanism is
structural: a closed-end fund has a fixed share count and no authorised
participants, so nothing arbitrages price back to NAV. That is why this works
where the same idea died in ETFs.

**The edge is real, it is not decaying, and it is not a factor tilt. Done.**

### 0.2 The objective: capture ratio

What did not survive was our ability to *keep* it:

| | gross SR | net SR | **kept** |
|---|---:|---:|---:|
| holdout, `z_window=63` | **1.75** | −0.298 | **0%** |
| holdout, as deployed | 0.96 | +0.352 | **37%** |
| full sample, live config (measured §2.2) | 1.20 | 0.33 @15bp | **28%** |
| **the same, after measured borrow (§3.3)** | **1.20** | **0.10** | **8%** |

**We are throwing away roughly two-thirds to three-quarters of a genuine edge** —
and once the short leg is charged its real borrow cost, measured on 2026-09-06,
**over ninety percent of it.** The capture problem is larger than this document
originally stated, and the last row is the one to attack.
That is the number this plan attacks. Not "does the alpha exist" — it does — but
**capture ratio**, and it is the single most improvable quantity in the programme.

The good news is that a capture problem is a *construction* problem, and
construction is the part of a strategy you can change without needing the market
to cooperate.

### 0.3 One correction to the previous draft of this plan

An earlier version argued that a no-trade band would be **more stable in turnover**
than a rebalance calendar. **Measured, that is false** — see §2.3. Band turnover is
slightly *less* stable in relative terms. The band still wins, decisively, for a
different and better reason that I had not measured. Recorded because a plan that
quietly drops its own wrong arguments is not worth trusting on its right ones.

---

## Part 1 — Where the two-thirds goes

`src/deploy/sleeves/cef_discount.py` implements:

$$z_{i,t} = \mathrm{clip}\!\left(\frac{d_{i,t}-\mu^{252}_{i,t-1}}{\sigma^{252}_{i,t-1}},\pm4\right),
\qquad
w_{i,t} = -\frac{z_{i,t}-\bar z_t}{\sum_j |z_{j,t}-\bar z_t|}$$

scaled by $\mathrm{clip}(6\%/\hat\sigma^{63}_t,\,0.2,\,2.5)$, refreshed on a 2-day
calendar, MOC at $t+1$.

This is a reasonable construction. It also makes six modelling choices it never
states, and **each one is a lever**:

| # | silent assumption | measured cost | lever |
|---|---|---|---|
| **L1** | trading is free at the decision stage | **the whole capture problem** | §2 |
| **L2** | 6% vol is the right size | ~1/12 of Kelly; scalar caps 5% of days | §3 |
| **L3** | shorting is free | **1.22%/yr = 0.23 Sharpe** (measured) | §3.3 |
| **L4** | all funds revert at one speed | half-lives 11.9 → 41.9bd, **3.5×** | §4.1 |
| **L5** | the names are independent | **65.7%** of risk is one factor | §4.2 |
| **L6** | $3m ADV is the right screen | caps breadth at 8 eligible names | §4.3 |

L1 is worth more than L2–L6 combined. It is Part 2.

---

## Part 2 — The trading policy: this is where the money is

### 2.1 Why the rebalance calendar is the wrong instrument

A fixed-interval calendar makes a decision that has nothing to do with economics:
*ignore the signal entirely for k days, then implement all of it at once.* It
discards information on the days it sleeps, and on the days it wakes it trades
every position — including the ones that barely moved and were not worth touching.

The right structure for our cost is known and it is not a calendar. Our
participation is **0.7% of ADV** against the cost model's own 5% guard, so we pay
essentially no impact. What we pay is the **half-spread**, which is *proportional*
to notional. For proportional costs the optimal policy is a **no-trade band**
(Constantinides 1986; Davis & Norman 1990): leave a position alone while it is
within a band of target; when it leaves, trade back **only to the band edge**.

### 2.2 Measured: the band dominates the calendar outright

5,452 trading days, 2005-01 → 2026-09, identical signal, identical T+1 MOC
execution. Gross return is before costs; `net` charges bp per unit of turnover.

| policy | gross SR | ann % | turn/yr | hold (d) | net@5bp | net@15bp | net@30bp |
|---|---:|---:|---:|---:|---:|---:|---:|
| calendar 1d | 1.39 | 7.32 | 45.7 | 4.4 | 0.95 | 0.09 | −1.21 |
| **calendar 2d — LIVE** | **1.20** | **6.40** | **31.1** | **6.4** | **0.91** | **0.33** | **−0.55** |
| calendar 5d | 0.84 | 4.39 | 17.6 | 11.3 | 0.67 | 0.34 | −0.17 |
| calendar 10d | 0.51 | 2.65 | 11.2 | 17.6 | 0.40 | 0.19 | −0.14 |
| band 1.6% | 1.31 | 6.93 | 30.3 | 6.9 | 1.02 | 0.45 | −0.41 |
| band 2.4% | 1.27 | 6.69 | 25.9 | 8.2 | 1.02 | 0.53 | −0.20 |
| band 4.8% | 1.16 | 6.16 | 17.6 | 12.6 | 0.99 | **0.66** | 0.17 |
| **band 6.4%** | **1.11** | **5.92** | **14.2** | **16.1** | **0.97** | **0.71** | **0.31** |
| band 9.6% | 0.89 | 4.78 | 9.8 | 24.3 | 0.80 | 0.61 | 0.34 |
| band 12.8% | 0.68 | 3.64 | 7.1 | 33.2 | 0.61 | 0.48 | 0.28 |

**Matched on turnover — the only honest comparison:**

| turnover | calendar | band | gross SR | net@15bp |
|---:|---|---|---|---|
| ~31×/yr | calendar 2d | — | 1.20 | 0.33 |
| ~30×/yr | — | band 1.6% | **1.31** | **0.45** (+36%) |
| ~18×/yr | calendar 5d | — | 0.84 | 0.34 |
| ~14×/yr | — | band 6.4% | **1.11** | **0.71** (+109%) |

**At the same amount of trading, the band earns more gross Sharpe and far more net.**
This is not a tuning result — it holds at every width tested, and the advantage
*widens* as you trade less, because a calendar's information loss compounds with
its interval while a band only ever discards small moves.

**Against the live configuration: net Sharpe 0.33 → 0.71 at 15bp. We roughly
double what we keep, and we trade less than half as much doing it.**

### 2.3 The real robustness argument (and my correction)

The claim I made before measuring — that band turnover is more stable — is
**false**. 2015+, where the universe is stable:

| policy | 2015–19 | 2020–22 | 2023–26 | sd/mean |
|---|---:|---:|---:|---:|
| calendar 2d | 52.1 | 62.2 | 46.4 | **12.2%** |
| band 2.4% | 47.1 | 52.5 | 33.6 | 17.8% |
| band 6.4% | 27.4 | 28.0 | 17.0 | 20.9% |

Relative turnover variability is slightly *worse* for the band.

**The robustness that actually matters is different, and it is decisive.** Because
the band trades so much less, its net Sharpe barely moves when the cost estimate
is wrong — and cost is the one parameter we do not know:

| policy | turn/yr | net@5bp | net@30bp | span | flips sign? |
|---|---:|---:|---:|---:|---|
| calendar 1d | 45.7 | 0.95 | −1.21 | 2.16 | **YES** |
| **calendar 2d — LIVE** | 31.1 | 0.91 | −0.55 | 1.46 | **YES** |
| calendar 5d | 17.6 | 0.67 | −0.17 | 0.85 | **YES** |
| band 2.4% | 25.9 | 1.02 | −0.20 | 1.22 | **YES** |
| **band 4.8%** | 17.6 | 0.99 | **0.17** | 0.83 | no |
| **band 6.4%** | 14.2 | 0.97 | **0.31** | 0.66 | no |

**Every calendar configuration goes negative in a 30bp world. Bands at 4.8% and
wider never do.** The live config's outcome spans 1.46 Sharpe across a plausible
cost range and changes sign inside it; band 6.4% spans 0.66 and stays positive
throughout.

That is the argument. We are choosing a policy under genuine uncertainty about the
one input that decides the answer, so we should choose the policy whose payoff is
least sensitive to it. Theory says the same thing independently: band width scales
as $(\text{cost})^{1/3}$, so an 8× error in cost is a 2× error in width.

### 2.4 Why it also harvests more signal

Our own IC term structure: **0.040 (1d) → 0.103 (42d)**, with IC/√h decaying on a
31-day half-life. The edge is slow; Sharpe peaks short only because $IR \approx
IC\sqrt{BR}$ rewards frequency.

A calendar picks one holding period for every position forever. A band lets the
holding period be **decided per position by whether the signal actually moved** —
average hold goes 6.4d → 16.1d, straight toward where the IC is larger, without
paying a calendar's information loss to get there. That is why gross Sharpe at
matched turnover is *higher*, not merely cheaper.

### 2.5 Do not tune the band on this table

The frontier above characterises the *policy class*; it is not a licence to pick
6.4% because it topped a column. Derive the width from the cube-root law with our
measured cost and risk, then check it lands in the flat region (4.8%–9.6% at
15–30bp — a wide plateau, not a spike). **Verify the derived value; do not
optimise it.** Selecting the argmax of a swept column is precisely how
`z_window=63` was chosen.

**Trials: 1.**

---

## Part 3 — Leverage: you asked, and 6% is far too small

### 3.1 What conviction is not

Two implementations are refuted by our own data and should not be built:

- **Not "size up when |z| is large."** Every |z| threshold above zero *lowers*
  Sharpe: 0.81 → 0.40 → 0.29 → 0.27. The edge is spread across the cross-section.
- **Not "size up when the market is dislocated."** Net Sharpe by dispersion
  quintile: **1.24 / 0.59 / 0.80 / −0.23 / 0.68**. Best in calm markets. Sizing
  into dislocation is what produced −12.9% at 35.8% vol with a −31.5% drawdown in
  2008.

### 3.2 What is genuinely being left on the table: the vol target itself

**This is the constructive answer, and it is large.**

Kelly says a strategy with Sharpe $S$ maximises log growth at a volatility target
of $S$ — i.e. full Kelly on a net Sharpe of 0.7 is a **70% vol target**. Nobody
runs full Kelly on a book with kurtosis 41.2; half Kelly is 35%, quarter Kelly
17.5%.

**We target 6%.** That is roughly **one-twelfth of Kelly** — extraordinarily
conservative for a book whose worst backtested drawdown is −12%.

Measured behaviour of the current scalar $\mathrm{clip}(6\%/\hat\sigma^{63},0.2,2.5)$:

- mean **1.50**, median 1.48 — it levers up almost always
- **pinned at the 2.5 cap on 5.2% of days** (3.8% in 2021+)
- mean ex-ante vol **4.95%** against the 6% target — it does not even reach it

One day in twenty, the risk model asks for leverage the cap refuses. The cap is
not managing risk; it is managing an arbitrary constant.

**Going from a 6% to a 12% vol target doubles the return for the same Sharpe.**
No signal improvement in this document comes close to that. Three things gate it,
and all three are checkable rather than researchable:

1. **Margin.** Reg T caps gross at 2×; 12% vol needs ~3×. `RESEARCH_STATE.md`
   already priced the alternative: **Portfolio Margin reaches 10×** on a hedged
   book because it nets exposure before shocking it. A dollar-neutral CEF book is
   exactly that shape. **Applying for PM is plausibly the highest-return single
   action available to this programme**, and it is paperwork, not research.
2. **Borrow** — §3.3, and it is the real constraint. **Now measured, and it
   binds hard: levering a 0.10 net Sharpe multiplies a drag that is most of the
   return. The vol-target decision cannot be taken before the band lands.**
3. **Fat tails.** Kurtosis 41.2 is documented. Argues for a fraction of Kelly and
   for keeping a cap — but a cap set by drawdown tolerance, not by inheritance.

### 3.3 ✅ MEASURED 2026-09-06 — the short leg, and what it actually costs

*This section was written as a warning that borrow had never been priced. It has
since been measured. Full record: `results/cef/BORROW_NOTE_2026-09-06.md`.
Reproduce with `scripts/cef/fetch_borrow_rates.py --api --positions`,
`scripts/cef/borrow_impact.py`, `scripts/cef/borrow_capacity.py`.*

The finding stands: `scripts/cef/validate.py:93` computes cost as
`(dw * hs / 1e4).sum(axis=1)` — **half-spread only, no borrow term**. Every CEF
Sharpe quoted before today — 1.26, 0.82, the 1.75 holdout gross, the audit's
2.90 — is before the cost of financing the short leg. The live ledger applies the
`FinancingModel`'s flat **+50bp**, calibrated by its own docstring for *"liquid
Treasury/IG ETFs (general collateral bucket)"*.

**Measured, that 50bp is wrong by roughly 2.5× on average and by 20× on the worst
name.** Median fee 0.83%, mean 2.29%, max 10.56%.

| policy | gross SR | +spread@15bp | +50bp assumed | **+measured borrow** |
|---|---:|---:|---:|---:|
| **calendar 2d — LIVE** | 1.20 | 0.33 | 0.29 | **0.10** |
| band 4.8% | 1.16 | 0.66 | 0.62 | **0.43** |
| **band 6.4%** | **1.11** | **0.71** | **0.67** | **0.48** |

Borrow costs **1.22%/yr on held short market value = 0.23 of Sharpe**, near-constant
across policies because it scales with *holdings*, not turnover. **Trading less does
not reduce it.** Only shorting different names does.

**The live configuration's true net Sharpe is 0.10.** Against Lo (2002)'s ~2.05
standard error over 60 sessions, that is not distinguishable from zero by anything
we can measure this year. This does not weaken Part 2 — it converts it. The band
was an improvement from 0.33 to 0.71; it is now the difference between a strategy
that is indistinguishable from nothing and one that is not.

**Three names are 70% of the cost:**

| ticker | avg short wt | fee % | drag %/yr | share of drag |
|---|---:|---:|---:|---:|
| **HYT** | 0.0338 | **10.56** | 0.357 | **29.2%** |
| **NAD** | 0.0327 | **9.98** | 0.327 | **26.7%** |
| **NVG** | 0.0403 | **4.23** | 0.170 | **13.9%** |
| NEA | 0.0321 | 3.06 | 0.098 | 8.0% |
| NZF | 0.0355 | 2.58 | 0.091 | 7.5% |
| **total** | 0.3962 | | **1.225** | 100% |

NAD and NVG are Nuveen munis — **the same names carrying PC2, the 65.7% risk
factor of §4.2.** The concentration problem and the borrow bill are the same
trade. One fix addresses both, which §4.2 did not know when it was written.

#### What this section got wrong

**The premium hypothesis is refuted.** This section reasoned that the largest
premiums — PHK +22.6%, PTY +13.9%, PCN +10.4% — would be the crowded,
hard-to-borrow shorts. Measured: **PHK 1.06%, PTY 1.09%, PCN 0.63%**, every one
below the 2.29% mean. Premium does not predict borrow cost in this universe.

Consequence for §4.1 and Phase 0 item 5: PHK's fifth failing measure was "largest
premium, most likely hard to borrow." **That measure is withdrawn.** The other
four stand untouched — slowest reversion 41.9bd, widest discount sd 6.92pp, most
expensive tick 10.65bp, leave-one-out Sharpe rising 2.49 → 2.93.

**The live book is three times more exposed than typical.** Historical drag is
1.22%/yr; the book as of 2026-09-03 carries a weighted-average borrow of **3.62%**
— $13,732/yr, **2.75% of the $500k capital base** — because the signal currently
has us short the whole Nuveen muni complex at once. Again: PC2, now with a cash
cost attached.

#### Availability is a second constraint, and it binds today

Cost is a price; availability is a position unavailable at any price. They bind on
different names — HYT is expensive (10.56%) but plentiful (2.5m shares); **NAD is
expensive and scarce (3,000 shares)**.

IBKR's `AVAILABLE` is the pool lendable *now* and does not count shares already
lent to us, so our 6,643-share NAD short is **not a violation** — it is located
and borrowed. It means we cannot add, and a recall leaves nothing to re-borrow.

Capital at which each name's 95th-percentile short exceeds 25% of its pool:

| **NAD** | **NVG** | NZF | NEA | PHK | JFR | DSL | HYT |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **$45k** | **$278k** | $2.2m | $2.3m | $4.3m | $12.1m | $12.3m | $22.5m |

At our actual $500k, **11.4% of the desired short book is unbuildable**; 27.8% at
$5m, 52.5% at $25m. **This is the programme's first capacity estimate: roughly $5m
before availability materially degrades the book.**

#### The fix, and it pays for itself

Cap each name's short weight at the borrowable size (φ = 0.25 of the visible pool,
on a rolling minimum rather than a snapshot), then scale the long leg to match so
the book stays dollar-neutral. Longs are never capped — you can always buy. A
feasibility projection at construction, not a name exclusion.

| capital | gross SR | net@15bp | borrow % | **net + borrow** |
|---|---:|---:|---:|---:|
| uncapped | 1.20 | 0.33 | 1.22 | **0.10** |
| **$500k** | 1.16 | 0.32 | **0.88** | **0.14** |
| $5m | 1.08 | 0.27 | 0.65 | 0.12 |
| $25m | 0.93 | 0.18 | 0.43 | 0.04 |

**It costs 0.04 of gross Sharpe and saves 0.34%/yr of borrow — a net gain.** The
positions it removes are the scarce ones, and here scarce correlates with
expensive. Feasibility and cost point the same way, so there is no trade-off to
negotiate.

#### The caveat that travels with all of it

**One day of rates applied to 21 years.** `data/cef/cef_borrow.csv` starts today
and is append-only. This is the counterfactual "if today's schedule had held
throughout", which is the right basis for a *forward* decision and is **not** a
backtest of realised borrow. Worse, CEF borrow rates move with the fund's own
premium — the signal itself — so a short may become more expensive exactly as it
becomes more attractive. Not modelled.

### 3.4 The defensible form of conviction sizing

With the above fixed, conviction enters where Kelly says it does — through
*forecast quality*, not signal magnitude:

$$\text{gross}_t \;\propto\; \frac{\widehat{IC}_t \cdot \sqrt{BR^{\text{eff}}_t}}{\hat\sigma_t}$$

- $\widehat{IC}_t$ — conditional; known to be lower in dislocated regimes.
- $BR^{\text{eff}}_t$ — the **risk-effective** breadth of §4.2 (**2.24**, not 17).
  It falls automatically when the book concentrates into the muni factor, which is
  when we should be smaller.
- $\hat\sigma_t$ — replace the 63-day equal-weight estimate with $\sqrt{w'\Sigma w}$
  from §4.2's shrunk covariance. Same quantity, computed correctly, and free once
  $\Sigma$ exists.

---

## Part 4 — Signal and construction

Real gains, but all of them smaller than Part 2 and Part 3.

### 4.1 Put the reversion rate in the score (L4)

Model the dislocation as Ornstein–Uhlenbeck, $dx_i = -\kappa_i x_i dt + \sigma_i dW_i$.
Then over a holding period $h$ the expected convergence is exact:

$$\mathbb{E}[d_{i,t+h}-d_{i,t}] = -x_{i,t}\left(1-e^{-\kappa_i h}\right)
\qquad\Rightarrow\qquad
\text{score}_i = \frac{-x_{i,t}(1-e^{-\kappa_i h})}{\sigma^P_i\sqrt{h}}$$

Our score is $z_i = x_i/\sigma^d_i$: **the convergence term is missing entirely,
and it normalises by discount volatility where price volatility belongs.**

Measured half-lives (AR(1) of the demeaned discount, full history):

| fastest | bd | | slowest | bd |
|---|---:|---|---|---:|
| DSL | **11.9** | | AWF | 30.2 |
| PFN | 14.2 | | JFR | 30.9 |
| PCN | 15.3 | | **PHK** | **41.9** |

Over a 2-day hold, DSL delivers **11.0%** of its dislocation and PHK **3.3%** —
**3.4× more expected convergence per unit of z**, and we size them identically.

Two cautions: shrink $\kappa_i$ toward the pooled $\phi=0.9722$ by empirical Bayes
(raw per-name estimates will overfit — the half-life transform is convex in a noisy
$\phi$), and evaluate jointly with the band, since any score change moves turnover.

**PHK fails on four independent measures** — slowest reversion, widest discount sd
(6.92pp), most expensive tick (**10.65bp** on a $4.69 share), and leave-one-out
Sharpe *rises* 2.49 → 2.93 without it. Dropping it needs no new mathematics.

*A fifth measure was claimed here and is withdrawn.* This section argued PHK was
"the largest premium in the book and so the most likely hard-to-borrow." Measured
2026-09-06: **PHK borrows at 1.06%**, below the 2.29% universe mean, and is 4.2%
of total drag. Premium does not predict borrow cost in this universe (§3.3). The
four surviving measures are unaffected.

#### ⛔ MEASURED 2026-09-06 — this does not work, and here is why

Built and evaluated (`scripts/cef/ou_score.py`). $\phi$ re-estimated on an
expanding window ending the day before use, refit annually, empirical-Bayes
shrunk toward pooled. **The $\kappa$ term costs Sharpe at every setting:**

| score | calendar gross | band 6.4% net@15bp |
|---|---:|---:|
| **A — live, $z = x/\sigma^d$** | **1.20** | **0.70** |
| B — OU with *pooled* $\kappa$ | 1.21 | 0.70 |
| C — OU, shrunk per-name $\kappa$ | 1.11 | 0.49 |
| E — OU, raw $\kappa$ (no shrinkage) | 0.94 | 0.35 |

B reproducing A exactly is the sanity check — a common scalar cancels in
cross-sectional demeaning. E far below C confirms the convexity warning above:
shrinkage helps substantially, and is still not enough.

Mapping the $\kappa$ exposure directly, score $= x\kappa^p/\sigma^d$:

| $p$ | −0.50 | −0.25 | **0 (live)** | +0.25 | +0.50 | +1.00 |
|---|---:|---:|---:|---:|---:|---:|
| band net@15bp | 0.70 | 0.72 | **0.71** | 0.69 | 0.65 | 0.57 |

Flat below zero, monotonically declining above it. There is no peak elsewhere.

**The premise of this section was wrong.** For an OU process the stationary
variance is $\sigma^2/2\kappa$, so $\sigma^d \propto \sigma/\sqrt{\kappa}$ —
**the live z-score already carries $\kappa^{+1/2}$ in its denominator.**
Regressing $\log\sigma^d$ on $\log\kappa$ across the 17 names gives a slope of
**−0.463 against OU's predicted −0.500**. Multiplying by
$(1-\phi^h)\approx\kappa h$ therefore does not supply a missing term — it
double-counts one, taking the tilt from $\kappa^{0.5}$ to $\kappa^{1.5}$.

The denominator swap fails separately: dividing by price vol instead of discount
sd cuts turnover 31.1 → 26.0 but loses more gross than it saves (1.20 → 1.03,
net 0.33 → 0.30).

**Trials: 0 — withdrawn.** The two trials budgeted here are released. The PHK
observations in this section stand on their own and are unaffected.

### 4.2 Give the book a covariance matrix (L5)

There is no $\Sigma$ anywhere in the sleeve. Decomposing book variance over 1,424
days using the sleeve's own weights:

| component | share | what it is |
|---|---:|---|
| PC1 | 3.6% | market direction — correctly neutralised ✅ |
| **PC2** | **65.7%** | **muni vs taxable** (+0.32 on all six Nuveen munis, negative on all eleven others) |
| PC3 | 9.6% | quality / duration residual |
| PC4–17 | 21.1% | genuinely idiosyncratic |

$$BR^{\text{eff}} = 1/\textstyle\sum_k v_k^2 = \mathbf{2.24}\ \text{of 17 names}$$

The dollar-neutral construction kills market beta and then puts two-thirds of the
risk into one unmanaged spread bet. $IR \approx IC\sqrt{BR}$ computed on 17 names
overstates by **2.75×**.

Replace $w \propto \alpha$ with $w \propto \Sigma^{-1}\alpha$, **Ledoit–Wolf
shrunk** (mandatory — an unshrunk inverse concentrates into the noisiest
eigenvector). Note what this is *not*: hard group neutrality was tested and lost
gross Sharpe 0.97 → 0.82. $\Sigma^{-1}\alpha$ keeps factor exposure where alpha
justifies it and cuts it where it does not, rather than inheriting whatever falls
out of the demeaning.

*Prior, stated so it can be wrong:* Lee, Shleifer & Thaler (1991) established that
CEF discounts share a large common component. PC2 is a credit-CEF instance of it.
That the alpha survives controlling for it, while the risk does not, suggests the
factor is *partly* compensated — which is an argument for sizing it deliberately,
not for hedging it away.

#### ⚖ MEASURED 2026-09-06 — the diagnosis is right, the cure is not yet affordable

Built and evaluated (`scripts/cef/covariance_construction.py`). Ledoit–Wolf
shrunk $\Sigma$ on a trailing 252-day window ending the day before use, refit
monthly; $\alpha$ in Grinold units ($\sigma_i z_i$).

| construction | gross | turn/yr | net@15bp | **BR_eff** |
|---|---:|---:|---:|---:|
| $w \propto \alpha$ — **live** | 1.20 | 31.1 | **0.33** | **2.24** |
| $w \propto \Sigma^{-1}z$ (LW) | 1.47 | 44.1 | 0.20 | 3.92 |
| **$w \propto \Sigma^{-1}(\sigma z)$ (LW)** | **1.54** | 44.4 | 0.28 | **3.95** |
| the same, **unshrunk** | 1.67 | 52.5 | 0.18 | 4.05 |

**The concentration diagnosis is confirmed and the fix works on its own terms:
gross Sharpe +28%, effective breadth +76% (2.24 → 3.95).** Shrinkage is
vindicated exactly as predicted — unshrunk has the *highest* gross and the
*worst* net, because inverting an unshrunk $\Sigma$ loads the smallest,
worst-estimated eigenvalues and then trades to chase them.

**But it buys the breadth with turnover (+43%), and at 15bp that is the whole
gain.** Turnover-matched against the band, the only honest comparison:

| | turn/yr | net@5bp | net@15bp | net@30bp |
|---|---:|---:|---:|---:|
| **live, band 6.4%** | 14.2 | 0.97 | **0.70** | **0.31** |
| $\Sigma^{-1}$, band 9.6% | 17.4 | 1.02 | 0.69 | 0.19 |
| $\Sigma^{-1}$, band 12.8% | 13.0 | 0.86 | 0.62 | 0.25 |
| **$\Sigma^{-1}$, band 6.4%** | 24.5 | **1.11** | 0.65 | −0.03 |

**The ranking flips with cost.** At 5bp $\Sigma^{-1}$ wins decisively (1.11 vs
0.97); at 15bp it is a small loss; at 30bp a large one. Widening the band to pay
for it does not work — the $\Sigma^{-1}$ advantage decays faster than the cost
saving.

So this is not a dead idea, it is a **conditional** one: *$\Sigma^{-1}\alpha$ is
a bet that execution is cheap.* The single MOC session on record printed
**2.8bp** (§7.1), squarely in the region where it wins. That is the first
genuinely offensive reason to measure realised cost — not to decide whether to
kill the book, but to decide whether we can afford a 28% gross improvement.

**Trials: 1, and deferred** — hold until realised cost has a usable estimate,
then run once at the measured level rather than sweeping the cost assumption.

### 4.3 Buy breadth by screening on the right thing (L6)

$IR \approx IC\sqrt{BR}$ — breadth is the one input that improves the ratio without
the signal getting better. Median eligible universe today: **8 funds.**

`min_adv_usd = $3m` is what binds, and it is calibrated for a much larger book:

| ADV floor | names | | at 37 names | |
|---|---:|---|---|---:|
| $3.0m | 18 | | traded/name/day | $4,416 |
| $1.5m | 28 | | participation @ $1m ADV | **0.44%** |
| **$1.0m** | **37** | | cost model's own guard | 5% |

**But screen on ticks, not ADV.** We do not move markets; we pay ticks. At $4.69–
$17.07 a share, a one-cent spread is 2.9–10.7bp against a 32.6bp breakeven — the
minimum possible increment is a third of our edge on the worst names.

Five names we do not trade clear $1m ADV *and* are cheaper per tick than our live
median (4.3bp): **DBL (3.45), NXP (3.50), BGH (3.50), ISD (3.75), GHY (4.15)** —
and **four of the five are non-muni**, so they add breadth in the direction that
dilutes PC2.

**Trials: 1.**

### 4.4 Reopen the Kalman level — one narrow reason

| spec | gross SR | net SR | turn/yr | what happened |
|---|---:|---:|---:|---|
| rolling z, 63d | 1.72 | **0.84** | 45.3 | **failed the holdout, net −0.298** |
| Kalman λ=30 | 1.60 | 0.81 | **39.5** | never tested out of sample |
| rolling z, 252d — live | 1.23 | 0.69 | 26.3 | holdout +0.352 |

The Kalman lost to exactly one specification, and that specification was
invalidated hours later. It also beat the live config on both gross and net, at
lower turnover, and it fixes the post-cut misreading on its own terms (post-cut
mean signal −0.106/−0.073/−0.113 against the rolling z's −0.217/−0.286/−0.341).

λ already showed an interior plateau from 30 to 100, so **there is no sweep to
re-run** — fold the measured λ into the combined specification and evaluate once.

**Trials: 1.**

---

### 4.5 ✅ The joint cost-aware optimiser — measured 2026-09-06, and it wins

§2 chose the trading policy and §4.2 chose the construction, *separately*, and
§4.2 measured the consequence: composing them sequentially destroys the
$\Sigma^{-1}$ advantage. At matched turnover the sequential book's gross Sharpe
is **1.07 — below plain $\alpha$'s 1.10.** Slowing a $\Sigma^{-1}$ book down with
a scalar band gives back exactly what $\Sigma^{-1}$ bought.

The two are not features to compose. They fall out of one objective:

$$\max_w \; w'\alpha \;-\; \tfrac{\lambda}{2} w'\Sigma w \;-\; c\lVert w - w_{t-1}\rVert_1
\qquad \text{s.t.} \quad \mathbf{1}'w = 0$$

The $\ell_1$ term induces a no-trade region directly, so the band is *derived*
rather than bolted on — and it is $\Sigma$-aware, unlike the per-name scalar band.

**Turnover-matched at 14.2 turns/yr:**

| construction | turn/yr | gross | net@5bp | net@15bp | net@30bp |
|---|---:|---:|---:|---:|---:|
| $w \propto \alpha$, band 6.4% *(reference)* | 14.2 | 1.10 | 0.97 | **0.70** | 0.31 |
| the same + ADV exit *(control)* | 14.1 | 1.12 | 0.98 | **0.70** | 0.27 |
| $\Sigma^{-1}\alpha$ + band 12.1% *(sequential)* | 14.2 | 1.07 | 0.92 | 0.62 | 0.17 |
| **joint, $c_{model}$ = 25.2bp** | 14.2 | **1.33** | **1.19** | **0.90** | **0.47** |

**+0.20 net Sharpe over the band, +0.28 over sequential composition**, at
identical turnover. The control line is the load-bearing one: giving the
baseline the same ADV hygiene moves it 0.70 → 0.70, so the win is structural.

$c_{model}$ is derived, not fitted. $c_{model}\approx c_{exec}/(IC\cdot H)$ gives
19–32bp at $c_{exec}$=15bp; bisecting on turnover landed independently at 25.2bp.
The joint beats the band frontier's best point across $c_{model}$ 10–45bp
(7–29 turns/yr) — a range, not a point, and it loses outside it.

**Robustness.** Charging 3× turnover in ADV-filtered names: the joint book puts
**1.3%** of turnover there against the live band's **18.5%** — 14× less — and
still nets 0.87 vs 0.69. The win is not bought by trading illiquid names; the
*current* construction is the one doing that.

**Costs, stated plainly.** Turnover stability is materially worse: era sd/mean
**36.9% vs 11.9%**. The win is not uniform — on the active 2013+ sample the gap
is 1.14 vs 0.89, but 2013–16 *loses* (0.92 vs 1.43) where the universe is too
thin for $\Sigma^{-1}$; 2017–20 (0.86 vs 0.32) and 2021–26 (1.51 vs 1.00) win
decisively. And the ADV treatment is a real modelling fork: letting ineligible
names stay as decision variables lets $\Sigma^{-1}$ size them as hedges, putting
28% of gross in untradeable names and **losing** (0.54). Only closing them wins.

Three claims in the original framing were wrong and are corrected here: the
per-name no-trade condition $|\nabla_i|_{w_{prev}} < c$ is exact only for
**diagonal** $\Sigma$ (79% agreement on the real panel with dense $\Sigma$; the
exact condition is evaluated at $w^*$); the no-trade region is a **polytope**,
not an ellipsoid (an ellipsoid is what an $\ell_2$ penalty gives); and the IC
does **not** drop out — it sets the alpha-to-cost ratio.

Implementation: `src/analysis/l1_meanvar.py` (FISTA on $d = w - w_{prev}$ with a
joint prox for the $\ell_1$ term and the neutrality indicator, then an
active-set KKT polish; every solve returns a certificate and raises on failure),
`src/analysis/tests/test_l1_meanvar.py` (8 tests), evaluation in
`scripts/cef/joint_cost_optimiser.py`.

**Trials: 1. This supersedes item 11 rather than adding to it.**

## Part 5 — Execution: the band buys us patience, and patience is worth ticks

Currently every order is MOC. That was the right call — it fixed the 100.5bp
overnight-market-order disaster and it matches what the research assumed.

But MOC crosses the full spread by construction. With the band cutting turnover
from 31× to 14× and stretching the average hold from 6 to 16 days, **the urgency
of any individual trade collapses** — and low urgency is exactly the condition
under which passive execution becomes available.

Worth pricing (not yet measured, flagged as such):

- **Limit-on-close** at the midpoint or better, accepting partial fills. Under a
  band the cost of not filling is small: the position simply stays inside its band
  another day, which is where the policy wanted it anyway.
- **Splitting between the close and the next open** for the least urgent legs.
- Capturing even **half a tick** on the median name is ~2.2bp against a 32.6bp
  breakeven — roughly 7% of the entire edge, from order type alone.

The measurement that decides this is the same implementation-shortfall log that
§7.1 needs, so it costs nothing extra to find out.

---

## Part 6 — Not building, and why

**More prediction.** IC is 0.075 over 27 years; gross Sharpe is 1.2–1.75. The
numerator is not the problem. Every hour spent sharpening it is an hour not spent
on the two-thirds we are dropping on the floor.

**Signal combination — measured, and it is dead.** The obvious second signal is
price reversal, over 2,950 non-overlapping 2-day periods:

| | IC | t |
|---|---:|---:|
| discount z | **−0.0747** | −11.68 |
| log-price z | −0.0458 | −6.67 |
| IC-series correlation | +0.575 | |

Optimal combination $\sqrt{IC'R^{-1}IC} = 0.0748$ — **+0.1%**, with weights of
−0.95 / −0.05. The price signal is 95% subsumed. Measured, not assumed.

**Machine learning.** 17 names, one feature, IC 0.075. The bias–variance trade-off
is emphatically against it, and this is where the request for no AI slop bites
hardest.

**Regime-switching models.** The dispersion-quintile table *is* the regime study.
Vol targeting already exploits it continuously with no hidden state to estimate.

**Jump-diffusion for the discount.** Kurtosis 41.2 is real, but a fatter-tailed
model changes sizing, not the signal, and §3 handles sizing.

**Cointegration / Johansen pairs.** Already killed — `pair-reversion`, D2 +
capacity, gross 1.03 → net −0.16, needing 32.8× leverage against a 2× ceiling.

**Stochastic volatility (Heston/SABR).** We trade no derivatives.

**Almgren–Chriss scheduling.** We execute in one auction at <1% participation.
Nothing to schedule. (§5 is about *order type*, which is a different question.)

**A third pass at the distribution data.** Failed twice — as a universe filter
(1 of 8 variants beat baseline by +0.05, chosen after looking at 8) and as a
variance term inside the Kalman (1.60 → 1.28). The damage lands at 63 days; we
hold for 2. A fast-adapting $\theta$ absorbs cuts without being told, which is
§4.4's work, not additional work.

---

## Part 7 — Choosing between constructions

Parts 2–4 change the book substantially. We need a way to pick among them that
does not just re-fit the 17 names.

### 7.1 Measure what we can measure fast

Sharpe converges uselessly slowly — over 60 sessions its standard error is ~2.05
(Lo 2002), so live P&L will not adjudicate anything this year. **Cost converges
~60× faster**: at ~15 fills a session and ~6.5bp session-level dispersion, 60
sessions gives SE ≈ 0.84bp against a 32.6bp breakeven.

So log, from the next session onward:

1. **Implementation shortfall per fill** vs decision price — sets the band width
   (§2.5), prices the order-type question (§5), and is the fastest-converging
   number we have access to.
2. **Realised borrow rate per short name** — gates the leverage decision (§3.2–3.3).
3. **Realised turnover** per session.
4. **Realised IC** per session — 17 names × 60 sessions = 1,020 name-days.
5. **$BR^{\text{eff}}$ and PC2 loading**, daily.

None of these costs a trial. All of them are inputs to decisions in Parts 2–4.

### 7.2 The 27 untouched names

Committed 2026-09-06: `data/cef/cef_universe.csv` holds 44 credit CEFs and we
trade 17. **The other 27 have never informed a single specification decision**,
which makes them independent of our *selection process* — the thing the
deflated-Sharpe haircut exists to correct for. They are not independent of era or
market, and that caveat travels with any result.

This is not a tribunal. It is how we choose between the band widths, scores and
covariance treatments in Parts 2–4 **without spending trial budget on the 17**.
Live-forward runs alongside as the slow independent check.

### 7.3 ⚠ Sequencing conflict — the holdout and the breadth names are the same 27

§4.3 wants to add DBL, NXP, BGH, ISD, GHY. **Those five are among the 27.** Trading
them consumes the comparison set silently, with nothing erroring.

**Resolution: open the 27 once on the combined specification, then promote.** Costs
nothing — the comparison happens before Phase 5 anyway, and 27 names beats 22.

**Rule: no name enters the live universe before the comparison on the 27 is run
and written down.**

### 7.4 Two housekeeping items, because real capital arrives this year

- **The automatic risk controls are all disabled.** All three sleeves' `risk_check`
  return OK unconditionally, `book_drawdown_suspend_pct` is 99.0 everywhere, and
  the frozen spec's declared `kill_drawdown: 0.18` / `halve_drawdown: 0.12` are
  **read by no code path**. That was justified explicitly by *"there is no real
  capital at risk"* — a justification now on a clock. Config change, not research.
- **The existing kill rule is a bigger threat to this strategy than the market is.**
  "Kill if live net Sharpe < 0 at session 60" fires **34% of the time** on a
  strategy whose true Sharpe is exactly the 0.82 we believe. Replace the P&L
  trigger with the cost trigger from §7.1, which measures the binding constraint
  and actually converges. Keep clause (c) — discount spread below 12% — unchanged;
  it measures whether the opportunity still exists and is the clause that would
  have caught E1.

---

## Part 8 — Sequencing

Term deadline; **assumption: ~14 weeks, end of autumn term** — give me the date and
I will re-cut. **Revised 2026-09-06: total new trials 7 → 4**, taking the CEF
counter 47 → 51 and the DSR bar 2.77 → 2.80. Two trials were
released by §4.1 (the OU $\kappa$ score, measured and withdrawn) and one by
§4.2 (halved and deferred until realised cost is known). Measurement that
removes work is worth more than measurement that adds it.

### Phase 0 — this week, zero trials, no research
| # | item | status | § |
|---|---|---|---|
| 1 | **Pull IBKR borrow rates on all 17 names.** Gates every leverage decision | ✅ **done 2026-09-06** — `BORROW_NOTE_2026-09-06.md` | 3.3 |
| 2 | Start the implementation-shortfall log | in progress | 7.1 |
| 3 | Re-enable the risk controls; reconcile spec vs code | open | 7.4 |
| 4 | Replace the P&L kill trigger with the cost trigger | open | 7.4 |
| 5 | Drop PHK — four independent measures agree | open | 4.1 |
| **6** | **Availability cap on short weights** — new, from item 1 | open | 3.3 |

Item 2 is smaller than it looked. The shortfall log already exists — `slippage.csv`
carries `realised_bp`/`modelled_bp`/`excess_bp` and `trades.csv` carries
`slip_vs_decision_bp` against a stored decision price. What is missing is that
`ops/capture_fills.py` is **not called by `ops/schedule/run_cef.sh`**, so it has
only ever run by hand: **2 sessions captured out of 25 traded.** Wiring it into
the schedule is the whole of the work.

Item 6 did not exist when this plan was written. Availability binds at **$45k of
capital on NAD** against the $500k we run, and the cap is **self-financing** —
0.04 of gross Sharpe for 0.34%/yr of borrow saved. See §3.3.

### Phase 1 — the capture fix (weeks 2–5, 1 trial)
| # | item | trials | § |
|---|---|---:|---|
| 6 | **No-trade band replacing the calendar.** Derive width; verify, don't optimise | 1 | 2 |
| 7 | Price limit-on-close against MOC on the shortfall log | 0 | 5 |

**Sequencing note added 2026-09-06:** §4.5 measures a *better* endpoint than the
scalar band — net 0.90 vs 0.70 at matched turnover, because the band is derived
from the objective rather than bolted onto it. The band remains the right first
step (it is simpler, its turnover is 3× more stable, and it wins the thin-universe
era), but Phase 3 item 11 should be read as the destination, not an optional extra.

Expected: net Sharpe 0.33 → ~0.7 at 15bp, on less than half the trading. **This is
the item that matters** — and after §3.3 it matters more than when this was
written: post-borrow the same move is **0.10 → 0.48**, which is the difference
between a book indistinguishable from zero and a book worth funding.

### Phase 2 — size it properly (weeks 3–6, 0 trials)
**⚠ Re-sequenced 2026-09-06: Phase 2 is now strictly gated on Phase 1.** §3.3
measured the borrow drag at 1.22%/yr, which is most of the live configuration's
0.10 net Sharpe. Leverage multiplies return *and* drag, so sizing up a book at
0.10 buys almost nothing and risks a great deal. Do the band first, then size the
0.48.
| # | item | § |
|---|---|---|
| 8 | Decide the vol target against measured borrow and drawdown tolerance | 3.2 |
| 9 | Apply for Portfolio Margin if §8 needs gross above 2× | 3.2 |

Zero trials — this is a capital and paperwork decision, not a research question,
and doubling the vol target doubles the return at unchanged Sharpe.

### Phase 3 — construction (weeks 5–10, ~~5~~ **2** trials)
| # | item | trials | § |
|---|---|---:|---|
| ~~10~~ | ~~Shrunk-$\kappa$ OU score~~ — **measured 2026-09-06, withdrawn** | **0** | 4.1 |
| 11 | ~~Ledoit–Wolf $\Sigma$, sequential~~ → **joint cost-aware optimiser** (§4.5), which supersedes it | **1** | 4.5 |
| 12 | Fold in the measured-λ Kalman level | 1 | 4.4 |

*Evaluate 10–12 jointly with the band, never separately* — each moves turnover, and
turnover is what we have already proved we cannot hold fixed one variable at a time.

### Phase 4 — compare on the 27 (weeks 10–12)
Run the combined specification once. Record the result whatever it is.

### Phase 5 — breadth (weeks 12–14, 1 trial)
Re-screen on tick cost; promote names. **Gated by Phase 4** (§7.3).

### 8.1 If the term is shorter
Cut from the bottom. Phase 0 and Phase 1 are the plan; everything after is
improvement on top of it. Phase 5 slips to next term at no loss — breadth compounds
with whatever construction wins rather than competing with it.

### 8.2 Reproduction
| script | what it reproduces |
|---|---|
| `scripts/cef/plan_diagnostics.py` | blocks `kappa`, `pca`, `adv`, `tick`, `volscalar`, `combination` |
| `scripts/cef/band_frontier.py` | the Part 2 frontier |
| `scripts/cef/fetch_borrow_rates.py` | §3.3 rates and availability; appends `data/cef/cef_borrow.csv` |
| `scripts/cef/borrow_impact.py` | §3.3 net-of-borrow Sharpe and the drag decomposition |
| `scripts/cef/borrow_capacity.py` | §3.3 capacity, where availability binds, and the cost of the cap |

Re-run all of them whenever the panel is restaged. `fetch_borrow_rates.py` should
run *daily* rather than on demand — it builds a panel, and the one-day-of-rates
caveat in §3.3 only shrinks by accumulating sessions.

---

## Reading list

**The trading policy — Part 2, the core of this plan**
- Constantinides (1986), *Capital Market Equilibrium with Transaction Costs*, JPE — the no-trade band and the cube-root law.
- Davis & Norman (1990), *Portfolio Selection with Transaction Costs*, Math. of OR.
- Bertram (2010), *Analytic solutions for optimal statistical arbitrage trading* — OU entry/exit under proportional costs, closed form. **The single most applicable paper.**
- Gârleanu & Pedersen (2013), *Dynamic Trading with Predictable Returns and Transaction Costs*, JF — the quadratic-cost analogue, for if we ever scale into impact.
- Muthuraman & Kumar (2006) — the multi-asset band.

**Sizing — Part 3**
- Thorp (2006), *The Kelly Criterion in Blackjack, Sports Betting and the Stock Market*.
- MacLean, Thorp & Ziemba (2011), *The Kelly Capital Growth Investment Criterion* — fractional Kelly under fat tails.
- Moreira & Muir (2017), *Volatility-Managed Portfolios*, JF.

**Signal and construction — Part 4**
- Avellaneda & Lee (2010), *Statistical Arbitrage in the US Equities Market* — the OU s-score, per-name κ, and the slow-reversion exclusion rule.
- Cartea, Jaimungal & Penalva (2015), *Algorithmic and High-Frequency Trading*, Ch. 10.
- Ledoit & Wolf (2004), JMVA — covariance shrinkage; mandatory before any Σ⁻¹.
- Grinold (1989); Clarke, de Silva & Thorley (2002) — the Fundamental Law and the transfer coefficient.
- Getmansky, Lo & Makarov (2004), JFE — return smoothing from stale marks (our NAV autocorrelation is 0.388).

**Closed-end funds**
- Lee, Shleifer & Thaler (1991), *Investor Sentiment and the Closed-End Fund Puzzle*, JF — **the common discount factor; PC2 is a credit instance of it.**
- Pontiff (1996), *Costly Arbitrage: Evidence from Closed-End Funds*, QJE — who is on the other side, and why they stay there.
- Cherkes, Sagi & Stanton (2009), *A Liquidity-Based Theory of Closed-End Funds*, RFS.

**Inference**
- Lo (2002), *The Statistics of Sharpe Ratios*, FAJ.
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, JPM.
