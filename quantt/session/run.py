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
  2. read      Alpaca clock, calendar, account, positions, closed orders, assets.
               Gate 6's order lists are read at step 4, not here.
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
  3b. corporate actions only when the book json sets `corporate_actions.mode`
               (absent = off, the behaviour above unchanged). Alpaca paper
               processes no splits or mergers, so a held name's broker count
               can sit on a different basis from its as-of close. Every
               non-dividend action naming a held or targeted name inside its
               window is found (`corp_actions.py`, THE WINDOW): `report`
               records it and sends anyway; `halt` refuses with a gate-5 `data`
               refusal naming each event, and also refuses when the feed cannot
               be read. Run again at the late-market SEND on fresh reads (team
               lead 2026-10-28). On a combined book (MULTI-SLEEVE BOOKS below)
               the targets are the netted decision's AND every sleeve's own
               (`_plan_targets`), and the held names are still the broker's.
  4. gate      all nine (`gate.evaluate`), on a clock read AFTER the slow
               steps, never the one from the start. Gate 6's order lists
               (status=all since midnight before the as-of, and open) are the
               last broker read before that clock read (`_gate6_orders`; review
               2026-10-29); a failed read refuses. Any refusal: nothing is sent.
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
          re-evaluated on fresh broker reads, and so is the corporate-action
          gate when the book sets it (step 3b): Alpaca can list an action
          effective on the session date only after the evening decide. Gate
          6's lists are read after all of those, just before the gate's clock
          read (step 4).
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

MULTI-SLEEVE BOOKS (quantt/session/combine.py; DARK, team lead 2026-10-28).
`Deps.sleeves` is None for the released book json, and every step above runs
exactly as before (proved against de6e9c5: tests/test_combine_noop.py). It is
set only when every enabled entry of the book json's `sleeves[]` carries a
`risk_budget`. Then step 3 builds each sleeve from its own spec on its own
sleeve_nav and decides the NETTED book once; the closes, NAVs, assets, gate 9
and the send read the union of the sleeves' universes; gate 5 acts per sleeve
(`gate.gate_data_by_sleeve`); the stale-NAV gate's holds go to the sleeve that
owns the name; and plan.json gains `combine`, the per-sleeve record. The
book-level limits stay the book spec's, applied to the netted orders by
`fit_to_buying_power` and gate 8.

