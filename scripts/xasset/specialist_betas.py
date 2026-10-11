"""How much of the CEF specialists' return is beta? CRSP returns, betas and intercepts.

    export QUANTT_ENV_FILE=/abs/path/to/config/.env      # R2; never printed
    python3 scripts/xasset/specialist_betas.py

Descriptive, 0 trials (XASSET stays at 0). It scores no signal and trades no
name; it describes OTHER firms' listed vehicles. Re-run of the 2026-10-09 scratch
scripts `betas.py` / `betas2.py` / `xcheck.py` (deleted with their session) behind
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.3: "On monthly market returns,
SPX plus HY explain R^2 0.44-0.88. The intercept is negative for 15 of 17
vehicles", and "BRW ... at about 12% vol". Report:
`results/xasset/REPRO_SPECIALISTS_2026-10-11.md`.

WHAT IS MEASURED (as the scratch run, so it reproduces)
------------------------------------------------------
* Vehicle returns: CRSP daily `dsf.ret` (market price, distributions included)
  for listed vehicles; CRSP MF `daily_returns.dret` (NAV, net of fees,
  distributions included) for the open-end MDCEX, MDFIX and RNCOX. Each from its
  MANAGER-ERA start (taken from CRSP's name history; e.g. permno 77460 was Voya
  Prime Rate Trust until it became Saba's BRW on 2021-06-07) to 2024-12-31,
  where the CRSP stock file ends.
* Factors: SPY and HYG CRSP total returns (permnos 84398, 91933) -- the note's
  "SPX plus HY" means these two ETFs -- in excess of the Fama-French daily rf.
* Monthly: daily returns compounded within calendar months (partial first and
  last months included, as the scratch run did). Two-factor OLS
  r - rf = a + b_SPY (SPY - rf) + b_HY (HYG - rf) + e; R^2; a x 12 = the
  "intercept" (return beyond the two betas).
* Daily: CAGR, annualised vol, maximum drawdown.

ADDED HERE (they choose nothing)
--------------------------------
* The intercept's OLS t and a Newey-West t (3 lags), so "negative for 15 of
  17" can be read against noise; and the count over every plausible set of
  "17", because the scratch report never listed which 17.
* An independent check of two FILED returns: MDCEX and MDFIX trailing 1/5/10-year
  NAV returns to 2026-03-31 from CRSP MF (which runs to 2026-03-31), against the
  Matisse N-CSR/A (re-read 2026-10-11).
* A guard: no vehicle may be one of the 44 names in `data/cef/cef_universe.csv`
  (the 27-name holdout is consumed by the first test that computes returns on
  one; docs/SYSTEM.md §5). It raises if one is.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CACHE = REPO / "results/xasset/_cache_specialists"
END = "2024-12-31"
SPY, HYG = 84398, 91933

# vehicle: (source, ids, manager-era start). ids for YYY are two permnos that
# never overlap in time (a trust change on 2019-10-07); they are spliced.
VEHICLES = {
    "SPE (Bulldog)":         ("stk", [79236], "2009-12-22"),
    "BRW (Saba)":            ("stk", [77460], "2021-06-07"),
    "SABA (Saba, ex-GIM)":   ("stk", [75274], "2024-01-02"),
    "CEFS (Saba ETF)":       ("stk", [17440], "2017-03-21"),
    "RIV (RiverNorth)":      ("stk", [15887], "2015-12-24"),
    "OPP (RiverNorth/DL)":   ("stk", [16337], "2016-09-28"),
    "RSF (RiverNorth)":      ("stk", [18765], "2019-06-12"),
    "RMI (RiverNorth)":      ("stk", [18179], "2018-10-26"),
    "RMM (RiverNorth)":      ("stk", [18811], "2019-07-26"),
    "RFM (RiverNorth)":      ("stk", [19300], "2020-03-27"),
    "RFMZ (RiverNorth)":     ("stk", [20550], "2021-02-24"),
    "RMMZ (RiverNorth)":     ("stk", [22858], "2022-02-11"),
    "RNCOX (RiverNorth OE)": ("mf",  [26513], "2007-01-01"),
    "MDCEX (Matisse)":       ("mf",  [56557], "2012-11-01"),
    "MDFIX (Matisse bond)":  ("mf",  [96939], "2020-05-01"),
    "YYY (passive)":         ("stk", [13433, 18971], "2013-06-21"),
    "PCEF (passive)":        ("stk", [93254], "2010-02-19"),
    "FCEF (passive)":        ("stk", [16288], "2016-09-28"),
    "XMPT (passive muni)":   ("stk", [12899], "2011-07-13"),
}
TICKERS = {k: k.split()[0] for k in VEHICLES}


def pull() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame]:
    """R2 reads, cached under results/xasset/_cache_specialists/ (gitignored)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = {k: CACHE / f"{k}.parquet" for k in ("stk", "mf", "ff", "names")}
    if not all(p.exists() for p in f.values()):
        from src.data import r2
        con = r2.connect()
        stk = sorted({i for s, ids, _ in VEHICLES.values() if s == "stk" for i in ids} | {SPY, HYG})
        mf = sorted({i for s, ids, _ in VEHICLES.values() if s == "mf" for i in ids})
        r2.q(con, f"select permno id, date, cast(ret as double) r from read_parquet('"
                  f"{r2.r2_path('crsp_a_stock', 'dsf')}') where permno in ({','.join(map(str, stk))}) "
                  f"and ret is not null").to_parquet(f["stk"])
        r2.q(con, f"select cast(crsp_fundno as int) id, caldt date, dret r from read_parquet('"
                  f"{r2.r2_path('crsp_q_mutualfunds', 'daily_returns')}') where crsp_fundno in "
                  f"({','.join(map(str, mf))}) and dret is not null").to_parquet(f["mf"])
        r2.q(con, f"select date, cast(rf as double) rf from read_parquet('"
                  f"{r2.r2_path('ff_all', 'factors_daily')}')").to_parquet(f["ff"])
        r2.q(con, f"select permno, ticker, comnam, shrcd, namedt, nameendt from read_parquet('"
                  f"{r2.r2_path('crsp_a_stock', 'dsenames')}') where permno in "
                  f"({','.join(map(str, stk))}) order by permno, namedt").to_parquet(f["names"])
    S = pd.read_parquet(f["stk"]).assign(date=lambda x: pd.to_datetime(x.date))
    M = pd.read_parquet(f["mf"]).assign(date=lambda x: pd.to_datetime(x.date))
    F = pd.read_parquet(f["ff"]).assign(date=lambda x: pd.to_datetime(x.date)).set_index("date")["rf"]
    N = pd.read_parquet(f["names"])
    return S, M, F, N


