"""The CEF book's nightly data collector: one data day, six idempotent steps, a report.

    python3 -m quantt.collect --book cef

WHY THIS EXISTS (2026-09-29)
----------------------------
Before this, the panels were refreshed only by the trading session, as its first
step, the evening it trades. A day the session did not run (a refusal, a halt, a
weekend catch-up) left no record of the day at all. The paper account is scored
on two P&Ls, Alpaca's fill and the official closing-auction print (CLAUDE.md
research rules, team lead 2026-09-28), and the auction print is only fetchable
from Alpaca's data API, so a day nobody fetched is a day that can never be
scored. The collector records every trading day whether or not anything traded:
prices and NAV, the official closes, the account, the distributions, and two
cross-checks between independent sources.

WHEN IT RUNS
------------
launchd, every 30 minutes, all day, every day. So it must be cheap and silent
when there is nothing to do: after reading the Alpaca clock and calendar it
prints `IDLE <D> complete` and exits 0 without another network call. Each step
is recorded in `<state>/data/<D>/status.json`; a completed step is never redone
and a failed one is retried on the next slot. NAVs for day D reach yfinance
around 21:21-21:51 ET on D (measured 2026-09-28), so `prices_nav` is expected to
fail for the first few slots of every evening; that is the design, not a fault.

THE DATA DAY D
--------------
The latest date that is a trading day by BOTH Alpaca's /v2/calendar and
`ops/schedule/nyse_calendar`, and whose close + CLOSE_SETTLE has passed by
Alpaca's clock (not this machine's). If the two calendars disagree about any
day examined, the run raises naming both: which one is wrong is a question for a
human, and guessing would record a holiday as a missing day or skip a real one.
When D moves on, an earlier day's unfinished steps are abandoned; its
status.json keeps what did and did not complete.

REPORT ONLY (team lead, 2026-09-29)
-----------------------------------
The two cross-checks (NAV: panel vs CEFConnect; close: panel vs Alpaca's
official auction print) write FLAGS. A flag names both sources and both values.
It never blocks trading, never fails a step, and the two values are never
averaged and neither is picked (CLAUDE.md data rules). A value one source does
not have is a GAP naming the fund, never a substituted number.

READ-ONLY AT THE BROKER
-----------------------
This module calls only the GET methods of `quantt.broker.alpaca.AlpacaClient`.
A test reads this package's source and fails if it names the client's transmit
method. Credentials never pass through here: the client keeps them in its HTTP
session headers, and `account.json` drops the client's `raw` echo and any key
that looks like a credential before it is written.

EXIT CODES
----------
0  complete, or idle (nothing to do).
5  incomplete: at least one step is not ok and will be retried next slot; also
   when another collector run holds the collector lock.
20 unexpected error: recorded in data.log (and status.json when D is known),
   traceback on stderr.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:            # `scripts.cef.spec`, `ops.*` resolve from the repo
    sys.path.insert(0, str(REPO))

from ops.schedule.nyse_calendar import (is_trading_day, next_trading_day,  # noqa: E402
                                        previous_trading_day)
from quantt.broker.alpaca import AlpacaError  # noqa: E402
from quantt.session.records import (StateDirError, state_dir_from_env,  # noqa: E402
                                    write_json_atomic)

ET = ZoneInfo("America/New_York")    # the exchange's clock; D is an ET trading date

# D is ready this long after its close. The auction query below needs the close
# to be more than 15 minutes old (the Basic data plan 403s SIP queries touching
# the last 15 minutes [V: alpaca.py closing_auction_prints]); 45 minutes also
# lets the closing prints settle on the SIP. From the team lead's brief, 2026-09-29.
CLOSE_SETTLE = dt.timedelta(minutes=45)
# `closing_auction_prints` queries a window that ENDS at 16:30 ET on D whatever
# the day's close (alpaca.py, "EXPLICIT TIMESTAMPS"). On an early-close day D is
# ready at 13:45 ET, but that window still touches "the last 15 minutes" until
# 16:45 ET, so the query is held until then rather than sent to be refused.
AUCTION_QUERY_READY = dt.time(16, 45)
CALENDAR_LOOKBACK_DAYS = 14          # verify.py's bound: longer than any US closure cluster
# Cross-check tolerance. Prices and NAVs are quoted to the cent, so any real
# disagreement is at least $0.01; half a cent absorbs float representation only.
# Matches scripts/data/cef_crosscheck_crsp.py's $0.005 (docs/DATA.md section 4).
TOLERANCE_USD = 0.005
PRICES_NAV_TIMEOUT_S = 15 * 60       # must end well inside the 30-minute slot
DISTRIBUTIONS_TIMEOUT_S = 20 * 60
TAIL_LINES = 40

STEPS = ("prices_nav", "nav_crosscheck", "official_closes", "close_crosscheck",
         "account_snapshot", "distributions")
DEPENDS_ON = {"nav_crosscheck": ("prices_nav",),
              "close_crosscheck": ("prices_nav", "official_closes")}

OFFICIAL_CLOSE_FILE = "alpaca_official_close.parquet"
OFFICIAL_CLOSE_COLUMNS = ("date", "ticker", "price", "exchange", "condition", "t",
                          "fetched_at_utc")
EQUITY_COLUMNS = ("date", "equity", "last_equity", "cash", "long_market_value",
                  "short_market_value", "n_positions", "read_at_utc")
# Any account key matching this is dropped before account.json is written. The
# parsed account carries none today; this is for the day Alpaca adds one.
CREDENTIAL_KEY = re.compile(r"key|secret|token|password|auth", re.I)

BOOKS = {"cef": {"book_path": "ops/books/cef_discount_book.json"}}

EXIT_OK, EXIT_INCOMPLETE, EXIT_UNEXPECTED = 0, 5, 20


class CalendarDisagreement(RuntimeError):
    """Alpaca's calendar and nyse_calendar disagree about whether a day trades."""


