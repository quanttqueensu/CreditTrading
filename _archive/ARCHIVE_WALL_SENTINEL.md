# Archive wall sentinel

This file exists to be searched for. The token below appears nowhere else in the
repository, so a search that finds it without being pointed at `_archive/` has
crossed the wall that the `/_archive/` line in `.gitignore` is supposed to hold.

    zqx-archive-wall-sentinel-4417

See `_archive/README.md` for the wall, and `results/ops/ARCHIVE_WALL_2026-09-13.md`
for the checks run against it. Tests read the token from this file rather than
spelling it, so that they do not become a second copy of it.
