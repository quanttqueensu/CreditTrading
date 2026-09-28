# Pre-registration — a soft cap on the muni-minus-taxable tilt, and a hard cap on gross

**Spec** `cef_discount.v6.20260906` → `cef_discount.v7.20260916`
**Written before the first session that trades it.** Two keys, two very different
kinds of claim, and they are accounted for separately below.

**Counter: CEF.** `docs/RESEARCH_STATE.md` reads **55** at the time of writing
(branch `nextgen-20260914`; row log `ng/research/trials/*.csv`).

- **`group_cap` spends NOTHING. Its trial is already spent.** The operator and
  the value of *k* are **GN-N2**, CEF trial **55**, registered at
  `ng/research/prereg/PREREG_GROUP_NEUTRALITY_2026-09-15.md` and scored in
  `ng/05_research_group_neutrality.md` on 2026-09-15. **This document is an
  ADOPTION of a counted trial, not a new one.** Adopting a result you have
  already paid for does not cost a second haircut; re-scoring it and then
  quoting the better of the two readings would, and is not done here — every
  number in §5 reproduces GN-N2's published table rather than replacing it.
- **`max_gross_stress` is CEF trial 56.** `ng/05_research_no_borrow_rescore.md`
  §8.2 says so in terms: *"Items 1, 2 and 4 argue for (a) with a margin cap
  rather than (b). That construction is not registered: '1×, gross capped at
  G_stress' would be a new parameter choice and a CEF trial."* It is registered
  here. **Counter CEF 55 → 56. Bar √(2 ln 56) = 2.836.**
  `docs/RESEARCH_STATE.md` and `ng/research/trials/` are updated in the same
  commit as this note.

---

## 1. What changes

Two keys added to `ops/specs/cef_discount.frozen.json`, both **absent = off**:

| key | old | new | units | where it acts |
|---|---|---|---|---|
| `frozen.group_cap` | *(absent)* | `0.30` | weight (fraction of sleeve NAV) | on the FINAL target, **before** the band |
| `frozen.max_gross_stress` | *(absent)* | `1.90` | multiple of sleeve NAV | on the HELD book, **after** the band |

Nothing else moves. `band_width` stays 4.8%, `z_window` stays 252,
`vol_target_annual` stays 6%, the universe stays the 17, `order_type` stays MOC,
`min_trade_usd` stays $517, `gross_leverage` stays 1.0.

**The one-line revert is per key: delete it** (or set it to `null`). Both keys
read as "no cap" when absent, when `null`, and when `""`.

`spec_id` → `cef_discount.v7.20260916`, `_supersedes` →
`cef_discount.v6.20260906`, previous file kept at
`ops/specs/cef_discount.frozen.json.bak-2026-09-16`.

### The no-op is proved, not asserted

`ng/store/deploy/gc_noop.py` runs the sleeve over every session of the harness
sample (**2005-01-03 … 2026-09-11**, the pinned `snapshot_20260914` panel) on
four streams with **identical inputs on every date** — same `asof`, same panel,
same holdings — and hashes the full emitted book, reason strings and `meta`
included:

| stream | sha256 of the full emitted history |
|---|---|
| 1. `HEAD` sleeve, keys absent | `11fe31aef569c9ec…178562ddc` |
| 2. new sleeve, keys absent | **identical to 1** |
| 3. new sleeve, keys present-but-`null` | **identical to 1** |
| 4. new sleeve, keys active | `f1a2e5e587ccc121…2e2564c4a7c` — **differs**, so the proof is not vacuous |

Streams 1–3 emit 13,876 trades / 29,326 band HOLDs / 49,567 FLATs, byte-identical. Stream 4 emits
22,790 / 20,245 / 49,734. Full hashes and the one disclosed caveat (a docstring corrected after the
run began, closed by an AST comparison) are in `ng/08_strategy_change.md` §2.

