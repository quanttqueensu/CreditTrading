# What we found overnight, 30 July 2026

**We do not have validated alpha this morning.** Nothing cleared the gate, so
nothing new was deployed. What follows is what we ruled out, what the evidence
actually showed, and the shortest path to an answer.

That is not a wasted night. We found a real, strongly-measured market effect,
proved it is genuinely caused by forced selling rather than by news, and then
showed that we cannot capture it with the instruments we are allowed to trade.
Knowing *why* something does not work is worth more than a fourth strategy that
backtests well and then loses money.

---

## 1. What we are betting on, in one paragraph

An exchange-traded fund, or ETF, is a single share you can buy that represents a
basket of hundreds of bonds. It trades on the stock exchange all day, like a
share. The bonds inside it mostly do not — a typical corporate bond changes hands
a few times a week, or less. That mismatch is the source of everything we look
for: the wrapper moves continuously while its contents move in fits and starts,
and the gap between the two is sometimes a genuine mispricing you can trade
against. Our bet is that we can identify moments when the fund's price is wrong
relative to what it actually owns, buy the cheap side, sell the expensive side,
and hold nothing directional in between.

## 2. Who is on the other side, and why they keep losing

For this to work, somebody has to be losing money on purpose, or at least
knowingly. There is such a group, and we measured them directly last night.

When a company's credit rating is cut from "investment grade" to "high yield" —
from the safe tier to the risky tier — a large set of investment funds are
**contractually forbidden** from continuing to hold its bonds. Their rules say
investment grade only. So they must sell, immediately, regardless of price. They
are not selling because they think the bond is overpriced. They are selling
because their mandate leaves them no choice.

They keep doing it because for them it is not a trade, it is compliance. A
pension fund that breaches its mandate has a much bigger problem than the half a
percent it gives away on the way out.

**We measured this happening.** Around these forced sales, the customers on the
other side of dealers flip from balanced to net sellers — an imbalance of 0.060
in the three days around the event, against roughly 0.000 in the weeks before and
after. The forced selling is visibly there, exactly when the rules say it must be.

## 3. Why our two previous attempts failed — this is the important part

Both earlier strategies tried to trade the gap between an ETF's market price and
its **net asset value**, or NAV — the fund's own daily statement of what its
bonds are worth. Buy the fund when it trades below the value of its contents,
sell when above. Both lost money out of sample.

The old explanation was that competition had eaten the opportunity. **The
evidence says something different and more useful.**

The fund does not *know* what its bonds are worth, because most of them did not
trade today. It gets prices from a pricing service, which estimates them. Those
estimates lag. So the published NAV is a **smoothed, stale** version of the truth.

That has a fingerprint, and we tested for it. If a number is a smoothed version of
reality, today's change predicts tomorrow's change — the lag has to catch up.
Here is high yield's flagship fund, HYG, over 19 years:

| measure | value |
|---|---|
| NAV daily change predicting the next day | **+0.388** |
| the fund's own market price, same test | **−0.005** |
| NAV volatility vs price volatility | 6.05% vs 9.51% |

The market price has no such pattern — it is a real price, set by real trades. The
NAV does, strongly. And the NAV appears **less volatile than the fund that holds
it**, which is impossible for a true valuation and is the classic signature of a
smoothed number.

So the "mispricing" our old strategies were trading was substantially **the
pricing service being slow, not the market being wrong.** When a stale estimate
finally catches up, the NAV jumps and the gap closes — but the ETF's price never
moved, so there was never anything to trade. That is why the backtest showed a
reliable-looking pattern and the live result was negative.

**And the effect has been decaying, in lockstep, as pricing services got faster:**

| period | NAV staleness | size of the apparent "mispricing" |
|---|---|---|
| 2007–10 | +0.580 | 187.9 bp |
| 2011–14 | +0.427 | 14.0 bp |
| 2015–18 | +0.303 | 5.6 bp |
| 2019–22 | +0.289 | 4.4 bp |
| 2023–26 | **+0.148** | **3.8 bp** |

The two columns fall together because they were substantially the same thing.

**The clearest way to see the death** is what the old strategy actually earned,
run continuously through today's cost model (chart `results/bench/charts/01`):

