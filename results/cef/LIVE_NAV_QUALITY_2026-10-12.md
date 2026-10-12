# Live-book NAV and price panel quality — 2026-10-12

**What this is.** A data-quality check on the panels the live book decides
on, for the 13 names of `cef_discount.v7.20260928` (read through
`scripts/cef/spec.py`). It asks whether the two yfinance defects found on the
C4 equity families (`results/cef/CEF_FAMILIES_DATA_2026-10-12.md` §3) are in
the live panels too:

- **stale copies**: a NAV row that repeats yfinance's previous NAV while
  CEFConnect's NAV for that date moved;
- **re-based closes**: a close back-adjusted for an event, with a NAV that is
  not.

It then measures the footprint of what it finds on the book's decision dates.

**Zero trials. No counter moved. Nothing pre-registered.** No corrected panel
was built, and nothing was backtested against the live panel. No IC, P&L,
Sharpe or forward return was computed. The deployed book's holdings are
reconstructed with the canonical harness only to say which names a defect
touched. Nothing under `data/` was written.

**Reproduce:**

```bash
QUANTT_ENV_FILE=<abs path to config/.env> python3 scripts/data/live_nav_quality.py \
    --state-dir /Users/simonjarvis/quantt_state/cef        # add --refresh to re-fetch
```

- The run log is `results/cef/live_nav_quality/live_nav_quality_output.txt`.
  Sections `[0]`–`[5]` there are cited below.
- Aggregate tables are `results/cef/live_nav_quality/*_2026-10-12.csv`.
- Row-level rows and every fetched response are in
  `results/cef/live_nav_quality/_cache_live_nav/`, which is gitignored. CRSP is
  licensed, and its values never leave that directory.
- Tests: `scripts/data/tests/test_live_nav_quality.py`.
- Every figure below is **[V]**: measured on 2026-10-12 by that script.

## Sources and their last dates

| source | what | last date | read |
|---|---|---|---|
| `data/cef/cef_nav.parquet` (yfinance `X<TK>X`) | the live NAV panel, laptop copy, read-only | **2026-09-25** | 2026-10-12 |
| `data/cef/cef_prices.parquet` (yfinance) | the live price panel, laptop copy, read-only | **2026-09-28** | 2026-10-12 |
| CEFConnect `pricinghistory/{TK}/1Y` | daily price and NAV | 2025-10-13 → 2026-10-09 | 2026-10-12T22:47Z |
| CEFConnect `pricinghistory/{TK}/All` | weekly (Fridays) price and NAV | 1996-10-18 → 2026-10-09 | 2026-10-12T22:48Z |
| yfinance as served now | the live fetcher's own call (`history(period="max", auto_adjust=False)`) | prices 2026-10-12, NAV 2026-10-09 | 2026-10-12T22:51Z |
| CRSP `crsp_a_stock.dsf` through R2 | raw closing price `prc` | **2024-12-31** | 2026-10-12 |
| EDGAR, BIT (CIK 1562818) | 497AD 2025-08-06, 424B2 2025-08-20, 497AD 2025-09-10 | — | 2026-10-12 |
| laptop prod state `/Users/simonjarvis/quantt_state/cef` | each live session's `plan.json` and `orders.jsonl`; the collector's `data/<D>/report.json` | sessions 2026-09-29 → 2026-10-08 | read-only |

**What is not read.** The VM, prod since 2026-10-08, holds its own panels and
plans. It was not touched (task scope). Every live-period figure below covers
only the laptop's sessions.

On their 611 common (fund, date) rows, CEFConnect's `1Y` and `All` responses
agree on every NAV and every close.

---

## The answer

1. **The vendor archive's stale copies are in the live NAV panel**, in the
   same episodes as on the families. Counting weekly fund-days:
   - **201 of 649 (31%) in 2023**;
   - 59 of 650 in 2024;
   - 50 and 51 in 2019 and 2020;
   - 22 in 2022.

   On a stale copy, CEFConnect is the source that is right. yfinance's next
   change carries the move it skipped: slope 1.19 (s.e. 0.04), correlation
   0.82, n = 414. **There is no basis defect on any of the 13**, in NAV or in
   price, against CEFConnect or CRSP. Closes agree with CRSP on 65,630 of
   65,664 comparable rows.
