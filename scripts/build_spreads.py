#!/usr/bin/env python3
"""Build data/spreads_daily.parquet and data/riskfree_daily.parquet.

spreads_daily.parquet — LONG format: [date, series, value, source].
  series = lowercase FRED id; value = level in PERCENT (OAS and yields both);
  source = 'crsp-mirror' (row came from the R2 WRDS mirror
  wrds/frb_all/rates_daily.parquet, whose columns are lowercase FRED ids)
  or 'fred' (row fetched from the keyless fredgraph.csv endpoint).

Series requested (present-in-R2 determined at runtime):
  bamlh0a0hym2  HY OAS            bamlc0a0cm    IG corp OAS
  bamlh0a1hybb  BB OAS            bamlh0a2hyb   B OAS
  bamlh0a3hyc   CCC-and-lower OAS bamlc0a4cbbb  BBB OAS
  dgs3mo / dgs2 / dgs10           CMT Treasury yields
R2 (probed 2026-07-19) carries bamlh0a0hym2 + the three dgs series; the five
other OAS series exist there only as effective-yield (*ey) variants, so their
OAS history is fetched in full from FRED.

FRED cap trap: the keyless fredgraph.csv endpoint SILENTLY truncates ICE BofA
(BAML*) series to roughly the last 3 years regardless of cosd (verified again
at build time: cosd=1997-01-01 returned data starting 2023-07-18). fetch_fred()
therefore asserts, on EVERY response, that the returned date range covers the
requested window (small slack for weekends/holidays at the start, publication
lag at the end). BAML series are fetched in <=3-year chunks with overlapping
seams; overlapping observations must agree exactly before stitching, and the
overlap with R2 must also agree exactly (same value on same date).

Splice rule: for series present in R2, the R2 rows are kept through each
series' last non-null R2 date and FRED rows strictly after it are appended
(R2 file ends 2025-02-13; last non-null is 2025-02-12 for bamlh0a0hym2,
2025-02-11 for the dgs series).

riskfree_daily.parquet: [date, dgs3mo, rf_daily] on a Mon-Fri business-day
index spanning the stitched dgs3mo history. Convention: dgs3mo (percent,
annualized 3m CMT) is forward-filled over non-publication weekdays (market
holidays / FRED '.' days), then rf_daily = dgs3mo / 100 / 252 — the simple
daily risk-free accrual under a 252-trading-day year. Weekend rows are not
emitted; joining on any trading calendar therefore always finds a rate.

Run:  python3 scripts/build_spreads.py
"""

import io
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.data.r2 import connect, r2_path, q  # noqa: E402

OUT_SPREADS = REPO / "data" / "spreads_daily.parquet"
OUT_RF = REPO / "data" / "riskfree_daily.parquet"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={cosd}&coed={coed}"
CHUNK_YEARS = 2.5          # < the ~3y silent cap on BAML* series
SEAM_OVERLAP_DAYS = 20     # consecutive chunks share this window; values must match
START_SLACK_DAYS = 7       # returned first date may lag cosd by weekends/holidays
END_SLACK_DAYS = 10        # returned last date may lag coed by publication delay
R2_OVERLAP_DAYS = 400      # FRED patch is fetched this far back into R2 to cross-check