Stream 1 is the half that could actually fail: it is the proof that the *code*
change, not the configuration, moves nothing.
`src/deploy/tests/test_group_cap.py::test_absent_and_null_are_byte_identical`
holds the same property shut on a synthetic panel, with its own vacuity control.

---

## 2. Why, mechanically

### 2a. `group_cap`

The sleeve ranks each fund against **its own** discount history and then
cross-sectionally demeans. That removes the *market*. It does not remove the
*mandate*: a leveraged municipal CEF and a multi-sector credit CEF have
different buyers, and the spread between the two blocks moves for reasons the
discount signal knows nothing about. Nothing in the construction bounds the net
muni-minus-taxable weight, so when the signal happens to point one way across
the mandate line, the book takes a large group bet **as a side effect**.

Measured, not supposed: at the panel's last date the rolling-252 R² of the live
band's own gross P&L to the in-panel equal-weight muni-minus-taxable
total-return spread is **0.746** (β −0.623, NW t −11.83) and last-12m effective
breadth is **2.27** bets on a nominal 17 names. Over those 12 months the price
leg was **−1.84 %/yr** and the book's return was distribution carry against a
losing price leg — the exact pair of conditions `05_verify` §7 pre-registered as
*"the book is not doing the thing it was deployed to do"*. **The live book flags
that monitor today.**

A cap bounds the side effect and leaves the name selection alone. That matters
because the name selection is still working: a **within-group** label
permutation over the last 12 months gives p = 0.0475. What failed was the group
tilt, not the signal.

### 2b. `max_gross_stress`

The sleeve targets **6% volatility**. Nothing targets **margin**, and margin —
not the 20% vol cap — is what this account is short of (`05_research` §6.3). The
vol scalar is free to run to its 2.5 ceiling, and gross reaches **2.77×** of the
$500k book over the traded window.

At the 2026-09-15 16:50 ET account read the fundable gross under a worst-week
buffer is **1.931×**. The live book exceeds it on **17.0%** of traded days and
exceeds `G_max` (no buffer at all) on **10.7%**. **There is nothing on the live
path that stops it** — no preflight check computes this, and `risk_check` is
observe-only by standing instruction.

A book that spends more margin than the account has is not a sizing question.
This key is the floor under that, and it is the *only* thing enforcing it until
a run-time preflight re-measurement exists.

---

## 3. How each parameter was DERIVED

### 3a. `group_cap = 0.30`

**Rule, fixed in GN-N2's prereg before anything was scored:** the **median**
`|net group weight|` the live band ran **on its own targets** over the traded era
**before 2023**.

Measured 2013-06-14 … 2022-12-30: **0.304953 → k = 0.30**.

- A second reading on **held** weights gives **0.2832** — same answer to the
  first digit, from a different object.
- The **mean** is **0.4427** and was **rejected in advance**, because the tail
  the cap exists to cut would otherwise set its own limit.
- Deriving *k* on pre-2023 data makes **2023–26 out of sample for k**.

**The argmax of the swept column was k = 0.15 (traded gross SR 1.706) and was
NOT chosen.** The derived 0.30 sits 0.9% below it, on a plateau spanning
1.62–1.71 across the entire range from k = 0 to no cap, reproduced here:

| k | 0.00 | **0.15 ← argmax** | **0.30 (derived)** | 0.45 | 0.60 | 0.90 | none |
|---|---:|---:|---:|---:|---:|---:|---:|
| traded gross SR | 1.640 | **1.706** | **1.691** | 1.666 | 1.645 | 1.616 | 1.537 |
| traded ann % | 8.61 | 9.16 | 9.40 | 9.58 | 9.77 | 10.09 | 10.10 |
| traded turn/yr | 25.0 | 25.2 | 25.9 | 26.6 | 27.3 | 28.1 | 28.8 |

Picking the argmax of a swept column is how `z_window = 63` was selected, and it
failed out of sample. Same discipline that put `band_width` at the derived 4.8%
and not the sweep-topping 6.4%.