GATE 5'S MISSING-NAV HOLD (book json `data.missing_nav`; DARK, team lead
2026-10-29). `Deps.missing_nav` is None for the released book json, and gate 5
refuses the whole day when one name has no NAV dated the as-of date, exactly as
before (proved against bd87144: tests/test_missing_nav_hold.py). Why the key:
on 2026-10-22 PDO's 10-21 NAV never landed, the CEFConnect fallback that used
to fill such a gap has refused every scripted request since 10-21, and one
fund's NAV cost all 13 the day. With "hold" (`gate.missing_nav_hold`):
  * EVENING DECIDE and every morning slot BEFORE the final check (the
    stale-NAV gate's `nav_gate.final_check_at`, close - 90 min: 14:30 ET):
    REFUSED with today's gate-5 refusals plus one line saying the decide is
    deferred. Nothing is decided or marked; the next slot re-runs the refresh,
    and a NAV that lands meanwhile is simply used. The DEFERRAL AND THE ORDER
    PATH notes above apply unchanged.
  * AT OR AFTER THE FINAL CHECK: each name whose only fault is a NAV not dated
    as-of is HELD -- current shares, no order, out of the cross-section, never
    targeted to zero, never the cause of the sleeve's `min_names` flatten --
    through the stale-NAV gate's `nav_hold` extra; the other names decide. The
    stale-NAV gate runs on that exit-4 refresh too (`_nav_gate`).
  * Still refused at any hour, as today: a missing or stale CLOSE, a name with
    no NAV at all, a refresh failure other than INCOMPLETE, and more names
    without a NAV than `gate.max_missing_nav_holds` (n - min_names: 7 of 13).
  * THE AGE LIMIT (team lead 2026-10-29, a policy): a fund may be held for at
    most data.missing_nav_max_sessions consecutive sessions. At the final check
    after that, its NAV still not dated as-of, the day is REFUSED as without
    the key, the fund and its count named. The count is re-read from the prior
    sessions' plan.json (`missing_nav_streaks`); a missing or unreadable record
    refuses rather than counts as zero.
  * SHORT OF min_names (release-check of 6d42f4f): if, with the holds and the
    sleeve's own exclusions, fewer than `min_names` names are eligible on their
    signal (the sleeve's own count, tagged on its targets), the day is REFUSED
    as without the key, not decided as a whole-book hold that marks it DONE.
`missing_nav` in plan.json and the run record says what was missing, the
action, and what was held.

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
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from quantt.session import combine as cmb
from quantt.session import corp_actions as cam
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
    averaged by a pivot. A NaN, infinite or non-positive NAV is not a NAV.

    FINITE (review of fetch_daily's NAV half, 2026-10-28): the filter was
    `notna() & > 0`, which +inf passes, so an infinite NAV dated D would have
    counted as D's NAV here (measured that day on a copy of the real panel:
    one deployed name's NAV(D) set to +inf, and the old filter let the session
    DECIDE a plan on it). It is `isfinite & > 0` now, the same test as
    fetch_daily's `has_nav` and nav_gate's `panel_rows`. No NAV in the panels is
    infinite (measured that day), so on them this is the old filter exactly
    (quantt/session/tests/test_nav_finite.py, on the real panel).
    """
    import numpy as np
    import pandas as pd
    N = pd.read_parquet(nav_path, columns=["date", "ticker", "nav"])
    N = N[N["ticker"].isin(list(universe))].copy()
    N["date"] = pd.to_datetime(N["date"]).dt.normalize()
    N = N[N["date"] <= pd.Timestamp(asof)]
    dup = N[N.duplicated(["date", "ticker"], keep=False)]
    if len(dup):
        raise SessionError(f"{nav_path}: duplicate (date, ticker) rows, e.g. "
                           f"{dup.head(3).to_dict('records')}")
    nav = pd.to_numeric(N["nav"])
    N = N[np.isfinite(nav) & (nav > 0)]
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


def require_core_panel(spec: dict) -> None:
    """Refuse a spec whose sleeve decides on another panel than this runner reads.

    WHY (C4 step 1 review, 2026-10-27). The `cef_discount` sleeve can now read a
    panel named by its spec's `panel_source` (C4_DEPLOY_PLAN_2026-10-27.md §1
    row 1), but this runner still takes the closes it sizes orders on, the NAV
    dates gate 5 checks, the pre-flight's close history and the stale-NAV gate's
    panel from the core paths `cefmod.PX_PATH` / `NAV_PATH` (`sleeve_targets`'s
    MarketState prices; `default_deps`). Run as it stands, such a spec would
    decide on one panel and size and gate on another, and nothing would say so.
    Wiring the sleeve's `panel_paths()` through the runner is plan row 6A (§2
    step 5); until it lands, the runner refuses. The check is here and not in
    the registry because research and the tests build such specs on purpose.

    The comparison is of the paths the sleeve would read against the module's
    core paths at call time, so it is a no-op for the core spec (no
    `panel_source`: the sleeve returns those very paths) and for a spec that
    names `data/cef/` explicitly.
    """
    from src.deploy.sleeves import cef_discount as cefmod
    got = cefmod.CEFDiscountSleeve(spec, 0.0).panel_paths()
    core = (cefmod.PX_PATH, cefmod.NAV_PATH)
    if got != core:
        raise SessionError(
            f"spec {spec.get('spec_id')!r} decides on panel {[str(p) for p in got]} "
            f"(panel_source), but this runner prices, gates and checks NAV dates on "
            f"{[str(p) for p in core]}. Plan row 6A (results/cef/C4_DEPLOY_PLAN_2026-10-27.md "
            f"§1 row 6A, §2 step 5) must land first; refusing to decide on one panel and "
            f"size on another")


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
    require_core_panel(spec)              # until plan row 6A: one panel for deciding and sizing
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


def _data_block(book: Book) -> dict | None:
    """The book json's `data` block, or None. Present, it must be a mapping that
    sets at least one of `stale_nav` and `missing_nav` (each key ABSENT is today's
    behaviour); a block that sets neither raises, as it always has."""
    data = json.loads(book.book_path.read_text()).get("data")
    if data is None:
        return None
    if not isinstance(data, dict) or not ({"stale_nav", "missing_nav"} & set(data)):
        raise SessionError(f"{book.book_path}: a `data` block must set stale_nav to one of "
                           f"{ng.MODES} or missing_nav to one of {gt.MISSING_NAV_MODES} (or "
                           f"the block must be deleted)")
    return data


def stale_nav_for(book: Book) -> str | None:
    """The book json's `data.stale_nav`: the stale-NAV gate's mode, or None.

    ABSENT means no gate, today's behaviour (CLAUDE.md: a new key defaults to
    current behaviour), exactly as an absent `execution` block means `cls`.
    Present, it must be one of `nav_gate.MODES`; anything else raises. Why the
    gate is a runner setting and not a frozen-spec key: `nav_gate` docstring.
    Since 2026-10-29 the `data` block may set `missing_nav` without it
    (`missing_nav_for`); a block that sets neither still raises."""
    data = _data_block(book)
    if data is None or "stale_nav" not in data:
        return None
    mode = data["stale_nav"]
    if mode not in ng.MODES:
        raise SessionError(f"{book.book_path}: data.stale_nav {mode!r} is not one of {ng.MODES}")
    return mode


def missing_nav_for(book: Book) -> str | None:
    """The book json's `data.missing_nav`: "hold", or None (DARK; team lead 2026-10-29).

    ABSENT means gate 5 as it always was: one name without a NAV dated the
    as-of date refuses the whole day (CLAUDE.md: a new key defaults to current
    behaviour; the no-op is proved against bd87144, release-20261029-1, by
    tests/test_missing_nav_hold.py). "hold" is `gate.missing_nav_hold`: from
    the final check such a name keeps its current shares and the other names
    decide. Anything else raises. A runner setting, beside `stale_nav`, for the
    same reason: it is about the live capture, which the research's panels never
    lacked, not about the strategy the frozen spec states."""
    data = _data_block(book)
    if data is None or "missing_nav" not in data:
        return None
    mode = data["missing_nav"]
    if mode not in gt.MISSING_NAV_MODES:
        raise SessionError(f"{book.book_path}: data.missing_nav {mode!r} is not one of "
                           f"{gt.MISSING_NAV_MODES}")
    return mode


def missing_nav_max_sessions_for(book: Book) -> int | None:
    """The book json's `data.missing_nav_max_sessions`: the hold's age limit, or None.

    A POLICY (team lead 2026-10-29), not a measurement: a fund may be held for
    a missing NAV for at most this many consecutive sessions; on the next one
    gate 5 refuses the day (`gate.missing_nav_hold`, THE AGE LIMIT, says why 2
    and why it is not derived). It lives beside `missing_nav` in the book json,
    never as a code literal, and is REQUIRED when `missing_nav` is set: a
    positive int, else this raises. Set without `missing_nav` it raises too: a
    limit for a hold that is off is a setting nothing reads."""
    data = _data_block(book) or {}
    on = "missing_nav" in data
    if "missing_nav_max_sessions" not in data:
        if on:
            raise SessionError(f"{book.book_path}: data.missing_nav is set but "
                               f"data.missing_nav_max_sessions is not; the hold's age limit "
                               f"has no default")
        return None
    v = data["missing_nav_max_sessions"]
    if not on:
        raise SessionError(f"{book.book_path}: data.missing_nav_max_sessions {v!r} is set "
                           f"without data.missing_nav")
    if not gt.max_sessions_ok(v):
        raise SessionError(f"{book.book_path}: data.missing_nav_max_sessions {v!r} is not a "
                           f"positive int")
    return v


def missing_nav_streaks(state: Path, session_date: dt.date, names, limit: int) -> dict:
    """{name: the consecutive sessions before `session_date` in which it had no
    NAV dated its as-of, counted up to `limit`; or a string saying why that
    cannot be counted}. Read from each prior session's `<state>/<D>/plan.json`,
    the session's own record, newest first, and never from memory: the count
    survives a restart because it is re-read at every final check.

    For each prior session D (NYSE days, `previous_trading_day`):
      * plan.json absent, not JSON, or for another session: cannot count. The
        caller refuses the day rather than read a missing record as zero
        (team lead 2026-10-29);
      * plan.json with a `missing_nav` record (the key was on): the name in its
        `missing` -> one more session without a dated NAV, look further back;
        not in it -> its NAV was dated: the count stops (it resets);
      * plan.json without one (the key was off): gate 5 then refused the day on
        any missing NAV. No `data` refusal means gate 5 passed and every name had
        a NAV dated as-of: the count stops. A `data` refusal does not record
        which names lacked one: cannot count.
    Only `limit` sessions are ever read: at `limit` the day is refused anyway.
    Read-only: unlike rec.day_dir, it never creates a directory."""
    from ops.schedule.nyse_calendar import previous_trading_day
    out = {}
    for name in sorted(names):
        n, d, why = 0, session_date, None
        while n < limit and why is None:
            d = previous_trading_day(d)
            path = Path(state) / d.isoformat() / "plan.json"
            try:
                plan = json.loads(path.read_text())
            except FileNotFoundError:
                why = f"no plan.json for the session {d}"
                break
            except (OSError, ValueError) as e:
                why = f"{path} is unreadable: {type(e).__name__}: {e}"
                break
            if not isinstance(plan, dict) or plan.get("session_date") != d.isoformat():
                why = (f"{path} is not the record of the session {d} (session_date "
                       f"{plan.get('session_date') if isinstance(plan, dict) else None!r})")
                break
            mv = plan.get("missing_nav")
            if mv is not None:
                if not isinstance(mv, dict) or not isinstance(mv.get("missing"), dict):
                    why = f"{path}: its missing_nav record has no `missing` mapping"
                elif name in mv["missing"]:
                    n += 1
                    continue
                break
            refusals = plan.get("refusals")
            if not isinstance(refusals, list):
                why = f"{path} has no refusals list"
            elif any(isinstance(r, dict) and r.get("gate") == "data" for r in refusals):
                why = (f"{path}: the key was off and gate 5 refused that session; whether "
                       f"{name}'s NAV was dated is not recorded")
            break
        out[name] = why if why is not None else n
    return out


def _short_of_min_names(targets) -> dict | None:
    """The sleeve's tag on a decide that had holds and fell short of `min_names`
    eligible names (`cef_discount.SHORT_OF_MIN_NAMES`), or None. Every target
    carries the same tag or none does; a mixture is a sleeve bug and raises."""
    from src.deploy.sleeves.cef_discount import SHORT_OF_MIN_NAMES
    tags = [t.meta.get(SHORT_OF_MIN_NAMES) for t in targets]
    if not any(tags):
        return None
    if not all(tags):
        raise SessionError("the sleeve tagged some targets short of min_names and not "
                           "others; not deciding on a mixed answer")
    return tags[0]


def min_names_of(spec: dict) -> int:
    """The frozen spec's `min_names`, for the missing-NAV hold's limit
    (`gate.max_missing_nav_holds`). Read only when the book json sets
    data.missing_nav; missing or not a positive int raises, naming it."""
    v = (spec.get("frozen") or {}).get("min_names")
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise SessionError(f"frozen spec {spec.get('spec_id')!r}: frozen.min_names {v!r} is "
                           f"not a positive int; the missing-NAV hold's limit is derived "
                           f"from it")
    return v


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


def corporate_actions_for(book: Book) -> str | None:
    """The book json's `corporate_actions.mode`: the corporate-action gate's mode, or None.

    ABSENT means no gate, today's behaviour (CLAUDE.md: a new key defaults to
    current behaviour), as an absent `execution` block means `cls`. Present, the
    block must set `mode` to one of `corp_actions.MODES`; anything else raises,
    so a typo cannot leave the book looking guarded when it is not. Why a runner
    setting and not a frozen-spec key: the strategy the research measured never
    met a paper broker that ignores splits; whether the runner trusts the
    broker's counts is how the runner runs, like `execution` and `data`."""
    block = json.loads(book.book_path.read_text()).get("corporate_actions")
    if block is None:
        return None
    if not isinstance(block, dict) or "mode" not in block:
        raise SessionError(f"{book.book_path}: a `corporate_actions` block must set mode to one "
                           f"of {cam.MODES} (or the block must be deleted)")
    mode = block["mode"]
    if mode not in cam.MODES:
        raise SessionError(f"{book.book_path}: corporate_actions.mode {mode!r} is not one of "
                           f"{cam.MODES}")
    return mode


