# Closing-auction capacity, and the opening cross's cost (C5's first gate) — 2026-10-13

**Measurement only. Spends no trial: the CEF counter stays at 50 and no other
counter moves. Pre-registers nothing, changes no spec, touches nothing on the
live path, and sends nothing to a broker.** Every call made is a read-only GET:
Alpaca SIP market data, and the cef paper account's fill activities and equity
history. No order endpoint is called.

**What it answers.**

1. **Capacity.** `results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md` (§1, "two side
   observations") put the book's dollar-weighted median order at about 0.95× the
   median NYSE closing print, and said: "If prints are whole crosses, the book is
   a large part of the closing auction it trades in." This note says what that
   print is, re-measures the closing cross in the 13 deployed names, and sets the
   book's orders against it, day by day.
2. **C5's first kill test.** C5 would fill at the t+1 opening auction instead of
   the t+1 close. Its cheapest kill test is the opening cross's cost, which had
   never been measured. Here it is measured against a fair reference, beside the
   same measurement for the close, with Alpaca's `opg` rules and the exchanges'
   opening cut-offs.

**Reproduce every figure:**

```bash
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side close --sizes
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open --sizes
QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/exec_capacity_open_cross.py fetch      # resumable; ~30 min
QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/exec_capacity_open_cross.py report \
    --state /Users/simonjarvis/quantt_state/cef
```

The run behind this note is `results/cef/exec_capacity/exec_capacity_output.txt`
(§1–§6 below match its blocks). It holds counts, ratios and basis points only:
no account number, equity, position or order size. Every figure is **[V]**,
measured this session by that script, unless labelled otherwise. External
sources are in `docs/REFERENCES.md` §12o.

**Data, and their dates.**

| what | window | used for |
|---|---|---|
| Alpaca SIP auction prints, trades and NBBO quotes, 13 names | last 60 sessions, 2026-07-21 → 2026-10-13 | cross size today, and the cost comparison |
| The same, a systematic sample | every 14th session of 2016-01-04 → 2022-12-30 (126 sessions) | the tape check and the cost comparison in the fit period |
| Alpaca auction prints, every name-day | 2016-01-04 → 2022-12-30 (W4's cache) | the fit-period orders, matched to their own day's cross |
| The deployed policy's weights | `cef_prices` to 2026-09-28, `cef_nav` to 2026-09-25; **only rows to 2022-12-30 used** | the fit-period orders |
| The book's orders | every session since it opened, 2026-09-29 → 2026-10-13 (orders on 7 sessions) | participation today |

**The holdout stays sealed.** Every frame that carries a position, signal or
return stops at 2022-12-30 (`fit_only`, `_assert_fit`). The 2026 window is read
for volumes, quotes and the sizes of orders the book actually sent: no
dislocation is signed by our side, no signal is evaluated and no return is
computed on any date from 2023-01-01.

---

## The answers in brief

| question | answer |
|---|---|
| What was the "closing print"? | The `s` field of the primary's `M` (official close) print, else its `6` (closing trade) print. **On a day with a round-lot cross that is the whole cross**: NYSE reports the cross as one `6` print (the 2016–22 tape often repeats it, §1) and `M` repeats its size. **On a day without one, `M` still carries a size, and it is not the cross** (§1) |
| How big is the closing cross? | Median per name over the last 60 sessions: **3,703 shares, about $38k**, which is **0.57%** of the day's consolidated volume. The opening cross is **4.8×** larger (§2) |
| How large a share of it are our orders, at ~$100k? | **Steady state** (2026-10-01 on, 42 orders): median **5.9%**, 90th percentile **34%**, notional-weighted median **31%**. **The build from flat** (2026-09-29, 13 orders): median 16%, notional-weighted median **76%**, largest **115%** (§3) |
| And in the fit period? | Matched to its own fill day, 2016–22: median **10.7%**, notional-weighted median **52%**, 90th percentile **116%** (§4) |
| Capital where it binds | Median participation in the closing cross reaches **10% at about $0.17m** and **25% at about $0.43m** (live orders). The notional-weighted median is **already above 25% at $100k**. In the opening cross the same orders reach 10% at about **$1.2m** (median) or **$0.33m** (notional-weighted) (§5) |
| Does the opening cross cost more than the closing cross? | **Against the pre-open quote it looks far worse** (+29.8bp mean, last 60 sessions), **but that quote is not a fair reference**: 58bp wide at the half, 204s stale, and biased. **Against a mid at a matched horizon on each side, the open print is further from fair by +1.4 to +2.0bp on average in the last 60 sessions, and by +6.0 to +6.5bp in 2016–22** (medians +0.0–0.3 and +3.2bp). As an upper bound that is 3–5% (today) and 15–16% (2016–22) of the deployed book's gross return per unit of turnover (§6) |
| Can Alpaca send an opening-auction order? | **Documented yes**: `time_in_force=opg`, market or limit, routed to the primary, accepted until **09:28 ET** (after 19:00 queued for the next open), **not fractional**. One Alpaca page restricts OPG and CLS to "Elite Smart Router users"; the current docs do not. **Untested on this account** (§7) |

---

## 1. What the "closing print" is

**What the earlier note measured.** `scripts/cef/core_signal_decomp.py::auction_depth`
took, per name-day, the size and price of the primary's (NYSE, SIP code `N`)
condition-`M` print where present and condition `6` otherwise, from
`/v2/stocks/auctions`. It divided the median deployed order (dollar-weighted,
2016–22, at $100,000) by the median of those print values. Reproduced on this
note's order set the ratio is **1.00×** (the note had 0.95×; this set rounds to
whole shares and dates each order on its fill day).

**What carries volume.** The consolidated tape's specification (CTS Pillar
output spec v2.11b, 2026-01-29; `docs/REFERENCES.md` §12o) marks `6` "Market
Center Closing Trade" and `O` "Market Center Opening Trade" as updating volume,
and `M` "Market Center Official Close" and `Q` "Market Center Official Open" as
**not** updating it. So the cross is the `6` (`O`) print; `M` (`Q`) is a price
message that happens to carry a size.

