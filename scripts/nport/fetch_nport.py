#!/usr/bin/env python3
"""
Fetch SEC EDGAR Form N-PORT (NPORT-P) filings for bond ETFs.

Why: iShares/SSGA only publish TODAY's holdings file. N-PORT is the only free
historical source of full holdings with par balance, market value and the
fair-value-hierarchy level (1/2/3).

What EDGAR actually gives us (verified, not assumed):
  * NPORT-P is filed PER SERIES (one accession = one ETF), quarterly.
  * The PUBLIC NPORT-P contains exactly ONE month-end snapshot: <repPdDate>.
    Months 1 and 2 of the quarter are filed non-public (NPORT-P is the public
    part of N-PORT); they do not appear in the Archives XML.
  * Holdings live in primary_doc.xml under formData/invstOrSecs/invstOrSec.

Usage:
    python3 scripts/nport/fetch_nport.py
    python3 scripts/nport/fetch_nport.py --tickers HYG LQD --force
"""
from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(REPO, "data", "holdings", "nport_raw")
MANIFEST = os.path.join(RAW_DIR, "manifest.csv")

# EDGAR requires a descriptive User-Agent with a contact address; without it -> 403.
UA = "QUANTT Research simon.jarvis0@gmail.com"
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
SLEEP = 0.15  # seconds between requests (SEC limit is 10 req/s)

# ticker -> (registrant CIK, EDGAR series id).  Series ids taken from
# https://www.sec.gov/files/company_tickers_mf.json
FUNDS = {
    "HYG":  (1100663, "S000016772"),  # iShares iBoxx $ High Yield Corporate Bond ETF
    "LQD":  (1100663, "S000004361"),  # iShares iBoxx $ Investment Grade Corporate Bond ETF
    "JNK":  (1064642, "S000019669"),  # SPDR Bloomberg High Yield Bond ETF
    "AGG":  (1100663, "S000004362"),  # iShares Core U.S. Aggregate Bond ETF
    "SHYG": (1100663, "S000042353"),  # iShares 0-5yr High Yield Corporate Bond ETF
    "IGSB": (1100663, "S000013697"),  # iShares 1-5yr Investment Grade Corporate Bond ETF
    "IGIB": (1100663, "S000013698"),  # iShares 5-10yr Investment Grade Corporate Bond ETF
    "FALN": (1100663, "S000054186"),  # iShares Fallen Angels USD Bond ETF
}
DEFAULT_TICKERS = ["HYG", "LQD", "JNK"]


def http_get(url: str, retries: int = 4) -> bytes:
    """GET with SEC-compliant UA, gzip handling and exponential backoff."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            code = getattr(exc, "code", None)
            if code in (403, 429) or code is None or (code and code >= 500):
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


def discover(series_id: str) -> list[dict]:
    """List every NPORT-P accession for one fund series via the browse-edgar atom feed.

    Filtering by series id (CIK=S000...) is what pins the feed to a single ETF -
    the registrant CIK alone returns every series in the trust.
    """
    out, start = [], 0
    while True:
        url = (
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={series_id}&type=NPORT-P&dateb=&owner=include&count=100"
            f"&start={start}&output=atom"
        )
        body = http_get(url).decode("latin-1")
        time.sleep(SLEEP)
        entries = re.findall(r"<entry>(.*?)</entry>", body, re.S)
        for e in entries:
            acc = re.search(r"<accession-number>([\d-]+)</accession-number>", e)
            fdt = re.search(r"<filing-date>([\d-]+)</filing-date>", e)
            ftp = re.search(r"<filing-type>([^<]+)</filing-type>", e)
            if not (acc and fdt):
                continue
            out.append({
                "accession": acc.group(1),
                "filing_date": fdt.group(1),
                "form_type": ftp.group(1) if ftp else "NPORT-P",
            })
        if len(entries) < 100:
            break
        start += 100
        if start > 2000:  # safety valve
            break
    return out


def fetch_one(cik: int, accession: str, dest: str) -> tuple[bool, str]:
    """Download primary_doc.xml for one accession, gzip it to `dest`."""
    acc_nodash = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}"
    try:
        body = http_get(f"{base}/primary_doc.xml")
    except Exception as exc:  # fall back to the index if the doc is named oddly
        try:
            import json
            idx = json.loads(http_get(f"{base}/index.json").decode())
            time.sleep(SLEEP)
            cand = [i["name"] for i in idx["directory"]["item"]
                    if i["name"].lower().endswith(".xml")]
            if not cand:
                return False, f"no xml in index ({exc})"
            body = http_get(f"{base}/{cand[0]}")
        except Exception as exc2:
            return False, f"{exc} / {exc2}"
    if b"invstOrSec" not in body:
        return False, "xml has no invstOrSec elements"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with gzip.open(dest, "wb") as fh:
        fh.write(body)
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS)
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    args = ap.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    rows, n_new, n_skip, n_fail = [], 0, 0, 0

    for tk in args.tickers:
        if tk not in FUNDS:
            print(f"[warn] unknown ticker {tk}; skipping")
            continue
        cik, sid = FUNDS[tk]
        filings = discover(sid)
        print(f"[{tk}] series={sid} cik={cik} -> {len(filings)} NPORT-P filings "
              f"({filings[-1]['filing_date'] if filings else '-'} .. "
              f"{filings[0]['filing_date'] if filings else '-'})", flush=True)
        for f in filings:
            dest = os.path.join(RAW_DIR, tk, f"{f['accession']}.xml.gz")
            if os.path.exists(dest) and not args.force:
                ok, err, n_skip = True, "", n_skip + 1
            else:
                ok, err = fetch_one(cik, f["accession"], dest)
                time.sleep(SLEEP)
                n_new += ok
                n_fail += (not ok)
                if not ok:
                    print(f"  [fail] {tk} {f['accession']}: {err}", flush=True)
            rows.append({
                "ticker": tk, "fund_cik": cik, "series_id": sid,
                "accession": f["accession"], "filing_date": f["filing_date"],
                "form_type": f["form_type"],
                "path": os.path.relpath(dest, REPO) if ok else "",
                "ok": int(ok), "error": err,
                "fetched_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })

    with open(MANIFEST, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\nmanifest: {MANIFEST}")
    print(f"downloaded={n_new} cached={n_skip} failed={n_fail} total={len(rows)}")
    return 1 if n_fail and n_new == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
