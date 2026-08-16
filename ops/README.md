# `ops/` — the daily paper-trading simulator

This runs the one strategy that survived the build, on paper, so we can find
out whether anything is actually left in it before any money is committed.

**There is no broker here.** Nothing in this directory can place an order.
Fills are simulated against closing prices from the same cost model the
backtests used. If you ever want it to trade for real, that is a different
project with a different review.

---

## Read this before you read anything else

The strategy is the fallen-angel ETF tilt: hold **37.2% ANGL / 62.8% BIL**,
rebalanced at each month-end, on a **$60,000** book.

Two facts that the ops layer prints on every run, and that you should not let
familiarity soften:

1. **The crowding kill criterion has already fired.** Trailing 36-month
   ANGL-vs-HYG alpha is −0.77%/yr against a +1.06%/yr planning floor, and it
   has been below that floor for 36 consecutive months against a trigger of 6.
   The encoded action is **CUT SIZE**. This was true on the day the sleeve was
   funded. `ops/monitor.py` surfaces it at the top of every run and
   `ops/weekly_report.py` puts it in the headline table.

2. **The edge being paper-traded is small and the tail is not.** Risk-matched,
   the book is expected to earn roughly **$194/yr** at $60k, against a worst
   month of about **−$2,934** and a max drawdown of about **−$7,006**. One bad
   month costs about fifteen years of edge. The point of paper trading is to
   find out whether the edge is there at all, not to collect it.

The full argument is in `results/S1_FALLEN_ANGEL.md` (and its liquidity
addendum), `results/S1_BOND_LEVEL.md`, `results/S2_TREND_VALUE.md` and
`PREREGISTRATION.md` Gate S. Read them before changing anything here.

---

## The files

| file | what it does |
|---|---|
| `spec/frozen_spec.json` | **The only place target weights come from.** Weights, book size, rebalance rule, Gate S parameters, and the provenance of each choice. Change the book here and nowhere else. |
| `common.py` | Paths, the spec loader, and the local price store. No decisions live here. |
| `daily_run.py` | The daily job. Pulls prices, appends them to the store, advances the ledger, writes today's target vs current positions. |
| `ledger.py` | The position and trade book. Simulates fills at the next close ± half the configured spread plus market impact. Never fills a day twice. |
| `monitor.py` | The Gate S divergence check, plus the S1 crowding light. |
| `weekly_report.py` | Writes the weekly markdown report into `ops/reports/`. |
| `smoke_test.py` | Runs the whole chain on historical data and checks it. Run this after changing anything. |
| `state/` | All persisted state. Plain CSV and JSON — open them in a spreadsheet. |
| `reports/` | The weekly reports. |

### What is in `state/`

| file | one row per |
|---|---|
| `prices.csv` | (date, ticker) — close, distribution, volume, source, when it was fetched |
| `orders.csv` | rebalance decision — what we wanted to trade and at what price we decided |
| `trades.csv` | simulated fill — what we got, and the slippage against the decision price |
| `positions.csv` | (date, ticker) — shares held and their market value, daily |
| `nav.csv` | date — book value, cash, distributions, costs, daily return, and *why* we traded that day |
| `gate_s_bands.json` | the stored bootstrap bands (see below) |
| `monitor_status.json` | the last monitor verdict, machine-readable |
| `target_vs_current.csv` | today's target book against what is actually held |

---

## The first run funds the book — pick the date deliberately

`ops/state/` is empty. The **first** `daily_run.py` against it creates the
ledger, funds it with the spec's `book_usd`, and buys the target book at the
next close. That is a decision, not a chore, so make it on purpose:

```bash
python3 ops/daily_run.py --start 2026-07-20     # first run only
python3 ops/daily_run.py                        # every day after
```

Everything after that is automatic. If you get it wrong, delete `ops/state/`
and start again — nothing downstream depends on a ledger you threw away.

---

## Running it daily

Once a day, after the US close. Add this to `crontab -e`:

```cron
# QUANTT paper trading — weekdays at 18:30 New York time.
# Adjust the hour if your machine is not on New York time; the job only needs
# to run after the 16:00 close and before midnight.
30 18 * * 1-5 cd /Users/simonjarvis/Desktop/QUANTT/2027 && /usr/bin/python3 ops/daily_run.py >> ops/state/daily.log 2>&1

# Weekly report and full monitor — Saturday morning.
0 9 * * 6 cd /Users/simonjarvis/Desktop/QUANTT/2027 && /usr/bin/python3 ops/weekly_report.py >> ops/state/weekly.log 2>&1
```

By hand:

```bash
cd /Users/simonjarvis/Desktop/QUANTT/2027

python3 ops/daily_run.py                 # the daily job
python3 ops/monitor.py                   # Gate S + crowding, any time
python3 ops/weekly_report.py --print     # the weekly report
```

