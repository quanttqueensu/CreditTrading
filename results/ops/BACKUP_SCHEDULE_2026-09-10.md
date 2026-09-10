# Scheduling the state backup — 2026-09-10

**Status: PREPARED, NOT INSTALLED.** The plist is rendered and linted; no
`launchctl` was run. The one command the human runs is in §5.

Written because `ops/backup_state.sh` existed but **nothing scheduled it**. That
was tolerable while the live ledgers were tracked in git. It stops being
tolerable the moment the planned `git rm -r --cached ops/books/*_live` lands,
because git history is currently the only off-machine copy of those ledgers.
Between promotions there is otherwise **no copy at all** — `ops/promote.sh`
archives live state, but only when someone promotes.

Provenance labels: `[V]` verified by running or reading it here today, `[S]`
sourced from a file I read but did not independently re-derive.

---

## 1. What `ops/backup_state.sh` actually does (verified)

Read in full at `ops/backup_state.sh` (29 lines). The dev and prod copies are
**byte-identical** — `diff` returned no output. [V]

| property | value | evidence |
|---|---|---|
| tree archived | derived from the script's **own location**, `$(dirname $0)/..` | `ops/backup_state.sh:14` |
| destination | `${BACKUP_DIR:-$HOME/prod-backups}`, created if absent | `ops/backup_state.sh:15` |
| archive name | `state_<YYYYmmdd_HHMM>.tgz` — **minute** resolution | `ops/backup_state.sh:16-17` |
| contents | `ops/books`, `ops/heartbeat.json`, plus `ops/HALT.md`, `data/cef/nav_fallback_log.csv`, `data/cef/cef_borrow.csv` **only if each exists** | `ops/backup_state.sh:18-23` |
| failure | `exit 1` if `tar` rc≠0 **or** the archive is empty | `ops/backup_state.sh:25-27` |
| retention | `tail -n +91` → keeps the newest **90** | `ops/backup_state.sh:28` |
| shell flags | `set -uo pipefail` — note **no `-e`**; rc is checked explicitly instead | `ops/backup_state.sh:13` |

Deliberately excluded: price/NAV parquets. The rationale is in the header — 
yfinance serves those again; what it cannot serve is the ledgers.
`ops/backup_state.sh:11-12` [S]

### Is it safe to run? Is it read-only with respect to `ops/books/**`?

**Yes.** The only verbs in the script are `tar -czf` (reads the tree, writes the
archive), `mkdir -p "$DEST"`, and `rm -f` restricted to `"$DEST"/state_*.tgz`.
Nothing writes inside the repo. On that basis I ran it once.

### The verification run

Ran the **prod** copy at 11:36 today:

```
[2026-09-10 11:36:19] wrote /Users/simonjarvis/prod-backups/state_20260910_1136.tgz (164K); 2 kept
rc=0
```

- **164 KB claim: confirmed.** [V] 167,028 bytes on disk; the pre-existing
  10:29 archive is 167,866 bytes.
- **90-archives claim: confirmed by reading `:28`,** not by observation — there
  are only 2 archives, so pruning has never yet fired. [V for the code, not for
  the behaviour at the limit.]
- Archive contains 222 `ops/books/**` entries, `ops/heartbeat.json`, and
  `data/cef/cef_borrow.csv`, including the live
  `ops/books/cef_live/_ibkr_shadow/cef_discount/{broker_fills,positions,nav}.csv`. [V]

**Safe to run twice?** Effectively yes, with one wrinkle: the stamp is
minute-resolution (`:16`), so two runs inside the same minute write the *same*
filename and the second silently overwrites the first. Harmless here — both
would be snapshots of the same state — but it means you cannot use the archive
count to count runs.

### Two caveats worth recording

1. **Optional inputs are silently omitted.** The `[ -f ... ] && echo` guards at
   `:20-22` mean a missing file is dropped and the script still reports success.
   Today `data/cef/nav_fallback_log.csv` and `ops/HALT.md` **do not exist** [V],
   which is why neither is in the archive. If `nav_fallback_log.csv` is ever
   created and later moved or renamed, the backup will quietly stop capturing it
   and still print `wrote ... ; N kept`. The archive's *contents* should be
   spot-checked occasionally, not just its existence.
2. `tar`'s stderr is sent to `/dev/null` (`:23`), so a partially-readable tree
   produces a warning nobody sees. The rc check still catches a hard failure.

I also tested the `xargs -r` in the retention line (`:28`), because `-r` is a
GNU extension that BSD `xargs` historically lacked and its absence would have
meant retention never pruned. **It is honoured on this machine** — empty input
produced no invocation, rc=0. [V] No bug.

---

## 2. The scheduling-mechanism contradiction, and its resolution

The repo genuinely contradicts itself here, so this is stated plainly.

**The two claims.** `CLAUDE.md` landmine #2 says `ops/schedule/rendered/*.plist`
are stale, point at the old repo path, and are **not** what runs — launchd runs
`~/Library/Application Support/quantt/launch_job.py` directly. But
`ops/schedule/install.sh` exists, renders plists, and offers `--enable` to
`launchctl bootstrap` them (`ops/schedule/install.sh:8, 77-78`), which reads
like the supported path.

