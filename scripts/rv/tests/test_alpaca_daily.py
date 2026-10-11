"""The Alpaca leg that continues the ETF panels (scripts/rv/alpaca_daily.py).

Each test pins one refusal or one convention the module docstring promises:
NY-midnight dates, raw SIP bars asked for explicitly, summed same-day
dividends, refusal of splits / capital gains / duplicate records / missing
sessions, the 5bp cross-check gate, and that the first spliced return accrues
from ALPACA's own seam close. Synthetic payloads and a fake client: the claims
are about the code, not the market, and nothing here opens a socket.
"""
import datetime as dt

import pandas as pd
import pytest

from scripts.rv import alpaca_daily as ad


def bar(t, c, o=None, h=None, l=None, v=1000):  # noqa: E741
    o = c if o is None else o
    h = max(o, c) if h is None else h
    l = min(o, c) if l is None else l  # noqa: E741
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "n": 10, "vw": c}


class FakeClient:
    """Answers GET /v2/stocks/bars and /v1/corporate-actions from canned pages,
    and /v2/calendar from a list of dates. Records every call."""

    def __init__(self, bar_pages, ca_pages, sessions):
        self.bar_pages, self.ca_pages, self._sessions = list(bar_pages), list(ca_pages), sessions
        self.calls = []

    def _get(self, base, path, params=None):
        self.calls.append((base, path, dict(params or {})))
        assert base == ad.DATA_BASE
        if path == "/v2/stocks/bars":
            return self.bar_pages.pop(0)
        if path == "/v1/corporate-actions":
            return self.ca_pages.pop(0)
        raise AssertionError(f"unexpected GET {path}")

    def calendar(self, start, end):
        return [{"date": d} for d in self._sessions if start <= d <= end]


D = dt.date


# ------------------------------------------------------------------ dates

def test_daily_bars_map_to_the_new_york_date_in_both_dst_regimes():
    rows = ad.parse_bars({"HYG": [bar("2026-07-29T04:00:00Z", 79.24),     # EDT midnight
                                  bar("2026-01-05T05:00:00Z", 80.00)]},   # EST midnight
                         {"HYG"})
    assert [r["date"] for r in rows] == [pd.Timestamp("2026-07-29"), pd.Timestamp("2026-01-05")]


def test_a_bar_not_stamped_at_ny_midnight_is_refused():
    with pytest.raises(ad.AlpacaLegError, match="not midnight"):
        ad.parse_bars({"HYG": [bar("2026-07-29T00:00:00Z", 79.24)]}, {"HYG"})


def test_unrequested_symbol_and_missing_field_are_refused():
    with pytest.raises(ad.AlpacaLegError, match="not requested"):
        ad.parse_bars({"JNK": [bar("2026-07-29T04:00:00Z", 1.0)]}, {"HYG"})
    b = bar("2026-07-29T04:00:00Z", 1.0)
    del b["c"]
    with pytest.raises(ad.AlpacaLegError, match="missing"):
        ad.parse_bars({"HYG": [b]}, {"HYG"})


def test_last_complete_date_is_never_today():
    ny = ad.NY
    assert ad.last_complete_date(dt.datetime(2026, 7, 29, 10, 46, tzinfo=ny)) == D(2026, 7, 28)
    assert ad.last_complete_date(dt.datetime(2026, 7, 29, 23, 59, tzinfo=ny)) == D(2026, 7, 28)
    # 01:00 UTC on the 30th is still the 29th in New York
    assert ad.last_complete_date(dt.datetime(2026, 7, 30, 1, 0, tzinfo=dt.timezone.utc)) == D(2026, 7, 28)


# ------------------------------------------------------------------ bars

