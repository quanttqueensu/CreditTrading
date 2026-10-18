"""The CEFConnect distribution-history parser (trial C4's third source, 2026-10-15).

Two records on one ex-date (TY books its regular and capital-gains distributions
separately) must be summed, never one of them dropped; a record without an
ex-date or a total must raise. Synthetic payloads: claims about the code.
"""
from __future__ import annotations

import pytest

from scripts.data.fetch_cefconnect_distributions import CefConnectDistError, parse, per_ex_date


def test_two_records_on_one_ex_date_are_summed():
    js = {"Data": [{"TotDiv": 2.0443, "ExDivDateDisplay": "12/12/2025"},
                   {"TotDiv": 0.2711, "ExDivDateDisplay": "12/12/2025"},
                   {"TotDiv": 0.29, "ExDivDateDisplay": "6/16/2025"}]}
    s = per_ex_date(parse(js, "TY")).set_index("ex_date")
    assert s.loc["2025-12-12", "cc_amount"] == pytest.approx(2.3154)
    assert s.loc["2025-12-12", "cc_records"] == 2 and s.loc["2025-06-16", "cc_records"] == 1


def test_a_record_without_a_total_or_an_ex_date_raises():
    with pytest.raises(CefConnectDistError):
        parse({"Data": [{"TotDiv": None, "ExDivDateDisplay": "1/2/2025"}]}, "X")
    with pytest.raises(CefConnectDistError):
        parse({"Data": [{"TotDiv": 0.1, "ExDivDateDisplay": ""}]}, "X")
    assert parse({"Data": []}, "X").empty
