# QUANTT Credit Trading: Infrastructure and Onboarding

**Repository:** https://github.com/quanttqueensu/CreditTrading
**Team lead:** Simon Jarvis
**Document version:** 1.0
**Last updated:** 2026-08-16

---

## How to use this document

This is the reference manual for the whole system. It is written so that any part
can be replaced without rewriting the rest. Each section stands alone.

**If you are new, read Part 1 only.** It takes about thirty minutes and gets your
machine running. Come back to the other parts when you actually need them.

**If you change something, update the section it belongs to and add a line to the
changelog below.** A document that quietly goes out of date is worse than no
document, because people trust it.

### Changelog

| Date | Version | What changed | Who |
|---|---|---|---|
| 2026-08-16 | 1.0 | First version. Written from the state of the system at the end of summer 2026. | Simon |

---

# PART 1: ONBOARDING

## 1.1 What this project is

We run a systematic credit trading strategy on a $500,000 Interactive Brokers
paper account. Systematic means the rules are fixed in advance and a computer
follows them, with no judgement calls. Paper means the money is simulated but
everything else is real: real prices, real order routing, real fills, real costs.

The system places its own orders every weekday on a schedule, checks its own
safety before every trade, records every fill, and raises an alarm if something
breaks. On a normal day nobody touches it.

## 1.2 Getting set up

You need Python 3.11 or newer. The live machine runs 3.13.5 through Anaconda.

```bash
git clone https://github.com/quanttqueensu/CreditTrading.git
cd CreditTrading
python3 -m pip install -r requirements.txt
```

The `data/` folder is not in the repository. It is 3.8 GB, which is far past what
GitHub allows. See section 1.4 for how to rebuild it, or ask Simon for a copy on
a drive, which is much faster.

You do not need broker access to do research. You only need it to trade, and
only two or three people should have it.

## 1.3 What to read, in order

1. **`HOW_WE_GOT_HERE.md`** at the repo root. The story of the summer: what we
   tried, what broke, what we got wrong. Start here. It assumes no finance
   background.
2. **`RESEARCH_AND_METHODOLOGY.md`**. How we decide whether a result is real.
   This is the part that matters most, because it is what stops us fooling
   ourselves.
3. **`RESEARCH_STATE.md`**. The living state of the project. What is deployed,
   what is dead and why, what is queued next. This file is read first and written
   last in every research session.
4. **`results/AUDIT_2026-07-31.md`**. The end-to-end audit that found three
   things wrong with the deployed strategy. The most useful single document for
   understanding where the system actually stands.
5. **`ops/AUTOMATION.md`**. How the daily automation works and what stops it.

## 1.4 Rebuilding the data folder

Most of the data can be refetched from free sources. Run these from the repo
root, in this order:

```bash
python3 scripts/cef/stage_cef.py           # closed-end fund prices and NAVs
python3 scripts/fetch/refresh_market_feeds.py   # VIX complex, Treasury futures
python3 scripts/fetch/fetch_live_sources.py     # daily free sources
python3 scripts/holdings/ingest_holdings.py     # ETF holdings, ~11k bonds
python3 scripts/holdings/fetch_nav_multi.py     # issuer-published NAVs
```

Two things cannot be rebuilt and must be copied from Simon:

- **The daily ETF holdings history.** Fund issuers publish today's holdings and
  nothing else. There is no archive, and passing a date is silently ignored. Our
  panel started on 2026-07-29 and grows by one day per day. A day we miss is gone
  permanently. This is why the collection job is separate from the trading job.
- **TRACE bond data and the forced-flow panels** (3.3 GB of `data/forced_flow2/`).
  These came from a licensed source and cannot be refetched.

## 1.5 Your first useful task

Run the strategy's validation battery and confirm you get the same numbers we
did. This proves your environment works and teaches you the strategy at the same
time.

```bash
python3 scripts/cef/validate.py
```

You should see a gross Sharpe near 1.26 and a net Sharpe near 0.82. If you get
something different, that is a real finding, not user error. Tell the team.

## 1.6 Team rules

These came out of the summer and they are not negotiable.

**A fabricated pass is the worst possible outcome.** Worse than finding nothing.
If a result looks great, your first job is to try to kill it, not to report it.

