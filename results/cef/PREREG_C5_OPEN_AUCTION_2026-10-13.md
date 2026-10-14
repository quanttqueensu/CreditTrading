# Pre-registration — C5: fill the CEF book at the t+1 opening auction, not the t+1 closing auction

**Date** 2026-10-13 · **Counter** CEF, one trial (50 → 51 if C5 is the next CEF
trial approved; 52 if C4 is approved first) · **Pass bar**
`scripts/cef/validate.py::_dsr` > 0.95 at the CEF counter's N, on the series
decision 2 names · **Source** `results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md`
§1 (rank 1) · **Author** research agent, branch `research-prereg-c5`

> **DRAFT — awaiting team-lead approval; the counter moves only in the commit that records approval.**
>
> **Nothing has run.** No P&L, Sharpe, IC, session or overnight return, gain,
> or volatility of any of them was computed to write this. The only
> measurements are counts and shares on the data and arithmetic on the bar:
> opening-print coverage by name and year, the declared price rule's defect
> classes, the two evaluation sets' holdings paths (trade counts and turnover,
> from H alone), and the power of the bar
> (`python3 scripts/cef/c5_feasibility.py`, run 2026-10-13, output
> `results/cef/c5/c5_feasibility_output_2026-10-13.txt`).
>
> This commit moves no counter, changes no spec, does **not** edit
> `CLAUDE.md` (the rule-3 text in §16 is a draft), and touches nothing on the
> order path. No order endpoint was called.

---

## 0. The declaration in one table

| item | declared |
|---|---|
| what is tested | whether filling the live book's trades at the **t+1 opening auction** instead of the t+1 closing auction earns the t+1 session the decision on *t*'s NAV can reach. Same evening decision, same holdings path, same turnover |
| the decision series | **the gain** G, row s: Σᵢ (Hₛ₋₁,ᵢ − Hₛ₋₂,ᵢ) · (Cₛ,ᵢ / Oₛ,ᵢ − 1). The day's trade, times the session it is earlier for (§5) |
| fill price | the NYSE opening-auction **trade** print: Alpaca SIP `/v2/stocks/auctions`, exchange `N`, condition `O` (§4.2) |
| evaluation set | **WIDE decides**; the deployed fit sample and WIDE's at-or-above-floor trades must agree in sign (decision 1) |
| decision window | 2016-01-04 → 2022-12-30, 1,762 sessions: the span that has the official print (decision 3) |
| holdout | 2023-01-03 → **2026-09-30 (fixed)**, 939 sessions, opened once |
| headline | the gain's annualised Sharpe and its HAC t; the C5 and deployed books' gross Sharpes beside it, with net at 5 / 15 / 30bp and the measured open surcharge as its own row |
| kills | D1 (t < 1.96; the stale-open stratum; the lagged-signal placebo; the shuffled-trade placebo), D4 (alpha t < 3.0 or \|β\| > 0.10), the evaluation-set sign checks, D3 (holdout sign) |
| pass | every kill survived, `_dsr` > 0.95 at N on the gain, the holdout sign agrees |
| if it passes | nothing trades until the team lead approves the spec change (§1), the rule-3 amendment (§16) and a single `opg` acceptance test on paper |

### 0.1 Decisions left for the team lead

Each has a stated default, so the document is complete as written. Approval
approves the defaults unless a ruling says otherwise.

| # | decision | this draft's default | the alternative, and what it changes |
|---|---|---|---|
| **1** | **The evaluation set** (candidates note, "What should change in the order of phase 2", item 1; W10-B §10). Still open, and C5 depends on it | **WIDE decides** (the same 13 names and rule with the ADV floor at 0). Two guards, both kills: the **deployed fit sample's** gain must be > 0, and **WIDE's gain on trades in names at or above the floor** must be > 0. Why: today's book trades nearly every session (the deployed set had at least 6 names above the floor on 85.3% of holdout sessions, against 40.2% in 2016–22 [V]). WIDE makes material trades on 1,571 of 1,762 sessions, the deployed set on 606 [V]. The gain lives only on trade days: if it were the same per trade session in both sets, the deployed set's gain Sharpe would be about √(606/1,571) ≈ 0.62 of WIDE's [arithmetic, U] | **(A) Deployed decides**, WIDE a sign check: the spec's own historical book, with no harness flag needed, but only 1,763 trade name-days, 45 of them in munis (WIDE: 6,456 and 1,143) [V]. Power falls by roughly the factor above. **(B) Both must pass the bar**: more conservative again, and it fails if either does. What WIDE costs: **54% of its trade name-days in 2016–22 (3,483 of 6,456) are in names below the $3m ADV floor** on the decision date [V]. Those are trades the live spec would not have made then, which is why the at-or-above-floor guard is a kill |
| **2** | **Which series the bar is applied to** | **The gain G.** C5 changes when the trades fill, not what is held. The question is whether that is worth anything, and G is exactly that difference (§5). Its Sharpe is not diluted by the held book's variance, which C5 leaves untouched | **The C5 book's own gross Sharpe.** This re-tests the deployed signal (already live under its own pre-registration). At the prior (+0.1 to +0.3 on the deployed 0.96 [S]) it passes with probability **0.05–0.13** over 2016–22 even if C5 is exactly as good as hoped (§12.3). Reported beside the decision either way |
| **3** | **The decision window** | **2016-01-04 → 2022-12-30 on the official print only.** `leadlag` died on an effect measured on a price nobody could trade. Before 2016 the repo has no auction print | **From first position + 2 sessions, with CRSP `openprc` before 2016** (WIDE: 17.97 years, bar 1.05; deployed: 9.52 years, bar 1.44 [V, arithmetic]). CRSP `openprc` equals the 2016–22 `O` print within $0.005 on 98.4% of name-days [V], so it is close. It is a consolidated first price, though, not a documented auction print. It is reported as R-PRE16 in any case |
| **4** | **Live: an `opg` order that does not fill, or a plan not sent by 09:25 ET** | **The residual goes to that day's closing auction as `cls`** (on paper, through the `late_market` path), logged as an open miss. The holdings path is then still H, and the backtest's no-cross rule (§4.2) is the same rule | drop it, and let the next evening's band re-decide. The live book then departs from H, and the backtest would have to model that |
| **5** | **When the `opg` set is sent** | **In the morning, 06:00–09:25 ET, from the plan saved in the evening, never re-decided.** Nothing goes before 06:00, so an overnight `DRY_RUN=1` or halt still wins (rule 4) | **in the evening after 19:00 ET** (Alpaca queues it for the next open). This gives more retry room, but an order queued at the broker outlives a later `DRY_RUN=1` |
| **6** | **Paper** | Before any C5 sleeve: **one `opg` order on the cef paper account, on the team lead's go**. It settles whether paper accepts `opg` and how it fills it. No paper-only substitute for `opg` is assumed; one would be a separate ruling (§16) | skip the test and send `opg` from the first C5 session |
| **7** | The rule-3 amendment | **considered only after a PASS**; the §16 text is a draft | rule on it in principle now, so a PASS can go straight to release |
| **8** | When the counter moves | in the commit that records approval (the `/prereg` skill; the team lead accepted the same default for C4 on 2026-10-13, main `7512c98`) | at the run (the XASSET convention) |
| **9** | The holdout end | **2026-09-30, fixed** (the XASSET review, 2026-10-13, finding 5; the same proposal is pending for C4) | "the panel's last date at run time": this lets whoever runs the trial choose the end date |
| **10** | Spend now or defer, and the order against C4 | §12.3: P(pass) cannot be stated without the gain's own volatility, which is the trial's statistic. At the prior's midpoint it is 0.80 if the gain's volatility is a tenth of the book's, and 0.035 if it is a fifth | defer |

