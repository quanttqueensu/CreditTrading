# Ledger divergence — measured 2026-09-10

**Scope.** Internal consistency of the seven live shadow sub-ledgers under
`ops/books/{cef_live,benchmarks_live,phase0_live}/_ibkr_shadow/`, their
`_attribution.json` files, and what each reports as NAV. Reconciled against
`results/ops/BROKER_SNAPSHOT_2026-09-10.json`, a read-only `ib.positions()` /
`reqAllOpenOrders` capture taken by a sibling agent at
**2026-09-10T11:35:29.772714−04:00** (port 4002, clientId 115, `readonly=True`).
Nothing here was fixed, edited or re-run against live state. No broker connection
was opened by this work.

Provenance labels: `[V]` re-derived here from the named file by the named command,
`[S]` read from a file but not independently re-derived, `[U]` uncertain.

---

## Headline

1. **The CEF book — the deliverable — is clean on positions.** All 17 names in
   `cef_discount/positions.csv` at 2026-09-09 equal the broker's account net at
   2026-09-10 11:35 ET, exactly, to the share. `[V]` The dollar error in the CEF
   book's reported NAV *attributable to position divergence* is **$0.00**.
   **CLAUDE.md landmine #3 ("disagrees with the broker on all 17 positions,
   ~$223k account-wide") is out of date and should be rewritten.** It described
   the state before the 2026-09-08 epoch reseed.
2. **The account-wide divergence is real but it is the null trader's, and 99.3%
   of it was created today.** Gross **$260,515.10**, net **+$106,427.64**, across
   **15 of 35** symbols `[V]`. Five orders the null trader transmitted this
   morning never filled at the broker, and the shadow ledger booked all five as
   filled anyway. Those five symbols alone are **$258,631.78** of the
   **$260,418.10** measured on the null-trader/benchmark symbol set `[V]`.
3. **The CEF book has two NAV observations, not a track record.** `nav.csv` holds
   exactly two rows: a declared epoch of $500,000.00 at 2026-09-08 and one
   mark-to-market at 2026-09-09. `trades.csv` is **empty**. The reported
   +$4,573.20 is a two-session mark on a base that was asserted, not measured.
4. **The order record disagrees with itself and with the broker**, and the reason
   is not a lost row — it is **two sizing paths using two different NAVs**. Both
   paths agree about current shares. See §1.

---

## §1 The order record: `orders.csv` vs `_order_map.csv` vs the broker

### 1.1 What the three artefacts say about the same four orders

`_order_map.csv`, written by the adapter at placement, recorded 2026-09-10T01:46:28Z
(= 2026-09-09 21:46 ET) `[S]`; broker open orders from the snapshot `[S]`;
`orders.csv` from the shadow sub-ledger `[S]`:

| ticker | `_order_map` | broker resting (MOC, PreSubmitted) | `orders.csv` delta | `orders.csv` target |
|---|---:|---:|---:|---:|
| JFR | SELL 4,630 (id 22) | SELL 4,630, permId 260360466 | −4,727 | −10,564 |
| MHD | BUY 115 (id 23) | BUY 115, permId 260360467 | **no row** | — |
| MQY | BUY 185 (id 24) | BUY 185, permId 260360468 | +169 | −1,581 |
| NEA | SELL 4,458 (id 25) | SELL 4,458, permId 260360469 | −4,565 | −11,683 |

`_order_map.csv` and the broker agree **exactly** on all four (ids, sides,
quantities) `[V]`. `orders.csv` has three rows, omits MHD, and states three
quantities that were never transmitted. Both faults named by the coordinator are
confirmed: **wrong count, and wrong quantities.**

    awk -F, 'NR==1 || $1 ~ /2026-09-09/' ops/books/cef_live/_ibkr_shadow/_order_map.csv
    cat ops/books/cef_live/_ibkr_shadow/cef_discount/orders.csv
    python3 -c "import json;d=json.load(open('results/ops/BROKER_SNAPSHOT_2026-09-10.json'));[print(o['symbol'],o['action'],o['totalQuantity'],o['orderId'],o['permId']) for o in d['open_orders']]"

### 1.2 The cause — and a correction to the working hypothesis

A decode was circulated that reads the gap as a **position** error: that the
broker holds more short than the ledger believes (JFR by 97, NEA by 107, MQY by
16, MHD agreeing). That decode assumes both paths used the *same target* and
differed on *current shares*.

**That is not what happened, and the broker snapshot settles it.** Two
independent lines of evidence:

**(a) The broker's actual positions.** JFR −5,837, MHD −8,856, MQY −1,750,
NEA −7,118 — identical to the ledger, not 97/107/16 shares more short `[V]`.

**(b) The transmitted quantities reproduce exactly from the ledger's own current
shares at a NAV of $500,000.** Using `target_weight` from
`ops/books/cef_live/target_vs_current.csv` (written 2026-09-09 21:46) and the
2026-09-09 closes from `positions.csv`, `floor(500000 × |w| / px)` gives:

| ticker | `target_weight` | close | `floor(500000·w/px)` | broker target = current + delta | match |
|---|---:|---:|---:|---:|:--:|
| JFR | 0.160575 | 7.670000 | 10,467 | −5,837 − 4,630 = **−10,467** | ✓ |
| MHD | 0.194064 | 11.100000 | 8,741 | −8,856 + 115 = **−8,741** | ✓ |
| MQY | 0.033509 | 10.699999 | 1,565 | −1,750 + 185 = **−1,565** | ✓ |
| NEA | 0.253765 | 10.960000 | 11,576 | −7,118 − 4,458 = **−11,576** | ✓ |
| NAD | 0.145240 | 11.149999 | 6,513 | delta +37 = $412.55 < `min_trade_usd` $517 → not sent | ✓ |

Four exact hits out of four, plus NAD's non-transmission explained to the cent.
At NAV $504,573.20 not one of them reproduces `[V]`.

    python3 - <<'EOF'
    import math
    W={"JFR":0.160575,"MHD":0.194064,"MQY":0.033509,"NAD":0.14524,"NEA":0.253765}
    PX={"JFR":7.670000076293945,"MHD":11.100000381469727,"MQY":10.699999809265137,
        "NAD":11.149999618530273,"NEA":10.960000038146973}
    for nav in (500000.0, 504573.20132208994):
        print(nav, {t: math.floor(nav*W[t]/PX[t]) for t in W})
    EOF

**So the mechanism is:** the adapter's `_resolve_qty` sizes off
`IBKRBroker._sleeve_nav` (`src/deploy/broker/ibkr.py:610`), which reads the last
row of `nav.csv` — at order time that was still the **2026-09-08 epoch row,
$500,000**. The shadow sub-ledger then advanced and sized its own book against
the **2026-09-09 row, $504,573.20**, which it wrote in the same run. The NAV gap
is 0.907%, so every target differs by ~0.9%.

**And that is why MHD has no `orders.csv` row.** `min_trade_usd = 517.0`
(`ops/specs/cef_discount.frozen.json`, `rebalance.min_trade_usd`) `[V]`. The two
paths land on opposite sides of that gate:

| ticker | sim delta @ $504,573.20 | sim notional | adapter delta @ $500,000 | adapter notional | outcome |
|---|---:|---:|---:|---:|---|
| MHD | +35 sh | **$388.50** < $517 | +115 sh | **$1,276.50** > $517 | ledger skips, broker trades |
| NAD | +22 sh | $245.30 < $517 | +37 sh | $412.55 < $517 | both skip |

MHD is not a dropped row in the recording path. It is a real order that the
ledger's own sizing never wanted, because the ledger was pricing itself 0.907%
richer than the adapter was. Nothing needs fixing in `orders.csv`'s *writer*; the
fix is that both paths must size off one NAV.

`[U]` — the ordering claim (adapter reads `nav.csv` before the sub-ledger appends
the session row) is inferred from the arithmetic above, not read from the session
entry point: `src/deploy/run_book.py` could not be opened, see §9.

### 1.3 What this will cost tonight

The four MOC orders were still `PreSubmitted` at 11:35 ET. If all four fill in
full at today's close, the ledger will book its own `orders.csv` targets and the
broker will hold the transmitted ones, opening a fresh four-name divergence:

| ticker | ledger after | broker after | ledger − broker | × close | $ |
|---|---:|---:|---:|---:|---:|
| JFR | −10,564 | −10,467 | −97 | 7.67 | −744.00 |
| MHD | −8,856 | −8,741 | −115 | 11.10 | −1,276.50 |
| MQY | −1,581 | −1,565 | −16 | 10.70 | −171.20 |
| NEA | −11,683 | −11,576 | −107 | 10.96 | −1,172.72 |
| | | | | **gross** | **$3,364.42** |

Direction: in all four the **ledger will be more short than the broker**. Note
that this is the opposite framing to the circulated decode — the bias is not
"the broker holds more short than the ledger believes" (which is false today);
it is that the ledger *will come to* believe it holds more short than it does,
because it books a bigger trade than it sent. The sign is consistent because the
ledger sizes off the larger NAV in a book whose gross is dominated by shorts.

**Directional-bias question, answered:** across all 17 CEF names the divergence
today is exactly zero, so there is no bias to characterise. The mechanism is
therefore *not* unrecorded partial fills or dropped odd lots — it is deterministic
double-sizing, which is good news: it is repairable prospectively and, because
`arm()` re-seeds share counts from the broker, it never compounds into a wrong
order. It compounds into a wrong *book*.

---

## §2 Positions: ledger vs broker

Every sleeve's `positions.csv` at its own last date, summed per symbol, against
the account net at 2026-09-10 11:35 ET. Marks are each symbol's most recent close
from whichever sub-ledger carries it; the mark date is stated. `[V]`

