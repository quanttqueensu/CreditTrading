# References

Every external source the 2026-09-09 research pass established, with the claim
it supports and its verification status. **Prompts and notes cite this file
rather than re-deriving.** When a prompt's result changes what a source is used
for, amend the row here rather than leaving two versions in circulation.

Status key:
- **[V]** verified this session against a primary source that was actually fetched
- **[S]** sourced — a real, identified publication or page, but not fetched and
  re-read this session
- **[U]** uncertain — the claim is directionally supported but the number, the
  citation details, or both could not be confirmed. **Do not put a [U] number
  into a model without pulling the primary source first.**

---

## 1. Closed-end fund discounts: the foundational literature

| claim | source | status |
|---|---|---|
| Discounts co-move across funds; CEF IPOs cluster when seasoned funds trade near par; discounts correlate with other sentiment-sensitive assets | Lee, Shleifer & Thaler (1991), *J. Finance* 46:75–109 | [S] |
| Dividend yield and replication risk confirmed as two of the arbitrage-cost proxies with the expected signs (via Gemmill & Thomas 2002, read in full). **The full four-proxy set, the coefficients, and the "~25% of cross-sectional variance" R² could NOT be verified** — JSTOR, Oxford Academic and every PDF mirror blocked | Pontiff (1996), *QJE* 111(4):1135–1151 | **[U]** on magnitudes |
| Funds at premiums accrue negative abnormal returns, funds at discounts positive — direction confirmed by two papers citing it. **The "20% discount → ~6pp over 12 months" magnitude could NOT be verified** (ScienceDirect 403, no OA copy, no citing paper quotes the coefficient). Treat the number as unconfirmed | Pontiff (1995), *JFE* 37(3):341–370 | **[U]** on magnitude |
| **~85% of CEF excess volatility is idiosyncratic** to a four-factor model; idiosyncratic risk, not transaction cost, is the binding arbitrage constraint | Pontiff (2006), *J. Accounting & Economics* | [S] |
| CEF value = NAV + capitalised liquidity benefit − capitalised fees; explains why illiquid-asset CEFs can trade at *smaller* discounts | Cherkes, Sagi & Stanton (2009), *RFS* 22(1):257–297 | [S] |
| Discount = PV(fees) − PV(manager value added), with a firing threshold generating the IPO-to-discount lifecycle | Berk & Stanton (2007), *J. Finance* 62(2):529–556 | [S] |
| Management fees as a derivative claim on NAV; a non-behavioural rationalisation of the discount | Ross (2002), *European Financial Management* | [S] |
| Noise-trader sentiment drives short-run discount moves but is **rejected** as the explanation of the long-run level (158 UK CEFs) | Gemmill & Thomas (2002), *J. Finance* 57:2571–2594 | [S] |
| Payout level and stability signal sustainable NAV growth; higher, steadier payout → smaller discount | Johnson, Lin & Song (2006), *JFE* | [S] |
| Investor-sentiment proxies explain only **~7% of the variance** of weekly discount changes | Brauer (1993), *J. Financial Services Research* 7(3):199–216 | [S] |
| Abstract, verified verbatim: *"equity-based funds converge to the steady-state level faster than fixed income funds."* Method is "bias-corrected bootstrap half-life estimates" on UK and US CEFs. **Body, tables and actual half-life numbers are paywalled with no open-access copy anywhere** (Unpaywall: `is_oa: false`, no repository copy) | Ji & Kim (2013), *Applied Economics* 45(32):4503–4515 | [V] abstract only |
| **CONTRADICTS the above.** 377 US CEFs, Aug 1984–Dec 2011, monthly, per-fund ADF bias-corrected by 10,000-replication simulation: *"funds investing in fixed-income securities have faster speeds of reversion than funds investing in equities"* — Table III mean β −0.121 equity vs −0.136 fixed income | Patro, Piccotti & Wu (2014), "Exploiting Closed-End Fund Discounts" | [V] read in full |
| **Full-sample bias-adjusted half-life 7.7 months**; reversion coefficient ranges **−0.002 to −0.541 across 334 funds**; optimised quintile half-lives 4.1–4.9 months | Patro, Piccotti & Wu (2014) | [V] read in full |
| **The closest thing to a pooled-vs-per-fund horse race, and it favours per-fund**: strategies exploiting reversion-speed heterogeneity earn **Sharpe 1.86–1.92 against 1.52** for a naive premium-sign strategy — *"substantially improves trading strategy returns"*. **Monthly, and gross of costs** | Patro, Piccotti & Wu (2014) | [V] read in full |
| **The asset-class ordering is NOT settled** — two papers disagree, with different samples and methods. No prompt may assert a prior about it | — | [V] negative |
| Average CEF discount ~8.42% with ~98% period-to-period autocorrelation | Xu et al., "The Persistence and Predictability of Closed-End Fund Discounts" (UT Dallas) | [S] |

**The horizon gap, and it is the most important row in this table.** None of the
above operates at a 1–5 day horizon, and this was checked rather than assumed on
2026-09-09: a targeted search for daily or weekly CEF-discount half-life
estimates found **nothing published or in working-paper form**. Every locatable
study is monthly at best, with half-lives of 4–8 months. Our pooled AR(1)
φ = 0.9722 implies **24.6 days**. The negative result is itself the finding — any
two-day estimate has no precedent and must be derived in-house. That mismatch is
why `W4_artifact_battery.md` runs before any further trial.

---

## 2. Stale pricing, smoothing, and NAV mechanics

| claim | source | status |
|---|---|---|
| Observed returns are a moving average of true returns under stale marks; smoothing understates volatility and inflates Sharpe. The MA(q) unsmoothing framework | Getmansky, Lo & Makarov (2004), *JFE* 74(3):529–609 | [S] |
| Bond-fund NAVs are "extremely stale"; fund returns predictable over days to weeks, worse in crises; ~$1.2bn/yr dilution to buy-and-hold investors | Choi, Kronlund & Oh (2022), *JFE* 145(2):296–317, "Sitting Bucks" | [S] |
| Cross-fund dispersion in month-end marks on **identical** corporate bonds, consistent with return smoothing by managers — i.e. part of the smoothing is discretionary, not mechanical | Cici, Gibson & Merrick, "Missing the Marks", *JFE* | [S] |
| Muni market averages **under 2,800 trades and under 1,500 unique securities per day**; ~two-thirds of securities that trade at all trade once or twice; >1m CUSIPs outstanding | MSRB, "Trading Patterns in the Municipal Securities Market" (2024, 2023 data) | [V] |
| Muni NAVs are evaluated/matrix priced from comparable-bond curves, not last trades — sponsor's own language: *"yields or prices of municipal securities of comparable quality, type of issue, coupon, maturity and rating"* | Nuveen N-2/A (SEC EDGAR, CIK 883618) | [V] |
| ICE evaluates ~1.0m active US municipal bonds via a rules-based curve framework refreshed from MSRB RTRS round-lot reports | ICE Data Pricing & Reference Data, evaluated-pricing methodology | [V] |
| Bank-loan CEFs price from independent pricing services (dealer-quote surveys) approved by the board | Nuveen floating-rate N-CSR (EDGAR CIK 1276533) | [V] |
| **Rule 22c-1's forward-pricing mandate applies only to redeemable securities and therefore not to CEFs at all**; daily NAV striking is convention, not a clean statutory requirement | SEC, Rule 22c-1 amendments (2003) | [V] |
| Rule 2a-5 (adopted Dec 2020, **compliance 8 Sept 2022**) moved fair-valuation to a board-overseen "valuation designee" — a family's smoothing profile can change without announcement | SEC Release IC-34128 | [S] |
| CEFConnect **italicises a NAV whose published date is earlier than the row's date** — the aggregator itself flags carried-forward NAVs | cefconnect.com daily pricing page | [V] |
| On the ex-date **both NAV and price fall by the distribution**; the realised price drop is slightly less than the distribution due to tick discreteness | Bali & Hite (1998); mechanics per fund accounting | [S] |
| 2023 traditional-CEF distributions: **67% income, 13% capital gains, 20% return of capital** | ICI, "The Closed-End Fund Market, 2023" | [V] |
| Managed distribution policies require an SEC exemptive order under §19(b)/Rule 19b-1; **~32% of traditional CEFs** had one as of April 2024, concentrated outside credit | ICI, citing Morningstar | [V] |

