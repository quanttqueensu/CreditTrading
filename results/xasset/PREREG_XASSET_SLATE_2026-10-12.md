# Pre-registration — the XASSET slate: five cross-asset tests, declared before any runs

**Date** 2026-10-12 · **Counter** XASSET, a declared slate of **N = 5** (one trial
per test, counted when each runs) · **Bar** √(2 ln 5) = **1.794** for every test
in the slate · **Gate** G8 of `results/cef/RESEARCH_PLAN_2026-10-09.md` ·
**Author** research agent, branch `research-xasset-slate`

> **Status: DRAFT — awaiting team-lead approval.** Nothing below has run. To
> write it, no strategy return, Sharpe, IC, turnover or backtest of any X-test
> was computed. The only measurements are data coverage, history start dates,
> today's Alpaca asset flags and arithmetic on the bar
> (`python3 scripts/xasset/slate_feasibility.py --alpaca`). This commit moves no
> counter, changes no spec and touches nothing on the order path. §0.1 lists
> four decisions the team lead must make before approval.

---

## 0. The declaration

| id | test | traded instruments | published rule (REFERENCES §12g) | its control | plan |
|---|---|---|---|---|---|
| **X1** | credit and rates trend | HYG LQD IEF TLT EMB PFF MUB BKLN CWB | Moskowitz, Ooi & Pedersen (2012) TSMOM | Huang, Li, Wang & Zhou (2020) TSH, same weights | §3 row 3 |
| **X2** | front-running pension and balanced-fund rebalancing | SPY, IEF | Harvey, Mazzoleni & Melone (2026) Threshold + Calendar strategy | the same weight on SHY − BIL | §3 row 4 |
| **X3** | month-end Treasury extension | IEF | Hartley & Schwarz (2019), long the last 3 sessions | IEF on every other session | §3 row 12 |
| **X4** | multi-asset trend | X1 + SPY EFA EEM GLD DBC | Moskowitz, Ooi & Pedersen (2012) TSMOM, as X1 | TSH, as X1 | §3 row 12 |
| **X5** | cross-sectional fixed-income momentum | X1 less MUB (8 names) | Baltussen, Swinkels & van Vliet (2019), after Asness, Moskowitz & Pedersen (2013) | the identical rule on SHY IEI IEF TLH TLT | §3 row 12 |

**The rules of the declaration:**

1. **N is fixed on approval.** Each test is judged against the bar for the
   slate's full size, not the running count (`docs/RESEARCH_STATE.md`,
   2026-10-09 note). If the team lead removes a test before approval, the slate
   and N shrink with it (§9). A test removed after approval leaves N where it
   was: dropping a declared test after seeing a sibling's result is itself a
   selection.
2. **Every parameter is the paper's**, quoted with its page in each test's
   table and in `docs/REFERENCES.md` §12g. Where a futures or index rule cannot
   be applied verbatim to ETFs, the mapping is stated once, here, before any
   return is seen. It is not revisited after a result. **Nothing was chosen by
   looking at our data, and nothing is swept.**
3. **The counter moves when a test runs, not now.** XASSET's trials-used column
   goes 0 → k in the same commit as the k-th run. The bar for every test is the
   declared N's.
4. **Approval approves a test, not a sleeve.** A test that passes goes through
   plan §4: a frozen-spec key with a byte-for-byte no-op proof, its H11 statistic,
   then a release.
5. **The plan's one-line summaries are superseded where they differ from a
   paper.** X1 in plan §3 reads "252-day excess return ÷ 63-day vol; refreshed
   every 21 days". The paper's parameters, used here, are 12 calendar months,
   an exponentially weighted volatility with a 60-day centre of mass, and a
   month-end refresh. X2's "SPY vs IEF/TLT" becomes SPY vs IEF, because the
   paper's bond leg is the 10-year note; TLT is not used.

### 0.1 Decisions the team lead must make before approving

| # | question | options | this draft proposes |
|---|---|---|---|
| D-a | **How the bar is applied.** The agenda (§6 item 1) read "1.79" as about a 0.46 Sharpe over 15 years, which is SR·√years ≥ √(2 ln N). At that point the repo's own deflated Sharpe (`scripts/cef/validate.py::_dsr`, PASS > 0.95) is about 0.5: a coin flip. | (i) `_dsr` > 0.95 at N, as `validate.py` implements; (ii) SR·√years ≥ √(2 ln N) | **(i)**, the only implementation in the repo. (ii) is printed beside it in every table. The required Sharpes under both are in §2.2 |
| D-b | **The slate's size** | keep 5, or cut (§9) | **cut X5 and X3** before approval (N = 3, bar 1.482). Optionally also fold X1 into X4 (N = 2, bar 1.177) |
| D-c | **D4's "betas ≤ 0.10" depends on the sleeve's scale.** It fails any long-only timing sleeve by construction: X3's TERM beta is about its notional × 3/21 | apply as written; or apply to the alpha t only for timing sleeves; or test a TERM-hedged X3 (a different, newly declared trial) | apply as written, at the scale each sleeve would trade, and say in advance that X3 fails it (§6) |
| D-d | **A correlation rule.** Plan §3 gives C4 a kill at correlation with the book ≥ 0.5; it gives none for XASSET | adopt the same rule or report only | **adopt** it: a test whose non-overlapping 21-session P&L correlates ≥ 0.5 with the book is not an independent stream and gets no sleeve |

---

## 1. Common protocol (P1–P14; every test, unless its section says otherwise)

