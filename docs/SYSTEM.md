# QUANTT — the system

**The one document that says what this book is, how it runs, and what we know
about it.** Written 2026-09-13; rewritten for the move to Alpaca and the clean
slate on 2026-09-28 (the documents it replaced are at tag `pre-clean-slate`).

**It holds no figures that move.** Where a number matters, this document names
the command that produces it. Run the command. The only figures written here
are decisions (which carry a date and a decider) and a few observations that
are labelled `[V]` verified, `[S]` sourced but not re-read, or `[U]` uncertain,
each with a date and the note it came from. Why: every number this repo wrote
into prose about its own state was contradicted by another document within
days — the arm rate existed as four different fractions at once.

`docs/INDEX.md` lists which document owns which question. `CLAUDE.md` holds the
rules. `docs/ROADMAP.md` is the plan to prod. `docs/HISTORY.md` says what existed
before the clean slate; git (tag `pre-clean-slate`) holds it, as provenance, never
authority.

---

## 0. How to know anything

**Order of authority**, highest first. When two sources disagree, the higher one
is right and the lower one is a defect to fix — do not average them and do not
pick one silently.

1. **The broker** — what is resting, what executed, what is held.
2. **The frozen spec**, `ops/specs/cef_discount.frozen.json` — every live
   parameter. Prose about parameters is always downstream of it.
3. **A measuring command, run now** — `python3 -m ops.orient` first.
4. **This document** — the shape of the system and the standing decisions.
5. **A dated results note** in `results/` — true as of its date, by its method.
6. **Git history** (tag `pre-clean-slate`) — provenance only.

**Which artifact answers which question.** Keyed by question, not by quantity,
because most contradictions in this repo's history were two artifacts
answering different questions.

| question | authoritative artifact |
|---|---|
| Where am I, what is the spec, what do the Alpaca accounts look like? | `python3 -m ops.orient` |
| Is anything trading? | **No** (2026-09-28): IBKR is retired and the Alpaca runner is not built. The SessionStart banner and status line say so until it is. |
| What is held, resting or executed at the broker? | The Alpaca paper account for that book — `python3 -m quantt.broker.alpaca_probe` (read-only snapshot, one account per book). The broker is the fact. |
| Is a name tradable / shortable / hard-to-borrow at Alpaca? | The probe snapshot's `assets`, dated — `borrow_status` changes daily |
| What did the IBKR book hold, send and fill? | History only, at tag `pre-clean-slate`: `pre-clean-slate:_archive/prod_state_2026-09-28/` and `pre-clean-slate:results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` §7 |
| What are the live parameters? | orient SPEC, which reads the frozen spec through `scripts/cef/spec.py` |
| Gross / net Sharpe and turnover of the live policy? | `python3 scripts/cef/band_frontier.py`, re-run |
| IC, persistence, PCA, ADV, vol scalar? | `python3 scripts/cef/plan_diagnostics.py`, re-run |
| How many trials have been spent? | `docs/RESEARCH_STATE.md` counter table (not its prose); orient TRIALS derives the deflated-Sharpe bar |
| How many tests pass? | `python3 -m pytest`, run now. Never quote a stored count. |
| What is left to do for the Alpaca system? | `docs/ROADMAP.md` |
| Is an external claim verified? | `docs/REFERENCES.md` |
| Do the documents still say true things? | `python3 -m ops.doc_audit` |

---

## 1. What we trade

A **systematic credit closed-end-fund discount-reversion book** that places its
own MOC orders on a schedule. It ran on an IBKR paper account until 2026-09-28
and is moving to Alpaca paper (§4); nothing trades in between. Capital and
universe are in the frozen spec. **Mandate** (§5): paper indefinitely, a
competition track record, judged on absolute return under a vol cap.

**The trade.** A closed-end fund publishes a net asset value daily and its
shares trade at whatever the market pays. Buy funds unusually cheap against
*their own* discount history, short the ones unusually rich, in equal dollars.

**Why it is not arbitraged away.** A CEF has a fixed share count and no
authorised participants. Nothing creates or redeems shares against the basket,
so no mechanism drags price back to NAV. The mechanisms, who is on the other
side and why they stay there: `docs/BRIEF.md` §2. How the
instruments actually trade — NAV timing, ex-distribution arithmetic, the
closing auction, the short side, corporate events: `docs/BRIEF.md` §3.

**Signal.** For fund *i* on day *t*, discount `d = 100·(P − N)/N`; z-score it
against that fund's own rolling mean and standard deviation, both **shifted one
day** (point-in-time), clipped. Window: orient SPEC `z_window`. It was once
changed to the argmax of a swept column, failed out of sample hours later, and
was reverted — the project's most instructive event.

