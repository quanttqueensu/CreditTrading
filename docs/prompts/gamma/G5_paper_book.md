# G5 — The paper book: what sixty sessions can and cannot establish

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `G0_BRIEF.md` (§2 and §6 especially), `G3_hedging.md`.
**Settles:** whether the machinery works, what the P&L decomposition looks like
in reality, and what delta hedging actually costs us. **It settles nothing about
whether gamma scalping makes money, and it is not permitted to claim otherwise.**
**Trials:** 0. Nothing here is a specification evaluated on P&L.
**Touches the live book:** never. Own book, own ledger, own client id, hard
notional cap.
**Prerequisites:** G1, G2, G3, G4, and **W2's account audit saying
"options: permitted"** — check the permission *level*, since long options and
delta hedging need level 2 plus stock permission.

---

## Paste from here

You are building a small options book for the QUANTT team on the IBKR paper
account. Read `docs/prompts/gamma/G0_BRIEF.md` in full, then
`results/ops/ACCOUNT_AUDIT_<date>.md`. **If that note does not say options are
permitted, stop and do nothing else.**

Then read `ops/books/phase0_book.json` and `ops/schedule/phase0.env` for how a
separate book is declared, scheduled and given its own client id, and
`src/deploy/sleeves/null_trader.py` as the model of a book that exists to
measure rather than to earn.

---

## The scope, narrowed honestly before anything is built

This book was originally proposed with four things to learn. **One of them is
already answered, in IBKR's own words, and the answer removes it.** From their
paper-trading documentation, verified 2026-09-09:

> *"Fills are simulated from the top of the book; no deep book access."*
> *"Penny trading for US Options is not supported. Orders can be submitted but
> will not receive a penny fill."*

No deep book means size beyond the top quote is never modelled as absorbed or
impacting. No penny fills means the simulation cannot represent the increment
real option markets quote in. So "how kind are paper option fills?" resolves to
"infinitely kind", and **no option transaction-cost economics can be learned here
at all.** Quote those two lines in the book's own README rather than discovering
it at session 60. The same page adds that stops and complex order types are
always simulated in paper, so their behaviour differs from production too.

**What it can legitimately establish:**

- Greeks behaviour and hedge mechanics under real rolls, expiries and
  assignments — G4's machinery exercised against a live gateway rather than a
  fixture.
- **The shape of discretely-hedged P&L.** Boyle & Emanuel predict a
  χ²-driven, right-skewed distribution: many small theta-bleed days, a few large
  gamma days. Confirming that shape on our own path is a real, checkable result
  and it is the honest headline of the 60-session note.
- The qualitative effect of hedge frequency and deadband width on P&L variance,
  via G3's ex-post counterfactual columns.
- **Delta-hedge execution cost at MOC in ETF shares — this part is genuinely
  real**, because the share legs fill like any other share order. It feeds W7's
  cost programme directly and is arguably the most valuable output here.
- Close-to-close realised versus implied variance in HYG and TLT, session by
  session, extending `vrp_monthly.csv` into credit and rates with our own
  executions behind it.
- Whether the option ledger holds across a full cycle without desync.

**What it cannot establish, and must never be reported as establishing:**
whether the strategy has positive expected value. The fills are unrealistic, the
P&L distribution is fat-tailed and skewed so a short sample is dominated by
noise in both directions, and the dominant real-world driver — slippage — is
absent from the simulation. Lo (2002) gives SE(ŜR) ≈ √((1 + ½SR²)/T); at
T = 60 even a true annualised Sharpe of 1.0 cannot be distinguished from zero,
and the χ² skew widens that further. **60 sessions is also typically one
volatility regime.**

---

## Design

- **Book:** `ops/books/gamma_book.json` — **to be created by this prompt; it
  does not exist** — sleeve `gamma_scalp`, capital $50,000,
  `max_gross_option_notional_usd: 50000`, its own IBKR client id, its own
  launchd job at **08:45** (after `cef`), with capture riding on `cef_pm` at
  17:30. Never netted with, or attributed to, any other book.
