# RESEARCH STATE — the research ledger

> **Citations written `pre-clean-slate:<path>`** name files deleted in the
> 2026-09-28 clean slate. Read one with `git show pre-clean-slate:<path>`;
> `docs/HISTORY.md` explains. They are provenance, not current state.

**What is canonical here:** the trial-counter table, the D1–D7 verdict legend,
and the KILLED, WATCH, ACTIVE and CLOSED tables. **Update the counter in the same
commit as any trial**, never at the end of a session. `python3 -m ops.orient`
(TRIALS) parses the counter table's bold rows; keep that shape.

**What is not here:** live state, which is `python3 -m ops.orient`; what the book
is and how it runs, which is `docs/SYSTEM.md`; and narrative. The dated research
write-ups that used to follow these tables — the 2026-07-31 deployment, audit,
cost-model audit, queue, data inventory, open questions and CEF v1–v3 history,
and the W14 Part A and G6 write-ups — are in the snapshot at git tag `pre-clean-slate`
`pre-clean-slate:_archive/docs/RESEARCH_STATE_2026-09-14.md`, taken 2026-09-14 at `92734a4`.

---

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
| **CEF** | **credit closed-end fund discounts** | **52** |
| **GAMMA** | **options / volatility sleeve (NEW SOURCE 2026-09-08)** | **0** |
| POSITIONING | FINRA short interest + daily short volume | 1 |
| **EVENTS** | **corporate actions from EDGAR/CRSP: CEF/BDC mergers, CEF IPOs, convertible issuance, term/tender events (NEW SOURCE 2026-10-09)** | **0** |
| **XASSET** | **cross-asset ETF/futures slate, declared up front (NEW SOURCE 2026-10-09)** | **4** |
> **2026-10-09: EVENTS and XASSET opened at 0** (team lead, `docs/SYSTEM.md` §5,
> 2026-10-09). Opening a counter spends no trial. **XASSET is a declared slate**: its
> five tests (`results/cef/RESEARCH_PLAN_2026-10-09.md` §3) are listed before any runs,
> and each is judged against the bar for the slate's full size, √(2 ln 5) = 1.79, not
> the running count. Options stay on GAMMA. Changes to the live CEF book stay on CEF.
> **The 27-name holdout is opened for event trades.** It is consumed by the first
> pre-registered test that computes returns on a `cef_universe.csv` name. The
> 2023-01-01 time holdout stays sealed.

> **2026-10-13: the GAMMA holdout was touched before it was opened.** Recorded
> so that whoever opens it knows what has already been seen. The holdout is
> 2023+ TLT data for the options sleeve: `docs/SYSTEM.md` §5, team lead
> 2026-10-09, narrowed on 2026-10-12 to "spreads and costs from 2023+ may be
> used; return-based statistics stay sealed".
>
> Gate G2 (`results/gamma/G2_GATE_FREE_DATA_2026-10-12.md`, zero trials)
> touched it on 2026-10-12, in two ways:
>
> 1. Its G2(a) headline included one 21-session realised-vol window (IV date
>    2022-12-27) that ran on January 2023 TLT returns.
> 2. It printed and read `scripts/gamma/book_vs_shortvol.py`'s labelled 2023+
>    block of book-versus-short-variance correlations. That script's second
>    method also ran one window to 2023-01-31.
>
> An independent review caught both on 2026-10-13. The effect on G2 is
> negligible: on the strict window the upper bound nets −18.9 %² (t −1.12),
> against −18.4 (t −1.09). Both scripts now refuse 2023 returns, and tests pin
> it.
>
> Earlier, before the 2026-10-12 narrowing, `results/gamma/REPRO_TLT_VRP_2026-10-11.md`
> quoted labelled 2023+ IV−RV and book-correlation figures as "description
> only". `scripts/gamma/vrp_summary.py` still prints them, and its 2004–22 row
> also runs its last window into January 2023; neither was changed here.
> **GAMMA stays at 0.**