**Resolution: `CLAUDE.md` is right. `install.sh` is dead and is a hazard.**

Evidence:

1. **The installed, live plists dispatch through the outside-the-repo entry
   point.** `~/Library/LaunchAgents/com.quantt.cef.daily.plist` and
   `com.quantt.benchmarks.daily.plist` both have `ProgramArguments` =
   `/opt/anaconda3/bin/python3` → `.../Application Support/quantt/launch_job.py`
   → a book name (`cef`, `benchmarks`). [V] Neither references
   `ops/schedule/` at all.
2. **`install.sh` can only render two jobs, and they are not in the live set.**
   It renders exactly `com.quantt.book.daily` and `com.quantt.book.weekly`
   (`install.sh:35-36, 61-62`). The installed set is `com.quantt.{cef, phase0,
   benchmarks, collect, watchdog, weekly}.daily` plus `awake`, `dashboard`,
   `ibgateway`. [V — directory listing of `~/Library/LaunchAgents`.] The two
   `com.quantt.book.*` plists sitting there are dated **Jul 24**, predating
   everything else.
3. **Everything under `rendered/` hardcodes a path that no longer exists.**
   All four rendered plists reference `/Users/simonjarvis/Desktop/QUANTT/2027`;
   `ls` on that path returns **No such file or directory**. [V] The real tree is
   `/Users/simonjarvis/Desktop/2027/QUANTT/2027`.
4. `ops/schedule/README.md` already carries a banner saying the same
   (`README.md:9-13`). [S]

**The hazard, which is worth more than the job I was asked to add.**
`install.sh --enable` is not merely useless — it is dangerous. It recomputes
`REPO` from its own location, so it would render a plist pointing at the
*current dev tree* and bootstrap `com.quantt.book.daily`, which executes
`run_after_close.sh`. Per `ops/schedule/README.md:19`, **the `run_*.sh` wrappers
arm and trade, and they skip preflight, the halt check and the same-day
guard.** So the one command in that directory that looks like "the supported way
to install a scheduled job" would install a trading job, pointed at the
non-production tree, outside every safety gate. It should be deleted or
neutered; that is `docs/prompts/W0_repo_hygiene.md`'s to own, and I did not
touch it because it is outside the paths I was given.

**Consequence for this task:** extending `install.sh` would have filed a live
artifact in a dead directory next to plists that lie about what runs. The backup
job therefore ships as its own installer, `ops/schedule/install_backup.sh`,
rendering into `rendered_backup/` rather than `rendered/`.

---

## 3. Which tree gets backed up: PROD. Why.

**Target: `~/prod/QUANTT`.** Getting this wrong is the failure mode the task
called out — a backup of the wrong tree looks exactly like success.

The script derives its tree from its own location (`:14`), so the plist pointing
at `~/prod/QUANTT/ops/backup_state.sh` is *the entire mechanism* by which prod
gets archived. That is the only knob.

Why prod:

- `~/prod/QUANTT/.git` is a **gitfile**, not a directory:
  `gitdir: /Users/simonjarvis/Desktop/2027/QUANTT/2027/.git/worktrees/QUANTT` — 
  it is the detached worktree described in `CLAUDE.md`. [V]
- `~/prod/QUANTT/ops/books/` is a **real directory** (not a symlink) holding
  `cef_live/`, `benchmarks_live/`, populated at 10:31 today — the promotion. [V]
- The live **dashboard** job runs `/Users/simonjarvis/prod/QUANTT/dashboard/server.py`. [V]
- Sessions write their ledgers into the tree the scheduler runs, which is prod.

One subtlety that makes prod the *complete* target rather than a partial one:
`~/prod/QUANTT/data` is a **symlink** to the dev tree's `data/`. [V] So archiving
prod picks up prod's own `ops/books` **and** resolves `data/cef/cef_borrow.csv`
through the symlink to the dev copy that currently owns the panels. Backing up
prod therefore captures both halves of the deliberate, temporary split. Backing
up dev would capture the borrow panel but the **wrong** `ops/books`.

**Note for whoever reads this later:** at the time of writing the two trees'
ledgers are still identical, because the split happened today at 10:31 and no
session has run since (next cef fire is 17:15). `broker_fills.csv` is 295 lines
in both. [V] **They diverge from tonight onward** — do not let today's
equality talk you into pointing this at dev. When `ops/sync_dev_data.sh`
eventually moves `data/` ownership to prod, this job needs no change.

---

## 4. Timing: 23:55 local, every day

The archive must contain the day's fills, so it has to fire after the evening
capture. The constraint is tighter than it looks and 23:55 is close to forced.

| input | value | evidence |
|---|---|---|
| cef session fires | 17:15, Mon–Fri | `com.quantt.cef.daily.plist` `StartCalendarInterval` [V] |
| cef waits for same-day NAV until | `NAV_DEADLINE=23:30` | `ops/schedule/cef.env:51` [V] |
| NAV poll interval | 900s | `ops/schedule/cef.env:52` [V] |
| benchmarks fires | 17:25, Mon–Fri | `com.quantt.benchmarks.daily.plist` [V] |
| observed cef finish 2026-09-09 | **21:46** | mtime of `ops/schedule/logs/cef_2026-09-09.log` [V] |
| observed cef finish 2026-09-08 | **22:54** | mtime of `ops/schedule/logs/cef_2026-09-08.log` [V] |

