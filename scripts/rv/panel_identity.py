"""Prove that a rebuilt panel equals the staged one, byte for byte, up to the old last date.

    python3 scripts/rv/panel_identity.py OLD.parquet NEW.parquet          # long panel (date, ticker, ...)
    python3 scripts/rv/panel_identity.py OLD.parquet NEW.parquet --wide   # date-indexed wide panel

WHY THIS EXISTS (2026-10-11, RESEARCH_PLAN_2026-10-09 item 0.1)
---------------------------------------------------------------
The restored ETF fetchers are accepted only if what they rebuild today is what
was staged before the clean slate, on every date the old panel covered. "Looks
the same" is not that test: a float that moved in its last bit, a revised
volume or a dropped row all print identically at default precision. So the
rebuilt panel is cut to the OLD panel's tickers (or columns), columns and last
date, in the rebuilt file's own row order, and checked three ways:

  1. structure: same columns in the same order, same dtypes, same row keys in
     the same order;
  2. values: every cell compared BITWISE (float64 as its uint64 bit pattern,
     datetimes as int64), and separately NaN-equal, so a NaN-payload difference
     cannot hide a real one or masquerade as one;
  3. file: the cut frame is written with the same writer the fetchers use
     (pandas `to_parquet`, pyarrow) and its SHA-256 compared with the old
     file's. Only this is "byte-identical"; it can hold only when the pandas
     and pyarrow versions match the old file's `pandas` metadata, which is
     printed beside the verdict.

Every differing cell is listed (first 20 per column) with both values, so a
failure says exactly where and by how much -- the report the plan asks for
when history cannot be rebuilt byte-identically.

Exit code 0 only on a file-level match. Read-only on both inputs; the cut
frame is written to a temporary directory and deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

MAX_LISTED = 20


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def writer_meta(path: Path) -> dict:
    meta = json.loads(pq.read_schema(path).metadata[b"pandas"])
    return {"pandas": meta.get("pandas_version"), "creator": meta.get("creator")}


def cut(new: pd.DataFrame, old: pd.DataFrame, wide: bool) -> pd.DataFrame:
    """`new` restricted to old's last date, keys and columns, in new's own order."""
    if wide:
        last = old.index.max()
        missing = [c for c in old.columns if c not in new.columns]
        if missing:
            raise ValueError(f"rebuilt wide panel lacks old columns {missing}")
        out = new.loc[new.index <= last, list(old.columns)]
        return out
    for c in ("date", "ticker"):
        if c not in new.columns or c not in old.columns:
            raise ValueError(f"long panel needs a {c!r} column in both files")
    missing = [c for c in old.columns if c not in new.columns]
    if missing:
        raise ValueError(f"rebuilt panel lacks old columns {missing}")
    last = old["date"].max()
    keep = (new["date"] <= last) & new["ticker"].isin(set(old["ticker"]))
    return new.loc[keep, list(old.columns)].reset_index(drop=True)


def _bits(s: pd.Series) -> np.ndarray:
    v = s.to_numpy()
    if v.dtype == np.float64:
        return v.view(np.uint64)
    if np.issubdtype(v.dtype, np.datetime64):
        return v.view(np.int64)
    return v


def compare(old: pd.DataFrame, new: pd.DataFrame, wide: bool) -> dict:
    """Structural and cell-level comparison; never raises on a difference."""
    rep = {"rows_old": len(old), "rows_new": len(new), "problems": [], "cells": {}}
    if list(old.columns) != list(new.columns):
        rep["problems"].append(f"columns differ: {list(old.columns)} vs {list(new.columns)}")
        return rep
    dt_old, dt_new = old.dtypes.astype(str).to_dict(), new.dtypes.astype(str).to_dict()
    if dt_old != dt_new:
        rep["problems"].append(f"dtypes differ: {dt_old} vs {dt_new}")
    if wide:
        ko, kn = list(old.index), list(new.index)
        label = lambda i: str(pd.Timestamp(old.index[i]).date())  # noqa: E731
        day = lambda i: str(pd.Timestamp(old.index[i]).date())    # noqa: E731
    else:
        day = lambda i: str(pd.Timestamp(old["date"].iat[i]).date())  # noqa: E731
        ko = list(zip(old["ticker"], old["date"]))
        kn = list(zip(new["ticker"], new["date"]))
        label = lambda i: f"{old['ticker'].iat[i]} {pd.Timestamp(old['date'].iat[i]).date()}"  # noqa: E731
    if ko != kn:
        so, sn = set(ko), set(kn)
        rep["problems"].append(
            f"row keys differ: {len(so - sn)} only in old (e.g. {sorted(so - sn)[:5]}), "
            f"{len(sn - so)} only in new (e.g. {sorted(sn - so)[:5]})"
            + ("" if so != sn else "; same set, different ORDER"))
        return rep
    for c in old.columns:
        a, b = old[c], new[c]
        bit_eq = _bits(a) == _bits(b)
        if a.dtype == np.float64:
            val_eq = (a.to_numpy() == b.to_numpy()) | (a.isna().to_numpy() & b.isna().to_numpy())
        else:
            val_eq = bit_eq
        nd = np.flatnonzero(~bit_eq)
        if len(nd):
            days = pd.Series([day(i) for i in nd]).value_counts().sort_index()
            rep["cells"][c] = {
                "n_bitwise_diff": int(len(nd)), "n_value_diff": int((~val_eq).sum()),
                "by_date": days.to_dict() if len(days) <= MAX_LISTED else
                {"first": days.index[0], "last": days.index[-1], "n_dates": int(len(days))},
                "examples": [(label(i), repr(a.iat[i]), repr(b.iat[i])) for i in nd[:MAX_LISTED]]}
    return rep


def _write(frame: pd.DataFrame, path: Path, wide: bool) -> None:
    if wide:
        frame.to_parquet(path)
    else:
        frame.to_parquet(path, index=False)


def identity(old_path: Path, new_path: Path, wide: bool = False,
             through: str | None = None, exclude=()) -> dict:
    """Compare the rebuilt panel with the staged one.

    Default: the old FILE as it is, against the rebuilt panel cut to it.
    `through=DATE` cuts BOTH at DATE (both rewritten by the same writer, so the
    hashes compare like with like): it locates the last date through which the
    two are byte-identical once the differing dates are known. `exclude` drops
    named columns from both, for a column that differs everywhere by design;
    every exclusion is printed with the verdict, never applied silently.
    """
    old = pd.read_parquet(old_path)
    new = pd.read_parquet(new_path)
    exclude = list(exclude)
    if exclude:
        missing = [c for c in exclude if c not in old.columns]
        if missing:
            raise ValueError(f"--exclude names columns the old panel lacks: {missing}")
        old = old.drop(columns=exclude)
    if through is not None:
        t = pd.Timestamp(through)
        old = old.loc[old.index <= t] if wide else old.loc[old["date"] <= t].reset_index(drop=True)
    c = cut(new, old, wide)
    rep = compare(old, c, wide)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cut.parquet"
        _write(c, p, wide)
        rep["sha_cut"], rep["writer_cut"] = sha256(p), writer_meta(p)
        if through is None and not exclude:
            rep["sha_old"], rep["writer_old"] = sha256(old_path), writer_meta(old_path)
            rep["old_hashed"] = "the old file as staged"
        else:
            q = Path(td) / "old_cut.parquet"
            _write(old, q, wide)
            rep["sha_old"], rep["writer_old"] = sha256(q), writer_meta(q)
            rep["old_hashed"] = (f"the old file cut through {through or 'its end'}"
                                 + (f", columns {exclude} excluded" if exclude else "")
                                 + ", rewritten by this writer")
    rep["old_last"] = str(pd.Timestamp(old.index.max() if wide else old["date"].max()).date())
    rep["byte_identical"] = rep["sha_old"] == rep["sha_cut"]
    rep["cell_identical"] = not rep["problems"] and not rep["cells"]
    return rep


def render(name: str, rep: dict, max_examples: int = MAX_LISTED) -> str:
    lines = [f"{name}: compared through {rep['old_last']}; rows old {rep['rows_old']}, "
             f"rebuilt-cut {rep['rows_new']}; hashed: {rep['old_hashed']}",
             f"  file SHA-256 old {rep['sha_old'][:16]}..  cut {rep['sha_cut'][:16]}..  "
             f"-> {'BYTE-IDENTICAL' if rep['byte_identical'] else 'DIFFERENT'}",
             f"  writer old {rep['writer_old']}  cut {rep['writer_cut']}"]
    for p in rep["problems"]:
        lines.append(f"  STRUCTURE: {p}")
    for col, d in rep["cells"].items():
        lines.append(f"  {col}: {d['n_bitwise_diff']} cell(s) differ bitwise "
                     f"({d['n_value_diff']} by value); by date {d['by_date']}")
        for k, a, b in d["examples"][:max_examples]:
            lines.append(f"      {k}: old {a}  new {b}")
    if rep["cell_identical"] and not rep["byte_identical"]:
        lines.append("  every cell is bitwise equal; the files differ only in encoding/metadata")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--wide", action="store_true", help="date-indexed wide panel")
    ap.add_argument("--examples", type=int, default=MAX_LISTED,
                    help=f"differing cells listed per column (max {MAX_LISTED})")
    ap.add_argument("--through", default=None,
                    help="cut BOTH panels at this date (YYYY-MM-DD) before comparing")
    ap.add_argument("--exclude", action="append", default=[],
                    help="drop this column from both (repeatable); printed with the verdict")
    a = ap.parse_args(argv)
    rep = identity(a.old, a.new, a.wide, a.through, a.exclude)
    print(render(a.old.name, rep, a.examples))
    return 0 if rep["byte_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