---

## 3. Market structure, leverage, and the wrapper

| claim | source | status |
|---|---|---|
| Traditional CEFs issue a fixed share count at IPO with **no creation/redemption** | ICI (2023) | [V] |
| **62% of traditional CEFs use leverage**; average structural leverage ~28% (bond funds 29%) | ICI (2023) | [V] |
| 1940 Act §18(a): **≥300% asset coverage for debt, ≥200% for preferred** | SEC filings / statute | [V] |
| Nuveen munis lever via **tender option bond trusts**; floaters reset to the **SIFMA Municipal Swap Index** (tax-exempt, weekly, published Wednesdays by 4pm ET) | Nuveen, "Understanding Tender Option Bonds" | [V] |
| Average fund-sponsored TOB leverage ~**2.5× (Dec 2023)** rising to ~**3.32× (Q2 2024)** across ~$21.4bn / 169 funds | S&P Global Ratings (Jan 2024) | [V] |
| PIMCO CEFs lever via **reverse repo at 18–42% of managed assets**, ~6.3% effective cost | PIMCO N-CSR filings (EDGAR) | [V] |
| SOFR 3.65%, EFFR 3.63% (Sept 2026) | sofrrate.com; Federal Reserve H.15 | [V] |
| N-PORT `fundInfo` carries `totAssets`, `totLiabs`, `netAssets`, **`liquidPref`** (NAD: $1.6026bn) and `amtPay*` borrowings; holdings carry **`fairValLevel` (1/2/3)**; fund level carries **DV01/DV100** and **IG/non-IG spread duration** | SEC NPORT-P, live filing fetched | [V] |
| **Traditional CEF count 427 (YE2022) → 402 (YE2023)**, a 12th consecutive annual decline, ~36% below 2011; negative net issuance, zero new launches in 2023 | ICI (2023) | [V] |
| ~3.2m US households own CEFs; median income $104k, 43% retired; >80% also own mutual funds | ICI (2023) | [V] |
| **NYSE/Nasdaq MOC and LOC may be entered, modified or cancelled only until 15:50 ET**; after that no modification or cancellation, and new closing-only interest only on the imbalance-offsetting side | NYSE "Opening and Closing Auctions" fact sheet | [V] |
| Significant Imbalance published 15:50, refreshed every second; publication threshold on the order of **500 round lots (~50,000 shares)** | NYSE fact sheet; Federal Register 2024-13418 | [V] / [U] on the exact threshold |
| **Closing Offset** orders: limit-only, yield to all other closing interest, execute only against the opposite side of an imbalance | NYSE fact sheet | [V] |
| NYSE closing auctions matched ~9% of market-wide notional in 2024, up from 3.1% in 2010 | NYSE Data Insights | [S] |

| **NYSE MOC/LOC cutoff is 15:50 ET** — Rule 7.35(a)(8)'s "Closing Auction Imbalance Freeze Time", ten minutes before the end of Core Trading Hours, **so it moves with early closes** | NYSE Regulatory Memo RM-24-02 | [V] rule quote |
| **After 15:50 NYSE MOC/LOC cannot be cancelled or reduced "even to correct a legitimate error"**; carve-out under 7.35B(j)(2)(B) needs Trading Official approval. Tightened from a pre-2021 regime allowing error cancels 15:50–15:58 | RM-24-02; SEC Rel. 34-93849 | [V] |
| **NYSE imbalance threshold: "500 round lots or more" (50,000 shares)**, Rule 7.35B(d)(1) | RM-24-02 | [V] rule quote |
| **CORRECTION — the NYSE Closing Imbalance publishes ONCE at 15:50 and does not refresh.** An earlier version of this file said "refreshed every second"; that is Nasdaq's NOII | SEC Rel. 34-106126 (SR-NYSE-2026-36) | [V] |
| **Nasdaq differs materially: MOC until 15:55, LOC until 15:58**, IO until 16:00; cancel/modify frozen from 15:50. **NOII refreshes every 10s from 15:50, every 1s from 15:55**, with no share threshold | Nasdaq Closing Cross FAQ | [V] |
| NYSE **Closing IO Order** (Rule 7.31(c)(2)(D)) is limit-only, auction-only, and may be entered on **both sides up to 16:00**. **Being amended now** — SR-NYSE-2026-36, implementation by Q1 2027 | RM-24-02; SR-NYSE-2026-36 | [V] |
| **NYSE Arca's cutoff and imbalance threshold could NOT be verified** — and Arca lists HYG, LQD and SPY | — | **[U]** |
| **NYSE retains DMM discretion** (7.35B(b)–(c)): may close without a trade, may run the auction manually. Arca and Nasdaq have no equivalent | RM-24-02 | [V] |
| Closing auctions matched **$55.5bn/day = 9.44% of US notional**, Q2 2024; NYSE-listed share 10.52%. Large indexed names have a *higher* auction share than the broad universe | NYSE Data Insights | [V] |
| **~3.3% of NYSE auction volume goes unfilled; 6.3% for non-Russell-1000 names** — the category all 17 CEFs are in | NYSE Research Insights, Q1 2026 | [V] |
| **IBKR equities: Tiered $0.0035/share, min $0.35/order; Fixed $0.005/share, min $1.00/order**, both capped at 1% of trade value. **Options: Tiered $0.15–$0.65/contract, Fixed $0.65, $1.00 order minimum on both.** No MOC/LOC surcharge found | interactivebrokers.com pricing, observed 2026-09-09 | [V] |
| **The frozen spec's `min_trade_usd: 517` was derived on the Fixed $1.00 minimum. On Tiered it should be $181** — a 2.9× difference in what gets suppressed | internal arithmetic | [V] |
| IBKR short-sale credit interest gated on **NAV > $100,000**; tiers $100k–$1M **2.380%**, $1M–$3M 3.130%, >$3M 3.380% | IBKR short-sale-cost page, 2026-09-09 | [V] |
| **IBKR paper trading, verbatim:** *"Fills are simulated from the top of the book; no deep book access."* and *"Penny trading for US Options is not supported. Orders can be submitted but will not receive a penny fill."* Stops and complex order types are always simulated | ibkrguides.com paper-trading page | [V] direct quote |
| **Reg SHO threshold security: 5 consecutive settlement days, 10,000+ shares, AND ≥0.5% of shares outstanding.** Rule 203(b)(3) forces close-out at **13 consecutive settlement days** | SEC Reg SHO investor bulletin | [V] |
| **CORRECTION — the "2 trading days' recall notice" is NOT a Reg SHO rule.** The SEC's Reg SHO material does not address recall; terms are contractual under the MSLA and practice has shifted since T+1. **Ask IBKR and record the answer** | — | **[U]** |

