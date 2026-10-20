# Data guards: spike-and-revert bars, and Stage-0 flags that block P&L (2026-10-19)

**Zero trials. No counter moves.** These guards were built on the team lead's ruling
of 2026-10-19 ("build both zero-trial fixes"), after the C4 holdout review
(`results/cef/C4_RESULT_2026-10-14.md` §8).

**Amended 2026-10-20: a third guard (§7).** It covers a recorded split applied to a close
the vendor had already split-adjusted, the defect class §6 item 2 left unguarded.

**Reproduce:**

```bash
python3 -m pytest scripts/cef/tests/test_data_guards.py     # the guards on synthetic frames
python3 scripts/cef/data_guards.py scan                     # every hit in data/cef/ and data/cef_families/
python3 results/cef/data_guards/c4_callsites_noop.py        # C4's call sites, old vs guarded, hashed
python3 results/cef/data_guards/c4_holdout_under_rulings.py --cache <C4's gitignored _cache_c4>
python3 scripts/cef/data_guards.py scan-splits              # §7: every recorded split, labelled by basis
python3 results/cef/data_guards/split_basis_callsites.py    # §7: every split call site, old vs guarded, hashed
```

The outputs are next to the scripts in `results/cef/data_guards/`. Every figure
below is [V] from those runs on 2026-10-19 unless it says otherwise.

## 1. Why

- **The defect:** in `data/cef_families/cef_prices.parquet`, IGR's bars for
  2026-07-29, 08-04, 08-07 and 08-11 are on the post-split basis (about 14.2).
  The series around them is raw and pre-split (about 4.7). They come ahead of
  IGR's 1:3 reverse split of 2026-09-08, and the NAV is flat across them.
- **The cost:** C4's holdout booked each bar as +200% and then −66.7%. That cost
  −10.87% of capital.
- **Two failures let it through:**
  1. Nothing on the return path looked at the bars.
  2. Stage 0 flagged all eight rows (Q5) on 2026-10-14, but nothing made the
     trial wait for anyone to rule on the flags.
- **One guard for each failure:**
  - the spike-and-revert guard raises on such bars;
  - the Stage-0 block stops P&L until every flag has a ruling.
- **Neither guard alters a number on its own.**

## 2. Guard 1: split-like spike-and-revert (`scripts/cef/data_guards.py`)

**What it scans.** `guard_closes` runs before `yf_total_returns`
(`scripts/cef/c4_families.py`) forms any return. It looks at the funds of the
call, on each fund's own consecutive bars. It reads the split-corrected close
C·K, where K is the product of the actions file's share-count multipliers, so a
recorded split is not a jump.

| condition | rule |
|---|---|
| split-like jump | \|Δln C\| within τ of ln m, for an integer m ≥ 2 (a factor m, or 1/m) |
| the NAV did not make it | \|Δln NAV − Δln C\| > τ over the same two bars. Where the NAV lacks either bar, the price alone decides |
| it reverts | within 5 sessions: an opposite split-like step that brings the close back within τ of its level before the jump |
| it raises | on every such bar whose run touches the call's date window, naming each one as (ticker, date, ratio, factor, revert date, NAV ratio) |

