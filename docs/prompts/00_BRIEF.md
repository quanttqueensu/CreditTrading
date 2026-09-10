# The standing brief

**Every prompt in this directory opens by reading this file.** It holds what
they all share — the theory of the edge, the mechanisms, how these instruments
actually trade, the scoreboard, the harness, the house rules, and the standing
decisions — so that no prompt repeats it and every prompt can cite it by
section.

Written 2026-09-07 from a full read of the repo and the live dashboard;
Section 3 added 2026-09-09 from sourced market research; consolidated from 51
prompts to 14 on 2026-09-09.

---

## 1. What "finding alpha" means for this book

The book earns its return through one relation, Grinold's fundamental law, in
the form Clarke, de Silva & Thorley (2002, FAJ) generalised:

    IR ≈ IC · TC · √BR

- **IC**, the information coefficient: how well the signal ranks tomorrow's
  returns. Ours is **−0.074 (t −11.6)** at the traded 2-day / T+1 horizon over
  27 years, in every sub-period, stronger out of sample than in. The repo has
  measured many times that sharpening it is the least productive place to work
  (price reversal adds +0.1%; the Kalman lost to a shorter window; per-name
  kappa lost to pooled). **But see W4: the IC has never been tested against the
  three mechanical effects that produce exactly this signature, and every
  number below is conditional on that battery.**
- **BR**, breadth: the number of *independent* bets per year. We hold 17 names
  and pretend that is 17 bets. It is not. On the live weights the book has an
  effective breadth of **1.17** today (2.24 historically), because 92.5% of its
  variance is one factor: municipal CEFs against taxable ones. Qian & Hua
  (2004) is the reference for why nominal position count is never breadth when
  forecasts are cross-sectionally correlated. **This is the biggest hole in the
  strategy.**
- **TC**, the transfer coefficient: how much of the ideal book we actually hold
  after costs, borrow, availability, rounding and missed sessions. Gross Sharpe
  near 1.2 becomes 0.10 net on the old calendar and 0.43 on the band once borrow
  is charged — a TC of about **37%**, against the 0.3–0.8 range Clarke et al.
  report as typical for constrained portfolios. **This is the capture problem
  and the highest-value work per hour.**

So "finding alpha" here has three distinct meanings, and every prompt says which
one it is doing:

1. **Raise BR** without lowering IC — make seventeen names into more than one
   bet (W10).
2. **Raise TC** — trade less, trade cheaper, short what can be borrowed, size to
   the right volatility, never send an order the strategy did not ask for, and
   measure execution fast enough to act on it (W5, W7, W8, W11, W12).
3. **Add a genuinely new IC source** only where a *mechanism* says one should
   exist and the current signal is provably blind (W10, W13, W14).

---

## 2. Where alpha comes from in closed-end funds

Before any test, name who is on the other side and why they stay there.

| # | mechanism | who loses, and why they keep doing it | horizon | status |
|---|---|---|---|---|
| M1 | **Discount mean reversion.** Retail sentiment moves price; NAV is the anchor; nothing arbitrages the gap because the share count is fixed and there are no APs (Lee, Shleifer & Thaler 1991; Pontiff 1996) | Retail holders who buy yield and sell losses, at whatever price | days to weeks | **Live.** IC −0.074, pending W4 |
| M2 | **Stale NAV.** Munis and loans are matrix-priced; the published NAV lags true value (Getmansky, Lo & Makarov 2004; Choi, Kronlund & Oh 2022) | Nobody — it is measurement error we can remove, or an artefact we are mistaking for alpha | days | NAV autocorrelation 0.388, unmodelled → W4 §C, W13 |
| M3 | **Seasonal retail flow.** Tax-loss selling into year-end, reversal after (Starks, Yong & Zheng 2006, in *municipal* CEFs specifically) | Tax-motivated retail — not stupid; the tax value exceeds the price concession | dated, weeks | Pooled January measured (+7.7bp/day). Group split untested → W10 §E |
| M4 | **Group-level fair value.** A muni fund's fair discount moves with the muni/Treasury ratio and its SIFMA-linked leverage cost; a HY fund's with spreads; a PIMCO fund's with its repo cost and its own premium regime | The z-score reads a fair-value shift as a dislocation and trades the wrong way for months | weeks to months | Untested as a *conditional* level → W10 §D |
| M5 | **The group spread itself.** The muni-vs-taxable discount spread reverts; the book is short it at whatever level the demeaning produced | The same retail base, at sector level | weeks | Taken by accident at 92.5% of risk. Never sized → W10 §B, §C |
| M6 | **Corporate events.** Tenders, rights offerings, mergers, open-endings, activist 13Ds move a discount to a known level on a known date | Boards that resist activists; holders who sell before the tender | dated | Not staged. Calendar only → W9 Stage 3. **Regime change: see §3** |
| M7 | **Distribution policy.** Cuts re-rate a fund permanently; the rolling mean takes a year to notice | Yield-screening retail | months | Tested twice, failed at a 2-day hold. **Do not rebuild** |
| M8 | **Fund health / price level.** Low-priced CEFs have eroded capital through return-of-capital; higher-priced funds revert better AND cost fewer ticks | Yield chasers in eroded funds | — | Measured +0.16 net in July, "Adopt", **never deployed** → W11 §D |
| M9 | **Volatility state.** Discounts widen together in credit sell-offs and revert fastest afterwards; the options market prices tomorrow's volatility today. Two uses: a *hedge* (long gamma pays exactly then, but costs the variance risk premium every other day) and *information* (a band width and vol target that know a shock is on) | Nobody, for the hedge — it is insurance, priced rich. For the information use: the book's own lagging estimates | days to weeks | Unmeasured on the CEF book → W14 |

