# Dead-entry audit — directory scans on the live path

**Date:** 2026-09-10 · **Tree:** `/Users/simonjarvis/Desktop/2027/QUANTT/2027` (dev; prod is
`~/prod/QUANTT`, detached at `v2026.09.10.1`) · **Scope:** `src/deploy/`, `ops/`,
`~/Library/Application Support/quantt/launch_job.py`, the scripts `launch_job.py` invokes, and
`~/Library/LaunchAgents/`.

Nothing was changed. Every figure below names the command that reproduces it, run from the repo
root unless stated. Provenance is labelled `[V]` verified by running or reading the code,
`[S]` sourced but not re-proved, `[U]` uncertain.

---

## 1. The shape being generalised

On 2026-09-09 17:25 the `benchmarks_paper` book failed to arm on ANGL. The cause was
`IBKRBroker._foreign_book_claims()` (`src/deploy/broker/ibkr.py:743`), which globs
`ops/books/*.json`, treats every file carrying a list-shaped `sleeves` key as a live sibling book
in the shared paper account, and adds that book's whole universe to the symbols `arm()` may not
adopt from the account net. It tested neither `enabled` nor whether the book had ever held a
share. `credit_rv` was killed on 2026-07-30 and its spec stayed in that directory claiming 21
symbols, so a book dead for six weeks was still voting on attribution. `[V]` — the block is in
`ops/schedule/logs/benchmarks_2026-09-09.log`:

```
[ibkr] arm: BLOCKED ANGL: account holds +87 and bench_b6_ew_credit trades it,
       but so does another book and this sleeve's ledger has no entry
[2026-09-09 17:25:10] book run FAILED rc=3
```

The general shape is: **a directory scan on the live path that treats every entry it finds as
live, with no test that the entry is still real.** The rest of this note is every other instance
of that shape.

Two variants recur and are worth naming separately, because they need different fixes:

| variant | description | example here |
|---|---|---|
| **open scan** | a glob accepts whatever is in the directory | `_foreign_book_claims` |
| **closed list** | a hardcoded list enumerates what *should* be there and is therefore blind to what is | `doctor.JOBS` |

An open scan picks up a dead entry. A closed list fails to look at one. Both produce the same
outcome — an entry nobody has checked is treated as though someone had.

---

## 2. Ranked findings

Ranked by blast radius. "Live fault" means something is wrong right now; "latent" means the
mechanism is reachable but no dead entry currently sits in its path.

| # | site | enumerates | used for | dead entry reachable? | status |
|---|---|---|---|---|---|
| 1 | `src/deploy/broker/ibkr.py:766` | `ops/books/*.json` | symbols `arm()` may not adopt | **yes** — any `*.json` with a list `sleeves`; `enabled` never read | latent (was the 09-09 live fault; fixed by a file move, not by the code) |
| 2 | `ops/preflight.py:334` | `ops/books/*/_ibkr_shadow/*` | proves a book "has traded", suppressing the phantom-book warning | **yes** — archives and a preflight scratch root both vouch for a sleeve | **live fault** (false-negative surface open today) |
| 3 | `ops/preflight.py:385` | — | `except Exception: return Check(ok=True)` | n/a | **live fault** (a crashed guard reports PASS) |
| 4 | `ops/doctor.py:48` + `:84` | hardcoded `JOBS`, then `~/Library/LaunchAgents/com.quantt.<job>.*plist` | the only audit of what launchd will run | **yes** — two installed plists are outside `JOBS` and never examined | **live fault** (two unaudited plists installed today) |
| 5 | `ops/schedule/install.sh:61,72` | renders from templates against the *invoking* tree, copies to `~/Library/LaunchAgents` | installs a trading job | **yes** — would create a 4th job on the dev tree, outside the prod boundary and outside `doctor.JOBS` | latent |
| 6 | `~/Library/LaunchAgents/*.plist.bak-*` | 5 backup files carrying **live Labels** and a dead `WorkingDirectory` | — | **yes** under a directory-form `launchctl bootstrap` | latent |
| 7 | `ops/rebuild_ledger.py:218` | `next(<books_root>/../*_book.json)` | picks the book spec, then calls `br.arm()` | **yes** — silently defaults to `benchmarks_book.json` | latent |
| 8 | `src/deploy/registry.py` `_REGISTRY` | alloc types registered at import | `build_sleeve` | **yes** — `credit_rv_statarb` is registered and buildable although the strategy is killed | latent |
| 9 | `ops/reset_epoch.py:139` | `ops/specs/<--sleeve>.frozen.json`, name-built | epoch reseed universe | **yes** in principle; closed today by the ledger-existence guard at `:136` | latent |
| 10 | `ops/halt.py:207` | `ops/HALT_*.md`, non-recursive | advisory cross-book halt warnings | no — archive lives in `ops/halts/` | clean by design |
| 11 | `ops/doctor.py:189` | `ops/schedule/*.env` | env path check | no — filtered against `JOBS` at `:190` | clean by design |
| 12 | `ops/schedule/weekly_book_report.py:172` | four dry-run globs under `ops/books` | weekly report only | cosmetic | clean enough |
| 13 | `ops/specs/*.frozen.json` | **nobody globs this directory** | — | no — selection is by explicit `spec_path` | clean |
| 14 | `config/costs.yaml` `tickers` | 42 entries | membership test only | no — the check runs deployed→costs, never costs→deployed | clean |

