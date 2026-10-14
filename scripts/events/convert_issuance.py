"""Convertible-issuance event study: the issuer's stock around a new 144A convert.

    export QUANTT_ENV_FILE=<absolute path to the env file holding the R2 keys>
    python3 scripts/events/convert_issuance.py            # uses the R2 pulls cached under
                                                           # results/events/_cache_convert/
    python3 scripts/events/convert_issuance.py --refresh  # re-pull from R2

WHAT THIS RE-RUNS (plan item 0.9, gate G3)
------------------------------------------
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.1 row 4: "755 events 2011–22:
[-1,0] -4.41% against -0.64% for straight-debt issuers. Days +2..+5 +0.54%
(t 2.6) against -0.17%. That nets about +44/+24/-6bp on the 5/15/30 grid."
Those figures came from a desk agent's scratch script of 2026-10-09, now
deleted. Its code survives in the session transcript. This file rebuilds that
method step for step (spec "A", the reproduction) and then adds what the
reproduction lacked (spec "B", and the clustered statistics).

THE MECHANISM, AND WHO IS ON THE OTHER SIDE
-------------------------------------------
Convertible arbitrageurs buy most of a new convert and short the issuer's stock
to hedge its delta, mostly around pricing (Duca, Dutordoir, Veld & Verwijmeren
2012; Choi, Getmansky & Tookes 2009; docs/REFERENCES.md §12d). If that selling
pushes the price below value, part of the drop should reverse once the hedge is
done. The buyer of that reversal is paid by the arbitrageur's need for
immediacy.

THE METHOD (the agent's, kept so the figures are comparable)
------------------------------------------------------------
1. Universe: TRACE master file (`trace_enhanced.camasterfile`) CUSIPs with
   `cnvrb_fl='Y'`, `sub_prdct_type='CORP'`, ever flagged 144A. Most
   convertible-flagged CUSIPs are bank structured notes; the 144A subset is
   mostly real corporate converts (the agent spot-checked 2021).
2. Day 0: the CUSIP's first trade in the 144A trade file
   (`trace_btds144a_enhanced`, trade status T or R). New issues only: day 0
   must fall within 10 calendar days of the master file's first set-up date.
   Day 0 in 2011-01-01..2022-10-31.
3. Issuer: bond CUSIP[:6] = CRSP `stocknames.ncusip[:6]`, common shares (shrcd
   10/11), with a name record that covers day 0. One event per (permno, day 0);
   then an event within 7 calendar days of the same permno's previous event is
   dropped (multi-tranche deals).
4. Abnormal return: CRSP daily `ret` minus SPY's (permno 84398). Window sums of
   daily abnormal returns, in trading days around the first CRSP day on or after
   day 0. An event needs every window complete, with no missing return.
5. Negative control (H12), named by the agent BEFORE it ran: the same pipeline on
   144A NON-convertible corporate bonds (`cnvrb_fl='N'`). Straight debt draws
   no delta hedging, so it should show no hedging pressure.

WHAT IS ADDED HERE
------------------
* **Spec B, one event per issuer-day.** In spec A, one bond can map to several
  share classes of one issuer (Liberty's tracking stocks, dual-class shares),
  and each counts as an event. Spec B averages the share classes into one event
  per (CUSIP6, day 0). Spec A is the reproduction; spec B is the correction.
* **Clustered standard errors.** Issuance clusters in time (2020-21). The plain
  cross-sectional t treats every event as independent. Reported beside it:
  - t clustered by event date;
  - t clustered by calendar week of day 0. Events in one week share most of their
    window's return days, so this is the honest cluster for 4-day windows;
  - a calendar-time portfolio (equal weight across events in their window each
    day), plain and Newey-West(4) t.
  **Declared before the run (G3):** the gate statistic is the WEEK-clustered t
  of the shift(2) window [+2,+5] in spec A, with spec B beside it.
* **Convert minus control**, with week-clustered SE from a pooled regression.
* **Eras (H5)** 2010-14, 2015-19, 2020-22. The 2023-26 era is the sealed time
  holdout: this script reads no return on or after 2023-01-01 and asserts it.
* **Cost grid (H3).** The trade is long day +1 MOC to day +5 MOC: one round
  trip per event, so net = gross - 2 x one-way cost, at 5/15/30bp. Borrow: none
  (long only). Gross is the headline.

THE WINDOWS HAVE ALREADY BEEN LOOKED AT
---------------------------------------
[+2,+5] is the house shift(2) convention (decide at day 0's close, fill MOC at
day +1, earn from day +2) applied to the agent's windows. It was first computed
on 2026-10-09 on 2011-22, so 2011-22 is NOT out of sample for it. The 2023-24
CRSP years stay unread here.

ZERO TRIALS. A descriptive reproduction: no counter moves, nothing is chosen.

ENVIRONMENT. `compute.use_numexpr` is turned off below and the window sums are
done in numpy, because broadcast arithmetic on large frames is wrong on the
laptop's numexpr (`scripts/events/numexpr_fault.py`). That fault, not the
agent's code, produced the agent's first-run denormals.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Broadcast arithmetic on frames over 1e6 cells is wrong on this laptop's
# numexpr (scripts/events/numexpr_fault.py). Off before any frame is built.
pd.set_option("compute.use_numexpr", False)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CACHE = REPO / "results" / "events" / "_cache_convert"          # gitignored (results/**/_cache_*)
OUT_EVENTS = REPO / "results" / "events" / "convert_issuance_events.csv"

D0_START, D0_END = pd.Timestamp("2011-01-01"), pd.Timestamp("2022-10-31")
RET_START, RET_END = "2010-09-01", "2022-12-30"
HOLDOUT_START = pd.Timestamp("2023-01-01")      # H13: nothing on or after this date is read
SPY_PERMNO = 84398
NEW_ISSUE_DAYS = 10
DEDUP_DAYS = 7
WINDOWS = {                                     # trading days relative to day 0
    "pre[-5,-2]": (-5, -2),
    "evt[-1,0]": (-1, 0),
    "post[+1,+5]": (1, 5),
    "post[+1,+20]": (1, 20),
    "post[+1,+60]": (1, 60),
    "shift2[+2,+5]": (2, 5),
    "shift2[+2,+20]": (2, 20),
}
G3_WINDOW = "shift2[+2,+5]"
COST_GRID_BP = (5, 15, 30)
ERAS = [("2010-14", 2010, 2014), ("2015-19", 2015, 2019), ("2020-22", 2020, 2022)]
AGENT_SPLIT = [("2011-16", 2011, 2016), ("2017-22", 2017, 2022)]


# ----------------------------------------------------------------- R2 pulls

def _con():
    from src.data import r2
    return r2, r2.connect()


def _cached(name: str, refresh: bool, build):
    """Parquet cache of an R2 pull. A missing cache is rebuilt, never guessed."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{name}.parquet"
    if p.exists() and not refresh:
        return pd.read_parquet(p)
    df = build()
    df.to_parquet(p, index=False)
    return df


