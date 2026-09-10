# W0 — Repo hygiene: fix what is broken, archive what is finished, date what is stale

**Reads first:** `00_BRIEF.md` §6 (house rules), and rule **H14** — no decision
rule may key on a number written in a document. This prompt is partly about
enforcing that rule on the repo itself.
**Lever:** none directly. It makes everything else cheaper and safer to read,
and three of its items are live bugs.
**Trials:** 0. Nothing here evaluates a specification.
**Touches the live book:** two import fixes on code paths the executor reaches.
Everything else is archival.
**Run first.** It is cheap, it unblocks reading, and the broken imports are
real.
**New 2026-09-10.**

---

## Paste from here

You are doing a hygiene pass on the QUANTT repo. Read
`docs/prompts/00_BRIEF.md` §6, then work through the parts below.

**The governing principle, because most of this is deletion and deletion is the
one thing you cannot undo by reading harder:**

> **Nothing is deleted if it is the sole surviving record of a published number,
> an incident, or a decision.** Those are archived with a pointer. Everything
> else — genuine duplicates, superseded backups, one-off scripts whose job is
> done — is deleted, and the commit message says what and why. **When in doubt,
> archive; the cost of a stale file in `_archive/` is a directory entry, and the
> cost of deleting the only copy of the evidence behind a number in
> `RESEARCH_STATE.md` is that the number becomes unfalsifiable.**

Check `git log --oneline -- <path>` before removing anything. A file that is in
git history is recoverable and can be deleted; a file that never was is not.

---

## Part A — Stale parameters in analysis code (do this first; it is the one that silently produces wrong answers)

**Four analysis scripts hardcode the band width at 6.4%. The live band has been
4.8% since 2026-09-06.** Verified 2026-09-10:

```
scripts/cef/joint_cost_optimiser.py:395   band(Tp, 0.064)     "plain_band"
scripts/cef/joint_cost_optimiser.py:403   band(Ti, 0.064)     "inv_band"
scripts/cef/joint_cost_optimiser.py:412   band_hard_exit(Tp, 0.064, E)
scripts/cef/joint_cost_optimiser.py:413   band_hard_exit(Ti, 0.064, E)
scripts/cef/joint_cost_optimiser.py:560   band(Tp, 0.064)     "w ~ alpha, band 6.4%"
scripts/cef/covariance_construction.py:151  band(T, 0.064)    "band 6.4%"
scripts/cef/borrow_impact.py:101            band(T, 0.064)    "band 6.4%"
scripts/cef/ou_score.py:198                 band(T, 0.064)    "band 6.4%"
```

