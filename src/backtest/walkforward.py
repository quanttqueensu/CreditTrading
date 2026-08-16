"""Expanding-window walk-forward runner — Phase 2 harness.

Standing rule (BUILD_PLAN / PREREGISTRATION): *walk-forward only, no
full-sample fitting*. This module is the mechanism that makes that rule
structural rather than a promise.

The contract
------------
The caller supplies two functions:

    fit(train_panel, window)  -> params            (a dict)
    apply(params, panel, window) -> weights DataFrame

and the runner guarantees:

1. ``fit`` is handed a panel **physically truncated** at the window's fit
   end (``returns.loc[:fit_end]``). It cannot see later data because later
   data is not in the object it receives. Parameters are therefore a
   function of the past only, by construction — not by convention.

2. The parameters fitted through ``fit_end`` are applied **strictly after**
   ``fit_end``. Window k keeps only the weight rows dated in
   ``[fit_end_k, fit_end_{k+1})``; the engine's T+1 rule turns those rows
   into exposure on ``(fit_end_k, fit_end_{k+1}]``. The earliest return any
   window-k parameter can touch is the day AFTER its fit window closes.

   (A weight row dated exactly ``fit_end`` is legitimate and deliberate: the
   parameters are known at that day's close, the position is taken at that
   close, and the first return earned is the next day's. Forbidding it would
   instead force an artificial flat day at every window boundary.)

3. ``apply`` receives history truncated at the window's **OOS end**, so a
   signal with a 63-day warm-up still works inside the window, but an apply
   function that peeks at "the end of the data" sees only its own window
   end — never the true end of the sample.

4. ``apply`` is AUDITED for causality (``check_causality=True``, the
   default). Handing apply history through ``oos_end`` is necessary — a
   weight row dated t inside the window genuinely needs data through t — but
   it also means apply is holding data it must not use for its earlier rows.
   The runner therefore REPLAYS apply on a panel physically truncated at a
   probe row's own date and requires the row to come back unchanged. A row
   that moves when its future is removed was built from that future, and the
   run stops with ``guard.LookaheadError``.

   This is verification, not a promise: it is the only layer that can catch a
   leak on the apply side, because the fit-side truncation (1) says nothing
   about how apply uses the panel it is given.

Limits of the audit, stated plainly — it is real protection, not total:

* It cannot catch a fit or apply that closes over an outer full-sample
  variable and ignores its arguments (``test_a_leak_would_be_visible_in_
  this_test`` plants exactly that; the regime trap's economics, not the
  audit, is what exposes it). No in-process harness can detect that.
* It is a SAMPLE of rows, so power scales with how much of the path a leak
  contaminates. See ``causality_probes`` for the measured numbers.
* It tests EFFECT, not form. An apply that is formally non-causal but whose
  future-dependence moves no weight passes — correctly, in the sense that a
  future that changes no position cannot have inflated the backtest. (Real
  example found while calibrating this: ``price > price.mean()`` on HYG.
  The mean is a full-window statistic, but HYG's cumulative price sits so
  far above its own running mean that adding a year of future data never
  flips the comparison. Zero rows changed.) The audit's guarantee is
  therefore "no future information reached the weights that were probed",
  which is the property the backtest's validity actually rests on.

The remaining layers stay independent on purpose: the engine's
``info_dates`` / ``guard.assert_lagged`` row-level check (pass ``info_fn``;
the runner never fabricates it), and ``guard.shift_test``.

Windows are EXPANDING (every fit starts at the first available date), which
is the right default for slow-moving credit relationships: it never throws
away history, and it makes each refit a superset of the last.

Every run prints sample start/end and N.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import guard
from .engine import TRADING_DAYS, load_costs, run_backtest

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    """One expanding-window fit/apply block.

    fit_start..fit_end : data the parameters may be fitted on (inclusive).
    oos_start..oos_end : dates those parameters earn returns on (inclusive).
                         oos_start is always the trading day AFTER fit_end.
    """
    index: int
    fit_start: pd.Timestamp
    fit_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    n_fit_days: int
    n_oos_days: int


def make_windows(dates, min_train, step):
    """Build the expanding-window schedule.

    Parameters
    ----------
    dates : DatetimeIndex of trading days (sorted, unique).
    min_train : int  -> number of trading days in the first fit window; or
                Timestamp/str -> first fit ends on the last trading day <= it.
    step : int -> refit every N trading days; or a pandas offset alias
           ('ME', 'QE', 'YE', '2YE', ...) -> refit at each period end.

    Returns a list of Window. The last window's OOS runs to the final date.
    """
    dates = pd.DatetimeIndex(dates)
    if not dates.is_monotonic_increasing or dates.has_duplicates:
        raise ValueError("dates must be sorted and unique")
    if len(dates) < 3:
        raise ValueError("need at least 3 trading days to walk forward")

    # --- where the first fit window closes --------------------------------
    if isinstance(min_train, (int, np.integer)):
        if min_train < 2:
            raise ValueError("min_train must be >= 2 trading days")
        if min_train >= len(dates):
            raise ValueError(
                f"min_train={min_train} leaves no out-of-sample days "
                f"(sample has {len(dates)})")
        first_pos = int(min_train) - 1
    else:
        cutoff = pd.Timestamp(min_train)
        first_pos = int(dates.searchsorted(cutoff, side="right")) - 1
        if first_pos < 1:
            raise ValueError(f"min_train date {cutoff.date()} precedes the sample")
        if first_pos >= len(dates) - 1:
            raise ValueError(
                f"min_train date {cutoff.date()} leaves no out-of-sample days")

    # --- refit dates -------------------------------------------------------
    if isinstance(step, (int, np.integer)):
        if step < 1:
            raise ValueError("step must be >= 1 trading day")
        fit_end_pos = list(range(first_pos, len(dates) - 1, int(step)))
    else:
        period_ends = dates.to_series().resample(step).last().dropna()
        pos = [int(dates.get_loc(d)) for d in period_ends]
        fit_end_pos = [first_pos] + [p for p in pos if p > first_pos]
        fit_end_pos = [p for p in fit_end_pos if p < len(dates) - 1]
        fit_end_pos = sorted(set(fit_end_pos))

    if not fit_end_pos:
        raise ValueError("window schedule is empty — loosen min_train/step")

    windows = []
    for k, p in enumerate(fit_end_pos):
        last_pos = (fit_end_pos[k + 1] if k + 1 < len(fit_end_pos)
                    else len(dates) - 1)
        windows.append(Window(
            index=k,
            fit_start=dates[0],
            fit_end=dates[p],
            oos_start=dates[p + 1],
            oos_end=dates[last_pos],
            n_fit_days=p + 1,
            n_oos_days=last_pos - p,
        ))
    return windows


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class WalkforwardResult:
    """Stitched out-of-sample path. Exposes the same attribute names as
    engine.BacktestResult, so tearsheet.tearsheet() works on it unchanged."""
    name: str
    gross: pd.Series
    net: pd.Series
    positions: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    rf: pd.Series
    params_log: pd.DataFrame
    windows: list
    weights: pd.DataFrame = None       # stitched OOS target weights
    backtest: object = None            # untrimmed BacktestResult
    start: pd.Timestamp = None
    end: pd.Timestamp = None
    n_days: int = 0
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_walkforward(returns, fit, apply, costs, min_train, step, rf=None,
                    info_fn=None, book_usd=None, name="walkforward",
                    verbose=True, check_causality=True, causality_probes=10,
                    **engine_kwargs):
    """Run an expanding-window walk-forward backtest.

    Parameters
    ----------
    returns : DataFrame dates x tickers of daily total returns (load_panel).
    fit : callable(train_panel, window) -> dict of parameters.
        ``train_panel`` is ``returns.loc[:window.fit_end]`` — truncated, so
        the future is not merely off-limits, it is absent.
    apply : callable(params, panel, window) -> DataFrame of target weights.
        ``panel`` is ``returns.loc[:window.oos_end]``. Return whatever date
        range is convenient; the runner keeps only the rows this window is
        entitled to (dated ``[fit_end, next_fit_end)``) and discards the rest.
    costs : dict from load_costs(), or a path to a costs yaml.
    min_train, step : see make_windows.
    rf : risk-free Series; defaults to BIL ret_total inside the engine.
    info_fn : optional callable(weights, window) -> Series of info dates for
        those rows, passed through to the engine's lookahead guard. If None,
        NOTHING is passed to the engine's guard — the runner never invents
        info dates, because an invented one (info_dates = weights.index)
        cannot fail and would only disguise an unchecked run as a checked
        one. Supply info_fn when a row uses data OLDER than its own date
        (e.g. a monthly rebalance built from the prior month-end).
    book_usd : book size for the commission term (default from config).
    name, verbose : labeling / printing.
    check_causality : replay-audit apply() (default True). For a sample of
        weight rows the runner re-calls apply with the panel truncated at
        that row's own date and requires an identical row. Catches an apply
        that builds row t from data after t — the one leak the fit-side
        truncation cannot see. Turn off only with a written justification.
    causality_probes : probe rows per window (default 10, spread across the
        window; rows dated at oos_end are skipped as they remove no future).
        The audit is a SAMPLE, so its power depends on how many rows a leak
        actually contaminates. Measured on the real HYG panel (16 annual
        windows, 2011-2026) against the common accidental leak forms —
        ``shift(-1)``, ``rolling(center=True)``, full-window vol target,
        full-window z-score — each contaminated 50-73% of rows and was caught
        in the first window at this budget. A leak touching f of all rows is
        missed with probability ~(1-f)^(probes*windows): at the default that
        is <1e-3 for f=5%, ~20% for f=1%. Probing is cheap (~0.25s for a
        19-year daily run); raise it when a signal is near a threshold and a
        leak would flip only a few rows.

    Returns
    -------
    WalkforwardResult — stitched OOS daily path (gross/net/turnover/costs),
    plus ``params_log``: one row per window with the fit/OOS dates, day
    counts, and the fitted parameters.

    The stitched path is produced by ONE engine run over the concatenated
    weight rows (not by gluing per-window runs together), so turnover and
    costs at window boundaries are the real trades — a window that refits to
    the same parameters correctly pays nothing at the seam.
    """
    if isinstance(costs, str) or hasattr(costs, "__fspath__"):
        costs = load_costs(costs)
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a DataFrame (dates x tickers)")
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise TypeError("returns index must be a DatetimeIndex")
    if not callable(fit) or not callable(apply):
        raise TypeError("fit and apply must both be callables")

    dates = returns.index
    windows = make_windows(dates, min_train, step)

    if verbose:
        print(f"[walkforward] {name}: {len(windows)} expanding windows over "
              f"{dates[0].date()}..{dates[-1].date()} N={len(dates)} days")
        print(f"[walkforward]   first fit {windows[0].fit_start.date()}.."
              f"{windows[0].fit_end.date()} ({windows[0].n_fit_days}d) -> OOS "
              f"from {windows[0].oos_start.date()}")

    pieces, log_rows = [], []
    n_probes = 0

    for w in windows:
        # --- FIT: physically truncated history ----------------------------
        train_panel = returns.loc[:w.fit_end]
        if len(train_panel) != w.n_fit_days:  # defensive; slicing is inclusive
            raise AssertionError(
                f"window {w.index}: train panel has {len(train_panel)} rows, "
                f"expected {w.n_fit_days}")
        params = fit(train_panel, w)
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise TypeError(
                f"fit() must return a dict of parameters (window {w.index} "
                f"returned {type(params)})")

        # --- APPLY: history through this window's OOS end only ------------
        apply_panel = returns.loc[:w.oos_end]
        w_raw = apply(params, apply_panel, w)
        if not isinstance(w_raw, pd.DataFrame):
            raise TypeError(
                f"apply() must return a DataFrame of weights (window "
                f"{w.index} returned {type(w_raw)})")
        if not isinstance(w_raw.index, pd.DatetimeIndex):
            raise TypeError(f"apply() weights need a DatetimeIndex "
                            f"(window {w.index})")
        w_raw = w_raw.sort_index()
        if w_raw.index.has_duplicates:
            raise ValueError(f"apply() returned duplicate dates (window {w.index})")

        # --- ENTITLEMENT SLICE: this is the walk-forward guarantee --------
        # Rows dated [fit_end, next_fit_end) -> exposure on (fit_end, ...].
        # Anything earlier would apply these params to in-sample days;
        # anything later belongs to a window whose fit has not happened yet.
        upper = _next_fit_end(windows, w, dates)
        keep = (w_raw.index >= w.fit_end) & (w_raw.index < upper)
        piece = w_raw.loc[keep]

        if len(piece) == 0:
            raise ValueError(
                f"window {w.index}: apply() returned no weight rows inside "
                f"[{w.fit_end.date()}, {upper.date()}) — the window would "
                f"have no out-of-sample exposure")

        off_cal = piece.index.difference(dates)
        if len(off_cal):
            raise ValueError(
                f"window {w.index}: weight rows on non-trading days, first "
                f"{off_cal[0].date()}")

        # --- NaN CHECK, before the causality audit ------------------------
        # A NaN apply() produced (rolling warm-up, divide-by-zero vol) must
        # surface as a NaN, not be filled to a flat position at the stitch.
        # It has to be caught HERE: the causality replay compares a row
        # against itself, and NaN != NaN, so a NaN row would be reported as a
        # leak — sending the reader hunting a bug that does not exist.
        if piece.isna().any().any():
            bad = piece.isna().any(axis=1)
            raise ValueError(
                f"window {w.index}: apply() returned NaN weights (first row: "
                f"{bad.index[bad][0].date()}). Fill them explicitly inside "
                "apply() — 0.0 for flat — so the intent is visible.")

        # --- CAUSALITY AUDIT: is each row a function of its own past? -----
        # The entitlement slice above proves WHEN these rows are applied.
        # It says nothing about WHAT built them: apply() was handed history
        # through oos_end, so an early row could have been computed from
        # data that had not happened yet. Replay and compare.
        if check_causality:
            n_probes += _audit_apply_causality(
                apply, params, piece, w, returns, causality_probes)

        pieces.append(piece)
        log_rows.append({
            "window": w.index,
            "fit_start": w.fit_start,
            "fit_end": w.fit_end,
            "oos_start": w.oos_start,
            "oos_end": w.oos_end,
            "n_fit_days": w.n_fit_days,
            "n_oos_days": w.n_oos_days,
            "n_weight_rows": len(piece),
            **{f"param_{k}": v for k, v in params.items()},
        })

    # --- stitch -----------------------------------------------------------
    cols = list(dict.fromkeys([c for p in pieces for c in p.columns]))
    # A NaN that apply() itself produced (rolling warm-up, divide-by-zero vol)
    # must NOT be quietly turned into a flat position — that hides a broken
    # signal as a deliberate no-trade. Catch those here, BEFORE the reindex
    # below legitimately introduces NaN for tickers a window doesn't trade.
    for i, p in enumerate(pieces):
        if p.isna().any().any():
            bad = p.isna().any(axis=1)
            raise ValueError(
                f"apply() returned NaN weights in window {i} (first row: "
                f"{bad.index[bad][0].date()}). Fill them explicitly inside "
                "apply() — 0.0 for flat — so the intent is visible.")
    weights = pd.concat([p.reindex(columns=cols) for p in pieces], axis=0)
    # Remaining NaN can only come from the reindex: ticker absent from that
    # window's frame, which genuinely means no position.
    weights = weights.sort_index().fillna(0.0)
    if weights.index.has_duplicates:
        dupes = weights.index[weights.index.duplicated()][:3]
        raise AssertionError(
            f"stitched weight rows overlap between windows (first: "
            f"{[d.date() for d in dupes]}) — window schedule is broken")

    # --- final leak assertion: no row may predate its own window's fit ----
    _assert_no_leak(weights, windows)

    # --- row-level info dates --------------------------------------------
    # NOTE: when info_fn is None we pass None THROUGH to the engine. We do
    # not synthesise info_dates = weights.index. That value is self-
    # certifying — assert_lagged only ever compares info dates against the
    # row's own date, so an index-derived series makes the check
    # mathematically incapable of failing while looking like it passed, and
    # it also suppresses the engine's own "no info_dates" warning. A guard
    # that cannot fail is worse than no guard: it launders an unchecked run
    # as a checked one. The causality audit above is the real protection.
    info_dates = None
    if info_fn is not None:
        info_dates = pd.Series(
            pd.concat([pd.Series(info_fn(p, w)) for p, w in zip(pieces, windows)])
        ).sort_index()
        info_dates = info_dates.reindex(weights.index)
        if info_dates.isna().any():
            raise ValueError("info_fn did not return an info date for every "
                             "weight row")
        guard.assert_lagged(weights, info_dates)
    elif not check_causality:
        warnings.warn(
            f"[walkforward] {name}: no info_fn AND check_causality=False — "
            "this run has NO automated look-ahead protection on the apply "
            "side at all. Pass info_fn, or leave check_causality on.",
            UserWarning, stacklevel=2)
    elif verbose:
        print(f"[walkforward] {name}: no info_fn — engine row-level guard "
              f"skipped; apply causality verified by replay instead "
              f"({n_probes} probe rows).")

    bt = run_backtest(
        weights, returns, costs, rf=rf, info_dates=info_dates,
        book_usd=book_usd, name=f"{name} (stitched OOS)", verbose=False,
        **engine_kwargs)

    # The engine's sim window opens on the first weight row's date (that day
    # is flat by construction — T+1). The OOS path proper starts the next day.
    oos_mask = bt.net.index > weights.index[0]
    params_log = pd.DataFrame(log_rows)

    result = WalkforwardResult(
        name=name,
        gross=bt.gross[oos_mask],
        net=bt.net[oos_mask],
        positions=bt.positions.loc[oos_mask],
        turnover=bt.turnover[oos_mask],
        costs=bt.costs[oos_mask],
        rf=bt.rf[oos_mask],
        params_log=params_log,
        windows=windows,
        weights=weights,
        backtest=bt,
        start=bt.net.index[oos_mask][0],
        end=bt.net.index[oos_mask][-1],
        n_days=int(oos_mask.sum()),
        meta={"n_windows": len(windows), "min_train": min_train, "step": step,
              "tickers": cols, "book_usd": bt.meta.get("book_usd"),
              "causality_checked": bool(check_causality),
              "causality_probes": n_probes,
              "info_dates_supplied": info_fn is not None},
    )

    if verbose:
        years = result.n_days / TRADING_DAYS
        print(f"[walkforward] {name}: OOS sample {result.start.date()}.."
              f"{result.end.date()} N={result.n_days} days ({years:.1f}y), "
              f"{len(windows)} windows")
        print(f"[walkforward]   avg annual turnover "
              f"{result.turnover.sum() / years:.2f}x | total cost drag "
              f"{result.costs.sum():.4%}")
        if check_causality:
            print(f"[walkforward]   causality audit PASSED: {n_probes} weight "
                  f"row(s) replayed on truncated history, all unchanged")
        else:
            print("[walkforward]   causality audit SKIPPED "
                  "(check_causality=False)")
    return result


def _probe_dates(piece_index, oos_end, n_probes):
    """Rows worth probing: those dated strictly before the window's OOS end.

    A row dated exactly oos_end is unprobeable — truncating the panel at that
    date removes no future, so the replay is guaranteed to match and would
    manufacture false reassurance. Probes are spread evenly and always
    include the earliest row, where the most future is withheld and a leak is
    therefore most visible.
    """
    cand = pd.DatetimeIndex(piece_index)
    cand = cand[cand < oos_end]
    if len(cand) == 0 or n_probes < 1:
        return []
    if len(cand) <= n_probes:
        return list(cand)
    pos = np.unique(np.linspace(0, len(cand) - 1, n_probes).round().astype(int))
    return [cand[i] for i in pos]


def _audit_apply_causality(apply, params, piece, w, returns, n_probes,
                           atol=1e-9):
    """Replay apply() with the future physically removed; demand the same row.

    For probe date t, apply is re-called with ``returns.loc[:t]`` — the same
    parameters, the same window, but a panel that stops at the row's own
    date. A causal apply must return an identical row for t, because
    everything it legitimately used is still there. A row that changes was
    built from data after t.

    Returns the number of probes actually run.
    """
    probes = _probe_dates(piece.index, w.oos_end, n_probes)
    for t in probes:
        replay = apply(params, returns.loc[:t], w)
        if not isinstance(replay, pd.DataFrame) or not isinstance(
                replay.index, pd.DatetimeIndex):
            raise TypeError(
                f"window {w.index}: apply() returned "
                f"{type(replay)} when replayed on history through "
                f"{t.date()} — apply must behave the same on a truncated "
                "panel (it is called that way by the causality audit)")
        if replay.index.has_duplicates:
            raise ValueError(
                f"window {w.index}: apply() returned duplicate dates when "
                f"replayed on history through {t.date()}")
        if t not in replay.index:
            raise ValueError(
                f"window {w.index}: apply() produced no weight row for "
                f"{t.date()} when given history through {t.date()}, so that "
                "row's causality cannot be verified. A weight row dated t "
                "must be constructible from data through t — that is what "
                "makes it tradeable. Fix apply(), or pass "
                "check_causality=False with a written justification.")

        want = piece.loc[t]
        got = replay.loc[t].reindex(want.index)
        delta = (got - want).abs()
        if got.isna().any() or (delta > atol).any():
            moved = delta.reindex(want.index)
            worst = moved.idxmax() if moved.notna().any() else want.index[0]
            raise guard.LookaheadError(
                f"window {w.index}: apply() is not causal. The weight row "
                f"dated {t.date()} changes when the panel is truncated at "
                f"its own date — so it was built from data AFTER "
                f"{t.date()}. Worst column {worst}: "
                f"{want.get(worst, float('nan')):+.6g} with the future "
                f"visible vs {got.get(worst, float('nan')):+.6g} without it. "
                "apply() receives history through window.oos_end so that "
                "warm-up works inside the window; it may NOT use any of that "
                "history beyond the date of the row it is building.")
    return len(probes)


def _next_fit_end(windows, w, dates):
    """Upper bound (exclusive) on window w's weight-row dates."""
    if w.index + 1 < len(windows):
        return windows[w.index + 1].fit_end
    # last window: allow rows through the end of the sample
    return dates[-1] + pd.Timedelta(days=1)


