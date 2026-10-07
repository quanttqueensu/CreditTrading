"""One trading session for one book: refresh, read, decide, gate, record, transmit, confirm.

This is the ONLY caller of `AlpacaClient.submit_order` in the repository
(docs/RUNNER.md module boundaries). The order of the steps is the contract in
RUNNER.md "The session, in order"; the reasons for the order are the incidents:

  1. refresh   `scripts/cef/fetch_daily.py --require-asof <prev trading day>`
               in a child process. The as-of date is the previous NYSE trading
               day by `ops/schedule/nyse_calendar.py` AND by Alpaca's
               `/v2/calendar`; if the two disagree the session raises rather
               than pick one (CLAUDE.md: two sources that disagree are reported,
               never averaged or silently chosen). A non-zero exit is a gate-5
               refusal: stale data never trades. The child is killed at
               the session's cls cutoff or after REFRESH_TIMEOUT_CAP_S,
               whichever is sooner, and a timeout is also a gate-5 refusal. Gate 5
               checks each name's CLOSE and NAV are dated as-of, so
               --skip-refresh cannot trade a name the sleeve silently dropped.
  2. read      Alpaca clock, calendar, account, positions, orders, assets.
  3. decide    the sleeve on the as-of date with the broker's holdings and
               `extras={"sleeve_nav": equity, "opening_session": bool}`, then
               `decide.decide` -> whole-share orders and `plan_sha`.
  4. gate      all nine (`gate.evaluate`), on a clock read AFTER the slow
               steps, never the one from the start. Any refusal: nothing is sent.
  5. record    `<state>/<date>/STARTED`, exclusively, BEFORE the first order
               (CLAUDE.md order-path rule 2).
  6. transmit  in `decide.transmit_sequence` order (running net kept near
               zero); the Alpaca clock re-read before every POST and the batch
               stopped at the cutoff. One POST per order, each attempt and response appended to
               orders.jsonl as it happens. ANY failure stops the batch: an
               `AmbiguousSubmit` is resolved by looking the id up, never by
               resending (a resend of an accepted order doubles it in the same
               auction), and a rejection or a bad echo stops the rest too,
               because the list that was approved is no longer the list that
               is going.
  7. confirm   every sent id is re-read from Alpaca by client_order_id; one
               missing or different is FAIL.

PAPER EXECUTION (team lead 2026-09-29; recorded exception to CLAUDE.md rule 3,
paper account only). When the book's json has `execution.mode = late_market`
the session runs in two phases:
  DECIDE  (evening 22:00-01:00 ET, or the morning backstop 06:00-15:15 ET):
          steps 1-4 as above, with every gate except dry-run, arming and clock;
          the plan is saved with `status: decided` and its plan_sha. Nothing is
          sent. Exit 6 PLANNED.
  SEND    (inside `late_window_et`, e.g. 15:52-15:58 ET): the SAVED plan is
          loaded and sent as market `day` orders -- never re-decided, because
          intraday equity moves the sizing, and what the team lead approved must
          be what goes. Positions must still equal the plan's "current" for
          every name; dry-run, arming (--approve, <D>/APPROVED, or AUTO_ARMED),
          halt, late clock, no-set, shortability, exposure and sanity are
          re-evaluated on fresh broker reads.
Why: paper runs no closing auction and under-fills `cls` (11 of 13 expired on
2026-09-29). Absent the key, the book runs as `cls` exactly as before.

OPENING SESSION. True only when Alpaca shows no positions AND no order in the
account's history has ever filled. The sleeve is told explicitly (it never
infers it from a flat book: a failed day or a manual flatten also looks flat),
and it trades to full target instead of the band edge (team lead 2026-09-28).

EXIT CODES (distinct, for launchd logs and the operator):
    0  SENT             orders transmitted and every one confirmed at Alpaca
    3  NOTHING_TO_SEND  every gate passed and the order list is empty
    4  PREVIEW          --preview: the list was printed; never sends
    5  IDLE             --scheduled: not a slot, or this session is already done
    6  PLANNED          late-market execution: the plan is decided and saved; it
                        is sent in the late window (see "PAPER EXECUTION")
   10  DRY              DRY_RUN not "0" (and nothing else refused except arming)
   11  REFUSED          a gate refused; nothing sent
   20  FAIL             an error, a rejected/ambiguous submit, or a confirm miss
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from quantt.session import decide as dec
from quantt.session import gate as gt
from quantt.session import records as rec

REPO = Path(__file__).resolve().parents[2]

EXIT_SENT, EXIT_NOTHING, EXIT_PREVIEW, EXIT_IDLE, EXIT_PLANNED = 0, 3, 4, 5, 6
EXIT_DRY, EXIT_REFUSED, EXIT_FAIL = 10, 11, 20
EXIT_NAMES = {EXIT_SENT: "SENT", EXIT_NOTHING: "NOTHING_TO_SEND", EXIT_PREVIEW: "PREVIEW",
              EXIT_IDLE: "IDLE", EXIT_PLANNED: "PLANNED", EXIT_DRY: "DRY",
              EXIT_REFUSED: "REFUSED", EXIT_FAIL: "FAIL"}

# A hung fetcher must not hold the job past the next scheduled attempt: launchd
# never starts a second instance of a running job, so a refresh that hangs
# until the cutoff (the old bound, ~17 h away for an evening run) would
# silently cancel every retry behind it. The fetch took 58 s on 2026-09-28 and
# may wait up to 10 min for the collector's panel lock; 25 min < the 30-min slot.
REFRESH_TIMEOUT_CAP_S = 25 * 60

# SCHEDULED WINDOWS (team lead 2026-09-29: "we dont have to do it at 830 ...
# should be flexible"). launchd fires `run --scheduled` every 30 minutes; the
# runner itself decides whether this is a slot to try in. EVENING: 22:00-01:00
# ET after the as-of close, because the as-of NAVs land ~21:30 ET (measured
# 2026-09-28: 0/13 at 21:21, 13/13 at 21:51). MORNING BACKSTOP: 06:00-15:15 ET
# on the session date, for a night whose data never came or whose machine was
# asleep or offline (2026-09-29 08:30: DNS failure on wake). The first attempt
# that gets through is the day; later ones find it done and idle.
EVENING_FROM, EVENING_UNTIL = dt.time(22, 0), dt.time(1, 0)
MORNING_FROM, MORNING_UNTIL = dt.time(6, 0), dt.time(15, 15)
# The local-clock pre-check only ever SKIPS a slot (so an offline machine does
# not log a failed Alpaca call every 30 minutes all day); it never permits one:
# the Alpaca clock decides. Five minutes of slack for local clock drift.
LOCAL_SLACK = dt.timedelta(minutes=5)
# The late-market send windows the pre-check must never skip: 16:00 and 13:00
# (early) closes, generously wider than any window_minutes_before_close we use.
LATE_LOCAL_RANGES = ((dt.time(15, 40), dt.time(16, 0)), (dt.time(12, 40), dt.time(13, 0)))


class SessionError(RuntimeError):
    """A fact the session needs is missing or contradictory. Names it."""


@dataclass(frozen=True)
class Book:
    name: str             # CLI name, and the ALPACA_<NAME>_* key prefix
    cid_prefix: str
    spec_path: Path
    book_path: Path


BOOKS = {
    "cef": Book("cef", "cef", REPO / "ops/specs/cef_discount.frozen.json",
                REPO / "ops/books/cef_discount_book.json"),
}


# ------------------------------------------------------------------ the spec

def load_spec(path: Path) -> dict:
    """The frozen spec as JSON. Read directly rather than through
    `scripts/cef/spec.py` because `scripts/` is never on the live path
    (CLAUDE.md layout); the registry validates it when the sleeve is built."""
    return json.loads(Path(path).read_text())


def spec_params(spec: dict) -> dict:
    """Every live parameter the session reads, each REQUIRED except
    `max_gross_stress`, whose absence is the spec's own "no cap" (the same
    semantics as `scripts/cef/spec.py::_optional`: absent/null = constraint off)."""
    def need(block, key):
        b = spec.get(block) if block else spec
        if not isinstance(b, dict) or key not in b:
            raise SessionError(f"frozen spec has no {block + '.' if block else ''}{key}")
        return b[key]
    mgs = (spec.get("frozen") or {}).get("max_gross_stress")
    return {"spec_id": need(None, "spec_id"),
            "universe": tuple(sorted(need("frozen", "universe"))),
            "capital_usd": float(need(None, "capital_usd")),
            "min_trade_usd": float(need("rebalance", "min_trade_usd")),
            "max_gross_usd": float(need("risk", "max_gross_exposure_usd")),
            "max_gross_stress": None if mgs in (None, "") else float(mgs)}


# ------------------------------------------------------------ dates and data

def session_for(now: dt.datetime, calendar_rows: list, cutoff_of=None) -> dt.date:
    """The auction an order sent NOW would be for: today, if today is a trading
    day and the clock is before today's cls cutoff; otherwise the next trading
    day after today. Both Alpaca's calendar and nyse_calendar must agree, or
    this raises rather than pick one.

    WHY. Until 2026-09-29 the session date was simply the clock's date, so a
    run could only trade the same day. The team lead moved the decision to the
    evening: at 22:00 ET on the 28th the auction is the 29th's, decided on the
    28th's close and NAV -- the same pair, and so the same plan, as a morning run
    on the 29th (shift(2) is unchanged). Between the cutoff and 19:15 ET this
    names tomorrow and gate 4 refuses (Alpaca rejects cls then [V]).
    """
    from ops.schedule.nyse_calendar import is_trading_day, next_trading_day
    now = now.astimezone(gt.ET)
    today = now.date()
    alpaca_days = sorted(r["date"] for r in calendar_rows)
    rows_today = [r for r in calendar_rows if r["date"] == today]
    if len(rows_today) > 1:
        raise SessionError(f"Alpaca calendar has {len(rows_today)} rows for {today}")
    if is_trading_day(today) != bool(rows_today):
        raise SessionError(f"calendars disagree on {today}: nyse_calendar trading="
                           f"{is_trading_day(today)}, Alpaca rows={len(rows_today)}; "
                           f"not choosing one")
    cutoff_of = cutoff_of or gt.cutoff_et      # late-market: the send window's end
    if rows_today and now < cutoff_of(today, rows_today[0]["close"]):
        return today
    ours = next_trading_day(today)
    after = [d for d in alpaca_days if d > today]
    if not after:
        raise SessionError(f"Alpaca calendar returned no trading day after {today}")
    if after[0] != ours:
        raise SessionError(f"next trading day disagrees: nyse_calendar {ours}, Alpaca "
                           f"calendar {after[0]}; not choosing one")
    return ours


def scheduled_slot(now: dt.datetime, session_date: dt.date, asof: dt.date) -> str | None:
    """'evening' or 'morning' if NOW (ET) is a scheduled slot for this
    session, else None. Evening = from 22:00 on the as-of date to 01:00 the
    next calendar day; morning = 06:00-15:15 on the session date."""
    now = now.astimezone(gt.ET)
    t, d = now.time(), now.date()
    if (d == asof and t >= EVENING_FROM) or \
            (d == asof + dt.timedelta(days=1) and t < EVENING_UNTIL):
        return "evening"
    if d == session_date and MORNING_FROM <= t < MORNING_UNTIL:
        return "morning"
    return None


def near_a_slot_locally(local_now: dt.datetime) -> bool:
    """Local-clock pre-check (see LOCAL_SLACK): could this be ANY slot on ANY
    day? False only when the ET time of day is well outside both windows."""
    t = local_now.astimezone(gt.ET)
    def within(a, b):          # [a - slack, b + slack) on the time of day, wrapping midnight
        lo = (dt.datetime.combine(t.date(), a, tzinfo=gt.ET) - LOCAL_SLACK).time()
        hi = (dt.datetime.combine(t.date(), b, tzinfo=gt.ET) + LOCAL_SLACK).time()
        x = t.time()
        return (lo <= x < hi) if lo < hi else (x >= lo or x < hi)
    return (within(EVENING_FROM, EVENING_UNTIL) or within(MORNING_FROM, MORNING_UNTIL)
            or any(within(a, b) for a, b in LATE_LOCAL_RANGES))


def done_reason(day: Path, env) -> str | None:
    """Why a scheduled run has nothing left to do for this session, or None.

    STARTED: a set went (or began to go) -- never again (CLAUDE.md rule 2).
    DONE: a scheduled run finished SENT or NOTHING_TO_SEND.
    DRY_DONE: a scheduled run finished DRY; honoured only while DRY_RUN is not
    "0", so arming (DRY_RUN=0 + AUTO_ARMED) makes the next slot trade rather
    than idle behind a dry run of the same day.
    """
    if (day / "STARTED").exists():
        return "a set was already started for this session (STARTED)"
    if (day / "DONE").exists():
        return f"done: {(day / 'DONE').read_text().strip()}"
    if (day / "DRY_DONE").exists() and env.get("DRY_RUN") != "0":
        return f"dry run done: {(day / 'DRY_DONE').read_text().strip()}"
    return None


def decided_reason(day: Path) -> str | None:
    """Late-market DECIDE slots idle once a plan is decided (it waits for the send)."""
    if (day / "DECIDED").exists():
        return f"plan decided, waiting for the send window: {(day / 'DECIDED').read_text().strip()}"
    return None


def asof_for(session_date: dt.date, calendar_rows: list) -> dt.date:
    """The previous trading day, from nyse_calendar AND Alpaca; raise if they differ."""
    from ops.schedule.nyse_calendar import previous_trading_day
    ours = previous_trading_day(session_date)
    before = sorted(r["date"] for r in calendar_rows if r["date"] < session_date)
    if not before:
        raise SessionError(f"Alpaca calendar returned no trading day before {session_date}")
    if before[-1] != ours:
        raise SessionError(f"previous trading day disagrees: nyse_calendar {ours}, Alpaca "
                           f"calendar {before[-1]}; not choosing one")
    return ours


def last_closes(px_path: Path, asof: dt.date, universe) -> dict:
    """{symbol: (close, date)} -- each name's own last close on or before `asof`.

    `px.ffill().iloc[-1]` per name (CLAUDE.md landmine 6, HYT lags a day), with
    the date of the print it came from, so gate 5 can refuse a close that is
    not the as-of date. NO LOOKAHEAD: rows after `asof` are dropped before
    anything is read, and the returned dates are asserted <= asof. A duplicate
    (date, ticker) row raises: a pivot would silently average it.
    """
    import pandas as pd
    P = pd.read_parquet(px_path, columns=["date", "ticker", "close"])
    P = P[P["ticker"].isin(list(universe))].copy()
    P["date"] = pd.to_datetime(P["date"]).dt.normalize()
    P = P[P["date"] <= pd.Timestamp(asof)]
    dup = P[P.duplicated(["date", "ticker"], keep=False)]
    if len(dup):
        raise SessionError(f"{px_path}: duplicate (date, ticker) rows, e.g. "
                           f"{dup.head(3).to_dict('records')}")
    wide = P.pivot(index="date", columns="ticker", values="close").sort_index()
    ff = wide.ffill()
    out = {}
    for s in universe:
        if s not in wide.columns or wide[s].last_valid_index() is None:
            out[s] = (None, None)
            continue
        d = wide[s].last_valid_index().date()
        assert d <= asof, f"lookahead: {s} close dated {d} > as-of {asof}"
        out[s] = (float(ff[s].iloc[-1]), d)
    return out


def last_navs(nav_path: Path, asof: dt.date, universe) -> dict:
    """{symbol: date or None} -- the date of each name's last finite, positive
    NAV on or before `asof`, for gate 5.

    WHY. The sleeve inner-joins price and NAV; a name whose as-of NAV is
    missing drops out of the signal and is emitted FLAT (gate.gate_data
    docstring has the measured case). `last_closes` alone cannot see that.
    Same discipline as `last_closes`: rows after `asof` dropped first (NO
    LOOKAHEAD, asserted), a duplicate (date, ticker) raises rather than being
    averaged by a pivot. A NaN or non-positive NAV is not a NAV.
    """
    import pandas as pd
    N = pd.read_parquet(nav_path, columns=["date", "ticker", "nav"])
    N = N[N["ticker"].isin(list(universe))].copy()
    N["date"] = pd.to_datetime(N["date"]).dt.normalize()
    N = N[N["date"] <= pd.Timestamp(asof)]
    dup = N[N.duplicated(["date", "ticker"], keep=False)]
    if len(dup):
        raise SessionError(f"{nav_path}: duplicate (date, ticker) rows, e.g. "
                           f"{dup.head(3).to_dict('records')}")
    N = N[N["nav"].notna() & (N["nav"] > 0)]
    last = N.groupby("ticker")["date"].max()
    out = {}
    for s in universe:
        d = last.get(s)
        out[s] = None if d is None else d.date()
        assert out[s] is None or out[s] <= asof, f"lookahead: {s} NAV dated {out[s]} > {asof}"
    return out


@dataclass(frozen=True)
class RefreshResult:
    exit: int | None      # the fetcher's exit code; None when it did not finish
    tail: str             # last lines of the fetcher's stdout+stderr, for the record
    incomplete: str | None = None   # why it did not finish (timeout / not run); refuses gate 5


def _text(v) -> str:
    if v is None:
        return ""
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else v


def refresh_subprocess(asof: dt.date, book: Book, timeout_s: float) -> RefreshResult:
    """RUNNER.md step 1, verbatim flags. A child process so a fetcher crash
    cannot take the session with it, and its exit code is the whole verdict.

    TIMEOUT (review 2026-09-28). A fetch that hangs (cefconnect has no
    timeout of its own here) once meant the session could reach the gate after
    19:00 ET, when Alpaca queues cls orders into the NEXT day's auction [V].
    `run_session` passes the seconds left until the session's cls cutoff by
    Alpaca's clock (a refresh that ends after it cannot lead to an order for
    that auction), capped at REFRESH_TIMEOUT_CAP_S (2026-09-29) so a hung fetch
    cannot swallow the next scheduled slot. A timeout is a
    gate-5 refusal, recorded with whatever the fetcher printed.
    """
    cmd = [sys.executable, str(REPO / "scripts/cef/fetch_daily.py"),
           "--require-asof", asof.isoformat(), "--nav-fallback", "cefconnect",
           "--book", str(book.book_path.relative_to(REPO))]
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        tail = "\n".join((_text(e.stdout) + _text(e.stderr)).splitlines()[-40:])
        return RefreshResult(exit=None, tail=tail,
                             incomplete=f"timed out after {timeout_s:.0f}s (the sooner of the "
                                        f"cls cutoff and the {REFRESH_TIMEOUT_CAP_S}s cap)")
    tail = "\n".join((p.stdout + p.stderr).splitlines()[-40:])
    return RefreshResult(exit=p.returncode, tail=tail)


def sleeve_targets(spec: dict, capital: float, asof: dt.date, holdings: dict,
                   equity: float, opening: bool) -> list:
    """The strategy's targets, built exactly as RUNNER.md step 3 says: the
    registry's sleeve from the frozen spec at the spec's capital, asked on the
    as-of date with the broker's holdings and the two extras."""
    import pandas as pd
    from src.deploy.registry import build_sleeve
    from src.deploy.sleeve import MarketState
    from src.deploy.sleeves import cef_discount as cefmod
    sl = build_sleeve(spec, capital)
    ts = pd.Timestamp(asof)
    prices = pd.read_parquet(cefmod.PX_PATH)       # MarketState requires it; this sleeve reads its own panel
    prices = prices[pd.to_datetime(prices["date"]) <= ts]
    ms = MarketState(asof=ts, prices=prices, holdings=dict(holdings),
                     extras={"sleeve_nav": equity, "opening_session": opening})
    return sl.target_positions(ts, ms)


