# W4 — Is the edge real? The artifact battery, and the missing distribution

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `00_BRIEF.md` §2 (mechanisms), §3 (how these instruments
trade), §5 (harness).
**Lever:** none — this prompt can only *subtract*. It is the highest-value hour
in the queue because everything downstream is conditional on it.
**Trials:** 0. These are diagnostics on the existing signal, not new
specifications. **Touches the live book:** the return convention in Part A is a
correction to the harness, not a specification change; the sleeve's targets do
not move.
**Run immediately after W1.** Nothing that spends a trial should run before it.
**New prompt (2026-09-09), from the literature and a code read.**

---

## Paste from here

You are a quant researcher on the QUANTT credit CEF book. Read
`docs/prompts/00_BRIEF.md`, then `results/cef/ALPHA_AUDIT_2026-09-05.md` in
full and `scripts/cef/band_frontier.py::build_targets` line by line.

The book's measured IC is −0.074 (t = −11.6) at the traded 2-day/T+1 horizon
over 27 years, in every sub-period, stronger out of sample than in. The repo
treats this as settled. Two facts say it should be checked once, properly,
before another trial is spent:

- **There is no academic literature validating a CEF discount-reversion signal
  at a 1–5 day horizon.** This was checked properly on 2026-09-09 rather than
  assumed: every locatable study — Ji & Kim (2013), Patro, Piccotti & Wu (2014),
  Gemmill & Thomas (2002) — uses **monthly data at best**, and a targeted search
  for daily or weekly CEF-discount half-life estimates found nothing published
  or in working-paper form. **The negative result is the finding.** Any two-day
  estimate has no precedent and must be derived in-house, which is what this
  prompt is for. Pontiff (1995, JFE) finds
  a 20%-discount fund earns ~6pp more over *twelve months*; Ji & Kim (2013,
  *Applied Economics* 45(32):4503–4515) find strong mean reversion with
  half-lives measured in **months**, not days. Our own pooled AR(1) φ = 0.9722
  implies a 24.6-day dislocation half-life — an order of magnitude faster than
  the published estimates. **Note an unresolved conflict to settle before
  citing that paper either way:** a second reading of Ji & Kim's abstract says
  *equity* funds stabilise faster than *fixed-income* funds, which is the
  opposite of the ordering this desk has assumed. Pull the paper, read the
  half-life table, and record the actual ordering in `docs/REFERENCES.md`
  before any prompt leans on it. Being
  novel is allowed. Being novel *and* untested against the two mechanical
  effects that produce exactly this signature is not.
- **Three mechanical effects produce a negative 2-day IC on a price-minus-NAV
  signal with no economics at all:** bid-ask bounce in the price leg, stale
  NAV catching up in the NAV leg, and ex-distribution arithmetic. Each is
  testable in a day.

Six parts. Part A is a correction that must land regardless of what the rest
finds. Parts B–E are the falsification battery. Part F is the write-up.

---

## Part A — The backtest does not know these funds pay distributions

`build_targets()` builds returns as

```python
ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
```

on `data/cef/cef_prices.parquet`, which `scripts/cef/fetch_daily.py` fetches
with `auto_adjust=False`. Those are **price returns on unadjusted closes**.
Grep confirms nothing in the CEF path reads `cef_distributions.parquet` into a
return series. **Verify this yourself before proceeding** — read
`build_targets`, `evaluate`, and the sleeve, and confirm no distribution term
enters anywhere.

If it is as it appears, then on every ex-date the backtest books the price drop
as a return and never books the cash:

- The **long** leg drops ~the distribution and is never credited the
  distribution it would have received. Its return is understated by its yield.
- The **short** leg gains the price drop and is never debited the **payment in
  lieu** it owes the lender. Its return is overstated by its yield.

For a dollar-neutral book the two do not cancel. The bias is exactly the
book's yield-weighted net exposure:

    true_return − backtest_return  =  Σ_i w_i · y_i

where `y_i` is name *i*'s distribution yield and `w_i` its signed weight.

**It has now been measured, and it is smaller than an earlier draft of this
prompt claimed.** Computed 2026-09-09 on the band's own holdings path
(`H.shift(2)` against each name's distribution over its prior close, 3,962
ex-dates, 2005-01 to 2026-09):

| period | carry, %/yr | mean net muni weight |
|---|---:|---:|
| **full sample** | **−0.01** | — |
| 2005–09 | +0.00 | +0.0% |
| 2010–14 | **−0.77** | +1.1% |
| 2015–19 | +0.32 | +6.4% |
| 2020–22 | +0.36 | −10.7% |
| 2023–26 | +0.25 | −26.6% |

