# Pre-registration (DRAFT, NOT APPROVED): on a thin session, trade the eligible names — `below_min_names = "trade_eligible"`, floor 4, PAPER ONLY

Date: drafted 2026-11-03. **Status: DRAFT, not approved. Nothing here trades, no spec or live file is
edited, and no counter moves.** Counter: **CEF, trial N (assigned at approval)**. The CEF counter reads
53 on `main` and on this branch [V `docs/RESEARCH_STATE.md`]. Author: an agent, for the team lead, who
chose on 2026-11-03 to pre-register this rule **for paper**. Branch `research-thin-third-rule`; origin/main
is merged at f27ef81, so trial 53's amendment 1 (#35, #36) is in view.

**Labels.**
- **[V]** computed in this session by `results/cef/prereg_thin_te4/compose.py` (2026-11-03; output
  `compose_output_2026-11-03.txt` and `.json` beside it). Fit window only: every frame ends by
  2022-12-30, asserted. Section letters (§A–§G) refer to that output.
- **[S screen]** quoted from `results/backtests/thin-third-rule-2026-11-03/REPORT.md`, the zero-trial
  screen. **[S thin-days]** from `results/backtests/thin-days-2026-11-03/REPORT.md`. **[S T53]** from
  `results/cef/PREREG_VOLTARGET_2026-10-30.md` or `results/cef/prereg_voltarget/FLATTEN_REMEASURE_2026-11-02.md`.
  These are not re-run here, except where compose.py §A reproduces them; that is said where it applies.
- **[U]** an interpretation, or arithmetic on stated inputs.

**Panels and spec.**
- **Panels.** Prices end 2026-10-15 and NAV 2026-10-14. The screen cuts every return at DIST_END,
  2026-09-03 [S screen]. compose.py reads fit rows only, 2005-01-03 → 2022-12-30. Every panel is three to
  seven weeks stale against 2026-11-03.
- **Spec.** `cef_discount.v9.20261102`, on this branch and on `main`, read through `scripts/cef/spec.py`
  [V]: `sizing_multiplier` 1.30, `band_width` 0.048, `max_gross_stress` 1.8, `min_names` 6,
  `min_abs_weight` 0.005. Tag `release-20261103-1` carries the same spec id [V `git show`].
- **Prod.** Which tag prod runs, and whether it is armed, is **UNMEASURED here**. This task may not
  reach the VM; `python3 -m ops.orient` PROD answers it.

---

## 0. The draft in one table

| item | answer |
|---|---|
| **what changes** | One frozen key gains a value, and one key is new: `below_min_names: "trade_eligible"` and `below_min_names_floor: 4`. **Absent is today's rule, flatten**, and must be proved byte-identical (§1.6). On a session with fewer than `min_names` (6) but at least 4 eligible names, the core builds its book on the eligible names with its own construction, instead of closing every position. Below 4 it goes flat, as today (§1.1, §1.3) |
| **paper only** | Like the book json's `late_market` exception, it never applies to a live-money account. Today the broker client can reach only the paper endpoint. The implementation adds a run-time refusal of this key against any other endpoint, plus the written scoping (§1.2) |
| **why** | It earned the **highest gross return in every window** of the screen: fit 5.77% against hold 3.29% and flatten 1.58%/yr; 2023+ 11.50 / 10.61 / 10.63 [S screen]. Paper is scored on gross P&L with no borrow (team lead D19/D20, 2026-09-15). That is the whole case, and it is a gross case |
| **against it, up front** | **Not shown to be alpha** (§2.1). Matched-turnover gap +2.13pp/yr (t 2.34): INCONCLUSIVE under the 2.818 bar. Two names (PHK, PDI); 87% of the gap is PIMCO. Holdout +0.87 (t 0.72), one episode. Nine fit episodes at the bar, not over it. Forward power is about a coin flip only after 5 episodes, which is 7 to 18 years away |
| **real money** | **Negative where borrow is measured**: −2.33pp/yr against flatten on 2023+ fees. It shorts rich PIMCO funds when they are dear to borrow [S screen]. Before 2021-09-13 borrow is unmeasured |
| **the floor** | 4, **derived from the construction, not swept**. One name is 0/0, two carry only a sign, three force one side onto a single fund; four is the first count with none of these. 3 was the fit argmax and **is not chosen** (§3) |
| **today's effect** | **Zero.** No session has been thin since 2023-08-30 (783 sessions to 2026-10-14). But the least-liquid eligible name has sat at a median 1.13× the $3m ADV floor on 6–7-name sessions since 2023 [S screen §7] |
| **evaluation** | Forward only: 2023+ has been seen (H13). The unit is a **thin episode**: runs of reduced sessions merged when fewer than 63 sessions apart. The statistic is the account's broker-confirmed gross P&L of record over the episode's thin earning days, against flatten's exactly zero. The cost grid, the borrow it would have paid, the closing-print view and the modelled re-entry leg are labelled beside it (§4) |
| **verdicts** | PRESENT: the episode t clears the t(k−1) critical value at the bar's p, read at N on the read date. ABSENT, and revert: the first two episodes both negative, or the mean ≤ 0 at any read from the third. KILLED: an in-episode stop fires (§6) |
| **power** | Exact small-sample P(PRESENT) at the fit effect is 0.10 after 5 episodes, 0.43 after 9, 0.74 after 13; at the holdout-shrunk effect 0.02 / 0.07 / 0.13 (bar at N = 54) [V §G]. **This trial cannot establish alpha in any useful time.** What it can do on paper: score the gross, catch the bad case (P(ABSENT by the third episode) 3.1% at the fit effect, 52.7% at zero) and bound the risk inside an episode |
| **in-episode kills** | K1, drawdown inside an episode ≥ D_E (10.52% on drafting day). K2, the largest single-name position above the fit maximum (0.956 × equity). K3, \|net\| above the fit p99 (0.248) on 3 consecutive reduced sessions, or above the fit maximum (0.833) once. **Each is re-measured on the read date by compose.py §E (H14)** |
| **composition with trial 53** | **m = 1.30 multiplies the reduced book too, and trial 53's figures move** (§7.2). On W1 at ×1.30 with deferred flips: maxDD 13.79% against 8.63% (total return), crossing the spec's 12% HALVE line. Zero-edge P(HALVE) / P(KILL) while trading: 23.2% / 3.28% against 17.1% / 1.75%. Trial 53's rule fed te4's trading-session sd gives ×1.15, not ×1.30. The approved R3 fires 8.3% of the time on te4's fit mix, against its 5% design [V §B–§D]. Recommended: keep m; read R1–R3 on full sessions only; this trial's K1–K3 cover reduced sessions (§7.3, Q3) |
| **deferred flips** | On 4–5 names, a deferred flip of a one-fund side leaves the book one-sided for a session: \|net\| up to 0.833 of NAV on the fit (2019-10-09), against 0.235 with instant flips [V §E] (§7.6) |
| **revert** | Set `below_min_names` back to `"flatten"`, or delete both keys. The sleeve is then v9's, byte for byte, by the same pins. A revert during an episode closes the book at the next reduced decision (§6.5) |
| **trial** | CEF trial N (assigned at approval). The counter moves only in the commit that records the approval, and the bar is read from the counter on the read date (§9) |

---

## 1. What changes

### 1.1 The key and the value