**Every research session adds a new column to the data, not a new parameter to
the model.** Searching the same data harder has brutally diminishing returns and
raises the statistical bar for everything you will ever test afterwards.

**Count every test you run.** We keep a permanent count in `RESEARCH_STATE.md`
that never resets. If you test enough ideas against the same history, one will
look brilliant purely by luck. At 10 tests the luckiest pure-noise strategy
scores about 2.1. At 162 tests it scores about 3.2. Your result is judged against
the running total.

**Classify every failure.** "It didn't work" is not an acceptable entry. See
`RESEARCH_AND_METHODOLOGY.md` for the seven failure types.

**Write the shutdown rule before you deploy, not after.** The moment to decide
when to quit is before you have money on it and a story about why this time is
different.

---

# PART 2: THE STRATEGY

## 2.1 The idea

A closed-end fund trades on the exchange like a stock, but the number of shares
is fixed forever. The fund publishes what its holdings are worth (the net asset
value, or NAV) every day, but the share price can drift far from that value,
because nobody can create or redeem shares to pull it back.

This is the whole point. An ordinary exchange-traded fund has authorised
participants who can swap shares for the underlying bonds and back again, so any
gap gets arbitraged away within minutes. We measured that machine at work: the
gap on high-yield ETFs shrank from 188 basis points in 2008 to 3.8 basis points
in 2026. That collapse is what killed our two previous strategies.

A closed-end fund has no such mechanism. Credit closed-end funds trade about
3.16% below their stated value on average, with a standard deviation of 5.95%,
which is roughly 150 times the ETF gap.

## 2.2 What the strategy does

For each fund, compare today's discount to that fund's own discount history over
the past 252 trading days. Express the difference as a z-score. Buy the funds
that look unusually cheap, short the ones that look unusually rich, hold equal
dollars on each side, and size the whole book so its volatility targets 6% a year.

The signal comes from the fund's own history, not from comparing funds to each
other. That matters, because some funds are structurally cheap forever and that
tells you nothing.

## 2.3 Why we believe it

The test that killed the ETF version reverses here. For an ETF, the discount
predicts the *NAV* moving (t-statistics of +15 to +24), which means the stale
paperwork is catching up to a price that was already correct. Trading that means
betting against genuine price discovery. For closed-end funds the discount
predicts *the price* instead (mean t of −1.75, with 6 of 18 funds beyond −2), and
barely predicts the NAV at all.

It also passes the test every previous candidate failed. Regressed against high
yield, investment grade, rates, equity, and volatility, the R-squared is 0.005.
That means 99.5% of the return is unexplained by any market we tested. The alpha
is +2.68% a year with a t-statistic of 3.11.

We then tried twice to kill it. The live book is 66% net short municipal funds
and 57% net long taxable funds, which looks like a sector bet wearing a costume.
Adding municipal ETFs and a duration spread as controls leaves the alpha at
+8.83% a year with t of 5.67. Regressing against the closed-end fund sector's own
group returns, which is the sharper control, leaves +7.63% a year with t of 5.90,
an R-squared of 0.006, and every group beta at or below 0.025. Both attacks
failed.

## 2.4 Live configuration

Frozen spec: `ops/specs/cef_discount.frozen.json`, id `cef_discount.v5.20260731`.

| Setting | Value | Note |
|---|---|---|
| Universe | 17 funds | AWF BIT DSL HYT JFR MHD MQY NAD NEA NVG NZF PCN PDI PDO PFN PHK PTY |
| z-window | 252 days | Reverted from 63 after the sealed holdout failed that change |
| Rebalance | every 2 days | Changed from 5 on 2026-07-31; 2 is the measured optimum |
| Volatility target | 6% annual | |
| Minimum daily volume | $3,000,000 | |
| Maximum NAV age | 3 business days | A stale NAV is a blind signal, not a cheap fund |
| Minimum names | 6 | |
| Order type | market-on-close | Fixes the pre-market fill disaster, see 4.5 |
| Capital | $500,000 | |
| Gross cap | $1,300,000 | |

Every setting that was changed carries a `_note` field in the spec recording the
measurement that justified it. Do not change a value without adding one.

## 2.5 Honest weaknesses

