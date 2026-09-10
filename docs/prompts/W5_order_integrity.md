# W5 — Order integrity: the ledger must decide what the broker decides

**Status:** in progress — done: P0.1 dust orders (`9636502`, `results/cef/DUST_ORDERS_2026-09.md`). remains: everything else.
**Reads first:** `00_BRIEF.md` §5, §6.
**Lever:** the integrity of the record every statistic is computed from.
**Trials:** 0. **Touches the live book:** the shadow ledger and an append-only
log; no decision changes.
**Prerequisite:** W3 (the morning session and the same-pair guard).
**Supersedes:** P0.2, P3.4. **P0.1 (dust orders) is done** — landed 2026-09-08,
recorded in `results/cef/DUST_ORDERS_2026-09.md`; band HOLDs are qty-expressed
and the `min_trade_usd` key is derived and in the spec. Read that note first;
Part A depends on it.

> **⚠ One number in that note needs re-deriving, 2026-09-09.** The spec carries
> `min_trade_usd: 517`, derived as `$1 + N·hs/1e4 = N·30/1e4` with **"$1 is
> IBKR's MINIMUM COMMISSION PER ORDER"**. That is the **Fixed** plan's minimum.
> IBKR's **Tiered** plan has a **$0.35** order minimum (verified 2026-09-09:
> Tiered $0.0035/share, min $0.35; Fixed $0.005/share, min $1.00). On Tiered the
> same arithmetic gives **$181**, not $517 — so if the account is on Tiered the
> live threshold suppresses orders **2.9× larger than the economics justify**,
> a real if modest drag on transfer coefficient.
> **W2's audit establishes which plan the account is on. Re-derive
> `min_trade_usd` from that answer, show the arithmetic, and record the plan in
> the spec note so the number's provenance is explicit.**

---

## Paste from here

You are a trading engineer on the QUANTT CEF book. There are two executors: the
live one in `src/deploy/broker/ibkr.py`, which transmits orders, and the shadow
ledger in `src/deploy/exec_ledger.py`, which books modelled fills and is **the
sole P&L source** for every number on the dashboard and in every report. The
two must make the same decisions or the P&L describes a book that does not
exist. Read `docs/prompts/00_BRIEF.md`, then:

1. `results/cef/DUST_ORDERS_2026-09.md` — what landed and why.
2. `src/deploy/broker/ibkr.py` lines ~955–1000: the "Held-but-unmentioned →
   drive to flat" block and its incident history. On 2026-08-31 SPY was
   unpriceable and a 60/40 book sold all its SPY; on 2026-09-01 ANGL was
   unpriceable and an equal-weight credit book sold all its ANGL. The fix
   tracks an `unpriceable` set and excludes those names from the flatten
   sweep. *"A pricing failure is a reason to do NOTHING with a leg, never to
   flatten it."*
3. `src/deploy/exec_ledger.py::_make_orders` (~line 648). **The same bug is
   still live here.** A weight target with no close hits `continue`, never
   enters `desired`, and the loop `for inst in pos: if inst not in desired:
   desired[inst] = 0.0` then flattens it.
4. `src/deploy/broker/ibkr.py::place_targets`, `::arm`, `ops/capture_fills.py`,
   and the CEF shadow ledger's `orders.csv`, `trades.csv`,
   `broker_fills.csv`, `slippage.csv`.

---

## Part A — Port the unpriceable-name fix into the shadow ledger

### What happens on a lag day

The sleeve wants HYT at +0.0761 (a band HOLD). The shadow ledger cannot price
HYT on the sizing date, drops it from `desired`, then sweeps it to zero: a
modelled SELL of 4,598 shares, about $38k, charged the modelled half-spread.
The live broker, correctly, sends nothing. Next day HYT's close arrives, the
sleeve still wants +0.0761, and the ledger books a BUY of ~4,598 shares. Net
effect in the P&L source: a phantom round trip of ~$76k, 15% of NAV, with
modelled costs, on a day the strategy did nothing — and the ledger and broker
disagree by 4,598 shares until the next `arm()` reseeds. This corrupts exactly
the two numbers the band's pre-registration says we judge it on: realised
turnover and cost.

1. **Port the fix.** In `_make_orders`, collect `unpriceable` exactly as
   `ibkr.py` does (a weight target whose close is missing or non-positive),
   print the same warning, skip those names in the flatten sweep. Copy the
   incident comment verbatim and add "ported to the shadow ledger <date>" so
   the two implementations carry the same history and cannot drift again
   without someone noticing.
2. **The residual case.** Since P0.1, band-HOLD targets are qty-expressed and
   need no price, so an unpriced HOLD is safe. The `unpriceable` path now only
   matters for a band-**TRADE** target on a lagging name: warn, skip, leave the
   position alone. Do not let it fall through to the sweep.
3. **Keep the sweep.** A name the sleeve genuinely did not ask for must still
   go flat; that is how exits work. Only unpriceable names are exempt.
4. **Test.** In `src/deploy/tests/`: construct a `DerivativesLedger` with one
   held position, hand it a weight target for that name and a close dict
   without the name, `advance()` one day, assert (a) no order row, (b) the
   position unchanged, (c) a warning printed naming the ticker. Mirror it for
   `ibkr.py::place_targets` against `src/deploy/broker/simulator.py`.