| # | rule |
|---|---|
| **P1 Data** | Returns are `ret_total` from `data/rv/etf_panel.parquet`, or from `data/rv/etf_ohlc_extended.parquet` for the names the former lacks (MUB, TLH). It is the in-house total return, (close + distribution) / previous close − 1: yfinance raw closes up to each fetcher's `YF_LAST`, then Alpaca SIP bars (`docs/REFERENCES.md` §8; fetchers `scripts/rv/stage_universe.py`, `stage_ohlc_extended.py`). **Both panels end 2026-10-09** [V]. A missing return inside a name's live range raises (H15); today there are none. Before any P&L, each run prints the largest daily gap between this return and CRSP's (`data/etf_daily.parquet`) over 2003–2022 for the names both hold. Any name-date gap above 5bp (the build's own CRSP gate, `SPLICE_MAX_BP` in `scripts/build_etf_daily.py`) is listed, and the run halts **before any P&L** (so no trial is spent) for the team lead to rule on the source. The two are never averaged, and neither is picked silently |
| **P2 Risk-free** | FRED **DGS3MO**, fetched at run time by `scripts/gamma/fetch_fred.py DGS3MO --out <cache outside data/>` (REFERENCES §8, 2026-10-12: 1981-09-01 → 2026-10-08 [V]). The rate for session t is the last value published **strictly before** t, divided by 100 and by 252. `data/riskfree_daily.parquet` is not used: it has no fetcher and stops 2026-07-16 |
| **P3 Execution (H1)** | `H.loc[t]` is decided after t's close, filled at t+1's close and earns t+2, through `evaluate()` in `scripts/cef/band_frontier.py`. A component whose timing is set by the calendar (X2's month-end window, X3) may be decided early, because the trading calendar is published in advance. The **information** it uses is always data through t. The run asserts the alignment (H7) |
| **P4 Costs** | **Gross P&L is the headline.** Beside it is net at 5/15/30bp per unit of one-way turnover (`band_frontier._stats`), with whether the sign flips across the grid. **Borrow is not charged:** the repo holds no history of ETF borrow fees, so borrow is labelled **UNMEASURED**. Each run reports the average short notional so any rate can be applied to it. Distributions owed on shorts are inside the total returns (H15) |
| **P5 Shorting** | A name not shortable on the 2026-10-12 snapshot (MUB) is long-or-flat for the whole backtest. Names shortable on it are assumed shortable throughout history. That is a stated divergence: historical borrow availability is unknown. Live, shorts are re-read at send, and a short that has flipped is skipped (`quantt/session/run.py`) |
| **P6 Windows** | **Fit** runs from the test's first decision under its declared breadth rule (§2.2) to 2022-12-30. Nothing is fitted: "fit" means the in-sample evaluation window. Eras follow H5. **Holdout:** 2023-01-03 → 2026-10-09, 946 sessions [V]. It is opened **once per test, after that test's fit verdict is committed**. The holdout row can kill a test; it can never rescue one |
| **P7 The bar** | `validate._dsr` on the test's **gross** fit-period daily P&L at the slate's N; PASS > 0.95 (D-a). Printed beside it: SR·√years against √(2 ln N), and `_dsr` at N = 162 (the LEGACY reading, agenda §6) |
| **P8 D4, alpha only** (plan §0) | Daily OLS of the gross P&L on MKT = SPY − rf, TERM = IEF − rf and CREDIT = HYG − rf − β₆₃·(IEF − rf). β₆₃ is the rolling 63-session OLS beta through t−1 (the archived HY_XS definition, `scripts/xasset/diversification_screen.py`). X4 adds COMMOD = DBC − rf. Newey–West standard errors, 21 lags. **Pass: alpha t ≥ 3.0 and every \|β\| ≤ 0.10**, with the sleeve at the scale it would trade (each test states it) |
| **P9 Correlation with the book** | The book's daily gross total-return P&L, built as `scripts/xasset/book_profile.py` builds it (v7 band, gross-capped, `total_returns`), from the book's first position. It reports daily ρ; non-overlapping 21-session ρ (Pearson and Spearman); and 21-session ρ in HY-stress windows (the worst quintile of 21-session HY_XS), as `diversification_screen.py` does. Fit and holdout rows; **the CEF price panel ends 2026-09-28** [V, orient], so the holdout correlation stops there. Proposed rule (D-d): 21-session ρ ≥ 0.5 → no sleeve |
| **P10 Turnover first** | Before any P&L, each run prints turnover per year, mean gross and the share of sessions where the gross cap binds. If a test's turnover or gross is not what its section predicts, the run stops and the code is checked. That is a bug hunt, not a result |
| **P11 Scripts** | One per test, `scripts/xasset/x<k>_<name>.py`. Each imports `evaluate`, `_stats`, `fit_only` and `calendar_offset` from `scripts/cef/band_frontier.py`, and `_dsr` from `scripts/cef/validate.py`. **No new backtester** (`/harness`). If a month-end refresh helper is needed, it is added to `band_frontier.py` visibly, with a test |
| **P12 Outcomes** | **PASS**: every pass condition, holdout included → plan §4. **KILL**: any kill condition → KILLED in `docs/RESEARCH_STATE.md` with its D-code. **Neither**: real but below the bar → recorded as the team lead rules (WATCH or D5 inventory). It gets no sleeve and is not re-tested on these data. Kill conditions are not softened afterwards |
| **P13 No sweeps** | Robustness rows (calendar offsets, era splits, regime splits) are printed and **never chosen from** |
| **P14 The 27-name holdout** | No X instrument is in `data/cef/cef_universe.csv` (checked 2026-10-12), so no X-test consumes the set |

---

## 2. Feasibility, measured today (zero trials)

### 2.1 Instruments

`python3 scripts/xasset/slate_feasibility.py --alpaca` →
`results/xasset/slate_feasibility_2026-10-12.csv`. Alpaca flags were read on
the cef paper key at 2026-10-12T18:47:13–14Z and **are true on that date only**
(landmine 5) [V].

| symbol | used in | panel | first return | last | interior gaps | CRSP panel first | exchange | shortable | easy to borrow |
|---|---|---|---|---|---:|---|---|---|---|
| HYG | X1 X4 X5; D4 CREDIT | `etf_panel` | 2007-04-12 | 2026-10-09 | 0 | 2007-04-12 | ARCA | yes | yes |
| LQD | X1 X4 X5 | `etf_panel` | 2002-07-31 | 2026-10-09 | 0 | 2002-07-29 | ARCA | yes | yes |
| IEF | X1 X2 X3 X4 X5; X5 control; D4 TERM | `etf_panel` | 2002-07-31 | 2026-10-09 | 0 | 2002-07-29 | NASDAQ | yes | yes |
| TLT | X1 X4 X5; X5 control | `etf_panel` | 2002-07-31 | 2026-10-09 | 0 | 2002-07-29 | NASDAQ | yes | yes |
| EMB | X1 X4 X5 | `etf_panel` | 2007-12-20 | 2026-10-09 | 0 | — | NASDAQ | yes | yes |
| PFF | X1 X4 X5 | `etf_panel` | 2007-04-02 | 2026-10-09 | 0 | — | NASDAQ | yes | yes |
| MUB | X1 X4 | `etf_ohlc_extended` | 2007-09-11 | 2026-10-09 | 0 | — | ARCA | **no** | **no** |
| BKLN | X1 X4 X5 | `etf_panel` | 2011-03-04 | 2026-10-09 | 0 | — | ARCA | yes | yes |
| CWB | X1 X4 X5 | `etf_panel` | 2009-04-17 | 2026-10-09 | 0 | — | ARCA | yes | yes |
| SPY | X2 X4; D4 MKT | `etf_panel` | 1993-02-01 | 2026-10-09 | 0 | — | ARCA | yes | yes |
| EFA | X4 | `etf_panel` | 2001-08-28 | 2026-10-09 | 0 | 2001-08-20 | ARCA | yes | yes |
| EEM | X4 | `etf_panel` | 2003-04-15 | 2026-10-09 | 0 | 2003-04-14 | ARCA | yes | yes |
| GLD | X4 | `etf_panel` | 2004-11-19 | 2026-10-09 | 0 | 2004-11-19 | ARCA | yes | yes |
| DBC | X4; D4 COMMOD (X4) | `etf_panel` | 2006-02-07 | 2026-10-09 | 0 | 2006-02-06 | ARCA | yes | yes |
| SHY | X2 control; X5 control | `etf_panel` | 2002-07-31 | 2026-10-09 | 0 | 2002-07-29 | NASDAQ | yes | yes |
| BIL | X2 control | `etf_panel` | 2007-05-31 | 2026-10-09 | 0 | 2007-05-31 | ARCA | yes | yes |
| IEI | X5 control | `etf_panel` | 2007-01-12 | 2026-10-09 | 0 | — | NASDAQ | yes | yes |
| TLH | X5 control | `etf_ohlc_extended` | 2007-01-12 | 2026-10-09 | 0 | — | ARCA | yes | yes |
| AGG | reference only | `etf_panel` | 2003-09-30 | 2026-10-09 | 0 | — | ARCA | yes | yes |

For the names both hold, the in-house panel's first return is up to six
sessions later than the CRSP panel's (EFA 2001-08-28 against 2001-08-20; IEF
2002-07-31 against 2002-07-29). The two vendors' histories begin on different
days; the cause was not investigated. Every eligibility date below uses the
in-house panel, which is the one the tests run on.

