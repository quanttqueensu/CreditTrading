# QUANTT — the system

**The one document that says what this book is, how it runs, and what we know
about it.** Written 2026-09-13 from the documents it replaces: the
strategy, system and decision sections of `CLAUDE.md`, `docs/INFRASTRUCTURE.md`,
`docs/prompts/00_BRIEF.md`, the retired `SYSTEM_AND_STRATEGY.md` and `PLAN.md` (both archived under `_archive/docs/`),
and `results/ops/NUMBER_CONSISTENCY_2026-09-10.md` §12.

**It holds no figures that move.** Where a number matters, this document names
the command that produces it. Run the command. The only figures written here
are decisions (which carry a date and a decider) and a few observations that
are labelled `[V]` verified, `[S]` sourced but not re-read, or `[U]` uncertain,
each with a date and the note it came from. Why: every number this repo wrote
into prose about its own state was contradicted by another document within
days — the arm rate existed as four different fractions at once.

`docs/INDEX.md` lists which document owns which question. `CLAUDE.md` holds the
rules. `_archive/` holds the superseded record and is never authority.

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
6. **`_archive/`** — provenance only.

**Which artifact answers which question.** Keyed by question, not by quantity,
because most contradictions in this repo's history were two artifacts
answering different questions. (Adapted from
`results/ops/NUMBER_CONSISTENCY_2026-09-10.md` §12, figures removed.)

| question | authoritative artifact |
|---|---|
| Where am I, what does prod lack, what is halted, what is the spec? | `python3 -m ops.orient` |
| What is resting at the broker right now? | `ib.reqAllOpenOrders()`, one read-only connection. Nothing in the repo can say an order is still working. |
| What was transmitted, and when? | `ops/books/<book>/_ibkr_shadow/_order_map.csv` — written at placement, carries the IBKR `orderId` |
| What did the strategy decide, and why? | `ops/books/<book>/target_vs_current.csv` — target weights, z-score, band/hold reason per name |
| What actually filled? | `.../cef_discount/broker_fills.csv` — **the only evidence of a fill.** `trades.csv` contains modelled fills. orient BOOK prints executions per fill date. |
| Did today's trades happen? | `python3 -m ops.verify_session` — asks the broker after the close, one message per trading day (§4.6) |
| What is actually held? | broker `ib.positions()` — three books share one account; never attribute a symbol from the account net (§4.3) |
| What does the ledger believe is held? | `.../cef_discount/positions.csv` — a local reconstruction; verify against the broker, do not assume |
| What is the sleeve NAV / P&L? | `.../cef_discount/nav.csv` — modelled, epoch-seeded. The dashboard and `report_*.md` restate it; they are not corroboration. |
| What is the account worth? | broker `NetLiquidation` — whole account, all books, not comparable to a sleeve NAV without attribution |
| What are the live parameters? | orient SPEC, which reads the frozen spec through `scripts/cef/spec.py` |
| Gross / net Sharpe and turnover of the live policy? | `python3 scripts/cef/band_frontier.py`, re-run |
| IC, persistence, PCA, ADV, vol scalar? | `python3 scripts/cef/plan_diagnostics.py`, re-run |
| Effective breadth? | dashboard `/api/factors` — a live quantity with no stored value |
| Is the book arming? | `python3 -m ops.session_uptime` (reads both log trees; refuses rather than undercounts) |
| Did one session arm, and why not? | `ops/schedule/logs/cef_<date>.log` in **prod** — the `ARMED:` / `NOT ARMED ->` line |
| How many trials have been spent? | `docs/RESEARCH_STATE.md` counter table (not its prose); orient TRIALS derives the deflated-Sharpe bar |
| How many tests pass? | `python3 -m pytest`, run now. Never quote a stored count. |
| What is running in production? | orient TREES, or `git -C ~/prod/QUANTT describe --tags` |
| Where is a work order? | `python3 -m ops.prompt_status` |
| Is an external claim verified? | `docs/REFERENCES.md` |
| Do the documents still say true things? | `python3 -m ops.doc_audit` |

---

## 1. What we trade

A **systematic credit closed-end-fund discount-reversion book** on an IBKR paper
account, placing its own MOC orders on a schedule. The account id, capital and
universe are in the frozen spec. **Mandate** (§5): paper indefinitely, a
competition track record, judged on absolute return under a vol cap.

