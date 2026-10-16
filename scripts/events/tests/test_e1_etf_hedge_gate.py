"""The E1 ETF-hedge gate's computations (`scripts/events/e1_etf_hedge_gate.py`), on synthetic inputs.

WHY THESE TESTS
---------------
* The windows are the trial discipline. The test window must end GUARD valid
  sessions before the announcement (so an upper-bound EDGAR date cannot leak
  the deal into it), and a window reaching 2023 must raise.
* `spans` must take the hedge's return over the SAME span as a target return
  that bridges a missing price, and must drop (and count) a bridge longer than
  CRSP's 10 periods rather than compound across it.
* `dimson` exists because a lagged target biases a lag-0 beta toward zero;
  it must recover the summed beta where OLS does not.
* `hedge_stats` must apply the ESTIMATION beta to the test window (out of
  sample), never the test window's own beta.
* N-PORT: month 1 is the earliest month of the quarter, percent becomes a
  decimal, a two-class filing raises, and the alignment check raises when the
  months are really in the other order.
* The gate: "at most X" includes X; a hedge must be shortable AND easy to
  borrow today AND on every earlier read; capacity is beta x $1m over ADV.
* The holdout guard raises on a universe name, and the sample loader on a
  count other than 167.
Synthetic inputs test the code, not the market. No network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import e1_etf_hedge_gate as g


def _series(rets, start="2015-01-02", permno=1, prc=10.0):
    d = pd.bdate_range(start, periods=len(rets))
    dsf = pd.DataFrame({"permno": permno, "date": d, "ret": rets,
                        "prc": [np.nan if pd.isna(r) else prc for r in rets], "vol": 1000.0})
    return g.series(dsf)[permno]


# ----------------------------------------------------------------- windows

def test_window_ends_guard_sessions_before_the_announcement():
    d = pd.bdate_range("2015-01-02", periods=600)
    ann = d[550]
    w = g.windows(d, ann, h=100, est=252, guard=42)
    s_est, s0, e = w
    assert e < ann
    assert ((d > e) & (d < ann)).sum() == 42          # exactly GUARD sessions between test end and A
    assert ((d > s0) & (d <= e)).sum() == 100          # test window = h spans
    assert ((d > s_est) & (d <= s0)).sum() == 252      # estimation window = EST spans


def test_window_too_short_is_none_not_a_shorter_window():
    d = pd.bdate_range("2015-01-02", periods=300)
    assert g.windows(d, d[-1], h=100, est=252, guard=42) is None


def test_window_reaching_the_time_holdout_raises():
    d = pd.bdate_range("2021-06-01", "2023-12-29")
    with pytest.raises(g.WindowError):
        g.windows(d, pd.Timestamp("2023-12-29"), h=50, est=100, guard=5)


# ------------------------------------------------------------------ spans

def test_span_bridging_a_missing_target_price_uses_the_same_hedge_span():
    T = _series([0.0, 0.01, np.nan, 0.02, 0.01], permno=1)
    H = _series([0.0, 0.001, 0.002, 0.003, 0.004], permno=2)
    a, b = T.index[1], T.index[4]
    df, drops = g.spans(T, H, a, b)
    assert len(df) == 2 and drops == {"long_gap": 0, "hedge_unpriced": 0}
    # the first span runs over two sessions: the hedge compounds both
    assert df["rH"].iloc[0] == pytest.approx(1.002 * 1.003 - 1)
    assert df["rT"].iloc[0] == pytest.approx(0.02)
    assert df["gap"].iloc[0] == 1


def test_span_longer_than_crsp_bridge_is_dropped_and_counted():
    rets = [0.0, 0.01] + [np.nan] * (g.MAX_GAP + 1) + [0.02, 0.01]
    T = _series(rets, permno=1)
    H = _series([0.001] * len(rets), permno=2)
    df, drops = g.spans(T, H, T.index[1], T.index[-1])
    assert drops["long_gap"] == 1
    assert np.isnan(g.cum(T, T.index[1], T.index[-1]))


def test_span_anchor_must_be_a_valid_target_date():
    T = _series([0.0, np.nan, 0.01], permno=1)
    H = _series([0.0, 0.0, 0.0], permno=2)
    with pytest.raises(g.WindowError):
        g.spans(T, H, T.index[1], T.index[2])


# --------------------------------------------------------- beta, blocks

def test_dimson_recovers_a_lagged_beta_that_ols_misses():
    rng = np.random.default_rng(0)
    rH = rng.normal(0, 0.01, 3000)
    lag = np.concatenate([[0.0], rH[:-1]])
    rT = 0.6 * rH + 0.6 * lag + rng.normal(0, 0.002, 3000)
    beta, beta_ols = g.dimson(rT[1:], rH[1:], lag[1:])
    assert beta == pytest.approx(1.2, abs=0.02)
    assert beta_ols == pytest.approx(0.6, abs=0.02)


def test_blocks_compound_and_drop_a_partial_block():
    rT = np.array([0.01] * 7)
    bT, bH = g.block_returns(rT, rT, block=5)
    assert len(bT) == 1 and bT[0] == pytest.approx(1.01 ** 5 - 1)


def test_hedge_stats_uses_the_estimation_beta_out_of_sample():
    rng = np.random.default_rng(1)
    n = 700
    d = pd.bdate_range("2015-01-02", periods=n)
    win = g.windows(d, d[-1], h=100, est=252, guard=42)
    rH = rng.normal(0, 0.005, n)
    beta = np.where(d <= win[1], 1.5, 0.5)          # the beta changes exactly where the test window starts
    rT = beta * rH + rng.normal(0, 0.0005, n)
    T, H = _series(rT, permno=1), _series(rH, permno=2)
    assert (T.index == d).all()
    rec = g.hedge_stats(T, H, win, h=100)
    assert rec["status"] == "ok"
    assert rec["beta"] == pytest.approx(1.5, abs=0.05)
    assert rec["beta_test"] == pytest.approx(0.5, abs=0.1)
    expect = rec["R_T_test"] - rec["beta"] * rec["R_H_test"]
    assert rec["resid_oos"] == pytest.approx(expect)
    assert rec["res_vol_hold"] < 0.2 * rec["unhedged_vol_hold"]


# ----------------------------------------------------------------- N-PORT

XML = """<edgarSubmission><genInfo><repPdEnd>2020-07-31</repPdEnd><repPdDate>2020-04-30</repPdDate></genInfo>
<returnInfo><monthlyTotReturns><monthlyTotReturn rtn1="2.41000000" rtn2="-8.82000000" rtn3="-2.36000000"/>
</monthlyTotReturns></returnInfo></edgarSubmission>"""


def test_nport_month_one_is_the_earliest_month_and_percent_becomes_decimal():
    rep, vals = g.parse_nport_returns(XML)
    s = g.nport_months(rep, vals)
    assert rep == pd.Timestamp("2020-04-30")
    assert s.index.tolist() == [pd.Timestamp("2020-02-29"), pd.Timestamp("2020-03-31"), pd.Timestamp("2020-04-30")]
    assert s.loc["2020-03-31"] == pytest.approx(-0.0882)


def test_nport_two_classes_raise():
    two = XML.replace("</monthlyTotReturns>",
                      '<monthlyTotReturn classId="C2" rtn1="1" rtn2="1" rtn3="1"/></monthlyTotReturns>')
    with pytest.raises(ValueError):
        g.parse_nport_returns(two)


def test_nport_alignment_check_raises_on_the_wrong_month_order():
    rng = np.random.default_rng(2)
    rH = rng.normal(0, 0.01, 520)
    H = _series(rH, start="2018-01-01", permno=2)
    months = pd.date_range("2018-03-31", "2019-12-31", freq="ME")
    hm = g.monthly_from_index(H, months)
    right = hm.dropna()
    assert g.nport_alignment_check({1: right}, {1: H})["corr_same_month"] > 0.99
    # The same returns two months late: what a reversed reading would produce.
    wrong = pd.Series(right.values[:-2], index=right.index[2:])
    with pytest.raises(ValueError):
        g.nport_alignment_check({1: wrong}, {1: H})


# ------------------------------------------------------------------ gate

def _flags(sym, short=True, easy=True):
    return pd.DataFrame([{"symbol": sym, "found": True, "shortable": short, "easy_to_borrow": easy}])


EMPTY_EARLY = pd.DataFrame(columns=["symbol", "read_utc", "shortable", "easy_to_borrow", "source"])


def _stats(k_ts, k_xs, beta=1.0):
    return {"X": {"k_ts": k_ts, "k_xs": k_xs, "beta_median": beta, "implied_clustered_t": 1.0}}


def test_gate_at_exactly_x_passes_and_above_fails():
    adv = pd.DataFrame([{"symbol": "X", "adv_median_usd": 1e9}])
    assert g.gate_verdict(_stats(0.5, 0.5), _flags("X"), EMPTY_EARLY, adv, x=0.5)["segment_pass"]
    assert not g.gate_verdict(_stats(0.5, 0.51), _flags("X"), EMPTY_EARLY, adv, x=0.5)["segment_pass"]


def test_gate_needs_easy_to_borrow_today_and_on_every_earlier_read():
    adv = pd.DataFrame([{"symbol": "X", "adv_median_usd": 1e9}])
    assert not g.gate_verdict(_stats(0.1, 0.1), _flags("X", easy=False), EMPTY_EARLY, adv)["segment_pass"]
    early = pd.DataFrame([{"symbol": "X", "read_utc": "2026-10-12", "shortable": False, "easy_to_borrow": False,
                           "source": "f"}])
    assert not g.gate_verdict(_stats(0.1, 0.1), _flags("X"), early, adv)["segment_pass"]


def test_gate_capacity_is_beta_times_one_million_over_adv():
    adv = pd.DataFrame([{"symbol": "X", "adv_median_usd": 150e6}])
    v = g.gate_verdict(_stats(0.1, 0.1, beta=1.5), _flags("X"), EMPTY_EARLY, adv, cap=0.01)
    assert v["per_hedge"]["X"]["participation_at_1m"] == pytest.approx(0.01)
    assert v["segment_pass"]                                     # exactly 1% passes
    adv2 = pd.DataFrame([{"symbol": "X", "adv_median_usd": 149e6}])
    assert not g.gate_verdict(_stats(0.1, 0.1, beta=1.5), _flags("X"), EMPTY_EARLY, adv2, cap=0.01)["segment_pass"]


def test_t_ceiling():
    assert g.t_ceiling_x(2.41) == pytest.approx(np.sqrt((2.41 / 2) ** 2 - 1))
    assert np.isnan(g.t_ceiling_x(1.9))


def test_state_etf_matching():
    assert g.state_etf("NUVEEN CALIFORNIA MUN VALUE FD") == "CMF"
    assert g.state_etf("BLACKROCK N Y MUN INCOME TR") == "NYF"
    assert g.state_etf("NUVEEN AMT FREE MUN VALUE FD") is None
    with pytest.raises(ValueError):
        g.state_etf("FUND CALIFORNIA NEW YORK")


# --------------------------------------------------------- holdout guards

def test_universe_name_in_the_sample_raises(monkeypatch):
    monkeypatch.setattr(g.ce, "universe", lambda: pd.DataFrame({"ticker": ["NZF"], "start": ["2002-01-01"]}))
    monkeypatch.setattr(g.ce, "universe_permnos", lambda nm: {"NZF": [999]})
    clean = pd.DataFrame({"ticker": ["AAA"], "acq": ["BBB"], "permno": [1], "nwperm": [2]})
    assert g.assert_no_universe(clean, None)["targets_checked"] == 1
    for bad in (dict(acq="NZF"), dict(nwperm=999), dict(ticker="NZF"), dict(permno=999)):
        with pytest.raises(AssertionError):
            g.assert_no_universe(clean.assign(**bad), None)


def test_sample_count_must_be_167(tmp_path):
    p = tmp_path / "s.csv"
    pd.DataFrame({"status": ["ok"] * 3, "ann": "2015-01-01", "completion": "2015-06-01",
                  "permno": [1, 2, 3], "nwperm": 9, "tdays_to_close": 100}).to_csv(p, index=False)
    with pytest.raises(ValueError):
        g.load_sample(p)


def test_effect_refuses_a_priced_deal_without_a_pair_return():
    s = pd.DataFrame({"cls": ["muni"] * 3, "pair_A1_to_close": [0.01, np.nan, 0.02], "nwperm": [1, 2, 3],
                      "ann": pd.to_datetime(["2015-01-01"] * 3)})
    with pytest.raises(ValueError):
        g.effect_by_segment(s)
