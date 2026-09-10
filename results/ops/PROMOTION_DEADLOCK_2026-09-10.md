# The promotion deadlock has three layers, not one, and the third is machine state

**Measured 2026-09-10 evening, read-only. No broker connection was opened and
nothing was promoted.** `[V]` verified by re-running the command shown, `[S]`
sourced not re-read, `[U]` uncertain.

## The short version

Prod runs `v2026.09.10.1`. The fix it needs is in `.3`. **Three separate things
block the promotion, and only the first is the one everybody has been talking
about.**

| # | blocker | cleared by | cleared by a promotion? |
|---|---|---|---|
| 1 | prod has 2 dirty phase0 ledger files, and `.1`'s promote.sh has the broken pathspec that refuses on them | `git checkout -- ops/books/phase0_live` | — |
| 2 | the 16:30–22:30 session window | waiting until after 22:30 | — |
| 3 | **`doctor` FAILs on `loaded:benchmarks last exit 3`** | a successful benchmarks run, or a launchd reload | **NO — see below** |

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