**τ = ln(1.15) = 0.140, derived rather than swept.**
- **The model:** a bar on the wrong basis is the true print × f, so its booked
  ratio is f × (1 + the fund's genuine one-day move).
- **The bound on that move:** the desk's own outlier line, P2's Q5 (\|r\| > 15%),
  which C4's pre-registration §4.5 also uses. A test pins the two as equal.
- **Two checks, neither of which chose τ:**
  - τ < ln(3/2)/2, so the bands around 2 and 3 do not overlap;
  - τ < ln 2, so a ratio of 1 is never split-like.

**The 5-session window is a choice, stated as one** (one trading week).
- A longer wrong-basis run is reported as "unreverted" and not raised. A
  genuine split that nobody recorded looks the same from the price alone.
- **The rule sits on a plateau.** In the families panel the hits are 4 at τ/2,
  at τ, at W = 1 and at W = 21. They are 11 at 2τ, which adds crash-and-rebound
  days (KYN and TYG in 2020, DXYZ in 2024, VCX in 2026). These counts were
  computed after the choice and decided nothing.

**The override is a recorded rulings file** (`load_bar_rulings`).
- **The file:** a JSON that names who ruled, when, and where it is recorded,
  with one entry per bar: ticker, first and last bar, factor, treatment and
  reason.
- **The treatments:**
  - `rebase` divides the close by the factor. That is exact when the vendor's
    bar is the true print × the split ratio.
  - `book_as_is` books the close unchanged.
- **It also raises when:**
  - a ruling's factor or run disagrees with the scan;
  - a ruling inside the window matches no bar, because the data changed under
    it;
  - a rebased close is the prior close of an ex-date (the yield reads that close
    from the price file);
  - a treated bar still spikes after the treatment.
- **With no bar in range, the output is the old formula's, bit for bit.**

## 3. Guard 2: Stage-0 flags block P&L (`require_stage0_rulings`)

- **What it does:** a trial script calls it before it forms any P&L, in the fit
  or the holdout.
- **When it refuses** (naming every flag concerned):
  - while any Stage-0 flag lacks a row in the trial's rulings CSV (the flag's
    keys, then `ruling`, `ruled_by`, `ruled_on`);
  - when a row has an empty field;
  - when a key is ruled twice, or the keys do not identify each flag uniquely;
  - when a ruling matches no flag.
- **Zero flags need no file.**
- **`stage0_rulings_template`** writes the blank form, and never over a rulings
  file.
- **The skill:** `.claude/skills/prereg/SKILL.md` §4b now requires every
  pre-registration to declare its flag table, its keys, its rulings file and
  this block.

**Not wired into C4 or C5:** wiring would change what their scripts do.
- **C4:** its committed Stage 0 (`c4_stage0_flags_2026-10-14.csv`) carries 5,130
  Q2–Q7 flags with no recorded ruling. Only the 12 Q1 rows are ruled, and those
  in code. Wired in, the block would make C4's fit and `--rehearse` refuse.
  (C4's flags need the key `check, ticker, date, source`, because Q3 flags one
  day from two sources.)
- **C5:** its 17 amended Stage-0 flags have no ruling column, and C5 was killed
  at the fit.
- **No ruling was made on anyone's behalf.** A test shows the block refusing C4's
  committed flags, naming IGR's Q5 rows.

## 4. Hits in the panels (`scan_output_2026-10-19.txt`, `scan_hits_2026-10-19.csv`)

