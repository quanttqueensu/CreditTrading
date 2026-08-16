# E1 — RELATIVE ETF PREMIUM/DISCOUNT (HYG vs JNK)

**VERDICT: KILL.** Net conservative Sharpe −0.17 in-sample, −3.97 out-of-sample.
The mechanism is real and was confirmed; the edge has been arbitraged away.

Format per `credit_rv_agent_workflow.md` §11. Pre-registration: `E1_PREREG.md`
(frozen 2026-07-30 before any return was examined).

---

## 1. Hypothesis and mechanism

HYG and JNK hold near-identical US high-yield exposure through different index
families. Their NAVs are struck from **evaluated/matrix bond prices** — stale and
smoothed — while the ETFs trade continuously. APs close price-to-NAV gaps by
transacting the underlying basket at roughly **145bp round trip**, quoted by
appointment. That cost is the width of the no-arbitrage band.

**Who loses:** the flow-driven participant who must transact in one wrapper today
— a pension buying HYG for liquidity, an allocator buying JNK for fee. Each pushes
its own wrapper off fair value and pays the dislocation.

**Why they persist:** for them it is not an arbitrage, it is the cost of executing
a mandate; the tracking error of waiting dominates the 20bp given away. The agent
who could close it (the AP) only fires above its ~145bp threshold.

**What would kill it:** electronification of the underlying bond market narrowing
the AP round trip. *This is what happened — see §9.*

## 2. Instruments, expression, neutralization

Long/short HYG vs JNK, **never outright**. The traded quantity is the *difference*
of the two premium/discounts, so the common stale-NAV component cancels. An
outright P/D trade fades genuine price discovery (the ETF leading its own stale
NAV) and is explicitly not this strategy. Unit of neutralization: beta-scaled
spread exposure, not dollars.

## 3. Data and point-in-time handling

- Premium/discount: `data/forced_flow2/hyg_jnk_pd_derived.parquet`, 2007-04-11 →
  2026-07-24, 9,540 rows. **Validated against official issuer P/D** on the
  2025-01→2026-07 overlap: HYG corr **1.0000** (MAE 0.0000pp), JNK corr **0.9959**
  (MAE 0.0118pp, bias −0.0035pp).
- Returns: `data/etf_daily.parquet` — CRSP to 2024-12-31, yfinance splice after,
  audited to <5bp on the overlap year.
- NAV is struck at 16:00 and published that evening, so `PD(t)` → trade at
  `close(t+1)` is point-in-time clean. No same-close signal-and-execution.

## 4. Estimation and fitted parameters

Relative premium `S = PD_mid(HYG) − PD_mid(JNK)`, OU fitted by AR(1), PIT:

| sample | AR(1) | half-life | σ_eq | R² |
|---|---|---|---|---|
| full 2007–2026 | 0.6713 | **1.74d** | 53.2bp | 0.453 |
| IS 2007–2019 | 0.6707 | 1.74d | 65.2bp | 0.452 |
| OOS 2020–2023 | 0.5499 | 1.16d | **14.2bp** | 0.302 |

The 4.6× collapse in σ_eq between IS and OOS is the headline, not the Sharpe.

**Bounce control.** The signal is built on `(H+L)/2`, not the close, because
`PD = (price − NAV)/NAV` inherits the closing print's bid-ask alternation. Split
safety via the ratio identity `PD_mid = (M/P)(1+PD_price) − 1`.

Pre-committed 2×2 (§3.1 of the prereg):

| lag-1 Sharpe | return on CLOSE | return on MID |
|---|---|---|
| **signal from CLOSE** | 1.25 | −0.03 |
| **signal from MID** | **0.66** | 0.83 |

`close→mid = −0.03` — a close-built signal does not predict fair value at all,
exactly as in the predecessor family. `mid→mid = 0.83` and `mid→close = 0.66`
show the NAV-based premium carries information no price-only signal had. **2×2
PASSES.** The lag-2 collapse (0.66 → 0.04) is consistent with a 1.74-day
half-life — the dislocation is genuinely gone by then — not with bounce.

## 5. Cost model, gross vs net edge per round trip

Every term measured, none assumed. Half-spreads from IBKR historical `BID_ASK`,
RTH, closing-window median (SPY control returned 0.068bp against a ~0.1bp truth):
**HYG 0.63bp, JNK 0.52bp**. Borrow from `data/financing_curve.parquet` (mean
1.90%/yr on the short leg). Round trip, both legs in and out: **2.29bp**.

| period | turn/yr | hold | gross bp/turn | cost bp/turn | ratio | net %/yr | net SR |
|---|---|---|---|---|---|---|---|
| IS 2007–2019 | 116 | 4.4d | 3.72 | 1.79 | **2.07×** | +2.23 | +0.64 |
| OOS 2020–2023 | 130 | 3.9d | **−0.15** | 2.36 | −0.06× | −3.27 | −6.65 |

## 6. Validation

Gate §5.6 requires gross edge ≥ **2.5×** cost. IS 2.07× → FAIL. OOS −0.06× → FAIL.
Not run further: DSR/PBO/bootstrap are not meaningful on a negative OOS edge, and
running them would burn trials for no information.

## 7. Carry/beta

Not reached. The verdict rule (§8 of the prereg) fires on the §6 failure before
the carry/beta regression is informative. Noted: the banded variant held a
position **72% of days** with borrow at 0.66–1.49%/yr — i.e. the "RV" strategy
degenerates into a carry position, which is trap §2.3(a).

## 8. Frequency test

Median hold 3.9–4.4d against a 1.74d half-life = 2.2–2.5 half-lives, above the
0.5–1.5 target. 275 banded trades over IS+OOS, so the ≥250 requirement is met —
the sample is adequate; the edge is not.

## 9. Failure mode — WHY IT DIED, AND IT IS THE USEFUL RESULT

Dispersion of the relative premium, by year (sd, bp of NAV):

| 2008 | 2010 | 2013 | 2017 | 2019 | 2021 | 2023 | 2026 |
|---|---|---|---|---|---|---|---|
| 187.9 | 34.2 | 14.0 | 5.6 | 5.1 | 4.4 | 6.6 | **3.8** |

A ~**40× collapse**, monotone, with AR(1) decaying 0.82 → 0.29. The dislocation is
now ~4bp against a 2.29bp round-trip cost — there is no longer room between the
mispricing and the cost of capturing it.

This is precisely the death named in prereg §1(d) before any test was run:
electronification of corporate bond trading (portfolio trades, all-to-all venues)
cut the AP's round-trip cost, which narrowed the no-arbitrage band, which is the
band this strategy harvested. **The mechanism was correct. The edge was real. It
has been competed away.**

Both specifications fail:
- continuous `w ∝ −z`: net SR −6.65 OOS
- cost-derived OU bands (the pre-registered form): net SR −0.17 IS, −3.97 OOS,
  and it degenerates into carry

## 10. Verdict

**KILL** — the dislocation this strategy harvests has decayed below its own
transaction cost, confirmed on 19 years of validated premium/discount data.

**Corroboration from an unrelated route.** The `credit_rv` family (cross-sectional
price residuals, different signal, different data) failed its sealed 2024–2026
holdout the same night: net Sharpe **−1.44**, and **gross edge negative**
(−0.19%/yr) before any cost. Two independent measurements of the same complex
agree. Do not spend further trials on wrapper-level dislocation in US credit ETFs
without first showing the dispersion has widened again — `results/e1/` contains
the series to check that against.
