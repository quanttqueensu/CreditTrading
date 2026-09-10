# W7 — What it costs to trade, and whether the band is actually trading less

**Reads first:** `00_BRIEF.md` §3 (how these instruments trade), §4 (the
scoreboard), §5 (harness).
**Lever:** measurement that gates every capture decision. Cost is the
fastest-converging number the desk owns.
**Trials:** 0. **Touches the live book:** no — logs, scripts, a dashboard card
and a pre-registered A/B design. The routing change itself is a later trial.
**Prerequisites:** W5 (the order-event log and the phantom-flatten port; both
inflate realised turnover with trades that are not strategy).
**Supersedes:** P1.3, P1.4, P6.7.

---

## Paste from here

You are a trading engineer on the QUANTT CEF book. The strategy's economics
hinge on one number nobody knows: what it costs to trade. Read
`docs/prompts/00_BRIEF.md`, then:

1. `docs/PLAN.md` §7.1 (Sharpe SE ≈ 2.05 over 60 sessions; cost SE ≈ 0.84bp
   over 60) and §5 (the order-type question).
2. `results/cef/ALPHA_AUDIT_2026-09-05.md` "Economics": breakeven **32.6bp per
   unit turnover** (28.9bp for 2021–26); one MOC session at 2.8bp with ±25bp
   per-fill dispersion, mostly penny rounding on $4–12 names.
3. `docs/SYSTEM_AND_STRATEGY.md` §1.4 (why MOC: overnight market orders
   realised 100.5bp on 2026-07-31) and §5.1.
4. `results/cef/PREREG_BAND_2026-09-06.md` "Committed in advance": the primary
   readout is **turnover**, expected ~17.6×/yr against 31.1 on the old
   calendar; holding period ~6 → ~12 business days; *"if realised turnover is
   not materially below the calendar's within 20 armed sessions, the
   implementation is wrong — that is a code bug to find, not a result to
   interpret"*; no P&L verdict this year; the width is not re-tuned on live
   data.
5. `results/cef/ESTIMATOR_NOTE.md` "What actually failed": z_window=63 failed
   its holdout **on turnover** (45×/yr in sample → 102× out), not on the
   signal. Turnover is the quantity that does not generalise, which is why it
   is the readout.
6. `ops/capture_fills.py`; the CEF shadow ledger's `broker_fills.csv`,
   `slippage.csv`, `trades.csv`, `nav.csv`, `positions.csv`,
   `order_events.csv` (W5); `src/deploy/exec_ledger.py::_fill_order` (how the
   modelled fill price is built, so "modelled" means the same thing in your
   log); `scripts/cef/band_frontier.py::evaluate`.

---

## Part A — What to measure, precisely

Under W3's morning architecture the sleeve decides at 08:30 on day *D* from the
completed pair of *D−1*, and the MOC fills in *D*'s closing auction. Let `C_dec`
be the decision close (the *D−1* close the sleeve used) and `C_fill` the
official close of *D*. There are two gaps and only one of them is execution:

- **Delay** = `s_i·(C_fill − C_dec)/C_dec`: the move between the information
  set and the fill. **The backtest already pays this** — it is why weights are
  shifted two days. Report it, labelled "already in the backtest"; it is not a
  cost the desk controls.
- **Execution** = `s_i·(VWAP_fill − C_fill)/C_fill + commission/notional`: what
  we paid relative to the official close the model assumed. For a MOC this
  *should* be near zero; the deviations are penny rounding, partial fills
  across prints, and — the important one — **our own order moving the closing
  print**.

`s_i = +1` for buys, `−1` for sells, so a positive number is a cost. Breakeven
32.6bp is one-way, per unit of turnover.

**The impact test MOC hides.** If our order moves the close, the fill looks
perfect against `C_fill` and the cost appears next morning as a reversal. Test:
for each name, compare the *D → D+1* open-to-close reversal on sessions we
traded it against sessions we did not, signed by our side. Report mean and t.
This is the only way to see impact when you benchmark against the close you
helped set.

