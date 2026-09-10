# The gamma programme: standing brief

**Every prompt in `docs/prompts/gamma/` opens by reading this file and
`docs/prompts/00_BRIEF.md` §5–§6 (the harness rules and house rules, which
apply here unchanged).**

This is a **second strategy with its own trial counter and its own track
record**, not a sub-section of the CEF book. Where the two meet — a long-gamma
overlay bought to protect the CEF book's tail — that use case lives in the CEF
queue as `W14_options.md` and is gated on the CEF book's own stress beta.
Everything else lives here.

Written 2026-09-09 from sourced research plus a full read-only audit of the
repo's existing options infrastructure.

---

## 1. What gamma scalping is, exactly

Hold an option, hedge its delta, and the P&L over an interval is

    dΠ = ½·Γ·S²·(r² − σ_imp²·Δt)

where `r = dS/S` is the realised return over the interval. Delta hedging removes
the directional bet; what remains is a bet that the underlying moves **more than
the option price assumed**. `$Γ = Γ·S²` is *dollar gamma* — P&L per unit of
squared return, so ½·$Γ·(0.01)² is what a 1% move pays.

Held to expiry, the total is

    ½∫₀ᵀ Γ_t·S_t²·(σ_t² − σ_imp²) dt

which is a **gamma-weighted** average of realised variance, not a simple one.
Instantaneous variance is weighted by the dollar-gamma path, which is largest
at-the-money and near expiry and near zero far from the strike. **Two paths with
identical total realised variance pay very differently.** Path matters.

This is why a variance swap is the *pure* volatility instrument and a
delta-hedged option is not: the log contract has Γ = 1/S², so its dollar gamma
is constant and its variance weighting is uniform (Neuberger 1994; Carr & Madan
1998). We cannot trade variance swaps. **Everything this programme does is
therefore a distorted, path-dependent proxy for a volatility view, and every
result must be read with that distortion in mind.**

**The daily breakeven move** falls straight out of the identity: setting
½Γ(ΔS)² + ΘΔt = 0 and substituting Θ ≈ −½σ_imp²S²Γ gives

    ΔS_breakeven ≈ S · σ_imp · √Δt  =  S · σ_imp / √252  for a daily hedge.

The underlying must move more than that, on average, for a long-gamma book to
pay. It is the first screen on any candidate trade.

## 2. Why it loses on average, and what that leaves

Implied variance exceeds subsequent realised variance on average — the variance
risk premium. In the repo's own SPY data the ratio of implied to forward
realised variance has median **1.32** and mean 1.55.

**The best-verified external number, read from the primary paper:** Carr & Wu
(2009, RFS 22(3)), over five indices and 35 single names, Jan 1996 – Feb 2003,
find an average **log variance risk premium of −66%** on 30-day S&P 500 variance
swaps — i.e. *shorting* variance earned +66% on average — with annualised
Sharpe ratios on the short side of **0.98 (S&P 500), 0.85 (S&P 100), 0.87
(Dow)**. Note the asymmetry they also document: only **7 of 35 single names**
show a significantly negative premium in levels, against all three major
indices. **The premium is an index/systematic phenomenon far more than a
single-name one.**

> **An earlier version of this brief cited "an average synthetic variance-swap
> payoff of about −74% across ETFs including HYG" as the headline evidence.
> That figure could NOT be verified** (Aragon, Chen & Shi; authorship and AFA
> 2025 venue confirmed, but SSRN is bot-blocked and no abstract is indexed
> anywhere). **Do not cite it.** Carr & Wu above is verified and makes the same
> point more precisely. The credit-specific evidence is in §G6.

**So a systematic long-gamma book loses on average and wins in stress.** That
leaves exactly three honest jobs for it, and this programme is organised around
them:

1. **Insurance** — carry paid deliberately to remove a tail the main book
   cannot otherwise remove. Judged on the *combined* book's Calmar and worst
   months, never on the overlay's own Sharpe, which is expected to be negative.
   That is `W14_options.md`, in the CEF queue.
2. **A timed bet** — held only when something observable says realised will
   exceed implied. The evidence for any such signal is thin and mostly negative
   (§4); G6 ranks the candidates and G7 tests at most one.
