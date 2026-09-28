---
name: next-task
description: Decide what to work on next, ranked by value per hour against the book's actual constraints. Use at the start of a work session, when the queue is unclear, or when asked what matters most right now. Reads live state first, because operations outrank research when the book is not trading — and since 2026-09-28 nothing trades until the Alpaca system is built.
allowed-tools: Bash(python3 -m ops.orient*) Read Grep Glob
---

# What to work on next

## Live state

```!
python3 -m ops.orient --no-tests 2>/dev/null | sed -n '1,60p'
```

```!
sed -n '/^## 5\./,/^## 6\./p;/^## 6\. Next/,$p' results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md 2>/dev/null | head -60
```

---

## The ranking rule

`IR ≈ IC · TC · √BR` (`docs/SYSTEM.md` §3). The IC is good; the **transfer
coefficient** and **effective breadth** are the binding problems, and uptime
multiplies all three. **Take no figure from this file.** Measure TC with
`python3 scripts/cef/band_frontier.py`; breadth and uptime have no live
measurement until the Alpaca runner exists (the IBKR-era tools are archived).

So the order is almost always:

**1. Get a book trading again.** Since 2026-09-28 nothing trades: IBKR is
retired and the Alpaca system is not built. Until it is, every other item below
is research on a book with no uptime. The remaining steps, in order, are
`results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` §5–§6 — the keys, the
read-only probe, the v7 spec change on Alpaca, the paper order-behaviour probes,
then the runner, reconciliation and the VM.

**2. Build the fill record from the first Alpaca session.** Execution cost
converges far faster than Sharpe. Alpaca paper fills MOC at the quote, so keep
the auction-print P&L beside every paper fill (`CLAUDE.md`, research rules).

**3. The broker is the fact.** Reconcile from Alpaca's positions and account
activities, never from a local reconstruction: the IBKR design's ledger desyncs
halted every book in September (`_archive/prod_state_2026-09-28/`).

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

There are no live work orders: every one was archived on 2026-09-28
(`_archive/docs/prompts/`, archived) with the move to Alpaca. The research ideas in
them are provenance for new orders, not a queue. Until new ones are written, the
queue is the migration manifest's §5–§6.

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
