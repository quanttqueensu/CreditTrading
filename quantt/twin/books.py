"""The three Alpaca books, read-only: where their state lives, and what each one decided for a session.

WHAT IS READ, AND HOW IT IS CHECKED (contract §4.1). Each book's own `<state>/<F>/plan.json`, and
nothing it has not already written:
  * core `cef` and C4 `c4`: `quantt.session.run.load_decided_plan`, the same call the books' own
    late-market send makes: decided, for this session, its orders still hashing to `plan_sha`;
  * `events`: `quantt.sleeves.run.load_plan`, the events send's call: all of the above and its
    sleeve plans still hashing to `record_sha`.
A plan that fails either check is one the book's own send would refuse, so the book does not
trade on Alpaca, and its twin HOLDS (below). A plan for another book in this directory is a
misconfiguration and refuses the whole twin (`TwinRefused`), never a hold.

FRESHNESS. The plan's as-of must be the NYSE session before F, by the repo's calendar; any other
as-of holds the book (the Alpaca send does not re-check it, the twin does: contract §4.1).

THE SLUGS (team lead 2026-11-25, through the coordinator: "copy all our existing logic ... for all
3 sleeves and strategies"). The core and C4 are one strategy each: slugs `cef` and `c4`, whose
targets are `targets[sym]["target"]`. The events book is eight sleeves; each is its own slug,
`events/<slug>`, with the sleeve's own post-scale whole-share targets from `plan["sleeves"]`, which
must sum to the book's `targets[sym]["target"]` on every symbol or the twin refuses naming the
symbols. An events sleeve whose `action` is not `decided` (hold, flatten) takes the targets the
plan already gives it: the plan is never re-decided here. `legacy` is the account's positions at
the twin's epoch (`run.epoch`): no plan, target zero, flattened by the first session.

WHAT A HOLD MEANS. Every slug of a book whose plan did not decide is targeted at the shares the
TWIN's ledger holds for it (resolved in `combine.slug_plans`), so it sends nothing for that book.

WHY `targets[sym]["target"]` AND NOT THE BOOK'S ORDERS (contract §4.1: "copies the Alpaca books'
share targets"). The core's orders can differ from its targets: gate 7 skips a short Alpaca will
not lend, a long-to-short flip sends only its closing leg (decide.FLIP_SAME_SESSION), a delta under
min_trade_usd is not sent, and `bp_shortfall = scale` shrinks openings to Alpaca's buying power.
The twin trades to the target in each case. Those four are labelled differences, recorded per
symbol from the plan's own `notes` (`notes` below), and the comparison counts a short IBKR lends
where Alpaca would not in the twin's favour (contract §2 line 6).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import os
from pathlib import Path

LEGACY = "legacy"
EVENTS_PREFIX = "events/"


class TwinRefused(RuntimeError):
    """The twin will not go on; the message says what was measured. Nothing was sent."""


@dataclasses.dataclass(frozen=True)
class BookSpec:
    name: str            # the Alpaca book: cef | c4 | events
    kind: str            # "session" (quantt/session) | "sleeves" (quantt/sleeves)
    state_env: str       # the env var naming its state directory (read-only to the twin)


BOOKS = (BookSpec("cef", "session", "QUANTT_TWIN_CEF_STATE"),
         BookSpec("c4", "session", "QUANTT_TWIN_C4_STATE"),
         BookSpec("events", "sleeves", "QUANTT_TWIN_EVENTS_STATE"))
BOOK_NAMES = tuple(b.name for b in BOOKS)


def slug_book(slug: str) -> str:
    """The book a ledger slug belongs to; raises on a slug this twin does not know."""
    if slug in ("cef", "c4", LEGACY):
        return slug
    if slug.startswith(EVENTS_PREFIX) and len(slug) > len(EVENTS_PREFIX):
        return "events"
    raise TwinRefused(f"ledger slug {slug!r} belongs to no book this twin trades")


@dataclasses.dataclass(frozen=True)
class SlugPlan:
    slug: str
    action: str                 # decided | hold | flatten
    why: str
    targets: dict | None        # {symbol: whole shares}; None = hold at the twin ledger's shares
    dropped: tuple = ()         # an events sleeve's blocked legs, as its plan recorded them


@dataclasses.dataclass(frozen=True)
class BookRead:
    book: str
    status: str                 # "decided" | "hold"
    why: str
    slugs: tuple                # SlugPlan, one per strategy
    plan_sha: str | None = None
    record_sha: str | None = None
    asof: str | None = None
    closes: dict = dataclasses.field(default_factory=dict)
    notes: dict = dataclasses.field(default_factory=dict)
    book_targets: dict = dataclasses.field(default_factory=dict)

    def record(self) -> dict:
        return {"book": self.book, "status": self.status, "why": self.why, "plan_sha": self.plan_sha,
                "record_sha": self.record_sha, "asof": self.asof,
                "slugs": [dataclasses.asdict(s) for s in self.slugs],
                "notes": {s: n for s, n in self.notes.items()
                          if any(not x.startswith("no trade: target equals") for x in n)}}


def book_states(env) -> dict:
    """{book: its state directory}, each required, existing, and named after its book (the
    books' own rule, quantt/session/records.STATE_DIR_NAMES and quantt/sleeves/run._setup)."""
    out = {}
    for b in BOOKS:
        v = env.get(b.state_env, "")
        if not v:
            raise TwinRefused(f"{b.state_env} is not set: it must name book {b.name}'s state directory")
        p = Path(v).expanduser()
        if not p.is_dir():
            raise TwinRefused(f"{b.state_env}={v} is not an existing directory")
        if p.name != b.name:
            raise TwinRefused(f"{b.state_env}={v}: book {b.name}'s state directory is named {b.name!r}")
        out[b.name] = p
    return out


def _whole_targets(targets: dict, where: str) -> dict:
    out = {}
    for sym, t in targets.items():
        q = t.get("target") if isinstance(t, dict) else None
        if type(q) is not int:
            raise TwinRefused(f"{where}: target for {sym} is {q!r}, not a whole number of shares")
        if q:
            out[sym] = q
    return out


def _closes(plan: dict, where: str) -> dict:
    out = {}
    stale = plan.get("stale_closes") or {}
    for sym, v in stale.items():
        out[sym] = v["price"] if isinstance(v, dict) else v
    out.update(plan.get("closes") or {})
    for sym, p in out.items():
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
            raise TwinRefused(f"{where}: close for {sym} is {p!r}")
    return {s: float(p) for s, p in out.items()}


def hold(book: str, why: str) -> BookRead:
    return BookRead(book=book, status="hold", why=why, slugs=())


def read_session_book(name: str, state: Path, F: dt.date, asof: dt.date) -> BookRead:
    """Core or C4: its saved plan for F, or a hold saying why there is none to copy."""
    from quantt.session.run import SessionError, load_decided_plan
    day = state / F.isoformat()
    path = day / "plan.json"
    if not path.exists():
        return hold(name, f"no plan.json for {F}: the book decided nothing to send")
    raw = json.loads(path.read_text())
    if raw.get("book") != name:
        raise TwinRefused(f"{path} is book {raw.get('book')!r}'s, not {name!r}'s")
    try:
        plan, _orders = load_decided_plan(day, F)
    except SessionError as e:
        return hold(name, f"not a sendable plan: {e}")
    if plan.get("asof") != asof.isoformat():
        return hold(name, f"the plan's as-of {plan.get('asof')} is not the session before {F} ({asof})")
    t = _whole_targets(plan["targets"], str(path))
    return BookRead(book=name, status="decided", why="", plan_sha=plan["plan_sha"], asof=plan["asof"],
                    slugs=(SlugPlan(name, "decided", "", t),), closes=_closes(plan, str(path)),
                    notes=dict(plan.get("notes") or {}), book_targets=t)


def read_events_book(state: Path, F: dt.date, asof: dt.date) -> BookRead:
    """The events book: its saved plan for F, sleeve by sleeve, or a hold saying why."""
    from quantt.session.run import SessionError
    from quantt.sleeves.run import Refused, load_plan
    day = state / F.isoformat()
    path = day / "plan.json"
    if not path.exists():
        return hold("events", f"no plan.json for {F}: the book decided nothing to send")
    raw = json.loads(path.read_text())
    if raw.get("book") != "events":
        raise TwinRefused(f"{path} is book {raw.get('book')!r}'s, not 'events''s")
    try:
        plan, _orders = load_plan(day, F, "events")
    except (SessionError, Refused) as e:
        return hold("events", f"not a sendable plan: {e}")
    if plan.get("asof") != asof.isoformat():
        return hold("events", f"the plan's as-of {plan.get('asof')} is not the session before {F} ({asof})")
    book_t = _whole_targets(plan["targets"], str(path))
    slugs, total = [], {}
    for s in plan["sleeves"]:
        tg = s.get("targets")
        if not isinstance(tg, dict) or any(type(q) is not int for q in tg.values()):
            raise TwinRefused(f"{path}: sleeve {s.get('slug')!r} targets are not whole shares")
        for sym, q in tg.items():
            total[sym] = total.get(sym, 0) + q
        slugs.append(SlugPlan(EVENTS_PREFIX + s["slug"], s["action"], s.get("why") or "",
                              {k: v for k, v in sorted(tg.items()) if v}, tuple(s.get("dropped") or ())))
    bad = sorted(sym for sym in set(total) | set(book_t) if total.get(sym, 0) != book_t.get(sym, 0))
    if bad:
        raise TwinRefused(f"{path}: the sleeves' targets do not sum to the book's targets in {bad}; the "
                          "plan cannot be split between its strategies, so nothing is sent")
    return BookRead(book="events", status="decided", why="", plan_sha=plan["plan_sha"],
                    record_sha=plan["record_sha"], asof=plan["asof"], slugs=tuple(slugs),
                    closes=_closes(plan, str(path)), notes=dict(plan.get("notes") or {}), book_targets=book_t)


def read_books(states: dict, F: dt.date, asof: dt.date) -> dict:
    out = {}
    for b in BOOKS:
        if b.kind == "session":
            out[b.name] = read_session_book(b.name, states[b.name], F, asof)
        else:
            out[b.name] = read_events_book(states[b.name], F, asof)
    return out


def book_halt(name: str, state: Path) -> str | None:
    """Why book `name` is halted, or None: its repo halt (ops/HALT_<book>.md) or a `<state>/HALT`
    file (the events book's VM switch). A halted Alpaca book does not trade, so its twin holds.
    The GLOBAL halt is not read here: it stops the twin itself (run.py)."""
    from ops.halt import _parse_halt, scoped_path
    h = _parse_halt(scoped_path(name), book=name)
    if h:
        return f"{h.get('path')}: {h.get('reason')}"
    if os.path.lexists(state / "HALT"):
        return f"{state / 'HALT'} exists"
    return None


def ca_mode(name: str) -> str | None:
    """The book json's corporate_actions.mode for a session book, read by the book's own reader."""
    if name not in ("cef", "c4"):
        return None
    from quantt.session.run import BOOKS as SB, corporate_actions_for
    return corporate_actions_for(SB[name])
