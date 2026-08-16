"""Cycle-2 forced-flow LIVE free-data staging — idempotent daily refresh.

Fetches, parses and stages every free live source the M-register depends on
(FORCED_FLOW_2_PREREG.md: M4 premium/discount, M7 dealer-constraint conditioner,
M8 proxy basket). Designed to be run by a daily cron; every run overwrites the
deterministic snapshots and extends the two accumulator files, then rewrites
data/forced_flow2/manifest.json with URL / fetch time / rows / bounds / md5.

Sources
  1. NY Fed primary-dealer statistics (markets.newyorkfed.org API, weekly):
     corporate net outright positions, all definitional regimes 2001-07-04 ->
     present, plus a spliced z-scoreable series (see REGIMES below).
  2. iShares HYG + LQD product-page fund-download XLS: daily NAV per share,
     shares outstanding (2002/2007 -> present) + derived $ flow.
  3. iShares HYG product page embedded premium/discount chart (official, but
     only previous-calendar-year + YTD  -> ACCUMULATED across cron runs).
  4. SSGA JNK navhist.xlsx (full NAV/SO/TNA history since 2007-11 inception)
     and pdhist.xlsx (official premium/discount, rolling ~2y window ->
     ACCUMULATED across cron runs).
  5. Derived FULL-HISTORY premium/discount for HYG + JNK: official NAV x
     as-traded exchange close (yfinance unadjusted, split-factor restored),
     validated against the official windows on overlap (stats in manifest).

Probed and NOT staged (documented in manifest.unfetchable_or_limited):
  free daily/weekly rating-action counts. SEC 17g-7(b) XBRL histories are free
  but disclosed with a 12-month delay (already staged historically repo-wide as
  data/agency_actions_17g7.parquet); ESMA's register is a JSF web app without a
  stable machine endpoint and covers EU-registered CRAs only. No fabrication.

NY Fed regimes (documented from the data, 2026-07-26 recon):
  L2001  2001-07-04..2013-03-27  PDPCSM1NOP = "corporate securities due in
         more than one year", net outright. DEFINITION CLIFF at 2013-04:
         the legacy category also carried non-agency structured paper that the
         April-2013 FR-2004 redesign moved to new ABS/non-agency-MBS
         categories: last legacy print 2013-03-27 = $55,979m vs first clean
         corporate-bond print 2013-04-03 = $21,806m. Never z-score across it.
  B2013  2013-04-03..2014-12-31  corporate BONDS = L13 + G13 + BEL
         (IG <=13m, IG >13m, below-IG total; commercial paper split out).
  B2015  2015-01-07..present     corporate BONDS = 8 maturity/grade buckets
         (L13, G13, G5L10, G10, BELL13, BELG13, BELG5L10, BELG10). The total
         is continuous across 2015-01 ($18,442m -> $19,260m) but G13/BELG13
         narrow from ">13m" to ">13m..5y", and the IG/HY split jumps
         (IG 12,730 -> 9,641; HY 5,712 -> 9,619) — bucket reclassification,
         so IG/HY subseries are also z-scored within-regime only.
  The 2022-01-05 (SBN2022) and 2024-07-03 (SBN2024) administrative series
  breaks do NOT touch the corporate keyids: weekly series are gap-free across
  both (694 weekly obs 2013-04-03..2026-07-15 = complete).
  RELEASE LAG: positions as of Wednesday are published the following Thursday
  (~8 days). Any live signal must lag the as-of date by >= 8 calendar days.

Run:  /opt/anaconda3/bin/python3 scripts/forced_flow2/fetch_live_sources.py
      [--source nyfed|ishares_so|hyg_pd|jnk|derived_pd]   (default: all)
Exit code 0 iff every requested source succeeded.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forced_flow2"
RAW_DIR = OUT_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST = OUT_DIR / "manifest.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ---------------------------------------------------------------- helpers

def fetch(url: str, tries: int = 3, timeout: int = 120) -> bytes:
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2.0 * (k + 1))
    raise RuntimeError(f"fetch failed after {tries} tries: {url} ({last})")


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dataset_entry(path: Path, url: str, desc: str, notes: str,
                  df: pd.DataFrame, date_col: str = "date") -> dict:
    return {
        "source_url": url,
        "fetch_script": "scripts/forced_flow2/fetch_live_sources.py",
        "fetched_at_utc": utcnow(),
        "rows": int(len(df)),
        "date_min": str(pd.Timestamp(df[date_col].min()).date()),
        "date_max": str(pd.Timestamp(df[date_col].max()).date()),
        "columns": list(df.columns),
        "description": desc,
        "notes": notes,
        "md5": md5_of(path),
    }


def merge_accumulate(new: pd.DataFrame, path: Path, keys: list[str],
                     numeric_cols: list[str] | None = None) -> pd.DataFrame:
    """Union with an existing parquet; newest fetch wins on key collision."""
    if path.exists():
        old = pd.read_parquet(path)
        combined = pd.concat([old, new], ignore_index=True)
        combined = combined.drop_duplicates(subset=keys, keep="last")
    else:
        combined = new
    for c in numeric_cols or []:
        combined[c] = pd.to_numeric(combined[c], errors="coerce")
    combined = combined.sort_values(keys).reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return combined


# ---------------------------------------------------------------- 1. NY Fed

NYFED_API = "https://markets.newyorkfed.org/api/pd/get/{key}.csv"

NYFED_KEYS = {
    # legacy (2001-07-04 .. 2013-03-27), net outright positions, $ millions
    "PDPCS1LNOP": "corporate securities due in <=1 year incl commercial paper (legacy)",
    "PDPCSM1NOP": "corporate securities due in >1 year (legacy; incl non-agency structured pre-2013)",
    "PDPCSTNOP": "corporate securities total (legacy)",
    # modern (2013-04-03 ..), net positions, $ millions
    "PDPOSCS-TOT": "corporate securities total net position (incl CP)",
    "PDPOSCSCP": "commercial paper net",
    "PDPOSCSBND-L13": "IG bonds due <=13m net",
    "PDPOSCSBND-G13": "IG bonds due >13m (2013-14) / >13m..5y (2015-) net",
    "PDPOSCSBND-G5L10": "IG bonds due >5y..10y net (2015-)",
    "PDPOSCSBND-G10": "IG bonds due >10y net (2015-)",
    "PDPOSCSBND-BEL": "below-IG bonds total net (2013-14 only)",
    "PDPOSCSBND-BELL13": "below-IG bonds due <=13m net (2015-)",
    "PDPOSCSBND-BELG13": "below-IG bonds due >13m..5y net (2015-)",
    "PDPOSCSBND-BELG5L10": "below-IG bonds due >5y..10y net (2015-)",
    "PDPOSCSBND-BELG10": "below-IG bonds due >10y net (2015-)",
}

IG_BUCKETS = ["PDPOSCSBND-L13", "PDPOSCSBND-G13", "PDPOSCSBND-G5L10",
              "PDPOSCSBND-G10"]
HY_BUCKETS = ["PDPOSCSBND-BELL13", "PDPOSCSBND-BELG13",
              "PDPOSCSBND-BELG5L10", "PDPOSCSBND-BELG10"]

Z_WINDOW, Z_MIN = 104, 52  # weeks: trailing 2y z, min 1y of within-regime data


def trailing_z(s: pd.Series) -> pd.Series:
    mu = s.rolling(Z_WINDOW, min_periods=Z_MIN).mean()
    sd = s.rolling(Z_WINDOW, min_periods=Z_MIN).std(ddof=0)
    return (s - mu) / sd.replace(0.0, np.nan)


def fetch_nyfed(manifest: dict) -> None:
    frames, raw_parts = [], []
    for key, label in NYFED_KEYS.items():
        blob = fetch(NYFED_API.format(key=key))
        raw_parts.append(blob.decode("utf-8"))
        df = pd.read_csv(io.BytesIO(blob))
        df.columns = ["date", "keyid", "value_musd"]
        # '*' marks confidentiality-masked prints (only *C change series in
        # recon, but guard the levels anyway)
        df["value_musd"] = pd.to_numeric(df["value_musd"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        df["series_label"] = label
        frames.append(df)
        time.sleep(0.3)
    raw = pd.concat(frames, ignore_index=True).sort_values(["keyid", "date"])
    raw_csv = RAW_DIR / "nyfed_pd_corp_raw.csv"
    raw_csv.write_text("".join(raw_parts))
    raw_path = OUT_DIR / "nyfed_pd_corp_raw.parquet"
    raw.reset_index(drop=True).to_parquet(raw_path, index=False)

    # ---- spliced series
    wide = raw.pivot_table(index="date", columns="keyid", values="value_musd",
                           aggfunc="first").sort_index()
    out = pd.DataFrame(index=wide.index)
    legacy = wide.index <= pd.Timestamp("2013-03-27")
    b2013 = (wide.index >= pd.Timestamp("2013-04-03")) & \
            (wide.index <= pd.Timestamp("2014-12-31"))
    b2015 = wide.index >= pd.Timestamp("2015-01-07")

    out["regime"] = np.where(legacy, "L2001",
                             np.where(b2013, "B2013",
                                      np.where(b2015, "B2015", "GAP")))
    corp = pd.Series(np.nan, index=wide.index)
    corp[legacy] = wide.loc[legacy, "PDPCSM1NOP"]
    corp[b2013] = wide.loc[b2013, ["PDPOSCSBND-L13", "PDPOSCSBND-G13",
                                   "PDPOSCSBND-BEL"]].sum(axis=1, min_count=3)
    corp[b2015] = wide.loc[b2015, IG_BUCKETS + HY_BUCKETS].sum(axis=1,
                                                               min_count=8)
    out["corp_bond_net_musd"] = corp

    ig = pd.Series(np.nan, index=wide.index)
    ig[b2013] = wide.loc[b2013, ["PDPOSCSBND-L13", "PDPOSCSBND-G13"]].sum(
        axis=1, min_count=2)
    ig[b2015] = wide.loc[b2015, IG_BUCKETS].sum(axis=1, min_count=4)
    out["ig_bond_net_musd"] = ig

    hy = pd.Series(np.nan, index=wide.index)
    hy[b2013] = wide.loc[b2013, "PDPOSCSBND-BEL"]
    hy[b2015] = wide.loc[b2015, HY_BUCKETS].sum(axis=1, min_count=4)
    out["hy_bond_net_musd"] = hy

    cp = pd.Series(np.nan, index=wide.index)
    if "PDPOSCSCP" in wide:
        cp[~legacy] = wide.loc[~legacy, "PDPOSCSCP"]
    out["cp_net_musd"] = cp

    # internal consistency asserts (rounding tolerance $5m)
    chk_legacy = (wide.loc[legacy, "PDPCS1LNOP"] + wide.loc[legacy, "PDPCSM1NOP"]
                  - wide.loc[legacy, "PDPCSTNOP"]).abs()
    assert chk_legacy.max() <= 5, "legacy components != legacy total"
    tot_mod = corp[~legacy] + cp[~legacy]
    chk_mod = (tot_mod - wide.loc[~legacy, "PDPOSCS-TOT"]).abs().dropna()
    assert chk_mod.max() <= 5, "modern bond+CP != PDPOSCS-TOT"

    # within-regime trailing z (never spans a definitional break)
    for col in ["corp_bond_net_musd", "ig_bond_net_musd", "hy_bond_net_musd"]:
        zname = col.replace("_musd", "_z104w")
        out[zname] = (out.groupby("regime")[col]
                         .transform(lambda s: trailing_z(s)))
    out = out.reset_index().rename(columns={"index": "date"})
    spliced_path = OUT_DIR / "nyfed_pd_corp_spliced.parquet"
    out.to_parquet(spliced_path, index=False)

    n_weeks = int((wide.index.max() - pd.Timestamp("2013-04-03")).days / 7) + 1
    n_g13 = int(wide["PDPOSCSBND-G13"].notna().sum())
    manifest["datasets"]["nyfed_pd_corp_raw.parquet"] = dataset_entry(
        raw_path, NYFED_API.format(key="{keyid}"),
        "NY Fed primary-dealer corporate net outright positions, $ millions, "
        "weekly (Wednesday as-of), every corporate keyid in every definitional "
        "regime 2001-07-04 -> present. Long: date, keyid, value_musd, "
        "series_label.",
        "Masked prints ('*') parsed as NaN — recon 2026-07-26 found masking "
        "only in *C change series, levels clean. Corporate positions do not "
        "exist in the API before 2001-07-04 (the 1998-2001 SBP2001 break has "
        "no corporate category). RELEASE LAG ~8 days (Wed as-of -> next-Thu "
        "publication): live signals must lag >=8 calendar days.",
        raw, "date")
    manifest["datasets"]["nyfed_pd_corp_spliced.parquet"] = dataset_entry(
        spliced_path, NYFED_API.format(key="{keyid}"),
        "Spliced z-scoreable dealer corporate-bond net position series: date, "
        "regime (L2001/B2013/B2015), corp_bond_net_musd, ig_bond_net_musd, "
        "hy_bond_net_musd, cp_net_musd, and trailing-104w (min 52w) z-scores "
        "computed WITHIN regime only.",
        "Definitional breaks documented in the fetch-script docstring: "
        "2013-04 cliff ($55,979m legacy -> $21,806m clean corporate bonds; "
        "legacy included non-agency structured paper), 2015-01 bucket "
        "reclassification (total continuous 18,442 -> 19,260 but IG/HY split "
        "jumps), 2022-01/2024-07 administented series breaks touch no "
        f"corporate keyid (G13 gap-free: {n_g13}/{n_weeks} weeks). Never "
        "z-score across regimes; the staged z columns already respect this.",
        out, "date")
    print(f"[nyfed] raw {len(raw)} rows, spliced {len(out)} weeks "
          f"{out['date'].min().date()} -> {out['date'].max().date()}")


# ------------------------------------------------- 2. iShares NAV/SO (+flows)

ISHARES_API = ("https://www.blackrock.com/varnish-api/blk-one01-product-data/"
               "product-data/api/v1/get-fund-document?appType=PRODUCT_PAGE"
               "&appSubType=ISHARES&targetSite=us-ishares&locale=en_US"
               "&portfolioId={pid}&component=fundDownload&userType=individual")
ISHARES_FUNDS = {"HYG": "239565", "LQD": "239566"}
NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}


def parse_ishares_historical(raw_text: str, ticker: str) -> pd.DataFrame:
    import xml.etree.ElementTree as ET
    raw_text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)",
                      "&amp;", raw_text)
    root = ET.fromstring(raw_text)
    ws = [w for w in root.findall("ss:Worksheet", NS)
          if w.get("{urn:schemas-microsoft-com:office:spreadsheet}Name")
          == "Historical"]
    if not ws:
        raise RuntimeError(f"{ticker}: no 'Historical' worksheet")
    header, recs = None, []
    for r in ws[0].findall(".//ss:Row", NS):
        cells = [(c.find("ss:Data", NS).text
                  if c.find("ss:Data", NS) is not None else None)
                 for c in r.findall("ss:Cell", NS)]
        if header is None:
            header = cells
            continue
        recs.append(cells)
    df = pd.DataFrame(recs, columns=header).rename(columns={
        "As Of": "date", "NAV per Share": "nav_per_share",
        "Ex-Dividends": "ex_dividend",
        "Shares Outstanding": "shares_outstanding"})
    df["date"] = pd.to_datetime(df["date"], format="%b %d, %Y")
    for c in ["nav_per_share", "ex_dividend", "shares_outstanding"]:
        df[c] = pd.to_numeric(df[c].replace("--", None), errors="coerce")
    df["ticker"] = ticker
    return df.sort_values("date").reset_index(drop=True)


def fetch_ishares_so(manifest: dict) -> None:
    frames = []
    for ticker, pid in ISHARES_FUNDS.items():
        blob = fetch(ISHARES_API.format(pid=pid))
        (RAW_DIR / f"{ticker}_fund_download.xls").write_bytes(blob)
        df = parse_ishares_historical(blob.decode("utf-8"), ticker)
        assert df["date"].duplicated().sum() == 0, f"{ticker}: dup dates"
        df["so_chg"] = df["shares_outstanding"].diff()
        df["flow_usd_m"] = df["so_chg"] * df["nav_per_share"] / 1e6
        frames.append(df)
        print(f"[ishares_so] {ticker}: N={len(df)} "
              f"{df['date'].min().date()} -> {df['date'].max().date()}")
    out = pd.concat(frames, ignore_index=True)[
        ["date", "ticker", "nav_per_share", "ex_dividend",
         "shares_outstanding", "so_chg", "flow_usd_m"]]
    path = OUT_DIR / "ishares_so_daily.parquet"
    out.to_parquet(path, index=False)
    manifest["datasets"]["ishares_so_daily.parquet"] = dataset_entry(
        path, ISHARES_API.format(pid="{239565:HYG, 239566:LQD}"),
        "iShares official daily NAV/share, ex-dividend, shares outstanding "
        "for HYG + LQD (product-page fund-download XLS, 'Historical' sheet), "
        "plus derived so_chg and flow_usd_m = so_chg x NAV / 1e6.",
        "Cycle-2 refresh + extension of cycle-1 data/forced_flow/"
        "ishares_so_daily.parquet (same parser; unescaped '&' in the "
        "SpreadsheetML export is escaped before XML parse). flow_usd_m is "
        "DERIVED, not published. Missing bdays are US market holidays.",
        out, "date")


# ------------------------------------- 3. HYG official premium/discount

HYG_PAGE = ("https://www.ishares.com/us/products/239565/"
            "ishares-iboxx-high-yield-corporate-bond-etf")


def extract_pd_chart(page: str) -> pd.DataFrame:
    i = page.find("premiumDiscountChartData")
    if i < 0:
        raise RuntimeError("premiumDiscountChartData not found in HYG page")
    start = page.rfind("{", 0, i)
    depth, j = 0, start
    while True:
        c = page[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if depth == 0:
            break
        j += 1
    d = json.loads(html.unescape(page[start:j + 1]))
    chart = d["premiumDiscountChartData"]
    df = pd.DataFrame({
        "date": pd.to_datetime(pd.Series(chart["asOfDate"]).astype(str),
                               format="%Y%m%d"),
        "premium_discount_pct": pd.to_numeric(
            pd.Series(chart["value"]), errors="coerce"),
    })
    (RAW_DIR / "HYG_premium_discount_chart.json").write_text(
        json.dumps(d, indent=1))
    return df.sort_values("date").reset_index(drop=True)


def fetch_hyg_pd(manifest: dict) -> None:
    page = fetch(HYG_PAGE).decode("utf-8", errors="replace")
    new = extract_pd_chart(page)
    new["ticker"] = "HYG"
    path = OUT_DIR / "hyg_pd_official.parquet"
    combined = merge_accumulate(new, path, ["ticker", "date"],
                                numeric_cols=["premium_discount_pct"])
    manifest["datasets"]["hyg_pd_official.parquet"] = dataset_entry(
        path, HYG_PAGE,
        "iShares OFFICIAL HYG premium/discount (%, closing price vs NAV), "
        "extracted from the product page's embedded premiumDiscountChartData.",
        "The page only serves previous-calendar-year + YTD (~19 months, SEC "
        "minimum), so this file ACCUMULATES across cron runs (newest fetch "
        "wins on date collision). Full pre-2025 history lives in "
        "hyg_jnk_pd_derived.parquet (validated on overlap).",
        combined, "date")
    print(f"[hyg_pd] window {new['date'].min().date()} -> "
          f"{new['date'].max().date()} ({len(new)} d); accumulated "
          f"{len(combined)} rows")


# ---------------------------------------------------------- 4. SSGA JNK

SSGA_NAV = ("https://www.ssga.com/library-content/products/fund-data/etfs/us/"
            "navhist-us-en-jnk.xlsx")
SSGA_PD = ("https://www.ssga.com/library-content/products/fund-data/etfs/us/"
           "pdhist-us-en-jnk.xlsx")


def parse_ssga(blob: bytes, value_cols: dict[str, str]) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(blob), header=None)
    hdr = df.index[df[0].astype(str).str.strip() == "Date"][0]
    body = df.iloc[hdr + 1:, :].copy()
    body.columns = [str(x).strip() for x in df.iloc[hdr]]
    body = body.loc[:, [c for c in body.columns if c in
                        (["Date"] + list(value_cols))]]
    body["Date"] = pd.to_datetime(body["Date"], format="%d-%b-%Y",
                                  errors="coerce")
    body = body.dropna(subset=["Date"])
    for c in value_cols:
        body[c] = pd.to_numeric(body[c], errors="coerce")
    body = body.rename(columns={"Date": "date", **value_cols})
    return (body.drop_duplicates(subset="date", keep="first")
                .sort_values("date").reset_index(drop=True))


def fetch_jnk(manifest: dict) -> None:
    nav_blob = fetch(SSGA_NAV)
    (RAW_DIR / "jnk_navhist.xlsx").write_bytes(nav_blob)
    nav = parse_ssga(nav_blob, {"NAV": "nav_per_share",
                                "Shares Outstanding": "shares_outstanding",
                                "Total Net Assets": "total_net_assets"})
    nav["ticker"] = "JNK"
    nav["so_chg"] = nav["shares_outstanding"].diff()
    nav["flow_usd_m"] = nav["so_chg"] * nav["nav_per_share"] / 1e6
    nav_path = OUT_DIR / "jnk_nav_so_daily.parquet"
    nav.to_parquet(nav_path, index=False)

    pd_blob = fetch(SSGA_PD)
    (RAW_DIR / "jnk_pdhist.xlsx").write_bytes(pd_blob)
    pdw = parse_ssga(pd_blob, {"Premium/Discount": "premium_discount_pct"})
    pdw["ticker"] = "JNK"
    pd_path = OUT_DIR / "jnk_pd_official.parquet"
    combined = merge_accumulate(pdw, pd_path, ["ticker", "date"],
                                numeric_cols=["premium_discount_pct"])

    manifest["datasets"]["jnk_nav_so_daily.parquet"] = dataset_entry(
        nav_path, SSGA_NAV,
        "SPDR JNK official daily NAV/share, shares outstanding, total net "
        "assets — FULL history since 2007-12 inception — plus derived so_chg "
        "and flow_usd_m.",
        "SSGA product-page download 'Net Asset Value History'. flow_usd_m is "
        "DERIVED, not published.",
        nav, "date")
    manifest["datasets"]["jnk_pd_official.parquet"] = dataset_entry(
        pd_path, SSGA_PD,
        "SPDR JNK OFFICIAL premium/discount (%, closing price vs NAV).",
        "SSGA serves a rolling ~2.2-year window, so this file ACCUMULATES "
        "across cron runs (newest fetch wins). Full pre-window history lives "
        "in hyg_jnk_pd_derived.parquet (validated on overlap).",
        combined, "date")
    print(f"[jnk] nav {len(nav)} rows {nav['date'].min().date()} -> "
          f"{nav['date'].max().date()}; official P/D window {len(pdw)} d, "
          f"accumulated {len(combined)}")


# ------------------------------------------- 5. derived full-history P/D

def as_traded_close(ticker: str) -> pd.Series:
    """Yahoo unadjusted close with split back-adjustment UNDONE."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    h = t.history(period="max", auto_adjust=False)
    close = h["Close"].copy()
    close.index = pd.to_datetime(close.index.date)
    splits = t.splits
    if len(splits):
        splits.index = pd.to_datetime(splits.index.date)
        factor = pd.Series(1.0, index=close.index)
        for dt, ratio in splits.items():
            factor.loc[factor.index < dt] *= ratio
        close = close * factor
    return close


