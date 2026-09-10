# One broker execution, two owners — `capture_fills` dedups per book, not per account

**Measured 2026-09-10, dev tree, read-only. No broker connection was opened.**
Everything below comes from the on-disk `broker_fills.csv` records and
`results/ops/BROKER_SNAPSHOT_2026-09-10.json` (read-only probe, 11:35:29 ET).

## The finding

**60 of 1,088 distinct execIds in the live ledgers are booked by more than one
sleeve.**

| symbol | sleeves that both booked it | net double-booked |
|---|---|---:|
| HYG | `bench_b1_hyg` + `null_trader` | −442 sh |
| JNK | `bench_b6_ew_credit` + `null_trader` | −961 sh |
| LQD | `bench_b6_ew_credit` + `null_trader` | −862 sh |
| USHY | `bench_b6_ew_credit` + `null_trader` | +896 sh |

The 2026-09-08 executions appear in phase0's record at **13:35:19 UTC** and
again in the benchmarks record at **21:25:08 UTC** — same `execId`, same
quantity, same price, same broker `time=`, captured eight hours apart by two
different sessions. Example: `execId=00012ec5.6b3b4068.01.01`, JNK SELL 20 @
95.10, present in both files.

## The mechanism

`ops/capture_fills.py:149`

```python
seen = _recorded_exec_ids(books_root, universes)
...
if e.execId in seen.get(sleeve, set()):
    dupes += 1
    continue
```

`_recorded_exec_ids(books_root, universes)` reads
`<books_root>/_ibkr_shadow/<sleeve>/broker_fills.csv`. **Both arguments are
scoped to the single book being captured.** Three books share one IBKR paper
account with overlapping tickers, and each runs its own capture against the same
`ib.fills()`. When two books both trade a symbol, each attributes the execution
to its own sleeve, neither `seen` set contains the other's copy, and it is
written twice.

The `shared` / `order_map` branch above it does not help: `universes` holds only
the sleeves of the book in *this* process, so a symbol traded by `null_trader`
(phase0) **and** `bench_b6_ew_credit` (benchmarks) is not "shared" from either
book's point of view. Each sees itself as the sole owner.

`dedupe()` cannot repair it either — it is scoped the same way and will never see
the twin under another `books_root`.

**This is the same blind spot as `arm()`'s cross-book claims, in the opposite
direction.** `arm()` was taught on 2026-07-31 to consult sibling book specs
before adopting a shared symbol from the account net. `capture_fills` never was.

## What it does and does not corrupt

**Not P&L, and not positions.** The module's own docstring is explicit —
*"Nothing here feeds P&L"*; the shadow ledger with its modelled cost is the sole
P&L source (FORCED_FLOW_PREREG locked decision 1).

**USHY is the control that proves it**: 896 shares double-booked, and its
ledger-vs-broker position gap is **−11 shares**. If double-booking drove
positions, USHY would be the worst row in the book. It is one of the best.

| sym | broker | Σ ledgers | gap | double-booked |
|---|---:|---:|---:|---:|
| USHY | −1,273 | −1,262 | **−11** | 896 |
| LQD | −881 | −23 | −858 | −862 |
| HYG | 383 | 987 | −604 | −442 |
| JNK | 26 | 446 | −420 | −961 |
| JAAA | 0 | −1,503 | +1,503 | 0 |

So this is a **second, independent fault**, not the cause of the phase0
divergence in `HALT_phase0_null.md`. `gap + double_booked` does not close for any
row. Both faults are real; neither explains the other.

What it does corrupt is the **realised-slippage record** — which is precisely the
input to **kill rule (b)**, *"realised slippage > 2× modelled for 5 consecutive
sessions"*. Slippage is volume-weighted, so a duplicated execution does not
inflate a row count, it moves the statistic. That is the same reasoning the
module's own dedup comment gives for why the within-book dedup is
*"LOAD-BEARING, NOT HYGIENE"*.

## The $500k CEF book is unaffected

None of HYG, JNK, LQD or USHY is in `cef_discount`'s 17-name universe, and **no
`cef_discount` execId is double-booked**. Verified by intersecting the 60 against
the frozen spec. `cef_discount` is also the only one of the three books whose
sleeve is not paired with another book on any of these symbols.

## Coverage

`CLAUDE.md` lists `capture_fills` under **"Still zero"** test coverage. It now
has four tests — `ops/tests/test_capture_fills_cross_book.py` — built entirely in
`tmp_path`, no broker, no network, and no reads of `ops/books/*_live/`. Two of
them are **characterisation tests that assert the broken behaviour on purpose**;
the file says so and says what should start failing when it is fixed.

## Suggested fix, not applied

Key the dedup on the **account**, not on one `books_root`: one `execId` is one
broker execution and can have exactly one owner. The natural owner is whichever
sleeve's `_order_map.csv` claims the originating `orderId`, with the existing
`UNATTRIBUTED` branch handling the rest — the machinery already exists, it is
just never reached across books. **Not applied here**: it changes what lands in
the live fill record, it needs the order maps of all three books to agree, and
the existing rows would need a one-time cross-book `dedupe`. That is a live-path
change and wants its own session.

## Reproduce

```bash
python3 - <<'PY'
import csv,glob,os,re
from collections import defaultdict
ex=defaultdict(set)
for bf in glob.glob("ops/books/*_live/_ibkr_shadow/*/broker_fills.csv"):
    sl=os.path.basename(os.path.dirname(bf))
    if sl.startswith("_pre"): continue
    for r in csv.DictReader(open(bf)):
        m=re.search(r"execId=(\S+)", r.get("note") or "")
        if m: ex[m.group(1)].add((sl,r["instrument"]))
dup={k:v for k,v in ex.items() if len({s for s,_ in v})>1}
print("distinct execIds:", len(ex), " double-booked:", len(dup))
for k,v in list(dup.items())[:3]: print("  ", k, sorted(v))
PY
```
