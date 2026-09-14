# Infrastructure and onboarding — reference

> **⚠ CORRECTED 2026-09-14 — REFERENCE MATERIAL, NOT THE SYSTEM DESCRIPTION.**
> What the book is and how it runs is `docs/SYSTEM.md`; any number is
> `python3 -m ops.orient`; the authority on a live parameter is
> `ops/specs/cef_discount.frozen.json` (the live spec was
> `cef_discount.v6.20260906` when this was written — orient SPEC is the check).
> Parts 1, 3, 8, 9 and sections 6.0, 6.1, 6.3 and 6.5 moved to `docs/SYSTEM.md`
> and are stubs here, numbered so existing citations still land. Parts 2, 4, 5,
> 7 and sections 6.2, 6.2b and 6.4 were first written 2026-08-16 and patched
> since: read them as reference, and verify anything that looks like a current
> state. The full pre-trim text is the archived snapshot
> `_archive/docs/INFRASTRUCTURE_2026-09-14.md`.

## 1. Overview

**Moved to `docs/SYSTEM.md` §1 and §4.** The earlier overview ("targets 6% annualised volatility", "five scheduled jobs") is in the archived snapshot `_archive/docs/INFRASTRUCTURE_2026-09-14.md`.

## 2. Onboarding

### 2.1 Environment

Python 3.11 or later. The trading machine runs 3.13.5 under Anaconda.

```
git clone https://github.com/quanttqueensu/CreditTrading.git
cd CreditTrading
python3 -m pip install -r requirements.txt
```

The `data` directory is 3.8 GB and is excluded from the repository. Section 2.3
covers reconstruction. Broker access is needed only for trading and is limited to
two or three members.

### 2.2 Required reading

| Order | Document | Content |
|---|---|---|
| 1 | `CLAUDE.md` | The hard rules: order path, code, data, research. |
| 2 | `docs/SYSTEM.md` | What we trade, how it runs, what we know, standing decisions. |
| 3 | `docs/RESEARCH_STATE.md` | The research ledger: trial counters, D1–D7 legend, what is dead and why. |
| 4 | `docs/INDEX.md` | Which document owns which question. |

Run `python3 -m ops.orient` before reading any of them.

### 2.3 Reconstructing the data directory

Most sources are free and can be refetched in this order:

```
python3 scripts/cef/stage_cef.py              # closed-end fund prices and NAVs
python3 scripts/fetch/refresh_market_feeds.py # VIX complex, Treasury futures
python3 scripts/fetch/fetch_live_sources.py   # daily free sources
python3 scripts/holdings/ingest_holdings.py   # ETF holdings, ~11k bonds
python3 scripts/holdings/fetch_nav_multi.py   # issuer-published NAVs
```

Two datasets cannot be reconstructed and must be copied from the team lead. The
first is the daily ETF holdings history: issuers publish only the current day and
silently ignore any date parameter, so our record begins 29 July 2026 and extends
forward one day at a time. Missed days are unrecoverable, which is why collection
runs as a job separate from trading. The second is the TRACE bond data and
forced-flow panels, 3.3 GB in `data/forced_flow2`, which came from a licensed
source.

### 2.4 Verification

New members run the validation battery before anything else:

```
python3 scripts/cef/validate.py --trials <CEF counter from docs/RESEARCH_STATE.md>
```

`--trials` is required and has no default. **Read the numbers it prints; do not
compare them with a number written in a document.** It scores the retired
calendar policy at `shift(2)`; what that battery established is
`results/cef/EXECUTION_CONVENTION_2026-09-10.md`. Any surprise is a finding to
report, not a local error to assume.

### 2.5 Working standards

A false positive is the worst outcome of a research session, worse than a null
result. Promising results are attacked before they are reported.

Each session adds a new data source rather than a new parameter to an existing
model. Repeated search over the same data yields diminishing returns and raises
the statistical threshold for all subsequent work.

Every test is counted. `RESEARCH_STATE.md` holds a running total that never
resets. At 10 trials the best pure-noise result scores approximately 2.1; at 162
trials, approximately 3.2. Results are assessed against the running total.

Every failure is classified into one of the seven D1–D7 categories in
`docs/RESEARCH_STATE.md`. "It did not work" is not an acceptable entry.

