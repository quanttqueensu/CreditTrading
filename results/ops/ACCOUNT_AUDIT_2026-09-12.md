# ACCOUNT AUDIT — options: **UNMEASURABLE (read-only connection)**

**This note does NOT say options are unavailable. It says the question was not answered**, and the difference matters: G5 and G7 are gated on a real answer, and recording a false negative would retire the programme for the wrong reason.

Either way `G1`-`G4` and the research phases are unaffected.

> **Run on a NON-TRADING day.** Q1 (permission), Q2 (historical bars) and Q4 (account) are unaffected — margin checks, history and account values all answer with the market closed. **Q3 cannot be answered** and says so rather than concluding.

Run 2026-09-12T11:55:12 by `python3 -m ops.account_audit` against 127.0.0.1:4002, clientId 116, **readonly=True**. No order was placed, modified or cancelled; `whatIfOrder` never transmits.

| probe | question | answer | detail |
|---|---|---|---|
| Q1 options permission | whatIfOrder on a 1-lot HYG put -- margin response = permitted, IB 10xxx / 'not permitted' = the answer | **UNMEASURABLE (read-only connection)** | whatIfOrder returned [] — a timeout, not a refusal. The contract QUALIFIED (conId 823320930), so it exists. `readonly=True` is enforced at the gateway and drops the order message. **Answer this in the Client Portal** (Settings -> Account Settings -> Trading Permissions): 30 seconds, zero risk. Re-probing with readonly=False would put a live order path in an agent's hands to answer a question a human can read off a web page. |
| Q2 historical option bars | reqHistoricalData on that contract: how far back, at what bar size | **NONE** | no bars at any duration  -> G2 cannot build an HYG surface from IBKR; the programme falls back to SPY (equity gamma) or needs another source |
| Q3 option market data | reqMktData under reqMarketDataType(3) then (1) -- OPRA is a separate subscription from equity top-of-book | **UNMEASURED (market closed)** | live: bid=nan ask=nan  -> today is not an NYSE trading day, so an absent quote says nothing about the subscription. RE-RUN ON A TRADING DAY before treating this as an answer. |
| Q4 margin type + account | accountSummary: AccountType, NetLiquidation, FullMaintMarginReq, Cushion | **INDIVIDUAL** | AccountType=INDIVIDUAL, NetLiquidation.CAD=991387.72, ExcessLiquidity.CAD=163194.17, Cushion=0.164612, FullMaintMarginReq.CAD=828193.56, GrossPositionValue.CAD=1996541.20 |
| Q5 commission plan | Tiered or Fixed -- sets min_trade_usd ($517 on Fixed, $181 on Tiered) | **READ FROM whatIf** | Tiered options $0.15-$0.65/contract, Fixed $0.65, $1.00 order minimum on both. Compare the commission in Q1's response; confirm in Client Portal -> Settings -> Commissions. NOT an assumption -- if Q1 returned no commission, this stays UNMEASURED. |

## What each answer unblocks

| answer | unblocks / blocks |
|---|---|
| Q1 permitted | `gamma/G5` (paper book) and `gamma/G7` (the sleeve, 1 GAMMA trial) |
| Q2 bar depth | `gamma/G2`'s HYG surface, and therefore `G6`'s conditioners and `G7`'s budget. **No bars = no credit surface**, and the programme is equity gamma on SPY or nothing |
| Q3 option quote | `G5`'s daily marks. Without it the paper book cannot mark a position even if Q1 says permitted |
| Q4 account | sizes a fourth book against preflight's account-wide 0.10 cushion floor (`ops/preflight.py:236`) |
| Q5 commissions | `min_trade_usd` — $517 was derived on the Fixed $1.00 minimum; Tiered gives $181 |

Re-run `python3 -m ops.gamma_status` after this lands; it reads this note to decide what is unblocked.
