# phase0 halt — the divergence is two faults, and the halt file mislabels three of five symbols

**Written 2026-09-10, dev tree. Read-only: no broker connection was opened for
this note.** Every figure below is recomputed from
`results/ops/BROKER_SNAPSHOT_2026-09-10.json` (a read-only probe at
**11:35:29 ET**, 34 position rows) and from the books' own `positions.csv`
ledgers. Reproduce with the script block at the bottom.

## Why this note exists

`~/prod/QUANTT/ops/HALT_phase0_null.md` blocks `phase0_null`, correctly, and its
share counts are right. **Its characterisation of $182.6k of that divergence is
not**, and the error changes what has to be done to clear it.

The halt says:

> The account holds what no ledger claims. LQD 858 sh, HYG 604, JNK 420,
> EMB 58 — about $182.6k — exist at the broker and are claimed by no book's
> ledger at all.

For **LQD that is true**. For **HYG, JNK and EMB it is backwards**: the ledgers
claim *more* than the broker holds. Those are phantom ledger positions — the
same fault as JAAA — not unattributed broker positions.

## Measured

Broker from the 11:35 snapshot; ledger is the sum of the latest `positions.csv`
row across every live sleeve; marks are the phase0 ledger's own 2026-09-10
closes, as the halt used.

| sym | broker | Σ ledgers | gap | abs $ | which way it is wrong |
|---|---:|---:|---:|---:|---|
| JAAA | 0 | −1,503 | **+1,503** | 76,021.89 | ledger claims what the broker does **not** hold |
| LQD | −881 | −23 | **−858** | 89,841.18 | **broker holds what no ledger claims** |
| HYG | 383 | 987 | **−604** | 47,558.96 | ledger claims what the broker does **not** hold |
| JNK | 26 | 446 | **−420** | 39,782.40 | ledger claims what the broker does **not** hold |
| EMB | 550 | 608 | **−58** | 5,427.35 | ledger claims what the broker does **not** hold |
| | | | | **258,631.78** | matches the halt's top-five total exactly |

Per-sleeve, so the overclaim is attributable:

```
JAAA  null_trader −1503
LQD   bench_b6_ew_credit +23,  null_trader −46
HYG   bench_b1_hyg +252, bench_b6_ew_credit +31, null_trader +704
JNK   bench_b6_ew_credit +26, null_trader +420
EMB   bench_b6_ew_credit +26, null_trader +582
AGG   bench_b3_agg +206 vs broker 205  (−1, the halt's unpriced row)
```

## The split that matters for remediation

| | $ | what fixes it |
|---|---:|---|
| **ledger overclaim** — JAAA, HYG, JNK, EMB | **168,790.60** | rebuilding the ledger from broker-confirmed executions. No position decision, no order. |
| **genuinely unattributed** — LQD short | **89,841.18** | a decision: attribute the 858-share short to a book, or flatten it. **Flattening transmits an order.** |

The halt's remediation paragraph asks for both at once ("the ~$182.6k of
unattributed LQD/HYG/JNK/EMB has to be attributed to a book or deliberately
flattened"). **Three quarters of that figure needs neither** — it needs the
ledger corrected downward. Only LQD is a position question, and it is
$89.8k, not $182.6k.

## A second finding: there is no `credit_rv` ledger at all

`credit_rv.frozen.json` claims all five of JAAA, LQD, HYG, JNK and EMB, and
`credit_rv_book.json` is retired to `ops/books/retired/`. **No `credit_rv`
sleeve ledger exists anywhere under `ops/books/*_live/_ibkr_shadow/`.** So if
that book ever held these names, its positions have no ledger and would present
exactly as "held at the broker, claimed by nobody" — which is the LQD signature.
**This is a hypothesis, not a finding**: it is consistent with LQD, and it is
*not* tested here, because testing it needs the broker's execution history and
this note opened no connection.

## Staleness, which bounds all of the above

* snapshot **11:35:29 ET**; the halt's own probe was **~12:50–13:00 ET**. Both
  produce the same five gaps, so neither is an artifact of timing.
* `null_trader` ledger asof **2026-09-10**; `cef_discount` **2026-09-09**; all
  five `bench_*` ledgers asof **2026-09-08**, i.e. two sessions stale. A stale
  bench ledger inflates an overclaim it did not cause.

## What this does NOT change

**The halt stands. Do not clear it.** The JAAA mechanism is unaffected: the
broker emits no row for a flat symbol, so `arm()`'s
`for sym, qty in account.items()` never visits JAAA, the −1,503 survives into
`place_targets`, and phase0 fires 09:35 Friday 2026-09-11 at `DRY_RUN=0`.
Nothing in this note makes that safer.

## Reproduce

```bash
python3 - <<'PY'
import json,glob,csv,os
from collections import defaultdict
snap=json.load(open("results/ops/BROKER_SNAPSHOT_2026-09-10.json"))
broker={r["symbol"]: r["position"] for r in snap["positions_account_net"]}
def f(x):
    try: return float(x)
    except (TypeError,ValueError): return 0.0
led=defaultdict(dict)
for pf in glob.glob("ops/books/*_live/_ibkr_shadow/*/positions.csv"):
    s=os.path.basename(os.path.dirname(pf))
    if s.startswith("_pre"): continue
    rows=[r for r in csv.DictReader(open(pf)) if r.get("date")]
    if not rows: continue
    last=max(r["date"] for r in rows)
    for r in rows:
        if r["date"]==last and r.get("ticker"): led[s][r["ticker"]]=f(r.get("shares"))
for sym in ("JAAA","LQD","HYG","JNK","EMB","AGG"):
    b=broker.get(sym,0.0)
    parts={s:v[sym] for s,v in led.items() if v.get(sym)}
    print(f"{sym:5s} broker {b:8.0f}  ledgers {sum(parts.values()):8.0f}  gap {b-sum(parts.values()):8.0f}  {parts}")
PY
```
