"""Daily borrow-cost panel for the credit CEF universe.

WHY THIS EXISTS
---------------
Nothing in this repo has ever charged the short leg a borrow cost. `scripts/cef/
validate.py:93` computes cost as half-spread only, and the live ledger's
`FinancingModel` applies a flat +50bp calibrated -- by its own docstring -- for
"liquid Treasury/IG ETFs (general collateral bucket)". Credit CEFs are not
general collateral. Every Sharpe this programme has quoted is before the cost of
financing the short leg, and PLAN.md 3.3 makes that the gate on the entire
leverage decision.

So: measure it, daily, and keep the series.

SOURCES (two, deliberately)
---------------------------
1. IBKR's public short-availability file, https://www.interactivebrokers.com/
   shortstock/usa.txt -- pipe-delimited, refreshed through the day, and the ONLY
   source that carries an actual FEERATE. No authentication.
   (The historical ftp://shortstock.interactivebrokers.com host is retired and
   now NXDOMAINs; this is the live mirror.)
2. The TWS API, generic tick 236 -> `shortableShares`, on the account we
   actually trade. This carries availability but NOT a rate, so it cannot
   replace source 1 -- it cross-checks it.

   The paper account has no NYSE top-of-book subscription (error 10089), so the
   request MUST run under `reqMarketDataType(3)` (delayed). Delayed returns tick
   89 fine. Do not "fix" this by removing the call.

The two sources are snapshots taken at different times and will not agree
exactly; they are kept as separate columns rather than reconciled, because a
disagreement is information about how fast availability moves.

WHAT IT WRITES
--------------
`data/cef/cef_borrow.csv`, append-only, keyed (date, ticker) -- the same shape
as the price and NAV panels. Re-running on a date replaces that date's rows, so
it is safe to run repeatedly.

Usage:
    python3 scripts/cef/fetch_borrow_rates.py              # file only
    python3 scripts/cef/fetch_borrow_rates.py --api        # + TWS cross-check
    python3 scripts/cef/fetch_borrow_rates.py --positions  # + drag on the live book
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SPEC = REPO / "ops" / "specs" / "cef_discount.frozen.json"
OUT = REPO / "data" / "cef" / "cef_borrow.csv"
POSITIONS = REPO / "ops/books/cef_live/_ibkr_shadow/cef_discount/positions.csv"

SHORTSTOCK_URL = "https://www.interactivebrokers.com/shortstock/usa.txt"
# Columns as published: #SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|
SYM, REBATE, FEE, AVAIL = 0, 5, 6, 7

# A distinct client id. cef=45, phase0=17, benchmarks=46, capture_fills=id+50.
IB_CLIENT_ID = 77
IB_HOST, IB_PORT = "127.0.0.1", 4002


def universe() -> list[str]:
    return json.loads(SPEC.read_text())["frozen"]["universe"]


def _num(x):
    """AVAILABLE is '>10000000' or 'NA' for some names; FEERATE can be 'NA'."""
    try:
        return float(str(x).lstrip(">"))
    except (TypeError, ValueError):
        return None


def from_file(tickers: list[str], url: str = SHORTSTOCK_URL) -> pd.DataFrame:
    """The public file. Carries the fee rate, which the API does not."""
    with urllib.request.urlopen(url, timeout=60) as r:
        raw = r.read().decode("latin-1")

    lines = raw.splitlines()
    stamp = lines[0] if lines and lines[0].startswith("#BOF") else ""
    want = set(tickers)
    rows = []
    for ln in lines:
        if ln.startswith("#"):
            continue
        p = ln.split("|")
        if len(p) > AVAIL and p[SYM] in want:
            rows.append({
                "ticker": p[SYM],
                "fee_rate_pct": _num(p[FEE]),
                "rebate_rate_pct": _num(p[REBATE]),
                "available_shares": _num(p[AVAIL]),
            })
    df = pd.DataFrame(rows)
    df.attrs["stamp"] = stamp
    return df


def from_api_fee(tickers: list[str]) -> pd.DataFrame:
    """Fee and rebate rates from IBKR's historical-data service.

    `reqHistoricalData(whatToShow="FEE_RATE")` returns one daily bar per
    session whose close is the annual borrow fee as a decimal (verified
    2026-09-10: HYT 0.1056, PDI 0.0028 -- the same numbers the file carried
    on 09-04). REBATE_RATE is requested the same way but has timed out on
    every name tried; it is best-effort and None when absent. No market-data
    subscription is involved, so this works during a "competing live
    session" (error 10197) when tick 236 does not.

    Sequential, one name at a time, one retry: the first request after a
    connection warms up the service and can time out on its own.
    """
    # LANDMINE 8: ib_async first. ib_insync 0.9.86 hangs in its asyncio
    # handshake on Python 3.12+ and looks exactly like a dead broker.
    try:
        from ib_async import IB, Stock, util
    except ImportError:
        from ib_insync import IB, Stock, util

    util.logToConsole(50)
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, readonly=True, timeout=20)
    rows = []
    try:
        cts = ib.qualifyContracts(*[Stock(t, "SMART", "USD") for t in tickers])

        def last_close(c, what, tries=2):
            for _ in range(tries):
                try:
                    bars = ib.reqHistoricalData(
                        c, endDateTime="", durationStr="5 D",
                        barSizeSetting="1 day", whatToShow=what, useRTH=True,
                        formatDate=1, timeout=30)
                except Exception:
                    bars = []
                if bars:
                    return float(bars[-1].close), str(bars[-1].date)
            return None, None

        for c in cts:
            fee, fee_d = last_close(c, "FEE_RATE")
            reb, _ = last_close(c, "REBATE_RATE", tries=1)
            rows.append({"ticker": c.symbol,
                         "fee_rate_pct": None if fee is None else round(fee * 100, 4),
                         "rebate_rate_pct": None if reb is None else round(reb * 100, 4),
                         "available_shares": None,
                         "_fee_date": fee_d})
    finally:
        ib.disconnect()
    df = pd.DataFrame(rows)
    df.attrs["stamp"] = "IBKR API FEE_RATE bars"
    return df


def from_api(tickers: list[str]) -> pd.DataFrame:
    """TWS cross-check. Availability only -- there is no fee-rate tick."""
    # LANDMINE 8: ib_async first. ib_insync 0.9.86 hangs in its asyncio
    # handshake on Python 3.12+ and looks exactly like a dead broker.
    try:
        from ib_async import IB, Stock, util
    except ImportError:
        from ib_insync import IB, Stock, util

    util.logToConsole(50)          # 10089 warnings are expected and handled below
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, readonly=True, timeout=20)
    try:
        ib.reqMarketDataType(3)    # delayed; live requires a subscription we lack
        cts = ib.qualifyContracts(*[Stock(t, "SMART", "USD") for t in tickers])
        tks = [ib.reqMktData(c, "236", False, False) for c in cts]
        ib.sleep(15)               # tick 89 is slow to arrive on delayed data
        out = [{"ticker": c.symbol, "api_shortable_shares": t.shortableShares}
               for c, t in zip(cts, tks)]
        for c in cts:
            ib.cancelMktData(c)
    finally:
        ib.disconnect()
    return pd.DataFrame(out)


def live_shorts() -> pd.Series:
    """Current short market values from the shadow ledger, as positive numbers."""
    if not POSITIONS.exists():
        return pd.Series(dtype=float)
    p = pd.read_csv(POSITIONS)
    p = p[p["date"] == p["date"].max()]
    p = p[(p.ticker != "CASH") & p.market_value.notna()]
    s = p.set_index("ticker").market_value.astype(float)
    return -s[s < 0]


def append(df: pd.DataFrame, asof: str) -> None:
    df = df.assign(date=asof)
    cols = ["date", "ticker", "fee_rate_pct", "rebate_rate_pct",
            "available_shares", "api_shortable_shares"]
    df = df.reindex(columns=cols)
    if OUT.exists():
        prev = pd.read_csv(OUT)
        prev = prev[prev.date != asof]          # idempotent re-run
        df = pd.concat([prev, df], ignore_index=True)
    df.sort_values(["date", "ticker"]).to_csv(OUT, index=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    # NOT passed by the scheduler. The fee rate -- the number that actually
    # matters -- comes from the file, and the scheduled run happens inside a
    # live trading session; opening a second broker connection in the refresh
    # phase to obtain a nice-to-have cross-check is not worth the risk to the
    # trade phase. Run it by hand when the cross-check is wanted.
    ap.add_argument("--api", action="store_true", help="cross-check against TWS")
    ap.add_argument("--positions", action="store_true", help="drag on the live book")
    ap.add_argument("--asof", default=date.today().isoformat())
    a = ap.parse_args()

    u = universe()
    # The public file 404s since 2026-09-09 (www.interactivebrokers.com/shortstock/
    # usa.txt; the ftp hosts do not answer either). The fee -- the number that
    # matters -- now comes from the API's FEE_RATE bars; the file is tried first
    # and used if it ever comes back, because it also carries availability.
    try:
        df = from_file(u)
        print(f"IBKR shortstock file {df.attrs.get('stamp','')} -- {len(df)}/{len(u)} names")
    except Exception as e:
        print(f"IBKR shortstock file unavailable ({type(e).__name__}: {str(e)[:80]}); "
              f"fees from the API instead")
        df = pd.DataFrame(columns=["ticker", "fee_rate_pct", "rebate_rate_pct",
                                   "available_shares"])
    if df.empty or df["fee_rate_pct"].isna().all():
        api = from_api_fee(u)
        got = api["fee_rate_pct"].notna().sum()
        print(f"IBKR API FEE_RATE -- {got}/{len(u)} names"
              + (f" (fee dated {api['_fee_date'].dropna().max()})" if got else ""))
        df = api.drop(columns=["_fee_date"])
        if got == 0:
            print("  no fee rate from either source; not writing a row")
            return 1

    missing = sorted(set(u) - set(df.ticker))
    if missing:
        print(f"  NOT LISTED (treat as unborrowable, not as free): {', '.join(missing)}")

    if a.api:
        try:
            df = df.merge(from_api(u), on="ticker", how="outer")
        except Exception as e:                  # never let the cross-check block the fee
            print(f"  API cross-check unavailable ({type(e).__name__}: {e})")

    df = df.sort_values("fee_rate_pct", ascending=False)
    has_api = "api_shortable_shares" in df

    print(f"\n{'SYM':6}{'fee %':>9}{'rebate %':>10}{'avail':>12}" + (f"{'API avail':>12}" if has_api else ""))
    print("-" * (37 + 12 * has_api))
    def fmt(v, spec):
        # rebate and availability are None when only the API answered
        return "--" if v is None or v != v else format(v, spec)

    for r in df.itertuples():
        line = (f"{r.ticker:6}{fmt(r.fee_rate_pct, '.2f'):>9}"
                f"{fmt(r.rebate_rate_pct, '.2f'):>10}"
                f"{fmt(r.available_shares, ',.0f'):>12}")
        if has_api:
            v = getattr(r, "api_shortable_shares", None)
            line += f"{'--' if v is None or v != v else format(v, ',.0f'):>12}"
        print(line)

    if a.positions:
        shorts = live_shorts()
        if shorts.empty:
            print("\nno short positions in the shadow ledger")
        else:
            fee = df.set_index("ticker").fee_rate_pct
            avail = df.set_index("ticker").available_shares
            drag = shorts * fee.reindex(shorts.index) / 100.0
            print(f"\nlive short book -- annual borrow drag")
            print(f"{'SYM':6}{'short $':>12}{'fee %':>8}{'drag $/yr':>12}  flag")
            print("-" * 52)
            for t in drag.sort_values(ascending=False).index:
                px = pd.read_csv(POSITIONS)
                px = px[(px.date == px.date.max()) & (px.ticker == t)]
                sh = abs(float(px.shares.iloc[0])) if len(px) else float("nan")
                short_avail = avail.get(t)
                flag = "SHORT > AVAILABLE" if short_avail and sh > short_avail else ""
                print(f"{t:6}{shorts[t]:>12,.0f}{fee[t]:>8.2f}{drag[t]:>12,.0f}  {flag}")
            print("-" * 52)
            tot, gross_short = drag.sum(), shorts.sum()
            print(f"{'TOT':6}{gross_short:>12,.0f}{100*tot/gross_short:>8.2f}{tot:>12,.0f}")
            print(f"\nweighted-average borrow on the short leg: {100*tot/gross_short:.2f}%")

    append(df, a.asof)
    print(f"\nwrote {OUT.relative_to(REPO)} ({a.asof})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
