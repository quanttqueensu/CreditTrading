> **ARCHIVED 2026-09-28 — not evidence of current state.** Was `~/prod/QUANTT/ops/HALT_phase0_null.md`.
> Now owned by: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` (IBKR retired 2026-09-28; this is the prod tree's state that day). Numbers: `python3 -m ops.orient`.

# HALT — phase0_null

`ops/preflight.py` reads this file before every session of **phase0_null** and will not arm live orders for it while this file exists. Other books see it as a WARNING and continue: an arming failure is about the symbols the failing book trades, and one book's bookkeeping must not stop another's strategy. Data collection and logging continue regardless.

Most recent halt first.

---

## 2026-09-10 16:04:42  CORRECTION to the entry below: $168,790.60 is ledger overclaim (rebuild, no position call); only LQD's $89,841.18 is unattributed. Total $260,418.10 unchanged. Block unchanged.

- **source**: `recomputed by sign from this session's reconcile_orders --check-broker; peer-caught, independently reproduced 2026-09-10`
- **state**: trading is BLOCKED for **phase0_null** until this file is cleared (other books are warned, not blocked)

### Correcting the entry below: the split, not the total

The total is unchanged and reproduces exactly — **$260,418.10 gross across 15
symbols**, top five $258,631.78. Share counts and marks below are the same ones
the original entry used. What was wrong was the **direction** of the gap for
three of the four non-JAAA symbols, and that changes what clearing this costs.

The entry below says ~$182.6k "exists at the broker and is claimed by no book's
ledger", naming LQD, HYG, JNK and EMB. **That is true of LQD only.** Recomputed
2026-09-10, this session, by sign:

| sym | ledger | broker | gap | $ at ledger's 09-10 mark | class |
|---|---:|---:|---:|---:|---|
| JAAA | −1,503 | 0 | 1,503 | $76,021.89 | ledger overclaim |
| HYG | 987 | 383 | 604 | $47,558.96 | ledger overclaim |
| JNK | 446 | 26 | 420 | $39,782.40 | ledger overclaim |
| EMB | 608 | 550 | 58 | $5,427.35 | ledger overclaim |
| LQD | −23 | −881 | 858 | **$89,841.18** | **unattributed at broker** |

For HYG, JNK and EMB the LEDGER asserts more exposure than the account holds —
`|ledger| > |broker|`, the same fault class as JAAA, not its opposite. Only LQD
has the broker holding more (−881) than every ledger together claims (−23).

**So the work splits:**

* **$168,790.60 — ledger overclaim.** Fixable by rebuilding the ledger from
  broker executions. **No position decision, and no order.**
* **$89,841.18 — genuinely unattributed (LQD alone).** This is the part that
  needs an attribute-or-flatten call from the team lead.

The original entry put $182.6k on the decision side. It is **$89,841.18** — about
half. Clearing this is a smaller judgement call and a larger bookkeeping job than
that entry implied, and stating it the other way round risks the whole thing being
deferred as a position problem when most of it is arithmetic.

**Nothing about the block changes.** Every reason in the entry below still stands:
`arm()` cannot correct the JAAA leg because `ib.positions()` emits no row for a
flat symbol, phase0 is RUNG-2, and it fires 09:35. This correction makes the
remediation cheaper to scope, not safer to skip.

**Untested hypothesis, recorded because it fits.** `ops/specs/credit_rv.frozen.json`
claims all five of these symbols, the book is retired, and it has no ledger
anywhere. A book that traded and then lost its ledger presents exactly as the LQD
signature — broker holds it, no ledger claims it. Testing that needs the broker's
execution history attributed by time, which is `scripts/ops/reconcile_attribution.py`
territory. If it holds, LQD may be attributable after all rather than a flatten
decision, which would reduce the decision side to roughly nothing.

Credit: the direction error was caught by a parallel agent re-deriving the split
from the broker snapshot, and I reproduced it before writing this.

To clear once the cause is genuinely fixed:

    python3 -c "from ops.halt import clear_halt; clear_halt('what you fixed', book='phase0_null')"

---

## 2026-09-10 12:56:17  phase0 ledger disagrees with the account by $260,418.10 gross across 15 symbols; arm() cannot correct the worst of it

- **source**: `ops.reconcile_orders --check-broker + read-only ib.positions() probe, 2026-09-10 (session, not scheduled)`
- **state**: trading is BLOCKED for **phase0_null** until this file is cleared (other books are warned, not blocked)

### What was measured, and how

All figures below are from THIS session (2026-09-10, ~12:50-13:00 ET), against
the live account DUQ199038. Nothing here is recalled.