def pull_universe(flag: str, refresh: bool) -> pd.DataFrame:
    """CUSIPs from the TRACE master with cnvrb_fl=flag, CORP, ever 144A."""
    if flag not in ("Y", "N"):
        raise ValueError(flag)

    def build():
        r2, con = _con()
        p = r2.r2_path("trace_enhanced", "camasterfile")
        return r2.q(con, f"""
            SELECT cusip_id, MIN(stdt) AS first_dt,
                   MAX(CASE WHEN ind_144a='Y' THEN 1 ELSE 0 END) AS ever144a
            FROM read_parquet('{p}')
            WHERE cnvrb_fl='{flag}' AND sub_prdct_type='CORP' AND cusip_id IS NOT NULL
            GROUP BY cusip_id
            HAVING MAX(CASE WHEN ind_144a='Y' THEN 1 ELSE 0 END) = 1""")
    return _cached(f"universe_{flag}", refresh, build)


def pull_first_trades(flag: str, universe: pd.DataFrame, refresh: bool) -> pd.DataFrame:
    """First 144A trade date per CUSIP (trade status T or R)."""
    def build():
        r2, con = _con()
        p = r2.r2_path("trace_enhanced", "trace_btds144a_enhanced")
        con.register("u", universe[["cusip_id"]])
        return r2.q(con, f"""
            SELECT x.cusip_id, MIN(x.trd_exctn_dt) AS d0
            FROM read_parquet('{p}') x JOIN u USING (cusip_id)
            WHERE x.trc_st IN ('T','R') GROUP BY 1""")
    return _cached(f"first_trade_{flag}", refresh, build)


