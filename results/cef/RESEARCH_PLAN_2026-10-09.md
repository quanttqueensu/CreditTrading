# Research and testing plan — 2026-10-09

**What this is.** The research and testing programme that follows from the
2026-10-08/09 research:

- `results/cef/RESEARCH_AGENDA_2026-10-08.md`: product × signal families;
- `results/cef/SCALING_RESEARCH_2026-10-08.md`: how others clear 10%, and the
  eight-topic pass in §7;
- the team lead's rulings of 2026-10-09, recorded in `docs/SYSTEM.md` §5.

It orders the work, names what each item needs first, and states what kills
it. **It spends no trial on its own.** Every trial below is pre-registered with
`/prereg`, approved by the team lead before it runs, and counted in
`docs/RESEARCH_STATE.md` in the same commit. The usual route is the
`/research-idea` workflow: graveyard check, pre-registration, harness result,
independent review.

## 0. The rulings this plan obeys (team lead, 2026-10-09)

| | ruling | what it means here |
|---|---|---|
| Capital | Real capital soon | Item 0.5, the real-money cost re-run, **gates any deployment of capital**. The paper `late_market` exception never applies live |
| Target | ≥10%/yr gross, net beside it; Reg T now; vol target derived (W6, cap 20%) | Return comes from breadth and the vol target. Leverage beyond Reg T is research (phase 4) |
| Beta | Alpha only | Every sleeve faces the D4 test (alpha t ≥ 3.0 with factor betas ≤ 0.10). Carry is closed |
| Counters | New per source | CEF for the live book and CEF-discount signals; **EVENTS** for corporate actions; **XASSET** for the cross-asset slate; **GAMMA** for options |
| Holdout | The 27 names opened for event trades; the time holdout stays sealed | The first event test that computes returns on a `cef_universe.csv` name **consumes** the set and must say so |
| TLT data | Fit on VXTLT 2004–22; 2023+ strike data is the GAMMA holdout | The defined-risk test opens 2023+ once |
| Sleeve home | Inside the CEF account | Each sleeve is a spec-keyed component with its own P&L line, combined by Σ⁻¹·IR |
| Dividends | Third P&L line | Built in 0.4 before any yield-carrying sleeve is scored on paper |

**Standing harness rules apply to every test** (H1–H15, `/harness`):

- `shift(2)`;
- turnover-matched comparisons;
- the gross headline with the 5/15/30bp grid beside it (and whether it flips
  sign);
- borrow charged separately;
- five eras;
- a fit row before 2023 and a 2023+ row;
- negative controls;
- no sweeping;
- total returns;
- figures labelled [V]/[S]/[U].

**Every agent figure must be re-run first.** The agents' 2026-10-08/09 numbers
live in session scratch, not the repo. A pre-registration may cite a figure only
after it has been reproduced by a script in the repo.

---

## 1. Phase 0: foundations (0 trials; starts now)

Two streams that can run in parallel. **P** = production (`quantt/`, the live
path: a test that fails against the old behaviour, `/release-check`, then a
release tag). **R** = research data (`scripts/`, never on the live path).

