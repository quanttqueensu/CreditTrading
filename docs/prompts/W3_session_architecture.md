# W3 — The session: decide in the morning, source the data twice, be loud when it fails

**Reads first:** `00_BRIEF.md` §3 (how these instruments trade), §5 (harness),
§6 (house rules), §7 (standing decisions).
**Lever:** TC and reliability. The book armed on 3 of 26 sessions and nobody
was told. **Trials:** 0 — none of this changes *what* the sleeve computes,
only *when* it runs, *where* its inputs come from, and *who* hears about it.
**Touches the live book:** yes.
**Scheduled for Thursday 2026-09-10** (the prod/dev split lands Wednesday).
**Supersedes:** P8.1, P8.2, P0.4, P4.3.

---

## Paste from here

You are working in the QUANTT credit CEF repo. Read `docs/prompts/00_BRIEF.md`,
then:

> **⚠ Corrected 2026-09-10.** An earlier version of this prompt opened *"you are
> working on the PROD checkout"* and its header said the prod/dev split would
> land on Wednesday 2026-09-09. **It did not. Verified 2026-09-10: `~/prod/`
> does not exist and `launch_job.py:54` still points `REPO` at the dev tree**,
> so the scheduler runs the same working tree research edits. `W0b` deploys the
> split; run it first if you can. If you cannot, **every change in this prompt
> lands directly in the tree that trades tomorrow morning** — work accordingly,
> and do not leave the tree in a half-edited state at the end of a session.

1. `~/Library/Application Support/quantt/launch_job.py` — the session contract
   (REFRESH → PANELS → PREFLIGHT → TRADE → CAPTURE), the same-day guard, the
   `wait` step added 2026-09-08, `halt_mod.beat`. **It lives outside the repo
   on purpose** (macOS TCC denies launchd agents access to ~/Desktop; only the
   Anaconda python holds Full Disk Access). Read it; do not move it.
2. `ops/schedule/logs/cef_2026-09-08.log` — the first night of the NAV wait.
   At 19:27 ET neither yfinance nor CEFConnect had a single one of the 17
   NAVs for the day.
3. `scripts/cef/band_frontier.py::evaluate` — `H.shift(2)`: decide on the pair
   at *t*, MOC fill at the *t+1* close, earn *t+1* → *t+2*.
4. `src/deploy/exec_ledger.py` — `decision_date` and `fill_date`. The ledger's
   fill date must equal the broker's fill date or the P&L record is wrong by a
   day.
5. `src/deploy/broker/ibkr.py::arm` and `place_targets`; `ops/capture_fills.py`;
   `ops/halt.py`; `ops/preflight.py`; `ops/doctor.py`; `ops/heartbeat.json`.
6. `scripts/cef/fetch_daily.py` (after the 2026-09-08 changes: `--require-asof`,
   `--nav-fallback cefconnect`, the before-16:05 guard),
   `scripts/cef/wait_for_nav.py`, `src/deploy/sleeves/cef_discount.py::_panel`,
   `src/deploy/run_book.py::_load_cef`.
7. `~/Library/LaunchAgents/com.quantt.*.plist`, `ops/schedule/install.sh`,
   `com.quantt.awake.plist`.

Four parts. A and B change the schedule and the data path and must land
together on Thursday. C and D make failure audible and visible.

---

## Part A — The morning decision

### The insight, in one line

A decision made at 08:30 on day *D* from the completed pair of *D−1*, placed as
MOC for *D*'s close, is **the same trade** as a decision made at 20:00 on *D−1*
from the same pair — identical fill, identical information — except that at
08:30 the pair is complete on every vendor and the gateway has been up since
its 03:00 restart. The publication race disappears, and it is exactly the
backtest's convention: pair at *t*, fill at *t+1*.

The only thing the morning cannot do is capture the previous day's fills, since
IB's `reqExecutions` serves the current TWS session and the 03:00 restart
empties it. So capture moves to a small evening job. Two jobs, two questions:
**the morning decides, the evening records.**

