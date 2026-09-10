---
name: prereg
description: Write a pre-registration before a change trades. Use when adopting a new parameter, policy, signal or sleeve, before the session that trades it. Produces a dated note in results/ and increments the correct trial counter.
argument-hint: [what is changing]
---

# Pre-registration

**Write this before the session that trades the change, not after.** A
pre-registration written afterwards is a rationalisation, and this desk can tell
the difference because it dates them.

Model: `results/cef/PREREG_BAND_2026-09-06.md`.

## The template

Write to `results/cef/PREREG_<TOPIC>_<YYYY-MM-DD>.md`:

```markdown
# Pre-registration — <what is changing>
Date: <YYYY-MM-DD>   Counter: <CEF|GAMMA>, trial <n>   Author: <name>

## 1. What changes
The exact key, file and value. Old → new. The one-line revert.

## 2. Why, mechanically
The mechanism, not the backtest. If the only argument is that it scored better,
that is a swept column and it is not enough.

## 3. How the parameter was DERIVED
The formula, the measured inputs, the resulting value. Then: where the derived
value sits on the swept plateau, and **what the argmax of the sweep was and why
it was not chosen**.

## 4. Committed in advance
- Execution convention: shift(2)
- Cost grid: 5 / 15 / 30bp; borrow charged separately and labelled
- Eras: 2005–09, 2010–14, 2015–19, 2020–22, 2023–26
- Fit period ends 2023-01-01; holdout 2023–2026 reported separately
- Turnover-matched against: <reference policy, turn/yr>
- Negative control: <where the mechanism cannot operate>

## 5. What we expect
The numbers, with uncertainty. Being wrong here is fine and is the point.

## 6. What would FALSIFY this
**The live statistic, the horizon, and the threshold.** Name the number that
would reverse the decision and when it will be read. Vague failure conditions
are how a bad change survives.

## 7. Divergences from backtest, stated up front
Everything the live path does that the backtest does not: min_trade_usd flooring,
odd lots, availability caps, missed sessions, delayed data, the auction's ~3.3–6.3%
unfilled rate for non-Russell-1000 names.

## 8. Trial accounting
Counter <CEF|GAMMA>: <n-1> → <n>. Bar √(2 ln N) = <x.xx>.
Updated in docs/RESEARCH_STATE.md in this same commit: yes/no.
```

## Rules

- **Section 6 is the one that matters.** A pre-registration without a falsifier is
  a press release. Name the statistic, the horizon and the threshold.
- **Section 3 must name the value you did not choose.** `z_window = 63` was the
  argmax of a swept column, chosen with the holdout sealed; the holdout was opened
  hours later and it failed (gross 1.75, **net −0.298**). The band note names 6.4%
  as the swept winner that was rejected, which is what makes it credible.
- **Update `docs/RESEARCH_STATE.md` in the same commit.** That table is the
  canonical trial record and it has already drifted once — the CEF counter read 18
  for five weeks while the true figure was 48.
- **Say which counter.** CEF (48) and GAMMA (0) each carry their own deflated-Sharpe
  bar; the combined book is judged on the joint record.
- **Kill rules are pre-committed and not softened later.** The CEF book's is
  reviewed at 60 live sessions and not before: (a) live net Sharpe < 0; (b) realised
  slippage > 2× modelled for 5 consecutive sessions; (c) top-minus-bottom discount
  spread below 12%. No extension of rope.

## Then

Run `/spec-change` for the mechanics of editing the frozen spec safely.
