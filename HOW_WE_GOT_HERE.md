# How We Got Here: The Full Record of the Work

**QUANTT credit strategy programme · written 31 July 2026**

This is the story of the work itself — what we did, in what order, why we made
each decision, what we got wrong, and how we caught it. It is a companion to
`RESEARCH_AND_METHODOLOGY.md`, which covers *what* we found. This one covers *how
we got there*, including the wrong turns, because the wrong turns are most of it.

Written in plain English. No finance knowledge assumed.

---

# PART ONE — WHERE WE STARTED

## 1.1 The situation

We had a goal: build a systematic credit strategy. "Systematic" means the rules
are fixed in advance and a computer follows them — no judgement calls, no
discretion, no "it felt like the right time." "Credit" means the market for
lending money to companies.

The target was double-digit annual returns at 12–15% volatility, market-neutral —
meaning we should make money whether the market goes up or down.

We had two prior attempts, both of which had just died:

**Attempt one (`credit_rv`)** looked for funds that had drifted away from where
their peers said they should be. We sealed away three years of data, ran the
strategy on it once, and it returned a Sharpe of **−1.44**. Worse, its edge was
negative *before* we even charged trading costs. There was nothing there at all.

**Attempt two (`E1`)** traded the gap between two high-yield funds' prices and
their published values. Out of sample it also lost money.

So we were starting from zero, with two corpses and a mandate.

## 1.2 What we already knew about our own plumbing

Before any research, we had established some unglamorous facts about the account
we would trade through. These mattered more than they sound:

- The account is a **paper account** (fake money) at Interactive Brokers, and it
  is denominated in **Canadian dollars**, not US dollars. Any US-dollar position
  sizing has to account for that.
- We have **no real-time market data subscription.** Quotes arrive 15 minutes
  delayed. So we cannot look at a live price when deciding — cost estimates have
  to come from historical measurement instead.
- **Historical bid-ask data does work**, through a separate entitlement. This is
  how we measure what trading actually costs.
- The standard Python library for talking to Interactive Brokers, `ib_insync`,
  **hangs forever** on our Python version. It looks exactly like a dead connection.
  We lost an hour to this before proving the connection was fine by opening a raw
  socket by hand. The fix is a maintained fork called `ib_async`.

That last item is a good illustration of a general principle: **a large fraction
of this work is not research, it is finding out that a tool is broken.**

## 1.3 The rules we agreed to work under

Two documents governed the work. Both came from you, and both were followed
literally rather than loosely.

**The overnight runbook** set the structure of a research night: fix the data
first, build the benchmarks second (non-negotiable, guaranteed deliverable), then
research, then an honest deploy-or-refuse decision, then a plain-English report.

Its most important line was this: **"A fabricated pass is the worst possible
outcome of this night — worse than deploying nothing."** That single sentence
determined the outcome of two of the three nights.

**The nightly iteration loop** set the rules for how nights should compound
rather than repeat:

- **Every night must add a new column to the data, not a new parameter to the
  model.** Searching the same data harder has brutally diminishing returns and
  raises the statistical bar for everything you will ever test afterwards.
- **Keep a permanent state file** that is read first and written last, so that
  night four doesn't re-test what night two already killed.
- **Classify every failure** into one of seven types. "It didn't work" is not an
  acceptable entry.
- **A strategy's value is its contribution to the whole book, not its own score.**
  A mediocre strategy that makes money on different days than everything else is
  worth more than a good one that moves in lockstep with what you already own.

---

# PART TWO — NIGHT ONE

## 2.1 The idea that opened everything

You made an observation that reframed the entire project:

> *"You're treating the ETF as a ticker. It's a portfolio whose exact contents are
> published daily, for free."*

Here is why that matters. A fund holding a thousand bonds publishes, every single
day, a complete list: every bond, and **the price of every bond.** For free. No
subscription.

We had been reading those files to find out *what* a fund owned. We had never
read them as **a source of bond prices.**

Take the union across fifteen funds and you have a daily price for several
thousand individual bonds — with no data licence and no delay. Our best bond
dataset at the time was 238 days out of date.

## 2.2 Testing the premise before building on it

The first thing we did was check the claim was true, because everything depended
on it. One command.

