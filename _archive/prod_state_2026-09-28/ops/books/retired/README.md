# Retired book specs

Book JSONs for strategies that are **killed or otherwise cannot hold a position**.

## Why this directory exists

`IBKRBroker._foreign_book_claims()` (`src/deploy/broker/ibkr.py`) treats every
`*.json` in `ops/books/` carrying a `sleeves` list as a **live sibling book in the
shared paper account**, and adds that book's whole universe to the set of symbols
`arm()` must not adopt from the account net. That glob is deliberately
non-recursive, so a spec in this subdirectory is retained for reference without
being read as a live claimant.

Leaving a dead book in `ops/books/` is not harmless. A killed book claims symbols
it can never hold, which makes those symbols *contested* for the books that are
still trading. `arm()` then refuses to adopt them from the account net and demands
a per-sleeve ledger entry instead — and blocks the session when one is missing.

Measured 2026-09-10, with `credit_rv` (killed 2026-07-30) still in `ops/books/`:

| sleeve | contested with it | without it |
|---|---|---|
| `bench_b6_ew_credit` | 8 | 7 — frees **ANGL** |
| `null_trader` | 14 | 7 — frees BKLN, IGSB, JAAA, SJNK, SPHY, SRLN, VCSH |

ANGL is the symbol that halted `benchmarks_paper` on 2026-09-09 17:25:

    arm: BLOCKED ANGL: account holds +87 and bench_b6_ew_credit trades it,
    but so does another book and this sleeve's ledger has no entry

The "another book" was `credit_rv`, which has never held a share: no ledger
directory, no attribution entry, no broker fills, no schedule entry, no launchd
job. ANGL was contested by a book that died six weeks earlier.

## Rule

**When a strategy is killed, move its book JSON here in the same commit.** A
killed book that stays in `ops/books/` keeps voting on attribution for the books
that are still alive.

Retiring a book here does not touch its frozen spec (`ops/specs/*.frozen.json`),
its results, or its trial log. Reinstating one is a move back.

| file | strategy | killed | why |
|---|---|---|---|
| `credit_rv_book.json` | `credit_rv` | 2026-07-30 | D1 gross edge negative before costs (−0.19%/yr); sealed holdout net SR −1.44, t −2.29 |
