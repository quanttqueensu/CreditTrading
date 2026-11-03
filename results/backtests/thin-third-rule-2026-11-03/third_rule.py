"""Thin sessions, a THIRD rule: trade the eligible names (report only, 2026-11-03).

ZERO TRIALS, NO SPEC CHANGE, NOTHING CHOSEN. On a decision date with fewer than
the spec's `min_names` eligible names the live sleeve FLATTENS (PR #33,
results/backtests/thin-days-2026-11-03/REPORT.md section 1) and the harness's
default HOLDS the previous target. The team lead (2026-11-02) asked for a third
rule to be screened: trade the eligible names, with the sleeve's own
construction on the smaller set. Every book here is the canonical path:
`build_targets` -> `band_gross_capped` -> `evaluate` (shift(2): decide t, fill
t+1, earn t+2), total returns cut at DIST_END (PR #33's `thin_days.load`, which
asserts the cut and the live sleeve's thin set), the spec read through
`scripts/cef/spec.py`.

DECLARED BEFORE ANY OF THIS RAN (REPORT.md section 1 holds the derivation):
  * the floor is 4, DERIVED from what the construction does at each count
    (1 name: 0/0; 2: only the sign of z1 - z2; 3: one side is always a single
    fund holding half the gross; 4: the first count with none of those). The
    plateau is checked at 3, 4 and 5 on the FIT period only. Nothing is chosen
    from any row, and nothing from the 2023+ rows (H13);
  * below the floor the rule does what the live sleeve does: FLAT;
  * rules scored: hold, flatten, trade_eligible at 3 / 4 / 5 (te3, te4, te5),
    each with instant and deferred flips; te4 is the row the questions ask about;
  * the leave-one-name-out runs PHK and PTY first, because PR #33 found them the
    two largest contributors to hold's thin-day P&L; every other name is printed
    beside them so nothing is selected by the ranking;
  * the direction control (H12): on every thin session the rule trades, the
    reduced-set target's weights are reassigned among THAT session's eligible
    names by a random order drawn once per thin stretch (same names, same gross,
    same weight distribution, stable within a stretch, direction random). SEED
    20261103, 500 draws, instant flips;
  * borrow: the IBKR FEE_RATE panel where it exists (2021-09-13 on); before
    that it is unmeasured and the report says so; never charged in the headline.

ADDED AFTER A FIRST (SMOKE) RUN, stated so the order is visible: that run
printed the scoreboard, the paired gaps, the plateau, the matched rows, the
leave-outs, the borrow and the forward block, and showed te4 ahead of both rules
in the fit period. The ATTACKS on that result were then added, before any of
them ran: (a) the thin-day P&L split between eligible names and the band's
residues in ineligible names; (b) the stale-price signature; (c) the
distribution leg and the beta; (d) the stretches as the unit; (e) the gap
without its best 10 days; (f) the deflated bar at N = 52 / 53 / 54; the
per-traded-session plateau; and the replay of the two degenerate sessions. The
direction control had not yet run. A fix to the hypothetical in step 5 (one 0/0
target, 2025-04-07, made its median cosine NaN) was made at the same time.

SECOND METHODS, all asserted:
  * the reduced-set targets equal the LIVE SLEEVE's own output on every thin
    session (sleeve_reduced.csv, from sleeve_reduced_check.py), after its gross
    ceiling, wherever its min-weight block does not act;
  * the trade_eligible books equal an independently written pandas loop
    (PR #33's `independent_flatten`, given the floor's targets and mask);
  * `scripts.research.harness.report` (nan_policy="raise") reproduces te4's fit
    and holdout Sharpe ratios.

    python3 results/backtests/thin-third-rule-2026-11-03/third_rule.py     # about 5-8 min

Writes run.log (gitignored) and results.json beside this file. Reads data/ only.
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]          # the worktree root
TD = REPO / "results" / "backtests" / "thin-days-2026-11-03"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TD))

import numpy as np                                    # noqa: E402
import pandas as pd                                   # noqa: E402

import attack as ak                                   # noqa: E402  (PR #33; imports thin_days)
import thin_days as td                                # noqa: E402
from scripts.cef import band_frontier as bf           # noqa: E402
from scripts.cef.spec import (BAND_WIDTH, MAX_GROSS_STRESS, MIN_ADV_USD,   # noqa: E402
                              MIN_NAMES, SPEC_ID, UNIVERSE, spec)
from scripts.research.harness import ERAS, HOLDOUT_START, report   # noqa: E402
from src.deploy.registry import cef_below_min_names   # noqa: E402
from src.deploy.sleeves.cef_discount import _cap_gross   # noqa: E402

FLOOR = 4                    # derived (REPORT.md section 1), not swept
PLATEAU = (3, 4, 5)          # the floor and one either side
SEED, N_DRAWS = 20261103, 500
COSTS = (5, 15, 30)
P = 252
FLIPS = ("instant", "deferred")
MAIN = ("hold", "flatten", "te4")
LOG, OUT = [], {}


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def nwt(x):
    return ak.nwt(x)


def te(f):
    return f"te{f}"


# --------------------------------------------------------------------------- inputs
def eligible_count(panel, index, universe=None):
    U = UNIVERSE if universe is None else universe
    z, adv = panel["z"].reindex(index)[U], panel["adv"].reindex(index)[U]
    return (z.notna() & (adv >= MIN_ADV_USD)).sum(axis=1)


def inputs():
    T, R, thin, panel, dist_end, keep, Rt = td.load()
    cnt = eligible_count(panel, T.index)
    if not (thin.to_numpy() == (cnt < MIN_NAMES).to_numpy()).all():
        raise AssertionError("thin_sessions and the eligible count disagree")
    TF, BF = {}, {}
    for f in PLATEAU:
        TF[f], Rf = bf.build_targets(min_names=f)
        if not (Rf.equals(R) and TF[f].index.equals(T.index)):
            raise AssertionError(f"build_targets(min_names={f}) changed R or the index")
        BF[f] = bf.thin_sessions(T.index, min_names=f)
        if not (BF[f].to_numpy() == (cnt < f).to_numpy()).all():
            raise AssertionError(f"the floor-{f} mask is not 'fewer than {f} eligible'")
        if (BF[f] & ~thin).any():
            raise AssertionError(f"the floor-{f} mask flags a session the spec calls active")
        act = (~thin).to_numpy()
        if not (TF[f].values[act] == T.values[act]).all():
            raise AssertionError(f"floor {f}: a session with >= {MIN_NAMES} eligible has another target")
    for f in PLATEAU[1:]:
        rows = (cnt >= f).to_numpy()
        if not (TF[f].values[rows] == TF[PLATEAU[0]].values[rows]).all():
            raise AssertionError(f"floor {f} and floor {PLATEAU[0]} built different targets on a session both trade")
    p(f"targets at floors {PLATEAU}: identical to the spec targets on every session with >= {MIN_NAMES} eligible, "
      "and identical to each other wherever both floors trade (the construction does not read the floor)")
    return T, R, thin, panel, dist_end, keep, Rt, TF, BF, cnt


def sleeve_check(T, thin, TF, cnt):
    """Second method 1: the live sleeve's own reduced-set targets (sleeve_reduced.csv)."""
    s = pd.read_csv(HERE / "sleeve_reduced.csv", parse_dates=["date"]).set_index("date")
    dates = T.index[thin.to_numpy()]
    if not s.index.equals(dates):
        raise AssertionError("sleeve_reduced.csv is not on the thin sessions; re-run sleeve_reduced_check.py")
    below = (s["status"] == "below").to_numpy()
    c = cnt.loc[dates].to_numpy()
    if not (below == (c < PLATEAU[0])).all():
        raise AssertionError("the sleeve's below-floor set differs from the eligible count")
    if not (s["n_below"].to_numpy()[below] == c[below]).all():
        raise AssertionError("the sleeve's count differs from the harness's on a below-floor session")
    tr = dates[~below]
    W = s.loc[tr, UNIVERSE]
    ref = pd.DataFrame([_cap_gross(TF[PLATEAU[0]].loc[d], MAX_GROSS_STRESS)[0].reindex(UNIVERSE).values
                        for d in tr], index=tr, columns=UNIVERSE)
    diff = (W - ref).abs().max(axis=1)
    # The sleeve's min-weight block acts on an eligible name whose weight is under min_abs_weight, before the
    # ceiling (re-neutralise, l.926-933) or after it (FLAT, l.1195). The ceiling only scales down, so a weight
    # under the threshold before it is under it after: flag on the capped harness target.
    minw = bf_minw()
    small = ((ref != 0) & (ref.abs() < minw)).any(axis=1)
    dropped = ((ref != 0) & (W == 0)).any(axis=1)          # an eligible name the sleeve sent FLAT
    clean = ~small
    mx_clean = float(diff[clean].max())
    if mx_clean > 1e-12:
        raise AssertionError(f"the sleeve's reduced-set target differs from the harness's by {mx_clean}")
    if (dropped & clean).any():
        raise AssertionError("the sleeve sent an eligible name FLAT on a session with no weight under min_abs_weight")
    cs = pd.Series(c[~below], index=tr)
    out = dict(thin=len(dates), below=int(below.sum()), traded=len(tr), clean=int(clean.sum()),
               max_abs_diff_clean=mx_clean, minw_rows=int(small.sum()), minw_dropped_rows=int(dropped.sum()),
               max_abs_diff_minw=float(diff[small].max()) if small.any() else 0.0,
               minw_by_n={int(k): int(v) for k, v in cs[small].value_counts().sort_index().items()},
               minw_by_n_floor4={int(k): int(v) for k, v in cs[small & (cs >= FLOOR)].value_counts().sort_index().items()})
    p(f"second method 1 [live sleeve, min_names {MIN_NAMES} -> {PLATEAU[0]} in memory, on all {len(dates)} thin "
      f"sessions]: below the floor on {out['below']} (count identical); traded on {len(tr)}; on the {out['clean']} "
      f"with no eligible weight under min_abs_weight ({minw}) the sleeve's target after its ceiling equals "
      f"_cap_gross(build_targets row) to {mx_clean:.1e}; on the other {out['minw_rows']} its min-weight block acts "
      f"(an eligible name sent FLAT on {out['minw_dropped_rows']}; max abs weight diff {out['max_abs_diff_minw']:.4f}); "
      f"by eligible count {out['minw_by_n']}")
    OUT["sleeve_check"] = out


