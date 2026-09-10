# The ledger now books the broker's real fills — and "locked decision 1" did not say what eight files say it said

**Decided by the team lead, 2026-09-10.** Written the same day, against the code
that implements it. `[V]` verified by re-running the command shown, `[S]` sourced
not re-read, `[U]` uncertain.

## What changed

`ops/ledger.py` used to fill every pending order at the next close from the cost
model. It now books the broker's own executions: **that** the fill happened,
**how many** shares, **at what price**, and the **commission**. The cost model's
price is retained beside it in a new `modelled_fill_price` column.

The trigger was a measured fault, not a preference. On **2026-09-10**
`null_trader` closed fourteen orders as `filled`. `[V]`

| | ledger delta | broker signed | executions |
|---|---:|---:|---:|
| **EMB** | +57 | 0 | **0** |
| **HYG** | +605 | 0 | **0** |
| **JAAA** | −1,503 | 0 | **0** |
| **JNK** | +420 | 0 | **0** |
| **LQD** | +861 | 0 | **0** |
| BKLN | +2,905 | +2,904 | 25 |
| IGSB | +1,135 | +1,137 | 3 |
| SHYG | +1,126 | +1,128 | 16 |
| SJNK | −1,869 | −1,874 | 176 |
| SPHY | −810 | −809 | 18 |
| SRLN | −3,920 | −3,918 | 241 |
| USHY | −3,434 | −3,438 | 33 |
| VCIT | +1,522 | +1,524 | 18 |
| VCSH | −599 | −598 | 42 |

Five had **zero** executions and nothing resting. **The other nine each
disagree with the broker too** — that is the part a phantom-only guard would
have missed, and it is why the fix is "book the real fill" and not "refuse the
fake one". That day's `nav.csv` row charged `cost_usd` **$291.68** and
`traded_usd` **$941,271.62** against the whole set. `[V]`

The invented 1,503-share JAAA short is what `ops/HALT_phase0_null.md` exists
for.

**Cause, in one line:** `IBKRBroker.place_targets` handed the shadow sub-ledger
the sleeve's `targets` and never its `fills` (`src/deploy/broker/ibkr.py`), so
`Ledger.advance` filled every pending order by construction and could not tell a
rejected order from an executed one.

## The governance claim, corrected

Eight files in this repo cite **"FORCED_FLOW_PREREG locked decision 1"** for the
rule that *the modelled cost is the sole P&L source*:

```
ops/capture_fills.py:24   src/deploy/broker/ibkr.py:107,576
ops/rebuild_ledger.py:20  ops/reset_epoch.py:11
ops/ledger.py             src/deploy/exec_ledger.py:747
ops/tests/test_capture_fills_cross_book.py:32
src/deploy/lib/portfolio_v2.py:192,220
```

**Two things are wrong with that, and both were found while implementing this
change.**

**1. The document is not in this repository and never has been.** `[V]`

```
$ git log --oneline --all --diff-filter=A -- '*FORCED_FLOW_PREREG*'
(nothing)
```

The only copy on this machine is
`~/Desktop/2027/QUANTT/QUANTT202/_cleared_2026-07-28/FORCED_FLOW_PREREG.md` — a
*cleared* directory of a different repo, dated six weeks before the CEF book went
live. A locked governance object that eight live-path files cite, which is not in
the tree, cannot be checked by anyone reading the code, which is exactly how the
next point survived.

**2. Decision 1 is scoped to BOND legs.** Quoted in full from that file: `[V]`

> 1. **Instruments:** credit ETFs + single corporate bonds on IBKR (~$1–2k
>    minimum denominations). IBKR *paper* fills **on bonds** are unrealistically
>    kind → **every bond leg** is charged the measured odd-lot cost model in the
>    ledger regardless of paper fill: **1.45% round-trip** at $25k–$100k, **8.6%
>    sub-20c**…

It says nothing about equity or ETF legs. The only other mention of ETF costs in
that document is in the **Amendment-5 deploy bar** — "net of honest costs (ETF
legs: measured spreads + the engine's impact model)" — which governs what a
*candidate must clear to be deployed*, not how the live paper ledger books a
fill price.

**No bond leg is deployed in any live book** `[V]` — `grep -c corporate_bond
ops/specs/cef_discount.frozen.json` returns 0, and no book spec carries an
`odd_lot_cost` block. The CEF book trades seventeen listed closed-end funds;
phase0 and the benchmarks trade listed ETFs.

**So this change does not override decision 1.** It contradicts a blanket
restatement of decision 1 that entered through docstrings and was never in the
decision. `src/deploy/lib/odd_lot.py` still charges the bond model unchanged, and
`Simulator.place_targets` **refuses** the real-fill path for a
`DerivativesLedger`, which is where a bond leg would live — so the part of
decision 1 that is real is now enforced by a raise rather than by convention.

## What is still true, and is an economic caveat rather than a governance one

An IBKR **paper** fill is generated against top of book with no dealer layer and
no market impact. Reported P&L from this ledger is therefore flattered by however
much the paper venue is kinder than a real one, and **the competition deliverable
is this track record.**