Shutdown rules are written before deployment, not after.

## 3. Strategy

**Moved to `docs/SYSTEM.md` §1–§2** (mechanism, implementation, evidence, live configuration; §3.4's table described the retired 2-day calendar). The kill rule and declared weaknesses of 2026-08-16 are in the archived snapshot `_archive/docs/INFRASTRUCTURE_2026-09-14.md` §3.5–§3.6; the live kill-rule keys are in the frozen spec.

## 4. Code

### 4.1 Layout

```
src/deploy/          live trading framework
  sleeve.py          the contract every strategy implements
  registry.py        strategy type to class mapping, spec validation
  portfolio.py       consolidates sub-ledgers into a book view
  run_book.py        session entry point
  exec_ledger.py     sub-ledgers strategies trade through
  fills.py           fill price model: half spread, market impact
  risk.py            per-strategy kill and halve switches, book limits
  report.py          daily reports
  sleeves/           cef_discount, null_trader, credit_rv, static_weights
  broker/            base interface, ibkr.py, simulator.py
  lib/               v2 namespace, additive, does not modify v1
src/backtest/        daily engine, lookahead guard, walk-forward
src/strategies/      credit relative value research code
src/data/            Cloudflare R2 access for the WRDS mirror
ops/                 preflight, halts, ledgers, monitoring, reports
scripts/             research and data scripts by family
config/              cost models and credentials
results/             outputs, one directory per research family
docs/                this document, project intro, summer summary
data/                3.8 GB, excluded from git
```

### 4.2 Strategy contract

Every strategy implements four methods defined in `src/deploy/sleeve.py`:
`instruments()`, `history_warmup_trading_days()`, `target_positions()`, and
`risk_check()`, which returns OK, HALVE or KILL. A strategy is registered by
decorator with an `alloc_type` name, after which the registry validates any spec
claiming that type. We added this after shipping two defects in which a spec type
was accepted and validated with no implementing class behind it, failing only at
run time.

### 4.3 The deployed strategy

`src/deploy/sleeves/cef_discount.py`, 239 lines. It computes the discount as
`100 * (price - nav) / nav`, z-scores it against a rolling 252-day window shifted
by one day, and clips at ±4. It then applies the rebalance gate, anchored to the
trading-day index so the schedule does not drift, drops names failing the ADV,
NAV age and minimum weight filters, neutralises the book, and scales to the
volatility target using 63-day trailing realised volatility with the scalar
clipped to [0.2, 2.5].

The minimum weight filter runs before neutralisation. It previously ran after,
leaving the book 0.37% net short, which is precisely the exposure the strategy
exists to avoid. Residual is now 1e-6.

## 5. Live trading system

### 5.1 Broker interface

Interactive Brokers TWS, paper account DUQ199038, at 127.0.0.1:4002.

The account is denominated in Canadian dollars, so all US dollar sizing converts.
Net liquidation of 1,000,674 CAD was 714,059 USD at the 31 July rate.

We hold no real-time data subscription; quotes arrive 15 minutes delayed. Cost
estimates therefore come from historical measurement rather than live quotes.
Historical bid-ask data is available under a separate entitlement and is how we
measure execution cost.

We use `ib_async`, not `ib_insync`. The latter is unmaintained and hangs
indefinitely in its asyncio handshake on Python 3.12 and above; TWS answers a raw
socket normally while the library never returns, which presents identically to a
dead gateway. `src/deploy/broker/ibkr.py` imports `ib_async` first and falls back
only if absent.

TWS restarts daily and requires an interactive login, which is currently our
largest operational weakness.

`orderRef` does not survive the round trip on this TWS build; every execution
returns an empty ref. Fill attribution is therefore by ticker, which is safe only
while no two deployed strategies trade the same symbol.
`ops/capture_fills.py` refuses to run if that condition is violated.

Credentials live in `config/.env`, excluded from git:

```
R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ENDPOINT / R2_BUCKET
IBKR_HOST=127.0.0.1 / IBKR_PORT=4002 / IBKR_CLIENT_ID=17
```

Each scheduled job overrides the client id to prevent collisions. The CEF job
uses 45; audit scripts use 93 and 95.

### 5.2 Books and ledgers

| Book | Strategies | Capital | Status |
|---|---|---|---|
| cef_discount_paper | cef_discount | $500,000 | Live |
| phase0_null | null_trader | $640,000 | Live control experiment |
| benchmarks_paper | five static weight books | $20,000 each | Live reference |
| credit_rv_paper_v1 | credit_rv | $1,000,000 | Killed, retained for reference |

Each live book maintains a shadow ledger: `nav.csv` (daily value, cash, cost,
turnover, return), `positions.csv`, `orders.csv`, `trades.csv` (modelled fills
with cost breakdown), `broker_fills.csv` (real executions with exec id and
commission), `slippage.csv` (realised against modelled), and `manifest.json`
(row counts and last dates, verified on load).

The shadow ledger books modelled fills by design and remains the P&L source; real
executions are held separately. The exception is the null trader, rebuilt from
real fills because measuring real execution is its purpose.

### 5.3 The arm() gate

This is the primary safety control. It runs after strategy registration and
before any order, and divides authority: the broker is authoritative for how many
shares exist, the ledger for which strategy owns them.

It adopts quantities from the broker's actual positions, consults sibling book
specs so a symbol another book also trades is never taken from the account net,
and refuses to arm where attribution is ambiguous, in which case `place_targets`
raises `NotArmed` rather than transmitting.

The non-obvious case: the account held 823 shares of HYG, of which the null
trader owned 541 and the benchmark books 282. Adopting the account net would have
sold 282 shares the strategy never bought.

This control exists because on 31 July the ledger froze at its funding row
showing zero positions while the account held 35 positions worth $2.07M gross.
The following session would have re-bought both books in full.

### 5.4 Manual operation

```
# dry run: compute targets, log, transmit nothing
python3 -m src.deploy.run_book --asof YYYY-MM-DD \
    --book ops/books/cef_discount_book.json --source yfinance --dry-run

# live paper session
python3 -m src.deploy.run_book --asof YYYY-MM-DD \
    --book ops/books/cef_discount_book.json --source yfinance
```

Re-running an armed book is not idempotent; each run stacks an additional order
set with no deduplication. On the evening of 31 July four armed runs stacked 79
unseen market-on-close orders, invisible because `openTrades()` returns only the
querying client's orders, and `cancelOrder` failed across client ids with error
10147. `reqGlobalCancel()` cleared them. Pending orders must be cancelled before
any manual re-run.

### 5.5 Execution

The strategy decides in the evening because its signal requires the NAV, which
publishes after the close. On the first live day plain market orders rested
overnight and filled at 07:27 ET, two hours before the exchange opened, in funds
trading $3M to $45M per day with negligible pre-market depth.

| Traded | Slippage | Realised | Modelled | Ratio |
|---|---|---|---|---|
| $682,351 | $6,405 | 0.94% | ~0.10% | 9.4× |

Worst names were BIT at 2.87%, DSL at 2.62% and PFN at 2.27%. Slippage ran
against us on every buy and every sell, the signature of crossing a wide spread
rather than noise. The three most liquid municipal funds filled at approximately
0.00%, consistent with their being the only names with real pre-market depth.

Priced at decision prices the book was up $50; priced at fills it was down
$7,350. At 24 rebalances per year, 0.94% per rebalance is 22.6% annually against
a strategy earning 4.85%.

We excluded the alternative explanation by reconciling all 17 funds against the
broker's daily bars over 10 days: median disagreement 0.000%. Our prices are
exact, so this is purely execution.

The remedy is market-on-close orders, which execute in the closing auction, the
deepest and tightest liquidity of the day and the point the backtest assumed.
Routing was verified live at 16:39 ET, after the exchange cutoff and after the
close, matching the conditions the 17:15 job encounters; it returned
`PreSubmitted` with no error and cancelled cleanly.

Whether this remedy is sufficient is the most important open question in the
project, ahead of returns. We cannot slow the strategy to escape the cost: net
Sharpe by holding period runs 0.62 at one day, 0.73 at two, 0.51 at five, 0.30 at
ten and 0.20 at twenty-one. If slippage remains above twice modelled, these
instruments are too expensive to trade at the only frequency at which the edge
exists.

## 6. Automation

### 6.0 Prod and dev (2026-09-10)

**Moved to `docs/SYSTEM.md` §4.1.**

### 6.1 Scheduled jobs

**Moved to `docs/SYSTEM.md` §4.2.** The table that stood here was the evening schedule, replaced by the W3 morning schedule on 2026-09-13; what is loaded is `launchctl list | grep quantt`.

### 6.2 IBKR API client ids

IB allows **one session per client id**. A second connect on an id already in
use silently evicts the first, which then reports a dead broker — so every
caller needs its own, and a collision is a real fault, not a tidiness issue.

| caller | client id | where it comes from |
|---|---|---|
| cef session | 45 | `ops/schedule/cef.env` |
| benchmarks session | 46 | `ops/schedule/benchmarks.env` |
| phase0 session | *inherited* | **no `IBKR_CLIENT_ID` in `phase0.env`** — falls back to the shared broker config, so it uses whatever that holds |
| `capture_fills` | session id + 50 | `ops/capture_fills.py` |
| `preflight` | session id + 60 | `ops/preflight.py` |
| `reconcile_orders` | session id + 70 | `ops/reconcile_orders.py` |
| `fetch_borrow_rates` | 77 | `IB_CLIENT_ID` |
| `fetch_borrow_history` | 78 | `IB_CLIENT_ID` |
| `rebuild_ledger` | 110 | hardcoded |
| epoch reset tool | 120 | hardcoded (**was 96 until 2026-09-10 — that is `capture_fills` for the benchmarks book, 46 + 50**) |
| `switch_broker` probe | 199 | `PROBE_CLIENT_ID` |
| dashboard `_probe_broker` | 205 | hardcoded |
| dashboard `_portfolio` | 302 | hardcoded |

Two faults found on 2026-09-10 and fixed:

1. **The dashboard opened a session per widget refresh.** `/api/live` polls
   every 5s against what was a 4s cache TTL, and `/api/verify` called the same
   `_portfolio` under a *second* cache key — so two threads could hold client
   302 at once and evict each other. Roughly 17,000 connect/disconnect cycles a
   day, seven sockets still held `CLOSED` by the process after 38 hours, and
   the gateway answering **10197 "No market data during competing live
   session"** to the borrow-availability tick. Fixed by making `cached()`
   single-flight (one lock per key), sharing one portfolio snapshot between
   both endpoints, serialising `_portfolio` on a process-wide broker lock, and
   raising the TTL to 12s. The durable fix — one long-lived session owned by
   the server, subscribing to events instead of polling — is `W9`.
2. **The epoch reset tool defaulted to 96**, the benchmarks book's
   `capture_fills` id, and it runs during exactly the recovery window where
   capture is most likely to be running too. Moved to 120.

**`phase0.env` still has no id of its own.** Give it one before the null trader
is retired, or the retirement session will contend with whatever else reads the
shared broker config.

### 6.2b The TCC constraint

No scheduled job may run through the shell. The repository sits under `~/Desktop`,
which macOS protects with TCC. A launchd agent holds no Full Disk Access, so
`/bin/bash` cannot read a script located there. The 09:35 job on 31 July exited
126, transmitted nothing, and wrote no log.

The Anaconda interpreter holds Full Disk Access; the system shell does not. The
entry point is therefore a Python file located outside the protected directory.

This failure mode is invisible under manual testing, because a Terminal holds Full
Disk Access. Scheduled jobs must be tested with `launchctl kickstart`, never by
loading fresh: a freshly loaded agent inherits the loading Terminal's permissions
and passes a test the real scheduled run fails.

Consequently `ops/schedule/run_cef.sh` and its siblings are not what runs daily.
They are retained for manual use only.

### 6.3 Session structure

**Moved to `docs/SYSTEM.md` §4.2** (the four-phase session contract, whose canonical text is the `launch_job.py` docstring).

### 6.4 Preflight checks

`ops/preflight.py` runs before every session. Any blocker clears the arm while
leaving collection enabled, so a halted book still records.

| Check | Blocks | Catches |
|---|---|---|
| halt | Yes | Active file in `ops/halts` |
| costs | Yes | Deployed ticker with no cost entry |
| cost_drift | Warn | Static cost diverging from the model |
| data | Yes | Stale prices or NAV |
| broker | Yes | TWS not listening |
| margin | Yes | Cushion below 0.10 |
| heartbeat | Warn | Previous session did not run |

The cost check exists because `config/costs.yaml` priced 12 tickers while the two
live books traded 31. The ledger hard-fails on a missing spread by design, so
every ledger update died on the first unknown name, after orders had transmitted.
The broker layer caught the exception, printed one line, returned normally, and
the run logged "ok".

`DRY_RUN=1` is a human hard halt and always wins. `DRY_RUN=0` means trade if
preflight agrees, not trade unconditionally.

### 6.5 Alerting

**Moved to `docs/SYSTEM.md` §4.4 (halts) and §4.6 (alerting and verification).**

## 7. Data and external sources

### 7.1 Sources

| Source | Content | Cost | Script |
|---|---|---|---|
| yfinance | CEF prices, NAVs, distributions | Free | `scripts/cef/fetch_daily.py` |
| iShares / BlackRock | Daily holdings with per-bond prices | Free | `scripts/holdings/ingest_holdings.py` |
| State Street, VanEck | Same, other fund families | Free | Same |
| SEC EDGAR (N-PORT) | Quarterly holdings from 2019 | Free | `scripts/nport/` |
| FINRA | Daily short volume and short interest | Free | `scripts/positioning/` |
| ICI | Weekly fund flows | Free | `scripts/fetch/fetch_ici_flows.py` |
| US Treasury | Auction calendar from 1990 | Free | `scripts/fetch/build_calendar.py` |
| IBKR | Historical bid-ask spreads | Entitlement | `scripts/rv/fetch_ibkr_spreads.py` |
| Cloudflare R2 | Our WRDS mirror | Our bucket | `src/data/r2.py` |

### 7.2 The bond price panel

Funds publish a complete daily holdings list including a price for every bond,
free and without delay. We had been reading these files to determine holdings and
had not recognised them as a bond price source. The union across fifteen funds
gives daily prices for 11,423 individual bonds; our best licensed bond dataset at
the time was 238 days stale.

Two operational notes. The advertised download link returns a web page rather
than data; the working path is `latest-holdings.csv`, not the `.ajax` link the
page itself provides. And fund ids must be validated against the published fund
name, because two of ours were wrong: we were fetching what we believed was a
fallen-angel bond fund and it was the iShares Low Carbon Optimized MSCI ACWI ETF,
an equity fund. We caught it only because we print the full column set on first
pull and the equity fund had no bond columns. The ingester now rejects any fund
whose published name does not match expectation.

No archive exists. Issuers publish the current day only and ignore date
parameters, so bond-level backtests are not possible until approximately mid
2027. This is why the collection job must not be skipped.

### 7.3 Cost model

`config/costs.yaml` holds all trading cost assumptions and prices 45 tickers
across four provenance blocks: original tick-floor ETFs, Treasury futures, 11
ETFs with IBKR-measured spreads, and 17 closed-end funds with model-derived
spreads.

A July audit found the headline figure had been wrong for the duration of the
project. The formula was accurate, matching real measured spreads to within 1 to
2% on seven of eight funds. The sample was the defect.

| Era | Cost per trade | Cost p.a. |
|---|---|---|
| 2007–2010 | 13.91 bp | 42.5% |
| 2015–2018 | 4.49 bp | 15.3% |
| 2023–2026 | 1.73 bp | 5.9% |

The 21.2% figure was a full-sample average dominated by 2007 to 2014, when these
funds were young and thin. Equivalent trading today costs 3.7 times less. We had
been charging 2007 costs to modern strategies, imposing a false obstacle on every
signal tested. Correcting it rescued nothing, since our failures were absence of
edge rather than excessive cost, and it changed no verdict.

## 8. Open issues

**Removed 2026-09-14.** Every item listed here on 2026-08-16 had been resolved or overtaken (no trading since 1 August; dead `book.*` jobs; an empty `src/analysis/`). Open work lives in `docs/prompts/README.md`. The old list is in the archived snapshot `_archive/docs/INFRASTRUCTURE_2026-09-14.md` §8.

## 9. Reference

**Moved.** Documents: `docs/INDEX.md`. Commands: `docs/SYSTEM.md` §0. Literature: `docs/REFERENCES.md`. The earlier tables are in the archived snapshot `_archive/docs/INFRASTRUCTURE_2026-09-14.md` §9.
