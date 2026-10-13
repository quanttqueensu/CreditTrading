# The real-money cost re-run — THE GATE (plan item 0.5) — 2026-10-12

**Report only. Spends no trial (CEF counter stays 50). Changes no spec and nothing
on the live path.** Item 0.5 of `results/cef/RESEARCH_PLAN_2026-10-09.md`: "If the
live book is not positive net after measured costs, real capital waits, and C1/C2
come before any new sleeve." `docs/SYSTEM.md` §5 (2026-10-09) makes this re-run the
condition for deploying any capital.

**Reproduce every figure:**

```bash
QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/real_money_costs.py --refresh-snapshots \
    --state ~/quantt_state/cef --state <a copy of the VM's state directory>
python3 scripts/cef/real_money_costs.py          # offline: every section except execution
```

The run behind this note is `results/cef/real_money_costs/real_money_costs_output.txt`
(§0–§7 below name its blocks). It holds counts, basis points and percentages only:
no account number, position or equity. Every figure here is **[V]**, measured this
session by that script, unless labelled otherwise. The calls the script makes are
read-only: Alpaca market data (closing-auction prints, SIP quotes), asset flags and
the account's fill activities, plus IBKR's public shortstock file.

> **Corrections and additions, 2026-10-12 (independent review of commit 8b80e26).**
> The review re-derived the verdict by its own loop (−3.51%/yr at MOC, 13.11%
> borrow, 328 sessions) and found five things. Each is fixed below, in place:
>
> 1. **The bootstrap was not centred.** The first version used W4's
>    `block_boot_t`, which draws block starts from [0, n−20] and so under-samples
>    the first and last 19 sessions. In the measured window those sessions
>    netted far above the middle, so every interval sat about 1–1.5pp low. Two
>    statements were false as a result. The first read "The interval includes
>    zero at MOC and at the half-spread, and **excludes it at 15bp** and 30bp";
>    with a circular block bootstrap the 15bp interval is [−15.0, +1.0] and
>    includes zero. The second read "The iid and Newey–West t **agree with the
>    bootstrap in every row**"; they did not where the old interval excluded zero
>    at |t| ≈ 1.4. Every interval in this note is now circular
>    (`circular_block_ci`), the Newey–West t sits beside each, and the script
>    still prints W4's interval beside it so the difference stays visible. The
>    verdict does not change: the point estimate is negative under every
>    execution assumption.
> 2. **The collateral round-up was ignored.** Both brokers mark collateral at
>    102% "rounded up to the nearest dollar". Whether that is per share or per
>    position is [U]. Read per share it raises the measured borrow to 13.66%/yr
>    and lowers the net at MOC to −4.06%/yr. It is now a labelled sensitivity
>    (P0r, and a round-up row in the breakevens). The tests pin 1.02 and 360 as
>    literals.
> 3. **Three items added to "What would change the verdict":** where the fee
>    history's start date comes from; the sealed 2023–26 period; and HYT's
>    10.56% fee in late 2026.
> 4. **Scope added.** The −3.5%/yr describes an IBKR-like account. In a
>    high-fee regime the Alpaca book would more likely fail to open its shorts
>    than pay the fee.
> 5. **Which breakeven the "58% of dates" uses**, and the alternative, are now
>    stated.

**What changed in the harness.** One additive function, `borrow_charge()` in
`scripts/cef/band_frontier.py`. It charges each short its fee on the book
`evaluate()` holds (`H.shift(2)`), at the fee of session *t*−1, per calendar day
/360 on 102% collateral. Those are IBKR's and Alpaca's published conventions
(`docs/REFERENCES.md` §4, §12l). A missing fee is returned as uncovered short
weight, never charged zero. An optional `collateral_px` applies the per-share
round-up as a sensitivity. The default is the flat 102%, and the default output
was shown to be identical to the first version's. `evaluate()` is untouched.

Tests:

- `scripts/cef/tests/test_borrow_charge.py` was checked to fail with
  `shift(1)`, with a silent zero, and with a changed day count. It pins 1.02 and
  360 as literals.
- `scripts/cef/tests/test_real_money_costs.py` includes a test that the
  circular bootstrap is centred where W4's scheme is not.

**Panels** (read-only; the run printed these dates):

| panel | last date |
|---|---|
| `data/cef/cef_prices.parquet` | 2026-09-28 |
| `data/cef/cef_nav.parquet` | 2026-09-25 |
| `data/cef/cef_distributions.parquet` | last ex-date 2026-09-10 |
| `data/cef/cef_borrow_history.parquet` (IBKR FEE_RATE) | 2021-09-13 → 2026-09-09 |
| `data/cef/cef_borrow.csv` | 2026-09-06 → 2026-09-21 |
| IBKR shortstock file, fetched | stamped 2026.10.12 14:22:28 |
| Alpaca asset flags | probes 2026-09-28 and 2026-10-10; read 2026-10-12 |
| paper fills | 2026-09-29 → 2026-10-08 (records), re-read from the broker 2026-10-12 |

**Holdouts.** Every **return** statistic stops at 2022-12-30. T and R are truncated
by `fit_only` before the policy runs, and `_assert_fit` checks each frame. Borrow
**fees** dated after 2022 are read only as cost inputs. They give the per-name level
of proxies P2, P3 and P3f, and the description of the fee history in the tables in
"Borrow" below. No 2023+ position, P&L or return is computed. The fee-regime table prices the 2013–22
short-book composition at later fees; it chooses nothing. No untouched name is read.

