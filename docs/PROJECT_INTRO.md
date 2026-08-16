---
title: "QUANTT Credit Trading"
subtitle: |
  **Project introduction and open roles · 2026/27**\
  Simon Jarvis, team lead · simon.jarvis0@gmail.com\
  github.com/quanttqueensu/CreditTrading
compact: true
---

## The project

We operate a systematic credit strategy on a $500,000 Interactive Brokers paper
account. The capital is simulated; the prices, orders, fills and trading costs
are real.

The system runs unattended. Each weekday it refreshes its data, assesses whether
trading is safe, transmits its orders, records the executions, and raises an
alert on failure. This year we intend to keep it running, establish whether it
survives real trading costs, and research the next strategy.

## The strategy

A closed-end fund trades on an exchange but issues its shares once, after which
the share count is fixed. It publishes the value of its holdings daily as the
NAV, while the share price is set independently by the exchange. The two diverge.

In an ordinary ETF they do not, because large banks can exchange shares for the
underlying bonds and back, trading against any gap until it closes. We measured
this: the gap on high yield ETFs compressed from 188 basis points in 2008 to 3.8
by 2026, and that compression killed our first two strategies. Closed-end funds
have no equivalent mechanism, so the gap opens and persists.

Our strategy scores each fund's gap against that fund's own history over the
prior year, holds the unusually cheap funds long and the unusually rich funds
short in equal dollar amounts, and is therefore indifferent to market direction.

We spent much of the summer attempting to show this was a conventional exposure
in disguise. Against high yield, investment grade, interest rates, equity and
volatility, those five factors explain half a percent of the returns. The result
also held against the closed-end fund sector's own returns, the strongest control
we could construct.

## Current position

The signal is established. Trading costs remain the open risk.

The strategy must decide in the evening, because its signal requires the NAV,
which publishes after the close. On the first live day the orders rested
overnight and filled at 07:27, two hours before the exchange opened, when these
funds have negligible depth. We paid 0.94% to trade against a modelled 0.10%.
Priced at decision prices the book was up $50; priced at fills it was down
$7,350.

We moved to orders that execute in the closing auction, the deepest liquidity of
the day, but have not tested that change because the broker platform has been
down since August. Restoring it is our first priority.

One further correction should be stated before anyone joins. Our backtest assumed
an entry price that is not obtainable, and correcting it reduces the expected
Sharpe ratio from 0.82 to approximately 0.51. We would rather recruit against the
accurate figure.

New members do not start from nothing. The summer produced a daily feed of prices
for 11,423 bonds built from public filings at no cost, five scheduled jobs that
run the book unattended, and a written record of twelve strategy ideas that
failed, with the cause of each.

## Roles

No finance background is required. Our documentation covers the finance from
first principles.

**Quant Researcher, 2 to 4 positions.** Testing new strategy ideas and
establishing whether they are real. Most are not, and reaching that conclusion
quickly is the core skill; promising results are attacked before they are
reported. Requires Python and pandas, basic statistics including regressions and
t-tests, and the discipline to abandon a preferred idea when it fails a test.

**Execution and Infrastructure, 1 to 2 positions.** Ownership of the broker
connection, the schedulers, order flow, and the measurement of realised trading
cost. This area has produced more insight than any backtest, because live systems
fail in ways research code does not expose. Requires solid Python, patience with
silent failures, and ideally exposure to APIs or scheduled jobs.

**Risk and Reporting, 1 to 2 positions.** Weekly comparison of live performance
against backtest expectation across returns, exposures, drawdowns and slippage.
Requires basic Python and the ability to produce a concise written summary the
team will read.

## Goals and timeline

| Period | Objective |
|---|---|
| September | Recruit and onboard. Backtest reproduced on every machine; broker connection restored. |
| Oct – Nov | Accumulate 60 live sessions, then execute the review committed to in writing before launch. The strategy is shut down if it fails. |
| Dec – Jan | Pre-register the January trade, then run it. Positive in 20 of the past 23 Januaries and uncorrelated with the main strategy. |
| Feb – Apr | Continued research, a resizing decision based on live evidence, and the final report and handover. |

## Applications

Send a brief note stating the role of interest and any relevant work to
simon.jarvis0@gmail.com. The repository is public. `HOW_WE_GOT_HERE.md` is the
recommended starting point and assumes no finance background.
