"""CRSP extracts for the CEF event studies (merger pairs, term CEFs). Read-only on R2.

WHY THIS EXISTS
---------------
The 2026-10-08/09 targeted pass (`results/cef/SCALING_RESEARCH_2026-10-08.md`
§7) measured the NAV-for-NAV merger pair and term-CEF pull-to-par with scratch
scripts that each pulled their own CRSP extracts into a session scratchpad,
which was then deleted. Item 0.9 of `results/cef/RESEARCH_PLAN_2026-10-09.md`
brings them into the repo. Both studies read the same four CRSP tables, so the
pull lives here once, and both re-runs read identical inputs.

THE TIME HOLDOUT IS ENFORCED HERE, NOT BY THE CALLER
----------------------------------------------------
The 2023-01-01 time holdout is sealed (`docs/SYSTEM.md` §5, team lead
2026-10-09). Every return-based statistic in these studies must use data
strictly before it. So `daily()` pulls `dsf` rows with `date < 2023-01-01` and
nothing later, and asserts it on what came back: a caller cannot compute a
post-2022 return from this module even by accident. Names, delistings and
distribution records are NOT return data and are pulled for every date, so an
event COUNT can see 2023-24 (CRSP's mirror ends 2024-12-31). A caller that
counts 2023+ events must label them as counts only.

CACHE
-----
Extracts are written to `results/events/_cache_crsp/` (gitignored by
`results/**/_cache_*`) with the pull time in `_manifest.json`. A cached
extract is reused only if its name matches exactly; the permno list is part of
the name (a hash), so a different request never silently reads a stale file.
`--refresh` re-pulls. Nothing here writes to `data/` (CLAUDE.md landmine 9) or
to the bucket.

CRSP CONVENTIONS RELIED ON (each re-checked on our extracts where it matters)
----------------------------------------------------------------------------
- Share codes 14 and 44 are closed-end funds
  (`results/data/cef_crosscheck_crsp_2026-09-28.md`).
- `prc` is negative when CRSP used the bid/ask average; magnitudes are used.
- `ret` is missing (NaN in the mirror) when CRSP had no valid price; the next
  valid `ret` is then measured from the last valid price. `merger_pairs.py`
  verifies this on its own windows before compounding across a gap
  (`window_return`), rather than assuming it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

CACHE = REPO / "results" / "events" / "_cache_crsp"
TIME_HOLDOUT = pd.Timestamp("2023-01-01")
CEF_SHRCD = (14, 44)
UNIVERSE_CSV = REPO / "data" / "cef" / "cef_universe.csv"


def _manifest_write(name: str, n: int, sql: str) -> None:
    path = CACHE / "_manifest.json"
    m = json.loads(path.read_text()) if path.exists() else {}
    m[name] = {"pulled_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "rows": n, "sql": sql}
    path.write_text(json.dumps(m, indent=1, sort_keys=True))


def manifest() -> dict:
    """When each cached extract was pulled (for the note's data-date lines)."""
    path = CACHE / "_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: nothing has been pulled yet")
    return json.loads(path.read_text())