**The trade.** A closed-end fund publishes a net asset value daily and its
shares trade at whatever the market pays. Buy funds unusually cheap against
*their own* discount history, short the ones unusually rich, in equal dollars.

**Why it is not arbitraged away.** A CEF has a fixed share count and no
authorised participants. Nothing creates or redeems shares against the basket,
so no mechanism drags price back to NAV. The mechanisms, who is on the other
side and why they stay there: `docs/prompts/00_BRIEF.md` §2. How the
instruments actually trade — NAV timing, ex-distribution arithmetic, the
closing auction, the short side, corporate events: `00_BRIEF.md` §3.

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
policy exactly, which is the revert path (the archived `_archive/ops/_archive/cef_discount.v5.20260731.frozen.json`).
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
| The discount signal has a real, persistent IC at the traded horizon, present across sub-periods | `python3 scripts/cef/plan_diagnostics.py`; `results/cef/ALPHA_AUDIT_2026-09-05.md` |
| It is not credit beta, not one name, not reversal | `results/cef/ALPHA_AUDIT_2026-09-05.md` |
| The **retired calendar policy fails** the validation battery at an obtainable price (`shift(2)`): deflated Sharpe FAIL at every trial count tried | `python3 scripts/cef/validate.py --trials <CEF counter>`; `results/cef/EXECUTION_CONVENTION_2026-09-10.md` |
| The sealed CEF holdout was opened and its recorded verdict is **FAIL** on net Sharpe; its gross figure is not out-of-sample evidence | `results/cef/HOLDOUT_OPENED.json` |
| The book is not short volatility in a sense that gives a hedging option a job; credit gamma is not timeable by any declared conditioner | `results/cef/STRESS_BETA_2026-09-11.md`; `results/gamma/CONDITIONERS_2026-09-13.md` |

### Measured but conditional

- **The band's net Sharpe and turnover** come from the correct harness but have
  **never been walk-forwarded, bootstrapped or deflated** — nothing in this repo
  tests the traded policy out of sample (2026-09-13 [S], `CLAUDE.md`). That is
  the largest open research gap.
- **Borrow drag** was first charged from one day of fees; the daily fee history
  (`data/cef/cef_borrow_history.parquet`) shows much higher historical borrow on
  some names, so any net-of-borrow figure computed on one day's fees is suspect
  until re-measured. `results/cef/BORROW_NOTE_2026-09-06.md`, `00_BRIEF.md` H4.

### Unknown, and the unknowns dominate

- **What execution actually costs.** Very few broker-confirmed MOC sessions
  exist; the standard error is too wide to act on. `/fill-audit`.
- **Whether the paper record means anything.** The pre-epoch ledger booked
  fills for sessions the account never made; only broker-confirmed fills count.
  The CEF sleeve's ledger was re-seeded from broker positions at an epoch dated
  2026-09-11, with the old ledger archived beside it (2026-09-13 [V], `epoch`
  and `epoch_reason` in prod's `ops/books/cef_live/_ibkr_shadow/cef_discount/manifest.json`;
  procedure in `results/ops/GO_LIVE_W3_2026-09-13.md`).
- **Survivorship.** The panel holds only funds alive today; every CEF that
  closed or merged is absent. The bias is upward and unmeasured.

---

## 3. What binds

The book earns through one relation, Grinold's fundamental law in the Clarke,
de Silva & Thorley (2002) form: **IR ≈ IC · TC · √BR**. Derivation and the three
meanings of "finding alpha": `00_BRIEF.md` §1.

- **IC** is good, and sharpening it has repeatedly been the least productive
  work.
- **TC, the transfer coefficient** — how much of the ideal book survives costs,
  borrow, availability, rounding and missed sessions — is low. Measure it as net
  ÷ gross from `band_frontier.py` with borrow charged.
- **BR, breadth** — the book holds many names but most of its variance is one
  factor, municipal CEFs against taxable ones, so its effective breadth is a
  small fraction of its name count. Measure on today's weights: `/api/factors`.
- **Uptime** — a session that does not arm earns nothing. `python3 -m ops.session_uptime`.

**Work that raises TC or uptime beats work that sharpens IC, every time.**

---

## 4. How it runs

### 4.1 Two trees, and promotion

```
$ git worktree list
~/Desktop/2027/QUANTT/2027   <sha> [main]            <- dev: where work happens
~/prod/QUANTT                <sha> (detached HEAD)   <- prod: == a release tag
```