def pull_names(refresh: bool) -> pd.DataFrame:
    def build():
        r2, con = _con()
        p = r2.r2_path("crsp_a_stock", "stocknames")
        return r2.q(con, f"""
            SELECT permno, namedt, nameenddt, ncusip, shrcd, ticker, comnam
            FROM read_parquet('{p}')
            WHERE shrcd IN (10,11) AND nameenddt >= DATE '2010-06-01'""")
    return _cached("crsp_names", refresh, build)


def pull_returns(permnos, refresh: bool) -> pd.DataFrame:
    """CRSP daily ret, RET_START..RET_END (pre-holdout), NULLs excluded in SQL.
    The permnos asked for are cached beside the returns, so a cache built for a
    different event set is rebuilt rather than silently reused."""
    want = pd.DataFrame({"permno": sorted(set(int(x) for x in permnos) | {SPY_PERMNO})})
    req = CACHE / "crsp_returns_request.parquet"
    if not refresh and req.exists():
        refresh = not pd.read_parquet(req)["permno"].equals(want["permno"])

    def build():
        r2, con = _con()
        p = r2.r2_path("crsp_a_stock", "dsf")
        con.register("pp", want)
        return r2.q(con, f"""
            SELECT d.permno, d.date, CAST(d.ret AS DOUBLE) AS ret
            FROM read_parquet('{p}') d JOIN pp USING (permno)
            WHERE d.date BETWEEN DATE '{RET_START}' AND DATE '{RET_END}' AND d.ret IS NOT NULL""")
    df = _cached("crsp_returns", refresh, build)
    want.to_parquet(req, index=False)
    return df


def check_spy(refresh: bool) -> None:
    """Permno 84398 must be SPY over the window, or the benchmark is wrong."""
    def build():
        r2, con = _con()
        p = r2.r2_path("crsp_a_stock", "dsenames")
        return r2.q(con, f"SELECT permno, namedt, nameendt, ticker, comnam FROM read_parquet('{p}') WHERE permno={SPY_PERMNO}")
    n = _cached("spy_names", refresh, build)
    n = n[(pd.to_datetime(n.nameendt) >= pd.Timestamp(RET_START)) & (pd.to_datetime(n.namedt) <= pd.Timestamp(RET_END))]
    if n.empty or set(n.ticker) != {"SPY"}:
        raise RuntimeError(f"permno {SPY_PERMNO} is not SPY over {RET_START}..{RET_END}: {n.to_dict('records')}")


# ------------------------------------------------------------ event table

def build_events(flag: str, refresh: bool, *, d0_start: pd.Timestamp = D0_START,
                 d0_end: pd.Timestamp = D0_END) -> pd.DataFrame:
    """Matched events (one row per permno and day 0), before windows.

    `d0_start` / `d0_end` (added 2026-10-13 for the E2 pre-registration's
    zero-trial feasibility, `scripts/events/e2_feasibility.py`) default to this
    study's own range, so `main()` is unchanged. A wider range is for COUNTING
    events (dates and identities only): this function reads no return, and the
    return reader below still refuses anything on or after 2023-01-01."""
    uni = pull_universe(flag, refresh)
    ft = pull_first_trades(flag, uni, refresh)
    ft = ft.merge(uni[["cusip_id", "first_dt"]], on="cusip_id", how="inner")
    ft["d0"] = pd.to_datetime(ft["d0"])
    ft["first_dt"] = pd.to_datetime(ft["first_dt"])
    ft = ft[(ft.d0 - ft.first_dt).dt.days.abs() <= NEW_ISSUE_DAYS]
    ft = ft[(ft.d0 >= d0_start) & (ft.d0 <= d0_end)].copy()
    ft["c6"] = ft["cusip_id"].str[:6]
    n_cusips = len(ft)
    names = pull_names(refresh).copy()
    names["c6"] = names["ncusip"].str[:6]
    names["namedt"] = pd.to_datetime(names["namedt"])
    names["nameenddt"] = pd.to_datetime(names["nameenddt"])
    m = ft.merge(names, on="c6", how="inner")
    m = m[(m.d0 >= m.namedt) & (m.d0 <= m.nameenddt)]
    # The agent's order of operations, kept exactly: first CUSIP per (permno, d0),
    # then drop an event within DEDUP_DAYS of the same permno's previous one.
    m = m.sort_values(["d0", "cusip_id"], kind="mergesort").drop_duplicates(["permno", "d0"])
    m = m.sort_values(["permno", "d0"], kind="mergesort")
    gap = m.groupby("permno")["d0"].diff().dt.days
    m = m[gap.isna() | (gap > DEDUP_DAYS)].copy()
    m.attrs["n_cusips"] = n_cusips
    return m


