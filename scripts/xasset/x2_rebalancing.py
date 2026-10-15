"""X2 -- front-running pension and balanced-fund rebalancing (Harvey, Mazzoleni & Melone 2026), SPY vs IEF.

    python3 scripts/xasset/x2_rebalancing.py --trial N
    python3 scripts/xasset/x2_rebalancing.py --holdout

Declared in PREREG_XASSET_SLATE_2026-10-12 §5. Every reading below is the
pre-registration's own, written before any return was seen:

* Simulated 60/40 SPY / IEF portfolios on TOTAL returns,
  w' = w(1+R_SP) / [w(1+R_SP) + (1-w)(1+R_10Y)].
* Threshold: 26 portfolios, delta = 0%, 0.1%, ..., 2.5%. The state is the
  post-trade weight at each close; the signal is the PRE-TRADE drift (drifted
  weight - 60%); a portfolio rebalances to 60% when |drift| > delta. Each starts
  at 60% at the close of 2002-07-29 (IEF's first CRSP return). Threshold
  Signal = the average of the 26 drifts.
* Calendar: rebalanced to 60% at every E_m; Calendar(t) = its pre-trade drift.
* w = average of -Threshold/1.5% and the modified Calendar: sign(-Calendar) on
  the week4 component, sign(Calendar_-4) on the Calendar_-4 component, 0 else.
* Exposure days (revision 3): the week4 component sits in H on E-5 .. E-1, each
  with sign(-Calendar) at that row (one session staler than the paper's), and
  so earns E-3 .. D1; the Calendar_-4 component sits in H on E with
  sign(Calendar at E-3), and earns D2. The alternative readings are not run.
* Raw sleeve H = {SPY: +w, IEF: -w}; P5 sizes it. First decision 2002-08-30;
  P&L 2002-09-04 to 2022-12-30, T = 5,118 (Table A).

Stage 2: the control H = {BIL: +w, SHY: -w} with X2's own w, sized by P5; both
Sharpes on 2007-05-31 (BIL's first return) to 2022-12-30, 3,926 sessions; KILL
D1 if the control's gross Sharpe >= 1/2 x X2's. Stage 3: the placebo decides;
shift(3) is reported. Stage 4: MKT and TERM over the full fit; MKT, TERM, HY, IG
from 2007-04-12; both must pass. Reported: R-FF; R-AQR on TSMOM and VME MOM;
the diagnostics of §5 (mid-month placebo window, monthly-sign permutations,
correlation with X3, the week4 component's alpha on X3's sleeve).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import month_end_sessions  # noqa: E402
from scripts.xasset import protocol as P  # noqa: E402
from scripts.xasset.runner import Spec, fit_cache, fit_json, main  # noqa: E402

FIRST_DEC = "2002-08-30"
START = "2002-07-29"                  # Threshold portfolios at 60% at this close (revision 3)
TARGET = 0.60
DELTAS = np.round(np.arange(26) * 0.001, 4)          # 0.000 .. 0.025
THR_SCALE = 0.015
BIL_FIRST = "2007-05-31"
CONTROL_T = 3926
PERMUTATIONS = 1000                 # §5: "1,000 seeded permutations"


def drift(w, a, b):
    return w * (1 + a) / (w * (1 + a) + (1 - w) * (1 + b))


def signals(R: pd.DataFrame, start: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    """Threshold signal (mean pre-trade drift of the 26 portfolios) and Calendar
    signal (pre-trade drift of the month-end-rebalanced portfolio), from the
    session after `start`. Uses returns dated <= t only (H7)."""
    cal = R.index
    me = set(month_end_sessions(cal))
    sp, ief = R["SPY"].values, R["IEF"].values
    i0 = cal.get_loc(start)
    post = np.full(len(DELTAS), TARGET)
    cpost = TARGET
    thr = np.full(len(cal), np.nan)
    cs = np.full(len(cal), np.nan)
    for i in range(i0 + 1, len(cal)):
        a, b = sp[i], ief[i]
        if not (np.isfinite(a) and np.isfinite(b)):
            raise P.ProtocolError(f"X2 drift: missing SPY or IEF return on {cal[i].date()}")
        pre = drift(post, a, b)
        d = pre - TARGET
        thr[i] = d.mean()
        post = np.where(np.abs(d) > DELTAS, TARGET, pre)
        cpre = drift(cpost, a, b)
        cs[i] = cpre - TARGET
        cpost = TARGET if cal[i] in me else cpre
    return pd.Series(thr, index=cal), pd.Series(cs, index=cal)


def calendar_components(cs: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(week4 component, Calendar_-4 component) as H rows (revision 3's exposure days)."""
    cal = cs.index
    w4 = pd.Series(0.0, index=cal)
    c4 = pd.Series(0.0, index=cal)
    for E in month_end_sessions(cal):
        i = cal.get_loc(E)
        for j in range(i - 5, i):                      # E-5 .. E-1
            if j >= 0:
                w4.iloc[j] = np.sign(-cs.iloc[j])
        if i - 3 >= 0:
            c4.iloc[i] = np.sign(cs.iloc[i - 3])       # Calendar at E-3, set on E
    return w4, c4


