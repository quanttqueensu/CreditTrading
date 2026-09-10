---
name: book-status
description: Full readout of what the live book is doing right now — broker-confirmed fills, heartbeat, halt state, preflight blockers, ledger-vs-broker disagreement, and today's session log. Use when asked how the book is doing, whether it traded, what happened today, or before starting any work that assumes the book is healthy.
allowed-tools: Bash(python3 .claude/hooks/book_state.py*) Bash(python3 -m ops.doctor*) Bash(python3 -m ops.preflight*) Bash(cat ops/heartbeat.json) Bash(tail *) Read Grep Glob
---

# Book status

## Live state

```!
python3 .claude/hooks/book_state.py -p
```

## Today's session log (tail)

```!
ls -t ops/schedule/logs/cef_*.log 2>/dev/null | head -1 | xargs tail -25 2>/dev/null || echo "no cef log found"
```

## Recent broker-confirmed fills

```!
python3 - <<'PY'
import csv, collections, pathlib
p = pathlib.Path("ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv")
if not p.exists():
    print("no broker_fills.csv — the book has never recorded a real execution")
else:
    rows = list(csv.DictReader(p.open(newline="")))
    by = collections.Counter(r["fill_date"] for r in rows if r.get("fill_date"))
    print(f"{len(rows)} executions across {len(by)} session(s)")
    for d in sorted(by)[-6:]:
        same = [r for r in rows if r.get("fill_date") == d]
        gross = sum(abs(float(r["qty"])) * float(r["price"]) for r in same
                    if r.get("qty") and r.get("price"))
        names = len({r["instrument"] for r in same})
        print(f"  {d}: {by[d]:>4} fills, {names:>2} names, ${gross:,.0f} traded")
PY
```

---

## How to read this

**`gap_sessions` is the number that matters.** It is trading days since the last
*broker-confirmed* fill — not since the last session, log line, heartbeat or ledger
row. Between 2026-08-03 and 2026-08-28 the book ran 21 consecutive sessions that
logged "ok", wrote a heartbeat and advanced a ledger with modelled fills, and traded
nothing, because the config pointed at TWS 7497 while the gateway served 4002.
Preflight refused correctly every time. Nobody was reading preflight.

- **0–2 sessions** — trading normally.
- **3–5** — check. Was there a holiday? Did preflight block?
- **6+ or none** — it is not trading. Escalate to `/preflight`, then the
  `ops-watchdog` subagent.

**A non-armed session is silent by design.** It writes `ok_not_armed` and raises no
alert. That is the failure mode this readout exists to defeat, and making it loud is
the highest-value operational fix outstanding.

**The shadow-ledger NAV is a local reconstruction; the account is the fact.**
When the two diverge, order *sizing* is unaffected because `arm()` re-seeds from
`ib.positions()` before every session, but reported NAV and P&L are wrong. Quote
ledger P&L as indicative and say so.

**Do not carry a divergence magnitude from memory or from a document.** The
figure that circulated for weeks — "all 17 positions, ~$223k account-wide" —
predates the 2026-09-08 epoch re-seed and no longer reproduces. Measured
2026-09-10 against a broker snapshot: **none of the 17 CEFs diverge.** Every
divergent symbol belongs to `null_trader` and the benchmark books, and five of
those are *phantom fills* — orders the ledger booked as filled that produced no
execution at all. Re-measure before quoting:

```bash
python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json \
    --books-root ops/books/cef_live --check-broker
```

**Modelled fills are not evidence.** 22 of 24 ledger trade dates are modelled fills
for sessions that never traded. Only rows in `broker_fills.csv` count toward any
live statistic.

## If something is wrong

| symptom | next step |
|---|---|
| halt active | read `ops/HALT.md` and the matching `ops/halts/HALT_*.md`; do not clear it yourself |
| gap ≥ 3 sessions | `/preflight`, then the `ops-watchdog` subagent |
| heartbeat job `failed`/`stale` | `python3 -m ops.doctor --quick` |
| ledger ≠ broker | `python3 ops/reconcile_orders.py` — expected today; note it, do not "fix" the ledger |
| fills captured 0 on an armed day | check whether it was a band-HOLD day (no order is correct) before assuming a fault |
