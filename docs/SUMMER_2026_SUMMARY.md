---
title: "Summer 2026: Progress and Results"
subtitle: |
  **QUANTT Credit Trading**\
  Period 19 July to 16 August 2026 · issued 16 August 2026\
  github.com/quanttqueensu/CreditTrading
---

## 1. Summary

We set out to build a credit strategy that performs independently of market
direction. We tested thirteen mechanisms. Twelve failed. The survivor is deployed
on a $500,000 Interactive Brokers paper account and places its own orders on a
schedule.

We also built a free daily feed of 11,423 bond prices, established that our own
cost model had overcharged every strategy by a factor of 3.7, identified sixteen
defects in our own work, and established on the first live trading day that
execution cost is a larger constraint than signal quality.

The ratio of thirteen tested to one deployed is the most representative figure
for the summer.

## 2. What we built

### 2.1 The strategy

Credit closed-end fund discount reversion. A closed-end fund trades on an
exchange with a permanently fixed share count, so no mechanism pulls its price
back to the value of its holdings. Credit closed-end funds trade at a mean
discount of 3.16% with a standard deviation of 5.95%, approximately 150 times the
equivalent ETF gap.

The strategy z-scores each fund's discount against its own 252-day history, holds
the cheapest long and the richest short in equal dollar amounts, and targets 6%
annualised volatility.

### 2.2 Infrastructure

We built a backtest engine with a lookahead guard and purged walk-forward
testing; a deployment framework in which every strategy implements the same four
methods; and 1,077 lines of Interactive Brokers integration including a gate that
reconciles our records against the broker's before any order transmits. Each
strategy maintains a ledger recording positions, orders, modelled trades, real
fills and slippage. Five scheduled jobs run the book unattended on weekdays,
behind seven preflight checks, against a cost model covering 45 tickers
calibrated to measured bid-ask spreads.

### 2.3 Data

| Dataset | Size | Note |
|---|---|---|
| Daily bond price panel | 11,423 bonds/day | Free, from fund holdings files. No archive exists, so it accumulates forward only |
| SEC N-PORT holdings | 136,268 rows from 2019 | 95.3% CUSIP overlap against a live holdings file |
| CEF prices and NAVs | 265,615 and 232,799 rows from 1986 | 44 funds |
| Fallen-angel events | 16,388 migrations, 2003–2025 | With index removal dates |
| FINRA short volume | 26,116 rows | Daily, free |
| Tradable universe | 10 to 56 instruments | |

## 3. Results

### 3.1 The thirteen mechanisms

| Mechanism | Verdict | Cause |
|---|---|---|
| credit_rv | Killed | Sealed holdout Sharpe −1.44; edge negative before costs |
| E1, HYG vs JNK | Killed | Negative out of sample; opportunity fell from 188bp to 3.8bp |
| S1, cross-issuer disagreement | Killed | Input carries no information: median disagreement 0.09bp, as all issuers price from one vendor |
| S3, fallen angels via ETFs | Killed | A credit-quality premium in disguise. Unconditional holding scored 0.37; signal-conditioned scored 0.03 to 0.24 |
| Single-fund premium/discount | Killed | Predicts the NAV converging, not the price. Trading it opposes price discovery |
| leadlag | Killed | Measured at a non-transactable price. At tradable prices t fell from 5.20 to −0.50, and the control group scored higher |
| nport-trace-nav | Infeasible | Only 17 to 30% of holdings trade daily, and those are selected for news |
| dealer-constraint | Killed | No credit name significant at any horizon; Treasury control showed equal magnitude |
| pair-reversion | Killed on arithmetic | Gross Sharpe +1.03, but costs do not diversify while volatility does, giving net −0.16. Volatility target required 32.8× leverage against a 2× limit |
| short-pressure | Killed | Rates control group scored higher than credit |
| raw-flow-z | Killed | Precise zero across 28,025 observations, all t below 0.8 |
| Distribution events | Killed | Cuts move the discount against the thesis and show no dose-response |
| **CEF discount reversion** | **Deployed** | Passed the full battery below |