2. **BIT 2025-08-19 is not a vendor re-basing.** The event is the record date
   (and ex-date) of a 1-for-3 transferable rights offering. The panel's BIT
   closes and NAVs are raw on both sides of it and equal CEFConnect and CRSP.
   - The raw discount does carry a real corporate-action transient. For the
     15 sessions until the dilution reached the NAV, it was too wide by a
     median **2.37pp** (1.6 of BIT's own sd).
   - Those rows left BIT's z-score window on **2026-09-10**, before the
     first live decision.
3. **Footprint, W4 fit window.** The deployed book's 1,047 decision dates
   (2013-06-21 → 2022-12-30) include 207 checkable Fridays.
   - 13 of those 207 had a stale copy on a name in the deployed set. That is
     48 of 1,367 checked eligible name-days, almost all in 2020 (27) and 2022
     (13).
   - Median discount error **0.33pp**; median z error 0.07; worst 1.22pp and
     0.68.
   - In both 2020 and 2022 the error has a sign: the stale NAV made funds
     look cheaper.
   - The 2023–24 episode lies outside W4's window, in the sealed holdout.
4. **The live paper period has a defect the archive does not show:
   stale copies at decision time.** Yahoo serves a NAV row dated D that
   carries D−1's NAV, and corrects it later.
   - The z each live session printed identifies the NAV it used. **On 28 of
     73 checkable name-days**, across 7 of 8 laptop decision dates, the
     session used NAV(D−1), not the final NAV(D).
   - **11 orders that reached the broker were sized on such a NAV:** 5 on
     the opening session, 1 on 2026-10-01 and 5 on 2026-10-07.
   - The z error is a median 0.10 and at most 0.26.
   - Because Yahoo corrects these rows later, neither the families check nor
     the backtest panel can see them.
5. **The capture needs a fix before the next decide; the history does not.**
   See §6. This is described here, not applied.

---

## 1. NAV: the live panel against CEFConnect (`[1]`)

**The panel equals yfinance as served today** (`[0]`): 66,593 of 66,595 NAV
rows and all 71,323 comparable closes. The two exceptions are the panel's last
NAV date, 2026-09-25:

- DSL: the panel has 11.11 (the 09-24 value); yfinance now has 11.10;
- PDI: the panel has 15.06; yfinance now has 15.10.

Both were captured on 2026-09-28 and corrected by Yahoo since. They are the
first sign of §5. Separately, **11 panel price rows are empty bars**, with a
NaN close: BIT, HYT and JFR on 2026-02-13; PCN, PDI, PDO, PFN, PHK and PTY on
2026-02-12; DSL on 2026-02-18 and 2026-03-18. yfinance now fills all 11. The
sleeve's `close > 0.5` filter drops those name-days.

**How a row is classified** (the script's docstring has the full ladder):

- **AGREE**: within half a cent.
- **STALE_COPY** (category a): yfinance repeats its own previous row while
  CEFConnect's value differs.
- **BASIS** (category b): the name-year's median yfinance/CEFConnect ratio is
  off 1 by more than 0.2%.
- **SHIFT_PREV, SHIFT_NEXT, OTHER** (category c): a one-day date shift
  either way, or a cent-level difference.

| window | compared | agree | stale copy (a) | basis (b) | shift / other (c) |
|---|---:|---:|---:|---:|---:|
| `All`, weekly, 1998–2026 | 13,189 | 12,553 | 415 | **0** | 55 / 31 / 135 |
| `1Y`, daily, 2025-10-13 → 2026-09-25 | 3,066 | 3,048 | 16 | **0** | 0 / 0 / 2 |

**Stale-copy share of weekly fund-days, by name and year.** Every year not
shown has at most two stale rows across all 13 names. The basis share is 0
for every name in every year.

| | 2014 | 2016 | 2019 | 2020 | 2022 | **2023** | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AWF | 2.0% | 2.0% | 5.9% | 8.2% | 2.0% | 18.0% | 10.0% | 2.1% | 0 |
| BIT | 0 | 0 | 15.7% | 10.2% | 2.0% | 32.0% | 6.0% | 0 | 0 |
| DSL | 12.0% | 0 | 9.8% | 10.2% | 2.0% | 18.0% | 2.0% | 0 | 2.9% |
| HYT | 0 | 0 | 3.9% | 14.3% | 2.0% | **50.0%** | 8.0% | 0 | 0 |
| JFR | 0 | 0 | 5.9% | 6.1% | 6.4% | 44.0% | 6.0% | 0 | 0 |
| MHD | 0 | 0 | 3.9% | 6.1% | 2.0% | 18.0% | 12.0% | 4.2% | 0 |
| MQY | 0 | 0 | 5.9% | 6.1% | 2.0% | 14.0% | 8.0% | 2.1% | 0 |
| PCN | 0 | 2.0% | 7.8% | 8.2% | 4.1% | 28.0% | 10.0% | 0 | 0 |
| PDI | 0 | 0 | 13.7% | 10.2% | 6.1% | 46.0% | 16.0% | 0 | 0 |
| PDO | — | — | — | — | 4.2% | 42.9% | 16.0% | 0 | 0 |
| PFN | 0 | 2.0% | 9.8% | 8.2% | 4.1% | 34.0% | 4.0% | 0 | 0 |
| PHK | 0 | 2.0% | 7.8% | 8.2% | 4.1% | 30.0% | 10.0% | 0 | 0 |
| PTY | 0 | 2.0% | 7.8% | 8.2% | 4.1% | 28.0% | 10.0% | 0 | 0 |
| **all 13** | 7 / 599 | 5 / 612 | 50 / 612 | 51 / 588 | 22 / 634 | **201 / 649** | 59 / 650 | 4 / 624 | 1 / 455 |

Each name has 47–51 weekly rows a year (35 in 2026 to date). Counts per cell
are in `nav_by_name_year_2026-10-12.csv`.

**The episodes are vendor-wide, not fund-specific** (`[1g]`). In 2023, stale
copies fell on 31 Fridays. On the median one, 8 of the 13 names were stale at
once, and on the worst, 11. The six PIMCO funds (PCN, PDI, PDO, PFN, PHK, PTY)
largely move together.

**Category (c) is small except in two years**:

- 2019: 51 rows (8.3%), including 19 one-day yfinance lags.
- 2021: 43 rows (7.2%), mostly BIT and HYT. These are 1–5 cent differences
  that are neither repeats nor shifts.

Nothing here says which source is right on those; they are left as OTHER.

**Who is right on a stale copy** (`[1f]`). Take each stale row. Regress
yfinance's next change (to the first later value that differs) on the move
CEFConnect shows that yfinance skipped:

- weekly: **slope 1.19 (s.e. 0.04), correlation 0.82, signs agree 86%**,
  n = 414;
- daily: slope 1.05, n = 15.

yfinance catches up by the amount CEFConnect said it had missed, so CEFConnect's
value is the true NAV. The slope above 1 is expected: the next change also
holds the next day's move, and these NAVs autocorrelate positively (families
note §5).

**The repeat share, the [U] flag in the families note §7.** Re-measured, the
share of panel NAV rows that repeat the previous row is:

| 2013–16 | 2017 | 2018 | 2019 | 2020 | 2021 | **2022** | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 16.3–17.8% | 22.0% | 20.6% | 26.0% | 16.8% | 22.4% | **10.1%** | 22.2% | 26.3% | 23.5% | 20.1% |

So the "rise from 10.1% to 22–26%" starts from an unusually low 2022. Repeats
are mostly genuine: 2025–26 sit at 20–24% with almost no stale copies. Only
in 2019 and 2023–24 is a large part of them vendor copies. **The repeat share
is a poor proxy. The CEFConnect comparison is the measurement.**

## 2. Prices (`[2]`, `[2c]`)

**Against CRSP's raw `prc`, to 2024-12-31** (65,668 panel rows):

- 65,667 map to a closed-end-fund permno (share code 14/44). The one that
  does not is the JFR 2004-03-25 pre-listing bar already in `docs/DATA.md` §4.
- **65,630 of 65,664 comparable closes agree within half a cent.**
- 34 rows differ:
  - 3 on AWF in the fractional-tick years (1994–2000), at most $0.125;
  - 12 in 2001 and 2004: PCN's and JFR's first weeks after listing, one day
    (2004-02-05) on HYT and MHD, and one AWF row;
  - 19 single days of 0.5–5 cents, 2008–2017.
- No name-year's median panel/CRSP ratio is off 1 by more than 0.2%: **no
  re-based closes**.
- Three MHD bars sit on CRSP no-trade days (1997–2001).
- From 2013 on: 37,101 of 37,110 agree; the 9 that do not are at most
  $0.03.

**Against CEFConnect's close**:

- daily: 3,068 of 3,068 agree;
- weekly: 13,622 of 13,687 agree. Every difference is before 2012, mostly
  AWF and MQY in 1998–2002. From 2013 on: 8,413 of 8,413.

**The price panel is clean.** The defects are in the NAV.

## 3. BIT, 2025-08-19 (`[3]`)

**The event** (EDGAR, BIT CIK 1562818; fetched and parsed by the script):

- **A transferable rights offering:** one right per share, three rights for
  one new share. 42,797,032 rights for 14,265,677 shares.
- Record date **2025-08-19**, which is also the ex-date under T+1.
- Expiration 2025-09-09; issuance scheduled for 2025-09-16.
- Subscription price $13.01, **"90% of the net asset value as of 9/9/2025"**
  (497AD of 2025-09-10). That NAV floor applied because 95% of the five-day
  average market price came out lower (497AD of 2025-08-06).

yfinance books it as a 1.029 "split" (`data/cef/cef_splits.parquet`; yfinance
today).

**Did yfinance re-base BIT's close and not its NAV? No.**

- Before the record date the panel's close equals CEFConnect's on 619 of 619
  weekly rows (median ratio 1.0000), and CRSP's raw `prc` on 2,980 of 2,980
  days to 2024-12-31.
- After it, 241 of 242 agree. The other row is an empty panel bar
  (2026-02-13, §1).
- yfinance as served today gives the identical, un-re-based closes: none
  differs.
- Unlike NRO, JRI and RIV on the families, yfinance has not applied this
  "split" to BIT's history.

**Is the discount biased? Before 2025-08-19: no.** Price and NAV are on one
basis. **From 2025-08-19 to 2025-09-09: yes, by a real corporate action, not
a vendor.**

- **The ex-date.** The close fell 14.47 → 13.84 on 2025-08-19. That is the
  right detaching. The NAV did not move (14.31 → 14.30), so the discount
  jumped from +1.12% to −3.22%.
- **The dilution.** It reached the NAV only after expiry: −2.42% on
  2025-09-10. The discount went from −4.22% to −1.06%.
- **Over the 15 rights-period sessions**, the raw discount was wider than a
  dilution-consistent one by a median **2.37pp**. That is 1.59 of BIT's own
  rolling sd (1.49pp).
- **CEFConnect shows the same jump.** No source can "correct" it; only an
  event mask could.
- **The z window.** Those 15 rows sat in BIT's 252-session window for
  decisions up to **2026-09-10**. They were out of it for every live paper
  decision (the first was asof 2026-09-28).
- **A docstring is wrong.** The harness's `split_factor` docstring
  (`scripts/cef/band_frontier.py`) says BIT's "NAV is unadjusted too and
  drops by the same factor, so price/NAV is unaffected". The NAV did not
  drop on the ex-date. That sentence is wrong and should be corrected by
  the harness's owner. The return-side handling (the 1.029 share
  multiplier) is a separate question, not examined here.

