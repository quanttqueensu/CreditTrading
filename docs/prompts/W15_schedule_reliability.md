# W15 — A trading schedule that does not break: uptime as the first-class deliverable

**Status:** in progress — written 2026-09-11 ~12:00 ET. Written after the desk lead's observation
that "something breaks literally everyday" — which is measurably true, and the
measurement is the useful part.
**Reads first:** `00_BRIEF.md` (standing brief), `CLAUDE.md` (hard rules — the
order path especially), `results/ops/HALT_20260911_103200.md` (the 17h20m
session), `docs/prompts/NEXT_2026-09-11.md` §0b (the promotion deadlock).
**Lever:** uptime, which is the `√BR` and the `TC` in `IR ≈ IC · TC · √BR` at
once. A session that does not arm has IC 0.
**Trials:** 0. This prompt spends none. **Touches the live book:** lanes A, B, E
do. Lanes C, D, F, G do not.

`[V]` = verified by running the command shown, on 2026-09-11 between 11:49 and
11:56 ET. `[S]` = sourced, not re-read. Every figure here is a dated observation,
not an input to a decision rule (H14) — **re-measure before acting.**

---

## 0. The state as measured, 2026-09-11 ~11:50 ET

```
prod        ~/prod/QUANTT     7fe3ad8, tag v2026.09.11.2, detached      [V]
dev         ~/Desktop/2027/QUANTT/2027   main @ 8f5c111, clean          [V]
third tree  /private/tmp/claude-501/.../ops2  branch ops-guards-20260911 [V]
gateway     java pid 37143 LISTEN on 127.0.0.1:4002                     [V]
power       AC, 97%; caffeinate pid 38452 holds PreventSystemSleep
            for 54000s from ~09:00; `pmset -g` reads `sleep 0`          [V]
halts       prod: ops/HALT_phase0_null.md active. dev: none.            [V]
book        NAV $504,030.09 at 2026-09-10; 4 MOC orders resting into
            2026-09-11's close: JFR +97, MHD +115, NAD +1317, NEA +107  [V]
tests       dev `python3 -m pytest` green. Do not write the count here.  [V]
```

Reproduce every line before you use it:

```bash
git -C ~/prod/QUANTT describe --tags && git -C ~/prod/QUANTT rev-parse HEAD
git worktree list
lsof -nP -iTCP:4002 -sTCP:LISTEN
pmset -g ps; pmset -g | grep -w sleep; pmset -g sched
ls ~/prod/QUANTT/ops/HALT*.md 2>/dev/null; ls ops/HALT*.md 2>/dev/null
cat ~/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/cef_discount/orders.csv
cd ~/prod/QUANTT && python3 -m ops.doctor --quick
```

---

## 1. The finding that outranks every other item here

**Prod is not running `main`, and the branch it runs forked before the entire
2026-09-10 evening order-path repair.** `[V]`

```bash
git merge-base --is-ancestor 7fe3ad8 main || echo "prod is NOT on main"
git merge-base main ops-guards-20260911      # -> ac83a26
git diff --stat 8f5c111 aeebdf7 -- src/deploy/ ops/ scripts/cef/ | tail -3
```

The merge base is `ac83a26` ("Bring dev's live ledgers up to prod's"). Everything
committed to `main` after it — fifteen commits — is absent from prod, including
all six live-path repairs:

| file | lines prod is missing | what it is |
|---|---|---|
| `src/deploy/broker/ibkr.py` | 418 | the real-fill booking path, the globally unique order-map key, the ledger-behind guard — **the file that places orders** |
| `ops/ledger.py` | 424 | books the broker's real executions instead of the sleeve's targets |
| `ops/capture_fills.py` | 113 | the cross-book dedup and the two bare-`except` readers |
| `ops/common.py` | 47 | the atomic panel write |
| `scripts/cef/{fetch_daily,stage_cef,fetch_borrow_rates,fetch_borrow_history}.py` | 28 | the same atomic write, on the panels the sleeve prices from |
| `ops/unbook_unexecuted_fills.py` | 260 | absent entirely |

Plus every test written for them: `test_real_fill_booking.py`,
`test_ledger_behind_guard.py`, `test_order_map_key.py`,
`test_atomic_panel_write.py`, `test_execution_convention.py`,
`test_unbook_unexecuted_fills.py`. **93 files, 4,606 lines.** `[V]`

Two consequences, and neither is theoretical:

1. **Landmine 3 is unchanged in prod, exactly as `CLAUDE.md` says — and the
   commit that says so (`2d4e946`) is itself not in prod.** The shadow ledger
   there still books the sleeve's targets as fills.
