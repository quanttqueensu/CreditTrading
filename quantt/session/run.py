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
  1b. NAV gate only when the book json sets `data.stale_nav` (absent = off,
               the behaviour above unchanged; `report` records what `on` would
               do and changes nothing). Gate 5 checks a NAV's DATE; Yahoo serves
               rows dated D carrying an older NAV
               (results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5). A name whose
               NAV(D) equals its previous NAV, or CEFConnect's NAV(D-1), is
               checked against CEFConnect's D: a stale copy is replaced (logged
               fallback), a genuine repeat kept. An UNVERIFIED name DEFERS the
               decide until the final pre-send check (a gate-5 `data` refusal:
               nothing decided, nothing marked, the next slot re-reads
               CEFConnect); from the final check it is HELD at its current
               shares, out of the cross-section (team lead 2026-10-13;
               `nav_gate.py`, "DEFERRAL AND THE ORDER PATH" below). After the
               sleeve has read the panel, `still_holds` checks it was the panel
               the gate certified, or the session FAILs.
  2. read      Alpaca clock, calendar, account, positions, orders, assets.
  2b. drawdown only when the book json sets `risk.drawdown` (absent = off;
               `report` is the only mode built). The book's drawdown from its
               high-water mark on `<state>/eod_equity.csv` (Alpaca's EOD
               portfolio history, the official daily P&L) is compared with the
               frozen spec's risk.halve_drawdown / risk.kill_drawdown and
               recorded in plan.json and the log, with what an `on` mode would
               do. Nothing that trades reads it (`drawdown.py`; team lead
               2026-10-19).
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

DEFERRAL AND THE ORDER PATH (stale-NAV gate, `on` mode; team lead 2026-10-13).
A decide that finds an unverified NAV before the final pre-send check
(`nav_gate.final_check_at`: the session's calendar close minus 90 minutes, on
the session date; an evening run is never final) is REFUSED with a gate-5
`data` refusal naming the names. Nothing new was built around it, on purpose:
  * one plan per day: a refused plan is never `decided`, so `DECIDED` is not
    written and plan.json is overwritten by the next run, exactly as on an
    evening whose NAVs have not landed. The morning backstop's slots re-run
    refresh + gate and re-read CEFConnect; the first that verifies every name,
    or the first at or after the final check (holding what is still
    unverified), decides. A decided plan is never re-decided (unchanged).
  * STARTED / idempotency (CLAUDE.md order-path rule 2): untouched. A deferral
    happens at DECIDE, before any order and before STARTED could exist;
    `done_reason` and gate 6 still stop any second set for the auction.
  * plan_sha and approval: a refused plan cannot be approved (`approve_main`
    needs a decided plan) and cannot be sent (`load_decided_plan` needs one).
    The plan_sha that APPROVED or `--approve` binds to is the morning plan's,
    computed after the re-check; AUTO_ARMED sends whatever is decided, as now.
  * DRY_RUN: a deferral is a `data` refusal, so it is REFUSED, never DRY, and
    can never write DRY_DONE and idle the morning behind it.
  * late_market (CLAUDE.md order-path rule 3, the paper exception): the send
    window is unchanged; the final check sits 82 minutes before it opens, and
    the 15:00 slot is left to retry a final decide that failed. In `cls` mode
    the same refusal stops the evening send and the morning slots decide and
    send before the cls cutoff.
  * verify: a day still deferred at the send reads, from plan.json's refusal,
    `MISSED: ... [data] stale-NAV gate: ... deferred`: a FAIL, never a PASS.

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
import itertools
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
from quantt.session import drawdown as ddm
from quantt.session import gate as gt
from quantt.session import nav_gate as ng
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


def close_history(px_path: Path, asof: dt.date, universe, rows: int):
    """The last `rows` closes on or before `asof`: a date-indexed frame, one column
    per name, each name forward-filled over its own gaps (landmine 6). Same
    discipline as `last_closes`: rows after `asof` are dropped before anything
    is read (NO LOOKAHEAD, asserted), and a duplicate (date, ticker) raises."""
    import pandas as pd
    P = pd.read_parquet(px_path, columns=["date", "ticker", "close"])
    P = P[P["ticker"].isin(list(universe))].copy()
    P["date"] = pd.to_datetime(P["date"]).dt.normalize()
    P = P[P["date"] <= pd.Timestamp(asof)]
    dup = P[P.duplicated(["date", "ticker"], keep=False)]
    if len(dup):
        raise SessionError(f"{px_path}: duplicate (date, ticker) rows, e.g. "
                           f"{dup.head(3).to_dict('records')}")
    wide = P.pivot(index="date", columns="ticker", values="close").sort_index().ffill()
    assert wide.index.max().date() <= asof, f"lookahead: close history past {asof}"
    return wide.iloc[-rows:]


# THE PRE-FLIGHT (team lead's go 2026-10-09, after that day's two refused sends).
# The evening DECIDE re-runs the SEND phase's exposure path -- the re-fit when
# bp_shortfall is "scale", then gate 8 -- on an account whose equity is lower by
# the worst one-day loss of the book held NOW over the last
# PREFLIGHT_WINDOW_SESSIONS close-to-close changes up to the as-of date. That is
# the book whose marks move equity between the decide and the 15:52 send. If an
# ordinary bad day would get tomorrow's send refused or scaled, the decide says
# so tonight: a day's notice instead of none.
# 252 sessions = one year of the book's own names, so the worst day comes from
# the regime the book trades in now. The pre-flight sizes a WARNING and decides
# nothing (H14): the send re-measures everything on live reads at 15:52.
# Buying power is held at its decide-time value: how Alpaca's buying_power moves
# with equity intraday is not modelled.
PREFLIGHT_WINDOW_SESSIONS = 252


