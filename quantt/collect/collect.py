"""The CEF book's nightly data collector: one data day, nine idempotent steps, a report.

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
cross-checks between independent sources. From 2026-10-09 it also records Alpaca's whole active
asset list with its borrow flags (`borrow_snapshot`). Alpaca keeps no history of
which names could be shorted on which day, and short sleeves need that history
(`results/cef/RESEARCH_PLAN_2026-10-09.md` 0.3). From 2026-10-19 it keeps the
book's official daily P&L series, Alpaca's end-of-day equity history, in
`<state>/eod_equity.csv` (`step_eod_equity`, team lead's ruling of that day).

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

CEFCONNECT ARRIVAL (team lead, 2026-10-13)
------------------------------------------
`cefconnect_arrival` is a WATCH step: it polls CEFConnect each slot until every
deployed name's row for D has appeared, and logs when it first did
(`<state>/cefconnect_arrival.csv`). It keeps the collector from idling but never
makes the day INCOMPLETE; the log line says `watching=cefconnect_arrival` while
it runs (`step_cefconnect_arrival`).

REPORT ONLY (team lead, 2026-09-29)
-----------------------------------
The two cross-checks (NAV: panel vs CEFConnect; close: panel vs Alpaca's
official auction print) write FLAGS. A flag names both sources and both values.
It never blocks trading, never fails a step, and the two values are never
averaged and neither is picked (CLAUDE.md data rules). A value one source does
not have is a GAP naming the fund, never a substituted number -- with one
exception since 2026-10-13: a panel NAV for D that repeats the previous NAV
while CEFConnect has no row for D is a FLAG (`nav_repeat_unverified`), because
that is how Yahoo's stale copies looked at this step's hour
(`step_nav_crosscheck`).

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
import math
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
from quantt.broker.alpaca import (AlpacaError, AssetNotFound, MissingAuctionPrint,  # noqa: E402
                                  UnmappedExchange)
# A definite answer that there is no print to be had for (name, D): recorded as
# a gap and not asked again. Anything else (5xx, network, an unexpected shape) is
# "not measured", retried next slot (review 2026-09-29: a transient error on a
# non-deployed name used to become a permanent hole in the official-close file).
FINAL_PRINT_GAPS = (MissingAuctionPrint, AssetNotFound, UnmappedExchange)
from quantt.session.records import (StateDirError, state_dir_from_env,  # noqa: E402
                                    write_json_atomic)
# The CEFConnect reader and its error moved to quantt/session/nav_gate.py on
# 2026-10-13, so the session's stale-NAV gate and this cross-check read
# CEFConnect through one function; re-exported here under their old names.
# nav_gate imports only the standard library at module level (pytest.ini).
from quantt.session.nav_gate import CefConnectError, cefconnect_nav  # noqa: E402,F401
from quantt.session.nav_gate import move_aside  # noqa: E402
from quantt.session.nav_gate import repeats as nav_repeats  # noqa: E402

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
         "account_snapshot", "distributions", "borrow_snapshot",
         "cefconnect_arrival", "eod_equity")
# eod_equity runs LAST (review 2026-10-19). It is new code that runs every slot
# until D's point lands. An unexpected error in it aborts the run, so it must
# come after borrow_snapshot (D's close only, never recoverable later) and after
# every step the book decides on.
# A WATCH step keeps the collector polling every slot until it is done, but never
# makes the day INCOMPLETE, never fails the exit code and never blocks another
# step: it measures something that arrives on its own clock (2026-10-13).
WATCH_STEPS = ("cefconnect_arrival",)
ARRIVAL_FILE = "cefconnect_arrival.csv"
ARRIVAL_COLUMNS = ("date", "ticker", "last_absent_utc", "first_seen_utc", "polls", "nav")
DEPENDS_ON = {"nav_crosscheck": ("prices_nav",),
              "close_crosscheck": ("prices_nav", "official_closes")}

OFFICIAL_CLOSE_FILE = "alpaca_official_close.parquet"
OFFICIAL_CLOSE_COLUMNS = ("date", "ticker", "price", "exchange", "condition", "t",
                          "fetched_at_utc")
EQUITY_COLUMNS = ("date", "equity", "last_equity", "cash", "long_market_value",
                  "short_market_value", "n_positions", "read_at_utc")
# The official daily P&L series (team lead, 2026-10-19; step `eod_equity`). A
# CONTRACT: another branch and a HALVE/KILL monitor read it by these names, and
# the first three must stay first and keep these names. Extra columns may only
# be added after them.
EOD_FILE = "eod_equity.csv"
EOD_COLUMNS = ("date", "equity", "change_usd", "read_at_utc")
# Any account key matching this is dropped before account.json is written. The
# parsed account carries none today; this is for the day Alpaca adds one.
CREDENTIAL_KEY = re.compile(r"key|secret|token|password|auth", re.I)

# `eod_from`: the date the book's Alpaca paper account opened (IBKR retired and
# the per-book Alpaca accounts set up on 2026-09-28, docs/SYSTEM.md §5). The
# end-of-day history is read from here on every read. Days before funding come
# back as equity 0 and the client drops them by name (alpaca.py
# `eod_equity_history`), so the first row written is the first funded session
# whichever day that was.
BOOKS = {"cef": {"book_path": "ops/books/cef_discount_book.json",
                 "eod_from": dt.date(2026, 9, 28)}}

EXIT_OK, EXIT_INCOMPLETE, EXIT_UNEXPECTED = 0, 5, 20


class CalendarDisagreement(RuntimeError):
    """Alpaca's calendar and nyse_calendar disagree about whether a day trades."""


