# R4: fund-of-CEF index reconstitution (YYY, PCEF, XMPT): zero-trial screen

2026-10-26. Asked for by the team lead. Report only: **no trial is spent and no counter moves.**
Graveyard neighbours: A9 (BIZD review demand, KILLED: median 0.39 days of ADV, and
`shift(2)` misses the window). B2 in `results/cef/EVENT_DRIVEN_POD_2026-10-12.md`
(~line 371) says "count events first".

## 1. Question

Do reconstitutions of the indices behind the fund-of-CEF ETFs YYY (ISE High Income
Index), PCEF (S-Network Composite Closed-End Fund Index) and XMPT (its muni CEF index)
force buying and selling in the CEFs they add, drop or reweight? Are those flows large
against the CEF's ADV? Do they leave a price-pressure-and-reversal pattern that a
`shift(2)` book could trade?

## 2. Declared design (written BEFORE any return was computed)

Nothing in this section was changed after a return was looked at. If a later section
departs from it, that section says so.

### 2.1 Events

- **Event** = one constituent change in one of the three indices on one reconstitution
  date: an **add** (Δw = +w_new), a **drop** (Δw = −w_old), or a **reweight**
  (Δw = w_new − w_old).
- **Known date** = the public announcement date of the change, not the effective date.
  Where a methodology fixes the lag (YYY: 6 trading days before effective [doc]), the
  announcement is that date. Where no public announcement before the effective date can
  be shown, the event counts as known only on its effective date, and so it has **no
  tradeable pre-effective window** under `shift(2)`.
- **Alignment.** A signal known at close A (the announcement) fills in the close-A+1
  auction and earns from close A+1. Window 1 therefore runs from close A+1 to the last
  close at which the index fund trades (the effective close E). It exists only if
  E ≥ A+2 sessions. Asserted in code.

### 2.2 Size

- **Demand** D = AUM_ETF(last known before A) × |Δw| ÷ ADV_63(name), with ADV_63 = the
  mean of close × volume over the 63 sessions ending at close A−1, from
  `data/cef/cef_prices.parquet` or `data/cef_families/cef_prices.parquet`. No AUM or
  weight is invented: an event whose AUM or Δw cannot be sourced is counted as
  **UNSIZED** and is not counted as ≥ 1 ADV.
- **Bar.** An event qualifies if D ≥ **1.0** day of ADV (the A9 bar).
- **Step-2 gate.** Step 2 runs only if **≥ 30** dated, sized, qualifying events fall
  on allowed names with A ≤ 2022-12-30 and with a Window 1 of at least one session.

### 2.3 Names

- **Allowed for returns:** the deployed 13 (`scripts/cef/spec.py` UNIVERSE); the wide
  17 (UNIVERSE + NAD, NEA, NVG, NZF, per `scripts/cef/w4_artifacts.py`); C4's families
  universe (`data/cef_families/universe.csv`, `included == True`).
- **Sealed:** the other 27 names of `data/cef/cef_universe.csv`. Events touching them
  are **counted** and excluded. No return is computed on them.
- **Everything else** (a CEF in none of these lists): counted as "outside our panels";
  no return is computed, because we hold no price panel for it.

### 2.4 Returns (step 2 only, if the gate passes)

- **Fit window only.** Every price used has date ≤ 2022-12-30, asserted in code. Events
  dated 2023+ are counted (dates and names only), never priced.
- **Windows.** W1 = close A+1 → close E (pressure). W2 = close E → close E+10 sessions
  (reversal).
- **Abnormal return** = the name's total return minus the equal-weight mean total return
  of same-family allowed CEFs that had no change in that index on that date, over the
  same window. Family = `grp` in `cef_universe.csv` (restricted to allowed names), or
  `family` in the C4 universe.
- **Signed** by the direction of the flow: AR × sign(Δw). The prediction is a positive
  signed AR in W1 and a negative one in W2.
- **Discount change** over each window: Δ(P/NAV − 1) on the same days, abnormal against
  the same control set.
- **Inference.** Mean signed AR, t clustered by reconstitution date. Gross only: no cost
  grid, as the team lead asked.

### 2.5 Negative control (declared first)

1. **Non-changers.** The same W1 and W2 on same-family CEFs that did NOT change on those
   dates, each against the mean of the others, with the event's sign. It should be zero;
   if it is as large as the treatment, the treatment is a family or date effect, not flow.
2. **Placebo dates.** The same event names and windows shifted 21 sessions earlier
   (about one month). It should be zero.

### 2.6 Verdict rule

- **INFEASIBLE** if the events cannot be dated and sized from public, credential-free
  sources for enough of 2010–2022 to apply the gate.
