# QUANTT — Credit Trading

A systematic **credit closed-end-fund discount-reversion** book running live on a
$500,000 IBKR paper account (DUQ199038), placing its own MOC orders on a schedule.
Team lead: Simon Jarvis. Paper indefinitely — the deliverable is a competition
track record, judged on **absolute return** with a **20% vol cap**.

**The alpha is probably real. It is NOT "settled", and this line used to say it
was.** Re-measured 2026-09-10 with `python3 scripts/cef/validate.py --trials 48`
(panel to 2026-09-09, T=5,455): **8/9** purged walk-forward blocks positive —
not 9/9 — worst block **−0.15** (2018-01-05..2020-03-06), median 1.05; gross
Sharpe **1.27**, net **0.83**; bootstrap P(SR≤0) = **0.000%**. The 9/9 and the
"gross 1.23" in this line do not reproduce. Run the command; do not quote these.

**And it fails its own deflated-Sharpe bar at the real trial count.** DSR is
**0.870 (FAIL)** at the CEF counter of **48**. It printed 0.963 PASS for months
only because `validate.py` hard-coded `N_SPECS_TRIED = 10`; that literal is now
a required `--trials` argument with no default. The verdict flips straight
through MARGINAL between the two counts, so **the trial count is not a footnote
to this claim, it is the claim.** Nothing here says the edge is fake — the
bootstrap and 8/9 blocks stand, DSR is a deliberately harsh multiple-testing
haircut, and out-of-sample the sealed holdout opened at 1.75. It says the honest
summary is "survives every test but the multiplicity correction, at N=48", and
that the 49th trial makes the bar harder still.

**The problem is capture, and operations.** `IR ≈ IC · TC · √BR`. Our IC is good.
Our transfer coefficient is **~37%** — gross Sharpe ~1.2 becomes net ~0.43 once
costs and measured borrow are charged. Our effective breadth is **1.17** against a
nominal 17 names, because 92.5% of book variance is one factor (muni vs taxable).
And the book has armed on **5 of 29** CEF sessions (measured 2026-09-10:
`grep -la 'ARMED:' ops/schedule/logs/cef_*.log | wc -l` over
`ls ops/schedule/logs/cef_*.log | wc -l`; the "3 of 26" this line carried until
then was never dated and was wrong). Work that raises TC or uptime beats work
that sharpens IC, every time.

Read `docs/prompts/00_BRIEF.md` before any research. It is the standing brief and
every prompt in that directory opens with it.

---

## Hard rules — the order path

**These are not enforced.** The `PreToolUse` hook that blocked them was removed on
2026-09-10 at the team lead's instruction, so they hold only as far as they are
followed. Treat them as absolute anyway: each names an action that **cannot be
undone**, and there is now nothing behind them.

1. **Never run anything that can transmit an order.** The live session entry point,
   the `ops/schedule/run_*.sh` wrappers, the launchd job, the MOC routing probe,
   the promote/cancel/reset/switch-broker tools, `launchctl load|unload`. Propose
   it, explain why, and let the human run it with `! <command>`.
2. **The trade phase is not idempotent.** There is no dedupe at the broker. A
   second armed run stacks a second order set, and `arm()` re-seeds from
   `ib.positions()`, which do *not* include unfilled MOC orders — so both sets fill
   in the same closing auction and the book doubles.
3. **Order type stays MOC.** Overnight market orders realised **100.5bp** against a
   **32.6bp** breakeven on 2026-07-31. The one MOC session on record realised
   2.8bp. NYSE MOC cannot be cancelled after 15:50 ET, not even to correct a
   legitimate error.
4. **`DRY_RUN=1` is a human hard halt and always wins.** `DRY_RUN=0` means "trade
   *if preflight agrees*", not "trade".
5. **Never print, copy or transmit credentials.** To test whether a key is set,
   print the boolean, never the value.

## Hard rules — code

- **NO SILENT FALLBACKS.** Never `except: pass`, never `fillna()` an invented
  value, never a default for missing data, never degrade to a simpler method when
  something fails. **Raise, naming what was missing.** Two shipped examples:
  `nav_now = _nav_last(...) or 500000.0` sized every displayed target against an
  invented book, and `fee.fillna(fee.median())` charged an unmeasured name
  0.83%/yr inside a confident-looking total. Both were dormant for months — which
  is exactly what makes them dangerous.
- **No lookahead.** Every estimated quantity uses data strictly before the date it
  is used on. State the alignment in a comment. Assert it at runtime.
