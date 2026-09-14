"""Union bond price panel + issuer reconciliation.

Three jobs:

1. UNION PANEL.  Take every (cusip, asof_dt, price) across all ingested funds and
   collapse to one row per bond-day. Where two issuers price the same bond on the
   same day we keep both the mean and the spread between them.

2. CROSS-ISSUER DISAGREEMENT.  If two issuers publish different prices for the
   same CUSIP on the same day, at least one mark is stale. That disagreement is a
   direct, model-free staleness measurement and it is the one input to the
   staleness score that needs no history at all.

3. NAV RECONCILIATION.  Rebuild each fund's NAV from its own holdings and compare
   to the issuer's reported NAV. This is the proof that the engine works; the
   runbook forbids building signals on an engine that does not reconcile.
       NAV_reconstructed = sum(market_value_i) / shares_outstanding
   Market value is used rather than weight x price because iShares market value
   is dirty (includes accrued interest) while Price is clean -- summing clean
   prices would understate NAV by roughly one coupon accrual.

Writes data/holdings/union_price_panel.parquet and results/s1/issuer_reconcile.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
HOLD = REPO / "data/holdings/etf_holdings_daily.parquet"
NAV = REPO / "data/holdings/ishares_nav_daily.parquet"
OUT_PANEL = REPO / "data/holdings/union_price_panel.parquet"
OUT_REC = REPO / "results/s1/issuer_reconcile.csv"
OUT_REC.parent.mkdir(parents=True, exist_ok=True)

CLEAN_SRC = {"published_clean", "derived_clean_mv_over_par"}


def main() -> int:
    h = pd.read_parquet(HOLD)
    h["cusip"] = h["cusip"].replace({"-": np.nan, "nan": np.nan, "": np.nan})
    bonds = h[h.cusip.notna() & h.price.notna() & (h.price > 0)].copy()

    # ---- 1. union panel (clean prices only; dirty marks are not comparable) --
    clean = bonds[bonds.price_src.isin(CLEAN_SRC)]
    g = clean.groupby(["cusip", "asof_dt"])
    panel = g.agg(
        price_mean=("price", "mean"),
        price_min=("price", "min"),
        price_max=("price", "max"),
        n_funds=("fund", "nunique"),
        n_issuers=("issuer", "nunique"),
        duration=("duration", "mean"),
        ytw=("ytw", "mean"),
        coupon=("coupon", "mean"),
        maturity_dt=("maturity_dt", "first"),
        sector=("sector", "first"),
        funds=("fund", lambda s: ",".join(sorted(set(s)))),
    ).reset_index()
    panel["disagree_bp"] = 100.0 * (panel.price_max - panel.price_min) / panel.price_mean
    panel.to_parquet(OUT_PANEL, index=False)

    latest = panel.asof_dt.max()
    cur = panel[panel.asof_dt == latest]
    print("=" * 78)
    print("UNION BOND PRICE PANEL")
    print("=" * 78)
    print(f"  latest date            {str(latest)[:10]}")
    print(f"  distinct CUSIPs priced {cur.cusip.nunique():,}")
    print(f"  total bond-days        {len(panel):,}")
    print(f"  priced by >=2 funds    {(cur.n_funds >= 2).sum():,}")
    print(f"  priced by >=2 issuers  {(cur.n_issuers >= 2).sum():,}")

    # ---- 2. cross-issuer disagreement -------------------------------------
    print()
    print("=" * 78)
    print("CROSS-ISSUER PRICE DISAGREEMENT (same CUSIP, same day, 2+ issuers)")
    print("  If two issuers disagree, at least one mark is stale.")
    print("=" * 78)
    multi = cur[cur.n_issuers >= 2]
    if len(multi):
        d = multi.disagree_bp
        print(f"  n bonds  {len(multi):,}")
        for q in (0.50, 0.75, 0.90, 0.99):
            print(f"  p{int(q*100):<3d}     {d.quantile(q):7.2f} bp")
        print(f"  mean     {d.mean():7.2f} bp   max {d.max():7.2f} bp")
        print(f"  >10bp    {(d > 10).mean()*100:5.1f}% of bonds")
        print(f"  >25bp    {(d > 25).mean()*100:5.1f}% of bonds")
    else:
        print("  none (need >=2 issuers covering a shared CUSIP)")

    # sanity: does the SSGA clean-price derivation line up with iShares?
    pair = clean[clean.asof_dt == latest].pivot_table(
        index="cusip", columns="issuer", values="price", aggfunc="mean")
    if {"iShares", "SSGA"}.issubset(pair.columns):
        p = pair.dropna()
        diff = 100.0 * (p["SSGA"] - p["iShares"]) / p["iShares"]
        print()
        print(f"  SSGA-vs-iShares on {len(p):,} shared bonds: "
              f"median {diff.median():+.2f} bp, mean {diff.mean():+.2f} bp, "
              f"|med|<5bp => SSGA MV/par is CLEAN "
              f"[{'CONFIRMED' if abs(diff.median()) < 5 else 'REJECTED'}]")

    # ---- 3. NAV reconciliation --------------------------------------------
    print()
    print("=" * 78)
    print("NAV RECONCILIATION  sum(market_value)/shares_out  vs  reported NAV")
    print("=" * 78)
    nav = pd.read_parquet(NAV)
    nav["date"] = pd.to_datetime(nav["date"])
    rows = []
    for (fund, asof), grp in h.groupby(["fund", "asof_dt"]):
        n = nav[(nav.ticker == fund) & (nav.date == asof)]
        if n.empty or grp.market_value.isna().all():
            continue
        so = n.shares_outstanding.iloc[0]
        rep = n.nav_per_share.iloc[0]
        if not so or not np.isfinite(so) or so <= 0:
            continue
        recon = grp.market_value.sum() / so
        rows.append(dict(fund=fund, asof=str(asof)[:10], reported_nav=rep,
                         recon_nav=recon, err_pct=100.0 * (recon - rep) / rep,
                         n_holdings=len(grp)))
    rec = pd.DataFrame(rows).sort_values("err_pct", key=abs, ascending=False)
    if not rec.empty:
        rec.to_csv(OUT_REC, index=False)
        print(f"{'fund':<6}{'holdings':>9}{'reported':>11}{'rebuilt':>11}{'err %':>9}")
        for _, r in rec.iterrows():
            flag = "  OK" if abs(r.err_pct) < 0.10 else "  <-- CHECK"
            print(f"{r.fund:<6}{r.n_holdings:>9,}{r.reported_nav:>11.4f}"
                  f"{r.recon_nav:>11.4f}{r.err_pct:>+9.3f}{flag}")
        ok = (rec.err_pct.abs() < 0.10).sum()
        print(f"\n  {ok}/{len(rec)} funds reconcile within 0.10%")
    print(f"\nwrote {OUT_PANEL}\n      {OUT_REC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