---

## 4. The short side

| claim | source | status |
|---|---|---|
| IBKR publishes availability at `ftp2.interactivebrokers.com` `shortstock/usa.txt`, fields `SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE` | IBKR short-securities-availability page | [V] |
| TWS tick **236** returns exact shortable shares; legacy tick 46 is a coarse more/fewer-than-1,000 bucket | IBKR TWS API tick types | [V] |
| **Borrow fee = (market value × fee rate) / 360**, market value marked up to **102%** of prior settlement, rounded up to the nearest dollar | IBKR Borrow Fee Details report guide | [V] |
| Only fully-paid and excess-margin shares are lendable, and only where the holder opted into a lending programme; IBKR's requires a margin account or cash account with liquid net worth >$25,000 | IBKR Stock Yield Enhancement Program | [V] |
| Payment in lieu is **ordinary income to the lender, never a qualified dividend** — and for a municipal fund, never the exempt-interest dividend the holder bought it for | IBKR glossary; IRS substitute-payment guidance | [V] / [U] on the muni-specific extension |
| Short-seller deductibility of a payment in lieu depends on holding period: **capitalised into basis if the short is closed within 45 days**, deductible as investment interest beyond | IRC §263(h); CCH AnswerConnect | [S] |
| Discretionary recall requires **2 trading days' notice**; broker cannot force-close sooner than 3 hours before the deadline | SEC loaned-securities FAQ | [S] |
| Reg SHO threshold: 10,000+ aggregate fails **and** ≥0.5% of shares outstanding for 5 consecutive settlement days; **13 consecutive days forces mandatory buy-in at the start of T+14** | SRO/Reg SHO summaries | [S] |
| CEF short-selling **rises with the premium**, and — stronger than earlier recorded — *"short selling over the current day and the previous five days explains **60% of the variance** in the change in premiums over the subsequent five days."* Sample Jan 2005–Mar 2007; short sellers hold ~7 days. **Note the window is five days, not two, so this does not by itself establish that our 2-day leg is competed away** — the day-by-day decomposition was not accessible | Alexander & Peterson (2017), *J. Financial Markets* | [V] abstract |
| FINRA publishes short interest twice monthly for all listed securities, free, ~7 business days after settlement; Reg SHO daily short volume at `cdn.finra.org/equity/regsho/daily/` | FINRA; already implemented in `scripts/positioning/` | [V] |

---

## 5. Corporate events and activism

| claim | source | status |
|---|---|---|
| Saba, Karpus and Bulldog drove ~90% of 2023 CEF activist actions (77 filings, 70 funds); held stakes in **44% of all traditional CEFs** at 31 Dec 2024 | ICI, "Closed-End Fund Activism" (2025) | [V] |
| Across 34 funds with activist-forced tenders, excess discount ran **−4.4% (year before 13D) → −1.2% (pre-tender) → −0.2% (during) → −3.3% (year after)** — largely round-trips within a year | ICI, Figure 3 | [V] confirmed to the decimal |
| **Caveat on that figure:** the 2023 ICI report states the window as "2015 and 2022", the 2024 report as "2015 and June 2023" — **byte-identical statistics and the same 34 funds under two different stated windows.** The chart may not have been recomputed; treat the period as approximate | ICI 2023 vs 2024 reports | [V] |
| Of 44 forced tenders 2015–Jun 2023, activists fully exited **75% within a year**; of those, ~48% within three months, ~24% at 3–6 months, ~27% at 6–12 months | ICI | [V] |
| Saba **25% (97 funds)**, Karpus **26% (99)**, Bulldog **9% (33)** at YE2024; 167 distinct CEFs held by at least one, 9 by all three. **Concentration FELL from ">50%" at YE2023 to 44% at YE2024** | ICI activism brief (2025) | [V] |
| Saba filed 13Ds against **at least 18 named CEFs in 2023–24**, including muni/credit names NPFD, VTN, VKQ | SEC EDGAR full-text search | [V] |
| Nuveen has filed **395 N-14 reorganisation documents** across its trusts, 2002–2021+ | SEC EDGAR full-text search | [V] |
| **SEC rule of 10 Oct 2023 shortened the initial Schedule 13D deadline from 10 calendar days to 5 business days**; amendments to 2 business days | SEC press release 2023-219 | [V] |
| **CORRECTION — "successful open-ending cuts the discount in half" is wrong.** Successful conversion **eliminates** the discount (an open-end fund redeems at NAV). The "roughly half" figure describes funds that did **not** convert: their discount fell 21.20% (t−2) → 9.59% (t+3), ~55%, via **defensive buybacks, tenders and managed distributions in response to the mere threat**. All-sample 21.20% → 5.61% (~73%), mechanically pulled down by converters hitting zero | Bradley, Brav, Goldstein & Jiang (2010), *JFE* 95(1):1–19 | [V] read in full |
| Sample: 1988–2003; 142 equity CEFs; 127 discount events; 106 open-ending spells. Matched-fund-adjusted discount −0.49% (t−1) → −5.27% (attempt year) = ~4.8pp attributable to the attack | Bradley et al. (2010) | [V] |
| **There is NO short-window announcement CAR in that paper** — its granularity is annual (t−3 to t+3). Do not cite a "13D announcement return" to it. **Completion rate and time-to-completion are not reported** either | Bradley et al. (2010) | [V] negative |
| **On 11 June 2026 SCOTUS held that §47(b) creates no implied private right of action** — verbatim: *"Section 47(b) of the ICA does not impliedly empower private parties to sue for rescission of contracts that allegedly violate the Act."* Applied *Alexander v. Sandoval*. **CORRECTION: it was 6–3, not unanimous** — Barrett writing, with Jackson (joined by Sotomayor, and Kagan as to Parts I–II) and Kagan dissenting separately | *FS Credit Opportunities Corp. v. Saba Capital Master Fund*, No. 24-345, slip op. | [V] read in full |
| The ruling settles **who may sue, not whether defensive bylaws comply** with the Act. State-law fiduciary suits and SEC enforcement remain open, so the expectation is a pivot to slower, costlier routes rather than an end to activism | slip op.; ICI commentary (fund-side, not neutral) | [V] / [S] |
| SEC staff require a CEF tender to be priced at **NAV as of the close of the tender's final day** | Nuveen N-2/A | [V] |
| **Rights-offering subscription price, from a live filing on one of our own names** — BlackRock **HYT**, Rule 424(b)(5), filed 2022-09-20: **95%** of the average close on the expiration date and the 4 preceding sessions; if that formula price ≥ NAV it is set $0.01 below NAV; **if it is below 90% of NAV it floors at 90% of NAV**. The same template appears in a 2025 Neuberger N-2/A, so it is standing convention. (An earlier note here said "~90%" — the 90% is the *floor*, not the formula) | SEC EDGAR, CIK 1222401 | [V] primary filing |
| The CEF rights-offering paper is **Khorana, Wahal & Zenner (2002), *JFQA* 37(2)**, "Agency Conflicts in Closed-End Funds: The Case of Rights Offerings" — 120 offerings, 1988–1998. Funds trade at a **premium** on announcement and **"this premium turns into a discount over the course of the offering"**; the decline is larger where the advisor's fee gain from the enlarged asset base is bigger. (An earlier pass half-remembered this as "Kadapakkam" — that was a misattribution) | JFQA 37(2), DOI 10.2307/3595002 | [V] abstract; full text unreachable |
| **Section 19(a) notices have no EDGAR form** — sponsor sites and wire services only. PIMCO's site returns HTTP 403 to automated fetches | verified against a fund's full form census, 2026-09-09 | [V] |
| Fund-of-CEF ETFs: PCEF ~$809m, XMPT ~$216m AUM — small against the sector but potentially large against a single constituent's float | stockanalysis.com | [V] |
| Tax-loss selling drives the turn-of-year effect **specifically in municipal CEFs**; *"funds associated with brokerage firms display more tax-loss-selling behavior"*. **Direction only — the magnitudes, the December volume effect, the size of the affiliation difference and the sample period are all paywalled and could NOT be obtained** | Starks, Yong & Zheng (2006), *J. Finance* 61(6):3049–3067 | [V] abstract; **[U]** on every magnitude |

