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
               today's cls cutoff (a timeout derived from Alpaca's clock,
               not chosen), and a timeout is also a gate-5 refusal. Gate 5
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

OPENING SESSION. True only when Alpaca shows no positions AND no order in the
account's history has ever filled. The sleeve is told explicitly (it never
infers it from a flat book: a failed day or a manual flatten also looks flat),
and it trades to full target instead of the band edge (team lead 2026-09-28).

EXIT CODES (distinct, for launchd logs and the operator):
    0  SENT             orders transmitted and every one confirmed at Alpaca
    3  NOTHING_TO_SEND  every gate passed and the order list is empty
    4  PREVIEW          --preview: the list was printed; never sends
   10  DRY              DRY_RUN not "0" (and nothing else refused except arming)
   11  REFUSED          a gate refused; nothing sent
   20  FAIL             an error, a rejected/ambiguous submit, or a confirm miss
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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

EXIT_SENT, EXIT_NOTHING, EXIT_PREVIEW = 0, 3, 4
EXIT_DRY, EXIT_REFUSED, EXIT_FAIL = 10, 11, 20
EXIT_NAMES = {EXIT_SENT: "SENT", EXIT_NOTHING: "NOTHING_TO_SEND", EXIT_PREVIEW: "PREVIEW",
              EXIT_DRY: "DRY", EXIT_REFUSED: "REFUSED", EXIT_FAIL: "FAIL"}


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
    The timeout is not a chosen number: `run_session` passes the seconds left
    until today's cls cutoff by Alpaca's clock, because a refresh that ends
    after the cutoff cannot lead to an order today anyway. A timeout is a
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
                             incomplete=f"timed out after {timeout_s:.0f}s (the cls cutoff)")
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
                approve: str | None = None, skip_refresh: bool = False) -> int:
    """The session. Returns an EXIT_* code; records everything it measured."""
    out = deps.out
    stamp = deps.utcnow().strftime("%Y%m%dT%H%M%SZ")
    mode = "preview" if preview else "run"
    record: dict = {"book": book.name, "mode": mode, "started_utc": stamp,
                    "argv": {"preview": preview, "approve": approve,
                             "skip_refresh": skip_refresh}}
    state = day = None
    try:
        state = rec.state_dir_from_env(deps.env)    # required; nothing runs without it
        p = spec_params(spec)
        record["spec_id"] = p["spec_id"]
        c = deps.client
        clock = c.clock()
        session_date = clock["timestamp"].astimezone(gt.ET).date()
        day = rec.day_dir(state, session_date)
        cal = c.calendar(session_date - dt.timedelta(days=14), session_date)
        asof = asof_for(session_date, cal)
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
            cut = gt.cutoff_et(session_date, cal_today[0]["close"])
            left = (cut - clock["timestamp"]).total_seconds()
            if left <= 0:
                refresh_exit = f"not run: Alpaca clock is at/after the cls cutoff {cut:%H:%M} ET"
                record["refresh"] = {"not_run": refresh_exit}
            else:
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
        midnight = dt.datetime.combine(session_date - dt.timedelta(days=1), dt.time(0),
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
                                  min_trade_usd=p["min_trade_usd"])
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
            # The book holds MOC positions OVERNIGHT, where Reg T (2x) binds, not
            # the 4x intraday `buying_power` (review 2026-09-28): gate on the
            # tighter of the two.
            buying_power=min(acct["buying_power"], acct["regt_buying_power"]),
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
        if not (day / "STARTED").exists():
            rec.write_json_atomic(day / "plan.json", plan)

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
        for r in refusals:
            print(f"  REFUSED {r}", file=out)

        if preview:
            return _finish(record, day, stamp, mode, EXIT_PREVIEW, out)
        gates_hit = {r.gate for r in refusals}
        if refusals:
            code = EXIT_DRY if ("dry_run" in gates_hit and gates_hit <= {"dry_run", "arming"}) \
                else EXIT_REFUSED
            return _finish(record, day, stamp, mode, code, out)
        if not decision.orders:
            return _finish(record, day, stamp, mode, EXIT_NOTHING, out)

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
                         session_date=session_date, cutoff=cut)
        return _finish(record, day, stamp, mode, code, out)
    except Exception as e:  # recorded and surfaced, never swallowed: exit FAIL
        record["error"] = f"{type(e).__name__}: {e}"
        record["traceback"] = traceback.format_exc()
        print(f"FAIL {type(e).__name__}: {e}", file=out)
        print(traceback.format_exc(), file=sys.stderr)
        return _finish(record, day, stamp, mode, EXIT_FAIL, out, state=state)


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


def _transmit(c, orders, log: Path, record: dict, deps: Deps, out, *,
              session_date: dt.date, cutoff: dt.datetime) -> int:
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

    Before EVERY POST the Alpaca clock is read again and the batch stops if it
    is at/after `cutoff` or no longer `session_date` (ET): an order sent past
    15:50 is rejected and one sent after 19:00 is queued into the next day's
    auction [V], and a POST retry or a slow response can carry a batch across
    either line. A clock read that fails also stops the batch -- an unmeasured
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
        if t_et >= cutoff or t_et.date() != session_date:
            rec.append_jsonl(log, {"event": "cutoff", "at": now(), "clock": ts,
                                   "client_order_id": o.client_order_id,
                                   "cutoff": cutoff})
            failed = (f"Alpaca clock {t_et:%Y-%m-%d %H:%M:%S} ET is at/after the cls cutoff "
                      f"{cutoff:%H:%M} ET on {session_date} before {o.client_order_id}; "
                      f"batch stopped")
            break
        rec.append_jsonl(log, {"event": "submit", "at": now(), **o.wire()})
        try:
            resp = c.submit_order(o.symbol, o.qty, o.side, o.client_order_id)
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


def _finish(record, day, stamp, mode, code, out, state=None) -> int:
    record["exit"] = {"code": code, "name": EXIT_NAMES[code]}
    target = day if day is not None else state
    if target is not None:
        runs = target / "runs"
        runs.mkdir(exist_ok=True)
        rec.write_json_atomic(runs / f"{stamp}-{mode}.json", record)
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
                       skip_refresh=a.skip_refresh)