3. **Learning and machinery** — greeks, hedging, rolls, expiries, a ledger that
   survives assignment. Real, valuable, and the only one of the three that is
   not conditional on a research result. G1–G5.

The side that *earns* the premium — selling volatility — adds to the same stress
exposure a credit mean-reversion book already carries. **This programme is
long-only in options by construction.** No prompt here may write an option.

## 3. What can be traded, and what the paper account can prove

**No CEF we trade has usable listed options.** Verified per-ticker 2026-09-09:
sixteen of the seventeen have no listed options market at all, including PDI and
PTY, the two most likely candidates by market cap. **DSL is a single exception, and its depth is now measured**: a real chain
across four expiries with strikes $2.50–$20 in $2.50 increments, but most
strikes carry 0–6 open interest and the most active line — the Nov-20 $12.50 put
— shows 83 OI, 80 volume and a bid/ask of $1.95/$2.50, a **~22% spread**. So it
is genuine and shallow: usable for one crude at-the-money observation, not for a
surface and not for a hedge. **PDI and PTY are confirmed not optionable** (Cboe's
options endpoint returns 403 for both; MarketBeat flags both "Not Optionable"),
which closes the two most plausible remaining candidates.

So every option trade happens in an ETF — and the liquidity is far more
concentrated than the listings suggest.

**The table below is one afternoon's snapshot from Cboe's delayed-quote chain
(2026-09-09), recorded so you know roughly what to expect. It is not a
qualification test.** G2 defines the actual screen — a minimum surviving-day
fraction measured over the whole sample — and an underlier either passes it on
your data or it does not. Re-pull the chain before committing to an instrument;
option liquidity migrates, and the JNK-versus-HYG gap below is exactly the kind
of thing that reverses when a product is relaunched or an index is re-licensed.

| ticker | weeklies | daily option volume | near-money spread | verdict |
|---|---|---:|---|---|
| **HYG** | **yes** (3 concurrent) | **367,197** | $0.09–$0.29 | **the only real credit-vol surface candidate** |
| TLT | yes (incl. Wed) | ~230,000 | $0.08 | excellent — rates, not credit |
| LQD | yes | 31,506 | $0.09–$1.45 | usable, materially thinner |
| EMB | **no** | thin | not observable | coarse ATM only |
| JNK | no | **20** | $0.30–$1.30, one-sided | **nominal — HYG took all the flow** |
| MUB | no | 168 (165P / **3C**) | wide | **effectively dead** |
| BKLN | nominal dates | 517, likely one block | **zero OI at every strike sampled** | dead |
| AGG | no | 66 | untradeable | dead |

**On that snapshot HYG was not merely the best choice but close to the only
one** — JNK traded 20 contracts against HYG's 367,000 despite a near-identical
basket, which is what extreme flow concentration looks like. **Treat that as the
shape of the problem, not as a fact about today.** The operative rule is G2's:
an underlier that fails the surviving-day screen on our own sample is not
tradeable for this purpose, whatever any snapshot said.

The institutional alternatives are out of reach, and one of them is deader than
expected. CDX payer swaptions are OTC and need ISDA documentation. **Cboe's
IBHY/IBIG options on iBoxx futures showed volume 0 and open interest 0 on
2026-09-09**, three years after listing, while the futures themselves trade
modestly (IBHY volume 436, OI 5,884). They are American-style and physically
settle into the futures, $1,000 multiplier, $0.01 tick — real contracts with no
market. Do not design around them.

**A free implied-vol series exists, and that is the durable fact here.** Cboe
publishes **VXHYG**, a VIX-methodology implied-vol index on HYG options, daily
since 2015-04-22, free and unauthenticated at
`cdn.cboe.com/api/global/us_indices/daily_prices/VXHYG_History.csv`. A companion
**VXIEF** covers IEF, and the CDS-based **VIXHY / VIXIG** reach back to
2012-03-05.

