"""B10: IBKR daily bars (and an intraday quote capture) for the shadow books, written as plain files. READ ONLY.

    python3 -m quantt.twin feed --slot after-close|evening|intraday

WHY (team lead, 2026-11-25: "we can trade/interacti with ibrk quotes to run shadow books / test
ideas"; results/ops/IBKR_PAPER_MOVE_2026-11-25.md §5 B10, on its own branch). The paper books move
to one IBKR paper account behind an IB Gateway on the VM. The shadow books and idea tests may use
IBKR's prices. THE RULE THAT CANNOT BEND: the shadow user never reaches the Gateway's API port,
because the Gateway can send orders. So:
  * this producer runs as the trading user (`quantt`), with its own client id, through a client
    built in READ mode, which refuses `place_moc`, `cancel` and `global_cancel`
    (quantt/broker/ibkr.py), and reads market data only through quantt/broker/ibkr_market.py;
  * it writes plain files into the feed directory (`/srv/quantt-ibkr-feed`, `quantt:quantt-shadow`
    2750, files 0640), which the shadow side only reads (shadow/ibkr_feed.py on the shadow branch);
  * the shadow user asks for symbols only by dropping a text file into `<feed>/requests/`;
  * a firewall rule installed with the Gateway refuses every local user but `quantt` a connection
    to the API port (quantt/deploy/install_twin_vm.sh, THE GUARD), because file permissions alone
    do not stop a local process from opening a loopback socket.

WHAT IT READS
  * The symbols: every key of `targets` in each book's LATEST saved plan (`<state>/<D>/plan.json`
    with the greatest D; core, C4 and events, the twin's own book table), then the symbols in the
    request files. Every symbol must match `SYMBOL_RE`; the count is capped (`max_symbols`).
  * The session: Alpaca's calendar through the twin's `MarketData` (no order method), checked against
    the repo's NYSE calendar exactly as the twin checks it (`run.session_for`), so the feed and the
    twin agree on every session's close, early closes included.
  * Nothing of the twin's state but the Gateway lock (`config.gateway_lock_path`).

THE REQUEST FILES are written by another user, so each is treated as hostile: opened relative to the
directory's descriptor with O_NOFOLLOW (a symlink is refused, not followed), required to be a regular
file with one link, owned by the requests directory's owner (the shadow user, never the producer),
under `max_request_file_bytes`, ASCII, one ticker a line (`#` comments). A rejected line is named by
file and line number and its content is never echoed. File names must be `<slug>.txt`.

WHAT IT WRITES, per session `<feed>/<YYYY-MM-DD>/` (2750), never overwriting a file:
  bars-<run>.csv       every symbol's daily TRADES bars (regular hours), oldest first, with `source`
                       "ibkr" and `data_type` "historical" on every row. A bar dated after the last
                       COMPLETE session is dropped and counted: a session is complete from its close
                       + SETTLE (20 min: the 16:20 and 13:20 timers), so an intraday run carries no
                       partial bar (no lookahead in the data).
  quotes-<run>.csv     intraday runs only: bid, ask, last and close, each with its label (live, frozen,
                       delayed, delayed_frozen, unlabelled) and the tick type that carried it.
  manifest-<run>.json  written LAST: the files with their sha256, counts, every UNMEASURED symbol with
                       IBKR's codes and words, rejected requests, why a run stopped, IBKR's own
                       Gateway messages, and how many of the session's closes changed against the
                       session's previous run. A reader takes the newest manifest and checks the hashes.
IBKR's text is scrubbed of the account id before it is written; nothing written holds an account id,
order id or key.

THE TIMES (New York). Timers: `after-close` at 13:20 and 16:20, `evening` at 20:20, Monday to Friday.
  after-close  runs from the close + 20 min to the close + 60 min: on a 13:00 close the 13:20 fire runs
               and the 16:20 fire idles; on a 16:00 close the reverse.
  evening      runs from the close + 60 min, on a trading day; it re-reads the day (a bar IBKR
               revises after 16:20 is counted) and picks up requests the shadow runner wrote at 18:50.
  intraday     no timer: by hand only (run_twin.sh), from the open to the close; bars through the
               previous session and a quote capture.
NEVER INSIDE THE TWIN'S WINDOWS. The feed refuses to start, and stops asking, before any of these
(computed from quantt/twin/config.py for the session's own close AND both standard closes):
  the twin's send   close - 35 min to the freeze, close - 10 min: 15:25-15:50 and 12:25-12:50
  the twin's verify 17:40-17:55;  the twin's probes 09:00, 12:00, 15:15 (-3 / +5 min)
  the Gateway's daily restart 03:00 (-10 / +20 min)
It stops at the next window's start less (request timeout + spacing + 60 s), or after
`max_run_minutes`, whichever is first; the symbols not reached are UNMEASURED, named.

THE LOCK. The Gateway has one login session, and the twin and the feed must never be connected at
the same moment. Every IBKRClient the desk builds takes the flock on `<twin state>/.gateway.lock`
from connect to disconnect (quantt/broker/ibkr.py, THE SESSION LOCK). The twin's phases wait up to
`config.TWIN_LOCK_WAIT_S` for it; the feed never waits: if anyone holds the lock it stands down
(exit IDLE) without opening a socket. The windows above are the plan; the lock is the guarantee.

PACING. One historical request at a time, `request_spacing_s` apart (ops/twin/ibkr_feed.json, where
the IBKR limits and their sources are written). Each symbol is asked once a run. A pacing violation or
a dropped connection stops the run (`ibkr_market.FeedStop`); nothing is ever retried in a run.

WHAT IT NEVER DOES: place, cancel or modify an order; hold a trade client; write outside the feed
directory; read a key file (the IBKR account id comes from the unit's environment and is only compared
by the client, never printed); fill a missing value. DRY_RUN does not apply: there is nothing to send.

EXIT CODES: 0 every symbol measured; 3 PARTIAL (files written, some symbols UNMEASURED or the run
stopped); 5 IDLE (not this slot's time, a window, or the lock held); 11 REFUSED (a setting, a
directory or the Gateway); 20 FAIL (an error, with its traceback).
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import errno
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import traceback
from pathlib import Path
from typing import Callable

from quantt.twin import config

ENV_FEED_DIR = "QUANTT_IBKR_FEED_DIR"
SETTINGS_PATH = config.REPO / "ops" / "twin" / "ibkr_feed.json"
REQUESTS_DIR = "requests"
SLOTS = ("after-close", "evening", "intraday")

SETTLE = dt.timedelta(minutes=20)            # a session's bars are read as complete from close + 20 min
AFTER_CLOSE_SPAN = dt.timedelta(minutes=60)  # the after-close slot: close + 20 to close + 60
STANDARD_CLOSES = (dt.time(13, 0), dt.time(16, 0))
VERIFY_PAD = (dt.timedelta(minutes=5), dt.timedelta(minutes=10))
PROBE_PAD = (dt.timedelta(minutes=3), dt.timedelta(minutes=5))
GATEWAY_RESTART_ET = dt.time(3, 0)           # ibc_config AutoRestartTime (pinned by a test)
RESTART_PAD = (dt.timedelta(minutes=10), dt.timedelta(minutes=20))
MIN_RUN = dt.timedelta(minutes=2)

SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z])?$")
REQUEST_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}\.txt$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OWN_FILE = re.compile(r"^(bars|quotes|manifest)-\d{8}T\d{6}Z\.(csv|json)$")
FILE_MODE = 0o640
DIR_MODE = 0o2750

SOURCE = "ibkr"
LABEL = ("IBKR paper-account market data, read through a read-only client. Bars are IBKR's daily TRADES "
         "bars, not the official closing-auction print; quotes are labelled by the tick type that carried "
         "them. Data for research and shadow books, never evidence toward any live statistic.")
BARS_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "wap", "bar_count",
                "source", "data_type", "what_to_show", "use_rth", "bar_size", "fetched_utc")
QUOTE_COLUMNS = ("symbol", "captured_utc", "bid", "bid_type", "bid_tick", "ask", "ask_type", "ask_tick",
                 "last", "last_type", "last_tick", "close", "close_type", "close_tick",
                 "requested_market_data_type", "reported_market_data_type", "codes", "source")

EXIT_OK, EXIT_PARTIAL, EXIT_IDLE, EXIT_REFUSED, EXIT_FAIL = 0, 3, 5, 11, 20
EXIT_NAMES = {EXIT_OK: "OK", EXIT_PARTIAL: "PARTIAL", EXIT_IDLE: "IDLE", EXIT_REFUSED: "REFUSED",
              EXIT_FAIL: "FAIL"}


class FeedRefused(RuntimeError):
    """The feed will not run; the message names what was measured. Nothing was asked of IBKR."""


# ------------------------------------------------------------------ settings

@dataclasses.dataclass(frozen=True)
class FeedSettings:
    bar_duration: str
    request_spacing_s: float
    request_timeout_s: float
    quote_batch: int
    quote_wait_s: float
    market_data_type: int
    max_symbols: int
    max_request_files: int
    max_request_symbols: int
    max_request_file_bytes: int
    max_run_minutes: int
    keep_days: int

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def load_settings(path: Path = SETTINGS_PATH) -> FeedSettings:
    """Every key required, each range-checked; a missing or odd one refuses, naming it."""
    d = json.loads(Path(path).read_text())
    fields = [f.name for f in dataclasses.fields(FeedSettings)]
    missing = [k for k in fields if k not in d]
    if missing:
        raise FeedRefused(f"{path} has no {missing}")

    def num(k, lo, hi, integer=False):
        v = d[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi \
                or (integer and not isinstance(v, int)):
            raise FeedRefused(f"{path}: {k} {v!r} is not {'an integer' if integer else 'a number'} in [{lo}, {hi}]")
        return v

    if not isinstance(d["bar_duration"], str) or not re.fullmatch(r"[1-9][0-9]{0,3} [DWMY]", d["bar_duration"]):
        raise FeedRefused(f"{path}: bar_duration {d['bar_duration']!r} is not IBKR's '<n> <D|W|M|Y>'")
    # 600 s / 60 requests: the strictest IBKR family (ops/twin/ibkr_feed.json says why it binds here)
    s = FeedSettings(
        bar_duration=d["bar_duration"], request_spacing_s=float(num("request_spacing_s", 10, 120)),
        request_timeout_s=float(num("request_timeout_s", 5, 120)), quote_batch=num("quote_batch", 1, 90, True),
        quote_wait_s=float(num("quote_wait_s", 1, 60)), market_data_type=num("market_data_type", 1, 4, True),
        max_symbols=num("max_symbols", 1, 2000, True), max_request_files=num("max_request_files", 0, 200, True),
        max_request_symbols=num("max_request_symbols", 0, 2000, True),
        max_request_file_bytes=num("max_request_file_bytes", 64, 1 << 20, True),
        max_run_minutes=num("max_run_minutes", 1, 240, True), keep_days=num("keep_days", 1, 400, True))
    return s


# ------------------------------------------------------------------ deps

@dataclasses.dataclass
class FeedDeps:
    """Everything the run touches outside itself; tests pass fakes."""
    env: dict
    state: Path                                  # the twin's state directory (the lock only)
    feed: Path                                   # the feed directory the shadow user reads
    market: object                               # quantt.twin.market.MarketData (calendar only)
    read_client: Callable[[], object]            # -> an unconnected READ IBKRClient
    utcnow: Callable[[], dt.datetime] = dataclasses.field(
        default=lambda: dt.datetime.now(dt.timezone.utc))
    monotonic: Callable[[], float] = None
    wait: Callable[[float], None] | None = None  # None: the connected IB object's own sleep
    out: object = dataclasses.field(default_factory=lambda: sys.stdout)
    settings: FeedSettings = None
    producer_uid: int = dataclasses.field(default_factory=os.getuid)

    def __post_init__(self):
        if self.settings is None:
            self.settings = load_settings()
        if self.monotonic is None:
            import time
            self.monotonic = time.monotonic


def feed_dir_from_env(env) -> Path:
    v = env.get(ENV_FEED_DIR, "")
    if not v:
        raise FeedRefused(f"{ENV_FEED_DIR} is not set: it names the feed directory (no default)")
    return Path(v)


def check_feed_dir(feed: Path) -> os.stat_result:
    """The feed directory as the installer makes it: a real directory (never a symlink), setgid,
    no write for group or others, and a requests directory inside it. Returns its stat."""
    try:
        st = os.lstat(feed)
    except FileNotFoundError:
        raise FeedRefused(f"{feed} does not exist: run the installer (quantt/deploy/install_twin_vm.sh)") from None
    if not stat.S_ISDIR(st.st_mode):
        raise FeedRefused(f"{feed} is not a directory (a symlink is refused)")
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o022 or not mode & stat.S_ISGID:
        raise FeedRefused(f"{feed} has mode {oct(mode)}: it must be setgid with no group or other write "
                          f"(the installer makes it 2750)")
    if not (feed / REQUESTS_DIR).is_dir():
        raise FeedRefused(f"{feed / REQUESTS_DIR} is missing: run the installer")
    return st


# ------------------------------------------------------------------ times

@dataclasses.dataclass(frozen=True)
class Window:
    name: str
    start: dt.datetime
    end: dt.datetime


def windows(day: dt.date, close: dt.datetime) -> list:
    """The twin's windows on `day` (New York), as the module docstring lists them."""
    from quantt.session.gate import ET
    out = []
    closes = sorted({close} | {dt.datetime.combine(day, c, tzinfo=ET) for c in STANDARD_CLOSES})
    for c in closes:
        t = config.times(c)
        out.append(Window(f"twin send ({c:%H:%M} close)", t["slots"][0] - config.SLOT_SLACK, t["freeze"]))
    v = dt.datetime.combine(day, config.VERIFY_ET, tzinfo=ET)
    out.append(Window("twin verify", v - VERIFY_PAD[0], v + VERIFY_PAD[1]))
    for p in config.PROBE_ET:
        pt = dt.datetime.combine(day, p, tzinfo=ET)
        out.append(Window(f"twin probe {p:%H:%M}", pt - PROBE_PAD[0], pt + PROBE_PAD[1]))
    for d in (day, day + dt.timedelta(days=1)):
        r = dt.datetime.combine(d, GATEWAY_RESTART_ET, tzinfo=ET)
        out.append(Window("Gateway daily restart", r - RESTART_PAD[0], r + RESTART_PAD[1]))
    return sorted(out, key=lambda w: w.start)