def weights(R: pd.DataFrame, start=START) -> dict:
    thr, cs = signals(R, pd.Timestamp(start))
    w4, c4 = calendar_components(cs)
    w = 0.5 * (-thr / THR_SCALE) + 0.5 * (w4 + c4)
    w = w.loc[FIRST_DEC:]
    if w.isna().any():
        raise P.ProtocolError("X2 weight has NaN inside the sleeve")
    return dict(w=w, thr=thr, cs=cs, w4=w4.loc[FIRST_DEC:], c4=c4.loc[FIRST_DEC:])


def build(Rx, R, rf, source):
    start = START
    if source == "inhouse":
        # [U reading, reported row only] the in-house panel's IEF starts later than
        # CRSP's, so its portfolios start at the close before its first common return.
        f = max(R["SPY"].first_valid_index(), R["IEF"].first_valid_index())
        start = R.index[R.index.get_loc(f) - 1]
    w = weights(R, start)["w"]
    return pd.DataFrame({"SPY": w, "IEF": -w})


def bil_shy_control(ctx):
    R, Rx, cal = ctx["R"], ctx["Rx"], ctx["cal"]
    if R["BIL"].first_valid_index() != pd.Timestamp(BIL_FIRST):
        raise P.ProtocolError(f"BIL's first return is {R['BIL'].first_valid_index().date()}, declared {BIL_FIRST}")
    w = weights(R)["w"]
    i = cal.get_loc(pd.Timestamp(BIL_FIRST))
    rows = cal[i - 2:]                                  # decided 2 sessions before -> earns from BIL's first return
    Hc = pd.DataFrame({"BIL": w.reindex(rows), "SHY": -w.reindex(rows)})
    win = cal[(cal >= pd.Timestamp(BIL_FIRST)) & (cal <= P.FIT_END)]
    if len(win) != CONTROL_T:
        raise P.ProtocolError(f"control window has {len(win)} sessions; declared {CONTROL_T}")
    sc = P.size(Hc, Rx, win, "BIL/SHY control")
    rc = P.run(sc["H_sized"], Rx, "BIL/SHY control")
    pc = rc["pnl"].reindex(win)
    sr_c, sr_x = P.sharpe(pc), P.sharpe(ctx["pnl"].reindex(win))
    return dict(rule="control {BIL:+w, SHY:-w} gross Sharpe < 1/2 x X2's, both 2007-05-31..2022-12-30 "
                     "(else KILL D1)",
                pass_=sr_c < 0.5 * sr_x, control_sharpe=sr_c, x2_sharpe_same_window=sr_x,
                control_k=sc["k"], window_T=len(win), control_cost_grid=P.cost_grid(pc, rc["turn_series"]))


def control_preflight(data) -> dict:
    """Zero-trial (dates only): BIL's first return and the control window's length
    are as declared, so a mismatch halts BEFORE the trial is spent."""
    R, cal = data["R"], data["cal"]
    f = R["BIL"].first_valid_index()
    if f != pd.Timestamp(BIL_FIRST):
        raise P.ProtocolError(f"BIL's first return is {f.date()}, declared {BIL_FIRST}")
    n = int(((cal >= f) & (cal <= P.FIT_END)).sum())
    if n != CONTROL_T:
        raise P.ProtocolError(f"control window has {n} sessions; declared {CONTROL_T}")
    if R["SHY"].first_valid_index() > f or pd.Timestamp(START) not in cal:
        raise P.ProtocolError("SHY or the Threshold start date is not in the panel as declared")
    return dict(bil_first=str(f.date()), control_T=n)


def cross_with_x3(R, Rx, window, k_x2: float, x2_pnl: pd.Series, x3_pnl: pd.Series) -> dict:
    """§5 diagnostics needing both series (§1.12): the daily correlation of the two
    sized sleeves, and the alpha of X2's week4 component (sized by X2's k) on X3's
    sized sleeve, HAC L = 21. Computed by whichever of X2 and X3 runs second."""
    W = weights(R)
    w4p = _cal_part_pnl(W["w4"], k_x2, Rx, window)
    j = pd.concat([x2_pnl.rename("x2"), x3_pnl.rename("x3"), w4p.rename("w4")], axis=1).dropna()
    return dict(corr_with_x3_daily=float(j["x2"].corr(j["x3"])),
                week4_alpha_on_x3=P.ols_hac(j["w4"], j[["x3"]], P.NW_LAGS, 252))