class StepFailed(RuntimeError):
    """A step did not complete; it is recorded and retried on the next slot."""

    def __init__(self, msg: str, detail: dict | None = None):
        super().__init__(msg)
        self.detail = detail or {}


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
    Two rows for one (date, ticker) is a corrupted panel and raises.

    A row that is present but EMPTY (NaN, or any value that is not finite)
    comes back as that float, not None: "no row" and "a row with nothing in it"
    are different gaps, and every caller tests `math.isfinite` before it
    compares (`_compare`, 2026-10-28)."""
    v = rows.loc[rows["ticker"] == ticker, col]
    if len(v) > 1:
        raise StepFailed(f"{what} has {len(v)} rows for {ticker}; expected one")
    return None if v.empty else float(v.iloc[0])


def _compare(fund, source_a, value_a, source_b, value_b) -> dict | None:
    """A flag naming both sources and both values when they differ by more
    than TOLERANCE_USD, else None. Both values must be finite.

    WHY THE RAISE (2026-10-28). yfinance can write a price row whose every
    price is NaN (scripts/cef/fetch_daily.py, EMPTY ROWS: 15 good 2026-09-15
    bars on the laptop panel had become such rows by 2026-10-15). A NaN
    compares False against everything, so `abs(nan - x) > tol` was False and a
    deployed name whose panel close for D was empty came back as "agrees":
    neither a flag nor a gap, the silent pass this module exists to prevent.
    The callers now record a value that is not finite as a GAP naming the fund
    and the date before they get here; this raise is for the caller that
    forgets, so the mistake fails the run instead of passing quietly."""
    if not (math.isfinite(value_a) and math.isfinite(value_b)):
        raise ValueError(f"{fund}: cannot compare {source_a} {value_a!r} with {source_b} "
                         f"{value_b!r}: not finite, and must be recorded as a gap")
    if abs(value_a - value_b) > TOLERANCE_USD:
        return {"fund": fund, "source_a": source_a, "value_a": value_a,
                "source_b": source_b, "value_b": value_b,
                "diff": round(value_a - value_b, 6)}
    return None


# ------------------------------------------------------------------ the steps
# Each returns a detail dict with "flags" and "gaps" lists, or raises StepFailed.

def step_prices_nav(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """fetch_daily for D WITHOUT the CEFConnect fallback. Its exit code is the
    verdict: 0 = every deployed name has a close and a yfinance NAV dated D. 4
    is the expected answer before the evening's NAVs land; 3 is the panel lock.

    WHY NO FALLBACK (review 2026-09-29). With it, a name CEFConnect had before
    yfinance was written FROM CEFConnect, the step was done for good, and the
    cross-check then skipped that name as "same source" -- while the session's
    later refresh overwrote it with yfinance's value, the one actually traded,
    which nothing then compared. Without it, this step completes only on
    yfinance NAVs, and nav_crosscheck compares exactly those against CEFConnect,
    an independent source. The SESSION still uses the fallback (RUNNER.md step 1);
    a name it filled from CEFConnect is still reported as a same-source gap."""
    cmd = [sys.executable, "scripts/cef/fetch_daily.py", "--require-asof", day.isoformat(),
           "--book", ctx.book_path]
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
    """Panel NAV (yfinance) vs CEFConnect's NAV for D, per deployed name. Report only.

    A REPEAT WITH NO CEFCONNECT ROW IS A FLAG, NOT A GAP (team lead, 2026-10-13).
    This step runs about 21:40 ET, when CEFConnect usually has no row for D yet:
    on 6 of 7 laptop data days it recorded 13 gaps and compared nothing, while
    Yahoo was serving rows dated D that carried D-1's NAV
    (results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5). A gap reads as "nothing to
    see". So a name whose panel NAV for D equals its previous NAV row to the cent
    (`quantt.session.nav_gate.repeats`, the session gate's own test) while
    CEFConnect has no NAV dated D is flagged `nav_repeat_unverified`: value_a is
    NAV(D), value_b the previous row's NAV, both from the panel, and `reason`
    says CEFConnect could not confirm it. Report only, like every flag here: it
    never blocks and never fails the step. A name that does not repeat is still
    a gap.

    AN EMPTY ROW IS A GAP (2026-10-28). A panel row dated D whose NAV is NaN
    used to reach `_compare`, where NaN compares False against everything: the
    name was neither flagged nor a gap. It is now a gap naming the fund, the
    date and the value. A CEFConnect NAV that is not finite is unreadable, as
    the session's gate treats it (`nav_gate.read_cc`): a fetch error, retried
    next slot, never compared."""
    nav_panel = _read_parquet(ctx.cef_dir / "cef_nav.parquet", "NAV panel")
    rows = _on_day(nav_panel, day)
    same_source = _fallback_names(ctx.cef_dir, day)
    flags, gaps, errors = [], [], []
    for t in ctx.deployed:
        panel = _one_value(rows, t, "nav", "cef_nav.parquet")
        if panel is None:
            gaps.append({"fund": t, "reason": f"cef_nav.parquet has no NAV dated {day}"})
            continue
        if not math.isfinite(panel):
            gaps.append({"fund": t, "reason": f"cef_nav.parquet's row dated {day} is empty "
                                              f"(nav {panel}): no NAV to compare"})
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
            rep = nav_repeats(nav_panel, day, [t])
            if rep:
                r = rep[0]
                flags.append({"fund": t, "check": "nav_repeat_unverified",
                              "source_a": "cef_nav.parquet (yfinance)", "value_a": r.nav_d,
                              "source_b": f"cef_nav.parquet previous row {r.prev_date}",
                              "value_b": r.nav_prev, "diff": round(r.nav_d - r.nav_prev, 6),
                              "reason": f"NAV dated {day} equals the previous NAV "
                                        f"({r.prev_date}) and CEFConnect has no NAV dated "
                                        f"{day}: possibly a stale copy, unverified"})
            else:
                gaps.append({"fund": t, "reason": f"CEFConnect has no NAV dated {day}"})
            continue
        if not math.isfinite(float(cc)):
            errors.append(f"{t}: CEFConnect's NAV dated {day} is {cc!r}, not a finite number")
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
    rows, gaps, transient = [], [], []
    fetched_at = _utc_now()
    for sym in [s for s in symbols if s not in have]:
        try:
            code = ctx.client.primary_sip_code(sym, exchanges)
            got = ctx.client.closing_auction_prints([sym], day, exchange_codes={sym: code},
                                                    condition="M")
        except FINAL_PRINT_GAPS as e:
            gaps.append({"fund": sym, "reason": f"{type(e).__name__}: {e}"})
            continue
        except AlpacaError as e:
            transient.append(f"{sym}: {type(e).__name__}: {e}")
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
    detail = {"flags": [], "gaps": gaps, "stored_now": len(rows), "stored_before": len(have),
              "transient_errors": transient}
    if missing:
        raise StepFailed(f"no official close for deployed name(s) {missing}", detail)
    if transient:
        raise StepFailed(f"{len(transient)} name(s) not measured (transient errors); "
                         f"retrying next slot", detail)
    return detail


def step_close_crosscheck(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Alpaca official close vs panel close (yfinance) for D, per deployed name. Report only.

    AN EMPTY ROW IS A GAP (2026-10-28). fetch_daily wrote price rows with every
    price NaN until that day (its docstring, EMPTY ROWS), and the panel still
    holds them: a deployed name whose close for D was NaN reached `_compare`,
    compared False, and was neither flagged nor a gap. Either value not finite
    is now a gap naming the fund, the date and the value; a missing row reads
    exactly as it always did."""
    px = _on_day(_read_parquet(ctx.cef_dir / "cef_prices.parquet", "price panel"), day)
    oc = _on_day(_read_parquet(ctx.cef_dir / OFFICIAL_CLOSE_FILE, "official-close file"), day)
    flags, gaps = [], []
    for t in ctx.deployed:
        a = _one_value(oc, t, "price", OFFICIAL_CLOSE_FILE)
        b = _one_value(px, t, "close", "cef_prices.parquet")
        sides = (("alpaca official close", a, f"{OFFICIAL_CLOSE_FILE}'s price"),
                 ("panel close", b, "cef_prices.parquet's close"))
        which = [n for n, v, _ in sides if v is None]
        empty = [f"{col} dated {day} is empty ({v})" for _, v, col in sides
                 if v is not None and not math.isfinite(v)]
        if which or empty:
            why = ([f"no {' and no '.join(which)} dated {day}"] if which else []) + empty
            gaps.append({"fund": t, "reason": "; ".join(why)})
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


def _read_eod(path: Path) -> dict:
    """{date: row} from eod_equity.csv; a header that is not EOD_COLUMNS, or a
    date listed twice, fails the step rather than being rewritten over."""
    if not path.exists():
        return {}
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != EOD_COLUMNS:
            raise StepFailed(f"{path} has columns {rd.fieldnames}, expected {list(EOD_COLUMNS)}",
                             {"flags": [], "gaps": []})
        rows: dict = {}
        for r in rd:
            if r["date"] in rows:
                raise StepFailed(f"{path} lists {r['date']} twice", {"flags": [], "gaps": []})
            # A cell that is not a finite number (a hand edit, a torn write)
            # would otherwise reach float() in the step as a bare ValueError and
            # abort the whole collector run (review 2026-10-19).
            try:
                finite = math.isfinite(float(r["equity"]))
            except (TypeError, ValueError):
                finite = False
            if not finite:
                raise StepFailed(f"{path}: equity {r['equity']!r} on {r['date']} is not a "
                                 f"finite number; the file is left as it is",
                                 {"flags": [], "gaps": []})
            rows[r["date"]] = r
    return rows


def _write_eod(path: Path, rows: list) -> None:
    """The whole file, sorted by date; temp file, fsync, rename (as `_write_equity_row`)."""
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=EOD_COLUMNS)
        w.writeheader()
        w.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _with_changes(rows: dict) -> tuple[list, list]:
    """(rows sorted by date with change_usd filled in, gaps).

    change_usd is this row's equity minus the PREVIOUS TRADING SESSION's
    (`ops/schedule/nyse_calendar.previous_trading_day`), and only when that
    session is the row just before it. The first row is the first funded
    session, and has no previous session in this file, so its cell is empty.
    A row whose previous session is missing from Alpaca's history also gets an
    empty cell, and a gap naming the missing session. Differencing across the
    hole would give a two-day change labelled as one day.
    Alpaca returns cash to two digits [V: reference, §12an], so the
    difference is rounded to the cent only to drop float noise.
    """
    out, gaps = [], []
    dates = sorted(rows)
    for i, d in enumerate(dates):
        r = dict(rows[d])
        r["change_usd"] = ""
        if i:
            want = previous_trading_day(dt.date.fromisoformat(d)).isoformat()
            if dates[i - 1] == want:
                r["change_usd"] = f"{float(r['equity']) - float(rows[want]['equity']):.2f}"
            else:
                gaps.append({"date": d, "reason": f"the previous session {want} is not in "
                                                  f"Alpaca's EOD history; change_usd left empty"})
        out.append({k: r[k] for k in EOD_COLUMNS})
    return out, gaps