def fetch_derived_pd(manifest: dict) -> None:
    navs = {}
    iso = pd.read_parquet(OUT_DIR / "ishares_so_daily.parquet")
    navs["HYG"] = (iso[iso.ticker == "HYG"]
                   .set_index("date")["nav_per_share"])
    jnk = pd.read_parquet(OUT_DIR / "jnk_nav_so_daily.parquet")
    navs["JNK"] = jnk.set_index("date")["nav_per_share"]

    frames, closes = [], []
    for ticker in ["HYG", "JNK"]:
        close = as_traded_close(ticker)
        closes.append(pd.DataFrame({"date": close.index, "ticker": ticker,
                                    "close_unadj": close.values}))
        nav = navs[ticker]
        both = pd.concat([close.rename("close"), nav.rename("nav")],
                         axis=1).dropna()
        pdd = pd.DataFrame({
            "date": both.index, "ticker": ticker,
            "premium_discount_pct": 100.0 * (both["close"] / both["nav"] - 1.0),
        })
        # guard: a missed/mis-signed split shows up as a SUSTAINED block at a
        # constant ratio far from 1 — fat-tail single days (GFC 2008-09: HYG
        # printed -8.4%..+12.8%) are genuine and must pass.
        med = float(pdd["premium_discount_pct"].abs().median())
        assert med < 0.5, f"{ticker}: median |P/D| {med:.2f}% — scale error?"
        roll = (both["close"] / both["nav"]).rolling(21).median().dropna()
        worst = float((roll - 1.0).abs().max())
        assert worst < 0.2, (f"{ticker}: 21d-median close/nav deviates "
                             f"{worst:.2f} from 1 — split artifact?")
        n_big = int((pdd["premium_discount_pct"].abs() > 5).sum())
        if n_big:
            print(f"[derived_pd] {ticker}: {n_big} days |P/D|>5% "
                  "(crisis prints, kept)")
        frames.append(pdd)
    derived = pd.concat(frames, ignore_index=True).sort_values(
        ["ticker", "date"]).reset_index(drop=True)
    dpath = OUT_DIR / "hyg_jnk_pd_derived.parquet"
    derived.to_parquet(dpath, index=False)
    cpath = OUT_DIR / "etf_close_unadj.parquet"
    closedf = pd.concat(closes, ignore_index=True)
    closedf.to_parquet(cpath, index=False)

    # validation vs official windows
    val = {}
    for ticker, off_file in [("HYG", "hyg_pd_official.parquet"),
                             ("JNK", "jnk_pd_official.parquet")]:
        off = pd.read_parquet(OUT_DIR / off_file)
        off = off[off.ticker == ticker][["date", "premium_discount_pct"]]
        der = derived[derived.ticker == ticker][
            ["date", "premium_discount_pct"]]
        m = off.merge(der, on="date", suffixes=("_off", "_der"))
        if len(m) < 50:
            raise RuntimeError(f"{ticker}: only {len(m)} overlap days")
        corr = float(m["premium_discount_pct_off"].corr(
            m["premium_discount_pct_der"]))
        mae = float((m["premium_discount_pct_off"]
                     - m["premium_discount_pct_der"]).abs().mean())
        val[ticker] = {"overlap_days": int(len(m)),
                       "pearson_corr": round(corr, 4),
                       "mean_abs_diff_pct": round(mae, 4)}
        print(f"[derived_pd] {ticker}: overlap {len(m)} d, corr {corr:.4f}, "
              f"MAE {mae:.4f} pct-pts")

    manifest["datasets"]["hyg_jnk_pd_derived.parquet"] = dataset_entry(
        dpath, "yfinance unadjusted Close x official NAV (iShares XLS / SSGA "
        "navhist)",
        "DERIVED full-history premium/discount for HYG + JNK: 100 x "
        "(as-traded close / official NAV - 1), daily since fund NAV history "
        "begins (HYG 2007-04, JNK 2007-12).",
        "Derived, not official. Yahoo close is the exchange closing trade; "
        "official P/D uses the same convention. Validation against the "
        "official windows: " + json.dumps(val) + ". Split factors undone via "
        "yfinance split history (none for HYG/JNK as of 2026-07).",
        derived, "date")
    manifest["datasets"]["etf_close_unadj.parquet"] = dataset_entry(
        cpath, "yfinance Ticker.history(period='max', auto_adjust=False)",
        "As-traded (unadjusted, split-restored) daily closes for HYG + JNK "
        "used to derive premium/discount.",
        "Support file for hyg_jnk_pd_derived.parquet.",
        closedf, "date")
    manifest["validation"] = {"derived_pd_vs_official": val,
                              "checked_at_utc": utcnow()}


