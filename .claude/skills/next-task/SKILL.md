---
name: next-task
description: Decide what to work on next, ranked by value per hour against the book's actual constraints. Use at the start of a work session, when the queue is unclear, or when asked what matters most right now. Reads live book state first, because operations outrank research when the book is not trading.
---

# What to work on next

## Live state

```!
python3 .claude/hooks/book_state.py -p 2>/dev/null | python3 -c "
import json, sys
s = json.load(sys.stdin)
f, hb = s.get('fills', {}), s.get('heartbeat', {})
gap = f.get('gap_sessions')
print(f\"last broker-confirmed fill: {f.get('date')} ({gap} trading day(s) ago)\")
print(f\"sessions with real fills: {f.get('n_sessions')}   executions: {f.get('n_fills')}\")
bad = [f'{k}:{v.get(\"status\")}' for k, v in hb.items() if v.get('status') not in (None, 'ok')]
print('heartbeat problems:', ', '.join(bad) if bad else 'none')
print('halt active:', (s.get('halt') or {}).get('active'))
"
```

---

## The ranking rule

`IR ≈ IC · TC · √BR`. Our **IC is settled and good**. Our **TC is ~37%**. Our
**effective breadth is 1.17** against a nominal 17. And the book has armed on **3 of
26 sessions**.

So the order is almost always:

**1. Uptime before everything.** If `gap_sessions ≥ 3`, stop and fix that. Nothing
else matters if the book does not trade — a book that trades on 3 sessions in 5
weeks cannot learn anything about itself no matter how good the mathematics gets.
The named highest-value change in `docs/SYSTEM_AND_STRATEGY.md` §12 is still
outstanding: **make a non-armed session raise an alert.** It currently writes
`ok_not_armed` and is silent, which is exactly how a 21-session outage went
unnoticed for a month.

**2. Accumulate the fill record.** Cost converges ~60× faster than Sharpe: at ~15
fills/session, 60 sessions gives SE ≈ 0.84bp against a 32.6bp breakeven. We have
**n = 1** for the live method. Everything about whether this strategy is viable
turns on that number.

**3. Reconcile ledger vs broker.** Reported P&L is currently wrong on all 17
positions. Sizing is unaffected, but no live statistic can be trusted until this is
closed.

**4. Decide the vol target.** We run 6% — roughly 1/12 Kelly, realising 4.95%.
**Doubling it doubles return at unchanged Sharpe, which is larger than every signal
improvement combined.** Gated on measured borrow and a stated drawdown tolerance.
Derive it, cap at 20%, do not pick it.

**5. Raise breadth.** 92.5% of live book variance is one factor. Note that *hard*
muni neutrality costs gross Sharpe 0.97 → 0.82 — the answer is to **size the group
bet deliberately**, not eliminate it.

**6. Deploy the joint optimiser** — but only after the band has live evidence.

**7. Sharpen the signal.** Last, and it has been measured repeatedly as the least
productive place to work: price reversal adds +0.1%, the Kalman lost to a shorter
window, per-name κ lost to pooled.

## The prompt queue

`docs/prompts/00_BRIEF.md` §8 carries the ordered queue and its dependencies:

**W0 → W1 → W2 → W4 → W3 → W5 → W7 → W6 §A → W9 Stage 1 → F1 → W8 → W10 §A/§B →
W9 Stages 2–4 → W11 → W12 → F2 → W10 §C/§E/§F → W13 → F3 → W6 §B.**

Gamma runs beside it: **G1 → G4 → G3 → G2 → G6 → G5 → G7.**

Three things are early on purpose. **W4** (the artifact battery) can only subtract,
costs no trials, and if the IC does not survive it then most of what follows is
answering the wrong question — including all of `perfund/`, which would otherwise
build seventeen sleeves on an artifact. **F1** because F2 and F3 are fiction without
per-fund facts. **G1/G4** because they are pure engineering that unblocks the rest,
and two of G4's defects are live on the order path.

## Budget discipline

If every research prompt ran its maximum it would spend ~21 trials on CEF (48 → ~69,
bar 2.80 → 2.90) and 2 on GAMMA. **They should not all run.** Several parts are
built to close themselves — W14 Part B on its stress-beta gate, W10 Part C and G7 on
a derived budget of zero, W13 Part C on the nowcast R², F2 on a τ posterior that
includes zero. **A prompt that closes itself has done its job at the cost of one
trial rather than a year.**

Rank by *information gained per trial*, not expected Sharpe.

## Before starting anything

Check `/graveyard`. Thirteen mechanisms are dead and six died the same way.
