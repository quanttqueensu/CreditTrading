---
title: "Summer 2026: Progress and Results"
subtitle: |
  **QUANTT Credit Trading**\
  Covering 19 July to 16 August 2026 · written 16 August 2026\
  github.com/quanttqueensu/CreditTrading
---

## The short version

We set out to build a credit strategy that makes money whether the market goes up
or down. We tested thirteen separate ideas. Twelve of them died. One survived
everything we could throw at it, and it now runs on a $500,000 Interactive
Brokers paper account, placing its own orders on a schedule.

Along the way we built a free daily feed of 11,423 bond prices, discovered that
our own cost model had been overcharging every strategy by a factor of 3.7,
caught sixteen mistakes in our own work, and learned on the first day of live
trading that execution costs matter more than the signal does.

The number that describes the summer best is not a return. It is thirteen tested
and one survived.

## What we built

### The strategy

Credit closed-end fund discount reversion. A closed-end fund trades on an
exchange like a stock but has a fixed share count forever, so nothing can pull
its price back to the value of what it holds. Credit closed-end funds sit about
3.16% below that value on average, with a standard deviation of 5.95%, which is
around 150 times the gap you find on an ordinary ETF.

The strategy compares each fund's discount to its own 252-day history, buys the
unusually cheap ones, shorts the unusually rich ones, holds equal dollars on each
side, and targets 6% volatility a year.

### The machinery

We built a backtest engine with a lookahead guard and purged walk-forward
testing, a deployment framework where every strategy implements the same four
methods, and 1,077 lines of Interactive Brokers integration with a gate that
reconciles our records against the broker's before any order goes out. Each
strategy keeps its own ledger recording positions, orders, modelled trades, real
fills and slippage. Five scheduled jobs run the whole thing unattended on
weekdays, with seven safety checks in front of any trade and a cost model
covering 45 tickers calibrated against real measured bid-ask spreads.

### The data

| Dataset | Size | Note |
|---|---|---|
| Daily bond price panel | 11,423 bonds a day | Free, from fund holdings files. No archive exists, so it only grows forward |
| SEC N-PORT holdings | 136,268 rows from 2019 | Checked against a live holdings file, 95.3% overlap |
| Closed-end fund prices and NAVs | 265,615 and 232,799 rows, back to 1986 | 44 funds |
| Fallen-angel events | 16,388 rating migrations, 2003 to 2025 | With index removal dates |
| FINRA short volume | 26,116 rows | Daily, free |
| Tradable universe | 10 instruments up to 56 | |

## What we found

### The thirteen ideas

| Idea | Verdict | Why |
|---|---|---|
| credit_rv | killed | Sealed holdout Sharpe −1.44, and the edge was negative before costs |
| E1, HYG against JNK | killed | Negative out of sample. The opportunity shrank from 188bp to 3.8bp |
| S1, cross-issuer price disagreement | killed | The input carries no information. Median disagreement 0.09bp, because every issuer buys prices from the same vendor |
| S3, fallen angels through ETFs | killed | A credit-quality risk premium in disguise. Holding the fund with no signal scored 0.37; adding our signal scored 0.03 to 0.24 |
| single-fund premium/discount | killed | The gap predicts the NAV catching up, not the price. Trading it means betting against real price discovery |
| leadlag | killed | Measured at a price that does not exist. At tradable prices it went from t of 5.20 to −0.50, and the control group scored higher |
| nport-trace-nav | infeasible | Only 17 to 30% of a fund's holdings trade on a given day, and those are the ones with news |
| dealer-constraint | killed | No credit name significant at any horizon, and the Treasury control showed the same size effect |
| pair-reversion | killed on arithmetic | Gross Sharpe +1.03, but costs do not diversify while volatility does, so net came to −0.16. Hitting the volatility target needed 32.8x leverage against a 2x legal limit |
| short-pressure | killed | The rates comparison group scored higher than credit |
| raw-flow-z | killed | A precise zero across 28,025 observations, every t below 0.8 |
| distribution events | killed | Cuts move the discount the wrong way for the thesis, and the effect is not proportional to the size of the cut |
| CEF discount reversion | deployed | Passed everything below |

