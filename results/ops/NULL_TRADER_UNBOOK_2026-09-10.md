# The prescribed fix for null_trader's ledger would have made it 4x worse

**Measured 2026-09-10 evening, dev tree. No broker connection was opened** — the
broker side is `results/ops/BROKER_SNAPSHOT_2026-09-10.json` (read-only,
clientId 115, read 11:35:29 ET). `[V]` verified by re-running the command shown.

**The ledger change landed in `c92f70e`, whose message does not mention it** —
it was swept in with the review fixes. This note is the record.

## What was prescribed, and why it is wrong

Every note written on 2026-09-10 — the halt file, `LEDGER_DIVERGENCE`,
`LQD_ATTRIBUTION` — prescribes the same remedy: **rebuild `null_trader` from its
own `broker_fills.csv`**. `LQD_ATTRIBUTION_2026-09-10.md` states it plainly:
*"Once done the ledger reads −904, the broker reads −904, and there is no
position decision left to make."*

**That is true of LQD and of almost nothing else.** `broker_fills.csv` holds 677
executions across three dates only — 07-31: 45, 09-08: 60, 09-10: 572. Fill
capture began 2026-07-31 21:20 UTC and `ib.fills()` cannot reach back past a TWS
restart, so the file is not a history of the account; it is everything we caught.
The book also advanced on **simulated** fills through August while TWS was down.

Reconciling *captured fills + every other book's ledger claim* against the broker
account net: `[V]`

| | symbols reconciling | total |gap| vs broker |
|---|---:|---:|
| ledger as it stood 2026-09-10 | 2 of 14 | **3,487 shares** |
| **rebuild from broker_fills** | **2 of 14** | **14,346 shares** |
| **reverse only the unexecuted fills** | **14 of 14, all within 12** | **49 shares** |

The rebuild's worst errors would have been **BKLN +4,901** (captured fills say
+3,700; the broker says −1,201 and no other book trades BKLN) and **SRLN
−4,444**.

**LQD is one of the two symbols that does reconcile**, which is exactly why the
attribution note — which checked LQD and only LQD — reached the opposite
conclusion. Its arithmetic was right; its generalisation was not.

`rebuild_ledger`'s own docstring names the property that would have caught this:
*"refuses to run unless the captured fills reproduce the broker's CURRENT
position exactly"*. **That check only runs under `--check-broker`**, which opens
a broker socket, so the default invocation — the one every note prescribes —
skips the guard the file advertises.

## What was done instead

`ops/unbook_unexecuted_fills.py`: reverse the ledger fills that have **no
execId-backed execution on that date**, and nothing else. Five rows, all
2026-09-10, all previously reported: `[V]`

```
JAAA  SELL  1,503 @ 50.5682     EMB  BUY     57 @ 93.5834
JNK   BUY     420 @ 94.7369     HYG  BUY    605 @ 78.7517
LQD   BUY     861 @ 104.7290
NAV 641,105.36 -> 641,154.24 (+48.88)   cost_usd -48.88   traded_usd -258,944.17
```

**NAV moves by exactly the reversed `cost_usd`.** That is the arithmetic closing
on itself: a fill booked at `close ± slippage` that never happened cost the book
precisely its own modelled slippage, and nothing else.

Resulting position vs the broker, after adding every other book's ledger claim: `[V]`

| | | | | | | | |
|---|---:|---|---:|---|---:|---|---:|
| JAAA | **0** | JNK | **0** | LQD | −3 | HYG | −1 |
| EMB | +1 | SJNK | −1 | IGSB | −2 | SPHY | +2 |
| VCSH | +2 | SRLN | +4 | SHYG | −4 | VCIT | −6 |
| USHY | +11 | BKLN | −12 | | | | |

JAAA and JNK close **exactly**. LQD's **−3** is the pre-existing modelled drift
`LQD_ATTRIBUTION_2026-09-10.md` predicted independently, which is a real
cross-check: two methods, same residual. The rest are 1–12 shares of the same
August drift and are **not** what the halt was raised for.

## What this does NOT fix, and why the halt must stay until it is promoted

**The corrected ledger is in DEV. Prod still has the wrong one.** `~/prod/QUANTT`
is detached at `v2026.09.10.1`. Until a promotion carries this,
`ops/HALT_phase0_null.md` in prod is the only thing standing between the phantom
JAAA short and an armed session.

**Clear the halt only after prod's ledger reads the corrected numbers** — verify
`LQD −907` and no `JAAA` row in
`~/prod/QUANTT/ops/books/phase0_live/_ibkr_shadow/null_trader/positions.csv`
first. Clearing it on the strength of this note, while prod still holds the old
file, re-arms exactly the fault it documents.

The recurrence guard is separate and already in: `Ledger._broker_fill` refuses to
book a fill with no execId at write time (`df6a818`). This file is the
retrospective half of that guard, for rows written before it existed.

## Open

- **`bench_b6_ew_credit`'s +23 LQD is still `[U]`**, unchanged by any of this. It
  is not broker-confirmed and no LQD row has ever appeared in the benchmarks
  order map. Settling it needs an IBKR Flex Query for DUQ199038 covering
  2026-07-01..07-31; `reqExecutions()` cannot reach back that far.
- **The 1–12 share August drift on twelve symbols** is untouched and is not worth
  a broker round trip on its own. It will wash out as those names trade.

## Governance

Forensic repair of an existing ledger. No parameter swept, no specification
tested against returns, nothing feeding a signal. **CEF stays 48, GAMMA stays 0.**
