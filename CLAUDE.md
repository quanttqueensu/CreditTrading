# QUANTT — Credit Trading

A systematic **credit closed-end-fund discount-reversion** book, moving from IBKR
to **Alpaca paper** (team lead, 2026-09-28): one paper account per book, prod on a
cloud VM, MOC orders on a schedule. Team lead: Simon Jarvis. Paper indefinitely —
a competition track record, judged on absolute return under a vol cap.

**Right now nothing trades.** IBKR was retired on 2026-09-28 and the repo was cut
to a clean slate the same day; the Alpaca system is being built in `quantt/`. **The
plan, step by step, is `docs/ROADMAP.md`.**

**This file holds the rules, which do not rot. It holds no figures about the
book, which do.** Start every session with:

```bash
python3 -m ops.orient      # ~3s: where you are, the Alpaca accounts, spec, counters, panels
```

Then **`docs/SYSTEM.md`** — what we trade, how it runs, what we know, what has
been decided. **`docs/INDEX.md`** says which file owns every other question.
Read `docs/BRIEF.md` before any research.

| you want | ask |
|---|---|
| any number about the accounts, the spec or the counters | `python3 -m ops.orient` (a section that cannot measure says `UNMEASURED`, never a guess) |
| what the system is, how it runs, the standing decisions | `docs/SYSTEM.md` |
| trial counters, D1–D7, what is dead | `docs/RESEARCH_STATE.md` |
| whether a document still says true things | `python3 -m ops.doc_audit` |

**There is no archive.** Everything from before 2026-09-28 — the IBKR system, the
research notes, the old research families — lives only in git at the tag
`pre-clean-slate` (`docs/HISTORY.md` says what was there and how to recover it).
It is provenance, never evidence of what is true now. Do not rebuild an `pre-clean-slate:_archive/`
folder: delete what is dead, and let git keep it.

---

## Hard rules — the order path

**Not enforced by any hook.** Treat them as absolute anyway: each names an action
that cannot be undone.

1. **Never transmit an order on your own initiative.** Anything that can send,
   replace or cancel an order at a broker runs only when the team lead has asked
   for it in the session — and even then, **show the concrete order list and get
   an explicit go before transmitting.** (Until 2026-09-28 the rule was "the human
   runs it with `!`"; the team lead asked agents to run the migration commands
   themselves, and this is that instruction made durable.)
2. **The trade phase is not idempotent, and the broker does not dedupe.** Open
   positions exclude unfilled MOC orders, so a second armed run's orders fill in
   the same auction and the book doubles. At Alpaca, `client_order_id` is unique
   only among *active* orders [V: docs, 2026-09-28]. Any runner must refuse before
   transmitting if the broker shows a set already headed for an unclosed auction,
   and must record that it started before its first order goes.
3. **Order type stays MOC** (Alpaca `time_in_force=cls`). Overnight market orders
   realised 100.5bp against a 32.6bp breakeven on 2026-07-31. Alpaca rejects `cls`
   entries from 15:50 ET; NYSE cancels no MOC after 15:50.
4. **`DRY_RUN=1` is a human hard halt and always wins.**
5. **Never print, copy or transmit credentials.** To test whether a key is set,
   print the boolean, never the value. Alpaca keys live in `config/.env`
   (`ALPACA_<BOOK>_KEY_ID` / `_SECRET_KEY`), which agents never read.

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
- **Any monitor is read-only.** The IBKR-era dashboard is deleted; the team
  lead will have a new one built later. No code path from a monitor transmits an
  order.
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
  last date first; (2) **Alpaca through its API**, the authority on our accounts and
  on what is tradable and shortable (`python3 -m quantt.broker.alpaca_probe`,
  read-only); (3) a **primary external source you actually fetched** —
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
- **Turnover-matched comparisons only** (within 5% turn/yr). **Every table shows
  gross P&L as the headline** — the paper account is scored on gross P&L with no
  borrow or execution cost (team lead, D19/D20, 2026-09-15) — **and the cost grid
  5 / 15 / 30bp beside it as the real-money view, labelled, never mixed into one
  column** (team lead, 2026-09-28). Say whether the answer flips sign across the
  grid. Borrow is charged separately and labelled.
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
  toward any live statistic. On Alpaca paper, record both the fill Alpaca reports
  (the official record) and the P&L at the official closing-auction print, labelled
  separately (team lead, 2026-09-28) — paper does not simulate the auction.
- **No decision rule may key on a number written in a document** (H14). Re-measure
  at run time and say what you do under either outcome.
