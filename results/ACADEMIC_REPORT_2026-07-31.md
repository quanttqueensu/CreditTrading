# Thirteen mechanisms, one surviving effect, and no deployable alpha

**Overnight research report, 31 July 2026.** QUANTT credit relative value.

---

## Abstract

We tested thirteen distinct mechanisms for extracting relative-value alpha from
the US credit ETF complex, across two overnight cycles, using a 40.7M-row TRACE
bond-day panel, 19 years of issuer NAV data, a newly built 15-fund daily holdings
ingester, and a newly staged SEC N-PORT quarterly holdings history. **Twelve
mechanisms are dead. One is real but not harvestable at our account size.** We
deployed five reference benchmark books and no alpha strategy.

The single most useful result is negative and precise: the premium/discount
between a credit ETF's price and its published net asset value — the object both
prior strategies traded — is **not a dislocation**. It is a measurement artifact
of stale bond marks, and the ETF price is the *more* accurate valuation of the two.
Trading it means fading genuine price discovery.

The second most useful result is a correction to our own machinery: the cost model
had been charging **21.2%/yr** to every candidate, a figure that turned out to be a
full-sample artifact of 2007–2014 ETF illiquidity. Current-era cost is **1.73bp per
trade, 3.7× cheaper.** This did not rescue any strategy, and the reason matters:
our failures were absence of gross edge, not cost.

---

## 1. Data

| source | size | period | live? |
|---|---|---|---|
| TRACE bond-day panel | 40.7M rows | 2002–2025 | no (238d stale) |
| Fallen-angel index migrations | 16,388 events | 2003–2025 | no |
| Issuer NAV, 25 funds | 119,085 rows | 2002–2026 | yes |
| ETF OHLC, 58 tickers | 227,647 rows | 1993–2026 | yes |
| **ETF holdings, 15 funds** (built) | 29,698 rows, 11,423 CUSIPs | **2026-07-29→** | yes |
| **SEC N-PORT** (built) | 136,268 rows | 2019–2026, quarterly | yes |
| **FINRA daily short volume** (built) | 26,116 rows | 2018–2026 | yes |
| Measured IBKR half-spreads | 29 names | 2021–2026 | — |

Three data findings are worth recording independently of any strategy:

**(a) An ETF is a published bond price panel.** Issuers post every holding daily
with a price, free. The union across 15 funds is **11,423 individually-priced
CUSIPs per day**. But there is no archive — the date parameter is ignored — so
this panel begins on 2026-07-29 and accumulates one day at a time.

**(b) Cross-issuer price disagreement carries no information.** On 1,132 bonds
held by both iShares and State Street, median disagreement is **0.09bp** (p99
1.03bp). Both issuers buy marks from the same evaluated-pricing vendor, so
mark-versus-mark comparison is structurally blind to staleness.

**(c) N-PORT's fair-value hierarchy is degenerate for this purpose.** 135,850 of
135,870 corporate bond rows are Level 2. It provides no within-bond markability
differentiation.

---

## 2. The central negative result: premium/discount is measurement error

Both prior strategies traded the gap between an ETF's price and its NAV. We
established why that fails, in three steps.

**Step 1 — NAV is a smoothed series.** If a published value is a lagged average of
truth, its changes autocorrelate. For HYG over 19 years:

| | value |
|---|---|
| AR(1) of NAV total return | **+0.388** |
| AR(1) of the fund's own price return | **−0.005** |
| NAV volatility vs price volatility | 6.05% vs 9.51% |

A valuation *less volatile than the asset it values* is the classical signature of
smoothing. The market price shows none of it.

**Step 2 — the smoothing decayed in lockstep with the apparent opportunity.**

| era | NAV AR(1) | PD dispersion | naive PD trade return |
|---|---|---|---|
| 2007–10 | +0.580 | 187.9bp | 2.54%/yr |
| 2015–18 | +0.303 | 5.6bp | 1.04%/yr |
| **2023–26** | **+0.148** | **3.8bp** | **0.05%/yr** |

The naive band trade's *Sharpe* held up across all four eras (0.75 → 2.64 → 0.41 →
0.48) while its *return* went to five basis points a year. It did not begin
losing; it stopped trading, because the dislocation shrank below its entry
threshold.

**Step 3 — where PD does predict, it predicts the NAV, not the price.**
Regressing forward returns on PD, 2019–2026:

| fund | PD → NAV revision (t) | PD → price return (t) |
|---|---|---|
| EMB | **+24.4** | +1.94 |
| ANGL | **+19.1** | +0.11 |
| HYG | **+15.3** | −2.30 |
| LQD | **+14.7** | +3.08 |

PD forecasts the NAV catching up. Under a bounce-free 2×2 falsification, the
credit funds' `close→mid` coefficients are **positive** (EMB +15.3, LQD +11.7,
HYG +10.0), meaning a fund trading above NAV keeps rising — the ETF is *leading*
its stale NAV. Fading that is fading price discovery.

