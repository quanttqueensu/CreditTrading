# F3 — Seventeen sleeves, one book: per-fund budgets and what neutrality means

**Reads first:** `00_BRIEF.md` §1 (BR and the law), §4 (the scoreboard), §5, §7.
**Lever:** BR and attribution. Seventeen funds become seventeen bets with
seventeen P&L lines, each of which can be judged, sized or switched off alone.
**Trials:** **1 on the CEF counter for the whole construction**, run as one
pre-declared grid of four neutrality rules — not one trial per rule and not one
per fund.
**Touches the live book:** yes, after pre-registration. This is the largest
single change to the construction the repo has attempted.
**Prerequisites, all of them, no exceptions:** W1 (holdout), **W4 (the artifact
battery — a per-fund architecture built on an artifact IC is seventeen times
the wasted effort)**, F1, F2 (the per-fund signals this consumes), W8 (the
availability cap, which binds much harder here than it does today), W11 (the
per-fund band), W12 Part B (a structured covariance — a raw sample Σ on 17
correlated sleeves is not invertible in any useful sense).
**New 2026-09-09. Standing decision: 17 sleeves, one combined book.**

---

## Paste from here

You are a quant researcher and developer on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md`, then `results/cef/ARTIFACT_BATTERY_<date>.md`,
`results/cef/GROUP_FORMS_<date>.md` (F2), and
`results/cef/ALPHA_DECOMPOSITION_<date>.md` (W10 Part B). Then:

1. `src/deploy/sleeves/cef_discount.py` in full — the current construction, and
   in particular lines 190–192, which are the thing this prompt replaces:
   ```python
   s = pd.Series(row)
   w = -(s - s.mean())        # cheap -> long, rich -> short
   w = w / w.abs().sum()
   ```
2. `src/deploy/portfolio.py` and `src/deploy/registry.py` — how multiple sleeves
   are declared, budgeted and combined today, and how `_attribution.json` keeps
   two books' positions in the same ticker apart.
3. `docs/PLAN.md` §4.2 — **hard group neutrality was tested and lost gross
   Sharpe 0.97 → 0.82**, and `docs/RESEARCH_STATE.md` line 365 on why: *"With
   only 18 funds across 5 groups, several groups hold 2-3 members, so
   within-group demeaning throws away most of the cross-section. The cross-group
   differences apparently carry signal, not just NAV noise."*

---

## What actually changes, and the risk it creates

Today the book is **cross-sectional**: one mean is subtracted across the
eligible names, which makes the book dollar-neutral *by construction* and, as a
side effect, turns any common move into a group bet nobody sized. Under this
prompt each fund carries its **own** conditional dislocation z_i from F2 —
a time-series signal against its own conditional fair value, not a relative
ranking.

**That is the whole point, and it is also the danger.** A cross-sectional
construction nets out the common sentiment factor for free. Seventeen
time-series sleeves do not: when credit sells off, every fund's discount widens
together (our own pairwise correlation of daily discount changes runs 0.42–0.66
across groups), every sleeve independently says "cheap", and the book goes
maximally long into the drawdown with no offsetting short. **Neutrality stops
being a by-product and becomes a design decision.** That decision is Part B and
it is the reason this prompt exists as its own trial.

Two further consequences to hold in mind throughout:

- **Borrow and availability bind much harder.** Seventeen independent sleeves
  can all want to be short the same group at once, with no long leg forced to
  offset them. W8's availability cap moves from a refinement to a hard
  constraint, and it must be applied at book level *after* aggregation, not
  inside each sleeve.
- **Breadth becomes measurable rather than emergent.** With 17 named sleeves
  and a covariance matrix you can compute each sleeve's marginal contribution
  to risk and its marginal contribution to return directly. Report BR_eff the
  same way the dashboard does, but now also report it *per sleeve*.

---

## Part A — The sleeve

One sleeve per fund. `sleeve_i` trades exactly one instrument, `ticker_i` — so
attribution is exact by construction and `_attribution.json` never has to split
a shared position between two sleeves.

Each sleeve owns, and exposes:

| field | source | note |
|---|---|---|
| `z_i` | F2's conditional dislocation | its own fair value, its own sd |
| `w_i^raw` | `−z_i · v_i / σ_i` | signed target weight before book constraints |
| `v_i` | Part C's derived budget | vol budget in book-vol units |
| `b_i` | W11's per-fund band | its own no-trade width |
| `h*_i` | F2 Part C | its derived holding period |
| `f_i` | W8's borrow panel | its fee and pool |
| `state` | live / shrunk / disabled | see the kill rule below |
| P&L line | ledger | gross, net, borrow, carry, turnover, hold |

**The sizing form is derived, not chosen.** In return units the Grinold weight
for a diagonal risk model is `w_i ∝ α_i/σ_i² = IC·σ_i·s_i/σ_i² = IC·s_i/σ_i`,
so a sleeve's dollar weight scales inversely with its price volatility and its
risk weight is `v_i`. This is the same relation W11 Part B tests as group vol
scaling; here it is per sleeve by construction. **Use group-level σ_P (the
resolution table says σ_P is a GROUP parameter, R² = 0.51) unless F2 Part A's
redone table says otherwise.**

**Per-sleeve kill rule**, evaluated on broker-confirmed data only: a sleeve
whose realised cost exceeds its own breakeven for 20 consecutive armed
sessions, or whose fund is subject to a live 13D / pending tender /
rights offering / announced merger (F1's event feed), goes to `disabled` and
winds down to flat. **A disabled sleeve does not reallocate its budget to the
others automatically** — the book simply gets smaller, and a human decides.
Silent reallocation is how a concentrated book appears without anyone choosing
it.

---

## Part B — What neutrality means: four rules, one pre-declared grid

This is the open question and it is settled by measurement, not by preference.
Declare all four before running, run all four, report all four.

**N0 — Cross-sectional demean (the control).** Today's construction: subtract
the mean of `z` across eligible names, normalise to unit gross. Dollar-neutral
by construction. This is the baseline every other rule must beat, and it is
what the entire existing backtest measures.

**N1 — Aggregate, then hard dollar-neutralise.** Sum the seventeen `w_i^raw`,
subtract the weighted mean so `Σw = 0`, renormalise to unit gross. Neutrality is
imposed on the *weights* rather than on the *signal*, which is a different
object: N0 removes the common component before sizing, N1 after. Report how
often the two differ materially and in which direction.

**N2 — Budgeted net exposure.** Allow `Σw ≠ 0` up to a limit derived from
W10 Part B's decomposition: the between-group bet gets the budget
`v_b ∝ Σ⁻¹·IR` that W10 Part C derives, and the residual net dollar exposure is
capped at the level implied by that budget. **If W10 Part C found the between
bet deserves zero budget, N2 collapses to N1 and that is a finding, not a
failure.**

**N3 — Factor-neutral, dollar-free.** The book carries whatever net dollar
exposure the seventeen sleeves imply, and a hedge overlay in listed ETFs
neutralises the *factor* exposure instead: HYG/JNK against the high-yield and
multi-sector sleeves, BKLN against the loan sleeve, **MUB against the muni
sleeves**, TLT for residual duration. Hedge ratios estimated per sleeve on
trailing NAV returns against the proxy, refit monthly, shrunk toward the group
ratio.

This is the economically coherent version — dollar-neutrality is a crude proxy
for factor-neutrality and always has been — but **be honest in the note about
its one severe weakness: the muni hedge barely exists.** Six of seventeen funds
are municipal, and the position is worse than "thin". Measured 2026-09-09,
**MUB's options traded 168 contracts on the day — 165 puts and 3 calls — with
essentially all standing open interest in a single legacy $105 put line.** They
are not a hedging instrument. The ETF itself is shortable and that is the only
listed muni exposure available.

So a muni factor hedge is: short MUB, or a synthetic muni/Treasury view as long
MUB against short Treasury duration — a basis trade with its own tracking error,
which does not replicate the leveraged Nuveen funds' interest-rate-reset risk,
and which for the two **BlackRock** muni names (MQY, MHD) does not replicate
their preferred-share financing either. There is no tax-exempt derivative and no
muni CDS. **Measure the tracking error of a short-MUB hedge against each muni
sleeve's NAV return and report it before N3 is scored; if it is large, N3 is not
really factor-neutral for a third of the book and the grid should say so.**

**Also note what N3 costs that the others do not:** it adds ETF positions to a
book that currently holds only CEFs, which means borrow on the short hedge
legs (HYG/LQD/MUB should be general collateral — verify against W8's panel
rather than assuming), execution in a second instrument set, and a potential
attribution collision if another book holds the same ETF. Resolve that before
the first order, not after.

### The comparison

All four rules, harness, turnover-matched to 17.6×/yr, full sample, by era, fit
and holdout:

| rule | gross | turn/yr | hold | net@5 | net@15 | net@30 | borrow %/yr | net@15 − borrow | **BR_eff** | PC2 share | mean \|Σw\| | p95 \|Σw\| | max 21d DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N0 cross-sectional (live) | 1.16 | 17.6 | | 0.99 | 0.66 | 0.17 | 1.22 | 0.43 | 2.24 | 65.7 | 0 | 0 | |
| N1 hard neutral | | | | | | | | | | | ~0 | ~0 | |
| N2 budgeted net | | | | | | | | | | | | | |
| N3 factor-neutral | | | | | | | | | | | | | |

Plus, for every rule: the **time series of net exposure**, the worst drawdown
and the date it occurred, and — the number that decides whether this whole
architecture is worth it — **BR_eff**. The claim being tested is that seventeen
deliberate bets have higher effective breadth than one accidental one. If
BR_eff does not rise, the per-fund architecture has bought complexity and
nothing else, and the honest answer is to keep N0 and use F2's conditional fair
value inside it.

**Decision rule, committed before running.** Adopt the per-fund architecture
only if the best rule improves net@15 − borrow over N0 by ≥ 0.05, raises BR_eff
by ≥ 1.0, does not worsen net@30, holds in at least four of five eras, and the
2023–2026 holdout agrees in sign. Among rules that clear that bar, **take the
one with the lowest p95 net exposure**, not the highest Sharpe — an
architecture whose neutrality depends on the sample is not neutral. If none
clears it, record it and keep N0: *"the cross-sectional construction was doing
work that seventeen independent sleeves do not replicate"* is a real finding and
it costs one trial to learn.

---

## Part C — The seventeen budgets

Each sleeve's budget `v_i` is derived once, from the same rule W10 Part C uses
for two sleeves, generalised: `v ∝ Σ⁻¹·IR` where `IR_i` is sleeve *i*'s
**net-of-borrow** information ratio from F2's fit period and Σ is the sleeve
return covariance.

**Σ must be the structured estimator from W12 Part B, not a sample covariance.**
Seventeen sleeves with pairwise correlations of 0.42–0.66 give a sample Σ whose
inverse loads the worst-estimated eigenvectors — this is the exact failure
`covariance_construction.py` documents, and at 17×17 with a 252-day window it is
worse, not better, than the cross-sectional case. Use the two-factor structured
Σ (market, muni-vs-taxable) plus idiosyncratic, or Ledoit-Wolf shrunk toward it.

**Constraints on the derived budget, all stated in advance:**

- `v_i ≥ 0` — a negative budget means the sleeve is a hedge, which is a
  different claim and is not what this construction is for. Clip at zero and
  **report every sleeve that clipped**; a sleeve that wants a negative budget is
  telling you its IR estimate is noise.
- `Σ v_i² ` scaled so the combined book hits the live vol target.
- A floor: any sleeve whose derived budget is below 3% of total book vol is set
  to zero and the fund is dropped from the live universe for that period, with
  the reason recorded. **Below that, the tickets are not worth the borrow, the
  ledger row or the attention.**
- **Do not sweep the budgets, and do not re-derive them on live P&L.** They come
  from the fit period and are applied to the holdout unchanged, exactly as W1
  requires of every derived quantity.

Report a sensitivity at ±50% on the three largest budgets, for the reader — the
decision stays at the derived point.

---

## Part D — Implementation

**Spec.** `construction: "cross_sectional" | "per_fund"`, absent =
`cross_sectional`, with

```json
"per_fund": {
  "neutrality": "N0|N1|N2|N3",
  "budgets": {"NAD": 0.0, "...": 0.0},
  "budget_source": "results/cef/sleeve_budgets.json@<sha256>",
  "sigma_mode": "structured_2f",
  "min_budget_share": 0.03
}
```

The no-op with the key absent must be **proved byte-for-byte** on the last five
complete pairs, exactly as every other spec change in this repo.

**Code.** Implement `per_fund` as a separate method in `cef_discount.py` that
`target_positions` dispatches to — the same pattern W12 uses for `joint_l1`.
**Agree one construction enum across W10 Part C (`two_sleeve`), W12
(`joint_l1`) and this prompt (`per_fund`) before any of the three lands**, or
three prompts will each add a different value to the same key.

**Ledger and attribution.** Seventeen P&L lines under one ledger. Because each
sleeve holds exactly one ticker there is no shared-position problem, but the
ledger must still carry `sleeve_id` on every order, fill and position row so the
lines can be reconstructed. Per sleeve, per session: gross, net, borrow, realised
turnover, holding period, and the sleeve's state.

**Order aggregation.** Seventeen sleeves each wanting a change in the same
ticker cannot happen (one ticker per sleeve), but the book-level neutrality step
and W8's availability cap both act *after* aggregation and can change a sleeve's
realised weight away from its target. **The band must then be applied to the
post-constraint target, not the pre-constraint one**, or every constrained
sleeve will trade every session trying to reach a target it is not allowed to
hold. Prove this with a test: constrain a sleeve, advance five sessions, assert
it does not churn.

**Dashboard.** W9's blotter gains a `sleeve` column and seventeen subtotal rows
replacing the four group subtotals — the group rows stay, computed as sums of
their sleeves. Screen 2 gains a per-sleeve P&L table. A disabled sleeve renders
greyed with its reason.

## Deliverables

- `scripts/cef/sleeve_budgets.py` (Part C, writing `sleeve_budgets.json` with a
  hash), `scripts/cef/neutrality_grid.py` (Part B's four rules, one table).
- The sleeve construction behind the spec key with its no-op proof; the
  `sleeve_id` ledger columns; the churn test.
- `results/cef/NEUTRALITY_GRID_<date>.md` and
  `results/cef/SLEEVE_BUDGETS_<date>.md`.
- `PREREG_PER_FUND_<date>.md` if adopted: the rule, the budgets, the source
  hash, and the readouts — **realised net exposure, realised BR_eff, and
  per-sleeve realised turnover over 40 armed sessions. Not P&L.** CEF counter +1.

## Do not

- Do not run this before W4. Seventeen sleeves built on an artifact IC is
  seventeen times the wasted effort.
- Do not let a disabled sleeve's budget be reallocated automatically.
- Do not use a sample covariance for the budget derivation.
- Do not apply W8's availability cap inside a sleeve; it is a book-level
  constraint and belongs after aggregation.
- Do not sweep the neutrality rule, the budgets, or the minimum-budget floor.
- Do not adopt on Sharpe alone. The tie-break is p95 net exposure, declared in
  advance, because an architecture whose neutrality depends on the sample is
  not neutral.
- Do not report a sleeve's P&L as evidence of its signal at fewer than the
  sessions W1's MinTRL calculation says are required. Seventeen underpowered
  Sharpe ratios are not seventeen findings.