def is_opening_session(positions: dict, closed_orders: list) -> bool:
    """No position AND no order in the account's history ever filled."""
    if positions:
        return False
    for o in closed_orders:
        try:
            f = Decimal(str(o["filled_qty"]))
        except (KeyError, InvalidOperation):
            raise SessionError(f"closed order {o.get('client_order_id')!r} has unreadable "
                               f"filled_qty {o.get('filled_qty')!r}") from None
        if f > 0:
            return False
    return True


def halts_for(book: Book) -> list:
    """Every halt that blocks this book: global ops/HALT.md, and the scoped
    files under both names it has gone by (`cef`, and the book json's
    `book_id`). Checking both can only refuse more, never less."""
    from ops.halt import read_halt
    book_id = json.loads(book.book_path.read_text())["book_id"]
    out = []
    for scope in dict.fromkeys((book.name, book_id)):
        h = read_halt(scope)
        if h and h not in out:
            out.append(h)
    return out


# ------------------------------------------------------------------ plumbing

def execution_for(book: Book) -> dict:
    """The book json's `execution` block. ABSENT means `cls`, today's behaviour
    (CLAUDE.md: a new key defaults to current behaviour). `late_market` needs
    `window_minutes_before_close: [a, b]`; anything else raises."""
    ex = json.loads(book.book_path.read_text()).get("execution")
    if ex is None:
        return {"mode": "cls", "bp_shortfall": "refuse"}
    mode = ex.get("mode")
    # bp_shortfall (2026-10-07): ABSENT = "refuse", today's behaviour.
    short = ex.get("bp_shortfall", "refuse")
    if short not in ("refuse", "scale"):
        raise SessionError(f"{book.book_path}: execution.bp_shortfall {short!r} is not "
                           f"refuse or scale")
    if mode == "cls":
        return {"mode": "cls", "bp_shortfall": short}
    if mode == "late_market":
        w = ex.get("window_minutes_before_close")
        if not (isinstance(w, list) and len(w) == 2):
            raise SessionError(f"{book.book_path}: execution.window_minutes_before_close "
                               f"{w!r} must be [a, b]")
        return {"mode": "late_market", "window_minutes_before_close": (w[0], w[1]),
                "bp_shortfall": short}
    raise SessionError(f"{book.book_path}: execution.mode {mode!r} is not cls or late_market")


