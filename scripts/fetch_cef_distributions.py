"""Fetch CEF distribution history + fund structure facts from yfinance.

Outputs:
  data/cef/cef_distributions.parquet   raw ex-date/amount panel (+ splits)
  data/cef/cef_dist_features.parquet   per-ticker/per-ex-date event features
  data/cef/cef_facts.csv               static/structural facts from .info
                                       *** A DATED SNAPSHOT, NOT A PANEL. ***
                                       Carries fetched_at. Every row holds the
                                       fund's attributes AS OF THAT INSTANT and
                                       there is no history behind them, so
                                       joining it to the 27-year panel applies
                                       today's facts to 2005 -- look-ahead with
                                       no error message. 13 of 46 columns were
                                       100% null and 5 constant across all 44
                                       rows at the 2026-07-31 fetch. Superseded
                                       by docs/prompts/perfund/F1.
  data/cef/_raw_info.json              raw .info dicts (audit trail)
"""
import json
from pathlib import Path
import os
import time
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.common import atomic_write   # noqa: E402

warnings.filterwarnings("ignore")

ROOT = str(Path(__file__).resolve().parents[1])  # repo root, not hardcoded
CEF = os.path.join(ROOT, "data", "cef")

uni = pd.read_csv(os.path.join(CEF, "cef_universe.csv"))
TICKERS = uni["ticker"].tolist()
GRP = dict(zip(uni["ticker"], uni["grp"]))
print(f"universe: {len(TICKERS)} tickers")


def naive_date(idx):
    s = pd.DatetimeIndex(idx)
    if s.tz is not None:
        s = s.tz_localize(None)
    return s.normalize()


# ---------------------------------------------------------------- 1. actions
rows = []
errors = {}
empty = []

for i, tk in enumerate(TICKERS, 1):
    got = None
    for attempt in range(3):
        try:
            t = yf.Ticker(tk)
            act = t.actions
            if act is None or len(act) == 0:
                # fall back to .dividends alone
                dv = t.dividends
                if dv is not None and len(dv) > 0:
                    act = dv.to_frame("Dividends")
                    act["Stock Splits"] = 0.0
                else:
                    act = pd.DataFrame(columns=["Dividends", "Stock Splits"])
            got = act
            break
        except Exception as e:  # network / parse
            errors[tk] = f"{type(e).__name__}: {e}"
            time.sleep(2 + 2 * attempt)
    if got is None:
        print(f"  [{i:2d}/{len(TICKERS)}] {tk:5s} FAILED  {errors.get(tk)}")
        continue
    if len(got) == 0:
        empty.append(tk)
        print(f"  [{i:2d}/{len(TICKERS)}] {tk:5s} EMPTY (0 actions)")
        continue

    df = got.copy()
    df.index = naive_date(df.index)
    df = df.reset_index()
    df.columns = ["ex_date"] + list(df.columns[1:])
    df["ticker"] = tk
    df["grp"] = GRP.get(tk)
    rows.append(df)
    ndiv = int((df.get("Dividends", pd.Series(dtype=float)) > 0).sum())
    nspl = int((df.get("Stock Splits", pd.Series(dtype=float)) > 0).sum())
    print(f"  [{i:2d}/{len(TICKERS)}] {tk:5s} rows={len(df):4d} div={ndiv:4d} splits={nspl}")
    time.sleep(0.3)

if not rows:
    raise SystemExit("NO distribution data fetched at all - aborting, nothing written.")

acts = pd.concat(rows, ignore_index=True)
for c in ("Dividends", "Stock Splits"):
    if c not in acts.columns:
        acts[c] = 0.0
acts = acts.rename(columns={"Dividends": "amount", "Stock Splits": "stock_split"})
acts["amount"] = pd.to_numeric(acts["amount"], errors="coerce").fillna(0.0)
acts["stock_split"] = pd.to_numeric(acts["stock_split"], errors="coerce").fillna(0.0)

dist = acts[acts["amount"] > 0].copy()
dist = dist[["ticker", "grp", "ex_date", "amount", "stock_split"]]
dist = dist.sort_values(["ticker", "ex_date"]).reset_index(drop=True)

