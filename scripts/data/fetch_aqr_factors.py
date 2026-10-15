"""Fetch AQR's Time Series Momentum and Value and Momentum Everywhere factor files
(monthly) into a gitignored cache, recording the vintage of each file.

    python3 scripts/data/fetch_aqr_factors.py            # fetch, parse, write the cache

WHY THIS EXISTS (2026-10-14, gate DG2 of the XASSET slate)
---------------------------------------------------------
`results/xasset/PREREG_XASSET_SLATE_2026-10-12.md` (revision 3, approved
2026-10-14) reports each sleeve's monthly excess P&L on AQR's published factors
(regression R-AQR, §1.7): TSMOM and its FI / EQ / CM sub-factors (Moskowitz, Ooi
& Pedersen 2012, updated by AQR) and VME's MOM (Asness, Moskowitz & Pedersen
2013). CLAUDE.md: "never hand-copy a data series -- anything fetched gets a
fetcher and a source note in docs/REFERENCES.md". REFERENCES §12i (2026-10-12)
found both files reachable and required this fetcher before any run used them.

THE VINTAGE IS RECORDED, NOT ASSUMED
------------------------------------
Each file says "AQR reconstructs the full history each time the returns are
updated", so two fetches a month apart are two different series, including in
months long past. The files carry no as-of date. So every cached row carries:
the file's SHA-256 as downloaded, the HTTP `Last-Modified` header (or the
literal "absent" when the server sends none -- recorded, never invented), the
UTC fetch time, the URL, and the file's last data month. A regression quotes
these; the XASSET Stage 0a manifest pins the cache's SHA-256.

WHERE IT WRITES
---------------
`results/xasset/_cache_xasset/aqr_{tsmom,vme}_monthly.parquet`, gitignored
(`results/**/_cache_*`). Third-party data is not committed: the repository is
public and the files are re-fetchable by this script. Nothing is written under
`data/` (CLAUDE.md landmine 9).

PARSING RULES (no silent fallbacks)
-----------------------------------
* The factor sheet is the workbook's FIRST sheet, named as expected below; a
  renamed sheet raises.
* The header row is located by its exact contents and must equal the expected
  column list, in order. A renamed, dropped or re-ordered column raises rather
  than shifting values silently.
* Data rows run from the row after the header to the first row whose first
  cell is not a date. Every value must parse as a float or be empty. Empty
  cells stay NaN: AQR publishes some sub-factors over shorter spans (the VME
  asset-allocation columns end before the global ones). A consumer that needs a
  month a factor does not cover must raise, naming it; this fetcher never fills.
* Dates must be strictly increasing month-ends, one per month, with no gap.
* Values are decimals as published (AQR's files are not in percent; a value
  with |x| > 1 in a monthly factor return raises, since that would mean a unit
  change).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "results" / "xasset" / "_cache_xasset"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
FILES = {
    "tsmom": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/"
               "Time-Series-Momentum-Factors-Monthly.xlsx",
        "sheet": "TSMOM Factors",
        # the header row's first cell is empty in this file
        "header": [None, "TSMOM", "TSMOM^CM", "TSMOM^EQ", "TSMOM^FI", "TSMOM^FX"],
    },
    "vme": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/"
               "Value-and-Momentum-Everywhere-Factors-Monthly.xlsx",
        "sheet": "VME Factors",
        "header": ["DATE", "VAL", "MOM", "VAL^SS", "MOM^SS", "VAL^AA", "MOM^AA",
                   "VALLS_VME_US90", "MOMLS_VME_US90", "VALLS_VME_UK90", "MOMLS_VME_UK90",
                   "VALLS_VME_ROE90", "MOMLS_VME_ROE90", "VALLS_VME_JP90", "MOMLS_VME_JP90",
                   "VALLS_VME_EQ", "MOMLS_VME_EQ", "VALLS_VME_FX", "MOMLS_VME_FX",
                   "VALLS_VME_FI", "MOMLS_VME_FI", "VALLS_VME_COM", "MOMLS_VME_COM"],
    },
}


class AQRFetchError(RuntimeError):
    pass


def _cell(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _as_date(v):
    """A data row's first cell as a Timestamp, or None if it is not a date."""
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return pd.Timestamp(v)
    s = _cell(v)
    if s is None:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.Timestamp(dt.datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def parse_sheet(raw: pd.DataFrame, header: list) -> pd.DataFrame:
    """The factor table inside a raw (header=None) sheet. Raises on any surprise."""
    want = [None if h is None else h for h in header]
    hdr = None
    for i in range(min(80, len(raw))):
        row = [_cell(v) for v in raw.iloc[i, :len(want)].tolist()]
        if row == want:
            hdr = i
            break
    if hdr is None:
        raise AQRFetchError(f"no header row equal to {want}; the file layout changed -- look at it")
    extra = [_cell(v) for v in raw.iloc[hdr, len(want):].tolist()]
    if any(e is not None for e in extra):
        raise AQRFetchError(f"header has extra columns {[e for e in extra if e]}")
    names = [h for h in want[1:]]
    rows = []
    for i in range(hdr + 1, len(raw)):
        d = _as_date(raw.iat[i, 0])
        if d is None:
            break
        vals = []
        for j in range(1, len(want)):
            c = raw.iat[i, j]
            if _cell(c) is None:
                vals.append(np.nan)
                continue
            try:
                vals.append(float(c))
            except (TypeError, ValueError) as exc:
                raise AQRFetchError(f"row {d.date()} column {want[j]}: non-numeric {c!r}") from exc
        rows.append([d] + vals)
    if not rows:
        raise AQRFetchError("no data rows under the header")
    df = pd.DataFrame(rows, columns=["date"] + names)
    if not df["date"].is_monotonic_increasing or df["date"].duplicated().any():
        raise AQRFetchError("dates are not strictly increasing")
    per = df["date"].dt.to_period("M")
    if (per.diff().iloc[1:].apply(lambda x: x.n) != 1).any():
        raise AQRFetchError("months are not consecutive (a gap or a repeat)")
    big = (df[names].abs() > 1.0).any(axis=1)
    if big.any():
        raise AQRFetchError(f"|monthly return| > 1 in rows {df.loc[big, 'date'].dt.date.tolist()[:5]}"
                            " -- a unit change (percent?)")
    return df


def fetch(name: str) -> tuple[bytes, str]:
    spec = FILES[name]
    req = urllib.request.Request(spec["url"], headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
            last_mod = r.headers.get("Last-Modified") or "absent"
    except Exception as exc:                                  # noqa: BLE001
        raise AQRFetchError(f"{spec['url']} could not be fetched: {exc!r}") from exc
    return blob, last_mod


def build(name: str) -> pd.DataFrame:
    spec = FILES[name]
    blob, last_mod = fetch(name)
    book = pd.ExcelFile(io.BytesIO(blob))
    if not book.sheet_names or book.sheet_names[0] != spec["sheet"]:
        raise AQRFetchError(f"{name}: first sheet {book.sheet_names[:1]} != {spec['sheet']!r}")
    df = parse_sheet(book.parse(spec["sheet"], header=None), spec["header"])
    df["source_url"] = spec["url"]
    df["file_sha256"] = hashlib.sha256(blob).hexdigest()
    df["http_last_modified"] = last_mod
    df["fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    df["last_data_month"] = df["date"].max().strftime("%Y-%m")
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", default=str(CACHE),
                    help="cache directory (default results/xasset/_cache_xasset); never under data/")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir).resolve()
    if (REPO / "data").resolve() in [out_dir, *out_dir.parents]:
        raise SystemExit(f"refusing to write under data/: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        df = build(name)
        path = out_dir / f"aqr_{name}_monthly.parquet"
        df.to_parquet(path, index=False)
        cols = [c for c in df.columns if c not in ("date", "source_url", "file_sha256",
                                                    "http_last_modified", "fetched_at_utc",
                                                    "last_data_month")]
        print(f"{name}: {len(df)} months {df.date.min().date()}..{df.date.max().date()}; "
              f"file sha256 {df.file_sha256.iloc[0][:16]}..; Last-Modified "
              f"{df.http_last_modified.iloc[0]}; columns {cols} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
