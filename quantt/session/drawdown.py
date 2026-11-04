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
it to the session log (`lines`). Report mode acts on nothing. ONE READER OF THE
STATUS RESTRICTS ON IT, and only while the core spec sets `below_min_names =
"trade_eligible"` (CEF trial 55, paper only; added 2026-11-03): run.py's K0
(`_thin_k0_stop`) lets the sleeve build a reduced 4-5 name book only when the
status is exactly OK, and on HALVE, KILL, UNMEASURED or anything else passes the
stop that takes today's flatten instead. Its one action is today's rule: it never
sizes up and never unlocks a send (the owner's term, pinned by
quantt/session/tests/test_trade_eligible_runner.py, "no drawdown status can
increase gross"). With that key absent nothing reads the status, and the
orders, the plan_sha and plan.json are a check-off session's, byte for byte,
apart from the added `drawdown` record. The K0-K3 REPORT lines for that trial
are at the end of this module (`thin_stop_record`); they report and act on
nothing. quantt/session/tests/test_drawdown.py
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


# ---------------------------------------------------------------------------
# CEF TRIAL 55 ("te4"): the K0-K3 report lines
# ---------------------------------------------------------------------------
#
# results/cef/PREREG_THIN_TRADE_ELIGIBLE_2026-11-03.md §6.3 requires, in the activation release,
# report lines for K0-K3 "in report mode and tested": "a stop that lives only in a document is
# a stop nobody reads". This is them. REPORT ONLY: nothing that trades reads any of it. K0's
# ACTION (a reduced build only on an exact OK) is quantt/session/run.py `_thin_k0_stop`, which
# reads this module's status; the line here reports whether that reading also KILLS the trial.
# Called only while the core spec sets `below_min_names = "trade_eligible"` (run.py
# `_thin_stops`), so with the key absent nothing here runs and plan.json has no `thin_stops`.
#
# Every input is passed in (the records, the series, the positions, the thresholds), so the
# function is tested on synthetic records; run.py does the reading.
#
# DEFINITIONS (§4.2, §6.3; compose.py's, where it has one):
#   reduced decision  §4.2: "a decide on which the sleeve's reduced build ran AND ITS TARGETS
#                     WERE SENT". A prior plan.json whose `thin_session.reduced` is true and
#                     whose `refusals` list is empty (the structured flag, never a reason
#                     string), whose targets were sent (`sent`, below; review fix F2 after
#                     7fcc2b7). The first build did not read the send, so a decided reduced plan
#                     whose late-market SEND was refused, dry or never ran counted, and K1
#                     compounded its earning day although the account held another book that
#                     session. A decided reduced plan that was NOT sent is not a reduced
#                     decision: it opens no episode, earns K1 nothing, and its close is not a
#                     reduced close for K2 or K3 (it neither breaks nor extends K3's run). One
#                     whose send cannot be established (`sent`'s UNMEASURED cases) makes the
#                     episode UNMEASURED, named, as a missing record does.
#   episode           reduced decisions fewer than THIN_EPISODE_GAP sessions apart; OPEN at this
#                     decide while the newest is fewer than THIN_EPISODE_GAP sessions back.
#   earning day       for a reduced decision whose session is s (filled at s's late window), the
#                     next session e; its return is eod_equity(e) / eod_equity(s) - 1, counted
#                     only once e is on or before the as-of date (no lookahead).
#   K1                the maximum drawdown of the episode's earning-day returns compounded end
#                     to end from 1.0 at the episode's start; TRIPPED at or above the line.
#   K2, K3            at this decide, if the previous session's decision was reduced: the
#                     account's positions (after that session's fills) at the as-of closes,
#                     over eod_equity(as-of). K2 the largest |name|, K3 |long - short|. TRIPPED
#                     above the line. K3's run counts reduced closes IN SEQUENCE (compose.py's
#                     `runs_above` over reduced decisions; a full session between them does not
#                     break it), read back from earlier plans' `thin_stops.K3.net` within the
#                     open episode only (a run that crossed two episodes, which compose.py
#                     would count, is not seen: episodes are 63 or more sessions apart), against
#                     today's line. WHICH RECORD HOLDS WHICH CLOSE: the decide for session X
#                     reads as-of previous(X), so plan(X).thin_stops.K3 judges the close of the
#                     session BEFORE X (its `session` field says so). The close before this
#                     decide's as-of is therefore in the as-of session's own plan, the newest
#                     record read back; the first build skipped it and counted one close too far
#                     back, so K3 tripped a close late on a true run and could trip on a broken
#                     one (both reviews of 7fcc2b7). Each earlier K3 counted must name the close
#                     it judged, or the run is UNMEASURED; so is a run still open where the
#                     walk stopped at a record it could not read.
#   send skip         the previous session's late-market SEND (send.json `skipped`, the run
#                     record's `skipped_at_send`) after a reduced decision. The send skips only
#                     orders that open or increase a short of a name no longer shortable
#                     (run.py `_send_planned`), so any entry is a lost short. Ruled 2026-11-03:
#                     accept it and label it; this is the label, and K3 watches the result.
#                     ONLY FROM A SEND THAT WENT (`_send_state`; review fix F3 after 7fcc2b7).
#                     `_send_planned` builds the skipped list BEFORE its gates, so a send that
#                     was then refused, or dry, writes the list and sends nothing; the first
#                     build labelled that a lost short. A send that did not go labels nothing
#                     (applies False, naming its exit): it is not a reduced decision (below).
#                     One whose outcome is not established leaves the session's record
#                     unmeasured, so whether the label applies reads UNMEASURED.
#   sent              (`_send_state`) whether a decision's targets went to the broker, read
#                     from the session's own records: plan.json `orders` / `plan_sha` /
#                     `execution`, send.json `plan_sha` / `exit`, and whether <D>/STARTED exists
#                     (run.py writes it before the first order of a set, and never otherwise;
#                     CLAUDE.md order-path rule 2). The rule:
#                       * no orders: nothing needed sending, and the account already held the
#                         plan's targets when it was decided (a late-market decide with no
#                         orders exits NOTHING_TO_SEND and no send runs): SENT;
#                       * cls (the decide is the send): SENT exactly when STARTED exists (a cls
#                         transmit that failed part-way counts as sent; its run record, not
#                         read here, says what filled);
#                       * late market: send.json's `exit` SENT with STARTED: SENT. DRY, REFUSED
#                         or NOTHING_TO_SEND without STARTED, or no send.json and no STARTED (no
#                         send ran in the window): NOT SENT. Anything else is UNMEASURED, named:
#                         FAIL (part of a set may have gone), a send.json of another plan_sha,
#                         a STARTED beside a refused, dry or missing send record (a later run's
#                         record over the send's, or a send that never wrote one), a SENT
#                         without STARTED.
# READING BACK. Sessions are walked newest first from the one before this decide. A session
# with no plan.json, or one that cannot be read, makes the episode UNMEASURED (named): a
# missing record is not a session without a reduced build. A plan.json with no
# `thin_session` was decided with the key absent, when no reduced build could run, and ends
# the walk (the rule was off before it).

THIN_EPISODE_GAP = 63    # sessions: build_panel's ADV window, the screen's merge rule (§4.2)
THIN_K3_RUN = 3          # K3's persistence: above the run line on 3 reduced closes (§6.3)
THIN_SCAN_LIMIT = 2000   # sessions walked back at most; beyond it the episode is UNMEASURED
TRIPPED, CLEAR, KILLED, NOT_APPLICABLE = "TRIPPED", "CLEAR", "KILLED", "N/A"


def _decided_reduced(plan: dict) -> bool:
    """The sleeve's reduced build ran on a decided plan: the structured flag, no refusals."""
    ts = plan.get("thin_session") or {}
    return ts.get("reduced") is True and plan.get("refusals") == []


def _is_reduced(d, day: dict) -> tuple[bool, str | None]:
    """(reduced, why not) for the session d: a REDUCED DECISION (block comment) is a decided
    reduced plan whose targets were sent (`_send_state`). `why not` names a decided reduced
    plan that was not sent, else None. Raises `Unmeasured` when the send cannot be read."""
    if not _decided_reduced(day["plan"]):
        return False, None
    went, how = _send_state(d, day)
    return (True, None) if went else (False, f"{d}'s reduced decision was not sent: {how}")


SEND_WENT = "SENT"                                         # send.json `exit` of a set that went
SEND_NOT_GONE = ("DRY", "REFUSED", "NOTHING_TO_SEND")      # exits that send nothing


def _send_state(d, day: dict) -> tuple[bool, str]:
    """(sent, how) for the decision recorded for session `d` (`day` = read_day(d)): did its
    targets go to the broker? The rule is the block comment's `sent`. Raises `Unmeasured`,
    naming the session and the record, when the records cannot say: never a guess either way."""
    plan = day["plan"]
    orders = plan.get("orders")
    if not isinstance(orders, list):
        raise Unmeasured(f"{d}'s plan.json has no `orders` list ({orders!r}): whether its "
                         f"targets were sent cannot be read")
    if not orders:
        return True, f"{d}'s plan had no orders: the account already held its targets"
    started = day.get("started")
    if not isinstance(started, bool):
        raise Unmeasured(f"whether a set STARTED for {d} was not read ({started!r})")
    if plan.get("execution") != "late_market":
        return started, (f"cls: the decide is the send, and a set "
                         + ("STARTED" if started else "never STARTED") + f" for {d}")
    send = day.get("send")
    if send is None:
        if started:
            raise Unmeasured(f"a set STARTED for {d} and there is no send.json: what went is "
                             f"not recorded")
        return False, f"no send ran for {d} (no send.json, no STARTED)"
    if send.get("plan_sha") != plan.get("plan_sha"):
        raise Unmeasured(f"{d}'s send.json is of plan_sha {send.get('plan_sha')!r}, its "
                         f"plan.json of {plan.get('plan_sha')!r}")
    ex = send.get("exit")
    if ex == SEND_WENT and started:
        return True, f"{d}'s send exited {ex}"
    if ex in SEND_NOT_GONE and not started:
        return False, f"{d}'s send exited {ex}: nothing was sent"
    raise Unmeasured(f"{d}'s send.json exit is {ex!r} and a set "
                     + ("STARTED" if started else "never STARTED")
                     + ": whether its targets were sent is not established")


def _walk(session_date, previous_session, read_day) -> dict:
    """The open episode's records, read back from the session before `session_date`.

    Walks newest first. It stops at a session THIN_EPISODE_GAP or more sessions back from the
    oldest reduced decision found so far (from this decide when none is found): that session
    cannot belong to the episode. Returns {"status": "OPEN" | "NONE" | "UNMEASURED", "why",
    "days": [(session, day)] newest first, "reduced": [session, ...] newest first, "unsent":
    {session: why} (decided reduced plans that were not sent), "scanned"}. OPEN means a
    reduced decision fewer than THIN_EPISODE_GAP sessions back. A session whose send cannot be
    read is not appended to `days` (it is the record that could not be read)."""
    days, reduced, unsent, d, k, last = [], [], {}, session_date, 0, 0
    while True:
        d = previous_session(d)
        k += 1
        if k - last >= THIN_EPISODE_GAP:
            why = f"{THIN_EPISODE_GAP} sessions back from the " + (
                "oldest reduced decision found" if reduced else "this decide") + " reached"
            break
        if k > THIN_SCAN_LIMIT:
            return {"status": UNMEASURED, "why": f"more than {THIN_SCAN_LIMIT} sessions read back",
                    "days": days, "reduced": reduced, "unsent": unsent, "scanned": k - 1}
        try:
            day = read_day(d)
        except Exception as e:  # recorded, named: an unreadable record is not an empty one
            return {"status": UNMEASURED, "why": f"the record of {d} could not be read: "
                    f"{type(e).__name__}: {e}", "days": days, "reduced": reduced,
                    "unsent": unsent, "scanned": k}
        plan = day.get("plan")
        if plan is None:
            return {"status": UNMEASURED, "why": f"no plan.json for the session {d}",
                    "days": days, "reduced": reduced, "unsent": unsent, "scanned": k}
        if "thin_session" not in plan:
            why = f"{d} was decided with the key absent"
            break
        try:
            is_red, not_sent = _is_reduced(d, day)
        except Unmeasured as e:     # a send that cannot be read is not a send that did not go
            return {"status": UNMEASURED, "why": str(e), "days": days, "reduced": reduced,
                    "unsent": unsent, "scanned": k}
        days.append((d, day))
        if is_red:
            reduced.append(d)
            last = k
        elif not_sent is not None:
            unsent[d] = not_sent
    return {"status": "OPEN" if reduced else "NONE", "why": why, "days": days,
            "reduced": reduced, "unsent": unsent, "scanned": k}


def _verdict(stat, line, above_or_at: bool) -> str:
    if line is None:
        return UNMEASURED
    return TRIPPED if (stat >= line if above_or_at else stat > line) else CLEAR


def thin_stop_record(*, asof, session_date, drawdown: dict, current: dict, previous_session,
                     read_day, series, positions: dict, closes: dict,
                     thresholds: dict) -> dict:
    """The K0-K3 report lines for the decide on `asof` for `session_date` (block comment above).

    `drawdown` is this decide's drawdown record (`check`); `current` its `thin_session`;
    `previous_session(d)` the NYSE session before d; `read_day(d)` -> {"plan": dict | None,
    "send": dict | None, "started": bool} for the session d (it may raise); `series` the
    eod_equity rows [(date, equity)] on or before `asof`, or a string saying why there are
    none; `positions`
    {symbol: signed shares} now; `closes` {symbol: as-of close}; `thresholds` the four
    `risk.thin_*` values (None where absent: that line reads UNMEASURED). Pure: reads nothing
    but what it is given."""
    eq = dict(series) if isinstance(series, list) else None
    eq_why = None if eq is not None else f"no equity series: {series}"
    assert eq is None or all(d <= asof for d in eq), "lookahead: an equity row after the as-of"
    th = dict(thresholds)
    w = _walk(session_date, previous_session, read_day)
    rec = {"report_only": True, "asof": asof, "session_date": session_date,
           "episode": {"status": w["status"], "why": w["why"], "scanned": w["scanned"],
                       "reduced_sessions": sorted(w["reduced"]),
                       "this_decide_reduced": current.get("reduced") is True}}
    # ---- K0: the account, read at this decide
    status = drawdown.get("status")
    k0 = {"status": status, "asof": drawdown.get("asof"),
          "acted": current.get("stopped_by") == "K0"}
    if status in (HALVE, KILL):
        k0["verdict"] = {"OPEN": KILLED, "NONE": CLEAR}.get(w["status"], UNMEASURED)
    else:
        k0["verdict"] = CLEAR       # OK, or UNMEASURED: flattens the session, kills nothing
    rec["K0"] = k0
    # ---- K1: the episode's earning days
    line = th.get("thin_k1_episode_drawdown")
    k1 = {"line": line}
    if w["status"] == UNMEASURED:
        k1.update(verdict=UNMEASURED, why=f"episode unmeasured: {w['why']}")
    elif w["status"] == "NONE" and current.get("reduced") is True:
        k1.update(earning_days=0, drawdown=0.0, verdict=_verdict(0.0, line, True),
                  why="the episode opens at this decide; no day earned yet")
    elif w["status"] == "NONE":
        k1.update(verdict=NOT_APPLICABLE, why="no open episode")
    else:
        sessions = [x[0] for x in w["days"]]          # newest first
        rets, missing = [], None
        for s in sorted(w["reduced"]):
            i = sessions.index(s)
            e = session_date if i == 0 else sessions[i - 1]
            if e > asof:
                continue                              # not yet earned
            if eq is None:
                missing = eq_why
            elif s not in eq or e not in eq:
                missing = f"no eod_equity row for {s if s not in eq else e}"
            if missing is not None:
                break
            rets.append((e, eq[e] / eq[s] - 1.0))
        if missing is not None:
            k1.update(verdict=UNMEASURED, why=missing)
        else:
            path, peak, worst = 1.0, 1.0, 0.0
            for _, r in sorted(rets):
                path *= 1.0 + r
                peak = max(peak, path)
                worst = max(worst, 1.0 - path / peak)
            k1.update(earning_days=len(rets), drawdown=round(worst, 8),
                      verdict=_verdict(worst, line, True))
    rec["K1"] = k1
    # ---- K2, K3: the previous session's close, after a reduced decision
    prev = w["days"][0] if w["days"] and w["days"][0][0] == asof else None
    prev_unread = prev is None and w["status"] == UNMEASURED and not w["days"]
    # A reduced decision is one whose targets were sent (`_is_reduced`): the walk classified
    # `prev` already. Not one: N/A, naming a decided reduced plan that was not sent.
    prev_reduced = prev is not None and asof in w["reduced"]
    not_reduced = w["unsent"].get(asof) or f"{asof} was not a reduced session"
    run_line, once_line = th.get("thin_k3_net_run"), th.get("thin_k3_net_once")
    k2 = {"line": th.get("thin_k2_max_name_frac"), "session": asof}
    k3 = {"line_run": run_line, "line_once": once_line, "session": asof}
    if prev_unread:
        for k in (k2, k3):
            k.update(verdict=UNMEASURED, why=f"the record of {asof} is unmeasured: {w['why']}")
    elif not prev_reduced:
        for k in (k2, k3):
            k.update(verdict=NOT_APPLICABLE, why=not_reduced)
    else:
        held = {s: q for s, q in positions.items() if q}
        nocl = sorted(s for s in held if not isinstance(closes.get(s), (int, float)))
        why = (eq_why if eq is None else f"no eod_equity row for {asof}" if asof not in eq
               else f"no as-of close for {nocl}" if nocl else None)
        if why is not None:
            for k in (k2, k3):
                k.update(verdict=UNMEASURED, why=why)
        else:
            mv = {s: q * float(closes[s]) for s, q in held.items()}
            e = eq[asof]
            k2_stat = max((abs(v) for v in mv.values()), default=0.0) / e
            net = abs(sum(mv.values())) / e
            k2.update(stat=round(k2_stat, 8), verdict=_verdict(k2_stat, k2["line"], False))
            k3["net"] = round(net, 8)
            if run_line is None or once_line is None:
                k3.update(verdict=UNMEASURED, why="a K3 line is not set")
            else:
                run, broken = (1, None) if net > run_line else (0, None)
                if run:
                    # Newest first FROM `prev` itself: w["days"][i]'s K3 judges the close of
                    # w["days"][i + 1] (the decide for X reads as-of previous(X); block
                    # comment, WHICH RECORD HOLDS WHICH CLOSE). Only the closes of reduced
                    # decisions count; a full session between them does not break the run.
                    # The oldest day's K3 judges a close outside the walk: skipped.
                    reduced_set = set(w["reduced"])
                    sessions = [x[0] for x in w["days"]]
                    for i, (d, day) in enumerate(w["days"]):
                        judged = sessions[i + 1] if i + 1 < len(sessions) else None
                        if judged not in reduced_set:
                            continue                        # not a reduced decision's close
                        k = ((day["plan"].get("thin_stops") or {}).get("K3") or {})
                        if not isinstance(k.get("net"), (int, float)):
                            broken = (f"the K3 of {judged}'s reduced close (in {d}'s plan) is "
                                      f"unmeasured ({k!r})")
                            break
                        if str(k.get("session")) != judged.isoformat():
                            broken = (f"{d}'s K3 names the close of {k.get('session')!r}, not "
                                      f"{judged}; not counting a run on it")
                            break
                        if k["net"] > run_line:
                            run += 1
                            if run >= THIN_K3_RUN:
                                break
                        else:
                            break
                    else:
                        # The walk ran out with the run still open. A walk that stopped at a
                        # record it could not read may have cut a longer run short (the oldest
                        # day's K3 judges the close of the session it could not read): not
                        # CLEAR. One that stopped at the key-absent plan or the 63-session gap
                        # did not: no reduced close lies beyond either.
                        if w["status"] == UNMEASURED and run < THIN_K3_RUN:
                            broken = (f"the walk back stopped before the run ended, at "
                                      f"{w['why']}")
                k3["run"] = run
                if net > once_line or run >= THIN_K3_RUN:
                    k3["verdict"] = TRIPPED
                elif broken is not None:
                    k3.update(verdict=UNMEASURED, why=broken)
                else:
                    k3["verdict"] = CLEAR
    rec["K2"], rec["K3"] = k2, k3
    # ---- the send-time skip after a reduced decision (ruled 2026-11-03: label it)
    sk = {"session": asof}
    if prev_unread:
        sk.update(applies=UNMEASURED, why=f"the record of {asof} is unmeasured: {w['why']}")
    elif not prev_reduced:
        # Only a send that went can have lost a short (block comment, send skip): a refused or
        # dry send wrote its skipped list and sent nothing, and is not a reduced decision.
        sk.update(applies=False, why=not_reduced)
    elif prev[1]["plan"].get("execution") != "late_market":
        sk.update(applies=False, why="cls: the decide is the send; there is no send-time skip")
    else:
        # A reduced decision's targets were sent (`_is_reduced`): with no orders no send ran;
        # with orders send.json exited SENT (`_send_state`).
        send = prev[1].get("send")
        skipped = None if send is None else send.get("skipped")
        if not prev[1]["plan"]["orders"]:
            sk.update(applies=False, why=f"{asof}'s plan had no orders: no send ran, so nothing "
                                         f"was skipped at one")
        elif not isinstance(skipped, list):
            sk.update(applies=True, lost_short=UNMEASURED,
                      why=f"send.json for {asof} has no `skipped` list ({skipped!r})")
        else:
            sk.update(applies=True, skipped_at_send=list(skipped), lost_short=bool(skipped))
    rec["send_skip"] = sk
    return rec


def thin_unmeasured_record(asof, why: str) -> dict:
    """The record when the K-lines could not be computed at all (run.py `_thin_stops`)."""
    return {"report_only": True, "asof": asof, "unmeasured": why}


def thin_stop_lines(rec: dict) -> list[str]:
    """The session log's K0-K3 lines (report only)."""
    head = "  TE4 STOPS (report only)"
    if "unmeasured" in rec:
        return [f"{head}: UNMEASURED: {rec['unmeasured']}"]
    ep = rec["episode"]
    out = [f"{head}: episode {ep['status']}"
           + (f" (reduced sessions {ep['reduced_sessions']})" if ep["reduced_sessions"] else "")
           + (f"; {ep['why']}" if ep["status"] == UNMEASURED else "")]
    k0 = rec["K0"]
    out.append(f"    K0 {k0['verdict']}: drawdown status {k0['status']} (as-of {k0['asof']})"
               + ("; it stopped this session's reduced build" if k0["acted"] else ""))
    for name in ("K1", "K2", "K3"):
        k = rec[name]
        stat = {"K1": k.get("drawdown"), "K2": k.get("stat"), "K3": k.get("net")}[name]
        lines_ = (f"line {k['line']}" if name != "K3"
                  else f"lines run {k['line_run']} / once {k['line_once']}")
        out.append(f"    {name} {k['verdict']}: {stat if stat is not None else '-'} against "
                   f"{lines_}" + (f", run {k['run']}" if name == "K3" and "run" in k else "")
                   + (f"; {k['why']}" if k.get("why") else ""))
    sk = rec["send_skip"]
    if sk.get("applies") is True:
        out.append(f"    SEND SKIP {sk['session']}: lost a short at send: {sk['lost_short']}"
                   + (f" {sk['skipped_at_send']}" if sk.get("skipped_at_send") else "")
                   + (f"; {sk['why']}" if sk.get("why") else ""))
    elif sk.get("applies") == UNMEASURED:
        out.append(f"    SEND SKIP {sk['session']}: UNMEASURED; {sk['why']}")
    return out
