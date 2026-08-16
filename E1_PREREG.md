# E1 — RELATIVE ETF PREMIUM/DISCOUNT REVERSION (HYG vs JNK)

**Pre-registered 2026-07-30, BEFORE any return of this signal was examined.**
Written to satisfy `credit_rv_agent_workflow.md` §5.1. Nothing below may change after the
first backtest; changes require a numbered amendment that increments the trial counter.

Family tag: `e1_pd`. This is a NEW family — it uses a data source (issuer NAV) that the
`credit_rv` family never touched. The `credit_rv` counter (141) does not transfer, but this
document records that 141 trials have already been spent on this *asset class* by the same
researcher, so the prior on any positive result here is correspondingly weaker and the
holdout discipline in §7 is not optional.

---

## §1 MECHANISM (workflow §1.1 — all four parts required)

### (a) The structural friction that creates the mispricing

HYG and JNK hold economically near-identical US high-yield exposure through different index
families (ICE BofA vs Bloomberg). Their NAVs are struck once daily at 16:00 ET from
**evaluated / matrix bond prices** — most HY bonds do not trade on a given day, so the
evaluator interpolates from comparable paper. The ETFs meanwhile trade continuously on
ARCA with sub-second price discovery.

The gap between an ETF's price and its NAV is closed by Authorised Participants, who create
or redeem units against the underlying bond basket. That arbitrage costs roughly **145bp
round trip in odd lots**, and the bonds are quoted by appointment rather than continuously.
That cost is the **width of the no-arbitrage band**: inside it, no economic force pulls
price back to NAV.

### (b) Who is on the losing side

Not the AP — the AP is constrained, not foolish. The loser is the **flow-driven marginal
participant who must transact in one specific wrapper today**. An institution buying
liquidity buys HYG because it is the most liquid HY vehicle; a fee-sensitive allocator buys
JNK because it is cheaper to hold. Each pushes *its own wrapper* away from the complex's
fair value and pays that dislocation. We take the other side and warehouse the imbalance
for days.

### (c) Why they keep doing it instead of arbitraging it away

Because for them it is not an arbitrage — it is the cost of executing a mandate. A pension
rebalancing into HY today cannot wait a week for HYG's premium to decay; the tracking error
of *not* being invested dominates the 20bp it pays away. And the agent who could close the
gap (the AP) only fires when the dislocation exceeds its ~145bp bond-market round trip.
Below that threshold the gap simply persists and then decays.

### (d) What would make this edge disappear

- Electronification of the underlying bond market (portfolio trading, all-to-all platforms)
  cutting the AP's round-trip cost and narrowing the band.
- Convergence of the two funds' holder bases, so flows arrive in both simultaneously.
- A structural change in NAV striking (e.g. real-time evaluated pricing) removing the
  staleness that lets the dislocation be measured at all.

---

## §2 WHY THIS IS NOT ONE OF THE FOUR TRAPS (workflow §2.3)

| trap | why this is not it |
|---|---|
| duration-hedged long HY | both legs are HY ETFs of near-identical duration and credit quality; there is no long-HY leg to earn a risk premium. Enforced by §5 `G-BETA`. |
| short vol in disguise | position size is a bounded function of the z-score; there is no add-on-drawdown rule and a hard stop exists at §4.4. Verified by the short-straddle regressor in §5. |
| IG vs HY quality spread | both legs are HY. There is no IG leg. |
| frequency without edge | §6 requires gross edge per round trip ≥ 2.5× modelled cost BEFORE promotion. This is the gate that killed the predecessor and it is applied first, not last. |

---

## §3 THE SIGNAL

### 3.1 Bounce-free construction — the non-negotiable part

The predecessor strategy (`credit_rv`) died because its signal was built on the **closing
print**, which alternates between bid and ask. A name that printed at the bid looks cheap
and mean-reverts mechanically the next day — profit that cannot be captured, because you
must lift the ask to own it. Phase 0 proved this three ways (`FINDINGS.md` §8e).

Premium/discount is **not automatically immune**: `PD = (price − NAV)/NAV` contains the
closing price and therefore its bounce. So the signal is built on the bounce-free mid:

```
PD_mid(i,t)  =  ( (H(i,t) + L(i,t))/2  −  NAV(i,t) )  /  NAV(i,t)
```

`(H+L)/2` is known at that day's close, so the signal remains computable in time to trade,
and it contains no bid-ask alternation. NAV carries no bid-ask by construction.

**Pre-committed falsification test.** The same 2×2 that killed the predecessor is run
here BEFORE any performance claim: signal from {close, mid} × return measured on
{close, mid}. If the `mid → close` cell is not positive and not within a factor of ~2 of
the `close → close` cell, the edge is bounce and this family is killed. No exceptions.

### 3.2 The relative signal

