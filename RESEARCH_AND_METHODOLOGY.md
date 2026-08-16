# How We Do This: Research, Methodology, and What We Found

**QUANTT credit strategy programme · written 31 July 2026**

This document assumes you know nothing about finance. Every term is explained the
first time it appears, in ordinary words, in the sentence where you meet it. If a
sentence needs jargon to make sense, it is a badly written sentence and should be
rewritten rather than footnoted.

It is long on purpose. It covers what we are trying to do, how we decide whether
something is real, everything we tried, why almost all of it failed, the one idea
that worked, and exactly how confident we are.

---

# PART ONE — THE BASIC IDEA

## 1.1 What we are trying to do

We want to find a repeatable way to make money in **credit** — that is, in the
market for lending money to companies — that does not depend on the market going
up.

That last clause is the whole difficulty. Anyone can make money in credit when
credit does well: you buy risky company loans, you collect the interest, and in a
good year you are up. That is not a skill. It is called **taking risk premium** —
being paid for holding something risky — and you can buy it for a few dollars in
fees through any fund.

We want something different: a strategy where we make money whether the credit
market rises or falls, because we are betting on a *relationship* between two
things rather than on the direction of anything.

## 1.2 The words you need

**Bond.** An IOU. A company borrows money and promises to pay it back with
interest. You can buy and sell these IOUs.

**Credit.** The whole market of these company IOUs. "Investment grade" means the
borrower is considered safe. "High yield" (or "junk") means riskier, paying more
interest to compensate.

**Fund.** A basket holding hundreds of bonds. You buy one share of the basket
instead of buying hundreds of bonds yourself.

**Net asset value, or NAV.** What the stuff inside the basket is worth. Funds
publish this every day. If a fund holds $100 million of bonds and has issued 10
million shares, the NAV is $10 per share.

**The price.** What people actually pay for a share of the fund on the stock
exchange. This is *not* automatically the same as NAV.

**The discount (or premium).** The gap between the two. If the stuff inside is
worth $10 and the share trades at $9.20, the fund trades at an 8% *discount*. At
$10.70 it trades at a 7% *premium*.

**Long and short.** "Long" means you own something and profit if it rises.
"Short" means you have borrowed and sold something, so you profit if it falls.

**Dollar-neutral.** You have put exactly as much money into longs as into shorts.
If the whole market moves, your gains and losses cancel and you are left with only
the difference between your specific picks.

**Sharpe ratio.** Return divided by how bumpy the ride was. It answers "how much
did I get paid per unit of stomach-churning?" A Sharpe of 0.5 is ordinary. 1.0 is
good. Anything claimed above 2.0 in a backtest is usually a mistake.

**Backtest.** Running a strategy against historical data to see what it would have
done. Backtests lie constantly, which is what most of this document is about.

**Basis point (bp).** One hundredth of one percent. 100bp = 1%. Used because the
numbers we care about are often tiny.

## 1.3 Who has to lose for us to win

This is the question we ask before building anything, and it is the one most
people skip.

Markets are not machines that hand out money. If we are making money on a trade,
somebody is on the other side of it, and they are losing. If we cannot name that
person and explain why they keep doing it, then either we have not understood the
trade, or we are the one losing and have not noticed yet.

A good answer sounds like: *"Pension funds are contractually forbidden from
holding this bond after it is downgraded. They must sell it within days,
regardless of price. They are not stupid — for them, breaching the mandate is a
much bigger problem than the half percent they give away."*

A bad answer sounds like: *"The market is inefficient."* That is not an answer,
it is a shrug.

---

# PART TWO — HOW WE DECIDE IF SOMETHING IS REAL

This is the most important part of the document. The strategy matters less than
the method, because the method is what stops us fooling ourselves.

## 2.1 The core problem: backtests lie

If you test enough ideas against the same history, some will look brilliant purely
by luck. Test a thousand random strategies and the best one will look superb —
and it will be worthless, because you selected it *for* having got lucky.

This is not a small effect. There is a formula for it: if you try **N** ideas, the
best one will score roughly `√(2 × ln N)` even if every single one is pure noise.

- Try 10 ideas → the luckiest scores about **2.1**
- Try 100 ideas → about **3.0**
- Try 162 ideas → about **3.2**

We have run 162 tests on our original data. So on that data, a strategy would need
to score above 3.2 before we could say it was anything but luck. Our best scored
0.37. That is why we abandoned that entire line of work.