def _corporate_actions(deps, read_closed: Callable[[], list], positions: dict, targets,
                       asof: dt.date, session_date: dt.date, *, universe, state: Path,
                       book_name: str) -> tuple[dict, str | None, list]:
    """Step 3b, the corporate-action gate (quantt/session/corp_actions.py):
    (record, the `data` refusal's sentence or None, log lines).

    `read_closed()` gives the account's closed orders: at DECIDE the list step 2
    already read, at SEND a fresh read. It is called inside the try, so a
    failure of that read is the gate's failure too.

    Any failure -- the order history, the fetch, a malformed response, a held
    name the history cannot date -- is recorded as UNMEASURED with its type, in
    both modes, and never as CLEAR. Under `report` the session goes on, like the
    drawdown check's report mode. Under `halt` it is a refusal naming the
    error, not a FAIL: refusing is the gate's own answer to "cannot see", and
    the next slot retries the read (the team lead's brief, 2026-10-28).

    The two rulings of 2026-10-29 (corp_actions.py, ACKNOWLEDGEMENTS; and
    AlpacaClient.corporate_actions, MALFORMED ROWS): `universe`, the book's
    symbols, lets the read skip and record a malformed row that cannot be ours;
    the team lead's acknowledgements are read from `<state>/ca_acks.json`
    inside the same try, so a file that cannot be read is UNMEASURED too, never
    "no acknowledgement"."""
    mode = deps.corp_actions
    try:
        acks = _read_ca_acks(state / cam.ACKS_FILE, book_name)
        res = cam.check(deps.client.corporate_actions, read_closed(), positions, targets,
                        asof, session_date, mode, universe=universe, acks=acks)
    except Exception as e:  # recorded in plan.json and printed, never swallowed (docstring)
        res = cam.unmeasured_record(mode, asof, session_date, f"{type(e).__name__}: {e}")
    refusal = cam.refusal_text(res) if mode == cam.HALT else None
    return res, refusal, cam.lines(res)


