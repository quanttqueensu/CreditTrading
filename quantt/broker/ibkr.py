"""The IBKR paper client for the twin runner: reads one paper account, sends one kind of order.

WHY THIS EXISTS, AND WHY IT IS THIS SMALL
-----------------------------------------
The team lead ruled on 2026-11-25 that the three Alpaca paper books move to IBKR paper so that
their orders are MOC, each first trading as an IBKR "twin" beside its Alpaca book
(`results/ops/IBKR_PAPER_MOVE_2026-11-25.md`, on its own branch). This module is the twin's only
door to IBKR, as `quantt/broker/alpaca.py` is the Alpaca books' door: it turns the TWS API's
objects into checked Python and back, decides nothing, and refuses every shape it was not built
for. The twin runner (`quantt/twin/`) decides what to send and whether the gates allow it.

It is a PORT, not a revival. The archived adapter (`git show pre-clean-slate:_archive/src/deploy/
broker/ibkr.py`, 2,144 lines) carried a shadow ledger, `arm()`, per-sleeve attribution by
`orderRef`, bonds, options and combos. The 2026-09 halts came from those parts, and the Alpaca
design removed them ("the broker is the fact"). Kept, with their incidents: the MOC order shape,
the lazy library import, the all-client open-order read, the permId record, and the refusal to
treat "could not ask" as "nothing there". Dropped: the `ib_insync` fallback, `IBKRConfig.from_env`'s
defaults, the shadow ledger and `arm()` (results/ops/IBKR_SECOND_BROKER_2026-10-19.md §3).

INCIDENTS THIS MODULE CARRIES
-----------------------------
  * 2026-07-31, the stack. Four armed runs stacked 79 MOC orders that were "invisible because
    `openTrades()` returns only the querying client's orders" (archived INFRASTRUCTURE §5.4). So
    `open_orders` asks `reqAllOpenOrders()` AND `openTrades()` and keeps the union: a trade missing
    from one and present in the other is still a trade. A query that raises is not an empty answer
    (`OpenOrdersUnknown`).
  * 2026-07-31, overnight market orders realised 100.5bp against a 32.6bp breakeven (CLAUDE.md
    order-path rule 3). There is no market order here: `place_moc` builds `orderType="MOC"`,
    `tif="DAY"` and nothing else. IBKR rejects an MOC with an empty TIF (archived `_order`).
  * The silent default. The archived `IBKRConfig.from_env` read `config/.env` itself and defaulted
    every missing value (port 4002, client id 17): on one day the default won while TWS listened on
    7497, and every run died. Here host, port, client id and the expected account id are REQUIRED
    environment variables (`IBKRConfig.from_env`), and a missing one raises naming the variable.
  * `orderRef` came back '' on all 257 executions of 2026-07-31 [V, archived broker_fills.csv], and
    IBKR documents it as "Intended for institutional customers only" [V, October §2.3]. It is still
    SET on every order (the twin's order id), but nothing here relies on it alone: every placement
    returns `client_id`, `order_id` and `perm_id`, and the runner records all four.
  * permId is assigned asynchronously; the archive's rows all carried 0 because it was read once at
    placement. `place_moc` waits for the acknowledgement and returns what has arrived.

WHAT IT WILL NOT DO
-------------------
  * Connect to a live port. `PAPER_PORTS` holds the paper defaults (Gateway 4002, TWS 7497) and
    nothing else; the constructor raises on any other port, and `quantt/tests/test_ibkr_client.py`
    fails if a live port (4001, 7496) is ever accepted. A port is not proof of paper on its own, so
    the expected account id must also look like a paper account (`PAPER_ACCOUNT_PREFIX`, [U]) and
    must be one of the Gateway's `managedAccounts()` at connect.
  * Print the account id. It is compared, never shown: not in `repr`, not in an exception, not in a
    return value. A mismatch says "the expected paper account is not among the N accounts this
    login manages".
  * Send anything but MOC, a fractional or non-positive quantity, or a symbol outside the US-stock
    pattern; place or cancel on a client built read-only (`ReadOnlyClient`): the probe, verify and
    every dry run use one. That mode check IS the guard. `readonly=True` is also passed to ib_async
    for a read client, but it is not a lock at the Gateway: the Gateway's own Read-Only API setting
    is off (the send must place; quantt/deploy/ibc_config.py), and ib_async's `placeOrder` has no
    read-only check of its own [S: October §2.4].
  * Retry a placement. One `placeOrder` per call. An order the Gateway has not acknowledged within
    `ACK_WAIT_S` is returned as `accepted=None` (ambiguous) and the runner stops the batch; it is
    never placed again (CLAUDE.md order-path rule 2: the broker does not dedupe).

THE LIBRARY. `ib_async` only, imported inside `connect` (CLAUDE.md landmine 10: bare `ib_insync`
hangs forever on Python 3.12+). Tests pass a stub module as `ib_module`, so nothing imports the
library and no socket opens (root conftest.py, ops/netguard.py).

THE SESSION LOCK (added 2026-11-25 for B10, the IBKR market-data feed, quantt/twin/feed.py). The
Gateway serves the twin's send, verify and probe AND, since B10, a read-only feed producer. They
must never be connected at the same moment (the contract: one Gateway session, one weekly login,
and a feed that cannot slow or confuse a send). So a client built with `session_lock=<path>` takes
an exclusive `flock` on that file BEFORE `ib.connect` and holds it until `disconnect` (or the
process's end: the kernel drops it on a crash). A second client waits up to `lock_wait_s`, then
raises `GatewayBusy` (a `NotConnected`: the caller's existing "Gateway down" path) WITHOUT opening
a socket. Every client the desk builds passes the same path, `quantt.twin.config.gateway_lock_path`
(the twin's state directory's `.gateway.lock`); quantt/twin/tests/test_feed_lock.py fails if a
non-test IBKRClient is ever built without one. `session_lock=None` keeps the old behaviour, which
only the client's own unit tests use. The lock is a flock on the twin's own 0700 state, so only
user quantt can take it: the shadow user cannot hold the Gateway hostage.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import fcntl
import math
import os
import re
import time
from pathlib import Path
from typing import Callable

# The paper API ports and nothing else: IB Gateway paper 4002, TWS paper 7497 [S: IBKR's API
# settings defaults, archived ibkr.py RUNBOOK; October §2.9]. Live is 4001 / 7496.
PAPER_PORTS = frozenset({4002, 7497})
LIVE_PORTS = frozenset({4001, 7496})
assert not PAPER_PORTS & LIVE_PORTS

# IBKR paper account ids begin "D" (individual paper accounts read "DU..." in every IBKR-era record
# this desk kept) [U: not re-read from an IBKR page in this build, which had no network]. A check
# that fails closed: an expected id that does not start so is refused before any connection. If an
# IBKR page shows otherwise, change this constant with its source; never remove the check.
PAPER_ACCOUNT_PREFIX = "D"

ENV_HOST = "QUANTT_IBKR_HOST"
ENV_PORT = "QUANTT_IBKR_PORT"
ENV_CLIENT_ID = "QUANTT_IBKR_CLIENT_ID"
ENV_ACCOUNT = "QUANTT_IBKR_ACCOUNT"
REQUIRED_ENV = (ENV_HOST, ENV_PORT, ENV_CLIENT_ID, ENV_ACCOUNT)

CONNECT_TIMEOUT_S = 20
# EVERY BLOCKING REQUEST IS BOUNDED (final review, 2026-11-25, a blocker for arming). ib_async 2.1.0's
# `IB.RequestTimeout` defaults to 0, "wait indefinitely" [V: the installed library's IB docstring,
# 2026-11-25]. A half-alive Gateway that never answers `reqAllOpenOrders`, `accountSummary` or
# `reqExecutions` would then hold the Gateway session lock for ever, and the 12:30 and 12:40 sends
# would each wait their 90 s for it and refuse: a missed session nobody caused. So every client sets
# `ib.RequestTimeout` to this before it connects; a request still unanswered then raises
# `RequestTimedOut`, and the client DISCONNECTS at once, which releases the lock. 30 s: a healthy
# Gateway answers these in well under a second [U: no timing measured on this account yet; the first
# probes record their durations], and one hung request plus the drop must fit inside the send's 90 s
# wait for the lock (quantt/twin/config.py TWIN_LOCK_WAIT_S). The units' own run-time limits
# (install_twin_vm.sh, TimeoutStartSec) are the second bound, for anything that is not a request.
REQUEST_TIMEOUT_S = 30.0
LOCK_POLL_S = 0.5            # how often a waiting client re-tries the session lock (no socket meanwhile)
# How long `place_moc` waits for the Gateway to say what it did with an order. Measured on nothing
# yet: the IBKR-era record kept no acknowledgement times. The read-only week and the first armed
# sends measure it (`ack_s` in the runner's order log).
ACK_WAIT_S = 10.0
ACK_POLL_S = 0.1

# ib_async 2.1.0's OrderStatus.DoneStates, measured 2026-09-13 and again on this machine 2026-11-25:
# {Filled, Cancelled, ApiCancelled, Inactive}. `Inactive` IS done: IB defines it as received but no
# longer active because it was rejected or cancelled (archived pending_orders.py; pinned by
# quantt/tests/test_ibkr_client.py against the installed library).
DONE_STATUSES = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})
ACCEPTED_STATUSES = frozenset({"PreSubmitted", "Submitted", "Filled"})
REJECTED_STATUSES = frozenset({"Cancelled", "ApiCancelled", "Inactive"})

# A WARNING IS NOT A REJECTION (release check of 8f9d026, 2026-11-26). ib_async 2.1.0's `Wrapper.error`
# treats these codes as warnings: it sets the trade's status to "ValidationError" and KEEPS the trade,
# "because the order is STILL LIVE at the broker" (404: shares for a short are not immediately
# available; the order is held while IBKR locates them) [V: ib_async/wrapper.py `error`, the installed
# 2.1.0, read 2026-11-26]. Any other error code on an order makes ib_async set it Cancelled, which is
# REJECTED_STATUSES here. So a ValidationError, or one of these codes in the trade's log, never refuses
# an order: place_moc re-asks the Gateway for its open orders, and an order found there is live.
# Exceptions ib_async itself makes (110 on a PendingSubmit order, or on a what-if request) arrive as
# Cancelled and are refusals through that status. Pinned against the installed library by a test.
IB_WARNING_CODES = frozenset({105, 110, 165, 321, 329, 399, 404, 434, 492, 10167})
IB_WARNING_RANGE = (2100, 2200)              # 2100 <= code < 2200
VALIDATION_ERROR = "ValidationError"


def is_ib_warning(code) -> bool:
    return isinstance(code, int) and (code in IB_WARNING_CODES or IB_WARNING_RANGE[0] <= code < IB_WARNING_RANGE[1])

# US equity symbols as the books write them (PDI, BRK.B). IBKR writes a share class with a space
# ("BRK B") [U: the convention of IBKR's contract search; no book traded one at IBKR], so the two
# spellings are mapped here and nowhere else.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_ACCOUNT_RE = re.compile(r"^[A-Z0-9]{3,20}$")
_ORDER_REF_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class IBKRError(RuntimeError):
    """Base for everything this client raises. Messages never hold the account id."""


class MissingSetting(IBKRError):
    """A required environment variable is unset or unreadable; names the variable, never a value."""


class NotPaper(IBKRError):
    """The port or the account is not a paper one."""


class WrongAccount(IBKRError):
    """The Gateway's login does not manage the expected paper account."""