**Negative control.** Treasury ETFs, which are marked from a continuous screen
market, show NAV AR(1) of 0.00 to −0.106 in every era and PD viability of 0.0–0.4×
against 1.5–18.6× for credit. The test discriminates.

---

## 3. The one real effect: forced index-migration flow

When a bond is downgraded out of investment grade, index-tracking funds must sell
it regardless of price. The downgrade is public beforehand; the selling at the
index flip is mechanical and information-free. This is a Coval–Stafford
identification.

**16,388 migrations, 2003–2025, abnormal return vs the median same-grade bond:**

| business days from flip | CAR | t |
|---|---|---|
| −10 | −235bp | −12.7 |
| **+2 (trough)** | **−424bp** | **−17.5** |
| +20 | −139bp | −5.6 |
| +60 | −2.8bp | −0.10 |

The bond falls 4.2% and recovers essentially all of it. Information would leave it
down; pressure reverses. **Robustness:** two bugs in our first pass (survivorship
from dropouts, and trade-count rather than calendar event time) produced a
spurious 414% recovery. Corrected and re-run under five sample definitions,
including one where a bond that stops trading is carried flat and *cannot*
recover, recovery is **82–85%** with the trough deeper (−460bp).

**Mechanism chain, all links verified:**
1. Customer sell imbalance goes 0.000 → **+0.060** exactly in the k=0..+2 window.
2. Price is pushed down (−424bp, t −17.5).
3. Price recovers (82–99%).
4. **Monotone in intensity:** quiet months (<25 migrations) recover **−22%** — the
   price keeps falling, i.e. genuine company news. Crisis months (>400) recover
   **98%** — pure pressure. The mechanism correctly separates where it should and
   should not apply.

**Why it is not tradable by us.** Bonds cannot be traded at our size, so the only
expression is the wrapper. About 104 bonds sit in the recovery window against ~350
holdings, so perfect capture yields ~416bp/yr against **5.3% of hedged-basis
noise** — signal one-fifth of noise. Empirically: holding ANGL vs HYG with **no
signal** scores 0.37; adding our forced-flow timing signal scores **0.03–0.24**,
strictly worse. The premium is already passive in ANGL and has been sold as a
product since 2012. Test 7 fails regardless (alpha t 1.98 vs 3.0 required; HY beta
−0.163 and IG beta +0.123 vs 0.10 limit) — it is a credit-quality tilt, not alpha.
And the crisis regime fired **4 times in 273 months**.

---

## 4. The combination lever, and the limit nobody mentions

Portfolio Sharpe from N sleeves of Sharpe S at average correlation ρ is
`S·√(N/(1+(N−1)ρ))`. We built 22 within-class wrapper pairs to test it.

**The orthogonality thesis holds.** Mean pairwise correlation **+0.027**, and the
combined **gross Sharpe is +1.03** — the best number in the project.

**It fails on two arithmetic walls:**

1. **Costs do not diversify.** Volatility falls with √N; costs are subtracted from
   every leg regardless. So cost drag *in Sharpe units* grows with √N. Gross +1.03
   becomes **net −0.16**.
2. **Capacity.** Combined volatility is 0.37%. Reaching the 12% mandate requires
   **32.8× leverage** against a ~2× Reg T ceiling — an 18-fold shortfall.

The underlying per-pair signal is weak and we report it as such: mean t −1.17 at
one day, 5 of 22 individually significant (IGLB/VCLT −3.58, SPLB/IGLB −3.20,
SPHY/USHY −2.78), Treasury control +0.12 with 0 of 3.

---

## 5. Everything tested, with cause of death

| # | mechanism | verdict | evidence |
|---|---|---|---|
| 1 | credit_rv cross-sectional residual | **D1** | gross edge −0.19%/yr; holdout SR −1.44 |
| 2 | E1 raw HYG/JNK premium/discount | **D1** | OOS SR −6.65; return → 0.05%/yr |
| 3 | S1 staleness via cross-issuer disagreement | **D1** | input is 0.09bp — same vendor |
| 4 | Single-fund PD, all wrappers | **D1** | predicts NAV (t 15–24), not price |
| 5 | S2 common-priced basket | **untestable** | needs holdings history; panel starts 2026-07-29 |
| 6 | S3 forced flow via ETF wrapper | **D4** | quality tilt; unconditional beats conditional |
| 7 | Raw ETF creation/redemption flow | **D1** | 28,025 obs, all abs(t) < 0.8 |
| 8 | Lead-lag wrapper diffusion | **D1** | mean t 5.20 → **−0.50** on executable prices |
| 9 | N-PORT × TRACE reconstructed NAV | **D7** | 17–30% daily weight coverage, declining |
| 10 | Dealer balance-sheet constraint | **D1** | 0/9 credit names significant, control equal |
| 11 | OU-band pair reversion | **D2+capacity** | gross +1.03, net −0.16, needs 32.8× leverage |
| 12 | FINRA crowded-hedge reversal | **D1** | credit mean t 0.28; rates control higher |
| 13 | MBS prepayment staleness | folded into #4 | MBS is not distinguishable from other credit |