### 2.2 Fit windows, and the Sharpe the bar demands

Each test's breadth rule is declared in its section. "Required SR" is the
annualised gross Sharpe at which `validate._dsr` reaches 0.95, at skew 0 and
kurtosis 3. It is found by inverting the repo's own function: arithmetic on the
bar, with no return involved [V, `slate_feasibility.py`].

| test | breadth rule | first decision | fit sessions (years) | required SR at N = 5 / 4 / 3 / 2 | SR·√yr = 1.794 (D-a ii) | D4 alpha t 3.0 ⇒ SR ≥ | LEGACY N = 162 | **published SR** (§12g) |
|---|---|---|---|---|---:|---:|---:|---|
| X1 | ≥ 5 of 9 with 12 months | 2008-04-30 | 3,694 (14.7) | 0.90 / 0.86 / 0.82 / 0.74 | 0.47 | 0.78 | 1.26 | bond trend 0.53 (1981–2011), 0.49 (new sample); credit trend: none found |
| X2 | both, 1 month | 2002-08-30 | 5,119 (20.3) | 0.76 / 0.73 / 0.69 / 0.63 | 0.40 | 0.67 | 1.07 | 1.11 (1997–2023, futures, next-day; 0.90 ex-crises) |
| X3 | IEF, 1 month | 2002-08-30 | 5,119 (20.3) | 0.76 / 0.73 / 0.69 / 0.63 | 0.40 | 0.67 | 1.07 | 0.88 (10-year zero, t = 3, 1990–2018) |
| X4 | ≥ 7 of 14 with 12 months | 2005-11-30 | 4,300 (17.1) | 0.83 / 0.80 / 0.76 / 0.68 | 0.43 | 0.73 | 1.17 | multi-asset trend 1.09 / 0.98 (a wider universe with FX) |
| X5 | ≥ 4 of 8 with 36 months | 2010-03-31 | 3,211 (12.7) | 0.96 / 0.93 / 0.88 / 0.79 | 0.50 | 0.84 | 1.36 | bond momentum 0.29 (t 1.61, not significant) / 0.31 |

**What the table says, before anything runs:**

- **The D4 alpha test binds about as hard as the bar.** At N = 3 the bar asks
  for 0.69–0.88 and D4 for 0.67–0.84. Below N = 3, cutting tests buys little.
- **X1 and X5 cannot pass even if their effects are real at the published
  strength.** X1 needs about 0.8–0.9 against 0.49–0.53; X5 needs about 0.85–0.96
  against 0.29–0.31. A failure of either teaches almost nothing about the
  mechanism. A pass would be a surprise.
- **X2, X3 and X4 are powered** at their published Sharpes. All three published
  figures are in-sample, on futures or indices and before costs.