def committed_series(key: str) -> pd.Series:
    """A sibling test's committed sized fit series, checked against its verdict's hash."""
    if not (fit_cache(key).exists() and P.git_tracked(fit_json(key))):
        return None
    if P.sha256(fit_cache(key)) != json.loads(fit_json(key).read_text())["fit_series_cache"]["sha256"]:
        raise P.ProtocolError(f"{key}'s cached fit series does not match its committed verdict")
    return pd.read_parquet(fit_cache(key))["pnl_sized"]


def _cal_part_pnl(part: pd.Series, k: float, Rx: pd.DataFrame, window) -> pd.Series:
    H = pd.DataFrame({"SPY": 0.5 * part * k, "IEF": -0.5 * part * k})
    return P.run(H, Rx, "calendar part")["pnl"].reindex(window)


def extras(ctx):
    """§5 diagnostics, reported, never kills."""
    R, Rx, cal, window, k = ctx["R"], ctx["Rx"], ctx["cal"], ctx["window"], ctx["sized"]["k"]
    W = weights(R)
    out = {}
    real = _cal_part_pnl(W["w4"] + W["c4"], k, Rx, window)
    # mid-month placebo window: [U reading] the week4 rule moved to the month's
    # sessions 6-10 (paper time), mapped as revision 3 maps week4: H rows at
    # sessions 5-9 with sign(-Calendar) at that row; no Calendar_-4 analogue.
    cs = W["cs"]
    mid = pd.Series(0.0, index=cal)
    pos = pd.Series(np.arange(len(cal)), index=cal)
    first_of_month = pos.groupby([cal.year, cal.month]).transform("min")
    n_in_month = (pos - first_of_month + 1)
    for j in np.where((n_in_month >= 5) & (n_in_month <= 9))[0]:
        mid.iloc[j] = np.sign(-cs.iloc[j])
    mid = mid.loc[FIRST_DEC:]
    pm = _cal_part_pnl(mid, k, Rx, window)
    out["calendar_part"] = dict(sharpe=P.sharpe(real), ann_mean_pct=float(real.mean() * 252 * 100))
    out["mid_month_placebo_window"] = dict(sharpe=P.sharpe(pm), ann_mean_pct=float(pm.mean() * 252 * 100),
                                           reading="[U] sessions 6-10 in paper time, H rows 5-9")
    # permutations of the Calendar part's monthly sign patterns: [U reading] each
    # month's block of Calendar-part rows (E-5 .. E) is reassigned to another
    # month, 1,000 seeded draws.
    part = (W["w4"] + W["c4"])
    me = [E for E in month_end_sessions(part.index) if part.index.get_loc(E) >= 5]
    blocks = [part.iloc[part.index.get_loc(E) - 5: part.index.get_loc(E) + 1].values for E in me]
    rng = np.random.default_rng(P.SEED)
    srs = []
    for _ in range(PERMUTATIONS):
        perm = rng.permutation(len(blocks))
        q = pd.Series(0.0, index=part.index)
        for E, b in zip(me, perm):
            i = part.index.get_loc(E)
            q.iloc[i - 5:i + 1] = blocks[b]
        srs.append(P.sharpe(_cal_part_pnl(q, k, Rx, window)))
    srs = np.array(srs)
    out["calendar_sign_permutations"] = dict(draws=PERMUTATIONS, p95=float(np.percentile(srs, 95)),
                                             share_below_real=float((srs < P.sharpe(real)).mean()),
                                             reading="[U] month blocks E-5..E permuted across months")
    # correlation with X3, and the week4 component's alpha on X3's sized sleeve (§1.12)
    x3 = committed_series("X3")
    if x3 is not None:
        out.update(cross_with_x3(R, Rx, window, k, ctx["pnl"], x3))
    else:
        out["corr_with_x3_daily"] = "pending: computed by X3's run, which follows (§1.12)"
    return out


def holdout_extras(c):
    x = c["pnl"].loc["2023-03-18":]
    return dict(post_paper_sample_from_2023_03_18=dict(n=len(x), sharpe=P.sharpe(x),
                                                       ann_mean_pct=float(x.mean() * 252 * 100)))


SPEC = Spec(
    key="X2", title="X2 rebalancing front-run", names=["SPY", "IEF"], first_dec=FIRST_DEC, T_declared=5118,
    build=build, control=bil_shy_control, control_kill="KILL D1 (stage 2: not rebalancing pressure)",
    shift3_decides=False,
    d4=[("R-D4 full fit", ["MKT", "TERM"], None),
        ("R-D4 from 2007-04-12", ["MKT", "TERM", "HY", "IG"], "2007-04-12")],
    aqr=["TSMOM", "VME_MOM"], extras=extras, holdout_extras=holdout_extras, preflight=control_preflight)

if __name__ == "__main__":
    sys.exit(main(SPEC))
