# First band sessions — a running record

The band policy replaced the 2-day calendar on 2026-09-06. Everything before that
is a different policy and does not belong in this series.

**Purpose:** one short section per session, recording what was decided, what was
transmitted, and what it cost. **No analysis here.** One session is not a cost
estimate; the readout that interprets these lives in `W7`. This file exists so
that when there are enough sessions to say something, the raw record was not
reconstructed from memory.

**Provenance labels** follow `docs/REFERENCES.md`: `[V]` verified by re-reading
the artifact now, `[S]` sourced but not re-read, `[U]` uncertain.

**Authoritative sources, and which question each answers:**

| question | file |
|---|---|
| what was *transmitted* to the broker | `_ibkr_shadow/_order_map.csv` |
| what the *ledger* stepped from its own position | `_ibkr_shadow/cef_discount/orders.csv` |
| what actually *filled* | `_ibkr_shadow/cef_discount/broker_fills.csv` |

The first two are **not the same quantity and were never meant to be** — see the
docstring of `ops/reconcile_orders.py`. `orders.csv` records the ledger's step
from *its* position; the order map records what was sent, diffed against broker
truth. They diverge whenever the ledger and the account disagree, which they do.
**Only `broker_fills.csv` is evidence of a fill.**

---

## 2026-09-09 — decision session (fills pending at time of writing)

Ran from the **dev** tree (`~/Desktop/2027/QUANTT/2027`). The prod worktree did
not exist until 2026-09-10 10:31, so despite the surrounding paperwork this was
*not* a prod-tree session. [V]

**NAV wait.** Session started 17:15:05, polled every 900s, resolved at **21:45**
— yfinance 17/17 NAV and 17/17 close, cefconnect 0/17 throughout. [V]
Third data point in the series: 22:43 (09-08) [S], 21:45 (09-09) [V].

**Panel failure, non-fatal.** `scripts/cef/fetch_borrow_rates.py` died with
`HTTP Error 404` and the session continued by design (`FAILED rc=1 (session
continues)`). Borrow rates were therefore **not refreshed** for this decision. [V]
This is the same figure `W8` part A is trying to settle; note it there.

**Preflight.** All seven checks PASS, including `broker: TWS/Gateway listening on
127.0.0.1:4002`. Margin cushion 0.190, gross/NLV 2.02x. [V]

**Armed** 21:46:27. Note `[ibkr] arm: ARMED` appears **twice** in the log — worth
a look, though nothing downstream doubled (four orders sent, not eight). [V]

**Transmitted** — from `_order_map.csv`, recorded 2026-09-10T01:46:28Z
(= 21:46:28 ET), broker order IDs 22–25: [V]

| id | ticker | side | shares |
|---:|---|---|---:|
| 22 | JFR | SELL | 4,630 |
| 23 | MHD | BUY | 115 |
| 24 | MQY | BUY | 185 |
| 25 | NEA | SELL | 4,458 |

These are **the book's first real band trades**. Everything prior was either the
retired 2-day calendar or a pre-epoch order.

**Not transmitted:** `SKIP NAD +37 @ 11.15 = $413 < min_trade_usd $517`. [V]

**Ledger's own step**, for contrast (`orders.csv`, 3 rows, all `status=open`):
JFR −4,727 from −5,837; MQY +169 from −1,750; NEA −4,565 from −7,118; MHD absent. [V]

> **CORRECTED 2026-09-10 ~11:50 ET against the broker.** An earlier revision of
> this section attributed the membership and quantity gaps to "the documented
> ledger-vs-broker divergence". **That attribution is wrong.** The broker was
> read at 11:35:29 ET and the cef_discount ledger agrees with the account
> **exactly, to the share, on all 17 names** — JFR −5,837, MQY −1,750,
> NEA −7,118, MHD −8,856, difference 0 on every one. There is no position
> divergence in this book to explain anything. The real cause is a **NAV base**,
> and it is reproduced to the share below.

**Session log reports `turnover $0`** and prints no line for the four orders it
sent. Turnover is computed from *filled* trades, and MOC orders resting into the
next close have not filled — so the figure is defensible but the log is a poor
record of what was transmitted. Anyone reading only the log would conclude the
session did nothing. [V]

**Cost:** not measurable yet. `[slippage] cef_discount: no overlapping fill dates
yet`. [V]

**Status at 2026-09-10 11:25 ET: these four orders are still working, into
today's 16:00 close.** No fills exist for them. `broker_fills.csv` ends at
2026-09-08. The execution measurement for this decision belongs in the *next*
section, after tonight's capture.

---

## 2026-09-10 11:35:29 ET — broker read (read-only), settling the order dispute

