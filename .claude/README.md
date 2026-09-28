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
are, each Alpaca paper account's latest read-only snapshot, the live spec, panel
dates and trial counters — each beside the command that produced it, and
`UNMEASURED` with a reason where it cannot measure. `CLAUDE.md` holds the rules;
`docs/SYSTEM.md` what the system is and has decided; `docs/ROADMAP.md` the plan to
prod; `docs/INDEX.md` which file owns every other question.

## Hooks — advisory

| hook | event | what it does |
|---|---|---|
| `post_edit_check.py` | `PostToolUse(Edit\|Write)` | Never blocks. Flags the bug classes this repo has actually shipped, on the lines you just added. |
| `session_context.py` | `SessionStart` | Says whether anything trades (today: no live book), the Alpaca probe snapshots, and where to start. |
| `statusline.py` | status line | Model · git · context · **no live book** in red until a book trades. |
| `book_state.py` | *(library)* | The one reader behind the two above. Files and git only; no network, no keys. |

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

## Agents — specialist seats

Each runs in isolated context and returns a summary. Ask for one by name, or
describe the task and let Claude route.

| agent | seat |
|---|---|
| `alpha-finder` | generates return sources; names who loses before proposing |
| `beta-detector` | adversarial — tries to prove a result is an artifact or a risk premium |
| `unique-angle-researcher` | edges nobody is looking for: mechanical, calendar, regulatory |
| `execution-trader` | fills, slippage, auctions, venue rules, borrow. Owns TC |
| `portfolio-manager` | sizing, leverage, vol target, risk limits, deployment calls |
| `market-structure-analyst` | how the instruments actually trade — plumbing, from primary sources |
| `equity-research` | per-name fundamentals across the seventeen funds |
| `quant-reviewer` | lookahead, silent fallbacks, convention and unit errors |

## Maintaining this

- A convention Claude gets wrong twice → `CLAUDE.md`, or a `rules/` file if it is
  path-specific.
- A prompt you type a third time → a skill.
- Something that must happen every time → a hook, not an instruction.
- A number in any of these files is a **dated observation, not an input** (H14).
  Re-measure at run time.
