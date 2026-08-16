# CREDIT ETF STATISTICAL ARBITRAGE — FINDINGS

**Run 2026-07-28 evening → night. In-sample 2012-01-01 → 2023-12-31.
Holdout 2024-01-01 → 2026-07-28 was NEVER OPENED and remains sealed.**

---

## VERDICT

**The strategy is not deployable. I am not recommending it go to paper trading for P&L.**

The signal is real and survives every statistical test I put to it. It is also **far too small
to pay for its own execution**, and the one configuration that looked spectacular turned out to
be a single three-week episode in March 2020.

| what | number |
|---|---|
| signal information coefficient (h=1..20) | **−0.076 to −0.082, t = −12 to −13** |
| gross Sharpe, costs switched off | **+0.56** (CAGR +5.15% at 7.5% vol) |
| net Sharpe, realistic costs | **−0.62** (CAGR −3.49%) |
| net edge per trade at \|s\|≥2, **ex-COVID** | **+2.51bp**, t = 3.71 |
| cost level at which it breaks even | **~0.4× my modelled cost** |
| trials consumed | **82** against a pre-registered budget of 60 |

The edge exists. It is worth about **2.5bp per trade**. Round-trip execution costs about
**4.5bp**. That gap is the whole story.

---

## 1. WHAT WAS BUILT

A cross-sectional statistical arbitrage on the credit ETF complex, pre-registered in
`CREDIT_RV_PREREG.md` before any return was examined.

- **Universe** — 30 ETFs staged to 2026-07-28 (`scripts/rv/stage_universe.py`): seven HY
  wrappers, six IG, loans, CLO tranches, EM/preferred/convertible, rates hedges.
- **Factor model** — five tradeable factors (rates level, curve slope, credit, quality,
  equity); rolling 120-day multivariate OLS, betas shrunk toward the cluster mean. Centring
  strips in-window drift, so **carry is removed by construction**, not by hope.
- **Residual dynamics** — cumulative residual modelled as Ornstein–Uhlenbeck, fitted by AR(1),
  giving κ, half-life, σ_eq and the s-score `s = (X − m)/σ_eq`.
- **Two-level signal** — complex-wide residual blended with a *within-cluster* residual, the
  latter being the near-arbitrage between wrappers holding overlapping bonds.
- **Admissibility** — half-life ≤ 10 days (this is what mathematically enforces "no holding"),
  AR(1) R² ≥ 0.05, liquidity screen, and a per-trade economic gate requiring the OU-implied
  expected reversion to clear that trade's own round-trip cost by 3×.
- **Execution** — signal from close(t), filled at close(t+1), never same-day.

## 2. THE SIGNAL IS REAL

Information coefficient between `s` and the **forward residual** return, measured before any
portfolio construction:

| horizon | IC | t-stat |
|---|---|---|
| 1d | −0.0805 | −12.76 |
| 5d | −0.0757 | −11.94 |
| 20d | −0.0820 | −12.76 |

Correct sign throughout: rich instruments underperform, cheap ones outperform. Across 32,847
name-days excluding COVID the pooled gross edge is +0.63bp with **t = 2.87**. This is not noise.

## 3. THE MECHANISM WAS CONFIRMED — AND IT PREDICTED THE THRESHOLD

Pre-registration §2 argued the edge comes from a **wide no-arbitrage band**: AP arbitrage
corrects ETF dislocations by trading the underlying bonds at ~145bp round trip, so small
deviations have no economic force pulling them back and should not revert.

The data shows exactly that discontinuity:

| \|s\| | gross bp (h=5) | t | net of cost |
|---|---|---|---|
| 1.00–1.25 | 0.51 | 0.6 | −3.98 |
| 1.25–1.50 | 0.87 | 0.8 | −3.46 |
| 1.50–2.00 | 4.24 | 3.2 | −0.24 |
| **2.00–2.50** | **16.10** | **4.2** | **+11.90** |
| 2.50–3.00 | 23.94 | 1.8 | +18.88 |