class NotConnected(IBKRError):
    """The Gateway could not be reached or is not logged in (the twin's MISSED session)."""


class RequestTimedOut(NotConnected):
    """A blocking request got no answer within REQUEST_TIMEOUT_S; the session was dropped and the
    Gateway session lock released. Named, so a hung Gateway is never read as an empty answer."""


class GatewayBusy(NotConnected):
    """Another of this desk's processes holds the Gateway session lock; no socket was opened."""


class ReadOnlyClient(IBKRError):
    """A read-only client was asked to place or cancel."""


class UnexpectedReply(IBKRError):
    """The API answered with a shape this client was not built for. Raised instead of guessing."""


class OpenOrdersUnknown(IBKRError):
    """The open-order question could not be answered. Not knowing is not "nothing resting"."""


def to_ib_symbol(sym: str) -> str:
    if not isinstance(sym, str) or not _SYMBOL_RE.match(sym):
        raise ValueError(f"symbol {sym!r} is not an upper-case US equity symbol")
    return sym.replace(".", " ")


def from_ib_symbol(s: str) -> str:
    out = str(s).strip().replace(" ", ".")
    if not _SYMBOL_RE.match(out):
        raise UnexpectedReply(f"IBKR symbol {s!r} is not one this client maps")
    return out


@dataclasses.dataclass(frozen=True)
class IBKRConfig:
    """Where the Gateway is and which paper account it must be. Every field is required.

    The host and port are configuration, not code, so a Gateway moved to a second free-size VM
    (the fallback the team lead named on 2026-11-25) needs only the unit's environment changed.
    The account id is kept out of `repr` and every message."""
    host: str
    port: int
    client_id: int
    account: str = dataclasses.field(repr=False)

    def __post_init__(self):
        if not isinstance(self.host, str) or not self.host or any(c.isspace() for c in self.host):
            raise MissingSetting(f"{ENV_HOST} must be a host name or address")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise MissingSetting(f"{ENV_PORT} must be an integer port")
        if self.port in LIVE_PORTS:
            raise NotPaper(f"port {self.port} is a LIVE IBKR API port; this client connects to the "
                           f"paper ports {sorted(PAPER_PORTS)} only")
        if self.port not in PAPER_PORTS:
            raise NotPaper(f"port {self.port} is not a paper API port {sorted(PAPER_PORTS)}; a "
                           f"Gateway listening elsewhere cannot be shown to be paper")
        if isinstance(self.client_id, bool) or not isinstance(self.client_id, int) or not 0 < self.client_id < 2**31:
            raise MissingSetting(f"{ENV_CLIENT_ID} must be a positive integer")
        if not isinstance(self.account, str) or not _ACCOUNT_RE.match(self.account):
            raise MissingSetting(f"{ENV_ACCOUNT} is not an account id of upper-case letters and digits "
                                 f"(its value is not shown)")
        if not self.account.startswith(PAPER_ACCOUNT_PREFIX):
            raise NotPaper(f"the expected account ({ENV_ACCOUNT}, value not shown) does not start with "
                           f"{PAPER_ACCOUNT_PREFIX!r}, as an IBKR paper account id does [U]; refusing")

    @classmethod
    def from_env(cls, env) -> "IBKRConfig":
        """All four from `env` (os.environ in the runner). No default, no config file read here:
        the systemd unit sets host, port and client id, and loads the account id from the tmpfs
        file the vault fetch writes (`EnvironmentFile=`)."""
        missing = [k for k in REQUIRED_ENV if not env.get(k)]
        if missing:
            raise MissingSetting(f"{', '.join(missing)} not set; the IBKR client has no defaults "
                                 f"(quantt/broker/ibkr.py)")
        try:
            port = int(env[ENV_PORT])
            cid = int(env[ENV_CLIENT_ID])
        except ValueError:
            raise MissingSetting(f"{ENV_PORT} and {ENV_CLIENT_ID} must be integers") from None
        return cls(host=env[ENV_HOST], port=port, client_id=cid, account=env[ENV_ACCOUNT])


