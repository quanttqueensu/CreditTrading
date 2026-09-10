# The promotion deadlock has four layers, not one; the third is machine state and the fourth is an hour of every night

**Measured 2026-09-10 evening, read-only. No broker connection was opened and
nothing was promoted.** `[V]` verified by re-running the command shown, `[S]`
sourced not re-read, `[U]` uncertain.

## The short version

Prod runs `v2026.09.10.1`. The fix it needs is in `.3`. **Four separate things
bear on the promotion, and only the first is the one everybody has been talking
about.**

| # | blocker | cleared by | cleared by a promotion? |
|---|---|---|---|
| 1 | prod has 2 dirty phase0 ledger files, and `.1`'s promote.sh has the broken pathspec that refuses on them | `git checkout -- ops/books/phase0_live` | — |
| 2 | the session window | waiting until the cef session has **exited** — not merely 22:30, see layer 4 | — |
| 3 | ~~`doctor` FAILs on `loaded:benchmarks last exit 3`~~ **CLEARED 17:25** | the 17:25 benchmarks run succeeded on its own; doctor now exits 0 from prod | n/a |
| 4 | `promote.sh`'s window ends **22:30** while the session runs to **23:30** | fixed in `.4`; tonight, check the cef pid | — |

## Layer 3 is the one that matters, and it has already sunk one promotion

**This is not hypothetical.** `~/prod/QUANTT/ops/schedule/logs/promotions.log`:

```
[2026-09-10 11:36:49] promoting v2026.09.10.1 -> v2026.09.10.2
[2026-09-10 11:36:49] smoke test on 2026-09-09 -> …/promote_smoke_v2026.09.10.2.log
[2026-09-10 11:36:50] SMOKE FAILED at step 'doctor' -- rolling back to v2026.09.10.1
```

The smoke log shows **every other check passing** — `repo-path`, all six
plists, broker, IBC, all four heartbeats — with exactly one FAIL:
`loaded:benchmarks  last exit 3`. `ops/doctor.py:81` is `return 1 if fails
else 0`, and `promote.sh` rolls back on any non-zero doctor. So **one FAIL on a
job unrelated to the CEF book rolls back the whole promotion.** `[V]`

Note also what this tells you about layer 1: at 11:36 the gate did **not**
refuse — it printed `promoting …`. The two dirty phase0 files appeared later,
from the 16:08 capture. So layers 1 and 3 arrived in that order and a reader of
`promotions.log` alone would never see layer 1 at all.

## Why a promotion cannot clear layer 3

`promote.sh` checks out the tag **before** it smoke-tests. So by the time
`ops.doctor` runs, prod *is* at `.3`. That does not help, because:

**`doctor` reads `launchctl list`, not the repo.** `ops/doctor.py:158-177`
parses the second column of `launchctl list` — the job's last exit status — and
FAILs on anything that is not `0` or `-`. That is **machine state**. Checking
out a different tag cannot change it. `[V]`


> # ⚠ OUTCOME, 17:25-17:26 — LAYER 3 CLEARED ITSELF, AND THIS NOTE PREDICTED THE OPPOSITE
>
> **The 17:25 benchmarks run SUCCEEDED. `last exit` is now `0`, and
> `python3 -m ops.doctor --quick` run from prod exits `0` with no FAIL at
> all.** `[V]` Heartbeat: `{"status": "ok", "at": "2026-09-10 17:25:11",
> "detail": {"armed": true, "rc": 0, "blockers": []}}`.
>
> **The section below headed "Why tonight's 17:25 benchmarks run is unlikely to
> clear it either" is WRONG, and it is left standing so the reasoning error is
> visible.** What it got right, and I re-measured directly: prod at `.1` really
> does still carry `credit_rv_book.json`, and `_foreign_book_claims()` really
> does still return ANGL as claimed by another book. That part reproduces.
>
> **The wrong step was the inference from there to "therefore `arm()` refuses".**
> A foreign claim on a symbol does not by itself refuse; it only stops `arm()`
> taking that symbol from the **account net**, and the session then needs a
> ledger entry it can attribute. `43ec054` — "bench_b6 ANGL fix", which **is**
> in `.1` — evidently supplied that. So `26a5336` is **structural hardening**
> (stop a dead book voting at all), not the thing that unblocked ANGL. The
> commit message's "would have recurred" is about the class of fault, not about
> tonight.
>
> **Consequences for the promotion, all good:** no launchd reload is needed,
> `--force` is still not needed and still must not be used, and the only
> remaining gate is layer 1 (the two dirty ledger files) plus waiting for the
> **cef** session to exit — which is layer 4, and is the one that actually
> binds tonight.
>
> **The lesson worth keeping:** a mechanism that is present is not a fault that
> fires. I measured the mechanism correctly and predicted the outcome anyway,
> which is the same shape as every confident wrong number this repo keeps
> catching. The `launchctl list | grep benchmarks` instruction below — "confirm
> from the actual outcome rather than this paragraph" — is the only reason this
> was caught in an hour rather than at 22:30.

