# Pre-registration: C4's discount level against family peers, as a second signal in the C4 account (CEF trial 54 if approved)

Date: 2026-11-02 (finalised the same day)   Counter: CEF, trial 54 **on approval**   Author: idea-generation seat
**Status: FINAL, awaiting the team lead's approval. CEF stays 53.** The counter moves only in the commit that
records the approval (`docs/RESEARCH_STATE.md`; `/prereg`). No trial has been spent. No 2023+ return of this
signal has been computed, and **Gate 0 (§4b) runs before any 2023+ return of it is read.**

The team lead chose on 2026-11-02 to take this signal to a pre-registration. The evidence is the zero-trial
screen `ALPHA_SLATE.md` §S5 in this folder (fit only, yfinance return leg). The design inputs are in
`prereg_c4_level_design.py` → `prereg_c4_level_design_output.txt`. On approval this file moves to
`results/cef/PREREG_C4_LEVEL_2026-11-02.md` (open question 9).

## 0. The answer in one table

| item | answer |
|---|---|
| **what changes** (§1) | One new optional frozen key in C4's spec, `level_signal`. **Absent, C4 is today's book byte for byte.** Present, C4's unit target becomes an equal-risk blend of its z target and a within-family discount-level target, through the same vol scalar, multiplier, band and **the same 1.90 gross cap** |
| **the split** (§3) | **Half the ex-ante risk on each signal.** Derived from the two-sleeve mean-variance rule on fit inputs (gives 0.515 on z) and rounded to equal risk. Plateau: SR 1.443–1.549 across 0.30–0.70; the derived 0.50 is also the grid's argmax, so nothing was moved toward it |
| **the shared cap** (§3.3) | Kept at 1.90 (a margin rule, not a tuned parameter). On the fit at ×1.27 the blend's held book sits at the cap on **29.0%** of sessions, against 22.0% for z alone. Turnover falls from 48.9 to **33.2** turns a year (construction properties only; no P&L of the blend computed) |
| **Gate 0** (§4b) | Survivorship, with dead funds included, run **before approval**. **A team-lead judgment on the result** (ruled 2026-11-02: "keep it flexible and make judgment off results"), recorded **post-data** in `docs/SYSTEM.md` §5. It is evidence, **not a pre-registered gate**. `gate0_analysis.py` reports the ratio with 95% CIs, the sign test, and the verdict under both candidate rules (≥ 0.5, ≥ 0.75) with each one's power and false-alarm rate. Pull 1 (CRSP) was too thin; pull 2 (EDGAR N-CSR) is running |
| **pass rule** (§6.2) | Fit: the level book's spanning alpha on C4's z book, **NW t ≥ 2.825** (√(2 ln 54)). Also the deflated-Sharpe bars at declared N = 54, NC1, the placebo and D4. Then the 2023–26 holdout's **sign** (the C4 precedent). Net at 15bp is reported (D2 label) **Unchanged by the Gate 0 ruling, and still pre-registered** |
| **stops** (§6.3) | C4's own kill rule and the trial-53 stops, **rebuilt on the blended book**, plus L1: the level component's modelled 120-session P&L below its fit 5th percentile → revert the key |
| **revert** (§9) | Delete `level_signal` from C4's spec |
| **expected** (§5) | +0.4 to +1.0%/yr gross on all capital [model, U] after the cap haircut; the blend's ex-ante SR about 1.5 vs 1.18 uncapped |
| **open questions** (§10) | ten, each with a recommended answer (the tenth: amendment A1, after pull 1 proved too thin) |

---

## 1. What changes

### 1.1 The key, the file, the value

| spec | file | today | after |
|---|---|---|---|
| C4 | `ops/specs/c4_families.frozen.json` (branch `c4-rel`, 8b14298; dark, not on `main`) | `c4_families.v3.20261102`; key absent | **`level_signal: {"risk_share": 0.5, "family_of": {<ticker>: <family>, ... 74 rows>}}`**, spec id v4 |

