"""Auction-calendar loader for the Engine B+ auction-cycle butterfly test.

    import sys; sys.path.insert(0, "scripts/auction")
    from _cal import load_auction_calendar, auction_dates, nominal_coupon_auctions

    cal = load_auction_calendar()                       # full frame
    d10 = auction_dates("10y")                           # 10y nominal-coupon auction dates
    ref = nominal_coupon_auctions(refunding_week=True)   # Feb/May/Aug/Nov 3y/10y/30y slug

Columns in auction_calendar.parquet
    auction_date            when the auction is held (datetime64)
    issue_date / settle_date  settlement date (issue_date == settle_date)
    maturity_date           security maturity (NaT for a few legacy rows)
    security_type           Bill | Note | Bond            (fiscaldata taxonomy)
    coupon_type             nominal_coupon | tips | frn | bill
    security_term           raw term e.g. '9-Year 10-Month' (reopenings show reduced term)
    original_security_term  raw ORIGINAL term e.g. '10-Year' (reopening collapsed back)
    tenor                   canonical label: 2y/3y/4y/5y/7y/10y/20y/30y (coupons),
                            4w/8w/13w/17w/26w/52w... (bills)
    term_years              float years of the ORIGINAL term (10y reopening -> 10.0)
    reopening               bool
    offering_amt            USD offering amount (float; 100% populated from the API)
    refunding_month         auction month in {Feb,May,Aug,Nov}
    refunding_week          nominal-coupon 3y/10y/30y in a refunding month (peak slug)
    cusip                   security CUSIP
    source                  'fiscaldata_api' (or 'deterministic_schedule' fallback)

Provenance: fiscaldata.treasury.gov Auctions Query, auction_date>=1990-01-01, built
by scripts/auction/build_calendar.py. Namespaced to data/auction/ (read-only here).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CAL_PARQUET = REPO / "data" / "auction" / "auction_calendar.parquet"

COUPON_TENORS = ["2y", "3y", "4y", "5y", "7y", "10y", "20y", "30y"]


def load_auction_calendar() -> pd.DataFrame:
    """Full auction calendar, sorted by auction_date. Dates are datetime64."""
    if not CAL_PARQUET.exists():
        raise FileNotFoundError(
            f"{CAL_PARQUET} missing -- run scripts/auction/build_calendar.py first")
    df = pd.read_parquet(CAL_PARQUET)
    for c in ("auction_date", "issue_date", "settle_date", "maturity_date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df.sort_values(["auction_date", "term_years"]).reset_index(drop=True)


def nominal_coupon_auctions(tenors=None, reopening=None,
                            refunding_week=None) -> pd.DataFrame:
    """Nominal-coupon (non-TIPS, non-FRN, non-bill) auctions, optionally filtered.

    tenors        : iterable of canonical labels e.g. ('5y','10y','30y'); None=all
    reopening     : True/False to keep only reopenings / new issues; None=both
    refunding_week: True/False on the refunding-week flag; None=both
    """
    df = load_auction_calendar()
    df = df[df["coupon_type"] == "nominal_coupon"]
    if tenors is not None:
        df = df[df["tenor"].isin(list(tenors))]
    if reopening is not None:
        df = df[df["reopening"] == bool(reopening)]
    if refunding_week is not None:
        df = df[df["refunding_week"] == bool(refunding_week)]
    return df.reset_index(drop=True)


def auction_dates(tenor: str, coupon_type: str = "nominal_coupon",
                  reopening=None, refunding_week=None) -> pd.DatetimeIndex:
    """Unique, sorted auction dates for one tenor (default nominal coupon)."""
    df = load_auction_calendar()
    df = df[(df["tenor"] == tenor) & (df["coupon_type"] == coupon_type)]
    if reopening is not None:
        df = df[df["reopening"] == bool(reopening)]
    if refunding_week is not None:
        df = df[df["refunding_week"] == bool(refunding_week)]
    return pd.DatetimeIndex(sorted(df["auction_date"].unique()))


def _selftest() -> None:
    df = load_auction_calendar()
    assert not df.empty, "auction calendar is empty"
    assert df["auction_date"].notna().all(), "null auction_date present"
    lo, hi = df["auction_date"].min(), df["auction_date"].max()
    print(f"auction_calendar: {CAL_PARQUET}")
    print(f"range           : {lo.date()} .. {hi.date()}   N={len(df):,}   "
          f"source={df['source'].iloc[0]}")

    print("\nper security_type:")
    print(df["security_type"].value_counts().to_string())
    print("\nper coupon_type:")
    print(df["coupon_type"].value_counts().to_string())

    nom = df[df["coupon_type"] == "nominal_coupon"]
    print(f"\nnominal-coupon auctions: N={len(nom):,}")
    print("per-tenor (nominal coupon):")
    print(nom["tenor"].value_counts().reindex(COUPON_TENORS).dropna().astype(int).to_string())

    print(f"\nrefunding-week rows (nominal 3y/10y/30y, Feb/May/Aug/Nov): "
          f"{int(df['refunding_week'].sum()):,}")
    d10 = auction_dates("10y")
    d30 = auction_dates("30y")
    d5 = auction_dates("5y")
    print(f"auction_dates() : 5y={len(d5)}  10y={len(d10)}  30y={len(d30)}")
    assert len(d10) > 100 and len(d5) > 100, "too few 5y/10y auction dates"

    print("\n_cal.py selftest OK -- calendar non-empty and consistent.")


if __name__ == "__main__":
    _selftest()
