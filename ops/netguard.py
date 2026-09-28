"""A process-wide tripwire on outbound connections: install it and none opens.

WHY THIS EXISTS
---------------
The safest-looking command in this repo once reached for the order path.
`scripts/audit/moc_routing_test.py` opens a LIVE BROKER CONNECTION at import
time and transmits a test order to the closing auction; it matches pytest's
default discovery patterns, so a bare `python3 -m pytest` imported it during
COLLECTION. `pytest.ini` now scopes collection away from it, and that is a
fence around one file. It says nothing about the next module that grows an
import-time fetch, a test that builds a real `IBKRBroker` and forgets to stub
`ib`, or a rehearsal driver that runs `run_book.main` with EXECUTION=ibkr.

An order cannot leave this machine without a TCP connection to the gateway.
So the control that does not depend on anyone remembering anything is: inside
a test run (the root `conftest.py`) and inside the rehearsal and no-op-proof
drivers, no connection opens at all, to any destination, and the attempt is
loud.

WHY EVERY DESTINATION, NOT JUST THE GATEWAY PORTS
-------------------------------------------------
A port list is a list of the brokers we remembered. 4001/4002/7496/7497 are
IBKR's defaults and `IBKR_PORT` overrides them; the vendor fetchers reach for
HTTPS; `ops.halt._email` reaches for SMTP. A test that needs any of those is a
test that depends on the world, and the rule on this desk is that such a test
is made hermetic, never that the guard is widened. There is deliberately no
allowlist, no `uninstall()` and no context manager that lifts it: a guard with
an off switch gets switched off by the one test that most needs it.

WHAT IT REPLACES
----------------
  socket.socket.connect        every blocking and non-blocking TCP/UDP/UNIX
                               connect, including asyncio's: the selector
                               event loop's `sock_connect` calls
                               `sock.connect(address)` on a `socket.socket`,
                               which is how `ib_async` and
                               `asyncio.open_connection` get here.
  socket.socket.connect_ex     the errno-returning twin, which would otherwise
                               walk straight past a guard on `connect`.
  socket.create_connection     what `http.client`, `urllib`, `smtplib` and
                               `ftplib` call. It ends in `sock.connect` too,
                               but only after a DNS lookup -- replacing it
                               makes the refusal happen before the resolver is
                               asked anything.

WHAT IT IS NOT
--------------
A sandbox. Code that calls `_socket.socket.connect` on the C type directly, a
C extension with its own sockets, a subprocess (`curl`, a child Python), and
connectionless `sendto` all pass it. It catches the honest mistake, which is
the only kind this repo has ever made. The subprocess side is covered
separately by the root conftest's argv guard.

`is_active()` re-reads the three attributes rather than trusting a flag,
because the failure it exists to catch is a `monkeypatch.setattr(socket...)`
somewhere putting the real function back and nobody noticing.
"""

from __future__ import annotations

import socket


class NetGuardViolation(RuntimeError):
    """Something tried to open a network connection while netguard was active.

    A RuntimeError and not an OSError ON PURPOSE: a caller that catches the
    network errors it expects (`OSError`, `ConnectionRefusedError`,
    `TimeoutError`) and reads them as "nothing listening" must not be able to
    read this as that.

    It is still swallowed by `except Exception`, and two of this repo's
    connect sites are that shape: `ops.halt._email` returns "failed (...)" and
    `ops.preflight.check_broker` returns a failed Check reading "nothing
    listening", whatever was raised. For those the guard still does its job
    (nothing connected) but the raise is invisible, so every refusal is ALSO
    appended to a record that `violations()` returns; the root conftest prints
    it at the end of the run. A refusal nobody saw is how a test comes to
    depend on the gateway being down.
    """


_VIOLATIONS: list = []


def violations() -> tuple:
    """Every refused attempt so far as (entry_point, address), oldest first.

    Includes the ones a caller's `except Exception` swallowed, which is the
    point of keeping it.
    """
    return tuple(_VIOLATIONS)


def _refuse(what: str, address) -> None:
    _VIOLATIONS.append((what, address))
    raise NetGuardViolation(
        f"netguard: {what} to {address!r} refused. No network connection may "
        f"open while ops.netguard is installed (pytest under the root "
        f"conftest.py, ops/rehearsal.py, ops/noop_proof.py). If a test needs "
        f"this destination, make the test hermetic (stub the client); do not "
        f"widen the guard.")


def _guarded_connect(self, address, *args, **kwargs):
    _refuse("socket.connect", address)


def _guarded_connect_ex(self, address, *args, **kwargs):
    # Raises instead of returning an errno: a caller of connect_ex is by
    # construction one that reads a non-zero return as "nothing listening",
    # which is the quiet outcome this module exists to make impossible.
    _refuse("socket.connect_ex", address)


def _guarded_create_connection(address, *args, **kwargs):
    _refuse("socket.create_connection", address)


_GUARDS = (
    (socket.socket, "connect", _guarded_connect),
    (socket.socket, "connect_ex", _guarded_connect_ex),
    (socket, "create_connection", _guarded_create_connection),
)


def install() -> None:
    """Replace the three connect entry points with the raiser. Idempotent.

    Process-wide and permanent for the life of the interpreter; see the module
    docstring for why there is no way back.
    """
    for owner, name, guard in _GUARDS:
        setattr(owner, name, guard)


def is_active() -> bool:
    """True only if ALL THREE entry points are the raiser right now.

    Measured from the live attributes, not remembered from `install()`: a
    caller that must not proceed unguarded (`run_book.main` under test, the
    rehearsal driver) asserts this immediately before the risky call, and a
    partial restore by some earlier monkeypatch must read as inactive.
    """
    return all(getattr(owner, name, None) is guard
               for owner, name, guard in _GUARDS)
