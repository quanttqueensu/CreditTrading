# W0b — Deploy the prod/dev split (designed, written, never deployed)

> ## ✅ EXECUTED 2026-09-10 — the split is deployed. Do not run it again.
>
> Marked executed in `c6fc9b1`. **Verify against the machine, not this file:**
>
> ```bash
> git worktree list                        # 2 trees: dev, and prod detached
> git -C ~/prod/QUANTT describe --tags     # the tag prod actually runs
> ```
>
> `~/prod/QUANTT` is now a git worktree detached at a tag; the scheduler, the
> dashboard and every live ledger run there. Editing the dev tree reaches no
> session until someone tags it and runs `ops/promote.sh <tag>`.
>
> **The human-at-the-keyboard warning below still applies to any RE-run or
> rollback.** Two things this prompt describes as future are still open: prod
> does not yet own its own `data/` (it is a symlink back into the dev tree, so a
> research script can still corrupt what the sleeve prices from — the reversal
> is `ops/sync_dev_data.sh`), and the live ledgers are still tracked in git
> (`git ls-files ops/books/cef_live` is non-empty).

**Reads first:** `CLAUDE.md` §4 (safety), `00_BRIEF.md` §6.
**Lever:** the single largest operational risk in the repo. **Trials:** 0.
**Touches the live book:** **yes, profoundly** — it changes which tree the
scheduler executes.
**Run second, after W0.**
**⚠ THIS PROMPT REQUIRES A HUMAN AT THE KEYBOARD.** It repoints live trading
infrastructure. Do not execute the final two steps autonomously, do not run any
of it inside the session window, and do not run it on a day the book must trade.
**New 2026-09-10.**

---

> ## ✅ EXECUTED 2026-09-10 11:00 ET. Do not run this prompt again.
>
> `~/prod/QUANTT` is a worktree detached at **v2026.09.10.1**;
> `launch_job.py:REPO` and the dashboard plist both point at it. Verified before
> the switch: 126 tests, preflight arms against the live gateway, a dry-run
> session builds all 17 targets, dashboard imports and resolves prod.
>
> Three things had to be fixed to make it work, all committed: the `.env` files
> pinned absolute `~/Desktop` paths for `BOOK`/`BOOKS_ROOT` (the launchd entry
> point ignores them but `run_*.sh` does not — a manual run would have advanced
> a *different* ledger than the scheduler); phase0 had no `IBKR_CLIENT_ID` and
> fell back to the shared config; and the promotion gate's clean-tree check was
> tripped by the book having traded, so it could never have promoted twice.
>
> **Two deliberate compromises remain and are the next session's work, not
> re-litigation of this design** — see `NEXT_2026-09-11.md` items 4 and 5:
> prod's `data/` is still a symlink back to dev, and the live ledgers are still
> tracked by git. What follows is kept as the record of why and how.

## Paste from here

You are working in the QUANTT repo. **Establish the current state before
changing anything** — the following was verified on 2026-09-10 and is the reason
this prompt exists:

```
~/prod/                                    DOES NOT EXIST
launch_job.py:54  REPO = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027")
```

**The scheduler runs the same working tree that research edits.** Every script
you run, every parquet a research job rewrites, every half-finished edit sits in
the tree the 08:30 session will execute. `ops/promote.sh` and
`ops/sync_dev_data.sh` were written on 2026-09-08 to close exactly this, and
were never deployed.

Read both scripts in full before doing anything. They are good, and the design
below is theirs, not yours to redesign. From `promote.sh`'s own header:

> *"Until today the scheduler ran the same working tree every edit and every
> research script ran in. On go-live day fetch_daily.py and launch_job.py were
> changed four hours before the 17:15 session. Tested, but nothing STOPPED an
> untested edit reaching the sleeve, and any script could write into the
> parquets the sleeve prices from."*

That sentence describes the situation **as it still is today.**

---

## Part A — What the split is

| | **PROD** | **DEV** |
|---|---|---|
| path | `~/prod/QUANTT/` | `~/Desktop/2027/QUANTT/2027` (this tree) |
| contents | a **detached checkout of a tag**, nothing else | the working tree, branches, edits |
| who writes code here | **nobody** — only `promote.sh` | you |
| runs the scheduled session | **yes** | no |
| `data/` | the authority; written only by the session's own fetchers | a **read-only mirror**, refreshed by `sync_dev_data.sh` |
| results, notes | none | all research output |

The two invariants that make it work, and both are already enforced by the
scripts:

1. **Code reaches prod only as a tag, only through `promote.sh`, only outside
   the session window, and only if the tag passes the smoke test.** Prod's tree
   being clean is checked; a dirty prod tree means someone edited in prod, which
   is the one thing the split forbids.
2. **Data flows one way, prod → dev, via `rsync --delete`.** Anything a research
   script writes into dev's `data/` is **removed on the next sync, by design.**
   Research output belongs in `results/`. This is what stops a research job
   corrupting the panel the sleeve prices from.

---

## Part B — Deploy it

**Do steps 1–5 yourself. Steps 6 and 7 need a human.**