splits = acts[acts["stock_split"] > 0][["ticker", "ex_date", "stock_split"]].copy()
splits = splits.sort_values(["ticker", "ex_date"]).reset_index(drop=True)

out_dist = os.path.join(CEF, "cef_distributions.parquet")
atomic_write(dist, out_dist)
print(f"\nwrote {out_dist}  {dist.shape}")
if len(splits):
    atomic_write(splits, os.path.join(CEF, "cef_splits.parquet"))
    print(f"wrote cef_splits.parquet  {splits.shape}")

# ---------------------------------------------------------------- 2. features
px = pd.read_parquet(os.path.join(CEF, "cef_prices.parquet"))
px = px[["ticker", "date", "close"]].dropna().sort_values(["ticker", "date"])

feat = []
for tk, g in dist.groupby("ticker", sort=True):
    g = g.sort_values("ex_date").reset_index(drop=True).copy()
    g["prev_amount"] = g["amount"].shift(1)
    g["prev_ex_date"] = g["ex_date"].shift(1)
    g["pct_change_vs_prev"] = (g["amount"] / g["prev_amount"] - 1.0) * 100.0
    g["days_since_prev"] = (g["ex_date"] - g["prev_ex_date"]).dt.days
    g["months_since_prev"] = g["days_since_prev"] / 30.436875
    g["is_cut"] = g["amount"] < g["prev_amount"] * 0.99
    g["is_raise"] = g["amount"] > g["prev_amount"] * 1.01
    # trailing 12m total = sum of amounts with ex_date in (t-365d, t]
    amt = g["amount"].values
    dts = g["ex_date"].values.astype("datetime64[D]").astype(int)
    t12 = np.empty(len(g))
    for j in range(len(g)):
        lo = dts[j] - 365
        t12[j] = amt[(dts > lo) & (dts <= dts[j])].sum()
    g["trailing_12m_total"] = t12
    # number of distributions in that same window -> implied frequency
    n12 = np.empty(len(g))
    for j in range(len(g)):
        lo = dts[j] - 365
        n12[j] = ((dts > lo) & (dts <= dts[j])).sum()
    g["n_dists_ttm"] = n12
    feat.append(g)

f = pd.concat(feat, ignore_index=True)

# price on ex_date: exact match if traded, else last close on/before ex_date
f = f.sort_values("ex_date")
merged = []
for tk, g in f.groupby("ticker", sort=False):
    p = px[px["ticker"] == tk][["date", "close"]].sort_values("date")
    if len(p) == 0:
        g["price_on_ex_date"] = np.nan
        g["price_date_used"] = pd.NaT
        merged.append(g)
        continue
    g = g.sort_values("ex_date")
    m = pd.merge_asof(
        g, p.rename(columns={"date": "price_date_used", "close": "price_on_ex_date"}),
        left_on="ex_date", right_on="price_date_used", direction="backward",
        tolerance=pd.Timedelta("7D"),
    )
    merged.append(m)

f = pd.concat(merged, ignore_index=True)
f["price_is_exact"] = f["price_date_used"] == f["ex_date"]
f["annualized_yield_pct"] = f["trailing_12m_total"] / f["price_on_ex_date"] * 100.0
f.loc[~np.isfinite(f["annualized_yield_pct"]), "annualized_yield_pct"] = np.nan

cols = [
    "ticker", "grp", "ex_date", "amount", "prev_amount", "prev_ex_date",
    "pct_change_vs_prev", "days_since_prev", "months_since_prev",
    "is_cut", "is_raise", "trailing_12m_total", "n_dists_ttm",
    "price_on_ex_date", "price_date_used", "price_is_exact",
    "annualized_yield_pct",
]
f = f[cols].sort_values(["ticker", "ex_date"]).reset_index(drop=True)
out_feat = os.path.join(CEF, "cef_dist_features.parquet")
atomic_write(f, out_feat)
print(f"wrote {out_feat}  {f.shape}")