### Morning session `cef` at 08:30 ET

- The `cef` job's `asof` becomes the **previous trading day**
  (`nyse_calendar --prev today`), not today. Refresh requires the pair complete
  for that date (`fetch_daily --require-asof <prev>`), the sleeve decides on
  it, and the shadow ledger's `fill_date` for those orders is **today** —
  verify by reading how `exec_ledger` derives the fill date from `asof`
  (decision *t* → fill *t+1*; with `asof = prev`, *t+1* is today). If it
  derives the fill date from the calendar, confirm it uses the NYSE calendar
  and not `+1 day`.
- **`arm()` cancels any resting order carrying this book's client id before
  placing anything**, logging each cancellation. This is the fix for the
  2026-09-04→08 incident and it lives at arm time, not in a separate tool.
- The **same-day guard becomes a same-pair guard**: the heartbeat records
  `pair_date`; an armed run for a `pair_date` that already has an armed
  heartbeat is refused. This is what makes morning-plus-evening safe — the
  evening fallback on *D* decides on pair *D*, and the morning of *D+1* would
  decide on pair *D* again, and must be refused by the guard rather than by
  luck.
- A **retry** fire at 12:00 ET runs the same job. The same-pair guard makes it
  a no-op if 08:30 armed. If 08:30 failed, 12:00 is a second chance
  comfortably inside the auction cutoff: **NYSE MOC and LOC orders may be
  entered, modified or cancelled only until 15:50 ET; after 15:50 they cannot
  be modified or cancelled at all, and new closing-only interest may be entered
  only on the side that offsets a published imbalance.** Nothing in this
  system may assume an order can be pulled after 15:50.
- `NAV_DEADLINE` in the morning: poll at most 45 minutes (to 09:15) for a
  straggler NAV, then stand down for that fire and let 12:00 try again.

### Evening capture `cef_pm` at 17:30 ET

- `JOBS["cef_pm"]` with `capture_only: True`: no refresh, no trade; phase 4
  (`capture_fills --slippage`) and the heartbeat key `cef_pm`. It runs after
  the 16:00 fills and before the 03:00 restart, and **must run even on a day
  the morning did not arm** — there may be fills from a resting order.
- The **evening fallback**: if today's heartbeat shows no armed `cef` for pair
  *D−1*, `cef_pm` runs the existing wait-for-today's-NAV path and, if the pair
  completes by 21:30, decides on pair *D* for the *D+1* close — the 2026-09-08
  behaviour, now the exception. It writes `pair_date = D` so the next morning's
  guard refuses the duplicate.

### Scheduling

Plists: `com.quantt.cef.daily` → 08:30 and 12:00 Mon–Fri; new
`com.quantt.cef.pm` → 17:30 Mon–Fri. Render with `install.sh`; the human
enables. `com.quantt.awake`: caffeinate from **08:00** to 22:30. Phase0 (being
retired in W2) and benchmarks (17:25) keep their slots; confirm no client id is
shared with the new jobs. Doctor checks the new plists and the new window.

### Prove it before Thursday, on dev

With `DRY_RUN=1`: run the morning path against a Wednesday-morning snapshot and
confirm (a) the required pair date is Tuesday, (b) the dry-run targets equal
what the evening path would have produced on Tuesday's pair, **byte for byte**,
(c) the ledger dry-run dates the fill Wednesday. Then the same-pair guard test
(two runs, second refused) and the evening fallback with a faked "no armed
heartbeat".

---

## Part B — Two inputs, two sources each

The signal is price minus NAV and both halves currently arrive through one
vendor, yfinance, which (a) returned "possibly delisted" for HYT on 2026-09-04,
leaving the panel without a close the executor would have flattened a $38k
position over, (b) serves a partial session as a `Close` before 16:00, and (c)
for NAV is one redistributor of a feed we could read from two others.

