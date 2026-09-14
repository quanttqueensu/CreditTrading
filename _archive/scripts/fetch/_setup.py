"""Engine-A shared data/loader helper. Import this from any scripts/calendar/*
module to get the frozen calendar machinery + the A0-refreshed frames without
re-plumbing paths.

    import sys; sys.path.insert(0, "scripts/calendar")
    from _setup import (
        load_futures_returns, load_etf, load_etf_excess, load_riskfree,
        load_cmt_recon, load_cmt_recon_wide, load_events,
        days_to_month_end, eom_window_flags, map_events_to_trading_days,
        daily_log_returns, car_matrix,
    )
    fut = load_futures_returns(["ZN", "ZF", "ZB"])   # roll-splice-safe log returns
    j   = days_to_month_end(fut.index)               # month-end countdown on ZN bars

Data provenance (A0, 2026-07-20):
  * futures_daily, events_v2  -> archive/calendar-premia-v2/data (FROZEN, read-only)
  * etf_daily, riskfree_daily -> data/calendar (archive + yfinance/treasury tail to today)
  * cmt_recon_returns         -> data/calendar (Swinkels CMT excess returns, 1990-> today)
Each loader prefers the data/calendar copy and falls back to the archived frame.
The roll-splice returns and j-countdown calendar come straight from the frozen
archive/calendar-premia-v2/src (never re-implemented here).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "archive" / "calendar-premia-v2"
CAL = REPO / "data" / "calendar"          # A0-refreshed frames
ADATA = ARCHIVE / "data"                  # frozen archived frames

# frozen calendar machinery lives under archive/calendar-premia-v2/src
if str(ARCHIVE) not in sys.path:
    sys.path.insert(0, str(ARCHIVE))
from src.data.calendar import (  # noqa: E402
    days_to_month_end, eom_window_flags, map_events_to_trading_days,
)
from src.analysis.returns import daily_log_returns, car_matrix  # noqa: E402

FUTURES_PARQUET = str(ADATA / "futures_daily.parquet")   # frozen roll-splice source


def _pick(name: str) -> Path:
    """Prefer the A0-refreshed data/calendar copy; fall back to the archive."""
    fresh, arch = CAL / name, ADATA / name
    return fresh if fresh.exists() else arch


# ---------------------------------------------------------------- futures
def load_futures_raw() -> pd.DataFrame:
    df = pd.read_parquet(FUTURES_PARQUET)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_futures_returns(instruments=("ZN", "ZF", "ZB")) -> pd.DataFrame:
    """Roll-splice-safe daily LOG returns, wide (index=date, cols=instruments)."""
    return daily_log_returns(FUTURES_PARQUET, list(instruments))


# ---------------------------------------------------------------- ETFs
def load_etf(prefer_fresh: bool = True) -> pd.DataFrame:
    """Long frame [date, ticker, ret_tr, close, source] (TLT/IEF/SHY total returns)."""
    p = _pick("etf_daily.parquet") if prefer_fresh else ADATA / "etf_daily.parquet"
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_etf_excess(tickers=("IEF", "TLT", "SHY")) -> pd.DataFrame:
    """Wide EXCESS total returns (total return minus the t-bill accrual over the
    same holding gap), index=date, one column per ticker."""
    etf = load_etf()
    ret = etf.pivot(index="date", columns="ticker", values="ret_tr")
    rf_cum = load_riskfree().cumsum()
    rf_win = rf_cum.reindex(ret.index).ffill().diff()
    ex = ret.sub(rf_win, axis=0)
    keep = [t for t in tickers if t in ex.columns]
    return ex[keep]


# ---------------------------------------------------------------- risk-free
def load_riskfree() -> pd.Series:
    """Per-weekday risk-free accrual, Series indexed by date (rf_daily)."""
    df = pd.read_parquet(_pick("riskfree_daily.parquet"))
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["rf_daily"].sort_index()


# ---------------------------------------------------------------- CMT recon
def load_cmt_recon() -> pd.DataFrame:
    """Long frame [date, tenor, ret_excess, mod_dur] — synthetic constant-maturity
    Treasury EXCESS returns (2y/5y/10y/20y/30y), 1990 -> today. Long-sample fuel."""
    df = pd.read_parquet(_pick("cmt_recon_returns.parquet"))
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_cmt_recon_wide(value: str = "ret_excess") -> pd.DataFrame:
    """CMT recon pivoted wide: index=date, columns=tenor."""
    df = load_cmt_recon()
    return df.pivot(index="date", columns="tenor", values=value)


# ---------------------------------------------------------------- events
def load_events(scheduled_only: bool = True, types=None) -> pd.DataFrame:
    """Event calendar [date, event_type, scheduled, source, notes]. CPI/NFP/FOMC,
    scheduled dates to 2026-12 (incl. the 2025 shutdown irregulars)."""
    df = pd.read_parquet(_pick("events_v2.parquet"))
    df["date"] = pd.to_datetime(df["date"])
    if scheduled_only:
        df = df[df["scheduled"]]
    if types is not None:
        df = df[df["event_type"].isin(list(types))]
    return df.sort_values("date").reset_index(drop=True)


def event_dates(event_type: str, scheduled_only: bool = True) -> pd.DatetimeIndex:
    ev = load_events(scheduled_only=scheduled_only, types=[event_type])
    return pd.DatetimeIndex(ev["date"].unique())


# ---------------------------------------------------------------- self-test
def _selftest() -> None:
    print(f"REPO      = {REPO}")
    print(f"futures   = {FUTURES_PARQUET}")
    print("frames refreshed at A0 come from data/calendar; frozen ones from archive.\n")

    fut = load_futures_returns(["ZN", "ZF", "ZB"])
    assert not fut.empty and list(fut.columns) == ["ZN", "ZF", "ZB"]
    print(f"futures returns : {fut.index.min().date()}..{fut.index.max().date()}  "
          f"N={len(fut)}  cols={list(fut.columns)}")

    etf = load_etf()
    assert not etf.empty and set(etf.ticker.unique()) >= {"TLT", "IEF", "SHY"}
    print(f"etf_daily       : {etf.date.min().date()}..{etf.date.max().date()}  "
          f"N={etf.date.nunique()}  tickers={sorted(etf.ticker.unique())}")

    ex = load_etf_excess()
    assert not ex.empty
    print(f"etf excess wide : {ex.index.min().date()}..{ex.index.max().date()}  "
          f"cols={list(ex.columns)}")

    rf = load_riskfree()
    assert not rf.empty
    print(f"riskfree_daily  : {rf.index.min().date()}..{rf.index.max().date()}  N={len(rf)}")

    cmt = load_cmt_recon()
    assert not cmt.empty and set(cmt.tenor.unique()) >= {"2y", "10y", "30y"}
    print(f"cmt_recon       : {cmt.date.min().date()}..{cmt.date.max().date()}  "
          f"N={cmt.date.nunique()}  tenors={sorted(cmt.tenor.unique())}")

    ev = load_events()
    assert not ev.empty and set(ev.event_type.unique()) >= {"CPI", "NFP", "FOMC"}
    print(f"events (sched)  : {ev.date.min().date()}..{ev.date.max().date()}  "
          f"N={len(ev)}  types={sorted(ev.event_type.unique())}")

    # --- j-countdown + EOM window: every full month's n=3 window has exactly 3 return days ---
    j = days_to_month_end(fut.index)
    flags = eom_window_flags(j, 3)
    per_month = flags.groupby(j.index.to_period("M")).sum()
    full = per_month.iloc[1:-1]                       # drop possibly-partial first/last month
    assert (full == 3).all(), f"EOM n=3 window not exactly 3 days in: {full[full != 3].to_dict()}"
    print(f"EOM n=3 window  : all {len(full)} full months on the ZN index have exactly 3 return days  OK")

    # --- roll-splice union sanity: patched returns never exceed raw magnitude ---
    zn_raw = np.log(load_futures_raw().query("instrument=='ZN' and roll=='wvol'")
                    .set_index("date")["settle"].sort_index()).diff()
    assert fut["ZN"].abs().max() <= zn_raw.abs().max() + 1e-12
    print("roll-splice     : patched |ZN| max <= raw |ZN| max  OK")

    # --- event mapping smoke: a known FOMC maps onto a futures bar ---
    m = map_events_to_trading_days(event_dates("FOMC"), fut.index)
    assert m.notna().sum() > 100
    print(f"event->bar map  : {m.notna().sum()} FOMC dates map onto futures bars  OK")

    print("\n_setup.py selftest OK — all frames non-empty and consistent.")


if __name__ == "__main__":
    _selftest()
