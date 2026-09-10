# W0 — repo hygiene, 2026-09-10

**Scope of this note: Parts A and E**, plus the document corrections those parts
made necessary. Parts B, C, D, F and G were worked in a parallel session on the
same branch; where its commits overlap this one, they are named below rather than
duplicated. Trials spent: **zero**. No frozen-spec key changed.

---

## Part A — the stale baseline, which is the item that silently produces wrong answers

### What was wrong

Five analysis scripts baselined against `band(T, 0.064)`. The live band has been
**4.8%** since 2026-09-06, and 6.4% is specifically the width that was
**deliberately not chosen** — it topped the swept column, and picking the argmax
of a sweep is how `z_window = 63` was selected and failed out of sample.

| script | sites | named in |
|---|---:|---|
| `joint_cost_optimiser.py` | 5 calls, 4 labels | W11, W12 |
| `covariance_construction.py` | 1 | W12, W8, F3 |
| `borrow_impact.py` | 2 | W8 |
| `ou_score.py` | 1 | F2 |
| `band_frontier.py` | — (6 spec-owned constants) | the canonical harness |

Nothing errored. Every result was simply measured against a book nobody runs, off
by the difference between two policies — which is the size of the effects those
prompts exist to detect. Because all five are named in prompts as things to
extend, the error was positioned to propagate into new work indefinitely.

`band_frontier.py` had the deeper version: `UNIVERSE`, `Z_WINDOW`, `VOL_TARGET`,
`MIN_ADV`, `MIN_NAMES` and `GROSS_LEVERAGE` were module constants that *happened
to agree* with the spec. Happening to agree stops being true at the next bump.

Three scripts also printed **"calendar 2d (LIVE)"** four days after the band
replaced the calendar. A label that can go stale silently is the same bug one
layer up.

### The fix

`scripts/cef/spec.py` is now the single reader of the frozen spec. Every accessor
raises `SpecError` naming the missing key — a default there would reintroduce the
same bug one layer down. `LIVE_POLICY` is derived, so the LIVE tag follows the
spec rather than asserting a policy.

**Proved a numerical no-op** where it should be one: `band_frontier` output
diffed byte-for-byte against the pre-change run. Every figure identical; only the
LIVE marker moved.

### What actually changed, and it is not only labels

**1. The joint optimiser's edge is larger than published.** It was matched
against the retired band at *that* band's turnover.

| | vs retired 6.4% @ 14.2/yr | vs live 4.8% @ 17.6/yr |
|---|---|---|
| net@5bp | 1.19 vs 0.98 (+0.21) | **1.26 vs 1.00 (+0.26)** |
| net@15bp | 0.91 vs 0.71 (+0.19) | **0.91 vs 0.67 (+0.24)** |
| net@30bp | 0.48 vs 0.31 (+0.16) | **0.39 vs 0.17 (+0.22)** |
| derived `c_model` | 25.4bp | **20.1bp** |

`c_model` moved because it is solved to match the baseline's turnover and the
baseline's turnover changed. **The "why not deployed" argument is untouched** —
it rests on turnover stability (36.9% vs 11.9% sd/mean) and the ADV fork.

**2. The borrow attribution was computed on the wrong book.** `borrow_impact.py`
apportioned the bill across `calendar(T, 2)`'s average short weights. Borrow
scales with **holdings**, and the band holds a different book.

| | calendar (retired) | band (live) |
|---|---:|---:|
| HYT | 29.9% | 28.2% |
| NAD | 28.0% | 27.1% |
| NVG | 12.5% | 12.1% |
| JFR | 2.3% | **3.7%** |
| AWF | 1.7% | **2.8%** |
| **top three** | **70.4%** | **67.4%** |

Ranking stable, conclusion unchanged — the bill is still concentrated in
HYT/NAD/NVG, two of them the Nuveen munis carrying PC2 — but the widely-quoted
"three names are 70% of the cost" is **67.4%**.

**3. A block was violating the rule it demonstrates.** `band_frontier`'s
matched-turnover table paired calendar 5d (17.6 turn/yr) with band 6.4% (14.2) —
a **19% mismatch**, in the block whose purpose is demonstrating H2's 5% rule.
Against the live band the match is exact at 17.6, and the band wins both legs:
gross 1.17 vs 0.85, net@15bp 0.67 vs 0.35.

### The guard

`scripts/cef/tests/test_spec_is_single_source.py` fails the build if a `band()`
call takes a bare float, or if a converted script reads the spec JSON directly
again.

**The first version of that guard was wrong, and the failure is the lesson.** It
flagged any literal equal to a spec value — so `np.sqrt(252)` tripped
`z_window = 252`, and `vol_target = 0.06` collided with unrelated sixes. A
value-equality check cannot distinguish two quantities that happen to share a
number, and a test with false positives gets deleted rather than fixed. It now
checks the **argument position** of a `band()` call, which is where the bug lived
and is unambiguous. Deliberate sweeps stay legal; a row that labels its own width
is exempt.

---

## Part E — stale data, and the discipline that stops it recurring

### Measured

| file | last data | behind prices | feeds |
|---|---|---:|---|
| `cef_prices.parquet` | 2026-09-09 | 0 | the signal |
| `cef_nav.parquet` | 2026-09-09 | 0 | the signal |
| `cef_borrow.csv` | 2026-09-10 | 0 | short-side sizing |
| `cef_distributions.parquet` | 2026-07-24 | **32 sessions** | W4 return convention, W9 ex-date calendar |
| `etf_ohlc.parquet` | 2026-07-29 | **29 sessions** | W10/W13 ETF proxies, gamma/G3 |
| `etf_daily.parquet` | 2026-07-20 | **36 sessions** | the frozen backtest panel (deliberate) |
| `cef_facts.csv` | — | **no date column** | per-fund attributes |

