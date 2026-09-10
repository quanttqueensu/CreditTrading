---
name: fill-audit
description: Analyse realised execution cost from broker-confirmed fills — slippage versus modelled, split by session and method, with the standard error. Use when asked what execution actually costs, whether the MOC switch worked, or to check kill-rule condition (b).
allowed-tools: Bash(python3 *) Read Grep Glob
---

# Fill audit

## The record

```!
python3 - <<'PY'
import csv, collections, pathlib, statistics
p = pathlib.Path("ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv")
if not p.exists():
    raise SystemExit("no broker_fills.csv — no real executions on record")
rows = [r for r in csv.DictReader(p.open(newline="")) if r.get("fill_date")]
by = collections.defaultdict(list)
for r in rows:
    by[r["fill_date"]].append(r)
print(f"{len(rows)} broker-confirmed executions across {len(by)} session(s)\n")
print(f"{'date':<12}{'fills':>6}{'names':>7}{'gross $':>14}{'commission':>12}{'bp of gross':>13}")
for d in sorted(by):
    rs = by[d]
    gross = sum(abs(float(r["qty"])) * float(r["price"]) for r in rs)
    comm = 0.0
    for r in rs:
        note = r.get("note") or ""
        if "commission=" in note:
            try:
                comm += float(note.split("commission=")[1].split()[0])
            except (ValueError, IndexError):
                pass
    bp = 1e4 * comm / gross if gross else float("nan")
    print(f"{d:<12}{len(rs):>6}{len({r['instrument'] for r in rs}):>7}"
          f"{gross:>14,.0f}{comm:>12,.2f}{bp:>13.2f}")
PY
```

## Slippage as logged

```!
python3 - <<'PY'
import pathlib
p = pathlib.Path("ops/books/cef_live/_ibkr_shadow/cef_discount/slippage.csv")
if not p.exists():
    print("no slippage.csv yet")
else:
    lines = p.read_text().strip().splitlines()
    print(lines[0])
    for line in lines[-12:][1:] if len(lines) > 12 else lines[1:]:
        print(line)
PY
```

---

## How to read this, and the trap

**Never quote the pooled `realised/modelled` ratio.** The logged **4.59×** averages
the pre-MOC disaster that *caused* the switch to MOC. Split by session and method,
always:

| session | fills | method | realised | modelled |
|---|---:|---|---:|---:|
| 2026-07-31 | 16 | overnight market orders — **abandoned** | **120.6bp** | 15.5 |
| 2026-09-01 | 15 | MOC | **2.8bp** | 12.1 |

The 2026-07-31 orders rested overnight and filled at 07:27 ET, two hours before the
exchange opened, at up to 2.9% from the decision price. That is the signature of
crossing a wide spread with no liquidity present, not of a bad model.

## The numbers that frame every answer

- **Breakeven: 32.6bp** per unit turnover full-sample, 28.9bp for 2021–26.
- **n = 1** for the live method. Dispersion ±93.8bp. Everything about whether this
  strategy is viable turns on this number, and we have one observation of it.
- **Cost converges ~60× faster than Sharpe.** At ~15 fills/session, 60 sessions
  gives **SE ≈ 0.84bp**. This is the fastest-converging statistic available, which
  is why accumulating the fill record outranks nearly all research.
- **Commission is real and the backtest ignores it.** `config/costs.yaml` carries
  `commission_usd_per_trade: 0.0`; IBKR charges a **$1 minimum per order**, which
  is exactly what makes `min_trade_usd` $517.

## Kill rule (b)

*Realised slippage > 2× modelled for **5 consecutive sessions**.* Graded at the
60-session review and **not before** — a comfortable-looking reading off two weeks
of data is worse than no reading at all. Count consecutive sessions on
broker-confirmed fills only.

## What is not evidence

- **Modelled fills.** 22 of 24 ledger trade dates are modelled fills for sessions
  that never traded.
- **Paper fills as a cost model.** IBKR paper fills from top of book with no dealer
  layer and no impact — unrealistically kind. The shadow ledger with its modelled
  cost stays the sole P&L source; this audit is a side channel.
- **A day with zero fills.** Check whether it was a band-HOLD day (no order is the
  correct outcome) before recording it as a miss.

## Divergences to account for

The live path drops orders below `min_trade_usd` ($517), rounds to shares, is
capped by borrow availability on the short leg, and faces a closing auction where
**~3.3% of NYSE volume goes unfilled, rising to 6.3% for non-Russell-1000 names** —
which all seventeen of ours are. A backtest that ignores these overstates capture.
