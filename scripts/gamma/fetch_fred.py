"""One FRED series from the keyless CSV endpoint, validated, as (date, value).

    python3 scripts/gamma/fetch_fred.py DGS1MO --out <path.parquet>

WHY THIS EXISTS (2026-10-11, RESEARCH_PLAN_2026-10-09 item 0.9)
--------------------------------------------------------------
The TLT implied-vol build (`scripts/gamma/tlt_atm_iv.py`) discounts option
prices and recovers forwards at the 1-month Treasury bill rate, FRED `DGS1MO`.
The 2026-10-09 agent that first built it curled the CSV into a scratchpad that
no longer exists. The repo's own `data/riskfree_daily.parquet` carries DGS3MO
only, has no fetcher (`data/README.md` lists it as "not yet built") and stops
2026-07-16, so it is not a substitute: a fetched series gets a fetcher.

`--out` is REQUIRED. `data/` is read by the live sleeve (CLAUDE.md landmine 9),
so this script never picks a path under it on its own.

WHAT IS AND IS NOT A MISSING VALUE
----------------------------------
FRED marks a non-publication day (a federal holiday on which the H.15 rate is
not published) with an empty field or ".". Those rows are DROPPED, never
filled: a consumer that needs the rate "as of" a date takes the last published
value on or before it and says so. A non-numeric value that is NOT one of those
two markers raises.

SOURCE: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SID>` (keyless;
`docs/REFERENCES.md` §8). Header `observation_date,<SID>` as of 2026-10-09; the
older `DATE,<SID>` header is also accepted. Values are percent per annum.
`BAML*` series silently truncate to ~3 years on this endpoint (REFERENCES §8),
so this fetcher refuses them rather than hand back a short series.
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
_UA = "Mozilla/5.0 (QUANTT research; contact via repo)"
MISSING_MARKERS = {"", "."}


class FetchError(RuntimeError):
    """The source did not give us something we can use. Never returns a default."""


def parse(sid: str, raw: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False)
    if list(df.columns) not in (["observation_date", sid], ["DATE", sid]):
        raise FetchError(f"{sid}: unexpected header {list(df.columns)}; FRED changed "
                         f"the CSV schema. Look at it before changing this parser.")
    date_col = df.columns[0]
    vals = df[sid].str.strip()
    keep = ~vals.isin(MISSING_MARKERS)
    num = pd.to_numeric(vals[keep], errors="raise")   # anything else non-numeric raises
    out = pd.DataFrame({
        "date": pd.to_datetime(df.loc[keep, date_col], format="%Y-%m-%d", errors="raise"),
        "value": num.astype(float),
    }).sort_values("date").reset_index(drop=True)
    if out.empty:
        raise FetchError(f"{sid}: no numeric rows")
    if out["date"].duplicated().any():
        raise FetchError(f"{sid}: duplicated dates in the source")
    out["series"] = sid
    out["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def fetch(sid: str, timeout: int = 60) -> pd.DataFrame:
    if sid.upper().startswith("BAML"):
        raise FetchError(f"{sid}: BAML* series truncate to ~3 years on the keyless "
                         f"endpoint (docs/REFERENCES.md §8); not fetched here")
    url = URL.format(sid=sid)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="strict")
    except Exception as exc:                                  # noqa: BLE001
        raise FetchError(f"{url} could not be fetched: {exc!r}") from exc
    return parse(sid, raw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sid")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    df = fetch(a.sid)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"{a.sid}: {len(df):,} rows {df.date.min().date()} .. {df.date.max().date()}, "
          f"last {df.value.iloc[-1]:.2f}% -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