| | today (v9) | after (v10) |
|---|---|---|
| `below_min_names` | absent, which the registry reads as `"flatten"` (`src/deploy/registry.py::cef_below_min_names`) | **`"trade_eligible"`** |
| `below_min_names_floor` | does not exist | **`4`**: required when, and only when, `below_min_names` is `"trade_eligible"`; refused under `"flatten"` and `"hold"`, as the harness refuses `floor` (`band_frontier.band_gross_capped`) |
| spec id | `cef_discount.v9.20261102` | `cef_discount.v10.<activation date>`, through `/spec-change`, with tag `spec-cef_discount.v9.20261102` pushed first |
| `_below_min_names_note` | — | the WHAT / DERIVED / NOT CHOSEN / **PAPER ONLY** / READ BY / NO-OP PROOF / REVERT note, in the house shape of `_sizing_multiplier_note` |

**UNITS.** The floor is a count of eligible names, not a weight and not a fraction. The registry refuses a
non-int, a bool, anything below 2 (one name is 0/0) and anything at or above `min_names` (at `min_names`
the rule is flatten). **It does not hard-code 4.** The spec is the only authority on a live parameter
(CLAUDE.md), and the derivation's reason for 4 lives in the note.

**The default is today's.** With both keys absent, or `below_min_names: "flatten"` written explicitly, the
sleeve is v9's byte for byte (§1.6). C4's `"hold"` is untouched.

### 1.2 PAPER ONLY, and the mechanism that enforces it

The rule is chosen *because* paper scores gross without borrow (§2.3). On a live-money account its measured
sign is negative, so **it never applies to a live-money account**, as the book json's `late_market`
exception never does.