**Conventions.** The deployed v7 policy is `band_gross_capped(T, BAND_WIDTH,
MAX_GROSS_STRESS)` on the spec's 13 names, read through `scripts/cef/spec.py` (as in
W4). Returns are **total returns** (`total_returns()`): a short pays its
distribution and a long receives it, as at a real broker. P&L comes only from
`evaluate()` (`shift(2)`).

- The **gross Sharpe on total returns is the headline**, with the price-return
  figure beside it. The paper account is scored on price returns.
- Borrow is charged separately under every proxy, each labelled; none is picked.
- Execution sits beside the gross: measured columns, then the 5/15/30bp grid.
- There is one book and one turnover path, so every comparison is
  turnover-matched by construction (H2). Only the cost assumption changes.
- "flips?" is YES when gross and the net columns do not all share a sign.

---

## The verdict

**The gate does not pass. Real capital waits.**

The only window where borrow is measured by name and date is 2021-09-14 →
2022-12-30: 328 sessions, with a fee on 98.8% of the short book. In it, the
deployed book loses money net of measured costs:

| net of measured borrow, 2021-09-14 → 2022-12-30 | %/yr | t (iid / NW) | circular block-bootstrap 95% CI |
|---|---:|---:|---|
| gross, total returns (the headline) | **+9.63** (SR 1.57) | | |
| measured borrow (IBKR FEE_RATE by name-date) | −13.11 | | |
| net, MOC at the print (regulatory fees only, 0.106bp) | **−3.51** | −0.65 / −0.64 | [−11.5, +5.6] |
| net, measured paper half-spread (6.01bp) | −5.10 | −0.94 / −0.94 | [−12.9, +3.8] |
| net, 15bp | −7.53 | −1.39 / −1.41 | [−15.0, +1.0] |
| net, 30bp | −11.57 | −2.13 / −2.19 | [−19.0, −3.1] |
| *sensitivity: per-share collateral round-up [U]*, MOC | −4.06 (borrow −13.66) | −0.75 / −0.74 | [−12.0, +5.0] |

The point estimate is negative under every execution assumption, including free
execution. The circular interval includes zero at MOC, at the half-spread and at
15bp, and excludes it only at 30bp. *(Corrected 2026-10-12: the first version
said it excluded zero at 15bp too, on a bootstrap that was not centred; see the
correction block above.)* On 328 sessions the measured window can show that the
book **was not positive**. It cannot show that the book was significantly
negative except at 30bp.

**Borrow decides the gate. Execution does not.**

- The short book paid a short-weighted **19.91%/yr** in that window, against a
  breakeven fee of **14.58%/yr** (at MOC).
- Over the book's whole live history (2013-06 → 2022), the breakeven uniform
  fee is **10.25%/yr** at MOC and **6.93%/yr** at 15bp.
- Priced at the five-year IBKR fee history, the book's typical 2013–22 short
  basket paid more than the 2013–22 breakeven (10.25% at MOC) on **58% of
  dates**: every date in 2021 and 2023, 96% in 2022, 64% in 2024, and **none in
  2025–26**. The figure uses the long-run breakeven because it reflects the
  book's edge over nine and a half years, not its best fifteen months. Against
  the measured window's own, higher breakeven (14.58%) the share is **44%**, or
  **42%** with that window's short composition. The full table is in §5.

**The book is positive net only in the fee regime of 2025–26, and nothing in it
reacts to fees.**

- At today's fee levels it is clearly positive on 2013–22: +5.46%/yr at
  IBKR's recent FEE_RATE (NW t 2.73, CI [2.2, 9.2]), +5.73%/yr at today's IBKR
  file, and +6.20%/yr at Alpaca's $0 for easy-to-borrow names (a lower bound on
  cost).
- At the 2021–22 fee level it is clearly negative: −5.45%/yr (NW t −2.70, CI
  [−8.9, −1.7]).
- At the 2021–26 average fee, the rule `docs/BRIEF.md` H4 prescribes for
  pre-2021 rows, it is negative: −1.88%/yr (NW t −0.93, CI [−5.3, +1.9]).
- **These figures assume an IBKR-like account that pays the fee and keeps its
  shorts.** On the Alpaca path a high-fee regime fails differently; see
  "Scope" below.

Execution has room to spare: today's fees leave a breakeven of 41–46bp per unit
of turnover, against a measured paper half-spread of 6bp.

**Provenance caveat on the deciding input.** The 2021–24 fee levels rest on one
source: IBKR's `FEE_RATE` bars. Their scale is verified: the 2026-09-06 public-file
rows equal FEE_RATE of 2026-09-04 to 0.005 percentage points on 13 names. Their
levels before 2026-09 are not. Every independent source tried failed (§2).
If those levels are wrong, so is this verdict. "What would change the verdict"
below says how to settle it.

---

## 1. The book and its distributions (§1)