Recorded before capital moved, and still true.

- **The as-deployed net Sharpe is 0.51, not 0.82.** The backtest entered at day
  t's close using day t's NAV, but that NAV publishes *after* that close. A
  market-on-close order actually fills at t+1's close. Correcting that costs 38%
  of the Sharpe. Treat 0.51 as the honest expectation.
- **Kurtosis is 41.2.** Expect sharp single-day losses. This is not a smooth
  return series.
- **Recent performance is flat.** The most recent walk-forward block scored 0.05
  and the 2023 to 2026 era net Sharpe is 0.30. Strong history, flat present.
- **Execution costs are the binding problem, not the signal.** See section 4.5.
- **The strategy is best in calm markets, not turbulent ones.** We assumed the
  opposite and were wrong. Net Sharpe by dispersion quintile runs 1.24 (calm),
  0.59, 0.80, −0.23, 0.68 (dislocated). Sizing up into dislocation is what
  produced a 31.5% drawdown in 2008.
- **No group exposure limit exists in the spec.** The 66% municipal tilt is not a
  return risk by the regressions, but it is an unmonitored concentration.
- **Distribution data is fetched and unused.** `data/cef/cef_dist_features.parquet`
  has 11,988 rows flagging distribution cuts and raises. A cut re-rates a discount
  permanently wider, which is the classic way this strategy loses money, and the
  sleeve currently has no defence. We studied the events and found they move the
  discount the wrong way for the obvious trade, so this is a risk control problem
  rather than a signal, and it is still open.

## 2.6 The kill rule

Pre-committed before deployment. Reviewed at 60 live sessions and not before.
Kill if any of:

- (a) live net Sharpe below 0.0
- (b) realised slippage above 2x modelled for 5 consecutive sessions
- (c) the top-minus-bottom discount spread falls below 12%, half its current 22.5%

**Currently in observe-only mode.** All automatic sleeve kills return OK and log
a loud warning instead of halting, and book drawdown suspension is set to 99%.
The reason is that the paper deployment exists to generate evidence, and a sleeve
that suspends itself stops producing the data it was deployed to collect. With no
real capital at risk the usual reason to cut a losing book does not apply. The
kill rule is now a checklist a human applies at session 60, not an automatic
trigger. Broker margin limits still apply and are not ours to disable.

---

# PART 3: CODE LAYOUT

## 3.1 Map

```
src/
  deploy/          the live trading framework
    sleeve.py      the contract every strategy obeys
    registry.py    maps a strategy type name to its class, validates specs
    portfolio.py   rolls independent sub-ledgers into one book view
    run_book.py    MAIN ENTRY POINT for a live or dry session
    exec_ledger.py the sub-ledgers sleeves trade through
    fills.py       fill price maths: half spread, market impact, simulated fills
    risk.py        per-sleeve kill and halve switches, book limits
    report.py      daily reports
    sleeves/       the strategies themselves
      cef_discount.py   THE LIVE STRATEGY
      null_trader.py    the random control experiment
      credit_rv.py      killed by holdout, kept for reference
      static_weights.py benchmark books
    broker/
      base.py      the Broker interface
      ibkr.py      Interactive Brokers, 1077 lines, the arm() safety gate
      simulator.py simulated broker and a dry-run broker that sends nothing
    lib/           the v2 refine-cycle namespace, additive, does not touch v1
  backtest/        the vectorised daily engine, lookahead guard, walk-forward
  strategies/      research code for credit relative value
  data/            Cloudflare R2 access for the WRDS mirror

ops/               operations: preflight, halts, ledgers, monitoring, reports
scripts/           one-off and scheduled scripts, grouped by research family
config/            cost models and the secrets file
results/           every output, one directory per research family
docs/              this document, the project intro, the summer summary
data/              3.8 GB, not in git
```

## 3.2 The sleeve contract

Every strategy implements the same four methods, defined in
`src/deploy/sleeve.py`:

- `instruments()` returns what it trades
- `history_warmup_trading_days()` returns how much history it needs before it can
  produce a signal
- `target_positions(asof, market_state)` returns what it wants to hold
- `risk_check(ledger_view)` returns OK, HALVE, or KILL

