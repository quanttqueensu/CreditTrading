# Research agenda: a broad credit, fixed-income and multi-asset book — 2026-10-08

**What this is.** On 2026-10-08 the team lead asked what the desk should research,
over years rather than weeks, to add signals and legs to the book. Later that day
they redirected the question: *"I don't want to focus too much on one specific
thing, like muni CEF — we should incorporate more broad credit related instruments
as we can and get signals for those, adding other fixed income / multi asset
products might be a good fit too."* This note answers the redirected question. It
**replaces the morning's version**, which led with a muni-CEF seasonal. That
version's CEF-specific items survive here as Track C.

**Companion (written the same evening):** `results/cef/SCALING_RESEARCH_2026-10-08.md`.
It covers how other firms clear 10%, the return-on-capital arithmetic, and a
staged build order for real capital. It **upgrades C4** from a filter into an
event-driven CEF sleeve, and adds three Track B candidates: the CEF IPO
lifecycle pair, the discount pull-to-par on term CEFs, and the rights-offering
window.

**It spends no trial, changes no spec and trades nothing.** Every item is a
candidate work order. Each must be checked against `/graveyard` and pre-registered
(`/prereg`) before it spends a trial.

**How it was made.**

1. **A deep-research workflow on CEF discounts.** 20 sources, 25 claims put to a
   three-vote adversarial check, 14 of them surviving. Sources are in
   `docs/REFERENCES.md` §12.
2. **Three desk agents on the broadened question.** Each fetched its own papers
   and measured from repo data; their sources are in `docs/REFERENCES.md` §12b:
   - alpha-finder: signal families across asset classes;
   - unique-angle-researcher: structural, calendar and flow effects;
   - market-structure-analyst: the tradable universe, from one read-only Alpaca
     assets request and CRSP.
3. **Measurements re-run by the author** (zero trials, fit period only for
   anything touching a candidate):

   | script | measures |
   |---|---|
   | `python3 scripts/xasset/diversification_screen.py` | correlation of candidate return streams with the book |
   | `python3 scripts/xasset/trend_turnover.py` | turnover and gross exposure of a trend leg |
   | `python3 scripts/xasset/book_profile.py` | the live book's distribution leg and its ETF correlations |
   | `python3 scripts/data/r2_signal_coverage.py` | what R2 holds |

   The universe map is a dated record in `results/data/universe_2026-10-08/`.

**Literature labels.** [V] means the agent fetched and read the source; this
note's author did not re-read it. [S] means sourced, not read. [U] means
uncertain.

---

## 0. The answer

- **Break the book into product families, with signal families applied to each.**
  The current book is one family (13 credit CEFs) and one signal (the discount
  z-score), and in practice it is close to one bet. Under an absolute-return
  mandate with a volatility cap, the cheapest source of extra return is an
  *independent* stream. A sleeve at half the book's Sharpe raises the combined
  Sharpe by about 12% at zero correlation, 8% at 0.1 and 5% at 0.2 (arithmetic).
- **The candidates are close to uncorrelated with the book.** Over the fit
  period (2013-06-21 to 2022-12-30), the book's daily P&L correlates with HYG,
  TLT, IEF, LQD and SPY returns at 0.03 or less. Most candidate legs sit between
  −0.15 and +0.22 at a 21-day horizon (§2).
- **Build first, both cross-asset legs on ETFs:**
  - **trend on credit and rates ETFs**, the longest-lived out-of-sample evidence
    of any family;
  - **front-running pension and balanced-fund rebalancing**, SPY against
    Treasury ETFs: recent, strong, positively skewed and in shortable names.
- **Then the listed-fund family beyond our 13:** the discount z-score on daily-NAV
  CEF families (equity, preferred, multi-asset), plus two dated flows the z-score
  cannot see. One is index reconstitution of funds of CEFs; the other is dividend
  reinvestment buying on payable dates.
- **What the broad direction rules out:**
  - **Carry is a risk premium, not a signal.** Holding it is a sizing decision
    for the team lead.
  - **Bond-level factor premia mostly fail replication.**
  - **Duration timing fails out of sample.**
  - **Cross-sectional relative value across credit ETFs is already dead**
    (`credit_rv`, `E1`, `leadlag`, `pair-reversion`).
