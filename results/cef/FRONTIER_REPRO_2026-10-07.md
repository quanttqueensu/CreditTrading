# Frontier reproduction and slower-policy rows — 2026-10-07

**Report only. Spends no trial (CEF counter stays 50). Changes no spec.**
Team-lead plan item 5.

**Reproducers**

```bash
python3 scripts/cef/band_frontier.py            # A: the frontier, current spec (13 names)
python3 scripts/cef/band_frontier.py --slower   # B: slower policies, FIT PERIOD ONLY
```

Part A's 17-name check uses the same harness with the v6 universe passed in:
`build_targets(universe=<v6 list>)`, the list read from
`git show spec-cef_discount.v6.20260906:ops/specs/cef_discount.frozen.json`,
then `calendar(T, 2)` / `band(T, 0.048)` scored by `evaluate()` on the full
sample and on the first 5,452 sessions. That is the prereg's session count.

**Panels** (`data/cef/`, read-only) [V, read 2026-10-07]:
`cef_prices.parquet` last date **2026-09-28**; `cef_nav.parquet` last date
**2026-09-25**; `cef_distributions.parquet` last ex-date **2026-09-10**. The
harness sample ends **2026-09-25** (5,467 sessions from 2005-01-03), because it
is the inner join of price and NAV. **The panels do not reach 2026-10.** Data
added since the 2026-09-06 prereg is 15 sessions, nothing more.

Convention throughout: `evaluate()`, i.e. `shift(2)`. Costs are bp per unit of
turnover. **Gross SR is the headline. net@5/15/30bp is the labelled
real-money view.** No borrow is charged in any row.

---

## A. Reproduction — verdict: **reproduced; drift explained**

The 2026-09-06 prereg table was measured on the **17-name v6 universe** with
price returns. Re-run today [V]:

| policy | universe | sample | gross SR | turn/yr | net@5 | net@15 | net@30 |
|---|---|---|---:|---:|---:|---:|---:|
| calendar 2d — *prereg says* | 17 | 5,452 d | 1.20 | 31.1 | — | 0.33 | −0.55 |
| calendar 2d | 17 | 5,452 d (to 2026-09-03) | **1.20** | **31.1** | 0.91 | **0.33** | **−0.55** |
| calendar 2d | 17 | 5,467 d (to 2026-09-25) | 1.21 | 31.2 | 0.92 | 0.33 | −0.54 |
| band 4.8% — *prereg says* | 17 | 5,452 d | 1.16 | 17.6 | — | 0.66 | +0.17 |
| band 4.8% | 17 | 5,452 d (to 2026-09-03) | **1.16** | **17.6** | 1.00 | **0.66** | **+0.17** |
| band 4.8% | 17 | 5,467 d (to 2026-09-25) | 1.17 | 17.6 | 1.00 | 0.67 | +0.18 |

Truncated to the prereg's 5,452 sessions, **every figure matches to two
decimals**. So the panel fixes since 2026-09-06 did not move these figures.
Fifteen more sessions move them by at most 0.01.

**The default `band_frontier.py` output does differ, and the cause is the
universe.** The script reads the universe from the frozen spec, and v7
(2026-09-28, CEF trials 49–50) cut it from 17 to 13 names. NAD, NEA, NVG and NZF
were dropped as unshortable on Alpaca. Today's default run (13 names, price
returns, full sample to 2026-09-25) [V]:

| policy | gross SR | ann % | turn/yr | net@5 | net@15 | net@30 | flips? |
|---|---:|---:|---:|---:|---:|---:|---|
| calendar 2d | 0.94 | 4.89 | 20.0 | 0.75 | 0.36 | −0.21 | YES |
| calendar 5d | 0.65 | 3.41 | 11.7 | 0.54 | 0.31 | −0.02 | YES |
| band 4.8% (LIVE width) | 0.91 | 4.67 | 13.4 | 0.78 | 0.52 | +0.12 | no |
| band 9.6% | 0.77 | 3.96 | 8.1 | 0.69 | 0.53 | +0.30 | no |
| band 12.8% | 0.66 | 3.41 | 6.1 | 0.60 | 0.48 | +0.30 | no |

On the 13-name book, gross SR falls from 1.16 to 0.91 for the band, and turnover
falls from 17.6 to 13.4. The prereg's qualitative claims still hold on 13 names:

- At 30bp every calendar goes negative and bands of 4.8% or wider stay positive.
- At matched turnover the band beats the calendar. Calendar 1d at 29.9/yr earns
  1.05 / 0.18 (gross / net@15); band 0.2% at 28.6/yr earns 1.05 / 0.22.

One pairing in the script's own matched block now **breaks H2**. Calendar 5d
(11.7) against band 4.8% (13.4) is 13% apart. It was a near-exact match on 17
names, and the script's comment still says so. Calendar 2d (20.0) against
band 1.6% (21.6) is 8% apart. That is flagged here, not fixed: rewriting the
existing output was out of scope.

The frontier scores the **plain band**. The live policy also carries
`max_gross_stress` 1.80, which is not modelled in these rows. Its effect on the
13-name band is in `PREREG_ALPACA_V7_2026-09-28.md` §3b.