```
S(t)  =  PD_mid(HYG,t)  −  β(t) · PD_mid(JNK,t)
z(t)  =  ( S(t) − μ(t) ) / σ(t)          on a trailing window, PIT
```

The *difference* is what is traded, never the level. Both NAVs are stale in the same way,
so the common evaluation-lag component cancels and what remains is wrapper-specific
dislocation. An outright PD trade would be fading genuine price discovery — the ETF leading
its own stale NAV — and is explicitly NOT this strategy.

`β(t)` is estimated by **Kalman filter** on the two PD series, not fixed OLS (workflow
§5.2). The filtered ratio's own volatility is reported; an unstable β is evidence the pair
is not a pair.

### 3.3 Dynamics and bands

`S(t)` is modelled as Ornstein–Uhlenbeck; θ, μ, σ and the implied half-life are fitted PIT.
Entry/exit bands come from the **OU optimal-stopping solution given round-trip cost**
(Bertram; Leung & Li), not from ±2σ by habit. Cost enters the band width directly, which is
the entire reason for doing it this way.

---

## §4 EXECUTION AND RISK

- **Decide at T, execute at T+1 close.** Never same-bar. (workflow §7, §10)
- Beta-scaled, not dollar-scaled (workflow §10: dollar-neutral ≠ risk-neutral).
- Capital: IBKR paper DUQ199038, NetLiquidation ~**$1.00M CAD** (≈$0.73M USD). USD legs are
  dollar-neutral so the residual FX exposure is the net USD balance, ~0.
- Vol target 12% annualised. Max gross 2.0× (Reg T reality on offsetting ETF legs —
  workflow §6.2.5; the observed BuyingPower/NetLiq is 3.33×, so 2.0× is inside it).
- §4.4 **Hard stop**: position closed if |z| exceeds 4.0 (dislocation regime-shifted rather
  than reverting) or if the Kalman β moves more than 3 filtered SDs in 20 days.
- Drawdown throttle per workflow §6.2.4.

---

## §5 CARRY AND BETA TEST (workflow §5.5) — MANDATE ENFORCEMENT

Daily net returns regressed on: HY excess return (HYG − duration-matched Treasury), IG
excess return, 10y Treasury return, SPX return, ΔVIX, short-ATM-straddle proxy, credit
momentum.

**Pass conditions, pre-committed:** |β| ≤ 0.10 on every factor, factor R² ≤ 0.25, alpha
t ≥ 3.0 out of sample.

Separately, P&L is recomputed with all distributions and accruals stripped. If net Sharpe
falls by more than 20%, this is carry and it is killed. Both numbers reported side by side,
always.

---

## §6 FREQUENCY TEST (workflow §5.6)

- Median holding period must be consistent with the fitted OU half-life (0.5–1.5×).
- **Gross edge per round trip ≥ 2.5 × modelled round-trip cost.** If this fails the
  response is to trade less often at wider bands — NOT to find a cheaper cost assumption.
- ≥ 250 non-overlapping trades in the evaluation sample.

Cost model (workflow §5.4), every term measured not assumed:
```
round_trip_bps = 2 × measured_half_spread        # IBKR BID_ASK, RTH closing window
               + impact(participation)            # threshold form, verified vs touch depth
               + commission                       # IBKR live schedule
               + borrow × holding_days/252         # data/financing_curve.parquet
               + accrual difference                # distributions on both legs
```

---

## §7 SAMPLE SPLIT — DECLARED BEFORE LOOKING

- **In-sample:** 2007-04-11 → 2019-12-31
- **Out-of-sample:** 2020-01-01 → 2023-12-31
- **HOLDOUT, sealed:** 2024-01-01 → 2026-07-24. Opened at most ONCE, on a configuration
  frozen from IS+OOS evidence only.

COVID (2020-02-15 → 2020-04-30) is reported separately in every table. The predecessor's
single most seductive result was one three-week episode in March 2020 and it did not
survive; any result here that depends on that window is presumed dead until shown otherwise.

---

## §8 VERDICT RULE — WRITTEN BEFORE THE RESULT

**PROMOTE** only if all hold on out-of-sample data:
1. bounce 2×2 passes (§3.1)
2. net Sharpe ≥ 0.8 on the conservative cost series
3. gross edge ≥ 2.5× round-trip cost (§6)
4. carry/beta test passes (§5)
5. ≥ 250 non-overlapping trades
6. positive net Sharpe in ≥ 70% of rolling 6-month windows

**DEMOTE-TO-WATCH** if the mechanism survives but the economics do not clear costs.
**KILL** if the bounce test fails or the edge is carry.

Anything short of PROMOTE does not get capital. It may still be deployed as a
**zero-capital shadow tracker** (workflow Phase 4), which is a measurement, not a position.
