"""X4 -- multi-asset trend (MOP time-series momentum on X1's nine plus SPY EFA EEM GLD DBC).

    python3 scripts/xasset/x4_multi_trend.py --trial N
    python3 scripts/xasset/x4_multi_trend.py --holdout

Declared in PREREG_XASSET_SLATE_2026-10-12 §7: X1's table unchanged
(`scripts/xasset/tsmom.py`); breadth >= 7 of 14, first decision 2005-11-30; P&L
2005-12-02 to 2022-12-30, T = 4,299 (Table A). The decision is on the combined
sleeve only; rows by asset class are reported and never selected from.

Stage 2: TSH on X4's universe (as X1). Stage 4: two R-D4 regressions, both must
pass: MKT, TERM, COMMOD, GOLD, INTL, EM over the full fit (from the factors'
first common date), and the same plus HY and IG from 2007-04-12. Reported: R-FF;
R-AQR on TSMOM, TSMOM^EQ, TSMOM^CM; R-LONG; leave-one-out; refresh offsets;
asset-class rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.xasset import protocol as P, tsmom  # noqa: E402
from scripts.xasset.runner import Spec, main  # noqa: E402
from scripts.xasset.x1_credit_trend import trend_extras, tsh_control  # noqa: E402

NAMES = P.X4_NAMES
FIRST_DEC = "2005-11-30"
# [U reading] the asset-class rows (reported only): X1's nine as one class, as
# X1 declares them; equities SPY EFA EEM; commodities GLD DBC.
CLASSES = {"credit_and_rates": P.X1_NAMES, "equity": ["SPY", "EFA", "EEM"], "commodity": ["GLD", "DBC"]}


def build(Rx, R, rf, source):
    return tsmom.build(Rx, NAMES, pd.Timestamp(FIRST_DEC), "tsmom")


def extras(ctx):
    out = trend_extras(ctx, NAMES, FIRST_DEC)
    Hs, Rx, w = ctx["sized"]["H_sized"], ctx["Rx"], ctx["window"]
    rows = {}
    for c, names in CLASSES.items():
        H = Hs.copy()
        H[[n for n in H.columns if n not in names]] = 0.0
        p = P.run(H, Rx, "class " + c)["pnl"].reindex(w)
        rows[c] = dict(sharpe=P.sharpe(p), ann_mean_pct=float(p.mean() * 252 * 100))
    out["asset_class_rows"] = dict(rows=rows, reading="[U] each class's contribution to the sized sleeve")
    return out


SPEC = Spec(
    key="X4", title="X4 multi-asset trend", names=NAMES, first_dec=FIRST_DEC, T_declared=4299,
    build=build, control=lambda ctx: tsh_control(ctx, NAMES, FIRST_DEC),
    control_kill="KILL D4 (stage 2: the historical-mean rule, TSH)", shift3_decides=True,
    d4=[("R-D4 full fit", ["MKT", "TERM", "COMMOD", "GOLD", "INTL", "EM"], None),
        ("R-D4 from 2007-04-12", ["MKT", "TERM", "COMMOD", "GOLD", "INTL", "EM", "HY", "IG"], "2007-04-12")],
    aqr=["TSMOM", "TSMOM^EQ", "TSMOM^CM"], extras=extras,
    notes=["MUB is long-or-flat and counts in S_t.", "X1 and X4 share 9 of 14 names; both count as trials."])

if __name__ == "__main__":
    sys.exit(main(SPEC))