**The adversarial reading, kept rather than dropped.** The traded column is
flat; the 2023–26, last-12m and R² columns are **monotone** in k. A monotone
gradient in exactly the window whose concentration prompted the test is what you
see when a constraint fixes a real recent problem — *and also* what you see when
you fit one window. The flat traded column is what separates the two: the
constraint is not paying for itself out of the long run.

### 3b. `max_gross_stress = 1.90`

`G_stress = (NLV − M_other)/(0.5 + w5)/E_book`, where 0.5 is the IBKR-Canada CEF
maintenance rate and `w5` is the worst 5-session loss per unit gross.

**Re-derived here [V]** from the recorded READONLY account snapshot at
**2026-09-15T16:50:06-04:00** (`ng/store/research/no_borrow_rescore/out/nbr_lever.json`):

| input | value |
|---|---:|
| NLV | $714,475.4510832613 |
| M_other, 09-15 marks | $194,797.03120376007 |
| M_other, 09-14 accepted marks | $189,566.1991782321 |
| w5 (worst 5 sessions per unit gross, ending 2020-03-18) | 0.038264817497540925 |
| E_book | $500,000 |
| **G_stress** | **1.930940×** / **1.950375×** |
| **G_max** (no buffer) | 2.078714× / 2.099637× |

Both reproduce the recorded figures to 1e-12. The recorded mark sensitivity is
**0.02×**.

**Rule, fixed before the value was scored:** *floor to 0.05 of (the lowest
reading, less the mark sensitivity)* = `floor₀.₀₅(1.930940 − 0.02)` = **1.90**.

**The value NOT chosen is 1.931 — the measurement itself.** A ceiling set
exactly at one account read leaves no room for that read's own stated
sensitivity, and none at all for the other two books' margin rising without this
book trading (`05_research` §6.2 risk 5). **G_max 2.079 was also not chosen**: it
carries no stress buffer.

**Plateau (H8), on the group-capped book, traded window:**

| cap × | 1.70 | 1.80 | **1.90** | 1.9309 | 2.00 | 2.0787 | none |
|---|---:|---:|---:|---:|---:|---:|---:|
| gross SR | 1.732 | 1.728 | **1.724** | 1.723 | 1.720 | 1.716 | 1.691 |
| ann % | 9.26 | 9.33 | **9.40** | 9.41 | 9.43 | 9.44 | 9.40 |
| binds % of days | 16.8 | 13.7 | **11.6** | 11.0 | 9.3 | 8.0 | — |

Flat to 0.016 of Sharpe across the whole range. **This is deliberately not a
P&L-selected parameter** — the number comes from the broker's margin arithmetic,
and the plateau is shown to prove that choosing conservatively inside it costs
nothing, not to justify the choice.

---

## 4. Committed in advance

- **Execution convention: `shift(2)`.** Decide at *t*, MOC fill at *t+1*, earn
  the *t+2* return. `band_frontier.evaluate` owns it; nothing here re-implements
  it.
- **Scoring is GROSS P&L (D19/D20), which is this programme's binding rule.**
  Held weights × total returns (price + distributions, split-corrected). No
  borrow, no commission, no slippage, no financing.
- **Cost grid 5 / 15 / 30bp is reported on every table and labelled a
  SENSITIVITY, not the score.** Borrow is charged separately and is **not**
  charged anywhere in this note. The answer must not flip sign across the grid —
  and §5 records where it does.
- **Eras** 2005–09, 2010–14, 2015–19, 2020–22, 2023–26.
- **Fit period for *k* ends 2023-01-01**; 2023–26 and the last 12 months are
  reported separately and are **examined, not holdout**.
- **Turnover-matched against** the live band 4.8% at **28.8×/yr** traded. Both
  constrained books trade **less** (25.9 and 25.6), so no turnover match is
  needed in the direction that flatters: the change is compared at *lower* turn.