**The tape check.** The script reads the primary's own trades around every
auction and checks the `6` / `O` size against them (rule in the module
docstring).

| sample | side | name-days | round-lot cross | odd-lot | no auction trade | unknown | no primary print | tape agrees with the `6`/`O` size |
|---|---|---:|---:|---:|---:|---:|---:|---|
| last 60 sessions | close | 780 | 779 | 0 | 1 | 0 | 0 | **779 of 779** |
| last 60 sessions | open | 780 | 780 | 0 | 0 | 0 | 0 | **780 of 780** |
| fit sample, 126 sessions | close | 1,638 | 1,409 | 62 | 8 | 159 | 0 | **1,409 of 1,409** (295 printed twice) |
| fit sample, 126 sessions | open | 1,638 | 1,536 | 0 | 0 | 0 | 102 | 1,487 of 1,536 |

- **"Unknown"** is a close with no `6` and no `M` (before 2020-11-04) and no
  odd-lot print after the bell: nothing says an auction ran. **PDO listed in
  2021**, so 94 of the 159 unknown closes and 92 of the 102 opens with no
  primary print are PDO before it existed.
- **"Printed twice"**: the tape repeats the `6` print, at the same size, about
  10–40ms later. It does so on every sampled closing name-day before
  2020-11-04, on 385 of 433 from then to 2022, and on none in the 2026 window.
  `/v2/stocks/auctions` lists it once. Identical sizes on every such day make
  two separate executions implausible, so it is read as one cross printed
  twice. Whether the legacy tape counted the copy in daily volume is **[U]**.
- **The 49 opens that do not check** (2016–21; none in 2026): the `O` print
  carries a 0.1ms timestamp, and continuous prints stamped in nanoseconds up to
  about 13ms earlier fall inside the 20ms window. Their cross is still the `O`
  print's size.
- **`/v2/stocks/auctions` lists at most one `6` per name-day** (0 of 19,960 in
  2016–22 carry two), and `M` repeats the `6` size on all 4,993 name-days that
  have both.

**The trap.** On a day with no round-lot cross there is no `6`, but `M` still
has a size:

- **PCN 2021-04-07**: the cross was a **74-share odd lot** (an N print coded
  `I` at 16:00:02.081); `M` said **270**, the size of the 15:59:44 regular trade.
- **MHD 2021-04-07**: no N trade after the bell at all; `M` said 100 at 16.285,
  a TRF price.