Levels observed on 2026-09-09 — around 6, a calm floor near 4, a COVID peak near
59 — are context, not calibration. **Pull the file, check its last-modified
header, and use what it says**; on that date VXHYG was current while VIXHY's
file was three weeks stale, and either can change. G2 uses these as anchors and
cross-checks rather than building an ATM level from scratch, and G2's acceptance
test is a *relationship* — our fitted ATM must track the published index — not a
level either of us wrote down.

**And the constraint that shapes every claim this programme may make: IBKR
paper trading fills options at the displayed price, from top of book, with no
market impact, and does not support penny-increment option fills.** Paper option
P&L is therefore systematically optimistic and **cannot establish that any
option strategy has positive expected value.** This is not a caveat to add at
the end of a note; it determines what G5 is allowed to conclude. The *share*
hedges are real execution evidence. The option legs are not.

## 4. Timing: what the evidence actually supports

If long gamma is to be a return engine rather than insurance, some signal must
predict realised exceeding implied. The literature, ranked:

| signal | evidence | verdict |
|---|---|---|
| **VRP's own level** (standardised trailing implied-minus-realised spread) | Bollerslev, Tauchen & Zhou 2009 RFS; Carr & Wu 2009 RFS; Bekaert & Hoerova 2014 | **Strongest.** The only candidate whose published predictive object *is* the quantity we care about |
| Variance term-structure slope / inversion | Simon & Campasano 2014 | Moderate; crowded; short useful horizon; the mirror short-vol trade blew up in Feb 2018 |
| Vol-of-vol | Huang, Schlag, Shaliastovich & Thimme 2019 JFQA | Moderate; genuinely priced factor, thin as a standalone trigger |
| Realised-vol level or trend (HAR-RV) | Corsi 2009; Andersen, Bollerslev & Diebold 2007 | Weak standalone — forecasts RV well, but implied re-prices with it, so the *spread* does not widen |
| Credit-spread widening as a vol lead | Cremers et al. 2008 (cross-sectional, not timing) | Weak; plausible mechanism, thin predictive evidence |
| Dealer gamma positioning (GEX) | practitioner origin; thin peer review | Weak to folklore; third-party estimates are noisy proxies for unobserved books |
| **Scheduled macro/earnings events** | **Goyal & Saretto 2009 (read in full)**; Ederington & Lee 1996 | **Folklore, and the evidence points hard the other way.** Sorting on the implied-minus-realised spread, the most "overpriced-IV" decile's straddles returned **−12.8% a month** and the 10−1 long-short straddle **+22.7% a month, monthly Sharpe 0.903** against the market's 0.131 (1996–2006). The documented edge is in *selling* into an implied run-up, not buying |
| CFTC VIX positioning | descriptive only | Folklore |

Two consequences, both binding on G6 and G7:

- **"Buy gamma into a known catalyst" is not supported and should not be
  pre-registered as a conditioner.** An earlier draft of the CEF-side options
  prompt proposed an event-calendar conditioner; the evidence contradicts it.
- **The structural counter-argument is strong, now quantified, and must be
  stated in every timing note.** Bollerslev & Todorov (2011, JF) decompose the
  variance risk premium and attribute **close to three-quarters of it (≈74%) to
  investor fears of rare events** rather than to diffusive variance risk — the
  left-tail component alone is 88.4% of the average premium against 14.8% for
  the right tail. They find the same for equities: the median jump/tail premium
  is 5.2% against a total equity risk premium near 8%, so **roughly two-thirds
  of the equity premium is tail compensation too.** If that is right, a
  signal that reliably predicted realised exceeding implied would be a signal
  that reliably predicted crashes — and would be arbitraged into option prices,
  collapsing the premium it was built to time. The premium survives *because*
  the timing is hard. A cheap signal we can compute is unlikely to be the one
  nobody else has found.

## 5. What the repo already has, and what is missing

Audited read-only, 2026-09-09.

