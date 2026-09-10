# W2 — What the account can actually do, and retiring the control book

**Status:** in progress — done: per-book halt scoping (`43ec054`, `26a5336`). remains: the account audit itself, and the benchmark fill dedupe.
**Reads first:** `00_BRIEF.md` §6 (house rules), §7 (standing decisions).
**Lever:** prerequisites. Nothing in W14 (options) can start until this note
says "permitted", and W6's sizing memo cannot be written until the margin type
is known. **Trials:** 0. **Touches the live book:** no; it winds down a
different book.
**Run second, after W1.** **Supersedes:** P8.3.

---

**Amended 2026-09-09 (incident), resolved in part 2026-09-10.** On 2026-09-09
the *benchmarks* book halted over ANGL — its own pre-epoch fill landing after
its re-seed — and, because `ops/HALT.md` was global, that halt would have
blocked the CEF session's preflight at 22:45.

**Halt scoping is now DONE, not a task in this prompt.** `arm()` failures write
`ops/HALT_<book>.md`, which blocks that book and reaches every other book as a
non-blocking preflight warning; the global file keeps its old meaning for human
halts and unattributable faults. `ops.halt.scoped_path` carries the reasoning,
`src/deploy/tests/test_halt_scope.py` pins it (11 tests), and the drill replaying
the 09-09 incident showed benchmarks blocked with the CEF book warned and armed.

**Still to do here:** dedupe the benchmark fill files. `capture_fills` attributes
by symbol, so the null trader's 09-08 fills in JNK/LQD/USHY/SHYG/VCIT/EMB were
also written into bench_b6's `broker_fills.csv`. Retiring the null trader removes
the cause; the existing duplicates must be removed by execId before that file is
used for any cost or P&L statistic.

## Paste from here

You are working in the QUANTT credit CEF repo. Read `docs/prompts/00_BRIEF.md`,
then:

1. `ops/books/phase0_book.json`, `ops/schedule/phase0.env`,
   `src/deploy/sleeves/null_trader.py` — the control book: 6 ETF positions,
   ~$310k gross, built 2026-07 to measure execution cost against a book with
   no signal. W7 now measures cost from our own MOC fills, so the control has
   done its job.
2. `ops/books/benchmarks_book.json` — the five reference books. They stay.
3. `ops/reconcile_orders.py::ALL_BOOKS` and `ops/books/*/_attribution.json` —
   LQD, VCIT, USHY, EMB, HYG and SHYG are held by the null trader **and** by
   bench_b6, attributed by ledger, so winding one book down must remove only
   its share.
4. `src/deploy/portfolio.py` — "a killed sleeve keeps advancing FLAT until its
   position is wound down": the disable path already exists.
5. `ops/halt.py`, `ops/halts/`, `ops/preflight.py`.

---

## Part A — The capability audit

Write `ops/account_audit.py`: read-only except for `whatIfOrder`, run against
the gateway, output a table and a verdict per capability.