---

## 6. Options, volatility, and hedging

| claim | source | status |
|---|---|---|
| Delta-hedged P&L identity `dΠ = ½ΓS²(r² − σ_imp²Δt)`; held to expiry it is a **gamma-weighted** average of realised variance, so path matters | standard; Carr & Madan (1998); Neuberger (1994) "The Log Contract", *JPM* | [S] |
| A variance swap is the pure vol instrument because the log contract has Γ = 1/S², making dollar gamma constant and variance weighting uniform | Carr & Madan (1998); Demeterfi et al. (1999, GS) | [S] |
| Discrete hedging error is proportional to Γ(ΔS² − σ²S²Δt), approximately **χ²₁**-distributed; **variance scales as 1/N, standard deviation as 1/√N**. Citation exact (DOI 10.1016/0304-405X(80)90003-3); **the primary text is paywalled and the numerical results could not be read** — the characterisation is how the paper is universally described, not a verified quote. G3 Part A verifies the 1/N scaling on our own path instead | Boyle & Emanuel (1980), *JFE* 8:259–282 | [V] citation / **[U]** internals |
| Whalley-Wilmott no-transaction band. **The distinctive result — H ∝ Γ^(2/3) — is safe and consistently cited. The full expression is NOT verified**, and an earlier version of our own spec had a **notation collision**, writing risk aversion as lowercase `γ` while capital `Γ` is the option gamma in the same formula (literature generally uses `λ`). Whether the spot term is `S` or `S²` is also unconfirmed. **Get the paper before coding the band** | Whalley & Wilmott (1997), *Mathematical Finance* | **[U]** |
| Leland's adjusted volatility `Le = √(2/π)·k/(σ√Δt)`; **Kabanov & Safarian (1997) showed the limiting hedging error is non-zero**, contradicting Leland's convergence claim | Leland (1985), *J. Finance* 40:1283–1301; Kabanov & Safarian (1997) | [S] |
| Zakamouline corrects WW's degenerate bandwidth away from the money; Hodges & Neuberger (1989) is the reference true optimum | Zakamouline (2006) | [S] |
| ATM asymptotics: `Γ ∝ 1/√T`, `Θ ∝ 1/√T`, `Vega ∝ √T`, `Γ/premium ∝ 1/T`, `|Θ|/Γ ≈ ½σ²S²` tenor-invariant; ATM premium ≈ 0.4Sσ√T | standard Black-Scholes; Brenner-Subrahmanyam | [S] |
| Daily breakeven move ≈ `S·σ_imp/√252` | derivation from the identity | [S] |
| **Arbitrage-free SVI**: butterfly (non-negative density) and calendar (total variance non-decreasing in T) conditions on the five raw SVI parameters; SSVI for surfaces | Gatheral & Jacquier (2013), *Quantitative Finance*; arXiv:1204.0646 | [V] |
| SPY implied ÷ forward realised variance: **median 1.32, mean 1.55** in this repo's own data | `data/vrp/vrp_monthly.csv` | [V] internal |
| **DO NOT CITE — the "−74% average synthetic variance-swap payoff across ETFs including HYG" could NOT be verified.** Authorship (Aragon, Chen & Shi) and AFA 2025 venue confirmed via the authors' own pages; SSRN is bot-blocked and no abstract is indexed by CrossRef, Semantic Scholar or Unpaywall. Use Carr & Wu below instead — verified, and it makes the same point | Aragon, Chen & Shi | **[U] — unusable** |
| **Average log variance risk premium −66%** on 30-day S&P 500 variance swaps; annualised Sharpe on *shorting* variance **0.98 (S&P 500), 0.85 (S&P 100), 0.87 (Dow)**. Sample Jan 1996 – Feb 2003, five indices and 35 single names | Carr & Wu (2009), *RFS* 22(3):1311–1341 | [V] read in full |
| **The premium is an index phenomenon far more than a single-name one:** only **7 of 35 single names** show a significantly negative premium in levels (23 of 35 in logs), against all three major indices | Carr & Wu (2009) | [V] |
| **Credit VRP, all three figures confirmed exactly against the primary PDF:** firm VRP alone explains **34%** of cross-sectional 5-year CDS spread variation (adjusted R²), **49%** with controls; mean VRP rises monotonically **from 7 at AAA to 82 at CCC** (monthly %²); estimated price of market VRP risk **λ = 1.17 against an observed 1.20**. Sample Jan 2001 – Sep 2008, 382 firms. **The cleanest citation in the options programme** | Wang, Zhou & Zhou (2011), Federal Reserve FEDS 2011-02 | [V] read in full |
| Verbatim from the abstract: *"This smirk is more pronounced in the credit market than in the equity market."* Higher-leverage and larger firms have lower VRP. **Magnitudes paywalled** | Kita & Tortorice (2021), *J. Corporate Finance* 69 | [V] abstract |
| VRP predicts aggregate excess returns, concentrated at the **quarterly** horizon. **CORRECTION: the headline univariate quarterly adjusted R² is 6.82%, not the "low-to-mid teens" recorded earlier** — teens are reachable only in multivariate specifications adding P/E, term spread and the relative short rate (16.76%, up to 21.81%). Sample S&P 500, Jan 1990 – Dec 2007 | Bollerslev, Tauchen & Zhou (2009), *RFS* 22(11):4463–4492 | [V] read in full |
| Variance risk premia across five indices and 35 single names; **significantly negative for indices, smaller and less consistent for single names** | Carr & Wu (2009), *RFS* 22(3):1311–1341 | [V] abstract |
| Splitting VIX² into expected-variance and premium components: the **premium** part predicts returns, the expected-variance part predicts activity | Bekaert & Hoerova (2014), *J. Econometrics* | [S] |
| **≈74% of the variance risk premium is compensation for jump/tail risk, not diffusive risk** — left-tail component 88.4% of the average premium against 14.8% right-tail; the authors' own words are *"close to three-quarters... may be attributed to investor fears."* Median equity jump/tail premium 5.2% against a total ERP near 8%, so **~two-thirds of the equity premium is tail compensation too.** This is the structural argument against timing | Bollerslev & Todorov (2011), *J. Finance* 66(6) | [V] read in full |
| HAR-RV is the standard realised-vol forecasting framework; separating jump from continuous components improves out-of-sample forecasts | Corsi (2009), *J. Financial Econometrics*; Andersen, Bollerslev & Diebold (2007), *REStat* | [V] |
| Implied vol rises into scheduled releases and falls after — the market **prices scheduled events correctly** | Ederington & Lee (1996), *JFQA* | [S] |
| Sorting on the implied-minus-realised vol spread: the most "overpriced-implied" decile's straddles return **−12.8% per month**, the opposite decile **+9.9%**, and the 10−1 long-short straddle **+22.7% per month with a monthly Sharpe of 0.903** — against the market's 0.131. Sample Jan 1996 – Dec 2006. **The documented edge is in selling into an implied run-up**, which is why no event conditioner is pre-registered | Goyal & Saretto (2009), *JFE* 94(2) | [V] read in full |
| VIX futures basis predicts subsequent VIX futures returns; strategy shorts VIX futures in contango and goes long in backwardation, hedged with mini-S&P futures, sample 2006–2011. **Citation now exact: *Journal of Derivatives* 21(3):54–69, DOI 10.3905/jod.2014.21.3.054. Reported Sharpe ratios could not be obtained** (paywalled) | Simon & Campasano (2014) | [V] citation / **[U]** magnitudes |
| Vol-of-vol is a separately priced risk factor | Huang, Schlag, Shaliastovich & Thimme (2019), *JFQA* | [S] |
| Optimal policy under proportional costs is a no-trade region; bandwidth scales as **cost^(1/3)** — the cube-root rule | Constantinides (1986), *JPE* 94:842–862 | [S] |
| Optimal buy/sell boundaries form a wedge around the frictionless allocation; trading only at the boundaries | Davis & Norman (1990), *Math. of OR* 15(4) | [S] |
| **VIXHY and VIXIG** (CDX-based credit volatility indices) launched **13 Oct 2023**; VIXHY rose 240.09 → 394.15 between 2 and 20 Mar 2023 | Cboe / S&P DJI press release | [V] |
| Cboe IBHY/IBIG options on iBoxx futures: IBHY OI **$1.2bn (May 2025, 4.5× YoY)**, IBIG ~$598m; average bid/offer **0.05% of futures price**; $1,000 multiplier, $0.01 tick. Cboe's stated rationale includes *"dividend incorporation reducing early exercise risk"* relative to ETF options | Cboe product pages; ETF Express (Jul 2025); fi-desk.com | [V] |
| **IBKR paper trading fills options at the displayed price, top of book, no market impact, and does not support penny-increment option fills** | IBKR Campus documentation | [S] |
| Options permission level 2 covers long calls/puts and straddles; level 3 defined-risk spreads; level 4 uncovered | IBKR options-permissions docs | [S] |
| OCC exercise-by-exception threshold is **$0.01 in-the-money** at expiration | OCC / Cboe regulatory circular | [S] |
| OPRA US options data is a separate subscription; ~$10/month for non-professionals, waived at $30 monthly commissions | IBKR market-data pricing | [S] |
| HYG's average absolute stated premium/discount to NAV rose from **0.21% (Jan–Feb 2020) to 1.06% (Mar–Apr 2020)**; intraday deviation reached −5% to −8% around 18–19 Mar 2020 | BlackRock EII, "Pricing and Liquidity of Fixed Income ETFs in the Covid-19 Crisis" (Jul 2020) | [S] — sponsor research, not independent |
| IG corporate bond ETFs averaged a **3.4% discount to NAV in mid-March 2020, some exceeding 8%** | SEC Fixed Income Advisory Committee / IOSCO COVID reports | [U] on the exact figure |
| **CEF discounts widened by more than 1,600bp during March 2020**; average CEF discount since 2005 ~14.3%, 19.2% at the March 2009 extreme | Calamos, citing CEF universe data | [S] |
| Lipper measured the **median** CEF discount widening only 170bp to 9.78% in March 2020 — crisis widening is concentrated, not uniform | Lipper Alpha, "The Month in Closed-End Funds, March 2020" | [S] |
| **16 of the 17 traded CEFs have no listed options. PDI and PTY confirmed NOT optionable** (Cboe options endpoint 403 for both; MarketBeat "Not Optionable"). BDCs (ARCC, PSEC) do have options; large equity CEFs (ADX, UTF) do not | Cboe delayed-quote chain + MarketBeat, 2026-09-09 | [V] |
| **DSL genuinely has listed options, and they are shallow**: four expiries, strikes $2.50–$20 in $2.50 steps, most strikes 0–6 OI; best line Nov-20 $12.50 put at 83 OI / 80 volume, bid $1.95 / ask $2.50 = **~22% spread**. One crude ATM point, not a surface, not a hedge | Cboe delayed-quote chain, 2026-09-09 | [V] |
| **Credit/rates ETF option liquidity, measured**: HYG **367,197** contracts/day, weeklies, $0.09–$0.29 spreads — TLT ~230,000, $0.08 — LQD 31,506 — EMB thin, no weeklies — **JNK 20/day** — **MUB 168/day (165P / 3C), effectively dead** — **BKLN zero OI at every strike sampled** — AGG 66/day. HYG is close to the only usable credit-vol instrument | Cboe delayed-quote chain, 2026-09-09 | [V] |
| **Cboe IBHY/IBIG options: volume 0, open interest 0** on 2026-09-09, three years after listing, while the futures trade modestly (IBHY volume 436, OI 5,884; IBIG 648 / 4,068). Options are **American-style, physically settled into the futures**, $1,000 multiplier, $0.01 tick = $10, strike interval 0.25 | Cboe contract specs + daily statistics, 2026-09-09 | [V] |
| **VXHYG — a free VIX-methodology implied-vol index on HYG ETF options**, daily since 2015-04-22, **verified current 2026-09-09** (1,913 rows, level 6.13). Calm floor ~3.7–4.0; **COVID peak 59.26 on 2020-03-23**. Companion VXIEF covers IEF | `cdn.cboe.com/api/global/us_indices/daily_prices/VXHYG_History.csv` | [V] fetched |
| **VIXHY / VIXIG** (CDX-based) history back to **2012-03-05**, 3,682 rows. **But the file's last-modified was 2026-08-16 — ~3.5 weeks stale.** Check freshness before use | same path, `VIXHY_History.csv` / `VIXIG_History.csv` | [V] fetched |