def step_eod_equity(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Alpaca's end-of-day equity for every funded session, upserted into <state>/eod_equity.csv.

    WHY (team lead, 2026-10-19). Alpaca's end-of-day portfolio history is the
    paper book's official daily P&L of record. equity.csv (step
    `account_snapshot`) is a snapshot read after the close and stays as one.
    The 17:30 ET equity - last_equity disagreed with this history on all
    four days compared on 2026-10-19 (`quantt/session/score.py`).

    THE FILE IS A CONTRACT (EOD_COLUMNS). Another branch and a HALVE/KILL
    monitor read it by column name:
      date        the session's New York date, ISO
      equity      Alpaca's EOD equity, USD, as parsed (no rounding)
      change_usd  equity minus the previous session's equity in this file.
                  Empty for the first funded session, and for a session whose
                  previous one is missing (`_with_changes`). Never filled from an
                  invented baseline.
      read_at_utc when this value was first read (set again when it is revised)
    Every write rewrites the whole file from every funded session since
    BOOKS[book]["eod_from"]. So the first run after install backfills from
    2026-09-28 on its own, and every later read re-checks every earlier day.
    The write is temp + fsync + rename, like equity.csv.

    A REVISION IS LOGGED, NEVER SILENT. If a recorded date's equity differs
    from Alpaca's now, the new value is written. A line naming the date, the
    old value and the new one goes to data.log, and a flag
    (`check: eod_revised`) goes to the day's report. A recorded date missing
    from a later read keeps its row and is flagged (`eod_absent_from_read`):
    a missing point does not delete the official history.

    WHAT IS WRITTEN: ONLY FINISHED DAYS, UP TO D. The read asks for points up
    to the data day D; the client leaves out any later, unfinished session.
    A point whose own stamp is after this run's Alpaca clock is not written:
    its day's window has not closed. Alpaca stamped the 2026-10-16 close
    2026-10-17T00:00Z, 20:00 ET, and documents neither when a point first
    appears nor whether it can change (§12an). Such a point is written on the
    first run after its stamp has passed.

    WHEN IT READS: EVERY SLOT UNTIL D's POINT IS WRITTEN, THEN ONCE A DATA DAY.
    The step is ok only once D's finished point is in the file. Until then it
    fails, names why ("no point for D yet", or "stamped after this read"),
    and is retried every 30 minutes, as `prices_nav` is until the evening NAVs
    land. So D's row appears within one slot of Alpaca's stamp. After that the
    collector idles, which costs a clock and a calendar read and nothing else
    (module docstring). The next re-read is the next data day's first run.
    Because every read covers the whole history, a revision to any day is
    caught and logged within one session. Reading on every slot forever would
    end the idle state for a series that changes once a day.

    A regular step, not a WATCH step: a shape the client refuses, or a file
    in the wrong format, makes the day INCOMPLETE in data.log. The monitor
    reading this file must not lose it quietly.
    """
    points = ctx.client.eod_equity_history(BOOKS[ctx.book]["eod_from"], day)
    now = clk["timestamp"]
    path = ctx.state_dir / EOD_FILE
    old = _read_eod(path)
    read_at = _utc_now()
    rows = {d: dict(r) for d, r in old.items()}
    flags, revised, written = [], [], 0
    finished = [p for p in points if p.stamp <= now]
    for p in finished:
        d = p.date.isoformat()
        new = repr(float(p.equity))
        if d not in rows:
            rows[d] = {"date": d, "equity": new, "read_at_utc": read_at}
            written += 1
        elif float(rows[d]["equity"]) != float(p.equity):
            revised.append((d, rows[d]["equity"], new))
            flags.append({"check": "eod_revised", "date": d, "old": rows[d]["equity"],
                          "new": new, "read_at_utc": read_at})
            rows[d] = {"date": d, "equity": new, "read_at_utc": read_at}
    read_dates = {p.date.isoformat() for p in points}
    for d in sorted(set(old) - read_dates):
        flags.append({"check": "eod_absent_from_read", "date": d, "kept": old[d]["equity"],
                      "reason": f"recorded earlier, not in Alpaca's history read {read_at}"})
    out, gaps = _with_changes(rows)
    if out:
        _write_eod(path, out)
    for d, o, n in revised:
        _append_log(ctx.state_dir, f"{day} DATA EOD_REVISED {d} equity {o} -> {n} "
                                   f"(Alpaca EOD history, read {read_at})")
    detail = {"flags": flags, "gaps": gaps, "written_now": written, "revised": len(revised),
              "rows": len(out), "first": out[0]["date"] if out else None,
              "last": out[-1]["date"] if out else None}
    mine = [p for p in points if p.date == day]
    if not mine:
        raise StepFailed(f"Alpaca's EOD history has no point for {day} yet; read again next slot",
                         detail)
    if mine[0].stamp > now:
        raise StepFailed(f"Alpaca's point for {day} is stamped "
                         f"{mine[0].stamp.astimezone(ET).isoformat()}, after this run's clock "
                         f"{now.astimezone(ET).isoformat()}: its day has not closed; written "
                         f"once the stamp has passed", detail)
    return detail


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


ASSETS_FILE = "assets.parquet"
# The flags compared day to day for the deployed names. A change is a report-only
# flag: the session re-reads `shortable` at send (gate 7), so nothing here gates.
BORROW_FIELDS = ("tradable", "shortable", "easy_to_borrow")


def _assets_frame(rows: list):
    import pandas as pd
    return pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


def step_borrow_snapshot(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """Alpaca's active US-equity asset list as of D's close, one parquet per day.

    WHY. Borrow flags change daily, and Alpaca keeps no history of them. AWF and
    MHD were shortable on 2026-09-28 and not on 2026-10-08. Short sleeves (the
    merger pair's acquirer leg, ETF shorts) need to know how often a name could
    actually be borrowed (results/cef/RESEARCH_PLAN_2026-10-09.md 0.3, gate G1a).
    The rows are written to <state>/data/<D>/assets.parquet with the read time.

    WHEN. Read on D's own ET evening, and nowhere else (review 2026-10-09). The
    clock read at the start of the run can be ~35 minutes stale by now, since the
    subprocess steps run first, so it is re-read here just before the GET. The
    read must be on D's ET calendar date, with the market shut and the next open
    being the session after D. A retry that only succeeds the next morning would
    carry Alpaca's overnight refresh, whose time is [U], under D's label. So that
    day gets no snapshot (the step fails, visibly) rather than a mislabelled one.

    REPORT ONLY. A deployed name whose tradable / shortable / easy_to_borrow
    changed since the previous trading day's snapshot is a flag. A deployed name
    missing from Alpaca's list is a gap. Neither blocks trading: gate 7 re-reads
    `shortable` at send.
    """
    import pandas as pd
    nxt = next_trading_day(day)
    fresh = ctx.client.clock()                     # not the run's clock: see WHEN
    now_et = fresh["timestamp"].astimezone(ET)
    next_open = fresh["next_open"].astimezone(ET)
    if fresh["is_open"] or next_open.date() != nxt or now_et.date() != day:
        raise StepFailed(
            f"the asset list would not describe {day}'s evening (now {now_et.isoformat()}, "
            f"market open={fresh['is_open']}, next open {next_open.isoformat()}, first trading "
            f"day after {day} is {nxt}); not recorded rather than recorded under the wrong day",
            {"flags": [], "gaps": []})
    read_at = _utc_now()
    rows = ctx.client.assets(status="active", asset_class="us_equity")
    if not rows:
        raise StepFailed("Alpaca returned an empty active asset list", {"flags": [], "gaps": []})
    df = _assets_frame(rows)
    df["read_at_utc"] = read_at
    day_dir = ctx.state_dir / "data" / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    tmp = day_dir / f".{ASSETS_FILE}.tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, day_dir / ASSETS_FILE)

    flags, gaps = [], []
    today = df.set_index("symbol")
    prev = previous_trading_day(day)
    prev_path = ctx.state_dir / "data" / prev.isoformat() / ASSETS_FILE
    before = pd.read_parquet(prev_path).set_index("symbol") if prev_path.exists() else None
    for t in ctx.deployed:
        if t not in today.index:
            gaps.append({"fund": t, "reason": f"not in Alpaca's active asset list read {read_at}"})
            continue
        if before is None or t not in before.index:
            continue
        for f in BORROW_FIELDS:
            a, b = before.at[t, f], today.at[t, f]
            if pd.isna(a) and pd.isna(b):
                continue
            if pd.isna(a) or pd.isna(b) or bool(a) != bool(b):
                flags.append({"fund": t, "field": f, "previous": None if pd.isna(a) else bool(a),
                              "now": None if pd.isna(b) else bool(b),
                              "previous_date": prev.isoformat()})
    dep = today.reindex([t for t in ctx.deployed if t in today.index])
    return {"flags": flags, "gaps": gaps, "n_assets": int(len(df)),
            "n_shortable": int(df["shortable"].sum()),
            "deployed_not_shortable": sorted(dep.index[~dep["shortable"].astype(bool)]),
            "compared_with": prev.isoformat() if before is not None else "no previous snapshot",
            "read_at_utc": read_at}


def _append_arrivals(path: Path, rows: list, when: dt.datetime) -> str | None:
    """Append first sightings to <state>/cefconnect_arrival.csv, one row per
    (date, ticker) ever: a row already there is not written again (a crash
    between this append and status.json would otherwise log a name twice).

    A FILE WHOSE HEADER IS NOT ARRIVAL_COLUMNS (quant-reviewer, 2026-10-14) --
    empty after a kill before the first flush, or from an older column list --
    is moved aside whole (`nav_gate.move_aside`: `<name>.<UTC stamp>.unreadable`)
    and a new file is started at once, so this slot's arrivals are still
    logged. Until 2026-10-14 such a file failed the step on every slot with an
    empty detail, silently ending the measurement that turning the stale-NAV
    gate `on` depends on. Returns a note naming both files, or None."""
    have, note = set(), None
    if path.exists():
        with open(path, newline="") as fh:
            rd = csv.DictReader(fh)
            head = rd.fieldnames
            good = tuple(head or ()) == ARRIVAL_COLUMNS
            if good:
                have = {(r["date"], r["ticker"]) for r in rd}
        if not good:
            aside = move_aside(path, when)
            note = (f"{path} had columns {head}, not {list(ARRIVAL_COLUMNS)}: moved aside to "
                    f"{aside}; a new file was started")
    rows = [r for r in rows if (r["date"], r["ticker"]) not in have]
    if not rows and note is None:
        return None
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ARRIVAL_COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())
    return note


def step_cefconnect_arrival(ctx: Ctx, day: dt.date, clk: dict, status: dict) -> dict:
    """When each deployed name's CEFConnect row for D first appears. Report only.

    WHY (team lead, 2026-10-13). The session's stale-NAV gate defers an
    unverified NAV to the morning backstop and holds it from its final check
    (`quantt/session/nav_gate.py`), so when CEFConnect publishes D decides how
    often a name is held. The evidence so far is three readings: no row by 00:10
    ET on D+1 (2026-10-05), a row by 11:41 ET (2026-10-01), and Friday's row
    still missing at 09:40 ET on Saturday (2026-10-02). The reviewer's point:
    "present by midday" rests on one of them.

    HOW. Every slot, each name not yet seen is read once (`ctx.cefconnect_nav`,
    the gate's own reader). A name's arrival lies in (last_absent_utc,
    first_seen_utc]; the slot cadence (30 minutes) is the resolution. A first
    sighting is appended to `<state>/cefconnect_arrival.csv`; the running state
    is this step's detail in status.json. A WATCH step: it keeps polling until
    every name has been seen, or D moves on (then status.json keeps the last
    absent reading), and never makes the day INCOMPLETE. A read error is
    recorded and the name is read again next slot."""
    prev = (status["steps"].get("cefconnect_arrival") or {}).get("detail") or {}
    seen = dict(prev.get("first_seen") or {})
    absent = dict(prev.get("last_absent_utc") or {})
    polls = dict(prev.get("polls") or {})
    errors, new = [], []
    for t in ctx.deployed:
        if t in seen:
            continue
        now = _utc_now()
        polls[t] = polls.get(t, 0) + 1
        try:
            v = ctx.cefconnect_nav(t, day)
        except CefConnectError as e:
            errors.append(str(e))
            continue
        if v is None:
            absent[t] = now
            continue
        seen[t] = {"utc": now, "nav": float(v)}
        new.append({"date": day.isoformat(), "ticker": t, "last_absent_utc": absent.get(t, ""),
                    "first_seen_utc": now, "polls": polls[t], "nav": float(v)})
    rotated = _append_arrivals(ctx.state_dir / ARRIVAL_FILE, new,
                               dt.datetime.now(dt.timezone.utc))
    detail = {"flags": [], "gaps": [], "first_seen": seen, "last_absent_utc": absent,
              "polls": polls, "fetch_errors": errors,
              "file_rotations": list(prev.get("file_rotations") or []) + ([rotated] if rotated
                                                                           else [])}
    waiting = [t for t in ctx.deployed if t not in seen]
    if waiting:
        raise StepFailed(f"watching: CEFConnect has no NAV dated {day} yet for {waiting}",
                         detail)
    return detail


STEP_FUNCS = {"prices_nav": step_prices_nav, "nav_crosscheck": step_nav_crosscheck,
              "official_closes": step_official_closes, "close_crosscheck": step_close_crosscheck,
              "account_snapshot": step_account_snapshot, "eod_equity": step_eod_equity,
              "distributions": step_distributions,
              "borrow_snapshot": step_borrow_snapshot,
              "cefconnect_arrival": step_cefconnect_arrival}


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
    failed = [s for s in STEPS if not steps.get(s, {}).get("ok") and s not in WATCH_STEPS]
    watching = [s for s in WATCH_STEPS if not steps.get(s, {}).get("ok")]
    flags, gaps = [], []
    for s in STEPS:
        detail = steps.get(s, {}).get("detail", {})
        flags += [{"step": s, **f} for f in detail.get("flags", [])]
        gaps += [{"step": s, **g} for g in detail.get("gaps", [])]
    return {"date": day.isoformat(), "book": book, "complete": not failed,
            "failed_steps": failed, "watching": watching, "flags": flags, "gaps": gaps,
            "steps": steps, "written_at_utc": _utc_now()}


def log_line(report: dict) -> str:
    what = ("COMPLETE" if report["complete"]
            else "INCOMPLETE " + ",".join(report["failed_steps"]))
    line = (f"{report['date']} DATA {what} flags={len(report['flags'])} "
            f"gaps={len(report['gaps'])}")
    if report.get("watching"):
        line += " watching=" + ",".join(report["watching"])
    return line


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
