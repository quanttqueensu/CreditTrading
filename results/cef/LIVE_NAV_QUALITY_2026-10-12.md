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

> **Corrected 2026-10-13** after an independent review (CONFIRMED WITH
> CORRECTIONS). The review reproduced 28 of 73, 7 of 8 dates, 11 orders,
> 201 of 649, slope 1.19 and 48 of 1,367; none of those moved. What was wrong
> is corrected in place below, each marked *corrected 2026-10-13*:
>
> 1. **§6's gate said "drop the name for the day … rather than trade it".**
>    In the sleeve a drop *is* a trade: a dropped name's target is zero, and
>    below `min_names` the whole book goes flat. Any NAV gate must keep current
>    shares for an unverified name, never target zero (§6).
> 2. **The Friday sample was called [U]; the note's own daily window answers
>    it.** 15 of the 16 daily stale copies fall on Thursdays, and the Friday
>    sample catches one (a capture artefact). The weekly figures are Friday
>    counts, not rates, and the W4 footprint could be off by a large factor
>    either way (§1, §4).
> 3. **"11 orders" understated the reach.** Every order of a session is sized
>    from the whole cross-section, so all 30 orders of the three sessions whose
>    plan held a stale NAV were sized from a set containing one. 11 is the
>    number in a name whose own NAV was stale (§5).
> 4. **"The live NAV panel" was the development checkout's copy.** The panel
>    the laptop traded on is now read too (§1, §5). It confirms the
>    2026-10-07 decision directly. "35 of 73 repeated at decide time" was an
>    inference, and is now labelled one. A gate keyed on a repeat misses a
>    stale value that is not a repeat (PDI 2026-09-25, §6).
> 5. **§5's μ and sd came from yfinance as served now**, which fills 12 empty
>    price bars the session's panel carried. They now come from the traded
>    panel. The verdicts are unchanged (28 stale, 38 final, 7 flat), but
>    "unambiguous rows sit within 0.001" was wrong: under the old rebuild the
>    largest accepted distance was 0.0019 (§5).
> 6. **"The collector ran at about 21:40 ET"** held on 4 of 7 days (§5).
> 7. **Minor.** "No basis defect" now cites row-level counts. The SHIFT_NEXT
>    count is what rules out "CEFConnect dated a day early" (§1). The run log
>    printed each disagreeing CRSP row's date beside its difference from a
>    public close. That made CRSP's price recoverable up to sign, so it no
>    longer does (§2). The verdict logic now has tests.

**Reproduce:**

```bash
QUANTT_ENV_FILE=<abs path to config/.env> python3 scripts/data/live_nav_quality.py \
    --state-dir /Users/simonjarvis/quantt_state/cef \
    --traded-panel-dir /Users/simonjarvis/prod/quantt-alpaca/data/cef   # add --refresh to re-fetch
```

- The run log is `results/cef/live_nav_quality/live_nav_quality_output.txt`.
  Sections `[0]`–`[5]` there are cited below.
- Aggregate tables are `results/cef/live_nav_quality/*_2026-10-12.csv`. They
  are stamped with the date of the network fetch they rest on, so the
  2026-10-13 re-run rewrote them in place.
- Row-level rows and every fetched response are in
  `results/cef/live_nav_quality/_cache_live_nav/`, which is gitignored. CRSP is
  licensed, and its values never leave that directory.
- Tests: `scripts/data/tests/test_live_nav_quality.py`.
- Every figure below is **[V]**. It was measured on 2026-10-12 by that script
  and re-run on 2026-10-13, after the corrections, from the same cached
  2026-10-12 fetches plus the traded panel. Nothing was re-fetched.

## Sources and their last dates

