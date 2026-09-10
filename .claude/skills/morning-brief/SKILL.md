---
name: morning-brief
description: The pre-session brief — book state, data freshness, what the signal wants today, borrow and availability constraints, and anything that would stop the session. Use at the start of a trading day or before a decision window. Read-only; it computes and reports, it never trades.
allowed-tools: Bash(python3 *) Bash(curl -s http://127.0.0.1:8787/api/*) Read Grep Glob
---

# Morning brief

The standing decision (from Thursday 2026-09-10) is **morning primary, evening
fallback**: decide at 08:30 on yesterday's complete price/NAV pair, MOC for today's
close; 12:00 retry; 17:30 capture.

## 1. Is the book alive

```!
python3 .claude/hooks/book_state.py -p
```

## 2. Is the data current enough to decide

```!
python3 - <<'PY'
import pathlib, datetime
try:
    import pandas as pd
except ImportError:
    raise SystemExit("pandas unavailable")
rows = []
for label, rel in [("prices", "data/cef/cef_prices.parquet"),
                   ("NAV", "data/cef/cef_nav.parquet")]:
    p = pathlib.Path(rel)
    if not p.exists():
        rows.append((label, "MISSING", "")); continue
    d = pd.to_datetime(pd.read_parquet(p, columns=["date"])["date"])
    last = d.max().date()
    age = (datetime.date.today() - last).days
    rows.append((label, str(last), f"{age}d old"))
b = pathlib.Path("data/cef/cef_borrow.csv")
rows.append(("borrow", str(datetime.date.fromtimestamp(b.stat().st_mtime)) if b.exists() else "MISSING", ""))
for r in rows:
    print(f"  {r[0]:<8} {r[1]:<14} {r[2]}")
print("\nThe pair must be COMPLETE and SAME-DATE for every deployed name.")
print("A stale NAV is a blind signal, not a cheap fund — the session stands down.")
PY
```

## 3. Preflight

```!
python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live --quiet-alerts 2>&1 | tail -18
```

---

## What to check, and why

**Data completeness gates everything.** The sleeve decides only when every deployed
name has that day's NAV. Measured 2026-09-08: yfinance publishes the day's NAVs at
~22:45 ET, in one batch; CEFConnect later still. If the pair is not complete by
`NAV_DEADLINE` the session **stands down and alerts** — it never trades on a lagged
pair. IB Gateway auto-restarts at 03:00, so anything before ~02:30 is safe.

**CEFConnect italicises a NAV whose published date is earlier than the row's date.**
Capture the NAV's own as-of date, never just its value.

**Bond-market holidays on which the NYSE trades** — Columbus/Indigenous Peoples'
Day, Veterans Day — produce a mechanical discount swing: price moves, NAV carries
forward stale. Know whether today is one before reading the signal.

**HYT lags the price panel by a day.** `px.iloc[-1]` can be NaN; use
`px.ffill().iloc[-1]` where a name's own last close is needed.

## Constraints that bind before the signal does

- **Borrow availability**, not cost, is what stops a short. NAD's pool supports
  ~$45,000 of capital against an 8,129-share short; at $500k, **11.4% of the desired
  short book is unbuildable**. Check availability before assuming a target is
  reachable.
- **Recall risk is monthly**, not occasional — all seventeen distribute monthly and
  muni lenders lose the exempt-interest character on a payment in lieu, so they have
  a standing incentive to recall before the record date.
- **`min_trade_usd` = $517.** Anything smaller is skipped and the name sits inside
  the band until its gap is worth closing. A skipped dust order is correct
  behaviour, not a fault.
- **The 15:50 ET MOC cutoff moves with early closes** — it is defined as ten minutes
  before the end of Core Trading Hours. After it, MOC cannot be cancelled or reduced.

## If you are asked what the book should do today

Compute it and report it. **Do not run the live session** — the entry point and the
schedule wrappers transmit real MOC orders at RUNG-2, and the trade phase is not
idempotent. Name the command and let the operator run it with `! <command>`.
