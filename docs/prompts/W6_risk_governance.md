# W6 — Risk governance: arm the controls, replace the kill rule, then size the book

**Reads first:** `00_BRIEF.md` §4 (the scoreboard), §7 (standing decisions).
**Lever:** governance, then return at unchanged Sharpe.
**Trials:** 0. Part A changes spec keys and code paths; Part B produces a
decision table a human acts on.
**Prerequisites:** Part A after W3 (broker-confirmed NAV needs the session to
run). **Part B is gated** and cannot be written until W7's cost estimate has
SE < 3bp, W8's availability work is deployed, and 20 armed sessions exist.
**Supersedes:** P0.5, P1.5.

---

## Paste from here

You are the risk analyst on the QUANTT CEF book. Read `docs/prompts/00_BRIEF.md`,
then:

1. `ops/specs/cef_discount.frozen.json` — the `risk` block (`kill_drawdown:
   0.18`, `halve_drawdown: 0.12`, `max_gross_exposure_usd: 1.3m`) and the
   `kill_rule` string.
2. `src/deploy/risk.py` — `evaluate_sleeve()` reads
   `sleeve.risk.get("max_drawdown_kill_pct")`. **That key does not exist in the
   spec.** Neither `kill_drawdown` nor `halve_drawdown` is read by any code
   path; grep to confirm.
3. `src/deploy/sleeves/cef_discount.py::risk_check` — returns `OK`
   unconditionally with a "WATCH" message at −12% and −18%.
4. `ops/books/cef_discount_book.json` — `book_drawdown_suspend_pct: 99.0` and
   the UNITS FIX note (it was 0.99, read as 0.99%, the tightest limit in the
   book, breached at −1.84% on 2026-08-31). Leave it alone; the fix is correct.
5. `docs/PLAN.md` §7.4, §3.1, §3.2; `docs/SYSTEM_AND_STRATEGY.md` §4 item 5, §5.
6. `src/deploy/lib/vol_target.py`, `lib/margin.py`, `lib/broker/margin_broker.py`.

---

## Part A — The controls (do this now)

### Why a P&L kill rule is the wrong instrument

Lo (2002): the standard error of an annualised Sharpe over *n* daily
observations is roughly √((1 + SR²/2)/n)·√252. Over 60 sessions that is about
2.05 for SR near 0.5. A rule "kill if SR < 0 at session 60" on a strategy with
true SR 0.45 fires with probability Φ(−0.45/2.05) ≈ 41%; the plan's 34% used
0.82. Either way the rule kills a working strategy more often than not by
chance, and it would never have caught the thing that actually threatens this
book, which is cost. Cost converges ~60× faster: at ~15 fills a session and
~6.5bp session-level dispersion, 60 MOC sessions give SE ≈ 0.84bp against a
32.6bp breakeven. That is a trigger that can fire for a true reason.

**1. One set of key names.** Make `risk.py` read `kill_drawdown` and
`halve_drawdown` (fractions), delete the dead `max_drawdown_kill_pct` lookup,
document the keys and units in `src/deploy/sleeve.py`'s module docstring next
to `RiskVerdict`, and grep every spec under `ops/specs/` and every sleeve so no
spec silently loses a control.

**2. The arming switch.** Add to the `risk` block:

```
"controls_armed": true,
"_controls_armed_note": "HALVE at halve_drawdown, KILL at kill_drawdown,
computed on broker-confirmed NAV only. Flipping this is a governance act
recorded in RESEARCH_STATE with the date and the thresholds."
```

With the key **absent or false**, behaviour must be byte-identical to today —
prove it by running `risk_check` and `risk.evaluate_sleeve` on the current
ledger before and after. **Then set it true.** Arming is the governance act
(standing decision, 2026-09-08); record the date and thresholds in
`docs/RESEARCH_STATE.md`.

**3. Drawdown on real sessions only.** The drawdown fed to the controls is
computed on the **broker-confirmed** NAV path, never the modelled one. Move
`dashboard/server.py::_provenance` into `ops/` so the dashboard and `risk.py`
import one implementation — the dashboard must not own logic the executor
depends on. A drawdown including modelled sessions is labelled "modelled" and
never triggers.

**4. Replace kill clause (a).** New `kill_rule` text and `ops/kill_rule.py`
evaluating it from files, no broker:

- **(a′) Cost.** Mean implementation shortfall over the last 40 MOC sessions
  (W7's `shortfall_log.csv`; until it exists, `slippage.csv` restricted to MOC
  sessions), with Lo-style SE, exceeds the 32.6bp breakeven at 95% confidence,
  **and** at least 20 sessions are in the window.
- **(b)** unchanged: realised slippage > 2× modelled for 5 consecutive
  sessions.
- **(c)** unchanged: top-minus-bottom discount spread below 12%.
- **(d) Structural, a REVIEW flag not a kill:** BR_eff below 1.5 for 20
  consecutive sessions **and** net muni weight beyond ±60% — the book has
  collapsed into one bet. Stays a flag until W10 gives the group bet a budget.
