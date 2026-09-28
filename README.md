# CreditTrading

**QUANTT, Queen's University. Credit Trading Team.** Team lead: Simon Jarvis.

A systematic credit **closed-end-fund discount-reversion** strategy. It ran on an
Interactive Brokers paper account until 2026-09-28 and is moving to **Alpaca
paper** — one account per book, prod on a cloud VM. **Nothing trades until the
Alpaca system in `quantt/` is built.** The plan:
[`results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md`](results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md).

**This file carries no status figures, on purpose.** Every number this repo once
wrote about its own state was contradicted by another document within days.

## Start here

```bash
python3 -m ops.orient     # ~3s — where you are and what is true right now
```

It reports where you are, what each Alpaca paper account's latest read-only
snapshot says, the live spec, panel dates and the trial counters — each beside
the command that produced it.

Then read **[`docs/SYSTEM.md`](docs/SYSTEM.md)**: what we trade, how the system
runs, what we know and what has been decided. **[`docs/INDEX.md`](docs/INDEX.md)**
says which file owns every other question. **[`CLAUDE.md`](CLAUDE.md)** holds the
hard rules — on the order path, on data and on research — and applies to people
as much as to agents. The theory and harness rules every piece of research
follows are in [`docs/BRIEF.md`](docs/BRIEF.md).

## Where it runs

There is no prod right now. The IBKR prod worktree and its launchd jobs were
retired on 2026-09-28 (`ibkr-final` tags the last commit of that era); the Alpaca
prod will be a cloud VM. `docs/SYSTEM.md` §4.

## Quick setup

```bash
git clone https://github.com/quanttqueensu/CreditTrading.git
cd CreditTrading
python3 -m pip install -r requirements.txt
python3 -m pytest                    # the suite; never quote a count from a document
python3 scripts/cef/validate.py --trials <CEF counter from docs/RESEARCH_STATE.md>
```

`--trials` is required: the deflated-Sharpe verdict depends on how many
specifications this desk has tried, and that count lives only in the counter
table. **Read the numbers `validate.py` prints, not numbers written anywhere.**
It writes `results/cef/cef_validated_daily.parquet`, which is tracked —
`git checkout --` that path afterwards unless you meant to commit it.

The `data/` folder is gigabytes and gitignored; `docs/INFRASTRUCTURE.md` §2.3
says how to rebuild the free parts and what must be copied by hand. Credentials
live in `config/.env`, never committed; never print, copy or transmit one.

## Where things live

```
src/deploy/      the trading framework; src/deploy/sleeves/cef_discount.py IS the strategy
quantt/          the new Alpaca run package (so far: a read-only account probe)
src/backtest/    the backtest engine, lookahead guard, walk-forward
ops/             operations: halts, ledgers, orient, doc_audit, the network guard
ops/specs/       frozen specs — governance objects, not config
scripts/         research and data scripts; never on the live path
config/          cost models and secrets
results/         dated findings, one directory per research family
docs/            SYSTEM.md, INDEX.md, RESEARCH_STATE.md, REFERENCES.md, INFRASTRUCTURE.md, BRIEF.md
_archive/        superseded documents and history, incl. all IBKR code — never evidence of current state
data/            panels, gitignored
```

## Where finished work goes

**`_archive/`, mirroring original paths, with `git mv`, never a delete.** Every
archived document opens with a banner naming what now owns its subject, and
`_archive/README.md` says what each is wrong about. The folder is gitignored so
search skips it, while everything in it stays tracked; `python3 -m ops.doc_audit`
checks every brick. The two older archive folders were folded in on 2026-09-14
(archived at `_archive/ops/_archive/`, which holds the band's revert spec, and
`_archive/scripts/_archive/`). Everything IBKR went there on 2026-09-28.

*What does deleting it cost if you are wrong?* When in doubt, archive.
