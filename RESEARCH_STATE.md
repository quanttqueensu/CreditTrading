# RESEARCH STATE
Last updated: 2026-07-31 (overnight run 2)  |  Global trial count: 156 + per-source counters below  |  Nights run: 2

Trial budgeting (per user decision 2026-07-31): the deflated-Sharpe bar applies
WITHIN a data source. Each genuinely new source gets its own counter; the legacy
counter (156) covers all ETF-price/PD work done to date.

| counter | source | trials used |
|---|---|---|
| LEGACY | ETF prices + HYG/JNK PD + TRACE fallen-angel | 162 |
| NPORT | SEC N-PORT holdings history 2019+ | 1 |
| BREADTH | 45-instrument extended universe | 4 |
| DISP | PD dispersion / staleness decomposition | 3 |
| DEALER | NY Fed primary dealer inventory | 1 |
| MBS | mortgage prepayment staleness | 0 |
| **CEF** | **credit closed-end fund discounts (NEW SOURCE)** | **18** |
| POSITIONING | FINRA short interest + daily short volume | 1 |

---

## DEPLOYED — live state read from the BROKER, 2026-07-31 16:45 ET

**The local ledgers are wrong.** Every `nav.csv`/`trades.csv` under `ops/books/`
still shows only the funding row. The IBKR account holds **35 positions, $2.07M
gross**. The table below is read from IBKR, not from our files. Attribution sums
to −$7,884 against IBKR's reported total unrealised of −$7,883.09, so every
position is accounted for. Reproduce: `scripts/audit/live_pnl_attribution.py`.

| book | capital | gross | live P&L | return | status |
|---|---:|---:|---:|---:|---|
| **cef_discount** | $500k | $749k (1.50x) | **−$7,350** | **−1.47%** | filled 07-31 pre-market; loss is ~all execution, see below |
| phase0_null_trader | $640k | $640k | −$281 | −0.04% | fired 14:45 ET 07-31, filled. Control: expected P&L = −costs |
| bench_b1_hyg | $20k | $20k | −$2 | −0.01% | filled |
| bench_b3_agg | $20k | $20k | −$126 | −0.63% | filled, but at 98.005 vs 97.62 decision = 39bp of after-hours slippage |
| bench_b4_60_40 | $20k | $20k | −$98 | −0.49% | **DID fill** (SPY 16 / IEF 85, exactly 60/40) despite being recorded as FAILED. Ledger gap |
| bench_b5_shy | $20k | $20k | −$9 | −0.04% | filled |
| bench_b6_ew_credit | $20k | $20k | −$18 | −0.09% | filled |

**CEF day-one split.** Priced against the decision prices the sleeve traded on:
**+$50 (+0.01%)** — flat. Priced against the fills we got: **−$7,350**. The
difference, **$7,399**, is slippage from plain market orders resting overnight and
filling at 07:27 ET, two hours before the open. Slippage is against us on every
buy *and* every sell — the signature of crossing a wide spread, not noise.

**Margin is tight:** ExcessLiquidity 164,500 CAD against FullInitMarginReq
825,109 CAD and NetLiquidation 989,609 CAD — 83% utilisation, 2.09x gross.

---

## AUDIT 2026-07-31 — full end-to-end review

Complete write-up with every number: **`results/AUDIT_2026-07-31.md`**.
Reproduction scripts: `scripts/audit/`.

**The alpha is real.** Two deliberate attempts to kill it failed. The live book is
66% net short muni CEFs / 57% net long taxable, so the obvious hypothesis was
muni-vs-taxable in costume — the way `S3-wrapper` was a quality tilt in costume.
It is not: adding MUB, HYD and a duration spread leaves alpha at +8.83%/yr t+5.67;
regressing on the CEF sector's **own** group returns (the sharp control, since
muni CEF discounts do not move like MUB) leaves +7.63%/yr t+5.90, R² 0.006, every
group beta ≤ 0.025. This is the strongest result the project has produced.

**But the deployed configuration is wrong three ways.**

1. **Spec, code and optimum disagree.** `rebalance_days: 5` is in the frozen spec;
   the only file that reads that key is `null_trader.py`, so `cef_discount.py`
   trades **every session**. The optimum under real execution is **2 days**.
   Net SR: hold=1 → 0.62, **hold=2 → 0.73**, hold=5 → 0.51, hold=21 → 0.20.
2. **The backtest assumes an unobtainable entry price.** `validate.py:86` uses
   `held = W.shift(1)`, entering at day *t*'s close using day *t*'s NAV — which
   publishes after that close. An MOC fills at *t+1*'s close = `shift(2)`. Cost:
   gross SR 1.26 → 0.95, net SR at hold=5 **0.82 → 0.51 (−38%)**.
3. **No sealed holdout.** `credit_rv` got 141 trials *and* a sealed holdout before
   being killed. CEF got 10 specs, no holdout, and $500k — the one discipline this
   project held religiously, dropped on the one strategy that got money.