| source | what | last date | read |
|---|---|---|---|
| `data/cef/cef_nav.parquet` (yfinance `X<TK>X`) | the development checkout's NAV panel, read-only. *Corrected 2026-10-13:* this row said "the live NAV panel"; it is not the panel the laptop traded on (next rows) | **2026-09-25** | 2026-10-12 |
| `data/cef/cef_prices.parquet` (yfinance) | the development checkout's price panel, read-only | **2026-09-28** | 2026-10-12 |
| `/Users/simonjarvis/prod/quantt-alpaca/data/cef/cef_{nav,prices}.parquet` | **the panels the laptop traded on**, read-only. Last written 2026-10-07 23:00:18 ET by the asof-2026-10-07 decide run, whose plan was written one second later | **2026-10-07** | 2026-10-13 |
| CEFConnect `pricinghistory/{TK}/1Y` | daily price and NAV | 2025-10-13 → 2026-10-09 | 2026-10-12T22:47Z |
| CEFConnect `pricinghistory/{TK}/All` | weekly (Fridays) price and NAV | 1996-10-18 → 2026-10-09 | 2026-10-12T22:48Z |
| yfinance as served now | the live fetcher's own call (`history(period="max", auto_adjust=False)`) | prices 2026-10-12, NAV 2026-10-09 | 2026-10-12T22:51Z |
| CRSP `crsp_a_stock.dsf` through R2 | raw closing price `prc` | **2024-12-31** | 2026-10-12 |
| EDGAR, BIT (CIK 1562818) | 497AD 2025-08-06, 424B2 2025-08-20, 497AD 2025-09-10 | — | 2026-10-12 |
| laptop prod state `/Users/simonjarvis/quantt_state/cef` | each live session's `plan.json` and `orders.jsonl`; the collector's `data/<D>/report.json` | sessions 2026-09-29 → 2026-10-08 | read-only |

**What is not read.** The VM, prod since 2026-10-08, holds its own panels and
plans. It was not touched (task scope). Every live-period figure below covers
only the laptop's sessions.

**Which panel is which** (`[0b]`). `scripts/cef/fetch_daily.py` re-writes the
last 6 months on every run. So the traded panel's last date (2026-10-07) is
exactly what that evening's decide run read. Its older rows are what Yahoo
served at 23:00 ET on 2026-10-07. The history sections (§1–§4) still read the
development checkout's copy. The two agree on 66,593 of 66,595 common NAV rows
and on all 71,323 common closes. The two NAV exceptions are DSL and PDI on
2026-09-25 (§1).

On their 611 common (fund, date) rows, CEFConnect's `1Y` and `All` responses
agree on every NAV and every close.

---

## The answer

1. **The vendor archive's stale copies are in the live NAV panel**, in the
   same episodes as on the families. This was measured on the development
   checkout's copy, which equals the traded panel on every common NAV row but
   two (§1). Counting Friday fund-days (CEFConnect's weekly history is Fridays
   only):
   - **201 of 649 Fridays in 2023**;
   - 59 of 650 in 2024;
   - 50 and 51 in 2019 and 2020;
   - 22 in 2022.

   These are counts on a Friday sample, not rates. *Corrected 2026-10-13:*
   "201 of 649" carried "(31%)". In the one window with daily checks, 15 of
   the 16 stale copies fell on Thursdays (§1), so a Friday share does not
   estimate the share on other days.

   On a stale copy, CEFConnect is the source that is right. yfinance's next
   change carries the move it skipped: slope 1.19 (s.e. 0.04), correlation
   0.82, n = 414. **There is no basis defect on any of the 13**, in NAV or in
   price, against CEFConnect or CRSP. Row by row, NAVs agree within half a cent
   on 12,553 of 13,189 weekly and 3,048 of 3,066 daily rows; the rest are
   stale copies, one-day shifts and cent-level differences (§1). Closes agree
   with CRSP on 65,630 of 65,664 comparable rows.
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
   - These are Friday counts. Because the Friday sample is not representative
     of other weekdays, the footprint on all 1,047 dates could be off by a
     large factor in either direction (§4).
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
   - For the last date (asof 2026-10-07) the decide-time panel survives. It
     shows the same two stale names directly (§5).
   - **11 orders that reached the broker were in a name whose own NAV was
     stale:** 5 on the opening session, 1 on 2026-10-01 and 5 on 2026-10-07.
   - **All 30 orders of those three sessions** (13, 5 and 12) were sized from
     a cross-section that contained a stale NAV. The sleeve demeans and
     normalises z across every eligible name, so one stale NAV moves every
     order. *Corrected 2026-10-13:* this bullet said only "11 orders … were
     sized on such a NAV".
   - The z error is a median 0.10 and at most 0.26.
   - Because Yahoo corrects these rows later, neither the families check nor
     the backtest panel can see them.