@dataclass
class Deps:
    """Everything the session touches outside itself; tests pass fakes."""
    client: object
    env: dict
    refresh: Callable[[dt.date, float], RefreshResult]   # (asof, timeout_s)
    closes: Callable[[dt.date, tuple], dict]
    navs: Callable[[dt.date, tuple], dict]              # (asof, universe) -> {sym: date|None}
    targets: Callable[..., list]           # (asof, holdings, equity, opening) -> [PositionTarget]
    halts: Callable[[], list]
    utcnow: Callable[[], dt.datetime] = field(default=lambda: dt.datetime.now(dt.timezone.utc))
    out: object = field(default_factory=lambda: sys.stdout)
    execution: dict = field(default_factory=lambda: {"mode": "cls"})   # execution_for(book)
    sleep: Callable[[float], None] = field(default=lambda s: __import__("time").sleep(s))


def default_deps(book: Book, spec: dict, env) -> Deps:
    from quantt.broker.alpaca import AlpacaClient
    if not env.get("QUANTT_ENV_FILE"):
        raise SessionError("QUANTT_ENV_FILE is not set: it must name the key file")
    from src.deploy.sleeves import cef_discount as cefmod
    p = spec_params(spec)
    return Deps(
        client=AlpacaClient.from_environment(book.name),
        env=dict(env),
        refresh=lambda asof, timeout_s: refresh_subprocess(asof, book, timeout_s),
        closes=lambda asof, uni: last_closes(cefmod.PX_PATH, asof, uni),
        navs=lambda asof, uni: last_navs(cefmod.NAV_PATH, asof, uni),
        targets=lambda asof, h, eq, op: sleeve_targets(spec, p["capital_usd"], asof, h, eq, op),
        halts=lambda: halts_for(book),
        execution=execution_for(book),
    )


def order_table(orders) -> str:
    rows = [f"{'symbol':<7}{'side':<6}{'qty':>8}{'est_px':>10}{'est_notional':>15}  "
            f"{'client_order_id':<24}reason"]
    for o in orders:
        rows.append(f"{o.symbol:<7}{o.side:<6}{o.qty:>8}{o.est_price:>10.2f}"
                    f"{o.est_notional:>15,.2f}  {o.client_order_id:<24}{o.reason}")
    if not orders:
        rows.append("(no orders)")
    return "\n".join(rows)


