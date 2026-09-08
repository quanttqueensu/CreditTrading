# The short leg has never been charged — 2026-09-06

First measurement of borrow cost and borrow availability for the 17 frozen CEF
names. Closes PLAN.md Phase 0 item 1.

Reproduce: `scripts/cef/fetch_borrow_rates.py --api --positions`,
`scripts/cef/borrow_impact.py`, `scripts/cef/borrow_capacity.py`.

## Verdict

Borrow costs **1.22%/yr** on held short market value, which is **0.23 of Sharpe**.
The live configuration's net Sharpe after spread and borrow is **0.10** — not
distinguishable from zero at any sample size we will have this year. The same
book under a no-trade band is **0.48**.

Borrow scales with holdings, not turnover, so it is not reduced by trading less.
It is reduced by shorting different names.

Separately, **availability binds today**: NAD's borrow pool supports roughly
$45,000 of capital against the $500,000 we run.

## Source

`https://www.interactivebrokers.com/shortstock/usa.txt` — pipe-delimited,
no authentication, refreshed intraday, stamped `2026.09.04 23:46`. It is the only
source carrying an actual fee rate. The historical
`ftp://shortstock.interactivebrokers.com` host is retired and now NXDOMAINs.

Cross-checked against the TWS API (generic tick 236 → `shortableShares`) on the
paper account. **The account has no NYSE top-of-book subscription (error 10089)**,
so the request must run under `reqMarketDataType(3)`; delayed data returns tick
89 fine. The two sources agree within a few percent on all 17 names, which is the
only reason the file is trusted here.

## Measured rates

| ticker | fee % | available | API avail | | ticker | fee % | available | API avail |
|---|---:|---:|---:|---|---|---:|---:|---:|
| **HYT** | **10.56** | 2,500,000 | 2,526,664 | | PFN | 0.83 | 900,000 | 939,666 |
| **NAD** | **9.98** | **3,000** | 5,172 | | MQY | 0.76 | 150,000 | 189,310 |
| **NVG** | **4.23** | **20,000** | 23,999 | | PCN | 0.63 | 1,800,000 | 1,907,274 |
| NEA | 3.06 | 150,000 | 224,336 | | BIT | 0.62 | 250,000 | 282,050 |
| NZF | 2.58 | 150,000 | 276,934 | | PDI | 0.51 | 6,400,000 | 6,545,529 |
| JFR | 1.45 | 950,000 | 971,851 | | PDO | 0.43 | 1,000,000 | 1,230,442 |
| PTY | 1.09 | 5,700,000 | 5,810,277 | | DSL | 0.42 | 950,000 | 1,033,565 |
| PHK | 1.06 | 1,300,000 | 1,376,912 | | MHD | 0.41 | 250,000 | 291,444 |
| | | | | | AWF | 0.28 | 650,000 | 662,610 |

Median 0.83%, mean 2.29%, max 10.56%. Against the `FinancingModel`'s flat
**+50bp**, whose docstring calibrates it for *"liquid Treasury/IG ETFs (general
collateral bucket)"*. Six of seventeen names are above 1%; two are above 9%.

## Effect on the answer

Applying the measured schedule to held short weights, 5,452 days, 2005→2026:

| policy | gross SR | +spread@15bp | +50bp assumed | **+measured borrow** |
|---|---:|---:|---:|---:|
| **calendar 2d — LIVE** | 1.20 | 0.33 | 0.29 | **0.10** |
| band 4.8% | 1.16 | 0.66 | 0.62 | **0.43** |
| band 6.4% | 1.11 | 0.71 | 0.67 | **0.48** |

Borrow removes a near-constant 0.23 Sharpe, because it is a fixed ~1.22%/yr drag
against ~5.3% vol and does not depend on the trading policy. It therefore does
not change the *ranking* in PLAN.md §2.2 — but it changes what the ranking means.
The band was an improvement from 0.33 to 0.71. It is now the difference between a
strategy that is indistinguishable from zero and one that is not.

## Where the drag is

Average short weight × fee, live calendar:

| ticker | avg short wt | fee % | drag %/yr | share |
|---|---:|---:|---:|---:|
| **HYT** | 0.0338 | 10.56 | 0.357 | **29.2%** |
| **NAD** | 0.0327 | 9.98 | 0.327 | **26.7%** |
| **NVG** | 0.0403 | 4.23 | 0.170 | **13.9%** |
| NEA | 0.0321 | 3.06 | 0.098 | 8.0% |
| NZF | 0.0355 | 2.58 | 0.091 | 7.5% |
| PHK | 0.0488 | 1.06 | 0.052 | 4.2% |
| *(11 others)* | | | 0.130 | 10.5% |
| **total** | 0.3962 | | **1.225** | 100% |

**Three names are 70% of the cost.** Two of them — NAD and NVG — are Nuveen munis
and therefore the same names carrying PC2, the 65.7% risk factor of §4.2. The
concentration problem and the borrow bill are the same trade. That is a
connection PLAN.md did not have, and it means one fix can address both.

## Two things PLAN.md §3.3 got wrong