**What we do about it:** we keep a permanent count of every test ever run, in a
file called `RESEARCH_STATE.md`. It never resets. Every result is judged against
the running total, not against one.

## 2.2 The seven ways a strategy can fail

"It didn't work" is not a diagnosis and cannot be acted on. We classify every
failure into one of seven types, because the correct response is different for
each, and the wrong response wastes weeks.

| code | what happened | what it means | what to do |
|---|---|---|---|
| **D1** | No edge even *before* trading costs | The effect does not exist | Kill it. No amount of tuning creates something from nothing |
| **D2** | Edge exists but costs eat it | A trading problem, not an idea problem | Trade less often, in bigger, better-chosen bets |
| **D3** | Great in old data, bad in new | Either overfitted, or the world changed | Check if the *mechanism* still holds. If yes, it's a regime shift. If no, we fooled ourselves |
| **D4** | Good numbers, but it's just market exposure | A risk premium wearing a costume | Demote it. It is not skill and must never be counted as skill |
| **D5** | Everything passes, Sharpe 0.3–0.6 | **This is not a failure. This is inventory** | Keep it. Several mediocre-but-different strategies beat one good one |
| **D6** | Works in one environment, not others | A conditional strategy, correctly identified | Only run it when its environment is present, and size it accordingly |
| **D7** | Fewer than ~250 independent trades | Not a result at all | You cannot conclude anything. Get more instruments, not more history |

D5 deserves emphasis because it is the most expensive mistake available. A
strategy with a Sharpe of 0.5 sounds disappointing. But five *unrelated* strategies
each at 0.5 combine to about 1.1 — because their bad days do not line up. Throwing
away 0.5s while hunting for a 1.5 is how people end up with nothing.

## 2.3 The tests every candidate must survive

**Negative controls.** This is the single most valuable technique we use.

Every strategy has a story about *why* it works. That story implies places where
it *cannot* work. We test there too, and the strategy must fail.

For example: several of our ideas relied on bond prices being out of date. US
government bonds trade constantly on a live screen, so their prices are never out
of date — the mechanism physically cannot operate there. So we ran every signal on
government bond funds as well. If a signal works on government bonds, it is not
what we think it is, and we throw it away no matter how good the numbers look.

This caught two false discoveries that we would otherwise have deployed.

**The mechanism chain.** A story implies intermediate steps. We test the steps,
not just the outcome. If the story is "forced sellers push prices down, then
prices recover," then we must separately observe: the forced selling happening, the
price falling, and the price recovering. A strategy that makes money but fails its
own mechanism chain is one we do not understand and therefore cannot size.

**The carry-and-beta test.** This checks whether an apparent skill is secretly
just market exposure. We take the strategy's daily returns and ask how much of
them are explained by simply owning high yield, owning investment grade, owning
government bonds, owning shares, or being exposed to market fear. If most of it is
explained that way, it is not skill — it is something you can buy for a few
dollars in fees, and we must not dress it up as alpha.

**Walk-forward testing.** Rather than judging on the whole history at once, we cut
it into consecutive blocks and check each separately, with a gap between blocks so
that overlapping trades cannot leak information across the boundary.

**Bootstrap.** We resample the returns thousands of times — in contiguous chunks,
to preserve the fact that calm days cluster together and wild days cluster
together — and see how often the result comes out positive.

**Point-in-time discipline.** Every calculation may only use information that
existed at the time. This sounds obvious and is violated constantly. Our own worst
example: we picked our list of funds using *today's* trading volumes, which
silently excluded every fund that had since died. Rebuilding it properly — so that
each historical day only knows what was knowable that day — is described in §5.4.

**Cost realism.** Every trade is charged the actual measured cost of trading that
specific instrument. Not an assumption. We measured real bid-ask spreads through
our broker for 29 funds and use those numbers.

## 2.4 The null trader: checking our own scales

Before trusting any result, we needed to know our measuring apparatus was honest.

So we built a strategy that picks its trades **completely at random** and put it
into the live system. It runs through exactly the same path as a real strategy:
same order routing, same fill assumptions, same profit-and-loss accounting.

A random strategy should lose precisely what trading costs and nothing more. If it
*makes* money, then our accounting is flattering us somewhere, and every result we
have ever produced is fiction.