def _order_summary(o: dict) -> dict:
    keep = ("id", "client_order_id", "status", "symbol", "side", "qty", "type",
            "time_in_force", "submitted_at", "filled_qty", "filled_avg_price", "filled_at")
    return {k: o.get(k) for k in keep}


# --------------------------------------------------------------- the session

def run_session(book: Book, spec: dict, deps: Deps, *, preview: bool = False,
                approve: str | None = None, skip_refresh: bool = False,
                scheduled: bool = False) -> int:
    """The session. Returns an EXIT_* code; records everything it measured.

    `scheduled` (launchd, every 30 min): try only in a scheduled slot and only
    if this session is not done (see `scheduled_slot`, `done_reason`); else
    print one IDLE line and exit EXIT_IDLE without writing a run record.
    """
    out = deps.out
    stamp = deps.utcnow().strftime("%Y%m%dT%H%M%SZ")
    mode = "preview" if preview else "run"
    if scheduled and preview:
        raise SessionError("--scheduled and --preview are exclusive")
    if scheduled and not near_a_slot_locally(deps.utcnow()):
        print(f"IDLE outside the scheduled windows (local clock "
              f"{deps.utcnow().astimezone(gt.ET):%Y-%m-%d %H:%M} ET)", file=out)
        return EXIT_IDLE
    record: dict = {"book": book.name, "mode": mode, "started_utc": stamp,
                    "argv": {"preview": preview, "approve": approve,
                             "skip_refresh": skip_refresh, "scheduled": scheduled}}
    state = day = None
    try:
        state = rec.state_dir_from_env(deps.env)    # required; nothing runs without it
        p = spec_params(spec)
        record["spec_id"] = p["spec_id"]
        c = deps.client
        clock = c.clock()
        today_et = clock["timestamp"].astimezone(gt.ET).date()
        cal = c.calendar(today_et - dt.timedelta(days=14), today_et + dt.timedelta(days=14))
        late = deps.execution["mode"] == "late_market"
        mins = deps.execution.get("window_minutes_before_close")
        cutoff_of = (lambda d, close: gt.late_window_et(d, close, mins)[1]) if late \
            else gt.cutoff_et
        session_date = session_for(clock["timestamp"], cal, cutoff_of)
        asof = asof_for(session_date, cal)
        record["execution"] = deps.execution["mode"]
        win, in_send = None, False
        if late:
            rows = [r for r in cal if r["date"] == session_date]
            if len(rows) != 1:
                raise SessionError(f"Alpaca calendar has {len(rows)} rows for {session_date}")
            win = gt.late_window_et(session_date, rows[0]["close"], mins)
            in_send = win[0] <= clock["timestamp"] < win[1]
        if scheduled:
            dday = rec.day_dir(state, session_date)
            if in_send:
                slot, why = "send", done_reason(dday, deps.env)
            else:
                slot = scheduled_slot(clock["timestamp"], session_date, asof)
                why = (None if slot else "outside the scheduled windows") or \
                    done_reason(dday, deps.env) or (decided_reason(dday) if late else None)
            if why:
                print(f"IDLE {session_date}: {why} (Alpaca clock "
                      f"{clock['timestamp'].astimezone(gt.ET):%Y-%m-%d %H:%M} ET)", file=out)
                return EXIT_IDLE
            record["slot"] = slot
        day = rec.day_dir(state, session_date)
        if late and in_send:
            record["phase"] = "send"
            return _send_planned(book, spec, deps, record, state=state, day=day, stamp=stamp,
                                 mode=mode, session_date=session_date, clock=clock, cal=cal,
                                 win=win, approve=approve, preview=preview, scheduled=scheduled)
        if late:
            record["phase"] = "decide"
        record.update(session_date=session_date, asof=asof,
                      clock={k: clock[k] for k in ("timestamp", "is_open", "next_open",
                                                   "next_close")})

        cal_today = [r for r in cal if r["date"] == session_date]

        # 1. refresh -- bounded by the time left before today's cls cutoff
        if skip_refresh:
            refresh_exit = None
            record["refresh"] = {"skipped": True}
        elif len(cal_today) != 1:
            refresh_exit = (f"not run: Alpaca's calendar has {len(cal_today)} rows for "
                            f"{session_date}")
            record["refresh"] = {"not_run": refresh_exit}
        else:
            cut = cutoff_of(session_date, cal_today[0]["close"])
            left = (cut - clock["timestamp"]).total_seconds()
            if left <= 0:
                refresh_exit = f"not run: Alpaca clock is at/after the cls cutoff {cut:%H:%M} ET"
                record["refresh"] = {"not_run": refresh_exit}
            else:
                left = min(left, REFRESH_TIMEOUT_CAP_S)
                r = deps.refresh(asof, left)
                refresh_exit = r.incomplete if r.incomplete is not None else r.exit
                record["refresh"] = {"exit": r.exit, "incomplete": r.incomplete,
                                     "timeout_s": left, "tail": r.tail}
        closes_dated = deps.closes(asof, p["universe"])
        closes = {s: v[0] for s, v in closes_dated.items() if v[0] is not None}
        close_dates = {s: v[1] for s, v in closes_dated.items()}
        nav_dates = deps.navs(asof, p["universe"])
        record["closes"] = {s: {"close": v[0], "date": v[1]} for s, v in closes_dated.items()}
        record["nav_dates"] = nav_dates
        data_refusals = gt.gate_data(asof, refresh_exit, close_dates, nav_dates, p["universe"])

        # 2. read
        acct = c.account()
        pos = c.positions().qty
        # From midnight before the as-of date: an evening run's set (sent on the
        # as-of date, possibly a Friday for a Monday auction) must be in view.
        midnight = dt.datetime.combine(asof - dt.timedelta(days=1), dt.time(0),
                                       tzinfo=gt.ET)
        orders_recent = c.orders(status="all", after=midnight)
        orders_open = c.orders(status="open")
        closed = c.orders(status="closed")
        opening = is_opening_session(pos, closed)
        assets = {s: c.asset(s) for s in p["universe"]}
        shortable = {s: a["shortable"] for s, a in assets.items()}
        record.update(
            account={k: v for k, v in acct.items() if k != "raw"},
            positions=pos, opening_session=opening,
            orders_recent=[_order_summary(o) for o in orders_recent],
            orders_open=[_order_summary(o) for o in orders_open],
            assets={s: {k: a.get(k) for k in ("tradable", "shortable", "borrow_status",
                                              "easy_to_borrow", "marginable")}
                    for s, a in assets.items()})
        equity = acct["equity"]

        # 3. decide -- only on data that passed gate 5
        if data_refusals:
            decision = dec.Decision(orders=(), targets={}, notes={"*": [
                "not decided: the data gate refused"]}, plan_sha=dec.plan_sha(()))
        else:
            targets = deps.targets(asof, pos, equity, opening)
            decision = dec.decide(targets, pos, equity, closes, shortable,
                                  session_date=session_date, universe=p["universe"],
                                  cid_prefix=book.cid_prefix,
                                  min_trade_usd=p["min_trade_usd"],
                                  time_in_force="day" if late else dec.TIME_IN_FORCE)
        if decision.orders and deps.execution.get("bp_shortfall") == "scale":
            scaled, factor, binding = fit_to_buying_power(
                decision.orders, pos, closes, equity, acct["buying_power"], _gross_now(acct),
                acct["maintenance_margin"])
            record["bp_scale"] = {"factor": factor, "binding": binding}
            if binding is not None:
                decision = dec.Decision(orders=scaled, targets=decision.targets,
                                        notes={**decision.notes, "*": list(decision.notes.get("*", []))
                                               + [f"opening orders scaled x{factor:.4f} to fit "
                                                  f"{binding}"]},
                                        plan_sha=dec.plan_sha(scaled))
        record["decision"] = decision.to_dict()
        borrow_warnings = hard_to_borrow_short_opens(decision.orders, pos, assets)
        record["borrow_warnings"] = borrow_warnings

        # 4. gate -- on a clock read NOW, not the one from before the refresh.
        # Review 2026-09-28: the refresh, 13 asset GETs (each with retries) and
        # the sleeve all run after the first read; gating on it let a session
        # that reached here after 19:00 ET pass gate 4 and have its orders
        # queued into tomorrow's auction [V].
        clock_gate = c.clock()
        record["clock_at_gate"] = clock_gate["timestamp"]
        facts = gt.GateFacts(
            env_dry_run=deps.env.get("DRY_RUN"), approve_sha=approve,
            auto_armed=(state / "AUTO_ARMED").exists(), plan_sha=decision.plan_sha,
            halts=deps.halts(), clock_ts=clock_gate["timestamp"], session_date=session_date,
            calendar_today=cal_today,
            nyse_trading_today=_nyse_trading(session_date),
            asof=asof, refresh_exit=refresh_exit, close_dates=close_dates, nav_dates=nav_dates,
            started_exists=(day / "STARTED").exists(), orders_recent=orders_recent,
            orders_open=orders_open, cid_prefix=book.cid_prefix,
            orders=decision.orders, positions=pos, shortable=shortable,
            shorting_enabled=acct["shorting_enabled"], closes=closes, equity=equity,
            # Order-time: Alpaca's live buying_power. Overnight Reg T is checked on
            # the book AFTER the plan (gate.margin_limits; review 2026-10-07).
            buying_power=acct["buying_power"], current_gross=_gross_now(acct),
            maintenance_margin=acct["maintenance_margin"],
            max_gross_usd=p["max_gross_usd"],
            max_gross_stress=p["max_gross_stress"], universe=p["universe"],
            account_flags={k: acct[k] for k in ("trading_blocked", "account_blocked",
                                                "trade_suspended_by_user")})
        refusals = gt.evaluate(facts)
        record["refusals"] = [{"gate": r.gate, "detail": r.detail} for r in refusals]

        plan = {"book": book.name, "spec_id": p["spec_id"], "session_date": session_date,
                "asof": asof, "equity": equity, "opening_session": opening,
                **decision.to_dict(), "refusals": record["refusals"],
                "borrow_warnings": borrow_warnings, "mode": mode}
        shown = refusals
        if late:
            # DECIDE phase: dry-run, arming and the clock belong to the SEND phase.
            shown = [r for r in refusals if r.gate not in ("dry_run", "arming", "clock")]
            plan.update(execution="late_market", send_window=list(win), closes=closes,
                        status="refused" if shown else "decided",
                        refusals=[{"gate": r.gate, "detail": r.detail} for r in shown])
        # Late-market (review 2026-09-29): a DECIDED plan is what gets sent at
        # 15:52, so nothing overwrites it -- not a later manual run, and never a
        # --preview (which re-sizes on intraday equity and could replace the
        # evening's plan, or overwrite it with a refused one). To re-decide on
        # purpose, delete <D>/plan.json and <D>/DECIDED first (RUNBOOK).
        existing = _read_plan(day) if late else None
        keep = late and (preview or (existing or {}).get("status") == "decided")
        if not (day / "STARTED").exists() and not keep:
            rec.write_json_atomic(day / "plan.json", plan)
        elif late and (existing or {}).get("status") == "decided" and not preview:
            print(f"  a DECIDED plan already exists for {session_date} (plan_sha "
                  f"{existing.get('plan_sha')}); NOT overwritten -- it is the one sent "
                  f"in the window", file=out)

        print(f"{book.name} session {session_date} (as-of {asof}), equity ${equity:,.2f}, "
              f"opening_session={opening}", file=out)
        print(order_table(decision.orders), file=out)
        for sym, ns in sorted(decision.notes.items()):
            for n in ns:
                if not n.startswith("no trade: target equals"):
                    print(f"  note {sym}: {n}", file=out)
        for w in borrow_warnings:
            print(f"  WARNING {w}", file=out)
        print(f"plan_sha {decision.plan_sha}", file=out)
        for r in shown:
            print(f"  REFUSED {r}", file=out)

        if late:
            print(f"  execution: late-market; send window {win[0]:%Y-%m-%d %H:%M}-"
                  f"{win[1]:%H:%M} ET as market `day` orders", file=out)
            if preview:
                return _finish(record, day, stamp, mode, EXIT_PREVIEW, out)
            if shown:
                return _finish(record, day, stamp, mode, EXIT_REFUSED, out, scheduled=scheduled)
            if not decision.orders:
                return _finish(record, day, stamp, mode, EXIT_NOTHING, out, scheduled=scheduled)
            print(f"  approve: python3 -m quantt.session approve --book {book.name} "
                  f"--date {session_date} --sha {decision.plan_sha}", file=out)
            return _finish(record, day, stamp, mode, EXIT_PLANNED, out, scheduled=scheduled)

        if preview:
            return _finish(record, day, stamp, mode, EXIT_PREVIEW, out)
        gates_hit = {r.gate for r in refusals}
        if refusals:
            code = EXIT_DRY if ("dry_run" in gates_hit and gates_hit <= {"dry_run", "arming"}) \
                else EXIT_REFUSED
            return _finish(record, day, stamp, mode, code, out, scheduled=scheduled)
        if not decision.orders:
            return _finish(record, day, stamp, mode, EXIT_NOTHING, out, scheduled=scheduled)

        # 5. record BEFORE the first order
        started = {"plan_sha": decision.plan_sha, "session_date": session_date,
                   "pid": os.getpid(), "written_utc": deps.utcnow(),
                   "client_order_ids": [o.client_order_id for o in decision.orders],
                   "plan": plan}
        if not rec.create_exclusive(day / "STARTED", started):
            record["refusals"].append({"gate": "no_set_in_auction",
                                       "detail": "STARTED appeared between gate and record"})
            print("  REFUSED [no_set_in_auction] STARTED appeared between gate and record",
                  file=out)
            return _finish(record, day, stamp, mode, EXIT_REFUSED, out)
        rec.write_json_atomic(day / "plan.json", plan)

        # 6-7. transmit and confirm
        cut = gt.cutoff_et(session_date, cal_today[0]["close"])     # gate 4 passed: one row
        code = _transmit(c, decision.orders, day / "orders.jsonl", record, deps, out,
                         in_window=lambda ts: gt.in_send_window(ts, asof, cut),
                         window_text=(f"the send window for the {session_date} auction "
                                      f"({gt.queue_open_et(asof):%Y-%m-%d %H:%M} ET evening, "
                                      f"to {cut:%Y-%m-%d %H:%M} ET)"))
        return _finish(record, day, stamp, mode, code, out, scheduled=scheduled)
    except Exception as e:  # recorded and surfaced, never swallowed: exit FAIL
        record["error"] = f"{type(e).__name__}: {e}"
        record["traceback"] = traceback.format_exc()
        print(f"FAIL {type(e).__name__}: {e}", file=out)
        print(traceback.format_exc(), file=sys.stderr)
        return _finish(record, day, stamp, mode, EXIT_FAIL, out, state=state)