def deadline(now: dt.datetime, wins: list, settings: FeedSettings) -> tuple:
    """(the time the feed must stop asking by, why). Raises nothing; the caller checks the slack."""
    margin = dt.timedelta(seconds=settings.request_timeout_s + settings.request_spacing_s + 60)
    cap = now + dt.timedelta(minutes=settings.max_run_minutes)
    nxt = [w for w in wins if w.start > now]
    if nxt and nxt[0].start - margin < cap:
        return nxt[0].start - margin, f"{nxt[0].name} opens {nxt[0].start:%H:%M} ET"
    return cap, f"max_run_minutes ({settings.max_run_minutes})"


# ------------------------------------------------------------------ symbols

def books_universe(states: dict) -> tuple:
    """(sorted symbols, {book: note}, [rejections]) from each book's latest saved plan's targets."""
    syms, notes, rejected = set(), {}, []
    for name, state in states.items():
        days = sorted(d.name for d in Path(state).iterdir()
                      if d.is_dir() and _DAY.match(d.name) and (d / "plan.json").is_file())
        if not days:
            notes[name] = {"plan": None, "symbols": 0, "note": "no saved plan"}
            continue
        p = Path(state) / days[-1] / "plan.json"
        try:
            plan = json.loads(p.read_text())
        except ValueError:
            notes[name] = {"plan": f"{days[-1]}/plan.json", "symbols": 0, "note": "not JSON; nothing read"}
            continue
        if plan.get("book") != name or not isinstance(plan.get("targets"), dict):
            notes[name] = {"plan": f"{days[-1]}/plan.json", "symbols": 0,
                           "note": f"book {plan.get('book')!r} or targets not as written by {name}; nothing read"}
            continue
        n = 0
        for s in sorted(plan["targets"]):
            if isinstance(s, str) and SYMBOL_RE.match(s):
                syms.add(s)
                n += 1
            else:
                rejected.append({"from": f"{name} {days[-1]}/plan.json", "reason": "not a ticker the feed maps"})
        notes[name] = {"plan": f"{days[-1]}/plan.json", "symbols": n, "note": ""}
    return sorted(syms), notes, rejected


