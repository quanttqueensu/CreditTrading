# Core-signal improvement candidates from W4 — 2026-10-12

**Proposals and zero-trial decompositions only. Spends no trial (the CEF counter
stays at 50, bar 2.80). Pre-registers nothing, changes no spec and touches
nothing on the live path.** Each candidate below that survives goes through
`/prereg` and the team lead before it runs. The human disposes.

**What it answers.** Which of W4's findings (`results/cef/W4_ARTIFACTS_2026-10-11.md`)
point to a change in the live signal or its execution that is worth a counted
trial. Each candidate was checked against the graveyard (`/graveyard`,
`docs/RESEARCH_STATE.md`, KILLED and "KILLED — CEF construction variants") before
anything was measured. Candidates are ranked by **information per trial**.

**Reproduce every figure:**

```bash
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/stage_crsp_w4.py               # CRSP opening prices (second source)
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open           # NYSE opening prints
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open --sizes   # with print sizes
QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side close --sizes
python3 scripts/cef/core_signal_decomp.py                                        # sections exdates, toy, t1; ~10s
```

The run behind this note is `results/cef/w10/core_signal_decomp_output.txt`.
Every figure is **[V]**, measured this session, unless labelled otherwise.

**Panels:**

- `cef_prices` last date 2026-09-28; `cef_nav` 2026-09-25; `cef_distributions`
  last ex-date 2026-09-10.
- Only 2005-01-03 → 2022-12-30 is used.
- CRSP rows to 2022-12-30. Alpaca auction prints 2016-01-04 → 2022-12-30.
- The 2023-01-01 holdout stays sealed.

**What is allowed here, and what is not.** Every statistic splits the *deployed*
signal's existing predictive content, by a characteristic known at *t* or by a
segment of the forward path. That is the same kind of split W4 §2–§4 made. **No
modified signal is built, no policy is scored, no variant is compared.**

The shared statistic is the pooled slope of the cross-sectionally demeaned
forward return [t+2, t+3] on the demeaned z, in bp per unit z, with a
date-clustered t. Its share of the total predictive covariance is "contribution".
On all deployed name-days it reproduces W4: **−6.74 (t −2.92)**.

---

## Ranked by information per trial

| rank | candidate | counter | the cheapest test that could kill it | prior |
|---|---|---|---|---|
| **1** | **C5 (new): fill at the t+1 opening auction, not the t+1 closing auction.** Same evening decision on *t*'s NAV, same holdings path | CEF, 50 → 51 | **Zero-trial gate**: opening-auction effective spread minus closing, from Alpaca SIP quotes 2016–22, against the t+1-session return the earlier fill captures per unit of turnover. Then one trial: identical H, a visible open-fill extension of `evaluate()` | 35–45% [U] |
| **2** | **C2 Part C: two sleeves, a derived tilt toward selection within groups** (`results/cef/W10_PARTB_2026-10-12.md`) | CEF, 1 trial | As archived: matched turnover, net@15 − borrow, BR_eff, eras, and the holdout sign. **Needs the evaluation-set ruling first** (W10-B §10) | 30–40% [U] |
| **3** | **(a′) Freeze trading in the sessions before a regular ex-date** | CEF, 1 trial | Dies if the same freeze on the placebo calendar (+10 sessions) helps as much, or if gross falls or net@15 does not improve on the fit period's 5/15/30 grid, or if the 2023+ row disagrees in sign | 20–30% [U] |
| — | **(b) Turn of year as its own sleeve or gate**: closed at zero trials (D7; the tax-loss mechanism is not isolated). Kept as a declared stratum | — | — | — |
| — | **(c) NAV nowcast (C3/W13)**: dominated by rank 1; parked | — | — | <15% [U] |
| — | **(a) Distribution-adjust the discount around specials**: killed at zero trials, because its premise is reversed in the data | — | — | — |

---

## 1. C5 (new): an opening-auction fill on t+1

### Why W4 points to it

W4 §2: "the largest single-day IC is on day t+1, the day no book decided at t can
earn" (−0.042, t −3.00), and it survives on quote midpoints. W4's "What this
changes" item 2 concluded that "no change to the session schedule can do it",
because every schedule decides on *t*'s NAV.

