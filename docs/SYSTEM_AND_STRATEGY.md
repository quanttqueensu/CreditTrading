# QUANTT — the system, the strategy, and everything known about both

**Written 2026-09-06. Audience: a competent agent (human or otherwise) picking
this up cold and expected to improve it.**

This document is deliberately opinionated about what is *established*, what is
*measured but conditional*, and what is *unknown*. Those three categories are
treated very differently here and you should treat them differently too. Where a
number appears, it was measured, and the script that reproduces it is named.

> **⚠ CORRECTED 2026-09-10 — THIS FILE HAD NO BANNER AND STATES TWO CLAIMS THE
> REPO HAS SINCE RETRACTED.** Its own header promises that "where a number
> appears, it was measured, and the script that reproduces it is named". Three
> of its live numbers no longer reproduce, and §7.3 was a *trading* fault
> described as a reporting one:
>
> - **"armed on 3 of 26 sessions"**, in three places → re-measured 2026-09-10:
>   **5 of 29**. Corrected in place; the ratio is the one number here that moves
>   every session, so re-run the command rather than quoting either figure.
>   `echo "$(grep -la 'ARMED:' ops/schedule/logs/cef_*.log | wc -l) of $(ls ops/schedule/logs/cef_*.log | wc -l)"`
> - **"only 2026-07-31 and 2026-09-01 have broker-confirmed executions"** (:284)
>   → **2026-09-08 has 18 more**; 294 fills over three dates. And those 18 are
>   **uncosted** — `slippage.csv` has no 09-08 row.
> - **"the ledger disagrees with the broker on all 17 positions (~$223k), order
>   sizing is *unaffected* — `arm()` re-seeds from the broker"** (:285-287) →
>   **both halves are false.** All 17 CEF names match the broker share-for-share
>   (CEF gross divergence $0.00); 15 non-CEF symbols diverge. And the re-seed
>   does **not** protect you in two cases: where the broker reports **no row at
>   all** for a flattened symbol, `arm()` never visits it (JAAA), and where a
>   symbol is **contested** by two books, `arm()` deliberately adopts the ledger
>   rather than the account net (LQD). Both are trading faults. See
>   `results/ops/LEDGER_DIVERGENCE_2026-09-10.md` and CLAUDE.md landmine 3.
> - **120.6bp at :309 and 100.5bp at :115 are the same session** (2026-07-31),
>   194 lines apart, and are *different statistics* — 120.6 is the simple mean
>   of the 16 rows, 100.5 the share-weighted mean. Neither is labelled as such.
>   `ops/capture_fills.py` and the dashboard both report the simple mean.

---

## 0. Orientation in one page

QUANTT runs a **systematic credit closed-end-fund discount-reversion strategy** on
a **$500,000 IBKR paper account (DUQ199038)**. Real capital is expected this year.

The trade: a closed-end fund publishes a net asset value daily and its shares
trade at whatever the market pays. Buy the funds unusually cheap against *their
own* discount history, short the ones unusually rich, in equal dollars.

**Why it works and did not get arbitraged away:** a CEF has a **fixed share count
and no authorised participants**. Nothing can create or redeem shares against the
basket, so no mechanism drags price back to NAV. The identical idea in ETFs died
as the AP mechanism compressed the gap from 188bp (2008) to 3.8bp (2026). Credit
CEFs sit at discounts averaging −3.2% with a standard deviation near 6%.

**The alpha is probably real. It is NOT "settled", and this line used to say it
was.** IC −0.074 (t −11.6) at the traded horizon over 27 years, present in every
sub-period; block bootstrap P(SR≤0) = 0.000%; and gross Sharpe went **1.23
in-sample → 1.75 out-of-sample** when the sealed holdout was opened. But
**8/9** purged walk-forward blocks positive, not 9/9 — re-measured 2026-09-10,
`python3 scripts/cef/validate.py --trials 48`, panel to 2026-09-09: worst block
**−0.15** (2018-01-05..2020-03-06), median 1.05, gross 1.27, net 0.83. And it
**fails its deflated-Sharpe bar at the real trial count**: DSR **0.870 FAIL**
at CEF = 48 against a bar of 2.783. It printed PASS for months only because
`validate.py` hard-coded `N_SPECS_TRIED = 10`. Run the command; do not quote
these.

**The problem is capture.** Gross Sharpe ~1.2; net Sharpe after realistic costs
was **0.33**, and **0.10** once the short leg is charged its measured borrow. The
entire research agenda is: *how much of a real edge can we actually keep?*

**The other problem is operational.** The book has armed on **5 of 29 sessions** (re-measured 2026-09-10).
Most of the "live" track record is modelled fills for sessions that never traded.
Fixing that is worth more than any research in this document.

