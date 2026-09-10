# G2 — The surface from trade prints: what "implied vol" is allowed to mean here

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `G0_BRIEF.md`, `G1_option_math.md` (this prompt inverts with
that module), `00_BRIEF.md` §6.
**Settles:** the implied-vol series every later prompt compares realised against.
**Trials:** 0. **Touches the live book:** no.
**Run after G1 and G4.** G3 should be read first — the hedging frequency
determines which realised-vol estimator this surface is benchmarked against, and
getting that backwards invalidates G6.

---

## Paste from here

You are a quant researcher on the QUANTT book. Read `docs/prompts/gamma/G0_BRIEF.md`,
then:

1. `data/vrp/` in full. `marks_SPY.parquet`: 389,135 rows, columns
   `date, expiry, opt_type, strike, px, sz, n`, 2014-06-02 → 2026-07-10, 143
   expiries, 947 strikes. `marks_QQQ.parquet`: 256,557 rows, same schema.
   `atm_iv_daily.parquet`: 14,770 rows, `ticker, date, expiry, dte, T, iv, F, K,
   n5_min, straddle` — **SPY and QQQ only**.
   **Note that `marks_SPY_full.parquet` is a duplicate of `marks_SPY.parquet`**
   — identical except for 129 `px` values differing by ≤ 5.7e-14, which is
   float round-trip noise. Pick one, delete or archive the other, and say which
   in the note; carrying two "sources" that differ in the fourteenth decimal is
   how a reconciliation bug is born.
2. `data/vrp/costs_vrp.yaml` and its caveat, in full: *"the $0.02 option
   half-spread is an ASSUMED conservative floor, NOT a measured spread.
   Trades-only data cannot confirm the true bid/ask, so every net-of-cost result
   is GROSS of the real option spread."* **There is no bid or ask anywhere in
   this dataset.** Every price is a trade print.
3. `data/vrp/_extract_SPY.log` — 146 lines, one per month, recording the
   extraction that produced the marks. **The script that wrote it is gone**
   (`scripts/vrp/` does not exist), and the final line points at the pre-move
   repo path. So the pipeline cannot currently be re-run, which is why Part D
   exists.
4. `src/deploy/lib/option_spread_model.py` — the VIX-keyed half-spread curve
   (anchors: VIX 20 → $0.02, VIX 40 → $0.25, VIX 80 → $1.00, floor $0.02, cap
   $1.00). This is the repo's existing model of what the spread *would* be. It
   is a model, not a measurement.

---

## Part A — What a trade print is not

A trade print is not a mid. It is a transaction at someone's bid or someone's
ask, so the implied vols inverted from a strike's prints are **bimodal around
the true mid**, with the spacing between the modes being the spread. Every
statistic computed from raw print-implied vols inherits that, and averaging
does not fix it unless buys and sells arrive in balanced proportion — which
they do not, systematically, near events.

Four screens before anything is fitted, each with its rejection count reported:

1. **Liquidity.** The existing `n5_min` column is the shape of this screen —
   understand exactly what it counts before reusing it, and state the definition
   in the note rather than inheriting it silently.
2. **Staleness and off-market prints.** A print far from the neighbouring
   strikes' implied vols, or timestamped away from the rest of the day's
   activity, is more likely a legged multi-leg trade or a size accommodation
   than a fair single-leg market.
3. **Arbitrage bounds.** Any print outside intrinsic-plus-time-value bounds is
   rejected outright; `implied_vol` already returns `None` there (G1).
4. **Wing sparsity.** Restrict the *fit* to the region where prints are dense
   enough to mean something and let the parameterisation extrapolate the wings.
   Fitting a far strike from two prints and calling the result a vol is how a
   surface acquires a spike.

**Get the forward right before inverting anything.** Do not assume a discount
rate and a dividend yield. Use **put-call parity on the most liquid ATM pair per
expiry** to back out the implied forward and discount factor, then invert every
other strike against those. A wrong forward tilts the whole inverted skew and
will look like a real skew signal.

**And use the American pricer.** G1 establishes that these are American options
on monthly-distributing ETFs and that a European inversion misprices ITM strikes.
The surface must be inverted with `american_binomial` (or its closed-form
approximation), with the actual ex-dividend schedule.

---

## Part B — Fitting

Fit in **total implied variance against log-forward-moneyness**, per expiry
slice, with **SVI** (five raw parameters `a, b, ρ, m, σ` controlling level,
slope, curvature and skew). Then enforce no-arbitrage explicitly, using the
conditions in Gatheral & Jacquier (2013), *Quantitative Finance*, "Arbitrage-free
SVI volatility surfaces":

