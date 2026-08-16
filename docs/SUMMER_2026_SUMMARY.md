# Summer 2026: Progress and Results

**QUANTT Credit Trading**
**Period covered:** 2026-07-19 to 2026-08-16
**Repository:** https://github.com/quanttqueensu/CreditTrading
**Written:** 2026-08-16

---

## The short version

We set out to build a systematic credit strategy that makes money whether the
market rises or falls. We tested thirteen separate ideas. Twelve died. One
survived every test we could throw at it and now runs live on a $500,000
Interactive Brokers paper account, placing its own orders on a schedule.

Along the way we built a free daily feed of 11,423 individual bond prices, found
that our own cost model had been overcharging every strategy by a factor of 3.7,
caught sixteen separate mistakes in our own work, and discovered on day one of
live trading that execution costs matter far more than the signal does.

The most useful number in this document is not a return. It is thirteen tested,
one survived. That ratio is roughly what an honest research process is supposed
to produce.

---

## Part 1: What we built

### The strategy

Credit closed-end fund discount reversion. A closed-end fund trades on the
exchange like a stock but has a fixed share count forever, so nothing can
arbitrage its price back to the value of what it holds. Credit closed-end funds
trade about 3.16% below their stated value on average, with a standard deviation
of 5.95%, which is about 150 times the equivalent gap on an ordinary ETF.

The strategy compares each fund's discount to its own 252-day history, buys the
unusually cheap ones, shorts the unusually rich ones, holds equal dollars on each
side, and targets 6% annual volatility.

### The infrastructure

| Piece | What it is |
|---|---|
| Backtest engine | Vectorised daily engine with a lookahead guard and purged walk-forward |
| Deployment framework | A four-method contract every strategy implements, with a registry that validates specs |
| Broker layer | 1,077 lines of Interactive Brokers integration, with an arming gate that reconciles our records against the broker's before any order |
| Ledgers | Per-strategy sub-ledgers recording positions, orders, modelled trades, real fills, and slippage |
| Automation | Five scheduled jobs running unattended on weekdays |
| Safety | Seven preflight checks before any trade, plus halt files, banners, and spoken alerts |
| Cost model | 45 tickers priced, calibrated against real measured bid-ask spreads |

### The data

| Dataset | Size | Note |
|---|---|---|
| Daily bond price panel | 11,423 priced bonds per day | Free, from fund holdings files. No historical archive exists, so it accumulates forward only |
| SEC N-PORT holdings | 136,268 rows, 2019 onward | Verified against a live holdings file at 95.3% overlap |
| Closed-end fund prices and NAVs | 265,615 price rows, 232,799 NAV rows, back to 1986 | 44 funds |
| Fallen-angel events | 16,388 rating migrations, 2003 to 2025 | With index removal dates |
| FINRA short volume | 26,116 rows | Daily, free |
| Tradable universe | Expanded from 10 instruments to 56 | |

---

## Part 2: Results

### The thirteen mechanisms

| Idea | Verdict | Why it died |
|---|---|---|
| credit_rv | Killed | Sealed holdout Sharpe −1.44. Edge was negative before costs |
| E1 (HYG vs JNK discount) | Killed | Out of sample negative. The opportunity shrank from 188bp to 3.8bp |
| S1 (cross-issuer price disagreement) | Killed | The input carries no information. Median disagreement 0.09bp, because all issuers buy from the same pricing vendor |
| S3-wrapper (fallen angels via ETFs) | Killed | A credit-quality risk premium in costume. Holding the fund with no signal scored 0.37, adding our signal scored 0.03 to 0.24 |
| single-fund premium/discount | Killed | The gap predicts the NAV catching up, not the price. Trading it means betting against genuine price discovery |
| leadlag | Killed | Measured on a price that does not exist. Under tradable prices the effect went from t of 5.20 to −0.50, and the control group scored higher |
| nport-trace-nav | Infeasible | Only 17 to 30% of a fund's holdings trade daily, and the ones that do are selected for having news |
| dealer-constraint | Killed | Zero credit names significant at any horizon. The Treasury control showed the same magnitude |
| pair-reversion | Killed on arithmetic | Combination worked (gross Sharpe +1.03, mean pairwise correlation +0.027) but costs do not diversify while volatility does, so net fell to −0.16. Reaching the volatility target needed 32.8x leverage against a 2x legal limit |
| short-pressure | Killed | The rates comparison group scored higher than credit |
| raw-flow-z | Killed | A precise zero across 28,025 observations, all t below 0.8 |
| distribution events | Killed | Cuts move the discount the wrong way for the thesis, and are not monotone in cut size |
| **CEF discount reversion** | **Deployed** | Passed everything below |

