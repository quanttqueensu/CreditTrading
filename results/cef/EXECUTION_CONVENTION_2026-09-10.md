# The execution convention — measured 2026-09-10 evening

**What this file is.** The stored record of the run that corrected
`scripts/cef/validate.py` from `shift(1)` to `shift(2)`, with all three
measurements verbatim. Written because **this battery had never stored a
single one of its own results.** `validate.py` prints sections 1–4 to stdout
and writes only `cef_validated_daily.parquet`; every walk-forward, bootstrap
and deflated-Sharpe figure ever quoted in this repo existed solely as prose
transcribed by hand into a document. That is how "9/9 blocks positive"
survived in five files for six weeks after it stopped reproducing.

**Panel:** `data/cef/cef_prices.parquet` + `cef_nav.parquet`, raw universe 44
CEFs, 1998-10-29 → **2026-09-09** (T = 5,455 scored sessions). Not refreshed on
2026-09-10 — there is no `ops/schedule/logs/cef_2026-09-10.log`.

**Reproduce:** `python3 scripts/cef/validate.py --trials 48`, in **dev**.
Prod (`~/prod/QUANTT`, detached at `v2026.09.10.1`) predates both fixes.

---

## The defect

`validate.py` scored `held = W.shift(1)` — entering at day *t*'s close using day
*t*'s NAV, which the fund publishes **after** that close. The entry price did not
exist. Every other number in this repo is scored `shift(2)`
(`band_frontier.py::evaluate`, `H.shift(2)`), so the headline validation was not
comparable to anything it was printed beside.

**It was diagnosed on 2026-07-31 and not fixed.** `docs/RESEARCH_STATE.md` named
the line and predicted the cost. Six weeks later the line was still there, having
survived a 2026-09-10 14:37 commit that edited the same file for another reason.

| | predicted 2026-07-31 | measured 2026-09-10 |
|---|---|---|
| gross Sharpe | 1.26 → 0.95 | 1.27 → **0.94** |
| net Sharpe (hold=5) | 0.82 → 0.51 | 0.83 → **0.51** |

A second defect in the same section: the header printed `"10 blocks, 5d embargo
either side"` over a bare `np.array_split` whose blocks touched. **The embargo was
announced, never applied.**

## The three runs

| run | config | gross | net | walk-forward | P(SR≤0) | DSR @48 |
|---|---|---|---|---|---|---|
| **A** | `shift(1)`, no embargo — as it stood at 14:37 | 1.27 | 0.83 | 8/9, med 1.05, worst −0.15 | 0.000% | 0.870 FAIL |
| **B** | `shift(2)`, no embargo | 0.94 | 0.51 | 7/9, med 0.62, worst −0.45 | 0.300% | 0.333 FAIL |
| **C** | `shift(2)` + embargo applied — **current** | 0.94 | 0.51 | 7/9, med 0.63, worst −0.45 | 0.300% | 0.333 FAIL |

A→B isolates the lookahead; B→C isolates the embargo. The embargo does not move
sections 1 or 3 (it only touches the block split), which is the expected signature
and worth checking on any future edit.

**The trial count is moot.** DSR is FAIL at every count — 0.588 at N=10, 0.333 at
48, 0.330 at 49, 0.197 at 162. The 14:37 finding (verdict flips PASS→FAIL between
N=10 and N=48) is overtaken. Observed Sharpe **0.51 is below the best-of-48 null of
0.60**. Counter stays at **48**: a lookahead fix re-measures an existing trial
rather than adding a specification.

## What this measures — and what it does not

`validate.py` scores a **5-day-hold calendar** sleeve (`HOLD = 5`), **retired
2026-09-06**. It is *not* the live book.

The deployed policy is **band 4.8%**, measured by the correct harness
(`band_frontier.py`, `shift(2)`) on the same panel the same day: **gross 1.17,
net@15bp 0.67, turn 17.6×/yr, hold 12.6d**. That output is stored beside this file
as `band_frontier_2026-09-10_control.txt` and was verified **byte-identical before
and after** the `validate.py` change — the two scripts share no code, so any
movement there would have meant the edit leaked.

> **The band has never been walk-forwarded, bootstrapped or deflated.**
> Every figure in the table above belongs to a policy we no longer trade.
> Pointing this battery at the band is the open work.

Two sealed holdouts remain unopened and would be the real out-of-sample test: the
**2023-01-01 time holdout** (H13 — its helper `scripts/cef/holdout.py` does not
exist) and the **27 untouched CEFs** (no `results/cef/HOLDOUT27_*.md`). The 2024+
holdout was opened 2026-07-31 and is **spent**; its verdict was **FAIL**
(`HOLDOUT_OPENED.json`: `net_sharpe -0.298`, `cost_pct_of_gross 117.2`) — do not
cite its gross 1.75 as out-of-sample support.

