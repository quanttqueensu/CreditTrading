---
name: next-task
description: Decide what to work on next, ranked by value per hour against the book's actual constraints. Use at the start of a work session, when the queue is unclear, or when asked what matters most right now. Reads live state first (python3 -m ops.orient PROD: which machine is prod and whether it is armed), because operations outrank research whenever the book is not trading cleanly.
allowed-tools: Bash(python3 -m ops.orient*) Read Grep Glob
---

# What to work on next

## Live state

```!
python3 -m ops.orient --no-tests 2>/dev/null | sed -n '1,60p'
```

```!
grep -nE "^\| [0-9]|^## Phase" docs/ROADMAP.md 2>/dev/null | head -60
```

---

## The ranking rule

`IR ≈ IC · TC · √BR` (`docs/SYSTEM.md` §3). The IC is good; the **transfer
coefficient** and **effective breadth** are the binding problems, and uptime
multiplies all three. **Take no figure from this file.** Measure TC with
`python3 scripts/cef/band_frontier.py`; breadth and uptime have no live
measurement until the Alpaca runner exists (the IBKR-era tools were deleted).

So the order is almost always:

**1. Keep the book trading.** Measure it first: `python3 -m ops.orient` PROD
says which machine is prod and whether it is armed, and the last verify line
says whether the last session PASSed. A FAIL, a missed send, or an unarmed prod
outranks everything below, because research on a book with no uptime is wasted.
The open operations steps, with owners, are `docs/ROADMAP.md`; take the first
open one you can do.

**2. Build the fill record from the first Alpaca session.** Execution cost
converges far faster than Sharpe. Alpaca paper fills MOC at the quote, so keep
the auction-print P&L beside every paper fill (`CLAUDE.md`, research rules).

**3. The broker is the fact.** Reconcile from Alpaca's positions and account
activities, never from a local reconstruction: the IBKR design's ledger desyncs
halted every book in September (`pre-clean-slate:_archive/prod_state_2026-09-28/`).

**4. The vol target.** The value in force is orient SPEC `vol_target_annual`; the
standing decision on how it should be set is `docs/SYSTEM.md` §5. Sizing is a
larger lever on absolute return than any signal improvement, and it is gated on
measured borrow and a stated drawdown tolerance (W6).

**5. Raise breadth.** Most of the book's variance is one factor, municipal CEFs
against taxable ones. *Hard* group neutrality was tested and lost gross Sharpe
(`docs/RESEARCH_STATE.md`, KILLED — CEF construction variants): **size the group
bet deliberately**, do not eliminate it.

**6. Deploy the joint optimiser** — only after the band has live evidence (W12).

**7. Sharpen the signal.** Last. It has been measured repeatedly as the least
productive place to work (see the same KILLED table).

## The queue

`docs/ROADMAP.md` is the queue. The old work orders were deleted in the
2026-09-28 clean slate (git tag `pre-clean-slate`); their research ideas are
provenance for new work, not a queue.

## Budget discipline

Every research prompt that ran its maximum would spend many trials, and **they
should not all run**. Several parts are built to close themselves on a gate or a
derived budget of zero; a prompt that closes itself has done its job at the cost
of one trial rather than a year. Read the counters from `docs/RESEARCH_STATE.md`
(orient TRIALS derives each bar). Rank by *information gained per trial*, not
expected Sharpe.

## Before starting anything

Check `/graveyard`. The most common cause of death on this desk is a stale-price
artifact.
