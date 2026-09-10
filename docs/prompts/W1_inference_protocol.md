# W1 — The inference protocol: holdout, counters, and the statistics that decide

**Reads first:** `00_BRIEF.md` §5 (harness), §6 (house rules), §7 (standing decisions).
**Lever:** inference. Every other prompt's decision rule inherits what this one builds.
**Trials:** 0. **Touches the live book:** no.
**Run this before any other research prompt.** It changes what a decision rule means.
**Supersedes:** P8.6, P5.6, P5.5.

---

## Paste from here

You are a quant researcher on the QUANTT credit closed-end-fund book: 17 CEFs,
dollar-neutral cross-sectional discount reversion, MOC at T+1, 4.8% no-trade
band, $500k IBKR paper capital. Read `docs/prompts/00_BRIEF.md` in full, then:

1. `docs/RESEARCH_AND_METHODOLOGY.md` §2.1 (the deflated-Sharpe haircut
   √(2 ln N); the permanent trial counter) and §2.3 (walk-forward, bootstrap,
   negative controls).
2. `docs/RESEARCH_STATE.md` — the CEF trial counter (48 after the band) and
   whatever per-trial Sharpes are recorded.
3. `docs/PLAN.md` §7.1 (Lo 2002: Sharpe SE ≈ 2.05 over 60 sessions; cost
   converges ~60× faster) and §7.4 (the P&L kill rule fires 34% of the time
   on a true 0.82).
4. `scripts/cef/band_frontier.py` — where dates enter every harness run, and
   the configuration grid whose argmax we refuse to pick (which is exactly
   the set a PBO test needs).
5. `results/cef/ALPHA_AUDIT_2026-09-05.md` "What this audit does NOT
   establish" (the survivorship paragraph) and
   `docs/RESEARCH_AND_METHODOLOGY.md` §5.4 (the point-in-time rebuild, which
   *raised* the Sharpe — that precedent cuts both ways and must be cited).

This prompt has three parts. Part A is a protocol and a helper other prompts
import. Part B is a statistics module. Part C is a data-recovery job that can
run in parallel and takes the longest.

---

## Part A — The holdout protocol and the two counters

### Why the 27 alone is not enough