# ---------------------------------------------------------------- 3. facts
FIELDS = [
    "symbol", "longName", "shortName", "quoteType", "typeDisp", "legalType",
    "category", "fundFamily", "totalAssets", "netAssets", "marketCap",
    "nonDilutedMarketCap", "sharesOutstanding", "impliedSharesOutstanding",
    "yield", "dividendYield", "dividendRate", "trailingAnnualDividendRate",
    "trailingAnnualDividendYield", "fiveYearAvgDividendYield", "payoutRatio",
    "lastDividendValue", "lastDividendDate", "exDividendDate", "dividendDate",
    "navPrice", "bookValue", "priceToBook", "beta", "beta3Year",
    "fundInceptionDate", "totalDebt", "debtToEquity", "totalExpenseRatio",
    "annualReportExpenseRatio", "netExpenseRatio", "annualHoldingsTurnover",
    "sector", "industry", "exchange", "fullExchangeName", "currency",
    "longBusinessSummary",
]

raw_info = {}
fact_rows = []
info_err = {}
for i, tk in enumerate(TICKERS, 1):
    info = None
    for attempt in range(3):
        try:
            info = yf.Ticker(tk).info
            break
        except Exception as e:
            info_err[tk] = f"{type(e).__name__}: {e}"
            time.sleep(2 + 2 * attempt)
    if not info:
        print(f"  info [{i:2d}] {tk:5s} FAILED {info_err.get(tk)}")
        raw_info[tk] = {}
        fact_rows.append({"ticker": tk, "grp": GRP.get(tk)})
        continue
    raw_info[tk] = info
    r = {"ticker": tk, "grp": GRP.get(tk)}
    for fld in FIELDS:
        v = info.get(fld, None)
        if isinstance(v, str):
            v = v.replace("\n", " ").strip()
            if fld == "longBusinessSummary":
                v = v[:400]
        r[fld] = v
    # leverage hints scraped from the business summary text
    summ = (info.get("longBusinessSummary") or "").lower()
    r["summary_mentions_leverage"] = ("leverage" in summ) or ("leveraged" in summ)
    fact_rows.append(r)
    print(f"  info [{i:2d}/{len(TICKERS)}] {tk:5s} n_fields={len(info)} quoteType={info.get('quoteType')}")
    time.sleep(0.3)

facts = pd.DataFrame(fact_rows)

# STAMP THE SNAPSHOT. Without this column cef_facts.csv looks like a fact table
# and is not one: it is a single yfinance .info snapshot taken on one afternoon,
# with no history. Joining it to the 27-year price/NAV panel applies TODAY's
# fund attributes to every historical date -- a look-ahead error that produces
# no error message. Measured 2026-09-10 on the 2026-07-31 snapshot: 13 of its
# 46 columns are 100% null (netAssets, netExpenseRatio, fundFamily,
# fundInceptionDate among them) and quoteType/typeDisp/sector/industry are
# constant across all 44 rows, so most of what looks like per-fund data is not.
# ops/doctor.py warns until this column exists. See docs/prompts/perfund/F1,
# which supersedes this file with a dated characteristics panel.
facts.insert(0, "fetched_at", pd.Timestamp.utcnow().tz_localize(None).isoformat(timespec="seconds"))

out_facts = os.path.join(CEF, "cef_facts.csv")
atomic_write(facts, out_facts)
print(f"wrote {out_facts}  {facts.shape}  (fetched_at stamped; this is a SNAPSHOT,")
print("  not a panel -- do not join it to history without reading its header note)")

with open(os.path.join(CEF, "_raw_info.json"), "w") as fh:
    json.dump({k: {kk: (str(vv) if not isinstance(vv, (int, float, str, bool, type(None))) else vv)
                   for kk, vv in v.items()} for k, v in raw_info.items()}, fh, indent=1)

diag = {
    "n_universe": len(TICKERS),
    "fetch_errors": errors,
    "empty_action_tickers": empty,
    "info_errors": info_err,
}
with open(os.path.join(CEF, "_fetch_diagnostics.json"), "w") as fh:
    json.dump(diag, fh, indent=1)
print("\nDONE")
print("empty:", empty)
print("errors:", list(errors))
