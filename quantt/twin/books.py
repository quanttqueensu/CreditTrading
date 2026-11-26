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


# The plan's own words for a target it did not trade to (quantt/session/decide.py notes): a delta
# under min_trade_usd, a short gate 7 skipped, a flip whose open leg waits. Review finding 4.
EXPLAINED_NOTES = ("no trade:", "not shortable today", "flip deferred")


def target_integrity(plan: dict) -> list:
    """Symbols whose orders and targets do not tell one story, as sentences; [] when they agree.

    plan_sha covers the ORDERS only, so a target edited by hand would pass the books' own check;
    the twin trades to the targets, so it binds them to the orders (review of the build, finding 4):
      * every order starts at its symbol's `current` and ends at its `target`, except the closing
        leg of a deferred flip (ends at zero) and an opening order the buying-power fit scaled
        (`bp_scale.binding` set; same side, smaller);
      * a symbol whose target differs from its current with no order carries the plan's own
        note saying why (EXPLAINED_NOTES), or was dropped by a binding buying-power fit."""
    t = plan["targets"]
    notes = plan.get("notes") or {}
    scaled = bool((plan.get("bp_scale") or {}).get("binding"))
    bad, ordered = [], set()
    for o in plan.get("orders") or []:
        sym = o["symbol"]
        ordered.add(sym)
        if sym not in t:
            bad.append(f"{sym}: an order with no target")
            continue
        cur, tgt = t[sym]["current"], t[sym]["target"]
        if o["current"] != cur:
            bad.append(f"{sym}: the order starts at {o['current']}, the target's current is {cur}")
        elif o["target"] != tgt:
            flip = o["target"] == 0 and "flip deferred" in str(o.get("reason", "")) and cur * tgt < 0
            shrunk = scaled and (o["target"] - cur) * (tgt - cur) > 0 and abs(o["target"] - cur) < abs(tgt - cur)
            if not (flip or shrunk):
                bad.append(f"{sym}: the order ends at {o['target']}, the plan's target is {tgt}")
    for sym, v in t.items():
        if sym in ordered or v["target"] == v["current"]:
            continue
        said = [n for n in notes.get(sym, []) if str(n).startswith(EXPLAINED_NOTES)]
        cur, tgt = v["current"], v["target"]
        # A binding fit scales OPENING orders only, and may round one to nothing; it never drops a
        # reduction (quantt/session/run.py fit_to_buying_power). So only an opening symbol may lack
        # its order for that reason (re-review 5).
        opening = tgt != 0 and (cur == 0 or cur * tgt > 0) and abs(tgt) > abs(cur)
        if not said and not (scaled and opening):
            bad.append(f"{sym}: target {v['target']} differs from current {v['current']} with no order and no note")
    return bad