ORDER_FIELDS = ("symbol", "side", "qty", "leg", "client_order_id", "current", "target",
                "est_price", "reason", "time_in_force")


def load_decided_plan(day: Path, session_date: dt.date) -> tuple[dict, tuple]:
    """The saved late-market plan for `session_date` and its orders, rebuilt
    exactly. Raises unless the plan is decided, for this date, and its orders
    still hash to its plan_sha (a hand-edited plan never goes out)."""
    path = day / "plan.json"
    if not path.exists():
        raise SessionError(f"no plan for {session_date}: nothing was decided before the "
                           f"send window ({path})")
    plan = json.loads(path.read_text())
    if plan.get("execution") != "late_market" or plan.get("status") != "decided":
        raise SessionError(f"{path} is not a decided late-market plan (execution="
                           f"{plan.get('execution')!r}, status={plan.get('status')!r})")
    if plan.get("session_date") != session_date.isoformat():
        raise SessionError(f"{path} is for {plan.get('session_date')}, not {session_date}")
    orders = tuple(dec.Order(**{k: o[k] for k in ORDER_FIELDS}) for o in plan["orders"])
    if dec.plan_sha(orders) != plan.get("plan_sha"):
        raise SessionError(f"{path}: its orders hash to {dec.plan_sha(orders)}, the file says "
                           f"{plan.get('plan_sha')}; refusing a plan that is not what was decided")
    if any(o.time_in_force != "day" for o in orders):
        raise SessionError(f"{path}: a late-market plan holds a non-`day` order")
    return plan, orders