2. **The only checkout of the branch prod runs lives in
   `/private/tmp/claude-501/…/ops2`** — a session-scoped scratch directory that
   is deleted without warning. The tag survives in the repo; the working tree
   does not. `[V]`

What is *not* wrong: the frozen spec. `ops/specs/cef_discount.frozen.json`
differs between the two trees by **one documentation key** (`_superseded_by`).
`band_width` is `0.048` in both, `rebalance_days: 2` is INERT in both. **The
policy prod trades is the policy dev believes it trades.** Verify before
trusting this paragraph:

```bash
git diff 8f5c111 aeebdf7 -- ops/specs/cef_discount.frozen.json
```

---

## 2. Why the schedule feels like it breaks daily — the actual tally

Per-session outcome over all 30 CEF logs in **both** trees (`[V]`, and note that
reading one tree undercounts — `CLAUDE.md` has the two-tree command):

| period | sessions | armed | the single blocker |
|---|---|---|---|
| 2026-07-31 | 1 | 0 | first session, no broker yet |
| 2026-08-03 → 08-28 | 20 | 0 | **`[FAIL] broker` — gateway not logged in, 20 consecutive sessions** |
| 2026-08-31 → 09-01 | 2 | 2 | — |
| 2026-09-02 → 09-03 | 2 | 0 | `[FAIL] broker` again |
| 2026-09-04 | 1 | 1 | — |
| 2026-09-07 | 1 | — | NYSE closed (Labor Day), correctly skipped |
| 2026-09-08 | 1 | 1 | armed, then `status=failed`: *"ledger state is inconsistent with its manifest — a previous run almost certainly crashed mid-write"* |
| 2026-09-09 | 1 | 1 | — |
| 2026-09-10 | 1 | 1 | armed **17h20m late**, at 10:38 the following morning |

**6 armed of 30.** But the shape matters more than the ratio: **22 of the 24
failures are one fault** — IB Gateway not logged in — and that fault is fixed.
IBC now holds credentials and manages the gateway (`doctor` reads
`[PASS] ibc`). `[V]`

The last four trading sessions armed 4 for 4. So the honest statement is not "it
breaks every day"; it is **"each of the last three sessions broke in a new and
different way, and none of them was caught by a guard."** That is a worse
problem than a repeated fault, because a repeated fault gets fixed once.

- **09-08** — ledger/manifest inconsistency after a mid-write crash. Armed, then
  the book run died.
- **09-10** — machine slept through the NAV deadline; the session woke at 09:46
  and armed on a decision 17 hours old.
- **09-11 (this morning)** — the promotion went out on a side branch.

---

## 3. The three defects that produced 09-10, none of which is yet closed

**These are lanes B, C and E below. Stated here because they are one incident.**

**(a) There is no clock anywhere that says a decision is too old to act on.**
`scripts/cef/wait_for_nav.py` checks completeness *before* it checks the
deadline, deliberately — its own docstring says so, and for a session that is
merely slow that is the right order. But it means a process that sleeps past
23:30 and wakes at 09:46 to find the data **takes the success path and returns
0** (`wait_for_nav.py:148`, deadline test at `:158`). `[V]` The deadline bounds
the wait, not the session. Nothing downstream re-asks the question.

**(b) The guard added this morning would not have caught the incident it was
written for.** `ops/doctor.py::check_stuck_sessions` compares process age against
`NAV_DEADLINE − StartCalendarInterval + 1h` = **7h15m** for cef. It reaches
production only through `doctor.failures()`, called from `launch_job.py:525` in
the **watchdog** job — which runs **19:30 Mon–Fri, once**. `[V]` On 2026-09-10
the session was 2h15m old at 19:30, well under the ceiling; by the next 19:30 it
had already finished (10:38) and armed late. **The guard detects a hang that is
still hanging at 19:30 and nothing else.** It is a good check wired to the wrong
clock.

**(c) `scripts/cef/fetch_borrow_rates.py` has no overall timeout.** It bounds
individual calls — `urlopen(timeout=60)` `:84`, `ib.connect(timeout=20)` `:130`
`:174`, `reqHistoricalData(timeout=30)` `:141` — and nothing bounds the loop over
17 names × 2 sources. On 09-10 it burned **52 minutes** (09:46 → 10:38) to reach
`FEE_RATE 0/17` and `rc=1`. `[V]` Separately, its primary source now 404s:
`IBKR shortstock file unavailable (HTTPError: HTTP Error 404: Not Found)`.

