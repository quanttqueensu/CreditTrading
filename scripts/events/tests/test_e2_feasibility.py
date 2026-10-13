"""E2 feasibility: the holdout's last day 0, the pre-event ADV, the issuer-day
collapse, and the date-range arguments added to convert_issuance.build_events.

Synthetic frames only: these test the counting code, never a market claim.
Nothing here reads R2 or Alpaca (the root conftest blocks the network).
"""
import pandas as pd
import pytest

from scripts.events import convert_issuance as ci
from scripts.events import e2_feasibility as e2


def test_last_holdout_d0_keeps_day_plus_5_inside_crsp():
    # 2024-12-23 (Mon): +1 Dec 24, +2 Dec 26, +3 Dec 27, +4 Dec 30, +5 Dec 31.
    assert e2.last_holdout_d0(pd.Timestamp("2024-12-31")) == pd.Timestamp("2024-12-23")
    # a CRSP end on a holiday falls back to the session before it
    assert e2.last_holdout_d0(pd.Timestamp("2024-12-25")) == pd.Timestamp("2024-12-17")


def test_adv_before_day0_uses_only_prior_sessions_and_never_passes_unmeasured():
    dates = pd.bdate_range("2020-01-01", periods=100)
    dv = pd.Series(range(100), dtype=float)
    pv = pd.DataFrame({"permno": 1, "date": dates, "prc": -1.0, "vol": dv})   # |prc| used
    ev = pd.DataFrame({"permno": [1, 1, 2], "d0": [dates[70], dates[10], dates[70]]})
    adv = e2.adv_before(ev, pv)
    assert adv.iloc[0] == pytest.approx(dv.iloc[70 - 63:70].mean())   # sessions 7..69: before day 0
    assert pd.isna(adv.iloc[1])                                        # 10 prior sessions < 21
    assert pd.isna(adv.iloc[2])                                        # no price history at all


def test_spec_b_keeps_one_row_per_issuer_day():
    m = pd.DataFrame({"c6": ["X", "X", "X", "Y"], "permno": [1, 2, 1, 3],
                      "d0": pd.to_datetime(["2020-01-02", "2020-01-02", "2020-02-03", "2020-01-02"])})
    assert len(e2.spec_b(m)) == 3


def test_build_events_range_defaults_to_the_study_and_widens_on_request(monkeypatch):
    uni = pd.DataFrame({"cusip_id": ["AAA111AA1", "BBB222BB2"],
                        "first_dt": pd.to_datetime(["2015-03-01", "2023-06-01"]), "ever144a": 1})
    ft = pd.DataFrame({"cusip_id": ["AAA111AA1", "BBB222BB2"],
                       "d0": pd.to_datetime(["2015-03-02", "2023-06-02"])})
    names = pd.DataFrame({"permno": [10, 20], "namedt": pd.to_datetime(["2000-01-01", "2000-01-01"]),
                          "nameenddt": pd.to_datetime(["2024-12-31", "2024-12-31"]),
                          "ncusip": ["AAA11110", "BBB22220"], "shrcd": [11, 11],
                          "ticker": ["AAA", "BBB"], "comnam": ["A CO", "B CO"]})
    monkeypatch.setattr(ci, "pull_universe", lambda flag, refresh: uni)
    monkeypatch.setattr(ci, "pull_first_trades", lambda flag, u, refresh: ft)
    monkeypatch.setattr(ci, "pull_names", lambda refresh: names)
    assert ci.build_events("Y", False)["ticker"].tolist() == ["AAA"]
    wide = ci.build_events("Y", False, d0_end=pd.Timestamp("2024-12-23"))
    assert wide["ticker"].tolist() == ["AAA", "BBB"]
