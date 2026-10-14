"""The parts of the capacity / open-cross measurement that can be wrong silently.

WHY THESE. The note's two headline numbers -- how large a share of the closing
cross our orders are, and what the opening cross costs against the close --
both rest on reading "the cross" correctly off the consolidated tape. The
2026-10-12 note read the size of the primary's M (official close) print. On a
day with a round-lot cross that equals the cross; on a day without one it is
the size of the last eligible sale, which is not the cross at all. Each case
below is a shape measured on this book's own names (dates in the comments),
rebuilt as literal rows: a statement about the code, never about the market.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef import exec_capacity_open_cross as m

CLOSE = pd.Timestamp("2026-07-22T20:00:00Z")      # 16:00 ET
OPEN = pd.Timestamp("2026-07-22T13:30:00Z")       # 09:30 ET


def _p(x, c, p, s, t):
    return {"x": x, "c": c, "p": p, "s": s, "t": t}


def _tr(t, p, s, *codes):
    return {"t": t, "p": p, "s": s, "c": [" ", *codes]}


def test_round_cross_is_the_6_print_and_a_post_bell_straggler_is_not_part_of_it():
    # JFR 2026-07-22: 6 at +3.0418s, its M twin 7.5ms later. MHD 2026-07-29 showed a
    # continuous N print stamped 2.5ms after the bell; a window that starts at the
    # bell counts it into the cross and the tape check fails.
    auc = [_p("N", "6", 7.71, 5573, "2026-07-22T20:00:03.041816793Z"),
           _p("N", "M", 7.71, 5573, "2026-07-22T20:00:03.049358759Z"),
           _p("P", "M", 7.70, 100, "2026-07-22T20:00:00.2Z")]
    tape = [_tr("2026-07-22T20:00:00.002510995Z", 7.70, 100),
            _tr("2026-07-22T20:00:03.041816793Z", 7.71, 5573, "6"),
            _tr("2026-07-22T20:00:03.049358759Z", 7.71, 5573, "M")]
    cov = [["2026-07-22T20:00:00Z", "2026-07-22T20:01:00Z"]]
    x = m.classify_cross("close", auc, tape, CLOSE, cov)
    assert x["kind"] == "round" and x["shares"] == 5573 and x["check"] == "ok"


def test_an_odd_lot_cross_is_read_from_the_tape_not_from_the_M_size():
    # PCN 2021-04-07: no 6 print; the cross was 74 shares coded I at 16:00:02.0807,
    # and the M twin carried 270 -- the size of the 15:59:44 regular trade.
    close = pd.Timestamp("2021-04-07T20:00:00Z")
    auc = [_p("N", "M", 17.85, 270, "2021-04-07T20:00:02.081820416Z")]
    tape = [_tr("2021-04-07T19:59:44.957416448Z", 17.85, 270),
            _tr("2021-04-07T20:00:02.080695296Z", 17.85, 74, "I"),
            _tr("2021-04-07T20:00:02.081820416Z", 17.85, 270, "M")]
    cov = [["2021-04-07T20:00:00Z", "2021-04-07T20:01:00Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "odd" and x["shares"] == 74
    assert x["twin_size"] == 270 and x["shares"] != x["twin_size"], \
        "the M size is what the earlier note read; on this day it is not the cross"


def test_a_day_with_no_auction_trade_is_zero_shares_and_has_no_auction_price():
    # MHD 2021-04-07: no N trade after the bell; M = 100 at a TRF price.
    close = pd.Timestamp("2021-04-07T20:00:00Z")
    auc = [_p("N", "M", 16.285, 100, "2021-04-07T20:00:02.016422912Z")]
    tape = [_tr("2021-04-07T19:59:51.125273856Z", 16.31, 99, "I"),
            _tr("2021-04-07T20:00:02.016422912Z", 16.285, 100, "M")]
    cov = [["2021-04-07T20:00:00Z", "2021-04-07T20:01:00Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "none" and x["shares"] == 0 and np.isnan(x["price"])


def test_a_late_print_outside_the_fetched_tape_is_unknown_not_none():
    # PHK 2026-08-20: the primary's M printed at 16:10. Tape fetched only to 16:01.
    close = pd.Timestamp("2026-08-20T20:00:00Z")
    auc = [_p("N", "M", 5.0, 13138, "2026-08-20T20:10:00.001249957Z")]
    cov = [["2026-08-20T20:00:00Z", "2026-08-20T20:01:00Z"]]
    x = m.classify_cross("close", auc, [], close, cov)
    assert x["kind"] == "unknown"


def test_two_volume_prints_on_the_primary_raise():
    auc = [_p("N", "6", 7.71, 100, "2026-07-22T20:00:03Z"), _p("N", "6", 7.72, 200, "2026-07-22T20:00:04Z")]
    with pytest.raises(m.CrossError):
        m.classify_cross("close", auc, None, CLOSE)


def test_another_venues_print_is_never_the_cross():
    auc = [_p("P", "6", 7.71, 900, "2026-07-22T20:00:00.2Z"), _p("T", "M", 7.71, 100, "2026-07-22T20:00:00.3Z")]
    x = m.classify_cross("close", auc, None, CLOSE)
    assert x["kind"] == "missing"


def test_open_cross_excludes_continuous_prints_just_after_the_open():
    # PCN 2026-07-22: O and Q share a timestamp; a 172-share N print 3.8ms later.
    auc = [_p("N", "O", 11.78, 5301, "2026-07-22T13:30:01.178151782Z"),
           _p("N", "Q", 11.78, 5301, "2026-07-22T13:30:01.178151782Z")]
    tape = [_tr("2026-07-22T13:30:01.178151782Z", 11.78, 5301, "O"),
            _tr("2026-07-22T13:30:01.178151782Z", 11.78, 5301, "Q"),
            _tr("2026-07-22T13:30:01.181970739Z", 11.79, 172)]
    cov = [["2026-07-22T13:30:00Z", "2026-07-22T13:31:00Z"]]
    x = m.classify_cross("open", auc, tape, OPEN, cov)
    assert x["kind"] == "round" and x["shares"] == 5301 and x["check"] == "ok"


def test_last_valid_quote_skips_crossed_and_ignores_the_boundary():
    b = pd.Timestamp("2026-07-22T13:30:00Z")
    qs = [{"t": "2026-07-22T13:29:00Z", "bp": 10.0, "ap": 10.2},
          {"t": "2026-07-22T13:29:30Z", "bp": 10.3, "ap": 10.1},       # crossed: skipped
          {"t": "2026-07-22T13:30:00Z", "bp": 11.0, "ap": 11.1}]       # at the boundary: not before it
    q = m.last_valid_quote(qs, b)
    assert q["mid"] == pytest.approx(10.1) and q["n_crossed"] == 1 and q["n"] == 2
    assert q["hs_bp"] == pytest.approx(0.1 / 10.1 * 1e4)
    assert m.last_valid_quote(qs[1:2], b) is None


def test_dislocation_sign_and_size():
    s, a = m.dislocation_bp(10.1, 10.0)
    assert s == pytest.approx(100.0) and a == pytest.approx(100.0)
    s, a = m.dislocation_bp(9.9, 10.0)
    assert s == pytest.approx(-100.0) and a == pytest.approx(100.0)
    with pytest.raises(ValueError):
        m.dislocation_bp(10.0, np.nan)


def test_weighted_median_and_capital_scaling():
    assert m.weighted_median([1, 2, 3], [1, 1, 1]) == 2
    assert m.weighted_median([1, 2, 100], [1, 1, 10]) == 100
    assert m.capital_for(0.10, 0.02, 100_000) == pytest.approx(500_000)
    assert m.capital_for(0.10, 0.0, 100_000) == np.inf


def test_backtest_orders_fill_the_session_after_the_decision_in_whole_shares():
    idx = pd.to_datetime(["2022-12-27", "2022-12-28", "2022-12-29", "2022-12-30"])
    H = pd.DataFrame({"AAA": [0.10, 0.10, 0.0501, 0.20], "BBB": [0.0, -0.00001, -0.05, -0.05]}, index=idx)
    px = pd.DataFrame({"AAA": [10.0, 10.0, 10.0, 10.0], "BBB": [20.0, 20.0, 20.0, 20.0]}, index=idx)
    B = m.backtest_orders(H, px, 100_000)
    # decided 12-27 (from flat): AAA 0.10 -> 1000 sh, fills 12-28
    r = B[(B.ticker == "AAA") & (B.decided == idx[0])].iloc[0]
    assert r.fill == idx[1] and r.shares == 1000 and r.side == "buy"
    # BBB's 0.00001 is 0.05 shares: rounds to 0 and is not an order
    assert not ((B.ticker == "BBB") & (B.decided == idx[1])).any()
    # the last decision (12-30) has no fill session inside H: dropped, never dated 2023
    assert B.decided.max() == idx[2] and B.fill.max() == idx[3]
    px2 = px.copy()
    px2.loc[idx[2], "AAA"] = np.nan
    with pytest.raises(ValueError):
        m.backtest_orders(H, px2, 100_000)


def test_participation_never_divides_by_a_zero_or_unknown_cross():
    orders = pd.DataFrame({"date": ["d1", "d2", "d3"], "ticker": ["A", "A", "A"], "shares": [10.0, 10.0, 10.0]})
    cross = pd.DataFrame({"date": ["d1", "d2"], "ticker": ["A", "A"], "kind": ["round", "none"],
                          "shares": [100.0, 0.0]})
    P = m.participation(orders, cross, on="date").set_index("date")
    assert P.at["d1", "part"] == pytest.approx(0.10)
    assert np.isinf(P.at["d2", "part"])
    assert np.isnan(P.at["d3", "part"]) and P.at["d3", "kind"] == "missing"


def test_a_long_gap_between_the_6_print_and_its_M_twin_is_still_one_cross():
    # PDI 2026-07-21: 6 at 16:00:03.205, M 104ms later; nothing else on N between.
    # A window that ends a few ms after the 6 (or starts a few ms before the M)
    # misses it and reports a mismatch that is not there.
    close = pd.Timestamp("2026-07-21T20:00:00Z")
    auc = [_p("N", "6", 16.29, 4408, "2026-07-21T20:00:03.205078498Z"),
           _p("N", "M", 16.29, 4408, "2026-07-21T20:00:03.309396804Z")]
    tape = [_tr("2026-07-21T20:00:03.205078498Z", 16.29, 4408, "6"),
            _tr("2026-07-21T20:00:03.309396804Z", 16.29, 4408, "M")]
    cov = [["2026-07-21T20:00:00Z", "2026-07-21T20:01:00Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "round" and x["check"] == "ok"


def test_a_legacy_close_printed_minutes_late_is_read_from_the_extra_tape_window():
    # PDI 2016-01-04: legacy NYSE printed the 6 at 16:02:01.425 (no M before
    # 2020-11-04); the tape repeats a same-size 6 9.9ms later. The fetch adds a
    # [print - 2s, print + 1s] window, so the cross is covered and checked.
    close = pd.Timestamp("2016-01-04T21:00:00Z")
    auc = [_p("N", "6", 27.74, 2587, "2016-01-04T21:02:01.425Z")]
    tape = [{"t": "2016-01-04T21:02:01.425Z", "p": 27.74, "s": 2587, "c": ["6"]},
            {"t": "2016-01-04T21:02:01.4349Z", "p": 27.74, "s": 2587, "c": ["6"]}]
    cov = [["2016-01-04T21:00:00Z", "2016-01-04T21:01:00Z"],
           ["2016-01-04T21:01:59.425Z", "2016-01-04T21:02:02.425Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "round" and x["shares"] == 2587 and x["check"] == "ok"


def test_a_late_M_with_a_size_but_no_primary_trade_is_no_cross():
    # PHK 2026-08-20: nothing on N after the bell; at 16:10 a size-0 "9"
    # (corrected consolidated close) and an M claiming 13,138 shares.
    close = pd.Timestamp("2026-08-20T20:00:00Z")
    auc = [_p("N", "M", 4.50, 13138, "2026-08-20T20:10:00.001249957Z")]
    tape = [_tr("2026-08-20T20:10:00.001231735Z", 4.50, 0, "9"),
            _tr("2026-08-20T20:10:00.001249957Z", 4.50, 13138, "M")]
    cov = [["2026-08-20T20:00:00Z", "2026-08-20T20:01:00Z"],
           ["2026-08-20T20:09:58.001249Z", "2026-08-20T20:10:01.001249Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "none" and x["shares"] == 0 and x["twin_size"] == 13138


def test_no_6_and_no_M_is_unknown_not_a_zero_cross():
    # Before 2020-11-04 NYSE published no M. PDO did not list until 2021, so on
    # 2016-01-04 it has no print and no tape: that is not a day with a zero cross.
    close = pd.Timestamp("2016-01-04T21:00:00Z")
    cov = [["2016-01-04T21:00:00Z", "2016-01-04T21:01:00Z"]]
    assert m.classify_cross("close", [], [], close, cov)["kind"] == "unknown"
    odd = [{"t": "2016-01-04T21:00:02Z", "p": 10.0, "s": 40, "c": ["I"]}]
    x = m.classify_cross("close", [], odd, close, cov)
    assert x["kind"] == "odd" and x["shares"] == 40


def test_a_6_print_repeated_on_the_tape_is_one_cross_printed_twice():
    # 2020-11 -> 2022: the tape often repeats the 6 print (same size, ~10ms
    # later) before the M twin. Summing the window would double the cross.
    close = pd.Timestamp("2021-06-01T20:00:00Z")
    auc = [_p("N", "6", 10.0, 500, "2021-06-01T20:00:02.100Z"),
           _p("N", "M", 10.0, 500, "2021-06-01T20:00:02.200Z")]
    tape = [_tr("2021-06-01T20:00:02.100Z", 10.0, 500, "6"),
            _tr("2021-06-01T20:00:02.110Z", 10.0, 500, "6"),
            _tr("2021-06-01T20:00:02.200Z", 10.0, 500, "M")]
    cov = [["2021-06-01T20:00:00Z", "2021-06-01T20:01:00Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "round" and x["shares"] == 500 and x["check"] == "ok_twice"
    # a different-size second print is NOT a repeat: it stays a mismatch
    tape[1] = _tr("2021-06-01T20:00:02.110Z", 10.0, 300, "6")
    assert m.classify_cross("close", auc, tape, close, cov)["check"] == "mismatch"


def test_coverage_joins_overlapping_windows_but_not_gaps():
    lo, hi = pd.Timestamp("2021-06-01T20:00:57Z"), pd.Timestamp("2021-06-01T20:01:00.5Z")
    joined = [["2021-06-01T20:00:00Z", "2021-06-01T20:01:00Z"], ["2021-06-01T20:00:58Z", "2021-06-01T20:01:02Z"]]
    gapped = [["2021-06-01T20:00:00Z", "2021-06-01T20:01:00Z"], ["2021-06-01T20:01:00.2Z", "2021-06-01T20:01:02Z"]]
    assert m._covered(joined, lo, hi)
    assert not m._covered(gapped, lo, hi)


def test_a_late_M_does_not_stretch_the_window_of_a_round_cross():
    # 2021-04-16: every name's 6 printed at 16:00:02, its M at 16:10. The tape
    # between 16:01 and 16:09:58 was never fetched; the cross is still checkable.
    close = pd.Timestamp("2021-04-16T20:00:00Z")
    auc = [_p("N", "6", 11.98, 3689, "2021-04-16T20:00:02.107510272Z"),
           _p("N", "M", 11.98, 3689, "2021-04-16T20:10:00.001298944Z")]
    tape = [_tr("2021-04-16T20:00:02.107510272Z", 11.98, 3689, "6"),
            _tr("2021-04-16T20:10:00.001298944Z", 11.98, 3689, "M")]
    cov = [["2021-04-16T20:00:00Z", "2021-04-16T20:01:00Z"],
           ["2021-04-16T20:09:58.001167Z", "2021-04-16T20:10:01.002123Z"]]
    x = m.classify_cross("close", auc, tape, close, cov)
    assert x["kind"] == "round" and x["check"] == "ok"