Prod is a git worktree **detached at a tag**; the scheduler, the dashboard and
the live ledgers run there, and nobody edits it. It never appears in
`git branch`. "Detached HEAD" is the intended steady state. What prod lacks
from dev: orient TREES.

The whole boundary is one line — `REPO` in
`~/Library/Application Support/quantt/launch_job.py`, which lives **outside** the
repo because macOS TCC denies launchd access to `~/Desktop`. Code reaches prod
only through `ops/promote.sh <tag>`, which refuses inside the session window or
on a prod tree with uncommitted code, archives live state, checks out the tag,
smoke-tests it (doctor, NAV wait, fetch, dry-run session, dashboard import) and
rolls back on any failure. **Never cut a tag off the prod tag** — it would not
be an ancestor of `main`, and the next promotion from dev would drop it (orient
TREES prints `dev lacks` when this has happened).

Shared deliberately and temporarily: `~/prod/QUANTT/data` is a symlink to dev's
`data/`, so a research script can still corrupt what the sleeve prices from
(`ops/sync_dev_data.sh` reverses it); and the live ledgers are gitignored but
still tracked, which is why the promotion gate excludes them by pathspec.

### 4.2 Sessions

**Schedule** (2026-09-13 [V], `launchctl list | grep quantt` and the plists in
`~/Library/LaunchAgents`): since the W3 go-live the CEF book **decides in the
morning on yesterday's complete price/NAV pair** and sends MOC orders for that
day's close (`com.quantt.cef.daily`, with a midday retry); an evening job
(`com.quantt.cef_pm`) and a post-close verifier (`com.quantt.verify.cef`,
§4.6) follow. Why the evening decision was abandoned — NAV-wait sleeps and IB's
nightly restart destroying fill records — is in `results/ops/GO_LIVE_W3_2026-09-13.md`.
Which plan a given fire follows: `ops/session_plan.py`. The machine's own
readiness to run unattended: `python3 -m ops.doctor --quick`.

**The session contract** (the `launch_job.py` docstring is canonical). Four
phases with **different failure policies**:

| phase | on failure |
|---|---|
| 1. REFRESH prices/NAV | do not trade, still log — a stale NAV is a blind signal |
| 2. PREFLIGHT | do not trade, still log |
| 3. TRADE | halt + alert |
| 4. CAPTURE fills | **always runs**, even after 1–3 fail — IB forgets executions at its daily restart |

The trade phase is **not idempotent**, `DRY_RUN=1` always wins, and the order
type stays MOC: `CLAUDE.md`, order-path rules. What the preflight gate checks:
`docs/INFRASTRUCTURE.md` §6.4 and `python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live`.

### 4.3 Books and the shared account

Several books share **one IBKR account with overlapping tickers**; the books are
`ops/books/*_book.json`. Attribution is per sleeve (`_attribution.json`,
`_order_map.csv`); `reconcile()` checks the tagged books sum to
`ib.positions()`. **Never take a symbol from the account net.**

`arm()` re-seeds each sleeve from the broker before a live session because the
ledger is a local reconstruction and the account is the fact — **but the
re-seed cannot reach a symbol the broker holds none of** (IBKR emits no row for a
flattened position), so a stale ledger quantity there goes unchallenged into
order sizing. A ledger-vs-broker divergence of that shape is a trading fault,
not a reporting one (`results/ops/LEDGER_DIVERGENCE_2026-09-10.md`).

`ops/books/retired/` holds retired book specs and **must not move**:
`IBKRBroker._foreign_book_claims` globs `ops/books/*.json` non-recursively, and
that location is what keeps a retired book's symbols out of the check.

### 4.4 Halts

**This section is the one place halts are described.**

- `ops/HALT.md` is **global** and blocks every book — a human halt, or a fault
  nobody can attribute.
- `ops/HALT_<book>.md` blocks **one** book and reaches the others as a
  non-blocking preflight warning. `arm()` failures write this one, because arm
  only refuses on symbols the failing book trades.
- **Halts are written in prod and are untracked.** `ls ops/HALT*.md` in dev
  returns nothing while prod is halted. Read both trees: orient HALTS, or
  `ls ~/prod/QUANTT/ops/HALT*.md`.