Full snapshot: `results/ops/BROKER_SNAPSHOT_2026-09-10.json`.
Command recorded at the top level of that file. `ib_async`,
`IB().connect(127.0.0.1, 4002, clientId=115, readonly=True)` — clientId 115 =
cef base 45 + 70, the reconcile slot. Calls made: `reqAllOpenOrders`,
`openTrades`, `positions`, `portfolio`, `accountValues`, `reqExecutions`.
Nothing was placed, modified or cancelled.

**Resting at the broker — FOUR orders, by order id.** [V]

| id | permId | ticker | side | shares | type | tif | status | filled | remaining | clientId |
|---:|---:|---|---|---:|---|---|---|---:|---:|---:|
| 22 | 260360466 | JFR | SELL | 4,630 | MOC | DAY | PreSubmitted | 0 | 4,630 | 45 |
| 23 | 260360467 | MHD | BUY | 115 | MOC | DAY | PreSubmitted | 0 | 115 | 45 |
| 24 | 260360468 | MQY | BUY | 185 | MOC | DAY | PreSubmitted | 0 | 185 | 45 |
| 25 | 260360469 | NEA | SELL | 4,458 | MOC | DAY | PreSubmitted | 0 | 4,458 | 45 |

`whyHeld` empty on all four. These are the only open orders in the account.
Ids, sides and quantities match `_order_map.csv` exactly. **MHD 115 exists at
the broker.** The `NEXT_2026-09-11.md` table is right and `orders.csv` is the
wrong artifact for the question.

**MHD is not a desync.** A desync would be a live order the ledger has no record
of. The ledger *does* record it — in `_order_map.csv`, written by the adapter at
placement with the IBKR order id. `orders.csv` is a different register and never
claimed to hold transmissions. Both files are correct about their own subject.

### Why the two registers differ: the NAV base, reproduced to the share

The adapter sizes a weight-expressed target as
`floor(nav * |weight| / close)` and takes `nav` from `_sleeve_nav`, which
returns the shadow sub-ledger's **last** NAV row at the moment of placement.
Both live in `src/deploy/broker/ibkr.py` — `_resolve_qty` and `_sleeve_nav`,
with `_last_close` supplying the price as "latest local close on or before
asof". The table below is that expression evaluated by hand against the two
candidate NAV rows; it needs no script beyond the four artifacts named above.

Recomputed 2026-09-10 ~11:45 ET from `data/cef/cef_prices.parquet`
(panel last date **2026-09-09** [V]), the 2026-09-09 `target_weight` column of
`ops/books/cef_live/target_vs_current.csv` [V], and the two NAV rows in
`_ibkr_shadow/cef_discount/nav.csv` (2026-09-08 `500000.0` epoch;
2026-09-09 `504573.20132208994`) [V]:

| ticker | close 09-09 | weight | NAV 500,000.00 → delta | NAV 504,573.20 → delta | transmitted |
|---|---:|---:|---:|---:|---:|
| JFR | 7.67 | −0.160575 | **−4,630** | −4,726 | −4,630 |
| MHD | 11.10 | −0.194064 | **+115** | +35 | +115 |
| MQY | 10.70 | −0.033509 | **+185** | +170 | +185 |
| NAD | 11.15 | −0.145240 | **+37** | −22 | (skipped) |
| NEA | 10.96 | −0.253765 | **−4,458** | −4,564 | −4,458 |

At **NAV = $500,000.00** all four transmitted quantities reproduce **exactly,
with zero residual**, and NAD reproduces at **+37** — which is the number the
session log itself printed (`SKIP NAD +37 @ 11.15 = $413 < min_trade_usd $517`).
At NAV = $504,573.20 not one of the five reproduces. The 09-09 log line is
therefore independent confirmation of the NAV base, from an artifact written
four hours before this read.

So: **placement sized against the 2026-09-08 epoch NAV row (500,000.00)**
because the sub-ledger had not yet been advanced to the 09-09 mark when
`place_targets` ran; **`orders.csv` sized against the 09-09 mark
(504,573.20)**, which is 0.914% larger. Same positions, two NAV bases, hence
two different quantity sets and hence MHD's presence: at 500,000 its step is
+115 shares (≈$1,277, above the $517 `min_trade_usd` floor and so sent); at
504,573.20 it is +35 shares (≈$389, below the floor and so never written as an
`orders.csv` row).

**Fact, not interpretation:** the four resting orders are ~0.91% smaller than
the book's own 09-09 marked NAV would size them. Whether that ordering is a
defect is a `W5` question, not this file's.

### A competing explanation, tested and rejected

It was proposed mid-session that `sent = target − broker_current`, implying the
broker was shorter than the ledger by 97 (JFR), 107 (NEA) and 16 (MQY) shares.
Tested directly against the 11:35:29 ET read: [V]

| ticker | ledger target | implied broker | **actual broker** | verdict |
|---|---:|---:|---:|---|
| JFR | −10,564 | −5,934 | **−5,837** | fails by +97 |
| MQY | −1,581 | −1,766 | **−1,750** | fails by +16 |
| NEA | −11,683 | −7,225 | **−7,118** | fails by +107 |