> **2026-10-14: CEF 50 → 52** (team lead's approval of two pre-registrations;
> each counted in the commit that records its approval):
> - **Trial 51 is C5**, `results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md`:
>   the t+1 opening-auction fill.
> - **Trial 52 is C4**, `results/cef/PREREG_C4_FAMILIES_2026-10-13.md`: the
>   discount z-score pooled over five CEF families.
> - **Both are judged at N = 52, bar √(2 ln 52) = 2.811.**
> - **Trial 51 (C5): KILLED, D1, at the fit (2026-10-14).** The open fill's gain G
>   (WIDE) is +293bp/yr, SR 1.16, t 2.82. The lagged-signal placebo earns more
>   (+351bp/yr), so stage 2b kills it. It also fails D4 (MUB summed β −0.22) and
>   the bar (`_dsr` 0.61 at N = 52). **The holdout (report-only) HALTED on D-5 before
>   its gain was formed (2026-10-15):** material trades on name-days with no panel
>   close, 0.19% (WIDE) and 0.29% (deployed) against a 0.1% halt. It awaits the team
>   lead, and the kill stands either way (`results/cef/C5_RESULT_2026-10-14.md`).
>   **2026-10-19: opened once under the team lead's D-5 repair rule.** A D-5
>   name-day takes the NYSE closing print where it and CEFConnect's close agree.
>   This is a deviation after the halt, recorded in the pre-registration. Residual
>   D-5 is 0, and no other class fires. **Holdout G (WIDE): +313.6bp/yr, SR 2.12,
>   NW t 4.66**, the same at every grid point (one turnover). It has the fit's
>   sign, so stage 8 passes, but it cannot rescue: **C5 stays KILLED (D1).** The
>   counter does not move.
>
> **2026-10-14: the XASSET slate is declared at N = 4**
> (`results/xasset/PREREG_XASSET_SLATE_2026-10-12.md`, revision 3, approved):
> - **X5 was withdrawn before any data step,** on power forecast from the
>   draft's own expected Sharpes. No return had been seen.
> - **Each of X1–X4 is judged at the slate bar √(2 ln 4) = 1.665**, not the
>   2026-10-09 note's 1.79.
> - **XASSET stays at 0 until a test's Stage 0b begins.** The counter moves
>   per test (revision 3).
>
> **2026-10-14, later: XASSET Stage 0a recorded; no test entered Stage 0b.**
> - **Stage 0a is in** `results/xasset/STAGE0A_2026-10-14.md`. The spec pin
>   matches, and DG1's build gates, DG2, DG3 and Q1 pass.
> - **DG1's "rebuild unchanged in every existing column" cannot hold
>   bitwise.** The yfinance leg's Adj Close return differs by up to 0.0075bp
>   between any two builds.
> - **That question, and one about the X1/X4 placebo, are with the team lead**
>   (`results/xasset/XASSET_RESULTS_2026-10-14.md`).
> - **XASSET stays 0. N stays 4.**
>
> **2026-10-14: XASSET counter moves, one commit before each test's Stage 0b**
> (team lead's rulings recorded first, in the prereg's amendment block):
> - XASSET 0 → 1: **X1's Stage 0b begins** (trial 1 of N = 4).
> - XASSET 1 → 2: **X3's Stage 0b begins** (trial 2 of N = 4).
> - XASSET 2 → 3: **X2's Stage 0b begins** (trial 3 of N = 4).
> - XASSET 3 → 4: **X4's Stage 0b begins** (trial 4 of N = 4).
>
> **2026-10-14/15: XASSET slate outcome: all four FAIL; no sleeve**
> (`results/xasset/XASSET_RESULTS_2026-10-14.md`):
> - X1: **D1**.
> - X2: **D1**.
> - X3: **D4**, and D2 at 15bp.
> - X4: **D4**, the historical-mean rule.
>
> All four holdouts were opened once. **XASSET is at 4 = N. The slate is closed.**

> **2026-09-28: CEF 48 → 50** (`results/cef/PREREG_ALPACA_V7_2026-09-28.md`). Trial 49:
> the universe change 17 → 13 (NAD, NEA, NVG, NZF not shortable on Alpaca). Trial
> 50: `max_gross_stress` adopted and re-derived for the Alpaca account. The team lead
> ruled on 2026-09-28 that this counter (48 on `main`), not the nextgen branch's
> 53–56, is authoritative; the nextgen trials were shadow research.

