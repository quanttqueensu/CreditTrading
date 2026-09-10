# G3 — The hedging specification, and the one benchmark that grades it

**Reads first:** `G0_BRIEF.md` (§1, the identity), `G1_option_math.md`.
**Settles:** how we hedge, how often, at what price, and — the part that is
easiest to get wrong and most expensive when you do — **which realised-volatility
estimator the result is compared against.**
**Trials:** 0. **Touches the live book:** no; it produces a specification and a
measurement plan.
**Run after G1 and G4, and before G2 and G6.** G6's central number is realised
against implied, and Part C decides what "realised" is allowed to mean.

---

## Paste from here

You are a trading engineer on the QUANTT book. Read
`docs/prompts/gamma/G0_BRIEF.md` and `G1_option_math.md`, then
`docs/prompts/00_BRIEF.md` §3 for the auction mechanics this inherits.

Our constraint is unusual and shapes everything: **no intraday process, no live
quote subscription, one hedge decision per day, executed in the closing
auction.** The question is not whether that is ideal. It is what it costs, how
to specify it precisely, and how to measure whether it was done well.

---

## Part A — What discrete hedging costs

Over one rehedge interval the hedging error is proportional to
`Γ·(ΔS² − σ²S²Δt)`. Since `ΔS/√(σ²S²Δt)` is approximately standard normal,
`ΔS²/(σ²S²Δt)` is approximately χ²₁, so **the per-interval error is proportional
to (χ²₁ − 1): mean zero, right-skewed, fat-tailed** (Boyle & Emanuel 1980, JFE
8:259–282).

Summed over `N` rehedges, **the total hedging error's variance scales as 1/N and
its standard deviation as 1/√N**. Moving from weekly to daily rehedging (≈5×
more rehedges) shrinks the dispersion by about √5 ≈ 2.2×; hourly would shrink it
by a further √6.5 ≈ 2.5× while multiplying transaction costs by 6.5. At N = 252
we are already at the point where the marginal variance reduction is small
against the marginal cost — **so once-daily is a defensible place to sit, not a
crippled one**, and the note should say so plainly rather than apologising for
it.

What does *not* shrink is the shape. The χ²-driven skew persists at finite N
because convergence is slow, so the realised P&L path is **many small
theta-bleed days and a few large gamma days**. That is the signature to expect
and to check for (G5), and it is the reason 60 sessions cannot settle anything
about the mean.

**Measure it rather than assuming it.** Simulate the book's own hedging error at
N ∈ {252, 504, 1260} on the historical path and confirm the variance falls
approximately as 1/N. If it does not, the model is wrong somewhere and that is
worth finding before any money — even paper money — is committed.

---

## Part B — Bands, and why ours is not a risk control

Under proportional transaction costs the optimal policy is a **no-trade band**
around the theoretical delta, not continuous zeroing. Whalley & Wilmott (1997,
*Mathematical Finance*) solve the Hodges-Neuberger utility problem
asymptotically and give a half-width of the form

    H ∝ [ (3/2) · e^{−r(T−t)} · S^a · Γ² · ε / λ ]^(1/3)

with `ε` the proportional cost rate and `λ` a risk-aversion coefficient.

**Two terms in that expression were unverified, and dimensional analysis
settles both** — done 2026-09-10, so the paper is no longer needed for this:

    H       no-trade band, in DELTA units; delta = ∂V/∂S   → dimensionless
    Γ       ∂²V/∂S² = price / price²                        → price⁻¹
    ε       proportional transaction cost                   → dimensionless
    λ       CARA risk aversion; λ·W must be dimensionless   → price⁻¹
    S       spot                                            → price⁺¹

Inside the bracket: `price^a · price⁻² · 1 · price⁺¹ = price^(a−1)`. For H³ to
be dimensionless, **a = 1**.

> **So it is `S`, not `S²`** — the desk's original spec had that right. The one
> genuine error was a **notation collision**: an earlier draft wrote the
> risk-aversion parameter as lowercase `γ` while capital `Γ` is the option's
> gamma **in the same formula**. Use `λ`. Anyone implementing from the old form
> would have been reading one symbol as two different quantities.

The full expression is therefore

    H = [ (3/2)·e^{−r(T−t)}·S·Γ²·ε / λ ]^(1/3)