### Prices: the broker is the source

We trade these 17 names through IBKR; its `reqHistoricalData` daily bars
(`whatToShow="TRADES"`, `useRTH=True`, `barSize="1 day"`) are the official
closes of the instruments we hold, from a session we already maintain, with no
ticker-mapping risk and no partial bars.

1. `scripts/cef/fetch_prices_ibkr.py`: for every ticker in the panel (44),
   request the last 10 daily bars (44 requests, well under IB's 60-per-10-min
   pacing), normalise to the panel schema, append with the same
   `drop_duplicates(keep="last")` discipline. Never write a bar dated today
   before 16:05. Own client id from `config/.env` (`DATA_CLIENT_ID`).
2. **History check, once.** Pull IBKR's full daily history for the 44 and
   compare close-by-close with the yfinance-built panel. Report the
   disagreement rate at > 1 tick by name and by year, and every disagreement
   > 1%. Splits: yfinance `auto_adjust=False` versus IB raw TRADES bars should
   agree; where they do not, resolve against the fund's own statement and write
   it down. **Decide with evidence** whether to rebuild the panel from IBKR or
   keep the yfinance history and switch only the forward source: rebuild if the
   disagreement rate exceeds 0.1% or any disagreement exceeds a tick.
3. Cross-check rule, every session: for each (ticker, date) both sources
   report, |IBKR − yfinance| > 1 tick → log the pair, use IBKR, count it in the
   heartbeat (`price_disagreements`). Three or more in one session → alert.
4. `fetch_daily.py` becomes NAV-only plus the completeness gate; its price path
   is **deleted**, not left as a fallback. If the gateway is down at refresh
   time there is no price for today's pair and the session stands down — which
   is correct, because it could not have traded either.

### NAV: three channels, one agreement rule

NAV originates at the sponsor and reaches every vendor through Nasdaq's fund
network. Note what the 1940 Act does and does not require of a *closed-end*
fund's NAV publication frequency and timing, and record what you find in the
note — the schedule we depend on is sponsor practice, not a legal deadline, and
the channel log below is how we learn each sponsor's actual habit.

- **A. yfinance `X{tk}X`** (today's source).
- **B. CEFConnect `pricinghistory/{tk}/1Y`** — dated daily rows (verified
  2026-09-08: 246 rows, agreeing with A to the cent on 21 of 21 comparisons
  except AWF 11.22 vs 11.21). Never `DailyPricing`: it carries no date.
- **C. Sponsor first-party.** The sponsor map, verified 2026-09-09 against
  `cef_facts.csv` — **do not assume it from the group**:

  | sponsor | names |
  |---|---|
  | Nuveen | NAD, NEA, NVG, NZF (muni), JFR (loan) |
  | BlackRock | **MQY, MHD (muni)**, BIT (multi), HYT (hy) |
  | PIMCO | PDI, PTY, PDO, PCN, PHK, PFN |
  | DoubleLine | DSL |
  | AllianceBernstein | AWF |

  Open each sponsor's product page in a headless browser once, record the XHR
  endpoint it calls for daily NAV, and call that endpoint directly with a
  fixture-backed test. If it is not stable or needs a session token, fall back
  to rendering and parsing, and mark the channel fragile in the log.
  **Nuveen runs CEFConnect, so channel B is already Nuveen-sourced for the five
  Nuveen names; C is the check that B has not been re-rounded or delayed, and
  it is the only first-party channel at all for the twelve that are not
  Nuveen.** Note PIMCO's site actively blocks automated fetches (HTTP 403 to
  both curl and a plain fetcher, observed 2026-09-09); for PIMCO, try the
  wire-service route (GlobeNewswire / Business Wire carry the same 19a-1 and
  NAV releases and are not bot-protected) before investing in a headless
  browser, and record which route you used.

