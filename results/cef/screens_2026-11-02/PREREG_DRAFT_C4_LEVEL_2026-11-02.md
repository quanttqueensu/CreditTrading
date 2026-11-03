# Pre-registration DRAFT — C4's discount level against family peers, as a second signal in the C4 account

Date: 2026-11-02   Counter: CEF, trial 54 **if approved** (CEF stays 53 until the team lead's approval is
recorded)   Author: idea-generation seat, for the team lead
**Status: DRAFT. Not approved. No trial spent. Nothing is built, and no 2023+ return of this signal has been
computed.** The evidence is `ALPHA_SLATE.md` §S5 in this folder.

## 0. Open questions for the team lead (each has a recommended answer)

| # | question | recommended |
|---|---|---|
| Q1 | A second signal blended into C4's target, or its own book in its own account? | **Blended into C4's target** at equal risk (§3). It uses the same names, so a separate account would only add a third set of fills and wash-trade risk (landmine 2) |
| Q2 | How is it judged? | **As C4 was** (trial 52): the fit at the bar, then the 2023–26 holdout's sign, then net at 15bp. Holdout alone at 2.825 has P(pass) of only 0.04–0.26 over 3.74 years |
| Q3 | Survivorship Stage 0 needs CRSP rows for dead funds in the five families, 2005–22 | **The team lead's credentialed R2 pull**, as for E1's control pool. The test does not open without it |
| Q4 | Borrow on the shorts (premium funds: DNP, GCV, GGN, RFI, BME, ASG led the fit) | **Paper: ignored in the verdict, reported in its own column** (C4's precedent). Measured, not modelled, before any real-money proposal |
| Q5 | A cross-sectional check on the 60 five-family funds outside the frozen 74 (not shortable today) | **Report-only, opened once at the fit** (they cannot be traded short, so they cannot be a sleeve) |
| Q6 | Paper credits no dividends | **Score both.** The fit's price-only SR (1.19) is above total return (1.12), so paper does not flatter it |

## 1. What changes

The C4 book only (`ops/specs/` C4 spec, through `/spec-change`). A new frozen key, `level_weight`, and an
absent key reproduces C4 byte-for-byte (the no-op proved by diffing sleeve output). With the key set, C4's
daily target becomes T = (1 − a) · T_z + a · T_L:

- T_z is C4's z target as today;
- T_L is the unit-gross within-family book on −(fund discount − family mean discount), as of the decision date;
- both are scaled to equal ex-ante risk before blending;
- the combined target goes through C4's existing band, gross cap and vol scalar, unchanged.

Revert: delete the key.

## 2. Why, mechanically

Retail yield buyers overpay for some funds (brand, distribution rate), and the arbitrage is a short of a fund
whose lendable pool cannot grow (Pontiff 1995 [U on magnitude]; Pontiff 2006 [S]). C4's z is standardised
against each fund's own history, so it is blind to a persistent level gap between peers by construction. On the
fit, the NAV leg is flat (−0.26bp/pp, t −0.32), so the effect is convergence of price toward NAV, not fair value
in the holdings. On the credit core the same test fails exactly there: the NAV leg is t +3.01. That is why this
draft is for C4 only.

## 3. How the parameters were DERIVED

- **a, the blend.** Two unit-vol strategies with Sharpes s1, s2 and correlation ρ have mean-variance risk weights
  ∝ (s1 − ρ s2, s2 − ρ s1). On the fit the inputs are s_z 1.13, s_L 1.12 and ρ +0.10 (all three [V] on the
  yfinance leg), which gives 1.018 : 1.007. With Sharpes estimated this noisily, the derived answer is **equal
  risk**. It is not swept, and no other a was scored.
- **The level's cadence.** Decided daily, with the band doing the work. The screen's book rebalanced every 21
  sessions; that was declared in `alpha_level.py` before its first run and never varied. h = 63 was also
  declared and reported. No other cadence was scored.
- **Within-family demeaning, and the C4 families.** These come from C4's own construction, not chosen here.
- **What was not chosen, and why.** The pooled level across families. It was never run, because `docs/SYSTEM.md`
  says a cross-group level is a permanent group bet.

## 4. Committed in advance

- shift(2); the canonical `harness.evaluate` / `report`; turnover-matched against C4's z book alone (H2), with
  the band width matched within 5% turn/yr. **The derived band is not re-tuned for the trial's headline.**
- Gross is the headline; the 5/15/30bp grid sits beside it; borrow in its own labelled column.
- Eras 2005–09, 2010–14, 2015–19, 2020–22, 2023–26. The fit ends 2022-12-30. **The holdout is 2023-01-03 →
  2026-09-30**, the window C4's own holdout used. It is opened once, after the fit verdict's commit.
- **Negative controls:**
  - NC1, the NAV leg of the level book (must stay flat);
  - K7, another fund's level in the same family on the same date (20 draws; the real book must rank above 19);
  - the credit WIDE17 is recorded as a control that already failed NC1.
- **Declared seen:** this screen's fit figures (`ALPHA_SLATE.md`), and C4's 2023–26 returns, which were opened
  for trial 52 on 2026-10-18. This signal's 2023+ P&L has not been computed.

## 4b. Stage 0 (no P&L of any kind before every gate is clear)

| gate | test | halts if |
|---|---|---|
| DG-L1 survivorship | the level book on the five families **including dead funds** (CRSP, 2005–22; Q3) | dead-inclusive gross SR < ½ of the survivor-only fit, or its sign changes |
| DG-L2 second return source | the fit on C4's CRSP primary returns (to 2024) in place of the yfinance leg | gross SR differs by > 0.2 from the yfinance leg's 1.12, unexplained |
| DG-L3 data | the |price TR − NAV TR| > 10% name-days (242 on the fit) triaged; C4's split and bar rulings applied | any untriaged flag (`require_stage0_rulings`) |
| DG-L4 identity | `level_weight` absent reproduces C4's book byte-for-byte | any diff |

## 5. What we expect [model, U]

- Fit (already seen): blend SR about 1.5 against z alone about 1.1, on the yfinance leg.
- Holdout gross SR of the level book: 0.5–1.1. P(sign > 0) is 0.86–0.99.
- On all capital: **+0.8 to +1.5%/yr gross** at C4's approved vol (×1.27), on $100k of $200k.
- Turnover rises by about the level book's 5.4/yr at its risk share, less what the band nets.

## 6. What would FALSIFY this (each read once, at the stated point)

1. Stage 0 DG-L1 or DG-L2 fails: **withdrawn before any 2023+ return is read**, and the trial is not counted if
   withdrawn at Stage 0 (to be ruled: Q2).
2. **Fit:** the blended book's gross increment over z alone at matched turnover has `sharpe_diff` t < 2.825, or
   NC1 |t| ≥ 2, or the K7 placebo rank < 19 of 20, or D4 fails (alpha t < 3.0 or any |β| > 0.10): KILL.
3. **Holdout:** the level book's 2023–26 gross SR ≤ 0: KILL. Net SR at 15bp ≤ 0: D2.
4. **Forward paper (if adopted):** the level component's own attributed P&L after 120 armed C4 sessions below
   the fit's 5th percentile for 120-session windows: reverse.

## 7. Divergences from backtest, stated up front

- Paper credits no dividends and fills at the quote, not the auction (landmine 1).
- Whole shares only; shorts Alpaca will not lend are skipped, which tilts the level book long.
- The 9 non-NYSE funds are scored as gaps for now.
- Borrow on premium funds is the arbitrage cost the mechanism relies on, so a real-money view must carry it.

## 8. Trial accounting

Counter CEF: 53 → 54 **only on approval**. Bar √(2 ln 54) = 2.825. `docs/RESEARCH_STATE.md` is not changed by
this draft.
