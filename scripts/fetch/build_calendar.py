"""Build a clean US Treasury auction calendar, 1990 -> today.

Engine B+ (auction-cycle butterfly confirmation) namespace. Writes ONLY to
data/auction/. Reads nothing from the calendar/archive namespaces.

Source of truth: fiscaldata.treasury.gov "Auctions Query" dataset
    /services/api/fiscal_service/v1/accounting/od/auctions_query
which carries every marketable auction back to 1979 with issue/settle date,
offering amount, term, reopening flag and inflation/floating flags. We pull
auction_date >= 1990-01-01, all security types, and classify:

    coupon_type  : nominal_coupon | tips | frn | bill   (Note/Bond=coupon unless
                   inflation/floating; Bill incl. CMB = bill)
    tenor        : canonical label from ORIGINAL security term so a reopening of
                   a 10-Year (e.g. "9-Year 10-Month") is tagged 10y, not 9y.
    refunding_week: nominal-coupon 3y/10y/30y auctioned in a quarterly refunding
                    month (Feb/May/Aug/Nov) -- the peak-supply slug.

If the API is unreachable after retries, we fall back to a DETERMINISTIC regular
schedule (nominal coupons only) with source='deterministic_schedule' and a loud
caveat, and assert coverage before saving.

Run:  python3 scripts/auction/build_calendar.py
Out:  data/auction/auction_calendar.parquet   (+ raw pull under data/auction/raw/)
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "auction"
RAW_DIR = OUT_DIR / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

FISCAL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
          "v1/accounting/od/auctions_query")
START = "1990-01-01"
REFUNDING_MONTHS = {2, 5, 8, 11}
REFUNDING_TENORS = {"3y", "10y", "30y"}
CANON_YEARS = np.array([2, 3, 4, 5, 7, 10, 20, 30])

FIELDS = ",".join([
    "cusip", "auction_date", "issue_date", "maturity_date",
    "security_type", "security_term", "original_security_term",
    "offering_amt", "reopening", "inflation_index_security", "floating_rate",
])


# --------------------------------------------------------------- fetch
def _get(url: str, tries: int = 6, pause: float = 8.0) -> str:
    ctx = ssl.create_default_context()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
                return r.read().decode()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    fetch retry {i+1}/{tries}: {type(e).__name__} (backoff {pause:.0f}s)")
            time.sleep(pause)
            pause = min(pause * 1.5, 45)
    raise RuntimeError(f"fiscaldata unreachable after {tries} tries: {last}")


def fetch_fiscaldata() -> pd.DataFrame:
    """Paginated pull of all marketable auctions since 1990."""
    rows, page = [], 1
    while True:
        url = (f"{FISCAL}?fields={FIELDS}"
               f"&filter=auction_date:gte:{START}"
               f"&sort=auction_date&page[size]=5000&page[number]={page}")
        d = json.loads(_get(url))
        rows.extend(d["data"])
        tp = d["meta"].get("total-pages", page)
        tc = d["meta"].get("total-count")
        print(f"    page {page}/{tp}: +{len(d['data'])} (cum {len(rows)}/{tc})")
        if page >= tp:
            break
        page += 1
        time.sleep(3)
    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "fiscaldata_auctions.parquet", index=False)
    return df


# --------------------------------------------------------------- parsing
_TERM_RE = re.compile(r"(?:(\d+)-Year)?\s*(?:(\d+)-Month)?\s*(?:(\d+)-Week)?\s*(?:(\d+)-Day)?")


def term_to_years(term: str) -> float:
    """Parse a Treasury term string ('10-Year', '9-Year 10-Month', '13-Week')
    into a float number of years."""
    if not term or not isinstance(term, str):
        return np.nan
    m = _TERM_RE.match(term.strip())
    if not m:
        return np.nan
    y, mo, wk, dy = (int(g) if g else 0 for g in m.groups())
    return y + mo / 12.0 + wk / 52.0 + dy / 365.0


def canon_coupon_tenor(orig_term: str) -> str:
    """Map an original coupon term to a canonical tenor label (2y..30y) by
    nearest standard maturity."""
    yrs = term_to_years(orig_term)
    if np.isnan(yrs) or yrs <= 0:
        return None
    return f"{int(CANON_YEARS[np.argmin(np.abs(CANON_YEARS - yrs))])}y"


def bill_tenor(term: str) -> str:
    """Bill tenor label in weeks (e.g. '13w'); CMBs -> canonical week bucket."""
    yrs = term_to_years(term)
    if np.isnan(yrs) or yrs <= 0:
        return None
    wk = int(round(yrs * 52))
    for std in (4, 8, 13, 17, 26, 52):          # standard bill tenors
        if abs(wk - std) <= 1:
            return f"{std}w"
    return f"{wk}w"


def classify_coupon_type(row) -> str:
    if row["security_type"] == "Bill":
        return "bill"
    if str(row.get("inflation_index_security", "")).strip().lower() in ("yes", "true", "1"):
        return "tips"
    if str(row.get("floating_rate", "")).strip().lower() in ("yes", "true", "1"):
        return "frn"
    return "nominal_coupon"


# --------------------------------------------------------------- build
def build_from_api(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["auction_date"] = pd.to_datetime(df["auction_date"])
    df["issue_date"] = pd.to_datetime(df["issue_date"])
    df["maturity_date"] = pd.to_datetime(df["maturity_date"], errors="coerce")
    df["settle_date"] = df["issue_date"]        # issue date IS the settlement date
    df["offering_amt"] = pd.to_numeric(df["offering_amt"], errors="coerce")
    df["reopening"] = df["reopening"].astype(str).str.strip().str.lower().isin(
        ["yes", "true", "1"])

    df["coupon_type"] = df.apply(classify_coupon_type, axis=1)
    df["term_years"] = df["original_security_term"].map(term_to_years)

    def _tenor(r):
        if r["coupon_type"] == "bill":
            return bill_tenor(r["original_security_term"] or r["security_term"])
        return canon_coupon_tenor(r["original_security_term"] or r["security_term"])
    df["tenor"] = df.apply(_tenor, axis=1)

    m = df["auction_date"].dt.month
    df["refunding_month"] = m.isin(REFUNDING_MONTHS)
    df["refunding_week"] = (
        df["refunding_month"]
        & (df["coupon_type"] == "nominal_coupon")
        & df["tenor"].isin(REFUNDING_TENORS)
    )
    df["source"] = "fiscaldata_api"

    cols = ["auction_date", "issue_date", "settle_date", "maturity_date",
            "security_type", "coupon_type", "security_term", "original_security_term",
            "tenor", "term_years", "reopening", "offering_amt",
            "refunding_month", "refunding_week", "cusip", "source"]
    df = df[cols].sort_values(["auction_date", "term_years", "cusip"]).reset_index(drop=True)
    return df


# --------------------------------------------------------------- deterministic fallback
def build_deterministic() -> pd.DataFrame:
    """Regular nominal-coupon schedule, used ONLY if the API is unreachable.

    Cadence (post-1990 regular pattern; an approximation, flagged as such):
      2y/3y/5y/7y : monthly new issue, auction late in the month, settle ~last day.
      10y/30y     : new issue in the refunding month (Feb/May/Aug/Nov), reopened the
                    other 8 months; auction ~2nd week, settle the 15th.
    Offering amount is unknown here (left NaN). This is a coverage stopgap, NOT the
    real calendar -- source is stamped 'deterministic_schedule' so downstream code
    can refuse to trust it silently.
    """
    print("  !! API UNREACHABLE -> building DETERMINISTIC schedule (approximate) !!")
    today = pd.Timestamp.today().normalize()
    recs = []
    for yr in range(1990, today.year + 1):
        for mo in range(1, 13):
            month_start = pd.Timestamp(yr, mo, 1)
            if month_start > today:
                continue
            # monthly tenors: auction ~3rd-to-last business day, settle last business day
            last_bd = (month_start + pd.offsets.BMonthEnd(0))
            auc_mid = pd.bdate_range(end=last_bd, periods=4)[0]
            for tn, yrs in [("2y", 2), ("3y", 3), ("5y", 5), ("7y", 7)]:
                recs.append(dict(auction_date=auc_mid, tenor=tn, term_years=yrs,
                                 settle_date=last_bd))
            # 10y / 30y: auction 2nd week, settle the 15th (roll fwd off weekends)
            settle15 = pd.Timestamp(yr, mo, 15)
            while settle15.weekday() >= 5:
                settle15 += pd.Timedelta(days=1)
            auc10 = pd.bdate_range(end=settle15, periods=4)[0]
            reopen = mo not in REFUNDING_MONTHS
            for tn, yrs in [("10y", 10), ("30y", 30)]:
                recs.append(dict(auction_date=auc10, tenor=tn, term_years=yrs,
                                 settle_date=settle15, reopening=reopen))
    df = pd.DataFrame(recs)
    df = df[df["auction_date"] <= today]
    df["issue_date"] = df["settle_date"]
    df["maturity_date"] = pd.NaT
    df["security_type"] = np.where(df["term_years"] >= 20, "Bond", "Note")
    df["coupon_type"] = "nominal_coupon"
    df["security_term"] = df["tenor"]
    df["original_security_term"] = df["tenor"]
    df["reopening"] = df.get("reopening", False).fillna(False)
    df["offering_amt"] = np.nan
    df["cusip"] = None
    m = df["auction_date"].dt.month
    df["refunding_month"] = m.isin(REFUNDING_MONTHS)
    df["refunding_week"] = df["refunding_month"] & df["tenor"].isin(REFUNDING_TENORS)
    df["source"] = "deterministic_schedule"
    cols = ["auction_date", "issue_date", "settle_date", "maturity_date",
            "security_type", "coupon_type", "security_term", "original_security_term",
            "tenor", "term_years", "reopening", "offering_amt",
            "refunding_month", "refunding_week", "cusip", "source"]
    return df[cols].sort_values(["auction_date", "term_years"]).reset_index(drop=True)


# --------------------------------------------------------------- validation
def validate(df: pd.DataFrame) -> None:
    print("\n--- VALIDATION ---")
    assert not df.empty, "calendar is empty"
    assert df["auction_date"].notna().all(), "null auction_date"
    assert df["settle_date"].notna().all(), "null settle_date"
    lo, hi = df["auction_date"].min(), df["auction_date"].max()
    print(f"range           : {lo.date()} .. {hi.date()}   N={len(df):,}")
    assert lo.year <= 1990 and hi.year >= 2025, "coverage does not span 1990..2025"

    nominal = df[df["coupon_type"] == "nominal_coupon"]
    print(f"nominal coupons : N={len(nominal):,}")
    print("per-tenor (nominal coupon):")
    print(nominal["tenor"].value_counts().sort_index().to_string())

    # coverage assertion: no year is near-empty. Floor is 18 (not higher) because
    # 2000-2002 genuinely thinned out -- 30y suspended 2001-2006, 7y gone 1993-2009,
    # 3y suspended 1998-2003 -- so a higher floor would encode issuance history, not
    # catch a broken pull. Any year under 18 nominal coupons signals a gap.
    per_year = nominal.groupby(nominal["auction_date"].dt.year).size()
    thin = per_year[(per_year.index >= 1990) & (per_year.index <= 2024) & (per_year < 18)]
    assert thin.empty, f"thin nominal-coupon years (<18 auctions): {thin.to_dict()}"
    print(f"coverage        : every yr 1990-2024 has >=18 nominal auctions "
          f"(min={per_year.loc[1990:2024].min()} in {per_year.loc[1990:2024].idxmin()}) OK")

    # KNOWN-AUCTION CHECK: 10y refunding new-issues auction mid-month, settle the 15th
    ten = nominal[(nominal["tenor"] == "10y") & (~nominal["reopening"])
                  & (nominal["refunding_month"])]
    if len(ten):
        sd = ten["settle_date"].dt.day
        ad = ten["auction_date"].dt.day
        mode_settle = int(sd.mode().iloc[0])
        print(f"10y refunding   : N={len(ten)}  settle-day mode={mode_settle} "
              f"(median {int(sd.median())}, range {sd.min()}-{sd.max()})  "
              f"auction-day median={int(ad.median())}")
        assert mode_settle == 15, f"10y refunding settle-day mode is {mode_settle}, expected 15"
        assert 6 <= ad.median() <= 16, f"10y auction-day median {ad.median()} not mid-month"
        print("known-auction   : 10y refunding settles the 15th, auctions mid-month  OK")

    if (df["source"] == "fiscaldata_api").all():
        assert df["offering_amt"].notna().mean() > 0.95, "offering_amt largely missing"
        print(f"offering_amt    : {df['offering_amt'].notna().mean()*100:.1f}% populated  OK")
    print("refunding_week  : N=%d nominal 3y/10y/30y in Feb/May/Aug/Nov" %
          int(df["refunding_week"].sum()))


def main() -> int:
    print("Building Treasury auction calendar 1990 -> today")
    try:
        raw = fetch_fiscaldata()
        df = build_from_api(raw)
        print(f"  built from fiscaldata API: {len(df):,} rows")
    except Exception as e:  # noqa: BLE001
        print(f"  API path failed: {e}")
        df = build_deterministic()
        print(f"  built deterministic fallback: {len(df):,} rows")

    validate(df)
    out = OUT_DIR / "auction_calendar.parquet"
    df.to_parquet(out, index=False)
    print(f"\nsaved -> {out}   ({len(df):,} rows, source={df['source'].iloc[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
