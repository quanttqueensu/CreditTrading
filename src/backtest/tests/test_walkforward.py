"""Walk-forward tests.

The centrepiece is the CLAIRVOYANCE TRAP (see `_regime_panel`): a market
built so that a runner which fits on the future scores brilliantly and an
honest expanding-window runner necessarily loses money. Any leak in the
runner turns the sign of the out-of-sample path from negative to positive,
so "no leak" is a testable claim rather than a hopeful comment.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import guard, walkforward as wf
from src.backtest.tests.conftest import make_panel, zero_rf

REGIME = 60          # trading days per regime
N_REGIMES = 8
DAILY = 0.002        # winner earns +0.2%/day, loser -0.2%/day


def _regime_panel():
    """Two assets whose leadership flips every REGIME days.

    Regime r (0-indexed): HYG wins when r is even, JNK wins when r is odd.
    The winner earns +DAILY every day of the regime, the loser -DAILY.

    Why this is a trap: a momentum fit on the just-finished regime always
    picks the asset that is about to LOSE for the whole next regime. So the
    honest walk-forward path is systematically negative. A runner that let
    the fit see its own out-of-sample window would instead pick the coming
    winner every time and print a spectacular positive path.
    """
    n = REGIME * N_REGIMES
    hyg, jnk = np.empty(n), np.empty(n)
    for i in range(n):
        hyg_wins = (i // REGIME) % 2 == 0
        hyg[i] = DAILY if hyg_wins else -DAILY
        jnk[i] = -DAILY if hyg_wins else DAILY
    return make_panel({"HYG": hyg, "JNK": jnk})


def _fit_trailing_winner(train_panel, window):
    """Honest fit: pick the better asset over the last REGIME days of the
    data we are ALLOWED to see. Uses train_panel only."""
    trailing = train_panel.tail(REGIME)
    total = (1.0 + trailing).prod() - 1.0
    return {"pick": str(total.idxmax()), "edge": float(total.max())}


def _apply_hold_pick(params, panel, window):
    """Hold the chosen asset at 1.0 across the whole slice we were given."""
    w = pd.DataFrame(0.0, index=panel.index, columns=["HYG", "JNK"])
    w[params["pick"]] = 1.0
    return w


# ---------------------------------------------------------------------------
# The leak test
# ---------------------------------------------------------------------------

def test_walkforward_does_not_leak(costs_simple):
    """The honest runner must LOSE on the trap. Losing is the proof."""
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
        name="trap (honest)", verbose=False)

    total = float((1.0 + res.net).prod() - 1.0)
    assert total < 0, (
        f"walk-forward earned {total:+.2%} on a market where fitting on the "
        "past guarantees holding the wrong asset — parameters are reaching "
        "data from after their fit window")

    # every window picked the asset that then lost: each OOS block is ~-11.3%
    per_window = wf.summarize_windows(res, verbose=False)
    assert (per_window["oos_return"] < 0).all()
    assert total < -0.40      # (1-0.002)^420 - 1 = -57%


def test_a_leak_would_be_visible_in_this_test(costs_simple):
    """Power check for the test above.

    Same market, same apply, but a CHEATING fit that closes over the full
    panel and looks at the window it is about to trade. If the trap had no
    teeth this would also come out negative; it comes out strongly positive,
    which is what makes the previous test's negative result meaningful.
    """
    rets = _regime_panel()

    def cheating_fit(train_panel, window):
        future = rets.loc[window.oos_start:window.oos_end]   # not allowed!
        total = (1.0 + future).prod() - 1.0
        return {"pick": str(total.idxmax())}

    res = wf.run_walkforward(
        rets, cheating_fit, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
        name="trap (cheating)", verbose=False)

    total = float((1.0 + res.net).prod() - 1.0)
    assert total > 1.0, "the trap should richly reward a clairvoyant fit"


# ---------------------------------------------------------------------------
# The APPLY-side leak (the fit-side trap above cannot see this one)
# ---------------------------------------------------------------------------

def _cheating_apply(params, panel, window):
    """A leak on the apply side, and an easy one to write by accident.

    It ignores the honestly-fitted params and picks from ``panel.tail(REGIME)``
    — but the runner hands apply history through the window's OOS end, so
    that tail IS the window it is about to trade. Every row in the window is
    therefore built from its own future.
    """
    total = (1.0 + panel.tail(REGIME)).prod() - 1.0
    w = pd.DataFrame(0.0, index=panel.index, columns=["HYG", "JNK"])
    w[str(total.idxmax())] = 1.0
    return w


def test_an_apply_that_peeks_at_its_own_window_is_caught(costs_simple):
    """Regression test for the hole that made this audit necessary.

    fit() truncation cannot see this leak: fit here is honest and its panel
    really does stop at fit_end. The leak lives entirely in apply(), which
    uses the warm-up history it is legitimately given for rows it must not
    use it for. The causality replay is what catches it.
    """
    rets = _regime_panel()
    with pytest.raises(guard.LookaheadError, match="not causal"):
        wf.run_walkforward(
            rets, _fit_trailing_winner, _cheating_apply, costs_simple,
            min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
            name="trap (apply-side leak)", verbose=False)


def test_the_apply_side_leak_would_otherwise_flip_the_sign(costs_simple):
    """Power check for the test above — and the reason it is not optional.

    With the audit disabled, that same apply() turns the honest path's heavy
    loss into a large profit and raises nothing. So the audit is not
    decoration: it is the only thing standing between this harness and a
    strategy result that looks spectacular for the worst possible reason.
    """
    rets = _regime_panel()

    honest = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)
    with pytest.warns(UserWarning, match="NO automated look-ahead protection"):
        leaked = wf.run_walkforward(
            rets, _fit_trailing_winner, _cheating_apply, costs_simple,
            min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
            check_causality=False, verbose=False)

    honest_total = float((1.0 + honest.net).prod() - 1.0)
    leaked_total = float((1.0 + leaked.net).prod() - 1.0)
    assert honest_total < -0.40      # honest walk-forward must lose
    assert leaked_total > 1.0        # the leak pays spectacularly
    assert leaked.meta["causality_checked"] is False


def test_an_honest_apply_passes_the_audit_and_probes_are_recorded(costs_simple):
    """The audit must not cry wolf, and must show its work: a clean run
    records how many rows it actually replayed."""
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    assert res.meta["causality_checked"] is True
    assert res.meta["causality_probes"] >= len(res.windows)


def test_the_audit_probes_rows_where_a_leak_would_be_visible(costs_simple):
    """A probe at a row dated oos_end removes no future and so can never
    fail. Those rows must not be counted as evidence."""
    rets = _regime_panel()
    windows = wf.make_windows(rets.index, min_train=REGIME, step=REGIME)
    w = windows[0]
    piece_index = rets.index[(rets.index >= w.fit_end) &
                             (rets.index <= w.oos_end)]

    probes = wf._probe_dates(piece_index, w.oos_end, 3)
    assert len(probes) == 3
    assert all(p < w.oos_end for p in probes)
    assert probes[0] == w.fit_end          # earliest row: most future withheld
    # a piece consisting only of the unprobeable row yields no false comfort
    assert wf._probe_dates(pd.DatetimeIndex([w.oos_end]), w.oos_end, 3) == []


def test_the_audit_catches_an_off_by_one_peek(costs_simple):
    """The leak that actually happens in practice.

    Not a cartoon cheat like _cheating_apply — just a signal shifted the
    wrong way, so each row is built from tomorrow's return. It contaminates
    most rows, and it is invisible to every other layer in the harness: the
    fit is honest, the entitlement slice is satisfied, and the weights look
    entirely ordinary.
    """
    rets = _regime_panel()

    def peeking_apply(params, panel, window):
        # signal = "was HYG up?", but shifted -1: row t sees day t+1
        sig = (panel["HYG"] > 0).astype(float).shift(-1).fillna(0.0)
        return pd.DataFrame({"HYG": sig, "JNK": 1.0 - sig})

    with pytest.raises(guard.LookaheadError, match="not causal"):
        wf.run_walkforward(
            rets, _fit_trailing_winner, peeking_apply, costs_simple,
            min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
            verbose=False)


def test_the_audit_reports_which_row_and_column_moved(costs_simple):
    """A leak report has to be actionable: which row, which column, and what
    the weight was with and without the future."""
    rets = _regime_panel()
    with pytest.raises(guard.LookaheadError) as excinfo:
        wf.run_walkforward(
            rets, _fit_trailing_winner, _cheating_apply, costs_simple,
            min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
            verbose=False)

    msg = str(excinfo.value)
    assert "window 0" in msg
    assert "truncated at its own date" in msg
    assert "HYG" in msg or "JNK" in msg


# ---------------------------------------------------------------------------
# The guard must never certify itself
# ---------------------------------------------------------------------------

def test_runner_never_fabricates_info_dates(costs_simple, monkeypatch):
    """info_dates derived from weights.index compares the index against
    itself, so assert_lagged cannot fail and the engine's own "no info_dates"
    warning is suppressed — an unchecked run wearing a checked run's badge.
    When no info_fn is given the engine must receive None instead.
    """
    rets = _regime_panel()
    captured = {}

    real_run_backtest = wf.run_backtest

    def spy(weights, returns, costs, **kwargs):
        captured["info_dates"] = kwargs.get("info_dates", "absent")
        return real_run_backtest(weights, returns, costs, **kwargs)

    monkeypatch.setattr(wf, "run_backtest", spy)

    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    assert captured["info_dates"] is None
    assert res.meta["info_dates_supplied"] is False


def test_a_real_info_fn_is_passed_through_to_the_engine(costs_simple, monkeypatch):
    """The genuine article still reaches the engine's row-level guard."""
    rets = _regime_panel()
    captured = {}

    real_run_backtest = wf.run_backtest

    def spy(weights, returns, costs, **kwargs):
        captured["info_dates"] = kwargs.get("info_dates")
        return real_run_backtest(weights, returns, costs, **kwargs)

    monkeypatch.setattr(wf, "run_backtest", spy)

    def honest_info(piece, window):
        # rows are built from the prior day's close: strictly older than t
        return pd.Series(piece.index - pd.Timedelta(days=1), index=piece.index)

    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
        info_fn=honest_info, verbose=False)

    info = captured["info_dates"]
    assert isinstance(info, pd.Series)
    assert info.index.equals(res.weights.index)
    assert (info.values < res.weights.index.values).all()
    assert res.meta["info_dates_supplied"] is True


