"""Report-only exposure readout: the book's TERM / CREDIT / MUNI / LOANS exposure, per day.

ZERO TRIALS. IT READS A BOOK AND REPORTS. IT NEVER TRADES.

WHY THIS EXISTS (team lead, 2026-11-02)
---------------------------------------
The live attribution of the cef paper account (results/cef/LIVE_ATTRIBUTION_2026-11-02.md,
PR #26) split its 09-29..10-30 loss into a discount part (the signal's leg) that made money
and a NAV part that lost it, most of it in the muni shorts as muni NAVs rose against
taxable ones [S: that note]. The Sharpe-framed NAV hedge was screened the same day and
CLOSED at the power gate (results/cef/NAVHEDGE_SCREEN_2026-11-02.md). The team lead
approved this readout in its place: position-based daily telemetry of the live book's
exposure to rates, HY credit, munis and loans, so that the next muni-vs-taxable move is
measured, not inferred from a few weeks of P&L. It is the deleted `/api/factors`, rebuilt.

It holds no order code, imports nothing from quantt/ or src/deploy/, reads no key and
opens no broker connection. Its only network call is keyless yfinance, in `fetch`.
Nothing on the live path imports it. A test pins all of that.

    fetch       keyless yfinance -> a gitignored cache (closes, adjusted closes, actions)
    crosscheck  the cache against the repo's own panels on the overlap (read-only)
    derive      re-measures the two modelling choices below on the fit era (< 2023, H13)
    analyse     a positions CSV + the cache -> exposures, the review list, factor P&L

THE FACTORS, AND WHY THEY ARE ORTHOGONALISED
--------------------------------------------
TERM = IEF, CREDIT = HYG, MUNI = MUB, LOANS = BKLN, each a daily TOTAL return (below).

Collinearity was measured first (`derive`, fit era 2011-03-04 .. 2022-12-30, 2,978
sessions, after BKLN's first return) [V: derive, re-run 2026-11-02]:
  * full-era correlations: IEF-MUB +0.394, HYG-BKLN +0.703, MUB-HYG +0.305,
    MUB-BKLN +0.342, IEF-HYG -0.100, IEF-BKLN -0.135; VIF 1.32 / 1.48 / 2.01 / 2.14
    (IEF, MUB, HYG, BKLN); condition number of the correlation matrix 6.67;
  * but the readout estimates on a 252-session window, and there the pairs are much
    tighter and unstable. Over the era's rolling windows: IEF-MUB median +0.64, up to
    +0.83; HYG-BKLN median +0.63, up to +0.88; IEF-HYG changes sign, -0.59 to +0.50;
    MUB-HYG -0.48 to +0.64. Rolling VIF median about 1.8, max 4.5;
  * netting IEF out of the other three is not enough. The residuals MUB|IEF and HYG|IEF
    still correlate up to +0.75 (p95 +0.66), and BKLN|IEF with HYG|IEF up to +0.83
    (median +0.63).
The VIFs alone would not call this severe. The reason to orthogonalise is what the readout
reports: each factor's vol contribution |E_k| x sigma_k, read one factor at a time, and a
review rule on it. That number is the factor's contribution only if the cross terms
2 E_j E_k rho_jk sigma_j sigma_k are small, and with window correlations of 0.6-0.9 they
are as large as the own terms. Offsetting raw betas (long MUB, short IEF) would each look
large and cancel. So the four are orthogonalised by Gram-Schmidt on each window, in this
order, general to specific:
  TERM   = IEF                                  (every ETF here carries duration)
  CREDIT = HYG  net of IEF                      (HY spread, beyond rates)
  MUNI   = MUB  net of IEF and HYG              (the muni-vs-taxable move this exists for)
  LOANS  = BKLN net of IEF, HYG and MUB         (the floating-rate remainder)
Each is a tradable spread return: the ETF less its window OLS slopes times the earlier
ETFs (the intercept is not subtracted, so the factor stays a return). On the window the
four are exactly uncorrelated in sample, so the factor variance of the book is the sum of
the squared contributions on that window. CREDIT comes before MUNI because a joint
muni-and-HY sell-off (outflows, a risk-off week) is a general credit move. MUNI is then
what munis did that Treasuries and taxable HY did not. That is the muni-vs-taxable
dimension, and it is where the order matters most: the MUB|IEF and HYG|IEF residuals are
near zero in the median window but +0.66 at p95. The framework's fixed differences
(MUB - IEF, HYG - IEF; PORTFOLIO_FRAMEWORK_2026-10-15 §3.1) do not orthogonalise: the
window OLS slope of MUB on IEF has a median of +0.33 in the fit era, not 1.

Orthogonalising changes how the exposure is SPLIT, never its total. On the window the
orthogonal set spans the same space as the raw ETFs, so the fitted values, and the total
factor P&L sum_k E_k f_k, are identical in either basis; a test pins that.

DIMSON LAGS: THE LEAD-PLACEBO RULE (team lead, 2026-11-02: re-derive L before the next reading)
-----------------------------------------------------------------------------------------------
A CEF's close can trail the ETFs' closes: the fund trades thinner, and its price partly
anchors to a NAV that is struck from stale evaluated bond prices (W4 measured NAV AC(1) of
+0.26 to +0.54 by group; results/cef/W4_ARTIFACTS_2026-10-11.md §3 [S]). Dimson (1979)
regresses on the factor at t, t-1, ..., t-L and sums the betas. The exposure uses that sum:
the whole eventual response of the price to a factor move.

THE RULE. Written into this module, with its tests, and committed on its own (2026-11-03)
before it was first run on any data. No alternative to it was computed before that commit.
`lead_placebo_counts` makes the counts and `placebo_lag_rule` decides; `derive` runs both.
  Data      the cache's total returns, cut at FIT_END (2022-12-30) BEFORE anything is
            shifted, so no response, lag or lead is dated 2023 or later (H13;
            `lead_placebo_counts` raises if one is). The four ETFs orthogonalised once on the
            whole fit era, in FACTORS order. Names: the frozen spec's UNIVERSE, read at run
            time; the pairs are names x 4 factors (52 on 13 names).
  Model     ONE OLS per name: its daily total return on a constant, the four factors at lags
            0..K and the four factors at leads 1..J, with HAC (Newey-West, 5 lags) standard
            errors, on every session where all of them exist. K = DERIVE_MAX_LAG = 10, the
            bound W4 used for its NAV-staleness sensitivity. J = DERIVE_RULE_LEADS = 19.
  Counts    c(l), l = 0..K: pairs whose lag-l coefficient has a two-sided p < 0.05.
            p(j), j = 1..J: pairs whose lead-j coefficient does. Same model, same sample.
  Bound     T = max over j of p(j): the largest count the placebo produced.
  Decision  Lag 0 must have c(0) > T, or the rule raises: the factors would then explain the
            funds no better than their future returns, and no L means anything. Then for
            l = 1, 2, ..., K in that order, lag l is included if and only if c(l) > T,
            strictly. L is the last lag included before the first lag that is not.
  Ties      c(l) = T does not include lag l, and it stops the sequence.
  Gaps      A lag that clears T after a lag that did not is NOT included: the Dimson sum
            needs lags 0..L without a hole, and the sequence below needs the stop.
  Censoring If every lag 1..K clears T the rule raises. L would then be censored at K; K is
            widened only under a new rule declared first, and K is never taken as the answer.
WHY EACH PIECE
  * The null is a placebo, not Binomial(52, 0.05). A lead coefficient loads the fund's
    return on the factor's FUTURE return. With the lags in the model it has no causal
    channel unless the fund leads the ETF. So its count is what 5% noise produces under the
    real dependence among 13 co-moving funds' t-statistics, which a Binomial treats as 52
    independent draws: the review's 5-lead placebo reached 18 against a Binomial 95% point
    of 5 (below). Lags and leads come from ONE model per name so that they share the
    residuals, the HAC weights, the sample and the design; the leads are then the nearest
    available copies of a lag that carries nothing.
  * q is the maximum of J = 19 lead counts. If lag l carries no response, its count is
    (assumed) exchangeable with the 19 lead counts, and the chance that it strictly exceeds
    all 19 is at most 1/20 = 0.05. That is the placebo's 95% point in the rank sense. It
    matches the 5% that each pair is counted at, and it needs no quantile interpolated from
    a small sample. J = 19 is the fewest leads at which the maximum gives a 5% test
    (1/(J + 1) <= 0.05); a test pins that relation.
  * The fixed order. Testing lags 1, 2, ... in a declared order, each at 5%, and stopping at
    the first that fails keeps the chance of including ANY null lag at 5% with no
    multiplicity adjustment: including a null lag requires including the first null lag in
    the order, and that is one 5% event.
  * The tie. Strict ">" keeps the rank test at or below 5% when counts tie. A lag that only
    matches the largest placebo count has not shown more than the placebo.
  * Risks, stated and not corrected. (a) If a fund does lead an ETF, some lead counts are
    not null: T is then too high and L too short. (b) Exchangeability of lag and lead counts
    is an assumption [U]. (c) The 19 lead counts are correlated with each other, so the
    maximum comes from fewer than 19 effective draws [U how many].
WHAT WAS IN SIGHT WHEN THE RULE WAS WRITTEN: the review's figures below (the lags-only counts
at K = 10 and the five lead counts), all of 2026-11-02. No piece of the rule (K, J, the 5% per
pair, HAC(5), the maximum, the tie, the stop, the single joint model) was computed on data
before the commit that declared it. One consequence was visible in advance: the review's
lead-1 count (18) exceeds every lags-only count from lag 1 on, so if the 19-lead maximum
lands near it, this rule gives L = 0. That outcome was accepted in advance. The rule is not
re-tuned after it runs, and any change to it lands in a commit of its own, before it is run.

The plateau check sits beside it, as before, and nothing is chosen from it: `derive` prints
the muni names' summed MUNI beta at every L, and `analyse --plateau` the per-factor review
counts at L - 1 .. L + 2.

THE RULES IT REPLACES (2026-11-02; history). DIMSON_LAGS = 3 came from this rule (`derive`,
fit era, 13 names, factors orthogonalised on the whole era, HAC(5)) [V: derive, re-run
2026-11-02]. For each lag l, count the (name, factor) pairs, of 52, whose lag-l coefficient
is significant at 5%, with lags 0..K in the model and K = 10. Take the first gap: L = the last
lag before the first lag whose count is within Binomial(52, 0.05)'s 95% point, 5. The counts
were 43, 14, 10, 7, 2 at lags 0..4, so L = 3. `derive` still prints it and the three rules
tried before it, labelled superseded; nothing is chosen from them.

The review of 2026-11-02 (finding 1) showed that the data pin this L weakly. `derive` now
prints the first three points below and `analyse --plateau` the fourth [V: both re-run
2026-11-02]:
  * The adopted rule was the fourth tried, all in one session, and the only one that gave
    3. The first build's docstring disclosed only the first. All four, at both lag bounds:
                                                              K = 5   K = 10
      joint Wald test of lag l, a majority of the 13 names      1       1    (tried first)
      sum of lags L+1..K, pairs within the bound                2       1
      single-lag first gap (adopted)                            2       3
    One (rule, K) pair of the six gives 3. The adopted rule gives 2 at K = 5.
  * The null bound fails a placebo. Binomial(52, 0.05) treats the 52 pairs as independent,
    and 13 co-moving funds are not. With five LEADS in the model (the factors' returns at
    t+1..t+5, which cannot cause anything), 18, 1, 9, 11 and 4 pairs come out significant:
    three of the five exceed 5. Under the first-gap rule a bound of 2-6 gives L = 3, 7-9
    gives 2, 10-13 gives 1, and 14 or more gives 0. The counts at lags 5..10 (12, 9, 12, 5,
    7, 10), which the first build read as a possible weekly flow pattern, sit in the same
    range as the lead counts, so noise under that dependence explains them as well [U which].
  * The plateau check picks a hump, not a plateau. The muni names' summed MUNI beta (group
    median) is 0.97 at L = 1, 1.13 at 2, 1.42 at 3, 1.38-1.40 at 4-5, 1.11-1.23 at 6-9 and
    1.10 at 10. L = 3 is the peak, 29% above the L = 10 value. The first build called
    L = 1 "about a third short"; that compared it to the peak, and against L = 10 it is 12%
    short. The muni names' TERM beta does level off: 0.50 at L = 1, 0.63-0.65 at 3-5,
    0.63-0.74 at 6-10. CREDIT moves by up to 0.17 per group from L = 3 to L = 5 (loan
    1.00 -> 1.17, hy 1.28 -> 1.37, multi 1.35 -> 1.43, muni 0.74 -> 0.75; the first build
    said "at most 0.10", which these same figures contradict). LOANS has no plateau at any
    L: outside the loan fund (JFR) its group medians wander between -0.20 and 0.73.
  * The per-factor review counts move with L. On the first validation book, between
    L = 1 and L = 3 the dates flagged moved by 7 to 12 of 24 for TERM, CREDIT and LOANS,
    and by 3 for MUNI [V: `analyse --plateau`, 2026-11-02; the reading is not committed,
    because it derives from the account's positions]. `analyse --plateau` prints the
    counts at L = 0 .. L + 2 beside the adopted row.

The team lead ruled on 2026-11-02: re-derive L properly, under a lead-calibrated null
declared before it is run, before the next reading. THE RULE above is that null. At the
commit that declares it DIMSON_LAGS is still 3, from the superseded first-gap rule; it is
set to the new rule's output in a commit of its own, after `derive` has run it. The rule
reads only the fit era's public prices, never a reading of any account. Each lag costs
estimation noise: at L = 3, 17 regressors on 252 sessions, about 15 sessions each.

THE WINDOW: THE SLEEVE'S OWN z_window
-------------------------------------
W = frozen `z_window` (252 sessions today, read through scripts/cef/spec.py at run time).
  * It is the memory of the signal that chose the positions, so the readout reads the book
    through the same window as the signal that built it.
  * It is the framework's trailing-beta convention (PORTFOLIO_FRAMEWORK_2026-10-15 §3.1).
  * One year spans a full distribution and tax calendar, including munis' year-end.
  * A shorter window was tried for z and failed out of sample (the spec's z_window note).
`analyse --plateau` re-runs at W/2 and 2W (lags fixed) and at lags 0 .. L + 2 (window
fixed), and prints the factor P&L, by book and by group, and the per-factor review counts
beside the adopted row. That is a check for a plateau; nothing is chosen from it.

NO LOOKAHEAD (H7, asserted at run time)
---------------------------------------
The exposure on date t uses betas, orthogonalisation slopes and factor vols estimated on
the W sessions STRICTLY BEFORE t (the y rows), with lagged factor rows reaching L sessions
further back. `assert_strictly_before` raises `LookaheadError` if any row of either window
is dated t or later; it is an explicit raise, not an `assert`, so `python -O` cannot strip
it. The factor P&L of session t uses the exposure of the previous session (E(t-1) x f(t)),
with f(t) built from E(t-1)'s own slopes.

TOTAL RETURNS (H15)
-------------------
r_t = (1 + close_t / close_{t-1} - 1) * k_t - 1 + D_t / close_{t-1}, on yfinance's raw
`Close` and `Dividends`, where k is the split multiplier on an ex-split date: the harness's
own formula (`band_frontier.total_returns`), checked by the same split-basis guard
(`data_guards.guard_split_basis`). It does not use Yahoo's Adj Close for returns, because
Adj Close is re-based at every distribution and is not stable even between two fetches
(docs/REFERENCES.md §8, the byte-identity row). Adj Close is cached and cross-checked only.
A split and a distribution on one name-date raise, as in the harness. Yahoo reports no
capital-gains column for the CEFs; for an ETF a non-zero `Capital Gains` value raises,
because whether Yahoo also counts it in `Dividends` is not documented here [U].

The CEF closes and distributions come from the same vendor as data/cef/'s panels, so
`crosscheck` agreeing with those panels confirms the fetch, not the data (review 2026-11-02,
finding 6); every cross-check row now names its panel's vendor. docs/REFERENCES.md records
11 CRSP distributions missing from the yfinance distribution panel in 2005-2022 [S], three
of them large year-end specials (PFN 2012-12-26, PTY 2011-12-28, PCN 2012-12-26). The cache
lacks those three as well [V: cache read, 2026-11-02], so they enter `derive` as price
returns. Dropping the three name-days from derive's regressions leaves its lag counts and
the muni group's plateau table unchanged [V: re-run 2026-11-02]. All three fall years
before any 2025-26 window.

EXPOSURE, VOL CONTRIBUTION AND THE REVIEW RULE
----------------------------------------------
For held name i on date t, v_i = shares_i(t) x close_i(t), signed (a short is negative):
  E_k(t)     = sum_i v_i x beta_ik(t)                     dollars; beta = summed Dimson beta
  e_k(t)     = E_k(t) / equity(t)                         fraction of equity
  sigma_k(t) = sd of factor k's daily return on the window x sqrt(252)
  c_k(t)     = |e_k(t)| x sigma_k(t)                      ex-ante vol contribution
  t-stat     = E_k / SE(E_k), SE^2 = (v' S v) a_k' (X'X)^-1 a_k, the OLS identity for
               names that share one design X (S = the names' residual covariance, a_k
               selects factor k's lag columns). Homoskedastic OLS; read it as a guide.
The total factor vol is sqrt(e' Sigma_f e), with Sigma_f the window covariance of the
factors (diagonal on the window, by construction).

REVIEW RULE (proposed 2026-11-02, declared and committed BEFORE the first reading on any
account's positions; it is a proposal, and the team lead decides it). Provenance: the rule
landed in one commit with this module, its tests and its REFERENCES row (034f1df), so git
alone cannot show that it came first (review 2026-11-02, finding 5). File times show it as
far as they go: the first analyse run on the account's positions wrote its outputs 11 s
after that commit, and the only earlier analyse run used invented three-name positions
[V: file times, 2026-11-02]. Any change to the rule lands in a commit of its own, before
any reading made under it.
  On each date t, a factor k whose c_k(t) exceeds REVIEW_FRACTION x vol_target_annual goes
  to the team lead's review. vol_target_annual is read from the frozen spec at run time.
  NOTHING IS EVER HEDGED, TRADED OR RESIZED AUTOMATICALLY. Without an equity figure for t
  the rule is UNMEASURED on t. It is never evaluated against a default capital.

How REVIEW_FRACTION = 0.10 was derived (H14: the rule re-measures e_k and sigma_k at run
time and reads the vol target from the spec; the 0.10 is a rule, not a measurement):
  * D4 (docs/BRIEF.md; .claude/rules/research-harness.md) tolerates a factor beta of at
    most 0.10 in a strategy at its vol target ("alpha only, beta tolerated only as
    residual", team lead, 2026-10-09). PORTFOLIO_FRAMEWORK_2026-10-15 §3.1 applies the
    same bar to the whole book.
  * A beta bar does not compare factors whose vols differ. In the fit era's 252-session
    windows the orthogonal factors' median vols are TERM 5.5%, CREDIT 5.8%, MUNI 2.0% and
    LOANS 2.7% a year [V: derive, 2026-11-02]: a MUNI beta of 0.10 carries about a third
    of the risk of a CREDIT beta of 0.10. So the bar is applied to
    each factor rescaled to the book's own vol target: beta x sigma_k / vol_target <= 0.10,
    which is c_k <= 0.10 x vol_target.
  * Read another way, a factor at the line explains 0.10^2 = 1% of the target variance on
    its own, or correlates 0.10 with a book at its target.
  * Beside it the readout prints D4's literal reading |e_k| > 0.10 and the exposure's t, so
    the team lead can see whether a flag is size or noise. Neither is part of the rule.

WHAT IT REFUSES (raises, naming what is missing; never a default)
-----------------------------------------------------------------
  * a fetch as of today or later: yfinance serves today's bar intraday (REFERENCES §8);
  * a ticker whose rows are not exactly the NYSE sessions from its first row to the asof
    (`ops/schedule/nyse_calendar.py`), a duplicate row, a non-finite or non-positive close,
    a negative dividend, a non-zero ETF capital gain;
  * a held name or a factor ETF with a missing return anywhere in its window, or with fewer
    sessions than the window needs; a close missing on a positions date;
  * a split on a held name after the first positions date (the cached close would no
    longer match the share count), and a split the guard reads as already adjusted;
  * a positions file with a duplicate (date, symbol), a non-finite share count, a date
    that is not a cached session, or an equity column that holds a value that is not a
    plain number (e.g. "$100,000.00"), is empty on every row, is missing on some rows,
    differs within a date, or is not a finite positive number. A file without the column
    reads every rule cell as UNMEASURED;
  * a held symbol with no group in data/cef/cef_universe.csv;
  * any write under data/ (CLAUDE.md landmine 9), or of a file git could see in the
    repository that encloses the target (from a linked worktree, that can be the main
    checkout): the outputs carry the caller's positions, and this repository is public.

USAGE
-----
    python3 scripts/cef/exposure_readout.py fetch --asof YYYY-MM-DD [--start YYYY-MM-DD] [--cache-dir D] [--symbols S ...]
    python3 scripts/cef/exposure_readout.py crosscheck [--cache-dir D]
    python3 scripts/cef/exposure_readout.py derive [--cache-dir D]
    python3 scripts/cef/exposure_readout.py analyse --positions P.csv [--cache-dir D] [--out-dir D] [--plateau]

The positions CSV has columns date, symbol, shares (signed; short < 0), and optionally
equity (one value per date). A date's rows are the book at that date's close; a symbol
absent on a date is not held. Both default directories (results/cef/exposure_readout/
_cache and _out) are gitignored. A directory outside every git repository is allowed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.schedule import nyse_calendar as NYSE  # noqa: E402  (stdlib only)
from scripts.cef.data_guards import guard_split_basis  # noqa: E402  (numpy/pandas only)
from scripts.cef.spec import SPEC_ID, UNIVERSE, VOL_TARGET, Z_WINDOW  # noqa: E402  (a JSON read)

NY = ZoneInfo("America/New_York")
DATA_DIR = REPO / "data"
UNIVERSE_CSV = DATA_DIR / "cef" / "cef_universe.csv"
# Both gitignored (.gitignore); `_refuse_git_visible` enforces it at write time, in whichever
# repository encloses the target.
DEFAULT_CACHE = REPO / "results" / "cef" / "exposure_readout" / "_cache"
DEFAULT_OUT = REPO / "results" / "cef" / "exposure_readout" / "_out"
CACHE_FILES = ("prices.parquet", "meta.json")
OUT_FILES = ("exposure.csv", "exposure_by_group.csv", "betas.csv", "factor_defs.csv",
             "factor_pnl.csv", "summary.md")

# (factor, ETF) in Gram-Schmidt order, general to specific (module docstring).
FACTORS: tuple[tuple[str, str], ...] = (("TERM", "IEF"), ("CREDIT", "HYG"), ("MUNI", "MUB"),
                                        ("LOANS", "BKLN"))
FACTOR_NAMES = tuple(f for f, _ in FACTORS)
FACTOR_ETFS = tuple(e for _, e in FACTORS)

DIMSON_LAGS = 3          # from the SUPERSEDED first-gap rule; to be set from the lead-placebo
                         # rule's output in a commit of its own (module docstring, THE RULE)
WINDOW = Z_WINDOW        # the sleeve's own z_window, read from the frozen spec
ANNUALISE = 252          # sessions a year, the convention of every vol on this desk
D4_BETA_BAR = 0.10       # D4: factor betas <= 0.10 (docs/BRIEF.md; research-harness rules)
REVIEW_FRACTION = D4_BETA_BAR   # D4 applied to each factor rescaled to the vol target
FETCH_START = dt.date(2010, 1, 1)   # covers the fit era from BKLN's 2011-03 inception
FIT_END = pd.Timestamp("2022-12-30")   # H13: derive reads nothing after this
DERIVE_MAX_LAG = 10      # K: W4's NAV-staleness sensitivity bound (module docstring)
DERIVE_RULE_LEADS = 19   # J: the lead placebo's draws; the max of 19 is a 1/(J+1) = 5% rank test
DERIVE_RULE_ALPHA = 0.05 # two-sided p at which each (name, factor) lag or lead is counted
DERIVE_RULE_HAC = 5      # Newey-West lags of every derive regression (unchanged from 2026-11-02)
DERIVE_ALT_MAX_LAG = 5   # the bound the first lag rule was tried at (superseded; history)
DERIVE_PLACEBO_LEADS = 5 # leads in the review's 2026-11-02 placebo (superseded; history)

# The tolerances the cross-check reports against. They label disagreements; they decide
# nothing. Half a cent: yfinance stores closes as float32 and Yahoo rounds to the cent
# (docs/REFERENCES.md §8, the Alpaca daily-bars row). Dividends: Yahoo rounds to 3dp
# (same row: "dividends differ by <= $0.00054/share").
TOL_CLOSE = 0.005
TOL_DIV = 0.0006
TOL_TR_BP = 1.0

REVIEW_RULE = (
    "A factor whose ex-ante vol contribution c_k(t) = |E_k(t)/equity(t)| x sigma_k(t) exceeds "
    "REVIEW_FRACTION x vol_target_annual (the frozen spec's, read at run time) goes to the team "
    "lead's review. Nothing is ever hedged, traded or resized automatically. With no equity for "
    "t the rule is UNMEASURED on t.")


class ReadoutError(RuntimeError):
    """Missing, inconsistent or refused input. The message names what."""


class LookaheadError(ReadoutError):
    """A window reached the date it is used on (H7)."""


# --------------------------------------------------------------------------- refusals

def _refuse_data_dir(path: Path, data_dir: Path = DATA_DIR) -> None:
    """Never write under data/ (CLAUDE.md landmine 9): in every worktree it is a symlink to
    the panels the live sleeve decides on."""
    p = Path(path).resolve()
    d = Path(data_dir).resolve()
    if p == d or d in p.parents:
        raise ReadoutError(f"refusing to write {path}: it is under data/ ({d})")


def _enclosing_repo(path: Path) -> Path | None:
    """The innermost git work tree containing `path` (which need not exist yet), found the way
    git finds it: the nearest ancestor holding a `.git` entry, a directory in a main checkout
    or a file in a linked worktree. None if no ancestor has one."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def _refuse_git_visible(directory: Path, names) -> None:
    """Refuse to write any of `names` into `directory` if git could see it.

    Copied from scripts/cef/live_attribution.py (branch research-live-attribution), whose
    first build had a git-visible default out-dir (review 2026-11-02). The analyse outputs
    carry the caller's positions and the cache sits beside them, and this repository is
    public.

    The check runs in the repository that encloses the TARGET, not in this module's own
    checkout. The first build checked only its own checkout (review 2026-11-02, finding 3):
    a linked worktree sits inside the main checkout, so from the worktree `--out-dir
    <main checkout>/results/cef/x` counted as "outside the repository", was let through, and
    git in the main checkout could see the files. Now: no enclosing repository, nothing to
    check; otherwise every file must be ignored there (`git check-ignore`; a tracked file
    counts as visible). If git cannot answer, the write is refused: there is no default."""
    p = Path(directory).resolve()
    root = _enclosing_repo(p)
    if root is None:
        return
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
            raise ReadoutError(f"refusing to write in {directory}: {root} holds a .git entry but git "
                               f"does not report it as a work tree's top level (exit {top.returncode}: "
                               f"{(top.stderr or top.stdout).strip()[:200]})")
        paths = [(p / n).relative_to(root).as_posix() for n in names]
        r = subprocess.run(["git", "-C", str(root), "check-ignore", *paths],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise ReadoutError(f"refusing to write in {directory}: git could not run "
                           f"({type(e).__name__}: {e})") from None
    if r.returncode not in (0, 1):      # 0 some ignored, 1 none ignored, else an error
        raise ReadoutError(f"refusing to write in {directory}: git check-ignore exited "
                           f"{r.returncode}: {r.stderr.strip()[:200]}")
    visible = sorted(set(paths) - set(r.stdout.splitlines()))
    if visible:
        raise ReadoutError(
            f"refusing to write {visible[:3]}{' ...' if len(visible) > 3 else ''}: git in {root} "
            "can see them, and this public repository must not carry an account's positions. "
            "Use the gitignored default, or a directory outside every git repository")


def _refuse_write(directory: Path, names) -> None:
    _refuse_data_dir(directory)
    _refuse_git_visible(directory, names)


# --------------------------------------------------------------------------- fetch

def nyse_sessions(start: dt.date, end: dt.date) -> pd.DatetimeIndex:
    """NYSE sessions from start to end inclusive (ops/schedule/nyse_calendar.py rules)."""
    days, d = [], start
    while d <= end:
        if NYSE.is_trading_day(d):
            days.append(d)
        d += dt.timedelta(days=1)
    return pd.DatetimeIndex(pd.to_datetime(days))


def check_asof(asof: dt.date, now: dt.datetime | None = None) -> None:
    """The asof must be an NYSE session strictly before today in New York. yfinance serves
    the current session's bar while it trades, and a cache written at 10:46 once froze an
    intraday bar as a close (docs/REFERENCES.md §8, the byte-identity row)."""
    today = (now or dt.datetime.now(NY)).astimezone(NY).date()
    if asof >= today:
        raise ReadoutError(f"asof {asof} is not before today ({today}, New York): its bar may be "
                           "intraday. Fetch a completed session.")
    if not NYSE.is_trading_day(asof):
        raise ReadoutError(f"asof {asof} is not an NYSE session")


def validate_prices(px: pd.DataFrame, asof: dt.date) -> None:
    """Raise unless every ticker's rows are exactly the NYSE sessions from its first row to
    `asof`, with finite positive closes, non-negative dividends and no duplicate."""
    need = {"date", "ticker", "close", "adj_close", "dividend", "split"}
    miss = need - set(px.columns)
    if miss:
        raise ReadoutError(f"price cache lacks columns {sorted(miss)}")
    dup = px.duplicated(["ticker", "date"])
    if dup.any():
        raise ReadoutError(f"duplicate (ticker, date) rows: {px.loc[dup, ['ticker', 'date']].head(5).values.tolist()}")
    bad = ~np.isfinite(px["close"].to_numpy(float)) | (px["close"].to_numpy(float) <= 0)
    if bad.any():
        raise ReadoutError("non-finite or non-positive closes: "
                           f"{px.loc[bad, ['ticker', 'date']].head(5).astype(str).values.tolist()}")
    for col in ("dividend", "split"):
        v = px[col].to_numpy(float)
        if (~np.isfinite(v)).any() or (v < 0).any():
            raise ReadoutError(f"non-finite or negative {col} values: "
                               f"{px.loc[~np.isfinite(v) | (v < 0), ['ticker', 'date']].head(5).astype(str).values.tolist()}")
    for tk, g in px.groupby("ticker"):
        have = pd.DatetimeIndex(g["date"]).sort_values()
        want = nyse_sessions(have[0].date(), asof)
        missing = want.difference(have)
        extra = have.difference(want)
        if len(missing) or len(extra):
            raise ReadoutError(
                f"{tk}: rows are not the NYSE sessions {have[0].date()}..{asof}: missing "
                f"{[d.date().isoformat() for d in missing[:5]]}{' ...' if len(missing) > 5 else ''} "
                f"({len(missing)}), extra {[d.date().isoformat() for d in extra[:5]]} ({len(extra)})")


def fetch_yf(tickers, start: dt.date, asof: dt.date) -> tuple[pd.DataFrame, dict]:
    """Keyless yfinance `Ticker.history(auto_adjust=False, actions=True)` for each ticker,
    start..asof. Returns the long frame and a note of which tickers carry a Capital Gains
    column. An exception propagates; nothing is written then."""
    import yfinance as yf
    frames, cg = [], {}
    for tk in sorted(set(tickers)):
        h = yf.Ticker(tk).history(start=start.isoformat(),
                                  end=(asof + dt.timedelta(days=1)).isoformat(),
                                  auto_adjust=False, actions=True)
        if h is None or h.empty:
            raise ReadoutError(f"yfinance returned no rows for {tk}")
        miss = [c for c in ("Close", "Adj Close", "Dividends", "Stock Splits") if c not in h.columns]
        if miss:
            raise ReadoutError(f"yfinance rows for {tk} lack {miss}")
        if "Capital Gains" in h.columns:
            v = h["Capital Gains"].to_numpy(float)
            if (np.isfinite(v) & (v != 0)).any():
                raise ReadoutError(f"{tk}: yfinance reports a non-zero Capital Gains value; whether "
                                   "Dividends also counts it is not documented here (module docstring)")
            cg[tk] = "present, all zero"
        else:
            cg[tk] = "absent"
        idx = pd.DatetimeIndex(h.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)        # the exchange's wall date
        frames.append(pd.DataFrame({
            "date": idx.normalize(), "ticker": tk,
            "close": h["Close"].to_numpy(float), "adj_close": h["Adj Close"].to_numpy(float),
            "dividend": h["Dividends"].to_numpy(float), "split": h["Stock Splits"].to_numpy(float)}))
        last = frames[-1]["date"].max().date()
        if last != asof:
            raise ReadoutError(f"{tk}: the last yfinance row is {last}, not the asof session {asof}")
    px = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    return px, cg


def write_cache(cache_dir: Path, px: pd.DataFrame, meta: dict) -> None:
    cache_dir = Path(cache_dir)
    _refuse_write(cache_dir, CACHE_FILES)
    cache_dir.mkdir(parents=True, exist_ok=True)
    px.to_parquet(cache_dir / "prices.parquet", index=False)
    (cache_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))