**with the (3/2) constant still uncited** — dimensional analysis fixes the
exponents, not the leading coefficient. That does not matter here, because Part
B concludes we do not use this as a risk control at once-daily frequency
anyway; what we rely on is the scaling, **H ∝ Γ^(2/3)**, which is the result the
paper is known for and which dimensional analysis is consistent with. If a
future intraday process ever makes the band operational, get the constant. H also scales as `ε^(1/3)`
(so even tiny costs justify a real band) and `γ^(−1/3)`.

Zakamouline (2006) corrects WW's bandwidth where it degenerates far from the
money; Leland (1985) offers the alternative of an *adjusted volatility* rather
than a band, and **Kabanov & Safarian (1997) showed Leland's limiting hedging
error is non-zero, contradicting his original convergence claim** — so use the
no-trade region, not a vol adjustment, and cite why.

**Now the part that matters for us, and it is a correction to the obvious
reading of that literature.** Those bands are derived under **continuous
monitoring**: you sit inside the band and react the instant delta touches the
edge. A once-daily observer cannot do that. Delta can breach the band at 10:15
and there is no way to act until 15:50. And for a book with meaningful gamma,
one day's delta drift is typically *already larger* than the WW band computed
for that gamma — the band was sized to filter sub-day noise a daily process
never sees.

**So for this desk the band is not a risk policy; it is a minimum-ticket
filter.** Hedge to flat essentially every day, and use a deadband only to skip
trades that are not worth an order — fewer than one round lot, or below a stated
minimum notional. **Derive that threshold from the commission and half-spread
the way `min_trade_usd` was derived for the CEF book, and state it as an
operational filter, not as a Zakamouline band.** Report the WW band width
alongside for the record, so a future reader can see it was computed and
deliberately not used, and re-open the question if an intraday process ever
exists.

---

## Part C — The benchmark, and the expensive mistake

**This is the most important paragraph in the gamma programme.**

A once-daily close-to-close hedger's realised P&L tracks **close-to-close
realised variance**. That is the `r²` term in the identity, literally. Every
other realised-volatility estimator measures something else:

| estimator | what it measures | correct benchmark here? |
|---|---|---|
| **close-to-close**, `Var[ln(C_t/C_{t−1})]` | exactly the r² we earn | **YES — the only one** |
| Parkinson, `(1/4ln2)·mean[ln(H/L)]²` | intraday range, **excludes the overnight gap** | no |
| Garman-Klass | intraday, assumes no overnight jump | no |
| Rogers-Satchell | intraday, drift-independent | no |
| Yang-Zhang | includes overnight; ~14× more efficient | **as a lower-noise cross-check of the vol *level*, never as the attribution benchmark** |
| high-frequency realised variance | open-to-close only, by construction | no |

Parkinson, Garman-Klass, Rogers-Satchell and intraday RV **systematically
exclude or underweight the overnight gap our position actually carries**.
Benchmarking a close-to-close hedger against any of them will make the book look
like it is underperforming its hedge when in fact the estimator is blind to part
of what hit it. **Pulling a vendor's range-vol screen — usually Parkinson or
Garman-Klass by default — and comparing it to our P&L is the expensive
mistake.** Write the rule into the code: the capture-ratio function accepts
close-to-close variance and raises on anything else.

### The overnight share — measured, not assumed

This was computed on `data/rv/etf_ohlc.parquet` on 2026-09-09. **Re-run it and
confirm before relying on it**, but the design implication is already clear and
it is the opposite of the intuition most people bring:

    overnight_share = Σ[ln(O_t / C_{t−1})]² / Σ[ln(C_t / C_{t−1})]²

| ticker | period | ann. c-to-c vol | **overnight share** | intraday share | **Parkinson ÷ c-to-c** |
|---|---|---:|---:|---:|---:|
| HYG | full | 11.0% | 37.3% | 62.0% | 65.2% |
| **HYG** | **2019+** | **9.1%** | **59.6%** | 45.2% | **48.3%** |
| LQD | 2019+ | 9.7% | 48.6% | 49.2% | 48.4% |
| TLT | 2019+ | 16.0% | 54.5% | 48.5% | 45.9% |
| SPY | 2019+ | 19.5% | 43.7% | 53.4% | 56.3% |
| JNK | 2019+ | 9.2% | 55.0% | 45.0% | 48.2% |