against the band's measured 6.22%/yr gross return, and with a standard deviation
of **1.23%/yr**.

**So the earlier estimate of "about 2%/yr" was wrong and is withdrawn.** On the
full sample the bias is essentially nil: the long and short legs' yields net out
almost exactly, because this book is not systematically long or short yield —
it rotates. That is a real finding and it should be stated as one.

**Reproduce that table first — it is a prior, not a result.** It was computed
before the convention was fixed, on a distribution panel that ends in late July
2026 (so the last weeks carry none), with thin pre-2013 rows where fewer than
`min_names` clear the ADV filter. Your number will differ.

**The correction is worth making whatever it comes out at, for reasons that do
not depend on its size:**

1. **A return series that omits a known cash flow is simply wrong**, and fixing
   it costs nothing and spends no trial.
2. **The pooled mean is the least informative statistic here.** Report the
   series, its era breakdown and its standard deviation, because a term whose
   average is nil can still be large in any given era and still add variance to
   every Sharpe computed over it. **Whether that is true of our book is what you
   are measuring** — do not assume it from the table above.
3. **It changes what other prompts may claim.** Any era-conditional result, any
   regime study, and W10's group work all read a return series; if the carry is
   material in the era they examine, their numbers move. State which downstream
   results your measured carry affects, by name.

If your measured carry turns out negligible in every era and low-variance, say
so — *"the legs' yields net out and this was not a problem"* is a perfectly good
finding, and it retires the question instead of leaving it open.

**Frame it as total return, not as a fee.** Once returns are total returns the
distribution is handled correctly and automatically: the fund pays out of NAV,
NAV falls, the long receives the cash, the short pays it in lieu, and a fund's
total return is its portfolio's return net of expenses and leverage cost
regardless of how much of it is distributed. Do **not** then also charge a
"distribution cost" inside the alpha score - that double-counts. What survives
the correction as a genuinely separate cost is the **borrow fee** (W8); what
survives as a genuine operational risk is monthly **recall pressure** around
record dates (W8 Part D). The tax treatment of payments in lieu does not bind a
paper book; note it in one line and move on.

### The work

1. **Measure the carry.** From `cef_distributions.parquet` build a per-name
   daily distribution-yield series `y_it` (trailing 12-month distributions ÷
   price, and separately the actual per-share amount on each ex-date). Compute
   `carry_t = Σ_i H_it · (d_it / P_it)` on the live band's holdings path,
   where `d_it` is the distribution with an ex-date of *t*. Report the
   annualised mean, by era, by group, and its sign. **State it in basis points
   against the 32.6bp breakeven and against the band's ~2.3%/yr net
   expectation.**
2. **Build a total-return panel and re-score everything.** `ret_total = ret_price
   + d/P_prev` on the ex-date. Re-run the harness on both conventions and
   report every headline number twice:

   | convention | gross SR | ann % | vol % | turn/yr | net@15 | net@30 | net of borrow |
   |---|---|---|---|---|---|---|---|
   | price return (as scored today) | 1.16 | | | 17.6 | 0.66 | 0.17 | 0.43 |
   | total return (corrected) | | | | | | | |

   Full sample, by era, and fit/holdout per W1. **This is not a trial** — no
   specification was chosen with sight of P&L; a wrong return convention was
   corrected. Say so explicitly in `RESEARCH_STATE.md`.
3. **Make it permanent.** `evaluate()` takes the total-return panel. If the
   distribution panel does not cover a name-date, the harness **raises**; it
   does not fall back to price returns silently. Add the ex-date coverage
   fraction per name to the note — `cef_distributions.parquet`'s last ex-dates
   are in late July 2026, so the panel needs the forward fetch W9 builds.
4. **Correct the record.** Several existing notes and dashboard strings assert
   that an ex-date "moves price and not NAV". That is wrong: **the distribution
   leaves the fund's assets, so NAV drops on the ex-date too.** With price and
   NAV both falling by *D*, a discount `(P−N)/N` goes from `(P−N)/N` to
   `(P−N)/(N−D)` — for a 10% discount and a 0.75% monthly distribution that is
   about **7bp**, not the 75bp the notes claim. Verify this in our own panel
   (regress the one-day change in discount on the ex-date dummy and on
   `d/P`), state the measured coefficient, and fix every string that says
   otherwise. Note the second-order effect Bali & Hite (1998) document: the
   realised price drop is slightly *less* than the distribution because of tick
   discreteness, so the discount narrows a touch on the ex-date — measure the
   sign in our names rather than assuming it.

