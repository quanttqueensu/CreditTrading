"""Standard tearsheet for the Phase 2+ harness — one metric interface for
every strategy, so Phases 3-6 report the same numbers the same way.

Conventions (matched to engine.py):

* Returns are simple daily returns; compounding is geometric.
* Sharpe is ALWAYS excess of the risk-free series carried on the result
  (``BacktestResult.rf`` — BIL ret_total unless the caller passed its own).
  Gross Sharpe uses the pre-cost path, net Sharpe the post-cost path; the
  same rf is subtracted from both, so the gross-net gap is pure cost drag.
* Annualization: 252 trading days (engine.TRADING_DAYS), vol by sqrt-time,
  CAGR by (1+r).prod() ** (252/N) - 1.
* Turnover is the engine's one-way daily turnover in weight units; the
  reported figure is the average ANNUAL total (sum / years), i.e. "1.0x"
  means the book's notional was traded through once per year, one way.
* Max drawdown is on the NET equity curve (what the book actually lived
  through) and is reported as a negative number.
* Worst calendar month is the worst compounded net month, labeled with its
  month, not a rolling 21-day window.

Standing engineering rule: every output prints its sample start/end and N.
``tearsheet()`` prints a one-line sample banner unless ``verbose=False``.
"""

from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252
_EPS = 1e-12


# ---------------------------------------------------------------------------
# Metric primitives (each takes plain Series; used directly by tests)
# ---------------------------------------------------------------------------

def _clean(returns):
    """Drop NaNs, validate, return a float Series."""
    s = pd.Series(returns).astype(float).dropna()
    if len(s) == 0:
        raise ValueError("return series is empty after dropping NaNs")
    return s


def cagr(returns, trading_days=TRADING_DAYS):
    """Geometric annualized return. (1+r).prod() ** (252/N) - 1."""
    s = _clean(returns)
    growth = float((1.0 + s).prod())
    if growth <= 0:
        return -1.0  # wiped out; annualizing a non-positive equity is undefined
    return growth ** (trading_days / len(s)) - 1.0


def ann_vol(returns, trading_days=TRADING_DAYS):
    """Annualized volatility of daily returns (sample std, ddof=1)."""
    s = _clean(returns)
    if len(s) < 2:
        return np.nan
    return float(s.std(ddof=1) * np.sqrt(trading_days))


def sharpe_ratio(returns, rf=None, trading_days=TRADING_DAYS):
    """Annualized Sharpe ratio of returns IN EXCESS of ``rf``.

    ``rf`` may be None (treated as zero), a scalar daily rate, or a Series
    aligned on dates (reindexed to the return index; NaNs are an error, so a
    short rf series can never silently inflate the ratio).

    Returns NaN when the excess series has zero variance — a constant path
    has no risk-adjusted return to speak of, and returning inf would poison
    downstream medians/gates.

    NOTE: guard.shift_test imports this function; keep the signature stable.
    """
    s = _clean(returns)
    if rf is None:
        excess = s
    elif np.isscalar(rf):
        excess = s - float(rf)
    else:
        rf_s = pd.Series(rf).astype(float).reindex(s.index)
        if rf_s.isna().any():
            first_bad = rf_s.index[rf_s.isna()][0]
            raise ValueError(
                f"rf series does not cover the return sample (first gap: "
                f"{pd.Timestamp(first_bad).date()}); pass a full rf or trim "
                "the returns")
        excess = s - rf_s
    if len(excess) < 2:
        return np.nan
    sd = float(excess.std(ddof=1))
    if sd < _EPS:
        return np.nan
    return float(excess.mean() / sd * np.sqrt(trading_days))


def equity_curve(returns, initial=1.0):
    """Cumulative growth of 1 unit (geometric)."""
    return initial * (1.0 + _clean(returns)).cumprod()


def max_drawdown(returns):
    """Worst peak-to-trough decline on the compounded curve, as a NEGATIVE
    fraction. Returns (maxdd, peak_date, trough_date)."""
    eq = equity_curve(returns)
    peak = eq.cummax()
    dd = eq / peak - 1.0
    trough = dd.idxmin()
    mdd = float(dd.min())
    if mdd >= 0.0:
        return 0.0, None, None
    peak_date = eq.loc[:trough].idxmax()
    return mdd, peak_date, trough


def monthly_returns(returns):
    """Compounded calendar-month returns (index = month-end timestamps)."""
    s = _clean(returns)
    if not isinstance(s.index, pd.DatetimeIndex):
        raise TypeError("monthly_returns needs a DatetimeIndex")
    return s.resample("ME").apply(lambda x: float((1.0 + x).prod() - 1.0))


def worst_month(returns):
    """(worst compounded calendar-month return, 'YYYY-MM' label)."""
    m = monthly_returns(returns)
    if len(m) == 0:
        return np.nan, None
    idx = m.idxmin()
    return float(m.min()), pd.Timestamp(idx).strftime("%Y-%m")


def avg_annual_turnover(turnover, n_days, trading_days=TRADING_DAYS):
    """Average one-way turnover per year, in weight units (engine's units)."""
    if turnover is None or n_days == 0:
        return np.nan
    years = n_days / trading_days
    if years <= 0:
        return np.nan
    return float(pd.Series(turnover).fillna(0.0).sum() / years)


# ---------------------------------------------------------------------------
# Tearsheet
# ---------------------------------------------------------------------------

