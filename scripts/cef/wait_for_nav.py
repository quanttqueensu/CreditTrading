"""Block until TODAY's NAV is published for every deployed CEF, or give up.

    python3 scripts/cef/wait_for_nav.py --asof 2026-09-08 [--deadline 21:30]
                                        [--interval 600] [--book <book.json>]

Exit 0  every deployed name has today's NAV on yfinance (the panel's source)
        and today's close -> run fetch_daily and trade on today's pair.
Exit 3  deadline reached; yfinance is still missing some NAVs but CEFConnect
        has a dated row for today on every one of them -> fetch_daily can fill
        those from CEFConnect (--nav-fallback cefconnect), named in the log.
Exit 2  deadline reached and neither source is complete -> stand down. A
        decision without today's NAV is a decision on yesterday's discounts,
        and that is precisely the thing this script exists to stop.

WHY
---
The sleeve's signal is price minus NAV, inner-joined on date. Until
2026-09-08 the session fired at 17:15 ET, before sponsors had published the
day's NAV, so the panel's last complete pair was YESTERDAY's and the order
that rested overnight was built on it. The backtest decides on the pair at t
and fills at t+1; live was deciding on the pair at t-1 and filling at t+1 --
one extra day of decay on an IC measured at a 2-day horizon, and the cause of
the "dust" orders: the band judged held weights on yesterday's prices while
the executor sized shares on today's, so names it had ruled HOLD still moved
by a few shares each.

An MOC order rests until the next auction whatever time it is placed, so
waiting for the NAV costs nothing in execution. It only costs the wait.

MEASURED 2026-09-08 (first night): yfinance had 0/17 at 21:18 and 17/17 at
22:43, all names at once; CEFConnect had 0/17 at 22:43. So the evening
decision waits until ~22:45, and the morning decision (docs/prompts P8.1)
is the durable answer. Each poll iteration can itself take an hour when
yfinance throttles (21:18 -> 22:43 was ONE iteration), which is why the
deadline is checked after the completeness check and why the poll should
stay light.

The poll is deliberately light: one NAV request per deployed name per
iteration, prices only once the NAVs are in, and one CEFConnect request per
name so the log records WHEN each source publishes. That record is what
decides whether CEFConnect becomes the same-day source or stays a fallback.
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

CC_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def deployed(book_path: Path) -> list[str]:
    from ops.preflight import deployed_tickers
    return sorted({t for insts in deployed_tickers(book_path).values() for t in insts})


def yf_has(symbol: str, asof: pd.Timestamp, need_volume: bool) -> bool:
    """True if yfinance serves a bar dated `asof` for `symbol`."""
    import yfinance as yf
    try:
        h = yf.Ticker(symbol).history(period="5d", auto_adjust=False)
    except Exception:
        return False
    if not len(h):
        return False
    d = pd.to_datetime(h.index).tz_localize(None).normalize()
    row = h[d == asof]
    if not len(row):
        return False
    if need_volume and float(row["Volume"].iloc[-1] or 0) <= 0:
        return False
    return bool(pd.notna(row["Close"].iloc[-1]))


def cefconnect_nav(ticker: str, asof: pd.Timestamp):
    """CEFConnect's dated NAV for `asof`, or None. One request, daily rows."""
    import requests
    try:
        r = requests.get(f"https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/1Y",
                         headers=CC_HEADERS, timeout=20)
        rows = r.json()["Data"]["PriceHistory"]
    except Exception:
        return None
    for x in reversed(rows):
        if pd.Timestamp(x["DataDate"]).normalize() == asof:
            return float(x["NAVData"])
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", default=f"{datetime.now():%Y-%m-%d}")
    ap.add_argument("--deadline", default="21:30", help="local HH:MM to give up")
    ap.add_argument("--interval", type=int, default=600, help="seconds between polls")
    ap.add_argument("--book", default=str(REPO / "ops/books/cef_discount_book.json"))
    ap.add_argument("--once", action="store_true", help="one poll, no waiting")
    ap.add_argument("--no-cefconnect", action="store_true",
                    help="skip the CEFConnect probe (evening: it had 0/17 at "
                         "22:43 on 2026-09-08 while yfinance had 17/17)")
    ap.add_argument("--cc-grace", type=int, default=30,
                    help="minutes to keep waiting for yfinance once CEFConnect "
                         "already has every name; then use CEFConnect")
    a = ap.parse_args(argv)

    asof = pd.Timestamp(a.asof).normalize()
    hh, mm = (int(x) for x in a.deadline.split(":"))
    deadline = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    names = deployed(Path(a.book))
    print(f"waiting for NAV dated {asof.date()} on {len(names)} deployed names; "
          f"deadline {deadline:%H:%M}, poll every {a.interval}s")

    seen_yf, seen_cc = {}, {}      # ticker -> first time seen, for the record
    cc_complete_at = None
    while True:
        now = datetime.now()
        yf_nav = {t for t in names if yf_has(f"X{t}X", asof, need_volume=False)}
        cc_nav = (set() if a.no_cefconnect
                  else {t for t in names if cefconnect_nav(t, asof) is not None})
        for t in yf_nav:
            seen_yf.setdefault(t, f"{now:%H:%M}")
        for t in cc_nav:
            seen_cc.setdefault(t, f"{now:%H:%M}")
        yf_px = ({t for t in names if yf_has(t, asof, need_volume=True)}
                 if len(yf_nav) == len(names) or len(cc_nav) == len(names)
                 else set())
        miss_yf = sorted(set(names) - yf_nav)
        miss_cc = sorted(set(names) - cc_nav)
        print(f"[{now:%H:%M:%S}] yfinance NAV {len(yf_nav)}/{len(names)}  "
              f"cefconnect NAV {len(cc_nav)}/{len(names)}  "
              f"close {len(yf_px)}/{len(names)}"
              + (f"  missing on yfinance: {' '.join(miss_yf)}" if miss_yf else "")
              + (f"  missing on cefconnect: {' '.join(miss_cc)}" if miss_cc else ""),
              flush=True)

        if len(yf_nav) == len(names) and len(yf_px) == len(names):
            print(f"today's pair is complete on yfinance at {now:%H:%M} "
                  f"(first NAV seen {min(seen_yf.values())}, last {max(seen_yf.values())})")
            return 0

        # CEFConnect complete but yfinance not: give yfinance a bounded grace
        # rather than the whole evening. The pair is the same either way; the
        # only thing at stake is which source wrote today's row.
        if len(cc_nav) == len(names) and cc_complete_at is None:
            cc_complete_at = now
        grace_up = (cc_complete_at is not None
                    and (now - cc_complete_at).total_seconds() >= 60 * a.cc_grace)

        if now >= deadline or a.once or grace_up:
            if not yf_px:          # not probed above; the verdict must name real gaps
                yf_px = {t for t in names if yf_has(t, asof, need_volume=True)}
            miss_px = sorted(set(names) - yf_px)
            if len(cc_nav) == len(names) and not miss_px:
                print(f"{now:%H:%M}: yfinance still lacks {' '.join(miss_yf)}; "
                      f"CEFConnect has every name dated {asof.date()} (complete "
                      f"since {cc_complete_at:%H:%M}) -> fill those from CEFConnect")
                return 3
            if grace_up and now < deadline:
                # CEFConnect is whole but a CLOSE is missing; that is a yfinance
                # price gap, keep polling until the deadline.
                cc_complete_at = now
                time.sleep(max(30, min(a.interval, int((deadline - now).total_seconds()) + 1)))
                continue
            print(f"DEADLINE {deadline:%H:%M}: today's pair is NOT complete -- "
                  f"NAV missing on yfinance: {' '.join(miss_yf) or 'none'}; "
                  f"on cefconnect: {' '.join(miss_cc) or 'none'}; "
                  f"close missing: {' '.join(miss_px) or 'none'}")
            return 2

        time.sleep(max(30, min(a.interval, int((deadline - now).total_seconds()) + 1)))


if __name__ == "__main__":
    sys.exit(main())