**Context for how much impact to expect.** NYSE publishes a Significant
Imbalance at 15:50 ET **once — it does not refresh** (that is Nasdaq's NOII, not
NYSE's); the publication threshold is **500 round lots (50,000 shares)** under
Rule 7.35B(d)(1). Our
clips are $10k–50k on $3–43m ADV names — one to three orders of magnitude
below that, so our orders essentially never register as a published imbalance.
That is a prior, not a result: measure the reversal anyway, because the
imbalance threshold governs what is *published*, not what moves the print in a
thin auction.

### `scripts/cef/shortfall.py`

Per fill: `fill_date, decision_date, pair_date, instrument, side, qty, price,
commission_usd, decision_close, official_close, exec_bp, delay_bp,
commission_bp, modelled_bp, method` where `method` is `MOC`, `LOC` or
`overnight_market` — **classified from the order record, not from the date**.

Per session: turnover-weighted mean `exec_bp`, its cross-name SD, number of
fills, gross notional, `modelled_bp`, and `excess_bp = exec − modelled`. **MOC
sessions only** in any running statistic; the 2026-07-31 overnight-market
session gets its own row and is excluded from every mean, with the reason in
the file header.

Running: cumulative turnover-weighted mean of `exec_bp` over MOC sessions, its
standard error **treating sessions as the independent unit** (per-fill errors
within a session are correlated through the auction), the session count, and
the number still needed for SE ≤ 1bp at the observed dispersion. Same for
`delay_bp`, labelled.

Outputs `results/cef/shortfall_log.csv` (append-only, one row per fill,
idempotent on re-run: dedupe on `execId`) and `shortfall_sessions.csv`. Wire it
after CAPTURE in the `cef_pm` job, writing `ops/heartbeat.json` under
`cef.cost`: `{n_sessions, mean_bp, se_bp, breakeven_bp: 32.6, asof}`. If the
script fails the heartbeat carries `{"error": ...}` — never a stale number.

---

## Part B — Turnover, defined once so the live number and the backtest number
are the same object

- **Session turnover** `τ_t = Σ_i |q_it·P_it| / N_t` from **broker-confirmed
  fills only**, `q` the filled quantity, `P` the fill VWAP, `N_t` the sleeve NAV
  at decision. Modelled sessions do not count. Sessions that did not arm are
  **excluded from the denominator**, not counted as zero — a non-armed day is a
  missing observation, not a quiet one.
- **Annualised** = 252·mean(τ) over armed sessions, with a moving-block
  bootstrap CI (block 5 sessions).
- **Strategy turnover** excludes dust orders (any order whose reason is a band
  HOLD; after P0.1 there are none) and phantom flattens (W5 Part A's audit
  list, by session).
- **Exclude any fill whose decision date precedes the band epoch.** The
  $223,540 that filled at the 2026-09-08 close was Friday's calendar-policy
  order set resting over the weekend, decided pre-epoch under v5. It is the
  epoch's opening position, not a band session.
- **Holding period**, two estimates side by side: (i) mean gross ÷ mean session
  turnover, the harness definition; (ii) per-position life from first fill to
  flat, from `positions.csv`, median and mean.
- **Counterfactuals on the same dates:** `calendar(T, 2)` and `band(T, 0.048)`
  from `build_targets()`, restricted to the armed session dates, so the
  comparison is same-days, same-signal, policy-only. The live number should
  track the band counterfactual; a gap between them is the implementation, not
  the market.

### `scripts/cef/turnover_readout.py`

Writes `results/cef/turnover_readout.csv` (per armed session: date, armed,
n_fills, gross_traded_usd, nav, tau, tau_strategy, tau_dust, tau_phantom,
counterfactual_calendar, counterfactual_band) plus a summary block: annualised
realised, CI, both counterfactuals, holding period (i) and (ii), armed sessions
÷ trading days since 2026-09-06, and "sessions until the 20-session test".

**The 20-session test, coded now so it cannot be re-cut later.** After 20 armed
sessions: a one-sided paired bootstrap test that realised strategy turnover is
below the counterfactual calendar's on the same dates. If p ≥ 0.1, write a
REVIEW-level alert through `ops/halt.py`'s notification path (no HALT.md)
naming the pre-registration and both numbers. Second comparison: if realised
exceeds the band counterfactual by more than 30%, the same alert with
"implementation divergence".

Backfill what exists: 2026-07-31 (overnight market, different policy and
method), 2026-09-01 (calendar-2d, band not yet live), 2026-09-04 (band live).
Label each session's policy and show the series starting at the band's
activation.

---

## Part C — Cost by group, from 40 years of highs and lows

Two sources of cost information, neither yet used by group.

**From history: a daily spread estimate for every name since 1986.** The panel
has high and low. Corwin & Schultz (2012, JF) estimate the bid-ask spread from
the ratio of two-day to one-day high-low ranges:

    CONST = 3 − 2√2
    β_t   = [ln(H_t/L_t)]² + [ln(H_{t−1}/L_{t−1})]²
    γ_t   = [ln(H_max2day / L_min2day)]²        H_max2day = max(H_t, H_{t−1})
                                                L_min2day = min(L_t, L_{t−1})
    α_t   = (√(2β_t) − √β_t)/CONST − √(γ_t/CONST)
    S_t   = 2(e^{α_t} − 1)/(1 + e^{α_t})

**Verified against the authors' own distributed code and data description,
2026-09-09** — these are equations (14) and (18) of the paper, and the constant
is exactly `3 − 2√2`.

**Set negative daily estimates to zero, not to missing, before averaging into a
monthly figure.** That is not a convenience: Corwin's own follow-up note tests
both treatments and finds zero matches TAQ-quoted spreads better, and it is what
the paper and his distributed estimates use. Treating them as missing is
documented as inferior — do not "improve" on it. This gives a
spread panel by name, group and era across the whole backtest sample, so the
harness's flat 15bp can be replaced by a group- and era-specific cost, and
`config/costs.yaml`'s 2026 one-shot probe can be checked against two decades of
implied spreads. **W4 Part B imports this estimator for the bounce test; write
it once, here.**

1. `scripts/cef/spread_panel.py`: Corwin–Schultz monthly by name, then by group
   and era. Report group medians (expect the PIMCO premium funds tight, munis
   moderate, the $4–8 names widest in bp), the trend since 2010, and the
   comparison to `costs.yaml`'s half-spreads for the 17 (CS estimates a full
   spread; halve it). Where they disagree by more than 2× for a name, say which
   is more likely right and why — CS is noisy on low-volume days; the probe was
   one snapshot.