def worst_day_loss(history, book: dict, window: int) -> tuple[float, dt.date | None]:
    """(dollars, date): the largest one-day loss of holding `book` (signed
    shares) over the last `window` close-to-close changes in `history`
    (`close_history`). Price changes only -- no distributions, no borrow: a
    stress size, not a P&L. 0.0 for a flat book. Raises naming any held name
    without a close on every one of the window's rows; it never assumes one."""
    names = sorted(s for s, q in book.items() if q)
    if not names:
        return 0.0, None
    missing = [s for s in names if s not in history.columns]
    tail = history.iloc[-(window + 1):]
    gaps = [s for s in names if s not in missing and tail[s].isna().any()]
    if missing or gaps or len(tail) < window + 1:
        raise SessionError(f"pre-flight: {len(tail)} rows of close history, {window + 1} "
                           f"needed; no column for {missing}; gaps in {gaps}")
    import pandas as pd
    pnl = tail[names].diff().iloc[1:].mul(pd.Series({s: book[s] for s in names})).sum(axis=1)
    return max(0.0, -float(pnl.min())), pnl.idxmin().date()


def preflight_send(orders, positions: dict, closes: dict, acct: dict, p: dict,
                   execution: dict, *, sized_equity: float, history) -> dict:
    """See PREFLIGHT_WINDOW_SESSIONS. Returns what the SEND phase would do if
    equity were the worst day lower: {"ok", "shock_usd", "shock_date",
    "equity_stressed", "scaled", "kept", "refusals"}; `kept` (2026-10-13) is the
    share of the plan's traded notional the re-fit would keep."""
    loss, on = worst_day_loss(history, positions, PREFLIGHT_WINDOW_SESSIONS)
    eq = float(acct["equity"]) - loss
    out_orders, binding, kept = tuple(orders), None, 1.0
    if execution.get("bp_shortfall") == "scale" and out_orders:
        out_orders, kept, binding = fit_to_buying_power(
            out_orders, positions, closes, eq, acct["buying_power"], _gross_now(acct),
            acct["maintenance_margin"], max_gross_stress=p["max_gross_stress"],
            sized_equity=sized_equity)
    refusals = gt.gate_exposure(out_orders, positions, closes, eq, acct["buying_power"],
                                p["max_gross_usd"], p["max_gross_stress"],
                                sized_equity=sized_equity, current_gross=_gross_now(acct),
                                maintenance_margin=acct["maintenance_margin"])
    return {"ok": not refusals and binding is None, "shock_usd": round(loss, 2),
            "shock_date": on, "window_sessions": PREFLIGHT_WINDOW_SESSIONS,
            "equity_stressed": round(eq, 2), "scaled": binding, "kept": round(kept, 4),
            "refusals": [{"gate": r.gate, "detail": r.detail} for r in refusals]}


def _preflight(deps, orders, positions, closes, acct, p, asof, *, sized_equity) -> dict:
    """`preflight_send`, recorded whatever happens. A pre-flight that cannot run
    records UNMEASURED and the reason, in plan.json and the log. It is advisory:
    it must never stop the plan it describes from being saved, because a lost
    plan is a missed day. So its errors are caught here, and written down."""
    if deps.history is None:
        return {"unmeasured": "no close-history reader in this session's deps"}
    try:
        hist = deps.history(asof, p["universe"], PREFLIGHT_WINDOW_SESSIONS + 1)
        return preflight_send(orders, positions, closes, acct, p, deps.execution,
                              sized_equity=sized_equity, history=hist)
    except Exception as e:  # recorded in plan.json and printed, never swallowed (docstring)
        return {"unmeasured": f"{type(e).__name__}: {e}"}


def preflight_line(pf: dict) -> str:
    """One line for the session log; orient reads plan.json's "preflight"."""
    if "unmeasured" in pf:
        return f"  PRE-FLIGHT UNMEASURED: {pf['unmeasured']}"
    at = (f"at equity ${pf['equity_stressed']:,.2f} (${pf['shock_usd']:,.2f} lower: the worst "
          f"one-day loss of the book held now over the last {pf['window_sessions']} sessions"
          + (f", on {pf['shock_date']}" if pf["shock_date"] else "") + ")")
    if pf["refusals"]:
        return (f"  PRE-FLIGHT WARNING: {at} the send would be REFUSED: "
                + "; ".join(f"[{r['gate']}] {r['detail']}" for r in pf["refusals"]))
    if pf["scaled"]:
        return (f"  PRE-FLIGHT WARNING: {at} the send would scale the plan to {pf['kept']:.1%} "
                f"of its traded notional to fit {pf['scaled']}")
    return f"  PRE-FLIGHT ok: {at} the send still goes whole"


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
                   equity: float, opening: bool, nav_hold: dict | None = None) -> list:
    """The strategy's targets, built exactly as RUNNER.md step 3 says: the
    registry's sleeve from the frozen spec at the spec's capital, asked on the
    as-of date with the broker's holdings and the two extras. `nav_hold`
    ({"asof", "names"}, from the stale-NAV gate in `on` mode) is added as a third
    extra only when the gate holds a name, so otherwise the sleeve's input is
    unchanged."""
    import pandas as pd
    from src.deploy.registry import build_sleeve
    from src.deploy.sleeve import MarketState
    from src.deploy.sleeves import cef_discount as cefmod
    sl = build_sleeve(spec, capital)
    ts = pd.Timestamp(asof)
    prices = pd.read_parquet(cefmod.PX_PATH)       # MarketState requires it; this sleeve reads its own panel
    prices = prices[pd.to_datetime(prices["date"]) <= ts]
    extras = {"sleeve_nav": equity, "opening_session": opening}
    if nav_hold is not None:
        extras["nav_hold"] = nav_hold
    ms = MarketState(asof=ts, prices=prices, holdings=dict(holdings), extras=extras)
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


