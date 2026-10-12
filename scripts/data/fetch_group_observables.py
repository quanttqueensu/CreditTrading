"""Fetch the pre-declared per-group observables for C2 (W10 Parts C and D) into a
gitignored research cache.

    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_group_observables.py
    python3 scripts/data/fetch_group_observables.py --coverage   # read the cache, print coverage

WHY THIS EXISTS
---------------
results/cef/RESEARCH_PLAN_2026-10-09.md section 3 row 7 (C2) names the
observables a per-group conditional fair value may use, declared before any
test: "HY OAS and CCC-BB; muni leverage cost; SOFR for loans; PIMCO repo cost"
(from results/cef/RESEARCH_AGENDA_2026-10-08.md Track C1). None had a fetcher
in this repository on 2026-10-12. `data/spreads_daily.parquet` holds HY OAS and
the bucket yields, but its builder exists only at tag `pre-clean-slate`
(`scripts/build_spreads.py`) and it stops 2026-07-16; a fetched series gets a
fetcher (CLAUDE.md). This script fetches; it decides nothing and fits nothing.

WHAT EACH OBSERVABLE IS, AND WHERE IT COMES FROM
------------------------------------------------
| series            | what                                                        | source                                     |
|-------------------|-------------------------------------------------------------|--------------------------------------------|
| hy_oas            | ICE BofA US High Yield OAS, % (BAMLH0A0HYM2)                 | R2 `frb_all.rates_daily` + FRED patch      |
| bb_ey, ccc_ey     | ICE BofA BB / CCC-and-lower effective yields, %              | R2 `frb_all.rates_daily` + FRED patch      |
| ccc_minus_bb_ey   | ccc_ey - bb_ey, % (DERIVED here, same-date rows only)        | the two rows above                         |
| sifma             | SIFMA Municipal Swap Index, %, WEEKLY (Wednesday reset)      | sifma.org historical files (two)           |
| sofr              | SOFR, %                                                      | FRED SOFR (keyless CSV)                    |
| dff               | effective federal funds rate, %                              | FRED DFF (keyless CSV)                     |
| repo_tri_corp     | tri-party repo average rate, corporate-debt collateral, %    | OFR Short-term Funding Monitor API         |
| repo_tri_tsy      | tri-party repo average rate, Treasury collateral, %          | OFR Short-term Funding Monitor API         |

THE PROXIES, NAMED AS PROXIES
-----------------------------
* CCC-BB: the OAS buckets (BAMLH0A3HYC, BAMLH0A1HYBB) are ICE-licensed. FRED's
  keyless endpoint returns only their trailing ~3 years, and the R2 mirror
  carries the buckets only as effective yields (checked 2026-10-12: the mirror's
  BAML columns are bamlh0a0hym2 and five *ey series). So the full-history
  quality spread is the EFFECTIVE-YIELD difference, which differs from the OAS
  difference by the Treasury curve between the two buckets' durations. It is a
  proxy and is labelled one wherever it is used.
* Loans before SOFR (2018-04): JFR's loans reset off LIBOR, and FRED no longer
  serves LIBOR (USD3MTD156N returned HTTP 404 on 2026-10-12). `dff` is the
  only unlicensed daily base rate covering 2013-2018; a consumer that splices
  it under SOFR must say so.
* PIMCO repo cost: what a PIMCO fund actually pays on its reverse repos is in
  its N-CSR/N-CSRS (semi-annual, prose) and is NOT fetched here (plan items 0.7
  and 0.8 own EDGAR). The daily observable is the OFR tri-party rate on
  corporate-debt collateral, which starts 2014-08-22 -- after the deployed
  book's first position (2013-06-21). Treasury-collateral tri-party is fetched
  beside it so the collateral spread can be formed.
* Muni leverage cost: the deployed munis (MHD, MQY) are BlackRock funds levered
  through preferred shares (docs/BRIEF.md section 3, [S]); whether their resets
  track SIFMA weekly is a filing question not settled here. SIFMA is the
  pre-declared muni financing observable either way.

THE SEAMS (no silent splice)
----------------------------
* ICE series: R2 history through the mirror's last row, FRED rows strictly
  after it. FRED's keyless window must OVERLAP the R2 history by at least
  MIN_OVERLAP sessions and agree EXACTLY on every overlapping date, or this
  raises (measured 2026-10-12: 352 overlapping sessions, max |diff| 0.0 on all
  three). `scripts/gamma/fetch_fred.py` refuses BAML* on purpose because the
  keyless window is short; this script fetches it only as a patch whose
  agreement with the full history is checked.
* SIFMA: the 1989-2014 file ends 2014-08-13 and the current file starts
  2014-08-20; one week apart, no overlap, no gap. Asserted. Every row must be a
  Wednesday or the publication day after a Wednesday holiday; anything else
  raises with the date.

WHERE IT WRITES. `results/cef/w10/_cache_w10/group_observables.parquet`
(gitignored: `results/**/_cache_*`). ICE data is licensed and this repository
is public: nothing fetched is committed. Long format: date, series, value,
unit, source, fetched_at_utc. Never under data/ (CLAUDE.md landmine 9).

LIVE USE. None. If C2 ever deploys a conditioner, its live source must be
re-decided: R2 never feeds the live path (docs/DATA.md section 1), and FRED's
BAML window is about three years.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.gamma.fetch_fred import URL as FRED_URL, _UA, FetchError, fetch as fred_fetch, parse as fred_parse  # noqa: E402

CACHE = REPO / "results" / "cef" / "w10" / "_cache_w10"
OUT = CACHE / "group_observables.parquet"
MIN_OVERLAP = 100
ICE = {"hy_oas": "BAMLH0A0HYM2", "bb_ey": "BAMLH0A1HYBBEY", "ccc_ey": "BAMLH0A3HYCEY"}
FRED_PLAIN = {"sofr": "SOFR", "dff": "DFF"}
OFR = {"repo_tri_corp": "REPO-TRI_AR_CORD-F", "repo_tri_tsy": "REPO-TRI_AR_T-F"}
OFR_URL = "https://data.financialresearch.gov/v1/series/timeseries?mnemonic={m}"
SIFMA_PAGE = "https://www.sifma.org/resources/guides-playbooks/about-the-municipal-swap-index"
SIFMA_FILES = (
    ("https://www.sifma.org/wp-content/uploads/2017/07/psaswaps_excel_file.xls", "SIFMA_SWAP_INDEX_HISTORY"),
    ("https://www.sifma.org/wp-content/uploads/2024/01/Muni-Swap-Historical-Data.xlsx", "MUNIPSA"),
)
FIT_WINDOW = ("2013-06-21", "2022-12-30")     # the deployed set's span before the sealed holdout


class ObservableError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as exc:                                   # noqa: BLE001
        raise ObservableError(f"{url} could not be fetched: {exc!r}") from exc


def _rows(df: pd.DataFrame, series: str, unit: str, source: str) -> pd.DataFrame:
    out = df[["date", "value"]].copy()
    out["series"], out["unit"], out["source"], out["fetched_at_utc"] = series, unit, source, _now()
    return out


# ------------------------------------------------------------------------- ICE (R2 + FRED patch)

def ice_history() -> pd.DataFrame:
    """R2 mirror rows for the three ICE series (licensed; read-only)."""
    from src.data import r2
    cfg = r2.load_config()
    con = r2.connect(cfg)
    cols = [v.lower() for v in ICE.values()]
    h = con.execute(f"SELECT date, {', '.join(cols)} FROM "
                    f"read_parquet('{r2.r2_path('frb_all', 'rates_daily', cfg)}') ORDER BY date").df()
    h["date"] = pd.to_datetime(h["date"])
    return h


def splice_ice(series: str, sid: str, hist: pd.DataFrame, patch: pd.DataFrame) -> pd.DataFrame:
    """History through its last row, then the FRED patch strictly after it.
    Raises unless the two overlap by >= MIN_OVERLAP dates and agree exactly."""
    h = hist[["date", sid.lower()]].dropna().rename(columns={sid.lower(): "value"})
    if h.empty:
        raise ObservableError(f"{sid}: no rows in the R2 mirror")
    m = patch.merge(h, on="date", suffixes=("_fred", "_r2"))
    if len(m) < MIN_OVERLAP:
        raise ObservableError(f"{sid}: FRED keyless window ({patch.date.min().date()}..) overlaps the R2 "
                              f"history (..{h.date.max().date()}) on {len(m)} dates < {MIN_OVERLAP}; the seam "
                              f"cannot be checked, so nothing is spliced")
    bad = m[(m.value_fred - m.value_r2).abs() > 1e-9]
    if len(bad):
        raise ObservableError(f"{sid}: FRED and the R2 mirror disagree on {len(bad)} of {len(m)} overlapping "
                              f"dates, e.g. {bad.head(3).to_dict('records')}. Decide which is right; not averaged.")
    tail = patch[patch.date > h.date.max()][["date", "value"]]
    a = _rows(h, series, "pct", "r2 frb_all.rates_daily")
    b = _rows(tail, series, "pct", f"fred keyless {sid} (patch after the mirror; seam {len(m)} dates exact)")
    return pd.concat([a, b], ignore_index=True)


def fetch_ice() -> tuple[pd.DataFrame, dict]:
    hist = ice_history()
    parts, seams = [], {}
    for series, sid in ICE.items():
        raw = _get(FRED_URL.format(sid=sid)).decode("utf-8", errors="strict")
        patch = fred_parse(sid, raw)
        parts.append(splice_ice(series, sid, hist, patch))
        seams[series] = dict(r2_last=str(hist[["date", sid.lower()]].dropna().date.max().date()),
                             fred_first=str(patch.date.min().date()), fred_last=str(patch.date.max().date()))
    df = pd.concat(parts, ignore_index=True)
    w = df.pivot_table(index="date", columns="series", values="value")
    both = w[["bb_ey", "ccc_ey"]].dropna()
    q = pd.DataFrame({"date": both.index, "value": (both.ccc_ey - both.bb_ey).values})
    df = pd.concat([df, _rows(q, "ccc_minus_bb_ey", "pct",
                              "derived: ccc_ey - bb_ey, same-date rows (EFFECTIVE-YIELD proxy for CCC-BB OAS)")],
                   ignore_index=True)
    return df, seams


# ------------------------------------------------------------------------- SIFMA

def parse_sifma(blob: bytes, sheet: str) -> pd.DataFrame:
    """Two columns, a header row 'Date' / 'Index Value', newest first. Raises on
    any other shape, a non-date, a non-number or a duplicate."""
    x = pd.read_excel(io.BytesIO(blob), sheet_name=sheet, header=None)
    hdr = [str(v).strip() for v in x.iloc[0, :2]]
    if hdr != ["Date", "Index Value"]:
        raise ObservableError(f"SIFMA sheet {sheet}: header {hdr} != ['Date', 'Index Value']")
    body = x.iloc[1:, :2].dropna(how="all")
    out = pd.DataFrame({"date": pd.to_datetime(body.iloc[:, 0], errors="raise"),
                        "value": pd.to_numeric(body.iloc[:, 1], errors="raise").astype(float)})
    if out.date.duplicated().any():
        raise ObservableError(f"SIFMA sheet {sheet}: duplicated dates")
    return out.sort_values("date").reset_index(drop=True)


# Five rows in SIFMA's own history break the weekly pattern. Each was inspected
# on 2026-10-12 against its neighbours and is KEPT AS PUBLISHED (it is SIFMA's
# data, not a parse error): 1991-06-13 (one day after 06-12), 1991-10-09 (a
# 14-day gap before it), 1996-09-16 (a Monday print replacing 09-11; 12 days
# after 09-04), 1996-09-18 (2 days after it), 2008-03-21 (an extra Friday print
# in March 2008). Listed BY DATE so a new irregularity raises instead of being
# waved through by a looser rule. None falls inside the deployed fit window.
KNOWN_IRREGULAR = {pd.Timestamp(d) for d in
                   ("1991-06-13", "1991-10-09", "1996-09-16", "1996-09-18", "2008-03-21")}


def check_weekly(df: pd.DataFrame):
    """Every reset is a Wednesday (or the Thursday after a Wednesday holiday),
    5-9 days after the previous one, except the dates in KNOWN_IRREGULAR."""
    gaps = df.date.diff().dt.days
    odd = df[(~df.date.dt.weekday.isin([2, 3])) | (gaps < 5) | (gaps > 9)]
    new = sorted(set(odd.date) - KNOWN_IRREGULAR)
    if new:
        raise ObservableError(f"SIFMA rows off the weekly pattern and not in KNOWN_IRREGULAR: "
                              f"{[d.date() for d in new][:10]}; inspect before adding them")


def fetch_sifma() -> pd.DataFrame:
    old, new = (parse_sifma(_get(u), s) for u, s in SIFMA_FILES)
    gap = (new.date.min() - old.date.max()).days
    if not (old.date.max() < new.date.min() and 5 <= gap <= 9):
        raise ObservableError(f"SIFMA seam: old file ends {old.date.max().date()}, new starts "
                              f"{new.date.min().date()} ({gap} days); expected one weekly step")
    df = pd.concat([old, new], ignore_index=True)
    check_weekly(df)
    src = f"sifma.org ({SIFMA_FILES[0][0].rsplit('/', 1)[-1]} to {old.date.max().date()}, " \
          f"{SIFMA_FILES[1][0].rsplit('/', 1)[-1]} from {new.date.min().date()}); linked from {SIFMA_PAGE}"
    return _rows(df, "sifma", "pct", src)


# ------------------------------------------------------------------------- FRED, OFR

def fetch_fred_plain() -> pd.DataFrame:
    parts = []
    for series, sid in FRED_PLAIN.items():
        d = fred_fetch(sid)
        parts.append(_rows(d, series, "pct", f"fred keyless {sid}"))
    return pd.concat(parts, ignore_index=True)


def parse_ofr(mnemonic: str, raw: str) -> pd.DataFrame:
    js = json.loads(raw)
    if not isinstance(js, list) or not js or not all(isinstance(r, list) and len(r) == 2 for r in js):
        raise ObservableError(f"OFR {mnemonic}: expected a list of [date, value] pairs")
    df = pd.DataFrame(js, columns=["date", "value"])
    df = df[df.value.notna()]                    # OFR omits confidential cells as null: dropped, never filled
    df["date"] = pd.to_datetime(df.date, format="%Y-%m-%d", errors="raise")
    df["value"] = pd.to_numeric(df.value, errors="raise").astype(float)
    if df.date.duplicated().any():
        raise ObservableError(f"OFR {mnemonic}: duplicated dates")
    return df.sort_values("date").reset_index(drop=True)


def fetch_ofr() -> pd.DataFrame:
    parts = []
    for series, m in OFR.items():
        d = parse_ofr(m, _get(OFR_URL.format(m=m)).decode("utf-8"))
        parts.append(_rows(d, series, "pct", f"OFR Short-term Funding Monitor {m}"))
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------------------------- main

def coverage(df: pd.DataFrame) -> str:
    lo, hi = (pd.Timestamp(x) for x in FIT_WINDOW)
    lines = [f"{'series':<17}{'rows':>7}{'first':>12}{'last':>12}{'rows in fit window':>20}{'first in window':>17}"]
    for s, g in df.groupby("series"):
        w = g[(g.date >= lo) & (g.date <= hi)]
        lines.append(f"{s:<17}{len(g):7d}{str(g.date.min().date()):>12}{str(g.date.max().date()):>12}"
                     f"{len(w):20d}{str(w.date.min().date()) if len(w) else '--':>17}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--coverage", action="store_true", help="read the cache and print coverage only")
    a = ap.parse_args(argv)
    if a.coverage:
        if not OUT.exists():
            raise ObservableError(f"{OUT.relative_to(REPO)} is missing; run without --coverage first")
        print(coverage(pd.read_parquet(OUT)))
        return 0
    ice, seams = fetch_ice()
    df = pd.concat([ice, fetch_sifma(), fetch_fred_plain(), fetch_ofr()], ignore_index=True)
    df = df.sort_values(["series", "date"]).reset_index(drop=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"wrote {len(df):,} rows, {df.series.nunique()} series -> {OUT.relative_to(REPO)}")
    print("ICE seams:", json.dumps(seams))
    print(coverage(df))
    print(f"(fit window = the deployed set's span before the sealed holdout, {FIT_WINDOW[0]}..{FIT_WINDOW[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