**What enforces `late_market` today** [V, read in the code at this branch's HEAD]:
1. **The broker client cannot reach a live account.** `quantt/broker/alpaca.py`: `AlpacaClient.__init__`
   raises on any trading endpoint other than `PAPER_BASE = "https://paper-api.alpaca.markets"` (l.348).
   `submit_order` checks again before every order (l.610). No book in this repository can send an order to
   a live account until a new client is written.
2. **The written scoping.** CLAUDE.md order-path rule 3 ("It never applies to a live-money account"). The
   book json's `execution._note` ("PAPER ONLY ... Not for a live-money account"). `docs/SYSTEM.md` §5,
   2026-10-09 ("the paper `late_market` exception never applies to a live account").
3. **There is no code check of `late_market` against the account type.** `run.execution_for` validates
   the mode and the window only (l.980–1002). Its enforcement is (1) plus (2).

**What enforces it for this key**, required in the implementation (the owning session's files, §1.5):
1. **The same paper-only client**, unchanged.
2. **A run-time tripwire.** The runner refuses to decide a book whose sleeve spec sets
   `below_min_names: "trade_eligible"` unless its broker client's trading endpoint is exactly
   `alpaca.PAPER_BASE`. It raises `SessionError`, naming the key and the endpoint. A test must fail
   without the check. **Today the check is unreachable** (the client can be nothing else). It exists for
   the day a live client is written, so that this key refuses rather than trades.
3. **The written scoping.** The spec note opens "PAPER ONLY; never for a live-money account; delete this
   key before any live-money arming of the core". At approval, a row in `docs/SYSTEM.md` §5 records the
   ruling, beside the 2026-10-09 `late_market` row.
4. **The standing real-money gate**: "the real-money cost re-run is the gate for deploying any capital"
   (`docs/SYSTEM.md` §5, 2026-10-09). This trial's borrow column (§4.4) is part of what that re-run
   would read.

### 1.3 Exactly how the sleeve would build the reduced book

`src/deploy/sleeves/cef_discount.py::target_positions`, read at this branch's HEAD. Line numbers are
today's; the screen read the same lines 37 earlier, e.g. l.841 / l.928. **Nothing below is edited here.**

| step | where (today) | under `trade_eligible`, on a session with floor ≤ n < `min_names` eligible |
|---|---|---|
| eligibility | l.831–876 | **unchanged**. A finite z (rolling `z_window`, `.shift(1)`, clipped at ±4); a measured ADV of at least `min_adv_usd` ($3m; 63-session mean, `.shift(1)`); a NAV no older than `max_nav_age_bd`; not held by the stale-NAV or missing-NAV gate |
| the thin test | l.878, `len(row) < min_names` | n < 4: **FLAT every name, today's rule, unchanged**. 4 ≤ n < 6: **do not return; build on `row`** |
| z-neutralisation | l.948–950 | **unchanged code on the smaller set**: w = −(z − z̄) / Σ\|z − z̄\| over the n eligible names. Dollar-neutral; Σ\|w\| = 1; longs ½, shorts ½. On 19.1% of fit reduced decisions one side is a single fund [V §E] |
| vol scalar | l.953–957 | **unchanged**: rv = the annualised sd of the last 63 sessions of Σ wᵢrᵢ over these n names (today's w on past returns, panel through the decision date); w ← w × clip(0.06 / rv, 0.2, 2.5) × `gross_leverage` (1.0). On reduced decisions the scalar's median is 1.007 (p99 2.239, max 2.418), and it never reached a clip on the fit [V §E] |
| **`min_abs_weight` and the re-neutralisation guard** | l.963–970: `keep = w[\|w\| >= 0.005]`; `if len(keep) >= min_names:` re-neutralise | **Declared: the guard stays as written, comparing with `min_names`.** For any reduced set n ≤ 5 < 6, so **a reduced set is never re-neutralised**. w is kept as built, and a name under 0.005 is flattened at the output by the dust filter (l.1245), after the band. Today's sleeve already does exactly this on any ≥ 6-name session where fewer than 6 names survive the filter. **The consequence is bounded by construction**: the net residual is Σ of the dropped names' \|w\|, each under 0.005 unit. **Incidence:** the block found a sub-0.005 name on 127 of te4's 1,708 traded reduced sessions [S screen §2] |
| group cap | l.997–1000 | not set on the core spec; unchanged |
| band | l.1084–1135 | **unchanged**. The unit target is compared with held / (NAV × m); a name more than 0.048 from target trades to the band EDGE. A name no longer eligible has target 0 and is cut to ±0.048, not closed. These band residues hold about 10 names on a 4–5-name session and are below the ADV floor [S screen §5] |
| gross ceiling | l.1157–1164 | **unchanged**. `_cap_gross(w, max_gross_stress / m)` = 1.8 / 1.30 = 1.385 unit, one uniform scale-down. The held book sits at the cap on 16.9% of fit reduced decisions, against 14.6% of full ones, at ×1.30 with deferred flips [V §E] |
| output | l.1185–1263 | **unchanged**. Weight targets are m × the unit weight; a band HOLD is a share count; the dust filter reads the unit weight; decide sizes whole shares |

**New pieces** (the implementation's; not here):
1. **No silent 0/0.** On a reduced set, a non-finite weight (every z equal) **raises**, naming the
   session and the names. Today's full-book path holds silently on 0/0 under a false reason (PR #33 §5.H).
   That path is the owning session's open question 4 there, and this draft does not inherit it. No fit
   reduced session had a 0/0 row [S screen §1].
2. **A structured record of the reduced set.**
   - Every target carries `meta["cef_reduced_set"] = {"eligible", "min_names", "floor"}`, and the reason
     says "reduced set".
   - plan.json records the eligible count and a `reduced` flag as structured fields. The scorer (§4)
     never parses a reason string, as `docs/RUNNER.md` already requires for `cef_short_of_min_names`.
3. **The NAV holds** (l.929–946), with holds present:
   - If `len(row) + len(held_out) >= min_names`, the **whole book holds, unchanged** ("holds never trigger
     the flatten", and they never trigger a reduced build either).
   - Otherwise, if `len(row) >= floor`, the reduced build runs on `row`, and held names keep their shares,
     as on a full day.
   - Otherwise, today's rule applies.
   - A reduced build is a decide on the signal, so it carries **no** `cef_short_of_min_names` tag. The tag
     stays on the hold and flatten returns.
4. **Unchanged on purpose.**
   - `strict` (l.749: raise rather than flatten on a missing panel) is still set only by `panel_source` or
     `"hold"`. A data shortfall under `trade_eligible` flattens, as today.
   - `gate.max_missing_nav_holds` stays n − `min_names`. This rule does not widen the missing-NAV
     tolerance.

**Why the guard is not moved to the floor.**
- **Re-neutralising a 3-name survivor set would recreate the 3-name degeneracy** that the floor exists to
  exclude: one side would be a single fund carrying half the gross. That happens when a 4-name set loses
  one name to the dust filter.
- **Two thresholds for one block is a second rule.** With the guard at the floor, a 5-name session with
  one dust name would re-neutralise while a 6-name session with two would not.
- **The alternative's effect is the same size.** The screen's sleeve check lowered `min_names` to 3 in
  memory, so on those 127 sessions it *did* re-neutralise. The largest weight difference from the harness
  was 0.0050 [S screen §2]. The declared rule differs from the harness by the dropped names alone, each
  under 0.005.

### 1.4 What does not change

The signal; the universe (13 names); every other frozen key; `sizing_multiplier`; the band; the ceiling;
`min_names` itself (6: still the line below which the full construction is not used); every gate; the
deferred-flip rule; the execution mode. **On any session with 6 or more eligible names the target is
identical under both rules** [V §A: te4 and the spec build the same target on every fit session with ≥ 6
eligible, asserted].

### 1.5 The files that would change (owned by the other session; listed, not edited)

| file | change |
|---|---|
| `ops/specs/cef_discount.frozen.json` | the two keys and the note; v9 → v10 (`/spec-change`) |
| `src/deploy/registry.py` | `CEF_BELOW_MIN_NAMES` gains `"trade_eligible"`; a new `cef_below_min_names_floor(frozen)`; `_validate_cef_discount`; the misspelling guard's key list (`CEF_C4_KEYS`, 2 edits) gains `below_min_names_floor` |
| `src/deploy/sleeves/cef_discount.py` | the `min_names` block (l.878–946): the reduced branch, the holds interplay, the 0/0 raise, `meta["cef_reduced_set"]`; a comment at l.965 saying the guard is deliberately left at `min_names`; the module docstring |
| `quantt/session/run.py` | the paper-only tripwire (§1.2); plan.json's structured eligible count and `reduced` flag |
| `scripts/cef/spec.py`, `ops/orient.py` | expose and print the key (SPEC), as for `sizing_multiplier` |
| tests | `src/deploy/tests/test_below_min_names_trade_eligible.py` (the reduced target equals `band_frontier._target_row` then the band and the cap, on synthetic panels and on the real fit panel; floor validation; the holds interplay; the 0/0 raise; the guard). `quantt/session/tests/test_trade_eligible_noop.py` (pins, §1.6). The tripwire test. **Each fails against the old code before it is kept** (CLAUDE.md) |
| a scorer | a read-only script that computes §4's statistics from `<state>/eod_equity.csv`, plan.json, the fills and the closing prints; required in the activation release |
| `docs/RUNNER.md`, `docs/SYSTEM.md` §5, `docs/RESEARCH_STATE.md`, `docs/JOURNAL.md` | the rule, the paper-only ruling, the ledger (§9) |

### 1.6 The no-op proof and the revert

`/spec-change`'s proof, before the key is set:
1. **Key absent**, and **`below_min_names: "flatten"` written explicitly**: the sleeve's targets,
   plan.json, the orders and plan_sha are byte-identical to v9's code. They are pinned from the code
   *before* the change, as `quantt/session/tests/test_c4_keys_noop.py` and `test_sizing_multiplier_noop.py`
   pin theirs.
2. **Key set, on every real-panel date with ≥ 6 eligible**: the targets are byte-identical to v9's. That
   is every date since 2023-08-31 [S screen §7]. The diff covers every such date on the live panel, not a
   sample.
3. **Key set, on a reduced date**: the targets equal `band_frontier._target_row` → band → `_cap_gross` on
   the same panel, to ≤ 1e-12, except names under `min_abs_weight` (§1.3). The screen's sleeve check is
   the model (`sleeve_reduced_check.py`).

**REVERT:** `below_min_names: "flatten"`, or delete both keys. The spec id moves again through
`/spec-change`, and pin 1 proves the reverted sleeve is v9's. Or restore it whole with
`git show spec-cef_discount.v9.20261102:ops/specs/cef_discount.frozen.json`.

---

## 2. Why, mechanically — and every finding against it, first

### 2.1 Against: what the screen's attacks found (all [S screen] unless marked)

| # | finding | figure |
|---|---|---|
| 1 | **At matched turnover (H2) it is under the bar.** te4 trades 2.3× flatten's fit turnover (19.3 against 8.5/yr). Re-banded to flatten's turnover (the device declared before the first run), the gap is INCONCLUSIVE | **+2.13pp/yr, NW t 2.34** against the bar 2.818 at N = 53; interval [−0.87, +5.14]. Unmatched it reads t 4.51, but that is not an H2 comparison |
| 2 | **Two names.** | without PHK's and PDI's own P&L: +1.08 (t 1.43). A universe rebuilt without them: +2.23 (t 3.55), from 2020–22 only. The methods disagree; both are shown |
| 3 | **One sponsor.** | the six PIMCO funds carry +3.63 of +4.19pp/yr (87%); the other seven names +0.56 |
| 4 | **Independent episodes are at the bar, not over it.** | 9 fit episodes, all positive, t 3.68 against a t(8) critical value of 3.86; sign test p 0.0020 against 0.00242 |
| 5 | **The holdout does not show it.** | 2023+: +0.87pp/yr (t 0.72), one 138-session episode (+3.02pp); direction control p 0.242. **H13 is now seen for this rule** |
| 6 | **Forward power is inadequate.** | P(pass) 0.47 at 5 episodes at the fit effect (normal approximation, generous); 0.07 at the shrunk effect; 7.0 years at the fit-period rate, 18.4 at the rate since 2023 |
| 7 | **Against hold it is not robust.** | matched turnover −0.26 (t −0.30) |
| 8 | **Not every metric favours it.** | flatten has the shallowest drawdown in every window from 2015 on, and the best H13 Sharpe (2.07 against te4's 2.01) |
| 9 | **The hindsight universe.** | 77% of fit earning days (3,484 of 4,531) follow a thin decision, because the 2026 universe is projected back into years when most of it was illiquid. **These files cannot measure that hindsight.** Forward thin sessions, if any, come from one name's ADV dipping, which is a different process |
| 10 | **Concentration.** | a single name holds ≥ 0.5 of NAV on 27% of thin sessions, against 10% of active ones [S beta-detector]. At ×1.30 the held book's largest name is 0.498 of NAV at the median and 0.956 at the fit maximum [V §E] |
| 11 | **Band residues below the ADV floor.** | about 10 names held on a 4–5-name session, most at their band edge |
| 12 | **The signal decays fast.** | half the thin-day P&L is gone when the signal is 5 sessions old; a static tilt loses money (−1.63) |

### 2.2 For: the gross case, and its mechanism

- **The score.** te4 has the highest gross return in every window and with both flip modes. Fit: 5.77
  (instant) / 5.35 (deferred) against hold 3.29 / 3.16 and flatten 1.58 / 1.46%/yr. 2023+: 11.50 / 10.95
  against 10.61 / 9.85 and 10.63 / 10.34 [S screen §3].
- **Why gross.** The paper account is scored on gross P&L, with no borrow and no execution cost (team lead
  D19/D20, 2026-09-15). **That is the reason the team lead chose paper.**
- **The mechanism** [U, a reading]. The z-score's relative-value bet does not need six names to be
  defined; it needs a cross-section in which no side is forced onto one fund (§3). Flattening discards the
  signal on exactly the days it still exists.
- **Where the gap comes from.** It is real gross P&L on the panel, and its sign follows the signal:
  - not factor beta: alpha +6.26pp/yr (t 4.41), every |β| ≤ 0.06;
  - not stale prices: it survives one extra session of delay, +3.06 (t 3.62);
  - not distributions: the price leg is +4.22 of +3.94;
  - the direction matters in the fit: p < 0.002 over 500 reassignments.

  [S screen §6]
- **On paper the comparison is gross**, and the cost grid shows what the extra turnover would cost
  (§2.3). Against flatten the fit gap stays positive across the grid: +3.65 / +2.58 / +0.96pp/yr at 5 /
  15 / 30bp. In 2015–19 it flips at 30bp (−1.98) [S screen §3].

### 2.3 Real money: negative where borrow is measured

| measured window | te4 − flatten, gross → net of borrow |
|---|---|
| 2021-09-14 → 2022-12-30 | +7.72 → +2.79pp/yr (borrow took 64%) |
| 2023-01-03 → 2026-09-03 | **+0.87 → −2.33pp/yr** |
| before 2021-09-13 | **UNMEASURED** (the IBKR FEE_RATE panel starts then) |

[S screen §5]
- **A back-cast, not history** [S screen, U]: the fit at each name's median fee is +2.21; at its p90 fee,
  −2.67.
- **Why borrow takes it.** te4's thin-day shorts paid 27.9%/yr, size-weighted, in 2023, against a 6.7%
  median fee for the same names. The signal shorts rich funds when they are dear to borrow [S
  beta-detector].
- **Capacity** [U]: real money would also meet band residues below the ADV floor, and a least-liquid
  eligible name near 1.13× the floor.
- **This is why the rule is paper only (§1.2).**

### 2.4 The graveyard

Nothing in `docs/RESEARCH_STATE.md`'s KILLED tables is a thin-session rule [V, read 2026-11-03].
- **The nearest relatives** are "sizing up on |z|" and "sizing up on dislocation". Both are conditional
  sizing. This rule changes which sessions the unchanged construction runs on, not how it sizes.
- **The usual causes of death were checked** by the screen. A stale-price artefact: zero-return name-days
  4.22% on thin days against 4.70% on active ones, and no zero-volume day. A control scoring as well as
  the treatment: the direction control passes in the fit (p < 0.002) and **fails on H13 (p 0.242)** [S
  screen §6].

---

## 3. How the floor was derived

**From what the construction does at each count n** (the screen's §1, written into the harness's
docstrings before its first scoring run; the build is one commit, so git cannot show that order) [S
screen]:

| n | w = −(z − z̄) / Σ\|z − z̄\| | breaks? |
|---|---|---|
| 1 | z − z̄ = 0, so 0/0 | **undefined** |
| 2 | w = ±½ whatever \|z₁ − z₂\| is: the sign only, and each crossing reverses the whole book | **sign only** |
| 3 | the demeaned values sum to 0, so one side is one fund carrying ½ of the gross | **forced single-fund side** |
| 4 | a 2–2 split is possible; one side is a single fund on 27.3% of 4-name and 16.0% of 5-name sessions [S] (19.1% of fit reduced decisions [V §E]) | possible, not forced |

**The floor is 4**: the smallest count with none of the three degeneracies. Below it the rule does what the
sleeve does today, FLAT.

**The plateau (H8)**, read on the fit only [S screen §4]:

| floor | te − flatten, FIT, pp/yr (NW t) | per unit share of sessions traded |
|---|---|---|
| 3 | **+4.59 (4.61)**: the argmax | +10.83 |
| **4** | **+4.19 (4.51)** | +12.10 |
| 5 | +3.17 (3.74) | +12.42 |

- **The argmax, floor 3, is not chosen.** It is the count the derivation excludes: 3 names force a
  single-fund side. Choosing it would be choosing the sweep over the construction (the `z_window = 63`
  lesson).
- **4 sits on a plateau.** The sign is the same at all three floors in every fit era where they differ,
  and the edge per traded session is nearly flat. The floor sets how many sessions trade, not what each
  earns.
- **H13 could not have steered it.** Since 2015 every thin session has had 4 or 5 eligible names, so te3
  and te4 are the same book from 2015 on, and all three floors are identical on H13.
- **Not re-tuned live.** The next legitimate change to the floor is a re-derivation from the construction
  (for example, if `min_names` or the construction changes), never a re-sweep.

---

## 4. Committed in advance: the evaluation, forward only

### 4.1 What evidence is clean

**Only forward thin episodes.**
- The fit (2005–22) is in-sample for the screen.
- 2023+ was printed by the screen, so H13 is seen for this rule.
- **No historical window is clean**, and none is re-read as evidence here.
- compose.py reads fit rows only, to state composition and calibrate stops. It judges nothing.

### 4.2 The unit: thin episodes, not days

| term | definition (committed) |
|---|---|
| reduced decision | a decide whose plan.json records `floor ≤ eligible < min_names` under the spec in force; the sleeve's own count, read from the structured field (§1.3), never re-derived from a reason string |
| below-floor decision | eligible < floor: flat under both rules (both earn 0 on its earning day) |
| thin earning day | the session two sessions after a reduced decision: decide at t (evening), late-market fill at t+1, earn t+1 close → t+2 close (shift(2)) |
| episode | runs of reduced decisions merged when **fewer than 63 sessions** apart: `build_panel`'s ADV window, the screen's rule (`third_rule.episodes`); below-floor decisions inside it contribute 0 |
| completed | 63 sessions after its last reduced decision with no new one; an episode is read only when complete, so the merge is final |

Why episodes, not days.
- The days inside an episode share one liquidity state and one trailing-ADV window, so they are not
  independent.
- The screen's day-level reading (t 4.51) overstates the evidence 9 episodes give (t 3.68) [S screen].

### 4.3 The per-episode statistic, and its counterfactual

**E_k (the paper score; gross; broker-confirmed)**: the sum of the account's daily return of record
over episode k's thin earning days.
- The daily return is equity_d / equity_{d−1} − 1, with no cash flows on paper.
- Equity is read from Alpaca's end-of-day portfolio history, `<state>/eod_equity.csv`: the official P&L
  (team lead 2026-10-19), the series the drawdown report already reads.
- It is price only: paper pays no distributions.
- No cost and no borrow are charged.

**The flatten counterfactual is exactly zero on those days.** Flatten holds no book after a reduced
decision, so E_k needs no model. It is te4's P&L minus flatten's, as the screen's episode value is
(compose.py §A reproduces the screen's nine values from this definition to 1e-17).
- **Two parts of the difference are not in E_k**, and are labelled beside it (§4.4):
  - the re-entry trades flatten would make and te4 avoids;
  - the slightly different book te4 carries into the first full sessions after the episode.
- **The last minutes before the t+1 late window** are not in E_k either. Both rules hold the same book
  until then [U: small].

### 4.4 Labelled beside E_k, never mixed into it

| column | what | provenance |
|---|---|---|
| **E_k, closing-print view** | the same days, with positions marked at the official closing-auction prints and each late fill replaced by that session's official print | modelled on broker positions; CLAUDE.md's "record both", labelled separately |
| **net at 5 / 15 / 30bp** | E_k − c × (te4's traded notional over the episode's reduced decisions and the first full decision after it − flatten's counterfactual notional) / NAV. Flatten's notional is the exit of the held book at the episode's first reduced decision, from broker positions, plus its re-entry to the band edge at the first full decision. **Say whether the sign flips across the grid** | te4's leg from broker fills; flatten's exit from broker positions; **flatten's re-entry MODELLED** (the sleeve, read-only, key absent, against a flat book) |
| **borrow it would have paid** | Σ over thin earning days of short market value × fee / 360 × 1.02, `bf.borrow_charge`'s definition, from the freshest measured fee covering those dates | **UNMEASURED today, and so stated, never a default.** The IBKR FEE_RATE panel ends 2026-09-09 and IBKR is retired; Alpaca paper has no locates and no borrow fees |
| **re-entry leg R_k** | over the 63 sessions after the episode, the account's P&L of record minus the flatten-shadow book's (the sleeve read-only with the key absent, from flat, marked at closes) | **MODELLED**; never in a verdict. Fit analogue: +0.25 of +4.19pp/yr [S screen §3] |
| **concentration and net** | each reduced session's realised largest \|position\| / equity and \|net\| / equity, from Alpaca positions at the close | broker-confirmed; feeds K2 and K3 |
| **turnover** | te4's and the counterfactual's per episode. **H2 cannot be matched live** (the book has one band); the fit's matched comparison is INCONCLUSIVE (§2.1) | as above |
| **attribution** | E_k by name and by sponsor; E_k without PHK's and PDI's own P&L | broker positions × closes |
| **direction control** | the episode's reduced-set weights reassigned at random among the same names, 500 draws, seed 20261103 + k, → p | **MODELLED** on the panel; a negative control, not a decision rule |

**Negative control.** On every full session (≥ 6 eligible) te4 and flatten build the same target, so the
mechanism cannot act there. **Outside the 63-session re-entry window**, any difference between the
account's targets and the flatten shadow's is an implementation fault, to be found, not scored.

### 4.5 Conventions

- shift(2), the late-market send (8 to 2 minutes before the close), deferred flips: as the live runner.
- **Gross P&L is the headline**; the cost grid is the real-money view, beside it. Borrow is separate.
- The bar is √(2 ln N), with **N read from `docs/RESEARCH_STATE.md` (orient TRIALS) on the read date**,
  never from this note.
- **The floor is not re-tuned**, and **no verdict reads a 2023+ or fit return.**

---

## 5. What we expect

Each figure has its uncertainty; being wrong here is the point.

1. **Now: nothing.**
   - No session has been thin since 2023-08-30: 783 sessions to 2026-10-14. 192 sessions had exactly 6
     eligible names, the last on 2026-02-12 [S screen §7; S thin-days §5.I].
   - Until a thin session occurs, the key is inert, and the book is v9's.
2. **The forward rate is unknown.**
   - It was 0.71 episodes a year over the fit, 0.27 since 2023, and 0 since 2023-08-30 [S screen §6.M].
   - **What moves it** is one name's ADV dipping under $3m. On 6–7-name sessions since 2023, the least
     liquid eligible name sat at a median 1.13× the floor, p10 1.03× [S screen §7]. On 2026-10-14 AWF was
     just under it, at $2.97m [S thin-days §5.I].
   - Re-measure at run time: the eligible count is in plan.json every day.
3. **Per thin earning day, gross**: about +5.5 to +11.4%/yr of unit book. The low end is the holdout's
   rate and the high end the fit's [S screen §6.M].
   - At ×1.30 that is **about +2.8 to +5.9pp of NAV per 100 thin earning days** [U: × 100/252 × 1.30].
   - The holdout's rate is the only out-of-sample analogue, so expect the low end.
4. **Per episode.**
   - Fit episodes at ×1.30 with deferred flips, price only: mean +9.95pp, median +7.82pp; 8 of 9 positive;
     lengths 28 to 390 thin earning days, median 195 [V §F].
   - **Forward episodes from a one-name dip may be much shorter.** The per-episode effect then shrinks
     roughly with √length: about 1.71 × √(L/252) at the screen's day-level Sharpe [U]. That is 0.48 for a
     20-day episode, and power falls with it (§6.2).
5. **Per year, if thin sessions recur at 2023's share (15%)**: about +0.8 to +2.0pp/yr gross at ×1.13 [S
   screen §7], so roughly +1.0 to +2.3 at ×1.30 [U: scaled by 1.30 / 1.13; the cap makes this approximate].
   - On real money the same rows read −2.9 and −2.1pp/yr at ×1.13, after extra turnover at 15bp and 2023+
     borrow [S screen §7]; more negative at ×1.30, since both costs scale with the book [U].
6. **Risk inside an episode** at ×1.30 with deferred flips, from the fit [V §E, §F]:
   - within-episode drawdowns of 2.2–8.9%;
   - the largest single name 0.53–0.96 of NAV;
   - a one-session \|net\| that can reach 0.83 after a deferred flip (§7.6).

---

## 6. What would falsify it, what kills it, and the revert

### 6.1 Verdicts, read at each completed forward episode

| verdict | rule (committed) | action |
|---|---|---|
| **H-TE PRESENT** | at k completed episodes: the one-sample t of E_1..E_k ≥ the t(k−1) critical value at the bar's one-sided p (bar √(2 ln N), N read on the read date). **And** the same t on E_k without PHK's and PDI's own P&L (attribution) is > 0: the screen's two-name finding, declared as a gate (§2.1 row 2). The exact sign-flip p is reported beside it | keep; recorded with its D-code. Promotion to real money still needs the real-money gates (§1.2) and a new ruling |
| **H-TE ABSENT** | E_1 < 0 and E_2 < 0; **or** at any read with k ≥ 3, mean(E_1..E_k) ≤ 0 | **revert the same day** (§6.5) |
| **KILLED (risk)** | any of K1–K3 (§6.3) | **revert the same day**; the episode values to date are recorded |
| **INCONCLUSIVE** | none of the above | keep. The team lead reviews at each completed episode and at each anniversary of activation, with this note's power table in hand |

**Why this falsifier.** P(ABSENT by the third episode) is 3.1% if the fit effect is true, 18.8% at the
holdout-shrunk effect and **52.7% if the rule earns nothing** [V §G, 200,000 simulated draws]. It is a
coarse test against zero, and the honest one that this many episodes allow. **The rules are not
softened later.** Extending the episode count, lowering the bar or dropping the PHK/PDI gate is a new
trial.

### 6.2 Power: forward P(PRESENT) by number of episodes

Per-episode effect (mean / sd) of the fit episodes at ×1.30, deferred, price only: **1.16**; at the
holdout's shrink (×0.49): **0.56** [V §F, §G]. Bar at N = 54 shown (2.825); N = 53 and 55 differ in the
third decimal [V §G].

| episodes k | t(k−1) critical | P(PRESENT), fit effect: exact t / normal approximation | P(PRESENT), shrunk: exact t / normal | years at 0.71/yr | years at 0.27/yr |
|---:|---:|---|---|---:|---:|
| 3 | 14.48 | 0.023 / 0.21 | 0.009 / 0.03 | 4.2 | 11.0 |
| 5 | 5.68 | **0.098** / 0.41 | 0.021 / 0.06 | 7.0 | 18.4 |
| 9 | 3.87 | 0.43 / 0.74 | 0.065 / 0.13 | 12.7 | 33.0 |
| 13 | 3.46 | 0.74 / 0.91 | 0.13 / 0.21 | 18.3 | 47.7 |
| 20 | 3.20 | 0.96 / 0.99 | 0.29 / 0.38 | 28.1 | 73.4 |

Exact power is from the noncentral t; the normal approximation is the screen's `inference.p_clear_bar`
and is generous at small k [V §G]. Years are k divided by the rate [U on S screen §6.M rates].

**Reading.** PRESENT is out of reach for a decade or more, and shorter forward episodes (§5 item 4) push
it further. **This trial measures gross paper P&L and risk on thin sessions; it does not establish
alpha.** That is said here, before any session trades it.

### 6.3 In-episode kills (H14: every threshold re-measured on the read date)

Thresholds below are **drafting-day values only**. Each is recomputed by re-running
`results/cef/prereg_thin_te4/compose.py` (§E) on the read date. The script reads m, the band, the
ceiling and `min_names` from the frozen spec at run time, and the floor from the spec once the key
exists.

| kill | statistic (live, broker-confirmed) | threshold: rule (drafting-day value) | fit check |
|---|---|---|---|
| **K1, drawdown** | the running maximum drawdown of the account's P&L of record, compounded over the episode's thin earning days joined end to end, from the episode's start (the full sessions between merged runs are R1's and HALVE's) | **D_E**: the 95th percentile of the 252-session maximum drawdown of te4's reduced-session earning-day series on the fit, at the spec's m, deferred flips; the largest of SB21 / SB63 / GAUSS; the worse of TR and PR. Trial 53's R1 construction on reduced sessions (**10.52%**; 21 / 63 / 126-session values 4.13 / 6.62 / 8.51% printed for context) | no fit episode reached it: worst 8.90% PR, 2017-06-21 → 2018-12-19 [V §F] |
| **K2, single name** | on any reduced session's close, the largest \|position market value\| / equity | **above the fit maximum** of the same statistic for te4's held book at the spec's m, deferred (**0.956**) | by construction, never on the fit; the fit p99 is 0.891 |
| **K3, net** | on reduced sessions' closes, \|long − short market value\| / equity | **above the fit p99 on 3 consecutive reduced sessions (0.248)**, or **above the fit maximum once (0.833)** | the 3-in-a-row rule never fired on the fit; 2-in-a-row happened once [V §E] |

**Under either outcome of a re-measure:**
- If the read-date threshold has moved, because m, the band, the ceiling or the panel's fit rows moved,
  the new value governs. The note's numbers do not.
- If compose.py cannot run (a panel is missing or a reproduction assertion fails), the threshold is
  **UNMEASURED**. The rule is then to revert at the next reduced decision unless the measurement is
  restored first. A stop that cannot be read does not count as passed.

**Who acts.** The team lead, through `/spec-change`, the same day a kill reads true. No code acts on these
thresholds; this follows trial 53's convention. The implementation should add a K1–K3 line to the
drawdown report in report mode, tested, so that the stops are visible rather than remembered.

### 6.4 Stops that keep running unchanged

- The spec's HALVE / KILL lines (12% / 18%, report only, `risk.drawdown: report`). They read the whole
  account. §7.3 says what changes for them.
- The core's 60-session kill rule: live net Sharpe < 0; slippage > 2× modelled for 5 sessions; discount
  spread < 12%.
- Trial 53's R1–R3, with the question in §7.3.

### 6.5 The revert path

`below_min_names: "flatten"`, or both keys deleted, through `/spec-change` (§1.6).
- **During an episode** the next reduced decision then flattens the whole book, as today. That is a full
  round trip, accepted as the cost of a kill.
- **Between episodes** a revert changes nothing that trades.
- A reverted trial is not re-opened without a new pre-registration and a new trial.

---

## 7. Composition with what is live

### 7.1 Does trial 53's multiplier apply on thin sessions under te4? Yes

The reduced build falls through to the same lines as a full session:
- the band reads held / (NAV × m);
- `_cap_gross` acts at `max_gross_stress / m`;
- the weights are emitted as m × unit.

So **m = 1.30 multiplies the reduced book**, and the ceiling stays at 1.8 × NAV. Nothing in this rule reads
m.

### 7.2 Do trial 53's figures move under te4? Yes, materially

Trial 53's exact-build rows, W1 (2013-06-25 → 2022-12-30). Every W1 thin session has 4 or 5 eligible
names, so under te4 the core trades on 100% of W1 against flatten's 43.6% [V §B]. compose.py §A reproduces
trial 53's committed flatten rows exactly (difference 0.0).

| book (exact B, W1) | TR %/yr | SR | maxDD (PR) | vol while trading | held at the cap | zero-edge P(HALVE) / P(KILL), 12 months while trading |
|---|---:|---:|---|---:|---:|---|
| flatten ×1.30, instant (trial 53 as amended) | 3.78 | 0.805 | 8.26% | 7.10% | 15.2% | 16.0% / 1.54% (approved, cap model: 16.7% / 1.68% [S T53]) |
| flatten ×1.30, deferred (the live runner) | 3.50 | 0.726 | 8.48% | 7.29% | 13.6% | 17.1% / 1.75% |
| te4 ×1.30, instant | 11.90 | 1.492 | 13.27% | 7.97% | 19.9% | **23.2% / 3.28%** |
| **te4 ×1.30, deferred** | **10.90** | **1.361** | **13.76%** (2017-06-02 → 2018-06-05) | **8.01%** | **17.5%** | **23.2% / 3.28%** |
| te4 ×1.15, deferred | — | — | — | — | — | 16.7% / 1.69% |

[V §B, §D2]

**What moves:**
1. **The fit path crosses HALVE.** At ×1.30 the te4 book's W1 drawdown is 13.76%, past the spec's 12%
   line. The flatten book's is 8.48%. The crossing sits in the 2017–18 thin stretch, the same one that put
   the hold book at 14.84% before amendment 1 [S thin-days §6].
2. **The multiplier.** The 2026-10-29 rule (m_core = m_c4_rule × sd_c4 / sd_core, with m_c4_rule 1.2642 and
   sd_c4 0.003659 read from `flatten_remeasure_2026-11-02_m1.30.json` [S T53]):
   - fed te4's W1 trading-session sd, 0.004021, it gives **×1.1502 → 1.15**;
   - fed flatten's, 0.003556, it gives ×1.3007 → 1.30 [V §C].
3. **The odds.** At ×1.30 the te4 mix carries zero-edge P(HALVE) / P(KILL) of **23.2% / 3.28%** while
   trading, against the ~16–17% / ~1.5–1.7% the trial approved. At ×1.15 it carries 16.7% / 1.69%, back
   at the approved level [V §D2].
4. **The stops**, below.

**Why m should not move for this** [U, recommended in Q2].
- W1 is 56% thin sessions; the forward book has had 0% since 2023-08-30. On full sessions the te4 book is
  the flatten book, so ×1.30 is right for them.
- Cutting m to 1.15 would shrink every full session to pay for risk in episodes that may never come.
- The reduced-session risk is better bounded where it arises, by K1–K3.

**Disclose either way.** Under te4, trial 53's W1 figures describe the book only while no thin session
occurs.

### 7.3 R1–R3 and HALVE / KILL: do they need anything? Yes, one decision

- **Under flatten**, a thin session is flat and "cannot trip any stop" [S T53 FLATTEN_REMEASURE §4].
  **Under te4** thin sessions trade, so R1–R3 become live during an episode, on a book their calibration
  never contained.
- **How they behave on te4's fit mix, at ×1.30 with deferred flips** [V §D, fit edge, SB21; nominal 5%]:
  - **the approved R3 (12.07%) fires 8.3% of the time**: spurious reverts of the raise, caused by te4's
    higher vol;
  - R2 fires 4.0%, R1 2.7%.
- **Recalibrated on te4's trading sessions** (exact build): R1 10.75%, R2 −2.48%, R3 15.66%. The
  exact-build flatten reference, deferred, is 10.68% / −3.26% / 12.41%, beside the approved cap-model
  10.14% / −3.06% / 12.07%.

**Recommended (Q3): (a) read R1–R3 on full-session earning days only** while this key is set: the sessions
after a decision with ≥ 6 eligible, joined end to end.
- That is exactly the population trial 53 calibrated them on: the flatten book's trading sessions *are*
  the full sessions.
- This trial's K1–K3 cover the reduced sessions. Each trial is then judged on its own sessions, and
  neither trips the other's stops.
- **Alternative (b):** recalibrate R1–R3 on te4's trading sessions, an amendment to trial 53 by its
  owner. It mixes the two trials' risk in one stop.
- **The decision is trial 53's owner's.** This note only measures it.

**HALVE / KILL** (report only; a peer owns them).
- No change is needed: they read the whole account, as now.
- **But a HALVE report during a thin episode is an expected event on the fit's evidence** (item 1 of §7.2),
  not a malfunction, and the peer should know before it happens.

### 7.4 The vol scalar on 4–5 names

- **It is computed on the reduced set's own weights** over its trailing 63 sessions, so a concentrated
  book is scaled down.
- **It holds less well there.** The unit te4 book's realised vol is **6.64% on reduced earning days
  against 5.78% on full ones**, for a 6% target [V §E]: about 11% over the target, and 15% above the
  full book [U: 6.64 / 6.0; 6.64 / 5.78]. The scalar's look-back of today's weights under-reads the
  concentration risk.
- The scalar never reached its 0.2 or 2.5 clip on a reduced decision [V §E].

### 7.5 The gross ceiling, `max_gross_stress`, gate 8 and the send-time fit

- **The ceiling is unchanged.** 1.8 × NAV in account units, 1.385 in unit weights at ×1.30, applied after
  the band. Reduced decisions sit at it 16.9% of the time, full ones 14.6% [V §E].
- **Gate 8 is unchanged**: projected gross ≤ `max_gross_stress` × the lower of sized and live equity,
  unless the plan does not add gross; and buying power and Reg T on the live account.
- **One interaction.** `bp_shortfall: scale` (`fit_to_buying_power`) scales opening orders only and sends
  reductions in full. On a 4–5-name book where one side is opening and the other reducing, that leaves a
  net imbalance for the session. K3 watches the realised result.

### 7.6 The deferred-flip rule

`quantt/session/decide.py`: `FLIP_SAME_SESSION = False`. A long↔short flip sends only the closing leg
today, and the band reopens the other side from flat next session.

**On a reduced set a flip can be a whole side.** On the fit, at ×1.30, the held book's |net| on reduced
decisions reaches **0.833 of NAV with deferred flips**, against **0.235 with instant flips** (p99 0.248
against 0.175). On full decisions it reaches 0.487 [V §E].
- **Example, 2019-10-09.** HYT's target flipped from short to +0.64 long while PHK's long was cut from 0.89
  to 0.06. HYT was held flat for the session, and the book was net short 0.83 for one session.
- **Not changed here.** The deferral exists for a broker reason (CLAUDE.md landmine 4 [U]). It is part of
  what paper scores, and the fit's deferred-flip episode values are the ones quoted.
- **K3** is set so that this one-session pattern (0 runs of 3 on the fit) does not trip it, while a
  persistent one-sided book does.

### 7.7 The stale-NAV and missing-NAV holds

Holds never trigger a reduced build, as they never trigger the flatten (§1.3, new piece 3).
`gate.max_missing_nav_holds` stays n − `min_names` (§1.3, new piece 4).

### 7.8 C4

**C4 does not share the account.**
- It is its own book (`ops/books/c4_families_book.json`, `c4_families_paper`) on its own Alpaca paper
  account.
- Its spec sets `below_min_names: "hold"` and `sizing_multiplier` 1.26 (`c4_families.v4.20261102`) [V].
- This key goes into the core spec only. The registry accepting `"trade_eligible"` changes nothing for a
  spec that does not set it.

---

## 8. Divergences from the backtest, stated up front

1. **Constant weights against whole shares.**
   - The harness holds a weight vector and re-applies the band and cap daily in weight space.
   - Live, a band HOLD is a share count, so held weights drift with prices between trades. Orders are
     whole shares. The dust filter flattens names under 0.005.
   - The harness models no `min_abs_weight`. The declared guard (§1.3) leaves a residual under 0.005 per
     dropped name, on about 7% of reduced sessions (127 of 1,708 [S screen]).
2. **Live eligibility gates the harness does not have.**
   - The stale-NAV gate and missing-NAV holds (§7.7), gate 5's refusals, and the corporate-action halt.
   - **Gate 7's shortability skip.** On paper a short Alpaca will not lend is skipped, with no
     substitute. On a 4–5-name book the skipped short can be a whole side, leaving the book net long; the
     harness never had this. K3 watches the realised result.
3. **Paper fills at the quote, not in the auction.**
   - `late_market` sends market `day` orders 8 to 2 minutes before the close. Paper runs no closing
     auction (CLAUDE.md landmine 1).
   - E_k is on Alpaca's fills; the closing-print view sits beside it (§4.4).
4. **No borrow, no distributions, no corporate actions on paper.**
   - E_k is price only. The screen's figures are total return; the distribution leg of te4's thin-day P&L
     was −0.28 of +3.94 [S screen], so price only reads slightly higher.
   - Borrow is UNMEASURED forward (§4.4).
5. **Deferred flips** are modelled in the harness (`defer_flips=True`) as flat for one session, then the
   band from flat. That is the live rule; the instant-flip rows are context only.
6. **`bp_shortfall: scale`** scales opening orders only; the harness scales the held book uniformly
   (§7.5).
7. **The hindsight universe.**
   - The fit's thin sessions come from projecting today's 13 names into years when they were illiquid.
   - Forward thin sessions would come from one name's ADV dip, likely shorter and in a book that is
     otherwise liquid. The per-episode effect may not transfer (§5 item 4).
   - Survivorship is unmeasured.
8. **Missed sessions.** A day that does not arm, refuses or is halted still has a P&L of record. It counts
   in E_k as what the account did, which the harness never models.
9. **The 0/0 sessions.** The harness fills 0/0 with 0, and the full-book sleeve holds silently (PR #33
   §5.H). The reduced path raises (§1.3), so such a day is a missed decide with the book held in shares.
10. **The re-entry leg is modelled**, and is kept out of every verdict (§4.4).

---

## 9. Trial accounting, and the exact ledger edit (for the owning session at approval)

- **Counter: CEF.** The counter moves from its value at approval, 53 today, to N = that value + 1 **in the
  commit that records the team lead's approval, not before** (`/prereg`; `docs/RESEARCH_STATE.md`'s
  rule).
- **Bar √(2 ln N):** 2.818 at 53, 2.825 one later, 2.831 two later [V §G].
- **One trial.** One rule, one derived floor, one account.
- **Updated in `docs/RESEARCH_STATE.md` in the same commit as the approval: to be done by the owning
  session.** This draft does not edit that file.

**The edit, exactly** (replace `<N>` with the counter's value at approval plus one, `<date>` with the
approval date, and `<file>` with the approved note's name):

1. The counter row:

```
| **CEF** | **credit closed-end fund discounts** | **<N>** |
```

2. A dated note, above the 2026-11-02 notes:

```
> **<date>: CEF <N−1> → <N>** (team lead; this commit records the approval):
> - **Trial <N> is the thin-session rule `trade_eligible`, floor 4, PAPER ONLY**
>   (`results/cef/<file>`, from `PREREG_DRAFT_THIN_TRADE_ELIGIBLE_2026-11-03.md`): on a session with
>   fewer than `min_names` but at least 4 eligible names, the core builds its book on the eligible names
>   instead of closing it. Keys `below_min_names: "trade_eligible"`, `below_min_names_floor: 4`
>   (absent = flatten, byte-identical, proved). Never on a live-money account (the paper-only client,
>   a run-time refusal of the key against any other endpoint, and `docs/SYSTEM.md` §5).
> - **Not shown to be alpha** (`results/backtests/thin-third-rule-2026-11-03/REPORT.md`): matched-turnover
>   +2.13pp/yr (t 2.34), INCONCLUSIVE; PHK and PDI; 87% PIMCO; holdout t 0.72; −2.33pp/yr net of measured
>   2023+ borrow. Chosen for paper because paper is scored gross (D19/D20).
> - **Judged at N = <N>, bar √(2 ln <N>)**, on forward thin episodes only (2023+ is seen). PRESENT is out
>   of reach for years (exact P 0.10 at 5 episodes); ABSENT (first two episodes negative, or the mean
>   ≤ 0 from the third) and the in-episode kills K1–K3 are the operative rules, re-measured on the read
>   date by `results/cef/prereg_thin_te4/compose.py`.
> - **Trial 53 composes with it** (pre-registration §7): m 1.30 applies on reduced sessions; <the team
>   lead's answer to Q3: R1–R3 read on full sessions only / recalibrated>.
```

3. A row in the ACTIVE table, after VT:

```
| **TE4** (CEF trial <N>) | on a session with 4 or 5 eligible names, trading the eligible set with the sleeve's own construction earns more gross than closing the book (`results/cef/<file>`); keys `below_min_names: "trade_eligible"`, `below_min_names_floor: 4`; **paper only** | **APPROVED <date>** (team lead); inert until a session is thin (none since 2023-08-30 on the panel to 2026-10-14) | forward thin episodes only: ABSENT on the first two negative or a mean ≤ 0 from the third; KILLED on K1–K3; PRESENT at t ≥ t(k−1) critical at the bar, with PHK and PDI out still positive |
```

---

## 10. Open questions for the team lead, each with a recommended answer

1. **Approve for paper, as drafted?**
   - Weigh it as follows: the gross case is real on the panel, it is not shown to be alpha, and it cannot
     be shown forward in any useful time.
   - **Recommend: approve only if the paper score of gross P&L on thin sessions is itself the objective.**
     If the objective is evidence for real money, this trial cannot supply it (§6.2), and option (c) of
     the screen (record the screen, keep flatten) costs nothing.
2. **Trial 53's multiplier under te4?**
   - Re-fed te4's book, trial 53's rule gives ×1.15, against ×1.30 (§7.2).
   - **Recommend: keep ×1.30**, record in trial 53 that its W1 figures describe the book only while no
     session is thin, and let K1–K3 bound the reduced sessions. The owning session decides.
3. **R1–R3 under te4?** **Recommend (a): read them on full-session earning days only** while this key is
   set (§7.3). Otherwise the approved R3 fires 8.3% of the time against its 5% design on te4's fit mix.
   The alternative is to recalibrate on te4's trading sessions, an amendment to trial 53 by its owner.
4. **The min-weight guard** (l.965). **Recommend: leave it at `min_names`** (§1.3). The alternative, the
   guard at the floor, re-creates the 3-name degeneracy when a 4-name set loses a name to the filter.
5. **The deferred flip on a one-fund side** (§7.6). **Recommend: no change.** It is the broker's
   constraint and part of what paper scores; K3 watches persistence.
6. **The paper-only tripwire** (§1.2). **Recommend: build it with the key.** Whether the same tripwire
   should cover `late_market` is a separate question for the runner's owner. It would make that
   exception's enforcement a check, not only the client and the written rule.
7. **The forward borrow column.** It is UNMEASURED: IBKR is retired and paper has no fees.
   **Recommend:** record it as UNMEASURED per episode and decide nothing on it. If a real-money proposal
   ever cites this rule, a point-in-time securities-lending history for PHK, PDI and PTY is the first
   purchase (the screen's open question 8).

---

## 11. Reproduce

```bash
python3 results/cef/prereg_thin_te4/compose.py      # §A-§G above; about 10 s; fit rows only; writes compose_2026-11-03.json and compose_output_2026-11-03.txt beside itself
# the screen this note rests on
python3 results/backtests/thin-third-rule-2026-11-03/third_rule.py && python3 results/backtests/thin-third-rule-2026-11-03/tables.py
python3 -m pytest scripts/cef/tests/test_band_trade_eligible.py scripts/cef/tests/test_band_below_min_names.py
```

What compose.py asserts before it prints any result (it raises otherwise):
- the flatten book at ×1.00 / 1.13 / 1.30 equals trial 53's committed exact build
  (`prereg_voltarget/flatten_exact_2026-11-02.json`), largest difference 0.0;
- the flatten unit book's trading-session sd equals `flatten_remeasure_2026-11-02_m1.30.json`'s
  0.003556;
- te4's nine fit episodes equal the screen's `results.json` (largest difference 1.4e-17);
- no frame reaches 2023-01-01.

**It writes nothing under `data/`** (CLAUDE.md landmine 9).