1. **Pick a window.** Not 16:30–22:30 local on a trading day (`promote.sh`
   enforces this), and ideally a weekend or a market holiday. Confirm against
   `ops/schedule/nyse_calendar.py`.
2. **Commit and tag.** The working tree currently has uncommitted work
   (the prompt set, `docs/REFERENCES.md`, `CLAUDE.md`, and whatever W0 changed).
   **Commit it, push, and tag** — `promote.sh` requires the tag to exist on
   origin. Use the `vYYYY.MM.DD` convention its usage line shows.
3. **Create the prod checkout:**
   ```
   mkdir -p ~/prod && git clone <origin> ~/prod/QUANTT
   ```
   Do **not** copy the dev tree. A clone from origin is the point: it contains
   exactly what is committed and nothing that is not.
4. **Seed prod's data.** Prod needs `data/` before it can run, and `data/` is
   gitignored (~3.9GB, not in the clone). Copy it once from dev —
   `rsync -a ~/Desktop/2027/QUANTT/2027/data/ ~/prod/QUANTT/data/` — and note
   that this is the **only** time data flows dev → prod. Thereafter it is
   prod → dev, one way, forever.
5. **Seed prod's config and ledgers.** `config/.env` is gitignored and prod
   cannot connect to IBKR without it. `ops/books/` holds live ledger state that
   is partly untracked. Copy both, then **verify prod's `config/.env` has the
   same client IDs and that nothing now runs twice** — see Part C.
6. **⚠ HUMAN STEP: repoint the scheduler.** Edit `REPO` in
   `~/Library/Application Support/quantt/launch_job.py` from the dev path to
   `~/prod/QUANTT`. Check whether `BOOK` and `BOOKS_ROOT` in that file also
   carry the old path — the file's own docstring at lines 67–82 records a
   previous incident where `REPO` was updated and something else was not, and
   the job "died the same way and so could not report the stall either."
7. **⚠ HUMAN STEP: run the first promote from prod.**
   `~/prod/QUANTT/ops/promote.sh <tag>` — it will refuse inside the session
   window, check prod's tree is clean, detach-checkout the tag, and run its
   smoke test (`ops.doctor`, `wait_for_nav --once`,
   `fetch_daily --require-asof <last>`, `run_book --dry-run`, a dashboard
   import). **If any step fails it rolls back to the previous tag and exits
   non-zero.** Read its output; do not force past a failure.

---

## Part C — Verify, and the things most likely to go wrong

Work through every one of these before the next session:

- **Nothing runs twice.** Both trees now exist on one machine. Confirm the
  launchd agents point only at prod, that dev has no plists installed, and that
  **no IBKR client ID is used by both trees simultaneously** — two processes on
  one client ID is a connection failure at best. Enumerate every ID in
  `ops/schedule/*.env`, `config/.env`, the dashboard and any tool.
- **The dashboard.** `promote.sh` restarts it so it serves the new tag. Decide
  deliberately whether the dashboard reads **prod** (it should — it is a monitor
  of what actually traded) and confirm its plist points there.
- **`ops/doctor.py` passes in prod**, including its `REPO` path check.
- **Run the session once in `DRY_RUN=1` from prod** and confirm it produces the
  same targets dev does on the same pair, byte for byte. If they differ, prod is
  missing something — most likely `config/costs.yaml`, a `.env` key, or ledger
  state.
- **Dev must not be able to trade.** After the split, dev's `.env` should point
  at a simulator or have no gateway credentials at all. A research script that
  accidentally arms is the failure mode this whole exercise exists to prevent.
- **First real session: watch it.** Do not deploy and go to bed.

---

## Part D — What changes in daily work afterwards

- **Research happens in dev, always.** Never edit prod. If prod's tree is dirty,
  something is wrong and `promote.sh` will refuse to run.
- **Shipping a change means: commit in dev → push → tag → run `promote.sh` from
  prod, outside the session window.** There is no other path.
- **`sync_dev_data.sh` runs after the session**, so dev research always reads
  what the sleeve actually traded on. Consider scheduling it; if you do, it must
  run *after* capture, never during.
- **Every prompt in this queue that touches the sleeve, the executor or the
  schedule now has a deployment step**, and "it works in dev" is no longer the
  same claim as "it is live". Say which you mean in every note.

## Deliverables

- `~/prod/QUANTT` existing, on a tag, passing `promote.sh`'s smoke test.
- `launch_job.py` repointed, with every path in it checked, not just `REPO`.
- A client-ID table proving no collision between the two trees.
- `docs/INFRASTRUCTURE.md` updated with the split: which tree runs what, the
  promote path, the data direction, and the rule that prod is never edited.
- `results/ops/PROD_SPLIT_<date>.md`: what was done, the verification evidence,
  and the first session's outcome.

## Do not

- Do not run any of this inside 16:30–22:30 local on a trading day.
- Do not deploy on a day the book must trade, and do not deploy unattended.
- Do not copy the dev working tree into prod. Clone from origin.
- Do not let data flow dev → prod after the initial seed.
- Do not edit code in prod, ever, for any reason. That is the whole point.
- Do not skip the smoke test or force past its failure.
