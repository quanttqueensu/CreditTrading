"""What did IBKR PAPER do with our MOC orders? The IBKR-era fills against the close.

    python3 scripts/ops/ibkr_paper_moc_fills.py

WHY (`results/ops/IBKR_SECOND_BROKER_2026-10-19.md` §2.6). IBKR's paper-trading
guide says fills are "simulated from the top of the book" and says nothing about
MOC [V, ibkrguides, 2026-10-19]. Alpaca paper turned out not to run the auction
either (`docs/RUNNER.md`, "Paper execution"), and the book had to change its paper
order type. Before a second broker's paper account is scored, what its simulator
does with an MOC order should be read from the record we already have, not
assumed. The CEF book sent MOC orders to an IBKR paper account on four sessions
between 2026-09-01 and 2026-09-15; every execution IBKR reported was captured to
`broker_fills.csv`, which survives at git tag `pre-clean-slate`.

WHAT IT READS. `git show pre-clean-slate:<FILLS>` (no broker, no network), and the
local price panel `data/cef/cef_prices.parquet` (yfinance, `auto_adjust=False`, so
`close` is the unadjusted consolidated close). The panel close is used as the
official close: for NYSE-listed funds the consolidated close is normally the
closing-auction print, but these four dates were NOT cross-checked against
NYSE's own print here, so the "at the close" count is labelled against the panel.
2026-07-31 is excluded: those were overnight market orders (07:27 ET), not MOC.

WHAT IT PRINTS. Per fill: the execution time IBKR stamped (ET), the fill price,
the panel close, the signed difference in bp (positive = worse for us: a buy
above the close or a sell below it) and the commission per share. A fill with no
panel close is reported and left out of the statistics, never filled in.

The output is about IBKR's simulator and our code's record of it, not about the
market: paper fills prove nothing about real auction cost (`docs/SYSTEM.md` §4.3).
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))
TAG = "pre-clean-slate"
FILLS = "_archive/prod_state_2026-09-28/ops/books/cef_live/_ibkr_shadow/cef_discount/broker_fills.csv"
PANEL = REPO / "data" / "cef" / "cef_prices.parquet"
ORDER_MAP = "_archive/prod_state_2026-09-28/ops/books/cef_live/_ibkr_shadow/_order_map.csv"
FIRST_MOC_SESSION = "2026-09-01"     # 2026-07-31 was overnight market orders (CLAUDE.md rule 3)


def _show(path: str) -> pd.DataFrame:
    raw = subprocess.run(["git", "-C", str(REPO), "show", f"{TAG}:{path}"],
                         check=True, capture_output=True, text=True).stdout
    return pd.read_csv(io.StringIO(raw))


def load_fills() -> pd.DataFrame:
    f = _show(FILLS)
    for c in ("fill_date", "instrument", "side", "qty", "price", "note"):
        if c not in f.columns:
            raise ValueError(f"{TAG}:{FILLS} lacks column {c!r}")
    t = f.note.str.extract(r"time=([0-9\-: ]+\+00:00)")[0]
    c = f.note.str.extract(r"commission=([0-9.eE\-]+)")[0]
    if t.isna().any():
        raise ValueError(f"{int(t.isna().sum())} fill(s) carry no execution time in their note")
    f["exec_et"] = pd.to_datetime(t, utc=True).dt.tz_convert("America/New_York")
    f["commission"] = pd.to_numeric(c, errors="raise")
    return f


def score(f: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    m = f[f.fill_date >= FIRST_MOC_SESSION].merge(
        px[["date", "ticker", "close"]], left_on=["fill_date", "instrument"],
        right_on=["date", "ticker"], how="left")
    sign = m.side.map({"BUY": 1, "SELL": -1})
    if sign.isna().any():
        raise ValueError(f"unknown side(s) {sorted(m.side[sign.isna()].unique())}")
    m["vs_close_bp"] = sign * 1e4 * (m.price - m.close) / m.close
    m["at_close"] = (m.price - m.close).abs() < 0.005
    m["comm_per_share"] = m.commission / m.qty
    return m


def auction_for(sent_et: pd.Timestamp) -> str:
    """The closing auction an MOC sent at `sent_et` joins: that day's if it is a
    trading day and before the 15:50 ET NYSE cutoff, else the next trading day's
    (2026-09-07 was Labor Day: a Friday-evening set joined Tuesday's auction)."""
    from ops.schedule.nyse_calendar import is_trading_day, next_trading_day
    day = sent_et.date()
    if is_trading_day(day) and (sent_et.hour * 60 + sent_et.minute) < 15 * 60 + 50:
        return str(day)
    return str(next_trading_day(day))


def fill_rate(f: pd.DataFrame) -> pd.DataFrame:
    """Per auction in the order map: orders, and how many the captured executions
    filled in full, in part or not at all. 'Not at all' can mean unfilled,
    cancelled, or filled and never captured (`ib.fills()` forgets at IBKR's daily
    restart; the capture step was separate): the record cannot tell them apart."""
    o = _show(ORDER_MAP)
    for c in ("recorded_utc", "instrument", "action", "qty"):
        if c not in o.columns:
            raise ValueError(f"{TAG}:{ORDER_MAP} lacks column {c!r}")
    o["sent_et"] = pd.to_datetime(o.recorded_utc, utc=True).dt.tz_convert("America/New_York")
    o["auction"] = o.sent_et.apply(auction_for)
    got = f.groupby(["fill_date", "instrument", "side"]).qty.sum().rename("filled").reset_index()
    m = o.merge(got, left_on=["auction", "instrument", "action"],
                right_on=["fill_date", "instrument", "side"], how="left")
    m["filled"] = m.filled.fillna(0.0)   # no captured execution for that order: counted as none, and labelled so
    return m.groupby("auction").apply(lambda x: pd.Series({
        "orders": len(x), "first_sent_et": str(x.sent_et.min())[:16],
        "full": int((x.filled >= x.qty).sum()),
        "partial": int(((x.filled > 0) & (x.filled < x.qty)).sum()),
        "none_captured": int((x.filled == 0).sum())}), include_groups=False)


def main() -> int:
    px = pd.read_parquet(PANEL, columns=["date", "ticker", "close"])
    px["date"] = pd.to_datetime(px.date).dt.strftime("%Y-%m-%d")
    m = score(load_fills(), px)
    print(f"panel {PANEL.relative_to(REPO)}: last date {px.date.max()}")
    with pd.option_context("display.width", 200):
        print(m[["fill_date", "instrument", "side", "qty", "price", "close", "vs_close_bp",
                 "comm_per_share", "exec_et"]].to_string(index=False))
    ok = m[m.close.notna()]
    miss = m[m.close.isna()]
    print(f"\nfills on MOC sessions: {len(m)}; with a panel close: {len(ok)}; "
          f"without (left out): {len(miss)} {list(zip(miss.fill_date, miss.instrument))}")
    tod = m.exec_et.dt.time          # time of day, across sessions (a max timestamp is not a max time)
    print(f"execution times of day (ET): {min(tod)} .. {max(tod)}")
    print(f"at the panel close to the half-cent: {int(ok.at_close.sum())} of {len(ok)}")
    print(f"signed vs close, bp (+ = worse): median {ok.vs_close_bp.median():.1f}, "
          f"mean {ok.vs_close_bp.mean():.1f}, median |.| {ok.vs_close_bp.abs().median():.1f}, "
          f"max |.| {ok.vs_close_bp.abs().max():.1f}")
    by = ok.groupby("fill_date").agg(n=("price", "size"), at_close=("at_close", "sum"),
                                     median_bp=("vs_close_bp", "median"))
    print(by.to_string())
    print(f"commission per share: median {m.comm_per_share.median():.6f} "
          f"(buys {m[m.side == 'BUY'].comm_per_share.median():.6f}, "
          f"sells {m[m.side == 'SELL'].comm_per_share.median():.6f}); min order "
          f"{m.commission.min():.4f}")
    print("\nfill rate by auction (orders from the order map; executions as captured):")
    print(fill_rate(load_fills()).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