- **Butterfly** (within a slice): the implied risk-neutral density must be
  non-negative — equivalently the call price is convex in strike. State the
  parameter condition you implement and **assert it after every fit**.
- **Calendar** (across slices): total implied variance must be **non-decreasing
  in maturity** at matched log-forward-moneyness. Assert it pairwise across the
  fitted expiries.

For the surface as a whole, use **SSVI**, which ties the slices' parameters to a
common shape and enforces the calendar condition surface-wide by construction.
For thin names, fit in **delta space** rather than strike space so skew is
comparable across tenors, use a **robust loss** (Huber or median) rather than
least squares so bid/ask-bounce outliers do not drag the fit, and regularise a
thin expiry toward its neighbours — or, for JNK/EMB, seed the shape from HYG's
fitted surface — rather than fitting it independently.

**A fit that violates either arbitrage condition is a failure, not a
warning.** Raise, log the expiry and the violated condition, and leave that
slice out of the surface with a reason. Do not ship a surface with a negative
density in it.

---

## Part C — Extend to credit and rates

The existing `atm_iv_daily.parquet` covers **SPY and QQQ only**. The programme
needs **HYG** above all, then **TLT**, then LQD; MUB and BKLN are almost
certainly too thin, and **finding that out is a result worth writing down**,
because it bounds what can ever be hedged.

Extract HYG, LQD, TLT (and MUB if the source carries it) by the same path that
produced `marks_SPY`, and build `atm_iv_daily` rows for each with the **identical
method and the identical liquidity screen**, so the credit series is comparable
to the equity one. Then extend `vrp_monthly.csv` and `vrp_series.parquet` so
`rich_ratio` — implied variance ÷ forward realised variance — exists for credit
as it does for equity, with **G3's benchmark estimator** in the denominator.

**Report how many days survive the screen, per ticker.** That count is the
finding. If LQD survives on 40% of days it is not a tradeable vol instrument for
us, whatever its nominal listing says.

### Start from the free series, not from zero

**Cboe already publishes a VIX-methodology implied-vol index on HYG options.**
Verified live 2026-09-09:

| series | what | history | endpoint (free, unauthenticated) |
|---|---|---|---|
| **VXHYG** | HYG **ETF option** implied vol | 2015-04-22 → **2026-09-09**, 1,913 rows, current | `cdn.cboe.com/api/global/us_indices/daily_prices/VXHYG_History.csv` |
| VXIEF | IEF ETF option implied vol | 2015 → current | same path, `VXIEF_History.csv` |
| VIXHY | **CDX HY** index-option vol | 2012-03-05 → 2026-08-14, 3,682 rows | same path, `VIXHY_History.csv` |
| VIXIG | CDX IG index-option vol | 2012-03-05 → 2026-08-14 | same path, `VIXIG_History.csv` |

VXHYG's range is informative on its own: a calm floor near **3.7–4.0** against a
COVID peak of **59.26 on 2020-03-23**, currently 6.13.

**This reorders the work.** The ATM level for HYG does not need to be built from
trade prints — it exists, free, daily, back to 2015. So:

1. **Use VXHYG as the anchor and the acceptance test.** Fit the surface from
   prints, then compare your fitted 30-day ATM implied vol against VXHYG on the
   same dates. **A persistent gap is a bug in the fit, not a finding.** Report
   the distribution of the difference; that is the cheapest and strongest
   validation available and it costs one CSV download.
2. **G6's base-rate measurement can start immediately** against VXHYG rather
   than waiting for the surface — realised close-to-close variance against
   VXHYG-implied gives a `rich_ratio` for HYG back to 2015 today.
3. **The surface is still needed** for what VXHYG cannot give: skew, term
   structure, and per-strike greeks for an actual position. Build it, but build
   it knowing the level is already checkable.
4. **Note the freshness trap.** VXHYG was current on 2026-09-09; **VIXHY and
   VIXIG were last modified 2026-08-16** and may be lagging by weeks. Check the
   file's last-modified header before treating any of these as live, and log the
   check — a stale vol index silently poisons every ratio computed from it.

The CDS-based VIXHY/VIXIG measure **spread** vol rather than ETF **price** vol,
so they will not match the ETF surface and are not meant to. **The divergence is
itself the interesting quantity** (Part E) — it is the cleanest available read on
how much of HYG's option-implied vol is wrapper noise rather than credit risk.

