# QUANTT — Credit Trading

A systematic **credit closed-end-fund discount-reversion** book on an IBKR paper
account, placing its own MOC orders on a schedule. Team lead: Simon Jarvis.
Paper indefinitely — a competition track record, judged on absolute return under
a vol cap.

**This file holds the rules, which do not rot. It holds no figures about the
book, which do.** Start every session with:

```bash
python3 -m ops.orient      # ~3s: both trees, what prod lacks, halts, fills, uptime, spec, counters, panels
```

Then **`docs/SYSTEM.md`** — what we trade, how it runs, what we know, what has
been decided. **`docs/INDEX.md`** says which file owns every other question.
Read `docs/prompts/00_BRIEF.md` before any research.

| you want | ask |
|---|---|
| any number about the book, the spec, the trees or the counters | `python3 -m ops.orient` (a section that cannot measure says `UNMEASURED`, never a guess) |
| what the system is, how it runs, the standing decisions | `docs/SYSTEM.md` |
| trial counters, D1–D7, what is dead | `docs/RESEARCH_STATE.md` |
| whether a document still says true things | `python3 -m ops.doc_audit` |

**`_archive/` is the record of what we did, never evidence of what is true.**
It is tracked but gitignored, so `rg` and `grep -r` skip it unless pointed at it;
`find` and `git grep` do not, so every file there opens with an ARCHIVED banner.
Cite it as provenance only, never as authority; `git add -f` new files; never
create a `CLAUDE.md` inside it. The rules: `_archive/README.md`.

---

## Hard rules — the order path