A strategy is registered by decorating its class with `@register` and giving it an
`alloc_type` name. The registry then validates any spec claiming that type. This
matters because we shipped two bugs where a spec type was accepted and validated
with no class behind it, and the failure only appeared at run time.

## 3.3 The strategy code itself

`src/deploy/sleeves/cef_discount.py`, 239 lines. It reads the price and NAV
panels, computes the discount as `100 * (price - nav) / nav`, z-scores it against
a rolling 252-day window shifted by one day, and clips at plus or minus 4. It
then applies the cadence gate (anchored to the trading day index so the schedule
does not drift), drops names that fail the volume, NAV age, and minimum weight
filters, makes the book dollar-neutral, and scales it to hit the volatility
target using 63-day trailing realised volatility with the scalar clipped between
0.2 and 2.5.

One detail worth knowing: the minimum weight filter runs *before* neutralisation.
It used to run after, which left the book 0.37% net short, which is exactly the
market exposure this strategy exists not to have. Residual is now 1e-6.

---

# PART 4: THE LIVE TRADING SYSTEM

## 4.1 The broker connection (the paper API)

**Interactive Brokers TWS, paper account DUQ199038, at 127.0.0.1 port 7497.**

Things that will save you hours:

- **The account is Canadian dollars, not US dollars.** Any US-dollar position
  sizing has to convert. Net liquidation of about 1,000,674 CAD was 714,059 USD
  at the 2026-07-31 rate.
- **There is no real-time data subscription.** Quotes arrive 15 minutes delayed.
  We cannot look at a live price when deciding, so cost estimates come from
  historical measurement instead.
- **Historical bid-ask data does work** through a separate entitlement. This is
  how we measure what trading actually costs.
- **Use `ib_async`, never `ib_insync`.** `ib_insync` 0.9.86 is unmaintained and
  hangs forever in its asyncio handshake on Python 3.12 and up. TWS answers a raw
  socket handshake normally while the library never returns, so it looks exactly
  like a dead gateway. `src/deploy/broker/ibkr.py` imports `ib_async` first and
  falls back only if it is missing.
- **TWS restarts daily and needs a human login.** This is currently the single
  biggest operational weakness. See section 7.1.
- **`orderRef` does not survive the round trip** on this TWS build. Every
  execution comes back with an empty ref. Fill attribution is therefore done by
  symbol, which is safe only while no two deployed strategies trade the same
  ticker. `ops/capture_fills.py` refuses to run if that ever stops being true.

Credentials live in `config/.env`, which is not in git. You need:

```
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ENDPOINT=...
R2_BUCKET=...
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=17
```

Each scheduled job overrides the client id so two jobs never collide. The CEF job
uses 45, phase 0 uses its own, audit scripts use 93 and 95.

## 4.2 Books and ledgers

A "book" is a pot of capital running one or more strategies. Four exist:

| Book | Strategies | Capital | Status |
|---|---|---|---|
| `cef_discount_paper` | cef_discount | $500,000 | live |
| `phase0_null` | null_trader | $640,000 | live control experiment |
| `benchmarks_paper` | 5 static weight books | $20,000 each | live reference |
| `credit_rv_paper_v1` | credit_rv | $1,000,000 | killed, kept for reference |

Each book directory under `ops/books/*_live/` holds a shadow ledger with these
files:

| File | What it records |
|---|---|
| `nav.csv` | daily net asset value, cash, cost, turnover, return |
| `positions.csv` | what we hold |
| `orders.csv` | what we asked for, and whether it filled |
| `trades.csv` | modelled fills with cost breakdown |
| `broker_fills.csv` | **real** executions from IBKR, with exec id and commission |
| `slippage.csv` | realised versus modelled cost per name |
| `manifest.json` | row counts and last dates, verified on load |

The shadow ledger books *modelled* fills by design and remains the source of
P&L. Real executions live separately in `broker_fills.csv`. The one exception is
the null trader, which was rebuilt from real fills, because measuring real
execution is its entire purpose.

## 4.3 The arm() gate

This is the most important piece of safety code in the system. It runs after
strategy registration and before any order is placed, and it splits authority:

> The **broker** is authoritative for how many shares exist.
> The **ledger** is authoritative for which strategy owns them.