def _load(path: Path, name: str):
    """(raw plan, None) or (None, the hold's reason): a plan.json that is not JSON holds this
    book only (review, finding 12); another book's plan here is a misconfiguration and refuses."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, f"plan.json cannot be read ({type(e).__name__}): the book holds"
    if not isinstance(raw, dict):
        return None, "plan.json is not an object: the book holds"
    if raw.get("book") != name:
        raise TwinRefused(f"{path} is book {raw.get('book')!r}'s, not {name!r}'s")
    return raw, None


def read_session_book(name: str, state: Path, F: dt.date, asof: dt.date) -> BookRead:
    """Core or C4: its saved plan for F, or a hold saying why there is none to copy."""
    from quantt.session.run import SessionError, load_decided_plan
    day = state / F.isoformat()
    path = day / "plan.json"
    if not path.exists():
        return hold(name, f"no plan.json for {F}: the book decided nothing to send")
    raw, why = _load(path, name)
    if why:
        return hold(name, why)
    try:
        plan, _orders = load_decided_plan(day, F)
    except (SessionError, KeyError, TypeError, ValueError) as e:
        return hold(name, f"not a sendable plan: {type(e).__name__}: {e}")
    if plan.get("asof") != asof.isoformat():
        return hold(name, f"the plan's as-of {plan.get('asof')} is not the session before {F} ({asof})")
    try:
        bad = target_integrity(plan)
        t = _whole_targets(plan["targets"], str(path))
        closes = _closes(plan, str(path))
    except (KeyError, TypeError, AttributeError, TwinRefused) as e:
        return hold(name, f"the plan's targets cannot be read ({type(e).__name__}: {e})")
    if bad:
        return hold(name, "the plan's orders and targets disagree: " + "; ".join(bad[:8]))
    return BookRead(book=name, status="decided", why="", plan_sha=plan["plan_sha"], asof=plan["asof"],
                    slugs=(SlugPlan(name, "decided", "", t),), closes=closes,
                    notes=dict(plan.get("notes") or {}), book_targets=t)


def read_events_book(state: Path, F: dt.date, asof: dt.date) -> BookRead:
    """The events book: its saved plan for F, sleeve by sleeve, or a hold saying why."""
    from quantt.session.run import SessionError
    from quantt.sleeves.run import Refused, load_plan
    day = state / F.isoformat()
    path = day / "plan.json"
    if not path.exists():
        return hold("events", f"no plan.json for {F}: the book decided nothing to send")
    raw, why = _load(path, "events")
    if why:
        return hold("events", why)
    try:
        plan, _orders = load_plan(day, F, "events")
    except (SessionError, Refused, KeyError, TypeError, ValueError) as e:
        return hold("events", f"not a sendable plan: {type(e).__name__}: {e}")
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


# THE BOOKS' CLONE (re-review N1, 2026-11-25). The twin runs from its own clone, but the books run
# from theirs (/home/quantt/prod/quantt-alpaca), where a person writes ops/HALT.md and
# ops/HALT_<book>.md, and whose book files hold the settings the books actually run with. So every
# halt is read in BOTH clones, and the events minimum and the corporate-action modes are read from
# the books' clone. QUANTT_BOOKS_CLONE is required and has no default.
ENV_BOOKS_CLONE = "QUANTT_BOOKS_CLONE"
BOOKS_CLONE_FILES = ("ops/sleeves/events_sleeves.json", "ops/books/cef_discount_book.json",
                     "ops/books/c4_families_book.json")


def books_clone(env) -> Path:
    v = env.get(ENV_BOOKS_CLONE, "")
    if not v:
        raise TwinRefused(f"{ENV_BOOKS_CLONE} is not set: it must name the clone the Alpaca books run from "
                          "(their halts and settings are read there)")
    p = Path(v)
    missing = [f for f in BOOKS_CLONE_FILES if not (p / f).is_file()]
    if missing:
        raise TwinRefused(f"{ENV_BOOKS_CLONE}={v} lacks {missing}: not the books' clone")
    return p


def halts_in(root: Path, name: str) -> list:
    """Active halts in one clone: the global ops/HALT.md and the scoped ops/HALT_<name>.md."""
    from ops.halt import _parse_halt
    out = []
    for path, book in ((Path(root) / "ops" / "HALT.md", None), (Path(root) / "ops" / f"HALT_{name}.md", name)):
        h = _parse_halt(path, book=book)
        if h:
            out.append(f"{path}: {h.get('reason')}")
    return out


# Each book's OWN send unit (rule 4 at the twin; the switch branch's review, 2026-11-25). Names read
# from the installers, never written twice: install_vm.py's VM_BOOKS session job for the core and
# C4 (their late-market send runs in the session unit), install_events_vm.sh's send unit for events
# (pinned by quantt/twin/tests/test_book_arming.py against that script).
EVENTS_SEND_UNIT = "quantt-events-send.service"


def send_unit(name: str) -> str:
    if name == "events":
        return EVENTS_SEND_UNIT
    from quantt.deploy import install_vm as iv
    return next(j.service for j in iv.VM_BOOKS[name].jobs if j.job.log_stem == "session")


def book_not_armed(name: str, state: Path, unit_env, clones) -> str | None:
    """Why book `name`'s slugs must hold at the twin, or None when the book itself is armed:
    its own send unit's loaded DRY_RUN is exactly "0", its <state>/AUTO_ARMED exists, and no halt
    blocks it in either clone or in <state>/HALT. The team lead's DRY_RUN=1 on a book stops it at
    both brokers (CLAUDE.md order-path rule 4). A unit whose environment cannot be read holds the
    book, named: an unread setting is never taken as armed."""
    unit = send_unit(name)
    try:
        env = unit_env(unit)
    except Exception as e:  # noqa: BLE001 -- the book holds, named; never guessed armed
        return f"{name}: its own send unit {unit} could not be read ({type(e).__name__}: {e}); it holds"
    dry = [w for w in str(env or "").split() if w.startswith("DRY_RUN=")]
    if dry != ["DRY_RUN=0"]:
        shown = dry[0] if len(dry) == 1 else ("DRY_RUN unset" if not dry else "DRY_RUN set twice")
        return f"{name}: its own send is {shown} ({unit}; rule 4)"
    if not os.path.lexists(state / "AUTO_ARMED"):
        return f"{name}: its own {state / 'AUTO_ARMED'} is absent, so its own send is not armed"
    for root in clones:
        h = halts_in(root, name)
        if h:
            return f"{name}: halted: {h[0]}"
    if os.path.lexists(state / "HALT"):
        return f"{name}: halted: {state / 'HALT'} exists"
    return None


# THE REVERT BARRIER (the switch branch's re-review, 2026-11-25). A book that has switched to IBKR
# decides for IBKR and its plan.json carries the switch's marker; if a release WITHOUT the switch's
# `broker` key then reaches prod, the book decides at Alpaca again and sends there, and the twin must
# not trade the same plan, or the book trades at both brokers. The twin's half: when the book's state
# shows an OPEN IBKR segment but the session's plan was not decided for IBKR, the book holds, named.
# The two files, as branch ibkr-switch-build's quantt/session/switch.py writes them (read 2026-11-25;
# not imported, so a change of format there stops the twin loudly here):
#   <book state>/eod_equity_sources.json
#       {"file": "eod_equity.csv", "segments": [{"source": "alpaca_eod_history" | "ibkr_twin_ledger",
#        "label": ..., "first": "YYYY-MM-DD", "last": "YYYY-MM-DD" | null}, ...], "_note": ...}
#       oldest first; only the newest may be open (last null). Absent: the book never switched.
#   <book state>/<F>/plan.json  "broker": {"name": "ibkr", "from": "YYYY-MM-DD", "session_date":
#       "YYYY-MM-DD", "note": ..., ["capital_usd": ...]}, present only on a plan decided for IBKR.
SOURCES_FILE = "eod_equity_sources.json"
SOURCE_TWIN = "ibkr_twin_ledger"
SOURCE_ALPACA = "alpaca_eod_history"


def open_ibkr_segment(state: Path) -> str | None:
    """The `first` date of the book's OPEN IBKR segment, or None (never switched, or back on
    Alpaca). Raises TwinRefused naming the file on anything this reader was not built for."""
    p = Path(state) / SOURCES_FILE
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise TwinRefused(f"{p} cannot be read ({type(e).__name__})") from None
    segs = d.get("segments") if isinstance(d, dict) else None
    if not isinstance(segs, list) or not segs:
        raise TwinRefused(f"{p} has no segments list")
    for i, sg in enumerate(segs):
        if not isinstance(sg, dict) or sg.get("source") not in (SOURCE_TWIN, SOURCE_ALPACA):
            raise TwinRefused(f"{p}: segment {i} is not one this reader knows")
        for k in ("first", "last"):
            v = sg.get(k)
            if not (v is None and k == "last") and not (isinstance(v, str) and len(v) == 10):
                raise TwinRefused(f"{p}: segment {i} {k} is {v!r}")
        if sg.get("last") is None and i != len(segs) - 1:
            raise TwinRefused(f"{p}: segment {i} is open and is not the newest")
    last = segs[-1]
    return last["first"] if last["source"] == SOURCE_TWIN and last.get("last") is None else None


def revert_barrier(name: str, state: Path, F: dt.date) -> str | None:
    """Why the book must hold because its state says it trades at IBKR but its plan for F was
    decided at Alpaca, or None. An unreadable sources file or plan holds the book too, named."""
    try:
        since = open_ibkr_segment(state)
    except TwinRefused as e:
        return f"{name}: its P&L-source record cannot be read ({e}); it holds (revert barrier)"
    if since is None:
        return None
    path = Path(state) / F.isoformat() / "plan.json"
    if not path.exists():
        return None                      # no plan: the book holds anyway (read_session_book)
    try:
        marker = json.loads(path.read_text()).get("broker")
    except (OSError, ValueError, AttributeError) as e:
        return f"{name}: its plan cannot be read to check the IBKR marker ({type(e).__name__}); it holds"
    ok = (isinstance(marker, dict) and marker.get("name") == "ibkr"
          and marker.get("session_date") == F.isoformat())
    if not ok:
        return (f"{name}: its state shows an open IBKR segment from {since}, but its plan for {F} was not "
                f"decided for IBKR (no broker marker for {F}): a release without the switch would trade "
                "it at both brokers; it holds (revert barrier)")
    return None


def ca_mode(name: str, clone: Path) -> str | None:
    """The book json's corporate_actions.mode in the BOOKS' clone, read by the book's own reader."""
    if name not in ("cef", "c4"):
        return None
    import dataclasses as _dc
    from quantt.session.run import BOOKS as SB, REPO as SREPO, corporate_actions_for
    b = SB[name]
    return corporate_actions_for(_dc.replace(b, book_path=Path(clone) / b.book_path.relative_to(SREPO)))
