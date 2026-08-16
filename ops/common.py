"""Shared plumbing for the ops/ paper-trading simulator.

Nothing clever lives here. Paths, the frozen-spec loader, and the local price
store that daily_run.py appends to and everything else reads.

The price store is a plain CSV so a human can open it. One row per
(date, ticker). Prices are split-adjusted closes; distributions (dividends and
capital gains) are carried in their own column so the ledger can credit them as
cash the way a real account receives them, instead of hiding them inside an
adjusted price.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

OPS_DIR = Path(__file__).resolve().parent
REPO_ROOT = OPS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from src.backtest import engine  # noqa: E402

SPEC_PATH = OPS_DIR / "spec" / "frozen_spec.json"
PANEL_PATH = REPO_ROOT / "data" / "etf_daily.parquet"
DEFAULT_STATE_DIR = OPS_DIR / "state"
DEFAULT_REPORT_DIR = OPS_DIR / "reports"

# `high`/`low` added 2026-07-30 (ADDITIVE widen, credit_rv sleeve). They carry the
# session range so a sleeve can build the bounce-free mid (H+L)/2 that Phase 0
# proved is the only signal price not contaminated by bid-ask bounce. Rows written
# before this date have them as NaN; every existing consumer keys on
# close/dividend/volume and is unaffected.
PRICE_COLUMNS = ["date", "ticker", "close", "dividend", "volume",
                 "high", "low", "source", "fetched_at"]

# Impact sizing uses the same trailing window and fallback as the backtest
# engine, so the sim and the backtest price a trade the same way.
IMPACT_VOL_WINDOW = engine.IMPACT_VOL_WINDOW
IMPACT_VOL_FALLBACK_BP = engine.IMPACT_VOL_FALLBACK_BP
TRADING_DAYS = engine.TRADING_DAYS


# ---------------------------------------------------------------------------
# Spec and costs
# ---------------------------------------------------------------------------

# Allocation types the harness understands. static_weights is the base credit
# book (this ops/ path); the other four are the deploy sleeves, validated by
# src/deploy/registry and run under src/deploy/run_book.py's orchestrator.
ALLOWED_ALLOC_TYPES = {"static_weights", "eom_duration", "fomc_event",
                       "short_vol_straddle", "duration_hedged_overlay"}


def load_spec(path=SPEC_PATH):
    """Load the frozen portfolio spec. This is the ONLY place target weights
    come from — no ops/ module invents an allocation.

    The ``static_weights`` path below is byte-for-byte the original code (same
    checks, same error strings), so the smoke test and backtest tests are
    unaffected. Any other allowed type is structurally validated by
    ``src.deploy.registry`` (lazy import: the base credit book never needs
    src/deploy) — that path does not touch weights/book_usd, so it never
    KeyErrors on a sleeve spec."""
    import json
    with open(path) as f:
        spec = json.load(f)
    alloc = spec["allocation"]
    t = alloc["type"]
    if t not in ALLOWED_ALLOC_TYPES:
        raise ValueError(
            f"unsupported allocation type {t!r}. Only "
            "'static_weights' is implemented; add the new rule to "
            "target_weights() in daily_run.py, do not special-case it here.")
    if t == "static_weights":
        w = alloc["weights"]
        total = sum(w.values())
        if total > 1.0 + 1e-9:
            raise ValueError(
                f"frozen spec weights sum to {total:.4f} > 1.0. This simulator "
                "does not borrow; a levered book needs the financing leg wired in "
                "first (config/costs.yaml financing_spread_bp).")
        return spec
    from src.deploy import registry           # lazy: base credit book never needs src/deploy
    registry.validate_spec(spec)              # per-type structural validation
    return spec


def load_costs():
    """Trading costs, from config/costs.yaml via the audited loader."""
    return engine.load_costs()


def spec_tickers(spec):
    tickers = sorted(spec["allocation"]["weights"])
    rf = spec.get("risk_free_ticker")
    if rf and rf not in tickers:
        tickers.append(rf)
    return tickers


# ---------------------------------------------------------------------------
# Price store
# ---------------------------------------------------------------------------

def price_store_path(state_dir):
    return Path(state_dir) / "prices.csv"


def read_prices(state_dir):
    """The local price store as a tidy DataFrame (empty frame if absent)."""
    path = price_store_path(state_dir)
    if not path.exists():
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def write_prices(state_dir, df):
    path = price_store_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.sort_values(["ticker", "date"])[PRICE_COLUMNS]
    out.to_csv(path, index=False, date_format="%Y-%m-%d")


def append_prices(state_dir, new, refetch=False, verbose=True):
    """Merge freshly-pulled bars into the store, idempotently.

    Existing rows WIN by default. A vendor that quietly restates a close it
    already published is exactly the kind of thing that should be noticed, not
    absorbed, so disagreements are printed and the old value is kept unless
    ``refetch=True``.

    Returns (merged_frame, n_added, n_conflicts).
    """
    old = read_prices(state_dir)
    if new.empty:
        return old, 0, 0
    new = new.copy()
    new["date"] = pd.to_datetime(new["date"])

    if old.empty:
        merged, n_conflicts = new, 0
    else:
        key = ["date", "ticker"]
        both = old.merge(new, on=key, how="inner", suffixes=("_old", "_new"))
        conflict = both[
            (both["close_old"] - both["close_new"]).abs() > 1e-6]
        n_conflicts = len(conflict)
        if n_conflicts and verbose:
            print(f"[prices] WARNING: {n_conflicts} already-stored bars came "
                  f"back with a DIFFERENT close this run "
                  f"({'overwriting, --refetch was passed' if refetch else 'keeping the stored value'}):")
            for _, r in conflict.head(5).iterrows():
                print(f"[prices]   {r['date'].date()} {r['ticker']}: "
                      f"stored {r['close_old']:.4f} -> vendor "
                      f"{r['close_new']:.4f}")
        if refetch:
            keep_old = old.merge(new[key], on=key, how="left", indicator=True)
            keep_old = keep_old[keep_old["_merge"] == "left_only"].drop(
                columns="_merge")
            merged = pd.concat([keep_old, new], ignore_index=True)
        else:
            add = new.merge(old[key], on=key, how="left", indicator=True)
            add = add[add["_merge"] == "left_only"].drop(columns="_merge")
            merged = pd.concat([old, add], ignore_index=True)

    merged = merged.drop_duplicates(subset=["date", "ticker"], keep="last")
    n_added = len(merged) - len(old)
    if n_added or (refetch and n_conflicts):
        write_prices(state_dir, merged)
    return read_prices(state_dir), n_added, n_conflicts


def fetch_local(tickers, start, end):
    """Bars from the audited panel data/etf_daily.parquet (replay / smoke test).

    The panel stores returns, not distributions, so the per-share distribution
    is backed out of the two return columns:
        ret_total = (P_t + D_t)/P_{t-1} - 1,  ret_px = P_t/P_{t-1} - 1
        => D_t = P_{t-1} * (ret_total - ret_px)
    which is exact on this panel by construction.
    """
    df = pd.read_parquet(
        PANEL_PATH,
        columns=["date", "ticker", "ret_total", "ret_px", "prc_adj", "volume"])
    df = df[df["ticker"].isin(tickers)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    prev = df.groupby("ticker")["prc_adj"].shift(1)
    df["dividend"] = ((df["ret_total"] - df["ret_px"]) * prev).fillna(0.0)
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    out = pd.DataFrame({
        "date": df["date"].values,
        "ticker": df["ticker"].values,
        "close": df["prc_adj"].values,
        "dividend": df["dividend"].values,
        "volume": df["volume"].values,
        "source": "parquet",
        "fetched_at": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M:%S"),
    })
    return out.reset_index(drop=True)


def fetch_yfinance(tickers, start, end, verbose=True):
    """Bars from yfinance. Raw (split-adjusted) closes plus distributions.

    auto_adjust=False so the close is the close a human would see on a
    statement; actions=True so dividends and capital-gain distributions arrive
    as cash, which is how the ledger treats them.
    """
    import yfinance as yf

    end_excl = pd.Timestamp(end) + pd.Timedelta(days=1)
    raw = yf.download(sorted(tickers), start=pd.Timestamp(start),
                      end=end_excl, auto_adjust=False, actions=True,
                      progress=False, group_by="column")
    if raw is None or len(raw) == 0:
        if verbose:
            print(f"[prices] yfinance returned nothing for {sorted(tickers)} "
                  f"{start}..{end}")
        return pd.DataFrame(columns=PRICE_COLUMNS)

    def field(name, default=0.0):
        """Pull one field out as a date x ticker frame, single- or multi-index."""
        if isinstance(raw.columns, pd.MultiIndex):
            if name not in raw.columns.get_level_values(0):
                return pd.DataFrame(default, index=raw.index,
                                    columns=sorted(tickers))
            return raw[name]
        if name not in raw.columns:
            return pd.DataFrame(default, index=raw.index, columns=list(tickers))
        return raw[[name]].rename(columns={name: list(tickers)[0]})

    close = field("Close")
    volume = field("Volume")
    high = field("High", default=np.nan)
    low = field("Low", default=np.nan)
    divs = field("Dividends").fillna(0.0)
    cgs = field("Capital Gains").fillna(0.0)
    splits = field("Stock Splits").fillna(0.0)

    if float(np.abs(splits.values).sum()) > 0:
        where = splits[(splits != 0).any(axis=1)]
        print(f"[prices] *** SPLIT DETECTED on {len(where)} day(s) — a split "
              f"changes the share count and this simulator does NOT adjust "
              f"held shares automatically. Check the ledger by hand:\n"
              f"{where.to_string()}")

    frames = []
    for t in close.columns:
        s = close[t].dropna()
        if s.empty:
            continue
        frames.append(pd.DataFrame({
            "date": s.index,
            "ticker": t,
            "close": s.values,
            "dividend": (divs[t].reindex(s.index).fillna(0.0).values
                         + cgs[t].reindex(s.index).fillna(0.0).values),
            "volume": volume[t].reindex(s.index).fillna(0.0).values,
            "high": high[t].reindex(s.index).values if t in high.columns else np.nan,
            "low": low[t].reindex(s.index).values if t in low.columns else np.nan,
            "source": "yfinance",
            "fetched_at": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }))
    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    return out


# ---------------------------------------------------------------------------
# Derived views on the price store
# ---------------------------------------------------------------------------

def wide(prices, field="close"):
    """date x ticker frame of one column of the price store."""
    if prices.empty:
        return pd.DataFrame()
    w = prices.pivot(index="date", columns="ticker", values=field).sort_index()
    w.columns.name = None
    return w


def total_returns(prices):
    """Daily TOTAL returns, (close_t + distribution_t) / close_{t-1} - 1.

    Used for the risk-free leg (BIL) and for the live-vs-backtest comparison.
    """
    px = wide(prices, "close")
    dv = wide(prices, "dividend").reindex_like(px).fillna(0.0)
    return ((px + dv) / px.shift(1) - 1.0).iloc[1:]


def impact_vol_bp(prices):
    """Trailing daily return vol in bp, per ticker — the impact model's
    ``daily_vol_bp`` term. Same window and fallback as the engine."""
    px = wide(prices, "close")
    rets = px.pct_change()
    vol = (rets.rolling(IMPACT_VOL_WINDOW, min_periods=5).std() * 1e4)
    return vol.bfill().fillna(IMPACT_VOL_FALLBACK_BP)


def month_end_dates(index):
    """Last available trading day of each calendar month in ``index``."""
    idx = pd.DatetimeIndex(index)
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(sorted(s.groupby([idx.year, idx.month]).max().values))


def banner(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def money(x):
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"
