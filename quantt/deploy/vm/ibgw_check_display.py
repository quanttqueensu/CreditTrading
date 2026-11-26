"""Prove the Gateway's X display is up and its own, and that the shadow user cannot open it. Stdlib only.

    runuser -u quantt        -- python3 -I -B ibgw_check_display.py owner   47 <Xauthority>   exit 0: it is up
    runuser -u quantt-shadow -- python3 -I -B ibgw_check_display.py refused 47 <Xauthority>   exit 0: refused

WHY (final review, 2026-11-25). A user who can open the Gateway's X display can drive its GUI, and the
GUI can send orders. ibgw_run.sh starts Xvfb with `-nolisten tcp -nolisten local -auth <cookie>`.

`owner` FIRST (final check, 2026-11-25): a refusal proves nothing if no X server is there, so the
installer first shows, as quantt, that the file socket `/tmp/.X11-unix/X<n>` exists and that the X
server accepts a connection carrying the cookie from <Xauthority> (reply byte 1, Success). Only then
does `refused`, as quantt-shadow, count:
  * the cookie file cannot be read (its directory is quantt's 0700 tmpfs);
  * the file socket exists, and the server answers an unauthorised setup with a refusal (reply byte 0
    Failed or 2 Authenticate), or the socket's permissions refuse the connection; a socket nobody
    answers on is NOT a refusal ("nothing proved", exit 1);
  * the ABSTRACT socket `@/tmp/.X11-unix/X<n>` (no file permission or PrivateTmp covers it) takes no
    connection, since `-nolisten local` closes it.
Exit 0 when the mode's checks hold; 1, naming what failed, otherwise; 2 on bad arguments. The cookie is
read into memory by `owner` only, sent only to that socket, and never printed.
"""
from __future__ import annotations

import os
import socket
import stat
import struct
import sys

COOKIE_NAME = b"MIT-MAGIC-COOKIE-1"


def _pad(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)


def setup_bytes(name: bytes = b"", data: bytes = b"") -> bytes:
    """An X11 connection setup, little-endian, protocol 11.0, with the given authorisation (none by default)."""
    return struct.pack("<cxHHHHxx", b"l", 11, 0, len(name), len(data)) + _pad(name) + _pad(data)


SETUP = setup_bytes()


def setup_refused(reply: bytes) -> bool:
    """True when an X server's first reply byte says the setup did not succeed."""
    return bool(reply) and reply[0] != 1


def read_cookie(path: str, display: str) -> bytes:
    """The MIT-MAGIC-COOKIE-1 for `display` from an Xauthority file (big-endian records: family u16, then
    address, number, name and data, each a u16 length and that many bytes). Raises naming what is wrong."""
    with open(path, "rb") as f:
        data = f.read()
    i = 0

    def take(n: int) -> bytes:
        nonlocal i
        if i + n > len(data):
            raise ValueError(f"{path} ends inside a record")
        out = data[i:i + n]
        i += n
        return out

    def field() -> bytes:
        return take(struct.unpack(">H", take(2))[0])
    while i < len(data):
        take(2)                                          # the family
        field()                                          # the address
        number, name, cookie = field(), field(), field()
        if number == display.encode() and name == COOKIE_NAME and cookie:
            return cookie
    raise LookupError(f"{path} holds no {COOKIE_NAME.decode()} for display :{display}")


def is_socket(path: str) -> bool:
    try:
        return stat.S_ISSOCK(os.lstat(path).st_mode)
    except OSError:
        return False


def exchange(address, setup: bytes):
    """("reply", first bytes) | ("denied", why) for a permission refusal | ("no_answer", why)."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(address)
        s.sendall(setup)
        reply = s.recv(8)
    except PermissionError as e:
        return "denied", f"{type(e).__name__}"
    except OSError as e:
        return "no_answer", f"{type(e).__name__}"
    finally:
        s.close()
    return ("reply", reply) if reply else ("no_answer", "the connection closed with no reply")


def owner(display: str, xauthority: str) -> list:
    """Problems with the display as its owner sees it; [] when it is up and takes its own cookie."""
    path = f"/tmp/.X11-unix/X{display}"
    if not is_socket(path):
        return [f"no X socket at {path}: the display is not up, so no refusal would prove anything"]
    try:
        cookie = read_cookie(xauthority, display)
    except (OSError, ValueError, LookupError) as e:
        return [f"cannot read the display's cookie ({type(e).__name__}: {e})"]
    kind, got = exchange(path, setup_bytes(COOKIE_NAME, cookie))
    if kind != "reply" or setup_refused(got):
        return [f"the X server at {path} did not accept its own cookie ({kind})"]
    return []


def refused(display: str, xauthority: str) -> list:
    """What the calling user COULD open; [] when every way in is refused (and the display answered)."""
    path = f"/tmp/.X11-unix/X{display}"
    bad = []
    try:
        with open(xauthority, "rb"):
            bad.append(f"this user can read the display's cookie file {xauthority}")
    except PermissionError:
        pass
    except OSError as e:
        bad.append(f"the cookie file {xauthority} is not there to be refused ({type(e).__name__}): nothing proved")
    if not is_socket(path):
        bad.append(f"no X socket at {path}: nothing proved")
    else:
        kind, got = exchange(path, SETUP)
        if kind == "no_answer":
            bad.append(f"the X server at {path} did not answer ({got}): nothing proved")
        elif kind == "reply" and not setup_refused(got):
            bad.append(f"{path} accepted an X connection without the cookie")
    kind, got = exchange("\0" + path, SETUP)
    if kind == "reply" and not setup_refused(got):
        bad.append(f"the abstract socket @{path} accepted an X connection without the cookie")
    elif kind == "reply":
        bad.append(f"the abstract socket @{path} is listening (-nolisten local did not hold)")
    return bad


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3 or argv[0] not in ("owner", "refused") or not argv[1].isdigit():
        print("usage: ibgw_check_display.py owner|refused <display number> <Xauthority file>", file=sys.stderr)
        return 2
    mode, display, xauth = argv
    bad = owner(display, xauth) if mode == "owner" else refused(display, xauth)
    if bad:
        print("REFUSED: " + "; ".join(bad), file=sys.stderr)
        return 1
    print(f"display :{display} is up and takes its own cookie" if mode == "owner" else
          f"display :{display} refused to this user (cookie file, file socket and abstract socket)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