## 4. Footprint on the deployed book's decision dates (`[4]`)

**How it is built.**

- **Decision dates**: the harness's own. They are the sessions on which at
  least `min_names` (6) names have a z-score and 63-day ADV of at least
  `min_adv_usd`, from the first position on 2013-06-21. This reproduces W4's
  count of **1,047 decision dates before 2023**.
- **Held**: the name has a non-zero weight in
  `band_gross_capped(T, 0.048, 1.80)`.
- **Traded**: the held weight changed that day.
- **Checked**: only dates with a CEFConnect row can be checked. Those are
  Fridays until 2025-10-10, and every day after.
- **Size of a defect**: discount error = 100 · px · (1/NAV_yf − 1/NAV_cc) in
  pp. z error = that / the sleeve's own sd that day (`rolling(252).std().shift(1)`).

| era | decision dates | checked | dates with a stale copy on an eligible / held / traded name | eligible name-days: stale / checked | median abs discount error, pp | median (p90, max) abs z error |
|---|---:|---:|---|---:|---:|---|
| **W4 fit window** (2013-06-21 → 2022-12-30) | 1,047 | 207 | 13 / 13 / 6 | 48 / 1,367 (3.5%) | 0.33 | 0.07 (0.26, 0.68) |
| holdout years (2023-01-03 → 2026-09-25) | 798 | 348 | 30 / 32 / 28 | 112 / 3,552 (3.2%) | 0.20 | 0.06 (0.20, 0.56) |
| all | 1,845 | 555 | 43 / 45 / 34 | 160 / 4,919 | 0.22 | 0.06 (0.21, 0.68) |