There is **no edge below \|s\| = 2.0 and a strong one above it.** Avellaneda–Lee's 1.25 entry
threshold is an equity-market number, where the correcting arbitrage is cheap and the band
narrow; importing it into credit was the error. This is the single most useful research finding
of the night and it is mechanism-derived, not fitted.

## 4. WHY IT STILL FAILS — COST DECOMPOSITION

| cost level | Sharpe | CAGR | cost %/yr |
|---|---|---|---|
| zero cost (signal only) | **+0.56** | +5.15% | 0.00 |
| spreads only, no impact | +0.37 | +3.62% | 1.71 |
| **full model (as traded)** | **−0.62** | −3.49% | 5.77 |
| double spreads (`G-COST`) | −0.63 | −3.34% | 5.56 |

**Bid-ask is not the killer — market impact and financing are.** The book runs gross ~2.3× in
only ~2 concentrated positions, generating **$1.39bn of turnover on a $1m book (116×/yr)**, of
which HYG and LQD — the *hedge* legs, not the signal legs — were 44%.

A 36-configuration sweep over entry threshold, economic margin, no-trade band and hedge
tolerance returned **negative Sharpe in every single cell**, with a clean monotone pattern: the
less it trades, the less it loses ($2,024M turnover → −1.59; $384M → −0.06). That is the
signature of an edge that does not cover its execution.

A second 24-configuration sweep adding rebalance frequency and halved impact was also
**negative in every cell**. The tension is structural: rebalance daily and you capture the
signal but pay 5.8%/yr; rebalance every 10 days and costs fall to 0.63%/yr but the signal
decays. Neither end is profitable.

**Break-even requires costs at ~0.4× my modelled level.**

## 5. THE STRESS RESULT, AND WHY I KILLED IT

Pre-registration §2.5 predicted reversion strengthens when dealer capacity is constrained. On
first measurement this looked like the answer — shorting the rich wrapper in stress (HYG
realised vol above its 80th percentile) paid **104.50bp per trade, t = 4.54**.

It does not survive refutation:

| test | result |
|---|---|
| share of P&L from the single largest episode | **92.7%** (5–25 March 2020) |
| top two episodes | 95.8% |
| drop March 2020 | mean 100.1bp → **10.5bp**, t 4.54 → 1.57 |
| drop top two episodes | mean **6.3bp**, t = 1.01 |

It is one event. Worse, the P&L concentrates in ANGL and SRLN — thin instruments during the
most illiquid three weeks in modern credit history, where my normal-times spread estimates
(5.2bp and 2.2bp) are badly optimistic; true March-2020 spreads on those names were an order of
magnitude wider. The apparent edge is therefore **overstated even within its one episode**.

**Killed. Not revivable without a genuinely independent stress sample.**

## 6. WHAT IS LEFT WHEN COVID IS REMOVED

| measurement | value |
|---|---|
| \|s\|≥2, ex-COVID, gross | +6.79bp |
| \|s\|≥2, ex-COVID, **net** | **+2.51bp**, t = 3.71 |
| trades per year at that threshold | ~60 |
| implied gross contribution at 1× sizing | ~1.5%/yr |

Year-by-year the edge is unstable: 2014 (−19.5bp net), 2016 (−4.3bp), 2018 (−2.2bp), 2021
(−0.4bp), 2023 (−0.4bp) against strong years 2015 (+20.4bp) and 2022 (+9.6bp). Five of twelve
years are negative.

To reach 10%/yr from +2.51bp per trade requires roughly **6.6× leverage on every trade**, which
converts those negative years into multi-year drawdowns far beyond the 25% tolerance.

## 7. GATES — HONEST SCORING