## Why tonight's 17:25 benchmarks run is unlikely to clear it either

`run_book.py:493` returns **3** for an `arm()` refusal — "a refusal is FATAL on
purpose" (`:457`). So `last exit 3` means benchmarks' arm was refused, which
matches the 2026-09-09 17:25 failure. `[V]`

**The prior brief said that cause "is already fixed in `.1`". It is not.**

| commit | subject | in `.1`? | in `.2`/`.3`? |
|---|---|---|---|
| `43ec054` | Session state: per-book halt scoping, **bench_b6 ANGL fix**, ledger advances | **YES** | yes |
| `26a5336` | **Stop a dead book from blocking a live one** | **NO** | yes |

`26a5336`'s own message says the 09-09 arm refusal "was **structural** and would
have recurred". The structural cause is `_foreign_book_claims()`
(`src/deploy/broker/ibkr.py:743`), a plain scan of `ops/books/*.json` that
treats the killed `credit_rv` spec as a live sibling book and adds its 21
symbols — ANGL among them — to the set `arm()` may not adopt from the account
net.

**Measured directly, replicating that scan read-only against both trees:** `[V]`

```
PROD (.1)  foreign claims vs benchmarks_book:
   {'cef_discount_book.json': 17, 'credit_rv_book.json': 21, 'phase0_book.json': 14}
   ANGL claimed by another book?  True   <- credit_rv_book.json
DEV (main):
   {'cef_discount_book.json': 17, 'phase0_book.json': 14}
   ANGL claimed by another book?  False
```

`ls ~/prod/QUANTT/ops/books/*.json` still lists `credit_rv_book.json`; dev
retired it to `ops/books/retired/`. **So prod carries the structural cause
tonight, and the 17:25 run is expected to exit 3 again.** Confirm from the
actual outcome rather than this paragraph — `launchctl list | grep benchmarks`.

## The circularity, stated plainly

- Benchmarks cannot go green while prod is at `.1` (credit_rv still claims ANGL).
- Prod cannot leave `.1` while benchmarks' last exit is 3 (doctor rolls it back).
- And a promotion cannot fix benchmarks *first*, because the checkout happens
  before the smoke test but `last exit` is machine state.

**Something outside both has to break it.** There are exactly two candidates:

1. **A successful benchmarks run.** Not available on `.1` for the reason above.
2. **A launchd reload** — `bootout` + `bootstrap`. This is what `doctor`'s own
   fix line recommends: *"fix the plist, then bootout + bootstrap it to
   reload"*. A freshly bootstrapped job has not run in that load, so
   `launchctl list` reports `0`/`-` and doctor passes.

Reload is the one that works, and it is on CLAUDE.md's hard-rule list
(`launchctl load|unload`), so a human runs it.

**`RunAtLoad` is `0` on this plist `[V]`** (`plutil -p
~/Library/LaunchAgents/com.quantt.benchmarks.daily.plist | grep RunAtLoad`), so
a reload does **not** fire a session. It resets the counter and nothing else.
Do it **after** 17:25, or that evening's run re-sets the exit code to 3.

**The failure mode to check for afterwards:** doctor reports a *not-loaded* job
as **WARN**, not FAIL (`doctor.py:167`). So a botched reload would leave
benchmarks dead *and let the promotion pass*. Verify the job is present in
`launchctl list` with exit `0` or `-`, not merely that doctor went green.

## A fourth thing, found while waiting for the 17:25 run: the window is an hour short

**`ops/schedule/cef.env:51` sets `NAV_DEADLINE=23:30`. `promote.sh`'s window
ended at `22:30`.** `[V]` Both trees carry the same env file; the `21:30` in
`launch_job.py:243` and `wait_for_nav.py:103` is the **code default**, which the
env file overrides — which is why every document that says "the cef session
waits for NAV until 21:30" is wrong, including CLAUDE.md.

Tonight's session log, read at 17:15:

```
[2026-09-10 17:15:05] waiting for today's NAV on every deployed name (deadline 23:30)
waiting for NAV dated 2026-09-10 on 17 deployed names; deadline 23:30, poll every 900s
```

`cef.env`'s own comment records why: *"Measured 2026-09-08: yfinance publishes
the day's NAVs at ~22:45 ET, in one batch; CEFConnect later still."*