**By year.** Stale copies on eligible name-days over checked eligible
name-days:

| 2014 | 2016 | 2020 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| 6 / 262 | 2 / 71 | 27 / 210 | 13 / 183 | **60 / 145** | 37 / 331 | 0 / 792 | 15 / 2,284 |

The other years are 0.

**The 2019 episode barely touches the book.** It had only 58 decision dates
that year, because the ADV filter left fewer than 6 names on most sessions.

**The error has a sign in the sell-offs.** The signed mean discount error is
**−0.27pp in 2020 and −0.48pp in 2022**. A NAV left over from before a fall
makes the panel discount wider, so the fund looks cheap and the book leans
long. In 2023–24 the mean is about zero.

**Unchecked dates are not counted, and are not extrapolated.** The only
upper bound is the yfinance repeat: on 468 of the 840 unchecked W4 decision
dates, an eligible name repeats its NAV. That bound is uninformative, because
genuine repeats are about a fifth of all rows (§1). Whether Fridays are
representative of other weekdays is [U].

**For the W4 baseline** (`results/cef/W4_ARTIFACTS_2026-10-11.md`, fit to
2022-12-30):

- **Inside its window**: the 2014, 2016, 2019–20 and 2022 episodes. In
  decision-date terms that is 13 of 207 checkable dates, 48 eligible
  name-days, concentrated in 2020 and 2022.