> **⚠ CORRECTED 2026-09-09.** The CEF row read **18** until today, which was its
> value on 2026-07-31 when this file was last updated. It missed the +29 that
> `pre-clean-slate:results/cef/ESTIMATOR_NOTE.md` recorded that same session (9 distribution-cut
> + 16 Kalman sweeps + 4 window control) and the band trial that followed.
> **48 is correct**, and it is the figure `SYSTEM_AND_STRATEGY.md` §9 (git tag `pre-clean-slate`),
> `PREREG_BAND_2026-09-06.md` and `DUST_ORDERS_2026-09.md` have been using.
> A second counter, **GAMMA**, was opened by the 2026-09-08 standing decisions
> for the options programme (its prompts, deleted 2026-09-28, are under `pre-clean-slate:_archive/docs/prompts/gamma/`); it has its own
> deflated-Sharpe bar and the combined book is judged on the joint record.
> **This table is the canonical record — update it in the same commit as any
> trial, not at the end of a session.**

---

## Verdict legend — D1–D7

> Moved verbatim on 2026-09-13 from §2.2 of `RESEARCH_AND_METHODOLOGY.md`
> (git tag `pre-clean-slate`: `pre-clean-slate:_archive/docs/RESEARCH_AND_METHODOLOGY.md`, dated 2026-07-31).
> Every verdict in the tables below uses these codes.

"It didn't work" is not a diagnosis and cannot be acted on. We classify every
failure into one of seven types, because the correct response is different for
each, and the wrong response wastes weeks.

| code | what happened | what it means | what to do |
|---|---|---|---|
| **D1** | No edge even *before* trading costs | The effect does not exist | Kill it. No amount of tuning creates something from nothing |
| **D2** | Edge exists but costs eat it | A trading problem, not an idea problem | Trade less often, in bigger, better-chosen bets |
| **D3** | Great in old data, bad in new | Either overfitted, or the world changed | Check if the *mechanism* still holds. If yes, it's a regime shift. If no, we fooled ourselves |
| **D4** | Good numbers, but it's just market exposure | A risk premium wearing a costume | Demote it. It is not skill and must never be counted as skill |
| **D5** | Everything passes, Sharpe 0.3–0.6 | **This is not a failure. This is inventory** | Keep it. Several mediocre-but-different strategies beat one good one |
| **D6** | Works in one environment, not others | A conditional strategy, correctly identified | Only run it when its environment is present, and size it accordingly |
| **D7** | Fewer than ~250 independent trades | Not a result at all | You cannot conclude anything. Get more instruments, not more history |

D5 deserves emphasis because it is the most expensive mistake available. A
strategy with a Sharpe of 0.5 sounds disappointing. But five *unrelated* strategies
each at 0.5 combine to about 1.1 — because their bad days do not line up. Throwing
away 0.5s while hunting for a 1.5 is how people end up with nothing.

---

## KILLED — CEF construction variants

> Moved verbatim on 2026-09-13 from §7 of `SYSTEM_AND_STRATEGY.md`, written
> 2026-09-06 (git tag `pre-clean-slate`: `pre-clean-slate:_archive/docs/SYSTEM_AND_STRATEGY.md`). Figures are as
> measured then; section references (§1.2, §8.1) are to that document (git tag `pre-clean-slate`).

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

