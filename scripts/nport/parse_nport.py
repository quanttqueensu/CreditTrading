#!/usr/bin/env python3
"""
Parse downloaded NPORT-P XML into a normalized holdings panel.

Verified schema (SEC nport namespace, stable 2019-2026):

  formData/genInfo/{regName,regCik,seriesName,seriesId,repPdDate,repPdEnd}
  formData/invstOrSecs/invstOrSec/
      name, lei, title, cusip
      identifiers/isin@value          <- ISIN is an ATTRIBUTE, not element text
      balance, units, curCd, valUSD, pctVal
      payoffProfile, assetCat, issuerCat, invCountry, isRestrictedSec
      fairValLevel                    <- fair value hierarchy 1/2/3
      debtSec/{maturityDt, couponKind, annualizedRt, isDefault, ...}

Note the task brief's field names differ from reality: coupon is
`debtSec/annualizedRt` (not `couponRate`) and maturity is nested under
`debtSec`, not a direct child of `invstOrSec`.

price_per_100 = 100 * valUSD / balance, computed ONLY where units == 'PA'
(par amount) and curCd == 'USD' and balance > 0. For units == 'NS' (shares)
the ratio is not a bond price, so it is left null rather than emitting a
number that looks like a price but isn't.

Usage:  python3 scripts/nport/parse_nport.py
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import os
import sys
from datetime import datetime, timezone

import pandas as pd
from lxml import etree

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(REPO, "data", "holdings", "nport_raw")
OUT_PARQUET = os.path.join(REPO, "data", "holdings", "nport_holdings.parquet")

COLUMNS = [
    "fund_cik", "fund_name", "ticker", "series_id", "report_dt",
    "cusip", "isin", "name", "title", "lei",
    "balance_par", "units", "cur_cd", "val_usd", "pct_val",
    "maturity_dt", "coupon", "coupon_kind", "is_default",
    "fair_val_level", "asset_cat", "issuer_cat", "inv_country",
    "payoff_profile", "is_restricted",
    "price_per_100", "filing_accession", "filing_date", "ingest_ts",
]


def ln(el) -> str:
    return etree.QName(el).localname


def text(el):
    if el is None:
        return None
    t = (el.text or "").strip()
    return t or None


def num(v):
    if v in (None, "", "N/A"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def child_map(el) -> dict:
    """localname -> element for direct children (last wins)."""
    return {ln(c): c for c in el}


def parse_filing(path: str, ticker: str, accession: str, filing_date: str) -> tuple[list[dict], dict]:
    with gzip.open(path, "rb") as fh:
        root = etree.fromstring(fh.read())

    gen = None
    for el in root.iter():
        if ln(el) == "genInfo":
            gen = el
            break
    g = child_map(gen) if gen is not None else {}
    fund_cik = text(g.get("regCik"))
    meta = {
        "fund_cik": int(fund_cik) if fund_cik and fund_cik.isdigit() else None,
        "reg_name": text(g.get("regName")),
        "fund_name": text(g.get("seriesName")),
        "series_id": text(g.get("seriesId")),
        "report_dt": text(g.get("repPdDate")),
        "rep_pd_end": text(g.get("repPdEnd")),
    }

    rows = []
    for sec in root.iter():
        if ln(sec) != "invstOrSec":
            continue
        c = child_map(sec)

        isin = None
        ids = c.get("identifiers")
        if ids is not None:
            for i in ids:
                if ln(i) == "isin":
                    isin = i.get("value") or text(i)
                    break

        debt = c.get("debtSec")
        d = child_map(debt) if debt is not None else {}

        balance = num(text(c.get("balance")))
        val_usd = num(text(c.get("valUSD")))
        units = text(c.get("units"))
        cur = text(c.get("curCd"))
        price = None
        if balance and balance > 0 and val_usd is not None and units == "PA" and cur == "USD":
            price = 100.0 * val_usd / balance

        fvl = text(c.get("fairValLevel"))
        rows.append({
            "fund_cik": meta["fund_cik"],
            "fund_name": meta["fund_name"],
            "ticker": ticker,
            "series_id": meta["series_id"],
            "report_dt": meta["report_dt"],
            "cusip": text(c.get("cusip")),
            "isin": isin,
            "name": text(c.get("name")),
            "title": text(c.get("title")),
            "lei": text(c.get("lei")),
            "balance_par": balance,
            "units": units,
            "cur_cd": cur,
            "val_usd": val_usd,
            "pct_val": num(text(c.get("pctVal"))),
            "maturity_dt": text(d.get("maturityDt")),
            "coupon": num(text(d.get("annualizedRt"))),
            "coupon_kind": text(d.get("couponKind")),
            "is_default": text(d.get("isDefault")),
            "fair_val_level": fvl,
            "asset_cat": text(c.get("assetCat")),
            "issuer_cat": text(c.get("issuerCat")),
            "inv_country": text(c.get("invCountry")),
            "payoff_profile": text(c.get("payoffProfile")),
            "is_restricted": text(c.get("isRestrictedSec")),
            "price_per_100": price,
            "filing_accession": accession,
            "filing_date": filing_date,
        })
    meta["n_holdings"] = len(rows)
    return rows, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_PARQUET)
    args = ap.parse_args()

    man_path = os.path.join(RAW_DIR, "manifest.csv")
    if not os.path.exists(man_path):
        print(f"[error] no manifest at {man_path}; run fetch_nport.py first")
        return 2
    with open(man_path) as fh:
        manifest = [r for r in csv.DictReader(fh) if r["ok"] == "1"]

    all_rows, metas, failures = [], [], []
    for m in manifest:
        path = os.path.join(REPO, m["path"])
        if not os.path.exists(path):
            failures.append((m["ticker"], m["accession"], "missing file"))
            continue
        try:
            rows, meta = parse_filing(path, m["ticker"], m["accession"], m["filing_date"])
        except Exception as exc:
            failures.append((m["ticker"], m["accession"], repr(exc)))
            continue
        if not rows or not meta["report_dt"]:
            failures.append((m["ticker"], m["accession"], f"rows={len(rows)} repPdDate={meta['report_dt']}"))
            continue
        # sanity: the filing must belong to the series we asked for
        if meta["series_id"] and meta["series_id"] != m["series_id"]:
            failures.append((m["ticker"], m["accession"],
                             f"series mismatch {meta['series_id']} != {m['series_id']}"))
            continue
        all_rows.extend(rows)
        metas.append({"ticker": m["ticker"], **meta})

    if not all_rows:
        print("[error] parsed zero holdings rows")
        for f in failures:
            print("  ", f)
        return 3

    df = pd.DataFrame(all_rows)
    df["report_dt"] = pd.to_datetime(df["report_dt"], errors="coerce")
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["maturity_dt"] = pd.to_datetime(df["maturity_dt"], errors="coerce")
    df["fair_val_level"] = pd.to_numeric(df["fair_val_level"], errors="coerce").astype("Int8")
    df["ingest_ts"] = pd.Timestamp.now(tz="UTC")
    df = df[COLUMNS].sort_values(["ticker", "report_dt", "cusip"]).reset_index(drop=True)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df.to_parquet(args.out, index=False, compression="snappy")

    print(f"parsed filings : {len(metas)} / {len(manifest)}   failures: {len(failures)}")
    for f in failures:
        print("   FAIL", f)
    print(f"wrote {args.out}  rows={len(df):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
