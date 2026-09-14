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
| `_archive/docs/HOW_WE_GOT_HERE.md` | `docs/HOW_WE_GOT_HERE.md` | 2026-09-13 | `docs/SYSTEM.md`; `docs/RESEARCH_STATE.md` | A narrative of the summer, correct as of 2026-07-31 and deliberately never updated. Everything it calls current predates the no-trade band, the `shift(2)` correction and every broker-confirmed session after 07-31. It sends readers to `SYSTEM_AND_STRATEGY.md` for current state, which is itself archived. |
| `_archive/docs/SUMMER_2026_SUMMARY.md` | `docs/SUMMER_2026_SUMMARY.md` | 2026-09-13 | `docs/SYSTEM.md` | The 2026-08-16 progress summary. Its broker endpoint is the port that **caused** 21 silent dry-run sessions, its strategy section is the retired 2-day calendar, and its Sharpe figures are scored at `shift(1)`. |
| `_archive/docs/PROJECT_INTRO.md` | `docs/PROJECT_INTRO.md` | 2026-09-13 | `docs/SYSTEM.md` | A two-page recruiting introduction as issued 2026-08-16. Its timeline, status and strategy description are as of that date; the trading policy changed three weeks later. |
| `_archive/docs/recruiting-page.html` | `docs/recruiting-page.html` | 2026-09-13 | — | An "open roles 2026/27" web page. Referenced by nothing. Its reading list starts with a document that is now archived. |
| `_archive/docs/pdf/` | `docs/pdf/` | 2026-09-13 | — | PDFs of INFRASTRUCTURE, PROJECT_INTRO and the summer summary, built 2026-08-16 — **before** the correction banners, so the Infrastructure PDF still gives the broker port that caused the silent dry runs. Never read a PDF here for any fact. |
| `_archive/docs/build_pdfs.py` | `docs/build_pdfs.py` | 2026-09-13 | — | The pandoc + headless-Chrome builder for those PDFs (with `template.html` and `print.css`). Two of its three sources are archived; it will not run from here without editing its paths. |
| `_archive/docs/template.html` | `docs/template.html` | 2026-09-13 | — | Pandoc template for `build_pdfs.py`. |
| `_archive/docs/print.css` | `docs/print.css` | 2026-09-13 | — | Print stylesheet for `build_pdfs.py`. |
| `_archive/docs/handoffs/HANDOFF_2026-09-10.md` | `docs/handoffs/HANDOFF_2026-09-10.md` | 2026-09-13 | — | An overnight session handoff. Every "status" in it is 2026-09-10 10:40 ET: branch names, halts, what main was at. |
| `_archive/docs/prompts/NEXT_2026-09-11.md` | `docs/prompts/NEXT_2026-09-11.md` | 2026-09-13 | `docs/prompts/README.md` | The work order for one day. It names prod's tag and a book NAV as of 2026-09-10, and named two release tags when three existed. The day has passed. |
| `_archive/docs/prompts/_superseded/` | `docs/prompts/_superseded/` | 2026-09-13 | the W/F/G work orders | The original P-series prompts, consolidated into W/F/G on 2026-09-09. Their own README lists two claims now known to be wrong (an ex-distribution date "moves price and not NAV"; a SOFR leverage-cost conditioner for SIFMA-reset munis). P-numbers are not live identifiers. |
| `_archive/results/ACADEMIC_REPORT_2026-07-31.md` | `results/ACADEMIC_REPORT_2026-07-31.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` | The "thirteen mechanisms" report on the credit-ETF programme that preceded the CEF book. Correct as a record of those kills; says nothing about the CEF strategy as traded. |
| `_archive/results/OVERNIGHT_REPORT_2026-07-30.md` | `results/OVERNIGHT_REPORT_2026-07-30.md` | 2026-09-13 | `docs/RESEARCH_STATE.md` | The 2026-07-30 overnight write-up of the forced-flow / ETF work. Pre-CEF. |
| `_archive/results/journal/` | `results/journal/` | 2026-09-13 | `docs/RESEARCH_STATE.md` | Checkpoint journal for that overnight run. |
| `_archive/notebooks/` | `notebooks/` | 2026-09-13 | — | R2/TRACE research notebooks from the fallen-angel programme, which is dead. They read data sources this repo no longer stages. |