| panel | last date | bars | hits | unreverted (reported only) |
|---|---|---:|---:|---:|
| `data/cef/cef_prices.parquet` (the live book's) | 2026-10-15 | 267,879 | **0** | 0 |
| `data/cef_families/cef_prices.parquet` (yfinance) | 2026-10-09 | 925,342 | **4: the four IGR bars** | 16 |
| `data/cef_families/cef_nav_cefconnect.parquet`, `close_cc` | 2026-10-09 | 187,154 | 7 | 22 |
| `data/cef_families/cef_prices_crsp.parquet` (licensed: counts only) | 2024-12-31 | 921,217 | 2 (1932, 2001) | 27 |

**The four IGR bars**, all single bars on factor 3:

| bar | ratio | reverts on | NAV ratio |
|---|---:|---|---:|
| 2026-07-29 | 3.000 | 07-30 | 1.000 |
| 2026-08-04 | 3.006 | 08-05 | 1.000 |
| 2026-08-07 | 3.019 | 08-10 | 1.007 |
| 2026-08-11 | 2.981 | 08-12 | 0.989 |

**Nothing else in either yfinance panel hits.**

**The CEFConnect hits are leads, not findings.** That history is sampled weekly
(the median gap is 7 days) and τ is derived for one-day moves.
- **CRF, 6 hits (2001–02):** factor 2 on a flat NAV, with one-week reverts.
- **FLC, 2008-10-10:** factor 1/2, with the NAV −12.6%. This is probably the
  October 2008 crash and rebound [U].

**Neither CRSP-built hit is in any window a committed result reads** (both are
before 2005).

**What the "unreverted" list is.** It contains:
- March 2020 crash days, which are genuine;
- DXYZ's first weeks of trading in 2024;
- recorded split dates on which the close was already split-adjusted
  (§6, item 2).

## 5. Committed results this touches

**The scope.** Every caller of `yf_total_returns` (grep, 2026-10-19):
- C4's three call sites;
- the review's `repro.py`.

`corrected.py` and the other review scripts call `band_frontier.total_returns`
directly, so they are untouched.

| call | without a ruling | with its ruling: old vs guarded (sha256 of `hash_pandas_object`) |
|---|---|---|
| C4 Stage 0, `primary_returns` (105 funds, 2005-01-03 → 2026-09-30) | **raises** on the four IGR bars | 8 IGR cells differ (07-29 … 08-12); with them masked, **identical** |
| C4 fit, R-yf row (105 funds, fit window) | no bar in range | **identical**; the row rebuilt = committed 1.131 / 0.214 (to 1e-12) |
| C4 holdout, `assemble`: ruled, uncorrected and R-ADX actions (81 funds) | **raises** | 8 IGR cells differ; masked, **identical**; the ruled actions equal the committed cache |
| `holdout_review_2026-10-18/repro.py` | **raises** | given `repro_bar_rulings.json` (`book_as_is`): **max \|ΔP\| = 0** against the committed holdout P&L; SR 0.725 |

**C4's ruling** is `results/cef/c4/c4_bar_rulings_2026-10-19.json`.
- **What it records:** the corrected book is trial 52's holdout verdict (team
  lead, 2026-10-19), so the four bars are rebased (close ÷ 3).
- **Why rebasing is the review's correction:** each bar equals Alpaca's
  split-adjusted close, and the quotient equals Alpaca's raw close to within
  $4e-8.
- **Run through the holdout's assembly** (`c4_holdout_under_rulings.py`), the
  ruling gives **SR 1.434; net 0.999 / +0.130 / −1.174** at 5 / 15 / 30bp; turnover
  49.2. That is §8's corrected verdict to every quoted decimal.
- **The four IGR returns** match the review's substitution of Alpaca raw bars to
  8e-9.

**What is not recomputed:**
- **The committed holdout files are not recomputed.** The holdout is opened once,
  and its marker makes a second run refuse.
- **C4's Stage 0 was not re-run here:** it needs the gitignored CRSP cache and
  would rewrite the 2026-10-14 records. What a re-run would change [inferred
  from the hash proof; not run]:
  - IGR's eight Q5 rows would no longer be flagged;
  - IGR's robust-z Q5 flags after 2026-07-29 could move as well, because their
    252-session median and MAD included the eight bad returns;
  - Q6 (to 2024) and Q7 (the seam) read no changed cell.
- **`--rehearse` is unchanged.** Its P&L ends 2022-12-30, and the guarded
  returns differ only in 2026 cells.

**`repro_bar_rulings.json` is not a ruling that the bars are genuine.** It
exists so that the reproduction keeps reproducing what was committed.

## 6. Open, for the team lead

1. **The signal leg is not guarded.** `build_targets` reads the same panel, and
   this guard polices only `yf_total_returns`. On IGR, correcting only the
   returns reproduces the verdict to every decimal quoted, even though the
   review also rebuilt the signal on the corrected panel. So the signal-side
   correction changed nothing visible at that precision. That is measured for
   this case only.
