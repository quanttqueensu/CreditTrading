"""The corporate-action gate: refuse a session whose share counts or prices a corporate action has broken.

THE DEFECT (team lead, 2026-10-28: build a HALT guard)
------------------------------------------------------
Alpaca paper processes no corporate actions: no splits, no mergers [V: two
Alpaca staff forum replies, docs/REFERENCES.md §12pc; CLAUDE.md landmine 1].
IBKR paper processes none either, and paper stays on Alpaca for at least six
months (docs/SYSTEM.md §5, 2026-10-28). The runner reads broker share counts as
they are (`run.py` step 2) and prices them at the as-of close. Nothing handled a
split or a merger until this module. Say a held CEF reverse-splits 1:4: paper
keeps the old count while the price is four times higher, so the book's dollar
exposure in that name reads four times too large, equity jumps by the same
phantom amount, and the orders sent to reach target are sized on both errors.
A forward split does the same in the other direction. A merged-away name sits
in the account at its old count, and a name that is renamed or removed may not
trade at all.

WHAT THIS IS
------------
At every DECIDE, and again at the late-market SEND on fresh reads (run.py,
step 3b), the runner asks Alpaca for every non-dividend corporate action naming
a held or targeted name (`AlpacaClient.corporate_actions`), and `blocking_events`
keeps those inside the window that name's role and match call for (THE WINDOW
and TWO WINDOWS, below). The book json's
`corporate_actions.mode` says what happens then (`MODES`; absent = no gate,
today's behaviour, `run.corporate_actions_for`):
  report   record everything in plan.json and the run record (and send.json at
           the send), print it, and send anyway. A fetch or parse failure is
           recorded as UNMEASURED, never as CLEAR.
  halt     refuse the session when anything blocks, through the runner's
           existing refusal path: a gate-5 `data` refusal (exit 11 REFUSED,
           nothing sent) naming each event. A failed or unparseable fetch also
           REFUSES, naming the error (CLAUDE.md: no silent fallbacks): a gate
           that cannot see is not a gate that saw nothing.

WHY A `data` REFUSAL, NOT A NEW GATE OR `halt`. The plan's inputs (the broker's
share counts against the as-of closes) are on two bases, which is what gate 5
exists to refuse; the stale-NAV gate's deferral is a `data` refusal for the same
reason. A `halt` refusal would read in verify as a human's deliberate choice, a
PASS (verify.DELIBERATE_GATES). This one is not: the book should have traded and
could not, so verify reads it as MISSED, a FAIL, loudly, which is what should
bring a person to it.

THE WINDOW, AND ITS ALIGNMENT
-----------------------------
Dates are ET calendar dates, both ends inclusive. For session date D (the
auction or the late-market slot the orders fill in) with as-of date A (the
previous trading day, whose close every order is priced on):

  held name X    [min(L_X, A), D]
  target only    [A, D]

L_X is the close X's shares were last SIZED on, at the latest: the NYSE
trading day BEFORE the ET date on which the latest order in X that filled
anything was submitted (`held_since`, by `ops.schedule.nyse_calendar`). It is
read from the account's own closed-order history, which run.py already reads
for the opening-session check.
Why the trading day before, not the submission date (re-review 2026-10-29). A
late-market order submitted Monday at 15:52 ET was sized on Friday's close. So
an action effective on the Saturday or Sunday between changed the basis after
the sizing close and before the fill. With the window starting at Monday, it
would fall outside [L_X, D] for good if Alpaca listed it after the send. In
both modes the sizing close is on or after the trading day before the
submission date:
  * a late-market send on D is sized on close(A), and A is the trading day
    before D;
  * a `cls` order sent the evening of A is sized on close(A), and the trading
    day before A is earlier still.
So the window can only start early, never late.

Why each bound:
  * from L_X. Paper never adjusts a count, so an action that took effect after
    X's shares were last sized leaves the count on the wrong basis for good, not
    just on the day. Only a later trade in X, sized on the new basis, makes the
    count consistent again. L_X itself is inside the window: an action effective
    on the sizing close's own date changed that close's basis.
  * through A. The plan prices every name at close(A). An action effective on A
    puts close(A) on the new basis, while the count, and a NAV row that may lag
    by a day, are on the old one. A target-only name has no count to break, but
    its close(A) and its fill are what the order is sized on, so its window
    starts at A.
  * through D. An action effective on D moves the price basis between close(A),
    on which the order was sized, and the fill on D. Calendar days between A
    and D (a weekend, a holiday) are inside, because a process date can fall on
    one.
  * not after D. An action effective after the fill is the next session's, and
    the next session's window includes it.

TWO WINDOWS (team lead, 2026-10-29). The window above is a name's LONG
window. Its SHORT window is (A, D]: after the as-of date, through the session
date. In calendar dates that is [A + 1 day, D], and it is recorded that way.
Which one an event is judged on depends on how it matches the name
(`blocking_events`):

  long   the event's market date (`date`: the ex or effective date, or the
         process date for the types that have no other) is inside the name's
         long window, and the name's role is one whose count or symbol paper
         leaves wrong: an acquiree, every split type, a stock dividend, a
         spin-off party, a reorganization's own `symbol` (the security being
         reorganized), a name change (paper may leave the position under the
         old symbol), a redemption, a worthless removal, a partial call.
  short  (a) the ACQUIRER in any of the three merger types, and the
         "allocated" leg of a reorganization, on the MARKET date only; and
         (b) any other event that matches only through its `process_date`,
         because its market date is outside the name's long window. Each blocks
         only while that date is inside (A, D].

Why the acquirer is short. Its share count does not change, so paper leaves
nothing wrong after the deal. Its price and NAV jump on the terms, which matters
to the plan sized across the jump and to no later one. The holders of a
reorganization's allocated security keep their count the same way (re-review
2026-10-29, extending the team lead's acquirer ruling; flagged to the team
lead).
Why the acquirer and the allocated leg are judged on the market date ONLY
(re-review 2026-10-29). The feed lists each real MQY merger of 2026-02-23 twice,
processed on 02-23 and on 02-24 (docs/REFERENCES.md §12pc). Market-or-process
blocked sessions 02-23 AND 02-24, two sessions against a ruling of one. Paper
never applies a process date, so the second refusal protected nothing. The
match returns at once for these roles, so the process-date-only rule (b) cannot
add that session back.
Why a process-date-only match is short. The real feed backfills: a 2016 forward
split was processed on 2025-12-17, and 18 of 3,443 rows over twelve months were
processed more than 31 days after their market date (docs/REFERENCES.md §12pc).
A long window would halt a held name for an action that changed its price basis
before the book bought it. Processed inside (A, D], it may be what a broker
that does process actions applies to the count today, so it blocks that
session, and then it clears.
"A day at most" is ONE session (team lead, 2026-10-29). An event dated on
trading day E is inside (A, D] for the session on E, whose window
(E - 1 trading day, E] holds it. It is outside the next session's window,
because that session's as-of IS E. By then the as-of close and the counts are
post-event and consistent, so there is nothing left to protect. An acquirer's
or an allocated holder's count was never touched, and a process-date-only
match's count was always consistent. The as-of side is open for the short window only. The long window
keeps A inside, because there the count IS wrong (THE WINDOW, "through A").

NO LOOKAHEAD. This is a gate, not an estimate. It reads the feed as Alpaca
serves it at run time, including actions already scheduled for dates up to D.
That is information a person deciding at the same moment would have.

WHY THE WINDOW REACHES BACK TO L_X, NOT JUST TO A. Alpaca's feed is late. Its
merger coverage is mostly effective actions: on 2026-10-13 it listed none of
seven pending CEF/BDC pairs, nor one merger three days before it closed
(docs/REFERENCES.md §12p). An action can first appear after its date. A window
of [A, D] would let it slide out of view the day after, while the paper count
stays wrong. Reaching back to L_X keeps a late-listed action in view until X
is traded again.

WHAT CLEARS A HALT.
  * Short-window matches clear by themselves after one session: from the
    session whose as-of date is the event's date (TWO WINDOWS).
  * Long-window matches do not. While the gate refuses, nothing trades, so L_X
    stays before the event and the refusal repeats every session. One clears
    when X's shares are set again after the event, or when the team lead sets
    the mode to `report` for the sessions that should go. Setting the shares
    means a trade in X dated after the event's dates. While the gate refuses,
    only a person can send one, and only through the team lead (CLAUDE.md
    order-path rule 1). docs/RUNBOOK.md, "Corporate-action halt", is the
    procedure, including the phantom P&L paper keeps.
There is no per-event acknowledgement. Its shape would need a ruling, and
`report` already says "send anyway, recorded".

BE CONSERVATIVE: EVERY PARTY BLOCKS. A held or targeted name blocks in any role
the event gives it, on the window its role and match call for (TWO WINDOWS). That
includes the ACQUIRER in all three merger types, a cash merger's included: its
count does not change, but its price can jump on the deal's terms, and its NAV
absorbs the target's. It also includes a spin-off's new symbol and a name
change's new symbol. A false halt costs missed sessions until it clears: one on
the short window, and on the long window every session until a person acts
(WHAT CLEARS A HALT). A false pass costs an order sized on the wrong basis,
which cannot be taken back.

NOT COVERED, AND WHY
  * Cash dividends, capital-gains distributions and rights distributions. None
    changes a share count. Paper credits none of them either; that is the
    distribution-adjusted P&L line's job (`dist_score.py`).
  * An action Alpaca never lists (ABSENCE IS NOT PROOF, `corporate_actions`).
  * The signal's own history. A split inside the z-score's lookback can break
    the discount series if the price and NAV panels are adjusted differently.
    That is the panels' quality, gates 5 and 1b, not a share count.

H14. Nothing here keys on a number from a document. The events, the dates and
the window are measured at run time and recorded: each name's window, the query
window, every event found and every blocking one.

Standard library only at module level (pytest.ini; the send path never imports
`scripts/`).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

REPORT, HALT = "report", "halt"
MODES = (REPORT, HALT)

CLEAR, BLOCKING, UNMEASURED = "CLEAR", "BLOCKING", "UNMEASURED"

# The three merger types: an ACQUIRER in any of them is judged on the short
# window, on its market date only (module docstring, TWO WINDOWS).
MERGER_TYPES = frozenset({"cash_merger", "stock_merger", "stock_and_cash_merger"})

# The query is padded before and after the union of the names' windows. The
# events returned are then filtered on their own dates (`blocking_events`).
# The API's start/end filter on process_date. Measured on twelve months of the
# real feed, 2026-10-29: all 3,443 rows had a process date inside the query
# window, and 13 had a market date outside it (docs/REFERENCES.md §12pc). So
# the pads must cover the gap from an event's market date to its process date.
#
#   BEFORE, 31 days. The earliest process date seen was 4 days BEFORE its
#     market date: 21 of 3,443 rows were processed early, none by more. 31 was
#     the first commit's margin (a cash dividend's documented 15-day gap,
#     doubled). It is kept because it covers the measured -4 with room.
#   AFTER, 731 days. 18 of 3,443 rows were processed more than 31 days AFTER
#     their market date: spin-offs at 40 to 47 days, stock dividends at 32,
#     and backfills of up to 3,358 days. So the first commit's 31 would have
#     missed an action already listed with a process date more than a month
#     out (corrected 2026-10-29). 731 covers every measured gap up to 668 days
#     (a 2024 spin-off processed 2026-01-12).
#     The three larger gaps, 3,113 to 3,358 days, are 2016-17 actions
#     processed in 2025-26. Whether a backfill is listed BEFORE its process
#     date is not known [U]; if one were, a gap beyond 731 days would be
#     missed. Two years ahead is also the furthest a read is known to work:
#     the 2026-10-11 read asked through 2028-12-31 (§12e). The cost is every
#     action in the market scheduled up to two years out. Measured 2026-10-29
#     for process dates 2026-10-29 -> 2028-10-29, data_quality=all: one page,
#     62 rows, none naming a deployed name, the furthest out on 2027-03-31
#     (§12pc).
QUERY_PAD_BEFORE_DAYS = 31
QUERY_PAD_AFTER_DAYS = 731


def held_since(closed_orders, held) -> dict:
    """{symbol: L_X}, for each held symbol: the NYSE trading day BEFORE the ET
    submission date of the last order in it that filled anything.

    That day's close is the latest the order can have been sized on (module
    docstring, THE WINDOW): a late-market order submitted Monday at 15:52 ET
    was sized on Friday's close, and a `cls` order sent the evening of A on
    close(A), later than the day before. So a window starting here can only
    start early, in both modes. The submission time is the order's
    `submitted_at`, which every order carries (AlpacaClient.ORDER_FIELDS),
    converted to New York. `filled_at` is not used: whether Alpaca sets it on
    an order that filled in part and then expired is not documented [U]. The
    trading day is `ops.schedule.nyse_calendar.previous_trading_day`, the
    calendar run.py's as-of date comes from.

    Raises, naming it, when a held symbol has no filled order in the history (a
    count the account's own record cannot date is not assumed to be old or new),
    or when an order's filled_qty or submitted_at is unreadable."""
    from ops.schedule.nyse_calendar import previous_trading_day
    from quantt.broker.alpaca import parse_ts
    last: dict = {}
    for o in closed_orders:
        cid = o.get("client_order_id") if isinstance(o, dict) else None
        try:
            filled = Decimal(str(o["filled_qty"]))
        except (KeyError, TypeError, InvalidOperation):
            raise ValueError(f"closed order {cid!r}: unreadable filled_qty "
                             f"{o.get('filled_qty') if isinstance(o, dict) else o!r}") from None
        if not filled > 0:
            continue
        sym = o.get("symbol")
        if not isinstance(sym, str) or not sym:
            raise ValueError(f"closed order {cid!r} filled {filled} with no symbol")
        d = parse_ts(o.get("submitted_at"), f"closed order {cid!r} submitted_at").astimezone(ET).date()
        if sym not in last or d > last[sym]:
            last[sym] = d
    missing = sorted(s for s in held if s not in last)
    if missing:
        raise ValueError(f"held {missing} but no filled order for them in the account's "
                         f"closed-order history: when their shares were last set cannot be "
                         f"dated, so the window cannot be drawn")
    return {s: previous_trading_day(last[s]) for s in sorted(held)}


def windows(held: dict, targets, asof: dt.date, session_date: dt.date) -> dict:
    """{symbol: (first, last)}: each name's window, inclusive (module docstring,
    THE WINDOW). `held` is {symbol: date its shares were last set}
    (`held_since`); `targets` is every symbol the plan wants to hold. A name in
    both takes the held window, which is never narrower."""
    if not (isinstance(asof, dt.date) and isinstance(session_date, dt.date)):
        raise ValueError(f"asof {asof!r} and session_date {session_date!r} must be dates")
    if not asof < session_date:
        raise ValueError(f"asof {asof} must be before the session date {session_date}")
    out = {}
    for s, since in held.items():
        if not isinstance(since, dt.date):
            raise ValueError(f"held {s}: the date its shares were last set is {since!r}")
        out[s] = (min(since, asof), session_date)
    for s in targets:
        out.setdefault(s, (asof, session_date))
    return dict(sorted(out.items()))


def query_window(win: dict) -> tuple[dt.date, dt.date]:
    """(start, end) to ask Alpaca for: the union of the windows, padded
    (QUERY_PAD_BEFORE_DAYS, QUERY_PAD_AFTER_DAYS)."""
    return (min(a for a, _ in win.values()) - dt.timedelta(days=QUERY_PAD_BEFORE_DAYS),
            max(b for _, b in win.values()) + dt.timedelta(days=QUERY_PAD_AFTER_DAYS))


# Which rule judged a blocking pair (module docstring, TWO WINDOWS).
LONG, SHORT_PROCESS = "long", "short: process_date only"
SHORT_ACQUIRER, SHORT_ALLOCATED = "short: merger acquirer", "short: reorganization allocated"


def _short_role(e: dict, role: str) -> str | None:
    """The short-window rule for a role whose holders keep their count, or None."""
    if role == "acquirer" and e["type"] in MERGER_TYPES:
        return SHORT_ACQUIRER
    if role == "allocated" and e["type"] == "reorganization":
        return SHORT_ALLOCATED
    return None


def _match(e: dict, role: str, long_w: tuple, short_w: tuple):
    """(rule, window, fields inside it) for one (event, name), or None. TWO WINDOWS."""
    def inside(w, fields):
        return [f for f in fields if w[0] <= e[f] <= w[1]]
    rule = _short_role(e, role)
    if rule is not None:
        # The MARKET date only, and return here either way: the process date
        # neither blocks these roles nor reaches the process-date-only rule
        # below (TWO WINDOWS, the MQY pair listed twice).
        return (rule, short_w, ["date"]) if inside(short_w, ("date",)) else None
    if inside(long_w, ("date",)):
        return LONG, long_w, inside(long_w, ("date", "process_date"))
    if inside(short_w, ("process_date",)):
        return SHORT_PROCESS, short_w, ["process_date"]
    return None


def blocking_events(events, *, held: dict, targets, asof: dt.date,
                    session_date: dt.date) -> list[dict]:
    """Every (event, name) pair that blocks the session, oldest first.

    `events`: `AlpacaClient.corporate_actions` rows. `held`: {symbol: date its
    shares were last set} for every held symbol (`held_since`). `targets`: the
    symbols the plan wants to hold. A pair blocks when the name is held or
    targeted, in ANY role the event gives it (BE CONSERVATIVE), and on the
    window that role and match call for (TWO WINDOWS):
      * a merger ACQUIRER or a reorganization's ALLOCATED leg: its market date
        only, inside (as-of, session]; its process date is never read;
      * otherwise its market date inside the name's long window (THE WINDOW);
      * otherwise its process date alone inside (as-of, session].
    Each pair records the rule, the window (as inclusive calendar dates) and
    the dates that fell inside it. Pure: no clock, no network."""
    win = windows(held, targets, asof, session_date)
    # (as-of, session], open at the as-of (TWO WINDOWS: one session). Dates are
    # whole calendar days, so this is [as-of + 1 day, session] exactly.
    short_w = (asof + dt.timedelta(days=1), session_date)
    out = []
    for e in events:
        for sym, role in e["parties"]:
            if sym not in win:
                continue
            m = _match(e, role, win[sym], short_w)
            if m is None:
                continue
            rule, (lo, hi), hits = m
            out.append({"symbol": sym, "role": role, "held": sym in held,
                        "id": e["id"], "type": e["type"], "date": e["date"],
                        "date_field": e["date_field"], "process_date": e["process_date"],
                        "rule": rule, "in_window": hits, "window": [lo, hi],
                        "parties": e["parties"]})
    return sorted(out, key=lambda b: (b["date"], b["symbol"], b["type"], b["id"]))


def check(fetch, closed_orders, positions: dict, targets, asof: dt.date,
          session_date: dt.date, mode: str) -> dict:
    """The gate's record for one session (module docstring). `fetch(symbols,
    start, end)` is `AlpacaClient.corporate_actions`. Raises on anything it
    cannot measure; run.py `_corporate_actions` turns that into UNMEASURED (and,
    under `halt`, a refusal)."""
    if mode not in MODES:
        raise ValueError(f"corporate-action mode {mode!r} is not one of {MODES}")
    held = held_since(closed_orders, [s for s, q in positions.items() if q])
    targets = sorted(set(targets))
    win = windows(held, targets, asof, session_date)
    rec = {"mode": mode, "asof": asof, "session_date": session_date,
           "names": {s: {"held_since": held.get(s), "window": list(w)} for s, w in win.items()}}
    if not win:
        return {**rec, "status": CLEAR, "query": None, "events": [], "blocking": [],
                "note": "nothing held and nothing targeted: no name to check"}
    qs, qe = query_window(win)
    events = fetch(list(win), qs, qe)
    blocking = blocking_events(events, held=held, targets=targets, asof=asof,
                               session_date=session_date)
    return {**rec, "status": BLOCKING if blocking else CLEAR, "query": [qs, qe],
            "events": events, "blocking": blocking}


def unmeasured_record(mode: str, asof, session_date, why: str) -> dict:
    """The record when `check` failed: never CLEAR (module docstring, MODES)."""
    return {"mode": mode, "asof": asof, "session_date": session_date,
            "status": UNMEASURED, "why": why}


def _event_text(b: dict) -> str:
    return (f"{b['symbol']} ({'held' if b['held'] else 'target'}) is the {b['role']} in "
            f"{b['type']} {b['id']} ({b['date_field']} {b['date']}, process_date "
            f"{b['process_date']}; {b['rule']} window {b['window'][0]}..{b['window'][1]})")


def refusal_text(rec: dict) -> str | None:
    """The `data` refusal's sentence under `halt`, or None when the session may go."""
    if rec["status"] == CLEAR:
        return None
    if rec["status"] == UNMEASURED:
        return (f"corporate-action gate (halt): UNMEASURED: {rec['why']}; a gate that "
                f"cannot see refuses (paper processes no corporate actions)")
    return ("corporate-action gate (halt): " + "; ".join(_event_text(b) for b in rec["blocking"])
            + ". Paper processes no corporate actions, so the broker's share count and the "
              "as-of close may be on different bases")


def lines(rec: dict) -> list[str]:
    """The session log's lines. Report mode says on each line that it sent anyway."""
    head = f"  CORPORATE ACTIONS ({rec['mode']})"
    tail = "; report mode: nothing refused" if rec["mode"] == REPORT else "; REFUSED"
    if rec["status"] == UNMEASURED:
        return [f"{head}: UNMEASURED: {rec['why']}{tail}"]
    if rec["status"] == CLEAR:
        n = len(rec["names"])
        q = rec.get("query")
        where = f" (asked {q[0]}..{q[1]}, {len(rec['events'])} event(s) naming them)" if q else ""
        return [f"{head}: CLEAR for {n} name(s){where}"]
    return [f"{head}: BLOCKING: {_event_text(b)}{tail}" for b in rec["blocking"]]