5. **The capture needs a fix before the next decide; the history does not.**
   See §6. This is described here, not applied. Any such gate must keep an
   unverified name's current shares. In this sleeve, dropping a name targets
   it at zero, and dropping below 6 names flattens the book (*corrected
   2026-10-13*).

---

## 1. NAV: the live panel against CEFConnect (`[1]`, `[0b]`, `[1h]`–`[1j]`)

**The development checkout's panel equals yfinance as served today** (`[0]`):
66,593 of 66,595 NAV rows and all 71,323 comparable closes. The two exceptions
are the panel's last NAV date, 2026-09-25:

- DSL: the panel has 11.11 (the 09-24 value); yfinance now has 11.10;
- PDI: the panel has 15.06; yfinance now has 15.10.

Both were captured on 2026-09-28 and corrected by Yahoo since. They are the
first sign of §5. PDI's is not a repeat: §6 shows why that matters.
Separately, **11 panel price rows are empty bars**, with a NaN close: BIT, HYT
and JFR on 2026-02-13; PCN, PDI, PDO, PFN, PHK and PTY on 2026-02-12; DSL on
2026-02-18 and 2026-03-18. yfinance now fills all 11. The sleeve's
`close > 0.5` filter drops those name-days.

**The traded panel** (`[0b]`, added 2026-10-13) equals yfinance as served today
on 66,697 of 66,699 NAV rows and all 71,414 comparable closes. The two
exceptions are its last date, BIT and HYT on 2026-10-07, which §5 reads as
decide-time copies. It carries **12 empty bars**: the 11 above, plus AWF
2026-04-02, which the development checkout has filled.

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
| `All`, weekly (Fridays), 1998–2026 | 13,189 | 12,553 | 415 | **0** | 55 / 31 / 135 |
| `1Y`, daily, 2025-10-13 → 2026-09-25 | 3,066 | 3,048 | 16 | **0** | 0 / 0 / 2 |

**Stale copies on Fridays, by name and year** (`[1a]`). Each name has 47–51
Fridays a year (35 in 2026 to date). Every year not shown has at most two stale
rows across all 13 names. No row in any name-year is BASIS.

| | 2014 | 2016 | 2019 | 2020 | 2022 | **2023** | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AWF | 1 | 1 | 3 | 4 | 1 | 9 | 5 | 1 | 0 |
| BIT | 0 | 0 | 8 | 5 | 1 | 16 | 3 | 0 | 0 |
| DSL | 6 | 0 | 5 | 5 | 1 | 9 | 1 | 0 | 1 |
| HYT | 0 | 0 | 2 | 7 | 1 | **25** | 4 | 0 | 0 |
| JFR | 0 | 0 | 3 | 3 | 3 | 22 | 3 | 0 | 0 |
| MHD | 0 | 0 | 2 | 3 | 1 | 9 | 6 | 2 | 0 |
| MQY | 0 | 0 | 3 | 3 | 1 | 7 | 4 | 1 | 0 |
| PCN | 0 | 1 | 4 | 4 | 2 | 14 | 5 | 0 | 0 |
| PDI | 0 | 0 | 7 | 5 | 3 | 23 | 8 | 0 | 0 |
| PDO | — | — | — | — | 2 | 21 | 8 | 0 | 0 |
| PFN | 0 | 1 | 5 | 4 | 2 | 17 | 2 | 0 | 0 |
| PHK | 0 | 1 | 4 | 4 | 2 | 15 | 5 | 0 | 0 |
| PTY | 0 | 1 | 4 | 4 | 2 | 14 | 5 | 0 | 0 |
| **all 13** | 7 / 599 | 5 / 612 | 50 / 612 | 51 / 588 | 22 / 634 | **201 / 649** | 59 / 650 | 4 / 624 | 1 / 455 |

