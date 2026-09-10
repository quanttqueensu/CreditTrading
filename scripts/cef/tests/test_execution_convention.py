"""The execution convention is shift(2), and it is load-bearing.

WHY THIS FILE EXISTS. From the day validate.py was written until 2026-09-10 it
scored the CEF battery at shift(1) -- entering at day t's close on day t's NAV,
which the fund publishes only AFTER that close. Every other number in the repo
is scored shift(2) (band_frontier.evaluate), so the headline validation was not
comparable to anything it was quoted beside.

The defect was FOUND on 2026-07-31, WRITTEN DOWN in docs/RESEARCH_STATE.md with
the line number and the measured cost (gross 1.26 -> 0.95, net at hold=5
0.82 -> 0.51), and STILL SURVIVED a 2026-09-10 commit that edited the same file
for another reason. A documented bug with a named line number was not enough.
That is what this file is for: the convention now fails a test if it moves.

These tests assert on BEHAVIOUR, not on source text. Grepping for ".shift(2)"
would pass on a file that shifted the wrong frame; planting a signal that only a
shift(1) book could monetise cannot be satisfied by anything except the correct
lag. Precedent: scripts/calibration_planted_lookahead.py does the same against
src/backtest.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/cef"))
sys.path.insert(0, str(REPO))

import validate as V  # noqa: E402
from src.backtest.guard import LookaheadError  # noqa: E402

N_DAYS, N_TICKERS = 600, 8
SEED = 20260910


def _panel(predict_lag: int):
    """Build a synthetic panel whose signal predicts EXACTLY one return step.

    `predict_lag` is the offset, in sessions from the decision date t, of the
    single daily return the signal foresees. A book that executes at shift(k)
    holds W[t] into the return dated t+k, so it monetises this panel if and only
    if predict_lag == k. Everything else in the panel is noise.

    This is synthetic data used to test whether a METHOD behaves -- the repo's
    one sanctioned use. It says nothing about the market.
    """
    rng = np.random.default_rng(SEED)
    idx = pd.bdate_range("2015-01-01", periods=N_DAYS)
    cols = [f"F{i}" for i in range(N_TICKERS)]

    ret = pd.DataFrame(rng.normal(0.0, 0.01, (N_DAYS, N_TICKERS)),
                       index=idx, columns=cols)
    px = 20.0 * (1.0 + ret).cumprod()

    # W[t] is built as -(z[t] - mean) normalised, so W[t] is proportional to
    # -z[t] demeaned. Setting z[t] = -ret[t + predict_lag] therefore makes W[t]
    # point exactly at the return dated t + predict_lag.
    fwd = ret.shift(-predict_lag)
    z = (-fwd).div(fwd.abs().max(axis=1).replace(0, np.nan), axis=0) * 3.0

    adv = pd.DataFrame(1e9, index=idx, columns=cols)
    return px, z.fillna(0.0), adv


def _gross_sharpe(predict_lag: int) -> float:
    px, z, adv = _panel(predict_lag)
    # vol_target=0 disables the vol scalar: it is a separate mechanism and would
    # only add noise to a lag measurement.
    d = V.run(px, z, adv, vol_target=0, start=str(px.index[0].date()))
    return V.sr(d.gross)


def test_exec_lag_is_two():
    """The constant itself. H1 fixes it at 2; it is not a tuning knob."""
    assert V.EXEC_LAG == 2


def test_signal_predicting_t_plus_2_is_captured():
    """Positive control: the harness DOES earn the return it can actually reach.

    Without this, test_signal_predicting_t_plus_1_is_not_captured would pass on a
    harness that was simply broken and earned nothing at any lag.

    SCOPE, measured not assumed: this control alone does NOT pin the lag. W is
    forward-filled HOLD-1 sessions, so a position decided at t is still open at
    t+2 under shift(1) as well, and this test was verified to keep passing when
    the lag was deliberately regressed to 1. It proves the harness scores
    something reachable; test_signal_predicting_t_plus_1_is_not_captured is the
    one that discriminates, and that one does fail under the regression.
    """
    assert _gross_sharpe(2) > 3.0, (
        "a signal that perfectly foresees the t+2 return -- the one an MOC fill "
        "at t+1's close actually earns -- was not captured; the harness is not "
        "scoring anything")


def test_signal_predicting_t_plus_1_is_not_captured():
    """THE regression test. This is the bug that shipped for six weeks.

    A signal that foresees only the t->t+1 return is worth nothing to us: the
    decision needs t's NAV, which publishes after t's close, so the earliest
    auction we can reach is t+1's and the first return we earn is t+2's. If this
    panel becomes profitable, the book is being scored at an entry price it
    cannot obtain.
    """
    assert _gross_sharpe(1) < 1.0, (
        "a signal that foresees ONLY the t->t+1 return was monetised. That "
        "return is unreachable: it requires trading at t's close on t's NAV, "
        "which publishes after that close. The execution lag has regressed to "
        "shift(1) -- see docs/RESEARCH_STATE.md on the 2026-07-31 measurement")


def test_guard_fires_if_the_lag_is_changed(monkeypatch):
    """The runtime assertion must actually raise, not just exist."""
    px, z, adv = _panel(2)
    monkeypatch.setattr(V, "EXEC_LAG", 1)
    with pytest.raises(LookaheadError, match="must be 2"):
        V.run(px, z, adv, vol_target=0, start=str(px.index[0].date()))


def test_guard_catches_a_mismatched_held_frame():
    """_assert_exec_lag compares positions against the index, not just the call.

    A resample or reindex that changes the row spacing between W and held would
    otherwise pass unnoticed.
    """
    idx = pd.bdate_range("2020-01-01", periods=50)
    W = pd.DataFrame(np.arange(50, dtype=float).reshape(50, 1),
                     index=idx, columns=["A"])
    V._assert_exec_lag(W, W.shift(2).fillna(0.0))          # correct: silent
    with pytest.raises(LookaheadError, match="execution lag is wrong"):
        V._assert_exec_lag(W, W.shift(1).fillna(0.0))      # off by one
