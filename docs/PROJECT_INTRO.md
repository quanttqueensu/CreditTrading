---
title: "QUANTT Credit Trading"
subtitle: |
  **Project introduction and open roles · 2026/27**\
  Simon Jarvis, team lead · simon.jarvis0@gmail.com\
  Code and full write-ups: github.com/quanttqueensu/CreditTrading
compact: true
---

## What we do

Over the summer we built a small trading desk from scratch. It runs one credit
strategy on a $500,000 Interactive Brokers paper account. The money is fake.
Everything else is real: real prices, real orders sent to a real exchange, real
fills, real trading costs.

The system trades by itself. Every weekday it pulls new data, checks whether it
is safe to trade, sends its orders, records what came back, and raises an alarm
if something went wrong. This year we want to keep it running, find out whether
it survives real trading costs, and look for the next strategy.

## The strategy

A closed-end fund trades on an exchange like a stock, but it issues its shares
once and the count never changes afterwards. Every day it publishes what its
holdings are worth, a number called the NAV. The share price is separate, and the
two are often nowhere near each other.

With a normal ETF they stay close, because big banks can swap shares for the
bonds inside and back again, so they trade against any gap until it closes. We
watched that happen in our own data: the gap on high yield ETFs shrank from 188
basis points in 2008 to 3.8 by 2026, and that collapse killed the first two
strategies we tried. A closed-end fund has none of that machinery. Nobody can
open the basket, so the gap opens up and just sits there.

Our strategy compares each fund's gap to that fund's own history over the past
year. Unusually cheap funds we buy, unusually expensive ones we short, equal
money on each side, so it makes no difference whether the market rises or falls.

We spent much of the summer trying to prove this was an ordinary bet in disguise.
Tested against high yield, investment grade, interest rates, stocks and
volatility, those five explain half a percent of the returns. It also held up
against the closed-end fund sector's own returns, the hardest test we could
build.

## Where it actually stands

The signal looks real. The trading costs might still kill it.

The strategy has to decide in the evening, because it needs the NAV and the NAV
only comes out after the close. On our first live day the orders sat overnight
and filled at 7:27 in the morning, two hours before the exchange opened, when
almost nobody is trading these funds. We paid 0.94% to trade against a budget of
about 0.10%. Priced at the numbers the strategy decided on we made $50 that day.
Priced at what we actually paid, we lost $7,350.

We switched to orders that fill in the closing auction, the cheapest moment of
the day, but we have not tested that fix because the broker platform has been
down since August. Getting it back up is the first job of the year. One more
thing worth saying before anyone joins: our backtest assumed an entry price we
cannot really get, and correcting it takes the expected Sharpe ratio from 0.82
down to about 0.51. We would rather recruit people on the true number.

You would not be starting from a blank folder. The summer left a daily feed of
prices for 11,423 bonds built free from public filings, five scheduled jobs that
run the book unattended, and a written record of twelve strategy ideas that
failed and why.

## Roles we are hiring

No finance background is needed. Our documentation explains the finance from
scratch and assumes you know none of it.

**Quant Researcher, 2 to 4 people.** You test new strategy ideas and find out
whether they are real. Most are not, and getting to that answer quickly is the
skill. When a result looks great, your first job is to attack it. You need Python
and pandas, basic statistics such as regressions and t-tests, and the temperament
to drop your favourite idea when it fails a test.

**Execution and Infrastructure, 1 to 2 people.** You own the plumbing: the broker
connection, the schedulers, the orders going out, and the measurement of what our
trading really costs. This side has taught us more than any backtest, because
live systems break in ways research code never shows you. You need solid Python,
patience for things that fail silently, and ideally some experience with APIs or
scheduled jobs.

**Risk and Reporting, 1 to 2 people.** You watch the live book, and each week you
compare what the strategy did against what the backtest said it should do, across
returns, exposures, drawdowns and costs. You need basic Python and the ability to
write a short summary the team will actually read.

## Goals and timeline

| When | What |
|---|---|
| September | Recruit and onboard. Get the backtest running on every machine and the broker connection working again. |
| Oct – Nov | Build up to sixty live sessions, then run the review we committed to in writing before launch. If the strategy fails it, we shut it down. |
| Dec – Jan | Freeze the rules for the January trade, then run it. Positive in 20 of the past 23 Januaries, and it moves independently of the main strategy. |
| Feb – Apr | Keep researching, decide on resizing from live evidence, and write the final report and handover for next year's team. |

## To apply

Send a short note saying which role interests you and anything you have built, to
simon.jarvis0@gmail.com. Everything is public on GitHub if you want to look
first, starting with `HOW_WE_GOT_HERE.md`, the story of the summer including all
the wrong turns.
