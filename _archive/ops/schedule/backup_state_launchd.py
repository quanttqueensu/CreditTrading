#!/usr/bin/env python3
"""launchd entry point for ops/backup_state.sh, so the archive can read data/.

WHY THIS EXISTS
---------------
`com.quantt.backup.daily` ran `/bin/bash .../backup_state.sh` directly and
reported `last exit 1` every night since it was scheduled. Run by hand in a
terminal the same script exits 0 and writes a complete archive. Measured
2026-09-10/11:

    12:17  launchd archive      172,507 bytes, 223 entries, NO `data/` entries
    17:29  interactive          175,744 bytes, contains data/cef/cef_borrow.csv
    10:37  via this wrapper     176,128 bytes, contains data/cef/cef_borrow.csv

So it is not the script's logic -- it is the EXECUTABLE. macOS TCC grants Full
Disk Access per binary, and `data/` in prod is a symlink into ~/Desktop, a
protected location. `/opt/anaconda3/bin/python3` has that grant: the cef, phase0
and benchmarks jobs read those same parquets under launchd every day.
`/bin/bash` does not, so `tar` spawned from it silently omitted every path under
`data/`, and `backup_state.sh` reported that as a flat failure.

Running the script as a CHILD of the Python binary makes Python the responsible
process for TCC, and the child inherits the grant.

WHERE IT RUNS FROM. `ops/schedule/install_backup.sh` copies this file to
`~/Library/Application Support/quantt/`, beside `launch_job.py`, and the plist
names it there. It must live OUTSIDE the repo for the same reason `launch_job.py`
does: launchd cannot reach `~/Desktop`, and a prod worktree checked out to a
different tag must not be able to take the entry point with it. This file is the
SOURCE; the installed copy is what launchd runs.

Exit codes pass through unchanged, because they mean different things and
`ops/doctor.py` distinguishes them:

    0   archive written and complete
    2   archive written, but a file it wanted was unreadable   (doctor: WARN)
    1   no archive at all                                      (doctor: WARN, loud)

`ops/promote.sh` tolerates 2 and refuses on 1, for the same reason: the ledgers
are in the archive either way, and they are the irreplaceable part.
"""
import os
import subprocess
import sys
from pathlib import Path

PROD = Path(os.environ.get("QUANTT_PROD", Path.home() / "prod" / "QUANTT"))
SCRIPT = PROD / "ops" / "backup_state.sh"


def main() -> int:
    if not SCRIPT.exists():
        # Not a silent skip: the job exists to insure the ledgers, and a missing
        # script is the one failure that would otherwise archive nothing while
        # exiting cleanly.
        print(f"backup wrapper: {SCRIPT} does not exist -- nothing archived",
              file=sys.stderr)
        return 1
    # stdout/stderr are inherited so the plist's log keeps the script's own
    # output. The point of the exit-code rewrite was that it can explain itself;
    # swallowing that here would undo it.
    return subprocess.run(["/bin/bash", str(SCRIPT)]).returncode


if __name__ == "__main__":
    sys.exit(main())