- `family_of` is C4's frozen family map (`results/cef/c4/c4_universe_frozen_2026-10-14.csv`, column `family`),
  copied into the spec so the sleeve reads no second file.
- **Nothing else in the spec moves:**
  - `vol_target_annual` 0.06, `sizing_multiplier` 1.27, `band_width` 0.048 and `max_gross_stress` 1.9;
  - `z_window` 252, `min_adv_usd` $3m, `min_names` 6 and `min_abs_weight` 0.005;
  - the masks, and the `risk` block.

### 1.2 What the sleeve does with it

The blend is built inside `src/deploy/sleeves/cef_discount.py::target_positions`, on the date-t panel only (H7):

1. **w_z**: today's unit-gross z weights, −(z − mean z), on today's eligible names.
2. **w_L**: on the same eligible names, −(discount − its family's mean discount), unit gross. A family with
   fewer than 2 eligible names contributes zero. The discount is the panel's own `disc` (price against NAV),
   with C4's M1|M2 masks applied as they are to the z.
3. **Risk equalised.** s_z and s_L are the trailing realised vols of the two unit-gross books, using today's
   weights on the last 63 sessions of price returns through t. That is the estimator `build_targets` already
   uses for its vol scalar. mix = ½·w_z/s_z + ½·w_L/s_L, renormalised to unit gross.
4. **One vol scalar, the existing one:** target = mix × clip(0.06 / s_mix, 0.2, 2.5).
5. From here **today's code path runs unchanged:** the account holds m × the unit target, the band compares it
   with held / m, `_cap_gross` acts at 1.90 / m in unit weights, and the dust filter reads the unit weight.

When the key is absent, steps 2–4 do not run, and w_z × its scalar is today's target.

### 1.3 Tests, each shown to fail against the old code before it is kept

1. **Key absent: byte-identical** to `c4_families.v3.20261102` on the real panel and on the synthetic one. It
   covers plan.json, plan_sha, orders, targets and the run record, as the trial-53 pins do.
2. **Key present with `risk_share` 0** (all risk on z): identical to absent.
3. **Equal risk:** on a synthetic panel with known vols, the blend's ex-ante risk contributions are equal to
   1e-12.
4. **Families:** a ticker without a family raises. A one-name family gets zero level weight.
5. **The cap:** the emitted gross is ≤ 1.90 × NAV.
6. **C4's fidelity probe passes:** `scripts/cef/c4_paper_benchmark.py` gains the same blend, so the HALT rule
   still compares like with like.
7. **The combiner refuses** a `risk_budget` sleeve whose spec carries the key, as it refuses `sizing_multiplier`.

---

## 2. Why, mechanically

**The mechanism.** Retail yield buyers overpay for some funds' brand or distribution rate. The arbitrage is a
short of the premium fund, whose lendable pool cannot grow (no creation). Borrow is dearest exactly there, and
idiosyncratic risk binds (Pontiff 1995 [U on magnitude], Pontiff 2006 [S]; `docs/REFERENCES.md`). So premium
funds underperform their peers and discount funds outperform, over months. **The loser** is the holder who
pays the premium.

**The z cannot see it.** C4's z is standardised against each fund's own 252-session history, so a fund that has
sat 10pp rich of its peers for a year has z near zero. **It is not fair value in costume, in these families.**
The NAV leg of the fit slope is −0.26bp/pp (t −0.32). On the credit core the same test fails exactly there: its
NAV leg is +1.17bp/pp (t +3.01), which is why the trial is C4 only (`ALPHA_SLATE.md` §S5).

---

## 3. How the parameters were derived

### 3.1 The risk split

The rule: for two unit-vol strategies with Sharpe s1, s2 and correlation ρ, the mean-variance risk weights
are ∝ (s1 − ρ s2, s2 − ρ s1). The inputs were measured on the fit, 2005-02-22 → 2022-12-30, total return, on
the series the screen had already seen [V `prereg_c4_level_design.py` §A]:

- s_z = 1.178 (C4's spec book, ×1.27, cap 1.90);
- s_L = 1.123 (the level book);
- ρ = +0.104.

The weights come out 1.073 : 1.011, which puts **0.515 on z**. Two Sharpes estimated this noisily do not
support 0.515 over ½, so **the derived value is equal risk, 0.50.**

**The plateau** (an equal-weight-of-risk blend of the two unit-risk series, fit, already seen):

| share of risk on z | 0.30 | 0.40 | **0.50** | 0.60 | 0.70 |
|---|---|---|---|---|---|
| Sharpe | 1.443 | 1.517 | **1.549** | 1.531 | 1.471 |

The surface is flat within 0.03 Sharpe across 0.40–0.60, and the derived value sits on top of it. **The grid's
argmax is also 0.50.** It was not chosen from the grid: the rule gives 0.515 before the grid is read.

### 3.2 The level's construction

The construction was declared before the screen's first run (`alpha_level.py` docstring) and never varied:
within family, unit gross, the raw discount level, and z-blind.

- **Not chosen:** a pooled level across families, never run, because `docs/SYSTEM.md` says that is a
  permanent group bet.
- **Not chosen:** a monthly calendar refresh, which the screen's book used. The live policy is the band (H8:
  the band width was derived by the cube-root law). The trial measures the daily level through the band.

### 3.3 The shared 1.90 cap

`max_gross_stress` 1.90 is C4's margin rule, re-derived by the core's frozen rule (`docs/SYSTEM.md` §5), and
it is not re-tuned for this trial. Lower correlation means more gross per unit of risk, so the cap binds more
often. Construction properties on the fit, at ×1.27, band 4.8% [V `prereg_c4_level_design.py` §B]:

| book | target gross | target > cap | uncapped held gross | held gross | at the cap | turns/yr |
|---|---:|---:|---:|---:|---:|---:|
| z only (the v3 spec book) | 1.525 | 23.2% | 2.118 | 1.556 | 22.0% | 48.9 |
| **blend, ½ : ½** | **2.298** | **72.6%** | **2.556** | **1.722** | **29.0%** | **33.2** |

The cap scales the whole held book by one factor, so it takes risk from both signals in proportion. The split
survives the cap; the account's level of risk does not. That haircut is in §5.

---

## 4. Committed in advance

- **Execution:** shift(2) through `scripts/research/harness.py` (`band_frontier.band_gross_capped`, then
  `evaluate` / `report`). No new backtester.
- **Score:** gross P&L is the headline, total return, on **CRSP primary returns as C4's fit used**, with the
  yfinance leg as the second source. Price only (paper's P&L of record) sits beside it. The 5 / 15 / 30bp grid
  is labelled as the real-money view. Borrow gets its own column, not charged on paper.
- **Eras:** C4's: 2005–09, 2010–14, 2015–19, 2020–22; holdout 2023–26.
- **Fit ends 2022-12-30**, asserted in every helper.
- **Holdout 2023-01-03 → 2026-09-30**, the window C4's own holdout used. Opened once, after the fit verdict's
  commit.
- **Turnover matching (H2):** the z-only reference is re-run at the band width that matches the blend's
  turnover within 5% (`band_frontier.match_band_width`), and the comparison is made there.
- **Negative controls:**
  - NC1, the NAV leg of the level slope (must stay |t| < 2);
  - the within-family shuffle placebo (20 draws, seed 20261102).
- **Declared seen:**
  - every figure in `ALPHA_SLATE.md` §S5 and in `prereg_c4_level_design_output.txt` (fit);
  - C4's 2023–26 returns, which were opened for trial 52 on 2026-10-18 (the z book, not this signal).

### 4b. Stage 0: Gate 0 first, then the data gates. No P&L of any kind before every gate is clear

**Gate 0 — survivorship, run before the approval commit** (open question 1), on fit data only:

> **RULED 2026-11-02 (the team lead): "keep it flexible and make judgment off results".**
>
> - **Gate 0 is a team-lead judgment on its result, not a mechanical gate.** The rules in the table below (and
>   amendment A1's 0.75) stay as the declared reference points. Neither one decides.
> - **The caveat, plainly.** A gate decided after its data have been seen is not a pre-registered gate. Gate 0 is
>   evidence for the team lead's judgment. It cannot claim a pre-registered pass, and the record must not describe
>   it as one.
> - **What the evidence is.** `gate0_analysis.py`, which writes `gate0_analysis_output.txt` and `.json`. It
>   reports:
>   - b_D / b_A (dead against survivor slope) and b_B / b_A (all funds against survivors), each with a 95% CI from
>     (1) a bootstrap by fund-half-year, the headline, and (2) a bootstrap by calendar half-year as a second
>     method. The two are reported side by side and not averaged;
>   - the sign test: the share of half-years whose dead-only slope is negative, a binomial p, and P(b_D ≥ 0);
>   - the verdict under both candidate rules, ≥ 0.5 (the original) and ≥ 0.75 (A1), each with its power
>     P(flag | halving) and false-alarm rate P(flag | r = 1) at the realised NAV coverage. For reference, at full
>     coverage the power is 0.50 and the false-alarm rate 0.00 for ≥ 0.5, and 0.97 and 0.03 for ≥ 0.75
>     (`gate0_coverage_output.txt`);
>   - coverage, the calibration agreement, and two sensitivities: cells of family × period-end month (primary,
>     declared before any dead-fund NAV was read) against family × half-year, and with the dead funds whose names
>     go unclassified excluded.
> - **The record.** The team lead's Gate 0 call goes into `docs/SYSTEM.md` §5 with its date, labelled
>   **"post-data"**. It names the evidence file's commit and the reasons in a sentence. A negative call means no
>   approval and no trial; a positive one leaves §6.2 to judge the trial.
> - **What does not change.** The trial's own pass rule (§6.2: the fit's spanning alpha NW t ≥ 2.825 at N = 54,
>   the deflated-Sharpe bars, NC1, the placebo, D4, then the holdout's sign) is unchanged and stays pre-registered.
> - **Code check.** `gate0_analysis.py --self-test` (15 survivors posing as dead) gives b_B / b_A 1.047, CI (1)
>   0.873–1.297. That is the expected answer with no survivorship by construction, so the test can see a null.



| step | what | rule, stated now |
|---|---|---|
| G0-pull | the team lead runs `results/cef/screens_2026-11-02/run_gate0_pull.sh`: the CRSP dead population and a CRSP mutual-fund NAV probe (§11) | the manifest's row counts and dates are recorded; `check_holdout` must pass |
| G0-NAV | a NAV for every pulled fund. CRSP-MF where the probe matches (each match reviewed by name). Otherwise the funds' N-CSR / N-CSRS period-end NAVs from EDGAR, read with `scripts/events/cef_corp_action_census.py::nav_beside_price` (the team lead's EDGAR run) | **HALT** (team lead rules) if under 80% of dead five-family fund-half-years 2005–22 get a NAV |
| G0-family | each pulled CEF permno is assigned to one of C4's five families or to "out" (credit, muni, global, convertible, other). The script proposes from name keywords; every row is ruled in `gate0_family_rulings_<date>.csv` | **HALT** if unruled rows exceed 10% of fund-half-years; unruled rows are excluded and counted |
| G0-run | the level statistic at semiannual frequency, with one NAV source for everyone. At each half-year's period-end NAV: the pooled within-family slope of the forward CRSP total return over t+2 .. t+127, delisting returns included, on the within-family discount level. z is not included (there is no daily NAV for the dead). Standard errors clustered by half-year. **A** = the 65 fit funds alone; **B** = every five-family CEF, alive or dead (the 60 left-out live funds included) | **PASS** if b_B < 0 and b_B / b_A ≥ 0.5. **HALT** (team lead rules) if 0 < b_B / b_A < 0.5. **FAIL → withdraw, no trial spent** if b_B ≥ 0. **HALT** also if b_A ≥ 0, because then the frequency change broke the test, not survivorship |

> **2026-11-02 (later): Gate 0, pull 1 is NOT enough; pull 2 is written.** The team lead ran `run_gate0_pull.sh`
> (manifest 2026-11-03T03:01Z: 1,003 CEF permnos; dsf 2,902,916 rows, 2004-01-02..2022-12-30; 36 CRSP-MF NAV matches).
> Measured by `gate0_coverage.py` (output `gate0_coverage_output.txt`), zero trials, no Gate 0 statistic formed:
> - **0 of 36 matches are on CUSIP. 34 are recycled tickers** (ETFs that took a dead CEF's ticker). Only **2 are
>   genuine**: First Trust Value Line Dividend and Value Line 100, CEFs that later became ETFs. Both are dead C4
>   candidates, with **9 fund-half-years** in the fit window.
> - The dead set: 498 CEFs died in 2005–22. **190 are C4 candidates or unclassified** by name (75 + 115):
>   2,626 fund-half-years, against the survivors' 1,570.
> - **Power.** The survivors' semiannual slope is b_A −27.24bp/pp (t −4.55). With pull 1's NAVs, B ≈ A, so
>   **P(flag | halving) = 0.00** whatever the truth. With full EDGAR coverage, under the rule as stated
>   (flag below 0.5): P(flag | halving) = **0.50** at any sample size, because a halving sits on the boundary;
>   0.99 at r = 0.25; 1.00 at r = 0; 0.00 false alarms at r = 1. At 80% coverage the figures are 0.35 / 0.95 / 1.00.
> - **Pull 2:** `run_gate0_ncsr.sh` → `gate0_pull_ncsr.py`, the funds' N-CSR/N-CSRS period-end NAVs from EDGAR.
>   `--plan` on the census's cached index: 133 of 190 candidates map to a filer (57 for rulings); 1,630 filings
>   2008-01..2023-06, plus the 2004–07 quarters.
>
> **Amendment proposal A1, for the team lead** *(superseded 2026-11-02 by the ruling above: both thresholds are now reported reference points; neither is mechanical)*. **It changes no rule until ruled, and it is made before any dead-fund
> NAV has been read:**
> - (i) **Flag below 0.75, not 0.5.** Full coverage: P(flag | halving) 0.97, false alarms at r = 1 0.03. At 80%:
>   0.94 / 0.03.
> - (ii) **Live funds use the families panel's NAV on the same period-end; dead funds use the report NAV.**
>   Pre-condition: on `ncsr_calibration.parquet` (up to 40 survivors), the report NAV and the panel NAV agree
>   within 1% on ≥ 95% of rows. Else HALT. This replaces "one NAV source for everyone", which would need N-CSRs
>   for about 125 live funds as well.

**The data gates, after approval** (the C4 trial's own machinery, `require_stage0_rulings` in
`scripts/cef/data_guards.py`):

| gate | test | halts if |
|---|---|---|
| DG-L2 second source | the fit's level book on CRSP primary vs the yfinance leg | gross SR differs by more than 0.2, unexplained |
| DG-L3 data | the 242 fit name-days with \|price TR − NAV TR\| > 10% are triaged; C4's split, bar and seed rulings applied | any flag without a ruling |
| DG-L4 identity | the key absent reproduces C4's v3 book, and the trial script's blend reproduces the sleeve's | any diff |

---

## 5. What we expect [model, U]

- **Fit, already seen.** Unit-risk blend Sharpe about 1.55 against z alone 1.18, uncapped. Under the cap the
  held gross falls to 0.67 of its uncapped level, against 0.73 for z alone.
- **Account return.** Scaling each book's Sharpe by its cap ratio, at C4's 7.62% ex-ante vol (0.06 × 1.27),
  gives +1.4%/yr on C4's $100k. That is **+0.7%/yr on all capital** ($200k across the two accounts,
  `docs/SYSTEM.md`). **Range +0.4 to +1.0%/yr** for out-of-sample shrink.
- **Holdout** (3.74 years). The level book's gross SR 0.5–1.1: P(SR > 0) 0.86–0.99, but P(t ≥ 2.825 on the
  holdout alone) only 0.04–0.26. That is why the judging structure is the C4 precedent (open question 2).
- **P(pass) overall about 0.5–0.7 [U].** Gate 0 is the largest unknown: P ≈ 0.6–0.8, guessed and not measured.
  The fit stage is ≈ 0.9, an in-sample upper bound, and the holdout sign ≈ 0.9.

## 6. What the trial can show, and what would falsify it

### 6.1 The claim

**H-L:** inside C4's families, the discount level against family peers predicts returns beyond C4's z, through
the discount and not the NAV, and survives survivorship. It is recorded as PRESENT, ABSENT or INCONCLUSIVE beside
its D-code (team lead 2026-10-27).

### 6.2 The pass rule, at the CEF bar for N = 54

**This rule is unchanged by the 2026-11-02 Gate 0 ruling and stays pre-registered.** The bar is √(2 ln 54) = **2.825**. The registry's least N for CEF is 54 (`minimum_declared_n`, measured
2026-11-02). Each kill is read once, in order:

1. **Gate 0 and the data gates** (§4b).
2. **P1, fit, the bar.** Regress the daily P&L of the level-only spec book (w_L with its own scalar, ×1.27,
   band, cap 1.90 / m) on the daily P&L of the z-only v3 spec book. The alpha's NW t (automatic lag,
   `w4_artifacts.nw_auto_lag`) must be **≥ 2.825**. Else **KILL (D1)**.
3. **P2, fit.** The blended book passes both deflated-Sharpe bars:
   `python3 -m scripts.research.registry bars CEF 54 blend --declared-n 54`. Else KILL.
4. **K1–K3, fit.** Each failure is a KILL with its D-code:
   - NC1: the NAV-leg slope has |t| < 2, else D1;
   - the placebo: the real book ranks above ≥ 19 of 20 within-family shuffles;
   - D4: alpha t ≥ 3.0 with every |β| ≤ 0.10 on C4's factor set (`c4_families.fit`'s D4 block), else D4.
5. **P3, fit, H2.** The blend's gross Sharpe must exceed the z-only book's at matched turnover. `sharpe_diff`
   (`scripts/research/resampling.py`) is reported, not gated: its expected t is about 2.3. Else KILL.
6. **Holdout, opened once.** The level book's gross SR > 0 **and** the blend's gross return above the z-only
   book's. Else **KILL (D3)**.
