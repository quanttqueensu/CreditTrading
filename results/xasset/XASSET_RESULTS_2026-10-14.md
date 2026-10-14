# XASSET slate — run record, 2026-10-14: stopped before Stage 0b on two questions

**Pre-registration** `results/xasset/PREREG_XASSET_SLATE_2026-10-12.md`,
revision 3, approved 2026-10-14 with X5 withdrawn: N = 4, slate bar
√(2 ln 4) = 1.665, pass = `validate._dsr` > 0.95 at N = 4 · **Branch**
`trial-xasset` (from main `9d1d9ab`) · **Counter** XASSET **0**: no test
entered Stage 0b.

**Reproduce:** Stage 0a by the five commands in
`results/xasset/STAGE0A_2026-10-14.md`; the trial code's behaviour by
`python3 -m pytest -q scripts/xasset/tests scripts/cef/tests/test_xasset_helpers.py`
(synthetic returns only). Once the questions below are answered, each test runs
as `python3 scripts/xasset/x<k>_*.py --trial N`, after the commit that moves
the counter to N.

## Outcome

**No test has a verdict.** No return was combined into a P&L, no Sharpe of any
X-test was computed, and **XASSET stays 0**.

| test | status | what stops it | trials spent |
|---|---|---|---:|
| X1 credit and rates trend | **STOPPED before Stage 0b** | question 1 (DG1) and question 2 (the preflight halts on it) | 0 |
| X2 rebalancing front-run | **STOPPED before Stage 0b** | question 1 (DG1) | 0 |
| X3 month-end Treasury | **STOPPED before Stage 0b** | question 1 (DG1) | 0 |
| X4 multi-asset trend | **STOPPED before Stage 0b** | question 1 (DG1) and question 2 (the preflight halts on it) | 0 |

- **STOPPED is not UNRUN.** UNRUN is a verdict: the gate cannot clear, and
  the test closes with no trial spent. STOPPED means the run's rule 5 applied:
  the pre-registration is "impossible as written" at one point, so it waits
  for the team lead.
- **No holdout was opened.** The 2023-01-01 time holdout stays sealed.

## The questions for the team lead

**1. Does DG1 clear?** (It blocks all four tests.)

- **What DG1 asks.** "All 13 tickers already built … rebuild unchanged in
  every existing column (`scripts/rv/panel_identity.py`)".
- **What was measured** (`results/xasset/STAGE0A_2026-10-14.md` §2):
  - against `data/etf_daily.parquet`, every column is byte-identical through
    2026-10-09, except `ret_total` in the yfinance leg (2025-01-02 →
    2026-07-20): 3,210 of 5,018 cells, max 0.0074bp;
  - two fresh builds minutes apart differ in the same way (6,112 cells, max
    0.0075bp, nothing else).
- **Why no rebuild can meet it.** That leg's return is Yahoo Adj Close
  `pct_change`. Yahoo re-bases Adj Close, and REFERENCES §8 has recorded since
  2026-10-11 that such a series "can[not] be reproduced bitwise, by any
  fetcher".
- **What the difference touches.** It lies wholly inside the holdout, and it
  is four orders of magnitude below the build's 5bp gate. The fit stages read
  only the CRSP leg, which is identical.
- **The options, none taken here:**
  - (a) DG1 clears on the measured result;
  - (b) DG1 is re-specified, for example with a tolerance, or by switching the
    yfinance leg to the in-house total return, which REFERENCES §8 notes would
    change 2025–26 history;
  - (c) the tests are UNRUN.
- **If (a),** the staged panel already pinned in
  `STAGE0A_MANIFEST_2026-10-14.json` (SHA-256 `b843f558…`) is the one the
  trials read, and no rebuild is needed.

**2. In X1's and X4's placebo, what does a position earn on a date before its
fund existed?** (It decides stage 3 of X1 and X4. It does not affect X2 or X3,
whose instruments trade throughout.)

- **What §1.8 says.** "The rows of the sized H are permuted in contiguous
  21-session blocks while returns stay fixed." It says nothing about a row
  that lands on a date before one of its funds existed.