Two ideas sit on a watch list rather than dead. Forced-flow price pressure is
real and large, at −424bp with a t of −17.5 and 82 to 85% of it reversing, but
the only way we can trade it dilutes the signal five to one. And the
premium/discount band still works per opportunity; what collapsed was the number
of opportunities.

### What the survivor passed

| Test | Result | Verdict |
|---|---|---|
| Point-in-time universe, no survivorship or liquidity hindsight | gross 1.26, net 0.82, volatility 6.00%, worst drawdown −12.0% | pass, and better than the biased version |
| Purged walk-forward, 10 blocks, 5-day embargo | 9 of 9 positive, median 1.12, worst 0.01 | pass |
| Block bootstrap, 5,000 draws | 5th and 95th percentile 0.52 and 1.11, chance of Sharpe at or below zero 0.000% | pass |
| Deflated Sharpe, adjusted for 10 specifications | 0.956 | pass |
| Market exposure, the test that killed everything else | alpha t 3.11, R-squared 0.005, 5 of 5 factor limits | pass |

An R-squared of 0.005 means 99.5% of the return is unexplained by high yield,
investment grade, rates, equity or volatility.

### Two attempts to kill it, both failed

The live book runs 66% net short municipal funds and 57% net long taxable funds,
so the obvious suspicion was that it is a sector bet in disguise, which is exactly
what one earlier candidate turned out to be.

| Control set | Alpha per year | t | R-squared |
|---|---|---|---|
| The original factor set | +8.21% | +5.67 | 0.0037 |
| Plus municipal ETFs | +8.88% | +5.69 | 0.0117 |
| Plus municipal ETFs and a duration spread | +8.83% | +5.67 | 0.0125 |
| All five closed-end fund group factors | +7.63% | +5.90 | 0.0057 |

The last row is the one that counts, because municipal closed-end fund discounts
do not move like a municipal ETF. Under it every group beta comes in at or below
0.025 and the alpha does not move.

### Three things we got wrong

An end-to-end audit on 31 July found three problems with what was actually
deployed. They change the expected result, so they belong in this document.

The specification, the code and the optimum all disagreed about how often to
trade. The spec said rebalance every five days, only an unrelated file ever read
that setting, so the live code traded every session, and the measured optimum was
two days. Net Sharpe runs 0.62 at one day, 0.73 at two, 0.51 at five and 0.20 at
twenty-one. We changed it to two.

The backtest assumed an entry price we cannot get. It entered at day t's close
using day t's NAV, but that NAV comes out after that close. A market-on-close
order fills at the next day's close instead. Correcting this costs 38% of the
Sharpe, taking 0.82 down to 0.51.

No sealed holdout was ever taken for this strategy. The credit_rv strategy got
141 trials and a sealed holdout before we killed it. This one got ten
specifications and $500,000 in under two hours. That was a governance failure, and
it happened on the one strategy that got money.

So the honest expected net Sharpe of what was deployed is 0.51, not 0.82. Fixing
the holding period takes it to about 0.73.

### The holdout we did open, and failed

On 31 July we opened a sealed holdout on a proposed change, a 63-day z-window
instead of 252. The pass mark was written down beforehand at +0.40. It scored
−0.298 across 646 days of 2024 to 2026 data, so we reverted the change.

The interesting part is that the signal itself generalised. Gross Sharpe went from
1.23 in sample to 1.75 out of sample, which is the best gross number the project
has produced. What failed was turnover, which came out at 102.6 times a year
against 45.3 in sample, and costs then ate 117% of the gross.

That lesson applies to every configuration choice we make. When you pick a
configuration on net Sharpe you are really picking it on a turnover estimate, and
turnover is much less stable out of sample than the signal is. You can lose this
way with the alpha completely intact, and it hits hardest on the fast
configurations where turnover is largest.

## The live trading record

The strategy funded on 30 July and traded on 31 July. That is still the only
trading day.