def test_a_fully_unguarded_run_says_so_out_loud(costs_simple):
    """No info_fn AND no causality audit = no automated leak protection.
    That combination must be impossible to reach quietly."""
    rets = _regime_panel()
    with pytest.warns(UserWarning, match="NO automated look-ahead protection"):
        wf.run_walkforward(
            rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
            min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
            check_causality=False, verbose=False)


def test_apply_that_cannot_rebuild_a_row_from_its_own_past_is_rejected(costs_simple):
    """An apply that only ever emits rows at the very end of its panel cannot
    have its causality verified. Unverifiable is not the same as leaking, so
    the message says so — but it still stops the run rather than passing."""
    rets = _regime_panel()

    def drops_its_final_row_when_truncated(params, panel, window):
        w = pd.DataFrame(0.0, index=panel.index, columns=["HYG", "JNK"])
        w[params["pick"]] = 1.0
        if panel.index.max() < window.oos_end:   # i.e. a causality replay
            return w.iloc[:-1]                   # probe row itself is missing
        return w

    with pytest.raises(ValueError, match="cannot be verified"):
        wf.run_walkforward(
            rets, _fit_trailing_winner, drops_its_final_row_when_truncated,
            costs_simple, min_train=REGIME, step=REGIME,
            rf=zero_rf(rets.index), verbose=False)


