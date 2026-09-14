# RESEARCH STATE — the research ledger

**What is canonical here:** the trial-counter table, the D1–D7 verdict legend,
and the KILLED, WATCH, ACTIVE and CLOSED tables. **Update the counter in the same
commit as any trial**, never at the end of a session. `python3 -m ops.orient`
(TRIALS), `ops/prompt_status.py` and `ops/gamma_status.py` all parse the counter
table's bold rows; keep that shape.

**What is not here:** live state, which is `python3 -m ops.orient`; what the book
is and how it runs, which is `docs/SYSTEM.md`; and narrative. The dated research
write-ups that used to follow these tables — the 2026-07-31 deployment, audit,
cost-model audit, queue, data inventory, open questions and CEF v1–v3 history,
and the W14 Part A and G6 write-ups — are in the archived snapshot
`_archive/docs/RESEARCH_STATE_2026-09-14.md`, taken 2026-09-14 at `92734a4`.

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
| **CEF** | **credit closed-end fund discounts** | **48** |
| **GAMMA** | **options / volatility sleeve (NEW SOURCE 2026-09-08)** | **0** |
| POSITIONING | FINRA short interest + daily short volume | 1 |

> **⚠ CORRECTED 2026-09-09.** The CEF row read **18** until today, which was its
> value on 2026-07-31 when this file was last updated. It missed the +29 that
> `results/cef/ESTIMATOR_NOTE.md` recorded that same session (9 distribution-cut
> + 16 Kalman sweeps + 4 window control) and the band trial that followed.
> **48 is correct**, and it is the figure `SYSTEM_AND_STRATEGY.md` §9 (archived),
> `PREREG_BAND_2026-09-06.md` and `DUST_ORDERS_2026-09.md` have been using.
> A second counter, **GAMMA**, was opened by the 2026-09-08 standing decisions
> for the options programme (`docs/prompts/gamma/`); it has its own
> deflated-Sharpe bar and the combined book is judged on the joint record.
> **This table is the canonical record — update it in the same commit as any
> trial, not at the end of a session.**

---

## Verdict legend — D1–D7