**And a fourth, which is why nobody knew until a human looked:** alerts reach
nobody. `config/.env` has `ALERT_SMTP_USER` and `ALERT_EMAIL_TO` set and
**`ALERT_SMTP_PASS` unset** `[V]` (checked as a boolean — never print the value,
`CLAUDE.md` hard rule 5). The fallback is `say`, which itself times out:
`[alert] speech: failed (TimeoutExpired(['say', 'Quant session failed.'], 20))`.

---

## 4. Tonight — the four things only a human can do

The scheduler fires **17:15 ET**. `promote.sh` refuses inside 16:30–23:30 on a
trading day, so lane A must land **before 16:30** or wait for tomorrow.

1. **Leave the charger plugged in.** `caffeinate -s` asserts only on AC; losing
   AC drops `PreventSystemSleep` and nothing schedules a wake to recover. This is
   the whole of tonight's sleep protection. `[V]`
2. **Add the SMTP app password** to `config/.env` as `ALERT_SMTP_PASS`. One line,
   and it is the difference between a silent failure and a known one.
3. **Optional, and it removes the AC dependency permanently** — `doctor`'s own
   suggested fix, which needs sudo:
   `sudo pmset -a disablesleep 1 && sudo pmset -b sleep 0 && sudo pmset repeat wakeorpoweron MTWRF 17:00:00`
4. **Decide on lane A before 16:30.** Tonight will trade on prod's current code
   either way; the question is whether it trades the repaired ledger path or the
   one landmine 3 describes.

---

## 5. The lanes

Six lanes. **A is blocking and sequential. B–F are independent of each other and
should run in parallel.** Each is self-contained: paste the lane, not this whole
file, and open `00_BRIEF.md` and `CLAUDE.md` first.

Every lane obeys the same four rules, without exception:

- **Never run anything that can transmit an order.** Propose it; the human runs
  it with `! <command>`. The hook that used to enforce this was removed on
  2026-09-10 — the rule is now honour-only, which makes it more binding, not less.
- **Write the test with the change.** A green suite tells you almost nothing
  about the order path; the cwd defect fixed on 2026-09-10 was found by *writing*
  a test, and the suite passed green throughout.
- **No invented numbers, no silent fallbacks.** Raise, naming what was missing.
- **Re-measure anything this document asserts** before you build on it.

---

### Lane A — Reunify prod onto `main` *(BLOCKING · live path · ops-watchdog + quant-reviewer)*

**Goal:** one line of development reaches production, and the order-path repairs
of 2026-09-10 are the code that trades.

The situation is a fork, not a lag: `7fe3ad8` is not an ancestor of `main`
(`[V]`), the branch it sits on was built in a temporary worktree, and the two
lines contain overlapping fixes written twice with different shas — `main` and
`ops-guards-20260911` both carry "The sleep check read the same sentence out…"
under different commits. Do not assume a fast-forward exists. Do not assume a
merge is clean.

Deliver, in order, stopping at any step that surprises you:

1. **A written reconciliation** before any git operation: for every one of the 15
   commits on `main` after `ac83a26` and every commit on `ops-guards-20260911`,
   say whether its content is present on the other side, absent, or present in a
   different form. `git diff 8f5c111 aeebdf7 -- <path>` per file, not by message.
   Message equality has already misled once here.
2. **Merge `ops-guards-20260911` into `main`**, resolving toward `main` for the
   live-path files (dev has the newer repair) and toward the branch for anything
   it alone fixed. Prove the merge kept both: the six files in §1's table must
   still carry their dev content, and `check_sleep` must still read
   `AppleClamshellCausesSleep`.
3. **Run the full suite**, plus specifically the six test files prod is missing.
4. **Tag from `main`** and promote with `ops/promote.sh <tag>` — **the human runs
   this**, before 16:30, and it must archive live state first. Prod's
   `ops/HALT_phase0_null.md` is untracked and survives a checkout by accident
   rather than design; **verify it is still there afterwards** and record that
   you did.
5. **Delete the scratch worktree** (`git worktree remove`) so there is no third
   tree, and add a `doctor` check that FAILs when `git worktree list` shows any
   tree outside `~/prod/QUANTT` and the dev path. Test it.
6. **Push.** `main` is 12 commits ahead of `origin/main` `[V]`; a tree that only
   exists on one laptop is not a backup.

**Falsifies the lane:** the merge cannot be made clean without discarding a live-
path repair. Then stop, write it up, and promote nothing — trading the older path
knowingly beats trading a half-merged one.

---

### Lane B — A decision-age clock on the order path *(live path · execution-trader + quant-reviewer)*

**Goal:** the session refuses to arm on a decision that is too old to be the
decision the backtest scored, and says so loudly.