def test_fit_never_receives_data_past_its_fit_end(costs_simple):
    """Structural guarantee: the panel handed to fit() is truncated, so the
    future is absent rather than merely off-limits."""
    rets = _regime_panel()
    seen = []

    def recording_fit(train_panel, window):
        seen.append({
            "fit_end": window.fit_end,
            "max_date": train_panel.index.max(),
            "n_rows": len(train_panel),
            "expected_rows": window.n_fit_days,
        })
        return _fit_trailing_winner(train_panel, window)

    wf.run_walkforward(rets, recording_fit, _apply_hold_pick, costs_simple,
                       min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
                       verbose=False)

    assert len(seen) > 1
    for s in seen:
        assert s["max_date"] == s["fit_end"]          # not one day more
        assert s["n_rows"] == s["expected_rows"]


def test_apply_sees_history_only_through_its_own_window_end(costs_simple):
    """apply() gets warm-up history but never the true end of the sample —
    so an apply that peeks at panel.iloc[-1] cannot see the real future.

    NOTE: apply() is now called twice per window for two different reasons —
    once for real (panel through oos_end) and once per probe row by the
    causality audit (panel deliberately truncated at the probe date). A
    recording apply sees both, so the claim is stated per window: no call
    ever reaches past oos_end, and the deepest call reaches it exactly.
    """
    rets = _regime_panel()
    seen = []

    def recording_apply(params, panel, window):
        seen.append((panel.index.max(), window.oos_end))
        return _apply_hold_pick(params, panel, window)

    wf.run_walkforward(rets, _fit_trailing_winner, recording_apply,
                       costs_simple, min_train=REGIME, step=REGIME,
                       rf=zero_rf(rets.index), verbose=False)

    # no call of any kind sees past its own window's OOS end
    for panel_end, oos_end in seen:
        assert panel_end <= oos_end

    # per window, the real call reaches exactly oos_end
    deepest = {}
    for panel_end, oos_end in seen:
        deepest[oos_end] = max(deepest.get(oos_end, panel_end), panel_end)
    for oos_end, panel_end in deepest.items():
        assert panel_end == oos_end

    # and no window but the last is ever shown the true end of the sample
    for oos_end in sorted(deepest)[:-1]:
        assert deepest[oos_end] < rets.index[-1]