| symbol | ledgers sum | broker net | diff | mark | mark date | $ |
|---|---:|---:|---:|---:|---|---:|
| AGG | 206 | 205 | +1 | 97.00 | 2026-09-08 | +97.00 |
| BKLN | −1,213 | −1,201 | −12 | 20.58 | 2026-09-10 | −246.90 |
| EMB | 608 | 550 | +58 | 93.57 | 2026-09-10 | +5,427.35 |
| HYG | 987 | 383 | +604 | 78.74 | 2026-09-10 | +47,558.96 |
| IGSB | 1,205 | 1,207 | −2 | 51.67 | 2026-09-10 | −103.33 |
| **JAAA** | **−1,503** | **0** | **−1,503** | 50.58 | 2026-09-10 | **−76,021.89** |
| JNK | 446 | 26 | +420 | 94.72 | 2026-09-10 | +39,782.40 |
| LQD | −23 | −881 | +858 | 104.71 | 2026-09-10 | +89,841.18 |
| SHYG | 1,005 | 1,009 | −4 | 41.83 | 2026-09-10 | −167.34 |
| SJNK | −3,531 | −3,530 | −1 | 24.62 | 2026-09-10 | −24.62 |
| SPHY | 198 | 196 | +2 | 23.03 | 2026-09-10 | +46.06 |
| SRLN | −1,954 | −1,958 | +4 | 40.51 | 2026-09-10 | +162.06 |
| USHY | −1,262 | −1,273 | +11 | 36.41 | 2026-09-10 | +400.52 |
| VCIT | 417 | 423 | −6 | 79.94 | 2026-09-10 | −479.64 |
| VCSH | 414 | 412 | +2 | 77.92 | 2026-09-10 | +155.84 |

**35 symbols reconciled, 15 diverge. Gross |$| = 260,515.10. Net = +106,427.64.**
**The 17 CEF names contribute 0 of the 15 and $0.00 of the gross.**

The prior [U] measurement of "~15 symbols, worst case JAAA at ledger −1,503 vs
broker 0" is **confirmed**, independently re-derived `[V]`.

Reproduce (script written to the session scratchpad, reproduced verbatim in §10):

    python3 <scratchpad>/recon.py

### 2.1 Where today's divergence came from

Cross-referencing `_order_map.csv` (transmitted), the snapshot's
`executions_this_tws_session` (572 executions, all dated 2026-09-10), and
`null_trader/trades.csv` (what the ledger booked) `[V]`:

| symbol | ledger booked | transmitted | real fill | outcome |
|---|---:|---:|---:|---|
| BKLN | +2,905 | +2,904 | +2,904 | filled |
| IGSB | +1,135 | +1,137 | +1,137 | filled |
| SHYG | +1,126 | +1,128 | +1,128 | filled |
| SJNK | −1,869 | −1,874 | −1,874 | filled |
| SPHY | −810 | −809 | −809 | filled |
| SRLN | −3,920 | −3,918 | −3,918 | filled |
| USHY | −3,434 | −3,438 | −3,438 | filled |
| VCIT | +1,522 | +1,524 | +1,524 | filled |
| VCSH | −599 | −598 | −598 | filled |
| **EMB** | **+57** | +61 | **0** | **NOT FILLED — ledger booked it** |
| **HYG** | **+605** | +607 | **0** | **NOT FILLED — ledger booked it** |
| **JAAA** | **−1,503** | −1,502 | **0** | **NOT FILLED — ledger booked it** |
| **JNK** | **+420** | +421 | **0** | **NOT FILLED — ledger booked it** |
| **LQD** | **+861** | +863 | **0** | **NOT FILLED — ledger booked it** |

Those five are not resting either — the snapshot's `open_orders` contains only
the four CEF MOC orders `[V]`. So they were rejected or cancelled between
09:43 ET and 11:35 ET. **Which of the two, and why, cannot be determined from
artefacts on disk** — `_order_map.csv` records placement only, never status, and
`orders.csv` marks all eleven of today's null-trader rows `open` with no
`fill_date` `[V]`. JAAA is a short and the plausible explanation is no borrow
availability; the four buys are not explained by that and I will not guess.

Those five symbols account for **$258,631.78** of the **$260,418.10** measured on
this symbol set — **99.3%**. Stripping today out, the residual pre-existing
divergence across the same 14 symbols is **49 shares, $2,105.92 gross** `[V]` —
the accumulated drift from the same modelled-vs-transmitted quantity gap seen in
the first nine rows (1–5 shares per name per session).

---

## §3 Internal consistency, per artefact

### 3.1 Does `positions.csv` equal the cumulative sum of `trades.csv`?

| sleeve | positions legs | trades rows | cumsum(trades) == positions? |
|---|---:|---:|---|
| cef_discount | 17 | **0** | **No — structurally impossible.** 17 positions, zero trades. |
| null_trader | 14 | 238 | **Yes, exactly, all 14 symbols.** `[V]` |
| bench_b1_hyg | 1 | 0 | No — 1 position, zero trades |
| bench_b3_agg | 1 | 0 | No |
| bench_b4_60_40 | 1 | 0 | No |
| bench_b5_shy | 1 | 0 | No |
| bench_b6_ew_credit | 8 | 0 | No |

Six of seven sleeves hold positions that no trade in their own ledger created.
This is **by construction, not corruption**: `ops/reset_epoch.py` seeds positions
directly and starts `trades.csv` empty. It nonetheless means that for six of seven
sleeves, `trades.csv` cannot be used to audit `positions.csv` at all. The null
trader is the only sleeve where the two agree, and it is the only sleeve whose
positions were *not* re-seeded after 2026-07-31.

### 3.2 Does `_attribution.json` match `positions.csv`?

