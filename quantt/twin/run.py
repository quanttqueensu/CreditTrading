"""The twin's order phase and its read-only tools: send (and its dry form), epoch, probe, approve, cancel-open.

PAPER ONLY. The only caller of `IBKRClient.place_moc` in the repository is `_transmit` below, and
it is reached only after every gate here has passed. Nothing here re-implements the Alpaca books'
gates; it imports their pure pieces (`quantt.session.gate.gate_dry_run`, `gate_arming`,
`buying_power_needed`, the corporate-action check, the records writer) and adds what IBKR needs.

THE SEND, IN ORDER (contract §4.1-4.4)
  1. clock    Alpaca's clock and calendar (read-only), checked against the repo's NYSE calendar, as
              the books do; F is today. Outside the slot: IDLE (before it, or after the close) or
              REFUSED (from close - 15 min). `config.py` has the times; a 13:00 close moves them.
  2. done     DONE (a send finished) or, while DRY_RUN is not "0", DRY_DONE: IDLE. STARTED without
              DONE is a send that began and did not finish: REFUSED by rule 2, never resumed.
  3. plans    each book's saved plan for F (`books.py`); a book that did not decide, or whose own
              halt is set, HOLDS. The corporate-action gate runs for each book in its own mode on
              the twin's own holdings (`_ca_gate`); under `halt` a blocking event holds that book.
  4. IBKR     connect (read-only unless the send could transmit), prove the account, read
              positions, buying power, all-client open orders and today's executions. A Gateway
              that cannot be reached or is logged out is REFUSED [gateway]: a missed session that
              counts against the twin (contract §2 line 1).
  5. ledger   the twin's ledger must sum to IBKR's positions on every symbol (`ledger.py`), and
              every earlier session that STARTED must have been booked by verify.
  6. orders   combined target - IBKR position, one MOC order a symbol (`combine.py`).
  7. gates    DRY_RUN exactly "0"; not staging; armed (`<state>/AUTO_ARMED`, or `<F>/APPROVED` /
              `--approve` naming this plan_sha); no global or twin halt; rule 2 (`guard.py`);
              buying power (the openings within `bp_fit_fraction` of IBKR's buying power).
  8. record   STARTED, exclusively, BEFORE the first order, holding the whole plan; then plan.json.
  9. transmit one `place_moc` per order, an `intent` line fsynced before each and the result
              after; the batch stops at close - 12 min and at the first unacknowledged order, and
              never resends. A rejection skips that symbol and the rest go (team lead 2026-09-28).

`send --dry [--session D]` runs steps 3-7 for session D's saved plans against IBKR's positions NOW,
on a read-only connection, prints the orders and every gate's result, and transmits nothing
whatever DRY_RUN says (team lead 2026-11-25: the weekend check). It writes only runs/.

STAGING (team lead 2026-11-25: "staged on the VM from a local copy, and only then pushed once").
`QUANTT_TWIN_STAGING` set, to anything, is a refusal that no setting can lift: a staging install
runs a copy of an unreleased tree and must never transmit. Its units also force DRY_RUN=1.

EXIT CODES are the books' (`quantt.session.run.EXIT_NAMES`): 0 SENT, 3 NOTHING_TO_SEND, 5 IDLE,
10 DRY (only dry_run / arming / staging refused), 11 REFUSED, 20 FAIL.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from quantt.session import gate as gt
from quantt.session import records as rec
from quantt.session.run import (EXIT_DRY, EXIT_FAIL, EXIT_IDLE, EXIT_NAMES, EXIT_NOTHING, EXIT_REFUSED,
                                EXIT_SENT, asof_for)
from quantt.sleeves import ledger
from quantt.twin import books, combine, config, guard, status
from quantt.twin.books import LEGACY, TwinRefused

DELIBERATE = frozenset({"dry_run", "arming", "staging"})
EPOCH_FILE = "EPOCH.json"
CALENDAR_LOOKBACK_DAYS = 14


@dataclasses.dataclass
class Deps:
    """Everything a phase touches outside itself; tests pass fakes."""
    env: dict
    state: Path
    market: object                                  # market.MarketData
    ibkr: Callable[[str], object]                   # mode -> an unconnected IBKRClient
    utcnow: Callable[[], dt.datetime] = dataclasses.field(
        default=lambda: dt.datetime.now(dt.timezone.utc))
    out: object = dataclasses.field(default_factory=lambda: sys.stdout)
    cfg: config.TwinConfig = None
    memory: Callable[[], dict] = None
    own_clone: Path = config.REPO                    # the clone the twin runs from (its own halts)
    unit_env: Callable[[str], str] = None            # unit -> its loaded Environment (books' arming)
    firewall_status: Path = config.FIREWALL_STATUS   # root's record of the port filter (read only)

    def __post_init__(self):
        if self.cfg is None:
            self.cfg = config.load()
        if self.memory is None:
            self.memory = host_memory
        if self.unit_env is None:
            self.unit_env = systemd_environment


def systemd_environment(unit: str) -> str:
    """`systemctl show <unit> -p Environment --value`: the LOADED environment, read-only (the
    loaded copy is what runs: quantt/deploy/install_vm.py). Raises when it cannot be read."""
    import subprocess
    r = subprocess.run(["systemctl", "show", unit, "-p", "Environment", "--value"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(f"systemctl show {unit} exited {r.returncode}")
    return r.stdout.strip()


def host_memory() -> dict:
    """The Gateway unit's MemoryPeak and the machine's MemAvailable, for status.json at every
    probe (review of the build, finding 7: the staging day measures them; no setting reads them).
    Each that cannot be read is UNMEASURED with why, never a number."""
    import subprocess
    out = {}
    try:
        r = subprocess.run(["systemctl", "show", "quantt-ibgw.service", "-p", "MemoryPeak", "--value"],
                           capture_output=True, text=True, timeout=10)
        v = r.stdout.strip()
        out["ibgw_memory_peak_bytes"] = int(v) if r.returncode == 0 and v.isdigit() else f"UNMEASURED ({v or r.returncode})"
    except (OSError, subprocess.TimeoutExpired) as e:
        out["ibgw_memory_peak_bytes"] = f"UNMEASURED ({type(e).__name__})"
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                out["mem_available_kb"] = int(line.split()[1])
        out.setdefault("mem_available_kb", "UNMEASURED (no MemAvailable line)")
    except OSError as e:
        out["mem_available_kb"] = f"UNMEASURED ({type(e).__name__})"
    return out


def twin_halts(deps, books_clone: Path) -> list:
    """ops/HALT.md (every book) and ops/HALT_twin.md, in the twin's own clone AND the books' clone
    (re-review N1): a halt a person wrote where the books run stops the twin too."""
    return books.halts_in(deps.own_clone, "twin") + books.halts_in(books_clone, "twin")


def staging(env) -> bool:
    return bool(env.get(config.ENV_STAGING))


def _stamp(deps) -> str:
    return deps.utcnow().strftime("%Y%m%dT%H%M%SZ")


def setup(deps) -> Path:
    state = Path(deps.state)
    if not state.is_dir():
        raise rec.StateDirError(f"twin state directory {state} does not exist; create it deliberately")
    if state.name != config.STATE_DIR_NAME:
        raise rec.StateDirError(f"the twin's state directory must be named {config.STATE_DIR_NAME!r}; {state} "
                                "is not (a book's STARTED and plan.json would be read as the twin's)")
    return state


def session_for(market, day: dt.date) -> tuple:
    """(F's calendar row or None, the session before F). Alpaca's calendar and the repo's NYSE
    calendar must agree on whether F trades, or this refuses rather than pick one."""
    from ops.schedule.nyse_calendar import is_trading_day
    cal = market.calendar(day - dt.timedelta(days=CALENDAR_LOOKBACK_DAYS), day)
    rows = [r for r in cal if r["date"] == day]
    if len(rows) > 1:
        raise TwinRefused(f"Alpaca's calendar has {len(rows)} rows for {day}")
    if is_trading_day(day) != bool(rows):
        raise TwinRefused(f"calendars disagree on {day}: Alpaca rows={len(rows)}, nyse_calendar "
                          f"trading={is_trading_day(day)}; not choosing one")
    if not rows:
        return None, None
    try:
        want = config.expected_close(day)
    except LookupError as e:
        raise TwinRefused(str(e)) from None
    if rows[0]["close"] != want:
        raise TwinRefused(f"Alpaca's calendar closes {day} at {rows[0]['close']}; this repo expects {want} "
                          "(quantt/twin/config.expected_close); not choosing one")
    return rows[0], asof_for(day, cal)


def midnight_et(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(0, 0), tzinfo=gt.ET)


def events_min_usd(books_clone: Path) -> float:
    """The events book's own minimum net order (`min_order_usd`), from the events book file in the
    BOOKS' clone (the file the events book runs with), read by the events runner's own loader."""
    from quantt.sleeves import config as scfg
    return float(scfg.load(Path(books_clone) / "ops" / "sleeves" / "events_sleeves.json").min_order_usd)


# ------------------------------------------------------------------ the ledger

def read_ledger(state: Path) -> tuple:
    """(ledger, epoch record). No EPOCH.json is a refusal: the twin starts only from a recorded
    epoch (`epoch`), which seeds the account's own positions under `legacy`."""
    ep = state / EPOCH_FILE
    if not ep.exists():
        raise TwinRefused(f"no {ep}: record the twin's epoch first (`python3 -m quantt.twin epoch`)")
    from quantt.sleeves.run import check_ledger
    p = state / "ledger.json"
    if not p.exists():
        raise TwinRefused(f"{ep} exists and {p} does not: the ledger was removed after the epoch")
    return check_ledger(json.loads(p.read_text()), str(p)), json.loads(ep.read_text())


def unbooked(state: Path, before: dt.date) -> list:
    out = []
    for d in sorted(state.iterdir()):
        if d.is_dir() and guard._DAY.fullmatch(d.name) and d.name < before.isoformat() \
                and (d / "STARTED").exists():
            v = d / "verify.json"
            if not (v.exists() and json.loads(v.read_text()).get("ledger_applied")):
                out.append(d.name)
    return out


def slug_history(state: Path, slug: str) -> list:
    """The twin's own "closed orders" for one slug, in the shape the corporate-action gate reads
    (`corp_actions.held_since`: symbol, filled_qty, submitted_at): one per booking, fill or cross,
    stamped with that session's STARTED time. A crossed booking sets shares too, so it counts."""
    out = []
    for d in sorted(state.iterdir()):
        if not (d.is_dir() and guard._DAY.fullmatch(d.name)):
            continue
        v, st = d / "verify.json", d / "STARTED"
        if not (v.exists() and st.exists()):
            continue
        vd = json.loads(v.read_text())
        if not vd.get("ledger_applied"):
            continue
        at = json.loads(st.read_text())["written_utc"]
        for b in vd.get("bookings") or []:
            if b["slug"] == slug and b["shares"]:
                out.append({"client_order_id": f"twin-{d.name}-{b['symbol']}", "symbol": b["symbol"],
                            "filled_qty": str(abs(b["shares"])), "submitted_at": at})
    return out


def _ca_gate(deps, name: str, mode: str, held: dict, targets, asof: dt.date, F: dt.date,
             book_state: Path, state: Path) -> tuple:
    """The book's corporate-action gate, in ITS mode, on the TWIN's holdings of its slug
    (`quantt.session.corp_actions.check`, the books' own function). Any failure is UNMEASURED,
    never CLEAR; under `halt` that, or a blocking event, holds the book."""
    from quantt.session import corp_actions as cam
    from quantt.session.run import _read_ca_acks
    try:
        acks = _read_ca_acks(book_state / cam.ACKS_FILE, name)
        res = cam.check(deps.market.corporate_actions, slug_history(state, name), held, targets, asof, F,
                        mode, universe=sorted(set(held) | set(targets)), acks=acks)
    except Exception as e:  # noqa: BLE001 -- recorded as UNMEASURED, never swallowed
        res = cam.unmeasured_record(mode, asof, F, f"{type(e).__name__}: {e}")
    return res, (cam.refusal_text(res) if mode == cam.HALT else None)


def _prices(reads: dict) -> tuple:
    """({symbol: as-of close}, {symbol: {book: close}}). Where two plans price one symbol (the core
    from its yfinance panel, events from Alpaca's daily bar) the HIGHER is used, so the buying-power
    estimate errs high; both are recorded."""
    by = {}
    for name, r in reads.items():
        for s, p in r.closes.items():
            by.setdefault(s, {})[name] = p
    return {s: max(v.values()) for s, v in by.items()}, by


def bp_check(orders, positions: dict, summary: dict, fraction: float) -> tuple:
    """(record, refusal or None). The events book's rule (team lead 2026-11-25, "Keep 3% spare"):
    the openings' buying-power need (`gate.buying_power_needed`: shorts at 1.03x, reductions zero)
    against `fraction` x IBKR's BuyingPower in USD. Over it: refused, with the factor that would
    have fitted, because the scale-fit is not on main (a labelled difference from the books)."""
    need = gt.buying_power_needed(orders, positions, {o.symbol: o.est_price for o in orders})
    r = {"buying_power": summary["buying_power"], "base_currency": summary["base_currency"],
         "usd_per_base": summary["usd_per_base"], "fit_fraction": fraction, "need_usd": round(need, 2)}
    if summary["usd_per_base"] is None:
        return r, (f"buying power is in {summary['base_currency']} and IBKR gave no USD exchange rate; the "
                   "openings' need cannot be judged, so nothing is sent")
    bp_usd = summary["buying_power"] * summary["usd_per_base"]
    target = fraction * bp_usd
    factor = 1.0 if need <= target else target / need
    r.update(buying_power_usd=round(bp_usd, 2), target_usd=round(target, 2), factor_needed=round(factor, 6))
    if factor < 1.0:
        return r, (f"the openings need ${need:,.2f} of buying power, above {fraction} x IBKR's ${bp_usd:,.2f}; "
                   f"they would fit scaled by {factor:.4f}. The scale-fit (quantt/sleeves/fit.py) is not on "
                   "main, so the twin REFUSES where the Alpaca books would scale: a labelled difference")
    return r, None


# -------------------------------------------------------------------- the send

def send(deps, *, dry: bool = False, session: dt.date | None = None, approve: str | None = None) -> int:
    return _guarded(lambda: _send(deps, dry=dry, session=session, approve=approve), deps,
                    "dry" if dry else "send")


def _guarded(fn, deps, mode: str) -> int:
    from quantt.broker.ibkr import IBKRError
    try:
        return fn()
    except (TwinRefused, rec.StateDirError, ledger.LedgerError, config.ConfigError, guard.GuardUnknown,
            guard.AlreadyTransmitting, IBKRError) as e:
        print(f"REFUSED {mode}: {type(e).__name__}: {e}", file=deps.out)
        print(f"exit {EXIT_REFUSED} {EXIT_NAMES[EXIT_REFUSED]}", file=deps.out)
        return EXIT_REFUSED
    except Exception as e:  # noqa: BLE001 -- reported with its traceback, exit FAIL
        print(f"FAIL {mode}: {type(e).__name__}: {e}", file=deps.out)
        print(traceback.format_exc(), file=deps.out)
        print(f"exit {EXIT_FAIL} {EXIT_NAMES[EXIT_FAIL]}", file=deps.out)
        return EXIT_FAIL


def _finish(deps, state: Path, day: Path | None, record: dict, code: int, *, scheduled: bool) -> int:
    record["exit"] = {"code": code, "name": EXIT_NAMES[code]}
    stamp = _stamp(deps)
    where = (day if day is not None else state) / "runs"
    where.mkdir(exist_ok=True)
    rec.write_json_atomic(where / f"{stamp}-{record['mode']}.json", record)
    if scheduled and day is not None:
        marker = {EXIT_SENT: "DONE", EXIT_NOTHING: "DONE", EXIT_DRY: "DRY_DONE"}.get(code)
        if marker:
            (day / marker).write_text(f"{EXIT_NAMES[code]} at {stamp}\n")
        write_send_record(day, record)
    if record["mode"] in ("send", "dry"):
        summ = {"mode": record["mode"], "session_date": record.get("session_date"),
                "exit": EXIT_NAMES[code], "orders": len(record.get("orders") or []),
                "refusals": sorted({r["gate"] for r in record.get("refusals") or []}),
                "sent": record.get("sent"), "rejected": record.get("rejected")}
        status.update(state, "last_" + record["mode"], summ, deps.utcnow().isoformat())
        if code != EXIT_IDLE:
            # Release check 4: an IDLE run (outside a slot, or the day already DONE) overwrites
            # last_send every time; the last run that did anything is kept apart for orient and the page.
            status.update(state, "last_session_" + record["mode"], summ, deps.utcnow().isoformat())
    print(f"exit {code} {EXIT_NAMES[code]}", file=deps.out)
    return code


SEND_RECORD = "send.json"
_SEND_RUN_RE = re.compile(r"^send_\d{4}(?:_\d+)?\.json$")


def write_send_record(day: Path, record: dict) -> Path:
    """THE RUN THAT WROTE STARTED HAS THE ONE `send.json` (release check 2, 2026-11-26). It is created
    exclusively and never overwritten. Every other scheduled run (a backup that refused on STARTED, a
    refusal before any set, a dry run) gets its own `send_<HHMM>.json`, New York time of its clock, so a
    backup can never replace the record of a first send that stopped or was rejected (verify read the
    last record, and scored a part-sent batch PASS)."""
    if record.get("wrote_started"):
        if rec.create_exclusive(day / SEND_RECORD, record):
            return day / SEND_RECORD
        other = day / f"send_STARTED_conflict_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
        rec.write_json_atomic(other, record)
        raise TwinRefused(f"{day / SEND_RECORD} already exists although this run wrote STARTED; this run's "
                          f"record is {other.name}. Read both before verify books anything")
    hhmm = record["clock"].astimezone(gt.ET).strftime("%H%M")
    for n in range(1000):
        p = day / (f"send_{hhmm}.json" if n == 0 else f"send_{hhmm}_{n}.json")
        if rec.create_exclusive(p, record):
            return p
    raise TwinRefused(f"{day}: a thousand send records for {hhmm}; not writing another")


def started_send_record(day: Path) -> dict | None:
    """The record of the run that wrote STARTED, or None (it never finished: a crash after STARTED)."""
    p = day / SEND_RECORD
    return json.loads(p.read_text()) if p.exists() else None


def latest_send_record(day: Path) -> dict | None:
    """With no STARTED: the newest run's own record (`send_<HHMM>.json`). A `send.json` without STARTED
    is a record in the format before 2026-11-26 (every run rewrote it); it is read when no newer one exists."""
    runs = sorted(p.name for p in day.iterdir() if _SEND_RUN_RE.fullmatch(p.name)) if day.exists() else []
    if runs:
        return json.loads((day / runs[-1]).read_text())
    return started_send_record(day)


def _gateway_down(deps, state, e) -> None:
    """Record a logged-out or unreachable Gateway for orient. A BUSY session lock (B10: another of
    this desk's processes, the feed, is connected) says nothing about the login, so it is not
    written as "logged out"; the phase still refuses, and its own record says why."""
    from quantt.broker.ibkr import GatewayBusy
    if isinstance(e, GatewayBusy):
        return
    status.update(state, "gateway", {"logged_in": False, "why": f"{type(e).__name__}: {e}"},
                  deps.utcnow().isoformat())


def _send(deps, *, dry: bool, session: dt.date | None, approve: str | None) -> int:
    from quantt.broker.ibkr import IBKRError, NotConnected, OpenOrdersUnknown, UnexpectedReply, WrongAccount
    out, env = deps.out, deps.env
    state = setup(deps)
    states = books.book_states(env)
    mode = "dry" if dry else "send"
    clk = deps.market.clock()
    now = clk["timestamp"].astimezone(gt.ET)
    F = session if (dry and session is not None) else now.date()
    if not dry and session is not None:
        raise TwinRefused("--session is for --dry only: a real send is always for today's session")
    row, asof = session_for(deps.market, F)
    record = {"mode": mode, "session_date": F, "clock": now, "staging": staging(env), "refusals": []}
    if row is None:
        print(f"twin {mode}: {F} is not a trading day; nothing to send", file=out)
        return _finish(deps, state, None, record, EXIT_IDLE, scheduled=False)
    close = config.close_et(F, row["close"])
    t = config.times(close)
    record.update(asof=asof, close_et=close, slots=t["slots"], refuse_from=t["refuse_from"])
    day = None
    if not dry:
        where = config.slot_state(now, close)
        if where in ("early", "after_close"):
            print(f"twin send: {now:%Y-%m-%d %H:%M} ET is not a send slot for {F} (close {row['close']}; slots "
                  f"{t['slots'][0]:%H:%M} and {t['slots'][1]:%H:%M}); nothing to do", file=out)
            return _finish(deps, state, None, record, EXIT_IDLE, scheduled=False)
        day = rec.day_dir(state, F)
        if (day / "DONE").exists():
            print(f"twin send: {F} is done ({(day / 'DONE').read_text().strip()})", file=out)
            return _finish(deps, state, None, record, EXIT_IDLE, scheduled=False)
        if (day / "DRY_DONE").exists() and env.get("DRY_RUN") != "0":
            print(f"twin send: {F} already ran dry ({(day / 'DRY_DONE').read_text().strip()})", file=out)
            return _finish(deps, state, None, record, EXIT_IDLE, scheduled=False)
        if where == "too_late":
            record["refusals"].append({"gate": "clock", "detail": f"{now:%H:%M:%S} ET is at or after the "
                                       f"refuse time {t['refuse_from']:%H:%M} ET ({F} closes {row['close']})"})
            print(f"  REFUSED [clock] {record['refusals'][-1]['detail']}", file=out)
            return _finish(deps, state, day, record, EXIT_REFUSED, scheduled=True)

    # 3. the books' plans, their own arming and halts, and the twin's ledger
    bclone = books.books_clone(env)
    reads = books.read_books(states, F, asof)
    arming = {}
    for name in books.BOOK_NAMES:
        why = books.book_not_armed(name, states[name], deps.unit_env, (deps.own_clone, bclone))
        why = why or books.revert_barrier(name, states[name], F)
        arming[name] = why or "armed"
        if why and reads[name].status == "decided":
            reads[name] = books.hold(name, why)
    record["books_own_arming"] = arming
    epoch_simulated = False
    try:
        led, epoch_rec = read_ledger(state)
    except TwinRefused as e:
        if not dry:
            raise
        led, epoch_rec, epoch_simulated = None, None, True
        print(f"  NOTE (--dry): {e}; the epoch is SIMULATED from IBKR's positions under {LEGACY!r}", file=out)
    if not dry:
        ub = unbooked(state, F)
        if ub:
            raise TwinRefused(f"session(s) {ub} STARTED and are not booked; run verify for them first")

    # 4. IBKR
    can_transmit = (not dry) and env.get("DRY_RUN") == "0" and not staging(env)
    client = deps.ibkr("trade" if can_transmit else "read")
    try:
        client.connect()
    except (NotConnected, WrongAccount) as e:
        _gateway_down(deps, state, e)
        record["refusals"].append({"gate": "gateway", "detail": str(e)})
        print(f"  REFUSED [gateway] {e}", file=out)
        return _finish(deps, state, day, record, EXIT_REFUSED, scheduled=not dry)
    try:
        status.update(state, "gateway", {"logged_in": True, "why": f"{mode} connected"}, deps.utcnow().isoformat())
        try:
            pos = client.positions()
            summary = client.account_summary()
        except IBKRError as e:
            # Review finding 13: a failed read still leaves a send record saying why.
            record["refusals"].append({"gate": "ibkr_read", "detail": f"{type(e).__name__}: {e}"})
            print(f"  REFUSED [ibkr_read] {type(e).__name__}: {e}", file=out)
            return _finish(deps, state, day, record, EXIT_REFUSED, scheduled=not dry)
        try:
            try:
                open_o, open_err = client.open_orders(), None
            except OpenOrdersUnknown as e:
                open_o, open_err = None, str(e)
            try:
                execs, exec_err = client.executions_today(since=midnight_et(now.date())), None
            except (UnexpectedReply, ValueError) as e:
                execs, exec_err = None, f"{type(e).__name__}: {e}"
        except IBKRError as e:
            # A hung Gateway (RequestTimedOut: the session is dropped, the lock released) or a lost
            # session: the send stops here and still writes its record (review finding 13).
            record["refusals"].append({"gate": "ibkr_read", "detail": f"{type(e).__name__}: {e}"})
            print(f"  REFUSED [ibkr_read] {type(e).__name__}: {e}", file=out)
            return _finish(deps, state, day, record, EXIT_REFUSED, scheduled=not dry)
        if epoch_simulated:
            led = ledger.empty()
            if pos:
                led["sleeves"][LEGACY] = {"shares": dict(pos), "cash": 0.0, "stale_sessions": 0}
        record.update(positions_n=len(pos), account={k: summary[k] for k in ("base_currency",)},
                      epoch_simulated=epoch_simulated)
        try:
            ledger.check_against_broker(led, pos)
        except ledger.LedgerError as e:
            record["refusals"].append({"gate": "ledger", "detail": str(e)})

        # the corporate-action gate, each book in its own mode, on the twin's holdings
        shares = ledger.shares_of(led)
        ca = {}
        for name in ("cef", "c4"):
            m = books.ca_mode(name, bclone)
            if m is None:
                continue
            r = reads[name]
            held = shares.get(name, {})
            tg = sorted(r.book_targets) if r.status == "decided" else sorted(held)
            ca[name], refusal = _ca_gate(deps, name, m, held, tg, dt.date.fromisoformat(str(asof)), F,
                                         states[name], state)
            if refusal and r.status == "decided":
                reads[name] = books.hold(name, refusal)
        record["corporate_actions"] = ca

        # 6. the orders
        plans = combine.slug_plans(reads, shares)
        prices, priced_by = _prices(reads)
        tgt_all = combine.combined(plans)
        need_px = sorted(s for s in set(tgt_all) | set(pos)
                         if tgt_all.get(s, 0) != pos.get(s, 0) and s not in prices)
        if need_px:
            got = deps.market.daily_closes(need_px, asof, deps.utcnow())
            for s, p in got.items():
                prices[s] = p
                priced_by.setdefault(s, {})["alpaca_daily_bar"] = p
        plans, small = combine.apply_events_minimum(plans, shares, prices, events_min_usd(bclone))
        record["events_below_minimum"] = small
        orders, tgt = combine.make_orders(plans, pos, F, prices)
        sha = combine.plan_sha(orders)
        # Review finding 3: every symbol resolved to one US stock BEFORE any gate is judged, on the
        # dry path too (`reqContractDetails` is a read). An unresolved one is a named refusal.
        try:
            client.qualify([o.symbol for o in orders])
        except IBKRError as e:
            record["refusals"].append({"gate": "contracts", "detail": f"{type(e).__name__}: {e}"})
        record.update(books={n: r.record() for n, r in reads.items()},
                      slugs=[dataclasses.asdict(p) for p in plans], targets=tgt,
                      orders=[o.to_dict() for o in orders], plan_sha=sha,
                      prices_by_source={s: priced_by[s] for s in sorted({o.symbol for o in orders})})

        # 7. the gates
        bp_rec, bp_refusal = bp_check(orders, pos, summary, deps.cfg.bp_fit_fraction)
        record["buying_power"] = bp_rec
        if bp_refusal:
            record["refusals"].append({"gate": "buying_power", "detail": bp_refusal})
        started = day is not None and (day / "STARTED").exists()
        pend = guard.pending_in_logs(state, deps.utcnow().astimezone(gt.ET))
        for g, d in guard.refusals(started=started, open_orders=open_o, open_orders_error=open_err,
                                   pending=pend, executions=execs, executions_error=exec_err):
            record["refusals"].append({"gate": g, "detail": d})
        for r in gt.gate_dry_run(env.get("DRY_RUN")):
            record["refusals"].append({"gate": r.gate, "detail": r.detail})
        if staging(env):
            record["refusals"].append({"gate": "staging", "detail": f"{config.ENV_STAGING} is set: a staging "
                                       "install never transmits"})
        appr = approve
        if appr is None and day is not None and (day / "APPROVED").exists():
            a = json.loads((day / "APPROVED").read_text())
            if str(a.get("session_date")) != F.isoformat():
                record["refusals"].append({"gate": "arming", "detail": f"{day / 'APPROVED'} approves session "
                                           f"{a.get('session_date')}, not {F}"})
            else:
                appr = a["plan_sha"]
        for r in gt.gate_arming(appr, sha, (state / "AUTO_ARMED").exists()):
            record["refusals"].append({"gate": r.gate, "detail": r.detail})
        for h in twin_halts(deps, bclone):
            record["refusals"].append({"gate": "halt", "detail": h})
        if os.path.lexists(state / "HALT"):
            record["refusals"].append({"gate": "halt", "detail": f"{state / 'HALT'} exists"})

        _print_plan(out, F, now, reads, plans, orders, sha, record)
        if dry:
            print("DRY (--dry): nothing was transmitted, and nothing can be from this mode", file=out)
            return _finish(deps, state, None, record, EXIT_DRY, scheduled=False)
        gates = {r["gate"] for r in record["refusals"]}
        if not (day / "STARTED").exists():
            rec.write_json_atomic(day / "plan.json", {**record, "status": "refused" if gates else "decided"})
        if gates:
            code = EXIT_DRY if gates <= DELIBERATE else EXIT_REFUSED
            return _finish(deps, state, day, record, code, scheduled=True)
        if not orders:
            return _finish(deps, state, day, record, EXIT_NOTHING, scheduled=True)
        return _transmit(deps, client, state, day, F, close, t, orders, sha, record, epoch_rec, led)
    finally:
        client.disconnect()


def _print_plan(out, F, now, reads, plans, orders, sha, record) -> None:
    print(f"twin {record['mode']} {F} (as-of {record['asof']}), clock {now:%Y-%m-%d %H:%M:%S} ET, close "
          f"{record['close_et']:%H:%M}", file=out)
    for name, r in reads.items():
        print(f"  {name:<7}{r.status:<9}{r.plan_sha or '':<16.16}{r.why}", file=out)
    for p in plans:
        print(f"    {p.slug:<34}{p.action:<9}{len(p.targets):>4} name(s){'  ' + p.why if p.why else ''}", file=out)
    print(combine.order_table(orders), file=out)
    print(f"plan_sha {sha}", file=out)
    b = record.get("buying_power") or {}
    print(f"  buying power: need ${b.get('need_usd', 0):,.2f}; IBKR {b.get('buying_power')} "
          f"{b.get('base_currency')} (USD {b.get('buying_power_usd')}); factor needed {b.get('factor_needed')}",
          file=out)
    for name, c in (record.get("corporate_actions") or {}).items():
        print(f"  corporate actions {name}: {c.get('mode')} {c.get('status')}", file=out)
    if not record["refusals"]:
        print("  every gate passed", file=out)
    for r in record["refusals"]:
        print(f"  REFUSED [{r['gate']}] {r['detail']}", file=out)


def _transmit(deps, client, state, day, F, close, t, orders, sha, record, epoch_rec, led) -> int:
    """Steps 8-9. Holds the transmit lock from before STARTED to the process's end."""
    out = deps.out
    with guard.transmit_lock(state):
        if (day / "STARTED").exists():
            record["refusals"].append({"gate": "no_set_in_auction", "detail": "STARTED appeared before the lock"})
            return _finish(deps, state, day, record, EXIT_REFUSED, scheduled=True)
        client.qualify([o.symbol for o in orders])      # an unknown symbol refuses while nothing is sent
        clk = deps.market.clock()
        skew = clk["timestamp"] - deps.utcnow()
        from quantt.sleeves.run import ledger_sha
        started = {"plan_sha": sha, "session_date": F, "pid": os.getpid(), "written_utc": deps.utcnow(),
                   "ledger_sha": ledger_sha(led),
                   "order_refs": [o.order_ref for o in orders], "close_et": close,
                   "slugs": record["slugs"], "books": record["books"], "orders": record["orders"],
                   "epoch": epoch_rec}
        if not rec.create_exclusive(day / "STARTED", started):
            record["refusals"].append({"gate": "no_set_in_auction", "detail": "STARTED appeared between gate and record"})
            return _finish(deps, state, day, record, EXIT_REFUSED, scheduled=True)
        record["wrote_started"] = True                   # this run's record is THE send.json
        rec.write_json_atomic(day / "plan.json", {**record, "status": "decided"})
        log = day / "orders.jsonl"
        sent, rejected, stopped = [], [], None
        refused_close = set()
        for i, o in enumerate(orders):
            if o.leg == 2 and o.symbol in refused_close:
                rec.append_jsonl(log, {"event": "skipped_open_leg", "order_ref": o.order_ref, "symbol": o.symbol,
                                       "at": deps.utcnow()})
                continue
            now = (deps.utcnow() + skew).astimezone(gt.ET)
            if now >= t["place_by"]:
                # The session's own deadline (config.SEND_PLACE_MARGIN_S before the batch stop), never a
                # count from the run's start; the unit's kill a minute later is the backstop.
                stopped = (f"cutoff: {now:%H:%M:%S} ET is at or after {t['place_by']:%H:%M} ET "
                           f"(the batch stop {t['stop_batch']:%H:%M} less {config.SEND_PLACE_MARGIN_S} s)")
                for o2 in orders[i:]:
                    rec.append_jsonl(log, {"event": "cutoff", "order_ref": o2.order_ref, "symbol": o2.symbol,
                                           "at": deps.utcnow()})
                break
            rec.append_jsonl(log, {"event": "intent", "order_ref": o.order_ref, "symbol": o.symbol, "side": o.side,
                                   "qty": o.qty, "session_date": F, "close_et": close, "at": deps.utcnow()})
            try:
                res = client.place_moc(o.symbol, o.qty, o.side, o.order_ref)
            except Exception as e:  # noqa: BLE001 -- recorded; the batch stops; never resent
                rec.append_jsonl(log, {"event": "error", "order_ref": o.order_ref, "symbol": o.symbol,
                                       "error": f"{type(e).__name__}: {e}", "at": deps.utcnow()})
                stopped = f"{o.symbol}: placeOrder raised {type(e).__name__}: {e}; the batch stopped, nothing resent"
                break
            rec.append_jsonl(log, {"event": "placed", **res, "at": deps.utcnow()})
            if res["accepted"] is True:
                sent.append(o.order_ref)
            elif res["accepted"] is False:
                rejected.append({"symbol": o.symbol, "order_ref": o.order_ref, "status": res["status"],
                                 "opens_short": o.opens_short, "leg": o.leg, "messages": res["messages"]})
                if o.leg == 1:
                    refused_close.add(o.symbol)
                print(f"  REJECTED {o.symbol} {o.side} {o.qty}: {res['status']} {res['messages']}", file=out)
            else:
                stopped = (f"{o.symbol}: no acknowledgement within the wait (status {res['status']!r}); the "
                           "batch stopped and nothing is resent (rule 2)")
                break
        record.update(sent=len(sent), rejected=rejected, stopped=stopped)
        print(f"  sent {len(sent)} of {len(orders)}; rejected {len(rejected)}"
              + (f"; STOPPED: {stopped}" if stopped else ""), file=out)
        return _finish(deps, state, day, record, EXIT_FAIL if stopped else EXIT_SENT, scheduled=True)


# ------------------------------------------------------------- the read-only tools

def probe(deps) -> int:
    """Read the account: whether the Gateway is logged in, the account's base currency, NLV and
    buying power, and COUNTS of positions, open orders and today's executions. Read-only by
    construction: a read client (`IBKRClient` mode "read": no place, no cancel). The
    printed lines are aggregates; the full reading goes to `<state>/probe/<stamp>.json`."""
    from quantt.broker.ibkr import GatewayBusy, IBKRError, NotConnected, RequestTimedOut, WrongAccount
    state = setup(deps)
    client = deps.ibkr("read")
    at = deps.utcnow().isoformat()
    status.update(state, "firewall", firewall_record(deps.firewall_status, deps.utcnow()), at)
    try:
        client.connect()
    except GatewayBusy as e:
        print(f"PROBE gateway BUSY (not read): {e}", file=deps.out)
        return 2
    except (NotConnected, WrongAccount) as e:
        _gateway_down(deps, state, e)
        print(f"PROBE gateway LOGGED OUT or unreachable: {e}", file=deps.out)
        return 2
    try:
        s = client.account_summary()
        pos = client.positions()
        oo = client.open_orders()
        ex = client.executions_today(since=midnight_et(deps.utcnow().astimezone(gt.ET).date()))
        st = client.server_time()
    except RequestTimedOut as e:
        # A Gateway that connects and then never answers is as good as down for the next send.
        status.update(state, "gateway", {"logged_in": False, "why": f"unresponsive: {e}"}, at)
        print(f"PROBE gateway UNRESPONSIVE: {e}", file=deps.out)
        return 1
    except IBKRError as e:
        print(f"PROBE FAIL: {type(e).__name__}: {e}", file=deps.out)
        return 1
    finally:
        client.disconnect()
    skew = (st - deps.utcnow()).total_seconds()
    agg = {"logged_in": True, "why": "probe connected", "base_currency": s["base_currency"],
           "net_liquidation": s["net_liquidation"], "buying_power": s["buying_power"],
           "positions": len(pos), "gross_shares": sum(abs(q) for q in pos.values()),
           "open_orders": len(oo), "executions_today": len(ex), "server_skew_s": round(skew, 1),
           **deps.memory()}
    d = state / "probe"
    d.mkdir(exist_ok=True)
    rec.write_json_atomic(d / f"{_stamp(deps)}.json", {**agg, "positions_by_symbol": pos, "open_orders_rows": oo,
                                                       "at": at})
    status.update(state, "gateway", agg, at)
    print(f"PROBE gateway logged in; base {s['base_currency']}; net liquidation {s['net_liquidation']:,.2f}; "
          f"buying power {s['buying_power']:,.2f}; {len(pos)} position(s); {len(oo)} open order(s); "
          f"{len(ex)} execution(s) today; server clock {skew:+.1f}s from this machine's", file=deps.out)
    return 0


FIREWALL_STALE = dt.timedelta(minutes=15)


def firewall_record(path: Path, now: dt.datetime) -> dict:
    """The port filter's state as the probe unit's root check wrote it (config.FIREWALL_STATUS, in root's
    own directory, by ibgw_check_firewall.sh --status just before this probe; final review 3), for
    status.json. Missing, unreadable or older than FIREWALL_STALE is UNMEASURED, never "in force"."""
    p = Path(path)
    FIREWALL_FILE = str(p)
    if not p.exists():
        return {"in_force": None, "detail": f"UNMEASURED: no {FIREWALL_FILE} (the probe unit's check did not run)"}
    try:
        d = json.loads(p.read_text())
        at = dt.datetime.fromisoformat(str(d["checked_utc"]).replace("Z", "+00:00"))
        in_force = d["in_force"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return {"in_force": None, "detail": f"UNMEASURED: {FIREWALL_FILE} cannot be read ({type(e).__name__})"}
    if not isinstance(in_force, bool) or at.tzinfo is None:
        return {"in_force": None, "detail": f"UNMEASURED: {FIREWALL_FILE} is not in the check's form"}
    if now - at > FIREWALL_STALE:
        return {"in_force": None, "detail": f"UNMEASURED: the last check was {at.isoformat()}, stale", "checked_utc": at.isoformat()}
    return {"in_force": in_force, "detail": str(d.get("detail", ""))[:200], "checked_utc": at.isoformat()}


def epoch(deps) -> int:
    """ONCE: record the twin's epoch and seed its ledger (team lead 2026-11-25).

    The account may still hold the September positions (contract step 5). They are seeded under
    the slug `legacy`, which has no plan, so its target is zero and the first armed session's order
    list flattens them together with the books' openings: one list, one go. Refuses while any
    order rests (rule 2: a person cancels them, `cancel-open`), and refuses if the epoch exists."""
    from quantt.broker.ibkr import NotConnected, WrongAccount
    state = setup(deps)
    ep = state / EPOCH_FILE
    if ep.exists() or (state / "ledger.json").exists():
        print(f"REFUSED epoch: {ep if ep.exists() else state / 'ledger.json'} exists; the epoch is recorded "
              "once and never again", file=deps.out)
        return EXIT_REFUSED
    sent = sorted(d.name for d in state.iterdir() if d.is_dir() and (d / "STARTED").exists())
    if sent:
        print(f"REFUSED epoch: {sent} hold STARTED: a set has gone from this state directory, so an epoch "
              "now would seed the twin's own orders as legacy", file=deps.out)
        return EXIT_REFUSED
    client = deps.ibkr("read")
    try:
        client.connect()
    except (NotConnected, WrongAccount) as e:
        _gateway_down(deps, state, e)
        print(f"REFUSED epoch: {e}", file=deps.out)
        return EXIT_REFUSED
    try:
        oo = client.open_orders()
        pos = client.positions()
        s = client.account_summary()
    finally:
        client.disconnect()
    if oo:
        print(f"REFUSED epoch: {len(oo)} order(s) rest at IBKR; cancel them first (`cancel-open`)", file=deps.out)
        return EXIT_REFUSED
    led = ledger.empty()
    if pos:
        led["sleeves"][LEGACY] = {"shares": dict(pos), "cash": 0.0, "stale_sessions": 0}
    rec_ = {"written_utc": deps.utcnow(), "net_liquidation": s["net_liquidation"],
            "base_currency": s["base_currency"], "legacy_symbols": len(pos)}
    if not rec.create_exclusive(ep, rec_):
        print(f"REFUSED epoch: {ep} appeared meanwhile", file=deps.out)
        return EXIT_REFUSED
    rec.write_json_atomic(state / "ledger.json", led)
    print(f"EPOCH recorded: {len(pos)} position(s) seeded under {LEGACY!r} (flattened by the first session); "
          f"net liquidation {s['net_liquidation']:,.2f} {s['base_currency']}", file=deps.out)
    return 0


def approve(deps, *, session: dt.date, sha: str) -> int:
    """`<state>/<session>/APPROVED` naming the plan_sha the team lead read in `send --dry --session`
    (rule 1). The send for THAT session transmits only if it recomputes exactly this sha; no other
    session reads it. `session` is required, with no default (release check 3, 2026-11-26: the approval
    used to be written under today's date, so an approval read on Thursday for Friday armed nothing, and
    one written after midnight armed the wrong day). Refuses a past session and a day that does not
    trade. Sends nothing."""
    state = setup(deps)
    if not isinstance(session, dt.date):
        print("REFUSED approve: --session YYYY-MM-DD is required (the session the list is for)", file=deps.out)
        return EXIT_REFUSED
    today = deps.market.clock()["timestamp"].astimezone(gt.ET).date()
    if session < today:
        print(f"REFUSED approve: {session} is before today ({today}) in New York", file=deps.out)
        return EXIT_REFUSED
    row, _ = session_for(deps.market, session)
    if row is None:
        print(f"REFUSED approve: {session} is not a trading day", file=deps.out)
        return EXIT_REFUSED
    F = session
    day = rec.day_dir(state, F)
    if (day / "STARTED").exists():
        print(f"REFUSED approve: a set already STARTED for {F}", file=deps.out)
        return EXIT_REFUSED
    if not isinstance(sha, str) or len(sha) != 64:
        print("REFUSED approve: --sha must be the 64-character plan_sha that `send --dry` printed", file=deps.out)
        return EXIT_REFUSED
    rec.write_json_atomic(day / "APPROVED", {"plan_sha": sha, "session_date": F, "written_utc": deps.utcnow()})
    print(f"APPROVED {F} plan_sha {sha}: the send transmits only if it recomputes exactly this list", file=deps.out)
    return 0


def cancel_open(deps, *, confirm: int | None) -> int:
    """HUMAN-RUN (CLAUDE.md order-path rule 1: the team lead's go, the list shown first). Lists every
    open order on the account; with `--confirm N`, where N is the count just listed, cancels them all
    with `reqGlobalCancel()` (the archived lesson: `cancelOrder` fails across client ids, error
    10147; `reqGlobalCancel` cleared the 2026-07-31 stack). Refuses unless DRY_RUN is exactly "0",
    in staging, and from the freeze (close - 10 min) to the close, when NYSE cancels no MOC."""
    from quantt.broker.ibkr import NotConnected, WrongAccount
    env = deps.env
    state = setup(deps)
    act = confirm is not None
    if act:
        if env.get("DRY_RUN") != "0":
            print("REFUSED cancel-open: DRY_RUN is not exactly 0 (rule 4: it always wins)", file=deps.out)
            return EXIT_REFUSED
        if staging(env):
            print(f"REFUSED cancel-open: {config.ENV_STAGING} is set", file=deps.out)
            return EXIT_REFUSED
        now = deps.market.clock()["timestamp"].astimezone(gt.ET)
        row, _ = session_for(deps.market, now.date())
        if row is not None:
            t = config.times(config.close_et(now.date(), row["close"]))
            if t["freeze"] <= now < t["close"]:
                print(f"REFUSED cancel-open: {now:%H:%M} ET is inside the MOC freeze", file=deps.out)
                return EXIT_REFUSED
    client = deps.ibkr("trade" if act else "read")
    try:
        client.connect()
    except (NotConnected, WrongAccount) as e:
        print(f"REFUSED cancel-open: {e}", file=deps.out)
        return EXIT_REFUSED
    try:
        oo = client.open_orders()
        for o in oo:
            print(f"  open: {o['symbol']} {o['action']} {o['qty']:.0f} {o['order_type']} {o['status']} "
                  f"client {o['client_id']} permId {o['perm_id']}", file=deps.out)
        print(f"{len(oo)} open order(s)", file=deps.out)
        if not act:
            print("listed only; to cancel them all: DRY_RUN=0 ... cancel-open --confirm <that count>", file=deps.out)
            return 0
        if confirm != len(oo):
            print(f"REFUSED cancel-open: --confirm {confirm} is not the {len(oo)} listed now", file=deps.out)
            return EXIT_REFUSED
        if not oo:
            return 0
        client.global_cancel()
        rec.append_jsonl(state / "cancels.jsonl", {"at": deps.utcnow(), "cancelled": len(oo)})
        print(f"reqGlobalCancel sent for {len(oo)} order(s); run cancel-open again to see what remains",
              file=deps.out)
        return 0
    finally:
        client.disconnect()