---

## 3. How these instruments actually trade

Sourced facts about the products themselves. Every claim here is either a
primary source or is flagged. Prompts cite this section rather than restating
it.

### The wrapper

A traditional CEF issues a fixed share count at IPO and **never creates or
redeems**. There is no authorized-participant mechanism, which is why the
discount persists and why nothing closes it mechanically. It is also why the
**lendable pool cannot grow with short demand** (§ below).

At end-2023 there were **402 traditional CEFs, down from 427 a year earlier —
a twelfth consecutive annual decline, about 36% below 2011** — with negative net
share issuance for a second year and no new launches. The universe we are
shopping in is shrinking, which matters for breadth (W10 §F) and for
survivorship (W1 §C).

**62% of traditional CEFs use leverage**, at an average structural leverage
ratio around 28% (bond funds 29%). The 1940 Act §18(a) requires **≥300% asset
coverage for debt and ≥200% for preferred**, so a large NAV drawdown forces
deleveraging *mechanically*. Leverage type differs by group and is a required
control, never something to average away:

- **Nuveen munis** lever through **tender option bond trusts** — a fixed-rate
  muni deposited in a trust that issues a floater to money funds and a residual
  to the fund. **The floater resets to the SIFMA Municipal Swap Index**, which
  is tax-exempt, resets **weekly (published Wednesdays by 4pm ET)** and trades
  structurally below taxable short rates. S&P put average fund-sponsored TOB
  leverage at ~2.5× in Dec 2023, rising to ~3.32× by Q2 2024.
- **PIMCO multi-sector** funds lever through **reverse repo** — 18–42% of
  managed assets in recent filings, at roughly 6.3% effective cost.
- For reference, Sept 2026: SOFR 3.65%, EFFR 3.63%.

### NAV: what it is, when it appears, and how stale it is

Rule 22c-1's forward-pricing mandate applies to **redeemable** securities and
therefore **not to CEFs at all**. Daily NAV striking is strong industry
convention reinforced by exchange norms, not a clean statutory daily
requirement. Nuveen's prospectus language is representative: NAV "determined as
of the close of trading (normally 4:00 p.m. Eastern time) on each day the NYSE
is open". **No sponsor documents a public posting time**, which is why the
evening decision was a race we did not control (W3).

