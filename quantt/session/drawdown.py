"""The book's drawdown from its high-water mark, against the frozen spec's HALVE and KILL lines. Report mode only.

THE DEFECT (results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md §1 item 4 and §3.4)
----------------------------------------------------------------------------
The frozen spec has carried `risk.halve_drawdown` and `risk.kill_drawdown` since
v5, and the standing decision is to arm HALVE/KILL on broker-confirmed NAV (team
lead, 2026-09-08; docs/SYSTEM.md §5). On the Alpaca path nothing read either key,
and the runner never called any sleeve's `risk_check`. That sleeve method writes
0.18 and 0.12 as literals, and on an exception returns OK, a silent fallback.
Re-verified on 2026-10-19 at main 832aeaa: no `.py` under `quantt/`, `src/` or
`ops/` named either key, and nothing in the repository called `risk_check(`.
A survival line wired to nothing looks armed and is not. The deployed book's own
fit-window drawdown, 12.78% (2017-06 -> 2018-06; that note §1), would have
crossed the 12% HALVE line.

WHAT THIS IS (team lead, 2026-10-19: report mode first)
------------------------------------------------------
At every DECIDE the runner (quantt/session/run.py, step 2b) asks `check` for the
book's drawdown from its high-water mark on the official daily equity series,
compares it with the two lines, and records the result, together with what an
`on` mode WOULD do, in plan.json and the run record (`drawdown`). It also prints
it to the session log (`lines`). Nothing that trades reads the result. The
orders, the plan_sha and plan.json are a check-off session's, byte for byte,
apart from the added `drawdown` record. quantt/session/tests/test_drawdown.py
proves it on the live spec, the real sleeve and the real panel. This is the
stale-NAV gate's report-mode design (quantt/session/nav_gate.py, 2026-10-13),
reused.

THE SERIES: `<state>/eod_equity.csv`, never `equity.csv`
-------------------------------------------------------
Team lead, 2026-10-19: Alpaca's end-of-day portfolio history
(`GET /v2/account/portfolio/history`, timeframe 1D) is the OFFICIAL daily P&L.
The collector writes it to `<state>/eod_equity.csv` and backfills it from
2026-09-28. Its header has `date`, `equity` and `change_usd`, possibly with
extra columns after them, and `change_usd` is empty on the first funded row.
This module reads two columns BY HEADER NAME, `date` (YYYY-MM-DD) and `equity`
(USD). `change_usd` and every other column are never read, so an empty cell or an
added column cannot break the check.
  * Why not `equity.csv`. Its rows are account SNAPSHOTS, taken by the collector
    after the close on after-hours marks. A snapshot can set a high-water mark
    the book never closed at, and every later drawdown would then be measured
    from a number that never existed at a close. The day-on-day changes differ
    materially: 2026-10-05 snapshot +$1,068.53 against Alpaca's EOD +$126.05,
    2026-10-16 +$242.56 against +$160.58 (figures as relayed from the session
    that built eod_equity.csv, 2026-10-19 [S]).
  * eod_equity.csv absent or unreadable -> UNMEASURED, naming the file. There is
    NEVER a fallback to equity.csv (CLAUDE.md: no silent fallbacks).
  * The snapshot is still SHOWN, as a second line explicitly labelled as
    snapshots and not the check's input (`snapshot` in the record). It never
    changes the status. It is there because, until eod_equity.csv ships (a
    hotfix release, week of 2026-10-19), it is the only equity history on the
    VM, and a reader should see both.

THE MEASURE
-----------
  HWM       the largest `equity` over every row dated on or before the as-of
            date (its first date is reported);
  drawdown  1 - (equity of the newest such row) / HWM, a fraction >= 0;
  STATUS    KILL if drawdown >= kill_drawdown, else HALVE if >= halve_drawdown,
            else OK. UNMEASURED when it cannot be measured (below).
NO LOOKAHEAD: the decide on as-of date D (evening of D, or the morning backstop
on D+1) may use the EOD equity of D and earlier, never later. Rows dated after D
are dropped before anything is computed, and that is asserted. The newest row
must BE D. A series that ends before D is UNMEASURED and says so; the stale
figures are still recorded, labelled with their own date. Whether the EOD row
for D exists by the 22:00 ET evening decide is not established [U]: report mode
measures it.
The record also gives the worst drawdown in the series and the first date each
line was crossed. A STICKY `on` (below) would still be holding a line crossed
earlier, even after the book recovered above it.

THE LEVELS: the frozen spec, through the live path's own read
------------------------------------------------------------
`levels(spec)` reads `risk.halve_drawdown` and `risk.kill_drawdown` from the spec
dict that run.py's `load_spec` loaded (the live path reads the spec directly,
never through `scripts/`), never a literal. UNITS: a drawdown line is a FRACTION
of the high-water mark, in (0, 1), and halve < kill. A value >= 1 is a percent
written where a fraction belongs. That is the units trap that once made
`book_drawdown_suspend_pct` = 0.99 the tightest live limit in the book
(.claude/skills/spec-change). It is refused, never rescaled.

MODES (`MODES`; the book json's `risk.drawdown`; absent = off, run.drawdown_for)
------------------------------------------------------------------------------
  report   measure, record and print. It never blocks, never changes an order.
           An unexpected error is recorded as UNMEASURED with its type, and the
           session goes on (run.py `_drawdown`), as the stale-NAV gate's report
           mode does.
  on       NOT BUILT. Setting it raises; it needs the team lead's ruling.
What an `on` mode would do is recorded each session (`would_on`, `WOULD_ON`):
  HALVE       size every sleeve on half its budget, which halves the vol target,
              and keep that until the team lead records a review (STICKY: never
              restored automatically on recovery, framework §3.4, because
              re-levering on recovery whipsaws exactly when risk pays least);
  KILL        flatten every sleeve through the normal order path (every gate
              still applies), then write ops/HALT_cef.md; the team lead restarts.
              The halt must follow the flatten's send, or the halt gate would
              refuse the flatten;
  UNMEASURED  REFUSE THE DECIDE (a named `risk` refusal: nothing is sent, and
              verify reads the day as a MISSED FAIL).
WHY UNMEASURED SHOULD BLOCK UNDER `on` (the decision this docstring was asked to
make). A survival stop that fails open is the defect this module replaces: lines
that looked armed for months while nothing read them, and a `risk_check` that
returned OK on an exception. Failing closed costs one missed day. The desk
already shows a missed day loudly (MISSED FAIL in verify, orient and the status
line), and the cure is in our own hands (the collector backfills the file).
Failing open costs an unbounded drawdown, unseen. The trade-off accepted: a
refused day cannot reduce risk either. The alternative for the ruling is a
close-only day, which sends reductions only. That needs new order-path code, so
it was not chosen as the default.
In report mode UNMEASURED never blocks: that is the definition of report mode.

NOT HANDLED, AND WHY IT MATTERS BEFORE `on` ON REAL MONEY
---------------------------------------------------------
Deposits and withdrawals move equity without P&L. Alpaca paper has none, so the
HWM here is not flow-adjusted. A real-money `on` mode must adjust for flows, for
example from the account's CSD/CSW activities, before it can act.

H14: no number from a document is keyed on. The levels come from the frozen
spec, the equity from the broker's own series, both read at run time and
recorded with their source.

Standard library only at module level (pytest.ini; the send path never imports
`scripts/`).
"""
from __future__ import annotations