def _read_plan(day: Path) -> dict | None:
    p = day / "plan.json"
    return json.loads(p.read_text()) if p.exists() else None


def approval_for(day: Path) -> str | None:
    """The plan_sha the team lead approved for this session (<D>/APPROVED), or None."""
    p = day / "APPROVED"
    if not p.exists():
        return None
    return json.loads(p.read_text())["plan_sha"]


def _send_planned(book: Book, spec: dict, deps: Deps, record: dict, *, state: Path, day: Path,
                  stamp: str, mode: str, session_date: dt.date, clock: dict, cal: list,
                  win: tuple, approve: str | None, preview: bool, scheduled: bool) -> int:
    """The SEND phase (see "PAPER EXECUTION"): the saved plan, re-gated on fresh
    broker reads, sent as market `day` orders inside the late window."""
    out, c = deps.out, deps.client
    p = spec_params(spec)
    plan, orders = load_decided_plan(day, session_date)
    record.update(plan_sha=plan["plan_sha"], asof=plan["asof"])
    acct = c.account()
    pos = c.positions().qty
    asof = dt.date.fromisoformat(plan["asof"])
    midnight = dt.datetime.combine(asof - dt.timedelta(days=1), dt.time(0), tzinfo=gt.ET)
    orders_recent = c.orders(status="all", after=midnight)
    orders_open = c.orders(status="open")
    assets = {s: c.asset(s) for s in p["universe"]}
    shortable = {s: a["shortable"] for s, a in assets.items()}
    record.update(account={k: v for k, v in acct.items() if k != "raw"}, positions=pos,
                  orders_open=[_order_summary(o) for o in orders_open])
    # The plan was sized on these holdings; if they moved, it is not the plan any more.
    moved = {s: {"plan": t["current"], "now": pos.get(s, 0)}
             for s, t in plan["targets"].items() if pos.get(s, 0) != t["current"]}
    # A name whose `shortable` flipped since the decision (landmine 5: it changes
    # daily) is skipped at send and the rest go -- the team lead's rule for a
    # name that cannot trade (2026-09-28: "skip that name, send the rest"). The
    # arming check still binds to the DECIDED plan's sha: what goes is a subset
    # of what was approved, never anything else. Logged in send.json.
    skipped = []
    keep_orders = []
    for o in orders:
        cur = pos.get(o.symbol, 0)
        opens_short = o.side == "sell" and cur - o.qty < 0
        if opens_short and shortable.get(o.symbol) is not True:
            skipped.append(f"{o.client_order_id}: {o.symbol} shortable="
                           f"{shortable.get(o.symbol)!r} at send; skipped, the rest go")
        else:
            keep_orders.append(o)
    orders = tuple(keep_orders)
    record["skipped_at_send"] = skipped
    borrow_warnings = hard_to_borrow_short_opens(orders, pos, assets)
    approve_sha = approve or approval_for(day)
    clock_gate = c.clock()
    record["clock_at_gate"] = clock_gate["timestamp"]
    cal_today = [r for r in cal if r["date"] == session_date]
    closes = {k: float(v) for k, v in plan["closes"].items()}
    refusals = [
        *gt.gate_dry_run(deps.env.get("DRY_RUN")),
        *gt.gate_arming(approve_sha, plan["plan_sha"], (state / "AUTO_ARMED").exists()),
        *gt.gate_halt(deps.halts()),
        *gt.gate_late_clock(clock_gate["timestamp"], session_date, cal_today,
                            _nyse_trading(session_date), win),
        *gt.gate_no_set_in_auction((day / "STARTED").exists(), orders_recent, orders_open,
                                   book.cid_prefix, session_date),
        *gt.gate_shortability(orders, pos, shortable, acct["shorting_enabled"]),
        *gt.gate_exposure(orders, pos, closes, acct["equity"], acct["buying_power"],
                          p["max_gross_usd"], p["max_gross_stress"],
                          current_gross=_gross_now(acct),
                          maintenance_margin=acct["maintenance_margin"]),
        *gt.gate_sanity(orders, p["universe"], pos, book.cid_prefix, session_date,
                        {k: acct[k] for k in ("trading_blocked", "account_blocked",
                                              "trade_suspended_by_user")}),
    ]
    if moved:
        refusals.append(gt.Refusal("sanity", f"positions moved since the plan was decided: {moved}"))
    record["refusals"] = [{"gate": r.gate, "detail": r.detail} for r in refusals]
    print(f"{book.name} SEND {session_date} (plan decided on as-of {plan['asof']}), equity "
          f"${acct['equity']:,.2f}, window {win[0]:%H:%M}-{win[1]:%H:%M} ET", file=out)
    print(order_table(orders), file=out)
    print(f"plan_sha {plan['plan_sha']}", file=out)
    for x in skipped:
        print(f"  SKIPPED {x}", file=out)
    for w in borrow_warnings:
        print(f"  WARNING {w}", file=out)
    for r in refusals:
        print(f"  REFUSED {r}", file=out)
    if preview:
        return _finish(record, day, stamp, mode, EXIT_PREVIEW, out)

    def outcome(code):
        # verify and shadow read this (review 2026-09-29): without it a day the
        # SEND refused (dry run, halt, moved positions) read as a crash.
        rec.write_json_atomic(day / "send.json", {
            "session_date": session_date, "plan_sha": plan["plan_sha"], "at": stamp,
            "exit": EXIT_NAMES[code], "refusals": record["refusals"], "skipped": skipped,
            "final": record.get("final", {}), "unfilled": record.get("unfilled", {}),
            "not_final": record.get("not_final", [])})
        return _finish(record, day, stamp, mode, code, out, scheduled=scheduled)
    gates_hit = {r.gate for r in refusals}
    if refusals:
        return outcome(EXIT_DRY if ("dry_run" in gates_hit and gates_hit <= {"dry_run", "arming"})
                       else EXIT_REFUSED)
    if not orders:
        return outcome(EXIT_NOTHING)
    started = {"plan_sha": plan["plan_sha"], "session_date": session_date, "pid": os.getpid(),
               "written_utc": deps.utcnow(), "execution": "late_market",
               "client_order_ids": [o.client_order_id for o in orders], "plan": plan}
    if not rec.create_exclusive(day / "STARTED", started):
        print("  REFUSED [no_set_in_auction] STARTED appeared between gate and record", file=out)
        return _finish(record, day, stamp, mode, EXIT_REFUSED, out)
    close_h, close_m = map(int, cal_today[0]["close"].split(":"))
    poll_until = (dt.datetime.combine(session_date, dt.time(close_h, close_m), tzinfo=gt.ET)
                  - dt.timedelta(seconds=30))
    code = _transmit(c, orders, day / "orders.jsonl", record, deps, out,
                     in_window=lambda ts: win[0] <= ts < win[1],
                     window_text=f"late-market window {win[0]:%Y-%m-%d %H:%M}-{win[1]:%H:%M} ET",
                     poll_until=poll_until)
    return outcome(code)