- **Negative control, already run and not re-run here:** 200 random 6/11
  partitions of the same 17 names through the identical operator. The real
  muni/taxable partition is at the **100th percentile** on all three windows and
  a random partition *lowers* the traded Sharpe on average (mean ΔSR −0.113).
  The improvement is a property of **the muni axis**, not of within-group
  arithmetic.
- **The 27 sealed CEFs are not loaded.** The panel is the D16-filtered 17-name
  snapshot.
- **We do not re-tune either parameter on live data.** The next legitimate
  change to `group_cap` is a re-derivation of the median on a longer pre-2023
  record; the next legitimate change to `max_gross_stress` is a fresh account
  read, done deliberately at a promotion.

---

## 5. What we expect

Gross P&L, `shift(2)`, band 4.8%, pinned panel to **2026-09-11**, traded era
**2013-06-14 …** unless stated. `v7` = both keys active.

| book | gross SR | ann % | vol % | CAGR % | maxDD % | turn/yr | mean gross × | max gross × | > 1.931× |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **v6 live band** | 1.537 | 10.10 | 6.57 | 10.39 | −9.47 | 28.8 | 1.44 | **2.77** | **17.0%** |
| group cap only | 1.691 | 9.40 | 5.56 | 9.68 | −6.61 | 25.9 | 1.23 | **2.76** | **11.0%** |
| stress cap only | 1.572 | 10.07 | 6.41 | 10.37 | −9.03 | 28.6 | 1.39 | 1.90 | 0.0% |
| **v7 both** | **1.724** | 9.40 | 5.45 | 9.69 | −5.58 | 25.6 | 1.19 | **1.90** | **0.0%** |

**The group cap does not fix the margin breach and the margin cap does not fix
the concentration.** The group-cap-only book still reaches 2.76× gross; the
stress-cap-only book still carries the factor. That is why there are two keys
and not one.

**The change's own t, which is the number that matters** (paired daily
difference against v6, same dates, same return matrix, NW lag 26; bar **2.836**):

| candidate | traded | **pre-2023** | 2023–26 | last 12m |
|---|---|---|---|---|
| group cap only | −0.71 %/yr, t **−1.06** | −1.13 %/yr, t **−1.67** | +0.39, t +0.24 | +1.47, t +0.44 |
| stress cap only | −0.03 %/yr, t **−0.28** | −0.06 %/yr, t −0.42 | +0.03, t +0.10 | +0.14, t +1.41 |
| **v7 both** | −0.71 %/yr, t **−1.06** | −1.16 %/yr, t **−1.71** | +0.46, t +0.29 | +1.50, t +0.45 |

**Not one difference clears any significance bar, and pre-2023 — the only window
out of sample for *k* — both are negative.** So the expectation recorded here is:

1. **No return improvement.** Expected change in gross return: **zero within
   error**, with a point estimate of about **−0.7 %/yr** on the traded window.
   If the live record shows a *return* improvement, that is luck, not this
   change working.
2. **A risk improvement that should be visible quickly.** Vol 6.57% → 5.45%,
   mean gross 1.44× → 1.19×, max gross 2.77× → 1.90× **by construction**.
3. **Turnover should FALL**, 28.8 → 25.6 ×/yr on the backtest; over the last 12
   months 15.0 → 13.1.
4. **The margin breach goes to zero by construction.** Not a forecast — an
   identity, provided the sleeve is the only thing sizing the book.

**Cost sensitivity, labelled** (net Sharpe at bp per unit turnover; **not** the
score, and borrow is not charged):

| book | traded net5 / net15 / net30 | 2023–26 | last 12m |
|---|---|---|---|
| v6 live | 1.323 / 0.888 / 0.225 | 0.768 / 0.410 / **−0.131** | 0.003 / **−0.247** / **−0.624** |
| **v7 both** | 1.495 / 1.030 / 0.319 | 1.418 / 0.895 / 0.097 | 0.531 / 0.100 / **−0.561** |

