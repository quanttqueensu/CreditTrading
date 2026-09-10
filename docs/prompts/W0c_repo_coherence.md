# W0c — Repo coherence: make the repo agree with itself, and with the machine

**Status:** in progress — done: 5 of 6 §8 items (`cb6f3a7`, `0b828dc`). remains: the push — `main` is ahead of `origin/main`.
**Reads first:** `00_BRIEF.md` (all of it), `CLAUDE.md`, and rule **H14** — no
decision rule may key on a number written in a document. W0 enforced H14 on a
handful of files. This prompt enforces it on the repo as a whole, and on
`CLAUDE.md` itself.
**Lever:** no alpha, no trials. It buys agent-hours and removes a class of
incident where a confident document sends a session down the wrong path. Three
of its items are live defects, one of which currently blocks every promotion.
**Trials:** 0. Nothing here evaluates a specification.
**Touches the live book:** one gate fix in `ops/promote.sh` (item 2). Everything
else is documentation, archival and layout.
**Run first.** It is cheap, and the promotion gate is wedged until item 2 lands.
**New 2026-09-10.**

---

## 0. Why this prompt exists

On 2026-09-10 the team lead read `CLAUDE.md`, the handoff, and the work order,
and then asked:

> *"what is prod / dev? i dont see it on the git and our branch right now is
> called cleanup/whateverrr"*

That is the finding. Three documents describe the prod/dev split at length —
`CLAUDE.md`, `docs/INFRASTRUCTURE.md` §6.0, `W0b_prod_dev_split.md` — and the
person who authorised it still could not locate it in git.

**Corrected 2026-09-10, and the correction is the sharper point.** The first
draft of this paragraph said none of them says the words `git worktree`. That was
wrong — `CLAUDE.md:179` and `INFRASTRUCTURE.md:423` both say it verbatim, and a
second agent caught the overstatement within the hour. The true gap is narrower
and more useful: **the term is named, but no document anywhere in the repo gives
the command that shows it.** `git worktree list` appears in exactly two files,
this one and a `results/` note — neither of which a new reader opens. Naming a
concept is not orienting someone; the one-line command is. That the first draft
of a prompt about stale claims contained a confident wrong claim is the whole
problem restated, and it is left visible here on purpose.

The repo is not disorganised in the usual sense. It is *over*-documented and
*under*-reconciled: many files, each locally careful, collectively disagreeing.
An agent that reads three of them gets three different pictures and no way to
tell which is current. Every item below is a measured instance of that, not a
style preference.

**The standing rule for this prompt: a document may only state a fact it also
tells the reader how to re-measure.** Where you cannot give a command, give a
date and a method. Where you can, give the command and delete the number.

---

## 1. Verify the inheritance (10 min, blocking)

Run these and paste the output into your first reply. Every number in this
prompt was measured 2026-09-10 ~13:00 ET; if any disagrees, something moved and
you should say so before acting.

```bash
cd ~/Desktop/2027/QUANTT/2027
git worktree list                      # expect 2: this tree, and prod detached
git branch -a && git remote -v
git rev-list --count main..HEAD        # expect 40
git rev-list --left-right --count origin/cleanup/2026-09-10-prompts-and-hygiene...HEAD
python3 -m pytest -q | tail -2         # expect 211 passed
find . ~/prod/QUANTT -maxdepth 2 -name 'HALT*.md' 2>/dev/null   # expect 1, in prod
```

(`find`, not `ls ops/HALT*.md` — under zsh an unmatched glob aborts the whole
line before `ls` runs, so the one-halt case looks like an error.)

**Measured state at hand-off:**

```
dev        ~/Desktop/2027/QUANTT/2027   branch cleanup/2026-09-10-prompts-and-hygiene
prod       ~/prod/QUANTT                WORKTREE, detached at v2026.09.10.1 (2a7c486)
remote     origin  github.com/quanttqueensu/CreditTrading.git
main       9636502 ("add")  — 40 commits behind dev, 0 ahead
tags       v2026.09.10, .1, .2  — all three ARE on origin
unpushed   28 commits ahead of origin (everything after v2026.09.10.2)
tests      211 passed (was 271; commit 7ad3a82 removed the guard and "its 60 tests")
halt       ~/prod/QUANTT/ops/HALT_phase0_null.md  ACTIVE since 2026-09-10 12:56
```