The obvious download link returned a web page instead of data. The working link
turned out to be a different path entirely (`latest-holdings.csv` rather than the
`.ajax` link the page itself advertises). Once found, it delivered **27 columns
including a price for every bond, plus duration, yield, sector, and maturity.**

The premise held. We built an ingester for fifteen funds.

**Result: 11,423 individually-priced bonds in a single day.** The target set by
the runbook was 3,000.

## 2.3 Three things that went wrong immediately

**We had two fund IDs wrong.** We were fetching what we believed was FALN, a
fallen-angel bond fund. It was actually the *iShares Low Carbon Optimized MSCI
ACWI ETF* — a stock fund. Another supposed bond fund was a completely different
Treasury fund.

We only caught this because the runbook says to print the full column set on the
first pull. The stock fund had no bond columns, which made it obvious. If we had
skipped that step, an equity fund would have sat inside our credit analysis
silently poisoning it.

**The fix:** the ingester now refuses to accept a fund whose published name
doesn't match what we expected. That check is load-bearing, not decoration.

**One of the runbook's ideas turned out to carry no information.** The plan was to
use disagreement between two issuers pricing the same bond as a staleness
detector — "nobody looks at this."

We looked. Across 1,132 bonds held by both iShares and State Street, the median
disagreement was **0.09 basis points.** They agree essentially perfectly.

The reason nobody looks at it is that there's nothing to see: both issuers buy
their prices from the *same* pricing vendor. Comparing them is like asking the
same person twice.

**The engine didn't balance at first.** Rebuilding each fund's value from its own
holdings matched the published value for most funds but was 1.80% off for the
largest one. We tracked it to securities lending: when a fund lends out its bonds,
the cash collateral it receives appears in the holdings file as an *asset*, but the
obligation to hand that cash back is a *liability* that isn't published. A level
offset, not a drift — which matters, because a constant offset doesn't affect a
strategy built on daily changes.

## 2.4 The blocker we could not engineer around

Then we hit the wall that shaped the whole night.

**The issuers publish today's holdings and nothing else.** There is no archive. We
tried passing a date parameter — it is silently ignored, and you get today's file
regardless.

So the panel we had just built started on 29 July 2026 and would grow by exactly
one day per day.

This meant the two strategies the runbook was built around — both needing a
*history* of bond-level holdings — could not be tested. Not "were hard to test."
Could not be, because the data did not exist and could not be bought.

**Decision made:** start the ingester running immediately anyway. It costs nothing
and in a year it becomes the only route to that test. Then pivot the night's
research to things that *were* testable.

## 2.5 The discovery that explained both prior failures

We needed to test the stale-price idea some other way. Nineteen years of published
fund values were sitting in our own data.

Here is the logic. If a published number is a *smoothed* version of reality — a
lagged average rather than the truth — then today's change predicts tomorrow's
change, because the lag has to catch up. That's a fingerprint you can test for.

We ran it on HYG, the largest high-yield fund, over nineteen years:

| | |
|---|---|
| Does today's published-value change predict tomorrow's? | **+0.388 — strongly yes** |
| Does today's *price* change predict tomorrow's? | **−0.005 — no** |
| How bumpy the published value looks vs the actual fund | **6.05% vs 9.51%** |

That last line is the smoking gun. **The published value of the fund appears to
bounce around less than the fund itself does.** That is impossible for an accurate
valuation of the same assets. It is exactly what you see when a number is being
smoothed.

Then we checked whether it had changed over time:

| era | how smoothed | size of the apparent opportunity |
|---|---|---|
| 2007–10 | +0.580 | 187.9bp |
| 2011–14 | +0.427 | 14.0bp |
| 2015–18 | +0.303 | 5.6bp |
| **2023–26** | **+0.148** | **3.8bp** |

**The two columns fall together because they were largely the same thing.** The
"opportunity" our previous strategies were trading was substantially the pricing
service being slow — and as pricing services got faster, it vanished.

We also confirmed the test discriminates: US government bond funds, whose prices
come from a live screen and cannot be stale, showed no smoothing in any era.

## 2.6 The sharpest way to see a strategy die

We ran the old strategy continuously through today's cost model and split it by era:

| era | Sharpe ratio | actual money made |
|---|---|---|
| 2007–12 | 0.75 | **2.54% a year** |
| 2013–18 | 2.64 | 1.04% a year |
| 2019–22 | 0.41 | 0.14% a year |
| 2023–26 | 0.48 | **0.05% a year** |

Look carefully. **The quality of the trade never deteriorated.** The Sharpe ratio
is as good at the end as the beginning. What collapsed was the *money*.

It did not start losing. **It stopped trading** — the gap it needed shrank below
the cost of crossing it, so the strategy simply sat there. Five basis points a year
is nothing.

This is a much more accurate death certificate than "it got competed away," and it
turned out to be the key that unlocked the eventual solution.

## 2.7 The benchmarks, and two bugs in our own accounting

The runbook's guaranteed deliverable was nine reference books, all running through
the *identical* cost and accounting path — because a benchmark that gets easier
treatment makes any strategy look good.

Building them exposed two accounting errors in our own machinery:

**Idle cash was earning interest and being counted as skill.** Books that held
mostly cash were collecting the risk-free rate on the idle balance and booking a
respectable Sharpe that was really just T-bill yield. Fixed by putting every book
on the same "excess of cash" basis.

**We were charging the risk-free rate to market-neutral books.** A book with equal
longs and shorts finances itself and owes nothing. Charging it made a genuinely
zero-edge strategy look negative. The tell was the random null trader showing a
before-cost Sharpe of −0.77 when it should have been zero. After the fix: −0.39,
which is statistically zero.

**Then the null trader passed its test**, and this was the reassuring moment of the
night. It lost **20.68% a year against a modelled cost of 21.2% a year.** A random
strategy losing exactly its costs and nothing more means our accounting is not
inventing profits — the failure mode that quietly destroys quant books.

## 2.8 The best research of the night, and why we still couldn't trade it

You had flagged that the strongest possible evidence is an *identification
argument*, not a Sharpe ratio. We took that seriously.

**The setup.** When a company's credit rating drops from "safe" to "risky," a
large group of funds are contractually forbidden from holding its bonds. They must
sell — immediately, regardless of price. Not because they think it's overpriced,
but because their rules leave no choice. The downgrade itself was public earlier
and already in the price. So the selling at the moment of removal is *mechanical
and carries no information.*

That separates price pressure from news, which is the hardest problem in this
field.

**The result, across 16,388 bonds from 2003 to 2025:**

| business days from forced sale | cumulative abnormal move | t |
|---|---|---|
| −10 | −235bp | −12.7 |
| **+2 (bottom)** | **−424bp** | **−17.5** |
| +60 | −2.8bp | −0.10 |

The bond falls 4.2% and recovers essentially all of it. News would push it down and
leave it there. This returns to where it started.

**Our first version of this was wrong**, and catching it matters more than the
result. The first run showed the price recovering **414%** of its fall — obviously
absurd. Two bugs:

1. **Survivorship.** Bonds that stopped trading dropped out of the sample. After a
   downgrade, the ones that stop trading are the distressed ones. We were left with
   only the survivors, and survivors recover.
2. **Broken event time.** We counted *trading days observed* rather than calendar
   days. For a bond that trades once a week, "60 days later" meant a year later.

Fixed both, then re-ran under five different sample definitions — including the
harsh one where a bond that vanishes is carried at its last price and *cannot*
recover. Recovery came out at **82–85%.** Real.

**But we couldn't trade it.** Bonds can't be traded at our size, so the only route
was a fund holding them. A fallen-angel fund holds ~350 bonds and only ~104 are in
the recovery window at once — the signal is diluted to about a fifth of the
surrounding noise. And measured directly: holding such a fund with **no signal at
all** scored 0.37, while adding our timing signal scored **0.03–0.24 — strictly
worse.** The premium is already sitting passively inside those funds and has been
sold as a product since 2012.

## 2.9 The decision: refuse to deploy

Nothing cleared. We deployed no strategy.

The runbook permitted deploying the best candidate at 10% size with a
"PROVISIONAL" tag. **We declined that too**, for a specific reason: the candidate's
measured market exposures showed it was a static bet on credit quality held
permanently. That is exactly the "get paid for taking risk" the mandate forbids.
Deploying it would not have been a small bet on an unproven idea — it would have
been a mandate breach dressed as research.