Two ideas remain on a watch list rather than dead: forced-flow price pressure
(the mechanism is real and large, at −424bp with t of −17.5 and 82 to 85%
reversal, but the only tradable expression dilutes it five to one) and the
premium/discount band form (the edge per opportunity survived, only the number of
opportunities collapsed).

### What the survivor passed

| Test | Result | Verdict |
|---|---|---|
| Point-in-time universe, no survivorship or liquidity hindsight | gross 1.26, net 0.82, volatility 6.00%, max drawdown −12.0% | Pass, and *better* than the biased version |
| Purged walk-forward, 10 blocks, 5-day embargo | 9 of 9 positive, median 1.12, worst 0.01 | Pass |
| Block bootstrap, 5,000 draws | 5th and 95th percentile 0.52 and 1.11, probability of Sharpe at or below zero 0.000% | Pass |
| Deflated Sharpe, haircut for 10 specifications | 0.956 | Pass |
| Market exposure (the test that killed everything else) | alpha t 3.11, R-squared 0.005, 5 of 5 factor limits | Pass |

An R-squared of 0.005 means 99.5% of the return is unexplained by high yield,
investment grade, rates, equity, or volatility.

### Two deliberate attempts to kill it, both failed

The live book is 66% net short municipal funds and 57% net long taxable funds, so
the obvious suspicion was that it is a sector bet in disguise, exactly the way
one earlier candidate turned out to be a credit-quality tilt in disguise.

| Control set | Alpha per year | t | R-squared |
|---|---|---|---|
| The original factor set | +8.21% | +5.67 | 0.0037 |
| Plus municipal ETFs | +8.88% | +5.69 | 0.0117 |
| Plus municipal ETFs and a duration spread | +8.83% | +5.67 | 0.0125 |
| **All five closed-end fund group factors** | **+7.63%** | **+5.90** | **0.0057** |

The last row is the sharp control, because municipal closed-end fund discounts do
not move like a municipal ETF. Under it every group beta is at or below 0.025 and
the alpha is untouched.

### The honest corrections

An end-to-end audit on 2026-07-31 found three things wrong with what was actually
deployed, and we are reporting them because they change the expected result.

1. **The specification, the code, and the optimum all disagreed on holding
   period.** The spec said rebalance every 5 days, only an unrelated file read
   that setting, so the live code traded every session, and the measured optimum
   was 2 days. Net Sharpe by hold: 0.62 at 1 day, 0.73 at 2, 0.51 at 5, 0.20 at
   21. Fixed to 2.
2. **The backtest assumed an entry price we cannot get.** It entered at day t's
   close using day t's NAV, but that NAV publishes *after* that close. A
   market-on-close order fills at t+1's close instead. Correcting this costs 38%
   of the Sharpe, taking 0.82 down to 0.51.
3. **No sealed holdout was ever taken for this strategy.** The killed credit_rv
   strategy got 141 trials and a sealed holdout before it died. This one got 10
   specifications and $500,000 in under two hours. That was a governance failure
   on the one strategy that received money.

**The honest expected net Sharpe of the as-deployed configuration is 0.51, not
0.82.** Fixing the holding period takes it to roughly 0.73.

### The sealed holdout we did open, and failed

On 2026-07-31 we opened a sealed holdout on a proposed tuning (a 63-day z-window
instead of 252). Pre-registered pass bar was +0.40. It scored **−0.298** on 646
days of 2024 to 2026 data. We reverted the change.

The signal itself generalised: gross Sharpe went from 1.23 in-sample to 1.75 out
of sample, the best gross number the project has produced. What failed was
turnover, which came in at 102.6 times a year against 45.3 in-sample, and costs
then ate 117% of gross.

The lesson generalises to every configuration choice we make: **a configuration
chosen on net Sharpe is implicitly chosen on a turnover estimate, and turnover is
far less stable out of sample than the signal is.** Selection on net Sharpe can
fail with the alpha fully intact, and it fails worst on the fast configurations
where turnover is largest.

---

## Part 3: The live trading record

### What happened on day one

