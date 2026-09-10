---
name: graveyard
description: The thirteen dead mechanisms, how each died, and the patterns behind them. Use BEFORE proposing any new signal or research direction, when an idea feels familiar, or when asked what has already been tried. Rebuilding one of these is a wasted week.
---

# The graveyard

**Check this before proposing anything.** Six of thirteen deaths were the same
mistake wearing different clothes.

## Dead — never re-test without new data

| id | hypothesis | cause of death |
|---|---|---|
| `credit_rv` | cross-sectional price-residual RV on credit ETFs | **D1** gross edge NEGATIVE before costs (−0.19%/yr); sealed holdout net SR −1.44 |
| `E1` | HYG vs JNK raw premium/discount reversion | **D5** the band form earned 2.54%/yr → 0.05%/yr: it *stopped trading* rather than lost. Edge per opportunity survived; opportunity count collapsed |
| `S1-as-specified` | per-bond staleness from cross-issuer price disagreement | **D1** the input carries no information — median disagreement 0.09bp across 1,132 shared bonds, because all issuers buy from the SAME vendor |
| `S3-wrapper` | fallen-angel forced flow via ANGL/FALN vs HYG | **D4** a credit-quality risk premium in costume. Alpha *t* 1.98 (need 3.0). The **unconditional** pair (0.37) BEAT the signal-conditioned one (0.03–0.24) |
| `single-fund-PD` | premium/discount tradable in non-industrialised wrappers | **D1** dispersion is real and large but it is NAV *staleness*, not dislocation. PD predicts the NAV **revision**; where it predicts price the sign is POSITIVE — the ETF correctly leading a stale NAV. Trading it fades price discovery |
| `leadlag` | thin wrappers lag liquid ones within an asset class | **D1** pure non-synchronous trading. Raw effect huge (mean *t* by group up to 17.7) but measured on `(H+L)/2`, **not a transactable price**. Executable close-to-close: mean *t* 5.20 → **−0.50**, and the Treasury CONTROL scored higher than every credit group but one |
| `nport-trace-nav` | rebuild daily NAV from N-PORT weights × TRACE prints | **D7 infeasible** daily TRACE coverage of HYG's N-PORT weight is 17–30% and *declining*; the bonds that print are selected for having news |
| `dealer-constraint` | primary-dealer inventory predicts credit excess returns | **D1** ZERO names significant at any horizon; the UST control shows the SAME magnitude |
| `pair-reversion` | 22 within-class wrapper pairs, combined for breadth | **D2 + capacity.** Combination thesis CONFIRMED, gross Sharpe **+1.03** — but costs do not diversify while vol does, so net fell to **−0.16**, and the mandate needed **32.8× leverage** against a 2× ceiling |
| `short-pressure` | crowded credit hedges unwind and reverse | **D1** the RATES comparison group scored HIGHER at every horizon |
| `raw-flow-z` | ETF creation/redemption z-score predicts returns | **D1** precise zero: 28,025 obs, all \|t\| < 0.8. Informed and forced flow cancel when pooled |
| `z_window = 63` | shorter discount window | Argmax of a swept column, chosen with the holdout sealed. Opened hours later: gross 1.75, **net −0.298**. Reverted to 252 |
| `OU / per-name κ` | size by per-name reversion speed | Withdrawn on measurement. OU stationary variance is σ²/2κ, so σ^d ∝ σ/√κ — **the live z-score already carries κ^(1/2)**. Measured slope −0.463 vs theory's −0.500. Multiplying by (1−φ^h) double-counts |

## Also measured and rejected

- **Signal combination with price reversal** — combined \|IC\| 0.0748 vs 0.0747 for
  discount alone. **+0.1%.** The price signal is 95% subsumed.
- **Hard group (muni) neutrality** — gross Sharpe 0.97 → 0.82.
- **Sizing up on \|z\|** — *every* threshold above zero lowers Sharpe: 0.81 → 0.40
  → 0.29 → 0.27.
- **Sizing up on dislocation** — best in *calm* markets; produced −12.9% at 35.8%
  vol in 2008.
- **Distribution data** — failed twice: as a universe filter (1 of 8 variants beat
  baseline, chosen after looking at 8) and inside the Kalman (1.60 → 1.28).
- **Sequential Σ⁻¹α + band** — at matched turnover gross **1.07, below plain α's
  1.10**. The scalar band destroys what Σ⁻¹ buys. Use the joint objective instead.
- **Full Kalman state-space model** — net 0.81, beaten by a one-line window change.

## Do not build

**Machine learning** — 17 names, one feature, IC 0.075; the bias–variance trade-off
is emphatically against it. **Regime-switching** — the dispersion-quintile table
*is* the regime study, and vol targeting already exploits it continuously.
**Jump-diffusion** — changes sizing, not signal. **Heston/SABR** — we trade no
derivatives on these names. **Almgren-Chriss scheduling** — one auction at <1%
participation; there is nothing to schedule.

## Still alive on the watch list

- **S3-forced-flow** — −424bp trough, *t* −17.5, 82–85% reversal; Test 3 monotone
  (quiet −22% recovery = information, crisis 98% = pressure). **D6**: needs a
  non-wrapper expression, a regime gate, and sizing to fraction-of-time-on. Fires 4×
  in 273 months, and is negatively correlated with everything — marginal portfolio
  value ≫ standalone Sharpe.
- **E1-band** — edge per opportunity survived across eras; only HYG's opportunity
  died, because portfolio trading industrialised that name. Nobody built a PT desk
  for HYD, HYMB, IGLB, SPLB, EMHY, preferreds or MBS.

## The two patterns

**1. Six of thirteen were stale-price artifacts.** The detection machinery here is
good. The *generation* side keeps returning to one well — price minus a stale mark —
which is dry in ETFs because APs arbitraged it, and wet in CEFs precisely because no
AP mechanism exists there. If your idea is that well again, say so.

**2. Three lost to their own control group.** Always name the negative control
before running the test, never after (H12).

**One caveat worth acting on:** any **D2** verdict reached on full-sample costs must
be re-opened. Modern-era cost is 1.73bp/trade against a full-sample 6.36bp, and
charging 2007 illiquidity to a 2024 signal manufactures a fake obstacle.

Full detail: `docs/RESEARCH_STATE.md` (KILLED/WATCH/ACTIVE/QUEUE) and
`docs/SYSTEM_AND_STRATEGY.md` §7.