## KILLED — never re-test without new data
| id | hypothesis | cause of death | evidence | date |
|---|---|---|---|---|
| credit_rv | cross-sectional price-residual RV on credit ETFs | **D1** gross edge NEGATIVE before costs (−0.19%/yr) | sealed holdout net SR −1.44, t −2.29 | 2026-07-30 |
| E1 | HYG vs JNK raw premium/discount reversion | **D1→D5 reclassified** see WATCH | OOS SR −6.65 continuous; but band form earns 2.54%/yr→0.05%/yr, i.e. it STOPPED TRADING rather than lost | 2026-07-30 |
| S1-as-specified | per-bond staleness score using cross-issuer price disagreement | **D1** the input carries no information: median disagreement 0.09bp, p99 1.03bp across 1,132 shared bonds — all issuers buy from the SAME vendor | `pre-clean-slate:_archive/results/s1/` (git tag `pre-clean-slate`) | 2026-07-30 |
| S3-wrapper | fallen-angel forced flow expressed via ANGL/FALN vs HYG | **D4** it is a credit-quality risk premium in costume: alpha t 1.98 (need 3.0), HY beta −0.163, IG beta +0.123 (need ≤0.10). Unconditional pair (0.37) BEATS signal-conditioned (0.03–0.24) | `pre-clean-slate:results/s3/angl_expression.csv` | 2026-07-30 |
| single-fund-PD | premium/discount is still tradable in non-industrialised wrappers | **D1** dispersion is REAL and large (EMB 28.6bp, ANGL 23.3bp, viability 6-19x cost) but it is NAV staleness, not dislocation. PD predicts the NAV REVISION at t=15-24, and where it predicts price the sign is POSITIVE (EMB +15.3, LQD +11.7, HYG +10.0 on close->mid) = the ETF correctly LEADING a stale NAV. Trading it fades price discovery. Treasury controls show mid->mid t=-15..-18, a spurious-regression artifact from the shared price term, confirming the raw metric is fragile | `pre-clean-slate:_archive/results/disp/` (git tag `pre-clean-slate`) | 2026-07-31 |
| leadlag | thin wrappers lag liquid ones within an asset class (information diffusion) | **D1** pure non-synchronous trading. Raw effect was huge (mean t by group: IG_long 17.7, HY 12.4, MBS 11.7, EM 11.0, PREF 9.5) but it was measured on (H+L)/2, which is NOT a transactable price. Under executable close-to-close with the repo's T+1 convention the overall mean t goes 5.20 -> **-0.50**, and the Treasury CONTROL (+3.48) scores HIGHER than every credit group but one | `pre-clean-slate:_archive/results/leadlag/leadlag_specs.csv` (git tag `pre-clean-slate`) | 2026-07-31 |
| nport-trace-nav | rebuild daily NAV from N-PORT weights x TRACE transaction prints (mark-vs-TRACE, not mark-vs-mark) | **D7 infeasible** daily TRACE coverage of HYG's N-PORT weight is only 17-30% and DECLINING (26.5% in 2020 -> 17.4% in 2022). The bonds that print on a given day are selected for having news, so a 20%-weight subset cannot stand in for the book. N-PORT itself is sound (136,268 rows, 27 quarterly snapshots/fund, 95.3% CUSIP overlap vs the live iShares file) but is QUARTERLY not monthly, and `fair_val_level` is degenerate (135,850/135,870 corporate bonds are Level 2) | `data/holdings/nport_holdings.parquet` | 2026-07-31 |
| dealer-constraint | primary-dealer corporate inventory predicts credit excess returns (intermediary asset pricing) | **D1** ZERO credit names significant at any horizon 5-63d (best t=1.59, ANGL 42d); UST control shows the SAME magnitude (mean t 0.95-1.50), so even the sign that is there is not credit-specific | `pre-clean-slate:_archive/results/s4/dealer_constraint.csv` (git tag `pre-clean-slate`) | 2026-07-31 |
| pair-reversion | within-class wrapper pairs mean-revert; combine 22 for breadth | **D2 + capacity.** Combination thesis CONFIRMED: mean pairwise correlation +0.027, combined **GROSS Sharpe +1.03**. But (a) costs do NOT diversify while vol does, so the cost drag in Sharpe terms grows ~sqrt(N) and net falls to **-0.16**; (b) combined vol is 0.37%, so reaching the 12% mandate needs **32.8x leverage** against a ~2x Reg T ceiling. Per-pair signal is weak and honest: mean t -1.17 at h=1, 5/22 individually significant (IGLB/VCLT -3.58, SPLB/IGLB -3.20, SPHY/USHY -2.78), UST control +0.12 with 0/3 | `pre-clean-slate:_archive/results/ou/pair_sleeve_v2.csv` (git tag `pre-clean-slate`) | 2026-07-31 |
| short-pressure | crowded credit hedges (FINRA daily short volume) unwind and reverse | **D1** credit mean t 0.28/0.03/-0.20/-0.42 at h=1/3/5/10d, 2/10 names significant at the best horizon; the RATES comparison group scores HIGHER (1.01/0.92/1.05/0.45), so nothing here is credit-specific | `pre-clean-slate:_archive/results/positioning/short_pressure.csv` (git tag `pre-clean-slate`) | 2026-07-31 |
| gamma-timing-C3 | CEF discount stress nowcasts HYG realised vol, so long credit gamma can be timed | **D1 holdout.** In sample it works and is not an artifact: beside C1, β +0.0097 (t +2.42), incremental R² +0.0358, and against forward realised vol with no IV term anywhere β +0.02105 (t +3.95, n 4,851), real mean target at the 100th percentile of 20 shuffled draws. On the 2023–26 holdout the coefficient falls to **24%** of full sample (t +1.69) and on the stated target it is **−0.20**. Separately fatal: no state at any reported threshold has a positive mean target — the best is C3 > 2.0 at −0.0113, i.e. still paying 1.13 vol points. C2 is declared and UNAVAILABLE, not tested | `pre-clean-slate:results/gamma/PREREG_GAMMA_TIMING_2026-09-13.md` | 2026-09-13 |
| C5 (CEF trial 51) | filling the evening's CEF trade at the t+1 OPENING auction earns the session that t's NAV reaches (`results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md`) | **D1, artefact control (stage 2b)**: the gain is real, +293bp/yr (SR 1.16, t 2.82, 2016–22 WIDE), but the same open fill on the trade decided a day earlier earns +351bp/yr. It is session drift on the signal's trades, not NAV arrival. Also fails D4 (MUB β −0.22) and `_dsr` (0.61 at N = 52). **Holdout (opened once, 2026-10-19, under the team lead's D-5 repair rule): G +313.6bp/yr, SR 2.12, t 4.66, the fit's sign. It cannot rescue; the kill stands** | `results/cef/C5_RESULT_2026-10-14.md`; `python3 scripts/cef/c5_open_auction.py fit`; `python3 scripts/cef/c5_open_auction.py holdout` (opens once) | 2026-10-14; holdout 2026-10-19 |
| raw-flow-z | ETF creation/redemption z-score predicts returns | **D1** precise zero: 28,025 obs, all \|t\|<0.8; Treasury control equally flat. Informed and forced flow cancel when pooled | `pre-clean-slate:results/s3/flow_regression.csv` | 2026-07-30 |