def bf_minw():
    from scripts.cef.spec import MIN_ABS_WEIGHT
    return float(MIN_ABS_WEIGHT)


def books(T, thin, TF, BF, b=BAND_WIDTH, cap=MAX_GROSS_STRESS, rules=("hold", "flatten") + tuple(te(f) for f in PLATEAU),
          flips=FLIPS):
    H = {}
    for rule in rules:
        for fl in flips:
            d = fl == "deferred"
            if rule == "hold":
                H[(rule, fl)] = bf.band_gross_capped(T, b, cap, defer_flips=d)
            elif rule == "flatten":
                H[(rule, fl)] = bf.band_gross_capped(T, b, cap, defer_flips=d, below_min_names="flatten", thin=thin)
            else:
                f = int(rule[2:])
                H[(rule, fl)] = bf.band_gross_capped(TF[f], b, cap, defer_flips=d, below_min_names="trade_eligible",
                                                     thin=BF[f], floor=f)
    return H


# --------------------------------------------------------------------------- step 3
def thin_days_of(thin, idx):
    """Earning-day mask: the decision two sessions earlier was a thin session (H1)."""
    t = thin.shift(2).reindex(idx)
    return t.where(t.notna(), False).astype(bool)


def scoreboard(res, thin, dist_end, rules, title, key):
    W = td.windows(dist_end)
    rows = {}
    for (rule, fl), r in res.items():
        if rule not in rules:
            continue
        for lab, a, b in W:
            rows[(rule, fl, lab)] = td.stats(r["pnl"].loc[a:b], r["turn_series"].loc[a:b])
    p(f"\n=== {title} ===")
    p("gross total return is the headline; net = ann - turn x c is the real-money view, labelled; no borrow charged; "
      "vol-matched = scaled to 6% on its own ex-post vol (descriptive)")
    p(f"{'window':<11}{'rule':<8}{'flips':<9}{'SR':>6}{'ann%':>7}{'vol%':>6}{'maxDD%':>7}{'turn':>6} | "
      f"{'net%/yr @5/@15/@30':>22} | {'BE bp':>6} {'flip?':>6} | {'vm ann%':>8}{'vm @15':>7}")
    for lab, a, b in W:
        for rule in rules:
            for fl in FLIPS:
                s = rows.get((rule, fl, lab))
                if s is None:
                    continue
                if s["flat"]:
                    p(f"{lab:<11}{rule:<8}{fl:<9} flat: held nothing (turn {s['turn']:.1f})")
                    continue
                nets = "/".join(f"{s['net'][c] * 100:.2f}" for c in COSTS)
                fl_ = f"{s['flip_bp']}bp" if s["flip_bp"] else "no"
                p(f"{lab:<11}{rule:<8}{fl:<9}{s['sr']:6.2f}{s['ann'] * 100:7.2f}{s['vol'] * 100:6.2f}"
                  f"{s['maxdd'] * 100:7.1f}{s['turn']:6.1f} | {nets:>22} | {s['be']:6.1f} {fl_:>6} | "
                  f"{s['vm']['ann'] * 100:8.2f}{s['vm']['net'][15] * 100:7.2f}")
    OUT[key] = {f"{k[0]}/{k[1]}/{k[2]}": v for k, v in rows.items()}
    return rows


def paired(res, dist_end, rule, refs, key):
    W = td.windows(dist_end)
    p(f"\n--- paired daily difference {rule} minus each reference, same flips (pp/yr, NW t; Newey-West 1994 lag) ---")
    p(f"{'window':<11}" + "".join(f"{f'- {r} ({fl[:4]})':>22}" for r in refs for fl in FLIPS))
    out = {}
    for lab, a, b in W:
        cells = []
        for r in refs:
            for fl in FLIPS:
                d = (res[(rule, fl)]["pnl"] - res[(r, fl)]["pnl"]).loc[a:b]
                cells.append((float(d.mean() * P), nwt(d.to_numpy())))
                out[f"{r}/{fl}/{lab}"] = dict(pp=cells[-1][0], t=cells[-1][1])
        p(f"{lab:<11}" + "".join(f"{c[0] * 100:14.2f} ({c[1]:5.2f})" for c in cells))
    OUT[key] = out
    return out


def thin_only(res, thin, dist_end, rules):
    """Gross on thin-decision earning days and on active ones, ann% of the window."""
    W = td.windows(dist_end)
    p("\n--- gross P&L split by the decision behind each earning day: thin session (< min_names eligible) or active; "
      "ann% of the window [thin earning days] ---")
    p(f"{'window':<11}{'flips':<9}" + "".join(f"{r + ' thin':>12}{r + ' act':>11}" for r in rules))
    out = {}
    for fl in FLIPS:
        for lab, a, b in W:
            cells = []
            for r in rules:
                x = res[(r, fl)]["pnl"].loc[a:b]
                m = thin_days_of(thin, x.index)
                cells.append((float(x[m].sum() / len(x) * P), float(x[~m].sum() / len(x) * P), int(m.sum())))
                out[f"{r}/{fl}/{lab}"] = dict(thin=cells[-1][0], active=cells[-1][1], thin_days=cells[-1][2])
            p(f"{lab:<11}{fl:<9}" + "".join(f"{c[0] * 100:12.2f}{c[1] * 100:11.2f}" for c in cells)
              + f"   [{cells[0][2]}]")
    OUT["thin_only"] = out


def era_cv(rows, rules):
    labs = [("2023+" if lab == "2023-" else lab) for lab, _, _ in ERAS]
    p("\n--- era turnover sd/mean (H5), instant flips, over the eras in which the rule traded ---")
    out = {}
    for r in rules:
        t = np.array([rows[(r, "instant", e)]["turn"] for e in labs])
        tr = t[t > 0]
        out[r] = dict(eras=[float(x) for x in t], cv=float(tr.std(ddof=1) / tr.mean()), n_eras=int(len(tr)))
        p(f"{r:<8} turn/yr by era {' / '.join(f'{x:.1f}' for x in t)}  sd/mean {out[r]['cv']:.2f} over {len(tr)} eras")
    OUT.setdefault("era_turnover_cv", {}).update(out)


