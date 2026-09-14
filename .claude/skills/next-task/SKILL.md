---
name: next-task
description: Decide what to work on next, ranked by value per hour against the book's actual constraints. Use at the start of a work session, when the queue is unclear, or when asked what matters most right now. Reads live book state first, because operations outrank research when the book is not trading.
allowed-tools: Bash(python3 -m ops.orient*) Bash(python3 -m ops.prompt_status*) Bash(python3 -m ops.session_uptime*) Read Grep Glob
---

# What to work on next

## Live state

```!
python3 -m ops.orient --no-tests 2>/dev/null | sed -n '1,60p'
```

```!
python3 -m ops.prompt_status 2>/dev/null | tail -25
```

---

## The ranking rule

`IR ≈ IC · TC · √BR` (`docs/SYSTEM.md` §3). The IC is good; the **transfer
coefficient** and **effective breadth** are the binding problems, and uptime
multiplies all three. **Take no figure from this file.** Measure TC with
`python3 scripts/cef/band_frontier.py`, breadth with the dashboard's
`/api/factors`, uptime with `python3 -m ops.session_uptime`, which reads both log
trees and refuses rather than undercounts.

So the order is almost always:

**1. Uptime before everything.** If orient BOOK shows the last broker-confirmed
fill three or more trading days back, or UPTIME is incomplete, stop and fix that —
a book that does not trade cannot learn anything about itself. The session
itself still raises no alert when it declines to arm; the post-close verifier
(`ops/verify_session.py`) FAILs a day on which no deciding job armed and sends one
message per trading day. Whether that message reaches anyone off the machine is
`python3 -m ops.doctor --quick`.

**2. Accumulate the fill record.** Execution cost converges far faster than
Sharpe, and whether this strategy is viable turns on it. `/fill-audit` says how
many broker-confirmed MOC sessions exist and what their standard error is.

**3. Reconcile ledger vs broker.** The ledger is a local reconstruction; `arm()`'s
re-seed cannot reach a symbol the broker holds none of, so a divergence of that
shape is a **trading** fault, not a reporting one (`CLAUDE.md` landmine 3).
Re-measure before quoting any magnitude — read-only, from a snapshot where one
exists, and with `python3 -m ops.reconcile_orders ... --check-broker` only when a
broker socket is acceptable.

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

`docs/prompts/README.md` is the index and `python3 -m ops.prompt_status` derives
each work order's real status from the repo. **Read a part-done prompt's evidence
row before starting it**, or you will redo work that has already landed. The
ordering rationale as written on 2026-09-09 is in the archived snapshot
`_archive/docs/prompts/00_BRIEF_2026-09-14.md` §8; treat it as history, not as the
current order.

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