The 13-name full-sample figures here (gross 0.91, price returns, from 2005)
differ from that prereg's 1.16 (total returns, traded era from 2013-06-14 only).
These are two conventions and two windows, not a disagreement. Landmine 8 says
the pre-2013 years are flat.

---

## B. Slower policies — fit period only (2005-01-03 .. 2022-12-30, 4,531 sessions)

**The 2023+ holdout is sealed.** `fit_only()` truncates the targets and returns
*before* any policy runs, so no 2023+ number exists for these candidates; it was
never computed. The new widths (16 / 19.2 / 25.6%) extend the existing grid past
12.8% as a deliberate characterisation. Nothing was selected on P&L. Matched
partners were found by bisection on **turnover alone**.

Motivation: published CEF discount half-lives are 7.7–12 months [U: figure from
the task brief, not fetched or re-read for this note; monthly data, mostly equity
CEFs]. The 14.3-day half-life behind the live width is a different object: it
is the half-life of the **target weight**, not of the discount. So the published
figure does not map straight onto a band width. Hence the empirical check below.

### B1. Fit-period table, TOTAL returns (headline; the paper score convention)

| policy | era | gross SR | ann % | turn/yr | net@5 | net@15 | net@30 | flips? |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **band 4.8% (LIVE width)** | fit 2005–22 | **0.69** | 3.30 | 7.1 | 0.61 | 0.46 | 0.24 | no |
| | 2015–19 | 0.85 | 5.83 | 7.8 | 0.80 | 0.68 | 0.51 | no |
| | 2020–22 | 0.95 | 6.33 | 21.3 | 0.79 | 0.47 | −0.01 | YES |
| calendar 5d *(context)* | fit 2005–22 | 0.46 | 2.24 | 7.1 | 0.39 | 0.24 | 0.02 | no |
| calendar 10d *(context)* | fit 2005–22 | 0.36 | 1.75 | 5.1 | 0.31 | 0.20 | 0.04 | no |
| **calendar 21d (monthly)** | fit 2005–22 | **0.21** | 1.13 | 3.4 | 0.18 | 0.12 | 0.02 | no |
| | 2015–19 | 0.35 | 2.50 | 3.8 | 0.32 | 0.27 | 0.19 | no |
| | 2020–22 | 0.06 | 0.53 | 9.9 | 0.00 | −0.11 | −0.29 | YES |
| band 9.6% *(context, existing sweep)* | fit 2005–22 | 0.66 | 3.20 | 4.2 | 0.62 | 0.53 | 0.40 | no |
| band 12.8% *(context, existing sweep)* | fit 2005–22 | 0.53 | 2.58 | 3.1 | 0.50 | 0.43 | 0.34 | no |
| **band 16.0%** | fit 2005–22 | **0.33** | 1.55 | 2.3 | 0.31 | 0.26 | 0.18 | no |
| | 2015–19 | 0.51 | 3.17 | 2.8 | 0.49 | 0.44 | 0.37 | no |
| | 2020–22 | 0.44 | 3.37 | 6.5 | 0.40 | 0.32 | 0.19 | no |
| **band 19.2%** | fit 2005–22 | **0.15** | 0.68 | 1.7 | 0.13 | 0.09 | 0.03 | no |
| | 2015–19 | 0.40 | 2.36 | 2.2 | 0.38 | 0.34 | 0.29 | no |
| | 2020–22 | 0.01 | 0.10 | 4.7 | −0.02 | −0.08 | −0.18 | no (all ≤0) |
| **band 25.6%** | fit 2005–22 | **−0.14** | −0.58 | 1.0 | −0.15 | −0.17 | −0.21 | no (all <0) |
| | 2015–19 | 0.09 | 0.48 | 1.4 | 0.08 | 0.05 | 0.01 | no |
| | 2020–22 | −0.44 | −3.18 | 2.6 | −0.46 | −0.49 | −0.55 | no (all <0) |

Era turnover sd/mean over 2015–19 and 2020–22 (two eras only, a weak
statistic): live band 46.6%, calendar 21d 44.8%, band 16.0% 39.4%, band 19.2%
36.0%, band 25.6% 29.7%. Era rows for the context policies are in the script's
output.