The strategy funded on 2026-07-30 and traded on 2026-07-31. It is the only
trading day so far.

| Book | Capital | Gross | Live P&L | Return |
|---|---|---|---|---|
| cef_discount | $500,000 | $749,458 | −$7,350 | −1.47% |
| phase0_null_trader | $640,000 | $640,000 | −$281 | −0.04% |
| 5 benchmark books | $20,000 each | $100,000 | −$253 total | |

Attribution summed to −$7,884 against the broker's reported total of −$7,883.09,
so every position is accounted for.

### The day-one lesson

Priced against the decision prices the strategy traded on, the book was **up
$50**. Priced against the fills we actually got, it was **down $7,350**. The
difference of $7,399 is entirely slippage.

The cause: the strategy must decide in the evening, because its signal needs the
NAV, which does not publish until after the close. Plain market orders therefore
rested overnight and filled at 07:27 ET, two hours before the exchange opened,
into pre-market where these funds have almost no liquidity.

| | |
|---|---|
| Traded | $682,351 |
| Slippage | $6,405 |
| Realised cost | 0.94% |
| Modelled cost | ~0.10% |
| Ratio | **9.4x** |

Slippage was against us on every buy *and* every sell, which is the signature of
crossing a wide spread rather than random noise. At 24 rebalances a year this is
22.6% annually in costs against a strategy earning 4.85%. Fatal several times
over.

We ruled out the alternative explanation by reconciling all 17 funds against the
broker's own daily bars over 10 days. Median disagreement was 0.000%. Our prices
are exact. This is purely an execution problem.

**The fix** is market-on-close orders, which execute in the closing auction, the
deepest and tightest liquidity of the day and the exact point the backtest
assumed. Routing was verified live and the scheduled job transmitted 16
market-on-close orders successfully.

**Whether this worked is the single most important open question**, ahead of
returns. We know we cannot slow the strategy down to escape the cost, because net
Sharpe collapses with holding period. If slippage stays above twice modelled, the
strategy is dead on costs.

### Current status, stated plainly

**The system has not traded since 2026-08-01.** Interactive Brokers TWS has not
been running, and every session since then ends with the blocker "nothing
listening on 127.0.0.1:7497". TWS restarts daily and needs a human login.

This is worth stating clearly rather than burying: we have one day of live
trading evidence, not sixty. The 60-session review the kill rule calls for is
still ahead of us, and getting the broker connection reliable is the first
infrastructure job of the school year.

The rest of the system kept running correctly through the outage. Data collection,
reporting, and the watchdog have all continued cleanly every weekday, which is the
four-phase session design working as intended: a book that cannot trade still
records.

---

## Part 4: Proof of real history

Everything above is reproducible from files in the repository. This section lists
where the evidence lives so anyone can check it rather than take our word.

### Real broker executions

`ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv` holds **257 real
executions** from the paper account, each with the broker's own execution id,
commission, and timestamp. A sample row:

```
2026-07-31T21:20:29.234516+00:00,2026-07-31,BIT,BUY,720.0,12.55,ibkr_paper,
execId=00012ec5.6a6cade0.01.01 orderRef='' commission=3.60216
time=2026-07-31 11:27:57+00:00
```

The 11:27 UTC timestamp is the 07:27 ET pre-market fill described above. The
evidence of the problem and the record of the trade are the same file.

`ops/books/phase0_live/_ibkr_shadow/null_trader/broker_fills.csv` holds a further
**45 executions** for the control experiment.

### The full ledger trail

For each book: `nav.csv` (daily value and return), `positions.csv`,
`orders.csv` (what we asked for and whether it filled), `trades.csv` (modelled
fills with a cost breakdown), `slippage.csv` (realised versus modelled per name),
and `manifest.json` (row counts and last dates, verified whenever the ledger
loads).

The CEF strategy's `slippage.csv` records the failure per name: AWF 158.6 basis
points realised against 17.5 modelled, BIT 261.7 against 13.8, PFN 254.2 against
18.8.

### The trial ledger

`results/credit_rv/trial_log.csv` holds **156 numbered trials**, timestamped,
each with its Sharpe, return, volatility, drawdown, turnover, cost drag, and a
written note. Trial 1 is dated 2026-07-28T20:12:03 and reads "first baseline:
continuous sizing, 1993+ sample, 87x/yr turnover, rejected on cost". Trial 156 is
dated 2026-07-31T01:44:18.

