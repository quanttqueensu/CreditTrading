"""The decide-time stale-NAV gate: a NAV dated D that repeats the previous one is checked against CEFConnect.

THE DEFECT (results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5; docs/REFERENCES.md §12n)
-----------------------------------------------------------------------------------
Yahoo serves a NAV row dated D that still carries D-1's NAV, and corrects it
later. `scripts/cef/fetch_daily.py --require-asof D` checks the DATE of each
deployed name's NAV, not its value, so it passes such a row as "today's pair".
Inverting the z each laptop paper session printed (as-of 2026-09-28 ->
2026-10-07): on 28 of 73 checkable name-days the session decided on NAV(D-1),
and 11 orders that reached the broker were sized on one. Deciding later does
not cure it: plans written 20-23 hours after the close still used stale rows
(note §5, "Timing does not cure it"). Yahoo then corrects the row, so neither
the backtest panel nor a later check of yfinance can see it.

THE REMEDY (team lead, 2026-10-13: "Use CEFConnect, else drop")
-----------------------------------------------------------------
At decide time, after the refresh, for each deployed name whose panel NAV for
D equals its previous NAV row to the cent, read CEFConnect's daily row for D:

  * CEFConnect has D and differs by more than half a cent -> STALE COPY. The
    panel row is replaced by CEFConnect's value, through the logged fallback
    fetch_daily already uses for a missing NAV: written under the panel lock,
    appended to `data/cef/nav_fallback_log.csv` with source
    `cefconnect_stale_copy`. CEFConnect is the right source on a stale copy:
    yfinance's next change carries the move it skipped (slope 1.19, s.e. 0.04,
    n = 414 weekly rows; note §1, "Who is right on a stale copy").
  * CEFConnect has D and agrees -> GENUINE REPEAT, kept. NAVs genuinely repeat
    on about a fifth of name-days (note §1, the repeat-share table).
  * CEFConnect has no row for D, or cannot be read -> UNVERIFIED. The name is
    DROPPED for the day through the sleeve's own drop path, the one
    `max_nav_age_bd` uses (`extras["nav_unverified"]` in
    `src/deploy/sleeves/cef_discount.py`), and the reason -- with the error,
    named, when CEFConnect raised -- is in the record. A CEFConnect NAV that is
    not a finite positive number is treated as unreadable, never written.

What a drop does to the book is the sleeve's, not this module's: a dropped
name leaves the cross-section and its target is zero, so the band holds a
held position whose weight is inside `band_width` and trades one outside it to
the band edge; a name not held is not opened. If drops leave fewer than
`min_names` eligible names, the sleeve's existing rule applies unchanged: every
name is emitted FLAT ("cef: only N eligible names"), before the band.

"Equal to the cent" is |a - b| <= half a cent: NAVs are quoted in cents and
yfinance stores them as float32, so a stale copy is bit-identical but a
CEFConnect fill of the same cent (12.56 against 12.5600004) is not. Half a cent
is the collector's own tolerance (`quantt/collect/collect.py` TOLERANCE_USD).

WHY A RUNNER SETTING, NOT A FROZEN-SPEC KEY
-------------------------------------------
The frozen spec states the strategy the research measured, on panels where
Yahoo had long since corrected these rows. This gate restores the NAV the
research assumed; it has no backtest counterpart. It is a check on the live
capture, like gate 5, so it lives beside the other runner settings in the
book json (`execution.mode`, `execution.bp_shortfall`), with the same
convention: ABSENT is today's behaviour, and enabling it is one reviewed edit
of `ops/books/cef_discount_book.json` (`"data": {"stale_nav": <mode>}`;
`/spec-change` covers that file).

MODES (`MODES`)
  cefconnect_else_drop   the remedy above.
  report                 the same checks and the same record, and nothing
                         else: no panel write, no drop. For measuring how often
                         the gate would bind at the real decide time before it
                         acts. An error in this mode is recorded as UNMEASURED
                         and never stops the session (run.py `_nav_gate`).

H14. Nothing here keys on a number from a document: every binding is measured
at run time and recorded (name, D, the panel NAV(D), the previous row's date
and NAV, CEFConnect's value or "absent" or the error, the verdict and the
action) in the run record, in plan.json and in `<state>/nav_gate.csv`.

Imports only the standard library at module level: `quantt.collect.collect`
imports this module at its top, and an idle collector run must stay cheap
(pytest.ini). pandas, requests and fetch_daily are imported where used.
"""
from __future__ import annotations