def add_windows(m: pd.DataFrame, ret: pd.DataFrame) -> pd.DataFrame:
    """Window sums of (stock ret - SPY ret), in numpy. An event needs every
    window complete. Day 0's index is the first CRSP trading day on or after d0."""
    ret = ret.copy()
    ret["date"] = pd.to_datetime(ret["date"])
    if ret["date"].max() >= HOLDOUT_START:
        raise RuntimeError("a return on or after 2023-01-01 was read: the time holdout is sealed")
    days = np.sort(ret["date"].unique())
    pos = {p: g for p, g in ret.groupby("permno")}
    spy = pos[SPY_PERMNO].set_index("date")["ret"].reindex(days).to_numpy(dtype=float)
    if np.isnan(spy).any():
        raise RuntimeError("SPY has a missing return inside the window span")
    lo_all = min(lo for lo, _ in WINDOWS.values())
    hi_all = max(hi for _, hi in WINDOWS.values())
    rows = []
    for e in m.itertuples(index=False):
        i = int(np.searchsorted(days, np.datetime64(e.d0), side="left"))
        if i + lo_all < 0 or i + hi_all >= len(days) or e.permno not in pos:
            continue
        r = pos[e.permno].set_index("date")["ret"].reindex(days[i + lo_all:i + hi_all + 1]).to_numpy(dtype=float)
        ar = r - spy[i + lo_all:i + hi_all + 1]
        rec = {"permno": int(e.permno), "c6": e.c6, "cusip_id": e.cusip_id, "ticker": e.ticker,
               "d0": e.d0, "day0_crsp": pd.Timestamp(days[i])}
        ok = True
        for k, (lo, hi) in WINDOWS.items():
            seg = ar[lo - lo_all:hi - lo_all + 1]
            if np.isnan(seg).any():
                ok = False
                break
            rec[k] = float(seg.sum())
        if ok:
            rows.append(rec)
    E = pd.DataFrame(rows)
    vals = E[list(WINDOWS)].to_numpy()
    tiny = (np.abs(vals) < 1e-12) & (vals != 0)
    if tiny.any():
        raise RuntimeError(f"{int(tiny.sum())} denormal-like window sums: the numexpr fault is back")
    return E


def collapse_issuer(E: pd.DataFrame) -> pd.DataFrame:
    """Spec B: one event per (CUSIP6, day 0), share classes averaged."""
    g = E.groupby(["c6", "d0"], as_index=False)
    out = g[list(WINDOWS)].mean()
    out["n_classes"] = g.size()["size"].to_numpy()
    out["permno"] = g["permno"].first()["permno"].to_numpy()
    return out


# ------------------------------------------------------------- statistics

def cluster_t(x: np.ndarray, groups) -> tuple[float, int]:
    """t of the mean with cluster-robust SE (CR1): var = G/(G-1) * sum_g (sum_i e_i)^2 / N^2."""
    x = np.asarray(x, dtype=float)
    e = x - x.mean()
    s = pd.Series(e).groupby(np.asarray(groups)).sum().to_numpy()
    G, N = len(s), len(x)
    if G < 2:
        raise ValueError("fewer than two clusters")
    var = G / (G - 1) * (s ** 2).sum() / N ** 2
    return x.mean() / np.sqrt(var), G