---

## 3. Live faults today

### 3.1 `check_phantom_books` accepts archive directories and a preflight scratch root as proof of trading

`ops/preflight.py:334` builds the set of sleeves that "have traded" from

```python
for d in books_dir.glob(f"*/{shadow}/*"):
    if d.is_dir():
        traded.add(d.name)
```

The docstring at `ops/preflight.py:325` says the test is "has never held a share … tested
directly — a shadow sub-ledger directory". The glob does not distinguish a sub-ledger from an
archive of one, nor a live book root from a scratch root. `[V]`

```bash
python3 -c "from pathlib import Path; print('\n'.join(sorted(str(d.relative_to('ops/books')) for d in Path('ops/books').glob('*/_ibkr_shadow/*') if d.is_dir())))"
```

returns 17 directories: 7 live sub-ledgers, 9 archives, and 1 scratch-root entry. **10 of the 17 are not live sub-ledgers**:

| directory | what it actually is |
|---|---|
| `benchmarks_live/_ibkr_shadow/_pre_epoch_bench_b1_hyg_20260907_160249` | epoch archive, written by `ops/reset_epoch.py:213` |
| `benchmarks_live/_ibkr_shadow/_pre_epoch_bench_b3_agg_20260907_160249` | epoch archive |
| `benchmarks_live/_ibkr_shadow/_pre_epoch_bench_b4_60_40_20260907_161916` | epoch archive |
| `benchmarks_live/_ibkr_shadow/_pre_epoch_bench_b5_shy_20260907_160250` | epoch archive |
| `benchmarks_live/_ibkr_shadow/_pre_epoch_bench_b6_ew_credit_20260907_160250` | epoch archive |
| `benchmarks_live/_ibkr_shadow/_pre_epoch_bench_b6_ew_credit_20260907_162044` | epoch archive |
| `cef_live/_ibkr_shadow/_pre_epoch_cef_discount_20260907_155225` | epoch archive |
| `cef_live/_ibkr_shadow/_pre_epoch_cef_discount_20260908_170128` | epoch archive |
| `phase0_live/_ibkr_shadow/_prerebuild_null_trader_20260731_173307` | rebuild archive, `ops/rebuild_ledger.py:171` |
| `phase0_preflight/_ibkr_shadow/null_trader` | **a scratch root, not a live book** |

The last row is the one that bites. `phase0_preflight` is not a book root — no `*_book.json`
names it, and it carries no `_attribution.json`. Yet its `null_trader` directory puts
`null_trader` into `traded` on its own. If `phase0` were killed tomorrow and its live ledger
cleared, that scratch directory would keep vouching for the sleeve and `check_phantom_books`
would stay silent about a book that was once again claiming 14 symbols against the CEF book.

