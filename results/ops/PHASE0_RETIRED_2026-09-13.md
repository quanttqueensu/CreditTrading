# Retiring `phase0_null` — the prepared sequence

**Reproduce:** `python3 -m pytest src/deploy/tests/test_null_trader_winddown.py`
pins the mechanism in §3; `python3 -m ops.gamma_status` prints the margin figures
in §4 step 7. The position table in §1 is a read of prod's
`ops/books/phase0_live/_ibkr_shadow/null_trader/positions.csv`.

**Prepared 2026-09-13. NOT EXECUTED.** Everything below that could be verified
without transmitting an order has been. The steps that reach the book are for
the team lead to run, and they are marked **HUMAN**.

`phase0_null` is the Phase 0 control experiment: a random-signal, dollar-neutral
trader whose expected net P&L is minus costs. It has been halted since
2026-09-10, cannot trade, and is still holding the largest single block of
margin on the account while producing no data. That is the case for retiring it.

---

## 1. The precondition, measured

CLAUDE.md landmine 3 requires one check before anything touches this book:
prod's ledger must read **`LQD −907` with no `JAAA` row**. Measured now against
`~/prod/QUANTT/ops/books/phase0_live/_ibkr_shadow/null_trader/positions.csv`,
last block **2026-09-10**:

**PASS.** `LQD −907.0` is present; there is **no `JAAA` row**. The unbook repair
described in `NULL_TRADER_UNBOOK_2026-09-10.md` reached prod, and the phantom
1,503-share JAAA short that this halt exists to contain is gone from the ledger.

| | |
|---|---:|
| positions | 12 |
| long market value | $226,430.03 |
| short market value | −$334,473.53 |
| **gross** | **$560,903.55** |
| net | −$108,043.50 |
| cash | $749,197.74 |

**This is the LEDGER, and the ledger is not the authority.** The broker is. The
last read-only broker snapshot predates the 2026-09-10 session that produced
these rows, so it cannot confirm them, and that is exactly why step 1 below is a
broker read and not a spec edit.

---

## 2. The trap — `"enabled": false` does NOT wind this down

The obvious move is wrong, and it fails silently. `Orchestrator.advance`
(`src/deploy/portfolio.py:150-151`) reads:

```python
disabled_now = name in self.disabled
if not disabled_now and name not in self.enabled:
    continue
```

A sleeve in `self.disabled` keeps advancing and places **FLAT** for everything
it holds until the position is gone (`portfolio.py:181-189`). But `self.disabled`
is populated in exactly one place — `risk.py:75`, at runtime, on a KILL verdict.
**No config key reaches it.** Setting `"enabled": false` in
`ops/books/phase0_book.json` puts the sleeve in *neither* set, so `advance`
**skips it entirely**: the 12 positions and $560,903 of gross stay on the
account, unmanaged, with nothing left in the system that would ever close them.

**Wind down first, disable second.** Pinned by
`src/deploy/tests/test_null_trader_winddown.py`, including a test that asserts
the skip condition still has the shape this argument depends on.

---

## 3. The mechanism that does work, verified

Take the sleeve's gross to zero and leave it enabled. Every weight then falls
below `min_abs_weight`, and `null_trader.py:95-96` returns an **explicit FLAT
for every name in the universe**:

| `gross_leverage` | targets | sides | non-zero weights |
|---|---:|---|---:|
| **1.0** (live today) | 14 | 8 LONG, 6 SHORT | 14 |
| **0.0** (the change) | 14 | **14 FLAT** | **0** |

Explicit FLAT matters. An empty target list would also close the book, but only
via the broker's held-but-unmentioned branch (`ibkr.py:988`) — the same path
that would have sent BUY 1,503 against a phantom JAAA short. **Omission infers
the intent; FLAT states it.** All 14 universe names are named, so no held symbol
can be missed.

JAAA is in the sleeve's universe and held nowhere. A FLAT target against a zero
position produces no order.

---

## 4. The sequence

**1. HUMAN — confirm the broker agrees, read-only.** Nothing below is safe on
the ledger's word alone.

```bash
python3 -m ops.reconcile_orders --book ops/books/phase0_book.json \
        --books-root ops/books/phase0_live --check-broker
```

Expect the 12 symbols above and **no JAAA**. If the broker shows a JAAA
position, **stop** — the premise of this whole document is wrong and the halt
stays up.

**2. Me — the spec change, in dev.** One key in
`ops/specs/null_trader.frozen.json`: `frozen.gross_leverage` **1.0 → 0.0**. This
is a governance object, so it is a visible, single-key, reviewable edit and
nothing else moves. I have not made it yet — it should be made against a broker
read that confirms step 1.

**3. HUMAN — promote.** `ops/promote.sh <tag>`. Prod is at `v2026.09.13.1`; the
spec change has to cross the gate like any other, and prod is what trades.

**4. HUMAN — clear the scoped halt**, with a note saying why it is now safe:

```bash
python3 -c "from ops.halt import clear_halt; clear_halt('phase0 wind-down: ledger repaired (LQD -907, no JAAA), gross_leverage 0.0, flattening to retire', book='phase0_null')"
```

Run it **in prod**, where the halt file lives. The halt exists because the
ledger over-claimed; that condition is measured resolved in §1.

**5. The next phase0 session flattens the book.** It runs at `DRY_RUN=0`,
`EXECUTION=ibkr` (`ops/schedule/phase0.env`), so it will place real MOC orders
on the paper account. **The trade phase is not idempotent** — one session, and
do not re-run it. NYSE MOC cannot be cancelled after 15:50 ET.

**6. HUMAN — verify flat, then disable.** Once `positions.csv` and the broker
both show nothing, `"enabled": false` in `ops/books/phase0_book.json` is safe,
because there is no longer a position to abandon. Not before.

**7. Re-measure the margin cushion.** `python3 -m ops.gamma_status` prints it.
This is the point of the exercise: the cushion was **0.165** against preflight's
**blocking** 0.10 floor, with slack down 49% in three days. That floor is
account-wide, so when it trips it stops the **$500k CEF book**, not the book
that drew the margin.

---

## 5. What I have not done, and will not

- No order was transmitted and no broker socket was opened by anything in this
  document. The ledger read is a file read.
- I have **not** edited the frozen spec. Step 2 is written but unapplied,
  because it should follow the broker confirmation in step 1 rather than
  precede it.
- I have **not** cleared the halt or touched prod.
- The gross figure is the **ledger's**. Until step 1 runs, treat it as an
  estimate with a known direction of error: this ledger has over-claimed before,
  by $168,790.60, which is what the halt file itself records.