---

## Part D — Rebuild the pipeline that is missing

The extraction script is gone and `results/vrp/` with it, which means the SPY
marks cannot currently be reproduced and `src/deploy/lib/attribution.py`'s VOL
factor — which reads `results/vrp/refute_tail_ledger_SPY.csv` — is unbuildable.

Reconstruct `scripts/vrp/extract_option_marks.py` from the log's evidence: it
looped month by month over a remote source, accumulating trade prints into one
parquet, with per-month wall times of 0.8–31.3 seconds and row counts that track
volatility (2020-03 spikes to 7,222 rows against a ~2,000 baseline). Parameterise
it by ticker so HYG/LQD/TLT run through the same code. **Write its provenance
into the module docstring** — which source, which fields, which date range —
because the current situation, where a 389k-row dataset has no reproducible
origin, is exactly what the house rules exist to prevent.

Also fix the two stale-path defects the audit found while you are here:
`exec_ledger.py:770` lazily imports `src/deploy/v2/odd_lot`, but the module is
at `src/deploy/lib/odd_lot.py`; and `run_book.py:326` imports
`src/deploy/sleeves/spy_shortvol_marks`, which does not exist. Both are latent
`ModuleNotFoundError`s on paths nothing currently exercises.

---

## Part E — The one genuinely open question

HYG is a wrapper over illiquid bonds and **it has its own basis to NAV**. Under
normal conditions it carries a persistent premium of roughly 0.25%, an artifact
of NAV being struck off stale bid-side marks rather than a mispricing. Under
stress the basis blows out: investment-grade corporate bond ETFs averaged a
**3.4% discount to NAV in mid-March 2020, with some exceeding 8%**, and HYG's
own average absolute stated premium/discount rose from 0.21% in January–February
2020 to 1.06% in March–April.

**So a gamma scalper long HYG is long the variance of the wrapper, which
includes basis noise that is not in the underlying bond market.** That cuts two
ways and the desk should know which:

- **The edge case.** The ETF price-discovers continuously while the OTC bond
  market marks stale, so some of HYG's extra realised variance is *genuine
  information arriving early* — a real risk premium a gamma position could be
  paid for.
- **The trap.** Some of it is creation/redemption friction and AP inventory
  noise: whipsaw a delta-hedger eats without directional follow-through. And
  option market-makers hedge the actual ETF, not its NAV, so they have plausibly
  already priced it into HYG's implied vol — leaving no edge unless the basis
  noise is *time-varying in a predictable way*.

**Measure it rather than arguing about it.** Decompose HYG's realised variance
into the part explained by a matched bond-index or CDX-implied move and the
residual basis component; test whether the residual is predictable (concentrated
around outflow days, month-end, index roll); and compare HYG's implied vol
against VIXHY to see whether the ETF surface prices the basis or ignores it.
**Report it as a hypothesis with a measurement, not as a conclusion** — no paper
found in the research settles it, and it is the most interesting open question
in this programme.

## Deliverables

- `scripts/vrp/extract_option_marks.py` (parameterised, documented provenance),
  `scripts/vrp/build_surface.py` (screens, parity forward, SVI/SSVI fit,
  arbitrage assertions).
- `data/vrp/atm_iv_daily.parquet` extended to HYG/LQD/TLT (+MUB if it survives),
  `surface_params.parquet` (per ticker, date, expiry: the fitted parameters,
  the fit residual, the rejection counts, the arbitrage-check results), and
  `vrp_monthly.csv` / `vrp_series.parquet` extended to credit.
- `results/gamma/SURFACE_<date>.md`: the screen rejection table, days surviving
  per ticker, the arbitrage-violation log, the VIXHY/VIXIG overlay, and Part E's
  basis decomposition. Plus the duplicate-marks decision and the pipeline's
  restored provenance.

## Do not

- Do not treat a trade print as a mid.
- Do not assume a forward; derive it from parity on the liquid ATM pair.
- Do not invert an ETF option with a European model.
- Do not ship a slice that violates a butterfly or calendar condition.
- Do not fit a far strike from a handful of prints; extrapolate instead and say
  so.
- Do not present any net-of-cost option result as anything but **gross of the
  real option spread**, since the data cannot establish it. Report at the
  1× / 2× / 3× floor multipliers the cost file already declares.
- Do not mix regenerated implied vols with the legacy `atm_iv_daily` rows unless
  G1's test 6 says they are compatible.