- **Why it arises.** X1's later rows hold BKLN (first return 2011-03-04) and
  CWB (2009-04-17). X4's hold up to seven funds that start after its first
  decision (2005-11-30). Almost every draw moves such rows onto dates when
  those funds had no return.
- **What the code does now.** It refuses: `protocol.run` raises, naming the
  name-dates. It does not score them 0 silently (test
  `test_x1_placebo_refuses_to_score_a_fund_before_it_existed`).
- **The options, none taken here:**
  - (a) the harness's own convention: such a position earns 0
    (`build_targets` fills a missing return with 0, and `evaluate`'s row sum
    skips NaN);
  - (b) shuffle only inside the span where every one of the sleeve's funds
    trades;
  - (c) another rule.
- **Why it must be answered first.** If the run went ahead and stopped here,
  the trial would already be spent. The answer is needed **before** X1 or X4
  enters Stage 0b.

**3. Confirm three readings that touch the decision series.** The code takes
the pre-registration's words literally in each. An independent review of the
trial code (2026-10-14) listed them as choices the text does not spell out.
Each is small; none was chosen by looking at a return.

- **(a) MUB counts in S_t when its signal is short (X1, X4).**
  - What §4 says: "1/S_t over eligible names"; MUB is "long-or-flat".
  - The reading: MUB is eligible (12 months of returns), so it is in S_t;
    only its position is set to 0.
- **(b) The ex-ante variance is pandas `ewm(com=60, adjust=True).var()` with
  its default bias correction.**
  - What §4 says: "`ewm(com=60, adjust=True)` mean and variance".
  - MOP's eq. 1 is the uncorrected weighted variance. The difference is a
    near-uniform scale, which P5's k removes.
- **(c) Turnover is `evaluate()`'s, Σ|ΔH| on the rows inside the P&L window.**
  - The first decision's entry trade is therefore not charged, and the trades
    decided on 2022-12-29 and 2022-12-30 are.
  - It touches X1/X4's stage 2 net comparison and stage 8's net Sharpe,
    negligibly.

Unless the team lead says otherwise with the answers to questions 1 and 2,
these readings stand as written.

## The zero-trial preflight (run 2026-10-14; dates and coverage only, no P&L)

`python3 scripts/xasset/x<k>_*.py --preflight` checks four things without
building a position or a P&L:

- the pins and the input hashes;
- the declared first decision, re-derived from the breadth rule on the panel's
  first returns, and the declared T;
- each D4 factor's coverage of its regression window, from its components'
  missing-value masks, and the French and AQR coverage;
- whether the placebo would move a position onto a date with no return.

| test | preflight |
|---|---|
| X1 | **halts: question 2** (BKLN and CWB start after the first P&L, 2008-05-02) |
| X2 | passes: first decision 2002-08-30, T 5,118; BIL's first return 2007-05-31; control window 3,926 sessions |
| X3 | passes: first decision 2002-08-30, T 5,118 |
| X4 | **halts: question 2** (HYG, EMB, PFF, MUB, BKLN, CWB and DBC start after the first P&L, 2005-12-02) |

`fit()` also refuses Stage 0b while DG1 is unruled (`protocol.DG1_RULING is
None`). It refuses a test that already has a fit verdict, and it writes stages
0b–5 before any reported row.

## The pre-run review (quant-reviewer, 2026-10-14)

An independent review of the trial code, run before any return was used,
found no critical defect.

- **Its one high finding was the TSMOM silent short below.** It had already
  been fixed during the review.
- **Its medium findings are fixed:**
  - the breadth rule is now checked against the data;
  - every halt that depends only on dates or missing data runs before Stage
    0b (the preflight);
  - the decision stages are written before the reported rows;
  - a completed test cannot be rerun.
- **So are its low ones:**
  - the holdout guard requires the verdict files in the committed tree;
  - `run()` refuses a NaN position;
  - capacity counts rebalance days that lack dollar-volume history instead of
    skipping them;
  - X2's X3-dependent rows are computed by whichever of the two runs second;
  - X4 has a synthetic pipeline test.