def _assert_no_leak(weights, windows):
    """Every stitched weight row must be dated on/after the fit_end of the
    window that produced it, so its first return (T+1) is strictly after
    that fit window closed. Belt-and-braces over the entitlement slice."""
    first_fit_end = windows[0].fit_end
    early = weights.index[weights.index < first_fit_end]
    if len(early):
        raise guard.LookaheadError(
            f"{len(early)} stitched weight row(s) predate the first fit end "
            f"{first_fit_end.date()} (first: {early[0].date()}) — parameters "
            "would be applied to their own training data")
    for w in windows:
        upper = (windows[w.index + 1].fit_end
                 if w.index + 1 < len(windows) else None)
        seg = weights.index[weights.index >= w.fit_end]
        if upper is not None:
            seg = seg[seg < upper]
        if len(seg) and seg.min() < w.fit_end:
            raise guard.LookaheadError(
                f"window {w.index}: weight row {seg.min().date()} precedes "
                f"its fit end {w.fit_end.date()}")


def summarize_windows(result, verbose=True):
    """Per-window OOS summary (return, days) joined to the parameter log —
    the table Phase 3+ memos publish to show the walk-forward is real."""
    rows = []
    for w in result.windows:
        seg = result.net.loc[
            (result.net.index >= w.oos_start) & (result.net.index <= w.oos_end)]
        rows.append({
            "window": w.index,
            "fit_end": w.fit_end,
            "oos_start": w.oos_start,
            "oos_end": w.oos_end,
            "oos_days": len(seg),
            "oos_return": float((1.0 + seg).prod() - 1.0) if len(seg) else np.nan,
        })
    df = pd.DataFrame(rows).merge(result.params_log, on="window",
                                  how="left", suffixes=("", "_log"))
    if verbose:
        print(f"[walkforward.summarize] {result.name}: OOS "
              f"{result.start.date()}..{result.end.date()} "
              f"N={result.n_days} days across {len(df)} windows")
    return df
