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
  run_book.py        (archived 2026-09-28 with IBKR)
  exec_ledger.py     sub-ledgers strategies trade through
  fills.py           fill price model: half spread, market impact
  risk.py            per-strategy kill and halve switches, book limits
  report.py          daily reports
  sleeves/           cef_discount, null_trader, credit_rv, static_weights
  broker/            base interface and simulator (ibkr.py archived 2026-09-28)
  lib/               v2 namespace, additive, does not modify v1
src/backtest/        daily engine, lookahead guard, walk-forward
src/strategies/      credit relative value research code
src/data/            Cloudflare R2 access for the WRDS mirror
ops/                 halts, ledgers, orient, doc_audit, netguard (IBKR tools archived 2026-09-28)
quantt/              the Alpaca run package (2026-09-28 onward)
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

**Retired 2026-09-28 with IBKR.** This section described IBKR TWS/Gateway, the
paper account, books and shadow ledgers, the `arm()` gate, manual operation and
execution through `IBKRBroker`. None of it runs. The text is in the archived
snapshot `_archive/docs/INFRASTRUCTURE_2026-09-28.md` §5; what replaces it is
`docs/SYSTEM.md` §4 and `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md`.

## 6. Automation

**Retired 2026-09-28 with IBKR.** Prod/dev worktrees, launchd jobs, IBKR client
ids, the TCC constraint, session structure, preflight checks and alerting — all
for the IBKR run on this Mac. The archived snapshot
`_archive/docs/INFRASTRUCTURE_2026-09-28.md` §6 holds the text. The Alpaca system
will run on a cloud VM (`docs/SYSTEM.md` §4).

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

**Removed 2026-09-14.** Every item listed here on 2026-08-16 had been resolved or overtaken (no trading since 1 August; dead `book.*` jobs; an empty `src/analysis/`). Open work: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` §5–§6 (the work orders were archived 2026-09-28). The old list is in the archived snapshot `_archive/docs/INFRASTRUCTURE_2026-09-14.md` §8.

## 9. Reference

**Moved.** Documents: `docs/INDEX.md`. Commands: `docs/SYSTEM.md` §0. Literature: `docs/REFERENCES.md`. The earlier tables are in the archived snapshot `_archive/docs/INFRASTRUCTURE_2026-09-14.md` §9.
