# G7 — The timed sleeve, and the budget that may be zero

**Reads first:** `G0_BRIEF.md`, `G6_vrp_research.md` and its pre-registration,
`G3_hedging.md`, `00_BRIEF.md` §5.
**Settles:** whether the gamma programme trades at all, and at what size.
**Trials:** **1 on the GAMMA counter.** The first, and it should be the only one
for some time.
**Touches the live book:** as a sleeve with its own sub-ledger, after
pre-registration, sized by a derived rule that may return zero.
**Prerequisites:** G6's pre-registration exists and names a surviving
conditioner; G1–G5 landed; **W10 Part C** (the Σ⁻¹·IR budget rule this
generalises); **W12 Part B** (a structured covariance).

---

## Paste from here

You are a quant researcher on the QUANTT book. Read
`results/gamma/PREREG_GAMMA_TIMING_<date>.md` first. **If G6 found no
conditioner that cleared its decision rule, this prompt does not run** — the
answer is that long gamma is insurance, the question returns to
`W14_options.md`, and the GAMMA counter stays at zero. Do not look for a fourth
conditioner.

---

## Part A — The construction

The sleeve is long an ATM straddle on the pre-registered underlier (HYG
primary), delta-hedged at the close per G3's specification, **while the
pre-registered conditioner's state is 1, and flat otherwise.** Entry and exit
are MOC in shares and limit-at-mid in options at the next session; **state the
shift convention explicitly and reconcile it with the CEF book's shift-2
convention**, since the combined book's P&L series must be aligned before any
correlation between them means anything.

Reuse G6's engine. Do not write a second backtester, and do not re-tune the
threshold — it is fixed by the pre-registration.

---

## Part B — The budget, derived

Size against the CEF book by the same rule W10 Part C uses for two sleeves.
With `IR_g` the gamma sleeve's net Sharpe (net of the modelled option spread at
2×, and of hedge costs), `IR_c` the CEF book's net-of-borrow Sharpe, and ρ their
**daily** correlation on aligned dates:

    (v_g, v_c) ∝ (1/(1−ρ²)) · (IR_g − ρ·IR_c,  IR_c − ρ·IR_g)

scaled so the combined book hits the live volatility target.

**If `IR_g − ρ·IR_c ≤ 0`, the derived budget is zero and the sleeve is not an
engine.** Record it, hand the question back to `W14` where the same machinery is
priced as insurance, and stop. **This is the expected outcome and the prompt is
not a failure if it happens** — a long-gamma book's unconditional expectation is
negative, so a positive derived budget requires the conditioner to have done real
work, which is exactly the thing G6 was built to doubt.

Three constraints, all stated in advance:

- **A floor.** If the derived budget is below 5% of combined book volatility,
  set it to zero. Below that the tickets, the ledger rows and the operational
  attention are not worth it.
- **ρ is measured, not assumed**, on the overlapping sample, with a
  block-bootstrap standard error. **Report ρ's confidence interval**, because
  the budget formula divides by `(1−ρ²)` and is therefore most unstable exactly
  where ρ is least well estimated. If the interval spans values that flip the
  sign of `IR_g − ρ·IR_c`, the budget is not identified and the answer is zero.
- **Σ from W12's structured estimator**, never a sample covariance — the same
  reason F3 gives, and with two sleeves the argument is weaker but the habit is
  worth keeping.

Report a ±50% sensitivity on `v_g` for the reader. The decision stays at the
derived point.

---

## Part C — The decision rule, fixed before running

Adopt the sleeve only if **all** of:

1. Its Sharpe is positive at 2× spread on the **full sample and on the
   2023–2026 holdout** — the thresholds and windows are fixed, so the holdout
   tests the rule rather than a fit.
2. The derived budget is ≥ 5% of combined book volatility.
3. **The combined book's Calmar is not lower than the CEF book's alone.**
   Absolute return is the objective, but not bought with a worse tail.
4. The combined book's annualised net return is not lower than the CEF book's.
5. G6's shuffled-state control showed no comparable gain.

If it clears, **the sleeve is named for what it actually is.** If the surviving
conditioner is C3, it is a *CEF-stress-timed gamma sleeve* and its falsifier is
the stress nowcast's continued predictive power. If it is C1, it is a
*VRP-level-timed sleeve* and it is a known effect implemented carefully, which
should be said plainly rather than dressed up.

---

## Part D — Deployment, if adopted

- Sleeve `gamma_timed` in the book spec with its own sub-ledger. Spec keys
  `gamma.conditioner`, `gamma.threshold`, `gamma.underlying`,
  `gamma.vol_budget`, `gamma.no_short_options: true`; **absent = no sleeve**,
  with the no-op proved byte-for-byte against the CEF sleeve's output.
- Option legs limit-at-mid ± one tick from our own surface (G1 on G2), never
  from IBKR's model. Hedge legs MOC/LOC in shares per G3.
- **The hedge instrument must not be held by another book.** `bench_b1` holds
  HYG. Resolve the attribution before the first order and state how, exactly as
  G5 requires.
- **The CEF kill rule is evaluated on the CEF sleeve alone**, so the gamma
  sleeve can never mask a failing strategy — and the gamma sleeve gets its own
  kill rule: any short option, notional above cap, ledger desync, or the
  conditioner's regression losing significance over a rolling 250 sessions.
- Reported on the dashboard as its own sleeve **and** in the combined book, with
  its own P&L line and its own Lo standard error.

## Part E — The readout, which is not P&L

Pre-register these as the 40-session readouts, and put them on the dashboard:

- **Realised-minus-implied captured per on-day**, in close-to-close terms — the
  thing the sleeve claims to harvest.
- **Hedge cost in bp of hedge notional**, which feeds W7's cost programme.
- **Decomposition accuracy** — `unexplained` as a share of gross gamma P&L,
  target under 10%, carried over from G5.
- **Time-in-market against the pre-registered expectation.** A conditioner that
  fires far more or far less often than the backtest said is a regime change or
  an implementation bug, and either way it is the earliest available warning.

P&L is reported with its standard error and without a verdict until the session
count clears W1's MinTRL calculation, which for a book like this will be years.

## Deliverables

- `scripts/gamma/timed_sleeve.py` (the construction, the budget derivation, the
  sensitivity), `src/deploy/sleeves/gamma_timed.py`, the spec keys with the
  no-op proof.
- `results/gamma/TIMED_GAMMA_<date>.md`: the conditioner's performance, the
  budget arithmetic including ρ's interval, the combined-book table, and the
  decision against the rule stated item by item.
- The GAMMA counter line in `docs/RESEARCH_STATE.md`.

## Do not

- Do not run if G6 found nothing. Do not go looking for a fourth conditioner.
- Do not re-tune the threshold, the tenor, the roll or the hedge rule; all are
  fixed upstream.
- Do not size by hand. The budget is Σ⁻¹·IR or it is zero.
- Do not let the sleeve be short options under any conditioner.
- Do not report the combined book without also reporting the CEF book alone.
- Do not treat a zero budget as a failed prompt. It is the expected answer and
  it is worth one trial to establish.
