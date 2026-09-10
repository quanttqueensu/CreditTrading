# The prompt series: how we look for alpha, and how we trade what we find

**Written 2026-09-07 from a full read of the repo and the live dashboard; Section 7 (options) added 2026-09-08.**
One file per prompt. Each is written to be pasted whole into a fresh Claude
Code session at the repo root; it carries its own context, method, harness,
decision rule and deliverables. This README is the method they all share.
Read it once; the prompts repeat what they need.

---

## Part A. What "finding alpha" means for this book

The book earns its return through one relation, Grinold's fundamental law:

    IR  ≈  IC · √BR · TC

- **IC**, the information coefficient: how well the signal ranks tomorrow's
  returns. Ours is −0.074 (t −11.6) at the traded 2-day / T+1 horizon over 27
  years, in every sub-period, stronger out of sample than in. **This is the
  part that is settled.** The repo has measured, many times, that sharpening
  it is the least productive place to work (price reversal adds +0.1%; the
  Kalman lost to a shorter window; per-name kappa lost to pooled).
- **BR**, breadth: the number of *independent* bets per year. We hold 17
  names and pretend that is 17 bets. It is not. On the live weights the book
  has an effective breadth of **1.17** today (2.24 historically), because
  92.5% of its variance is one factor: municipal CEFs against taxable ones.
  **This is the biggest hole in the strategy and it is where most of the
  per-fund work belongs.**
- **TC**, the transfer coefficient: how much of the ideal book we actually
  hold after costs, borrow, availability, rounding, and missed sessions. Gross
  Sharpe near 1.2 becomes 0.10 net on the old calendar and 0.43 on the band
  once borrow is charged. **This is the capture problem, and it is the
  highest-value work per hour.**

So "finding alpha" here has three distinct meanings, and every prompt says
which one it is doing:

1. **Raise BR** without lowering IC: make the seventeen names into more than
   one bet. Decompose the signal into within-group and between-group parts;
   size the group bet on purpose instead of by accident; add names from
   groups that dilute the dominant factor; give the book a covariance matrix.
2. **Raise TC**: trade less, trade cheaper, short the names that can be
   borrowed, size to the right volatility, never send an order the strategy
   did not ask for, and measure execution fast enough to act on it.
3. **Add a genuinely new IC source** only where a *mechanism* says one should
   exist and where the current signal is provably blind: stale NAVs by asset
   group, dated seasonal flows by group, and group-level state that moves the
   fair discount. These are tested on the 27 untouched names first.

## Part B. Where alpha comes from in closed-end funds (the mechanism list)

Before any test, name who is on the other side and why they stay there.
Every prompt below is tied to one of these.

| # | mechanism | who loses, and why they keep doing it | horizon | status in this repo |
|---|---|---|---|---|
| M1 | **Discount mean reversion.** Retail sentiment moves price; NAV is the anchor; nothing arbitrages the gap because share count is fixed and there are no APs (Lee, Shleifer & Thaler 1991; Pontiff 1996) | Retail holders who buy yield and sell losses, at whatever price | days to weeks | **Live.** IC −0.074. Settled. |
| M2 | **Stale NAV.** Munis and loans are matrix-priced; the published NAV lags true value. Part of a "discount" is NAV error, not price error (Getmansky, Lo & Makarov 2004) | Nobody loses; it is measurement error we can remove | days | Unmodelled. NAV autocorrelation 0.388. → P5.4 |
| M3 | **Seasonal retail flow.** Tax-loss selling into year-end, reversal after; distribution-driven flows around ex-dates | Tax-motivated retail; they are not stupid, the tax value exceeds the price concession | dated, weeks | Pooled January effect measured (+7.7bp/day). Group split untested; rough pass says it sits in PIMCO multi, not munis. → P6.4 |
| M4 | **Group-level fair value.** A muni fund's fair discount moves with the muni/Treasury ratio and leverage cost; a HY fund's with spreads; a PIMCO fund's with its own premium regime | The z-score treats a fair-value shift as a dislocation and trades the wrong way for months | weeks to months | Untested as a *conditional* level. The unconditional Kalman lost. → P6.3 |
| M5 | **The group spread itself.** Muni-vs-taxable discount spread reverts; the book is short it at whatever level the demeaning produced | Same retail base, but at the sector level | weeks | Taken by accident at 92.5% of risk. Never sized. → P6.1, P6.2 |
| M6 | **Corporate events.** Tenders, rights offerings, mergers, open-endings, activist 13Ds move a discount to a known level on a known date | Boards that resist activists; holders who sell before the tender | dated | Not staged. Calendar only. → P3.6 |
| M7 | **Distribution policy.** Cuts re-rate a fund permanently; the rolling mean takes a year to notice | Yield-screening retail | months | Tested twice as a signal and failed at a 2-day hold. Do not rebuild. |
| M8 | **Fund health / price level.** Low-priced CEFs have eroded capital through return-of-capital; higher-priced funds revert better AND cost fewer ticks | Yield chasers in eroded funds | — | Measured +0.16 net in July (5d-hold era), "Adopt", **never deployed**. → P1.8 |
| M9 | **Volatility state.** Discounts widen together in credit sell-offs and revert fastest afterwards; the options market prices tomorrow's volatility today. Two uses: a *hedge* (long gamma pays exactly then, but costs the variance risk premium every other day) and *information* (a band width and vol target that know a shock is on) | Nobody, for the hedge — it is insurance, priced rich (SPY implied ÷ realised variance 1.3–1.5× in our data). For the information use: the book's own lagging estimates | days to weeks | Unmeasured on the CEF book. The E1 short-straddle regressor was run on the RV book only. → P7.1, then P7.2 / P7.4 |

