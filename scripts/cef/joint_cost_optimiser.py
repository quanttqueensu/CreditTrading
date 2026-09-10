"""Does the band and the covariance, solved TOGETHER, beat solving them in sequence?

THE QUESTION
------------
Two improvements to the CEF sleeve's construction were each measured and each failed:

    w ~ Sigma^-1 alpha  raises gross SR 1.20 -> 1.54 and effective breadth 2.24 -> 3.95,
                        and raises turnover by 43%. At 15bp that is a wash: 0.33 -> 0.28.
    a no-trade band     cuts turnover 31 -> 14/yr and roughly doubles net SR, 0.33 -> 0.70.

Composing them in sequence -- build Sigma^-1 alpha targets, then run a scalar band over
those targets -- was measured too, at every band width, and it also failed. Matched at
~13 turns/yr, plain+band nets 0.70 and Sigma^-1+band nets 0.62.

The hypothesis under test here is that SEQUENCE IS THE WRONG STRUCTURE. A scalar band
asks a per-coordinate question ("has this name's weight drifted more than b?") of a
construction whose entire premise is that the coordinates are not separable. Ask both
questions at once instead:

    maximise_w   w'alpha - (lambda/2) w'Sigma w - c||w - w_prev||_1   s.t.  1'w = 0

and the no-trade region is no longer a parameter. It is a consequence: the subgradient
of the L1 term leaves a name alone unless its RISK-ADJUSTED marginal alpha exceeds the
cost of trading it. Solver, proofs and the five correctness tests live in
`src/analysis/l1_meanvar.py` and its test module.

WHAT IS HELD FIXED SO THE COMPARISON MEANS SOMETHING
----------------------------------------------------
Signal, universe, ADV filter, vol target, sample and execution convention are the
sleeve's own, taken from band_frontier.py and covariance_construction.py rather than
rebuilt. Sigma is the same Ledoit-Wolf estimate on the same 252d trailing window,
refit on the same monthly cadence. alpha is the same Grinold conversion, alpha_i =
sigma_i * (-z_i). The ONLY thing that changes across rows of the output table is how
weights are decided from those inputs.

LAMBDA. Risk aversion is not swept and is not free. On each date it is set so that the
FRICTIONLESS (c = 0) solution is exactly the vol-targeted Sigma^-1 alpha book the
existing code would have built: gross-normalise the frictionless direction, apply the
sleeve's own trailing-63d realised-vol scalar clipped to [0.2, 2.5], and read off the
lambda that reproduces it. So at c = 0 this optimiser IS the Sigma^-1 alpha baseline,
at the same ~6% vol, and every difference at c > 0 is attributable to the cost term.

c_model VERSUS c_exec, AND WHY THEY ARE NOT THE SAME NUMBER. Two corrections sit
between the cost the desk pays and the cost the objective should be fed, and they pull
in opposite directions.

  DOWN, by the holding period. The objective is single-period: it weighs ONE day of
  alpha against a WHOLE trade. These positions are held ~16 business days, so a
  literal reading over-penalises trading by roughly that factor.

  UP, by the information coefficient. alpha here is Grinold units, a_i = sigma_i * z_i,
  with the IC deliberately dropped -- covariance_construction.py drops it because a
  common scalar cannot survive gross normalisation. But it does NOT drop out here. The
  IC is exactly what fixes the ratio between the alpha term and the cost term, and
  dropping it inflates `a` by 1/IC relative to a true expected return.

Together, c_model ~ c_exec / (IC * H). At c_exec = 15bp, IC ~ 0.04 and H ~ 16d that is
about 24bp, and the value that independently matches the baseline's turnover is 25.2bp.
So c_model is anchored, not free: the sweep is here to show the SHAPE of the frontier,
and the operating point is derived and then checked against the match.

NO LOOKAHEAD. Sigma uses ret.iloc[i-252:i], which ENDS THE DAY BEFORE date i. The
Grinold sigma_i is rolling(252).shift(1), also ending at i-1. The z-score moments are
rolling(252).shift(1). The vol scalar applies today's candidate weights to trailing
returns through today, which is the sleeve's own convention -- weights are decided at
the close of t, filled MOC at t+1, and earn the t+2 return (evaluate() applies
H.shift(2)). Nothing here sees a return it could not have seen.

NO SILENT FALLBACKS. If Sigma cannot be estimated for a name the book is holding, this
RAISES rather than substituting a default. The two places where the loop declines to
trade -- fewer than MIN_NAMES eligible names, and a covariance window too short even
after dropping unestimable candidates -- are the sleeve's own documented "hold" rule,
applied identically to every row of the table including the baselines.

Usage:  python3 scripts/cef/joint_cost_optimiser.py
        python3 scripts/cef/joint_cost_optimiser.py --quick     (short c grid)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO))

from ou_score import panel                                          # noqa: E402
from spec import BAND_WIDTH, LIVE_POLICY  # noqa: E402  spec-owned width, never a literal
from band_frontier import (UNIVERSE, Z_WINDOW, MIN_PERIODS, VOL_TARGET,       # noqa: E402
                           VOL_LOOKBACK, MIN_ADV, MIN_NAMES, SAMPLE_START,
                           calendar, band, evaluate)
from covariance_construction import COV_WINDOW, COV_REFIT, br_eff, build      # noqa: E402
from src.analysis.l1_meanvar import frictionless, solve                       # noqa: E402

MIN_COV_OBS = 120          # same floor covariance_construction uses for a LW fit
COSTS_BP = [5, 15, 30]


# ------------------------------------------------------------------ shared inputs

def inputs():
    """Signal, Grinold vols and returns -- identical to covariance_construction."""
    px, disc, ret, adv = panel()
    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    vol_i = ret.rolling(COV_WINDOW, min_periods=120).std().shift(1)   # ends at i-1
    # the sleeve's tradeability test, materialised once so every row of the output
    # table is scored against exactly the same definition
    elig = z.notna() & (adv.reindex_like(z).fillna(0.0) >= MIN_ADV)
    return z, vol_i, ret, adv, elig


def _cov_window(ret, i, cols, held):
    """Complete-case trailing window ending STRICTLY BEFORE date i.

    If it is too short, drop the candidate name with the fewest observations of its
    own -- the one whose risk genuinely cannot be estimated -- and retry. Dropping a
    name the book is HOLDING is not an option: that would be pretending a live
    position carries no risk, so it RAISES instead.
    """
    cur = list(cols)
    while True:
        sub = ret[cur].iloc[max(0, i - COV_WINDOW):i]
        rows = sub.dropna()
        if len(rows) >= MIN_COV_OBS:
            return cur, rows
        counts = sub.notna().sum()
        worst = str(counts.idxmin())
        if worst in held:
            raise RuntimeError(
                f"{ret.index[i].date()}: only {len(rows)} complete return rows in the "
                f"{COV_WINDOW}d window for {cur}; the binding name {worst} is HELD "
                f"({int(counts[worst])} own obs) so it cannot be dropped")
        if len(cur) - 1 < MIN_NAMES:
            return None, None                    # untradeable date -> hold, as the sleeve does
        cur.remove(worst)


# --------------------------------------------------------------- the joint optimiser

def run_joint(c_model, z, vol_i, ret, adv, tol=1e-8, adv_mode="carry"):
    """Path of holdings from solving the joint problem at every rebalance date.

    Returns (H, R, diagnostics). H.loc[t] are the weights DECIDED at t, so it feeds
    evaluate() directly -- there is no separate target/policy split, which is the
    whole point: the trading rule is inside the objective.

    adv_mode decides what happens to a position in a name that has fallen out of the
    ADV filter. This is the one genuinely discretionary modelling choice here, so both
    answers are implemented and both are reported.

      "carry"  the name stays a decision variable with alpha_i = 0 -- no view, but
               still risk. The optimiser trims it when that beats the cost, and may
               also SIZE it as a hedge, which is the objection to this choice: it
               takes risk in a name the ADV filter says the sleeve cannot trade.
      "exit"   the name leaves the optimisation set and its position is closed at
               once, with the turnover charged. Harsher than the band baselines,
               which only walk such a position back to the band edge, but it keeps
               the book strictly inside the tradeable universe.

    Under "exit" the incoming book restricted to the eligible set is generally NOT
    dollar-neutral; the solver takes 1'w = 0 as a constraint on w, not an assumption
    about w_prev, so the imbalance is carried into the solve rather than papered over.
    """
    idx = z.index
    start = idx.searchsorted(pd.Timestamp(SAMPLE_START))
    H = pd.DataFrame(0.0, index=idx, columns=UNIVERSE)
    w = pd.Series(0.0, index=UNIVERSE)

    Sig, cached_cols = None, None
    brs, exante, iters, kkts = [], [], [], []
    n_solve = n_hold = n_notrade = 0
    names_seen = names_still = 0
    approx_agree = approx_total = 0

    for i in range(start, len(idx)):
        row = z.iloc[i].dropna()
        elig = [t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV]
        # exact test: the prox produces exact zeros, so an untouched weight is
        # bit-identical to yesterday's and a held name is exactly non-zero.
        held = {t for t in UNIVERSE if w[t] != 0.0}

        if len(elig) < MIN_NAMES:                # the sleeve's own hold rule
            H.iloc[i] = w.values
            n_hold += 1
            continue

        if adv_mode == "carry":
            cols = sorted(set(elig) | held)
        elif adv_mode == "exit":
            cols = sorted(elig)
        else:
            raise ValueError(f"unknown adv_mode {adv_mode!r}")
        cols, hist_rows = _cov_window(ret, i, cols, held if adv_mode == "carry" else set())
        if cols is None:
            H.iloc[i] = w.values
            n_hold += 1
            continue

        # Hard runtime guard on the failure mode that has already cost this project
        # once: the covariance window must END BEFORE the date it is used on.
        if len(hist_rows) and hist_rows.index[-1] >= idx[i]:
            raise RuntimeError(f"LOOKAHEAD: covariance window for {idx[i].date()} ends "
                               f"at {hist_rows.index[-1].date()}, which is not strictly "
                               f"before the decision date")
        if Sig is None or cols != cached_cols or (i - start) % COV_REFIT == 0:
            Sig = LedoitWolf().fit(hist_rows.values).covariance_
            cached_cols = cols

        # alpha in Grinold units. A held name that has dropped out of the eligible
        # set carries NO VIEW, not a short view: alpha_i = 0. It still carries risk,
        # so the optimiser trims it when, and only when, that is worth the cost.
        a = np.zeros(len(cols))
        for k, t in enumerate(cols):
            if t in elig:
                s_i = vol_i.iloc[i][t]
                if not np.isfinite(s_i):
                    raise RuntimeError(f"{idx[i].date()}: no trailing vol for eligible {t}")
                a[k] = -float(row[t]) * float(s_i)

        # lambda: reproduce the sleeve's vol-targeted Sigma^-1 alpha book at c = 0
        u = frictionless(a, Sig, 1.0)
        gu = float(np.abs(u).sum())
        if gu <= 0:
            raise RuntimeError(f"{idx[i].date()}: frictionless book is identically zero")
        uhat = pd.Series(u / gu, index=cols)
        bt = ret[cols].iloc[:i + 1].mul(uhat, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = float(bt.std() * np.sqrt(252))
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        lam = gu / scal

        # Every name the book holds is inside `cols` by construction (_cov_window
        # raises rather than dropping a held name), so the restriction of w to cols
        # is ALREADY exactly dollar-neutral. Verify it; do not quietly re-centre it,
        # which would inject an untracked trade into every name.
        w_prev = w[cols].to_numpy(float)
        if adv_mode == "carry":
            # every held name is inside `cols` by construction (_cov_window raises
            # rather than dropping one), so the restriction really is neutral already
            drift = abs(float(w_prev.sum()))
            if drift > 1e-10 * max(1.0, float(np.abs(w_prev).sum())):
                raise RuntimeError(f"{idx[i].date()}: incoming book is not neutral on "
                                   f"the optimisation set (1'w_prev = {w_prev.sum():.3e})")

        sol = solve(a, Sig, w_prev, lam, c_model, tol=tol)

        n_solve += 1
        iters.append(sol.iters)
        kkts.append(sol.kkt)
        if not sol.traded.any():
            n_notrade += 1
        names_seen += len(cols)
        names_still += int((~sol.traded).sum())

        # how often the at-w_prev per-name reading agrees with the true KKT partition
        g = a - lam * (Sig @ w_prev)
        approx_agree += int(((np.abs(g - sol.nu) <= c_model) == (~sol.traded)).sum())
        approx_total += len(cols)

        w = pd.Series(0.0, index=UNIVERSE)
        w[cols] = sol.w
        H.iloc[i] = w.values

        ws = pd.Series(sol.w, index=cols)
        if np.abs(sol.w).sum() > 0:
            brs.append(br_eff(ws, Sig))
        exante.append(float(np.sqrt(max(sol.w @ Sig @ sol.w, 0.0)) * np.sqrt(252)))

    T = H.iloc[start:]
    diag = dict(
        br_eff=float(np.nanmean(brs)) if brs else np.nan,
        exante_vol=float(np.mean(exante)) if exante else np.nan,
        solves=n_solve, holds=n_hold, no_trade_days=n_notrade,
        name_hold_rate=names_still / names_seen if names_seen else np.nan,
        approx_agree=approx_agree / approx_total if approx_total else np.nan,
        mean_iters=float(np.mean(iters)) if iters else np.nan,
        max_kkt=float(np.max(kkts)) if kkts else np.nan,
    )
    return T, ret.reindex(T.index)[UNIVERSE].fillna(0.0), diag


# ----------------------------------------------------------------------- reporting

ILLIQ_MULT = 3.0        # what a trade in an ADV-filtered name is assumed to cost


def band_hard_exit(T, b, E):
    """band(), except a name failing the eligibility test is closed AT ONCE rather
    than walked back to the band edge.

    This is the control that separates two effects. The joint optimiser is run with
    adv_mode="exit", so it never holds an ineligible name; the plain band leaves 18%
    of gross in them. Without this row a win for the optimiser could be nothing but
    better ADV hygiene, which has nothing to do with solving one objective instead
    of two.
    """
    A = T.values
    Em = E.reindex(index=T.index, columns=T.columns).fillna(False).to_numpy(bool)
    cur = np.zeros(T.shape[1])
    H = np.zeros_like(A)
    for i in range(len(A)):
        gap = A[i] - cur
        mv = np.abs(gap) > b
        cur = cur.copy()
        cur[mv] = A[i][mv] - np.sign(gap[mv]) * b
        cur[~Em[i]] = 0.0
        H[i] = cur
    return pd.DataFrame(H, index=T.index, columns=T.columns)


def stats(H, R, E, br=np.nan):
    """Performance of a holdings path, plus how much of it leans on illiquid names.

    `inelig` is the mean share of gross weight sitting in names that fail the sleeve's
    ADV test. Band rules carry such residuals for months, so the column is reported for
    every row, and `netI@` re-charges turnover in those names at ILLIQ_MULT times the
    headline cost -- applied identically to every construction.
    """
    r = evaluate(H, R)
    Em = E.reindex(index=H.index, columns=H.columns).fillna(False).to_numpy(bool)
    A = H.abs().to_numpy()
    g = A.sum(axis=1)
    ok = g > 1e-9
    inelig = float(((A * ~Em).sum(axis=1)[ok] / g[ok]).mean()) if ok.any() else np.nan

    dv = H.diff().abs().fillna(0.0).to_numpy()
    ann = 252.0 / len(H)
    t_el = float((dv * Em).sum()) * ann
    t_il = float((dv * ~Em).sum()) * ann

    out = dict(gross=r["gross_sr"], ann=r["ann_ret"] * 100, vol=r["vol"] * 100,
               turn=r["turn"], hold=r["hold"], br=br, inelig=inelig)
    for cbp in COSTS_BP:
        out[f"net{cbp}"] = (r["ann_ret"] - r["turn"] * cbp / 1e4) / r["vol"]
        out[f"netI{cbp}"] = (r["ann_ret"]
                             - (t_el + ILLIQ_MULT * t_il) * cbp / 1e4) / r["vol"]
    return out


HDR = (f"{'construction':<38}{'gross':>7}{'ann%':>7}{'vol%':>7}{'turn/yr':>9}"
       + "".join(f"{'net@' + str(c):>9}" for c in COSTS_BP)
       + f"{'BR_eff':>8}{'illiq%':>8}")


def line(label, s):
    print(f"{label:<38}{s['gross']:>7.2f}{s['ann']:>7.2f}{s['vol']:>7.2f}{s['turn']:>9.1f}"
          + "".join(f"{s['net' + str(c)]:>9.2f}" for c in COSTS_BP)
          + (f"{s['br']:>8.2f}" if np.isfinite(s['br']) else f"{'':>8}")
          + f"{s['inelig'] * 100:>8.1f}")


def match_turnover(fn, want, lo, hi, iters=18):
    """Bisect a monotone-decreasing turnover(x) to hit `want`. Returns (x, result).

    This matches the COMPARISON VARIABLE; it is not a search over a performance
    column. Turnover monotonicity in c is asserted separately (test 4).
    """
    flo, fhi = fn(lo), fn(hi)
    if not (flo["turn"] >= want >= fhi["turn"]):
        raise RuntimeError(f"turnover {want:.2f} not bracketed by [{fhi['turn']:.2f}, "
                           f"{flo['turn']:.2f}] over x in [{lo:.3e}, {hi:.3e}]")
    for _ in range(iters):
        mid = np.sqrt(lo * hi) if lo > 0 else 0.5 * (lo + hi)
        r = fn(mid)
        if r["turn"] > want:
            lo = mid
        else:
            hi = mid
        if abs(r["turn"] - want) < 0.05:
            return mid, r
    return mid, r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="short c_model grid")
    args = ap.parse_args()

    z, vol_i, ret, adv, E = inputs()
    base = {}

    print("=" * len(HDR))
    print("BASELINES  (reproduced from band_frontier.py / covariance_construction.py)")
    print("=" * len(HDR))
    print(HDR); print("-" * len(HDR))

    Tp, Rp, _ = build("plain")
    base["plain_cal1"] = stats(calendar(Tp, 1), Rp, E)
    base["plain_cal2"] = stats(calendar(Tp, 2), Rp, E)
    # The band baseline is the LIVE width from the frozen spec. This read 0.064
    # until 2026-09-10 -- the width deliberately NOT chosen on 2026-09-06 -- so
    # every joint-optimiser comparison below was scored against a book nobody
    # runs. The LIVE tag is derived for the same reason.
    base["plain_band"] = stats(band(Tp, BAND_WIDTH), Rp, E)
    line("w ~ alpha, calendar 1d", base["plain_cal1"])
    line("w ~ alpha, calendar 2d", base["plain_cal2"])
    line(f"w ~ alpha, {LIVE_POLICY}  <-- LIVE", base["plain_band"])

    Ti, Ri, bri = build("inv_alpha")
    base["inv_cal1"] = stats(calendar(Ti, 1), Ri, E, bri)
    base["inv_cal2"] = stats(calendar(Ti, 2), Ri, E, bri)
    base["inv_band"] = stats(band(Ti, BAND_WIDTH), Ri, E, bri)
    line("w ~ Sig^-1 a, calendar 1d", base["inv_cal1"])
    line("w ~ Sig^-1 a, calendar 2d", base["inv_cal2"])
    line(f"w ~ Sig^-1 a, {LIVE_POLICY}", base["inv_band"])

    print()
    print("CONTROL: the same bands, but ineligible names closed at once instead of")
    print("being walked to the band edge -- the ADV hygiene the optimiser is given.")
    print("-" * len(HDR))
    base["plain_bandX"] = stats(band_hard_exit(Tp, BAND_WIDTH, E), Rp, E)
    base["inv_bandX"] = stats(band_hard_exit(Ti, BAND_WIDTH, E), Ri, E, bri)
    line(f"w ~ alpha, {LIVE_POLICY} + ADV exit", base["plain_bandX"])
    line(f"w ~ Sig^-1 a, {LIVE_POLICY} + ADV exit", base["inv_bandX"])

    print()
    print("=" * len(HDR))
    print("JOINT OPTIMISER   max w'a - (lam/2)w'Sig w - c||w-w_prev||_1,  1'w = 0")
    print("=" * len(HDR))
    print(HDR); print("-" * len(HDR))

    grid = ([0.0, 8e-4, 3e-3, 6e-3] if args.quick else
            [0.0, 2e-4, 5e-4, 1e-3, 1.5e-3, 2.2e-3, 3e-3, 4.5e-3, 6e-3, 1.2e-2])
    cache = {}

    def joint(c, mode="exit"):
        if (c, mode) not in cache:
            T, R, d = run_joint(c, z, vol_i, ret, adv, adv_mode=mode)
            st = stats(T, R, E, d["br_eff"])
            st["diag"] = d
            cache[(c, mode)] = st
        return cache[(c, mode)]

    for c in grid:
        tag = "  (= Sig^-1 a, daily)" if c == 0 else ""
        line(f"joint exit, c_model={c * 1e4:.1f}bp{tag}", joint(c))

    print()
    print("ALTERNATIVE ADV TREATMENT: an ineligible name keeps alpha_i = 0 and stays a")
    print("decision variable, so the optimiser may size it as a hedge (see run_joint).")
    print("-" * len(HDR))
    for c in ([0.0, 3e-3] if args.quick else [0.0, 1.5e-3, 3e-3, 6e-3]):
        line(f"joint carry, c_model={c * 1e4:.1f}bp", joint(c, "carry"))

    print("\nc_model is the SOLVER's cost parameter, NOT the cost charged in the P&L;")
    print("the net@ columns always charge the stated execution cost whatever c_model")
    print("is. See the derivation under the turnover-matched table below.")

    # ---------------------------------------------------------------- correctness 4
    turns = [joint(c)["turn"] for c in grid]
    for a, b in zip(turns, turns[1:]):
        if b > a + 1e-9:
            raise RuntimeError(f"TEST 4 FAILED: turnover rose with c_model: {a} -> {b}")
    print(f"\n[TEST 4] turnover monotone non-increasing in c_model across the whole "
          f"sweep on the real panel: {turns[0]:.1f} -> {turns[-1]:.1f} turns/yr.")

    # ------------------------------------------------------------- solver diagnostics
    print(f"\n{'c_model':>9}{'solves':>8}{'holds':>7}{'no-trade d':>12}{'names held':>12}"
          f"{'mean iters':>12}{'max KKT':>11}{'exante vol%':>13}{'at-w_prev ok':>14}")
    for c in grid:
        d = joint(c)["diag"]
        print(f"{c * 1e4:>8.1f}b{d['solves']:>8}{d['holds']:>7}"
              f"{d['no_trade_days'] / max(d['solves'], 1):>11.1%}"
              f"{d['name_hold_rate']:>12.1%}{d['mean_iters']:>12.1f}"
              f"{d['max_kkt']:>11.1e}{d['exante_vol'] * 100:>13.2f}"
              f"{d['approx_agree']:>14.1%}")
    print("'no-trade d' = days the whole book sat still; 'names held' = share of")
    print("name-days the optimiser left untouched; 'holds' = days the sleeve's own")
    print("MIN_NAMES rule stood the book down (identical for every row of the table).")
    print("'at-w_prev ok' = share of names where reading the no-trade rule off the")
    print("gradient AT w_prev agrees with the exact KKT partition at w*. Below 100%")
    print("is the dense-Sigma coupling: the region is a sheared polytope, not a box.")

    # --------------------------------------------------- the decisive comparison
    ref = base["plain_band"]
    want = ref["turn"]
    print("\n" + "=" * 96)
    print("TURNOVER-MATCHED: the only honest comparison")
    print("=" * 96)
    print(f"Matching on turnover = {want:.1f}/yr, the live band baseline's rate.")
    print("c_model and band width are each bisected to hit it; the comparison variable")
    print("is being matched, no performance column is being searched.\n")

    c_m, s_m = match_turnover(lambda c: joint(c), want, 1e-5, 3e-2)
    b_m, sb_m = match_turnover(lambda b: stats(band_hard_exit(Tp, b, E), Rp, E),
                               want, 0.001, 0.40)
    bi_m, sbi_m = match_turnover(lambda b: stats(band_hard_exit(Ti, b, E), Ri, E, bri),
                                 want, 0.001, 0.60)

    mh = (f"{'construction':<40}{'turn/yr':>9}{'gross':>7}{'BR_eff':>8}"
          + "".join(f"{'net@' + str(c):>9}" for c in COSTS_BP))
    print(mh); print("-" * len(mh))

    def mrow(lab, s):
        br = f"{s['br']:>8.2f}" if np.isfinite(s['br']) else f"{'':>8}"
        print(f"{lab:<40}{s['turn']:>9.1f}{s['gross']:>7.2f}{br}"
              + "".join(f"{s['net' + str(c2)]:>9.2f}" for c2 in COSTS_BP))

    mrow(f"w ~ alpha, {LIVE_POLICY}  (reference)", ref)
    mrow(f"w ~ alpha, band {b_m * 100:.1f}% + ADV exit", sb_m)
    mrow(f"w ~ Sig^-1 a, band {bi_m * 100:.1f}% + ADV exit", sbi_m)
    mrow(f"w ~ Sig^-1 a, {LIVE_POLICY} (sequential)", base["inv_band"])
    mrow(f"joint, c_model={c_m * 1e4:.1f}bp", s_m)

    print()
    for cbp in COSTS_BP:
        dv = s_m[f"net{cbp}"] - ref[f"net{cbp}"]
        dvx = s_m[f"net{cbp}"] - sb_m[f"net{cbp}"]
        v = "WINS" if dv > 0.02 else ("LOSES" if dv < -0.02 else "TIES")
        print(f"  {cbp:>2}bp exec, matched at {s_m['turn']:.1f} turns/yr: joint "
              f"{s_m['net' + str(cbp)]:.2f}  vs plain+band {ref['net' + str(cbp)]:.2f} "
              f"({v} {dv:+.2f})  vs plain+band+ADVexit {sb_m['net' + str(cbp)]:.2f} "
              f"({dvx:+.2f})")

    print("\nIS c_model = 25bp A FITTED NUMBER? Two corrections separate it from the")
    print("execution cost, and they point opposite ways: DOWN by the holding period H")
    print("(a single-period objective weighs one day of alpha against a whole trade)")
    print("and UP by 1/IC (alpha is Grinold sigma*z with the IC dropped, so it")
    print("overstates a true expected return). c_model ~ c_exec / (IC * H):")
    hj = s_m["hold"]
    print(f"\n{'':>6}{'c_exec':>9}{'IC=0.03':>10}{'IC=0.04':>10}{'IC=0.05':>10}"
          f"      (the matched book holds {hj:.0f} business days)")
    for cx in COSTS_BP:
        print(f"{'':>6}{cx:>8}bp"
              + "".join(f"{cx / (ic * hj):>10.1f}" for ic in (0.03, 0.04, 0.05)))
    print(f"\nAt c_exec = 15bp that bracket is "
          f"{15 / (0.05 * hj):.0f}-{15 / (0.03 * hj):.0f}bp; the turnover match landed "
          f"independently at {c_m * 1e4:.1f}bp.")
    print("So the operating point is derived and then corroborated, not selected off")
    print("the top of a swept column.")
    best_band = max(v["net15"] for v in
                    [stats(band(Tp, b), Rp, E) for b in
                     (0.016, 0.024, 0.032, 0.048, 0.064, 0.096, 0.128)])
    above = [c for c in grid if joint(c)["net15"] > best_band]
    if above:
        print(f"\nRobustness to the match point: the band frontier's BEST net@15 over "
              f"all widths is {best_band:.2f}. The joint optimiser beats that at every")
        print(f"c_model from {min(above) * 1e4:.0f} to {max(above) * 1e4:.0f}bp, i.e. "
              f"across {joint(max(above))['turn']:.0f}-{joint(min(above))['turn']:.0f} "
              f"turns/yr. It does NOT beat it")
        print("outside that range -- at very low c_model it trades too much and at very")
        print("high c_model it stops trading -- so the claim is a range, not a point.")

    # ------------------------------------------------------ where the win comes from
    print("\n" + "=" * 96)
    print("BY ERA -- and the two caveats that go with the headline")
    print("=" * 96)
    print("1. The book is FLAT before 2013: fewer than MIN_NAMES names clear the ADV")
    print("   filter, so the sleeve stands down and 2411 of 5452 dates contribute")
    print("   nothing. Full-sample turnover is therefore diluted by ~44% and full-")
    print("   sample Sharpes are depressed by ~sqrt(3041/5452). This is the existing")
    print("   convention and it applies to every row equally, but it is worth naming.")
    print("2. Turnover is NOT matched WITHIN an era, so these columns rank eras, not")
    print("   constructions. They are here to show the win is not one lucky regime.\n")

    eras = [("2013-2016", "2013", "2016"), ("2017-2020", "2017", "2020"),
            ("2021-2026", "2021", "2026"), ("2013-2026 all", "2013", "2026")]
    Hj, Rj, _ = run_joint(c_m, z, vol_i, ret, adv, adv_mode="exit")
    era_books = [(f"w ~ alpha, {LIVE_POLICY}", band(Tp, BAND_WIDTH), Rp),
                 (f"w ~ alpha, band {b_m * 100:.1f}% + ADV exit",
                  band_hard_exit(Tp, b_m, E), Rp),
                 (f"w ~ Sig^-1 a, band {bi_m * 100:.1f}% + ADV exit",
                  band_hard_exit(Ti, bi_m, E), Ri),
                 (f"joint, c_model={c_m * 1e4:.1f}bp", Hj, Rj)]
    print(f"{'construction':<40}" + "".join(f"{e[0]:>19}" for e in eras))
    print(f"{'':<40}" + "".join(f"{'net@15 [turn]':>19}" for _ in eras))
    print("-" * (40 + 19 * len(eras)))
    tvar = {}
    for lab, H, R in era_books:
        cells, tv = [], []
        for _, a, b in eras:
            r = evaluate(H.loc[a:b], R.loc[a:b])
            net = (r["ann_ret"] - r["turn"] * 15 / 1e4) / r["vol"]
            cells.append(f"{net:>12.2f} [{r['turn']:4.1f}]")
            tv.append(r["turn"])
        tvar[lab] = np.array(tv[:-1])
        print(f"{lab:<40}" + "".join(cells))

    print("\nturnover stability across eras (the metric band_frontier.py tracks):")
    for lab, v in tvar.items():
        print(f"  {lab:<40} mean {v.mean():5.1f}   sd/mean {v.std() / v.mean():6.1%}")

    # ------------------------------------------- illiquidity sensitivity, uniform
    print("\n" + "=" * 96)
    print(f"SENSITIVITY: turnover in ADV-filtered names charged {ILLIQ_MULT:.0f}x, "
          f"uniformly")
    print("=" * 96)
    sh = (f"{'construction':<40}{'illiq%':>8}"
          + "".join(f"{'netI@' + str(c):>10}" for c in COSTS_BP))
    print(sh); print("-" * len(sh))
    for lab, st in ((f"w ~ alpha, {LIVE_POLICY}", ref),
                    (f"w ~ alpha, band {b_m * 100:.1f}% + ADV exit", sb_m),
                    (f"w ~ Sig^-1 a, {LIVE_POLICY}", base["inv_band"]),
                    (f"joint, c_model={c_m * 1e4:.1f}bp", s_m)):
        print(f"{lab:<40}{st['inelig'] * 100:>8.1f}"
              + "".join(f"{st['netI' + str(c2)]:>10.2f}" for c2 in COSTS_BP))
    return 0


if __name__ == "__main__":
    sys.exit(main())