---

# PART THREE — NIGHT TWO

## 3.1 Four leads, and doing the cheapest one first

You gave four specific directions. We ordered them by *what would change the most
if true*, and one stood out:

> *"Audit the 21% cost figure before anything else. One of those two numbers is
> wrong, and if it's the cost model, it has been manufacturing a fake obstacle in
> front of every signal you've tested."*

That was exactly right to check first, because if our cost model was wrong then
every conclusion in the project was suspect.

**What we found was subtler than either of us guessed.** The cost *formula* was
accurate — we compared it against real measured bid-ask spreads and it matched to
within 1–2% on seven of eight funds.

The problem was the **sample**:

| era | trading cost per trade | cost per year |
|---|---|---|
| 2007–10 | 13.91bp | **42.5%** |
| 2015–18 | 4.49bp | 15.3% |
| **2023–26** | **1.73bp** | **5.9%** |

The 21.2% was an average dominated by 2007–2014, when these funds were young and
thin. **Today the same trading costs 3.7× less.** We had been charging 2007-era
costs to modern strategies — a fake obstacle, exactly as you suspected, just
living in the data rather than the formula.

We also found one genuine formula error: a "thin fund" penalty was over-charging
one fund by exactly 2.5×, when measurement showed it trades as tightly as the big
ones.

**And then the honest part: fixing it rescued nothing.** Because our failures were
*absence of edge*, not *excessive cost*. Cheap execution cannot save a signal that
was never there. Worth knowing, worth doing, and it changed no verdict.

## 3.2 Running four investigations at once

To use the night efficiently we ran several independent investigations in parallel
while working on the critical path ourselves. Three of the four returned genuinely
useful results, and two of them returned *corrections to our own assumptions*:

**Government filings (N-PORT).** You suggested these would break the archive
blocker, since every registered fund files its holdings with the regulator. This
worked — 136,268 rows going back to 2019, verified against today's live file at
95.3% overlap.

But two corrections came back that we would have got wrong: the public filings
contain **one** snapshot per quarter, not three monthly ones (the other two months
are filed non-public). And the "how hard is this to value" field we hoped to use is
**degenerate** — 135,850 of 135,870 corporate bonds carry the identical
classification, so it distinguishes nothing.

**Universe expansion.** We went from ~10 tradable instruments to 56. The
investigation also caught that our existing price panel's **final bar was a partial
intraday capture** — one fund showed 10.4 million shares traded against a settled
70.7 million. Using it would have injected a fake return on the most recent day.

**Positioning data.** Short-selling data from FINRA, daily, free — 26,116 rows.
Plus a useful negative: our financing file contains **no real borrowing-cost data
at all**; the numbers in it are fixed assumptions. Any strategy built on borrowing
costs was never possible from our data.

## 3.3 Six more mechanisms, six more deaths

**The premium/discount gap, across every fund we could price.** Your point that
"the edge didn't die, the opportunity did" was correct, and we measured it — the
gap is still 6 to 19 times the cost of trading in several funds.

But the decisive test killed it. The gap predicts **the published value catching
up** (t-statistics of 15 to 24), not the price. And where it predicts price at all,
the sign says the fund is correctly *leading* its own stale paperwork. Trading it
means betting against genuine price discovery.

**Funds lagging each other.** If a big liquid fund is where prices get discovered,
a thin fund holding similar bonds should lag it. This looked spectacular —
t-statistics up to 25.

Then we tested it at prices you can *actually trade at*. It collapsed from an
average of 5.20 to **−0.50**, and the government-bond control group scored *higher*
than credit. The whole thing was an artifact of measuring returns at the midpoint
of the day's price range — a number that exists in a spreadsheet and nowhere else.

**Rebuilding fund values from real bond trades.** Only 17–30% of a fund's holdings
trade on a given day, and falling. The bonds that do trade are the ones with news,
so they don't represent the portfolio. Infeasible.

**Dealer balance-sheet pressure**, **crowded short positions** — both dead, both
with control groups scoring as high as the credit group.

**Pairs of similar funds converging.** This one taught us something. We built 22
pairs and the combination worked exactly as your maths predicted: average
correlation between them of **+0.027** — essentially independent — and a combined
gross Sharpe of **+1.03**, the best number in the project.