Three of three testable names fail, and each fails by exactly the share count
the theory required to exist. **Those 97 / 107 / 16-share position errors do not
exist at the broker.** The theory is rejected; the NAV-base reproduction above
stands, and it also accounts for MHD and NAD, which the rejected theory could
not test at all.

### Positions — cef_discount vs the account

All **17** cef_discount names match the account to the share, difference 0:
AWF 1,926 · BIT 6,842 · DSL 3,720 · HYT 3,210 · JFR −5,837 · MHD −8,856 ·
MQY −1,750 · NAD −6,550 · NEA −7,118 · NVG −4,679 · NZF −271 · PCN 720 ·
PDI 3,746 · PDO 7,311 · PFN 1,555 · PHK 7,089 · PTY 630. [V]

Computed two independent ways, agreeing exactly: (a) by hand from the snapshot
against the last row of each sleeve's `positions.csv`; (b) by
`python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json
--books-root ops/books/cef_live --check-broker --client-id 115`, run in
`~/prod/QUANTT` at ~11:44 ET. Both report the same 15 divergent symbols
account-wide and **none of them is a cef_discount name.**

### Account values — reported in CAD, not USD

`ib.accountValues()` at 11:35:29 ET, account **DUQ199038**: [V]

| tag | value | currency |
|---|---:|---|
| NetLiquidation | 999,975.56 | **CAD** |
| ExcessLiquidity | 225,746.27 | **CAD** |
| AvailableFunds | 225,746.27 | **CAD** |
| GrossPositionValue | 1,903,746.87 | **CAD** |
| MaintMarginReq | 774,229.28 | **CAD** |
| TotalCashValue | 1,020,632.94 | **CAD** |
| Cushion | 0.225752 | (ratio) |

Recorded exactly as the broker reported them. **No conversion is applied and
none should be inferred**; the currency tag is part of the figure. This is the
whole account — three books share it — and it is not the cef_discount sleeve
NAV, which the ledger marks at $504,573.20 as of 2026-09-09. A first pass of the
snapshot script filtered these tags to `currency in ("USD","BASE","")` and
returned only `Cushion`; the filter was removed rather than the gap papered over.

### Cross-book note: five phase0 orders transmitted, never executed, booked as filled

Not a cef finding, recorded here because it sits in the same account and the
same margin pool. From `ops/books/phase0_live/_ibkr_shadow/_order_map.csv`,
14 null_trader orders were transmitted at 2026-09-10T13:43:09Z (09:43:09 ET).
The 11:35:29 ET `reqExecutions` read shows fills for **9** of them, at exactly
the transmitted quantities. The other **five have no execution and are not
resting**: [V]

| ticker | transmitted | executed | broker position | null_trader + bench ledgers claim | diff |
|---|---|---|---:|---:|---:|
| HYG | BUY 607 | none | 383 | 987 | −604 |
| JNK | BUY 421 | none | 26 | 446 | −420 |
| LQD | BUY 863 | none | −881 | −23 | −858 |
| EMB | BUY 61 | none | 550 | 608 | −58 |
| JAAA | SELL 1,502 | none | **0** | −1,503 | +1,503 |

The null_trader ledger marked all 14 `filled` with `fill_date 2026-09-10`. The
position gap equals the five unexecuted orders. Priced at each sleeve's own
recorded decision price, the 15 account-wide divergent symbols total
**≈$260,948** of position the ledgers claim and the account does not hold
(AGG, 1 share, unpriced) — of which ≈$259,161 is these five names. Cause not
determined from `ops/schedule/logs/phase0_2026-09-10.log`, which records no
rejection and reports `status=ok`; that session's `[capture]` ran at 09:43:09,
**three seconds** after transmission and before the fills that did occur had
finished arriving (last execution 09:44:59 ET). Belongs to the phase0 owner.

---

## 2026-09-10 — fills of the 09-09 decision, and tonight's decision

_Pending. Fill at 16:00 ET; capture runs in the 17:15 session._

To complete after tonight, in this order:

1. `broker_fills.csv` for `cef_discount` dated **2026-09-10** — expect four
   symbols, JFR / MHD / MQY / NEA, at the quantities above. Any difference in
   count, symbol or quantity is the finding and outranks the rest.
2. Whether the ledger booked them (`trades.csv` currently header-only;
   `orders.csv` rows should close with a `fill_date`; `positions.csv` should
   move). A fill the ledger did not record is a **desync** and outranks
   everything.
3. The `[slippage]` line — realised vs modelled bp. **First honest execution
   measurement of the band policy.** Record it; do not interpret it.
4. Whether the 17:15 session ran **from prod** (first time), resolved the NAV
   wait, and what the band decided for the next close. Fourth NAV-timing point.
