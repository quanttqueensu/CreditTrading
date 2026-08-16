# The estimator: a state-space model loses to a shorter window

**2026-07-31.** Reproduce: `scripts/cef/kalman_discount.py`.
All numbers on **2005-01 .. 2023-12-31**. The 2024-01+ holdout was **not touched**
— every specification below was chosen without seeing it.

## What was built

The live signal is `(d_t − mean_252(d)) / sd_252(d)`. A 252-day boxcar weights an
eleven-month-old discount as heavily as yesterday's and lags by roughly half its
window, so a genuine re-rating takes about a year to register. Replaced with an
unobserved-components model, estimated by Kalman **filter** (never the smoother —
the smoother uses future data and is untradeable):

    d_t     = theta_t + x_t
    theta_t = theta_{t-1} + w_t        w ~ N(0, q_theta)    fair level
    x_t     = phi * x_{t-1} + v_t      v ~ N(0, q_x)        dislocation

The tradable signal is `−x_t`: a fund whose fair discount has moved gets a new
`theta` and an `x` near zero, correctly reading as neither cheap nor rich.

`phi = 0.9722` was **measured**, not tuned — the pooled AR(1) of the demeaned
discount, implying a 24.6-day dislocation half-life. `q_x = 1` normalised, `r`
pinned small, leaving one free parameter: `lam = q_theta/q_x`.

## It works on its own terms

Post-cut mean signal — the failure the model was built to fix:

| window after cut | rolling-252 z | Kalman |
|---|---:|---:|
| t+0..21 | −0.217 | **−0.106** |
| t+21..63 | −0.286 | **−0.073** |
| t+63..126 | −0.341 | **−0.113** |

The rolling z-score reads cut funds as cheap for six months; the state-space model
does not. And `lam` plateaus from 30 to 100 at gross 1.60 — an interior plateau,
not a knife-edge.

## But the control kills it

The test this project applies to every candidate, applied to my own work: **is the
sophisticated thing better than the obvious thing?** Per-name costs, hold=2,
shift=2:

| spec | gross SR | **net SR** | turn/yr |
|---|---:|---:|---:|
| rolling z, 21d | 1.60 | 0.37 | 61.8 |
| **rolling z, 63d** | **1.72** | **0.84** | 45.3 |
| rolling z, 126d | 1.33 | 0.65 | 34.5 |
| **rolling z, 252d — LIVE** | 1.23 | **0.69** | 26.3 |
| Kalman lam=1 | 1.48 | 0.78 | 35.7 |
| Kalman lam=30 | 1.60 | 0.81 | 39.5 |

**A plain 63-day rolling window beats the state-space model on both gross and
net.** The Kalman is not worthless — it reaches nearly the same net on lower
turnover, and it genuinely fixes the post-cut misreading — but it does not earn
its complexity.

The real finding is much simpler than the machinery built to find it: **the
lookback window is too long.** 252 → 63 days is worth **net 0.69 → 0.84**, +22%,
and it is a one-line change to the frozen spec.

63d is an interior optimum — 21d is worse (0.37, turnover eats it) and 126d is
worse (0.65) — so this is a peak, not a boundary artifact.

## Decision

- **Recommend:** `z_window` 252 → 63 in `cef_discount.frozen.json`.
- **Reject:** the state-space estimator. Tested, documented, not deployed.
- **Also rejected earlier:** the distribution-cut filter
  (`results/cef/DIST_CUT_NOTE.md`). Notably, the cut-inflation term inside the
  Kalman was *also* rejected — at high `lam`, `theta` already adapts fast enough
  to absorb a break without being told one happened (cuts-on 1.28 vs cuts-off
  1.60). Two independent attempts to use the distribution data both failed.

## Method note, recorded against myself

The first Kalman run was mis-specified twice and returned gross 1.05 against a
1.24 baseline. Both errors were mine, and both were found by checking the model
against the data rather than tuning it:

1. **`lam` was swept over the wrong region** (1e-5..1e-2), monotone increasing to
   the grid edge — a sweep whose optimum sits at a boundary has not found an
   optimum.
2. **The cut was modelled as a one-step jump**, when the event study says the
   re-rating is gradual: −0.044pp at t+21, −0.580pp at t+60. A one-step variance
   bump at the ex-date fires when nothing has happened and closes before it does.
   It made the post-cut misreading *worse* (−0.453 vs −0.341).

## HOLDOUT OPENED 2026-07-31 — THE CHANGE FAILED

Pre-registration `HOLDOUT_PREREG.md`, result `HOLDOUT_OPENED.json`, spec
`cef_discount.v3.20260731`. Window 2024-01-01 .. 2026-07-30, 646 days, never
previously evaluated.

| | v3 frozen (63/2) | reference as-deployed (252/5) |
|---|---:|---:|
| gross Sharpe | **1.75** | 0.96 |
| **net Sharpe** | **−0.298** | +0.352 |
| net t | −0.48 | +0.56 |
| CAGR | −2.05% | +2.09% |
| turnover/yr | **102.6** | 32.0 |
| **cost as % of gross** | **117.2%** | 63.8% |
| by year | 2024 +0.02, 2025 −1.12, 2026 +0.61 | 2024 +0.60, 2025 +0.14, 2026 +0.37 |

**Pre-registered verdict: FAIL** (net < 0.00). The `z_window=63` change is
rejected and the spec is reverted to `z_window=252, rebalance_days=5`
(`cef_discount.v4.20260731`). The 16 MOC orders queued for Monday's close were
cancelled — they implemented a configuration that no longer stands.

### What actually failed, and it was not the signal

**The signal generalised, and generalised well.** Gross Sharpe went 1.23
in-sample → **1.75 out-of-sample**, the strongest gross number the project has
produced. The discount-reversion effect is real and it is not decaying.

**Turnover is what did not generalise.** The 63-day window traded **102.6×/yr in
the holdout against 45.3×/yr in-sample — 2.3× the figure the configuration was
selected on.** Costs then consumed 117% of gross.

That is the methodological finding, and it is bigger than this one config:

> A configuration chosen on *net* Sharpe is implicitly chosen on a *turnover*
> estimate. Turnover is far less stable out-of-sample than the signal is. So
> net-Sharpe selection can fail even when the alpha is intact — and it fails
> precisely on the faster configurations, where turnover is largest and its
> instability is most costly.

Every config comparison in `AUDIT_2026-07-31.md` §3 was made this way. The hold=2
recommendation rests on the same fragile input as the window choice did, and
should be treated as unproven rather than measured.

**Costs are the binding constraint, again.** Even the surviving reference config
gives up **63.8% of gross** to spreads. That is the same wall `credit_rv`, `E1`
and `pair-reversion` hit. The alpha here is genuinely better than any of them —
gross 1.75 — and it is still barely worth trading after costs.

### What this does NOT license

The reference config scored +0.352 on the holdout, inside the pre-registered WEAK
band. It is **not** being adopted *because* it won — the pre-registration
committed in advance that the choice between the two would not be revisited on
holdout evidence. The spec reverts to 252/5 because that is the status quo the
failed change departed from, not because of its holdout number.

Note also that +0.352 carries **t = 0.56** over 646 days. It is not significantly
different from zero. The honest reading of the whole exercise is that this sleeve
has a strong gross signal, an unproven net edge, and a cost problem.

**The holdout is now spent. No further specification work on this source.**

## Trial accounting

CEF source counter **+29** this session: 9 (distribution-cut study) + 16 (Kalman
sweeps) + 4 (window control). Deflated-Sharpe haircut rises accordingly, and the
`z_window` change is a NEW selection that has never been out-of-sample tested.

**The sealed 2024-01+ holdout remains unopened.** The disciplined sequence is:
freeze the spec (`z_window=63`, `rebalance_days=2`), then open the holdout exactly
once as the adjudicated test.