Then it failed on two pieces of arithmetic:

1. **Costs don't diversify.** Volatility falls as you add strategies; costs are
   subtracted in full from every one. So the cost drag, measured in Sharpe, *grows*
   as you add more. Gross +1.03 became net −0.16.
2. **Capacity.** Combined volatility was 0.37%. Reaching a 12% target needed
   **32.8× leverage** against a legal limit near 2×.

## 3.4 Deploying the benchmarks, and two more broken things

We deployed five reference books to the paper account. Doing so surfaced two
defects that would have silently broken live trading:

**The broker adapter never read its own configuration.** The code that builds the
broker connection passed only two settings, so a hardcoded default port always won
— while the actual platform was listening on a different one. **Every live run
would have failed to connect, including the null trader's first scheduled run.**

**A whole category of strategy had no implementation.** The system accepted and
validated "fixed weight" strategy specs, then failed at run time because no code
existed to execute them.

**And a correction to something we'd told you.** We had reported the null trader as
deployed and trading. Reading its log properly showed it had run a *setup dry run*
and transmitted nothing. It had never traded — and until the port fix, it couldn't
have.

## 3.5 Where that left us

Thirteen mechanisms tested. Twelve dead. 162 cumulative tests on the original data,
which means the luck threshold — the score the best of 162 pure-noise strategies
would achieve — had risen to about **3.2.** Our best real result was 0.37.

The iteration loop's own stop condition had been met twice over: *"further search
on this data is close to worthless. The correct move is a fundamentally different
data source."*

---

# PART FOUR — THE PIVOT

## 4.1 One sentence changed the direction

> *"We can trade other mechanical but it has to be credit."*

We had been treating "credit strategy" as meaning "credit ETF strategy" without
noticing we'd made that substitution. The instruction removed a constraint we had
imposed on ourselves.

## 4.2 Working backwards from the failure

The most useful thing we knew was *why* the ETF version died, and we knew it
precisely:

Ordinary funds have a **repair mechanism**. Large banks can hand in shares and
receive the actual bonds, or hand in bonds and receive shares. So the moment the
price drifts from the value, they arbitrage it away. That competition compressed
the gap from 188bp to 3.8bp over nineteen years.

So instead of asking "what else can we trade?", we asked the sharper question:

**"Is there a kind of fund where nobody is allowed to repair the gap?"**

Yes — a **closed-end fund.** It issues its shares once, at launch, and the count is
fixed forever. No creation, no redemption, no way to open the basket.

A sealed jar of coins. You can count them through the glass, but you can't open it.
So the price drifts and *stays* drifted, because nothing forces it back.

## 4.3 The premise checked before building

Same discipline as night one — check the claim before investing in it.

| | ordinary funds | **closed-end funds** |
|---|---|---|
| average gap | 0.04% | **−3.16%** |
| variation | tiny | **5.95%** |
| 5th percentile | — | **−11.88%** |

**About 150 times wider**, exactly as the no-repair argument predicted.

## 4.4 The test that mattered

Wide gaps aren't enough — the ETF version had gaps too, and they closed by the
*paperwork* moving, not the price. We ran the identical test:

| | ordinary funds (dead) | **closed-end funds** |
|---|---|---|
| gap predicts the published value | **t = +15 to +24** | +1.7 (weak) |
| gap predicts **the price** | ≈ 0 | **t = −1.75; 6 of 18 beyond −2** |

**The result reverses.** In an ordinary fund, stale paperwork catches up to a price
that was already right. A closed-end fund can't do that — with no repair mechanism,
if the gap closes, the price has to move.

Then we ruled out the boring explanation — that "cheap" just means "fell recently,"
which is well-known and heavily competed. Racing the two against each other, **11
of 18 funds kept a significant effect**, and for the largest ones the recent-price
term was insignificant while the gap was overwhelming.

## 4.5 The first strategy ever to pass the market-exposure test

This is the test that had killed every previous candidate — checking whether
apparent skill is secretly just owning markets:

| | result | limit |
|---|---|---|
| explained by markets | **0.5%** | under 25% ✅ |
| skill | **+2.68%/yr, t = 3.11** | ✅ |
| all five market exposures | **5/5 within limits** | ✅ |