---

## Part B — Bid-ask bounce

The single most likely mechanical source of a negative short-horizon IC. If
today's close prints at the bid, the fund looks cheap, the signal says buy, and
tomorrow's close prints at the ask: an apparent gain with no convergence. The
general short-horizon reversal literature finds daily reversal profits are
substantially bid-ask bounce and largely vanish when measured off quote
midpoints. Our names trade at $4–17 with a one-cent tick, so the half-spread
runs 3–11bp — the same order as the per-trade edge.

1. **Corwin–Schultz spread estimate** from the panel's high/low (the estimator
   is written out in W7 Part C; import it, do not retype). Build a per-name
   monthly spread series 1986→2026.
2. **Bounce-adjusted IC.** Recompute the discount using a de-bounced price:
   the two standard treatments are (i) the mid of the day's high and low as a
   crude midpoint proxy, and (ii) a moving-average filter removing the
   first-order negative autocorrelation in price returns (report the measured
   AR(1) of price returns per name — a bounce shows up as a negative ρ₁ of
   roughly −(spread/2σ)²). Report IC at 2d/T+1 on the raw close and on each
   de-bounced series, pooled and by name, with the difference and its SE.
3. **The decisive cut:** IC by name against that name's estimated half-spread.
   **If the IC is monotonically stronger in the wider-spread, lower-priced
   names, it is bounce.** If it is flat or stronger in the tight names, it is
   not. State which before you look, and report the cross-sectional regression
   of per-name IC on per-name half-spread with its t.
4. **Why the strategy may survive even if the IC is partly bounce:** we fill
   MOC, in a single auction print, not at the bid or the ask. A bounce
   component of the IC is therefore an *unrealisable* part of the measured
   edge, which is one candidate explanation for gross 1.2 → net 0.10–0.43.
   Quantify: the share of the IC attributable to bounce, and what gross Sharpe
   remains without it.

---

## Part C — Stale NAV catching up

The NAV leg's version of the same problem, and the mechanism the literature
says is strongest in exactly our largest group. Municipal bonds are
matrix-priced: the MSRB reports fewer than 2,800 muni trades a day across
fewer than 1,500 unique securities against more than a million CUSIPs
outstanding, with two-thirds of the securities that trade at all trading once
or twice. Nuveen's own N-2 language says the pricing service values a bond
from "yields or prices of municipal securities of comparable quality, type of
issue, coupon, maturity and rating" — a curve, not a trade. Choi, Kronlund &
Oh (2022, JFE 145(2):296–317) find bond-fund NAVs "extremely stale" with fund
returns predictable over days to weeks, worse in crises.

If the muni CEF's NAV under-reacts on day 0 and catches up over 1–3 days, then
after a bond rally the fund reads *rich*, the signal shorts it, the NAV rises,
the discount "reverts" — and the position earned nothing, because the price
never moved. That is a negative IC with no economics.

1. **NAV return autocorrelation** at lags 1–3, per name and per group, with
   block-bootstrap SEs. The prediction is ordered: muni > loan > multi > hy.
   The repo's pooled figure is 0.388. **If HY is as autocorrelated as muni,
   the mechanism is not what we think and the rest of this part is void; say
   so and stop.**
2. **The lead–lag regression.** Regress each fund's daily NAV return on the
   contemporaneous *and lagged* returns of a matched live-priced proxy (muni:
   MUB and PZA — fetch them via `refresh_market_feeds.py` with a source note,
   the ETF panel has no muni ETF today; hy: HYG/JNK; loan: BKLN/SRLN; multi: a
   duration-matched HYG/LQD blend). **The sum of the significant lag
   coefficients is the size of the staleness.** Report it per group with t's.
3. **The decisive test.** Split the signal into the part explained by
   already-observed proxy moves the NAV has not yet reflected, and the
   residual. Compute the 2d/T+1 IC of each. **If essentially all of the IC
   sits in the stale-NAV component, the strategy is a bond-market timing trade
   wearing a discount-reversion costume, and it should be traded — or not —
   as that.** If the residual carries the IC, the dislocation story survives.
   This split is the single most informative number in the whole battery.