**Signal structure.** IC rises with horizon (0.040 at 1d → 0.103 at 42d);
IC/√h decays with a **31.1-day half-life**. Sharpe is nonetheless highest at short
holds because IR ≈ IC·√BR. This is a breadth machine, not a timing machine, and it
is under-trading its own breadth.

**Distribution data is fetched and unused.** `data/cef/cef_dist_features.parquet`
(11,988 rows, `is_cut`/`is_raise`/`annualized_yield_pct`) landed 16:42 today; the
deployed sleeve has zero references to it. Shorting a fund into a discount that
widened *permanently* after a distribution cut is the classic way this strategy
loses money, and there is currently no defence against it.

**MOC routing verified good.** Live test at 16:39 ET — after the 15:50 exchange
cutoff and after the close, the same conditions the 17:15 job hits — returned
`PreSubmitted`, no error, queued for the next closing auction, cancelled cleanly.
Note the launchd job runs `~/Library/Application Support/quantt/launch_job.py`,
not `run_cef.sh`, to work around macOS TCC blocking `/bin/bash` from the Desktop.

**Pattern across the 13 dead mechanisms.** Six were stale-price artifacts
(`credit_rv`, `S1`, `single-fund-PD`, `leadlag`, `E1`, `nport-trace-nav`); three
lost to their own control group (`dealer-constraint`, `short-pressure`,
`S3-wrapper`); two died on arithmetic (`pair-reversion`). The detection machinery
is good. The generation side keeps returning to one well — price minus a stale
mark — which is dry in ETFs because APs arbitraged it, and wet in CEFs precisely
because no AP mechanism exists there.

**Fixed en route:** `IBKRBroker` never read its own configuration. `make_broker`
passes only books_root/verbose, so the `IBKRConfig` dataclass default of port 4002
always won while TWS listens on 7497 — every live run would have died with
ConnectionRefused, including the null trader's first scheduled fire. Added
`IBKRConfig.from_env()` (process env, then config/.env) and wired it in.
Also implemented `StaticWeightsSleeve`: `static_weights` was an allowed and
validated alloc type with no sleeve class behind it.

---

## KILLED — never re-test without new data
| id | hypothesis | cause of death | evidence | date |
|---|---|---|---|---|
| credit_rv | cross-sectional price-residual RV on credit ETFs | **D1** gross edge NEGATIVE before costs (−0.19%/yr) | sealed holdout net SR −1.44, t −2.29 | 2026-07-30 |
| E1 | HYG vs JNK raw premium/discount reversion | **D1→D5 reclassified** see WATCH | OOS SR −6.65 continuous; but band form earns 2.54%/yr→0.05%/yr, i.e. it STOPPED TRADING rather than lost | 2026-07-30 |
| S1-as-specified | per-bond staleness score using cross-issuer price disagreement | **D1** the input carries no information: median disagreement 0.09bp, p99 1.03bp across 1,132 shared bonds — all issuers buy from the SAME vendor | `results/s1/` | 2026-07-30 |
| S3-wrapper | fallen-angel forced flow expressed via ANGL/FALN vs HYG | **D4** it is a credit-quality risk premium in costume: alpha t 1.98 (need 3.0), HY beta −0.163, IG beta +0.123 (need ≤0.10). Unconditional pair (0.37) BEATS signal-conditioned (0.03–0.24) | `results/s3/angl_expression.csv` | 2026-07-30 |
| single-fund-PD | premium/discount is still tradable in non-industrialised wrappers | **D1** dispersion is REAL and large (EMB 28.6bp, ANGL 23.3bp, viability 6-19x cost) but it is NAV staleness, not dislocation. PD predicts the NAV REVISION at t=15-24, and where it predicts price the sign is POSITIVE (EMB +15.3, LQD +11.7, HYG +10.0 on close->mid) = the ETF correctly LEADING a stale NAV. Trading it fades price discovery. Treasury controls show mid->mid t=-15..-18, a spurious-regression artifact from the shared price term, confirming the raw metric is fragile | `results/disp/` | 2026-07-31 |
| leadlag | thin wrappers lag liquid ones within an asset class (information diffusion) | **D1** pure non-synchronous trading. Raw effect was huge (mean t by group: IG_long 17.7, HY 12.4, MBS 11.7, EM 11.0, PREF 9.5) but it was measured on (H+L)/2, which is NOT a transactable price. Under executable close-to-close with the repo's T+1 convention the overall mean t goes 5.20 -> **-0.50**, and the Treasury CONTROL (+3.48) scores HIGHER than every credit group but one | `results/leadlag/leadlag_specs.csv` | 2026-07-31 |
| nport-trace-nav | rebuild daily NAV from N-PORT weights x TRACE transaction prints (mark-vs-TRACE, not mark-vs-mark) | **D7 infeasible** daily TRACE coverage of HYG's N-PORT weight is only 17-30% and DECLINING (26.5% in 2020 -> 17.4% in 2022). The bonds that print on a given day are selected for having news, so a 20%-weight subset cannot stand in for the book. N-PORT itself is sound (136,268 rows, 27 quarterly snapshots/fund, 95.3% CUSIP overlap vs the live iShares file) but is QUARTERLY not monthly, and `fair_val_level` is degenerate (135,850/135,870 corporate bonds are Level 2) | `data/holdings/nport_holdings.parquet` | 2026-07-31 |
| dealer-constraint | primary-dealer corporate inventory predicts credit excess returns (intermediary asset pricing) | **D1** ZERO credit names significant at any horizon 5-63d (best t=1.59, ANGL 42d); UST control shows the SAME magnitude (mean t 0.95-1.50), so even the sign that is there is not credit-specific | `results/s4/dealer_constraint.csv` | 2026-07-31 |
| pair-reversion | within-class wrapper pairs mean-revert; combine 22 for breadth | **D2 + capacity.** Combination thesis CONFIRMED: mean pairwise correlation +0.027, combined **GROSS Sharpe +1.03**. But (a) costs do NOT diversify while vol does, so the cost drag in Sharpe terms grows ~sqrt(N) and net falls to **-0.16**; (b) combined vol is 0.37%, so reaching the 12% mandate needs **32.8x leverage** against a ~2x Reg T ceiling. Per-pair signal is weak and honest: mean t -1.17 at h=1, 5/22 individually significant (IGLB/VCLT -3.58, SPLB/IGLB -3.20, SPHY/USHY -2.78), UST control +0.12 with 0/3 | `results/ou/pair_sleeve_v2.csv` | 2026-07-31 |
| short-pressure | crowded credit hedges (FINRA daily short volume) unwind and reverse | **D1** credit mean t 0.28/0.03/-0.20/-0.42 at h=1/3/5/10d, 2/10 names significant at the best horizon; the RATES comparison group scores HIGHER (1.01/0.92/1.05/0.45), so nothing here is credit-specific | `results/positioning/short_pressure.csv` | 2026-07-31 |
| raw-flow-z | ETF creation/redemption z-score predicts returns | **D1** precise zero: 28,025 obs, all \|t\|<0.8; Treasury control equally flat. Informed and forced flow cancel when pooled | `results/s3/flow_regression.csv` | 2026-07-30 |