2. **A second defect class is not guarded.** *Guarded since 2026-10-20 (§7), on
   the team lead's word of 2026-10-19; the text below is kept as it was written.*
   It is a recorded split applied to a
   close that yfinance had already split-adjusted, so the formula books k twice:
   - **Where:** in the fit window, BTO 2008-12-30, TYG 2020-05-01, NXG 2020-06-15
     and EMO 2020-07-28 book −74.7% to −80.3%.
   - **Evidence [V, two sources]:** on each date CRSP's raw print steps by 1/k,
     and yfinance's close does not.
   - **Why this guard misses it:** the families NAV is adjusted the same way,
     and nothing reverts.
   - **Effect:** only C4's report-only R-yf row moves, from 1.131 to 1.130
     (net@15 0.214 → 0.212). The CRSP primary return is untouched.
   - **The holdout's yfinance leg has no such case** on C4's funds. Its only
     recorded splits are UTF 2025-09-22 and IGR 2026-09-08. UTF's yfinance close
     there equals Alpaca's raw close, and IGR is filled from Alpaca.
   - **A proposed check:** on a recorded split date, the raw close ratio must be
     near 1/k. It is not built: the bars it would raise on in C4's fit window
     need rulings first.

## 7. Guard 3: a recorded split on an already-adjusted close (added 2026-10-20)

**Zero trials. No counter moves.** Built on the team lead's word of 2026-10-19 ("Yes,
tomorrow") to §6 item 2.

**Reproduce:** `python3 scripts/cef/data_guards.py scan-splits` (the hits),
`python3 results/cef/data_guards/split_basis_callsites.py` (the call sites, hashed) and
section (c) of `scripts/cef/tests/test_data_guards.py`.
- The outputs are `split_basis_scan_2026-10-20.txt` / `.csv` and
  `split_basis_callsites_output_2026-10-20.txt`, in `results/cef/data_guards/`.
- Every figure below is [V] from those runs on 2026-10-20.
- The panels end on these dates: `data/cef/` 2026-10-15; the families yfinance
  close and NAV 2026-10-09; the CRSP-built close 2024-12-31.

### 7.1 The rule (`guard_split_basis`, `scripts/cef/data_guards.py`)

**Where it runs.**
- **`band_frontier.total_returns`:** on every cell where a recorded split factor
  k ≠ 1 multiplies a finite raw one-step return r. These are exactly the cells
  the formula changes. This one call covers every `total_returns` caller, i.e.
  the live panel's default and C4's `yf_total_returns`.
- **C4's NAV catch-up:** it applies `split_factor` to the families NAV directly,
  and so calls the guard with `series="nav"`.
- **C5's `F.k`:** it reads the same `split_factor` on the live panel. Its
  `total_returns` call is guarded, and the live panel has no decidable split.

**The four readings,** with x = ln(1 + r) and τ = ln 1.15:

| reading | condition | what happens |
|---|---|---|
| raw | \|x + ln k\| ≤ τ | k is right; nothing |
| **adjusted** | \|ln k\| > 2τ and \|x\| ≤ τ | **raises** `SplitBasisError`, naming (ticker, ex-date, factor) |
| neither | \|ln k\| > 2τ, and neither condition above holds | reported by the scan; not raised |
| undecidable | \|ln k\| ≤ 2τ | reported by the scan; not raised: the guard has no power here |

**The tolerance is derived, not swept.**
- **τ is the spike guard's** (§2), not re-chosen. A test pins it to Q5's line.
- **Why 2τ:**
  - A raw close reads x = −ln k + e. An adjusted one reads x = e. Here e is the
    fund's genuine move, with |e| ≤ τ.
  - The two readings cannot both hold iff |ln k| > 2τ, i.e. iff k lies outside
    [0.756, 1.3225]. That is every reverse split, and every forward split of
    4:3 or more.
  - Below that line the price cannot tell the two bases apart. So the guard
    labels the cell and does not raise.
- **Why "neither" is not raised:** a step that fits neither basis is not this
  defect. Examples are a split recorded on the wrong day, or a day beyond the
  desk's line. The guard was not asked to judge it.

**The override** is a split rulings file (`load_split_rulings`).
- **The file:** who ruled, when and where it is recorded. It has one entry per
  (ticker, ex-date, series), with the factor the ruling was made on.
- **The treatments:**
  - `drop_split` sets k = 1 on the cell;
  - `book_as_is` applies k as recorded, for a script that reproduces a committed
    computation.
