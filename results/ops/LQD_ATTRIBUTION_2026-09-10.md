# The 858-share LQD short is NOT an orphan. It is `null_trader`'s, and every share is broker-confirmed.

**Measured 2026-09-10 evening, dev tree. No broker connection was opened** —
the broker side comes from `results/ops/BROKER_SNAPSHOT_2026-09-10.json`
(read-only, clientId 115, read 11:35:29 ET). Provenance: `[V]` verified by
re-running the command shown, `[S]` sourced not re-read, `[U]` uncertain.

## The question

`results/ops/HALT_PHASE0_ATTRIBUTION_2026-09-10.md:34` and
`~/prod/QUANTT/ops/HALT_phase0_null.md` both record LQD as **ledger −23 vs
broker −881**, an 858-share short worth **$89,841.18** that "no ledger claims",
and the halt file asks the team lead for **"an attribute-or-flatten call"**.

**That call is not needed. Flattening would be wrong.**

## The answer, in one line

`null_trader` really is short **904** LQD, every share of it confirmed by a
broker execId. Its ledger says **−46** because a **BUY 861 that never executed
was booked as filled** on 2026-09-10. The short was never unattributed; the
ledger lost its own paperwork.

## The arithmetic, and it closes exactly [V]

| quantity | shares |
|---|---:|
| `null_trader`, summed from its own broker-confirmed execIds | **−904** |
| `bench_b6_ew_credit` ledger claim | **+23** |
| **sum** | **−881** |
| **broker account net (snapshot)** | **−881** |

The account net closes **to the share**. There is no orphan in it.

And within `null_trader`, the gap is one booking:

```
ledger −46  −  phantom BUY 861  =  −907
broker-confirmed                =  −904
residual                        =     3 shares
```

The 3-share residual is pre-existing modelled drift from the August period when
TWS was down and the ledger advanced on simulated fills.

## The evidence, item by item [V]

Reproduce (read-only, no broker, ~1s) — this is the block that produced every
number above:

```bash
cd ~/Desktop/2027/QUANTT/2027 && python3 - <<'PY'
import json, pandas as pd, csv
snap=json.load(open("results/ops/BROKER_SNAPSHOT_2026-09-10.json"))
print("LQD executions in today's TWS session:",
      len([e for e in snap["executions_this_tws_session"] if e["symbol"]=="LQD"]))
print("resting orders:", [(o["symbol"],o["action"],o["totalQuantity"],o["orderType"])
                          for o in snap["open_orders"]])
d=pd.read_csv("ops/books/phase0_live/_ibkr_shadow/null_trader/broker_fills.csv")
lq=d[d.instrument=="LQD"]
print("null_trader LQD execIds:", len(lq),
      "signed:", (lq.qty*lq.side.map({"BUY":1,"SELL":-1})).sum())
for r in csv.DictReader(open("ops/books/phase0_live/_ibkr_shadow/_order_map.csv")):
    if r["instrument"]=="LQD": print("order_map:", r["asof"][:10], r["order_id"], r["action"], r["qty"])
PY
```

1. **20 LQD execIds exist, all `null_trader`'s**, summing to −904: −42 on
   2026-07-31 and −862 on 2026-09-08. 20 rows, 20 distinct execIds, no
   within-sleeve duplication.
2. **The 862 matches an order exactly.** `_order_map.csv` records
   `2026-09-08, order_id 9, null_trader, LQD, SELL, 862.0` at
   `13:35:18.038863+00:00`; the 18 executions are timestamped `13:35:18Z`.
3. **The 2026-09-10 order never executed.** `_order_map.csv` records
   `2026-09-10, order_id 25, null_trader, LQD, BUY, 863.0` at
   `13:43:09.171008+00:00`. The snapshot holds **572 executions for that
   session across nine symbols — BKLN, IGSB, SHYG, SJNK, SPHY, SRLN, USHY,
   VCIT, VCSH — and LQD is not one of them.** Nor is it resting: the only four
   open orders are CEF MOC legs (JFR, MHD, MQY, NEA).
4. **The ledger booked it anyway.** `trades.csv` carries
   `2026-09-10, LQD, BUY, 861.0 @ 104.728963` — a *modelled* price, for an
   order with no execution and no resting remainder. `positions.csv` then reads
   `2026-09-10, LQD, −46.0`.

So LQD is the fifth member of the phantom-fill class already recorded in
`results/ops/LEDGER_DIVERGENCE_2026-09-10.md:233` alongside JAAA, HYG, JNK and
EMB — **not** a separate "held at the broker, claimed by nobody" case.
`LEDGER_DIVERGENCE` had this right on 2026-09-10 at 11:50; the attribution note
written at 16:01 and the halt file amended at 16:04 both put LQD in the wrong
class.

## Why `arm()` will NOT repair this one, and JAAA's mechanism is not the reason

Worth stating precisely, because the two look alike and are not.