**That holds for the overnight part only.** The decision on *t*'s NAV is made in
the evening, and the next price a book can trade at is the **t+1 opening
auction**, not the t+1 close.

### The decomposition (zero-trial)

The t+1 return is split exactly into **overnight** (close *t* → open *t+1*, with
the distribution added back on an ex-date) and **session** (open → close *t+1*).

**Full sample, 2005–22**, deployed set, every session, NW t. The yfinance open
and CRSP `openprc` agree within $0.005 on 99.9% of 48,851 common name-days.

| segment | IC | t (NW) |
|---|---:|---:|
| day t+1, close to close | −0.0416 | −2.95 |
| t+1 overnight (yfinance / CRSP open) | +0.0053 / +0.0020 | 0.35 / 0.13 |
| **t+1 session (yfinance / CRSP open)** | **−0.0411 / −0.0413** | **−3.08 / −3.09** |
| day t+2 | −0.0225 | −1.58 |
| t+2 overnight / session | +0.0214 / −0.0310 | 1.33 / −2.31 |

Two-day windows on the phase-0 grid:

| window | IC | t |
|---|---:|---:|
| [close t+1 → close t+3], **deployed** | −0.0329 | −1.68 |
| [open t+1 → close t+2] | **−0.0644** | −3.38 |

**On the transactable price, the NYSE opening-auction print**, 2016–22:

- Alpaca SIP, exchange N. Condition Q (official open) where published, else O.
  The two never differ by more than $0.005 on the 5,341 name-days that have both.
- A print exists on 99.9% of panel name-days, and equals the yfinance open within
  $0.005 on 98.2% of them.
- On the common sample:

| | IC | t |
|---|---:|---:|
| t+1 overnight to the opening auction | −0.0265 | −1.68 |
| **t+1 session from the opening auction** | **−0.0458** | −2.85 |
| [close t+1 → close t+3], deployed (352 dates) | −0.0321 | −1.36 |
| **[opening auction t+1 → close t+2]** (353 dates) | **−0.0726** | −3.15 |

**The stale-open check.** A t+1 open sitting at close *t* would make the whole
day look like "session". Where the auction open moved more than $0.005 off close
*t*, the session IC is −0.047 (t −2.66). An open at the prior close occurs on
14.5% of name-days.

**What carries it.** z_t splits into three parts: its level carried from t−1
(zL, corr +0.973 with z_{t−1}), today's price move (zP) and today's NAV move (zN),
each in z units. Fama–MacBeth, bp per unit:

| forward | zL (t) | zP (t) | zN (t) |
|---|---|---|---|
| day t+1 | −9.50 (−3.77) | −2.57 (−0.19) | **−124.2 (−3.06)** |
| t+1 overnight | +2.40 (1.37) | +8.82 (1.04) | −24.8 (−1.23) |
| **t+1 session** | **−11.91 (−3.63)** | −11.39 (−1.13) | **−99.4 (−2.57)** |
| [t+2, t+3], deployed | −6.86 (−1.39) | −30.1 (−1.40) | −141.5 (−2.05) |

Standard deviations: zL 1.34, zP 0.62, zN 0.23.

The level and **today's NAV move** predict the t+1 session. Today's price move
does not, and the overnight gap carries nothing. **The price takes in t's NAV
during t+1's session, after the NAV is public and after the opening auction.**

### Mechanism and who is on the other side

- **The NAV is struck after the close and published in the evening**, with no
  documented posting time (`docs/BRIEF.md` §3, [S]). It is not on the tape.
- The t+1 opening cross is set by orders queued overnight against the last
  price.
- On Alpaca's print sizes, the median NYSE **opening** print in dollars is
  **9.4×** the median **closing** print across the 13 names (2016–22). The `s`
  field is documented only as "Auction trade size", so whether a print is the
  whole cross is **[U]**. Read the ratio, not the level.
  *(Settled 2026-10-13, `results/cef/EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md`
  §1: the primary's `O` / `6` print is the whole round-lot cross, and the `Q` /
  `M` print repeats its size only on a day that has one.)*