**99.5% of the returns are unexplained by any market we tested.** For contrast, the
previous best candidate was three times over the exposure limit — a disguised bet
on credit quality.

## 4.6 Being wrong about regimes, then fixing it

You pushed on two things: the gates were too strict, and we were probably applying
the idea suboptimally — think about regimes.

Both landed. The strictness was real: we'd set a bar of t ≥ 3.0, roughly a 0.1%
significance level. Standard practice is 2.0. We lowered it with that reasoning
stated.

On regimes, we formed a hypothesis and **it was exactly backwards.**

We assumed: this strategy eats dislocation, so trade bigger when markets are
dislocated. We built it, and results got *worse*. So we measured directly:

| market state | calm | | | | dislocated |
|---|---|---|---|---|---|
| Sharpe | **1.24** | 0.59 | 0.80 | **−0.23** | 0.68 |

**The strategy is best in calm markets.** In turbulence the returns get bigger but
the volatility grows faster, so reward per unit of risk falls. Sizing up into
dislocation levers into the worst state — which is precisely what produced 2008:
**−12.9% at 35.8% volatility with a 31.5% drawdown.**

The correct answer was the opposite: **shrink when things get violent.** Scaling to
constant risk cut the worst drawdown from **−27% to −12%.**

We also tested a second plausible improvement — matching funds only against similar
funds so their underlying bonds cancel. Sound reasoning, and **it made things
worse** (0.73 → 0.57). With only 18 funds across 5 categories, several categories
hold 2–3 members, so the matching threw away most of the comparison.

Two well-reasoned hypotheses, both wrong, both discovered by testing rather than
argument.

## 4.7 Catching bias in our own favour

Our fund list had been chosen using **today's** trading volumes. That is cheating
twice: it only includes funds that still exist, and only ones that became liquid.

We rebuilt it so each historical day sees only what was knowable that day.

**The result improved, 0.72 → 0.82.** Bias corrections normally go the other way,
which makes this genuinely reassuring rather than merely survived.

## 4.8 Knowing when to stop

At ten configurations tested on this data, we stopped searching.

The luck threshold at ten attempts is about 2.15. Our result clears it — the formal
calculation gives a **95.6% probability the edge is real.** But it clears without
much room, and every additional configuration would push it down.

**Stopping is a decision, and it was made deliberately.** The remaining work is
validation and live evidence, not more variants.

---

# PART FIVE — BUILDING IT FOR REAL

Research code and production code are different things. Research code runs once
under supervision. Production code runs unattended, every day, with money on it.

**What we built:**

- The strategy itself as a proper component the system recognises
- A validator that **refuses** a configuration with too few funds, an insane risk
  target, or a tolerance for out-of-date values wide enough to trade blind
- A daily data refresh that flags stale values and **aborts rather than trading**
  if it fails — the entire signal is price-minus-value, so a stale value isn't a
  cheap fund, it's a blind one
- A scheduled job, weekdays after the close
- The shutdown rule, written down **before** anything went live

**Two more bugs caught in the build:**

**The book was 0.37% net short.** The filter that drops tiny positions was running
*after* the balancing step, so removing one position left the book slightly
lopsided — precisely the market exposure this strategy exists not to have. Fixed by
filtering first, then re-balancing. Residual now 0.000001.

**The scheduler called a command that doesn't exist.** We used a flag the calendar
tool doesn't implement. It would have failed and silently fallen back to a default.
The default happened to be correct — but a live scheduler depending on a failing
command is how you get a wrong date six months from now. We only found it because
we tested the *scheduled path*, not just the strategy.

## 5.1 Sizing, and why not everything

Deployed at **$500,000**, not the full balance.

The reason is arithmetic, not caution: the null trader needs about $438,000 of
margin when it runs, and the account has $958,470 available. Taking everything
would have breached margin and one of the two would have failed.

Size should rise once we've measured how real fills compare to modelled ones. That
is a missing fact, not a confidence level.

---

# PART SIX — EVERY MISTAKE WE MADE

Collected in one place, because the pattern is the point.