- **NOTHING (D7)** if they can be, but fewer than 30 qualify.
- If the gate passes: **PROMISING** only if the signed W1 or W2 AR has |t| ≥ 2 with the
  predicted sign and both controls have |t| < 1; **ARTIFACT** if a control is as large
  as the treatment; else **NOTHING**.

## 3. Sources tried

Everything below §2 was written after §2. No return was computed: the step-2 gate failed
(§5), so the only market data read is daily dollar volume (close × volume) on allowed
names, through 2022-12-30 (asserted in `size_events.py`). Panels read:
`data/cef/cef_prices.parquet` (last date 2026-10-15; read to 2022-12-30) and
`data/cef_families/cef_prices.parquet` (last date 2026-10-09; read to 2022-12-30).

| source | result | label |
|---|---|---|
| `data/holdings/nport_holdings.parquet` | holds **HYG, JNK and LQD only**. YYY, PCEF and XMPT are not in it. No local file holds any of the three | [V] |
| Nasdaq `Methodology_YLDA.pdf` (fetched 2026-10-26) | effective at the **open of the first session after the 3rd Friday of Jan/Jul**; announced **after the close on the 6th trading day before**; current caps 3.5% (top 30) / 2% / **10 days of ADV ÷ 110% of YYY's net assets**. Before 2024-07-22: 45 funds, linear rank weight, cap 3% and ADTV ÷ $10m | [V] text; **[U] for 2013–21**: the archived YYY holdings show 30 funds at up to ~4.8% each, so the early rules differed |
| Nasdaq GIW `/Index/Weighting/YLDA` | the anonymous view gives **today's names only** (60, no weights). The date picker is disabled for non-subscribers, so I did not ask for history | [V] |
| S-Network CEF Index Family methodology (VettaFi, March 2024) | CEFX: all eligible taxable fixed-income and option-income CEFs, **adjusted-net-asset weighting**, 8% cap, quarterly, effective at the **close of the quarter's last business day**. CEFMX (XMPT): rebalanced quarterly, reconstituted semiannually (Mar/Sep) | [V] text; [U] for 2010–21 |
| PCEF / XMPT announcement date | not found. A web-search summary of a 2020 UBS 424B3 on EDGAR says a press release follows "by the Monday after" the 3rd Friday. I could not fetch it (EDGAR). VettaFi said in 2023 that it would stop announcing changes with quarterly rebalances | **[U]** |
| Wayback: PowerShares PCEF holdings page | **19 snapshots, 2010-02-26 → 2013-12-19**, full holdings (70–146 names). Weights sum to 99.4–100.1% | [V] |
| Wayback: PowerShares PCEF overview page | 41 AUM points (shares × price), **$122.7m (2010-08-24) → $488.6m (2014-01-02)** | [V] |
| Wayback: Invesco-era PCEF pages, 2019–22 | 6 captures. The pages are filled by script, so no holdings | [V] |
| Wayback: YieldShares YYY holdings page | **10 dated snapshots, 2013-12-06 → 2017-04-07**, 30–31 names with market values; AUM **$14.8m → $152.0m**. Captures from 2017-04 on carry no table | [V] |
| Wayback: Amplify family holdings CSV | YYY on **2020-03-16/17** and **2021-02-17/18**; AUM $183–204m and **$296m** | [V] |
| Wayback: Amplify `yyy-holdings`, 2022–23 | 7 captures, all filled by script ("Holdings as of TBD"), so no holdings | [V] |
| Wayback: VanEck XMPT holdings | **6 snapshots, 2019-11-12 → 2021-09-20**, 58–64 names; AUM $151–212m | [V] |
| Wayback: Market Vectors XMPT page, 2011–16 | 89 captures. **Top-10 holdings only**, so adds and drops cannot be read; AUM $22.7m (2014-01-07) → $98.7m (2016-05) | [V] |
| EDGAR (N-Q, N-CSR, N-PORT-P) and R2 `crsp_q_mutualfunds.holdings` | **not used**: both are forbidden in this screen (contact header; credentials) | — |

Every fetch is logged with its URL and UTC time in `raw/fetch_log.csv` (264 lines incl. header and the early curl rows).

**Two artifacts found and removed before counting.** Left in, they would have added
**7 false ≥ 1-ADV events**:

- **NAV-symbol tickers.** From 2012-05-18 to 2013-05-10, the PCEF page lists
  ETY, EXG, QQQX, BKT, JGV, JLA and MGF under their NAV symbols (XETYX, XEXGX, XQQQX, …),
  and YYY 2021-02 lists XDLYX. Read as tickers, this fakes a drop and a re-add of each
  fund. EXG, ETY and QQQX would each have produced a "drop" and an "add" at ≥ 1 ADV.
  They are mapped back; XQQQX goes to QQQX, not QQQ.