- **The loser** is the overnight retail order and the market maker anchored on
  close *t*, crossing at the open before the NAV is in the price.
- **Why it persists**: there are no authorised participants, the share count is
  fixed, the holder base is retail, and it is a one-day horizon that no
  arbitrageur's capital is sized for.

### The graveyard check

| relative | why it is or is not this |
|---|---|
| **The 2026-07-31 overnight market order** (realised 100.5bp against a 32.6bp breakeven; filled 07:27 ET pre-market; `CLAUDE.md` rule 3) | The nearest dead relative. That order rested overnight and filled in the pre-market. This one is an **auction-only** order (NYSE MOO/LOO; Alpaca `time_in_force=opg`) and cannot fill outside the opening cross. **The open cross's cost for thin CEFs is unmeasured, and it is the kill test** |
| `leadlag`: an effect on a price nobody could trade | Measured above on the **opening-auction print**, which an opening order gets |
| The `shift(1)` incident: entering at t's close on t's NAV | Not that. The decision uses N_t, which is published before the t+1 open. The fill is later than the decision |
| Stale-price family (6 of 13 deaths) | The other direction: the **price** lags a fresh NAV. No stale mark is being faded |

### What it changes

- A frozen-spec key `fill_auction: "close" | "open"`, absent = close. The no-op
  is proved byte-for-byte (`/spec-change`).
- The holdings path H is unchanged, so turnover matches the deployed book
  **exactly** (H2).
- The harness needs one **visible** extension of `evaluate()`: on day t+1,
  `H_{t−1} · r_overnight + H_t · r_session`, priced at the opening auction.
- **Blocked until the team lead rules.** `CLAUDE.md` order-path rule 3 says
  "order type stays MOC". Alpaca's `opg` is "only available to Elite Smart Router
  users" per one Alpaca page (`docs/REFERENCES.md` §8, **[U]**). Paper does not
  simulate an auction on either side.

### Control (H12)

1. **The overnight segment.** If the mechanism is "the price takes in the NAV
   during the session", the overnight carries nothing. Measured: +0.005.
2. **A wrapper where the mechanism cannot operate**: HYG's own
   premium/discount z against HYG's t+1 session. Authorised participants
   arbitrage it, so expect zero. *Declared, not run.*

### Kill tests, cheapest first

1. **Zero trials.** Fetch Alpaca SIP quotes around 09:30 and 16:00 for the 13
   names, 2016–22. Measure each name's effective half-spread at the opening print
   against the closing print. If the open's extra cost per unit of turnover is at
   least the t+1-session return the earlier fill captures per unit of turnover,
   the candidate is dead before any trial. Both quantities are re-measured at run
   time (H14).
2. **Zero trials.** The team lead declines to amend rule 3 for this key, or
   Alpaca's `opg` is not available to this account.
3. **One trial.** In the fit period at identical turnover, gross SR is not above
   the deployed book's once the measured open surcharge sits on the cost grid; or
   it flips sign across 5/15/30bp; or the 2023+ row disagrees in sign.

### Expected magnitude [U]

This is a prior, not a measurement. W4's skip-a-day cost one session of delay:
live gross SR 0.96 → 0.78. Filling at the t+1 open instead of the t+1 close moves
entries earlier by about one session, and the t+1-session IC (−0.041) is larger
than the t+2 day's (−0.023). So the gain could exceed what skip-a-day lost:
roughly +0.1 to +0.3 gross SR **before** the open's extra cost, which could take
all of it.

**This is rank 1** because one trial, at identical holdings, answers a binary
question, and a zero-trial gate can close it first.

**Two side observations for the real-money gate (plan item 0.5).**

- The book's dollar-weighted median order at the spec's $100,000 capital is about
  **0.95×** the median NYSE closing print (2016–22). If prints are whole crosses,
  the book is a large part of the closing auction it trades in.
  *(Settled 2026-10-13, `results/cef/EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md`:
  prints are whole crosses on round-lot days, and the ratio of medians
  understated the problem. Matched to the cross of its own fill day, the
  deployed book's notional-weighted median order at $100,000 was about half of
  that day's NYSE closing cross in 2016–22. That note also measures the
  opening cross's cost, C5's first kill test.)*
