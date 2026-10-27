# R5: does the CEF discount z-score work on BDCs? Zero-trial screen, 2026-10-26

Report only. **No trial spent and no counter moved.** Asked by the team lead on 2026-10-26.
Code tree: export of branch `simon` at dff4b5c. No network fetch was made, so `raw/` is empty.

Labels: [V] computed now by a script in this folder, [S] sourced but not re-read,
[U] uncertain, [doc] copied from a repo note.

## 1. Question and scope

The book's signal is the z-score of each fund's price-to-NAV discount against the fund's
own trailing window, demeaned across funds: long the cheap funds, short the rich ones.
Does it work on listed Business Development Companies (BDCs)? BDCs are closed-end, with no
creation or redemption.

**This screen covers BDCs only.**
- Preferred ETFs against their NAV are already dead: `single-fund-PD` (D1) in
  `docs/RESEARCH_STATE.md` [doc]. An ETF's premium or discount is NAV staleness.
- Preferred CEFs already sit inside C4's preferred family.

**Prior (graveyard pattern #1, `.claude/skills/graveyard/SKILL.md`)** [doc]. Six of
thirteen deaths were "price minus a stale mark". A quarterly NAV is the stalest mark
there is. Between filings, P/NAV moves only through price. The frozen spec's
`z_window` is 252 sessions [V, read through `scripts/cef/spec.py`], so one trailing window
holds about four NAV prints. Inside it, the z-score of P/NAV is mostly a z-score of price
with a few step changes.

## 2. Feasibility requirement (declared before searching)

We need a point-in-time NAV per share, with the date it became public, for **≥ 20 listed
BDCs across ≥ 5 years of 2012–2022**, plus their daily prices. The NAV counts as known
on the filing date of the 10-Q, 10-K or press release that reports it, never on the
quarter-end date.

## 3. Feasibility findings: what is on this machine

| ingredient | where it was looked for | result |
|---|---|---|
| BDC NAV in `data/` | every parquet and CSV identifier column, plus every column name in wide panels (`scripts/scan_data_dir.py`, `scripts/scan_data_wide.py`) | **None.** No panel in `data/` holds a BDC NAV [V]. The NAV panels (`data/cef/cef_nav.parquet`, `data/cef_families/cef_nav*.parquet`, the iShares and JNK NAV files) hold CEFs and ETFs only. The only BDC tickers anywhere in `data/` are three names (MAIN, ORCC, SSSS) in the merger-target name map `events/merger_targets/crsp_names_linked.csv`, with no NAV [V]. Some files under `holdings/raw/*.csv` are iShares bond-ETF holdings files that do not parse as plain CSV. They are not BDC sources. |
| CEFConnect coverage | `data/cef_families/raw/cefconnect_dailypricing_2026-10-12.json` (359 funds) | **0 BDCs** listed [V] |
| NAV knowledge dates | `d2_bdc_reports.parquet` in the D2 cache (worktree `research-ss-expansion`, `results/events/ssx/_cache_ssx_fil/`) | **Present.** 1,943 10-Q/10-K reports from 61 listed BDCs, filed 2012-01-01 → 2022-12-16. Of these BDCs, 46 have ≥ 20 reports spanning ≥ 5 years [V]. The index includes dead names such as ACAS, MCGC and MVC, so it is not survivor-only [V]. |
| NAV values from XBRL, point-in-time | `d2_bdc_navps_facts.parquet` (cached companyfacts) | **Fails.** For these 61 BDCs, the facts known by 2022-12-31 cover only 175 distinct BDC period-ends, 2017–22, almost all of them 2020–22 (35 / 79 / 49). They come from 39 BDCs. **0 BDCs have ≥ 20 quarters, and 1 spans ≥ 5 years** [V]. See the note on the 9.0% figure below this table. |
| NAV values from XBRL, read loosely (not point-in-time) | the same file, allowing values from later filings that restate old periods | **Fails even so.** 505 period-ends, mostly year-ends, and **0 BDCs reach ≥ 20** [V] |
| NAV values from Compustat | `comp_fundq_rdq.parquet` (local cache) | The local cache holds only `gvkey, datadate, rdq`, with **no `ceqq`/`cshoq`** [V]. It does show the route would cover the universe: 2,017 BDC-quarters with an `rdq` in 2012–22 across the 61 linked gvkeys, 49 of them with ≥ 20 quarters. `rdq − datadate` is 32 / 39 / 65 days at p10 / p50 / p90 [V]. |
| NAV from filing text already cached | all 17 local `_cache_edgar` and `_cache_event_engine` folders in the worktrees (`scripts/scan_edgar_caches.py`) | **Fails.** The caches hold 31 of the 1,943 listed-BDC 10-Q/10-K reports, and 23 of the 2,440 BDC 8-K item 2.02 earnings releases for 2012–22 (16 BDCs) [V]. |
| daily prices | local licensed CRSP caches (`scripts/scan_prices.py`; read only through 2022-12-30) | **Present.** `research-ss-expansion/results/events/_cache_crsp/dsf_44015b5199.parquet` covers 54 of 61 BDC permnos in 2012–22, and 44 of them have ≥ 1,260 price days. Last date read: 2022-12-30 [V]. These files are not in `data/`. |

**Note on the 9.0% point-in-time figure.** It is 175 period-ends against 1,943 reports.
This is a looser metric than D2's 1.6% [doc]. It counts any NAV-per-share fact known by
the end of 2022, including the comparative periods printed in 2022 filings. D2 counted
only a report's own period. Both say the same thing: XBRL NAV starts in 2022.

**Conclusion.** Dates and prices exist locally; **the NAV values do not.** The
requirement fails: 0 BDCs have ≥ 20 point-in-time quarters, against the ≥ 20 BDCs needed.
I stopped here. I computed no signal, IC or P&L, and loaded no return.

## 4. Verdict: **INFEASIBLE**

## 5. What would make it feasible (each needs the team lead)

1. **R2 read, the cheapest route.** Read `comp_na_daily_all.fundq` (Compustat; it is on
   R2 per `results/events/ssx/ssx_data/r2_full_inventory_columns_2026-10-19.csv` [V])
   with the columns `gvkey, datadate, rdq, ceqq, cshoq, cshopq, tic, cik`, for the
   61 linked gvkeys.
   - Coverage: about **2,017 BDC-quarters, 49 BDCs with ≥ 20 quarters**, sized from the
     local `rdq` rows [V].
   - Needs: R2 credentials, held by the team lead.
   - NAV per share ≈ `ceqq / cshoq` [U]. This is book equity per share. It equals NAV
     per share only up to preferred equity and the date of the share count, and
     Compustat can carry restated values.
   - Validate it against the 175 point-in-time XBRL NAV values for 2020–22 before
     using it.
2. **EDGAR text route.** Parse NAV per share from the text of the filings. This needs the
   team lead's `SEC_USER_AGENT`. The local index already lists every accession, so no
   search is needed.
   - **10-Q/10-K text: 1,943 listed reports, 61 BDCs** [V].
   - Or the earnings releases (8-K item 2.02, EX-99.1): **2,440 releases, 59 BDCs** [V].
     17 of 20 sampled releases print NAV per share as text [doc].
   - Either way that is about 2,000–2,500 document fetches, less the 31 + 23 already
     cached.
3. **Prices.** The CRSP BDC prices exist only in a worktree cache. A trial would need
   them staged by a fetcher, with a source note in `docs/REFERENCES.md` (never copied
   by hand), and written outside `data/`.

## 6. Design for a real trial (declared now; not run)

This is the design any later run must keep. It is fixed before anyone sees a number.

- **Universe.** Listed BDCs from the local report index. Each name enters on its first
  filing date with a NAV and a price, and leaves at delisting.
- **Window.** Fit window only: dates ≤ 2022-12-30, asserted in code. Eras 2012–17 and
  2018–22 (H5).
- **Knowledge date.** NAV_q is known from the session of the 10-Q/10-K `filingDate`, or
  the next session if the filing was accepted at or after 16:00 ET. Sensitivity run: the
  2.02 release or `rdq` date, under the same 16:00 rule. Assert that the known date is
  after the period end and no earlier than the filing date.
- **Signal.** d_t = P_t / NAV_last-known(t) − 1. Its z-score uses the fund's own trailing
  `z_window` (read from the spec), shifted one day and demeaned across funds. Long cheap,
  short rich, as in the book.
- **IC.** Use W4's forward window, close t+1 → close t+3, on non-overlapping dates
  (`scripts/cef/w4_artifacts.py`), reported by era. Any P&L mirrors `evaluate()` in
  `scripts/cef/band_frontier.py` (shift(2)). Gross only.
- **Negative control.** The z-score of log price against its own trailing `z_window`,
  with no NAV, under the same demeaning, forward window and dates. **ARTIFACT/NOTHING**
  if either holds:
  - the control's IC ≥ the treatment's IC in either era;
  - the treatment's IC, partialled on the control, has t < 2.
- **Second check.** IC on the 5 sessions after each fresh NAV filing, against all other
  sessions. If the NAV carries information, the IC should concentrate after filings. If
  it is flat or lower there, the signal is price reversal.
- **PROMISING** needs all three:
  - treatment IC > 0 with t ≥ 2 in both eras;
  - it beats the control under both conditions above;
  - the post-filing IC ≥ the IC on other sessions.

## 7. Reproduce

```bash
S=/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/767b4ac8-7cb7-4bf6-953a-b785b037a5b4/scratchpad
cd $S/tree && python3 ../r5_bdc/scripts/scan_data_dir.py && python3 ../r5_bdc/scripts/scan_data_wide.py
cd $S/r5_bdc && python3 -I scripts/scan_edgar_caches.py && python3 -I scripts/scan_prices.py && python3 -I scripts/feasibility_counts.py
```

Outputs: `feasibility_counts.json` and `out_scan_*.txt` in this folder. Every script is
read-only and has no network access. Return and price reads are limited to dates ≤
2022-12-30 and asserted.