def nw_t(y: np.ndarray, lags: int) -> float:
    y = np.asarray(y, dtype=float)
    e = y - y.mean()
    n = len(y)
    s = (e @ e) / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return y.mean() / np.sqrt(s / n)


def calendar_time(E: pd.DataFrame, ret: pd.DataFrame, window: tuple[int, int]) -> dict:
    """Equal-weight portfolio of every event inside [lo, hi] on each day."""
    ret = ret.copy()
    ret["date"] = pd.to_datetime(ret["date"])
    days = np.sort(ret["date"].unique())
    spy = ret[ret.permno == SPY_PERMNO].set_index("date")["ret"].reindex(days).to_numpy(dtype=float)
    pos = {p: g.set_index("date")["ret"].reindex(days).to_numpy(dtype=float) for p, g in ret.groupby("permno")}
    lo, hi = window
    acc = np.zeros(len(days))
    cnt = np.zeros(len(days))
    for e in E.itertuples(index=False):
        i = int(np.searchsorted(days, np.datetime64(e.d0), side="left"))
        sl = slice(i + lo, i + hi + 1)
        ar = pos[e.permno][sl] - spy[sl]
        acc[sl] += ar
        cnt[sl] += 1
    held = cnt > 0
    y = acc[held] / cnt[held]
    return {"days": int(held.sum()), "mean_bp": 1e4 * y.mean(), "t": y.mean() / (y.std(ddof=1) / np.sqrt(len(y))),
            "t_nw4": nw_t(y, 4), "per_event_equiv_pct": 100 * y.mean() * (hi - lo + 1)}


BETA_EST = (-260, -11)        # estimation window, trading days, strictly before the event
BETA_MIN_OBS = 120


def beta_adjusted(E: pd.DataFrame, ret: pd.DataFrame, window: tuple[int, int]) -> pd.DataFrame:
    """Robustness, declared with the gate and not the gate itself: the window sum of
    r - beta * SPY, beta from OLS on days [-260, -11] (all before day -5, so the
    pre-issue run-up and the event are outside it; H7). No intercept: a fitted
    alpha would carry the pre-issue run-up into the abnormal return. An event
    with fewer than 120 estimation days (early 2011: CRSP is read from
    2010-09-01) is left out and counted, never filled."""
    ret = ret.copy()
    ret["date"] = pd.to_datetime(ret["date"])
    days = np.sort(ret["date"].unique())
    spy = ret[ret.permno == SPY_PERMNO].set_index("date")["ret"].reindex(days).to_numpy(dtype=float)
    pos = {p: g.set_index("date")["ret"].reindex(days).to_numpy(dtype=float) for p, g in ret.groupby("permno")}
    lo, hi = window
    a, b = BETA_EST
    rows = []
    for e in E.itertuples(index=False):
        i = int(np.searchsorted(days, np.datetime64(e.d0), side="left"))
        if i + a < 0:
            continue
        r_est, m_est = pos[e.permno][i + a:i + b + 1], spy[i + a:i + b + 1]
        ok = ~np.isnan(r_est)
        if ok.sum() < BETA_MIN_OBS:
            continue
        beta = float(np.polyfit(m_est[ok], r_est[ok], 1)[0])
        sl = slice(i + lo, i + hi + 1)
        rows.append({"d0": e.d0, "beta": beta, "ar_beta": float(np.sum(pos[e.permno][sl] - beta * spy[sl])),
                     "ar_mkt": float(np.sum(pos[e.permno][sl] - spy[sl]))})
    return pd.DataFrame(rows)


def summarise(E: pd.DataFrame, label: str) -> pd.DataFrame:
    wk = E["d0"].dt.to_period("W-FRI").astype(str)
    out = []
    for k in WINDOWS:
        x = E[k].to_numpy()
        t_plain = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
        t_date, g_date = cluster_t(x, E["d0"].dt.strftime("%Y-%m-%d"))
        t_week, g_week = cluster_t(x, wk)
        out.append({"spec": label, "window": k, "n": len(x), "mean_pct": 100 * x.mean(),
                    "median_pct": 100 * np.median(x), "t_plain": t_plain, "t_cl_date": t_date,
                    "clusters_date": g_date, "t_cl_week": t_week, "clusters_week": g_week})
    return pd.DataFrame(out)


