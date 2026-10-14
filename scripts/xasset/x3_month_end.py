"""X3 -- the month-end Treasury extension (Hartley & Schwarz 2019), long IEF over the last three sessions.

    python3 scripts/xasset/x3_month_end.py --trial N
    python3 scripts/xasset/x3_month_end.py --holdout

Declared in PREREG_XASSET_SLATE_2026-10-12 §6. H&S: buy "t trading days before
the end of the month" and sell "on the last day of the month (at the close of
business)", t = 3. Applied: long IEF from the close of E-3 to the close of E,
earning E-2, E-1 and E, so H.loc = 1 on E-4, E-3 and E-2 -- decided early, which
P4 allows because the trading calendar is published in advance (the information
used is still data through t: none). Raw notional 1; P5 sizes it. First decision
2002-08-30; P&L 2002-09-04 to 2022-12-30, T = 5,118 (Table A). The sleeve is
part-time: its daily P&L is zero outside the windows, and every statistic is on
that daily series.

Stage 2: IEF on every other session (H&S eq. 2; H = 1 except on E-4..E-2), sized
by P5, two trades a month as X3; KILL D1 unless its gross Sharpe < 1/2 x X3's.
Stage 3: the placebo decides; shift(3) is reported (§1.8). Stage 4: TERM and MKT
over the full fit, and TERM, MKT, HY, IG from 2007-04-12; both must pass.
Stated in advance (§6): stage 4 very probably kills X3, because its TERM beta
grows with the window notional P5 sets. A TERM-hedged X3 is a new trial.
Reported: R-FF; R-AQR on TSMOM^FI; regime rows (2002-18 inside the paper's
sample, 2019-22 after; T+2 from 2017-09-05; T+1 from 2024-05-28 in the holdout).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import month_end_sessions  # noqa: E402
from scripts.xasset import protocol as P  # noqa: E402
from scripts.xasset.runner import Spec, main  # noqa: E402

FIRST_DEC = "2002-08-30"
T_DAYS = 3          # H&S t = 3


def window_rows(cal: pd.DatetimeIndex) -> pd.Series:
    """1.0 on E-4, E-3, E-2 of every month in `cal` (earning E-2, E-1, E), else 0."""
    me = month_end_sessions(cal)
    h = pd.Series(0.0, index=cal)
    for E in me:
        i = cal.get_loc(E)
        for j in range(i - T_DAYS - 1, i - 1):
            if j >= 0:
                h.iloc[j] = 1.0
    return h


def build(Rx, R, rf, source):
    h = window_rows(Rx.index).loc[FIRST_DEC:]
    return pd.DataFrame({"IEF": h})


def other_sessions_control(ctx):
    Rx, window = ctx["Rx"], ctx["window"]
    h = 1.0 - window_rows(Rx.index).loc[FIRST_DEC:]
    sc = P.size(pd.DataFrame({"IEF": h}), Rx, window, "IEF other sessions")
    rc = P.run(sc["H_sized"], Rx, "IEF other sessions")
    pc = rc["pnl"].reindex(window)
    sr_c, sr_x = P.sharpe(pc), P.sharpe(ctx["pnl"])
    return dict(rule="IEF-on-other-sessions gross Sharpe < 1/2 x X3's (else KILL D1)",
                pass_=sr_c < 0.5 * sr_x, control_sharpe=sr_c, x3_sharpe=sr_x, control_k=sc["k"],
                control_cost_grid=P.cost_grid(pc, rc["turn_series"]))


def extras(ctx):
    pnl = ctx["pnl"]
    rows = {}
    for lab, a, b in [("2002-09..2018 (inside H&S's sample)", None, "2018-12-31"),
                      ("2019-2022 (after it)", "2019-01-01", None),
                      ("before T+2 (to 2017-09-01)", None, "2017-09-01"),
                      ("T+2 (2017-09-05 on)", "2017-09-05", None)]:
        x = pnl.loc[a:b]
        rows[lab] = dict(n=len(x), sharpe=P.sharpe(x), ann_mean_pct=float(x.mean() * 252 * 100),
                         nw_t21=P.nw_t(x))
    out = dict(regime_rows=rows)
    # §1.12: X2's diagnostics that need X3's series, if X2 ran first
    from scripts.xasset import x2_rebalancing as x2
    x2p = x2.committed_series("X2")
    if x2p is not None:
        import json
        k2 = json.loads(x2.fit_json("X2").read_text())["stage0b"]["k"]
        w2 = P.pnl_window(pd.Timestamp(x2.FIRST_DEC), ctx["cal"])
        out["x2_cross_rows"] = x2.cross_with_x3(ctx["R"], ctx["Rx"], w2, k2, x2p, pnl)
    return out


def holdout_extras(c):
    x = c["pnl"].loc["2024-05-28":]
    return dict(regime_T1_from_2024_05_28=dict(n=len(x), sharpe=P.sharpe(x),
                                               ann_mean_pct=float(x.mean() * 252 * 100)))


SPEC = Spec(
    key="X3", title="X3 month-end Treasury extension", names=["IEF"], first_dec=FIRST_DEC, T_declared=5118,
    build=build, control=other_sessions_control,
    control_kill="KILL D1 (stage 2: the term premium, not month-end)", shift3_decides=False,
    d4=[("R-D4 full fit", ["TERM", "MKT"], None),
        ("R-D4 from 2007-04-12", ["TERM", "MKT", "HY", "IG"], "2007-04-12")],
    aqr=["TSMOM^FI"], extras=extras, holdout_extras=holdout_extras)

if __name__ == "__main__":
    sys.exit(main(SPEC))