**Every negative control passed**, which is what gives the nulls weight: Treasury
ETFs were flat for NAV staleness, PD viability, lead-lag (in the executable spec),
forced flow, and pair reversion.

---

## 6. Benchmarks, and what the strategy would have had to beat

All books run the identical cost model, fill assumption and accounting path.
Excess of the risk-free rate, 2007–2026.

| book | net Sharpe | CAGR | 2023–26 Sharpe |
|---|---|---|---|
| B4 60/40 SPY/IEF | 0.63 | 6.73% | 0.93 |
| B8 naive raw PD | 0.59 | 1.11% | 0.48 |
| **B2 duration-hedged HY carry** | **0.54** | **5.22%** | **0.47** |
| B6 equal-weight credit | 0.48 | 3.50% | 0.50 |
| B1 HYG | 0.35 | 3.29% | 0.59 |
| B7 naive pair z-score | 0.21 | 0.51% | −0.25 |
| B5 SHY (cash) | 0.20 | 0.29% | −0.47 |
| B9 null trader | −4.60 | −19.46% | — |

**B2 is the hurdle** — the credit risk premium with rates hedged out, earned with
zero skill. Our best candidate scored 0.37.

**B9 passed its test**, which validates the machinery: net −19.46%/yr against a
modelled cost of 19.7%/yr, with a before-cost Sharpe of −0.39 (statistically
zero). The accounting path does not invent profits.

**Multiple testing.** 162 cumulative trials on the legacy data source. Under
`E[max] = √(2·ln N)`, the best of 162 pure-noise strategies would score ≈ **3.19**.
Our best real candidate scored 0.37.

---

## 7. What was deployed

**Five reference benchmark books to the IBKR paper account**, 11 orders,
$79,533 notional. Not alpha claims — they exist so future work is measured against
zero skill through an identical execution path. B4 failed to place (SPY absent
from the local price source) and is pending.

**No alpha strategy was deployed.** No candidate cleared the gate, and we declined
the permitted 10% `PROVISIONAL` slot as well: the strongest candidate's measured
exposures (HY −0.163, IG +0.123) make it a static credit-quality tilt held
continuously, which breaches the no-carry/no-beta mandate outright rather than
being a small bet on an unproven edge.

**Two infrastructure defects found and fixed**, both of which would have silently
broken live trading:
- `IBKRBroker` never read its own configuration — `make_broker` passes only
  `books_root`/`verbose`, so the dataclass default port 4002 always won while TWS
  listens on 7497. Every live run, including the null trader's first scheduled
  fire, would have died on ConnectionRefused.
- `static_weights` was an allowed, validated allocation type with no sleeve class
  implemented behind it.

---

## 8. Honest confidence

**That the forced-flow price-pressure effect is real: ~90%.** 16,388 events,
t −17.5, survives every robustness check including those designed to kill it,
clean negative control, independent confirmation in the flow data, and correct
monotonicity in its own driver.

**That a 12% strategy exists in this space at $640k under Reg T: ~10%**, down from
where we started, and the reason is specific rather than atmospheric — the two
walls in §4 are arithmetic, not evidence we can improve with more search.

**What would move it:** access to the bonds themselves rather than the wrapper;
portfolio margin or a futures expression for the rates leg to relieve the gross
constraint; or a data source outside the ETF wrapper entirely. Further search on
ETF prices is close to worthless at 162 trials.

---

## 9. What we would do next, ranked

1. **Stop searching ETF price data.** Thirteen mechanisms, one survivor, and the
   deflated-Sharpe bar is now 3.19. The framework's own stop condition is met.
2. **Keep the holdings ingester running.** It is the only route to the per-bond
   staleness test and needs roughly a year of accumulation. Cost: zero.
3. ~~Price the futures expression.~~ **Done 2026-07-31 — it does not help.**
   Futures margin is 14-40x more efficient than Reg T, but all 22 pairs are
   credit-vs-credit and hold zero duration, so there is no rates leg to convert.
   PortfolioMargin does reach 10x by netting credit DV01 before the shock, and
   impact binds before margin on the full set (PCY at 18.5% of ADV at a 12%
   target). Filtering to deep legs lifts the ceiling only to **4.85% vol** at a
   net Sharpe of +0.03. The capacity chain has no single weak link to engineer
   away. Futures would pay only on a long-credit/short-duration sleeve, which is
   the carry the mandate forbids.
4. **Let the null trader run its 20 sessions.** We still have zero live fills, so
   realised-versus-modelled slippage — the last unvalidated piece of machinery —
   remains unmeasured.
