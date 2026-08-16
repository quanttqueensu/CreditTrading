"""Vectorized daily backtest engine — Phase 2 harness, reused by Phases 3-6.

Core rules (enforced here, tested in tests/test_engine.py):

* T+1 execution: a target-weight row dated day t is decided with data
  through day t's close and is APPLIED FROM day t+1's return. Internally:
  targets are reindexed to the simulation calendar, forward-filled, then
  shifted one day. A strategy can never earn same-day returns on a
  same-day decision.
* Costs come from config/costs.yaml (``load_costs``) — never hardcoded:
      daily cost fraction =
          sum_i |dw_i| * (half_spread_bp_i + slippage_extra_bp) / 1e4
        + (# tickers traded that day) * commission_usd_per_trade / book_usd
  charged on the first day the new weight earns returns. Turnover is
  one-way, in weight units (|delta applied weight| summed over tickers).
  Drift-rebalancing trades between explicit target changes are ignored
  (second-order for these daily/monthly ETF strategies; the conservative
  half-spread bumps in costs.yaml cover it).
* Cash: residual weight (1 - sum of applied weights) earns the daily
  risk-free return. Until data/riskfree_daily.parquet exists the proxy is
  BIL ``ret_total`` (audited, in the panel). Negative cash (gross exposure
  > 1) borrows at the same rate — a simplification, fine for the long-only
  strategies in this build.
* Look-ahead guard: pass ``info_dates`` (see guard.py). The engine raises
  guard.LookaheadError if any weight row claims information newer than its
  own date. Phase 3+ must always pass info_dates.

Every run prints sample start/end and N (standing engineering rule).
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import guard

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COSTS_PATH = REPO_ROOT / "config" / "costs.yaml"
DEFAULT_PANEL_PATH = REPO_ROOT / "data" / "etf_daily.parquet"

TRADING_DAYS = 252
_EPS = 1e-9

# Market-impact sizing: trailing window for the daily vol term, and the
# fallback used before that window has filled (roughly a credit ETF's daily
# vol; only reached in the first days of a sample).
IMPACT_VOL_WINDOW = 21
IMPACT_VOL_FALLBACK_BP = 50.0

WEIGHT_MIN, WEIGHT_MAX = -1.5, 1.5


# ---------------------------------------------------------------------------
# Config / data loading
# ---------------------------------------------------------------------------

def load_costs(path=DEFAULT_COSTS_PATH):
    """Load the trading-cost config (config/costs.yaml). Never hardcode costs.

    Returns a dict with keys: commission_usd_per_trade, book_usd_default,
    slippage_extra_bp, tickers -> {TICKER: {half_spread_bp: float}}.
    """
    with open(path) as f:
        costs = yaml.safe_load(f)
    for key in ("commission_usd_per_trade", "book_usd_default",
                "slippage_extra_bp", "tickers"):
        if key not in costs:
            raise KeyError(f"costs config {path} missing required key '{key}'")
    for tkr, entry in costs["tickers"].items():
        if "half_spread_bp" not in entry:
            raise KeyError(f"costs config: ticker {tkr} missing half_spread_bp")
    return costs


def load_panel(path=DEFAULT_PANEL_PATH, tickers=None, verbose=True):
    """Load data/etf_daily.parquet as a wide total-return panel.

    Returns (returns, rf):
      returns — DataFrame dates x tickers of ``ret_total`` (NaN before each
                fund's inception),
      rf      — BIL ``ret_total`` Series (risk-free proxy per data/README.md),
                or None if BIL was excluded via ``tickers``.
    """
    df = pd.read_parquet(path, columns=["date", "ticker", "ret_total"])
    if tickers is not None:
        df = df[df["ticker"].isin(tickers)]
    wide = df.pivot(index="date", columns="ticker", values="ret_total").sort_index()
    wide.columns.name = None
    if verbose:
        print(f"[load_panel] {path}")
        for tkr in wide.columns:
            s = wide[tkr].dropna()
            print(f"[load_panel]   {tkr}: sample {s.index.min().date()}.."
                  f"{s.index.max().date()} N={len(s)} days")
    rf = wide["BIL"].copy() if "BIL" in wide.columns else None
    return wide, rf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def realized_vol(returns, window=21, trading_days=TRADING_DAYS):
    """Rolling realized volatility, annualized. Value at date t uses returns
    through t only (info_date = t), so it is safe to feed into a weight row
    dated t (the engine's T+1 shift handles execution)."""
    return returns.rolling(window).std(ddof=1) * np.sqrt(trading_days)


def vol_target_scale(asset_returns, target_vol, window=21, cap=1.5,
                     trading_days=TRADING_DAYS):
    """Vol-target scaling series: min(cap, target_vol / realized_vol_t).

    ``asset_returns`` is a daily return Series; the value at date t uses
    returns through t only (info_date = t). First window-1 values are NaN —
    the caller decides how to handle warm-up (typically fillna(0) = stay in
    cash). Multiply by a directional signal to get target weights.
    """
    vol = realized_vol(asset_returns, window=window, trading_days=trading_days)
    return (target_vol / vol).clip(upper=cap)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class BacktestResult:
    name: str
    gross: pd.Series          # daily gross strategy return
    net: pd.Series            # daily net-of-cost strategy return
    positions: pd.DataFrame   # applied weights (the exposure earning that day's return)
    turnover: pd.Series       # one-way daily turnover, weight units
    costs: pd.Series          # daily cost drag (return fraction)
    rf: pd.Series             # daily risk-free return over the sim window
    start: pd.Timestamp = None
    end: pd.Timestamp = None
    n_days: int = 0
    meta: dict = field(default_factory=dict)


def run_backtest(weights, returns, costs, rf=None, info_dates=None,
                 book_usd=None, extra_lag=0, max_ffill_days=31,
                 dollar_volume=None, name="strategy", verbose=True):
    """Run the daily backtest.

    Parameters
    ----------
    weights : DataFrame, index = decision dates, columns = tickers.
        Row dated t = target weights decided with data through day t's close;
        applied from day t+1's return (T+1). Values must be in [-1.5, 1.5],
        no NaNs (fill 0 for flat). Targets persist (ffill) until changed.
    returns : DataFrame, dates x tickers of daily TOTAL returns
        (use ret_total from data/etf_daily.parquet via load_panel).
    costs : dict from load_costs(), or a path to a costs yaml.
    rf : Series of daily risk-free returns. If None and 'BIL' is a column of
        ``returns``, BIL ret_total is used (documented proxy). Cash earns rf.
    info_dates : Series indexed like weights.index; per row, the date of the
        newest data used to build that row. Checked by guard.assert_lagged
        (raises LookaheadError if any info date is after its row date).
        Phase 3+ must always pass this; omitting it prints a loud warning.
    book_usd : book size for the commission term; default from the config
        (book_usd_default). Only matters when commission_usd_per_trade > 0.
    extra_lag : extra days of signal delay on top of the T+1 rule
        (used by guard.shift_test; leave at 0 for normal runs).
    dollar_volume : optional DataFrame dates x tickers of daily dollar volume
        (volume * price from data/etf_daily.parquet). When supplied, trades pay
        square-root-law market impact on top of the half-spread, and any day
        whose trade exceeds max_participation_pct of that day's volume is
        counted and reported. WITHOUT it, book size has no effect on percent
        returns at all — which silently assumes infinite liquidity. Pass it
        whenever the book size is part of the claim.
    max_ffill_days : how many trading days the LAST weight row may be carried
        past the end of the weight frame before the run is rejected. Default 31
        covers a monthly-rebalanced strategy's final partial month; a truncated
        signal frame trips it instead of silently holding a stale position.
        Pass None to disable (say why in the calling code).
    name, verbose : labeling / printing.

    Returns BacktestResult (gross, net, positions, turnover, costs, rf, ...).
    """
    if isinstance(costs, (str, Path)):
        costs = load_costs(costs)

    # --- validate returns -------------------------------------------------
    # An unsorted returns index misaligns the T+1 shift SILENTLY: the position
    # decided on day t lands on whatever row happens to sit next in the frame.
    # load_panel() sorts, but callers may build panels by hand.
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a DataFrame (dates x tickers)")
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise TypeError("returns index must be a DatetimeIndex")
    if not returns.index.is_monotonic_increasing:
        raise ValueError(
            "returns index is not sorted ascending — the T+1 shift would "
            "misalign silently. Sort it (load_panel does this for you).")
    if returns.index.has_duplicates:
        dupes = returns.index[returns.index.duplicated()][:3]
        raise ValueError(
            f"returns index has duplicate dates (first: "
            f"{[d.date() for d in dupes]}) — T+1 alignment is undefined")

    # --- validate weights -------------------------------------------------
    if not isinstance(weights, pd.DataFrame):
        raise TypeError("weights must be a DataFrame (dates x tickers)")
    if not isinstance(weights.index, pd.DatetimeIndex):
        raise TypeError("weights index must be a DatetimeIndex")
    if not weights.index.is_monotonic_increasing or weights.index.has_duplicates:
        raise ValueError("weights index must be sorted and unique")
    if weights.isna().any().any():
        raise ValueError("weights contain NaN — fill explicitly (0 = flat)")
    if (weights.values < WEIGHT_MIN).any() or (weights.values > WEIGHT_MAX).any():
        bad = weights[(weights < WEIGHT_MIN) | (weights > WEIGHT_MAX)].dropna(how="all")
        raise ValueError(f"weights outside [{WEIGHT_MIN}, {WEIGHT_MAX}]:\n{bad.head()}")
    missing_cols = [c for c in weights.columns if c not in returns.columns]
    if missing_cols:
        raise ValueError(f"weights columns not in returns panel: {missing_cols}")
    off_calendar = weights.index.difference(returns.index)
    if len(off_calendar):
        raise ValueError(
            f"{len(off_calendar)} weight rows dated on non-trading days, "
            f"first: {off_calendar[0].date()}")
    missing_costs = [c for c in weights.columns if c not in costs["tickers"]]
    if missing_costs:
        raise ValueError(f"no cost entry in config for tickers: {missing_costs}")
    if not isinstance(extra_lag, (int, np.integer)) or extra_lag < 0:
        raise ValueError("extra_lag must be a non-negative integer")

    # --- lookahead guard --------------------------------------------------
    if info_dates is not None:
        guard.assert_lagged(weights, info_dates)
    elif verbose:
        print(f"[engine] WARNING ({name}): no info_dates passed — lookahead "
              "guard skipped. Phase 3+ must pass info_dates (see guard.py).")

    # --- simulation calendar ---------------------------------------------
    sim_dates = returns.index[returns.index >= weights.index.min()]
    if len(sim_dates) < 2:
        raise ValueError("simulation window has fewer than 2 days")
    cols = list(weights.columns)
    rets = returns.loc[sim_dates, cols]

    # --- risk-free --------------------------------------------------------
    if rf is None:
        if "BIL" in returns.columns:
            rf = returns["BIL"]
            if verbose:
                print(f"[engine] ({name}) rf = BIL ret_total (risk-free proxy "
                      "per data/README.md)")
        else:
            raise ValueError("rf is None and no BIL column in returns — pass "
                             "a risk-free return series explicitly")
    rf_sim = rf.reindex(sim_dates)
    if rf_sim.isna().any():
        first_bad = rf_sim.index[rf_sim.isna()][0]
        raise ValueError(
            f"risk-free series has NaN inside the simulation window "
            f"(first: {first_bad.date()}). Restrict the sample to the rf "
            "series' coverage or pass a longer rf.")

    # --- T+1 application --------------------------------------------------
    # Weights are forward-filled between decision dates (a monthly strategy
    # holds its position through the month). But an UNBOUNDED ffill means a
    # truncated signal frame silently holds its last position to the end of
    # the price panel — 10 weight rows would produce a multi-year run still at
    # full exposure. Anything past max_ffill_days of stale weight is a bug.
    trailing = int((sim_dates > weights.index.max()).sum())
    if max_ffill_days is not None and trailing > max_ffill_days:
        raise ValueError(
            f"weights end {weights.index.max().date()} but the returns panel "
            f"runs to {sim_dates[-1].date()} — {trailing} trading days would "
            f"be held on a stale weight (limit max_ffill_days={max_ffill_days}). "
            "Extend the weights to the sample end, or raise max_ffill_days "
            "deliberately if a long hold really is intended.")
    w_target = weights.reindex(sim_dates).ffill().fillna(0.0)
    w_applied = w_target.shift(1 + extra_lag).fillna(0.0)

    # exposure to a NaN return (pre-inception ticker) is a hard error
    exposed_nan = (w_applied.abs() > _EPS) & rets.isna()
    if exposed_nan.any().any():
        first_bad = exposed_nan.any(axis=1)
        first_bad = first_bad.index[first_bad][0]
        raise ValueError(
            f"nonzero weight on a NaN return (ticker not yet trading), "
            f"first: {first_bad.date()}. Start weights at/after inception.")
    rets = rets.fillna(0.0)

    # --- returns ----------------------------------------------------------
    # Cash above 100% invested is BORROWED, and no broker lends at the bill
    # rate. Charging borrowing at rf flatters every levered strategy (a
    # vol-targeted sleeve capped at 1.5x borrows on a large share of days), so
    # financing_spread_bp is added to rf on the negative cash leg only.
    cash_w = 1.0 - w_applied.sum(axis=1)
    fin_spread_ann = float(costs.get("financing_spread_bp", 0.0)) / 1e4
    fin_daily = fin_spread_ann / TRADING_DAYS
    lend_w = cash_w.clip(lower=0.0)      # uninvested cash earns rf
    borrow_w = cash_w.clip(upper=0.0)    # negative: pays rf + spread
    gross = ((w_applied * rets).sum(axis=1)
             + lend_w * rf_sim
             + borrow_w * (rf_sim + fin_daily))

    # --- turnover and costs ----------------------------------------------
    dw = w_applied.diff()
    dw.iloc[0] = w_applied.iloc[0]
    turnover = dw.abs().sum(axis=1)

    slippage = float(costs["slippage_extra_bp"])
    bp_vec = pd.Series(
        {c: float(costs["tickers"][c]["half_spread_bp"]) + slippage for c in cols})
    spread_cost = (dw.abs() * bp_vec).sum(axis=1) / 1e4

    if book_usd is None:
        book_usd = float(costs["book_usd_default"])
    commission = float(costs["commission_usd_per_trade"])
    n_traded = (dw.abs() > _EPS).sum(axis=1)
    commission_cost = n_traded * commission / book_usd

    # --- market impact and liquidity feasibility --------------------------
    # Half-spread is proportional, so without this a $25k and a $100k book are
    # byte-identical in percent terms — which quietly asserts that any size
    # trades free. For a thin ETF that is false, and it is exactly how a
    # backtest banks returns from an era it could never have traded.
    impact_cost = pd.Series(0.0, index=sim_dates)
    liquidity = None
    if dollar_volume is not None:
        dv = dollar_volume.reindex(index=sim_dates, columns=cols)
        traded_usd = dw.abs() * book_usd
        # A missing or zero volume day cannot absorb any trade at all.
        with np.errstate(divide="ignore", invalid="ignore"):
            participation = traded_usd / dv.replace(0.0, np.nan)
        participation = participation.where(traded_usd > 0.0, 0.0)

        vol_bp = (rets.rolling(IMPACT_VOL_WINDOW, min_periods=5).std()
                  * 1e4).reindex(sim_dates)
        vol_bp = vol_bp.bfill().fillna(IMPACT_VOL_FALLBACK_BP)
        coef = float(costs.get("impact_coefficient", 0.0))
        impact_bp = coef * vol_bp * np.sqrt(participation.fillna(0.0))
        impact_cost = (dw.abs() * impact_bp).sum(axis=1) / 1e4

        cap = float(costs.get("max_participation_pct", 100.0)) / 100.0
        infeasible = participation > cap
        unpriced = participation.isna() & (traded_usd > 0.0)
        n_bad = int(infeasible.sum().sum() + unpriced.sum().sum())
        if n_bad:
            worst = participation.max().max()
            per_ticker = (infeasible.sum() + unpriced.sum())
            per_ticker = per_ticker[per_ticker > 0].to_dict()
            liquidity = {"n_infeasible_trades": n_bad,
                         "worst_participation": float(worst),
                         "by_ticker": per_ticker,
                         "cap": cap}
            if verbose:
                print(f"[engine] LIQUIDITY WARNING ({name}): {n_bad} trades "
                      f"exceed {cap:.0%} of a day's volume (worst "
                      f"{worst:.0%}) — {per_ticker}. These fills are not "
                      "realistic at this book size; the result overstates "
                      "what the book could actually have captured.")

    cost = spread_cost + commission_cost + impact_cost
    net = gross - cost

    result = BacktestResult(
        name=name, gross=gross, net=net, positions=w_applied,
        turnover=turnover, costs=cost, rf=rf_sim,
        start=sim_dates[0], end=sim_dates[-1], n_days=len(sim_dates),
        meta={"book_usd": book_usd, "extra_lag": extra_lag,
              "tickers": cols, "target_weights": w_target,
              "impact_cost": impact_cost, "liquidity": liquidity},
    )
    if verbose:
        years = len(sim_dates) / TRADING_DAYS
        print(f"[engine] {name}: sample {result.start.date()}..{result.end.date()} "
              f"N={result.n_days} days | avg annual turnover "
              f"{turnover.sum() / years:.2f}x | total cost drag {cost.sum():.4%}")
    return result