### 2.3 Blockers found

| blocker | blocks | what clears it |
|---|---|---|
| `data/riskfree_daily.parquet` has no fetcher and stops 2026-07-16 | the excess returns of X1, X3, X4, X5 and D4 | **cleared for this slate by P2** (DGS3MO through the existing FRED fetcher) |
| **No X instrument is NYSE-listed** (ARCA or NASDAQ); `ASSET_EXCHANGE_SIP_NAME` maps NYSE only | the auction-print P&L line for any X sleeve on paper (CLAUDE.md research rules) | plan item 0.2. **Blocks phase 3, not the trial** |
| The third P&L line (distribution-adjusted) is merged but not released (`02a2fda`) | scoring any yield-carrying X sleeve on paper | plan item 0.4 release. **Blocks phase 3, not the trial** |
| MUB is not shortable | X1/X4 shorts in MUB; MUB in X5 | P5 (long-or-flat); X5 excludes MUB by declaration |
| `data/futures_daily.parquet` holds rates futures only (ZT/ZF/ZN/ZB 1998 → 2025-04-25, plus FF and SOFR), with no fetcher in `scripts/` | a longer, futures-based fit for X1/X4 | **checked and not used**: no credit, equity or commodity contracts, and stale |
| Credit ETF history begins in 2007 (HYG, PFF, MUB, EMB), 2009 (CWB) and 2011 (BKLN) | X1 and X5 statistical power | nothing in the repo. That is why §2.2 rules out X1 and X5 as informative trials |

---

## 3. Graveyard check (`/graveyard`, `docs/RESEARCH_STATE.md`)

| test | nearest dead mechanism | how it differs | stale-price well? |
|---|---|---|---|
| X1 | **`credit_rv`** (cross-sectional price-residual RV on credit ETFs; D1, gross −0.19%/yr). **`S3-wrapper`** (a credit-quality premium in costume; D4). **"Duration timing"** (agenda, closed) | A time-series signal on each ETF's **own 12-month** return, not short-horizon cross-sectional reversal. The D4 risk, that trend is long credit and duration in a bond bull market, is exactly what the TSH control and the P8 regression test. Duration timing on forward-rate models is closed; trend is listed apart from it, with the longest out-of-sample record (agenda A1) | **No.** The signal is the executable close-to-close return over 12 months, decided after the close and filled at the next close. There is no mark in it. Control C3 (shift(3)) is the check: a monthly signal must barely change |
| X2 | **`raw-flow-z`** (ETF creation/redemption flow; D1, informed and forced flow cancel). **`short-pressure`** (the rates control scored higher). **`leadlag`** (non-synchronous pricing, which shift(2) cannot harvest) | The flow is **mechanical**, signed by mandate and computed from public returns, with no flow data at all. The rates-group control that killed `short-pressure` is built in (SHY − BIL). SPY and IEF are the most synchronous closes in the market, so the `leadlag` artefact has nowhere to live; but shift(2) does give up the paper's day 1 | **No** |
| X3 | **Treasury auction cycle** (agenda, closed: 8.6bp/month gross against about 4 turns a month, D2) | A month-end index-rebalancing flow (Hartley & Schwarz §5.2; NY Fed) at 2 trades a month, not the auction cycle. **But it shares the auction trade's cost problem** (§6) | **No** |
| X4 | X1's, plus **"Daily equity → credit"** (agenda, closed; the `leadlag` mechanism) | Monthly, on each asset's own past, not one asset leading another | **No** |
| X5 | **`credit_rv`** (cross-sectional credit ETFs; D1). **Bond-level factor premia** (closed: six-month bond momentum 0.00%/month without winsorization). **Duration timing** (closed) | 12-1 continuation rather than short-horizon residual reversal. **But BSV find that "trend encompasses momentum"** (p.23). On ETFs of mixed duration, a rank of raw returns collapses into duration and credit timing, which is why its kill test is a Treasury-only control | **No**, but it is the test nearest the graveyard |

None of the five draws from the stale-price well. Two of them lean on a
control the graveyard says to name in advance: X2's rates control (as
`short-pressure`) and X5's Treasury control (as duration timing).

---

## 4. X1 — credit and rates trend

**Mechanism and the other side.** Prices under-react to news and then
over-react with a delay. Speculators "earn positive excess returns at the
expense of hedgers, who may be willing to compensate speculators for liquidity
provision in order to maintain their hedge" (MOP p.249). In credit and rates
ETFs the hedgers are holders who must keep duration and spread exposure for
liability or benchmark reasons, plus investors who use HYG, LQD and TLT as
macro hedges. They persist because the hedge is the mandate, not a view. The
wrapper's AP mechanism does not arbitrage this away: APs pin an ETF to its
basket, while the signal is the basket's own trend. Trend is a crowded,
capacity-limited trade, and its record has been "mixed since 2008" (HOP, §12b).

**Instruments.** HYG, LQD, IEF, TLT, EMB, PFF, MUB, BKLN, CWB: the agenda's
list, declared on 2026-10-08 before any return was computed. All nine were
tradable on 2026-10-12. All but MUB were shortable and easy to borrow; MUB is
long-or-flat under P5.

**Published parameters, verbatim, and how they map.**