The live universe is the liquid 17. The 27 untouched names are the illiquid
tail ($0.1–2.4m ADV against the 17's $3.1–49m). A specification that works on
both liquidity regimes is reassuring; one that works on the 17 and not the 27
may be a liquidity-conditional effect; one that works on the 27 and not the 17
is untradeable. Sign agreement on the 27 is a **weak** check. A **time
holdout** on the same names is a strong one: it asks whether the rule, fitted
through 2022, still works after.

### The rules, which every research prompt now inherits

1. **Time holdout.** Every *estimated* quantity — a window length, a
   threshold, a coefficient, a band width, a cost model, a factor loading — is
   estimated on data **before 2023-01-01**. Every harness table shows two
   rows: fit (2005–2022) and holdout (2023–2026), never a pooled row alone.
   Derived quantities (the cube-root band width, Σ⁻¹·IR budgets) are computed
   on the fit period and *applied* to the holdout unchanged. Rolling
   estimators (252-day z moments) are fine on the holdout because they use
   only trailing data; what is forbidden is *choosing* anything with sight of
   2023–26.
2. **The 27 stay** as the second check (W10 Part A owns the one-time run).
   A decision rule requires the holdout row to agree in sign **and** the 27 to
   agree in sign. If the two disagree with each other, the spec is not
   adopted and the disagreement is written up — it is information about
   liquidity-dependence, not noise.
3. **Two counters** in `docs/RESEARCH_STATE.md`, each with its own
   deflated-Sharpe bar √(2 ln N):
   - `CEF trials: 48` — every specification of the discount book (signal,
     policy, universe, sizing) evaluated with sight of P&L.
   - `GAMMA trials: 0` — every specification of the options sleeve.
   Every prompt states which counter it increments. The **combined** book is
   judged on the joint record, not on either counter alone.
4. **The falsifier is pre-registered with the trial.** Every adoption names
   the live statistic and the horizon that would reverse it. W7's turnover
   readout is the model.

### The helper

`scripts/cef/holdout.py`:

```python
from scripts.cef.holdout import FIT, HOLDOUT, split, assert_no_peek
fit_T, hold_T = split(T)                        # by the 2023-01-01 boundary
assert_no_peek(params_fitted_on=fit_T.index)    # raises, naming offending dates
```

`split` returns the two frames; `assert_no_peek` takes the index the
parameters were fitted on and raises naming the offending dates. `evaluate()`
in `band_frontier.py` gains a `period` label so its printed rows say which
they are, and `band_frontier.main()` prints both rows for every construction
it already reports.

**Do not move the boundary.** 2023-01-01 gives ~3.7 years of holdout, about a
fifth of the sample. That is the number.

---

## Part B — The statistics, each with its formula in the code

Add to `src/backtest/tearsheet.py`, each with a docstring stating the formula
and the paper, and a test against a hand-computed example.

**1. Lo (2002) autocorrelation-corrected Sharpe SE.**

The **IID form is confirmed** (verified 2026-09-09 via Bailey & López de Prado,
who reproduce Lo's derivation): for T observations,

    SE(ŜR) ≈ sqrt( (1 + 0.5·ŜR²) / T )

with ŜR at the *original* sampling frequency, non-annualised. **Implement this
one now** and put it next to every Sharpe the dashboard shows; refuse to render
a Sharpe without it.

**The autocorrelation correction is derived here rather than cited**, because
the paper is paywalled and the derivation is three lines. For returns with
autocovariance structure ρ_k, the q-period return has

    Var(Σ_{t=1}^q r_t) = q·σ² + 2σ²·Σ_{k=1}^{q−1}(q−k)·ρ_k

so the q-period Sharpe is `SR(q) = η(q)·SR(1)` with

    η(q) = q / √( q + 2·Σ_{k=1}^{q−1}(q−k)·ρ_k )

For **AR(1)**, where ρ_k = ρ^k, the sum has a closed form:

    Σ_{k=1}^{q−1}(q−k)·ρ^k = [ q·ρ·(1−ρ) − ρ·(1−ρ^q) ] / (1−ρ)²

**Verify both before use** — the closed form must equal the brute-force sum to
machine precision across q ∈ {2, 12, 60, 252} and ρ ∈ {0, ±0.15, 0.38, 0.9},
`η(q, 0)` must equal √q exactly (it does: η(252,0) = 15.8745 = √252), and a
Monte Carlo on simulated AR(1) returns must reproduce η(q) as the ratio of
q-period to 1-period Sharpe. All three checks passed on 2026-09-10; **re-run
them in the test suite rather than trusting this note.**

**And measure ρ before assuming the correction matters.** On the live band
policy's own daily P&L series the first-order autocorrelation is **+0.003**
(ρ₂ −0.003, ρ₃ −0.020) — essentially zero, so η(252) differs from √252 by
**0.3%** and the correction is immaterial *for this book*. Implement it anyway,
because it is correct and free, but do not present it as a fix for anything
here. Where it will matter: the repo's **NAV** autocorrelation is 0.388, at
which naive √252 would overstate an annualised Sharpe by **50%** — so any
statistic computed on a NAV-derived or unsmoothed series (W13), or on the
gamma book's χ²-shaped P&L (gamma/G5), needs it.

**One property worth stating in the code comment:** η scales the Sharpe estimate
and its standard error by the same factor, so **the t-statistic is unchanged**.
The correction fixes the reported *level*, not the significance — which matters
most when comparing two series whose autocorrelations differ.

**2. Minimum track record length.** **Verified term-for-term against the
primary source 2026-09-09** — note it originates in Bailey & López de Prado's
*"The Sharpe Ratio Efficient Frontier"* (2012), **not** the Deflated Sharpe
paper:

    MinTRL = 1 + [1 − γ̂₃·ŜR + (γ̂₄ − 1)/4 · ŜR²] · (Z_α / (ŜR − SR*))²

with γ̂₃ and γ̂₄ the skew and kurtosis of the track record being tested, ŜR its
Sharpe **at the original sampling frequency, non-annualised**, SR* the
benchmark, Z_α the one-sided normal critical value. Use SR* = 0 for "is it
positive" and 0.43 for "is it the band's expectation"; kurtosis is 41.2 on the
backtest, but measure the live one. Report MinTRL in sessions at α = 0.05. It
will be years — that is the honest statement of why P&L is not the readout.
The underlying asymptotics need roughly 30+ observations before the moment
estimates feeding it can be trusted; below that, report "insufficient data"
rather than a number.

**3. Probability of backtest overfitting** (Bailey, Borwein, López de Prado &
Zhu 2014, CSCV). Over the configuration set the band frontier already
evaluates (widths 0.2–12.8%, plus the calendars, at each cost level), split
the sample into S = 16 blocks, evaluate all C(16,8) in-sample/out-of-sample
splits, and compute the probability that the in-sample-best configuration has
below-median out-of-sample rank. Report PBO at 5/15/30bp. Note in the
write-up that the band width was *derived*, not selected, so PBO here
measures the risk we avoided — and it becomes the bar for any future selected
parameter.

**4. Deflated Sharpe ratio** (Bailey & López de Prado 2014). **Verified against
the primary source 2026-09-09:**

    SR₀ = √V[{ŜR_n}] · [ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]
    DSR = Z[ (ŜR − SR₀)·√(T−1) / √(1 − γ̂₃·ŜR + (γ̂₄−1)/4·ŜR²) ]

with γ = 0.5772 the Euler-Mascheroni constant, Z the standard-normal CDF, Z⁻¹
its inverse, **N the number of *independent* trials**, V[{ŜR_n}] the variance
across trial Sharpes, and T the sample length. **Note the independence
requirement on N** — our counter records trials, not independent ones, so state
that assumption where the number is reported. Parse N from `RESEARCH_STATE.md` automatically so the
number moves when the counter does. If per-trial Sharpes are not recorded,
reconstruct what can be reconstructed from the results notes, list them in a
table with sources, and state the assumption used for the rest. **Report DSR
separately for the CEF and GAMMA counters.**

**5. The cost test's power**, since it is the kill trigger (W6). Given the
observed per-session dispersion of `exec_bp` from W7's log: the number of MOC
sessions needed to detect a mean 10bp above breakeven at 80% power, and the
current power at the sessions on hand.

Runner: `scripts/cef/inference_report.py` runs all five on the current live
series and the harness path, writing `results/cef/INFERENCE_<date>.md` and
`results/cef/inference.json`.

---

## Part C — Quantify survivorship (this is a data job; start it early)

Every Sharpe in this repo is computed on a panel of funds alive today. PDO has
1,402 days of history; MHD has 6,989. Every CEF that closed or merged across
27 years is absent.

### Why the direction of the bias is not obvious here

The naive story — dead funds performed badly, so a survivor panel overstates —
is right for a long-only fund and wrong here:

- The long leg buys funds at unusually wide discounts. Funds that eventually
  liquidate or merge spend their last years at wide discounts (small,
  illiquid, cutting distributions). A survivor-only panel removes exactly the
  names the long leg would have been buying, **and their exit outcomes** — and
  those exits are bimodal: a merger or open-ending at NAV is a windfall for a
  long (the discount closes to zero on a known date), a liquidation at a
  fire-sale price is a loss, a fund that simply drifted wider for years is a
  long-leg loser.
- The short leg shorts rich funds. Rich funds rarely die.

So the missing names sit disproportionately on the long leg with a bimodal
payoff, and the bias could run either way. The only way to know is to find
them.

### The work

**1. Build `data/cef/cef_dead.csv`** with columns `ticker, name, family, group,
first_date, last_date, event (liquidated | merged_into:<ticker> | open_ended |
converted | delisted_other), event_date, terminal_terms, source_url,
confidence`. Sources in order of reliability:

- SEC EDGAR: N-CEN (2018+) items B.2/B.3 for mergers and liquidations; N-SAR
  before that; N-CSR "subsequent events". EDGAR full-text search for
  `"closed-end" AND ("liquidation" OR "reorganization" OR "merger")`
  restricted to the families in our universe: Nuveen, PIMCO, BlackRock, Eaton
  Vance, Invesco, Western Asset, DoubleLine, AllianceBernstein, MFS, Morgan
  Stanley, Franklin/Templeton, Putnam, Delaware, Dreyfus, Neuberger.
- Fund-family press releases on completed mergers. **Nuveen and BlackRock
  both ran large muni-CEF consolidation programmes; Nuveen merged dozens of
  muni CEFs between 2014 and 2020.** That programme is the single largest
  source of missing names in the group that carries most of our risk, so it
  gets its own subsection in the note.
- CEFConnect historical fund lists, and ICI's annual closed-end fund
  statistics for counts by year, to bound how many we are missing.
- yfinance: some delisted tickers still return history; try each.

Scope: taxable bond, high-yield, loan, municipal and EM-debt CEFs listed on
NYSE/NYSE American 1998–2026.

**2. Recover history where possible** — price and NAV from yfinance, EDGAR
N-CSR NAV tables, or CEFConnect historical — staged into the panel with a
`delisted` flag and the `event_date`.

**3. Rerun the live specification on a point-in-time universe:** eligible on
date t if listed, ADV clears the screen, and alive. Terminal returns on the
event date: merger at NAV → the position converts at the stated terms;
liquidation → proceeds at the stated terms; unknown terms → last price, and
flag it. Report gross, net@15, net of borrow, turnover, IC, by era, against
the survivor-only panel.

**4. Bound what could not be recovered.** For dead funds with no recoverable
history, two bounding scenarios applied at the long leg's typical weight for a
name of that size: (a) each earned the worst-quintile survivor return over its
final 252 days and exited at the last price; (b) each exited at NAV. Report
the Sharpe under each. **The deliverable is a range, not a point.**

---

## Deliverables

- `scripts/cef/holdout.py` with tests (a fit that peeks must raise);
  `band_frontier.py` printing both periods; the two counters in
  `RESEARCH_STATE.md`.
- `src/backtest/tearsheet.py`: `lo_se`, `min_trl`, `pbo_cscv`,
  `deflated_sharpe`, with tests; `scripts/cef/inference_report.py`;
  `results/cef/INFERENCE_<date>.md` and `inference.json`.
- `data/cef/cef_dead.csv` (source URL and confidence grade on every row),
  `results/cef/SURVIVORSHIP_<date>.md` with the list, the coverage estimate,
  the PIT rerun and the bounds; `ALPHA_AUDIT`'s caveat updated to cite it.
- Dashboard hooks for W9: Sharpe tiles carry `value ± SE (n sessions; MinTRL
  N)`; the drawer shows PBO and DSR with their inputs and both counters.

## Acceptance

- The live Sharpe never appears anywhere without its SE and n.
- The DSR recomputes when `RESEARCH_STATE.md`'s counter line changes (test by
  editing a copy).
- The PIT rerun reproduces the survivor-only numbers exactly when the dead
  names are excluded (regression check on the harness).
- `assert_no_peek` raises on a deliberately peeking fit, in a test.

## Do not

- Do not compute any live statistic on modelled sessions.
- Do not tune S or the block length to make PBO look better; 16 blocks is the
  paper's default and is stated in advance.
- Do not infer a fund's death from a gap in yfinance data alone; find the
  filing.
- Do not fill a dead fund's missing NAV with its price.