So there was **a full hour every trading night, 22:30 to 23:30, in which the
gate said "not in the session window" while the session was still running and
had not yet placed its orders.** Promoting there checks out a different tag
under a live session — exactly what the window exists to prevent. The two
numbers lived in different files and nothing compared them, so each looked
right on its own.

**Fixed in dev (`v2026.09.10.4`):** the window end is now derived from
`NAV_DEADLINE`, an unparseable one refuses rather than defaulting, and a live
session **pid** refuses outright — with `--force` unable to bypass that one,
asserted by test. A clock is a proxy for "is a session running"; a pid is the
question itself.

**This does not help tonight.** Prod runs `.1`'s `promote.sh`, which still has
the `22:30` literal. **So tonight's promotion must be timed by checking that
the cef job's pid is gone, not by the clock:**

```
launchctl list | grep com.quantt.cef.daily     # first column must be "-"
```

## `--force` is inert against all of this

`--force` is tested in exactly one place — the session-window branch. It does
**not** relax the dirty-tree gate and it does **not** skip the smoke test. So
forcing tonight would buy nothing against the actual blocker (doctor) while
giving up the protection that stops a checkout landing under a running session
holding resting MOC orders. There were four such orders resting at 11:35 today
(JFR, MHD, MQY, NEA, all `PreSubmitted`). **Do not use it.**

## What the discard actually costs, measured

`git checkout -- ops/books/phase0_live` is safe, but not for the reason the
one-line description suggests. `[V]`

- Prod worktree vs **`.3` committed**: identical 677-execId sets, zero
  duplicates, and **only `recorded_utc` differs**, on 512 rows. Every other
  column — `fill_date`, `instrument`, `side`, `qty`, `price`, `source`, `note`
  (which carries commission) — is identical on all 677 rows. `slippage.csv` is
  **byte-identical**.
- Prod worktree vs **`.1` = prod's HEAD, which is what `checkout --` restores**:
  `.1` holds only **165** rows. So the checkout **temporarily drops 512 rows**,
  all dated 2026-09-10 (BKLN, IGSB, SHYG, SJNK, SRLN, VCIT, VCSH).
- **All 512 are present in `.3`**, so the promotion restores every one and the
  end state has the same execId set it started with.

The exposure is the gap between the two commands: if `promote.sh` then refuses
or rolls back, prod sits at `.1` missing those 512 rows until restored.
`backup_state.sh` runs first for exactly this reason, and `.3` has them too.

Gate logic, dry-run read-only against prod's current state: `[V]`

```
corrected pathspecs (.3's):  0 dirty lines
broken pathspecs   (.1's):   2 dirty lines   <- the refusal
after `checkout -- ops/books/phase0_live`:  0 under BOTH
```

That last line is the point: the checkout clears the refusal for the **broken**
pathspec too, which is why `.1`'s own promote.sh can carry `.3` in.

## Other things verified tonight, so nobody re-checks them

- `ops/HALT_phase0_null.md` is **untracked** in prod (`??`), so `git checkout`
  cannot remove it and phase0 stays blocked through the promotion. `[V]`
- It blocks the right book: `phase0_book.json` has `book_id = phase0_null`, and
  `halt.read_halt('phase0_null')` returns BLOCKED while `cef_discount` and
  `benchmarks` return not-blocked. The $500k book is unaffected. `[V]`
- `git fetch --tags origin` from prod exits **0**, and `v2026.09.10.3` is
  pushed to origin. `v2026.09.10.4` is **local only** — `promote.sh` resolves
  local tags so it would still work, but push it before promoting it. `[V]`
- `ops/tests/test_promote_gate.py` passes (4 tests). `[V]`

---

# FINAL, 17:35 — do NOT promote tonight. The cost is three destructive acts, and nothing needs it.

Measured after the 17:25 benchmarks session, which **traded**. `[V]`

## What changed in ten minutes

The benchmarks session wrote **19 more tracked ledger files** plus
`ops/heartbeat.json`. Prod's dirty set under `.1`'s broken pathspecs went from
**2 lines to 22**. The gate refuses on all of them.

## Why the obvious fix is now destructive

`git checkout -- ops/books` no longer costs only timestamps.

| what | cost |
|---|---|
| `phase0_live` broker_fills | safe — identical 677-execId set to `.3`, **only `recorded_utc` differs** |
| `benchmarks_live` bench_b6 broker_fills | **67 broker-confirmed executions destroyed.** `.3` has 141 rows, prod has 208; the 67 are 2026-09-10 SHYG/USHY/VCIT. **`.3` does not contain them and cannot restore them.** |
| `ops/books/benchmarks_live/report_2026-09-10.md` | **untracked**, so a checkout cannot clear it — and `.1`'s pathspecs do not exclude it |

