"""Shared fixtures for the backtest-harness tests.

Everything here is synthetic and hand-checkable. No test touches
data/etf_daily.parquet — the harness must be provably correct on toy inputs
whose right answers are computed by hand in the test itself, independent of
the implementation being tested.
"""

import numpy as np
import pandas as pd
import pytest
import yaml


@pytest.fixture
def costs_simple(tmp_path):
    """Minimal costs config: HYG/JNK at 1.0bp half-spread, no slippage, no
    commission. Written to a temp yaml so tests exercise load_costs() rather
    than hand-building the dict — the 'costs come from config' rule."""
    cfg = {
        "commission_usd_per_trade": 0.0,
        "book_usd_default": 60000,
        "slippage_extra_bp": 0.0,
        "tickers": {
            "HYG": {"half_spread_bp": 1.0},
            "JNK": {"half_spread_bp": 1.0},
            "BIL": {"half_spread_bp": 0.5},
        },
    }
    path = tmp_path / "costs_simple.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def write_costs(tmp_path, name, *, half_spread_bp=1.0, slippage_extra_bp=0.0,
                commission_usd_per_trade=0.0, book_usd_default=60000):
    """Write a one-off costs yaml so a test can vary a single knob and prove
    the engine reads it (rather than a hardcoded number)."""
    cfg = {
        "commission_usd_per_trade": commission_usd_per_trade,
        "book_usd_default": book_usd_default,
        "slippage_extra_bp": slippage_extra_bp,
        "tickers": {t: {"half_spread_bp": half_spread_bp}
                    for t in ("HYG", "JNK", "BIL")},
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(cfg))
    return path


def make_panel(values, start="2020-01-02"):
    """Build a returns panel from {ticker: [daily returns]} on business days."""
    n = len(next(iter(values.values())))
    idx = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame(values, index=idx)


def zero_rf(index):
    """A zero risk-free series, so hand-computed gross returns are exact."""
    return pd.Series(0.0, index=index)
