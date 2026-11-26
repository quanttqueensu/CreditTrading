"""Prove the calling user CANNOT open the Gateway's X display. Stdlib only; run as quantt-shadow.

    runuser -u quantt-shadow -- python3 -I -B ibgw_check_display.py 47      exit 0: refused both ways

WHY (final review, 2026-11-25). A user who can open the Gateway's X display can drive its GUI, and the
GUI can send orders. ibgw_run.sh starts Xvfb with `-nolisten tcp -nolisten local -auth <cookie>`. This
checks, as the user who must be kept out, the two ways in that remain on Linux:
  * the ABSTRACT socket `@/tmp/.X11-unix/X<n>` (no file permission or PrivateTmp covers it): the
    connection itself must fail, since `-nolisten local` closes it;
  * the FILE socket `/tmp/.X11-unix/X<n>`: the connection may open, but the X server must refuse the
    connection setup without the cookie (reply byte 0 Failed, or 2 Authenticate; 1 is Success).
Exit 0 when both are refused; 1, naming what was open, otherwise; 2 on a bad argument. It never
sends a cookie and reads none.
"""
from __future__ import annotations

import socket
import struct
import sys

SETUP = struct.pack("<cxHHHHxx", b"l", 11, 0, 0, 0)    # little-endian, X11.0, no authorisation


def setup_refused(reply: bytes) -> bool:
    """True when an X server's first reply byte says the unauthorised setup did not succeed."""
    return bool(reply) and reply[0] != 1


def try_socket(address) -> str | None:
    """None when refused (no connection, or the setup refused); otherwise what was open."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(address)
    except OSError:
        return None
    try:
        s.sendall(SETUP)
        reply = s.recv(8)
    except OSError:
        return None
    finally:
        s.close()
    return None if setup_refused(reply) else f"{address!r} accepted an X connection without the cookie"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not argv[0].isdigit():
        print("usage: ibgw_check_display.py <display number>", file=sys.stderr)
        return 2
    path = f"/tmp/.X11-unix/X{argv[0]}"
    open_ = [w for w in (try_socket("\0" + path), try_socket(path)) if w]
    if open_:
        print("REFUSED: " + "; ".join(open_), file=sys.stderr)
        return 1
    print(f"display :{argv[0]} refused to this user (abstract and file sockets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
