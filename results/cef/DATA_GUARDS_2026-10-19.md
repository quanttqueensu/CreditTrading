# Data guards: spike-and-revert bars, and Stage-0 flags that block P&L (2026-10-19)

**Zero trials. No counter moves.** These guards were built on the team lead's ruling
of 2026-10-19 ("build both zero-trial fixes"), after the C4 holdout review
(`results/cef/C4_RESULT_2026-10-14.md` §8).

**Reproduce:**

```bash
python3 -m pytest scripts/cef/tests/test_data_guards.py     # the guards on synthetic frames
python3 scripts/cef/data_guards.py scan                     # every hit in data/cef/ and data/cef_families/
python3 results/cef/data_guards/c4_callsites_noop.py        # C4's call sites, old vs guarded, hashed
python3 results/cef/data_guards/c4_holdout_under_rulings.py --cache <C4's gitignored _cache_c4>
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
2. **A second defect class is not guarded.** It is a recorded split applied to a
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