# ---------------------------------------------------------------- driver

SOURCES = {
    "nyfed": fetch_nyfed,
    "ishares_so": fetch_ishares_so,
    "hyg_pd": fetch_hyg_pd,
    "jnk": fetch_jnk,
    "derived_pd": fetch_derived_pd,  # must run after ishares_so + jnk
}

UNFETCHABLE = {
    "rating_action_counts_live": (
        "PROBED 2026-07-26, NOT STAGED — no free cron-robust daily/weekly "
        "rating-action count source exists. SEC 17g-7(b) XBRL rating "
        "histories (via ratingshistory.info) are free but published with a "
        "~12-month disclosure delay: usable for history (already staged "
        "repo-wide as data/agency_actions_17g7.parquet, through the delay "
        "horizon) but NOT as a live signal. ESMA's register "
        "(registers.esma.europa.eu) is a JSF web app with no stable machine "
        "endpoint and covers EU-registered CRAs only. Moody's/S&P/Fitch "
        "press feeds require registration/ToS-restricted scraping. "
        "M-register work must not assume a live rating-action feed."),
    "hyg_pd_official_pre2025": (
        "iShares serves only previous-calendar-year + YTD premium/discount "
        "on the product page. Pre-2025 official P/D is not freely "
        "downloadable; the derived series stands in, validated on overlap."),
    "jnk_pd_official_pre_window": (
        "SSGA pdhist serves a rolling ~2.2y window; older official P/D not "
        "freely downloadable; derived series stands in."),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES), default=None,
                    help="run one source only (default: all)")
    args = ap.parse_args()
    todo = [args.source] if args.source else list(SOURCES)

    manifest = {"staged": "Cycle-2 forced-flow live free-data staging",
                "prereg": "FORCED_FLOW_2_PREREG.md",
                "last_run_utc": utcnow(), "datasets": {},
                "unfetchable_or_limited": UNFETCHABLE}
    if MANIFEST.exists():
        try:
            prev = json.loads(MANIFEST.read_text())
            manifest["datasets"] = prev.get("datasets", {})
            if "validation" in prev:
                manifest["validation"] = prev["validation"]
        except Exception:  # noqa: BLE001
            pass

    failed = []
    for name in todo:
        try:
            SOURCES[name](manifest)
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            print(f"[{name}] FAILED: {e}", file=sys.stderr)

    manifest["last_run_utc"] = utcnow()
    manifest["last_run_failed_sources"] = failed
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(f"manifest -> {MANIFEST}  (failed: {failed or 'none'})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