Agreement, per (ticker, date):
- All reporting channels agree to the cent → write it.
- Disagreement of exactly one cent → write the sponsor value if C reports, else
  A; log the disagreement with all values.
- Disagreement > one cent, or A and B both missing → the name is
  **INCOMPLETE** for that date. A NAV we cannot confirm is not a NAV, and the
  completeness gate stands the session down (or the 12:00 retry looks again).

Record, per channel, the first session at which each (ticker, date) was seen,
in `data/cef/nav_channel_log.csv`. After twenty sessions this is
publication-time evidence the programme has never had; summarise it by sponsor.

### The sleeve does not change

`_panel` reads the same two parquet files. Prove it: the sleeve's targets on
the last five complete pairs are byte-identical before and after.

---

## Part C — Make a non-armed session loud

A book that runs unattended has exactly two acceptable states at 18:30 ET on a
trading day: it traded, or a human has been told why it did not. "Wrote
`ok_not_armed` to a JSON file" is neither. The fault of 2026-08-03→08-28 was
not that the system misbehaved — preflight correctly refused to trade on a
wrong port — it was that the refusal was silent for a month.

1. **Alert on not-armed.** In `launch_job.py`, after PREFLIGHT, when today is a
   trading day, `DRY_RUN=0`, and `arm` is False: call the alert path
   `ops/halt.py` uses, subject `QUANTT cef: NOT ARMED <date>`, body listing the
   blocking checks and their details. Do **not** write `HALT.md` (a halt is a
   human hard stop; a non-armed session is a soft fault that retries tomorrow).
   Heartbeat gets `"needs_human": true` and `"blockers": [...]`. A `DRY_RUN=1`
   session is a human choice and does not alert; say so in the log.
2. **Alert on silence.** The watchdog checks, on a trading day: a `cef`
   heartbeat dated today by **09:30** (alert 09:45), the 12:00 retry's outcome
   by 12:30, a `cef_pm` heartbeat by 18:30, and the benchmarks heartbeat.
   Missing → `QUANTT: NO SESSION RECORDED <date>`. The watchdog itself is
   watched: if its own heartbeat is older than one trading day, the dashboard
   state strip turns red.
3. **Email that works.** `ops/halt.py` reads SMTP settings from `config/.env`
   (`ALERT_SMTP_HOST`, `_PORT`, `_USER`, `_PASS`, `ALERT_TO`), documented in
   `docs/INFRASTRUCTURE.md` §4.1, **never printed or logged**. Send a test
   through `halt.py`'s own function, confirm receipt, make
   `ops/doctor.py::check_alerts` PASS, and add a weekly "alive" email so a dead
   alert path is noticed within seven days.
4. **Confirm fill capture actually runs.** Grep the last three sessions' logs
   for the CAPTURE phase and `capture_fills`; show the lines. If it ran, show
   `broker_fills.csv` growing on 2026-09-01 and 2026-09-04. If it did not, wire
   it as phase 4, unconditional, wrapped so its failure is logged and alerted
   but never prevents the heartbeat, then run it by hand and show its output.
5. **Sleep.** Doctor warns that a closed lid sleeps the machine. Either
   `pmset repeat wake` weekdays or `caffeinate` inside `com.quantt.awake`; pick
   the one that survives a closed lid, install it, and make `doctor.check_sleep`
   PASS with `pmset -g sched` as evidence.

Test plan, and paste the evidence: force `arm=False` with a temporary halt, run
the job with `DRY_RUN=0` outside market hours, confirm the alert arrives on
banner, speech and email with the blocker listed, then clear it. Age the
heartbeat's cef entry by a day, run the watchdog, confirm the silence alert,
restore.

---

## Part D — Watch the session as it runs

At 08:29 ET the operator should see a strip move: REFRESH · PANELS · WAIT ·
PREFLIGHT · TRADE · CAPTURE, each grey, then blue with a start time, then green
with a duration or red with a reason.