# fred_id -> (description, first observation, mode).
#
# THE CAP IS NOT A CHUNKING PROBLEM (established 2026-07-20). Keyless
# fredgraph.csv/alfredgraph.csv ignore `cosd` entirely for licensed ICE BofA
# (BAML*) series and always return only the trailing ~3 years: asking for
# 1996-1999 still returns 2023-07-18 onward. Chunking therefore cannot recover
# their history — only the R2 mirror can, and it holds every BAML series we
# need through 2025-02-12. Because FRED's trailing window opens in 2023-07 and
# the mirror ends 2025-02, the two overlap and stitch into a full history.
#
# Modes:
#   r2+patch   in the R2 mirror -> mirror history + FRED trailing patch forward.
#   fred_full  unlicensed on FRED -> full history in one guarded fetch.
#
# DELIBERATELY OMITTED: the pure-OAS bucket series (bamlc0a0cm, bamlh0a1hybb,
# bamlh0a2hyb, bamlh0a3hyc, bamlc0a4cbbb). They are licensed, absent from the
# mirror, and therefore only ~3 years deep — a trap sitting next to 30-year
# series. The *ey (effective yield) versions below cover the same rating
# buckets across the full sample; derive bucket spreads from those instead
# (e.g. CCC-BB quality spread, or an *ey series minus the matched Treasury).
SERIES = {
    "bamlh0a0hym2":   ("ICE BofA US High Yield OAS",            "1996-12-31", "r2+patch"),
    "bamlh0a0hym2ey": ("ICE BofA US High Yield effective yield", "1996-12-31", "r2+patch"),
    "bamlc0a0cmey":   ("ICE BofA US Corporate (IG) eff. yield",  "1996-12-31", "r2+patch"),
    "bamlc0a1caaaey": ("ICE BofA AAA eff. yield",                "1996-12-31", "r2+patch"),
    "bamlh0a1hybbey": ("ICE BofA BB eff. yield",                 "1996-12-31", "r2+patch"),
    "bamlh0a3hycey":  ("ICE BofA CCC & Lower eff. yield",        "1996-12-31", "r2+patch"),
    "daaa":           ("Moody's Aaa corporate yield",            "1983-01-03", "r2+patch"),
    "dbaa":           ("Moody's Baa corporate yield",            "1986-01-02", "r2+patch"),
    "dgs3mo":         ("3-Month Treasury CMT",                   "1981-09-01", "r2+patch"),
    "dgs2":           ("2-Year Treasury CMT",                    "1976-06-01", "r2+patch"),
    "dgs10":          ("10-Year Treasury CMT",                   "1962-01-02", "r2+patch"),
    # Unlicensed long-history credit spreads (Moody's minus 10y Treasury), the
    # only credit-spread series free of the ICE cap: 1986 -> present in one call.
    "baa10y":         ("Moody's Baa minus 10y Treasury",         "1986-01-02", "fred_full"),
    "aaa10y":         ("Moody's Aaa minus 10y Treasury",         "1986-01-02", "fred_full"),
}


def fetch_fred(sid: str, cosd: str, coed: str, retries: int = 3) -> pd.DataFrame:
    """One keyless fredgraph.csv request -> DataFrame[date, value] (NaN rows
    dropped), with the range-assertion guard: the response MUST cover the
    requested [cosd, coed] window (modulo weekend/publication slack), so the
    ~3-year silent cap on ICE BofA series can never pass unnoticed."""
    url = FRED_URL.format(sid=sid.upper(), cosd=cosd, coed=coed)
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                txt = r.read().decode()
            break
        except Exception as e:                       # transient network only
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    else:
        raise RuntimeError(f"{sid}: fredgraph.csv fetch failed after {retries} tries: {last_err}")

    df = pd.read_csv(io.StringIO(txt))
    assert list(df.columns) == ["observation_date", sid.upper()], \
        f"{sid}: unexpected fredgraph columns {list(df.columns)}"
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # '.' -> NaN
    df = df.dropna(subset=["value"]).reset_index(drop=True)
    assert len(df), f"{sid}: fredgraph returned no observations for {cosd}..{coed}"

    got0, got1 = df["date"].min(), df["date"].max()
    want0 = pd.Timestamp(cosd) + pd.Timedelta(days=START_SLACK_DAYS)
    want1 = min(pd.Timestamp(coed),
                pd.Timestamp.today().normalize()) - pd.Timedelta(days=END_SLACK_DAYS)
    assert got0 <= want0, (
        f"{sid}: response starts {got0.date()} but cosd={cosd} was requested "
        f"(+{START_SLACK_DAYS}d slack) — SILENT TRUNCATION (the ~3y BAML cap?); "
        f"fetch this series in smaller chunks"
    )
    assert got1 >= want1, (
        f"{sid}: response ends {got1.date()} but coed={coed} was requested "
        f"(-{END_SLACK_DAYS}d slack) — truncated or stale response"
    )
    return df