- **A new frozen-spec key must default to current behaviour**, and the no-op must
  be *proved* by diffing sleeve output byte-for-byte with the key absent.
- **The dashboard is read-only.** Exactly one non-GET route (`/api/connect`). No
  code path from it transmits an order. Keep it that way.
- **Docstrings explain WHY.** Most of this codebase's real knowledge, especially
  its incident history, lives in them. Match that density.
- **Never hand-copy a data series.** Anything fetched gets a fetcher and a source
  note in `docs/REFERENCES.md`.

## Hard rules — data

**Confident wrong numbers have cost this desk more than missing ones. Assume your
recall of any specific figure is wrong until you have fetched it.**

- **Never invent a number.** Not a placeholder, not "roughly", not "typically
  around", not a plausible value to keep an analysis moving. If you do not have
  it, you do not have it, and the output is a stated gap. **A number without
  provenance is a rumour.**
- **Real data or nothing**, in this order: (1) the repo's own panels — check the
  last date first, several lag by weeks; (2) **IBKR through the gateway**, the
  authority on our account and the instruments we trade; (3) a **primary external
  source you actually fetched** — EDGAR, FINRA, FRED, an exchange rulebook, a
  fund filing, Cboe's endpoints, the paper itself; (4) a script in this repo,
  **re-run now**, not a number copied from an old note. If none of those yields
  it: say so, name what you tried, and stop.
- **Synthetic data has exactly one legitimate use: testing whether a *method*
  behaves** — an estimator's bias, a formula's algebra, a controller's stability.
  **Never to support a claim about the market.** The test: *is the conclusion
  about our code, or about the world?*
- **Double-check anything that drives a decision.** Recompute it a second way,
  cross-check against an independent source, sanity-check sign and magnitude.
  When two sources disagree, **do not average them and do not pick one
  silently** — report the disagreement and say which you used.
- **Label provenance on every figure**: `[V]` verified / `[S]` sourced but not
  re-read / `[U]` uncertain, as `docs/REFERENCES.md` does.
- **Stale is a form of wrong.** State a panel's last date in any note that uses
  it.

Five recent examples, every one of which would have propagated into a decision:
a variance-risk-premium figure recalled as −74% exists in no reachable source; a
predictive R² recalled as "low-to-mid teens" is **6.82%**; a Supreme Court ruling
recalled as unanimous was **6–3**; a finding recalled as "open-ending halves the
discount" is backwards — it *eliminates* it; and a return-convention bias
asserted at "about 2%/yr" measured **−0.01%/yr**.

## Hard rules — research

- **Execution convention is `shift(2)`**: decide at *t*, MOC fill at *t+1*, earn
  the *t+2* return. Anything scored differently is not comparable to any number in
  this repo. Canonical implementation: `evaluate()` in
  `scripts/cef/band_frontier.py`. **Do not build a new backtester** — extend that
  one, visibly.
- **Turnover-matched comparisons only.** A construction that trades more looks
  better gross and worse net; neither is the point. Match turn/yr within 5%, then
  compare there.
- **Cost grid 5 / 15 / 30bp on every table.** The answer must not flip sign across
  it. Borrow is charged separately and labelled.
- **No sweeping and picking.** Derive a parameter, then check it lands on a
  plateau. `z_window = 63` was the argmax of a swept column and failed out of
  sample; that episode is the most instructive event in this project's history.
- **Count trials.** Two counters, each with its own deflated-Sharpe bar √(2 ln N):
  **CEF = 48**, **GAMMA = 0**. Update `docs/RESEARCH_STATE.md` in the *same commit*
  as the trial, never at the end of a session.
- **Holdouts are sealed and opened once.** The 27 untouched CEFs are one — trading
  any of them consumes it. A **2023-01-01 time holdout** is the other.
- **Modelled sessions are not evidence.** Only broker-confirmed fills count toward
  any live statistic. 22 of 24 ledger trade dates are modelled fills for sessions
  that never traded.
- **No decision rule may key on a number written in a document.** Every figure in
  these docs is a dated observation with a method, not an input. Re-measure at run
  time and say what you do under either outcome.

## Commands

```bash
python3 -m pytest                                 # ~5s. pytest.ini scopes collection — see the file
python3 -m ops.doctor --quick                     # can this machine run unattended?
python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live
python3 scripts/cef/band_frontier.py              # the trading-policy frontier
python3 scripts/cef/plan_diagnostics.py           # reproduces every number in docs/PLAN.md
python3 dashboard/server.py                       # read-only monitor on :8787
python3 .claude/hooks/book_state.py -p            # live book state as JSON
```

## Layout