- **Infrastructure has to come first** (Track 0). ETF legs cannot be scored or
  traded cleanly until three things change:
  - the official-close record covers non-NYSE venues;
  - the ETF panels have fetchers again;
  - a daily shortability snapshot exists.

---

## 1. The universe, measured

From the 2026-10-08 Alpaca snapshot and CRSP liquidity over the 252 days to
2024-12-31 (`results/data/universe_2026-10-08/`). **Shortability is true on that
date only, and the liquidity is 21 months stale.** The floor is the spec's
`min_adv_usd` on the sleeve's 63-day definition.

| family | tradable | shortable | median ADV $m | clear the floor | median spread bp | most liquid (S = shortable and easy to borrow; -- = not shortable) |
|---|---:|---:|---:|---:|---:|---|
| Treasury ETF | 105 | 40 | 3.10 | 38 | 4.4 | TLT, IEF, BIL, SGOV, SHY (all S) |
| IG corporate ETF | 114 | 35 | 2.09 | 41 | 6.4 | LQD, VCIT, VCSH, VCLT (S) |
| HY corporate ETF | 95 | 23 | 0.81 | 19 | 11.0 | HYG, JNK, USHY, SJNK (S) |
| Bank-loan ETF | 14 | 4 | 3.92 | 6 | 4.2 | BKLN, SRLN (S) |
| CLO ETF | 34 | 6 | 2.47 | 7 | 3.9 | JAAA (S); JBBB (--) |
| EM debt ETF | 30 | 9 | 1.86 | 5 | 11.5 | EMB, VWOB, EMLC (S) |
| Preferred ETF | 30 | 5 | 1.92 | 11 | 13.8 | PFF, PGX (S) |
| Convertible ETF | 6 | 2 | 10.58 | 2 | 11.6 | CWB, ICVT (S) |
| MBS / securitised ETF | 43 | 18 | 1.06 | 8 | 13.2 | MBB, VMBS (S) |
| TIPS ETF | 46 | 10 | 0.28 | 10 | 7.8 | TIP, SCHP (S) |
| Floating / ultra-short | 58 | 28 | 5.33 | 22 | 2.3 | JPST, USFR (S) |
| Aggregate / core | 215 | 55 | 1.64 | 55 | 9.0 | AGG, BND (S) |
| Muni ETF | 169 | **15** | 1.04 | 29 | 9.9 | MUB, VTEB (**--**) |
| Multi-asset / managed futures | 74 | 21 | 0.63 | 8 | 23.4 | AOR, DBMF (S) |
| Taxable credit CEF | 109 | 69 | 0.96 | 20 (7 deployed, 13 holdout) | 16.3 | PDI, GOF, PTY |
| Equity & multi-asset CEF | 145 | 91 | 1.17 | 24 | 18.6 | — |
| Preferred / convertible CEF | 24 | 11 | — | 2 | 15–23 | — |
| Muni CEF | 72 | 23 | 0.67 | 10 | 17.0 | — |
| BDC | 49 | 27 | 3.21 | 26 | 11.1 | OBDC, FSK (S); ARCC, BXSL, MAIN (--) |
| Mortgage REIT | 38 | 34 | 5.61 | 24 | 11.9 | AGNC, NLY, ABR, STWD (S) |

The preferred and convertible CEF row merges two families of the record, so its
ADV is left blank: the record gives each family's median, and the two cannot be
combined.

**What the table says:**

- **ETFs are deep but mostly long-only at Alpaca.** About a fifth to a third of
  each family is shortable, and almost no muni ETF is. ETF legs should be
  directional, or short only names on a daily-checked shortable list.
- **CEFs, BDCs and mREITs are shallow** but mostly shortable.
- **Bonds themselves** are reachable only through Alpaca's Broker API, as far as
  any Alpaca page says. Whether a paper account can trade them is [U]. Even if it
  can, they take day orders and never MOC (`docs/REFERENCES.md` §12b).
