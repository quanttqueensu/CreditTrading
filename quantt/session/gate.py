"""The nine pre-transmit gates (docs/RUNNER.md "The gates"). Pure: facts in, refusals out.

WHY PURE
--------
Every gate here stands between an automated job and an order that cannot be
taken back (CLAUDE.md order-path rule 2: the trade phase is not idempotent and
the broker does not dedupe). A gate that reads the clock, the disk or the broker
itself can only be tested against whatever the machine happens to say today. So
`run.py` measures every fact once, records it, and hands it here in `GateFacts`;
each gate is a function of those facts alone and is tested refusal by refusal
(`tests/test_gate.py`).

`evaluate` runs ALL nine and returns every refusal, never just the first: a
shadow session must show everything that would have stopped it, and the
operator fixing one refusal should not discover the next one tomorrow.

Each refusal carries the gate's name (`Refusal.gate`, one of `GATES`) and a
sentence saying what was measured. Any refusal means nothing is sent.

TIME
----
Every wall-clock comparison is done in America/New_York, converted from
Alpaca's `/v2/clock` timestamp (RFC-3339 with an offset [V]). Alpaca's
`/v2/calendar` `open`/`close` are "HH:MM" with NO documented timezone [U]; this
module reads them as America/New_York, the exchange's zone. That is an
assumption, stated here and in the refusal text, and it errs only one way: if
the calendar were in another zone the computed cutoff would be wrong by whole
hours, and the fixed 15:45 ET ceiling still applies regardless.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

GATES = ("dry_run", "arming", "halt", "clock", "data", "no_set_in_auction",
         "shortability", "exposure", "sanity")

# Gate 4. Alpaca: "CLS orders submitted after 3:50pm but before 7:00pm ET will
# be rejected" [V, docs "orders-at-alpaca"]; 15:45 leaves five minutes (RUNNER.md).
CLS_CUTOFF_ET = dt.time(15, 45)
# Early-close days: no Alpaca page documents the cls cutoff [U]. RUNNER.md's
# own margin: the calendar's close minus ten minutes.
EARLY_CLOSE_MARGIN = dt.timedelta(minutes=10)
# The EVENING side of the window (team lead 2026-09-29: decide in the evening,
# once the day's NAVs are in, with a morning backstop). Alpaca: "CLS orders
# submitted after 3:50pm but before 7:00pm ET will be rejected. CLS orders
# submitted after 7:00pm will be queued and routed to the following day's
# closing auction" [V, docs "orders-at-alpaca"]. 19:15 leaves fifteen minutes
# after Alpaca's line, as 15:45 leaves five before 15:50. So an order for the
# auction on date S may be sent from 19:15 ET on the previous trading day
# (the as-of date) until the cutoff on S; outside that window it would be
# rejected, or -- worse -- queued into an auction nobody decided for.
# Whether paper honours the queue exactly as documented is [U] until the first
# evening send is confirmed at Alpaca.
QUEUE_OPEN_ET = dt.time(19, 15)

# Gate 8. Alpaca values a market short order at "(3% above the current ask
# price) * order quantity" for buying power [V, docs "orders-at-alpaca"]. The
# runner has no ask before the open; it applies the 3% to the as-of close, an
# ESTIMATE, recorded as such.
SHORT_ORDER_BP_MULTIPLIER = 1.03


@dataclass(frozen=True)
class Refusal:
    gate: str
    detail: str

    def __post_init__(self):
        if self.gate not in GATES:
            raise ValueError(f"unknown gate {self.gate!r}")

    def __str__(self) -> str:
        return f"[{self.gate}] {self.detail}"


@dataclass(frozen=True)
class GateFacts:
    """Everything the gates read, measured once by run.py. No field has a default
    that could stand in for a measurement."""
    # 1-2
    env_dry_run: str | None          # os.environ.get("DRY_RUN"): None when unset
    approve_sha: str | None          # --approve value, or None
    auto_armed: bool                 # <state>/AUTO_ARMED exists
    plan_sha: str
    # 3
    halts: list                      # the non-None results of ops.halt.read_halt(...)
    # 4
    clock_ts: dt.datetime            # Alpaca /v2/clock timestamp (aware)
    session_date: dt.date            # the auction the orders are for (ET)
    calendar_today: list             # Alpaca /v2/calendar rows whose date == session_date
    nyse_trading_today: bool         # ops/schedule/nyse_calendar.is_trading_day(session_date)
    # 5
    asof: dt.date
    refresh_exit: int | None         # fetch_daily exit code; None = --skip-refresh
    close_dates: dict                # symbol -> date of the close used (universe)
    nav_dates: dict                  # symbol -> date of the last finite, positive NAV <= as-of
    # 6
    started_exists: bool
    orders_recent: list              # Alpaca orders (status=all) since 00:00 ET the day before the as-of date
    orders_open: list                # Alpaca orders (status=open), any age
    cid_prefix: str
    # 7
    orders: tuple                    # decide.Order, the list that would be sent
    positions: dict                  # {symbol: signed int} from Alpaca
    shortable: dict                  # {symbol: bool} from /v2/assets today
    shorting_enabled: bool           # account.shorting_enabled
    # 8
    closes: dict                     # symbol -> as-of close
    equity: float
    buying_power: float              # Alpaca's live `buying_power` (the order-time check)
    current_gross: float             # long_market_value + |short_market_value| now
    maintenance_margin: float        # Alpaca's maintenance_margin now (measured ratio)
    max_gross_usd: float             # spec risk.max_gross_exposure_usd
    max_gross_stress: float | None   # spec frozen.max_gross_stress (None = key absent)
    # 9
    universe: tuple
    account_flags: dict              # trading_blocked, account_blocked, trade_suspended_by_user


# ----------------------------------------------------------------- the gates

def gate_dry_run(env_dry_run) -> list[Refusal]:
    """Gate 1. Transmit only if DRY_RUN is EXACTLY the string "0". Unset, empty,
    "1", "false", " 0", anything else is dry. A human hard halt that always
    wins (CLAUDE.md order-path rule 4), so it fails closed on every spelling
    nobody meant as "go"."""
    if env_dry_run == "0":
        return []
    shown = "unset" if env_dry_run is None else repr(env_dry_run)
    return [Refusal("dry_run", f"DRY_RUN is {shown}; only exactly '0' transmits")]


def gate_arming(approve_sha, plan_sha, auto_armed: bool) -> list[Refusal]:
    """Gate 2. `--approve <sha>` must equal the freshly recomputed plan_sha (what
    was approved is what is sent), OR `<state>/AUTO_ARMED` exists (created by
    the team lead after the first go). A WRONG --approve refuses even when
    AUTO_ARMED exists: someone approving a specific list and getting a
    different one is exactly the mistake this gate is for."""
    if approve_sha is not None:
        if approve_sha == plan_sha:
            return []
        return [Refusal("arming", f"--approve {approve_sha} does not match the recomputed "
                                  f"plan_sha {plan_sha}; the order list changed since it "
                                  f"was approved")]
    if auto_armed:
        return []
    return [Refusal("arming", "not armed: no --approve <plan_sha> and no <state>/AUTO_ARMED")]


def gate_halt(halts) -> list[Refusal]:
    """Gate 3. Any active halt (global ops/HALT.md or this book's scoped file) refuses."""
    return [Refusal("halt", f"halt active ({h.get('scope')}): {h.get('reason')} "
                            f"[{h.get('path')}]") for h in halts if h]


def cutoff_et(session_date: dt.date, calendar_close: str) -> dt.datetime:
    """The last moment (ET) a cls order may be sent on `session_date`:
    min(15:45 ET, calendar close - 10 min). The calendar close is read as ET
    (see module docstring: Alpaca does not document its zone)."""
    if not re.fullmatch(r"\d{2}:\d{2}", calendar_close or ""):
        raise ValueError(f"calendar close {calendar_close!r} is not HH:MM")
    hh, mm = map(int, calendar_close.split(":"))
    close = dt.datetime.combine(session_date, dt.time(hh, mm), tzinfo=ET)
    return min(dt.datetime.combine(session_date, CLS_CUTOFF_ET, tzinfo=ET),
               close - EARLY_CLOSE_MARGIN)


def queue_open_et(asof: dt.date) -> dt.datetime:
    """The first moment (ET) a cls order for the auction after `asof` may be
    sent: 19:15 ET on the as-of date (see QUEUE_OPEN_ET)."""
    return dt.datetime.combine(asof, QUEUE_OPEN_ET, tzinfo=ET)


# The evening part of the window ends at 01:00 ET the next calendar day (the end
# of the scheduled evening slot). Review 2026-09-29: a window running straight
# from the as-of evening to the session cutoff also covered the DAYTIME of any
# non-trading day in between (a Saturday afternoon, Thanksgiving morning), and
# what Alpaca does with a `cls` sent then is undocumented [U] -- it documents only
# "before 15:50 -> today's close, 15:50-19:00 rejected, after 19:00 -> the
# following day's close". So only the documented stretches are open.
EVENING_WINDOW_END = dt.time(1, 0)


def in_send_window(clock_ts: dt.datetime, asof: dt.date, cutoff: dt.datetime) -> bool:
    """True when an order sent at `clock_ts` joins the auction whose as-of date
    is `asof` and whose cutoff is `cutoff`: either the as-of evening
    [19:15 ET on `asof`, 01:00 ET the next day) or the session day itself
    [00:00 ET on the cutoff's date, cutoff)."""
    now = clock_ts.astimezone(ET)
    eve_end = dt.datetime.combine(asof + dt.timedelta(days=1), EVENING_WINDOW_END, tzinfo=ET)
    day_start = dt.datetime.combine(cutoff.astimezone(ET).date(), dt.time(0, 0), tzinfo=ET)
    return queue_open_et(asof) <= now < eve_end or day_start <= now < cutoff


def gate_clock(clock_ts, session_date, calendar_today, nyse_trading_today,
               asof) -> list[Refusal]:
    """Gate 4. The session date is a trading day by BOTH Alpaca's calendar and
    the repo's NYSE rules, and Alpaca's clock is inside that auction's send
    window: from 19:15 ET on the as-of date (the previous trading day) to the
    cls cutoff on the session date.

    `is_open` from /v2/clock is NOT used: it means "open right now" [V], and
    both the evening and the morning runs happen while the market is shut.
    Before 19:00 ET on the as-of date Alpaca rejects cls, and after the cutoff
    on the session date an order is rejected or queued for the auction AFTER
    this one [V] -- a real order nobody decided for that day -- so the window
    is enforced here, not left to the broker. (Until 2026-09-29 the window was
    the session date only; the team lead moved the decision to the evening.)
    """
    out = []
    if clock_ts.tzinfo is None:
        return [Refusal("clock", f"Alpaca clock timestamp {clock_ts!r} has no timezone")]
    now = clock_ts.astimezone(ET)
    qo = queue_open_et(asof)
    if now < qo:
        out.append(Refusal("clock", f"Alpaca clock {now:%Y-%m-%d %H:%M:%S} ET is before "
                                    f"{qo:%Y-%m-%d %H:%M} ET, when Alpaca starts queueing cls "
                                    f"for the {session_date} auction (as-of {asof})"))
    elif now.date() != session_date and not in_send_window(
            clock_ts, asof, dt.datetime.combine(session_date, CLS_CUTOFF_ET, tzinfo=ET)):
        out.append(Refusal("clock", f"Alpaca clock {now:%Y-%m-%d %H:%M:%S} ET is between the "
                                    f"as-of evening (ends 01:00 ET) and {session_date}; Alpaca "
                                    f"does not document where a cls sent now is routed [U]"))
    if len(calendar_today) > 1:
        out.append(Refusal("clock", f"Alpaca calendar has {len(calendar_today)} rows for "
                                    f"{session_date}"))
        return out
    alpaca_trading = len(calendar_today) == 1
    if alpaca_trading != nyse_trading_today:
        out.append(Refusal("clock", f"calendars disagree on {session_date}: Alpaca "
                                    f"trading={alpaca_trading}, nyse_calendar "
                                    f"trading={nyse_trading_today}"))
    if not alpaca_trading:
        out.append(Refusal("clock", f"{session_date} is not a trading day on Alpaca's calendar"))
        return out
    cut = cutoff_et(session_date, calendar_today[0]["close"])
    if now >= cut:
        out.append(Refusal("clock", f"Alpaca clock {now:%Y-%m-%d %H:%M:%S} ET is at/after the cls "
                                    f"cutoff {cut:%H:%M} ET (calendar close "
                                    f"{calendar_today[0]['close']}, read as ET)"))
    return out


# ------------------------------------------------ paper late-market execution

def late_window_et(session_date: dt.date, calendar_close: str,
                   minutes_before_close: tuple) -> tuple[dt.datetime, dt.datetime]:
    """[close - a, close - b) ET for the book's `execution.window_minutes_before_close`
    = (a, b). Measured from the CALENDAR close, so an early close (13:00) moves the
    window with it (12:52-12:58 for (8, 2)).

    WHY LATE MARKET ORDERS AT ALL (team lead 2026-09-29, a recorded exception to
    CLAUDE.md rule 3 for the PAPER account only): paper runs no closing auction;
    Alpaca staff say it treats `cls` as a market order at the close with random
    partial fills, and on 2026-09-29 eleven of thirteen `cls` orders expired
    unfilled. A plain market order sent in the last minutes fills at the quote
    (paper docs: matched against the NBBO; a partial fill's remainder is
    re-evaluated while marketable) -- the nearest paper gets to the close.
    """
    a, b = minutes_before_close
    if not (isinstance(a, int) and isinstance(b, int) and a > b > 0):
        raise ValueError(f"window_minutes_before_close {minutes_before_close!r} must be two "
                         f"ints a > b > 0")
    if not re.fullmatch(r"\d{2}:\d{2}", calendar_close or ""):
        raise ValueError(f"calendar close {calendar_close!r} is not HH:MM")
    hh, mm = map(int, calendar_close.split(":"))
    close = dt.datetime.combine(session_date, dt.time(hh, mm), tzinfo=ET)
    return close - dt.timedelta(minutes=a), close - dt.timedelta(minutes=b)


def gate_late_clock(clock_ts, session_date, calendar_today, nyse_trading_today,
                    window) -> list[Refusal]:
    """Gate 4 for late-market execution: the session date is a trading day by BOTH
    calendars and Alpaca's clock is inside the send window on that date. Before
    it, a market order fills at a quote too far from the close to stand for it;
    after it, too near the close to be sure it fills."""
    if clock_ts.tzinfo is None:
        return [Refusal("clock", f"Alpaca clock timestamp {clock_ts!r} has no timezone")]
    out = []
    alpaca_trading = len(calendar_today) == 1
    if alpaca_trading != nyse_trading_today:
        out.append(Refusal("clock", f"calendars disagree on {session_date}: Alpaca "
                                    f"trading={alpaca_trading}, nyse_calendar "
                                    f"trading={nyse_trading_today}"))
    now = clock_ts.astimezone(ET)
    lo, hi = window
    if not (lo <= now < hi):
        out.append(Refusal("clock", f"Alpaca clock {now:%Y-%m-%d %H:%M:%S} ET is outside the "
                                    f"late-market send window {lo:%Y-%m-%d %H:%M}-{hi:%H:%M} ET"))
    return out


# The late-send BUDGET (release-check #6, 2026-10-08). A set is not started
# unless the send window has room for all of it:
#     budget = n_orders x SEND_ALLOWANCE_PER_ORDER_S + SEND_MARGIN_S
# Provenance:
#   MEASURED_MAX_ORDER_CYCLE_S: the slowest per-order cycle the runner has
#     recorded. A cycle is one clock GET plus one POST, from one `submit`
#     event to the next in orders.jsonl. Over 33 cycles on the 4 real send
#     days (2026-09-29, 09-30, 10-01, 10-07; laptop prod orders.jsonl, read
#     2026-10-08) the slowest was 0.259 s, the median about 0.09 s, and the
#     largest batch, 13 orders, took 1.18 s.
#   SEND_ALLOWANCE_PER_ORDER_S = 2 + 1 = 3 s:
#     - 2 s is the client's own first retry backoff (alpaca.GET_BACKOFF_S[0]),
#       so each order may have its clock read retried once;
#     - 1 s is the measured worst cycle, rounded up to a whole second, about
#       four times what was seen.
#   SEND_MARGIN_S = 30 s, the client's read timeout (alpaca.TIMEOUT_S[1]), so
#     one request in the batch may stall to its timeout and the set still ends
#     inside the window.
# They are not imported from quantt.broker (gate.py stays free of broker code);
# test_late_send_budget pins them to the client's constants.
# At the live size (13 orders) the budget is 69 s. A set may start until 15:56:51
# (12:56:51 on an early close), which leaves the 15:52 send and the 15:55 retry
# untouched.
MEASURED_MAX_ORDER_CYCLE_S = 0.259
SEND_ALLOWANCE_PER_ORDER_S = 2 + math.ceil(MEASURED_MAX_ORDER_CYCLE_S)
SEND_MARGIN_S = 30


def send_budget_s(n_orders: int) -> float:
    """Seconds of send window a set of `n_orders` needs (see the constants above)."""
    return n_orders * SEND_ALLOWANCE_PER_ORDER_S + SEND_MARGIN_S


def gate_late_send_budget(clock_ts, window, n_orders: int) -> list[Refusal]:
    """Gate 4, the late-market budget: refuse to START a set that the time left in
    the send window cannot finish.

    Why: once STARTED is written, a batch that runs past the window's end stops
    there (`_transmit` re-checks the clock before every POST). That leaves a
    partial book, a FAIL, and STARTED blocking any retry that day. Refusing here,
    before STARTED and before any POST, sends nothing instead. A decide that
    hangs until 15:57 and a timer firing queued behind it reach exactly this
    point. The time left is measured on Alpaca's clock, the same reading
    `gate_late_clock` uses. A set started before the window opens is that gate's
    refusal, not this one's.
    """
    if n_orders <= 0:
        return []
    now = clock_ts.astimezone(ET)
    hi = window[1]
    left = (hi - now).total_seconds()
    need = send_budget_s(n_orders)
    if left < need:
        return [Refusal("clock", (
            f"SEND BUDGET: {left:.0f}s left in the send window (until {hi:%H:%M:%S} ET, "
            f"Alpaca clock {now:%H:%M:%S} ET) for {n_orders} order(s); the set needs "
            f"{need:.0f}s ({n_orders} x {SEND_ALLOWANCE_PER_ORDER_S}s + {SEND_MARGIN_S}s). "
            f"Starting it would end in a partial batch: nothing sent, no STARTED written"))]
    return []


def gate_data(asof, refresh_exit, close_dates, nav_dates, universe) -> list[Refusal]:
    """Gate 5. The refresh exited 0 for the required as-of date (or was skipped
    by --skip-refresh), AND every universe name has BOTH a close and a NAV dated
    exactly the as-of date. Stale data never trades.

    WHY BOTH, measured on the real panels (review 2026-09-28): the sleeve
    inner-joins price and NAV (`CEFDiscountSleeve._panel`), so a name with an
    as-of close and no as-of NAV gets a NaN z on the last row, drops out of the
    signal, and is emitted FLAT with the reason "below min weight". With PDI's
    as-of NAV row removed (panels ending 2026-09-21) PDI went from LONG
    w=+0.064 to FLAT. With `--skip-refresh` the fetcher's own close+NAV
    completeness check (exit 4) never runs, so this gate is the only thing
    between a missing NAV and an order that closes (or never opens) that
    name. The close-date check additionally stops the per-name ffill
    (landmine 6) from sizing on an older print.

    `refresh_exit` is None (skipped), an int exit code, or a string saying why
    the refresh did not complete (a timeout, or not run); anything but None or
    0 refuses.
    """
    out = []
    if refresh_exit is not None and refresh_exit != 0:
        what = (f"exited {refresh_exit}" if isinstance(refresh_exit, int)
                else f"did not complete: {refresh_exit}")
        out.append(Refusal("data", f"refresh for as-of {asof} {what}"))
    for label, dates in (("close", close_dates), ("NAV", nav_dates)):
        missing = [s for s in universe if s not in dates or dates[s] is None]
        if missing:
            out.append(Refusal("data", f"no {label} at all for {missing}"))
        stale = {s: str(dates[s]) for s in universe
                 if s not in missing and dates[s] != asof}
        if stale:
            out.append(Refusal("data", f"{label} not dated {asof} for {stale}"))
    return out


def gate_no_set_in_auction(started_exists, orders_recent, orders_open, cid_prefix,
                           session_date) -> list[Refusal]:
    """Gate 6. Refuse if a set may already be headed for today's auction:
    `<state>/<date>/STARTED` exists, or Alpaca shows any order whose
    client_order_id starts with `<prefix>-<YYYYMMDD>-`, or ANY open order.

    WHY ALL THREE. Open positions exclude unfilled MOC orders, so a second run
    sees the same flat book and sends the same orders again; both fill in the
    same auction and the book doubles (CLAUDE.md rule 2). STARTED catches a
    second local run; the Alpaca order checks catch a run from another machine
    or a lost state dir. `status=all` for the prefix check, because an order
    already filled or cancelled today still means the set went.
    """
    out = []
    if started_exists:
        out.append(Refusal("no_set_in_auction", f"STARTED exists for {session_date}"))
    pfx = f"{cid_prefix}-{session_date:%Y%m%d}-"
    ours = sorted({o.get("client_order_id") or "" for o in orders_recent
                   if (o.get("client_order_id") or "").startswith(pfx)})
    if ours:
        out.append(Refusal("no_set_in_auction", f"Alpaca already has order ids for the "
                                                f"{session_date} auction {ours}"))
    # ANY open order, not only cls (review 2026-09-28): a day/GTC order left by a
    # manual probe reserves shares (positions are read from `qty`, not
    # `qty_available`) and may fill against today's set. Each book has its own
    # account, so an open order this runner did not just send is never expected.
    any_open = sorted(f"{o.get('symbol')}:{o.get('client_order_id')}:{o.get('time_in_force')}"
                      for o in orders_open)
    if any_open:
        out.append(Refusal("no_set_in_auction", f"open order(s) at Alpaca: {any_open}"))
    return out


def gate_shortability(orders, positions, shortable, shorting_enabled) -> list[Refusal]:
    """Gate 7. Re-checks decide's per-symbol rule on the FINAL list (decide
    drops such a symbol and logs it; reaching here with one is a bug), and
    refuses if any order opens or increases a short while the account has
    shorting disabled."""
    out, running = [], dict(positions)
    for o in orders:
        cur = running.get(o.symbol, 0)
        after = cur + o.signed_qty
        running[o.symbol] = after
        if after < 0 and after < min(cur, 0):
            if shortable.get(o.symbol) is not True:
                out.append(Refusal("shortability", f"{o.client_order_id} opens/increases a "
                                                   f"short in {o.symbol}, shortable="
                                                   f"{shortable.get(o.symbol)!r}"))
            if shorting_enabled is not True:
                out.append(Refusal("shortability", f"{o.client_order_id} opens/increases a "
                                                   f"short but account shorting_enabled="
                                                   f"{shorting_enabled!r}"))
    return out


def projected_positions(orders, positions) -> dict:
    out = dict(positions)
    for o in orders:
        out[o.symbol] = out.get(o.symbol, 0) + o.signed_qty
    return {s: q for s, q in out.items() if q != 0}


def buying_power_needed(orders, positions, closes) -> float:
    """Estimated buying power the orders consume at submission, per Alpaca's
    documented rule [V, docs "orders-at-alpaca"]: open buy-long and sell-short
    orders reduce buying power (a short at 3% above the price); sell-to-close
    and buy-to-cover "do not replenish ... until they are executed", so they
    count zero here, not negative. Priced at the as-of close: an estimate."""
    need, running = 0.0, dict(positions)
    for o in orders:
        cur = running.get(o.symbol, 0)
        after = cur + o.signed_qty
        running[o.symbol] = after
        opening_long = max(0, after - max(cur, 0)) if o.side == "buy" else 0
        opening_short = max(0, min(cur, 0) - after) if o.side == "sell" else 0
        px = closes[o.symbol]
        need += opening_long * px + opening_short * px * SHORT_ORDER_BP_MULTIPLIER
    return need


REG_T_INITIAL = 0.5   # Reg T initial margin, 50% of gross [V: Alpaca margin docs;
                      # measured 2026-10-06: initial_margin = 50.0% of gross]


def margin_limits(positions_after: dict, closes: dict, equity: float, current_gross: float,
                  maintenance_margin: float) -> list[str]:
    """The OVERNIGHT check (review 2026-10-07): after the orders fill, Reg T
    initial margin (50% of projected gross) <= equity, and projected maintenance
    at the account's LIVE measured ratio (maintenance_margin / current gross,
    47.8% on 2026-10-06 [V], never a literal) <= equity. With no current gross
    the ratio cannot be measured; the initial-margin check then stands alone
    (on these names it is the stricter of the two: 50% > 47.8% measured)."""
    gross = sum(abs(q) * closes[s] for s, q in positions_after.items())
    out = []
    if REG_T_INITIAL * gross > equity:
        out.append(f"projected Reg T initial margin ${REG_T_INITIAL * gross:,.2f} "
                   f"(50% of gross ${gross:,.2f}) > equity ${equity:,.2f}")
    if current_gross > 0:
        if maintenance_margin <= 0:
            out.append(f"maintenance_margin {maintenance_margin} with current gross "
                       f"{current_gross:,.2f}: the ratio cannot be measured; not assumed")
            return out
        ratio = maintenance_margin / current_gross
        if ratio * gross > equity:
            out.append(f"projected maintenance ${ratio * gross:,.2f} (measured "
                       f"{ratio:.1%} of gross) > equity ${equity:,.2f}")
    return out


def gate_exposure(orders, positions, closes, equity, buying_power, max_gross_usd,
                  max_gross_stress, *, current_gross: float,
                  maintenance_margin: float) -> list[Refusal]:
    """Gate 8. After the orders fill as sent: gross <= risk.max_gross_exposure_usd,
    gross <= max_gross_stress x equity (when the spec sets it); the ORDER-TIME
    check -- buying power the opening orders consume <= Alpaca's live
    `buying_power`, which is what Alpaca enforces at submission [V]; and the
    OVERNIGHT check (`margin_limits`). A name with a position or an order and
    no close refuses (it cannot be valued), never counts as 0.

    WHY TWO CHECKS (review 2026-10-07). Until then the gate compared opening
    notional with min(buying_power, regt_buying_power) -- the overnight Reg T
    HEADROOM left by today's book, with no credit for what the same plan
    closes. On 2026-10-06 that refused a catch-up plan ($82.8k opening vs
    $80.8k regt) that Alpaca would have accepted ($188.5k buying_power) and that
    ended at 1.57x gross, inside every limit. The overnight limit is now checked
    on the book AFTER the plan, which is what it is about.
    """
    out = []
    proj = projected_positions(orders, positions)
    unpriced = sorted(s for s in set(proj) | {o.symbol for o in orders}
                      if not (isinstance(closes.get(s), (int, float))
                              and math.isfinite(closes[s]) and closes[s] > 0))
    if unpriced:
        return [Refusal("exposure", f"no close to value {unpriced}")]
    gross = sum(abs(q) * closes[s] for s, q in proj.items())
    if gross > max_gross_usd:
        out.append(Refusal("exposure", f"projected gross ${gross:,.2f} > spec "
                                       f"max_gross_exposure_usd ${max_gross_usd:,.2f}"))
    if max_gross_stress is not None and gross > max_gross_stress * equity:
        out.append(Refusal("exposure", f"projected gross ${gross:,.2f} > max_gross_stress "
                                       f"{max_gross_stress} x equity ${equity:,.2f}"))
    need = buying_power_needed(orders, positions, closes)
    if need > buying_power:
        out.append(Refusal("exposure", f"orders need ~${need:,.2f} of buying power "
                                       f"(est. at as-of closes) > Alpaca buying_power "
                                       f"${buying_power:,.2f}"))
    for m in margin_limits(proj, closes, equity, current_gross, maintenance_margin):
        out.append(Refusal("exposure", m))
    return out


def gate_sanity(orders, universe, positions, cid_prefix, session_date,
                account_flags) -> list[Refusal]:
    """Gate 9. Every qty a positive int, every symbol in the frozen universe, no
    symbol with opposite-side orders (the wash-trade 403, landmine 2), no
    duplicate client ids, every id this session's; no position the book does
    not trade (an account holding something this runner did not buy is not a
    state to trade on top of); the account not blocked."""
    out = []
    uni = set(universe)
    stray = sorted(s for s in positions if s not in uni)
    if stray:
        out.append(Refusal("sanity", f"account holds non-universe symbol(s) {stray}"))
    for f in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
        if account_flags.get(f) is not False:
            out.append(Refusal("sanity", f"account {f}={account_flags.get(f)!r}"))
    sides, cids = {}, set()
    pfx = f"{cid_prefix}-{session_date:%Y%m%d}-"
    for o in orders:
        if type(o.qty) is not int or o.qty <= 0:
            out.append(Refusal("sanity", f"{o.client_order_id}: qty {o.qty!r} is not a "
                                         f"positive int"))
        if o.symbol not in uni:
            out.append(Refusal("sanity", f"{o.client_order_id}: {o.symbol} not in the "
                                         f"frozen universe"))
        if o.side not in ("buy", "sell"):
            out.append(Refusal("sanity", f"{o.client_order_id}: side {o.side!r}"))
        sides.setdefault(o.symbol, set()).add(o.side)
        if o.client_order_id in cids:
            out.append(Refusal("sanity", f"duplicate client_order_id {o.client_order_id}"))
        cids.add(o.client_order_id)
        if o.client_order_id != f"{pfx}{o.symbol}-{o.leg}":
            out.append(Refusal("sanity", f"client_order_id {o.client_order_id!r} is not "
                                         f"{pfx}{o.symbol}-{o.leg}"))
    both = sorted(s for s, v in sides.items() if len(v) > 1)
    if both:
        out.append(Refusal("sanity", f"opposite-side orders in {both}"))
    return out


def evaluate(f: GateFacts) -> list[Refusal]:
    """All nine gates, in RUNNER.md order; every refusal, not the first."""
    return [
        *gate_dry_run(f.env_dry_run),
        *gate_arming(f.approve_sha, f.plan_sha, f.auto_armed),
        *gate_halt(f.halts),
        *gate_clock(f.clock_ts, f.session_date, f.calendar_today, f.nyse_trading_today,
                    f.asof),
        *gate_data(f.asof, f.refresh_exit, f.close_dates, f.nav_dates, f.universe),
        *gate_no_set_in_auction(f.started_exists, f.orders_recent, f.orders_open,
                                f.cid_prefix, f.session_date),
        *gate_shortability(f.orders, f.positions, f.shortable, f.shorting_enabled),
        *gate_exposure(f.orders, f.positions, f.closes, f.equity, f.buying_power,
                       f.max_gross_usd, f.max_gross_stress, current_gross=f.current_gross,
                       maintenance_margin=f.maintenance_margin),
        *gate_sanity(f.orders, f.universe, f.positions, f.cid_prefix, f.session_date,
                     f.account_flags),
    ]