| parameter | published | source | applied here |
|---|---|---|---|
| signal | sign of the past 12-month excess return; k = 12, h = 1 | MOP §4, p.236; Fig. 2 caption, p.237 | compounded daily excess TR over (E₍ₘ₋₁₂₎, Eₘ], where Eₘ is the month's last session. Long if ≥ 0 and short if < 0 (HLWZ's tie rule, Table 10 caption, p.791) |
| ex-ante volatility | σ²ₜ = 261 Σ (1−δ)δⁱ (r₍ₜ₋₁₋ᵢ₎ − r̄ₜ)², with centre of mass δ/(1−δ) = 60 days | MOP §2.4, eq. 1, p.233 | `ewm(com=60, adjust=True)` mean and variance of daily excess returns through Eₘ, × 261 |
| position | 40%/σₜ₋₁; "the choice of 40% is inconsequential" | MOP §4.1, eq. 5, p.236 | the spec's `vol_target_annual` in place of 40% (read at run time through `scripts/cef/spec.py`; 0.06 on 2026-10-12). A constant, so the Sharpe is unchanged |
| portfolio | equal-weighted over the Sₜ securities available | MOP §4.1, p.236 | 1/Sₜ over eligible names |
| holding | one month | MOP §4, p.236 | refreshed at each Eₘ; filled at the next session's close (H1). MOP earn month m+1 from Eₘ, so this lags them by one session |
| sample start | from 1985 "to ensure that a comprehensive set of instruments have data" | MOP p.236 | the first Eₘ with ≥ ⌈9/2⌉ = 5 names holding 12 months of returns: **2008-04-30** |
| gross cap | none | — | the spec's `max_gross_stress` (1.80 on 2026-10-12), through `_cap_gross`, the sleeve's own operator. The run reports how often it binds |

**Data and windows.** Fit 2008-05-01 → 2022-12-30, 14.7 years. In 2008 the
eligible names are LQD, IEF, TLT, HYG and PFF; all nine are eligible from
2012-03. Eras are reported from 2008. Holdout per P6.

**Controls.**

- **C1, TSH (the D4 control; plan).** The same weights with the signal
  replaced by the sign of the **inception-to-date** cumulative excess return
  (HLWZ eq. 17, p.788; volatility weighting as in Table 10 Panel B, p.791).
  H2's turnover matching cannot be met without altering one of the two published
  rules: TSH trades only when an expanding-window sign flips or σ moves. The test
  is therefore stricter than matching. **TSM must beat TSH on gross Sharpe, and
  on net Sharpe at each of 5, 15 and 30bp**, with TSH charged its own turnover.
- **C2, a placebo where serial dependence cannot operate (H12).** 200 draws,
  seeded. Each draw shuffles the panel in 21-session blocks, with one
  permutation shared by all assets so cross-correlation survives. The same rule
  runs on each draw, giving a null distribution of gross Sharpe.
- **C3, shift(3) (the stale-price check).** `evaluate(H.shift(1), R)`.

**Kill test (stated before any result).** Any one kills:

1. Fit gross Sharpe ≤ 0 (D1).
2. TSM does not beat TSH, gross or at any grid cost (D4).
3. Real gross Sharpe ≤ the 95th percentile of C2 (D1).
4. Gross Sharpe at shift(3) < ½ of shift(2)'s: a stale-price artefact (D1).
5. The holdout's gross mean has the opposite sign to the fit's (D3). At a true
   Sharpe of 0.5 this kill fires by chance with probability Φ(−0.5·√3.75) ≈ 0.17
   [arithmetic].
6. P8 fails (D4). The scale is the sleeve as declared, `vol_target_annual`-scaled.
7. 21-session ρ with the book ≥ 0.5, under D-d (no sleeve).

**Pass.** `_dsr` > 0.95 at the slate's N on the fit's gross P&L, and no kill.

**Turnover and costs.** The nearest measured relative is a 10-ETF, 12-month
sign rule with 63-day volatility and `vol_target_annual`/√n per asset:
11.1 turns a year at a mean gross of 3.3× over 2008–2022
(`scripts/xasset/trend_turnover.py`, 2026-10-08, agenda A1) **[S: not re-run;
re-running it is outside this gate's allowed checks]**. X1's 1/Sₜ scaling sits
about √n lower in gross, and turnover scales with gross. X1's own figure is
printed first (P10). The cost grid is applied per P4.

**What we expect** [U, and being wrong is the point]: a gross Sharpe of
0.3–0.6, from the bond-trend literature, because no credit-trend figure was
found. That is below the bar, so the likeliest outcome is "Neither" (P12), or a
kill by TSH if the period's mean returns carry the result (HLWZ's argument).

**Reverse once trading (H11).**

- **Fidelity, at every month-end.** The live target must equal the trial
  script's target on the same panel, to whole-share rounding. Any other
  difference halts the sleeve as a bug.
- **Reversal at 24 refreshes** of broker-confirmed sleeve P&L. Reverse if
  cumulative live gross return is below the 5th percentile of the trial's own
  24-month cumulative returns over the fit window, re-measured on the read date
  by a 21-session block bootstrap. Reverse at any time if the live drawdown
  exceeds the fit window's worst drawdown, re-measured. No threshold is written
  here as a number (H14).

**Divergences from the backtest, stated up front.**

- Paper executes `late_market` day orders, not MOC (CLAUDE.md rule 3).
- Whole shares only.
- No auction-print line until plan item 0.2 is done.
- No dividends on paper until the third line is released.
- Shorts are re-read daily.
- The account-level gross cap is shared with the CEF book; the backtest caps
  the sleeve alone.
- Borrow is unmodelled.

---

## 5. X2 — front-running pension and balanced-fund rebalancing

**Mechanism and the other side.** Pension funds, balanced funds and
target-date funds rebalance a stock–bond mix on a calendar or when the mix
drifts past a band, "as stipulated by their investment policies" (HMM pp.6–8).
Month-end is favoured, both to meet benefit payments and to track benchmarks
that rebalance monthly (pp.7–8). Their trades are predictable from public
returns, and they pay for it: "about $16 billion annually" (abstract, p.3).
They persist because the policy, not price, sets the trade. Front-runners
exist ("hedge funds do deploy front-running strategies", p.41), but the trade
is risky in timing and size (p.39), and its profits concentrate where
liquidity providers are constrained: 17.96%/yr against 3.79%/yr by liquidity
risk (Table 6 Panel C, p.38). No AP mechanism is involved: the pressure is in
the underlying stock and Treasury markets.