*Corrected 2026-10-13:* the cells were each name-year's stale count as a
percentage of its Fridays (HYT 2023 read "50.0%"). Those percentages are
shares of a Friday sample shown below to be unrepresentative. They are not
rates, so the cells are now counts. The percentages remain derivable from
`nav_by_name_year_2026-10-12.csv` (`stale_share`), which is a share of Fridays
only.

**The Friday sample is not representative** (`[1h]`, added 2026-10-13). The
2026-10-12 version left this as [U] (§4, §7), but the daily window answers it:

- In the daily window (2025-10-13 → 2026-09-25), 15 of the 16 stale copies in
  the development checkout's panel fell on Thursdays: 2026-06-25 (4 names),
  07-02 (5) and 09-24 (6).
- A Friday-only sample catches one, DSL 2026-09-25. That one is a capture
  artefact: yfinance as served today has corrected it, and has the other 15.
- So in this window a Friday sample saw none of the three vendor episodes. Three
  episode days are too few to say that stale copies favour Thursdays. They are
  enough to show that a Friday count cannot be scaled into a rate.
- Every weekly figure in this note is therefore a **Friday count**. The true
  number on all weekdays could be larger or smaller by a large factor.

**The episodes are vendor-wide, not fund-specific** (`[1g]`). In 2023, stale
copies fell on 31 Fridays. On the median one, 8 of the 13 names were stale at
once, and on the worst, 11. The six PIMCO funds (PCN, PDI, PDO, PFN, PHK, PTY)
largely move together.

**Category (c) is small except in two years**:

- 2019: 51 Friday rows, including 19 one-day yfinance lags.
- 2021: 43 Friday rows, mostly BIT and HYT. These are 1–5 cent differences
  that are neither repeats nor shifts.

Nothing here says which source is right on those; they are left as OTHER.

**Why "no basis defect" stands, row by row** (`[1j]`, added 2026-10-13). The
BASIS rung tests a name-year's *median* ratio. A defect on a minority of a
year's rows would pass that test, so the claim also rests on the rows:

- NAV agrees within half a cent on 12,553 of 13,189 Friday rows and 3,048 of
  3,066 daily rows.
- Of the rest:
  - Fridays: 415 stale copies, 86 one-day shifts and 135 OTHER (median
    |diff| 2 cents). From 2013, the 88 OTHER rows are at most 13 cents.
  - Daily: 16 stale copies and 2 OTHER.
- A share-basis difference would be a constant ratio across a run of rows. The
  three name-years with the largest share of non-stale disagreement are AWF
  1999 (15 rows, 39%), HYT 2021 (16, 35%) and BIT 2021 (14, 30%). Their mean
  differences are −1.0, −0.4 and +0.2 cents, with median |diff| 1–2.5 cents.
  Those are cent-level differences of both signs, not an offset.

**"CEFConnect dated a day early" is ruled out by SHIFT_NEXT.** If CEFConnect
dated each NAV a day early, its value would equal yfinance's next row on every
Friday the NAV moved: a SHIFT_NEXT row. In 2023, the stale-copy year,
SHIFT_NEXT occurs once in 649 Fridays, and 433 agree. Across all years it
peaks at 19, in 2019 (`[1b]`).

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
  - 12 in 2001–2007, at most $0.05: PCN in 2001 (its first year listed), and
    JFR, HYT, MHD and AWF in 2004;
  - 19 single days of 0.5–5 cents, 2008–2017 (10 in 2008–2012, 9 from 2013).
- No name-year's median panel/CRSP ratio is off 1 by more than 0.2%: **no
  re-based closes**. Row by row, the 34 are scattered single days, and no
  name-year has more than 5 (`[2c]`).
- Three MHD bars sit on CRSP no-trade days (1997–2001).
- From 2013 on: 37,101 of 37,110 agree; the 9 that do not are at most
  $0.03.