It overwrites quantities from the broker's actual positions, consults sibling
book specs so a symbol another book also trades is never adopted from the account
net, and refuses to arm when attribution is genuinely ambiguous. If it refuses,
`place_targets` raises `NotArmed` rather than transmitting.

The subtlety that cost a debugging cycle: the account held 823 shares of HYG, of
which the null trader owned 541 and the benchmark books owned 282. Adopting the
account net of 823 would have sold 282 shares the strategy never bought.

This exists because of a real incident. On 2026-07-31 the ledger froze at its
funding row showing zero positions while the account actually held 35 positions
and $2.07M gross. The next session would have re-bought both books entirely.

## 4.4 Running it by hand

```bash
# dry run: compute and log targets, transmit nothing
python3 -m src.deploy.run_book --asof 2026-08-16 \
    --book ops/books/cef_discount_book.json --source yfinance --dry-run

# live paper session
python3 -m src.deploy.run_book --asof 2026-08-16 \
    --book ops/books/cef_discount_book.json --source yfinance
```

**Re-running an armed book is not idempotent.** Each run stacks another order set
at the broker and there is no dedupe. On the evening of 2026-07-31 four armed runs
stacked 79 unseen market-on-close orders, invisible because `openTrades()` only
returns the querying client's own orders, and `cancelOrder` failed across client
ids with error 10147. `reqGlobalCancel()` cleared them. Cancel pending orders
before re-running by hand.

## 4.5 Execution, the binding problem

Day one taught us more than any backtest. The strategy necessarily decides in the
evening, because its signal needs the NAV, which does not exist until after the
close. Plain market orders therefore rested overnight and filled at 07:27 ET, two
hours before the exchange opened, into pre-market where these $3M to $45M a day
funds have essentially no liquidity.

| | |
|---|---|
| Traded | $682,351 |
| Slippage cost | $6,405 |
| Realised | 0.94% |
| Modelled | ~0.10% |
| Ratio | **9.4x** |

Worst names: BIT 2.87%, DSL 2.62%, PFN 2.27%. Slippage was against us on every
buy *and* every sell, which is the signature of crossing a wide spread rather
than random noise. The three most liquid municipal funds filled at roughly 0.00%,
which fits, since they were the only ones with real pre-market depth.

Priced at the decision prices the book was up $50. Priced at the fills we got it
was down $7,350.

At 24 rebalances a year, 0.94% per rebalance is about 22.6% a year in costs
against a strategy earning 4.85% a year. Fatal several times over.

**We ruled out the obvious alternative explanation.** All 17 funds were reconciled
against the broker's own daily bars over 10 days: median disagreement 0.000%,
worst single day 0.00%. Our prices are exact. This is purely execution.

**The fix** is market-on-close orders. The decision still happens in the evening
when the NAV lands, but execution happens in the next closing auction, which is
the deepest and tightest liquidity of the day and the exact point the backtest
assumed. Routing was verified live at 16:39 ET, after the exchange cutoff and
after the close, the same conditions the 17:15 job hits. It returned
`PreSubmitted` with no error and cancelled cleanly.

**This is the single most important open question, ahead of returns.** If
slippage stays above 2x modelled after the market-on-close fix, that is not an
execution bug. It means these instruments are too expensive to trade at the only
frequency where the edge works, and the strategy is dead on costs. We know we
cannot slow down to escape the problem: net Sharpe by hold period runs 0.62 at
1 day, 0.73 at 2, 0.51 at 5, 0.30 at 10, 0.20 at 21.

---

# PART 5: AUTOMATION

## 5.1 What runs

Five scheduled jobs, all through macOS launchd:

| Job | When (ET) | What it does |
|---|---|---|
| `com.quantt.phase0.daily` | 09:35 Mon to Fri | null trader control experiment |
| `com.quantt.cef.daily` | 17:15 Mon to Fri | the CEF strategy, market-on-close for the next close |
| `com.quantt.collect.daily` | 18:30 Mon to Fri | forward-only data collection |
| `com.quantt.watchdog.daily` | 19:30 Mon to Fri | alerts on any job that did not run |
| `com.quantt.weekly` | Sat 09:00 | book roll-up report |