def stale_nav_for(book: Book) -> str | None:
    """The book json's `data.stale_nav`: the stale-NAV gate's mode, or None.

    ABSENT means no gate, today's behaviour (CLAUDE.md: a new key defaults to
    current behaviour), exactly as an absent `execution` block means `cls`.
    Present, it must be one of `nav_gate.MODES`; anything else raises. Why the
    gate is a runner setting and not a frozen-spec key: `nav_gate` docstring."""
    data = json.loads(book.book_path.read_text()).get("data")
    if data is None:
        return None
    if not isinstance(data, dict) or "stale_nav" not in data:
        raise SessionError(f"{book.book_path}: a `data` block must set stale_nav to one of "
                           f"{ng.MODES} (or the block must be deleted)")
    mode = data["stale_nav"]
    if mode not in ng.MODES:
        raise SessionError(f"{book.book_path}: data.stale_nav {mode!r} is not one of {ng.MODES}")
    return mode


def drawdown_for(book: Book) -> str | None:
    """The book json's `risk.drawdown`: the drawdown check's mode, or None.

    ABSENT means no check, today's behaviour (CLAUDE.md: a new key defaults to
    current behaviour), as an absent `data` block means no stale-NAV gate.
    Present, it must be one of `drawdown.MODES`, which today is `report` only:
    `on` is not built and raises here, so a book json cannot claim an armed
    HALVE/KILL that nothing enforces (the defect `drawdown.py` replaces). Why a
    runner setting and the levels in the frozen spec: the levels are the
    strategy's commitment and already live there; whether the runner acts on them
    is how the runner runs, like `execution` and `data`."""
    risk = json.loads(book.book_path.read_text()).get("risk")
    if risk is None:
        return None
    if not isinstance(risk, dict) or "drawdown" not in risk:
        raise SessionError(f"{book.book_path}: a `risk` block must set drawdown to one of "
                           f"{ddm.MODES} (or the block must be deleted)")
    mode = risk["drawdown"]
    if mode not in ddm.MODES:
        raise SessionError(f"{book.book_path}: risk.drawdown {mode!r} is not one of "
                           f"{ddm.MODES}; an acting mode is not built and needs the team "
                           f"lead's ruling (quantt/session/drawdown.py)")
    return mode


def _drawdown(deps, state: Path, spec: dict, asof: dt.date) -> tuple[dict, list]:
    """Step 2b, the drawdown check (quantt/session/drawdown.py): (record, log
    lines). Report mode changes nothing that trades, so an unexpected error,
    in the check or in its log lines, is recorded as UNMEASURED with its type
    and the session goes on, like the stale-NAV gate's report mode and the
    pre-flight. Only report mode exists; an acting mode would have to stop the
    session instead (drawdown.py, WHY UNMEASURED SHOULD BLOCK UNDER `on`), hence
    the re-raise."""
    try:
        res = ddm.check(state, spec, asof, deps.drawdown)
        return res, ddm.lines(res)
    except Exception as e:  # report mode: recorded in plan.json and printed, never swallowed
        if deps.drawdown != ddm.REPORT:
            raise
        res = ddm.unmeasured_record(deps.drawdown, asof, f"{type(e).__name__}: {e}")
        return res, [f"  DRAWDOWN ({deps.drawdown}): UNMEASURED: {res['why']}. Report mode: "
                     f"no order changed."]


def _nav_gate(deps, asof: dt.date, universe, refresh_exit, final: bool, record_csv):
    """Step 1b, the stale-NAV gate (quantt/session/nav_gate.py). Returns
    (record dict, GateResult or None).

    It runs only on a refresh that passed (or was skipped): a failed refresh is
    gate 5's refusal and nothing is decided, so there is no NAV to certify. In
    act mode an error is the session's error (FAIL, the next slot retries):
    deciding without knowing which NAVs are stale is what the gate exists to
    stop. In report mode it changes nothing that trades, so an error is
    recorded as UNMEASURED and the session goes on, like the pre-flight.
    `record_csv(result)` is the gate's record; in act mode the gate writes it
    BEFORE it writes the panel (nav_gate.PanelGate.run, RECORD FIRST)."""
    mode = deps.stale_nav
    if refresh_exit is not None and refresh_exit != 0:
        return {"mode": mode, "not_run": f"the refresh did not pass ({refresh_exit}); "
                                         f"gate 5 refuses the day"}, None
    if deps.nav_gate is None:
        raise SessionError(f"the book sets data.stale_nav={mode!r} but this session has no "
                           f"NAV gate wired in its deps")
    try:
        res = deps.nav_gate.run(asof, universe, mode, deps.utcnow(), final,
                                record=record_csv if mode == ng.ON else None)
    except Exception as e:  # report mode only: recorded, never swallowed (docstring)
        if mode != ng.REPORT:
            raise
        return {"mode": mode, "unmeasured": f"{type(e).__name__}: {e}"}, None
    return res.to_dict(), res


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
    # (asof, universe, rows) -> close_history frame, for the pre-flight. None
    # means not wired; the pre-flight then records itself UNMEASURED, never ok.
    history: Callable[[dt.date, tuple, int], object] | None = None
    # The stale-NAV gate (step 1b): its mode from the book json (None = off,
    # today's behaviour; `stale_nav_for`) and the gate itself, a
    # `nav_gate.PanelGate` or a fake with its `run` and `still_holds`.
    stale_nav: str | None = None
    nav_gate: object | None = None
    # The drawdown check (step 2b): its mode from the book json (None = off,
    # today's behaviour; `drawdown_for`).
    drawdown: str | None = None