- *Corrected 2026-10-13:* the 2026-10-12 run log printed each disagreeing
  row's date beside |panel − CRSP|. With the public close, that gave CRSP's
  licensed price up to sign. `[2c]` now prints counts by ticker, year and
  category, and a maximum only over an era where at least 3 rows disagree.
  The dated rows stay in the gitignored cache. The earlier run log remains in
  git history.

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
| **W4 fit window** (2013-06-21 → 2022-12-30) | 1,047 | 207 (Fridays) | 13 / 13 / 6 | 48 / 1,367 | 0.33 | 0.07 (0.26, 0.68) |
| holdout years (2023-01-03 → 2026-09-25) | 798 | 348 (Fridays, then daily from 2025-10-13) | 30 / 32 / 28 | 112 / 3,552 | 0.20 | 0.06 (0.20, 0.56) |
| all | 1,845 | 555 | 43 / 45 / 34 | 160 / 4,919 | 0.22 | 0.06 (0.21, 0.68) |

*Corrected 2026-10-13:* the stale / checked cells carried "(3.5%)" and
"(3.2%)". Those were shares of a Friday sample (§1), not rates for the
decision dates, and they are withdrawn.

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
genuine repeats are about a fifth of all rows (§1).

**The Friday sample is shown to be unrepresentative** (§1, `[1h]`). This
replaces "whether Fridays are representative of other weekdays is [U]"
(*corrected 2026-10-13*). In the daily window a Friday sample missed all
three vendor episodes. **The W4 footprint (48 of 1,367 checked name-days; 13
of 207 checked dates) is therefore a Friday count.** Across all 1,047
decision dates it could be off by a large factor in either direction: larger
if episodes fall mostly off Fridays, smaller if the Fridays it caught were
the heavy days. Nothing here measures which.

**For the W4 baseline** (`results/cef/W4_ARTIFACTS_2026-10-11.md`, fit to
2022-12-30):

- **Inside its window**: the 2014, 2016, 2019–20 and 2022 episodes. In
  decision-date terms that is 13 of 207 checkable Fridays, 48 eligible
  name-days, concentrated in 2020 and 2022. These are Friday counts (above).
- **Outside its window**: the large 2023–24 episode (260 Friday fund-days;
  97 eligible name-days on 26 checked dates), in the sealed holdout.
- W4 read the vendor archive, so it could not see the decision-time defect
  of §5. Its §3 "stale NAV" is genuine NAV smoothing, measured by
  autocorrelation. This vendor defect is a different and episodic thing.

## 5. The live paper period: stale copies at decision time (`[5]`)

**Method.** The sleeve's z on date D is (disc − μ) / sd, with
disc = 100 (px − NAV) / NAV. Each laptop session saved the z it computed
(two decimals) and its close in `plan.json`.

- μ and sd are rebuilt from **the traded panel**, rolled exactly as the sleeve
  rolls them. *Corrected 2026-10-13:* the 2026-10-12 version rebuilt them from
  yfinance as served now. That fills the 12 empty bars the session's panel
  carried and the sleeve drops (§1), and it moved implied intervals by up to
  0.0029 (PTY 2026-09-28), more than the tolerance.
- Inverting gives the NAV interval the session must have used.
- That interval is compared with yfinance's final NAV(D), NAV(D−1) and
  CEFConnect's daily NAV(D).
- Acceptance tolerance: 0.002, fixed in the script before the review and not
  re-chosen. **Measured margins:** the largest accepted distance is 0.0006
  (AWF 2026-10-01). The nearest rejected candidate is 0.0039 (PDI 2026-09-30,
  whose final NAV differs from NAV(D−1) by one cent). *Corrected 2026-10-13:*
  this bullet said "Unambiguous rows sit within 0.001". Under the 2026-10-12
  rebuild the largest accepted distance was in fact 0.0019, inside the
  tolerance by a hair.
- Both candidates inside the interval would be "AMBIGUOUS". None was.
- The verdicts are the same under both rebuilds: 28 stale, 38 final, 7 where
  NAV(D) equals NAV(D−1) (flat), and 31 name-days with no z printed.