- W4 "What this changes" item 2 should carry a dated pointer to this section.
  One is added.

---

## 2. C2 Part C: two sleeves (from W10 Part B)

The full evidence is in `results/cef/W10_PARTB_2026-10-12.md`. In short:

- **Within-group selection pays more per unit of signal than between-group
  timing** on every view:
  - deployed: −9.1 against −3.3bp/z;
  - WIDE: −12.6 against −9.1, and since 2013 −10.0 against −4.5 (difference t
    2.46).
- Within carries 89% of the deployed book's return.
- **Today's live book is 67% between by gross mix**, long multi and short
  muni/JFR. That is above the fit period's 90th percentile.

| | |
|---|---|
| **Mechanism and loser** | Within: the same retail base misprices sibling funds of one family (PIMCO premiums) against each other. Between: sector-level sentiment (M5). Both are retail holders who buy yield and sell losses |
| **W4 pointer** | §4 (the IC is concentrated in multi), §5 (by group, multi carries the P&L) |
| **Graveyard** | "Hard group neutrality, 0.97 → 0.82". **Different**: the budget is derived and the WIDE set says between is paid, so expect a tilt, not zero. If Part C's derived split did come out zero, the trial would be re-testing a killed variant, and the reconciliation must be written first |
| **Key** | `construction: "band" \| "two_sleeve"`, absent = band (as archived) |
| **Control** | Random groups (W10-B §3: the real difference ranks above 18 of 20 draws). The WIDE set as a second view |
| **Kill** | As archived (W10 Part C decision rule), re-measured at run time |
| **Prior** | 30–40% [U]. Information per trial is high because the bet it sizes is most of today's book. It ranks below C5 because its answer depends on the evaluation-set ruling |

---

## 3. (a′) The regular ex-date cycle: freeze trading for five sessions before each ex-date

### Why W4 points to it

- W4 §1: the discount *falls* on the ex-date and keeps falling for two sessions.
  The price drops 1.04× the distribution. This is a post-ex price pattern, not
  arithmetic, and it is a correction to `docs/BRIEF.md` §3.
- W4 §4a: name-days touched by an ex-date dilute the IC (−0.033 against −0.043
  untouched).

### The decomposition

The deployed signal in event time, regular distributions, phase-0 grid. k is the
signal date minus the ex-date.

| window | name-days | slope bp/z (t) | contribution |
|---|---:|---|---:|
| **pre [−5, −1]** | 788 | **+3.91 (0.75)**; phase 1 −3.00 (−0.71) | −0.140 |
| ex [0] | 149 | −7.69 (−0.80) | 0.058 |
| post [+1, +2] | 331 | −8.70 (−1.43) | 0.127 |
| post [+3, +10] | 1,361 | −8.03 (−2.49); phase 1 −9.18 (−2.61) | 0.456 |
| outside every [−5, +10] window | 785 | −12.23 (−2.67) | 0.381 |
| **placebo** pre [−5, −1] (ex-dates moved +10 sessions) | 835 | **−12.40 (−2.93)** | 0.436 |

**In the five sessions before a monthly ex-date, the deployed signal has no
slope.** The same window on the placebo calendar has a strong one.

Same-day abnormal total return, regular cycle, every session (NW t):

| k | −3 | −2 | −1 | 0 | +1 | +2 | +3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bp | +8.45 (1.85) | +2.57 (0.62) | **+12.65 (2.30)** | +0.24 (0.05) | −2.91 (−0.62) | **−11.49 (−2.24)** | **−8.61 (−2.40)** |

This is a run-up into the ex-date and a fall after it, a pattern the z-score
cannot see.

**20.3%** of the deployed book's turnover (trades over 0.5% of capital) is decided
in the pre-ex window, which holds 21.7% of name-days.

### Mechanism and who is on the other side

**The loser** is the yield buyer who buys before the record date "to get the
distribution" and sells after. For a monthly payer that is a standing,
calendar-driven flow. It persists because it is behavioural and because the
distribution looks like free money to the holder.

### The graveyard check

