# `docs/handoffs/`

**Dated session handoffs.** One file per handoff, named for the date it was
written.

## What these are, and how to read one

A handoff is written at the end of a working session for whoever picks the book
up next. It is a **snapshot of a moment**, not a reference: it says what was
true, what was in flight, and what the next person should do first.

**Every statement in a handoff is stale by construction.** Read the date in the
filename, then read every "today", "now", "currently" and "live" in the file as
of that date. A handoff is the one document class in this repo that is *supposed*
to go out of date — that is what makes it useful as a record and dangerous as a
reference.

**Never take a number from a handoff into a decision.** `CLAUDE.md` H14: no
decision rule may key on a number written in a document. Re-measure:

```bash
python3 .claude/hooks/book_state.py -p     # live book state
python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live
```

## Why they live here

They were at the repo root, beside `README.md` and `CLAUDE.md`, where a new
reader could not tell a dated artifact from a standing document. Moved
2026-09-10 (W0c §4). The convention: **dated artifacts get a dated directory;
standing documents live at the root or in `docs/`.**