## Part C. What "trading better" means (the capture goals)

These are the numbers the trading-quality prompts move. Each is measurable
faster than P&L.

| goal | live today | target / reference | how measured |
|---|---|---|---|
| Capture ratio, net ÷ gross Sharpe | 0.43 / 1.16 = 37% (band, net of borrow) | 0.90 / 1.33 = 68% (joint optimiser, modelled) | band_frontier harness |
| Turnover | 17.6×/yr expected; realised unknown | below 31.1 within 20 armed sessions (pre-registered) | broker fills only |
| Cost robustness | net@5bp 0.99, net@30bp 0.17: never flips | never flips | harness, 5/15/30bp |
| Turnover stability, era sd/mean | 11.9% (band) vs 36.9% (joint) | ≤ band's | harness by era |
| Borrow drag | 1.22%/yr hist; 3.62% on today's book | cut by shorting different names | cef_borrow.csv |
| Availability | 11.4% of desired short book unbuildable at $500k; NAD short 8,129 vs 3,000 pool | 0% unbuildable | borrow_capacity |
| Effective breadth | 1.17 today, 2.24 hist | ≥ 4 | /api/factors |
| Execution | 2.8bp (1 MOC session), 120.6bp (abandoned method) | below 32.6bp breakeven with SE < 1bp after 60 sessions | shortfall log |
| Uptime | armed 3 of 26 sessions | every trading day, or an alert | heartbeat |
| Dust | 12 orders/session with no strategy content | 0 | /api/trades |

## Part D. How we test anything (the harness every research prompt uses)

Do not build a new backtester. Use the canonical one and extend it visibly.

```
from scripts.cef.band_frontier import build_targets, band, calendar, evaluate
T, R = build_targets()          # T: frictionless daily targets as the sleeve builds them
H_live = band(T, 0.048)         # the live policy
H_old  = calendar(T, 2)         # the previous configuration
res = evaluate(H, R)            # applies H.shift(2): decide t, MOC fill t+1, earn t+2
```

Rules:

1. **Execution convention is shift(2).** Anything scored differently is not
   comparable to any number in the repo.
2. **Turnover-matched comparisons only.** A construction that trades more
   looks better gross and worse net; neither is the point. Find the band
   width or cost coefficient that matches the reference's turn/yr within 5%
   and compare there.
3. **Cost grid 5 / 15 / 30bp** on every table. Realised cost is unknown; the
   answer must not flip sign across the grid.
4. **Borrow is charged separately and labelled.** drag_t = Σ_i max(−H_it, 0)
   · fee_i / 252, fee from the latest `data/cef/cef_borrow.csv`. One day of
   fees applied to history is a counterfactual, not a backtest; say so.