**The sign flip at 30bp in the last 12 months survives the change** and is
recorded rather than buried: the constrained book is less cost-sensitive
everywhere, and is still negative at 30bp over the last 12 months.

---

## 6. What would FALSIFY this

**Read at 60 armed sessions, with the existing kill rule, and not before —
except items 3 and 4, which are read every session.**

| # | statistic | where read | horizon | threshold that reverses the decision |
|---|---|---|---|---|
| 1 | **realised turnover, ×/yr** | `ops/ledger.py` fills, broker-confirmed only | 20 armed sessions | If realised turnover is **not below** the pre-change book's over the same names, the cap is not wired the way this note says. That is a **code bug to find**, not a result — revert `group_cap` and fix it. Expected ~25.6 vs 28.8. |
| 2 | **realised book vol, annualised over the live record** | broker-confirmed NAV series | 60 armed sessions | If realised vol is **not lower** than the v6 record at the same gross, the risk claim — the only claim made — has not shown up. Revert `group_cap`. |
| 3 | **`max(gross) / sleeve NAV` on any armed session** | preflight / `book_state.py` | **every session** | Any reading **> 1.90 + 0.02** means the cap is not binding where it must. Halt the book (`ops/HALT_cef_discount.md`) and find out why before the next session. |
| 4 | **`G_stress` re-measured from a fresh READONLY account read** | `nbr_lever.margin_headroom` on a new snapshot | **every promotion**, and monthly | If the re-measured `G_stress` falls **below 1.90**, the frozen ceiling is no longer conservative and is itself the hazard. Lower the key to the new `floor₀.₀₅(G_stress − 0.02)` in a fresh spec bump — do **not** leave it. |
| 5 | **rolling-252 R² of live gross P&L to the muni-minus-taxable spread** | `gn_score.rolling_factor` on the live series | 252 sessions | If it is **above 0.40** while the trailing-252 price leg is **negative**, the cap has failed to do the one thing it was adopted for. (`05_verify` §7's monitor, which v6 flags on today.) |
| 6 | **net group weight of the HELD book** | `book_state.py` | every session | Sustained `mean |g| > 0.45` (1.5× the cap) over 20 armed sessions means the band is defeating the cap. Backtest says 0.332 mean, 0.541 max. |

**What would NOT reverse it:** a run of negative months, or a live gross return
below v6's. §5 commits in advance to a point estimate of **−0.7 %/yr**. Reading a
realised shortfall as evidence against the change would be reading the thing this
note already predicts.

---

## 7. Divergences from the backtest, stated up front

1. **The reference state is actual holdings, not a stored target.** The backtest
   has no failed fills; we do. The band compares against what we really hold, so
   a missed session leaves the position further from target and the band closes
   it later.
2. **`min_abs_weight` = 0.005 wins over both caps.** If the group cap shifts a
   name under the dust threshold, or the gross cap scales it under, the name is
   flattened instead. **The direction is conservative for the margin cap** (it
   reduces gross further, never increases it) and **is not conservative for the
   group cap** (it can move the net group weight by up to `min_abs_weight` per
   flattened name). Backtested magnitude: the emitted `|g|` stays inside
   `k + n·0.005`. Bounded, deliberate, not special-cased.
3. **A binding gross cap turns every band HOLD into a trade.** A HOLD is
   share-expressed precisely because "leave it alone" must cost nothing; when
   the margin cap binds we are not leaving the book alone. `min_trade_usd`
   ($517) still drops the resize orders too small to send, which is what keeps a
   hairline breach from churning the book. Backtested: the cap binds on **11.6%**
   of traded days with a mean scale factor of **0.862** and a worst of **0.688**.
4. **`max_gross_stress` is a STATIC ceiling and `G_stress` is not static.** It
   moves with NLV and with the other two books' margin, and a frozen key cannot
   re-measure it. Falsifier 4 is the control on this, and it is a human check,
   not code. **No preflight check computes gross-vs-G_stress today.** That gap
   is named in `ng/08_strategy_change.md` §6 as the first follow-on.
5. **The sleeve's cap runs row-wise; the research's ran frame-vectorised.**
   Measured: identical algebra (max abs difference **exactly 0.0** against a
   row-wise transcription), and **5.551e-17** on 1,608 of 92,769 cells against
   the vectorised call `gn_score.py` actually made — a numpy summation-order
   artifact confirmed by a memory-layout control at 4.441e-16. **No reported
   statistic moves** (|Δ| exactly 0.0 on gross SR, annual return, vol and
   turnover).
6. **The group axis is `grp` = current stated mandate applied over all
   history** (STATIC_ASSUMED). AWF (2007-01-29) and PFN (2010-03-01) have
   recorded mandate changes and **neither crosses the muni/taxable line**, so
   the binary split is unaffected. A five-group split would not be.
7. **The panel's last date is 2026-09-11.** The 2026-09-14 and 2026-09-15 live
   sessions, which have broker-confirmed fills, are **not** in it.
8. **Two inherited panel defects are in every number here**: the 28 zero-filled
   name-days of 2026-02-12…19, and the six missing PIMCO 2026-09-11 ex-dates.
   Both are inherited identically by every book, so they cancel in the paired
   differences and do **not** cancel in the levels.
9. The auction's ~3.3–6.3% unfilled rate for non-Russell-1000 names, odd lots,
   and delayed data all apply exactly as they did to v6.

---

## 8. Trial accounting

| counter | before | after | bar √(2 ln N) | what spent it |
|---|---:|---:|---:|---|
| CEF | 55 | **56** | **2.836** | `max_gross_stress` — a new parameter choice, per `05_research` §8.2 |
| CEF | — | — | — | `group_cap` — **already spent as GN-N2 (trial 55)**; adoption only |
| GAMMA | 0 | 0 | — | untouched |

Updated in `docs/RESEARCH_STATE.md` and `ng/research/trials/group_cap.csv` in
this same commit: **yes**.

**Not one figure in §5 clears 2.836, and none is claimed to.** The case for this
change is a risk case and an operational case. The deflated Sharpe of a *level*
is not evidence for a *change*; the paired t in §5 is the change's own number,
and it says the return difference is zero.

---

## 9. What this change is NOT

- **Not a leverage change.** `vol_target_annual` stays 6% and `gross_leverage`
  stays 1.0. `max_gross_stress` **only scales down**. The construction that
  levers *up* to `G_stress` — `05_research` §6.3 book (b), +14.20% CAGR at 8.55%
  vol — is a different book with its own evidence and its own trial, and nothing
  here licenses it.
- **Not a universe change.** The 17 stay, PHK included.
- **Not a borrow decision.** C1 remains unresolved and outside D19's scope; no
  borrow is charged anywhere in this note.
- **Not hard group neutrality.** GN-N1 is in the graveyard: traded turnover
  1.5002× the reference (2.72× in 2023–26, 4.96× over the last 12 months), mean
  gross 2.17× against a 1.931× stress cap breached on 83.3% of last-12m days,
  and the vol scalar pinned at its 2.5 ceiling on 34.7% of days.
- **Not a claim that the last 12 months were positive for v6.** They were +0.59%
  at t 0.13, ±~0.5pp of panel artefact — indistinguishable from zero.
- **Not a fix for the thing that actually limits this book.** Operations outrank
  this. A construction change is worth nothing on sessions that do not arm.

## 10. Reproduce

```bash
cd /Users/simonjarvis/Desktop/2027/QUANTT/nextgen
python3 ng/store/deploy/gc_score.py     # the tables, with all four parity pins
python3 ng/store/deploy/gc_noop.py      # the no-op proof, four hashed streams
python3 -m pytest -q src/deploy/tests/test_group_cap.py
```