- **A merger.** Between 2013-08-05 and 2013-12-19, COY, CYE and HYV leave PCEF while
  HYT's weight goes from 0.46% to 1.80%. That is the BlackRock high-yield merger (the
  four weights summed to 1.47%), not an index trade, and it would have counted as a
  3.06-day "reweight". Excluded.

**Calendar check [V].** All 11 snapshot pairs that bracket no scheduled rebalance show
**0 constituent changes**. That covers PCEF, YYY and XMPT, gaps of 1 day to 6 weeks.
Changes appear only in pairs that bracket a scheduled date. This supports the
quarter-end calendar for PCEF and the Jan/Jul calendar for YYY.

## 4. Event counts and sizes

**Coverage.** Snapshot pairs that bracket exactly one scheduled rebalance give dated events:
- PCEF: **11 of 52** quarter-ends, 2010-09 → 2013-09.
- YYY: **3 of ~18** reconstitutions, 2014-01, 2015-07 and 2016-01, when its AUM was $15–95m.
- XMPT: **1 of ~46**, 2020-12.

Together that is **15 of ~116** scheduled rebalances (~13%) [V counts; the ~18 and ~46
assume the inception dates 2013-06 and 2011-07, [S]].

**Window.**
- YYY: **4 sessions** from the `shift(2)` fill (close A+1) to the last close before the
  effective date [V on the current text].
- PCEF and XMPT: 3–8 sessions, on the [U] announcement proxy.

So, unlike A9, a pre-effective window would exist if the announcement is public.

**Snapshot bound: the ETF's full position in each allowed name, in days of ADV63 [V].**
This bounds a full add or drop at that AUM.

| ETF | dates | AUM | median | max | names ≥ 1 ADV |
|---|---|---|---:|---:|---|
| PCEF | 2010-09 → 2011-02 | $131–192m | 0.73–0.87 | 2.1 | 6–9 of 26–33 |
| PCEF | 2012-10 → 2013-12 | $360–490m | **1.8–2.1** | 3.8 | 33–40 of 36–45 |
| YYY | 2013-12 → 2014-03 | $15–32m | 0.2–0.3 | 0.5 | 0 |
| YYY | 2015-08 → 2017-04 | $79–152m | 0.7–1.7 | 3.0 | 5–10 of 12–17 |
| YYY | 2021-02 | $296m | **1.65** | 3.9 | 11 of 14 |
| XMPT | 2019-11 → 2021-09 | $151–212m | **2.0–4.1** | 5.4 | 6 of 6 |

The XMPT row covers MHD, MQY, NAD, NEA, NVG and NZF, which sit at the 8% cap.

So the flow can be large against ADV (A9's median was 0.39). But XMPT's large positions
are in names that never leave the index, and **reweights are small**. Over the dated
events on allowed names, excluding the merger, the median reweight is:
- PCEF 0.10 days (n 376, max 0.74);
- YYY 0.04 (n 44);
- XMPT 0.01 (n 6).

**0 of 426** reweights reach 1 ADV [V]. Only additions and deletions can.

**Dated events on allowed names** (`out/events_dated.csv`):
- PCEF: 19 adds (median 0.78 days) and 1 drop (0.64).
- YYY: 8 adds (0.42) and 5 drops (0.23).
- XMPT: no adds or drops.

**GATE: dated, sized, ≥ 1 ADV, allowed names, fit window = 7 [V]. The gate needs 30.**

| E | ETF | kind | name | class | weight | demand, days of ADV |
|---|---|---|---|---|---:|---:|
| 2010-12-31 | PCEF | add | JFR | deployed 13 | 1.45% | 1.90 |
| 2010-12-31 | PCEF | add | HPF | C4 | 0.76% | 1.11 |
| 2012-12-31 | PCEF | add | DNP | C4 | 2.16% | 1.30 |
| 2013-03-28 | PCEF | add | LDP | C4 | 0.79% | 1.37 |
| 2013-03-28 | PCEF | add | HEQ | C4 | 0.40% | 1.87 |
| 2013-06-28 | PCEF | add | BIT | deployed 13 | 0.66% | 1.25 |
| 2013-09-30 | PCEF | add | FPF | C4 | 1.15% | 1.09 |

By year: 2010: 2, 2012: 1, 2013: 4.

**Independent re-derivation.** JFR's ADV63 was recomputed from the raw panel: $1.355m over
2010-09-21 → 2010-12-17, 63 sessions. The demand is 1.90 days, or 2.06 on the median dollar volume. YYY's
AUM implied by % of net assets matches the sum of market values to within 1% on all 14
snapshots [V].

Several adds are recent IPOs reaching the 3-month seasoning rule (BIT 2013-02, FPF
2013-05, LDP 2012) [S on the IPO dates; panel start dates agree for BIT].

**Undatable** adds and drops come from pairs that span ≥ 2 rebalances, sized at the near
snapshot (`out/events_undatable.csv`):
- YYY, allowed names: **57 changes, 32 at ≥ 1 ADV** (C4 adds median 1.41 days).
  - 2016-04 → 2017-02 (2 reconstitutions): 13 of 15.
  - 2017-04 → 2020-03 (6): 8 of 10.
  - 2020-03 → 2021-02 (2): 8 of 12.
- PCEF: 2 of 7.

These cannot be dated to a single rebalance, so they cannot be event-studied. They are
the history a full holdings file would add.

**Sealed holdout (27 names): counted, never sized or priced.**
- Dated: PCEF 10 adds, 1 drop and 123 reweights; YYY 1 drop and 10 reweights; XMPT 5 reweights.
- Undatable: PCEF 2 adds and 1 drop; YYY 11 adds and 4 drops.
- Today's YLDA list (2026-10-26, names only) holds 8 sealed names (BGT, DHY, EDD, EMD,
  GHY, HIO, PFL, VVR), 6 of the deployed 13 (BIT, DSL, HYT, JFR, PFN, PHK), 24 C4 names
  and 22 others [V].