- **It confirmed the declared mappings:**
  - r_f alignment;
  - TSMOM, TSH and MUB;
  - X2's state and signal, its exposure rows and its control;
  - X3's rows and their complement;
  - sizing;
  - the factors;
  - `_dsr`'s inputs;
  - the placebo seed, draws and rule;
  - the verdict order;
  - the holdout's bit-exact fit-row check.

## What is ready, so a ruling translates directly into a run

- **Stage 0a is committed** (`STAGE0A_2026-10-14.md` and its manifest):
  - the spec pin matches;
  - DG1's build gates, DG2, DG3 and Q1 pass;
  - no repair was needed.
- **The trial code is written and tested on synthetic returns:**
  - one script per test, `scripts/xasset/x1_credit_trend.py`,
    `x2_rebalancing.py`, `x3_month_end.py` and `x4_multi_trend.py`;
  - the shared order of evaluation, `scripts/xasset/runner.py`;
  - the MOP rule, `scripts/xasset/tsmom.py`;
  - the protocol, `scripts/xasset/protocol.py`.
- **Each script refuses to start Stage 0b** unless:
  - the spec still matches its pins;
  - every Stage 0a input re-hashes to the manifest;
  - the committed counter table already shows its trial number;
  - the panel gives the declared first decision and the declared T.
- **The declared windows were checked, zero-trial, on the staged calendar.**
  Each first decision and each T in Table A matches:

  | test | first decision | T |
  |---|---|---:|
  | X1 | 2008-04-30 | 3,693 |
  | X2, X3 | 2002-08-30 | 5,118 |
  | X4 | 2005-11-30 | 4,299 |

  Also matching: the BIL control window (3,926 sessions), HYG's first return
  (2007-04-12), IEF's (2002-07-29), and the holdout (939 sessions, ending
  2026-09-30, a month-end).
- **Planned order:** X1, X3, X2, X4, so that X2's reported week4-on-X3
  regression has X3's series (§1.12). The counter moves 0 → 1 → 2 → 3 → 4,
  one commit before each test's Stage 0b.

## Corrected before any run (no trial was affected)

- **`scripts/xasset/tsmom.py`: a silent short.** The 12-month return was
  `logc[E] − logc[start]` with `logc = log1p(r).cumsum()`, which is NaN before
  a fund's first return.
  - **Where it bites.** A fund whose first return is exactly the first
    session of its window is eligible at that month-end. PFF qualifies: its
    first return, 2007-04-02, is the first session of April 2007, so it
    becomes eligible in X4 at 2008-03-31.
  - **What it would have done.** The 12-month return would have been NaN.
    `NaN >= 0` is False, so PFF would have been shorted with no data behind
    the sign.
  - **The fix.** `cum_log` returns 0 before the first return (nothing has
    accrued) and raises on a gap inside the live range. Any non-finite return
    now raises.
  - **The test.**
    `test_tsmom_name_starting_on_its_windows_first_session_is_not_shorted`
    fails against the old code.

## Readings the code applies to REPORTED rows only (never deciding; [U])

These sit where the pre-registration names a reported statistic without fixing
every detail. None reaches a decision, and each is labelled in its output.

| row | reading |
|---|---|
| Q2 stale price | "3 consecutive sessions with an unchanged close" = three or more sessions sharing one close |
| R-AQR | calendar months wholly inside the P&L window only (W4's convention) |
| refresh offsets (X1, X4) | a daily TSMOM target with the 12-month window (s, t], s = the last session on or before t minus 12 months; then `calendar_offset(·, 21, o)` for o = 0..20 |
| leave-one-out (X1, X4) | the same first decision and window; 1/S_t over the remaining eligible names |
| asset-class rows (X4) | credit and rates = X1's nine; equity = SPY EFA EEM; commodity = GLD DBC; each class's contribution to the sized sleeve |
| X2 mid-month placebo | the week4 rule moved to sessions 6–10 in paper time (H rows 5–9), no Calendar₋₄ analogue |
| X2 sign permutations | month blocks of Calendar-part rows (E−5 … E) reassigned across months |
| capacity | the median, across rebalance days, of the largest name's \|ΔH\| / 63-session median dollar volume |
| in-house source row (X2) | its portfolios start at the close before the in-house panel's first common SPY/IEF return |