def _shown(name: str) -> str:
    return name if re.fullmatch(r"[\x21-\x7e]{1,80}", name) else "<name not shown>"


def read_requests(req_dir: Path, settings: FeedSettings, *, producer_uid: int) -> dict:
    """{"symbols", "files", "rejected", "ignored"} from the request files, read as hostile input
    (module docstring, THE REQUEST FILES). A directory that is not as installed yields no symbols
    and one rejection saying why; it never stops the books' symbols being fetched."""
    out = {"symbols": [], "files": [], "rejected": [], "ignored": 0}
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        dfd = os.open(req_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        out["rejected"].append({"file": REQUESTS_DIR, "reason": f"cannot open the requests directory ({type(e).__name__})"})
        return out
    try:
        dst = os.fstat(dfd)
        if dst.st_uid == producer_uid:
            out["rejected"].append({"file": REQUESTS_DIR, "reason": "the requests directory is the producer's own; "
                                    "it must belong to the shadow user (re-run the installer)"})
            return out
        if stat.S_IMODE(dst.st_mode) & 0o002:
            out["rejected"].append({"file": REQUESTS_DIR, "reason": "the requests directory is world-writable"})
            return out
        seen = set()
        for name in sorted(os.listdir(dfd)):
            if name.startswith("."):
                out["ignored"] += 1                # a writer's temporary file
                continue
            if not REQUEST_NAME_RE.match(name):
                out["rejected"].append({"file": _shown(name), "reason": "file name is not <slug>.txt"})
                continue
            if len(out["files"]) >= settings.max_request_files:
                out["rejected"].append({"file": name, "reason": f"over the cap of {settings.max_request_files} files"})
                continue
            try:
                fd = os.open(name, flags, dir_fd=dfd)
            except OSError as e:
                out["rejected"].append({"file": name, "reason": "a symbolic link" if e.errno == errno.ELOOP else
                                        f"cannot be opened ({type(e).__name__})"})
                continue
            try:
                st = os.fstat(fd)
                why = None
                if not stat.S_ISREG(st.st_mode):
                    why = "not a regular file"
                elif st.st_nlink != 1:
                    why = f"has {st.st_nlink} links"
                elif st.st_uid != dst.st_uid:
                    why = "not owned by the requests directory's owner"
                elif st.st_size > settings.max_request_file_bytes:
                    why = f"over {settings.max_request_file_bytes} bytes"
                if why:
                    out["rejected"].append({"file": name, "reason": why})
                    continue
                data = os.read(fd, settings.max_request_file_bytes + 1)
            finally:
                os.close(fd)
            if len(data) > settings.max_request_file_bytes:
                out["rejected"].append({"file": name, "reason": f"over {settings.max_request_file_bytes} bytes"})
                continue
            try:
                text = data.decode("ascii")
            except UnicodeDecodeError:
                out["rejected"].append({"file": name, "reason": "not ASCII text"})
                continue
            out["files"].append(name)
            for i, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if not SYMBOL_RE.match(s):
                    out["rejected"].append({"file": name, "line": i, "reason": "not a ticker (one per line, "
                                            "[A-Z]{1,5} with an optional .[A-Z] class)"})
                    continue
                if s in seen:
                    continue
                if len(seen) >= settings.max_request_symbols:
                    out["rejected"].append({"file": name, "line": i,
                                            "reason": f"over the cap of {settings.max_request_symbols} requested symbols"})
                    continue
                seen.add(s)
        out["symbols"] = sorted(seen)
        return out
    finally:
        os.close(dfd)


def order_symbols(book_syms: list, request_syms: list, cap: int) -> tuple:
    """(symbols to ask, in order: the books' first, then requests not already there; those over the cap)."""
    allsyms = list(book_syms) + [s for s in request_syms if s not in set(book_syms)]
    return allsyms[:cap], allsyms[cap:]


# ------------------------------------------------------------------ files

def _write(path: Path, data: bytes, *, gid: int) -> None:
    """Temp file at FILE_MODE beside `path`, fsync, then link it into place: never over an existing
    file. Refuses unless the result carries the feed directory's group and FILE_MODE."""
    if path.exists():
        raise FeedRefused(f"{path} exists; a feed file is never rewritten")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        os.fchmod(fd, FILE_MODE)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.link(tmp, path)            # fails if `path` appeared meanwhile
    os.unlink(tmp)
    st = os.stat(path)
    if st.st_gid != gid or stat.S_IMODE(st.st_mode) != FILE_MODE:
        raise FeedRefused(f"{path}: group {st.st_gid} mode {oct(stat.S_IMODE(st.st_mode))}, not {gid} and "
                          f"{oct(FILE_MODE)}: the feed directory must be setgid to the reader's group")


def session_dir(feed: Path, day: dt.date, gid: int) -> Path:
    d = feed / day.isoformat()
    if not os.path.lexists(d):
        os.mkdir(d, DIR_MODE)
        os.chmod(d, DIR_MODE)
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_gid != gid or stat.S_IMODE(st.st_mode) != DIR_MODE:
        raise FeedRefused(f"{d} is not a {oct(DIR_MODE)} directory of the feed's group")
    return d


def _csv(columns, rows) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r[k]) for k in columns})
    return buf.getvalue().encode()