The nine archive directories are harmless *only* because timestamped names cannot collide with a
sleeve name. That is a property of the naming convention, not of the check.

**Blast radius.** This is the guard built today to catch the ANGL fault. It does not arm or size
anything itself, but it is the only automated detector of the finding-1 mechanism, and it is
currently capable of a false negative for `null_trader` specifically. `[V]`

```bash
python3 -c "import sys;sys.path.insert(0,'.');from ops import preflight as p;c=p.check_phantom_books();print(c.ok, c.detail)"
# True no dead books claiming symbols
```

**Fix.** Restrict the glob to directories whose name matches a sleeve declared by some
`ops/books/*.json`, and skip any name beginning with `_`; and take the book roots from the book
specs rather than from a glob over `ops/books/*/`, so a scratch root can never contribute.

### 3.2 A crashed `check_phantom_books` reports PASS

`ops/preflight.py:385`:

```python
except Exception as exc:
    return Check("phantom_books", True, f"not checked ({exc})")
```

`ok=True` on failure. This is a silent fallback of exactly the kind `CLAUDE.md` forbids: the
detector for the fault that halted a book yesterday degrades to "PASS" if anything inside it
raises, and the only trace is a parenthesis in a line whose left-hand side reads `[PASS]`. `[V]`

**Blast radius.** No order, but the whole value of the check is that a human reading preflight
output learns about a dead book. A PASS is read as "checked and clean".

**Fix.** Return `Check(..., False, ..., blocking=False)` on the exception path, so a check that
could not run shows as a warning rather than as a pass.

### 3.3 `ops/doctor.py` cannot see two installed plists

`ops/doctor.py:48` is a closed list:

```python
JOBS = ["cef", "benchmarks", "phase0", "collect", "watchdog", "weekly"]
```

and `_plist_path` (`ops/doctor.py:84`) only ever looks for `com.quantt.<job>.daily.plist` or
`com.quantt.<job>.plist` for a job in that list. Nothing enumerates `~/Library/LaunchAgents`.
`[V]`

`python3 -m ops.doctor --quick` prints six `plist:*` rows, all PASS. The directory holds 11
`com.quantt.*.plist` files: the 6 those rows cover, 3 non-job services (`awake`, `dashboard`,
`ibgateway`), and 2 that are never examined by anything: `[V]`

```bash
python3 -c "
import plistlib,glob,os
for p in sorted(glob.glob(os.path.expanduser('~/Library/LaunchAgents/com.quantt.*.plist'))):
    d=plistlib.load(open(p,'rb'))
    print(os.path.basename(p), d.get('ProgramArguments'), d.get('WorkingDirectory'))"
```

| plist | target | `WorkingDirectory` | in `doctor.JOBS`? |
|---|---|---|---|
| `com.quantt.book.daily.plist` | `/bin/bash /Users/simonjarvis/Desktop/QUANTT/2027/ops/schedule/run_after_close.sh` | `/Users/simonjarvis/Desktop/QUANTT/2027` | **no** |
| `com.quantt.book.weekly.plist` | `/bin/bash /Users/simonjarvis/Desktop/QUANTT/2027/ops/schedule/run_weekly.sh` | `/Users/simonjarvis/Desktop/QUANTT/2027` | **no** |

Both point at the pre-2026-08-31 repo path, which does not exist:

```bash
ls -la /Users/simonjarvis/Desktop/QUANTT/
# ls: /Users/simonjarvis/Desktop/QUANTT/: No such file or directory
```

Neither is currently loaded — `launchctl list | grep quantt` returns nine labels and neither
`com.quantt.book.daily` nor `com.quantt.book.weekly` is among them. `[V]` So they cannot fire
today, and the fault is one of coverage rather than of execution: **`doctor` reports every plist
resolving while two installed plists point at a directory that is gone.** That is precisely the
2026-09-01 fault class — a stale `WorkingDirectory` making launchd refuse to spawn with
EX_CONFIG 78, silently — against which `check_plists` was written, sitting in the same directory
the check reads, invisible because the check asks by name.

