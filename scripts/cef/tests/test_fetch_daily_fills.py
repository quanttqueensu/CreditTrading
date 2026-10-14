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


def test_cefconnect_d_and_d_minus_1_come_from_one_request(monkeypatch):
    """2026-10-13: the stale-NAV gate reads CEFConnect's D-1 and D for every name.
    One request per name, and the row chosen for a date is the one the
    single-date reader always chose (newest first, first row wins)."""
    import requests
    calls = []
    rows = [{"DataDate": "2026-09-24T00:00:00", "NAVData": 15.06},
            {"DataDate": "2026-09-25T00:00:00", "NAVData": 15.09},
            {"DataDate": "2026-09-25T00:00:00", "NAVData": 15.10}]   # a duplicate: last wins

    class R:
        def json(self):
            return {"Data": {"PriceHistory": rows}}

    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(a) or R())
    d1, d = pd.Timestamp("2026-09-24"), pd.Timestamp("2026-09-25")
    assert fd._cefconnect_navs("PDI", [d1, d, pd.Timestamp("2026-09-28")]) == {
        d1: 15.06, d: 15.10, pd.Timestamp("2026-09-28"): None}
    assert len(calls) == 1
    assert fd._cefconnect_nav("PDI", d) == 15.10
