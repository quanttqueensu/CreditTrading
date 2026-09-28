"""Measure REAL bid/ask spreads for the credit RV universe from IBKR history.

WHY THIS EXISTS
---------------
Every cost number in `config/costs_rv.yaml` is a MODELLED estimate: a $0.005 tick
floor times a liquidity-tier multiple. Its own `_provenance` field says so, and
says "ESTIMATE pending RTH IBKR re-probe". The only probe ever taken
(`ibkr_spread_probe.csv`, 2026-07-28 20:04) ran AFTER the close on DELAYED data and
returned FALN at 1490bp and SPY at 0.605bp. It is unusable and was never used.

The entire deploy decision reduces to one scale-invariant number: the bounce-free
book earns ~1.18bp per unit of turnover. If the true round-trip cost is below that,
the strategy is live; above it, it is not. Leverage cannot change the ratio. So the
cost model must be MEASURED, not assumed.

WHAT IS FETCHED
---------------
IBKR `whatToShow='BID_ASK'` historical bars. For such bars IBKR defines:

    open  = time-average BID over the bar
    close = time-average ASK over the bar
    low   = minimum BID
    high  = maximum ASK

so the time-average quoted spread over a bar is exactly `close - open`. This is a
real quoted spread from the consolidated book, not a tick-floor guess, and it does
NOT require the market to be open to retrieve.

Two resolutions, because they answer different questions:

  * DAILY bars over several years -> the long-run average spread per name. Big
    sample, robust, matches the backtest's daily horizon.
  * 5-MINUTE bars over the last ~60 sessions, keeping the 15:55-16:00 bar -> the
    spread in the CLOSING WINDOW specifically, which is where this book actually
    trades. Smaller sample, but it is the price we would really pay.

Both are written; the rebuild step prefers the closing-window number where it
exists and falls back to the daily average.

HONESTY GUARDS
--------------
  * `useRTH=True` everywhere. After-hours books are wide and meaningless here.
  * Every row records its bar count, so thin measurements can be down-weighted.
  * SPY is fetched as a CONTROL. Its true half-spread is ~0.1bp. If the measured
    SPY number comes back far from that, the whole measurement is suspect and the
    script says so rather than letting a bad number into the cost model.

Usage:  python3 scripts/rv/fetch_ibkr_spreads.py [--port 7497] [--client-id 41]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "credit_rv"
OUT.mkdir(parents=True, exist_ok=True)

# The 22 credit names the book may trade, plus rates hedges it trades against,
# plus SPY purely as a measurement control.
CREDIT = ["HYG", "JNK", "USHY", "SPHY", "SHYG", "SJNK", "HYGH", "ANGL", "FALN",
          "LQD", "VCSH", "VCIT", "VCLT", "IGSB", "LQDH",
          "BKLN", "SRLN", "JAAA", "JBBB", "EMB", "PFF", "CWB"]
HEDGES = ["SHY", "IEI", "IEF", "TLT", "GOVT", "AGG"]
CONTROL = ["SPY"]
TICKERS = CREDIT + HEDGES + CONTROL

# IBKR historical pacing: 60 requests per 10 min. We issue 2 per name, so pace
# deliberately rather than discovering the limit through errors.
PACE_SEC = 2.5


def _spread_bp(df: pd.DataFrame) -> pd.DataFrame:
    """BID_ASK bars -> per-bar quoted spread in bp of mid."""
    bid = df["open"].astype(float)     # time-average bid
    ask = df["close"].astype(float)    # time-average ask
    mid = (bid + ask) / 2.0
    out = df.copy()
    out["bid_avg"] = bid
    out["ask_avg"] = ask
    out["mid"] = mid
    out["spread_bp"] = np.where(mid > 0, (ask - bid) / mid * 1e4, np.nan)
    # a crossed or zero book is a data artefact, not a tradeable spread
    out.loc[(ask <= bid) | (mid <= 0), "spread_bp"] = np.nan
    return out


def _ib_module():
    """Prefer `ib_async` (maintained fork). `ib_insync` 0.9.86 is unmaintained and
    hangs in its asyncio handshake on Python 3.12+ — TWS answers a raw socket
    handshake fine while the library never returns, which reads deceptively like
    a broker problem."""
    try:
        import ib_async as m
        return m, "ib_async"
    except ImportError:
        import ib_insync as m
        return m, "ib_insync"


def fetch_one(ib, contract, duration: str, bar: str, label: str):
    """One historical BID_ASK request, with pacing-violation retry."""
    util = _ib_module()[0].util
    for attempt in range(3):
        try:
            bars = ib.reqHistoricalData(
                contract, endDateTime="", durationStr=duration,
                barSizeSetting=bar, whatToShow="BID_ASK", useRTH=True,
                formatDate=1, keepUpToDate=False,
            )
            if not bars:
                return None
            df = util.df(bars)
            if df is None or df.empty:
                return None
            return _spread_bp(df)
        except Exception as exc:
            msg = str(exc)
            if "pacing" in msg.lower() and attempt < 2:
                time.sleep(20)
                continue
            print(f"    !! {label}: {type(exc).__name__}: {msg[:120]}")
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=41)
    ap.add_argument("--daily-duration", default="5 Y")
    ap.add_argument("--intraday-duration", default="60 D")
    args = ap.parse_args()

    try:
        mod, modname = _ib_module()
        IB, Stock = mod.IB, mod.Stock
    except ImportError:
        print("FATAL: neither ib_async nor ib_insync importable")
        return 2
    print(f"using {modname}")

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=25)
    except Exception as exc:
        print(f"FATAL: connect failed on {args.host}:{args.port}: "
              f"{type(exc).__name__}: {exc}")
        print("  -> Is TWS/IB Gateway running and logged in, with "
              "'Enable ActiveX and Socket Clients' ticked on this port?")
        return 2

    print(f"connected: {ib.isConnected()}  server {ib.client.serverVersion()}")

    daily_rows, close_rows = [], []
    daily_panels = {}

    for i, t in enumerate(TICKERS, 1):
        c = Stock(t, "SMART", "USD")
        try:
            q = ib.qualifyContracts(c)
            if not q:
                print(f"  {t:5s} !! could not qualify contract")
                continue
            c = q[0]
        except Exception as exc:
            print(f"  {t:5s} !! qualify failed: {exc}")
            continue

        # --- long-run daily average spread ---
        d = fetch_one(ib, c, args.daily_duration, "1 day", f"{t} daily")
        time.sleep(PACE_SEC)
        if d is not None and d["spread_bp"].notna().sum() >= 30:
            s = d["spread_bp"].dropna()
            daily_panels[t] = d[["date", "spread_bp", "mid"]].assign(ticker=t)
            daily_rows.append(dict(
                ticker=t, n_days=int(s.size),
                spread_bp_mean=float(s.mean()),
                spread_bp_median=float(s.median()),
                spread_bp_p90=float(s.quantile(0.90)),
                half_spread_bp_median=float(s.median() / 2.0),
                px=float(d["mid"].iloc[-1]),
                first=str(d["date"].iloc[0]), last=str(d["date"].iloc[-1]),
            ))
            print(f"  {t:5s} daily  n={s.size:>5d}  median spread {s.median():>7.2f}bp"
                  f"  -> half {s.median()/2:>6.2f}bp")
        else:
            print(f"  {t:5s} daily  no usable BID_ASK history")

        # --- closing-window spread (the price this book actually pays) ---
        m = fetch_one(ib, c, args.intraday_duration, "5 mins", f"{t} 5min")
        time.sleep(PACE_SEC)
        if m is not None and m["spread_bp"].notna().sum() >= 30:
            ts = pd.to_datetime(m["date"], utc=True, errors="coerce")
            et = ts.dt.tz_convert(ZoneInfo("America/New_York"))
            # 15:55 bar is the final RTH 5-minute bar
            last_bar = (et.dt.hour == 15) & (et.dt.minute >= 55)
            sc = m.loc[last_bar, "spread_bp"].dropna()
            if sc.size >= 10:
                close_rows.append(dict(
                    ticker=t, n_closes=int(sc.size),
                    close_spread_bp_median=float(sc.median()),
                    close_half_spread_bp=float(sc.median() / 2.0),
                    close_spread_bp_p90=float(sc.quantile(0.90)),
                ))
                print(f"  {t:5s} close  n={sc.size:>5d}  median spread "
                      f"{sc.median():>7.2f}bp  -> half {sc.median()/2:>6.2f}bp")

    ib.disconnect()

    if not daily_rows and not close_rows:
        print("\nFATAL: no BID_ASK history retrieved for any name.")
        print("  Historical bid/ask requires a Level 1 US equity market-data")
        print("  subscription on the logged-in account. Check TWS -> Account ->")
        print("  Market Data Subscriptions.")
        return 3

    dd = pd.DataFrame(daily_rows)
    cc = pd.DataFrame(close_rows)
    merged = dd.merge(cc, on="ticker", how="outer") if not cc.empty else dd

    meta = {
        "fetched_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "use_rth": True,
        "daily_duration": args.daily_duration,
        "intraday_duration": args.intraday_duration,
        "what_to_show": "BID_ASK",
        "n_daily": int(len(dd)), "n_close": int(len(cc)),
    }

    # --- CONTROL CHECK: SPY must come back near 0.1bp half-spread ---
    verdict = "unknown"
    spy = merged[merged.ticker == "SPY"]
    if not spy.empty:
        h = spy.get("close_half_spread_bp")
        h = float(h.iloc[0]) if h is not None and pd.notna(h.iloc[0]) \
            else float(spy["half_spread_bp_median"].iloc[0])
        meta["spy_half_spread_bp"] = h
        verdict = "PASS" if h <= 0.6 else "SUSPECT"
        meta["control_verdict"] = verdict
        print(f"\nCONTROL  SPY measured half-spread = {h:.3f}bp "
              f"(truth ~0.1bp)  ->  {verdict}")
        if verdict == "SUSPECT":
            print("  Measurement looks inflated. Do NOT feed this into the cost")
            print("  model without understanding why.")

    if not merged.empty:
        merged.to_csv(OUT / "ibkr_measured_spreads.csv", index=False)
    if daily_panels:
        pd.concat(daily_panels.values(), ignore_index=True).to_parquet(
            OUT / "ibkr_spread_panel.parquet", index=False)
    (OUT / "ibkr_measured_spreads_meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\nwrote {OUT/'ibkr_measured_spreads.csv'}  ({len(merged)} names)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