**Since 2019, roughly 60% of HYG's close-to-close variance arrives overnight.**
Shares need not sum to 100% because `Σcc² = Σon² + Σoc² + 2Σ(on·oc)`; the cross
term is small and the overnight/intraday correlation is near zero (HYG: ρ =
−0.046), so this is not a reversal artifact. Nor is it a stale-open artifact:
HYG's opening gaps since 2019 have a median of 0.0bp, a standard deviation of
44bp, only 4.0% exactly zero, and 9.7% beyond ±50bp — real prints.

**Re-run this before it shapes anything.** The panel ends 2026-07-29 and the
split moves with regime — HYG's own overnight share was 37% on the full sample
against 60% since 2019. **The table is a prior, not an input.** What the note
must contain is the number you measured, on the window you traded, with the
method above.

**Then let the design follow from whichever way it comes out**, and state both
branches in advance:

- **If the overnight share is high** (as the recent sample suggests), a
  once-daily close-to-close hedger captures the majority of realised variance in
  a window *neither* a daily nor an intraday hedger can trade. The once-daily
  constraint then costs far less than the discrete-hedging literature implies,
  the 1/N argument of Part A applies only to the intraday remainder, and the
  note should say so plainly rather than apologising for the constraint.
- **If it is low**, the intraday portion dominates, the 1/N penalty bites on
  most of the variance, and hedge frequency becomes a real design question worth
  revisiting — at which point the band literature in Part B stops being
  academic.

Note also, whichever way it lands, that **French & Roll (1986) is not in
conflict with a high overnight share.** Per unit of *clock* time intraday
variance is higher; the overnight *total* can still be larger simply because the
window is ~17.5 hours against a 6.5-hour session. Compute both framings and say
which you mean.

**The last column is the point of this whole section**, and it is a
*relationship* rather than a level: measure what fraction of close-to-close
variance a range estimator recovers on your own data. On the sample above
Parkinson recovered roughly half. Whatever it recovers on yours, benchmark a
close-to-close hedger against a range estimator and you will misread realised
against implied by that factor.

**Two corrections to the intuitive reading of that number, both worth stating in
the note.** First, **a daily hedger and an intraday hedger carry the same
overnight gap** — neither can trade between the close and the next open — so
daily hedging is not a worse *overnight-risk* design; intraday hedging only
improves how the *intraday* portion is captured. Second, long gamma's
expectation does not care how the variance arrived, since `E[dΠ] ∝ E[r²] −
σ²Δt`, but its **variance does**: concentrating the same quadratic variation
into fewer, larger jumps raises the dispersion of realised gamma P&L for the
same mean, by exactly the 1/N mechanism of Part A run backwards. **Overnight-heavy
variance is neutral in mean and worse in variance.** State it that way.

---

## Part D — Execution

**The auction's clock binds, and it is not the same clock at every venue.**
Verified against rule text 2026-09-09; the differences are large enough to break
a router that assumes uniformity:

| venue | our instruments | MOC cutoff | LOC cutoff | imbalance | human backstop |
|---|---|---|---|---|---|
| **NYSE** | the 17 CEFs | **15:50** | **15:50** | once at 15:50, >=500 round lots | **DMM discretion** |
| **Nasdaq** | **TLT** | **15:55** | **15:58** | NOII every 10s from 15:50, every 1s from 15:55 | none |
| **NYSE Arca** | HYG, LQD, SPY | **unverified** | unverified | unverified | none |

Three consequences for the hedge:

1. **The CEF book and the TLT hedge have different deadlines** - 15:50 against
   15:55/15:58. Do not build one cutoff into the scheduler.
2. **NYSE's 15:50 freeze is absolute**: MOC/LOC cannot be cancelled or reduced
   after it **"even to correct a legitimate error"**, the only carve-out
   requiring a Trading Official's approval. Nasdaq freezes cancel/modify at 15:50
   but keeps accepting new MOC to 15:55. Plan the submission buffer against the
   *earliest* binding cutoff, not the latest.