| period | its Sharpe ratio | its actual return |
|---|---|---|
| 2007–12 | 0.75 | **2.54%/yr** |
| 2013–18 | 2.64 | 1.04%/yr |
| 2019–22 | 0.41 | 0.14%/yr |
| 2023–26 | 0.48 | **0.05%/yr** |

The quality of the trade looks fine throughout. The *money* is gone. The strategy
did not start losing — it stopped trading, because the gap it needed shrank below
the threshold that makes it worth crossing. Five basis points a year is nothing.

## 4. What we built last night

**The insight we acted on:** an ETF is not a ticker with a price. It is a
portfolio whose exact contents the issuer publishes every single day, for free,
and almost nobody reads carefully as a *price source*. iShares posts every bond in
HYG with its price, duration and yield, daily.

We built an ingester for that. It now pulls **15 funds**, normalises three
issuers' incompatible file formats to one schema, and produced a panel of
**11,423 individually-priced corporate bonds** for a single day — free, with no
data licence and no lag. Target was 3,000.

Two things we learned immediately, one of which killed part of the plan:

- **The engine reconciles.** Rebuilding each fund's NAV from its own holdings
  matches the issuer's published NAV to within 0.07% for 10 of 12 funds. HYG is
  1.80% off, which we traced to securities lending: the cash collateral the fund
  holds appears as an asset in the file, but the matching obligation to give it
  back is a liability that is not published. That is a level offset, not a drift.
- **Comparing two issuers' prices for the same bond does not measure staleness.**
  The plan was to use disagreement between issuers as a staleness detector. We
  measured it on 1,132 bonds held by both iShares and State Street: the median
  disagreement is **0.09 basis points**. They agree almost perfectly, because they
  buy their prices from the same vendor. That input is dead.

**The honest limitation:** the issuers publish today's holdings and nothing else.
There is no archive, and the date parameter on the endpoint is ignored. So this
panel starts on 29 July 2026 and grows by one day per day. **Any strategy that
needs a history of bond-level holdings cannot be tested yet.** It will be testable
in roughly a year. We started the clock last night; that is the main durable asset
built.

## 5. The evidence

**Test 1 — mechanism chain.** For the forced-selling story, every link held. The
selling shows up in the flow data when the rules say it must (imbalance 0.000 →
0.060). The price falls. The price recovers. For the stale-NAV story, the chain
broke at the first link: staleness in the funds we can actually trade is now
+0.038 for HYG in 2023–26, statistically indistinguishable from zero. There is
nothing left to correct. **We killed that strategy on mechanism, before spending a
backtest on it.**

**Test 2 — negative controls. PASSED, repeatedly.** US Treasury bonds trade on a
continuous screen market, so their prices cannot be stale and no Treasury is ever
forced out of an index by a downgrade. Every effect we found had to be absent
there, and was: Treasury NAV staleness is 0.000 to −0.106 in every period, and the
forced-flow strategy run on a Treasury pair returns a Sharpe of 0.00 to 0.07. The
tests discriminate. This is what stops us fooling ourselves.

**Test 4 — the identification argument. This is the strongest result of the
night.** We took 16,388 bonds that were forced out of investment grade between
2003 and 2025 and tracked them against comparable bonds:

| business days from forced sale | cumulative abnormal move | t-statistic |
|---|---|---|
| −10 | −235 bp | −12.7 |
| **+2 (bottom)** | **−424 bp** | **−17.5** |
| +20 | −139 bp | −5.6 |
| **+60** | **−2.8 bp** | **−0.10** |

The bond falls 4.2% and then **recovers essentially all of it.** If the downgrade
were simply bad news, the price would fall and stay down. It does not. It returns
to where it started. That is price pressure — the temporary cost of everyone being
forced through the same door at once — and almost nothing else produces this shape.

We attacked this result hard, because our first version of it was wrong. The first
run showed the price recovering 414% of its fall, which is absurd. Two bugs: bonds
that stopped trading were silently dropping out of the sample (the distressed ones,
leaving only survivors), and "60 days later" meant a year later for a bond that
trades weekly. Fixed both. Then we re-ran it five ways, including the version where
a bond that vanishes is carried at its last price and *cannot* recover:

| sample definition | bonds | bottom | recovery |
|---|---|---|---|
| survivors only (headline) | 2,724 | −424 bp | 99% |
| **dropouts held flat — the honest test** | **3,163** | **−460 bp** | **82%** |
| **dropouts held flat, no filters** | **4,285** | **−393 bp** | **85%** |

It survives. Roughly 60–80 bp of the fall is permanent — real news — and **330–380
bp is temporary pressure that fully reverses within three months.**

**Test 3 — does the effect grow with the thing that supposedly causes it?** The
mechanism names one driver: the volume of forced selling. So the effect must be
stronger when more bonds are forced out at once. We sorted every event by how many
bonds migrated in the same month:

| forced selling that month | events | bottom | after 3 months | recovered? |
|---|---|---|---|---|
| **under 25 bonds (quiet)** | 794 | −289 bp | **−353 bp** | **no — it keeps falling** |
| 25–100 bonds | 849 | −461 bp | −101 bp | 78% |
| 100–400 bonds | 1,110 | −307 bp | +115 bp | 137% |
| **over 400 bonds (crisis)** | 1,532 | −505 bp | −10 bp | **98%** |

**This is the cleanest confirmation of the mechanism we have.** In quiet months a
downgrade is one company having a bad time — that is genuine news, and the price
falls and *keeps falling*. In heavy months it is a wave of institutions all forced
through the same exit at once — that is pressure, and the price falls further and
then fully recovers. The mechanism does not just show up; it correctly separates
the cases where it should apply from the cases where it should not.

**And it is also why there is no trade here.** Months with over 400 migrations
occurred **4 times in 273 months — once every 5.7 years**: Ford and GM in May 2005,
Lehman in September 2008, April 2009, and December 2024. The regime where this is
a clean pressure trade rather than a news event arrives about as often as a
recession. You cannot size, validate, or run a strategy on four observations, and
you certainly cannot hold a 12–15% volatility book waiting years for one.

**Test 5 — not reached.** The strategy failed on Tests 3 and 7 before
cross-sectional out-of-sample testing would have been informative.

**Test 7 — carry and beta. FAILED, and this is what kills it.** The tradable
version's apparent profit is not a microstructure edge. It is a systematic tilt:

| | best candidate | gate | result |
|---|---|---|---|
| alpha t-statistic | +1.98 | ≥ 3.0 | **FAIL** |
| high-yield exposure | −0.163 | ≤ 0.10 | **FAIL** |
| investment-grade exposure | +0.123 | ≤ 0.10 | **FAIL** |

Fallen-angel bonds are the best of the risky tier, so a fund holding them behaves
partly like a safe-tier fund. Being short high yield and long investment grade is
an exposure anyone can buy for a few basis points. It is not skill.

**Why the real effect is not tradable by us.** Bonds cannot be traded at our size,
so the only route is the ETF wrapper. The arithmetic defeats it: about 104 bonds
are inside the recovery window at any time against roughly 350 the fund holds, so
even capturing the entire effect perfectly gives about 416 bp a year — against
**5.3% of unrelated noise** from every other difference between the two funds. The
signal is real and it is one-fifth the size of the noise around it.

**And the decisive test:** holding the fallen-angel fund against high yield with
**no signal at all** scores 0.37. Adding our forced-flow timing signal scores
**0.03 to 0.24 — strictly worse.** The premium is already inside the fund's return,
passively, and has been sold as a packaged product since 2012. There is nothing
left to time.

## 6. How it compares

All ten books run through the identical cost model, fill assumption and accounting
path. If the benchmarks got easier fills the comparison would be worthless.

| book | net Sharpe | return/yr |
|---|---|---|
| 60/40 stocks and bonds | 0.63 | 6.73% |
| **B2 — high yield with interest-rate risk removed** | **0.54** | **5.21%** |
| equal-weight credit basket | 0.47 | 3.49% |
| just owning high yield | 0.35 | 3.29% |
| **B8 — the naive version of our own dead idea** | 0.59 | 1.11% |
| **B7 — the naive version of our other idea** | 0.21 | 0.51% |
| **our best candidate last night** | **0.37** | 1.86% |