| asof D | plan written (UTC) | sent? | orders sent | names with a z | **used NAV(D−1)** | of which submitted |
|---|---|---|---:|---:|---:|---:|
| 2026-09-28 | 2026-09-29 14:33 | yes (opening) | 13 | 12 | **5** (PCN PDI PDO PFN PTY) | 5 |
| 2026-09-29 | 2026-09-30 02:00 | yes | 7 | 7 | 0 | 0 |
| 2026-09-30 | 2026-10-01 02:00 | yes | 5 | 6 | 1 (PDI) | 1 |
| 2026-10-01 | 2026-10-02 16:00 | no | — | 11 | **5** (BIT HYT PCN PDO PTY) | — |
| 2026-10-02 | 2026-10-05 13:30 | no | — | 4 | 2 (DSL PHK) | — |
| 2026-10-05 | 2026-10-06 19:00 | no (refused, buying power) | — | 13 | **8** | — |
| 2026-10-06 | 2026-10-07 02:00 | yes | 12 | 12 | **5** (PCN PDI PFN PHK PTY) | 5 |
| 2026-10-07 | 2026-10-08 03:00 | no (VM took over) | — | 8 | 2 (BIT HYT) | — |
| **total** | | | **37** | **73** | **28** | **11** |

"Orders sent" counts the `submit` events in each session's `orders.jsonl`.
The column was added 2026-10-13.

**What the table shows.**

- The z error on those 28 name-days is a median 0.10 and at most 0.26.
- **The orders it reached.** 11 orders went to the broker in a name whose own
  NAV was stale. But the sleeve sets each weight from the whole
  cross-section: w = −(z − mean z), normalised by Σ|w|, then the vol scalar
  and the min-weight re-neutralisation. A stale z therefore moves every
  eligible name's target. So **all 30 orders** sent on the three sessions
  whose plan held a stale NAV (13 + 5 + 12) were sized from a set that
  contained one. The fourth sent session (asof 2026-09-29, 7 orders) had no
  stale NAV among its 7 checkable names. Its other 6 names printed no z, so
  they cannot be checked either way. *Corrected 2026-10-13:* the note gave
  only the 11.
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
- **For asof 2026-10-07 the decide-time panel survives and is read directly**
  (`[0b]`, `[5]`, added 2026-10-13). The traded panel was last written at
  23:00:18 ET, by the run whose plan was written at 23:00:19.
  - Its 2026-10-07 row repeats 2026-10-06 for exactly two names: BIT
    12.62/12.62 (final and CEFConnect 12.60) and HYT 8.78/8.78 (final 8.77).
    No other name repeats, and every other name equals its final NAV.
  - z recomputed from that panel equals the printed z on 8 of 8 names with
    a z.
  - This is the inversion's verdict for that date, observed rather than
    inferred.
- For the other seven dates the decide-time values were overwritten by later
  runs, so the inversion is the only evidence.

**Timing does not cure it.** Plans written 20–23 hours after the close still
used stale NAVs: 8 of 13 names at 15:00 ET on 2026-10-06 for D = 2026-10-05,
and 5 of 11 at noon on 2026-10-02 for D = 2026-10-01. `docs/RUNNER.md` decides
"once t's NAVs are in (they landed 21:21–21:51 ET on 2026-09-28)". What lands
then is a row dated t, not necessarily t's NAV. The PIMCO funds account for
21 of the 28.

**The collector did not catch it.** Its `nav_crosscheck` ran at 21:40 ET on
the data day on 4 of 7 days (09-29, 09-30, 10-06, 10-07). It ran at 00:10 ET
the next day for 10-05, and at 09:40 ET on Saturday 10-03 for 10-02.

- On those 6 runs CEFConnect had no row for D, so the collector recorded 13
  gaps and compared nothing, even 17 hours after the 10-02 close.
- The one day it compared was 10-01, run at 11:41 ET on 10-02, when all 13
  rows were present. It flagged exactly these copies, report-only.
- *Corrected 2026-10-13:* this paragraph said the check "ran at about 21:40
  ET". The run log now prints each run's ET time (`[5]`, collector table).

