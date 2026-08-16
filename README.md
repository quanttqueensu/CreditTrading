# CreditTrading

**QUANTT, Queen's University. Credit Trading Team.**
Team lead: Simon Jarvis

A systematic credit strategy running live on a $500,000 Interactive Brokers paper
account. It places its own orders every weekday on a schedule, checks its own
safety before every trade, records every fill, and raises an alarm when something
breaks.

## Start here

| Document | Read it for | PDF |
|---|---|---|
| [`docs/PROJECT_INTRO.md`](docs/PROJECT_INTRO.md) | What this is and who we are hiring. Two pages. | [PDF](docs/pdf/QUANTT-Project-Intro.pdf) |
| [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md) | The full technical reference and new member onboarding. | [PDF](docs/pdf/QUANTT-Infrastructure.pdf) |
| [`docs/SUMMER_2026_SUMMARY.md`](docs/SUMMER_2026_SUMMARY.md) | What we did over the summer and what the results actually were. | [PDF](docs/pdf/QUANTT-Summer-2026-Summary.pdf) |

New members: read `docs/INFRASTRUCTURE.md` Part 1. It takes about thirty minutes
and gets your machine running.

The PDFs are build output. Edit the markdown, then run `python3 docs/build_pdfs.py`
and commit both. That script needs pandoc and Google Chrome.

## Background reading, in order

1. [`HOW_WE_GOT_HERE.md`](HOW_WE_GOT_HERE.md) — the story of the summer,
   including every wrong turn. Assumes no finance background.
2. [`RESEARCH_AND_METHODOLOGY.md`](RESEARCH_AND_METHODOLOGY.md) — how we decide
   whether a result is real. The most important document here.
3. [`RESEARCH_STATE.md`](RESEARCH_STATE.md) — the living state of the project:
   what is deployed, what is dead and why, what is queued next.
4. [`results/AUDIT_2026-07-31.md`](results/AUDIT_2026-07-31.md) — the end-to-end
   audit that found three things wrong with the deployed strategy.
5. [`ops/AUTOMATION.md`](ops/AUTOMATION.md) — how the daily automation works and
   what stops it.

## Quick setup

```bash
git clone https://github.com/quanttqueensu/CreditTrading.git
cd CreditTrading
python3 -m pip install -r requirements.txt
python3 scripts/cef/validate.py     # should print gross Sharpe ~1.26, net ~0.82
```

The `data/` folder is not in this repository. It is 3.8 GB, well past what GitHub
allows. See `docs/INFRASTRUCTURE.md` section 1.4 for how to rebuild the free parts
and what has to be copied by hand.

Credentials live in `config/.env`, which is deliberately not committed. See
section 4.1 for the variables you need.

## Where things live

```
src/deploy/      the live trading framework and the strategies
src/backtest/    the backtest engine, lookahead guard, walk-forward
ops/             operations: preflight checks, halts, ledgers, reports
scripts/         research and data scripts, grouped by family
config/          cost models and secrets
results/         every output, one directory per research family
docs/            the three documents listed above
```

## Status as of 2026-08-16

The strategy is deployed and passed its full validation battery. It has one day
of live trading (2026-07-31, 257 real executions) and has not traded since
2026-08-01 because the broker platform has been down. Data collection, reporting,
and monitoring have continued running cleanly throughout.

The open question that matters most is whether trading costs are survivable. Our
first live fills came in about nine times worse than modelled. We diagnosed the
cause, fixed it, and have not yet been able to test the fix.