5. **Fix the dashboard's description.** `api_trades` labels the row
   `forced-exit` and the banner says the executor "cannot size an unpriced leg
   and the held-but-unmentioned rule flattens it". After the port that is false
   on both paths. Rename the kind to `unpriced-hold`, keep it flagged (the name
   is stale and the trader should know), and rewrite the banner: "No close for
   HYT on <date>. The position is held unchanged; the sleeve's target for it
   will be applied when a price exists."
6. **Audit the history.** The ledger was re-seeded from broker positions on
   2026-09-08 so `trades.csv` is short, but `ops/books/_recovered_dryruns/` and
   the pre-epoch ledger in git history exist. Find every same-name
   SELL-to-flat followed by a BUY within three sessions where the SELL date has
   no close for that name in the panel. Report the count, the notional, the
   modelled cost charged, and which sessions' turnover statistics they
   inflated. Those sessions are excluded from W7's band readout by name.

W3 Part B removes the cause on the price side (IBKR bars primary, no
yfinance "possibly delisted"), but the ledger must never book a fill the
broker skipped, whatever the source. Both changes are required.

---

## Part B — Order lifecycle, end to end

At 08:31 ET a trader should be able to see: "Thirteen orders were decided at
08:30 on yesterday's pair. Twelve transmitted; one was skipped because it was
unpriced. They rest as MOC until today's close. At 16:00 they fill; by 16:05 I
see each fill against the decision close; by 17:30 the journal says what the
session did." Today none of that is visible: orders live in `orders.csv` with a
status column, fills arrive in `broker_fills.csv` after capture, and nothing
ties an order to its fill or shows the resting state.

**Remember the auction's own clock.** NYSE MOC and LOC orders may be entered,
modified or cancelled only until **15:50 ET**; after that they cannot be
modified or cancelled, and new closing-only interest may be entered only on the
side that offsets a published imbalance. The lifecycle view must therefore mark
15:50 as the point of no return — after it, "resting" means committed.

**1. Order events, append-only.** After each `placeOrder`, and in an
`orderStatusEvent` handler while the session is connected, append to
`ops/books/cef_live/_ibkr_shadow/cef_discount/order_events.csv`:

`ts_utc, decision_date, pair_date, fill_date, ticker, side, qty, order_type,
limit_price, ib_order_id, perm_id, status, filled_qty, avg_fill_price,
decision_close, reason`

with `status` in `decided | transmitted | skipped_unpriced | rejected | resting
| committed_1550 | partially_filled | filled | cancelled`. The live path writes
`decided`, `transmitted`, `skipped_*`, `rejected`; `capture_fills.py` writes
`filled` / `partially_filled` with the VWAP, linked by `perm_id`. Idempotent on
re-run: dedupe on `(perm_id, status)`. Never rewrite a row.

**2. `/api/orders`.** Today's lifecycle: merge `order_events.csv` for the
current decision date with the broker snapshot's `openOrders` (resting state,
live) and `fills` as they arrive. Per order: the state chain with timestamps
and, once filled, `exec_bp` against the official close (W7's definition).
Past sessions come from the file only.

**3. The screen** (W9 builds it; define the payload here). Before 16:00: each
order with its state and a resting indicator, and a 15:50 marker. After the
close: fills as they arrive, each with `exec_bp` coloured by sign, a session
total, and the count still unfilled. **An unfilled MOC after the close is a red
row** — the auction did not fill it, which for a MOC is a broker-side event
worth a human.

**4. The journal.** At the end of every session (phase 4, after capture),
`ops/journal.py` writes `ops/books/cef_live/journal/YYYY-MM-DD.md`:

```
# Session 2026-09-10 — cef_discount
armed: yes | no (blockers: ...)
pair: 2026-09-09 (complete: prices IBKR 17/17, NAV 3-channel 17/17)
phases: REFRESH ok 08:30 · PANELS ok 08:31 · WAIT skipped · PREFLIGHT ok 08:33 · TRADE ok 08:35 · CAPTURE ok 17:31
decision: band 4.8%, volscal 1.51, 17 eligible
orders: n, gross $, by kind
fills: n, gross $, exec bp mean ± sd, delay bp (already in the backtest)
provenance: broker_confirmed | modelled_only | no_trades
risk: gross, net, BR_eff, PC2 share, net muni weight
carry: weighted borrow fee, borrow $/yr, net yield carry, ex-dates today, recall watch
alerts: none | ...
notes: <anything the job printed at WARNING or above>
```

Written from files only; a section whose source is missing says so. The
dashboard shows the last five in a drawer and deep-links `#journal/<date>`.

## Acceptance

- After the next armed session, `order_events.csv` has a `decided` and a
  `transmitted` row per order, then `filled` rows after capture, each linked by
  `perm_id`; `/api/orders` shows every chain and its `exec_bp` matches
  `shortfall_log.csv` (W7) to 0.1bp.
- The unpriced-name test passes on both executors.
- The journal exists for every session since the change, including non-armed
  ones, which say why.

## Do not

- Do not remove the flatten sweep.
- Do not touch `arm()`'s broker-truth adoption or the same-pair guard.
- Do not ffill, interpolate or substitute a price anywhere on the order path.
- Do not add any order-placing or cancelling code path to the dashboard.
- Do not let a failure in event logging raise into `place_targets`; logging is
  wrapped, the order path is not.