**Share counts** — `python3 -m ops.reconcile_orders --book ops/books/phase0_book.json
--books-root ops/books/phase0_live --check-broker`, run twice: once from the dev
tree and once from `~/prod/QUANTT` (client id 131). Both runs returned the
SAME 15 divergent symbols, so this is not an artifact of which tree was read.

**Marks** — `ops/books/phase0_live/_ibkr_shadow/null_trader/positions.csv`,
date row 2026-09-10: the ledger's OWN closes, i.e. the prices it used to assert
its own NAV. Using the ledger's marks, not an independent panel, is deliberate:
the question is how wrong the ledger is in its own units.

| | ledger | broker | diff | at ledger's 09-10 mark |
|---|---:|---:|---:|---:|
| JAAA | -1,503 | 0 | +1,503 | $76,021.89 |
| LQD | -23 | -881 | -858 | $89,841.18 |
| HYG | 987 | 383 | -604 | $47,558.96 |
| JNK | 446 | 26 | -420 | $39,782.40 |
| EMB | 608 | 550 | -58 | $5,427.35 |
| 10 others | | | 1-12 sh each | $2,078.32 combined |

**Gross absolute divergence $260,418.10** across 15 symbols; the top five are
$258,631.78 = 99.3% of it. AGG (1 share, bench_b3_agg) is unpriced — it has no
09-10 mark in this book's ledger.

These are TWO different faults, not one:

* **The ledger claims what the account does not hold.** JAAA: the ledger books a
  1,503-share short. The broker holds none. Five `null_trader` orders
  transmitted 2026-09-10 09:43:09 are marked `filled` in the ledger with no
  execution at the broker and nothing resting.
* **The account holds what no ledger claims.** LQD 858 sh, HYG 604, JNK 420,
  EMB 58 — about $182.6k — exist at the broker and are claimed by no book's
  ledger at all. These contribute real P&L and real margin to a book that does
  not know they are there.

### Why this blocks trading, and is not merely bad accounting

The standing note in CLAUDE.md says a ledger/broker divergence leaves sizing
unaffected because `arm()` re-seeds from the broker. **For JAAA that is false,
and I measured why.**

`arm()` (`src/deploy/broker/ibkr.py:796`) seeds from `sync_positions(None)`,
which is `self.ib.positions()` (`ibkr.py:658`), then iterates
`for sym, qty in account.items()`. A read-only probe at ~12:58 ET (client id
133) returned **34 rows, with JAAA ABSENT and no symbol returned with
exactly 0.0**. IBKR does not emit a row for a flattened position.

So JAAA is never visited by that loop, the re-seed cannot reach it, and the
ledger's `-1,503` survives into `place_targets`, which diffs against
`self._live_positions` (`ibkr.py:954`). Three outcomes tomorrow, and the null
trader's signal is random, so the sign is a coin flip:

* target short again (~-1,500) -> delta ~ +3, a no-op: the book stays FLAT
  while believing it is short $76k.
* target flips long (e.g. +1,200) -> delta +2,703 BUY against a true base of 0:
  ~$76k of unintended long exposure.
* **JAAA not mentioned at all** -> the held-but-unmentioned path
  (`ibkr.py:988-992`) sets desired=0 and sends **BUY 1,503** to close a short
  that does not exist, creating ~$76k of long from nothing.

In every branch the realised position is wrong by exactly 1,503 shares.

### Why nothing would have stopped it

* `ops/schedule/phase0.env` is **RUNG-2: `DRY_RUN=0`, `EXECUTION=ibkr`**.
  This book is supposed to send real orders.