7. **Net, reported.** At 15bp the blend's net SR must be ≥ the z-only book's; if not, the label is **D2**. It
   does not block paper (C4 is paper only by ruling).

### 6.3 The live stops (per C4 account, on Alpaca's end-of-day history, the P&L of record)

Every threshold is re-measured on the read date by the trial script on the blended book (H14). None is written
in the spec.

| stop | rule | action |
|---|---|---|
| C4 kill rule, **rebuilt on the blended spec book** | HALT on a fidelity break. REVERSE at 120 armed sessions below the 5th percentile of the blended spec book's 120-session price-only returns (stationary bootstrap, mean block 21). REVERSE on a drawdown past its fit worst | as today's rule |
| trial-53 stops R1–R3, rebuilt on the blended book | as `PREREG_VOLTARGET_2026-10-30.md` §6.2 | revert the multiplier |
| **L1, the level component** | at 120 armed sessions, the level-only book's **modelled** P&L on the live panel, decided as the runner decided, below the 5th percentile of its fit 120-session distribution. Modelled, so it is a stop, not evidence | **revert `level_signal`** |
| reported, no rule | the share of sessions at the 1.90 cap, against the fit's 29.0% | — |

---

## 7. Divergences from the backtest, stated up front

1. **Paper pays no distributions and fills at the quote**, 8 to 2 minutes before the close (`late_market`).
   The level book's price-only Sharpe on the fit (1.19) is above total return (1.12), so paper does not flatter
   it.