5. **Eras:** 2005–09, 2010–14, 2015–19, 2020–22, 2023–26. Pre-2013 is thin
   (fewer than `min_names` on many dates). Report era turnover sd/mean.
6. **IC** is Spearman between the signal at t and the forward 2-day return
   starting t+2, non-overlapping, expected negative.
7. **No lookahead.** Every estimated quantity uses data strictly before the
   date it is used on; state the alignment in a comment; assert it at runtime.
8. **No sweeping and picking.** Derive parameters, then check they land on a
   plateau. Picking the argmax of a swept column is how `z_window=63` was
   chosen, and it failed out of sample.
9. **The 27 untouched names** (`data/cef/cef_universe.csv` minus the 17) are
   the comparison set. Any specification change is run on them once, on the
   combined spec, before promotion. Trading any of them consumes the set.
10. **Count trials.** Every specification evaluated with sight of P&L is a
    trial in `docs/RESEARCH_STATE.md`'s CEF counter (48 after the band). The
    deflated-Sharpe bar is √(2 ln N).
11. **Pre-register before the session that trades it.**
    `results/cef/PREREG_BAND_2026-09-06.md` is the shape.
12. **Negative controls.** If a mechanism says an effect lives in munis, test
    it in HY too. If it is equally strong where the mechanism cannot operate,
    it is not what you think.
13. **Time holdout (added 2026-09-08, P8.6).** Every estimated quantity is
    fitted on data before 2023-01-01; every table shows a fit row and a
    2023–2026 holdout row. Derived quantities are computed on the fit period
    and applied unchanged. The 27 stay as the second check. Two trial
    counters: CEF (48) and GAMMA (0), each with its own √(2 ln N) bar.

## Part E. House rules for code that every prompt inherits

- **No silent fallbacks.** Never `except: pass`, never `fillna` an invented
  value, never a default for missing data. Raise, naming what was missing.
- **A new frozen-spec key must default to current behaviour**, and the
  no-op must be *proved* by diffing sleeve output byte-for-byte with the key
  absent.
- **The dashboard is read-only.** One POST route (`/api/connect`, starts
  the gateway). No code path from the dashboard transmits an order.
- **Order type stays MOC** unless a pre-registered A/B changes it.
- **`launch_job.py` lives outside the repo** on purpose (TCC). Do not move it.
- **Docstrings explain why.** Incident history lives in them.
- **Modelled sessions are not evidence.** Only broker-confirmed fills count
  toward any live statistic.

## Part F. What was found in the review (why Section 0 exists)

1. **Dust orders.** 12 of tonight's 13 orders are share-rounding drift on
   band-HOLD names, $3,019 gross, no strategy content. Roughly $15/session,
   about a third of expected net return per year, and it inflates the
   pre-registered turnover readout. → P0.1
2. **Phantom flatten.** The live broker skips an unpriceable name (fixed
   2026-09-01); the shadow ledger still flattens it. HYT lags the price panel
   by a day, so the P&L source books a $38k sale and re-buy the broker never
   sends. → P0.2
3. **Risk keys mismatch.** Spec declares `kill_drawdown`/`halve_drawdown`;
   `risk.py` reads `max_drawdown_kill_pct`. → P0.5
4. **Dashboard:** `#bookExp` null dereference when the broker is down;
   `chip bad` / tile `neg` classes undefined; three transient IB connections
   make the header flicker "Broker down"; parquet re-read per call; network
   fonts. → P0.3
5. **Missing for a trader:** borrow panel, distance to band edge, realised
   cost vs breakeven, turnover vs pre-registration, group view, order
   lifecycle, per-name history, event calendar. → Section 3.
6. **Never deployed:** price/tick-aware weighting measured +0.16 net and
   recommended "Adopt" on 2026-07-31. → P1.8

Two rough measurements from the review (single pass, not trials):

Pairwise correlation of daily discount changes, 2015+:

| | muni | multi | hy |
|---|---:|---:|---:|
| muni | 0.66 | 0.35 | 0.42 |
| multi | | 0.53 | 0.48 |
| hy | | | 0.57 |

Mean daily discount change by month and group, 2010+, bp/day:

| group | Jan | Jul | Sep | Nov | Dec |
|---|---:|---:|---:|---:|---:|
| multi | +10.5 | +3.0 | −9.6 | +1.8 | −6.0 |
| muni | +0.1 | +4.5 | −3.4 | +5.5 | −0.3 |
| hy | +1.1 | −0.4 | −4.4 | +1.7 | −0.8 |
| loan | +3.9 | +0.8 | +0.2 | +6.5 | +1.3 |

## Part H. Options: what gamma scalping can and cannot be here (added 2026-09-08)

The team asked whether gamma scalping — long options, delta-hedged,
harvesting realised against implied volatility — can be part of the book.
Three facts bound the answer, and the four P7 prompts follow from them.

1. **No CEF we trade has liquid listed options.** Whatever we do with
   options happens in HYG, LQD, TLT, JNK or SPY, not in the seventeen names.
   Options cannot express a discount view; they can hedge or inform it.
2. **Long gamma pays the variance risk premium.** Delta-hedged, an option's
   P&L is ½ΓS²(r² − σ²_imp Δt): realised minus implied variance. Implied runs
   1.3–1.5× realised in the repo's own SPY/QQQ data (`data/vrp/vrp_monthly.csv`).
   A systematic long-gamma book **loses on average** and wins in stress. The
   side that earns the premium — selling vol — adds to the same stress
   exposure a mean-reversion book already carries. So gamma scalping is not
   an alpha source for us; it is at most a **hedge whose carry must be paid
   for by the drawdown it removes**, judged on the book's Calmar, never on
   its own Sharpe.
3. **Whether the book is short vol is a measurement, not an opinion.**
   Every position is bounded by the z-clip, yet the portfolio may still lose
   exactly when implied vol jumps. That regression (E1 §5's short-straddle
   proxy) has never been run on the CEF book. It gates everything.

The programme, in order:

- **P7.1** measures the book's stress beta and conditional IC, and extracts
  HYG/LQD/TLT option data by the same path that produced `marks_SPY`.
  0 trials. Gates P7.2 and P7.4.
- **P7.2** — the convexity overlay: 25-delta puts on the credit ETF with the
  largest stress beta, sized by a theta budget (0.5/1/2% NAV/yr), delta-
  hedged at the close, judged on the book's Calmar and five worst months
  with the thresholds fixed in advance. 1 trial. Open only if P7.1 says the
  drawdowns are vol-state drawdowns.
- **P7.3** — a $50k gamma-scalping paper book, separate ledger, separate
  client id, long-only in options, judged on the accuracy of its P&L
  decomposition (gamma − theta − vega − hedge) and on 60 clean sessions,
  never on P&L. It teaches what gamma scalping is, measures realised vs
  implied in credit ETFs with our own executions, calibrates how kind IBKR
  paper option fills are, and proves the option ledger. 0 trials. Can start
  now.
- **P7.4** — options as *information*: the band width scaled by
  (IV/IV_med)^(2/3) from the cube-root law already in the band's
  pre-registration, and a vol target that blends implied with realised.
  No option is traded. 1 trial, gated on the 27.

The infrastructure exists: `PositionTarget` carries an `OPTION` kind,
`MarketState` has `mark_fn`/`greeks_fn`, `DerivativesLedger` books option
legs, `ibkr.py` sends them as limit orders and combos, and a trades-only
option dataset with an IV extraction path sits in `data/vrp/`. Every vol
in the programme is computed by us (Black–76 on extracted marks), never
read from IBKR's model, so every number can be reproduced.

## Part I. Standing decisions (team lead, 2026-09-08 evening)

Sixteen questions were put to the team lead after the first same-day-NAV
session showed no sponsor NAV on any vendor by 19:30. These answers are the
constraints every prompt below now inherits; a prompt that needs to depart
from one says so in its header and asks.