---

## 2. The promotion gate is wedged — fix this first (live defect)

**`ops/promote.sh`'s clean-tree gate currently refuses every promotion.** The
pathspec exclusion does not match anything:

```bash
# ':!ops/books/*_live' matches NO tracked path -- `*` does not cross `/`,
# and no tracked path is literally named `…_live`. The live ledgers are
# therefore NOT excluded, and any session that writes them wedges the gate.
cd ~/prod/QUANTT && git status --porcelain -- . ':!ops/books/*_live'    # 3 lines
cd ~/prod/QUANTT && git status --porcelain -- . ':!ops/books/*_live/**' # 1 line
```

Measured 2026-09-10 13:05: 3 lines → 1. The two `phase0_live` ledger files drop
out once the exclusion actually matches; the line that remains is the untracked
`?? ops/HALT_phase0_null.md`, which the gate's own `':!ops/HALT_*.md'` then
excludes — with the full corrected exclusion set the gate is clean. Verify that
end-to-end, not just the one pathspec.

Measured 2026-09-10: prod's gate refused with two modified `phase0_live` files.
`':!ops/HALT_*.md'` *does* work, because it matches a real single-segment path —
which is exactly why the bug is easy to miss: four of the six exclusions work.

**Fix:** append `/**` to the directory exclusions. **Write a test** — this is a
live-path script with none, and the failure mode is silent in the direction that
matters (an exclusion that matches nothing looks identical to one that matched
and found nothing).

While you are in the file: the **uncommitted** working-tree version of
`ops/promote.sh` and `ops/backup_state.sh` replaces this gate with a bare
`git status --porcelain` and describes the ledgers as already untracked. **They
are not** — `git ls-files ops/books/cef_live` returns 30. Those two diffs
describe a future state as though it were current. Either correct them to
describe what is true, or revert them; do not commit them as they stand. See
item 5 for the ordering they assume.

---

## 3. Make `CLAUDE.md` re-measurable, and fix what it gets wrong

`CLAUDE.md` is the one file every agent reads, and it is now the repo's largest
single source of stale numbers. It already tells you *"Get the count by running
`python3 -m pytest`, never from this file"* — and then prints a count. Apply its
own rule to itself.

**Verified wrong as of 2026-09-10 ~13:00:**

| claim in `CLAUDE.md` | measured |
|---|---|
| "Measured 2026-09-10 ~12:00, **271 passing**" | **211** (`7ad3a82` removed 60 guard tests the same afternoon) |
| "`.claude/hooks/tests/` is the next largest (57)" | directory **does not exist** |
| "Each file below now carries a correction banner at its top" | **false for 2 of 6** — `docs/RESEARCH_STATE.md` and `docs/PER_NAME_ARCHITECTURE.md` have none |
| landmine 3: divergence "leaves sizing unaffected, `arm()` re-seeds from the broker" | **false when the broker holds zero.** `ib.positions()` emits no row for a flat symbol (measured: 34 rows, JAAA absent, nothing at exactly 0.0), so the re-seed cannot reach it and the stale ledger quantity survives into `place_targets` |

That last one is not a documentation nit — it is the reassurance that would have
let phase0 arm on 2026-09-11 against a 1,503-share position it does not hold.
Rewrite it to state the exception, and **cite the probe**.

**Do:** replace every standing count with the command that produces it. Keep
dated observations where the date *is* the point (incidents, measurements), and
mark them as observations. Add `git worktree list` to the prod/dev paragraph —
one command answers the question three documents failed to.

---

## 4. Compartment the old work (the actual "filing" job)

Six archive directories already exist and disagree about what they are for:

```
scripts/_archive   ops/_archive   docs/prompts/_superseded
ops/books/retired  ops/books/_dryruns   .claude/skills/graveyard
```