def fx_from_rows(base: str, summary_rows, value_rows) -> dict:
    """IBKR's OWN USD rate for a non-USD base (staging on the VM, 2026-11-26: the paper account is CAD).

    IBKR's per-currency `ExchangeRate` is the value of one unit of that currency in the base [S: IBKR's
    account-value tag list, "the exchange rate of the currency to your base currency"; not re-read], so
    with base CAD the USD row is CAD per USD and USD = CAD / rate. ib_async passes the rows through
    unchanged [V: wrapper.accountSummary / updateAccountValue, the installed 2.1.0]. Two sources:
    `accountSummary` (a fresh request whose `$LEDGER:ALL` tag gives per-currency rows, ib.py
    reqAccountSummaryAsync) is used; `accountValues` (the account-updates subscription) is recorded
    beside it. The DIRECTION is checked at run time against IBKR's own ledger when it is there:
    sum over currencies of NetLiquidationByCurrency x rate must be nearer the BASE row than the same
    sum divided by the rate; if it is not, the rate is not used. Missing, non-finite or not positive:
    usd_per_base None, and whatever needs it refuses (no rate is ever made up)."""
    seen = []
    for source, rs in (("accountSummary", summary_rows), ("accountValues", value_rows)):
        for r in rs:
            if getattr(r, "tag", None) == "ExchangeRate":
                seen.append({"source": source, "currency": str(getattr(r, "currency", "")), "value": str(r.value)})
    out = {"tag": "ExchangeRate", "currency": "USD", "base": base, "rows": seen, "base_per_usd": None,
           "source": None, "direction_check": None, "usd_per_base": None}
    if base == "USD":
        out.update(base_per_usd=1.0, usd_per_base=1.0, source="the base is USD", direction_check="not needed")
        return out
    for source in ("accountSummary", "accountValues"):
        for r in seen:
            if r["source"] == source and r["currency"] == "USD":
                try:
                    x = float(r["value"])
                except ValueError:
                    continue
                if math.isfinite(x) and x > 0 and out["base_per_usd"] is None:
                    out.update(base_per_usd=x, source=source)
    if out["base_per_usd"] is None:
        out["why"] = "no finite, positive ExchangeRate row for USD from IBKR"
        return out
    rates, nlv = {}, {}
    for r in summary_rows:
        tag, cur = getattr(r, "tag", None), str(getattr(r, "currency", ""))
        try:
            x = float(r.value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x):
            continue
        if tag == "ExchangeRate" and cur != "BASE":
            rates[cur] = x
        elif tag == "NetLiquidationByCurrency":
            nlv[cur] = x
    cur_rows = [c for c in nlv if c != "BASE" and c in rates and rates[c] > 0]
    if "BASE" in nlv and cur_rows:
        mul = sum(nlv[c] * rates[c] for c in cur_rows)
        div = sum(nlv[c] / rates[c] for c in cur_rows)
        if abs(mul - nlv["BASE"]) <= abs(div - nlv["BASE"]):
            out["direction_check"] = f"consistent: sum of NetLiquidationByCurrency x rate {mul:,.2f} vs BASE {nlv['BASE']:,.2f}"
        else:
            out["direction_check"] = (f"CONTRADICTS: x rate gives {mul:,.2f}, / rate gives {div:,.2f}, "
                                      f"BASE {nlv['BASE']:,.2f}; the rate is not used")
            out["why"] = "IBKR's own ledger contradicts reading ExchangeRate as base per unit of the currency"
            return out
    else:
        out["direction_check"] = "UNVERIFIED: no per-currency NetLiquidationByCurrency rows to check against [U]"
    out["usd_per_base"] = 1.0 / out["base_per_usd"]
    return out