| relative | why it is or is not this |
|---|---|
| "Distribution data" (failed twice: as a universe filter and inside the Kalman) | Those used distribution *levels and cuts*. This is the *calendar position* |
| Agenda "Closed: ex-day dividend capture" (paper credits no dividends) | As a **standalone** three-day trade it is D2 here: about 24bp abnormal against two crossings of a 32.6bp breakeven. As a **freeze on trades the band makes anyway** it adds no turnover. It is a TC lever, not a new IC source. The third P&L line now credits distributions on paper |

### What it changes

A frozen-spec key `ex_window_freeze_sessions`, absent = off. A name whose next
regular ex-date is 1 to N sessions ahead is not traded that session (the band
holds it).

**N must be derived, not swept, and this table cannot be the derivation.** Under
shift(2) a decision at k earns sessions k+2 and k+3. For k ∈ [−5, −1] those
sessions lie in [−3, +2]: the run-up, the ex-date and the first post-ex sessions,
where the price pattern runs. Choosing N = 5 *from the table above* would be
fitting it.

The pre-registration must state the mechanism's window before any score is
computed. That window is the sessions whose earning window overlaps the
record-date flow, read from the declared ex-date and settlement calendar. It must
also say plainly that the fit-period table was seen first.

### Control, kill test and prior

- **Control (H12)**: the identical freeze on the placebo calendar (+10 sessions)
  must not improve the book by as much.
- **Kill**: in the fit period, gross SR lower, or net@15 not better at the 5/15/30
  grid, or the placebo improves as much, or the 2023+ row disagrees in sign.
- **Prior**: 20–30% [U]. The pre-window is "no slope", not "wrong slope", and the
  two phases disagree in sign (+3.9 against −3.0). Most of any gain is turnover
  deferred rather than avoided, so the gain is small: at most 20% of turnover is
  touched.

---

## 4. (b) The turn of year: a stratum, not a sleeve. No trial

### Why W4 points to it

W4 §4: Dec–Jan signal dates are 18% of dates and carry 52% of the summed IC. The
concentration is in multi and overlaps the year-end specials. Agenda item B4
proposes a generalised tax-loss trade.

### The decomposition

Tax-loss status is known at *t*: in December, the year-to-date total return
through *t*; in January, the previous calendar year's; otherwise year to date.

| subset | name-days | slope bp/z (t) | contribution |
|---|---:|---|---:|
| Dec–Jan, all | 619 | −14.32 (−3.02) | 0.459 |
| Dec–Jan, **losers** / winners | 169 / 450 | **−25.53 (−2.40)** / −10.63 (−2.39) | 0.202 / 0.257 |
| Feb–Nov, all | 2,839 | −4.65 (−1.78) | 0.541 |
| **Feb–Nov, losers / winners (the calendar control)** | 1,137 / 1,702 | **−9.12 (−1.45) / −2.43 (−1.11)** | 0.353 / 0.188 |
| Dec–Jan excluding specials [−3, +10] | 562 | −10.76 (−2.52) | 0.312 |
| Dec 1–15 / **Dec 16–31** | 62 / 145 | −26.56 (−1.96) / **−35.93 (−3.19)** | 0.128 / **0.310** |
| Jan 1–15 / Jan 16–31 | 157 / 255 | −0.75 (−0.14) / −1.39 (−0.23) | 0.006 / 0.015 |
| Dec–Jan, multi / not multi | 433 / 186 | −16.55 (−2.94) / −11.10 (−1.79) | 0.313 / 0.146 |

Mechanism checks:

- **Seasons**: 9 have any deployed date (2020's has none: the deployed set was
  absent from July 2020 to January 2021). The IC was negative in 6 of the 9.
  The mean of the season ICs is −0.186, with a t over seasons of −1.93.
- December dollar volume is **1.21×** the Feb–Nov mean per name-year (median of
  195; above 1 in 72%).

**Reading.**

- The concentration is real and sits in **late-December signal dates**. Their
  forward windows span the turn of the year.
- **It is not isolated as tax-loss selling.** Losers out-slope winners in Feb–Nov
  as well, by a similar ratio, so the calendar control does not isolate the
  season.