def _read_ca_acks(path: Path, book_name: str) -> dict | None:
    """The team lead's corporate-action acknowledgements (corp_actions.py,
    ACKNOWLEDGEMENTS): None when no file is there (nothing acknowledged, the
    state before the 2026-10-29 ruling), else `cam.parse_acks` of it. Anything
    at the path that cannot be read and parsed raises, a dangling link
    included (`os.path.lexists`): it is never read as empty."""
    if not os.path.lexists(path):
        return None
    return cam.parse_acks(json.loads(path.read_text()), book_name)


def _gate6_orders(c, after: dt.datetime) -> tuple[list | None, list | None, str | None]:
    """Gate 6's two Alpaca lists: (orders_recent, orders_open, None), or
    (None, None, why) when either read fails.

    WHY HERE, AND LAST (execution-trader, release-check of 35b429f, 2026-10-29).
    Gate 6's Alpaca check is the only guard against a second runner, or a lost
    state directory, doubling the book (CLAUDE.md order-path rule 2), and
    `_transmit` never reads the orders again. Until this fix both send paths
    read the lists early and judged them at the gate, so they were as old as
    everything read in between: the asset GETs, the sleeve (at decide and
    `cls`), the closed-order history and every corporate-action page (the
    late send's gap widened by PR #20). One GET that exhausts its retries takes
    about 250 s (docs/RUNNER.md "Latency at the send"), and the send-budget
    gate refuses only once the clock passes the window's end minus the set's
    budget, so a stall that finished earlier sent on lists minutes old, blind
    to an order another runner placed meanwhile.

    So each path calls this after every other broker read, immediately before
    the gate's own clock read. The clock read stays AFTER it on purpose: the
    late-clock and send-budget gates (gate 4 for `cls`) then judge a time after
    this read too, as they do the corporate-action read, so a slow read here can
    only make them see a later time. Between these lists and the first POST
    stand only that clock GET, the pure gates, STARTED and `_transmit`'s clock
    GET before the POST.

    A FAILED READ REFUSES: gate 6 is handed `unread` and refuses, naming it
    (gate.gate_no_set_in_auction). A list that cannot be read is not an empty
    one, and no earlier read stands in for it: neither path reads the lists
    anywhere else. Not a FAIL, so the next slot is free to try again, as for
    the corporate-action gate's failed read."""
    try:
        recent = c.orders(status="all", after=after)
        open_ = c.orders(status="open")
    except Exception as e:  # a gate-6 refusal naming it, never swallowed (docstring)
        return None, None, f"{type(e).__name__}: {e}"
    return recent, open_, None