- **R2 history:** CRSP to 2024-12-31 holds every ETF from launch: 2002 for
  LQD/TLT/IEF, 2007 for HYG/JNK/MUB/EMB, 2011 for BKLN. H.15 OAS runs to
  2025-02-13. CRSP MF holds open-end funds, not CEFs
  (`results/data/R2_SIGNAL_COVERAGE.md`). The local `data/rv/` ETF panels run to
  2026-07-30, but their fetchers exist only at tag `pre-clean-slate` (Track 0).
- **Operational, today:** AWF and MHD are no longer shortable (they were on
  2026-09-28). The session re-reads `shortable` at send and skips shorts that
  have flipped (`quantt/session/run.py`), so nothing breaks.

---

## 2. How the candidates relate to the book (measured, 2026-10-08)

**The live book against raw ETF returns.** Source: `scripts/xasset/book_profile.py`,
v7 band, gross-capped, from the book's first position (2013-06-21) to 2026-07-28,
n = 3,294 days.

- Daily correlation: TLT 0.007, IEF 0.009, SPY 0.038, HYG 0.031, LQD 0.026.
- Monthly correlation: TLT −0.11, IEF −0.09, SPY +0.03.
- On the book's worst 5% of days (n = 165), TLT averaged −6.6bp and SPY −3.4bp.
  Those are small numbers. They do not support a claim that the book's tail is
  an equity or duration selloff.

**Candidate legs against the book.** Source: `scripts/xasset/diversification_screen.py`.
Simple versions of each leg, shift(2), fit period 2013-06-21 to 2022-12-30.
**Correlations only: no candidate's mean or Sharpe was computed.**

| proxy | ρ daily | ρ 21-day (n = 115) | ρ 21-day in HY stress (n = 23) |
|---|---:|---:|---:|
| 12-month trend, basket of 10 credit/rates ETFs | +0.04 | +0.04 | +0.15 |
| 12-month trend on hedged HY (HY_XS) | +0.09 | +0.22 | +0.49 |
| 12-month trend on IEF | −0.07 | −0.01 | −0.20 |
| cross-sectional 12-1 momentum, 12 credit/rates ETFs | −0.02 | −0.14 | −0.46 |
| long HY_XS (a carry beta) | +0.04 | +0.12 | +0.00 |
| SHY − TLT risk parity (bond BAB) | −0.01 | +0.17 | +0.09 |
| sign(SPY 63d) × HY_XS (equity to credit) | +0.04 | +0.18 | +0.33 |

- **Precision:** the standard error is about 0.09 at n = 115 and about 0.21 at
  n = 23.
- **Instability:** the credit-trend 21-day ρ was +0.12 in 2013–16, +0.47 in
  2017–19 and −0.05 in 2020–22. Spearman gives the same signs.
- **The book in stress:** in HY-stress windows it earned +0.29% per 21 days,
  against +0.51% across all windows. It is not a crisis loser on its own sample,
  so a new leg earns its place as an *independent stream*, not as a hedge.
- **2008 is unmeasured.** The book's first position is in 2013.

**The distribution leg that paper drops.** Total-return P&L minus price-return
P&L, from `book_profile.py`:

| era | distribution leg |
|---|---:|
| 2010–14 | −0.70%/yr |
| 2015–19 | +0.67%/yr |
| 2020–22 | −0.61%/yr |
| 2023–26 | −0.88%/yr |

So the book has recently been net short distribution yield. Alpaca paper does
not simulate dividends [V], so the scored paper record flatters the book by about
that much against a real account. That assumes paper also charges no dividend on
shorts, which is [U]. Any new leg that is long yield will be **understated** on
paper.

---

## 3. The map: product families × signal families

| | discount to NAV | trend (time series) | cross-sectional momentum | carry / beta | calendar & flow | events |
|---|---|---|---|---|---|---|
| **Credit CEFs, deployed 13** | **LIVE** | — | dead (combining with price reversal) | D4 | B3 DRIP, B2 index reconstitution, B4 tax-loss | C4 filter |
| **Other CEFs, daily NAV** (equity, preferred, multi-asset, option-income) | **B1 TEST** | — | — | — | B2, B3, B4 | C4 filter |
| **BDCs, mREITs** (quarterly NAV / book) | B5 PARK (stale NAV) | — | — | D4 | B4 tax-loss | — |
| **Credit ETFs** (HY, IG, loans, EM, preferred, convertible, CLO, MBS) | dead (`E1`, `single-fund-PD`) | **A1 BUILD-FIRST** | A5 TEST | Track D (sizing ruling) | — | — |
| **Rates ETFs** (Treasuries by duration, TIPS) | n.a. | **A1** | A5 | Track D | A3 month-end TEST; auction cycle KILL | post-FOMC PARK |
| **Multi-asset ETFs** (SPY, EFA, EEM, GLD, DBC) | n.a. | A4 TEST | — | — | **A2 rebalancing BUILD-FIRST** | macro-announcement PARK |
| **Bonds directly** | Broker API only; paper [U] | | | | | |

