# The desk — how this repo is configured for Claude Code

Four layers, each doing what it is best at. `CLAUDE.md` is the always-on context;
everything here is the machinery around it. Rewritten for the 2026-09-28 clean
slate; the IBKR-era desk is at tag `pre-clean-slate`.

```
.claude/
├── settings.json   permissions + hooks + status line
├── hooks/          advisory scripts; nothing blocks
├── rules/          path-scoped context, loads on demand
├── skills/         invocable workflows  (/name)
└── agents/         specialist seats     (subagents)
```

**Before anything else, run `python3 -m ops.orient`** (~3s). It prints where you
are, each Alpaca paper account's latest read-only snapshot, the prod machine's
official daily P&L (Alpaca's end-of-day history) beside the three scores, the live
spec, panel dates and trial counters — each beside the command that produced it, and
`UNMEASURED` with a reason where it cannot measure. `CLAUDE.md` holds the rules;
`docs/SYSTEM.md` what the system is and has decided; `docs/ROADMAP.md` the plan to
prod; `docs/INDEX.md` which file owns every other question.

## Hooks — advisory

| hook | event | what it does |
|---|---|---|
| `post_edit_check.py` | `PostToolUse(Edit\|Write)` | Never blocks. Flags the bug classes this repo has actually shipped, on the lines you just added. |
| `session_context.py` | `SessionStart` | Which machine is prod and whether it is armed (a WARNING first if two are), its tag, last verdict and broker-confirmed equity, the probe snapshots' ages, and where to start. |
| `statusline.py` | status line | Model · git · context · prod machine, its arming and last verdict (`TWO ARMED` in red if two are). Never opens ssh: the VM part is the banner's reading, with its age. |
| `book_state.py` | *(library)* | The one reader behind the two above: `ops/prod_state.py` (launchd and files on the laptop; one read-only ssh call to the VM, 3 s budget, banner only), git, probe file names. No broker connection, no keys. |

**There is no blocking hook.** The order-path rules in `CLAUDE.md` are context,
not enforcement. The facts behind them are unchanged: an NYSE MOC cannot be
cancelled after 15:50 ET, and the trade phase is not idempotent — a second armed
run doubles the book.

## Rules — path-scoped, load only when relevant

| file | loads when you open |
|---|---|
| `research-harness.md` | `scripts/**`, `src/backtest/**` |
| `frozen-specs.md` | `ops/specs/**`, `ops/books/*.json`, `config/*.yaml` |
| `documents.md` | `docs/**`, `results/**`, `README.md` |

The Alpaca order path will get its own rule file when it is built
(`docs/ROADMAP.md` phase 4).

## Skills — workflows you or Claude can invoke

| skill | use it for |
|---|---|
| `/morning-brief` | data freshness, what the signal wants today, the Alpaca accounts |
| `/next-task` | what to work on, ranked against the actual constraints |
| `/graveyard` | the dead mechanisms and how each died — **read before proposing anything** |
| `/harness` | how to run a backtest that is comparable to existing numbers |
| `/repro` | reproduce a number before quoting it; check panel freshness |
| `/prereg` | write a pre-registration before a change trades |
| `/spec-change` | safely change a frozen-spec key |

## Agents — one research line

Rebuilt 2026-10-27 (`results/research/DESK_METHOD_2026-10-27.md`). Each seat is
one **station**: it owns one subtask, its output is judged on its own, and the
person who designs a test never runs it (López de Prado's "meta-strategy"
assembly line, `docs/REFERENCES.md` §12rm). Each seat runs in isolated context
and returns a summary. Ask for one by name, or describe the task and let Claude
route it. `/research-idea` runs the whole line.

```
quant-researcher → data-engineer → data-analyst → statistician ─┬─ PROCEED → /prereg → approved (CLAUDE.md)
   the question      data gathering   data audit     power gate  └─ UNDERPOWERED: redesign, nothing spent
                                                                   ↓
        backtest-engineer (or ml-engineer) → beta-detector + quant-reviewer + statistician → portfolio-manager + quant-trader → verdict
           one run, P&L series stored        the adversaries: claim, code, inference      what it adds; can it be traded    evidence + D-code
```

| station | agent | the seat |
|---|---|---|
| 1 | `quant-researcher` | mechanism, the loser, the negative control, the components; reads the graveyard as evidence |
| 2 | `data-engineer` | data gathering: sources, R2, point-in-time fields, survivorship, terms, one fetcher per series |
| 3 | `data-analyst` | data analytics: audit before any P&L (staleness, bad bars, alignment), feature profile; never touches returns |
| 4 | `statistician` | power before data (MDE, P(pass) per gate), both DSR bars, effective N, clustering, PRESENT / ABSENT / INCONCLUSIVE |
| 5 | `ml-engineer` | ML model implementation: in bounds or not, purged CV, triple-barrier, meta-labelling, every configuration a trial |
| 6 | `backtest-engineer` | runs the approved pre-registration once on the canonical harness; gross headline, cost grid, P&L series stored |
| 7 | `beta-detector` | adversary on the claim: artifact, control, risk premium, kept apart from "too weak to tell" |
| 7 | `quant-reviewer` | adversary on the code: lookahead, leakage, fallbacks, units, private statistics, pre-registration fidelity |
| 8 | `portfolio-manager` | sizing and allocation; judges each sleeve by its marginal contribution to the book |
| 9 | `quant-trader` | implementation into the strategy: costs, venue rules, borrow, rollout to shadow and paper, live against backtest |
| — | `market-structure-analyst` | domain, for every station: plumbing and per-name fund facts, from primary sources |

The line's statistics live in one place, `scripts/research/inference.py`, as its
backtests do in the canonical harness. The four event-desk seats on branch
`simon` (`event-scout`, `filings-analyst`, `deal-analyst`,
`credit-situations-analyst`) are domain seats that plug into station 1 and the
domain row. A new agent file becomes a subagent type only in a new session.

## Maintaining this

- A convention Claude gets wrong twice → `CLAUDE.md`, or a `rules/` file if it is
  path-specific.
- A prompt you type a third time → a skill.
- Something that must happen every time → a hook, not an instruction.
- A number in any of these files is a **dated observation, not an input** (H14).
  Re-measure at run time.
