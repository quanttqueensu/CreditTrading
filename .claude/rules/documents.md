---
paths:
  - "docs/**"
  - "results/**"
  - "README.md"
---

# Writing documents and results notes

This project's documents are load-bearing. They are how a competent stranger picks
the book up cold, and how a decision made in September survives to February. Match
the register that is already there.

## The three categories, kept separate

**Established / measured-but-conditional / unknown.** Keeping these apart is the
most important discipline in this project. Never let a conditional number drift
into the established column because it has been repeated a few times.

- *Established*: IC −0.074 (t −11.6), 27 years, every sub-period; 9/9 purged
  walk-forward; bootstrap P(SR≤0) = 0.000%; not credit beta (β +0.013, R² 0.0008).
- *Measured but conditional*: borrow at 1.22%/yr ≈ 0.23 Sharpe — **measured once**,
  on 2026-09-06, and applied to 21 years. A forward estimate, not a historical cost.
- *Unknown, and the unknowns dominate*: what execution actually costs (n = 1,
  dispersion ±93.8bp); whether the paper record means anything; survivorship, which
  these files cannot measure.

## Rules

1. **Every number names the script that reproduces it.** If it cannot be
   reproduced, it is an anecdote and must be labelled as one.
2. **Say when it was measured.** A borrow panel two days old, an option chain
   snapshotted one afternoon, a variance decomposition on a panel that ends six
   weeks ago — several figures in these documents have already gone stale. Date
   them so the reader can tell.
3. **Record negative results against yourself.** `docs/PLAN.md` §0.3 records a claim
   its own author made and then measured to be false. Do that. The graveyard is the
   most valuable artefact this project has.
4. **No decision rule may key on a number written in a document** (H14). If a
   passage reads "X is 59.6%, therefore do Y", it is wrong and should read "measure
   X this way; if it is high, Y follows; if not, Z."
5. **Correct in place, visibly.** When a figure was wrong, leave a dated correction
   note rather than a silent edit — `RESEARCH_STATE.md`'s CEF-counter correction and
   the ex-distribution arithmetic correction in the brief are the model. Someone is
   relying on the old number somewhere.
6. **Cite externally-sourced claims into `docs/REFERENCES.md`** with a verification
   status. Prompts cite that file; they do not re-derive it.
7. **British spelling, plain sentences, no marketing.** Tables for anything with
   more than two dimensions. The audience is a competent agent picking this up cold.

## Where things belong

| file | holds |
|---|---|
| `docs/prompts/00_BRIEF.md` | the standing brief every research prompt opens with |
| `docs/PLAN.md` | what to do next about capture, with the measurements behind it |
| `docs/RESEARCH_STATE.md` | **canonical trial counters**, killed/watch/active/queue |
| `docs/SYSTEM_AND_STRATEGY.md` | the system and strategy for a cold reader |
| `docs/RESEARCH_AND_METHODOLOGY.md` | D1–D7, how we decide something is real |
| `docs/REFERENCES.md` | every external claim, with a verification status |
| `results/<family>/` | dated findings notes and pre-registrations |
| `ops/halts/HALT_<ts>.md` | incident records |

`docs/RESEARCH_STATE.md` is the canonical trial record — **update it in the same
commit as the trial, not at the end of a session.** It has already drifted once:
the CEF counter read 18 for five weeks while the true figure was 48.

## Pre-registrations

`results/cef/PREREG_BAND_2026-09-06.md` is the shape. Every one states, before the
session that trades it: what changes, why, what is committed in advance, what would
falsify it, and the divergences from backtest **stated up front**. Use `/prereg`.