| sleeve | symbol | `positions.csv` | `_attribution.json` | broker | which is right |
|---|---|---:|---:|---:|---|
| bench_b6 | **ANGL** | **87** | **86** | **87** | positions.csv `[V]` |
| bench_b6 | **USHY** | **68** | **67** | shared | unresolvable |
| bench_b6 | **VCIT** | **31** | **30** | shared | unresolvable |
| bench_b3 | AGG | 206 | 204 | **205** | **neither** `[V]` |
| bench_b5 | SHY | 244 | 243 | 244 | positions.csv `[V]` |
| bench_b4 | IEF | 86 | 85 | 86 | positions.csv `[V]` |
| bench_b4 | **SPY** | **absent** | **16** | **absent** | attribution is wrong by 16 `[V]` |
| bench_b1 | HYG | 252 | 251 | shared | unresolvable |
| cef_discount | all 17 | see §2 | all 17 differ | matches positions.csv | positions.csv `[V]` |

The coordinator's example is **verified**: `bench_b6_ew_credit` shows ANGL 87 in
`positions.csv` and 86 in `_attribution.json`. ANGL is traded by no other book in
the account, the broker holds 87, so `positions.csv` is right. `USHY` and `VCIT`
in the same sleeve show the same +1 signature; both are shared with the null
trader so the broker net cannot arbitrate them.

**`AGG` is the worst row here**: only `bench_b3_agg` trades it, and all three
artefacts give a different number — ledger 206, attribution 204, broker 205.

**The CEF `_attribution.json` is not wrong, it is frozen.** Its 17 values equal
the cumulative net of `cef_discount/broker_fills.csv` up to and including
2026-07-31 **exactly, to the share, on all 17 names** `[V]`; it has not moved
since (file mtime 2026-07-31 17:26:39). It therefore misses the 19 fills of
2026-09-01 and the 18 of 2026-09-08.

    python3 - <<'EOF'
    import json, pandas as pd
    bf=pd.read_csv("ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv")
    bf["fill_date"]=pd.to_datetime(bf["fill_date"])
    att=json.load(open("ops/books/cef_live/_attribution.json"))["cef_discount"]
    for cut in ("2026-07-31","2026-09-08"):
        s=bf[bf.fill_date<=cut]; cum={}
        for r in s.itertuples():
            cum[r.instrument]=cum.get(r.instrument,0.)+(1 if r.side=="BUY" else -1)*float(r.qty)
        print(cut, {k:round(cum.get(k,0.)-att.get(k,0.),4) for k in att if abs(cum.get(k,0.)-att.get(k,0.))>1e-9} or "EXACT MATCH")
    EOF

This matters because `_attribution_seed` (`src/deploy/broker/ibkr.py:719`) reads
this file, and `ops/preflight.py:337` globs it. It is consulted only when the
shadow ledger has nothing to say, and only ever to answer *which sleeve owns a
contested symbol* — never a quantity that reaches an order. The exposure is
therefore an `arm()` refusal or a wrong ownership claim on a shared symbol, not a
wrong trade. `SPY: 16` is the live instance: `bench_b4_60_40` claims 16 SPY that
the account does not hold.

### 3.3 `broker_fills.csv` is cross-contaminated between books

`bench_b1_hyg/broker_fills.csv` contains ten HYG SELL executions timestamped
`2026-09-08 13:35:18+00:00` `[V]`. `phase0_live/_ibkr_shadow/_order_map.csv`
records `null_trader` placing HYG SELL 442 at exactly `2026-09-08T13:35:18Z`
`[V]`. `bench_b1_hyg` is a long-only $20,000 single-name benchmark whose entire
book is 252 HYG; its `broker_fills.csv` cumulates to **−440** `[V]`. Those fills
are the null trader's.

The same signature appears in `bench_b6_ew_credit/broker_fills.csv`: cumulative
JNK −961 against a ledger position of +26, and the null trader's `_order_map`
shows JNK SELL 961 on 2026-09-08 `[V]`.

**Cause.** `ops/capture_fills.py` resolves shared tickers *within one book*
(`sleeve_universes(book_path)`), then falls back to that book's own
`_order_map.csv`. Three books share this account with overlapping ETF universes,
so a symbol contested *across books* looks solely-owned *within* a book and the
whole account's fills for it are swept into that book's sleeve. The docstring's
own premise — "no two deployed sleeves share a ticker" — is true per book and
false per account.

**Blast radius.** `broker_fills.csv` feeds no P&L path (stated at
`ops/capture_fills.py` docstring, and `FORCED_FLOW_PREREG` decision 1). It feeds
the realised-slippage statistic that **kill rule (b)** is evaluated against, and
the dashboard's execution-provenance panel (`dashboard/server.py:861`). So the
consequence is a corrupted kill-rule input and a misleading provenance display,
not a wrong NAV. The CEF sleeve is unaffected: no other book trades a CEF ticker,
and its 294 fills cumulate to its positions exactly (§3.4).

### 3.4 `broker_fills.csv` vs `positions.csv`, CEF

Cumulative net of all 294 rows in `cef_discount/broker_fills.csv` equals
`positions.csv` at 2026-09-09 **exactly on all 17 names** `[V]`. Two independent
records of the CEF book agree with each other and with the broker. This is the
strongest single piece of evidence that the CEF sleeve's share counts are sound.

(`294` also confirms the CLAUDE.md figure "there are 294 [live fills]" `[V]`.)

### 3.5 `orders.csv` rows marked `open` with no `fill_date`

