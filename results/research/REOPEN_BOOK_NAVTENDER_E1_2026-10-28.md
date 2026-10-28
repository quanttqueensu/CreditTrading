# NAV tenders and E1, judged by what they add to the CEF book — fit period only, 2026-10-28

**Zero trials. No counter, spec or `docs/RESEARCH_STATE.md` edited. No holdout opened. It decides nothing.**
Branch `research-reopen-book`, cut from `desk-research-method` at db88b14.
**Reproducer:** `python3 -m scripts.research.reopen_book.reopen_book`, i.e. `scripts/research/reopen_book/reopen_book.py`
(about 20 s; writes `results/research/reopen_book/reopen_book_2026-10-28.json`). Tests:
`python3 -m pytest scripts/research/tests -q`.
It needs the worktrees `trial-events-navtender` (ac2c7ca) and `trial-events-e1` (6d8bdbf) with their
CRSP caches, and `data/` linked as in the other worktrees. Every figure below marked **[V]** comes
from that command's JSON. **[S]** marks a figure read from a trial's committed note or fit JSON.

## 0. The answer

The team lead's rule (`docs/SYSTEM.md` §5, 2026-10-27, "Admission by marginal contribution") has two
limbs. A sleeve that fails the standalone deflated Sharpe may join the **paper** book, labelled, if:
1. SR_sleeve > ρ·SR_book across ρ's range; and
2. the combined book's net is positive at 5, 15 and 30bp.

Both limbs are measured on fit-period dates the sleeve and the book share: 2013-06-25 to 2022-12-30,
T = 2,398 sessions. The book holds nothing before 2013-06-25.

| per sleeve [V] | NAV tenders (EVENTS 2) | E1, muni merger pair (EVENTS 1) |
|---|---|---|
| days active of 2,398 (median spell) | 1,680, 70.1% (60 sessions; 19 spells) | 1,492, 62.2% (120 sessions; 10 spells) |
| **1.** standalone gross Sharpe; net 5 / 15 / 30bp | **0.382**; 0.314 / 0.180 / **−0.022** | **0.273**; 0.238 / 0.168 / 0.063 |
| DSR at N = 6, sr_var = 1/T: desk bar `upper` (SR₀) · paper bar `gumbel` (SR₀) | 0.245 (0.614) · 0.453 (0.421): fails both | 0.146 (0.614) · 0.323 (0.421): fails both |
| sleeve mean, Newey–West t (auto lag; L 21) | 1.43; 1.57 | 1.14; 1.32 |
| **2.** ρ with the book, daily (point) | **+0.086** | **+0.021** |
| ρ's range (union of five intervals, §2.2) | **[−0.174, +0.195]** | **[−0.278, +0.086]** |
| break-even ρ = SR_sleeve / SR_book (gross) | 0.399 | 0.286 |
| **3.** marginal gain, gross: point / low end / high end | +0.299 / +0.548 / **+0.196** | +0.253 / +0.539 / **+0.191** |
| marginal gain at the high end, net 5 / 15 / 30bp | +0.149 / +0.055 / **−0.087** | +0.165 / +0.113 / +0.035 |
| **4.** combined gross Sharpe (book alone 0.955) | 0.959 | 0.965 |
| combined net 5 / 15 / 30bp (book alone 0.852 / 0.645 / 0.334) | 0.840 / 0.603 / 0.248 | 0.858 / 0.644 / 0.323 |
| combined held gross: mean · p95 · max · share of days above the 1.80× cap | 1.83 · 2.96 · 3.50 · **48.2%** | 1.98 · 3.26 · 3.60 · **50.1%** |
| **5.** reading (gross, the paper score) | **Meets the rule across ρ's range**, at gross, 5bp and 15bp. **Fails limb 1 at 30bp, even at the point estimate** | **Meets the rule across ρ's range**, at gross and at every cost on the grid |

In short:
- **ρ is not what binds.** Both break-even correlations sit above the upper end of every interval
  measured. The arithmetic's weak input is the sleeve's own Sharpe, whose Newey–West t is 1.43 and
  1.14 (§3.1).
- **What the rule does not test binds more.** At the equal-risk weight (§2.4):
  - the combined net Sharpe is **below the book alone** at every cost for NAV tenders, and at 30bp
    for E1;
  - the combined book needs more than the frozen 1.80× gross ceiling on about half its days;
  - each sleeve earns less per unit of gross than the book: **2.88%/yr and 1.20%/yr, against
    5.15%/yr**.
- **With the ceiling applied** (approximately, §2.4), NAV tenders lower the book's gross Sharpe, to
  0.933, and E1 leaves it where it was (0.960 against 0.955).

## 1. The series