| capability | how to test | needed by |
|---|---|---|
| **Options trading permission** | `whatIfOrder` on a 1-lot HYG put (nearest monthly, ~25-delta). A permission error (IB 10xxx / "not permitted") is the answer; a margin response means yes. **Never transmit.** Record the permission *level* too — long options, spreads and short options sit at different levels, and the programme only ever needs long options plus share hedging | W14 |
| Option **market data** | `reqMktData` on that contract under `reqMarketDataType(3)` (delayed) and (1) (live): which returns a bid/ask, and the exact subscription message. OPRA is a separate subscription from equity top-of-book | W14 marks |
| **Historical option bars** | `reqHistoricalData` on the same contract: how far back, at what bar size | W14 fallback data |
| **Historical equity bars** for the 44 | daily, full history: confirm depth and split handling | W3 Part A |
| **Margin type** | `accountSummary` tags including `AccountType`. Reg-T caps gross at 2× equity; portfolio margin is TIMS-style on net exposure. This single fact sets the ceiling on the vol target | W6 Part B |
| **Commission plan: Tiered or Fixed** | Read it from the account, not from an assumption. **This is not cosmetic.** Verified 2026-09-09: Tiered is $0.0035/share with a **$0.35 order minimum**; Fixed is $0.005/share with a **$1.00 order minimum**. The frozen spec's `min_trade_usd: 517` was derived as `$1.00 × 1e4 / (30 − 10.67)` — i.e. **on the Fixed minimum**. On Tiered the same derivation gives **$181**, and the live threshold is suppressing orders nearly 3× larger than it should. Options: Tiered $0.15–$0.65/contract, Fixed $0.65, **$1.00 order minimum on both** | W5, W7 |
| Short-sale credit interest | Confirm the account clears the **$100,000 NAV** threshold for the full rate (it does at $500k). Tiers observed 2026-09-09: $100k–$1M **2.380%**, $1M–$3M 3.130%, >$3M 3.380% | W6 Part B |
| **Short-sale data over the API** | **Answered 2026-09-10:** `FEE_RATE` daily bars are served, five years deep (43/44 names; `data/cef/cef_borrow_history.parquet`); `REBATE_RATE` times out on every name tried; tick 236 availability returns NaN under error 10197 ("competing live session"). Record only what still needs confirming: whether tick 236 works when no other session holds market data | W8 |
| Client id headroom | list every client id in `ops/schedule/*.env`, `config/.env`, the dashboard and the tools; confirm no collision with W3's new jobs | W3 |

Write `results/ops/ACCOUNT_AUDIT_<date>.md` with the exact IB messages. If
options permission is absent, the note says so in its **first line** and lists
the human step (IBKR Client Portal → Settings → Trading Permissions → Options,
US). W14 refuses to start until this note says "permitted".

---

## Part B — Scope the halts per book

A halt written by one book currently blocks every book's preflight. Change it:

- `ops/HALT.md` keeps blocking everything **only** when written by a human or
  by the book itself at the global level.
- A sibling book's arm failure writes `ops/halts/HALT_<book>.md` and blocks
  **only that book**.
- `ops/preflight.py` reads both, and its verdict names which file blocked it.
- Test: write a fake `HALT_benchmarks.md`, run the CEF preflight, confirm it
  arms; write `HALT.md`, confirm every book refuses. Clear both.

---

## Part C — Retire the null trader, cleanly

The order matters because of the shared tickers.

1. **Freeze attribution first.** Snapshot `_attribution.json` and every
   ledger's positions for the six shared ETFs; compute the null trader's share
   of each from *its* ledger. Write the table into the note before anything
   moves.
2. **Dedupe the benchmark fill files** by `execId` against the null trader's,
   before the record is used for anything. `capture_fills` attributes by
   symbol, so bench_b6 currently carries fills that were not its own.
3. **Disable the sleeve** (`"enabled": false` in `phase0_book.json`) and run
   the phase0 job once, armed: the portfolio path emits FLAT targets for the
   null trader's held names and the broker path sells *its share only* —
   verify `place_targets` diffs against `_live_positions["null_trader"]`, not
   the account net. Confirm from the fills that the benchmark books' positions
   in the six names are unchanged to the share.
4. **Reconcile** with `reconcile_orders --check-broker` across all books: zero
   divergence on the six shared names.
5. **Unschedule:** `launchctl bootout` of `com.quantt.phase0.daily`, remove the
   plist, keep `ops/books/phase0_live/` as a read-only archive (`chmod -w`),
   remove `phase0` from the watchdog's expected jobs and from `ALL_BOOKS`'
   *live* list while keeping it in the attribution-history readers, and record
   the retirement in `docs/RESEARCH_STATE.md` with the control's final
   measurement (its realised cost, by W7's method).
6. Dashboard: the null trader disappears from Positions attribution; the
   benchmark sleeves remain.

## Deliverables

- `ops/account_audit.py`, `results/ops/ACCOUNT_AUDIT_<date>.md`.
- The per-book halt scoping with its test.
- `results/ops/NULL_TRADER_RETIRED_<date>.md`: the before/after table on the
  shared tickers, the dedupe count, and the control's final cost measurement.

## Do not

- Do not transmit any option order. `whatIfOrder` only.
- Do not flatten a shared ticker at the account level. Only the null trader's
  own tag book is driven to zero.
- Do not delete the phase0 ledger or its fills; they are the control's record.