**2023+ events:** none could be counted. No 2023+ capture carries holdings.

**Projection, labelled [U] and not used for the verdict.**
- At PCEF's observed rate (7 in 11 quarters), 52 quarters would give ~33, if AUM and
  universe were stable, which they were not.
- YYY's undatable pairs suggest ~4–6 allowed ≥ 1-ADV changes per reconstitution from
  2016 on, so ~50–80 over 2016–2022.
- A full holdings history could therefore plausibly clear the gate, mostly through YYY
  and PCEF additions.

## 5. Results

Step 2 did not run. The declared gate needs ≥ 30 dated, sized, ≥ 1-ADV events on
allowed names in the fit window; the credential-free record gives **7**. **No return,
abnormal return or discount change was computed, so the negative control (same-family
non-changers, and placebo dates 21 sessions earlier) was declared but not run.**

The only control that ran is the calendar check in §3: 0 changes in 11 pairs that
bracket no rebalance.

## 6. Verdict: **INFEASIBLE**

Per §2.6: the public, credential-free record dates **15 of ~116** scheduled rebalances.
That is not enough of 2010–2022 to apply the gate, and it yields 7 qualifying events
against 30. This is not a null on the mechanism.

The sizes clear the A9 bar where it matters: additions and deletions. PCEF's full
positions reached a median of ~2 days of ADV by 2013, and YYY's ~1.7 days by 2021.
YYY also has a 4-session pre-effective window under its published calendar.

**What would make it testable** (any one; the first is cheapest):
1. **R2 `crsp_q_mutualfunds.holdings` + `portnomap` + `monthly_tna`** for the portnos of
   YYY, PCEF and XMPT. This needs the team lead's R2 credentials. The repo has already
   read it for PFF and BIZD, monthly from 2010-06 (`results/events/ssx/ssx_data/DATA_MAP_2026-10-19.md`).
   Monthly holdings bracket every quarter-end and every Jan/Jul reconstitution.
2. **EDGAR** N-Q (to 2019) and N-PORT-P exhibits (2019+), with the team lead's SEC
   user-agent. YYY's schedules are dated Jan 31 and Jul 31 [S: search result titles],
   which bracket each reconstitution.
3. **A Nasdaq GIW subscription** for YLDA's daily historical weights.

Plus, for PCEF and XMPT, the S-Network/VettaFi announcement history. Without it, those
events are known only at the effective date, and only the post-effective (W2) window is
testable.

## 7. Reproduce

```sh
sh /private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/767b4ac8-7cb7-4bf6-953a-b785b037a5b4/scratchpad/r4_index_rebal/reproduce.sh
```

- Network: web.archive.org only. The fetches skip files already on disk.
- Then it runs `parse_snapshots.py`, `parse_aum.py` and, from `tree/`, `size_events.py`.
- Output goes to `out/size_events_final.txt`, identical to the run quoted here.
- Outputs: `out/holdings_snapshots.csv`, `out/aum_points.csv`,
  `out/snapshot_position_days.csv`, `out/events_dated.csv`, `out/events_undatable.csv`,
  `out/events_qualifying.csv` and `out/rebalance_calendar.csv`.
