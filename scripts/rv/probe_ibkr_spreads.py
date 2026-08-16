"""Probe live IBKR quotes for the credit RV universe.

Records bid/ask/last plus derived half-spread in bp for every tradeable name, and
stamps whether the probe ran inside regular trading hours.  OUTSIDE RTH the book
is thin and the spread is an UPPER BOUND, not the cost we would actually pay -
the output carries that flag so downstream code never mistakes one for the other.

Usage:  python3 scripts/rv/probe_ibkr_spreads.py [--client-id 31]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "credit_rv"
OUT.mkdir(parents=True, exist_ok=True)

TICKERS = [
    "HYG", "JNK", "USHY", "SPHY", "SHYG", "SJNK", "HYGH",
    "FALN", "ANGL",
    "LQD", "VCSH", "VCIT", "VCLT", "IGSB", "LQDH",
    "BKLN", "SRLN", "JAAA", "JBBB",
    "EMB", "PFF", "CWB",
    "SHY", "IEI", "IEF", "TLT", "GOVT", "BIL", "SPY", "AGG",
]


def in_rth(ts: datetime) -> bool:
    et = ts.astimezone(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return False
    return dtime(9, 30) <= et.time() <= dtime(16, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", type=int, default=31)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    args = ap.parse_args()

    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("FATAL: ib_insync not importable")
        return 2

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=20)
    except Exception as exc:
        print(f"FATAL: connect failed: {type(exc).__name__}: {exc}")
        return 2

    now = datetime.now(ZoneInfo("America/New_York"))
    rth = in_rth(now)
    print(f"connected. {now:%Y-%m-%d %H:%M:%S %Z}  RTH={rth}")
    if not rth:
        print("  NOTE: outside RTH -> spreads below are UPPER BOUNDS, re-probe before funding\n")

    # delayed data is fine for a spread probe and needs no subscription
    ib.reqMarketDataType(3)

    rows = []
    for t in TICKERS:
        try:
            c = Stock(t, "SMART", "USD")
            ib.qualifyContracts(c)
            tk = ib.reqMktData(c, "", False, False)
            ib.sleep(2.0)
            bid, ask, last = tk.bid, tk.ask, tk.last
            mid = (bid + ask) / 2 if (bid and ask and bid > 0 and ask > 0) else None
            half_bp = ((ask - bid) / 2 / mid * 1e4) if mid else None
            rows.append({
                "ticker": t, "bid": bid, "ask": ask, "last": last, "mid": mid,
                "half_spread_bp": half_bp,
            })
            hs = f"{half_bp:8.2f}" if half_bp is not None else "     n/a"
            print(f"  {t:5s} bid={str(bid):>9s} ask={str(ask):>9s} half_bp={hs}")
            ib.cancelMktData(c)
        except Exception as exc:
            print(f"  {t:5s} ERROR {type(exc).__name__}: {exc}")
            rows.append({"ticker": t, "bid": None, "ask": None, "last": None,
                         "mid": None, "half_spread_bp": None})

    ib.disconnect()

    df = pd.DataFrame(rows)
    df["probe_ts"] = now.isoformat()
    df["rth"] = rth
    df["is_upper_bound"] = not rth
    df.to_csv(OUT / "ibkr_spread_probe.csv", index=False)

    ok = df["half_spread_bp"].notna().sum()
    print(f"\n{ok}/{len(df)} quoted -> {OUT/'ibkr_spread_probe.csv'}")
    if ok:
        print(df.dropna(subset=["half_spread_bp"])
                .sort_values("half_spread_bp")[["ticker", "half_spread_bp"]]
                .to_string(index=False))
    (OUT / "ibkr_spread_probe_meta.json").write_text(json.dumps(
        {"probe_ts": now.isoformat(), "rth": rth, "quoted": int(ok),
         "n": len(df), "market_data_type": "delayed(3)"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