* `com.quantt.phase0.daily` fires **09:35 local, Weekday 1-5**. Tomorrow,
  Friday 2026-09-11, is a fire day. (The "09:43" in the work order is last
  session's TRANSMIT time, not the job time.)
* phase0 preflight logged `verdict: arm=True collect=True (0 blocker(s),
  0 warning(s))` on 09-08, 09-09 and 09-10 — including `[PASS] halt: no active
  halt`. `arm()` only halts when attribution is genuinely ambiguous; for a
  shared symbol with a tagged ledger value it trusts the ledger and returns ok.
  So the automated path had no objection to make.

### What clearing this requires

Not a re-run of reconcile. The ledger has to be rebuilt from real broker fills
(`ops/rebuild_ledger.py`), and the ~$182.6k of unattributed LQD/HYG/JNK/EMB has
to be attributed to a book or deliberately flattened. Re-measure with
`--check-broker` afterwards and confirm the divergence is gone BEFORE clearing.

Note that the phantom JAAA fills mean broker_fills.csv is not a clean source for
JAAA on 2026-09-10 either — the rebuild has to reconcile against executions the
broker confirms, not against the ledger's own fill rows.

To clear once the cause is genuinely fixed:

    python3 -c "from ops.halt import clear_halt; clear_halt('what you fixed', book='phase0_null')"

---


---

## 2026-09-10 evening  LQD is ATTRIBUTED — the flatten decision this file asked for is withdrawn

**The halt STAYS. This entry removes a decision, not the halt.** `ops/halt.py`
gates on this file *existing*, so nothing here changes what is blocked.

The CORRECTION entry above says of LQD: *"$89,841.18 — genuinely unattributed
(LQD alone). This is the part that needs an attribute-or-flatten call from the
team lead."*

**No it does not. Do not flatten LQD.**

`null_trader` really is short **904** LQD and every share carries a broker
execId — 20 of them, −42 on 2026-07-31 and −862 on 2026-09-08, the latter
matching `_order_map.csv` order_id 9 (`null_trader, LQD, SELL, 862`) to the
share. The ledger reads −46 only because a **BUY 861 that never executed was
booked as filled** on 2026-09-10 (order_id 25, `BUY 863`, recorded
13:43:09Z — zero executions in the session's 572, and not resting; the only
open orders were four CEF MOC legs).

The account net closes exactly, to the share:

```
null_trader broker-confirmed  −904
bench_b6_ew_credit ledger      +23
                              ————
                              −881   = broker account net
```

So LQD belongs in the **same phantom-fill class as JAAA / HYG / JNK / EMB**,
and the remediation is the one already prescribed for those four: **rebuild
`null_trader`'s ledger from its own `broker_fills.csv`. That transmits
nothing.** Afterwards ledger and broker both read −904 and there is no position
decision left.

**Flattening would have been wrong twice**: the real position is `null_trader`
−904 plus an unidentified +23, and the next armed session would re-create the
discrepancy regardless, because the cause is the ledger and not the position.

**Still open, and much smaller:** `bench_b6_ew_credit`'s **+23 shares
(≈$2,408)** is not broker-confirmed — no LQD execId in any `bench_*` record
before the 09-08 duplicates, and no LQD row in the benchmarks order map ever.
It is most likely a pre-capture long from before 2026-07-31 21:20 UTC, which
`reqExecutions()` cannot reach. Settling it needs an IBKR activity statement
for July 2026. **23 shares. Not urgent, and not a reason to send an order.**

Working, with a read-only reproduce block that opens no broker connection:
`results/ops/LQD_ATTRIBUTION_2026-09-10.md` in the **dev** tree. Prod has a
`results/` but no `results/ops/` at v2026.09.10.1 -- that directory arrives
with v2026.09.10.3 -- so read it from
`~/Desktop/2027/QUANTT/2027/results/ops/`.

**Why `arm()` will not fix LQD by itself:** unlike JAAA — where the broker
emits no position row at all, so the re-seed never visits the symbol — LQD *is*
reported by the broker, and `arm()` then declines to adopt it because LQD is
**contested**: `bench_b6_ew_credit`'s universe contains it, and the account net
is not one book's to take. `arm()` falls back to the ledger. So the next armed
phase0 session would size LQD from −46 against a real −904. **That is why this
halt must stay until the ledger is rebuilt.**

## 2026-09-10 evening  arithmetic correction: "10 others" is $1,786.32, not $2,078.32

The `| 10 others |` row above says **$2,078.32**. That figure reproduces from no
file, and this document's own arithmetic does not close with it:

```
258,631.78 + 2,078.32 = 260,710.10   <- appears nowhere
258,631.78 + 1,786.32 = 260,418.10   <- the gross this file states
```

Recomputed from this book's own 2026-09-10 marks: BKLN 246.90, USHY 400.52,
VCIT 479.64, SHYG 167.34, SRLN 162.06, IGSB 103.33, VCSH 155.84, SPHY 46.06,
SJNK 24.62, AGG unpriced -> **$1,786.32**. The gross total of $260,418.10 is
correct; only the "10 others" row is wrong. Working and the reproduce block:
`results/ops/LEDGER_DIVERGENCE_2026-09-10.md`, addendum, in the dev tree.

**Sign convention:** this file quotes `broker - ledger`. `LEDGER_DIVERGENCE`
quotes `ledger - broker`. Same magnitudes, opposite signs. Read the direction
off the wording, never off the sign.