Municipal bonds are **matrix-priced**. The MSRB reports fewer than 2,800 muni
trades a day across fewer than 1,500 unique securities against more than a
million CUSIPs outstanding, with two-thirds of the securities that trade at all
trading once or twice. Nuveen's own registration language says the pricing
service values a bond from *"yields or prices of municipal securities of
comparable quality, type of issue, coupon, maturity and rating"* — a curve, not
a trade. Bank-loan funds use dealer-quote surveys. Choi, Kronlund & Oh (2022,
JFE 145(2):296–317) find bond-fund NAVs "extremely stale" with returns
predictable over days to weeks, worse in crises; Cici, Gibson & Merrick ("Missing
the Marks", JFE) find cross-fund dispersion in month-end marks on *identical*
bonds, so part of the smoothing is **discretionary**, not mechanical.

**Rule 2a-5** (compliance 8 Sept 2022) moved fair-valuation to a board-overseen
"valuation designee" at each adviser. A family's smoothing profile can change
without announcement — and our time holdout begins 2023-01-01, immediately
after.

**CEFConnect italicises a NAV whose published date is earlier than the row's
date.** Capture the NAV's own as-of date, never just its value.

**Bond-market holidays on which the NYSE trades** — Columbus/Indigenous Peoples'
Day, Veterans Day — produce a mechanical discount swing every year: price moves,
NAV carries forward stale. W4 §C decides how the panel treats them.

### Ex-distribution arithmetic — and a correction

On the ex-date the distribution leaves the fund's assets, so **NAV drops too**,
not just price. With both falling by *D*, a discount `(P−N)/N` becomes
`(P−N)/(N−D)` — for a 10% discount and a 0.75% monthly distribution, about
**7bp**, not the 75bp earlier notes in this repo claimed. Bali & Hite (1998)
find the realised price drop is slightly *less* than the distribution because of
tick discreteness. **Earlier prompts asserting that an ex-date "moves price and
not NAV" were wrong; W4 §A measures the real coefficient and corrects every
string.**

2023 traditional-CEF distributions were 67% income, 13% capital gains and **20%
return of capital** — which is the substance behind M8. Managed distribution
policies need an SEC exemptive order under §19(b)/Rule 19b-1 and covered about
32% of traditional CEFs in 2024, concentrated in multi-strategy and equity
funds rather than credit — so in our universe a distribution cut is more likely
to reflect real income degradation than a smoothing-policy choice.

### The secondary market and the closing auction

Our names run from about $3m a day (JFR) to $43m (PDI) in dollar ADV. We do not
move markets at the live screen (0.7% of ADV); **we pay ticks** — a one-cent
spread is 10.7bp on a $4.69 share and 2.9bp on a $17 share, against a 32.6bp
breakeven.

#### The tick convention — defined once here, cited everywhere else

**Added 2026-09-10, resolving W0 Part F.** Three documents quoted three
different numbers for PHK's tick and none stated its convention, so they read as
a dispute. They are three different quantities:

| quantity | PHK | what it is |
|---|---:|---|
| **half-tick** | 10.65bp | half a cent on $4.69 — `docs/PLAN.md` §4.1 |
| **full tick** | 22.22bp | one cent on $4.51 — `docs/PER_NAME_ARCHITECTURE.md` §4 |
| **charged half-spread** | 25.77bp | `config/costs.yaml`, **1.25× the full tick**, and that multiplier holds for all 17 CEFs |

**The ledger charges 25.77bp — 2.4× what PLAN's prose implies.** So:

- **State the convention wherever a tick figure appears.** A bare "PHK's tick is
  X" is ambiguous and has already been read three ways.
- **The number that enters a cost calculation is the charged half-spread**, from
  `config/costs.yaml`, because that is what the ledger actually applies.
- **The 1.25× multiplier is itself an assumption**, not a measurement. `W7` Part C
  measures spreads independently; if it disagrees with the yaml, the yaml is
  wrong and every net figure computed from it moves.

Per **H14**, do not key a rule on the numbers in this table — re-read
`config/costs.yaml` and say which convention you used.

**The auction rules differ by venue, and getting them from one fact sheet is how
you end up with a wrong specification.** Verified against rule text 2026-09-09:

**NYSE** (where the CEFs trade). MOC/LOC must be entered by **15:50 ET** — the
"Closing Auction Imbalance Freeze Time" of Rule 7.35(a)(8), defined as ten
minutes before the end of Core Trading Hours, so **it moves with early closes**.
After it, only orders opposite a published Regulatory Closing Imbalance are
accepted, and if none was published all are rejected. **MOC/LOC may not be
cancelled or reduced after 15:50 "even to correct a legitimate error"** — the
only carve-out needs a Trading Official's approval. The Regulatory Closing
Imbalance publishes when it is **500 round lots or more (50,000 shares)** under
Rule 7.35B(d)(1), and — correcting an earlier version of this brief — **it is
published once, at 15:50. It does not refresh.** NYSE also retains **DMM
discretion**: a DMM may close a security without a trade, or run the auction
manually.

**Nasdaq** (where TLT trades, so the gamma hedge lives here). **MOC until 15:55,
LOC until 15:58**, IO until 16:00, with cancel/modify frozen from 15:50. Its
NOII **does** refresh — every 10 seconds from 15:50, then every second from
15:55 — with no share threshold gating it. No DMM.

**NYSE Arca** (HYG, LQD, SPY): Rule 7.35-E is parallel in architecture but
**its cutoff and threshold could not be verified** and vendor sources only
suggest parity with NYSE. **Confirm before routing.**

Our clips are one to three orders of magnitude below 50,000 shares, so we never
register as a published imbalance. NYSE's **Closing IO Order** (Rule
7.31(c)(2)(D)) is limit-only and auction-only and, unlike MOC/LOC, may be entered
on **both** sides up to 16:00 — note NYSE is amending this order type now
(SR-NYSE-2026-36, implementation by Q1 2027).

Closing auctions matched **$55.5bn a day, 9.44% of US notional, in Q2 2024**.
And the number that matters for a thin CEF: **about 3.3% of NYSE auction volume
goes unfilled, rising to 6.3% for non-Russell-1000 names** — which is what all
seventeen of ours are.