All five execute exactly one file:
`~/Library/Application Support/quantt/launch_job.py`.

## 5.2 The trap that makes this weird

**Nothing scheduled may go through the shell.** The repository lives under
`~/Desktop`, which macOS protects with TCC. A launchd agent has no Full Disk
Access, so `/bin/bash` cannot even read a script there. The 09:35 job on
2026-07-31 died with exit 126, transmitted nothing, and wrote no log at all.

The Anaconda interpreter holds Full Disk Access and the system shell does not.
So the entry point is a Python file living deliberately *outside* the protected
folder.

This fails invisibly, because a Terminal has Full Disk Access and hand-runs
always work. **Always test a scheduled job with `launchctl kickstart`, never with
a fresh load.** A freshly loaded agent inherits the loading Terminal's
permissions and will pass a test that the real scheduled run fails.

Consequence for reading the code: `ops/schedule/run_cef.sh` and its siblings are
**not** what runs daily. They are kept for manual use. Anyone reading them to
learn what happens each day is reading dead code.

## 5.3 A session has four phases

```
1. REFRESH    fetch today's prices and NAV      fail -> no trading, still logs
2. PREFLIGHT  decide whether trading is safe    fail -> no trading, still logs
3. TRADE      run the book, live or dry         fail -> halt and alert
4. CAPTURE    record real broker executions     ALWAYS, even after 1 to 3 fail
```

The split matters. Trading is dangerous when state is wrong and should fail
closed. Data collection is only lost if it does not happen, since the issuers
publish no archive, so a missed day is gone forever. The old design conflated
them, so any fault also cost us the day's data.

Phase 4 is unconditional because `ib.fills()` serves the current TWS session
only, and the daily restart destroys it. A capture that runs only after a
successful trade would lose exactly the fills worth having, which is what
happened to 302 executions on 2026-07-31.

## 5.4 What stops trading

`ops/preflight.py` runs before every session. Any blocker clears the arm while
leaving collection on, so a halted book still records, it just does not trade.

| Check | Blocks? | Catches |
|---|---|---|
| `halt` | yes | an active file in `ops/halts/` |
| `costs` | yes | any deployed ticker with no cost entry |
| `cost_drift` | warn | a static cost that no longer matches the model |
| `data` | yes | stale prices or NAV |
| `broker` | yes | TWS not listening |
| `margin` | yes | cushion under 0.10 |
| `heartbeat` | warn | the previous session never ran |

The cost check exists because of a specific failure. `config/costs.yaml` priced
12 tickers while the two deployed books traded 31. The ledger hard-fails on a
missing spread by design, so every ledger advance died on the first unknown name,
*after* orders had already transmitted. The broker layer caught the exception,
printed one line, and returned normally. The run logged "ok".

`DRY_RUN=1` in a job's env file is a human hard halt and always wins. `DRY_RUN=0`
does **not** mean "trade". It means "trade if preflight agrees".

## 5.5 Alerts

`ops/halt.py` pushes on three channels in increasing loudness: a durable file in
`ops/halts/` which preflight reads as a hard gate and which survives reboots, a
macOS banner and spoken alert if you are at the machine, and email if you are
not. Alerting is best-effort and individually wrapped, so an SMTP timeout can
never prevent a halt being recorded. The file write happens first and unguarded.

Clearing a halt is deliberately manual and attributed:

```bash
python3 -c "from ops.halt import clear_halt; clear_halt('what you fixed')"
```

**Email is not configured yet.** It needs a Google App Password, since Gmail
rejects a plain account password over SMTP. Add `ALERT_SMTP_USER` and
`ALERT_SMTP_PASS` to `config/.env`.

---

# PART 6: DATA AND EXTERNAL SOURCES

## 6.1 What we pull, and from where