**The VM era is a gap.** From asof 2026-10-08 the VM decides on its own
panel, with the same fetcher and the same evening schedule. Whether its plans
used stale NAVs is **[U]**. The test that settles it is in §7.

## 6. Does the live panel need a fix before the next decide?

**Yes: the decide-time capture. No: the history.** This is described, not
applied. It is a live-path change, so it needs `/spec-change`-style proof and
a test, and the choice between the two remedies below is the team lead's.

1. **Check the NAV's value, not its date.** `fetch_daily.py --require-asof D`
   passes as soon as a row dated D exists. The fix is a stale-copy gate at
   decide time.

   **What triggers it.** A deployed name is suspect when either:
   - (a) its yfinance NAV for D exactly equals its yfinance NAV for D−1 (a
     repeat); or
   - (b) its yfinance NAV for D equals CEFConnect's NAV for D−1 (added
     2026-10-13).

   Trigger (a) alone misses the case in §1. PDI, as captured on 2026-09-28,
   read 15.12 for 09-24 and 15.06 for 09-25:
   - yfinance's 09-24 row is itself an uncorrected archive copy of 09-23;
   - 15.06 is CEFConnect's 09-24 NAV;
   - the true 09-25 NAV is 15.10.

   That is D−1's value dated D with no repeat (`[1i]`: one such row in the
   development checkout's daily window, none in the traded panel or in
   yfinance today). Trigger (b) can add cases only where yfinance's own D−1
   row already disagrees with CEFConnect's; otherwise it coincides with (a).
   For a suspect name, read CEFConnect's daily row for D:
   - If CEFConnect has D and differs by more than half a cent, the yfinance
     row is a stale copy. Use CEFConnect's dated value through the existing
     logged fallback (`nav_fallback_log.csv`), or treat the name as
     unverified (below).
   - If CEFConnect has no row for D, the value is **unverified**. That was the
     case at every laptop collector run but one (§5).

   **What it does with an unverified name: keep its current shares, never
   target zero.** *Corrected 2026-10-13:* this item said "drop the name for
   the day, as `max_nav_age_bd` already does for a missing NAV, rather than
   trade it". In this book a drop *is* a trade, so the gate must not be built
   that way. Read on 2026-10-13:
   - In `src/deploy/sleeves/cef_discount.py`, a dropped name (as
     `max_nav_age_bd` drops one) never enters the cross-section, so its
     target weight is zero. The band then compares zero with what is held: a
     held name more than `band_width` (4.8%) from zero is sold or covered to
     the band edge.
   - If fewer than `min_names` (6) names remain, `cef_discount.py:467` sets
     all 13 targets FLAT.
   - `quantt/session/decide.py:243` (`target_shares`) turns FLAT into zero
     shares, so the session sends orders that close every position.
   - Nothing in `quantt/` refuses a full liquidation. Gate 8 (exposure) bounds
     gross and buying power, and a liquidation lowers both.

   On these evenings a drop rule would often have left fewer than 6 names.
   On 2026-10-05, 8 of 13 were stale. So "drop the name" would have
   liquidated the book on a data-quality flag. The two safe shapes already
   exist in the code:
   - **Hold in shares.** Emit the name's held quantity as a band HOLD does
     (`qty`, so the executor's diff is exactly zero), and leave its z out of
     the cross-section.
   - **Refuse the session.** Gate 5 (`gate_data` in `quantt/session/gate.py`)
     already refuses the whole send when any NAV is not dated D. A refusal
     sends nothing, so every position is kept.

   If fewer than `min_names` verified names remain, the gate must refuse, not
   flatten. Whichever shape is chosen, it needs a test that fails against a
   drop-to-zero gate.

   **What it costs.** Genuine repeats are about 20% of name-days (§1), so
   trigger (a) will bind often. In the live sample the inversion *infers* that
   on 35 of 73 checkable name-days the NAV the session used equalled
   yfinance's NAV(D−1): 28 stale and 7 genuinely flat (`[5]`). *Corrected
   2026-10-13:* the note said these "showed a repeat at decide time", as if
   observed. Only the 2026-10-07 decide-time panel survives to be read, and
   there 2 of 13 names repeated, both stale (§5). Prefer CEFConnect's dated
   value where it exists, and re-measure at run time how often the gate binds
   (H14).
   - Whether Yahoo's quote metadata (the NAV symbol's market time) can
     identify a carried-forward bar directly is **[U]**, and was not tested.
