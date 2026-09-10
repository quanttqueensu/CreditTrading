---
name: spec-change
description: The safe procedure for changing a frozen spec key, a book limit, or a cost-model entry. Use whenever editing anything under ops/specs/, ops/books/ or config/*.yaml. Covers the no-op proof, the sibling note, the units trap and the revert path.
argument-hint: [spec key or file]
---

# Changing a frozen spec

A key in `ops/specs/*.frozen.json` is **a commitment, not a constant**. Changing
one is a governance act with a paper trail.

## Current state

```!
ls -1 ops/specs/*.frozen.json 2>/dev/null; echo "---"; python3 -c "
import json
d = json.load(open('ops/specs/cef_discount.frozen.json'))
print('spec_id:', d['spec_id'], '| supersedes:', d.get('_supersedes'))
f = d['frozen']
for k in sorted(f):
    if not k.startswith('_'):
        print(f'  {k} = {f[k]}' + ('   [has _note]' if f'_{k}_note' in f else ''))
print('risk:', d.get('risk'))
print('rebalance:', {k: v for k, v in d.get('rebalance', {}).items() if not k.startswith('_')})
"
```

## The procedure

**1. Pre-register first.** Run `/prereg`. Anything that changes traded behaviour
needs a dated note in `results/cef/` and a trial on the CEF or GAMMA counter,
*before* the session that trades it.

**2. The new key must default to current behaviour.** With the key absent, the
sleeve must do exactly what it does today. The code change alone should be a
provable no-op, so that activation is one visible edit.

**3. Prove the no-op — do not assert it.** Diff sleeve output byte-for-byte with
the key absent. The band was verified this way. Record in the commit message that
you did it and how.

**4. Write the sibling `_<key>_note`.** Read `_band_width_note` and
`_min_trade_note` in `cef_discount.frozen.json` — that is the standard. Each names:
what was derived and how, the measured inputs, **the value that topped the sweep
and was deliberately not chosen**, the consequence accepted knowingly, what reads
the key, and the exact **REVERT** (usually "delete this key").

**5. Bump `spec_id`, set `_supersedes`, keep the old file** as `*.bak-<date>`.

**6. Update `docs/RESEARCH_STATE.md` in the same commit** as the trial.

## The units trap

`book_drawdown_suspend_pct` read `0.99` when it was meant to be *disabled*.
`src/deploy/risk.py` computes `cap = -abs(pct)/100`, so the limit intended to be
off at 99% was live at **0.99% — the tightest in the book** — and breached at
−1.84% on 2026-08-31. It is now `99.0`.

**Percent keys in this repo are whole numbers.** State the unit in the note. Check
bp vs percent vs fraction at every boundary, and ÷252 vs ÷360 on anything that
accrues.

## Keys that are declared but wired to nothing

`kill_drawdown` (0.18) and `halve_drawdown` (0.12) are in the frozen spec and read
by **no code path**. All three sleeves' `risk_check` return OK unconditionally.
This was justified in writing by "there is no real capital at risk" — a
justification on a clock, and the standing decision is to arm HALVE/KILL on
broker-confirmed NAV.

**Do not quietly change these numbers.** Wire them, then decide the numbers with a
memo. Changing a number that nothing reads is theatre; changing it *as* you wire it
conflates two decisions.

## Inert-by-design keys

`rebalance_days: 2` is **inert while `band_width` is set** — a band and a calendar
are two answers to the same question and running both compounds them. It is
retained so that deleting `band_width` restores v5 exactly. Do not "clean up" an
inert key; it is the revert path.

## After the edit

```bash
python3 -m pytest -q                       # 115 tests
python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live
```

If you changed behaviour and no test failed, that is itself a finding — add the
test.

The `PostToolUse` hook will remind you of this procedure when you edit a frozen
spec. The `ask` permission rule on `ops/specs/**` and `ops/books/**` will pause
first. Both are deliberate.