def series(S, M, src, ids, start, end=END) -> pd.Series:
    T = S if src == "stk" else M
    x = T[T.id.isin(ids)]
    if x.groupby("date").size().max() > 1:
        raise ValueError(f"ids {ids} overlap in time; a splice would double-count")
    x = x.set_index("date")["r"].sort_index()
    return x[(x.index > pd.Timestamp(start)) & (x.index <= pd.Timestamp(end))]


def mdd(r: pd.Series) -> float:
    w = (1 + r).cumprod()
    return float((w / w.cummax() - 1).min())


def ols(y: np.ndarray, X: list[np.ndarray], nw_lags: int = 3):
    Z = np.column_stack([np.ones(len(y))] + X)
    b, *_ = np.linalg.lstsq(Z, y, rcond=None)
    e = y - Z @ b
    n, k = Z.shape
    ZtZi = np.linalg.inv(Z.T @ Z)
    se_ols = np.sqrt(np.diag(ZtZi) * (e @ e) / (n - k))
    S = (Z * e[:, None]).T @ (Z * e[:, None])
    for L in range(1, nw_lags + 1):
        w = 1 - L / (nw_lags + 1)
        G = (Z[L:] * e[L:, None]).T @ (Z[:-L] * e[:-L, None])
        S += w * (G + G.T)
    se_nw = np.sqrt(np.diag(ZtZi @ S @ ZtZi))
    r2 = 1 - e.var() / y.var()
    return b, b / se_ols, b / se_nw, r2


def describe(S, M, F) -> pd.DataFrame:
    spy, hyg = series(S, M, "stk", [SPY], "1990-01-01"), series(S, M, "stk", [HYG], "1990-01-01")
    rows = []
    for k, (src, ids, start) in VEHICLES.items():
        r = series(S, M, src, ids, start)
        df = pd.concat({"r": r, "spy": spy, "hyg": hyg, "rf": F}, axis=1, join="inner").dropna()
        n = len(df)
        m = (1 + df).groupby(df.index.to_period("M")).prod() - 1
        mex = m[["r", "spy", "hyg"]].sub(m.rf, axis=0)
        b, t_ols, t_nw, r2 = ols(mex.r.values, [mex.spy.values, mex.hyg.values])
        rows.append(dict(vehicle=k, start=df.index[0].date(), end=df.index[-1].date(),
                         n_months=len(m), cagr=((1 + df.r).prod() ** (252 / n) - 1) * 100,
                         vol=df.r.std() * np.sqrt(252) * 100, mdd=mdd(df.r) * 100,
                         b_spy=b[1], b_hy=b[2], r2=r2, alpha_ann=b[0] * 12 * 100,
                         t_alpha_ols=t_ols[0], t_alpha_nw3=t_nw[0]))
    return pd.DataFrame(rows).set_index("vehicle")