**Blast radius.** No order today. The exposure is that `doctor` is the outermost guard, run by
the watchdog, and its plist audit is not an audit of the plists — it is an audit of six names.

**Fix.** Enumerate `~/Library/LaunchAgents/com.quantt.*` and check every file found, reporting any
label outside `JOBS` as a WARN in its own right ("an installed job nobody expects").

**Unrelated but observed while running it:** `doctor --quick` also reports
`[FAIL] loaded:benchmarks last exit 3` with the fix hint "fix the plist". Exit 3 here is
`run_book`'s not-armed return from the ANGL block of 2026-09-09, not a plist fault, so the hint
points at the wrong thing. `[V]`

---

## 4. Latent hazards

### 4.1 `_foreign_book_claims` is safe today only because of a file move and two key shapes

`src/deploy/broker/ibkr.py:766` still globs every `*.json` in `ops/books/` and still reads
neither `enabled` nor any evidence of trading. The 2026-09-09 fault was closed by moving
`credit_rv_book.json` into `ops/books/retired/` (commit `26a5336`; the glob is non-recursive, and
`ops/books/retired/README.md` records the rule). The code is unchanged. `[V]`

What the glob returns today: `[V]`

```bash
python3 -c "
import json,glob
for p in sorted(glob.glob('ops/books/*.json')):
    s=json.load(open(p)).get('sleeves')
    print(p, type(s).__name__, len(s) if isinstance(s,(list,dict)) else '')"
```

| file | `sleeves` | read as a live sibling book? |
|---|---|---|
| `benchmarks_book.json` | `list[5]` | **yes** |
| `cef_discount_book.json` | `list[1]` | **yes** |
| `phase0_book.json` | `list[1]` | **yes** |
| `book_status_dryrun.json` | `dict` | no — only because `isinstance(sleeves, list)` fails |
| `dryrun_2026-07-29.json` | absent | no |
| `dryrun_2026-07-30.json` | absent | no |

Resulting claim sets, obtained by calling the real method on an instance built with
`__new__` so that `__init__` never runs and no socket is opened: `[V]`

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from src.deploy.broker.ibkr import IBKRBroker
for root, mine in (("ops/books/cef_live", ["cef_discount"]),
                   ("ops/books/phase0_live", ["null_trader"]),
                   ("ops/books/benchmarks_live", ["bench_b1_hyg","bench_b3_agg",
                    "bench_b4_60_40","bench_b5_shy","bench_b6_ew_credit"])):
    b = IBKRBroker.__new__(IBKRBroker)      # no __init__, no connect
    b._books_root, b._sleeves = root, dict.fromkeys(mine)
    c = b._foreign_book_claims(); print(f"{root:28s} N={len(c)} {sorted(c)}")
