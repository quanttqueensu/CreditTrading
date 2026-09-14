"""Archive the old schedule's machine-side leftovers once W3 is live. Dry run by default.

    python3 -m ops.archive_machine_pre_w3            # list what would move
    python3 -m ops.archive_machine_pre_w3 --apply    # move it

WHY THIS EXISTS
---------------
The team lead decided on 2026-09-13: finish the W3 morning schedule, start the
track record from it, and archive the old schedule and stale files. The repo
half rode the go-live promotion (`ops/_archive/schedule_pre_w3_2026-09-13/`, folded into
`_archive/ops/_archive/` on 2026-09-14).
This is the half git cannot reach: backups of the out-of-repo scheduler and
plist backups sitting beside the live LaunchAgents, where the next reader has to
work out which of six `*.plist.bak-*` files, if any, is what runs.

WHAT MOVES (measured 2026-09-13, re-measured on every run -- nothing is listed
from this docstring):
  ~/Library/Application Support/quantt/launch_job.py.bak-*
      Four backups, including `.bak-20260913-212735`: the evening scheduler as
      it stood before W3 was patched in. It is kept -- moved, not deleted --
      because it is the rollback path if W3 has to be abandoned.
  ~/Library/LaunchAgents/com.quantt.*.plist.bak-*
  ~/Library/LaunchAgents/com.quantt.<label>.plist whose label is NOT loaded
      (on 2026-09-13: com.quantt.book.daily and com.quantt.book.weekly).

Everything goes to `~/Library/Application Support/quantt/_archive/pre_w3_<stamp>/`
with a MANIFEST.txt listing each file's origin and sha256, and the exact `mv`
that puts it back.

WHAT IT REFUSES
---------------
  * to run --apply unless `com.quantt.cef_pm` is loaded. That label exists only
    under W3, so this is the test for "W3 is live". Archiving the rollback path
    before the new schedule is running is the one ordering that could strand
    the book with neither.
  * to move a plist whose label launchd has loaded, whatever its name says.
  * to overwrite anything already in the archive.

It never calls launchctl load/unload/bootstrap/bootout. It only reads
`launchctl list`.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SUPPORT = Path.home() / "Library/Application Support/quantt"
AGENTS = Path.home() / "Library/LaunchAgents"
W3_LABEL = "com.quantt.cef_pm"


def loaded_labels(listing: str | None = None) -> set:
    """Labels in `launchctl list`. Raises if launchctl cannot be read: an empty
    set would make every plist look unloaded and movable."""
    if listing is None:
        listing = subprocess.run(["launchctl", "list"], check=True,
                                 capture_output=True, text=True).stdout
    out = set()
    for line in listing.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            out.add(parts[2])
    if not out:
        raise RuntimeError("launchctl list returned no labels; refusing to "
                           "judge which plists are loaded")
    return out


def candidates(support: Path, agents: Path, loaded: set) -> list[Path]:
    found = sorted(support.glob("launch_job.py.bak-*"))
    found += sorted(agents.glob("com.quantt.*.plist.bak-*"))
    for p in sorted(agents.glob("com.quantt.*.plist")):
        if p.name[:-len(".plist")] not in loaded:
            found.append(p)
    return [p for p in found if p.is_file()]


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv=None, *, support=SUPPORT, agents=AGENTS, listing=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    loaded = loaded_labels(listing)
    items = candidates(support, agents, loaded)
    for p in items:
        print(f"  {p}")
    if not items:
        print("nothing to archive")
        return 0
    if not a.apply:
        print(f"\n{len(items)} file(s). Dry run -- re-run with --apply to move them.")
        return 0
    if W3_LABEL not in loaded:
        print(f"REFUSING: {W3_LABEL} is not loaded, so W3 is not live. These "
              f"files include the evening scheduler's rollback copy; archive "
              f"them after the new schedule is running, not before.")
        return 2

    dest = support / "_archive" / f"pre_w3_{datetime.now():%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True, exist_ok=False)
    lines = [f"archived {datetime.now():%Y-%m-%d %H:%M:%S} by "
             f"ops/archive_machine_pre_w3.py; loaded labels at the time: "
             f"{sorted(loaded)}", ""]
    for p in items:
        sub = "LaunchAgents" if p.parent == agents else "quantt"
        target = dest / sub / p.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(target)
        digest = _sha256(p)
        shutil.move(str(p), str(target))
        lines.append(f"{digest}  {p}")
        lines.append(f"    restore: mv '{target}' '{p}'")
    (dest / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
    print(f"\nmoved {len(items)} file(s) to {dest} (MANIFEST.txt has the "
          f"restore commands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