- **(e) Carry, new:** the book's borrow bill, annualised on held short market
  value, exceeds its expected net return (the band's expectation recomputed on
  W4's post-battery IC and total-return convention) for 20 consecutive
  sessions. A book paying more to hold its positions than it expects to earn
  from them is not a strategy, and no drawdown rule sees this. Borrow only —
  the distribution is inside total return once W4 lands and must not be charged
  twice.

Simulate the false-positive rate of the old clause (a) and the new (a′) on the
band backtest path with block-bootstrapped 60-session windows; both numbers go
in the note.

**5. Surface it.** `api_risk` reports `controls_armed`, each threshold, the
current value on the confirmed path, and the distance to it; the Controls
screen renders "observe-only" or "ARMED" in the chip.

---

## Part B — The sizing memo (gated; do not start until the gates pass)

**Objective (standing decision): absolute return at the highest volatility
target the evidence supports, capped at 20%.** The team is judged on absolute
return on a paper record. State plainly in the memo that a paper record judged
on absolute return still ends at the first margin call.

### The arithmetic the memo rests on

- The **unit-gross book** (Σ|w| = 1) realises about 4% annualised vol today. A
  target *v* needs gross *g = v/0.04*: 6% → 1.5×, 12% → 3.0×, 20% → 5.0×.
- **Reg T** caps gross at 2× equity, so at this vol Reg T allows about 8%.
  Anything above needs Portfolio Margin — which is why W2's `AccountType` audit
  gates this memo.
- **Kelly.** For Sharpe *S* with normal returns the growth-optimal vol target
  is *S* itself. At the band's net-of-borrow *S* ≈ 0.43–0.48 that is a 43–48%
  target; 6% is a Kelly fraction of ~0.13, half-Kelly ~22%, quarter-Kelly ~11%.
  With kurtosis 41.2 nobody should run above quarter-Kelly, and the fraction is
  a stated tolerance, not a derivation.
- **Costs that scale with gross, not with turnover.** Borrow drag at 1.22%/yr
  on held short MV is ~0.9% of NAV at 1.5× and ~1.8% at 3×. Return scales too,
  so the ratio is unchanged — but the dollar bill is not, the availability cap
  binds harder, the monthly recall exposure grows, and the margin cushion
  shrinks. The book's net yield carry (W4 Part A) also scales with gross and
  can run either sign; carry its measured value into every row.

### The table, one row per target *v* ∈ {6, 8, 10, 12, 15, 20}%

| target | required gross | Reg-T feasible | PM margin req | E[return] at S = 0.43 / 0.48 | short MV | borrow $/yr | net yield carry (sign, from W4) | availability: unfillable % | worst month (bootstrap) | worst 1-yr drawdown (bootstrap) | P(hit KILL within a year) | margin cushion at 3σ | Kelly fraction |

- **Margin:** use `margin.py`'s model, stating its provenance and assumed
  haircut; if it does not cover PM, state IBKR's published PM methodology
  (TIMS-style stress on net exposure) and give a range, clearly labelled an
  estimate, not a quote. Take the current cushion from `accountSummary`.
- **Drawdown and worst month: not from a normal.** Take the band policy's daily
  P&L path from the harness, scale by *g*, subtract borrow and carry, and
  moving-block bootstrap (6-month blocks, 5,000 draws) for the 5th percentile
  of 21-day loss and of max drawdown over one year. Kurtosis 41.2 is real; the
  empirical path carries it.
- **Availability:** run W8's capacity function at each implied short MV.
- **Kill probability:** the bootstrap frequency of touching `kill_drawdown`
  within a year at that gross.

**Derive the target** as the largest one whose bootstrap kill-probability is
below 10% **and** whose margin cushion stays above 0.25 at a 3σ one-day move.
Cap at 20%.

### The scalar cap

Today `clip(6%/σ̂, 0.2, 2.5)`. The 2.5 is inherited, not chosen. Propose the cap
as a function of a stated drawdown budget: given `book_worst_month_usd = 30000`
(6% of NAV) and the bootstrap distribution of monthly loss per unit gross, the
cap is the gross at which the 95th-percentile monthly loss equals the budget.
Show the number, and how often the historical scalar would have hit it.

### The gates, as a checklist with today's state

- [ ] Band has ≥ 20 armed sessions and W7's turnover readout passed.
- [ ] W7's realised-cost estimate has SE ≤ 2bp and a mean below breakeven.
- [ ] W4's artifact battery is written and the surviving IC is known — **the
      expected return in this table must use the post-battery IC, not −0.074,
      if the battery moved it.**
- [ ] W8's availability cap deployed, so scaling up does not scale unfillable
      shorts.
- [ ] Borrow drag on the live book below 1.5%/yr. Today it is 3.62% weighted;
      that is the muni concentration, and it must come down before leverage
      goes up.
- [ ] PM application status known (W2).
- [ ] The kill rule (Part A) is armed.

### The recommendation

One paragraph with the target you would choose **today** given which gates are
and are not met, and the single spec edit that implements it.

## Deliverables

- `risk.py` and sleeve changes, the spec keys, `ops/kill_rule.py`, the shared
  provenance function, the dashboard changes.
- `results/cef/KILL_RULE_<date>.md`: old vs new rule, the simulated
  false-positive rates, the exact conditions under which each clause fires, and
  the arming record.
- `docs/VOL_TARGET_DECISION.md`: the table, the cap derivation, the checklist,
  the recommendation.

## Do not

- Do not compute any control on modelled NAV.
- Do not change `book_drawdown_suspend_pct`.
- Do not size up on |z|, on dispersion, or on any conditional signal; all three
  were measured and lowered Sharpe.
- Do not change the spec in Part B; it produces a decision, a human makes it.
- Do not present the bootstrap drawdown as a forecast. It is the backtest
  path's tail, on a survivor-only panel until W1 Part C says otherwise.