| # | item | stream | needs | deliverable | done when |
|---|---|---|---|---|---|
| 0.1 | Restore the ETF fetchers (`scripts/rv/stage_ohlc.py`, `stage_ohlc_extended.py`, `scripts/build_etf_daily.py` from tag `pre-clean-slate`). Extend them to EFA, EEM, GLD and DBC, and continue past 2024 from Alpaca bars | R | — | fetchers plus `docs/REFERENCES.md` §8 rows; `data/rv/` rebuilt | the panels rebuild byte-identically up to their old last dates |
| 0.2 | Official-close mapping for NYSE Arca, Nasdaq, Cboe BZX and NYSE American (`ASSET_EXCHANGE_SIP_NAME`, `quantt/broker/alpaca.py`), with sourced closing cut-offs | P | sourced venue rows (Arca [S 2018], BZX [S proposed], NYSE American [U]) | code, tests, `docs/REFERENCES.md` rows | a non-NYSE name no longer raises `UnmappedExchange`; auction prints recorded |
| 0.3 | A daily shortability and borrow snapshot of the candidate universe (extend `alpaca_probe`, read-only) | P | — | `results/ops/alpaca_probe/` daily rows | 20 consecutive sessions captured |
| 0.4 | **The third P&L line: distribution-adjusted** (credit long distributions, charge short ones) in verify and collect | P | the distribution panel | code, tests, `docs/RUNNER.md` | the verify report shows three scores; the test fails on the old two-line code |
| 0.5 | **The real-money cost re-run**: `band_frontier.py` with measured borrow by name, distributions owed on shorts (total returns), and the measured paper-fill vs auction-print slippage | R | 0.3 (borrow), 0.4 | `results/cef/REAL_MONEY_COSTS_<date>.md` | **The gate.** If the live book is not positive net after measured costs, real capital waits, and C1/C2 (phase 2) come before any new sleeve |
| 0.6 | **W4, the artifact battery**: total-return panel; bid–ask bounce; stale-NAV catch-up; where the IC lives (ex-dates, crises, turn of year); split of P&L into price and NAV closure; FF5 + momentum + Pástor–Stambaugh + Sadka attribution by era | R | — | `results/cef/W4_ARTIFACTS_<date>.md` | every later "incremental to the z-score" claim has a clean baseline |
| 0.7 | **The EDGAR event fetcher**: SC TO-I/TO-C, N-14, 425, DEF/PRE 14A, 8-K, N-2/424B, with a contact user-agent set by the team lead (never the user's email by default) | R | the team lead supplies the SEC user-agent string | `scripts/data/fetch_edgar_events.py` and an event table | announcement, effective and termination dates for CEF and BDC events, 2010+ |
| 0.8 | **CEF NAV history beyond the 44 names**: N-CSR/N-CSRS NAVs, N-PORT monthly net assets ÷ CRSP shares, plus yfinance X-tickers and CEFConnect for live names | R | 0.7 | a NAV panel for event names | ex-ante NAVs exist for the merger and term-CEF events |
| 0.9 | **Bring the agents' scratch analyses into the repo and re-run them**: merger spreads, convertible-issuance event study, VRP/IV build, BDC release events, term-CEF census, specialists' betas | R | — | `scripts/events/`, `scripts/gamma/`, `scripts/xasset/` | each figure in SCALING §7 reproduces, or is corrected visibly |
| 0.10 | Option quote capture for TLT (and HYG) **during regular trading hours**. Today's quotes are post-close or "indicative", and OPRA access was refused ("agreement is not signed") | R | the team lead decides on an OPRA data subscription (Alpaca or another vendor) | ≥20 sessions of regular-hours NBBO for 4-leg structures | spread cost per structure measured |
| 0.11 | One read-only `GET /v2/assets?asset_class=treasury` (and `=corporate`) | R | — | one line in `results/ops/` | whether the paper account can see bonds is settled |

---

## 2. Phase 1: zero-trial gates (each can kill an idea at no cost)

| gate | for | measure | passes when | kills when |
|---|---|---|---|---|
| G1a | merger pair | Alpaca shortability today of acquirers in pending CEF/BDC mergers, and the historical share of shortable acquirers (0.3) | most acquirers are shortable | the hedged pair is not buildable. A long-only target leg would be a different, beta-carrying bet, which is ruled out (alpha only) |
| G1b | merger pair | the ex-ante sign of the target/acquirer discount gap from NAVs at announcement (0.8), against the ex-post sign | they agree in ≥85% of events | below 85%: the hindsight results are not reachable |
| G1c | merger pair | event count with the 27 opened, clustered by acquirer group | ≥30 independent groups | below 30: D7 |
| G2 | TLT short variance | (a) a VXTLT 2004–22 variance-swap proxy net of the measured 4-leg regular-hours spread (0.10); (b) a replay of 2008 and 2020 for a defined-risk structure inside the vol cap; (c) correlation with the book | (a) is positive; (b) stays inside the cap; (c) is about 0 | (a) ≤ 0, or (b) breaches the cap |
| G3 | convertible-issuance reversal | the repo re-run (0.9); events per year; clustering of issue dates | it reproduces: +0.54% over days 2–5, t ≥ 2 on clustered SE | it does not reproduce |
| G4 | listed mandatory convertibles | census of 2016–22 listed mandatories with history (Alpaca delisted bars, EDGAR 424B terms) | N ≥ 30 | N < 30: D7 |
| G5 | co-held loan marks (BDC) | the cost of parsing 10-Q schedules for ≥20 BDCs before 2023; loan-ID match rate | match rate ≥70% and about 150+ events a year feasible | data infeasible: PARK |
| G6 | corporate-action filter | from 0.7: how often the live book held a short in a name under a pending NAV tender, merger or liquidation, and what that cost | material (≥ the cost grid per year) | immaterial: build it as hygiene, no trial |
| G7 | CEF IPO pair | count of 2014–22 CEF IPOs (0.7); Alpaca shortability at IPO+45 days | ≥30 IPOs, mostly shortable | below that: D7 |
| G8 | XASSET slate | **declare the five tests and their published parameters** (§3) in one pre-registration header before any is run | declared | — |

---

## 3. Phase 2: trials, in order

Each is one trial. It runs only after its gates pass, its foundations exist and
the team lead approves its pre-registration.

| order | trial | counter (bar) | gates and needs | design (summary; the full version goes in the pre-registration) | kill test |
|---|---|---|---|---|---|
| 1 | **C1: corporate-action filter** on the live book | CEF 50→51 (2.80) | 0.7, G6 | A frozen-spec key, default off, with a byte-for-byte no-op proof (`/spec-change`). Do not short a fund under an announced NAV tender, merger, liquidation or open-ending, and know PDO's 2033 term | net (gross headline) not improved at matched turnover, or the sign flips across the grid |
| 2 | **E1: NAV-for-NAV CEF merger pair** | EVENTS 0→1 | G1a–c, 0.8 | Long target / short acquirer from announcement+1 to completion; pro-ration and failure handling; controls are the same pairs a year earlier and non-merging same-sponsor funds. **Consumes the 27-name holdout if any event name is in `cef_universe.csv`; the pre-registration says so** | median per deal ≤ 60bp, or group-clustered t < 2, or the control earns ≥ ½ of the effect |
| 3 | **X1: credit and rates trend** | XASSET (slate 1.79) | 0.1, G8 | HYG, LQD, IEF, TLT, EMB, PFF, MUB, BKLN, CWB; sign of the 252-day excess return ÷ 63-day vol; refreshed every 21 days; gross-capped; shorts only where shortable that day | does not beat the historical-mean rule at matched turnover (D4), or the holdout sign disagrees |
| 4 | **X2: rebalancing front-run** (SPY vs IEF/TLT) | XASSET | 0.1, G8 | Rebuild the calendar and drift signals of Harvey, Mazzoleni & Melone from SPY and IEF total returns; no sweep | fit gross Sharpe inside its 95% band around zero, or the SHY/BIL control scores as well |
| 5 | **G1: standalone short TLT variance** | GAMMA 0→1 | G2, 0.10 | Fit on VXTLT 2004–22. The defined-risk Alpaca version (iron fly or condor) is tested **once** on the 2023+ strike holdout. Meets all six conditions in SCALING §7.2 | the proxy is negative net of measured spreads; the 2008/2020 replay breaches the cap; correlation with the book is not about 0; the holdout is negative |
| 6 | **E2: convertible-issuance reversal** | EVENTS | G3 | Windows fixed as already examined (days +2..+5); 2011–22 is **not** called out of sample; the 2023–24 holdout stays untouched until opened; straight-debt control | t < 2 clustered, or net ≤ 0 at 15bp one-way |
| 7 | **C2: W10 Parts C and D** (two sleeves; a fair-value conditioner per group) | CEF (up to 5) | 0.6 (W4), W10 Part B (0 trials) | As archived: pre-declared observables per group (HY OAS and CCC−BB; muni leverage cost; SOFR for loans; PIMCO repo cost); a muni conditioner run on HY as the negative control | as archived |
| 8 | **C3: W13 stale-NAV correction** | CEF | 0.6 | GLM unsmoothing, or a nowcast from executable ETF closes | as archived |
| 9 | **C4: discount z-score on equity, preferred and multi-asset CEF families** (agenda B1) | CEF | NAV fetchers for those families | The live signal on a new family; equity CEFs double as the stale-NAV control | D1/D4, or correlation with the book ≥ 0.5 |
| 10 | E3: listed mandatory convertibles, delta-hedged | EVENTS | G4 | first-day return against the offer, then hedged P&L under a declared delta rule | median ≤ the cost grid |
| 11 | E4: CEF IPO lifecycle pair | EVENTS | G7, 0.7 | short at IPO+45 against a seasoned match; 2014–22 | 6-month abnormal return ≥ 0 after costs and measured borrow |
| 12 | X3, X4, X5: month-end extension, multi-asset trend, cross-sectional fixed-income momentum | XASSET | 0.1 | as in the agenda, Track A | as in the agenda |

**Deferred until their foundations exist:**

- **Agenda B2 (fund-of-CEF index reconstitution):** NPORT counter; count events
  first.
- **B3 (DRIP buying on payable dates):** EVENTS.
- **B4 (generalised tax-loss selling):** CEF.
- **Co-held loan marks:** gated by G5. It is a new 10-Q source, so it needs a
  counter ruling.

**Expected bars if everything runs:**

| counter | trials | bar √(2 ln N) |
|---|---:|---:|
| CEF | 50 → 58 | 2.85 |
| EVENTS | 4 | 1.67 |
| XASSET | 5 (declared slate) | 1.79 |
| GAMMA | 1 | none; judged on its pre-registered kill test |

*The CEF count takes the upper end of C2's range; the EVENTS count assumes E1–E4.*

---

## 4. Phase 3: from passing test to paper sleeve

For each passing trial:

1. A frozen-spec key that defaults to current behaviour, with a byte-for-byte
   no-op proof (`/spec-change`).
2. A pre-registered **live statistic and horizon that would reverse it** (H11).
3. A sleeve inside the CEF account with its own P&L line. All three scores are
   recorded: the fill, the auction print, and the distribution-adjusted line.
4. Delivered to prod through `/release-check` → release tag → `install_vm`
   (`docs/RUNBOOK.md` §8.6). Never a hand edit on the VM.
5. **Sizing.** Once two or more sleeves are live, combine them by Σ⁻¹·IR on
   measured correlations. The **vol target is derived under W6** (cap 20%) from
   the combined book. That, together with breadth, is the route to 10%.

## 5. Phase 4: real-capital readiness (research, no trials)

| item | question | output |
|---|---|---|
| 4.1 | Does the gate (0.5) pass? | a go/no-go note |
| 4.2 | Broker and margin: is portfolio margin available to a small entity, and at what cost? A futures account for hedges (Treasury, equity index, Cboe IBHY/IBIG/IEMD) and for trend legs; options level 3 approval | a comparison note with fetched terms. Prime brokerage, repo and CDX are out of reach for now (SCALING §7) |
| 4.3 | Capacity per sleeve against ADV (CEF median about $1m/day; merger pair about $0.5m per deal) | a capacity table; the size at which the combined book stops scaling |
| 4.4 | Firm structure, registration and fees | **not researched; it needs counsel.** No guess is made here |

---

## 6. What runs first (this week, all at 0 trials)

1. **0.4, the third P&L line** (prod) and **0.3, the shortability snapshot**
   (prod): small, and both feed the gate.
2. **0.6, W4** and **0.9, re-running the scratch analyses in the repo**.
3. **0.1, the ETF fetchers** and **0.7, the EDGAR event fetcher**. The latter
   needs the team lead's SEC user-agent string.
4. **G1a and G6** as soon as 0.3 and 0.7 exist: they decide whether E1 and C1
   are worth their trials.

**Open items for the team lead (not blocking phase 0):**

- the SEC contact user-agent for EDGAR (0.7);
- whether to buy an OPRA options data feed (0.10);
- timing, size and broker for real capital (4.2).