| XASSET-X1 | credit and rates trend: MOP time-series momentum on HYG LQD IEF TLT EMB PFF MUB BKLN CWB | **D1**: sized gross Sharpe 0.41, NW t 1.62 < 1.96 (2008-05 to 2022-12, T 3,693). Every later rule fails too. TSH wins net; placebo p95 0.78; alpha t 0.79 with TERM β 0.17; `_dsr` (N = 4) 0.47. Holdout Sharpe −0.39. Spanned by AQR TSMOM^FI (t 5.2) | `results/xasset/x1_fit_2026-10-14.json`; `python3 scripts/xasset/x1_credit_trend.py` | 2026-10-14 |
| XASSET-X2 | front-run pension and balanced-fund rebalancing (HMM Threshold + Calendar), SPY vs IEF | **D1**: Sharpe 0.33, NW t 1.59 (2002-09 to 2022-12, T 5,118). The rates control {BIL: +w, SHY: −w} scores 0.18, at least ½ of X2's 0.33, so stage 2 fails as well. 57 turns a year; net −1.09 at 15bp. Holdout 0.25 | `results/xasset/x2_fit_2026-10-14.json`; `python3 scripts/xasset/x2_rebalancing.py` | 2026-10-14 |
| XASSET-X3 | month-end Treasury extension (Hartley & Schwarz): long IEF over the last 3 sessions | **D4**: the effect is real, but it is term premium in a part-time wrapper. Sharpe 1.04, NW t 4.94; IEF on other days −0.05; placebo passes; `_dsr` 0.999; alpha t 4.54 / 4.30. But TERM β is 0.34 / 0.33 (> 0.10), as PREREG §6 stated in advance. **Also D2**: 58 turns a year, net −0.42 at 15bp. Holdout 0.59. A TERM-hedged X3 is a new trial, if wanted | `results/xasset/x3_fit_2026-10-14.json`; `python3 scripts/xasset/x3_month_end.py` | 2026-10-14 |
| XASSET-X4 | multi-asset trend: MOP TSMOM on X1's nine plus SPY EFA EEM GLD DBC | **D4, the historical-mean rule**: Sharpe 0.45, NW t 1.964 (stage 1 passes, barely). The inception-to-date sign (TSH) beats it net at 5, 15 and 30bp. The placebo (p95 0.77) and D4 (alpha t 1.00) would also fail; `_dsr` 0.58. Holdout 0.19. Spanned by AQR TSMOM (t 5.3) | `results/xasset/x4_fit_2026-10-14.json`; `python3 scripts/xasset/x4_multi_trend.py` | 2026-10-14 |
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
| **CEF-DISC** | **credit closed-end fund discount reversion** | **Ran on IBKR paper 2026-07-31 → 2026-09-15; IBKR retired 2026-09-28; being rebuilt on Alpaca paper** | `docs/ROADMAP.md`; the 60-live-session review restarts with the Alpaca track record |
| COST-AUDIT | the 21.2%/yr modelled cost is a full-sample artifact | **RESOLVED, see below** | — |
| DISP-SCAN | PD dispersion is still wide in non-industrialised wrappers | building | — |
| NPORT | monthly holdings history 2019+ from SEC EDGAR | agent staging | EDGAR parse |
| BREADTH | 45-instrument universe | agent staging | data fetch |
| **C4** (CEF trial 52) | the live discount z-score pooled over five CEF families, on the 74 funds frozen at the 2026-10-14 re-read (65 with fit data) (`results/cef/PREREG_C4_FAMILIES_2026-10-13.md` and its four amendments) | **PASS, labelled D2** (2026-10-18; holdout opened once at `353dc57`). Fit (2026-10-14, 3be92cd; both independent reviews confirmed it): gross SR 1.217 (NW t 5.32), `_dsr` 0.991 at N = 52, every kill passed. Holdout 2023-01-03 → 2026-09-30: gross SR **0.725** (NW t 1.32), the fit's sign (stage 8 pass); net 0.382 at 5bp, **−0.304 at 15bp** (stage 9: D2), −1.332 at 30bp, flips; 2023–24 +12.78%/yr, 2025–26 −3.50%/yr. Report-only: without IGR 1.486 (net@15 +0.086); 82% of the holdout P&L in the ex-date window [0,2] (fit 33%); rho21 with the book 0.134/0.196. Recorded deviation: BTX's Stage-0 flags were cleared after the fit P&L (zero weight in the fit) **CORRECTION PENDING (2026-10-18, result note §8):** an independent review found four bad IGR price bars (2026-07-29, 08-04, 08-07, 08-11; post-split basis inside a raw pre-split series, flagged by Stage 0 Q5 on 2026-10-14 and never triaged) costing −10.87% of capital. Corrected (report-only): gross SR 1.434, net@15 +0.130, NW t 2.89, which would not carry D2; grid still flips by 30bp. R-IGR's 1.486 was this defect. Which book is the verdict: team lead's ruling | the team lead's ruling on D2 (paper only, or not), and on amendment 4's reading of IGR's 2026-08-20 amount: `results/cef/C4_RESULT_2026-10-14.md` §7, §4c |

