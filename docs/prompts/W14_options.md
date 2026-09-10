# W14 — Is the book short vol, and is a convexity overlay worth its carry?

**Reads first:** `00_BRIEF.md` §2 (M9), §3, §5, §7 — and
`gamma/G0_BRIEF.md`, which holds the option mechanics, the market facts and the
programme's own rules. **This prompt is the CEF book's *use* of options; the
options machinery itself lives in `docs/prompts/gamma/`.**
**Lever:** Part A is none — it is the measurement that decides whether options
have any job here. Part B is the book's drawdown. Part C is TC and timing.
**Trials:** Part A 0; Part B 1 on the **GAMMA** counter; Part C 1 on the **CEF**
counter.
**Prerequisites:** W2 must say "options: permitted". Parts B and C are gated on
Part A's verdict. Part B additionally needs `gamma/G1` (the pricer), `G2` (the
surface), `G3` (the hedge rule) and `G4` (a ledger that survives an expiry) —
**do not backtest an overlay with machinery that cannot book one.**
**Moved out 2026-09-09:** the learning book is now `gamma/G5_paper_book.md` and
the timed sleeve is `gamma/G7_sleeve_and_sizing.md`.
**Supersedes:** P7.1, P7.2, P7.4.

---

## Paste from here

You are a quant researcher on the QUANTT CEF book. The team asked whether gamma
scalping can be part of what we do. `gamma/G0_BRIEF.md` answers the general
question; this prompt answers the specific one: **does *this* book need
convexity, and would buying it be worth the carry?**

Read `docs/prompts/00_BRIEF.md`, `docs/prompts/gamma/G0_BRIEF.md`, then:

1. `docs/E1_PREREG.md` §5 — the factor set the previous book was tested against,
   **including the short-ATM-straddle proxy** built from
   `data/vrp/marks_SPY.parquet`. That regressor exists because a mean-reversion
   book can be "short vol in disguise": every position bounded, the portfolio
   still losing exactly when volatility jumps. It was run on the credit-RV book.
   **It has never been run on the CEF book.** Note that
   `src/deploy/lib/attribution.py` reads that factor from
   `results/vrp/refute_tail_ledger_SPY.csv`, **which does not exist** — G2 Part D
   rebuilds the pipeline, so either sequence this after it or rebuild the single
   series you need here and say which.
2. `scripts/cef/band_frontier.py::evaluate` — you will extend it to return the
   daily P&L series `pnl`. A **visible extension** of the canonical harness; do
   not build a second backtester.
3. `data/vrp/atm_iv_daily.parquet` and `vix_daily.parquet`.

---

## Part A — Is the book short vol? (trial: 0. This gates everything below.)

Before anyone prices a put, answer the only question that decides it: **does
this book lose money in the states where long gamma pays?**

### The mechanism, stated so it can be falsified

Discount reversion is liquidity provision to retail. Retail sells CEFs hardest
in credit sell-offs — 2008, December 2018, March 2020, the 2022 rates shock —
and discounts widen *together* (our own pairwise correlation of daily discount
changes runs 0.42–0.66 across groups). The z-score clips at ±4 and the vol
target scales on 63-day realised vol, which lags. So the book is already at full
size when the shock arrives, loses on the widening, and is paid back over the
following weeks as discounts revert. Whether that is "short vol" turns on two
measurements:

- **β_vol** — the book's daily P&L loading on the *change* in implied
  volatility (ΔVIX now; ΔHYG-IV once G2 has extracted it). Negative and
  significant means long gamma is a hedge for this book. Near zero means it is
  not, whatever the drawdowns look like.
- **Conditional IC** — the signal's 2d/T+1 IC in high- versus low-vol states.
  If the IC is *higher* in stress, the book is "hurt by the shock, paid by the
  reversion", and a convexity hedge would be protecting the exact P&L the
  strategy is designed to earn. **The question then becomes one of timing
  (Part C), not protection.**

### The measurements

1. **Extend `evaluate`** to return `pnl`. Run band 4.8% on the real panel, **on
   W4's total-return convention** — a price-return P&L series will mis-state the
   loading on any factor correlated with the distribution calendar. Keep the
   pre-2013 flat convention and say so.
2. **Factor regression** of daily P&L, 2014-01 → 2026-07 (the VIX window) and by
   era: HY excess return (HYG minus duration-matched Treasury), IG excess, 10y
   Treasury return, SPX return, ΔVIX, the E1 short-ATM-straddle proxy, credit
   momentum. Newey-West t-stats, lag 5. Report β, t, R², and **β on ΔVIX in
   dollars per VIX point on the $500k book**. Repeat with ΔHYG-IV once G2 lands.
