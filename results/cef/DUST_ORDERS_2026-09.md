# Dust orders — a band HOLD was costing ~0.75%/yr to hold

**2026-09-08. Not a trial: no specification was evaluated with sight of P&L,
and the CEF counter stays at 48.** `band_width`, `order_type`, `z_window` and
every other frozen-block key are untouched.

## The mechanism

The band decides in **weight** space. It reads the held weight as
`cur = q * px[-1] / nav`, where `px[-1]` is the last close in the **signal**
panel, finds `|target − cur| ≤ 4.8%`, and said "hold" by returning `cur` as a
weight target. The executor then converts that weight back to shares with
`floor(nav * |w| / price)` — using the close it reads on the **sizing** date.

Two different prices, two different floors. A handful of shares of difference,
and a name the band had explicitly told us to leave alone went out as a live
MOC order. The panel is a session behind the price store more often than not,
because price and NAV are inner-joined and a fund's NAV publishes after its
close (`docs/INFRASTRUCTURE.md` §6.1; the same-day-NAV wait, also landing
2026-09-08, removes that particular trigger but not the round trip itself).

There was no minimum trade anywhere on the path: `_make_orders` read
`spec["rebalance"]["min_trade_usd"]`, the frozen spec had no `rebalance` block,
so it was 0; `ibkr.py` had no minimum at all.

## Before — the 2026-09-03 signal, sized on the 2026-09-04 close

Run against the **pre-change** sleeve; the identical command against the code
as it now stands is the "After" block below.

```
$ python3 scripts/cef/dust_check.py orders --signal 2026-09-03 --sizing 2026-09-04 --min-trade 0
signal 2026-09-03 / sizing close 2026-09-04 / min_trade_usd 0 / nav $500,000
n_orders 13  n_by_kind {'dust': 13}  gross $3,151
  PDO     -143sh  $    1,833  dust      cef band hold: |gap|<=0.0480 w=+0.1527
  NEA      +27sh  $      298  dust      cef band hold: |gap|<=0.0480 w=-0.1610
  NVG      +17sh  $      204  dust      cef band hold: |gap|<=0.0480 w=-0.1160
  PDI      -11sh  $      169  dust      cef band hold: |gap|<=0.0480 w=+0.1254
  HYT      +16sh  $      132  dust      cef band hold: |gap|<=0.0480 w=+0.0761
  PCN      -11sh  $      129  dust      cef band hold: |gap|<=0.0480 w=+0.0495
  DSL      +10sh  $      105  dust      cef band hold: |gap|<=0.0480 w=+0.0785
  JFR      +13sh  $       99  dust      cef band hold: |gap|<=0.0480 w=-0.0492
  BIT       +6sh  $       71  dust      cef band hold: |gap|<=0.0480 w=+0.1935
  MHD       -5sh  $       56  dust      cef band hold: |gap|<=0.0480 w=-0.1317
  AWF       +3sh  $       30  dust      cef band hold: |gap|<=0.0480 w=+0.0350
  PFN       -2sh  $       14  dust      cef band hold: |gap|<=0.0480 w=+0.0077
  MQY       -1sh  $       11  dust      cef band hold: |gap|<=0.0480 w=-0.0455
```

The twelve names of the live 2026-09-03 list sum to **$3,019 exactly**; the
thirteenth here is HYT, which on the night had no close in the panel and left
the executor by the unpriced path instead. Every one of the thirteen is a band
HOLD. `/api/trades` could not be used for the "before" picture today: the panel
and the price store both end 2026-09-04, so the two prices coincide and the
leak is dormant — which is exactly what makes it dangerous, and why the check
above sets the two dates explicitly.

## After — same signal, same sizing close, same book

```
$ python3 scripts/cef/dust_check.py orders --signal 2026-09-03 --sizing 2026-09-04 --min-trade 0
signal 2026-09-03 / sizing close 2026-09-04 / min_trade_usd 0 / nav $500,000
n_orders 0  n_by_kind {}  gross $0
```

`--min-trade 0` on purpose: the source fix alone removes all thirteen. The
`min_trade_usd` backstop below never gets a chance to act on them.

