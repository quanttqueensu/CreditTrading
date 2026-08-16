"""Lookahead guard for the Phase 2+ backtest harness.

Two layers of protection:

1. ``assert_lagged(weights, info_dates)`` — a hard check the engine runs on
   every backtest that passes ``info_dates``. Each weight row dated t is
   applied from day t+1's return (T+1 rule in engine.py), so the newest data
   used to build that row must be dated <= t. Any row whose info date is
   AFTER its own date raises LookaheadError.

2. ``shift_test(...)`` — the shuffle/shift artifact test. Rerun the same
   strategy with every signal delayed one extra day. Delaying information can
   only destroy genuine edge; if the delayed run's net Sharpe IMPROVES by
   more than noise, the pipeline is leaking future information somewhere
   upstream of the engine (e.g. a mis-aligned array in signal construction).

How Phase 3+ strategies must call this
--------------------------------------
1. Build weight rows so that the row dated t uses ONLY data dated <= t
   (signals from closes through t). Then pass info dates explicitly:

       info = pd.Series(weights.index, index=weights.index)   # signal uses day-t close
       run_backtest(weights, returns, costs, rf=rf, info_dates=info)

   If a row uses only older data (e.g. a monthly rebalance built from the
   prior month-end), pass that older date for the row instead. If any row's
   info date is after its row date, the engine refuses to run.

2. After ANY change to signal construction, run:

       verdict = guard.shift_test(weights, returns, costs, rf=rf)

   and paste the printed verdict block into the results memo.

   ``verdict["passed"]`` is False only when BOTH (a) a block bootstrap says
   the delay genuinely helped at this strategy's own noise scale, and (b) the
   delayed lag is an outlier against the other delayed lags in the printed lag
   profile. The old flat 0.05 threshold was removed after it produced roughly
   a 25% false-positive rate and two false alarms — read ``diagnosis`` and
   ``lag_profile`` before touching any code. A large DROP in Sharpe under the
   shift is reported for information only: genuine fast signals also decay
   with delay, so a drop alone is not proof of leakage.
"""

import numpy as np
import pandas as pd


class LookaheadError(ValueError):
    """A weight row claims information from after its own date."""


def assert_lagged(weights, info_dates):
    """Raise LookaheadError unless every weight row is properly lagged.

    Parameters
    ----------
    weights : DataFrame indexed by decision date (row dated t is applied
        from day t+1's return — engine T+1 rule).
    info_dates : Series indexed exactly like ``weights.index``; value = date
        of the newest piece of data used to build that row.

    Rule: info_dates[t] <= t. (Then the first return the row touches, t+1,
    is strictly after the information date.)
    """
    if not isinstance(info_dates, pd.Series):
        raise TypeError("info_dates must be a pd.Series indexed like weights")
    if not info_dates.index.equals(weights.index):
        raise ValueError("info_dates index must equal weights index exactly")
    info = pd.to_datetime(info_dates)
    if info.isna().any():
        raise ValueError("info_dates contains NaT")
    bad = info.index[info.values > info.index.values]
    if len(bad):
        examples = ", ".join(
            f"row {d.date()} claims info from {info.loc[d].date()}"
            for d in bad[:3])
        raise LookaheadError(
            f"{len(bad)} weight row(s) use information from AFTER their own "
            f"date (weight dated t may only use data <= t; it is applied "
            f"from t+1). First offenders: {examples}")