Total returns, deployed policy. The P&L split between the legs uses the yield
*D*/*P*ₜ₋₁ on ex-dates, on the held book.

| window | gross SR | price SR | ann % | vol % | turn/yr | dist. leg %/yr | longs receive | shorts pay | avg short |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2005–09 | flat | | | | | | | | |
| 2010–14 | 0.72 | 0.90 | 2.24 | 3.12 | 5.2 | −0.70 | +1.71 | −2.41 | 0.18 |
| 2015–19 | 0.84 | 0.72 | 5.70 | 6.83 | 7.8 | +0.67 | +6.52 | −5.85 | 0.61 |
| 2020–22 | 1.02 | 1.08 | 6.49 | 6.36 | 21.5 | −0.61 | +4.82 | −5.43 | 0.55 |
| fit 2005–22 | **0.69** | 0.70 | 3.29 | 4.73 | 7.2 | −0.11 | +3.09 | −3.20 | 0.31 |
| live 2013-06 → 2014 | 1.30 | 1.63 | 7.33 | 5.65 | 16.3 | −2.31 | +5.60 | −7.91 | 0.59 |
| **live 2013-06 → 2022** | **0.96** | 0.96 | 6.21 | 6.50 | 13.5 | −0.21 | +5.83 | −6.05 | 0.58 |
| measured-borrow window | 1.57 | 1.77 | 9.63 | 6.15 | 26.6 | −1.67 | +5.79 | −7.46 | 0.64 |
| 2023–26 | sealed (H13) | | | | | | | | |

- These reproduce W4 exactly: gross SR 0.69 fit and 0.96 live; distribution leg
  −70 / +67 / −61bp/yr by era.
- Era turnover sd/mean is 37.1% on live sessions.
- **Distributions owed on shorts are a real cost, but the yields roughly net.**
  On live sessions, shorts pay 5.4–7.9%/yr of capital in distributions. Longs receive almost as
  much. The net leg is −0.21%/yr over the live history and −1.67%/yr in the
  measured window.
- W4 cross-checked the distribution panel against CRSP `ret`: 2,318 of 2,329
  distribution days matched, and the deployed P&L agrees to two decimals [S: W4
  note §1, not re-run here; the CRSP cache is not in this worktree].

## 2. Borrow: what is measured, and how a live account is charged (§2, §3)

**Source and coverage.**

- `data/cef/cef_borrow_history.parquet` is IBKR TWS
  `reqHistoricalData(whatToShow="FEE_RATE", 1 day)`. It was built by
  `fetch_borrow_history.py` (deleted 2026-09-28; at tag `pre-clean-slate`; it
  needs an IBKR session, which no longer exists).
- It covers all 13 deployed names from 2021-09-13 to 2026-09-09. Its fit-period
  part is 2021-09-13 → 2022-12-30, 319–327 dates per name.
- **There is no fee data before 2021-09-13.** Eight of the book's nine and a
  half live years have no measured borrow.

`data/cef/cef_borrow.csv` holds two kinds of row:

- 2026-09-06 and 2026-09-08 are IBKR's public shortstock file, with fee, rebate
  and availability. The two days are identical: the same file content was read
  twice.
- 2026-09-09 → 2026-09-21 are fee-only rows with no recorded source. On
  2026-09-09 they equal FEE_RATE exactly on 13 names.

**The fee history is not benign.** Cross-name mean fee by year, unweighted, %/yr:

| 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (to 09-09) |
|---:|---:|---:|---:|---:|---:|
| 21.29 | 21.12 | 21.73 | 9.36 | 2.96 | 1.25 |

**Today's fees.** IBKR's public file, stamped 2026.10.12 14:22:28, shows fees
from 0.29% (PDI) to 2.33% (MHD). PHK is 0.38%. Every name has at least 80,000
shares available.

**How Alpaca charges borrow on a live account** [V: Alpaca Brokerage Fee Schedule,
revised 2026-10-01; `docs/REFERENCES.md` §12l]:

- **Easy-to-borrow (ETB) names are free:** no locate fee and no borrow fee.
- **Hard-to-borrow (HTB) names pay two charges.**
  - A per-share **locate fee**, quoted by the Locates API, charged once and
    non-refundable.
  - A **daily borrow fee**: end-of-day short quantity rounded up to 100-share
    lots, × "a per-share collateral value from the prior trading day's closing
    price (adjusted by 102% and rounded up to the nearest dollar)", × the annual
    rate / 360, for every calendar day.
- **The round-up is ambiguous [U].** Alpaca's wording reads per share. IBKR's
  guide says the market value is marked up to 102% and rounded up to the
  nearest dollar, without saying whether per share or per position.
  - Per position, the round-up is at most $1 and negligible.
  - Per share, it is material on $4–15 funds: PHK at $4.13 carries $5 of
    collateral, 21% more than the flat 102%.
  - The base case here is the flat 102%. The per-share reading is sensitivity
    P0r (below).
- **Alpaca publishes no per-name HTB rate.** The locate-quote endpoint "is not
  available in paper trading" [V: API reference]. So **Alpaca's real-money HTB
  cost cannot be measured from the paper account**. It is a gap until a live
  account exists.

**Alpaca flags** (true on their date only):

- 12 of the 13 names are ETB on 2026-10-12.
- **PHK flipped ETB → HTB between 2026-09-28 and 2026-10-10.** IBKR charges it
  0.38% today.
- The four munis v7 dropped (NAD, NEA, NVG, NZF) were HTB on 2026-09-28 and are
  still HTB.
- Cross-tab against IBKR's fee a week earlier (2026-09-21): Alpaca's ETB names
  carried IBKR fees of 0.25–1.97% (median 0.68). Its HTB names carried
  2.85–6.18% (median 4.34).

**Is the IBKR history a fair proxy for Alpaca?**

- **While a name stays ETB, no.** Alpaca charges $0, and IBKR's fee overstates
  Alpaca's cost.
- **As a measure of the regime, yes.** Alpaca's ETB/HTB split lines up with
  IBKR's fee level on the one date the two can be compared. In 2021–22 IBKR's
  per-name mean fee on these names was 6–37% a year, and the cross-name mean
  was about 21% in each of 2021, 2022 and 2023. On that evidence almost all of them would
  have been HTB at Alpaca, paying an unpublished daily rate plus locate fees, or
  being unshortable.
- So Alpaca's $0 is today's regime, not a hedge against the next one. For an
  HTB name, IBKR's fee is the best available stand-in and probably a lower bound,
  because Alpaca adds a locate fee.

**The borrow proxies**, as drag in %/yr of capital, by era. P0 is a measurement.
P1–P4 apply one fee level per name to every session, so they are counterfactuals
(H4).

| proxy | 2010–14 | 2015–19 | 2020–22 | live 2013–22 | measured window | coverage |
|---|---:|---:|---:|---:|---:|---|
| **P0** IBKR FEE_RATE by name-date [measured] | — | — | — | — | **13.11** | 98.8% of the short book; the 31 uncovered name-days are not charged |
| P0+ P0, gaps carried from the last fee [assumption] | — | — | — | — | 13.25 | 100% |
| P0r P0, collateral rounded up per share [sensitivity, U] | — | — | — | — | 13.66 | 98.8% |
| P1 each name's 2021-09 → 2022 mean | 4.06 | 11.24 | 11.48 | 11.65 | 12.84 | 100% |
| P2 each name's 2021-09 → 2026-09 mean (`BRIEF` H4 rule) | 2.84 | 8.18 | 7.28 | 8.08 | 7.25 | 100% |
| P3 each name's mean over the last 63 FEE_RATE dates | 0.17 | 0.66 | 0.97 | 0.74 | 1.05 | 100% |
| P3f IBKR shortstock file, 2026-10-12 | 0.12 | 0.51 | 0.43 | 0.47 | 0.37 | 100% |
| P4 Alpaca flags 2026-10-12: ETB $0, HTB unpriced | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | live 79.5%: PHK, ~20% of the short book, unpriced (lower bound) |
| P4+ P4 with PHK at today's IBKR fee [stand-in] | 0.03 | 0.05 | 0.02 | 0.05 | 0.02 | 100% |
| P5 zero: the paper score | 0 | 0 | 0 | 0 | 0 | — |

**Where the measured drag went** (P0, measured window, bp/yr of capital):

| | HYT | DSL | PDO | PHK | PDI | JFR | PTY | PCN | PFN | MQY | AWF, BIT, MHD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| drag, bp/yr | 382 | 189 | 165 | 165 | 103 | 99 | 83 | 74 | 62 | 11 | 0 (not short) |

The pressure is spread across names, not one hard-to-borrow outlier. HYT, the
largest single drag, sat at 22.5% a year.

## 3. Execution (§4)

**What exists.**

- Five sessions have broker-confirmed fills:
  - 2026-09-29: `cls`, 2 fills (the paper under-fill day);
  - 2026-09-30, 2026-10-01, 2026-10-07 and 2026-10-08: the paper `late_market`
    exception. That is 32 orders and 88 fills.
- Sessions with a plan and no fills: 2026-10-02, 10-05 and 10-06 (the laptop was
  asleep or offline) and 2026-10-09 (refused at send). The VM copy was taken on
  2026-10-11, so the 2026-10-12 session's fills are not in these records.
- The records were read in place: the laptop's `~/quantt_state/cef` and the VM
  copy. They match a fresh broker read of `/v2/account/activities/FILL` fill for
  fill on all five days.

| session | mode | orders | fills | slippage vs print, bp | = half-spread paid | + drift, quote → print | verify recorded | ADV participation, median / max |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-09-29 | cls | 2 | 2 | 0.00 | 10.61 | −10.60 | +0.0 | 0.31% / 0.35% |
| 2026-09-30 | late_market | 7 | 18 | +5.76 | 6.50 | −0.75 | (verify errored) | 0.13% / 0.42% |
| 2026-10-01 | late_market | 5 | 17 | +5.10 | 6.33 | −1.22 | (verify errored) | 0.04% / 0.38% |
| 2026-10-07 | late_market | 12 | 27 | −17.95 | 5.39 | −23.35 | −17.9 / −17.95 | 0.02% / 0.50% |
| 2026-10-08 | late_market | 8 | 26 | +15.75 | 6.09 | +9.67 | +15.8 | 0.09% / 0.22% |

How these are measured:

- Slippage is notional-weighted bp against the primary exchange's official
  closing-auction print, condition M, fetched again from Alpaca. Positive means
  worse than the print.
- Each fill is split against the last SIP NBBO in the 60 seconds before it.
  Every fill had one, and every paper fill was at the touch.
- Participation uses the panel's 63-day ADV as of 2026-09-28.

**Uncertainty with n = 4 `late_market` sessions:**

| quantity | pooled | session mean | session sd | 95% CI (t, 3 df) |
|---|---:|---:|---:|---|
| slippage vs print | −0.68 | +2.17 | 14.27 | **[−20.5, +24.9]** |
| half-spread paid | 6.01 | 6.08 | 0.49 | [5.3, 6.9] |
| drift, quote → print | −6.69 | −3.91 | 13.90 | [−26.0, +18.2] |

- Order-level slippage has a median of 10.2bp and an sd of 30.8bp over 32
  orders. Orders within a session share the market's move, so that sd is not a
  standard error.
- The half-spread is measured tightly. The slippage against the print is a
  stable 6bp half-spread plus a drift over the last eight minutes. The drift has
  zero mean and an sd of about 14bp per session, and four sessions cannot tell
  0bp from 20bp.

**Which measured quantity proxies the real-money cost, and why.** A live account
sends MOC (`cls`). The `late_market` exception never applies to it (`CLAUDE.md`
order-path rule 3). **An MOC order fills at the auction print itself**, so it pays
neither the paper half-spread nor the paper drift. The backtest prices at the
panel close, which equalled the NYSE auction print on 96.6% of name-days in
2016–22 [S: W4 §2]. The real-money cost relative to the model is therefore:

- **regulatory fees**: 0.106bp per unit of turnover. That is the SEC fee of
  0.206bp on the 50% of turnover that sells, plus CAT; TAF is $0 and there is
  no commission [V: fee schedule];
- **our own impact in the auction: UNMEASURED.** There are no live auction
  fills (n = 0), and paper runs no auction. In these five sessions our orders
  were at most 0.5% of 63-day ADV.

The measured paper half-spread (6.0bp) is the cost of any live session that
misses the 15:50 MOC cut-off and has to cross. It serves as a pessimistic
reference, not an estimate of the MOC cost. The paper slippage against the print
adds only noise to that.

**Execution does not bind.** The breakeven cost per unit of turnover after borrow
is:

- 40.6bp (P3), 42.6bp (P3f) and 46.1bp (P4) on 2013–22;
- **negative under P0, P1 and P2**: no execution cost, however low, makes the
  book positive at those fees.

## 4. Net of measured costs, by era (§5)

Net SR (net %/yr). MOC = regulatory fees only. hs = the measured half-spread
(6.01bp). slipHi = the upper 95% bound of the measured paper slippage (24.9bp).

**P1: each name's 2021-09 → 2022 mean fee [counterfactual]**

| window | gross SR | borrow %/yr | MOC | hs | slipHi | 5bp | 15bp | 30bp | flips? |
|---|---:|---:|---|---|---|---|---|---|---|
| 2010–14 | 0.72 | 4.06 | −0.58 (−1.8) | −0.68 (−2.1) | −0.97 (−3.1) | −0.66 (−2.1) | −0.82 (−2.6) | −1.05 (−3.3) | YES |
| 2015–19 | 0.84 | 11.24 | −0.81 (−5.5) | −0.88 (−6.0) | −1.10 (−7.5) | −0.87 (−5.9) | −0.98 (−6.7) | −1.15 (−7.9) | YES |
| 2020–22 | 1.02 | 11.48 | −0.79 (−5.0) | −0.99 (−6.3) | −1.61 (−10.3) | −0.95 (−6.1) | −1.29 (−8.2) | −1.78 (−11.4) | YES |
| live 2013–22 | 0.96 | 11.65 | −0.84 (−5.4) | −0.96 (−6.2) | −1.34 (−8.8) | −0.94 (−6.1) | −1.14 (−7.5) | −1.45 (−9.5) | YES |

**P2: each name's 2021-09 → 2026-09 mean fee (the `BRIEF` H4 rule)**

| window | gross SR | borrow %/yr | MOC | hs | slipHi | 5bp | 15bp | 30bp | flips? |
|---|---:|---:|---|---|---|---|---|---|---|
| 2010–14 | 0.72 | 2.84 | −0.19 (−0.6) | −0.29 (−0.9) | −0.59 (−1.8) | −0.27 (−0.9) | −0.43 (−1.4) | −0.67 (−2.1) | YES |
| 2015–19 | 0.84 | 8.18 | −0.36 (−2.5) | −0.43 (−3.0) | −0.65 (−4.5) | −0.42 (−2.9) | −0.54 (−3.7) | −0.71 (−4.9) | YES |
| 2020–22 | 1.02 | 7.28 | −0.13 (−0.8) | −0.33 (−2.1) | −0.96 (−6.1) | −0.29 (−1.9) | −0.63 (−4.0) | −1.12 (−7.2) | YES |
| live 2013–22 | 0.96 | 8.08 | −0.29 (−1.9) | −0.41 (−2.7) | −0.80 (−5.2) | −0.39 (−2.5) | −0.60 (−3.9) | −0.90 (−5.9) | YES |

**P3: each name's IBKR FEE_RATE mean over its last 63 dates (to 2026-09-09) [today]**

| window | gross SR | borrow %/yr | MOC | hs | slipHi | 5bp | 15bp | 30bp | flips? |
|---|---:|---:|---|---|---|---|---|---|---|
| 2010–14 | 0.72 | 0.17 | 0.66 (2.1) | 0.57 (1.8) | 0.26 (0.8) | 0.58 (1.8) | 0.42 (1.3) | 0.18 (0.6) | no |
| 2015–19 | 0.84 | 0.66 | 0.74 (5.0) | 0.67 (4.6) | 0.45 (3.1) | 0.68 (4.6) | 0.56 (3.9) | 0.39 (2.7) | no |
| 2020–22 | 1.02 | 0.97 | 0.86 (5.5) | 0.67 (4.2) | 0.03 (0.2) | 0.70 (4.4) | 0.36 (2.3) | −0.14 (−0.9) | **YES** |
| live 2013–22 | 0.96 | 0.74 | 0.84 (5.5) | 0.72 (4.7) | 0.33 (2.1) | 0.74 (4.8) | 0.53 (3.4) | 0.22 (1.4) | no |

**P4: Alpaca flags of 2026-10-12, ETB $0 and PHK unpriced [lower-bound cost]**

| window | gross SR | borrow %/yr | MOC | hs | slipHi | 5bp | 15bp | 30bp | flips? |
|---|---:|---:|---|---|---|---|---|---|---|
| 2010–14 | 0.72 | 0.00 | 0.71 (2.2) | 0.62 (1.9) | 0.32 (1.0) | 0.64 (2.0) | 0.48 (1.5) | 0.24 (0.7) | no |
| 2015–19 | 0.84 | 0.00 | 0.83 (5.7) | 0.77 (5.2) | 0.54 (3.7) | 0.78 (5.3) | 0.66 (4.5) | 0.48 (3.3) | no |
| 2020–22 | 1.02 | 0.00 | 1.02 (6.5) | 0.82 (5.2) | 0.18 (1.2) | 0.85 (5.4) | 0.51 (3.3) | 0.01 (0.1) | no |
| live 2013–22 | 0.96 | 0.00 | 0.95 (6.2) | 0.83 (5.4) | 0.44 (2.9) | 0.85 (5.5) | 0.64 (4.2) | 0.33 (2.2) | no |

The rest of the net tables are in the output file:

- P3f is slightly better than P3 (0.04–0.11 SR), because today's file fees are
  lower than the last-63-date FEE_RATE mean.
- P4+ matches P4, and P5 equals P4.
- P0, P0+ and P0r exist only in the measured window (the verdict table above).
- The "fit 2005–22" harness rows are diluted by the flat pre-2013 sessions.

Under every low-fee proxy, 2020–22 at 30bp sits at about zero (−0.14 to +0.01).
That repeats W4's finding (+0.01 at 30bp, no borrow).

## 5. The gate, under each proxy (§6)

The rows below are the book's live history 2013-06 → 2022 (2,398 sessions),
except P0 and P0r, which cover the measured window only. Each cell is net %/yr,
the Newey–West(5) t, and the **circular** block-bootstrap 95% interval (20-session
blocks, 2,000 reps). *(Corrected 2026-10-12: the first version used W4's
non-circular bootstrap; see the correction block at the top. The script prints
both.)*

| proxy | MOC | measured half-spread | 15bp | 30bp | verdict at MOC |
|---|---|---|---|---|---|
| P0 measured (window only, 328 sessions) | −3.51 (−0.64) [−11.5, +5.6] | −5.10 (−0.94) [−12.9, +3.8] | −7.53 (−1.41) [−15.0, +1.0] | −11.57 (−2.19) [−19.0, −3.1] | **not positive** |
| P0r per-share round-up [U] (window) | −4.06 (−0.74) [−12.0, +5.0] | −5.65 (−1.05) [−13.5, +3.2] | −8.07 (−1.51) [−15.6, +0.5] | −12.12 (−2.29) [−19.5, −3.6] | **not positive** |
| P1 2021–22 level | −5.45 (−2.70) [−8.9, −1.7] | −6.24 (−3.11) [−9.6, −2.5] | −7.46 (−3.72) [−10.8, −3.8] | −9.48 (−4.73) [−12.9, −5.9] | **negative, CI < 0** |
| P2 2021–26 mean (`BRIEF` H4) | −1.88 (−0.93) [−5.3, +1.9] | −2.68 (−1.33) [−6.1, +1.1] | −3.89 (−1.94) [−7.2, −0.2] | −5.91 (−2.95) [−9.2, −2.2] | **not positive** |
| P3 IBKR recent | +5.46 (2.73) [2.2, 9.2] | +4.66 (2.34) [1.5, 8.3] | +3.45 (1.74) [0.3, 7.0] | +1.43 (0.72) [−1.8, 4.9] | positive, CI > 0 |
| P3f IBKR file today | +5.73 (2.86) [2.5, 9.4] | +4.93 (2.48) [1.7, 8.6] | +3.72 (1.88) [0.5, 7.3] | +1.70 (0.86) [−1.5, 5.2] | positive, CI > 0 |
| P4 Alpaca today (lower bound) | +6.20 (3.10) [2.9, 9.9] | +5.40 (2.71) [2.2, 9.0] | +4.19 (2.11) [1.0, 7.7] | +2.17 (1.09) [−1.1, 5.7] | positive, CI > 0 |
| P5 no borrow (paper) | +6.20 (3.10) [2.9, 9.9] | +5.40 (2.71) [2.2, 9.0] | +4.19 (2.11) [1.0, 7.7] | +2.17 (1.09) [−1.1, 5.7] | positive, CI > 0 |

The circular interval and the Newey–West t agree in sign everywhere. Three rows
are borderline on significance: the interval just excludes zero while |NW t| is
below 1.96. They are P2 at 15bp ([−7.2, −0.2], t −1.94), P3 at 15bp ([0.3, 7.0],
t 1.74) and P3f at 15bp ([0.5, 7.3], t 1.88). Read all three as not significant.
*(Corrected 2026-10-12: the first version said "the iid and Newey–West t agree
with the bootstrap in every row". On the uncentred bootstrap they did not.)*

**Breakevens (computed, not quoted; H14).**

| window | collateral | gross %/yr | turn/yr | drag per 1% fee | f* at MOC | f* at 15bp |
|---|---|---:|---:|---:|---:|---:|
| live 2013-06 → 2022 | flat 102% | 6.21 | 13.5 | 0.605%/yr | **10.25%** | **6.93%** |
| live 2013-06 → 2022 | per-share round-up [U] | 6.21 | 13.5 | 0.626%/yr | 9.90% | 6.69% |
| measured window | flat 102% | 9.63 | 26.6 | 0.659%/yr | 14.58% | 8.55% |
| measured window | per-share round-up [U] | 9.63 | 26.6 | 0.686%/yr | 14.00% | 8.21% |

Under the per-share reading every breakeven is about 3–4% lower.

The table below takes the live-history short book's composition (each name's
share, 2013–22; 12 names) and prices it at the FEE_RATE history. 1,135 of 1,253
dates have a fee for every name.

| year | dates | mean fee %/yr | above f* at MOC | above f* at 15bp |
|---|---:|---:|---:|---:|
| 2021 | 72 | 14.52 | 100% | 100% |
| 2022 | 223 | 20.82 | 96% | 100% |
| 2023 | 225 | 25.08 | 100% | 100% |
| 2024 | 227 | 12.64 | 64% | 93% |
| 2025 | 233 | 3.17 | 0% | 0% |
| 2026 | 155 | 1.35 | 0% | 0% |
| all | 1,135 | 13.35 | **58%** | **64%** |

**Which breakeven, and why** (added 2026-10-12, after review). The table above
sets the 2013–22 short basket against the **2013–22 breakeven**. That is the
book's long-run edge: its gross and turnover over nine and a half years. The
measured window was the book's best stretch (gross 9.63%/yr against 6.21% long
run), so its own breakeven is higher, and judged against it the share falls:

| short-book composition | breakeven from | f* at MOC | share above | f* at 15bp | share above |
|---|---|---:|---:|---:|---:|
| 2013–22 | 2013–22 (long run) | 10.25 | **58%** | 6.93 | 64% |
| 2013–22 | measured window | 14.58 | **44%** | 8.55 | 61% |
| measured window | 2013–22 | 10.25 | 49% | 6.93 | 61% |
| measured window | measured window | 14.58 | **42%** | 8.55 | 56% |

The headline is 58% because a book is deployed on its long-run edge, not its
best fifteen months. Under every pairing, the fee history sat above the
breakeven on 42–64% of dates.

**The live paper record** is read with `python3 -m ops.orient` (PROD, broker-confirmed
equity); no account figure is copied here. It is gross, because paper charges no
borrow and credits no distributions, and it covers nine sessions, five of which
traded. At that n it is no evidence either way.

## 6. Second methods (§7)

| figure | method 1 | method 2 | agree? |
|---|---|---|---|
| measured borrow drag, window | mean of daily name-date products: 13.11%/yr | product of per-name means: 12.78% | yes (the gap is the short–fee covariance) |
| | fee dated *t*−1 | fee dated *t*: 12.92% | yes |
| | daily fees | each name's median window fee, held constant: 12.31% | yes. Spikes do not drive it |
| | gaps not charged: 13.11% | gaps carried forward (P0+): 13.25% | yes |
| gross baseline | this run: 0.69 fit / 0.96 live (total), 0.70 fit (price) | W4 2026-10-11: 0.69 / 0.96 / 0.70 | exact |
| cost-grid booking | harness `_stats`: 0.619 / 0.467 / 0.240 | fill-day series: 0.619 / 0.467 / 0.239 | yes |
| fills | records (laptop and VM copies) | fresh broker read, `/v2/account/activities/FILL` | match on all 5 days |
| slippage | this script: −17.95 / +15.75bp | verify's own: −17.95 (`tca.csv`) / +15.8bp | yes |
| auction prints | re-fetched from Alpaca | `reconcile.json` prints | equal where both exist |
| significance | iid t | Newey–West t; circular block bootstrap (W4's non-circular printed beside it) | same signs; three borderline 15bp rows named in §5 *(corrected 2026-10-12)* |
| collateral | flat 102%: 13.11%/yr | per-share round-up [U]: 13.66%/yr (P0r) | sensitivity; the sign is unchanged |
| **2021–24 fee levels** | IBKR FEE_RATE | **none found** (§2) | **single source** |

## Scope: which account the −3.5%/yr describes (added 2026-10-12)

**The measured-borrow figures describe an IBKR-like account**: one that pays the
fee and keeps its shorts. On the Alpaca path, in a regime like 2021–22's, the book
would more likely fail to open its shorts than pay 13%/yr.

- **At those fees these names would very likely be hard-to-borrow at Alpaca**
  (§2). In the probes here, every name Alpaca has called hard-to-borrow has also
  been `shortable: false`: NAD, NEA, NVG and NZF on 2026-09-28 and 2026-10-12,
  and PHK on 2026-10-10 and 2026-10-12.
- **A name that is not `shortable` today sends nothing.** `decide` sends no
  order for it and substitutes no other name (`quantt/session/decide.py`). Gate 7
  keys on `shortable` only (`quantt/session/gate.py`, `gate_shortability`).
- **A name that is `shortable` but hard-to-borrow draws only a preview warning**
  (`hard_to_borrow_short_opens` in `quantt/session/run.py`). A live short-open in
  it needs a paid locate. If Alpaca rejects the order, `_transmit` skips that
  name, sends the rest (team lead, 2026-09-28) and marks the day FAIL.
- **So the Alpaca book in a high-fee regime would run without some or all of its
  shorts**: net long, a beta position the alpha-only mandate rules out. Passing
  the gate on cost alone would not make the Alpaca book safe in that regime.
  What it needs is a decision on what the book does when its shorts become
  hard-to-borrow, and that is the team lead's.
- **Side finding (not changed here; live-path documentation).** The module
  docstring of `quantt/session/decide.py` ("The runner stops the batch at the
  first rejection ... (gate 6)") and the `hard_to_borrow_short_opens` docstring
  ("any rejection stops the batch") contradict `_transmit`. `_transmit` skips a
  rejected name and sends the rest, and stops only on an ambiguous or unknown
  outcome.

## What would change the verdict

1. **A second source for 2021–24 borrow levels.** IBKR activity statements from
   any account that was short these names, a paid Markit, S3 or Ortex history, or
   an iborrowdesk export. The measured window turns positive at MOC only if the
   true fees were more than 27% below FEE_RATE (19.91% paid against a 14.58%
   breakeven), and at 15bp only if they were more than 57% below (breakeven
   8.55%). P1 and P2 would move with it.
2. **A book that stops shorting at fees above its own alpha.** The book has no
   borrow awareness. A pre-registered borrow-aware short rule is the direct
   answer, net of the fee at *t*: exclude or cap a short whose fee exceeds its
   expected discount closure. **It would spend a CEF trial** (bar 2.80 at N = 51),
   and it is not on the plan's list. C1 (corporate actions) and C2 (fair-value
   conditioners) do not touch borrow. Ordering is the team lead's call.
3. **Evidence that the 2025–26 regime persists.** Today the book clears with
   room (f* 10.25% against fees of about 0.3–2.3%). That evidence would have to
   be measured going forward. Plan item 0.3 records Alpaca's flags daily; it
   should record the IBKR file's fees too, so that the short book's live
   short-weighted fee can be set against f* every session.
4. **Not execution.** Even the upper bound of the paper slippage (24.9bp)
   leaves 2013–22 positive at today's fees. Live auction impact is unmeasured
   but is unlikely to approach a 41–46bp breakeven at 0.5% of ADV. **No
   execution result can rescue the high-fee regime**, because c* is negative
   there.
5. **An older fee history** (added 2026-10-12). The history starts on 2021-09-13
   because the deleted fetcher's default was `--years 5` (`durationStr` "5 Y",
   built about 2026-09-10 [S: `docs/BRIEF.md` H4]; the code is at
   `pre-clean-slate:_archive/scripts/cef/fetch_borrow_history.py`). Nobody has
   shown that IBKR serves no `FEE_RATE` before then; it is untested [U], and the
   desk no longer runs an IBKR session. If the history goes further back, the
   2013–21 rows could be measured instead of assumed.
6. **The sealed 2023–26 period** (added 2026-10-12). From 2023-01-03 to
   2026-09-09, FEE_RATE covers all 13 names on 831 of the 924 sessions, and the
   panel has returns for every one. It is the only place where a **measured** net
   across both fee regimes could be computed: about 22% a year in 2023 and 1–3%
   in 2025–26. Opening it consumes the 2023-01-01 time holdout (H13) for every
   later test. That is the team lead's decision, and this note does not open it.
7. **A per-name view of "today"** (added 2026-10-12). Today's regime is not
   uniform. HYT, the largest single drag in the measured window (382bp/yr),
   shows **10.56% on every FEE_RATE date from 2026-08-21 to 2026-09-09**. The
   2026-09-04 public-file row agrees at 10.562%. Today's file shows 0.43%. A low
   cross-name mean can hide one name at 10% or more for weeks, so any live
   borrow check (item 3) has to be per name and weighted by the short book.

## What this means for sizing (portfolio-manager note)

Borrow scales with the short book, so it scales one for one with the vol target
until the 1.8× gross ceiling binds. At the book's average short of 0.58 of
capital (2013–22), each 1% of fee costs 0.605%/yr. Doubling the vol target (W6)
roughly doubles that drag. At the 2021–24 fee levels it roughly doubles a loss.

A derived vol target therefore needs a **borrow-regime constraint** beside the
kill-probability and margin-cushion constraints. Until the book can stop
shorting into expensive borrow, the case for levering it rests on a fee regime
that did not hold on 42–58% of the dates in the fee history, depending on which
breakeven is used (§5).

- **Downside if this verdict is wrong:** waiting forgoes about 5.5–6%/yr net at
  today's fees (P3–P4 at MOC, 2013–22), on whatever capital was planned, for as
  long as the wait lasts.
- **Downside of deploying wrongly:** if fees return to 2021–24 levels, the book
  loses an estimated 3.5–7.5%/yr at about 6% vol. Nothing would stop it except
  the kill rule, which is reviewed at 60 live sessions (spec `kill_rule`;
  `results/cef/PREREG_ALPACA_V7_2026-09-28.md`).

## Gaps

- **The 2021–24 borrow level is single-source** (FEE_RATE). The tries are listed
  in `docs/REFERENCES.md` §12l.
- **No borrow before 2021-09-13.** The 2013–21 rows are counterfactual under
  every proxy. The start date is the fetcher's default, not a proven limit of the
  source [U].
- **Collateral round-up, per share or per position [U].** The base case is the
  flat 102%; per share (P0r) adds about 0.5pp a year of measured borrow.
- **Alpaca's live HTB rates and locate fees are unpublished.** The locate API is
  unavailable on paper. P4 is a lower bound; P4+ uses IBKR's fee as a labelled
  stand-in.
- **Own impact in a live closing auction: n = 0.** Paper does not simulate the
  auction (`CLAUDE.md` landmine 1).
- **Execution: n = 4 `late_market` sessions.** The half-spread is tight; the
  slippage against the print is not.
- **Not modelled:**
  - the tax treatment of payments in lieu (`docs/REFERENCES.md` §4);
  - interest on credit balances. The backtest earns none, and a dollar-neutral
    book at or under 1.8× gross carries no debit balance, so no margin interest
    at 6.25%;
  - recall and buy-in risk;
  - availability limits beyond today's file;
  - HTB 100-share lot rounding.
- **Survivorship**, as before: unmeasured, and biased upward.
- **The time holdout (2023+) was not opened.** No 2023+ return or position was
  computed.