---

## 1. What is tested, and what is not

**Tested.** One binary question at identical holdings. Each evening the book
decides on *t*'s NAV. Is it better to fill that trade in the t+1 opening
auction than in the t+1 closing auction?

**Not tested:**

- a new signal, window, threshold or sizing rule. Every parameter is the
  spec's and nothing is swept;
- intraday entry at any other time (a limit order, a VWAP, a pre-market
  order). The 2026-07-31 overnight market order is the dead relative (§2);
- the 27-name set. Only the 13 spec names are read, so it is not consumed.

**What changes if it passes and the team lead approves** (none of it in this
commit):

- the frozen spec's existing `frozen.order_type`, `"MOC"` → `"MOO"`, through
  `/spec-change`;
  - the candidates note proposed a new key `fill_auction`; using the existing
    key avoids a new key;
  - whichever is chosen, the no-op proof is byte-for-byte on the sleeve
    output with the value or key absent;
- the runner's send path (§16);
- `CLAUDE.md` rule 3 (§16).

**Revert:** `"MOO"` → `"MOC"`, and the runner sends `cls` exactly as today.

## 2. Mechanism, who is on the other side, and the graveyard

**Mechanism** (the candidates note §1; figures [S], from
`scripts/cef/core_signal_decomp.py t1`, not re-run here):

- The NAV is struck after the close and published in the evening. On
  2026-09-28 it landed at 21:21–21:51 ET (`docs/RUNNER.md`).
- The t+1 opening cross is set by orders queued against the last price.
- On the NYSE opening print, 2016–22, the IC of z on the **t+1 session** is
  **−0.046 (t −2.85)**. The overnight gap to the opening auction is −0.027
  (t −1.68), both on the 2016–22 common sample.
  - The overnight part is not zero on this sample, so the open does not
    capture all of day t+1.
  - On the full-sample yfinance and CRSP opens (2005–22) the overnight IC is
    +0.005 and +0.002.
- t's **NAV move** predicts the t+1 session (−99bp per unit, t −2.57). t's
  price move does not.
- **The price takes in t's NAV during t+1's session**, after the opening
  auction. A book that fills at the open holds the trade over that session; a
  book that fills at the close does not.

**Who is on the other side.** The overnight retail order and the market maker
anchored on close *t*, crossing at the open before the NAV is in the price.

**Why it persists.** There are no authorised participants, the share count is
fixed, holders are retail, and the horizon is one session.

**Graveyard** (`/graveyard`, `docs/RESEARCH_STATE.md`):

| dead relative | why C5 is or is not it, and where the risk remains |
|---|---|
| **The 2026-07-31 overnight market order** (100.5bp realised against a 32.6bp breakeven, filled 07:27 ET pre-market; `CLAUDE.md` rule 3) | An `opg` order is auction-only. It cannot fill pre-market or in the continuous market (REFERENCES §12o [V]). **Risk remains** in the open cross's cost: §6 puts the measured surcharge on its own row, and §15 makes the live cost a falsifier |
| `leadlag` (an effect on a price nobody could trade) | The fill price is the auction trade print itself, and the decision window is where that print exists (decision 3) |
| the `shift(1)` incident (entering at *t*'s close on *t*'s NAV) | Not that. The session leg starts at the t+1 open, after *t*'s NAV is public, and the overnight leg stays with the book decided a day earlier (§5). A test pins it |
| the stale-price family (six of thirteen deaths) | The opposite direction: here the price lags a fresh NAV. **Risk remains**: an opening print sitting at close *t* would book day t+1's whole move as "session". 14.5% of name-days are such [V]. That stratum is a kill (§9) |
| three deaths to their own control group | The lagged-signal placebo and the shuffled-trade placebo are kills (§9) |
| `z_window = 63` (an argmax) | Nothing is chosen. There is no free parameter |

## 3. Divergences from the backtest, stated up front

Everything a live C5 book would do that this trial does not:

1. **Our own impact on the opening print.** The backtest fills at the print
   every participant got. The open cross is about 4.8× the close in shares
   (last 60 sessions), and the book's orders are about one-fifth the
   participation (EXEC note §2–§5 [S]). Unmeasurable before live money.
2. **Paper runs no auction on either side.** How paper fills `opg` is [U]
   (decision 6). Paper scoring is §15.
3. **`opg` availability** for this account type and for a live account is
   [U]: Alpaca's pages disagree (REFERENCES §12o).
4. **Missed opens.** A plan not sent by 09:25 ET, or an `opg` residual, goes
   to the close (decision 4). The backtest has no missed sends.
5. **Late opens.** An MOO order waits for the DMM to open the name. In 2016–22
   the NYSE `O` print came after 09:35 ET on 70 of 21,601 name-days, and after
   10:00 on 9 [V]. The backtest uses the print whenever it came.
6. **Whole shares**; Alpaca `opg` takes no fractional orders [V]. The
   `min_abs_weight` re-neutralisation (0.005) is in the sleeve and not in the
   harness.
7. **Flips** are deferred live (the closing leg first; `docs/RUNNER.md`).
   The harness flips in one step.
8. **The decide-time NAV defect**: a Yahoo row dated D can carry D−1's value
   (`results/cef/LIVE_NAV_QUALITY_2026-10-12.md`). It is the same for both
   fills, but a C5 book acts on it a session sooner.
9. **Shortability** is re-read at the morning send, not historically
   (landmine 5).
10. **Reference state**: live holdings, against the stored target here.

## 4. Data

### 4.1 Universe and the two evaluation sets

- **Names**: the spec's 13 (`frozen.universe`, read through
  `scripts/cef/spec.py`). PDO starts in 2021.