- **JAAA**: the broker reports **no position row at all** for a flattened
  symbol, so `arm()`'s re-seed loop never visits it and the stale ledger
  quantity survives.
- **LQD**: the broker *does* report −881, so `arm()` visits it — and then
  **deliberately declines to adopt it**, because LQD is **contested**:
  `bench_b6_ew_credit`'s frozen universe is
  `['ANGL','EMB','HYG','JNK','LQD','SHYG','USHY','VCIT']`. The account net is
  not one book's to take (CLAUDE.md landmine 7), so `arm()` falls back to the
  ledger. Observed rather than inferred: the 2026-09-10 run's
  `target_vs_current.csv` shows LQD `current_qty −908.0` — the ledger, not
  −881 and not −904. **[S]** — reported by the forensic pass; I verified the
  contested-universe fact and the ledger values, not that CSV.

Consequence: the next armed phase0 session would size LQD from **−46** against
a real **−904**, i.e. roughly **858 shares (~$89.8k)** of unintended
correction. This is a **trading** fault, same severity class as JAAA, different
mechanism. It is why `ops/HALT_phase0_null.md` must stay in place.

## The remediation, and what it is not

**Do not flatten.** Flattening the account net would be wrong twice: the real
position is `null_trader` −904 plus someone's +23, and the discrepancy would be
re-created by the next armed session anyway, because the cause is the ledger,
not the position.

The correct fix is the one the halt document already prescribes for the other
four and explicitly excluded for LQD: **rebuild `null_trader`'s ledger from its
own `broker_fills.csv`.** That transmits nothing. Once done the ledger reads
−904, the broker reads −904, and there is no position decision left to make.

## The one genuinely unresolved piece: `bench_b6_ew_credit`'s +23 [U]

Not the 858 — **23 shares, ~$2,408**.

`bench_b6`'s +23 is **not broker-confirmed**: no LQD execId appears in any
`bench_*` `broker_fills.csv` before the 2026-09-08 duplicates, and
`benchmarks_live/_ibkr_shadow/_order_map.csv` has **no LQD row, ever**. Its
recorded fill price (106.26…) is a simulator price, not the real 2026-07-31
print of 106.02.

Yet the account net closes only if a real +23 exists, and IBKR's own
`avgCost 105.5430874` on −881 is consistent with a pre-existing 23-share long
that predates fill capture entirely (capture began 2026-07-31 21:20 UTC; TWS
retains nothing earlier). **[S]** for the avgCost reconciliation — reported by
the forensic pass, arithmetic not re-derived here.

**What would settle it, and where it lives:** an IBKR Flex Query or activity
statement for DUQ199038 covering 2026-07-01 → 2026-07-31. `reqExecutions()`
cannot reach back that far, and no such statement exists anywhere in this repo.
Until one is fetched, the +23 stays `[U]`. **It is 23 shares and it is not the
question the halt file asked.**

## Negative results — recorded so nobody re-runs them

- **N1. "The retired `credit_rv` book holds the orphan LQD." FALSIFIED.** All
  20 LQD execIds are `null_trader`'s and the 862 block matches its order map to
  the share. `credit_rv` was killed 2026-07-30, one day *before* the earliest
  LQD execution, and `ops/books/retired/README.md` states it never held a
  share. After attributing both blocks the residual is +23, not −858 — there is
  no room for a `credit_rv` position of any size.
- **N2. "Cross-book double-booking explains the LQD position gap." FALSIFIED —
  and this is the trap, because the arithmetic nearly closes.** LQD has **862**
  shares double-booked and a gap of **−858**; `−858 + 862 = +4` *looks* like
  closure and is coincidence — both trace to the same 862-share order by two
  unrelated routes. Mechanism-level proof: `ops/capture_fills.py` writes only
  `broker_fills.csv` and `slippage.csv`. It never touches `positions.csv`,
  `orders.csv`, `trades.csv` or `nav.csv`, so a duplicated capture **cannot**
  move a position ledger. Same verdict as the earlier USHY control (896
  double-booked against a gap of −11); LQD is the case where the numbers nearly
  line up and it is *still* false.
- **N3. "`dur_hedged_overlay` bought 564 LQD."** FALSIFIED. That run was
  `DRY_RUN=1, EXECUTION=simulator` into a throwaway books-root deleted three
  lines later. Only four phase0 logs ever carry `EXECUTION=ibkr`: 07-31, 09-08,
  09-09 (NOT ARMED) and 09-10.
- **N4. "`bench_b6`'s +23 is broker-confirmed."** FALSIFIED — see above. It is a
  simulator backfill that happens to coincide with a real +23, which is exactly
  why the account-level view netted to a clean −858 and looked like one orphan.

## Governance

**This is forensic attribution of an existing position, not a research trial.**
No parameter was swept, no specification was tested against returns, and
nothing here feeds a signal. **The CEF counter stays at 48 and GAMMA at 0.**