Two mechanisms remain on watch rather than killed. Forced-flow price pressure is
real and large, at −424bp with t = −17.5 and 82 to 85% reversal, but the only
available expression dilutes the signal fivefold. The premium/discount band form
retained its edge per opportunity; only the opportunity count collapsed.

### 3.2 Validation of the deployed strategy

| Test | Result | Verdict |
|---|---|---|
| Point-in-time universe, no survivorship or liquidity hindsight | Gross 1.26, net 0.82, volatility 6.00%, max drawdown −12.0% | Pass, and better than the biased construction |
| Purged walk-forward, 10 blocks, 5-day embargo | 9 of 9 positive, median 1.12, worst 0.01 | Pass |
| Block bootstrap, 5,000 draws | 5th/95th percentile 0.52/1.11, P(SR ≤ 0) = 0.000% | Pass |
| Deflated Sharpe, adjusted for 10 specifications | 0.956 | Pass |
| Factor exposure | Alpha t 3.11, R² 0.005, 5 of 5 factor limits | Pass |

An R² of 0.005 means 99.5% of the return is unexplained by high yield, investment
grade, rates, equity or volatility.

### 3.3 Two attempts to invalidate the result

The live book is 66% net short municipal funds and 57% net long taxable funds, so
the natural hypothesis was a disguised sector position, which is what one earlier
candidate proved to be.

| Control set | Alpha p.a. | t | R² |
|---|---|---|---|
| Base factor set | +8.21% | +5.67 | 0.0037 |
| Plus municipal ETFs | +8.88% | +5.69 | 0.0117 |
| Plus municipal ETFs and duration spread | +8.83% | +5.67 | 0.0125 |
| All five CEF group factors | +7.63% | +5.90 | 0.0057 |

The final row is decisive, since municipal CEF discounts do not track municipal
ETFs. Under it every group beta is at or below 0.025 and the alpha is unchanged.

### 3.4 Three defects in the deployed configuration

An end-to-end audit on 31 July identified three problems. They alter the expected
result and are therefore reported here.

The specification, the code and the optimum disagreed on rebalance frequency. The
spec declared five days, only an unrelated file read that key, so the live code
traded every session, and the measured optimum was two days. Net Sharpe runs 0.62
at one day, 0.73 at two, 0.51 at five and 0.20 at twenty-one. We changed it to
two.

The backtest assumed an unobtainable entry price, entering at day *t*'s close
using day *t*'s NAV, which publishes after that close. A market-on-close order
fills at *t+1*'s close. The correction costs 38% of the Sharpe, taking 0.82 to
0.51.

No sealed holdout was taken for this strategy. The killed credit_rv strategy
received 141 trials and a sealed holdout before being terminated; this one
received ten specifications and $500,000 within two hours. That was a governance
failure, and it occurred on the only strategy that received capital.

The honest expected net Sharpe of the deployed configuration is therefore 0.51,
not 0.82. Correcting the holding period raises it to approximately 0.73.

### 3.5 The holdout we opened and failed

On 31 July we opened a sealed holdout on a proposed change, a 63-day z-window in
place of 252, against a pass mark of +0.40 recorded in advance. It scored −0.298
across 646 days of 2024 to 2026 data, and we reverted the change.

The signal itself generalised: gross Sharpe rose from 1.23 in sample to 1.75 out
of sample, the best gross figure the project has produced. Turnover was the
failure, at 102.6 times per year against 45.3 in sample, after which costs
consumed 117% of gross.

The finding generalises to every configuration decision we make. Selecting a
configuration on net Sharpe is implicitly selecting it on a turnover estimate,
and turnover is substantially less stable out of sample than the signal. This
failure mode operates with the alpha fully intact, and is most severe on fast
configurations where turnover is largest.

