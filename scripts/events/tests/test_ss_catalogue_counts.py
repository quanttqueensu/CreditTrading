"""Tests for the special-situations catalogue counts (no network: fakes only).

What is pinned, and why:
- the pre-event ADV window ends two sessions before the event and never reads the
  event's own sessions (a window that included the event day would count the
  event's own flow as "liquidity before it");
- the ADV pass cannot read 2023+ market data (the time holdout);
- the spin-off reconciliation drops CVR and warrant rows and backfilled events,
  each counted, rather than silently mixing them into a spin-off count.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.events import ss_catalogue_counts as sc


def _px(permno: int, n: int, start="2020-01-01"):
    d = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"permno": permno, "date": d, "dv": range(1, n + 1)})


def test_adv_window_ends_two_sessions_before_the_event():
    px = _px(1, 40)
    event_date = px["date"].iloc[30]                       # sessions 0..29 are before it
    ev = pd.DataFrame({"cls": ["x"], "permno": [1], "date": [event_date], "sub": ["COM"]})
    a = sc._adv_table(px, ev, lo=2, hi=22)
    # 22 sessions before -> indices 8..29; drop the last 2 -> 8..27 -> dv 9..28
    assert a["adv"].iloc[0] == pytest.approx(sum(range(9, 29)) / 20)


def test_adv_skips_events_without_enough_history():
    px = _px(1, 10)
    ev = pd.DataFrame({"cls": ["x"], "permno": [1], "date": [px["date"].iloc[9]], "sub": ["COM"]})
    assert sc._adv_table(px, ev, lo=2, hi=22).empty


def test_summary_shares_use_book_size_thresholds():
    a = pd.DataFrame({"cls": "x", "sub": "COM", "adv": [5e4, 2e5, 2e6, 2e7]})
    s = sc._summ(a).iloc[0]
    assert (s.share_adv_ge_100k, s.share_adv_ge_1m, s.share_adv_ge_10m) == (0.75, 0.5, 0.25)


def test_adv_window_is_before_the_time_holdout():
    assert sc.ADV_END < sc.TIME_HOLDOUT


class _FakeClient:
    _data = "data"

    def __init__(self, rows, active):
        self._rows, self._active = rows, active

    def assets(self, status="active"):
        return [{"symbol": s, "exchange": e} for s, e in self._active.items()]

    def _get(self, base, path, params):
        return {"corporate_actions": {"spin_offs": self._rows}, "next_page_token": None}


def test_spin_off_reconcile_counts_and_drops_cvr_warrant_and_backfill():
    rows = [
        {"source_symbol": "AAA", "new_symbol": "BBB", "ex_date": "2024-04-01"},   # kept
        {"source_symbol": "CCC", "new_symbol": "123CVR018", "ex_date": "2024-05-01"},  # CVR
        {"source_symbol": "DDD", "new_symbol": "DDDW", "ex_date": "2024-06-01"},  # warrant
        {"source_symbol": "EEE", "new_symbol": "FFF", "ex_date": "2022-08-02"},   # backfilled
        {"source_symbol": "AAA", "new_symbol": "BBB", "ex_date": "2024-04-01"},   # duplicate
    ]
    out = sc.spin_off_reconcile(_FakeClient(rows, {"AAA": "NYSE"}), years=(2024,))["2024"]
    assert out == {"raw_rows": 5, "cvr_or_warrant_rows": 2, "backfilled_rows": 1,
                   "kept_unique_source_exdate": 1, "kept_with_source_listed_today": 1}