Directory names are self-describing; these four facts are not.
`src/deploy/sleeves/cef_discount.py` **is** the strategy. `ops/specs/*.frozen.json`
are governance objects, not config. `scripts/` is research and is **never** on the
live path. `data/` is 3.9 GB and gitignored — read the parquet, never grep it.

## Documents that will mislead you

Audited 2026-09-10 by four parallel agents. The trap is what each says without
its banner.

**Do not trust this section to have banner-ed them.** It claimed all six carried
one; re-measured 2026-09-10 ~13:00, **two do not** — `docs/RESEARCH_STATE.md`
(header still reads "Last updated: 2026-07-31" with no warning) and
`docs/PER_NAME_ARCHITECTURE.md` (no warning, while this table says three of its
seven bands must not be deployed). `PLAN.md`, `INFRASTRUCTURE.md`,
`RESEARCH_AND_METHODOLOGY.md` and both `ops/README.md`s do carry one. Check with
`head -12 <file>` before believing either the banner claim or the row. A table
that asserts its own remedy is applied is worse than one that only warns,
because it stops the reader looking.

| file | the trap |
|---|---|
| `docs/PLAN.md` | Five tables label the **2-day calendar as "LIVE"**. The band replaced it 2026-09-06. Its headline **0.10** net Sharpe is the retired policy's; the band's is **0.66** pre-borrow, ~0.43 after. Also: its "Drop PHK" item is contradicted by the later `PER_NAME_ARCHITECTURE.md`, and its "fill capture is not wired" claim is false — capture runs unconditionally. |
| `docs/INFRASTRUCTURE.md` | Gave the broker port as **7497** — the exact misconfiguration that dry-ran **21 consecutive sessions silently**. Live is **4002**. Also names spec v5 (actual v6) and has no `band_width` row. |
| `docs/RESEARCH_AND_METHODOLOGY.md` | Dated 31 July. Its deflated-Sharpe bar assumes **10 trials**; the counter is **48**, so the bar is 2.78 not 2.15. Says "zero live fills"; there are **294**. Its "today's live position" is a July snapshot. |
| `docs/RESEARCH_STATE.md` | Header claims "last updated 2026-07-31" while containing September amendments. Its **counter table is canonical**; its prose is not. |
| `docs/PER_NAME_ARCHITECTURE.md` | Its derived band table silently mixes **target-weight** κ_w with **discount** κ_d, and PHK's row carries the *pooled* constant rather than PHK's own. Three of seven bands (MHD ≈130 obs, MQY ≈365, PDO ≈1,286) rest on fewer observations than this repo's own identification budget allows. **Do not deploy those three.** |
| `ops/README.md`, `ops/schedule/README.md` | Superseded in full. The first opens *"There is no broker here"* — false; seven files in `ops/` open IBKR sockets. Both use the pre-2026-08-31 repo path and reference directories that do not exist. |

**FIXED 2026-09-10.** This read: "four analysis scripts baseline against
`band(T, 0.064)`, the 6.4% width retired on 2026-09-06". All four —
`joint_cost_optimiser.py`, `covariance_construction.py`, `borrow_impact.py`,
`ou_score.py` — now import `BAND_WIDTH` from `scripts/cef/spec.py`, which reads
the frozen spec. The rule stands and is now enforced by tests: **read
`band_width` from the frozen spec; never write the literal.** Four `0.064`s
remain and are all legitimate — two historical comments, one sweep grid, and one
explicitly labelled `("band 6.4%", ...)` comparison row. Verify with
`grep -n '0\.064' scripts/cef/*.py` before believing either this paragraph or
its predecessor.

**This working tree is NO LONGER production (since 2026-09-10).** `~/prod/QUANTT`
is a git worktree detached at a tag, and the scheduler, the dashboard and every
live ledger live there. **`git worktree list` is how you see this** — it is not a
branch and will never appear in `git branch`, which is exactly why the team lead
asked "what is prod/dev? i dont see it on the git" on 2026-09-10 after reading
three documents that each named the concept and none of which gave the command:

```
$ git worktree list
~/Desktop/2027/QUANTT/2027   6bdd5ea [cleanup/...]   <- dev, you are probably here
~/prod/QUANTT                2a7c486 (detached HEAD) <- prod, == a release tag
```