def _num(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise UnexpectedReply(f"{what} = {v!r} is not a number") from None
    if not math.isfinite(x):
        raise UnexpectedReply(f"{what} = {v!r} is not finite")
    return x


def _whole(v, what: str) -> int:
    x = _num(v, what)
    if x != int(x):
        raise UnexpectedReply(f"{what} = {v!r} is not a whole number of shares")
    return int(x)


class IBKRClient:
    """One IBKR paper account through one Gateway session. `mode` is "read" or "trade".

    `ib_module` is the `ib_async` module, injected by tests as a stub; None imports the real one
    inside `connect`. `sleep` waits between acknowledgement polls; it defaults to the connected
    IB object's own `sleep`, which runs the library's event loop (a plain `time.sleep` would not
    let the acknowledgement arrive).

    `session_lock` / `lock_wait_s`: the Gateway session lock (module docstring, THE SESSION LOCK).
    `lock_sleep` waits between lock polls; no event loop exists yet, so it is a plain sleep."""

    def __init__(self, config: IBKRConfig, *, mode: str, ib_module=None,
                 monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] | None = None,
                 session_lock: Path | str | None = None, lock_wait_s: float = 0.0,
                 lock_sleep: Callable[[float], None] = time.sleep):
        if not isinstance(config, IBKRConfig):
            raise TypeError("config must be an IBKRConfig")
        if mode not in ("read", "trade"):
            raise ValueError(f"mode {mode!r} must be 'read' or 'trade'")
        if isinstance(lock_wait_s, bool) or not isinstance(lock_wait_s, (int, float)) \
                or not math.isfinite(lock_wait_s) or lock_wait_s < 0:
            raise ValueError(f"lock_wait_s {lock_wait_s!r} must be a non-negative number of seconds")
        self.config = config
        self.mode = mode
        self._mod = ib_module
        self._monotonic = monotonic
        self._sleep = sleep
        self.ib = None
        self._contracts: dict = {}
        self._lock_path = None if session_lock is None else Path(session_lock)
        self._lock_wait_s = float(lock_wait_s)
        self._lock_sleep = lock_sleep
        self._lock_fd = None

    def __repr__(self) -> str:
        c = self.config
        return f"IBKRClient(host={c.host!r}, port={c.port}, client_id={c.client_id}, mode={self.mode!r})"

    __str__ = __repr__

    # ------------------------------------------------------------ connection

    def connect(self) -> "IBKRClient":
        """Open the API session, then prove it is the expected paper account.

        A refused or timed-out connection is `NotConnected`: on this desk it means the Gateway is
        down or logged out (the weekly login, a crash, a reboot), which is the twin's most likely
        failure (contract §8 N1). It is named, never retried here: the next timer slot retries.

        With a session lock, the lock is taken first and released on every refusal below; a
        busy lock raises `GatewayBusy` before any socket is opened."""
        if self._lock_path is not None:
            self._take_session_lock()
        try:
            return self._connect()
        except BaseException:
            self._release_session_lock()
            raise

    def _take_session_lock(self) -> None:
        if self._lock_fd is not None:
            return
        try:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as e:
            raise NotConnected(f"cannot open the Gateway session lock {self._lock_path} "
                               f"({type(e).__name__}); no session was opened") from None
        deadline = self._monotonic() + self._lock_wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if self._monotonic() >= deadline:
                    try:
                        holder = os.pread(fd, 120, 0).decode("ascii", "replace").strip() or "holder not recorded"
                    except OSError:
                        holder = "holder unreadable"
                    os.close(fd)
                    raise GatewayBusy(f"another process holds the Gateway session lock {self._lock_path} "
                                      f"({holder}) after {self._lock_wait_s:g}s; no session was opened, "
                                      f"so the two never share the Gateway") from None
                self._lock_sleep(LOCK_POLL_S)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()} client {self.config.client_id} mode {self.mode}\n".encode(), 0)
        self._lock_fd = fd

    def _release_session_lock(self) -> None:
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            os.close(fd)            # closing the descriptor drops the flock

    def _connect(self) -> "IBKRClient":
        if self._mod is None:
            import ib_async as _ib        # noqa: F401  only here (landmine 10: never ib_insync)
            self._mod = _ib
        ib = self._mod.IB()
        ib.RequestTimeout = REQUEST_TIMEOUT_S    # every blocking request bounded (REQUEST_TIMEOUT_S)
        c = self.config
        try:
            # raiseSyncErrors (release check 5, 2026-11-26): ib_async 2.1.0's connect syncs positions,
            # open orders, account values and executions, and with the default False a sync request
            # that times out is only LOGGED, leaving an empty or partial cache that `positions()` would
            # return as the account [V: ib_async/ib.py connect/connectAsync, the installed 2.1.0]. With
            # True it raises ConnectionError, refused here as NotConnected (epoch and the saved read).
            # fetchFields (release check of 300b884, 2026-11-26): no ORDERS_OPEN and no ORDERS_COMPLETE at
            # startup, for every client. ib_async 2.1.0 makes those two requests only for a connection
            # that is not readonly [V: ib/py connectAsync, the installed 2.1.0], so the armed send would
            # have been the first ever to make them, and with raiseSyncErrors a slow completed-orders
            # reply refuses the send. The twin never reads the cache they fill: the guard and
            # open_orders() ask reqAllOpenOrders() themselves, and place_moc judges an order only from it.
            sf = self._mod.StartupFetch
            # account=: the account-updates subscription is for the expected account by name, never
            # left to ib_async's "the only managed account" pick (the VM's CAD rate came back empty).
            ib.connect(c.host, c.port, clientId=c.client_id, timeout=CONNECT_TIMEOUT_S,
                       readonly=(self.mode == "read"), raiseSyncErrors=True, account=c.account,
                       fetchFields=sf.POSITIONS | sf.ACCOUNT_UPDATES | sf.SUB_ACCOUNT_UPDATES | sf.EXECUTIONS)
        except Exception as e:  # noqa: BLE001 -- re-raised as the named refusal, never swallowed
            raise NotConnected(f"could not open an API session to {c.host}:{c.port} as client "
                               f"{c.client_id}: {type(e).__name__}: {e}. The Gateway is down or "
                               f"not logged in") from None
        self.ib = ib
        try:
            accounts = list(ib.managedAccounts() or [])
        except Exception as e:  # noqa: BLE001 -- re-raised, named
            self.disconnect()
            raise NotConnected(f"connected, but managedAccounts() failed: {type(e).__name__}") from None
        if c.account not in accounts:
            n = len(accounts)
            self.disconnect()
            raise WrongAccount(f"the expected paper account ({ENV_ACCOUNT}) is not among the {n} "
                               f"account(s) this Gateway login manages; ids are not printed. "
                               f"Nothing was read or sent")
        return self

    def disconnect(self) -> None:
        try:
            if self.ib is not None:
                try:
                    self.ib.disconnect()
                finally:
                    self.ib = None
        finally:
            self._release_session_lock()

    def _need(self):
        if self.ib is None:
            raise NotConnected("connect() first")
        if not self.ib.isConnected():
            raise NotConnected("the API session dropped")
        return self.ib

    def _wait(self, secs: float) -> None:
        if self._sleep is not None:
            self._sleep(secs)
        else:
            self._mod.IB.sleep(secs)

    def _blocking(self, what: str, fn, *a, **kw):
        """`fn(*a, **kw)`, a blocking ib_async request. On no answer within REQUEST_TIMEOUT_S
        (ib_async raises asyncio.TimeoutError, the built-in TimeoutError on Python 3.11+): drop the
        session, which releases the Gateway session lock, and raise RequestTimedOut naming it."""
        try:
            return fn(*a, **kw)
        except TimeoutError:
            self.disconnect()
            raise RequestTimedOut(f"{what} got no answer within {REQUEST_TIMEOUT_S:.0f} s; the session was "
                                  "dropped and the Gateway lock released") from None

    # --------------------------------------------------------------- reads

    def server_time(self) -> dt.datetime:
        t = self._blocking("reqCurrentTime", self._need().reqCurrentTime)
        if not isinstance(t, dt.datetime) or t.tzinfo is None:
            raise UnexpectedReply(f"reqCurrentTime returned {t!r}, not an aware datetime")
        return t

    def account_summary(self) -> dict:
        """{"net_liquidation", "buying_power", "base_currency", "usd_per_base", "fx"}.

        From `accountSummary(account)`: NetLiquidation and BuyingPower, each exactly once, in one
        currency, the account's base [S: the September account was CAD-based]. `usd_per_base` is
        IBKR's OWN ExchangeRate for USD from `accountValues(account)` when the base is not USD (1.0
        when it is), so a dollar figure can be judged against the base-currency one without a rate
        from anywhere else; absent, it is None and the caller must refuse what needs it."""
        ib = self._need()
        acct = self.config.account
        rows = [r for r in (self._blocking("accountSummary", ib.accountSummary, acct) or [])
                if getattr(r, "account", acct) == acct]
        got: dict = {}
        for r in rows:
            tag = getattr(r, "tag", None)
            if tag in ("NetLiquidation", "BuyingPower"):
                if tag in got:
                    raise UnexpectedReply(f"accountSummary carries {tag} twice")
                got[tag] = (_num(r.value, tag), str(getattr(r, "currency", "")))
        missing = [t for t in ("NetLiquidation", "BuyingPower") if t not in got]
        if missing:
            raise UnexpectedReply(f"accountSummary lacks {missing}")
        ccy = {c for _, c in got.values()}
        if len(ccy) != 1 or not re.fullmatch(r"[A-Z]{3}", next(iter(ccy))):
            raise UnexpectedReply(f"NetLiquidation and BuyingPower are in {sorted(ccy)}, not one currency")
        base = ccy.pop()
        fx = fx_from_rows(base, rows, self._blocking("accountValues", ib.accountValues, acct) or [])
        return {"net_liquidation": got["NetLiquidation"][0], "buying_power": got["BuyingPower"][0],
                "base_currency": base, "usd_per_base": fx["usd_per_base"], "fx": fx}

    def positions(self) -> dict:
        """{symbol: signed whole shares} in the expected account, zero rows left out.

        A position that is not a USD stock, or a fractional one, raises naming the symbol: the
        twin trades US stocks in whole shares, and a position it cannot describe is one it cannot
        reconcile (the September account may still hold things; contract step 5)."""
        ib = self._need()
        out: dict = {}
        for p in ib.positions(self.config.account) or []:
            if getattr(p, "account", self.config.account) != self.config.account:
                continue
            c = p.contract
            sym = getattr(c, "localSymbol", "") or getattr(c, "symbol", "")
            if getattr(c, "secType", "") != "STK" or getattr(c, "currency", "") != "USD":
                raise UnexpectedReply(f"position in {sym!r} is {getattr(c, 'secType', '?')} "
                                      f"{getattr(c, 'currency', '?')}, not a USD stock")
            q = _whole(p.position, f"position {sym}")
            if q:
                s = from_ib_symbol(sym)
                if s in out:
                    raise UnexpectedReply(f"two position rows for {s}")
                out[s] = q
        return dict(sorted(out.items()))

    def open_orders(self) -> list:
        """Every order not in a done state, from ANY client id, as plain dicts.

        `reqAllOpenOrders()` and `openTrades()`, unioned (the 2026-07-31 stack, module docstring).
        Whether `reqAllOpenOrders` still reports another client's MOC across the Gateway's nightly
        restart is NOT measured [U, October R7]; the runner's own order map is the source that
        cannot be blind to a restart (quantt/twin/guard.py). Any failure, or a trade whose status
        cannot be read, raises `OpenOrdersUnknown`."""
        ib = self._need()
        try:
            trades = list(self._blocking("reqAllOpenOrders", ib.reqAllOpenOrders) or [])
            seen = {id(t) for t in trades}
            trades += [t for t in (ib.openTrades() or []) if id(t) not in seen]
        except RequestTimedOut:
            raise                          # the session is gone: not an answer, and not resumable
        except Exception as e:  # noqa: BLE001 -- re-raised as the named unknown
            raise OpenOrdersUnknown(f"could not ask the Gateway what is resting ({type(e).__name__}: "
                                    f"{e}); not knowing is not nothing pending") from None
        out, perms = [], set()
        for t in trades:
            try:
                status = str(t.orderStatus.status)
                o, c = t.order, t.contract
                sym = str(getattr(c, "localSymbol", "") or getattr(c, "symbol", ""))
            except AttributeError as e:
                raise OpenOrdersUnknown(f"an open trade could not be read ({e}); refusing to assume "
                                        f"it is not resting") from None
            if status in DONE_STATUSES:
                continue
            perm = getattr(o, "permId", 0) or 0
            if perm and perm in perms:
                continue
            if perm:
                perms.add(perm)
            out.append({"symbol": sym, "status": status, "action": str(getattr(o, "action", "")),
                        "qty": _num(getattr(o, "totalQuantity", 0) or 0, f"{sym} totalQuantity"),
                        "order_type": str(getattr(o, "orderType", "")),
                        "client_id": getattr(o, "clientId", None), "order_id": getattr(o, "orderId", None),
                        "perm_id": perm, "order_ref": str(getattr(o, "orderRef", "") or "")})
        return out

    def executions_today(self, since: dt.datetime) -> list:
        """The expected account's executions at or after `since` (aware: the caller passes
        midnight ET of the session), each with its commission report. `reqExecutions` returns
        the current day's only [V, October §2.13], so verify runs the same day; IBKR's "day" is
        not documented as New York's, so every row is also filtered here by its own time, and a
        row with no time raises rather than being counted on a guess (review of the build, 11).

        A commission report whose `execId` is '' is the library's default, not a report: its
        commission is None, never zero (archived ibkr.py, "a defaulted report has execId == ''").
        """
        if not isinstance(since, dt.datetime) or since.tzinfo is None:
            raise ValueError("since must be an aware datetime (midnight ET of the session)")
        ib = self._need()
        flt = self._mod.ExecutionFilter(acctCode=self.config.account,
                                        time=since.astimezone(dt.timezone.utc).strftime("%Y%m%d-%H:%M:%S"))
        out = []
        for f in self._blocking("reqExecutions", ib.reqExecutions, flt) or []:
            ex, c = f.execution, f.contract
            if getattr(ex, "acctNumber", self.config.account) != self.config.account:
                continue
            t0 = getattr(f, "time", None) or getattr(ex, "time", None)
            if not isinstance(t0, dt.datetime) or t0.tzinfo is None:
                raise UnexpectedReply(f"execution {getattr(ex, 'execId', '?')} has no aware time; it cannot be "
                                      "placed on a session")
            if t0 < since:
                continue
            side = {"BOT": "buy", "SLD": "sell"}.get(str(ex.side))
            if side is None:
                raise UnexpectedReply(f"execution {ex.execId}: side {ex.side!r} is not BOT|SLD")
            if getattr(c, "secType", "") != "STK" or getattr(c, "currency", "") != "USD":
                raise UnexpectedReply(f"execution {ex.execId} is not a USD stock")
            qty = _whole(ex.shares, f"execution {ex.execId} shares")
            if qty <= 0:
                raise UnexpectedReply(f"execution {ex.execId}: shares {ex.shares!r} is not positive")
            price = _num(ex.price, f"execution {ex.execId} price")
            if price <= 0:
                raise UnexpectedReply(f"execution {ex.execId}: price {ex.price!r} is not positive")
            cr = getattr(f, "commissionReport", None)
            have_cr = cr is not None and str(getattr(cr, "execId", "")) == str(ex.execId)
            t = getattr(f, "time", None) or getattr(ex, "time", None)
            out.append({"exec_id": str(ex.execId),
                        "symbol": from_ib_symbol(getattr(c, "localSymbol", "") or c.symbol),
                        "side": side, "qty": qty, "price": price,
                        "time": t.isoformat() if isinstance(t, dt.datetime) else None,
                        "perm_id": getattr(ex, "permId", 0) or 0, "order_id": getattr(ex, "orderId", None),
                        "client_id": getattr(ex, "clientId", None),
                        "order_ref": str(getattr(ex, "orderRef", "") or ""),
                        "commission": _num(cr.commission, "commission") if have_cr else None,
                        "commission_currency": str(getattr(cr, "currency", "")) if have_cr else None})
        return out

    # ---------------------------------------------------------- contracts

    def qualify(self, symbols) -> dict:
        """{symbol: qualified contract}, resolved BEFORE the first order: a symbol IBKR cannot
        resolve to exactly one US stock refuses the whole set while nothing has been sent (the
        archive's lesson from its option legs: validate the basket, then transmit)."""
        ib = self._need()
        bad = []
        for s in sorted(set(symbols)):
            if s in self._contracts:
                continue
            con = self._mod.Stock(to_ib_symbol(s), "SMART", "USD")
            # `reqContractDetails` is a READ (no order, no subscription), so the dry check and a
            # read-only client resolve the same contracts the send will (review of the build, 3).
            try:
                got = list(self._blocking("reqContractDetails", ib.reqContractDetails, con) or [])
            except RequestTimedOut:
                raise                      # the session is gone: stop, not one wait per symbol
            except Exception as e:  # noqa: BLE001 -- collected and raised below, named
                bad.append(f"{s} ({type(e).__name__})")
                continue
            cons = [getattr(d, "contract", None) for d in got]
            cons = [c for c in cons if c is not None and getattr(c, "conId", 0)
                    and getattr(c, "secType", "STK") == "STK" and getattr(c, "currency", "USD") == "USD"]
            if len(cons) != 1:
                bad.append(f"{s} ({len(cons)} US stock match(es))")
                continue
            self._contracts[s] = cons[0]
        if bad:
            raise UnexpectedReply(f"IBKR could not resolve to one US stock: {bad}; nothing is sent")
        return {s: self._contracts[s] for s in sorted(set(symbols))}

    # -------------------------------------------------------------- writes

    def place_moc(self, symbol: str, qty: int, side: str, order_ref: str) -> dict:
        """Place ONE market-on-close order and wait for the Gateway to say what it did.

        Returns {"symbol", "side", "qty", "order_ref", "client_id", "order_id", "perm_id",
        "status", "accepted" (True | False | None), "messages", "ack_s"}. `accepted` is True for
        PreSubmitted/Submitted/Filled, False for Cancelled/ApiCancelled/Inactive (a rejection: the
        runner skips the symbol and sends the rest, team lead 2026-09-28), and None when nothing
        arrived within ACK_WAIT_S (ambiguous: the runner stops the batch and never resends)."""
        if self.mode != "trade":
            raise ReadOnlyClient("this client is read-only; it cannot place an order")
        if side not in ("buy", "sell"):
            raise ValueError(f"side {side!r} must be buy|sell")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"qty {qty!r} must be a positive whole number of shares")
        if not isinstance(order_ref, str) or not _ORDER_REF_RE.match(order_ref):
            raise ValueError(f"order_ref {order_ref!r} is not a plain id")
        ib = self._need()
        con = self._contracts.get(symbol)
        if con is None:
            raise ValueError(f"{symbol}: not qualified; call qualify() for the whole set first")
        o = self._mod.Order()
        o.action = "BUY" if side == "buy" else "SELL"
        o.totalQuantity = qty
        o.orderType = "MOC"          # CLAUDE.md order-path rule 3; no other type exists here
        o.tif = "DAY"                # IBKR rejects an MOC with an empty TIF (archived _order)
        o.orderRef = order_ref
        o.account = self.config.account
        o.transmit = True
        t0 = self._monotonic()
        trade = ib.placeOrder(con, o)
        status = self._status_of(trade)
        found, requeries, notes = None, 0, []
        # Wait for a definite status. A warning (ValidationError) is not one: the order may be live, so
        # ask the Gateway's open orders, once at once and once more at the deadline (IB_WARNING_CODES).
        while status not in ACCEPTED_STATUSES | REJECTED_STATUSES:
            warned = status == VALIDATION_ERROR or bool(self._warnings_of(trade))
            timed_out = self._monotonic() - t0 >= ACK_WAIT_S
            if warned and (requeries == 0 or (timed_out and requeries == 1)):
                found, note = self._find_open(trade)
                requeries += 1
                if note:
                    notes.append(note)
                status = self._status_of(trade)          # a re-query refreshes ib_async's own status
                if found is not None or status in ACCEPTED_STATUSES | REJECTED_STATUSES:
                    break
            if timed_out:
                break
            self._wait(ACK_POLL_S)
            status = self._status_of(trade)
        if status in REJECTED_STATUSES:
            accepted = False                             # Cancelled / Inactive: IBKR refused it
        elif status in ACCEPTED_STATUSES:
            accepted = True
        elif found is not None:
            found_status = self._status_of(found)
            accepted = False if found_status in REJECTED_STATUSES else True    # resting at IBKR: live
        else:
            accepted = None                              # ambiguous: the runner stops and never resends
        msgs = [str(getattr(e, "message", e)) for e in (getattr(trade, "log", None) or [])
                if getattr(e, "message", "")]
        return {"symbol": symbol, "side": side, "qty": qty, "order_ref": order_ref,
                "client_id": getattr(trade.order, "clientId", self.config.client_id),
                "order_id": getattr(trade.order, "orderId", None),
                "perm_id": getattr(trade.order, "permId", 0) or 0,
                "status": status, "accepted": accepted, "messages": (msgs + notes)[-5:],
                "warnings": self._warnings_of(trade), "found_open": found is not None, "requeries": requeries,
                "ack_s": round(self._monotonic() - t0, 3)}

    @staticmethod
    def _status_of(trade) -> str:
        return str(getattr(getattr(trade, "orderStatus", None), "status", "") or "")

    @staticmethod
    def _warnings_of(trade) -> list:
        """The warning codes (is_ib_warning) in the trade's log, in order, each once."""
        out = []
        for e in getattr(trade, "log", None) or []:
            c = getattr(e, "errorCode", 0)
            if is_ib_warning(c) and c not in out:
                out.append(c)
        return out

    def _find_open(self, trade):
        """(the order as one of the GATEWAY's open orders now, or None; a note when the query failed).

        ONLY `reqAllOpenOrders()`, the Gateway's answer (release check of 300b884, 2026-11-26).
        `ib.openTrades()` is the client's LOCAL cache: every trade whose status is not a DoneState
        [V: ib_async/ib.py openTrades, the installed 2.1.0], and placeOrder puts the new trade there
        before the Gateway replies, so a warned order (ValidationError is not done) always found
        ITSELF there and was counted accepted although IBKR may never have taken it. Matched on the
        permanent id, on this client's id and order id, or on the order ref. A failed query is never
        read as "absent and refused": None with the reason, and the caller's answer stays None."""
        ib = self._need()
        oid = getattr(trade.order, "orderId", None)
        cid = getattr(trade.order, "clientId", self.config.client_id)
        perm = getattr(trade.order, "permId", 0) or 0
        ref = getattr(trade.order, "orderRef", "") or ""
        try:
            rows = list(self._blocking("reqAllOpenOrders", ib.reqAllOpenOrders) or [])
        except RequestTimedOut:
            raise
        except Exception as e:  # noqa: BLE001 -- named in the order's messages; the order stays ambiguous
            return None, f"open-order query after a warning failed: {type(e).__name__}: {e}"
        for t in rows:
            o = getattr(t, "order", None)
            if o is None:
                continue
            if (perm and (getattr(o, "permId", 0) or 0) == perm) \
                    or (oid is not None and getattr(o, "orderId", None) == oid and getattr(o, "clientId", None) == cid) \
                    or (ref and (getattr(o, "orderRef", "") or "") == ref):
                return t, None
        return None, None

    def cancel(self, order_id: int) -> dict:
        """Cancel ONE of this client id's open orders by its order id. Human-run tools only: the
        runner never cancels (an MOC cannot be cancelled or reduced after 15:50 at NYSE; Rule 7.35).
        `cancelOrder` fails across client ids (error 10147, the archived cancel tool's lesson)."""
        if self.mode != "trade":
            raise ReadOnlyClient("this client is read-only; it cannot cancel an order")
        ib = self._need()
        mine = [t for t in (ib.openTrades() or []) if getattr(t.order, "orderId", None) == order_id]
        if len(mine) != 1:
            raise ValueError(f"order id {order_id} is not exactly one of this client's open orders "
                             f"({len(mine)} found); another client's order cannot be cancelled here")
        t = ib.cancelOrder(mine[0].order)
        return {"order_id": order_id, "status": str(getattr(getattr(t, "orderStatus", None), "status", ""))}

    def global_cancel(self) -> None:
        """`reqGlobalCancel()`: every open order on the login, whatever client placed it. Human-run
        only (`quantt.twin cancel-open --confirm N`): it is what cleared the 2026-07-31 stack, where
        `cancelOrder` across client ids failed with error 10147 (archived cancel_open_orders.py)."""
        if self.mode != "trade":
            raise ReadOnlyClient("this client is read-only; it cannot cancel")
        self._need().reqGlobalCancel()
