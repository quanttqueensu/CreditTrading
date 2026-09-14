# PRE-REGISTRATION — timed long gamma in credit

**Written 2026-09-13, before any G7 work.** This is `G6`'s named deliverable.
**Trials spent here: 0.** Counters at the time of writing: **CEF 48, GAMMA 0**
(`docs/RESEARCH_STATE.md` canonical table; re-read it rather than this line).

It records what was declared, what was measured, what could not be measured,
and the decision rule's answer. It is written the way a pre-registration is
written even though the answer is negative, because a negative answer that is
not recorded gets re-derived by the next person with the next dataset.

---

## 1. The specification, as declared before any result

| | C1 — VRP level | C2 — term structure | C3 — CEF stress nowcast |
|---|---|---|---|
| **state** | standardised trailing implied−realised spread in its cheap tail | 1m/3m ATM implied ratio inverted | `⅓(D̃+Ṽ+W̃)` over the 17 CEFs |
| **threshold** | **−1.0 sd** | **> 1.0** | **> 1.5** |
| **window** | trailing 504 sessions ending *t−1* | n/a | trailing 252 sessions ending *t−1* |
| **sensitivity reported, not selected on** | −0.5, −1.5 | — | 1.0, 2.0 |
| **status** | run | **DECLARED, NOT RUN** | run |

**Underlying:** HYG (primary), TLT reported. **Position while `S_t = 1`:** long a
rolled ATM straddle, delta-hedged once daily at the close. **Flat otherwise.**

**Benchmark estimator: close-to-close realised variance, and nothing else.**
A once-daily close-to-close hedger earns close-to-close realised variance.
Parkinson, Garman-Klass and Rogers-Satchell all discard the overnight gap, and
`docs/REFERENCES.md` §9 measures that gap at **59.6% of HYG's close-to-close
variance since 2019** — so the intraday estimators would understate the
denominator of every ratio in this programme by roughly that much, in the
direction that makes long gamma look cheap. This is `G3` Part C's rule and it is
not optional.

**C2 is recorded as unavailable, not as unpromising.** It needs a term structure,
which needs per-strike historical option prints. IBKR serves none (verified nine
ways, 2026-09-12) and no free source has been found. The distinction matters: a
later data source reopens C2 without reopening anything else here.

---

## 2. The structural counter-argument, stated before the results

Required by `G6` Part C, and written here in full because it is the correct
prior rather than a caveat.

Bollerslev & Todorov (2011) decompose the variance risk premium and find that
roughly **three-quarters of it is compensation for jump and tail risk, not for
ordinary diffusive variance** — the left-tail component alone is 88.4% of the
average premium. If that is what the premium is, then a signal that reliably
picks the windows where realised will exceed implied is not a volatility signal
at all. It is a **crash-timing signal wearing a volatility signal's clothes**.
And a cheap, robust, computable crash-timing signal does not survive contact
with an options market: it gets traded, the premium it identified gets priced
in, and the thing that made it profitable disappears.

So the premium persists **because the timing is hard**, and the hardness is the
mechanism, not an obstacle in front of it. Any result that clears the decision
rule below has to be read against that — which is why the rule asks for a
holdout and a shuffled control rather than a significance level.

---

## 3. What was measured

Both notes were produced today by named scripts and carry their own provenance.