- **It also raises when:**
  - the ruling's factor is not the one the frame applies;
  - the ruled cell no longer reads `adjusted` (the data changed under it);
  - the ruling is for the other series (a NAV ruling does not cover a close);
  - the file is malformed.
- **With no hit and no `drop_split`,** the guard hands back the same k object.
  The output is then the old formula's, bit for bit.

### 7.2 Hits (`split_basis_scan_2026-10-20.txt`)

| panel | where it is read | splits applied | **adjusted** | raw | neither | undecidable |
|---|---|---:|---:|---:|---:|---:|
| `data/cef/cef_prices.parquet` (live) | every default `total_returns(R)` | 1 | **0** | 0 | 0 | 1 (BIT 2025-08-19, k 1.029) |
| `data/cef_families/cef_prices.parquet` (yfinance) | C4's `yf_total_returns` | 44 | **24** | 0 | 0 | 20 |
| `data/cef_families/cef_nav.parquet` | C4's NAV catch-up | 33 | **13** | 3 | 0 | 17 |
| `cef_nav_cefconnect.parquet` `close_cc` (weekly: leads) | not read with k | 38 | 16 | 1 | 3 | 18 |
| `cef_prices_crsp.parquet` (licensed: counts only) | not read with k | 34 | 0 | 21 | 0 | 13 |

**The four names are found.** All four have no step on the ex-date, and the guard
raises on each:

| name | ex-date | factor | raw ratio |
|---|---|---|---:|
| BTO | 2008-12-30 | 1/4 | 1.013 |
| TYG | 2020-05-01 | 1/4 | 0.931 |
| NXG | 2020-06-15 | 1/4 | 1.005 |
| EMO | 2020-07-28 | 1/5 | 0.985 |

**The families yfinance close carries every decidable split recorded against it:
24 of 24, and none reads raw.**
- **The second source:**
  - 21 of the 24 fall in the CRSP span. CRSP's print reads `raw` on all 21,
    including the four.
  - The other three (IAF 2025-10-23, AWP 2026-02-09, HERZ 2026-02-09) come after
    CRSP ends.
  - On IAF and AWP the families NAV steps by 1/k (raw) while the close does not.
    So a fund's close and NAV can sit on different bases, and a ruling names its
    series.
- **The other 20 touch no committed computation.** Each is either outside C4's
  pool or before 2005. The widest C4 call raises on exactly the four; it is
  Stage 0, over the 105-fund pool from 2005-01-03.
- **IGR 2026-09-08 has no yfinance return** (C4 fills its 09-08/09 from Alpaca), so
  k multiplies nothing there. This is reported only.

**The blind spot is real, and sized.**
- **What CRSP shows:** of the 13 undecidable splits with a CRSP return on the same
  day, all 13 read adjusted in yfinance. Each time, the gap between the two
  sources' steps is nearer ln k than 0. So the formula books those factors
  (k from 1.008 to 1.1) twice, and this guard cannot see it.
- **Where it touches C4:** among C4's 74 in the fit window, it is GRX 2013-06-13
  and 2014-05-30. Removing k there as well leaves the R-yf row at 1.1302 to four
  decimals.

**The CEFConnect rows are leads, not findings** (weekly; τ is derived for one-day
moves). Its three "neither" rows (BTO 1997, TYG 2020, SRV 2020) span a week.

### 7.3 Committed results this touches (`split_basis_callsites_output_2026-10-20.txt`)

