"""One session's closing-quote reading for the unit-trust termination rule (2026-11-20, a termination session T).

WHY: the rule buys at T's close, and no test so far could say what a late order pays against that close.
This reads public Yahoo quotes saved by hand-run fetches at 15:52, 15:57, 15:59:30 and 16:12 New York, and
the daily bars re-read at 17:15 once the official closes had settled (the 16:12 "close" was the last trade,
not the closing print, for 21 of 29 funds). It is a READING of one session, not a test.

Known weakness, measured below rather than assumed away: Yahoo's bid and ask carry no timestamp and the last
trade lies outside them for a third of the funds, so the quote may be delayed or single-venue. Every figure
that compares the close with a quote inherits that.

Inputs live outside the repository (~/quantt_research/uit_cef_flows/close_reading_2026-11-20/). No account
data, no keys, no orders. Missing inputs raise.
"""
import json
from pathlib import Path

import pandas as pd

SRC = Path.home() / "quantt_research/uit_cef_flows/close_reading_2026-11-20"
FUNDS = ("BTT DMB DSM EIM ETX EVN IIM IQI LEO MHD MHF MMD MMU MQY MUJ MYI NAD NBH NDMO NEA NMCO NMZ NUV "
         "NVG NXP NZF OIA VFL VGM VKQ").split()
BENCH = "PCEF"
READS = ["1552", "1557", "1559", "1612"]


def stats(x: pd.Series) -> dict:
    return {"mean": round(float(x.mean()), 1), "median": round(float(x.median()), 1),
            "min": round(float(x.min()), 1), "max": round(float(x.max()), 1)}


def main() -> dict:
    q = {k: pd.read_csv(SRC / f"yahoo_{k}.csv").set_index("symbol") for k in READS}
    early = pd.read_csv(SRC / "yahoo_daily_1620.csv").set_index("symbol")
    d = pd.read_csv(SRC / "yahoo_daily_1715.csv").set_index("symbol")
    no_data = [s for s in FUNDS if s not in d.index or pd.isna(d.close.get(s))]
    funds = [s for s in FUNDS if s not in no_data]
    if (d.date[funds + [BENCH]] != "2026-11-20").any():
        raise ValueError("a daily bar is not dated 2026-11-20")
    c = d.close[funds]
    if (abs(c * 100 - (c * 100).round()) > 1e-4).any():
        raise ValueError("a settled close is not a whole-cent price")
    out = {"session": "2026-11-20", "source": "Yahoo public quotes; no timestamp on bid/ask",
           "funds_listed": len(FUNDS), "funds_with_data": len(funds), "no_data": no_data,
           "closes_changed_1620_to_1715": int((abs(early.close[funds] - c) > 1e-6).sum()), "reads": {}}
    for k in READS:
        r = q[k].loc[funds]
        if ((r.bid <= 0) | (r.ask <= 0) | r.bid.isna() | r.ask.isna()).any():
            raise ValueError(f"reading {k}: a fund has no two-sided quote")
        mid = (r.bid + r.ask) / 2
        inside = (r.regularMarketPrice >= r.bid - 1e-9) & (r.regularMarketPrice <= r.ask + 1e-9)
        out["reads"][k] = {
            "spread_bp": stats((r.ask - r.bid) / mid * 1e4),
            "spread_cents": {str(int(a)): int(b) for a, b in
                             ((r.ask - r.bid) * 100).round().value_counts().sort_index().items()},
            "last_trade_inside_quote": int(inside.sum()),
            "ask_size_median": float(r.askSize.median()), "ask_size_min": float(r.askSize.min()),
            # close against the quote: positive = the close printed above
            "close_minus_mid_bp": stats((c - mid) / mid * 1e4),
            "ask_minus_close_bp": stats((r.ask - c) / c * 1e4),   # what lifting the ask costs against the close
            "close_at_or_below_ask": int((c <= r.ask + 1e-9).sum()),
            "close_below_bid": int((c < r.bid - 1e-9).sum()), "close_above_ask": int((c > r.ask + 1e-9).sum()),
            "last_minus_close_bp": stats((r.regularMarketPrice - c) / c * 1e4),
            "abs_last_minus_close_bp_mean": round(float(((r.regularMarketPrice - c) / c * 1e4).abs().mean()), 1),
        }
    dv = c * d.volume[funds]
    out["dollar_volume"] = {"min": round(float(dv.min())), "median": round(float(dv.median())),
                            "max": round(float(dv.max())), "thinnest": dv.nsmallest(3).round().to_dict(),
                            "order_5000_pct_of_thinnest": round(5000 / float(dv.min()) * 100, 2),
                            "order_1000_pct_of_thinnest": round(1000 / float(dv.min()) * 100, 2)}
    # T's own return, price only; the quote endpoint's previous close is used because the chart's is not
    # adjusted for the two funds that went ex-distribution today (they differ on MHF and MMU)
    prev = q["1612"].regularMarketPreviousClose
    ret = (c / prev[funds] - 1) * 1e4
    bench = (d.close[BENCH] / prev[BENCH] - 1) * 1e4
    out["t_day_return_bp"] = {"funds": stats(ret), "share_down": round(float((ret < 0).mean()), 2),
                              "pcef": round(float(bench), 1)}
    return out


if __name__ == "__main__":
    res = main()
    Path(__file__).with_name("close_reading_2026-11-20.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