---

## 7. Statistical method

| claim | source | status |
|---|---|---|
| Shrinkage dominates the per-entity MLE in total MSE for m ≥ 3 means | James & Stein (1961); Efron & Morris (1975), *JASA* | [V] |
| Empirical-Bayes posterior mean `θ̂_i = w_i·y_i + (1−w_i)·μ̂` with **`w_i = τ²/(τ² + se_i²)`** | Morris (1983), *JASA* 78; Gelman et al., *BDA3* Ch. 5 | [S] |
| **With few groups, use a weakly-informative prior on τ (half-Cauchy/half-Normal) rather than a moment estimator** | Gelman (2006), *Bayesian Analysis* 1(3) | [S] |
| **Imposing a common autoregressive coefficient on a heterogeneous dynamic panel is inconsistent as T→∞**, not merely biased — the deviation `(φ_i − φ̄)` is correlated with `y_{i,t−1}` by construction, so the correlation is structural rather than a finite-sample artifact. **Distinct from Nickell bias, which does vanish as T→∞.** The Mean Group estimator stays consistent; inconsistency is a pooling artifact. Primary paywalled — substance is standard, exact regularity conditions unverified | Pesaran & Smith (1995), *J. Econometrics* 68:79–113 | [S] / **[U]** on conditions |
| Pooled Mean Group estimator; Hausman test of PMG against MG | Pesaran, Shin & Smith (1999), *JASA* 94:621–634 | [S] |
| Fixed-effects dynamic panel bias ≈ **−(1+φ)/(T−1)** | Nickell (1981), *Econometrica* 49:1417–1426 | [S] |
| AR(1) small-sample bias **E[φ̂] − φ ≈ −(1+3φ)/T**, which **assumes a fitted intercept**. With a known or zero mean the leading bias is smaller (≈ −2φ/T). Primary (Biometrika 1954) unreachable; the exact constants are unconfirmed | Kendall (1954); Marriott & Pope (1954) | **[U]** |
| Half-life sensitivity `dh/dφ = ln2/[φ(lnφ)²]` diverges as φ→1. **At a 25-day half-life (φ = 0.9727), dh/dφ ≈ 927; SE(h)/h ≤ 20% needs T ≥ ~1,854 observations (~7.4 years)** — and 2–4× that in practice | delta method + `Var(φ̂) ≈ (1−φ²)/T` (Hamilton 1994) | [V] computed |
| Indirect inference preferred to first-order analytic corrections near a unit root | Gouriéroux, Monfort & Renault (1993), *J. Applied Econometrics* 8:S85–S118 | [S] |
| Swamy test: `S = Σ(β̂_i−β̄)'Σ̂_i⁻¹(β̂_i−β̄) ~ χ²(K(N−1))` — **and β̄ is a GLS/precision-weighted mean, `β̄ = [ΣΣ̂_i⁻¹]⁻¹ΣΣ̂_i⁻¹β̂_i`, not a simple average.** Getting that wrong inflates the statistic | Swamy (1970), *Econometrica* 38; Stata `xtrc` | [V] via textbook restatement |
| **Shrinkage beats both pooled and per-entity estimation out of sample, including where homogeneity is statistically rejected** | Baltagi & Griffin (1997), *J. Econometrics* 77; Baltagi, Bresson & Pirotte (2000) | [S] |
| Vasicek beta shrinkage `β_adj,i = w_i·β̂_i + (1−w_i)·β̄_cs`, `w_i = σ²_cs/(σ²_cs + se_i²)` — mathematically consistent with precision-weighted Bayesian updating. **But whether σ²_cs is the raw observed cross-sectional variance or bias-corrected for `E[se²]` could NOT be confirmed** (Wiley paywalled). This is the same trap as the τ² moment estimator; state which you use | Vasicek (1973), *J. Finance* 28:1233–1239 | **[U]** on σ²_cs |
| **"0.33 + 0.67·β" is a rounded practitioner convention** (widely attributed to a Merrill Lynch adjusted-beta service), **not a literal quote of Blume's regression coefficients**, which varied by sub-period | Blume (1971) | **[U]** |
| Bayes-Stein shrinkage: target `μ₀ = (1'Σ⁻¹μ̂)/(1'Σ⁻¹1)`, intensity `φ = (N+2)/[(N+2) + T(μ̂−μ₀1)'Σ⁻¹(μ̂−μ₀1)]`. Citation confirmed via the author's own CV page. **Whether Σ here is the plain sample covariance, and the form of Jorion's separate covariance adjustment, are unverified — do not implement that piece from memory** | Jorion (1986), *JFQA* 21:279–292 | **[U]** on Σ |
| **A single hierarchical fit is not multiple testing — but only if nothing is filtered on afterwards** | Gelman, Hill & Yajima (2012), *J. Research on Educational Effectiveness* 5:189–211 | [S] |
| False discovery rate control | Benjamini & Hochberg (1995), *JRSS-B* 57:289–300 | [V] |
| Regularised multi-task learning is structurally identical to a hierarchical Bayes prior; MAML is equivalent to hierarchical Bayes under a Laplace approximation | Evgeniou & Pontil (2004); Grant et al. (2018), ICLR | [S] |
| **SE(ŜR) ≈ √((1 + ½ŜR²)/T)** for IID returns, ŜR non-annualised | Lo (2002), *FAJ* 58(4) — confirmed via Bailey & López de Prado, who reproduce the derivation | [V] indirect |
| **The autocorrelation-corrected η(q) factor could NOT be verified.** General variance-ratio form is `η(q) = q/√(q + 2Σ(q−k)ρ_k)`, collapsing to √q under IID — but whether Lo gives a closed form for AR(1), and what it is, is unconfirmed. **Do not implement from memory; source the paper** | — | **[U]** |
| **MinTRL = 1 + [1 − γ̂₃·ŜR + (γ̂₄−1)/4·ŜR²]·(Z_α/(ŜR − SR*))²** — verified term for term. **Originates in "The Sharpe Ratio Efficient Frontier" (2012), not the DSR paper.** ŜR non-annualised; needs ~30+ obs before the moments are trustworthy | Bailey & López de Prado (2012), *Journal of Risk* | [V] read in full |
| Probability of backtest overfitting (CSCV) | Bailey, Borwein, López de Prado & Zhu (2014) | [S] |
| **DSR verified exactly:** `SR₀ = √V[{ŜR_n}]·[(1−γ)Z⁻¹(1−1/N) + γZ⁻¹(1−1/(Ne))]`, `DSR = Z[(ŜR−SR₀)√(T−1)/√(1 − γ̂₃ŜR + (γ̂₄−1)/4·ŜR²)]`, γ = 0.5772. **N is the number of *independent* trials** — our counter records trials, not independent ones; state the assumption | Bailey & López de Prado (2014), *JPM* 40(5) | [V] read in full |
| `IR = IC × TC × √BR`; **TC typically 0.3–0.8** for constrained portfolios | Clarke, de Silva & Thorley (2002), *FAJ* | [S] |
| Effective breadth collapses far below nominal position count when forecasts are cross-sectionally correlated | Qian & Hua (2004) | [S] |
| Bid-ask bounce drives much of measured short-horizon reversal; profits largely vanish measured off quote midpoints | short-horizon reversal literature (equity microstructure) | [S] |
| French & Roll (1986), *JFE* 17(1):5–26 — the classic trading-time vs non-trading-time variance reference. **Citation exact; the magnitude could not be read (paywalled), and no published overnight/intraday variance split for bond ETFs exists at all.** Which is why §9 computes it on our own data | French & Roll (1986) | [V] citation / **[U]** magnitude |
| **Corwin-Schultz verified against the authors' own distributed code and data description** (equations 14 and 18): `CONST = 3−2√2`; `β_t = [ln(H_t/L_t)]² + [ln(H_{t−1}/L_{t−1})]²`; `γ_t = [ln(H_max2day/L_min2day)]²`; `α_t = (√(2β)−√β)/CONST − √(γ/CONST)`; `S_t = 2(e^α−1)/(1+e^α)` | Corwin & Schultz (2012), *J. Finance* 67(2) | [V] |
| **Negative estimates are set to ZERO, not missing**, before averaging — the author's own 2014 note tests both and finds zero matches TAQ-quoted spreads better | Corwin, "Dealing with Negative Values" (2014) | [V] |

