"""Zero-trial decompositions of the DEPLOYED discount signal behind the
2026-10-12 core-signal candidates. No modified signal, no book, no variant.

    python3 scripts/cef/core_signal_decomp.py               # every section
    python3 scripts/cef/core_signal_decomp.py exdates t1    # chosen sections

The write-up is results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md.

WHAT THIS IS ALLOWED TO DO, AND WHY
-----------------------------------
Each section splits the deployed signal's existing predictive content -- the
pooled slope of the cross-sectionally demeaned forward return on the
cross-sectionally demeaned z, and its rank IC -- by a characteristic known on
the signal date, or splits the forward return into segments. That is exactly
what W4 sections 2-4 did (by ex-date touch, by month, by volatility state, by
forward day; scripts/cef/w4_artifacts.py). Nothing here builds an alternative
z, scores a policy, or compares a candidate with the deployed book: each of
those is a counted trial, and the candidates note says which counter it goes
on. Fit period only (.. 2022-12-30); the 2023-01-01 holdout stays sealed.

THE THREE SECTIONS
------------------
exdates  The deployed signal in event time around distributions (W4 sections
         1 and 4a): for each signal date t, event day k = t - ex-date of the
         nearest distribution (k in -5..+10). Regular payments and year-end
         specials (D/P > 2%, W4's definition) are separate; a placebo
         calendar (every ex-date moved +10 sessions, mid-cycle for a monthly
         payer) is the negative control.
toy      The turn of year (W4 section 4c) split by tax-loss status known at t:
         in December the year-to-date total return through t; in January the
         previous calendar year's; elsewhere the year-to-date return. Losers
         (status < 0) against winners; Dec-Jan against Feb-Nov (the calendar
         control); half-months; specials excluded; season by season.
t1       The day no deployed book can earn (W4 section 2): the t+1 return split
         into the overnight gap (close t -> open t+1) and the t+1 session
         (open -> close), from the yfinance open and, as a second source, the
         CRSP opening price; and z_t split into its level (zL), the price leg
         of today's discount change (zP) and its NAV leg (zN).

STATISTICS (shared)
-------------------
zdm, Fdm: z and the forward return over closes t+1 -> t+3 (total returns),
each demeaned over the deployed set on date t. For a subset S of deployed
name-days on the phase-0 non-overlapping grid:
  slope_S = sum_S zdm*Fdm / sum_S zdm^2   (bp of 2-day return per unit z)
  contribution share = sum_S zdm*Fdm / sum_all zdm*Fdm
with a date-clustered t (per-date sums are the scores, G/(G-1)). The whole
deployed set reproduces W4's pooled slope (-6.74bp, t -2.92) and is printed
first as a regression check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import HOLDOUT_START  # noqa: E402
from scripts.cef.spec import MIN_NAMES, summary  # noqa: E402
from scripts.cef.w4_artifacts import (  # noqa: E402
    DEPLOYED_WIN, FIT_END, IC_HDR, Data, _assert_fit, _pivot, fmt_ic, fwd,
    ic_row, ic_series, nw_t,
)

PRE, POST = 5, 10                 # event window k in [-PRE, +POST]
SPECIAL_YIELD = 0.02              # W4 section 4a: D/P > 2% on the ex-date
PLACEBO_SHIFT = 10                # sessions; mid-cycle for a monthly payer
EXCL_SPECIAL = (3, 10)            # W4's middle sensitivity window [-3, +10]


# --------------------------------------------------------------------------- shared

def demeaned(D: Data):
    """zdm and Fdm on the deployed set (NaN elsewhere). ALIGNMENT: z_t uses data
    through t; F is closes t+1 -> t+3, the window a book decided at t earns."""
    F = fwd(D.r_tr, *DEPLOYED_WIN)
    ok = D.M_dep & D.z.notna() & F.notna()
    ok = ok & (ok.sum(axis=1) >= MIN_NAMES).to_numpy()[:, None]
    z = D.z.where(ok)
    f = F.where(ok)
    return z.sub(z.mean(axis=1), axis=0), f.sub(f.mean(axis=1), axis=0), ok


def subset_stats(zdm, Fdm, mask, dates, total_cov=None):
    """Pooled slope, contribution share and descriptive means on a subset."""
    z, f = zdm.reindex(dates), Fdm.reindex(dates)
    m = mask.reindex(index=dates, columns=zdm.columns, fill_value=False) & z.notna() & f.notna()
    zs, fs = z.where(m), f.where(m)
    Sxy, Sxx = (zs * fs).sum(axis=1), (zs ** 2).sum(axis=1)
    use = m.any(axis=1)
    Sxy, Sxx = Sxy[use], Sxx[use]
    G, n = int(use.sum()), int(m.sum().sum())
    out = dict(n=n, dates=G, mean_z=float(zs.stack().mean()) if n else np.nan,
               mean_F_bp=float(fs.stack().mean() * 1e4) if n else np.nan,
               cov=float(Sxy.sum()))
    if G >= 10 and Sxx.sum() > 0:
        b = Sxy.sum() / Sxx.sum()
        e = (Sxy - b * Sxx) / Sxx.sum()
        out.update(slope_bp=b * 1e4, t=b / np.sqrt(G / (G - 1) * (e ** 2).sum()))
        tm = Sxy.mean() / Sxy.std(ddof=1) * np.sqrt(G)   # t of the contribution itself
        out.update(t_contrib=tm)
    else:
        out.update(slope_bp=np.nan, t=np.nan, t_contrib=np.nan)
    if total_cov is not None:
        out["share"] = out["cov"] / total_cov
    return out


HDR = (f"{'subset':<40}{'n':>6}{'dates':>6}{'mean z':>8}{'mean F bp':>10}{'slope bp/z':>11}"
       f"{'t':>7}{'contrib':>9}{'t(c)':>7}")


def line(lab, s):
    return (f"{lab:<40}{s['n']:6d}{s['dates']:6d}{s['mean_z']:8.3f}{s['mean_F_bp']:10.2f}"
            f"{s['slope_bp']:11.2f}{s['t']:7.2f}{s.get('share', np.nan):9.3f}{s['t_contrib']:7.2f}")


def regression_check(D, zdm, Fdm, ok):
    tot = subset_stats(zdm, Fdm, ok, D.G0)
    tot["share"] = 1.0
    print(HDR)
    print(line("ALL deployed name-days (W4: -6.74, t -2.92)", tot))
    return tot


# --------------------------------------------------------------------------- ex-dates

def event_days(ex: pd.DataFrame, special: pd.DataFrame):
    """(k, kind): event day of each name-date relative to its nearest ex-date
    within [-PRE, +POST], post-event assignment preferred where two windows
    overlap; kind 1 = special, 0 = regular; NaN outside every window. Event
    days count SESSIONS of the panel index."""
    K = pd.DataFrame(np.nan, index=ex.index, columns=ex.columns)
    T = pd.DataFrame(np.nan, index=ex.index, columns=ex.columns)
    pos = np.arange(len(ex.index))
    for c in ex.columns:
        e = np.flatnonzero(ex[c].to_numpy())
        if not len(e):
            continue
        sp = special[c].to_numpy()[e]
        nxt = np.searchsorted(e, pos, side="left")            # first ex >= pos
        prv = nxt - 1                                         # last ex < pos ... unless pos is an ex
        on = (nxt < len(e)) & (e[np.minimum(nxt, len(e) - 1)] == pos)
        prv = np.where(on, nxt, prv)                          # an ex-date is k = 0 of itself
        kp = np.where(prv >= 0, pos - e[np.maximum(prv, 0)], 10 ** 9)
        nn = np.where(on, nxt + 1, nxt)
        kn = np.where(nn < len(e), pos - e[np.minimum(nn, len(e) - 1)], -10 ** 9)
        use_p = kp <= POST
        use_n = (~use_p) & (kn >= -PRE)
        k = np.where(use_p, kp, np.where(use_n, kn, np.nan))
        kind = np.where(use_p, sp[np.maximum(prv, 0)], np.where(use_n, sp[np.minimum(nn, len(e) - 1)], np.nan))
        K[c], T[c] = k, kind.astype(float)
    return K, T


def sec_exdates(D: Data):
    print("\n" + "=" * 104 + "\nA. THE DEPLOYED SIGNAL IN EVENT TIME AROUND DISTRIBUTIONS (phase-0 grid; total returns)\n"
          + "=" * 104)
    zdm, Fdm, ok = demeaned(D)
    tot = regression_check(D, zdm, Fdm, ok)
    special = (D.y_px > SPECIAL_YIELD)
    K, T = event_days(D.ex, special)
    _assert_fit(K)
    for kind, lab in ((0.0, "REGULAR distributions"), (1.0, f"SPECIALS (D/P > {SPECIAL_YIELD:.0%})")):
        print(f"\n{lab}: event day k = t - ex-date (k = 0: the signal date is the ex-date; the book "
              "decided then fills at close k+1 and earns k+2, k+3)")
        print(HDR)
        ks = range(-PRE, POST + 1) if kind == 0.0 else [None]
        if kind == 0.0:
            for k in ks:
                s = subset_stats(zdm, Fdm, ok & (K == k) & (T == kind), D.G0, tot["cov"])
                print(line(f"  k = {k:+d}", s))
        for lab2, lo, hi in (("  pre  [-5,-1]", -5, -1), ("  ex   [0]", 0, 0), ("  post [+1,+2]", 1, 2),
                             ("  post [+3,+10]", 3, 10), ("  whole window [-5,+10]", -5, 10)):
            s = subset_stats(zdm, Fdm, ok & (K >= lo) & (K <= hi) & (T == kind), D.G0, tot["cov"])
            print(line(lab2, s))
    s = subset_stats(zdm, Fdm, ok & K.isna(), D.G0, tot["cov"])
    print(line("  outside every window", s))

    # same-day abnormal return and discount change by event day (every session; descriptive)
    print("\nsame-day abnormal price TOTAL return and abnormal discount change by event day, REGULAR, every "
          "session, deployed set (abnormal = minus the deployed cross-sectional mean that day); NW t:")
    ar = D.r_tr.where(ok | D.M_dep)
    ar = ar.sub(ar.where(D.M_dep).mean(axis=1), axis=0)
    dd = D.disc.diff()
    add = dd.sub(dd.where(D.M_dep).mean(axis=1), axis=0)
    print(f"{'k':>4}{'n':>7}{'abn ret bp':>11}{'t':>7}{'abn d disc pp':>15}{'t':>7}")
    for k in range(-3, 6):
        m = D.M_dep & (K == k) & (T == 0.0)
        x = (ar.where(m).mean(axis=1) * 1e4).dropna()
        y = add.where(m).mean(axis=1).dropna()
        print(f"{k:+4d}{int(m.sum().sum()):7d}{x.mean():11.2f}{nw_t(x):7.2f}{y.mean():15.3f}{nw_t(y):7.2f}")

    # placebo: the ex calendar moved +PLACEBO_SHIFT sessions
    print(f"\nPLACEBO (negative control): every ex-date moved +{PLACEBO_SHIFT} sessions, regular kind")
    exP = D.ex.shift(PLACEBO_SHIFT, fill_value=False)
    KP, TP = event_days(exP, special.shift(PLACEBO_SHIFT, fill_value=False))
    print(HDR)
    for lab2, lo, hi in (("  placebo pre  [-5,-1]", -5, -1), ("  placebo ex   [0]", 0, 0),
                         ("  placebo post [+1,+2]", 1, 2), ("  placebo post [+3,+10]", 3, 10)):
        s = subset_stats(zdm, Fdm, ok & (KP >= lo) & (KP <= hi) & (TP == 0.0), D.G0, tot["cov"])
        print(line(lab2, s))
    # where the deployed book's TRADING happens in the cycle (descriptive): the share
    # of its turnover |H_t - H_(t-1)| decided on each event window, against the share
    # of name-days there. Turnover above 0.5% of capital per name-day only: the gross
    # ceiling rescales every held name a little each day, and that dust is not a
    # trade anyone decides.
    dH = D.H.diff().abs().reindex(index=D.idx, columns=D.U)
    real = dH.where(dH > 0.005)
    live = D.idx[D.idx >= D.H.index[D.H.abs().sum(axis=1) > 0].min()]
    tot_t = real.loc[live].sum().sum()
    print("\nthe deployed book's turnover by event window of the DECISION date (regular cycle; trades "
          "> 0.5% of capital; live sessions to 2022-12-30):")
    print(f"{'window':<22}{'share of turnover':>18}{'share of name-days':>20}")
    for lab2, lo, hi in (("pre  [-5,-1]", -5, -1), ("ex   [0]", 0, 0), ("post [+1,+2]", 1, 2),
                         ("post [+3,+10]", 3, 10)):
        m = ((K >= lo) & (K <= hi) & (T == 0.0)).loc[live]
        print(f"{lab2:<22}{real.loc[live].where(m).sum().sum() / tot_t:18.3f}{m.sum().sum() / m.size:20.3f}")

    # phase-1 replication of the windows
    print("\nphase-1 grid replication (regular): ")
    tot1 = subset_stats(zdm, Fdm, ok, D.G1)
    for lab2, lo, hi in (("  pre  [-5,-1]", -5, -1), ("  ex   [0]", 0, 0), ("  post [+1,+2]", 1, 2),
                         ("  post [+3,+10]", 3, 10)):
        s = subset_stats(zdm, Fdm, ok & (K >= lo) & (K <= hi) & (T == 0.0), D.G1, tot1["cov"])
        print(line(lab2, s))


# --------------------------------------------------------------------------- turn of year

def tax_status(D: Data) -> pd.DataFrame:
    """Tax-loss status known at close t: year-to-date total return through t in
    Feb-Dec; the previous calendar year's total return in January (the year
    whose losses were harvested). ALIGNMENT: uses returns through t only."""
    lr = np.log1p(D.r_tr)
    yr = D.idx.year
    ytd = lr.groupby(yr).cumsum()
    full = lr.groupby(yr).sum(min_count=1)           # calendar-year total (log)
    prev = pd.DataFrame(np.nan, index=D.idx, columns=D.U)
    for y in sorted(set(yr)):
        if y - 1 in full.index:
            prev.loc[yr == y] = full.loc[y - 1].to_numpy()
    jan = D.idx.month == 1
    st = ytd.copy()
    st.loc[jan] = prev.loc[jan]
    # require a reasonably complete year: >= 150 sessions of returns behind the status
    n_ytd = D.r_tr.notna().groupby(yr).cumsum()
    n_prev = D.r_tr.notna().groupby(yr).sum()
    cnt = n_ytd.copy().astype(float)
    for y in sorted(set(yr)):
        if y - 1 in n_prev.index:
            cnt.loc[(yr == y) & jan] = n_prev.loc[y - 1].to_numpy()
    st = st.where(~((D.idx.month == 12) | jan)[:, None] | (cnt >= 150))
    return st


def sec_toy(D: Data):
    print("\n" + "=" * 104 + "\nB. TURN OF YEAR BY TAX-LOSS STATUS (phase-0 grid; total returns)\n" + "=" * 104)
    zdm, Fdm, ok = demeaned(D)
    tot = regression_check(D, zdm, Fdm, ok)
    st = tax_status(D)
    _assert_fit(st)
    mon = pd.DataFrame(np.repeat(D.idx.month.to_numpy()[:, None], len(D.U), axis=1), index=D.idx, columns=D.U)
    day = pd.DataFrame(np.repeat(D.idx.day.to_numpy()[:, None], len(D.U), axis=1), index=D.idx, columns=D.U)
    toy = mon.isin([12, 1])
    loser, winner = st < 0, st >= 0
    special = (D.y_px > SPECIAL_YIELD)
    pre = special.copy()
    for k in range(1, EXCL_SPECIAL[0] + 1):
        pre = pre | special.shift(-k, fill_value=False)
    post = special.copy()
    for k in range(1, EXCL_SPECIAL[1] + 1):
        post = post | special.shift(k, fill_value=False)
    near_special = pre | post
    print("\nstatus: Dec = YTD total return through t; Jan = previous calendar year's; Feb-Nov = YTD (control)")
    print(HDR)
    rows = [("Dec-Jan, all", ok & toy), ("Dec-Jan, LOSERS (status < 0)", ok & toy & loser),
            ("Dec-Jan, winners", ok & toy & winner),
            ("Feb-Nov, all", ok & ~toy), ("Feb-Nov, losers (control)", ok & ~toy & loser),
            ("Feb-Nov, winners (control)", ok & ~toy & winner),
            (f"Dec-Jan ex specials [-{EXCL_SPECIAL[0]},+{EXCL_SPECIAL[1]}]", ok & toy & ~near_special),
            ("  ... losers", ok & toy & ~near_special & loser),
            ("  ... winners", ok & toy & ~near_special & winner),
            ("Dec 1-15", ok & (mon == 12) & (day <= 15)), ("Dec 16-31", ok & (mon == 12) & (day > 15)),
            ("Jan 1-15", ok & (mon == 1) & (day <= 15)), ("Jan 16-31", ok & (mon == 1) & (day > 15)),
            ("Dec 16-31, losers", ok & (mon == 12) & (day > 15) & loser),
            ("Jan 1-15, losers", ok & (mon == 1) & (day <= 15) & loser)]
    multi = pd.DataFrame({t: [D.grp[t] == "multi"] * len(D.idx) for t in D.U}, index=D.idx)
    rows += [("Dec-Jan, multi", ok & toy & multi), ("Dec-Jan, not multi", ok & toy & ~multi),
             ("Dec-Jan, multi ex specials", ok & toy & multi & ~near_special)]
    for lab, m in rows:
        print(line(lab, subset_stats(zdm, Fdm, m, D.G0, tot["cov"])))
    print("\n  mean status (log YTD / prior-year TR) of deployed name-days: Dec-Jan losers share "
          f"{loser.where(ok & toy).stack().mean():.3f}; Feb-Nov losers share {loser.where(ok & ~toy).stack().mean():.3f}")

    # season by season (Dec of Y and Jan of Y+1), the deployed rank IC
    F = fwd(D.r_tr, *DEPLOYED_WIN)
    ic = ic_series(D.z, F, D.M_dep, D.G0)
    seas = pd.Series(np.where(ic.index.month == 12, ic.index.year, ic.index.year - 1), index=ic.index)
    tic = ic[ic.index.month.isin([12, 1])]
    ss = seas[tic.index]
    print("\nseason by season (Dec Y + Jan Y+1), DEPLOYED rank IC on the phase-0 grid, and the share of "
          "deployed name-days that are tax-loss candidates (a season with no deployed date is absent):")
    print(f"{'season':<8}{'dates':>6}{'IC':>9}{'losers':>8}")
    seas_rows = []
    for y in sorted(set(ss)):
        x = tic[ss == y]
        m = ok & toy
        sl = loser.where(m)
        di = sl.index[(sl.index.month == 12) & (sl.index.year == y) | (sl.index.month == 1) & (sl.index.year == y + 1)]
        lshare = sl.loc[di].stack().mean()
        print(f"{y:<8}{len(x):6d}{x.mean():+9.4f}{lshare:8.3f}")
        seas_rows.append((y, x.mean(), lshare, len(x)))
    S = pd.DataFrame(seas_rows, columns=["season", "ic", "loser_share", "dates"])
    print(f"seasons {len(S)}; IC < 0 in {(S.ic < 0).sum()}; mean of season ICs {S.ic.mean():+.4f} "
          f"(t over seasons {S.ic.mean() / S.ic.std(ddof=1) * np.sqrt(len(S)):.2f}); "
          f"corr(season IC, loser share) {S.ic.corr(S.loser_share):+.2f} on {len(S)} seasons (D7: descriptive only)")
    # December volume, a W10 Part E mechanism check (all name-days of the 13, 2005-22)
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    P = P[P.ticker.isin(D.U)]
    P["date"] = pd.to_datetime(P.date)
    P = P[(P.date >= "2005-01-01") & (P.date < HOLDOUT_START)]
    P["dv"] = P.close * P.volume
    P["m"] = P.date.dt.month
    P["y"] = P.date.dt.year
    mdv = P.groupby(["ticker", "y", "m"]).dv.mean().unstack("m")
    ratio = (mdv[12] / mdv[[2, 3, 4, 5, 6, 7, 8, 9, 10, 11]].mean(axis=1)).dropna()
    ratio_d2 = (P[(P.m == 12) & (P.date.dt.day > 15)].groupby(["ticker", "y"]).dv.mean()
                / mdv[[2, 3, 4, 5, 6, 7, 8, 9, 10, 11]].mean(axis=1)).dropna()
    print(f"\nDecember dollar volume / Feb-Nov mean, per name-year, 2005-22 ({len(ratio)} name-years): median "
          f"{ratio.median():.2f}, share > 1 {(ratio > 1).mean():.2f}; second half of December median "
          f"{ratio_d2.median():.2f}")


# --------------------------------------------------------------------------- t+1

def sec_t1(D: Data):
    print("\n" + "=" * 104 + "\nC. THE t+1 DAY: overnight vs session, and z's level / price leg / NAV leg\n" + "=" * 104)
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    P = P[P.ticker.isin(D.U)]
    P["date"] = pd.to_datetime(P.date)
    pv = lambda c: P.pivot_table(index="date", columns="ticker", values=c).reindex(index=D.idx, columns=D.U)
    op_y, hi, lo, cl = pv("open"), pv("high"), pv("low"), pv("close")
    c = D.crsp()
    c = c[c.ticker.isin(D.U)]
    op_c = _pivot(c, "openprc", D.U, D.idx)
    op_c = op_c.where(op_c > 0)
    priced = cl.notna()
    TICK = 0.005                       # half a cent: the comparison tolerance (float32 panel vs CRSP)
    print("open-price quality, 2005-22, the 13 names, all panel name-days (tolerance $0.005):")
    for lab, op in (("yfinance open", op_y), ("CRSP openprc", op_c)):
        good = op.notna() & (op > 0)
        print(f"  {lab:<14} present on {(good & priced).sum().sum() / priced.sum().sum():.1%}; outside "
              f"yfinance [low, high] {((op < lo - TICK) | (op > hi + TICK))[good].sum().sum() / good.sum().sum():.2%}; "
              f"within $0.005 of the previous close {((op - cl.shift(1)).abs() <= TICK)[good].sum().sum() / good.sum().sum():.1%}")
    both = op_y.notna() & op_c.notna() & (op_y > 0)
    agree = ((op_y - op_c).abs() <= 0.005) & both
    print(f"  yfinance open = CRSP openprc within $0.005 on {agree.sum().sum() / both.sum().sum():.1%} of "
          f"{int(both.sum().sum())} common name-days")

    D_amt = D.dist.reindex(index=D.idx, columns=D.U)
    Dz = D_amt.fillna(0.0)                                    # no distribution on a date IS zero cash
    out = {}
    for lab, op in (("yfinance open", op_y), ("CRSP openprc", op_c)):
        ok_o = op.notna() & (op > 0) & cl.notna() & cl.shift(1).notna()
        # log split, exact: log((C_t + D_t)/C_{t-1}) = log((O_t + D_t)/C_{t-1}) + log((C_t + D_t)/(O_t + D_t))
        on = np.log((op + Dz) / cl.shift(1)).where(ok_o)
        se = np.log((cl + Dz) / (op + Dz)).where(ok_o)
        full = np.log((cl + Dz) / cl.shift(1)).where(ok_o)
        chk = (on + se - full).abs().max().max()
        if chk > 1e-12:
            raise AssertionError(f"overnight + session != day ({chk})")
        out[lab] = (on, se, full)
    print("\nIC of z_t (DEPLOYED) by segment of the forward path; every session, NW t (W4 2a style), common "
          "sample where both opens exist. Total returns (distribution added back at the open on ex-dates):")
    on_y, se_y, full_y = out["yfinance open"]
    on_c, se_c, full_c = out["CRSP openprc"]
    common = D.M_dep & on_y.shift(-1).notna() & on_c.shift(-1).notna() & D.r_tr.shift(-2).notna()
    print("  " + IC_HDR)
    segs = [("day t+1, close-to-close (W4: -0.042)", full_y.shift(-1)),
            ("t+1 OVERNIGHT, yfinance open", on_y.shift(-1)), ("t+1 SESSION, yfinance open", se_y.shift(-1)),
            ("t+1 OVERNIGHT, CRSP open", on_c.shift(-1)), ("t+1 SESSION, CRSP open", se_c.shift(-1)),
            ("day t+2 (deployed earns it)", np.log1p(D.r_tr.shift(-2))),
            ("t+2 OVERNIGHT, yfinance open", on_y.shift(-2)), ("t+2 SESSION, yfinance open", se_y.shift(-2))]
    for lab, S in segs:
        print("  " + fmt_ic(lab, ic_series(D.z, S, common, D.idx)))
    print("  two-day windows, phase-0 grid, same common sample:")
    open_win = se_y.shift(-1) + np.log1p(D.r_tr.shift(-2))      # open t+1 -> close t+2
    dep_win = np.log1p(fwd(D.r_tr, *DEPLOYED_WIN))
    for lab, S in (("[close t+1 -> close t+3] DEPLOYED", dep_win),
                   ("[open t+1 -> close t+2] yfinance open", open_win),
                   ("[open t+1 -> close t+2] CRSP open", se_c.shift(-1) + np.log1p(D.r_tr.shift(-2)))):
        print("  " + fmt_ic(lab, ic_series(D.z, S, common & S.notna(), D.G0)))

    # ---- the TRANSACTABLE open: NYSE opening-auction print (Alpaca SIP), 2016-22
    sec_t1_auction(D, cl, op_y, Dz, dep_win, TICK)

    # z = level + price leg + NAV leg
    print("\nz_t split: zP = 100 (P/N)_(t-1) log(1 + r_price,TR,t) / sd_t (today's price move in z units), "
          "zN = -100 (P/N)_(t-1) log(1 + r_NAV,TR,t) / sd_t (today's NAV move), zL = z - zP - zN (the level "
          "carried from t-1, plus the window's drift). Fama-MacBeth, DEPLOYED set, bp per unit:")
    pn = (D.px / D.nav).shift(1)
    zP = 100 * pn * np.log1p(D.r_tr) / D.sd
    zN = -100 * pn * np.log1p(D.r_nav_tr) / D.sd
    zL = D.z - zP - zN
    _assert_fit(zP, zN, zL)
    M = D.M_dep & zP.notna() & zN.notna() & zL.notna()
    st = lambda X: X.where(M).stack()
    print(f"  sd: zL {st(zL).std():.3f}, zP {st(zP).std():.3f}, zN {st(zN).std():.3f}, z {st(D.z).std():.3f}; "
          f"corr(zL, z_(t-1)) {np.corrcoef(st(zL), st(D.z.shift(1)).reindex(st(zL).index).fillna(0))[0, 1]:+.3f}; "
          f"corr(zP, zN) {np.corrcoef(st(zP), st(zN).reindex(st(zP).index))[0, 1]:+.3f}")

    def fm3(F, dates):
        rows = []
        for d in dates:
            m = M.loc[d] & F.loc[d].notna()
            if m.sum() < MIN_NAMES:
                continue
            y = F.loc[d][m].to_numpy()
            X = np.c_[np.ones(m.sum()), zL.loc[d][m], zP.loc[d][m], zN.loc[d][m]]
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
            rows.append(b[1:])
        return pd.DataFrame(rows, columns=["zL", "zP", "zN"]) * 1e4

    for lab, F, dates, nw in (("day t+1 (unearned), every session", np.log1p(D.r_tr.shift(-1)), D.idx, True),
                              ("t+1 OVERNIGHT (yfinance open), every session", on_y.shift(-1), D.idx, True),
                              ("t+1 SESSION (yfinance open), every session", se_y.shift(-1), D.idx, True),
                              ("[t+2,t+3] DEPLOYED, phase-0 grid", dep_win, D.G0, False)):
        B = fm3(F, dates)
        tt = (lambda s: nw_t(s)) if nw else (lambda s: s.mean() / s.std(ddof=1) * np.sqrt(len(s)))
        print(f"  {lab:<46} dates {len(B):5d}   zL {B.zL.mean():+7.2f} (t {tt(B.zL):5.2f})   "
              f"zP {B.zP.mean():+7.2f} (t {tt(B.zP):5.2f})   zN {B.zN.mean():+7.2f} (t {tt(B.zN):5.2f})")


def sec_t1_auction(D: Data, cl, op_y, Dz, dep_win, TICK):
    """The t+1 split on the NYSE OPENING-AUCTION print, the price an opening
    order would actually get. W4 used the closing-auction print the same way.
    Rule, stated: primary listing (exchange N); condition Q (official open)
    where NYSE published one, else O (opening trade); raises if the two
    disagree by more than $0.005 where both exist. A name-day with no NYSE
    opening print is a recorded gap, never filled. The leadlag death
    (docs/RESEARCH_STATE.md) was an effect measured on a price nobody could
    trade; this block exists so that this one is not."""
    from scripts.cef.w4_artifacts import CACHE, _need
    a = pd.read_parquet(_need(CACHE / "alpaca_opening_prints_2016_2022.parquet",
                              "scripts/data/fetch_alpaca_auction_history.py --side open"))
    _assert_fit(a.set_index("date"))
    n = a[a.exchange == "N"]
    piv = n.pivot_table(index=["date", "ticker"], columns="condition", values="price", aggfunc="first")
    if {"O", "Q"} <= set(piv.columns):
        both = piv["O"].notna() & piv["Q"].notna()
        dis = ((piv["O"] - piv["Q"]).abs() > TICK) & both
        print(f"\nNYSE opening prints: O and Q both exist on {int(both.sum())} name-days; they differ by more "
              f"than $0.005 on {int(dis.sum())}")
        if dis.mean() > 0.01:
            raise ValueError("NYSE condition-O and condition-Q opening prints disagree on more than 1% of "
                             "name-days; decide which is the auction price before using either")
        auc = piv["Q"].combine_first(piv["O"])
    else:
        auc = piv[[c for c in ("Q", "O") if c in piv.columns][0]]
    oa = auc.unstack().reindex(index=D.idx, columns=D.U)
    win = D.idx >= pd.Timestamp("2016-01-04")
    have = oa.notna() & cl.notna()
    have.loc[~win] = False
    priced = cl.notna() & pd.DataFrame(np.repeat(win[:, None], len(D.U), axis=1), index=D.idx, columns=D.U)
    print(f"  a NYSE opening print exists on {have.sum().sum() / priced.sum().sum():.1%} of panel name-days "
          f"2016-22; it equals the yfinance open within $0.005 on "
          f"{(((oa - op_y).abs() <= TICK) & have).sum().sum() / have.sum().sum():.1%} of them, and the previous "
          f"close within $0.005 on {(((oa - cl.shift(1)).abs() <= TICK) & have).sum().sum() / have.sum().sum():.1%}")
    ok_o = have & cl.shift(1).notna()
    on = np.log((oa + Dz) / cl.shift(1)).where(ok_o)
    se = np.log((cl + Dz) / (oa + Dz)).where(ok_o)
    on_y = np.log((op_y + Dz) / cl.shift(1))
    se_y = np.log((cl + Dz) / (op_y + Dz))
    common = (D.M_dep & on.shift(-1).notna() & se.shift(-1).notna() & D.r_tr.shift(-2).notna()
              & on_y.shift(-1).notna())
    idx16 = D.idx[win]
    G016 = D.G0[D.G0 >= pd.Timestamp("2016-01-04")]
    print("  IC of z_t (DEPLOYED) on the common 2016-22 sample where the t+1 NYSE opening print exists:")
    print("  " + IC_HDR)
    for lab, S in (("day t+1 close-to-close", (on + se).shift(-1)),
                   ("t+1 OVERNIGHT to the opening AUCTION", on.shift(-1)),
                   ("t+1 SESSION from the opening AUCTION", se.shift(-1)),
                   ("t+1 OVERNIGHT, yfinance open (same sample)", on_y.shift(-1)),
                   ("t+1 SESSION, yfinance open (same sample)", se_y.shift(-1))):
        print("  " + fmt_ic(lab, ic_series(D.z, S, common, idx16)))
    print("  two-day windows, phase-0 grid, same sample:")
    for lab, S in (("[close t+1 -> close t+3] DEPLOYED", dep_win),
                   ("[opening AUCTION t+1 -> close t+2]", se.shift(-1) + np.log1p(D.r_tr.shift(-2))),
                   ("[yfinance open t+1 -> close t+2]", se_y.shift(-1) + np.log1p(D.r_tr.shift(-2)))):
        print("  " + fmt_ic(lab, ic_series(D.z, S, common & S.notna(), G016)))
    # the stale-open check: does the session IC survive where the auction open MOVED off the prior close?
    moved = ((oa - cl.shift(1)).abs() > TICK).shift(-1, fill_value=False)
    print("  the stale-open check (a name-day whose t+1 opening print sits within $0.005 of close t carries "
          "the whole day in its 'session'):")
    for lab, M in (("t+1 SESSION, auction open MOVED off close t", common & moved),
                   ("t+1 SESSION, auction open AT close t", common & ~moved)):
        print("  " + fmt_ic(lab, ic_series(D.z, se.shift(-1), M, idx16, min_n=4)))
    print("  (rows with the open at the prior close need >= 4 names, not min_names; read them as a split, "
          "not a baseline)")
    auction_depth(D)


def auction_depth(D: Data):
    """Median NYSE auction print in dollars, open vs close, per name (2016-22),
    beside the deployed book's median order at the spec's capital. The `s`
    field is documented only as "Auction trade size" (docs.alpaca.markets
    stockauctions, fetched 2026-10-12): whether it is the whole cross or one
    print of it is [U]. Read the ratio, not the level."""
    from scripts.cef.w4_artifacts import CACHE, _need
    from scripts.cef.spec import frozen as spec_frozen
    import json as _json
    cap = float(_json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())["capital_usd"])
    rows = {}
    for side, pref in (("opening", ("Q", "O")), ("closing", ("M", "6"))):
        a = pd.read_parquet(_need(CACHE / f"alpaca_{side}_prints_sized_2016_2022.parquet",
                                  f"scripts/data/fetch_alpaca_auction_history.py --side {side[:-3] if side == 'opening' else 'close'} --sizes"))
        _assert_fit(a.set_index("date"))
        n = a[a.exchange == "N"]
        pv = n.pivot_table(index=["date", "ticker"], columns="condition", values=["price", "size"], aggfunc="first")
        price = pv["price"][pref[0]].combine_first(pv["price"][pref[1]])
        size = pv["size"][pref[0]].combine_first(pv["size"][pref[1]])
        rows[side] = (price * size).groupby(level="ticker").median()
    # deployed orders: |dH| x capital on decision dates, 2016-22. The plain median is
    # dust (the gross ceiling rescales every held name a little each day), so the
    # statistic is the DOLLAR-WEIGHTED median: half of the traded notional is in
    # orders at least this large.
    dH = D.H.diff().abs().loc["2016-01-04":FIT_END] * cap

    def wmed(x):
        x = np.sort(x[x > 0])
        if not len(x):
            return np.nan
        c = np.cumsum(x)
        return float(x[np.searchsorted(c, c[-1] / 2)])
    orders = pd.Series({t: wmed(dH[t].to_numpy()) for t in D.U})
    T_ = pd.DataFrame({"open $ med": rows["opening"], "close $ med": rows["closing"],
                       "order $ wmed": orders}).reindex(D.U)
    T_["open/close"] = T_["open $ med"] / T_["close $ med"]
    T_["order/open"] = T_["order $ wmed"] / T_["open $ med"]
    T_["order/close"] = T_["order $ wmed"] / T_["close $ med"]
    print(f"\n  auction depth, NYSE prints 2016-22 (median dollars per print; `s` semantics [U]); deployed "
          f"dollar-weighted median order at capital ${cap:,.0f} (the spec's), 2016-22:")
    print(T_.round(2).to_string())
    print(f"  median across names: open/close {T_['open/close'].median():.1f}x; order/open "
          f"{T_['order/open'].median():.2f}x; order/close {T_['order/close'].median():.2f}x")


SECTIONS = {"exdates": sec_exdates, "toy": sec_toy, "t1": sec_t1}


def main(argv):
    want = argv or list(SECTIONS)
    bad = [w for w in want if w not in SECTIONS]
    if bad:
        raise SystemExit(f"unknown section(s) {bad}; choose from {list(SECTIONS)}")
    print(summary())
    print(f"core-signal decompositions -- FIT PERIOD ONLY (.. {FIT_END}); 2023+ sealed. Run "
          f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Zero trials.")
    D = Data()
    for w in want:
        SECTIONS[w](D)


if __name__ == "__main__":
    main(sys.argv[1:])