### The fix

`ops/doctor.py` gained `check_panels`. Preflight already gates the two panels the
*session* cannot trade without and refuses to arm on a stale pair. This is the
other half: the panels **research** depends on, which no session blocks on, and
which therefore rot quietly. A script joining a 32-session-old distribution panel
to a current price panel does not fail — it silently applies the wrong correction,
or none, and returns a number.

**WARN, never FAIL.** A stale research panel does not stop the book trading
tonight, and doctor's FAIL means "unattended operation is broken right now".
Overloading it would train the operator to ignore FAIL — which is exactly how a
21-session outage went unnoticed while preflight blocked correctly every session.
A test pins that distinction.

### `cef_facts.csv` — the dangerous one

A single yfinance `.info` snapshot with no history. **13 of its 46 columns are
100% null** (`netAssets`, `netExpenseRatio`, `fundFamily`, `fundInceptionDate`
among them) and `quoteType`/`typeDisp`/`sector`/`industry` are **constant across
all 44 rows**, so most of what reads as per-fund data is not. Joining it to the
27-year panel applies today's attributes to 2005 — look-ahead with no error
message.

- The **fetcher** now stamps `fetched_at` and its docstring says in the output
  list that this is a dated snapshot, not a panel. That is the part that persists.
- The **local file** is stamped from its own mtime, `2026-07-31T16:43:19`, which
  `_raw_info.json` corroborates to the second. `data/` is gitignored, so any other
  machine's copy will warn until re-fetched.
- Provenance lives in a separate `fetched_at_source` column. The first attempt put
  `[inferred from file mtime]` inside the timestamp and made it unparseable, which
  would have left the check passing on a column it could not read.

### One bug in the new check, caught by its own tests

`pd.to_datetime` reads a bare integer as **nanoseconds since epoch**, so a column
named `date` holding `3` returns `1970-01-01`. The check would have confidently
reported a panel as ~20,000 sessions stale — or, for the right integer, as
current. **A monitor that commits the silent-wrong-answer bug it exists to catch
is worse than no monitor.** It now requires a plausible date window and tries
every date-like column before giving up. `fetched_at` counts as a date column and
is preferred over a content date, because for a snapshot the stamp *is* the date.

---

## Documents amended, per "if a number moves, the note that quoted it is now wrong"

| file | change |
|---|---|
| `docs/PLAN.md` | borrow table re-measured on the live band; dated correction note |
| `docs/SYSTEM_AND_STRATEGY.md` §5.2 | 70% → ~67%, with the reason |
| `docs/SYSTEM_AND_STRATEGY.md` §5.3 | **capacity flagged DISPUTED** (see below) |
| `docs/SYSTEM_AND_STRATEGY.md` §8.1 | joint-optimiser figures re-measured |
| `docs/prompts/W12` | told a future agent to match at 14.2/yr — the retired rate. Now reads it from `spec.py`, per H14 |
| `.claude/agents/{execution-trader,equity-research,portfolio-manager,dashboard-designer}.md` | same corrections in the seats that quote them |

Every correction is **dated and in place**, not a silent edit — someone is
relying on the old number somewhere.

---

## Still open

**Borrow availability is disputed and nothing may be sized on it.** Found in the
parallel session (`38b4d4a`). The public `shortstock` file was retired
2026-09-09; TWS tick 236 had been returning NaN under error 10197 because the
dashboard opened a broker session per widget refresh. With that fixed, the two
sources disagree by **28×** on NAD — 3,000 shares vs 83,942. On the file's pools
18.7% of the short book is unbuildable; on the tick's, **0%**. **W8 Part A** owns
the resolution with a week of paired observations. Flagged in the brief, W8,
`SYSTEM_AND_STRATEGY` §5.3 and three agent seats.

**Two panels are still stale.** `cef_distributions` (32 sessions) and `etf_ohlc`
(29). Not refreshed here deliberately: refreshing changes data other work is
mid-flight on, and W0 is explicit that a refreshed panel obliges amending every
note that quoted the old one. Doctor now says so on every run, which was the
missing part. `etf_daily.parquet` is stale **by design** — it is the frozen
backtest reference and is never modified.

**`joint_cost_optimiser.py`'s docstring** still works its `c_model ≈ c_exec/(IC·H)`
example to "about 24bp, and the value that independently matches is 25.2bp". The
match value is now 20.1bp. Correcting the worked example needs `IC` and `H`
re-measured, which belongs with W12 rather than here.

**Six other scripts read the frozen spec directly** (`dust_check`,
`open_holdout`, `reconcile_prices`, `fetch_borrow_rates`, `fetch_borrow_history`,
and `dashboard/server.py`). W0 says nothing should open that JSON twice. They read
it for live-ledger and fetch purposes rather than as research baselines, so they
are not the bug this part was closing; the guard test allow-lists them explicitly
so the exemption is visible rather than forgotten.

---

## Test coverage

Suite went **115 → 219**, and for the first time `ops/` has tests at all.

| added | covers |
|---|---|
| `.claude/hooks/tests/` (57) | the order-path guard |
| `scripts/cef/tests/` (29) | the spec single-source rule |
| `ops/tests/` (7) | doctor's panel check |

`pytest.ini` also now scopes collection. Before it, a bare `python3 -m pytest`
failed at **collection** with `ConnectionRefusedError`, because
`scripts/audit/moc_routing_test.py` matches pytest's default discovery pattern and
opens a live broker connection at import — the safest-looking command in the repo
reached for the order path.