def diff_test(Ec: pd.DataFrame, Es: pd.DataFrame, k: str) -> dict:
    """Convert minus control mean, SE clustered by calendar week across both samples."""
    y = np.concatenate([Ec[k].to_numpy(), Es[k].to_numpy()])
    d = np.concatenate([np.ones(len(Ec)), np.zeros(len(Es))])
    g = pd.concat([Ec["d0"], Es["d0"]]).dt.to_period("W-FRI").astype(str).to_numpy()
    X = np.column_stack([np.ones_like(d), d])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    meat = np.zeros((2, 2))
    for gg in np.unique(g):
        s = X[g == gg].T @ u[g == gg]
        meat += np.outer(s, s)
    G, N = len(np.unique(g)), len(y)
    V = XtX_inv @ meat @ XtX_inv * G / (G - 1) * (N - 1) / (N - 2)
    return {"diff_pct": 100 * b[1], "t_cl_week": b[1] / np.sqrt(V[1, 1]), "clusters": G}


# ------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="re-pull every R2 input")
    args = ap.parse_args(argv)
    pd.set_option("display.width", 200)

    check_spy(args.refresh)
    mc = build_events("Y", args.refresh)
    ms = build_events("N", args.refresh)
    ret = pull_returns(pd.concat([mc.permno, ms.permno]).unique(), args.refresh)
    print(f"CRSP returns read: {pd.to_datetime(ret.date).min().date()} .. {pd.to_datetime(ret.date).max().date()} "
          f"(R2 dsf ends 2024-12-31; nothing on or after {HOLDOUT_START.date()} is read)")
    out = {}
    for flag, m, lab in (("Y", mc, "convert"), ("N", ms, "straight-debt control")):
        E = add_windows(m, ret)
        out[flag] = E
        print(f"\n== {lab}: new 144A CUSIPs with day 0 in {D0_START.date()}..{D0_END.date()}: {m.attrs['n_cusips']}; "
              f"matched events {len(m)} ({m.permno.nunique()} permnos); complete windows {len(E)}")
    Ec, Es = out["Y"], out["N"]
    Bc, Bs = collapse_issuer(Ec), collapse_issuer(Es)
    print(f"\nshare-class duplicates: convert {len(Ec) - len(Bc)} of {len(Ec)} spec-A events collapse "
          f"(spec B n={len(Bc)}); control {len(Es) - len(Bs)} of {len(Es)} (spec B n={len(Bs)})")

    S = pd.concat([summarise(Ec, "A convert"), summarise(Es, "A control"),
                   summarise(Bc, "B convert"), summarise(Bs, "B control")])
    print("\n== window statistics (abnormal = stock ret - SPY ret, summed; t: plain, clustered by date, by week)")
    print(S.round({"mean_pct": 2, "median_pct": 2, "t_plain": 2, "t_cl_date": 2, "t_cl_week": 2}).to_string(index=False))

    print(f"\n== calendar-time portfolio, {G3_WINDOW} (equal weight across events held each day; spec A)")
    for lab, E in (("A convert", Ec), ("A control", Es)):
        ct = calendar_time(E, ret, WINDOWS[G3_WINDOW])
        print(f"   {lab:<10} days {ct['days']}, mean {ct['mean_bp']:+.1f}bp/day (x4 = {ct['per_event_equiv_pct']:+.2f}%), "
              f"t {ct['t']:+.2f}, Newey-West(4) t {ct['t_nw4']:+.2f}")

    print(f"\n== robustness: beta-adjusted {G3_WINDOW} (beta on days {BETA_EST[0]}..{BETA_EST[1]}, no intercept; spec A)")
    for lab, E in (("A convert", Ec), ("A control", Es)):
        bA = beta_adjusted(E, ret, WINDOWS[G3_WINDOW])
        wk = bA["d0"].dt.to_period("W-FRI").astype(str)
        tb, _ = cluster_t(bA["ar_beta"].to_numpy(), wk)
        tm, _ = cluster_t(bA["ar_mkt"].to_numpy(), wk)
        print(f"   {lab:<10} n {len(bA)} of {len(E)} (short estimation history left out); median beta "
              f"{bA['beta'].median():.2f}; beta-adjusted {100 * bA['ar_beta'].mean():+.2f}% (t_cl_week {tb:+.2f}) "
              f"vs market-adjusted on the same events {100 * bA['ar_mkt'].mean():+.2f}% (t_cl_week {tm:+.2f})")

    print("\n== convert minus control (pooled regression, SE clustered by calendar week)")
    for k in ("evt[-1,0]", G3_WINDOW):
        for lab, a, b in (("A", Ec, Es), ("B", Bc, Bs)):
            d = diff_test(a, b, k)
            print(f"   spec {lab} {k:<14} diff {d['diff_pct']:+.2f}%  t {d['t_cl_week']:+.2f}  ({d['clusters']} weeks)")

    print(f"\n== eras (H5), {G3_WINDOW} and evt[-1,0]; t clustered by week; the 2023-26 era is the sealed holdout")
    for lab, E in (("A convert", Ec), ("A control", Es), ("B convert", Bc)):
        for era, a, b in ERAS + AGENT_SPLIT:
            x = E[(E.d0.dt.year >= a) & (E.d0.dt.year <= b)]
            if len(x) < 10:
                continue
            wk = x["d0"].dt.to_period("W-FRI").astype(str)
            t5, _ = cluster_t(x[G3_WINDOW].to_numpy(), wk)
            t0, _ = cluster_t(x["evt[-1,0]"].to_numpy(), wk)
            print(f"   {lab:<10} {era}: n {len(x):>4}  [-1,0] {100 * x['evt[-1,0]'].mean():+.2f}% (t {t0:+.2f})  "
                  f"[+2,+5] {100 * x[G3_WINDOW].mean():+.2f}% (t {t5:+.2f})")

    print(f"\n== convert minus control by era, {G3_WINDOW} (spec A, week-clustered): does the control score as well? (H12)")
    for era, a, b in ERAS:
        sel = lambda E: E[(E.d0.dt.year >= a) & (E.d0.dt.year <= b)]
        d = diff_test(sel(Ec), sel(Es), G3_WINDOW)
        print(f"   {era}: convert {100 * sel(Ec)[G3_WINDOW].mean():+.2f}% vs control {100 * sel(Es)[G3_WINDOW].mean():+.2f}%"
              f" -> diff {d['diff_pct']:+.2f}% (t {d['t_cl_week']:+.2f}, {d['clusters']} weeks)")

    print(f"\n== cost grid (H3): long day +1 MOC to day +5 MOC, one round trip = 2 x one-way; borrow none (long only)")
    for lab, E in (("A convert", Ec), ("B convert", Bc), ("A control", Es)):
        g = 1e4 * E[G3_WINDOW].mean()
        nets = "  ".join(f"{c}bp: {g - 2 * c:+.0f}bp" for c in COST_GRID_BP)
        print(f"   {lab:<10} gross {g:+.0f}bp per event | net {nets}")

    print("\n== clustering of issue dates (G3)")
    yr = Ec.groupby(Ec.d0.dt.year).size()
    print("   spec A convert events per year:", yr.to_dict())
    print("   busiest day:", int(Ec.groupby("d0").size().max()), "events; busiest week:",
          int(Ec.groupby(Ec.d0.dt.to_period("W-FRI")).size().max()), "events;",
          "weeks with any event:", Ec.d0.dt.to_period("W-FRI").nunique())

    # holdout names: convert issuers are operating companies; check no CEF ticker slipped in
    uni = pd.read_csv(REPO / "data" / "cef" / "cef_universe.csv")
    hit = sorted(set(Ec.ticker.dropna()) & set(uni["ticker"]))
    print("\n   tickers shared with data/cef/cef_universe.csv:", hit if hit else "none")

    ev = pd.concat([Ec.assign(sample="convert"), Es.assign(sample="straight_control")])
    ev["d0"] = ev["d0"].dt.date
    ev["day0_crsp"] = ev["day0_crsp"].dt.date
    OUT_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    ev.to_csv(OUT_EVENTS, index=False, float_format="%.6f")
    print(f"\nwrote {OUT_EVENTS.relative_to(REPO)} ({len(ev)} rows, spec A)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
