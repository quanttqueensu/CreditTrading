# W8 — The short leg: what it costs to hold, what can be borrowed, what gets recalled

**Reads first:** `00_BRIEF.md` §3 (how these instruments trade), §5 (harness),
§7 (standing decisions).
**Lever:** TC. Borrow scales with *holdings*, not turnover, so trading less
cannot reduce it — only shorting different names can.
**Trials:** 2 at most (Part B the availability cap; Part C the borrow-aware
score), each pre-registered, each on the **CEF** counter. Parts A, D and E are
measurement, 0 trials.
**Prerequisites:** W4 (the surviving IC — Part C's score is in return units and
uses it). **W2's question is answered (2026-09-10): the API serves daily
FEE_RATE history to 2021-09-13** — `data/cef/cef_borrow_history.parquet`,
`scripts/cef/fetch_borrow_history.py`; REBATE_RATE times out; availability
(tick 236) needs a market-data session that is not "competing". The public
file is gone (404), and `fetch_borrow_rates.py` now takes the fee from the API.
**Part A must open with the measured 2021–26 drag by name and group** — the
PIMCO premium funds averaged 13–30%/yr to borrow, PTY peaking at 178% — before
any of Parts B–E uses a fee number.
**Supersedes:** P1.1, P1.2, P6.6, and the server half of P3.5.

---

## Paste from here