**Result: it lost 20.68% a year against a modelled cost of 21.2% a year, with a
before-cost Sharpe of −0.39, which is statistically zero.** The machinery is
honest. This is the least glamorous thing we built and one of the most important.

## 2.5 Benchmarks: what "good" means

A strategy is only good relative to the easy alternative. So we built nine
reference books that run through the identical cost and accounting path — because
a benchmark that gets easier treatment makes any strategy look good.

| book | what it is | Sharpe |
|---|---|---|
| B1 | Just owning high yield | 0.35 |
| **B2** | **High yield with interest-rate risk removed** | **0.54** |
| B3 | The whole bond market | 0.29 |
| B4 | 60% shares / 40% bonds | 0.63 |
| B5 | Cash | 0.20 |
| B6 | Equal amounts of every credit fund | 0.48 |
| B7 | The naive version of one of our own ideas | 0.21 |
| B8 | The naive version of our other idea | 0.59 |
| B9 | The random null trader | −4.60 |

**B2 is the number that matters.** It is what you earn with zero skill: buy high
yield, cancel out the interest-rate risk, go to the beach. Any strategy that
cannot beat 0.54 has not earned its existence.

B7 and B8 matter for a subtler reason: they are the *stupid versions of our own
ideas*. Beating the market proves little. Beating the dumb version of your own
idea is the actual test of whether the sophistication earned anything.

---

# PART THREE — WHAT WE TRIED AND WHY IT FAILED

We tested thirteen distinct mechanisms. Twelve are dead. Here is the honest record,
because the failures contain more information than the success.

## 3.1 The big one: fund price versus fund value

**The idea.** Funds publish what they are worth (NAV) daily. Prices sometimes
differ. Buy when the price is below the value, sell when above, wait for the gap
to close.

**Why it failed, and this is the most useful thing we learned all week.**

The fund does not actually *know* what its bonds are worth, because most of them
did not trade today. It gets estimates from a pricing service, and those estimates
lag reality. So the published NAV is a **stale, smoothed** version of the truth.

We proved this. If a number is a smoothed version of reality, then today's change
predicts tomorrow's change, because the lag has to catch up. For HYG, the largest
high yield fund, over 19 years:

| measure | value |
|---|---|
| Does today's NAV change predict tomorrow's? | **+0.388 — strongly yes** |
| Does today's *price* change predict tomorrow's? | **−0.005 — no** |
| NAV bumpiness vs price bumpiness | 6.05% vs 9.51% |

That last row is the giveaway. **The published value of the fund appears to move
around less than the fund itself.** That is impossible for a true valuation. It is
the textbook signature of a number that is being smoothed.

So the "mispricing" we were trading was largely *the pricing service being slow* —
not the market being wrong. When the stale estimate finally catches up, the NAV
jumps and the gap closes, but the fund's price never moved. There was never
anything to trade.

We then confirmed it directly. Asking whether the gap predicts the fund's *price*
or the fund's *published value*:

| fund | predicts the published value | predicts the price |
|---|---|---|
| EMB | **t = +24.4** | +1.9 |
| ANGL | **t = +19.1** | +0.1 |
| HYG | **t = +15.3** | −2.3 |

(A "t" above about 2 means the effect is unlikely to be chance. Above 15 means it
is overwhelming.)

The gap predicts the paperwork catching up. It does not predict the price. **There
is nothing to trade.**

**And it decayed, for a reason we can name.** Ordinary funds (ETFs) have a repair
mechanism: large banks can hand in shares and receive the actual bonds, or vice
versa. So the moment a gap appears, they arbitrage it away. Over nineteen years
this competition compressed the gap:

| era | how smoothed the NAV was | size of the apparent gap | what the trade earned |
|---|---|---|---|
| 2007–10 | +0.580 | 187.9bp | 2.54% a year |
| 2015–18 | +0.303 | 5.6bp | 1.04% a year |
| **2023–26** | **+0.148** | **3.8bp** | **0.05% a year** |

Note what happened: the strategy's *Sharpe ratio* held up the whole time. The
*money* went to nothing. It did not start losing — **it stopped trading**, because
the gap shrank below the cost of crossing it. Five basis points a year is nothing.

**Verdict: D1.** Remember this table. It is the reason the successful strategy
works where this one didn't.

## 3.2 Forced selling by index funds

