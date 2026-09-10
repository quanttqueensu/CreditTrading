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

---

# AMENDMENT — 2026-09-10 evening session

Re-measured from the live ledgers before using any figure above. Provenance
labels below are `[V]` verified by re-running the command shown, `[S]` sourced
but not re-read, `[U]` uncertain.

## 1. The headline reproduces exactly

**60 of 1,088 distinct execIds, symbols HYG / JNK / LQD / USHY. [V]**

Reproduce (dev tree, read-only, no broker):

```bash
python3 - <<'PY'
import pandas as pd, pathlib
rows=[]
for p in sorted(pathlib.Path("ops/books").glob("*_live/_ibkr_shadow/*/broker_fills.csv")):
    s=p.parts[4]
    if s.startswith("_"): continue          # archival snapshot, not a live sleeve
    d=pd.read_csv(p); d["_sleeve"]=s
    d["execId"]=d["note"].astype(str).str.extract(r"execId=(\S+)")[0]
    rows.append(d)
a=pd.concat(rows,ignore_index=True)
g=a.groupby("execId")["_sleeve"].nunique()
print(a["execId"].nunique(), "distinct execIds;", (g>1).sum(), "owned by >1 live sleeve")
PY
```

**The `if s.startswith("_")` filter is load-bearing, and omitting it is the
trap.** Without it the same scan returns **423**, not 60 — because it then
counts the `_pre_epoch_*` and `_prerebuild_*` archival snapshot directories,
whose whole purpose is to be a second copy. 276 of those 423 are
`cef_discount` against its own two pre-epoch archives. Anyone re-measuring this
and getting 423 has not found a worse fault; they have counted the backups.

Per-symbol, the excess (one copy of each duplicated pair) [V]:

| symbol | execIds | shares, both copies | excess shares |
|---|---:|---:|---:|
| HYG | 11 | 884 | 442 |
| JNK | 18 | 1,922 | 961 |
| LQD | 18 | 1,724 | 862 |
| USHY | 13 | 1,792 | 896 |

These reconcile with the table at the top of this note, which states the
excess. Both are right; they are different conventions, and the earlier table
does not say which it uses. It does now.

## 2. The invariant holds: the $500k book is untouched [V]

`cef_discount` shares **zero** execIds with any other live sleeve, and has no
within-sleeve duplicates: 294 rows, 294 distinct execIds. None of
HYG/JNK/LQD/USHY is in its 17-name universe.

## 3. NEW — the true owner of all 60 is determinable, and it is `null_trader`

All 60 fall on **2026-09-08**, and only phase0's order map claims them [V]:

| order_id | sleeve | symbol | action | qty ordered | excess shares filled |
|---:|---|---|---|---:|---:|
| 3 | null_trader | HYG | SELL | 442 | 442 |
| 4 | null_trader | JNK | SELL | 961 | 961 |
| 9 | null_trader | LQD | SELL | 862 | 862 |
| 5 | null_trader | USHY | BUY | 2,098 | 896 (partial) |

`benchmarks_live/_ibkr_shadow/_order_map.csv` has **no entry for any of those
four symbols on that date**. So the benchmarks copies are false claims,
created because `bench_b1_hyg` and `bench_b6_ew_credit` hold those tickers in
their universes and each book's capture pass claims any fill of a symbol it
holds. The three quantities that were fully filled match the order exactly;
USHY was a partial.

## 4. NEW — the corrupt rows have NOT reached any slippage statistic [V]

This is the part that changes the urgency, and it contradicts the natural
reading of "that history is the input to kill rule (b)".

`slippage.csv` exists for exactly **two** sleeves on disk:

```
ops/books/cef_live/_ibkr_shadow/cef_discount/slippage.csv      31 rows
ops/books/phase0_live/_ibkr_shadow/null_trader/slippage.csv    22 rows
```

Neither `bench_b1_hyg` nor `bench_b6_ew_credit` — the two sleeves that hold
every false row — has ever had `slippage_report` run against it. And
`null_trader`'s slippage covers **2026-07-31 and 2026-09-10 only**, not
2026-09-08, so the contested date is absent from it as well. `cef_discount`'s
covers 2026-07-31 and 2026-09-01 and contains none of the four symbols.

So the corruption is **latent, not realised**: it would enter the statistic the
first time benchmarks slippage is computed, and not before.

## 5. NEW — why the account-wide fix is BLOCKED, and what unblocks it

The intended fix is to key the dedup on the account rather than one
`books_root`. Deduping on execId account-wide is sound as far as it goes —
execId is globally unique at IBKR — but it stops the second write by letting
whichever book captures **first** own the execution. That is
first-capture-wins, which is a best guess wearing a timestamp, and this
module's own rule is that a shared ticker "is resolved by orderId or it is NOT
RECORDED... never split, apportioned or assigned to a best guess". On this
history first-capture-wins happens to give the right answer (phase0 captured
at 13:35:19, benchmarks at 21:25:08, and phase0 is the true owner) — but that
is luck, not a rule.

