# _archive — the record of what we did, and none of what is true now

**Nothing in this folder describes the current state of the book, the system or
the research.** Every figure here is a dated observation taken from a document
that has since been superseded. If you are about to quote one, re-measure it
(`python3 -m ops.orient`), or state it as a gap.

What is true now lives in exactly three places, and nowhere in here:

| question | owner |
|---|---|
| any number — fills, arm rate, spec, counters, panels, what prod lacks | `python3 -m ops.orient` |
| what we trade, how the system runs, what we know | `docs/SYSTEM.md` |
| which document owns which question | `docs/INDEX.md` |

## Why it is a separate folder

Before 2026-09-13 superseded documents sat beside current ones with a banner on
top. A banner tells a reader the document is stale; it does not stop an agent
that found the file by searching from quoting its body. Six documents each
claimed to be the entry point, "how the strategy works" was written six times,
and the copies disagreed about the arm rate, the vol target, breadth and which
tag prod ran. The cure is distance, not more banners.

## The wall, and its holes

`.gitignore` lists `/_archive/`. **Everything here is still tracked** — an
ignore line does not untrack a committed file, the same shape as the live
ledgers — with its history (`git log --follow`). What the line does is keep
archived bodies out of search: `rg` and the `grep` that Claude Code's shell
runs (ugrep with `--ignore-files`) both skip gitignored paths unless pointed at
them. So a search for a phrase lands on the current document, not a superseded
one. A `.ignore` file was tried first; only ripgrep reads it, and `grep -r`
walked straight through.

**The holes:** `find`, `ls`, `git grep` and `git ls-files` still see this folder,
and any tool can open a path it is given. That is why every archived `.md` opens
with a banner saying what it was and what now owns its subject, and why
`ops.doc_audit` fails if one does not. The verification is recorded in
`results/ops/ARCHIVE_WALL_2026-09-13.md`.

**The price:** a *new* file here is invisible to `git status` and skipped by
`git add -A`. Use `git mv` (which records the rename regardless) or `git add -f`.
`ops.doc_audit` fails on any file under `_archive/` that git is not tracking.

Deliberate reads still work: `rg <pattern> _archive/`, `grep -r <pattern>
_archive/`, or opening a path. Archived material is legitimate *provenance* — it
is where a number came from — and is never *authority* for what is true today.

## Rules

1. **Never delete.** The test from `ops/_archive/README.md` stands: *what does
   deleting it cost if you are wrong?* The only copy of the evidence behind a
   quoted number makes that number unfalsifiable when it goes.
2. **Mirror the original path.** `docs/PLAN.md` lives at `_archive/docs/PLAN.md`.
   A document trimmed in place leaves a dated snapshot beside its mirror path:
   `_archive/docs/RESEARCH_STATE_<date>.md`.
3. **`git mv` (or `git add -f` for a new file), and the banner in the same
   commit**, so rename detection keeps the history attached. Banner, within the
   first 45 lines:

   ```
   > **ARCHIVED <date> — not evidence of current state.** Was `docs/PLAN.md`.
   > Now owned by: `docs/SYSTEM.md` §N. Numbers: `python3 -m ops.orient`.
   ```

   A snapshot says ``Snapshot of `<path>` at `<sha>` `` in place of ``Was``.
4. **Repoint every citation in the same commit.** A work order in
   `docs/prompts/` may cite an archived file as background, spelled
   `_archive/...` and called archived. `CLAUDE.md`, `.claude/` and the canonical
   documents never cite this folder as an authority.
5. **Never create a file named `CLAUDE.md`, or a `.claude/` directory, in
   here.** Claude Code auto-loads a nested `CLAUDE.md` when it reads files in
   that subtree, which would put a superseded rulebook back in front of every
   agent that opened a path here. Snapshots of `CLAUDE.md` are named
   `CLAUDE_md_<date>.md`; archived agent-layer files go under
   `_archive/claude_layer/`.
6. **Nothing imports from here.** `ops.doc_audit` checks all of the above.

Two older archive folders predate this one and still hold code:
`ops/_archive/` (including the v5 frozen spec, which is the band's revert path)
and `scripts/_archive/`. They fold in here when research code is archived.
`ops/books/retired/` never moves — `IBKRBroker._foreign_book_claims` globs
`ops/books/*.json` non-recursively, and its location is what keeps a retired
book's symbols out of that check.

## Index

Every archived file, or a directory containing it, has a row. **The last column
is the reason this folder exists**: what the document is wrong *about*, in
substance, so that a reader who does open it knows which sentence not to copy.

| path | was | archived | now owned by | what it is wrong about |
|---|---|---|---|---|
| `_archive/ARCHIVE_WALL_SENTINEL.md` | — (new) | 2026-09-13 | — | Nothing. It carries a token that exists nowhere else in the repo, so a search that returns it has crossed the wall. |