That last row is the one that settles it. **After discarding every tracked
ledger, `.1`'s gate STILL refuses**, because one untracked file remains:

```
under .1's pathspecs, dirty now:                        22
after `git checkout -- ops/books ops/heartbeat.json`:    1   <- the untracked report
under .3's CORRECTED pathspecs:                          0
```

So promoting `.3` *through `.1`'s promote.sh* costs **three** destructive acts —
discard 67 real executions, discard the phase0 timestamps, and move or delete
tonight's benchmarks report — to deliver a fix whose entire purpose is to stop
the gate refusing on live state. That trade is not worth making, and the
executions are the paper track record, which is the one thing this desk cannot
re-create.

## Nothing needs it tonight

- The 17:25 benchmarks session **armed and traded**, rc 0.
- `ops.doctor --quick` from prod exits **0**, no FAIL.
- `ops/HALT_phase0_null.md` is in place and blocks phase0; `cef_discount` and
  `benchmarks` are not blocked.
- The CEF session is running normally, waiting for NAV to 23:30.

`.3` fixes *future* promotions. It changes nothing about tomorrow's trading.

## Do it on Saturday 2026-09-12, and carry the untracking with it

`2026-09-12` is **non-trading** `[V]` (`nyse_calendar.py --check`), so:
no session fires, the state does not move under the operation, `promote.sh`'s
window check does not apply at all, and the restore can be verified at leisure.

**And it should carry the ledger untracking (`NEXT_2026-09-11.md` §4), because
the preserve/restore dance is needed exactly once either way.** Doing it on the
untracking tag means it is never needed again. Prerequisite, currently unmet:
`com.quantt.backup.daily` **last exit 1** — see below.

## Two things found while establishing the above

**1. The nightly state backup is failing, invisibly.** `com.quantt.backup.daily`
(23:55) reports `last exit 1`, and its log holds one line: `backup FAILED
rc=1`. **`doctor` never checks it** — `JOBS = ["cef", "benchmarks", "phase0",
"collect", "watchdog", "weekly"]` (`ops/doctor.py:48`) does not include
`backup`. So the job that is meant to replace git history as the ledgers'
off-machine copy, and which the untracking is explicitly gated on, has been
failing with nothing to say so.

Run **interactively** it exits **0** and writes a complete archive
(`state_20260910_1729.tgz`, 175,744 bytes, 225 entries, containing tonight's
benchmarks fills — 209 lines, matching prod exactly — and `ops/heartbeat.json`).
So it is the launchd TCC boundary, not the script logic: under launchd it runs
as `/bin/bash` with no Full Disk Access and `data/` in prod is a symlink into
`~/Desktop`. `.1`'s copy collapses every failure to `exit 1`; `.3` rewrites the
script (+68/−12) to distinguish "archive written but incomplete" (exit 2, which
`promote.sh` tolerates) from "no archive" (exit 1, which refuses). **Another
thing `.3` fixes that cannot be delivered until `.3` lands.**

**2. `backup_state.sh` does not archive the halt file, though its own docstring
says it does.** Its header lists "the shadow ledgers, the heartbeat, **the halt
file**, the order maps...". `tar -tzf … | grep HALT` returns **nothing**. Not
urgent — the halt files are untracked, so no checkout can remove them — but the
docstring is wrong and someone will rely on it during a recovery.

## The sequence for Saturday, if promoting `.3` alone

Ordered so that nothing is discarded before it is archived, and so the restore
names an unambiguous file. **`promote.sh` runs `backup_state.sh` itself, after
our checkout — so its archive would contain the already-discarded state. Pin
the good archive to a fixed name first; do not `ls -t` for it afterwards.**

```bash
~/prod/QUANTT/ops/backup_state.sh
cp "$(ls -t ~/prod-backups/*.tgz | head -1)" ~/prod-backups/PRE_PROMOTE.tgz
mv ~/prod/QUANTT/ops/books/benchmarks_live/report_2026-09-10.md ~/prod-backups/
git -C ~/prod/QUANTT checkout -- ops/books ops/heartbeat.json
~/prod/QUANTT/ops/promote.sh v2026.09.10.3
tar -xzf ~/prod-backups/PRE_PROMOTE.tgz -C ~/prod/QUANTT \
    ops/books/cef_live ops/books/benchmarks_live ops/books/phase0_live ops/heartbeat.json
mv ~/prod-backups/report_2026-09-10.md ~/prod/QUANTT/ops/books/benchmarks_live/
```

**Never `tar -xzf … -C $PROD ops/books` wholesale.** The archive contains
`ops/books/credit_rv_book.json` and the other book JSONs, and
`_foreign_book_claims` globs that directory **from disk** — restoring it would
silently resurrect the retired book that this promotion is retiring.