This is the fix §3(a) names, and it is the one that would actually have stopped
2026-09-10's late arm. The convention is `shift(2)`: decide at *t*, MOC fill at
*t+1*, earn the *t+2* return (`evaluate()` in `scripts/cef/band_frontier.py`).
An order placed at 10:38 on *t+1* still reaches *t+1*'s auction, so 09-10 cost
nothing — **that was luck, not design.** Ten minutes later on the clock and the
same code arms into a closed auction, or into the wrong one.

Deliver:

1. **A derived ceiling, not a written one.** Express "too old" in terms the
   config already carries — `NAV_DEADLINE`, the plist's
   `StartCalendarInterval`, and the NYSE close — and assert it at runtime with
   the alignment stated in a comment, the way `EXEC_LAG = 2` is. An unparseable
   input must **raise**, never default (`CLAUDE.md`, no silent fallbacks).
2. **Refuse in `arm()`, not in the wrapper.** `arm()` is where the state that
   matters is already assembled, and it already raises `NotArmed` rather than
   transmitting on unverified state. Follow that pattern exactly.
3. **Decide and document what happens on refusal.** Stand down and alert, or
   re-decide on today's data? State the rule under either outcome — no decision
   rule may key on a number in a document (H14). Our view: **stand down.** A
   re-decision at 10:38 has not seen the 16:00 close it is being scored against.
4. **Tests, one per real timeline**: the 09-10 timeline (17:15 start, 09:46 wake,
   10:38 arm) must refuse; a normal 17:15 → 21:46 session must arm; a session
   that crosses midnight but still beats the following auction must have its
   verdict *pinned*, whichever way you choose.

**Do not** put this in `wait_for_nav.py`. Its ordering is deliberate and correct
for its own job; a guard that shares an assumption with the thing it guards is
not a guard.

---

### Lane C — Uptime the machine cannot lose *(no live path · ops-watchdog)*

**Goal:** the evening window survives a lost charger, and something recovers the
box if it sleeps anyway.

Measured now: `caffeinate -s -i -t 54000` from `com.quantt.awake`, started ~09:00,
covering to ~24:00; `PreventSystemSleep 1`; on AC. **`-s` asserts only on AC
power, and there is no `pmset repeat wakeorpoweron` at all** — `pmset -g sched`
lists three Apple alarms and nothing of ours. `[V]`

Deliver:

1. **The recovery wake**, as a scheduled `pmset repeat wakeorpoweron MTWRF` some
   minutes before the session, installed by a script in `ops/schedule/` that is
   idempotent and re-runnable — not a command in a document that someone must
   remember. It needs sudo, so it ends as a one-line proposal for the human.
2. **A `doctor` check that reads the system's verdict, not our intent.** The
   09-11 fix already moved `check_sleep` from lid angle to
   `AppleClamshellCausesSleep`; extend it to assert the repeating wake exists and
   to state plainly that AC is load-bearing while `-s` is the mechanism.
3. **Close the coverage gap the incident named**: `com.quantt.awake` covers
   09:00–24:00 while the session may poll to 23:30 and the backup runs 23:55.
   Re-derive the window from `NAV_DEADLINE` rather than the literal 54000.
4. **Tests** against the recorded 09-10 state: the check must FAIL on it.

---

### Lane D — A failure that reaches a human *(no live path · ops-watchdog)*

**Goal:** nobody discovers a broken session by reading a log the next morning.
This is the lane that changes how the desk *feels*, and it is a day's work.

Deliver:

1. **Email alerting actually working.** `ALERT_SMTP_USER` and `ALERT_EMAIL_TO`
   are set; `ALERT_SMTP_PASS` is not `[V]`. Test the path with the boolean, never
   the value. Make a missing secret a **`doctor` FAIL**, not a WARN — an alerting
   system that is off is worse than none, because it is trusted.
2. **Replace `say` or bound it.** It times out at 20s and its failure is logged
   and swallowed `[V]`.
3. **The check nobody has written: an affirmative one.** Every existing guard
   asks "did something go wrong". None asks **"did the book arm today, and if not
   why"**. A trading day that ends with no `ARMED:` line and no explicit
   stand-down reason is a fault, and right now it is indistinguishable from a
   quiet success. Run it from the watchdog job, after the session window closes,
   not from inside the session.
4. **Fix the watchdog's cadence while you are there.** One 19:30 firing cannot
   see a session that starts at 17:15 and hangs — §3(b). Either add a firing
   after `NAV_DEADLINE`, or make the stuck-session ceiling relative to the
   session's own start rather than the watchdog's.