**No CEF-specific bid-ask, quoted-depth or closing-auction-share dataset exists
publicly.** These must be measured from our own fills and quote history (W7).

### The short side

CEF borrow is structurally thin for a reason that will not improve: the share
count is fixed, only fully-paid and excess-margin shares are loan-eligible, and
only where the holder has opted into a lending programme (IBKR's requires a
margin account or a cash account with liquid net worth above $25,000). **The
marginal CEF holder is a retired retail income investor in a cash account —
precisely the holder whose shares are not in the pool.** Hence NAD's 3,000
visible lendable shares against our 8,129 short.

**⚠ That last number is now disputed and must be re-measured before any
availability work (2026-09-10).** The retired public file and TWS **tick 236**
were believed to report the same exact-share figure. On the first day both
could be compared they did not:

| | we short | file (09-08) | tick 236 (09-10) | |
|---|---:|---:|---:|---|
| NAD | 6,550 | **3,000** | **83,942** | 28× |
| NVG | 4,679 | 20,000 | 149,125 | 7× |
| MHD | 8,856 | 250,000 | 102,491 | 0.4× |
| NZF | 271 | 150,000 | 275,577 | 2× |

On the file's numbers 18.7% of today's short book is unbuildable; on the API's,
**0%**. The entire premise of the availability cap turns on which is right, and
one observation two days apart cannot settle it — the two could be measuring
different things (indicative pool vs currently-shortable, and whether shares
already lent to us are netted out). Until W8 Part A resolves it with a week of
paired observations, treat "11.4% of the short book is unbuildable" as
**unverified**, and do not size a cap on either number. Tick 236 only answers
when no other client session is holding market data — it returned NaN under
error 10197 all morning, which is why the comparison had never been made.

IBKR's public file (`shortstock/usa.txt`) was retired on 2026-09-09 (404; the
ftp hosts do not answer). The fee now comes from the API's FEE_RATE bars —
which also carry five years of history (H4); availability comes only from
TWS tick **236** returns the same exact-shares figure while legacy tick 46 is a
coarse bucket. The fee accrues as **market value × fee rate ÷ 360**, with market
value marked up to **102%** of the prior settlement price — not the ÷252 on the
raw close our harness uses (W8 §A).

**Recall is monthly, not occasional.** Every one of the 17 distributes monthly.
A lender whose shares are on loan through a record date receives a payment in
lieu, which is ordinary income — never a qualified dividend and, for a
**municipal** fund, never the exempt-interest dividend the holder bought the
fund for. Tax-sensitive muni lenders therefore have a standing monthly incentive
to recall before the record date. A discretionary recall requires two trading
days' notice; thirteen consecutive days on the Reg SHO threshold list forces a
mandatory buy-in at the start of T+14.

**We are not alone on the short side.** Alexander & Peterson (2017, *Journal of
Financial Markets*) find CEF short-selling rises with the premium and that
heavily-shorted funds see the premium decline over the following **five days** —
our horizon. FINRA publishes short interest twice monthly for all listed
securities, free, about seven business days after settlement.

### Corporate events, and a 2026 regime change

Saba, Karpus and Bulldog drove about 90% of 2023 CEF activist actions and held
stakes in **44% of all traditional CEFs** at end-2024. Across 34 funds with
activist-forced tenders 2015–2022, excess discount versus peers averaged −4.4%
the year before the initial 13D, narrowed to −1.2% pre-tender and −0.2% during
the tender, **then widened back to −3.3% the year after** — the effect largely
round-trips within a year, and 75% of activists fully exit within a year (48%
within three months). Bradley, Brav, Goldstein & Jiang (2010, JFE) found
successful open-endings cut discounts to roughly **half** their original level.

**But on 11 June 2026 the Supreme Court ruled unanimously that §47(b) of the
1940 Act creates no implied private right of action**, narrowing the activist
litigation toolkit against control-share provisions. Historical
activism-driven convergence should not be assumed to repeat at the same rate.

Two mechanics worth knowing precisely: **SEC staff require a CEF tender to be
priced at NAV as of the close of the tender's last day** — a dated, NAV-priced
convergence event, and being short into one is a known, avoidable loss. And
rights-offering subscription prices are commonly set at about 90% of the average
close over the expiration date and four preceding sessions, over a ~30-day
period; **transferable versus non-transferable is the field that matters**,
because non-transferable rights force mechanical dilution on non-participants.

### Who runs these funds

Verified 2026-09-09 against `cef_facts.csv`. **Do not infer the sponsor from the
group** — the muni group is two sponsors with two different leverage mechanisms,
and an earlier draft of this brief got it wrong.