**Weights.** Cross-sectionally demeaned z, negated, scaled to unit gross, times
a volatility scalar (`vol_target_annual` from the spec over trailing realised
vol, clipped). Three consequences:

- **Cross-sectional, not absolute** — a fund is cheap relative to today's mean
  z, which makes the book dollar-neutral by construction.
- **Ranked against its own history, not peers** — ranking on the raw discount
  would be a permanent long-muni bet dressed as a signal.
- **Volatility-targeted, measured not assumed** — the strategy is best in calm
  markets; a constant-notional book takes its worst losses when each unit of
  risk pays least.

Code: `src/deploy/sleeves/cef_discount.py` **is** the strategy.

**Trading policy: a no-trade band** (since 2026-09-06). The signal is recomputed
every session; a position is left alone unless it is more than `band_width`
(orient SPEC) from target, then traded back to the **band edge, not to target**
— the proportional-cost optimum (Constantinides 1986; Davis & Norman 1990). The
width was derived from a cube-root law, not swept. `rebalance_days` is inert
while `band_width` is set; deleting `band_width` restores the previous calendar
policy exactly, which is the revert path (the v5 spec file itself is at tag
`pre-clean-slate`, `pre-clean-slate:_archive/ops/_archive/cef_discount.v5.20260731.frozen.json`).
Pre-registration: `results/cef/PREREG_BAND_2026-09-06.md`.

**Execution: MOC, and `shift(2)`.** Decide at *t*, fill in the closing auction
of *t+1*, earn the *t+2* return. Every backtest must reproduce that;
`evaluate()` in `scripts/cef/band_frontier.py` is the canonical implementation,
and `EXEC_LAG` in `scripts/cef/validate.py` is asserted at runtime. Why MOC and
not a market order: `CLAUDE.md`, order-path rule 3.

**Universe and holdouts.** The deployed names are the spec's `universe`;
`data/cef/cef_universe.csv` holds the wider set. Two holdouts are sealed and
opened once: **the untouched CEFs** outside the deployed universe (trading any of
them consumes the set), and **a 2023-01-01 time holdout** on every fit.

---

## 2. What is established, what is conditional, what is unknown

Keeping these apart is the most important discipline here. Each claim names
the command or note that settles it. **Before quoting one, check `results/` for
a later note** — this section records the state as of its date.

### Established

| claim | settle it with |
|---|---|
| The discount signal has a real, persistent IC at the traded horizon, present across sub-periods | `python3 scripts/cef/plan_diagnostics.py`; `pre-clean-slate:results/cef/ALPHA_AUDIT_2026-09-05.md` |
| It is not credit beta, not one name, not reversal | `pre-clean-slate:results/cef/ALPHA_AUDIT_2026-09-05.md` |
| The **retired calendar policy fails** the validation battery at an obtainable price (`shift(2)`): deflated Sharpe FAIL at every trial count tried | `python3 scripts/cef/validate.py --trials <CEF counter>`; `pre-clean-slate:results/cef/EXECUTION_CONVENTION_2026-09-10.md` |
| The sealed CEF holdout was opened and its recorded verdict is **FAIL** on net Sharpe; its gross figure is not out-of-sample evidence | `pre-clean-slate:results/cef/HOLDOUT_OPENED.json` |
| The book is not short volatility in a sense that gives a hedging option a job; credit gamma is not timeable by any declared conditioner | `pre-clean-slate:results/cef/STRESS_BETA_2026-09-11.md`; `pre-clean-slate:results/gamma/CONDITIONERS_2026-09-13.md` |

### Measured but conditional

- **The band's net Sharpe and turnover** come from the correct harness but have
  **never been walk-forwarded, bootstrapped or deflated** — nothing in this repo
  tests the traded policy out of sample (2026-09-13 [S], `CLAUDE.md`). That is
  the largest open research gap.
- **Borrow drag** was first charged from one day of fees; the daily fee history
  (`data/cef/cef_borrow_history.parquet`) shows much higher historical borrow on
  some names, so any net-of-borrow figure computed on one day's fees is suspect
  until re-measured. `pre-clean-slate:results/cef/BORROW_NOTE_2026-09-06.md`, `docs/BRIEF.md` H4.

### Unknown, and the unknowns dominate

- **What execution actually costs.** Very few broker-confirmed MOC sessions
  exist (all IBKR, now deleted); the standard error is too wide to act on. Alpaca
  paper fills MOC at the quote rather than in the auction [V: staff forum post,
  2026-09-28], so its paper fills cannot settle this either.
