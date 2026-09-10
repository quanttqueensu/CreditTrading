# CreditTrading

**QUANTT, Queen's University. Credit Trading Team.**
Team lead: Simon Jarvis

A systematic credit **closed-end-fund discount-reversion** strategy running live
on a $500,000 Interactive Brokers paper account. It places its own MOC orders on
a schedule, checks its own safety before every trade, records every fill, and
raises an alarm when something breaks.

**Nothing in this file is a number you may act on.** Every figure here is a
dated observation with the command that produced it. Re-run the command. The
house rule (`CLAUDE.md`, H14) is that no decision keys on a number written in a
document, and this README is a document.

## What is live, and where

There are **two working trees**, and this is the one you are probably reading in.
One command tells you which is which:

```bash
git worktree list
```

| tree | path | what it is |
|---|---|---|
| **dev** | `~/Desktop/2027/QUANTT/2027` | where work happens. Editing here is safe. Nothing here reaches a trading session. |
| **prod** | `~/prod/QUANTT` | a **git worktree detached at a tag**. The scheduler, the dashboard and every live ledger run here. **Nobody edits it.** |

Code reaches prod only as a tag, only via `ops/promote.sh <tag>`, only outside
the session window, and only if the tag passes the same steps the session runs.
The whole boundary is one line — `REPO` in
`~/Library/Application Support/quantt/launch_job.py`, which lives **outside** the
repo because macOS TCC denies launchd access to `~/Desktop`.

Since the split, `main` carries the work and tags are cut from it. To see what
prod is actually running:

```bash
git -C ~/prod/QUANTT describe --tags     # the tag prod is detached at
git -C ~/prod/QUANTT log -1 --oneline    # the commit behind it
```

## Start here

| Document | Read it for | PDF |
|---|---|---|
| [`docs/PROJECT_INTRO.md`](docs/PROJECT_INTRO.md) | What this is and who we are hiring. Two pages. | [PDF](docs/pdf/QUANTT-Project-Intro.pdf) |
| [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md) | The full technical reference and new member onboarding. **Carries a correction banner — read it.** | [PDF](docs/pdf/QUANTT-Infrastructure.pdf) |
| [`docs/SUMMER_2026_SUMMARY.md`](docs/SUMMER_2026_SUMMARY.md) | What we did over the summer and what the results actually were. | [PDF](docs/pdf/QUANTT-Summer-2026-Summary.pdf) |

New members: read `docs/INFRASTRUCTURE.md` Part 1. It takes about thirty minutes
and gets your machine running.

The PDFs are build output. Edit the markdown, then run `python3 docs/build_pdfs.py`
and commit both. That script needs pandoc and Google Chrome.

**`CLAUDE.md` is the working brief** — the hard rules on the order path, on data,
and on research. Read it before changing anything. Several documents in `docs/`
open with a correction banner saying what they get wrong; those banners are load
bearing and are listed in `CLAUDE.md` under "Documents that will mislead you".

## Background reading, in order

1. [`docs/HOW_WE_GOT_HERE.md`](docs/HOW_WE_GOT_HERE.md) — the story of the summer,
   including every wrong turn. Assumes no finance background.
2. [`docs/RESEARCH_AND_METHODOLOGY.md`](docs/RESEARCH_AND_METHODOLOGY.md) — how we
   decide whether a result is real. The most important document here, and it is
   dated 31 July: read its banner first.
3. [`docs/RESEARCH_STATE.md`](docs/RESEARCH_STATE.md) — the living state: what is
   deployed, what is dead and why, what is queued. **Its trial-counter table is
   canonical; its prose is not.**
4. [`results/AUDIT_2026-07-31.md`](results/AUDIT_2026-07-31.md) — the end-to-end
   audit that found three things wrong with the deployed strategy.
5. [`ops/AUTOMATION.md`](ops/AUTOMATION.md) — how the daily automation works and
   what stops it.

Work orders live in [`docs/prompts/`](docs/prompts/) and that directory has its
own index saying which are executed and which are queued.

## Quick setup

```bash
git clone https://github.com/quanttqueensu/CreditTrading.git
cd CreditTrading
python3 -m pip install -r requirements.txt
python3 -m pytest                    # the suite. Never quote a count from a doc
python3 scripts/cef/validate.py      # the validation battery, ~1 min
```

`validate.py` prints the point-in-time universe, a purged walk-forward, a block
bootstrap and a deflated Sharpe. **Read the numbers it prints. Do not read
numbers written here, or in any other document** — the panel extends every
session, so they move. This README used to promise two specific Sharpes; both
had drifted by the time anyone checked.