**The idea.** When a company's credit rating is cut from "safe" to "risky," a
large group of funds are *contractually forbidden* from holding its bonds. They
must sell, immediately, regardless of price. They are not selling because they
think the bond is overpriced — they are selling because their rules leave no
choice. That is forced, information-free selling, and it should push the price
below fair value temporarily.

**We found it. It is real and it is large.** We tracked 16,388 bonds through their
forced index removal between 2003 and 2025:

| business days from the forced sale | cumulative abnormal move | t |
|---|---|---|
| −10 | −235bp | −12.7 |
| **+2 (the bottom)** | **−424bp** | **−17.5** |
| +20 | −139bp | −5.6 |
| +60 | −2.8bp | −0.10 |

The bond falls 4.2% and then recovers essentially all of it. If the downgrade were
simply bad news, the price would fall and *stay* down. It does not.

The mechanism chain checks out at every link: customer selling pressure goes from
zero to +0.060 exactly in the window where the price is being crushed, then back to
zero as it recovers. And it is correctly conditional — in quiet months, when few
bonds migrate, the price falls and **keeps falling** (that is genuine company bad
news). In months when hundreds migrate at once, it fully recovers (that is
pressure). The mechanism knows the difference.

**But we cannot trade it, for two reasons.**

First, we cannot trade individual bonds at our size, so we would have to express it
through a fund. But a fallen-angel fund holds ~350 bonds and only ~104 are in the
recovery window at any time, so the signal is diluted to about one-fifth of the
surrounding noise. Empirically: holding such a fund against broad high yield with
**no signal at all** scores 0.37; adding our timing signal scores **0.03 to 0.24 —
strictly worse.** The premium is already sitting passively inside those funds, and
has been sold as a product since 2012.

Second, the regime where it is pure pressure rather than news occurred **4 times in
273 months** — about once every 5.7 years.

**Verdict: D4 (it is a risk premium in costume) with a D6 note (conditional).**
Real effect, not our trade.

## 3.3 The rest, briefly

| what we tried | verdict | why |
|---|---|---|
| Cross-sectional price patterns in credit funds | D1 | Negative edge even before costs |
| Per-bond staleness from issuer disagreement | D1 | Two issuers priced the same bond within **0.09bp** of each other — they buy from the same vendor, so comparison is blind |
| Fund creation/redemption flows | D1 | 28,025 observations, every t below 0.8. Informed and forced flow cancel out |
| Thin funds lagging liquid ones | D1 | Looked spectacular (t up to 25) until we measured returns at prices you can *actually trade at*. Then it went to −0.50, and the government-bond control scored **higher** than credit. It was an artifact of using a price that doesn't exist |
| Rebuilding fund value from real bond trades | D7 | Only 17–30% of a fund's holdings trade on a given day — too thin to represent the portfolio |
| Dealer balance-sheet pressure | D1 | Zero of nine credit funds significant at any horizon |
| Crowded short positions unwinding | D1 | Credit t-stats near zero; the control group scored higher |
| Pairs of similar funds converging | D2 + capacity | 22 pairs, near-zero correlation between them, **combined gross Sharpe +1.03**. But costs don't diversify while volatility does, so net fell to −0.16. And reaching our volatility target needed **32.8× leverage** against a ~2× legal limit |

That last one taught us something worth writing down: **diversification reduces
your volatility but not your costs.** Stack twenty uncorrelated low-volatility
strategies and the volatility falls by roughly √20, while the trading costs are
subtracted in full from every one. The cost drag, measured in Sharpe, therefore
*grows* as you add strategies. Combination is a powerful lever but it is not free.

## 3.4 An error we made and corrected

Our cost model had been charging **21.2% a year** to every candidate. That is a
huge hurdle and it was killing things.

It turned out to be an artifact of averaging across time. In 2007–2010 these funds
were young and thin, and trading them really did cost that much. Today it costs
**1.73bp per trade — about 3.7× cheaper.**

We had been charging 2007-era costs to 2024-era strategies, which manufactured an
obstacle that no longer existed. We fixed it.

**It rescued nothing**, and that fact is itself informative: our failures were
absence of edge (D1), not excessive cost (D2). Cheaper execution cannot save a
signal that was never there.

---

# PART FOUR — THE ONE THAT WORKED

## 4.1 The insight

Look again at the table in §3.1. The fund price-versus-value gap collapsed from
188bp to 3.8bp over nineteen years, because **banks are allowed to repair it.**
They hand in shares, get the bonds, sell them, pocket the difference. That
competition is what crushed the opportunity.