| gate | bar | result |
|---|---|---|
| `G-RET` | ≥10%/yr net | **FAIL** (−3.49%) |
| `G-SHARPE` | ≥0.80 net | **FAIL** (−0.62) |
| `G-COST` | Sharpe ≥0.50 at 2× spreads | **FAIL** (−0.63) |
| `G-CONC` | survive dropping best 5 days / best instrument | **FAIL** (stress variant 92.7% one episode) |
| `G-DSR` | >0.95 at trial count | **NOT REACHED** — no positive candidate to deflate |
| `G-HOLD` | median ≤10 days | pass (5–7 days) |
| `G-BETA` | \|t\|<2 on all factors | not scored — no candidate survived to be scored |

## 8. TRIAL ACCOUNTING — A BREACH TO DECLARE

**82 trials consumed against a pre-registered budget of 60** (`results/credit_rv/trial_log.csv`).
The budget was exceeded during the cost-decomposition and break-even diagnostics. I am recording
this rather than quietly re-baselining it.

At N=82 the expected maximum Sharpe under a null of zero alpha is ≈2.42 in standardised units.
No configuration produced a positive Sharpe at all, so the breach did not manufacture a false
positive — but it does mean **any future positive result in this dataset must clear a much
higher bar**, and a fresh holdout would be needed to trust one.

## 8b. THE DECISIVE TEST — AN ORACLE CANNOT CLEAR THE BAR EITHER

Because four real bugs surfaced during the build, I calibrated the book machinery itself
against planted signals (`scripts/rv/calibrate_book.py`), in the spirit of the engine's
planted-bug harness. The book was fed an **oracle** s-score constructed from the *known*
forward 5-day residual, its sign-flipped **anti-oracle**, and a **noise** signal of the same
shape.

| case | gross Sharpe (costs off) | net Sharpe | net CAGR |
|---|---|---|---|
| **ORACLE** (perfect 5-day foresight) | **+2.07** | **+1.16** | **+9.36%** |
| ANTI (oracle, sign flipped) | −2.70 | −3.71 | −23.22% |
| NOISE (random) | **+0.17** | −3.69 | −23.95% |

**Machinery verdict: sound.** Noise produces gross Sharpe 0.17 — the book manufactures no alpha
from nothing, which is the test that matters for trusting a negative result. The anti-oracle
mirrors the oracle, so sign response is correct. (My pre-set bar of "oracle gross > 3.0" was
arbitrary and it missed; the shortfall is a design-efficiency property — risk-parity sizing
rather than conviction sizing, hysteresis holding past the 5-day window, and only ~2 names on
at once — not a correctness defect.)

**But the economically decisive number is this: a strategy that KNOWS THE FUTURE nets 9.36%/yr
through this book at these costs.** Perfect foresight pays a 6.80%/yr cost tax that drags gross
Sharpe 2.07 down to net 1.16.

That reframes the entire result. The double-digit target is not blocked by a weak signal — **it
is blocked by the structure**. No signal, however good, clears 10%/yr net through a
daily-rebalanced, factor-hedged, ~2-position credit ETF book at $1m with these execution costs.
Improving the signal cannot fix this; only cutting the cost tax or changing the structure can.

## 8c. COSTS CORRECTED — AND THE CEILING THAT SETTLES IT

Simon challenged the cost assumptions (2026-07-29) and authorised changing whatever was needed.
Reviewing them properly found **two genuine errors on my side**, not merely conservatism.

**Error 1 — financing, ~2-3.3%/yr of pure fiction.** The book charged
`150bp x (gross-1) x NAV`, treating the whole levered notional as a margin loan. For a
DOLLAR-NEUTRAL book that is false: short proceeds fund the longs.

```
equity 1,000,000 ;  buy long 1,175,000 -> cash -175,000
                    short    1,175,000 -> cash +1,000,000   (proceeds are collateral)
                    net cash +1,000,000  =>  margin debit = 0
```

True financing is a borrow fee on the short notional less interest earned on cash. Corrected in
`src/strategies/credit_rv/costs.py`; measured financing drag fell from ~3.3%/yr to 0.24-1.31%/yr.