| sleeve | orders rows | `open` | `open` with no `fill_date` | correspond to anything in `broker_fills.csv`? |
|---|---:|---:|---:|---|
| cef_discount | 3 | 3 | 3 | No — and correctly so; the four MOC orders are still resting `[V]` |
| null_trader | 403 | 11 | 11 | **9 of 11 filled today and are in `broker_fills.csv`; the row still says `open`** `[V]` |
| all bench | 0 | 0 | 0 | n/a |

`orders.csv` status is never reconciled back from fills. Nine null-trader orders
filled at 13:43 UTC, were captured into `broker_fills.csv` at 13:43:10 UTC, and
their `orders.csv` rows still read `open` with an empty `fill_date`. Anything
reading `orders.csv` to answer "what is resting at the broker right now" gets
eleven when the answer is zero.

### 3.6 Manifest integrity

`_pre_epoch_cef_discount_20260908_170128/manifest.json` claims
`positions.csv` 431 rows / `trades.csv` 397 / `orders.csv` 425 / `nav.csv` 25,
written 2026-09-04T21:58:29Z. The directory actually contains 17 / 0 / 0 / 1 rows
`[V]`. The manifest was copied from the *previous* archive rather than rewritten,
so the second CEF epoch archive misdescribes its own contents by an order of
magnitude. Nothing reads it (§7), so this is a forensic hazard rather than a live
one — but it is the archive a future auditor would open first.

---

## §4 Staleness

Trading days established with the repo's own calendar
(`python3 -c "import sys;sys.path.insert(0,'ops/schedule');import nyse_calendar..."`);
2026-09-07 is a holiday, so the sessions since 2026-09-04 are 09-08, 09-09, 09-10 `[V]`.

| artefact | last date / mtime | sessions stale as at 2026-09-10 |
|---|---|---:|
| `cef_live/.../cef_discount/positions.csv`, `nav.csv` | 2026-09-09 | 1 (today, unclosed) |
| `cef_live/.../cef_discount/broker_fills.csv` | 2026-09-08 | 2 |
| `cef_live/.../cef_discount/trades.csv` | **empty** | n/a |
| `cef_live/book_status.json` | 2026-09-09 | 1 |
| **`cef_live/_attribution.json`** | content = 2026-07-31; mtime 2026-07-31 17:26 | **28** |
| `phase0_live/.../null_trader/*` | 2026-09-10 | 0 |
| `phase0_live/_attribution.json` | mtime 2026-09-09 17:27 | 1 |
| `benchmarks_live/.../bench_b*/positions.csv`, `nav.csv` | 2026-09-08 | 2 |
| `benchmarks_live/.../bench_b4_60_40/broker_fills.csv` | 2026-08-31 | 7 |
| **`benchmarks_live/book_status.json`** | 2026-09-04 | **3** |
| **`benchmarks_live/_attribution.json`** | mtime 2026-08-31 14:40 | **7** |
| `ops/heartbeat.json` `benchmarks` | 2026-09-09, `status: failed`, rc 3 | 1 |
| `ops/heartbeat.json` `weekly` | 2026-08-29 | — (weekly job, 2 weeks) |
| `ops/heartbeat.json` `watchdog` | 2026-09-09, `status: stale` | 1 |

The benchmark book has not advanced its ledgers for two sessions and its rollup
for three, and its heartbeat records `rc 3` on 2026-09-09. No `ops/HALT*.md` file
exists `[V]` — so nothing is currently gating on this.

---

## §5 Which NAV is reported where

Traced for the CEF book at 2026-09-09.

| consumer | code path | value | source |
|---|---|---:|---|
| shadow ledger | `cef_discount/nav.csv` last row | **504,573.20132208994** | file `[S]` |
| book rollup | `cef_live/book_status.json` `book_nav` | **504,573.20132208994** | file `[S]` |
| dashboard `/api/pnl`, `/api/book` | `dashboard/server.py:721` `_nav_df` → `_nav_last` reads the same `nav.csv` | **504,573.20** | code read `[V]` |
| weekly report | `ops/schedule/weekly_book_report.py:43` `_sleeve_nav` reads the same `nav.csv` | **504,573.20** | code read `[V]` |
| **order sizing** | `src/deploy/broker/ibkr.py:610` `IBKRBroker._sleeve_nav` → `ledger(...).nav_series().iloc[-1]` | **500,000.00** at order time | inferred `[V]` from §1.2 |
| `ops/heartbeat.json` | records no NAV at all | — | file `[S]` |

**They reconcile trivially — all four reporting consumers read the same two-row
file.** There is no second opinion anywhere in the system. That is the finding:
`nav.csv` is not corroborated by anything, and the one place a *different* NAV is
used is the one place it moves money.

Decomposition of the reported figure `[V]`:

    nav = cash + invested
    2026-09-08 (epoch):  500,000.00 = 500,700.55 + (−700.55)
    2026-09-09 (mark) :  504,573.20 = 500,700.55 +  3,872.65    daily_return 0.9146%

Both rows satisfy the identity to floating-point exactly, for every sleeve `[V]`.
But **`cash` is a plug, not an observation**: `ops/reset_epoch.py` writes a
declared NAV and back-solves `cash = declared_nav − marked_invested`. The
$500,700.55 was never read from the broker. `invested` = the sum of the 17
`market_value` cells, verified `[V]`; gross exposure $745,271.73 on net $3,872.65,
i.e. a near-market-neutral book, which is why the net is so small.

