"""Stage the credit RV tradeable universe.

PIT discipline
--------------
yfinance ``Adj Close`` is retroactively re-adjusted every time a distribution is
paid, so a price *level* read off it is not what was on the screen that day.  We
therefore store the UNADJUSTED close and rebuild total return from the actual
dividend on its ex-date:

    ret_total_t = (close_t * split_t + div_t) / close_{t-1} - 1

That series is point-in-time by construction and never changes when a future
distribution is paid.  ``adj_close`` is kept only as a cross-check.

Universe is grouped by the RV axis each instrument serves; see UNIVERSE below.

RESTORED 2026-10-11 (RESEARCH_PLAN_2026-10-09 item 0.1)
-------------------------------------------------------
Deleted in the 2026-09-28 clean slate and restored from tag `pre-clean-slate`
because `data/rv/etf_panel.parquet` (read by `scripts/xasset/`) had no fetcher
and `stage_ohlc.py` imports UNIVERSE from here. Three changes, nothing else:

  * SOURCE BY DATE. Rows dated on or before `YF_LAST` (2026-07-28, the last
    date of the panel staged 2026-07-28) come from yfinance exactly as before;
    every later row comes from Alpaca daily bars (`scripts/rv/alpaca_daily.py`:
    SIP, raw, cash dividends from Alpaca corporate actions), cross-checked
    against yfinance over 2025-01-02..yesterday before anything is written.
    `adj_close` is Yahoo's dividend-adjusted close, kept "only as a
    cross-check"; Alpaca has no number on the same basis, so it is NaN on
    Alpaca rows -- missing, never filled. `split` is 1.0 on Alpaca rows because
    the corporate-actions query found no split (it raises if one appears).
  * EFA, EEM, GLD, DBC added (international and EM equity, gold, broad
    commodities) for the cross-asset slate, same source rule.
  * `--out-dir` (default `data/rv`), so a rebuild can be staged and proved
    byte-identical before it replaces anything; and a fetch failure now RAISES
    instead of writing a panel that silently lacks the ticker.

Every date the old panel covered rebuilds from yfinance; whether it rebuilt
byte-identically is `scripts/rv/panel_identity.py`'s question, and the answer
for 2026-10-11 is in docs/REFERENCES.md §8.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "rv"

# Source boundary: yfinance on or before this date, Alpaca after it. It is the
# old panel's last date, so the yfinance part is exactly the range that can be
# checked against what was staged; it is not a tuning choice.
YF_LAST = "2026-07-28"
# The cross-check window starts here: 18 months of overlap before the seam.
VALIDATE_FROM = "2025-01-02"

# ticker -> (sleeve, role) ; role documents what the leg is *for*
UNIVERSE = {
    # --- HY corporate: the core RV axis (wrapper, maturity, quality) ---
    "HYG":  ("hy_corp", "iBoxx liquid HY - primary price-discovery wrapper"),
    "JNK":  ("hy_corp", "Bloomberg HY Very Liquid - competing wrapper"),
    "USHY": ("hy_corp", "broad USD HY, 0.08% fee - cheapest beta"),
    "SPHY": ("hy_corp", "SPDR portfolio HY - third wrapper"),
    "SHYG": ("hy_corp", "0-5y HY - short end of HY curve"),
    "SJNK": ("hy_corp", "short-term HY - competing short wrapper"),
    "HYGH": ("hy_corp", "rate-hedged HY - isolates credit from duration"),
    "FALN": ("fallen",  "iShares fallen angels - forced-flow boundary"),
    "ANGL": ("fallen",  "VanEck fallen angels - competing FA wrapper"),
    # --- IG corporate: quality axis and IG curve ---
    "LQD":  ("ig_corp", "iBoxx liquid IG - primary IG wrapper"),
    "VCSH": ("ig_corp", "Vanguard short IG"),
    "VCIT": ("ig_corp", "Vanguard intermediate IG"),
    "VCLT": ("ig_corp", "Vanguard long IG - long end of IG curve"),
    "IGSB": ("ig_corp", "iShares 1-5y IG"),
    "LQDH": ("ig_corp", "rate-hedged IG - isolates IG credit from duration"),
    # --- loans and structured credit: separate investor base ---
    "BKLN": ("loans",   "senior loans - floating rate, CLO-adjacent"),
    "SRLN": ("loans",   "competing senior loan wrapper"),
    "JAAA": ("clo",     "AAA CLO - structured credit, distinct buyer base"),
    "JBBB": ("clo",     "B-BBB CLO - mezz structured credit, high vol"),
    # --- adjacent credit ---
    "EMB":  ("em",      "EM USD sovereign - credit with different driver"),
    "PFF":  ("pref",    "preferreds - subordinated credit/equity hybrid"),
    "CWB":  ("conv",    "convertibles - credit/equity hybrid"),
    # --- rates: duration hedges (the leg that makes RV RV) ---
    "SHY":  ("rates",   "1-3y UST"),
    "IEI":  ("rates",   "3-7y UST"),
    "IEF":  ("rates",   "7-10y UST"),
    "TLT":  ("rates",   "20y+ UST"),
    "GOVT": ("rates",   "broad UST"),
    "BIL":  ("cash",    "1-3m bills - cash leg / financing benchmark"),
    # --- risk reference ---
    "SPY":  ("equity",  "equity beta reference for capital-structure work"),
    "AGG":  ("bench",   "aggregate bond benchmark"),
    # --- cross-asset (added 2026-10-11, plan item 0.1) ---
    "EFA":  ("intl_eq", "developed ex-US equity"),
    "EEM":  ("em_eq",   "emerging-market equity"),
    "GLD":  ("commod",  "gold (grantor trust; pays no distributions)"),
    "DBC":  ("commod",  "broad commodity futures index"),
}


def fetch_one(tkr: str, tries: int = 3) -> pd.DataFrame | None:
    """Full daily history, unadjusted close + distributions."""
    for attempt in range(tries):
        try:
            h = yf.Ticker(tkr).history(period="max", auto_adjust=False, actions=True)
            if h is None or h.empty:
                raise ValueError("empty frame")
            h = h.reset_index()
            h["date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.normalize()
            out = pd.DataFrame({
                "date": h["date"],
                "ticker": tkr,
                "close": h["Close"].astype(float),
                "adj_close": h["Adj Close"].astype(float) if "Adj Close" in h else np.nan,
                "volume": h["Volume"].astype(float),
                "dividend": h.get("Dividends", pd.Series(0.0, index=h.index)).astype(float),
                "split": h.get("Stock Splits", pd.Series(0.0, index=h.index)).astype(float),
            })
            out["split"] = out["split"].replace(0.0, 1.0)
            return out.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        except Exception as exc:  # network flake -> retry
            if attempt == tries - 1:
                print(f"  !! {tkr}: {type(exc).__name__}: {exc}")
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def total_return(df: pd.DataFrame) -> pd.DataFrame:
    """PIT total return from split-adjusted close + ex-date dividend.

    NOTE ON THE SPLIT TERM.  With ``auto_adjust=False`` yfinance still returns a
    SPLIT-adjusted ``Close`` (the flag governs dividend adjustment only), and the
    ``Dividends`` column is expressed in those same split-adjusted units.  So the
    split factor must NOT be applied again here.  Doing so produced a spurious
    -66.7% day for JNK on its 2019-05-06 1:3 reverse split and -50.0% for BIL on
    2017-11-30 - caught by cross-checking against the CRSP-sourced panel, where
    JNK's CAGR came out -1.06%/yr instead of +4.96%/yr.

    ``split`` is retained in the panel purely as an audit column.
    """
    df = df.sort_values("date").copy()
    prev = df["close"].shift(1)
    df["ret_total"] = (df["close"] + df["dividend"]) / prev - 1.0
    df["ret_px"] = df["close"] / prev - 1.0
    df.loc[df.index[0], ["ret_total", "ret_px"]] = np.nan
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", type=Path, default=OUT,
                    help="where the four outputs go (default data/rv)")
    out = ap.parse_args(argv).out_dir
    out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT))
    from scripts.rv import alpaca_daily as ad

    seam = pd.Timestamp(YF_LAST)
    fetched, missing = {}, []
    for tkr in UNIVERSE:
        d = fetch_one(tkr)
        if d is None or d.empty:
            missing.append(tkr)
            continue
        fetched[tkr] = total_return(d)
    if missing:
        # The old script wrote the panel anyway and printed MISSING; a panel
        # that silently lacks a ticker is the failure CLAUDE.md forbids.
        raise RuntimeError(f"yfinance fetch failed for {missing}; nothing written")

    yf_full = pd.concat(fetched.values(), ignore_index=True)
    alp, stats = ad.continue_after(yf_full, YF_LAST, VALIDATE_FROM, ohlc=False)
    print("--- alpaca vs yfinance (ret_total, in-house on each side) ---")
    print(stats.to_string(index=False))

    frames = []
    for tkr, (sleeve, role) in UNIVERSE.items():
        d = fetched[tkr]
        d = d[d["date"] <= seam].copy()            # yfinance part, as staged
        a = alp[alp["ticker"] == tkr]
        tail = pd.DataFrame({
            "date": a["date"], "ticker": tkr, "close": a["close"],
            "adj_close": np.nan,                    # no Alpaca number on Yahoo's basis
            "volume": a["volume"], "dividend": a["dividend"],
            "split": 1.0,                           # no split: alpaca_daily raises on one
            "ret_total": a["ret_total"], "ret_px": a["ret_px"]})
        d = pd.concat([d, tail], ignore_index=True)
        d["sleeve"] = sleeve
        frames.append(d)
        print(f"  {tkr:5s} {sleeve:8s} {len(d):>6,} rows  "
              f"{d['date'].min().date()} -> {d['date'].max().date()}  "
              f"(alpaca rows after {YF_LAST}: {len(tail)})")

    panel = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"])
    assert not panel.duplicated(["ticker", "date"]).any(), "dup ticker/date"
    panel.to_parquet(out / "etf_panel.parquet", index=False)

    # wide total-return matrix, business-day indexed
    wide = panel.pivot(index="date", columns="ticker", values="ret_total").sort_index()
    wide.to_parquet(out / "returns_wide.parquet")

    px = panel.pivot(index="date", columns="ticker", values="close").sort_index()
    px.to_parquet(out / "close_unadj_wide.parquet")

    meta = pd.DataFrame(
        [{"ticker": t, "sleeve": s, "role": r} for t, (s, r) in UNIVERSE.items()]
    )
    first_last = panel.groupby("ticker")["date"].agg(["min", "max", "count"]).reset_index()
    meta = meta.merge(first_last, on="ticker", how="left")
    meta.to_csv(out / "universe_meta.csv", index=False)

    print(f"\npanel   {panel.shape}  -> {out/'etf_panel.parquet'}")
    print(f"returns {wide.shape}  -> {out/'returns_wide.parquet'}")
    print(f"span    {wide.index.min().date()} -> {wide.index.max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