def test_fetch_bars_asks_for_raw_sip_with_explicit_timestamps_and_follows_pages():
    pages = [{"bars": {"HYG": [bar("2026-07-27T04:00:00Z", 79.27)]}, "next_page_token": "p2"},
             {"bars": {"HYG": [bar("2026-07-28T04:00:00Z", 79.42)]}, "next_page_token": None}]
    c = FakeClient(pages, [], [])
    df = ad.fetch_bars(c, ["HYG"], D(2026, 7, 27), D(2026, 7, 28))
    assert list(df["close"]) == [79.27, 79.42]
    p1, p2 = c.calls[0][2], c.calls[1][2]
    assert (p1["feed"], p1["adjustment"], p1["timeframe"]) == ("sip", "raw", "1Day")
    assert p1["start"] == "2026-07-27T00:00:00-04:00" and p1["end"] == "2026-07-28T20:00:00-04:00"
    assert "page_token" not in p1 and p2["page_token"] == "p2"


def test_a_requested_symbol_with_no_bars_is_refused():
    pages = [{"bars": {"HYG": [bar("2026-07-27T04:00:00Z", 79.27)]}, "next_page_token": None}]
    with pytest.raises(ad.AlpacaLegError, match=r"no bars at all for \['JNK'\]"):
        ad.fetch_bars(FakeClient(pages, [], []), ["HYG", "JNK"], D(2026, 7, 27), D(2026, 7, 27))


# ------------------------------------------------------- corporate actions

def div(sym, ex, rate):
    return {"symbol": sym, "ex_date": ex, "rate": rate, "special": False, "foreign": False,
            "process_date": ex, "cusip": "x", "id": f"{sym}{ex}{rate}"}


def test_same_day_dividend_records_are_summed_and_out_of_window_ones_dropped():
    pages = [{"cash_dividends": [div("CLOI", "2025-12-29", 0.2332), div("CLOI", "2025-12-29", 0.0349),
                                 div("CLOI", "2024-12-27", 0.5)]}]
    out = ad.parse_corporate_actions(pages, D(2025, 1, 1), D(2026, 1, 31), D(2026, 10, 11))
    assert len(out) == 1
    assert out["dividend"].iat[0] == pytest.approx(0.2681)


def test_identical_dividend_records_are_refused_not_double_counted():
    pages = [{"cash_dividends": [div("QQQ", "2022-09-19", 0.51856), div("QQQ", "2022-09-19", 0.51856)]}]
    with pytest.raises(ad.AlpacaLegError, match="double-count"):
        ad.parse_corporate_actions(pages, D(2022, 1, 1), D(2022, 12, 31), D(2026, 10, 11))


def test_a_split_anywhere_from_window_start_to_today_is_refused():
    split = {"symbol": "JNK", "ex_date": "2026-09-01", "old_rate": 3, "new_rate": 1,
             "process_date": "2026-09-01"}
    pages = [{"reverse_splits": [split]}]
    # after the window's end but before today: still two share bases in one panel
    with pytest.raises(ad.AlpacaLegError, match="split"):
        ad.parse_corporate_actions(pages, D(2026, 1, 1), D(2026, 7, 31), D(2026, 10, 11))
    # before the window: no effect
    out = ad.parse_corporate_actions([{"reverse_splits": [dict(split, ex_date="2019-05-06")]}],
                                     D(2026, 1, 1), D(2026, 7, 31), D(2026, 10, 11))
    assert out.empty


def test_a_capital_gains_record_in_the_window_is_refused():
    pages = [{"capital_gains_distributions": [{"symbol": "BND", "ex_date": "2026-03-01"}]}]
    with pytest.raises(ad.AlpacaLegError, match="capital-gains"):
        ad.parse_corporate_actions(pages, D(2026, 1, 1), D(2026, 7, 31), D(2026, 10, 11))


