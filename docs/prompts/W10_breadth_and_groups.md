# W10 — Breadth: make seventeen names into more than one bet

**Reads first:** `00_BRIEF.md` §1 (the law), §2 (mechanisms M3, M4, M5), §3
(how these instruments trade), §5 (harness).
**Lever:** BR. The book's effective breadth is **1.17** today (2.24
historically) because 92.5% of its variance is one factor: municipal CEFs
against taxable ones. **This is the biggest hole in the strategy.**
**Trials:** up to 5 on the **CEF** counter — Part B is 0 (a decomposition),
Part C is 1, Part D is 1 per group tested (up to 4), Part E is 1, Part F is 1.
Count them as you spend them; do not run all of them.
**Prerequisites:** W1 (holdout protocol), W4 (the surviving IC — every baseline
below is measured against it), W8 Part E (borrow by group, for Part C's last
row).
**Supersedes:** P1.6, P6.1, P6.2, P6.3, P6.4, P6.8.

---

## Paste from here

You are a quant researcher on the QUANTT CEF book. Read
`docs/prompts/00_BRIEF.md`, then:

1. `docs/PLAN.md` §4.2 (PC2 is 65.7% of book variance historically; BR_eff 2.24
   of 17; *"the dollar-neutral construction kills market beta and then puts
   two-thirds of the risk into one unmanaged spread bet"*; **hard group
   neutrality was tested and lost gross Sharpe 0.97 → 0.82**, so the factor is
   partly compensated — an argument for sizing it deliberately, not hedging it
   away), §4.3 (screen on ticks, not ADV) and §7.2–7.3 (the 27 untouched names).
2. `dashboard/server.py::_decompose` and `curl -s :8787/api/factors`: today PC2
   is **92.5%**, BR_eff **1.17**, net muni weight **−74.9%**. The book is, today,
   one trade.
3. `docs/PER_NAME_ARCHITECTURE.md` §5 (the groups are different instruments
   with different holders) and §6 item 4 ("no group statistics on n = 1").
4. `results/cef/BORROW_NOTE_2026-09-06.md` (the muni shorts carry 91% of the
   borrow bill) and `results/cef/ESTIMATOR_NOTE.md` (the Kalman fair-value
   level lost to a plain 63-day window, which then failed out of sample on
   turnover — **a better unconditional level does not help; do not rebuild
   one**).
5. `data/cef/cef_universe.csv` (44 names, group, ADV, last price),
   `config/costs.yaml`, `scripts/cef/band_frontier.py`.

Six parts, in order. **B gates C. A gates E and F.** D and E may not run before
A's file exists.

---

## Part A — Open the 27, once, and never again like this (trial: 0)

The 27 untouched names (`cef_universe.csv` minus the frozen 17) are independent
of our selection process. They are consumed the moment any of them is traded.

**1. The tick screen first.** `min_adv_usd = $3m` binds hard: the median
eligible universe is 8 names. At $1m ADV, 37 names clear at 0.44%
participation. We do not move markets (0.7% of ADV at the live screen); **we
pay ticks.** A one-cent spread on a $4.69 share is 10.7bp against a 32.6bp
breakeven — a third of the edge in the minimum increment; on a $17 share it is
2.9bp. So the right screen is cost per unit of exposure, plus a participation
guard that ADV supplies at a much lower level than $3m.

`scripts/cef/tick_screen.py`, per name per date since 2005:
`half_spread_bp = 1e4·0.005/close` (state the convention); `adv_usd` = 63-day
mean of close × volume, shifted one day; `participation` at the strategy's
typical trade size; `nav_age` from the NAV panel. Cross-check the tick estimate
against W7 Part C's Corwin–Schultz spread panel and report where they disagree.