You are a quant researcher on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md`, then:

1. `results/cef/BORROW_NOTE_2026-09-06.md` in full — measured fees; three names
   are 70% of the drag (HYT 10.56%, NAD 9.98%, NVG 4.23%); drag 1.22%/yr
   historically ≈ 0.23 Sharpe, **3.62% on today's book** ($13,732/yr, 2.75% of
   capital) because the signal has us short the whole Nuveen muni complex.
2. `docs/PLAN.md` §3.3 in full (including "Availability is a second
   constraint") and §3.4.
3. `scripts/cef/borrow_capacity.py` (the φ = 0.25 rule and the
   capital-at-which-it-binds table), `borrow_impact.py`,
   `fetch_borrow_rates.py`.
   > **⚠ `borrow_impact.py:101` baselines against `band(T, 0.064)`** — the 6.4%
   > width superseded on 2026-09-06. Its published drag comparison is therefore
   > against a policy the book does not run. Read the width from the frozen spec
   > and re-run before quoting any of its numbers.
4. `data/cef/cef_borrow.csv` — `date, ticker, fee_rate_pct, rebate_rate_pct,
   available_shares, api_shortable_shares`. Append-only, one row per name per
   day, starts 2026-09-06.
5. `src/deploy/sleeves/cef_discount.py` — the order of operations (demean →
   normalise → vol scalar → min-weight filter with re-neutralisation → band),
   because both changes below slot into that order in one specific place.
6. `scripts/cef/band_frontier.py`, `covariance_construction.py` (the Grinold
   conversion `alpha_i = σ_i·(−z_i)` and the note that IC "is a common scalar
   and drops out of a gross-normalised book" — **that stops being true the
   moment a dollar cost is subtracted**).

---

## Part A — Get the mechanics right before modelling anything

These are cheap corrections that change every number downstream.

1. **The accrual convention.** IBKR's Borrow Fee Details defines
   `Borrow Fee = (Market Value × Fee Rate) / 360`, where market value is the
   prior-day settlement price **marked up to 102%** and rounded up to the
   nearest dollar. Our harness charges `Σ_i max(−H_it, 0)·fee_i/252` — a
   trading-day accrual on the raw close. The two differ by roughly 365/360 on
   the day count and another 2% on the base, so we are understating the bill by
   about 3.5%. Small, but it is free to be exact: implement the broker's
   convention, state both, and report the difference.
2. **What `available_shares` actually is.** The public file
   (`ftp2.interactivebrokers.com`, `shortstock/usa.txt`, pipe-delimited:
   `SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE`) reports an *indicative*
   count, and TWS tick **236** returns the same exact-shares figure while the
   legacy tick **46** only signals a coarse more/fewer-than-1,000 bucket. Our
   `api_shortable_shares` column should say which tick produced it. Confirm and
   document; if W2 found the API serves `FEE_RATE`/`REBATE_RATE` history, that
   is a dated series and it replaces the CSV as the primary source.
3. **Why CEF borrow is structurally thin, in one paragraph in the note.** The
   share count is fixed at IPO with no creation mechanism, so the lendable pool
   cannot grow with demand. Only fully-paid and excess-margin shares are
   loan-eligible, and only where the holder has opted into a lending programme
   — IBKR's Stock Yield Enhancement Program requires a margin account or a cash
   account with liquid net worth above $25,000. The marginal CEF holder is a
   retired retail income investor in a cash account: **precisely the holder
   whose shares are not in the pool.** That is the structural reason NAD shows
   3,000 lendable shares against our 8,129 short, and it will not improve.
4. **Add short interest as a free cross-check.** FINRA publishes short interest
   twice monthly for all exchange-listed securities, CEFs included, about seven
   business days after the settlement date, free. Stage it into
   `data/cef/cef_short_interest.csv` for the 44 with a source note. Report
   days-to-cover per name. Treat it as a slow, premium-correlated indicator,
   not a recall early-warning: Alexander & Peterson (2017, *Journal of
   Financial Markets*) find CEF short-selling rises with the premium and that
   heavily-shorted funds see the premium decline over the following **five
   days** — which is our horizon, and which means **we are not alone in this
   trade on the short side.** Say so in the note; it is the closest thing to
   evidence that the short leg is competed.

---

## Part B — Cap short weights at what can actually be borrowed (trial 1)

### The mechanism, and why this is capture, not prediction

The signal says short the richest names. Today that is the Nuveen muni complex:
NAD −8,129 shares, NEA −7,319, NVG −4,852, NZF −4,533, MHD −5,862, MQY −2,089.
IBKR's visible lendable pool for NAD is **3,000 shares**; NVG **20,000**. Our
NAD short is already borrowed (the pool excludes shares lent to us), but we
cannot add, and a recall leaves nothing to re-borrow. `borrow_capacity.py`
measured that at $500k, **11.4%** of the desired short book is unbuildable; at
$5m, 27.8%.

Cost and availability bind on different names (HYT is expensive at 10.56% but
plentiful at 2.5m shares; NAD is expensive *and* scarce), yet in this universe
scarce correlates with expensive. So a cap set by *availability* removes mostly
the *expensive* shorts, and the measured result is that the constraint pays for
itself: gross Sharpe 1.20 → 1.16, borrow drag 1.22 → 0.88%/yr, net-of-borrow
0.10 → 0.14 on the calendar. A feasibility constraint that raises expected
return is a rare thing. The alpha is untouched; we are choosing to hold the
part of the ideal book we can actually finance.

### The construction

Let `w⁰_i` be the frictionless target after demeaning and normalising
(Σ`w⁰` = 0, Σ|`w⁰`| = 1), `A_i` the **20-session rolling minimum** of
`available_shares` (a snapshot is not a pool; the minimum is the conservative
reading), `P_i` the sizing close, `N` the sleeve NAV, φ = 0.25.

1. **Cap each short:** `w_i^cap = max(w⁰_i, −φ·A_i·P_i/N)` for `w⁰_i < 0`.
   Longs are never capped; you can always buy.
2. **Rescale the long leg to the surviving short leg** so the book stays
   dollar-neutral: with `S = Σ_{short}|w^cap|` and `L = Σ_{long} w⁰`,
   `w_i^cap = w⁰_i·S/L` for longs. Gross is now `2S ≤ 1`. **Do not
   re-normalise gross back to 1** — the whole point is that the book is smaller
   when it cannot be financed.
3. **Vol scalar** is computed on the capped book exactly as today, so a smaller
   capped book gets a larger scalar up to its cap. State that this partially
   offsets step 2 and report gross before and after.
4. **Min-weight filter and band** apply afterwards, unchanged. The band's
   reference is the capped target, so a name whose pool shrinks is traded back
   to the edge of its *new* capped target.

Spec block `short_cap: {"phi": 0.25, "lookback_sessions": 20, "_note": ...}`;
absent = today's behaviour, byte-identical, proved.

**Failure policy:** a universe name with no borrow row inside the lookback
**raises**, naming the ticker. Do not assume an unlimited pool; do not assume
zero. A name with `available_shares == 0` gets a short cap of zero — a
constraint, not a universe filter; count how often it happens.

### The backtest, honestly labelled

The borrow panel is days old. A backtest over 2005–2026 uses *today's* pools
held constant. That is the counterfactual "if today's availability had held
throughout", which is the right basis for a forward decision and is **not** a
historical test. Put that sentence at the top of every table.

Run for capital ∈ {$500k, $2m, $5m}. Per capital, against the reference band:

| | gross SR | ann % | vol % | turn/yr | hold | net@5 | net@15 | net@30 | borrow %/yr | net@15 − borrow | avg gross | unfillable % |

"Unfillable %" = the share of *uncapped* desired short notional exceeding
`φ·A_i·P_i` on that date, averaged. Turnover-match if the cap moves turnover
more than 5%. Eras 2005–09, 2010–14, 2015–19, 2020–22, 2023–26 plus the
fit/holdout split. The cap should cost nothing in eras when the muni complex
was not the short side — that is the mechanism's own sanity check.

**Decision rule, committed before running.** Adopt if, at $500k, net@15 −
borrow ≥ the reference's and the sign of net@30 is unchanged, across the full
sample and in at least four of five eras, **and** the 2023–2026 holdout row
agrees in sign at matched turnover. If gross Sharpe falls by more than 0.08
(twice the measured 0.04), stop and write down why. **φ is not swept**; 0.25 is
a judgement recorded in BORROW_NOTE, and the only legitimate change to it is a
documented recall event.

---

## Part C — Charge the short leg its holding cost inside the alpha (trial 2)

### The mechanism

Borrow is a **holding** cost, paid per day for as long as the position is on;
trading cost is paid per unit traded. The band cut trading cost by trading
less; it cannot touch borrow, because the same names are held for longer. The
only way to reduce borrow is to short different names, which means the fee must
enter the decision **as a return**, not as a trading cost. Today the score is
symmetric in sign: a rich muni with a 10% fee and a rich PIMCO fund with a 0.6%
fee get identical short weight at identical z.

### The construction

For name *i* on decision date *t*: `s_i = −(z_i − z̄)`; `σ_i` = trailing 252-day
daily price-return volatility ending the day before; `H` = the **measured**
average holding period of the live band policy from
`evaluate(band(T, 0.048), R)["hold"]` (do not assume; expect ~12–16 business
days); `IC_H` = the IC at the horizon nearest `H`, interpolated on √h from
**W4's post-battery term structure, not the pre-battery one**; `f_i` = the
latest borrow fee, annual decimal.

    μ_i^(H) = |IC_H| · σ_i · √H · s_i        (expected trade return over H)
    b_i     = f_i · H/360 · 1.02             (holding cost of a short over H,
                                              broker convention from Part A)
    a_i     = μ_i^(H)                for s_i ≥ 0   (long)
    a_i     = μ_i^(H) + b_i          for s_i < 0   (short: less negative)

Weights are then built from `a_i` exactly as today from `s_i`. Demeaning after
the adjustment keeps the book dollar-neutral; note that this shifts the pivot,
so the adjustment also slightly re-ranks the long side — report that shift.

Worked example at today's numbers, `H` = 14, `IC_H` ≈ 0.115 **on the
pre-battery IC** (recompute with W4's):

| name | σ ann | σ√H | μ at s = −1 | fee | b_i | net at s = −1 | net at s = −2 |
|---|---|---|---|---|---|---|---|
| HYT | 16.3% | 3.8% | −0.44% | 10.56% | 0.59% | **+0.15%** (do not short) | −0.29% |
| NAD | 11.6% | 2.7% | −0.31% | 9.98% | 0.55% | **+0.24%** | −0.07% |
| NEA | 11.5% | 2.7% | −0.31% | 3.06% | 0.17% | −0.14% | −0.45% |
| PTY | 20.7% | 4.9% | −0.56% | 1.09% | 0.06% | −0.50% | −1.06% |

Verify with the real inputs. The point is that at one standard deviation rich,
a 10% borrow makes the short worthless, and the current score cannot see it.

**IC does not drop out.** The subtraction of `b_i` is in return units, so `μ`
must be too. Use the measured `IC_H`, and show the sensitivity at IC × 0.5, 1,
1.5 — **if W4 halved the IC, the cost term bites twice as hard, and that row is
the headline, not a footnote.**

**Do not** charge the distribution here. Once W4's total-return correction
lands, the yield is inside the return the position earns; adding it to the
score double-counts.

**Ordering with the cap:** score (Part C) → cap (Part B) → vol scalar →
min-weight → band. Scoring first means the cap acts on a short leg already
tilted toward cheap borrow, so the cap binds less often. Report how many
name-days the cap binds with and without the score.

**The backtest.** Factor `build_targets()` into `signal(...)` → `weights(...)`
and reuse the former unchanged. Fees: the **actual daily series** from
`cef_borrow_history.parquet` for 2021-09 → 2026, and for 2005 → 2021-08 the
2021–26 mean by name, labelled "assumed"; run the pre-2021 rows at 0.5× / 1× /
2× of that mean. **The decision must not depend on which is true**, and the
2021–26 rows — the only measured ones — get their own line in every table. Report reference vs adjusted, full sample, by era, fit and
holdout, turnover-matched:

| | gross SR | turn/yr | net@5 | net@15 | net@30 | borrow %/yr | net@15 − borrow | BR_eff | PC2 share |

Plus: average short weight per name before and after; the fraction of the short
leg in names with fee > 3%; and a **negative control** — the same adjustment
with fees randomly permuted across names, 10 draws. If the permuted version
helps as much, the gain is from something other than borrow (a size effect, a
volatility effect) and the mechanism claim fails.

**Decision rule.** Adopt if net@15 − borrow improves at all three fee
scenarios, gross Sharpe falls by no more than 0.05, the permuted control shows
no comparable gain, and the holdout agrees in sign. **Do not tune `H`, `IC_H`,
or a scaling on `b_i`** — all three are measured. If the adjusted book is
worse, the answer is "the fee is not large enough to matter at this IC", and
that is worth knowing.

**The caveat to carry:** CEF borrow fees move with the fund's own premium,
which is the signal, so a short may become more expensive exactly as it becomes
more attractive. Not modelled; Part E starts measuring it.

---

## Part D — Recall is monthly, not occasional

The repo treats recall as a rare tail. The mechanics say otherwise, and this
changes how the short book should be managed.

- **Reg SHO, verified against the SEC's own text:** a threshold security has an
  aggregate fail-to-deliver position for **five consecutive settlement days**
  totalling **10,000 shares or more** *and* at least **0.5% of shares
  outstanding**; Rule 203(b)(3) forces a **mandatory close-out once fails persist
  for 13 consecutive settlement days**. Threshold lists are published daily by
  Nasdaq, NYSE/Arca, Cboe and FINRA — check the 17 against them at onboarding
  and periodically.
- **Recall notice, corrected:** an earlier draft said "two trading days' notice"
  as though it were a rule. **It is not in Reg SHO** — the SEC's Reg SHO
  material does not address recall at all. Recall terms are **contractual**,
  under the Master Securities Loan Agreement between lender and broker, and
  market practice has been shifting since the T+1 move. **So do not put a
  specific notice period into a risk model on the strength of a half-remembered
  rule. Ask IBKR what their actual recall terms and notice practice are, record
  the answer with its date, and model from that.** Until then treat recall as a
  hazard with an unknown lead time, which is the conservative reading anyway.
- **Every one of the 17 names distributes monthly.** A lender whose shares are
  on loan through a record date receives a payment in lieu instead of the
  distribution, and a payment in lieu is ordinary income — never a
  qualified dividend, and for a **municipal** fund never the exempt-interest
  dividend the holder bought the fund for. A tax-sensitive muni-CEF lender
  therefore has a standing monthly incentive to recall before the record date.
  **Model recall hazard as elevated in the three to five trading days before
  each ex-date, twelve times a year per name — not as a flat annual rate.**

The work:

1. Build the forward ex-date calendar for the 17 (W9's calendar work fetches
   declared-but-not-yet-ex distributions; consume it here). For each held short,
   compute days-to-next-record-date.
2. Measure it: as `cef_borrow.csv` accumulates, test whether
   `available_shares` falls and `fee_rate_pct` rises in the window before
   record dates, per group. This is a clean, pre-registerable prediction with
   an obvious mechanism, and 12 observations per name per year.
3. Feed it to the desk, not to the sleeve: a `recall_watch` field on every
   short row — days to record date, utilisation, pool trend — and a crit flag
   when utilisation is above φ **and** a record date falls inside five sessions.
   No automatic action; a human decides whether to pre-cover.

---

## Part E — By group, for the sleeve design that follows

The facts as measured on one day:

| group | names | fee range | pool depth | binds at |
|---|---|---|---|---|
| muni | NAD 9.98%, NVG 4.23%, NEA 3.06%, NZF 2.58%, MQY 0.76%, MHD 0.41% | 0.4–10% | NAD 3k, NVG 20k, others 150–250k | NAD $45k, NVG $278k |
| hy | HYT 10.56%, AWF 0.28% | 0.3–10.6% | HYT 2.5m, AWF 650k | HYT $22.5m |
| multi | 0.42–1.09% | tight | 250k–6.4m | ≥ $4.3m |
| loan | JFR 1.45% | | 950k | $12m |

Munis carry **91%** of the borrow bill on the current book, and the short leg
of the between-group bet is, by construction, the muni complex. So the cost of
the group bet is that group's discount behaviour **minus 2–10% a year**, and it
is capacity-limited at $45k–$278k in the two scarcest names.

1. **Per group, per day**, on the current book and on the frictionless target:
   weighted fee, pool depth in shares and dollars, utilisation, drag $/yr, drag
   as % of the group's short MV. A table for today and a series that grows.
2. **Capacity by group.** Extend `borrow_capacity.py` to report, per group, the
   capital at which the group's short leg is 25% unfillable, and the book-level
   capacity if the muni short leg is (a) as today, (b) capped per Part B, (c)
   expressed only in the group's two cheapest-to-borrow names.
3. **Net-of-borrow short alpha by group**, using Part C's `a_i` with the
   measured `H` and post-battery `IC_H`: the **breakeven |z| per name** — how
   rich a name must be before shorting it is worth the carry. Expect multi
   shorts to work from |z| ≈ 0.3, scarce munis only above |z| ≈ 1.5, HYT never
   below |z| ≈ 1.5. Tabulate per name.
4. **The two questions W10 needs answered:**
   - At what capital does the muni short leg stop being worth holding at all —
     where does the between bet's net-of-borrow Sharpe cross zero as
     availability forces the short into the expensive names?
   - Is the between bet better expressed **asymmetrically**: long the taxable
     side fully, short only the cheapest-to-borrow munis (MHD 0.41%, MQY 0.76%),
     with the rest of the exposure taken by simply being less long taxables —
     a smaller, cheaper between book? Compute both in the harness with borrow
     charged and hand the result to W10 as its last row.
5. **Fee dynamics**, once there are 20+ days: the correlation between a name's
   fee change and its z change, per group.

---

## Deliverables

- `scripts/cef/short_cap.py`, `borrow_aware_score.py`, `borrow_by_group.py`;
  the two sleeve changes behind `short_cap` and
  `borrow_aware: {"horizon_bd", "ic_h", "_note"}`, each defaulting to off with
  the no-op proof; `data/cef/cef_short_interest.csv`.
- `results/cef/SHORT_CAP_<date>.md`, `BORROW_AWARE_<date>.md`,
  `BORROW_BY_GROUP_<date>.md` (re-runnable, dated, tables carrying the number
  of fee days used), and `results/cef/borrow_by_group.json` for W10 and the
  dashboard.
- Pre-registrations for whichever parts are adopted, and the CEF counter bumped
  by the number of trials actually spent.
- Dashboard payload for W9's borrow desk: per name — fee, rebate, pool, our
  short, utilisation (crit above φ = 25%, warn above 10%), short MV, drag $/yr,
  recall risk, fee Δ5d, days-to-record-date; book totals for the held book and
  for the frictionless target; the capacity line. A name with no row on the
  latest date gets `fee: null, reason: "no rate on <date>"` and the totals carry
  `partial: true`. **No median fill, ever.**

## Do not

- Do not exclude names; cap weights.
- Do not re-normalise gross to 1 after the cap.
- Do not fill a missing pool with a median, a zero, or yesterday's value beyond
  the lookback.
- Do not model a fee; use published rows only.
- Do not charge the distribution yield in the score (W4 handles it in returns).
- Do not feed the recall watch into the sleeve automatically.
- Do not sweep φ, `H`, `IC_H`, or a coefficient on `b_i`.