def test_oos_path_starts_strictly_after_the_first_fit_window(costs_simple):
    """No out-of-sample day may fall inside the first training window."""
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    first_fit_end = res.windows[0].fit_end
    assert res.net.index.min() > first_fit_end
    assert res.start == res.windows[0].oos_start
    assert res.end == res.windows[-1].oos_end


def test_each_windows_exposure_falls_entirely_after_its_fit_end(costs_simple):
    """Per-window check, not just the first: the positions attributable to
    window k are all dated after fit_end_k."""
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    for w in res.windows:
        assert w.oos_start > w.fit_end
        seg = res.positions.loc[w.oos_start:w.oos_end]
        assert len(seg) == w.n_oos_days
        assert seg.index.min() > w.fit_end


def test_windows_tile_the_oos_path_without_gaps_or_overlaps(costs_simple):
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    assert sum(w.n_oos_days for w in res.windows) == res.n_days
    for a, b in zip(res.windows, res.windows[1:]):
        assert b.fit_end == a.oos_end            # expanding, contiguous
        assert b.oos_start > a.oos_end
    assert not res.weights.index.has_duplicates


def test_expanding_windows_never_shrink(costs_simple):
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    for a, b in zip(res.windows, res.windows[1:]):
        assert b.fit_start == a.fit_start        # always from the beginning
        assert b.n_fit_days > a.n_fit_days


# ---------------------------------------------------------------------------
# Parameter log
# ---------------------------------------------------------------------------

def test_params_log_records_every_window_and_its_parameters(costs_simple):
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    log = res.params_log
    assert len(log) == len(res.windows)
    for col in ("window", "fit_start", "fit_end", "oos_start", "oos_end",
                "n_fit_days", "n_oos_days", "param_pick"):
        assert col in log.columns

    # each pick is the asset that led the PREVIOUS regime, so the picks
    # alternate in step with the regimes (window 0 fits on regime 0 = HYG)
    picks = list(log["param_pick"])
    assert picks[0] == "HYG"
    assert all(a != b for a, b in zip(picks, picks[1:]))

    # and the logged pick is what was actually held during that window
    for _, row in log.iterrows():
        held = res.positions.loc[row["oos_start"]:row["oos_end"],
                                 row["param_pick"]]
        assert (held == 1.0).all()


def test_summarize_windows_reports_per_window_oos(costs_simple):
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    df = wf.summarize_windows(res, verbose=False)
    assert len(df) == len(res.windows)
    assert df["oos_days"].sum() == res.n_days
    # compounding the per-window returns reproduces the whole path
    assert float((1.0 + df["oos_return"]).prod() - 1.0) == pytest.approx(
        float((1.0 + res.net).prod() - 1.0), rel=1e-9)


# ---------------------------------------------------------------------------
# Window schedule
# ---------------------------------------------------------------------------

def test_make_windows_int_step():
    dates = pd.bdate_range("2020-01-01", periods=100)
    windows = wf.make_windows(dates, min_train=20, step=20)

    assert windows[0].fit_end == dates[19]
    assert windows[0].n_fit_days == 20
    assert windows[0].oos_start == dates[20]
    assert windows[-1].oos_end == dates[-1]
    assert all(w.fit_start == dates[0] for w in windows)


def test_make_windows_calendar_step():
    dates = pd.bdate_range("2020-01-01", periods=500)
    windows = wf.make_windows(dates, min_train=60, step="YE")

    assert len(windows) >= 2
    assert windows[-1].oos_end == dates[-1]
    for a, b in zip(windows, windows[1:]):
        assert b.fit_end > a.fit_end