Useful flags:

```bash
python3 ops/daily_run.py --asof 2026-07-17      # pretend today is that date
python3 ops/daily_run.py --source local         # replay the audited panel, no network
python3 ops/monitor.py --rebuild-bands          # after changing the frozen weights
python3 ops/monitor.py --refresh-crowding       # re-runs scripts/s1_crowding_monitor.py
python3 ops/smoke_test.py                       # the whole chain, on history
```

**It is safe to run twice.** A second run on the same day is a no-op and says
so. **It is safe to miss days** — a holiday, a laptop that was shut, a week
away. The next run walks forward through every trading day it missed, in
order, and fills them the same way it would have live.

---

## How a day is simulated

1. **Distributions** on shares held into the previous close are credited as
   cash, exactly as a real account receives them.
2. **Yesterday's order fills at today's close**, at
   `close × (1 ± (half_spread_bp + impact_bp)/10000)`, where `impact_bp =
   impact_coefficient × daily_vol_bp × √participation` — the same square-root
   law and the same numbers the backtest engine uses, read from
   `config/costs.yaml`. Nothing is hardcoded.
3. **Everything is marked at today's close** and the NAV row is written.
4. **On a rebalance day, tomorrow's order is written**, using today's close as
   the decision price.

Deciding on one close and filling at the next matches the engine's T+1 rule
and is the honest retail convention: you see the close, you trade the next one.

**Rebalance timing.** The book rebalances when no business day is left in the
month. If the last business day of a month is a market holiday — Good Friday
closed March 2024, Memorial Day closed May 2021 — that day never arrives, so
the rebalance happens on the first trading day of the next month instead and
the `decision` column in `nav.csv` records it as *late*. Verified against both
of those months.

### Four ways the simulator is deliberately harsher than the backtest

These are real frictions, not modelling noise, and they are why the live path
should sit slightly *below* the backtest:

- **Whole shares only.** No fractional shares, so a few hundred dollars sit in
  cash between rebalances earning nothing.
- **Distributions wait.** Dividend cash sits idle until the next month-end
  rather than compounding instantly.
- **Drift rebalancing is charged.** The engine charges cost on changes in
  *target* weight, and a fixed tilt has the same target every day — so the
  backtest under-counts the month-end drift trades. `results/CALIBRATION.md`
  records that defect; `results/S1_FALLEN_ANGEL.md` measures the omitted cost
  at about 0.0009%/yr.
- **Fills cross the spread every time**, including on tiny drift trades.

The smoke test measures the total: over a replayed year the simulator came in
**13.4 bp below** the engine on the identical window and weights. A gap the
*other* way, or one much larger, means something is broken.

---

## Gate S — the divergence check

Straight from `PREREGISTRATION.md`:

> Bands set from block-bootstrap of the audited backtest (10th–90th percentile
> of 3-month return and Sharpe). Live-sim inside the band → continue; below
> 10th pct → halve size and review; drawdown > 1.25× backtest maxDD →
> suspend, written review.

All three are encoded in `monitor.py`:

| condition | action |
|---|---|
| 3-month return and Sharpe inside the 10th–90th band | `CONTINUE` |
| either below the 10th percentile | `HALVE_SIZE_AND_REVIEW` |
| live drawdown worse than 1.25 × backtest maxDD | `SUSPEND` |
| fewer than 63 live trading days | `INSUFFICIENT_DATA` — not graded |

The bands are built once and stored in `state/gate_s_bands.json`, from a
moving-block bootstrap (1,000 replications, 126-day = 6-month blocks) of the
frozen book's own backtest. Each replication is cut into non-overlapping
63-day windows; the windows are pooled and the 10th and 90th percentiles read
off. The risk-free leg rides the same block draws, so a resampled Sharpe never
pairs a 2020 return with a 2023 bill rate.

**The bands are built on 2017 onward, not the full sample.** That is a
deliberate choice, made on the explicit instruction of
`results/S1_FALLEN_ANGEL.md` recommendation 3: bands built on 14-year returns
*"will be far too generous to catch a sleeve that is already earning zero."*
2017 is also the first year ANGL's median daily volume clears $8M, so it is
the first year a book this size could actually have traded it.

Current stored values, for the frozen 37.2/62.8 book:

| | p10 | median | p90 |
|---|---:|---:|---:|
| 3-month return | −1.11% | +1.04% | +2.52% |
| 3-month Sharpe | −1.747 | +0.750 | +3.986 |

Suspend if the live drawdown goes past **−14.60%** (1.25 × the backtest's
−11.68%).

