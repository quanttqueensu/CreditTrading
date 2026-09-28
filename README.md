# CreditTrading

**QUANTT, Queen's University. Credit Trading Team.** Team lead: Simon Jarvis.

A systematic credit **closed-end-fund discount-reversion** strategy, being rebuilt
on **Alpaca paper**: one account per book, prod on a cloud VM. **Nothing trades
yet.** The plan from here to prod is [`docs/ROADMAP.md`](docs/ROADMAP.md).

This repository was cut to a clean slate on 2026-09-28: it holds only what the
Alpaca system needs. Everything earlier — the IBKR system, the archive, old research
— is in git at the tag `pre-clean-slate`, summarised in
[`docs/HISTORY.md`](docs/HISTORY.md).

**This file carries no status figures, on purpose.**

## Start here

```bash
python3 -m ops.orient     # ~3s — where you are and what is true right now
```

Then **[`docs/SYSTEM.md`](docs/SYSTEM.md)** (what we trade, how it runs, the
standing decisions), **[`docs/INDEX.md`](docs/INDEX.md)** (which file owns which
question) and **[`CLAUDE.md`](CLAUDE.md)** (the hard rules — for people as much as
agents). Research starts from [`docs/BRIEF.md`](docs/BRIEF.md).

## Setup

```bash
git clone https://github.com/quanttqueensu/CreditTrading.git
cd CreditTrading
python3 -m pip install -r requirements.txt
python3 -m pytest                    # never quote a count from a document
python3 -m ops.doc_audit --check     # do the documents still say true things?
```

Credentials live in `config/.env` (never committed): per book,
`ALPACA_<BOOK>_KEY_ID` and `ALPACA_<BOOK>_SECRET_KEY`. Never print, copy or
transmit one.

`data/` is gitignored. The CEF price and NAV panels are staged by
`python3 scripts/cef/stage_cef.py` and kept fresh by `scripts/cef/fetch_daily.py`;
distributions by `scripts/fetch_cef_distributions.py`.

## Where things live

```
quantt/          the Alpaca run package (so far: a read-only account probe)
src/deploy/      the strategy: sleeves/cef_discount.py IS the strategy; static_weights.py is b6
src/backtest/    the backtest engine, lookahead guard, walk-forward, cost model
scripts/cef/     the research harness (band_frontier, validate, diagnostics), spec reader, fetchers
ops/             orient, doc_audit, the network guard, halts, the NYSE calendar
ops/specs/       frozen specs — governance objects, not config
config/          cost model (and secrets, never committed)
results/cef/     the pre-registrations behind the live spec
docs/            SYSTEM, INDEX, ROADMAP, HISTORY, BRIEF, RESEARCH_STATE, REFERENCES
data/            panels, gitignored
```