So the question becomes: **is there a kind of fund where nobody is allowed to
repair the gap?**

Yes. It is called a **closed-end fund**.

## 4.2 What a closed-end fund is

An ordinary fund can create and destroy its own shares on demand. If lots of
people want in, it makes more shares. That elastic supply is exactly what lets
banks arbitrage the price back to the value.

A **closed-end fund** issues its shares once, at launch, and then the share count
is **fixed forever.** No new shares. No redemptions. Nobody can hand in shares and
receive the bonds inside.

Think of a **sealed jar containing $100 of coins.** You can count the coins through
the glass — the fund publishes the contents daily. But you cannot open the jar. All
you can do is buy the jar from someone, or sell it to someone.

And because you cannot open it, the price drifts. When people are gloomy, jars
holding $100 sell for $92. When people are keen, they sell for $107. And those
gaps *persist*, because there is no mechanism to close them.

**We measured it across 44 credit closed-end funds:**

| | ordinary funds (ETFs) | **closed-end funds** |
|---|---|---|
| average gap | 0.04% | **−3.16%** |
| how much it varies | tiny | **5.95%** |
| 5th percentile | — | **−11.88%** |
| 95th percentile | — | **+7.11%** |

Roughly **150 times wider**, exactly as the no-repair-mechanism argument predicts.

## 4.3 The decisive test

Wide gaps are not enough. The ETF version failed because the gap closed by the
*paperwork* moving, not the price. We had to check which one moves here.

| | ordinary funds (dead) | **closed-end funds** |
|---|---|---|
| gap predicts the published value | **t = +15 to +24** ← the trap | +1.7 (weak) |
| gap predicts **the price** | ≈ 0 | **t = −1.75 average; 6 of 18 funds beyond −2** |

**This is the reversal that makes the strategy possible.** In an ordinary fund the
stale paperwork catches up to a price that was already right. A closed-end fund
cannot do that — its published value is computed the same way, but there is no
repair mechanism, so if the gap is going to close, **the price has to move.**

That is the entire thesis, and it is why this works precisely where the other one
died.

## 4.4 Ruling out the boring explanation

An obvious objection: maybe "trading cheap" just means "the price fell recently,"
and we have rediscovered short-term bounce-back, which is well known and heavily
competed.

So we ran both variables against each other. If the gap still predicts returns
*after* accounting for recent price moves, it is genuinely about the gap.

**11 of 18 funds kept a significant effect** (average t = −3.16). For several of
the largest — PDI, PTY, PCN, PDO — the recent-price-move term was insignificant
while the gap was overwhelming. It is the gap.

## 4.5 What the strategy actually does

Every day, for each of 17 credit closed-end funds:

1. Compute the gap between price and published value.
2. Compare it **to that fund's own normal gap** over the past year. This matters
   enormously — some funds *always* trade 10% below value. That is their normal,
   not a bargain. Ranking on the raw gap would just be a permanent bet on one type
   of fund over another, disguised as a signal.
3. **Buy** the funds unusually cheap for themselves. **Sell** those unusually dear.
4. Put exactly as much money long as short, so market direction cancels.
5. Rebalance every 5 trading days.
6. Scale the whole position to a constant level of risk (see §4.6).

Today's actual live position: long PDI, PCN, PTY, AWF, DSL, HYT, BIT, PDO; short
NVG, NAD, NEA, MHD, NZF, MQY, JFR, PFN. **$375,678 long against $375,784 short —
net $106, which is 0.014% of the position.**

## 4.6 The regime lesson, where we were wrong first

Our first instinct was: this strategy eats dislocation, so when markets are
dislocated we should trade *bigger*.

**We tested it and we were exactly backwards.** Sorting every day by how dislocated
the market was:

| market state | calm | | | | dislocated |
|---|---|---|---|---|---|
| Sharpe | **1.24** | 0.59 | 0.80 | **−0.23** | 0.68 |

The strategy is **best in calm markets.** In turbulent ones the returns get bigger
but the *volatility grows faster*, so the reward per unit of risk falls.

Sizing up into turbulence therefore levers into the worst possible state. That is
precisely what produced the strategy's disaster year: **2008 lost 12.9% with 35.8%
volatility and a 31.5% drawdown.**

The correct response is the opposite — **shrink when things get violent.** We
scale the position by the strategy's own recent volatility, targeting a constant
6% annual risk level. This cut the worst historical drawdown from **−27% to −12%.**