import csv
import datetime as dt
import math
from pathlib import Path

REPORT = "report"
MODES = (REPORT,)                   # `on` is deliberately absent: not built (docstring)

OFFICIAL_FILE = "eod_equity.csv"    # Alpaca EOD portfolio history, 1D: the official series
SNAPSHOT_FILE = "equity.csv"        # the collector's after-hours account snapshots: shown, never used
READ_COLUMNS = ("date", "equity")   # the ONLY columns read, by header name, from either file

OFFICIAL_LABEL = ("eod_equity.csv: Alpaca end-of-day portfolio history (1D), the official "
                  "daily P&L (team lead 2026-10-19)")
SNAPSHOT_LABEL = ("equity.csv: the collector's after-hours account snapshots; shown for "
                  "comparison, NOT the check's input")

OK, HALVE, KILL, UNMEASURED = "OK", "HALVE", "KILL", "UNMEASURED"
LEVEL_KEYS = (("halve", "halve_drawdown"), ("kill", "kill_drawdown"))

WOULD_ON = {
    OK: "nothing",
    HALVE: ("halve: size every sleeve on half its budget (vol target halved), held until "
            "the team lead records a review (sticky)"),
    KILL: ("kill: flatten every sleeve through the normal order path, then write "
           "ops/HALT_cef.md; the team lead restarts"),
    UNMEASURED: "refuse the decide: a named `risk` refusal, nothing sent (verify: MISSED)",
}


class Unmeasured(Exception):
    """The drawdown cannot be measured. The message names the file, line or spec key."""


