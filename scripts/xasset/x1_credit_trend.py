"""X1 -- credit and rates trend (MOP time-series momentum on nine credit and rates ETFs).

    python3 scripts/xasset/x1_credit_trend.py --trial N     # fit stages; spends XASSET trial N
    python3 scripts/xasset/x1_credit_trend.py --holdout     # once, after all four fit verdicts

Declared in `results/xasset/PREREG_XASSET_SLATE_2026-10-12.md` §4 (revision 3,
approved 2026-10-14, N = 4). Nothing here is chosen: the rule is
`scripts/xasset/tsmom.py` (MOP's parameters, mapped in §4's table), the order of
evaluation is `scripts/xasset/runner.py` (§1.11), and the inputs are the Stage
0a manifest's.

Instruments HYG LQD IEF TLT EMB PFF MUB BKLN CWB; MUB long-or-flat (P6). First
decision 2008-04-30 (>= 5 of 9 with 12 months of returns); P&L 2008-05-02 to
2022-12-30, T = 3,693 (Table A).

Stage 2, the TSH control (HLWZ eq. 17): the same weights with the sign of the
inception-to-date excess return, sized by P5 with its own k. X1 must beat it on
gross Sharpe AND on the net Sharpe at 5, 15 and 30bp, each charged its own
turnover; otherwise KILL D4 (the historical-mean rule). Stage 3: the placebo and
shift(3) both decide. Stage 4: R-D4 on MKT, TERM, HY, IG (one regression; HYG
trades from the first decision). Reported: R-FF, R-AQR on TSMOM^FI and TSMOM,
R-LONG, leave-one-instrument-out, the 21 refresh offsets.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.xasset import protocol as P, tsmom  # noqa: E402
from scripts.xasset.runner import Spec, main  # noqa: E402

NAMES = P.X1_NAMES
FIRST_DEC = "2008-04-30"


def build(Rx, R, rf, source, names=NAMES, first_dec=FIRST_DEC, sign_rule="tsmom", exclude=()):
    return tsmom.build(Rx, names, pd.Timestamp(first_dec), sign_rule, exclude)


def tsh_control(ctx, names=NAMES, first_dec=FIRST_DEC):
    """Stage 2 (X1 and X4): TSMOM must beat TSH gross and at 5 / 15 / 30bp."""
    Rx, window = ctx["Rx"], ctx["window"]
    Hc = tsmom.build(Rx, names, pd.Timestamp(first_dec), "tsh")
    sc = P.size(Hc, Rx, window, "TSH")
    rc = P.run(sc["H_sized"], Rx, "TSH")
    pc, tc = rc["pnl"].reindex(window), rc["turn_series"]
    gx, gc = P.cost_grid(ctx["pnl"], ctx["turn"]), P.cost_grid(pc, tc)
    beats = dict(gross=gx["gross_sr"] > gc["gross_sr"], net5=gx["net5"] > gc["net5"],
                 net15=gx["net15"] > gc["net15"], net30=gx["net30"] > gc["net30"])
    diff = ctx["pnl"] - pc
    d = P.paired_sharpe_diff(ctx["pnl"].values, pc.values)
    return dict(rule="X1 beats TSH on gross and on net at 5/15/30bp (each its own turnover)",
                pass_=all(beats.values()), beats=beats, x=gx, tsh=gc, tsh_k=sc["k"],
                nw_t21_daily_difference=P.nw_t(diff),
                boot21_sharpe_difference_ci=[float(np.nanpercentile(d, 2.5)), float(np.nanpercentile(d, 97.5))])


def trend_extras(ctx, names=NAMES, first_dec=FIRST_DEC):
    """Reported only: R-LONG, leave-one-instrument-out, the 21 refresh offsets."""
    Rx, window, pnl = ctx["Rx"], ctx["window"], ctx["pnl"]
    fd = pd.Timestamp(first_dec)
    out = {}
    Hl = tsmom.build(Rx, names, fd, "long")
    sl = P.size(Hl, Rx, window, "LONG")
    pl = P.run(sl["H_sized"], Rx, "LONG")["pnl"].reindex(window)
    out["r_long"] = P.ols_hac(pnl, pl.rename("LONG").to_frame(), P.NW_LAGS, 252) | dict(
        long_only_sharpe=P.sharpe(pl))
    loo = {}
    for n in names:
        H = tsmom.build(Rx, names, fd, "tsmom", exclude=(n,))
        loo[n] = P.sharpe(P.run(H, Rx, "LOO")["pnl"].reindex(window))
    v = np.array(list(loo.values()))
    out["leave_one_out"] = dict(by_name=loo, min=float(v.min()), median=float(np.median(v)),
                                max=float(v.max()),
                                reading="[U] same first decision and window; 1/S_t over the remaining eligible names")
    from scripts.cef.band_frontier import calendar_offset
    Td = tsmom.daily_targets(Rx, names, fd)
    offs = [P.sharpe(P.run(calendar_offset(Td, 21, o), Rx, "offset")["pnl"].reindex(window))
            for o in range(21)]
    out["refresh_offsets_21"] = dict(min=float(min(offs)), median=float(np.median(offs)), max=float(max(offs)),
                                     all=offs, reading=tsmom.daily_targets.__doc__.split("[U reading:")[1].strip(" ]\n"))
    return out


SPEC = Spec(
    key="X1", title="X1 credit and rates trend", names=NAMES, first_dec=FIRST_DEC, T_declared=3693,
    build=build, control=tsh_control, control_kill="KILL D4 (stage 2: the historical-mean rule, TSH)",
    shift3_decides=True, d4=[("R-D4", ["MKT", "TERM", "HY", "IG"], None)],
    aqr=["TSMOM^FI", "TSMOM"], extras=trend_extras,
    notes=["MUB is long-or-flat and counts in S_t (it is available; only its position is constrained)."])

if __name__ == "__main__":
    sys.exit(main(SPEC))