- **Whether the paper record means anything.** The pre-epoch ledger booked
  fills for sessions the account never made; only broker-confirmed fills count.
  The IBKR record ended on 2026-09-28 with 34 flatten orders left unacknowledged
  and the account's final state unknown by decision; the Alpaca book starts a new
  track record.
- **Survivorship.** The panel holds only funds alive today; every CEF that
  closed or merged is absent. The bias is upward and unmeasured.

---

## 3. What binds

The book earns through one relation, Grinold's fundamental law in the Clarke,
de Silva & Thorley (2002) form: **IR ≈ IC · TC · √BR**. Derivation and the three
meanings of "finding alpha": `docs/BRIEF.md` §1.

- **IC** is good, and sharpening it has repeatedly been the least productive
  work.
- **TC, the transfer coefficient** — how much of the ideal book survives costs,
  borrow, availability, rounding and missed sessions — is low. Measure it as net
  ÷ gross from `band_frontier.py` with borrow charged.
- **BR, breadth** — the book holds many names but most of its variance is one
  factor, municipal CEFs against taxable ones, so its effective breadth is a
  small fraction of its name count. Measure on today's weights (the IBKR-era
  dashboard's `/api/factors` did this; it was deleted and has no replacement yet).
- **Uptime** — a session that does not arm earns nothing. On IBKR the book armed
  on a small minority of eligible sessions (session logs at tag `pre-clean-slate`);
  the Alpaca runner must measure its own from day one.

**Work that raises TC or uptime beats work that sharpens IC, every time.**

---

## 4. How it runs

**Rewritten 2026-09-28.** The IBKR-era description — prod worktree and
promotion, launchd sessions, the shared account, halts, verification — is at tag
`pre-clean-slate` (`pre-clean-slate:_archive/docs/SYSTEM_2026-09-28.md` §4). None of it runs any more.

### 4.1 Where things are

- **Nothing trades.** IBKR was retired on 2026-09-28: the scheduler's jobs were
  unloaded, a final flatten was sent and then abandoned (the team lead chose not
  to follow it up), and the repo was cut to a clean slate: everything not needed
  for the Alpaca system was deleted (tag `pre-clean-slate`; `docs/HISTORY.md`).
  `ibkr-final` tags the last IBKR-era commit.
- **The strategy is unchanged in kind**: `src/deploy/sleeves/cef_discount.py` and
  its frozen spec. v7's constraint code is present with its keys off; the spec
  change to v7 on Alpaca is pending (§5, 2026-09-28).
- **The new run package is `quantt/`.** So far it holds one read-only tool:
  `python3 -m quantt.broker.alpaca_probe`, which records what each Alpaca paper
  account holds and whether each spec name is tradable and shortable.
- **Prod will be a cloud VM** (team lead, 2026-09-28). It does not exist yet.

### 4.2 What the Alpaca system must be

Settled by the team lead on 2026-09-28 (§5) or measured from Alpaca's own
documentation the same day [V unless marked]. The design work is still ahead;
this is the brief it answers to.

- **One Alpaca paper account per book**: the CEF book and the b6 equal-weight
  credit benchmark. Alpaca rejects opposite-side orders in one symbol as wash
  trades, so books cannot share an account safely.
- **MOC via `time_in_force=cls`**, whole shares only (fractional orders cannot
  be `cls` or short). Alpaca rejects `cls` entries between 15:50 and 19:00 ET.
- **Not idempotent.** A runner must refuse to send while a set is already
  headed for an unclosed auction; Alpaca's `client_order_id` is unique only
  among *active* orders.
- **The broker is the fact.** Reconcile from Alpaca's positions, orders and
  account activities, not from a local ledger. The IBKR design's ledger
  desyncs halted all three books in September.
- **Score both P&Ls on paper.** Alpaca paper fills MOC at the quote [V: staff
  forum post], so record Alpaca's fill as the official record and the P&L at the
  official closing-auction print (`/v2/stocks/auctions`, SIP feed) beside it,
  labelled. Gross P&L only (D19/D20, 2026-09-15).
- **Alerting is dashboard and logs only** (hardening D3/D4, 2026-09-21,
  confirmed 2026-09-28). A monitor will be rebuilt later.

### 4.3 What counts as evidence

**Only broker-confirmed fills** count toward any live statistic. Modelled
sessions are not evidence. On Alpaca paper the fill price itself is simulated
(above), which is why the auction-print P&L is kept beside it.