**Exists:** an options *interface* — `PositionTarget` with an `OPTION` kind and
a `meta` dict carrying underlier/expiry/strike/opt_type/multiplier;
`DerivativesLedger`, which books, marks and charges option legs and correctly
excludes written premium from stock-borrow financing; `ibkr.py::_contract`,
which builds a real `ib_insync.Option`; `_place_combo` (line 1130) for
multi-leg orders; `margin.py`'s Reg-T-style option requirement;
`option_spread_model.py`, a VIX-keyed half-spread curve. And **data**:
`marks_SPY.parquet` (389,135 option trade prints, 2014-06 → 2026-07, 143
expiries), `marks_QQQ.parquet` (256,557), `atm_iv_daily.parquet` (14,770 rows,
SPY and QQQ only), `vix_daily.parquet`, `vrp_monthly.csv` and `vrp_series.parquet`.

**Missing, and each one is a prompt below:**

- **No option math of any kind.** No Black-Scholes, no Black-76, no implied-vol
  solver, no greeks. `src/deploy/lib/black76.py` does not exist and never has.
  The `iv` column in `atm_iv_daily.parquet` was produced by code that is not in
  this repo. → **G1**
- **No surface.** Trade prints only, no bid/ask, no fitting. → **G2**
- **No expiry, assignment or exercise handling anywhere in the ledger** — zero
  occurrences of the words. An option leg is marked forever by whatever
  `mark_fn` returns, and if `mark_fn` returns `None` past expiry **the ledger
  stops booking days entirely** rather than expiring the leg. → **G4**
- `greeks_fn` is threaded through six files and **never called**; `LegGreeks` is
  defined and never used. → **G4**
- Three live defects on the option order path: every BAG combo leg is submitted
  with `conId = 0` because `qualifyContracts` is never called; an option target
  with no `meta["limit_price"]` becomes a **limit order at $0.00**; and
  `src/deploy/sleeves/spy_shortvol_marks.py`, which `run_book.py:326` imports,
  does not exist. → **G4**
- `scripts/vrp/` (all extraction code) and `results/vrp/` are **gone**, so the
  pipeline that produced the SPY marks cannot be re-run and
  `attribution.py`'s VOL factor is unbuildable. → **G2, G4**

## 6. The counter, and the standard of proof

**GAMMA trials: 0.** Its own deflated-Sharpe bar √(2 ln N), separate from the
CEF counter. The combined book is judged on the joint record.

Two rules specific to this programme, beyond the house rules:

- **60 sessions decides mechanics, never P&L.** Lo (2002) gives
  SE(ŜR) ≈ √((1 + ½SR²)/T); at T = 60 even a true annualised Sharpe of 1.0
  cannot be distinguished from zero, and that is before the χ²-shaped skew of
  discretely-hedged P&L (§G3) widens it further. 60 sessions is also typically a
  single volatility regime. **Judge on cost discipline, decomposition accuracy
  and capture ratio; report P&L with its standard error and no verdict.**
- **Every volatility in this programme is computed by us**, from extracted
  marks, with a model we own and can re-run. **Never IBKR's model greeks or
  implied vols** — they need a subscription the paper account may not carry and
  they cannot be reproduced.

## 7. The queue

| # | prompt | what it settles | trials | depends on |
|---|---|---|---:|---|
| G1 | Option math: pricing, greeks, IV inversion | the model we own | 0 | — |
| G2 | The surface from trade prints | what "implied vol" means here | 0 | G1 |
| G3 | The hedging specification | how we hedge, and what benchmark grades it | 0 | G1 |
| G4 | Ledger, execution and the four defects | machinery that survives an expiry | 0 | — |
| G5 | The paper book | mechanics, honestly scoped | 0 | G1–G4, W2 |
| G6 | Realised vs implied in credit | whether a timing signal exists | 0 | G1, G2 |
| G7 | The timed sleeve and its budget | whether to trade it | 1 GAMMA | G6, G3, W10 Part C |

**Order: G1 → G4 → G3 → G2 → G6 → G5 → G7.** G1 and G4 are pure engineering and
unblock everything. G3 before G2 because the hedging specification determines
*which realised-volatility estimator is the correct benchmark*, and getting that
backwards invalidates G6's central measurement. G5 can start as soon as G1–G4
land and W2 says options are permitted; it runs alongside G6.

**Nothing in this programme starts until `results/ops/ACCOUNT_AUDIT_<date>.md`
says "options: permitted".** Long options and delta hedging need permission
level 2 plus stock permission; check the level, not just the flag.