That objection is not answered by this change and must not be treated as
retired. What the change does is make the size of it *measurable*: it is exactly
`excess_bp` in `slippage.csv`, realised minus modelled, which is why
`modelled_fill_price` is kept beside the real price rather than discarded.

**Anyone quoting a net return from this ledger states which price it is on.**

## The thing this nearly broke, and the guard against it

`capture_fills.slippage_report` computed `modelled_bp` from
`trades.csv:fill_price`. That was safe only while the ledger always simulated.
Once `fill_price` carries the broker's price, `modelled_bp == realised_bp` by
construction, `excess_bp` is exactly `0.0` on every row, and the printed ratio is
`1.00x` forever — so **kill rule (b)** ("realised slippage > 2× modelled for 5
consecutive sessions") becomes structurally unable to trip while still printing a
number that reads like evidence it was checked.

`modelled_bp` now reads `modelled_fill_price`, and `slippage_report` **raises**
rather than falling back if the column is absent. `test_real_fill_booking.py`
pins that the two prices differ on a real row.

## What was deliberately NOT changed

- **`broker_fills.csv` still belongs to `ops/capture_fills.py`**, which still
  runs at the end of every session regardless of whether trading succeeded. The
  ledger's live `ib.fills()` query is a *read* at the point of need, not a second
  writer. Both read one source, so they cannot disagree.
- **`cost_usd` still means "slippage against the close"** on both paths, so the
  column is comparable across every row in the file.
- **`DerivativesLedger` still simulates**, and now raises if handed an execution
  record rather than ignoring it in silence.
- **The pure-simulator path is byte-identical.** `execution_record = None` is the
  default; every backtest and research script takes that branch.

## Open, and not fixed here

- The **eight docstrings** listed above still state the blanket rule. They should
  be narrowed to bond legs. Not done in this commit because it touches five live
  files for a comment change and belongs in its own diff.
- **`FORCED_FLOW_PREREG.md` should be brought into this repo** (or the citations
  repointed at `src/deploy/lib/odd_lot.py`, which does carry the decision's
  substance and is in the tree). A cited-but-absent governance object is a
  rumour with a filename.
- `ops/ledger.py`'s module docstring still says state lives under `ops/state/`,
  which does not exist. Pre-existing.

---

# Found while implementing this: kill rule (b) has been measuring itself

**Measured 2026-09-10 on `phase0_live/null_trader`, read-only, from a scratch
copy so no live ledger moved.** `[V]`

`slippage_report` compares realised (broker) against modelled (ledger). A ledger
row written by `ops/rebuild_ledger.py` carries the **real** price, so for those
rows the comparison is against itself and `excess_bp` is exactly `0.0` —
a guaranteed 1.00x that carries no information about execution at all.

Nothing recorded which rows those were, so nothing could tell them apart:

| fill_date | n | self-comparisons | usable | ratio (all) | ratio (usable) |
|---|---:|---:|---:|---:|---:|
| 2026-07-31 | 13 | **13** | 0 | 1.00x | — |
| 2026-09-10 | 9 | 0 | 9 | 2.19x | **2.19x** |
| **pooled** | 22 | 13 | 9 | **1.16x** | **2.19x** |

**The pooled 1.16x is 59% information-free.** On the only session that can
support the measurement the ratio is **2.19x — above kill rule (b)'s 2.0x trip
level.** The rule needs 2.0x on **five consecutive** sessions, so it does not
trip on one; the point is that the number the desk has been reading as "1.13x,
comfortably below" was not evidence, and the count of consecutive sessions
should start from a measurement that means something.

The 09-10 detail, which is where the execution seat should look next: `[V]`

| | side | realised bp | modelled bp | excess bp |
|---|---|---:|---:|---:|
| **SHYG** | BUY | **44.2** | 3.8 | **+40.4** |
| SPHY | SELL | −8.6 | 4.4 | −13.0 |
| BKLN | BUY | 12.2 | 4.4 | +7.7 |
| IGSB | BUY | 8.7 | 3.1 | +5.6 |
| SJNK | SELL | −0.0 | 5.7 | −5.8 |
| USHY | SELL | 5.8 | 3.2 | +2.6 |
| SRLN | SELL | 6.2 | 4.5 | +1.7 |
| VCSH | SELL | 2.6 | 1.7 | +0.9 |
| VCIT | BUY | 1.3 | 2.1 | −0.9 |

**SHYG alone is 11.6x its modelled cost and drives the whole ratio.** One name,
one session — not a finding about execution yet, and it must not be quoted as
one. It is a thing to measure again.

**Note the phase0 session log for 2026-09-10 printed `realised +15.8bp modelled
+14.0bp ... 1.13x` on 16 matched fills**, where the same function on the
completed record gives 22 matched fills. The session computes this in phase 4
while its own capture is still landing, so the logged ratio is taken on a
partial record. `[V]`

**What changed as a result:** `slippage_report` now counts the self-comparisons
and prints the ratio with them excluded, on every run. It does not silently drop
them and it does not silently keep them. Going forward `exec_ids` marks a real
fill, so a rebuilt row is identifiable; rows written before 2026-09-10 are not,
and never will be.
