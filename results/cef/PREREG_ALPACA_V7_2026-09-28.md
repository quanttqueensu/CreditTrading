# Pre-registration — v7 on Alpaca: 13 names, a gross ceiling, $100k

**Spec** `cef_discount.v6.20260906` → `cef_discount.v7.20260928`
**Written 2026-09-28, before any session trades it.** Nothing trades on Alpaca yet;
the first armed session is at least `docs/ROADMAP.md` phase 5 away.

**Counter: CEF, 48 → 50. Bar √(2 ln 50) = 2.797.** Two trials, counted separately:

1. **The universe change** (17 → 13). Forced by tradability, not chosen from
   results, but it changes traded behaviour, and the rule counts every such change.
2. **`max_gross_stress` on this book.** The key and its derivation rule were
   pre-registered on the nextgen branch (`results/cef/PREREG_GROUP_CAP_2026-09-16.md`),
   but on `main`'s counter — which the team lead ruled authoritative on 2026-09-28
   — it was never counted, and it is re-derived here for a different account and
   universe.

`group_cap` is **not adopted** (§3a), so it spends nothing.

**Reproducer for every number below:**
`python3 scripts/cef/alpaca_v7_derivation.py` (panel to **2026-09-21**; it first
re-derives the two recorded 17-name figures and refuses to continue if either does
not reproduce).

---

## 1. What changes

| key | v6 | v7-on-Alpaca | units | decided by |
|---|---|---|---|---|
| `frozen.universe` | 17 names | **13**: drops NAD, NEA, NVG, NZF | tickers | team lead, 2026-09-28 |
| `frozen.max_gross_stress` | *(absent)* | **1.80** | multiple of sleeve NAV, on the HELD book after the band | derived, §3b |
| `frozen.group_cap` | *(absent)* | *(absent)* | — | team lead, 2026-09-28 (§3a) |
| `capital_usd` | 500,000 | **100,000** | USD | team lead: the Alpaca paper default |
| `risk.max_gross_exposure_usd` | 1,300,000 (2.6× capital) | **260,000** (2.6× capital) | USD | the same multiple of capital |
| `rebalance.min_trade_usd` | 517 | **0.0** | USD | derived, §3c |

Unchanged: `band_width` 4.8%, `z_window` 252, `vol_target_annual` 6%, `order_type`
MOC, `gross_leverage` 1.0, the ADV/NAV-age/min-names/min-weight filters, the kill
rule.

**Revert, per key:** restore the universe list; delete `max_gross_stress`;
`capital_usd` and `min_trade_usd` back to their v6 values. The v6 file is at the
commit tagged `spec-cef_discount.v6.20260906`.

## 2. Why

On 2026-09-28 the first read-only probe of the Alpaca paper account
(`results/ops/alpaca_probe/2026-09-28_cef.json`) returned all 17 names tradable,
and **NAD, NEA, NVG, NZF `shortable: false`, `borrow_status: hard_to_borrow`**
[V]. A dollar-neutral book that cannot short four of its names is not the book
that was tested, so the team lead dropped them.

The four are all municipal funds; so are MHD and MQY, which stay. The book's
dominant risk was muni-versus-taxable (R² 0.754 of its gross P&L to the in-panel
spread over the last 252 days on 17 names), and dropping four of six munis changes
that more than anything else in this note (§3a).

## 3. How each value was derived

### 3a. `group_cap` — not adopted

Its pre-registered rule — *k = the median |net muni-minus-taxable weight| the book
ran on its own targets, traded era before 2023, to 2dp* — reproduces **0.304953**
on 17 names [V], and on 13 names gives **0.000000 → k = 0.00**. The two remaining
muni funds have any target on only **7.4%** of pre-2023 traded days (17 names:
77.5%), so the median is zero. k = 0 is **hard group neutrality, which is in the
KILLED table**. The exposure the cap existed to bound has also mostly gone: R² of
the 13-name band's P&L to the muni-minus-taxable spread is **0.091** over the last
252 days (17 names: 0.754). **The team lead ruled: leave it off.** The operator
stays in the sleeve, off, and is re-derived by the same rule if the universe
regains municipal funds.

### 3b. `max_gross_stress = 1.80`

`G_stress = (NLV − M_other)/(m + w5)/E_book`, the pre-registered formula, with
Alpaca inputs:

| input | value | source |
|---|---:|---|
| NLV | $100,000 | probe, 2026-09-28 [V] |
| M_other | $0 | one book per account (team lead, 2026-09-28) |
| m, margin rate | 0.50 | Reg T initial margin (team lead, 2026-09-28; Alpaca's maintenance on these names is 0.30 [V, probe]) |
| E_book | $100,000 | `capital_usd` |
| w5, worst 5-session total-return loss per unit gross held, 13-name band | **0.0425814**, ending 2020-03-18 | the script; method reproduces the recorded 17-name 0.038264817497540925 to 1e-12 [V] |
| **G_stress** | **1.843041** | |

**Rule, fixed before the value was scored:** floor to 0.05 of (the lowest reading,
less the mark sensitivity). There is one reading, and **no mark sensitivity**: the
IBKR figure's 0.02× came from other books' margin, and there are none here. →
**1.80.** Not chosen: 1.843 itself (no room for the read's own movement) and "no
cap" (the 13-name band reaches **2.77×** gross, and exceeds 1.80× on **13.2%** of
traded days).

Plateau (H8), 13 names, traded era — **the value comes from the margin
arithmetic; this only shows it is not on a cliff:**

| cap × | 1.60 | 1.70 | **1.80** | 1.843 | 2.00 | none |
|---|---:|---:|---:|---:|---:|---:|
| gross SR | 1.141 | 1.155 | **1.170** | 1.174 | 1.168 | 1.160 |
| ann % | 6.96 | 7.14 | **7.29** | 7.33 | 7.37 | 7.39 |

### 3c. `min_trade_usd = 0.0`

The v6 value solved `$1 + N·hs = N·30bp` for N, where $1 was IBKR's minimum
commission per order. **Alpaca charges no commission per order** [V: Alpaca fee
schedule, fetched 2026-09-28]; its SEC, TAF and CAT fees are proportional to the
order, not fixed. The same equation with a $0 fixed cost gives **N = 0**. The team
lead ruled: follow the formula; the only floor is one whole share (fractional
shares cannot be shorted or sent to the closing auction on Alpaca [V: docs]). Paper
is scored on gross P&L (D19/D20), so a small order costs nothing scored.

## 4. Committed in advance

- **This is a report, not a gate.** The team lead ruled the change goes ahead on
  tradability grounds whatever §5 shows. §5 is recorded so the next reader knows
  what was given up.
- **Execution `shift(2)`; gross P&L on total returns is the score; the cost grid is
  a labelled sensitivity** (CLAUDE.md research rules, 2026-09-28).
- **Eras** as H5; the traded era starts 2013-06-14 as pre-registered; `k` was fit
  before 2023 (H13). `w5`'s worst window ends 2020-03-18, inside the fit period.
- **H9 is not run.** The sealed 27-name comparison set was opened once already
  (`pre-clean-slate:results/cef/HOLDOUT_OPENED.json`, verdict FAIL on net); it is not reopened for
  this change. A gap, stated.
- **H2 does not apply as a policy comparison**: 13 and 17 names are different
  books, not two policies on one book. The 13-name book trades *less* (22.2 vs
  28.8 turn/yr), so no turnover match flatters it.
- **We do not re-tune on live data.** The next legitimate change to
  `max_gross_stress` is a fresh account read at a promotion; to the universe, a
  change in what Alpaca lets us short, re-measured by the probe.

## 5. What we expect (report)

Gross P&L, total returns, `shift(2)`, band 4.8%, traded era 2013-06-14 .. 2026-09-21.

| book | gross SR | ann % | vol % | maxDD % | turn/yr | gross avg × | gross max × | net@5 | net@15 | net@30 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v6 band, 17 names | 1.54 | 10.15 | 6.57 | −9.47 | 28.8 | 1.44 | 2.77 | 1.32 | 0.89 | 0.23 |
| band, 13 names | 1.16 | 7.39 | 6.37 | −12.40 | 22.0 | 1.32 | 2.77 | 0.99 | 0.64 | 0.12 |
| **v7-on-Alpaca (13 + cap 1.80)** | **1.17** | **7.29** | **6.23** | **−12.78** | 22.2 | 1.26 | 1.80 | 0.99 | 0.64 | 0.10 |

By era, gross SR (ann %):

| book | 2005–09 | 2010–14 | 2015–19 | 2020–22 | 2023–26 | last 12m |
|---|---|---|---|---|---|---|
| v6 band, 17 names | flat | 0.86 (2.7) | 1.48 (9.9) | 2.17 (16.0) | 1.00 (6.0) | 0.16 (1.0) |
| v7-on-Alpaca | flat | 0.72 (2.2) | 0.82 (5.6) | 1.06 (6.7) | 1.90 (10.4) | 1.60 (9.9) |

**What this says, both ways.** Over the traded era the 13-name book is **worse**:
gross SR 1.54 → 1.17, a third less annual return, a deeper drawdown. The four
municipal funds carried much of the 2015–22 return. Since 2023 the 13-name book is
**better** (1.00 → 1.90; last 12 months 0.16 → 1.60), because the muni tilt that the
group cap was built to bound is what lost money recently. Both readings are
in-sample for the universe choice; none of it is out-of-sample evidence, and the
recent improvement must not be quoted as a reason for the change — the reason is
that Alpaca will not let us short those names. Net of costs the answer does not flip
sign across the grid (net@30 stays positive, 0.10).

## 6. What would make this wrong — stated in advance

- **The probe changes.** If a later probe shows any of NAD, NEA, NVG, NZF
  `shortable: true` and `easy_to_borrow` for **20 consecutive sessions**, this
  universe change is re-opened (a new trial), because its only reason is gone.
- **A kept name becomes unshortable.** If any of the 13 turns `shortable: false`
  on a session the book wants it short, that session sends **no** order for it and
  logs it; the runner must never substitute a different name. Five such sessions
  in 20 re-open the universe.
- **Margin.** If Alpaca's margin rules or the account's equity change the G_stress
  arithmetic by more than 0.05×, `max_gross_stress` is re-derived at the next
  promotion by §3b's rule, never re-tuned on P&L.
- **The kill rule stands** (spec `kill_rule`): review at 60 live sessions, counted
  from the first broker-confirmed Alpaca fill, not before.

## 7. Divergences from the backtest, stated up front

- **Alpaca paper fills MOC orders at the quote, not in the closing auction**
  [V: Alpaca staff forum post]. The backtest assumes the official close. Both P&Ls
  are recorded, labelled (team lead, 2026-09-28).
- **Paper charges no borrow and pays no dividends** [V: Alpaca paper-trading docs].
  The backtest earns distributions on longs and pays them on shorts; paper does
  neither, so paper P&L on this book will differ from the backtest by the
  distribution leg until the runner books it separately.
- **Whole shares only.** At $100k and 13 names, rounding moves each position by up
  to one share's price; the backtest trades continuous weights.
- **The vol scalar and band run on the same panel as research**; any price or NAV
  gap on a session stands the book down (ROADMAP 4.1), which the backtest never
  does.