def matched(T, thin, TF, BF, keep, Rt, rows):
    """H2: te4 (instant) re-banded so that its FIT turnover equals flatten's and hold's, by bisection on
    turnover only (never on P&L). A matching device, not a proposal."""
    fit = Rt.index < HOLDOUT_START

    def build(bw):
        h = bf.band_gross_capped(TF[FLOOR], bw, MAX_GROSS_STRESS, below_min_names="trade_eligible",
                                 thin=BF[FLOOR], floor=FLOOR).loc[keep]
        r = bf.evaluate(h, Rt)
        return float(r["turn_series"][fit].mean() * P), r

    out = {}
    te_turn = rows[(te(FLOOR), "instant", "FIT <2023")]["turn"]
    for ref in ("flatten", "hold"):
        target = rows[(ref, "instant", "FIT <2023")]["turn"]
        gap = te_turn / target - 1
        lo, hi = 0.002, 0.40
        tlo, thi = build(lo)[0], build(hi)[0]
        if not (thi <= target <= tlo):
            raise ValueError(f"{ref} fit turnover {target:.2f} outside [{thi:.2f}, {tlo:.2f}]")
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if build(mid)[0] > target:
                lo = mid
            else:
                hi = mid
        bw = 0.5 * (lo + hi)
        t_, r = build(bw)
        o = dict(ref_turn=target, te_turn_at_spec_band=te_turn, gap_at_spec_band=gap, band=bw, matched_turn=t_)
        p(f"\n=== H2: te{FLOOR} (instant) FIT turnover {te_turn:.2f}/yr vs {ref} {target:.2f}/yr at the spec band "
          f"({gap * 100:+.1f}%); re-banded to {bw:.4f} it turns {t_:.2f}/yr ({(t_ / target - 1) * 100:+.2f}%) ===")
        for lab, a, b in (("FIT <2023", pd.Timestamp(bf.SAMPLE_START), HOLDOUT_START - pd.Timedelta(days=1)),
                          ("H13 2023+", HOLDOUT_START, Rt.index[-1])):
            s = td.stats(r["pnl"].loc[a:b], r["turn_series"].loc[a:b])
            ref_s = rows[(ref, "instant", lab)]
            o[lab] = dict(te=s, ref=ref_s)
            p(f"{lab:<10} te{FLOOR}@{bw:.4f}: SR {s['sr']:.2f} ann {s['ann'] * 100:.2f}% turn {s['turn']:.1f} net "
              + "/".join(f"{s['net'][c] * 100:.2f}" for c in COSTS) + f" BE {s['be']:.1f}bp | {ref}: SR "
              f"{ref_s['sr']:.2f} ann {ref_s['ann'] * 100:.2f}% turn {ref_s['turn']:.1f} net "
              + "/".join(f"{ref_s['net'][c] * 100:.2f}" for c in COSTS))
        out[ref] = o
    OUT["matched"] = out


def plateau(res, dist_end):
    """H8: floors 3, 4, 5 against flatten and hold on the FIT period (H13 printed, not read)."""
    W = [w for w in td.windows(dist_end) if w[0] in ("2005-09", "2010-14", "2015-19", "2020-22", "FIT <2023",
                                                       "H13 2023+")]
    p("\n=== H8 plateau: te3 / te4 / te5 minus flatten and minus hold, instant flips (pp/yr, NW t) ===")
    p("(read on FIT and its eras; the H13 row is printed and not used)")
    out = {}
    for lab, a, b in W:
        cells = []
        for f in PLATEAU:
            for ref in ("flatten", "hold"):
                d = (res[(te(f), "instant")]["pnl"] - res[(ref, "instant")]["pnl"]).loc[a:b]
                cells.append((float(d.mean() * P), nwt(d.to_numpy()) if (d != 0).any() else float("nan")))
                out[f"te{f}-{ref}/{lab}"] = dict(pp=cells[-1][0], t=cells[-1][1])
        p(f"{lab:<11}" + "".join(f"  te{f}-{ref[:4]} {c[0] * 100:+6.2f} ({c[1]:+5.2f})"
                                 for (f, ref), c in zip([(f, r) for f in PLATEAU for r in ("flatten", "hold")], cells)))
    OUT["plateau"] = out


def plateau_per_session(res, thin, cnt, dist_end):
    """The same gaps per traded thin session: if the per-session edge is flat across floors, the floor sets how
    MANY sessions are traded, not what each earns."""
    fit = (pd.Timestamp(bf.SAMPLE_START), HOLDOUT_START - pd.Timedelta(days=1))
    p("\n--- H8 plateau per traded session (FIT): gap pp/yr / share of FIT sessions the floor trades and the spec "
      "does not ---")
    out = {}
    for f in PLATEAU:
        share = float((thin & (cnt >= f)).loc[fit[0]:fit[1]].mean())
        cells = {}
        for ref in ("flatten", "hold"):
            g = float((res[(te(f), "instant")]["pnl"] - res[(ref, "instant")]["pnl"]).loc[fit[0]:fit[1]].mean() * P)
            cells[ref] = dict(gap=g, per_share=g / share)
        out[f] = dict(share=share, **cells)
        p(f"te{f}: share {share * 100:.1f}%; per unit share vs flatten {cells['flatten']['per_share'] * 100:+.2f}pp/yr, "
          f"vs hold {cells['hold']['per_share'] * 100:+.2f}pp/yr")
    OUT["plateau_per_session"] = out