def trailing(r: pd.Series, end: str, years: float) -> float:
    """Annualised return over the `years` before `end` (calendar), from daily returns."""
    e = pd.Timestamp(end)
    s = e - pd.DateOffset(years=int(years))
    x = r[(r.index > s) & (r.index <= e)]
    return ((1 + x).prod() ** (1 / years) - 1) * 100


def main() -> int:
    u = pd.read_csv(REPO / "data/cef/cef_universe.csv")["ticker"]
    clash = sorted(set(TICKERS.values()) & set(u))
    if clash:
        raise RuntimeError(f"{clash} are in cef_universe.csv: computing their returns would "
                           f"consume the 27-name holdout (docs/SYSTEM.md §5)")
    S, M, F, N = pull()
    print(f"CRSP dsf last {S.date.max().date()}, CRSP MF last {M.date.max().date()}, "
          f"FF rf last {F.index.max().date()}; universe guard: none of the "
          f"{len(VEHICLES)} vehicles is among the {len(u)} cef_universe names")
    print("\nCRSP names behind each permno (manager-era start must fall inside the right row):")
    pd.set_option("display.width", 250)
    print(N[N.nameendt >= "2007-01-01"].to_string(index=False))

    out = describe(S, M, F)
    print(f"\nmonthly two-factor fit, manager era .. {END}")
    print(out.round(2).to_string())
    neg = out.alpha_ann < 0
    sets = {
        "all 19": list(out.index),
        "18: excl SABA (12 months)": [v for v in out.index if not v.startswith("SABA")],
        "17: excl SABA, XMPT": [v for v in out.index if not v.startswith(("SABA", "XMPT"))],
        "17: excl SABA, RSF": [v for v in out.index if not v.startswith(("SABA", "RSF"))],
        "17: excl the passive PCEF, FCEF": [v for v in out.index if not v.startswith(("PCEF", "FCEF"))],
    }
    print("\nnegative intercepts:")
    for lab, vs in sets.items():
        print(f"  {lab}: {int(neg[vs].sum())} of {len(vs)} negative; positive: "
              f"{[v.split()[0] for v in vs if not neg[v]]}")
    print(f"  |t_NW3| >= 2 on the intercept: "
          f"{[(v.split()[0], round(out.t_alpha_nw3[v], 2)) for v in out.index if abs(out.t_alpha_nw3[v]) >= 2]}")
    rr = out.r2
    print(f"\nR^2 range, all 19: {rr.min():.2f} ({rr.idxmin().split()[0]}) .. {rr.max():.2f} "
          f"({rr.idxmax().split()[0]}); below 0.44: "
          f"{[(v.split()[0], round(rr[v], 2)) for v in rr.index if rr[v] < 0.44]}")

    print("\nindependent check of filed NAV returns to 2026-03-31 (CRSP MF dret, net of fees):")
    for k, fid in (("MDCEX", 56557), ("MDFIX", 96939)):
        r = M[M.id == fid].set_index("date")["r"].sort_index()
        print(f"  {k}: 1y {trailing(r, '2026-03-31', 1):.2f}%  5y {trailing(r, '2026-03-31', 5):.2f}%  "
              f"10y {trailing(r, '2026-03-31', 10) if k == 'MDCEX' else float('nan'):.2f}%  "
              f"(CRSP MF from {r.index.min().date()})")
    print("\npipeline check against two 497K figures (to 2024-12-31, market price):")
    for k, pid, starts in (("PCEF", 93254, ("2023-12-31", "2019-12-31", "2014-12-31")),
                           ("FCEF", 16288, ("2023-12-31", "2019-12-31", "2016-09-27"))):
        r = S[S.id == pid].set_index("date")["r"].sort_index()
        vals = []
        for s in starts:
            x = r[(r.index > pd.Timestamp(s)) & (r.index <= pd.Timestamp(END))]
            yrs = (pd.Timestamp(END) - pd.Timestamp(s)).days / 365.25
            vals.append(round(((1 + x).prod() ** (1 / yrs) - 1) * 100, 2))
        print(f"  {k} 1y / 5y / {'10y' if k == 'PCEF' else 'since 2016-09-27'}: {vals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
