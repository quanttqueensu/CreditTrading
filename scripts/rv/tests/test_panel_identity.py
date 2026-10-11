"""panel_identity: a rebuilt panel is judged byte for byte, and a difference is located.

The failure this guards against is a check that passes when it should not: a
last-bit float change, a revised volume or an extra ticker must each be either
reported (inside the old range) or ignored (outside it) -- never blurred.
Synthetic panels; the claim is about the comparator.
"""
import numpy as np
import pandas as pd

from scripts.rv import panel_identity as pi


def _long(dates, tickers=("AAA", "BBB"), seed=0):
    rng = np.random.default_rng(seed)
    rows = [{"date": pd.Timestamp(d), "ticker": t, "close": float(np.float32(rng.uniform(10, 100))),
             "volume": float(rng.integers(1, 10**6))} for t in tickers for d in dates]
    return pd.DataFrame(rows)


def _write(df, path, wide=False):
    df.to_parquet(path) if wide else df.to_parquet(path, index=False)
    return path


def test_a_faithful_rebuild_with_extra_rows_and_tickers_is_byte_identical(tmp_path):
    days = pd.bdate_range("2026-07-01", periods=5)
    old = _long(days)
    new = pd.concat([_long(days), _long(pd.bdate_range("2026-07-08", periods=3), seed=1),
                     _long(days, tickers=("ZZZ",), seed=2)]).sort_values(["ticker", "date"])
    old = old.sort_values(["ticker", "date"]).reset_index(drop=True)
    rep = pi.identity(_write(old, tmp_path / "o.parquet"), _write(new, tmp_path / "n.parquet"))
    assert rep["cell_identical"] and rep["byte_identical"]


def test_a_last_bit_change_is_found_and_dated(tmp_path):
    days = pd.bdate_range("2026-07-01", periods=5)
    old = _long(days)
    new = old.copy()
    i = new.index[(new.ticker == "BBB") & (new.date == days[3])][0]
    new.at[i, "close"] = np.nextafter(new.at[i, "close"], np.inf)
    rep = pi.identity(_write(old, tmp_path / "o.parquet"), _write(new, tmp_path / "n.parquet"))
    assert not rep["byte_identical"]
    cell = rep["cells"]["close"]
    assert cell["n_bitwise_diff"] == 1 and cell["by_date"] == {str(days[3].date()): 1}


def test_through_locates_the_identical_prefix(tmp_path):
    days = pd.bdate_range("2026-07-01", periods=5)
    old = _long(days)
    new = old.copy()
    new.loc[new.date == days[-1], "volume"] += 1          # a revised last-day volume
    o, n = _write(old, tmp_path / "o.parquet"), _write(new, tmp_path / "n.parquet")
    assert not pi.identity(o, n)["byte_identical"]
    rep = pi.identity(o, n, through=str(days[-2].date()))
    assert rep["byte_identical"] and "cut through" in rep["old_hashed"]


def test_exclude_is_explicit_and_wide_panels_compare_by_index(tmp_path):
    days = pd.bdate_range("2026-07-01", periods=4)
    old = pd.DataFrame({"AAA": [0.1, 0.2, 0.3, 0.4], "BBB": [1.0, 2.0, 3.0, 4.0]},
                       index=pd.DatetimeIndex(days, name="date"))
    new = old.copy()
    new["CCC"] = 9.0                                        # a new column: outside the old panel
    new.loc[days[0], "BBB"] = 1.5                           # a differing column
    o, n = _write(old, tmp_path / "o.parquet", True), _write(new, tmp_path / "n.parquet", True)
    rep = pi.identity(o, n, wide=True)
    assert not rep["byte_identical"] and set(rep["cells"]) == {"BBB"}
    rep = pi.identity(o, n, wide=True, exclude=["BBB"])
    assert rep["byte_identical"] and "excluded" in rep["old_hashed"]