def approve_main(argv=None) -> int:
    """`python3 -m quantt.session approve --book cef --date D --sha PLAN_SHA`.

    Records the team lead's go for ONE decided late-market plan, so the
    scheduled send in the late window may transmit it (gate 2). Run only on the
    team lead's explicit go on the shown order list (CLAUDE.md order-path rule 1).
    Refuses unless the plan exists, is decided, is for D, hashes to its sha, and
    that sha is the one given; refuses once a set has STARTED.
    """
    ap = argparse.ArgumentParser(prog="python3 -m quantt.session approve")
    ap.add_argument("--book", required=True, choices=sorted(BOOKS))
    ap.add_argument("--date", required=True, type=dt.date.fromisoformat)
    ap.add_argument("--sha", required=True)
    a = ap.parse_args(argv)
    try:
        state = rec.state_dir_from_env(os.environ)
        day = rec.day_dir(state, a.date)
        if (day / "STARTED").exists():
            raise SessionError(f"a set already STARTED for {a.date}; nothing to approve")
        plan, _ = load_decided_plan(day, a.date)
        if plan["plan_sha"] != a.sha:
            raise SessionError(f"plan for {a.date} is {plan['plan_sha']}, not {a.sha}")
    except Exception as e:
        print(f"REFUSED: {type(e).__name__}: {e}")
        return EXIT_REFUSED
    rec.write_json_atomic(day / "APPROVED", {
        "plan_sha": a.sha, "session_date": a.date,
        "approved_utc": dt.datetime.now(dt.timezone.utc), "orders": len(plan["orders"])})
    print(f"APPROVED {a.date} plan_sha {a.sha} ({len(plan['orders'])} orders); it is sent in "
          f"the window {plan['send_window'][0]} -> {plan['send_window'][1]} if every gate passes")
    return 0


def _opening_part(o, cur: int) -> int:
    """Shares of order `o` that open or increase a position (the rest reduce)."""
    after = cur + o.signed_qty
    if o.side == "buy":
        return max(0, after - max(cur, 0))
    return max(0, min(cur, 0) - after)


def fit_to_buying_power(orders, positions: dict, closes: dict, equity: float,
                        buying_power: float, current_gross: float,
                        maintenance_margin: float) -> tuple[tuple, float, str | None]:
    """Scale every OPENING order by one factor f in (0, 1] so the plan fits
    Alpaca's order-time buying power and the overnight margin limits
    (gate.buying_power_needed / gate.margin_limits); reducing orders are kept
    in full. Returns (orders, f, binding constraint or None when f == 1).

    WHY (team lead 2026-10-07, after the execution-desk review): refusing a
    plan that does not fit leaves yesterday's stale book in place; skipping
    names breaks dollar-neutrality arbitrarily. One factor on every opening
    order -- long and short alike -- keeps the book balanced and lands it
    proportionally short of target; the next session closes the gap. It is the
    same uniform scale-down the sleeve's gross cap uses. Flips are deferred
    (decide.FLIP_SAME_SESSION), so each order is wholly opening or reducing.
    Whole shares are floored, so the scaled plan never exceeds the limit at
    the as-of closes; the SEND re-checks on live numbers and refuses if not.
    """
    import dataclasses
    need = gt.buying_power_needed(orders, positions, closes)
    opening = {o.client_order_id: _opening_part(o, positions.get(o.symbol, 0)) for o in orders}
    g_inc = sum(opening[o.client_order_id] * closes[o.symbol] for o in orders)
    fixed = gt.projected_positions([o for o in orders if not opening[o.client_order_id]],
                                   positions)
    g_fixed = sum(abs(q) * closes[s] for s, q in fixed.items())
    caps = {"order-time buying_power": buying_power / need if need > 0 else float("inf")}
    if g_inc > 0:
        caps["overnight Reg T initial margin"] = (equity / gt.REG_T_INITIAL - g_fixed) / g_inc
        if current_gross > 0:
            ratio = maintenance_margin / current_gross
            caps["overnight maintenance (measured ratio)"] = (equity / ratio - g_fixed) / g_inc
    binding = min(caps, key=caps.get)
    f = min(1.0, caps[binding])
    if f >= 1.0:
        return tuple(orders), 1.0, None
    f = max(0.0, f)
    out = []
    for o in orders:
        if not opening[o.client_order_id]:
            out.append(o)
            continue
        q = math.floor(o.qty * f)
        if q <= 0:
            continue
        out.append(dataclasses.replace(o, qty=q, target=o.current + (q if o.side == "buy" else -q),
                                       reason=f"{o.reason}; scaled x{f:.4f} to fit {binding}"))
    return dec.transmit_sequence(out), f, binding


def _gross_now(acct: dict) -> float:
    """Current gross from Alpaca's own marks: long_market_value + |short_market_value|."""
    return float(acct["long_market_value"]) + abs(float(acct["short_market_value"]))


def _nyse_trading(d: dt.date) -> bool:
    from ops.schedule.nyse_calendar import is_trading_day
    return is_trading_day(d)


def hard_to_borrow_short_opens(orders, positions: dict, assets: dict) -> list[str]:
    """One warning per order that opens or increases a short in a name whose
    `borrow_status` today is not `easy_to_borrow`.

    WHY A WARNING AND NOT A REFUSAL. Alpaca: an HTB short "strictly requires"
    a locate, and locates are "not available in paper trading" [V,
    results/ops/ALPACA_API_FACTS_2026-09-28.md]; so such an order is the most
    likely rejection in the batch, and any rejection stops the batch. Whether
    gate 7 should refuse `borrow_status != easy_to_borrow` is a team-lead
    decision not yet taken (RUNNER.md gate 7 keys on `shortable` only, prereg
    v7 section 6). Until it is, the preview shows it loudly so the person saying
    go on the first session sees it. A missing `borrow_status` is also warned:
    it is not a measurement of easy-to-borrow.
    """
    out, running = [], dict(positions)
    for o in orders:
        cur = running.get(o.symbol, 0)
        after = cur + o.signed_qty
        running[o.symbol] = after
        if after < 0 and after < min(cur, 0):
            bs = (assets.get(o.symbol) or {}).get("borrow_status")
            if bs != "easy_to_borrow":
                out.append(f"{o.client_order_id} opens/increases a short in {o.symbol} with "
                           f"borrow_status={bs!r}; Alpaca requires a locate for HTB shorts and "
                           f"paper has none [V], so this order may be rejected and stop the batch")
    return out


FINAL_ORDER_STATES = {"filled", "canceled", "expired", "rejected", "done_for_day", "replaced"}
POLL_EVERY_S = 2.0