- **Position:** one long ATM straddle at a time on **HYG** (credit) and one on
  **TLT** (rates), **30–45 DTE at entry, rolled at 14 DTE**. That tenor is
  chosen from G1's asymptotics, not by habit: gamma and theta both scale as
  1/√T so their ratio is roughly tenor-invariant, but Γ/premium scales as 1/T,
  so shorter is more gamma per dollar *and* more decay and pin risk. 30–45 DTE
  with a roll before the final fortnight is where those meet. **Quantity comes
  from the cap, never from a view.**
- **Hedge:** G3's specification exactly — hedge to flat at the close via LOC in
  shares, minimum-ticket deadband, full hedge log. One hedge decision per
  session.
- **Greeks and marks:** G1's module on G2's surface, **never IBKR's model
  values**, with the broker's closing mid recorded beside our model price so the
  gap is visible every day.

**Attribution comes first, and it is a hard gate.** `bench_b1` holds HYG, and
the retired null trader held it too. `arm()` must **refuse** if another book
trades the same ETF. So either resolve the attribution before the first order or
give this book a hedge instrument no other book holds — **state which, in the
book's README, before any code runs.** An attribution collision discovered after
sixty sessions invalidates the sixty sessions.

---

## The deliverable is the decomposition

Every session, decompose the book's P&L into

    gamma (½ΓS²r²) − theta (ΘΔt) + vega (𝒱Δσ) + vanna + volga
      + hedge P&L − costs + unexplained

and write it to the ledger as columns, reading greeks from G4's position rows
rather than recomputing them. **The book is judged on the size of
`unexplained`** — target under 10% of gross gamma P&L over 60 sessions — and on
60 clean, reconciled sessions. Not on P&L.

A large residual has three usual causes and the note should distinguish them: a
stale or mis-fitted vol surface, a deadband so wide that discretisation error
leaks into the residual, and genuinely uncaptured higher-order terms (vanna,
volga, charm). **Gamma minus theta is realised minus implied variance** — the
team should be able to read that number off the dashboard and say which one won
that day, in close-to-close terms per G3 Part C.

## Two traps, written into the README now

- **A quiet stretch is the position working as designed.** Long gamma bleeds in
  calm markets; that is what paying for convexity looks like, not evidence to
  abandon it.
- **A lucky high-realised-vol stretch is not skill.** With a χ²-shaped hedging
  error, short samples are dominated by noise in both directions, and the
  temptation to read a good quarter as validation is exactly what the 60-session
  rule exists to resist.

## Lifetime and kill rules

Closes after 60 armed sessions unless the CEF-side overlay (`W14`) was adopted,
in which case its machinery becomes the overlay's and this book is retired.
Kill immediately on: any position in another book's ETF; **any short option**
(this book is long-only in options by construction); notional above the cap; or
a ledger desync.

## Deliverables

- `src/deploy/sleeves/gamma_scalp.py`, `ops/books/gamma_book.json`, the `.env`,
  the launchd plist rendered by `ops/schedule/install.sh`, and an `arm()`
  refusal test for the shared-ETF case.
- Dashboard: a **Gamma** tab — three tiles (gamma − theta today, close-to-close
  realised vs implied over 21 sessions, unexplained %) and the decomposition
  table. Real data only; a session the book did not run shows as not run.
- `results/gamma/GAMMA_BOOK_<date>.md` at sessions 20, 40 and 60, each leading
  with the decomposition accuracy and the hedge-cost measurement, and each
  reporting P&L **with its Lo standard error and no verdict**.

## Do not

- Do not start before the account audit says options are permitted.
- Do not present this book's P&L as a strategy result anywhere, including
  informally.
- Do not size by conviction; the cap sizes it.
- Do not hedge in an ETF another book holds until attribution is resolved.
- Do not write an option under any circumstances.
- Do not report a Sharpe without its standard error and the session count.