| Source | What we get | Cost | How |
|---|---|---|---|
| **yfinance** | closed-end fund prices, NAVs, distributions | free | `scripts/cef/fetch_daily.py` |
| **iShares / BlackRock** | full daily holdings with a price for every bond | free | `scripts/holdings/ingest_holdings.py` |
| **State Street, VanEck** | same, other fund families | free | same |
| **SEC EDGAR (N-PORT)** | quarterly holdings history back to 2019 | free | `scripts/nport/` |
| **FINRA** | daily short volume and short interest | free | `scripts/positioning/` |
| **ICI** | weekly fund flows | free | `scripts/fetch/fetch_ici_flows.py` |
| **US Treasury** | auction calendar back to 1990 | free | `scripts/fetch/build_calendar.py` |
| **IBKR** | historical bid-ask spreads for cost measurement | entitlement | `scripts/rv/fetch_ibkr_spreads.py` |
| **Cloudflare R2** | our WRDS mirror | our bucket | `src/data/r2.py` |

## 6.2 The free bond price feed

This was the most valuable discovery of the summer and it is worth understanding.

A fund holding a thousand bonds publishes, every single day, a complete list:
every bond, and **the price of every bond**. For free, no subscription, no delay.
We had been reading those files to find out what a fund owned. We had never read
them as a source of bond prices.

Take the union across fifteen funds and you get a daily price for 11,423
individual bonds. Our best licensed bond dataset at the time was 238 days out of
date.

Two warnings, both learned the hard way:

- **The obvious download link returns a web page, not data.** The working path is
  `latest-holdings.csv`, not the `.ajax` link the page itself advertises.
- **Verify fund ids by the published fund name.** Two of ours were wrong. We were
  fetching what we believed was a fallen-angel bond fund and it was actually the
  iShares Low Carbon Optimized MSCI ACWI ETF, a stock fund. We only caught it
  because we print the full column set on the first pull and the stock fund had
  no bond columns. The ingester now refuses a fund whose published name does not
  match. That check is load-bearing.

**There is no historical archive.** The issuers publish today and nothing else,
and passing a date is silently ignored. This means bond-level backtests are not
possible until roughly mid-2027, and it is why the collection job must never be
skipped.

## 6.3 The cost model

`config/costs.yaml` is the single source of trading cost assumptions. It prices
45 tickers in four blocks: original tick-floor ETFs, Treasury futures, 11 ETFs
with IBKR-measured spreads, and 17 closed-end funds with model-derived spreads.

A cost audit in July found the headline number had been wrong for the whole
project. The formula was accurate, checked against real measured bid-ask spreads
to within 1 to 2% on seven of eight funds. The *sample* was the problem:

| Era | Cost per trade | Cost per year |
|---|---|---|
| 2007 to 2010 | 13.91 bp | 42.5% |
| 2015 to 2018 | 4.49 bp | 15.3% |
| **2023 to 2026** | **1.73 bp** | **5.9%** |

The old 21.2% headline was a full-sample average dominated by 2007 to 2014, when
these funds were young and thin. Today the same trading costs 3.7 times less. We
had been charging 2007-era costs to modern strategies, which manufactured a fake
obstacle in front of every signal we tested.

Fixing it rescued nothing, because our failures were absence of edge rather than
excessive cost. Worth knowing, worth doing, and it changed no verdict.

---

# PART 7: KNOWN PROBLEMS

These are open. Anyone can pick one up.

## 7.1 The system has not traded since 2026-08-01

TWS has not been running. Every session since then ends `ok_not_armed` with the
blocker "nothing listening on 127.0.0.1:7497". Collection, reporting, and the
watchdog have all continued cleanly, which is the four-phase design working as
intended, but no orders have transmitted since 2026-07-31.

Restarting TWS is a manual login. Automating around a daily human login is the
first infrastructure problem to solve this year.

## 7.2 The books are over-committed

CEF at $500,000 plus phase 0 at $640,000 is $1.14M claimed against about $722,000
USD of equity, which is 158%, at a margin cushion of 0.166 and 2.09x gross to net
liquidation. The margin check blocks new exposure below 0.10, but that is a
backstop, not a fix. Resizing is a decision somebody needs to make, not a bug.

## 7.3 Two dead scheduled jobs

`com.quantt.book.daily` and `com.quantt.book.weekly` still point at
`/bin/bash` wrappers, so TCC blocks them. They also reference
`ops/books/v2/book_v2_ff.json`, which does not exist in this tree. They are
broken twice over and should be removed.

## 7.4 Smaller items

- `data/README.md` is stale. It still says two parquet files are not yet built
  when both exist.
- `boto3` is not installed on the live machine, so `src/data/r2.py` would fail
  today.