def prune(feed: Path, today: dt.date, keep_days: int) -> list:
    """Remove the producer's own files from session directories older than `keep_days`, then the
    directory if it is empty. Anything else in one is left, and said."""
    notes = []
    floor = (today - dt.timedelta(days=keep_days)).isoformat()
    for d in sorted(feed.iterdir()):
        if not (_DAY.match(d.name) and d.name < floor) or d.is_symlink() or not d.is_dir():
            continue
        for f in d.iterdir():
            if _OWN_FILE.match(f.name) and f.is_file() and not f.is_symlink():
                f.unlink()
        try:
            d.rmdir()
        except OSError:
            notes.append(f"{d.name}: kept, it holds files the feed did not write")
    return notes


def latest_manifest(day_dir: Path, before: str | None = None) -> tuple:
    """(stamp, manifest) of the newest manifest in a session directory, older than `before` if given."""
    got = sorted(f.name for f in day_dir.iterdir() if re.match(r"^manifest-\d{8}T\d{6}Z\.json$", f.name))
    if before is not None:
        got = [g for g in got if g[len("manifest-"):-len(".json")] < before]
    if not got:
        return None, None
    name = got[-1]
    return name[len("manifest-"):-len(".json")], json.loads((day_dir / name).read_text())


def revision(day_dir: Path, stamp: str, session: dt.date, rows: list) -> dict | None:
    """How many of `session`'s closes changed against that session's previous run (the 16:20 bar
    against the 20:20 one): a measurement of whether IBKR's after-close bar is final."""
    prev_stamp, prev = latest_manifest(day_dir, before=stamp)
    if prev is None or not (prev.get("files") or {}).get("bars"):
        return None
    name = prev["files"]["bars"]["name"]
    old = {}
    with open(day_dir / name, newline="") as f:
        for r in csv.DictReader(f):
            if r["date"] == session.isoformat():
                old[r["symbol"]] = float(r["close"])
    new = {r["symbol"]: r["close"] for r in rows if r["date"] == session}
    both = sorted(set(old) & set(new))
    return {"previous_run": prev_stamp, "compared": len(both),
            "changed_close": sum(1 for s in both if old[s] != new[s])}