def test_make_windows_accepts_a_date_as_min_train():
    dates = pd.bdate_range("2020-01-01", periods=300)
    windows = wf.make_windows(dates, min_train="2020-06-30", step=30)
    assert windows[0].fit_end <= pd.Timestamp("2020-06-30")
    assert windows[0].oos_start > pd.Timestamp("2020-06-30")


def test_make_windows_rejects_schedules_with_no_oos():
    dates = pd.bdate_range("2020-01-01", periods=50)
    with pytest.raises(ValueError, match="no out-of-sample"):
        wf.make_windows(dates, min_train=50, step=10)
    with pytest.raises(ValueError, match="min_train"):
        wf.make_windows(dates, min_train=1, step=10)


# ---------------------------------------------------------------------------
# Runner plumbing
# ---------------------------------------------------------------------------

def test_runner_discards_weight_rows_outside_the_window_entitlement(costs_simple):
    """An apply() that returns weights for the whole history (a very easy
    mistake) must not be able to restate earlier windows: the runner keeps
    only the rows that window is entitled to."""
    rets = _regime_panel()

    def greedy_apply(params, panel, window):
        # returns rows for ALL dates seen so far, including in-sample ones
        w = pd.DataFrame(0.0, index=panel.index, columns=["HYG", "JNK"])
        w[params["pick"]] = 1.0
        return w

    res = wf.run_walkforward(
        rets, _fit_trailing_winner, greedy_apply, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index), verbose=False)

    # one weight row per date from the first fit_end to the sample end
    first_fit_end = res.windows[0].fit_end
    expected = rets.index[rets.index >= first_fit_end]
    assert list(res.weights.index) == list(expected)
    assert float((1.0 + res.net).prod() - 1.0) < 0     # still no leak


def test_runner_charges_no_cost_at_a_seam_when_the_pick_is_unchanged(costs_simple):
    """The stitched path is one engine run, so a refit that lands on the same
    parameters pays nothing at the window boundary. Gluing per-window runs
    together would have charged a spurious round-trip at every seam."""
    n = 300
    rets = make_panel({"HYG": [0.001] * n, "JNK": [-0.001] * n})

    def always_hyg(train_panel, window):
        return {"pick": "HYG"}

    res = wf.run_walkforward(
        rets, always_hyg, _apply_hold_pick, costs_simple,
        min_train=50, step=50, rf=zero_rf(rets.index), verbose=False)

    assert len(res.windows) > 3
    # exactly one entry trade in the whole run
    assert res.turnover.sum() == pytest.approx(1.0)
    assert res.costs.sum() == pytest.approx(1.0 * 1.0 / 1e4)


def test_runner_rejects_a_fit_that_returns_the_wrong_type(costs_simple):
    rets = _regime_panel()
    with pytest.raises(TypeError, match="dict"):
        wf.run_walkforward(rets, lambda t, w: "HYG", _apply_hold_pick,
                           costs_simple, min_train=REGIME, step=REGIME,
                           rf=zero_rf(rets.index), verbose=False)


def test_runner_rejects_an_apply_that_returns_nothing_usable(costs_simple):
    rets = _regime_panel()
    with pytest.raises(TypeError, match="DataFrame"):
        wf.run_walkforward(rets, _fit_trailing_winner,
                           lambda p, panel, w: None, costs_simple,
                           min_train=REGIME, step=REGIME,
                           rf=zero_rf(rets.index), verbose=False)


def test_runner_enforces_the_lookahead_guard_on_stitched_weights(costs_simple):
    """info_fn feeds the engine's guard; a lying info_fn is caught."""
    rets = _regime_panel()

    def bad_info(piece, window):
        # claims each row used data from a day LATER than the row itself
        return pd.Series(piece.index + pd.Timedelta(days=5), index=piece.index)

    with pytest.raises(guard.LookaheadError):
        wf.run_walkforward(rets, _fit_trailing_winner, _apply_hold_pick,
                           costs_simple, min_train=REGIME, step=REGIME,
                           rf=zero_rf(rets.index), info_fn=bad_info,
                           verbose=False)


def test_runner_prints_sample_dates_and_window_count(costs_simple, capsys):
    """Standing rule: every output prints sample start/end and N."""
    rets = _regime_panel()
    res = wf.run_walkforward(
        rets, _fit_trailing_winner, _apply_hold_pick, costs_simple,
        min_train=REGIME, step=REGIME, rf=zero_rf(rets.index),
        name="printer", verbose=True)

    out = capsys.readouterr().out
    assert str(res.start.date()) in out
    assert str(res.end.date()) in out
    assert f"N={res.n_days}" in out
    assert f"{len(res.windows)} " in out