- `src/analysis/` is empty.
- Distribution cut defence is unbuilt. See 2.5.
- No group exposure limit exists in the frozen spec.

---

# PART 8: WHERE TO FIND THINGS

## 8.1 Key documents

| Document | What it is |
|---|---|
| `HOW_WE_GOT_HERE.md` | the story of the summer, including every wrong turn |
| `RESEARCH_AND_METHODOLOGY.md` | how we decide something is real |
| `RESEARCH_STATE.md` | living state: deployed, killed, queued |
| `results/AUDIT_2026-07-31.md` | end-to-end audit, the most useful single file |
| `results/ACADEMIC_REPORT_2026-07-31.md` | formal write-up |
| `ops/AUTOMATION.md` | the daily automation runbook |
| `CREDIT_RV_PREREG.md`, `E1_PREREG.md` | pre-registrations for two killed strategies |
| `results/cef/HOLDOUT_PREREG.md` | the sealed holdout rules, written before it was opened |

## 8.2 Key scripts

| Script | What it does |
|---|---|
| `scripts/cef/fetch_daily.py` | daily price and NAV refresh, append-only, idempotent |
| `scripts/cef/validate.py` | the four-test validation battery |
| `scripts/cef/open_holdout.py` | one-shot sealed holdout opener |
| `scripts/cef/reconcile_prices.py` | do our prices agree with the broker's |
| `scripts/audit/live_pnl_attribution.py` | live P&L by strategy, reconciled to IBKR |
| `scripts/audit/cef_factor_audit.py` | factor exposures and control regressions |
| `scripts/audit/moc_routing_test.py` | places one share, cancels, proves routing works |
| `scripts/holdings/ingest_holdings.py` | the daily bond price collector |
| `scripts/bench/run_benchmarks.py` | nine benchmark books through one accounting path |
| `ops/preflight.py` | the seven safety checks |
| `ops/capture_fills.py` | pull real executions from the broker |
| `ops/rebuild_ledger.py` | rebuild a ledger from broker truth |

## 8.3 Citations and background reading

The ideas here are not original and the literature is worth reading.

**On closed-end fund discounts.** Lee, Shleifer and Thaler (1991), "Investor
Sentiment and the Closed-End Fund Puzzle", *Journal of Finance* 46(1). The
canonical reference for why these gaps exist and persist. Pontiff (1996),
"Costly Arbitrage: Evidence from Closed-End Funds", *Quarterly Journal of
Economics* 111(4), on why the gaps do not get arbitraged away.

**On forced selling and price pressure.** Ellul, Jotikasthira and Lundblad
(2011), "Regulatory Pressure and Fire Sales in the Corporate Bond Market",
*Journal of Financial Economics* 101(3). This is the mechanism behind the
fallen-angel work in `results/s3/`.

**On stale prices and smoothed returns.** Getmansky, Lo and Makarov (2004), "An
Econometric Model of Serial Correlation and Illiquidity in Hedge Fund Returns",
*Journal of Financial Economics* 74(3). The unsmoothing method sitting at rank 4
in our research queue.

**On overfitting and the multiple testing problem.** Bailey and López de Prado
(2014), "The Deflated Sharpe Ratio", *Journal of Portfolio Management* 40(5). This
is where our deflated Sharpe calculation comes from. Harvey, Liu and Zhu (2016),
"...and the Cross-Section of Expected Returns", *Review of Financial Studies*
29(1), on why a t-statistic of 2 is not enough when you have tested many ideas.

**On market impact.** Almgren et al. (2005), "Direct Estimation of Equity Market
Impact", *Risk*. The square-root law our impact model uses.

---

# PART 9: MAINTAINING THIS DOCUMENT

Sections are numbered so they can be referenced in messages and pull requests.
When you change the system:

1. Edit the section that owns the change.
2. Add a changelog row at the top.
3. If you added a new external data source, add it to the table in 6.1.
4. If you added a new script anyone else will run, add it to 8.2.
5. If you fixed something in Part 7, delete it from Part 7 rather than marking it
   done. The list should always be the live set of problems.

If a section grows past roughly two screens, split it into its own file under
`docs/` and leave a pointer here.
