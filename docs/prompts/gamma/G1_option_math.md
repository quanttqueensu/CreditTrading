# G1 — The option math we own: pricing, greeks, and implied vol from a trade print

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `G0_BRIEF.md`, `00_BRIEF.md` §6 (house rules).
**Settles:** the model every other prompt in this programme inverts, prices and
hedges with. **Trials:** 0 — nothing here is evaluated on P&L.
**Touches the live book:** no.
**Run first.** G2, G3, G5, G6 and G7 all import this module.

---

## Paste from here

You are a quant developer on the QUANTT book. Read `docs/prompts/gamma/G0_BRIEF.md`
and `docs/prompts/00_BRIEF.md` §6, then confirm for yourself the thing that
makes this prompt necessary:

```
grep -rn "black_scholes\|black76\|implied_vol\|norm\.cdf\|def bs_" --include=*.py .
```

**There is no option pricing code in this repository.** No Black-Scholes, no
Black-76, no implied-vol solver, no greeks. The `iv` column in
`data/vrp/atm_iv_daily.parquet` was produced by a script that is not here
(`scripts/vrp/` is gone). `src/deploy/lib/black76.py` is a file earlier prompts
propose to create; it has never existed.

Then read `src/deploy/sleeve.py` — `PositionTarget`'s `OPTION` kind, the `meta`
contract (`underlier`, `expiry`, `strike`, `opt_type`, `multiplier`), and
`LegGreeks`, **which is defined and never used anywhere in the repo**. This
prompt gives `LegGreeks` its first producer.

---

## Part A — Get the model right before writing it

**The contracts we will actually trade are American options on
dividend-paying ETFs, and that changes the model.** HYG, LQD and TLT distribute
**monthly**, and their listed options are American-style on the ETF. A European
Black-76 or Black-Scholes inversion applied to these will systematically
misprice — and therefore mis-invert the implied vol of — in-the-money puts, and
in-the-money calls near an ex-date, because early exercise carries real value
when the dividend is large relative to the option's time value. These are 6-9%
yielders paying twelve times a year; the dividend is not a rounding error.

This is not a theoretical nicety. **Cboe's own stated rationale for launching
options on IBHY/IBIG futures was "dividend incorporation reducing early
exercise risk" relative to the ETF options** — the exchange built a product to
route around exactly this problem.

So the module implements **three** pricers, and the caller chooses explicitly:

1. **`black76`** — European, on a forward. Correct for options on *futures*
   (IBHY/IBIG, if they ever become reachable), and the right model for a
   forward-based sanity check. **Not** the default for ETF options.
2. **`bs_discrete_div`** — Black-Scholes European with the present value of
   known discrete dividends removed from spot. Cheap, and adequate for
   at-the-money short-dated options where early exercise has negligible value.
3. **`american_binomial`** — Cox-Ross-Rubinstein with the **actual discrete
   ex-dividend schedule** applied as price drops at the ex-dates, and early
   exercise tested at every node. This is the reference implementation. Provide
   **Bjerksund-Stensland (2002)** as a fast closed-form approximation and
   report the two against each other on a grid; use BS-2002 in loops and the
   tree as the truth.

**The default for anything touching HYG / LQD / TLT / SPY option prints is
`american_binomial`.** Any use of `black76` on an ETF option must be an explicit
argument with a comment saying why, and the module should make the wrong choice
awkward rather than easy.

**Quantify the error rather than asserting it.** Part D's first table is the
early-exercise premium — `american_binomial` minus `bs_discrete_div` — across a
moneyness × tenor grid at realistic HYG parameters, in dollars and in implied
vol points. That table is the justification for the extra machinery, and if it
shows the premium is negligible everywhere we trade, say so and simplify.

**Dividends come from data, never from a yield assumption.** Build the
ex-dividend schedule for the option underliers from
`data/rv/etf_ohlc.parquet`, which **has a `dividend` column and a `ret_total`
column** (unlike the CEF panel, which has neither). Note that panel's last bar
is 2026-07-29 — six weeks stale against the CEF panel — and extend it before
relying on it.

---

## Part B — The module

`src/deploy/lib/black76.py` is the wrong name for what this is. Call it
**`src/deploy/lib/optmath.py`** and have `black76` be one function inside it.

**Pricing and greeks**, each returning analytic values where they exist and
finite differences where they do not, with the differencing step stated:

```
price(S, K, T, r, q_schedule, sigma, right, model)      -> float
greeks(S, K, T, r, q_schedule, sigma, right, model)     -> LegGreeks
    delta, gamma, theta, vega, vanna, volga, charm, rho
implied_vol(price, S, K, T, r, q_schedule, right, model) -> float | None
forward(S, T, r, q_schedule)                             -> float
```

Conventions, fixed here once so no other prompt re-decides them:

- **Time** in years, ACT/365F, and `T` measured to the **close of the expiration
  date**. State whether a same-day expiry is `T = 0` or a fraction and enforce it.
- **Theta** per calendar day, not per year. Every other prompt in this programme
  compares theta against a daily gamma term; a per-year theta silently
  introduces a 252× error.
- **Vega** per **one implied-vol point** (0.01), not per unit. Same reason.
- **Rate** from the repo's own curve, not a constant.
- `implied_vol` returns **`None`**, never a fallback, when the price is outside
  the no-arbitrage bounds, when the solver fails to bracket, or when `T <= 0`.
  A `None` propagates and the caller decides. **Never return a default vol, and
  never clamp silently** — house rule, §6.

**The at-the-money asymptotics** every consumer will use, so they belong in the
module docstring with their derivations:

    Γ_ATM ≈ φ(d1)/(S·σ·√T) ≈ 1/(S·σ·√(2πT))        so  Γ ∝ 1/√T
    Θ_ATM ≈ −S·σ·φ(d1)/(2√T)                        so  Θ ∝ 1/√T
    Vega_ATM ≈ S·φ(d1)·√T                           so  Vega ∝ √T
    premium_ATM ≈ 0.4·S·σ·√T                        (Brenner–Subrahmanyam)
    ⇒ Γ/premium ∝ 1/T,  and |Θ|/Γ ≈ ½σ²S² is tenor-invariant

That last relation is why the daily breakeven move `S·σ_imp/√252` does not
depend on the option's own tenor, and it is the single most useful screening
number in the programme. Implement `breakeven_move(S, sigma_imp, dt)` and use it
everywhere rather than re-deriving it.

**Assignment.** The OCC's exercise-by-exception threshold is **$0.01
in-the-money at expiration** for equity and ETF options. G4's ledger needs a
function here that decides, given a settlement price and a strike, whether a leg
is exercised — put it in this module so there is exactly one implementation.

---

## Part C — Tests, which are the deliverable as much as the code

Every one of these is a `pytest` case, and the module is not done until they all
pass:

1. **Put-call parity** holds to 1e-10 for `black76` and to the discretisation
   tolerance for the tree, across a moneyness × tenor grid, with dividends.
2. **The tree converges to Black-Scholes** as steps → ∞ with dividends removed
   and early exercise disabled: assert the gap falls monotonically and is under
   1e-4 at 2,000 steps.
3. **An American call on a non-dividend-paying underlier equals the European
   call** (the classic no-early-exercise result). This catches an early-exercise
   bug that a parity test will not.
4. **Greeks against finite differences** of `price`, each to a stated tolerance,
   including the second-order ones (vanna, volga) which are where sign errors
   hide.
5. **`implied_vol` round-trips `price`** to 1e-6 across the grid, and returns
   `None` — not a number — outside the arbitrage bounds and at `T <= 0`.
6. **Against real extracted marks.** Take a sample of ATM prints from
   `data/vrp/marks_SPY.parquet` and invert them; compare to
   `atm_iv_daily.parquet`'s `iv` column for the same (date, expiry). **They will
   not match exactly, because that column was produced by code we no longer
   have.** Report the distribution of the difference. If it is centred near
   zero with small dispersion, the missing script used a similar model and the
   existing `atm_iv_daily` rows can be trusted for SPY/QQQ history; if it is
   biased, **the existing column must be regenerated by G2 and cannot be mixed
   with new rows**. This test decides which, and it is why it is in G1 rather
   than left to be discovered later.

---

## Part D — The note

`results/gamma/OPTION_MATH_<date>.md`:

1. **The early-exercise premium table** — `american_binomial` minus
   `bs_discrete_div` across moneyness × tenor at HYG-like parameters, in dollars
   and in vol points, with the ex-dividend schedule used. Lead with it; it is
   the justification for the whole model choice.
2. The convergence and parity test results with their tolerances.
3. **The reconciliation against `atm_iv_daily.parquet`** from test 6, with the
   explicit verdict: existing rows usable, or regenerate.
4. The conventions table (time basis, theta per day, vega per point), stated
   once so every later prompt can cite it instead of re-deciding.

## Do not

- Do not use IBKR's model greeks or implied vols anywhere, ever. They need a
  market-data subscription the paper account may not carry and they cannot be
  reproduced from our own inputs.
- Do not default to a European model for an ETF option.
- Do not return a fallback implied vol. `None` is the answer when there is no
  answer.
- Do not assume a continuous dividend yield for a monthly-distributing ETF; use
  the discrete schedule from the data.
- Do not mix a per-year theta with a per-day gamma term anywhere.
- Do not add a stochastic-volatility model. `docs/PLAN.md` already recorded the
  verdict on Heston/SABR for this desk, and nothing in this programme needs one:
  we are inverting prints and hedging deltas, not calibrating a smile dynamic.