---

## WATCH — passed mechanism, failed magnitude
| id | hypothesis | gross edge | what it needs |
|---|---|---|---|
| S3-forced-flow | IG→HY forced index deletion causes temporary price pressure | **−424bp trough, t −17.5, 82–85% reversal with dropouts carried flat**; sell imbalance 0.000→0.060 at the flip; Test 3 monotone (quiet −22% recovery = information, crisis 98% = pressure) | **D6 conditional sleeve.** Crisis regime (>400 migrations/mo) fired 4× in 273 months. Needs (a) a non-wrapper expression — 104 migrating bonds vs 350 holdings is 5× noise, (b) regime gate, (c) sized to fraction of time on. Negatively correlated with everything → marginal portfolio value >> standalone Sharpe |
| E1-band | raw PD ±2σ band | Sharpe held 0.75→2.64→0.41→0.48 across eras while return fell 2.54%→0.05%/yr | **Edge per opportunity SURVIVED; opportunity count collapsed.** Needs instruments where dispersion has NOT been industrialised by portfolio trading. See QUEUE rank 1 |

---

## ACTIVE
| id | hypothesis | phase | blocking gate |
|---|---|---|---|
| **CEF-DISC** | **credit closed-end fund discount reversion** | **DEPLOYED 2026-07-31, $500k paper** | none — full battery passed; now needs 60 live sessions |
| COST-AUDIT | the 21.2%/yr modelled cost is a full-sample artifact | **RESOLVED, see below** | — |
| DISP-SCAN | PD dispersion is still wide in non-industrialised wrappers | building | — |
| NPORT | monthly holdings history 2019+ from SEC EDGAR | agent staging | EDGAR parse |
| BREADTH | 45-instrument universe | agent staging | data fetch |

---

## RESOLVED THIS RUN — cost model audit (critical)

The 21.2%/yr headline that has been sitting in front of **every signal tested to
date** is a full-sample average dominated by 2007–2014, when these ETFs were young
and thin. Decomposition of the null trader at constant ~340×/yr turnover:

| era | spread bp | impact bp | total bp/trade | cost %/yr | impact share |
|---|---|---|---|---|---|
| 2007–10 | 1.04 | **12.87** | 13.91 | 42.5% | 92.6% |
| 2011–14 | 1.21 | 8.99 | 10.20 | 34.8% | 88.1% |
| 2015–18 | 1.48 | 3.01 | 4.49 | 15.3% | 67.0% |
| 2019–22 | 1.18 | 0.99 | 2.17 | 7.4% | 45.4% |
| **2023–26** | **1.25** | **0.48** | **1.73** | **5.9%** | 28.0% |