4. **Bond-market holidays.** Columbus/Indigenous Peoples' Day and Veterans Day
   close the bond market while the NYSE trades. On those days the price moves
   and the NAV is carried forward stale, producing a mechanical discount swing
   every single year. Find them in the panel (the NAV date does not advance
   while the price date does), count them, measure the discount move and the
   next-day reversal on them, and **decide whether they are excluded from the
   IC and from trading**. Whatever the decision, it becomes a rule in the
   panel builder, not a footnote.
5. **Distinguish a stale NAV from a carried-forward one.** CEFConnect
   italicises a NAV whose published date is earlier than the row's date — the
   value exists but is old. W3's channel work must capture the NAV's own
   **as-of date**, not just its value; here, use whatever as-of information the
   panel has to count how often a "today" NAV is actually yesterday's, by
   name. A carried-forward NAV is a guaranteed one-day artefact.

---

## Part D — Where the IC actually lives

Three concentration cuts. Any one of them landing means the pooled t of −11.6
is describing something narrower than "a persistent daily edge".

1. **Ex-date concentration.** IC computed excluding the ex-date and the
   following session, per group. These are monthly payers, so ~8% of
   name-days are affected.
2. **Crisis concentration.** IC and its t excluding 2008-09→2009-03, March
   2020, and the 2022 rates shock — and separately, IC by volatility decile.
   In March 2020 Lipper measured the **median** CEF discount widening only
   170bp to 9.78% while mean-based sources report the universe average at
   21.6%; the difference says crisis widening is concentrated in a subset,
   which is exactly the shape that lets a handful of windows carry a pooled
   statistic.
3. **Turn-of-year concentration.** IC for December–January against the rest of
   the year, per group. Starks, Yong & Zheng (2006, JF) document tax-loss
   selling and the January effect specifically in **municipal** CEFs, held
   almost entirely by tax-sensitive retail. If our aggregate IC is materially a
   turn-of-year muni effect, we are rediscovering a published seasonal and
   should say so — and W10 should test it as one.

---

## Part E — The standard errors

Confirm what the t = −11.6 actually is. A naive OLS or plain Spearman t on a
panel with strong cross-sectional correlation (our pairwise correlation of
daily discount *changes* runs 0.42–0.66 across groups) and serial correlation
in overlapping windows will overstate significance badly.

Recompute the IC's standard error three ways and report all three: (i) as
computed today, (ii) clustered by date, (iii) double-clustered by date and
name, plus a moving-block bootstrap over dates. Report the t under each. State
whether the 2-day windows used are non-overlapping (the brief's §5 rule H6 requires it);
if any table used overlapping windows, flag every number that came from it.

---

## Part F — The verdict, written before the trials resume

`results/cef/ARTIFACT_BATTERY_<date>.md` leads with a table:

| candidate artefact | test | result | share of IC explained |
|---|---|---|---|
| missing distributions (carry) | Part A | | (in return, not IC) |
| bid-ask bounce | Part B | | |
| stale-NAV catch-up | Part C | | |
| ex-date arithmetic | Part D.1 | | |
| crisis windows | Part D.2 | | |
| turn-of-year muni seasonal | Part D.3 | | |
| inflated t from clustering | Part E | | (t only) |

Then one sentence, in this form: **"After correcting the return convention and
removing X, Y and Z, the signal's IC at 2d/T+1 is ___ (t ___), and the part of
it that survives is ___, which is the thing we are actually trading."**

Then the consequence, stated plainly. If the surviving IC is materially
smaller, every expected-return number downstream — the Grinold alpha in W8's
borrow-aware score, W12's `c_model`, W11's conviction bands, W7's breakeven
arithmetic — was computed on the old IC and must be recomputed. List them.

## Deliverables

- `scripts/cef/artifact_battery.py` (all five test groups, importing the
  harness — do not build a second backtester), the total-return panel and the
  `evaluate()` change, `results/cef/ARTIFACT_BATTERY_<date>.md`, the corrected
  strings, and a `RESEARCH_STATE.md` line recording that the return convention
  was corrected and that no trial was spent.
- If the distribution panel cannot cover the sample, say exactly which
  name-years are missing and bound the carry over them rather than assuming
  zero.

## Do not

- Do not "fix" a failed test by changing the signal. This prompt measures; W10
  and W13 respond.
- Do not drop a test because it is inconvenient, and do not report a battery
  with a missing row.
- Do not treat a surviving IC as vindication of the *size* of the edge; a
  surviving sign with a halved magnitude changes every downstream number.
- Do not spend a trial anywhere in this prompt. If you find yourself choosing
  between specifications, you have left the battery and entered W10.
