"""fetch_daily's NAV-fill convention, shared since 2026-10-13 by the missing-NAV
fallback and the session's stale-NAV gate (`quantt/session/nav_gate.py`).

WHY. The collector learns that a panel NAV came from CEFConnect only from
`data/cef/nav_fallback_log.csv` (`quantt/collect/collect.py` `_fallback_names`),
so every non-yfinance NAV must be logged there, in the same five columns, by
whichever path wrote it. These pin the columns, the header-once append, the
`source` label, and that a fill overwrites exactly its own (date, ticker) row.
Hermetic: tmp_path only.
"""
import pandas as pd

from scripts.cef import fetch_daily as fd


def test_the_log_keeps_its_columns_and_says_which_path_wrote_the_row(tmp_path):
    log = tmp_path / "nav_fallback_log.csv"
    F = pd.DataFrame([{"date": pd.Timestamp("2026-10-05"), "nav": 15.04, "ticker": "PDI"}])
    fd.log_nav_fills(F, "cefconnect", log)
    fd.log_nav_fills(F.assign(ticker="PCN", nav=10.99), "cefconnect_stale_copy", log)
    got = pd.read_csv(log)
    assert list(got.columns) == ["date", "nav", "ticker", "source", "written_utc"]
    assert got[["ticker", "nav", "source"]].values.tolist() == [
        ["PDI", 15.04, "cefconnect"], ["PCN", 10.99, "cefconnect_stale_copy"]]
    assert log.read_text().count("date,nav,ticker") == 1


def test_a_fill_overwrites_only_its_own_row():
    N = pd.DataFrame([{"date": pd.Timestamp(d), "nav": v, "ticker": t} for t, d, v in (
        ("PDI", "2026-10-02", 14.98), ("PDI", "2026-10-05", 14.98),
        ("PCN", "2026-10-05", 10.94))])
    F = pd.DataFrame([{"date": pd.Timestamp("2026-10-05"), "nav": 15.04, "ticker": "PDI"}])
    out = fd.merge_nav_fills(N, F)
    assert out[["ticker", "date", "nav"]].values.tolist() == [
        ["PCN", pd.Timestamp("2026-10-05"), 10.94],
        ["PDI", pd.Timestamp("2026-10-02"), 14.98],
        ["PDI", pd.Timestamp("2026-10-05"), 15.04]]