| call | without a split ruling | under `c4_split_rulings_2026-10-20.json` (book_as_is): old vs guarded | under `drop_split` (not ruled) |
|---|---|---|---|
| live `total_returns(R)`, `build_targets()` default and `min_adv=0` | no hit (BIT undecidable) | **identical**, with no rulings file | — |
| C4 Stage 0 `primary_returns`, pool | **raises**: the four | **identical** (`692f4f9ad4221927`, §5's guarded hash) | the four cells |
| C4 fit, R-yf row, pool | **raises**: the four | **identical**; the row = committed 1.131 / 0.214 to 1e-12 | gross SR 1.1302; net 0.824 / 0.212 / −0.705 |
| C4 holdout `assemble` ×3 (81 funds) | **raises**: BTO, NXG, EMO | **identical** (`aa0bb2b9…`, `230a2be0…`, `499bafc0…`) | three cells, all in 2008–2020; the yfinance leg the holdout keeps (from 2025-01-02) is identical |
| C4 fit, NAV catch-up | **raises**: BTO, EMO (NAV) | the guard returns k itself; slope = committed +0.6703bp (t 0.774, n 2062) to 1e-12 | the same, to 1e-12 |

**The defaults, hashed in fresh processes before (392ce57) and after.** Each value
below is a sha256 of `pd.util.hash_pandas_object`, and each is **identical**.
These hashes were printed in this session and are not committed; the committed
script re-proves the `total_returns` rows in-process.

| default output | before = after |
|---|---|
| `build_targets()` T | `e2c033d6…432b` |
| `build_targets()` R | `def7c0a1…0658` |
| `band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)` | `018ecbf9…7e90a` |
| `total_returns(R)` | `56b2e6ae…a37e` |
| `evaluate(H, total_returns(R))` P&L | `50c4f805…034d` |
| the same five at `min_adv=0.0` | `3064d905…`, `def7c0a1…`, `a0336e67…`, `56b2e6ae…`, `6e3169d7…` |

**The two committed 2026-10-19 scripts that run C4's paths from this tree** are
`c4_callsites_noop.py` and `c4_holdout_under_rulings.py --cache <trial-c4's
_cache_c4>`.
- **What changed in them:** they now pass `SPLIT_RULINGS`.
- **The check:** both were re-run on 2026-10-20, and both output files are byte
  for byte as committed.
- **The review's scripts are untouched.** `holdout_review_2026-10-18/repro.py`
  and `corrected.py` import the trial-c4 worktree's code.

**`c4_split_rulings_2026-10-20.json` is not a ruling that the four returns are
genuine.**
- **Why it is book_as_is:** the team lead asked that C4's committed paths
  reproduce exactly.
- **The correction is `drop_split`.** Nobody has ruled on it. It would move only
  the report-only R-yf row, from 1.131 to 1.130.

### 7.4 Tests (`scripts/cef/tests/test_data_guards.py`, section c)

- **What they check:**
  - an already-adjusted close raises at `total_returns`, naming (A, ex-date,
    factor 1/4);
  - a raw close with a 1:4 reverse split or a 2-for-1 does not raise, and is the
    old formula bit for bit;
  - `drop_split` changes only the ruled cell, and `book_as_is` reproduces the old
    formula;
  - a ruling with the wrong factor, the wrong series or stale data raises, and so
    does a malformed file;
  - the decidable line is 2τ: k = 1.029, 1.3 and 1/1.3 are undecidable, and 4/3,
    1.5 and 1/3 are raised;
  - "neither", and a split on a day with no return, are not raised;
  - C4's `yf_total_returns` raises on BTO's shape and passes with a ruling;
  - the committed C4 rulings name the four funds.
- **The test that failed against the old code:**
  `test_total_returns_raises_on_a_split_the_close_already_carries`. It was checked
  on 2026-10-20 with only `band_frontier.py` reverted to 392ce57. The result was
  "DID NOT RAISE": the old code booked −75%.

### 7.5 Open, for the team lead

1. **Rule on the four closes and the two NAV cells.** `drop_split` is the
   correction. Measured above, it moves no committed number except the
   report-only R-yf row.
2. **The fix belongs in the fetcher.**
   - **The finding:** the families yfinance close reads as split-adjusted
     throughout. That is 24 of 24 decidable splits, and 13 of 13 undecidable ones
     against CRSP. `total_returns` assumes a raw close.
   - **What this guard does:** it stops only splits larger than an ordinary day.
   - **What would close the class:** a raw close, or an actions file that leaves
     out the splits the close already carries.
3. **The live book's one split (BIT 2025-08-19, k 1.029) is undecidable by
   price.** `split_factor`'s docstring reads the raw close as 14.47 → 13.84 [S:
   not re-read against a second source here]. Nothing in this guard confirms it.