# ------------------------------------------------------------------ the run

KEY_GLOB = "/run/quantt-*"       # every runtime key or login directory but the core's /run/quantt (header)


def sandbox_problems(feed: Path, states: dict, key_glob: str = KEY_GLOB) -> list:
    """What the unit's sandbox must guarantee and here does not (the C4 feed's check, RUNBOOK 8.15):
    the requests directory or a book's state writable, or a key or login directory reachable."""
    import glob
    bad = []
    if os.access(feed / REQUESTS_DIR, os.W_OK):
        bad.append(f"{feed / REQUESTS_DIR} is writable")
    for name, st in sorted(states.items()):
        if os.access(st, os.W_OK):
            bad.append(f"book {name}'s state {st} is writable")
    keys = sorted(p for p in glob.glob(key_glob) if os.access(p, os.R_OK) or os.access(p, os.X_OK))
    if keys:
        bad.append(f"runtime directories that hold keys or logins are reachable: {keys}")
    return bad


def run(deps: FeedDeps, *, slot: str, require_sandbox: bool = False) -> int:
    from quantt.broker.ibkr import IBKRError
    from quantt.session import records as rec
    from quantt.twin import books
    from quantt.twin.books import TwinRefused
    try:
        if require_sandbox:
            bad = sandbox_problems(Path(deps.feed), books.book_states(deps.env))
            if bad:
                raise FeedRefused("not inside the sandbox its unit sets: " + "; ".join(bad))
        return _run(deps, slot)
    except (FeedRefused, TwinRefused, config.ConfigError, rec.StateDirError, IBKRError) as e:
        print(f"REFUSED feed: {type(e).__name__}: {e}", file=deps.out)
        print(f"exit {EXIT_REFUSED} {EXIT_NAMES[EXIT_REFUSED]}", file=deps.out)
        return EXIT_REFUSED
    except Exception as e:  # noqa: BLE001 -- reported with its traceback, exit FAIL
        print(f"FAIL feed: {type(e).__name__}: {e}", file=deps.out)
        print(traceback.format_exc(), file=deps.out)
        print(f"exit {EXIT_FAIL} {EXIT_NAMES[EXIT_FAIL]}", file=deps.out)
        return EXIT_FAIL