**Not enforced by any hook** (the blocking `PreToolUse` hook was removed
2026-09-10 at the team lead's instruction). Treat them as absolute anyway: each
names an action that cannot be undone.

1. **Never run anything that can transmit an order.** The live session entry
   point (`python3 -m src.deploy.run_book`), the launchd jobs and
   `launch_job.py`, the old shell wrappers (archived in
   `ops/_archive/schedule_pre_w3_2026-09-13/`, still live if run), the MOC routing
   probe, the promote/cancel/reset-epoch/switch-broker tools, `launchctl
   load|unload|bootstrap|bootout`. Propose it, explain why, and let the human run
   it with `! <command>`.
2. **The trade phase is not idempotent, and the broker does not dedupe.** `arm()`
   re-seeds from `ib.positions()`, which excludes unfilled MOC orders, so a second
   armed run's orders fill in the same auction and the book doubles.
   `place_targets` now refuses before transmitting if the broker or the order map
   shows a set already headed for an unclosed auction (`ops/pending_orders.py`).
   That is a backstop, not permission.
3. **Order type stays MOC.** Overnight market orders realised 100.5bp against a
   32.6bp breakeven on 2026-07-31. NYSE MOC cannot be cancelled after 15:50 ET,
   not even to correct a legitimate error.
4. **`DRY_RUN=1` is a human hard halt and always wins.** `DRY_RUN=0` means "trade
   *if preflight agrees*", not "trade".
5. **Never print, copy or transmit credentials.** To test whether a key is set,
   print the boolean, never the value.

## Hard rules — code

- **No silent fallbacks.** Never `except: pass`, never `fillna()` an invented
  value, never a default for missing data, never degrade to a simpler method.
  **Raise, naming what was missing.** Shipped examples sized every displayed
  target against an invented $500k book, and charged an unmeasured name a median
  fee inside a confident-looking total — both dormant for months.
- **No lookahead.** Every estimated quantity uses data strictly before the date
  it is used on. State the alignment in a comment. Assert it at runtime.
- **A new frozen-spec key must default to current behaviour**, and the no-op must
  be *proved* by diffing sleeve output byte-for-byte with the key absent. Use
  `/spec-change`.
- **The frozen spec is the only authority on a live parameter.** Read it (through
  `scripts/cef/spec.py`); never write the literal. Scripts once baselined against
  a band width the book had left, and nothing errored.
- **The dashboard is read-only.** Exactly one non-GET route (`/api/connect`). No
  code path from it transmits an order.
- **Docstrings explain WHY.** Most of this codebase's knowledge, especially its
  incident history, lives in them. Match that density.
- **Never hand-copy a data series.** Anything fetched gets a fetcher and a source
  note in `docs/REFERENCES.md`.
- **Write a test with any change to the live path**, and check it fails against
  the old behaviour before keeping it.

## Hard rules — data

**Confident wrong numbers have cost this desk more than missing ones. Assume your
recall of any specific figure is wrong until you have fetched it.**

- **Never invent a number.** Not a placeholder, not "roughly", not a plausible
  value to keep an analysis moving. If you do not have it, the output is a stated
  gap. **A number without provenance is a rumour.**
- **Real data or nothing**, in this order: (1) the repo's own panels — check the
  last date first; (2) **IBKR through the gateway**, the authority on our account
  and instruments; (3) a **primary external source you actually fetched** —
  EDGAR, FINRA, FRED, an exchange rulebook, a fund filing, the paper itself;
  (4) a script in this repo, **re-run now**. If none yields it: say so, name what
  you tried, and stop.
- **Synthetic data tests whether a method behaves, never a claim about the
  market.** The test: is the conclusion about our code, or about the world?
- **Double-check anything that drives a decision** — a second method, an
  independent source, sign and magnitude. When two sources disagree, **do not
  average and do not pick one silently**: report it and say which you used.
- **Label provenance on every figure**: `[V]` verified, `[S]` sourced but not
  re-read, `[U]` uncertain — as `docs/REFERENCES.md` does.
- **Stale is a form of wrong.** State a panel's last date in any note that uses it.
- Recalled figures on this desk have been wrong in every direction — a statistic
  that existed in no source, a unanimous ruling that was 6–3, a finding recalled
  backwards. Fetch it.

## Hard rules — research

- **Execution convention is `shift(2)`**: decide at *t*, MOC fill at *t+1*, earn
  the *t+2* return. Canonical implementation: `evaluate()` in
  `scripts/cef/band_frontier.py`. **Do not build a new backtester** — extend that
  one, visibly. `/harness`.
- **Turnover-matched comparisons only** (within 5% turn/yr). **Cost grid
  5 / 15 / 30bp on every table**; the answer must not flip sign across it. Borrow
  is charged separately and labelled.
- **No sweeping and picking.** Derive a parameter, then check it lands on a
  plateau. The argmax of a swept `z_window` column failed out of sample within
  hours.
- **Count trials.** Two counters, CEF and GAMMA, each with its own deflated-Sharpe
  bar √(2 ln N). Read them from the counter table in `docs/RESEARCH_STATE.md`
  (orient TRIALS derives the bar), and update that table **in the same commit as
  the trial**.
- **Holdouts are sealed and opened once**: the untouched CEFs outside the
  deployed universe (trading any of them consumes the set), and a **2023-01-01
  time holdout**.
- **Pre-register before the session that trades it** (`/prereg`).
- **Modelled sessions are not evidence.** Only broker-confirmed fills count
  toward any live statistic.
- **No decision rule may key on a number written in a document** (H14). Re-measure
  at run time and say what you do under either outcome.
- **Check the graveyard before proposing anything** (`/graveyard`). The most
  common cause of death is a stale-price artifact; the second, a control group
  scoring as well as the treatment.

## Commands

```bash
python3 -m ops.orient                  # first, every session
python3 -m pytest                      # pytest.ini scopes collection; never quote a count
python3 -m ops.session_uptime          # is the book arming? (both log trees)
python3 -m ops.doc_audit               # do the documents still say true things?
python3 -m ops.prompt_status           # where each work order stands
python3 -m ops.gamma_status            # the options programme
python3 -m ops.doctor --quick          # can this machine run unattended?
python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live
python3 scripts/cef/band_frontier.py   # the trading-policy frontier
python3 scripts/cef/plan_diagnostics.py  # IC, kappa, PCA, ADV, vol scalar
python3 dashboard/server.py            # read-only monitor on :8787
python3 .claude/hooks/book_state.py -p # live book state as JSON, both trees
```

## Layout

`src/deploy/sleeves/cef_discount.py` **is** the strategy. `ops/specs/*.frozen.json`
are governance objects, not config. `scripts/` is research and is never on the
live path. `data/` is gigabytes and gitignored — read the parquet, never grep it.
`.claude/rules/` loads path-scoped rules when you open matching files.

## Two trees, and halts

**This working tree is dev. Prod is `~/prod/QUANTT`, a git worktree detached at a
tag** — `git worktree list` shows it; `git branch` never will. Nothing edited
here reaches a session until it is tagged and promoted with `ops/promote.sh`, and
orient TREES says what prod lacks. Detached HEAD on prod is the intended state.
The details are `docs/SYSTEM.md` §4.1.

**Halts are written in prod and are untracked**, so `ls ops/HALT*.md` in dev
shows nothing while prod is halted. Read both trees (orient HALTS). A global
`ops/HALT.md` blocks every book; `ops/HALT_<book>.md` blocks one. Clear with
attribution via `clear_halt`, after reading every entry in the file and checking
it against the broker, not the ledger. `docs/SYSTEM.md` §4.4.

## Landmines

1. **`launch_job.py` lives outside the repo** (`~/Library/Application Support/quantt/`)
   because macOS TCC denies launchd `~/Desktop`, and its `REPO` line is the whole
   prod/dev boundary. Do not move it, and do not "fix" it.
2. **What launchd runs is what is loaded**, not what is in `ops/schedule/`:
   `launchctl list | grep quantt` and the plists in `~/Library/LaunchAgents`.
3. **The ledger is a local reconstruction; the account is the fact.** `arm()`'s
   re-seed from the broker cannot reach a symbol the broker holds none of (IBKR
   emits no row for a flattened position), so a stale ledger quantity there goes
   straight into order sizing. And `_sleeve_nav` swallows any exception and sizes
   against registered capital instead of marked NAV, silently.
   `results/ops/LEDGER_DIVERGENCE_2026-09-10.md`.
4. **HYT lags the price panel by a day.** `px.iloc[-1]` can be NaN for a name;
   use `px.ffill().iloc[-1]` for that name's own last close.
5. **`PositionTarget.weight` is signed.** Do not multiply by the side sign again.
6. **The years before 2013 are flat** — too few names clear the ADV filter — so
   full-sample turnover is diluted and full-sample Sharpes are depressed. Report
   by era (H5).
7. **Several books share one IBKR account with overlapping tickers.** Attribution
   is per sleeve; never take a symbol from the account net. `ops/books/retired/`
   must not move. `docs/SYSTEM.md` §4.3.
8. **Use `ib_async`, never bare `ib_insync`** — the latter hangs forever in its
   asyncio handshake on Python 3.12+ and looks exactly like a dead broker. The
   safe shape is `try: ib_async / except ImportError: ib_insync`. orient HYGIENE
   names every unguarded import by AST (a grep cannot express the check); do not
   add one.
9. **Prod prices from dev's `data/`.** `~/prod/QUANTT/data` is a symlink to this
   tree's `data/`, so a research script that rewrites a panel here rewrites what
   the live sleeve decides on. Write research output somewhere else.

## Tests

**Never quote a test count; run `python3 -m pytest`.** A green suite says little
about the code that places orders. `pytest.ini` scopes collection because
`scripts/audit/moc_routing_test.py` opens a live broker connection at import, and
a bare collection once reached for the order path. A directory is safe to add to
`testpaths` only if nothing it imports opens a socket at import time; never add
`scripts/audit/`.

## The desk

`.claude/README.md` is the map. `.claude/hooks/` is **advisory** — the
SessionStart banner, a post-edit check and the status line; nothing blocks.

Skills: `/book-status`, `/preflight`, `/morning-brief`, `/next-task`,
`/graveyard`, `/harness`, `/repro`, `/prereg`, `/spec-change`, `/fill-audit`,
`/dashboard-ui`, `/incident`.

Subagents: `alpha-finder`, `beta-detector`, `unique-angle-researcher`,
`execution-trader`, `portfolio-manager`, `market-structure-analyst`,
`equity-research`, `quant-reviewer`, `dashboard-designer`, `ops-watchdog`.

**Options are closed, and it is recorded rather than remembered**:
`docs/SYSTEM.md` §5 and `python3 -m ops.gamma_status`.