This is a good example of why we test the reasoning rather than trusting it. The
story "dislocation equals opportunity" is intuitive, plausible, and wrong.

---

# PART FIVE — HOW WE TESTED IT

## 5.1 The results

Over 5,427 trading days, from January 2005 to July 2026:

| measure | value | plain meaning |
|---|---|---|
| Sharpe ratio, after costs | **0.82** | Comfortably above the 0.54 benchmark |
| Return per year | **4.85%** | Before any leverage |
| Volatility | **6.00%** | A typical year moves ±6% |
| Worst peak-to-trough loss | **−12.0%** | The worst stretch in 21 years |
| Worst single day | −3.83% | |
| Best single day | +7.35% | |
| Winning days (of days it trades) | **51.5%** | Wins slightly more often than it loses |
| Average win vs average loss | 33.7bp vs −29.3bp | Wins are slightly bigger too |
| Trading costs | **5.2% of gross profit** | Costs are not the binding constraint |

## 5.2 Walk-forward: does it work in every period?

We cut the 21 years into 10 consecutive blocks and scored each independently.

**9 out of 9 measurable blocks were positive.** Median 1.12. The worst was 0.01 —
flat, not negative. There is no period in two decades where this lost money over a
two-year stretch.

## 5.3 Bootstrap: could this be luck?

We resampled the returns 5,000 times in contiguous 21-day chunks (chunks, not
individual days, so that the clustering of calm and wild periods is preserved).

- Observed Sharpe: **0.82**
- Middle 90% of resamples: **0.52 to 1.11**
- **Probability the true Sharpe is zero or below: 0.000%**

## 5.4 Survivorship: the bias we caught in ourselves

Our first version picked its 18 funds using **today's** trading volumes. That is
cheating twice over: it only considers funds that still exist in 2026, and only
ones that became liquid.

We rebuilt it so that each historical day sees only funds that were *already*
trading and *already* liquid on that day. No knowledge of the future.

**The result improved — from 0.72 to 0.82.** The correction admits more funds over
time (median 8, up to 25) while dropping illiquid ones dynamically. Bias
corrections usually go the other way, so this is genuinely reassuring rather than
merely survivable.

## 5.5 Multiple testing: haircut for everything we tried

We tried 10 different configurations on closed-end fund data. The luckiest of 10
pure-noise strategies would score about 2.15 on a t-statistic basis.

The formal calculation — the **deflated Sharpe ratio**, which adjusts for how many
things we tried, how long the sample is, and the fact that the returns are not
bell-curve shaped — gives **0.956.**

Read that as: **roughly a 95.6% probability the edge is real rather than the
luckiest of our attempts.** The conventional threshold is 95%. It passes, but not
by a wide margin, and it would not pass if we kept fiddling. That is why we stopped
searching.

## 5.6 Is it secretly just market exposure?

The most important test, and the one every previous candidate failed.

We regressed the strategy's daily returns against high yield, investment grade,
government bonds, the stock market, and market fear.

| | result | limit | |
|---|---|---|---|
| How much is explained by markets | **0.5%** | under 25% | ✅ |
| Skill (alpha) | **+2.68%/yr, t = 3.11** | t above 2 | ✅ |
| High yield exposure | +0.001 | under 0.10 | ✅ |
| Investment grade exposure | +0.007 | under 0.10 | ✅ |
| Government bond exposure | −0.008 | under 0.10 | ✅ |
| Stock market exposure | +0.017 | under 0.10 | ✅ |
| Market fear exposure | +0.002 | under 0.10 | ✅ |

**99.5% of this strategy's returns are not explained by any market we tested.**

For contrast, our previous best candidate had a high yield exposure of −0.163 and
an investment grade exposure of +0.123 — three times over the limit. It was a
disguised bet on credit quality. This is not that.

---

# PART SIX — WHAT IS RUNNING NOW

Everything is in a **paper trading account**. No real money is at risk.

| what | size | when it runs | what it is |
|---|---|---|---|
| **Closed-end fund strategy** | **$500,000** | weekdays 17:15 | The strategy. 17 positions, $751,463 gross |
| Null trader | $640,000 | weekdays 09:35 | Random-signal control. Checks our accounting is honest |
| 4 benchmark books | $80,000 | one-off | Reference points |

Both scheduled jobs are installed and confirmed running.

