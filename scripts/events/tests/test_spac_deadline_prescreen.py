"""Tests for the SPAC deadline-only D4 pre-screen (scripts/events/spac_deadline_prescreen.py).

Synthetic frames only: these test the METHOD (membership without lookahead, the
shift(2) exit after a deal announcement, the terminal payout, the trade-price
rule, the holdout cut, the exit arithmetic, the D4 rule and the Dimson sum),
never a claim about the market. Nothing here opens a socket.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef.band_frontier import evaluate
from scripts.events import spac_deadline_prescreen as S

pd.set_option("compute.use_numexpr", False)

DAYS = pd.bdate_range("2022-11-01", "2022-12-30")


def _links(permno=1, deal_end=None, status="live"):
    return pd.DataFrame({"cik": [1], "permno": [permno], "status": [status],
                         "deal_end": [pd.Timestamp(deal_end) if deal_end else pd.NaT]})


def _no_delist():
    return pd.DataFrame(columns=["permno", "delistingdt", "pay_day", "V"]).astype(
        {"permno": int, "delistingdt": "datetime64[ns]", "pay_day": "datetime64[ns]", "V": float})


# ------------------------------------------------------------------ membership and the shift(2) exit

def test_membership_starts_at_first_trade_and_ends_on_the_425_date():
    T = pd.DataFrame({1: np.r_[np.nan, np.nan, np.full(len(DAYS) - 2, 10.0)]}, index=DAYS)
    a = DAYS[10]
    M, spans = S.membership(_links(deal_end=a), T, _no_delist())
    assert not M[1].iloc[:2].any()                 # no trade yet: nothing to buy at
    assert M[1].iloc[2:10].all()                   # member until the day before the 425
    assert not M[1].iloc[10:].any()                # the decide on the 425 date sets the weight to zero
    assert spans["leave"].iloc[0] == a


def test_a_425_exits_after_the_next_session_under_shift2():
    """Decide on the 425 date a: the last return earned is a+1, never a+2 (band_frontier.evaluate)."""
    T = pd.DataFrame({1: np.full(len(DAYS), 10.0)}, index=DAYS)
    a = 10
    M, _ = S.membership(_links(deal_end=DAYS[a]), T, _no_delist())
    R = pd.DataFrame({1: np.zeros(len(DAYS))}, index=DAYS)
    R.iloc[a + 1, 0] = 0.07                        # the session after the announcement: still held
    R.iloc[a + 2, 0] = 0.50                        # two sessions after: already sold
    pnl = evaluate(S.ew_weights(M), R)["pnl"]
    assert pnl.iloc[a + 1] == pytest.approx(0.07)
    assert pnl.iloc[a + 2] == 0.0


def test_membership_never_reads_a_future_event():
    """Membership at t is the same whether or not the frame extends past t (no lookahead)."""
    T = pd.DataFrame({1: np.full(len(DAYS), 10.0)}, index=DAYS)
    full, _ = S.membership(_links(deal_end=DAYS[30]), T, _no_delist())
    cut, _ = S.membership(_links(deal_end=DAYS[30]), T.iloc[:20], _no_delist())
    assert full.iloc[:20].equals(cut)


# ------------------------------------------------------------------ the terminal payout

def _delist(permno, day, prc, delret):
    d = pd.DataFrame({"permno": [permno], "delistingdt": [day], "deldtprc": [prc], "delret": [delret]})
    return S.delistings(DAYS, d)


def test_terminal_value_is_booked_on_the_session_after_delisting():
    T = pd.DataFrame({1: np.full(len(DAYS), 10.0)}, index=DAYS)
    k = 20
    T.iloc[k + 1:, 0] = np.nan                     # no price after the delisting date
    dl = _delist(1, DAYS[k], 10.0, 0.01)
    M, _ = S.membership(_links(status="liquidated"), T, dl)
    assert M[1].iloc[k - 1] and not M[1].iloc[k]   # the last decide that can still be filled is k-1
    R, n = S.return_matrix(T, M, dl)
    assert n == {"terminal_returns_booked": 1, "terminal_returns_missing": 0}
    assert R.iloc[k + 1, 0] == pytest.approx(0.01)
    assert evaluate(S.ew_weights(M), R)["pnl"].iloc[k + 1] == pytest.approx(0.01)


def test_missing_delret_is_counted_not_invented():
    T = pd.DataFrame({1: np.full(len(DAYS), 10.0)}, index=DAYS)
    dl = _delist(1, DAYS[20], 10.0, np.nan)
    M, _ = S.membership(_links(), T, dl)
    R, n = S.return_matrix(T, M, dl)
    assert n == {"terminal_returns_booked": 0, "terminal_returns_missing": 1}
    assert R.iloc[21, 0] == 0.0                    # the carried price, no payout added


def test_a_payout_after_the_deal_exit_is_not_booked():
    T = pd.DataFrame({1: np.full(len(DAYS), 10.0)}, index=DAYS)
    dl = _delist(1, DAYS[30], 10.0, 0.5)
    M, _ = S.membership(_links(deal_end=DAYS[10]), T, dl)
    R, n = S.return_matrix(T, M, dl)
    assert n["terminal_returns_booked"] == 0


# ------------------------------------------------------------------ data rules

def test_quote_midpoint_is_never_a_trade_and_wide_quotes_are_not_a_market():
    px = pd.DataFrame({"permno": [1, 1, 1], "date": DAYS[:3], "prc": [10.0, -10.05, 10.1],
                       "bid": [9.99, 10.0, 7.0], "ask": [10.01, 10.1, 15.0]})
    pp = S.price_panels(px)
    assert np.isnan(pp["T"].iloc[1, 0])            # negative prc: no trade that day
    assert pp["Q"].iloc[1, 0] == pytest.approx(10.05)
    assert np.isnan(pp["Q"].iloc[2, 0])            # 7 / 15 is not a market on a $10 claim


def test_delistings_cut_the_holdout_before_use():
    d = pd.DataFrame({"permno": [1, 2, 3], "delistingdt": [DAYS[-2], DAYS[-1], pd.Timestamp("2023-02-01")],
                      "deldtprc": [10.0, 10.0, 10.0], "delret": [0.0, 0.0, 0.0]})
    out = S.delistings(DAYS, d)
    assert out["permno"].tolist() == [1]           # 2 pays in 2023, 3 delists in 2023


def test_holdout_guard_raises_on_2023():
    S._holdout_guard(DAYS, "fit")
    with pytest.raises(S.PrescreenError):
        S._holdout_guard(pd.DatetimeIndex(["2023-01-03"]), "x")


# ------------------------------------------------------------------ arithmetic and the D4 rule

def test_deadline_only_terms():
    assert S.deadline_only_terms(0.02, 365, 0, 0.0) == pytest.approx(0.02)
    # entry 30bp; half the exits are sales at 30bp that also give up 0.5%
    assert S.deadline_only_terms(0.02, 365, 30, 0.5, 0.005) == pytest.approx(0.02 - 0.003 - 0.5 * 0.008)
    # a shorter hold amortises the same legs over fewer days
    assert S.deadline_only_terms(0.02, 182.5, 30, 0.0) == pytest.approx(0.02 - 0.006)
    with pytest.raises(S.PrescreenError):
        S.deadline_only_terms(0.02, 0, 30, 0.5)


def test_d4_verdict():
    row = {"alpha_t": 3.1, "beta_mkt": 0.05, "beta_hy": -0.02, "beta_term": 0.0}
    assert S.d4_verdict(row)["pass"]
    assert not S.d4_verdict({**row, "beta_mkt": 0.11})["pass"]
    assert not S.d4_verdict({**row, "alpha_t": 2.99})["pass"]
    assert S.d4_verdict({**row, "beta_hy": -0.2})["worst_beta"] == "hy"


def test_dimson_sum_recovers_a_beta_hidden_by_a_stale_price():
    """A series that prices the factor a day late shows ~0 contemporaneous beta; the Dimson sum finds it."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2015-01-01", periods=1500)
    F = pd.DataFrame({"mkt": rng.normal(0, 0.01, len(idx)), "hy": rng.normal(0, 0.004, len(idx)),
                      "term": rng.normal(0, 0.003, len(idx))}, index=idx)
    y = 0.3 * F["mkt"].shift(1) + rng.normal(0, 0.002, len(idx))
    r = S.dimson(y.dropna(), F, ["mkt", "hy", "term"], 2, 5, 252)
    assert abs(r["beta_mkt_l0"]) < 0.05
    assert r["beta_mkt"] == pytest.approx(0.3, abs=0.03)