- **PHK 2026-08-20**: no N trade after the bell; at 16:10 a size-0 `9`
  ("Corrected Consolidated Close per Listing Market") and an `M` claiming
  **13,138** shares. NYSE's DMM may close a security without a trade
  (`docs/REFERENCES.md` §3, [V]).

In 2016–22, **435 name-days (2.1% of those with a primary print) have no `6`**;
on them the earlier note read a size that is not a cross. In the fit sample's
48 such name-days with an `M`, the `M` size has a median of 152 shares against
a median actual cross of 48. That is too few days to move a median, so the
0.95× was the right order of magnitude for what it measured. What it measured
was the wrong statistic (§4).

**Timing.** Legacy NYSE printed closes a minute or two late (PDI 2016-01-04:
16:02:01). Today the `6` lands 2–3 s after the bell and `M` follows it by 7 to
over 100 ms, with nothing else on N between. Continuous-market prints are
stamped within milliseconds after the bell, and after the open. The rule reads
the cross between those, and every case named above is a test
(`scripts/cef/tests/test_exec_capacity_open_cross.py`). Most of them were
written after an earlier version of the rule failed on that day, and each was
checked to fail against the version it replaced.

---

## 2. How big the closing cross is (last 60 sessions)

The crosses below are **without us**: under the paper `late_market` exception
(`CLAUDE.md` rule 3) the book's orders are market orders 8–2 minutes before the
close, so they never entered either auction.

| name | close cross, median shares | median $ | 10th pct shares | days without a round-lot cross | close cross / day's volume | open cross, median shares | open / close |
|---|---:|---:|---:|---:|---:|---:|---:|
| AWF | 2,549 | $25,725 | 1,141 | 0 | 0.94% | 12,727 | 5.0× |
| BIT | 2,924 | $35,125 | 1,556 | 0 | 0.86% | 7,232 | 2.5× |
| DSL | 3,304 | $33,797 | 2,064 | 0 | 0.56% | 13,828 | 4.2× |
| HYT | 7,895 | $66,012 | 3,749 | 0 | 0.93% | 28,444 | 3.6× |
| JFR | 5,800 | $43,720 | 2,375 | 0 | 0.85% | 24,434 | 4.2× |
| MHD | 1,881 | $21,359 | 701 | 0 | 0.43% | 20,342 | 10.8× |
| MQY | 3,703 | $39,140 | 1,455 | 0 | 0.53% | 20,205 | 5.5× |
| PCN | 2,300 | $26,076 | 861 | 0 | 0.57% | 10,976 | 4.8× |
| PDI | 11,486 | $175,687 | 5,887 | 0 | 0.33% | 67,581 | 5.9× |
| PDO | 3,822 | $49,064 | 1,745 | 0 | 0.45% | 24,742 | 6.5× |
| PFN | 3,298 | $22,029 | 1,738 | 0 | 0.77% | 11,785 | 3.6× |
| PHK | 8,468 | $37,647 | 2,088 | 1 (no trade, 2026-08-20) | 0.75% | 18,525 | 2.2× |
| PTY | 6,313 | $72,631 | 2,852 | 0 | 0.48% | 40,862 | 6.5× |
| **median across names** | **3,703** | **$37,647** | | | **0.57%** | **20,205** | **4.8×** |

**The closing cross in these funds is small: a median of about $38k per name per
day, and about half of one percent of the day's consolidated volume.** No cross
comes near NYSE's 50,000-share regulatory imbalance threshold, so no imbalance
in these names is ever published to attract offsetting interest
(`docs/REFERENCES.md` §3). The opening cross is about five times deeper.

---

## 3. Our orders against the same day's cross

Order size = the ordered quantity where the laptop's `orders.jsonl` holds the
session (2026-09-29 → 10-07), else the broker-confirmed fill (the VM era). On
the 26 name-days with both an order and a fill, ordered equals filled on 25;
the exception is a partial `cls` fill. On 2026-09-29 the book sent `cls` orders
from flat and paper expired 11 of 13, so fills would understate that
session. Each order is rescaled to $100,000 by the
account's equity on the prior close (the rescale is under 1.5%).

**Participation = our shares ÷ the same day's NYSE cross shares.**