2. **Re-run the band frontier with per-name, per-era costs** instead of the
   flat grid: `net = ann − Σ_t Σ_i |Δw_it|·hs_it`. Report the live band's net
   under measured-history costs beside net@15, by era. Add a `costs_mode`
   argument (`"flat"` | `"cs_history"`) to the harness's net computation so
   every later prompt can request it. **This is the honest version of the cost
   column.**
3. **From our fills, by group.** From `shortfall_log.csv`: `exec_bp` mean and
   dispersion by group; our fill size as a share of the day's volume and of the
   closing print by group; the impact test by group. With ~31 fills this is a
   table with wide error bars — state them, and never present it without.

### The questions this part answers for the desk

- **Should the LOC arm be group-specific?** If muni closes are thin and our
  share of the close is high, an LOC at the decision close may capture more
  there and non-fill more often. The A/B in Part D can stratify by group at no
  extra cost.
- **Does the per-name band (W11) already price this in via `c_i`?** Compare the
  CS half-spread ranking to the tick-cost ranking used there. If they agree,
  nothing further; if a group's real spread is systematically wider than its
  tick, the band should use the CS estimate.
- **Is `costs.yaml` stale?** Preflight's `cost_drift` check compares the yaml to
  a tick-floor model; propose adding the CS monthly estimate as a second drift
  reference.

---

## Part D — The LOC A/B, designed now, run later

Write `results/cef/PREREG_LOC_<date>.md`. Design only; no routing change here.