---

## 4. The programme

### Track 0: infrastructure and hygiene (0 trials; blocks everything else)

| # | item | why |
|---|---|---|
| 0.1 | **Restore the ETF fetchers** (`scripts/rv/stage_ohlc.py`, `stage_ohlc_extended.py`, `scripts/build_etf_daily.py` from tag `pre-clean-slate`), each with a `docs/REFERENCES.md` source note. Extend them to EFA, EEM, GLD and DBC, and continue them past 2024 from Alpaca bars or yfinance | CLAUDE.md: anything fetched gets a fetcher. The `data/rv/` panels are orphaned |
| 0.2 | **Map official closes beyond NYSE.** `ASSET_EXCHANGE_SIP_NAME` (`quantt/broker/alpaca.py`) maps only NYSE, so every Arca, Nasdaq, BZX and NYSE American name raises `UnmappedExchange`. That is about 98% of tradable ETF names | The research rules require the auction-print P&L beside the Alpaca fill |
| 0.3 | **Source each venue's closing cut-off.** Arca: a 2018 SEC release says 15:59 [S]. BZX: proposed text says 15:55 [S]. NYSE American: [U] | Order-path rule 3 |
| 0.4 | **Take a daily shortability snapshot of the candidate universe** by extending the read-only probe | `borrow_status` changes daily; only about a fifth of ETFs can be shorted |
| 0.5 | **Add a third P&L line that credits distributions** (ruling 4) | Paper drops dividends, so yield legs are mis-scored |
| 0.6 | **Run W4**, the artifact battery on the live book (stale NAV, ex-dates, bounce, total returns) | The baseline every "incremental" claim is measured against |
| 0.7 | **Make one read-only `GET /v2/assets?asset_class=treasury` (and `=corporate`)** | Settles whether paper can see bonds at all |

### Track A: a cross-asset ETF sleeve (the new independent bets)

**A1. Time-series trend on credit and rates ETFs. BUILD-FIRST, 1 trial.**

- **Mechanism.** Initial under-reaction, then delayed over-reaction. "Speculators
  profit … at the expense of hedgers" (Moskowitz, Ooi & Pedersen 2012 [V]).
- **Evidence.**
  - Bond trend: Sharpe 0.53 (t 2.94) in the replication sample, 0.49 (t 7.22) in
    new samples, 1800–1980 and 2012–16 (Baltussen, Swinkels & van Vliet [V]).
  - Trend overall 1880–2013: Sharpe 0.77 net of fees, correlation to equities
    0.00. Results have been "mixed since 2008" (Hurst, Ooi & Pedersen [V]).
- **Risk.** Huang et al. (2020) [V] find the strategy performs about as well as a
  rule built only on each asset's historical mean. That is the D4 test.
- **Design** (declared now, nothing tuned):
  - universe: HYG, LQD, IEF, TLT, EMB, PFF, MUB, BKLN, CWB;
  - signal: the sign of the 252-day excess log return, divided by 63-day
    volatility, scaled to the spec's `vol_target_annual`;
  - monthly refresh with `calendar(T, 21)`, gross-capped.
- **Controls:**
  - the historical-mean rule;
  - 200 placebos built from shuffled 21-day blocks;
  - a shift(3) run. A monthly signal should barely change; a large drop means a
    stale-price artifact.
- **Measured** (`trend_turnover.py`): 11.1 turns a year, so a cost drag of
  55, 166 and 332 bp/yr at 5, 15 and 30bp. Mean gross 3.3×, p95 5.5×. That is an
  upper bound, since it assumes zero correlation, but **the leg must be
  gross-capped**: it repeats `pair-reversion`'s leverage collision. If its Sharpe
  is near 0.5 at a 6% vol target (an inference), it **flips sign at 30bp**.