**B2 is the number that matters.** It is what you earn with zero skill — buy high
yield, hedge out the interest-rate risk, go to the beach. Our best idea scored
0.37 against it. We did not beat doing nothing clever.

**B9, the null trader, passed its test,** and this is genuinely reassuring. It
trades a random signal through the live order path. It should lose exactly its
costs and nothing else. It lost 20.68% a year against a modelled cost of 21.2% a
year, with no skill either way (its before-cost score is −0.39, statistically
zero). **Our fill and accounting machinery is honest** — it is not inventing
profits, which is the failure mode that destroys quant books.

**One more sobering number.** Across the project we have now run 156 distinct
strategy trials. If all 156 were pure noise, the best of them would be expected to
score about **3.18** by luck alone. Our best real candidate scored 0.37.

## 7. What would make this stop working

The forced-selling effect is real but shrinking, and we can name the threats
concretely. Pricing services keep getting faster, which is already visible in our
own numbers and is what killed the previous two strategies. Dedicated fallen-angel
funds have grown since 2012 and exist specifically to stand on the other side of
this trade — every dollar they add absorbs more of the forced selling before the
price gets pushed. Bond trading is moving to electronic all-to-all venues, which
shrinks the cost of stepping in. And index providers have been adding grace
periods that let funds sell over weeks instead of on one date, which spreads the
pressure out until there is no spike left to trade.

## 8. Honest confidence

**That the forced-selling effect is real: about 90%.** It is measured on 16,388
events with a t-statistic of −17.5, it survives every robustness check we threw at
it including the ones designed to kill it, its negative control is clean, and the
flow data independently confirms the selling happens when the mechanism says.

**That we can trade it profitably at our size within a month: about 10%.** The
obstacle is not the signal, it is that we can only reach it through a wrapper that
adds five times more noise than the signal contains.

What would move the second number: direct access to the bonds (would raise it a
lot, and is not available to us); a wrapper concentrated enough in freshly-migrated
bonds to cut the noise (does not currently exist); or a way to hold the trade
through a multi-year wait for the next crisis regime without bleeding carry.

**We tested the crisis idea last night rather than leaving it open** (Test 3). The
pressure does spike in heavy-migration months, exactly as the mechanism predicts.
It just happens once every 5.7 years, which makes it a thing to be ready for, not
a strategy to run.

## 9. What we did not get to, ranked by expected value

1. **Bank loans.** Loans settle in about 20 days and are marked from dealer
   quotes, not trades, so they are the stalest asset class in credit by
   construction. We fetched SRLN's holdings last night but have not measured it.
   If staleness survives anywhere, it survives there.
2. **Keep the holdings ingester running.** It is the only route to testing the
   per-bond staleness idea properly, and it needs about a year of accumulation.
   It costs nothing to run and should start now, which it has.
3. **The odd-lot execution gap.** We hold a genuinely rare dataset — separate
   prices for small and large trades in the same bond on the same day, which
   measures how badly the retail side is being handled. It cannot go live because
   the source is not current, but it would corroborate the mechanism.

---

## Deployment decision

**Deploy nothing new.** No candidate passed. The strongest scored 0.37 against a
zero-skill benchmark of 0.54, failed the alpha test at t=1.98 against a required
3.0, and failed both factor-exposure limits.

The runbook permits deploying the best candidate at 10% size tagged
*PROVISIONAL — NOT VALIDATED*. **We are declining that too**, for a specific
reason: the candidate's measured exposures are −0.163 to high yield and +0.123 to
investment grade. It is a static credit-quality tilt held continuously. The
standing mandate is fast-money relative value with no carry, no beta and no
holding. Deploying it would not be a small provisional bet on an unproven edge —
it would be a direct breach of the mandate, dressed as research.

**Still running:** the Phase 0 null trader, unchanged, at 09:35 ET each weekday.
It has now also passed its 19-year shadow test. It stays until it has enough live
fills to compare modelled slippage against real slippage, which is the last piece
of machinery we need before any real strategy is trusted with capital.