1. **The premium hypothesis is refuted.** §3.3 reasoned that the largest premiums
   — PHK +22.6%, PTY +13.9%, PCN +10.4% — would be the crowded, hard-to-borrow
   shorts. Measured: **PHK 1.06%, PTY 1.09%, PCN 0.63%**, all below the 2.29%
   mean. Premium does not predict borrow cost in this universe. The expensive
   names are a high-yield fund (HYT) and the muni complex.

   Consequence for Phase 0 item 5: PHK's fifth failing measure was "largest
   premium, so most likely hard to borrow." That measure is now **false** and is
   withdrawn. The other four — slowest reversion at 41.9bd, widest discount sd at
   6.92pp, most expensive tick at 10.65bp, leave-one-out Sharpe rising 2.49→2.93
   — are unaffected and still stand.

2. **The order of magnitude was optimistic in the wrong direction.** §3.3's
   scenario table offered 50bp / 300bp / 1000bp. The realised weighted average on
   the *current* book is **3.62%**, i.e. squarely in the 300bp row — but the
   historical average is 1.22%, so the live book today is roughly three times as
   exposed as typical. That is not bad luck: the signal currently has us short the
   entire Nuveen muni complex simultaneously, which is precisely the PC2
   concentration §4.2 warned about, now with a cash cost attached.

   Live book, 2026-09-03: short MV $379,356, weighted-average borrow **3.62%**,
   annual drag **$13,732 = 2.75% of the $500,000 capital base**.

## Availability is a separate, harder constraint

Cost is a price. Availability is a position you cannot take at any price, and the
two bind on different names: HYT is expensive (10.56%) but plentiful (2.5m
shares); NAD is expensive **and** scarce (3,000 shares).

`AVAILABLE` is the pool IBKR can lend *now*; it does not count shares already lent
to us. So our 6,643-share NAD short is **not a violation** — it is located and
borrowed. What it means is that we cannot add to it, and that a recall would leave
us with nothing to re-borrow.

Capital at which each name's 95th-percentile short exceeds 25% of its visible pool:

| ticker | binds at | | ticker | binds at |
|---|---:|---|---|---:|
| **NAD** | **$44,978** | | DSL | $12.3m |
| **NVG** | **$278,385** | | HYT | $22.5m |
| NZF | $2.16m | | PDO | $33.3m |
| NEA | $2.27m | | PTY | $68.8m |
| PHK | $4.31m | | AWF | $70.6m |
| JFR | $12.1m | | PDI | $86.4m |

Share of the desired short book that is unfillable:

| capital | names binding | unfillable |
|---:|---:|---:|
| **$500k (today)** | 2 | **11.4%** |
| $2m | 2 | 15.8% |
| $5m | 5 | 27.8% |
| $10m | 5 | 37.9% |
| $25m | 8 | 52.5% |
| $50m | 9 | 63.9% |

**This is the first capacity estimate the programme has produced.** At the current
construction the strategy holds roughly $5m before availability materially
degrades it.

## The fix, and its price

Cap each name's short weight at the borrowable size, then scale the long leg to
match so the book stays dollar-neutral. Longs are never capped — you can always
buy. This is a feasibility projection at construction, not a name exclusion, and
it composes with a borrow-aware score rather than competing with it.

| capital | gross SR | net@15bp | borrow % | **net + borrow** | avg gross |
|---|---:|---:|---:|---:|---:|
| uncapped | 1.20 | 0.33 | 1.22 | **0.10** | 0.79 |
| **$500k** | 1.16 | 0.32 | **0.88** | **0.14** | 0.71 |
| $2m | 1.12 | 0.31 | 0.76 | 0.15 | 0.65 |
| $5m | 1.08 | 0.27 | 0.65 | 0.12 | 0.57 |
| $10m | 1.05 | 0.24 | 0.56 | 0.08 | 0.48 |
| $25m | 0.93 | 0.18 | 0.43 | 0.04 | 0.37 |

**The constraint pays for itself.** At $500k it costs 0.04 of gross Sharpe and
saves 0.34%/yr of borrow, for a net gain of +0.04. The reason is not subtle: the
positions the cap removes are the scarce ones, and in this universe scarce is
correlated with expensive. Feasibility and cost point the same way.

It stays positive to about $5m and decays past $10m, which is the same capacity
number arrived at independently.

## Caveats

1. **One day of rates applied to 21 years.** The panel begins today
   (`data/cef/cef_borrow.csv`, append-only). Everything above is the
   counterfactual "if today's schedule had held throughout", not a historical
   cost. It is still the right basis for a forward decision — the question is what
   we will pay going forward, not what 2011 would have cost — but it is not a
   backtest of realised borrow and must not be quoted as one.
2. **Rates move, and for CEFs they move with the fund's own premium**, which is
   the signal itself. A short that gets more attractive may get more expensive at
   the same time. This is not modelled and could make the drag worse than measured
   exactly when the signal is strongest.
3. **Availability is a snapshot.** The φ=0.25 haircut in the capacity test exists
   because of this, and is a judgement, not a measurement.
4. **Paper account.** No borrow has actually been charged to this book; the
   ledger's `FinancingModel` still applies its flat 50bp.

## What this changes

- Phase 0 item 1 — **done**.
- Phase 0 item 5 (drop PHK) — one of five arguments withdrawn, four stand.
- Phase 1 (the band) — unchanged in rank, materially more important in stakes.
- Phase 2 (leverage) — **now gated on a real number**. Levering a 0.10 net Sharpe
  multiplies a drag that is nearly the whole return. The vol-target decision
  cannot be taken before the band lands.
- §4.2 (covariance) — gains a second, independent motivation: PC2 and the borrow
  bill are carried by the same names.
- New: borrow-aware scoring, and an availability cap at construction.