**Do not add a seventh.** Pick the convention that already dominates
(`_archive/` for code, `_superseded/` for prompts, `retired/` for books) and
write it down once, in `README.md`, with one line on what belongs in each. Then:

- **`docs/`** — 13 top-level `.md` files with no index, spanning July to
  September. Add the two missing correction banners (item 3). `PLAN.md`,
  `INFRASTRUCTURE.md` and `RESEARCH_AND_METHODOLOGY.md` already have banners —
  leave them, they are still cited.

  **DONE 2026-09-10, and the answer was "move nothing".** This item originally
  said to move anything "fully absorbed elsewhere" into `docs/_superseded/`.
  Measured against citation counts, that set is **empty**, and `docs/_superseded/`
  was deliberately NOT created. The two PREREGs and `HOW_WE_GOT_HERE.md` are
  protected historical records that `W0-G` (`9db624e`) already marked *"Not
  maintained, and MUST NOT BE"* — **archiving a pre-registration destroys the
  thing it exists to prove**, which is that a claim was committed to before the
  result was known. `EXIT_RESEARCH` (8 citations, written three days prior) and
  `SYSTEM_AND_STRATEGY` (33 citations) are live. Do not re-run this as a filing
  exercise: an instruction to archive is not evidence that anything should be,
  and the honest output of a tidy-up can be that the repo was already right.
- **Repo root** — `HANDOFF_2026-09-10.md` and `wu_paper_archive.html` sit beside
  `CLAUDE.md` and `README.md`. Handoffs are dated artifacts: give them
  `docs/handoffs/`. The stray HTML belongs in `docs/` or `results/`.
- **`docs/prompts/`** — 21 entries. **`W0b` is the pattern to copy** — it carries
  `> ## ✅ EXECUTED 2026-09-10 11:00 ET. Do not run this prompt again.` at line 15,
  above the body. `W0` is equally finished and carries nothing, so the pattern
  exists but is applied once. Note the banner sits below the preamble, so
  `head -12` misses it — check with `grep -n 'EXECUTED'`, not by eye. Apply it to
  every finished prompt, and give the directory an index table (prompt → lever →
  status → executed date) so a new agent does not open 21 files to find the three
  that are live.
- **`README.md`** — check whether it still describes this repo at all. It is the
  first file a new agent opens and nothing in the 2026-09-10 audit covered it.

**Constraint:** archiving is a `git mv`, never a delete, and every move leaves a
pointer behind. `ops/README.md`'s banner is the model to copy — it is wrong in
every material respect and says so in its own title.

---

## 5. Branch and merge hygiene — decide, then do it once

This is the team lead's call, not yours. Put the options to them and execute the
answer; do not pick silently.

All 40 commits of real work, the three tags, and the commit prod actually runs
live on a branch called `cleanup/2026-09-10-prompts-and-hygiene`. `main` is at
`9636502 "add"`, 40 behind and 0 ahead. So `main` no longer describes the
system, and the branch name no longer describes its contents.

The live tag **is** on origin, so nothing is at risk of being lost — but 28
commits after `v2026.09.10.2` are local-only. The question to ask:

1. Merge the branch to `main` (fast-forward — `main` is 0 ahead) and tag from
   `main` thereafter, so "what is live" is answerable from `main` alone; or
2. Keep a long-lived integration branch, rename it to something that means
   something, and document that `main` is decorative.

Either is defensible. The current state — neither — is what produced the
question that opened this prompt. **Push the 28 commits regardless.**

**Do not touch the ledger-untracking work** (`git rm --cached ops/books/*_live`,
`ops/heartbeat.json`) as part of this. Its precondition is not met: a
**scheduled** `backup_state.sh` run must first come back complete, and as of
2026-09-10 the only launchd-triggered run (12:17) silently omitted
`data/cef/cef_borrow.csv` and logged nothing but `rc=1`. The cause is the TCC
boundary — prod's `data/` is a symlink into `~/Desktop` and launchd's
`/bin/bash` has no Full Disk Access — so **no change to the backup script can
fix it.** The fix is prod owning its own `data/` (`ops/sync_dev_data.sh`).
Until then the panel's only copy outside `data/` is the dated manual one in
`~/prod-backups/borrow/`. Sequence: real `data/` → complete scheduled archive →
*then* untrack.