"detached HEAD" on prod is the intended steady state, not a problem to fix. Editing here is safe; nothing you change reaches a
session until someone tags it and runs `ops/promote.sh <tag>`, which refuses
inside the session window or on a prod tree with uncommitted **code**, archives
live state, checks out the tag, then smoke-tests it (doctor → NAV wait →
`fetch_daily --require-asof` → dry-run session → dashboard import) and rolls
back on any failure. The whole boundary is one line — `REPO` in
`~/Library/Application Support/quantt/launch_job.py`. Two things are still
shared, deliberately and temporarily: `data/` is a symlink from prod back to
this tree (so a research script *can* still corrupt what the sleeve prices
from — `ops/sync_dev_data.sh` reverses it once prod owns the panels), and the
live ledgers are still tracked in git, which is why the promotion gate has to
exclude them by pathspec. **The session architecture is still the evening one** — the
08:30 decision, 12:00 retry and evening capture job described in `W3` are planned,
not built. **Halts have two scopes since 2026-09-10.** `ops/HALT.md` is global
and blocks every book — a human halt, or a fault nobody can attribute.
`ops/HALT_<book>.md` blocks one book and reaches the others as a non-blocking
preflight *warning*; `arm()` failures write this one, because arm only ever
refuses on symbols the failing book trades. Two small books had stopped the
$500k strategy over their own bookkeeping in two days before this existed
(phase0/JNK, bench_b6/ANGL). `ls ops/HALT*.md` shows everything active;
`clear_halt(note)` clears the global one, `clear_halt(note, book=...)` a scoped
one, and clearing the global never silently clears a scoped one.

## What the test suite does and does not cover

A green suite here is more reassuring than it should be.

**Get the count by running `python3 -m pytest`, never from this file.** This
paragraph has been wrong in both directions inside 24 hours: it said 126 while
the suite passed 271, then said 271 while it passed **211**. A test count in a
document is stale the day after it is written, and this file is the proof — so
no count is quoted below, by design. If you find one here again, delete it.

The shape, which outlives any count:

- `src/backtest/walkforward.py` is the single largest block, and nothing on the
  live path imports it.
- **`.claude/hooks/tests/` is GONE.** It was the second-largest block (57-60
  tests) and it tested the order-path guard; `7ad3a82` removed the guard and its
  tests together on the team lead's instruction, 2026-09-10. If you are reading a
  count from before that, it is ~60 too high — which is exactly how this section
  came to claim 271 while the suite passed 211 the same afternoon. Run pytest.
- **`ops/promote.sh`'s gate is covered** (`ops/tests/test_promote_gate.py`) —
  written 2026-09-10 after both its pathspecs were found to match nothing.
- **`arm()` attribution is now covered** (`src/deploy/tests/test_arm_attribution.py`,
  17 tests, one per real incident) and so are three preflight checks
  (`ops/tests/test_preflight_checks.py`). Both were written 2026-09-10; before
  that the most incident-prone function in the repo had none.
- **Still zero** for `capture_fills`, `doctor`, `ops/ledger.py`,
  `src/deploy/{portfolio,run_book,registry}.py`, the simulator broker, and
  `dashboard/`.

So a green suite tells you the backtest engine and — since 2026-09-10 — arm()'s
attribution branches and the promotion gate are sound. It no longer tells you
anything about a guard on the order path, because there is no longer one.
**It still tells you little about the code that places orders.** Write a test with any change to the live
path, and never treat a passing count as evidence that a session-path edit is
safe. The cwd defect fixed on 2026-09-10 was found by *writing* such a test, not
by running the suite: it passed green throughout.

`pytest.ini` scopes collection to the real suites. Before it existed, a bare
`python3 -m pytest` failed at *collection* with `ConnectionRefusedError`, because
`scripts/audit/moc_routing_test.py` matches the default discovery pattern and opens
a live broker connection at import — the safest-looking command in the repo reached
for the order path. Do not widen `testpaths`.

## Landmines

1. `launch_job.py` lives **outside** the repo (macOS TCC denies launchd access to
   `~/Desktop`) and hardcodes the repo path. Moving the repo silently kills every
   job. Do not "fix" this.
2. `ops/schedule/rendered/*.plist` are **stale** and point at the old path. launchd
   runs `launch_job.py` directly; those plists are not what runs.