---

## 8. Data endpoints

| what | where | status |
|---|---|---|
| Ticker → CIK | `https://www.sec.gov/files/company_tickers.json` (10,407 entries, all 44 CEF CIKs resolve) | [V] |
| Full filing history, one call per fund | `https://data.sec.gov/submissions/CIK##########.json` | [V] |
| Filing XML | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/primary_doc.xml` | [V] |
| EDGAR full-text search | `https://efts.sec.gov/LATEST/search-index?q=...&forms=...&ciks=...` | [V] |
| 13D/G by subject company | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=SC+13&output=atom` | [V] |
| N-PORT coverage | public from ~2019; **month 3 of each fiscal quarter only; ~55–60 day lag** | [V] |
| CEFConnect dated NAV | `https://www.cefconnect.com/api/v3/pricinghistory/{TICKER}/1Y` → `{"Data":{"PriceHistory":[{"DataDate":...,"NAVData":...}]}}`. **Carries a per-row `DataDate`, so staleness is detectable** | [V] |
| FRED keyless CSV | `https://fred.stlouisfed.org/graph/fredgraph.csv?id={SID}` — SOFR, DFF, `BAMLH0A0HYM2`, `BAMLC0A0CM`, DGS3MO/2/10. **`BAML*` silently truncate to ~3 years on the keyless endpoint** | [V] |
| FINRA short interest | `POST api.finra.org/data/group/otcMarket/name/consolidatedShortInterest` (no key, paged) | [V] |
| FINRA Reg SHO daily | `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt` (daily from 2018-08-01) | [V] |
| IBKR short availability | `ftp2.interactivebrokers.com` `shortstock/usa.txt` | [V] |
| SIFMA Municipal Swap Index | sifma.org research/statistics — landing page live; **exact weekly-history file URL still to be pinned** | [V] / [U] |
| **No free AAA muni curve or muni/Treasury ratio found on FRED** — must be computed in-house from a muni ETF against a duration-matched Treasury and labelled a proxy | — | [V] negative |
| MSRB EMMA bulk historical trade data | **has historically required a data licence — do not scrape** | [S] |
| Morningstar public CEF pages | **ToS prohibits scraping/redistribution — avoid** | [S] |
| PIMCO sponsor site | **HTTP 403 to automated fetches** (verified 2026-09-09); use wire services instead | [V] |
| Nuveen / BlackRock CEF pages | HTTP 200 but client-rendered SPAs; raw HTML carries no PDF links | [V] |

