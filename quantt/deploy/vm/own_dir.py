"""Make a directory and set its owner and mode through a descriptor that refuses a symlink. Run as root.

    python3 -I -B own_dir.py <path> <user> <group> <octal mode>      e.g. /srv/quantt-ibkr-feed/requests quantt-shadow quantt 2750

WHY (final check, 2026-11-25). The installer runs as root, and some directories it must own for another
user sit inside a directory that user can write (`/srv/quantt-ibkr-feed/requests` inside quantt's
`/srv/quantt-ibkr-feed`). `chown` and `chmod` on such a path follow a symlink planted in its place, so
quantt could have root chown /etc to itself. Here the last component is opened with O_NOFOLLOW and
O_DIRECTORY, checked to be a directory, and owned and moded through that descriptor (fchown, fchmod):
whatever is planted, root acts on the directory it opened or refuses. Exit 0 done; 1 refused, named;
2 bad arguments.
"""
from __future__ import annotations

import grp
import os
import pwd
import stat
import sys


def own_dir(path: str, uid: int, gid: int, mode: int) -> None:
    """Create `path` (0700, if absent) and give it uid, gid and mode, never through a symlink."""
    if not os.path.isabs(path):
        raise ValueError(f"{path} is not absolute")
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass                                     # it exists: whatever it is, the open below decides
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NotADirectoryError(path)
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 4:
        print("usage: own_dir.py <path> <user> <group> <octal mode>", file=sys.stderr)
        return 2
    path, user, group, mode = argv
    try:
        uid, gid, m = pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid, int(mode, 8)
    except (KeyError, ValueError) as e:
        print(f"REFUSED: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    try:
        own_dir(path, uid, gid, m)
    except OSError as e:
        print(f"REFUSED: {path}: {type(e).__name__}: {e} (a symlink in its place is refused, never followed)",
              file=sys.stderr)
        return 1
    print(f"{path}: {user}:{group} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