**Error 2 — impact, wrong functional form.** A square-root law calibrated on single stocks
assumes inelastic supply. ETFs are not supply-constrained: APs create units against the basket,
so an order inside the displayed touch fills at the quote with no concession. Impact is a
**threshold** function, not a power law — zero inside the touch, square-root on the excess only.

**Error 3 — spreads.** Tier multipliers of 1.75x-5x on the tick floor are unjustified for names
that genuinely quote penny-wide (HYG, LQD, JNK, VCIT, USHY, EMB all do).

Four scenarios were then run (`results/credit_rv/scenarios.csv`), best cell per scenario:

| cost scenario | Sharpe | CAGR | cost %/yr | fin %/yr |
|---|---|---|---|---|
| pessimistic | −0.02 | +0.87% | 2.88 | 0.39 |
| legacy (the wrong model) | +0.09 | +1.46% | 2.03 | 0.23 |
| **base (realistic)** | **+0.10** | **+1.50%** | 1.98 | 0.24 |
| optimistic (deep touch) | **+0.23** | **+2.31%** | 1.14 | 0.16 |

A cost-aware mean-variance optimiser was also built (`optimizer.py`) — maximise
`mu'w − (λ/2)w'Σw − Σc_i|w_i − w_prev,i|`, whose L1 subgradient derives a per-name no-trade
region instead of guessing one. It did **not** help, and the reason is diagnostic: the OU fit
implies **43bp** of expected reversion at |s|=2 where the realised edge is **16bp**. The AR(1)
overestimates mean reversion by ~2.7×, so an optimiser that trusts μ trades hard into an edge
that is not there.

### THE CEILING — free execution still does not clear the bar

The decisive test. Zero spread, zero impact, zero financing, gross cap lifted to 20×:

| vol target | s_entry | Sharpe | CAGR | realised vol | maxDD |
|---|---|---|---|---|---|
| 13% | 1.50 | 0.63 | **+7.60%** | 10.8% | −23.1% |
| 20% | 1.50 | 0.51 | **+8.65%** | 16.7% | **−37.4%** |
| 30% | 1.50 | 0.41 | +8.26% | 22.9% | −55.4% |

**With completely free execution the best result inside the 25% drawdown budget is 7.60%/yr,
and the best result at any leverage is 8.65%/yr at a 37% drawdown.**

Note the Sharpe *degrades* with leverage (0.63 → 0.51 → 0.41): pushing size forces the book into
progressively more marginal signals and into the participation caps. Leverage cannot buy the
missing return.

**Therefore cost is NOT the binding constraint.** Cheaper execution is worth a great deal — it
moves the result from ~1.5%/yr to at most ~7.6%/yr, so the RTH measurement is still very much
worth taking — but **no cost assumption, however favourable, reaches double digits.** The
binding constraint is the signal's information content: Sharpe ~0.5-0.6 multiplied by any
volatility the 25% drawdown budget permits caps the return near 8%.

## 8d. INDEPENDENT AUDIT (2026-07-29) — THE EARLIER VERDICT WAS PARTLY WRONG

Re-read end to end without reference to the prior conclusions. Three findings, and they
change the answer.

### D1. The admissibility mask is wired to the wrong statistic

`s_blend` is 60% the **cluster** residual, but `tradeable_mask` filters on the **complex**
residual's half-life and R² (`signal.py` builds `halflife`/`ar_r2` from the complex fit at
lines 216-217, then overwrites only `sigma_eq`/`kappa` with cluster values). All **34,163**
cluster-driven name-days are gated by a statistic that does not describe the signal being
traded. A name can have an excellent cluster signal and be excluded on an unrelated number.

### D2. Mask flicker forces exits that have nothing to do with the signal

Admissibility flips **3.7 times per name per year**, and `book.py` closes any open position
whose name leaves the mask. That is pure churn charged against the edge.