**Two further NAV faults found while tracing:**

- `IBKRBroker._sleeve_nav` (`ibkr.py:610`) wraps its ledger read in
  `except Exception: pass` and falls back to the registered `capital_usd`. That
  is a silent fallback on the sizing path — if `nav.csv` ever fails to parse,
  every order in the session is sized off $500,000 with no message. It is
  currently returning the right kind of number for the wrong reason (§1.2), which
  is exactly the dormancy pattern CLAUDE.md warns about.
- `benchmarks_live/book_status.json` records `"nav": NaN` for `bench_b4_60_40`
  and a `book_nav` of 80,088.91 that is the sum of the *other four* sleeves
  (20,013.13 + 19,990.08 + 19,983.33 + 20,102.37 = 80,088.91, `[V]`). A sleeve
  whose NAV is NaN was silently dropped from the book total.
- The account's `NetLiquidation` is reported by IBKR as **999,975.56 CAD** and
  `TotalCashValue` as **1,020,632.94 CAD** `[S]`; the snapshot carries no USD or
  BASE row. The three books together claim 504,573.20 + 641,105.36 + 80,088.91 =
  **1,225,767.47 USD**. These are not comparable without an FX rate the snapshot
  does not contain, and I did not fetch one. **Flagged, not reconciled.**

---

## §6 The dollar error in reported NAV

### 6.1 CEF book — the deliverable

| component | error | confidence |
|---|---:|---|
| position divergence vs broker at 2026-09-09 | **$0.00** | high — 17/17 exact against the broker snapshot and against 294 cumulative broker fills, two independent records `[V]` |
| cash | **unbounded, unverifiable** | the $500,700.55 is a plug from the epoch declaration; the account is shared, so no per-book cash exists at the broker to check it against |
| the $500,000 base itself | **declared, not measured** | `ops/reset_epoch.py` asserted it on 2026-09-08 |
| expected error from tonight's fills | **$3,364.42 of mismatched exposure**, ledger more short (§1.3) | high, conditional on all four MOC orders filling in full |

**So: the reported CEF NAV of $504,573.20 as at 2026-09-09 carries no measurable
position error today. Its base is an assertion. It will begin accruing error at
roughly $3.4k of mismatched gross exposure per armed session unless §1.2 is
fixed.**

Note what a share-count divergence does and does not do to NAV. When the ledger
books a trade the broker did not make, cash moves the other way by the same
notional, so **NAV is unchanged at the moment of booking** — the error is the
modelled cost charged on a trade that never happened, plus, thereafter, the
mark-to-market of the phantom exposure. The error therefore grows as

    NAV_error(t) = Σ_symbols (ledger_shares − broker_shares) × (price_t − price_at_divergence)

which is zero on day one and unbounded afterwards. **This is why an unreconciled
ledger is a slow leak rather than a visible break, and why nobody has noticed.**

### 6.2 Null trader — where the money actually is

Today's five phantom fills, from `null_trader/trades.csv` at 2026-09-10 `[V]`:

| symbol | booked | fill price | notional booked | modelled cost |
|---|---:|---:|---:|---:|
| EMB | BUY 57 | 93.58341706 | +5,334.25 | 0.48 |
| JNK | BUY 420 | 94.73687472 | +39,789.49 | 7.09 |
| HYG | BUY 605 | 78.75171879 | +47,644.79 | 7.09 |
| LQD | BUY 861 | 104.72896253 | +90,171.64 | 16.33 |
| JAAA | SELL 1,503 | 50.56819648 | −76,004.00 | 17.89 |
| | | **net cash booked** | **−106,936.17** | **48.88** |

- **Immediate NAV error: −$48.88** (understated), being modelled costs charged on
  trades that never occurred `[V]`.
- **Latent NAV error: $258,631.78 of phantom gross exposure**, marked daily. A 1%
  adverse move across those five names is a **$2,586** NAV error that appears from
  nothing.
- Direction of the position error: the ledger is **long 604 HYG, 420 JNK, 858 LQD,
  58 EMB and short 1,503 JAAA that the account does not hold** — net **+$106,427.64**
  of exposure the book does not have. Reported NAV will therefore **overstate**
  gains in a rally and **overstate** losses in a sell-off across those names, with
  the JAAA short pulling the other way.

`null_trader`'s reported NAV of **641,105.36** at 2026-09-10
(`phase0_live/book_status.json`, `nav.csv`) `[S]` is wrong by an amount that is
**$48.88 today and grows with every subsequent close**. It cannot be corrected to
a single number without knowing at what prices each historical divergence opened.

### 6.3 What I could not bound

- **Per-book cash.** One IBKR account, three books, no per-book cash at the
  broker. Every sleeve's `cash` is a ledger construct. To bound it you would need
  a full cash-flow reconstruction from executions plus commissions plus
  distributions, per book, since 2026-07-30 — the executions for which were lost
  before 2026-07-31 (302 executions, `ops/capture_fills.py` docstring `[S]`).
- **Why the five orders did not fill.** Needs `reqOpenOrders` status history or
  the TWS log; not on disk.
- **The USD/CAD question in §5.** Needs an FX rate and an account-currency
  determination I did not fetch.
