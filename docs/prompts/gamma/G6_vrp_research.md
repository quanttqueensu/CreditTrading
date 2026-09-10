# G6 — Realised against implied in credit: does a timing signal exist at all?

**Reads first:** `G0_BRIEF.md` (§2 and §4 especially), `G3_hedging.md` Part C
(which defines the only benchmark this prompt may use), `G2_surface.md`.
**Settles:** whether long gamma in credit can be timed, and if so by what.
**Trials:** 0 — this is measurement and a pre-registration. G7 spends the trial.
**Touches the live book:** no. Nothing is traded here.
**Run after G1, G2, G3.**

---

## Paste from here

You are a quant researcher on the QUANTT book. Read `docs/prompts/gamma/G0_BRIEF.md`
in full — its §4 table is the prior this prompt is testing against, and you
should not re-derive it. Then read `results/gamma/SURFACE_<date>.md` (G2) and
`results/gamma/HEDGING_SPEC_<date>.md` (G3).

---

## Part A — The base rate, measured on our own data

Before any timing question, establish what a *systematically held* long-gamma
position would have earned in each instrument. This is the number every timing
claim must beat.

For HYG, TLT, LQD (and SPY as the reference), daily, over the full extracted
window:

- **`rich_ratio`** — implied variance ÷ **close-to-close** forward realised
  variance, at matched horizon. G3 Part C is not optional here: using Parkinson
  or intraday realised variance in the denominator will bias this ratio
  systematically and it is the ratio the entire programme turns on. The repo's
  SPY figures — median **1.32**, mean 1.55 — are the equity comparison.
- The **always-on delta-hedged P&L** of a rolled ATM straddle, using G3's
  hedging rule and G4's ledger, at option spread floors of **1× / 2× / 3×** and
  with `option_spread_model.py`'s VIX-keyed curve for the stress periods (a flat
  $0.02 through March 2020 is fiction).
- The same, decomposed: gamma, theta, vega, hedge, cost, unexplained.

**Report by era and separately on the 2023–2026 holdout. Expect it to lose.**
The verified benchmark is Carr & Wu (2009, RFS 22(3), read from the primary
PDF): an average **log variance risk premium of −66%** on 30-day S&P 500
variance swaps over 1996–2003, with an annualised Sharpe of **0.98 on the short
side**. If our long-gamma number comes out positive, the first hypothesis is a
bug in the surface or in the benchmark estimator, not an edge.

**One caveat from that same paper worth carrying:** only **7 of 35 single names**
showed a significantly negative premium in levels, against all three major
indices. The premium is far more an index phenomenon than a single-name one, and
HYG is a *basket* — so it plausibly sits closer to the index case than to the
single-name case, but that is a hypothesis this part tests rather than assumes.

**Then the credit-specific question, where the literature is unusually precise.**
Wang, Zhou & Zhou (Federal Reserve FEDS 2011-02, read from the primary PDF,
382 firms, Jan 2001 – Sep 2008) — **all three figures confirmed exactly against
the paper**:

- firm-level VRP alone explains **34%** of the cross-sectional variation in
  5-year CDS spreads (adjusted R²); **49%** with leverage, market VRP and firm
  controls added;
- mean VRP rises monotonically with credit risk, **from 7 at AAA to 82 at CCC**
  (monthly, percent-squared);
- the estimated cross-sectional price of market VRP risk is **λ = 1.17 against
  an observed market VRP of 1.20**.

Kita & Tortorice (2021, *J. Corporate Finance* 69) confirm, verbatim in the
abstract, that *"this smirk is more pronounced in the credit market than in the
equity market"* — magnitudes paywalled.

**So the prior is that credit's VRP is real and probably larger than equity's,
not smaller.** Test whether our measured credit `rich_ratio` is consistent with
that, and say so either way. **This is the cleanest citation in the programme —
use it rather than the ETF-level figures, which are weaker and in one case
unverifiable.**

---

## Part B — Three conditioners, one run, and a prior that is not neutral

Each produces a state `S_t ∈ {0,1}` at the close of *t*. The sleeve (G7) would
be long an ATM straddle, delta-hedged per G3, while `S_t = 1` and flat
otherwise. **Declare all three here and do not amend them after seeing
results.**

**C1 — the VRP's own level. This is the baseline, and the evidence says it
should win.** `S^C1_t = 1` when the standardised trailing implied-minus-realised
spread is in its cheap tail — implied unusually low relative to recent realised.
Standardise on a trailing 504-session window ending *t−1*; threshold at −1.0
standard deviations, **chosen before running**, with −0.5 and −1.5 reported as
sensitivity and not selected on.

This is the only candidate whose published predictive object *is* the quantity
we care about (Bollerslev, Tauchen & Zhou 2009, RFS; Carr & Wu 2009, RFS;
Bekaert & Hoerova 2014). **Anything else must beat it, not merely beat
always-on.**

**C2 — the variance term-structure slope.** `S^C2_t = 1` when the 1-month/3-month
ATM implied ratio exceeds 1.0 (inverted — stress priced at the front). Moderate
evidence (Simon & Campasano 2014), crowded, and with a short useful horizon:
backwardation tends to be *coincident* with elevated realised vol rather than
leading it by weeks, so by the time it is visible much of the move has happened.
Included as a known-effect control.

**C3 — the CEF stress nowcast. This is the only one that is ours.** The claim:
retail liquidation shows up in CEF discounts *before* it shows up in realised
ETF volatility, because the CEF holder sells the wrapper at whatever price while
the ETF's creation/redemption arbitrage keeps its price near NAV until flows are
large. Build from the 17 at *t*:

- `D_t` = cross-sectional standard deviation of the day's discount **changes**
- `V_t` = mean over names of `(z_t − z_{t−3})`, the 3-session z-velocity, signed
  so that widening is positive