**Instruments.** SPY (ARCA) and IEF (NASDAQ): tradable, shortable and easy to
borrow on 2026-10-12. Control legs SHY and BIL, the same.

**Published parameters, verbatim, and how they map.**

| parameter | published | source | applied here |
|---|---|---|---|
| portfolio simulated | 60% S&P 500, 40% 10-year Treasury note; wₜ₊₁ = wₜ(1+R^SP)/[wₜ(1+R^SP) + (1−wₜ)(1+R^10Y)] | p.2; p.10; App. B, p.53 | SPY and IEF total returns. The paper uses E-mini and 10-year note futures (App. A, p.52); IEF is "iShares 7-10 Year Treasury Bond ETF" (Alpaca asset name, 2026-10-12) |
| Threshold signal | rebalance to 60% when the weight is more than δ from target; signal = drifted weight − 60% (eq. B.1); **averaged over δ = 0%, 0.1%, …, 2.5%** | eq. 2, p.12; App. B, p.53 | 26 simulated portfolios. The state is the post-trade weight at each close; the signal is the pre-trade drifted weight minus 60% |
| Calendar signal | rebalance on the last business day of each month; signal = drifted weight − 60% (eq. B.2) | p.9; App. B, p.53 | as published |
| week4 | the last 5 days of the month (Dummy^5Days) | p.14 | the month's last 5 sessions |
| strategy | R = (R^SP − R^10y)·w; w = average of −Threshold/1.5% and a modified Calendar: **sign(−Calendar) in week4, sign(Calendar₋₄) on the first business day of the new month, 0 otherwise** | §4, pp.37–38 | H = {SPY: +w, IEF: −w}. "Calendar₋₄" is read as the Calendar signal four sessions before the day it is used, the 4th-to-last session of the old month **[U reading; one declared reading, not swept]** |
| sample | 1997-09-10 → 2023-03-17 | App. A, p.52 | see below |

**Mapping under H1 (declared).** The paper's wₛ uses signals through s and
earns s+1. Here the position that earns s+1 is decided at s−1, so **every
signal is one session staler than the paper's, and every exposure day is the
paper's**. For the Calendar part, membership of the month-end window is known
in advance (P3). For the Threshold part, this means the paper's strongest day,
day 1, is lost. The paper's Fig. 4 (pp.21–22) shows the cumulative pressure
still building to day 4 (Threshold) and day 2 (Calendar), so part of the
effect lies inside our reach. A same-day variant (signals from 15:50 prices,
MOC the same day) is **not** this trial.

**Data and windows.** Fit from the first decision on 2002-08-30 to
2022-12-30, 20.3 years. Every fit year
lies inside the paper's own sample, so the fit row is a replication on ETFs
under shift(2), not out-of-sample evidence. **The holdout is the only part
after the paper's sample** (from 2023-03-18). The paper finds the effect
significant only from the early 2000s (p.4), which is where our fit begins.

**Controls.**

- **C1, the same w on SHY − BIL (plan; H12).** Rebalancers trade equities
  against intermediate Treasuries, not two-year notes against bills. The
  control is turnover-matched by construction, being the same w. Its window is
  shorter (BIL from 2007-05-31).
- **C2, a mid-month placebo for the Calendar part (diagnostic).** Sessions
  6–10 of each month replace week4.
- **C3, 1,000 seeded permutations of the Calendar part's monthly signs
  (diagnostic).**

C2 and C3 describe the Calendar part only. They are not kills.

**Kill test.** Any one kills:

1. The fit's gross Sharpe t-statistic (SR·√years) is inside ±1.96, the plan's
   "95% band around zero" (D1).
2. C1's fit gross Sharpe ≥ ½ of X2's, same sign: it is not rebalancing
   pressure (D1).
3. The holdout's gross mean has the opposite sign to the fit's (D3).
4. P8 fails, at the published scale (|w| as constructed) (D4).
5. ρ with the book ≥ 0.5, under D-d.

**Pass.** `_dsr` > 0.95 at the slate's N, and no kill.

**Turnover and costs** [arithmetic, not measured]:

- **The Calendar part alone** moves the modified signal by about 4 units a
  month: 0 → ±1 at week4, a flip to the opposite sign on day 1, then back to 0.
- **In the book's terms** that is 2 units of w, on two legs: about 48 one-way
  turns a year, a drag of at least 240 / 720 / 1,440 bp/yr at 5 / 15 / 30bp.
  The Threshold part adds to this.
- **Against the published gross** of 10.20%/yr (Table 6), the sign flips by
  30bp even if the effect were fully intact.
- **The grid is the desk's CEF-calibrated grid.** SPY and IEF trade far tighter
  [U: not measured here; plan items 0.2 and 0.5].

**What we expect** [U]: a gross Sharpe well below the published 1.11, because
day 1 is lost. Our range is 0.2–0.8. Positive skew if the effect is there.

**Reported beside it.** Correlation with X3 (both month-end flows; agenda A3)
and with the book (P9).

**Reverse once trading (H11).**

- **Fidelity, daily.** Live w equals the trial script's w on the same panel;
  any other difference halts the sleeve.
- **Reversal at 252 sessions** (about 12 month-end windows). Reverse if the
  live gross Sharpe is below the 5th percentile of the trial's own overlapping
  252-session Sharpes over the fit window, re-measured on the read date. The
  drawdown rule is the same as X1's.

**Divergences.**

- **Instruments.** Futures carry no distributions and their financing is
  implicit. The ETFs pay distributions, so total returns are used, and the IEF
  leg is short a distributing fund.
- **Execution.** `late_market` on paper.
- **Scoring.** No auction-print line until plan item 0.2.

---

## 6. X3 — month-end Treasury extension