def fetch_fred_chunked(sid: str, cosd: str, coed: str) -> pd.DataFrame:
    """Fetch [cosd, coed] in <=CHUNK_YEARS windows (guarded by fetch_fred),
    with SEAM_OVERLAP_DAYS of overlap between consecutive chunks; overlapping
    observations must agree exactly before the chunks are stitched."""
    starts = []
    t = pd.Timestamp(cosd)
    end = pd.Timestamp(coed)
    step = pd.Timedelta(days=int(CHUNK_YEARS * 365.25))
    while t < end:
        starts.append(t)
        t = t + step
    out = None
    for i, s in enumerate(starts):
        e = min(s + step + pd.Timedelta(days=SEAM_OVERLAP_DAYS), end)
        chunk = fetch_fred(sid, s.date().isoformat(), e.date().isoformat())
        if out is None:
            out = chunk
        else:
            seam = out.merge(chunk, on="date", suffixes=("_a", "_b"))
            assert len(seam), f"{sid}: chunks {i - 1}/{i} share no dates — seam gap"
            bad = seam[seam["value_a"] != seam["value_b"]]
            assert bad.empty, \
                f"{sid}: chunk seam disagreement:\n{bad.head().to_string()}"
            out = (pd.concat([out, chunk[chunk["date"] > out["date"].max()]])
                   .reset_index(drop=True))
        time.sleep(0.4)
    return out.sort_values("date").reset_index(drop=True)


def demonstrate_guard(coed: str) -> None:
    """Required demo: a single-call full-history request for BAMLH0A0HYM2 must
    trip the range guard (the endpoint silently caps BAML series at ~3y)."""
    print("--- cap-trap guard demonstration ---")
    print("  requesting BAMLH0A0HYM2 1997-01-01 ->", coed, "in ONE call ...")
    try:
        fetch_fred("bamlh0a0hym2", "1997-01-01", coed)
    except AssertionError as e:
        print(f"  GUARD FIRED as expected:\n    AssertionError: {e}")
        return
    raise RuntimeError(
        "guard did NOT fire on a single-call 1997->present BAML request — "
        "either FRED lifted the cap or the guard is broken; investigate before trusting"
    )