---

## 9. Internal measurements

Facts established on our own data rather than from a source. **These are
reproducible — the method is stated so they can be re-run and disputed.**

| claim | method | date |
|---|---|---|
| **Overnight share of close-to-close variance, 2019+: HYG 59.6%, JNK 55.0%, TLT 54.5%, LQD 48.6%, SPY 43.7%.** Majority of HYG's variance arrives overnight | `Σ[ln(O_t/C_{t−1})]² / Σ[ln(C_t/C_{t−1})]²` on `data/rv/etf_ohlc.parquet` | 2026-09-09 |
| Not a reversal artifact: overnight/intraday correlation near zero (HYG ρ = −0.046) | same panel | 2026-09-09 |
| Not a stale-open artifact: HYG opening gaps 2019+ have median 0.0bp, sd 44bp, 4.0% exactly zero, 9.7% beyond ±50bp | same panel | 2026-09-09 |
| **French & Roll still holds per unit of clock time** — HYG intraday variance intensity 0.55 vs 0.27 overnight (×10⁻⁴/day-equivalent). The overnight *total* is larger only because the window is ~17.5h against a 6.5h session | same panel | 2026-09-09 |
| **Parkinson's estimator recovers only ~48% of HYG's close-to-close variance since 2019** — the size of the benchmark error G3 Part C exists to prevent | same panel | 2026-09-09 |
| **Distribution carry on the live band's holdings path: −0.01%/yr full sample**, sd 1.23%/yr. By era: 2010–14 **−0.77%**, 2015–19 +0.32%, 2020–22 +0.36%, 2023–26 +0.25% | `Σ_i H.shift(2)_it · (D_it/P_i,t−1)` over 3,962 ex-dates, 2005–2026 | 2026-09-09 |
| **This withdraws an earlier estimate of "about 2%/yr"** made before measurement. The legs' yields net out; the book is not systematically long or short yield | — | 2026-09-09 |
| Per-fund κ identification budget: a 25-day half-life needs **T ≥ ~1,854 paired observations** for ±20% precision (φ = 0.9727, dh/dφ ≈ 927, SE(φ) ≤ 0.0054). **PDO has 1,407 and fails; DSL 3,362, BIT 3,402, PDI 3,592 are marginal** on the realistic 2–4× bound | delta method + `Var(φ̂) ≈ (1−φ²)/T` on the paired price/NAV panel | 2026-09-09 |
| `band_frontier.py::band()` **raises on a vector `b`**; `qualifyContracts` appears nowhere in `src/`; an option target without `meta["limit_price"]` becomes a $0.00 limit; `exec_ledger.py` has **zero** occurrences of expiry/assign/exercise | direct code read and execution | 2026-09-09 |
| **MQY and MHD are BlackRock funds, not Nuveen** — splitting the muni group across two leverage mechanisms | `cef_facts.csv` `longName` | 2026-09-09 |
| **`validate.py` scored `shift(1)` until 2026-09-10** — an entry at day *t*'s close on day *t*'s NAV, which publishes after it. Corrected: gross **1.27→0.94**, net **0.83→0.51**, walk-forward **8/9→7/9** (worst −0.45), bootstrap P(SR≤0) **0.000%→0.300%**, DSR@48 **0.870→0.333**. Reproduces the cost predicted on 2026-07-31 and never acted on | `python3 scripts/cef/validate.py --trials 48`, panel to 2026-09-09; stored verbatim in `results/cef/EXECUTION_CONVENTION_2026-09-10.md` and `results/cef/runs/` | 2026-09-10 |
| **The deflated Sharpe now FAILS at every trial count** — 0.588 @N=10, 0.333 @48, 0.330 @49, 0.197 @162. Observed 0.51 sits **below** the best-of-48 null of 0.60. The 14:37 "flips PASS→FAIL between 10 and 48" finding is overtaken; the counter stays 48 and nothing turns on it | same run | 2026-09-10 |
| **Section 2's "5d embargo either side" was printed, never applied** — a bare `np.array_split` whose blocks touched. Applying it costs a further block (8/9 → 7/9 at `shift(2)`) | same run; `scripts/cef/validate.py:173-181` before the fix | 2026-09-10 |
| **The live band 4.8% policy has never been walk-forwarded, bootstrapped or deflated.** Every such figure in this repo belongs to `validate.py`'s 5-day-hold **calendar** sleeve, retired 2026-09-06. The band's own numbers are full-sample only: gross **1.17**, net@15bp **0.67**, turn 17.6×/yr | `python3 scripts/cef/band_frontier.py`, same panel, byte-identical before and after the `validate.py` fix; stored as `results/cef/runs/band_frontier_2026-09-10_control.txt` | 2026-09-10 |
| **"Gross 1.23 IS → 1.75 OOS" is withdrawn.** 1.75 is the *gross* of a holdout whose recorded verdict is FAIL — `net_sharpe −0.298`, `cost_pct_of_gross 117.2`. The signal generalised; the turnover did not (102.6×/yr vs 45.3 in sample) | `results/cef/HOLDOUT_OPENED.json`, direct read | 2026-09-10 |