- **Outside its window**: the large 2023–24 episode (260 weekly fund-days;
  97 eligible name-days on 26 checked dates), in the sealed holdout.
- W4 read the vendor archive, so it could not see the decision-time defect
  of §5. Its §3 "stale NAV" is genuine NAV smoothing, measured by
  autocorrelation. This vendor defect is a different and episodic thing.

## 5. The live paper period: stale copies at decision time (`[5]`)

**Method.** The sleeve's z on date D is (disc − μ) / sd, with
disc = 100 (px − NAV) / NAV. Each laptop session saved the z it computed
(two decimals) and its close in `plan.json`.

- μ and sd are rebuilt from yfinance today, rolled exactly as the sleeve
  rolls them.
- Inverting gives the NAV interval the session must have used.
- That interval is compared with yfinance's final NAV(D), NAV(D−1) and
  CEFConnect's daily NAV(D).
- Acceptance tolerance: 0.002, derived in the script. Unambiguous rows sit
  within 0.001.
- Both candidates inside the interval would be "AMBIGUOUS". None was.

| asof D | plan written (UTC) | sent? | names with a z | **used NAV(D−1)** | of which submitted |
|---|---|---|---:|---:|---:|
| 2026-09-28 | 2026-09-29 14:33 | yes (opening) | 12 | **5** (PCN PDI PDO PFN PTY) | 5 |
| 2026-09-29 | 2026-09-30 02:00 | yes | 7 | 0 | 0 |
| 2026-09-30 | 2026-10-01 02:00 | yes | 6 | 1 (PDI) | 1 |
| 2026-10-01 | 2026-10-02 16:00 | no | 11 | **5** (BIT HYT PCN PDO PTY) | — |
| 2026-10-02 | 2026-10-05 13:30 | no | 4 | 2 (DSL PHK) | — |
| 2026-10-05 | 2026-10-06 19:00 | no (refused, buying power) | 13 | **8** | — |
| 2026-10-06 | 2026-10-07 02:00 | yes | 12 | **5** (PCN PDI PFN PHK PTY) | 5 |
| 2026-10-07 | 2026-10-08 03:00 | no (VM took over) | 8 | 2 (BIT HYT) | — |
| **total** | | | **73** | **28** | **11** |