def tearsheet(result, verbose=True):
    """Standard metric dict for a BacktestResult (or a WalkforwardResult —
    anything exposing .name/.gross/.net/.turnover/.rf/.start/.end/.n_days).

    Returns a dict with:
        name, start, end, n_days, years,
        cagr, ann_vol, sharpe_gross, sharpe_net,
        max_drawdown, dd_peak, dd_trough,
        worst_month, worst_month_label,
        avg_annual_turnover, total_cost_drag, cost_drag_annual,
        cagr_gross, hit_rate

    Prints the sample banner (start/end/N) unless verbose=False — standing
    rule: every output prints its sample dates.
    """
    for attr in ("net", "gross"):
        if not hasattr(result, attr):
            raise TypeError(
                f"tearsheet() needs a result object with .{attr} "
                f"(BacktestResult / WalkforwardResult); got {type(result)}")

    net = _clean(result.net)
    gross = _clean(result.gross)
    rf = getattr(result, "rf", None)
    name = getattr(result, "name", "strategy")

    start = getattr(result, "start", None) or net.index[0]
    end = getattr(result, "end", None) or net.index[-1]
    n_days = getattr(result, "n_days", 0) or len(net)
    years = n_days / TRADING_DAYS

    mdd, peak_date, trough_date = max_drawdown(net)
    wm, wm_label = worst_month(net)

    costs = getattr(result, "costs", None)
    total_cost = float(pd.Series(costs).fillna(0.0).sum()) if costs is not None else np.nan
    cost_annual = total_cost / years if (years > 0 and costs is not None) else np.nan

    out = {
        "name": name,
        "start": pd.Timestamp(start),
        "end": pd.Timestamp(end),
        "n_days": int(n_days),
        "years": years,
        "cagr": cagr(net),
        "cagr_gross": cagr(gross),
        "ann_vol": ann_vol(net),
        "sharpe_gross": sharpe_ratio(gross, rf),
        "sharpe_net": sharpe_ratio(net, rf),
        "max_drawdown": mdd,
        "dd_peak": peak_date,
        "dd_trough": trough_date,
        "worst_month": wm,
        "worst_month_label": wm_label,
        "avg_annual_turnover": avg_annual_turnover(
            getattr(result, "turnover", None), n_days),
        "total_cost_drag": total_cost,
        "cost_drag_annual": cost_annual,
        "hit_rate": float((net > 0).mean()),
    }

    if verbose:
        print(f"[tearsheet] {name}: sample {out['start'].date()}.."
              f"{out['end'].date()} N={out['n_days']} days "
              f"({out['years']:.1f}y)")
        print(f"[tearsheet]   CAGR {out['cagr']:+.2%} | vol {out['ann_vol']:.2%} "
              f"| Sharpe gross {out['sharpe_gross']:+.2f} net {out['sharpe_net']:+.2f} "
              f"| maxDD {out['max_drawdown']:.2%} | worst month "
              f"{out['worst_month']:+.2%} ({out['worst_month_label']}) "
              f"| turnover {out['avg_annual_turnover']:.2f}x/yr")
    return out


def _fmt(value, kind):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    if kind == "pct":
        return f"{value:+.2%}"
    if kind == "pct_abs":
        return f"{value:.2%}"
    if kind == "num":
        return f"{value:+.2f}"
    if kind == "turn":
        return f"{value:.2f}x"
    if kind == "date":
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    return str(value)


def to_markdown(metrics, title=None, verbose=False):
    """Render a tearsheet dict (or a result object) as a Markdown table.

    Accepts either the dict from ``tearsheet()`` or a raw result object (in
    which case the tearsheet is computed first). The sample line is part of
    the output — every published table carries its own dates and N.
    """
    if not isinstance(metrics, dict):
        metrics = tearsheet(metrics, verbose=verbose)

    name = title or metrics.get("name", "strategy")
    dd_window = ""
    if metrics.get("dd_peak") is not None and metrics.get("dd_trough") is not None:
        dd_window = (f" ({_fmt(metrics['dd_peak'], 'date')} → "
                     f"{_fmt(metrics['dd_trough'], 'date')})")

    rows = [
        ("CAGR (net)", _fmt(metrics["cagr"], "pct")),
        ("CAGR (gross)", _fmt(metrics["cagr_gross"], "pct")),
        ("Annualized vol", _fmt(metrics["ann_vol"], "pct_abs")),
        ("Sharpe (gross, excess of rf)", _fmt(metrics["sharpe_gross"], "num")),
        ("Sharpe (net, excess of rf)", _fmt(metrics["sharpe_net"], "num")),
        ("Max drawdown", _fmt(metrics["max_drawdown"], "pct") + dd_window),
        ("Worst calendar month",
         _fmt(metrics["worst_month"], "pct")
         + (f" ({metrics['worst_month_label']})"
            if metrics.get("worst_month_label") else "")),
        ("Avg annual turnover (one-way)",
         _fmt(metrics["avg_annual_turnover"], "turn")),
        ("Cost drag (annualized)", _fmt(metrics["cost_drag_annual"], "pct_abs")),
        ("Positive days", _fmt(metrics["hit_rate"], "pct_abs")),
    ]

    lines = [
        f"### {name}",
        "",
        f"*Sample {_fmt(metrics['start'], 'date')} → {_fmt(metrics['end'], 'date')}, "
        f"N = {metrics['n_days']} trading days ({metrics['years']:.1f} years). "
        f"Net = after costs from `config/costs.yaml`. Sharpe is excess of the "
        f"risk-free series (BIL total return unless overridden).*",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines.append("")
    return "\n".join(lines)


def write_markdown(metrics, path, title=None):
    """Write ``to_markdown`` output to a file; returns the text."""
    text = to_markdown(metrics, title=title)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"[tearsheet] wrote {path}")
    return text


def compare(results, verbose=True):
    """Tearsheet several results into one DataFrame (one row per result) —
    used by the Phase 2 planted-case calibration and Phase 3+ variant tables."""
    rows = [tearsheet(r, verbose=verbose) for r in results]
    df = pd.DataFrame(rows).set_index("name")
    return df