- **Shorting.** Shorts must be limited to names shortable that day. MUB is not
  shortable.

**A2. Front-running pension and balanced-fund rebalancing (SPY against IEF/TLT).
BUILD-FIRST, 1 trial.**

- **Mechanism.** Balanced funds, pensions and target-date funds rebalance on the
  calendar or on drift because their mandates require it. Their returns pay for
  it.
- **Evidence.** Harvey, Mazzoleni & Melone (Jan 2026) [V], 1997–2023:
  - Sharpe 1.11, skew +5.23; 0.90 excluding crises;
  - 17.96%/yr when liquidity risk is high, against 3.79%/yr when it is low;
  - the effect is a **next-day** move that reverts within two weeks.
- **Harness consequence.** shift(2) gives up day t+1. The calendar signal is
  known ahead of time, so it can be decided early; the drift signal cannot. If
  the fit-period gross Sharpe falls inside its 95% band around zero, the leg dies
  in one trial.
- **Out of sample:** 2023-03-17 to 2026-07 is genuinely after the paper's
  sample.
- **Controls:** the same signal on SHY against BIL (should be zero); mid-month
  days; permuted month labels.
- **Shorting:** SPY, IEF and TLT were all shortable on 2026-10-08.

**A3. Month-end Treasury index extension (IEF over the last 3 days). TEST, 1
trial.**

- **Evidence.** Hartley & Schwarz (2019) [V]: +0.25%/month, Sharpe 0.88,
  1990–2018, still +0.27 in 2015–19. The NY Fed [V] finds the mechanism has grown
  since 2020.
- **Cost.** Two fills a month against about 25bp gross, so **expect a sign flip
  at 15bp**. Say so in the pre-registration.
- **Regime breaks to declare:** settlement moved to T+2 in September 2017 and to
  T+1 in May 2024.
- **Overlap with A2.** It is a month-end flow too: count them as separate trials
  and report them side by side.

**A4. Multi-asset trend extension. TEST after A1, 1 trial.** A1's rule plus SPY,
EFA, EEM, GLD and DBC. Out-of-sample multi-asset trend Sharpe is 1.09 in the
replication sample and 0.98 in new samples (Baltussen et al. [V]). The decision
is on the combined sleeve only, with no picking of asset classes. It needs
fetchers (0.1).

**A5. Cross-sectional momentum across fixed-income ETFs. TEST, cheap, 1 trial.**

- **Evidence is weak:** bond-country momentum 0.29 and 0.31 Sharpe out of
  sample. It is the most negatively correlated proxy (−0.46 in stress).
- **How it differs from `credit_rv`:** 12-month continuation, not short-horizon
  reversal.
- **Kill:** if a Treasury-only version scores as well, it is duration timing.

**Construction.** Each sub-sleeve gets its own P&L line, a per-sleeve vol scalar
and a gross cap, and the sleeves are combined by Σ⁻¹·IR. That follows the
standing rule "seventeen sleeves, one combined book" (2026-09-09). Vol targeting
earns its place only through the combined Sharpe: in real time it beats the
unmanaged version less often than chance (Cederburg et al. [V]).

### Track B: listed-fund structures beyond our 13

**B1. The discount z-score on daily-NAV CEF families (equity, preferred,
multi-asset, option-income). TEST.**

- **Mechanism.** M1 (retail sentiment) is generic. Patro et al. [V] find
  reversion across 377 CEFs.
- **Size.** 145 equity and multi-asset CEFs are tradable, 91 shortable, 24 clear
  the floor.
- **It doubles as a control.** Equity NAVs are struck on exchange closes, so
  these funds are the stale-NAV control for W4 and W13.
- **Correlation.** Some sentiment is shared (Lee, Shleifer & Thaler); measure the
  correlation with the book.
- **Rulings needed:** the counter, and whether these funds count as part of the
  H9 holdout (ruling 5).

**B2. Index reconstitution of funds of CEFs (YYY semi-annual, PCEF quarterly).
Count first (0 trials), then 1.**