**What the table shows.**

- The z error on those 28 name-days is a median 0.10 and at most 0.26.
- 7 of the 28 are one-cent cases, where NAV(D) and NAV(D−1) differ by
  $0.01. These are the weakest identifications.
- For the asof-2026-10-01 rows there is **a second, independent method**:
  the collector's own cross-check, run at 15:41Z on 2026-10-02, 20 minutes
  before that plan was written. It saw the same five names stale: BIT
  12.56/12.54, HYT 8.73/8.71, PCN 10.98/10.97, PDO 12.34/12.33 and PTY
  10.98/10.97. Those include two of the one-cent cases.
- Every session's fetch reported "every deployed name has a close and a NAV
  dated D". **The date was right and the value was the previous day's.**
- Yahoo has since corrected every one of these rows. Today's yfinance equals
  CEFConnect on every live-period date.

**Timing does not cure it.** Plans written 20–23 hours after the close still
used stale NAVs: 8 of 13 names at 15:00 ET on 2026-10-06 for D = 2026-10-05,
and 5 of 11 at noon on 2026-10-02 for D = 2026-10-01. `docs/RUNNER.md` decides
"once t's NAVs are in (they landed 21:21–21:51 ET on 2026-09-28)". What lands
then is a row dated t, not necessarily t's NAV. The PIMCO funds account for
21 of the 28.

**The collector did not catch it.** Its `nav_crosscheck` ran at about 21:40
ET. On 6 of 7 data days CEFConnect had no row for D at that time, so it
recorded 13 gaps and compared nothing. The one day it compared (run the next
morning), it flagged exactly these copies, report-only.

**The VM era is a gap.** From asof 2026-10-08 the VM decides on its own
panel, with the same fetcher and the same evening schedule. Whether its plans
used stale NAVs is **[U]**. The test that settles it is in §7.

## 6. Does the live panel need a fix before the next decide?

**Yes: the decide-time capture. No: the history.** This is described, not
applied. It is a live-path change, so it needs `/spec-change`-style proof and
a test, and the choice between the two remedies below is the team lead's.

