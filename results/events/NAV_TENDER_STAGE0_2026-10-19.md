# NAV tenders (EVENTS trial 2): Stage 0, part A, and the halt before any return

**Date** 2026-10-19 · **Pre-registration** `results/events/PREREG_NAV_TENDER_2026-10-19.md`
(approved 2026-10-19, all twelve defaults, N = 6) · **Counter** EVENTS 2, unchanged (it
moved on approval) · **Author** research agent, branch `trial-events-navtender`

> **Status: HALTED in Stage 0, before any price or return was read.** Part A (EDGAR)
> ran and is recorded here. Part B (DG-NT-3 to DG-NT-6, the quality screen, the hedge
> and beta) needs CRSP extracts and an Alpaca read that load credentials, which agents
> never do. The team lead runs one staging command (§5). After that, Stage 0 part B
> writes the rulings form and stops again until every flag has a ruling (prereg skill
> §4b). **No P&L, k, Sharpe or hedged return exists for any event. The 2023-01-01
> holdout was not touched. No CRSP row was read.**

Reproducer: `python3 scripts/events/nav_tender_trial.py stage0 --edgar-only` (run
2026-10-19; exit 2 = the halt). Outputs, all tracked, EDGAR facts and counts only:

| file | holds |
|---|---|
| `results/events/nav_tender/stage0_2026-10-19.json` | counts by period, the 20% gate, the halt |
| `results/events/nav_tender/stage0_events_2026-10-19.csv` | per event: day 0, the filings read, expiry, pricing session, P_final, pi and how each was read |
| `results/events/nav_tender/stage0_flags_2026-10-19.csv` | the Stage-0 flags awaiting rulings (part A's 65) |
| `results/events/nav_tender/dg_nt1_readings_2026-10-19.csv` | the DG-NT-1 hand readings, each with a verbatim quote the script checks against the filing |

Tests: `python3 -m pytest scripts/events/tests/test_nav_tender_trial.py` (synthetic
data only, including a tender with a known payoff, the shift(2) alignment and
an end-to-end run of part B and the fit on a fake CRSP).

## 1. The event set and the 20% gate (DG-NT-2): PASS, 26 of 134 unread

| period | events | groups | completed | terminated | unread | re-dated |
|---|---:|---:|---:|---:|---:|---:|
| fit | 134 | 120 | 108 | 0 | **26** | 7 |
| gap | 1 | 1 | 1 | 0 | 0 | 0 |
| holdout (counts only) | 42 | 21 | 28 | 0 | 14 | not yet read |

The 44 `cef_universe.csv` funds (8 events) and the 4 merger-open fit events are excluded
first, as declared. The fit is 134 events in 120 groups, exactly the pre-registration's
proxy count (§11).

**26 of 134 fit events (19.4%) have an unread outcome or P_final, at or under the 20%
line, so the gate passes and part B may proceed.** The margin is one event: 27 would
halt the trial with no trial spent. Part B re-reads every event after the staging fills
the 55 intermediate amendments the cache lacks (47 fit events have at least one), so
the count is recomputed there and can still move.

The unread 26, by reason:

| reason | n | events |
|---|---:|---|
| no SC TO-I/A after the offer document | 10 | EEA 2010-12, GFY 2010-01, SCD 2011-03, AEF 2018-04, MXE 2018-01, 2019-01, 2019-12, SPE 2016-09, 2022-03, CHN 2019-01 |
| pi unread (the census reader declares a gap) | 8 | HIX, EHI 2020-08; WIA 2020-11; GLV, GLQ, GLO 2017-07; IDE 2021-02; SVVC 2019-12 |
| pi and P_final unread (joint releases) | 6 | VLT, VTA 2019-10; NMA, NQU 2014-08; EVF 2021-05; FTP 2017-06 |
| P_final unread (no price in the results filing) | 2 | ERC 2017-04, NRO 2011-10 |

**Second method.** `scripts/events/nav_tender_feasibility.py` (the pre-registration's
zero-trial script, which never reads a filing) gives the same 134-event fit set and the
same 24 events with pi unread. Stage 0's re-dating and re-reading changed neither. The
other 2 are the P_final gaps, each confirmed by hand: neither filing prints a price.

## 2. What Stage 0 read

**DG-NT-1 (day 0).** The 47 fit events whose offer document came more than 60 days after
day 0, or that followed a triggered discount-programme window, were read by hand:

- 40 day-0 filings announce a definite tender;
- 7 announced a tender that still depended on a future discount average, a future
  vote or a board's later decision, and are re-dated to the filing that announced the
  decided tender, by 45 to 112 calendar days:

| event | day 0 moves | why |
|---|---|---|
| Thai Fund 2013-05-31 | → 2013-07-19 | subject to the stockholder vote on restructuring |
| HERZ 2021-08-20 | → 2021-10-04 | policy "subject to annual Board approval" |
| IFN 2013-11-18 | → 2014-02-19 | stockholder vote, then the Board's authorisation |
| NRO 2016-07-26 | → 2016-10-04 | discount window still open to 2016-09-30 |
| EVG 2021-03-09 | → 2021-06-29 (offer document) | conditioned on a shareholder vote |
| MCN 2018-06-29 | → 2018-10-10 (offer document) | to follow a merger needing a vote; the merger-open screen missed it |
| GFY 2010-01-12 | → 2010-04-05 | a twelve-week measuring period "to determine whether to proceed" |

The 15 flagged holdout events are read at the holdout's own Stage 0. Every quote is in
the readings file, and the script checks each against its filing. Day 0 is then the first
session whose 22:00 ET decision follows the filing's `observed_at`, taken from the SEC
header (§4.2).

**DG-NT-2 (terms and outcome), the 108 completed fit events.**

- **Final expiry:**
  - read from the results filing for 105;
  - from the offer document for 3 (no extension found).
  - Five differ from the census's offer expiry: PCF, FGF, FGI, RGT and GGO, all
    extended.
- **Pricing session X_p:**
  - the NAV date printed with the final price for 68;
  - the offer's terms for 23;
  - the expiry, as the pre-registration states, for 17.
  - X_p falls 0 to 5 calendar days after the expiry. DDF 2014's 5 days are its offer's
    stated pricing date, and the event is flagged.
- **P_final:**
  - read by narrative statement, results table, or a fund-anchored statement in a joint
    release, all statements agreeing;
  - the filing-fee block is never read unless it is dated at the final expiry.
  - Check against the offer's stated NAV: P_final / (k% × NAV) has median 1.005
    (n 101, range 0.90 to 1.22, the energy funds of autumn 2022 at the top). The one
    above 1.15, NDP 2022, is flagged.
- **pi:** the census's reader, unchanged, on each offer's own last amendment. One event
  uses the second method only, labelled.
- **Episodes that hold two offers.** The census paired 6 of the 8 such fit events with a
  later offer's results. Here each is read on its own offer's last amendment. All 6 are
  read: each release prints only the fund's own ticker, so the census's joint-release
  test cannot fire, whatever CRSP's ticker list holds.
- **No offer in the fit was terminated or withdrawn.**

## 3. The flags awaiting rulings (part A: 65)

| check | fit | holdout | what the team lead rules |
|---|---:|---:|---|
| `dg1_definite`, `dg1_redated` | 47 | — | each DG-NT-1 reading (§2) |
| `quality_episode_far` | 8 | 11 | the episode holds more than one offer; the event is its first (§4.4) |
| `time_key` | 1 | — | DDF 2017: EDGAR's filing date precedes acceptance; observed_at = acceptance by the max rule |
| `pricing_session` | 1 | — | DDF 2014 priced 3 sessions after expiry (its own stated pricing date) |
| `pfinal_vs_offer_nav` | 1 | — | NDP 2022 at 1.22 × the offer's NAV |
| `spec_beta_window` | 1 (all) | | `e1_etf_hedge_gate.windows` refuses a test window of 0, so the script fits beta on 252 spans ending 43 valid sessions before day 0, one more than §5.2's 42. Keep, or use est = 251 on (s_est, e] |
| `spec_results_filing` | 1 (all) | | three of the 10 no-results events published results only in a post-expiry SC TO-C press release (EEA 2010, GFY 2010, SCD 2011). Keep them unread (the census's reader, §4.3), or admit the press release |
| `spec_per_event_units` | 1 (all) | | stages 1 and 3 use x_e = u_e × (fund + hedge P&L per unit notional), mean over events, `cluster_t` by sponsor × day 0, the literal "raw units". The mean of group means is printed beside it |

Part B adds the CRSP flags:

- `quality_abs_ret` and `quality_no_close`;
- `quality_delisted_in_hold`, if any;
- `spec_dg4_reads`, if the Alpaca and IBKR reads are not from one date.

The rulings file is `results/events/nav_tender/nav_tender_stage0_rulings_2026-10-19.csv`.
Part B writes its blank form, and `require_stage0_rulings` refuses to form any P&L until
every row carries a ruling, `ruled_by` and `ruled_on`. Stage 0's P&L-dependent items
(k and the cap-binding share) come after that block, because §4b forbids P&L before the
rulings.

## 4. Divergences and provenance, stated

- **EDGAR documents.** EDGAR needs `SEC_USER_AGENT` from the env file, which agents never
  read. So the 937 public filings read here were clone-copied from sibling worktrees'
  gitignored EDGAR caches (the census's and the N1 census's), with a sha256 manifest in
  this worktree's gitignored cache. 55 intermediate amendments of fit events (82 in all)
  were in no cache. The staging run fetches them, and part B re-reads everything.
- **CRSP.** No CRSP file was copied or read. The census worktree's cache does hold
  pre-2023 daily rows for all 139 pre-2023 tender permnos, by its manifest. That is
  licensed data outside this worktree, so it was not used. The team lead may authorise
  it in place of the R2 pull.
- **DG-NT-4.** The pre-registration's own reads were not one date: Alpaca on 2026-10-18,
  IBKR's file on 2026-10-19. The staging step reads Alpaca with the cef paper key beside
  a fresh IBKR file.

## 5. What the team lead must run, then rule

In this worktree (`.claude/worktrees/trial-events-navtender`):

```bash
curl -s -o /tmp/usa.txt https://www.interactivebrokers.com/shortstock/usa.txt   # public file
export QUANTT_ENV_FILE=/abs/path/config/.env                                     # SEC agent, R2, Alpaca cef key
python3 scripts/events/nav_tender_trial.py stage --ibkr /tmp/usa.txt
```

This command:

- fetches the uncached EDGAR amendments;
- pulls CRSP names, delistings and one batch of pre-2023 `dsf` rows (R2);
- fetches the French factors;
- writes `results/events/nav_tender/dg_nt4_reads.json` (Alpaca flags and IBKR rows for
  the hedge ETFs).

It computes no return. Then:

1. `python3 scripts/events/nav_tender_trial.py stage0` runs part B and writes the
   rulings form.
2. The team lead rules every row of the form.
3. `fit` runs stages 1 to 5. Its verdict is committed before the holdout reader will run.
4. The holdout's own 2023-24 CRSP pull is `stage --holdout`. It refuses until the fit
   verdict is committed.

**The holdout's count is reported now, and decides nothing yet.** 14 of its 42 events
(33%) are unread on today's reading. If that stands at the holdout's Stage 0, the
holdout halts under §4.3 and is reported, and the fit verdict stands (§11.1).