## 4. Live trading record

The strategy funded on 30 July and traded on 31 July, which remains the only
trading day.

| Book | Capital | Gross | P&L | Return |
|---|---|---|---|---|
| cef_discount | $500,000 | $749,458 | −$7,350 | −1.47% |
| phase0_null_trader | $640,000 | $640,000 | −$281 | −0.04% |
| Five benchmark books | $20,000 each | $100,000 | −$253 total | |

Attribution summed to −$7,884 against the broker's reported −$7,883.09, so every
position is accounted for.

### 4.1 Execution finding

Priced at the decision prices the strategy traded on, the book was up $50. Priced
at the fills we received, it was down $7,350. The difference is entirely
slippage.

The strategy must decide in the evening, because its signal requires the NAV,
which publishes after the close. Plain market orders therefore rested overnight
and filled at 07:27 ET, two hours before the exchange opened, in funds with
negligible pre-market depth.

| Traded | Slippage | Realised | Modelled | Ratio |
|---|---|---|---|---|
| $682,351 | $6,405 | 0.94% | ~0.10% | 9.4× |

Slippage ran against us on every buy and every sell, the signature of crossing a
wide spread rather than noise. At 24 rebalances per year this is 22.6% annually
against a strategy earning 4.85%.

We excluded the possibility of erroneous prices by reconciling all 17 funds
against the broker's daily bars over ten days; median disagreement was 0.000%.
The cause is purely execution.

We switched to market-on-close orders, which execute in the closing auction, the
deepest liquidity of the day and the point the backtest assumed. Routing was
verified live and the scheduled job transmitted 16 market-on-close orders.

Whether this is sufficient is the most important open question in the project,
ahead of returns. We cannot slow the strategy to escape the cost, as net Sharpe
falls sharply with holding period.

### 4.2 Current status

The system has not traded since 1 August. Interactive Brokers TWS has not been
running, and every session since ends with the blocker "nothing listening on
127.0.0.1:7497". TWS restarts daily and requires an interactive login.

We therefore hold one day of live evidence, not sixty. The 60-session review
required by the kill rule remains ahead of us, and restoring the broker
connection is our first priority.

The remainder of the system operated correctly throughout the outage. Data
collection, reporting and the watchdog have run every weekday, which is the
four-phase session design performing as designed: a book that cannot trade still
records.

## 5. Evidence

All claims above are verifiable against files in the repository.

### 5.1 Broker executions

`ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv` holds 257 real
executions from the paper account, each with the broker's execution id,
commission and timestamp:

```
2026-07-31T21:20:29.234516+00:00,2026-07-31,BIT,BUY,720.0,12.55,ibkr_paper,
execId=00012ec5.6a6cade0.01.01 orderRef='' commission=3.60216
time=2026-07-31 11:27:57+00:00
```

The 11:27 UTC timestamp is the 07:27 ET pre-market fill described in section 4.1,
so the evidence of the defect and the record of the trade are the same file.
`ops/books/phase0_live/_ibkr_shadow/null_trader/broker_fills.csv` holds a further
45 executions for the control experiment.

### 5.2 Ledger trail

Each book maintains `nav.csv`, `positions.csv`, `orders.csv`, `trades.csv`,
`slippage.csv` and `manifest.json`, the last verified on every load. The slippage
file records the execution failure by name: AWF at 158.6bp realised against 17.5
modelled, BIT at 261.7 against 13.8, PFN at 254.2 against 18.8.

### 5.3 Trial ledger

`results/credit_rv/trial_log.csv` holds 156 numbered trials, each timestamped,
with Sharpe, return, volatility, drawdown, turnover, cost drag and a written note.
Trial 1 is dated 2026-07-28 20:12:03 and reads "first baseline: continuous sizing,
1993+ sample, 87x/yr turnover, rejected on cost". Trial 156 is dated 2026-07-31
01:44:18. This file is our multiple-testing count, it never resets, and it is what
makes the deflated Sharpe calculation legitimate.