- **The `bench_b1`/`bench_b6` shared-symbol rows** (HYG, USHY, VCIT, EMB, JNK,
  LQD, SHYG): the account net cannot split them, and the only artefact that
  claims to — `_attribution.json` — is 7 sessions stale and demonstrably off by
  one wherever the broker *can* arbitrate it.

---

## §7 `_pre_epoch_*` and `_prerebuild_*`

**What they are.** Archives written by `ops/reset_epoch.py:213` (`_pre_epoch_`)
and `ops/rebuild_ledger.py:171` (`_prerebuild_`) immediately before the live
sub-ledger is overwritten. Nine exist:

| archive | nav rows | span | trades | note |
|---|---:|---|---:|---|
| `cef_live/.../_pre_epoch_cef_discount_20260907_155225` | 25 | 2026-07-30 → 2026-09-03 | 397 | the real pre-epoch CEF history |
| `cef_live/.../_pre_epoch_cef_discount_20260908_170128` | 1 | 2026-09-08 only | 0 | the **first** epoch, itself archived a day later |
| `benchmarks_live/.../_pre_epoch_bench_b1_hyg_20260907_160249` | 27 | 2026-07-30 → 2026-09-04 | 3 | |
| `..._bench_b3_agg_20260907_160249` | 27 | 2026-07-30 → 2026-09-04 | 3 | |
| `..._bench_b4_60_40_20260907_161916` | **0** | — | 0 | **header only; b4 never had a ledger** |
| `..._bench_b5_shy_20260907_160250` | 27 | 2026-07-30 → 2026-09-04 | 3 | |
| `..._bench_b6_ew_credit_20260907_160250` | 27 | 2026-07-30 → 2026-09-04 | 15 | |
| `..._bench_b6_ew_credit_20260907_162044` | 1 | 2026-09-08 only | 0 | b6 was epoch-reset **twice**, 18 minutes apart |
| `phase0_live/.../_prerebuild_null_trader_20260731_173307` | 1 | — | 0 | pre-rebuild snapshot |

**Does anything read them?** **No.** Every reader addresses
`_ibkr_shadow/<sleeve>/` by explicit sleeve name — `dashboard/server.py` iterates
a hard-coded `BENCH_LABEL` dict (line 1122), `weekly_book_report.py` iterates the
book spec's `sleeves` list, `ibkr.py`, `capture_fills.py`, `reconcile_orders.py`
and `rebuild_ledger.py` all take `sleeve` as a parameter. No glob over
`_ibkr_shadow/*` exists anywhere `[V]`:

    grep -rn "_ibkr_shadow" --include="*.py" . | grep -v "\.git/"
    grep -rn "pre_epoch\|prerebuild" --include="*.py" --include="*.sh" --include="*.md" .

Only the two writers name them. They are inert.

**Does the epoch reseed make pre-epoch history unusable for a continuous track
record?** **Yes, and it was already unusable before the reseed.** The epoch
manifest states the reason in its own words:

> `"epoch_reason": "pre-epoch ledger booked 22 sessions of fills the account never
> made (broker port misconfigured 2026-08-03..2026-09-03); archived, not deleted"`

`[S]`, from `_pre_epoch_cef_discount_20260908_170128/manifest.json`. The archived
CEF series runs 2026-07-30 → 2026-09-03 and ends at **498,178.71**; the live
series restarts at **500,000.00** on 2026-09-08 `[V]`. The two cannot be spliced:
the $1,821.29 step is not a real loss being written off, it is a fictional series
being replaced by a declaration. Of the 25 archived NAV rows, 22 are contaminated,
so at most three (2026-07-30, 07-31, and the funding row) survive scrutiny — and
2026-07-31 is the 100.5bp overnight-market-order incident.

**Consequence for the deliverable.** The CEF book's honest live track record is:

| | |
|---|---|
| NAV observations | **2** (2026-09-08 epoch, 2026-09-09 mark) |
| trades in the live ledger | **0** |
| broker-confirmed fills post-epoch | **0** (all 294 pre-date it) |
| return that can be quoted | **+0.9146% over one session**, on a declared base |

Any claim of absolute return since inception (2026-07-30) is not supported by
anything currently on disk. `bench_b4_60_40` is worse: it has **1 NAV row and no
archive at all**, so it has no history in any form, and the dashboard's comparison
chart drops all five benchmarks because `len(df) < 2` (`dashboard/server.py:1138`)
`[V]`.

---

## §8 What would have to be true to fix this

Stated as conditions, not instructions. None of this was done.

1. **One NAV, one sizing path.** The adapter and the shadow sub-ledger must size
   from the same NAV value in the same session. Either the sub-ledger advances
   before `place_targets` reads `_sleeve_nav`, or `_resolve_qty` is handed the NAV
   explicitly rather than re-reading a file whose freshness depends on call order.
   Until then every armed CEF session opens a fresh divergence (§1.3), and
   `min_trade_usd` will keep admitting orders on one side of the gate and not the
   other.
2. **The ledger must book what was sent, not what it wanted.** `orders.csv` and
   `trades.csv` should be written from `_order_map.csv` and `broker_fills.csv`,
   not from the simulator's intent. That single change would have prevented all
   five of today's phantom null-trader fills and the entire $258,631.78.