---

## 1. The strategy, precisely

### 1.1 Signal

For each fund $i$ on day $t$, with price $P$ and net asset value $N$:

$$d_{i,t} = 100\cdot\frac{P_{i,t}-N_{i,t}}{N_{i,t}}
\qquad
z_{i,t} = \mathrm{clip}\!\left(\frac{d_{i,t}-\mu^{252}_{i,t-1}}{\sigma^{252}_{i,t-1}},\ \pm 4\right)$$

Both rolling moments are **shifted one day** — point-in-time, no lookahead. The
252-day window is frozen. (It was changed to 63 on 2026-07-31, the sealed holdout
was opened hours later, 63 **failed** out of sample, and it was reverted. That
episode is the single most instructive event in this project's history; see §7.)

### 1.2 Weights

$$w_{i,t} = -\frac{z_{i,t}-\bar z_t}{\sum_j|z_{j,t}-\bar z_t|}
\;\times\;\mathrm{clip}\!\left(\frac{6\%}{\hat\sigma^{63}_t},\,0.2,\,2.5\right)$$

Three things to understand about this:

- **Cross-sectional, not absolute.** A fund is cheap relative to *today's mean z*,
  not relative to zero. A fund at a wide discount outright is still sold if every
  other fund is wider. This is what makes the book dollar-neutral by construction.
- **Ranked against its own history, not against peers.** A leveraged municipal CEF
  structurally trades wider than a multi-sector one — different fee, buyer,
  leverage. Ranking on the raw discount would be a permanent long-muni bet dressed
  up as a signal.
- **Volatility-targeted, and this was measured, not assumed.** Net Sharpe by
  dislocation quintile runs **1.24 / 0.59 / 0.80 / −0.23 / 0.68** from calm to
  stressed. The strategy is *best in calm markets*: in stress, returns grow but
  volatility grows faster. A constant-notional book therefore takes its worst
  losses exactly when each unit of risk pays least — that produced a −31.5%
  drawdown at 35.8% vol in 2008. Vol targeting cut full-sample drawdown −27% → −12%.

### 1.3 Trading policy — **changed 2026-09-06**

Previously: refresh weights every 2 trading days, hold in between.

**Now: a no-trade band at 4.8%.** The signal is recomputed every session; a
position is left alone unless it is more than 4.8% (in weight) from target, then
traded back to the **band edge, not to target**.

This is the Constantinides (1986) / Davis & Norman (1990) result: under
*proportional* cost the optimal policy is a band, and the boundary is where you
stop, not where you aim. Our participation is ~0.7% of ADV so we pay half-spread
(proportional) and essentially no impact — the proportional-cost case exactly.

| policy | gross SR | turn/yr | net@15bp | net@30bp |
|---|---:|---:|---:|---:|
| calendar 2d (old) | 1.20 | 31.1 | 0.33 | **−0.55** |
| **band 4.8% (live)** | 1.16 | 17.6 | **0.66** | **+0.17** |

Two distinct wins. **Net Sharpe doubles on 43% less trading** — and at *matched*
turnover the band earns more *gross* too, because a calendar's information loss
compounds with its interval while a band only ever discards small moves. Second,
**every calendar configuration goes negative at 30bp; bands ≥4.8% never do.**
Cost is the input we do not know, so prefer the policy least sensitive to it.

The width was **derived, not swept**: cube-root law $h^*=(3c\sigma_w^2/2\kappa_w)^{1/3}$
on measured target-weight dynamics gives 4.26% at 15bp, 4.85% at 22bp; scaling
verifies exactly ($h(30)/h(15)=1.260$ vs $2^{1/3}=1.2599$). 6.4% topped the swept
column and was deliberately **not** chosen. Pre-registration:
`results/cef/PREREG_BAND_2026-09-06.md`.

### 1.4 Execution

**MOC (market-on-close), filling T+1.** The signal is only computable after the
close — a fund's NAV does not exist until then — so the sleeve necessarily decides
in the evening. A plain market order would rest overnight and fill at the next
open, the worst liquidity of the day in instruments trading $3–45m. On 2026-07-31
overnight market orders realised **100.5bp** against a **32.6bp breakeven**; the
method was changed the same week. The one MOC session on record realised **2.8bp**.

Held weights are therefore `W.shift(2)`: decided at $t$, filled at $t+1$'s close,
earning the $t+2$ return. **Every backtest in this repo must reproduce that**, and
`evaluate()` in `scripts/cef/band_frontier.py` is the canonical implementation.

### 1.5 Universe

17 credit CEFs, frozen: AWF BIT DSL HYT JFR MHD MQY NAD NEA NVG NZF PCN PDI PDO
PFN PHK PTY. Screened at `min_adv_usd = $3m`, which binds hard — median eligible
universe is **8 funds**. `data/cef/cef_universe.csv` holds 44; the other 27 have
**never informed a specification decision** and are reserved as a comparison set.

---

## 2. What is established, what is conditional, what is unknown

Keeping these separate is the most important discipline in this project.

### 2.1 Established — do not re-litigate

| claim | evidence |
|---|---|
| The edge exists | IC −0.074, t −11.6, 27 years, present in **every** sub-period |
| It is not credit beta | β +0.013, R² 0.0008, alpha +17.7%/yr |
| It is not one name | leave-one-out gross Sharpe spans 2.23–2.93 |
| It survives out of sample | purged walk-forward **8/9** (re-measured 2026-09-10; this said 9/9), worst block −0.15; **gross 1.23 IS → 1.75 OOS** |
| It clears the multiplicity haircut | **NO.** DSR **0.870 FAIL** at N=48, bar 2.783. The only row here that does not pass |
| It is not luck | block bootstrap, 5,000 draws, P(SR≤0) = 0.000% |
| Reversal does not explain it | price-only control IC −0.046 vs −0.074 |

### 2.2 Measured but conditional

- **Borrow costs 1.22%/yr ≈ 0.23 Sharpe** — measured once (2026-09-06) and applied
  to 21 years. A forward estimate, not a historical cost.
- **The joint optimiser beats the band** (net 0.90 vs 0.70 matched) — but on
  research code one day old, with 3× worse turnover stability.
- **Σ⁻¹α raises gross 28%** — but is cost-conditional: wins at 5bp, loses at 30bp.

### 2.3 Unknown, and the unknowns dominate

- **What execution actually costs.** One MOC session. n=1, dispersion ±93.8bp.
  Everything about whether this strategy is viable turns on this number, and
  §7.1 of `docs/PLAN.md` needs ~60 sessions to pin it.
- **Whether the paper record means anything.** 22 of 24 ledger trade dates are
  modelled fills for sessions that never traded.
- **Survivorship.** The panel contains only funds alive today. Every CEF that
  closed or merged across 27 years is absent. This biases everything upward by an
  amount these files cannot measure.

---

## 3. Architecture

188 Python files, ~37,800 lines. The parts that matter:

```
src/deploy/                  the live trading framework
  sleeve.py                  Sleeve ABC, MarketState, PositionTarget, RiskVerdict
  sleeves/cef_discount.py    THE STRATEGY. signal, weights, band, risk_check
  sleeves/{credit_rv,null_trader,static_weights}.py
  portfolio.py               PortfolioOrchestrator: fan out to sleeves, roll up
  broker/ibkr.py             IBKRBroker: arm(), place_targets(), shadow ledger
  exec_ledger.py             cost model (spread, impact, financing)
  registry.py                spec -> sleeve wiring
  run_book.py                CLI entry: one session for one book
  lib/                       financing, margin, netting, odd_lot, vol_target...

ops/                         operations, not research
  specs/*.frozen.json        FROZEN parameters. changing one is a governance act
  books/*_book.json          capital, limits, which sleeves are in which book
  books/*_live/_ibkr_shadow/ the shadow sub-ledgers (nav, positions, trades, fills)
  preflight.py               is it safe to trade? returns arm=True/False
  capture_fills.py           pull REAL executions before TWS forgets them
  halt.py                    heartbeat, alerts, kill switch
  doctor.py                  why is the plumbing broken
  schedule/                  launchd wrappers, NYSE calendar, env files

scripts/cef/                 research. NOT on the live path
  band_frontier.py           the trading-policy frontier (canonical evaluate())
  covariance_construction.py Ledoit-Wolf Sigma, Sigma^-1 alpha, BR_eff
  ou_score.py                the OU/kappa score (measured, rejected)
  joint_cost_optimiser.py    the joint cost-aware optimiser
  fetch_borrow_rates.py      daily borrow panel
  borrow_impact.py           what borrow does to net Sharpe
  borrow_capacity.py         where availability binds; capacity
  plan_diagnostics.py        reproduces every number in docs/PLAN.md
  validate.py                the original backtest

src/analysis/l1_meanvar.py   the L1 mean-variance solver (FISTA + KKT polish)

dashboard/                   READ-ONLY monitor, Flask, :8787
data/cef/                    price/NAV/borrow panels (parquet + csv)
docs/                        PLAN.md, RESEARCH_STATE.md, this file
results/cef/                 dated findings notes and pre-registrations
```

### 3.1 The session contract

**`launch_job.py` lives OUTSIDE the repo**, at
`~/Library/Application Support/quantt/launch_job.py`. This is not an accident and
you must not "fix" it. The repo is under `~/Desktop`, which macOS protects with
TCC. A launchd agent has no Full Disk Access: on 2026-07-31 a scheduled run died
with `exit 126, getcwd: Operation not permitted`, having transmitted nothing and
written no log. Probing showed `/bin/bash` is denied and `/opt/anaconda3/bin/python3`
is allowed. So the scheduled work is driven from Python, from outside the
protected folder. **The shell scripts in `ops/schedule/` are for manual use only
and launchd does not execute them.**

A session has four phases with *different failure policies*:

| phase | on failure |
|---|---|
| 1. REFRESH prices/NAV | do not trade (a stale NAV is a blind signal, not a cheap fund) |
| 1b. PANELS (borrow) | log and continue — never blocks a session |
| 2. PREFLIGHT | do not trade, still log |
| 3. TRADE | halt + alert |
| 4. CAPTURE fills | **runs unconditionally, even after 1–3 fail** |

Phase 4 is unconditional because `ib.fills()` serves the current TWS session only
and TWS force-restarts daily. A fill not captured today is **gone**. The old
design captured nothing, which is why 302 real executions from 2026-07-31 exist
nowhere.

### 3.2 Safety machinery you must not weaken

- **`arm()`** adopts quantities from `ib.positions()` before every live session,
  because *the ledger is a local reconstruction and the account is the fact*. On
  2026-07-31 the ledger read flat while the account held $2.07M gross; the next
  fire would have re-bought the entire book. `arm()` raises `NotArmed` rather than
  transmitting on unverified state.
- **Same-day guard.** The trade phase is not idempotent and there is no dedupe at
  the broker. A second armed run stacks a second order set — worse than a
  duplicate, because `arm()` reads positions that do not include the still-unfilled
  MOC orders, so both sets fill in the same auction and the book doubles.
- **DRY_RUN=1 is a human hard halt** and always wins. `DRY_RUN=0` means "trade *if
  preflight agrees*", not "trade".
- **Sibling-book attribution.** Three books share one IBKR account with
  overlapping tickers. `_live_positions` is per-sleeve; `reconcile()` checks the
  tagged books sum to `ib.positions()`. Never take a symbol from the account net.
- **The dashboard is read-only by design.** Exactly one non-GET route
  (`/api/connect`, which starts IB Gateway and nothing else). No code path
  transmits an order. Keep it that way.

### 3.3 Books

| book | spec | capital | role |
|---|---|---:|---|
| cef_discount | `cef_discount.v6.20260906` | $500k | the strategy |
| credit_rv | `credit_rv.v1.20260730` | $1.0m | second strategy |
| null_trader | `null_trader.phase0.20260730` | $640k | **control**: no edge, measures what real fills cost |
| 5 benchmarks | `bench_b{1,3,4,5,6}` | $20k ea | zero-skill baselines through the identical order path |

The null trader and the benchmarks are not decoration. They are the only way to
separate "our signal is bad" from "our execution is bad".

---

## 4. Operational reality as of 2026-09-06

**Read this before trusting any live number.**

1. **The book has armed on 5 of 29 sessions** (re-measured 2026-09-10; this
   said 3 of 26). 08-03→08-28 (21 sessions) were all
   dry runs because `config/.env` had `IBKR_PORT=7497` (TWS paper) while the
   gateway serves **4002**. Corrected by `ops/switch_broker.py` at 2026-09-01
   16:58. Two more sessions lost to the gateway being down. Preflight caught every
   one correctly and refused to trade — the system behaved properly, it just was
   not trading.
2. **22 of 24 ledger trade dates are modelled fills** for sessions that never
   traded. Broker-confirmed executions exist on **three** dates, not two —
   2026-07-31 (257), 2026-09-01 (19) and **2026-09-08 (18)**, 294 in total
   (corrected 2026-09-10; this said "only 07-31 and 09-01"). The 09-08 fills
   are **uncosted**: `slippage.csv` carries no row for that date.
3. **RETRACTED 2026-09-10 — this read "the ledger disagrees with the broker on
   all 17 positions (~$223k), order sizing is *unaffected* because `arm()`
   re-seeds from the broker".** Both halves are false. Measured from
   `results/ops/BROKER_SNAPSHOT_2026-09-10.json` (read-only, 11:35:29 ET):
   **all 17 CEF names match the broker share-for-share**, CEF gross divergence
   **$0.00**. **15** symbols diverge, all `null_trader`/benchmark names, worst
   JAAA 1,503 then LQD 858. And the re-seed does not protect sizing where the
   broker reports no row (a flattened symbol is never visited) or where a
   symbol is contested by two books (`arm()` adopts the ledger by design).
   Reported NAV and P&L are wrong *and so is sizing*, on those two paths.
4. **A non-armed session is silent.** It writes `ok_not_armed` to the heartbeat
   and raises no alert, which is why a 21-session outage went unnoticed for a
   month. **This is the highest-value operational fix available.**
5. **Automatic risk controls are disabled.** All three sleeves' `risk_check`
   return OK unconditionally, `book_drawdown_suspend_pct` is 99.0, and the frozen
   spec's declared `kill_drawdown`/`halve_drawdown` are read by **no code path**.
   Justified in writing by "there is no real capital at risk" — a justification on
   a clock.
6. **No market-data subscription.** Live quotes return error 10089; the API works
   only under `reqMarketDataType(3)` (delayed).

---

## 5. Costs — the thing that decides everything

Breakeven is **32.6bp** per unit turnover (full sample), 28.9bp for 2021–26.

### 5.1 Spread

| session | fills | realised | modelled | method |
|---|---:|---:|---:|---|
| 2026-07-31 | 16 | **120.6bp** | 15.5 | overnight market orders — abandoned |
| 2026-09-01 | 15 | **2.8bp** | 12.1 | MOC |

Beware the logged `realised/modelled = 4.59x` — it averages the pre-MOC disaster
that *caused* the switch to MOC. Split by session before drawing conclusions.

### 5.2 Borrow — measured 2026-09-06, previously never charged at all

`scripts/cef/validate.py:93` computes cost as half-spread only. Every Sharpe this
programme quoted before 2026-09-06 was **before financing the short leg**. The
live ledger applied a flat +50bp calibrated (by its own docstring) for *"liquid
Treasury/IG ETFs, general collateral"*. Credit CEFs are not general collateral.

Source: `https://www.interactivebrokers.com/shortstock/usa.txt` (public, no auth;
the old FTP host is retired). Cross-checked against TWS generic tick 236.

Median fee 0.83%, mean 2.29%, **max 10.56%**. Drag **1.22%/yr ≈ 0.23 Sharpe**,
which scales with *holdings*, not turnover — **trading less does not reduce it.**

**Three names are ~67% of the cost: HYT (10.56%), NAD (10.21%), NVG (3.70%).**
Two are Nuveen munis, i.e. the same names carrying PC2 (§6.1). The concentration
problem and the borrow bill are the same trade.

> **⚠ CORRECTED 2026-09-10.** This read *"70% of the cost"* with fees 9.98% and
> 4.23% for NAD and NVG. The share was computed by `borrow_impact.py`, which
> apportioned the bill across the average short weights of **`calendar(T, 2)`** —
> the retired policy — rather than the live band. Borrow scales with *holdings*,
> and the band holds a different book, so the per-name shares were not the shares
> we pay. On the live 4.8% band the top three are **28.2 / 27.1 / 12.1 = 67.4%**,
> and two names move materially: **JFR 2.3% → 3.7%** and **AWF 1.7% → 2.8%**.
> The conclusion is unchanged and the ranking is stable; only the arithmetic
> moved. Fee levels quoted here are the panel's own, re-read 2026-09-10.
> The script now takes the width from the frozen spec.

The premium hypothesis was **refuted**: PHK (+22.6% premium) borrows at 1.06%.
Premium does not predict borrow cost here.

### 5.3 Capacity — the first estimate this programme has

Availability is a separate constraint from cost and binds on different names.
On the retired public file's pools, **NAD's borrow pool supports ~$45,000 of
capital**, NVG ~$278,000; at the actual $500k **11.4% of the desired short book
is unbuildable**, 27.8% at $5m, 52.5% at $25m, and capacity is roughly $5m.

> **⚠ DISPUTED 2026-09-10 — do not size anything on these figures.** Every number
> in this section comes from IBKR's public `shortstock` file, which was **retired
> on 2026-09-09**. Its documented equivalent, TWS **tick 236**, had been returning
> NaN under error 10197 because the dashboard was opening a broker session per
> widget refresh; with that fixed the tick answers, and on the first day the two
> could be compared they disagreed badly on the name the whole thesis rests on:
>
> | | we short | file (09-08) | tick 236 (09-10) | ratio |
> |---|---:|---:|---:|---:|
> | NAD | 6,550 | **3,000** | **83,942** | 28× |
> | NVG | 4,679 | 20,000 | 149,125 | 7× |
> | MHD | 8,856 | 250,000 | 102,491 | 0.4× |
>
> On the file's pools 18.7% of today's short book is unbuildable; **on the tick's,
> 0%.** That is the difference between a constraint worth a pre-registered spec
> change and no constraint at all. One paired observation cannot settle it — the
> two may measure different things (indicative pool vs currently-shortable, and
> whether shares already lent to us are netted out). **W8 Part A pairs them over a
> week and owns the resolution.** Until then this section is unverified.

---

## 6. Known structural problems

### 6.1 Effective breadth is 2.24, not 17

Decomposing book variance on the sleeve's own weights:

| component | share | what it is |
|---|---:|---|
| PC1 | 3.6% | market direction — correctly neutralised |
| **PC2** | **65.7%** | **muni vs taxable** (+0.32 on **four Nuveen munis (NAD, NEA, NZF, NVG) plus two BlackRock (MQY, MHD)** — corrected 2026-09-10; earlier text said "six Nuveen munis", which matters because the two sponsors lever differently (Nuveen via SIFMA-linked tender option bonds, BlackRock via preferred shares) and so cannot share a financing conditioner, negative on the other eleven) |
| PC3 | 9.6% | quality / duration |
| PC4–17 | 21.1% | genuinely idiosyncratic |

$BR^{\text{eff}} = 1/\sum_k v_k^2 = \mathbf{2.24}$. Since $IR \approx IC\sqrt{BR}$,
breadth computed on the name count **overstates by 2.75×**. The dollar-neutral
construction kills market beta and then puts two-thirds of the risk into one
unmanaged spread bet. Lee, Shleifer & Thaler (1991) predicts exactly this: CEF
discounts share a large common component.

### 6.2 The vol target is ~1/12 Kelly

Full Kelly on a net Sharpe of 0.7 is a 70% vol target; half-Kelly 35%. We target
**6%**. The scalar averages 1.50, is pinned at its 2.5 cap on 5.2% of days, and
realises only 4.95% vol against the 6% target. Reg T caps gross at 2×; Portfolio
Margin reaches ~10× on a hedged book. **This is paperwork, not research** — but it
is gated on borrow (§5.2), because levering a 0.10 net Sharpe multiplies a drag
that is most of the return.

---

## 7. The graveyard — do not rebuild these

Each was measured and failed. Rebuilding one is a wasted week.

| idea | verdict |
|---|---|
| **`z_window = 63`** | Chosen on 2005–2023 with the holdout sealed. Opened hours later: **gross 1.75 but net −0.298**. Reverted to 252. *The canonical lesson: picking the argmax of a swept column.* |
| **OU / per-name κ score** | Measured 2026-09-06, **withdrawn**. κ exposure curve is flat below 0 and declining above; live setting is at the top. **Mechanism:** OU stationary variance is $\sigma^2/2\kappa$, so $\sigma^d\propto\sigma/\sqrt\kappa$ — the live z-score **already carries $\kappa^{1/2}$**. Measured slope of $\log\sigma^d$ on $\log\kappa$ = **−0.463** vs theory's −0.500. Multiplying by $(1-\phi^h)$ double-counts. |
| **Signal combination with price reversal** | Optimal combined \|IC\| 0.0748 vs 0.0747 for discount alone = **+0.1%**. Price signal 95% subsumed (weights −0.95/−0.05). |
| **Hard group (muni) neutrality** | Gross Sharpe 0.97 → 0.82. |
| **Sizing up on \|z\|** | Every threshold above zero *lowers* Sharpe: 0.81 → 0.40 → 0.29 → 0.27. |
| **Sizing up on dislocation** | Best in *calm* markets (§1.2). Produced −12.9% at 35.8% vol in 2008. |
| **Distribution data** | Failed twice — as a universe filter (1 of 8 variants beat baseline, chosen after looking at 8) and inside the Kalman (1.60 → 1.28). |
| **Cointegration pairs** | Gross 1.03 → net −0.16; needed 32.8× leverage against a 2× ceiling. |
| **Sequential Σ⁻¹α + band** | At matched turnover gross **1.07 — below plain α's 1.10**. The scalar band destroys what Σ⁻¹ buys. Use the joint objective instead (§8.1). |

**Also do not build:** machine learning (17 names, one feature, IC 0.075 — the
bias-variance trade-off is emphatically against it); regime-switching (the
dispersion-quintile table *is* the regime study, and vol targeting already
exploits it continuously); jump-diffusion (changes sizing, not signal);
Heston/SABR (we trade no derivatives); Almgren-Chriss scheduling (one auction at
<1% participation — there is nothing to schedule).

---

## 8. Open problems, ranked by value

### 8.1 The joint cost-aware optimiser — built, measured, **not deployed**

$$\max_w \; w'\alpha - \tfrac{\lambda}{2}w'\Sigma w - c\lVert w-w_{t-1}\rVert_1
\quad\text{s.t.}\quad \mathbf 1'w=0$$

The $\ell_1$ term induces a no-trade region *directly*, so the band is **derived**
rather than bolted on — and it is Σ-aware, unlike a per-name scalar band.

Turnover-matched at 17.6/yr — the **live** band's rate — **net@15bp 0.91 vs the
band's 0.67**, +0.24. Gross holds at 1.43 where sequential composition reaches
1.41 at 29.8 turns/yr, i.e. the joint objective gets there on 41% less trading.
Derived cost coefficient `c_model` = 20.1bp.

> **⚠ CORRECTED 2026-09-10.** This read *"matched at 14.2/yr: net@15bp 0.90 vs
> the band's 0.70, +0.28"*. Those figures were measured against `band(T, 0.064)`
> — the 6.4% width that was **deliberately not chosen** on 2026-09-06 — because
> `joint_cost_optimiser.py` hardcoded it as its baseline, in five places, and
> kept doing so for four days after the 4.8% band went live. Re-run against the
> live band the *conclusion strengthens*: the joint objective's edge over the
> deployed policy is **+0.24 at 15bp and +0.26 at 5bp**, not +0.19/+0.21 as the
> retired comparison implied. `c_model` moved 25.4 → 20.1bp because it is solved
> to match the baseline's turnover and the baseline's turnover changed.
> The scripts now read the width from the frozen spec
> (`scripts/cef/spec.py`), and a test fails the build if a `band()` call takes a
> bare literal again. **The "why not deployed" argument below is unaffected** —
> it rests on turnover stability and the ADV fork, neither of which this touches.

Implementation `src/analysis/l1_meanvar.py` (FISTA on $d = w-w_{prev}$, joint prox
for the ℓ1 term *and* the neutrality indicator, then an active-set KKT polish;
every solve returns a certificate and raises on failure). 8 tests pass;
independently verified c=0 → analytic Σ⁻¹α to 5.9e-17 and no feasible
perturbation improving the objective over 16,000 draws.

**Why not deployed:** turnover stability 36.9% vs 11.9% sd/mean across eras; it
*loses* 2013–16 (thin universe); and the ADV treatment is a real fork — letting
ineligible names stay as decision variables puts 28% of gross in untradeable
names and **loses**. Deploy after the band has live evidence, not before.

**Corrections to the naive theory, learned the hard way:** the per-name no-trade
condition $|\nabla_i|_{w_{prev}}<c$ is exact **only for diagonal Σ** (79%
agreement with the true KKT partition on the real panel); the no-trade region is
a **polytope**, not an ellipsoid (an ellipsoid is what an ℓ2 penalty gives); and
the IC does **not** drop out — it sets the alpha-to-cost ratio.

### 8.2 Ranked list

1. **Gateway uptime + alert on non-armed sessions.** Nothing else matters if the
   book does not trade. 5 of 29.
2. **Accumulate the fill record.** Cost converges ~60× faster than Sharpe: at ~15
   fills/session, 60 sessions gives SE ≈ 0.84bp against a 32.6bp breakeven.
3. **Reconcile ledger vs broker.** Reported P&L is currently wrong.
4. **Decide the vol target** against measured borrow and drawdown tolerance
   (§6.2). Doubling it doubles return at unchanged Sharpe — larger than every
   signal improvement combined.
5. **Deploy the joint optimiser** once the band has live evidence.
6. **Breadth.** `min_adv_usd = $3m` caps the median eligible universe at 8 names.
   $1m gives 37, at 0.44% participation — one-eleventh of the cost model's own 5%
   guard. Screen on **ticks, not ADV**: at $4.69–$17.07 a share, one cent is
   2.9–10.7bp against a 32.6bp breakeven.
7. **Compare on the 27 untouched names** before promoting any of them.

---

## 9. Research governance

- **Trials are counted permanently.** `docs/RESEARCH_STATE.md`. The CEF counter is
  at 47; the band is trial 48. The deflated-Sharpe haircut is $\sqrt{2\ln N}$, so
  every trial raises the bar for every result.
  **Amended 2026-09-09:** there are now **two** counters — **CEF (48)** and
  **GAMMA (0)** — each with its own bar, per the 2026-09-08 standing decisions.
  Note that `RESEARCH_STATE.md`'s own table still shows CEF at 18; that file has
  not been updated since 2026-07-31 and **48 is the canonical figure**, carried
  by `ESTIMATOR_NOTE.md` (+29 that session), `PREREG_BAND_2026-09-06.md`
  ("trial 48") and `DUST_ORDERS_2026-09.md` ("the CEF counter stays at 48").
- **Pre-register before the session that trades it.** See
  `results/cef/PREREG_BAND_2026-09-06.md` for the shape: what changes, why, what
  is committed in advance, what would falsify it, and the divergences from
  backtest stated *up front*.
- **Negative results are recorded against oneself.** `docs/PLAN.md` §0.3 records a
  claim its own author made and then measured to be false. Do this.
- **Holdouts are sealed and opened once.** The 27 untouched CEFs are the current
  one. Trading any of them consumes it.
- **D1–D7 failure taxonomy** in `docs/RESEARCH_AND_METHODOLOGY.md`.

### 9.1 House rules for code

- **NO SILENT FALLBACKS.** Never `except: pass`, never `fillna()` an invented
  value, never substitute a default for missing data, never degrade to a simpler
  method when something fails. **Raise, naming what was missing.** Two real
  examples from this repo: `nav_now = _nav_last(...) or 500000.0` sized every
  displayed target against an invented $500k book; `fee.fillna(fee.median())`
  charged an unmeasured name 0.83%/yr inside a confident-looking total. Both were
  dormant for months — that is exactly what makes them dangerous.
- **No lookahead.** Every estimated quantity uses data strictly before the date it
  is used on. State the alignment in a comment. Add runtime assertions.
- **A new frozen-spec key must default to current behaviour.** The code change
  alone should be a provable no-op, so that activation is one visible edit. The
  band was verified this way: sleeve output byte-identical with the key absent.
- **Docstrings explain WHY, not what.** Most of this codebase's real knowledge
  lives in them, especially the incident histories.

---

## 10. Landmines

1. **The repo path is hardcoded outside the repo.** `launch_job.py` has
   `REPO = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027")`. Moving the repo
   silently kills every job. It happened on 2026-08-31: the old path was
   *recreated* as an empty tree, the session logged into the ghost directory and
   died before the heartbeat, and the watchdog died the same way. There is now a
   fatal check that runs before any `mkdir`.
2. **`ops/schedule/rendered/*.plist` point at the OLD path.** They are stale.
   launchd runs `launch_job.py` directly; the rendered plists are not what runs.
3. **Never print or transmit broker credentials.** `~/ibc/config.ini` holds
   `IbLoginId`/`IbPassword`. `config/.env` holds R2 credentials.
4. **The trade phase is not idempotent.** See §3.2.
5. **Order type must stay MOC.** Overnight market orders cost 100.5bp.
6. **`_sleeve_nav` reads the shadow ledger**, which currently disagrees with the
   broker. Targets are sized off ledger NAV and diffed against broker quantities.
   Know this before touching sizing.
7. **HYT lags the price panel by a day.** `px.iloc[-1]` can be NaN for a name;
   use `px.ffill().iloc[-1]` where you need each name's own last close.
8. **`PositionTarget.weight` is signed.** Do not multiply by the side sign again.
9. **The 2411 dates before 2013 are flat** — fewer than `min_names` clear the ADV
   filter. Full-sample turnover is diluted ~44% and Sharpes depressed by
   $\sqrt{3041/5452}$. Applies to every row equally, but know it before quoting.

---

## 11. Reading list

**Trading policy** — Constantinides (1986) *Capital Market Equilibrium with
Transaction Costs*, JPE; Davis & Norman (1990), Math. of OR; **Bertram (2010)**
*Analytic solutions for optimal statistical arbitrage trading* (the single most
applicable paper); Gârleanu & Pedersen (2013), JF; Muthuraman & Kumar (2006).

**Sizing** — Thorp (2006); MacLean, Thorp & Ziemba (2011); Moreira & Muir (2017), JF.

**Construction** — Avellaneda & Lee (2010); Ledoit & Wolf (2004), JMVA; Grinold
(1989); Clarke, de Silva & Thorley (2002); Getmansky, Lo & Makarov (2004), JFE
(our NAV autocorrelation is 0.388 and unmodelled).

**Closed-end funds** — **Lee, Shleifer & Thaler (1991)**, JF (the common discount
factor; PC2 is a credit instance); Pontiff (1996), QJE; Cherkes, Sagi & Stanton
(2009), RFS.

**Inference** — Lo (2002), FAJ; Bailey & López de Prado (2014), JPM.

---

## 12. If you change one thing

Make a non-armed session raise an alert. The strategy is real; the research is
months ahead of the operations; and a book that trades on 3 sessions in 5 weeks
cannot learn anything about itself no matter how good the mathematics gets.