def _plan_targets(targets: dict, combine: dict | None = None) -> list:
    """The symbols the session wants to hold, for the corporate-action gate:
    every name whose target is not zero in the decision (`Decision.targets`,
    or a saved plan's "targets"), and on a combined book also in ANY sleeve's
    own targets (`combine`: the `combine.decide` record, plan.json's "combine").

    WHY THE SLEEVES TOO (2026-10-29, after the combiner landed). On a combined
    book `Decision.targets` is the NETTED book: each symbol's sum over the
    sleeves that own it. Today a symbol has one owner (combine.py refuses a
    shared symbol, SHARED_SYMBOLS_ALLOWED False), so the net IS that sleeve's
    target. But if that switch is ever turned on, two sleeves at +100 and -100
    would net to 0. A name that nets to zero, held by no one, would then drop
    out of the gate, while each sleeve's plan was still sized on it. Reading
    each sleeve's targets as well keeps the gate on every name any sleeve
    wants, whatever the netting does. A held sleeve (gate 5 at the final check)
    targets its current shares, which are held names anyway. `combine` None,
    the single-sleeve book, reads the decision alone, exactly as before."""
    out = {s for s, t in targets.items() if t["target"] != 0}
    if combine is not None:
        for r in combine["sleeves"].values():
            out |= {s for s, t in r["targets"].items() if t["target"] != 0}
    return sorted(out)


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
    BEFORE it writes the panel (nav_gate.PanelGate.run, RECORD FIRST).

    A COMBINED BOOK ON AN INCOMPLETE REFRESH (combine.py; release-check of
    00ec423). There, exit 4 is not "nothing is decided": gate 5 holds the
    sleeves whose names are incomplete from the final check and the others
    DECIDE (`gate.gate_data_by_sleeve`), so skipping the gate sent those
    sleeves with no stale-NAV check while plan.json said gate 5 refused the
    day. So on a combined book the gate runs on exit 4, over every enabled
    sleeve's names, exactly as on exit 0. That is safe because the gate never
    acts on a name with no NAV dated as-of (`nav_gate.judge`: "not this
    gate's", gate 5's) and only ever rewrites a row dated as-of that exists;
    fetch_daily wrote the panel whole before it returned 4. The record says so
    (`refresh_exit`). The single-sleeve book is unchanged: any failed refresh
    there is gate 5's refusal of the day.

    THE MISSING-NAV HOLD (book json `data.missing_nav`, 2026-10-29) makes the
    single-sleeve book the same case: on exit 4 gate 5 holds the names without
    an as-of NAV from the final check and the rest DECIDE
    (`gate.missing_nav_hold`), so the gate runs on exit 4 there too, over every
    deployed name, for the same reason and with the same safety. Key absent:
    unchanged."""
    mode = deps.stale_nav
    on_incomplete = ((deps.sleeves is not None or deps.missing_nav is not None)
                     and gt.refresh_incomplete(refresh_exit))
    if refresh_exit is not None and refresh_exit != 0 and not on_incomplete:
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
        out = {"mode": mode, "unmeasured": f"{type(e).__name__}: {e}"}
        if on_incomplete:
            out["refresh_exit"] = _incomplete_note(deps)
        return out, None
    if not on_incomplete:
        return res.to_dict(), res
    return {**res.to_dict(), "refresh_exit": _incomplete_note(deps)}, res


# What a combined book's stale-NAV record says when the gate ran on exit 4 (`_nav_gate`).
INCOMPLETE_NOTE = (f"{gt.REFRESH_INCOMPLETE} (INCOMPLETE): the gate ran over every enabled "
                   f"sleeve's names; a name with no NAV dated as-of is gate 5's, which holds "
                   f"its sleeve from the final check or refuses the decide before it")
# ... and the single-sleeve book's, with data.missing_nav set.
INCOMPLETE_NOTE_HOLD = (f"{gt.REFRESH_INCOMPLETE} (INCOMPLETE): the gate ran over every "
                        f"deployed name; a name with no NAV dated as-of is gate 5's, which "
                        f"holds it from the final check (data.missing_nav) or refuses the "
                        f"decide before it")


def _incomplete_note(deps) -> str:
    return INCOMPLETE_NOTE if deps.sleeves is not None else INCOMPLETE_NOTE_HOLD


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
    # The multi-sleeve combiner (combine.py; dark): the book's enabled sleeves as
    # `combine.load_sleeves` read them, or None = the single-spec book above,
    # today's behaviour, which never reads this field.
    sleeves: tuple | None = None
    # Gate 5's missing-NAV hold (dark; `missing_nav_for`): None = gate 5 refuses
    # the day on one missing as-of NAV, today's behaviour; "hold" =
    # `gate.missing_nav_hold`. Single-sleeve book only (`run_session` raises
    # with a combined book, which holds per sleeve).
    missing_nav: str | None = None
    # ... and its age limit (`missing_nav_max_sessions_for`); required with it.
    missing_nav_max_sessions: int | None = None
    # The corporate-action gate (step 3b): its mode from the book json (None =
    # off, today's behaviour; `corporate_actions_for`). The read itself is
    # `client.corporate_actions`.
    corp_actions: str | None = None


def _sleeve_target_fn(sleeve_spec: dict):
    """A combined sleeve's target callable: `sleeve_targets` on its own spec at
    its own spec's capital (the single-sleeve rule), with the sleeve_nav the
    combiner sizes it on in the equity argument (the sleeve's extras[sleeve_nav])."""
    cap = float(sleeve_spec["capital_usd"])
    return lambda asof, h, nav, op, **kw: sleeve_targets(sleeve_spec, cap, asof, h, nav, op, **kw)


def default_deps(book: Book, spec: dict, env) -> Deps:
    require_core_panel(spec)              # before any client is built (plan row 6A)
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
        # None for the released book json (combine.load_sleeves, OFF BY DEFAULT).
        sleeves=cmb.load_sleeves(book.book_path, book.spec_path, REPO, _sleeve_target_fn),
        # None for the released book json (missing_nav_for; dark, 2026-10-29).
        missing_nav=missing_nav_for(book),
        missing_nav_max_sessions=missing_nav_max_sessions_for(book),
        corp_actions=corporate_actions_for(book),
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
        if deps.sleeves is not None:     # combined book: everything below covers the union
            p = cmb.book_params(p, deps.sleeves)
        if deps.missing_nav is not None and deps.sleeves is not None:
            raise SessionError(f"data.missing_nav={deps.missing_nav!r} is built for the "
                               f"single-sleeve book; a combined book holds a whole sleeve "
                               f"from the final check (gate.gate_data_by_sleeve). Delete the "
                               f"key or the risk_budgets")
        if deps.missing_nav is not None and not gt.max_sessions_ok(deps.missing_nav_max_sessions):
            raise SessionError(f"data.missing_nav={deps.missing_nav!r} needs "
                               f"data.missing_nav_max_sessions, a positive int; got "
                               f"{deps.missing_nav_max_sessions!r}")
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
        data_held, data_final, missing_held, min_names, held_before = {}, None, {}, None, None
        short_refusal = None      # the missing-NAV hold short of min_names (below)
        if deps.sleeves is None and deps.missing_nav is None:
            data_refusals = gt.gate_data(asof, refresh_exit, close_dates, nav_dates, p["universe"])
        elif deps.sleeves is None:
            # Gate 5's missing-NAV hold (gate.missing_nav_hold; book json
            # data.missing_nav). Before the final check -- every evening slot and
            # the morning slots before close - 90 min, on the same clock as the
            # stale-NAV gate's -- a name without an as-of NAV DEFERS the decide,
            # as today it refuses it; from the final check it is HELD and the
            # rest decide.
            final_at = (ng.final_check_at(session_date, cal_today[0]["close"])
                        if len(cal_today) == 1 else None)
            data_final = final_at is not None and clock["timestamp"] >= final_at
            min_names = min_names_of(spec)
            # The age limit's count, read only at the final check, where a hold
            # can be granted: each name with a NAV older than as-of, from the
            # prior sessions' plan.json (missing_nav_streaks).
            # (`nav_late`, never `late`: that name is the late-market flag here)
            nav_late = sorted(s for s in p["universe"]
                              if nav_dates.get(s) is not None and nav_dates[s] != asof)
            held_before = (missing_nav_streaks(state, session_date, nav_late,
                                               deps.missing_nav_max_sessions)
                           if data_final and nav_late else None)
            mv = gt.missing_nav_hold(asof, refresh_exit, close_dates, nav_dates,
                                     p["universe"], data_final, min_names,
                                     deps.missing_nav_max_sessions, held_before)
            data_refusals, missing_held = mv["refusals"], mv["held"]
            record["missing_nav"] = {
                "mode": deps.missing_nav, "asof": asof, "final_check": data_final,
                "final_check_at": final_at, "n_universe": len(p["universe"]),
                "min_names": min_names, "max_held": mv["max_held"],
                "max_sessions": deps.missing_nav_max_sessions, "held_before": held_before,
                "action": mv["action"], "why": mv["why"], "missing": mv["missing"],
                "held": sorted(missing_held)}
            print(f"  MISSING NAV ({deps.missing_nav}) as-of {asof}"
                  f"{', final check' if data_final else ''}: {mv['action'].upper()}: "
                  f"{mv['why']}", file=out)
        else:
            # Gate 5 per sleeve (gate.gate_data_by_sleeve): from the final check
            # (the stale-NAV gate's, on the same clock) a sleeve whose own names
            # fail is held and the rest decide; before it the book is refused.
            data_final = len(cal_today) == 1 and clock["timestamp"] >= ng.final_check_at(
                session_date, cal_today[0]["close"])
            data_refusals, data_held = gt.gate_data_by_sleeve(
                asof, refresh_exit, close_dates, nav_dates, cmb.universes(deps.sleeves),
                data_final)

        # 2. read
        acct = c.account()
        pos = c.positions().qty
        # From midnight before the as-of date: an evening run's set (sent on the
        # as-of date, possibly a Friday for a Monday auction) must be in view.
        # Gate 6's own lists (status=all after it, and open) are NOT read here:
        # they are the last broker read before the gate's clock read, at step 4
        # (`_gate6_orders`). The closed-order history is read here because the
        # decide needs it (is_opening_session) and step 3b dates held names on it.
        midnight = dt.datetime.combine(asof - dt.timedelta(days=1), dt.time(0),
                                       tzinfo=gt.ET)
        closed = c.orders(status="closed")
        opening = is_opening_session(pos, closed)
        assets = {s: c.asset(s) for s in p["universe"]}
        shortable = {s: a["shortable"] for s, a in assets.items()}
        record.update(
            account={k: v for k, v in acct.items() if k != "raw"},
            positions=pos, opening_session=opening,
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
            if missing_held:
                # Gate 5's missing-NAV holds reach the sleeve through the stale-NAV
                # gate's extra, `nav_hold` (cef_discount._nav_hold): same contract,
                # current shares, out of the cross-section, never the flatten. The
                # two never name one fund: the stale-NAV gate judges only a NAV
                # dated as-of (nav_gate.judge), and these have none.
                both = sorted(set(hold) & set(missing_held))
                if both:
                    raise SessionError(f"{both} held both by the stale-NAV gate and for a "
                                       f"missing NAV; the two cannot both be true")
                hold = {**hold, **missing_held}
            if deps.sleeves is not None:
                # The combined book (combine.py): every enabled sleeve on its own
                # spec and sleeve_nav, the stale-NAV holds to the sleeve owning
                # each name, then ONE decide on the netted targets.
                decision, record["combine"] = cmb.decide(
                    deps.sleeves, asof=asof, positions=pos, equity=equity, closes=closes,
                    shortable=shortable, opening=opening, nav_hold=hold, held=data_held,
                    book_vol=cmb.book_vol_target(spec), session_date=session_date,
                    cid_prefix=book.cid_prefix, min_trade_usd=p["min_trade_usd"],
                    time_in_force="day" if late else dec.TIME_IN_FORCE)
            elif hold:
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
            if missing_held:
                # THE HOLD SHORT OF min_names (release-check of 6d42f4f; the
                # execution-trader's case, reproduced). With the missing-NAV holds
                # out of the cross-section, the sleeve's own exclusions (illiquid,
                # ADV unmeasured, NAV stale, no z, no panel) can leave fewer than
                # `min_names` names eligible on their signal. The sleeve then holds
                # the whole book: no order, NOTHING_TO_SEND, DONE, and the 15:00
                # slot idles on a day no name was decided. Its own rule counts
                # exactly those eligible names (`len(row)` against min_names), so
                # the runner keys on that count, which the sleeve tags on every
                # target (`cef_discount._tag_short`), not on reason text, and
                # refuses the day exactly as without the key, naming the cause.
                short = _short_of_min_names(targets)
                if short is not None:
                    short_refusal = gt.Refusal("data", (
                        f"missing-NAV hold (data.missing_nav=hold): with {sorted(missing_held)} "
                        f"held, {len(short['eligible'])} names are eligible on their signal "
                        f"{short['eligible']}, under min_names {short['min_names']}; the "
                        f"sleeve's own exclusions: "
                        f"{ {t: w for t, w in short['excluded'].items() if t not in missing_held} }"
                        f"; refused, as without the key"))
                    record["missing_nav"].update(action="refused", why=short_refusal.detail,
                                                 held=[], short_of_min_names=short)
            if deps.sleeves is None and short_refusal is not None:
                decision = dec.Decision(orders=(), targets={}, notes={"*": [
                    "not decided: the data gate refused"]}, plan_sha=dec.plan_sha(()))
            elif deps.sleeves is None:
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

        # 3b. the corporate-action gate (quantt/session/corp_actions.py). Off
        # unless the book json sets corporate_actions.mode. It runs before the
        # gate's clock read, so gate 4 judges a time after this read too. The
        # held names' dates come from the closed-order history read in step 2,
        # and the held names from the broker's positions. The targets are the
        # decision's and, on a combined book, every sleeve's (`_plan_targets`).
        ca_refusal = None
        if deps.corp_actions is not None:
            record["corporate_actions"], ca_refusal, ca_lines = _corporate_actions(
                deps, lambda: closed, pos,
                _plan_targets(decision.targets, record.get("combine")), asof, session_date,
                universe=p["universe"], state=state, book_name=book.name)
            for line in ca_lines:
                print(line, file=out)

        # 4. gate. Gate 6's lists first, as the last broker read before the
        # gate's clock read (`_gate6_orders`, review 2026-10-29): read at step 2
        # they were as old as the asset GETs, the sleeve and the corporate-action
        # pages, and a second runner's set placed meanwhile went unseen. A failed
        # read is a gate-6 refusal; nothing else stands in for it.
        orders_recent, orders_open, orders_unread = _gate6_orders(c, midnight)
        if orders_unread is None:
            record.update(orders_recent=[_order_summary(o) for o in orders_recent],
                          orders_open=[_order_summary(o) for o in orders_open])
        # Then a clock read NOW, not the one from before the refresh.
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
            orders_open=orders_open, orders_unread=orders_unread, cid_prefix=book.cid_prefix,
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
        if deps.sleeves is not None:     # gate 5 per sleeve, as decided above
            facts = replace(facts, sleeve_universes=cmb.universes(deps.sleeves),
                            data_final=data_final)
        elif deps.missing_nav is not None and short_refusal is None:   # the hold, as above
            facts = replace(facts, missing_nav=deps.missing_nav, min_names=min_names,
                            data_final=data_final,
                            missing_nav_max_sessions=deps.missing_nav_max_sessions,
                            missing_nav_held_before=held_before)
        refusals = gt.evaluate(facts)
        if gate_res is not None and gate_res.deferred:
            # The stale-NAV gate's deferral (module docstring, DEFERRAL AND THE ORDER PATH).
            refusals.append(gt.Refusal("data", gate_res.deferral_text()))
        if short_refusal is not None:
            # Gate 5 above ran as without the key (facts not replaced), so these
            # are today's refusals; this line names why the hold could not stand.
            refusals.append(short_refusal)
        if ca_refusal is not None:
            # The corporate-action gate under `halt` (corp_actions.py, WHY A `data` REFUSAL).
            refusals.append(gt.Refusal("data", ca_refusal))
        record["refusals"] = [{"gate": r.gate, "detail": r.detail} for r in refusals]

        plan = {"book": book.name, "spec_id": p["spec_id"], "session_date": session_date,
                "asof": asof, "equity": equity, "opening_session": opening,
                **decision.to_dict(), "refusals": record["refusals"],
                "borrow_warnings": borrow_warnings, "mode": mode}
        if "nav_gate" in record:             # only when the book turns the gate on
            plan["nav_gate"] = record["nav_gate"]
        if "drawdown" in record:             # only when the book turns the check on
            plan["drawdown"] = record["drawdown"]
        if "corporate_actions" in record:    # only when the book turns the gate on
            plan["corporate_actions"] = record["corporate_actions"]
        if "bp_scale" in record:
            plan["bp_scale"] = record["bp_scale"]
        if "combine" in record:              # only a combined book (combine.py)
            plan["combine"] = record["combine"]
        if "missing_nav" in record:          # only when the book sets data.missing_nav
            plan["missing_nav"] = record["missing_nav"]
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
        if "combine" in record:
            for line in cmb.lines(record["combine"]):
                print(line, file=out)
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
    if deps.sleeves is not None:     # combined book: the assets and gate 9 cover the union
        p = cmb.book_params(p, deps.sleeves)
    plan, orders = load_decided_plan(day, session_date)
    record.update(plan_sha=plan["plan_sha"], asof=plan["asof"])
    acct = c.account()
    pos = c.positions().qty
    asof = dt.date.fromisoformat(plan["asof"])
    # Gate 6's lists are read after everything else, just before the gate's
    # clock read (`_gate6_orders`), and nowhere earlier: nothing before the
    # gate needs them.
    midnight = dt.datetime.combine(asof - dt.timedelta(days=1), dt.time(0), tzinfo=gt.ET)
    assets = {s: c.asset(s) for s in p["universe"]}
    shortable = {s: a["shortable"] for s, a in assets.items()}
    record.update(account={k: v for k, v in acct.items() if k != "raw"}, positions=pos)
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
    # Step 3b again, on fresh reads (module docstring, PAPER EXECUTION): Alpaca
    # can list an action effective today only after the evening decide. Before
    # the gate's clock read, so the send budget is judged after it.
    ca_refusal, ca_lines = None, []
    if deps.corp_actions is not None:
        record["corporate_actions"], ca_refusal, ca_lines = _corporate_actions(
            deps, lambda: c.orders(status="closed"), pos,
            _plan_targets(plan["targets"], plan.get("combine")),
            asof, session_date, universe=p["universe"], state=state, book_name=book.name)
    approve_sha = approve or approval_for(day)
    # Gate 6's lists: the last broker read before the gate's clock read, after
    # the asset GETs, the closed-order history and the corporate-action pages
    # (`_gate6_orders`, review 2026-10-29). A failed read is a gate-6 refusal.
    orders_recent, orders_open, orders_unread = _gate6_orders(c, midnight)
    if orders_unread is None:
        record["orders_open"] = [_order_summary(o) for o in orders_open]
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
                                   book.cid_prefix, session_date, unread=orders_unread),
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
    if ca_refusal is not None:
        refusals.append(gt.Refusal("data", ca_refusal))
    record["refusals"] = [{"gate": r.gate, "detail": r.detail} for r in refusals]
    print(f"{book.name} SEND {session_date} (plan decided on as-of {plan['asof']}), equity "
          f"${acct['equity']:,.2f}, window {win[0]:%H:%M}-{win[1]:%H:%M} ET", file=out)
    print(order_table(orders), file=out)
    print(f"plan_sha {plan['plan_sha']}", file=out)
    for line in ca_lines:
        print(line, file=out)
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
        # `corporate_actions` is added only when the book turns the gate on, so
        # send.json is unchanged when it is off.
        extra = ({"corporate_actions": record["corporate_actions"]}
                 if "corporate_actions" in record else {})
        rec.write_json_atomic(day / "send.json", {**extra,
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


def _latest_ca_record(state: Path) -> tuple[Path, dict]:
    """The gate's most recent record that read the feed: (file, its
    `corporate_actions`). Day directories newest first; in each, send.json (the
    later read, at the late-market send) before plan.json. Raises when none has
    a `query`: then there is no window to read the feed on."""
    days = sorted((d for d in state.iterdir()
                   if d.is_dir() and len(d.name) == 10 and d.name[4] == d.name[7] == "-"),
                  key=lambda d: d.name, reverse=True)
    for d in days:
        for name in ("send.json", "plan.json"):
            f = d / name
            if f.exists():
                ca = json.loads(f.read_text()).get("corporate_actions")
                if isinstance(ca, dict) and ca.get("query"):
                    return f, ca
    raise SessionError(f"no corporate-action record with a feed read in {state}: the window "
                       f"to look the id up in is the gate's own last read, so run a session "
                       f"(it may refuse) and acknowledge after it")


def ca_ack_main(argv=None, *, client=None, now: dt.datetime | None = None) -> int:
    """`python3 -m quantt.session ca-ack --book cef --id ACTION_ID --reason "one line"`.

    Records the team lead's acknowledgement of ONE corporate action, by its
    Alpaca id, in `<state>/ca_acks.json` (corp_actions.py, ACKNOWLEDGEMENTS;
    team lead 2026-10-29). The gate then clears that id only. This is the ONLY
    writer of the file, and it is run by the team lead or on the team lead's
    explicit instruction for that id (docs/RUNBOOK.md §6.1). It sends nothing:
    its one broker call is the read-only corporate-action read (`client`, in
    tests a fake; otherwise `AlpacaClient.from_environment`, keys from
    QUANTT_ENV_FILE, never printed).

    Refuses (exit 11 REFUSED, the file untouched) unless: the id is one token
    and the reason one non-empty line; the file, if there, parses
    (`cam.parse_acks`; never read as empty) and does not already hold the id;
    the state dir holds a gate record that read the feed (`_latest_ca_record`);
    and the feed, read for that record's names over that record's window (how
    the gate read it), lists the id. An unknown id is refused, so a typo
    cannot acknowledge nothing and leave the halt on unexplained. Writes with
    `records.write_json_atomic` (temp file, fsync, rename): a reader sees the
    old file or the new one, never half of either.
    """
    ap = argparse.ArgumentParser(prog="python3 -m quantt.session ca-ack")
    ap.add_argument("--book", required=True, choices=sorted(BOOKS))
    ap.add_argument("--id", required=True, help="the Alpaca corporate-action id")
    ap.add_argument("--reason", required=True, help="the team lead's reason, one line")
    a = ap.parse_args(argv)
    book = BOOKS[a.book]
    try:
        aid, reason = a.id.strip(), a.reason.strip()
        if not aid or any(ch.isspace() for ch in aid):
            raise SessionError(f"--id {a.id!r} is not one action id")
        if not reason or "\n" in reason or "\r" in reason:
            raise SessionError("--reason must be one non-empty line")
        state = rec.state_dir_from_env(os.environ)
        path = state / cam.ACKS_FILE
        existing = []
        if os.path.lexists(path):
            raw = json.loads(path.read_text())
            known = cam.parse_acks(raw, book.name)        # raises: never read as empty
            if aid in known:
                raise SessionError(f"{aid} is already acknowledged, at "
                                   f"{known[aid]['acked_utc']}: {known[aid]['reason']}")
            existing = raw["acks"]
        src, ca = _latest_ca_record(state)
        names = sorted(ca["names"])
        qs, qe = (dt.date.fromisoformat(x) for x in ca["query"])
        universe = sorted(set(spec_params(load_spec(book.spec_path))["universe"]) | set(names))
        c = client if client is not None else _ca_ack_client(book)
        events = c.corporate_actions(names, qs, qe, universe=universe, skipped=[])
        found = [e for e in events if e["id"] == aid]
        if not found:
            raise SessionError(f"{aid} is not in the feed for {names} over {qs}..{qe} (the "
                               f"window of {src.relative_to(state)}); nothing acknowledged")
        e = found[0]
        stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        entry = {"id": aid, "reason": reason, "acked_utc": stamp.isoformat(), "book": book.name,
                 "event": {k: e[k] for k in ("type", "date", "date_field", "process_date",
                                             "parties")},
                 "feed_window": [qs, qe], "from_record": str(src.relative_to(state))}
        blocked = any(b["id"] == aid for b in ca.get("blocking", []))
    except Exception as ex:  # printed, never swallowed: nothing is written
        print(f"REFUSED: {type(ex).__name__}: {ex}")
        return EXIT_REFUSED
    try:
        rec.write_json_atomic(path, {"acks": [*existing, entry]})
    except Exception as ex:  # printed, never swallowed: the rename did not happen
        print(f"FAIL: {type(ex).__name__}: {ex}; {path} was not changed, nothing acknowledged")
        return EXIT_FAIL
    print(f"ACKNOWLEDGED {aid}: {e['type']} {e['parties']} ({e['date_field']} {e['date']}, "
          f"process_date {e['process_date']}), book {book.name}, at {entry['acked_utc']}: "
          f"{reason}")
    print(f"  {'it blocked' if blocked else 'it did not block'} in {entry['from_record']}; the "
          f"gate clears this id only, and any other action still halts. Written to {path}")
    if e["type"] not in cam.PROCESS_DATE_TYPES:
        print(f"  NOTE: {e['type']} is not one of the types dated by process_date alone "
              f"{sorted(cam.PROCESS_DATE_TYPES)}: the halt clears, but the paper share count "
              f"is not fixed (docs/RUNBOOK.md §6.1)")
    return 0


def _ca_ack_client(book: Book):
    """The read-only client `ca_ack_main` reads the feed with; a seam for tests."""
    from quantt.broker.alpaca import AlpacaClient
    return AlpacaClient.from_environment(book.name)


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
