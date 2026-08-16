# QUANTT Credit Trading — Project Intro and Open Roles

**2026–2027 school year · Team lead: Simon Jarvis (simon.jarvis0@gmail.com)**
**Code: https://github.com/quanttqueensu/CreditTrading**

## What this project is

Over the summer we built a small systematic trading desk from scratch. It runs a
market-neutral credit strategy on a $500,000 Interactive Brokers paper account.
It places its own orders every weekday on a schedule, checks its own safety
before every trade, records every fill, and raises an alarm if anything breaks.
No human touches it on a normal day.

This year the team's job is to keep that system running, judge the live strategy
honestly against rules we wrote down before launch, and research what comes next.

## The strategy, in plain terms

A closed-end fund is a fund whose shares trade on the exchange like a normal
stock, with one twist: the number of shares is fixed forever. The fund publishes
the value of everything it owns (the NAV) every day, but the share price can
drift far away from that value, because nobody can create or redeem shares to
pull it back. Credit closed-end funds trade about 3% below their stated value on
average, and that gap swings widely from fund to fund.

Our strategy compares each fund's gap to its own history. It buys the funds that
look unusually cheap, shorts the ones that look unusually rich, and waits for
the gaps to drift back. It holds equal dollars long and short, so it does not
care whether the market goes up or down. Across 20 years of backtests, 99.5% of
its returns are unexplained by moves in credit, rates, stocks, or volatility.

We are honest about the hard part. These funds are small and expensive to trade,
and our first live day proved that trading costs matter more than the signal. Our
first fills came in about nine times worse than modelled, which would be fatal if
it persists. We diagnosed the cause and fixed it, but we have not yet proven the
fix works. Measuring execution cost and getting it down is the largest single
piece of this year's work.

After correcting for an entry price the backtest assumed but we cannot actually
get, the honest expected Sharpe ratio of the live strategy is about 0.51, not the
0.82 recorded at deployment. We would rather recruit people with the real number.

## What already exists

You are not starting from zero. The summer produced:

- Data pipelines that pull prices, fund values, and bond-level holdings every
  day, including a free feed of 11,000+ individual bond prices daily
- A backtesting and accounting engine whose cost model was checked against real
  measured bid-ask spreads
- A fully automated daily trading loop: five scheduled jobs, seven safety checks
  before any trade, alerts by banner and email when something goes wrong
- A research process that tested 13 strategy ideas and killed 12 of them, each
  with a written cause of death. The survivor is what runs live today.

## Roles we are hiring

**Quant Researcher (2–4 people).** You test new strategy ideas against our
gating process. Most ideas die, and finding out why fast is the skill. You need
comfortable Python with pandas, basic statistics (regressions, t-tests, what
overfitting is), and the temperament to watch your favourite idea fail a test
and let it go. No finance background required; the docs teach it.

**Execution / Infrastructure (1–2 people).** You own the pipes: the broker
connection, the schedulers, the order flow, and the measurement of what trading
actually costs us. You need solid Python and patience for debugging things that
fail silently. Experience with APIs, cron/launchd, or any production system is a
plus. This role has taught us more than any backtest.

**Risk / Reporting (1–2 people).** You watch the live book. Weekly you compare
what the strategy did against what the backtest said it should do: returns,
exposures, drawdowns, and slippage. You need basic Python and the ability to
write a clear, plain-English summary that the whole team reads. This is the role
where you learn how a real desk stays honest.

## Goals and timeline

- **September.** Recruit and onboard. Everyone runs the backtest on their own
  machine and reads the summer report. Get the broker connection reliable again,
  since the system has not traded since 2026-08-01 (the broker platform needs a
  daily human login, and automating around that is job one).
- **October to November.** Accumulate live sessions. The strategy reaches its
  60-session review, where we check live performance and slippage against rules
  we committed to in writing before launch.
- **November–December.** Pre-register the January trade (a second, small
  strategy that only trades once a year, in January) so the rules are frozen
  before any money moves. Begin research on the next data sources.
- **January.** Run the January trade.
- **February–March.** Continue research. Decide whether the main book gets
  resized based on measured live evidence.
- **April.** Final report: live results versus backtest, everything we learned,
  and a handoff document for next year's team.

## What you get

End-to-end experience running a live systematic book: signal research, honest
backtesting, execution, and risk. Most students see one of these pieces in a
course. Here you see all of them connected, with real (paper) money moving every
day, and you inherit the written record of 12 dead ideas so you can learn from
failures you didn't have to pay for.
