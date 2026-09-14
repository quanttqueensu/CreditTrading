# `docs/prompts/` — the work orders, and which of them are live

**Index written 2026-09-10; executed and closed prompts archived 2026-09-14.**
Only work orders that still have open parts live here. Until this file existed
the only way to tell which of them mattered on a given day was to open all of them.

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
it cannot know that `W8` Part A's method is dead. It checks that whatever a human claimed is backed by something.

`IR ≈ IC · TC · √BR`. The lever column says which term a prompt moves. The IC is
good; **TC and effective breadth are the problem** (`docs/SYSTEM.md` §3 names
the command that measures each), so a TC or BR prompt outranks an IC prompt at
equal cost.

**When a part of a work order closes, its `**Status:**` line says so in the same
commit** — done parts with their commits, remaining parts by name, and parts
overtaken by other work marked as such. **When nothing remains, the prompt is
archived** (`git mv` to `_archive/docs/prompts/`), not left in this index as
"in progress". `ops.doc_audit` holds these files to the same no-stale-figures
check as `CLAUDE.md`.

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
| `W1_inference_protocol.md` | inference — every other prompt inherits it | 0 | no | **queued** | — |
| `W2_account_audit.md` | prerequisites for sizing and the null trader's retirement | 0 | no | **in progress** | done: Part A's tool and note (`ops/account_audit.py`, `results/ops/ACCOUNT_AUDIT_2026-09-12.md`): margin type measured; the options questions it asked are moot now options are closed; the commission plan was NOT measured. Part B, per-book halt scoping (`43ec054`, `26a5336`). remains: the commission plan (W5's `min_trade_usd` waits on it); Part C, retiring the null trader — prepared, not executed (`b12dec3`, `results/ops/PHASE0_RETIRED_2026-09-13.md`; open in `docs/SYSTEM.md` §5); the benchmark fill dedupe. |
| `W3_session_architecture.md` | TC and reliability | 0 | **yes** | **in progress** | done: Part A, the morning decision on yesterday's pair (`939af5c`, `b442986`, `e4ac1ed`), live since the 2026-09-13 go-live (`results/ops/GO_LIVE_W3_2026-09-13.md`); toward Part C, the post-close verifier that FAILs a day on which no deciding job armed (`5a92b70`, `da83a87`) and the pre-transmit refusal (`fa53395`, `cda493c`). remains: Part B (none of its deliverables exist: no IBKR price fetcher, no NAV-channel or price-source logs, no DATA_SOURCES note); Part C's alerting note and doctor passing on alerts (email is still a WARN); Part D (no `session_progress.json`, no `/api/session`); the 17:30 `cef_pm` job runs DRY_RUN=1 until one morning cycle has been watched. |
| `W4_artifact_battery.md` | none — can only *subtract* | 0 | no | **queued** | — |
| `W5_order_integrity.md` | integrity of the record every statistic uses | 0 | shadow ledger | **in progress** | done: P0.1 dust orders (`9636502`, `results/cef/DUST_ORDERS_2026-09.md`). remains: Part A is UNVERIFIED — since 2026-09-08 band HOLDs are qty-expressed, which stops the ledger's lag-day flatten, but the per-executor unpriced-name test Part A asks for was not found; Part B, the order lifecycle (no `order_events.csv`, no `/api/orders`, no session journal); re-deriving `min_trade_usd` once W2 measures the commission plan. |
| `W6_risk_governance.md` | governance, then return at unchanged Sharpe | 0 | spec keys + code paths | **queued** | — |
| `W7_cost_and_turnover.md` | measurement gating every capture decision | 0 | no | **queued** | — |
| `W8_carry_and_capacity.md` | **TC** — borrow scales with holdings | ≤2 | no | **in progress** | done: Part A's *method* is measured **dead** — `results/cef/BORROW_AVAILABILITY_2026-09-10.md` (`80b458e`) shows the two disputed sources never reported on the same date and one is permanently 404, so "a week of paired readings" settles nothing. **remains:** all of it; Part A needs a new method first |
| `W9_dashboard.md` | the desk's instrument | 0 | no | **queued** | — |
| `W10_breadth_and_groups.md` | **BR** — effective breadth is a small fraction of the name count | ≤5 | no | **queued** | Part D superseded by `perfund/F2` |
| `W11_trading_policy.md` | **TC** — holding period and per-name bands | 2 | no | **queued** | — |
| `W12_joint_optimiser.md` | **TC and BR together** | 0 shadowing; 1 promoted | no — computes alongside | **queued** | — |
| `W13_nav_quality_and_horizon.md` | IC, via NAV measurement error | 2 | no | **queued** | — |
| `W15_schedule_reliability.md` | **uptime** — a session that does not arm has IC 0 | 0 | **yes, lanes A/B/E** | **in progress** | done: Lane A, prod reunified on `main` (prod runs a tag cut from `main`; the `ops-guards-20260911` fork was deleted 2026-09-14 with its commits kept by tag; `main` is pushed); Lane B, the decision-age refusal (`2b682f5`) — but three of its timeline tests in `src/deploy/tests/test_decision_age_clock.py` FAIL on `main` as of 2026-09-14 and need re-deriving for the morning schedule; Lane E, `launch_job.py` runs each panel under the session's phase budget (verified by reading it, 2026-09-14); Lane F, `ops/session_uptime.py` and `GET /api/sessions`; toward Lane D, the stuck-session doctor check (`81c0658`) and the post-close verifier (`5a92b70`). remains: Lane B's failing tests; Lane A step 5, a doctor check for stray worktrees; Lane C, the repeating wake (a sudo command for the human, which doctor prints); Lane D, email alerting still a WARN not a FAIL and the watchdog still firing once, at 19:30; Lane G stays gated behind A–F. |
| `perfund/` (`F1`–`F3`) | per-name resolution | CEF counter | no | **queued** | `F2` supersedes `W10` Part D |

**The trial counters are in `docs/RESEARCH_STATE.md` and that table is
canonical** — CEF and GAMMA each carry their own deflated-Sharpe bar √(2 ln N).
The `trials` column above is what a prompt *budgets*, not what has been spent.
Update the counter in the same commit as the trial, never at the end of a
session.

## Archived prompts

The original P-series (including `00_README.md`, the method note the series
shared) and the dated `NEXT_2026-09-11.md` work order moved to
`_archive/docs/prompts/` on 2026-09-13. On 2026-09-14 the executed and closed
work orders followed: `W0`, `W0b` and `W0c` (executed), `W14` (Part A done, its
gate closed Part B, Part C needed the gamma surface), and the whole `gamma/`
programme (`G0_BRIEF`, `G1`–`G7`; options are recorded closed in
`docs/SYSTEM.md` §5 and `docs/RESEARCH_STATE.md`, and `python3 -m ops.gamma_status`
still reports the programme's state). They are provenance, not instructions:
nothing there should be executed, and `_archive/README.md` lists what they are
wrong about.

**Archiving is a `git mv`, never a delete, and every move leaves a pointer.**
See the repo `README.md` for the one archive convention this repo uses.