def _poll_final(c, sent, log: Path, record: dict, deps: Deps, out, until: dt.datetime) -> None:
    """Poll every sent order until it reaches a final state or `until` (late-
    market: 30 s before the close). Review 2026-10-07: the confirm read came ~1 s
    after submit, when on 2026-10-07 4 orders were still `new` and 5
    `partially_filled`, and the run exited SENT without ever seeing the fills.
    Records each order's final status and filled/unfilled shares; NEVER tops up
    a remainder (CLAUDE.md order-path rule 1: that is the team lead's call)."""
    pending = {o.client_order_id: o for o in sent}
    final = {}
    # Bounded by a poll COUNT as well as the clock: a clock source that stops
    # advancing must never turn this into an endless loop past the close.
    max_polls = max(1, int((until - deps.utcnow()).total_seconds() // POLL_EVERY_S) + 1)
    polls = 0
    while pending:
        polls += 1
        for cid, o in list(pending.items()):
            got = c.order_by_client_id(cid)
            if got is not None and got.get("status") in FINAL_ORDER_STATES:
                filled = int(Decimal(str(got.get("filled_qty") or 0)))
                final[cid] = {"status": got["status"], "filled": filled,
                              "unfilled": o.qty - filled,
                              "filled_avg_price": got.get("filled_avg_price")}
                rec.append_jsonl(log, {"event": "final", "at": deps.utcnow(),
                                       "client_order_id": cid, **final[cid]})
                del pending[cid]
        if not pending or deps.utcnow() >= until or polls >= max_polls:
            break
        deps.sleep(POLL_EVERY_S)
    for cid in pending:
        rec.append_jsonl(log, {"event": "not_final_at_deadline", "at": deps.utcnow(),
                               "client_order_id": cid})
    record["final"] = final
    record["not_final"] = sorted(pending)
    unfilled = {cid: f["unfilled"] for cid, f in final.items() if f["unfilled"]}
    record["unfilled"] = unfilled
    n_full = sum(1 for f in final.values() if not f["unfilled"])
    print(f"  fills: {n_full}/{len(sent)} fully filled"
          + (f"; UNFILLED {unfilled}" if unfilled else "")
          + (f"; not final by {until:%H:%M:%S}: {sorted(pending)}" if pending else ""), file=out)


def _transmit(c, orders, log: Path, record: dict, deps: Deps, out, *,
              in_window: Callable[[dt.datetime], bool], window_text: str,
              poll_until: dt.datetime | None = None) -> int:
    """POST each order in list order.

    A REJECTED order (Alpaca answered 4xx: it definitely does not exist) skips
    that symbol and the rest are still sent -- team lead, 2026-09-28: better
    fill coverage, accepting that the book can be net long or short that day.
    The day is still FAIL, loudly, naming every rejection. If EVERY order is
    rejected (e.g. paper refuses `cls` outright) nothing was sent, and the
    team lead decides the substitute: there is no fallback to `day` (team
    lead, 2026-09-28; CLAUDE.md rule 3). Anything whose outcome is UNKNOWN --
    an ambiguous submit, an unexpected error, a clock that cannot be read or
    has crossed the cutoff -- still stops the batch.

    Before EVERY POST the Alpaca clock is read again and the batch stops if
    `in_window` says it is outside the send window (gate.in_send_window for
    `cls`; the late window for late-market): an order sent past 15:50 is rejected and
    one sent after 19:00 is queued into the next day's auction [V], and a POST
    retry or a slow response can carry a batch across either line. A clock read that fails also stops the batch -- an unmeasured
    time is not "before the cutoff".
    """
    from quantt.broker.alpaca import AmbiguousSubmit, OrderRejected
    now = deps.utcnow
    sent, failed, rejected = [], None, []
    for o in orders:
        if o.symbol in {r[1] for r in rejected}:
            # a later leg for a symbol whose earlier leg was rejected
            rec.append_jsonl(log, {"event": "skipped_after_rejection", "at": now(),
                                   "client_order_id": o.client_order_id})
            continue
        try:
            ts = c.clock()["timestamp"]
        except Exception as e:
            rec.append_jsonl(log, {"event": "clock_error", "at": now(),
                                   "client_order_id": o.client_order_id,
                                   "error": f"{type(e).__name__}: {e}"})
            failed = f"clock read failed before {o.client_order_id}; batch stopped"
            break
        t_et = ts.astimezone(gt.ET)
        if not in_window(ts):
            rec.append_jsonl(log, {"event": "cutoff", "at": now(), "clock": ts,
                                   "client_order_id": o.client_order_id,
                                   "window": window_text})
            failed = (f"Alpaca clock {t_et:%Y-%m-%d %H:%M:%S} ET is outside the send window "
                      f"-- {window_text} -- before {o.client_order_id}; batch stopped")
            break
        rec.append_jsonl(log, {"event": "submit", "at": now(), **o.wire()})
        try:
            resp = c.submit_order(o.symbol, o.qty, o.side, o.client_order_id,
                                  time_in_force=o.time_in_force)
        except AmbiguousSubmit as e:
            rec.append_jsonl(log, {"event": "ambiguous", "at": now(),
                                   "client_order_id": o.client_order_id, "error": str(e)})
            try:
                found = c.order_by_client_id(o.client_order_id)
                rec.append_jsonl(log, {"event": "lookup", "at": now(),
                                       "client_order_id": o.client_order_id,
                                       "found": found is not None,
                                       "order": _order_summary(found) if found else None})
            except Exception as le:
                rec.append_jsonl(log, {"event": "lookup_error", "at": now(),
                                       "client_order_id": o.client_order_id,
                                       "error": f"{type(le).__name__}: {le}"})
            failed = f"AmbiguousSubmit on {o.client_order_id}; batch stopped"
            break
        except OrderRejected as e:
            rec.append_jsonl(log, {"event": "rejected", "at": now(),
                                   "client_order_id": o.client_order_id, "error": str(e)})
            rejected.append((o.client_order_id, o.symbol))
            print(f"  REJECTED {o.client_order_id}: {e}", file=out)
            continue
        except Exception as e:
            rec.append_jsonl(log, {"event": "error", "at": now(),
                                   "client_order_id": o.client_order_id,
                                   "error": f"{type(e).__name__}: {e}"})
            failed = f"{type(e).__name__} on {o.client_order_id}; batch stopped"
            break
        rec.append_jsonl(log, {"event": "accepted", "at": now(),
                               "client_order_id": o.client_order_id,
                               "order": _order_summary(resp)})
        sent.append(o)
        print(f"  sent {o.client_order_id} {o.side} {o.qty} {o.symbol} -> "
              f"{resp.get('status')}", file=out)

    missing = []
    for o in sent:
        got = c.order_by_client_id(o.client_order_id)
        ok = (got is not None and got.get("symbol") == o.symbol and got.get("side") == o.side
              and _same_qty(got.get("qty"), o.qty))
        rec.append_jsonl(log, {"event": "confirm", "at": now(),
                               "client_order_id": o.client_order_id, "ok": ok,
                               "order": _order_summary(got) if got else None})
        if not ok:
            missing.append(o.client_order_id)
    record["sent"] = [o.client_order_id for o in sent]
    record["rejected"] = [cid for cid, _ in rejected]
    record["confirm_missing"] = missing
    if poll_until is not None and sent:
        _poll_final(c, [o for o in sent if o.client_order_id not in missing], log, record,
                    deps, out, poll_until)
    if rejected and not failed:
        failed = (f"{len(rejected)} order(s) rejected by Alpaca "
                  f"{[cid for cid, _ in rejected]}; "
                  + ("NOTHING was sent -- team lead decides (no fallback to day)"
                     if not sent else f"{len(sent)} other order(s) sent"))
    if failed:
        record["transmit_failure"] = failed
        print(f"FAIL {failed}", file=out)
        return EXIT_FAIL
    if missing:
        print(f"FAIL not confirmed at Alpaca: {missing}", file=out)
        return EXIT_FAIL
    return EXIT_SENT


def _same_qty(v, want: int) -> bool:
    try:
        return Decimal(str(v)) == want
    except InvalidOperation:
        return False


def _finish(record, day, stamp, mode, code, out, state=None, scheduled=False) -> int:
    record["exit"] = {"code": code, "name": EXIT_NAMES[code]}
    target = day if day is not None else state
    if target is not None:
        runs = target / "runs"
        runs.mkdir(exist_ok=True)
        rec.write_json_atomic(runs / f"{stamp}-{mode}.json", record)
    # Done markers for later scheduled slots (done_reason). Only an outcome that
    # a retry cannot improve is marked; REFUSED and FAIL leave the next slot
    # free to try again (STARTED already stops any retry after a send began).
    if scheduled and day is not None:
        marker = {EXIT_SENT: "DONE", EXIT_NOTHING: "DONE", EXIT_DRY: "DRY_DONE",
                  EXIT_PLANNED: "DECIDED"}.get(code)
        if marker:
            (day / marker).write_text(f"{EXIT_NAMES[code]} at {stamp} (runs/{stamp}-{mode}.json)\n")
    print(f"exit {code} {EXIT_NAMES[code]}", file=out)
    return code


# ----------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m quantt.session run",
                                 description="One trading session (docs/RUNNER.md).")
    ap.add_argument("--book", required=True, choices=sorted(BOOKS))
    ap.add_argument("--preview", action="store_true",
                    help="print the order list and plan_sha; never sends")
    ap.add_argument("--approve", metavar="PLAN_SHA", default=None,
                    help="send only if the recomputed plan_sha equals this (gate 2)")
    ap.add_argument("--skip-refresh", action="store_true",
                    help="do not run the fetcher; the panel must still end on the as-of date")
    ap.add_argument("--scheduled", action="store_true",
                    help="launchd mode: try only in the evening/morning slots, and only "
                         "until the session is done; otherwise exit 5 IDLE")
    a = ap.parse_args(argv)
    book = BOOKS[a.book]
    try:
        spec = load_spec(book.spec_path)
        deps = default_deps(book, spec, os.environ)
    except Exception as e:
        print(f"FAIL before the session could start: {type(e).__name__}: {e}")
        print(f"exit {EXIT_FAIL} FAIL")
        return EXIT_FAIL
    return run_session(book, spec, deps, preview=a.preview, approve=a.approve,
                       skip_refresh=a.skip_refresh, scheduled=a.scheduled)