Two things to understand before you trust its verdict:

* **The deflated-Sharpe section's verdict depends on the trial count `N`**, and
  `N` is not a property of the strategy — it is how many specifications this
  desk has tried on this data source. It lives in the counter table in
  `docs/RESEARCH_STATE.md`, which is canonical, and the bar it sets is
  √(2 ln N). A larger `N` means a harsher haircut. At the CEF counter's true
  value the haircut is materially harsher than at the value this script
  historically assumed, and the printed verdict changes accordingly. **That is
  the multiple-testing correction working, not evidence about the edge** — the
  block bootstrap and the walk-forward are computed independently of `N` and are
  untouched by it. Read all four sections, not the last word of the last one.
* **It writes `results/cef/cef_validated_daily.parquet`, which is tracked.**
  Running it dirties the working tree. `git checkout --` that path when you are
  done, unless you meant to commit the new panel.

The `data/` folder is not in this repository — it is gigabytes, well past what
GitHub allows, and is gitignored. Measure it with `du -sh data`. See
`docs/INFRASTRUCTURE.md` section 1.4 for how to rebuild the free parts and what
has to be copied by hand. **Read the parquet, never grep it.**

Credentials live in `config/.env`, which is deliberately not committed. See
`docs/INFRASTRUCTURE.md` section 4.1 for the variables you need. **Never print,
copy or transmit a credential** — to test whether a key is set, print the
boolean, never the value.

## Where things live

```
src/deploy/      the live trading framework and the strategies
                 src/deploy/sleeves/cef_discount.py IS the strategy
src/backtest/    the backtest engine, lookahead guard, walk-forward
ops/             operations: preflight checks, halts, ledgers, reports
ops/specs/       frozen specs — governance objects, not config
scripts/         research and data scripts. NEVER on the live path
config/          cost models and secrets
results/         every output, one directory per research family
docs/            the written record; docs/prompts/ holds the work orders
dashboard/       the read-only monitor on :8787
data/            gigabytes of panels, gitignored, symlinked from prod (du -sh data)
```

## Where finished work goes

**One convention, four directories, and no fifth.** Archiving is a `git mv`,
never a delete, and every move leaves a pointer behind saying what replaced it.

| directory | holds | rule |
|---|---|---|
| `scripts/_archive/`, `ops/_archive/` | **code** | Kept because deleting it would destroy the sole record of a published number, an incident, or a decision. Nothing here is imported; nothing is on a live path. |
| `docs/_superseded/`, `docs/prompts/_superseded/` | **documents and work orders** | Superseded prose whose conclusions are fully absorbed elsewhere. Nothing here should be executed. |
| `ops/books/retired/` | **book specs** | Killed books. This one is **load-bearing, not cosmetic**: `_foreign_book_claims()` globs `ops/books/*.json` non-recursively, so a dead spec left in `ops/books/` still claims its symbols and can block a live book from arming. |
| `ops/books/_dryruns/` | **dry-run output** | Scratch ledgers from `--dry-run`. Never evidence of anything. |

The test, from `ops/_archive/README.md`: *what does deleting it cost if you are
wrong?* Sole code behind a quoted figure — archive it. A one-off whose output is
already committed — delete it, and say so in the commit message. **When in
doubt, archive**: a stale file costs a directory entry, deleting the only
evidence behind a published number costs you the ability to falsify it.

## Status

**Read it from the machine, not from here.**

```bash
python3 .claude/hooks/book_state.py -p     # live book state as JSON
python3 -m ops.doctor --quick              # can this machine run unattended?
ls ops/HALT*.md ~/prod/QUANTT/ops/HALT*.md 2>/dev/null   # active halts
```

Observations as of **2026-09-10**, each with the command that produced it — all
of these will be stale when you read them:

* **294 broker-confirmed executions** across three fill dates — 2026-07-31 (257),
  2026-09-01 (19), 2026-09-08 (18).
  `wc -l ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv`
* **The book armed on 5 of 29 CEF sessions.** Uptime, not signal quality, is the
  binding constraint.
  `grep -la 'ARMED:' ops/schedule/logs/cef_*.log | wc -l` over
  `ls ops/schedule/logs/cef_*.log | wc -l`
* **Only broker-confirmed fills count** toward any live statistic. Most ledger
  trade dates are modelled fills for sessions that never traded, and a modelled
  session is not evidence.

The open question that matters most is still whether trading costs are
survivable. The first live fills came in far worse than modelled; the diagnosis
was overnight market orders, the fix was **MOC**, and the fix has had one
session on record. `IR ≈ IC · TC · √BR` — the IC is settled, and the transfer
coefficient is the problem.