class StepFailed(RuntimeError):
    """A step did not complete; it is recorded and retried on the next slot."""

    def __init__(self, msg: str, detail: dict | None = None):
        super().__init__(msg)
        self.detail = detail or {}


class CefConnectError(RuntimeError):
    """CEFConnect could not be read (transport, HTTP body, or response shape)."""


@dataclass
class Ctx:
    """Everything a run touches, injected so tests need no network and no real panels."""
    book: str
    client: Any                  # the GET surface of quantt.broker.alpaca.AlpacaClient
    state_dir: Path              # QUANTT_STATE_DIR
    cef_dir: Path                # data/cef
    repo: Path
    book_path: str               # repo-relative, as fetch_daily's --book takes it
    deployed: list               # frozen.universe
    run: Callable                # (cmd, timeout_s) -> (exit code | None on timeout, tail)
    cefconnect_nav: Callable     # (ticker, date) -> float | None; raises CefConnectError
    day: dt.date | None = None   # set once D is known, for the error record


# ------------------------------------------------------------------ the data day

def data_day(client) -> tuple[dt.date, dict]:
    """(D, clock). See the module docstring, THE DATA DAY D.

    Alpaca's calendar `close` is a wall-clock "HH:MM" whose zone the docs do not
    state [U, alpaca.py `calendar`]; it is read as ET here, which is what every
    observed value (16:00, 13:00) is consistent with.
    """
    clk = client.clock()
    now = clk["timestamp"]
    today = now.astimezone(ET).date()
    start = today - dt.timedelta(days=CALENDAR_LOOKBACK_DAYS)
    alpaca = {row["date"]: row for row in client.calendar(start, today)}
    d = today
    while d >= start:
        a, n = d in alpaca, is_trading_day(d)
        if a != n:
            raise CalendarDisagreement(
                f"{d}: Alpaca /v2/calendar says {'trading' if a else 'closed'}, "
                f"ops/schedule/nyse_calendar says {'trading' if n else 'closed'}; "
                f"a human must decide which is wrong before this day is collected")
        if a:
            hh, mm = (int(x) for x in alpaca[d]["close"].split(":"))
            ready = dt.datetime.combine(d, dt.time(hh, mm), ET) + CLOSE_SETTLE
            if ready <= now:
                return d, clk
        d -= dt.timedelta(days=1)
    raise RuntimeError(f"no trading day ready in {start}..{today} by both calendars "
                       f"(Alpaca clock {now.isoformat()})")


