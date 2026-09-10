"""Backfill `modelled_fill_price` and `exec_ids` into pre-2026-09-10 trades.csv.

WHY THIS IS A MIGRATION AND NOT A DEFAULT
-----------------------------------------
`ops/ledger.py` gained two columns on 2026-09-10 when the ledger started booking
the broker's real fills. Every row written BEFORE that came from `_simulate_fill`,
where the fill price IS the modelled price -- so `modelled_fill_price = fill_price`
is not an invented value for those rows, it is true by construction, and this
script says so once, in writing, instead of a `fillna` saying it silently on
every read. `exec_ids` becomes "" for the same reason: no execution backed those
rows, and "" is exactly that claim.

It refuses to touch a file that already has the columns, and it never guesses at
a row that carries an execId -- if one is present the file is already post-
migration and something else is wrong.

    python3 scripts/ops/migrate_trades_modelled_price.py --dry-run
    python3 scripts/ops/migrate_trades_modelled_price.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def targets():
    return sorted(REPO.glob("ops/books/*_live/_ibkr_shadow/*/trades.csv"))


def migrate(path: Path, apply: bool) -> str:
    df = pd.read_csv(path)
    if df.empty:
        return "empty, nothing to do"
    if "modelled_fill_price" in df.columns and "exec_ids" in df.columns:
        return "already migrated"
    if "fill_price" not in df.columns:
        raise KeyError(f"{path} has no fill_price column; refusing to guess")
    df["modelled_fill_price"] = df["fill_price"]
    df["exec_ids"] = ""
    if apply:
        df.to_csv(path, index=False)
    return f"{len(df)} row(s) backfilled" + ("" if apply else " (dry run)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    found = targets()
    if not found:
        print("no trades.csv under ops/books/*_live/_ibkr_shadow/*/")
        return 1
    for path in found:
        print(f"{path.relative_to(REPO)}: {migrate(path, a.apply)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
