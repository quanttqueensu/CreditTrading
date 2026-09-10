# The desk — how this repo is configured for Claude Code

Four layers, each doing what it is best at. `CLAUDE.md` is the always-on context;
everything here is the machinery around it.

```
.claude/
├── settings.json            permissions + hooks + status line   (active)
├── settings.autonomy.json   proposed wider permissions          (NOT active — see below)
├── hooks/                   enforcement, deterministic
├── rules/                   path-scoped context, loads on demand
├── skills/                  invocable workflows  (/name)
└── agents/                  specialist seats     (subagents)
```

## Hooks — the only layer that is enforcement

`CLAUDE.md` and skills are *context*: Claude reads them and tries to follow them.
A hook fires regardless. Anything that must hold every time lives here.

| hook | event | what it does |
|---|---|---|
| `guard_order_path.py` | `PreToolUse(Bash)` | **Denies** any command that can transmit an order, read a credential, or destroy live state. 37 test cases, 0 failures. |
| `post_edit_check.py` | `PostToolUse(Edit\|Write)` | Advisory. Flags the four bug classes this repo has actually shipped, on the lines you just added. |
| `session_context.py` | `SessionStart` | Prints trading days since the last **broker-confirmed** fill, heartbeat problems, halt state. |
| `statusline.py` | status line | Model · git · context · cost · **fill −Nd**, colour-coded green/yellow/red. |
| `book_state.py` | *(library)* | One reader for live book state, shared by the three above and `/book-status`, so they can never disagree. |

**What the guard blocks** — the live session entry point, the `ops/schedule/run_*.sh`
wrappers, the launchd job, the MOC routing probe, `promote.sh`,
`cancel_open_orders.py`, `switch_broker.py`, `reset_epoch.py`, `rebuild_ledger.py`,
`launchctl load|unload`, halt clears and `rm` of `HALT.md`; reads of `config/.env`
and `~/ibc/config.ini`; deletion or truncation of `ops/books/**` and the shadow
ledgers.

**Why those and not more.** They are the actions that **cannot be undone**. An NYSE
MOC order cannot be cancelled after 15:50 ET, not even to correct a legitimate
error. The trade phase is not idempotent, so a second armed run stacks a second
order set that fills in the same auction and doubles the book. A fill not captured
before the daily TWS restart is gone permanently — there is no historical execution
endpoint. Everything else is deliberately open.

**The escape hatch is the point, not a limitation.** When Claude needs one of these
run, it says so and you type `! <command>` at the prompt. That takes two seconds and
leaves the decision, and the record of it, with a human.

Run the hook tests any time:

```bash
python3 .claude/hooks/guard_order_path.py < /dev/null   # should print nothing, exit 0
python3 .claude/hooks/book_state.py -p                  # live state as JSON
```

## Rules — path-scoped, load only when relevant

| file | loads when you open |
|---|---|
| `live-order-path.md` | `src/deploy/**`, `ops/**` |
| `research-harness.md` | `scripts/**`, `src/backtest/**`, `src/analysis/**`, `src/strategies/**`, `notebooks/**` |
| `frozen-specs.md` | `ops/specs/**`, `ops/books/*.json`, `config/*.yaml` |
| `dashboard.md` | `dashboard/**` |
| `documents.md` | `docs/**`, `results/**`, `README.md` |

This keeps `CLAUDE.md` short. Detail that only matters in one part of the tree does
not need to be in context for every session.

## Skills — workflows you or Claude can invoke

| skill | use it for |
|---|---|
| `/book-status` | is the book trading? Fills, heartbeat, halt, today's log |
| `/preflight` | run the gate and the plumbing check without trading |
| `/morning-brief` | pre-session: state, data freshness, constraints that bind |
| `/next-task` | what to work on, ranked against the actual constraints |
| `/graveyard` | the 13 dead mechanisms — **read before proposing anything** |
| `/harness` | how to run a backtest that is comparable to existing numbers |
| `/repro` | reproduce a number before quoting it; check panel freshness |
| `/prereg` | write a pre-registration before a change trades |
| `/spec-change` | safely change a frozen-spec key |
| `/fill-audit` | what execution actually costs, split by session and method |
| `/dashboard-ui` | add or rework a dashboard panel |
| `/incident` | diagnose and write up a live failure |

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
| `dashboard-designer` | dashboard information architecture and build |
| `ops-watchdog` | why the book is not trading |

## Autonomy

`settings.json` is deliberately permissive on everything reversible and stops only
at the irreversible broker surface.

`settings.autonomy.json` widens it further — `Bash(python3 *)`, edits across the
tree, the primary data sources this desk cites — so a session can work overnight
without stopping for approvals. **It is not active.** Claude Code's classifier
blocks an agent from writing its own broad allowlist, which is correct, so applying
it is a deliberate human act:

- open `/permissions` and add the entries, or
- paste its `permissions` block into `.claude/settings.json`.

It does **not** open the order path; that stays behind the hook. To lift that too,
delete the `PreToolUse` block from `settings.json` — knowingly.

## Maintaining this

- A convention Claude gets wrong twice → `CLAUDE.md`, or a `rules/` file if it is
  path-specific.
- A prompt you type a third time → a skill.
- Something that must happen every time → a hook, not an instruction.
- A number in any of these files is a **dated observation, not an input** (H14).
  Re-measure at run time.