| Book | Capital | Gross | P&L | Return |
|---|---|---|---|---|
| cef_discount | $500,000 | $749,458 | −$7,350 | −1.47% |
| phase0_null_trader | $640,000 | $640,000 | −$281 | −0.04% |
| five benchmark books | $20,000 each | $100,000 | −$253 total | |

Attribution summed to −$7,884 against the broker's reported −$7,883.09, so every
position is accounted for.

### What day one taught us

Priced against the numbers the strategy decided on, the book was up $50. Priced
against the fills we actually got, it was down $7,350. The whole difference is
slippage.

The cause is that the strategy has to decide in the evening, because its signal
needs the NAV and the NAV does not publish until after the close. Plain market
orders therefore sat overnight and filled at 07:27 in the morning, two hours
before the exchange opened, when these funds have almost no liquidity.

| | |
|---|---|
| Traded | $682,351 |
| Slippage | $6,405 |
| Realised cost | 0.94% |
| Modelled cost | about 0.10% |
| Ratio | 9.4 times |

Slippage went against us on every buy and every sell, which is what crossing a
wide spread looks like rather than random noise. At 24 rebalances a year this is
22.6% annually in costs against a strategy earning 4.85%.

We checked whether our prices were simply wrong by reconciling all 17 funds
against the broker's own daily bars over ten days. The median disagreement was
0.000%, so this is purely execution.

The fix was to switch to market-on-close orders, which trade in the closing
auction, the deepest and cheapest moment of the day and the exact point the
backtest assumed. Routing was tested live and the scheduled job successfully sent
16 market-on-close orders.

Whether that worked is the biggest open question in the project, ahead of
returns. We already know we cannot slow the strategy down to get out of the
problem, because the net Sharpe falls off sharply with holding period.

### Where it stands right now

The system has not traded since 1 August. Interactive Brokers TWS has not been
running, and every session since ends with the blocker "nothing listening on
127.0.0.1:7497". TWS restarts daily and needs a human to log in.

That is worth saying plainly rather than burying. We have one day of live
evidence, not sixty. The 60-session review the kill rule calls for is still ahead
of us, and getting the broker connection reliable is the first job of the year.

The rest of the system kept working through the outage. Data collection,
reporting and the watchdog have all run every weekday, which is the four-phase
session design doing what it was built to do: a book that cannot trade still
records.

## Proof of real history

Everything above can be checked against files in the repository rather than taken
on trust. This section says where to look.

### Real broker executions

`ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv` holds 257 real
executions from the paper account, each carrying the broker's own execution id,
the commission and the timestamp. One row looks like this:

```
2026-07-31T21:20:29.234516+00:00,2026-07-31,BIT,BUY,720.0,12.55,ibkr_paper,
execId=00012ec5.6a6cade0.01.01 orderRef='' commission=3.60216
time=2026-07-31 11:27:57+00:00
```

The 11:27 UTC timestamp is the 07:27 New York pre-market fill described above, so
the evidence of the problem and the record of the trade are the same file.
`ops/books/phase0_live/_ibkr_shadow/null_trader/broker_fills.csv` holds another 45
executions for the control experiment.

### The full ledger trail

Each book keeps `nav.csv` for daily value and return, `positions.csv`,
`orders.csv` for what we asked for and whether it filled, `trades.csv` for
modelled fills with the cost broken out, `slippage.csv` for realised against
modelled per name, and `manifest.json` with row counts and last dates that get
checked whenever the ledger loads.

The slippage file records the failure name by name: AWF at 158.6 basis points
realised against 17.5 modelled, BIT at 261.7 against 13.8, PFN at 254.2 against
18.8.

### The trial ledger

`results/credit_rv/trial_log.csv` holds 156 numbered trials, each timestamped,
with its Sharpe, return, volatility, drawdown, turnover, cost drag and a written
note. Trial 1 is dated 2026-07-28 at 20:12:03 and reads "first baseline:
continuous sizing, 1993+ sample, 87x/yr turnover, rejected on cost". Trial 156 is
dated 2026-07-31 at 01:44:18.

This file is our multiple-testing count. It is what makes the deflated Sharpe
calculation honest, and it never resets.

### Sealed holdout records

