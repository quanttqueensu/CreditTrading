"""Do distribution cuts permanently re-rate a CEF's discount?

THE RISK THIS TESTS
-------------------
The sleeve buys funds trading cheap against their own 252-day discount history.
That is correct when the discount is a temporary dislocation and wrong when the
fund has been permanently re-rated -- and the textbook cause of a permanent
re-rating in a closed-end fund is a distribution cut. A fund yielding 9% that
cuts to 6% loses the retail buyer who owned it for the yield; the discount widens
and STAYS wide. To the z-score that looks like an unusually cheap fund, so the
sleeve buys more of it. This is the classic value trap in this asset class and
the deployed sleeve has no defence against it.

WHAT IS MEASURED, IN ORDER
1. EVENT STUDY. Mean discount around a cut, t-30 to t+60 trading days, against a
   no-event control drawn from the same funds. If the discount widens and does
   not recover, the re-rating is permanent.
2. IS THE Z-SCORE FOOLED? What the sleeve's own signal says about cut funds --
   if post-cut z drifts negative ("cheap"), the sleeve is being actively pulled
   into them.
3. FORWARD RETURNS. Do recently-cut funds underperform at the horizons we trade?
4. THE RULE. Sleeve performance with recently-cut funds excluded, swept over the
   exclusion window, so the window is chosen from the curve and not by taste.

POINT-IN-TIME DISCIPLINE. Distributions are declared two to four weeks before the
ex-date, so a rule keyed on ex_date acts strictly LATER than a real desk could.
That is deliberate: it understates the benefit rather than manufacturing one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.cef.validate import load_raw, signals, MIN_ADV  # noqa: E402

HOLD = 5


def load_events():
    d = pd.read_parquet(REPO / "data/cef/cef_dist_features.parquet")
    d["ex_date"] = pd.to_datetime(d["ex_date"])
    return d


def event_study(disc, ev, mask, label, pre=30, post=60):
    """Mean discount path around an event, indexed to t=0."""
    idx = disc.index
    rows = []
    for _, r in ev[mask].iterrows():
        tk = r["ticker"]
        if tk not in disc.columns:
            continue
        pos = idx.searchsorted(r["ex_date"])
        if pos < pre or pos + post >= len(idx):
            continue
        seg = disc[tk].iloc[pos - pre: pos + post + 1].to_numpy(dtype=float)
        if np.isnan(seg).mean() > 0.2:
            continue
        rows.append(seg - seg[pre])           # index to the event date
    if not rows:
        return None
    A = np.vstack(rows)
    return pd.Series(np.nanmean(A, axis=0), index=range(-pre, post + 1),
                     name=f"{label} (n={len(rows)})")


def main() -> int:
    px, nav, vol = load_raw()
    disc, z, adv = signals(px, nav, vol)
    ev = load_events()
    ev = ev[ev.ticker.isin(disc.columns)]

    print("=" * 78)
    print("1. EVENT STUDY — discount change around a distribution cut (pp)")
    print("=" * 78)
    cut = event_study(disc, ev, ev.is_cut.astype(bool), "cut")
    big = event_study(disc, ev, ev.is_cut.astype(bool) & (ev.pct_change_vs_prev <= -20),
                      "cut >=20%")
    raise_ = event_study(disc, ev, ev.is_raise.astype(bool), "raise")
    flat = event_study(disc, ev, ~ev.is_cut.astype(bool) & ~ev.is_raise.astype(bool),
                       "unchanged (control)")
    tab = pd.concat([s for s in (cut, big, raise_, flat) if s is not None], axis=1)
    print(tab.loc[[-30, -10, -5, 0, 5, 10, 21, 42, 60]].round(3).to_string())
    print("\n  A NEGATIVE number is a WIDER discount (price further below NAV).")
    if cut is not None:
        print(f"  cut: t+0 {cut.loc[0]:+.3f} -> t+21 {cut.loc[21]:+.3f} -> "
              f"t+60 {cut.loc[60]:+.3f} pp")
        print(f"  recovery by t+60: "
              f"{100 * (1 - cut.loc[60] / cut.loc[21]):.0f}% of the t+21 move"
              if abs(cut.loc[21]) > 1e-9 else "")

    print("\n" + "=" * 78)
    print("2. IS OUR OWN SIGNAL FOOLED? mean z-score of cut funds after the cut")
    print("=" * 78)
    idx = disc.index
    for lo, hi in [(0, 5), (5, 21), (21, 63), (63, 126)]:
        vals = []
        for _, r in ev[ev.is_cut.astype(bool)].iterrows():
            tk = r["ticker"]
            if tk not in z.columns:
                continue
            p = idx.searchsorted(r["ex_date"])
            seg = z[tk].iloc[p + lo: p + hi].to_numpy(dtype=float)
            vals.extend(seg[~np.isnan(seg)])
        if vals:
            m = float(np.mean(vals))
            print(f"  t+{lo:>3}..{hi:<3}  mean z {m:+.3f}   n={len(vals):,}"
                  f"   {'<-- reads CHEAP, sleeve goes LONG' if m < -0.1 else ''}")

    print("\n" + "=" * 78)
    print("3. FORWARD RETURNS after a cut, at the horizons we trade")
    print("=" * 78)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    xs = ret.sub(ret.mean(axis=1), axis=0)          # cross-sectional excess
    for h in (5, 10, 21, 63):
        fwd = (1 + xs).rolling(h).apply(np.prod, raw=True).shift(-h) - 1
        a, b = [], []
        for _, r in ev.iterrows():
            tk = r["ticker"]
            if tk not in fwd.columns:
                continue
            p = idx.searchsorted(r["ex_date"])
            if p >= len(idx):
                continue
            v = fwd[tk].iloc[p]
            if np.isnan(v):
                continue
            (a if bool(r.is_cut) else b).append(v)
        if a and b:
            ta = (np.mean(a) - np.mean(b)) / np.sqrt(
                np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b))
            print(f"  h={h:>2}d  cut {100*np.mean(a):+6.3f}%  "
                  f"no-cut {100*np.mean(b):+6.3f}%  diff "
                  f"{100*(np.mean(a)-np.mean(b)):+6.3f}%  t={ta:+5.2f}  "
                  f"n_cut={len(a)}")

    print("\n" + "=" * 78)
    print("4. THE RULE — exclude recently-cut funds, sweep the window")
    print("=" * 78)
    # a per-date boolean: was this fund cut within the last W trading days?
    def cut_mask(window):
        m = pd.DataFrame(False, index=idx, columns=disc.columns)
        for _, r in ev[ev.is_cut.astype(bool)].iterrows():
            tk = r["ticker"]
            if tk not in m.columns:
                continue
            p = idx.searchsorted(r["ex_date"])
            m.iloc[p:p + window, m.columns.get_loc(tk)] = True
        return m

    elig0 = adv.fillna(0.0) >= MIN_ADV

    def run(excl=None, long_only=False):
        elig = elig0 if excl is None else (elig0 & ~excl if not long_only else elig0)
        W = pd.DataFrame(0.0, index=idx, columns=px.columns)
        for t in idx[::HOLD]:
            row = z.loc[t][elig.loc[t]].dropna()
            if len(row) < 6:
                continue
            v = -(row - row.mean())
            if long_only and excl is not None:
                # keep the short leg, refuse only the LONG side of cut funds
                banned = excl.loc[t]
                v = v[~((v > 0) & v.index.map(lambda c: bool(banned.get(c, False))))]
                if len(v) < 6:
                    continue
                v = v - v.mean()
            if v.abs().sum() < 1e-9:
                continue
            W.loc[t, v.index] = (v / v.abs().sum()).values
        W = W.replace(0.0, np.nan).ffill(limit=HOLD - 1).fillna(0.0)
        raw = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
        rv = raw.shift(1).rolling(63, min_periods=30).std() * np.sqrt(252)
        W = W.mul((0.06 / rv.replace(0, np.nan)).clip(0.2, 2.5).fillna(1.0), axis=0)
        g1 = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
        g2 = (W.shift(2).fillna(0.0) * ret).sum(axis=1)
        sr = lambda s: s.mean() / s.std() * np.sqrt(252)
        return sr(g1), sr(g2)

    base = run(None)
    print(f"  {'baseline (no filter)':38s} gross SR shift1 {base[0]:+5.2f}  "
          f"shift2 {base[1]:+5.2f}")
    for w in (21, 63, 126, 252):
        m = cut_mask(w)
        both = run(m)
        lo = run(m, long_only=True)
        print(f"  exclude cut funds {w:>3}d (both legs)      "
              f"shift1 {both[0]:+5.2f}  shift2 {both[1]:+5.2f}")
        print(f"  exclude cut funds {w:>3}d (LONG leg only)  "
              f"shift1 {lo[0]:+5.2f}  shift2 {lo[1]:+5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