def default_deps(book: Book, spec: dict, env) -> Deps:
    from quantt.broker.alpaca import AlpacaClient
    if not env.get("QUANTT_ENV_FILE"):
        raise SessionError("QUANTT_ENV_FILE is not set: it must name the key file")
    from src.deploy.sleeves import cef_discount as cefmod
    p = spec_params(spec)
    stale_nav = stale_nav_for(book)
    gate = None
    if stale_nav is not None:
        # The sleeve's own NAV path: the gate certifies the file the sleeve reads.
        # The fallback log and the panel lock are fetch_daily's, resolved only when
        # the gate writes, so no run imports scripts/ here (`nav_gate.PanelGate`).
        gate = ng.PanelGate(nav_path=cefmod.NAV_PATH)
    return Deps(
        client=AlpacaClient.from_environment(book.name),
        env=dict(env),
        refresh=lambda asof, timeout_s: refresh_subprocess(asof, book, timeout_s),
        closes=lambda asof, uni: last_closes(cefmod.PX_PATH, asof, uni),
        navs=lambda asof, uni: last_navs(cefmod.NAV_PATH, asof, uni),
        history=lambda asof, uni, rows: close_history(cefmod.PX_PATH, asof, uni, rows),
        targets=lambda asof, h, eq, op, **kw: sleeve_targets(spec, p["capital_usd"], asof, h,
                                                             eq, op, **kw),
        halts=lambda: halts_for(book),
        execution=execution_for(book),
        stale_nav=stale_nav,
        nav_gate=gate,
        drawdown=drawdown_for(book),
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
        # 1b. the stale-NAV gate (quantt/session/nav_gate.py). Off unless the
        # book json sets data.stale_nav; then nothing below changes but the
        # record, the panel's stale copies and the names the sleeve drops.
        gate_res = None
        if deps.stale_nav is not None:
            final = len(cal_today) == 1 and clock["timestamp"] >= ng.final_check_at(
                session_date, cal_today[0]["close"])
            def record_csv(res):
                """`on`: the gate's record, written by the gate BEFORE it touches
                the panel; a failure stops the session with the panel unwritten."""
                try:
                    ng.append_csv(state / ng.CSV_NAME, res, run=f"{stamp}-{mode}",
                                  session_date=session_date, written_utc=deps.utcnow())
                except Exception as e:
                    raise SessionError(f"stale-NAV gate ({res.mode}): recording failed: "
                                       f"{type(e).__name__}: {e}; not deciding without its "
                                       f"record, and the panel was not written") from e

            record["nav_gate"], gate_res = _nav_gate(deps, asof, p["universe"], refresh_exit,
                                                     final, record_csv)
            if gate_res is not None:
                # The gate's own record (release-check 2026-10-13). In report mode
                # nothing that trades depends on it, so its failure -- a bad
                # nav_gate.csv (moved aside by append_csv), or anything else -- is
                # recorded as UNMEASURED and the session goes on, as the book
                # json promises. Under `on` the gate acts, and acting without its
                # record breaks H14: the gate already wrote it, before the panel
                # (record_csv), and a failure here stops the session.
                try:
                    if deps.stale_nav == ng.REPORT:
                        ng.append_csv(state / ng.CSV_NAME, gate_res, run=f"{stamp}-{mode}",
                                      session_date=session_date, written_utc=deps.utcnow())
                    lines = gate_res.lines()
                except Exception as e:  # report: recorded below, never swallowed; on: raised
                    why = f"recording failed: {type(e).__name__}: {e}"
                    if deps.stale_nav != ng.REPORT:
                        raise SessionError(f"stale-NAV gate ({deps.stale_nav}): {why}; "
                                           f"not deciding without its record") from e
                    record["nav_gate"]["unmeasured"] = why
                    lines = [f"  NAV GATE ({deps.stale_nav}): UNMEASURED: {why}"]
                for line in lines:
                    print(line, file=out)
            else:
                g = record["nav_gate"]
                why = g["not_run"] if "not_run" in g else f"UNMEASURED: {g['unmeasured']}"
                print(f"  NAV GATE ({deps.stale_nav}): {why}", file=out)
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

        # 2b. the drawdown check (quantt/session/drawdown.py). Off unless the
        # book json sets risk.drawdown; in `report` mode it is recorded and
        # printed, and nothing below reads it.
        if deps.drawdown is not None:
            record["drawdown"], dd_lines = _drawdown(deps, state, spec, asof)
            for line in dd_lines:
                print(line, file=out)

        # 3. decide -- only on data that passed gate 5
        if data_refusals:
            decision = dec.Decision(orders=(), targets={}, notes={"*": [
                "not decided: the data gate refused"]}, plan_sha=dec.plan_sha(()))
        else:
            hold = gate_res.hold if gate_res is not None else {}
            if hold:
                targets = deps.targets(asof, pos, equity, opening,
                                       nav_hold={"asof": asof, "names": hold})
            else:
                targets = deps.targets(asof, pos, equity, opening)
            if gate_res is not None:
                # The sleeve has read the panel; was it the panel the gate
                # certified? (PanelGate.still_holds: a fetch between the two.)
                changed = deps.nav_gate.still_holds(gate_res)
                if changed:
                    raise SessionError(f"the NAV panel changed between the stale-NAV gate and "
                                       f"the sleeve's read: {changed}; not deciding on it")
            decision = dec.decide(targets, pos, equity, closes, shortable,
                                  session_date=session_date, universe=p["universe"],
                                  cid_prefix=book.cid_prefix,
                                  min_trade_usd=p["min_trade_usd"],
                                  time_in_force="day" if late else dec.TIME_IN_FORCE)
        if decision.orders and deps.execution.get("bp_shortfall") == "scale":
            scaled, factor, binding = fit_to_buying_power(
                decision.orders, pos, closes, equity, acct["buying_power"], _gross_now(acct),
                acct["maintenance_margin"], max_gross_stress=p["max_gross_stress"],
                sized_equity=equity)
            # orders_in/orders_out go into plan.json too: verify must tell a plan
            # the fit scaled to NOTHING (a missed day) from a plan with nothing to do.
            record["bp_scale"] = {"factor": factor, "binding": binding,
                                  "orders_in": len(decision.orders), "orders_out": len(scaled)}
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
            sized_equity=equity,               # decide: the plan is sized on this equity
            # Order-time: Alpaca's live buying_power. Overnight Reg T is checked on
            # the book AFTER the plan (gate.margin_limits; review 2026-10-07).
            buying_power=acct["buying_power"], current_gross=_gross_now(acct),
            maintenance_margin=acct["maintenance_margin"],
            max_gross_usd=p["max_gross_usd"],
            max_gross_stress=p["max_gross_stress"], universe=p["universe"],
            account_flags={k: acct[k] for k in ("trading_blocked", "account_blocked",
                                                "trade_suspended_by_user")})
        refusals = gt.evaluate(facts)
        if gate_res is not None and gate_res.deferred:
            # The stale-NAV gate's deferral (module docstring, DEFERRAL AND THE ORDER PATH).
            refusals.append(gt.Refusal("data", gate_res.deferral_text()))
        record["refusals"] = [{"gate": r.gate, "detail": r.detail} for r in refusals]

        plan = {"book": book.name, "spec_id": p["spec_id"], "session_date": session_date,
                "asof": asof, "equity": equity, "opening_session": opening,
                **decision.to_dict(), "refusals": record["refusals"],
                "borrow_warnings": borrow_warnings, "mode": mode}
        if "nav_gate" in record:             # only when the book turns the gate on
            plan["nav_gate"] = record["nav_gate"]
        if "drawdown" in record:             # only when the book turns the check on
            plan["drawdown"] = record["drawdown"]
        if "bp_scale" in record:
            plan["bp_scale"] = record["bp_scale"]
        shown = refusals
        if late:
            # DECIDE phase: dry-run, arming and the clock belong to the SEND phase.
            shown = [r for r in refusals if r.gate not in ("dry_run", "arming", "clock")]
            plan.update(execution="late_market", send_window=list(win), closes=closes,
                        status="refused" if shown else "decided",
                        refusals=[{"gate": r.gate, "detail": r.detail} for r in shown])
            if not shown and decision.orders:
                plan["preflight"] = _preflight(deps, decision.orders, pos, closes, acct, p,
                                               asof, sized_equity=equity)
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
            if "preflight" in plan:
                print(preflight_line(plan["preflight"]), file=out)
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
    eq = plan.get("equity")
    if not (isinstance(eq, (int, float)) and not isinstance(eq, bool)
            and math.isfinite(eq) and eq > 0):
        # The send judges the stress cap on this number (gate.stress_breach);
        # it is never assumed.
        raise SessionError(f"{path}: the plan's sized equity {eq!r} is not a positive number")
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
    # Re-fit on the LIVE account (review 2026-10-07): a plan scaled to the limit
    # at decide would otherwise be refused by any small adverse move by 15:52.
    # Only ever shrinks opening orders: what goes stays a subset of the plan.
    closes = {k: float(v) for k, v in plan["closes"].items()}
    # The stress cap is judged on the lower of the equity the plan was SIZED on
    # and live equity, and only for a plan that adds gross (gate.stress_breach:
    # the 2026-10-09 refusal and the team lead's ruling of 2026-10-11).
    sized_equity = float(plan["equity"])
    if deps.execution.get("bp_shortfall") == "scale" and orders:
        n_in = len(orders)
        orders, kept, binding = fit_to_buying_power(
            orders, pos, closes, acct["equity"], acct["buying_power"], _gross_now(acct),
            acct["maintenance_margin"], max_gross_stress=p["max_gross_stress"],
            sized_equity=sized_equity)
        # Also written to send.json (outcome): a fit that leaves nothing to send
        # is a missed day, and verify must be able to say which limit did it.
        record["bp_scale_at_send"] = {"kept": kept, "binding": binding,
                                      "orders_in": n_in, "orders_out": len(orders)}
    approve_sha = approve or approval_for(day)
    clock_gate = c.clock()
    record["clock_at_gate"] = clock_gate["timestamp"]
    cal_today = [r for r in cal if r["date"] == session_date]
    budget_short = gt.gate_late_send_budget(clock_gate["timestamp"], win, len(orders))
    record["send_budget_s"] = gt.send_budget_s(len(orders)) if orders else 0
    refusals = [
        *gt.gate_dry_run(deps.env.get("DRY_RUN")),
        *gt.gate_arming(approve_sha, plan["plan_sha"], (state / "AUTO_ARMED").exists()),
        *gt.gate_halt(deps.halts()),
        *gt.gate_late_clock(clock_gate["timestamp"], session_date, cal_today,
                            _nyse_trading(session_date), win),
        # A set the rest of the window cannot finish is not started (release-check
        # #6): see gate.gate_late_send_budget for the budget and its provenance.
        *budget_short,
        *gt.gate_no_set_in_auction((day / "STARTED").exists(), orders_recent, orders_open,
                                   book.cid_prefix, session_date),
        *gt.gate_shortability(orders, pos, shortable, acct["shorting_enabled"]),
        *gt.gate_exposure(orders, pos, closes, acct["equity"], acct["buying_power"],
                          p["max_gross_usd"], p["max_gross_stress"],
                          sized_equity=sized_equity, current_gross=_gross_now(acct),
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
            "not_final": record.get("not_final", []),
            # verify FAILs a day refused for time (late_no_trade_reason): the book
            # should have traded and could not, unlike a halt or a dry run.
            "budget_short": "; ".join(r.detail for r in budget_short) or None,
            # verify FAILs a day the send-time fit left with nothing to send, and
            # names the limit (release-check 2026-10-11 follow-up A).
            "bp_scale_at_send": record.get("bp_scale_at_send")})
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


