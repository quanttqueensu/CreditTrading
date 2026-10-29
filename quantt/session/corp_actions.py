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
keeps those that took effect inside that name's window (below). The book json's
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

L_X is the date X's shares were last set: the ET date on which the latest
order in X that filled anything was SUBMITTED (`held_since`). It is read from
the account's own closed-order history, which run.py already reads for the
opening-session check. The submission date is on or before the fill date (a
`cls` order sent the evening before its auction, a late-market order minutes
before it), so the window can only start early, never late.

Why each bound:
  * from L_X. Paper never adjusts a count, so an action that took effect after
    X's shares were last set leaves the count on the wrong basis for good, not
    just on the day. Only a later trade in X, sized on the new basis, makes the
    count consistent again. L_X itself is inside the window: an ex-date takes
    effect at the open, and the fill that set the count came at or near that
    day's close, sized on the previous close, which was on the old basis.
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

An event blocks when its market date (`date`: the ex or effective date, or the
process date for types that have no other) OR its `process_date` falls in the
window. The market date is when the price basis changes; the process date is
when a broker that does process actions changes the count. Checking both can
only refuse more.

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

WHAT CLEARS A HALT. Nothing automatic. While the gate refuses, nothing trades,
so L_X stays before the event and the refusal repeats every session. It clears
when X's shares are set again after the event (a trade in X dated after the
event's dates, which only a person can send while the gate refuses, CLAUDE.md
order-path rule 1), or when the team lead sets the mode to `report` for the
sessions that should go. There is no per-event acknowledgement. Its shape would
need a ruling, and `report` already says "send anyway, recorded".

BE CONSERVATIVE: EVERY PARTY BLOCKS. A held or targeted name blocks in any role
the event gives it. That includes the ACQUIRER in a stock merger, whose share
count does not change: its price can jump on the deal's terms, and its NAV
absorbs the target's. It also includes a cash merger's acquirer, a spin-off's
new symbol and a name change's new symbol. The cost of a false halt is one
missed day and a person's look. The cost of a false pass is an order sized on
the wrong basis, which cannot be taken back.

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

# The query is padded by this many calendar days on each side of the union of
# the names' windows, and the events are then filtered on their own dates
# (`blocking_events`). WHY: what the API's start/end filter is not documented;
# results are "sorted by their process_date" [V: reference]. In every
# non-dividend example in the reference the process date EQUALS the market date
# (ex or effective) [V: reference examples, fetched 2026-10-28], so a pad of zero
# would do on those. The widest gap Alpaca documents for any type is a cash
# dividend's, ex 2023-05-04 to process 2023-05-19 (15 days); 31 is that doubled,
# rounded up. A MARGIN, not a measurement: an action whose process date is more
# than 31 days from its market date is not covered [U].
QUERY_PAD_DAYS = 31


def held_since(closed_orders, held) -> dict:
    """{symbol: ET date of the last order in it that filled anything}, for each held symbol.

    The date is the order's `submitted_at`, which every order carries
    (AlpacaClient.ORDER_FIELDS), converted to New York. It is on or before the
    fill date, so a window starting there can only start early (module
    docstring). `filled_at` is not used: whether Alpaca sets it on an order that
    filled in part and then expired is not documented [U].

    Raises, naming it, when a held symbol has no filled order in the history (a
    count the account's own record cannot date is not assumed to be old or new),
    or when an order's filled_qty or submitted_at is unreadable."""
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
    return {s: last[s] for s in sorted(held)}


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
    """(start, end) to ask Alpaca for: the union of the windows, padded (QUERY_PAD_DAYS)."""
    pad = dt.timedelta(days=QUERY_PAD_DAYS)
    return min(a for a, _ in win.values()) - pad, max(b for _, b in win.values()) + pad


def blocking_events(events, *, held: dict, targets, asof: dt.date,
                    session_date: dt.date) -> list[dict]:
    """Every (event, name) pair that blocks the session, oldest first.

    `events`: `AlpacaClient.corporate_actions` rows. `held`: {symbol: date its
    shares were last set} for every held symbol (`held_since`). `targets`: the
    symbols the plan wants to hold. A pair blocks when the name is held or
    targeted, in ANY role the event gives it (BE CONSERVATIVE), and the event's
    market date or its process date falls inside the name's window (THE WINDOW).
    Pure: no clock, no network."""
    win = windows(held, targets, asof, session_date)
    out = []
    for e in events:
        for sym, role in e["parties"]:
            if sym not in win:
                continue
            lo, hi = win[sym]
            hits = [f for f in ("date", "process_date") if lo <= e[f] <= hi]
            if hits:
                out.append({"symbol": sym, "role": role, "held": sym in held,
                            "id": e["id"], "type": e["type"], "date": e["date"],
                            "date_field": e["date_field"], "process_date": e["process_date"],
                            "in_window": hits, "window": [lo, hi],
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
            f"{b['process_date']}; window {b['window'][0]}..{b['window'][1]})")


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