Doing it properly needs an account-wide order map. **The three recorded maps
cannot supply one.** Measured over all 96 rows of the three live
`_order_map.csv` files, 2026-09-10 [V]:

| key | ambiguous keys (map to >1 sleeve) |
|---|---:|
| `order_id` | 20 |
| `(asof, order_id)` | 8 |
| `(order_id, instrument)` | 1 |
| `(asof, order_id, instrument)` | 0 |
| `(instrument, asof)` | 0 |
| `perm_id` | **unusable — literally `0` on all 96 rows** |

Example collision: `(2026-09-01, order_id 3)` is `bench_b1_hyg` / HYG BUY 3 in
benchmarks **and** `cef_discount` / AWF SELL 37 in cef. IBKR order ids are
per-**clientId** sequences and the three books connect with different client
ids, so they collide by construction, not by accident.

The two keys that show zero collisions today do so **contingently**: both
`(asof, order_id, instrument)` and `(instrument, asof)` break the first day two
books trade the same ticker on the same date — which is precisely the situation
this note is about. Adopting one because it currently has no collisions is the
`z_window = 63` mistake in another costume: the argmax of a swept column.

`perm_id` is the one IBKR field that is globally unique and stable across
client ids and sessions, and the adapter records it as `0` — it is assigned
asynchronously after transmission, and `_record_order_attribution` writes the
row before that happens.

**So the blocker is upstream, in the adapter, not in `capture_fills`.** Until
`_record_order_attribution` records a globally unique order key — `perm_id`,
or at minimum `client_id` alongside `order_id` — account-wide attribution
cannot be made exact, and `capture_fills` must not pretend otherwise. Pinned by
`ops/tests/test_capture_fills_cross_book.py::test_the_order_map_cannot_key_attribution_across_books`
and `::test_perm_id_is_the_missing_global_key`, which are the tests that should
start failing when the key lands.

## 6. DECISION on the 60 already-duplicated rows: UNREPAIRED, deliberately

Stated explicitly, because a forward-only fix that leaves corrupt history in
place is exactly the thing that should not pass quietly.

They are **not repaired in this session**, for two reasons:

1. **Nothing reads them yet** (§4). The false rows sit only in
   `bench_b1_hyg` and `bench_b6_ew_credit`, neither of which has a
   `slippage.csv`. Repairing history that no statistic has consumed buys
   nothing today, and the repair is strictly easier to verify once the dedup
   that prevents recurrence exists — otherwise the next benchmarks capture
   re-creates the rows and the repair has to be redone.
2. **A dev-side ledger edit would reach prod as a code promotion, and that is
   the more dangerous fault.** The live ledgers are still **tracked in git**
   (`git ls-files ops/books/cef_live` returns 30). `ops/promote.sh` checks out
   a tag onto prod with `--merge`, so a repaired ledger committed to a tag in
   dev would overwrite prod's live record with a dev snapshot. `promote.sh`'s
   own docstring documents this hazard. The repair must therefore be applied to
   prod's ledgers directly, or after the ledgers are untracked — never shipped
   through a tag.

**What the repair would cost, if applied** — volume-weighted mean fill price
per affected sleeve, before → after removing the false copies [V]:

| sleeve | rows | shares | effect |
|---|---|---|---|
| `bench_b1_hyg` | 13 → 2 | 446 → 4 | HYG vwap 79.0617 → 79.2525 |
| `bench_b6_ew_credit` | 141 → 92 | 4,895 → 2,176 | JNK and LQD **removed entirely** (that sleeve never traded them); USHY vwap unchanged at 36.7600, 2,098 → 1,202 sh |
| `null_trader` | 677 → 677 | 33,377 → 33,377 | **unchanged** — it is the true owner of all 60 |

`null_trader` has 677 rows and 677 distinct execIds: no within-sleeve
duplicates at all. The whole of the corruption is the two benchmarks sleeves
claiming phase0's executions.

## 7. Negative results, recorded so nobody re-runs them

- **Cross-book double-booking does NOT explain the ledger-vs-broker position
  divergence.** Already established via USHY: 896 shares double-booked against
  a position gap of −11; gap + double_booked closes for no row. Two independent
  faults. *(Prior session, not re-run here — [S].)*
- **Counting duplicates without excluding `_`-prefixed sleeve directories gives
  423, and that number is meaningless** (§1). It counts archival snapshots.
  Recorded because it is the obvious way to re-measure this and it looks like a
  much worse finding.
- **`perm_id` is not a usable disambiguator today** and no composite key built
  from the current schema is structurally sound (§5). Do not adopt
  `(instrument, asof)` because it currently shows zero collisions.