2. **Shorts Alpaca will not lend are skipped.** The level book's shorts are the premium funds (on the fit: DNP,
   GCV, GGN, RFI, BME, ASG), the most likely to become hard to borrow. A skipped short tilts the book long.
3. Whole shares, `min_trade_usd`, and the dust filter on unit weights.
4. **The daily level through the band is not the screen's monthly book.** The fit stage measures the former.
5. **The 9 non-NYSE funds** are scored as gaps, as for C4 today.
6. **The missing-NAV hold and the stale-NAV gate** (report mode) are not in the backtest.

## 8. Costs

**Gross decides on paper.** Turnover falls under the blend (33.2 against 48.9 turns a year at ×1.27, §3.3), so
the drag at any cost is lower than z alone's. **Borrow on the premium-fund shorts is unmeasured.** It is the
arbitrage cost the mechanism relies on, so it must be measured, not modelled, before any real-money proposal.
Real money stays gated as for C4 (paper only, 2026-10-19).

## 9. The revert and the trial count

- **Revert:** delete `level_signal`. C4 is then v3 byte for byte (test 1). A revert is a spec change through
  `/spec-change`, recorded in the stop's row.
- **The trial:** CEF 53 → 54 in the commit that records the approval, not before. The bar at N = 54 is 2.825.
  If Gate 0 runs first as recommended and fails, there is no approval and no trial.

