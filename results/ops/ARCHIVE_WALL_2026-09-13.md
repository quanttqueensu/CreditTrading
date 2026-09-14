# The archive search wall: what it stops, what it does not

**Measured 2026-09-13 ~23:45 ET** in the `docs-cleanup` worktree (branched from
main `1354743`). Reproducer: the command matrix below, plus
`ops/doc_audit.py` (`check_archive_wall`) and its tests in
`ops/tests/test_doc_audit.py`. Tools: ripgrep 14.1.1; `grep` is a Claude Code
shell function that execs ugrep 7.8.4 with `--ignore-files`.

## Why this note exists

The cleanup plan for `_archive/` (team lead, 2026-09-13) chose "hidden from agent
search, readable on request". The plan assumed a `.ignore` file would hold it,
on the strength of how Claude Code's Grep and Glob tools invoke ripgrep. **Both
premises were wrong in this environment**, and either would have produced a wall
that looked built and stopped nothing:

1. **This Claude Code build has no Grep or Glob tool.** A subagent asked to run
   them reported that neither exists (ToolSearch `select:Grep,Glob` → no match).
   Agents search through the shell.
2. **The shell's `grep` does not read `.ignore`.** It is ugrep with
   `--ignore-files`, which reads `.gitignore`. With only `.ignore` in place,
   `grep -rl <token> .` returned the archived sentinel. ripgrep alone respected it.

The wall is therefore the line `/_archive/` in `.gitignore`, on a directory whose
files are tracked (ignore lines do not untrack committed files — the live
ledgers in `ops/books/*_live/` already have this shape).

## Matrix (with `.gitignore` holding `/_archive/`, sentinel tracked)

`T` is the token in `_archive/ARCHIVE_WALL_SENTINEL.md`, read from that file and
never spelled elsewhere (`test_the_real_sentinel_token_exists_only_in_the_archive`
enforces that).

| command | result | reading |
|---|---|---|
| `rg -l "$T"` | nothing | walled |
| `rg -l "$T" _archive` | `_archive/ARCHIVE_WALL_SENTINEL.md` | deliberate search works |
| `grep -rl "$T" --exclude-dir=data .` | nothing | walled |
| `grep -rl "$T" _archive` | `_archive/ARCHIVE_WALL_SENTINEL.md` | deliberate search works |
| `git grep -l "$T"` | `_archive/ARCHIVE_WALL_SENTINEL.md` | **not walled** — searches tracked files |
| `find . -name ARCHIVE_WALL_SENTINEL.md` | found | **not walled** — lists paths |
| Read `_archive/README.md` (subagent) | succeeded | explicit reads work |

Not tested and assumed **not walled**: `/usr/bin/grep -r` invoked by path or from
a subprocess (BSD grep reads no ignore file).

Throwaway-repo checks run before adopting `.gitignore` (in the scratchpad, then
deleted): `git mv docs/A.md _archive/docs/A.md` succeeds and records `R`; an edit
to a tracked archived file shows in `git status`; **a new file under `_archive/`
does not, and `git add -A` skips it** — hence `archive:tracked`, which failed on
this very commit's two files until they were added with `git add -f`.

## What this changes

- The banner on every archived `.md` is load-bearing, not belt-and-braces:
  `find` and `git grep` reach the bodies.
- `ops.doc_audit` checks the ignore line, tracking, banners, mirror paths, the
  index, nested `CLAUDE.md`/`.claude/`, and imports from `_archive`. Each
  sub-check has a test that plants the defect and watches it fail.

## What would make this wrong

If a future Claude Code build restores a Grep/Glob tool, re-run the matrix with
it: a tool that passes `--no-ignore` would cross the wall, as the plan feared for
Glob. If `grep` stops being the ugrep wrapper, re-run the `grep -rl` rows.