- **Mechanism.** Index ETFs must trade additions and deletions in thin CEFs at a
  dated open or close (methodologies [V]).
- **Count.** From N-PORT snapshots that bracket each reconstitution, count the
  events and each flow in days of ADV. Below about 100 events, or under one day
  of ADV, it is D7: park it.
- **Data.** The NPORT counter has 1 trial.

**B3. Dividend-reinvestment buying on payable dates. 1 trial.**

- **Mechanism.** When a fund trades at a discount, its plan agent buys in the
  open market "on or shortly after the payment date". At a premium the fund
  issues new shares instead (PDI plan [V]), which builds in a control. Hartzmark
  & Solomon [V] find payment-day price pressure in equities.
- **Design.** Within each payable-date cohort, go long the discount funds and
  short the premium funds.
- **Kill:** no gap between discount and premium funds.
- **Data:** CRSP `dsedist.paydt` × the repo NAV panel.

**B4. Tax-loss and January effects across retail-heavy wrappers (CEFs, BDCs,
mREITs, preferreds). TEST.**

- **What it replaces.** It generalises the muni-only seasonal: year-to-date
  losers against winners, across families.
- **Evidence.** Muni CEFs: January +2.21%/month against −0.19% in other months,
  working paper [V]. The HY index shows an abnormal December (Kotomin [S]).
- **Persistence is contested.**
- **Constraints.** One event per year (a D7 risk). The z-score already reads
  December widening as cheap, so only the increment counts.

**B5. BDC and mREIT discounts to NAV or book. PARK.** NAV is quarterly and filed
28–35 days after quarter-end (ARCC, XBRL [V]). The discount is mostly staleness:
the `single-fund-PD` death. Revisit only with a NAV nowcast.

### Track C: make the CEF engine sound

These are the morning version's items, unchanged in substance.

- **C1 W10:** separate selection within groups from timing between groups
  (0 trials). Then two sleeves (1 trial). Then a fair-value conditioner per group
  (up to 4 trials):
  - HY: OAS and the CCC−BB spread;
  - munis: leverage cost;
  - loans: SOFR;
  - PIMCO funds: repo cost.

  Pre-declared observables only, never a fitted latent level (the Kalman death).
  On 13 names the muni group is MHD and MQY only, and AWF and MHD are hard to
  borrow today.
- **C2 W13:** correct for stale NAV (GLM unsmoothing, or a nowcast from ETF
  closes) (1 trial).
- **C3 A funding-stress brake into W6**, as governance, not a signal. Freeze new
  longs on a pre-declared funding-stress observable (Mitchell & Pulvino [S]).
- **C4 Corporate-event filter:** never short into a NAV-priced tender or an
  open-ending, and block longs during rights offerings. The activism evidence is
  from equity CEFs only, and *FS Credit v. Saba* (2026, 6–3) [V] changes the
  regime. Needs an EDGAR fetcher.

### Track D: deliberate beta (0 trials)

Carry is a paid premium, not a signal. Credit carry earned a Sharpe of 0.47
over 1973–2012 and "suffers extreme negative returns … around recessions"
(Koijen et al. [V]). If the team wants credit or term beta for absolute return,
that is a sizing ruling (ruling 3). The only research it needs is a zero-trial
measurement of how it fails together with the book (joint tail and drawdown
overlap by era). It is never counted as skill.

### Closed: do not build