| sponsor | names |
|---|---|
| Nuveen | NAD, NEA, NVG, NZF (muni, **TOB / SIFMA**), JFR (loan) |
| BlackRock | **MQY, MHD (muni, preferred: VRDP/MFP)**, BIT (multi), HYT (hy) |
| PIMCO | PDI, PTY, PDO, PCN, PHK, PFN (multi, **reverse repo**) |
| DoubleLine | DSL (multi) |
| AllianceBernstein | AWF (hy) |

### Options

**No CEF we trade has usable listed options** — verified per ticker, not
assumed. Sixteen of seventeen have no listed options market at all, including
PDI and PTY, the two most likely by market cap. **DSL is a single exception**: it
appears in two independent options-analytics platforms' optionable universes,
but its depth is unverified and must be checked on a live broker chain before
anyone relies on it. For scale, business development companies (ARCC, PSEC) *do*
have options while large plain equity CEFs (ADX, UTF) do not — the gate is
order flow, not fund structure.

Whatever we do with options therefore happens in HYG, LQD, TLT, JNK or SPY. **Only HYG is genuinely usable** as a
credit-vol instrument; JNK, LQD, MUB, EMB and BKLN list options with materially
thinner books, TLT is the rates-vol venue, and the institutional alternatives
(CDX payer swaptions; Cboe's IBHY/IBIG options on iBoxx futures) are out of
reach from this account.

Long gamma pays the variance risk premium. Implied runs 1.3–1.5× realised in
the repo's own SPY data; the premium is documented in credit as well as equity;
and in the one study that includes HYG the average synthetic variance-swap
payoff across the ETFs examined was about **−74%**. A systematic long-gamma book
**loses on average and wins in stress.**

**IBKR paper fills options at the displayed price, from top of book, with no
market impact**, and does not support penny-increment option fills in paper.
Paper option P&L cannot establish that any option strategy has positive expected
value (W14 §C).

Basis risk is real: in March 2020 CEF discounts widened by more than 1,600bp
while HYG's own price-to-NAV deviation reached −5% to −8% intraday and its
average absolute stated premium/discount rose from 0.21% to 1.06%.

### One honest gap

**There is essentially no academic literature validating a CEF discount-reversion
signal at a 1–5 day horizon.** Pontiff (1995, JFE) finds a 20%-discount fund
earns about 6pp more over *twelve months*; Ji (2013) estimates reversion at
8.6%/month, a **7.7-month** half-life. Our pooled AR(1) φ = 0.9722 implies 24.6
days — an order of magnitude faster. Being novel is allowed. Being novel and
untested against bid-ask bounce, stale NAV and ex-date arithmetic is not, which
is why **W4 runs before any further trial is spent.**

---

## 4. The scoreboard

The numbers the capture work moves. Each is measurable faster than P&L.

| goal | live today | target / reference | how measured |
|---|---|---|---|
| Capture ratio, net ÷ gross Sharpe | 0.43 / 1.16 = 37% | 0.90 / 1.33 = 68% (joint optimiser, modelled) | band_frontier |
| Turnover | 17.6×/yr expected; realised unknown | below 31.1 within 20 armed sessions (pre-registered) | broker fills only |
| Cost robustness | net@5bp 0.99, net@30bp 0.17: never flips | never flips | harness, 5/15/30bp |
| Turnover stability, era sd/mean | 11.9% (band) vs 36.9% (joint) | ≤ band's | harness by era |
| Borrow drag | 1.22%/yr on today's fees (**understated: PIMCO names cost 13–30%/yr to borrow 2021–23**); 3.62% on today's book | cut by shorting different names; re-measure on `cef_borrow_history.parquet` first | cef_borrow_history.parquet |
| Availability | **disputed, 2026-09-10** — 18.7% of today's short book unbuildable on the retired file's pools, **0% on TWS tick 236** (NAD 3,000 vs 83,942). Do not act on either until W8 Part A pairs them | 0% unbuildable | tick 236 + FINRA; the public file is gone |
| Effective breadth | **1.17** today, 2.24 historical | ≥ 4 | /api/factors |
| Execution | 2.8bp (1 MOC session), 120.6bp (abandoned method) | below 32.6bp breakeven, SE < 1bp after 60 sessions | shortfall log |
| Uptime | armed 3 of 26 sessions | every trading day, or an alert | heartbeat |
| Dust | 0 (fixed 2026-09-08) | 0 | /api/trades |
| Return convention | price returns, distributions missing | total returns | W4 §A |

---

## 5. The harness, and the rules every research prompt inherits

Do not build a new backtester. Use the canonical one and extend it visibly.

```python
from scripts.cef.band_frontier import build_targets, band, calendar, evaluate
T, R = build_targets()          # frictionless daily targets as the sleeve builds them
H_live = band(T, 0.048)         # the live policy
H_old  = calendar(T, 2)         # the previous configuration
res    = evaluate(H, R)         # applies H.shift(2): decide t, MOC fill t+1, earn t+2
```

**H1.** Execution convention is **shift(2)**. Anything scored differently is not
comparable to any number in the repo.

**H2. Turnover-matched comparisons only.** A construction that trades more looks
better gross and worse net; neither is the point. Find the band width or cost
coefficient that matches the reference's turn/yr within 5% and compare there.

**H3. Cost grid 5 / 15 / 30bp** on every table, and where W7 §C exists, the
measured per-name per-era column beside it. The answer must not flip sign across
the grid.

**H4. Borrow is charged separately and labelled.** Since 2026-09-10 the fee is
a **daily series, by name, 2021-09-13 onward**: `data/cef/cef_borrow_history.parquet`
(43 of 44 names, 52,978 rows; FCT has none), from IBKR
`reqHistoricalData(whatToShow="FEE_RATE")`, built by
`scripts/cef/fetch_borrow_history.py`. Charge the actual daily fee over
2021–26; before 2021-09 there is no fee data — use the 2021–26 mean by name
and label those rows an assumption. "One day of fees applied to history" is
no longer the method. **The history is not benign:** the PIMCO premium funds
averaged PTY 29.7% (max 178%), PFN 19.7%, PHK 16.6%, PCN 13.8%, PDO 13.4% to
borrow over 2021–26 against 0.3–1% today, so every net-of-borrow figure in
this repo computed on today's fees (the 1.22%/yr drag included) is suspect
until re-measured on the panel.

**H5. Eras:** 2005–09, 2010–14, 2015–19, 2020–22, 2023–26. Pre-2013 is thin.
Report era turnover sd/mean.

**H6. IC** is Spearman between the signal at *t* and the forward 2-day return
starting *t+2*, **non-overlapping**, expected negative, with standard errors
clustered by date (W4 §E), never naive.

**H7. No lookahead.** Every estimated quantity uses data strictly before the
date it is used on; state the alignment in a comment; assert it at runtime.

**H8. No sweeping and picking.** Derive parameters, then check they land on a
plateau. Picking the argmax of a swept column is how `z_window=63` was chosen,
and it failed out of sample.

**H9. The 27 untouched names** are the comparison set. Any specification change
is run on them once, on the combined spec, before promotion. **Trading any of
them consumes the set.**

**H10. Count trials.** Two counters, each with its own deflated-Sharpe bar
√(2 ln N): **CEF** (48 after the band) and **GAMMA** (0). Every prompt says
which it increments. The combined book is judged on the joint record.

**H11. Pre-register before the session that trades it.**
`results/cef/PREREG_BAND_2026-09-06.md` is the shape. Every adoption names the
live statistic and horizon that would reverse it.

**H12. Negative controls.** If a mechanism says an effect lives in munis, test
it in HY too. If it is equally strong where the mechanism cannot operate, it is
not what you think.

**H13. Time holdout.** Every estimated quantity is fitted on data before
**2023-01-01**; every table shows a fit row and a 2023–2026 holdout row.
Derived quantities are computed on the fit period and applied unchanged.
Rolling estimators are fine on the holdout; what is forbidden is *choosing*
anything with sight of 2023–26. The 27 remain the second check, and if the two
disagree, the spec is not adopted and the disagreement is written up.

**H14. No decision rule may key on a number written in these documents.**
Every figure in this brief and in the prompts — measured, fetched or cited — is
a **starting observation with a date and a method**, recorded so you know what
to expect and can tell quickly if something has changed. **None of them is an
input to a decision.** A prompt's rule must re-measure the quantity it keys on,
at run time, from data, and must state what it does under either outcome.

This applies to our own measurements as much as to the literature. A borrow
panel two days old, an option chain snapshotted on one afternoon, a variance
decomposition run on a panel that ends six weeks ago, an era table computed
before the return convention was fixed — all of these go stale, and several
already have. **If a prompt reads "X is 59.6%, therefore do Y", it is wrong and
should read "measure X this way; if it is high, Y follows; if not, Z."**

The test to apply when writing or reviewing a prompt: *could this rule still be
executed correctly by someone who deleted every number from the document?* If
not, the rule is resting on a number instead of on a method.

**H15. Returns are total returns** once W4 §A lands. If the distribution panel
cannot cover a name-date, the harness **raises**; it never falls back to price
returns silently.

---

## 6. House rules for code

- **No silent fallbacks.** Never `except: pass`, never `fillna` an invented
  value, never a default for missing data. Raise, naming what was missing.
- **A new frozen-spec key must default to current behaviour**, and the no-op
  must be *proved* by diffing sleeve output byte-for-byte with the key absent.
- **The dashboard is read-only.** One POST route (`/api/connect`). No code path
  from the dashboard transmits an order.
- **Order type stays MOC** unless a pre-registered A/B changes it.
- **`launch_job.py` lives outside the repo** on purpose (macOS TCC). Do not move
  it.
- **Docstrings explain why.** Incident history lives in them.
- **Modelled sessions are not evidence.** Only broker-confirmed fills count
  toward any live statistic.
- **Never hand-copy a data series.** Anything fetched gets a fetcher and a
  source note.
- **The frozen spec is the only authority on a live parameter. Read it; never
  hardcode it.** The rule stands; the defect it was written about is gone.
  Four analysis scripts once baselined against `band(T, 0.064)` — the 6.4%
  width the book left behind on 2026-09-06 — so every comparison they produced
  was against a book that is not live, and **nothing about it errored or looked
  wrong.** **Fixed 2026-09-10** (`0b74658`, `9409762`, `666fab9`): all five scripts now import `BAND_WIDTH` from `scripts/cef/spec.py`, which reads the frozen spec, and tests hold it shut. Before extending any analysis script, check every
  parameter it hardcodes against `ops/specs/cef_discount.frozen.json`, and fix
  by *reading the spec*, not by editing the literal. A script that deliberately
  *sweeps* a parameter is fine and should say so in a comment — `grep -n
  '0\.064' scripts/cef/*.py` returns seven literals and all seven are of that
  kind. **Re-run the grep; do not trust this count.**

---

## 7. Standing decisions (team lead, 2026-09-08)

| question | decision |
|---|---|
| Universe | **Keep the 17.** They already are the liquid set (median $5.6m ADV). The 27 are the illiquid tail. Liquidity enters as a tilt (W11 §D), not a cut. |
| Gamma scalping's role | **Both** a hedge overlay judged on the tail and a timed standalone sleeve — W14 §A decides which survives. |
| Intraday scalping | **Research first** on PDI/PTY (W13 §C). MOC stays live; nothing intraday trades without its own pre-registration. |
| Decision timing | **Morning primary, evening fallback** (W3): 08:30 on yesterday's complete pair, MOC for today's close; 12:00 retry; 17:30 capture. From Thursday 2026-09-10. |
| Price source | **IBKR daily bars primary, yfinance cross-check.** |
| NAV source | **Free channels only:** yfinance X-tickers, CEFConnect dated history, sponsor first-party. Agreement to the cent, or the name is incomplete. |
| Options data | The R2 trades source if it carries HYG/LQD/TLT; QuantConnect research (results only) if not. |
| Gamma timing conditioners | **All three in one pre-registered run.** Adopt at most one. |
| Gamma sleeve size | **Derived, Σ⁻¹·IR** against the CEF book. May be zero. |
| Holdout | **Keep the 27 and add a 2023–2026 time holdout** to every fit. |
| Trial counters | **Two**: CEF and GAMMA, each its own bar. |
| Risk controls | **Arm HALVE/KILL on broker-confirmed NAV** once W6 §A lands. |
| Capital | **Paper indefinitely; a competition track record.** No real capital planned. |
| Judged on | **Absolute return.** Derive the vol target, **cap 20%**, with kill-probability and margin-cushion constraints. |
| Options permission | **Unknown** → W2 audits it first; every options part refuses to start without "permitted". |
| Other books | **Keep the five benchmarks; retire the null trader.** |

### Added 2026-09-09

| question | decision |
|---|---|
| Per-fund treatment | **Seventeen sleeves, one combined book.** Each fund gets its own signal, band, budget and P&L line; they sum into one portfolio where neutrality, borrow and capacity are managed at book level. → `perfund/F3` |
| Signal structure | **Model form by group (four mechanisms), parameters by fund shrunk within group.** Four trials, not seventeen. → `perfund/F2` |
| What neutrality means | **Undecided by design.** Four candidate rules are pre-declared and tested as one grid; the tie-break is p95 net exposure, not Sharpe. → `perfund/F3` Part B |
| Gamma scalping | **A standalone programme with its own counter and track record** (`gamma/`), **and** the hedge-overlay use case kept in the CEF queue (`W14`), gated on stress-beta evidence. |
| Sources | Every external claim lives in **`docs/REFERENCES.md`** with a verification status. Prompts cite it; they do not re-derive it. |

---

## 8. The queue

Three tracks. The **CEF book** (`W*`) is the live strategy. The **per-fund
architecture** (`perfund/F*`) rebuilds how it makes decisions. The **gamma
programme** (`gamma/G*`) is a second strategy with its own counter; see
`gamma/G0_BRIEF.md`, which every prompt there opens with.

### CEF book

| # | prompt | lever | trials | touches live book |
|---|---|---|---:|---|
| **W0** | **Repo hygiene: stale parameters, broken references, stale panels** | reading cost | 0 | two import fixes |
| **W0b** | **Deploy the prod/dev split — designed, written, never deployed** | operational risk | 0 | **yes, human-gated** |
| W1 | Inference protocol: holdout, counters, statistics, survivorship | inference | 0 | no |
| W2 | Account audit and book hygiene | prerequisites | 0 | retires the null trader |
| W3 | Session architecture: morning decision, data independence, alerting | TC, reliability | 0 | **yes** |
| **W4** | **The artifact battery: is the −0.074 IC real?** | subtraction | 0 | return convention only |
| W5 | Order integrity and the session journal | record | 0 | ledger + log |
| W6 | Risk governance: arm the controls, then size the book | governance | 0 | spec keys, decision memo |
| W7 | Cost and turnover measurement | measurement | 0 | no |
| W8 | Borrow, carry and capacity | TC | ≤2 CEF | pre-registered |
| W9 | The dashboard | ops | 0 | no |
| W10 | Breadth: decomposition, sleeves, group signals, additions | BR | ≤4 CEF | pre-registered |
| W11 | The policy layer: bands, conviction, turnover controller, tilt | TC | ≤2 CEF | pre-registered |
| W12 | The joint optimiser: derive c, structure Σ, shadow it | TC + BR | 0, 1 at promotion | shadow only |
| W13 | NAV quality and the horizon question | IC / M2 | ≤2 CEF | pre-registered |
| W14 | Options: stress beta, the convexity overlay, vol as information | M9 | 1 CEF, 1 GAMMA | own ledger |

### Per-fund architecture

| # | prompt | lever | trials | touches live book |
|---|---|---|---:|---|
| F1 | The characteristics panel: what is knowable, and when | data | 0 | no |
| F2 | Four group forms, seventeen parameter sets | IC | ≤4 CEF | pre-registered |
| F3 | Seventeen sleeves, one book, and what neutrality means | BR | 1 CEF | **yes**, pre-registered |

**F2 supersedes W10 Part D**, which is its special case with every shrinkage
weight zero. W10's other parts stand.

### Gamma programme (own counter)

| # | prompt | settles | trials |
|---|---|---|---:|
| G1 | Option math: pricing, greeks, IV inversion | the model we own | 0 |
| G2 | The surface from trade prints | what implied vol means here | 0 |
| G3 | The hedging specification and its benchmark | how we hedge, how it is graded | 0 |
| G4 | Ledger, execution, and four live defects | machinery that survives an expiry | 0 |
| G5 | The paper book | mechanics, honestly scoped | 0 |
| G6 | Realised vs implied in credit | whether timing exists | 0 |
| G7 | The timed sleeve and its budget | whether to trade it | 1 GAMMA |

### Order

**W0 → W0b → W1 → W2 → W4 → W3 → W5 → W7 → W6 §A → W9 Stage 1 → F1 →
W8 → W10 §A/§B → W9 Stages 2–4 → W11 → W12 → F2 → W10 §C/§E/§F → W13 → F3 →
W6 §B.**

**W0 first** because it is an hour, because two of its items are live bugs on
the order path, and because every prompt after it reads code and documents that
currently contain seven dangling references and two unacknowledged
contradictions.

The gamma programme runs beside that, not inside it:
**G1 → G4 → G3 → G2 → G6 → G5 → G7**, with W14 Part A able to start any time
(it is a measurement on an existing P&L series) and W14 Parts B–C gated on it.

**Three things are early on purpose.** **W4** can only subtract, costs no
trials, and if the IC does not survive it then most of what follows is answering
the wrong question — including all of `perfund/`, which would otherwise build
seventeen sleeves on an artifact. **F1** is early because F2 and F3 are fiction
without per-fund facts, and its Tier-1 fields cost almost nothing since the
fetchers already exist. **G1 and G4** are early because they are pure
engineering that unblocks everything else in that track, and because two of
G4's four defects are live on the order path today.

**Trial budget** if every research prompt runs its maximum: about **21 on the
CEF counter** (48 → ~69, bar 2.80 → 2.90) and **2 on GAMMA** (0 → 2, bar 1.18).
**They should not all run.** Several parts are built to close themselves —
W14 Part B on its stress-beta gate, W10 Part C and G7 on a derived budget of
zero, W13 Part C on the nowcast R², F2 on a τ posterior that includes zero — and
a prompt that closes itself has done its job at the cost of one trial rather
than a year.
