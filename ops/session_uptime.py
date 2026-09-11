#!/usr/bin/env python3
"""Per-session arm/miss outcomes for a scheduled book, from BOTH log trees.

    python3 -m ops.session_uptime                      # the table + the verdict
    python3 -m ops.session_uptime --json               # machine-readable
    python3 -m ops.session_uptime --job benchmarks     # any scheduled job
    python3 -m ops.session_uptime --target 20          # the definition of done
    python3 -m ops.session_uptime --through 2026-09-10 # pin the window's end

Exit codes:  0 target met · 1 target not met · 3 could not measure (see below).

WHY THIS FILE EXISTS
--------------------
Uptime was an anecdote. Three different figures for the same quantity were in
circulation in this repo inside two days -- "3 of 26", "5 of 29", "6 of 30" --
none of them dated, none reproducible, and the one most often quoted was
produced by a shell one-liner that read a single log tree. That is not a
rounding disagreement; it is the measurement that tells you whether the book is
trading at all, and it was being hand-tallied. This module is the named
reproducer for any uptime figure quoted anywhere. If a document states a rate,
it states the command that prints it.

THE FAILURE THIS MAKES VISIBLE
------------------------------
Between 2026-08-03 and 2026-08-28 the book logged `status=ok_not_armed` every
session, wrote a heartbeat and advanced a ledger while transmitting nothing,
because nothing was listening on the configured broker port. Preflight caught it
correctly every single time. Nobody was reading preflight. So the unit of
measurement here is NOT "did the job exit 0" -- every one of those sessions did
-- it is "did this session ARM, and if not, which blocker fired".

WHY THE LOGS, AND NOT THE HEARTBEAT
-----------------------------------
`ops/heartbeat.json` holds exactly one record per job: the last one. It cannot
produce a history, and its `date` field is the date the beat was WRITTEN, not
the session it describes. Measured 2026-09-11 in the prod tree: cef's beat reads
`"date": "2026-09-11", "detail": {"pair_date": "2026-09-10"}` -- so a naive
"did today arm?" check against the heartbeat reads green on a day whose session
has not started. The session logs are the only per-session record that survives.

WHY BOTH TREES, AND WHY THAT IS NOT OPTIONAL
--------------------------------------------
The logs bifurcated on 2026-09-10 when `~/prod/QUANTT` took over the scheduler.
The dev tree's newest cef log is `cef_2026-09-09`; every log written since lands
only in prod. A tally run in one tree undercounts by one more every session, and
that is exactly how "5 of 29" came to be written down. So the default is the
UNION of this tree and `~/prod/QUANTT`, a date present in both is reported as a
duplicate rather than silently collapsed, and a tree that is absent makes the
measurement INCOMPLETE (exit 3) rather than quietly smaller -- because an
undercounted denominator flatters the rate, which is the direction that hurts.

WHY THE CALENDAR IS NOT HAND-CODED
----------------------------------
Eligibility comes from `ops/schedule/nyse_calendar.py`, the same pure-stdlib
module the launchd wrapper itself gates on. Using any other calendar here would
let the measurement and the scheduler disagree about what a session even is --
and a holiday counted as a miss is a false alarm that teaches the operator to
ignore this number, which is how the August failure survived four weeks.

ARMED IS NECESSARY AND NOT SUFFICIENT, SO THERE ARE TWO RATES
-------------------------------------------------------------
`arm_rate` counts the `ARMED:` line. That is the loose reading and it is not
enough, because the log tree contains two sessions that armed and are not
sessions you would want to repeat twenty times:

  * 2026-09-08 armed at 22:44 and then `book run FAILED rc=1` -- the shadow
    ledger's manifest disagreed with its own files, so run_book raised before
    reaching the order phase. Armed, exit 1, nothing placed by the session.
  * 2026-09-10 armed at 10:38 the NEXT MORNING. The session launched 17:15,
    polled for a NAV that never came, slept through its own 23:30 deadline and
    decided seventeen hours late. `done status=ok`.

So `clean_rate` additionally requires that the arm happened on the session's own
calendar date, that the book run reported ok, and that the job finished
`status=ok`. The definition of done keys on the STRICT one. Both are printed,
and the loose-minus-strict gap is itself a finding.

WHAT THIS MODULE CANNOT TELL YOU
--------------------------------
Whether an order reached the broker, and whether it filled. The logs carry the
shadow ledger's MODELLED turnover, which on 2026-09-10 booked fills the broker
never executed (landmine 3). Turnover is reported here labelled `modelled` and
must never be read as evidence of a fill; `ops/capture_fills.py` and
`/api/provenance` own that question. Arming is an operational fact. Trading is a
broker fact.

NO SILENT FALLBACKS. A log that carries neither an `ARMED:` line nor a
`NOT ARMED ->` line is `indeterminate`, never "not armed" -- a crash before
preflight and a clean stand-down are different facts. An indeterminate session
inside the window, or an absent log tree, makes the whole measurement
`complete: false` and exits 3. This module refuses to print a rate it could not
measure.

Reads files. Opens no socket, writes nothing, transmits nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.schedule import nyse_calendar as cal  # noqa: E402

# The prod worktree's location is a convention, not a config: it is hardcoded
# the same way in ops/schedule/install_backup.sh:44 and ops/promote.sh's usage
# line. Kept as a module constant so a test can point it somewhere else.
PROD_TREE = Path.home() / "prod" / "QUANTT"
LOG_SUBDIR = Path("ops/schedule/logs")

#: How many consecutive eligible sessions must arm cleanly before uptime is
#: considered fixed. A RATE, not a fix: one green session proves nothing, and
#: the August failure ran for twenty. Overridable with --target; this is the
#: default only, and H14 forbids any decision keying on the number in a doc
#: rather than on what the tool measures.
DEFAULT_TARGET = 20

# ------------------------------------------------------------------ parsing --
# Every pattern below was written against the real logs in both trees on
# 2026-09-11, not against the wrapper's source. The wrapper's wording has
# changed at least twice (the dry-run path moved from $TMPDIR to
# ops/books/_dryruns, the port moved 7497 -> 4002) and the old spellings are
# still on disk, so these must match what is WRITTEN, not what is emitted now.
_TS = r"\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\]"
RE_START = re.compile(_TS + r" launchd start \(job=(\S+?)\)")
RE_VERDICT = re.compile(r"^(\d{4}-\d{2}-\d{2}) (TRADING|CLOSED)\b(?: \((.*)\))?$")
RE_SKIP = re.compile(_TS + r" not an NYSE trading day - skip")
RE_ARMED = re.compile(_TS + r" ARMED: (.*)$")
RE_NOT_ARMED = re.compile(_TS + r" NOT ARMED -> .*?\. Reason: (.*)$")
# An OLDER wrapper, still on disk in phase0's July logs, prints no `launchd
# start`, no `NOT ARMED` and no `done status=`. It says only `RUNG-0 dry run ->`.
# That is a complete, decipherable stand-down: the rung ladder in <job>.env was
# below RUNG-2, so the session computed targets and transmitted nothing. Reading
# it as `indeterminate` would make the tool refuse to measure phase0 forever over
# a format it can in fact read — and `indeterminate` has to keep meaning
# "undecipherable", or exit 3 stops meaning anything.
RE_RUNG = re.compile(_TS + r" (RUNG-\d) dry run ->")
# The same-day guard. Its presence is why a second `launchd start` in one log is
# designed behaviour rather than the doubling hazard, and the two must not be
# reported the same way.
RE_GUARD = re.compile(_TS + r" SAME-DAY GUARD: ")
RE_DONE = re.compile(_TS + r" done status=(\S+)")
RE_BOOK_RUN = re.compile(_TS + r" book run (ok|FAILED rc=\d+)")
RE_ASOF = re.compile(r"\basof=(\d{4}-\d{2}-\d{2})\b")
RE_BOOK_LINE = re.compile(
    r"^\[run_book\] BOOK asof (\d{4}-\d{2}-\d{2})\s+NAV \$(-?[\d,.]+)\s+"
    r"PnL \$(-?[\d,.]+)\s+turnover \$(-?[\d,.]+)")
# A reason string is one or more preflight verdicts joined by "; ", e.g.
#   "[FAIL] data: prices -> ...; [FAIL] broker: nothing listening on ..."
# It can also be free text with no verdict at all ("human halt (DRY_RUN=1)"),
# which is why the no-match branch keeps the text verbatim instead of dropping
# the session into an "other" bucket with nothing in it.
RE_VERDICT_ITEM = re.compile(
    r"\[(FAIL|WARN)\]\s*([^:]+):\s*(.*?)(?=\s*\[(?:FAIL|WARN)\]|$)", re.S)
RE_PORT = re.compile(r"nothing listening on (\S+?):(\d+)")

#: Blocker codes, matched against one preflight verdict's text. Order is the
#: match order and the first hit wins for that verdict. `other` is not in the
#: table: anything unmatched keeps its check name and full text, so a new
#: failure mode shows up as itself rather than being absorbed.
_CODE_PATTERNS = (
    ("broker_down", re.compile(r"nothing listening on|ConnectionRefused|"
                               r"not listening|no broker", re.I)),
    ("human_halt", re.compile(r"human halt|DRY_RUN=1", re.I)),
    ("halt_file", re.compile(r"^halt\b|active halt", re.I)),
    ("stale_data", re.compile(r"^(prices|NAV) ->|^data\b", re.I)),
    ("margin", re.compile(r"cushion|excess liquidity", re.I)),
    ("unpriced", re.compile(r"priced|costs", re.I)),
)

#: One short sentence per code, for the operator who has not read the logs.
CODE_LABEL = {
    "broker_down": "IB Gateway / TWS was not listening on the configured port",
    "human_halt": "a human set DRY_RUN=1 — a hard halt that always wins",
    "halt_file": "a HALT file was active",
    "stale_data": "the price/NAV pair was not fresh enough to decide on",
    "margin": "the margin check refused",
    "unpriced": "a deployed name had no cost or price entry",
    "other": "see the verbatim reason",
    # Not preflight verdicts — outcomes with no blocker line to classify.
    "rung_config": ("the job env was set below RUNG-2, so the session computed "
                    "targets and transmitted nothing"),
    "no_log": "no session log in any named tree; the job did not run",
    "indeterminate": "the log ends before it says whether it armed",
}


def _classify(check: str, text: str) -> str:
    """Which known blocker this preflight verdict is, or `other`.

    Takes check name and message separately because the check name alone is
    ambiguous (`broker` also names the PASS line) and the message alone is
    ambiguous too (`halt[phase0_null]` carries another book's halt text).
    """
    blob = f"{check}: {text}"
    for code, rx in _CODE_PATTERNS:
        if rx.search(check) or rx.search(blob):
            return code
    return "other"


def parse_reason(reason: str) -> list[dict]:
    """Split a `Reason:` string into its individual blockers.

    A session can be blocked by more than one thing -- 2026-08-07 failed both
    `data` and `broker` -- so "the single blocking reason" is a simplification
    the data does not always support. The first blocker in the log's own order
    is reported as primary; every blocker is kept.
    """
    out = []
    for level, check, text in RE_VERDICT_ITEM.findall(reason or ""):
        check = check.strip()
        text = " ".join(text.split())
        code = _classify(check, text)
        b = {"level": level, "check": check, "text": text, "code": code}
        m = RE_PORT.search(text)
        if m:
            b["endpoint"] = f"{m.group(1)}:{m.group(2)}"
            b["port"] = int(m.group(2))
        out.append(b)
    if not out and (reason or "").strip():
        # Free text with no preflight verdict in it. Keep it whole: a halt is a
        # real, named blocker and collapsing it to "other: " loses the sentence.
        text = " ".join(reason.split())
        out.append({"level": "FAIL", "check": None, "text": text,
                    "code": _classify("", text)})
    return out


def _money(s: str):
    """'504,030.09' -> 504030.09. Returns None rather than 0.0 on anything
    unparseable: a zero turnover and an unreadable turnover are opposite facts
    on a panel whose whole job is to show a book that traded nothing."""
    try:
        return float(s.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def _parse_run(lines: list[str], job: str, date: str, rec: dict) -> dict:
    """One RUN within a session log. A log can hold more than one.

    Kept separate from `parse_log` because a session date is not a session: on
    2026-09-01 the benchmarks job fired twice, and the interesting facts —
    whether the SAME-DAY GUARD refused the second set, and which run's
    `done status=` belongs to the arm — are per-run, not per-file. Collapsing the
    file to one record and taking the last value of each field attributes the
    second run's `ok_already_traded` to the first run's arm.
    """
    r = {"started_at": None, "armed_at": None, "asof": None, "reason": None,
         "blockers": [], "book_run": None, "done_status": None, "skipped": False,
         "same_day_guard": False, "n_arm_lines": 0,
         "book_nav": None, "book_turnover": None}
    for line in lines:
        if mm := RE_START.match(line):
            r["started_at"] = f"{mm.group(1)} {mm.group(2)}"
            if mm.group(3) != job:
                rec["anomalies"].append(
                    f"filename says job={job}, log says job={mm.group(3)}")
        elif mm := RE_VERDICT.match(line.strip()):
            rec["log_calendar"] = mm.group(2)
            if mm.group(1) != date:
                rec["anomalies"].append(
                    f"filename date {date}, log banner date {mm.group(1)}")
        elif RE_SKIP.match(line):
            r["skipped"] = True
        elif RE_GUARD.match(line):
            r["same_day_guard"] = True
        elif mm := RE_ARMED.match(line):
            r["n_arm_lines"] += 1
            r["armed_at"] = f"{mm.group(1)} {mm.group(2)}"
            if a := RE_ASOF.search(mm.group(3)):
                r["asof"] = a.group(1)
        elif mm := RE_NOT_ARMED.match(line):
            r["reason"] = " ".join(mm.group(3).split())
            r["blockers"] = parse_reason(mm.group(3))
        elif mm := RE_RUNG.match(line):
            r["reason"] = (f"{mm.group(3)} configured in the job env — dry run, "
                           f"nothing transmitted")
            r["blockers"] = [{"level": "FAIL", "check": None,
                              "text": r["reason"], "code": "rung_config"}]
        elif mm := RE_BOOK_RUN.match(line):
            r["book_run"] = mm.group(3)
        elif mm := RE_DONE.match(line):
            r["done_status"] = mm.group(3)
        elif mm := RE_BOOK_LINE.match(line):
            r["book_nav"] = _money(mm.group(2))
            r["book_turnover"] = _money(mm.group(4))
    return r


def parse_log(path: Path) -> dict:
    """One session log -> one outcome record. Never guesses.

    `date` comes from the FILENAME, because that is what the scheduler keys on
    and what makes two trees mergeable. The log's own `YYYY-MM-DD TRADING`
    banner and the `asof=` in the ARMED line are read as independent checks and
    a disagreement is reported in `anomalies` rather than resolved here.

    WHICH RUN GOVERNS. A log with two runs reports the FIRST run that armed,
    because that is the run that placed orders; if none armed, the last run with
    a verdict. `anomalies` carries anything a human should look at and `notes`
    carries anything that is designed behaviour — kept apart deliberately, since
    an anomaly list that fills up with non-faults is an anomaly list nobody
    reads, which is the same failure mode as the panel itself.
    """
    m = re.fullmatch(r"(\w+)_(\d{4}-\d{2}-\d{2})\.log", path.name)
    if not m:
        raise ValueError(f"not a session log filename: {path}")
    job, date = m.group(1), m.group(2)

    rec: dict = {
        "date": date, "job": job, "tree": None, "log": str(path),
        "started_at": None, "armed_at": None, "asof": None,
        "done_status": None, "book_run": None, "reason": None,
        "blockers": [], "modelled_turnover_usd": None, "modelled_nav_usd": None,
        "dryrun_turnover_usd": None, "n_runs": 1,
        "log_calendar": None, "anomalies": [], "notes": [],
    }
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        raise OSError(f"cannot read session log {path}: {exc}") from exc

    # Split on `launchd start`. Anything before the first one is its own segment:
    # the pre-2026-08 wrapper wrote no start line at all and it still has to be
    # read rather than discarded.
    lines = text.splitlines()
    bounds = [i for i, ln in enumerate(lines) if RE_START.match(ln)]
    if not bounds or bounds[0] != 0:
        bounds = [0] + bounds
    segs = [lines[a:b] for a, b in zip(bounds, bounds[1:] + [len(lines)])]
    runs = [_parse_run(seg, job, date, rec) for seg in segs]
    runs = [r for r in runs
            if any((r["started_at"], r["armed_at"], r["reason"], r["skipped"]))] \
        or runs[-1:]
    rec["n_runs"] = sum(1 for r in runs if r["started_at"]) or len(runs)

    armed_runs = [r for r in runs if r["armed_at"]]
    gov = (armed_runs[0] if armed_runs
           else next((r for r in reversed(runs)
                      if r["reason"] or r["skipped"]), runs[-1]))
    for k in ("started_at", "armed_at", "asof", "reason", "blockers",
              "book_run", "done_status"):
        rec[k] = gov[k]

    # TWO armed runs on one session date is the doubling hazard, not a cosmetic
    # oddity: the trade phase is not idempotent, there is no dedupe at the
    # broker, and `arm()` re-seeds from `ib.positions()`, which do NOT include
    # unfilled MOC orders — so both sets fill in the same closing auction.
    total_arms = sum(r["n_arm_lines"] for r in runs)
    if total_arms > 1:
        rec["anomalies"].append(
            f"{total_arms} ARMED: lines on one session date — two armed runs "
            f"stack two order sets at the broker and there is no dedupe")
    elif len(runs) > 1 and any(r["same_day_guard"] for r in runs):
        rec["notes"].append(
            f"the job ran {rec['n_runs']} times; the same-day guard refused the "
            f"second order set, which is designed behaviour")
    elif len(runs) > 1:
        rec["anomalies"].append(
            f"{rec['n_runs']} runs in one session log and no same-day guard line")

    armed = rec["armed_at"] is not None
    # A NOT-ARMED run still prints `BOOK asof ... turnover $0`: it downgrades to a
    # DRY RUN against a $0.00 book, by design (phase 2 clears arm, leaves collect
    # true). Filing that 0 under "modelled turnover" would put "it traded
    # nothing" and "it was never asked to trade" in one column under a header
    # that says neither — a zero meaning "not measured", which is the exact defect
    # this tool exists to stop.
    if armed:
        rec["modelled_nav_usd"] = gov["book_nav"]
        rec["modelled_turnover_usd"] = gov["book_turnover"]
    else:
        rec["dryrun_turnover_usd"] = gov["book_turnover"]
    if rec["asof"] and rec["asof"] != date:
        rec["anomalies"].append(f"armed with asof={rec['asof']} on a {date} log")

    if gov["skipped"]:
        rec["outcome"] = "closed"
    elif armed:
        rec["outcome"] = "armed"
    elif rec["reason"]:
        rec["outcome"] = "blocked"
    else:
        rec["outcome"] = "indeterminate"
        rec["reason"] = ("no ARMED: and no 'NOT ARMED ->' line in the log — "
                         "the session crashed, was killed, or is still running")

    # Did it arm LATE? The arm timestamp's own calendar date, against the
    # session's. 2026-09-10 armed at 10:38 the following morning.
    rec["late_arm"] = bool(armed and rec["armed_at"][:10] != date)
    rec["clean"] = bool(
        armed
        and not rec["late_arm"]
        and rec["book_run"] == "ok"
        and rec["done_status"] == "ok")
    if armed and not rec["clean"]:
        why = []
        if rec["late_arm"]:
            why.append(f"armed {rec['armed_at']}, a day after the session date")
        if rec["book_run"] != "ok":
            why.append(f"book run {rec['book_run'] or 'never reported'}")
        if rec["done_status"] != "ok":
            why.append(f"done status={rec['done_status'] or 'never written'}")
        rec["caveat"] = "; ".join(why)
    else:
        rec["caveat"] = None
    rec["primary"] = rec["blockers"][0] if rec["blockers"] else None
    rec["codes"] = sorted({b["code"] for b in rec["blockers"]})
    return rec


# ------------------------------------------------------------------- trees ---
def default_trees() -> list[Path]:
    """Dev first, prod second. Precedence is LAST-WINS, so prod -- where the
    scheduler actually runs -- decides a duplicated date."""
    return [REPO, PROD_TREE]


def collect(job: str, trees: list[Path], explicit: bool) -> tuple[dict, list, list]:
    """Read every `<job>_*.log` across `trees`.

    Returns (by_date, tree_reports, duplicates). `explicit` means the caller
    named the trees, in which case a missing one is an error rather than an
    incompleteness note -- you cannot ask for a tree that is not there and get
    a number back.
    """
    by_date: dict[str, dict] = {}
    dups: list[dict] = []
    reports: list[dict] = []
    for tree in trees:
        d = tree / LOG_SUBDIR
        if not d.is_dir():
            if explicit:
                raise FileNotFoundError(
                    f"named log tree has no {LOG_SUBDIR}: {tree}")
            reports.append({"tree": str(tree), "present": False, "n_logs": 0,
                            "reason": f"no {d} — sessions written there are "
                                      f"NOT counted, so the rate is incomplete"})
            continue
        logs = sorted(d.glob(f"{job}_*.log"))
        for p in logs:
            rec = parse_log(p)
            rec["tree"] = str(tree)
            prev = by_date.get(rec["date"])
            if prev is not None:
                dups.append({
                    "date": rec["date"],
                    "trees": [prev["tree"], rec["tree"]],
                    "outcomes": [prev["outcome"], rec["outcome"]],
                    "agree": prev["outcome"] == rec["outcome"]
                             and prev["clean"] == rec["clean"],
                    "used": rec["tree"],
                })
            by_date[rec["date"]] = rec          # last tree wins
        reports.append({"tree": str(tree), "present": True, "n_logs": len(logs),
                        "reason": None,
                        "first": logs[0].name[-14:-4] if logs else None,
                        "last": logs[-1].name[-14:-4] if logs else None})
    return by_date, reports, dups


# --------------------------------------------------------------- measuring ---
def eligible_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """NYSE trading days in [start, end], from the scheduler's own calendar."""
    out, d = [], start
    while d <= end:
        if cal.is_trading_day(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def measure(job: str = "cef", trees: list[Path] | None = None,
            through: dt.date | None = None, since: dt.date | None = None,
            target: int = DEFAULT_TARGET, today: dt.date | None = None) -> dict:
    """The whole measurement as one plain dict. The dashboard calls this.

    `through` defaults to the trading day BEFORE today, and the reason is
    printed rather than hidden: today's session has not finished (cef fires
    17:15 and may poll for NAV until 23:30), so counting it would book an
    in-progress session as a miss. `since` defaults to the first session log
    found, so the window is the book's whole recorded life.
    """
    explicit = trees is not None
    trees = list(trees) if trees is not None else default_trees()
    by_date, tree_reports, dups = collect(job, trees, explicit)

    today = today or dt.date.today()
    excluded_today = None
    if through is None:
        through = cal.previous_trading_day(today)
        if cal.is_trading_day(today):
            excluded_today = (
                f"{today} is a trading day but its session is still in progress "
                f"or has not started; the window ends {through}")
    if not by_date:
        return {"ok": False, "job": job, "complete": False,
                "reason": f"no {job}_*.log found in any of: "
                          + ", ".join(str(t / LOG_SUBDIR) for t in trees),
                "trees": tree_reports}
    if since is None:
        since = dt.date.fromisoformat(min(by_date))

    days = eligible_days(since, through)
    sessions = []
    for d in days:
        key = d.isoformat()
        rec = by_date.get(key)
        if rec is None:
            rec = {"date": key, "job": job, "tree": None, "log": None,
                   "outcome": "no_log", "clean": False, "late_arm": False,
                   "caveat": None, "blockers": [], "codes": [], "primary": None,
                   "reason": "no session log in any named tree — the job did "
                             "not run, or ran somewhere nobody is looking",
                   "started_at": None, "armed_at": None, "asof": None,
                   "done_status": None, "book_run": None, "n_runs": 0,
                   "modelled_turnover_usd": None, "modelled_nav_usd": None,
                   "dryrun_turnover_usd": None,
                   "log_calendar": None, "anomalies": [], "notes": []}
        sessions.append(rec)

    # Logs that exist on a day the exchange was shut. Not misses; reported
    # separately so nobody reconciles the two counts by hand.
    closed = [r for k, r in sorted(by_date.items())
              if since.isoformat() <= k <= through.isoformat()
              and not cal.is_trading_day(dt.date.fromisoformat(k))]

    n = len(sessions)
    armed = [r for r in sessions if r["outcome"] == "armed"]
    clean = [r for r in sessions if r["clean"]]
    misses = [r for r in sessions if r["outcome"] != "armed"]
    indet = [r for r in sessions if r["outcome"] == "indeterminate"]
    nolog = [r for r in sessions if r["outcome"] == "no_log"]

    # A session whose outcome could not be determined makes the rate a guess.
    complete = not indet and all(t["present"] for t in tree_reports)
    incomplete_why = []
    for t in tree_reports:
        if not t["present"]:
            incomplete_why.append(t["reason"])
    for r in indet:
        incomplete_why.append(f"{r['date']}: {r['reason']}")

    # Streaks run BACKWARD from the end of the window: what matters operationally
    # is the run you are in now, not the best one you ever had.
    def _tail_streak(pred):
        k = 0
        for r in reversed(sessions):
            if pred(r):
                k += 1
            else:
                break
        return k

    def _longest(pred):
        best = run = 0
        for r in sessions:
            run = run + 1 if pred(r) else 0
            best = max(best, run)
        return best

    streak_armed = _tail_streak(lambda r: r["outcome"] == "armed")
    streak_clean = _tail_streak(lambda r: r["clean"])

    # Blocker frequency. A session with two blockers counts in BOTH rows, so
    # these sum to >= len(misses); the payload says so rather than leaving the
    # reader to discover it from arithmetic that does not add up.
    bycode: dict[str, dict] = {}
    for r in misses:
        codes = r["codes"] or ["no_log" if r["outcome"] == "no_log"
                               else "indeterminate"]
        for c in codes:
            e = bycode.setdefault(c, {"code": c, "sessions": 0, "dates": [],
                                      "label": CODE_LABEL.get(c),
                                      "endpoints": []})
            e["sessions"] += 1
            e["dates"].append(r["date"])
        for b in r["blockers"]:
            if b.get("endpoint") and b["endpoint"] not in \
                    bycode[b["code"]]["endpoints"]:
                bycode[b["code"]]["endpoints"].append(b["endpoint"])
    blockers = sorted(bycode.values(), key=lambda e: (-e["sessions"], e["code"]))
    for e in blockers:
        e["longest_run"] = _longest(lambda r, c=e["code"]:
                                    c in (r["codes"] or [r["outcome"]]))
        e["first"], e["last"] = e["dates"][0], e["dates"][-1]

    # TODAY, reported separately from the rate and never folded into it.
    # "Has tonight's session armed yet?" is the question the operator actually
    # asks, and it is NOT answerable from the window above, which deliberately
    # ends yesterday. An absent log today is not a miss -- the job has not run --
    # so it is reported as its own state with its own wording.
    tkey = today.isoformat()
    trec = by_date.get(tkey)
    if not cal.is_trading_day(today):
        tstate, tnote = "closed", f"{tkey} is not an NYSE trading day"
    elif trec is None:
        tstate = "not_yet"
        tnote = (f"no {job} session log for {tkey} in any named tree yet — "
                 f"the job has not written one")
    else:
        tstate = trec["outcome"] if not trec["clean"] else "armed"
        tnote = (trec["caveat"] or trec["reason"] or
                 f"armed {trec['armed_at']}")
        if trec["outcome"] == "armed" and trec["clean"]:
            tnote = f"armed {trec['armed_at']}"
    today_block = {"date": tkey, "state": tstate, "note": tnote,
                   "session": trec, "counted_in_window": tkey <= through.isoformat()}

    return {
        "ok": True,
        "job": job,
        "measured_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today": today_block,
        "reproducer": f"python3 -m ops.session_uptime --job {job}",
        "window": {"since": since.isoformat(), "through": through.isoformat(),
                   "excluded_today": excluded_today},
        "trees": tree_reports,
        "duplicates": dups,
        "complete": complete,
        "incomplete_reasons": incomplete_why,
        "n_eligible": n,
        "n_armed": len(armed),
        "n_clean": len(clean),
        "n_missed": len(misses),
        "n_no_log": len(nolog),
        "n_indeterminate": len(indet),
        "arm_rate_pct": round(100.0 * len(armed) / n, 1) if n else None,
        "clean_rate_pct": round(100.0 * len(clean) / n, 1) if n else None,
        "streak_armed": streak_armed,
        "streak_clean": streak_clean,
        "longest_clean_run": _longest(lambda r: r["clean"]),
        "target_consecutive": target,
        "target_met": streak_clean >= target,
        "target_definition": (
            f"{target} consecutive eligible sessions that armed on the session's "
            f"own date, ran the book ok and finished status=ok"),
        "blockers": blockers,
        # Anomalies are reported but never folded into the rate. They are a
        # different question — "is this record trustworthy" rather than "did the
        # book trade" — and mixing them would make one number answer neither.
        "anomalies": [{"date": r["date"], "items": r["anomalies"]}
                      for r in sessions if r["anomalies"]],
        "notes": [{"date": r["date"], "items": r["notes"]}
                  for r in sessions if r["notes"]],
        "closed_days_with_logs": [
            {"date": r["date"], "outcome": r["outcome"]} for r in closed],
        "sessions": sessions,
    }


# ------------------------------------------------------------------- report --
_GLYPH = {"blocked": "x", "no_log": "-", "indeterminate": "?", "closed": "."}


def glyph(rec: dict) -> str:
    """One character per session. A glyph as well as a colour, so the strip is
    readable without colour vision and survives a screenshot in greyscale."""
    if rec["outcome"] == "armed":
        return "A" if rec["clean"] else "a"
    return _GLYPH.get(rec["outcome"], "?")


def render(m: dict) -> str:
    """The text table. Ordered worst-news-first, deliberately."""
    if not m.get("ok"):
        return f"CANNOT MEASURE: {m.get('reason')}"
    L = []
    w = m["window"]
    L.append(f"SESSION UPTIME — job={m['job']}   window {w['since']} .. "
             f"{w['through']}   measured {m['measured_at']}")
    for t in m["trees"]:
        if t["present"]:
            L.append(f"  tree  {t['tree']}   {t['n_logs']} log(s) "
                     f"{t['first']} .. {t['last']}")
        else:
            L.append(f"  tree  {t['tree']}   MISSING — {t['reason']}")
    if w["excluded_today"]:
        L.append(f"  note  {w['excluded_today']}")
    for d in m["duplicates"]:
        L.append(f"  dup   {d['date']} in both trees "
                 f"({'agree' if d['agree'] else 'DISAGREE'}: "
                 f"{'/'.join(d['outcomes'])}); used {d['used']}")
    if not m["complete"]:
        L.append("  INCOMPLETE — this rate is a lower bound, not a measurement:")
        for r in m["incomplete_reasons"]:
            L.append(f"            {r}")
    L.append("")

    t = m["today"]
    L.append(f"  TODAY  {t['date']}  {t['state'].upper()} — {t['note']}")
    L.append("")

    L.append(f"  armed        {m['n_armed']:>3} of {m['n_eligible']} eligible "
             f"({m['arm_rate_pct']}%)")
    L.append(f"  armed clean  {m['n_clean']:>3} of {m['n_eligible']} eligible "
             f"({m['clean_rate_pct']}%)   "
             f"— arm line present AND same-day AND book ok AND status=ok")
    L.append(f"  missed       {m['n_missed']:>3}   "
             f"({m['n_no_log']} with no log at all, "
             f"{m['n_indeterminate']} indeterminate)")
    L.append("")

    if m["blockers"]:
        L.append("  BLOCKERS (a session with two blockers is counted in both "
                 "rows, so these sum to more than the miss count)")
        L.append(f"    {'code':<14} {'sess':>4} {'run':>4}  first..last"
                 f"            what it was")
        for b in m["blockers"]:
            ep = (" [" + ", ".join(b["endpoints"]) + "]") if b["endpoints"] else ""
            L.append(f"    {b['code']:<14} {b['sessions']:>4} {b['longest_run']:>4}"
                     f"  {b['first']}..{b['last']}  "
                     f"{b['label'] or '?'}{ep}")
        L.append("")

    if m["anomalies"]:
        L.append("  ANOMALIES — not folded into the rate; a human should look")
        for a in m["anomalies"]:
            for it in a["items"]:
                L.append(f"    {a['date']}  {it}")
        L.append("")
    if m["notes"]:
        L.append("  NOTES — designed behaviour, recorded so it is not re-diagnosed")
        for a in m["notes"]:
            for it in a["items"]:
                L.append(f"    {a['date']}  {it}")
        L.append("")

    L.append("  PER SESSION")
    L.append(f"    {'date':<11} {'outcome':<14} {'armed at':<20} "
             f"{'done':<11} blocker / caveat")
    for r in m["sessions"]:
        note = r["caveat"] or ""
        if r["outcome"] != "armed":
            p = r["primary"]
            note = ((f"[{p['code']}] " + (f"{p['check']}: " if p["check"] else "")
                     + p["text"]) if p else f"[{r['outcome']}] {r['reason']}")
        oc = r["outcome"] + ("*" if r["outcome"] == "armed" and not r["clean"]
                             else "")
        L.append(f"    {r['date']:<11} {oc:<14} "
                 f"{(r['armed_at'] or '—'):<20} "
                 f"{(r['done_status'] or '—'):<11} {note[:120]}")
    L.append("")

    strip = "".join(glyph(r) for r in m["sessions"])
    L.append(f"  {w['since']}  {strip}  {w['through']}")
    L.append("    A armed clean · a armed with a caveat · x blocked · "
             "- no log · ? indeterminate")
    L.append("")

    L.append(f"  DEFINITION OF DONE   {m['target_definition']}")
    L.append(f"  current clean streak {m['streak_clean']} / "
             f"{m['target_consecutive']}   "
             f"(loose armed streak {m['streak_armed']}; "
             f"longest clean run ever {m['longest_clean_run']})")
    L.append(f"  VERDICT              "
             f"{'MET' if m['target_met'] else 'NOT MET'}"
             f"{'' if m['complete'] else ' — and the measurement is INCOMPLETE'}")
    for r in m["closed_days_with_logs"]:
        L.append(f"  (excluded: {r['date']} was not an NYSE trading day)")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--job", default="cef",
                    help="log prefix: cef, benchmarks, phase0 (default cef)")
    ap.add_argument("--tree", action="append", type=Path, default=None,
                    metavar="PATH",
                    help="repo tree to read logs from; repeatable. Default is "
                         "this tree UNION ~/prod/QUANTT.")
    ap.add_argument("--since", type=dt.date.fromisoformat, default=None,
                    help="window start (default: first session log found)")
    ap.add_argument("--through", type=dt.date.fromisoformat, default=None,
                    help="window end (default: the trading day before today, "
                         "because today's session is not finished)")
    ap.add_argument("--target", type=int, default=DEFAULT_TARGET,
                    help=f"consecutive clean sessions required "
                         f"(default {DEFAULT_TARGET})")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    m = measure(job=a.job, trees=a.tree, through=a.through, since=a.since,
                target=a.target)
    print(json.dumps(m, indent=2) if a.json else render(m))
    if not m.get("ok") or not m.get("complete"):
        return 3
    return 0 if m["target_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