> Moved verbatim on 2026-09-13 from §2.2 of `RESEARCH_AND_METHODOLOGY.md`
> (archived: `_archive/docs/RESEARCH_AND_METHODOLOGY.md`, dated 2026-07-31).
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
> 2026-09-06 (archived: `_archive/docs/SYSTEM_AND_STRATEGY.md`). Figures are as
> measured then; section references (§1.2, §8.1) are to that archived document.

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
| S1-as-specified | per-bond staleness score using cross-issuer price disagreement | **D1** the input carries no information: median disagreement 0.09bp, p99 1.03bp across 1,132 shared bonds — all issuers buy from the SAME vendor | `results/s1/` | 2026-07-30 |
| S3-wrapper | fallen-angel forced flow expressed via ANGL/FALN vs HYG | **D4** it is a credit-quality risk premium in costume: alpha t 1.98 (need 3.0), HY beta −0.163, IG beta +0.123 (need ≤0.10). Unconditional pair (0.37) BEATS signal-conditioned (0.03–0.24) | `results/s3/angl_expression.csv` | 2026-07-30 |
| single-fund-PD | premium/discount is still tradable in non-industrialised wrappers | **D1** dispersion is REAL and large (EMB 28.6bp, ANGL 23.3bp, viability 6-19x cost) but it is NAV staleness, not dislocation. PD predicts the NAV REVISION at t=15-24, and where it predicts price the sign is POSITIVE (EMB +15.3, LQD +11.7, HYG +10.0 on close->mid) = the ETF correctly LEADING a stale NAV. Trading it fades price discovery. Treasury controls show mid->mid t=-15..-18, a spurious-regression artifact from the shared price term, confirming the raw metric is fragile | `results/disp/` | 2026-07-31 |
| leadlag | thin wrappers lag liquid ones within an asset class (information diffusion) | **D1** pure non-synchronous trading. Raw effect was huge (mean t by group: IG_long 17.7, HY 12.4, MBS 11.7, EM 11.0, PREF 9.5) but it was measured on (H+L)/2, which is NOT a transactable price. Under executable close-to-close with the repo's T+1 convention the overall mean t goes 5.20 -> **-0.50**, and the Treasury CONTROL (+3.48) scores HIGHER than every credit group but one | `results/leadlag/leadlag_specs.csv` | 2026-07-31 |
| nport-trace-nav | rebuild daily NAV from N-PORT weights x TRACE transaction prints (mark-vs-TRACE, not mark-vs-mark) | **D7 infeasible** daily TRACE coverage of HYG's N-PORT weight is only 17-30% and DECLINING (26.5% in 2020 -> 17.4% in 2022). The bonds that print on a given day are selected for having news, so a 20%-weight subset cannot stand in for the book. N-PORT itself is sound (136,268 rows, 27 quarterly snapshots/fund, 95.3% CUSIP overlap vs the live iShares file) but is QUARTERLY not monthly, and `fair_val_level` is degenerate (135,850/135,870 corporate bonds are Level 2) | `data/holdings/nport_holdings.parquet` | 2026-07-31 |
| dealer-constraint | primary-dealer corporate inventory predicts credit excess returns (intermediary asset pricing) | **D1** ZERO credit names significant at any horizon 5-63d (best t=1.59, ANGL 42d); UST control shows the SAME magnitude (mean t 0.95-1.50), so even the sign that is there is not credit-specific | `results/s4/dealer_constraint.csv` | 2026-07-31 |
| pair-reversion | within-class wrapper pairs mean-revert; combine 22 for breadth | **D2 + capacity.** Combination thesis CONFIRMED: mean pairwise correlation +0.027, combined **GROSS Sharpe +1.03**. But (a) costs do NOT diversify while vol does, so the cost drag in Sharpe terms grows ~sqrt(N) and net falls to **-0.16**; (b) combined vol is 0.37%, so reaching the 12% mandate needs **32.8x leverage** against a ~2x Reg T ceiling. Per-pair signal is weak and honest: mean t -1.17 at h=1, 5/22 individually significant (IGLB/VCLT -3.58, SPLB/IGLB -3.20, SPHY/USHY -2.78), UST control +0.12 with 0/3 | `results/ou/pair_sleeve_v2.csv` | 2026-07-31 |
| short-pressure | crowded credit hedges (FINRA daily short volume) unwind and reverse | **D1** credit mean t 0.28/0.03/-0.20/-0.42 at h=1/3/5/10d, 2/10 names significant at the best horizon; the RATES comparison group scores HIGHER (1.01/0.92/1.05/0.45), so nothing here is credit-specific | `results/positioning/short_pressure.csv` | 2026-07-31 |
| gamma-timing-C3 | CEF discount stress nowcasts HYG realised vol, so long credit gamma can be timed | **D1 holdout.** In sample it works and is not an artifact: beside C1, β +0.0097 (t +2.42), incremental R² +0.0358, and against forward realised vol with no IV term anywhere β +0.02105 (t +3.95, n 4,851), real mean target at the 100th percentile of 20 shuffled draws. On the 2023–26 holdout the coefficient falls to **24%** of full sample (t +1.69) and on the stated target it is **−0.20**. Separately fatal: no state at any reported threshold has a positive mean target — the best is C3 > 2.0 at −0.0113, i.e. still paying 1.13 vol points. C2 is declared and UNAVAILABLE, not tested | `results/gamma/PREREG_GAMMA_TIMING_2026-09-13.md` | 2026-09-13 |
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

> Rows above that point elsewhere in this file ("See QUEUE rank 1", "RESOLVED,
> see below") refer to sections now in the archived snapshot
> `_archive/docs/RESEARCH_STATE_2026-09-14.md`. The rows themselves are unchanged.

---

## CLOSED — measured, adopted nothing, spent no trial

| id | question | verdict | evidence | date |
|---|---|---|---|---|
| W14-A | Is the book short volatility in a sense that gives a hedging option a job? | **No** — the convexity overlay (W14 Part B) is closed by its own pre-written gate | `results/cef/STRESS_BETA_2026-09-11.md`; `python3 scripts/cef/stress_beta.py` | 2026-09-11 |
| G6 | Can long credit gamma be timed by a declared conditioner? | **No** — no conditioner times it, and G7 does not run (C3 is in KILLED above) | `results/gamma/PREREG_GAMMA_TIMING_2026-09-13.md`, `results/gamma/CREDIT_BASE_RATE_2026-09-13.md`, `results/gamma/CONDITIONERS_2026-09-13.md` | 2026-09-13 |
