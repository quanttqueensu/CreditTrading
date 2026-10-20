"""Fetch FEMA's disaster declarations (OpenFEMA, public) for the muni hazard-flag gate B2.

WHY THIS EXISTS
---------------
Path B2 of the team lead's 2026-10-19 list asks whether disasters that hit a
state a muni CEF holds move the fund's discount before its matrix-priced NAV.
The event calendar is FEMA's declarations: dated, public, free, and published by
the agency that makes them. `CLAUDE.md` forbids hand-copying a data series, so
the calendar comes from this fetcher and nowhere else.

SOURCE AND TERMS (fetched 2026-10-20; docs/REFERENCES.md §12aw)
---------------------------------------------------------------
* Endpoint: `https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries`
  (OpenFEMA, version v2). No key, no account. One row per designated area
  (county, tribal area or statewide) per declaration.
* Terms: https://www.fema.gov/about/openfema/terms-conditions ("Last updated
  January 22, 2025"). "Data accessed through FEMA's API does not include
  controls over its end use." Users "should cite the specific API endpoint
  (including the version)" and the date of access, and must state: "This
  product uses the Federal Emergency Management Agency's OpenFEMA API, but is
  not endorsed by FEMA." No rate limit is stated; we page at 10,000 rows (the
  v2 maximum per call [S: OpenFEMA API documentation, not re-read]) with a
  pause between calls, so a full pull is under ten requests.

This product uses the Federal Emergency Management Agency's OpenFEMA API, but
is not endorsed by FEMA.

WHAT IS WRITTEN
---------------
* `results/events/muni_hazard/_cache_fema/page_<skip>.json`: each raw page,
  gitignored (`results/**/_cache_*`). `fetch_meta.json` beside them records
  each URL, the API's own `rundate`, byte count and SHA-256.
* `results/events/muni_hazard/fema_declarations_state.csv`: ONE ROW PER
  (femaDeclarationString), i.e. per declaration per state, tracked. Columns:
  declaration string, disaster number, state, type (DR major disaster, EM
  emergency, FM fire management), incident type, title, declaration date,
  incident begin and end dates, incidentId, the number of designated areas and
  whether any is statewide, and the API's latest `lastRefresh` among the rows.

LOOKAHEAD, STATED (H7)
----------------------
`declarationDate` is the date the declaration was made, so a state-level flag
keyed on it is knowable that day. Designated AREAS are added to a declaration
after it is made, and this endpoint does not date each addition; the area count
in the CSV is therefore as of the fetch, not as of the declaration, and must
never key a historical flag. The gate uses the state and the declaration date
only.

NO SILENT FALLBACKS
-------------------
A non-200 response, a page whose row count disagrees with the API's own
`count`, or a missing field raises naming what was missing. Nothing is
defaulted. Tests (`scripts/events/tests/test_muni_hazard_gate.py`) exercise the
aggregation offline; the root conftest blocks the network in tests.

Run: `python3 scripts/events/fetch_fema_declarations.py` (network: www.fema.gov).
     `python3 scripts/events/fetch_fema_declarations.py --offline` rebuilds the
     CSV from the cached pages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "results" / "events" / "muni_hazard"
CACHE = OUT_DIR / "_cache_fema"
CSV_OUT = OUT_DIR / "fema_declarations_state.csv"
ENDPOINT = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
ENTITY = "DisasterDeclarationsSummaries"
PAGE = 10000
PAUSE_S = 1.0
# Declarations from 2000 on: the CEF panels' usable fit sample starts 2005
# (band_frontier.SAMPLE_START); five earlier years cost one page and let a reader
# see the calendar's density before the sample.
SINCE = "2000-01-01T00:00:00.000Z"
FIELDS = ("femaDeclarationString", "disasterNumber", "state", "declarationType",
          "declarationDate", "incidentType", "declarationTitle", "incidentBeginDate",
          "incidentEndDate", "incidentId", "designatedArea", "fipsCountyCode",
          "lastRefresh")
UA = "QUANTT research (public repo; OpenFEMA terms 2025-01-22 accepted)"


class FemaError(RuntimeError):
    """The API refused, or returned something this fetcher cannot vouch for."""


def _url(skip: int) -> str:
    from urllib.parse import quote
    sel = ",".join(FIELDS)
    flt = f"declarationDate ge '{SINCE}'"
    return (f"{ENDPOINT}?$select={sel}&$filter={quote(flt)}&$orderby=id"
            f"&$top={PAGE}&$skip={skip}&$inlinecount=allpages")


def fetch() -> list[dict]:
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    meta, rows, skip, total = [], [], 0, None
    while True:
        url = _url(skip)
        r = requests.get(url, timeout=120, headers={"User-Agent": UA, "Accept": "application/json"})
        if r.status_code != 200:
            raise FemaError(f"OpenFEMA returned HTTP {r.status_code} for {url}")
        body = r.content
        (CACHE / f"page_{skip:06d}.json").write_bytes(body)
        js = json.loads(body)
        md = js.get("metadata")
        if md is None or ENTITY not in js:
            raise FemaError(f"page at skip={skip} has no metadata or no {ENTITY} array")
        total = md["count"] if total is None else total
        if md["count"] != total:
            raise FemaError(f"the API's count moved during the pull ({total} -> {md['count']}); re-run")
        page = js[ENTITY]
        rows.extend(page)
        meta.append(dict(url=url, rundate=md.get("rundate"), rows=len(page), bytes=len(body),
                         sha256=hashlib.sha256(body).hexdigest()))
        skip += PAGE
        if skip >= total:
            break
        time.sleep(PAUSE_S)
    if len(rows) != total:
        raise FemaError(f"fetched {len(rows)} rows against the API's count of {total}")
    (CACHE / "fetch_meta.json").write_text(json.dumps(dict(
        fetched_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        endpoint=ENDPOINT, version="v2", since=SINCE, count=total, pages=meta,
        attribution=("This product uses the Federal Emergency Management Agency's OpenFEMA API, "
                     "but is not endorsed by FEMA.")), indent=1))
    return rows


def load_cached() -> list[dict]:
    meta_p = CACHE / "fetch_meta.json"
    if not meta_p.exists():
        raise FemaError(f"no cached pull at {meta_p}; run without --offline first")
    meta = json.loads(meta_p.read_text())
    rows = []
    for p in sorted(CACHE.glob("page_*.json")):
        rows.extend(json.loads(p.read_text())[ENTITY])
    if len(rows) != meta["count"]:
        raise FemaError(f"cache holds {len(rows)} rows against the recorded count {meta['count']}")
    return rows


def aggregate(rows: list[dict]):
    """One row per declaration string (a declaration in one state). Raises on a missing field."""
    import pandas as pd
    if not rows:
        raise FemaError("no declaration rows to aggregate")
    df = pd.DataFrame(rows)
    missing = [f for f in FIELDS if f not in df.columns]
    if missing:
        raise FemaError(f"declaration rows lack field(s) {missing}")
    for c in ("femaDeclarationString", "state", "declarationType", "declarationDate", "incidentType"):
        if df[c].isna().any():
            raise FemaError(f"{int(df[c].isna().sum())} row(s) have no {c}")
    for c in ("declarationDate", "incidentBeginDate", "incidentEndDate", "lastRefresh"):
        df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(None)
    df["statewide"] = df["designatedArea"].astype(str).str.lower().str.contains("statewide") | (
        df["fipsCountyCode"].astype(str) == "000")
    g = df.groupby("femaDeclarationString", sort=False)
    # A declaration string names one state, one type and one date; check, never assume.
    for c in ("state", "declarationType", "declarationDate", "incidentType", "disasterNumber"):
        n = g[c].nunique(dropna=False)
        if (n > 1).any():
            bad = list(n[n > 1].index[:5])
            raise FemaError(f"declaration(s) {bad} carry more than one {c}")
    out = g.agg(disasterNumber=("disasterNumber", "first"), state=("state", "first"),
                declarationType=("declarationType", "first"), incidentType=("incidentType", "first"),
                declarationTitle=("declarationTitle", "first"),
                declarationDate=("declarationDate", "first"),
                incidentBeginDate=("incidentBeginDate", "min"), incidentEndDate=("incidentEndDate", "max"),
                incidentId=("incidentId", "first"), n_areas_at_fetch=("designatedArea", "size"),
                any_statewide_at_fetch=("statewide", "any"), last_refresh=("lastRefresh", "max"))
    out = out.reset_index().sort_values(["declarationDate", "femaDeclarationString"]).reset_index(drop=True)
    for c in ("declarationDate", "incidentBeginDate", "incidentEndDate"):
        out[c] = out[c].dt.strftime("%Y-%m-%d")
    out["last_refresh"] = out["last_refresh"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="rebuild the CSV from the cached pages")
    a = ap.parse_args(argv)
    rows = load_cached() if a.offline else fetch()
    out = aggregate(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CSV_OUT, index=False)
    print(f"{len(rows)} area rows -> {len(out)} declaration-state rows; "
          f"{out.declarationDate.min()} .. {out.declarationDate.max()} -> {CSV_OUT.relative_to(REPO)}")
    print("This product uses the Federal Emergency Management Agency's OpenFEMA API, but is not endorsed by FEMA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
