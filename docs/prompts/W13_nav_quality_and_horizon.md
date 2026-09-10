# W13 — NAV quality and the horizon question

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `00_BRIEF.md` §2 (M2), §3 (how these instruments trade), §5.
**Lever:** IC, via the measurement error in the NAV itself — and, separately,
whether the same logic works at a horizon we have never tested.
**Trials:** 2 on the **CEF** counter: Part B (NAV treatment) = 1, Part C
(intraday research) = 1. Part A is diagnostics already begun in W4 and costs
nothing.
**Prerequisites:** **W4 Part C is mandatory.** That prompt measures whether the
IC *is* stale-NAV catch-up. This one decides what to do about it. If W4 found
that essentially all the IC sits in the stale-NAV component, Part B is not a
refinement — it is a rewrite of what the strategy claims to be, and the note
must say so.
**Supersedes:** P5.4, P8.5.

---

## Paste from here

You are a quant researcher on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md` and `results/cef/ARTIFACT_BATTERY_<date>.md` (W4)
first — quote its stale-NAV numbers in your own note's opening. Then:

1. `docs/SYSTEM_AND_STRATEGY.md` §11: Getmansky, Lo & Makarov (2004, JFE
   74(3):529–609) — return smoothing from stale marks; **our NAV autocorrelation
   is 0.388 and unmodelled.**
2. `docs/PER_NAME_ARCHITECTURE.md` §5 and §3 (the resolution principle: apply
   per-group treatment where it is absent from the construction; **the z-score
   knows nothing about NAV quality**).
3. `results/cef/DIST_CUT_NOTE.md` and `ESTIMATOR_NOTE.md` — what has already
   failed on the *level*: a Kalman fair-value model lost to a shorter rolling
   window. **This prompt is not about the level. It is about measurement error
   in the NAV itself.**
4. `docs/EXIT_RESEARCH_2026-09-07.md` §3 and §5.2 — the reasons intraday
   *entry* was ruled out. Find that section and quote it; Part C exists to test,
   with data, whether it still holds for the two most liquid names.
5. `docs/E1_PREREG.md` §6 — the promotion gate that killed the predecessor:
   **gross edge per round trip ≥ 2.5× modelled cost**, measured before anything
   else.

### The mechanism, and why it is group-specific

A closed-end fund's NAV is the fund accountant's valuation of the portfolio. For
a high-yield fund most holdings have a TRACE print that day and the NAV is
fresh. For a **municipal** fund the marks come from an evaluated-pricing service
that prices from a curve — Nuveen's own registration language says the service
considers *"yields or prices of municipal securities of comparable quality, type
of issue, coupon, maturity and rating"* — and the MSRB reports fewer than 2,800
muni trades a day across fewer than 1,500 unique securities against more than a
million CUSIPs outstanding, with two-thirds of the securities that trade at all
trading once or twice. For a **loan** fund the marks are dealer-quote surveys
that update in steps.

So the published NAV relates to true value approximately as a moving average of
recent true changes:

    r°_t = Σ_{j=0}^{q} θ_j · r_{t−j},    Σθ_j = 1,  θ_j ≥ 0

and the observed discount contains a component that is **NAV lag, not price
dislocation**: after a rally in the underlying bonds a muni CEF's NAV has not
caught up, the fund looks rich, the signal shorts it, the NAV catches up, and
the "convergence" is the NAV moving — which earns the fund nothing.

**The prediction is specific and falsifiable:** unsmoothing should improve the
IC in muni and loan names, do little in HY, and NAV autocorrelation should be
highest in munis before and near zero after.

Two more facts to carry into the design:

- **Rule 2a-5** (adopted Dec 2020, compliance 8 Sept 2022) moved fair-value
  determination to a board-overseen "valuation designee" at each adviser. A
  sponsor-level policy or manager change can alter a whole family's
  smoothing profile **without any announcement**. Our time holdout starts
  2023-01-01, immediately after that compliance date — so a
  fit-period/holdout-period difference in θ is not automatically a failure of
  the model; check for a level shift in θ around Sept 2022 and report it.
- **Cici, Gibson & Merrick** ("Missing the Marks", JFE) find cross-fund
  dispersion in month-end marks on *identical* corporate bonds, consistent with
  return smoothing by managers. Smoothing is not purely mechanical; part of it
  is discretionary, which is an argument for fitting θ **per fund family**, not
  only per asset group.

---

## Part A — Diagnostics (0 trials; extends W4 Part C)

NAV return autocorrelation at lags 1–3, per name, **per group, and per sponsor
family**, before and after each treatment below, with block-bootstrap SEs.
Expect muni > loan > multi > hy. **If HY is as autocorrelated as muni, the
mechanism is not what we think — stop and write that.** Add the fit/holdout
split and the Sept-2022 level-shift check.

Report the mean absolute level difference by group between the observed and
unsmoothed NAV levels; it should be largest in munis. If it is not, the
reconstruction in Part B is doing something other than what it claims.

---

## Part B — Two treatments, one promoted at most (trial: 1)

### Variant 1 — GLM unsmoothing, no lookahead

Per name, on a trailing 504-session window ending the day before *t*, refit
monthly:

1. Estimate the MA(q) smoothing profile θ on log NAV returns with **q fixed at
   2** (GLM's finding for illiquid series; report q = 1 and 3 as sensitivity but
   **do not select on them**). Use maximum likelihood on the MA representation
   or the GLM moment estimator; normalise Σθ = 1.
2. Invert: `r̂_t = (r°_t − Σ_{j≥1} θ_j·r̂_{t−j}) / θ₀`.
3. Reconstruct a level. Inverting returns and cumulating drifts, so **anchor the
   unsmoothed log level to the observed log level's trailing 21-day mean** — a
   trailing anchor uses no future data.
4. `d^u_t = 100·(P_t − N̂_t)/N̂_t`; z on `d^u` with the **identical** 252-day
   moments, shift 1, clip ±4.

Alignment assertions: θ for date *t* fitted on data ≤ *t−1*; the anchor window
ends at *t−1*.

### Variant 2 — a NAV nowcast from a live-priced proxy

For each group pick one ETF whose return proxies the underlying bonds — **muni:
MUB and PZA, which must be fetched into the panel (there is no muni ETF in
`data/rv/etf_ohlc.parquet` today) via `refresh_market_feeds.py` with a source
note; hy: HYG; loan: BKLN or SRLN; multi: a duration-matched HYG/LQD blend.**
Regress the fund's NAV return on the proxy's contemporaneous and lagged returns
over the trailing 504 sessions; the nowcast NAV change is the fitted
contemporaneous part **plus the already-observed proxy moves the NAV has not yet
reflected** (the sum of significant lag coefficients times recent proxy
returns). This is the same mechanism by a different route, and it is where the
group structure enters explicitly.

**Note the tension with W10 Part D:** that prompt conditions the fair *level* on
group state; this one corrects the *NAV input*. They can both be right, but they
must not be adopted from the same regression twice — if both pass, state
explicitly which one is doing the work by running each with the other already in
place.

### The tests

1. **Diagnostics** from Part A must match the mechanism.
2. **IC by group**, 2d/T+1, non-overlapping, full sample, by era, fit and
   holdout, for the live z, the unsmoothed z and the nowcast z. The claim: muni
   and loan IC improve, HY does not. **A uniform improvement across groups is a
   failed negative control and is not adopted, whatever the pooled number
   says.**
3. **The harness**, band 4.8%, turnover-matched, net@5/15/30, net of borrow, by
   era, for each variant — plus the muni-only and taxable-only sub-books so the
   gain's location is visible at the portfolio level.
4. **The 27 first**, once, under W10 Part A's rules.

**Decision rule.** Adopt if the diagnostics match the mechanism; the IC gain is
concentrated in muni/loan; the 27 agree in sign; the 2023–26 holdout agrees in
sign; and the harness shows net@15 and net@30 improving at matched turnover with
gross not lower. **At most one variant is promoted; if both pass, the simpler
(GLM) wins by default, stated in advance.** Spec key
`nav_treatment: "raw" | "glm_q2" | "nowcast"`, absent = raw, no-op proven.

**And the honesty clause.** If W4 Part C found the IC lives in the stale-NAV
component, then a successful unsmoothing does not "improve the signal" — it
removes the thing the signal was trading. Expect the IC to **fall**, and say so
in advance. In that world the finding is that the book was a bond-market timing
trade, and the decision is whether to trade it as one deliberately (with a
proper hedge and a different horizon) or not at all. **Write that branch of the
note before running, so the result cannot be reinterpreted afterwards.**

---

## Part C — Intraday, on the two names that could carry it (trial: 1, research
only)

The team's question: our discount logic waits a day between decision and fill
and holds ~12 sessions. On the two most liquid names — **PDI at roughly $43m
a day and PTY** — could the same logic run *inside* the day? MOC stays live;
nothing here trades, under any outcome.

### State the binding constraint at the top of the note

**Intraday there is no NAV at all.** No vendor publishes an intraday NAV or
iNAV for a CEF. The anchor must be a nowcast, and the entire result is
conditional on how good it is.

    NAV̂_{t,τ} = NAV_{t−1}·(1 + β̂'·r^ETF_{t,τ})

with `r^ETF` the proxy ETFs' returns from yesterday's close to intraday time τ,
and β̂ fitted on the trailing 252 days of **daily** NAV returns against the same
ETFs' daily returns, ending *t−1*. **Report the daily-frequency R² of that
regression first** — for PDI/PTY expect 0.5–0.8. The intraday nowcast error is
then at least √(1−R²) of the NAV's daily vol; convert that to discount points
and compare it with the intraday discount moves you intend to trade. **If the
nowcast error is of the same order as the signal, stop and write that** — the
strategy cannot see what it is trading.

### Data

IBKR `reqHistoricalData`, `barSize="5 mins"` (and `"1 min"` for the last six
months), `whatToShow="TRADES"` and `"BID_ASK"` (for the spread), for PDI, PTY
and the proxy ETFs — HYG, LQD, TLT, MBB, since PIMCO's multi-sector funds hold
agency MBS and high yield and the nowcast regression should choose among them.
Page day by day within IB's pacing limits; store under `data/cef/intraday/` with
a `fetched_at`. **Record exactly how far back each bar size reaches.** If the
depth is under two years for 5-minute bars, run the backtest in QuantConnect's
research environment and bring back **tables only** — nothing exported into the
repo.

### The signal and the test

Intraday discount `d_{t,τ} = P_{t,τ}/NAV̂_{t,τ} − 1`. Anchor: the trailing
20-session mean of the *daily* discount (the same object the daily signal uses,
at a shorter window because the horizon is hours — state it, do not sweep it).
Deviation `e_{t,τ} = d_{t,τ} − d̄_{t−1}`.

Enter when `|e|` exceeds `k·σ̂_e` with σ̂_e the trailing 20-session intraday
standard deviation of `e` and **k = 2** (chosen now; report 1.5 and 2.5 as
sensitivity, do not select). Exit when `e` crosses zero or at the close,
whichever comes first. One position per name at a time. Fills at the next bar's
mid **minus** the measured half-spread from the BID_ASK bars, plus an impact
charge of `√(q/ADV_5min)` bp scaled to 10bp at 10% of the five-minute volume.
Cap participation at 1% of five-minute volume.

Report, by name and year: round trips per day; gross edge per round trip (bp);
cost per round trip (bp); **the E1 ratio (edge ÷ cost)**; net Sharpe at 1×/2×/3×
the measured spread; and the fraction of P&L that survives if the nowcast error
is doubled (shock β̂ by its standard error). Also the **time-of-day profile** of
the edge: **if it lives only in the first and last half hour, that is a
different and well-known effect — the open/close liquidity premium — and must be
named as such**, not as discount reversion.

**Decision rule.** Proceed to a *separate* intraday paper-book pre-registration
only if, on **both** names, on the full sample **and** the 2023–26 holdout: E1
ratio ≥ 2.5 at 2× spread, net Sharpe ≥ 1.5 at 2× spread, and the result survives
the doubled nowcast error with at least half its Sharpe. Otherwise record and
stop; the daily book keeps MOC and the intraday monitor (W9 Stage 4) stays
display-only.

---

## Deliverables

- `scripts/cef/nav_unsmoothing.py` (both variants, the diagnostics, the harness
  runs) and `intraday_discount.py`; the muni-ETF fetch additions with source
  notes; `data/cef/intraday/` or the QC notebook's exported tables.
- `results/cef/NAV_UNSMOOTHING_<date>.md` and `INTRADAY_<date>.md` (the nowcast
  R² table **first**, the decision stated against the rule).
- The sleeve change behind `nav_treatment` with its no-op proof, and the
  pre-registrations for whatever is adopted. CEF counter +2 at most, itemised.

## Do not

- Do not select q on P&L.
- Do not smooth or unsmooth **prices**; only NAV.
- Do not treat a uniform gain across groups as success; the negative control is
  the test.
- Do not use any intraday NAV or iNAV from a vendor; none exists for CEFs. The
  anchor is our nowcast and it is **modelled** — label it on every figure.
- Do not test names other than PDI and PTY; the others cannot carry the
  turnover.
- Do not build an intraday executor in this prompt.
- Do not bring QuantConnect data into the repo; tables only.
