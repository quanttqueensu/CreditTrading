# `docs/prompts/` — the work orders, and which of them are live

**Index written 2026-09-10 (W0c §4).** Twenty-one entries live here. Three of
them matter on any given day and eighteen do not, and until this file existed
the only way to tell was to open all twenty-one.

**Every prompt in this directory opens with `00_BRIEF.md`.** Read that first;
it is the standing brief, not a prompt, and the others assume it.

## How to read a row

Each prompt states its own **Lever**, **Trials** and **Touches the live book**
in its first ten lines. This table copies those, so it can drift — the prompt
is authoritative, this index is a finding aid. `Status` is the column that is
maintained here, and it is set from git evidence, not from memory.

`IR ≈ IC · TC · √BR`. The lever column says which term a prompt moves. Our IC
is settled; **TC (~37%) and BR (1.17 effective against 17 nominal) are the
problem**, so a TC or BR prompt outranks an IC prompt at equal cost.

## Status vocabulary

| status | means |
|---|---|
| **executed** | landed, with the commits named. The prompt is history; read it for why, not for what to do. |
| **in progress** | being worked now. Check with whoever holds it before starting. |
| **queued** | written, never run. No commit references it. |

## The index

| prompt | lever | trials | touches live book | status |
|---|---|---:|---|---|
| `00_BRIEF.md` | — standing brief, read first | — | no | **standing** |
| `W0_repo_hygiene.md` | none directly; unblocks reading | 0 | two import fixes | **executed** 2026-09-10 (`0c81d3f`, `W0-A`…`W0-G`, `80b458e`) |
| `W0b_prod_dev_split.md` | largest operational risk in the repo | 0 | **yes, profoundly** | **executed** 2026-09-10 (`c6fc9b1`; verify with `git worktree list`) |
| `W0c_repo_coherence.md` | agent-hours; kills a class of incident | 0 | one gate fix in `ops/promote.sh` | **in progress** 2026-09-10 |
| `W1_inference_protocol.md` | inference — every other prompt inherits it | 0 | no | queued |
| `W2_account_audit.md` | prerequisites; W14 blocks on it | 0 | no | queued |
| `W3_session_architecture.md` | TC and reliability | 0 | **yes** | queued |
| `W4_artifact_battery.md` | none — can only *subtract* | 0 | no | queued |
| `W5_order_integrity.md` | integrity of the record every statistic uses | 0 | shadow ledger | queued |
| `W6_risk_governance.md` | governance, then return at unchanged Sharpe | 0 | spec keys + code paths | queued |
| `W7_cost_and_turnover.md` | measurement gating every capture decision | 0 | no | queued |
| `W8_carry_and_capacity.md` | **TC** — borrow scales with holdings | ≤2 | no | queued |
| `W9_dashboard.md` | the desk's instrument | 0 | no | queued |
| `W10_breadth_and_groups.md` | **BR** — effective breadth is 1.17 | ≤5 | no | queued |
| `W11_trading_policy.md` | **TC** — holding period and per-name bands | 2 | no | queued |
| `W12_joint_optimiser.md` | **TC and BR together** | 0 shadowing; 1 promoted | no — computes alongside | queued |
| `W13_nav_quality_and_horizon.md` | IC, via NAV measurement error | 2 | no | queued |
| `W14_options.md` | Part A measurement; then GAMMA | 0 / 1 / 1 | no | queued (blocked on W2) |
| `NEXT_2026-09-11.md` | — dated work order, not a prompt | — | — | dated artifact |
| `gamma/` (`G0`–`G7`) | the options programme | GAMMA counter | no | queued |
| `perfund/` (`F1`–`F3`) | per-name resolution | CEF counter | no | queued |

**The trial counters are in `docs/RESEARCH_STATE.md` and that table is
canonical** — CEF and GAMMA each carry their own deflated-Sharpe bar √(2 ln N).
The `trials` column above is what a prompt *budgets*, not what has been spent.
Update the counter in the same commit as the trial, never at the end of a
session.

## `_superseded/`

Fifty-two finished or replaced prompts, including the original P-series. Its
`00_README.md` is the method note the whole series shares and is still worth
reading. Nothing in `_superseded/` should be executed.

**Archiving is a `git mv`, never a delete, and every move leaves a pointer.**
See the repo `README.md` for the one archive convention this repo uses.
