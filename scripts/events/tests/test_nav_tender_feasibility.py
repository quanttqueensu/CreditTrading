"""Tests for the NAV-tender pre-registration's zero-trial counts.

The period rule and the hedge route are the two pieces of this script that a
later trial script will repeat on real dates, so they are pinned here on
synthetic rows: a boundary that drifts by one session moves an event between
the fit and the sealed holdout, and a hedge route that falls back silently
would hide an unhedgeable class. No file outside the repo, no network.
"""
import math

import pandas as pd
import pytest

from scripts.events import nav_tender_feasibility as nf


def T(s):
    return pd.Timestamp(s)


def test_last_pnl_session_takes_the_later_of_results_and_pricing_plus_lag():
    # pricing Fri 2022-12-02; +5 sessions = Fri 2022-12-09; results earlier -> F = 12-09, exit 12-12
    assert nf.last_pnl_session(T("2022-12-05"), T("2022-12-02")) == T("2022-12-12")
    # results later than pricing + 5 -> F is the results session (Mon 12-19), exit Tue 12-20
    assert nf.last_pnl_session(T("2022-12-17"), T("2022-12-02")) == T("2022-12-20")


def test_last_pnl_session_raises_on_a_missing_date():
    with pytest.raises(nf.FeasibilityError):
        nf.last_pnl_session(pd.NaT, T("2022-12-02"))


def test_assign_period_boundaries():
    assert nf.assign_period(T("2022-11-01"), T("2022-12-30")) == "fit"
    assert nf.assign_period(T("2022-11-01"), T("2023-01-03")) == "gap"
    assert nf.assign_period(T("2023-01-03"), T("2024-12-31")) == "holdout"
    assert nf.assign_period(T("2024-11-20"), T("2025-01-02")) == "after_crsp"
    with pytest.raises(nf.FeasibilityError):
        nf.assign_period(T("2009-12-31"), T("2010-02-01"))


def _summary(shortable):
    return {"hedges": [{"symbol": s, "shortable": v} for s, v in shortable.items()]}


def test_hedge_route_prefers_alpaca_then_ibkr_and_never_invents_one():
    from scripts.events.cef_corp_action_census import HEDGE_ETF, HEDGE_ALTERNATES
    every = set(HEDGE_ETF.values()) | {s for v in HEDGE_ALTERNATES.values() for s in v}
    flags = {s: True for s in every}
    for s in ("MUB",) + HEDGE_ALTERNATES["muni"]:
        flags[s] = False
    ibkr = pd.DataFrame([{"symbol": "MUB", "available": 150000.0, "fee_rate_pct": 7.7}])
    r = nf.hedge_routes(_summary(flags), ibkr)
    assert r["high_yield"] == ("HYG", "alpaca", None)
    assert r["muni"] == ("MUB", "ibkr", 7.7)
    # no IBKR file: the muni class has no route, stated as 'none'
    assert nf.hedge_routes(_summary(flags), None)["muni"] == (None, "none", None)


def test_hedge_route_raises_when_a_declared_etf_was_never_read():
    with pytest.raises(nf.FeasibilityError):
        nf.hedge_routes(_summary({"HYG": True}), None)


def test_attach_episodes_raises_on_an_unmatched_day0_filing():
    nt = pd.DataFrame({"cik": [1], "ann_accession": ["A-1"]})
    ep = pd.DataFrame({"cik": [1], "kind": ["tender"], "first_accession": ["B-2"],
                       "last_date": [T("2020-01-01")]})
    with pytest.raises(nf.FeasibilityError):
        nf.attach_episodes(nt, ep)


def test_triggered_programme_window():
    nt = pd.DataFrame({"cik": [7, 7, 8], "ann_date": [T("2020-06-15"), T("2021-06-15"), T("2020-06-15")]})
    cond = pd.DataFrame({"cik": [7, 8], "outcome": ["triggered", "not_triggered"],
                         "window_end": [T("2020-05-31"), T("2020-05-31")]})
    got = nf.triggered_programme(nt, cond).tolist()
    assert got == [True, False, False]


def test_power_arithmetic():
    from statistics import NormalDist
    assert nf.per_event_power(0.0, 4.0, 100) == pytest.approx(NormalDist().cdf(-2.0))
    assert nf.clusters_needed(1.0, 2.0) == pytest.approx(2.8 ** 2 * 4)
    assert math.isfinite(nf.per_event_power(1.0, 4.0, 1))