3. **`orders.csv` status must be reconciled from fills.** `ops/reconcile_orders.py`
   exists and reads exactly the three files needed (`positions.csv`,
   `_order_map.csv`, `orders.csv` — lines 70/89/102). Whether it runs in the
   session is not established here.
4. **Fill capture must attribute across books, not within one.**
   `ops/capture_fills.py` needs the union of all three books' `_order_map.csv`
   files, or an account-level order map. Its current shared-ticker check is
   correct in logic and wrong in scope.
5. **`_attribution.json` must be regenerated or retired.** The CEF one is 28
   sessions stale, the benchmark one 7, and it claims 16 SPY the account does not
   hold. Regenerating it requires a broker call
   (`scripts/ops/reconcile_attribution.py --write`, which also defaults to
   **port 7497** at line 107 — the misconfiguration that dry-ran 21 sessions).
6. **A NAV that is corroborated by something.** Today every consumer reads the
   same unverified two-row file. A second, independent NAV — reconstructed from
   `broker_fills.csv` plus marks — would have caught all of this. It is buildable
   from artefacts already on disk for the CEF sleeve, whose 294 fills cumulate
   exactly to its positions (§3.4).
7. **A decision about the track record.** With 0 trades and 2 NAV rows post-epoch,
   the competition deliverable currently has no live history. Either the epoch is
   the declared inception and that is stated plainly wherever a return is quoted,
   or the pre-epoch series is rehabilitated — which cannot be done, because the
   fills it booked never happened.

---

## §9 Guard blocks encountered

Reported, not worked around, per the standing rule.

1. `wc -l src/deploy/exec_ledger.py src/deploy/portfolio.py src/deploy/run_book.py ...`
   — blocked by `.claude/hooks/guard_order_path.py` because the argument list
   named `run_book.py`. I wanted a line count. Not retried in any other form, and
   `run_book.py` was not read. **Consequence:** the ordering claim in §1.2 (that
   the adapter reads `nav.csv` before the sub-ledger appends the session row) is
   inferred from arithmetic and left `[U]`. Reading the session entry point would
   settle it.
2. `sed -n '1,120p' ops/reset_epoch.py` — blocked for the same reason. I wanted to
   read the epoch semantics. Not retried. §7 is built instead from the grep hits
   the hook did return (lines 22, 28–29, 213, 223, 245–249) and from the
   `epoch_reason` recorded in the archive manifest, which is sufficient and is
   primary evidence.

---

## §10 Reproducing this note

All figures above were produced read-only, from files in the working tree plus
`results/ops/BROKER_SNAPSHOT_2026-09-10.json`. The two multi-file scripts were
written to the session scratchpad and are reproduced here so the note stands
alone. Neither writes anything.

**Reconciliation (§2), `recon.py`:**

    import json, collections, pandas as pd
    SL=[("cef_live","cef_discount"),("phase0_live","null_trader"),
        ("benchmarks_live","bench_b1_hyg"),("benchmarks_live","bench_b3_agg"),
        ("benchmarks_live","bench_b4_60_40"),("benchmarks_live","bench_b5_shy"),
        ("benchmarks_live","bench_b6_ew_credit")]
    snap=json.load(open("results/ops/BROKER_SNAPSHOT_2026-09-10.json"))
    acct=collections.defaultdict(float)
    for p in snap["positions_account_net"]: acct[p["symbol"]]+=float(p["position"])
    led=collections.defaultdict(float); mark={}; msrc={}
    for root,sl in SL:
        df=pd.read_csv(f"ops/books/{root}/_ibkr_shadow/{sl}/positions.csv")
        df=df[df.ticker!="CASH"]
        if df.empty: continue
        df["date"]=pd.to_datetime(df["date"]); d=df[df["date"]==df["date"].max()]
        dt=str(df["date"].max().date())
        for r in d.itertuples():
            if pd.isna(r.shares): continue
            led[r.ticker]+=float(r.shares)
            if pd.notna(r.close) and (r.ticker not in mark or dt>msrc[r.ticker][1]):
                mark[r.ticker]=float(r.close); msrc[r.ticker]=(sl,dt)
    for s in sorted(set(acct)|set(led)):
        d=led.get(s,0.)-acct.get(s,0.)
        if abs(d)>1e-9:
            print(s, led.get(s,0.), acct.get(s,0.), d, mark.get(s), msrc.get(s,(None,None))[1],
                  (d*mark[s]) if s in mark else None)

**Per-sleeve internal audit (§3), `ledger_audit.py`:** iterates the same seven
sleeves, reads `{positions,trades,orders,broker_fills,nav}.csv` and
`manifest.json`, and prints (a) each file's last date, (b) `positions.csv` at its
last date against `cumsum(trades.csv)`, against `cumsum(broker_fills.csv)` and
against `_attribution.json`, (c) the `nav = cash + invested` residual per row, and
(d) `orders.csv` rows with `status == "open"` and no `fill_date`.

**Today's fill decomposition (§2.1):** joins `_order_map.csv` filtered to
`asof == 2026-09-10`, the snapshot's `executions_this_tws_session` netted by
symbol, and `null_trader/trades.csv` filtered to `fill_date == 2026-09-10`.

Single-command checks used above are quoted inline in §1.1, §1.2, §3.2 and §7.