- **Hypothesis:** a limit-on-close at a limit no worse than the decision close
  captures part of the spread with an acceptable non-fill rate, because under
  the band the cost of not filling is small — the position stays inside its
  band one more day.
- **The constraint that shapes the design:** the account has no live quote
  subscription (error 10089; delayed data only), so a mid-quote limit is not
  available at 15:50. The limit is therefore the **decision close**: buy at
  ≤ `C_dec`, sell at ≥ `C_dec`. Fill rate will be roughly the fraction of days
  the move from decision to close is favourable.
- **The auction's rules bind the design.** LOC orders may be entered, modified
  or cancelled only until 15:50 ET — **and after 15:50 they cannot be cancelled
  or reduced "even to correct a legitimate error"**, which is a harder constraint
  than an earlier draft implied. New closing-only interest is then accepted only
  opposite a published imbalance, and if none was published it is rejected
  outright. So the arm is chosen and committed at decision time with no intraday
  intervention available.
  Note NYSE's **Closing IO Order** (Rule 7.31(c)(2)(D)) as a possible third arm
  in a later study — limit-only, auction-only, and enterable on both sides up to
  16:00 — and say why it is not in this one: it executes only against an
  imbalance, so its fill rate is not comparable to MOC or LOC. **NYSE is
  amending that order type now (SR-NYSE-2026-36, implementation by Q1 2027);
  re-read the rule before designing an arm around it.**
- **Budget for non-fills, because the data says they happen.** NYSE reports
  about **3.3% of closing-auction volume goes unfilled, and 6.3% for
  non-Russell-1000 names** — the category all seventeen of ours are in. That is a
  base rate for the MOC arm, not just the LOC arm, and the A/B's "total cost
  including non-fills" accounting must apply to both.
- **Assignment:** on each session, names whose ticker's SHA-1 hex first digit is
  even go LOC, odd go MOC; flip the parity daily so every name sees both arms.
  Assignment is **by name, not by order**, so the arms carry the same turnover.
  Optionally stratify by group per Part C.
- **Outcome:** `exec_bp` by arm, and **total cost including non-fills**, where
  an unfilled LOC leg is charged the change in decision value until it fills or
  the band no longer wants it.
- **Stopping rule:** 20 sessions, then a paired test on session means. Adopt LOC
  only if it wins on total cost at p < 0.05 **and** the non-fill rate is below
  50%. Trials: 1, spent when the routing change is switched on.

---

## Deliverables

- `scripts/cef/shortfall.py`, `impact_test.py`, `turnover_readout.py`,
  `spread_panel.py`; `data/cef/cef_spread_cs.parquet`; the log CSVs; the
  heartbeat wiring (`cef.cost`, `cef.turnover`); the `costs_mode` harness
  argument.
- `results/cef/SHORTFALL_<date>.md` with the current running estimate — it will
  say "2 MOC sessions, SE too wide to read", which is the honest state — plus
  the impact result; `TURNOVER_READOUT_<date>.md` stating the count and what
  the test looks like at session 20; `EXECUTION_BY_GROUP_<date>.md`;
  `PREREG_LOC_<date>.md`.
- Dashboard payloads for W9: a "Realised cost" card (running mean with ±2 SE,
  breakeven line, per-session points sized by notional, modelled half-spread as
  a second line, 2026-07-31 hollow and labelled) and a "Pre-registered
  readouts" card (four rows, each with expected, realised, n of 20, and a
  state). No computation in the dashboard; it reads the CSVs.

## Do not

- Do not average the 2026-07-31 session into anything.
- Do not compute cost against the decision close and call it execution; that is
  delay.
- Do not include modelled sessions or non-armed days in any average.
- Do not re-tune the band width on this data. The pre-registration forbids it
  and the script must not offer a "what width would have matched" line.
- Do not change the order type in this prompt.
- Do not replace `costs.yaml` on the live path from Part C; it is a
  preflight-guarded config, changed by hand with a note.
- Do not present the ~31-fill group statistics without their standard errors.