3. **Arca's mechanics could not be verified**, and Arca is where HYG, LQD and SPY
   list - the three instruments this programme actually hedges in. **Confirm
   Arca's cutoff and threshold from Rule 7.35-E before the first live hedge**,
   and treat parity with NYSE as an assumption to test.

NYSE's close is DMM-facilitated - a DMM may close a security without a trade, or
run the auction manually - while **Arca and Nasdaq are purely algorithmic with no
human backstop.** That is a reason to prefer a limit over a naked market order at
those venues, not a reason to avoid them.

**Use LOC, not naked MOC**, with a protective limit a stated distance from the
last price. That trades a small probability of no-fill against protection from a
disorderly close, and an unfilled hedge is a known, loggable state whereas a
fill 3% away is a loss. Pick the distance from the ticker's own distribution of
close-to-last moves, not from a round number.

**Impact should be negligible and must still be measured.** At $10k–100k in
HYG or TLT we are far below NYSE's 500-round-lot (50,000-share) publication
threshold — though note Nasdaq's NOII has no such threshold, so a TLT hedge is
visible in the indicator in a way an NYSE order is not. The real risk is not our footprint but **correlation with the
crowd**: our hedge triggers on a large realised move, which is exactly when
vol-target, risk-parity and CTA rebalancing flows also trade the close in the
same direction. **Log the 15:50 published imbalance alongside every hedge and
test, after 60 sessions, whether our slippage is worse on days when the
imbalance was same-signed as our order.** That is a real, checkable hypothesis
and nobody has run it here.

**Instrument.** Hedge the ETF option with the ETF itself — exact, no basis. A
long call's delta hedge requires a short, so confirm HYG/LQD/TLT borrow against
W8's panel rather than assuming general collateral. Do not reach for IBHY
futures at this size: thin, a second basis to track, and futures permission we
may not have.

---

## Part E — The hedge log, and what it is for

Per hedge, one row, no exceptions:

`date, underlier, pre_hedge_delta_shares, pre_hedge_delta_usd, target_delta,
hedge_qty, order_type, limit_price, benchmark_price, fill_price, slippage_usd,
slippage_bp, commission, post_hedge_delta, imbalance_at_1550, filled (bool),
skipped_reason`

Per session, the full attribution from G0 §1:

`gamma_pnl, theta_pnl, vega_pnl, vanna_pnl, volga_pnl, hedge_pnl, costs,
unexplained, rv_cc, iv_used, capture_ratio, breakeven_move, actual_move`

Over a rolling 60 sessions, compute and report: mean and SD of daily hedge P&L;
slippage in bp and as a fraction of the estimated spread; the close-to-close
realised ÷ implied variance ratio; total cost as a percentage of option
notional, annualised; the variance-reduction ratio `Var(hedged)/Var(unhedged)`;
and **the autocorrelation of day-to-day hedge direction** — negative means
whipsaw and argues for a wider deadband, positive means trending and argues the
deadband is already too wide.

**And two counterfactuals computed ex post on every session**: P&L had we not
hedged that day, and P&L had we hedged only to a band edge. Those two columns are
what will eventually answer the band question with our own data instead of with
an asymptotic result derived under assumptions we do not satisfy.

## Deliverables

- `src/deploy/lib/hedging.py`: the deadband derivation, the WW band computed for
  the record, `capture_ratio()` which accepts close-to-close variance and
  **raises** on any other estimator, and `overnight_share()`.
- `results/gamma/HEDGING_SPEC_<date>.md`: the 1/N verification, the
  overnight/intraday split per ticker, the derived deadband with its arithmetic,
  the WW band alongside with the reason it is not used, the venue and auction
  table, and the complete hedge specification with **every parameter either
  derived or explicitly flagged as a judgement call**.

## Do not

- Do not benchmark a close-to-close hedger against Parkinson, Garman-Klass,
  Rogers-Satchell or intraday realised variance. Ever.
- Do not implement a Zakamouline band as a risk control on a once-daily
  process, and do not describe the minimum-ticket filter as one.
- Do not hedge intraday. There is no intraday process in this system and MOC is
  the only fill we can measure.
- Do not use a naked MOC where an LOC with a derived limit will do.
- Do not assume the overnight variance share; compute it per ticker.
- Do not assume HYG/LQD/TLT borrow is free; check the panel.