This file is the multiple-testing count. It is what makes the deflated Sharpe
calculation honest, and it never resets.

### Sealed holdout records

`results/cef/HOLDOUT_PREREG.md` states the rules and the pass bar. It was written
before the holdout was opened. `results/cef/HOLDOUT_OPENED.json` records the
opening at 2026-07-31T21:47Z, the window, the result of −0.298, and the verdict
FAIL. `results/credit_rv/HOLDOUT_OPENED.json` records the holdout that killed the
earlier strategy at −1.435 with a t of −2.29.

A holdout that fails and is recorded as failing is stronger evidence of an honest
process than a holdout that passes.

### Session logs and heartbeat

`ops/schedule/logs/` holds **42 session logs** spanning 2026-07-20 to 2026-08-15,
one per job per day, across five job types. `ops/heartbeat.json` records the
liveness of every job. As of this writing it shows collection succeeding at
2026-08-15 04:28, the weekly report at 2026-08-15 09:02, and the trading jobs
correctly reporting themselves blocked by the missing broker connection.

### Governance documents written before the fact

`CREDIT_RV_PREREG.md` and `E1_PREREG.md` are pre-registrations for two strategies
that were later killed. They state what would count as success before the tests
were run. `ops/specs/*.frozen.json` are frozen strategy specifications, each
carrying an evidence block and a pre-committed kill rule. Every setting that was
later changed carries a note field recording the measurement that justified the
change.

---

## Part 5: Proof of multiple agents

Research ran as parallel independent investigations rather than one sequential
thread, and each investigation left its own artifacts. This is visible in the
record in several places.

**Parallel investigations, documented as they ran.** On the second research night
four investigations ran at once while the critical path was worked separately.
Three returned useful results and two returned corrections to our own assumptions.
The government filings investigation produced 136,268 rows of holdings history
and also corrected us on two points we had assumed: the public filings contain one
snapshot per quarter rather than three monthly ones, and the valuation-difficulty
field we hoped to use is degenerate, with 135,850 of 135,870 corporate bonds
carrying an identical classification. The universe investigation expanded us from
10 to 56 instruments and separately caught that our price panel's final bar was a
partial intraday capture, which would have injected a fake return on the most
recent day. The positioning investigation delivered 26,116 rows of short-selling
data plus a useful negative: our financing file contains no real borrowing-cost
data at all, so any strategy built on borrowing costs was never possible from our
data. This is written up in `HOW_WE_GOT_HERE.md` section 3.2.

**Per-family result directories.** `results/` holds one directory per
investigation family, each with its own outputs: `s1/`, `s3/`, `s4/`, `disp/`,
`leadlag/`, `ou/`, `positioning/`, `universe/`, `e1/`, `credit_rv/`, `cef/`,
`bench/`. The same structure is mirrored in `scripts/`, where each family has its
own script directory. These were produced concurrently, not in sequence.

**Overnight session artifacts.** `results/journal/2026-07-30_overnight.md` is a
per-checkpoint journal written so that, in its own words, "the morning reader can
reconstruct the night without reading logs". It records each gate as it passed or
partially passed, with the concrete numbers attached: 15 funds, 29,698 holdings,
11,423 priced bonds, two wrong fund ids caught, NAV rebuild matching within 0.07%
for 10 of 12 funds, and two accounting bugs found and fixed.
`results/OVERNIGHT_REPORT_2026-07-30.md` is the full write-up of that session.

**Agent-generated analysis documents.** `results/AUDIT_2026-07-31.md` (the
end-to-end audit), `results/ACADEMIC_REPORT_2026-07-31.md`,
`results/cef/research/NICHE_EDGE_RESEARCH.md`, `results/cef/ESTIMATOR_NOTE.md`,
`results/cef/DIST_CUT_NOTE.md`, `results/credit_rv/FINDINGS.md`, and
`results/e1/E1_RESEARCH_NOTE.md` each document a separate line of work with its
own reproduction scripts.

**Explicit handoff boundaries in the code.** `ops/schedule/install.sh` carries the
comment that the agent which built it ran only the default render mode, and that
installing and enabling the scheduled jobs is deliberately left to a human.
`RESEARCH_STATE.md` credits agent staging for the N-PORT and breadth datasets and
tracks a separate trial counter per data source.

---

## Part 6: Sixteen mistakes, and how we caught them