`results/cef/HOLDOUT_PREREG.md` states the rules and the pass mark, and it was
written before the holdout was opened. `results/cef/HOLDOUT_OPENED.json` records
the opening at 2026-07-31 21:47 UTC, the window, the result of −0.298 and the
verdict FAIL. `results/credit_rv/HOLDOUT_OPENED.json` records the holdout that
killed the earlier strategy at −1.435 with a t of −2.29.

A holdout that fails and gets recorded as failing is better evidence of an honest
process than one that passes.

### Session logs and heartbeat

`ops/schedule/logs/` holds 42 session logs running from 20 July to 15 August, one
per job per day across five job types. `ops/heartbeat.json` records whether each
job is alive. As of writing it shows collection succeeding on 15 August at 04:28,
the weekly report at 09:02, and the two trading jobs correctly reporting
themselves blocked by the missing broker connection.

### Documents written before the fact

`CREDIT_RV_PREREG.md` and `E1_PREREG.md` are pre-registrations for two strategies
we later killed. They state what would count as success before the tests were
run. The files in `ops/specs/` are frozen strategy specifications, each with an
evidence block and a kill rule committed in advance. Every setting we later
changed carries a note field recording the measurement behind the change.

## Proof of multiple agents

Research ran as several independent investigations at once rather than one thread
in sequence, and each one left its own artifacts behind.

The clearest example is the second research night, when four investigations ran
in parallel while the critical path was worked separately. Three came back with
useful results and two of those came back correcting our own assumptions.

The government filings investigation produced 136,268 rows of holdings history,
and also corrected us on two points. The public filings contain one snapshot per
quarter rather than three monthly ones, and the valuation-difficulty field we had
hoped to use is useless because 135,850 of 135,870 corporate bonds carry an
identical classification.

The universe investigation took us from 10 tradable instruments to 56, and
separately caught that the final bar in our price panel was a partial intraday
capture, which would have put a fake return on the most recent day.

The positioning investigation delivered 26,116 rows of short-selling data plus a
useful negative: our financing file contains no real borrowing-cost data at all,
so any strategy built on borrowing costs was never possible from what we have.

All of this is written up in `HOW_WE_GOT_HERE.md`, section 3.2.

The parallel structure is visible in the repository too. `results/` holds one
folder per investigation family, each with its own outputs: `s1`, `s3`, `s4`,
`disp`, `leadlag`, `ou`, `positioning`, `universe`, `e1`, `credit_rv`, `cef` and
`bench`. The same split is mirrored in `scripts/`, where each family has its own
directory. These were produced alongside each other rather than one after
another.

Overnight sessions left their own record. `results/journal/2026-07-30_overnight.md`
is a checkpoint-by-checkpoint journal written, in its own words, so that "the
morning reader can reconstruct the night without reading logs". It notes each
gate as it passed, with the numbers attached: 15 funds, 29,698 holdings, 11,423
priced bonds, two wrong fund ids caught, the NAV rebuild matching within 0.07% on
10 of 12 funds, and two accounting bugs found and fixed.
`results/OVERNIGHT_REPORT_2026-07-30.md` is the full write-up of that session.

Several analysis documents came out of separate lines of work, each with its own
reproduction scripts: `results/AUDIT_2026-07-31.md`,
`results/ACADEMIC_REPORT_2026-07-31.md`,
`results/cef/research/NICHE_EDGE_RESEARCH.md`, `results/cef/ESTIMATOR_NOTE.md`,
`results/cef/DIST_CUT_NOTE.md`, `results/credit_rv/FINDINGS.md` and
`results/e1/E1_RESEARCH_NOTE.md`.

The handoff boundaries are marked in the code as well. `ops/schedule/install.sh`
carries a comment saying the agent that built it ran only the default render mode,
and that installing and enabling the scheduled jobs is deliberately left to a
human. `RESEARCH_STATE.md` credits agent staging for the N-PORT and breadth
datasets, and keeps a separate trial counter for each data source.

## The sixteen mistakes