1. **Check the NAV's value, not its date.** `fetch_daily.py --require-asof D`
   passes as soon as a row dated D exists. The fix is a stale-copy gate at
   decide time: for each deployed name whose yfinance NAV for D exactly
   equals its NAV for D−1, read CEFConnect's daily row for D.
   - If CEFConnect has D and differs by more than half a cent, the yfinance
     row is a stale copy. Either use CEFConnect's dated value through the
     existing logged fallback (`nav_fallback_log.csv`), or drop the name for
     the day.
   - If CEFConnect has no row for D, as on 6 of 7 laptop evenings, the
     value is unverified. Drop the name for the day, as `max_nav_age_bd`
     already does for a missing NAV, rather than trade it.
   - The cost of the drop rule: genuine repeats are about 20% of name-days
     (§1). In the live sample, 35 of 73 checkable name-days showed a repeat
     at decide time, and 28 of those were stale (`[5]`). A drop rule would
     often leave fewer than `min_names` (6) names. That is a reason to
     prefer the CEFConnect value where it exists, and to re-measure at run
     time how often the gate binds (H14).
   - Whether Yahoo's quote metadata (the NAV symbol's market time) can
     identify a carried-forward bar directly is **[U]**, and was not tested.
2. **Moving the decide later is not a fix.** NAVs were still stale at noon
   and 15:00 ET the next day (§5).
3. **The collector's cross-check should also flag "NAV(D) = NAV(D−1) and
   unverified"**, so that a gap is not a silent pass.
4. **The history needs no rewrite for the next decide.** Inside the current z
   window (2025-09-24 → 2026-09-25) the daily check finds 16 stale copies and
   2 other differences in 3,066 name-days, each at most 0.44pp. Spread over
   252 rows, they move μ by thousandths of a pp. The 11 empty bars of
   February and March 2026 are also inside the window; the sleeve drops those
   name-days. A refresh with a longer `--period` would refill them from
   yfinance. Panel writes are the team lead's call; this was not done.
5. **BIT needs nothing.** The panel is on one basis, and the rights-period
   rows are out of the window.

## 7. The sceptic's summary

**What was tested.** This is not an edge claim, so there is no D-verdict. The
claim tested is "a vendor artefact sits in the live data". **It survives**,
in two forms:

- **the archive form**: stale copies in 2019–20, 2022 and 2023–24, small for
  the deployed book before 2023;
- **the live form**: stale copies at decision time, about 38% of checkable
  name-days and 11 submitted orders on the laptop.

**The boring explanation the families note allowed.** It was "credit NAVs
genuinely repeat more". That is refuted for 2023 and 2024 by the CEFConnect
comparison and the tie-break regression. It is confirmed for 2025–26, where
repeats run at 20–24% with almost no stale copies.

**The one test that settles the open part (the VM era).** Run this script
with `--state-dir` pointed at a read-only copy of the VM's
`quantt_state/cef`. If its asof-2026-10-08 → 2026-10-12 plans show NAV(D−1)
on the PIMCO names, the gate in §6 is needed on the machine that trades.

**What could still overturn this.**

- The inversion assumes the sleeve's μ and sd at D equal today's rebuild. A
  panel row that differed at decide time by many cents on many days would
  break that. On every unambiguous row the residual was at most 0.001.
- The archive counts are a Friday sample.
- Survivorship does not apply. All 13 are alive, and the question is about
  their data, not a cross-section.

## 8. Gaps

- **The VM's panels, plans and collector reports**: not read (§5, §7).
- **Daily checks before 2025-10-13**: CEFConnect gives only weekly history,
  so stale copies on non-Fridays are not counted.
- **No third source for the 2021 cent-level differences** (OTHER) or the
  `SHIFT_PREV` rows: they are reported, not attributed.
  - A Nasdaq fund-quote endpoint was probed once (two requests) and then
    dropped, because its terms of use could not be confirmed.
  - The desk stopped using Cboe's delayed quotes on 2026-10-12 for the same
    kind of reason.
  - N-CSR and N-PORT give NAVs only at period ends (plan item 0.8).
- **Effect on P&L or IC: not measured**, by design. That would be a variant
  comparison.

*Code:* `scripts/data/live_nav_quality.py`. *Tests:* `scripts/data/tests/test_live_nav_quality.py`.
*Tables:* `results/cef/live_nav_quality/{nav_by_name_year,price_by_name_year,footprint,bit_event,live_period,live_period_by_date}_2026-10-12.csv`.
*Sources:* `docs/REFERENCES.md` §12h.