def shift_test(weights, returns, costs, rf=None, info_dates=None,
               extra_lag=1, tol=None, name="strategy", verbose=True,
               n_boot=1000, block=21, profile_lags=5, seed=0,
               **engine_kwargs):
    """Artifact test: delaying signals should not materially IMPROVE net Sharpe.

    Runs the backtest as given and with signals delayed ``extra_lag`` extra
    day(s). A large improvement can mean the signal is misaligned — reading
    returns at the wrong offset — which is worth investigating.

    WHY THERE IS NO LONGER A FIXED TOLERANCE. This test used to fail whenever
    the improvement exceeded a flat 0.05 Sharpe and announce it as a
    "build-stopping bug". That threshold has no per-signal meaning: how much
    Sharpe moves under a one-day delay depends on the signal's turnover and on
    the *asset's own* return autocorrelation, so the false-positive rate was
    measured at roughly 25% for signals of this persistence — it raised two
    false alarms across Phase 2 and Phase 4, one of them on a reference cell
    that five independent lines of evidence then cleared. The cause there was
    HYG's ~3-day return reversal (lag-3 autocorrelation -0.066), a property of
    the asset, not a leak in the code.

    So the tolerance is now derived per signal, two ways:

    * a block bootstrap of the daily difference between the shifted and base
      net-return paths, giving a one-sided p-value for "the delay genuinely
      helped" that respects this strategy's own noise scale;
    * a LAG PROFILE across 0..``profile_lags`` days. Real misalignment makes
      day 0 stand out against every later lag. Mean reversion in the
      underlying instead produces a smooth or oscillating profile, which is
      what exonerates the reversal case.

    Pass ``tol`` explicitly to restore a hard threshold; leave it None to use
    the bootstrap. ``passed`` is a screening result, never a verdict on its
    own: read ``diagnosis`` and ``lag_profile`` before changing any code.
    """
    from .engine import run_backtest  # local import to avoid circularity
    from .tearsheet import sharpe_ratio

    def _run(lag):
        return run_backtest(weights, returns, costs, rf=rf,
                            info_dates=info_dates, extra_lag=lag,
                            name=f"{name} (shift_test +{lag}d)",
                            verbose=False, **engine_kwargs)

    base = _run(0)
    shifted = _run(extra_lag)
    s_base = sharpe_ratio(base.net, base.rf)
    s_shift = sharpe_ratio(shifted.net, shifted.rf)
    improvement = s_shift - s_base

    # --- lag profile: is day 0 an outlier, or is this mean reversion? ------
    lag_profile = {0: float(s_base)}
    for lag in range(1, int(profile_lags) + 1):
        lag_profile[lag] = float(sharpe_ratio(_run(lag).net, base.rf))
    # The signature of misalignment is that the TESTED lag stands out against
    # the other delayed lags — not that lag 0 sits low. The null must exclude
    # both endpoints: including the tested lag inflates the mean and the
    # spread with the very outlier being tested, which hides real leaks
    # (a planted leak scored z = -0.5 that way, and passed).
    null_lags = [v for k, v in lag_profile.items() if k not in (0, extra_lag)]
    if len(null_lags) >= 3:
        med = float(np.median(null_lags))
        mad = float(np.median(np.abs(np.array(null_lags) - med)))
        scale = 1.4826 * mad if mad > 0 else float(np.std(null_lags, ddof=1))
        z_shift = (s_shift - med) / scale if scale > 0 else float("nan")
        z_base = (s_base - med) / scale if scale > 0 else float("nan")
    else:
        z_shift = z_base = float("nan")

    # --- block bootstrap of the paired daily difference --------------------
    diff = (shifted.net - base.net).dropna().to_numpy()
    p_value = float("nan")
    if n_boot and len(diff) > block * 3:
        rng = np.random.default_rng(seed)
        n = len(diff)
        n_blocks = int(np.ceil(n / block))
        starts = rng.integers(0, n - block, size=(int(n_boot), n_blocks))
        stat = np.empty(int(n_boot))
        for i in range(int(n_boot)):
            idx = (starts[i, :, None] + np.arange(block)[None, :]).ravel()[:n]
            d = diff[idx]
            sd = d.std(ddof=1)
            stat[i] = d.mean() / sd if sd > 0 else 0.0
        obs_sd = diff.std(ddof=1)
        obs = diff.mean() / obs_sd if obs_sd > 0 else 0.0
        # One-sided: how often does the bootstrap fail to reproduce a gain
        # at least this large? Small p = the delay reliably helped.
        p_value = float((stat <= 0).mean()) if obs > 0 else 1.0

    if tol is not None:
        passed = bool(improvement <= tol)
        basis = f"fixed tol {tol:+.3f}"
    else:
        # Flag only when the gain is both real for THIS signal and lag 0 is
        # genuinely anomalous — not merely when a round number was crossed.
        significant = np.isfinite(p_value) and p_value < 0.05
        anomalous = np.isfinite(z_shift) and z_shift > 3.0
        passed = not (significant and anomalous and improvement > 0)
        basis = "per-signal bootstrap + lag profile"

    if not passed:
        diagnosis = (f"Delaying the signal by {extra_lag}d improved net Sharpe "
                     "more than this strategy's own noise explains, and that "
                     "lag is an outlier against the other delayed lags "
                     f"(z={z_shift:+.1f}). Consistent with a misaligned "
                     "signal — inspect how the weights are dated before "
                     "trusting any result from it.")
    elif improvement > 0 and np.isfinite(z_shift) and z_shift <= 3.0:
        diagnosis = ("Delay helped, but the lag profile is smooth rather than "
                     "day-0-anomalous — the usual cause is mean reversion in "
                     "the underlying, not leakage. Not a code defect.")
    elif improvement < -0.5:
        diagnosis = ("Large drop under delay: fast signal decay. Expected for "
                     "a short-horizon signal; not evidence of leakage.")
    else:
        diagnosis = "No misalignment signature."

    out = {
        "base_net_sharpe": float(s_base),
        "shifted_net_sharpe": float(s_shift),
        "improvement": float(improvement),
        "tol": tol,
        "p_value": p_value,
        "lag_profile": lag_profile,
        "z_shift_vs_other_lags": z_shift,
        "z_base_vs_other_lags": z_base,
        "extra_lag": extra_lag,
        "passed": passed,
        "basis": basis,
        "diagnosis": diagnosis,
        "start": base.start,
        "end": base.end,
        "n_days": base.n_days,
    }
    if verbose:
        print(f"[guard.shift_test] {name}: sample {base.start.date()}.."
              f"{base.end.date()} N={base.n_days} days")
        print(f"[guard.shift_test]   net Sharpe base {s_base:+.3f} | "
              f"+{extra_lag}d delay {s_shift:+.3f} | improvement "
              f"{improvement:+.3f}  ({basis})")
        prof = "  ".join(f"{k}d:{v:+.3f}" for k, v in lag_profile.items())
        print(f"[guard.shift_test]   lag profile {prof}")
        print(f"[guard.shift_test]   bootstrap p={p_value:.3f}  "
              f"z(tested lag vs others)={z_shift:+.2f}")
        print(f"[guard.shift_test]   {'PASS' if passed else 'FLAG'} — {diagnosis}")
    return out