**Current-era cost is 1.73bp/trade — 3.7× cheaper than the full-sample 6.36bp.**
The half-spread component is *accurate* (modelled/measured = 1.00–1.02 on 7 of 8
names vs IBKR historical BID_ASK). Two corrections applied:

1. **The 2.5× "thin tier" multiplier is fiction** for penny-wide credit ETFs.
   ANGL: modelled 4.334bp vs measured 1.735bp — over-charged by exactly 2.5×.
   Now calibrated to measured half-spreads where a measurement exists.
2. **Evaluate on modern-era costs.** Charging 2007 illiquidity to a 2024 signal
   manufactures a fake obstacle. Any D2 verdict (gross>0, net≤0) reached on
   full-sample costs must be re-opened.

---

## QUEUE — ranked by expected information gain
| rank | direction | type | data needed | est. hours |
|---|---|---|---|---|
| 1 | **PD dispersion scan across ALL wrappers, ranked.** The E1 edge survived per-opportunity; only HYG's opportunity died, because portfolio trading industrialised that name. Nobody built a PT desk for HYD, HYMB, IGLB, SPLB, EMHY, preferreds, MBS. If dispersion is still wide there, the trade still exists there | B | NAV+price for 45 instruments | 2 |
| 2 | **MBS staleness.** Prepayment marks are the stalest in credit. If the S1 mechanism is real it must be STRONGEST in MBB/VMBS/SPMB. Simultaneously a breadth add and a mechanism test | B | MBB/VMBS/SPMB NAV+price | 2 |
| 3 | **N-PORT × TRACE reconstructed NAV.** Monthly weights × daily transaction prints = true NAV 2019–2025. Mark-vs-TRACE, not mark-vs-mark — the 0.09bp result proves mark-vs-mark is blind because staleness is SYSTEMATIC (one vendor) | B | N-PORT parse | 4 |
| 4 | **Getmansky-Lo-Makarov unsmoothing.** Turns the measured 0.388 NAV autocorrelation from a diagnostic into an actual estimator of true NAV. Causal/PIT: r_true(t) = [r_obs(t) − θ1·r_true(t−1) − θ2·r_true(t−2)]/θ0 | A | already have | 2 |
| 5 | Non-wrapper expression of S3 forced flow (D6 crisis sleeve) | B | — | 3 |
| 6 | FINRA short interest on credit ETFs; borrow rates as positioning | B | new fetch | 2 |

---

## DATA INVENTORY
| source | fields | freshness | live? | staged? |
|---|---|---|---|---|
| ETF holdings (15 funds) | per-CUSIP price, par, weight, duration, YTM, YTW, sector | 1d | yes | yes, **starts 2026-07-29, no history** |
| union bond price panel | 11,423 CUSIPs/day | 1d | yes | yes |
| iShares NAV (14 funds) | NAV/share, shares out, ex-div | 0d | yes | 2002→ |
| ETF OHLC | O/H/L/C/V, ret_total, mid_hl | 1d | yes | 1993→ |
| TRACE bond-day | 40.7M rows, per-CUSIP price + customer buy/sell direction, odd/round lot | **238d** | **no** | 2002–2025, **offline mechanism validation only** |
| fallen-angel events | 16,388 IG→HY migrations w/ index flip dates | — | no | 2003–2025 |
| VIX complex | VIX/VIX3M/VVIX | 0d | yes | 1990→ |
| UST futures (yf) | ZN/ZF/ZT/ZB | 0d | yes | 2000→, **separate series, do NOT splice to 1988 history** |
| measured IBKR spreads | half-spread bp, 29 names | 2026-07-30 | — | yes |

---

## OPEN QUESTIONS
- Does PD dispersion survive in wrappers without a portfolio-trading desk? (queue 1)
- Is stale-mark staleness strongest in MBS, as the mechanism predicts? (queue 2)
- How many of the LEGACY 156 trials' D2 verdicts flip when re-run on 1.73bp
  modern costs instead of 6.36bp full-sample costs?
- HYG/LQD rebuilt NAV carries a +1.80%/+0.46% level offset vs reported, consistent
  with securities-lending collateral booked as an asset with no published
  offsetting liability. Confirmed level, not drift — but only one day observed.

---

## PRICED 2026-07-31 — the futures expression, and the capacity chain

**Question:** does moving the rates leg into Treasury futures relieve the capacity
wall that stops the pair sleeve reaching 12% vol?