| # | Mistake | How we caught it |
|---|---|---|
| 1 | Compared a full bid-ask spread to a half spread, reporting costs at half their real ratio | Re-derived it from scratch |
| 2 | Two fund ids pointed at the wrong funds, one of them a stock fund | Printed the column set on the first pull |
| 3 | An event study showed a 414% recovery | The number was absurd on its face |
| 4 | Bonds that stopped trading dropped out, leaving only the survivors | Re-ran under five different sample definitions |
| 5 | Counted trading days instead of calendar days, so "60 days" meant a year for illiquid bonds | Same re-examination |
| 6 | Interest on idle cash counted as skill | Costs came out negative, which is impossible |
| 7 | Charged financing to market-neutral books that fund themselves | The random control scored −0.77 when it has to be zero |
| 8 | Measured returns at a price that does not exist | Re-tested at tradable prices and the effect vanished |
| 9 | Used a changing hedge ratio on both sides, which created fake momentum | The control group scored highest, which is impossible |
| 10 | Assumed dislocation means opportunity | Measured it by regime instead of assuming |
| 11 | Assumed matching similar funds would help | Tested one change at a time |
| 12 | Picked the fund list using today's data | Rebuilt it point-in-time |
| 13 | The broker never read its own settings and would have failed every live run | Tried to actually connect |
| 14 | The position filter ran after balancing, leaving the book lopsided | Checked the sum of the first live order set |
| 15 | The scheduler called a command that does not exist | Tested the scheduled path, not just the strategy |
| 16 | Reported the control experiment as trading when it had only done a dry run | Read the log properly instead of trusting our own summary |

Six of these, numbers 3, 6, 7, 8, 9 and 13, were caught because a control group
or a sanity check produced a number that could not possibly be right. Not because
we were clever, but because we had built something that had to come out a certain
way and it did not. That is what negative controls are for. They do not find your
edge, they find the times you were about to fool yourself.

## What we learned that carries over

Costs do not diversify but volatility does. Add more strategies and the
volatility falls, while the costs come off every one of them in full, so the cost
drag measured in Sharpe actually grows as you add more. That is what killed our
best combination idea, which had a gross Sharpe of +1.03 and a net of −0.16.

Picking a configuration on net Sharpe means picking it on a turnover estimate,
and turnover is the unstable part. Our sealed holdout failed on exactly that while
the signal itself got better out of sample.

Test the path you actually deploy, not just the logic. Three of our bugs, the
broker port, the scheduler flag and the missing strategy class, were invisible to
research testing and would only have shown up as live failures.

Check the data exists before designing around it. We built a whole research night
around holdings history and then found out there is no archive. Twenty minutes of
checking would have redirected the night much earlier.

Be suspicious of good news in particular. Every one of our false discoveries
looked excellent at first, with t-statistics of 25 and recoveries of 414%. The bad
results never fooled anybody.

A strategy is worth what it adds to the whole book, not what it scores on its
own. A mediocre strategy that makes money on different days than everything else
is worth more than a good one that moves in step with what you already hold.

## Where this leaves the school year

The signal is real and it survived every control we could build. The
infrastructure works: it schedules itself, checks itself, halts itself, and
reports honestly, including reporting its own failures.

Six things are open and they matter roughly in this order.

First, does market-on-close bring slippage inside tolerance? Everything depends on
this and we have no sessions of evidence on it yet. Second, get the broker
connection reliable so sessions actually trade, because one day of live data is
not a track record. Third, reach 60 sessions and run the pre-committed review
honestly. Fourth, build a defence against distribution cuts, which permanently
re-rate a discount wider and are the classic way this strategy loses money.
Fifth, resize the books, which are 158% committed against account equity. Sixth,
write up the January closed-end fund trade properly. It shows +11.71 basis points
a day in January with a t of 3.99, was positive in 20 of 23 Januaries, and has a
correlation with the main strategy of −0.001. Combining a 0.82 and a 0.73 at zero
correlation gives 1.10, which is a bigger gain than any realistic improvement to
the main strategy, and it is five months away so there is no excuse to rush it.

So: one strong signal, one working machine, one day of live evidence, and one
large unanswered question about whether we can afford to trade it. That is a good
place to start a year from, and a bad place to claim success from.