3. **Drawdown coincidence.** The book's ten worst 21-session windows; for each,
   the VIX percentile at the start, the peak VIX inside the window, and the
   HYG-IV percentile. **If eight or more of the ten sit in the top VIX quintile,
   the drawdowns are vol-state drawdowns.** If they are spread across the
   distribution, they are not, and no option hedge addresses them.
4. **Conditional IC** by VIX tercile at signal time, pooled and by group; plus
   the *forward* 21-day P&L of the book conditional on entering a top-decile VIX
   day.
5. **Basis, measured not assumed.** The overlay would be in HYG; the book is in
   CEFs. In March 2020 CEF discounts widened by more than 1,600bp while HYG's own
   average absolute premium/discount to NAV rose only from 0.21% to 1.06% and its
   intraday deviation reached −5% to −8%. **Regress the book's P&L on HYG's
   return and on HYG's implied vol change separately**, and report the R². That
   number is the ceiling on how much of the book's tail an HYG overlay can
   possibly remove.

### The verdict — this part adopts nothing

Four numbers and one sentence: β_ΔVIX (and β_ΔHYG-IV) with t-stats; the fraction
of the ten worst windows in the top VIX quintile; the IC ratio, high-vol tercile
÷ low-vol tercile; the credit `rich_ratio` from G6; and **"The book is / is not
short vol at the portfolio level, because …"**

**The gate: Part B opens only on β_ΔVIX < 0 with |t| ≥ 2.5 AND ≥ 7 of 10
drawdown windows in the top VIX quintile.** Either condition failing closes Part
B — a hedge that pays in states where the book does not lose is a pure carry
cost — and the honest answer becomes Part C plus the standalone programme.

---

## Part B — The convexity overlay (trial: 1, GAMMA; gated on Part A)

Judged on the book's **drawdown, not its mean** — Calmar, worst month, tail.

### Construction, every choice stated before running

- **Underlying:** the credit ETF with the largest |β| from Part A — HYG
  expected. Options must clear G2's liquidity screen on ≥ 90% of days or the
  underlying is untradeable for this purpose, and G2's per-ticker survival table
  is the evidence.
- **Structure, primary:** 25-delta puts, 1–3 month tenor, rolled at 21 DTE.
  Puts, not straddles, because **the book's losses are one-sided**: discount
  widening is a credit sell-off. **Secondary:** ATM straddles, reported
  alongside, **not selected on**.
- **Sizing by theta budget**, not by contracts: 0.5%, 1.0%, 2.0% of NAV per
  year. The notional follows from the budget and the day's implied vol, so **the
  hedge automatically shrinks when protection is expensive** — the opposite of
  buying most when it costs most.
- **Delta hedge:** G3's specification exactly. Daily, at the close, in ETF
  shares, in the same session as the CEF book, with G3's minimum-ticket
  deadband and its close-to-close benchmark.
- **No short options anywhere.** Selling a call to "finance" the put
  re-introduces the tail the overlay exists to remove.

### The backtest

Daily, 2014-06 → 2026-07, on top of band 4.8%'s P&L series. Option marks from
G2's surface, greeks from G1's American pricer, **spread floor charged at
1×/2×/3× on every leg crossing** (entry, exit, roll = two legs each), hedge at
G3's measured cost, and **`option_spread_model.py`'s VIX-keyed curve for the
crisis periods** — a flat $0.02 through March 2020 is fiction and would flatter
the overlay exactly where it matters most.

| metric | pre-committed role |
|---|---|
| net Sharpe (15bp on the book, spread floor on the options) | must not fall by more than 0.05 |
| **Calmar** (ann. return ÷ max drawdown) | **primary: must rise ≥ 25%** |
| worst month, 5 worst months | must improve in ≥ 4 of 5 |
| skew of monthly returns | reported |
| overlay carry, %/yr | reported — what the hedge costs |
| overlay P&L in the book's 10 worst windows | reported — what it buys |

Bootstrap the Calmar difference (block bootstrap, 21-day blocks, 2,000 draws)
and report the 5th percentile; adopt only if it is positive. Fit and holdout
rows separately.

**Negative control:** the identical overlay on **SPY** puts. If SPY protects the
book as well as HYG does, the hedge is generic equity tail protection rather
than credit convexity. It may still be adopted — but it is named correctly, and
the underlying with the better Calmar-per-carry wins, stated before the run.

### Decision rule, fixed before running

Adopt the **smallest** budget at which, at **all three** spread multipliers:
Calmar rises ≥ 25%, net Sharpe falls ≤ 0.05, the five worst months improve in
≥ 4, and the bootstrap 5th percentile of the Calmar change is > 0. **And** the
combined book's annualised net return is not lower than the CEF book's by more
than the overlay's carry at the smallest budget — the team is judged on absolute
return, so a hedge that buys Calmar by giving up return is adopted only where
that trade is smallest. If no budget passes, record the table and stop.
**Never pick the budget on Sharpe or on the overlay's own return, which is
expected to be negative.**

