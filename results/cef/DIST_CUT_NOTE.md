# Distribution cuts: the mechanism is real, the filter is not worth having

**2026-07-31.** Reproduce: `scripts/cef/dist_cut_study.py`.
Data: `data/cef/cef_dist_features.parquet`, 11,988 distributions across 44 funds,
1987–2026, of which **1,145 cuts** (median −6.9%, p25 −21.4%).

## The hypothesis

The sleeve buys funds cheap against their own 252-day discount history. That is
right when the discount is a temporary dislocation and wrong when the fund has
been permanently re-rated. The textbook cause of a permanent re-rating in a CEF is
a **distribution cut**: a fund yielding 9% that cuts to 6% loses the retail buyer
who held it for the yield, and the discount widens and stays wide. To a z-score
that looks like an unusually cheap fund, so the sleeve buys more of it.

## What the data says — the mechanism is confirmed

**1. Cuts do widen the discount, permanently.** Mean discount change, indexed to
the ex-date, in percentage points (negative = wider):

| | t−30 | t−5 | t0 | t+10 | t+21 | t+42 | t+60 |
|---|---:|---:|---:|---:|---:|---:|---:|
| cut (n=982) | +0.438 | +0.154 | 0 | −0.002 | −0.044 | −0.462 | **−0.580** |
| raise (n=859) | −0.555 | −0.423 | 0 | +0.135 | +0.368 | +0.732 | **+0.557** |
| unchanged (n=8,695) | +0.014 | +0.076 | 0 | −0.172 | −0.116 | −0.092 | **+0.011** |

The control goes nowhere. Cuts widen 0.58pp and do not recover; raises tighten
0.56pp. The sign is right and symmetric.

**2. Our own signal is demonstrably fooled.** Mean z-score of cut funds after the
cut — persistently negative, i.e. persistently reading "cheap":

| window | t+0..5 | t+5..21 | t+21..63 | t+63..126 |
|---|---:|---:|---:|---:|
| mean z | −0.260 | −0.203 | −0.286 | **−0.341** |

n = 4,880 to 61,447. The sleeve is being actively pulled into recently-cut funds
for up to six months.

**3. Cut funds do underperform — but only at long horizons.** Cross-sectional
excess return after the ex-date:

| horizon | cut | no-cut | difference | t |
|---|---:|---:|---:|---:|
| 5d | −0.122% | −0.077% | −0.045% | −0.73 |
| 10d | −0.001% | +0.053% | −0.054% | −0.69 |
| 21d | +0.047% | +0.128% | −0.081% | −0.76 |
| **63d** | −0.392% | +0.094% | **−0.486%** | **−2.91** |

## Why the filter is still not worth having

**The damage happens at 63 days. We hold for 2.** At 5, 10 and 21 days the effect
is economically small and statistically absent (|t| < 0.8). Sweeping the exclusion
window confirms it — gross Sharpe with recently-cut funds removed:

| rule | shift1 | shift2 (real execution) |
|---|---:|---:|
| **baseline, no filter** | **+1.16** | **+0.83** |
| exclude 21d, both legs | +1.13 | +0.83 |
| exclude 21d, long leg only | +1.13 | **+0.88** |
| exclude 63d, both legs | +0.84 | +0.53 |
| exclude 63d, long leg only | +1.08 | +0.74 |
| exclude 126d, both legs | +0.82 | +0.53 |
| exclude 252d, both legs | +0.32 | +0.24 |

Only one of eight variants beats baseline, by +0.05 Sharpe — inside noise, and
chosen after looking at eight. Every wider window is materially **worse**.

**The reason is breadth.** IR ≈ IC·√BR, and this strategy runs on breadth: the
median eligible universe is 8 funds. Cuts are common (1,145 events), so excluding
recently-cut funds removes a large slice of an already-thin cross-section. The
lost breadth costs more than the value trap does at a 2-day horizon.

**Decision: do not add a distribution-cut filter to the sleeve.** Recorded as a
tested-and-rejected specification, not an untried idea.

## What this changes about the estimator work

The right response to a cut is not to *remove* the fund — it is to *move its fair
discount*. A cut is a structural break in θ, the level the discount mean-reverts
to. The current 252-day rolling mean takes roughly a year to absorb one, which is
precisely why post-cut z stays at −0.34 for six months.

So this negative result is the strongest argument yet for the state-space model:
handle cuts as an observable level shift in θ_t rather than as a universe filter.
That keeps the fund, keeps the breadth, and stops the signal misreading a
re-rated fund as a cheap one. It is now the next piece of work.

**Trials: CEF counter +9** (1 event study, 8 filter variants).