| question | decision |
|---|---|
| Universe | **Keep the 17.** They already *are* the liquid set (the spec's $3m ADV screen; median $5.6m). The 27 are the illiquid tail. Liquidity enters as a tilt (P1.8), not a cut. |
| Gamma scalping's role | **Both** a hedge overlay judged on the tail (P7.2) **and** a timed standalone sleeve (P8.4) — the evidence from P7.1 decides which survives. |
| Intraday discount scalping | **Research first** on PDI/PTY (P8.5). MOC stays live; nothing intraday trades without its own pre-registration. |
| Decision timing | **Morning primary, evening fallback** (P8.1): 08:30 on yesterday's complete pair, MOC for today's close; 12:00 retry; 17:30 capture. Starts Thursday 2026-09-10, after the prod/dev split on Wednesday. |
| Price source | **IBKR daily bars primary, yfinance cross-check** (P8.2). |
| NAV source | **Free channels only**: yfinance X-tickers, CEFConnect dated history, **Nuveen first-party** for the Nuveen names; agreement to the cent or the name is incomplete. No paid feed for now. |
| Options data | The R2 trades source if it carries HYG/LQD/TLT; **QuantConnect research (results only) if it does not.** |
| Gamma timing conditioners | **All three in one pre-registered run**: our CEF stress nowcast, IV cheapness/term structure, event calendar. Adopt at most one. |
| Gamma sleeve size | **Derived, Σ⁻¹·IR** against the CEF book (P6.2's rule). May be zero. |
| Holdout | **Keep the 27 and add a 2023–2026 time holdout** to every fit (P8.6). |
| Trial counters | **Two**: CEF and GAMMA, each its own bar; the combined book judged on the joint record. |
| Risk controls | **Arm HALVE/KILL on broker-confirmed NAV once P0.5 lands.** |
| Capital | **Paper indefinitely; a competition track record.** No real capital planned. |
| Judged on | **Absolute return.** P1.5 (vol target) moves up; derive the target, **cap 20%**, kill-probability and margin-cushion constraints in the memo. |
| Options permission on the paper account | **Unknown** → P8.3 audits it first; every options prompt refuses to start without "permitted". |
| Other books | **Keep the five benchmarks; retire the null trader** (P8.3, attribution-safe wind-down). |

## Part G. Index and suggested order

| file | lever | trials | touches live book |
|---|---|---:|---|
| **Section 0 — fix first** | | | |
| 01_P0.1_dust_orders.md | TC | 0 | yes (bug fix) |
| 02_P0.2_phantom_flatten.md | TC / record | 0 | ledger only |
| 03_P0.3_dashboard_hardening.md | ops | 0 | no |
| 04_P0.4_non_armed_alert_and_capture.md | uptime | 0 | no |
| 05_P0.5_risk_controls_and_kill_rule.md | governance | 0 | spec keys |
| **Section 1 — capture** | | | |
| 06_P1.1_availability_cap.md | TC, borrow | 1 | yes, pre-registered |
| 07_P1.2_borrow_aware_scoring.md | TC, borrow | 1 | yes, pre-registered |
| 08_P1.3_realised_cost_programme.md | measurement | 0 | no |
| 09_P1.4_turnover_readout.md | measurement | 0 | no |
| 10_P1.5_vol_target_memo.md | sizing | 0 | decision memo |
| 11_P1.6_breadth_tick_screen_and_27.md | BR | 1 | after the 27 |
| 12_P1.7_joint_optimiser_shadow.md | TC + BR | 0 (shadow) | shadow only |
| 13_P1.8_price_tilt_revisit.md | M8 | 1 | pre-registered |
| **Section 2 — dashboard, minimal and professional** | | | |
| 14_P2.1_information_architecture.md | | 0 | no |
| 15_P2.2_visual_system.md | | 0 | no |
| 16_P2.3_book_screen.md | | 0 | no |
| **Section 3 — trader-focused** | | | |
| 17_P3.1_blotter.md | | 0 | no |
| 18_P3.2_name_drilldown.md | | 0 | no |
| 19_P3.3_group_view.md | | 0 | no |
| 20_P3.4_order_lifecycle_journal.md | | 0 | writes a log |
| 21_P3.5_borrow_desk.md | | 0 | no |
| 22_P3.6_event_calendar.md | M6 | 0 | no |
| **Section 4 — dynamic** | | | |
| 23_P4.1_sse_push.md | | 0 | no |
| 24_P4.2_intraday_convergence.md | | 0 | no |
| 25_P4.3_session_watch.md | | 0 | no |
| **Section 5 — rigour where it is better** | | | |
| 26_P5.1_structured_covariance.md | BR, stability | 0–1 | no |
| 27_P5.2_derive_c_model.md | TC | 0 | no |
| 28_P5.3_turnover_targeting.md | robustness | 1 | no |
| 29_P5.4_nav_unsmoothing.md | M2, IC | 1 | no |
| 30_P5.5_survivorship.md | inference | 0 | no |
| 31_P5.6_inference.md | inference | 0 | no |
| 32_P5.7_conviction_band.md | TC | 1 (shared with P6.5) | no |
| **Section 6 — each fund and group as its own instrument** | | | |
| 33_P6.1_alpha_decomposition.md | BR | 0 | no |
| 34_P6.2_two_sleeves.md | BR, M5 | 1 | pre-registered |
| 35_P6.3_group_fair_value.md | M4, IC | 1 per group | on the 27 first |
| 36_P6.4_group_seasonality.md | M3 | 1 | on the 27 first |
| 37_P6.5_resolution_architecture.md | TC | 1 (shared with P5.7) | pre-registered |
| 38_P6.6_borrow_by_group.md | borrow | 0 | no |
| 39_P6.7_execution_by_group.md | execution | 0 | no |
| 40_P6.8_group_balanced_breadth.md | BR | 1 | after the 27 |
| **Section 7 — options: hedge and information, not alpha** | | | |
| 41_P7.1_stress_beta_and_option_data.md | measurement | 0 | no |
| 42_P7.2_convexity_overlay.md | drawdown / Calmar | 1 | overlay sleeve, own ledger, pre-registered; gated on P7.1 |
| 43_P7.3_gamma_learning_book.md | learning / measurement | 0 | separate $50k book, never netted |
| 44_P7.4_vol_state.md | TC, timing | 1 | after the 27; gated on P7.1 |
| **Section 8 — after the 2026-09-08 decisions** | | | |
| 45_P8.1_decision_timing.md | TC, reliability | 0 | yes — when the sleeve runs; Thursday 09-10 |
| 46_P8.2_data_independence.md | reliability | 0 | yes — where the panels are written from |
| 47_P8.3_account_audit_and_book_hygiene.md | prerequisites | 0 | winds down the null trader |
| 48_P8.4_timed_gamma_sleeve.md | second engine | 1 (GAMMA) | sleeve inside the strategy, pre-registered, Σ⁻¹·IR sized |
| 49_P8.5_intraday_discount_research.md | IC at a new horizon | 1 (CEF) | no — research only |
| 50_P8.6_holdout_and_counters.md | inference | 0 | no — amends every research prompt |

**Order:** Section 0 → measurement (P1.3, P1.4, P6.1, P5.5, P5.6, P6.6, P6.7)
→ dashboard (P2.1, P3.1, P3.3, P3.5, then the rest of 2–4) → capture trials
(P1.1, P1.2, P1.8, P5.7/P6.5 as one run, P1.7 shadow) → rigour in the joint
optimiser (P5.2, P5.1, P5.3) → group signals gated on the 27 (P1.6 step 2,
then P6.3, P6.4, P6.2, P6.8) → sizing (P1.5) once the band has 20 armed
sessions and P1.3 has an estimate.

**Options (Section 7)** run beside that order, not ahead of it: P7.3 (the
learning book) can start any time the team has attention for it — after
P8.3 says the account may trade options; P7.1 runs with the other
measurement prompts; P7.2, P7.4 and P8.4 only if P7.1 opens them, and P7.4
with the group-signal work since both are gated on the 27.

**Section 8 re-orders the front of the queue (2026-09-08):** P8.6 first (it
changes every other prompt's decision rule) → P8.3 (what the account can do;
retire the null trader) → P8.1 on Thursday 09-10 (morning decision) → P8.2
(prices from the broker, NAV from three channels) → then Section 0 as before,
with P0.5 now *arming* the controls and P1.5 promoted into the first month
because the record is judged on absolute return. P8.5 (intraday research)
and P8.4 (timed gamma) join the capture-trials phase.

Trial budget if every research prompt runs once: about 13 on the CEF counter
(48 → ~61, bar 2.80 → 2.87) and 2 on the GAMMA counter (0 → 2, bar 1.18).
