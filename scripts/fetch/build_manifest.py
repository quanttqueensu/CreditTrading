"""R3 forced-flow staging: build data/forced_flow/manifest.json.

Reads the staged parquets and emits a manifest with source URL, fetch date,
row counts, and date bounds computed from the files themselves (no
transcription). Static notes document source quirks and limitations.

Run: /opt/anaconda3/bin/python3 scripts/forced_flow/build_manifest.py
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forced_flow"
FETCH_DATE = "2026-07-26"

SOURCES = {
    "ishares_so_daily.parquet": {
        "source_url": ("https://www.blackrock.com/varnish-api/blk-one01-product-data/"
                       "product-data/api/v1/get-fund-document?appType=PRODUCT_PAGE"
                       "&appSubType=ISHARES&targetSite=us-ishares&locale=en_US"
                       "&portfolioId={239565:HYG, 239566:LQD}&component=fundDownload"
                       "&userType=individual"),
        "fetch_script": "scripts/forced_flow/fetch_ishares_so.py",
        "description": ("iShares official daily NAV per share + shares outstanding "
                        "('Historical' worksheet of the product-page fund-download "
                        "XLS). Long format: date, ticker, nav_per_share, "
                        "ex_dividend, shares_outstanding. Fund-flow proxy = "
                        "day-over-day change in shares_outstanding x NAV."),
        "notes": ("SpreadsheetML export contains unescaped '&' in hyperlink "
                  "attributes; fetch script escapes them before XML parse. "
                  "Missing business days relative to a Mon-Fri calendar are US "
                  "market holidays (approx 9-10/yr), not data gaps."),
        "group_col": "ticker",
    },
    "angl_nav_aum_daily.parquet": {
        "source_url": ("https://www.vaneck.com/us/en/investments/"
                       "angel-high-yield-bond-etf-angl/downloads/fundhistoprices/"),
        "fetch_script": "scripts/forced_flow/fetch_vaneck_angl.py",
        "description": ("VanEck ANGL official daily NAV, last trade, volume, "
                        "premium/discount, AUM, index level since inception."),
        "notes": ("VanEck does NOT publish shares outstanding directly; "
                  "shares_outstanding_derived = aum / nav_per_share (exact at "
                  "inception: 10,000,000.00 / 25.0000 = 400,000 sh). Site "
                  "requires a cookie handshake (first request 302s; second "
                  "request with cookie jar succeeds). Raw file carries stale "
                  "weekend rows repeating Friday values; parquet drops Sat/Sun. "
                  "Holiday rows with repeated stale NAV may remain."),
        "group_col": "ticker",
    },
    "ici_mf_flows.parquet": {
        "source_url": "https://www.ici.org/flows_data_2025.xls",
        "fetch_script": "scripts/forced_flow/fetch_ici_flows.py",
        "description": ("ICI estimated long-term MUTUAL FUND net new cash flow, "
                        "$ millions, with bond detail (IG, HY, government, "
                        "multisector, global, muni). freq column separates "
                        "monthly rows from estimated-weekly rows."),
        "notes": ("LIMITATION: the freely published file is a rolling public "
                  "window only — monthly back ~2.5y plus the most recent ~7 "
                  "weekly estimates. Full weekly history is ICI "
                  "subscription-only (NOT freely fetchable). The "
                  "/flows_data_2026.xls URL serves the byte-identical file "
                  "(same MD5) as /flows_data_2025.xls."),
        "group_col": "freq",
    },
    "ici_combined_flows.parquet": {
        "source_url": "https://www.ici.org/combined_flows_data_2026.xls",
        "fetch_script": "scripts/forced_flow/fetch_ici_flows.py",
        "description": ("ICI estimated long-term MUTUAL FUND + ETF combined "
                        "flows, $ millions (equity dom/world, hybrid, bond "
                        "taxable/muni, commodity). freq column as above."),
        "notes": ("Same rolling public-window limitation as ici_mf_flows."),
        "group_col": "freq",
    },
    "etf_ff_daily.parquet": {
        "source_url": ("yfinance 0.2.66 (Yahoo Finance), Ticker.history("
                       "period='max', auto_adjust=True)"),
        "fetch_script": "scripts/forced_flow/fetch_etf_ff_daily.py",
        "description": ("Daily ADJUSTED closes + volume, long format "
                        "(date, ticker, adj_close, volume) for HYG JNK LQD ANGL "
                        "FALN BKLN SRLN JBBB JAAA BIL VWEHX IGSB SLQD, full "
                        "available history per ticker."),
        "notes": ("Adjusted for splits and dividends (total-return style "
                  "price). Missing business days vs Mon-Fri calendar are US "
                  "market holidays, verified no duplicate dates per ticker. "
                  "IGSB history includes its pre-2021 life as CSJ "
                  "(1-3y credit) per Yahoo's continuous series."),
        "group_col": "ticker",
    },
}

RAW_FILES = {
    "raw/HYG_fund_download.xls": "iShares HYG fund-download XLS (provenance copy)",
    "raw/LQD_fund_download.xls": "iShares LQD fund-download XLS (provenance copy)",
    "raw/ANGL_fundhistoprices.xlsx": "VanEck ANGL historical prices XLSX (provenance copy)",
    "raw/ici_flows_data_latest.xls": "ICI MF weekly flows XLS (provenance copy)",
    "raw/ici_combined_flows_data_latest.xls": "ICI combined MF+ETF flows XLS (provenance copy)",
}

UNFETCHABLE = {
    "ici_weekly_full_history": (
        "ICI weekly bond-fund flow FULL history: subscription-only; the free "
        "file carries just the rolling window described above. Not fabricated, "
        "not staged."),
    "ishares_ANGL": (
        "ANGL is a VanEck fund, not iShares — no iShares-style shares-"
        "outstanding file exists; VanEck AUM/NAV derivation staged instead "
        "(angl_nav_aum_daily.parquet)."),
}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = {
        "staged": "R3 forced-flow free-data staging",
        "fetch_date": FETCH_DATE,
        "datasets": {},
        "raw_files": {},
        "unfetchable_or_limited": UNFETCHABLE,
    }
    for fname, meta in SOURCES.items():
        path = OUT_DIR / fname
        df = pd.read_parquet(path)
        entry = {
            "source_url": meta["source_url"],
            "fetch_script": meta["fetch_script"],
            "fetch_date": FETCH_DATE,
            "rows": int(len(df)),
            "date_min": str(df["date"].min().date()),
            "date_max": str(df["date"].max().date()),
            "columns": list(df.columns),
            "description": meta["description"],
            "notes": meta["notes"],
            "md5": md5(path),
        }
        gc = meta["group_col"]
        entry["by_" + gc] = {
            str(k): {"rows": int(len(g)),
                     "date_min": str(g["date"].min().date()),
                     "date_max": str(g["date"].max().date())}
            for k, g in df.groupby(gc)}
        manifest["datasets"][fname] = entry
    for rel, desc in RAW_FILES.items():
        p = OUT_DIR / rel
        manifest["raw_files"][rel] = {
            "description": desc, "bytes": p.stat().st_size, "md5": md5(p),
            "fetch_date": FETCH_DATE}
    out = OUT_DIR / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