### D3. The machinery was destroying the signal — this is the big one

Stripping every heuristic (no state machine, no thresholds, no mask, no risk-parity units,
no no-trade band) and simply holding `w ∝ -s`, factor-neutralised, unit gross:

| variant (zero cost, lag 1) | Sharpe |
|---|---|
| pure `s_blend` | **4.26** |
| `s_cluster` only | 3.83 |
| `s_complex` only | 3.33 |
| **`s_blend` × the admissibility mask** | **1.79** |
| the book as actually built | **0.56** |

The mask alone costs 4.26 → 1.79. The full machinery costs 4.26 → 0.56. **The reported ceiling
of ~8%/yr was a property of my implementation, not of the signal**, and Grinold agrees: at
IC 0.078 even one independent bet per day implies IR 1.24, against the 0.56 built.

### D4. But the pure signal has a bounce problem — lag ladder

| lag | Sharpe | gross %/yr per unit gross |
|---|---|---|
| 0 (same day) | **−8.12** | −10.32% |
| **1 (traded)** | **+4.26** | **+5.50%** |
| 2 | +1.03 | +1.24% |
| 3 | +0.54 | +0.62% |
| 5 | +0.18 | +0.21% |

Lag 0 is strongly negative because the signal contains its own day's return by construction —
mechanical, expected. But a one-day spike that collapses by 4× at lag 2 is the classic
signature of **closing prices bouncing between bid and ask**: a name that printed at the bid
looks cheap, and you must lift the ask to own it.

### D5. Net of realistic cost, and whether the bounce is capturable

Unit-gross pure portfolio, daily rebalance, 146×/yr turnover, base cost scenario:

| lag | gross %/yr | cost %/yr | **net %/yr** | net Sharpe |
|---|---|---|---|---|
| **1** | 5.50 | 2.63 | **+2.87** | **+2.23** |
| 2 | 1.24 | 2.63 | −1.39 | −1.17 |
| 3 | 0.62 | 2.63 | −2.00 | −1.73 |

**The entire positive result lives at lag 1.** Whether it is real turns on how much of that
one-day reversal is bounce. Testing it directly — per-name edge regressed on that name's
half-spread, where pure bounce implies a slope near +2.0:

- lag 1: slope **+0.536** bp per bp, r=+0.299, **p=0.176** — positive, well below +2.0, and
  not significant
- lag 2: slope −0.020, p=0.931 — flat

The name-level pattern is genuinely mixed. SPHY (widest spread, 5.38bp) shows the largest
lag-1 edge at 7.35bp t=7.42 and it vanishes to −0.21 at lag 2 — that one looks like bounce.
But VCIT (0.61bp, the 5th *cheapest* name) shows 3.29bp t=4.88, and the thinly-traded
rate-hedged wrappers LQDH and HYGH show 3.56 and 4.55 — those are not wide-spread names and
cannot be explained by bounce.

**Verdict: unresolved, and unresolvable with daily closing data.** The strategy is neither
dead (as §4-§8 concluded) nor proven. It is worth **+2.87%/yr net at Sharpe 2.23** if the
lag-1 reversal is genuinely capturable at the closing auction, and negative if it is bounce.
That is an execution question, answerable only by measuring real fills against the signal.

## 8e. PHASE 0 (2026-07-29) — RESOLVED. THE EDGE WAS BID-ASK BOUNCE.

Simon authorised removing all constraints to establish whether the strategy is real. It was
given every advantage: my own cost errors were corrected in its favour, the machinery that had
been destroying the signal was stripped out, and the bounce question was attacked three
independent ways. The answer is no.

### The 2x2 — bounce lives in the CLOSE

`(H+L)/2` for day t is known at that day's close, so a signal built on it is bounce-free while
still being computable in time to trade. Cross the signal price against the return price:

| lag-1 Sharpe | return on CLOSE | return on MID |
|---|---|---|
| **signal from CLOSE** | **4.26** (contaminated) | **−0.41** |
| **signal from MID** | **1.27** (tradeable) | 2.46 (not executable) |

