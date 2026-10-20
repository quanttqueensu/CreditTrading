# E1 rulings form: the 19 Stage-0 flags, readings R1–R12, and decision 6

**Date** 2026-10-20 · **Trial** EVENTS trial 1, E1
(`results/events/PREREG_E1_MERGER_PAIR_2026-10-19.md`) · **Stage 0 record**
`results/events/E1_STAGE0_2026-10-19.md` · **Reproducers** `python3 scripts/events/e1_merger_pair.py stage0` (the flags), `python3 scripts/events/e1_rulings_facts.py` (the facts below)
· **Flag form** `results/events/e1/e1_stage0_rulings.csv` (reading R7's path)

> **This is a form, not a ruling.** Every recommendation below waits on the team lead.
>
> - **No E1 statistic was computed to write it.** The flag diagnosis reads only whether a CRSP
>   return is present, and where each acquirer's CRSP series starts. The R10 count reads only
>   CRSP names and EDGAR CIKs.
> - **To accept:** for each flag row of the CSV, copy `recommended_ruling` into `ruling`, and
>   fill `ruled_by` and `ruled_on`. Until then the fit refuses (`require_stage0_rulings`
>   blocks on any blank field; checked).
> - **Where R1–R12 are recorded:** as amendment 2 in the pre-registration's banner. R12 also
>   sets the code constant `HOLDOUT_OPENS_AFTER_FIT_KILL`.

## A. The 19 Stage-0 flags (one cause, one recommended ruling)

**What the flags are.** They are the 19 completed fit deals that the §6.3 guard excludes. They
are exactly the 19 that the published at-announcement sample of 2026-10-12 leaves unpriced.
Its status for them reads "no price at window start".

| acquirer (deals) | finding |
|---|---|
| GECC (FULL); RA (BOI, HTR, HHY); DRA (ASP, BSP, CSP, SLA); NMS (MXA, MXN); NMAI (JDD, JTA, JTD); DIAX (DPD, DPO); QQQX (JLA); JGH (JGG, JGT) | **18 deals.** The acquirer's CRSP series begins on the payment date: it is a fund the merger created, with no share to short at the A+1 fill |
| no CRSP name (BLJ) | **1 deal.** The acquirer permno has no CRSP name in force and no price on the payment date |

| # | question | recommended ruling | reason | alternative |
|---|---|---|---|---|
| F1–F18 | Exclude these deals, counted, or repair them? | **Exclude and count** | §6.3: "Anything else excludes the deal, and it is counted. Nothing is filled with zero." No acquirer existed to short at entry, so the declared pair never existed. Live, §5.2 routes such a deal to no trade | Short a predecessor or sibling fund instead. That is a different trade, and it is not pre-registered |
| F19 | The same, for BLJ | **Exclude and count** | The pair cannot be closed as declared without a return the source lacks | Recover the acquirer's payment-date price from a second, named source, as a ruled repair |

## B. Readings R1–R12 (the pre-registration is silent on each)

| # | question | recommended ruling, and why | alternative |
|---|---|---|---|
| R1 | Identity check 1 asks for 1e-12, but the published per-deal file holds 8 significant digits. Against what does 1e-12 bind? | **Accept as run.** 1e-12 binds against the published code's full-precision values, which matched with a difference of 0.0. The file is matched at its own precision, and the tracked aggregates exactly. §6.4 asks that the published figure be reproduced, and `%.8g` text cannot carry 1e-12 | Re-run `merger_pairs.py --edgar-dates` with a full-precision file. That would rewrite published outputs |
| R2 | What is a leg's weight in a multi-target group? | **1/n_g, where n_g is the group's priced deals in the sleeve's set.** §6.2 says "1 unit long, split equally across its active targets", and the acquirer short "falls by that target's share" when one fails, which fixes each share at entry | Count unpriced and excluded deals in n_g. This leaves their share uninvested |
| R3 | In what unit is control 1's window length counted? | **Target sessions**: (d_in, dlstdt] for a completed deal, (d_in, F+1] for a failed one. §8.2 anchors the control "252 target sessions before the real entry", and `merger_pairs.fixed_offset_pairs` counts the same way | Market sessions to the payment date. This adds the days between the last trade and payment |
| R4 | How is control 2's ADV defined, and what happens to a candidate with no EDGAR CIK? | **ADV is the 63-session mean of price × volume ending the session before A** (the same as `_announcement_row`'s `adv63_T_pre`). **A candidate with no unique CIK is excluded, and counted.** §8.2's "no merger episode" test cannot be checked without a CIK | Admit unmatched candidates. This risks a merging fund serving as the control |
| R5 | Which date assigns a deal to an era? | **The fill date d_in.** The trade exists from then | The announcement date A, or the completion date |
| R6 | What turnover does a conversion carry? | **Sleeve: \|R_T − R_A\| on the payment date × the converted weight. Per deal: 2 + \|pair\| units.** §6.4 and §7 name "the received shares' value minus the short's" | 2 units flat per deal, the published `UNITS_PER_DEAL` convention |
| R7 | The pre-registration declares no rulings file. Where do the rulings go? | **`results/events/e1/e1_stage0_rulings.csv`.** The house rule (`/prereg` §4b, team lead 2026-10-19) requires one, and the pre-registration predates it | The dated template name, `e1_stage0_rulings_<date>.csv` |
| R8 | DG-E1-5 asks for MUB/IEF/HYG coverage to 2024-12-31. Before the fit verdict, only the fit reader may read CRSP, and it stops at 2022-12-30 | **DG-E1-5 clears on coverage of the fit window (2009-07 to 2022-12-30).** Only R-D4 and R-FF use factors, and §8.3 runs them on the fit's P&L. As written, the gate can never clear before the fit, because MUB 2023-24 exists only behind the holdout reader | Keep the 2024-12-31 bar and add a non-CRSP MUB source as a recorded deviation. `data/etf_daily.parquet` has IEF and HYG but no MUB |
| R9 | Should control 2 exclude `cef_universe.csv` names or the spec's 13? | **No filter.** §8.2 lists the candidate rules exhaustively, and E1 consumes the 27-name set at Stage 1 anyway (decision 3) | Exclude all 44 universe names. The pool shrinks, and the risk of the 75% halt rises |
| R10 | Should the failed-deal census keep every unexplained episode (273), or pre-filter? | **Keep all 273; the reading decides.** §4.3 says "Each is read", and the counterparty is named only in the filing. Of the 273, 75 have their own CIK matched to a CRSP CEF listed on the first filing date (22 of those run past CRSP's end). Another 21 of the rest carry a BDC-like EDGAR name, which the CEF-only map cannot test (`python3 scripts/events/e1_rulings_facts.py`, run 2026-10-20) | Read only those 75 plus the 21 BDC-named, about 96. That is quicker, but it misses any deal whose own CIK fails the name match (24 of 604 CRSP merger parties fail it) |
| R11 | Control 2 must exclude funds in a holdout deal. How is a holdout deal's window found without reading holdout prices? | **From dates only, [A, exit + 1 day].** This is wider than the traded window, and §8.2's purpose is "so no holdout price leaks into the fit" | Use an exchange calendar's first session after A. Equally price-free, but narrower |
| R12 | Does stage 8 open after a fit KILL? | **Open it after any committed fit verdict except a HALT. After a KILL or NEITHER it is report-only, and the verdict stays the fit's.** §C gives the text both ways | Open it only after a fit that passes stages 1–6 |

## C. R12: the §10 text, both ways

**For opening after a fit kill:**

- §10: "**Every statistic of every stage is computed and reported**, whatever the verdict."
  Stage 8 is a stage.
- §10: "The holdout can kill; **it can never rescue a failed fit**." This sentence only has work
  to do if the holdout is evaluated after a failed fit.
- §0: "holdouts, opened once **after the fit verdict**". It says after the verdict, not after a
  passing verdict.
- §11: "**A holdout fail would be informative. A holdout pass alone would not be.**" The
  likeliest fit verdicts, it says, are "a D4 kill on alpha t, or NEITHER".
- Stage 6: after NEITHER, "The team lead rules WATCH or D5". The holdout is evidence for that
  ruling.
- Precedent: C5's holdout was opened once after its D1 kill and reported: "It cannot rescue;
  the kill stands" (`docs/RESEARCH_STATE.md`, KILLED table).

**Against:**

- §10: "The verdict is the first failing rule in this order." After a kill, stage 8 cannot
  change the verdict.
- §2.3 names the holdouts, "above all", as the test that carries information. §0 describes
  the name holdout as "never priced". Opening it for a dead trial spends the only unseen muni merger evidence
  that a later, redesigned merger test could use.

**Recommendation: open, report-only, after a KILL or NEITHER. Do not open after a HALT**, whose
verdict is not final. The literal "every stage … whatever the verdict" and the C5 precedent
point this way. The 27-name set is consumed at Stage 1 whatever is decided here, so keeping the
holdout sealed saves only the name and time holdouts themselves.

## D. Decision 6's alternative (completed deals only): would Stage 0 clear without the 273 readings?

**Yes for DG-E1-3, but not alone.**

- DG-E1-3 drops out, and so do the failed deals' parts of DG-E1-1 and DG-E1-4.
- Two blockers remain, and each needs a credentialed run:
  - **DG-E1-2:** holdout dating still needs `fetch-edgar`, 299 documents. Only its census half
    becomes unnecessary.
  - **DG-E1-1:** the 9 control-2 pool funds still need `pull-crsp`.
- The rulings above still apply: the 19 flags, and R8 for DG-E1-5.
- Code: a declared switch, so that `stage0` records DG-E1-3 as ruled out and `fit` and
  `holdout` omit failed deals. This is a small change, with a test, made once ruled.

**What the trial loses:**

1. **Stage 1 becomes nearly a re-statement.** The pre-registration says "stage 1 on completed
   deals is close to known": 92 of the 95 fit muni deals were priced and published on
   2026-10-12. The failed deals are the first item in §2.3's list of "the tests that carry
   information".
2. **The known survivorship bias stays** (§2.3 item 2; decision 6: "keeps a known survivorship
   bias"). §11 expects the failed deals to "lower the median by an amount nobody has measured".
   Its direction and size are unmeasured [U]. Without them, k, f_max and the break-even fee
   rest on survivors alone.
3. **The holdouts lose their failures too.** §2.3 names 2023 cases: SBI → MMU, NXJ → NAD and
   NQP → NVG. The time holdout (5 muni deals in 3 groups) then cannot see the failure mode.
4. **Live diverges.** A live sleeve trades every announced deal, failed ones included.

**Recommendation: keep the default (failed deals included).** The readings are an agent's work
once `fetch-edgar` has run. R10's alternative is the cheaper middle path if the team lead wants
one.
