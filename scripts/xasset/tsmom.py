"""Time-series momentum (MOP 2012) and its two declared comparators, for X1 and X4.

PREREG_XASSET_SLATE_2026-10-12 §4 (X1) and §7 (X4, "X1's table, unchanged"):

| MOP parameter | applied here |
|---|---|
| sign of the past 12-month excess return (k = 12, h = 1) | compounded daily excess return over (E_{m-12}, E_m]; long if >= 0, short if < 0 (HLWZ's tie rule) |
| ex-ante variance, EWMA, centre of mass 60 days, x 261 | `ewm(com=60, adjust=True)` variance of daily excess returns through E_m, x 261 |
| position 40% / sigma | raw sleeve verbatim; P5 then scales it |
| equal weight over the S_t securities available | 1/S_t over the names eligible at E_m (12 months of returns) |
| one-month holding | refreshed at each E_m; held to the next (`hold_from_refresh`), earned from E_m + 2 (H1) |

A name in `protocol.NOT_SHORTABLE` (MUB) is long-or-flat (P6): a short signal
gives it 0. It still counts in S_t: it is available, and only its position is
constrained.

The comparators use the same weights and differ only in the sign:
* TSH (HLWZ eq. 17): the sign of the INCEPTION-TO-DATE cumulative excess return,
  from the name's first return in the primary panel through E_m;
* LONG (R-LONG, MOP p.236): sign = +1 for every name.

ALIGNMENT (H7): everything at E_m uses returns dated <= E_m; `build` receives a
return panel already truncated by the caller (the fit panel ends 2022-12-30), and
asserts the targets' last date is not after it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.cef.band_frontier import hold_from_refresh, month_end_sessions
from scripts.xasset import protocol as P

LOOKBACK_M = 12
POS_SCALE = 0.40
EWM_COM = 60
ANN_DAYS = 261          # MOP eq. 1


def cum_log(rx: pd.Series) -> pd.Series:
    """Cumulative log excess return through each date: 0.0 before the name's first
    return (nothing has accrued), the running sum after it.

    WHY NOT `np.log1p(rx).cumsum()`: that leaves NaN on every date before the first
    return. A name whose first return is exactly the first session of its
    12-month window (PFF: 2007-04-02, the first session of April 2007) is
    eligible at that window's month-end, and `logc[E] - logc[start]` would be
    NaN; `NaN >= 0` is False, so the name would be SHORTED with no data behind
    the sign. A gap inside the live range is a different thing (a missing
    return, H15) and raises."""
    r = rx.dropna()
    if r.empty:
        return pd.Series(np.nan, index=rx.index)
    live = rx.loc[r.index[0]:r.index[-1]]
    if live.isna().any():
        raise P.ProtocolError(f"{rx.name}: {int(live.isna().sum())} missing returns inside its live range")
    c = np.log1p(r).cumsum().reindex(rx.index)
    c.loc[:r.index[0]] = c.loc[:r.index[0]].fillna(0.0)
    return c.ffill()


def ex_ante_sigma(rx: pd.Series) -> pd.Series:
    """sqrt(261 x EWMA variance), centre of mass 60, of the name's daily excess returns."""
    r = rx.dropna()
    return np.sqrt(ANN_DAYS * r.ewm(com=EWM_COM, adjust=True).var())


def targets(Rx: pd.DataFrame, names, first_dec: pd.Timestamp, sign_rule: str = "tsmom",
            exclude=()) -> pd.DataFrame:
    """Monthly raw targets from `first_dec` to the panel's last month-end.

    sign_rule: "tsmom" (12-month), "tsh" (inception-to-date) or "long" (+1).
    `exclude` drops names (the leave-one-out rows); eligibility is recomputed."""
    cal = Rx.index
    me = month_end_sessions(cal)
    me = me[me >= first_dec]
    names = [n for n in names if n not in set(exclude)]
    firsts = {n: Rx[n].first_valid_index() for n in names}
    me_all = month_end_sessions(cal)
    logc = {n: cum_log(Rx[n]) for n in names}
    sig = {n: ex_ante_sigma(Rx[n]) for n in names}
    rows = []
    for E in me:
        elig = P.eligible_at(E, names, firsts, cal, me_all, LOOKBACK_M)
        row = dict.fromkeys(names, 0.0)
        S = len(elig)
        for n in elig:
            if sign_rule == "tsmom":
                i = me_all.get_loc(E)
                start = me_all[i - LOOKBACK_M]
                cum = np.expm1(logc[n].loc[E] - logc[n].loc[start])
                if not np.isfinite(cum):
                    raise P.ProtocolError(f"{n} at {E.date()}: 12-month return is not finite")
                s = 1.0 if cum >= 0 else -1.0
            elif sign_rule == "tsh":
                cum = np.expm1(logc[n].loc[E])          # from the first return through E
                if not np.isfinite(cum):
                    raise P.ProtocolError(f"{n} at {E.date()}: inception-to-date return is not finite")
                s = 1.0 if cum >= 0 else -1.0
            elif sign_rule == "long":
                s = 1.0
            else:
                raise ValueError(sign_rule)
            if n in P.NOT_SHORTABLE:
                s = max(s, 0.0)
            sg = sig[n].loc[E]
            if not (np.isfinite(sg) and sg > 0):
                raise P.ProtocolError(f"{n} at {E.date()}: ex-ante sigma {sg}")
            row[n] = s * POS_SCALE / sg / S
        rows.append(row)
    T = pd.DataFrame(rows, index=me, columns=names)
    assert T.index.max() <= Rx.index.max()
    return T


def build(Rx: pd.DataFrame, names, first_dec: pd.Timestamp, sign_rule: str = "tsmom",
          exclude=()) -> pd.DataFrame:
    """The raw sleeve H, rows from `first_dec` to the panel's end."""
    T = targets(Rx, names, first_dec, sign_rule, exclude)
    idx = Rx.index[Rx.index >= first_dec]
    return hold_from_refresh(T, idx)


def daily_targets(Rx: pd.DataFrame, names, first_dec: pd.Timestamp) -> pd.DataFrame:
    """The TSMOM target computed on EVERY session (for the month-end refresh
    offset band, P11; reported only). [U reading: "12 calendar months" before a
    session t is the window (s, t], s = the last session on or before t minus 12
    calendar months; eligible once the first return is on or before the first
    session after s.]"""
    cal = Rx.index
    idx = cal[cal >= first_dec]
    out = pd.DataFrame(0.0, index=idx, columns=list(names))
    firsts = {n: Rx[n].first_valid_index() for n in names}
    logc = {n: cum_log(Rx[n]) for n in names}
    sig = {n: ex_ante_sigma(Rx[n]) for n in names}
    for t in idx:
        cut = t - pd.DateOffset(months=LOOKBACK_M)
        prev = cal[cal <= cut]
        if not len(prev):
            continue
        s0 = prev[-1]
        first_after = cal[cal > s0][0]
        elig = [n for n in names if firsts[n] is not None and firsts[n] <= first_after]
        S = len(elig)
        for n in elig:
            cum = np.expm1(logc[n].loc[t] - logc[n].loc[s0])
            if not np.isfinite(cum):
                raise P.ProtocolError(f"{n} at {t.date()}: 12-month return is not finite")
            s = 1.0 if cum >= 0 else -1.0
            if n in P.NOT_SHORTABLE:
                s = max(s, 0.0)
            out.at[t, n] = s * POS_SCALE / sig[n].loc[t] / S
    return out
