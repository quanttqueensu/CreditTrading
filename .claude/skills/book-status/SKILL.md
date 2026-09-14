---
name: book-status
description: Full readout of what the live book is doing right now — broker-confirmed fills, heartbeat, halt state, preflight blockers, ledger-vs-broker disagreement, and today's session log. Use when asked how the book is doing, whether it traded, what happened today, or before starting any work that assumes the book is healthy.
allowed-tools: Bash(python3 -m ops.orient*) Bash(python3 .claude/hooks/book_state.py*) Bash(python3 -m ops.doctor*) Bash(python3 -m ops.preflight*) Bash(cat ops/heartbeat.json) Bash(tail *) Read Grep Glob
---

# Book status

## Live state

```!
python3 .claude/hooks/book_state.py -p
```

## Halts, in both trees

Halts are written in **prod** and are untracked; a dev-only `ls` shows nothing
while prod is halted.

```!
python3 -m ops.orient --no-tests 2>/dev/null | sed -n '/^HALTS/,/^$/p'
```

## The newest session log, from either tree (tail)

```!
ls -t ~/prod/QUANTT/ops/schedule/logs/cef_*.log ops/schedule/logs/cef_*.log 2>/dev/null | head -1 | xargs tail -25 2>/dev/null || echo "no cef log found in either tree"
```

## Recent broker-confirmed fills

```!
python3 - <<'PY'
import csv, collections, pathlib
# Prod writes the evidence file; dev's tracked copy stops at the last promotion.
rel = "ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv"
trees = [pathlib.Path.home() / "prod/QUANTT", pathlib.Path(".")]
p = next((t / rel for t in trees if (t / rel).exists()), None)
if p is None:
    print("no broker_fills.csv in either tree — no real execution on record")
else:
    print(f"[{p}]")
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

**A non-armed session raises no alert of its own.** It writes `ok_not_armed`.
Since the W3 go-live, `ops/verify_session.py` FAILs a day on which no deciding job
armed and sends one message per trading day; whether that message leaves the
machine is `python3 -m ops.doctor --quick`. This readout still exists to catch the
day nobody reads it.

**The shadow-ledger NAV is a local reconstruction; the account is the fact.**
Quote ledger P&L as indicative and say so. And a divergence can reach order
*sizing*: `arm()` re-seeds from `ib.positions()`, which has no row for a symbol the
broker holds none of, so a stale ledger quantity there goes unchallenged
(`CLAUDE.md` landmine 3).

**Do not carry a divergence magnitude from memory or from a document** — every
one this desk has written down went stale within days, including one taken
mid-session and never re-taken. Re-measure before quoting (opens a broker socket):

```bash
python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json \
    --books-root ops/books/cef_live --check-broker
```

**Modelled fills are not evidence.** Only rows in `broker_fills.csv` count toward
any live statistic.

## If something is wrong

| symptom | next step |
|---|---|
| halt active | read the halt file orient HALTS names (in prod) — every entry; do not clear it yourself |
| gap ≥ 3 sessions | `/preflight`, then the `ops-watchdog` subagent |
| heartbeat job `failed`/`stale` | `python3 -m ops.doctor --quick` |
| ledger ≠ broker | `python3 ops/reconcile_orders.py` — expected today; note it, do not "fix" the ledger |
| fills captured 0 on an armed day | check whether it was a band-HOLD day (no order is correct) before assuming a fault |