import contextlib
import csv
import datetime as dt
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Half a cent. See the module docstring for why "equal" means "equal to the cent".
TOLERANCE_USD = 0.005

ACT = "cefconnect_else_drop"
REPORT = "report"
MODES = (REPORT, ACT)

STALE_COPY, GENUINE_REPEAT, UNVERIFIED = "stale_copy", "genuine_repeat", "unverified"
ACTIONS = {STALE_COPY: "replaced", GENUINE_REPEAT: "kept", UNVERIFIED: "dropped"}
REPORT_ACTION = "none (report mode)"

# The `source` written to data/cef/nav_fallback_log.csv for a replaced stale
# copy; fetch_daily's missing-NAV fallback writes "cefconnect". The collector
# treats every logged row for D as written from CEFConnect (a same-source gap),
# which is what a replaced row is.
FALLBACK_SOURCE = "cefconnect_stale_copy"

CSV_NAME = "nav_gate.csv"
CSV_COLUMNS = ("written_utc", "run", "session_date", "asof", "gate_mode", "ticker", "nav_d",
               "prev_date", "nav_prev", "cefconnect_nav", "cefconnect_status", "verdict",
               "action")


class CefConnectError(RuntimeError):
    """CEFConnect could not be read (transport, HTTP body, or response shape)."""


def cefconnect_nav(ticker: str, day: dt.date):
    """CEFConnect's NAV dated exactly `day`, or None -- the SAME endpoint and
    parsing fetch_daily's `--nav-fallback cefconnect` uses (reused, not copied,
    so the session, the collector and the fallback can never read different
    fields). Transport and shape errors are raised as CefConnectError, naming
    the fund. Moved here from `quantt/collect/collect.py` on 2026-10-13 so the
    session's gate and the collector share one reader; collect re-exports it.
    Imported lazily because it pulls in yfinance and pandas."""
    import pandas as pd
    import requests
    from scripts.cef.fetch_daily import _cefconnect_nav
    try:
        return _cefconnect_nav(ticker, pd.Timestamp(day).normalize())
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        raise CefConnectError(f"{ticker}: {type(e).__name__}: {e}") from e


def differs(a: float, b: float) -> bool:
    """True when two NAVs are different cents (|a - b| > half a cent)."""
    return abs(float(a) - float(b)) > TOLERANCE_USD


# ------------------------------------------------------------------ measuring

@dataclass(frozen=True)
class Repeat:
    """A name whose panel NAV for `asof` equals its previous NAV row to the cent."""
    ticker: str
    asof: dt.date
    nav_d: float
    prev_date: dt.date
    nav_prev: float


def repeats(nav, asof: dt.date, universe) -> list[Repeat]:
    """The universe names whose NAV dated `asof` equals their previous NAV row.

    `nav` is the NAV panel (columns date, ticker, nav). NO LOOKAHEAD: rows after
    `asof` are dropped before anything is read, and the previous row's date is
    asserted < `asof`. The previous row is the name's last row before `asof`,
    whatever its date (recorded): a carried-forward value repeats the last value
    Yahoo served, which is that row. A duplicate (date, ticker) for a universe
    name raises: which of two values is the NAV cannot be chosen silently. A
    name with no finite positive NAV dated `asof`, or no earlier one, is not a
    repeat -- a missing as-of NAV is gate 5's to refuse, not this gate's.
    """
    import pandas as pd
    n = nav[nav["ticker"].isin(list(universe))][["date", "ticker", "nav"]].copy()
    n["date"] = pd.to_datetime(n["date"]).dt.normalize()
    n = n[n["date"] <= pd.Timestamp(asof)]
    dup = n[n.duplicated(["date", "ticker"], keep=False)]
    if len(dup):
        raise ValueError(f"NAV panel has duplicate (date, ticker) rows, e.g. "
                         f"{dup.head(3).to_dict('records')}")
    n = n[n["nav"].notna() & (n["nav"] > 0)]
    out = []
    for tk in sorted(universe):
        rows = n[n["ticker"] == tk].sort_values("date")
        if len(rows) < 2 or rows["date"].iloc[-1] != pd.Timestamp(asof):
            continue
        nav_d, nav_prev = float(rows["nav"].iloc[-1]), float(rows["nav"].iloc[-2])
        prev_date = rows["date"].iloc[-2].date()
        assert prev_date < asof, f"lookahead: {tk} previous NAV dated {prev_date} >= {asof}"
        if not differs(nav_d, nav_prev):
            out.append(Repeat(tk, asof, nav_d, prev_date, nav_prev))
    return out


