"""E1 data assembly + the pre-committed bounce falsification test.

Per E1_PREREG.md §3.1 this runs BEFORE any performance number is computed. If the
2x2 says the edge lives in the closing print rather than in the premium/discount,
the family is killed and nothing further is built.

THE SPLIT-SAFE MID PREMIUM
--------------------------
The staged premium/discount is built from the *unadjusted* exchange close, while
the OHLC panel carries split-adjusted prices. Rather than reconcile two price
conventions (JNK had a 1:3 reverse split in 2019), the mid premium is derived as a
RATIO, which is invariant to any per-day scaling of the price series:

    PD_price = (P - NAV)/NAV          =>   P/NAV = 1 + PD_price
    PD_mid   = (M - NAV)/NAV = M/NAV - 1 = (M/P)(1 + PD_price) - 1

M and P are the same day's mid and close from the SAME file, so any split factor
cancels exactly. No re-adjustment, no seam risk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "e1"
OUT.mkdir(parents=True, exist_ok=True)

PAIR = ["HYG", "JNK"]


def build() -> pd.DataFrame:
    pd_der = pd.read_parquet(ROOT / "data/forced_flow2/hyg_jnk_pd_derived.parquet")
    pd_der["date"] = pd.to_datetime(pd_der["date"])

    ohlc = pd.read_parquet(ROOT / "data/rv/etf_ohlc.parquet")
    ohlc = ohlc[ohlc["ticker"].isin(PAIR)].copy()
    ohlc["date"] = pd.to_datetime(ohlc["date"])

    # CRSP-quality total returns (audited), spliced to yfinance from 2025.
    rets = pd.read_parquet(ROOT / "data/etf_daily.parquet")
    rets = rets[rets["ticker"].isin(PAIR)][["date", "ticker", "ret_total"]].copy()
    rets["date"] = pd.to_datetime(rets["date"])

    df = (ohlc[["date", "ticker", "open", "high", "low", "close", "volume"]]
          .merge(pd_der[["date", "ticker", "premium_discount_pct"]],
                 on=["date", "ticker"], how="inner")
          .merge(rets, on=["date", "ticker"], how="left"))

    df["pd_price"] = df["premium_discount_pct"] / 100.0
    df["mid_hl"] = (df["high"] + df["low"]) / 2.0
    # split-safe mid premium (see module docstring)
    df["pd_mid"] = (df["mid_hl"] / df["close"]) * (1.0 + df["pd_price"]) - 1.0
    # bounce-free return series, for the 2x2's "return on MID" column
    df = df.sort_values(["ticker", "date"])
    df["ret_mid"] = df.groupby("ticker")["mid_hl"].pct_change()
    return df.reset_index(drop=True)


def wide(df, col):
    return df.pivot(index="date", columns="ticker", values=col).sort_index()


def sharpe(x):
    x = pd.Series(x).dropna()
    if len(x) < 50 or x.std() == 0:
        return np.nan
    return float(x.mean() / x.std() * np.sqrt(252))


def run_cell(sig_wide, ret_wide, win=120, lag=1):
    """Unit-gross, dollar-neutral 2-leg book on the relative signal.

    w_HYG = -z, w_JNK = +z, normalised to unit gross. Deliberately the crudest
    possible expression: no bands, no sizing, no filtering. The point of the 2x2
    is to compare price conventions, and any machinery in between would confound
    that comparison (FINDINGS.md §8d is the cautionary tale).
    """
    s = (sig_wide["HYG"] - sig_wide["JNK"]).dropna()
    z = (s - s.rolling(win).mean()) / s.rolling(win).std()
    z = z.replace([np.inf, -np.inf], np.nan).dropna()

    r = ret_wide.reindex(z.index)
    spread_ret = (r["HYG"] - r["JNK"]) / 2.0          # unit gross across two legs
    pnl = (-z).shift(lag) * spread_ret                 # rich HYG -> short HYG
    return pnl.dropna(), z


def main() -> int:
    df = build()
    n_pair = df.groupby("date")["ticker"].nunique()
    both = n_pair[n_pair == 2].index
    df = df[df["date"].isin(both)]
    print(f"panel: {len(df):,} rows  {df.date.min().date()} -> {df.date.max().date()}  "
          f"({len(both):,} paired days)")

    df.to_parquet(OUT / "e1_panel.parquet", index=False)

    pd_mid = wide(df, "pd_mid")
    pd_px = wide(df, "pd_price")
    ret_c = wide(df, "ret_total")
    ret_m = wide(df, "ret_mid")

    print("\nrelative premium (HYG - JNK), bp of NAV:")
    for nm, w in (("from CLOSE", pd_px), ("from MID", pd_mid)):
        s = (w["HYG"] - w["JNK"]).dropna() * 1e4
        print(f"  {nm:10s} n={len(s):>5,}  mean={s.mean():+7.2f}  sd={s.std():6.2f}  "
              f"p1={s.quantile(.01):+7.2f}  p99={s.quantile(.99):+7.2f}")

    print("\n" + "=" * 74)
    print("PRE-COMMITTED BOUNCE FALSIFICATION 2x2  (E1_PREREG.md §3.1)")
    print("=" * 74)
    print(f"{'':22s} {'return on CLOSE':>17s} {'return on MID':>16s}")
    cells = {}
    for sig_name, sig_w in (("signal from CLOSE", pd_px), ("signal from MID", pd_mid)):
        row = []
        for ret_name, ret_w in (("close", ret_c), ("mid", ret_m)):
            p, _ = run_cell(sig_w, ret_w)
            sr = sharpe(p)
            cells[(sig_name, ret_name)] = sr
            row.append(sr)
        print(f"{sig_name:22s} {row[0]:>17.2f} {row[1]:>16.2f}")

    cc = cells[("signal from CLOSE", "close")]
    mc = cells[("signal from MID", "close")]
    cm = cells[("signal from CLOSE", "mid")]
    print("\nInterpretation:")
    print(f"  close->close = {cc:+.2f}   (contaminated: signal and return share the print)")
    print(f"  mid  ->close = {mc:+.2f}   (TRADEABLE: bounce-free signal, real execution)")
    print(f"  close->mid   = {cm:+.2f}   (does a close signal predict FAIR VALUE at all?)")
    ratio = mc / cc if cc and abs(cc) > 1e-9 else np.nan
    print(f"\n  tradeable / contaminated = {ratio:.2f}")
    verdict = "PASS" if (mc > 0 and (np.isnan(ratio) or ratio > 0.5)) else "FAIL"
    print(f"  VERDICT: {verdict}")
    if verdict == "FAIL":
        print("  -> The edge is in the closing print, not the premium. Per §8, KILL.")
    else:
        print("  -> The premium survives on a bounce-free price. Proceed to §5/§6 gates.")

    # lag ladder — a real signal decays smoothly; bounce collapses at lag 2
    print("\nlag ladder on the tradeable cell (mid signal, close returns):")
    for lag in (0, 1, 2, 3, 5):
        p, _ = run_cell(pd_mid, ret_c, lag=lag)
        print(f"   lag {lag}: Sharpe {sharpe(p):+.2f}")

    pd.DataFrame([{"cell": f"{k[0]}|{k[1]}", "sharpe": v} for k, v in cells.items()]) \
        .to_csv(OUT / "bounce_2x2.csv", index=False)
    print(f"\nwrote {OUT/'e1_panel.parquet'} and {OUT/'bounce_2x2.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