---

### Lane E — Bound the panel phase *(live path · execution-trader)*

**Goal:** no panel fetch can eat the trading window again.

Deliver:

1. **An overall wall-clock budget** for `fetch_borrow_rates.py`, derived from the
   session window, enforced around the whole loop, and **failing loudly at the
   budget** rather than at `rc=1` 52 minutes later. Per-call timeouts already
   exist and are not the problem.
2. **The 404.** The IBKR shortstock file URL no longer resolves. Find the current
   one from a primary source, add a fetcher and a source note in
   `docs/REFERENCES.md` per the hard rules, and state what the panel does when
   both sources fail — it currently writes no row, which is correct; keep it and
   test it.
3. **Say what a stale borrow panel means for sizing.** Borrow was measured once,
   on 2026-09-06, at 1.22%/yr ≈ 0.23 Sharpe `[S]`, and applied to 21 years. If
   the panel stops updating, name the consequence rather than letting it pass as
   "non-fatal".

Non-goal: making the panel fatal to the session. It is correctly non-fatal.

---

### Lane F — Make "consistent schedule" a number that is tracked *(no live path · dashboard-designer)*

**Goal:** uptime stops being an anecdote. Nobody should have to write the
per-session tally in §2 by hand again — it took a `for` loop over two trees and
it is the most decision-relevant table in this document.

Deliver:

1. **One script** that produces §2's table from both log trees, with the blocker
   attributed per session and NYSE non-trading days excluded, and that names
   itself as the reproducer for any uptime figure quoted anywhere.
2. **A dashboard panel** showing armed-vs-eligible, the current streak, and the
   reason for each recent miss. The dashboard is **read-only** — exactly one
   non-GET route (`/api/connect`), and no code path from it transmits an order.
   Keep it that way.
3. **A definition of done that is a rate, not a fix**: state the target
   explicitly (e.g. 20 consecutive eligible sessions armed) and measure against
   it. Until that number exists, every "we fixed it" is the same claim the last
   three sessions made.

---

### Lane G — Not tonight, and not until A–F are done *(research · quant-reviewer + portfolio-manager)*

**The band has never been walk-forwarded, bootstrapped or deflated.** `band 4.8%`
is what we trade — gross 1.17, net@15bp 0.67, turn 17.6×/yr on the correct
`shift(2)` harness `[S]`, re-run 2026-09-10 — and **nothing in this repo tests
the thing we trade out of sample.** The battery that exists was run on a 5-day
calendar sleeve retired on 2026-09-06, and it FAILs.

This is the largest piece of open work in the project and it is genuinely more
important than any lane above **on a long enough horizon**. It is last here for
one reason: a strategy that arms on 20% of sessions does not have an out-of-sample
problem yet. Fix the delivery, then ask whether the thing being delivered is real.

When it runs: extend `band_frontier.evaluate` visibly — **do not build a new
backtester** — hold turnover within 5%, report the 5/15/30bp cost grid, charge
borrow separately and labelled, and increment the CEF counter in
`docs/RESEARCH_STATE.md` **in the same commit as the trial**. Current counters:
CEF 48, GAMMA 0 — re-read them, do not trust this line.

---

## 6. Sequencing

```
NOW ────────── Lane A ─────────────── promote before 16:30, human runs it
                  │
                  ├── Lane B  decision-age clock       ┐
                  ├── Lane C  sleep + recovery wake    │ parallel,
                  ├── Lane D  alerting + affirmative   │ independent
                  ├── Lane E  panel budget             │
                  └── Lane F  uptime metric            ┘
                                   │
                                   └── 20 consecutive armed sessions
                                              │
                                              └── Lane G
```

A gates the others only because promoting on top of an unmerged fork multiplies
the reconciliation. If A stalls, B–F proceed in dev and promote together.

## 7. What not to do

- **Do not re-litigate the trial counter or the deflated Sharpe.** It is FAIL at
  every N on `shift(2)`; `CLAUDE.md` says the question is moot and it is right.
- **Do not "fix" `launch_job.py` living outside the repo.** macOS TCC denies
  launchd access to `~/Desktop`. Landmine 1.
- **Do not touch `ops/schedule/rendered/*.plist`.** They are stale by design and
  are not what runs.
- **Do not widen `pytest.ini`'s `testpaths`.** `scripts/audit/moc_routing_test.py`
  opens a live broker socket at import.
- **Do not quote a test count, an armed count, or a divergence magnitude from
  this file.** Every one of them has rotted inside 24 hours before. Re-run the
  command; that is why each is printed above the number.