def _pull(name: str, sql_template: str, refresh: bool) -> pd.DataFrame:
    """Run `sql_template` (with {dsf}/{names}/... placeholders) once and cache it."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    from src.data.r2 import connect, q, r2_path
    paths = {t: r2_path("crsp_a_stock", t) for t in ("dsf", "dsenames", "dsedelist", "dsedist")}
    sql = sql_template.format(**paths)
    df = q(connect(), sql)
    df.to_parquet(path)
    # The manifest records the template, not the expanded SQL: the expanded
    # form carries the bucket name, which never goes into a tracked file.
    _manifest_write(name, len(df), sql_template)
    return df


_CEF_PERMNOS = "SELECT DISTINCT permno FROM read_parquet('{dsenames}') WHERE shrcd IN (14, 44)"


def names(refresh: bool = False) -> pd.DataFrame:
    """Every `dsenames` record of (a) any permno that was ever a CEF (share code
    14/44), at any date, and (b) any security whose name record ends 2005 or
    later. (b) is what the merger study needs to name an acquirer that is not a
    CEF (a BDC with share code 11, an ETF); (a) is what the term study needs to
    reach back to 1988."""
    df = _pull("dsenames",
               "SELECT * FROM read_parquet('{dsenames}') "
               f"WHERE permno IN ({_CEF_PERMNOS}) OR nameendt >= DATE '2005-01-01'",
               refresh)
    for c in ("namedt", "nameendt"):
        df[c] = pd.to_datetime(df[c])
    return df


def delistings(refresh: bool = False) -> pd.DataFrame:
    """`dsedelist` for every permno that was ever a CEF, all dates."""
    df = _pull("dsedelist",
               f"SELECT * FROM read_parquet('{{dsedelist}}') WHERE permno IN ({_CEF_PERMNOS})",
               refresh)
    for c in ("dlstdt", "dlpdt", "nextdt"):
        df[c] = pd.to_datetime(df[c])
    for c in ("dlamt", "dlret", "dlretx", "dlprc"):
        df[c] = df[c].astype(float)
    return df


def _plist(permnos) -> tuple[str, str]:
    ps = sorted({int(p) for p in permnos})
    if not ps:
        raise ValueError("empty permno list")
    s = ",".join(map(str, ps))
    return s, hashlib.sha1(s.encode()).hexdigest()[:10]


def distributions(permnos, refresh: bool = False) -> pd.DataFrame:
    """`dsedist` rows for `permnos`, all dates (distribution records, not returns)."""
    s, h = _plist(permnos)
    df = _pull(f"dsedist_{h}", f"SELECT * FROM read_parquet('{{dsedist}}') WHERE permno IN ({s})",
               refresh)
    for c in ("exdt", "paydt", "dclrdt", "rcrddt"):
        df[c] = pd.to_datetime(df[c])
    for c in ("divamt", "facpr", "facshr"):
        df[c] = df[c].astype(float)
    return df


def daily(permnos, refresh: bool = False) -> pd.DataFrame:
    """`dsf` rows for `permnos`, every date BEFORE 2023-01-01 and none after.

    The cut is in the SQL and asserted on the result (module docstring).
    `prc` is returned as a magnitude; `ret` keeps CRSP's missing values as NaN.
    """
    s, h = _plist(permnos)
    df = _pull(f"dsf_{h}",
               "SELECT permno, date, prc, ret, retx, vol, shrout, cfacpr "
               f"FROM read_parquet('{{dsf}}') WHERE permno IN ({s}) AND date < DATE '2023-01-01'",
               refresh)
    df["date"] = pd.to_datetime(df["date"])
    if len(df) and df["date"].max() >= TIME_HOLDOUT:
        raise AssertionError(f"dsf extract reaches {df['date'].max().date()}: the 2023-01-01 "
                             "time holdout is sealed")
    df["prc"] = df["prc"].astype(float).abs()
    for c in ("ret", "retx", "vol", "shrout", "cfacpr"):
        df[c] = df[c].astype(float)
    return df


def universe() -> pd.DataFrame:
    """`data/cef/cef_universe.csv`: the deployed 13, the 4 dropped on Alpaca, and
    the 27-name comparison set (H9)."""
    u = pd.read_csv(UNIVERSE_CSV)
    if "ticker" not in u or "start" not in u:
        raise KeyError(f"{UNIVERSE_CSV} lacks a ticker or start column")
    return u


def universe_permnos(nm: pd.DataFrame) -> dict[str, list[int]]:
    """Ticker -> every CRSP permno that carried that ticker while the universe's
    price history for it runs.

    A universe ticker matches a CEF name record (share code 14/44) whose record
    ends on or after the fund's first date in `cef_universe.csv`. That keeps
    BGT (the Blackstone/BlackRock term trust of 1990-2002, permno 75610) apart
    from the universe BGT (2004-).

    MORE THAN ONE PERMNO IS POSSIBLE AND IS KEPT. The panel behind
    `cef_universe.csv` is keyed by ticker, so where a ticker passed from one fund
    to another inside that window (EMD: permnos 78011 to 2008, 79329 to
    2016-12-16, 89970 since), the universe's history spans all of them, and a
    holdout filter must exclude all of them. Zero matches raises: a holdout
    filter that silently matched nothing would leak.
    """
    u = universe()
    out = {}
    cef = nm[nm["shrcd"].isin(CEF_SHRCD)]
    for tk, start in zip(u["ticker"], pd.to_datetime(u["start"])):
        hit = sorted(int(p) for p in cef[(cef["ticker"] == tk) & (cef["nameendt"] >= start)]["permno"].unique())
        if not hit:
            raise LookupError(f"universe ticker {tk}: no CRSP CEF permno matches (start {start.date()})")
        out[tk] = hit
    return out


def name_at(nm: pd.DataFrame, permno: int, when: pd.Timestamp) -> pd.Series | None:
    """The name record of `permno` in force on `when`, else None (stated, not guessed)."""
    r = nm[(nm["permno"] == permno) & (nm["namedt"] <= when) & (nm["nameendt"] >= when)]
    if len(r) == 0:
        return None
    return r.sort_values("namedt").iloc[-1]


def last_name(nm: pd.DataFrame) -> pd.DataFrame:
    """Each permno's last name record (share code at delisting, ticker, name)."""
    return nm.sort_values(["permno", "nameendt"]).groupby("permno").tail(1)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Pull (or refresh) the shared CRSP extracts.")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    nm = names(a.refresh)
    dl = delistings(a.refresh)
    print(f"dsenames rows {len(nm)}; last nameendt {nm['nameendt'].max().date()}")
    print(f"dsedelist rows {len(dl)}; last dlstdt {dl['dlstdt'].max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
