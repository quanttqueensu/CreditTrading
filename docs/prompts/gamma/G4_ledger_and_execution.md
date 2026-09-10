# G4 — The machinery: four live defects, and a ledger that survives an expiry

**Reads first:** `G0_BRIEF.md` §5, `00_BRIEF.md` §6.
**Settles:** whether an option can be booked, marked, rolled, expired, assigned
and reconciled without a human noticing. Today it cannot.
**Trials:** 0. **Touches the live book:** the executor and the ledger. No
decision logic changes, but this touches the code path that transmits orders,
so every change carries a test.
**Run second, right after G1.** G5 cannot start until this lands, and the four
defects in Part A are live now.

---

## Paste from here

You are a trading engineer on the QUANTT book. Read `docs/prompts/gamma/G0_BRIEF.md`,
then `src/deploy/sleeve.py`, `src/deploy/exec_ledger.py` (the `DerivativesLedger`
class in full), and `src/deploy/broker/ibkr.py` (`_contract`, `_order`,
`_resolve_qty`, `place_targets`, `_place_combo`).

Everything in Part A was verified against the code on 2026-09-09. Reproduce each
one before fixing it — a fix for a defect you have not seen is a guess.

---

## Part A — Four defects, all live

**A1. Every combo leg is submitted with `conId = 0`.**
`_place_combo` (line ~1130) builds each leg as

```python
con = self._contract(pt)
leg = ibi.ComboLeg()
leg.conId = getattr(con, "conId", 0)
```

but `ib_insync.Option(...)` constructed locally has `conId == 0` until
`ib.qualifyContracts()` resolves it, and **`qualifyContracts` appears nowhere in
`src/`** — verify with `grep -rn "qualifyContracts" src/`, which returns
nothing. So every BAG order carries unresolved legs and IB will reject or
mis-resolve it. **Fix:** qualify every option contract before use, cache the
resulting `conId` by `(underlier, expiry, strike, right)`, and **raise** if
qualification fails rather than proceeding with a zero. Add a test with a stub
broker asserting no leg reaches `placeOrder` with `conId == 0`.

**A2. An option with no `limit_price` becomes a limit order at $0.00.**
`_order` (line ~465):

```python
if pt.kind == OPTION:
    lim = float((pt.meta or {}).get("limit_price", 0.0))
    return ibi.LimitOrder(action, abs(qty), lim)
```

A missing key silently produces a $0.00 limit — an order that can never fill on
a buy, and is a sell-at-zero on a sell. **Fix:** raise, naming the instrument,
if `limit_price` is absent or non-positive. This is the house rule on silent
fallbacks applied to the one code path that can lose money. Note also that the
`meta["order_type"]` MOC branch below is **unreachable for options** because the
OPTION check returns first — decide whether that is intended (it probably is;
MOC is for shares) and comment it so the next reader does not "fix" it.

**A3. `_place_combo` uses a MarketOrder on the BAG.** Single option legs are
limit-only, but the combo path sends `MarketOrder(pkg_action, 1)`. That
contradicts the module's own discipline and, on a multi-leg option package, is
how you get filled at the far side of two spreads at once. **Fix:** price the
package as a limit from our own mid (G1's pricer on G2's surface) ± a stated
tick allowance, with the same raise-on-missing rule as A2.

**A4. Two stale import paths that will `ModuleNotFoundError` when exercised.**
`exec_ledger.py:770` imports `from .v2.odd_lot import odd_lot_fill_price`, but
the module lives at `src/deploy/lib/odd_lot.py`. `run_book.py:326` imports
`src/deploy/sleeves/spy_shortvol_marks`, which does not exist at all — it is
reached only when a book spec declares an `alloc_type == "short_vol_straddle"`
sleeve, and none currently does, which is why nobody has hit it. **Fix the
first; for the second, decide explicitly** whether to write the module (G5 needs
a marks provider anyway) or to remove the dead branch and the registry entry
that permits it. Do not leave a lazy import to a missing module in the tree.

While you are here, record but do not necessarily fix: `attribution.py:18`
reads `results/vrp/refute_tail_ledger_SPY.csv`, and `results/vrp/` does not
exist, so **the VOL factor in the attribution model is currently unbuildable**.
G2 Part D rebuilds the pipeline; note the dependency.

---

## Part B — Expiry, exercise and assignment

**There is no expiry handling in the ledger at all.** `grep -in
"expir\|assign\|exercis" src/deploy/exec_ledger.py` returns **zero** matches. An
option leg is marked forever by whatever `mark_fn` returns, and — worse — when
`mark_fn` returns `None`, `advance()` **stops booking days entirely**:

> `STOPPING at {d}: no usable mark for {…}. Nothing booked; resumable.`

So the first time an option expires and the mark provider stops returning a
price, the whole ledger halts. For a book whose entire design is "roll a
straddle every month", that is not an edge case; it is the second month.

Implement, in the ledger:

1. **Expiry detection** from `leg_meta["expiry"]` against the session date, on
   every `advance()`. The leg's life ends at the close of its expiration date;
   nothing about it is marked afterwards.
2. **Settlement.** At expiry, value the leg at intrinsic against the official
   close of the underlier, and book the resulting cash or share position. Use
   **G1's exercise-by-exception function** — the OCC threshold is $0.01
   in-the-money — so there is exactly one implementation of that rule.
3. **Assignment into shares.** An exercised or assigned equity/ETF option
   becomes a share position of `100 × contracts` at the strike. The ledger must
   book that share leg, and **the delta hedge must know about it on the same
   session** or the book is accidentally double-delta'd overnight. This is the
   single most likely source of a silent desync and it deserves its own test.
4. **Corporate actions on the underlier.** A split or a special distribution
   adjusts the contract's strike and multiplier. HYG, LQD and TLT distribute
   monthly, and ordinary distributions do **not** adjust listed option terms —
   note that explicitly so nobody "fixes" it — but splits and specials do.
   Detect and raise rather than silently mis-marking.
5. **A `mark_fn` returning `None` for a *live* leg must still stop the day**
   (that behaviour is correct and protects the record). But a `None` for an
   *expired* leg must not: expiry is handled before marking.

Tests: an ATM straddle held to expiry with one leg finishing $0.02 ITM books one
assignment and one lapse; a roll at 14 DTE closes the old legs and opens the new
ones with no orphaned position; the ledger's position count returns to zero
after a full cycle; and `advance()` does not stop on an expired leg.

---

## Part C — Greeks, which are threaded through six files and never called

`greeks_fn` is accepted by `register_sleeve`, stored on `MarketState`, and
passed through `portfolio.py`, `ibkr.py`, `simulator.py`, `margin_broker.py` and
`run_book.py`. **It is never invoked anywhere.** `LegGreeks` is defined in
`sleeve.py` and has no producer and no consumer.

Give it both, and pin the signature, since nothing in the code currently
specifies it:

```
greeks_fn(asof: pd.Timestamp, pt: PositionTarget) -> LegGreeks | None
```

returning `None` beyond the last available mark, exactly as `mark_fn` does, so a
sleeve reports insufficient data rather than inventing a delta. The producer
computes from **G1's module on G2's surface** — never from IBKR's model values.

Then add greeks columns to the derivatives position rows — `delta, gamma, theta,
vega` per leg and netted per underlier — so that the P&L attribution in G5 reads
from the ledger rather than being recomputed in a notebook and disagreeing with
it.

---

## Part D — Execution realism, stated once and inherited everywhere

**IBKR paper trading fills options at the displayed price, from top of book,
with no market impact, and does not support penny-increment option fills.**
Every prompt in this programme inherits three consequences:

- **Paper option fills are not execution evidence.** The *share* hedges are.
  Every note that reports an option-book P&L states this in its own words in
  its opening paragraph, not in a footnote.
- The ledger must therefore charge a **modelled** option cost regardless of what
  the broker reports, and the modelled cost is the one that goes into any
  net-of-cost figure. `option_half_spread_usd` defaults to $0.02 in the ledger
  and `costs_vrp.yaml` declares floor multipliers of 1×/2×/3×; **report at all
  three, always.** `option_spread_model.py`'s VIX-keyed curve (VIX 20 → $0.02,
  40 → $0.25, 80 → $1.00) is the stress version — use it wherever a result
  depends on crisis-period option costs, since a flat $0.02 through March 2020
  is fiction.
- **Reconcile broker fill against modelled cost on every option leg** and log
  the gap. Over 60 sessions that gap is a real measurement of how generous paper
  fills are, which is the one thing about paper option execution worth knowing.

Two more things the audit found that are **correct** and should be preserved
deliberately rather than refactored away: written option premium is excluded
from stock-borrow financing (a short option is a credit, not a borrowed asset),
and `_resolve_qty` refuses a weight-expressed option target because there is no
unambiguous weight-to-contract mapping. Add comments saying so.

## Deliverables

- The four defect fixes, each with a test that fails before and passes after.
- Expiry, settlement and assignment in `DerivativesLedger`, with the four tests
  above.
- A `greeks_fn` producer, the pinned signature, and greeks columns on the
  position rows.
- The modelled-vs-broker option cost reconciliation and its log.
- `results/gamma/LEDGER_HARDENING_<date>.md`: what each defect was, how it was
  reproduced, what the fix is, and the test that holds it. Plus the explicit
  decision on `spy_shortvol_marks` — written or removed.

## Do not

- Do not let a missing `limit_price`, an unqualified contract, or an unpriceable
  leg proceed silently. Raise, naming the instrument.
- Do not remove the "stop the day on a missing mark for a live leg" behaviour;
  it protects the record.
- Do not use IBKR model greeks to populate `LegGreeks`.
- Do not report a paper option fill as evidence of executable cost.
- Do not charge stock-borrow on written option premium.