def main() -> None:
    today = pd.Timestamp.today().normalize().date().isoformat()
    demonstrate_guard(today)

    con = connect()
    p = r2_path("frb_all", "rates_daily")
    r2_cols = set(q(con, f"DESCRIBE SELECT * FROM read_parquet('{p}')")["column_name"])
    in_r2 = [s for s in SERIES if s in r2_cols]
    not_r2 = [s for s in SERIES if s not in r2_cols]
    print(f"\nR2 rates_daily: {len(r2_cols)} columns; present here: {in_r2}; "
          f"full-history from FRED: {not_r2}")

    r2 = q(con, f"SELECT date, {', '.join(in_r2)} FROM read_parquet('{p}') ORDER BY date")
    r2["date"] = pd.to_datetime(r2["date"])

    missing = [s for s, (_, _, mode) in SERIES.items()
               if mode == "r2+patch" and s not in r2_cols]
    assert not missing, f"expected in the R2 mirror but absent: {missing}"

    parts = []
    print("\n--- per-series build ---")
    for sid, (desc, full_start, mode) in SERIES.items():
        # BAML* history exists ONLY in the mirror; FRED serves its trailing ~3y
        # window, which is fetched in guarded chunks. Unlicensed series come
        # whole. See the SERIES comment for why chunking cannot beat the cap.
        chunked = sid.startswith("baml")
        if mode == "r2+patch":
            base = (r2[["date", sid]].dropna()
                    .rename(columns={sid: "value"}).reset_index(drop=True))
            d_last = base["date"].max()
            patch_from = (d_last - pd.Timedelta(days=R2_OVERLAP_DAYS)).date().isoformat()
            fred = (fetch_fred_chunked(sid, patch_from, today) if chunked
                    else fetch_fred(sid, patch_from, today))
            # R2 overlap must agree exactly: same value on same date.
            ov = base.merge(fred, on="date", suffixes=("_r2", "_fred"))
            assert len(ov) > 100, f"{sid}: only {len(ov)} overlap dates with R2"
            bad = ov[ov["value_r2"] != ov["value_fred"]]
            assert bad.empty, (
                f"{sid}: R2 vs FRED overlap disagreement on {len(bad)} dates:\n"
                f"{bad.head(10).to_string()}"
            )
            tail = fred[fred["date"] > d_last]
            df = pd.concat([base.assign(source="crsp-mirror"),
                            tail.assign(source="fred")], ignore_index=True)
            print(f"  {sid:<13} R2 {base['date'].min().date()} -> {d_last.date()} "
                  f"(n={len(base)}); overlap ok on {len(ov)} dates; FRED patch "
                  f"{tail['date'].min().date()} -> {tail['date'].max().date()} "
                  f"(n={len(tail)})")
        else:
            fred = (fetch_fred_chunked(sid, full_start, today) if chunked
                    else fetch_fred(sid, full_start, today))
            df = fred.assign(source="fred")
            print(f"  {sid:<13} FRED full history {df['date'].min().date()} -> "
                  f"{df['date'].max().date()} (n={len(df)})")
        df["series"] = sid
        parts.append(df[["date", "series", "value", "source"]])

    spreads = (pd.concat(parts, ignore_index=True)
               .sort_values(["series", "date"]).reset_index(drop=True))
    assert not spreads.duplicated(["series", "date"]).any()
    assert spreads["value"].notna().all()
    def _band(sids, lo, hi, what):
        v = spreads[spreads["series"].isin(sids)]["value"]
        assert v.between(lo, hi).all(), (
            f"{what} outside plausible % bounds [{lo}, {hi}]: "
            f"min={v.min()} max={v.max()} — unit error (bp vs %)?"
        )

    _band(["bamlh0a0hym2"], 0, 50, "HY OAS")
    # CCC gets its own band: distressed yields genuinely reached 45.02% on
    # 2008-12-15 (verified against the mirror), the GFC panic peak — the same
    # day HY OAS tops out. A 30% ceiling would reject real data.
    _band(["bamlh0a3hycey"], 0, 60, "CCC effective yield")
    _band([s for s in SERIES if s.endswith("ey") and s != "bamlh0a3hycey"]
          + ["daaa", "dbaa"], 0, 30, "yields")
    _band(["dgs3mo", "dgs2", "dgs10"], -1, 25, "Treasury yields")
    _band(["baa10y", "aaa10y"], -2, 15, "Moody's-Treasury spreads")

    print("\n--- spreads_daily summary (long format: date, series, value, source) ---")
    for sid in SERIES:
        sub = spreads[spreads["series"] == sid]
        srcs = sub.groupby("source").size().to_dict()
        print(f"  {sid:<13} {sub['date'].min().date()} -> {sub['date'].max().date()}  "
              f"n={len(sub)}  {srcs}  last={sub['value'].iloc[-1]:.2f}")
    spreads.to_parquet(OUT_SPREADS, index=False)
    print(f"wrote {OUT_SPREADS} ({len(spreads)} rows)")

    # --- risk-free file: Mon-Fri index, ffill over non-publication weekdays ---
    d3 = (spreads[spreads["series"] == "dgs3mo"][["date", "value"]]
          .rename(columns={"value": "dgs3mo"}).set_index("date").sort_index())
    idx = pd.bdate_range(d3.index.min(), d3.index.max())
    rf = d3.reindex(idx)
    n_filled = int(rf["dgs3mo"].isna().sum())
    rf["dgs3mo"] = rf["dgs3mo"].ffill()
    assert rf["dgs3mo"].notna().all()
    rf["rf_daily"] = rf["dgs3mo"] / 100.0 / 252.0
    rf = rf.rename_axis("date").reset_index()
    print(f"\n--- riskfree_daily (dgs3mo pct, rf_daily = dgs3mo/100/252, "
          f"ffilled over {n_filled} non-publication weekdays) ---")
    print(f"  {rf['date'].min().date()} -> {rf['date'].max().date()}  n={len(rf)}  "
          f"last dgs3mo={rf['dgs3mo'].iloc[-1]:.2f}  "
          f"last rf_daily={rf['rf_daily'].iloc[-1]:.6e}")
    rf.to_parquet(OUT_RF, index=False)
    print(f"wrote {OUT_RF} ({len(rf)} rows)")


if __name__ == "__main__":
    main()