| series | how it was built | check |
|---|---|---|
| NAV tenders: tradable sleeve, daily, 2010-03-24 to 2022-12-30 | `scripts/research/reopen_book/extract_trial_series.py navtender`. It runs the branch's own committed `scripts/events/nav_tender_trial.py` (`stage0(write=False)`, then `run_pnl` with the fit's k and the 1.80 cap at entry) from that worktree | reproduces `results/events/nav_tender/fit_2026-10-19.json` exactly: gross 0.450, nets 0.381 / 0.244 / 0.037, vol, turnover, T 3,217, k [S], max abs difference 0.0 [V] |
| E1: tradable muni sleeve, daily, 2009-06-23 to 2022-12-30 | the same script, `e1`. It runs `scripts/events/e1_merger_pair.py`'s `fit()` steps up to `sleeve(...)`; control 2's pick is skipped because the sleeve never reads it | reproduces `results/events/e1/e1_fit_verdict.json` exactly: gross 0.281, nets 0.244 / 0.170 / 0.059, k, T 3,406, 98 deals [S], max abs difference 0.0 [V] |
| CEF book, daily, live policy | `build_targets` on `data/cef/` panels **cut at 2022-12-30 before any computation** (the harness's `source=`), then `band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)` and `evaluate()` on `total_returns` (H15). The spec is `cef_discount.v7.20260928`, "band 4.8% + gmax 1.80x", all read through `scripts/cef/spec.py`. Full panels end 2026-10-15 (prices) and 2026-10-14 (NAV); nothing after 2022-12-30 enters the process | **second method:** each trial's own R-BOOK correlation, built on the full panel, is reproduced to six decimals. NAV tenders 0.086320 on n 2,398, as the trial got [S]; E1 0.016656 on n 3,406, as the trial got [S]. So the cut changed no fit-period value [V] |

- **Neither trial stored a daily series.** Their JSONs hold aggregates only, because the series are
  derived from licensed CRSP rows.
- The re-derived series stay in the gitignored `results/research/reopen_book/_cache_reopen/`.
- Nothing was written in either trial's worktree: `git status --ignored` and the file mtimes were
  identical before and after.
- The extractor makes the R2 client unimportable, refuses a CRSP cache miss rather than pulling, and
  installs `ops.netguard`.

## 2. How each item was computed (rules written into the script before its first run)

The trials' own aggregates were already published, so these rules are not blind to the sleeves'
Sharpes. They are blind to this measurement.

### 2.1 Standalone (item 1)

- **Statistics:** `band_frontier._stats` on the common window, on each sleeve's own cost convention:
  - NAV tenders charge notional on every leg (entry, residual sale, ETF hedge changes),
    6.34 turns/yr;
  - E1 charges event turnover, where a merger conversion is not a trade, 2.37 turns/yr.
- **Deflated Sharpe:**
  - `inference.desk_dsr(SR, T, skew, kurt, 6)`, asserted equal to `dsr(..., 1/T, bound="upper")`;
  - `dsr(..., 1/T, bound="gumbel")` beside it;
  - N = 6 is EVENTS' declared bar (`docs/RESEARCH_STATE.md`, 2026-10-19).
- **Own-span rows, which reproduce the trials:**

| | gross | net 30bp | desk DSR | paper DSR |
|---|---:|---:|---:|---:|
| NAV tenders, 2010-03-24 to 2022-12-30 [V] | 0.450 | +0.037 | 0.392 (trial: 0.392 [S]) | 0.617 |
| E1, 2009-06-23 to 2022-12-30 [V] | 0.281 | +0.059 | 0.194 (trial: 0.194 [S]) | 0.394 |

### 2.2 ρ and its range (item 2)

The range is the union of five intervals. The rule is tested at its upper end.

| interval [V] | NAV tenders | E1 |
|---|---|---|
| daily, stationary bootstrap, block = median active spell (60 / 120 sessions) | +0.086 [−0.014, +0.191] | +0.021 [−0.014, +0.060] |
| daily, stationary bootstrap, block 21 | +0.086 [−0.021, +0.195] | +0.021 [−0.014, +0.057] |
| daily, stationary bootstrap, block 63 | +0.086 [−0.014, +0.192] | +0.021 [−0.014, +0.059] |
| weekly (Friday) sums, n 497, Fisher | −0.032 [−0.119, +0.056] | −0.014 [−0.102, +0.074] |
| 21-session sums, n 114, Fisher | +0.010 [−0.174, +0.194] | −0.099 [−0.278, +0.086] |

**Why these blocks:**
- The stationary bootstrap resamples the pairs together: 10,000 draws, seed 20261028.
- The mechanism block is the sleeve's **median active spell**: the length of a run of sessions with
  a position held. It is measured from holdings, never from P&L. A resample shorter than that
  breaks the on/off pattern that makes a sparse sleeve's ρ noisy.
- 21 and 63 are the blocks both trials declared.

**The sums:**
- The 21-session sum is `results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md` §2.4's input, because daily
  correlations of thinly traded books understate co-movement.
- Their Fisher intervals assume independent sums.
- Not every sum has the sleeve active. NAV tenders has 362 of 497 weeks and 96 of 114 blocks;
  E1 has 320 and 80.

**The new statistics** live in `scripts/research/inference.py`: `stationary_bootstrap_corr` and
`fisher_corr_ci`, added with tests. The draw is pinned by a parity test to
`w4_artifacts.stationary_boot`'s, and the Fisher interval to scipy's.

### 2.3 Marginal gain (item 3)

- `inference.marginal_gain(SR_sleeve, SR_book, ρ)` at the point estimate and at both ends of the
  range.
- It is computed on gross Sharpes and on each net level, with the book's own net Sharpe at that
  cost.
- **NAV tenders at 30bp:** the sleeve's own net is −0.022 on this window, so the gain is negative
  for any ρ ≥ 0.
- On its own span NAV tenders is +0.037 at 30bp [V; trial +0.037 S]. **The window drops its
  2010–13 sessions, and that is where the sign flips.**

### 2.4 The combined book (item 4)

**The weight rule: equal risk budgets.**
- `PORTFOLIO_FRAMEWORK` §2.3 sets b ∝ R̃⁻¹·1 with fewer than four sleeves. For two sleeves that is
  equal budgets at any ρ.
- Each sleeve's own scalar targets its budget, and an event sleeve's budget is a ceiling (§2.2).
- So each enters at the sizing its pre-registration derived, and **combined = book + 1.0 × sleeve**
  on capital. Nothing is optimised on the fit.

**Costs and gross add, and nothing nets.** Neither sleeve trades a symbol the book holds [S, read
from each branch's code]:
- NAV tenders' Stage 0 drops in-universe funds (`in_universe_excluded` in its `stage0_2026-10-19.json`);
- E1's `e1_prereg_counts.partition` moves a deal touching a spec name to `excluded_spec`, and a
  deal touching the 44-fund universe to the name holdout.

| combined, gross / net 5 / 15 / 30bp [V] | NAV tenders | E1 |
|---|---|---|
| book alone (total returns) | 0.955 / 0.852 / 0.645 / 0.334 | same |
| **book + sleeve (headline)** | **0.959 / 0.840 / 0.603 / 0.248** | **0.965 / 0.858 / 0.644 / 0.323** |
| book + sleeve, ceiling applied to the combined held gross (approximate) | 0.933 / 0.814 / 0.576 / 0.219 | 0.960 / 0.854 / 0.641 / 0.321 |
| book on price returns + sleeve (paper pays no distributions: CLAUDE.md landmine 1) | 0.967 / 0.850 / 0.617 / 0.268 | 0.972 / 0.867 / 0.658 / 0.344 |
| plain `band()` book (no ceiling) + sleeve | 0.945 / 0.829 / 0.596 / 0.248 | 0.956 / 0.851 / 0.640 / 0.324 |
| E1 costed on the harness's turnover (12.33/yr, conversions as trades) | — | — / 0.791 / 0.442 / **−0.081** |
| long-only optimum at the point ρ (`combined_sharpe`; a ceiling, **not a weight choice**) | 1.001 gross; 0.334 at 30bp | 0.988 gross; 0.339 at 30bp |

About the approximate ceiling row:
- It scales the combined day by min(1, 1.80 / held gross), as `_cap_gross` scales a held book.
- It does not rebuild the band's feedback into the next day's trade, and it scales turnover with the
  book. It decides nothing.

**Leverage**, as held gross Σ|w| against `max_gross_stress` 1.80 from the spec [V]:

| | NAV tenders | E1 |
|---|---|---|
| book: mean 1.21, p95 1.80, never above the ceiling | | |
| sleeve alone: mean / p95 | 0.62 / 1.61 | 0.77 / 1.80 |
| combined: mean / p95 / max / days above 1.80 | 1.83 / 2.96 / 3.50 / 48.2% | 1.98 / 3.26 / 3.60 / 50.1% |
| days above 1.80, counting only days the sleeve is active | 68.8% | 80.6% |
| days above 1.80, combined rescaled to the book's own vol (× 0.778 / × 0.879) | 27.1% | 43.4% |
| annual return per unit of held gross: book / sleeve | 5.15% / 2.88% | 5.15% / 1.20% |

## 3. The caveats that matter

1. **The sleeve's Sharpe is the noisy input, not ρ.**
   - The rule treats SR_sleeve as known.
   - The sleeves' means have Newey–West t of 1.43 and 1.14 on this window.
   - Their Sharpes are each within about one standard error of zero, so "adds to the book" inherits
     that uncertainty.
   - ρ is noisy too, but it is small against the break-even. The widest interval is the 21-session
     sums' (n 114), and its upper end (+0.194 / +0.086) is still below the break-even ρ
     (0.399 / 0.286).
   - The daily bootstrap intervals are much narrower than the summed ones. **Read the summed rows
     as the range.**
2. **Limb 2 is weak as written.**
   - The book alone nets 0.334 at 30bp, so almost any sleeve leaves the combined net positive.
   - Measured against the book's own net instead, at the equal-risk weight, NAV tenders lowers it at
     5, 15 and 30bp, and E1 lowers it at 30bp (§2.4).
   - The marginal gain says a *small* allocation helps. An equal risk budget is not small for a
     Sharpe of 0.27–0.38.
3. **The gross ceiling binds before the vol budget does.**
   - The book already reaches the 1.80× ceiling (p95 1.80).
   - Under a binding gross budget the framework ranks sleeves by return per unit of gross (§2.5).
     Both sleeves earn less per unit than the book, so each unit of gross they take displaces book
     gross that earns more.
   - The framework also requires `max_gross_stress` to be re-derived on the combined book at
     promotion (§2.7). That was not done here.
4. **Overlap.**
   - The common window drops the sleeves' 2009/10–2013 sessions, because the book was flat then.
     That is where NAV tenders' own-span net 30bp is positive.
   - The sleeves' holdings overlap in time (median active spells 60 and 120 sessions). That is why
     the blocks and the sums were used.
   - Neither sleeve shares a symbol with the book [S]. **Whether the two sleeves share symbols with
     each other** was not measured: an E1 acquirer short could be a tendering fund. Each was judged
     against the book alone, not together.
5. **Cost conventions.**
   - Each leg is costed on its own convention.
   - E1's event turnover is the trial's declared one. Costed on the harness's count instead
     (conversions as trades), E1's own net is −0.272 at 15bp, and the combined net is −0.081 at
     30bp.
   - Borrow and NAV tenders' election fee are left out. Paper charges no borrow (landmine 1). On its
     own span NAV tenders' hedge borrow is −0.075 Sharpe and its election fee at $100k is −0.160
     [S, `NAV_TENDER_RESULT_2026-10-20.md` §2]. E1's B-med borrow schedule turns its 15bp net
     negative [S]. Both matter for real capital, which keeps the standalone gate anyway.
6. **Paper mechanics are unmeasured [U].**
   - Whether Alpaca paper processes a voluntary tender election or a merger conversion was not
     measured here.
   - The tender's own payoff (A − B) is +0.634% of NAV tenders' +1.084% per event [S].
   - Paper also pays no distributions (landmine 1). The price-return book row (§2.4) shows that the
     book's side barely moves; the sleeves' CRSP total returns include distributions.
7. **Eras (H5)** [V], each era clipped to the common window:

| era | NAV tenders: SR / ρ / gain | E1: SR / ρ / gain | book SR |
|---|---|---|---:|
| 2013-06-25 to 2014-12 (384 sessions) | 0.393 / +0.039 / +0.342 | −0.216 / +0.092 / **−0.336** | 1.298 |
| 2015-19 | −0.020 / +0.019 / **−0.036** | 0.320 / +0.023 / +0.301 | 0.835 |
| 2020-22 | 0.749 / +0.168 / +0.578 | 0.450 / −0.009 / +0.460 | 1.020 |

   - Each sleeve subtracts in one era.
   - In the book's worst-quintile 21-session blocks (23 blocks, book mean −1.45%):
     - NAV tenders still averaged +0.05% per block, against +0.18% elsewhere;
     - E1 averaged +0.22%, against +0.04% elsewhere.
   - 23 blocks is too few to rely on either reading.

## 4. What this does not do

- It spends no trial. EVENTS stays at 2, with its bar at N = 6.
- It opens no holdout:
  - every series ends 2022-12-30, and that is asserted in the extractor and in `common_window`;
  - E1's holdout extract still does not exist.
- Whether either sleeve is admitted is the team lead's call.
- It has not had an independent review. Two second methods were run instead:
  - the exact reproduction of both committed fits;
  - the R-BOOK parity check on the book.

## 5. Files

| file | role |
|---|---|
| `scripts/research/reopen_book/reopen_book.py` | the measurement; the rules in its docstring |
| `scripts/research/reopen_book/extract_trial_series.py` | runs each trial branch's committed code, guarded, and checks it reproduces the committed fit |
| `scripts/research/inference.py` | gains `stationary_bootstrap_indices`, `stationary_bootstrap_corr`, `fisher_corr_ci` |
| `scripts/research/tests/test_inference.py`, `test_reopen_book.py` | the tests: parity with `w4_artifacts`, scipy and `desk_dsr`, and the window, sums and combination arithmetic |
| `results/research/reopen_book/reopen_book_2026-10-28.json` | every figure above, aggregates only |