PY
```

```
ops/books/cef_live           N=19 ['AGG','ANGL','BKLN','EMB','HYG','IEF','IGSB','JAAA','JNK','LQD','SHY','SHYG','SJNK','SPHY','SPY','SRLN','USHY','VCIT','VCSH']
ops/books/phase0_live        N=29 ['AGG','ANGL','AWF','BIT','DSL','EMB','HYG','HYT','IEF','JFR','JNK','LQD','MHD','MQY','NAD','NEA','NVG','NZF','PCN','PDI','PDO','PFN','PHK','PTY','SHY','SHYG','SPY','USHY','VCIT']
ops/books/benchmarks_live    N=31 ['AWF','BIT','BKLN','DSL','EMB','HYG','HYT','IGSB','JAAA','JFR','JNK','LQD','MHD','MQY','NAD','NEA','NVG','NZF','PCN','PDI','PDO','PFN','PHK','PTY','SHYG','SJNK','SPHY','SRLN','USHY','VCIT','VCSH']
```

Every symbol above is claimed by a book that is genuinely live, so no claim is spurious today.
Three ways a dead entry re-enters:

1. **A disabled sleeve still claims.** The loop at `src/deploy/broker/ibkr.py:779-793` iterates
   `spec["sleeves"]` without reading `enabled`. Setting `"enabled": false` on a benchmark sleeve —
   the natural way to stand a book down without moving files — leaves every one of its symbols
   contested for the CEF book. All 8 sleeves across the three live books currently carry
   `enabled: true`, so this is not firing. `[V]`
2. **Non-book JSON already lands in `ops/books/`.** `book_status_dryrun.json` and two
   `dryrun_*.json` files sit in the scanned directory. They are skipped on key *shape*, not on any
   assertion that a file is a book spec. Anything that ever writes a `sleeves` list into that
   directory becomes a claimant.
3. **A newly killed book.** The rule that prevents this is a README, not a check. `[S]`

**Fix.** Require a positive marker rather than an absence — read `enabled`, and require a
`book_id` plus at least one sleeve with a ledger directory or attribution entry before a spec is
allowed to contest a symbol.

### 4.2 `install.sh` would install a fourth trading job on whatever tree it is run from

`ops/schedule/install.sh:53-62` renders `com.quantt.book.daily.plist` from the template by
substituting `__REPO__` with the tree the script lives in, and `:72` copies the result into
`~/Library/LaunchAgents`. The template (`ops/schedule/com.quantt.book.daily.plist.template`)
carries `Label = com.quantt.book.daily`, fires weekdays at `__HOUR__:__MINUTE__` (default 16:40)
and runs `__REPO__/ops/schedule/run_after_close.sh`. `[V]`

Run from this tree with `--install` or `--enable`, that installs a job that:

- runs the **dev** tree, bypassing the `REPO = Path("/Users/simonjarvis/prod/QUANTT")` boundary at
  `launch_job.py:71` entirely;
- fires at 16:40, ahead of the 17:15 `cef` and 17:25 `benchmarks` jobs, so it contends for the
  same TWS session;
- carries a label outside `doctor.JOBS`, so finding 3.3 means `doctor` would not report it.

This is also how the two stale plists of 3.3 got there. They are **byte-for-byte identical** to
the files in `ops/schedule/rendered/`, so they are that directory's contents, installed: `[V]`

```bash
for p in com.quantt.book.daily.plist com.quantt.book.weekly.plist; do
  diff -q ~/Library/LaunchAgents/$p ops/schedule/rendered/$p && echo "$p identical"; done
# com.quantt.book.daily.plist identical
# com.quantt.book.weekly.plist identical
```

The installed copies are dated 24 July and the repo copies 28 July. Why the repo copies were
touched four days later I did not establish `[U]`; the bytes are the same either way, so both
carry the old `__REPO__` substitution.

**Fix.** Have `install.sh` refuse unless the tree it is rendering equals `REPO` in
`launch_job.py`, and add `book` to `doctor.JOBS` so the artefacts it produces are audited.

### 4.3 Backup plists carry live labels and a dead working directory

Five files in `~/Library/LaunchAgents` are named `com.quantt.*.plist.bak-*`. **All five carry a
`Label` identical to a job that is loaded right now**, and four of them also carry a
`WorkingDirectory` of `/Users/simonjarvis/Desktop/QUANTT/2027`, which does not exist: `[V]`

| file | `Label` | `WorkingDirectory` |
|---|---|---|
| `com.quantt.collect.daily.plist.bak-20260901` | `com.quantt.collect.daily` | `/Users/simonjarvis/Desktop/QUANTT/2027` |
| `com.quantt.phase0.daily.plist.bak-20260901` | `com.quantt.phase0.daily` | `/Users/simonjarvis/Desktop/QUANTT/2027` |
| `com.quantt.watchdog.daily.plist.bak-20260901` | `com.quantt.watchdog.daily` | `/Users/simonjarvis/Desktop/QUANTT/2027` |
| `com.quantt.weekly.plist.bak-20260901` | `com.quantt.weekly` | `/Users/simonjarvis/Desktop/QUANTT/2027` |
| `com.quantt.awake.plist.bak-20260908` | `com.quantt.awake` | none |

A per-file `launchctl bootstrap` names a file and cannot reach these. A directory-form bootstrap
of `~/Library/LaunchAgents` is the exposure, and whether launchd's directory form picks up files
not ending in `.plist` I did not verify on this machine `[U]`. What is certain is that
`doctor._plist_path` matches only `.plist` and `.daily.plist`, so if a `.bak` ever were loaded,
`doctor` would report PASS against the *good* file while the bad one was the loaded service —
the same shape as 3.3. `[V]`

**Fix.** Move backups out of `~/Library/LaunchAgents` (they are configuration, not history, and
git already holds the templates); failing that, have `doctor` warn on any `com.quantt.*` file in
that directory that is not a checked plist.

### 4.4 `rebuild_ledger` picks the alphabetically first book spec, then arms

`ops/rebuild_ledger.py:218`:

```python
book = next(Path(a.books_root).resolve().parent.glob("*_book.json"))
for cand in Path(a.books_root).resolve().parent.glob("*_book.json"):
    spec = json.loads(cand.read_text())
    if any(s.get("name") == a.sleeve for s in spec.get("sleeves", [])):
        book = cand
        break
