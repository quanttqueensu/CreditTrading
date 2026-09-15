# The morning session transmits orders the ledger never records — three books halted

**Diagnosed 2026-09-15, read-only.** No broker connection was opened; every
figure below comes from prod's own files. Reproduce with
`python3 -m ops.orient`, `ops/ledger.py` (`advance`), `src/deploy/broker/ibkr.py`
(`place_targets`) and:

```bash
sed -n '/plan: mode=morning/p;/ARMED:/p;/BOOK asof/p' ~/prod/QUANTT/ops/schedule/logs/cef_2026-09-14.log
python3 -c "import json;print(json.load(open('$HOME/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/_desync/cef_discount_2026-09-14.json'))['error'])"
wc -l ~/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/cef_discount/orders.csv   # 1 = header only
```

`[V]` verified by reading the file or log named beside it, 2026-09-15.

## State

All three books are halted in prod `[V]`:

| book | halted | reason |
|---|---|---|
| `cef_discount_paper` | 2026-09-15 08:39:04 | shadow ledger desync in `cef_discount` @ 2026-09-14 |
| `benchmarks_paper` | 2026-09-14 17:25:10 | shadow ledger desync in `bench_b3_agg` @ 2026-09-14 |
| `phase0_null` | 2026-09-10 | the earlier attribution incident |

The CEF book **did trade**: `broker_fills.csv` carries 4 executions on
2026-09-14 and 4 on 2026-09-15, both sets filled in the closing auction
(19:59 UTC) `[V]`. The ledger recorded none of them: `orders.csv` is a header
line, `trades.csv` is a header line, `nav.csv` holds only the epoch row, and
`positions.csv` still reads 2026-09-11 `[V]`.

## What happened, in order

1. **2026-09-13 23:04** — the W3 go-live re-seeded the CEF ledger from broker
   positions at **epoch `2026-09-11`**, NAV $500,000 (`manifest.json`) `[V]`.
2. **2026-09-14 08:30** — first morning session: `plan: mode=morning
   asof=2026-09-11`. Armed 09:50 and transmitted 4 MOC orders (`_order_map.csv`
   rows 31–34, 13:50 UTC) `[V]`.
3. Same call, immediately after transmitting, `ibkr.place_targets` advanced the
   shadow ledger with `through=asof=2026-09-11`. The ledger's last booked date
   **was already 2026-09-11**, so `advance` had no day to process and returned
   its documented no-op. **Step 4 of the loop, "decide tomorrow's order", never
   ran, so the ledger never recorded the orders that had just gone to the
   broker.** The session's own log line says so without anyone noticing:
   `BOOK asof 2026-09-11 NAV $500,000.00 PnL $0.00 turnover $0` — a flat book,
   while four orders were live `[V]`.
4. **2026-09-14 16:00** — the four orders filled.
5. **2026-09-15 08:39:03** — second morning session, `asof=2026-09-14`. It armed
   and **transmitted four more orders** (`_order_map.csv` rows 37–40, 12:39:04
   UTC). Then the ledger advanced through 2026-09-14, found four executions with
   no pending order to attach them to, and raised `UnbookedExecution` at
   **08:39:04** — one second after the orders went out `[V]`.
6. The halt file was written, the transmitted-fills record was saved to
   `_desync/cef_discount_2026-09-14.json`, and the 12:00 retry refused on the
   same-pair guard. The orders from step 5 filled at 2026-09-15's close and are
   also unrecorded `[V]`.

## Cause

`Ledger.advance(through=asof)` processes trading days **strictly after** its
last booked date. Each day it (2) fills yesterday's orders at today's close and
(4) decides the next order. Under the evening schedule `asof` was always the day
just closed, so it was always after the last booked date and the order was
always created.

Under the W3 morning schedule the session decides on **yesterday's pair**, so
`place_targets` is called with `asof` = the pair date. When the ledger's last
booked date is that same date — which is exactly what the epoch re-seed of
2026-09-11 produced for the first morning session — `advance` is a no-op, and
the orders the adapter has already transmitted are never written to the ledger.
The next session then sees their executions and cannot place them.

**This is an epoch-alignment fault, not a general W3 fault.** Had the epoch been
any trading day before 2026-09-11, the 09-14 session would have processed
2026-09-11, created the orders, and the 09-15 session would have booked the
fills against them. It is worth fixing as a guard anyway, because nothing in
the system refused: the condition is knowable before the first order is sent.

The benchmarks book failed with the same error class on 2026-09-14
(`bench_b3_agg`, 1 execution). **I have not verified that it has the same
cause** — its epoch and schedule were not examined.

## Why the existing guards did not catch it

- `e4ac1ed` refuses an uncovered morning **before** transmitting, but it asks
  whether yesterday's *fills* are covered, not whether the ledger can represent
  *today's* order.
- The pending-order refusal (`fa53395`) asks the broker about resting orders.
  There were none: each day's orders had already filled.
- `place_targets` advances the ledger **after** it transmits, so the desync can
  only be detected once the orders are live. The halt then stops the *next*
  session, which is why two days of executions are unbooked rather than one.
- `verify_session` did flag it: its 2026-09-15 heartbeat reads `failed` `[V]`.
  That is the first guard in this sequence that spoke.

## What is not wrong

The broker's positions and the captured fills are real and complete; `arm()`
re-seeds the live tag book from the broker every session, so **order sizing was
never computed from the stale ledger**. What is wrong is the ledger, and
therefore reported NAV, P&L, turnover and every risk gate computed from it.

## The repair, and the guard

**Repair (human, opens a broker socket).** `python3 -m ops.rebuild_ledger
--books-root ops/books/cef_live --sleeve cef_discount --capital 500000 --asof
<date>` rebuilds a ledger from real executions and refuses unless the captured
fills reproduce the broker's current position exactly. Read its `--dry-run`
output first. The same question has to be answered for `bench_b3_agg`. Clearing
either halt before the ledger agrees with the broker would re-arm a book whose
NAV and risk gates are computed from a two-day-stale position.

**The guard that would have caught it**, to be written with a test per timeline:
refuse **before transmitting** when the ledger cannot represent the session's
`asof` — i.e. when its last booked date is not strictly before `asof` — and say
so in the same shape as the other pre-transmit refusals. A second, narrower
test should pin that a no-op `advance` never silently accompanies a transmitted
order set.