Real band-EDGE trades are untouched (today's live list, both fixes on):

```
$ curl -s http://127.0.0.1:8787/api/trades
n_orders 3 | n_by_kind {'rebalance': 3} | gross 17720.0 | turnover_pct 3.54
orders:    [('PDO', -1250, 'rebalance'), ('PHK', 197, 'rebalance'), ('JFR', -106, 'rebalance')]
unchanged: AWF BIT DSL HYT MHD MQY NAD NEA NVG NZF PCN PDI PFN PTY   (all band=hold, delta 0, kind=hold)
min_trade_usd 517.0
```

All 14 band-HOLD names appear in `unchanged` with a zero delta; `n_by_kind`
carries no `dust` entry. The dashboard keeps the `dust` label, and keeps it off
the zero-delta rows, so a regression shows up as an order rather than hiding
among the holds.

And through the scheduled runner, in dry run against the live book's positions
(`ops/books/_dryruns/cef/dryrun_2026-09-08.json`, 17 targets, `transmitted:
false`, no ledger writes):

```
$ EXECUTION=simulator python3 -m src.deploy.run_book --asof 2026-09-08 \
    --book ops/books/cef_discount_book.json --books-root ops/books/_dryruns/cef \
    --source local --dry-run
[dry-run] cef_discount: LONG  AWF   qty=1743   held=1743   (cef band hold: |gap|<=0.0480 w=+0.0350)
[dry-run] cef_discount: LONG  BIT   qty=8137   held=8137   (cef band hold: |gap|<=0.0480 w=+0.1933)
...
[dry-run] cef_discount: SHORT JFR   w=-0.050974  held=-3234  (cef discount z=+0.28 w=-0.0510 volscal=1.63)
[dry-run] cef_discount: LONG  PDO   w=0.124342   held=6099   (cef discount z=-1.46 w=+0.1243 volscal=1.63)
[dry-run] cef_discount: LONG  PHK   w=0.0593017  held=6392   (cef discount z=-1.77 w=+0.0593 volscal=1.63)
```

14 HOLDs, every one `qty == held_qty`; 3 TRADEs, still weight-expressed. The
sandbox at `ops/books/_dryruns/cef/cef_discount/` was seeded from the live
shadow ledger's CSVs so the dry run would see a real book — the wrapper's own
`DRY_RUN=1` path runs into a fresh `mktemp` root, where the book reads flat and
no name is ever inside the band. Its `manifest.json` was dropped in the sandbox
only (see the postscript).

## The no-op proof

House rule (`SYSTEM_AND_STRATEGY.md` §9.1): the code change alone must be a
provable no-op with the frozen key absent. `dust_check.py targets` serialises
every emitted target at full precision over the last five trading days, against
the live holdings and NAV, under a spec copy with `band_width` **deleted**:

```
$ python3 scripts/cef/dust_check.py targets --out targets_before.txt    # before the change
$ python3 scripts/cef/dust_check.py targets --out targets_after.txt     # after
$ diff <(sed -n '/^### band_width ABSENT/,/^### band_width LIVE/p' targets_before.txt) \
       <(sed -n '/^### band_width ABSENT/,/^### band_width LIVE/p' targets_after.txt)
$ echo $?
0
```

No output, exit 0: **byte-identical** across 2026-08-31 … 2026-09-04. With the
band LIVE, 158 lines differ — the 79 band-HOLD rows, before and after — and
**nothing else**: no TRADE row, no FLAT row, and no reason string changed.

```
$ diff targets_before.txt targets_after.txt | grep '^[<>]' | grep -vc 'band hold'
0
< 2026-08-31 AWF side=LONG kind=ETF qty=None   weight=0.03527831960105896 ... reason='cef band hold: |gap|<=0.0480 w=+0.0353'
> 2026-08-31 AWF side=LONG kind=ETF qty=1743.0 weight=None               ... reason='cef band hold: |gap|<=0.0480 w=+0.0353'
```

## The derived `min_trade_usd`

Belt and braces, and derived rather than guessed. An order costs IBKR's **$1
minimum commission** plus half the spread; ask what notional makes that equal
**30bp** of the trade — the top of this repo's standard cost grid, and the level
at which every calendar configuration of this strategy goes negative:

$$1 + N\cdot\frac{hs}{10^4} = N\cdot\frac{30}{10^4}
\quad\Longrightarrow\quad
N = \frac{10^4}{30 - hs}$$

`hs` is the **median half-spread of the 17 deployed names** in
`config/costs.yaml` — 10.67bp (MHD), between PDI's 6.96 and PHK's 25.77:

$$N = \frac{10^4}{30 - 10.67} = \frac{10^4}{19.33} = \$517.33 \;\longrightarrow\; \textbf{\$517}$$

Floored, not rounded: the smaller number skips fewer real trades. Note
`config/costs.yaml` carries `commission_usd_per_trade: 0.0` — the backtest's
commission-free assumption — which is not what the live account is charged; the
$1 above is the live minimum.

Written to `ops/specs/cef_discount.frozen.json` as a top-level `rebalance` block
(outside `frozen`), read by both sub-ledgers and now by `ibkr.place_targets`.
**Accepted consequence:** a genuine band-edge trade below $517 is skipped too,
and so is an exit whose remaining stub is worth less than $517 — the name sits
inside the band, or sits as a stub, until it is worth the ticket. At today's
list the smallest real order is $809.

## What the leak was worth

Twelve orders a session at the $1 IBKR minimum is $12; the half-spread on
$3,019 spread across those twelve names, at each name's own `half_spread_bp`
from `config/costs.yaml`, is $2.91. **$14.91 a session.** Over 252 sessions
that is **$3,757, or 0.75% of the $500k book** — against a band whose
net-of-borrow expectation is roughly 0.43 Sharpe at 5.3% vol, about 2.3%/yr.
**The plumbing was taking about a third of the strategy's expected return.** It
was also inflating the one number the band was pre-registered on
(`PREREG_BAND_2026-09-06.md`: turnover is the primary readout, 17.6×/yr expected
against 31.1 on the calendar): $3,019 a session is 0.60% of NAV, 1.52×/yr, which
would have padded the readout by 8.6% in the direction that reads "the band is
not working". And each of those $30–$250 tickets would have entered
`broker_fills.csv` and `slippage.csv` as a shortfall observation, where sixty
sessions of statistics (PLAN.md §7.1) would have been dominated by trades whose
rounding-to-a-penny cost says nothing about what the strategy's real trades
cost. Those three harms do not add up in dollars; the third is the expensive
one, because it corrupts the measurement the deployment exists to make.

## What changed

| file | change |
|---|---|
| `src/deploy/sleeves/cef_discount.py` | a band HOLD emits `qty=<held signed shares>` instead of the held weight. Raises, naming the ticker, if a HOLD somehow carries a weight but no quantity. The reason string is unchanged, so logs, the dashboard and `/api/verify` still read it. |
| `src/deploy/exec_ledger.py` | `_target_shares_for` returns the **signed** qty (was `floor(\|qty\|)`) and no longer consults a price for a qty target; `LongOnlySleeveLedger._make_orders` skips an exactly-zero delta. |
| `src/deploy/broker/ibkr.py` | `register_sleeve` keeps the spec; `place_targets` honours `rebalance.min_trade_usd` on `\|delta\| × price × multiplier`, never for an option, combo or bond leg, and prints every skip with ticker, delta and notional. |
| `ops/specs/cef_discount.frozen.json` | new top-level `rebalance` block, `min_trade_usd: 517.0`, with the derivation in `_min_trade_note`. Nothing inside `frozen` touched. |
| `dashboard/server.py`, `static/index.html` | `/api/trades` sizes a qty target without a price (it would otherwise have thrown on `pt.weight is None`); a zero-delta band-hold row is labelled `hold`, and `dust` now means a regression. |
| `src/deploy/tests/test_band_hold_dust.py` | 5 tests on a synthetic panel (new `src/deploy/tests/` package). |
| `scripts/cef/dust_check.py` | the two checks above, so the commands in this note are reproducible. |

`python3 -m pytest src -q` → **115 passed**.

### Two things found on the way

1. **`_target_shares_for` would have flipped every short.** It returned
   `floor(|qty|)`, which no sleeve had ever exercised because none had emitted
   a SHORT qty target. The CEF book's shadow ledger is this class, so a
   qty-expressed HOLD of −5,862 MHD would have been read as a target of
   **+5,862** and written an order to buy 11,724 shares in order to "hold" the
   position. Fixed with the sign, and pinned by a test.
2. **Zero-delta order rows.** `LongOnlySleeveLedger._make_orders` had no
   exactly-zero guard (the derivatives ledger has always had one), so a book
   that held its target wrote a zero-share ORDER row that the fill path then
   marked `skipped`: 11 of them, plus 2 left `open`, in the pre-epoch CEF
   ledger. Never a trade, never a dollar, but a phantom order in exactly the
   count the turnover readout is built from. Added.

### Postscript — unrelated, and it blocks tonight

`ops/books/cef_live/_ibkr_shadow/cef_discount/manifest.json` still carries the
**pre-epoch** row counts (orders 425, trades 397, positions 431, nav 25) while
the 2026-09-07 epoch reset left the files at 0/0/17/1. `Ledger.__init__` →
`_verify_manifest()` therefore raises `RuntimeError` on that directory, which is
`register_sleeve`, which is before the sleeve computes anything: **the next live
session dies at startup and transmits nothing.** The cause is
`ops/reset_epoch.py`, which `m.update(...)`s the epoch fields into the manifest
and never refreshes `files`. Left alone deliberately — the guard's own message
says a human inspects, restores or deletes, and repairing live ledger state is
not this note's business.