### Deployment, if adopted

A separate sleeve `cef_convexity_overlay` with its own sub-ledger; option legs
as limit orders priced from our own surface (**not** at IBKR's model value, and
**not** with a missing `limit_price` — see G4 defect A2); the hedge leg ordinary
MOC/LOC shares. Spec keys `theta_budget_pct`, `max_option_notional_usd`,
`vega_limit_usd`, `no_short_options: true`, all defaulting to "no overlay" with
the no-op proved on the CEF sleeve's output. Reported separately and combined.
**The main book's kill rule is evaluated on the book *without* the overlay, so
the hedge can never mask a failing strategy.**

---

## Part C — Options as information, no option traded (trial: 1, CEF)

Two of the book's parameters assume a stationary world:

- **The band.** `σ_w` — how fast target weights move — is not constant: in a vol
  spike z-scores move several units in days. The cube-root law says the no-trade
  region should widen with `σ_w^(2/3)`, so a constant 4.8% band is too narrow in
  stress (it trades every twitch at the worst spreads) and too wide in calm.
  Implied vol at decision time is a **forward-looking** estimate of `σ_w`'s
  driver; realised vol is a backward one.
- **The vol target.** 63-day realised vol lags a shock by weeks, so the book is
  at full size when the shock lands and *smallest* weeks later when the
  reversion pays — and Part A's conditional IC says whether that is when the
  edge is largest.

**Constructions, all derived, nothing swept:**

1. **State-scaled band:** `h_t = 4.8% × (IV_t / IV_med)^(2/3)`, IV = HYG ATM
   implied vol at decision time from G2's surface, median over the trailing 504
   sessions (trailing, so no lookahead), clipped to [3%, 9.6%] — the measured
   plateau's edges, stated in advance.
2. **Blended vol scalar:** replace `rv_63` with `√(½·rv_63² + ½·IV_t²·β²)` where
   β is the book's trailing 252-day beta of realised vol to HYG IV, **so the
   implied vol is translated into the book's own units rather than assumed
   equal.** Same clip.
3. Both together.

Each under the harness at the **turnover-matched** width or scalar, cost grid
5/15/30, net of borrow, by era, fit and holdout, on the 17 and then once on the
27.

**Tests.** Conditional performance: net@15 and turnover in the top VIX tercile
versus the bottom, for the live spec and each construction — **the gain must sit
in the high-vol tercile; a uniform gain fails the mechanism.** Negative control:
the same constructions driven by **VXN** instead of HYG IV; if VXN works as
well, the input is "any vol index" and the credit-specific story is not the
story — it may still be adopted, but named as generic vol-state conditioning.
Turnover stability by era must not be worse than 11.9%.

**Decision rule.** Adopt if net@15 and net@30 improve at matched turnover, the
gain is concentrated in the high-vol tercile, the 27 agree in sign, the holdout
agrees in sign, and era turnover stability is not worse. **If two pass, the
band-only change wins by default** (simpler; one parameter), stated in advance.
Spec keys `band_state: "const" | "iv_scaled"` and `vol_input: "realised" |
"blend"`, absent = current behaviour, no-op proved byte-for-byte. **The HYG IV
series must be fetched into the panel by the same refresh that fetches NAV — a
decision input that is not in the panel at decision time is not a decision
input.**

## Deliverables

- `scripts/cef/stress_beta.py`; the `evaluate` extension returning `pnl`;
  `scripts/cef/vol_state.py`; the overlay backtest built on G2/G3/G4.
- `results/cef/STRESS_BETA_<date>.md` with the four numbers, the basis R², the
  sentence, and **the Part B gate verdict stated explicitly**;
  `PREREG_CONVEXITY_<date>.md`; `results/cef/VOL_STATE_<date>.md`.
- The IV fetch wired into `scripts/cef/fetch_daily.py` with the same
  completeness requirement as NAV.

## Do not

- Do not start before the account audit says options are permitted.
- Do not backtest an overlay on machinery that cannot book an expiry; G4 first.
- Do not use IBKR model greeks or implied vols anywhere.
- Do not interpret a negative β_vol as "buy puts". It is the entry ticket to
  Part B, where the carry is charged.
- Do not hedge intraday, and do not scale any budget with recent losses — that
  is buying protection after the loss.
- Do not report the overlay's own Sharpe as if it were the result.
- Do not charge a flat option spread through a crisis period.
- Do not use the VIX level as a signal on individual names. Part C is about
  *parameters*, not alpha.