**Why this is the most dangerous item in the repo:** every one of those four
scripts is named in a prompt as something an agent should extend.
`joint_cost_optimiser.py` → W11 and W12 (W12 says "inside its loop, holding
everything else fixed"); `covariance_construction.py` → W12, W8, F3;
`borrow_impact.py` → W8; `ou_score.py` → F2.

An agent following those instructions inherits a 6.4% baseline and compares its
work against **a book that is not live**. Nothing errors. Nothing looks wrong.
The comparison is simply against the wrong reference, and every conclusion drawn
from it is off by the difference between two policies — which is precisely the
size of the effects these prompts are trying to detect.

**The fix is not to change 0.064 to 0.048.** That would be correct today and
wrong the next time the spec moves. **Read the parameter from the frozen spec:**

```python
import json, pathlib
SPEC = json.loads((REPO/"ops/specs/cef_discount.frozen.json").read_text())
BAND = SPEC["frozen"]["band_width"]          # and raise if the key is absent
```

Apply the same treatment to every parameter any analysis script shares with the
spec — `z_window`, `vol_target_annual`, `min_adv_usd`, `min_names`,
`min_abs_weight`, `max_nav_age_bd`, `gross_leverage`, `universe`. A sweep that
*deliberately* varies a parameter (the band frontier's width sweep, which is the
point of that script) is fine and should say so in a comment; a *baseline* that
hardcodes a value the spec owns is a bug.

**Then add the guard that stops it recurring.** A test that loads the frozen
spec and asserts no analysis script contains a literal matching a spec value it
should be reading — or, more simply and more robustly, a module
`scripts/cef/spec.py` that is the single reader of the frozen spec, with every
other script importing from it. **Nothing should open that JSON twice.**

Check `config/costs.yaml` the same way: it is described as a 2026-07 spread
probe, and W7 Part C measures spreads independently. If the two disagree, which
one a script picks up determines its answer.

---

## Part B — Broken references (these are bugs, fix them)

> **Four were fixed on 2026-09-10 before this prompt was written. Verify they
> are still fixed, then move on:**
>
> - **`scripts/audit/cef_{cost_frontier,factor_audit,sector_and_lag}.py`** each
>   began `from pathlib import Path, numpy as np, pandas as pd` — an
>   `ImportError` on **every** run. All three are cited in
>   `docs/INFRASTRUCTURE.md` as the factor-audit tooling, so "re-run the factor
>   audit" hit a wall every time. Now three proper imports.
> - **`scripts/fetch_cef_distributions.py`** used `Path(...)` without importing
>   it — `NameError` on every run. This is the fetcher for the distribution
>   panel that Part E flags as ~7 weeks stale and that W4 and W9 both need.
> - **The ignore file's bare `data/` also matched `src/data/`**, silently
>   untracking `r2.py` and `__init__.py` — and it would have swallowed any
>   future `src/**/data/` module the same way. Now anchored to `/data/`.
> - A stray empty `Other/` tree, created when an audit imported
>   `scripts/fetch/build_a0_data.py` (its module-level `mkdir` runs at import).
>   **That `mkdir`-at-import is itself the bug** — the script's `REPO` now
>   resolves inside the repo instead of to a sibling project. Fix or delete it.
>
> **All four came from one commit** — the bulk repo-move path rewrite. When you
> find a fifth, look there first.
>
> Still open, and flagged rather than fixed because it touches the live path:
> **`scripts/cef/fetch_borrow_rates.py` imports `ib_insync`** at two call sites
> while running in the session's panels phase. The repo's own rule in
> `.claude/rules/live-order-path.md` says `ib_insync` is unmaintained and hangs
> on Python 3.12+, and this machine is on 3.13. **It is empirically working** —
> the borrow panel has three dates including 2026-09-09 — so this is a latent
> inconsistency, not a live break. Migrate it to `ib_async` deliberately, with a
> human watching the next panels phase, rather than as a drive-by edit.

Seven paths are cited or imported and do not exist. Verified 2026-09-10; confirm
each yourself before acting, since some may have been fixed since.

| citing code | missing target | what it is |
|---|---|---|
| `src/deploy/run_book.py:326` | `src/deploy/sleeves/spy_shortvol_marks.py` | lazy import; `ModuleNotFoundError` if any book declares a `short_vol_straddle` sleeve |
| `src/deploy/exec_ledger.py:770` | `src/deploy/v2/odd_lot.py` | **wrong path** — the module is at `src/deploy/lib/odd_lot.py` |
| `src/deploy/lib/attribution.py:28` | `scripts/refine/a4_attribution.py` | cited in a docstring |
| `src/deploy/lib/attribution.py:18` | `results/vrp/refute_tail_ledger_SPY.csv` | **the VOL factor is unbuildable without it** |
| `data/vrp/costs_vrp.yaml` | `results/vrp/RECON.md` | the cost floor's own justification |
| — | `scripts/vrp/` (whole directory) | the pipeline that produced `marks_SPY.parquet` |
| prompts | `src/deploy/lib/black76.py` | never existed; `gamma/G1` creates it |

**Three decisions, each stated in the note:**

1. **`v2.odd_lot` is a straightforward path bug — fix it.** One line.
2. **`spy_shortvol_marks`**: either write the module (`gamma/G5` needs a marks
   provider anyway) or remove the dead branch **and** the registry entry that
   permits `short_vol_straddle`. Do not leave a lazy import to a module that
   cannot exist. Pick one and say why.
3. **`scripts/vrp/` and `results/vrp/`**: `gamma/G2` Part D rebuilds the
   extraction pipeline. Until then, **do not silently tolerate the dangling
   references** — put a `README` in each expected location stating what is
   missing, what depended on it, and which prompt restores it. A missing
   directory with an explanation is a known gap; a missing directory without one
   is a trap for the next reader.

Also fix the **name** error while you are here: prompts and comments refer to
`ibkr.py::_place_bag`; the method is **`_place_combo`** (line ~1130). Grep and
correct.

---

## Part C — Dead code that must NOT be deleted

`greeks_fn` appears in **40 places across six files** and has **zero call
sites**. `LegGreeks` is defined once and used nowhere.

**Do not delete either.** `gamma/G4` Part C gives both their first producer and
consumer, and pins the signature. Deleting them now means re-threading the same
parameter through the same six files in a fortnight.

What to do instead: add a one-line comment at each definition — *"threaded but
not yet called; first producer lands in gamma/G4"* — so the next reader knows it
is pending rather than abandoned. **The rule this illustrates is worth stating
in the note: unused scaffolding with a dated owner is not dead code; unused
scaffolding with no owner is.**

**Apply that test to the registry, where it comes out the other way.** Verified
2026-09-10: `src/deploy/registry.py` permits alloc types whose sleeve modules do
not exist — the four `FF_TRACKER_ALLOC_TYPES` (whose package `v2.ff_sleeves` is
gone), plus `short_vol_straddle` and `duration_hedged_overlay`. Each validates
happily and then raises at run time. **They have no dated owner, so by the rule
above they are dead** — either delete the entries or point each at the prompt
that will build it. `short_vol_straddle` is the one to keep, since `gamma/G5`
needs it; the other five are fossils.

Note the useful contrast: **`mark_fn` is threaded exactly like `greeks_fn` but
*is* called**, so it is live scaffolding, not dead. Check for a call site before
judging.

---

## Part C2 — How to decide a file is dead, because the obvious method is wrong

An audit on 2026-09-10 produced a confident list of ~107 deletable source files.
**Checking it found a file on that list that four active prompts depend on.**
The method below is what survived; use it, and do not shortcut it.

**`scripts/fetch/refresh_market_feeds.py` was listed as dead** on the reasoning
that `scripts/fetch/_setup.py` imports from an `archive/` directory that no
longer exists, so "the whole directory is dead". But `refresh_market_feeds.py`
imports only `sys`, `pathlib`, `pandas` and `yfinance` — it never touches
`_setup.py` — and **W4, W10, W13 and F2 all instruct an agent to use it** to
fetch MUB, PZA and VIX into the panel. Deleting it would have broken four
prompts in a way that only surfaces when someone runs one.

**The lesson: a directory is not a unit of deadness.** One broken file in it
proves nothing about its neighbours.

Three checks, all three required, per file:

1. **Does anything import it?** `grep -rn "from X import\|import X"` on the
   module path — **not** the basename. Basenames collide with English:
   `signal`, `costs`, `book`, `trials` and `pairs` each match dozens of prompt
   files as ordinary words. A basename grep will tell you a dead file is alive
   and, worse, is equally capable of the reverse.
2. **Does it run?** Import is not execution. Every one of
   `ops/{daily_run,monitor,portfolio_monitor,weekly_report,smoke_test}.py`
   **imports cleanly** and then exits `rc=1` with `FileNotFoundError` on the
   missing `ops/spec/frozen_spec.json` when actually invoked. If you test these
   by importing them you will conclude they are fine. Run them.
3. **Is it named by an active prompt, a live config, or a results note?** Search
   `docs/prompts/`, `ops/schedule/*.env`, `config/`, and `results/**/*.md` for
   the **path**. This is the check that saves the files that are dormant rather
   than dead — `scripts/nport/`, `scripts/positioning/` and
   `src/backtest/tearsheet.py` all look orphaned by import and are all named as
   inputs by `perfund/F1` or `W1`.

**Then apply the tiebreaker: what does deleting it cost if you are wrong?**
A research script that is the sole code behind a number quoted in
`RESEARCH_STATE.md` costs you the ability to reproduce that number — archive it.
A one-off with its output already committed costs nothing — delete it.

**Do not delete source files in bulk on the strength of a single audit pass**,
including this one. Work through them in small batches, run the test suite after
each, and record in the note which of the three checks each file failed.

---

## Part D — Superseded artifacts

**Backups, ten of them:**

```
config/.env.switch_broker.bak
ops/books/benchmarks_live/_attribution.json.bak-20260831
ops/capture_fills.py.bak-20260831
ops/schedule/cef.env.bak
ops/schedule/cef.env.bak-20260831
ops/schedule/phase0.env.bak-20260831
ops/schedule/schedule.env.bak-20260831
ops/schedule/weekly_book_report.py.bak-20260831
ops/specs/cef_discount.frozen.json.bak-20260906
src/deploy/broker/ibkr.py.bak-20260831
```

**Verified 2026-09-10, and it simplifies this considerably: nine of the ten
`.bak` files are themselves committed to git**, so deleting them is reversible
regardless of what they contain. Eight also match a historical blob of their
parent exactly, so they carry nothing git does not already hold.

Two exceptions, and only one matters:

- **`ops/schedule/cef.env.bak`** (undated) — committed as a file, but its
  content matches no commit of its parent. Deleting it is still reversible;
  keep it only if you want that intermediate state readable without a
  `git show`.
- **The `switch_broker` backup under `config/`** — **gitignored, so genuinely
  unrecoverable, and it is a byte copy of the live credentials file.** This one
  should be **deleted outright, not archived.** It was world-readable until
  2026-09-10; that has been corrected, but the right end state is that it does
  not exist. The ignore file's own comment anticipates exactly this file.

`cef_discount.frozen.json.bak-20260906` is the pre-band spec. That one is
**certainly evidence** — it is the specification the band's own pre-registration
compares against. Archive, never delete.

**One-off scripts:** `ops/fix_bench_b6_angl_20260909.py` did its job. Archive it
under `ops/_archive/` with the date and what it fixed, so the fill-file edit it
performed is explicable later.

**Duplicate data:** `marks_SPY_full.parquet` and `marks_SPY.parquet` are both
389,135 rows and differ only in 129 `px` values by at most **5.7e-14** — float
round-trip noise, not two datasets. **Keep one, delete the other, and record
which in the file's own provenance note.** Carrying two "sources" that disagree
in the fourteenth decimal is how a reconciliation bug is born.

**Orphaned research code:** `scripts/cef/cef_sleeve.py` and `cef_sleeve_v2.py`
(both 2026-07-31) have **zero references anywhere in the repo**, and are
superseded by `src/deploy/sleeves/cef_discount.py`. Their result artifacts —
`results/cef/cef_sleeve_daily.parquet`, `cef_sleeve_v2_daily.parquet`,
`cef_sleeve_v3_daily.parquet` — are the evidence behind numbers in
`RESEARCH_STATE.md`. **Archive the scripts, keep the parquets**, and add a line
to each pointing at the note that cites it.

---

## Part E — Stale data, and the discipline that stops it recurring

Measured 2026-09-10:

| file | last data / mtime | behind |
|---|---|---|
| `cef_prices.parquet`, `cef_nav.parquet` | 2026-09-09 | current |
| `cef_distributions.parquet` | 2026-07-24 | **~7 weeks** |
| `data/rv/etf_ohlc.parquet` | 2026-07-29 | **~6 weeks** |
| `cef_facts.csv` | mtime 2026-07-31, **no date column at all** | ~6 weeks |
| `cef_borrow.csv` | 2 dates, 17 names, `api_shortable_shares` 100% null | is a snapshot, not a panel |

Three of these are actively load-bearing and one is dangerous:

- **`cef_distributions.parquet`** feeds W4's return correction and W9's ex-date
  and record-date calendar. Seven weeks of missing ex-dates is seven weeks the
  correction cannot be applied to. **W9's forward-distribution fetch is the
  fix**; until it lands, every note using this panel states its end date.
- **`etf_ohlc.parquet`** feeds `gamma/G3`'s variance work and every ETF proxy in
  W10 and W13. Refresh it.
- **`cef_facts.csv` is the dangerous one.** It has no date column, its most
  valuable fields (expense ratios, net assets, fund family, inception date) are
  **100% null**, and `sector`/`industry` are constant across all 44 rows. It is a
  single undated yfinance snapshot. **Anything that joins it to a 27-year panel
  is committing a look-ahead error.** Either add a `fetched_at` column and a
  loud docstring, or let `perfund/F1` supersede it and mark it deprecated. Do
  not leave it as-is looking like a fact table.

**Then add the discipline, because this recurs otherwise:** every panel gets a
`fetched_at` or an explicit last-date assertion, and `ops/doctor.py` gains a
staleness check that warns when a panel the sleeve depends on falls more than a
stated number of sessions behind the price panel. **A stale input that fails
loudly is an inconvenience; a stale input that fails silently is a wrong
number.**

---

## Part F — Contradictions between documents

Two survive and neither has an owner:

1. **Per-name half-lives.** `docs/PER_NAME_ARCHITECTURE.md` §4's derived-band
   table gives PHK 24.6 and DSL 12.3; `docs/PLAN.md` §4.1 gives PHK 41.9 and
   DSL 11.9. Two different estimation windows are evidently in play and **no
   document says which produced which.** `perfund/F2` Part C recomputes all
   seventeen and owns the reconciliation — **cross-reference it from both
   documents now** so a reader who lands on either knows the number is disputed.
2. **Tick cost.** The same table says PHK 22.22bp; `config/costs.yaml` says
   25.77; `PLAN.md` §4.1 says 10.65. These are different quantities — full tick
   versus half-spread — but no document defines which it means. **Define the
   convention once, in `00_BRIEF.md` §3, and make all three cite it.**

**Do not resolve these by picking a number.** Note the disagreement where it
appears, name the prompt that will settle it, and move on. An acknowledged
contradiction is safe; a silently reconciled one is not.

---

## Part G — Age-check the documents

Six files under `docs/` have not been touched since July or August:
`PROJECT_INTRO.md`, `SUMMER_2026_SUMMARY.md`, `HOW_WE_GOT_HERE.md`,
`RESEARCH_AND_METHODOLOGY.md`, `E1_PREREG.md`, `CREDIT_RV_PREREG.md`.

**Read each and classify it — do not edit them yet:**

- **Historical record** (`HOW_WE_GOT_HERE.md`, the two PREREGs) — correct as of
  its date and should not be updated. Add a one-line header: *"Historical record
  as of &lt;date&gt;; not maintained."*
- **Live methodology** (`RESEARCH_AND_METHODOLOGY.md`) — still governs, so it
  must be current. Check it against `00_BRIEF.md` §5 and reconcile any rule that
  has since changed, notably the two trial counters and the 2023 time holdout.
- **Orientation** (`PROJECT_INTRO.md`, `SUMMER_2026_SUMMARY.md`) — check whether
  they describe a book that still exists. If they describe the pre-band
  configuration or the null trader as live, they are misleading a new reader on
  day one.

Also check whether `docs/pdf/`, `recruiting-page.html`, `template.html`,
`print.css` and `build_pdfs.py` are still used by anything. If they are a
finished deliverable, archive them together.

## Deliverables

- The two import fixes and the `_place_bag` rename, each with a test or a grep
  showing the path now resolves.
- `ops/_archive/` with the incident backups, the one-off scripts and the
  orphaned sleeve code, each with a README naming what it is and why it is kept.
- The duplicate marks file resolved, with provenance recorded.
- `fetched_at` on every panel that lacks it, and the doctor staleness check.
- `results/ops/REPO_HYGIENE_<date>.md`: what was fixed, what was archived, what
  was deleted **and why it was safe**, the contradictions still open with their
  owning prompt, and the document classification from Part F.

## Do not

- Do not delete anything that is the sole record of a published number, an
  incident, or a decision. Archive it.
- Do not delete `greeks_fn` or `LegGreeks`; `gamma/G4` wires them.
- Do not resolve a documented contradiction by choosing a value.
- Do not refresh a panel and leave the note that used the old one unamended —
  if a number moves, the note that quoted it is now wrong.
- Do not treat `cef_facts.csv` as a fact table.