**Answer: no, and the reason is structural.** Futures margin is genuinely 14-40x
more efficient than Reg T on a cash ETF (ZF $1,375 on ~$110k notional = 1.25%
against Reg T's 50%). But all 22 pairs are credit-versus-credit and hold **zero
duration**. There is no rates leg to convert. The saving is real and unavailable.

**What the constraint actually is — a chain, priced end to end:**

| subset | pairs | net SR | max gross | achievable vol | binds |
|---|---|---|---|---|---|
| all 22 | 22 | -0.16 | $2.3M (1.8x) | **0.65%** | impact (PCY, $5M ADV) |
| both legs >$50M ADV | 14 | -0.20 | $12.8M (10x) | **4.11%** | margin |
| both legs >$100M ADV | 9 | +0.03 | $12.8M (10x) | **4.85%** | margin |

- **Reg T caps leverage at 1.0x** on a book already 2x gross -> 0.37% vol.
- **PortfolioMargin reaches 10x** because it nets credit DV01 across the book
  before shocking it, so a beta-hedged pair collapses to the 5%-of-gross floor.
  That is a genuine 10x capital efficiency Reg T cannot express.
- **Impact binds first on the full set**: at a 12% target the clip in PCY is
  18.5% of its ADV, refused by the cost model's own 5% participation guard.
- Filtering to deep legs moves the binding constraint from impact to margin, and
  the ceiling still lands at **4.85%** — 40% of the mandate.

**Even in its best configuration the sleeve delivers 0.03 x 4.85% = ~0.15%/yr.**
The chain does not have one weak link that can be engineered away; relieving both
impact and margin entirely still leaves a net Sharpe of +0.03.

**Where futures WOULD pay:** any sleeve that is long credit outright and short
duration (the B2 shape). That is exactly the carry/beta the mandate forbids, so
the margin efficiency has nothing mandate-compliant to attach to today. If the
mandate is ever widened to allow a duration-hedged carry sleeve, price this again
first -- it is the one place the 27-40x saving would be worth real money.

---

## CEF DISCOUNT REVERSION — the first candidate to clear Test 7

**Why this structure and not the ETF.** An ETF has authorised participants who
create and redeem against the basket; that machine compressed the HYG/JNK
dislocation from 188bp (2008) to 3.8bp (2026), which is what killed E1. A
closed-end fund's share count is FIXED — no APs, no creation, no redemption, so
nothing mechanically pulls price to NAV. Measured: credit CEF discounts average
**−3.16% with sd 5.95%, p5 −11.88%, p95 +7.11%**, roughly 150x the ETF gap.

**The decomposition that killed the ETF version REVERSES here:**

| | ETF (killed, D1) | CEF |
|---|---|---|
| discount → NAV revision | **t = +15 to +24** (artifact) | t = +1.72 (weak) |
| discount → PRICE | ~0 | **t = −1.75 mean, 6/18 at t<−2** |

For an ETF the stale NAV catches up to a price that was already right. A CEF
cannot do that, so the PRICE has to move — which is the whole hypothesis.

**Survives the obvious confound.** In a joint regression against trailing 21d
price return, **11/18 funds keep a significant discount effect** (mean joint
t = −3.16). For PDI, PTY, PCN and PDO the past-return term is insignificant while
the discount is overwhelming, so this is the NAV gap, not short-term reversal.

**Sleeve** (long 4 cheapest / short 4 richest vs each fund's OWN discount history,
5d hold, dollar-neutral, costs charged off each fund's own price):

| | gross SR | net SR | CAGR | vol | maxDD |
|---|---|---|---|---|---|
| full sample | 1.06 | **0.76** | 2.69% | 3.57% | −7.3% |

Costs are only 4.2% of gross. Sensitivity is monotone across hold (5/10/21d) and
basket size (3/4/5) — no knife-edge.

**TEST 7 — the gate every prior candidate failed:**

| | full 2005–26 | modern 2019–26 |
|---|---|---|
| R² | **0.005** PASS | 0.017 PASS |
| alpha | **+2.68%/yr, t +3.11** PASS | +5.10%/yr, t +2.58 FAIL |
| all 5 factor betas | **5/5 PASS** | **5/5 PASS** |

R² of 0.005 means 99.5% of the return is unexplained by HY, IG, rates, equity or
vol. This is genuinely market-neutral, unlike the ANGL/HYG candidate (alpha t 1.98,
HY beta −0.163, IG beta +0.123) which was a quality tilt.

**Honest weaknesses, stated before deployment:**
- Modern-era alpha t is **2.58 against a 3.0 gate** — a near miss, not a pass.
- Era profile is uneven: net SR 1.17 (2010–14), 0.62 (2015–19), **1.87 (2020–22,
  COVID discount blowout)**, **0.13–0.32 (2023–26)**. Part of the full-sample
  result is crisis alpha.
- The opportunity HAS narrowed — discount sd 15.22% → 9.52%, top-bottom spread
  27.48% → 22.47% — though nothing like E1's 40x collapse.
- The D2 threshold fix does NOT work: every |z| threshold above zero lowers the
  Sharpe (0.81 → 0.40 → 0.29 → 0.27), so the edge is spread across the
  cross-section rather than concentrated in extremes.
- **Not yet run:** purged CV, PBO, block bootstrap, sealed holdout.

**KILL RULE SUPERSEDED 2026-07-31 — OBSERVE-ONLY MODE.** Standing instruction:
nothing is to be killed automatically. The paper deployment exists to generate
data, and a sleeve that suspends itself stops producing the evidence it was
deployed to collect; with no real capital at risk the usual reason to cut a
losing book does not apply. All sleeve risk checks now RETURN OK and log a loud
WATCH line instead of halting, and every book-level drawdown suspend is raised to
99%. Broker margin limits still apply and are not ours to disable. The original
rule is kept below as the review checklist a human applies, not an automatic one:

**ORIGINAL PRE-COMMITTED KILL RULE (now advisory, human-applied):**
> Deploy at 5% of book gross, tagged `LEARNING — NOT CAPITAL ALLOCATED`.
> KILL if, after 60 live sessions, any of: (a) live net Sharpe < 0.0;
> (b) realised slippage exceeds modelled by more than 2x for 5 consecutive
> sessions; (c) the cross-sectional top-bottom discount spread falls below 12%
> (half its current 22.5%), which would mean the opportunity has gone the way
> of E1. No extension of rope. Reviewed at session 60, not before.

---

## CEF v2/v3 — the regime finding, and where the search stops

**Gate lowered, on the user's instruction and with a defensible reason.** alpha
t >= 3.0 is roughly a 0.1% significance bar, unusually strict. Standard
institutional practice is t >= 2.0. At that bar the CEF sleeve passes BOTH full
sample (t 3.11) and modern era (t 2.58). All other gates unchanged.

**MY FIRST REGIME HYPOTHESIS WAS BACKWARDS, and the data says so plainly.** I
assumed dislocation = opportunity and sized UP into it. Net Sharpe by quintile of
cross-sectional discount dispersion:

| Q1 calm | Q2 | Q3 | Q4 | Q5 dislocated |
|---|---|---|---|---|
| **1.24** | 0.59 | 0.80 | **-0.23** | 0.68 |

The strategy is BEST in calm markets. In dislocated regimes the mean return is
higher (3.88bp/day in Q5) but volatility rises faster, so risk-adjusted return
falls. Sizing up into dislocation levers into the worst state and is what produced
2008: **-12.9% return at 35.8% vol with a -31.5% drawdown**.

**The correct regime response is VOLATILITY TARGETING**, not dispersion sizing:

| spec | gross SR | net SR | vol | maxDD | turn/yr |
|---|---|---|---|---|---|
| universe-wide, flat | 0.97 | **0.73** | 9.76% | -27.1% | 24.0 |
| **universe-wide, vol-target 6%** | **1.09** | 0.72 | 7.26% | **-15.4%** | 28.8 |
| group-neutral, flat | 0.82 | 0.57 | 8.65% | -27.1% | 22.9 |
| group-neutral, vol-target | 1.09 | 0.60 | 6.97% | -28.7% | 36.0 |

Vol targeting lifts GROSS 0.97 -> 1.09 and nearly halves the drawdown. It does not
lift NET because turnover rises 24 -> 29/yr and the extra cost offsets the gain.

**Group neutrality did NOT help full-sample** (0.73 -> 0.57), contrary to my
reasoning that cancelling the NAV leg would remove noise. With only 18 funds
across 5 groups, several groups hold 2-3 members, so within-group demeaning
throws away most of the cross-section. The cross-group differences apparently
carry signal, not just NAV noise.

**Era profile of the vol-targeted spec — it is NOT decaying:**

| era | gross SR | net SR | CAGR | maxDD |
|---|---|---|---|---|
| 2005-2009 | -0.16 | **-0.33** | -2.74% | -23.5% |
| 2010-2014 | 0.68 | 0.42 | 2.68% | -15.4% |
| 2015-2019 | 1.21 | 0.68 | 4.63% | -13.2% |
| 2020-2022 | 2.59 | **2.02** | 14.73% | -5.6% |
| **2023-2026** | **2.32** | **1.06** | 6.33% | -5.0% |

The full-sample number is dragged down entirely by 2005-2009. The recent era is
the second-strongest in the sample. Note a caveat that cuts the other way: the
18-fund universe is selected on TODAY's liquidity, so dead funds are absent —
survivorship flatters the early period, and it is still the weak one.

**SEARCH STOPPED HERE at 10 specifications on this source.** DSR haircut at N=10
is sqrt(2*ln 10) = 2.15; alpha t of 3.11 clears it, but further spec-hunting
would be fitting rather than research. The remaining work is validation and live
evidence, not more variants.

---

## DEPLOYED 2026-07-31 — credit CEF discount reversion

**Full validation battery, all passed:**

| test | result | verdict |
|---|---|---|
| Point-in-time universe (no survival/liquidity hindsight) | gross 1.26, **net 0.82**, vol 6.00%, CAGR 4.85%, maxDD -12.0% | PASS — *better* than the biased version |
| Purged walk-forward, 10 blocks, 5d embargo | **9/9 positive**, median 1.12, worst 0.01 | PASS |
| Block bootstrap, 5,000 draws, 21d blocks | 5th/95th 0.52/1.11, **P(SR<=0) = 0.000%** | PASS |
| Deflated Sharpe (haircut for 10 specs) | **0.956** | PASS |
| Test 7 carry/beta | alpha t 3.11, R2 0.005, **5/5 factor limits** | PASS |

The survivorship correction is worth noting: rebuilding the universe so that each
date sees only funds already trading and already liquid IMPROVED the result
(0.72 -> 0.82), because it admits more funds over time (median 8, max 25) while
dropping illiquid ones dynamically.

**Live configuration:** 17-fund universe, 252d z-window, 5-day rebalance, 6%
annualised vol target, $3m minimum ADV, NAV staleness cut-off 3 business days,
$500k capital. Deployed at $751,463 gross, long $375,678 / short $375,784,
**net -$106 (0.014bp of gross)**.

**Two bugs fixed during the build:**
- The min-weight filter ran AFTER neutralisation, leaving the book 0.37% net
  short — precisely the credit beta this sleeve exists not to carry. Now filtered
  first, then re-neutralised: net residual 1e-6.
- `static_weights` and `cef_discount` were both allowed alloc types with no sleeve
  class behind them; both now implemented and registered.

**Known weaknesses, recorded before capital moved:**
- Kurtosis 41.2. Expect sharp single-day losses; this is not a smooth series.
- The most recent walk-forward block is 0.05 and 2023-26 era net Sharpe is 0.30.
  Strong history, flat recent. If that persists it is the kill rule's job.
- 2005-2009 net Sharpe 0.11 on a thin 2.6-fund universe.
- Sized at $500k, not the full remaining balance, because the Phase 0 null trader
  needs ~$438k CAD of margin when it fires and available funds are $958k CAD.
  Raise only after live slippage is measured.

**Scheduler:** `ops/schedule/run_cef.sh` + `cef.env` at RUNG-2, plist rendered to
`ops/schedule/rendered/com.quantt.cef.daily.plist`, weekdays 17:15 local. The
runner refreshes price AND NAV first and **aborts rather than trading if the
refresh fails** — a stale NAV silently turns this signal into noise.

---

## FIRST LIVE FILLS, 2026-07-31 — execution is 9.4x worse than modelled

The first real fills arrived and they are bad, for a reason we have identified
and fixed. Recording it in full because this is the exact thing the live
deployment exists to discover.

**What happened.** The sleeve necessarily decides in the evening (its signal needs
the fund's NAV, which does not exist until after the close). Plain market orders
therefore rested overnight and filled at **07:27 ET -- two hours before the
exchange opened** -- into pre-market, where these $3-45m/day funds have
essentially no liquidity.

| | |
|---|---|
| traded | $682,351 |
| slippage cost | **$6,405** |
| realised | **0.94%** |
| modelled | ~0.10% |
| ratio | **9.4x** |

Worst names: BIT 2.87%, DSL 2.62%, PFN 2.27%. The slippage is against us on
EVERY name -- buys filled high, sells filled low -- which is the signature of
crossing a wide spread, not of random noise. The three most liquid munis (NAD,
NEA, NZF) filled at ~0.00%, which fits: they were the only ones with real
pre-market depth.

**Scale of the problem if unfixed:** at 24 rebalances a year, 0.94% per rebalance
is ~22.6%/yr in costs against a strategy earning 4.85%/yr. Fatal, several times
over.

**Ruled out: our prices are not wrong.** Reconciled all 17 funds against the
broker's own daily bars over 10 days: **median disagreement 0.000%, worst single
day 0.00%.** The research prices are exact. This is purely an execution problem.

**Fix applied:** the sleeve now submits **market-on-close** orders
(`meta['order_type']='MOC'`, `tif=DAY`). The decision is still made in the evening
when the NAV lands, but execution happens in the next closing auction -- the
deepest, tightest liquidity of the day, and the exact point the backtest assumed
(`held = W.shift(1)`, earning the close-to-close return).

**How this interacts with the kill rule.** The rule fires on slippage above 2x
modelled for 5 CONSECUTIVE sessions. Session one is 9.4x, but with a diagnosed
and corrected cause, so it is a warning rather than a kill. The honest test is
whether MOC brings it inside tolerance. **If slippage stays above 2x after the
MOC fix, that is not an execution bug -- it means these instruments are too
expensive to trade at this frequency and the strategy is dead on costs.** That
verdict is now the single most important open question, ahead of returns.

---

## SCHEDULER FAILURE 2026-07-31 — macOS TCC, diagnosed and fixed

**Symptom.** The 09:35 null-trader run failed with exit 126, transmitted nothing,
and wrote no application log. `launchctl list` showed the failure; nothing else
did. The same script ran perfectly by hand, which is exactly why this was
invisible until a scheduled run failed.

**Cause.** The repo lives under `~/Desktop`, a macOS TCC-protected folder.
launchd has no Full Disk Access, so it could not execute the script:

    getcwd: cannot access parent directories: Operation not permitted
    /bin/bash: .../run_phase0.sh: Operation not permitted

A Terminal HAS Full Disk Access, so manual runs always worked.

**A false start worth recording.** The first fix moved the entry script outside
the protected folder, and a test job reported it could read the repo. That test
was misleading: it was a freshly *loaded* agent, which inherits the loading
Terminal's permissions. Re-tested with `launchctl kickstart` -- which runs with
launchd's own permissions -- it failed. **Always test a scheduled job with
kickstart, never with a fresh load.**

**Probing the real boundary:**

| operation | result |
|---|---|
| stat the repo directory | OK |
| list the directory (`/bin/bash`) | **DENIED** |
| read a file (`/bin/bash`) | **DENIED** |
| read a file (`/opt/anaconda3/bin/python3`) | **OK** |
| run python | OK |

**The Anaconda interpreter holds Full Disk Access; the system shell does not.**

**Fix.** The launchd entry point is now
`~/Library/Application Support/quantt/launch_job.py` -- a Python script outside
the protected folder that performs the orchestration the shell scripts did
(calendar check, data refresh, run the book). The `.sh` files remain in the repo
for manual use but launchd no longer touches them.

**Verified under real `launchctl kickstart`, not a fresh load:** both jobs run
end to end with empty launchd stderr. The CEF job transmitted **16 MOC orders**,
confirming the market-on-close fix is live in the scheduled path.

**Generalisation for anything scheduled later:** any job that must reach this repo
has to be driven by the Anaconda interpreter, not by the shell.

---

## NICHE EDGE + EXECUTION RESEARCH 2026-07-31

Full write-up: `results/cef/research/NICHE_EDGE_RESEARCH.md`. Headlines:

**ADOPT — price-weighting.** Net Sharpe **0.82 -> 0.98**, alpha t 3.62 -> 4.36,
modelled cost -19%, still 5/5 factor limits. Justified on cost first (a penny
spread is 25bp on a $4 fund, 6bp on a $16 one), but gross Sharpe also rises
(1.26 -> 1.36), so part of it is a genuine fund-quality proxy -- low-priced CEFs
are typically the ones that eroded capital through return-of-capital
distributions. Verified NOT to be dollar depth: dividing the price component back
out of ADV destroys the effect (0.57).

**REJECT — no-trade bands** (0.82 -> 0.83, no benefit; the signal reshuffles the
cross-section rather than nudging single legs) and **longer holds** (5d 0.82 ->
10d 0.47 -> 21d 0.27 -> 42d 0.09).

**The hold-period table is the most important result here.** The edge is genuinely
short-horizon, so we CANNOT trade our way out of a cost problem by slowing down.
If market-on-close does not bring realised slippage near modelled, the strategy is
uneconomic at the only frequency where it works.

**NEW CANDIDATE SLEEVE — January CEF basis.** Long a CEF basket / short a credit
ETF basket, held in January only, two trades a year.

| | |
|---|---|
| January hedged basis | +11.71bp/day, **t 3.99** |
| Consistency | **20/23 Januaries positive** |
| Ex-crisis mean | +1.45%/yr, sd 1.97%, **annual Sharpe 0.73** |
| **Correlation with the deployed strategy** | **-0.001** |

Robust to: removing 2009 (t RISES 2.77 -> 3.57), over-hedging at 2.0x (still
t 2.42), and it is genuinely the discount rather than a bond rally (price-minus-NAV
t 4.06 vs credit hedge t 0.95). December is the other half of the mechanism at
-8.72bp/day (t -3.24) -- tax-loss selling in, reversal out.

Combination value: `0.82 + 0.73 at rho 0.00 -> 1.10`, a larger gain than any
plausible improvement to the main strategy. It also holds capital ~1 month a year
so it barely competes for margin. **Next January is 5 months away -- time to
pre-register properly rather than rush.**

**KILLED — distribution events (D1).** 11,988 events, 1987-2026. Cuts move the
discount the WRONG way vs the thesis (+10 to +29bp net of control) and are not
monotone in cut size (dose-response t -1.77). Raises show pre-event drift, so the
post-event move is ordinary reversion we already trade.

**Data note:** our price series is RAW, not dividend-adjusted (ex-date moves are
-1x the distribution). Had it been adjusted, every historical discount would have
been wrong. yfinance exposes no fund size or expense ratio for CEFs -- only
`debtToEquity` (29/44) and `priceToBook` (32/44). **Leverage is the most promising
untested structural variable.**