# ------------------------------------------------------------------ helpers

def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _tail(text: str) -> str:
    return "\n".join((text or "").splitlines()[-TAIL_LINES:])


def run_subprocess(repo: Path) -> Callable:
    """The real runner: a child process in the repo, output captured, bounded in time.

    A timeout kills the child (subprocess.run does), and a killed fetch_daily
    releases its panel lock with its file descriptor, so a hang costs one slot.
    """
    def run(cmd, timeout_s):
        try:
            p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                               timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"") + (e.stderr or b"")
            text = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            return None, _tail(text)
        return p.returncode, _tail(p.stdout + p.stderr)
    return run


def cefconnect_nav(ticker: str, day: dt.date):
    """CEFConnect's NAV dated exactly `day`, or None -- the SAME endpoint and
    parsing fetch_daily's `--nav-fallback cefconnect` uses (reused, not copied,
    so the two can never read different fields). Imported here, not at module
    top, because it pulls in yfinance and pandas and an idle run needs neither."""
    import pandas as pd
    import requests
    from scripts.cef.fetch_daily import _cefconnect_nav
    try:
        return _cefconnect_nav(ticker, pd.Timestamp(day).normalize())
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        raise CefConnectError(f"{ticker}: {type(e).__name__}: {e}") from e


def _read_parquet(path: Path, what: str):
    import pandas as pd
    if not path.exists():
        raise StepFailed(f"{what} {path} does not exist")
    return pd.read_parquet(path)


def _on_day(frame, day: dt.date):
    import pandas as pd
    return frame[pd.to_datetime(frame["date"]).dt.normalize() == pd.Timestamp(day)]


def _one_value(rows, ticker: str, col: str, what: str):
    """The single value of `col` for `ticker` in `rows`, or None if absent.
    Two rows for one (date, ticker) is a corrupted panel and raises."""
    v = rows.loc[rows["ticker"] == ticker, col]
    if len(v) > 1:
        raise StepFailed(f"{what} has {len(v)} rows for {ticker}; expected one")
    return None if v.empty else float(v.iloc[0])


def _compare(fund, source_a, value_a, source_b, value_b) -> dict | None:
    if abs(value_a - value_b) > TOLERANCE_USD:
        return {"fund": fund, "source_a": source_a, "value_a": value_a,
                "source_b": source_b, "value_b": value_b,
                "diff": round(value_a - value_b, 6)}
    return None


# ------------------------------------------------------------------ the steps
# Each returns a detail dict with "flags" and "gaps" lists, or raises StepFailed.