**Why $500,000 and not everything?** The null trader needs about $438,000 of margin
when it fires, and the account has $958,470 available. Taking the whole balance
would have breached margin. Size should rise only after we have measured how real
fills compare to modelled ones — that is a fact we don't have yet, not a matter of
confidence.

**The daily job refreshes prices and published values first, and aborts rather
than trading if that refresh fails.** The entire signal is price-minus-value, so a
stale value is not a cheap fund — it is a blind one. Any fund whose published value
is more than 3 business days old is dropped for the day.

## 6.1 The shutdown rule, written before it went live

Reviewed at **60 trading days, and not before** — so that we cannot talk ourselves
into changing our minds during a bad fortnight. Kill it if any of:

1. Live Sharpe is below zero.
2. Real trading costs exceed modelled costs by more than 2× for 5 consecutive days.
3. The gap between the cheapest and dearest funds falls below 12% — half its
   current 22.5%. That would mean the opportunity is closing the way the ETF one
   did.

Pre-committing this is the point. The moment to decide when to quit is *before* you
have money on it and a story about why this time is different.

---

# PART SEVEN — WHAT COULD GO WRONG

Stated plainly, because a research document that only lists strengths is marketing.

**1. It has fat tails.** The kurtosis is 41.2, which in plain terms means extreme
days happen far more often than a normal bell curve predicts. Worst day −3.83%.
Expect sharp, ugly single days. Do not read one as failure.

**2. It has been quiet for two years.** Nineteen years of strong results, but the
most recent walk-forward block scored 0.05 and the 2023–26 era scored 0.30. Either
this is a normal lull, or the opportunity is closing. **We cannot currently tell
the difference**, and that is exactly what the shutdown rule exists to resolve.

**3. Closed-end funds are less liquid than ordinary funds.** They trade $3–45
million a day, against $2 billion for the largest ETFs. Our position sizes fit
comfortably today, but this strategy cannot scale to very large amounts.

**4. Discounts can widen and stay wide for years.** The same absence of a repair
mechanism that creates the opportunity also means nothing forces it to close on any
schedule. In 2008 discounts blew out and stayed out for months.

**5. We have zero live fills.** Every cost number in this document is modelled,
carefully and from measurements, but modelled. Until we have real fills, the whole
cost model is unvalidated. This is the single biggest open risk and the first thing
the live period will settle.

**6. Deflated Sharpe of 0.956 is a pass, not a landslide.** It clears the
conventional 95% bar with little to spare. More fiddling with configurations would
push it below.

---

# PART EIGHT — WHAT WE DO NEXT

1. **Let it run 60 sessions.** No changes, no rescuing, no re-optimising. The
   shutdown rule decides.
2. **Measure real fills against modelled fills.** This validates or destroys the
   cost model underneath every result in this document.
3. **Quantify the scaling limit.** How much money can this hold before our own
   trading moves these relatively thin funds against us?
4. **Look for a second, unrelated strategy.** Per §2.2, two uncorrelated 0.8s beat
   one 1.0. The highest-value next research is something that makes money on
   *different days* than this does — not something that makes more money on the
   same days.
5. **Do not keep searching credit ETF prices.** 162 tests, the luck threshold is
   now 3.2, and the best real result was 0.37. That seam is mined out.

---

# APPENDIX — QUICK GLOSSARY

| term | plain meaning |
|---|---|
| **Alpha** | Return that isn't explained by simply owning markets. Actual skill |
| **Basis point (bp)** | One hundredth of a percent |
| **Beta** | How much you move when the market moves. Beta of 1 = you move with it |
| **Closed-end fund** | A fund with a permanently fixed share count. The sealed jar |
| **Discount** | The fund's price being below the value of its contents |
| **Dollar-neutral** | Equal money long and short, so market direction cancels |
| **Drawdown** | How far you fell from your best point. The pain measure |
| **ETF** | A fund that can create and destroy its own shares. The openable jar |
| **Gross exposure** | Total money at work, longs plus shorts added together |
| **Long / short** | Owning something / having sold something you borrowed |
| **NAV** | Net asset value. What the fund's contents are worth |
| **Point-in-time** | Only using information that existed at the time |
| **Sharpe ratio** | Return per unit of bumpiness. 0.5 ordinary, 1.0 good |
| **t-statistic** | How unlikely a result is by chance. Above 2 = probably real |
| **Volatility** | How much something bounces around |