## Guards added, because a comment was not enough last time

- `EXEC_LAG = 2` — one constant, used in both places, asserted at runtime by
  `_assert_exec_lag()`. It is not a tuning knob and the guard refuses any other value.
- `scripts/cef/tests/test_execution_convention.py` — plants a signal that only a
  `shift(1)` book could monetise and fails if it is captured. Verified by
  *simulating the regression* (`EXEC_LAG=1`, constant guard defeated): 4 of 5 tests
  fail, including the behavioural one.
- **Not** `src/backtest/guard.py::assert_lagged`. That encodes the Phase-2 T+1 rule
  (`info_dates[t] <= t`), which `shift(1)` satisfies — it would have printed a green
  check over the exact bug it was meant to catch.
- The DSR footer's N-sensitivity is now **computed**. It previously carried
  `"at N=10 ... 0.963 PASS, at N=48 ... 0.870 FAIL"` as literal text, which stopped
  describing the series the moment the convention changed. A stale number in a fresh
  run's output wears more authority than one in a document.

---

## Verbatim output

### Run A — `shift(1)`, no embargo (the state at 14:37)

```
raw universe 44 CEFs, 1998-10-29 -> 2026-09-09

====================================================================================
1. POINT-IN-TIME UNIVERSE (no hindsight on survival or liquidity)
====================================================================================
  eligible funds per day: min 1  median 8  max 25
  gross Sharpe 1.27   net Sharpe 0.83   vol 6.01%
  CAGR 4.94%   maxDD -12.0%
  by era:
    2005-2009: gross  0.23  net  0.11  universe  2.6 funds
    2010-2014: gross  1.56  net  1.25  universe  6.3 funds
    2015-2019: gross  1.05  net  0.54  universe  9.3 funds
    2020-2022: gross  2.67  net  1.99  universe 11.8 funds
    2023-2026: gross  0.98  net  0.40  universe 12.3 funds

====================================================================================
2. PURGED WALK-FORWARD (10 blocks, 5d embargo either side)
====================================================================================
  2007-03-07..2009-05-05       546    0.17  +
  2009-05-06..2011-07-05       546    1.52  +++++++++++++++
  2011-07-06..2013-09-05       546    0.78  +++++++
  2013-09-06..2015-11-04       546    1.05  ++++++++++
  2015-11-05..2018-01-04       545    1.26  ++++++++++++
  2018-01-05..2020-03-06       545   -0.15  -
  2020-03-09..2022-05-04       545    1.48  ++++++++++++++
  2022-05-05..2024-07-08       545    1.63  ++++++++++++++++
  2024-07-09..2026-09-09       545    0.43  ++++
  8/9 blocks positive, median 1.05, worst -0.15

====================================================================================
3. BLOCK BOOTSTRAP (5,000 draws, 21-day blocks)
====================================================================================
  observed net Sharpe   0.83
  bootstrap mean        0.82
  5th / 95th pct        0.52 / 1.11
  P(Sharpe <= 0)        0.000%

====================================================================================
4. DEFLATED SHARPE (haircut for 48 specs tried on this source)
====================================================================================
  observed Sharpe 0.83   null best-of-48 0.60   skew +1.78  kurt 40.9
  trials N = 48 (from --trials)   deflated-Sharpe bar sqrt(2 ln N) = 2.783
  DEFLATED SHARPE RATIO (prob the edge is real): 0.870   FAIL
  ^ this verdict is AT N=48. It is not a property of the edge alone -- at N=10 this same series reads 0.963 PASS, at N=48 it reads 0.870 FAIL. Quote N whenever you quote the verdict.

wrote /Users/simonjarvis/Desktop/2027/QUANTT/2027/results/cef/cef_validated_daily.parquet
```

### Run B — `shift(2)`, embargo not yet applied