---

## 10. Open questions — status 2026-09-10

### Closed by derivation (the papers were not needed)

Three formulas were flagged "must be re-sourced before coding". All three are
now settled without the paywalled originals, and the derivations are in the
prompts that use them:

- **Lo's η(q) autocorrelation factor** — derived from the variance of a q-period
  sum, with the AR(1) closed form
  `Σ_{k=1}^{q−1}(q−k)ρ^k = [qρ(1−ρ) − ρ(1−ρ^q)]/(1−ρ)²`. Verified against
  brute-force summation to machine precision and against a Monte Carlo on
  simulated AR(1) returns. `η(q,0) = √q` exactly. **→ W1**
- **Whalley-Wilmott `S` vs `S²`** — settled by dimensional analysis: Γ carries
  price⁻¹, λ carries price⁻¹, so the bracket is dimensionless only at `S¹`.
  **The desk's original spec was right; the only real error was the γ/Γ notation
  collision.** The (3/2) leading constant remains uncited and does not matter,
  since G3 uses only the `Γ^(2/3)` scaling. **→ G3**
- **Vasicek's σ²_cs / the τ² question** — settled by the law of total variance:
  `Var(θ̂ across i) = E[se²] + τ²`, so the numerator is **always** the
  bias-corrected quantity. What Vasicek actually wrote is irrelevant to what is
  correct. Simulated at N = 17 over 4,000 draws to show when it matters. **→ F2**

### Still open, in priority order

1. **NYSE Arca's closing-auction cutoff and imbalance threshold.** Arca lists
   HYG, LQD and SPY — everything the gamma hedging touches. Attempted again
   2026-09-10: nyse.com's Arca rulebook PDF 404s, and EDGAR full-text search
   returns zero hits for the Rule 7.35-E closing-auction timing language.
   **This is a broker/rulebook question, not a research question** — ask IBKR or
   read the rulebook through a paid SRO service. G3 already gates the first live
   hedge on it.
2. **DSL's option depth on a live broker chain.** Public data says real but
   shallow (most strikes 0–6 OI; best line 83 OI at a ~22% spread). Only an IBKR
   chain settles whether one ATM point is usable.
3. **IBKR's actual recall terms and notice practice** — contractual under the
   MSLA, not Reg SHO. Ask; record with a date.
4. **Whether HYG's price-vs-NAV basis noise is predictable** — the one genuinely
   open *research* question (G2 Part E). A hypothesis with a measurement
   attached, not a gap.
5. **The Aragon/Chen/Shi ETF variance-swap figure**, if anyone gets SSRN access.
   HYG-specific evidence would be valuable; Carr & Wu covers indices and single
   names only. Not blocking — the claim it supported is now made better by
   Carr & Wu.
6. **Magnitudes where the direction is already confirmed and nothing depends on
   the size:** Starks/Yong/Zheng, Khorana/Wahal/Zenner, Simon & Campasano,
   Ji & Kim's tables, Boyle & Emanuel's reported numbers. G3 verifies the 1/N
   hedging-error scaling on our own path instead of citing it.
7. **CEF bid-ask spreads and closing-auction share of volume.** No public
   dataset exists; W7 measures them from our own fills.

### Genuine negatives — findings, not gaps

- **No study anywhere estimates CEF discount half-life at daily or weekly
  frequency.** Every locatable paper is monthly at best, 4–8 month half-lives,
  against our 24.6-day implied figure.
- **Bradley et al. (2010) contains no short-window announcement CAR** and
  reports no completion rate.
- **No published overnight/intraday variance decomposition exists for bond
  ETFs**, which is why §9's own measurement is the only source we have.

### Corrections made to this file's own earlier entries

Seven claims recorded on 2026-09-09 were wrong and are fixed above: the BTZ
quarterly R² (6.82%, not "teens"); the SCOTUS vote (6–3, not unanimous); Bradley
et al. on open-ending (conversion *eliminates* the discount — the "half" applies
to funds that did **not** convert); the NYSE imbalance (published once, not
refreshing); the rights-offering price (95% formula, 90% NAV floor); the recall
notice period (contractual, not Reg SHO); and the Aragon −74% figure (withdrawn
as unverifiable).

### A fetch artifact that was never a source (moved 2026-09-10, W0c §4)

`wu_paper_archive.html` sat at the **repo root**, beside `README.md` and
`CLAUDE.md`, named as though it were an archived copy of a Wu paper. **It is
not.** Opened and read 2026-09-10: it is a 4.6 KB Internet Archive error page
whose entire content is *"The Wayback Machine has not archived that URL"* for
`http://faculty.baruch.cuny.edu/lwu/` (Liuren Wu's faculty page). It contains no
paper, no abstract and no figure, and **nothing in the repo ever cited it**.

It is now `results/ops/wu_faculty_page_wayback_MISS_2026-09-09.html` — renamed,
not deleted, because the failed fetch is itself a small piece of evidence: it
records that the archive route to that page was tried on 2026-09-09 and returned
nothing. **A file whose name asserts a provenance it does not have is worse than
no file**, which is the only reason this note exists rather than a silent move.

The Carr & Wu (2009) and Wang, Zhou & Zhou (2011) entries above are unaffected —
both were read in full from their own primary sources and are marked `[V]`.