| phase | auction | orders | median | 90th pct | max | notional-weighted median |
|---|---|---:|---:|---:|---:|---:|
| build, 2026-09-29 (13 names from flat) | **close** | 13 | 16.0% | 87.3% | 115.5% | **75.5%** |
| | open | 13 | 5.9% | 15.4% | 20.4% | 13.6% |
| catch-up, 2026-09-30 (the 7 expired names) | close | 7 | 0.8% | 5.2% | 6.9% | 4.0% |
| | open | 7 | 2.7% | 4.7% | 5.1% | 4.5% |
| **steady state, 2026-10-01 on** | **close** | 42 | **5.9%** | **34.2%** | 175.0% | **31.1%** |
| | open | 42 | 0.9% | 3.9% | 17.1% | 3.1% |

By name, steady state, closing cross (the run prints every name, and the open):

| name | orders | median | 90th pct | max | notional-weighted median |
|---|---:|---:|---:|---:|---:|
| AWF | 2 | 3.9% | 6.6% | 7.3% | 7.3% |
| BIT | 4 | 29.6% | 100.7% | 123.1% | 123.1% |
| DSL | 4 | 11.1% | 128.5% | 175.0% | 175.0% |
| HYT | 2 | 5.9% | 6.5% | 6.7% | 6.7% |
| JFR | 4 | 32.9% | 41.4% | 44.3% | 34.6% |
| MHD | 3 | 7.0% | 7.1% | 7.1% | 7.1% |
| MQY | 3 | 11.7% | 15.7% | 16.7% | 11.7% |
| PCN | 4 | 1.2% | 16.0% | 22.3% | 1.3% |
| PDI | 5 | 0.3% | 3.2% | 4.4% | 4.4% |
| PDO | 2 | 4.2% | 7.3% | 8.1% | 8.1% |
| PFN | 4 | 16.6% | 28.3% | 31.1% | 21.6% |
| PHK | 2 | 2.7% | 4.5% | 5.0% | 5.0% |
| PTY | 3 | 1.6% | 4.4% | 5.1% | 5.1% |

Two to five orders per name: read the column, not a row.

**Against the day's whole consolidated volume the same orders are small**:
steady-state median 0.02%, 90th percentile 0.20%, largest 0.34%. That is
the figure an ADV-based capacity check sees, and it is why such a check missed
this: an MOC-only book trades in a pool about 0.6% the size of the day.

---

## 4. The fit period, matched day by day — and what the 0.95× missed

The deployed policy (`band_gross_capped` on the frozen spec, decide *t*, fill
*t*+1), at the spec's $100,000, in whole shares: 2,391 orders on 681 fill days,
2016-01-28 → 2022-12-30. Each is matched to the NYSE cross of its own fill day.

| auction | orders matched | on days with no `6`/`O` (not scored) | median | 90th pct | notional-weighted median |
|---|---:|---:|---:|---:|---:|
| **close** | 2,301 | 37 orders, 2.3% of notional | **10.7%** | **116%** | **52.5%** |
| open | 2,386 | 0 | 1.4% | 9.4% | 5.8% |

A further 53 orders (close) and 5 (open) fall on name-days for which Alpaca has
no auction print at all; they are counted, not scored. MHD has no orders: it
was outside the deployed set throughout 2016–22.

**Why the ratio of medians misled.** A median order divided by a median print
says nothing about any one day. The orders that carry the notional are the
band-edge trades, and they are many times the typical cross. **Half of the
book's traded notional in 2016–22 went in orders at least half the size of that
day's entire closing cross.**