1. **Progress file.** At every phase transition, `launch_job.py` writes
   `ops/books/cef_live/session_progress.json` **atomically** (temp file +
   `os.replace`): `{date, job, dry_run, pair_date, phases: [{name, status
   (pending|running|ok|skipped|failed), started, ended, detail}], log_path,
   updated}`. `WAIT` carries the NAV poll state and which names are still
   missing. Non-trading days write one record with
   `"status": "skipped_non_trading_day"`. The write is wrapped so it can never
   raise into the session and never changes its exit code or timing.
2. **Server.** The dashboard's file-stat loop watches the progress file and the
   current log; on change it publishes `session.progress` and `session.log`
   (tail by byte offset, never re-send). `/api/session` returns the current
   progress and the last 200 log lines for a cold load. History: keep the last
   60 records under `ops/books/cef_live/session_history/`, copied at CAPTURE
   end, deep-linked as `#session/2026-09-10`.
3. **Not-started states**, client-side from the NYSE calendar and the clock:
   amber if no record dated today by 09:00 ET, red by 09:45, when it is a
   trading day.

Acceptance: run the job by hand with `DRY_RUN=1` and watch the strip move with
no page reload; kill it during TRADE and confirm TRADE shows failed with the
exception text while CAPTURE still ran; the progress file is valid JSON at
every instant.

---

## Deliverables

- The `launch_job.py` changes (outside the repo — note the diff in the commit
  message since git does not see it), the two new plists, the watchdog changes,
  `com.quantt.awake` from 08:00, doctor passing on alerts and sleep.
- `scripts/cef/fetch_prices_ibkr.py`; NAV channels inside `fetch_daily.py` (or
  a `fetch_nav.py` it calls); `data/cef/nav_channel_log.csv`;
  `price_source_log.csv`; the sponsor-endpoint fixture test.
- `results/cef/DATA_SOURCES_<date>.md`: the IBKR-vs-yfinance history table, the
  rebuild decision and its evidence, the agreement-rule statistics after the
  first week, the sponsor endpoint documented (URL pattern, fields, observed
  publication time), and what the 1940 Act actually requires.
- `ops/reports/ALERTING_2026-09.md`: what alerts exist, what each means, the
  test evidence. `ops/AUTOMATION.md` gains a table: condition → channel → what
  the human should do. `docs/INFRASTRUCTURE.md` §4.1 and the data section
  rewritten.
- `session_progress.json` and `/api/session`.

## Acceptance

- Thursday 08:30: the log shows pair 2026-09-09 complete, arm, cancel-stale
  (zero or more), orders placed, heartbeat `cef` armed with
  `pair_date = 2026-09-09`. 12:00: refused by the same-pair guard. 17:30: fills
  captured, slippage row written, heartbeat `cef_pm`.
- No session decides on a pair older than one trading day, ever again, except
  through the logged evening fallback.
- The sleeve's targets on the last five complete pairs are byte-identical
  before and after Part B.

## Do not

- Do not keep `asof = today` in the morning and let the sleeve "fall back to
  the last complete pair". The ledger would date the fill tomorrow while the
  broker fills today. The asof **is** the previous trading day.
- Do not remove the evening wait code; it is the fallback.
- Do not fire the morning job before 08:15 — IBC's 03:00 restart plus login
  must be verifiably complete.
- Do not compute, estimate or nowcast a NAV anywhere on the order path.
  Estimated NAV is research (W13); the sleeve trades the published number.
- Do not forward-fill a price or a NAV. A gap stands the session down.
- Do not add a paid feed. Free channels is the standing decision; revisit only
  with the channel log in hand.
- Do not let any alert path raise into the session; every notification is
  wrapped, the heartbeat write is unguarded and first.
- Do not print credentials anywhere, including test output.
- Do not move `launch_job.py` into the repo, and do not change `REPO` in it.