```

The default is whatever the glob yields first, which is alphabetical: `[V]`

```bash
python3 -c "
from pathlib import Path
for r in ('cef_live','phase0_live','benchmarks_live'):
    c=sorted(Path('ops/books/'+r).resolve().parent.glob('*_book.json'))
    print(f'{r:16s} next() -> {c[0].name}  out of {[x.name for x in c]}')"
```

```
cef_live         next() -> benchmarks_book.json  out of ['benchmarks_book.json', 'cef_discount_book.json', 'phase0_book.json']
phase0_live      next() -> benchmarks_book.json  out of [...]
benchmarks_live  next() -> benchmarks_book.json  out of [...]
```

The loop corrects this whenever `--sleeve` names a sleeve that some book declares. It does **not**
correct it when `--sleeve` names a sleeve no live book declares — a retired one, or a typo. The
fallback then wires `benchmarks_book.json` against a `--books-root` belonging to a different book
and calls `br.arm()` at `:231`. Reachable only via `--check-broker`, and only when a human runs it;
I did not run it, as `ops/rebuild_ledger.py` is guard-blocked. `[V]` for the glob result, `[S]` for
the arm consequence.

**Fix.** Delete the `next()` default and raise if the loop finds no book declaring `--sleeve`,
naming the sleeve and the candidates searched.

### 4.5 A killed strategy's sleeve class is still registered and buildable

`src/deploy/registry.py` resolves an `allocation.type` through `_REGISTRY`, populated by the
`@register` decorator as `src/deploy/sleeves/__init__.py` imports each module. That file still
imports `credit_rv`. `[V]`

```bash
python3 -c "
import sys;sys.path.insert(0,'.')
from src.deploy import registry as r, sleeves
print('registered:', sorted(r.registered_types()))"
# registered: ['cef_discount', 'credit_rv_statarb', 'null_trader', 'static_weights']
```

A book spec declaring `credit_rv_statarb` validates through `_validate_credit_rv` and builds a
working `CreditRVSleeve`, although the strategy was killed on 2026-07-30 for a negative gross edge
and a sealed-holdout net Sharpe of −1.44 (`ops/books/retired/README.md`). `[S]`

Worth recording that `registry.py` was edited by another agent while this audit was running; the
version read at 11:40 adds `UNIMPLEMENTED_ALLOC_TYPES` and refuses those types early in
`validate_spec` (`src/deploy/registry.py:57,145`). `credit_rv_statarb` is deliberately **not** in
that set — it is implemented, merely dead — so this finding stands against the edited file. `[V]`

**Fix.** Add a `retired` marker beside `UNIMPLEMENTED_ALLOC_TYPES` and have `validate_spec` refuse
a retired type with the kill date and reason, so reviving one is an explicit edit rather than a
spec that quietly works.

### 4.6 `reset_epoch` builds a spec path from an argument

`ops/reset_epoch.py:139` constructs `ops/specs/<--sleeve>.frozen.json` by name, so
`--sleeve credit_rv` would load the retired frozen spec. It is closed today by the check three
lines earlier (`:136`) that the sub-ledger exists, and no `_ibkr_shadow/credit_rv` directory
exists anywhere under `ops/books/`. `[V]` The residual case is `--books-root ops/books/phase0_preflight
--sleeve null_trader`, which passes the existence check against a scratch root. Low radius; the
tool is guard-blocked and human-run.

**Fix.** Resolve the spec through the book spec's `spec_path` rather than by filename.

---

## 5. Scans proved clean

| site | why it is safe |
|---|---|
| `ops/specs/*.frozen.json` | **Never globbed by anything.** Every spec is selected by an explicit `spec_path` in a book JSON. `credit_rv.frozen.json` and `cef_discount.frozen.json.bak-20260906` are unreachable. |
| `ops/halt.py:207` | `(REPO_ROOT/"ops").glob("HALT_*.md")` is non-recursive and the archive is `ops/halts/`, so a cleared halt cannot reappear as an active one. Returns `[]` today; `ops/HALT.md` absent. |
| `ops/doctor.py:189` | Globs `ops/schedule/*.env` but filters on `env.stem not in JOBS` at `:190`, so the dead `schedule.env` is skipped. Verified: `benchmarks.env`, `cef.env`, `phase0.env` CHECKED; `schedule.env` SKIPPED. |
| `config/costs.yaml` | The check runs deployed→costs (`ops/preflight.py:132-140`), never the reverse, so extra entries are inert. |
| `ops/capture_fills.py` | Sleeve universes come from the book spec's **enabled** sleeves, not from a directory scan. |
| `dashboard/server.py` | Books and sleeves come from the `BOOKS` and `LABEL` dicts at `:65,74`; `BENCH_ROOT` at `:69` is only ever indexed by a key from `BENCH_LABEL`, never listed. |
| `scripts/cef/{fetch_daily,wait_for_nav,fetch_borrow_rates}.py`, `scripts/holdings/*` | The five scripts `launch_job.py` actually invokes contain no glob, rglob, listdir or walk. |
| `launch_job.py` `JOBS` / `COLLECTORS` | Both are explicit literals (`:123`, `:162`) with no directory scan. `main()` rejects an unknown job at `:197`. `COLLECTORS` reports `MISSING` and counts a failure for a script that does not exist (`:429-432`) rather than skipping silently. |

### `ops/specs` selection, proved

```bash
python3 -c "
import json,glob
from pathlib import Path
sel={s['spec_path'] for p in glob.glob('ops/books/*.json')
     for s in (json.load(open(p)).get('sleeves') or [])
     if isinstance(s,dict) and s.get('spec_path')}
for p in sorted(Path('ops/specs').iterdir()):
    print(f'{p.name:40s} {\"SELECTED\" if \"ops/specs/\"+p.name in sel else \"never selected\"}')"
```

| file | status |
|---|---|
| `bench_b1_hyg.frozen.json` … `bench_b6_ew_credit.frozen.json` (5) | SELECTED |
| `cef_discount.frozen.json` | SELECTED |
| `null_trader.frozen.json` | SELECTED |
| `cef_discount.frozen.json.bak-20260906` | never selected |
| `credit_rv.frozen.json` | never selected |

### `config/costs.yaml` coverage

```bash
python3 -c "
import sys,yaml;sys.path.insert(0,'.')
from ops import preflight as p
have=set(yaml.safe_load(open('config/costs.yaml'))['tickers']); dep=set()
for b in ('cef_discount_book.json','phase0_book.json','benchmarks_book.json'):
    for _,i in p.deployed_tickers('ops/books/'+b).items(): dep|=set(i)
print(len(have), len(dep), sorted(dep-have), sorted(have-dep))"
```

42 cost entries, 36 deployed tickers, **0 deployed without a cost entry**, and 6 entries no live
book deploys: `BIL`, `FALN`, `TLT`, `ZB`, `ZF`, `ZN`. Those six are dead, but the direction of the
check makes them unreachable rather than dangerous.

---

## 6. Verifying the `CLAUDE.md` claim about `ops/schedule/rendered/`

`CLAUDE.md` landmine 2 states that the rendered plists are stale, point at the old path, and are
not what runs. Checked both ways.

**Are they stale, and does anything read them at run time?** Yes and no, respectively. All four
files in `ops/schedule/rendered/` name `/Users/simonjarvis/Desktop/QUANTT/2027`, which does not
exist. `[V]` Nothing on the live path reads that directory: the only writers are
`ops/schedule/install.sh:61-62` and `ops/schedule/install_backup.sh`, which deliberately renders
into `rendered_backup/` instead and says why at `:23`. Every loaded QUANTT job runs
`/opt/anaconda3/bin/python3 <launch_job.py> <job>` directly. `[V]`

**But the claim is incomplete in one respect worth recording.** `install.sh --install` copies two
of those rendered files into `~/Library/LaunchAgents`, and two such copies are sitting there now
(finding 3.3). So "the rendered plists are not what runs" is true of the directory and false of
its contents: `com.quantt.book.daily.plist` and `com.quantt.book.weekly.plist` are byte-for-byte
identical to the files in `ops/schedule/rendered/`, are installed, and are outside every check
this repo has.
They are inert today only because the path they name is gone and neither is loaded.

Loaded jobs, for the record: `[V]`

```bash
launchctl list | grep quantt
```

| label | last exit | fires |
|---|---|---|
| `com.quantt.cef.daily` | 0 | weekdays 17:15 |
| `com.quantt.benchmarks.daily` | **3** | weekdays 17:25 |
| `com.quantt.phase0.daily` | 0 | weekdays 09:35 |
| `com.quantt.collect.daily` | 0 | weekdays 18:30 |
| `com.quantt.watchdog.daily` | 0 | weekdays 19:30 |
| `com.quantt.weekly` | 0 | Saturday 09:00 |
| `com.quantt.awake` | running | weekdays 09:00 |
| `com.quantt.ibgateway` | running | — |
| `com.quantt.dashboard` | running | — |

`com.quantt.book.daily` and `com.quantt.book.weekly` do not appear.

---

## 7. What I could not check

Four commands were refused by `.claude/hooks/guard_order_path.py` and were not rewritten:

| wanted to run | why | how the fact was obtained instead |
|---|---|---|
| `cat "~/Library/Application Support/quantt/launch_job.py"` | read `JOBS` and `COLLECTORS` | read with the read-only Read tool |
| `sed -n ... ops/halt.py` / `ops/rebuild_ledger.py` / `ops/reset_epoch.py` | read the glob sites | read with the read-only Read tool |
| `ls .../ops/schedule/run_after_close.sh` | test whether the old wrapper still exists | listed the parent directory, which does not exist at all |
| `grep -n ... src/deploy/run_book.py` | read the sleeve loop | read with the read-only Read tool |

The hook matches on the path string appearing anywhere in a Bash command, including in a pure
read. That is the safe direction, and it is worth knowing that it makes `grep` and `sed` unusable
on five live-path Python files and the `ops/schedule/*.sh` wrappers, so an audit of those has to
go through the read-only Read tool.

---

## 8. Summary

The fault that halted `benchmarks_paper` yesterday has been closed by moving one file. The
mechanism that produced it — `src/deploy/broker/ibkr.py:766` — is unchanged, and three routes back
into it remain (a disabled sleeve, a non-book JSON in `ops/books/`, and the next killed book).
The guard written today to detect it, `check_phantom_books`, accepts an epoch archive or a
preflight scratch directory as proof that a sleeve has traded, and reports PASS if it crashes.

Separately, and of comparable seriousness for uptime rather than for arming: `ops/doctor.py`
audits six plists by name against a directory holding 11, and the two stale ones it cannot see
point at a repo path deleted on 2026-08-31. They are inert today only by accident of that deletion, and
`ops/schedule/install.sh` will happily install two more against whatever tree it is run from.

Nothing in this audit changed any file.