def step_prices_nav(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """fetch_daily as the session runs it, for D. Its exit code is the verdict:
    0 = every deployed name has a close and a NAV dated D. 4 is the expected
    answer before the evening's NAVs land; 3 is the panel lock (another fetch)."""
    cmd = [sys.executable, "scripts/cef/fetch_daily.py", "--require-asof", day.isoformat(),
           "--nav-fallback", "cefconnect", "--book", ctx.book_path]
    code, tail = ctx.run(cmd, PRICES_NAV_TIMEOUT_S)
    detail = {"exit": code, "tail": tail, "flags": [], "gaps": []}
    if code is None:
        raise StepFailed(f"fetch_daily timed out after {PRICES_NAV_TIMEOUT_S}s", detail)
    if code != 0:
        raise StepFailed(f"fetch_daily exited {code}", detail)
    return detail


def _fallback_names(cef_dir: Path, day: dt.date) -> set:
    """Deployed names whose panel NAV for D was WRITTEN from CEFConnect by
    fetch_daily's fallback (its log). Comparing those against CEFConnect is
    comparing a source with itself, so they are reported as gaps, not passes."""
    import pandas as pd
    log = cef_dir / "nav_fallback_log.csv"
    if not log.exists():
        return set()
    f = pd.read_csv(log)
    return set(f.loc[pd.to_datetime(f["date"]).dt.normalize() == pd.Timestamp(day), "ticker"])


def step_nav_crosscheck(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Panel NAV (yfinance) vs CEFConnect's NAV for D, per deployed name. Report only."""
    rows = _on_day(_read_parquet(ctx.cef_dir / "cef_nav.parquet", "NAV panel"), day)
    same_source = _fallback_names(ctx.cef_dir, day)
    flags, gaps, errors = [], [], []
    for t in ctx.deployed:
        panel = _one_value(rows, t, "nav", "cef_nav.parquet")
        if panel is None:
            gaps.append({"fund": t, "reason": f"cef_nav.parquet has no NAV dated {day}"})
            continue
        if t in same_source:
            gaps.append({"fund": t, "reason": f"panel NAV for {day} was written from CEFConnect "
                                              f"(nav_fallback_log.csv); not an independent check"})
            continue
        try:
            cc = ctx.cefconnect_nav(t, day)
        except CefConnectError as e:
            errors.append(str(e))
            continue
        if cc is None:
            gaps.append({"fund": t, "reason": f"CEFConnect has no NAV dated {day}"})
            continue
        f = _compare(t, "cef_nav.parquet (yfinance)", panel, "cefconnect", float(cc))
        if f:
            flags.append(f)
    detail = {"flags": flags, "gaps": gaps, "fetch_errors": errors}
    if errors:
        # Not measured is not "no disagreement": retry next slot.
        raise StepFailed(f"CEFConnect unreadable for {len(errors)} fund(s)", detail)
    return detail


def step_official_closes(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Alpaca's official closing-auction print (primary listing, condition M) for D,
    for every name in cef_universe.csv and every deployed name.

    One query per symbol, as `quantt/session/verify.py::fetch_prints` does, so one
    name's error is that name's gap. Not a call to fetch_prints itself: it keeps
    only the price, and this record needs the exchange, condition and timestamp
    too. Names already stored for D are not re-queried on a retry.
    """
    import pandas as pd
    import ops.common as common          # at call time, so the test harness's write guard applies
    now = clk["timestamp"]
    ready = dt.datetime.combine(day, AUCTION_QUERY_READY, ET)
    if now < ready:
        raise StepFailed(f"auction prints for {day} are not queryable on the Basic data "
                         f"plan until {ready.isoformat()}",
                         {"flags": [], "gaps": []})
    uni_path = ctx.cef_dir / "cef_universe.csv"
    if not uni_path.exists():
        raise StepFailed(f"{uni_path} does not exist; it names the symbols to fetch",
                         {"flags": [], "gaps": []})
    symbols = sorted(set(pd.read_csv(uni_path)["ticker"]) | set(ctx.deployed))
    path = ctx.cef_dir / OFFICIAL_CLOSE_FILE
    old = pd.read_parquet(path) if path.exists() else None
    have = set(_on_day(old, day)["ticker"]) if old is not None else set()

    exchanges = ctx.client.stock_exchanges()
    rows, gaps = [], []
    fetched_at = _utc_now()
    for sym in [s for s in symbols if s not in have]:
        try:
            code = ctx.client.primary_sip_code(sym, exchanges)
            got = ctx.client.closing_auction_prints([sym], day, exchange_codes={sym: code},
                                                    condition="M")
        except AlpacaError as e:
            gaps.append({"fund": sym, "reason": f"{type(e).__name__}: {e}"})
            continue
        if sym not in got:
            raise ValueError(f"closing_auction_prints returned no row and no error for {sym}")
        p = got[sym]
        rows.append({"date": pd.Timestamp(day), "ticker": sym, "price": float(p["price"]),
                     "exchange": p["exchange"], "condition": p["condition"], "t": str(p["t"]),
                     "fetched_at_utc": fetched_at})
    if rows:
        new = pd.DataFrame(rows, columns=list(OFFICIAL_CLOSE_COLUMNS))
        frame = new if old is None else pd.concat([old, new], ignore_index=True)
        frame = (frame.drop_duplicates(subset=["date", "ticker"], keep="last")
                      .sort_values(["date", "ticker"]).reset_index(drop=True))
        common.atomic_write(frame, path)
    stored = have | {r["ticker"] for r in rows}
    missing = [t for t in ctx.deployed if t not in stored]
    detail = {"flags": [], "gaps": gaps, "stored_now": len(rows), "stored_before": len(have)}
    if missing:
        raise StepFailed(f"no official close for deployed name(s) {missing}", detail)
    return detail


def step_close_crosscheck(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Alpaca official close vs panel close (yfinance) for D, per deployed name. Report only."""
    px = _on_day(_read_parquet(ctx.cef_dir / "cef_prices.parquet", "price panel"), day)
    oc = _on_day(_read_parquet(ctx.cef_dir / OFFICIAL_CLOSE_FILE, "official-close file"), day)
    flags, gaps = [], []
    for t in ctx.deployed:
        a = _one_value(oc, t, "price", OFFICIAL_CLOSE_FILE)
        b = _one_value(px, t, "close", "cef_prices.parquet")
        if a is None or b is None:
            which = [n for n, v in (("alpaca official close", a), ("panel close", b)) if v is None]
            gaps.append({"fund": t, "reason": f"no {' and no '.join(which)} dated {day}"})
            continue
        f = _compare(t, "alpaca official close (M, primary)", a, "cef_prices.parquet (yfinance)", b)
        if f:
            flags.append(f)
    return {"flags": flags, "gaps": gaps}


def _scrub_account(acct: dict) -> dict:
    return {k: v for k, v in acct.items() if k != "raw" and not CREDENTIAL_KEY.search(k)}


def _write_equity_row(path: Path, row: dict) -> None:
    """Replace D's row (or add it) in equity.csv; temp file, fsync, rename."""
    rows = []
    if path.exists():
        with open(path, newline="") as fh:
            rd = csv.DictReader(fh)
            if tuple(rd.fieldnames or ()) != EQUITY_COLUMNS:
                raise StepFailed(f"{path} has columns {rd.fieldnames}, expected {list(EQUITY_COLUMNS)}")
            rows = [r for r in rd if r["date"] != row["date"]]
    rows.append({k: row[k] for k in EQUITY_COLUMNS})
    rows.sort(key=lambda r: r["date"])
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=EQUITY_COLUMNS)
        w.writeheader()
        w.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def step_account_snapshot(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Account, positions, orders and fills as of D's close.

    Only valid until the next session opens: after that, equity and positions
    describe a later day, and writing them under D would be a confident wrong
    number. So the step refuses unless the market is shut and Alpaca's next open
    is the first trading day after D. Whether pre-market quotes move paper
    equity before 09:30 is not established [U].

    Orders: from 00:00 ET on the trading day BEFORE D, not the calendar day,
    because the orders for D's auction are submitted the evening before and for
    a Monday that evening is Friday's.
    """
    nxt = next_trading_day(day)
    next_open = clk["next_open"].astimezone(ET)
    if clk["is_open"] or next_open.date() != nxt:
        raise StepFailed(
            f"the account no longer describes {day}'s close (market open={clk['is_open']}, "
            f"next open {next_open.isoformat()}, first trading day after {day} is {nxt}); "
            f"not recorded rather than recorded under the wrong day",
            {"flags": [], "gaps": []})
    read_at = _utc_now()
    acct = _scrub_account(ctx.client.account())
    pos = ctx.client.positions()
    since = dt.datetime.combine(previous_trading_day(day), dt.time(0, 0), ET)
    orders = ctx.client.orders(status="all", after=since)
    fills = ctx.client.activities_fills(day)
    day_dir = ctx.state_dir / "data" / day.isoformat()
    write_json_atomic(day_dir / "account.json", {
        "date": day, "read_at_utc": read_at, "orders_submitted_after": since,
        "account": acct, "positions": {"qty": pos.qty, "raw": pos.raw},
        "orders": orders, "fills": fills})
    _write_equity_row(ctx.state_dir / "equity.csv", {
        "date": day.isoformat(), "equity": acct["equity"], "last_equity": acct["last_equity"],
        "cash": acct["cash"], "long_market_value": acct["long_market_value"],
        "short_market_value": acct["short_market_value"], "n_positions": len(pos.qty),
        "read_at_utc": read_at})
    return {"flags": [], "gaps": [], "n_positions": len(pos.qty), "n_orders": len(orders),
            "n_fills": len(fills)}


def step_distributions(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """scripts/fetch_cef_distributions.py, which reads cef_universe.csv at import."""
    uni = ctx.cef_dir / "cef_universe.csv"
    if not uni.exists():
        raise StepFailed(f"{uni} does not exist; fetch_cef_distributions.py needs it",
                         {"flags": [], "gaps": []})
    code, tail = ctx.run([sys.executable, "scripts/fetch_cef_distributions.py"],
                         DISTRIBUTIONS_TIMEOUT_S)
    detail = {"exit": code, "tail": tail, "flags": [], "gaps": []}
    if code is None:
        raise StepFailed(f"fetch_cef_distributions timed out after {DISTRIBUTIONS_TIMEOUT_S}s", detail)
    if code != 0:
        raise StepFailed(f"fetch_cef_distributions exited {code}", detail)
    return detail


STEP_FUNCS = {"prices_nav": step_prices_nav, "nav_crosscheck": step_nav_crosscheck,
              "official_closes": step_official_closes, "close_crosscheck": step_close_crosscheck,
              "account_snapshot": step_account_snapshot, "distributions": step_distributions}


# ------------------------------------------------------------------ the run

def _load_status(path: Path, day: dt.date) -> dict:
    import json
    if not path.exists():
        return {"date": day.isoformat(), "steps": {}}
    s = json.loads(path.read_text())
    if s.get("date") != day.isoformat() or not isinstance(s.get("steps"), dict):
        raise ValueError(f"{path} is not a status record for {day}")
    return s


def build_report(day: dt.date, book: str, status: dict) -> dict:
    steps = status["steps"]
    failed = [s for s in STEPS if not steps.get(s, {}).get("ok")]
    flags, gaps = [], []
    for s in STEPS:
        detail = steps.get(s, {}).get("detail", {})
        flags += [{"step": s, **f} for f in detail.get("flags", [])]
        gaps += [{"step": s, **g} for g in detail.get("gaps", [])]
    return {"date": day.isoformat(), "book": book, "complete": not failed,
            "failed_steps": failed, "flags": flags, "gaps": gaps, "steps": steps,
            "written_at_utc": _utc_now()}


def log_line(report: dict) -> str:
    what = ("COMPLETE" if report["complete"]
            else "INCOMPLETE " + ",".join(report["failed_steps"]))
    return (f"{report['date']} DATA {what} flags={len(report['flags'])} "
            f"gaps={len(report['gaps'])}")


def _append_log(state_dir: Path, line: str) -> None:
    with open(state_dir / "data.log", "a") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def collect(ctx: Ctx, out=print) -> int:
    """One invocation: find D, run every step not yet ok, report. Returns the exit code."""
    day, clk = data_day(ctx.client)
    ctx.day = day
    day_dir = ctx.state_dir / "data" / day.isoformat()
    status_path = day_dir / "status.json"
    status = _load_status(status_path, day)
    pending = [s for s in STEPS if not status["steps"].get(s, {}).get("ok")]
    if not pending:
        out(f"IDLE {day} complete")
        return EXIT_OK
    day_dir.mkdir(parents=True, exist_ok=True)
    for name in pending:
        blocked = [d for d in DEPENDS_ON.get(name, ())
                   if not status["steps"].get(d, {}).get("ok")]
        if blocked:
            rec = {"ok": False, "err": f"waiting on {','.join(blocked)}",
                   "detail": {"flags": [], "gaps": []}}
        else:
            try:
                rec = {"ok": True, "err": None,
                       "detail": STEP_FUNCS[name](ctx, day, clk, status)}
            except StepFailed as e:
                rec = {"ok": False, "err": str(e), "detail": e.detail}
            except AlpacaError as e:
                rec = {"ok": False, "err": f"{type(e).__name__}: {e}",
                       "detail": {"flags": [], "gaps": []}}
        rec["at"] = _utc_now()
        status["steps"][name] = rec
        write_json_atomic(status_path, status)     # after every step: a crash keeps progress
    report = build_report(day, ctx.book, status)
    write_json_atomic(day_dir / "report.json", report)
    line = log_line(report)
    _append_log(ctx.state_dir, line)
    out(line)
    return EXIT_OK if report["complete"] else EXIT_INCOMPLETE


class _CollectorLock:
    """Non-blocking exclusive flock on <state>/data/.collect.lock.

    launchd does not start a second copy of a job that is still running, but a
    manual run can overlap a scheduled one, and two runs would both write
    status.json and both append to the official-close file. The second one
    exits 5 and says so; the next slot retries.
    """

    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def build_ctx(book: str, state_dir: Path) -> Ctx:
    from quantt.broker.alpaca import AlpacaClient
    from scripts.cef.spec import frozen
    return Ctx(book=book, client=AlpacaClient.from_environment(book), state_dir=state_dir,
               cef_dir=REPO / "data" / "cef", repo=REPO,
               book_path=BOOKS[book]["book_path"], deployed=sorted(frozen("universe")),
               run=run_subprocess(REPO), cefconnect_nav=cefconnect_nav)


def main(argv=None, *, make_ctx=build_ctx, env=None) -> int:
    ap = argparse.ArgumentParser(prog="quantt.collect",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--book", required=True, choices=sorted(BOOKS))
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        state_dir = state_dir_from_env(env)
    except StateDirError as e:       # nowhere to record it: stderr, exit 20
        print(f"DATA ERROR {e}", file=sys.stderr)
        return EXIT_UNEXPECTED
    lock = _CollectorLock(state_dir / "data" / ".collect.lock")
    if not lock.acquire():
        print(f"BUSY another collector run holds {lock.path}; the next slot retries")
        return EXIT_INCOMPLETE
    ctx = None
    try:
        ctx = make_ctx(args.book, state_dir)
        return collect(ctx)
    except Exception as e:  # noqa: BLE001 -- recorded below, traceback to stderr, exit 20
        traceback.print_exc()
        _record_unexpected(state_dir, ctx.day if ctx is not None else None, e)
        return EXIT_UNEXPECTED
    finally:
        lock.release()


def _record_unexpected(state_dir: Path, day: dt.date | None, e: Exception) -> None:
    """data.log always; status.json too when D is known. The message is one line."""
    msg = " ".join(f"{type(e).__name__}: {e}".split())
    label = day.isoformat() if day else "????-??-??"
    _append_log(state_dir, f"{label} DATA ERROR {msg}")
    print(f"{label} DATA ERROR {msg}")
    if day is not None:
        path = state_dir / "data" / day.isoformat() / "status.json"
        status = _load_status(path, day)
        status["unexpected"] = {"err": msg, "at": _utc_now()}
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, status)