@dataclass(frozen=True)
class Binding:
    """One repeat, what CEFConnect said about it, and what the gate did."""
    repeat: Repeat
    cefconnect_nav: float | None
    cefconnect_status: str        # "present" | "absent" | "error: <what>"
    verdict: str                  # STALE_COPY | GENUINE_REPEAT | UNVERIFIED
    action: str                   # ACTIONS[verdict], or REPORT_ACTION

    def reason(self) -> str:
        r = self.repeat
        cc = {"present": f"CEFConnect {self.cefconnect_nav}",
              "absent": f"CEFConnect has no NAV dated {r.asof}"}.get(
            self.cefconnect_status, f"CEFConnect {self.cefconnect_status}")
        return (f"NAV {r.asof} {r.nav_d:.2f} = NAV {r.prev_date} {r.nav_prev:.2f} "
                f"(yfinance repeat); {cc}")

    def to_dict(self) -> dict:
        r = self.repeat
        return {"ticker": r.ticker, "asof": r.asof, "nav_d": r.nav_d,
                "prev_date": r.prev_date, "nav_prev": r.nav_prev,
                "cefconnect_nav": self.cefconnect_nav,
                "cefconnect_status": self.cefconnect_status,
                "verdict": self.verdict, "action": self.action}


def classify(rep: Repeat, reader: Callable) -> tuple[float | None, str, str]:
    """(CEFConnect value or None, cefconnect_status, verdict) for one repeat.

    `reader(ticker, date)` returns CEFConnect's NAV dated `date` or None, and
    raises CefConnectError when CEFConnect cannot be read. Only that error is
    caught, and it is named in the status: anything else is a bug and raises.
    """
    try:
        v = reader(rep.ticker, rep.asof)
    except CefConnectError as e:
        return None, f"error: {e}", UNVERIFIED
    if v is None:
        return None, "absent", UNVERIFIED
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or not math.isfinite(float(v)) or float(v) <= 0:
        return None, f"error: CEFConnect NAV {v!r} for {rep.asof} is not a finite positive " \
                     f"number", UNVERIFIED
    v = float(v)
    return v, "present", (STALE_COPY if differs(rep.nav_d, v) else GENUINE_REPEAT)


@dataclass(frozen=True)
class GateResult:
    mode: str
    asof: dt.date
    checked_utc: dt.datetime
    universe: tuple
    bindings: tuple               # of Binding, one per repeat, in ticker order

    @property
    def replaced(self) -> dict:
        """{ticker: CEFConnect NAV} written into the panel (act mode only)."""
        if self.mode != ACT:
            return {}
        return {b.repeat.ticker: b.cefconnect_nav for b in self.bindings
                if b.verdict == STALE_COPY}

    @property
    def dropped(self) -> dict:
        """{ticker: reason} the sleeve drops for the day (act mode only)."""
        if self.mode != ACT:
            return {}
        return {b.repeat.ticker: b.reason() for b in self.bindings if b.verdict == UNVERIFIED}

    def to_dict(self) -> dict:
        return {"mode": self.mode, "asof": self.asof, "checked_utc": self.checked_utc,
                "n_universe": len(self.universe), "n_repeats": len(self.bindings),
                "bindings": [b.to_dict() for b in self.bindings],
                "replaced": sorted(self.replaced), "dropped": sorted(self.dropped)}

    def lines(self) -> list[str]:
        """The session log's lines for this gate."""
        head = (f"  NAV GATE ({self.mode}) as-of {self.asof}: {len(self.bindings)} of "
                f"{len(self.universe)} deployed names repeat their previous NAV")
        if self.mode == ACT:
            head += (f"; replaced {len(self.replaced)}, kept "
                     f"{sum(b.verdict == GENUINE_REPEAT for b in self.bindings)}, "
                     f"dropped {len(self.dropped)}")
        return [head] + [f"    {b.repeat.ticker}: {b.reason()} -> {b.verdict}, {b.action}"
                         for b in self.bindings]


# ------------------------------------------------------------------ acting