**Part A — the base rate** (`scripts/gamma/credit_base_rate.py`,
`results/gamma/CREDIT_BASE_RATE_2026-09-13.md`), VXHYG against HYG
close-to-close, 2015-04-22 → 2026-07-30 (HYG's panel ends 43 days before
VXHYG's; `ops/doctor.py` flags it):

| | median implied | median forward realised | **variance ratio** |
|---|---:|---:|---:|
| **HYG** (credit) | 7.78% | 4.68% | **2.77×** |
| SPY (equity) | 14.02% | 12.40% | **1.28×** |

**Credit gamma costs more than twice what equity gamma costs.** Implied was
below subsequent realised — the state long gamma wants — on **9.1%** of days
over the full sample, **10.0%** in 2015–19, **11.5%** in 2020–22, and **1.8%**
in 2023–26.

This confirms a prior `G6` Part A stated in advance from Wang, Zhou & Zhou
(FEDS 2011-02): mean VRP rising monotonically from 7 at AAA to 82 at CCC. HYG is
a high-yield basket, so a large premium is what that literature predicts. The
prior was stated before the fetch and the measurement agrees with it.

**Part B — the conditioners** (`scripts/gamma/conditioners.py`,
`results/gamma/CONDITIONERS_2026-09-13.md`), target
`RV_cc(HYG)_{t+1..t+5} − IV_t`, OLS with Newey-West lag 5:

| model | n | β C1 | t | β C3 | t | R² |
|---|---:|---:|---:|---:|---:|---:|
| C1 alone | 1,374 | −0.0092 | −2.11 | — | | 0.0581 |
| C3 alone | 1,878 | — | | +0.0051 | +1.58 | 0.0115 |
| C1 + C3 | 1,374 | −0.0110 | −2.78 | +0.0097 | +2.42 | 0.0939 |

C3's incremental R² over C1 is **+0.0358**, and it survives the control that
matters: the stated target contains `IV_t` and so does C1 (corr +0.272), so part
of any fit is arithmetic. Against **forward realised vol alone, with no IV term
anywhere**, C3 gives β **+0.02105**, t **+3.95**, n = 4,851. CEF stress does
carry information about HYG's next week.

**And on the 2023–2026 holdout it does not.** The coefficient falls to **24%**
of its full-sample value (+0.02085 → +0.00490), t drops to **+1.69**, and on the
stated target it is **−0.20**.

---

## 4. What could NOT be measured, and why that is not a gap in the conclusion

`G6` Part D asks for the economic battery — annualised return, vol, Sharpe,
Calmar, time in market, trades/yr, carry while on, and P&L in the CEF book's ten
worst windows — for each conditioner at option spread floors of 1×/2×/3×.

**None of it is computable**, because a delta-hedged straddle P&L needs
per-strike option prices and there are none for HYG at any date. `P3` (G2's
surface) is blocked on exactly this and `python3 -m ops.gamma_status` prints the
blocker every run.

So the first clause of the decision rule below — *"Sharpe is positive at 2×
spread on the full sample and the holdout"* — is **UNMEASURABLE, not failed**.
That distinction is kept deliberately. It does not rescue anything, because:

1. the regression bar is a **prerequisite** to the economic bar, not an
   alternative to it — `G6` Part B says *"test C3 as a regression first, before
   it ever sizes a position"*, and C3 fails that test out of sample; and
2. the states-as-traded table answers the economic question in the one direction
   that does not need option prices. **Mean target while ON, every threshold
   reported.** Units are annualised vol as a **decimal**, so −0.0233 is 2.33
   percentage points of vol; the generating script spells this out because
   reading it as percentage points is a factor-of-100 error in the direction
   that makes the premium look negligible.

| conditioner | threshold | days on | % of sample | mean target when ON (decimal vol) |
|---|---:|---:|---:|---:|
| C1 **(declared)** | −1.0 | 129 | 6.9% | **−0.0342** |
| C1 | −0.5 | 304 | 16.2% | −0.0280 |
| C1 | −1.5 | 61 | 3.2% | −0.0444 |
| C3 **(declared)** | 1.5 | 99 | 5.3% | **−0.0233** |
| C3 | 1.0 | 160 | 8.5% | −0.0290 |
| C3 | 2.0 | 62 | 3.3% | −0.0113 |

**Every cell is negative.** There is no state, under either conditioner, at any
threshold reported, in which credit gamma was cheap on average. The best cell in
the table — C3 at 2.0, 62 days over eleven years — still paid **1.13 vol points
annualised** of premium, *before* any spread, commission or hedge cost. Option
prices would only make those numbers worse, never better, so their absence
cannot flip the sign.

---

## 5. The decision rule, and its answer

`G6`'s rule, verbatim, with what each clause returned:

| clause | result |
|---|---|
| Sharpe positive at 2× spread, **full sample and holdout** | **UNMEASURABLE** — no per-strike HYG option prices exist (§4) |
| Beats the always-on control on Calmar and Sharpe-per-unit-time-on | **UNMEASURABLE**, same cause |
| Shuffled control shows no comparable gain | **PASS for C3** — real mean target when on sits at the 100th percentile of 20 shuffled draws (C1: 80th) |
| **C3 must beat C1** (Part B, the prerequisite) | **PASS in sample, FAIL on the holdout** |

### VERDICT: NO CONDITIONER IS CARRIED FORWARD

- **C1** is the literature baseline. It is never a candidate in its own right
  here, and in any case its mean target while on is −0.0342 — the baseline never
  reaches a state where long gamma is cheap.
- **C2** is declared and unavailable.
- **C3** clears the full-sample half of the bar and survives the no-IV-term
  control, and **fails the 2023–2026 holdout**. `G6` requires both.

**Therefore `G7` does not run and the GAMMA trial is not spent.** This is the
outcome `G0` predicted in advance — *"expect no conditioner to beat C1"* — and
recording it is the deliverable, not a failure to produce one.

**This is the `z_window = 63` shape**, which the standing brief calls the most
instructive event in this project's history: a clean in-sample coefficient, a
plausible and pre-stated mechanism, and a holdout that says no. There is an
honest explanation available — 2023–26 is 298 observations of an unusually calm
credit tape in which only **1.8%** of days had implied below realised at all, so
there was very little for a long-gamma timer to find — but an explanation is not
a result, and the rule does not bend for one.

---

## 6. The falsifiers

Stated so that a later re-run tests the rule rather than re-fitting it. **Each is
a re-measurement by a named script, never a comparison against a number written
in this document** (H14).

1. **C3 on an extended holdout.** Re-run `scripts/gamma/conditioners.py` when the
   post-2023 window has materially more data than the 298 observations it has
   today. C3 is revived only if its holdout coefficient reaches **≥ 60% of its
   full-sample value with t ≥ 2.0 against forward realised vol**, on the
   thresholds and windows declared in §1 and unchanged. Any change to a
   threshold or a window makes it a new trial, not this one.
2. **C2 becomes measurable.** If a source of per-strike historical HYG option
   prints is found, `P3` unblocks, C2 runs on its declared threshold, and the
   Part D battery in §4 becomes computable for all three. That is a re-run of
   this pre-registration, not a new one.
3. **The base rate changes.** Re-run `scripts/gamma/credit_base_rate.py`. If the
   fraction of days on which implied sits below subsequent realised rises over a
   trailing year to something far above the 9.1% full-sample rate, the premium
   this verdict rests on has moved and the whole question reopens.
4. **The hedging spec.** `results/gamma/HEDGING_SPEC_<date>.md` (`G3`) is still
   unwritten — `python3 -m ops.gamma_status` shows P2 TODO. The close-to-close
   rule it defines **was applied** in both scripts above, so the numbers here are
   on the correct benchmark; what is missing is the note, not the convention. Any
   revival of this work writes that note first.

---

## 7. What this does NOT say

It does not say options are useless to this desk, and it does not say the credit
VRP is not real. It says the opposite of the second: the premium is **large** —
2.77× in variance against equity's 1.28× — and the measurement is the most solid
number the programme produced.

**A large premium is an argument against paying it, which is what a long-gamma
sleeve does every day it is on.** The side of that trade with published support
is the other one: Carr & Wu (2009) put the annualised Sharpe of *shorting* S&P
variance at **0.98**, and Goyal & Saretto (2009) find the edge in selling into an
implied run-up. That is a **different strategy with a different risk shape**
— short convexity, and the tail that Bollerslev & Todorov say the premium is
paying for in the first place — and it is explicitly **not** pre-registered here.
It would need its own prompt, its own pre-registration, its own trial, and a
margin budget the account does not currently have: `ops.gamma_status` measures
the slack above preflight's blocking cushion floor at **64,055 CAD, down 49%**
from three days earlier, and that floor is account-wide, so a fourth book
tripping it stops the $500k CEF book.

`W14` Part A separately measured that the CEF book is **not** short volatility in
any sense that gives a hedging option a job: β to ΔVIX is **−0.000092** (t −0.69,
≈ −$46 per VIX point), **0 of 10** worst windows start in the top VIX quintile,
and the drawdowns are single-name premium-regime events. So neither of the two
jobs an option could do here — hedge the book, or time the premium — is supported
by our own data.

---

**Committed before `G7`. `G7` does not run. GAMMA counter stays at 0.**