| # | mistake | how it was caught |
|---|---|---|
| 1 | Compared a full bid-ask spread to a half spread, reported costs at half their true ratio | Re-derived the comparison from scratch |
| 2 | Two fund IDs pointed at completely wrong funds, one a stock fund | Printed the column set on first pull, as the runbook requires |
| 3 | Event study showed a 414% recovery — impossible | The number was absurd on its face |
| 4 | Survivorship: bonds that stopped trading dropped out, leaving only survivors | Re-ran under five sample definitions |
| 5 | Counted trading days instead of calendar days, so "60 days" meant a year for illiquid bonds | Same re-examination |
| 6 | Idle cash interest counted as skill | Costs came out **negative**, which is impossible |
| 7 | Charged financing to self-funding market-neutral books | Random strategy scored −0.77 when it must be 0 |
| 8 | Measured returns at a price that doesn't exist (midpoint of the day's range) | Re-tested at tradable prices; effect vanished |
| 9 | Used a changing hedge ratio on both sides of a comparison, creating fake momentum | Control group scored *highest*, which is impossible |
| 10 | Assumed dislocation means opportunity — backwards | Measured it by regime instead of assuming |
| 11 | Assumed matching similar funds would help — it hurt | Tested one change at a time |
| 12 | Chose the fund list using today's data | Rebuilt point-in-time |
| 13 | Broker never read its own settings; would have failed every live run | Tried to actually connect |
| 14 | Position filter ran after balancing, leaving the book lopsided | Checked the sum of the first live order set |
| 15 | Scheduler called a non-existent command | Tested the scheduled path, not just the strategy |
| 16 | Reported the null trader as trading when it had only done a dry run | Read the log properly instead of trusting our own summary |

**Six of these — numbers 3, 6, 7, 8, 9, 13 — were caught because a control group
or a sanity check produced an impossible number.** Not because we were clever, but
because we had built something that *had* to come out a certain way, and it didn't.

That is the entire argument for negative controls. They don't find your edge. They
find the times you were about to fool yourself.

---

# PART SEVEN — WHAT THE PROCESS ACTUALLY PRODUCED

**Data built from nothing:**
- Daily bond price panel: 11,423 priced bonds/day, free, accumulating
- Government filings: 136,268 rows of quarterly holdings, 2019–2026
- Universe: 10 → 56 tradable instruments
- Closed-end funds: 44 funds, 265,615 price rows, 232,799 value rows, back to 1986
- Positioning: 26,116 rows of daily short-selling data
- Refreshed feeds that were 212 and 113 days out of date

**Understanding built:**
- Why both prior strategies failed — measured, not guessed
- That our cost model had been charging 3.7× too much
- That forced selling by index funds is real and large, and why we can't trade it
- That costs don't diversify — a real limit on combining strategies
- That this strategy is best in calm markets, not turbulent ones

**Machinery built:**
- Nine benchmark books through one honest accounting path
- A random-signal control proving our accounting doesn't invent profits
- Two new strategy types implemented, validated, registered
- Two scheduled jobs running unattended
- A permanent state file so no future night re-tests a dead idea

**And one strategy**, deployed, that cleared every gate.

**The ratio is thirteen tested, one survived.** That is not a bad night's work
repeated three times — that is roughly what this process is supposed to produce. If
a research programme is finding edges more often than that, it is almost certainly
not testing them properly.

---

# PART EIGHT — WHAT WE'D DO DIFFERENTLY

**1. Check the data exists before designing around it.** We built an entire night's
plan around holdings history, then found there is no archive. Twenty minutes of
checking would have redirected the whole night earlier.

**2. Run the cost audit first, always.** It sat in front of every result for two
nights. It turned out not to change any verdict, but we couldn't have known that,
and until we checked, every conclusion was provisional.

**3. Test the deployed path, not just the logic.** Three of our bugs — the broker
port, the scheduler flag, the missing strategy class — were invisible to research
testing and would only have appeared in live failure.

**4. Write the shutdown rule before, not after.** We did this, and it is the single
cheapest piece of discipline available. The moment to decide when to quit is before
you have money on it and a story about why this time is different.

**5. Be suspicious of good news specifically.** Every one of our false discoveries
looked *excellent* first — t-statistics of 25, recoveries of 414%. The bad results
were never the ones that fooled us.