2. **Moving the decide later is not a fix.** NAVs were still stale at noon
   and 15:00 ET the next day (§5).
3. **The collector's cross-check should also flag "NAV(D) = NAV(D−1) and
   unverified"**, so that a gap is not a silent pass.
4. **The history needs no rewrite for the next decide.** Inside the current z
   window (2025-09-24 → 2026-09-25) the daily check finds 16 stale copies and
   2 other differences in 3,066 name-days, each at most 0.44pp. Spread over
   252 rows, they move μ by thousandths of a pp. The empty bars of
   February–April 2026 are also inside the window: 12 in the traded panel,
   11 in the development checkout (§1). The sleeve drops those name-days. A
   refresh with a longer `--period` would refill them from yfinance. That
   would move the implied intervals of §5 by up to 0.0029, which is to say
   it changes the sleeve's μ and sd: a live-data change, not a cosmetic
   one. Panel writes are the team lead's call; this was not done.
5. **BIT needs nothing.** The panel is on one basis, and the rights-period
   rows are out of the window.

## 7. The sceptic's summary

**What was tested.** This is not an edge claim, so there is no D-verdict. The
claim tested is "a vendor artefact sits in the live data". **It survives**,
in two forms:

- **the archive form**: stale copies in 2019–20, 2022 and 2023–24, small for
  the deployed book before 2023;
- **the live form**: stale copies at decision time on 28 of 73 checkable
  name-days on the laptop. 11 submitted orders were in a name whose own NAV
  was stale. All 30 orders of the three sessions concerned were sized from a
  cross-section that contained one (*corrected 2026-10-13*; this bullet said
  "11 submitted orders").

**The boring explanation the families note allowed.** It was "credit NAVs
genuinely repeat more". That is refuted for 2023 and 2024 by the CEFConnect
comparison and the tie-break regression. It is confirmed for 2025–26, where
repeats run at 20–24% with almost no stale copies.

**The one test that settles the open part (the VM era).** Run this script
with `--state-dir` pointed at a read-only copy of the VM's
`quantt_state/cef`, and `--traded-panel-dir` at a read-only copy of the VM's
`data/cef` taken before its next decide run. Without the second, the
inversion cannot be done (§5). If its asof-2026-10-08 → 2026-10-12 plans show
NAV(D−1) on the PIMCO names, the gate in §6 is needed on the machine that
trades. The panel's last date can also be read directly, as 2026-10-07 was.

**What could still overturn this.**

- The inversion assumes the sleeve's μ and sd at D equal their rebuild from
  the traded panel. That panel is the session's own, except for rows Yahoo
  corrected between the session and 2026-10-07. A row that differed at decide
  time by many cents on many days would break the assumption.
  - On every checkable row the accepted candidate sits within 0.0006 of its
    interval, and the nearest rejected one is 0.0039 away.
  - On 2026-10-07 the panel is exactly the session's: 8 of 8 printed z values
    reproduce.
  - *Corrected 2026-10-13:* this bullet said the residual "was at most
    0.001". With μ and sd rebuilt from yfinance as served now, it was 0.0019.
- The archive counts are a Friday sample, and the daily window shows that a
  Friday sample is not representative (§1). They are counts, not rates.
- Survivorship does not apply. All 13 are alive, and the question is about
  their data, not a cross-section.

## 8. Gaps

- **The VM's panels, plans and collector reports**: not read (§5, §7).
- **Daily checks before 2025-10-13**: CEFConnect gives only weekly history,
  so stale copies on non-Fridays are not counted. In the one daily window,
  15 of 16 fell off Fridays (§1). The size of what is missed before
  2025-10-13 is unknown in either direction.
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
*Sources:* `docs/REFERENCES.md` §12n.