def levels(spec: dict) -> dict:
    """{"halve": f, "kill": f, "source": ...} from the frozen spec's `risk` block.

    Units-checked (module docstring, THE LEVELS): each must be a finite number in
    (0, 1), a fraction of the high-water mark, and halve < kill. Anything else
    raises `Unmeasured` naming the key. It is never rescaled and never defaulted."""
    risk = spec.get("risk")
    if not isinstance(risk, dict):
        raise Unmeasured("frozen spec has no `risk` block")
    out = {}
    for name, key in LEVEL_KEYS:
        if key not in risk:
            raise Unmeasured(f"frozen spec has no risk.{key}")
        v = risk[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise Unmeasured(f"frozen spec risk.{key} is {v!r}, not a finite number")
        if not 0 < v < 1:
            raise Unmeasured(
                f"frozen spec risk.{key} is {v!r}: a drawdown line is a FRACTION of the "
                f"high-water mark, in (0, 1); {v!r} reads as a percent (the units trap, "
                f".claude/skills/spec-change). Refused, not rescaled")
        out[name] = float(v)
    if not out["halve"] < out["kill"]:
        raise Unmeasured(f"frozen spec risk.halve_drawdown {out['halve']} is not below "
                         f"risk.kill_drawdown {out['kill']}")
    out["source"] = f"{spec.get('spec_id')} risk.halve_drawdown / risk.kill_drawdown"
    return out


def read_series(path: Path, asof: dt.date) -> list:
    """[(date, equity)] from `path`, rows dated on or before `asof`, oldest first.

    Reads `date` and `equity` by header name and nothing else (READ_COLUMNS), so
    an empty `change_usd` or an added column changes nothing. Raises
    `Unmeasured`, naming the file and line, on: no file, a file that cannot be
    read (a directory, no permission, not text), no header, a header
    without either column or with a repeated name, a row with the wrong number of
    fields, a date that is not YYYY-MM-DD, an equity that is not a finite
    positive number, a repeated date, or no row on or before `asof`. NO
    LOOKAHEAD: later rows are dropped, and that is asserted."""
    path = Path(path)
    if not path.exists():
        raise Unmeasured(f"no {path.name} at {path}")
    try:
        with open(path, newline="") as fh:
            rows = list(csv.reader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise Unmeasured(f"{path} could not be read: {type(e).__name__}: {e}") from None
    if not rows:
        raise Unmeasured(f"{path} is empty: no header row")
    header = rows[0]
    missing = [c for c in READ_COLUMNS if c not in header]
    if missing:
        raise Unmeasured(f"{path} header is {header}: no {missing} column")
    if len(set(header)) != len(header):
        raise Unmeasured(f"{path} header {header} repeats a column name")
    di, ei = header.index("date"), header.index("equity")
    seen, out = set(), []
    for n, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            raise Unmeasured(f"{path} line {n} has {len(row)} fields for {len(header)} columns")
        try:
            d = dt.date.fromisoformat(row[di])
        except ValueError:
            raise Unmeasured(f"{path} line {n}: date {row[di]!r} is not YYYY-MM-DD") from None
        try:
            e = float(row[ei])
        except ValueError:
            raise Unmeasured(f"{path} line {n}: equity {row[ei]!r} is not a number") from None
        if not (math.isfinite(e) and e > 0):
            raise Unmeasured(f"{path} line {n}: equity {row[ei]!r} is not a finite positive "
                             f"number")
        if d in seen:
            raise Unmeasured(f"{path} has two rows dated {d}")
        seen.add(d)
        if d <= asof:                    # NO LOOKAHEAD: nothing after the as-of date
            out.append((d, e))
    if not out:
        raise Unmeasured(f"{path} has no row dated on or before the as-of {asof}")
    out.sort()
    assert out[-1][0] <= asof, f"lookahead: {path} row {out[-1][0]} after as-of {asof}"
    return out


def measure(series: list, lv: dict) -> dict:
    """The drawdown of the newest row from the high-water mark of `series`, the
    worst drawdown in it (on the running HWM), and the first date each line was
    crossed. `series` is `read_series`'s output; `lv` is `levels`'s."""
    hwm_eq, hwm_date = series[0][1], series[0][0]
    for d, e in series:
        if e > hwm_eq:
            hwm_eq, hwm_date = e, d
    last_date, last_eq = series[-1]
    dd = 1.0 - last_eq / hwm_eq
    run, worst, worst_date = 0.0, 0.0, series[0][0]
    crossed = {"halve": None, "kill": None}
    for d, e in series:
        run = max(run, e)
        x = 1.0 - e / run
        if x > worst:
            worst, worst_date = x, d
        for k in crossed:
            if crossed[k] is None and x >= lv[k]:
                crossed[k] = d
    status = KILL if dd >= lv["kill"] else HALVE if dd >= lv["halve"] else OK
    return {"rows": len(series), "first_date": series[0][0], "last_date": last_date,
            "equity": last_eq, "hwm": hwm_eq, "hwm_date": hwm_date,
            "drawdown": round(dd, 8), "worst_drawdown": round(worst, 8),
            "worst_date": worst_date, "first_crossed": crossed, "status": status}


def _snapshot(state_dir: Path, asof: dt.date, lv: dict | None) -> dict:
    """The equity.csv reading, labelled. Shown beside the official one, NEVER an
    input to the status (module docstring, THE SERIES)."""
    path = Path(state_dir) / SNAPSHOT_FILE
    out = {"file": str(path), "label": SNAPSHOT_LABEL}
    if lv is None:
        out["unmeasured"] = "no levels to compare with (see the official reading)"
        return out
    try:
        out["reading"] = measure(read_series(path, asof), lv)
    except Unmeasured as e:
        out["unmeasured"] = str(e)
    return out


def check(state_dir: Path, spec: dict, asof: dt.date, mode: str) -> dict:
    """The drawdown record for the decide on `asof` (module docstring). Expected
    failures (no file, bad rows, bad levels, a series that ends before `asof`)
    give status UNMEASURED with `why`. Anything else is a bug and is raised; in
    report mode run.py records it as UNMEASURED."""
    if mode not in MODES:
        raise ValueError(f"drawdown mode {mode!r} is not one of {MODES}")
    path = Path(state_dir) / OFFICIAL_FILE
    rec = {"mode": mode, "asof": asof, "series": OFFICIAL_LABEL, "file": str(path),
           "acted": False}       # report mode never acts on what it finds
    lv = None
    try:
        lv = levels(spec)
        rec["levels"] = lv
        reading = measure(read_series(path, asof), lv)
        rec["reading"] = reading
        if reading["last_date"] != asof:
            raise Unmeasured(f"{path.name}'s newest row on or before the as-of is "
                             f"{reading['last_date']}, not the as-of {asof}: the figures in "
                             f"`reading` are as of {reading['last_date']}")
        rec["status"] = reading["status"]
    except Unmeasured as e:
        rec["status"], rec["why"] = UNMEASURED, str(e)
    rec["would_on"] = WOULD_ON[rec["status"]]
    rec["snapshot"] = _snapshot(state_dir, asof, lv)
    return rec


def unmeasured_record(mode: str, asof: dt.date, why: str) -> dict:
    """The record when `check` itself failed (report mode; run.py `_drawdown`)."""
    return {"mode": mode, "asof": asof, "series": OFFICIAL_LABEL, "acted": False,
            "status": UNMEASURED, "why": why, "would_on": WOULD_ON[UNMEASURED]}


def _pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def _reading_text(r: dict) -> str:
    return (f"{_pct(r['drawdown'])} below the high-water mark ${r['hwm']:,.2f} "
            f"({r['hwm_date']}), at ${r['equity']:,.2f} ({r['last_date']})")


def lines(rec: dict) -> list[str]:
    """The session log's lines: the official reading (and what `on` would do),
    then the snapshot, labelled. Report mode says so on every line it acts on."""
    head = f"  DRAWDOWN ({rec['mode']})"
    lv = rec.get("levels")
    lines_ = f"; lines halve {_pct(lv['halve'])} / kill {_pct(lv['kill'])}" if lv else ""
    st = rec["status"]
    if st == UNMEASURED:
        first = f"{head}: UNMEASURED: {rec['why']}{lines_}"
        if "reading" in rec:             # a series that ends before the as-of: shown, dated
            first += f"; stale reading: {_reading_text(rec['reading'])}"
    else:
        r = rec["reading"]
        tag = {OK: "OK", HALVE: "HALVE LINE BREACHED", KILL: "KILL LINE BREACHED"}[st]
        first = f"{head}: {tag}: {_reading_text(r)} on {OFFICIAL_FILE}{lines_}"
        # A line crossed earlier and recovered from: a sticky `on` would still hold it.
        rank = {OK: 0, HALVE: 1, KILL: 2}
        for k, k_rank in (("kill", 2), ("halve", 1)):
            if r["first_crossed"][k] is not None and rank[st] < k_rank:
                first += (f"; the {k} line was crossed on {r['first_crossed'][k]} "
                          f"(a sticky `on` armed before then would still hold it)")
                break
    out = [first + f". `on` would: {rec['would_on']}. Report mode: no order changed."]
    snap = rec.get("snapshot")
    if snap is not None:
        what = (_reading_text(snap["reading"]) if "reading" in snap
                else f"unreadable: {snap['unmeasured']}")
        out.append(f"  DRAWDOWN snapshot ({SNAPSHOT_FILE}, after-hours marks, NOT the "
                   f"check's input): {what}")
    return out