def load_cache(cache_dir: Path) -> tuple[pd.DataFrame, dict]:
    cache_dir = Path(cache_dir)
    for n in CACHE_FILES:
        if not (cache_dir / n).exists():
            raise ReadoutError(f"{cache_dir / n} is missing: run `exposure_readout.py fetch` first")
    px = pd.read_parquet(cache_dir / "prices.parquet")
    px["date"] = pd.to_datetime(px["date"])
    meta = json.loads((cache_dir / "meta.json").read_text())
    validate_prices(px, dt.date.fromisoformat(meta["asof"]))
    return px, meta


# --------------------------------------------------------------------------- returns

def returns_panel(px: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """(R, C, sessions): wide daily total returns, wide raw closes, and the session index.

    R is the harness's formula on yfinance's raw Close and Dividends (module docstring,
    TOTAL RETURNS), with the split-basis guard. A ticker's first row has no return (NaN):
    that is the absence of a previous close, and any window that needs it raises later."""
    C = px.pivot(index="date", columns="ticker", values="close").sort_index()
    D = px.pivot(index="date", columns="ticker", values="dividend").reindex_like(C)
    S = px.pivot(index="date", columns="ticker", values="split").reindex_like(C)
    sessions = pd.DatetimeIndex(C.index)
    prev = C.shift(1)
    Rpx = C / prev - 1.0
    # yfinance codes "no split" as 0.0; the multiplier is the ratio where one is recorded
    # and 1.0 (the identity, not an estimate) where none is.
    k = S.where((S != 0.0) & S.notna(), 1.0).astype(float)
    k = guard_split_basis(Rpx, k, series="close", context="exposure_readout.returns_panel")
    clash = (k != 1.0) & (D.fillna(0.0) != 0.0)
    if clash.to_numpy().any():
        where = [(C.index[i].date().isoformat(), C.columns[j]) for i, j in np.argwhere(clash.to_numpy())]
        raise ReadoutError(f"a split and a distribution fall on the same name-date {where[:5]}; "
                           "the per-share amount is ambiguous and this module will not guess")
    R = (1.0 + Rpx) * k - 1.0 + D / prev
    return R, C, sessions


# --------------------------------------------------------------------------- windows (H7)

def assert_strictly_before(dates, t, what: str) -> None:
    """H7 at run time: every row of a window used on date t is dated strictly before t.
    An explicit raise, so `python -O` cannot strip it."""
    t = pd.Timestamp(t)
    d = pd.DatetimeIndex(dates)
    if len(d) == 0:
        raise LookaheadError(f"{what} for {t.date()} is empty")
    if d.max() >= t:
        raise LookaheadError(f"{what} for {t.date()} reaches {d.max().date()}: a window used on t "
                             "must end strictly before t (H7)")


def window_rows(sessions: pd.DatetimeIndex, t, window: int, lags: int
                ) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """(y_dates, f_dates): the `window` sessions strictly before t, and those plus `lags`
    earlier sessions (the lagged factor rows). Both are asserted strictly before t."""
    t = pd.Timestamp(t)
    i = int(sessions.searchsorted(t))
    if i >= len(sessions) or sessions[i] != t:
        raise ReadoutError(f"{t.date()} is not a session in the price cache")
    if i - window - lags < 0:
        raise ReadoutError(f"the window for {t.date()} needs {window + lags} sessions before it; "
                           f"the cache has {i}")
    y_dates = sessions[i - window:i]
    f_dates = sessions[i - window - lags:i]
    assert_strictly_before(y_dates, t, "beta window")
    assert_strictly_before(f_dates, t, "lagged factor window")
    return y_dates, f_dates


def _require_finite(frame: pd.DataFrame, what: str) -> None:
    bad = ~np.isfinite(frame.to_numpy(float))
    if bad.any():
        cells = [(frame.columns[j], frame.index[i].date().isoformat()) for i, j in np.argwhere(bad)[:5]]
        raise ReadoutError(f"{what}: {int(bad.sum())} missing or non-finite returns, e.g. {cells}. "
                           "The readout does not drop or fill them.")


# --------------------------------------------------------------------------- the fit

def orthogonaliser(E: pd.DataFrame) -> pd.DataFrame:
    """M (ETF rows x factor columns) such that E @ M is the Gram-Schmidt factor set in FACTORS
    order: each ETF less its OLS slopes (with intercept) on the earlier ETFs, on E's rows."""
    M = pd.DataFrame(0.0, index=list(FACTOR_ETFS), columns=list(FACTOR_NAMES))
    for k, (fname, etf) in enumerate(FACTORS):
        M.loc[etf, fname] = 1.0
        prev = list(FACTOR_ETFS[:k])
        if prev:
            X = np.column_stack([np.ones(len(E)), E[prev].to_numpy(float)])
            b = np.linalg.lstsq(X, E[etf].to_numpy(float), rcond=None)[0][1:]
            for j, p in enumerate(prev):
                M.loc[p, fname] = -b[j]
    return M


def design(F: pd.DataFrame, y_dates: pd.DatetimeIndex, lags: int) -> tuple[np.ndarray, list]:
    """[1, F_k(s - l) for k for l in 0..lags] for s in y_dates. F must hold the lagged rows."""
    pos = F.index.get_indexer(y_dates)
    if (pos < lags).any() or (pos < 0).any():
        raise ReadoutError("design: the factor rows do not reach the lags the window needs")
    Fv = F.to_numpy(float)
    cols, blocks = ["const"], [np.ones((len(y_dates), 1))]
    for j, k in enumerate(F.columns):
        for l in range(lags + 1):
            cols.append((k, l))
            blocks.append(Fv[pos - l, j][:, None])
    return np.hstack(blocks), cols


@dataclass
class WindowFit:
    t: pd.Timestamp
    y_dates: pd.DatetimeIndex
    f_dates: pd.DatetimeIndex
    M: pd.DataFrame                 # ETF -> factor
    beta: pd.DataFrame              # names x (factor, lag)
    beta_sum: pd.DataFrame          # names x factor (the summed Dimson beta)
    cols: list
    xtx_inv: np.ndarray
    resid_cov: pd.DataFrame         # names x names
    factor_vol: pd.Series           # annualised, on y_dates
    factor_cov: pd.DataFrame        # annualised, on y_dates
    n_obs: int
    lags: int


def fit_window(R: pd.DataFrame, sessions: pd.DatetimeIndex, t, names, *,
               window: int = WINDOW, lags: int = DIMSON_LAGS) -> WindowFit:
    """Summed-Dimson betas of each name's total return on the orthogonal factors, the
    orthogonalisation slopes and the factor vols, all from sessions strictly before t."""
    t = pd.Timestamp(t)
    names = list(names)
    y_dates, f_dates = window_rows(sessions, t, window, lags)
    for etf in FACTOR_ETFS:
        if etf not in R.columns:
            raise ReadoutError(f"factor ETF {etf} is not in the price cache")
    miss = [n for n in names if n not in R.columns]
    if miss:
        raise ReadoutError(f"held symbols not in the price cache: {miss}")
    Eraw = R.loc[f_dates, list(FACTOR_ETFS)]
    _require_finite(Eraw, f"factor ETF returns on the window for {t.date()}")
    M = orthogonaliser(Eraw.loc[y_dates])
    F = Eraw @ M
    F.columns = list(FACTOR_NAMES)
    X, cols = design(F, y_dates, lags)
    p = X.shape[1]
    if len(y_dates) <= p:
        raise ReadoutError(f"window {len(y_dates)} is not longer than the {p} regressors")
    xtx = X.T @ X
    if np.linalg.cond(xtx) > 1e12:
        raise ReadoutError(f"the factor design for {t.date()} is singular (cond {np.linalg.cond(xtx):.3g})")
    xtx_inv = np.linalg.inv(xtx)
    if names:
        Y = R.loc[y_dates, names]
        _require_finite(Y, f"held names' returns on the window for {t.date()}")
        B = xtx_inv @ X.T @ Y.to_numpy(float)
        U = Y.to_numpy(float) - X @ B
        S = U.T @ U / (len(y_dates) - p)
    else:
        B = np.zeros((p, 0))
        S = np.zeros((0, 0))
    idx = pd.MultiIndex.from_tuples(cols[1:], names=["factor", "lag"])
    beta = pd.DataFrame(B[1:].T, index=names, columns=idx)
    beta_sum = beta.T.groupby(level="factor", sort=False).sum().T.reindex(columns=list(FACTOR_NAMES))
    Fy = F.loc[y_dates]
    fcov = Fy.cov() * ANNUALISE
    return WindowFit(t=t, y_dates=y_dates, f_dates=f_dates, M=M, beta=beta, beta_sum=beta_sum,
                     cols=cols, xtx_inv=xtx_inv, resid_cov=pd.DataFrame(S, index=names, columns=names),
                     factor_vol=np.sqrt(pd.Series(np.diag(fcov), index=list(FACTOR_NAMES))),
                     factor_cov=fcov, n_obs=len(y_dates), lags=lags)


def exposures(fit: WindowFit, value: pd.Series, equity: float | None,
              vol_target: float = VOL_TARGET, review_fraction: float = REVIEW_FRACTION) -> pd.DataFrame:
    """One row per factor: E (dollars), e (fraction of equity), sigma, c, the review flag.

    `value` is shares x close per held name, SIGNED (a short is negative). The rule is
    REVIEW_RULE; with `equity` None every fraction and the flag are UNMEASURED (NaN and the
    string), never computed against a default capital."""
    names = list(fit.beta_sum.index)
    v = value.reindex(names)
    if v.isna().any():
        raise ReadoutError(f"no position value for fitted names {list(v[v.isna()].index)}")
    vv = v.to_numpy(float)
    E = pd.Series(vv @ fit.beta_sum.to_numpy(float), index=list(FACTOR_NAMES)) if names else \
        pd.Series(0.0, index=list(FACTOR_NAMES))
    vSv = float(vv @ fit.resid_cov.to_numpy(float) @ vv) if names else 0.0
    rows = []
    for k in FACTOR_NAMES:
        a = np.array([1.0 if (c != "const" and c[0] == k) else 0.0 for c in fit.cols])
        se = math.sqrt(max(vSv, 0.0) * float(a @ fit.xtx_inv @ a))
        sig = float(fit.factor_vol[k])
        c_usd = abs(float(E[k])) * sig
        if equity is None:
            e = c = frac = float("nan")
            flag = "UNMEASURED"
        else:
            e = float(E[k]) / equity
            c = abs(e) * sig
            frac = c / vol_target
            flag = "REVIEW" if c > review_fraction * vol_target else "within"
        rows.append(dict(date=fit.t, factor=k, exposure_usd=float(E[k]), exposure_frac=e,
                         factor_vol=sig, contrib_usd=c_usd, contrib_frac=c, contrib_of_target=frac,
                         d4_literal_breach=(None if equity is None else abs(e) > D4_BETA_BAR),
                         t_stat=(float(E[k]) / se if se > 0 else float("nan")), review=flag))
    return pd.DataFrame(rows)


def total_factor_vol(fit: WindowFit, E: pd.Series) -> float:
    """sqrt(E' Sigma_f E), in the units of E (dollars, or a fraction of equity)."""
    e = E.reindex(list(FACTOR_NAMES)).to_numpy(float)
    return math.sqrt(max(float(e @ fit.factor_cov.to_numpy(float) @ e), 0.0))


# --------------------------------------------------------------------------- positions

def read_positions(path: Path) -> pd.DataFrame:
    """date, symbol, shares[, equity]. Raises on anything it would otherwise have to guess."""
    P = pd.read_csv(path)
    need = {"date", "symbol", "shares"}
    miss = need - set(P.columns)
    if miss:
        raise ReadoutError(f"{path}: positions file lacks columns {sorted(miss)}")
    return validate_positions(P, str(path))


def validate_positions(P: pd.DataFrame, where: str = "positions") -> pd.DataFrame:
    P = P.copy()
    P["date"] = pd.to_datetime(P["date"])
    P["symbol"] = P["symbol"].astype(str).str.strip().str.upper()
    P["shares"] = pd.to_numeric(P["shares"], errors="raise").astype(float)
    if not np.isfinite(P["shares"].to_numpy()).all():
        raise ReadoutError(f"{where}: non-finite share counts")
    dup = P.duplicated(["date", "symbol"])
    if dup.any():
        raise ReadoutError(f"{where}: duplicate (date, symbol) rows "
                           f"{P.loc[dup, ['date', 'symbol']].astype(str).head(5).values.tolist()}")
    if "equity" in P.columns:
        # A value that is present but does not parse raises, naming it. The first build
        # coerced it to NaN, so "$100,000.00" on every row dropped the column without a word
        # and the summary blamed a missing equity (review 2026-11-02, finding 4). No format
        # is guessed here: write the equity as a plain number.
        raw = P["equity"]
        blank = raw.isna() | raw.astype(str).str.strip().eq("")
        eq = pd.to_numeric(raw.where(~blank), errors="coerce")
        bad = ~blank & eq.isna()
        if bad.any():
            raise ReadoutError(f"{where}: column 'equity' holds values that are not plain numbers, e.g. "
                               f"{raw[bad].astype(str).head(3).tolist()} (dates "
                               f"{sorted(P.loc[bad, 'date'].dt.date.astype(str).unique())[:5]}). Write it "
                               "as a number, with no currency sign or thousands separator")
        if blank.all():
            raise ReadoutError(f"{where}: column 'equity' is present but empty on every row. Drop the "
                               "column to read without equity (every rule reading is then UNMEASURED)")
        if blank.any():
            raise ReadoutError(f"{where}: equity is given on some rows and missing on others "
                               f"(dates {sorted(P.loc[blank, 'date'].dt.date.astype(str).unique())[:5]})")
        if not (np.isfinite(eq.to_numpy(float)) & (eq.to_numpy(float) > 0)).all():
            raise ReadoutError(f"{where}: equity must be a finite positive number")
        n = eq.groupby(P["date"]).nunique()
        if (n > 1).any():
            raise ReadoutError(f"{where}: more than one equity on dates "
                               f"{[d.date().isoformat() for d in n[n > 1].index[:5]]}")
        P["equity"] = eq.astype(float)
    return P.sort_values(["date", "symbol"]).reset_index(drop=True)


def load_groups(path: Path = UNIVERSE_CSV) -> dict:
    """{ticker: grp} from data/cef/cef_universe.csv (read only). Duplicates raise."""
    if not Path(path).exists():
        raise ReadoutError(f"{path} is missing: the group table needs it")
    u = pd.read_csv(path)
    if u["ticker"].duplicated().any():
        raise ReadoutError(f"{path}: duplicate tickers")
    return dict(zip(u["ticker"], u["grp"]))


# --------------------------------------------------------------------------- the readout

@dataclass
class Readout:
    exposure: pd.DataFrame
    by_group: pd.DataFrame
    betas: pd.DataFrame
    factor_defs: pd.DataFrame
    factor_pnl: pd.DataFrame
    total_vol: pd.DataFrame
    window: int
    lags: int


def readout(px: pd.DataFrame, positions: pd.DataFrame, groups: dict, *, window: int = WINDOW,
            lags: int = DIMSON_LAGS, vol_target: float = VOL_TARGET) -> Readout:
    """Exposures on every positions date, and the factor P&L on every positions date whose
    previous session is also a positions date (E(t-1) x f(t), and the lag-distributed
    second method)."""
    P = validate_positions(positions)
    dates = list(pd.DatetimeIndex(P["date"].unique()).sort_values())
    have_eq = "equity" in P.columns
    # A split after the first positions date would put the cached close on a basis the share
    # count does not share (yfinance re-bases Close for splits). Checked before the returns,
    # so the refusal names the real problem rather than the split-basis guard's symptom.
    held_any = sorted(P.loc[P["shares"] != 0, "symbol"].unique())
    sp = px[(px["ticker"].isin(held_any)) & (px["split"] != 0) & (px["date"] > dates[0])]
    if len(sp):
        raise ReadoutError(f"split records after the first positions date on held names: "
                           f"{sp[['ticker', 'date']].astype(str).values.tolist()}")
    R, C, sessions = returns_panel(px)
    off = [d for d in dates if d not in sessions]
    if off:
        raise ReadoutError(f"positions dates that are not cached sessions: {[d.date().isoformat() for d in off[:5]]}")
    nogrp = [s for s in held_any if s not in groups]
    if nogrp:
        raise ReadoutError(f"held symbols with no group in the universe table: {nogrp}")

    fits, values, eqs = {}, {}, {}
    ex_rows, grp_rows, beta_rows, def_rows, tv_rows = [], [], [], [], []
    for t in dates:
        Pt = P[P["date"] == t].set_index("symbol")
        held = list(Pt.index[Pt["shares"] != 0])
        close = C.loc[t, held] if held else pd.Series(dtype=float)
        if held and not np.isfinite(close.to_numpy(float)).all():
            raise ReadoutError(f"no close on {t.date()} for {list(close[~np.isfinite(close)].index)}")
        value = Pt.loc[held, "shares"] * close
        eq = float(Pt["equity"].iloc[0]) if have_eq else None
        fit = fit_window(R, sessions, t, held, window=window, lags=lags)
        fits[t], values[t], eqs[t] = fit, value, eq
        ex = exposures(fit, value, eq, vol_target=vol_target)
        ex_rows.append(ex)
        E = ex.set_index("factor")["exposure_usd"]
        tv = total_factor_vol(fit, E)
        tv_rows.append(dict(date=t, gross_usd=float(value.abs().sum()), net_usd=float(value.sum()),
                            total_factor_vol_usd=tv,
                            total_factor_vol_frac=(tv / eq if eq else float("nan")),
                            total_of_target=(tv / eq / vol_target if eq else float("nan")),
                            equity=(eq if eq else float("nan"))))
        for g in sorted({groups[s] for s in held}):
            mem = [s for s in held if groups[s] == g]
            Eg = value.reindex(mem).to_numpy(float) @ fit.beta_sum.loc[mem].to_numpy(float)
            for k, x in zip(FACTOR_NAMES, Eg):
                grp_rows.append(dict(date=t, grp=g, factor=k, exposure_usd=float(x),
                                     exposure_frac=(float(x) / eq if eq else float("nan"))))
        for s in held:
            for k in FACTOR_NAMES:
                row = dict(date=t, symbol=s, grp=groups[s], factor=k, beta_sum=float(fit.beta_sum.at[s, k]))
                for l in range(lags + 1):
                    row[f"beta_l{l}"] = float(fit.beta.at[s, (k, l)])
                beta_rows.append(row)
        for etf in FACTOR_ETFS:
            def_rows.append(dict(date=t, etf=etf, **{k: float(fit.M.at[etf, k]) for k in FACTOR_NAMES}))

    # factor P&L: t whose previous session is a positions date
    pnl_rows = []
    pos_set = set(dates)
    for t in dates:
        i = int(sessions.searchsorted(t))
        if i == 0 or sessions[i - 1] not in pos_set:
            continue
        tp = sessions[i - 1]
        fit, value = fits[tp], values[tp]
        held = list(value.index)
        f_t = R.loc[[t], list(FACTOR_ETFS)]
        _require_finite(f_t, f"factor ETF returns on {t.date()}")
        ft = (f_t @ fit.M).iloc[0]
        ft.index = list(FACTOR_NAMES)
        lagdates = sessions[i - lags:i + 1]           # t - lags .. t
        assert_strictly_before(fit.y_dates, tp + pd.Timedelta(days=1), "P&L fit window")
        Fl = R.loc[lagdates, list(FACTOR_ETFS)]
        _require_finite(Fl, f"factor ETF returns on {lagdates[0].date()}..{t.date()}")
        Fl = Fl @ fit.M
        Fl.columns = list(FACTOR_NAMES)
        for scope, mem in [("book", held)] + [(f"grp:{g}", [s for s in held if groups[s] == g])
                                               for g in sorted({groups[s] for s in held})]:
            v = value.reindex(mem).to_numpy(float)
            Es = v @ fit.beta_sum.loc[mem].to_numpy(float) if mem else np.zeros(len(FACTOR_NAMES))
            for j, k in enumerate(FACTOR_NAMES):
                # second method: sum_l beta_l x F_k(t - l), on t-1's holdings
                lagd = 0.0
                for l in range(lags + 1):
                    b = fit.beta.loc[mem, (k, l)].to_numpy(float) if mem else np.zeros(0)
                    lagd += float(v @ b) * float(Fl[k].iloc[-1 - l])
                pnl_rows.append(dict(date=t, prev=tp, scope=scope, factor=k,
                                     exposure_prev_usd=float(Es[j]), factor_return=float(ft[k]),
                                     pnl_summed=float(Es[j]) * float(ft[k]), pnl_lagdist=lagd))
    return Readout(exposure=pd.concat(ex_rows, ignore_index=True),
                   by_group=pd.DataFrame(grp_rows), betas=pd.DataFrame(beta_rows),
                   factor_defs=pd.DataFrame(def_rows), factor_pnl=pd.DataFrame(pnl_rows),
                   total_vol=pd.DataFrame(tv_rows), window=window, lags=lags)


# --------------------------------------------------------------------------- plateau check

PLATEAU_LAG_SPAN = 2     # lags 0 .. L + 2: brackets L the way W/2 .. 2W brackets W


def plateau_summary(ro: Readout) -> dict:
    """One plateau row: the book and group factor P&L, and the review counts per factor.

    The counts are here because the first build printed only P&L and mean |E| (review
    2026-11-02, finding 1), while the per-factor review counts were the quantity that moved
    most with the Dimson lag count."""
    ex = ro.exposure
    fp = ro.factor_pnl
    by_scope = fp.groupby("scope", sort=True)[["pnl_summed", "pnl_lagdist"]].sum() if len(fp) else None
    measured = bool((ex["review"] != "UNMEASURED").any())
    rev = ex[ex["review"] == "REVIEW"]
    big_t = rev[rev["t_stat"].abs() >= 2.0]
    count = (lambda g: {k: int(g.loc[g["factor"] == k, "date"].nunique()) for k in FACTOR_NAMES})
    return dict(
        window=ro.window, lags=ro.lags,
        book_summed=(float(by_scope.at["book", "pnl_summed"]) if by_scope is not None else float("nan")),
        book_lagdist=(float(by_scope.at["book", "pnl_lagdist"]) if by_scope is not None else float("nan")),
        group_summed=({s[4:]: float(v) for s, v in by_scope["pnl_summed"].items() if s.startswith("grp:")}
                      if by_scope is not None else {}),
        n_dates=int(ex["date"].nunique()), measured=measured,
        review=(count(rev) if measured else None), review_t2=(count(big_t) if measured else None),
        mean_abs_E={k: float(ex.loc[ex["factor"] == k, "exposure_usd"].abs().mean()) for k in FACTOR_NAMES})


def plateau_check(px: pd.DataFrame, positions: pd.DataFrame, groups: dict, ro: Readout) -> list:
    """The readout re-run at W/2 and 2W with the lags fixed, and at lags 0 .. L + 2 with the
    window fixed. A check for a plateau: NOTHING IS CHOSEN FROM IT, and the rule keeps the
    adopted W and L whatever it prints."""
    runs = [(w, ro.lags) for w in (ro.window // 2, ro.window, 2 * ro.window)]
    runs += [(ro.window, l) for l in range(0, ro.lags + PLATEAU_LAG_SPAN + 1) if l != ro.lags]
    out = []
    for w, l in runs:
        r2 = ro if (w, l) == (ro.window, ro.lags) else readout(px, positions, groups, window=w, lags=l)
        out.append(dict(plateau_summary(r2), adopted=((w, l) == (ro.window, ro.lags))))
    return out


# --------------------------------------------------------------------------- outputs

def _fmt_money(x: float) -> str:
    return "n/a" if not np.isfinite(x) else f"{x:,.0f}"


def summary_md(ro: Readout, meta: dict, plateau: list | None = None) -> str:
    L = ["# Exposure readout (report only; zero trials)", "",
         f"- spec: `{SPEC_ID}`; vol_target_annual {VOL_TARGET:.4g} (read at run time)",
         f"- window {ro.window} sessions strictly before each date; Dimson lags 0..{ro.lags}; "
         f"factors {', '.join(f'{f}={e}' for f, e in FACTORS)}, Gram-Schmidt in that order",
         f"- price cache: yfinance, asof {meta.get('asof')}, fetched {meta.get('fetched_at_utc')}",
         "", "## Review rule (declared before the first reading)", "", REVIEW_RULE,
         f"REVIEW_FRACTION = {REVIEW_FRACTION} (D4's beta bar on factors rescaled to the vol "
         "target; module docstring). Nothing is hedged automatically.", ""]
    ex = ro.exposure
    rev = ex[ex["review"] == "REVIEW"]
    unm = ex[ex["review"] == "UNMEASURED"]
    L += ["## Readings against the rule", ""]
    if len(unm):
        L.append(f"- UNMEASURED on {unm['date'].nunique()} date(s): no equity in the positions file.")
    if len(rev):
        for k, g in rev.groupby("factor", sort=False):
            m = g.loc[g["contrib_of_target"].idxmax()]
            L.append(f"- **{k}: REVIEW on {g['date'].nunique()} of {ex['date'].nunique()} dates**; "
                     f"largest c/target {m['contrib_of_target']:.3f} on {m['date'].date()} "
                     f"(E {_fmt_money(m['exposure_usd'])} USD, t {m['t_stat']:.2f})")
    else:
        L.append("- no factor over the line on any date read")
    L += ["", "## Per date", "",
          "| date | factor | E USD | E/equity | sigma | c/target | t | D4 literal | rule |",
          "|---|---|---:|---:|---:|---:|---:|---|---|"]
    for r in ex.itertuples():
        L.append(f"| {r.date.date()} | {r.factor} | {_fmt_money(r.exposure_usd)} | "
                 f"{r.exposure_frac:+.3f} | {r.factor_vol:.4f} | {r.contrib_of_target:.3f} | "
                 f"{r.t_stat:+.2f} | {r.d4_literal_breach} | {r.review} |")
    L += ["", "## Book totals per date (information; not part of the rule)", "",
          "| date | gross USD | net USD | total factor vol USD | total / target |",
          "|---|---:|---:|---:|---:|"]
    for r in ro.total_vol.itertuples():
        L.append(f"| {r.date.date()} | {_fmt_money(r.gross_usd)} | {_fmt_money(r.net_usd)} | "
                 f"{_fmt_money(r.total_factor_vol_usd)} | {r.total_of_target:.3f} |")
    if len(ro.factor_pnl):
        fp = ro.factor_pnl
        L += ["", "## Factor P&L (model reading, USD): E(t-1) x f(t) and the lag-distributed method", "",
              "| scope | factor | summed-beta | lag-distributed |", "|---|---|---:|---:|"]
        for (sc, k), g in fp.groupby(["scope", "factor"], sort=False):
            L.append(f"| {sc} | {k} | {g['pnl_summed'].sum():,.2f} | {g['pnl_lagdist'].sum():,.2f} |")
        for sc, g in fp.groupby("scope", sort=False):
            L.append(f"| {sc} | ALL | {g['pnl_summed'].sum():,.2f} | {g['pnl_lagdist'].sum():,.2f} |")
        L.append(f"\nSessions: {fp['date'].nunique()} ({fp['date'].min().date()}..{fp['date'].max().date()}).")
    if plateau:
        fac = "/".join(FACTOR_NAMES)
        L += ["", "## Plateau check: window and Dimson lags (nothing is chosen from it)", "",
              "The adopted row is marked; every other row changes one of W and L. The review "
              "counts are the dates (of those read) on which the rule flagged each factor.", "",
              f"| window | lags | book P&L summed | lag-distributed | P&L summed by group | "
              f"REVIEW dates {fac} | REVIEW and abs t >= 2 {fac} | mean abs E USD by factor |",
              "|---:|---:|---:|---:|---|---|---|---|"]
        cnt = (lambda d: "UNMEASURED" if d is None else "/".join(str(d[k]) for k in FACTOR_NAMES))
        for r in plateau:
            L.append(f"| {r['window']}{' (adopted)' if r['adopted'] else ''} | {r['lags']} | "
                     f"{r['book_summed']:,.2f} | {r['book_lagdist']:,.2f} | "
                     f"{', '.join(f'{g} {v:,.0f}' for g, v in r['group_summed'].items())} | "
                     f"{cnt(r['review'])} | {cnt(r['review_t2'])} | "
                     f"{', '.join(f'{k} {v:,.0f}' for k, v in r['mean_abs_E'].items())} |")
    return "\n".join(L) + "\n"


def write_outputs(out_dir: Path, ro: Readout, meta: dict, plateau=None) -> None:
    out_dir = Path(out_dir)
    _refuse_write(out_dir, OUT_FILES)
    out_dir.mkdir(parents=True, exist_ok=True)
    ex = ro.exposure.merge(ro.total_vol, on="date", how="left")
    ex.to_csv(out_dir / "exposure.csv", index=False)
    ro.by_group.to_csv(out_dir / "exposure_by_group.csv", index=False)
    ro.betas.to_csv(out_dir / "betas.csv", index=False)
    ro.factor_defs.to_csv(out_dir / "factor_defs.csv", index=False)
    ro.factor_pnl.to_csv(out_dir / "factor_pnl.csv", index=False)
    (out_dir / "summary.md").write_text(summary_md(ro, meta, plateau))


# --------------------------------------------------------------------------- cross-check

def _panel(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ReadoutError(f"cross-check panel {path} is missing")
    return pd.read_parquet(path)


# Who supplies each panel's numbers, and so what agreeing with it can show. This cache is
# yfinance. Agreeing with a yfinance panel shows that this fetch reproduces that one; it does
# not show the data are right (review 2026-11-02, finding 6). Only a different vendor checks
# the data. Sources: docs/REFERENCES.md, the "ETF research panels: their fetchers" row (the rv
# panels and etf_daily) and the cef_distributions-against-CRSP row (the CEF panels).
# etf_daily carries a `source` column, so it is compared one leg at a time.
PANEL_VENDOR = {
    "rv/close_unadj_wide": ("yfinance, then Alpaca after the 2026-10-11 restore's YF_LAST", "partly"),
    "rv/returns_wide": ("yfinance, then Alpaca after the 2026-10-11 restore's YF_LAST", "partly"),
    "rv/etf_ohlc_extended": ("yfinance, then Alpaca after the 2026-10-11 restore's YF_LAST", "partly"),
    "cef/cef_prices": ("yfinance", "no"),
    "cef/cef_distributions": ("yfinance Ticker.actions", "no"),
}
ETF_DAILY_LEG_INDEPENDENT = {"crsp": "yes", "alpaca": "yes", "yfinance": "no"}


def crosscheck(px: pd.DataFrame, data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, list]:
    """The cache against the repo's own panels on their overlap (read-only). Reports; decides
    nothing. Returns (table, notes): one row per (panel, field, ticker) with the overlap, the
    count above the tolerance, the largest gap, the panel's vendor on that overlap and whether
    that vendor is independent of yfinance; and notes with the panels' last dates."""
    R, C, _ = returns_panel(px)
    Dv = px.pivot(index="date", columns="ticker", values="dividend").reindex_like(C)
    rows, notes = [], []
    etfs = [e for e in FACTOR_ETFS if e in C.columns]
    cefs = [c for c in C.columns if c not in FACTOR_ETFS]

    def comp(panel, field, tk, ours: pd.Series, theirs: pd.Series, tol, scale=1.0, vendor=None):
        vend, indep = vendor if vendor is not None else PANEL_VENDOR[panel]
        a, b = ours.dropna(), theirs.dropna()
        ix = a.index.intersection(b.index)
        if not len(ix):
            rows.append(dict(panel=panel, field=field, ticker=tk, n=0, vendor=vend,
                             independent_of_yfinance=indep))
            return
        d = (a.loc[ix] - b.loc[ix]) * scale
        ad = d.abs()
        rows.append(dict(panel=panel, field=field, ticker=tk, n=len(ix), first=ix.min().date(),
                         last=ix.max().date(), n_over_tol=int((ad > tol).sum()), tol=tol,
                         max_abs=float(ad.max()), max_on=ad.idxmax().date(),
                         p99_abs=float(ad.quantile(0.99)), vendor=vend, independent_of_yfinance=indep))

    cu = _panel(data_dir / "rv" / "close_unadj_wide.parquet")
    rw = _panel(data_dir / "rv" / "returns_wide.parquet")
    ext = _panel(data_dir / "rv" / "etf_ohlc_extended.parquet")
    ed = _panel(data_dir / "etf_daily.parquet")
    cp = _panel(data_dir / "cef" / "cef_prices.parquet")
    cd = _panel(data_dir / "cef" / "cef_distributions.parquet")
    notes += [f"data/rv/close_unadj_wide.parquet last {pd.Timestamp(cu.index.max()).date()}",
              f"data/rv/returns_wide.parquet last {pd.Timestamp(rw.index.max()).date()}",
              f"data/rv/etf_ohlc_extended.parquet last {pd.Timestamp(ext['date'].max()).date()}",
              f"data/etf_daily.parquet last {pd.Timestamp(ed['date'].max()).date()}",
              f"data/cef/cef_prices.parquet last {pd.Timestamp(cp['date'].max()).date()}",
              f"data/cef/cef_distributions.parquet last ex_date {pd.Timestamp(cd['ex_date'].max()).date()}"]
    for tk in etfs:
        if tk in cu.columns:
            comp("rv/close_unadj_wide", "close", tk, C[tk], cu[tk], TOL_CLOSE)
        else:
            notes.append(f"{tk}: not in data/rv/close_unadj_wide.parquet")
        if tk in rw.columns:
            comp("rv/returns_wide", "total return (bp)", tk, R[tk], rw[tk], TOL_TR_BP, 1e4)
        else:
            notes.append(f"{tk}: not in data/rv/returns_wide.parquet")
        g = ext[ext["ticker"] == tk].set_index("date")
        if len(g):
            comp("rv/etf_ohlc_extended", "close", tk, C[tk], g["close"], TOL_CLOSE)
            comp("rv/etf_ohlc_extended", "total return (bp)", tk, R[tk], g["ret_total"], TOL_TR_BP, 1e4)
            comp("rv/etf_ohlc_extended", "dividend", tk, Dv[tk], g["dividend"], TOL_DIV)
        else:
            notes.append(f"{tk}: not in data/rv/etf_ohlc_extended.parquet")
        g = ed[ed["ticker"] == tk]
        if len(g):
            for src, leg in g.groupby("source", sort=True):
                if src not in ETF_DAILY_LEG_INDEPENDENT:
                    raise ReadoutError(f"data/etf_daily.parquet: source leg {src!r} is not one this "
                                       "cross-check knows the vendor of")
                comp(f"etf_daily[{src}]", "total return (bp)", tk, R[tk], leg.set_index("date")["ret_total"],
                     TOL_TR_BP, 1e4, vendor=(src, ETF_DAILY_LEG_INDEPENDENT[src]))
        else:
            notes.append(f"{tk}: not in data/etf_daily.parquet")
    notes.append("cef/cef_prices and cef/cef_distributions are yfinance panels, the cache's own "
                 "vendor: agreement there confirms the fetch, not the data. Their known gaps against "
                 "CRSP are in docs/REFERENCES.md (the cef_distributions-against-CRSP row)")
    last_cd = pd.Timestamp(cd["ex_date"].max())
    for tk in cefs:
        g = cp[cp["ticker"] == tk].set_index("date")
        if not len(g):
            notes.append(f"{tk}: not in data/cef/cef_prices.parquet")
            continue
        comp("cef/cef_prices", "close", tk, C[tk], g["close"], TOL_CLOSE)
        ours = px[(px["ticker"] == tk) & (px["dividend"] > 0) & (px["date"] <= last_cd)].set_index("date")["dividend"]
        theirs = cd[(cd["ticker"] == tk) & (cd["ex_date"] >= px.loc[px["ticker"] == tk, "date"].min())
                    ].groupby("ex_date")["amount"].sum()
        only_ours = ours.index.difference(theirs.index)
        only_theirs = theirs.index.difference(ours.index)
        comp("cef/cef_distributions", "dividend", tk, ours, theirs, TOL_DIV)
        rows[-1].update(only_ours=len(only_ours), only_panel=len(only_theirs))
        if len(only_ours) or len(only_theirs):
            notes.append(f"{tk}: ex-dates only in the cache {[d.date().isoformat() for d in only_ours[:4]]}, "
                         f"only in the panel {[d.date().isoformat() for d in only_theirs[:4]]}")
    return pd.DataFrame(rows), notes


# --------------------------------------------------------------------------- derive

def derive(px: pd.DataFrame, groups: dict, names=None, fit_end: pd.Timestamp = FIT_END,
           max_lag: int = DERIVE_MAX_LAG, window: int = WINDOW) -> dict:
    """Re-measure the two modelling choices on the fit era only (< 2023, H13): factor
    collinearity (whether to orthogonalise) and the Dimson lag count (THE RULE, the lead
    placebo; the superseded rules are printed after it as history). Prints the tables the
    module docstring quotes and returns them."""
    from scipy.stats import binom
    names = list(names or UNIVERSE)
    R, _, _ = returns_panel(px)
    R = R.loc[:fit_end]
    E = R[list(FACTOR_ETFS)].dropna()
    out = {}
    print(f"fit era {E.index.min().date()}..{E.index.max().date()}, {len(E)} sessions (all four ETFs)")
    corr = E.corr()
    vif = pd.Series(np.diag(np.linalg.inv(corr.to_numpy())), index=corr.index)
    print("\n1. COLLINEARITY, raw total returns, whole fit era\n" + corr.round(3).to_string())
    print("VIF " + ", ".join(f"{k} {v:.2f}" for k, v in vif.items())
          + f"; condition number {np.linalg.cond(corr.to_numpy()):.2f}")
    pairs = [("IEF", "MUB"), ("HYG", "BKLN"), ("IEF", "HYG"), ("MUB", "HYG"), ("MUB", "BKLN"), ("IEF", "BKLN")]
    rc = {}
    for a, b in pairs:
        s = E[a].rolling(window).corr(E[b]).dropna()
        rc[f"{a}-{b}"] = s.describe(percentiles=[0.05, 0.5, 0.95])[["min", "5%", "50%", "95%", "max"]]
    rc = pd.DataFrame(rc).T
    print(f"\nrolling {window}-session correlations\n" + rc.round(2).to_string())

    def _res(y, X):
        X1 = np.column_stack([np.ones(len(X)), X])
        b = np.linalg.lstsq(X1, y, rcond=None)[0]
        return y - X1[:, 1:] @ b[1:]
    rr, vifs, slopes, fvols = [], [], [], []
    for i in range(window, len(E) + 1, 21):
        w = E.iloc[i - window:i]
        I, M_, H, B = (w[c].to_numpy() for c in ("IEF", "MUB", "HYG", "BKLN"))
        Mi, Hi, Bi = _res(M_, I[:, None]), _res(H, I[:, None]), _res(B, I[:, None])
        rr.append({"MUB|IEF vs HYG|IEF": np.corrcoef(Mi, Hi)[0, 1],
                   "BKLN|IEF vs HYG|IEF": np.corrcoef(Bi, Hi)[0, 1]})
        vifs.append(np.diag(np.linalg.inv(np.corrcoef(w.to_numpy().T))))
        slopes.append(np.polyfit(I, M_, 1)[0])
        Fw = w @ orthogonaliser(w)
        fvols.append((Fw.std() * math.sqrt(ANNUALISE)).to_numpy())
    rr = pd.DataFrame(rr).describe(percentiles=[0.05, 0.5, 0.95]).T[["min", "5%", "50%", "95%", "max"]]
    print("\nresidual correlations after netting IEF only (windows every 21 sessions)\n" + rr.round(2).to_string())
    v = np.array(vifs)
    print("rolling VIF median " + ", ".join(f"{k} {x:.2f}" for k, x in zip(E.columns, np.median(v, 0)))
          + "; max " + ", ".join(f"{k} {x:.2f}" for k, x in zip(E.columns, v.max(0))))
    print(f"window OLS slope of MUB on IEF: median {np.median(slopes):+.2f} (a fixed MUB - IEF assumes 1)")
    fv = np.array(fvols)
    print("orthogonal factor vol on the windows, annualised, median [min, max]: "
          + ", ".join(f"{k} {np.median(fv[:, j]):.3f} [{fv[:, j].min():.3f}, {fv[:, j].max():.3f}]"
                      for j, k in enumerate(FACTOR_NAMES)))
    out.update(corr=corr, vif=vif, rolling=rc, resid=rr)

    # 2. THE RULE (module docstring): the lead-placebo lag rule, adopted 2026-11-03. The
    # counts are printed before the decision, so a raise still leaves the table on screen.
    npairs = len(names) * len(FACTOR_NAMES)
    pc = lead_placebo_counts(R, names, fit_end=fit_end, max_lag=max_lag)
    print(f"\n2. DIMSON LAGS, THE RULE (adopted; module docstring): one OLS per name, lags 0..{max_lag} "
          f"and leads 1..{DERIVE_RULE_LEADS}, HAC({DERIVE_RULE_HAC}); pairs (of {pc['n_pairs']}) with "
          f"p < {DERIVE_RULE_ALPHA}")
    print(f"   sample {pc['first'].date()}..{pc['last'].date()} (last response row; its lead-"
          f"{DERIVE_RULE_LEADS} row is on or before {pd.Timestamp(fit_end).date()}), sessions per name "
          f"{min(pc['nobs'].values())}..{max(pc['nobs'].values())}")
    print("   lag counts  c(l): " + _fmt_counts(pc["lag"]))
    print("   lead counts p(j): " + _fmt_counts(pc["lead"], "m"))
    rule = placebo_lag_rule(pc["lag"], pc["lead"])
    at = [j for j, c in pc["lead"].items() if c == rule["T"]]
    print(f"   T = max lead count = {rule['T']} (at lead {at}); first lag not above T: {rule['stop_lag']} "
          f"(count {pc['lag'][rule['stop_lag']]}); so L = {rule['L']}")
    print(f"   module constant DIMSON_LAGS = {DIMSON_LAGS}: "
          + ("equals the rule's L" if DIMSON_LAGS == rule["L"] else
             f"DIFFERS from the rule's L = {rule['L']}; set it from the rule in a commit of its own"))
    L = rule["L"]

    # 3. SUPERSEDED (2026-11-02; history). Every rule the build session tried, at both lag
    # bounds, and the review's 5-lead placebo, kept so the docstring's review figures stay
    # reproducible. Nothing is chosen from them.
    M = orthogonaliser(E)
    F = E @ M
    F.columns = list(FACTOR_NAMES)
    models = {K: {n: _dimson_ols(R[n], F, K) for n in names} for K in sorted({DERIVE_ALT_MAX_LAG, max_lag})}
    bound = int(binom.ppf(0.95, npairs, 0.05))
    rules = {K: lag_rule_counts(ms, alpha=0.05) for K, ms in models.items()}
    sig = rules[max_lag]["single"]
    cum = {}
    for n in names:
        m = models[max_lag][n]
        for k in FACTOR_NAMES:
            cum[(n, groups.get(n, "?"), k)] = np.cumsum([m.params[f"{k}_{l}"] for l in range(max_lag + 1)])
    L_old = _first_gap(sig, bound)
    print(f"\n3. SUPERSEDED (2026-11-02; history, nothing is chosen here). Lags-only models, lags "
          f"0..{max_lag}, HAC(5): pairs (of {npairs}) with the lag-l coefficient significant at 5%")
    print("   " + ", ".join(f"l{l} {c}" for l, c in sig.items()) + f"; Binomial({npairs}, 0.05) 95% point {bound}")
    print(f"   the superseded first-gap rule's L = {L_old}")
    maj = len(names) // 2 + 1
    print("\n   the four lag rules tried on 2026-11-02, at both lag bounds K (superseded):")
    tab = []
    for K, c in rules.items():
        tab.append(dict(K=K, rule=f"joint Wald test of lag l, a majority ({maj} of {len(names)}) of names",
                        counts=_fmt_counts(c["joint"]), L=_first_gap(c["joint"], maj - 1)))
        tab.append(dict(K=K, rule=f"sum of lags L+1..K, pairs significant <= {bound}",
                        counts=_fmt_counts(c["tail"], "L"), L=_smallest_within(c["tail"], bound)))
        tab.append(dict(K=K, rule=f"single-lag first gap, pairs significant <= {bound}"
                                  + (" (adopted until 2026-11-03)" if K == max_lag else ""),
                        counts=_fmt_counts(c["single"]), L=_first_gap(c["single"], bound)))
    tab = pd.DataFrame(tab)
    with pd.option_context("display.width", 250, "display.max_colwidth", 120):
        print(tab.to_string(index=False))
    lead = {j: 0 for j in range(1, DERIVE_PLACEBO_LEADS + 1)}
    for n in names:
        m = _dimson_ols(R[n], F, max_lag, leads=DERIVE_PLACEBO_LEADS)
        for k in FACTOR_NAMES:
            for j in lead:
                lead[j] += int(m.pvalues[f"{k}_m{j}"] < 0.05)
    over = sum(c > bound for c in lead.values())
    print(f"\n   the review's placebo: pairs (of {npairs}) with a LEAD coefficient significant at 5%, "
          f"lags 0..{max_lag} and leads 1..{DERIVE_PLACEBO_LEADS}: "
          + ", ".join(f"lead{j} {c}" for j, c in lead.items())
          + f"; {over} of {len(lead)} leads exceed the Binomial bound {bound}")
    span = range(0, max(sig[l] for l in range(1, max_lag + 1)) + 2)
    print("   the superseded rule's L as a function of the bound: "
          + _fmt_runs({b: _first_gap(sig, b) for b in span}))

    # 4. The plateau check, beside the rule; nothing is chosen from it.
    cm = pd.DataFrame(cum).T
    cm.index.names = ["name", "grp", "factor"]
    cm.columns = [f"L{l}" for l in range(max_lag + 1)]
    med = cm.groupby(level=["grp", "factor"]).median()
    print(f"\n4. PLATEAU CHECK (nothing is chosen from it): median cumulative summed beta by group and "
          f"factor, from the lags-only 0..{max_lag} models\n" + med.round(2).to_string())
    near = [f"L{l}" for l in (L - 1, L, L + 1) if 0 <= l <= max_lag]
    if ("muni", "MUNI") in med.index:
        print(f"   muni names' MUNI beta at the rule's L - 1, L, L + 1: "
              + ", ".join(f"{c} {med.at[('muni', 'MUNI'), c]:.2f}" for c in near))
    out.update(sig=sig, bound=bound, L=L, L_superseded=L_old, placebo_counts=pc, rule=rule, cum=cm,
               rules=rules, rule_table=tab, placebo=lead)
    return out


def _dimson_ols(y: pd.Series, F: pd.DataFrame, max_lag: int, leads: int = 0):
    """OLS of y on F at lags 0..max_lag (and, for the placebo only, leads 1..leads), HAC(5)."""
    import statsmodels.api as sm
    cols = {f"{k}_{l}": F[k].shift(l) for k in F.columns for l in range(max_lag + 1)}
    cols.update({f"{k}_m{j}": F[k].shift(-j) for k in F.columns for j in range(1, leads + 1)})
    X = pd.concat(cols, axis=1)
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    return sm.OLS(d["y"], sm.add_constant(d.drop(columns="y"))).fit(
        cov_type="HAC", cov_kwds={"maxlags": DERIVE_RULE_HAC})


# --------------------------------------------------------------------------- the lag rule

class LagRuleError(ReadoutError):
    """The lead-placebo lag rule cannot place L (module docstring, THE RULE): lag 0 fails
    the placebo, every lag clears it (L censored at K), or its inputs are malformed."""


def lead_placebo_counts(R: pd.DataFrame, names, fit_end: pd.Timestamp = FIT_END,
                        max_lag: int = DERIVE_MAX_LAG, leads: int = DERIVE_RULE_LEADS,
                        alpha: float = DERIVE_RULE_ALPHA) -> dict:
    """The counts THE RULE decides on (module docstring): one OLS per name on the four
    orthogonal factors at lags 0..max_lag AND leads 1..leads, HAC; c(l) and p(j) are the
    (name, factor) pairs whose lag-l / lead-j coefficient has a two-sided p < alpha.

    H13: R is cut at fit_end BEFORE any shift, so a lead can never reach a 2023 return; the
    cut is then checked explicitly on every name's sample (an explicit raise, not an assert):
    its last response row must sit `leads` sessions before the last factor row, and that row
    must be on or before fit_end. The factors are orthogonalised once on the whole cut era,
    as `derive` always has. Returns dict(lag, lead, n_pairs, nobs, first, last)."""
    names = list(names)
    if not names:
        raise LagRuleError("lead_placebo_counts: no names")
    miss = [c for c in (*FACTOR_ETFS, *names) if c not in R.columns]
    if miss:
        raise LagRuleError(f"lead_placebo_counts: not in the returns panel: {miss}")
    fit_end = pd.Timestamp(fit_end)
    Rc = R.loc[:fit_end]                       # H13: cut first, shift afterwards
    E = Rc[list(FACTOR_ETFS)].dropna()
    if len(E) == 0:
        raise LagRuleError(f"lead_placebo_counts: no factor rows on or before {fit_end.date()}")
    if E.index.max() > fit_end:
        raise LookaheadError(f"lead_placebo_counts: factor rows reach {E.index.max().date()}, "
                             f"after the fit era's end {fit_end.date()} (H13)")
    M = orthogonaliser(E)
    F = E @ M
    F.columns = list(FACTOR_NAMES)
    lag = {l: 0 for l in range(max_lag + 1)}
    lead = {j: 0 for j in range(1, leads + 1)}
    nobs, first, last = {}, [], []
    for n in names:
        m = _dimson_ols(Rc[n], F, max_lag, leads=leads)
        rows = pd.DatetimeIndex(m.model.data.row_labels)
        k_reg = len(m.params)
        if len(rows) <= k_reg:
            raise LagRuleError(f"lead_placebo_counts: {n} has {len(rows)} sessions for {k_reg} regressors")
        pos_last = int(F.index.get_loc(rows.max()))
        if rows.max() > fit_end or pos_last + leads > len(F) - 1 or F.index[pos_last + leads] > fit_end:
            raise LookaheadError(f"lead_placebo_counts: {n}'s sample ends {rows.max().date()} and its "
                                 f"lead-{leads} row passes {fit_end.date()} (H13)")
        nobs[n], first, last = len(rows), first + [rows.min()], last + [rows.max()]
        for k in FACTOR_NAMES:
            for l in lag:
                lag[l] += int(m.pvalues[f"{k}_{l}"] < alpha)
            for j in lead:
                lead[j] += int(m.pvalues[f"{k}_m{j}"] < alpha)
    return dict(lag=lag, lead=lead, n_pairs=len(names) * len(FACTOR_NAMES), nobs=nobs,
                first=min(first), last=max(last))


def placebo_lag_rule(lag_counts: dict, lead_counts: dict) -> dict:
    """THE RULE's decision (module docstring), on counts already made. T = the largest lead
    count. Lag 0 must exceed T, or this raises. Lags 1, 2, ... are included in order while
    their count exceeds T STRICTLY; a tie stops the sequence; a lag after the first that
    fails is never included. Every lag 1..K clearing T raises (L censored at K). Returns
    dict(L, T, stop_lag): stop_lag is the first lag not included."""
    if not lead_counts:
        raise LagRuleError("placebo_lag_rule: no lead counts, so no placebo bound")
    lags = sorted(lag_counts)
    if lags != list(range(len(lags))) or len(lags) < 2:
        raise LagRuleError(f"placebo_lag_rule: lag counts must cover 0..K with K >= 1, got lags {lags}")
    T = max(lead_counts.values())
    if not lag_counts[0] > T:
        raise LagRuleError(f"placebo_lag_rule: lag 0 count {lag_counts[0]} does not exceed the largest "
                           f"lead count {T}; the factors explain the funds no better than their future "
                           "returns, and no L is meaningful")
    for l in lags[1:]:
        if not lag_counts[l] > T:
            return dict(L=l - 1, T=T, stop_lag=l)
    raise LagRuleError(f"placebo_lag_rule: every lag 1..{lags[-1]} exceeds the largest lead count {T}: "
                       f"L is censored at K = {lags[-1]}. Widen K only under a new rule declared first; "
                       "K is not the answer")


def lag_rule_counts(models: dict, alpha: float = 0.05) -> dict:
    """The counts behind the four lag rules, from per-name fits at lags 0..K:
    single[l]: (name, factor) pairs whose lag-l coefficient is significant;
    joint[l]:  names whose four lag-l coefficients are jointly significant (Wald);
    tail[L]:   pairs whose sum of the lag L+1..K coefficients is significant (L < K)."""
    any_m = next(iter(models.values()))
    K = max(int(c.rsplit("_", 1)[1]) for c in any_m.params.index if c != "const" and "_m" not in c)
    single = {l: 0 for l in range(K + 1)}
    joint = {l: 0 for l in range(K + 1)}
    tail = {L: 0 for L in range(K)}
    for m in models.values():
        idx = list(m.params.index)
        for l in range(K + 1):
            Rm = np.zeros((len(FACTOR_NAMES), len(idx)))
            for j, k in enumerate(FACTOR_NAMES):
                Rm[j, idx.index(f"{k}_{l}")] = 1.0
                single[l] += int(m.pvalues[f"{k}_{l}"] < alpha)
            joint[l] += int(float(m.wald_test(Rm, scalar=True).pvalue) < alpha)
        for k in FACTOR_NAMES:
            for L in range(K):
                r = np.zeros(len(idx))
                for l in range(L + 1, K + 1):
                    r[idx.index(f"{k}_{l}")] = 1.0
                tail[L] += int(float(m.t_test(r).pvalue) < alpha)
    return dict(single=single, joint=joint, tail=tail)


def _first_gap(counts: dict, bound: int):
    """The last lag before the first lag l >= 1 whose count is within the bound (<= bound).
    None if no lag is. For the majority rule the bound is (majority - 1)."""
    for l in sorted(counts):
        if l >= 1 and counts[l] <= bound:
            return l - 1
    return None


def _smallest_within(counts: dict, bound: int):
    """The smallest L whose count is within the bound. None if none is."""
    return next((L for L in sorted(counts) if counts[L] <= bound), None)


def _fmt_counts(c: dict, p: str = "l") -> str:
    return " ".join(f"{p}{k}:{v}" for k, v in c.items())


def _fmt_runs(m: dict) -> str:
    """{bound: L} as runs, e.g. 'bound 2-6 -> L 3; 7-9 -> L 2'. The last run holds for every
    larger bound too."""
    out, keys, i = [], sorted(m), 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and m[keys[j + 1]] == m[keys[i]]:
            j += 1
        last = j == len(keys) - 1
        out.append(f"{keys[i]}{'+' if last else ('' if i == j else '-' + str(keys[j]))} -> L {m[keys[i]]}")
        i = j + 1
    return "bound " + "; ".join(out)


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--asof", required=True)
    f.add_argument("--start", default=FETCH_START.isoformat())
    f.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    f.add_argument("--symbols", nargs="*", default=[])
    c = sub.add_parser("crosscheck")
    c.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    d = sub.add_parser("derive")
    d.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    a = sub.add_parser("analyse")
    a.add_argument("--positions", required=True)
    a.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    a.add_argument("--out-dir", default=None)
    a.add_argument("--plateau", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "fetch":
        asof = dt.date.fromisoformat(args.asof)
        check_asof(asof)
        cache = Path(args.cache_dir)
        _refuse_write(cache, CACHE_FILES)            # before any network call
        tickers = sorted(set(FACTOR_ETFS) | set(UNIVERSE) | {s.upper() for s in args.symbols})
        px, cg = fetch_yf(tickers, dt.date.fromisoformat(args.start), asof)
        validate_prices(px, asof)
        import yfinance
        meta = {"asof": asof.isoformat(), "start": args.start, "tickers": tickers,
                "source": "yfinance Ticker.history(auto_adjust=False, actions=True), keyless",
                "yfinance_version": yfinance.__version__, "capital_gains_column": cg,
                "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        write_cache(cache, px, meta)
        print(f"wrote {len(px)} rows, {len(tickers)} tickers, asof {asof}, into {cache}")
        tab, notes = crosscheck(px)
        _print_crosscheck(tab, notes)
        return 0
    px, meta = load_cache(Path(args.cache_dir))
    if args.cmd == "crosscheck":
        tab, notes = crosscheck(px)
        _print_crosscheck(tab, notes)
        return 0
    if args.cmd == "derive":
        derive(px, load_groups())
        return 0
    P = read_positions(Path(args.positions))
    groups = load_groups()
    ro = readout(px, P, groups)
    plateau = plateau_check(px, P, groups, ro) if args.plateau else None
    out = Path(args.out_dir) if args.out_dir else DEFAULT_OUT / P["date"].max().date().isoformat()
    write_outputs(out, ro, meta, plateau)
    print((out / "summary.md").read_text())
    print(f"outputs in {out}")
    return 0


def _print_crosscheck(tab: pd.DataFrame, notes: list) -> None:
    print("\nCROSS-CHECK against the repo panels (read-only; reports, decides nothing)")
    for n in notes:
        print("  " + n)
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(tab.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