def _idle(deps, why: str) -> int:
    print(f"feed: {why}; nothing asked", file=deps.out)
    print(f"exit {EXIT_IDLE} {EXIT_NAMES[EXIT_IDLE]}", file=deps.out)
    return EXIT_IDLE


def _run(deps: FeedDeps, slot: str) -> int:
    from quantt.broker.ibkr import GatewayBusy, NotConnected, WrongAccount
    from quantt.broker import ibkr_market as M
    from quantt.session.gate import ET
    from quantt.twin import books
    from quantt.twin.run import session_for

    if slot not in SLOTS:
        raise FeedRefused(f"slot {slot!r} is not one of {SLOTS}")
    s = deps.settings
    config.gateway_lock_path(deps.state)                 # refuses a state directory that is not the twin's
    if not Path(deps.state).is_dir():
        raise FeedRefused(f"the twin's state directory {deps.state} does not exist")
    fst = check_feed_dir(Path(deps.feed))
    feed, gid = Path(deps.feed), fst.st_gid

    started = deps.utcnow()
    now = started.astimezone(ET)
    today = now.date()
    row, prev = session_for(deps.market, today)
    if row is None:
        return _idle(deps, f"{today} is not a trading day")
    close = config.close_et(today, row["close"])
    opens = config.close_et(today, row["open"])
    if slot == "after-close" and not (close + SETTLE <= now < close + AFTER_CLOSE_SPAN):
        return _idle(deps, f"{now:%H:%M} ET is not the after-close slot for a {row['close']} close "
                           f"({close + SETTLE:%H:%M}-{close + AFTER_CLOSE_SPAN:%H:%M})")
    if slot == "evening" and not now >= close + AFTER_CLOSE_SPAN:
        return _idle(deps, f"{now:%H:%M} ET is before the evening slot ({close + AFTER_CLOSE_SPAN:%H:%M} on)")
    if slot == "intraday" and not (opens <= now < close):
        return _idle(deps, f"{now:%H:%M} ET is outside the session ({row['open']}-{row['close']})")
    complete_through = prev if slot == "intraday" else today
    wins = windows(today, close)
    inside = [w for w in wins if w.start <= now < w.end]
    if inside:
        return _idle(deps, f"{now:%H:%M} ET is inside the {inside[0].name} window "
                           f"({inside[0].start:%H:%M}-{inside[0].end:%H:%M})")
    stop_at, stop_why = deadline(now, wins, s)
    if stop_at - now < MIN_RUN:
        return _idle(deps, f"too close to the next window ({stop_why})")

    book_syms, book_notes, book_rejected = books_universe(books.book_states(deps.env))
    req = read_requests(feed / REQUESTS_DIR, s, producer_uid=deps.producer_uid)
    asked, over_cap = order_symbols(book_syms, req["symbols"], s.max_symbols)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    manifest = {"version": 1, "label": LABEL, "producer": "quantt.twin.feed", "session": today.isoformat(),
                "slot": slot, "run": stamp, "started_utc": started.isoformat(), "close_et": close.isoformat(),
                "complete_through": complete_through.isoformat() if complete_through else None,
                "settings": s.to_dict(), "requested_market_data_type": None,
                "symbols": {"asked": len(asked), "from_books": {b: n["symbols"] for b, n in book_notes.items()},
                            "from_requests": len([x for x in req["symbols"] if x not in set(book_syms)]),
                            "over_cap": over_cap},
                "books": book_notes, "requests": {"files": req["files"], "rejected": book_rejected + req["rejected"],
                                                  "ignored": req["ignored"]},
                "stop_by": {"at": stop_at.isoformat(), "why": stop_why}, "files": {"bars": None, "quotes": None},
                "unmeasured": [{"symbol": x, "what": "bars", "reason": f"over the cap of {s.max_symbols} symbols",
                                "codes": [], "messages": []} for x in over_cap],
                "stopped": None, "gateway_messages": [], "measured": {"bars": 0, "quotes": 0},
                "quote_labels": {}, "dropped_partial_bars": 0, "no_bar_for_session": 0, "revision": None}

    client = deps.read_client()
    if getattr(client, "mode", None) != "read":
        raise FeedRefused("the feed was handed a client that is not in read mode; it never holds a trade client")
    try:
        client.connect()
    except GatewayBusy as e:
        return _idle(deps, f"the Gateway session lock is held ({e})")
    except (NotConnected, WrongAccount) as e:
        manifest["stopped"] = f"gateway: {type(e).__name__}: {e}"
        manifest["unmeasured"] += [{"symbol": x, "what": "bars", "reason": "not asked: the Gateway could not be "
                                    "reached or is not logged in", "codes": [], "messages": []} for x in asked]
        _finish(deps, feed, gid, today, stamp, manifest, [], [])
        print(f"REFUSED feed [gateway]: {e}", file=deps.out)
        print(f"exit {EXIT_REFUSED} {EXIT_NAMES[EXIT_REFUSED]}", file=deps.out)
        return EXIT_REFUSED
    acct = client.config.account
    scrub = (lambda t: t.replace(acct, "<account>"))
    bars_rows, quote_rows, gaps, not_asked = [], [], [], []
    try:
        wait = deps.wait if deps.wait is not None else client.ib.sleep
        pacer = M.Pacer(s.request_spacing_s, monotonic=deps.monotonic, wait=wait)
        with M.MarketReader(client, pacer=pacer, request_timeout_s=s.request_timeout_s, scrub=scrub, wait=wait,
                            utcnow=deps.utcnow) as mr:
            try:
                for i, sym in enumerate(asked):
                    if deps.utcnow().astimezone(ET) >= stop_at:
                        manifest["stopped"] = f"deadline {stop_at:%H:%M:%S} ET ({stop_why})"
                        not_asked = asked[i:]
                        break
                    r = mr.daily_bars(sym, s.bar_duration, before=lambda: deps.utcnow().astimezone(ET) < stop_at)
                    if isinstance(r, M.Gap):
                        gaps.append(r)
                        continue
                    at = deps.utcnow().isoformat()
                    kept = [b for b in r.rows if b["date"] <= complete_through]
                    if any(b["date"] > today for b in r.rows):
                        gaps.append(M.Gap(sym, "bars", "IBKR sent a bar dated after today", r.messages))
                        continue
                    manifest["dropped_partial_bars"] += len(r.rows) - len(kept)
                    if not kept:
                        gaps.append(M.Gap(sym, "bars", "no complete bar", r.messages))
                        continue
                    if kept[-1]["date"] != complete_through:
                        manifest["no_bar_for_session"] += 1
                    for b in kept:
                        bars_rows.append({**b, "source": SOURCE, "data_type": M.BAR_LABEL,
                                          "what_to_show": M.WHAT_TO_SHOW, "use_rth": int(M.USE_RTH),
                                          "bar_size": M.BAR_SIZE, "fetched_utc": at})
                if slot == "intraday" and manifest["stopped"] is None:
                    mr.set_market_data_type(s.market_data_type)
                    manifest["requested_market_data_type"] = s.market_data_type
                    q, qg = mr.quotes(asked, batch=s.quote_batch, stream_s=s.quote_wait_s,
                                      before=lambda: deps.utcnow().astimezone(ET) < stop_at)
                    quote_rows, gaps = [{**x, "source": SOURCE} for x in q], gaps + qg
            except M.FeedStop as e:
                manifest["stopped"] = (f"deadline {stop_at:%H:%M:%S} ET ({stop_why})" if isinstance(e, M.Deadline)
                                       else f"{type(e).__name__}: {e}")
                done = {b["symbol"] for b in bars_rows} | {g.symbol for g in gaps}
                not_asked = [x for x in asked if x not in done]
            manifest["gateway_messages"] = _dedup([m.to_dict() for m in mr.messages if m.ib_symbol is None])
    finally:
        client.disconnect()

    for x in not_asked:
        gaps.append(M.Gap(x, "bars", f"not measured: the run stopped ({manifest['stopped']})"))
    manifest["unmeasured"] += [g.to_dict() for g in gaps if g.what != "bars" or g.symbol not in
                               {b["symbol"] for b in bars_rows}]
    manifest["measured"] = {"bars": len({b["symbol"] for b in bars_rows}),
                            "quotes": len({q["symbol"] for q in quote_rows})}
    labels: dict = {}
    for q in quote_rows:
        for f in M.QUOTE_FIELDS:
            if q.get(f + "_type"):
                labels[q[f + "_type"]] = labels.get(q[f + "_type"], 0) + 1
    manifest["quote_labels"] = dict(sorted(labels.items()))
    _finish(deps, feed, gid, today, stamp, manifest, bars_rows, quote_rows)
    notes = prune(feed, today, s.keep_days)
    n_un = len(manifest["unmeasured"])
    print(f"feed {slot} {today}: bars for {manifest['measured']['bars']} of {len(asked) + len(over_cap)} symbol(s)"
          f" ({n_un} UNMEASURED); quotes for {manifest['measured']['quotes']}"
          f"{'; labels ' + json.dumps(manifest['quote_labels']) if quote_rows else ''}; "
          f"{len(req['rejected']) + len(book_rejected)} rejected request line(s)"
          + (f"; STOPPED: {manifest['stopped']}" if manifest["stopped"] else ""), file=deps.out)
    for n in notes:
        print(f"  prune: {n}", file=deps.out)
    code = EXIT_OK if not n_un and manifest["stopped"] is None else EXIT_PARTIAL
    print(f"exit {code} {EXIT_NAMES[code]}", file=deps.out)
    return code


