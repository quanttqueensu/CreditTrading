"""W10 Part B -- within-group selection vs between-group timing in the DEPLOYED
signal and book. Zero trials.

    python3 scripts/cef/w10_partb.py              # every section, to stdout
    python3 scripts/cef/w10_partb.py signal pnl   # chosen sections only

The write-up is results/cef/W10_PARTB_2026-10-12.md. The aggregates C2 needs
are written to results/cef/w10/alpha_decomposition.json.

WHAT PART B WAS DECLARED TO BE
------------------------------
The archived work order (`git show pre-clean-slate:_archive/docs/prompts/
W10_breadth_and_groups.md`, Part B, "trial: 0") splits the live demeaned
signal exactly,

    z_i - zbar = (zbar_g(i) - zbar) + (z_i - zbar_g(i))  =  between_i + within_i

and asks how much of the edge, the breadth and the borrow each part carries,
because C2 (Part C, two sleeves; Part D / F2, a conditional fair value per
group) cannot be designed until that is known. Its measurements, and what this
script does with each:

  1. IC by component, clustered by date, by era, fit and holdout ........ DONE,
     fit period only (the 2023-01-01 holdout stays sealed);
  2. "the harness table, each book at its natural turnover and matched to
     17.6x/yr" ...................................................... NOT RUN.
     A WITHIN book renormalised, vol-targeted and banded on its own is a NEW
     PORTFOLIO, scored against LIVE at matched turnover -- a variant
     comparison, which is a trial however the work order labelled it (and
     WITHIN-only is the graveyard's "hard group neutrality", 0.97 -> 0.82 on 17
     names). Replaced by an EXACT decomposition of the deployed book's own P&L
     (section `pnl`), the same kind of split W4 section 5 made into NAV and
     discount legs;
  3. correlation and attribution ......................................... DONE
     on the exact P&L legs (the no-intercept regression the work order asks
     for is trivial for an exact decomposition: both coefficients are 1);
  4. borrow by book ...................................... DONE as borrow by
     group of the deployed book, 2021-09-13..2022-12-30 (the fee panel's span
     inside the fit period);
  5. the random-group negative control, 20 draws ......................... DONE;
  6. group-by-group within IC ............................................ DONE.

THE TWO DEFINITIONS OF "BETWEEN", BOTH REPORTED
-----------------------------------------------
* `algebraic`: the identity above for every group, whatever its size. A
  singleton (JFR) has within = 0 by arithmetic.
* `declared`: the work order's rule, "a group with fewer than 3 eligible names
  on a date is treated the same way [as a singleton: between-only]". It was
  written for 17 names, where only hy (2) and loan (1) were small. On the v7
  13-name universe muni is 2 names too, so under this rule ONLY multi has a
  within component and the hy and muni pair spreads are booked as "between".
Neither is chosen on results; the note leads with the algebraic split because
it is the one whose between part is a pure group-level quantity (what a group
conditioner acts on), and gives the declared one beside it.

WHY SLOPES LEAD AND RANK ICs FOLLOW
-----------------------------------
In the algebraic split the two parts are orthogonal on every date
(sum_i between_i * within_i = 0, because within sums to zero inside each group
and between is constant inside it). So the deployed pooled slope of forward
return on z is EXACTLY the variance-share-weighted mean of the two component
slopes. If forward returns were linear in z with no group structure, BOTH
component slopes would equal the deployed slope for ANY grouping. The
negative control therefore tests `slope_between - slope_within`, not "a random
between IC near zero" as the work order expected: a random grouping's between
part is a coarse average of z and inherits z's slope (recorded as a
correction to the archived text, not silently). Rank ICs are reported beside
the slopes for comparability with W4, which reports both.

CONVENTIONS (inherited from W4, imported, not copied)
-----------------------------------------------------
Signal, deployed set, forward window (closes t+1 -> t+3), the non-overlapping
grid, the date-clustered / Newey-West / block-bootstrap errors and the P&L
harness are `scripts/cef/w4_artifacts.py`'s, which imports `evaluate()` and
the deployed policy from `band_frontier.py`. Group labels are the static `grp`
column of `data/cef/cef_universe.csv` -- a fixed classification, not an
estimate, so it carries no lookahead. Fit period only (2005-01-03 ..
2022-12-30); the deployed set first exists on 2013-06-21.

DATA (read-only): data/cef/cef_prices, cef_nav, cef_distributions,
cef_borrow_history (parquet), cef_universe.csv; the committed Alpaca probe
snapshot results/ops/alpaca_probe/2026-10-10_cef.json for today's live group
weights (positions only, no returns).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import HOLDOUT_START, evaluate  # noqa: E402
from scripts.cef.spec import MIN_NAMES, UNIVERSE, summary  # noqa: E402
from scripts.cef.w4_artifacts import (  # noqa: E402
    DEPLOYED_WIN, ERAS, FIT, FIT_END, IC_HDR, NW_LAGS, SEED, Data, _assert_fit,
    block_boot_t, fmt_ic, fwd, ic_row, ic_series, nw_t,
)

OUT_DIR = REPO / "results" / "cef" / "w10"
OUT_JSON = OUT_DIR / "alpha_decomposition.json"
PROBE = REPO / "results" / "ops" / "alpaca_probe" / "2026-10-10_cef.json"
GROUP_MIN_DECLARED = 3      # W10 Part B as archived: < 3 eligible -> between-only
N_RANDOM = 20               # W10 Part B item 5: "20 draws"
RULES = ("algebraic", "declared")
GROUPS = ("multi", "hy", "muni", "loan")
TOL = 1e-10


# =========================================================================== decomposition

def decompose_signal(z: pd.DataFrame, M: pd.DataFrame, grp: dict, rule: str):
    """(zb, zw): the between and within parts of z - zbar on the set M.

    zbar is the mean of z over the names M admits on that date (the deployed
    set); zbar_g the mean over the admitted names of group g. NaN outside M.
    ALIGNMENT (H7): a pure same-date transform of z_t and of M_t, both of which
    use data through t only (z's moments and the ADV filter are shifted one
    day in build_panel). Asserts the identity and the group-neutrality of the
    within part on every date; raises rather than returning a decomposition
    that does not add up."""
    if rule not in RULES:
        raise ValueError(f"rule {rule!r} not in {RULES}")
    zz = z.where(M)
    zbar = zz.mean(axis=1)
    zb = pd.DataFrame(np.nan, index=z.index, columns=z.columns)
    zw = pd.DataFrame(np.nan, index=z.index, columns=z.columns)
    for g in sorted(set(grp[t] for t in z.columns)):
        cols = [t for t in z.columns if grp[t] == g]
        sub = zz[cols]
        have = sub.notna()
        n_g = have.sum(axis=1)
        zbar_g = sub.mean(axis=1)
        b = have.mul(1.0).where(have).mul(zbar_g - zbar, axis=0)
        w = sub.sub(zbar_g, axis=0)
        if rule == "declared":
            small = n_g < GROUP_MIN_DECLARED
            b.loc[small] = sub.loc[small].sub(zbar[small], axis=0)
            w.loc[small] = sub.loc[small].mul(0.0)
        zb[cols], zw[cols] = b, w
        # within is group-neutral on every date the group appears
        s = w.sum(axis=1, min_count=1).dropna()
        if (s.abs() > TOL).any():
            raise AssertionError(f"within part of group {g} does not sum to zero")
    resid = (zb + zw) - zz.sub(zbar, axis=0)
    if (resid.abs().max().max() > TOL) or (zb.notna() != zz.notna()).any().any():
        raise AssertionError("between + within != z - zbar on the admitted set")
    if (zb.sum(axis=1, min_count=1).dropna().abs() > TOL).any():
        raise AssertionError("between part does not sum to zero across the admitted set")
    return zb, zw


def decompose_holdings(H: pd.DataFrame, grp: dict, rule: str):
    """(B, W) with B + W == H exactly, W summing to zero inside every group.

    B spreads each group's NET held weight equally over the group's HELD names
    (H != 0); W is each name's deviation from that. Because sum_g(B) is the
    group net weights and W is group-neutral, P&L(B) = sum_g net_g * mean
    return of g's held names, and P&L(W) = sum_i (H_i - hbar_g)(r_i - rbar_g),
    exactly. Both are functions of H on the decision date only, so evaluate()
    applies the same shift(2) to them as to H. A group with no held name has
    B = W = 0 there: a genuine zero (nothing held), not a filled value.
    `declared`: a group with fewer than GROUP_MIN_DECLARED held names is
    between-only (B = H, W = 0)."""
    if rule not in RULES:
        raise ValueError(f"rule {rule!r} not in {RULES}")
    B = pd.DataFrame(0.0, index=H.index, columns=H.columns)
    for g in sorted(set(grp[t] for t in H.columns)):
        cols = [t for t in H.columns if grp[t] == g]
        h = H[cols]
        held = h.ne(0.0)
        n = held.sum(axis=1).to_numpy()
        net = h.sum(axis=1).to_numpy()
        hbar = np.divide(net, n, out=np.zeros_like(net), where=n > 0)
        b = np.where(held.to_numpy(), hbar[:, None], 0.0)
        if rule == "declared":
            small = (n < GROUP_MIN_DECLARED)[:, None]
            b = np.where(small, h.to_numpy(), b)
        B[cols] = b
    W = H - B
    if (B + W - H).abs().max().max() > 1e-15:
        raise AssertionError("B + W != H")
    for g in set(grp.values()):
        cols = [t for t in H.columns if grp[t] == g]
        if (W[cols].sum(axis=1).abs() > TOL).any():
            raise AssertionError(f"W is not neutral inside group {g}")
    return B, W


# =========================================================================== statistics

def pooled_components(zb, zw, F, M, dates):
    """Pooled slopes (bp of forward return per unit z) of the two components,
    their difference, and date-clustered t's, on the cross-sectionally demeaned
    forward return. Per-date sums are the cluster scores (H6).

    Returns a dict and the per-date frame of sums (for the bootstrap)."""
    zb, zw, F = zb.reindex(dates), zw.reindex(dates), F.reindex(dates)
    ok = M.reindex(dates, fill_value=False) & zb.notna() & F.notna()
    n = ok.sum(axis=1)
    ok = ok & (n >= MIN_NAMES).to_numpy()[:, None]
    f = F.where(ok)
    f = f.sub(f.mean(axis=1), axis=0)
    b, w = zb.where(ok), zw.where(ok)
    # The decomposition was made on the full admitted set; dropping a name for a
    # missing forward return leaves b and w a few bp off mean zero on that date.
    # Re-centre each on the scored set so the identity zb + zw = z - zbar holds
    # on exactly the names scored (the slope of a mean-zero regressor on a
    # demeaned target is unaffected by the target's mean either way).
    b = b.sub(b.mean(axis=1), axis=0)
    w = w.sub(w.mean(axis=1), axis=0)
    per = pd.DataFrame({
        "Sbf": (b * f).sum(axis=1), "Sbb": (b * b).sum(axis=1),
        "Swf": (w * f).sum(axis=1), "Sww": (w * w).sum(axis=1),
        "Sbw": (b * w).sum(axis=1),
    })[ok.any(axis=1)]
    G = len(per)
    if G < 10:
        return dict(G=G), per
    bb = per.Sbf.sum() / per.Sbb.sum()
    bw = per.Swf.sum() / per.Sww.sum()
    sz = per.Sbb.sum() + per.Sww.sum() + 2 * per.Sbw.sum()
    bz = (per.Sbf.sum() + per.Swf.sum()) / sz
    eb = (per.Sbf - bb * per.Sbb) / per.Sbb.sum()
    ew = (per.Swf - bw * per.Sww) / per.Sww.sum()
    ez = (per.Sbf + per.Swf - bz * (per.Sbb + per.Sww + 2 * per.Sbw)) / sz
    c = G / (G - 1)
    se = lambda e: np.sqrt(c * (e ** 2).sum())
    return dict(
        G=G, slope_z=bz * 1e4, t_z=bz / se(ez),
        slope_between=bb * 1e4, t_between=bb / se(eb),
        slope_within=bw * 1e4, t_within=bw / se(ew),
        diff_b_minus_w=(bb - bw) * 1e4, t_diff=(bb - bw) / se(eb - ew),
        var_share_between=per.Sbb.sum() / sz,
        cross_share=2 * per.Sbw.sum() / sz,
        cov_share_between=per.Sbf.sum() / (per.Sbf.sum() + per.Swf.sum()),
    ), per


def within_ic(z, F, M, grp, dates, rule):
    """Spearman of the within part against the forward return demeaned INSIDE
    each group, over names whose group has a within part on that date (>= 2
    admitted names algebraically; >= GROUP_MIN_DECLARED under `declared`)."""
    zb, zw = decompose_signal(z, M, grp, rule)
    Fm = F.where(M)
    Fw = pd.DataFrame(np.nan, index=F.index, columns=F.columns)
    keep = pd.DataFrame(False, index=F.index, columns=F.columns)
    floor = 2 if rule == "algebraic" else GROUP_MIN_DECLARED
    for g in set(grp.values()):
        cols = [t for t in F.columns if grp[t] == g]
        have = M[cols] & F[cols].notna() & z[cols].notna()
        Fw[cols] = Fm[cols].where(have).sub(Fm[cols].where(have).mean(axis=1), axis=0)
        keep[cols] = have & (have.sum(axis=1) >= floor).to_numpy()[:, None]
    return ic_series(zw, Fw, keep, dates, min_n=4)


def group_level(z, F, M, grp, dates):
    """One observation per group per date: mean z and mean forward return of the
    group's admitted names. Returns (Spearman across groups on dates with >= 3
    groups, the per-date sign agreement on dates with >= 2 groups)."""
    zz, ff = z.where(M & F.notna()), F.where(M & F.notna())
    gz = pd.concat({g: zz[[t for t in z.columns if grp[t] == g]].mean(axis=1) for g in GROUPS}, axis=1)
    gf = pd.concat({g: ff[[t for t in z.columns if grp[t] == g]].mean(axis=1) for g in GROUPS}, axis=1)
    gz, gf = gz.reindex(dates), gf.reindex(dates)
    ng = gz.notna().sum(axis=1)
    M3 = gz.notna() & (ng >= 3).to_numpy()[:, None]
    ic3 = ic_series(gz, gf, M3, dates, min_n=3)
    # Pooled group-level slope (bp per unit of group-mean z), date-clustered
    two = np.repeat((ng >= 2).to_numpy()[:, None], gz.shape[1], axis=1)
    gzd = gz.sub(gz.mean(axis=1), axis=0).where(two)
    gfd = gf.sub(gf.mean(axis=1), axis=0).where(two)
    Sxy, Sxx = (gzd * gfd).sum(axis=1), (gzd ** 2).sum(axis=1)
    keep = Sxx > 0
    Sxy, Sxx = Sxy[keep], Sxx[keep]
    b = Sxy.sum() / Sxx.sum()
    e = (Sxy - b * Sxx) / Sxx.sum()
    G = len(Sxx)
    t = b / np.sqrt(G / (G - 1) * (e ** 2).sum())
    return ic3, dict(G=G, slope_bp=b * 1e4, t=t, n_dates_ge3=int((ng >= 3).sum()),
                     n_groups_mean=float(ng[ng > 0].mean()))


def pair_sign(z, F, M, a, b, dates):
    """Two-name group: +1 when the richer name (higher z) underperforms over the
    forward window (the signal's prediction), -1 when it outperforms."""
    ok = (M[a] & M[b] & z[a].notna() & z[b].notna() & F[a].notna() & F[b].notna()).reindex(dates, fill_value=False)
    d = dates[ok.to_numpy()]
    dz = (z.loc[d, a] - z.loc[d, b])
    dF = (F.loc[d, a] - F.loc[d, b])
    s = -np.sign(dz) * np.sign(dF)
    return s[(dz != 0) & (dF != 0)]


def t_of_mean(x: pd.Series) -> float:
    x = x.dropna()
    return x.mean() / x.std(ddof=1) * np.sqrt(len(x)) if len(x) > 2 else np.nan


# =========================================================================== sections

def sec_signal(D: Data, out: dict):
    """1. The signal: implied mix, variance shares, component slopes and ICs."""
    print("\n" + "=" * 100 + "\n1. THE SIGNAL: between and within parts of z on the DEPLOYED set\n" + "=" * 100)
    F = fwd(D.r_tr, *DEPLOYED_WIN)
    for rule in RULES:
        zb, zw = decompose_signal(D.z, D.M_dep, D.grp, rule)
        _assert_fit(zb, zw)
        print(f"\n--- rule: {rule} " + ("(every group split by the identity)" if rule == "algebraic"
                                     else f"(W10 as archived: < {GROUP_MIN_DECLARED} eligible names -> between-only)"))
        # small date-groups
        Mg = {g: D.M_dep[[t for t in D.U if D.grp[t] == g]].sum(axis=1) for g in GROUPS}
        live = D.M_dep.any(axis=1)
        print("  eligible names per group on deployed dates (mean; share of dates with 0 / 1 / 2 / >=3):")
        for g in GROUPS:
            n = Mg[g][live]
            print(f"    {g:<6} mean {n.mean():4.2f}   0: {(n == 0).mean():5.1%}  1: {(n == 1).mean():5.1%}  "
                  f"2: {(n == 2).mean():5.1%}  >=3: {(n >= 3).mean():5.1%}")
        mix = (zb.abs().sum(axis=1) / (zb.abs().sum(axis=1) + zw.abs().sum(axis=1)))[live]
        vs = ((zb ** 2).sum(axis=1) / ((zb + zw) ** 2).sum(axis=1))[live]
        print(f"  implied mix sum|between| / sum(|between|+|within|) per date: mean {mix.mean():.3f}, "
              f"median {mix.median():.3f}, p10 {mix.quantile(.1):.3f}, p90 {mix.quantile(.9):.3f}")
        print(f"  between share of the cross-sectional variance of z per date: mean {vs.mean():.3f}, "
              f"median {vs.median():.3f}")
        for lab, a, b in ERAS[1:] + [FIT]:
            m = mix.loc[a:b]
            if len(m):
                print(f"    {lab:<12} mix mean {m.mean():.3f}   variance share mean {vs.loc[a:b].mean():.3f}   dates {len(m)}")
        # pooled slopes, the decisive split
        print("\n  pooled slope of the demeaned forward return [t+2,t+3] (bp per unit z), date-clustered t:")
        print(f"  {'grid':<14}{'dates':>6}{'z':>8}{'t':>7}{'between':>9}{'t':>7}{'within':>9}{'t':>7}"
              f"{'b-w':>8}{'t':>7}{'var sh b':>9}{'cov sh b':>9}")
        res = {}
        for ph, G in (("phase 0", D.G0), ("phase 1", D.G1)):
            for lab, a, b in ([("fit " + ph, None, None)] +
                              ([(f"{e[0]} {ph}", e[1], e[2]) for e in ERAS[1:]] if ph == "phase 0" else [])):
                Gs = G if a is None else G[(G >= a) & (G <= b)]
                r, _ = pooled_components(zb, zw, F, D.M_dep, Gs)
                if r.get("G", 0) < 10:
                    print(f"  {lab:<14}{r.get('G', 0):6d}   (fewer than 10 dates)")
                    continue
                print(f"  {lab:<14}{r['G']:6d}{r['slope_z']:8.2f}{r['t_z']:7.2f}{r['slope_between']:9.2f}"
                      f"{r['t_between']:7.2f}{r['slope_within']:9.2f}{r['t_within']:7.2f}"
                      f"{r['diff_b_minus_w']:8.2f}{r['t_diff']:7.2f}{r['var_share_between']:9.3f}"
                      f"{r['cov_share_between']:9.3f}")
                res[lab] = r
        out.setdefault("signal", {})[rule] = res
        # rank ICs beside the slopes (W4 comparability)
        print("\n  rank IC (Spearman, H6), DEPLOYED set, total returns:")
        print("  " + IC_HDR)
        ics = {}
        for ph, G in (("p0", D.G0), ("p1", D.G1)):
            for lab, S, FF, MM in (("z (deployed, the W4 baseline)", D.z, F, D.M_dep),
                                   ("between part", zb, F, D.M_dep),
                                   ("within part, whole cross-section", zw, F, D.M_dep)):
                ic = ic_series(S, FF, MM, G)
                print("  " + fmt_ic(f"{lab} {ph}", ic))
                ics[f"{lab} {ph}"] = ic_row(ic)
            icw = within_ic(D.z, F, D.M_dep, D.grp, G, rule)
            print("  " + fmt_ic(f"within part vs within-group fwd return {ph}", icw))
            ics[f"within proper {ph}"] = ic_row(icw)
        out["signal"][rule + "_ic"] = {k: {kk: float(vv) for kk, vv in v.items()} for k, v in ics.items()}

    # group level (rule-free: one observation per group)
    print("\n--- group level: the four group-mean z's against the group-mean forward returns")
    for ph, G in (("phase 0", D.G0), ("phase 1", D.G1)):
        ic3, gl = group_level(D.z, F, D.M_dep, D.grp, G)
        tb, lo, hi = block_boot_t(ic3)
        print(f"  {ph}: dates with >= 2 groups {gl['G']}, mean groups present {gl['n_groups_mean']:.2f}; "
              f"pooled group-level slope {gl['slope_bp']:+.2f} bp per unit group-mean z (t {gl['t']:.2f})")
        print(f"  {ph}: Spearman across groups on the {len(ic3)} dates with >= 3 groups: mean {ic3.mean():+.4f} "
              f"(t {ic_row(ic3)['t']:.2f}, NW {nw_t(ic3):.2f}, block bootstrap t {tb:.2f}, 95% [{lo:+.3f}, {hi:+.3f}]); "
              f"share < 0: {(ic3 < 0).mean():.3f}")
        out.setdefault("group_level", {})[ph] = dict(gl, spearman_mean=float(ic3.mean()), spearman_n=int(len(ic3)),
                                                     spearman_t=float(ic_row(ic3)["t"]))

    # WIDE set (context): the composition the live book trades today
    print("\n--- WIDE set (CONTEXT, not the deployed fit-period signal): the 13 names with a z-score, no ADV "
          "filter, >= min_names. On the current universe file every one of the 13 clears the ADV floor, so "
          "this is the closest fit-period analogue of TODAY's book, munis and JFR included. Algebraic rule.")
    Mw = D.M_wide & (D.M_wide.sum(axis=1) >= MIN_NAMES).to_numpy()[:, None]
    for g in GROUPS:
        n = Mw[[t for t in D.U if D.grp[t] == g]].sum(axis=1)[Mw.any(axis=1)]
        print(f"    {g:<6} mean eligible {n.mean():4.2f}")
    zbw, zww = decompose_signal(D.z, Mw, D.grp, "algebraic")
    print(f"  {'grid':<16}{'dates':>6}{'z':>8}{'t':>7}{'between':>9}{'t':>7}{'within':>9}{'t':>7}"
          f"{'b-w':>8}{'t':>7}{'var sh b':>9}{'cov sh b':>9}")
    wres = {}
    for lab, a, b in [("fit 2005-22", None, None)] + [(e[0], e[1], e[2]) for e in ERAS] + \
            [("2013-06..2022", "2013-06-21", FIT_END)]:
        Gs = D.G0 if a is None else D.G0[(D.G0 >= a) & (D.G0 <= b)]
        r, _ = pooled_components(zbw, zww, F, Mw, Gs)
        if r.get("G", 0) < 10:
            continue
        print(f"  {lab:<16}{r['G']:6d}{r['slope_z']:8.2f}{r['t_z']:7.2f}{r['slope_between']:9.2f}"
              f"{r['t_between']:7.2f}{r['slope_within']:9.2f}{r['t_within']:7.2f}"
              f"{r['diff_b_minus_w']:8.2f}{r['t_diff']:7.2f}{r['var_share_between']:9.3f}"
              f"{r['cov_share_between']:9.3f}")
        wres[lab] = r
    ic3w, glw = group_level(D.z, F, Mw, D.grp, D.G0)
    print(f"  group level (WIDE, phase 0): pooled slope {glw['slope_bp']:+.2f} bp per unit group-mean z "
          f"(t {glw['t']:.2f}); Spearman across groups mean {ic3w.mean():+.4f} (t {ic_row(ic3w)['t']:.2f}) on "
          f"{len(ic3w)} dates with >= 3 groups")
    out["signal"]["wide_context"] = wres
    out["signal"]["wide_group_level"] = glw

    # item 6: group by group within IC
    print("\n--- item 6: within each group separately (DEPLOYED set, [t+2,t+3] total return)")
    multi = [t for t in D.U if D.grp[t] == "multi"]
    Mm = D.M_dep.copy()
    Mm[[t for t in D.U if t not in multi]] = False
    for ph, G in (("p0", D.G0), ("p1", D.G1)):
        print("  " + fmt_ic(f"multi (8 names; >= 4 admitted) {ph}", ic_series(D.z, F, Mm, G, min_n=4)))
    for g in ("hy", "muni"):
        a, b = [t for t in D.U if D.grp[t] == g]
        for ph, G in (("p0", D.G0), ("p1", D.G1)):
            s = pair_sign(D.z, F, D.M_dep, a, b, G)
            print(f"  {g} pair {a}/{b} {ph}: dates {len(s)}, share where the richer name underperforms "
                  f"{(s > 0).mean() if len(s) else float('nan'):.3f}, mean sign {s.mean() if len(s) else float('nan'):+.3f} "
                  f"(t {t_of_mean(s):.2f})")
            out.setdefault("pairs", {})[f"{g} {ph}"] = dict(n=int(len(s)), share=float((s > 0).mean()) if len(s) else None)
    print("  loan: JFR is the only loan name; no within-group statistic exists.")


def sec_control(D: Data, out: dict):
    """2. Negative control: random group assignments, same sizes, 20 draws."""
    print("\n" + "=" * 100 + "\n2. NEGATIVE CONTROL: random group labels (same group sizes), "
          f"{N_RANDOM} draws, seed {SEED}\n" + "=" * 100)
    F = fwd(D.r_tr, *DEPLOYED_WIN)
    labels = [D.grp[t] for t in D.U]
    rng = np.random.default_rng(SEED)
    print("Under 'groups do not matter' the between and within slopes are equal for ANY grouping (see the "
          "module docstring), so the statistic is slope(between) - slope(within). Phase 0 grid, algebraic rule.")
    real, _ = pooled_components(*decompose_signal(D.z, D.M_dep, D.grp, "algebraic"), F, D.M_dep, D.G0)
    rows = []
    for k in range(N_RANDOM):
        perm = rng.permutation(labels)
        g = dict(zip(D.U, perm))
        r, _ = pooled_components(*decompose_signal(D.z, D.M_dep, g, "algebraic"), F, D.M_dep, D.G0)
        rows.append(r)
    R = pd.DataFrame(rows)
    print(f"{'':<22}{'between':>9}{'within':>9}{'b-w':>8}{'t(b-w)':>8}{'var sh b':>9}{'cov sh b':>9}")
    print(f"{'real groups':<22}{real['slope_between']:9.2f}{real['slope_within']:9.2f}{real['diff_b_minus_w']:8.2f}"
          f"{real['t_diff']:8.2f}{real['var_share_between']:9.3f}{real['cov_share_between']:9.3f}")
    for lab, f in (("random: mean", R.mean()), ("random: min", R.min()), ("random: max", R.max())):
        print(f"{lab:<22}{f['slope_between']:9.2f}{f['slope_within']:9.2f}{f['diff_b_minus_w']:8.2f}"
              f"{f['t_diff']:8.2f}{f['var_share_between']:9.3f}{f['cov_share_between']:9.3f}")
    rank = int((R["diff_b_minus_w"] < real["diff_b_minus_w"]).sum())
    print(f"real b-w ranks above {rank} of {N_RANDOM} random draws; random |t(b-w)| > 2 in "
          f"{int((R['t_diff'].abs() > 2).sum())} of {N_RANDOM}")
    out["control"] = dict(real=real, random_mean=R.mean().to_dict(), random_min=R.min().to_dict(),
                          random_max=R.max().to_dict(), real_rank_of_diff=rank, n=N_RANDOM)


def sec_pnl(D: Data, out: dict):
    """3. The deployed P&L, split exactly into the group-net (between) and the
    group-neutral (within) legs; correlation, variance shares, group nets."""
    print("\n" + "=" * 100 + "\n3. THE DEPLOYED P&L, SPLIT EXACTLY INTO BETWEEN AND WITHIN LEGS\n" + "=" * 100)
    H, R = D.H, D.R_tr
    pt = evaluate(H, R)["pnl"]
    live0 = pt.index[pt.ne(0)].min()
    print(f"deployed policy {summary()}; TOTAL returns; book live from {live0.date()}. "
          "Gross only on the legs: costs belong to the traded total and are not split.")
    r0 = evaluate(H, R)
    print(f"regression check against W4: fit gross SR {r0['gross_sr']:.2f}, turnover {r0['turn']:.1f}/yr")
    windows = [(e[0], e[1], e[2]) for e in ERAS[1:]] + [FIT, ("live 2013-06..2022", live0, FIT_END)]
    for rule in RULES:
        B, W = decompose_holdings(H, D.grp, rule)
        pb, pw = evaluate(B, R)["pnl"], evaluate(W, R)["pnl"]
        if not np.allclose(pb + pw, pt, atol=1e-15):
            raise AssertionError("legs do not add to the deployed P&L")
        net = H.sum(axis=1)
        nheld = H.ne(0).sum(axis=1)
        # the book's NET weight spread equally over every held name: P&L(Nw) is
        # net x the equal-weight return of the held names; between - Nw is the
        # pure group-spread part (it sums to zero across names).
        nbar = pd.Series(np.divide(net.to_numpy(), nheld.to_numpy(), out=np.zeros(len(net)),
                                   where=nheld.to_numpy() > 0), index=H.index)
        Nw = H.ne(0).astype(float).mul(nbar, axis=0)
        pn = evaluate(Nw, R)["pnl"]
        ps = pb - pn
        print(f"\n--- rule: {rule}")
        print(f"  legs add to the total exactly (max |diff| {(pb + pw - pt).abs().max():.1e})")
        print(f"{'':<4}{'window':<22}{'leg':<26}{'ann%':>7}{'vol%':>7}{'grossSR':>8}{'share of total ret':>20}")
        res = {}
        for lab, a, b in windows:
            T_ = pt.loc[a:b]
            if T_.abs().sum() == 0:
                continue
            for leg, x in (("TOTAL (deployed)", pt), ("between (group nets)", pb),
                           ("  of which book net", pn), ("  of which group spread", ps),
                           ("within (group-neutral)", pw)):
                s = x.loc[a:b]
                sr = s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else np.nan
                print(f"{'':<4}{lab:<22}{leg:<26}{s.mean() * 252 * 100:7.2f}{s.std() * np.sqrt(252) * 100:7.2f}"
                      f"{sr:8.2f}{s.mean() / T_.mean():20.2f}")
                res[f"{lab} | {leg.strip()}"] = dict(ann=float(s.mean() * 252), vol=float(s.std() * np.sqrt(252)),
                                                     sr=float(sr), share=float(s.mean() / T_.mean()))
        L = pt.loc[live0:FIT_END].index
        vb, vw, c = pb.loc[L].var(), pw.loc[L].var(), pb.loc[L].cov(pw.loc[L])
        vt = pt.loc[L].var()
        rho = pb.loc[L].corr(pw.loc[L])
        print(f"  live days: corr(between, within) {rho:+.3f}; variance shares of the total: between "
              f"{vb / vt:.3f}, within {vw / vt:.3f}, 2cov {2 * c / vt:+.3f}")
        gb, gw, gh = B.abs().sum(axis=1).loc[L], W.abs().sum(axis=1).loc[L], H.abs().sum(axis=1).loc[L]
        mixh = gb / (gb + gw)
        print(f"  gross held: total {gh.mean():.3f}; between leg {gb.mean():.3f}; within leg {gw.mean():.3f}. "
              f"Held-book mix sum|B| / (sum|B| + sum|W|): mean {mixh.mean():.3f}, median {mixh.median():.3f}, "
              f"p90 {mixh.quantile(.9):.3f}, max {mixh.max():.3f} (the measure section 6 applies to today's book)")
        res["held_mix_mean"], res["held_mix_p90"] = float(mixh.mean()), float(mixh.quantile(.9))
        # by-era correlation
        for lab, a, b in ERAS[2:]:
            print(f"    corr(between, within) {lab}: {pb.loc[a:b].corr(pw.loc[a:b]):+.3f}")
        # the indicative two-sleeve arithmetic, gross, labelled
        srb = res[f"live 2013-06..2022 | between (group nets)"]["sr"]
        srw = res[f"live 2013-06..2022 | within (group-neutral)"]["sr"]
        vw_, vb_ = (srw - rho * srb), (srb - rho * srw)
        print(f"  INDICATIVE ONLY (gross legs of the one deployed book, not Part C's separately built, "
              f"net-of-borrow sleeves): Part C's split (v_w, v_b) ~ (IR_w - rho IR_b, IR_b - rho IR_w) = "
              f"({vw_:+.3f}, {vb_:+.3f}); the between leg would get "
              f"{'ZERO budget' if vb_ <= 0 else f'{vb_ / (abs(vw_) + abs(vb_)):.0%} of the weight'}")
        res["rho_live"] = float(rho)
        res["var_share_between"], res["var_share_within"], res["var_share_2cov"] = (
            float(vb / vt), float(vw / vt), float(2 * c / vt))
        res["indicative_split"] = dict(v_w=float(vw_), v_b=float(vb_))
        out.setdefault("pnl", {})[rule] = res

    # active vs frozen: build_targets HOLDS the previous target on a date with fewer
    # than min_names eligible names, so the book is re-decided only on deployed dates
    active = D.M_dep.any(axis=1).reindex(H.index, fill_value=False)
    dec = active.shift(2, fill_value=False)          # P&L on t was decided at t-2 (evaluate's shift(2))
    Lx = pt.loc[live0:FIT_END].index
    last_active = pd.Series(np.where(active, np.arange(len(active)), np.nan), index=active.index).ffill()
    age = (pd.Series(np.arange(len(active)), index=active.index) - last_active).shift(2)
    print(f"\n  active vs frozen (live 2013-06..2022, {len(Lx)} sessions): the deployed set exists on "
          f"{active.loc[Lx].mean():.1%} of them; on the rest the target is HELD (build_targets). P&L by the "
          f"state of the decision date t-2:")
    for lab, m in (("decided on an active date", dec.loc[Lx]), ("held from an earlier active date", ~dec.loc[Lx]),
                   ("  of which held >= 21 sessions", (~dec.loc[Lx]) & (age.loc[Lx] >= 21))):
        x = pt.loc[Lx][m]
        print(f"    {lab:<34} sessions {int(m.sum()):5d}   ann {x.mean() * 252 * 100:+6.2f}%   "
              f"SR {x.mean() / x.std() * np.sqrt(252):+5.2f}   share of total P&L {x.sum() / pt.loc[Lx].sum():.2f}")
    out["active_share"] = float(active.loc[Lx].mean())

    # between leg by group, and the group net weights (rule-free)
    B, W = decompose_holdings(H, D.grp, "algebraic")
    L = pt.loc[live0:FIT_END].index
    gross = H.abs().sum(axis=1)
    print("\n  between leg by group (live 2013-06..2022, ann %), and each group's NET weight as a share of "
          "gross held (mean, mean |.|, p95 |.|):")
    gnet = {}
    for g in GROUPS:
        cols = [t for t in D.U if D.grp[t] == g]
        Bg = B.copy()
        Bg[[t for t in D.U if t not in cols]] = 0.0
        x = evaluate(Bg, R)["pnl"].loc[L]
        nw = (H[cols].sum(axis=1) / gross.replace(0, np.nan)).loc[L]
        print(f"    {g:<6} between ann {x.mean() * 252 * 100:+6.2f}%   SR {x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan:+6.2f}"
              f"   net/gross mean {nw.mean():+.3f}  mean|.| {nw.abs().mean():.3f}  p95|.| {nw.abs().quantile(.95):.3f}")
        gnet[g] = dict(between_ann=float(x.mean() * 252), net_over_gross_mean=float(nw.mean()),
                       abs_mean=float(nw.abs().mean()), abs_p95=float(nw.abs().quantile(.95)))
    out["group_net"] = gnet


def sec_breadth(D: Data, out: dict):
    """4. Effective breadth of the deployed book at month-ends, by the archived
    dashboard definition, and the ex-ante risk share of the between leg."""
    from sklearn.covariance import LedoitWolf
    print("\n" + "=" * 100 + "\n4. EFFECTIVE BREADTH (archived dashboard `_decompose` definition)\n" + "=" * 100)
    print("BR_eff = 1 / sum(share_k^2), share_k = variance share of principal component k of the HELD book, "
          "Ledoit-Wolf covariance of the held names' price returns over the trailing 252 sessions through the "
          "month-end (>= 120 joint rows, else not computed). `git show pre-clean-slate:_archive/dashboard/"
          "server.py` lines 1445-1555.")
    H = D.H
    ret = D.p["ret"][D.U]
    B, W = decompose_holdings(H, D.grp, "algebraic")
    me = H.index.to_series().groupby(H.index.to_period("M")).max()
    rows, skipped = [], 0
    for d in me:
        w = H.loc[d]
        names = [t for t in D.U if abs(w[t]) > 1e-9]
        if len(names) < 3:
            continue
        hist = ret.loc[:d, names].tail(252).dropna()
        _assert_fit(hist)
        if len(hist) < 120:
            skipped += 1
            continue
        S = LedoitWolf().fit(hist.values).covariance_
        wv = w[names].to_numpy()
        ev, V = np.linalg.eigh(S)
        o = np.argsort(ev)[::-1]
        ev, V = np.clip(ev[o], 1e-18, None), V[:, o]
        var = (V.T @ wv) ** 2 * ev
        share = var / var.sum()
        bv, wvv = B.loc[d, names].to_numpy(), W.loc[d, names].to_numpy()
        tot = wv @ S @ wv
        rows.append(dict(date=d, n=len(names), br_eff=1.0 / np.sum(share ** 2), pc1=share[0],
                         risk_between=bv @ S @ bv / tot, risk_within=wvv @ S @ wvv / tot,
                         risk_cross=2 * bv @ S @ wvv / tot))
    X = pd.DataFrame(rows).set_index("date")
    print(f"month-ends computed {len(X)}, skipped for < 120 joint rows {skipped}")
    print(f"{'era':<12}{'n':>4}{'names':>7}{'BR_eff med':>11}{'p10':>6}{'p90':>6}{'PC1 sh':>8}"
          f"{'risk b':>8}{'risk w':>8}{'2cov':>7}")
    res = {}
    for lab, a, b in ERAS[1:] + [FIT]:
        x = X.loc[a:b]
        if not len(x):
            continue
        print(f"{lab:<12}{len(x):4d}{x.n.mean():7.1f}{x.br_eff.median():11.2f}{x.br_eff.quantile(.1):6.2f}"
              f"{x.br_eff.quantile(.9):6.2f}{x.pc1.median():8.3f}{x.risk_between.median():8.3f}"
              f"{x.risk_within.median():8.3f}{x.risk_cross.median():7.3f}")
        res[lab] = dict(n=int(len(x)), br_eff_median=float(x.br_eff.median()), pc1_median=float(x.pc1.median()),
                        risk_between_median=float(x.risk_between.median()),
                        risk_within_median=float(x.risk_within.median()))
    out["breadth"] = res


def sec_borrow(D: Data, out: dict):
    """5. Borrow by group on the deployed holdings, 2021-09-13 .. 2022-12-30."""
    print("\n" + "=" * 100 + "\n5. BORROW BY GROUP (deployed holdings; fee panel span inside the fit period)\n" + "=" * 100)
    b = pd.read_parquet(REPO / "data/cef/cef_borrow_history.parquet")
    b["date"] = pd.to_datetime(b["date"])
    b = b[(b.date < HOLDOUT_START) & b.ticker.isin(D.U)]
    fee = b.pivot_table(index="date", columns="ticker", values="fee_rate_pct")
    start = fee.index.min()
    # the position HELD during session t is the one decided at t-2 (evaluate's shift(2))
    Hs = D.H.shift(2).loc[start:FIT_END]
    short = (-Hs).clip(lower=0.0)
    f = fee.reindex(index=short.index, columns=D.U)
    need = short > 0
    miss = need & f.isna()
    print(f"window {short.index.min().date()}..{short.index.max().date()} ({len(short)} sessions). Held short "
          f"name-days {int(need.sum().sum())}; with no fee row {int(miss.sum().sum())} "
          f"({miss.sum().sum() / max(need.sum().sum(), 1):.1%}) -- excluded and counted, never filled.")
    cost = (short * f / 100.0).where(need & f.notna())          # annual rate x weight, per session
    tot = cost.sum(axis=1, min_count=0).mean()
    print("Annualised borrow = mean over sessions of sum(short weight x annual fee rate); a simple annual-rate "
          "convention (IBKR accrued MV x 102% x fee / 360 per calendar day, about 3% more).")
    print(f"  TOTAL book: {tot * 100:.3f}%/yr of capital")
    res = {"total_pct_yr": float(tot * 100)}
    for g in GROUPS:
        cols = [t for t in D.U if D.grp[t] == g]
        x = cost[cols].sum(axis=1, min_count=0).mean()
        sh = short[cols].sum(axis=1).mean()
        mf = f[cols].where(need[cols]).stack().mean()
        print(f"  {g:<6} {x * 100:6.3f}%/yr ({x / tot if tot else np.nan:5.1%} of the bill); mean short weight "
              f"{sh:.3f}; mean fee on held shorts {mf:.2f}%")
        res[g] = dict(pct_yr=float(x * 100), share=float(x / tot) if tot else None)
    # second method: per name, mean short weight x mean fee on held days, re-summed
    # (an independent arithmetic route to the same order of magnitude; the two
    # differ by the covariance of weight and fee over time, which is reported)
    print("  by name (window above): mean short weight over all sessions, mean fee on the sessions it was "
          "short, their product, and the exact time-average of weight x fee:")
    per = []
    for t in D.U:
        w_ = short[t]
        f_ = f[t].where(need[t])
        prod = float(w_.mean() * (f_.mean() if need[t].any() else 0.0) / 100)
        exact = float(cost[t].sum(min_count=0) / len(cost))
        per.append((t, D.grp[t], w_.mean(), f_.mean(), prod, exact))
    P_ = pd.DataFrame(per, columns=["ticker", "grp", "mean_short_w", "mean_fee_pct", "w_x_fee", "exact"])
    print(P_.to_string(index=False, float_format=lambda v: f"{v:8.4f}"))
    print(f"  sum of products {P_.w_x_fee.sum() * 100:.3f}%/yr vs exact {P_.exact.sum() * 100:.3f}%/yr")
    res["by_name"] = P_.set_index("ticker")[["mean_short_w", "mean_fee_pct", "exact"]].to_dict("index")

    # shorts in a net-short group (the between bet's short side) vs a net-long group
    B, W = decompose_holdings(D.H, D.grp, "algebraic")
    Bs = B.shift(2).loc[start:FIT_END]
    in_net_short = Bs < 0
    xs = cost.where(in_net_short).sum(axis=1, min_count=0).mean()
    print(f"  shorts held while their group is net short (the between bet's short side): {xs * 100:.3f}%/yr "
          f"({xs / tot if tot else np.nan:.1%} of the bill)")
    res["in_net_short_group_share"] = float(xs / tot) if tot else None
    out["borrow"] = res


def sec_today(D: Data, out: dict):
    """6. Today's live book (Alpaca probe snapshot): group net weights. Positions only."""
    print("\n" + "=" * 100 + "\n6. TODAY'S LIVE BOOK: group nets from the committed Alpaca probe snapshot\n" + "=" * 100)
    s = json.loads(PROBE.read_text())
    pos = {p["symbol"]: float(p["market_value"]) for p in s["positions"]}
    eq = float(s["account"]["equity"])
    unknown = sorted(set(pos) - set(D.U))
    if unknown:
        raise ValueError(f"positions outside the spec universe: {unknown}")
    w = pd.Series({t: pos.get(t, 0.0) / eq for t in D.U})
    H1 = pd.DataFrame([w.values], columns=D.U, index=[pd.Timestamp(s["fetched_at_utc"][:10])])
    B, W = decompose_holdings(H1, D.grp, "algebraic")
    gross = w.abs().sum()
    print(f"snapshot fetched {s['fetched_at_utc']} (positions after the 2026-10-09 close), equity {eq:,.0f}; "
          f"gross {gross:.3f}x, net {w.sum():+.3f}x")
    res = {"fetched_at_utc": s["fetched_at_utc"], "gross": float(gross), "net": float(w.sum())}
    for g in GROUPS:
        cols = [t for t in D.U if D.grp[t] == g]
        nw = w[cols].sum()
        print(f"  {g:<6} net {nw:+.3f}x of equity ({nw / gross:+.3f} of gross); names held "
              f"{int((w[cols] != 0).sum())} of {len(cols)}")
        res[g] = float(nw / gross)
    gb, gw = B.abs().sum(axis=1).iloc[0], W.abs().sum(axis=1).iloc[0]
    print(f"  between leg gross {gb:.3f}x, within leg gross {gw:.3f}x; held-book mix sum|B| / (sum|B| + sum|W|) "
          f"{gb / (gb + gw):.3f} (compare section 3's fit-period distribution, algebraic rule)")
    res["held_mix"] = float(gb / (gb + gw))
    out["today"] = res


SECTIONS = {"signal": sec_signal, "control": sec_control, "pnl": sec_pnl,
            "breadth": sec_breadth, "borrow": sec_borrow, "today": sec_today}


def main(argv):
    want = argv or list(SECTIONS)
    bad = [w for w in want if w not in SECTIONS]
    if bad:
        raise SystemExit(f"unknown section(s) {bad}; choose from {list(SECTIONS)}")
    print(summary())
    print(f"W10 Part B -- FIT PERIOD ONLY (.. {FIT_END}); 2023+ sealed. Run "
          f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Zero trials; CEF counter unchanged.")
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet", columns=["date"])
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet", columns=["date"])
    print(f"panels: cef_prices last {P.date.max().date()}, cef_nav last {N.date.max().date()} (read-only)")
    D = Data()
    print("groups:", ", ".join(f"{g}: {[t for t in D.U if D.grp[t] == g]}" for g in GROUPS))
    out = {"run_utc": f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%dT%H:%MZ}", "fit_end": FIT_END,
           "spec": summary(), "rules": list(RULES), "group_min_declared": GROUP_MIN_DECLARED}
    for w in want:
        SECTIONS[w](D, out)
    if argv:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o)))
    print(f"\nwrote {OUT_JSON.relative_to(REPO)}")


if __name__ == "__main__":
    main(sys.argv[1:])