# The fit is solved exactly first. If float summation (about 1e-10 dollars at
# these sizes) puts that whole-share plan a hair over a limit it met to the
# cent, it is solved again this far inside every limit. One cent of notional;
# it decides nothing else (fit_to_buying_power, EXACT).
FIT_MARGIN_USD = 0.01
_FIT_TOL = 1e-7        # dollars: "on the boundary" for the solver's own tests


def _fit_line(halfplanes, d: float):
    """[lo, hi] of t such that (c_buy, c_sell) = (t, t + d) satisfies every
    half-plane a*c_buy + b*c_sell >= e, or None when no t does."""
    lo, hi = -math.inf, math.inf
    for a, b, e in halfplanes:
        k, r = a + b, e - b * d
        if abs(k) < 1e-12:
            if r > _FIT_TOL:
                return None
        elif k > 0:
            lo = max(lo, r / k)
        else:
            hi = min(hi, r / k)
    return (lo, hi) if lo <= hi + _FIT_TOL else None


def _fit_cuts(n: dict, m: float, e_bp: float, e_g: float):
    """The cheapest cut that fits, as (c_buy, c_sell): dollars of as-of notional
    NOT traded on the buy side and on the sell side; None when no cut fits.

    Each side is cut from its OPENING orders first and from its reductions only
    after those are gone: cutting a reduction instead of an opening on the same
    side moves net exposure and traded notional identically, but buys back no
    buying power and adds gross, so it is never better (fit_to_buying_power,
    EXACT). With that, every limit is a concave piecewise-linear function of
    (c_buy, c_sell), so the region that fits is a convex polygon, written here
    as half-planes a*c_buy + b*c_sell >= e:
      buying power  min(c_buy, N_ob) + m*min(c_sell, N_os) >= e_bp
      gross         g(c_buy, N_ob) + g(c_sell, N_os) >= e_g, g(c, N) = min(c, 2N - c)
    (a sum of minima is the minimum of the sums, so each is four half-planes),
    inside the box 0 <= c_side <= that side's notional. The answer is the
    point with the smallest |c_sell - c_buy| (the post-trade net closest to
    the full plan's), then the smallest c_buy + c_sell (the most traded):
    on the diagonal when it crosses the polygon, else at a vertex.
    """
    t_buy, t_sell = n["ob"] + n["rb"], n["os"] + n["rs"]
    hp = [(1.0, 0.0, 0.0), (-1.0, 0.0, -t_buy), (0.0, 1.0, 0.0), (0.0, -1.0, -t_sell),
          (1.0, 1.0, e_g), (1.0, -1.0, e_g - 2 * n["os"]), (-1.0, 1.0, e_g - 2 * n["ob"]),
          (-1.0, -1.0, e_g - 2 * n["ob"] - 2 * n["os"])]
    if e_bp > 0:
        hp += [(1.0, m, e_bp), (1.0, 0.0, e_bp - m * n["os"]), (0.0, m, e_bp - n["ob"]),
               (0.0, 0.0, e_bp - n["ob"] - m * n["os"])]
    diag = _fit_line(hp, 0.0)
    if diag is not None:
        t = max(diag[0], 0.0)
        return t, t
    pts = []
    for (a1, b1, e1), (a2, b2, e2) in itertools.combinations(hp, 2):
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-12:
            continue
        x, y = (e1 * b2 - e2 * b1) / det, (a1 * e2 - a2 * e1) / det
        if all(a * x + b * y >= e - _FIT_TOL for a, b, e in hp):
            pts.append((x, y))
    if not pts:
        return None
    near = min(abs(y - x) for x, y in pts)
    return min((p for p in pts if abs(p[1] - p[0]) <= near + _FIT_TOL),
               key=lambda p: p[0] + p[1])