**The fit-period order sizes against today's crosses** (every order × every one
of the last 60 sessions, by dollars): median **3.3%**, 90th percentile
**25.7%**, notional-weighted median **16.4%**. **Today's closing crosses are
about 6.9× their 2016–22 size** (median across names of the ratio of each
name's median cross in shares; 2.7× for AWF to 21.7× for PDI), so the same
orders are a smaller share of them. The live book's orders sit above this
because its current orders are larger than the fit period's typical ones
(§8, the vol scalar).

---

## 5. Capital where it binds

Participation scales linearly with capital if the cross does not grow when we
join it. It may not, because nothing advertises our imbalance (§2). The capital
at which participation reaches 10% and 25%:

| order source | auction | median reaches 10% | median reaches 25% | notional-weighted median reaches 10% | reaches 25% |
|---|---|---:|---:|---:|---:|
| live, steady state (42 orders) | **close** | **$0.17m** | **$0.43m** | **$0.03m** | **$0.08m** |
| live, steady state | open | $1.16m | $2.91m | $0.33m | $0.81m |
| live, the build from flat | close | $0.06m | $0.16m | $0.01m | $0.03m |
| fit period, matched day by day | close | $0.09m | $0.23m | $0.02m | $0.05m |
| fit period, matched day by day | open | $0.73m | $1.83m | $0.17m | $0.43m |
| fit-period sizes vs today's crosses | close | $0.31m | $0.77m | $0.06m | $0.15m |

**At today's ~$100k the closing auction already binds for the trades that carry
the notional.** The typical order is a few percent of the cross, but the
band-edge trades are a third of it or more, and a build from flat is most of
it.

---

## 6. C5's first gate: the opening cross's price against a fair reference

**The measure.** For every name-day with an auction trade: |auction price −
reference mid| / mid, in bp. The auction trade is the `6` / `O` print, or the
odd-lot print where there is no round lot. The reference is the last valid
consolidated NBBO (bid > 0, ask ≥ bid; crossed quotes skipped and counted) at
three horizons, matched on each side of the auction:

| horizon | open | close |
|---|---|---|
| h0 (the task's reference) | last NBBO before 09:30 (else the prior official close, labelled) | last NBBO before the close |
| h1 | last NBBO before 09:31 | last NBBO 1 minute before the close |
| h5 | last NBBO before 09:35 | last NBBO 5 minutes before the close |

**Why three.** The pre-open NBBO is quoted by other venues before NYSE opens.
In these names it is wide and stale. The 09:31 and 09:35 mids are fair but carry
drift. The close gets the same horizons on its own side, so drift is matched;
the first minutes after the open are the more volatile, so the matching biases
**against** the open.

**Last 60 sessions** (779 name-days paired; date-clustered t, 60 dates):

| horizon | close: median / mean | open: median / mean | open − close: median / mean (t) | quoted half-spread at the reference, close / open | signed mean, close / open |
|---|---|---|---|---|---|
| h0 | 7.2 / 11.5 | 25.6 / 41.3 | +15.6 / **+29.8** (12.85) | 6.1 / **58.0** | +1.1 / **−21.9** |
| h1 | 7.3 / 12.7 | 12.1 / 14.7 | +0.3 / **+2.0** (2.61) | 4.8 / 17.9 | +1.0 / −0.3 |
| h5 | 11.1 / 15.0 | 12.8 / 16.4 | +0.0 / **+1.4** (2.13) | 4.8 / 13.2 | +0.9 / +1.4 |

**Fit-period sample, 2016–22** (126 sessions, about 1,460 name-days paired;
date-clustered t, 126 dates):

| horizon | close: median / mean | open: median / mean | open − close: median / mean (t) | quoted half-spread at the reference, close / open | signed mean, close / open |
|---|---|---|---|---|---|
| h0 | 6.0 / 8.8 | 18.8 / 134.8 | +10.6 / +115.8 (5.12) | 5.6 / **68.7** | +1.0 / **−102.1** |
| h0 without the 39 stub-like quotes (labelled, not dropped) | | 18.8 / 29.7 | / +19.7 | | |
| h1 | 6.4 / 9.8 | 11.0 / 16.0 | +3.2 / **+6.0** (9.89) | 5.1 / 16.6 | +1.3 / −0.7 |
| h5 | 7.6 / 11.2 | 12.1 / 17.8 | +3.2 / **+6.5** (8.15) | 5.3 / 12.4 | +1.5 / −1.2 |

The h0 mean is wrecked by **stub quotes** in the pre-open book: 39 name-days
(BIT, MHD, MQY) whose reference has a half-spread above 1,000bp, such as MHD's
pre-open ask of $199,999 on 2018-04-16. The script prints the figures with and
without them.

**Reading it.**

- **The h0 surcharge is the reference, not the auction.** The pre-open quote is
  58bp wide at the half, its median age is 204s, and the opening price sits
  21.9bp below its mid on average. A fair reference has no fixed sign; at h1
  and h5 the signed means are within ±1.5bp. The task's reference was therefore
  not a fair one for these funds, and the +29.8bp is not a cost estimate.
- **Against matched fair references the opening print is a little further
  from fair than the closing print, not a lot.**
  - Last 60 sessions: +2.0bp (h1) and +1.4bp (h5) on average, 0.0–0.3bp at
    the median. Per name the h1 mean difference ranges from −3.3 to +7.6bp.
  - 2016–22: +6.0bp and +6.5bp on average, +3.2bp at the median.
  - Both differences are statistically clear (t 2.1–9.9) and small.
- **Upper bound, not cost.** |price − mid| is what a participant on the
  imbalance side of every auction would pay; the other side earns it. Set it
  against the deployed book's gross return per unit of turnover. That is
  **46.1bp** on 2013-06 → 2022 and **40.8bp** on 2016–22 (output §5; total
  return, no borrow or execution cost). Against the lower figure, the
  matched-horizon upper bound is **3–5% of the edge today and 15–16% in
  2016–22**.
- **And it is already inside the trial.** C5 as written prices its fills at
  the opening-auction print, and the deployed book is priced at the close,
  which equals the closing print within $0.005 on 96.6% of name-days
  (`docs/REFERENCES.md` §8). Every auction participant gets the print. So the
  print's distance from mid is in each backtest's gross already. What a
  print-priced backtest does not see is **our own impact on the print**, and
  that scales with participation, which is about five times lower at the open
  (§3–§5).

The script prints the surcharge as a share of the edge for each horizon; it is
an input to the trial's cost grid, not a gate that closes C5.

---

## 7. Can Alpaca send an opening-auction order? The cut-offs

All 13 names list on NYSE, and "On open/on close orders are routed to the
primary exchange", so NYSE's opening auction is the one that matters.

| fact | source | status |
|---|---|---|
| `opg` + market or limit = MOO / LOO, "eligible to execute only in the market opening auction"; unfilled orders are cancelled after the open | Alpaca docs, "Placing Orders", updated 2026-08-10 | [V] |
| **Rejected if submitted after 09:28 and before 19:00 ET**; after 19:00 it is "queued and routed to the following day's opening auction" | same | [V] |
| **Fractional orders: DAY only** (OPG and CLS "No"). Extended hours: limit DAY/GTC only | same | [V] |
| Short sales under OPG: **the docs say nothing**. HTB names need an approved locate first, on live accounts only | same; "Margin and Short Selling", updated 2026-09-17 | [V] silence; a gap, not a permission |
| **Availability: the sources disagree.** Alpaca Learn (2022-03-04): "OPG and CLS orders are only available to Elite Smart Router users". The current docs carry no such line. This paper account accepted `cls` on 2026-09-29 | Alpaca Learn; docs; `CLAUDE.md` rule 3 | [U] which binds, for paper and for a live account |
| Paper fills against the NBBO and does not simulate either auction | Alpaca docs, "Paper Trading", updated 2026-07-07 | [V] |
| **NYSE (primary)**: order entry from 06:30; "Orders can be entered and cancelled until the security is opened by the DMM, which may occur after 9:30 a.m."; Rule 7.35A(f): no Auction Imbalance Freeze before a Core Open Auction | nyse.com/trade/auctions (2026); SEC Rel. 34-85962 (2019) | [V] page and approval order; [S] that the current rule text still reads so |
| NYSE Arca and NYSE American: MOO/LOO cancels rejected from 09:29; new MOO/LOO rejected from 09:29:55 | nyse.com/trade/auctions | [V] page |
| Nasdaq: MOO/LOO entry, cancel and modify until just before 09:28 | a 2025 Nasdaq filing, via a search summary | [S] |

**Alpaca's 09:28 cut-off binds, not NYSE's.** C5's timeline fits: the NAV is
public in the evening, so the plan is decided then and an `opg` order sent
after 19:00 is queued for the next open. Nothing here was tested: placing an
`opg` order is an order, and needs the team lead.

The opening cross trades on nearly every name-day: 780 of 780 in the last 60
sessions, and all but 1 of 21,602 name-days with a primary print in 2016–22.

---

## 8. What it means

### (a) Real capital

- **The MOC-only book is capacity-bound now, not at some future size.** At
  ~$100k its band-edge orders are a third of the NYSE closing cross on the
  notional-weighted median, and the build was three-quarters. At $1m, the
  typical large order would be three times the cross.
- **Nothing measured here says what that costs.** Paper never entered an
  auction, so there is no measured impact. The NYSE figure that 6.3% of
  non-Russell-1000 auction volume goes unfilled (`docs/REFERENCES.md` §3) is the
  nearest evidence, and it is not about orders this large relative to their
  cross.
- **An ADV-based check measures the wrong pool.**
  `results/cef/REAL_MONEY_COSTS_2026-10-12.md` found the paper orders "at most
  0.5% of 63-day ADV", which is true and reassuring only for a book that can
  trade all day. An MOC-only book trades in a pool about 0.6% the size of the
  day's volume. For real capital the constraint is the closing cross, so it
  should be measured in shares of the cross, by name, at the sizes the band
  actually trades.
- **The opening cross is the deeper pool**, about five times the close. That
  makes C5 a capacity question as well as a signal one.

### (b) Does C5 deserve its trial?

**Yes, on everything measured here.** Its first kill test was the opening
cross's cost:

- Against a fair reference at matched horizons, the opening print is
  1.4–2.0bp (today) and 6.0–6.5bp (2016–22) per unit traded further from fair
  than the closing print. That is an upper bound: 3–5% and 15–16% of the
  deployed book's gross edge per unit of turnover. It would kill C5 only if
  the earlier fill captured less than that. The note that proposed C5 put its
  gain at "roughly +0.1 to +0.3 gross SR before the open's extra cost", as a
  prior ([U]); only the trial measures it.
- That distance is already priced into a print-based backtest.
- Our impact on the print, the part a backtest cannot see, scales with
  participation, which is about one-fifth at the open.
- The opening cross trades on effectively every name-day.

**Two zero-trial blockers remain, and neither is a market measurement:**

1. the team lead's ruling on `CLAUDE.md` order-path rule 3 ("order type stays
   MOC");
2. whether Alpaca accepts `opg` from this account type and from the live
   account. The sources disagree, and only an order can settle it.

**Paper cannot score C5's fills any better than it scores MOC.** Both are
auction-only, and paper runs no auction.

### What would change the verdict

- **On capacity:**
  - a measured closing-auction impact for orders at 20–100% of the cross. That
    needs live fills, or NYSE imbalance data the repo does not have;
  - a change in how large the band's trades are. Every order scales with the
    vol scalar, which ranged 1.30–2.50 in the laptop's plans (2026-09-28 →
    10-08; the sleeve clips it at 2.5), so a calmer market means smaller
    orders and lower participation;
  - a decision to execute the excess beyond some share of the cross in the
    continuous market. The measured paper half-spread is about 6bp
    (`results/cef/REAL_MONEY_COSTS_2026-10-12.md`).
- **On C5:**
  - Alpaca rejecting `opg` for the account type;
  - the team lead declining the rule-3 amendment;
  - the trial itself (identical H, priced at the opening print, this note's
    surcharge on the cost grid) failing in the fit period or flipping sign
    across 5/15/30bp;
  - the signed side of C5's own orders against the opening imbalance. If C5
    systematically joined the imbalance side, the matched-horizon upper bound
    would become its cost. That is a signal-conditional statistic, so it
    belongs to the trial, not here.

---

## Gaps

- **No auction impact is measured.** Paper never entered an auction; every
  participation figure is our shares over a cross that did not contain us.
- **Whether a print-based backtest's gross includes the dislocation for C5's own
  side** is the trial's question; this note does not sign any dislocation by
  our side.
- **Alpaca `opg` availability is [U]**, for paper and for live.
- The live record is **7 sessions with orders** (62 name-days). The fit-period
  view (2,301 orders) is the larger sample; it uses 2016–22 crosses, which were
  about 7× thinner than today's.
- **If the doubled legacy `6` print were two executions**, not one printed
  twice, every 2016–22 cross would be twice as large and the fit-period
  participation half as large. The 2026 figures are unaffected (no doubling).
- **The C5 gain side is not measured here.** The t+1-session return the earlier
  fill captures per unit of turnover is the trial's own statistic (identical
  H, so it is the whole difference between C5 and the deployed book), and
  computing it would be running the trial uncounted.
- Equity for the $100,000 rescale comes from `GET /v2/account/portfolio/history`
  (1D). Checked by hand against the laptop's `equity.csv` (2026-10-07) and the
  2026-10-07 plan's equity (asof 2026-10-06), it differs by under 0.1%; the
  effect on any ratio here is below the printed precision.
- The Nasdaq opening cut-off is [S]; the current NYSE Rule 7.35A text was not
  re-read ([S]); the two sources on NYSE closing-imbalance refresh disagree
  ([U], `docs/REFERENCES.md` §12o). None of the three changes a conclusion
  here.