- It survives excluding the specials, at about two-thirds strength.

### The graveyard check and the verdict

| use | verdict |
|---|---|
| As a **separate seasonal sleeve** | D7: 9 seasons, about 96 grid dates. The agenda already notes the one-event-a-year risk |
| As a **gate** that sizes up in December | The "sizing up on dislocation" / regime-switching family (killed; do not build) |
| As **what the book already earns** | The deployed z already trades it |

**The verdict:** no trial. Every CEF pre-registration should report December and
Feb–Nov separately as a declared stratum (W4 asked for the same). The
loser/winner gradient was found by slicing and is **not** proposed.

---

## 5. (c) NAV nowcast, C3/W13: dominated by C5; parked

### Why W4 points to it

W4 §3: NAVs are stale in every group, yet the stale part of z carries no IC at
the traded horizon. Its case has to be a timing gain.

### The decomposition (section 1's table)

- The t+1 predictive content sits in **zL** (the level, known at t−1) and **zN**
  (t's NAV move).
- A nowcast decided before the close can only approximate zN. W4 §3b's proxies
  explain part of a day's NAV move.
- The overnight segment it would add over C5 carries nothing (IC +0.005 full
  sample). zL's overnight slope is +2.4, the wrong sign.
- **C5 uses the true NAV and reaches the same session.** The nowcast's simplest
  form, deciding at about 15:45 on N_{t−1}, is not a nowcast at all.
- It is also the stale-mark well the graveyard warns about.

**Park it behind C5.** Reopen only if C5 dies on the open cross's cost and a
reason appears to expect the close-*t* fill to be cheaper. **Prior below 15%
[U].**

---

## 6. (a) Distribution-adjust the discount around specials: killed at zero trials

**The premise.** A year-end special makes a fund *look cheap*, and the deployed z
buys it wrongly (W4 §4a: specials carry 18–29% of the deployed IC).

**The decomposition reverses it.** Around specials (D/P above 2%, window
[−5, +10]), the deployed z reads the fund **rich**: mean demeaned z +0.45, and
+0.76 on k = +1..+2. Those funds then **underperform**: mean forward −16.3bp,
slope −49.5bp/z (t −3.76), 11.8% of the predictive covariance on 44 grid
name-days, 22 dates.

The signal is on the right side of specials. Adjusting the discount there would
remove IC, not a masquerade. The sample is D7 in any case.

---

## What should change in the order of phase 2

1. **Rule on the evaluation set before C1, C2, C4 or C5 is pre-registered.**
   - The deployed fit sample (W4's baseline) existed on only 43.6% of sessions
     between 2013-06 and 2022 and almost never held the munis.
   - Today all 13 names clear the ADV floor, and the book is two-thirds a group
     bet against munis and JFR (W10-B §1, §8).
2. **Insert C5, the opening-auction fill, ahead of C2 Part D and C3.**
   - Its zero-trial spread gate runs first.
   - It needs the team lead's ruling on `CLAUDE.md` order-path rule 3 and a read
     of Alpaca's `opg` availability.
3. **C2 becomes Part C first (1 trial).** Part D is cut to at most 2 groups and
   runs only if Part C keeps a between budget. Its loan form would consume the
   27-name set, so it **competes with E1**; sequence them deliberately.
4. **C3 drops behind C5.**
5. **Borrow.** On the IBKR fee panel the deployed book's borrow over 2021-09 →
   2022-12 was 12.6%/yr of capital, about twice its 2020–22 gross return
   (W10-B §7). Plan item 0.5 already gates real capital on measured costs. **No
   C-trial should be read net of costs until 0.5 has said what borrow really
   costs.**

## Gaps

- The opening cross's **cost** is unmeasured. That is C5's first kill test, and
  it needs SIP quotes the repo has not fetched. *(Measured 2026-10-13,
  `results/cef/EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md` §6.)*
- Alpaca's auction **size** semantics are [U]. *(Settled 2026-10-13, same note
  §1.)*
- **2023+ is sealed.** Every figure is 2005–22, and the deployed set's figures are
  2013–22.
- Survivorship is unmeasured.