| idea | why |
|---|---|
| Duration timing | forward-rate models fail out of sample and get worse (Thornton & Valente [V]); beyond level and slope the evidence is "much weaker" (Bauer & Hamilton [V]) |
| Daily equity → credit | the `leadlag` mechanism (non-synchronous pricing), which shift(2) cannot harvest. The monthly form is parked behind A1 |
| Defensive / BAB in bonds | out-of-sample country-bond BAB is −0.02 (t −0.29) [V]; it needs about 5.5× gross; the credit-quality form is `S3-wrapper` (D4) |
| Value in credit at index level | about three credit cycles of history (D7); short-horizon ETF value is `credit_rv` (D1) |
| Bond-level factor premia | 23% survive replication; momentum is 0.00 without winsorization (§12 [V]) |
| Treasury auction cycle | 8.6bp/month gross against about 4 turns a month (D2 on the grid); recovery reportedly gone after 2010 [S] |
| Ex-day dividend capture | paper credits no dividends, so the result cannot be measured on the scored account |
| Leveraged-ETF rebalancing, rate-hedged ETFs, CLO-ETF and quarter-end ETF premium/discount, rising stars, CEF IPO waves | insignificant [S], not shortable [V], `single-fund-PD`, no ETF expression, or zero CEF launches in 2023 |
| Post-FOMC drift; macro-announcement premium | PARK: too few events (D7), or a risk premium (D4) |
| Retail flows by Lipper class (CRSP MF open-end funds) as a sentiment conditioner | PARK: monthly, R2-only with no live source, and no verified literature. The nearest dead relative is `raw-flow-z`. If revived, re-run its Treasury control |
| Options, ML, regime-switching, dislocation sizing, distribution-policy signals | graveyard (`docs/RESEARCH_STATE.md`) |

---

## 5. Proposed sequence

| phase | items | trials | gate |
|---|---|---|---|
| **Now** | Track 0 (0.1–0.7); Track D joint-tail measurement; B2 event count; C1 W10 Part B decomposition | 0 | none |
| **Next** | A1 trend, A2 rebalancing | 2 | counter ruling (1); 0.1, 0.2, 0.4 done |
| **Then** | B1 other CEF families; B3 DRIP; A3 month-end; C2 stale NAV | about 4 | rulings 2 and 5; W4 done |
| **Later** | A4 multi-asset trend; A5 cross-sectional momentum; B2 trade; B4 tax-loss; C1 Parts C and D | about 8 | earlier results; each sleeve's correlation with the combined book |

---

## 6. Decisions only the team lead can make

1. **The counter for the cross-asset ETF slate** (A1–A5).
   - **On LEGACY** (162 trials, bar 3.19), a 15-year fit needs a Sharpe of about
     0.82. The literature puts bond trend near 0.5, so even a real effect would
     probably fail, and the trial would teach nothing.
   - **On a new counter** with the slate of 5 declared before any run, the bar is
     1.79, about a 0.46 Sharpe.
   - This reads the bar as a t-statistic on Sharpe; exactly how the desk applies
     it is [U].
   - **Recommendation:** a new XASSET counter, with all five declared up front
     and parameters taken only from the papers, and the LEGACY bar reported
     beside each result. The 162 LEGACY trials searched different hypotheses
     (premium/discount, relative value, microstructure) on the same price data.
     Declaring the slate in advance is what keeps that honest.
2. **Where a passing sleeve lives.**
   - **Recommendation:** inside the CEF account, as one combined book. The
     diversification benefit only shows in a single track record, and the
     standing decision is sleeves in one book. The symbols do not overlap, so
     the wash-trade rule is not a problem.
   - **The alternative:** a separate account gives clean attribution but cannot
     help the score. How the competition scores a track record is [U].
3. **Is deliberate credit or term beta allowed** under the absolute-return
   mandate (Track D)?
4. **A third paper P&L line that credits distributions** (0.5). Without it every
   yield-carrying leg is mis-scored.
5. **Other CEF families (B1):** which counter, and do they count as part of the
   H9 holdout? On 2026-10-08, 13 taxable-credit holdout CEFs clear the floor.
6. **Live sources a new signal may use:** Alpaca bars, yfinance, EDGAR, N-PORT,
   FRED/ICE OAS. R2 never feeds the live path.

---

## 7. What is not established

- **No candidate leg has been backtested on the harness.** Every Sharpe here is
  from a paper. The correlations measure relatedness, not profit.
- **Correlation estimates are noisy and unstable across eras.** Stress windows
  number only 23.
- **Paper scoring distorts yield legs** (no dividends), and ETF auction scoring
  is blocked until 0.2.
- **Liquidity is 2024 data.** 345 ETFs listed after 2024 have no liquidity
  figure.
- **Bonds at Alpaca:** paper eligibility is [U], and the guide and FAQ disagree
  on which corporates are offered.
- **Evidence for B2 and B3 in CEFs:** none; both are mechanism-led. The A2 paper
  is from 2025–26 and has only about 3.5 years after its sample.
