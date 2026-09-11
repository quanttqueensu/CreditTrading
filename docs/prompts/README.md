# `docs/prompts/` — the work orders, and which of them are live

**Index written 2026-09-10 (W0c §4); `W15` added 2026-09-11.** Twenty-two entries live here. Three of
them matter on any given day and eighteen do not, and until this file existed
the only way to tell was to open all twenty-one.

**Every prompt in this directory opens with `00_BRIEF.md`.** Read that first;
it is the standing brief, not a prompt, and the others assume it.

## How to read a row

Each prompt states its own **Status**, **Lever**, **Trials** and **Touches the
live book** in its preamble. This table copies those, so it can drift — **the
prompt is authoritative, this index is a finding aid.**

That hierarchy used to be a hope. It is now checked:

```bash
python3 ops/prompt_status.py           # the table, derived from the repo
python3 ops/prompt_status.py --check   # exit 1 if this file disagrees with the prompts
```

`ops/tests/test_prompt_status.py` runs `--check` in the suite, so a row that
drifts from its prompt, an `EXECUTED` banner citing a commit that does not
exist, and a status citing a `results/` note that was never written all turn
`python3 -m pytest` red. What the tool does **not** do is decide a status —
it cannot know that `W8` Part A's method is dead or that `W14` is blocked on
`W2`. It checks that whatever a human claimed is backed by something.

`IR ≈ IC · TC · √BR`. The lever column says which term a prompt moves. Our IC
is settled; **TC (~37%) and BR (1.17 effective against 17 nominal) are the
problem**, so a TC or BR prompt outranks an IC prompt at equal cost.

## Status vocabulary

| status | means |
|---|---|
| **executed** | landed in full, with the commits named. The prompt is history; read it for why, not for what to do. |
| **in progress** | **part of it has landed and part has not.** Either someone is working it now — check with them before starting — or work landed under another prompt and stopped. The evidence clause says which parts are done; **read it before starting, or you will redo them.** |
| **queued** | written, never run. No commit references it, no deliverable of its exists, and no trial has been spent on it. |
| **standing** | not a prompt. A brief that other prompts open with; it is never "run". |
| **dated artifact** | not a prompt. A work order written for one named day. |

**Corrected 2026-09-10 ~18:00.** Until then this table offered only the first
and third values in practice, and `in progress` was defined as "being worked
now". Three prompts — `W2`, `W5`, `W8` — had real work already landed and were
filed `queued`, whose definition explicitly says "no commit references it". That
was false for all three, and it is the shape of drift that costs a session:
the index reads *never started*, so the work gets done twice. Verify any row
below with `python3 ops/prompt_status.py`; do not trust the table.

## The index

| prompt | lever | trials | touches live book | status | evidence |
|---|---|---:|---|---|---|
| `00_BRIEF.md` | — standing brief, read first | — | no | **standing** | — |
| `W0_repo_hygiene.md` | none directly; unblocks reading | 0 | two import fixes | **executed** | 2026-09-10 — `0c81d3f`, the `W0-A`…`W0-G` commits, `80b458e`; `results/ops/REPO_HYGIENE_2026-09-10.md` |
| `W0b_prod_dev_split.md` | largest operational risk in the repo | 0 | **yes, profoundly** | **executed** | 2026-09-10 — `c6fc9b1`; verify against the machine with `git worktree list` |
| `W0c_repo_coherence.md` | agent-hours; kills a class of incident | 0 | one gate fix in `ops/promote.sh` | **in progress** | done: 5 of its 6 §8 items — `cb6f3a7` gate fix + `ops/tests/test_promote_gate.py`, `0b828dc` CLAUDE.md, this index. **remains:** "28 commits pushed" — `main` is ahead of `origin/main` and tags `v2026.09.10.4`/`.5` are local-only |
| `W1_inference_protocol.md` | inference — every other prompt inherits it | 0 | no | **queued** | — |
| `W2_account_audit.md` | prerequisites; W14 blocks on it | 0 | no | **in progress** | done: per-book halt scoping — `43ec054`, `26a5336`, pinned by `src/deploy/tests/test_halt_scope.py`; the prompt says so in its own body. **remains:** the account audit itself (options permission, margin type, commission plan), and deduping the benchmark fill files |
| `W3_session_architecture.md` | TC and reliability | 0 | **yes** | **queued** | — |
| `W4_artifact_battery.md` | none — can only *subtract* | 0 | no | **queued** | — |
| `W5_order_integrity.md` | integrity of the record every statistic uses | 0 | shadow ledger | **in progress** | done: P0.1 dust orders, 2026-09-08 — `9636502`, `results/cef/DUST_ORDERS_2026-09.md`; `min_trade_usd` is derived and in the frozen spec. **remains:** everything else, and re-deriving `min_trade_usd` once `W2` says which commission plan the account is on — the spec's 517 assumes Fixed, Tiered gives 181 |
| `W6_risk_governance.md` | governance, then return at unchanged Sharpe | 0 | spec keys + code paths | **queued** | — |
| `W7_cost_and_turnover.md` | measurement gating every capture decision | 0 | no | **queued** | — |
| `W8_carry_and_capacity.md` | **TC** — borrow scales with holdings | ≤2 | no | **in progress** | done: Part A's *method* is measured **dead** — `results/cef/BORROW_AVAILABILITY_2026-09-10.md` (`80b458e`) shows the two disputed sources never reported on the same date and one is permanently 404, so "a week of paired readings" settles nothing. **remains:** all of it; Part A needs a new method first |
| `W9_dashboard.md` | the desk's instrument | 0 | no | **queued** | — |
| `W10_breadth_and_groups.md` | **BR** — effective breadth is 1.17 | ≤5 | no | **queued** | Part D superseded by `perfund/F2` |
| `W11_trading_policy.md` | **TC** — holding period and per-name bands | 2 | no | **queued** | — |
| `W12_joint_optimiser.md` | **TC and BR together** | 0 shadowing; 1 promoted | no — computes alongside | **queued** | — |
| `W13_nav_quality_and_horizon.md` | IC, via NAV measurement error | 2 | no | **queued** | — |
| `W14_options.md` | Part A measurement; then GAMMA | 0 / 1 / 1 | no | **queued** | blocked on `W2` saying "options: permitted"; Parts B/C moved to `gamma/G5`, `G7` |
| `W15_schedule_reliability.md` | **uptime — 6 of 29 eligible sessions armed; a missed session has IC 0** | 0 | **yes, lanes A/B/E** | **in progress** | written 2026-09-11. **done:** Lane F — `ops/session_uptime.py` is the named reproducer for every uptime figure, with `ops/tests/test_session_uptime.py`, `ops/tests/test_dashboard_sessions_route.py` and a read-only `GET /api/sessions` panel; it measures **6 armed of 29 eligible, 4 cleanly**, and refutes this prompt's own "of 30" (30 counts Labor Day `cef_2026-09-07.log` as eligible). **remains:** lanes A–E, and G is gated behind them. Lane A is blocking: prod runs `ops-guards-20260911`, NOT an ancestor of `main`, forked at `ac83a26` — but five of its eight commits are patch-id-identical to `main`, so the only true delta is live ledger state, not code |
| `NEXT_2026-09-11.md` | — dated work order, not a prompt | — | — | **dated artifact** | — |
| `gamma/` (`G0`–`G7`) | the options programme | GAMMA counter | no | **queued** | `G0_BRIEF.md` is **standing**; GAMMA counter still 0 |
| `perfund/` (`F1`–`F3`) | per-name resolution | CEF counter | no | **queued** | `F2` supersedes `W10` Part D |

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