### 5.4 Holdout records

`results/cef/HOLDOUT_PREREG.md` states the rules and pass mark and was written
before the holdout was opened. `results/cef/HOLDOUT_OPENED.json` records the
opening at 2026-07-31 21:47 UTC, the window, the result of −0.298 and the verdict
FAIL. `results/credit_rv/HOLDOUT_OPENED.json` records the holdout that killed the
earlier strategy at −1.435, t = −2.29.

A holdout that fails and is recorded as failing is stronger evidence of process
integrity than one that passes.

### 5.5 Operational record

`ops/schedule/logs/` holds 42 session logs from 20 July to 15 August, one per job
per day across five job types. `ops/heartbeat.json` records per-job liveness; at
issue it shows collection succeeding 15 August 04:28, the weekly report at 09:02,
and both trading jobs correctly reporting themselves blocked by the absent broker
connection.

### 5.6 Pre-commitment documents

`CREDIT_RV_PREREG.md` and `E1_PREREG.md` are pre-registrations for two strategies
subsequently killed, stating success criteria before the tests were run. Files in
`ops/specs/` are frozen specifications, each carrying an evidence block and a kill
rule committed in advance. Every parameter subsequently changed carries a note
field recording the measurement behind the change.

## 6. Parallel research programme

Research ran as concurrent independent investigations rather than a single
sequential thread, and each left its own artifacts.

The clearest instance is the second research night, when four investigations ran
in parallel alongside the critical path. Three returned useful results, two of
which corrected our own assumptions.

The government filings investigation produced 136,268 rows of holdings history
and corrected us on two points: the public filings contain one snapshot per
quarter rather than three monthly ones, and the valuation-difficulty field we
intended to use is degenerate, with 135,850 of 135,870 corporate bonds carrying
an identical classification.

The universe investigation expanded us from 10 tradable instruments to 56, and
separately identified that the final bar in our price panel was a partial
intraday capture, which would have introduced a false return on the most recent
day.

The positioning investigation delivered 26,116 rows of short-selling data and a
useful negative: our financing file contains no real borrowing-cost data, so any
strategy built on borrowing costs was never feasible from our holdings. Full
account in `HOW_WE_GOT_HERE.md` section 3.2.

The structure is visible in the repository. `results/` holds one directory per
investigation family — `s1`, `s3`, `s4`, `disp`, `leadlag`, `ou`, `positioning`,
`universe`, `e1`, `credit_rv`, `cef`, `bench` — mirrored in `scripts/`. These were
produced concurrently.

Overnight sessions left their own record.
`results/journal/2026-07-30_overnight.md` is a checkpoint journal written, in its
own words, so that "the morning reader can reconstruct the night without reading
logs". It records each gate with figures attached: 15 funds, 29,698 holdings,
11,423 priced bonds, two incorrect fund ids caught, NAV rebuild matching within
0.07% on 10 of 12 funds, and two accounting defects found and fixed.
`results/OVERNIGHT_REPORT_2026-07-30.md` is the full write-up.

Separate lines of work produced their own analysis documents with reproduction
scripts: `results/AUDIT_2026-07-31.md`,
`results/ACADEMIC_REPORT_2026-07-31.md`,
`results/cef/research/NICHE_EDGE_RESEARCH.md`, `results/cef/ESTIMATOR_NOTE.md`,
`results/cef/DIST_CUT_NOTE.md`, `results/credit_rv/FINDINGS.md` and
`results/e1/E1_RESEARCH_NOTE.md`.

Handoff boundaries are marked in the code. `ops/schedule/install.sh` records that
the agent which built it ran only the default render mode, and that installing
and enabling the scheduled jobs is left to a human. `RESEARCH_STATE.md` credits
agent staging for the N-PORT and breadth datasets and maintains a separate trial
counter per data source.