- **Panels**: `data/cef/cef_prices.parquet` (close, open; last date
  2026-09-28 today) and `cef_nav.parquet` (last date 2026-09-25 today).
- **Deployed fit sample**: `build_targets()` as the sleeve builds it. A name
  needs a z-score and a 63-session ADV through *t*−1 of at least
  `min_adv_usd` ($3,000,000), and the book trades when at least `min_names`
  (6) are eligible.
- **WIDE**: the identical rule with the ADV floor at 0. A name then needs a
  z-score and a defined ADV.
- **The holdings path in both sets**: `band_gross_capped(T, BAND_WIDTH,
  MAX_GROSS_STRESS)`, the live v7 policy.

### 4.2 The opening price: the declared rule

**Source.** Alpaca SIP `GET /v2/stocks/auctions`, opening array `o`, fetched
by `scripts/data/fetch_alpaca_auction_history.py --side open`. It is a
read-only GET; the cache is gitignored, because this is vendor data and the
repository is public.

**The fill price Oₛ,ᵢ** is the print with **exchange `N`** (NYSE, the primary
for all 13 names) and **condition `O`** ("Market Center Opening Trade").

- `O` is the cross: it updates volume, while `Q` ("Market Center Official
  Open") does not (CTS Pillar spec v2.11b; REFERENCES §12o [V]).
- `Q` is the cross-check, published from late 2020.

**The close Cₛ,ᵢ** is the panel close, the price the deployed harness fills
at. The gain is then exactly the difference between the two harness fills.
R-CLOSE (§11) uses the NYSE closing print instead.

**Defect classes**, each declared before any return is seen. A name-day in
classes D-1 to D-5 is a **no-cross name-day**: its trade is treated as filled
at that day's close, so its gain is 0, the same as the live rule of decision
4. Every such name-day is counted and listed, never silently dropped.

| class | rule | count 2016–22 [V] | halt if |
|---|---|---:|---|
| D-1 | no `N` print at all, or `Q` without `O` (no round-lot cross) | 29 none + 1 Q-only of 21,628 panel name-days; on **material trade name-days 3 of 1,763 (deployed) and 9 of 6,456 (WIDE)** | > 1% of material trade name-days, or > 1% of traded notional, in the decision window |
| D-2 | `O` and `Q` both present and \|O − Q\| > $0.005 | 0 of 5,341 | > 1% of name-days with both |
| D-3 | `O` disagrees with **both** the yfinance open and CRSP `openprc` by > $0.005 **and** lies outside the yfinance day's [low, high] ± $0.005 | 0 | > 0.5% of material trade name-days |
| D-4 | two `O` prints on one name-day | 0 (the script raises) | any, until the fetcher is checked |
| D-5 | a material trade on a name-day with no panel close | 0 (deployed and WIDE) | > 0.1% of material trade name-days |
| — | `O` outside [low, high] with one consolidated open agreeing | 4 name-days | **not** a defect; flagged and used |

**Halting** means stopping before any P&L: no trial is spent, the case goes to
the team lead, and the rule is not edited to pass.

### 4.3 Returns (H15)

- **Rₛ,ᵢ**, the deployed leg: `total_returns(R)` of the harness, i.e. (1 +
  r_px)·k − 1 + D/Pₛ₋₁. This is the series every deployed baseline uses.
- **The session return** rˢₛ,ᵢ = Cₛ,ᵢ / Oₛ,ᵢ − 1.
  - **No distribution.** On an ex-date the open is already ex, and the
    distribution belongs to whoever held at the previous close; a trade filled
    at either auction that day receives none, so both fills are treated alike.
  - **No split factor.** Both prints are post-split.
- **The overnight return**, used only in diagnostics: 1 + rᴼₛ,ᵢ = (Oₛ,ᵢ·kₛ,ᵢ +
  Dₛ,ᵢ) / Cₛ₋₁,ᵢ.
- **A name-day with a material trade, a close, and no usable open** is a
  no-cross name-day (§4.2).
- **A trade name-day with no panel close** is class D-5 (§4.2). It is not
  silently zeroed: it is counted, listed and halts above its threshold.
  - Below the threshold its gain is 0. The deployed leg already treats that
    name-day the same way, because `build_targets` zero-fills a missing
    return. That is an existing harness convention, which C5 does not
    change.

### 4.4 Data gates (zero trials; any failure halts before a return is computed)

| gate | what | done when |
|---|---|---|
| **DG-C5-1** | the 2016–22 opening prints, re-fetched at run time; the classes of §4.2 re-counted | counts printed beside today's; no halt rule fires |
| **DG-C5-2** | **the spec pin**: sha256 of `ops/specs/cef_discount.frozen.json` equals **`c05035e55eaa89172f65d38a3485cb1c68123217177343b38576edf56583c02e`** (main @ 9d7d317, 2026-10-13). Values read through `spec.py`: `cef_discount.v7.20260928`, band_width 0.048, max_gross_stress 1.80, z_window 252, min_adv_usd 3,000,000, min_names 6, vol_target_annual 0.06, 13 names, capital $100,000, order_type MOC; harness constants MIN_PERIODS 120, VOL_LOOKBACK 63, SAMPLE_START 2005-01-03 | the trial script asserts the hash. **A changed spec halts the trial**, which returns to the team lead re-pinned |
| **DG-C5-3** | **The harness extension** (§5): `session_returns` and `open_fill_gain` added to `scripts/cef/band_frontier.py` beside `evaluate()`, which is not edited. Tests: (i) a zero session return reproduces `evaluate()` exactly; (ii) a unit trade decided on row *t* appears only on row *t*+1, times that row's session return; (iii) perturbing Oₛ₊₁ or Cₛ₋₁ leaves rˢₛ unchanged; (iv) no-cross name-days give 0 and are returned as a mask. Each test must fail against a wrong version (shift(2) on the trade, shift(0), the overnight return) | tests pass, each shown to fail against its wrong version |
| **DG-C5-4** | **WIDE**: a default-off `min_adv` argument on `build_targets`, the same flag as C4's DG-C4-5 (whichever lands first serves both) | sha256 of `pickle.dumps(build_targets())` unchanged with the argument absent |
| **DG-C5-5** | **The quote sample** for the surcharge rows (§6): `scripts/cef/exec_capacity_open_cross.py fetch` (2016–22 every 14th session; read-only) | the cache is rebuilt and its report reproduces the EXEC note's §6 table to the printed precision |
| **DG-C5-6** | **The holdout opening prints**, 2023-01-03 → 2026-09-30. The fetcher gains a `--holdout` flag that **refuses unless the fit verdict is committed**, so the prices cannot be read before then | run only at stage 8 (§13); §4.2's rule applied unchanged |
| **DG-C5-7** | **The panels reach the fixed holdout end**: prices through 2026-09-30, NAVs through 2026-09-29 | read at stage 8. If they do not reach it, the holdout waits; the end date is not moved |
| **DG-C5-8** | Intraday factor returns for R-D4 (§10): CRSP `openprc` / `prc` for HYG, IEF, MUB and BKLN, which `scripts/data/stage_crsp_w4.py` already stages | they cover the decision window |

### 4.5 The repair criteria (declared now; none applies after a return is seen)

- **Nothing in `data/` is repaired by this trial.** The live sleeve decides on
  `data/` (landmine 9), and the deployed and C5 legs share it.
- **The only alteration the trial script may make** is the no-cross
  reclassification of §4.2, by its stated classes, counted and listed.
- **Any other defect found at Stage 0** halts the trial before any P&L and
  goes to the team lead: for example a print at an impossible price, a
  session return over 50% in magnitude (the harness's own price filter), or a
  close that disagrees with both CRSP `prc` and the NYSE closing print.
  - A vendor defect is fixed in its fetcher with a dated note, and Stage 0
    re-runs. No trial is spent.
  - A rule is never edited to make a count pass.

## 5. The timing convention, and the visible extension of `evaluate()`

**The canonical convention (H1), unchanged:**

```python
pnl_D = evaluate(H, R)["pnl"]          # row s = sum_i H[s-2,i] * R[s,i]
```

H at row *t* is decided in the evening of *t* on *t*'s close and NAV. The
deployed book fills it at the close of *t*+1 and earns *t*+2.

**C5, on the same H:**

```python
RS, no_cross = session_returns(O, C)                 # row s: C[s]/O[s] - 1; 0 and flagged where no cross (§4.2)
G     = open_fill_gain(H, RS)                        # row s: sum_i (H[s-1,i] - H[s-2,i]) * RS[s,i]
                                                     #      = (H.diff().shift(1) * RS).sum(axis=1)
pnl_C5 = pnl_D + G
```

**Reading it.**

- The trade decided in the evening of *s*−1 (ΔHₛ₋₁ = Hₛ₋₁ − Hₛ₋₂) fills at
  Oₛ instead of Cₛ.
- It therefore also earns Cₛ / Oₛ − 1, which the deployed fill cannot.
- From Cₛ on, both books hold Hₛ₋₁.
- **Overnight** (Cₛ₋₁ → Oₛ), both books hold Hₛ₋₂. No decision ever earns an
  overnight gap that began before it was made.
- **Equivalence.** `pnl_C5` = Hₛ₋₂·rᴼₛ + Hₛ₋₁·rˢₛ + Hₛ₋₂·rᴼₛ·rˢₛ. That is the
  candidates note's two-segment form, plus the held book's overnight move
  compounded through the session. On an ex-date it also differs by the
  distribution's own session return, (D/Cₛ₋₁)·rˢₛ, because the harness's
  R books the cash at the close.
  - The additive form is declared because it makes the identity exact: G = 0
    on every session the band does not trade, so C5 equals the deployed book
    there to the last bit (DG-C5-3 (i)).

**Why this is not `shift(1)`.**

- `shift(1)` earned Cₛ₋₁ → Cₛ on Hₛ₋₁. That is a fill at the close of the
  decision day, before its NAV existed.
- C5's extra leg starts at Oₛ. *s*−1's NAV is public by then, published the
  evening before.
- **The alignment is asserted at runtime**, and it is pinned by DG-C5-3 (ii)
  and (iii).

**H2 is met by construction.**

- Both books are the **same H**, so `evaluate(H, R)["turn"]` is their common
  turnover: the gap is 0%, against the 5% tolerance.
- This is a comparison of two fills of one holdings path, not of two
  policies. No width is matched and nothing is chosen.
- Both turnovers are printed anyway, from the one H.

**The statistics window** (the XASSET review's lesson):

- Every statistic is computed on the series sliced to the window, never from
  `evaluate()["gross_sr"]`, whose index begins with the flat sessions before
  the first position.
- **Decision window: s = 2016-01-04 … 2022-12-30.** That is 1,762 sessions,
  each with an official print.
- Both sets' first decisions precede it, deployed 2013-06-21 and WIDE
  2005-01-03 [V]. So the window starts later than first decision + 2 sessions,
  and no flat lead-in enters.
- **R-PRE16** (§11) runs from the first decision + 2 sessions to 2015-12-31.
- **Sessions with no trade are in the gain series as zeros**: the strategy
  earns nothing those days, and dropping them would overstate its Sharpe.

## 6. Costs and borrow

- **Gross is the headline** (paper is scored gross: D19/D20).
- **Net beside it** at 5, 15 and 30bp per unit of one-way turnover
  (`band_frontier._stats`), for the deployed and the C5 book, labelled, with
  whether either flips sign.
  - **Because turnover is identical, the grid moves both books by the same
    amount.** The C5-minus-deployed difference is the same at every grid
    point, so the grid cannot flip the comparison; it can only flip a book.
    Both facts are printed.
- **The measured open-versus-close cost difference, as its own labelled row.**
  - s_open is re-measured at run time (H14) by
    `scripts/cef/exec_capacity_open_cross.py report` on the 2016–22 quote
    sample. It is the mean of (|open print − mid| − |close print − mid|) at the
    matched horizons, the larger of h1 and h5. The EXEC note read +6.0 / +6.5bp
    on 2026-10-13 [S]; that is orientation only, not an input.
  - The row is C5 net at (5 + s_open), (15 + s_open) and (30 + s_open).
  - **It is a stress, and it double counts.** The print's distance from mid is
    already inside the print-priced gross (EXEC note §6). What it stands in
    for is our own impact on the print, which no backtest sees.
  - A second row repeats it with **the signed open dislocation of C5's own
    trades**, on the same sample: sign(ΔH) · (Oₛ − mid₀₉:₃₁) / mid, minus the
    same for the close fill of the same trades (Cₛ against mid₁₅:₅₉). The EXEC
    note deferred this statistic to the trial (§8: "if C5 systematically joined
    the imbalance side, the matched-horizon upper bound would become its
    cost").
- **Borrow is charged separately and labelled (H4)**, through
  `borrow_charge(H, fee)` on `H.shift(2)`.
  - **It is identical for both fills**: the overnight book is the same, and a
    short opened at the open or at the close of one trade date carries the same
    overnight. Whether either broker charges an intraday-opened short
    differently is [U] and immaterial at one session.
  - The basis is Alpaca's published live terms (easy-to-borrow pays no fee;
    REFERENCES §12l [V]). That is a counterfactual applied to history, and it
    says so at the top of the table. The IBKR fee panel row (2021-09 →
    2022-12) is beside it [S].
  - No C-trial is read net of borrow as a verdict until plan 0.5 has measured
    borrow (candidates note, phase 2 item 5).

## 7. Windows, eras and the holdout

- **Decision window**: 2016-01-04 → 2022-12-30 (decision 3).
- **Eras (H5)**:
  - 2016–19, labelled "the 2015–19 era from the print's start";
  - 2020–22;
  - each with turnover sd/mean, and the five H5 eras in R-PRE16.
- **Declared strata** (the candidates note asks every CEF prereg for the
  first):
  - December and Feb–Nov;
  - ex-date name-days and the rest;
  - name-days whose decision-day NAV moved, and those whose NAV repeated.
- **Holdout: 2023-01-03 → 2026-09-30, fixed now.** That is 937 sessions in
  today's panel to 2026-09-28, plus 2 weekdays, so 939 [V].
  - It is opened **once**, after the fit verdict is committed, whatever that
    verdict.
  - Its opening prints are fetched only then (DG-C5-6).
  - The panel must reach the end date (DG-C5-7).
  - H is built once, from the first decision to 2026-09-30, and the holdout
    rows are sliced from that one continuous series. H through 2022 is the
    same either way, because nothing in it looks forward.
- **Holdout rule.** The holdout mean of G has the same sign as the decision
  window's. Otherwise **KILL (D3)**.
  - Beside it: the holdout Sharpe of G, its HAC t, a stationary-bootstrap 95%
    CI, and the probability of the observed sign under the fit Sharpe.
  - False-kill rate at a true Sharpe of 0.5 / 1.0 / 1.5: 0.17 / 0.03 / 0.002
    [arithmetic, `c5_feasibility.py` §4].
  - **It can kill; it cannot rescue.**
  - The two sets still differ in the holdout: **39.4% of name-days with a
    z-score are below the ADV floor** (2023-01-03 → 2026-09-25 [V]).

## 8. Inference

| quantity | method, declared |
|---|---|
| **headline** | annualised Sharpe of the WIDE gain G over the decision window: mean / sd(ddof = 1) × √252. Zeros included (§5) |
| **HAC t** | Newey–West (Bartlett), **L = 21**, `scripts/cef/w4_artifacts.py::nw_t(G, lags=21)`. Beside it: L = 5 and the Newey–West (1994) automatic lag |
| **bootstrap** | stationary bootstrap (Politis–Romano), **mean block 21 sessions, 10,000 resamples, seed 20261013**: 95% CIs for the mean (bp per year and per unit of turnover) and the Sharpe. The helper is the one C4 declares beside `nw_t` (whichever lands first serves both), with a test. A mean block of 63 and `w4_artifacts.block_boot_t` are second methods |
| **the bar** | `validate._dsr(obs, T, sk, ku, N)` on G over the decision window. obs is the headline; T = 1,762; **sk = `pd.Series(G).skew()` and ku = `pd.Series(G).kurt() + 3.0`, exactly as `scripts/cef/validate.py:342` computes them**. **PASS > 0.95.** N is the CEF counter when the result is committed. It already includes C5, which moved it at approval, so it is ≥ 51 |
| beside it, never deciding | SR·√years against √(2 ln N); `_dsr` of the C5 book's own gross series (decision 2's alternative); the gain per unit of turnover in bp (mean G × 252 / turn); the paired t of C5 − deployed (the same number as G's t, printed as a check) |

## 9. Controls and placebos (H12)

Every one is run through the same extension, on the same H, with the same
returns.

| stage | control | rule | what it catches |
|---|---|---|---|
| **2a** | **The stale-open stratum.** G restricted to name-days whose `O` print moved more than $0.005 off Cₛ₋₁ (85.5% of name-days [V]) | **KILL D1** if its mean is ≤ 0 | An open sitting at the previous close books the whole of day *s* as "session". The gain would then fade close *s*−1's bounce rather than catch the NAV. That is the stale-price death in a new place |
| **2b** | **Lagged-signal placebo: the open fill, a decision a day older.** G^lag = Σ (Hₛ₋₂ − Hₛ₋₃) · rˢₛ. This is the open fill applied to the skip-a-day book (`H.shift(1)`) | **KILL D1** if mean G^lag ≥ mean G. The paired difference and its HAC t are printed | If the gain does not need the decision to be fresh, it is a property of the opening print (bounce, a systematic open-to-close drift, a stale open), not of *t*'s NAV arriving. **The false-kill risk is real and unknown.** The full-sample IC of the t+2 session (−0.031) is three-quarters of the t+1 session's (−0.041) [S], so the signal decays slowly and the placebo will not be near zero |
| **2c** | **Shuffled-trade placebo.** The rows of the trade matrix ΔH are permuted in contiguous 21-session blocks against fixed rˢ. Trade sizes are kept and timing is destroyed. 1,000 draws, seed 20261013 | **KILL D1** if mean G ≤ the placebo's 95th percentile | the gain from trading at the open at all, whatever the trade |
| **5** | **The deployed set's gain** and **WIDE's gain on at-or-above-floor trades** (decision 1) | **KILL** if either mean is ≤ 0 | a WIDE result carried by trades the spec would not have made |

**Reported, never deciding:**

- **Where the return lands (the open→close split).**
  - The deployed book's P&L split exactly into Hₛ₋₂·rᴼₛ (overnight), Hₛ₋₂·rˢₛ
    (session) and the compounding term.
  - C5's split the same way.
  - G itself.
  - **The overnight the decision cannot reach**: Σ ΔHₛ₋₁·rᴼₛ. It is labelled
    **not transactable**, and is a diagnostic only. The mechanism expects it
    small. Its size against G says how much of day *s* the open fill leaves
    behind (the auction-print overnight IC was −0.027 in 2016–22 [S]).
- **The decay profile**: Σ (Hₛ₋ₖ − Hₛ₋ₖ₋₁)·rˢₛ for k = 1 … 5. Here k = 1 is G
  and k = 2 is the placebo.
- **The dislocation split** on the quote sample.
  - rˢ splits into print → mid₀₉:₃₅ and mid₀₉:₃₅ → close.
  - The mechanism puts the gain in the drift part.
  - If more than half of the sample's gain sits in the print → mid part, the
    verdict carries the label **capacity-bound**: it is a liquidity premium at
    the open that shrinks as we grow.
- **The NAV-freshness split**: G on name-days whose NAVₛ₋₁ differs from NAVₛ₋₂,
  against those whose NAV repeated. The mechanism expects more where the NAV
  moved.
- The correlation of G with the deployed book's daily P&L.

## 10. Regressions

OLS with statsmodels HAC covariance (maxlags 21). G is a self-financing
intraday return, so no risk-free rate is subtracted. Alpha is in bp/yr.

| regression | role | specification |
|---|---|---|
| **R-D4** | **decision** | G on the **session** returns (open → close, CRSP `openprc` → `prc`; DG-C5-8) of HYG, IEF, MUB and BKLN, and the equal-weight session return of the 13 names. Each is also lagged one session close-to-close (Dimson; the betas are summed). **Pass: alpha t ≥ 3.0 and every summed \|β\| ≤ 0.10.** G is at the book's own scale (the spec's vol scalar), so no resizing is needed. The alpha-t bar is below the `_dsr` bar's implied t (about 4.45 over 7 years), so it binds only if the factors explain G |
| R-0 | reported | the contemporaneous-only version |
| R-BOOK | reported | G on the deployed book's own daily P&L: does the open add more of the same bet, or a different one? |

**A gap, stated:** no intraday equity-market factor. SPY is not in the CRSP
stage, and the CEF equal-weight session return stands in for it.

## 11. Robustness: reported, never chosen from, and none of it rescues a failed headline

- **R-DEP**: the whole table on the deployed set (decision 1's alternative A).
- **R-PRE16**: the decision rule on CRSP `openprc` from the first decision + 2
  sessions to 2015-12-31, and the whole fit spliced. It is labelled a
  consolidated first price, not an auction print.
- **R-YF**: the yfinance open in place of the print (2016–22).
- **R-CLOSE**: the NYSE closing print in place of the panel close, for both
  books, on the closing-print rule of `docs/RUNNER.md` (`M` on `N`; the
  no-cross trap of the EXEC note §1 applies).
- **R-STALE0**: the 14.5% stale-open name-days treated as no-cross (gain 0).
- **R-LATE**: name-days whose `O` printed after 09:35 ET treated as no-cross.
- Eras, the strata of §7, leave-one-name-out (min, median, max), and the
  first half of the window against the second.
- Bootstrap mean block 63, and the Newey–West automatic lag.
- **Capacity**: the opening-cross participation of C5's trades at $100k, $1m
  and $10m, from the sized prints (the EXEC note's method), beside the closing
  cross's.

## 12. Feasibility, measured today (zero trials)

`python3 scripts/cef/c5_feasibility.py` (about 8 s), run 2026-10-13 [V].
Caches were re-fetched in this worktree the same day:
`fetch_alpaca_auction_history.py --side open` and `stage_crsp_w4.py`.
Tables: `results/cef/c5/c5_{coverage,trades,power}_2026-10-13.csv`.

### 12.1 Opening-print coverage, 2016–22

| name | AWF | BIT | DSL | HYT | JFR | MHD | MQY | PCN | PDI | PDO | PFN | PHK | PTY |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `O` share of panel name-days | 100% | 99.94% | 100% | 100% | 99.94% | **99.04%** | 99.77% | 99.83% | 99.94% | 100% (from 2021) | 99.94% | 99.94% | 99.94% |

| year | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 |
|---|---|---|---|---|---|---|---|
| `O` share | 99.87% | 99.93% | 99.60% | 99.90% | 99.87% | 99.97% | 99.88% |
| stale-open share (O within $0.005 of Cₛ₋₁) | 12.5% | 17.2% | 16.2% | 18.3% | 11.0% | 14.8% | 11.6% |
| O = yfinance open (±$0.005) | 97.6% | 97.6% | 98.4% | 98.4% | 98.0% | 98.5% | 99.1% |
| O = CRSP `openprc` (±$0.005) | 97.7% | 97.8% | 98.4% | 99.1% | 98.1% | 98.5% | 99.1% |

- **Overall** 21,598 of 21,628 name-days (99.86%).
- **The `O` print time**: median 09:30:00 ET; after 09:35 on 70 name-days.
- **Reproductions** of the candidates note, from the same sources: `O` = `Q`
  on all 5,341 shared name-days; O = the yfinance open on 98.2%; the stale
  share 14.5%.
- **Before 2016**, CRSP `openprc` covers 100% of panel name-days in every
  year 2005–15, and equals the yfinance open on 99.56–100% of them.

### 12.2 The two evaluation sets (holdings only; no P&L)

A trade decided at *s*−1 goes to the open of *s*. "Material" means at least
0.5% of capital.

| | deployed (ADV floor on) | WIDE (ADV floor 0) |
|---|---:|---:|
| first position | 2013-06-21 | 2005-01-03 |
| sessions active (≥ 6 eligible), 2016–22 | 40.2% | 100% |
| trade sessions, any / material | 782 / **606** | 1,658 / **1,571** |
| material trade name-days | **1,763** | **6,456** |
| … of which multi / hy / loan / muni | 1,142 / 423 / 153 / **45** | 3,532 / 1,167 / 614 / **1,143** |
| … with an `O` print / no cross | 1,760 / 3 | 6,447 / 9 |
| share of traded notional with an `O` print | 99.69% | 99.85% |
| turnover per year (`evaluate`'s formula, H only) | 13.46 | 32.10 |
| mean held gross / mean traded gross per material session | 1.24 / 0.154 | 1.37 / 0.140 |
| material trade name-days in names below the ADV floor on the decision date | 20 (exits: a name leaving eligibility is traded to 0) | **3,483 (54%)** |
| pre-2016 window (from first position + 2): sessions / material trade sessions | 636 / 283 | 2,767 / 2,317 |

- The deployed turnover reproduces W4's 13.5 per year (2013-06 → 2022 [S]).
- By year, the deployed set's material trade sessions run from 43 (2016) to
  141 (2022); WIDE's run from 198 to 241.

### 12.3 The bar and its power

Arithmetic on `validate._dsr` (skew 0, kurtosis 3, SE = 1/√years), reusing
`scripts/xasset/slate_feasibility.py::required_sharpe` and `power`.

| window | years | N | √(2 ln N) | **Sharpe needed** | for 80% power | P(pass) at true SR 1.0 | 1.5 | 2.0 | 2.5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **decision 2016–22** | 6.99 | **51** | 2.804 | **1.684** | 2.003 | 0.035 | 0.313 | 0.798 | 0.984 |
| decision 2016–22 | 6.99 | 52 | 2.811 | 1.687 | 2.005 | 0.035 | 0.310 | 0.796 | 0.984 |
| decision 2016–22 | 6.99 | 58 | 2.850 | 1.702 | 2.020 | 0.032 | 0.297 | 0.785 | 0.983 |
| deployed long (R-PRE16 spliced) | 9.52 | 51 | 2.804 | 1.443 | 1.716 | 0.086 | 0.569 | 0.957 | 0.999 |
| WIDE long (R-PRE16 spliced) | 17.97 | 51 | 2.804 | 1.050 | 1.248 | 0.416 | 0.972 | 1.000 | 1.000 |

**What the prior implies.**

- The candidates note's prior is +0.1 to +0.3 gross SR on the book's level
  [U].
- The gain's mean is then δ × σ_book. On W4's deployed vol (6.50%/yr) and
  turnover (13.5/yr) [S], that is **4.8–14.4bp per unit of one-way
  turnover**.
- The open's measured surcharge upper bound in 2016–22 is 6.0–6.5bp [S]. The
  prior gain and the stress are the same size, which is why §6's row matters.

**Power on the gain** depends on f = sd(G) / sd(book), and f is **not
measured**: it is the trial's own statistic. The script prints P(pass) at
N = 51 over 2016–22:

| prior δ \ f | 0.1 | 0.2 | 0.3 | 0.5 |
|---|---:|---:|---:|---:|
| 0.1 | 0.035 | 0.001 | 0.000 | 0.000 |
| 0.2 | 0.798 | 0.035 | 0.004 | 0.000 |
| 0.3 | 1.000 | 0.313 | 0.035 | 0.002 |

- **Measured, and what it suggests.** The day's trade is a small part of the
  book. A material trade session moves 0.14–0.15 of gross against a held
  1.24–1.37 [V], and G is non-zero only on trade sessions. That points to a
  small f, but it is not a measurement of f: diversification within the trade
  and session volatility decide it.
- **Power on the level (decision 2's alternative).** If C5's level Sharpe is
  0.96 + δ [S], P(pass) is **0.049 / 0.083 / 0.131** over 2016–22, and 0.12 /
  0.19 / 0.29 over the deployed long window.

**What a result means, stated before it exists:**

- a **pass** is strong evidence;
- a **D1 kill at stage 1** (G's t < 1.96) means the gain is not detectable in
  seven years;
- a **NEITHER** is the likeliest outcome if f is a fifth or more.

## 13. The order of evaluation (the exact kill tests)

| stage | statistic | rule | if it fails |
|---|---|---|---|
| 0 | DG-C5-1…5, DG-C5-8; the §4.2 classes and halts; the spec hash; turnover equal for both fills. **No return is combined into a P&L at this stage** (the XASSET review's finding 1). It ends with one commit of the SHA-256 of every input (both opening-print caches, the CRSP cache, `cef_prices`, `cef_nav`, `cef_distributions`, `cef_splits`, the spec) and the class counts and flag list; every later stage re-verifies those hashes before it reads an input, and a mismatch halts | a gate or halt rule fires | **no trial spent**: fixed, or referred to the team lead. A gate that cannot clear leaves C5 **UNRUN** |
| — | **the trial is spent from here** | — | — |
| 1 | G (WIDE): mean > 0 and NW t (L = 21) | t ≥ 1.96 | **KILL D1** |
| 2 | 2a stale-open stratum; 2b lagged-signal placebo; 2c shuffled-trade placebo (§9) | §9 | **KILL D1** (artefact) |
| 3 | R-D4 (§10) | alpha t ≥ 3.0 and every \|β\| ≤ 0.10 | **KILL D4** |
| 4 | the bar: `_dsr` on G at N | > 0.95 | **NEITHER**: real at most, below the bar. No change to the book, no re-test on these data. The team lead rules WATCH or D5 |
| 5 | the deployed set's G; WIDE's at-or-above-floor G (§9 stage 5) | both means > 0 | **KILL** (the evaluation-set guard) |
| 6 | the cost rows (§6): gain per unit of turnover against s_open and against the signed dislocation | — | **labelled, not killed**: below s_open gives **D2-open**, no real-money C5 until the live cost falsifier (§15c) has read; below the signed figure, the same; the dislocation split's **capacity-bound** label (§9) |
| 7 | the fit verdict is committed | — | — |
| 8 | DG-C5-6 and DG-C5-7; the holdout sign of G (§7) | same sign as the fit | **KILL D3** |

**Every statistic of every stage is computed and reported, whatever the
verdict.** The verdict is the first failing rule in this order. A PASS needs
stages 1–5 and 8. These kill rules are pre-committed and are not softened
later.

## 14. What we expect [U]

- **G positive**, at roughly 3–15bp per unit of turnover. That is the prior's
  arithmetic (§12.3), widened downward because the auction-print overnight IC
  (−0.027 [S]) says the open already prices part of day t+1.
- **The lagged placebo** (2b) about half to three-quarters of G, by the
  signal's measured decay.
- **The stale-open stratum** holds most of G. On the candidates note's
  moved-open sample the session IC was −0.047 [S].
- **Most likely verdict:** NEITHER or a stage-1 kill if f ≥ 0.2; PASS
  possible if f is near 0.1. **D2-open** is a real risk even on a pass,
  because the prior gain and the measured surcharge are the same size.

Being wrong here is fine, and is the point.

## 15. Paper against live, and what would falsify C5 once it trades (H11)

**How a C5 book is scored on paper.** Paper runs no auction on either side
(landmine 1), so paper's own fills say nothing about the open cross. Every
line below uses **broker-confirmed quantities**. None is a modelled session.

| line | what | status |
|---|---|---|
| 1 official | Alpaca's reported fills | as today |
| 2 auction-marked | each open-filled quantity marked from the fill day's NYSE `O` print; the held book at the official close | the C5 analogue of today's line 2 |
| 3 distributions | as today (`dist_score.py`) | unchanged |
| **4 the open's gain** | Σ qᵢ · (closing print − `O` print) / equity, on the same confirmed quantities: line 2 minus the same trades marked at that day's close | **new**: the live statistic for (b) |

**Falsifiers**, stated now, for a C5 book that passed and was released. No
threshold that is a measured quantity is written as a number (H14); each is
re-measured on its read date. The fixed numbers below are rules, not
measurements.

- **(a) Fidelity, daily.** The decided open set must equal the trial script's
  ΔH on the same panel, to whole shares. Any other difference halts C5 as a
  bug, not a result.
- **(b) Gain, at 120 sessions with open fills (paper or live).** Return to
  `cls` if line 4's cumulative gain per unit of traded notional falls below
  the 5th percentile of the trial's own 120-trade-session cumulative gains
  per unit of turnover. That percentile comes from a stationary bootstrap
  (mean block 21) on the fit and holdout G.
- **(c) Cost, at 60 sessions with live-money open fills.** This is the one
  thing paper cannot test.
  - The statistic: the realised signed cost of the `opg` fills,
    sign(q)·(fill − mid₀₉:₃₁)/mid, minus the same quantities' signed distance
    at the close, sign(q)·(closing print − mid₁₅:₅₉)/mid.
  - Return to `cls` if its mean exceeds the trial's gain per unit of
    turnover.
  - On paper this line is UNMEASURED, and says so.
- **(d) Fill, at any 20 sessions.** An `opg` unfilled or open-miss share above
  5% of orders halts and refers. The residual went to the close (decision 4),
  so nothing is lost, but the book is no longer doing what was tested.
- **(e) The book's kill rule** (spec `kill_rule`, 60 live sessions) stands
  unchanged.
- **Reported, no rule:** participation in the opening cross by name; how
  often the open was missed and why.

## 16. Draft amendment to `CLAUDE.md` order-path rule 3: NOT APPLIED

**Status.** This is a draft for the team lead.

- It is considered only if C5 passes (decision 7).
- It takes effect only in a commit carrying the team lead's approval, together
  with the spec change (§1).
- It also needs an `opg` acceptance read on paper (decision 6) and the
  runner's send path built to it, with tests that fail against today's
  behaviour.
- `CLAUDE.md` is not edited here.

**Today's text** (`CLAUDE.md`, "Hard rules — the order path", rule 3):

> 3. **Order type stays MOC** (Alpaca `time_in_force=cls`). Overnight market
> orders realised 100.5bp against a 32.6bp breakeven on 2026-07-31. Alpaca
> rejects `cls` entries from 15:50 ET; NYSE cancels no MOC after 15:50. **One
> recorded exception (team lead, 2026-09-29), the paper account only:** paper
> runs no closing auction and under-fills `cls` (11 of 13 expired on
> 2026-09-29), so the book's json sets `execution.mode = late_market`: the plan
> is decided in the evening and sent as market `day` orders 8 to 2 minutes
> before the close (`docs/RUNNER.md` "Paper execution"). Delete that block to
> return to `cls`. It never applies to a live-money account.

**Proposed text:**

> 3. **Orders go to an auction, never to the continuous market: MOC (Alpaca
> `time_in_force=cls`), or MOO (`type=market`, `time_in_force=opg`) for a book
> whose frozen spec sets `order_type: "MOO"`** (trial C5, team lead
> <date>; `results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md`). Overnight market
> orders realised 100.5bp against a 32.6bp breakeven on 2026-07-31, and an
> `opg` order cannot fill outside the opening cross. **Close:** Alpaca rejects
> `cls` entries from 15:50 ET; NYSE cancels no MOC after 15:50. **Open:** the
> plan is decided in the evening on *t*'s NAV and saved; the saved plan is sent,
> never re-decided, between 06:00 and 09:25 ET on *t*+1 (Alpaca rejects `opg`
> from 09:28). Nothing is sent for the open before 06:00, so an overnight
> `DRY_RUN=1` or halt still wins (rule 4); neither recalls an `opg` order
> already at the broker, and cancelling one is an order action under rule 1. A
> plan not sent by 09:25, and the unfilled part of any `opg` order, go to that
> day's close by the account's closing path, recorded as an open miss, never
> to the continuous market. **Rule 2 binds each auction separately:** a marker
> for the auction is written before its first order, and each send refuses if
> its marker exists, if the broker shows an order already sent for that
> auction, or if the account holds any open order. **One recorded exception
> (team lead, 2026-09-29), the paper account only:** paper runs no closing
> auction and under-fills `cls` (11 of 13 expired on 2026-09-29), so the
> book's json sets `execution.mode = late_market`: the plan is decided in the
> evening and sent as market `day` orders 8 to 2 minutes before the close
> (`docs/RUNNER.md` "Paper execution"). Delete that block to return to `cls`.
> It never applies to a live-money account, and it does not extend to the
> open: a paper substitute for `opg` would be a separate ruling.

**Why each clause is there.**

| clause | reason |
|---|---|
| "never to the continuous market" | the 2026-07-31 incident; it keeps the dead relative dead |
| `order_type: "MOO"` in the spec, not a runtime flag | the frozen spec is the only authority on a live parameter (code rules) |
| decided in the evening, sent in the morning from the saved plan | it is the `late_market` pattern already built and reviewed (`docs/RUNNER.md`): what was decided, and approved before `AUTO_ARMED`, is what goes; the plan's sha must still match and positions must still equal its "current" |
| 06:00 to 09:25 ET | the 09:28 cut-off with three minutes of margin, as 15:45 is to 15:50. The send-budget gate (`n_orders × 3 s + 42 s`) applies before 09:25 as it does before 15:58 |
| not before 06:00 | rule 4 ("`DRY_RUN=1` always wins") holds only until an order is at the broker; a queued `opg` would survive an overnight halt (decision 5) |
| the residual to the close | it keeps the live holdings path equal to the tested H (decision 4). Alpaca cancels an unfilled `opg` order after the open (Alpaca "Placing Orders", as quoted in the EXEC note §7 [S]; not yet a row in REFERENCES §12o, a gap) |
| a marker per auction | today's gate 6 refuses on any order today with the prefix `cef-<YYYYMMDD>-`. A morning `opg` set would then block that day's residual `cls` set, so the marker and the `client_order_id` must name the auction. The STARTED-before-first-order and refuse-on-open-order protections stay, per auction |
| the paper exception kept separate | `late_market` answers paper's broken close. Paper's handling of `opg` is unknown, and no exception is granted for it in advance |

**What else would change with it (not done here):**

- `docs/RUNNER.md`: the morning send slot, the open-set marker, the
  `client_order_id` scheme, gate 4's `opg` window and gate 6 per auction;
- `quantt/session/`: the send path, with tests that fail against today's;
- `verify`: line 4 of §15 and the `O`-print read;
- `docs/SYSTEM.md` §5: the decision record.

## 17. Trial accounting

- **CEF today: 50 trials, bar √(2 ln 50) = 2.797** (orient TRIALS,
  2026-10-13 [V]).
- **On approval:** 50 → 51, or → 52 if C4 is approved first, in the commit
  that records the team lead's approval (decision 8), not in this commit.
  **`docs/RESEARCH_STATE.md` changed in this commit: no.**
- No other counter moves. The 27-name set is not consumed. The 2023-01-01
  time holdout stays sealed until C5's fit verdict is committed, and its
  opening prints are not fetched before then.
- **Zero-trial script:** `scripts/cef/c5_feasibility.py`, with tests in
  `scripts/cef/tests/test_c5_feasibility.py`.
- **Trial script (after approval):** `scripts/cef/c5_open_auction.py`.
  - It imports `build_targets`, `band_gross_capped`, `evaluate`, `fit_only`,
    `_stats`, `borrow_charge`, and the new `session_returns` and
    `open_fill_gain` from `scripts/cef/band_frontier.py`.
  - It imports `_dsr` from `scripts/cef/validate.py` and `nw_t` from
    `scripts/cef/w4_artifacts.py`.
  - **There is no new backtester.**