def test_dividend_on_a_day_without_a_bar_is_refused_and_other_days_are_zero():
    bars = pd.DataFrame({"date": pd.to_datetime(["2026-08-03", "2026-08-04"]), "ticker": "HYG",
                         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    ok = pd.DataFrame({"ticker": ["HYG"], "date": pd.to_datetime(["2026-08-03"]), "dividend": [0.4]})
    out = ad.attach_dividends(bars, ok)
    assert list(out["dividend"]) == [0.4, 0.0]
    orphan = pd.DataFrame({"ticker": ["HYG"], "date": pd.to_datetime(["2026-08-01"]), "dividend": [0.4]})
    with pytest.raises(ad.AlpacaLegError, match="no bar"):
        ad.attach_dividends(bars, orphan)


def test_a_session_without_a_bar_is_refused():
    f = pd.DataFrame({"ticker": "HYG", "date": pd.to_datetime(["2026-08-03", "2026-08-05"])})
    cal = [pd.Timestamp(d) for d in ("2026-08-03", "2026-08-04", "2026-08-05")]
    with pytest.raises(ad.AlpacaLegError, match="sessions without a bar"):
        ad.check_sessions(f, cal, D(2026, 8, 3), D(2026, 8, 5), "t")


# ------------------------------------------------------------ cross-check

def _frame(closes, divs=None, start="2026-07-27"):
    n = len(closes)
    f = pd.DataFrame({"date": pd.bdate_range(start, periods=n), "ticker": "HYG",
                      "close": closes, "dividend": divs or [0.0] * n})
    return ad.inhouse_returns(f)


def test_compare_legs_passes_inside_the_gate_and_raises_outside_it():
    a = _frame([100.0, 100.10, 100.20])
    ok = _frame([100.0, 100.10, 100.205])          # 0.5bp apart on the last day
    st = ad.compare_legs(a, ok, D(2026, 7, 27), D(2026, 7, 29))
    assert st["ret_total_max_bp"].iat[0] < 1
    bad = _frame([100.0, 100.10, 100.30])          # ~10bp apart
    with pytest.raises(ad.AlpacaLegError, match="differs by"):
        ad.compare_legs(a, bad, D(2026, 7, 27), D(2026, 7, 29))


def test_compare_legs_refuses_different_ex_dates_even_when_returns_agree():
    a = _frame([100.0, 100.0, 100.0], [0.0, 0.0, 0.0])
    r = _frame([100.0, 100.0, 100.0], [0.0, 0.0, 0.0001])   # 0.01bp: inside the gate
    with pytest.raises(ad.AlpacaLegError, match="ex-dates differ"):
        ad.compare_legs(a, r, D(2026, 7, 27), D(2026, 7, 29))


# ------------------------------------------------------------ the splice

def test_continue_after_returns_only_post_seam_rows_priced_from_alpacas_own_seam_close():
    days = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
    stamps = [f"{d}T04:00:00Z" for d in days]
    alp = [bar(stamps[0], 100.0), bar(stamps[1], 100.10), bar(stamps[2], 100.205), bar(stamps[3], 100.40)]
    client = FakeClient([{"bars": {"HYG": alp}, "next_page_token": None}],
                        [{"corporate_actions": {}, "next_page_token": None}],
                        [D.fromisoformat(d) for d in days])
    # yfinance: same prices except the seam close is rounded to the cent
    yf_full = pd.DataFrame({"date": pd.to_datetime(days), "ticker": "HYG",
                            "close": [100.0, 100.10, 100.21, 100.40], "dividend": 0.0})
    rows, stats = ad.continue_after(yf_full, "2026-07-29", "2026-07-27", ohlc=False,
                                    client=client, end=D(2026, 7, 30))
    assert list(rows["date"]) == [pd.Timestamp("2026-07-30")]
    assert rows["ret_total"].iat[0] == pytest.approx(100.40 / 100.205 - 1, abs=0)
    assert rows["ret_total"].iat[0] != pytest.approx(100.40 / 100.21 - 1, abs=1e-9)
    assert stats["n"].iat[0] == 4


def test_continue_after_refuses_a_ticker_with_no_yfinance_row_on_the_seam():
    yf_full = pd.DataFrame({"date": pd.to_datetime(["2026-07-27"]), "ticker": "HYG",
                            "close": [100.0], "dividend": 0.0})
    with pytest.raises(ad.AlpacaLegError, match="seam date"):
        ad.continue_after(yf_full, "2026-07-29", "2026-07-27", ohlc=False,
                          client=FakeClient([], [], []), end=D(2026, 7, 30))