**Gate S is not graded until there are 63 live trading days.** A comfortable
`CONTINUE` off two weeks of data would be worse than no reading at all, so the
monitor refuses and reports how many days are left. Note also how wide the
Sharpe band is: three months of daily data barely constrains a Sharpe ratio at
all, so the return band will do most of the work in practice, and neither band
should be mistaken for a precise instrument.

`PREREGISTRATION.md` allows the bands to be adjusted after the first review
period — **in writing, before the next period.** Not after seeing a result you
dislike.

---

## The crowding light

`monitor.py` does not re-derive the crowding alpha. It reads
`results/s1_crowding_rolling_alpha.csv`, which `scripts/s1_crowding_monitor.py`
writes, and re-applies **that script's own constants** (`HAIRCUT_FLOOR`,
`KILL_N_MONTHS`) by importing them. The two therefore cannot quietly disagree.

- The light is reported on every `monitor.py` run, in the headline of every
  weekly report, and in the action list.
- If the rolling-alpha file is more than 45 days old the monitor says **STALE**
  and tells you to re-run the script. A stale green is not a green.
- If the crowding light cannot be read at all — a broken import, a missing file
  — it reports `UNREADABLE` and is **treated as RED**. A monitor that goes
  quiet is not a monitor that is happy.

One honesty note that belongs here rather than buried in a memo: the three red
lights (L1 latest alpha, L2 run length, L3 decay trend) are *three readings of
one fact* — the 36-month alpha has fallen — not three independent
confirmations. That is exactly why the encoded action is cut size and not shut
down. And the single light that is specifically about *crowding* rather than
performance (L5, fallen-angel ETF volume share of HYG) is **green and falling**.
So: cut size because the edge is gone, not because we proved the trade is full.
Why it is gone is still unexplained.

---

## What a human must check, weekly

1. **Did the job run every trading day?** Gaps in `state/nav.csv` mean cron did
   not fire. The next run catches up, but you want to know.
2. **Any `LIQUIDITY WARNING`?** A trade above the 10% participation cap in
   `config/costs.yaml` is simulated anyway and flagged — a real order that size
   would not have filled at the close. At this book size it should never
   happen; if it does, something is wrong with the size or the volume data.
3. **Any `SPLIT DETECTED`?** The simulator does **not** adjust held shares for
   a split. You must fix the ledger by hand. `data/README.md` records splits in
   BIL (1:2, 2017) and JNK (1:3, 2019), so this is a live possibility for BIL.
4. **Any restated bars?** `prices.csv` keeps the first value it stored and
   prints a warning if the vendor later disagrees. Investigate rather than
   passing `--refetch` reflexively.
5. **Is the crowding file stale?** Re-run `scripts/s1_crowding_monitor.py`
   monthly. It also accumulates the AUM snapshots that light L6 needs — it
   requires 12 dated observations and has 1, so this only becomes gradeable if
   somebody actually runs it every month.
6. **Is the slippage table behaving?** Size-weighted spread+impact should sit
   near the config assumption (about 3bp on ANGL, 0.5bp on BIL). The overnight
   move should average toward zero across many trades; if it does not, the
   decision rule is systematically trading into a move, and that is worth
   knowing.
7. **If Gate S says HALVE or SUSPEND, that is a written review** — not a
   judgement call made at the keyboard at 6pm.

---

## Changing the book

If the IC memo freezes a different rung, edit **`spec/frozen_spec.json`**:
change `allocation.weights`, add a `changelog` entry, then

```bash
python3 ops/monitor.py --rebuild-bands
python3 ops/smoke_test.py
```

Rebuilding the bands is not optional — they are derived from the weights, and
`monitor.py` will refuse to grade against bands built for a different book (it
detects the mismatch and rebuilds automatically, loudly).

Do not edit anything in `state/` by hand. If the ledger is wrong, work out why,
fix the code, delete the state directory and replay. The state is meant to be
reproducible from the code plus the price store.

---

## Known limitations, stated plainly

- **Whole shares, and cash earns nothing.** Residual cash between rebalances
  sits idle rather than in BIL. Worth a few basis points a year; measured, not
  assumed away.
- **Fills are at the close.** No intraday execution, no limit orders, no
  partial fills. A market-on-close order is the closest real-world analogue and
  is what a retail account would plausibly do.
- **Splits are detected, not handled.** See check 3 above.
- **The price feed is yfinance.** It is free and it is occasionally wrong. The
  store keeps the first value it saw and flags restatements rather than
  absorbing them, which is why the conflict warning exists.
- **One strategy only.** Strategy 2 was rejected and E2 authorises no pilot, so
  there is nothing else to run. If a second sleeve is ever funded it gets its
  own spec file and its own state directory, not a second set of columns in
  these files.