3. `_sleeve_nav` reads the shadow ledger, which can disagree with the broker; when it
   does, reported NAV and P&L are wrong.
   **⚠ "Sizing is unaffected because `arm()` re-seeds from the broker" is FALSE when
   the broker holds ZERO of a symbol, and this line said it for weeks.** Measured
   2026-09-10 ~12:58 ET (read-only, client id 133): `ib.positions()` returned 34
   rows, **JAAA absent, and nothing at exactly 0.0** — IBKR emits no row for a
   flattened position. `arm()` iterates `account.items()` (`ibkr.py:842`), so a
   symbol the broker has none of is **never visited**, the re-seed cannot reach it,
   and the ledger's stale quantity survives into `place_targets`, which diffs
   against `_live_positions` (`ibkr.py:954`). On 2026-09-11 that would have had
   phase0 trade against a phantom 1,503-share JAAA short: if the day's random
   target omitted JAAA, the held-but-unmentioned path (`ibkr.py:988`) sends
   **BUY 1,503** to close a short that does not exist. The re-seed protects you
   only where the broker reports a position. Where it reports nothing, the ledger
   is unchallenged — so a divergence of this shape is a **trading** fault, not a
   reporting one, and it is why `ops/HALT_phase0_null.md` exists.
   **Re-measure before quoting a magnitude — do not carry the old one.**
   `python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json
   --books-root ops/books/cef_live --check-broker` prints it. Measured 2026-09-10:
   **none of the 17 CEFs diverge**; all 13 divergent symbols belong to `null_trader`
   and the benchmark books (worst 3,924 shares, SRLN). The earlier "all 17, ~$223k"
   reading predates the 2026-09-08 epoch re-seed and no longer reproduces.
   Two things this entry does not say, both from a read-only broker query at
   2026-09-10 11:35:29 ET (`results/ops/BROKER_SNAPSHOT_2026-09-10.json`):
   **(a)** the divergence is not drift. Five `null_trader` orders transmitted
   09:43:09 that day are marked **`filled` in the ledger with no execution at the
   broker and nothing resting** (worst: JAAA ledger −1,503, broker 0). A ledger
   booking fills that never happened is a different and worse fault than a stale
   count, and it corrupts P&L directly. **(b)** sizing and reporting can disagree
   with **no** position error at all. On 2026-09-09 the adapter sized four MOC
   orders against a **$500,000.00** base while the book was marked
   **$504,573.20**, so those orders are ~0.91% smaller than the book's own NAV
   would size them, and `orders.csv` and `_order_map.csv` disagree for that
   reason alone. Never diagnose that gap as a position error; it is not one.
   `floor(500000·|w|/close)` reproduces all four sent quantities *and* the log's
   `SKIP NAD +37 @ 11.15 = $413`; $504,573.20 reproduces none of the five.

   **Which code path produced the $500,000 is NOT established, and the two are
   numerically indistinguishable** — `_sleeve_nav` (`ibkr.py:610`) returns the
   sub-ledger's last NAV row, which after the 09-08 reseed was the epoch row
   `500000.0`, and its `except Exception: pass` falls back to `capital_usd`,
   which for `cef_discount` is *also* exactly `500000.0`. Do not assert either
   without checking whether the day's NAV row is written before or after sizing.
   The `except Exception: pass` on the sizing path is a defect either way: if it
   ever fires it silently sizes against registered capital instead of marked NAV,
   and says nothing.
4. **HYT lags the price panel by a day.** `px.iloc[-1]` can be NaN for a name — use
   `px.ffill().iloc[-1]` where you need that name's own last close.
5. **`PositionTarget.weight` is signed.** Do not multiply by the side sign again.
6. The 2411 dates before 2013 are flat — fewer than `min_names` clear the ADV
   filter. Full-sample turnover is diluted ~44% and Sharpes depressed by √(3041/5452).
7. Three books share one IBKR account with overlapping tickers. Attribution is
   per-sleeve; `reconcile()` checks the tagged books sum to `ib.positions()`.
   **Never take a symbol from the account net.**
8. Use `ib_async`, never `ib_insync` — the latter hangs forever in its asyncio
   handshake on Python 3.12+ and looks exactly like a dead broker connection.

## The desk

Path-scoped detail lives in `.claude/rules/` and loads only when you open matching
files. Workflows are skills — `/book-status`, `/preflight`, `/morning-brief`,
`/next-task`, `/graveyard`, `/harness`, `/repro`, `/prereg`, `/spec-change`,
`/fill-audit`, `/dashboard-ui`, `/incident`. Specialist seats are subagents —
`alpha-finder`, `beta-detector`, `unique-angle-researcher`, `execution-trader`,
`portfolio-manager`, `market-structure-analyst`, `equity-research`,
`quant-reviewer`, `dashboard-designer`, `ops-watchdog`. `.claude/README.md` is the
map, and `.claude/hooks/` is the enforcement layer — what it blocks, and why those
actions and not others.

**Before proposing any idea, check the graveyard** (`/graveyard`). Thirteen
mechanisms are dead, and six of them died the same way: a stale-price artifact.