def _dedup(msgs: list) -> list:
    out, seen = [], set()
    for m in msgs:
        k = (m["code"], m["text"])
        if k not in seen:
            seen.add(k)
            out.append(m)
    return out[:20]


def _finish(deps, feed: Path, gid: int, today: dt.date, stamp: str, manifest: dict, bars_rows: list,
            quote_rows: list) -> None:
    """The data files first, the manifest LAST, so a reader never finds a manifest naming a file that
    is not complete."""
    d = session_dir(feed, today, gid)
    if bars_rows:
        rows = sorted(bars_rows, key=lambda r: (r["symbol"], r["date"]))
        manifest["revision"] = revision(d, stamp, today, rows)
        data = _csv(BARS_COLUMNS, [{**r, "date": r["date"].isoformat()} for r in rows])
        name = f"bars-{stamp}.csv"
        _write(d / name, data, gid=gid)
        manifest["files"]["bars"] = {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                                     "rows": len(rows), "symbols": len({r["symbol"] for r in rows})}
    if quote_rows:
        data = _csv(QUOTE_COLUMNS, sorted(quote_rows, key=lambda r: r["symbol"]))
        name = f"quotes-{stamp}.csv"
        _write(d / name, data, gid=gid)
        manifest["files"]["quotes"] = {"name": name, "sha256": hashlib.sha256(data).hexdigest(),
                                       "bytes": len(data), "rows": len(quote_rows)}
    manifest["finished_utc"] = deps.utcnow().isoformat()
    _write(d / f"manifest-{stamp}.json", (json.dumps(manifest, indent=1, sort_keys=True, default=str) + "\n").encode(),
           gid=gid)
