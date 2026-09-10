# ops/_archive

Files kept because deleting them would destroy the sole record of a published
number, an incident, or a decision. **Nothing here is on any code path.**

The rule this directory exists to serve (W0 Part A):

> Nothing is deleted if it is the sole surviving record of a published number,
> an incident, or a decision. Those are archived with a pointer. Everything else
> — genuine duplicates, superseded backups, one-off scripts whose job is done —
> is deleted, and the commit message says what and why. **When in doubt,
> archive**: the cost of a stale file here is a directory entry, and the cost of
> deleting the only copy of the evidence behind a number in `RESEARCH_STATE.md`
> is that the number becomes unfalsifiable.

---

## `cef_discount.v5.20260731.frozen.json`

The **pre-band specification**, in force from 2026-07-31 to 2026-09-06. Was
`ops/specs/cef_discount.frozen.json.bak-20260906`; renamed here to its own
`spec_id` so it is identifiable without opening it.

**Kept because it is evidence, not a backup.** It is the specification that
`results/cef/PREREG_BAND_2026-09-06.md` compares against, so it is one half of
the band's pre-registration. Every "the band improved X from Y to Z" figure in
this repo is a comparison to *this file's* behaviour.

It is also the definition of the revert path. `cef_discount.frozen.json` says
deleting the `band_width` key restores v5 exactly, and `rebalance_days: 2` is
retained inert for that purpose — this file is what "exactly" means.

Archived 2026-09-10. **Do not delete.**

## `fix_bench_b6_angl_20260909.py`

A one-off repair, run once on 2026-09-09. It edited the benchmark book's fill
record to fix an ANGL attribution fault in `bench_b6_ew_credit`.

**Kept because it mutated a fill file.** `broker_fills.csv` is the only record of
real executions — TWS forgets them at its daily restart and there is no
historical execution endpoint — so any hand-edit to one has to stay explicable
afterwards. Deleting this script would leave a fill record that disagrees with
its own capture history and nothing to explain why.

Its job is done and it must not be re-run: it is not idempotent and the fault it
repaired no longer exists. The scoped-halt work of 2026-09-10 (`HALT_<book>.md`)
is the durable fix for the class of problem it patched.

Archived 2026-09-10.

---

## What was deleted instead, and why that was safe

Seven `.bak` files from the 2026-08-31 repo move were removed in the same commit
that created this directory. Each was verified present in `HEAD` before removal,
so `git show HEAD~1:<path>` recovers any of them:

```
ops/capture_fills.py.bak-20260831
ops/schedule/cef.env.bak
ops/schedule/cef.env.bak-20260831
ops/schedule/phase0.env.bak-20260831
ops/schedule/schedule.env.bak-20260831
ops/schedule/weekly_book_report.py.bak-20260831
src/deploy/broker/ibkr.py.bak-20260831
```

An eighth, `ops/books/benchmarks_live/_attribution.json.bak-20260831`, was
removed later the same day, once the `PreToolUse` guard that refused agent writes
under `ops/books/` had been removed. Verified superseded first: a strict subset of
the live `_attribution.json`, missing `bench_b1_hyg` entirely and HYG from
`bench_b6_ew_credit` — a pre-2026-08-31 snapshot. Recoverable from `HEAD`.

They carry nothing git does not already hold, and a `.bak` sitting beside a live
file is an active hazard: `ibkr.py.bak-20260831` still contains the pre-rename
`from ..v2.odd_lot import ...` that was a real bug in its parent, and a grep for
that import returns the backup as though it were live code.

## One file that is NOT here, and must not be

`config/.env.switch_broker.bak` is a byte copy of the live credentials file,
written by `ops/switch_broker.py`. It is **gitignored, therefore genuinely
unrecoverable, and therefore must be deleted outright rather than archived** —
`.gitignore`'s own comment anticipates exactly this file. Archiving a credentials
copy would be moving the hazard, not removing it.

It is left in place as of 2026-09-10 because deleting it is irreversible and
touches credentials, which is an operator action, not an agent one. See the
"Still open" section of `results/ops/REPO_HYGIENE_2026-09-10.md`.