@dataclass
class PanelGate:
    """The gate against the real NAV panel. Paths and the CEFConnect reader are
    injected so tests touch neither data/ nor the network."""
    nav_path: Path
    log_path: Path
    lock_path: Path
    reader: Callable = cefconnect_nav
    lock_wait_s: float | None = None     # None: fetch_daily.LOCK_WAIT_S

    def _lock(self):
        from scripts.cef import fetch_daily as fd
        wait = fd.LOCK_WAIT_S if self.lock_wait_s is None else self.lock_wait_s
        return fd.panel_lock(self.lock_path, wait, fd.LOCK_POLL_S)

    def run(self, asof: dt.date, universe, mode: str, now: dt.datetime) -> GateResult:
        """Measure, and in act mode replace stale copies in the panel.

        Act mode holds fetch_daily's panel lock from the read to the write, so
        a fetch (the collector's or another session's) cannot interleave: it
        waits, as it waits for any refresh. Report mode only reads (the panel
        is written atomically, so a read sees a whole file)."""
        import pandas as pd
        if mode not in MODES:
            raise ValueError(f"stale-NAV gate mode {mode!r} is not one of {MODES}")
        universe = tuple(sorted(universe))
        with (self._lock() if mode == ACT else contextlib.nullcontext()):
            N = pd.read_parquet(self.nav_path)
            out = []
            for rep in repeats(N, asof, universe):
                v, status, verdict = classify(rep, self.reader)
                out.append(Binding(rep, v, status, verdict,
                                   ACTIONS[verdict] if mode == ACT else REPORT_ACTION))
            res = GateResult(mode, asof, now, universe, tuple(out))
            if res.replaced:
                self._write(N, asof, res.replaced)
        return res

    def _write(self, N, asof: dt.date, replaced: dict) -> None:
        """fetch_daily's fallback convention: merge, atomic write, append the log."""
        import pandas as pd
        import ops.common as common          # at call time: the test harness's write guard
        from scripts.cef import fetch_daily as fd
        F = pd.DataFrame([{"date": pd.Timestamp(asof), "nav": v, "ticker": t}
                          for t, v in sorted(replaced.items())])
        common.atomic_write(fd.merge_nav_fills(N, F), self.nav_path)
        fd.log_nav_fills(F, FALLBACK_SOURCE, self.log_path)

    def still_holds(self, res: GateResult) -> list[str]:
        """What changed in the panel since `res`, or [] -- read AFTER the sleeve.

        WHY. The lock is released before the sleeve reads the panel. A fetch
        that ran in between (the collector's, every 30 minutes) would write
        yfinance's rows back, a stale copy included, and the sleeve would decide
        on it with nothing saying so. The gate's own writes are the only ones
        that put CEFConnect's value in a stale row, so if every replaced row
        still holds it and no repeat exists that the gate did not judge, the
        panel the sleeve read in between was the one the gate certified."""
        import pandas as pd
        if res.mode != ACT:
            return []
        N = pd.read_parquet(self.nav_path)
        d = N[(pd.to_datetime(N["date"]).dt.normalize() == pd.Timestamp(res.asof))
              & N["ticker"].isin(list(res.universe))]
        now = {t: float(v) for t, v in zip(d["ticker"], d["nav"])}
        bad = [f"{t}: replaced with {v} but the panel now holds {now.get(t)}"
               for t, v in res.replaced.items() if t not in now or differs(now[t], v)]
        judged = {b.repeat.ticker for b in res.bindings if b.verdict != STALE_COPY}
        bad += [f"{r.ticker}: a repeat ({r.nav_d} = {r.nav_prev} on {r.prev_date}) the gate "
                f"did not judge" for r in repeats(N, res.asof, res.universe)
                if r.ticker not in judged]
        return bad


# ------------------------------------------------------------------ recording

def append_csv(path: Path, res: GateResult, *, run: str, session_date: dt.date,
               written_utc: dt.datetime) -> None:
    """One row per repeat to `<state>/nav_gate.csv`; a run with none writes one
    row with an empty ticker and verdict `no_repeat`, so the file alone counts
    how many decides ran the gate (the denominator of how often it binds).
    Appended and fsynced; a file whose header is not CSV_COLUMNS raises rather
    than be written into."""
    if path.exists():
        with open(path, newline="") as fh:
            head = next(csv.reader(fh), None)
        if tuple(head or ()) != CSV_COLUMNS:
            raise ValueError(f"{path} has columns {head}, expected {list(CSV_COLUMNS)}")
    common = {"written_utc": written_utc.isoformat(), "run": run,
              "session_date": session_date.isoformat(), "asof": res.asof.isoformat(),
              "gate_mode": res.mode}
    rows = [{**common, **{k: ("" if v is None else (v.isoformat() if isinstance(v, dt.date)
                                                    else v))
                          for k, v in b.to_dict().items() if k != "asof"}}
            for b in res.bindings]
    if not rows:
        rows = [{**common, "ticker": "", "nav_d": "", "prev_date": "", "nav_prev": "",
                 "cefconnect_nav": "", "cefconnect_status": "", "verdict": "no_repeat",
                 "action": "none"}]
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())
