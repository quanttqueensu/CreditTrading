# Overnight journal — 2026-07-30

Status line per checkpoint, so the morning reader can reconstruct the night
without reading logs.

**Gate A (holdings + feeds) — PASS on holdings, PARTIAL on feeds.**
iShares `latest-holdings.csv` confirmed working (the `.ajax` path returns HTML;
the URL slug is ignored, only portfolioId matters). 15 funds ingested, 29,698
holdings, union panel of 11,423 priced CUSIPs against a 3,000 target. Two
portfolioIds I guessed were WRONG — 271054 is the Low Carbon MSCI ACWI equity
fund (not FALN) and 239453 is TLH (not SLQD) — caught only because the runbook
says to print the column set on first pull. A fund-name assertion is now
load-bearing in the ingester. VIX 212d→0d, UST futures 113d→0d (kept as a
separate series, NOT spliced onto the 1988 history: different roll convention).
FRED/CRSP/financing remain 10–14d and are lag-published by nature.

**Engine reconciliation — PASS with one known offset.** Rebuilt NAV = sum(market
value)/shares outstanding matches reported NAV within 0.07% for 10/12 funds. The
dirty (accrued-inclusive) rebuild is correct; the clean rebuild is uniformly
1.2–2.8% low. HYG is +1.80% and LQD +0.46%, traced to securities-lending cash
collateral appearing as an asset with no published offsetting liability. Level
offset, not drift. Cross-issuer price disagreement is a DEAD input: median 0.09bp
across 1,132 shared bonds, because both issuers buy marks from the same vendor.

**Block B (nine benchmark books) — DONE, the guaranteed deliverable.** All nine
through one execution path. Two accounting bugs found and fixed: idle cash was
earning interest that inflated low-gross books (now all on excess-return basis),
and the risk-free rate was being charged to dollar-neutral books that are
self-financing (now charged on net exposure only). B9 null trader PASSES its
honesty test: net −20.68%/yr against modelled cost 21.2%/yr, before-cost Sharpe
−0.39 ≈ 0. The fill and accounting path does not invent profits.

**S1 (stale-mark corrected NAV) — KILLED ON MECHANISM, no backtest spent.**
NAV-return autocorrelation is the direct staleness measure: HYG +0.388 vs its own
price −0.005, NAV vol 6.05% vs price 9.51%. Decays 0.580 (2007–10) → 0.148
(2023–26) in lockstep with E1's PD dispersion (187.9bp → 3.8bp). Treasuries flat
in every era (negative control PASSES). By 2023–26 HYG staleness is +0.038,
t=1.1 — nothing left to correct, so PD* ≈ PD. Note: an earlier version of this
table mislabelled the equity fund above as FALN; corrected.

**S2 (common-priced basket) — CANNOT BE TESTED YET.** Needs a history of
bond-level holdings. `asOfDate` is ignored by the endpoint and no archive exists.
The panel starts 2026-07-29 and grows one day per day; testable in ~1 year. The
ingester is the durable asset built tonight.

**S3 / Test 4 (forced-flow identification) — MECHANISM CONFIRMED, TRADE REJECTED.**
16,388 IG→HY migrations. Bond falls −424bp to k+2 (t −17.5) and recovers to
−2.8bp by k+60. First version was WRONG — showed 414% recovery from survivorship
(dropouts) plus trade-count event time (k+60 meant a year later for illiquid
bonds). Fixed to business-day grid + balanced panel; re-ran 5 sample definitions.
Honest specs where dropouts are carried flat and cannot recover still give 82–85%.
Sell imbalance 0.000 → 0.060 exactly at the flip. Test 3 monotonicity is the
cleanest confirmation: quiet months (<25 migrations) show −22% recovery (price
keeps falling = information), crisis months (>400) show 98% (= pressure). But the
crisis regime fired 4 times in 273 months, once per 5.7 years.

**Block F (deployment) — DEPLOY NOTHING NEW.** Best candidate net Sharpe 0.37
against B2's zero-skill 0.54. Test 7 fails on alpha (t 1.98 vs 3.0) and on both
factor limits (HY −0.163, IG +0.123 vs 0.10). Adding the forced-flow signal to
the unconditional pair makes it WORSE (0.37 → 0.03–0.24), so the premium is
already passive in ANGL and has been packaged since 2012. Declined the 10%
PROVISIONAL slot too: the candidate is a static credit-quality tilt, which
breaches the no-carry/no-beta/no-holding mandate outright. Trial ledger 141→156;
selection haircut at N=156 is 3.18 against a best candidate of 0.37.

**Still running:** Phase 0 null trader, unchanged, 09:35 ET weekdays.