- Clear with attribution, never by deleting the file:
  `python3 -c "from ops.halt import clear_halt; clear_halt('what was fixed')"`,
  or `clear_halt(note, book='<book_id>')` for a scoped one — the `book_id` inside
  the book file (e.g. `phase0_null`), not the file's name. Clearing the global
  never silently clears a scoped halt. Cleared halts are archived to `ops/halts/`.
- **`ops/halt.py` resolves paths from the tree it is imported from**, so
  `clear_halt` must run **in `~/prod/QUANTT`**; run from dev it finds no halt and
  returns False. Clearing changes what trades, so it is a human action (`!`).
- Untracked files survive a promotion by accident rather than design — `git
  checkout` cannot remove them — and nothing tests that.

### 4.5 What counts as evidence

**Only broker-confirmed fills** (`broker_fills.csv`) count toward any live
statistic. Modelled sessions — ledger rows for sessions that never traded — are
not evidence. A sizing difference between `orders.csv` and `_order_map.csv` can
arise with no position error at all (sized against registered capital vs marked
NAV); never diagnose that gap as a position error without checking which base
the day's orders were sized on.

### 4.6 Alerting and verification

- `ops/halt.py` escalates across a halt file (read by preflight as a hard gate,
  survives reboots), a macOS banner and email; each channel is guarded
  separately so a mail failure cannot prevent the halt being recorded.
- `ops/verify_session.py` asks the broker after the close whether the day's
  trades happened — what was transmitted, executed, held, believed and resting
  — and sends **one message per trading day, pass or fail**, so silence is
  itself the alert.
- Whether email delivery is configured on this machine is a measurement, not a
  fact to carry: `python3 -m ops.doctor --quick`.
- The read-only monitor: `python3 dashboard/server.py` on :8787, including
  `/api/sessions` (per-session arm/miss across both log trees).

### 4.7 Setting up, and reference

- Environment, data rebuild, verification: `docs/INFRASTRUCTURE.md` §2.
- IBKR API client ids (one session per id; a collision evicts silently):
  `docs/INFRASTRUCTURE.md` §6.2.
- IB Gateway and IBC: `deploy/ibgw/README.md`.
- Credentials live in `config/.env`, which is never printed, copied or read by
  an agent (`CLAUDE.md`, order-path rule 5).

---

## 5. Standing decisions

Moved **as recorded** from `docs/prompts/00_BRIEF.md` §7 and `CLAUDE.md`, in the
order they were made. Nothing here was re-decided when this document was
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

### Recorded in `CLAUDE.md`, 2026-09-13

**Options are closed, and it is recorded rather than remembered.** `W14` Part A
measured that this book is not short volatility in any sense that gives a hedging
option a job. `G6` then measured that credit gamma costs more in variance than
equity gamma, and that no conditioner times it — C3 clears in sample and fails
the 2023–26 holdout, and no state under any conditioner at any declared
threshold has a positive mean outcome. `G7` does not run and the **GAMMA counter
stays at 0**. The pre-registration (`results/gamma/PREREG_GAMMA_TIMING_2026-09-13.md`)
records what would reopen it; `python3 -m ops.gamma_status` prints where the
programme actually stands. The option-pricing library and the fixed order path
stay, but nothing trades them.

---

## 6. Governance — where each rule lives

| subject | owner |
|---|---|
| Hard rules: order path, code, data, research | `CLAUDE.md` |
| Trial counters and the killed list | `docs/RESEARCH_STATE.md` (counter table and KILLED table are canonical) |
| Harness rules H1–H15 (`shift(2)`, turnover matching, cost grid, eras, IC, holdouts, H14) | `docs/prompts/00_BRIEF.md` §5, and `/harness` |
| Pre-registration | `/prereg`; shape: `results/cef/PREREG_BAND_2026-09-06.md` |
| Changing a frozen spec key | `/spec-change` |
| Dead mechanisms — check before proposing anything | `/graveyard`, and the KILLED table |
| External claims | `docs/REFERENCES.md` |
| Work orders and their status | `docs/prompts/README.md`, checked by `python3 -m ops.prompt_status` |
| Which document owns which question | `docs/INDEX.md`, checked by `python3 -m ops.doc_audit` |

---

## 7. Changes

| date | change | by |
|---|---|---|
| 2026-09-13 | Written, replacing six overlapping descriptions of the system. §5 moved verbatim; no decision re-made. | documentation cleanup, for the team lead |
