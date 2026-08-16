"""R3 forced-flow staging: ICI weekly long-term fund flow estimates.

Two freely published XLS files (rolling ~2.5y public window, $ millions):
  https://www.ici.org/flows_data_2025.xls          (mutual funds only; the
      /flows_data_2026.xls URL serves the identical file, same MD5)
  https://www.ici.org/combined_flows_data_2026.xls (mutual funds + ETFs)

Each has a 'Monthly' block then an 'Estimated Weekly' block. We parse both
blocks into tidy parquets with a freq column:
  data/forced_flow/ici_mf_flows.parquet        (bond detail: IG, HY, gov, ...)
  data/forced_flow/ici_combined_flows.parquet  (equity/hybrid/bond/commodity)
Raw provenance copies land in data/forced_flow/raw/.

Run: /opt/anaconda3/bin/python3 scripts/forced_flow/fetch_ici_flows.py
"""
import sys
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forced_flow"
RAW_DIR = OUT_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0"

MF_URL = "https://www.ici.org/flows_data_2025.xls"
COMBINED_URL = "https://www.ici.org/combined_flows_data_2026.xls"

# column positions established by inspection of the header block (rows 4-6)
MF_COLS = {
    1: "total_long_term", 3: "equity_total", 5: "equity_dom_total",
    7: "equity_dom_large", 9: "equity_dom_mid", 11: "equity_dom_small",
    13: "equity_dom_multi", 15: "equity_dom_other", 17: "equity_world_total",
    19: "equity_world_dev", 21: "equity_world_em", 23: "hybrid",
    25: "bond_total", 27: "bond_taxable_total", 29: "bond_ig", 31: "bond_hy",
    33: "bond_gov", 35: "bond_multisector", 37: "bond_global", 39: "bond_muni",
}
COMBINED_COLS = {
    1: "total_lt_mf_etf", 3: "equity_total", 5: "equity_dom", 7: "equity_world",
    9: "hybrid", 11: "bond_total", 13: "bond_taxable", 15: "bond_muni",
    17: "commodity",
}


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        dest.write_bytes(r.read())


def parse(path: Path, colmap: dict) -> pd.DataFrame:
    raw = pd.ExcelFile(path).parse(0, header=None)
    recs = []
    freq = None
    for _, row in raw.iterrows():
        v = row[0]
        if isinstance(v, str):
            low = v.lower()
            if "monthly" in low:
                freq = "monthly"
                continue
            if "weekly" in low and "note" not in low:
                freq = "weekly"
                continue
        d = pd.to_datetime(v, errors="coerce")
        if pd.isna(d) or freq is None:
            continue
        rec = {"date": d, "freq": freq}
        for pos, name in colmap.items():
            rec[name] = pd.to_numeric(row[pos], errors="coerce")
        recs.append(rec)
    df = pd.DataFrame(recs).sort_values(["freq", "date"]).reset_index(drop=True)
    return df


def report(df: pd.DataFrame, label: str) -> None:
    for freq, g in df.groupby("freq"):
        dups = g["date"].duplicated().sum()
        assert dups == 0, f"{label}/{freq}: {dups} duplicate dates"
        print(f"  {label} [{freq}]: N={len(g)}  {g['date'].min().date()} -> "
              f"{g['date'].max().date()}  dup_dates=0")


def main() -> None:
    mf_raw = RAW_DIR / "ici_flows_data_latest.xls"
    cb_raw = RAW_DIR / "ici_combined_flows_data_latest.xls"
    print("Fetching ICI weekly MF flow estimates ...")
    fetch(MF_URL, mf_raw)
    print("Fetching ICI combined MF+ETF flow estimates ...")
    fetch(COMBINED_URL, cb_raw)

    mf = parse(mf_raw, MF_COLS)
    report(mf, "ICI MF")
    mf.to_parquet(OUT_DIR / "ici_mf_flows.parquet", index=False)
    print(f"Wrote {OUT_DIR / 'ici_mf_flows.parquet'}  rows={len(mf)}")

    cb = parse(cb_raw, COMBINED_COLS)
    report(cb, "ICI combined")
    cb.to_parquet(OUT_DIR / "ici_combined_flows.parquet", index=False)
    print(f"Wrote {OUT_DIR / 'ici_combined_flows.parquet'}  rows={len(cb)}")


if __name__ == "__main__":
    sys.exit(main())
