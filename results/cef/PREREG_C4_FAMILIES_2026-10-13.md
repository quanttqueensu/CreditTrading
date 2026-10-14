# Pre-registration — C4: the live discount z-score on five CEF families, pooled

**Date** 2026-10-13 · **Counter** CEF, one trial (50 → 51 if C4 is the next CEF
trial) · **Pass bar** `scripts/cef/validate.py::_dsr` > 0.95 at the CEF
counter's N · **Plan** `results/cef/RESEARCH_PLAN_2026-10-09.md` §3 row 9
(agenda B1) · **Author** research agent, branch `research-prereg-c4-e2`

> **DRAFT — awaiting team-lead approval; the counter moves only in the commit that records approval.**
>
> **Nothing has run.** No discount z-score, position, P&L, Sharpe, IC,
> turnover or correlation of any family fund was computed to write this. The
> only measurements are counts on the data: the pool, what each declared
> mask removes, eligible breadth per session, the first session the pool can
> trade, and arithmetic on the pass bar
> (`python3 scripts/cef/c4_feasibility.py`, run 2026-10-13, output
> `results/cef/c4/c4_feasibility_output_2026-10-13.txt`). This commit moves no
> counter, changes no spec and touches nothing on the order path.

---

## 0. The declaration in one table

| item | declared |
|---|---|
| what is tested | the live sleeve's discount z-score, every parameter read from the frozen spec, run as one pooled cross-section on equity-domestic, sector, covered-call, preferred and multi-asset CEFs |
| universe | 68 funds on the 2026-10-12 Alpaca snapshot (§4.1), re-read at run time |
| eligible per session | median 10 over the fit, 13 in the holdout years; the book can trade on 89.5% of fit sessions (§11) |
| fit window | first position (2006-01-18 on today's universe) → 2022-12-30, 16.9 years |
| holdout | 2023-01-03 → the families panel's last date at run time (2026-10-09 today: 946 sessions), opened once |
| headline | gross Sharpe of the tradable sleeve's daily total-return P&L, with net at 5 / 15 / 30bp beside it |
| named control | the fresh-NAV sub-book: the stale-NAV control of plan row 9 (§8) |
| kills | D1 (NW t < 1.96, the control, the placebo, shift(3)), D4 (alpha t < 3.0 or any \|β\| > 0.10 at the vol target), correlation with the book ≥ 0.5 (plan row 9), D3 (holdout sign) |
| pass | every kill survived, `_dsr` > 0.95 at N, and the holdout sign agrees |

### 0.1 Decisions left for the team lead

Each is answered in this draft by a stated default, so the document is
complete as written. Approval approves the defaults unless a ruling says
otherwise.

> **Team lead, 2026-10-13: defaults 1–7 accepted** ("C4 on the draft's
> defaults"). Still open at final approval: decision 8 (spend now or defer).
> One more item also goes to that approval. The XASSET slate's adversarial
> review (2026-10-13, finding 5) showed that a holdout ending at "the panel's
> last date at run time" lets whoever runs the test choose the end date. The
> same wording is in §0 and §7 here. The proposed fix is a fixed end of
> **2026-09-30**, matching the slate. Nothing has changed in the text until
> it is approved.

| # | decision | this draft's default | the alternative, and what it changes |
|---|---|---|---|
| **1** | **The evaluation set** (`results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md`, "What should change in the order of phase 2", item 1: score C-trials on the deployed fit sample, or on the WIDE set). **Does C4 depend on it? Only through the correlation kill** (§9). C4's own universe is point-in-time by construction, because a today's-composition C4 would select on 2026 liquidity, which is look-ahead | the kill reads the **larger** of the correlation with the deployed series and with the WIDE series | name one series; the kill then reads that one only |
| **2** | Plan row 9 makes ρ ≥ 0.5 with the book a kill. The 2026-10-12 XASSET ruling 3 made correlation report-only for that slate | **kept as a kill.** C4 is the same signal on the same kind of wrapper, so ρ ≥ 0.5 means it is the book's own bet again, not new breadth. That reason does not apply to XASSET | report-only, as XASSET |
| **3** | Funds Alpaca does not list as shortable | **left out on both sides** (the v7 universe rule of 2026-09-28): 68 of 105 | keep all 105 with shortability assumed throughout (reported as R-S in any case); median breadth 14 instead of 10 |
| **4** | The global-equity family (NAVs struck at foreign closes) | **left out**: it is the `single-fund-PD` structure, and with a median of 1 eligible fund it cannot form its own control (D7) | include it in the pool |
| **5** | The NAV-repeat mask (§4.3) | **on** for the headline | headline on the raw vendor panel (reported as R-Q0 in any case) |
| **6** | Band width | **the spec's `band_width`, as read.** It was derived on the credit book's target dynamics, and C4's per-name weights are smaller, so it is relatively wide for C4: C4 trades less and gives up some gross (conservative for the headline) | re-derive by the cube-root law on C4's fit-period target dynamics at Stage 0 (no P&L), at the spec's implied cost |
| **7** | When the counter moves | in the commit that records approval (this draft's mandated wording, and the `/prereg` skill's) | at the run (the XASSET convention) |
| **8** | Whether to spend the trial now | §11.3's power: P(pass) is **0.31** if C4's true gross Sharpe equals the deployed credit book's live 0.96, and 0.37 at 1.00 | defer |

---

## 1. What is tested, and what is not

**Tested:** whether the live discount signal earns alpha on closed-end funds
outside credit, as one pooled sleeve. Nothing in the live book changes. A
pass makes C4 a candidate sleeve inside the CEF account (plan §4), which then
needs its own frozen-spec key with a byte-for-byte no-op proof
(`/spec-change`), its H11 statistic (§14), a release and a team-lead go.

**Not tested:**

- per-family sleeves: four of the six families have at most 3 usable funds a
  day (families note §6), and six trials would cost six counts against one;
- a new signal, window, threshold or sizing rule: there is no free parameter;
- the 27-name holdout: no fund here is in `data/cef/cef_universe.csv` (the
  families build asserts it before every write), so C4 does not consume it.

## 2. Mechanism, who is on the other side, and the graveyard

**Mechanism.** The same one the live book trades. A CEF's discount wanders
around a fund-specific level; deviations from the fund's own trailing
history revert, mostly through the price (W4 §5 on the credit book: the
discount leg is 116% of the total in the fit [S, `scripts/cef/w4_artifacts.py`,
not re-run here]). No AP mechanism closes a CEF's discount, so the reversion
is left to discretionary buyers.

**Who is on the other side.** Retail holders who sell on price and
distribution news, and buy for yield. Equity and covered-call CEFs are held
for their managed distributions (families note §6 item 5). Discount moves are
partly sentiment (Lee, Shleifer & Thaler 1991 [S]) and mostly idiosyncratic
(Pontiff 2006: about 85% of CEF excess volatility [S]); idiosyncratic risk,
not cost, limits the arbitrage (`docs/REFERENCES.md` §1).

**The horizon gap.** No published study measures equity-CEF discount
reversion at 1–5 days. The papers are monthly, with half-lives of 4–8
months, and they **disagree on whether equity or fixed-income funds revert
faster** (Ji & Kim 2013 against Patro, Piccotti & Wu 2014; REFERENCES §1,
[V] negative). No prior about the sign of the difference is assumed here.

**Graveyard** (`/graveyard`, `docs/RESEARCH_STATE.md`):

| dead mechanism | why C4 is not it, and where the risk remains |
|---|---|
| `single-fund-PD` (the ETF premium was NAV staleness; the price correctly led a stale NAV) | That is why the global family is out (decision 4), why the stale-NAV control decides (§8), and why vendor stale copies are masked (§4.3). **Risk remains** in funds outside the global family that hold foreign assets (global allocation, international covered-call); reported, not removed (§10, R-G) |
| `leadlag` (non-synchronous prices) | P&L is on executable closes under shift(2), and shift(3) is a kill test (§8) |
| the stale-price pattern (six of thirteen deaths) | The shift(3) test and the CRSP no-closing-trade flag (§4.4, Q4) |
| control scores as well as the treatment (three deaths) | The placebo is a kill (§8) |
| `z_window = 63` (an argmax) | Nothing is swept; every parameter is the spec's |

C4 is the live signal on new funds. It is not a rebuilt dead mechanism.

## 3. Divergences from the backtest, stated up front

Everything a live C4 sleeve would do that this trial does not:

1. **The decide-time NAV defect.** Live, Yahoo serves a NAV row dated D that
   carries D−1's value and corrects it later: 28 of 73 checkable name-days on
   the laptop's sessions (`results/cef/LIVE_NAV_QUALITY_2026-10-12.md` §5).
   Neither the archive nor this backtest can see it. **A live C4 sleeve needs
   the stale-copy gate of that note's §6 before it trades.** It is a phase-3
   blocker, not a trial blocker.
2. **The NAV-repeat mask** (§4.3) is not in the live sleeve. A C4 sleeve would
   carry it as part of its spec key.
3. **Shortability** is one snapshot here and is re-read at every send live.
   History is unknown (CLAUDE.md landmine 5).
4. **Borrow** is not in the history (§6).
5. **`min_abs_weight` re-neutralisation** (0.005) and **whole shares**: the
   sleeve has them, the harness does not (as in the band pre-registration).
6. **Reference state** is actual holdings live, the stored target here.
7. **Paper execution** is `late_market` day orders, not MOC (CLAUDE.md order
   rule 3). Paper has no auction, credits no distributions and charges no
   borrow: the third, distribution-adjusted P&L line is the relevant paper
   score.
8. **Eight of the 68 funds are not NYSE-listed** (4 Nasdaq, 4 NYSE American).
   Their auction-print line needs plan item 0.2.
9. **The account's gross cap** is shared with the CEF book live; here C4 is
   capped alone.
10. **Survivorship.** CEFConnect lists only live funds; a fund that
    liquidated or merged before 2026-10-12 is in no panel here. The bias
    favours funds that survived. Its direction for a dollar-neutral discount
    book is unknown, and it cannot be measured from the repo.

---

## 4. Data

### 4.1 Universe

**Source:** `data/cef_families/` (gitignored), built and described by
`results/cef/CEF_FAMILIES_DATA_2026-10-12.md` ("the families note") and
`docs/REFERENCES.md` §12h. Panels end 2026-10-09.

| step | rule | funds (2026-10-12) |
|---|---|---:|
| candidates | CEFConnect Morningstar families, Alpaca active and `tradable` | 164 |
| family | equity-domestic, sector (incl. real estate and MLP), covered-call, preferred, multi-asset. **Global equity left out** (decision 4) | 134 |
| NAV | a yfinance NAV series exists (16 do not: families note §4) | 118 |
| vendor defects | **the 14 flagged funds are left out on every date**: AWP, BST, CLM, CRF, GAB, GGT, GUT, IAF, JRI, NRO, RIV, SRV, UTG, ZTR (IAF is also global). For eight of them yfinance re-bases the close with no event in its own split record, so a flagged *date* cannot be identified from yfinance; the whole fund goes | **105 (the pool)** |
| shortable | Alpaca `shortable` on the snapshot read before the run (decision 3). On 2026-10-12T18:27Z: 68, all `easy_to_borrow` | **68 (the universe)** |

By family, the 68: sector 23, covered-call 15, multi-asset 13, preferred 10,
domestic 7.

**The shortable step is the one 2026 state the universe uses.** Every other
filter is point in time (§4.2). It is accepted for the reason the v7
universe rule gave: a fund that cannot be shorted cannot sit in a
dollar-neutral sleeve. Its direction of bias is unknown. R-S reports the book
without it, and decision 3 is the team lead's. The stale-NAV control's sub-book (§8) is the 45 domestic, sector
and covered-call funds among them.

**At run time** the shortable step is re-read (H14) from the latest daily
`borrow_snapshot` of the collector (plan 0.3), or a fresh read-only
`GET /v2/assets`, and the count is printed beside the 68 measured here.

### 4.2 Daily eligibility (the sleeve's filters, point in time)

A fund is eligible on session *t* when all of these hold:

- a paired yfinance close and NAV, both above $0.50 (`build_panel`);
- its discount is not masked on *t* (§4.3);
- at least 120 unmasked discounts in the trailing `z_window` sessions,
  through *t*−1;
- ADV (mean close × volume over 63 sessions, at least 21 present, through
  *t*−1) at or above the spec's `min_adv_usd`. Read through
  `scripts/cef/spec.py`: $3,000,000 on 2026-10-13.

The book trades when at least the spec's `min_names` (6) are eligible.
Otherwise it holds the previous target, as `build_targets` does.

### 4.3 The two masks, declared before any return is seen

**M1, the NAV repeat.** A fund-day whose yfinance NAV equals that fund's
previous yfinance NAV row exactly has **no discount that day**. It is not
eligible, and it does not count toward the z-window history. Its price stays
in the panel, so returns and ADV are unaffected.

Why this rule and not a CEFConnect-based one:

- every vendor stale copy is, by definition, such a repeat;
- CEFConnect can check only Fridays before 2025-10-13 and every day after, so
  a mask built on it would be four to five times stronger in the holdout's
  last year than in the fit;
- the repeat rule needs no second source and acts identically in every year.

What it costs, measured today [V, `c4_feasibility.py` §2–3]:

- it removes **4.1–8.4% of otherwise-eligible fund-days in each era**,
  8.4% in the holdout years;
- most repeats are not stale copies. On the dates CEFConnect can check, stale
  copies are 1–25% of repeats in 2005–18, 2021 and 2025–26, and 41–77% in
  2019, 2020 and 2022–24, the vendor episodes. In other years the mask mostly
  drops NAVs that both vendors show unchanged. That costs breadth, not bias:
  an unchanged NAV under a moving price is the stale-NAV case the control
  exists for.

**M2, zero volume.** A fund-day with zero volume has no discount that day.
Measured: **0** such fund-days among otherwise-eligible ones over 2005–2026,
so M2 is a guard.

**Reported, never chosen:** R-Q0 (no masks) and R-Q1 (only the stale copies
CEFConnect confirms are masked).

### 4.4 Returns (H15)

| leg | source | rule |
|---|---|---|
| **through 2024-12-31** | **CRSP `dsf.ret`**, the total return with each distribution on its ex-date. All 105 pool funds map to a current permno (families note §3.4) | primary. QQQX's pre-2014 history comes from a predecessor permno: it is used only if that permno's raw price equals yfinance's close within $0.005 on at least 95% of common dates (DG-C4-1); otherwise QQQX enters at its current permno's first date |
| **from 2025-01-02** | yfinance close, with yfinance dividends and splits from `cef_actions.parquet`: r = (1 + r_px)·k − 1 + D/P₍ₜ₋₁₎, the harness's `total_returns` formula | the only source after CRSP ends; all 105 pool funds have yfinance distributions in 2025–26 |
| any name-date with a price and no return in the declared source | — | **raise** |

**The seam** (2024-12-31 / 2025-01-02) is flagged, Q7. **The cross-check**
(Q6) rebuilds the yfinance total return over 2013–2024 and lists every
session that differs from CRSP by more than 5bp, with both values. The two
are never averaged. The yfinance distribution panel was measured missing
large specials on the live 13 (REFERENCES §8), which is why CRSP is primary
where it exists.

### 4.5 Data gates (zero trials; any failure halts before a return is computed)

| gate | what | done when |
|---|---|---|
| **DG-C4-1** | Extend `scripts/data/stage_crsp_cef_families.py` to stage `ret` and `retx` for the 105 pool permnos (and QQQX's predecessor), to a gitignored cache | every pool fund has CRSP returns over its CRSP span; the QQQX rule above is decided by its own count |
| **DG-C4-2** | **Harness extension, not a new backtester.** `build_panel` / `build_targets` take an optional panel source (prices, NAV) and an optional discount mask; `total_returns` takes the families' actions file. Defaults leave behaviour unchanged, proved by the sha256 of `pickle.dumps(build_targets())` before and after, as the 2026-09-28 `universe` argument was | the no-op hash matches; tests cover the mask and the source switch, and fail against the old code |
| **DG-C4-3** | Factors: French FF5 + UMD daily and monthly (`scripts/data/fetch_ff_factors.py`), Pástor–Stambaugh (`fetch_pastor_liquidity.py`), IEF and HYG total returns from `data/etf_daily.parquet`. Vintages recorded | they cover the fit and the holdout to the panel's last date minus the factor lag |
| **DG-C4-4** | The shortability snapshot (§4.1) | read and printed |
| **DG-C4-5** | The book series for the correlation kill (§9): `scripts/xasset/book_profile.py`'s deployed v7 series, and the WIDE series (the same with the ADV floor off, through a default-off harness flag with its own no-op proof) | both build, and the deployed one reproduces W4's first position (2013-06-21, re-measured today [V]) |

**The quality screen** runs at Stage 0 on the primary return of every
universe fund, fit and holdout, and lists every flag by fund and date. It is
the XASSET slate's P2: Q1 missing (halt); Q2 three or more unchanged closes
(flag); Q3 zero volume (M2); Q4 CRSP `prc` < 0, no closing trade, on an
eligible fund-day (flag; families note §3.4 counts 2,356 such yfinance bars,
the most on GRF, FUND, RCG and CRF, none of them in the universe); Q5 robust z > 10 or |r| > 15% (flag); Q6 the
cross-check above; Q7 the seam. **Nothing is dropped, filled or altered by
the trial script.** A flag found to be a vendor defect is fixed in the
fetcher with a dated note before any P&L, so no trial is spent.

---

## 5. Signal, rebalancing, sizing and execution

Every parameter is read through `scripts/cef/spec.py` at run time. The
values below are today's (`cef_discount.v7.20260928`) and are printed in the
run's header.

| element | rule | spec key (2026-10-13) |
|---|---|---|
| discount | d = 100 (P − NAV) / NAV, yfinance raw close and NAV | — |
| z-score | z = clip((d − μ) / σ, ±4); μ and σ are the rolling mean and sd over `z_window` sessions, at least 120 present, **through *t*−1** | `z_window` 252 |
| weights | w = −(z − z̄) / Σ\|z − z̄\| over the eligible funds: dollar-neutral, gross 1. One pooled cross-section: every fund is ranked against its own history, then all are demeaned together | `min_names` 6 |
| sizing | × clip(`vol_target_annual` / σ̂₆₃, 0.2, 2.5), σ̂₆₃ the annualised sd of the current weights' trailing 63-session returns. This is the live sleeve's own rule, and it sizes the sleeve to the spec's vol target | `vol_target_annual` 0.06 |
| policy | `band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)`: the live v7 band, traded to the edge, with the gross ceiling on the held book | `band_width` 0.048; `max_gross_stress` 1.80 |
| execution | `evaluate(H, R)`: decide *t*, fill at the close of *t*+1, earn *t*+2 (H1) | — |

**No fit-window constant is applied.** The live rule is the sizing rule; a
second scaler would make C4 a different strategy from the one the live book
runs. D4's betas are nevertheless read **at the spec's vol target** (ruling 4
of 2026-10-12): each is multiplied by `vol_target_annual` / σ_fit, where
σ_fit is the tradable sleeve's realised annualised vol over the fit window.

**The band width is the spec's** (decision 6). Stage 0 prints C4's turnover,
the share of name-days on which the band binds, and the cap-binding share.
Any later width for a C4 key is a re-derivation from target dynamics, never
from this trial's P&L.

**Alignment (H7)** is asserted in the run: μ, σ, ADV and the history count
are `.shift(1)`; the held book is `H.shift(2)`; the holdout guard
(`fit_only`) raises on any 2023+ date reaching a fit statistic.

## 6. Costs, borrow and shorting

- **Gross is the headline.** Net is beside it at 5, 15 and 30bp per unit of
  one-way turnover (`band_frontier._stats`), labelled, never mixed in, with
  whether the sign flips across the grid (H3). No measured per-name cost
  exists for these funds.
- **Borrow is charged separately and labelled (H4)**, through
  `band_frontier.borrow_charge()` on the held short book (`H.shift(2)`,
  Alpaca's actual/360 day count on 102% collateral):
  - **Alpaca's published live terms:** an easy-to-borrow short pays no
    borrow fee (Brokerage Fee Schedule, revised 2026-10-01; REFERENCES §12l
    [V]). All 68 universe funds were easy to borrow on 2026-10-12, so the
    column charges 0 on that basis. **It is one snapshot applied to 17 years:
    a counterfactual, and it says so at the top of the table.**
  - **No historical fee series exists** for these funds. The IBKR history
    covers the 44 credit names only. The run prints the mean short notional,
    so any rate can be applied.
  - Distributions a short owes are inside the total return (§4.4).
  - On the IBKR fee panel, the deployed credit book's borrow over 2021-09 →
    2022-12 was about twice its 2020–22 gross return (W10-B §7 [S]). **No
    C-trial is read net of borrow as a verdict** until plan 0.5 has measured
    borrow for real (`CORE_SIGNAL_CANDIDATES_2026-10-12.md`, phase-2 item 5).

## 7. Windows, eras and the holdout

- **Fit window:** from the first session on which the tradable sleeve holds a
  position (2006-01-18 on today's universe, re-measured) to 2022-12-30.
  Sessions before it are flat and are excluded from every fit statistic, as
  W4's "live" rows are. Nothing is fitted: "fit" means the in-sample window.
- **Eras (H5):** 2005–09, 2010–14, 2015–19, 2020–22, 2023–26, each with
  turnover sd/mean. 2005–09 is thinner: the book can trade on 67.8% of its
  sessions.
- **Holdout:** 2023-01-03 to the families panel's last date at run time. It is
  opened **once**, after the fit verdict is committed, whatever that verdict.
  Nothing estimated is carried into it, because nothing is estimated.
- **Holdout rule (declared now):** the mean daily gross P&L of the tradable
  sleeve over the holdout has the same sign as the fit's. Otherwise KILL (D3).
  Beside it: the holdout Sharpe, its HAC t, a stationary-bootstrap 95% CI, and
  the probability of the observed sign under the fit Sharpe.
  - False-kill probability over 3.75 years: 0.17 / 0.07 / 0.03 at a true
    Sharpe of 0.5 / 0.75 / 1.0 [arithmetic, `c4_feasibility.py` §5].
  - **The holdout can kill; it can never rescue a failed fit.**
  - It holds the 2023–24 vendor stale-copy episode. M1 acts on it exactly as
    on the fit (8.4% of eligible fund-days removed, against 4.1–8.4% in fit
    eras).

## 8. Inference, controls and placebos

**Inference** (declared; the XASSET slate's P8, so the two counters' numbers
compare):

| quantity | method |
|---|---|
| **headline** | annualised gross Sharpe of the tradable sleeve's daily total-return P&L over the fit window |
| **HAC t** | Newey–West (Bartlett), **L = 21**, `scripts/cef/w4_artifacts.py::nw_t(x, lags=21)`. Printed beside it: L = 5 (W4's) and the Newey–West (1994) automatic lag |
| **bootstrap** | stationary bootstrap (Politis–Romano), **mean block 21 sessions, 10,000 resamples, seed 20261013**: 95% CIs for the mean (%/yr) and the Sharpe. A mean block of 63, and the repo's moving-block `w4_artifacts.block_boot_t`, are second methods. The stationary-bootstrap helper is added beside `nw_t`, with a test |
| **the bar** | `validate._dsr(obs, T, skew, kurt, N)` on the fit-window gross series, with its own skew and kurtosis; **PASS > 0.95**. N is the CEF counter's value when the result is committed. It already includes C4, which moved it at approval, so it is at least 51 |
| beside it, never deciding | SR·√years against √(2 ln N); the IC (H6): Spearman of z on the forward 2-day total return from *t*+2, non-overlapping, date-clustered, expected negative; the Fama–MacBeth slope in bp per unit z, as W4 reports it |

**Controls, each run through the same harness:**

| stage | control | rule | why |
|---|---|---|---|
| **2** | **The stale-NAV control** (plan row 9: "equity CEFs double as the stale-NAV control"). The identical rule on the **fresh-NAV sub-book**: the domestic, sector and covered-call funds of the universe, whose NAV changes are measured **not** smoothed (family medians of lag-1 autocorrelation −0.16 to −0.05, 2013–22; families note §5). Own vol scalar and cap. It holds a median 8 eligible funds and can trade on 84% of fit sessions [V] | **KILL (D1, stale-NAV artefact)** if its gross Sharpe is ≤ 0 or below ½ × the pooled gross Sharpe | Where the NAV is fresh, a stale-NAV artefact cannot operate, so the effect must survive there. The result is also evidence on W4/W13's question about the credit book, and is reported as such |
| **3a** | **Block-shuffled-signal placebo.** The rows of the tradable `H` are permuted in contiguous 21-session blocks, with returns fixed: each position keeps its size and turnover and loses its timing. 1,000 draws, seed 20261013 | **KILL D1** if the real gross Sharpe is at or below the placebo's 95th percentile | H12 |
| **3b** | **shift(3).** `evaluate(H.shift(1), R)` | **KILL D1** if the shift(3) gross Sharpe is below ½ × the shift(2) Sharpe | On the credit book one extra day costs 17–19% of gross Sharpe (W4 [S]): slow signal decay. Losing more than half to one day is a next-day price artefact |

**Comparisons are turnover-matched by construction (H2).** The placebo and
shift(3) carry C4's own `H`, so they share its turnover exactly. The
stale-NAV control compares the gross Sharpes of two books on the same rule,
not two policies; both turnovers are printed. No reference policy is matched,
because C4 is scored against zero, not against another construction.

**Diagnostics** (reported, never kills):

- the IC by family;
- the within-family / between-family split of the signal (W10-B's method):
  the pooled cross-section takes family bets, and W10-B found the between bet
  unpaid in the deployed credit book;
- the **NAV catch-up slope**: the same z against the NAV's own total return
  over [*t*+2, *t*+3]. A positive slope means a wide discount predicts a
  falling NAV, the price having led a stale NAV.

## 9. Regressions, and correlation with the book

All are OLS with statsmodels HAC covariance (maxlags 21 daily, 4 monthly). The
P&L is a self-financing long-short return, so no risk-free rate is
subtracted, as in W4. Alpha is in %/yr.

| regression | role | specification |
|---|---|---|
| **R-D4** | **decision** | daily tradable gross P&L on French **Mkt-RF, SMB, HML, RMW, CMA, UMD**, **TERM** = IEF − RF and **HY** = HYG − IEF, each at *t* and *t*−1 (Dimson; the betas are summed, because a CEF price can carry its beta with a one-day lag). **Pass: alpha t ≥ 3.0, and every summed \|β\| ≤ 0.10 at the vol target (§5).** HYG starts 2007-04-12, after the fit starts, so **two regressions must both pass**: the full fit without HY, and 2007-04-12 → 2022-12-30 with it |
| R-FF | reported | monthly FF5 + UMD + Pástor–Stambaugh traded liquidity (W4 §6c) |
| R-0 | reported | the contemporaneous-only version of R-D4 |
| R-BOOK | reported | C4 on the deployed book's daily P&L: its book beta |

**Not in R-D4, stated as a gap:** a short-volatility factor. Covered-call
funds are 46.5% of C4's fit-period eligible fund-days [V]. A long-short
within covered-call funds should be close to volatility-neutral, but no
volatility-premium series is in the repo to test it.

**Correlation with the book (plan row 9: a kill; decisions 1 and 2):**

- **Book series:** the deployed v7 policy (band 4.8%, cap 1.80, 13 names, ADV
  floor), daily gross total-return P&L, from its first position on
  2013-06-21. It is built as `scripts/xasset/book_profile.py` builds it: W4's
  baseline, "the deployed fit sample". Beside it, the WIDE series: the same
  13 names with no ADV floor (DG-C4-5).
- **Statistic:** the Pearson correlation of non-overlapping 21-session sums
  over the fit overlap, 2013-06-21 → 2022-12-30: **114 blocks** [V].
  Reported beside it: daily ρ, Spearman 21-session ρ, ρ in HY-stress windows
  (the worst quintile of 21-session HYG − IEF), and the holdout row (to the
  live panel's last date, 2026-09-28 today).
- **KILL** if the larger of the two series' ρ₂₁ is ≥ 0.5 (default, decision
  1). By arithmetic the rule fires with probability 0.006 if the true ρ is
  0.3, 0.09 if 0.4, and 0.5 at 0.5 [`c4_feasibility.py` §4].

## 10. Robustness: reported, never chosen from, and none of it rescues a failed headline

- era rows with turnover sd/mean; the share of calendar years with positive
  gross; the first half of the fit against the second;
- leave-one-family-out (five rows);
- **R-Q0** no masks; **R-Q1** only CEFConnect-confirmed stale copies masked;
- **R-S** all 105 pool funds, shortability assumed;
- **R-G** the multi-asset "global allocation" sub-family removed (its NAVs
  are partly foreign-struck) [U on how much];
- **R-P** price returns in place of total returns;
- yfinance-built total returns in place of CRSP, for source sensitivity;
- the raw (uncapped) band against the tradable sleeve;
- bootstrap mean block 63; NW automatic lag;
- **capacity:** the sleeve capital at which the largest single-fund trade on
  a median rebalance day reaches 1% of that fund's 63-session ADV, and
  participation at $1m, $10m and $100m.

## 11. Feasibility, measured today (zero trials)

`python3 scripts/cef/c4_feasibility.py` (about 4 s), run 2026-10-13 on the
families panels (last date 2026-10-09) and the live panel (prices
2026-09-28) [V]. Tables: `results/cef/c4/c4_{breadth_by_era,repeat_mask_by_year,bar_power}_2026-10-13.csv`.

### 11.1 Breadth

Eligible funds per session from 2005-01-03. "Active" means at least 6
eligible.

| book | 2005–09 | 2010–14 | 2015–19 | 2020–22 | **2023–26** | **fit 2005–22** |
|---|---|---|---|---|---|---|
| **declared: shortable, masked** (median / active share) | 8 / 67.8% | 10 / 99.0% | 11 / 97.5% | 14 / 96.6% | 13 / 94.7% | **10 / 89.5%** |
| R-Q0: shortable, no masks | 8 / 70.5% | 11 / 100% | 11 / 100% | 15 / 100% | 15 / 100% | 11 / 91.8% |
| R-S: all 105, masked | 10 / 86.6% | 14 / 99.7% | 15 / 99.0% | 18 / 96.7% | 18 / 97.0% | 14 / 95.3% |
| stale-NAV control sub-book | 6 / 52.7% | 9 / 97.9% | 9 / 93.9% | 12 / 96.0% | 11 / 94.5% | 8 / 83.9% |

- **Against the brief's "≈18 a day":** that is the families note's pooled
  median with global funds, non-shortable funds and no masks. The declared
  universe's is 10 over the fit and 13–14 since 2020.
- The deployed 13 have a median of 5 eligible by the same rule over 2013–22,
  and existed on 43.6% of sessions (W10-B §1 [S]). C4 is not frozen for most
  of its history the way the deployed fit sample is.
- **Fit-period eligible fund-days by family:** covered-call 46.5%, sector
  30.1%, multi-asset 11.1%, preferred 6.5%, domestic 5.7%. C4 is mostly a
  covered-call and sector book.
- **First active session** 2006-01-18; **fit 4,269 sessions (16.9 years);
  holdout 946 sessions (3.75 years)** to 2026-10-09.

### 11.2 The masks

M1 and M2 remove 4.1% (2005–09), 6.3%, 8.4%, 7.6% and 8.4% (2023–26) of
otherwise-eligible fund-days. M2 removes none. The precision of M1 by year is
in `c4_repeat_mask_by_year_2026-10-13.csv` (§4.3).

### 11.3 The bar and its power

Arithmetic on `validate._dsr` (skew 0, kurtosis 3; SE = 1/√years), reusing
`scripts/xasset/slate_feasibility.py::required_sharpe` and `power`:

| N | √(2 ln N) | **Sharpe needed** | Sharpe for 80% power | P(pass) at true SR 0.75 | 1.00 | 1.25 |
|---:|---:|---:|---:|---:|---:|---:|
| **51** | 2.804 | **1.081** | 1.286 | 0.09 | 0.37 | 0.76 |
| 58 (plan §3's upper end) | 2.850 | 1.093 | 1.297 | 0.08 | 0.35 | 0.74 |

- **Reference, not a forecast:** the deployed credit book's live gross Sharpe
  2013-06 → 2022 is 0.96 on total returns (W4 summary [S,
  `scripts/cef/w4_artifacts.py`]). If C4 were as good, P(pass) at N = 51
  would be **0.31**.
- **D4's alpha t ≥ 3.0** needs a residual Sharpe of at least 0.73 over 16.9
  years, before HAC widens it.
- **What a result means, stated before it exists:**
  - a **pass** is strong evidence;
  - a **NEITHER** (real but below the bar) is the likeliest outcome unless
    C4 is better than the credit book;
  - a **D1 kill** at Stage 1 (NW t < 1.96, roughly SR < 0.48) is informative:
    the test has power against a Sharpe of about 0.8 or more.

## 12. The order of evaluation (the exact kill tests)

| stage | statistic | rule | if it fails |
|---|---|---|---|
| 0 | DG-C4-1…5; the quality screen; turnover, cap- and band-binding shares, realised vol against the target, universe count | a gate fails, or Q1 | **no trial spent**: fixed, or referred to the team lead |
| — | **the trial is spent from here** | — | — |
| 1 | headline gross Sharpe; NW t (L = 21) | t ≥ 1.96 | **KILL D1** |
| 2 | stale-NAV control (§8) | sub-book gross SR > 0 and ≥ ½ × pooled | **KILL D1** (stale-NAV artefact) |
| 3 | placebo; shift(3) | §8 | **KILL D1** |
| 4 | R-D4, both windows | alpha t ≥ 3.0 and every \|β\| ≤ 0.10 at the vol target | **KILL D4** |
| 5 | correlation with the book (§9) | ρ₂₁ < 0.5 | **KILL** (plan row 9: not new breadth) |
| 6 | the bar: `_dsr` at N | > 0.95 | **NEITHER**: real at most, below the bar; no sleeve, no re-test on these data. The team lead rules WATCH or D5 |
| 7 | the fit verdict is committed | — | — |
| 8 | holdout sign (§7) | same as the fit | **KILL D3** |
| 9 | for a PASS: net Sharpe at 15bp | > 0 | labelled **D2**: no real-money sleeve; paper only by team-lead ruling |

**Every statistic of every stage is computed and reported, whatever the
verdict.** The verdict is the first failing rule in this order. A PASS needs
stages 1–6 and 8. These kill rules are pre-committed and are not softened
later.

## 13. What we expect [U]

- **Gross Sharpe 0.3–0.9.** The live signal on the credit book has a live
  gross Sharpe of 0.96 [S], and an IC of −0.033 on the deployed set (W4).
  Equity-CEF NAVs are fresher, which should remove any stale-NAV help.
  Breadth is about twice the deployed set's.
- **Most likely verdict:** NEITHER, or a kill at R-D4 on alpha t.
- **Correlation with the book:** low (ρ₂₁ < 0.3). Both books are
  dollar-neutral within CEFs, and their assets differ.
- **The stale-NAV control** should hold most of the pooled Sharpe, because it
  is about 82% of the fit-period eligible fund-days [V]. If it does not, the
  pooled result came from preferred and multi-asset funds, and stage 2 kills
  it.

Being wrong here is fine and is the point.

## 14. What would falsify it once trading on paper (H11)

Stated now, for a C4 sleeve that passed and was released:

- **Fidelity, daily.** The live target must equal the trial script's target on
  the same panel, to whole-share rounding. Any other difference halts the
  sleeve as a bug, not a result.
- **Reversal at 120 armed sessions.** Reverse if the sleeve's live cumulative
  gross return on the official-fill line falls below the **5th percentile of
  the trial's own 120-session cumulative returns**. That percentile is
  re-measured on the read date by stationary bootstrap (mean block 21) on the
  fit and holdout series. The distribution-adjusted line is reported beside
  it. **No threshold is written here as a number (H14).**
- **At any time:** reverse if the live drawdown exceeds the fit's worst,
  re-measured.
- **Reported, no rule** (too few observations to decide on): the live daily
  correlation with the CEF book's own P&L.

## 15. Trial accounting

- **CEF today: 50 trials, bar √(2 ln 50) = 2.797** (orient TRIALS,
  2026-10-13 [V]).
- On approval: **50 → 51** in the commit that records the team lead's
  approval (decision 7), not in this commit. **`docs/RESEARCH_STATE.md`
  changed in this commit: no.**
- No other counter moves. The 27-name holdout is not consumed. The
  2023-01-01 time holdout stays sealed until C4's fit verdict is committed.
- **Zero-trial script:** `scripts/cef/c4_feasibility.py`, with tests in
  `scripts/cef/tests/test_c4_feasibility.py`. **Trial script (after
  approval):** `scripts/cef/c4_families.py`, importing `build_targets`,
  `band_gross_capped`, `evaluate`, `fit_only`, `_stats` and `borrow_charge`
  from `scripts/cef/band_frontier.py`, `_dsr` from `scripts/cef/validate.py`
  and `nw_t` from `scripts/cef/w4_artifacts.py`. There is no new backtester.