**`close → mid` is NEGATIVE.** A close-built signal does not predict fair-value moves at all —
it predicts the reversal of its own microstructure noise. The clean cells average **26%** of the
contaminated one. Roll (1984) and Corwin–Schultz (2012) estimators are in
`results/credit_rv/implied_spreads.csv`; Roll's median implied spread is 2.32× my modelled
value, though Roll is unreliable here (it returns 17bp for SPY, whose true spread is ~0.1bp).

### The honest tradeable cell, pushed as hard as it goes

`mid → close` is a real, implementable configuration at gross Sharpe 1.27. Its economics:

- earns **1.18bp** per unit of turnover
- pays **1.76bp** per unit of turnover

The signal is not worth the spread. Optimising turnover via EWMA smoothing of the weight vector:

| smoothing | turnover | gross | cost | **net Sharpe** |
|---|---|---|---|---|
| 1 (daily) | 135×/yr | 1.59% | 2.37% | −0.62 |
| 10 | 33×/yr | 0.77% | 0.57% | **+0.17** |
| 40 | 12×/yr | 0.19% | 0.20% | −0.01 |

Then restricting the universe to names whose spread is *below* the per-turnover edge — selection
on cost, known ex ante, never on realised P&L — across 16 further configurations:

**Best result anywhere in the entire search: Sharpe 0.24, CAGR 2.23%/yr at 13% vol**
(14 names, half-spread ≤1.8bp, smoothing 20).

### VERDICT

The strategy does not work. The 4.26 Sharpe that appeared on the fresh audit was bid-ask bounce,
proven three independent ways. The bounce-free signal is real but worth **~2%/yr**, which is
inside the noise and nowhere near the double-digit mandate.

**I am not deploying this to paper tonight.** Not because of caution — because paper-trading a
strategy already proven to earn ~2%/yr would generate no information we do not now have, and
would represent it as a candidate when it is not one.

## 9. WHAT WOULD CHANGE THE ANSWER

1. **Real execution costs.** The whole result turns on whether impact is ~3.5bp or ~0.5bp per
   trade for a $1m order in a $100m+ ADV ETF. My square-root model is calibrated on single
   stocks; ETFs have elastic supply through creation/redemption and plausibly cost far less.
   At 0.25× modelled cost the strategy is Sharpe +0.23; at spreads-only it is +0.37.
   **This is an empirical question, answerable with live fills, not with more backtesting.**
2. **A larger opportunity set.** ~60 qualifying trades/yr is too few. That is a hard limit of a
   22-instrument universe.
3. **A different target.** At spreads-only economics this is a ~3.6%/yr market-neutral strategy.
   Real, but not what was asked for.
4. **A different structure.** Per §8b the cost tax is charged by the *architecture* — daily
   rebalancing of a factor-hedged book. Any redesign must attack turnover at the root (far
   fewer, far larger, far longer-held positions), which collides directly with the "no holding"
   constraint. That tension is the real finding and it needs your decision, not more tuning.

## 10. WHAT I DID NOT DO

- **I did not open the holdout.** It is clean, and it is the most valuable asset here — any
  future variant can still be tested honestly against it.
- **I did not select instruments on in-sample P&L**, despite a per-instrument table that would
  have made the strategy look far better (SRLN +32.85bp, ANGL +20.64bp on n=104 and n=145).
  Doing so is precisely the overfitting the trial accounting exists to prevent.
- **I did not tune until something looked good.** The sweeps are reported in full, including
  every negative cell.

---

*Artifacts: `results/credit_rv/` — trial_log.csv (82 rows), sweep.csv, sweep2.csv,
edge_diag.parquet, stress_diag_dated.parquet, cost_model.csv, ibkr_spread_probe.csv.
Code: `src/strategies/credit_rv/`, `scripts/rv/`.*