# --------------------------------------------------------------------------- attacks on te4's gap
def attack(H, T, thin, cnt, panel, keep, Rt, res, dist_end):
    """Declared before reading any te4 result beyond the smoke run's scoreboard: where te4's thin-day P&L sits,
    whether it is stale prices, distributions or beta, the stretches as the unit, the best days, the bar."""
    from itertools import product as _prod
    from scripts.research.inference import p_clear_bar, read_result, upper_bound_max_z
    W = [w for w in td.windows(dist_end) if w[0] in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+")]
    out = {}
    H4 = H[("te4", "instant")]
    held = H4.loc[keep].shift(2).fillna(0.0)                       # H1: decided t earns t+2
    C = held * Rt
    if not np.allclose(C.sum(axis=1).to_numpy(), res[("te4", "instant")]["pnl"].to_numpy(), atol=1e-15):
        raise AssertionError("te4's name-day attribution does not sum to evaluate()'s P&L")
    z, adv = panel["z"].reindex(T.index)[UNIVERSE], panel["adv"].reindex(T.index)[UNIVERSE]
    elig = (z.notna() & (adv >= MIN_ADV_USD))
    elig_d = elig.shift(2).reindex(Rt.index)
    elig_d = elig_d.where(elig_d.notna(), False).astype(bool)      # eligibility AT THE DECISION behind the day
    thin_d = thin_days_of(thin, Rt.index)
    isheld = held != 0

    p("\n=== ATTACK a: te4's thin-day P&L by whether the held name was eligible at the decision (the band leaves "
      "an ineligible name at its band edge, as the live sleeve does) ===")
    p(f"{'window':<11}{'thin ann%':>10}{'eligible':>10}{'residue':>10}{'resid gross':>12}{'elig gross':>11}  [held name-days elig / resid]")
    for lab, a, b in W:
        m = thin_d.loc[a:b]
        n = len(C.loc[a:b])
        cc, ee, hh = C.loc[a:b][m], elig_d.loc[a:b][m], held.loc[a:b][m]
        o = dict(thin=float(cc.sum().sum() / n * P), elig=float(cc.where(ee, 0.0).sum().sum() / n * P),
                 resid=float(cc.where(~ee, 0.0).sum().sum() / n * P),
                 resid_gross=float(hh.where(~ee, 0.0).abs().sum(axis=1).mean()) if m.any() else float("nan"),
                 elig_gross=float(hh.where(ee, 0.0).abs().sum(axis=1).mean()) if m.any() else float("nan"),
                 nd_elig=int(((hh != 0) & ee).sum().sum()), nd_resid=int(((hh != 0) & ~ee).sum().sum()))
        out.setdefault("a_split", {})[lab] = o
        p(f"{lab:<11}{o['thin'] * 100:10.2f}{o['elig'] * 100:10.2f}{o['resid'] * 100:10.2f}{o['resid_gross']:12.3f}"
          f"{o['elig_gross']:11.3f}  [{o['nd_elig']} / {o['nd_resid']}]")
    cnt_d = cnt.shift(2).reindex(Rt.index)
    pn4 = res[("te4", "instant")]["pnl"]
    p("--- te4's thin-day P&L by the eligible count at the decision: ann% of the window, and per earning day x 252 "
      "(the floor's own count, 4, against 5) [earning days] ---")
    for lab, a, b in W:
        x, cd, m = pn4.loc[a:b], cnt_d.loc[a:b], thin_d.loc[a:b]
        cells = {}
        for k in (4, 5):
            sel = m & (cd == k)
            cells[k] = dict(days=int(sel.sum()), ann=float(x[sel].sum() / len(x) * P),
                            per_day=float(x[sel].mean() * P) if sel.any() else float("nan"),
                            t=nwt(x[sel].to_numpy()) if sel.sum() > 30 else float("nan"))
        out.setdefault("a_by_count", {})[lab] = cells
        p(f"{lab:<11}" + "  ".join(f"n={k}: {c['ann'] * 100:+.2f} ({c['per_day'] * 100:+.2f}/day-yr, t {c['t']:.2f}) "
                                   f"[{c['days']}]" for k, c in cells.items()))

    p("\n--- ATTACK b: stale-price signature on te4's held name-days: share with a total return of exactly 0, "
      "and with zero volume ---")
    zero = Rt[UNIVERSE] == 0
    v0 = panel["vol"].reindex(Rt.index)[UNIVERSE] == 0
    for lab, a, b in W:
        cells = {}
        for (nm, mk), (en, em) in _prod((("thin", thin_d.loc[a:b]), ("active", ~thin_d.loc[a:b])),
                                         (("elig", elig_d.loc[a:b]), ("resid", ~elig_d.loc[a:b]))):
            sel = isheld.loc[a:b][mk] & em[mk]
            nd = int(sel.sum().sum())
            cells[f"{nm}/{en}"] = dict(n=nd, zero=float((zero.loc[a:b][mk] & sel).sum().sum() / nd) if nd else float("nan"),
                                       vol0=float((v0.loc[a:b][mk] & sel).sum().sum() / nd) if nd else float("nan"))
        out.setdefault("b_stale", {})[lab] = cells
        p(f"{lab:<11}" + "  ".join(f"{k} {v['zero'] * 100:5.2f}% zero, {v['vol0'] * 100:4.2f}% vol0 [{v['n']}]"
                                   for k, v in cells.items()))

    y = bf.distribution_yield(Rt.index, Rt.columns).reindex_like(Rt)[UNIVERSE]
    Cd = held[UNIVERSE] * y
    ret_raw = panel["ret"].reindex(Rt.index)[UNIVERSE]
    ew = Rt[UNIVERSE].where(ret_raw.notna()).mean(axis=1)
    p("\n--- ATTACK c: te4's thin-day P&L, price leg and distribution leg, and its beta to the equal-weight universe "
      "total return on the same days ---")
    p(f"{'window':<11}{'thin ann%':>10}{'price':>8}{'dist':>8}{'beta':>8}{'alpha part':>11}{'NW t':>7}")
    for lab, a, b in W:
        m = thin_d.loc[a:b]
        n = len(C.loc[a:b])
        tot = float(C.loc[a:b][m].sum().sum() / n * P)
        dst = float(Cd.loc[a:b][m].sum().sum() / n * P)
        yv, xv = res[("te4", "instant")]["pnl"].loc[a:b][m], ew.loc[a:b][m]
        ok = xv.notna()
        yv, xv = yv[ok], xv[ok]
        if len(yv) > 30 and xv.var() > 0:
            beta = float(np.cov(yv, xv, ddof=1)[0, 1] / xv.var(ddof=1))
            resid = yv - beta * xv
            apart, ta = float(resid.sum() / n * P), nwt(resid.to_numpy())
        else:
            beta = apart = ta = float("nan")
        out.setdefault("c_legs_beta", {})[lab] = dict(thin=tot, price=tot - dst, dist=dst, beta=beta, alpha=apart, t=ta)
        p(f"{lab:<11}{tot * 100:10.2f}{(tot - dst) * 100:8.2f}{dst * 100:8.2f}{beta:8.3f}{apart * 100:11.2f}{ta:7.2f}")

    fit = (pd.Timestamp(bf.SAMPLE_START), HOLDOUT_START - pd.Timedelta(days=1))
    for ref in ("flatten", "hold"):
        d = (res[("te4", "instant")]["pnl"] - res[(ref, "instant")]["pnl"])
        x = d.loc[fit[0]:fit[1]]
        # stretches as the unit: each FIT run of thin sessions with a te4 book, the gap over its earning days
        idx = T.index
        runs = []
        for i0, i1 in ak.runs_of(thin & (cnt >= FLOOR)):
            if idx[i0] >= HOLDOUT_START:
                continue
            earn = idx[i0 + 2: i1 + 3]
            earn = earn[earn.isin(x.index)]
            if len(earn):
                runs.append((str(idx[i0].date()), str(idx[i1].date()), i1 - i0 + 1, float(x.loc[earn].sum())))
        v = np.array([r[3] for r in runs])
        nr = len(v)
        t_runs = float(v.mean() / v.std(ddof=1) * np.sqrt(nr))
        rng = np.random.default_rng(SEED)
        if nr <= 24:
            signs = ((np.arange(2 ** nr)[:, None] >> np.arange(nr)[None, :]) & 1).astype(np.int8) * 2 - 1
            p_flip, how = float(((signs @ v) >= v.sum() - 1e-15).mean()), "exact"
        else:
            signs = rng.choice([-1, 1], size=(200_000, nr))
            p_flip, how = float(((signs @ v) >= v.sum() - 1e-15).mean()), "200,000 sampled"
        srt = np.sort(v)[::-1]
        s = x.sort_values(ascending=False)
        o = dict(runs=nr, t_runs=t_runs, positive=int((v > 0).sum()), p_signflip=p_flip, p_how=how,
                 sum_pp=float(v.sum()), largest=float(srt[0]), largest_share=float(srt[0] / v.sum()),
                 largest_run=[r for r in runs if r[3] == srt[0]][0][:3],
                 t_without_best10=nwt(x.drop(s.head(10).index).to_numpy()),
                 best10_pp=float(s.head(10).sum()), total_pp=float(x.sum()),
                 table=[dict(first=r[0], last=r[1], sessions=r[2], pp=r[3]) for r in runs])
        p(f"\n=== ATTACK d-f: te4 minus {ref}, FIT, instant flips ===")
        p(f"d. stretches as the unit (the gap summed over each FIT thin stretch's earning days; {nr} stretches with a "
          f"te4 book): run t {t_runs:.2f}; positive {o['positive']}/{nr}; sign-flip p (one-sided, {how}) {p_flip:.4f}; "
          f"largest {srt[0] * 100:.2f}pp ({o['largest_share'] * 100:.0f}% of {v.sum() * 100:.2f}pp; "
          f"{o['largest_run'][0]}..{o['largest_run'][1]}). The rest of the gap ({(x.sum() - v.sum()) * 100:.2f}pp) "
          "is earned on active days after re-entry")
        p(f"e. the best 10 days sum to {o['best10_pp'] * 100:.2f}pp of {o['total_pp'] * 100:.2f}pp; without them NW t "
          f"{o['t_without_best10']:.2f}")
        est, t_day = float(x.mean() * P), nwt(x.to_numpy())
        o["bars"] = {}
        for N in (52, 53, 54):
            bar = float(upper_bound_max_z(N))
            rr = read_result(est, est / t_day, est, n_trials=N) if est > 0 else None
            o["bars"][N] = dict(bar=bar, p_clear_paired=float(p_clear_bar(t_day, bar)),
                                p_clear_runs=float(p_clear_bar(t_runs, bar)),
                                read=rr["outcome"] if rr else "n/a (negative)", lo=rr["lo"] if rr else None,
                                hi=rr["hi"] if rr else None)
            b = o["bars"][N]
            p(f"f. N={N}: bar {bar:.3f}; paired t {t_day:.2f}, run t {t_runs:.2f}; P(clear | true t = observed) "
              f"{b['p_clear_paired']:.2f} / {b['p_clear_runs']:.2f}; read_result (Sidak at N, meaningful = the "
              f"observed {est * 100:.2f}pp/yr) {b['read']}"
              + (f" [{b['lo'] * 100:.2f}, {b['hi'] * 100:.2f}]" if rr else ""))
        out[f"d_f_vs_{ref}"] = o
    OUT["attack"] = out


def degenerate_replay(T, thin, TF, BF, keep, Rt, dist_end):
    """PR #33 section 5.H: on 2020-03-18 and 2025-04-07 every eligible z sat at the -4 clip; the harness cuts the
    book to the band edge, the live sleeve holds every name. Replay each rule with the sleeve's behaviour (a zero
    gap on those dates) and report what moves."""
    W = [w for w in td.windows(dist_end) if w[0] in ("2020-22", "FIT <2023", "H13 2023+")]
    nz = T.abs().sum(axis=1) > 0
    deg = T.index[~thin & ~nz & (nz.cumsum() > 0)]
    p(f"\n=== the degenerate sessions {[str(d.date()) for d in deg]} replayed with the sleeve's hold (PR #33 5.H) ===")
    out = {}
    pn = {}
    for rule, fl in [(r, f) for r in MAIN for f in FLIPS]:
        if rule == "hold":
            TT, kw = T, {}
        elif rule == "flatten":
            TT, kw = T, dict(below_min_names="flatten", thin=thin)
        else:
            TT, kw = TF[FLOOR], dict(below_min_names="trade_eligible", thin=BF[FLOOR], floor=FLOOR)
        kw["defer_flips"] = fl == "deferred"
        h0 = bf.band_gross_capped(TT, BAND_WIDTH, MAX_GROSS_STRESS, **kw)
        T2, h = TT.copy(), h0
        for dt in deg:
            i = TT.index.get_loc(dt)
            if (TT.iloc[i] != 0).any():
                raise AssertionError(f"{rule}: {dt.date()} is not a zero row of its targets")
            T2.iloc[i] = h.iloc[i - 1].to_numpy()          # a zero gap: the band holds every name
            h = bf.band_gross_capped(T2, BAND_WIDTH, MAX_GROSS_STRESS, **kw)
            if not np.array_equal(h.iloc[i].to_numpy(), h.iloc[i - 1].to_numpy()):
                raise AssertionError(f"the replay did not hold {rule} on {dt.date()}")
        r0, r1 = bf.evaluate(h0.loc[keep], Rt)["pnl"], bf.evaluate(h.loc[keep], Rt)["pnl"]
        pn[(rule, fl)] = r1
        out[f"{rule}/{fl}"] = {lab: dict(harness=float(r0.loc[a:b].mean() * P), sleeve=float(r1.loc[a:b].mean() * P))
                               for lab, a, b in W}
        p(f"{rule:<8}{fl:<9} ann% harness -> sleeve: " + "  ".join(
            f"{lab} {out[f'{rule}/{fl}'][lab]['harness'] * 100:.2f}->{out[f'{rule}/{fl}'][lab]['sleeve'] * 100:.2f}"
            for lab, _, _ in W))
    for ref in ("flatten", "hold"):
        for fl in FLIPS:
            dd = pn[("te4", fl)] - pn[(ref, fl)]
            out[f"te4-{ref}/{fl}"] = {lab: dict(pp=float(dd.loc[a:b].mean() * P), t=nwt(dd.loc[a:b].to_numpy()))
                                      for lab, a, b in W}
            p(f"te4 minus {ref} ({fl}) under the replay: " + "  ".join(
                f"{lab} {out[f'te4-{ref}/{fl}'][lab]['pp'] * 100:+.2f} ({out[f'te4-{ref}/{fl}'][lab]['t']:+.2f})"
                for lab, _, _ in W))
    OUT["degenerate_replay"] = dict(dates=[str(d.date()) for d in deg], **out)


# --------------------------------------------------------------------------- step 4
def concentration(H, T, thin, TF, cnt, dist_end):
    W = [w for w in td.windows(dist_end) if w[0] not in ("full",)]
    p("\n=== STEP 4: concentration on thin sessions (the book as decided; instant flips) ===")
    out = {}
    for rule in ("te4", "hold"):
        Hh = H[(rule, "instant")]
        n = (Hh.abs() > 0).sum(axis=1)
        mx = Hh.abs().max(axis=1)
        g = Hh.abs().sum(axis=1)
        p(f"{rule}: on thin sessions with a book held: names held / max single-name |w| / gross "
          "(mean, median, p90, max) [sessions]; active sessions for reference")
        for lab, a, b in W:
            for nm, msk in (("thin", thin.loc[a:b]), ("active", ~thin.loc[a:b])):
                held = msk & (g.loc[a:b] > 0)
                if not held.any():
                    continue
                q = lambda s: dict(mean=float(s.mean()), median=float(s.median()),            # noqa: E731
                                   p90=float(s.quantile(0.9)), max=float(s.max()))
                o = dict(sessions=int(held.sum()), names=q(n.loc[a:b][held]), maxw=q(mx.loc[a:b][held]),
                         gross=q(g.loc[a:b][held]))
                out[f"{rule}/{nm}/{lab}"] = o
                p(f"  {lab:<10}{nm:<7} names {o['names']['mean']:.2f}/{o['names']['median']:.0f}/"
                  f"{o['names']['p90']:.0f}/{o['names']['max']:.0f}  max|w| {o['maxw']['mean']:.3f}/"
                  f"{o['maxw']['median']:.3f}/{o['maxw']['p90']:.3f}/{o['maxw']['max']:.3f}  gross "
                  f"{o['gross']['mean']:.3f}/{o['gross']['median']:.3f}/{o['gross']['p90']:.3f}/{o['gross']['max']:.3f}"
                  f" [{o['sessions']}]")
    # the target itself on the sessions te4 trades and the spec does not
    T4 = TF[FLOOR]
    m = (thin & (cnt >= FLOOR)).to_numpy()
    tg = T4[m]
    side_min = np.minimum((tg > 0).sum(axis=1), (tg < 0).sum(axis=1))
    cn = cnt[m].to_numpy()
    out["target_reduced"] = dict(sessions=int(m.sum()),
                                 by_n={int(k): int(v) for k, v in cnt[m].value_counts().sort_index().items()},
                                 single_name_side_share=float((side_min == 1).mean()),
                                 single_name_side_share_by_n={int(k): float((side_min[cn == k] == 1).mean())
                                                              for k in sorted(set(cn))},
                                 maxw_median=float(tg.abs().max(axis=1).median()),
                                 maxw_p90=float(tg.abs().max(axis=1).quantile(0.9)),
                                 gross_median=float(tg.abs().sum(axis=1).median()),
                                 degenerate_zero_rows=int((tg.abs().sum(axis=1) == 0).sum()))
    o = out["target_reduced"]
    p(f"te{FLOOR} TARGET on the {o['sessions']} thin sessions it trades (eligible count: {o['by_n']}): one side is a "
      f"single fund on {o['single_name_side_share'] * 100:.1f}% (by count: "
      + ", ".join(f"n={k} {v * 100:.1f}%" for k, v in o["single_name_side_share_by_n"].items())
      + f"); max |w| median {o['maxw_median']:.3f}, p90 "
      f"{o['maxw_p90']:.3f}; gross median {o['gross_median']:.3f}; all-equal-z (0/0) rows {o['degenerate_zero_rows']}")
    OUT["concentration"] = out


def leave_out(H, keep, Rt, dist_end, ref):
    """te4 minus ref with one name's own P&L taken out (attribution), PHK and PTY first."""
    W = [w for w in td.windows(dist_end) if w[0] in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+")]
    A, B = H[("te4", "instant")], H[(ref, "instant")]
    Dn = (A.loc[keep].shift(2).fillna(0.0) - B.loc[keep].shift(2).fillna(0.0)) * Rt   # H1; first 2 rows hold nothing
    d = Dn.sum(axis=1)
    chk = bf.evaluate(A.loc[keep], Rt)["pnl"] - bf.evaluate(B.loc[keep], Rt)["pnl"]
    if not np.allclose(d.to_numpy(), chk.to_numpy(), atol=1e-14):
        raise AssertionError("the name attribution does not sum to the paired gap")
    order = ["PHK", "PTY"] + [t for t in UNIVERSE if t not in ("PHK", "PTY")]
    p(f"\n=== STEP 4: te4 minus {ref} with each name's own P&L taken out (attribution; instant flips; pp/yr, NW t) ===")
    p(f"{'left out':<10}" + "".join(f"{lab:>18}" for lab, _, _ in W))
    out = {}
    for drop in [[]] + [[t] for t in order] + [["PHK", "PTY"]]:
        cells = []
        for lab, a, b in W:
            X = Dn.loc[a:b]
            x = X.sum(axis=1) - (X[drop].sum(axis=1) if drop else 0.0)
            cells.append((float(x.mean() * P), nwt(x.to_numpy())))
        k = "+".join(drop) if drop else "none"
        out[k] = {lab: dict(pp=c[0], t=c[1]) for (lab, _, _), c in zip(W, cells)}
        p(f"{k:<10}" + "".join(f"{c[0] * 100:10.2f} ({c[1]:5.2f})" for c in cells))
    contrib = {lab: {t: float(Dn.loc[a:b][t].sum() / len(Dn.loc[a:b]) * P) for t in UNIVERSE} for lab, a, b in W}
    fitc = sorted(contrib["FIT <2023"].items(), key=lambda kv: -abs(kv[1]))[:5]
    p("largest FIT contributors by |pp/yr|: " + ", ".join(f"{t} {v * 100:+.2f}" for t, v in fitc))
    OUT[f"leave_out_vs_{ref}"] = out
    OUT[f"contrib_vs_{ref}"] = contrib


def rebuilt(dist_end):
    W = [w for w in td.windows(dist_end) if w[0] in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+")]
    p("\n=== STEP 4: books REBUILT on the universe without the name(s) (targets, masks and books recomputed; "
      "a smaller universe is thin more often, so this is a different book) ===")
    out = {}
    for drop in (["PHK"], ["PTY"], ["PHK", "PTY"]):
        U = [u for u in UNIVERSE if u not in drop]
        T, R = bf.build_targets(universe=U)
        thin = bf.thin_sessions(T.index, universe=U)
        T4, _ = bf.build_targets(universe=U, min_names=FLOOR)
        B4 = bf.thin_sessions(T.index, universe=U, min_names=FLOOR)
        keep = T.index <= dist_end
        Rt = bf.total_returns(R.loc[keep])
        pnl = {"hold": bf.evaluate(bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS).loc[keep], Rt)["pnl"],
               "flatten": bf.evaluate(bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS, below_min_names="flatten",
                                                           thin=thin).loc[keep], Rt)["pnl"],
               "te4": bf.evaluate(bf.band_gross_capped(T4, BAND_WIDTH, MAX_GROSS_STRESS,
                                                       below_min_names="trade_eligible", thin=B4,
                                                       floor=FLOOR).loc[keep], Rt)["pnl"]}
        k = "+".join(drop)
        row = dict(thin=int(thin.sum()), below_floor=int(B4.sum()))
        for lab, a, b in W:
            row[lab] = {f"te4-{r}": dict(pp=float((pnl["te4"] - pnl[r]).loc[a:b].mean() * P),
                                         t=nwt((pnl["te4"] - pnl[r]).loc[a:b].to_numpy()))
                        for r in ("flatten", "hold")}
            row[lab].update({r: float(pnl[r].loc[a:b].mean() * P) for r in pnl})
        out[k] = row
        p(f"without {k:<8} thin {row['thin']}, below floor {row['below_floor']}: " + "  ".join(
            f"{lab} te4-flat {row[lab]['te4-flatten']['pp'] * 100:+.2f} ({row[lab]['te4-flatten']['t']:+.2f}), "
            f"te4-hold {row[lab]['te4-hold']['pp'] * 100:+.2f} ({row[lab]['te4-hold']['t']:+.2f})"
            for lab, _, _ in W))
    OUT["rebuilt"] = out


def borrow(H, keep, Rt, dist_end, res):
    p("\n=== STEP 4: borrow on the shorts te4 carries and the reference does not (charged nowhere else) ===")
    sh = {r: H[(r, "instant")].loc[keep].clip(upper=0).abs().shift(2).fillna(0.0) for r in MAIN}   # earning-day aligned
    W = [w for w in td.windows(dist_end) if w[0] in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+")]
    out = dict(breakeven={}, extra_by_name={})
    for ref in ("flatten", "hold"):
        xs = sh["te4"] - sh[ref]
        for lab, a, b in W:
            gap = float((res[("te4", "instant")]["pnl"] - res[(ref, "instant")]["pnl"]).loc[a:b].mean() * P)
            ex = float(xs.loc[a:b].sum(axis=1).mean())
            fee = gap / ex if ex > 0 else float("nan")
            out["breakeven"][f"{ref}/{lab}"] = dict(gap=gap, extra_short=ex, fee=fee)
            p(f"te4 - {ref} {lab}: gap {gap * 100:+.2f}pp/yr; mean extra short weight {ex:+.3f}; uniform fee that "
              f"erases the gap {fee * 100:.1f}%/yr" if ex > 0 else
              f"te4 - {ref} {lab}: gap {gap * 100:+.2f}pp/yr; mean extra short weight {ex:+.3f} (te4 carries no "
              "more short than the reference: no break-even fee)")
        bn = xs.loc[: HOLDOUT_START - pd.Timedelta(days=1)].mean()
        out["extra_by_name"][ref] = {t: float(v) for t, v in bn.items() if abs(v) > 0.005}
        p(f"FIT mean extra short weight by name vs {ref}: "
          + ", ".join(f"{t} {v:+.3f}" for t, v in bn.sort_values().items() if abs(v) > 0.005))
    bh = pd.read_parquet(bf.DATA_DIR / "cef_borrow_history.parquet")
    bh["date"] = pd.to_datetime(bh["date"])
    fee = bh.pivot_table(index="date", columns="ticker", values="fee_rate_pct")
    missing = [t for t in UNIVERSE if t not in fee.columns]
    if missing:
        raise AssertionError(f"the IBKR fee panel has no column for {missing}")
    fee = fee[UNIVERSE]
    p(f"IBKR FEE_RATE panel {fee.index.min().date()}..{fee.index.max().date()} (data/cef/cef_borrow_history.parquet; "
      "docs/REFERENCES.md: no independent source for its levels before 2026-09). Before "
      f"{fee.index.min().date()} borrow is UNMEASURED.")
    meas = {}
    for lab, a, b in (("2021-09-13..2022-12-30", fee.index.min(), pd.Timestamp("2022-12-30")),
                      ("2023-01-03..DIST_END", HOLDOUT_START, min(dist_end, fee.index.max()))):
        days = Rt.loc[a:b].index
        f, n_stale = ak._asof_fee(fee, days)
        ch = {r: float((sh[r].loc[days] * f / 100).sum(axis=1).mean()) for r in MAIN}
        gaps = {r: float((res[("te4", "instant")]["pnl"] - res[(r, "instant")]["pnl"]).loc[days].mean() * P)
                for r in ("flatten", "hold")}
        meas[lab] = dict(borrow=ch, gap=gaps, net={r: gaps[r] - (ch["te4"] - ch[r]) for r in gaps},
                         stale_name_days=n_stale)
        p(f"{lab}: borrow on short weight, simple annual rate: hold {ch['hold'] * 100:.2f}%, flatten "
          f"{ch['flatten'] * 100:.2f}%, te4 {ch['te4'] * 100:.2f}%/yr; te4 - flatten gap {gaps['flatten'] * 100:+.2f} "
          f"gross -> {meas[lab]['net']['flatten'] * 100:+.2f} net of the extra borrow; te4 - hold "
          f"{gaps['hold'] * 100:+.2f} -> {meas[lab]['net']['hold'] * 100:+.2f} (fee up to 5 sessions old on {n_stale} "
          "name-days)")
    out["measured"] = meas
    OUT["borrow"] = out


# --------------------------------------------------------------------------- H12 control
def direction_control(T, thin, TF, BF, cnt, keep, Rt, res, dist_end):
    """Reassign each traded thin session's target weights among that session's eligible names by a random
    order drawn once per thin stretch; everything else as te4. Declared before running (module docstring)."""
    T4, B4 = TF[FLOOR], BF[FLOOR]
    A = T4.values
    trade = (thin & (cnt >= FLOOR)).to_numpy()
    runs = ak.runs_of(pd.Series(trade, index=T4.index))
    below = B4.to_numpy()
    rng = np.random.default_rng(SEED)
    W = [w for w in td.windows(dist_end) if w[0] in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+")]
    thin_d = thin_days_of(thin, Rt.index)
    actual = {lab: float(res[("te4", "instant")]["pnl"].loc[a:b][thin_d.loc[a:b]].sum() / len(Rt.loc[a:b]) * P)
              for lab, a, b in W}
    draws = {lab: [] for lab, _, _ in W}
    for k in range(N_DRAWS):
        B = A.copy()
        for i0, i1 in runs:
            key = rng.random(A.shape[1])                    # one random order of the names per stretch
            for i in range(i0, i1 + 1):
                nz = np.flatnonzero(A[i] != 0)
                if len(nz) < 2:
                    continue
                by_w = nz[np.argsort(-A[i][nz], kind="stable")]       # names by weight, largest first
                by_key = nz[np.argsort(-key[nz], kind="stable")]      # the same names in the stretch's random order
                B[i, by_key] = A[i, by_w]
        for i in range(1, len(B)):                          # below-floor rows repeat the previous row, as build_targets does
            if below[i]:
                B[i] = B[i - 1]
        Tb = pd.DataFrame(B, index=T4.index, columns=T4.columns)
        h = bf.band_gross_capped(Tb, BAND_WIDTH, MAX_GROSS_STRESS, below_min_names="trade_eligible", thin=B4,
                                 floor=FLOOR).loc[keep]
        pnl = bf.evaluate(h, Rt)["pnl"]
        for lab, a, b in W:
            draws[lab].append(float(pnl.loc[a:b][thin_d.loc[a:b]].sum() / len(Rt.loc[a:b]) * P))
        if k % 100 == 0:
            p(f"  direction control draw {k}")
    out = {}
    p(f"\n=== H12 direction control: te4's thin-day P&L against {N_DRAWS} random within-session reassignments "
      f"(seed {SEED}; ann% of the window) ===")
    for lab, _, _ in W:
        x = np.array(draws[lab])
        o = dict(actual=actual[lab], null_mean=float(x.mean()), null_sd=float(x.std(ddof=1)),
                 p95=float(np.percentile(x, 95)), p_ge=float((x >= actual[lab]).mean()))
        out[lab] = o
        p(f"{lab:<10} te4 {o['actual'] * 100:+.2f}  null mean {o['null_mean'] * 100:+.2f} sd {o['null_sd'] * 100:.2f} "
          f"95th {o['p95'] * 100:+.2f}  P(null >= te4) {o['p_ge']:.3f}")
    OUT["direction_control"] = out


# --------------------------------------------------------------------------- step 5
def forward(T, thin, panel, cnt, H, res, keep, Rt, dist_end):
    p("\n=== STEP 5: forward relevance ===")
    out = {}
    c23 = cnt.loc[HOLDOUT_START:]
    by_year = {}
    for y, g in c23.groupby(c23.index.year):
        by_year[str(y)] = {"sessions": int(len(g)), **{f"n={k}": int((g == k).sum()) for k in (4, 5, 6, 7)},
                           "n>=8": int((g >= 8).sum()), "min": int(g.min())}
    out["by_year"] = by_year
    p("eligible count since 2023-01-01, sessions by year: " + "; ".join(
        f"{y}: n=4 {v['n=4']}, 5 {v['n=5']}, 6 {v['n=6']}, 7 {v['n=7']}, >=8 {v['n>=8']} (of {v['sessions']}, min "
        f"{v['min']})" for y, v in by_year.items()))
    last_thin = thin[thin].index.max()
    after = cnt.loc[last_thin + pd.Timedelta(days=1):]
    out["since_last_thin"] = dict(last_thin=str(last_thin.date()), sessions=int(len(after)),
                                  n6=int((after == 6).sum()), n7=int((after == 7).sum()),
                                  last_n6=str(after[after == 6].index.max().date()) if (after == 6).any() else None,
                                  last_n7=str(after[after == 7].index.max().date()) if (after == 7).any() else None)
    o = out["since_last_thin"]
    p(f"since the last thin session ({o['last_thin']}): {o['sessions']} sessions, eligible count 6 on {o['n6']} "
      f"(last {o['last_n6']}), 7 on {o['n7']} (last {o['last_n7']})")

    # the margin: on n = 6 / 7 sessions since 2023, how far the least liquid eligible name sat above the floor
    z, adv = panel["z"].reindex(T.index)[UNIVERSE], panel["adv"].reindex(T.index)[UNIVERSE]
    ok = z.notna() & (adv >= MIN_ADV_USD)
    sel = c23[(c23 == 6) | (c23 == 7)].index
    marg, ratio = [], []
    for d in sel:
        a = adv.loc[d][ok.loc[d]].sort_values()
        marg.append(a.index[0])
        ratio.append(float(a.iloc[0] / MIN_ADV_USD))
    ratio = pd.Series(ratio, index=sel)
    out["margin"] = dict(sessions=int(len(sel)), ratio_min=float(ratio.min()), ratio_p10=float(ratio.quantile(0.1)),
                         ratio_median=float(ratio.median()),
                         marginal_name=pd.Series(marg).value_counts().head(5).to_dict())
    p(f"on the {len(sel)} sessions since 2023 with 6 or 7 eligible: the least liquid eligible name's ADV / floor "
      f"min {ratio.min():.2f}, p10 {ratio.quantile(0.1):.2f}, median {ratio.median():.2f}; most often the "
      f"marginal name: {out['margin']['marginal_name']}")

    # a HYPOTHETICAL [U]: had the least liquid eligible name(s) fallen out, what would each rule hold?
    zp, retp = panel["z"], panel["ret"]
    Hf = H[("flatten", "instant")]
    hyp = {}
    for target_n in (5, 4):
        cos, gross, mx, held, skipped = [], [], [], [], []
        for d in sel:
            a = adv.loc[d][ok.loc[d]].sort_values()
            keep_names = list(a.index[len(a) - target_n:])        # drop the least liquid until target_n remain
            i = zp.index.get_loc(d)
            row = zp.loc[d, keep_names]
            w = bf._target_row(row, retp, i).reindex(UNIVERSE).fillna(0.0)
            full = T.loc[d]
            nw, nf = float(np.linalg.norm(w)), float(np.linalg.norm(full))
            if nw == 0 or nf == 0:
                skipped.append(str(d.date()))                     # every z at the clip: 0/0 (PR #33 5.H)
                continue
            cos.append(float((w @ full) / (nw * nf)))
            gross.append(float(w.abs().sum()))
            mx.append(float(w.abs().max()))
            held.append(float(Hf.loc[d].abs().sum()))
        hyp[f"dip_to_{target_n}"] = dict(cos_median=float(np.median(cos)), cos_p10=float(np.percentile(cos, 10)),
                                          gross_median=float(np.median(gross)), maxw_median=float(np.median(mx)),
                                          maxw_p90=float(np.percentile(mx, 90)),
                                          live_held_gross_median=float(np.median(held)), skipped=skipped)
        h = hyp[f"dip_to_{target_n}"]
        p(f"HYPOTHETICAL [U] dip to {target_n} (drop the least liquid eligible names) on {len(cos)} of those "
          f"{len(sel)} sessions (skipped, a 0/0 target: {skipped}): flatten closes a held book of gross "
          f"{h['live_held_gross_median']:.3f} (median); te4's target on the {target_n} left has cosine "
          f"{h['cos_median']:.2f} (p10 {h['cos_p10']:.2f}) to the full target, gross {h['gross_median']:.3f}, "
          f"max |w| {h['maxw_median']:.3f} (p90 {h['maxw_p90']:.3f})")
    out["hypothetical"] = hyp

    # what the rule changed on the actual 2023+ thin sessions
    a, b = HOLDOUT_START, dist_end
    thin_d = thin_days_of(thin, Rt.index)
    m = thin_d.loc[a:b]
    on = {}
    for r in MAIN:
        x = res[(r, "instant")]["pnl"].loc[a:b]
        g = H[(r, "instant")].abs().sum(axis=1).loc[a:b][thin.loc[a:b]]
        on[r] = dict(pp_on_thin_days=float(x[m].sum()), gross_mean=float(g.mean()))
    out["h13_thin"] = dict(days=int(m.sum()), first=str(thin.loc[a:b][thin.loc[a:b]].index.min().date()),
                           last=str(thin.loc[a:b][thin.loc[a:b]].index.max().date()), **on)
    p(f"the 2023+ thin sessions ({out['h13_thin']['first']}..{out['h13_thin']['last']}, {int(m.sum())} earning days): "
      + "; ".join(f"{r} earned {v['pp_on_thin_days'] * 100:+.2f}pp over them, mean gross {v['gross_mean']:.3f}"
                  for r, v in on.items()))

    # expected annual effect [U]: (te4 - flatten) per unit share of traded thin sessions, times a forward share
    def per_share(lab, a_, b_):
        d = (res[("te4", "instant")]["pnl"] - res[("flatten", "instant")]["pnl"]).loc[a_:b_]
        s = float(((thin & (cnt >= FLOOR)).loc[a_:b_]).mean())
        dt = (res[("te4", "deferred")]["pnl"] - res[("flatten", "deferred")]["pnl"]).loc[a_:b_]
        tt = (res[("te4", "instant")]["turn_series"] - res[("flatten", "instant")]["turn_series"]).loc[a_:b_]
        return dict(window=lab, gap=float(d.mean() * P), gap_deferred=float(dt.mean() * P), share=s,
                    per_share=float(d.mean() * P / s) if s > 0 else float("nan"),
                    per_share_deferred=float(dt.mean() * P / s) if s > 0 else float("nan"),
                    extra_turn=float(tt.mean() * P), extra_turn_per_share=float(tt.mean() * P / s) if s > 0 else
                    float("nan"))
    bases = [per_share("FIT <2023", pd.Timestamp(bf.SAMPLE_START), HOLDOUT_START - pd.Timedelta(days=1)),
             per_share("2015-22 (thin = 4-5 names)", pd.Timestamp("2015-01-01"), pd.Timestamp("2022-12-31"))]
    shares = {"0 (the state since 2023-08-30)": 0.0,
              "the 2023+ share": float(((thin & (cnt >= FLOOR)).loc[HOLDOUT_START:dist_end]).mean())}
    tag = td._git_show_json(f"{td.RELEASE_TAG}:ops/specs/cef_discount.frozen.json")
    mult = float(tag["frozen"]["sizing_multiplier"])
    if cef_below_min_names(tag["frozen"]) != "flatten":
        raise AssertionError(f"{td.RELEASE_TAG} sets below_min_names; the comparison is not against its live rule")
    out["expected"] = dict(bases=bases, shares=shares, m=mult, tag=td.RELEASE_TAG, spec_id=tag.get("spec_id"))
    p(f"EXPECTED ANNUAL EFFECT [U] = (te4 - flatten gap per unit share of sessions te4 trades and flatten does not) x "
      f"(a forward share); the current book at {td.RELEASE_TAG} ({tag.get('spec_id')}) multiplies the unit book by m "
      f"= {mult} (ceiling 1.8/m ignored)")
    for bs in bases:
        p(f"  base {bs['window']}: gap {bs['gap'] * 100:+.2f}pp/yr (deferred {bs['gap_deferred'] * 100:+.2f}) on a "
          f"share {bs['share'] * 100:.1f}% -> {bs['per_share'] * 100:+.2f}pp/yr per unit share (deferred "
          f"{bs['per_share_deferred'] * 100:+.2f}); extra turnover {bs['extra_turn']:+.2f}/yr -> "
          f"{bs['extra_turn_per_share']:+.1f}/yr per unit share")
        for sk, sv in shares.items():
            g = bs["per_share"] * sv
            c15 = bs["extra_turn_per_share"] * sv * 15 / 1e4
            p(f"    forward share {sk} = {sv * 100:.1f}%: {g * 100:+.2f}pp/yr gross unit ({g * mult * 100:+.2f} at m); "
              f"extra turnover cost at 15bp {c15 * 100:.2f}pp/yr unit")
    OUT["forward"] = out


# --------------------------------------------------------------------------- main
def main():
    live_rule = cef_below_min_names(spec()["frozen"])
    p(f"spec {SPEC_ID}; band {BAND_WIDTH}, max_gross_stress {MAX_GROSS_STRESS}, min_names {MIN_NAMES}, "
      f"min_adv_usd {MIN_ADV_USD:,.0f}; live below_min_names (registry) {live_rule!r}; floor {FLOOR} (derived), "
      f"plateau {PLATEAU}")
    if live_rule != "flatten":
        raise AssertionError("the live rule is no longer 'flatten'; this report's labels are wrong")
    T, R, thin, panel, dist_end, keep, Rt, TF, BF, cnt = inputs()
    p(f"panels: prices to {panel['px'].index.max().date()}, targets {T.index[0].date()}..{T.index[-1].date()}, "
      f"returns cut at DIST_END {dist_end.date()}")
    for f in PLATEAU:
        tr = thin & (cnt >= f)
        p(f"floor {f}: trades {int(tr.sum())} of the {int(thin.sum())} thin sessions; by era "
          + ", ".join(f"{lab} {int(tr.loc[a:b].sum())}" for lab, a, b in td.windows(dist_end)[:5]))
        OUT.setdefault("traded_thin", {})[f] = {lab: int(tr.loc[a:b].sum()) for lab, a, b in td.windows(dist_end)}
    sleeve_check(T, thin, TF, cnt)
    H = books(T, thin, TF, BF)
    for f in PLATEAU:
        for defer in (False, True):
            ref = td.independent_flatten(TF[f], BF[f], defer)
            got = H[(te(f), "deferred" if defer else "instant")]
            diff = float(np.abs(ref.values - got.values).max())
            if diff > 1e-12:
                raise AssertionError(f"independent loop differs for te{f} by {diff}")
    p("second method 2 [independent pandas loop on the floor's targets and mask]: every te book matches (<= 1e-12)")
    res = {k: bf.evaluate(h.loc[keep], Rt) for k, h in H.items()}
    rep = report(H[(te(FLOOR), "instant")].loc[keep], Rt)
    for k, a, b in (("fit", None, HOLDOUT_START - pd.Timedelta(days=1)), ("holdout", HOLDOUT_START, None)):
        x = res[(te(FLOOR), "instant")]["pnl"].loc[a:b]
        if abs(rep[k]["gross_sr"] - x.mean() / x.std() * np.sqrt(P)) > 1e-12:
            raise AssertionError(f"harness.report disagrees on {k}")
    p(f"second method 3 [harness.report, nan_policy='raise', te{FLOOR} instant]: fit SR {rep['fit']['gross_sr']:.3f}, "
      f"holdout SR {rep['holdout']['gross_sr']:.3f}")

    rows = scoreboard(res, thin, dist_end, MAIN, "STEP 3: hold / flatten / te4, instant and deferred flips", "table")
    paired(res, dist_end, "te4", ("flatten", "hold"), "paired_te4")
    thin_only(res, thin, dist_end, MAIN)
    era_cv(rows, MAIN)
    prow = scoreboard(res, thin, dist_end, tuple(te(f) for f in PLATEAU), "H8 plateau rows: te3 / te4 / te5",
                      "table_plateau")
    era_cv(prow, tuple(te(f) for f in PLATEAU))
    plateau(res, dist_end)
    plateau_per_session(res, thin, cnt, dist_end)
    matched(T, thin, TF, BF, keep, Rt, rows)
    concentration(H, T, thin, TF, cnt, dist_end)
    leave_out(H, keep, Rt, dist_end, "flatten")
    leave_out(H, keep, Rt, dist_end, "hold")
    rebuilt(dist_end)
    borrow(H, keep, Rt, dist_end, res)
    attack(H, T, thin, cnt, panel, keep, Rt, res, dist_end)
    degenerate_replay(T, thin, TF, BF, keep, Rt, dist_end)
    forward(T, thin, panel, cnt, H, res, keep, Rt, dist_end)
    direction_control(T, thin, TF, BF, cnt, keep, Rt, res, dist_end)

    (HERE / "run.log").write_text("\n".join(LOG) + "\n")
    (HERE / "results.json").write_text(json.dumps(OUT, indent=1, default=str))


if __name__ == "__main__":
    main()