Worst realistic finish is the 23:30 NAV deadline plus the capture phase, i.e.
around 23:40. That sets a **floor** of ~23:45.

There is also a **ceiling**, which is the non-obvious part. `com.quantt.awake`
runs `caffeinate -s -t 54000` — 15 hours — starting 09:00 on weekdays, so the
machine is held awake until exactly **00:00**. [V] A backup timed after midnight
would sit outside that window, and `caffeinate` *prevents* idle sleep but
**cannot wake a sleeping Mac** (its own comment says so, and says `pmset repeat`
is the real fix).

So the window is roughly 23:45–00:00, and **23:55** sits in it with margin on
both sides. It also keeps the archive's datestamp on the trading date it
describes.

Residual risks, stated rather than hidden:

- **Weekends are not covered by `caffeinate`.** The awake job fires Mon–Fri only,
  so a Saturday or Sunday 23:55 run will be missed if the Mac has slept. [V]
  This is benign: every archive is a **full** snapshot, not an incremental, so
  Monday's archive loses nothing. The job runs all seven days anyway because
  state can change by hand on a weekend and an archive costs 164 KB.
- **A session that overran past 23:55** would give one torn archive out of 90.
  Acceptable; missing the day's fills entirely would not be.
- **`com.quantt.awake.plist`'s comment is stale** — it says the NAV "deadline
  21:30" while `cef.env:51` says 23:30. [V] The *code* (`-t 54000`) is
  unaffected, so this does not change the analysis, but the comment should be
  corrected by whoever owns that file. It is outside the repo and outside my
  paths, so I left it.

---

## 5. What was prepared, and the command to install it

Three files under `ops/schedule/`:

| file | role |
|---|---|
| `com.quantt.backup.daily.plist.template` | the job. `__PROD__`/`__SUPPORT__`/`__HOUR__`/`__MINUTE__` placeholders; header documents why it bypasses the session entry point |
| `install_backup.sh` | renders → `plutil -lint` → *optionally* stages/enables. Default mode installs nothing |
| `rendered_backup/com.quantt.backup.daily.plist` | the rendered result (gitignored via `.gitignore:54`) |

Rendered and **`plutil -lint`: OK** [V]. Resolved values:

- `ProgramArguments` = `/bin/bash /Users/simonjarvis/prod/QUANTT/ops/backup_state.sh`
- `StartCalendarInterval` = Hour 23, Minute 55, **no `Weekday`** → all seven days
- `RunAtLoad` = **false** — installing it does not fire it
- logs → `~/Library/Application Support/quantt/launchd_backup.log`
- `PATH` pinned to `/usr/bin:/bin:/usr/sbin:/sbin`

`install_backup.sh` **refuses to render** if `$PROD/ops/backup_state.sh` is
missing or non-executable, rather than emitting a plist that would tar nothing
every night — that silent-success case is precisely what this backup insures
against.

### ▶ THE COMMAND THE HUMAN RUNS

```bash
! /Users/simonjarvis/Desktop/2027/QUANTT/2027/ops/schedule/install_backup.sh --enable
```

That stages the plist into `~/Library/LaunchAgents` and `launchctl bootstrap`s
it. **I did not and cannot run it** — `.claude/hooks/guard_order_path.py` blocks
an agent from `launchctl` in any form, and rightly: a stopped or wrongly-started
agent is a silently non-trading book, which has already cost this project a
month.

Verify afterwards, without waiting for 23:55:

```bash
launchctl print gui/$(id -u)/com.quantt.backup.daily | head -20
launchctl kickstart -p gui/$(id -u)/com.quantt.backup.daily
ls -lt ~/prod-backups/state_*.tgz | head -3
tar -tzf "$(ls -1t ~/prod-backups/state_*.tgz | head -1)" | grep cef_live | head
```

The last line is the one that matters: it proves the archive contains the live
ledgers and not an empty tree.

To back out: `install_backup.sh --disable` (bootout + remove).

**This is the gate on `git rm -r --cached ops/books/*_live`.** Do not run that
removal until the command above has been run and at least one archive has
appeared *from the scheduled job* rather than by hand.

---

## 6. What I could not verify

- **`launch_job.py` itself.** `guard_order_path.py` blocked reading it — my
  `cat` of it was refused because the command named the file. I did not reroute
  around the hook. Its role as the live dispatcher is nonetheless established
  independently, from the `ProgramArguments` of the installed plists (§2.1).
  If someone wants the `REPO` constant confirmed by eye:
  `! grep -n '^REPO' ~/Library/Application\ Support/quantt/launch_job.py`
- **`ops/promote.sh`.** Same hook, same decision — I wanted to confirm its prod
  path but did not need it; the dashboard plist and the worktree gitfile settle
  the question.
- **Retention at the 90-archive limit**, as noted in §1 — read, not observed.