### 4.4 Setting up, and reference

- Environment and data: `README.md` (setup).
- The plan to prod: `docs/ROADMAP.md`.
- Credentials live in `config/.env`, which is never printed, copied or read by
  an agent (`CLAUDE.md`, order-path rule 5).

---

## 5. Standing decisions

Moved **as recorded** from `docs/BRIEF.md` §7 and `CLAUDE.md`, in the
order they were made. Work-order ids in the rows (W14, `gamma/`, P-numbers) name
prompts that have since closed; their text is at tag `pre-clean-slate` under `pre-clean-slate:_archive/docs/prompts/`. Nothing here was re-decided when this document was
written. A later entry on the same question supersedes an earlier one only
where it says so; changing a row needs the team lead's name and a date (§7).

### Team lead, 2026-09-08

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

### Team lead, 2026-09-09

| question | decision |
|---|---|
| Per-fund treatment | **Seventeen sleeves, one combined book.** Each fund gets its own signal, band, budget and P&L line; they sum into one portfolio where neutrality, borrow and capacity are managed at book level. → `perfund/F3` |
| Signal structure | **Model form by group (four mechanisms), parameters by fund shrunk within group.** Four trials, not seventeen. → `perfund/F2` |
| What neutrality means | **Undecided by design.** Four candidate rules are pre-declared and tested as one grid; the tie-break is p95 net exposure, not Sharpe. → `perfund/F3` Part B |
| Gamma scalping | **A standalone programme with its own counter and track record** (`gamma/`), **and** the hedge-overlay use case kept in the CEF queue (`W14`), gated on stress-beta evidence. |
| Sources | Every external claim lives in **`docs/REFERENCES.md`** with a verification status. Prompts cite it; they do not re-derive it. |

### Team lead, 2026-09-14

Recorded during the documentation cleanup, in answer to two contradictions the
new documents exposed. Neither changes what trades.

| question | decision |
|---|---|
| Vol target until W6 | **The frozen spec's `vol_target_annual` stays in force** (0.06 when this was decided) **until W6 derives a new value** under the 2026-09-08 "derive it, cap 20%" decision. Until then the two are not in conflict: one is the setting, the other is how its replacement will be chosen. |
| Retiring the null trader | **Open, not yet actioned.** The 2026-09-08 decision stands; `phase0_null` is still a registered book and is halted in prod. Retiring it needs broker-side work a human runs (W2). |

### Team lead, 2026-09-28 — IBKR retired, move to Alpaca

Answered interactively; the full record (the migration manifest) is at tag
`pre-clean-slate`, `pre-clean-slate:results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` §2 and §7.

| question | decision |
|---|---|
| Broker | **Alpaca paper**, our own choice (not a competition requirement). |
| IBKR | **Flatten, archive everything, forget it.** The flatten was sent and left unconfirmed by decision. |
| New system | **Fresh package (`quantt/`), reusing parts.** |
| Books | **The CEF strategy and the b6 equal-weight credit benchmark.** phase0/null trader, b1/b3/b4/b5 and credit_rv retire. |
| Accounts | **One Alpaca paper account per book**, $100k each (the default). |
| Scoring | **Record both**: Alpaca's paper fill is the official record; the closing-auction-print P&L is logged beside it. |
| Hosting | **Cloud VM.** |
| Alerting | **Dashboard and logs only** (keeps hardening D3/D4). |
| Spec | **v7 from day one on Alpaca**, superseding hardening D14. `max_gross_stress` is re-derived on the Alpaca account; `min_trade_usd` and capital re-sized through `/spec-change`. |
| CEF trial counter | **48 is authoritative**; adopting v7 makes it 49. |
| Work orders, dashboard | **Archived**; new work orders as needed; a dashboard rebuilt later. `00_BRIEF` stays live as `docs/BRIEF.md`. |
| Who runs order-path commands | **The agent may, when the team lead asks in the session, after showing the concrete order list and getting a go.** |
| `CLAUDE.md` / settings | **The agent edits them directly for the migration** (supersedes hardening D15/D18 for this work). |
| Clean slate | **Delete everything not needed to run the strategy on Alpaca**, now, before building — supersedes the "never delete, archive" rule. Kept: the strategy and spec, research harness and fetchers, research memory (`RESEARCH_STATE`, `BRIEF`, `REFERENCES`), the band and group-cap pre-registrations, the agents and skills. Old research replaced by `docs/HISTORY.md`. Everything is recoverable from tag `pre-clean-slate`. |
| Research tables | **Gross P&L headline, cost grid beside it, labelled, never mixed.** |
| Universe on Alpaca | **Drop NAD, NEA, NVG, NZF** (not shortable on the Alpaca paper account, probe 2026-09-28). 17 → 13. |
| v7 on Alpaca | **`max_gross_stress` 1.80** (re-derived: Reg T **50%** margin); **`group_cap` off** (its rule gives k = 0 on 13 names, the killed hard-neutrality variant); **`min_trade_usd` $0** (the formula with no per-order fee; whole shares only); capital $100k. The 13-name backtest was **report only, not a gate**. Spec `cef_discount.v7.20260928`; `results/cef/PREREG_ALPACA_V7_2026-09-28.md`; CEF counter 48 → 50. |