- **Check the graveyard before proposing anything** (`/graveyard`). The most
  common cause of death is a stale-price artifact; the second, a control group
  scoring as well as the treatment.

## Commands

```bash
python3 -m ops.orient                  # first, every session
python3 -m pytest                      # pytest.ini scopes collection; never quote a count
python3 -m ops.doc_audit               # do the documents still say true things?
python3 -m quantt.broker.alpaca_probe --check-keys   # which Alpaca keys are SET (no network)
python3 -m quantt.broker.alpaca_probe  # read-only snapshot of each paper account
python3 scripts/cef/band_frontier.py   # the trading-policy frontier
python3 scripts/cef/plan_diagnostics.py  # IC, kappa, PCA, ADV, vol scalar
python3 .claude/hooks/book_state.py -p # what the banner and status line read
```

## Layout

`src/deploy/sleeves/cef_discount.py` **is** the strategy. `ops/specs/*.frozen.json`
are governance objects, not config. `quantt/` is the new Alpaca run package.
`scripts/` is research and is never on the live path. `data/` is gigabytes and
gitignored — read the parquet, never grep it. `.claude/rules/` loads path-scoped
rules when you open matching files.

## Where it runs

**There is no prod right now.** The IBKR prod worktree (`~/prod/QUANTT`) and its
launchd jobs were retired on 2026-09-28; the jobs are unloaded and the tree's
state is at tag `pre-clean-slate` (`pre-clean-slate:_archive/prod_state_2026-09-28/`). The Alpaca
prod will run on a cloud VM (team lead, 2026-09-28) and does not exist yet; its
rule is that it holds this repository at a tag and nothing else
(`docs/ROADMAP.md` phase 6). `ibkr-final` tags the last IBKR-era commit.

## Landmines

1. **Alpaca paper does not simulate the closing auction.** Staff say paper fills
   MOC at the current quote [V: forum staff post, 2026-09-28]. Paper also charges
   no borrow, no dividends and no regulatory fees [V: docs]. Paper P&L on this
   book is structurally different from a live auction fill; score both (research
   rules above).
2. **Alpaca rejects opposite-side orders in one symbol as wash trades**, paper
   included [V: docs]. That is why each book has its own account. Within a book,
   net each symbol into one order.
3. **Fractional shares cannot be shorted or sent `cls`** [V: docs]. Whole shares
   only.
4. **A long→short flip may need two orders** (close, then open) [U: 2020 staff
   post; test it on paper before relying on either answer].
5. **`borrow_status` changes daily.** A probe snapshot is true on its date only.
6. **HYT lags the price panel by a day.** `px.iloc[-1]` can be NaN for a name;
   use `px.ffill().iloc[-1]` for that name's own last close.
7. **`PositionTarget.weight` is signed.** Do not multiply by the side sign again.
8. **The years before 2013 are flat** — too few names clear the ADV filter — so
   full-sample turnover is diluted and full-sample Sharpes are depressed. Report
   by era (H5).
9. **The live sleeve decides on `data/`.** A research script that rewrites a
   panel there rewrites what the book trades on. Write research output elsewhere.
10. **Use `ib_async`, never bare `ib_insync`**, if IBKR code is ever revived from
    tag `pre-clean-slate` — the latter hangs forever on Python 3.12+. orient
    HYGIENE counts unguarded imports by AST.

## Tests

**Never quote a test count; run `python3 -m pytest`.** A green suite says little
about the code that places orders. `pytest.ini` scopes collection because a
script that opened a live broker connection at import (since deleted) was once
collected by a bare run. A directory is safe to add to `testpaths` only if
nothing it imports opens a socket at import time. The root `conftest.py` blocks
every network connection during tests (`ops/netguard.py`).

## The desk

`.claude/README.md` is the map. `.claude/hooks/` is **advisory** — the
SessionStart banner, a post-edit check and the status line; nothing blocks.

Skills: `/morning-brief`, `/next-task`, `/graveyard`, `/harness`, `/repro`,
`/prereg`, `/spec-change`. (The IBKR-run skills were deleted 2026-09-28; they are
at tag `pre-clean-slate` under `pre-clean-slate:_archive/claude_layer/`.)

Subagents: `alpha-finder`, `beta-detector`, `unique-angle-researcher`,
`execution-trader`, `portfolio-manager`, `market-structure-analyst`,
`equity-research`, `quant-reviewer`.

**Options are closed, and it is recorded rather than remembered**:
`docs/SYSTEM.md` §5.