**Mechanism and the other side.** Benchmark-relative holders of Treasuries
buy duration at month-end. Insurers buy the securities added to the Bloomberg
Barclays US Treasury Index, which rebalances on the final trading day (H&S
§5.2, pp.18–20). Window dressing adds to it. "The entire term premium is
concentrated in the last few days of the month" (p.21). Since 2020,
last-day benchmark volume is about 46% above normal and price impact about 28%
lower. The NY Fed authors conjecture that passive funds rebalancing to
month-end indices explain this (§12g) [V]. The buyers persist because their
tracking error is measured against an index that rebalances on that day.

**Instruments.** IEF only (NASDAQ; tradable; long-only, so no short is needed).

**Published parameters, verbatim, and how they map.**

| parameter | published | source | applied here |
|---|---|---|---|
| trade | buy "t trading days before the end of the month", sell "on the last day of the month (at the close of business)" | §2.1, p.4 | long IEF from the close of E−3 to the close of E (earning E−2, E−1, E). H.loc = 1 on E−4, E−3 and E−2 under H1, decided early from the calendar (P3) |
| t | 3: the paper's worked example. Excess return largest over the last 3–5 days (p.5); Sharpe best over 2–3 days (p.7) | p.5; Tables 1 and 3, pp.25–26 | **3**. It sits in both of the paper's ranges, and it was taken before any look at our data. The paper chose it from its own sweep over 1–10, so the value carries their selection |
| maturity | the 10-year (0.25%/month, SE 0.05; Sharpe 0.88) | p.5; Tables 1, 3 | IEF, the nearest listed fund. Its duration is shorter than a 10-year zero, so the per-window return scales down [U: IEF's duration not fetched]; the Sharpe does not |
| financing | excess over GC repo | §2.1, p.4 | excess over DGS3MO (P2) |
| size | a plain long position | §2.1 | notional 1.0 of the sleeve |

**Data and windows.** Fit from the first decision on 2002-08-30 to
2022-12-30, 20.3 years. 2002–2018 lies inside the paper's sample; **2019–2022 is after it**, and is printed as its
own row. Regime rows split at the move to T+2 settlement (compliance date
2017-09-05 [S: law-firm memos and a Deloitte summary of SEC Release 34-80295;
the release itself not fetched]) and, in the holdout, at the move to T+1
(2024-05-28, §12b [V]). Each split is reported, never chosen.

**Control (H12).** IEF over **every other session of the month**, at the same
notional: the paper's own comparison (eq. 2; Table 1 lower panel, 0.07%/month,
SE 0.13; Table 3, Sharpe 0.11). It is turnover-matched by construction, with
two trades a month each. If the month-end window does no better, X3 is just
the term premium.

**Kill test.** Any one kills:

1. The fit's gross Sharpe t inside ±1.96 (D1).
2. The other-sessions control's fit gross Sharpe ≥ ½ of X3's (D1).
3. The holdout's sign disagrees with the fit's (D3).
4. **P8 fails (D4). Stated in advance: it will.** X3's unconditional TERM beta
   is about notional × (3 of about 21 sessions) ≈ 0.14 at notional 1. It
   exceeds 0.10 at any notional above about 0.7 [arithmetic]. Under the
   alpha-only ruling, X3 can pass only if the team lead decides D-c otherwise.
5. ρ with the book ≥ 0.5, under D-d.

**Pass.** `_dsr` > 0.95 at the slate's N, and no kill.

**Turnover and costs** [arithmetic]:

- **Turnover** is exactly 24 one-way turns a year at notional 1, a drag of
  120 / 360 / 720 bp/yr at 5 / 15 / 30bp.
- **The published gross** for a 10-year zero is 0.25%/month, 300 bp/yr, and
  less for IEF. **Net at 15bp is expected to be negative by arithmetic before
  anything runs** (D2), as the agenda warned.

**What we expect** [U]: a positive gross effect of about the published Sharpe
in 2002–2018, smaller after it. D2 at 15bp. D4 failure on β.

**Reverse once trading (H11).** Fidelity at every window. Reversal after 36
windows: reverse if the live sum is below the 5th percentile of the trial's
own 36-window sums over the fit window (re-measured).

**Divergences.** As X2's. The sleeve trades twice a month and holds IEF for
three sessions, so on the paper account its whole cost record is two
`late_market` fills a month.

---

## 7. X4 — multi-asset trend

**Mechanism and the other side.** As X1, across asset classes. MOP's own
universe is commodities, equity indices, bonds and currencies (§2).

**Instruments.** X1's nine, plus SPY, EFA, EEM, GLD and DBC (all ARCA;
tradable, shortable and easy to borrow on 2026-10-12). There is no currency
leg: the plan lists none, and adding one now would be choosing.

**Published parameters.** X1's table, unchanged: MOP §2.4 and §4.1, pp.233
and 236. The breadth rule is ≥ ⌈14/2⌉ = 7 eligible, which first holds on
**2005-11-30** (SPY, EFA, LQD, IEF, TLT, EEM, GLD). **The decision is on the
combined sleeve only.** Rows by asset class are printed and never selected
from (agenda A4).

**Data and windows.** Fit 2005-12-01 → 2022-12-30, 17.1 years. The published
comparator is BSV's multi-asset trend, 1.09 in replication and 0.98 out of
sample (Tables II and IV, pp.42 and 44). It is an equal-volatility composite
of four asset classes over many markets, FX included, so it is an upper
reference for 14 ETFs, 9 of them credit and rates.

**Controls.** C1 TSH, C2 placebo and C3 shift(3), exactly as X1.

**Kill and pass.** As X1. P8 adds COMMOD.

**X1 and X4 are not independent trials:** X1's nine names carry 9/14 of X4's
equal risk budget. The bar counts them as two trials anyway, which is
conservative.

**Turnover, expectation, H11 and divergences.** As X1. The expected gross
Sharpe is 0.4–0.8 [U].

---

## 8. X5 — cross-sectional fixed-income momentum