> Rows above that point elsewhere in this file ("See QUEUE rank 1", "RESOLVED,
> see below") refer to sections now in the snapshot at git tag `pre-clean-slate`
> `pre-clean-slate:_archive/docs/RESEARCH_STATE_2026-09-14.md`. The rows themselves are unchanged.

---

## CLOSED — measured, adopted nothing, spent no trial

| id | question | verdict | evidence | date |
|---|---|---|---|---|
| W14-A | Is the book short volatility in a sense that gives a hedging option a job? | **No** — the convexity overlay (W14 Part B) is closed by its own pre-written gate | `pre-clean-slate:results/cef/STRESS_BETA_2026-09-11.md`; `python3 scripts/cef/stress_beta.py` | 2026-09-11 |
| W4 | Is the deployed discount IC an artifact of distributions, bid–ask bounce, stale NAV, ex-dates or crises, and is its P&L factor beta? | **No artifact explains a material share; not factor beta** (FF5 + UMD + Pástor–Stambaugh; betas ≤ 0.10, gross alpha t on the 3.0 bar). **The deployed 13-name, ADV-filtered IC is about half the 17-name figure the docs quote, and is concentrated in Dec–Jan and volatile states.** Fit period only; the 2023 holdout was not opened. No trial spent, no counter moved | `results/cef/W4_ARTIFACTS_2026-10-11.md`; `python3 scripts/cef/w4_artifacts.py` | 2026-10-11 |
| G6 | Can long credit gamma be timed by a declared conditioner? | **No** — no conditioner times it, and G7 does not run (C3 is in KILLED above) | `pre-clean-slate:results/gamma/PREREG_GAMMA_TIMING_2026-09-13.md`, `pre-clean-slate:results/gamma/CREDIT_BASE_RATE_2026-09-13.md`, `pre-clean-slate:results/gamma/CONDITIONERS_2026-09-13.md` | 2026-09-13 |
| W10-B | Is the deployed edge selection within groups or timing between them? (the zero-trial prerequisite of C2) | **Selection.** Deployed: within −9.07bp/z (t −3.02), between −3.29 (t −0.87); within carries 89% of live gross return, and the group spread alone earned 0.03%/yr. WIDE 13-name set (context): between is paid (−9.07, t −5.21) but less than within (−12.58). Random-group control: the real difference ranks above 18 of 20. **The deployed fit sample existed on only 43.6% of sessions and almost never held the munis**, while today's book is 67% between (long multi, short muni and JFR). Part B item 2 (separately built books at matched turnover) was **not run**: a variant comparison is a trial. C2 is cut to Part C (1 trial) plus at most 2 conditional Part D groups. No trial spent, no counter moved | `results/cef/W10_PARTB_2026-10-12.md`; `python3 scripts/cef/w10_partb.py` | 2026-10-12 |
| CORE-a, CORE-b | (a) Should the discount be distribution-adjusted around specials? (b) Is the Dec–Jan concentration a tax-loss sleeve? | **(a) No**: around specials the deployed z reads funds rich and is right (slope −49.5bp/z, t −3.76; 22 dates, D7). **(b) Not as a sleeve or gate**: the effect sits in late-December signal dates, the loser/winner gradient holds in Feb–Nov too (calendar control), there are 9 seasons (D7), and a gate is in the sizing-on-dislocation family. Kept as a declared stratum. Open proposals in the same note, not run: C5 (opening-auction fill), C2 Part C, the ex-cycle freeze. No trial spent | `results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md`; `python3 scripts/cef/core_signal_decomp.py` | 2026-10-12 |
| E1-G1a | Can E1's short-acquirer leg (CEF/BDC merger pair) be built at Alpaca? | **Not for munis, where the effect lives.** On 2026-10-13 the pending muni acquirers were 1 of 2 shortable (NZF no, MMU yes) and the historical muni acquirers 7 of 23 on today's flags: **FAIL**. Taxable (78%) and equity (62.5%) **pass**, but their at-announcement medians (+4.6bp, +15bp [S]) are already under E1's kill line. BDC is partial (n 1 and 3). At IBKR the muni shorts are mostly available, but universe muni acquirers' fees at first filing had a median of 9.43%/yr [S levels]. **E1 as designed: not recommended** (team lead to decide). No trial spent, no counter moved | `results/events/G1A_SHORTABILITY_2026-10-13.md`; `python3 scripts/events/g1a_shortability.py` | 2026-10-13 |
| SS5-MA, SS5-IBKR | (a) Is equity merger arbitrage feasible, and alpha-only, for this desk? (b) What would IBKR as a second broker cost and unlock? | **(a) Not alpha-only on the published evidence: D4 in costume.** Net of costs MP2001's index manager has α t 2.9 and β 0.12, and β 0.49 in months below −4% (a short index put); a SPY short moves the average β, not the kink, and a long-put hedge is outside the options ruling. Deal flow (3,851 listed-target deals 2010→2026-10-16, ~210–270 a year) and large-cap acquirer borrow (23 of 25 identified pending acquirers shortable and ETB at Alpaca; IBKR median 0.41%) are not the constraint; **reading is** (regex reader right on all fields for 0 of 16 sampled deals, on none of 12 stated outside dates; 4 of 10 cash-class picks were not targets). **(b)** IBKR would let the book short the six munis Alpaca cannot (0.83–5.15%/yr today) at the cost of Pro commissions, professional market data for an entity, 0% short-proceeds interest below USD 100k, and a weekly manual 2FA login the VM cannot do. No trial spent, no counter moved | `results/events/MERGER_ARB_AND_IBKR_2026-10-15.md`; `python3 scripts/events/merger_arb_feasibility.py --today 2026-10-18` | 2026-10-18 |