- `W_t` = fraction of names whose discount widened by more than one
  trailing-63-day standard deviation today

Standardise each on a trailing 252-session window ending *t−1* and average:
`Stress_t = ⅓(D̃ + Ṽ + W̃)`. `S^C3_t = 1` if `Stress_t > 1.5` — chosen before
running; report 1.0 and 2.0 as sensitivity, do not select on them.

**Test C3 as a regression first, before it ever sizes a position.** Does
`Stress_t` predict `RV_cc(HYG)_{t+1..t+5} − IV_t` with a positive coefficient,
out of sample, by era? And — the bar that matters — **does it predict it better
than C1 does?** If it does not beat the VRP level, C3 is dead and the sleeve has
nothing of ours in it. Report the incremental R² of `Stress_t` over C1, with
Newey-West standard errors.

**What is deliberately not here, and why.** An earlier draft proposed a
**scheduled-event conditioner** — long gamma into FOMC, CPI, payrolls. **The
evidence does not merely fail to support it; it points the other way, hard.**
Goyal & Saretto (2009, *JFE* 94(2), read from the published PDF, 1996–2006)
sort on the implied-minus-realised volatility spread and find the most
"overpriced-implied" decile's straddles return **−12.8% per month**, the
opposite decile **+9.9%**, and the 10−1 long-short straddle **+22.7% per month
with a monthly Sharpe of 0.903** — against the market's 0.131 over the same
sample. The documented edge is in **selling** into an implied run-up.
Ederington & Lee (1996, JFQA) separately show implied vol rises into scheduled
releases and falls after, consistent with correct anticipation rather than
mispricing. **"Buy gamma into a known catalyst" is folklore, and it is not
pre-registered here.** If someone
wants it tested later, it is a separate trial with that literature quoted in its
pre-registration.

Also excluded, with reasons, so they are not rediscovered: dealer gamma
positioning (real mechanism, but public estimates are noisy third-party proxies
for unobserved books, and the peer-reviewed support is thin), realised-vol level
or momentum alone (forecasts RV well, but implied re-prices with it so the
*spread* does not widen), and CFTC positioning (descriptive only).

---

## Part C — The structural counter-argument, stated in the note

Bollerslev & Todorov (2011, JF) find the variance risk premium is largely
compensation for **jump and tail risk specifically**, not for ordinary diffusive
variance risk. If that is right, then a signal that reliably identified windows
where realised will exceed implied is economically identical to a signal that
reliably identifies impending crashes — which, if robust and cheap to compute,
would be arbitraged into option prices and would collapse the premium it was
built to time.

**The premium survives because the timing is hard.** Write that paragraph into
the results note, in your own words, before reporting any positive result. It is
the correct prior, and a finding that clears the decision rule below despite it
is a more interesting finding for having been held to it.

---

## Part D — The tests

For each conditioner and for the always-on control, on HYG (primary) and TLT
(reported), 2014-06 → 2026-07, using G3's hedging rule and close-to-close
benchmark, at 1×/2×/3× spread:

| | ann. return | vol | Sharpe | Calmar | time in market | trades/yr | carry while on (%/yr) | P&L in the CEF book's 10 worst windows |
|---|---|---|---|---|---|---|---|---|

Plus, per conditioner:

- **Fit and holdout rows separately.** The thresholds and windows are fixed in
  advance, so the 2023–2026 holdout tests the *rule*, not a fit.
- **The regression test for C3** (Part B) with its incremental R² over C1.
- **A negative control:** each conditioner driven by a shuffled state series
  with the same on-fraction, 20 draws. If shuffled states earn comparably, the
  gain is time-in-market rather than timing.
- **Time-in-market matters.** A conditioner that is on 80% of the time is
  approximately always-on and its Sharpe should be read that way; report
  Sharpe-per-unit-time-on alongside.

## The pre-registration this prompt produces

`results/gamma/PREREG_GAMMA_TIMING_<date>.md`, committed **before** G7 runs:
the conditioner, the threshold, the underlying, the benchmark estimator, the
decision rule, and the falsifier. **At most one conditioner is carried
forward**, and the rule for choosing is:

- Its Sharpe is positive at 2× spread on the **full sample and the holdout**.
- It beats the always-on control on Calmar and on Sharpe-per-unit-time-on.
- The shuffled control shows no comparable gain.
- **C3 must beat C1 by ≥ 0.10 Sharpe to be chosen over it** — the prior favours
  the published effect unless ours is clearly better.
- If nothing clears, **record it and stop.** "No timing signal we can compute
  survives its own controls" is a complete and useful answer, and it returns the
  question to `W14`, where long gamma is priced as insurance rather than as an
  engine.

## Deliverables

- `scripts/gamma/vrp_credit.py` (Part A) and `scripts/gamma/conditioners.py`
  (Part B, all three, plus the regression test and the shuffled control).
- `results/gamma/VRP_CREDIT_<date>.md` — the base rate, by era and holdout, with
  the credit-versus-equity comparison and the literature's expectation quoted.
- `results/gamma/GAMMA_TIMING_<date>.md` — the conditioner table, the C3
  regression, the controls, and Part C's paragraph.
- `PREREG_GAMMA_TIMING_<date>.md` if anything clears.

## Do not

- Do not use any realised-vol estimator but close-to-close in the capture ratio
  or the conditioner definitions (G3 Part C).
- Do not add a fourth conditioner after seeing results, and do not combine them
  into a score. Three states, one run.
- Do not pre-register an event-calendar conditioner; the evidence points the
  other way and the reason is in Part B.
- Do not select a threshold on results. The sensitivities are reported, not
  chosen from.
- Do not report a conditioner's Sharpe without its time-in-market.
- Do not conclude from a positive result without addressing Part C.