## 10. Open questions for the team lead, each with a recommended answer

1. **Run Gate 0 before the approval commit?** **Yes.** It reads fit data only, like the screen, so a failure
   spends no trial. *Ruled 2026-11-02: Gate 0 is the team lead's post-data judgment (§4b).*
2. **Judging structure:** the fit at the bar, then the holdout's sign (C4's precedent), or the holdout alone at
   2.825? **The C4 precedent.** The holdout alone has P(pass) 0.04–0.26.
3. **The split:** **0.50**, derived (§3.1).
4. **The cap:** **keep 1.90.** It is a margin rule; the blend binds on 29.0% of sessions against 22.0%. Re-derive
   only if the margin rule changes.
5. **Gate 0's pulls:** **the team lead runs `run_gate0_pull.sh`** (CRSP via R2), then the EDGAR N-CSR NAV fetch
   if the mutual-fund probe finds no CEF NAVs.
6. **The fit's return source:** **CRSP primary** (C4's fit), with the yfinance leg as the second source (DG-L2).
7. **Borrow:** **ignored in the verdict, in its own column,** as C4. Measured before any real-money proposal.
8. **Gate 0's sample B:** **every five-family CEF, alive or dead,** the 60 non-shortable live funds included;
   survivorship is about the population, not the tradable list.