### Team lead, 2026-09-28 (evening) — the runner and go-live

Answered interactively while the runner was built. The design they shape is
`docs/RUNNER.md`; the Alpaca facts behind them are
`results/ops/ALPACA_API_FACTS_2026-09-28.md`.

| question | decision |
|---|---|
| Go-live | **Armed on 2026-09-29.** The first session's order list is shown to the team lead before transmit. |
| Where prod runs | **This laptop for now**, a clone at a release tag scheduled by launchd. No VM yet; the free Google Cloud e2-micro was offered and declined for now. |
| After the first go | **The scheduled runner trades daily on its own**, behind the nine gates. Rule 1 in `CLAUDE.md` governs agents in a chat. |
| Day one | **Trade to full target** (`extras["opening_session"]`), not to the band edge. |
| Phase 3 probes | **Design around them**; no probe orders on the account. |
| If `cls` is rejected | **No trade, then ask the team lead.** No fallback to `day`. |
| Hard-to-borrow shorts | **Allowed if `shortable`**; hard-to-borrow is a warning in the preview. |
| A rejected order mid-batch | **Skip that name, send the rest**; the day is FAIL, naming it. An ambiguous submit still stops the batch. |
| Key file for the scheduled job | **Stays `config/.env`**; whether launchd can read it under `~/Downloads` is tested on install, and fails loudly if not. |
| Research and backtest | **Saved workflows** (`.claude/workflows/`); research data from the R2 WRDS mirror (`docs/DATA.md`), never on the live path. |

### Recorded in `CLAUDE.md`, 2026-09-13

**Options are closed, and it is recorded rather than remembered.** `W14` Part A
measured that this book is not short volatility in any sense that gives a hedging
option a job. `G6` then measured that credit gamma costs more in variance than
equity gamma, and that no conditioner times it — C3 clears in sample and fails
the 2023–26 holdout, and no state under any conditioner at any declared
threshold has a positive mean outcome. `G7` does not run and the **GAMMA counter
stays at 0**. The pre-registration (`pre-clean-slate:results/gamma/PREREG_GAMMA_TIMING_2026-09-13.md`)
records what would reopen it. The options status tool, the option-pricing library
and the IBKR option order path were deleted on 2026-09-28 (tag `pre-clean-slate`).

---

## 6. Governance — where each rule lives

| subject | owner |
|---|---|
| Hard rules: order path, code, data, research | `CLAUDE.md` |
| Trial counters and the killed list | `docs/RESEARCH_STATE.md` (counter table and KILLED table are canonical) |
| Harness rules H1–H15 (`shift(2)`, turnover matching, cost grid, eras, IC, holdouts, H14) | `docs/BRIEF.md` §5, and `/harness` |
| Pre-registration | `/prereg`; shape: `results/cef/PREREG_BAND_2026-09-06.md` |
| Changing a frozen spec key | `/spec-change` |
| Dead mechanisms — check before proposing anything | `/graveyard`, and the KILLED table |
| External claims | `docs/REFERENCES.md` |
| Work orders and the plan | `docs/ROADMAP.md`. The old work orders were deleted 2026-09-28 (tag `pre-clean-slate`). |
| Which document owns which question | `docs/INDEX.md`, checked by `python3 -m ops.doc_audit` |

---

## 7. Changes

| date | change | by |
|---|---|---|
| 2026-09-13 | Written, replacing six overlapping descriptions of the system. §5 moved verbatim; no decision re-made. | documentation cleanup, for the team lead |
| 2026-09-28 | §0, §4 rewritten for the IBKR retirement and the move to Alpaca; §5 gains the 2026-09-28 decisions; §2 and §6 repointed. Earlier text at tag `pre-clean-slate`. | Alpaca migration, for the team lead |
| 2026-09-28 | Clean slate: archive references replaced by the tag; plan moved to `docs/ROADMAP.md`. | clean slate, for the team lead |
