"""The AQR factor-file parser, on synthetic sheets: the layout checks raise rather than
shift values, empty cells stay NaN, and a unit change is caught. No network."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from scripts.data import fetch_aqr_factors as fa

HDR = [None, "TSMOM", "TSMOM^CM", "TSMOM^EQ", "TSMOM^FI", "TSMOM^FX"]


def _sheet(rows, header=HDR, pad=3):
    junk = [["AQR Capital Management", None, None, None, None, None]] + [[None] * 6] * pad
    return pd.DataFrame(junk + [header] + rows + [[None] * 6, ["Source: AQR", None, None, None, None, None]])


def _rows(n=4, start=dt.datetime(2020, 1, 31)):
    out = []
    for i in range(n):
        d = (pd.Timestamp(start) + pd.offsets.MonthEnd(i)).to_pydatetime()
        out.append([d, 0.01 * i, -0.02, 0.0, 0.005, np.nan if i == 0 else 0.001])
    return out


def test_parses_and_keeps_nan():
    df = fa.parse_sheet(_sheet(_rows()), HDR)
    assert list(df.columns) == ["date"] + HDR[1:]
    assert len(df) == 4 and df["TSMOM"].iloc[2] == pytest.approx(0.02)
    assert np.isnan(df["TSMOM^FX"].iloc[0])                 # not filled


def test_string_dates_parse():
    rows = [[r[0].strftime("%m/%d/%Y")] + r[1:] for r in _rows()]
    assert len(fa.parse_sheet(_sheet(rows), HDR)) == 4


def test_renamed_column_raises():
    bad = HDR[:-1] + ["TSMOM^XX"]
    with pytest.raises(fa.AQRFetchError):
        fa.parse_sheet(_sheet(_rows(), header=bad), HDR)


def test_month_gap_raises():
    rows = _rows(4)
    del rows[2]
    with pytest.raises(fa.AQRFetchError):
        fa.parse_sheet(_sheet(rows), HDR)


def test_percent_units_raise():
    rows = _rows(4)
    rows[1][1] = 4.3                                          # 4.3 = a percent, not a decimal
    with pytest.raises(fa.AQRFetchError):
        fa.parse_sheet(_sheet(rows), HDR)


def test_non_numeric_raises():
    rows = _rows(4)
    rows[1][2] = "n/a"
    with pytest.raises(fa.AQRFetchError):
        fa.parse_sheet(_sheet(rows), HDR)