def fit_to_buying_power(orders, positions: dict, closes: dict, equity: float,
                        buying_power: float, current_gross: float,
                        maintenance_margin: float, *, max_gross_stress: float | None,
                        sized_equity: float) -> tuple[tuple, float, str | None]:
    """Scale the plan so it fits Alpaca's order-time buying power, the
    overnight margin limits and the spec's stress cap (gate.buying_power_needed /
    gate.margin_limits / gate.stress_breach). Returns (orders, kept, binding
    constraint or None when nothing was scaled); `kept` is the share of the
    plan's traded notional (at the as-of closes) that the whole-share orders
    returned still trade (until 2026-10-13: the fractional plan's share).

    THE STRESS CAP (2026-10-09, 2026-10-11). Scaling reductions for neutrality
    (below) can leave more gross than the plan, so a fitted plan could break
    `gate.stress_breach` when the full plan did not. The cap is therefore one of
    the limits fitted to, read exactly as the gate reads it: against the lower
    of the equity the plan was SIZED on and `equity` (live at send), and only
    when the plan adds to the gross held now. So when equity has fallen since
    decide, a plan that adds gross is scaled down here, not refused at the gate.

    NOTHING FITS (2026-10-09 audit). If the book held now already breaks a
    limit and no scaling of the plan fixes that, the plan is returned UNSCALED,
    with the binding limit named. The gate then refuses it with its own
    sentence. Until 2026-10-09 this case raised a TypeError, and the session
    ended FAIL with a traceback instead of a refusal saying why. When only
    trading NOTHING fits (say, the book is above the stress cap and every order
    adds gross), the empty plan is returned, as the released grid did; the
    session then has nothing to send, and verify reads that as a missed day
    (verify._fit_emptied).

    WHY (team lead 2026-10-07, after the execution-desk review): refusing a plan
    that does not fit leaves yesterday's stale book; skipping names breaks
    neutrality arbitrarily.

    NEUTRALITY (review 2026-10-07): scaling only the openings is NOT neutral
    when a plan rotates a leg -- covering one short in full while opening the
    replacement short scaled ended +$20.9k net long in the review's case. So
    four factors are chosen -- opening buys, opening sells, reducing buys,
    reducing sells -- to (1) satisfy every limit, (2) keep the post-trade net
    closest to the full plan's post-trade net, (3) then keep the most traded
    notional. Reductions consume no buying power (Alpaca: they do not replenish
    it until executed, and they never use it), so they are scaled only when
    neutrality needs it. Called at DECIDE (as-of closes, evening account) and
    again at SEND on the live account, so a plan sitting on the limit at decide
    is not refused by a small adverse move by 15:52.

    EXACT (release-check 2026-10-11, the execution desk's finding; fixed
    2026-10-13). Until 2026-10-13 the four factors were searched on a 0.05 grid
    and refined on 0.01, ranked by the post-trade net's distance from the full
    plan's ROUNDED TO THE CENT, then by traded notional. A grid almost never
    lands on exact neutrality, so the ranking took whichever grid point came a
    few dollars closer, however much of the trade it cost. On the 2026-10-07
    plan with equity 0.5% lower at send, it kept 72.0% of the traded notional
    ($4.98 from the full plan's net); solved exactly, 98.8% fits at exactly the
    full plan's net, 98.7% in whole shares ($4.61 from it). It never broke a
    limit, so it cost trade, never safety (tests/test_fit.py). The same three
    objectives are now solved exactly, in closed form (`_fit_cuts`): with every
    order wholly opening or wholly reducing, each limit is linear in each
    bucket's factor, so the search is a linear program in two variables, solved
    on its boundary. The answer is rounded to whole shares as below and checked
    with the gate's own terms; only if float noise put it a hair over a limit
    is it solved again FIT_MARGIN_USD inside every limit.

    Flips are deferred (decide.FLIP_SAME_SESSION), so every order is wholly
    opening or wholly reducing; a leg-2 order is refused here rather than
    mis-sized. A name without a close is left to the gate's clean refusal, and
    so is an order that would cross zero against the positions held now or a
    second order in one name: decide never emits either, so at send they mean
    the positions moved, which the send refuses itself.

    WHOLE SHARES (release-check 2026-10-11). The fit is solved in fractions, so
    each order is then rounded to whole shares, in the direction that can only
    lower gross: an opening order DOWN, a reducing order UP (capped at its own
    quantity, so it never crosses zero). Until 2026-10-11 every order was
    floored, which covers LESS of a reducing order and leaves MORE gross than
    the fractional plan the search accepted. Both reviewers reproduced a fitted
    plan that gate 8 then refused on the very stress cap it was fitted to (about
    1 in 100 synthetic cases where the cap binds): a missed day, the 2026-10-09
    failure. Rounded this way, gross and the buying power needed are never above
    the fractional plan's, every limit here is monotone in them, and |position
    after| is never above the fractional plan's in any name (to 1e-9 of a share:
    a solution that is a whole number in exact arithmetic can land a hair under
    it in floats, and must not lose a share for that). The rounded plan is
    re-checked with the gate's own terms (`breach`); if it broke a limit anyway
    it would be returned unscaled for the gate to refuse, never sent above a
    limit.
    """
    import dataclasses
    if any(o.leg != 1 for o in orders):
        raise SessionError("fit_to_buying_power: same-session flip legs are not supported "
                           "(FLIP_SAME_SESSION is False); refusing to size them")
    names = set(positions) | {o.symbol for o in orders}
    if any(not isinstance(closes.get(s), (int, float)) or closes[s] <= 0 for s in names):
        return tuple(orders), 1.0, None
    ratio = None
    if current_gross > 0:
        if maintenance_margin <= 0:
            raise SessionError(f"maintenance_margin {maintenance_margin} with current gross "
                               f"{current_gross}: the maintenance ratio cannot be measured")
        ratio = maintenance_margin / current_gross
    traded_syms = {o.symbol for o in orders}
    held = sum(abs(q) * closes[s] for s, q in positions.items())
    m = gt.SHORT_ORDER_BP_MULTIPLIER

    def opening(o) -> bool:
        return _opening_part(o, positions.get(o.symbol, 0)) > 0

    def book(qty):
        """Post-trade positions with each order at qty[client_order_id] shares.
        Built in `gate.projected_positions`' key order, so `breach` sums gross
        in the gate's order and gets the gate's number to the last bit (a zero
        position adds +0.0, which changes no float sum)."""
        after = dict(positions)
        for o in orders:
            after[o.symbol] = after.get(o.symbol, 0) + qty[o.client_order_id] * (
                1 if o.side == "buy" else -1)
        return after

    def bp_need(qty):
        return sum(qty[o.client_order_id] * closes[o.symbol] * (m if o.side == "sell" else 1.0)
                   for o in orders if opening(o))

    def breach(after, need):
        """The first limit the post-trade book `after` breaks, or None."""
        gross = sum(abs(q) * closes[s] for s, q in after.items())
        return ("order-time buying_power" if need > buying_power else
                "overnight Reg T initial margin" if gt.REG_T_INITIAL * gross > equity else
                "overnight maintenance (measured ratio)"
                if ratio is not None and ratio * gross > equity else
                "max_gross_stress (on the lower of sized and live equity)"
                if gt.stress_breach(gross, held, max_gross_stress, sized_equity, equity) else None)

    full = {o.client_order_id: o.qty for o in orders}
    binding = breach(book(full), bp_need(full))
    if binding is None:
        return tuple(orders), 1.0, None
    crossing = [o.client_order_id for o in orders
                if 0 < _opening_part(o, positions.get(o.symbol, 0)) < o.qty]
    if crossing or len(traded_syms) != len(orders):
        return tuple(orders), 1.0, (f"{binding} (not fitted: {crossing or 'two orders in one name'} "
                                    f"against the positions held now; left for the gate)")

    def bucket(o):
        return ("o" if opening(o) else "r") + ("b" if o.side == "buy" else "s")
    by = {o.client_order_id: bucket(o) for o in orders}
    n = {b: 0.0 for b in ("ob", "os", "rb", "rs")}
    for o in orders:
        n[by[o.client_order_id]] += o.qty * closes[o.symbol]
    gross_full = sum(abs(q) * closes[s] for s, q in book(full).items())
    gross_cap = [equity / gt.REG_T_INITIAL]
    if ratio is not None:
        gross_cap.append(equity / ratio)
    if max_gross_stress is not None:
        # gate.stress_breach passes a book at or under the cap OR at or under
        # the gross held now; so the ceiling here is the larger of the two.
        gross_cap.append(max(max_gross_stress * min(sized_equity, equity), held))
    need_full = n["ob"] + m * n["os"]

    def solve(margin):
        """Whole shares per order for the best cut held `margin` dollars inside
        every limit, or None when no cut fits (docstring, EXACT, WHOLE SHARES)."""
        e_bp = need_full - (buying_power - margin)
        if e_bp > need_full and buying_power >= 0:
            e_bp = need_full      # no opening at all needs 0 <= buying_power, exactly
        cut = _fit_cuts(n, m, e_bp, gross_full - (min(gross_cap) - margin))
        if cut is None:
            return None
        c_buy, c_sell = (max(0.0, c) for c in cut)
        x = {"ob": min(c_buy, n["ob"]), "rb": min(max(c_buy - n["ob"], 0.0), n["rb"]),
             "os": min(c_sell, n["os"]), "rs": min(max(c_sell - n["os"], 0.0), n["rs"])}
        f = {b: (min(1.0, max(0.0, 1.0 - x[b] / n[b])) if n[b] > 0 else 1.0) for b in n}
        whole = {}
        for o in orders:
            k = f[by[o.client_order_id]]
            if k >= 1.0:
                whole[o.client_order_id] = o.qty
            elif by[o.client_order_id][0] == "o":      # opening: DOWN
                whole[o.client_order_id] = max(0, math.floor(o.qty * k + 1e-9))
            else:                                      # reducing: UP, never past itself
                whole[o.client_order_id] = min(o.qty, max(0, math.ceil(o.qty * k - 1e-9)))
        return whole

    # Exact first, so a plan that fits on a limit to the cent keeps every share
    # (the released fit's 500/500/500 case); the margin only if float noise put
    # that rounded plan a hair over. `breach` (the gate's own terms) decides.
    whole = solve(0.0)
    if whole is None or breach(book(whole), bp_need(whole)) is not None:
        whole = solve(FIT_MARGIN_USD)
        if whole is None:
            nothing = {o.client_order_id: 0 for o in orders}
            if breach(book(nothing), bp_need(nothing)) is None:
                # Only trading nothing fits, on a limit's edge: typically the
                # book is above the stress cap and every order adds gross, so
                # adding none is the only way to pass. The released grid
                # returned the empty plan here, and so does this.
                return (), 0.0, binding
            # Not even trading nothing fits: the book held NOW is past a limit
            # (docstring, NOTHING FITS). Unscaled, so the gate refuses it and says which.
            return tuple(orders), 1.0, f"{binding} (no scaling fits: the book held now is past it)"
        still = breach(book(whole), bp_need(whole))
        if still:
            return tuple(orders), 1.0, (f"{still} (the whole-share fit still breaks it: returned "
                                        f"unscaled for the gate to refuse)")
    out = []
    for o in orders:
        q = whole[o.client_order_id]
        if q == o.qty:
            out.append(o)
        elif q > 0:
            out.append(dataclasses.replace(o, qty=q, target=o.current + (q if o.side == "buy" else -q),
                                           reason=f"{o.reason}; scaled x{q / o.qty:.2f} to fit {binding}"))
    full_traded = sum(o.qty * closes[o.symbol] for o in orders)
    kept = sum(whole[o.client_order_id] * closes[o.symbol] for o in orders)
    return dec.transmit_sequence(out), (kept / full_traded if full_traded else 1.0), binding


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
    errors = {}
    while pending:
        polls += 1
        for cid, o in list(pending.items()):
            if deps.utcnow() >= until:              # per order: one slow pass cannot overrun
                break
            try:
                got = c.order_by_client_id(cid)
            except Exception as e:  # noqa: BLE001 -- recorded as not_final, never a FAIL of a sent day
                errors[cid] = f"{type(e).__name__}: {e}"
                rec.append_jsonl(log, {"event": "poll_error", "at": deps.utcnow(),
                                       "client_order_id": cid, "error": errors[cid]})
                continue
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
    record["poll_errors"] = errors
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