Price returns (the frontier's convention), fit 2005–22 [V]:

| policy | gross SR | turn/yr | net@5 | net@15 | net@30 |
|---|---:|---:|---:|---:|---:|
| band 4.8% (LIVE width) | 0.68 | 7.1 | 0.60 | 0.46 | 0.24 |
| calendar 21d | 0.21 | 3.4 | 0.18 | 0.12 | 0.03 |
| band 16.0% | 0.29 | 2.3 | 0.26 | 0.22 | 0.14 |
| band 19.2% | 0.12 | 1.7 | 0.10 | 0.06 | 0.01 |
| band 25.6% | −0.05 | 1.0 | −0.06 | −0.08 | −0.12 |

The monthly calendar depends on its refresh phase. Across all 21 phases (fit
period, total returns):

| statistic | min | median | max |
|---|---:|---:|---:|
| gross SR | 0.17 | 0.26 | 0.35 |
| turn/yr | 3.31 | 3.57 | 3.67 |
| net@15 | 0.07 | 0.15 | 0.24 |
| net@30 | −0.03 | 0.05 | 0.13 |

So phase 0, the one shown in the tables, is not a lucky draw. Even the best phase
does not reach the live band.

### B2. H2 — turnover matching against the live band

The live band trades 7.1/yr on the fit period [V]. **No slower candidate falls
within 5% of it:**

| candidate | fit turn/yr | gap to live band | match? |
|---|---:|---:|---|
| calendar 5d *(context)* | 7.1 | −0.3% | MATCH |
| calendar 21d | 3.4 | −52.8% | no |
| band 16.0% | 2.3 | −67.3% | no |
| band 19.2% | 1.7 | −75.5% | no |
| band 25.6% | 1.0 | −85.6% | no |

Slower policies trade less by construction, so this was always going to be the
answer. The one fit-period match, calendar 5d, is not a slower policy, and it
loses to the band in every column: gross 0.46 vs 0.69, net@15 0.24 vs 0.46,
net@30 0.02 vs 0.24.

### B3. Class comparison at the slower policies' own turnover (fit 2005–22, TOTAL)

| candidate | gross SR | turn | net@5/15/30 | matched partner | gross SR | turn | net@5/15/30 |
|---|---:|---:|---|---|---:|---:|---|
| calendar 21d | 0.21 | 3.4 | 0.18 / 0.12 / 0.02 | band 11.99% | **0.58** | 3.4 | 0.54 / 0.48 / 0.37 |
| band 16.0% | **0.33** | 2.3 | 0.31 / 0.26 / 0.18 | calendar 48d | 0.20 | 2.3 | 0.18 / 0.13 / 0.07 |
| band 19.2% | 0.15 | 1.7 | 0.13 / 0.09 / 0.03 | calendar 91d | **0.36** | 1.8 | 0.34 / 0.31 / 0.26 |
| band 25.6% | −0.14 | 1.0 | −0.15 / −0.17 / −0.21 | calendar 217d | **0.35** | 1.0 | 0.34 / 0.33 / 0.30 |

At monthly turnover the band still beats the calendar by a wide margin, as it
does at faster turnovers. Past about 16%, bands stop working. A band that wide
trades only when a target has moved far from the holding, which in this book
means a flip of sign. It then holds a stale extreme. A very slow calendar at the
same turnover beats it. **Every policy at these turnovers is still well below
the live band** (gross 0.69). The ordering above holds under price returns too:
band 11.99% 0.49 vs calendar 21d 0.21; calendar 91d 0.31 vs band 19.2% 0.12.

---

## C. Verdict

1. **Reproduced, drift explained.** On the 17-name v6 universe and the
   prereg's 5,452 sessions, the harness returns the prereg table exactly
   (1.20 / 31.1 / 0.33 / −0.55 and 1.16 / 17.6 / 0.66 / +0.17) [V]. The default
   output differs because the spec's universe is now 13 names (v7). On 13 names
   the band is 0.91 / 13.4 / 0.52 / +0.12 over the full sample, and its
   qualitative advantages survive. The panels end 2026-09-25/28, not in 2026-10.
   Flag: the script's matched block now pairs calendar 5d with band 4.8% at a
   13% turnover gap. That breaks H2, and the comment says otherwise.

2. **Does a slower policy beat the live band at matched turnover on the fit
   period? No match.** No monthly calendar and no band wider than 12.8% comes
   within 5% of the live band's turnover. Without matching, the result is the
   same: every new candidate loses to the live band on the fit period, on gross
   and at 5, 15 and 30bp, under both return conventions. That holds across all
   21 phases of the monthly calendar. The only column where a slower candidate
   wins is one era: in 2020–22, band 16.0% makes net@30 0.19 against the live
   band's −0.01. That is a cost-grid edge case in one era, not a result.
   **The slower-policy question does not justify a /prereg.** Trial CEF #51 is
   not proposed, the counter is untouched, and no spec change is drafted.

3. **On the motivation.** The published 7.7–12-month half-lives [U] do not
   carry over to this book's band width. Measured on our credit panels, the
   monthly and very-wide policies throw away most of the gross edge.


## Caveats added on review (quant-reviewer, 2026-10-07)

- The "very slow calendar beats wide bands" comparison (section B3) uses calendar
  91d/217d at refresh phase 0 only; the phase spread was computed for 21d alone,
  and calendar 217d refreshes ~21 times in 18 years. Treat it as one draw.
- The era rows printed "(matched)" are matched on FIT-period turnover; within an
  era several pairs differ by ~14% or more (e.g. band 16.0% vs calendar 48d 2.8 vs
  3.2/yr in 2015-19), which breaks H2. They are context, not matched comparisons.
- The slower block's `flips?` column is sign(net@5) != sign(net@30), while main()
  uses net@30 < 0; band 19.2% in 2020-22 reads "no" under the former though every
  net is negative.
- None of this touches the verdict: no slower policy matches the live band's
  turnover, and every one loses to it on the fit period, gross and net.