**Mechanism and the other side.** The same under-reaction as X1, expressed as
relative strength across fixed-income ETFs: long the 12-1 winners, short the
losers. The other side is the same slow-moving holders. **BSV find the trend
factors "subsume the momentum factors" (p.23).**

**Instruments.** X1's names less MUB, which is not shortable, so the
long-short cross-section is buildable: HYG, LQD, IEF, TLT, EMB, PFF, BKLN, CWB.
Control: SHY, IEI, IEF, TLH, TLT, all shortable on 2026-10-12.

**Published parameters, verbatim, and how they map.**

| parameter | published | source | applied here |
|---|---|---|---|
| signal | "the 12-month-minus-1-month excess return" (MOM2–12) | BSV App. A.I, p.52; AMP §I.B, pp.936–937 | compounded excess TR from E₍ₘ₋₁₂₎ to E₍ₘ₋₁₎ |
| weights | zₜ(Rank(Sᵢₜ) − (Nₜ+1)/2); at least two markets | BSV App. A.II, p.54; AMP eq. 1, p.938 | zₜ sets one dollar long and one dollar short (AMP) before sizing |
| sizing | each position divided by its 3-year rolling volatility on monthly data, floored at the larger of the cross-section's 10% quantile and 2.5% | BSV pp.54–55 | as published, with 36 monthly excess returns. Hence the 36-month eligibility |
| factor scaling | a 10-year rolling window scaling each factor to 10% ex-ante volatility | BSV p.55 | **cannot be applied:** it needs ten years of factor history, which does not exist before 2020. It is replaced by the constant `vol_target_annual`, which leaves the Sharpe unchanged except through the cap |
| rebalance | monthly | BSV p.55 | at each Eₘ, under H1 |
| start | — | — | ≥ ⌈8/2⌉ = 4 eligible: **2010-03-31** |

**Data and windows.** Fit 2010-04-01 → 2022-12-30, 12.7 years, the shortest in
the slate.

**Control (agenda A5; H12).** The identical rule on SHY, IEI, IEF, TLH and
TLT. If a Treasury-only momentum scores as well, X5 is duration timing, which
is closed. Kill if the control's fit gross Sharpe is ≥ ½ of X5's. The
comparison is on gross Sharpe only, with both turnovers printed: it diagnoses
duration timing and chooses no policy. Also reported as a diagnostic: X5's alpha in a spanning regression on X1's P&L
(BSV's test).

**Kill test.** Any one kills:

1. Fit gross Sharpe ≤ 0 (D1).
2. The Treasury control (D1, duration timing).
3. The holdout's sign disagrees (D3).
4. P8 fails (D4).
5. ρ with the book ≥ 0.5, under D-d.

**Pass.** `_dsr` > 0.95 at the slate's N, and no kill.

**Turnover and costs.** Rank changes at month-ends. No measured relative
exists in the repo; the figure is printed first (P10).

**What we expect** [U]: a gross Sharpe of 0–0.4. The published 0.29 is not
significant (t 1.61, Table II).

**H11 and divergences.** As X1.

---

## 9. The slate's size: what each test can learn per trial

Rank by **information gained per trial**, not by expected Sharpe.

| rank | test | can it pass if the published effect is real? | what a result would teach | verdict |
|---|---|---|---|---|
| 1 | **X2** | yes: 1.11 published against 0.67–0.76 required, though shift(2) costs it day 1 | whether a mechanical, mandate-driven flow survives a one-session delay on ETFs, with a post-publication holdout. A failure closes it in one trial | **keep** |
| 2 | **X4** | plausibly: 0.98–1.09 published for a wider universe, against 0.73–0.83 | whether ETF-implementable trend clears the bar at all | **keep** |
| 3 | **X1** | **no**: 0.49–0.53 published, against 0.78–0.90 | a failure says nothing about the mechanism; a pass would be a surprise. It is nested in X4 | **keep only for a credit-only answer**; otherwise fold into X4 as printed rows never chosen from |
| 4 | **X3** | gross yes (0.88 against 0.67–0.76), **but D4's β fails by construction and net at 15bp is negative by arithmetic** | almost nothing on deploy-or-not, which is already answered no under the alpha-only ruling. Re-declare it as a TERM-hedged test if the team lead wants the month-end flow measured | **cut** |
| 5 | **X5** | **no**: 0.29–0.31 published (t 1.61 in replication), against 0.84–0.96 | spanned by trend (BSV p.23) and the nearest of the five to the graveyard (`credit_rv`, duration timing) | **cut** |

| option | slate | N | bar √(2 ln N) | required SR (`_dsr` > 0.95) |
|---|---|---:|---:|---|
| A, as planned | X1–X5 | 5 | 1.794 | §2.2 |
| B | cut X5 | 4 | 1.665 | X1 0.86, X2 0.73, X3 0.73, X4 0.80 |
| **C (proposed)** | **X1, X2, X4** | **3** | **1.482** | **X1 0.82, X2 0.69, X4 0.76** |
| D | X2, X4 | 2 | 1.177 | X2 0.63, X4 0.68 |

D4's alpha test (X1 0.78, X2 0.67, X4 0.73) binds about as hard as option C's
bar. That is why option D gains less than its lower bar suggests.

---

## 10. Trial accounting

- **XASSET today: 0 trials.** On approval the slate's N is fixed: 5 as
  declared, or the size the team lead chooses under D-b. The trials-used column
  moves in the same commit as each run, never at approval.
- **`docs/RESEARCH_STATE.md` changed in this commit: no.** Nothing ran.
- **The CEF, EVENTS and GAMMA counters are untouched.** The 27-name holdout is
  not consumed (P14). The 2023-01-01 time holdout stays sealed until each
  test's fit verdict is committed (P6).
- **Sources:** `docs/REFERENCES.md` §12g, with the §12b rows amended in place
  where this draft re-read them; the DGS3MO row is in §8.
- **Zero-trial script:** `scripts/xasset/slate_feasibility.py`, with its tests
  in `scripts/xasset/tests/`.