```
raw universe 44 CEFs, 1998-10-29 -> 2026-09-09

====================================================================================
1. POINT-IN-TIME UNIVERSE (no hindsight on survival or liquidity)
====================================================================================
  eligible funds per day: min 1  median 8  max 25
  gross Sharpe 0.94   net Sharpe 0.51   vol 6.04%
  CAGR 2.93%   maxDD -14.3%
  by era:
    2005-2009: gross -0.18  net -0.30  universe  2.6 funds
    2010-2014: gross  1.26  net  0.96  universe  6.3 funds
    2015-2019: gross  0.89  net  0.39  universe  9.3 funds
    2020-2022: gross  1.74  net  1.07  universe 11.8 funds
    2023-2026: gross  0.83  net  0.26  universe 12.3 funds

====================================================================================
2. PURGED WALK-FORWARD (10 blocks, 5d embargo either side)
====================================================================================
  2007-03-07..2009-05-05       546   -0.45  ----
  2009-05-06..2011-07-05       546    1.10  +++++++++++
  2011-07-06..2013-09-05       546    0.59  +++++
  2013-09-06..2015-11-04       546    0.96  +++++++++
  2015-11-05..2018-01-04       545    0.62  ++++++
  2018-01-05..2020-03-06       545   -0.17  -
  2020-03-09..2022-05-04       545    0.75  +++++++
  2022-05-05..2024-07-08       545    1.09  ++++++++++
  2024-07-09..2026-09-09       545    0.26  ++
  7/9 blocks positive, median 0.62, worst -0.45

====================================================================================
3. BLOCK BOOTSTRAP (5,000 draws, 21-day blocks)
====================================================================================
  observed net Sharpe   0.51
  bootstrap mean        0.49
  5th / 95th pct        0.20 / 0.79
  P(Sharpe <= 0)        0.300%

====================================================================================
4. DEFLATED SHARPE (haircut for 48 specs tried on this source)
====================================================================================
  observed Sharpe 0.51   null best-of-48 0.60   skew +2.03  kurt 44.7
  trials N = 48 (from --trials)   deflated-Sharpe bar sqrt(2 ln N) = 2.783
  DEFLATED SHARPE RATIO (prob the edge is real): 0.333   FAIL
  ^ this verdict is AT N=48. It is not a property of the edge alone -- at N=10 this same series reads 0.963 PASS, at N=48 it reads 0.870 FAIL. Quote N whenever you quote the verdict.

wrote /Users/simonjarvis/Desktop/2027/QUANTT/2027/results/cef/cef_validated_daily.parquet
```

### Run C — `shift(2)` + embargo applied (current; reproduces on re-run)

```
raw universe 44 CEFs, 1998-10-29 -> 2026-09-09

====================================================================================
1. POINT-IN-TIME UNIVERSE (no hindsight on survival or liquidity)
====================================================================================
  eligible funds per day: min 1  median 8  max 25
  gross Sharpe 0.94   net Sharpe 0.51   vol 6.04%
  CAGR 2.93%   maxDD -14.3%
  by era:
    2005-2009: gross -0.18  net -0.30  universe  2.6 funds
    2010-2014: gross  1.26  net  0.96  universe  6.3 funds
    2015-2019: gross  0.89  net  0.39  universe  9.3 funds
    2020-2022: gross  1.74  net  1.07  universe 11.8 funds
    2023-2026: gross  0.83  net  0.26  universe 12.3 funds

====================================================================================
2. PURGED WALK-FORWARD (10 blocks, 5d embargo either side)
====================================================================================
  2007-03-14..2009-04-28       536   -0.45  ----
  2009-05-13..2011-06-27       536    1.11  +++++++++++
  2011-07-13..2013-08-28       536    0.55  +++++
  2013-09-13..2015-10-28       536    0.94  +++++++++
  2015-11-12..2017-12-27       535    0.63  ++++++
  2018-01-12..2020-02-28       535   -0.30  ---
  2020-03-16..2022-04-27       535    1.02  ++++++++++
  2022-05-12..2024-06-28       535    0.99  +++++++++
  2024-07-16..2026-09-09       540    0.34  +++
  7/9 blocks positive, median 0.63, worst -0.45

====================================================================================
3. BLOCK BOOTSTRAP (5,000 draws, 21-day blocks)
====================================================================================
  observed net Sharpe   0.51
  bootstrap mean        0.49
  5th / 95th pct        0.20 / 0.79
  P(Sharpe <= 0)        0.300%

====================================================================================
4. DEFLATED SHARPE (haircut for 48 specs tried on this source)
====================================================================================
  observed Sharpe 0.51   null best-of-48 0.60   skew +2.03  kurt 44.7
  ^ the observed Sharpe is BELOW the best-of-48 null. On this many trials a no-edge source is expected to throw up a 0.60; we measured 0.51.
  trials N = 48 (from --trials)   deflated-Sharpe bar sqrt(2 ln N) = 2.783
  DEFLATED SHARPE RATIO (prob the edge is real): 0.333   FAIL
  ^ this verdict is AT N=48. It is not a property of the edge alone. The same series at other counts:
      N=10    bar 2.146   DSR 0.588   FAIL
      N=48    bar 2.783   DSR 0.333   FAIL  <- as run
      N=49    bar 2.790   DSR 0.330   FAIL
      N=162   bar 3.190   DSR 0.197   FAIL
  Quote N whenever you quote the verdict.

wrote /Users/simonjarvis/Desktop/2027/QUANTT/2027/results/cef/cef_validated_daily.parquet
```