Eligibility, **derived not swept**: `half_spread_bp ≤ 32.6/3` (the minimum
increment may cost at most a third of breakeven — write down why a third and
not a quarter or a half: it is the point at which one tick of adverse rounding
on entry and exit together consumes two-thirds of the edge); `participation ≤
1%` (five times below the cost model's own 5% guard); `adv_usd ≥ $1m` as the
floor below which the close is too thin to print. Report the eligible count per
date under the old and new screens and which names change status.

**2. Then run the 27, once.** Build the 27-name universe and run the **current
live specification unchanged** (z 252, band 4.8%, vol target 6%, shift 2,
`min_names` 6, the new tick screen for eligibility) as its own book through the
harness. Record in `results/cef/HOLDOUT27_<date>.md`: gross, ann, vol, turn/yr,
hold, net@5/15/30, by era, fit and holdout, BR_eff, PC2 share, per-name
leave-one-out, IC at 2d/T+1 **and per-group IC** — the per-group within-name IC
is the baseline every group-specific signal in Part D must beat.

Rules for this step: **one run. No variants. Whatever it prints is recorded. Do
not read it before the script has written the file.**

---

## Part B — Decompose the alpha (trial: 0)

The signal demeans z across all 17 names. When the whole muni group richens
relative to taxables, every muni reads RICH and every taxable reads CHEAP, and
the demeaning turns that into a short-muni/long-taxable book. **Nobody chose
that trade or sized it; it is what falls out of one mean.** So the live book is
a mixture of two economically different bets:

- **Within-group selection** — which muni is rich against the other munis, which
  PIMCO fund is cheap against the other PIMCO funds. Many names, same holder
  base, same tax treatment, same leverage mechanics: the cleanest expression of
  M1.
- **Between-group timing** — munis as a class against taxables as a class. One
  bet, driven by muni/Treasury ratios, tax-loss seasons and leverage-cost
  shocks: M5, and it is where the borrow bill lives.

Nobody has measured how much of the edge each carries, what breadth each has,
or how correlated they are — so Part C cannot be designed, and no group signal
in Part D can be evaluated, because we would not know what baseline it competes
against.

### The decomposition, exact

With group `g(i)` and eligible set `E_t`:

    z_i = z̄ + (z̄_g(i) − z̄) + (z_i − z̄_g(i))

so the live demeaned signal `s_i = −(z_i − z̄)` splits into

    s_i = between_i + within_i,   between_i = −(z̄_g(i) − z̄),  within_i = −(z_i − z̄_g(i))

**Assert in code:** `Σ within_i = 0` within **every** group (the within book is
group-neutral by construction); `Σ between_i = 0` weighted by eligible counts;
`between_i + within_i = s_i` exactly, before any normalisation. A singleton
group (loan, JFR) has `within = 0` and is between-only; a group with fewer than
3 eligible names on a date is treated the same way, and the number of such
date-groups is reported.

### Three books, identical policy

Build weights from each component exactly as the sleeve does from `s_i`
(normalise to unit gross, vol-scale to 6% on the book's own trailing 63-day
realised vol, min-weight filter, band 4.8%) and score at shift 2: **WITHIN**,
**BETWEEN**, and **LIVE** (which must reproduce the band's 1.16 / 17.6 / 0.66 —
regression check). Also record per date the **implied mix**,
`Σ|between| / Σ(|between| + |within|)`, and its time series; expect it high
today.

### What to measure

1. **IC by component**, 2d/T+1, non-overlapping, full sample, by era, fit and
   holdout, with t-stats **computed the way W4 Part E prescribes** (clustered,
   not naive). For the between component also the **group-level** IC: rank the
   4 group mean z's against the 4 group mean forward returns; with n = 4 per
   date this is noisy, so report the pooled sign test and the mean over dates
   with a block-bootstrap SE.
2. **The harness table**, each book at its natural turnover and matched to
   17.6×/yr: gross SR, ann, vol, turn/yr, hold, net@5/15/30, borrow %/yr,
   net@15 − borrow, BR_eff, PC2 share.
3. **Correlation and attribution.** Daily return correlation between WITHIN and
   BETWEEN, full sample and by era. Regress LIVE's daily return on the two, no
   intercept; the coefficients times the component Sharpes say where LIVE's
   gross comes from. Report the share of LIVE's variance from each and from
   their covariance.
4. **Borrow by book.** Expect BETWEEN to carry nearly all of it and WITHIN
   almost none, because within-muni selection shorts one muni and buys another.
5. **The negative control.** Repeat with **random group assignments** (same
   group sizes, names shuffled, 20 draws). A random grouping's between
   component should have IC near zero and its within component should recover
   the live IC. If a random between component has a comparable IC, "group" is
   doing nothing and the real between IC is a size or sector artefact.
6. **Group-by-group within IC** — inside each group separately (muni 6, multi
   8, hy 2 which is a sign test).

Lead the write-up with three numbers — `IC_within`, `IC_between`, ρ — then the
tables, then the sentence Part C needs: *"X% of live gross Sharpe comes from
the between-group bet, which has effective breadth Y and carries Z% of the
borrow."* If `IC_between` is insignificant, the group bet is uncompensated risk
and the answer is group-neutral construction with the muni exposure sized to
zero — **which contradicts the 0.97 → 0.82 finding and must be reconciled**
before concluding (different sample? different policy? borrow not charged
then?). Write `results/cef/alpha_decomposition.json` for Part C to read.

---

## Part C — Two sleeves, two risk budgets (trial: 1)

The live book holds the two bets in whatever proportion one cross-sectional
mean produces — today about 90% between. The fundamental law says each deserves
capital in proportion to its information ratio `IR_k ≈ IC_k√BR_k`, and that two
bets with correlation ρ should be combined as a mean-variance portfolio of
sleeves, not summed. Hard group neutrality is the special case "budget for
between = 0", and it lost. The live book is the special case "budget = whatever
the demeaning gives". **Neither is a decision. This part makes it one.**

Two sleeves, identical policy (band 4.8%, shift 2, min-weight, tick screen):
**WITHIN** from `within_i`, vol target `v_w`; **BETWEEN** from `between_i`, vol
target `v_b`, **borrow charged by name** (this sleeve carries the muni shorts).
Combined book = the sum of the two weight vectors with the band applied to the
combined target; also report the two banded separately, which is a different and
slightly worse construction.

**The budget split, derived.** Treat the sleeves as assets with Sharpes
`IR_w`, `IR_b` — use Part B's measured **net-of-borrow** Sharpes at matched
turnover, not the gross — and correlation ρ:

    (v_w, v_b) ∝ (1/(1−ρ²)) · (IR_w − ρ·IR_b,  IR_b − ρ·IR_w),
    subject to v_w² + v_b² + 2ρ·v_w·v_b = (6%)²

Show the arithmetic with Part B's numbers. **If `IR_b − ρ·IR_w ≤ 0`, the
between bet gets zero budget**, the answer is group-neutral construction, and
the 0.97 → 0.82 reconciliation must be written before concluding. **Do not
sweep the split** — it is derived once. Report a ±50% sensitivity on `v_b` for
the reader; the decision is at the derived point.

Harness, full sample, by era, fit and holdout, matched to 17.6×/yr:

| book | gross | turn/yr | net@5 | net@15 | net@30 | borrow %/yr | net@15 − borrow | BR_eff | PC2 share | net muni wt (mean, p95) |
|---|---|---|---|---|---|---|---|---|---|---|
| LIVE band 4.8% | 1.16 | 17.6 | 0.99 | 0.66 | 0.17 | 1.22 | 0.43 | 2.24 | 65.7 | |
| WITHIN only (v_b = 0) | | | | | | | | | | |
| TWO SLEEVES, derived split | | | | | | | | | | |
| TWO SLEEVES, v_b ±50% | | | | | | | | | | |
| TWO SLEEVES, between via cheapest-to-borrow only | | | | | | | | | | |

The last row is W8 Part E's asymmetric construction: express the between bet's
short side only in the group's cheapest-to-borrow names, longs unchanged. Also
report the time series of the between sleeve's gross — it should be *stable* by
construction, where the live book's between share swings with the demeaning —
and each sleeve's drawdown profile.

**Decision rule.** Adopt if, at matched turnover, net@15 − borrow improves over
LIVE by ≥ 0.05 with net@30 not worse, BR_eff rises by ≥ 1.0, the improvement
holds in at least four of five eras, and the holdout agrees in sign. If
WITHIN-only wins, that is the answer and the earlier neutrality finding is
superseded with the reconciliation written. **If nothing beats LIVE, record it:
the accidental mix was near-optimal, which is itself a finding.**

Spec key `construction: "band" | "two_sleeve"` with `two_sleeve: {v_within,
v_between, rho_used, source: alpha_decomposition.json@<hash>}`; absent = band,
no-op proven. Readout: realised between-sleeve gross share and PC2 share over
40 armed sessions. **Do not size the between sleeve on the spread's z level** —
that is dislocation sizing, measured to lower Sharpe. Its budget is a constant
derived from IC and BR.

---

## Part D — A conditional fair value per group (trial: 1 per group, up to 4)

> **⚠ SUPERSEDED 2026-09-09 by `perfund/F2_group_forms_fund_params.md`.** F2
> fits the same four group forms but lets each fund's *slope* coefficients be
> per-fund and shrunk within its group, rather than pooling them across the
> group with only a name fixed effect. **This Part D is F2's special case with
> every shrinkage weight set to zero**, and F2 runs it as one of its three
> variants (pooled / shrunk / unpooled) so the comparison is made rather than
> assumed. Run F2, not this. It is kept here because F2's conditioner list,
> its negative controls and its decision rule all originate in this section and
> a reader should see where they came from.
>
> **Parts A, B, C, E and F of this prompt stand unchanged.**


### The idea, and the trap

The live fair value is the 252-day rolling mean of the fund's own discount. A
muni CEF's *true* fair discount moves when the muni/Treasury ratio moves, when
its financing cost moves, and in tax season. The rolling mean sees all of that
as dislocation and trades against it for months. A conditional level
`θ_g,t = a_g + b_g'·x_g,t−1` absorbs it, and the residual is the part that is
actually noise-trader dislocation.

**The trap:** this is the Kalman argument with a different estimator, and the
Kalman lost — because a fast-adapting *unconditional* level is just a shorter
window, which trades more. A *conditional* level is different only if the
conditioners carry information the rolling mean does not. That is the thing to
test, and the negative control (feed a group the wrong group's conditioners) is
what tells the two apart.

### Get the financing conditioner right — it is per-sponsor machinery, not per-group

This is where the repo's group structure earns its keep, and where two earlier
drafts of this work were wrong: the first used one base rate for everyone, and
the second assumed the muni group was homogeneous. **It is not. Verified
2026-09-09 against `cef_facts.csv`: the six muni names are four Nuveen (NAD,
NEA, NVG, NZF) and two BlackRock (MQY = BlackRock MuniYield Quality, MHD =
BlackRock MuniHoldings).** They do not lever the same way, so they do not share
a financing conditioner.

- **Nuveen munis** lever primarily through **tender option bond trusts**: a
  fixed-rate muni is deposited in a trust that issues a floater to money-market
  funds and a residual retained by the fund. **The floater resets to the SIFMA
  Municipal Swap Index** — tax-exempt, reset **weekly and published Wednesdays
  by 4pm ET**, structurally below taxable short rates. Fetch it reproducibly
  from sifma.org with a source note; **SOFR is a fallback and must be labelled
  as one**. Its weekly step is a feature to align on, not to smooth away.
- **BlackRock munis** lever predominantly through **preferred shares** (VRDP /
  MFP / RVMTP structures) rather than TOB trusts, with a different reset
  mechanism and a different sensitivity to the same rate move. **Do not pool
  them with the Nuveen four on a single SIFMA coefficient.** Read each fund's
  actual structure out of its latest N-CSR leverage note before assigning a
  conditioner, and if a fund's structure cannot be established from a filing,
  it inherits the pooled treatment **explicitly in code**, never silently.
- **PIMCO multi-sector** levers through **reverse repo** — 18–42% of managed
  assets in recent filings at roughly 6.3% effective cost. Its conditioner is a
  taxable repo/SOFR rate.
- **Asset coverage is a hard constraint, not a preference:** §18(a) requires
  ≥300% coverage for debt and ≥200% for preferred, so a large NAV drawdown
  forces deleveraging mechanically.

**Leverage type and ratio are a required control, and they are observable.**
N-PORT's `fundInfo` block carries `totAssets`, `totLiabs`, `netAssets` and
`liquidPref` — the preferred-share liquidation preference, which is the
preferred-leverage stack read directly (NAD's most recent filing shows
$1.6026bn). Bank and credit-facility borrowings appear as
`amtPay{OneYr,AftOneYr}{BanksBorr,...}`, split by maturity and counterparty.
**The leverage *type label* and the reset benchmark are prose only** — they live
in the N-CSR "Notes to Financial Statements → Leverage" section and must be
parsed from text. F1 builds this panel; consume it here rather than
re-deriving it, and **do not use `cef_facts.csv`'s `totalDebt` or
`debtToEquity` for this**: that file is a single undated snapshot fetched
2026-07-31, so using it across a 27-year panel is a look-ahead error.

### The conditioners, pre-declared per group, written down before running

**muni** (6 in the 17; 10 in the 27): muni/Treasury relative value = 21-day
return of a national muni ETF minus IEF — **fetch MUB and PZA into the ETF
panel via `refresh_market_feeds.py` with a source note; the panel has no muni
ETF today, and never hand-copy a series**; leverage cost = 63-day change in
SIFMA; tax-season indicator = a November–January dummy; group NAV momentum =
trailing 63-day mean NAV return of the muni group.

**hy** (2 in the 17; 4 in the 27): credit spread proxy = 21-day HYG − LQD;
credit sentiment = 21-day HYG return; equity vol = 21-day change in VIX.

**multi** (8 in the 17 — PDI PTY PDO PCN PHK PFN are PIMCO, DSL DoubleLine, BIT
BlackRock; state that the group is mostly one family): family co-movement = the
mean z of the *other* PIMCO funds excluding the name itself; premium
persistence = the group's trailing 252-day mean premium; financing = 63-day
change in the repo/SOFR rate; distribution-coverage proxy = UNII per share over
the distribution **if** PIMCO's monthly coverage report can be fetched
reproducibly, otherwise omit and say so. **Never hand-enter.**

**loan** (1 in the 17; 6 in the 27): SOFR level and 63-day change; 21-day BKLN
or SRLN return. Estimate on the six loan names in the 27 only; JFR inherits the
pooled treatment, explicitly in code.

Each conditioner carries a **stated sign expectation** (e.g. muni cheapening →
muni discounts wider → negative coefficient on d). A fitted coefficient with the
wrong sign is a flag, reported, never silently used.

### The construction, no lookahead

Per group, on a trailing 504-session window ending *t−1*, refit monthly:
regress each name's discount on the group conditioners lagged one day with a
name fixed effect, `d_i,s = a_i + b_g'·x_g,s−1 + e_i,s`; conditional fair value
`θ_i,t = â_i + b̂_g'·x_g,t−1`; conditional dislocation `u_i,t = d_i,t − θ_i,t`;
z on `u` with its **own** trailing 252-day sd (shift 1), clip ±4. **The mean is
already removed by θ — do not demean again with a rolling mean or you have
rebuilt the live signal plus noise.** Everything downstream unchanged.

Alignment assertions on every window and lag. Report the fitted `b_g` with
signs and t-stats per era, and the R² of the conditioners in explaining the
discount level per group. **If R² is under 5%, the conditioner set is weak and
the result will be noise — say so before the IC test.**

### The tests

1. **The 27 first** (Part A's file must exist). The 27 include an **emd** group
   (EDD EMD EDF TEI MSD) which gets no conditioners and is the negative control
   receiving the pooled level. Per group: IC of the conditional z vs the live z,
   2d/T+1, non-overlapping, by era, with the difference and its SE. Recorded
   before the 17 are touched.
2. **The 17**, same IC table by group, then the harness turnover-matched with
   the conditional level applied to the groups that passed on the 27 and the
   live level elsewhere.
3. **The negative control:** feed each group the *other* groups' conditioners.
   If the IC improvement is similar, the gain is from a smoother level, not
   information, and the group-signal claim fails.
4. **Post-cut behaviour:** the mean conditional z of cut funds at t+21, t+63,
   t+126 after a distribution cut, against the live z's −0.286 / −0.341. A
   conditional level that still reads cut funds as cheap for six months has not
   solved the thing the Kalman was built for.

**Decision rule, per group.** Adopt if, on the 27, its IC beats the live IC by
more than 2 SE and the negative control does not; the same sign holds on the 17;
the whole-book harness shows net@15 and net@30 not worse at matched turnover;
and the holdout row agrees in sign. **Each group tested is one trial regardless
of outcome.** Groups that fail keep the rolling mean. Spec key
`level_model: {"muni": "conditional_v1", ...}`, absent = rolling mean.

---

## Part E — Group seasonality, pre-registered once (trial: 1 for the whole run)

**This is the third and last pass at seasonal data** unless it passes; two prior
passes failed.

### What is known, and what contradicts it

Pooled across 44 CEFs, January discounts narrow **+7.71bp/day** (t 11.75) and
September widens −4.74; December −8.72bp/day (t −3.24). A hedged January basis
trade earned Sharpe 2.94 while on, 20/23 Januaries, **correlation −0.001 with
the deployed book** — because the book is dollar-neutral and cross-sectional, so
a move that hits every fund cancels.

The literature is specific: **Starks, Yong & Zheng (2006, JF 61:3049)** document
tax-loss selling and the January effect in **municipal** CEFs, held almost
entirely by tax-sensitive retail, and find the pattern **more pronounced in
funds affiliated with brokerage firms**. Six of our seventeen are Nuveen munis.

But a rough single pass during the 2026-09-07 review (2010+, the 17, mean daily
discount change in bp/day) found the January narrowing sitting in the **PIMCO
multi** group, not the munis, with the muni seasonal in **November**:

| group | Jan | Jul | Sep | Nov | Dec |
|---|---:|---:|---:|---:|---:|
| multi | +10.5 | +3.0 | −9.6 | +1.8 | −6.0 |
| muni | +0.1 | +4.5 | −3.4 | +5.5 | −0.3 |
| hy | +1.1 | −0.4 | −4.4 | +1.7 | −0.8 |
| loan | +3.9 | +0.8 | +0.2 | +6.5 | +1.3 |

That contradicts the literature's mechanism. It was a rough pass; it is not a
finding; **it is exactly the kind of pattern a pre-registered test exists to
check.**

### The confound that must be removed before anything is tested

PIMCO funds pay large **year-end supplemental distributions** in December. So:
exclude ex-date days and the day after from every seasonal mean, and report each
mean **with and without** the exclusion so the reader sees how much was
mechanical. Note that W4 Part A establishes the true size of the ex-date effect
on the *discount* (small, because NAV drops too) — quote its measured
coefficient here rather than assuming the effect is large or is zero.

### Pre-register `PREREG_SEASONAL_<date>.md` BEFORE running anything

Hypotheses, one per group, each with its mechanism:

- **muni:** tax-loss selling widens discounts in Oct–Nov and they narrow
  Nov–Jan. **Mechanism checks, both required:** December volume is elevated
  relative to the year in muni names; and the January narrowing is larger after
  years in which the group's price return was negative (more losses to harvest)
  — a dose-response test. **Add the affiliation test** the literature suggests:
  split the muni names by whether the sponsor has a captive retail distribution
  channel and test whether the effect is stronger there.
- **multi:** December widening and January narrowing **survive the ex-date
  exclusion**. If they do not, the effect is distributions, not flow, and the
  hypothesis is rejected for this group. Second prediction: September widening,
  mechanism unknown, stated as such — **a result without a mechanism is
  recorded but not adopted.**
- **hy:** September widening. Same status as multi's September.
- **loan:** November narrowing; n = 1 in the 17, so test on the six loan names
  in the 27 only.

**The test:** per group and window, the mean daily discount change in-window
minus out-of-window, Newey–West t with 21 lags, on the **27 first**, then the
17, 2005–2026, by decade, and fit/holdout. Plus the year-by-year sign so a
single year cannot carry it.

**The decision rule:** a group's seasonal is adopted **only as a conditioner in
Part D** (a window dummy in `θ_g,t`), **never as a standalone overlay in the
live book**, and only if p < 0.01 on the 27, the same sign on the 17, survival
of the ex-date exclusion, and — for muni — the mechanism checks passing. One
trial for the whole run.

**The January basis sleeve, separately:** recompute the hedged January basis
**by group** (long the group's CEFs, short the matched ETF basket — munis vs
MUB/PZA, HY vs HYG/JNK, multi vs a HYG/LQD blend — at a rolling 252-day hedge
ratio), with the same robustness rows the July note ran. Report which group
carries it. **Do not deploy it here**; if it holds by group it is a separate
pre-registration for next January with its own trial.

---

## Part F — Add names that dilute the dominant factor (trial: 1)

Depends on Part A's `HOLDOUT27` file existing.

### The 27, by group

| group | in the 17 | in the 27 |
|---|---|---|
| muni | 6 | NXP, VMO, VKQ, MFM, NAN, PMM, NIM (count from the csv) |
| multi | 8 | PFL, BGB, DBL |
| hy | 2 | EAD, GHY, ISD, DHY, HIO, BGH |
| loan | 1 | VVR, FCT, BGT, EFR, EFT, BSL |
| emd | 0 | EDD, EMD, EDF, TEI, MSD |

The **emd** group is a fifth kind of fund with its own driver (EM sovereign and
corporate spreads, currency), a holder base overlapping high-yield retail, and
NAVs that may lag because of foreign holdings and time-zone pricing. It is not
in the live book at all. HY and loan are thin in the 17 and rich in the 27. The
additions that raise effective breadth are the ones that make the book less than
92% one factor, and those are **non-muni by construction**.

**Know what you are shopping in.** The traditional CEF universe has shrunk for
twelve consecutive years — 427 funds at end-2022 to 402 at end-2023, down about
36% since 2011 — with negative net share issuance and no new launches in 2023.
The candidate pool is not replenishing, which is an argument for taking breadth
where it exists now, and a caution that any name added may itself be a merger
candidate. Cross-reference W1 Part C's dead-fund list before promoting anything.

1. **Eligibility from Part A's tick screen**, per date, for all 27. Report each
   name's median half-spread bp, ADV, NAV-age distribution (**emd names in
   particular: what fraction of sessions is the NAV a day late?**), and borrow
   fee — extend `fetch_borrow_rates.py` to pull the 27 too; it is one file.
2. **Candidate sets, group-balanced, by a stated rule not a search.** For target
   sizes 3, 5, 8: rank eligible non-muni names by median half-spread ascending
   and take them in order, subject to at most 2 per group per step. Also build
   the muni-inclusive comparison set under the same rule so the reader sees the
   contrast.
3. **Evaluate** each set as the 17 plus the additions, live policy unchanged,
   matched to 17.6×/yr: n, median eligible/day, gross, turn/yr, net@15, net@30,
   net of borrow, BR_eff, PC2 share, mean half-spread bp, emd NAV-lag days/yr,
   fit and holdout.
4. **The frontier.** Plot BR_eff against mean half-spread for every set; the
   promotion is the point where BR_eff stops rising faster than cost.
5. **emd specifically:** the IC of the live signal on the five emd names alone,
   their NAV timing, and whether their addition changes PC1's reading (a sixth
   factor could appear as a new PC2). If emd NAVs are routinely a day late they
   fail `max_nav_age_bd` and are excluded honestly.

**Decision rule.** Promote the smallest set that raises BR_eff by ≥ 1.0 and
lowers PC2 share by ≥ 15 points at matched turnover, with net@15 and net@30 not
worse than the 17 alone, the additions' median half-spread no worse than the
live median, and the holdout agreeing in sign. Update `UNIVERSE` in the frozen
spec **and** in `band_frontier.py` together. Falsifier: BR_eff below the
17-only book after 20 sessions, or any added name failing NAV age on more than
10% of sessions.

**Record that promoting names consumes the 27 as a comparison set**, and list
the remaining names as the new holdout.

---

## Deliverables

- `scripts/cef/tick_screen.py`, `alpha_decomposition.py` (+ its JSON),
  `two_sleeves.py`, `group_fair_value.py`, `group_seasonality.py`,
  `breadth_groups.py`; the fetch additions (MUB, PZA, SIFMA, VIX) with source
  notes; leverage type and ratio added to `cef_facts.csv`.
- `HOLDOUT27_<date>.md` (written before Parts D–F run),
  `ALPHA_DECOMPOSITION_<date>.md`, `TWO_SLEEVES_<date>.md`,
  `GROUP_FAIR_VALUE_<date>.md` (27 first, 17 second),
  `GROUP_SEASONALITY_<date>.md`, `BREADTH_GROUPS_<date>.md`.
- Pre-registrations for whatever is adopted; the CEF counter bumped by the
  number of trials actually spent, itemised.

## Do not

- Do not run Parts D–F before `HOLDOUT27_<date>.md` exists.
- Do not sweep the tick threshold, the ADV floor, the budget split, or φ.
- Do not search over subsets in Part F; the rule picks the set.
- Do not normalise the components in Part B in a way that changes their sum.
- Do not pool the loan singleton into another group; it is between-only, stated.
- Do not add a conditioner in Part D after seeing a result, and do not use
  per-name coefficients on conditioners — the group pools, the name gets a
  fixed effect only.
- Do not use a smoother (future data) anywhere; the level at *t* uses data to
  *t−1*.
- Do not adjust a seasonal window after seeing a result, test months that were
  not pre-registered, or adopt a September effect with no mechanism, however
  significant.
- Do not add a name that fails the NAV-age rule "because it is cheap".