9. **Where the final file lives:** **move it to `results/cef/PREREG_C4_LEVEL_2026-11-02.md`** in the approval
   commit, with this folder's draft path left as a one-line pointer.
10. **Amendment A1 (§4b, 2026-11-02 later): flag below 0.75, and live funds on panel NAV with a calibration
    pre-condition?** **Superseded by the ruling** ("keep it flexible and make judgment off results"): both thresholds
    are reported with their power and false-alarm rates, and the team lead judges. Live funds use the panel NAV; the
    calibration agreement is reported.

## 11. Reproduce

```bash
python3 -B results/cef/screens_2026-11-02/alpha_level.py              # the screen (S5)
python3 -B results/cef/screens_2026-11-02/alpha_level_checks.py       # K1-K8
python3 -B results/cef/screens_2026-11-02/prereg_c4_level_design.py   # §3: the split, its plateau, the shared cap
python3 -B results/cef/screens_2026-11-02/gate0_pull_crsp.py --self-test   # Gate 0's SQL on synthetic tables
python3 -B results/cef/screens_2026-11-02/gate0_pull_crsp.py --dry-run     # Gate 0's SQL, printed; no connection
QUANTT_ENV_FILE=<abs path> results/cef/screens_2026-11-02/run_gate0_pull.sh   # the team lead: the pull
```

**Panels:** C4's families panels (`data/cef_families/`, last date 2026-10-09), read only to 2022-12-30. **Code:**
this branch at the commit that adds this file. C4's spec is read from `c4-rel` 8b14298 (`c4_families.v3.20261102`).