## 7. Defects identified in our own work

| # | Defect | Detection |
|---|---|---|
| 1 | Compared a full bid-ask spread to a half spread, halving the reported cost ratio | Re-derived the comparison |
| 2 | Two fund ids pointed at wrong funds, one an equity fund | Printed the column set on first pull |
| 3 | Event study showed a 414% recovery | Impossible on its face |
| 4 | Survivorship: bonds that ceased trading dropped out | Re-ran under five sample definitions |
| 5 | Counted trading days rather than calendar days, so "60 days" meant a year for illiquid bonds | Same re-examination |
| 6 | Interest on idle cash counted as skill | Costs came out negative |
| 7 | Charged financing to self-funding market-neutral books | Random control scored −0.77 where zero is required |
| 8 | Measured returns at a non-existent price | Re-tested at tradable prices; effect vanished |
| 9 | Used a varying hedge ratio on both sides, creating false momentum | Control group scored highest |
| 10 | Assumed dislocation implies opportunity | Measured by regime rather than assumed |
| 11 | Assumed group-neutral matching would help | Tested one change at a time |
| 12 | Selected the fund list using current data | Rebuilt point-in-time |
| 13 | Broker never read its own configuration; every live run would have failed | Attempted a real connection |
| 14 | Position filter ran after neutralisation, leaving the book lopsided | Checked the sum of the first live order set |
| 15 | Scheduler invoked a non-existent command | Tested the scheduled path, not the strategy |
| 16 | Reported the control experiment as trading when it had only dry-run | Read the log rather than trusting our summary |

Six of these — 3, 6, 7, 8, 9 and 13 — were detected because a control or sanity
check produced an impossible value. Negative controls do not find the edge; they
identify the occasions on which we were about to mislead ourselves.

## 8. Transferable findings

Costs do not diversify while volatility does. Adding strategies reduces
volatility, but costs are deducted in full from each, so cost drag measured in
Sharpe grows with the number of strategies. This killed our strongest combination
result, which showed a gross Sharpe of +1.03 and a net of −0.16.

Selecting on net Sharpe means selecting on a turnover estimate, and turnover is
the unstable component. Our sealed holdout failed on exactly this while the
signal improved out of sample.

Testing must cover the deployed path, not the logic alone. Three defects — the
broker port, the scheduler flag and the missing strategy class — were invisible
to research testing and would have surfaced only as live failures.

Data availability must be confirmed before design. We built an entire research
session around holdings history before establishing that no archive exists.

Favourable results warrant the most scepticism. Every false discovery we made
appeared excellent initially, with t-statistics of 25 and recoveries of 414%.

A strategy is valued by its contribution to the book, not its standalone score. A
mediocre strategy uncorrelated with existing holdings is worth more than a strong
one that moves with them.

## 9. Position entering the school year

The signal is established and survived every control we could construct. The
infrastructure schedules, checks, halts and reports itself, including reporting
its own failures.

Six items are open, in priority order.

1. Establish whether market-on-close brings slippage within tolerance. We hold no
   sessions of evidence on this and everything depends on it.
2. Restore a reliable broker connection so sessions trade. One day of live data is
   not a track record.
3. Reach 60 sessions and execute the pre-committed review.
4. Build a defence against distribution cuts, which permanently re-rate a discount
   wider and are the standard loss mode for this strategy.
5. Resize the books, currently 158% committed against account equity.
6. Pre-register the January CEF basis trade. It shows +11.71bp per day in January
   at t = 3.99, was positive in 20 of 23 Januaries, and correlates −0.001 with the
   deployed strategy. Combining 0.82 and 0.73 at zero correlation gives 1.10, a
   larger gain than any realistic improvement to the main strategy, and it is five
   months away.

We hold one established signal, one functioning system, one day of live evidence,
and one unresolved question over whether the strategy is affordable to trade.