The pattern matters more than the list.

| # | Mistake | How it was caught |
|---|---|---|
| 1 | Compared a full bid-ask spread to a half spread, reporting costs at half their true ratio | Re-derived from scratch |
| 2 | Two fund ids pointed at completely wrong funds, one a stock fund | Printed the column set on first pull |
| 3 | An event study showed a 414% recovery | The number was absurd on its face |
| 4 | Survivorship: bonds that stopped trading dropped out, leaving only survivors | Re-ran under five sample definitions |
| 5 | Counted trading days instead of calendar days, so "60 days" meant a year for illiquid bonds | Same re-examination |
| 6 | Idle cash interest counted as skill | Costs came out negative, which is impossible |
| 7 | Charged financing to self-funding market-neutral books | The random control scored −0.77 when it must be zero |
| 8 | Measured returns at a price that does not exist | Re-tested at tradable prices, the effect vanished |
| 9 | Used a changing hedge ratio on both sides, creating fake momentum | The control group scored highest, which is impossible |
| 10 | Assumed dislocation means opportunity | Measured by regime instead of assuming |
| 11 | Assumed matching similar funds would help | Tested one change at a time |
| 12 | Chose the fund list using today's data | Rebuilt point-in-time |
| 13 | The broker never read its own settings and would have failed every live run | Tried to actually connect |
| 14 | The position filter ran after balancing, leaving the book lopsided | Checked the sum of the first live order set |
| 15 | The scheduler called a command that does not exist | Tested the scheduled path, not just the strategy |
| 16 | Reported the control experiment as trading when it had only done a dry run | Read the log properly instead of trusting our own summary |

**Six of these, numbers 3, 6, 7, 8, 9, and 13, were caught because a control
group or sanity check produced an impossible number.** Not because we were
clever, but because we had built something that had to come out a certain way and
it did not.

That is the entire argument for negative controls. They do not find your edge.
They find the times you were about to fool yourself.

---

## Part 7: What we learned that transfers

**Costs do not diversify while volatility does.** Add more strategies and
volatility falls, but costs are subtracted in full from every one, so the cost
drag measured in Sharpe *grows* as you add more. This is what killed our best
combination idea, which had a gross Sharpe of +1.03 and a net of −0.16.

**A configuration chosen on net Sharpe is really chosen on a turnover estimate,
and turnover is the unstable part.** Our sealed holdout failed on exactly this
while the signal itself improved out of sample.

**Test the deployed path, not just the logic.** Three of our bugs (the broker
port, the scheduler flag, the missing strategy class) were invisible to research
testing and would only have appeared as live failures.

**Check the data exists before designing around it.** We built an entire research
night around holdings history and then discovered no archive exists. Twenty
minutes of checking would have redirected the whole night earlier.

**Be suspicious of good news specifically.** Every one of our false discoveries
looked excellent first, with t-statistics of 25 and recoveries of 414%. The bad
results never fooled us.

**A strategy's value is its contribution to the whole book, not its own score.**
A mediocre strategy that makes money on different days than everything else is
worth more than a good one that moves in lockstep with what you already own.

---

## Part 8: Where this leaves us for the school year

**Settled.** The signal is real and has survived every control we could build. The
infrastructure works: it schedules itself, checks itself, halts itself, and
reports honestly, including reporting its own failures.

**Open and important.**

1. Does market-on-close bring slippage inside tolerance? Everything depends on
   this and we have zero sessions of evidence on it.
2. Get the broker connection reliable so sessions actually trade. One day of live
   data is not a live track record.
3. Reach 60 sessions and run the pre-committed review honestly.
4. Build a defence against distribution cuts, which permanently re-rate a
   discount wider and are the classic way this strategy loses money.
5. Resize the books. They are 158% committed against account equity, which the
   margin check backstops but does not fix.
6. Pre-register the January closed-end fund basis trade properly. It shows +11.71
   basis points a day in January with a t of 3.99, positive in 20 of 23 years, and
   a correlation with the main strategy of −0.001. Combining a 0.82 and a 0.73 at
   zero correlation gives 1.10, which is a larger gain than any plausible
   improvement to the main strategy. It has five months of lead time, so there is
   no excuse to rush it.

**The honest summary.** We have one strong signal, one working machine, one day of
live evidence, and one very large unanswered question about whether we can afford
to trade it. That is a good place to start a year from, and a bad place to claim
success from.