---

## 6. Standing constraints (unchanged, and they bind here)

- **Never run anything that can transmit an order.** Propose it and let the human
  run it with `! <command>`. `ops/promote.sh`, the `run_*.sh` wrappers,
  `launchctl load|unload`, the MOC probe, promote/cancel/reset.
- **`DRY_RUN=1` always wins.** `DRY_RUN=0` means "trade if preflight agrees".
- **No invented numbers.** Every figure in this prompt is re-measurable by a
  command in it. Keep that property. If you cannot fetch a figure, the output is
  a stated gap.
- **Label provenance** `[V]` / `[S]` / `[U]` on anything you assert.
- **Update `docs/RESEARCH_STATE.md` in the same commit as any trial.** This
  prompt runs 0 trials; neither counter moves (CEF 48, GAMMA 0 — verify against
  the counter table, which is canonical; its prose is not).

---

## 7. Out of scope — open, and owned by the team lead

Name these in your report; do not act on them.

- **`ops/HALT_phase0_null.md` is active.** Clearing it needs a ledger rebuild
  from broker executions plus attribution of ~$182.6k of LQD/HYG/JNK/EMB that no
  book claims — not a re-run of `reconcile_orders`. Details in the halt file.
- **`loaded:benchmarks` last exit 3 — RESOLVED 2026-09-10, do not act on it.**
  `doctor` FAILs on it, which is why the `v2026.09.10.2` promotion rolled back at
  11:36:50, and doctor's own suggested fix ("fix the plist, then bootout +
  bootstrap") is **wrong twice over**. `plist:benchmarks` already PASSes. The
  exit 3 is `run_book` rc=3 from the 2026-09-09 17:25 session:
  `arm: BLOCKED ANGL — account holds +87 and bench_b6_ew_credit trades it, but so
  does another book and this sleeve's ledger has no entry`. The other book is the
  **retired** `credit_rv`, which `_foreign_book_claims` still saw because it globs
  `ops/books/*.json` from **disk**. That cause is already fixed in `.1` — commit
  `43ec054` restored `ANGL 87.0` to bench_b6's ledger, and prod's last ledger date
  (2026-09-08) carries it, so `arm()` now finds a tagged value and will not block.
  **It is a stale exit code, not a live fault**, and it clears the next time
  benchmarks runs (17:25 on a trading day). No plist edit, no `launchctl`, nothing
  to fix. The durable lesson: `doctor` reports `launchctl`'s LAST exit status as a
  current condition and attaches a fix for a cause it never diagnosed. Making it
  distinguish "failing now" from "failed once, cause since fixed" is worth more
  than this one incident.
- **Email alerts: closed 2026-09-10.** The team lead's decision is that email is
  not wanted. `doctor`'s `alerts` check will therefore WARN forever on a
  configuration nobody intends to complete. Either teach the check that "no
  email, on purpose" is a PASS, or remove it — a permanent warning trains
  everyone to ignore the warning list, which is the list that was supposed to
  catch the next silent failure. **Do not re-propose email.**
- **Two stale research panels**, neither on the live path:
  `cef_distributions` last bar 2026-07-24 (48d), `etf_ohlc` 2026-07-29 (43d).
  phase0's own report flags `etf_panel` and `vrp_underlying` STALE.

---

## 8. Done looks like

- `ops/promote.sh`'s gate excludes what it claims to, with a test proving it.
- `CLAUDE.md` states no count a command could state instead, and its four
  measured errors are corrected — including the `arm()` re-seed exception.
- One archive convention, written down once, with no new archive directory.
- `docs/prompts/` has an index; every executed prompt carries an executed banner.
- A new agent can answer "what is live, and where" from `git worktree list` plus
  one paragraph — and the team lead's question is answered in the repo, not in a
  session transcript.
- Branch/merge decision made by the team lead and executed; 28 commits pushed.

Report what you changed, what you found that this prompt did not predict, and
anything you left because it was the team lead's call.
