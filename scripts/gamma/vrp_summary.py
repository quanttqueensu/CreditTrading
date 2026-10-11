"""Implied vs forward-realised vol for TLT (and HYG): the SCALING §7 figures, re-run.

    export QUANTT_ENV_FILE=/abs/path/to/config/.env   # only for the CRSP cross-check
    python3 scripts/gamma/vrp_summary.py [--vol-panel PATH] [--no-crsp]

Descriptive, 0 trials (GAMMA stays at 0). It forms no strategy P&L, chooses no
parameter, and tests nothing; it re-measures the numbers that
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.1 rows 3 and 10 quote, which a
2026-10-09 agent computed in a scratch script (`vrp_summary.py`, deleted with its
session). Report: `results/gamma/REPRO_TLT_VRP_2026-10-11.md`.

WHAT THE STATISTICS ARE (identical to the scratch script, so they reproduce)
---------------------------------------------------------------------------
For an implied-vol series IV_t (annualised, decimal) and the forward realised
vol RV_t over sessions t+1..t+21 (`tlt_atm_iv.forward_rv`, log TOTAL returns):

* `spread_mean` -- mean of IV_t - RV_t over EVERY session (overlapping windows),
  in vol points. This is the "+1.23" of SCALING §7.1 row 3.
* `nonov_mean`, `nonov_t` -- the same difference sampled every 21st row
  starting at the first row (non-overlapping windows), and its plain t. This is
  the "t 4.16". NOTE: its mean is not the +1.23; the note paired a mean from one
  sample with a t from another (corrected visibly in the repro note).
* `worst` -- the most negative IV_t - RV_t and the IV date it belongs to. The
  "March 2020 -44.7" is the IV of 2020-02-21 against the realised vol of the 21
  sessions that followed it (2020-02-24..2020-03-23).

ADDED HERE, AS ROBUSTNESS (not in the scratch script; they choose nothing)
-------------------------------------------------------------------------
* `t` over all 21 phases of the non-overlapping sample (the scratch t used phase
  0 only), and a Newey-West t (20 lags) on the overlapping daily series.
* **G2(a)'s gross proxy**: VXTLT is a VIX-methodology (model-free) 30-day
  implied variance, so VXTLT_t^2 is approximately a 30-day variance-swap strike
  and VXTLT_t^2 - RV_t^2 is the gross P&L of a short variance swap held to
  expiry, in variance points. Reported by era (H5) on the non-overlapping
  sample. It is GROSS: G2(a) needs it net of a measured four-leg regular-hours
  spread (plan item 0.10), which does not exist yet.
* A strict-window variant: only IV dates whose 21-session forward window ends
  on or before 2022-12-30, so no 2023 return enters the 2004-22 reading.

INPUTS AND THEIR LAST DATES (printed on every run)
--------------------------------------------------
* Cboe VXTLT / VXHYG: `scripts/gamma/fetch_cboe_vol_indices.py` output.
  VXHYG's named defect (2017-10-30) is dropped by the fetcher; its 2021-09-24 ..
  2025-05-14 hole is NOT filled, so a "pre-2023" VXHYG window is 2015-04..2021-09.
* Realised vol: `data/rv/etf_panel.parquet` `ret_total` (as the scratch run), and
  independently CRSP `dsf.ret` via R2 (to 2024-12-31) as a second source. When
  they disagree, both are printed; neither is averaged.
* TLT tick-built ATM IV (2023-11+): `scripts/gamma/tlt_atm_iv.py`. **2023+ is the
  GAMMA holdout (docs/SYSTEM.md §5, 2026-10-09). Description only: the rows are
  labelled and no inference is drawn from them.**
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.gamma import fetch_cboe_vol_indices as cboe          # noqa: E402
from scripts.gamma.tlt_atm_iv import forward_rv, OUT as ATM_PATH   # noqa: E402

DEFAULT_PANEL = REPO / "data/gamma/cboe_vol_indices.parquet"
ETF_PANEL = REPO / "data/rv/etf_panel.parquet"
CRSP_CACHE = REPO / "results/gamma/_cache_inputs/crsp_etf_returns.parquet"
CRSP_PERMNO = {"TLT": 89468, "HYG": 91933}      # dsenames, verified 2026-10-11
H = 21
FIT = ("2004-01-01", "2022-12-31")
POST = ("2023-01-01", "2026-12-31")
ERAS = [("2004-09", "2004", "2009"), ("2010-14", "2010", "2014"),
        ("2015-19", "2015", "2019"), ("2020-22", "2020", "2022")]
EPISODES = {"2008-Q4": ("2008-09-01", "2008-12-31"), "Mar-2020": ("2020-02-15", "2020-03-31"),
            "2022": ("2022-01-01", "2022-12-31")}


def load_iv(panel: Path, index: str) -> pd.Series:
    if not panel.exists():
        raise FileNotFoundError(f"{panel} missing: run scripts/gamma/fetch_cboe_vol_indices.py")
    df = pd.read_parquet(panel)
    if index not in set(df["index"]):
        raise KeyError(f"{index} is not in {panel} (it holds {sorted(set(df['index']))}); "
                       f"fetch it with fetch_cboe_vol_indices.py --indices {index} --out ...")
    s = cboe.series(df, index) / 100.0
    if (s <= 0).any():
        raise ValueError(f"{index}: a non-positive implied vol reached the analysis")
    return s.rename("iv")


def etf_rv(sym: str, path: Path = ETF_PANEL) -> tuple[pd.Series, pd.Timestamp]:
    p = pd.read_parquet(path)
    s = p[p.ticker == sym].set_index("date").sort_index()["ret_total"]
    return forward_rv(s).rename("rv"), s.index.max()


def crsp_rv(sym: str) -> tuple[pd.Series, pd.Timestamp]:
    """Forward RV from CRSP daily total returns (`ret`, distributions included)."""
    if not CRSP_CACHE.exists():
        from src.data import r2
        con = r2.connect()
        d = r2.r2_path("crsp_a_stock", "dsf")
        ids = ",".join(str(v) for v in CRSP_PERMNO.values())
        df = r2.q(con, f"select permno, date, cast(ret as double) ret from read_parquet('{d}') "
                       f"where permno in ({ids}) order by permno, date")
        CRSP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(CRSP_CACHE)
    df = pd.read_parquet(CRSP_CACHE)
    s = df[df.permno == CRSP_PERMNO[sym]].assign(date=lambda x: pd.to_datetime(x.date)) \
        .set_index("date")["ret"].sort_index()
    return forward_rv(s).rename("rv"), s.index.max()


def newey_west_t(x: pd.Series, lags: int) -> float:
    x = x.dropna().values
    n = len(x)
    e = x - x.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return x.mean() / np.sqrt(s / n)


def stats(j: pd.DataFrame) -> dict:
    """The scratch script's statistics on a frame with columns iv, rv (decimal)."""
    j = j.dropna()
    sp = j.iv - j.rv
    m = j.iloc[::H]
    msp = m.iv - m.rv
    phase_t = []
    for ph in range(H):
        mm = j.iloc[ph::H]
        d = mm.iv - mm.rv
        phase_t.append(d.mean() / (d.std(ddof=1) / np.sqrt(len(d))))
    worst_day = sp.idxmin()
    out = dict(n=len(j), first=j.index.min().date(), last=j.index.max().date(),
               iv_mean=j.iv.mean() * 100, rv_mean=j.rv.mean() * 100,
               spread_mean=sp.mean() * 100, spread_med=sp.median() * 100,
               varratio_med=((j.iv ** 2) / (j.rv ** 2)).median(),
               pct_iv_below_rv=(sp < 0).mean() * 100,
               nonov_n=len(m), nonov_mean=msp.mean() * 100,
               nonov_t=msp.mean() / (msp.std(ddof=1) / np.sqrt(len(m))),
               phase_t_min=min(phase_t), phase_t_med=float(np.median(phase_t)),
               phase_t_max=max(phase_t), nw20_t=newey_west_t(sp, 20),
               worst=sp.min() * 100, worst_iv_date=worst_day.date())
    for k, (a, b) in EPISODES.items():
        w = sp.loc[a:b]
        out[f"min_{k}"] = w.min() * 100 if len(w) else np.nan
    return out


def varswap_proxy(j: pd.DataFrame) -> dict:
    """G2(a) GROSS: short-variance-swap P&L IV^2 - RV^2, non-overlapping, in %^2."""
    jj = j.dropna()
    m = jj.iloc[::H]
    vp = (m.iv ** 2 - m.rv ** 2) * 1e4
    ts = []
    for ph in range(H):                          # every start phase, as a robustness range
        v = (jj.iloc[ph::H].iv ** 2 - jj.iloc[ph::H].rv ** 2) * 1e4
        ts.append(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))
    return dict(n=len(vp), mean=vp.mean(), t=vp.mean() / (vp.std(ddof=1) / np.sqrt(len(vp))),
                t_phase_min=min(ts), t_phase_med=float(np.median(ts)), t_phase_max=max(ts),
                median=vp.median(), pct_pos=(vp > 0).mean() * 100, worst=vp.min(),
                worst_date=vp.idxmin().date(), skew=vp.skew())


def fmt(d: dict) -> str:
    return "  ".join(f"{k}={v:.3f}" if isinstance(v, (float, np.floating)) else f"{k}={v}"
                     for k, v in d.items())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vol-panel", default=str(DEFAULT_PANEL))
    ap.add_argument("--no-crsp", action="store_true")
    ap.add_argument("--etf-panel", default=str(ETF_PANEL),
                    help="realised-vol source; the 2026-10-09 scratch run read the panel that "
                         "ended 2026-07-28 (kept by the 2026-10-11 rebuild as "
                         "data/rv/etf_panel.parquet.pre-20261011.bak)")
    a = ap.parse_args()
    panel = Path(a.vol_panel)
    etf_path = Path(a.etf_panel)

    vxtlt = load_iv(panel, "VXTLT")
    vxhyg = load_iv(panel, "VXHYG")
    rv_tlt, last_tlt = etf_rv("TLT", etf_path)
    rv_hyg, last_hyg = etf_rv("HYG", etf_path)
    print(f"inputs: {etf_path.name}; {panel} (VXTLT last {vxtlt.index.max().date()}, VXHYG last "
          f"{vxhyg.index.max().date()}); etf_panel TLT last {last_tlt.date()}, HYG last "
          f"{last_hyg.date()}")
    for before, after, days in cboe.gaps(pd.read_parquet(panel), "VXHYG"):
        print(f"  VXHYG gap: {before} -> {after} ({days} calendar days), not filled")

    J = pd.concat([vxtlt, rv_tlt], axis=1, join="inner")
    print("\n== TLT, VXTLT vs etf_panel forward RV (the scratch run's inputs)")
    print("fit 2004-22   ", fmt(stats(J.loc[FIT[0]:FIT[1]])))
    strict = J.loc[FIT[0]:FIT[1]]
    last_ok = J.index[J.index.get_indexer([pd.Timestamp("2022-12-30")], method="pad")[0] - H]
    print(f"fit strict (IV date <= {last_ok.date()}, forward window ends <= 2022-12-30)")
    print("              ", fmt(stats(strict.loc[:last_ok])))
    print("2023+ [VXTLT index, labelled; no inference]")
    print("              ", fmt(stats(J.loc[POST[0]:POST[1]])))

    print("\n== G2(a) GROSS proxy: short 30d variance swap at VXTLT^2, held 21 sessions, %^2")
    print("fit 2004-22   ", fmt(varswap_proxy(J.loc[FIT[0]:FIT[1]])))
    for lab, a0, b0 in ERAS:
        print(f"era {lab}   ", fmt(varswap_proxy(J.loc[a0:b0])))

    if not a.no_crsp:
        rc, lastc = crsp_rv("TLT")
        Jc = pd.concat([vxtlt, rc], axis=1, join="inner")
        print(f"\n== TLT cross-check: VXTLT vs CRSP dsf forward RV (CRSP last {lastc.date()})")
        print("fit 2004-22   ", fmt(stats(Jc.loc[FIT[0]:FIT[1]])))
        both = pd.concat([rv_tlt.rename("etf"), rc.rename("crsp")], axis=1).loc[FIT[0]:FIT[1]].dropna()
        print(f"  RV etf_panel vs CRSP on {len(both)} common dates: corr {both.etf.corr(both.crsp):.5f}, "
              f"max |diff| {(both.etf-both.crsp).abs().max()*100:.3f} vol pts")

    K = pd.concat([vxhyg, rv_hyg], axis=1, join="inner")
    print("\n== HYG, VXHYG vs etf_panel forward RV (pre-2023 = 2015-04..2021-09; the hole is real)")
    print("pre-2023      ", fmt(stats(K.loc[FIT[0]:FIT[1]])))
    print("pre-2023 G2(a)-style gross proxy ", fmt(varswap_proxy(K.loc[FIT[0]:FIT[1]])))

    if ATM_PATH.exists():
        t = pd.read_parquet(ATM_PATH)
        T = pd.concat([t["iv30"].rename("iv"), rv_tlt], axis=1, join="inner")
        print("\n== TLT tick-built 30d ATM IV, 2023-11+  [GAMMA HOLDOUT: description only, "
              "no inference]")
        print("tick ATM      ", fmt(stats(T)))
        x = pd.concat([t["iv30"], vxtlt.rename("vxtlt")], axis=1, join="inner").dropna()
        print(f"  method check vs VXTLT on {len(x)} common dates: level corr {x.iv30.corr(x.vxtlt):.3f}, "
              f"daily-change corr {x.iv30.diff().corr(x.vxtlt.diff()):.3f}, "
              f"mean VXTLT-ATM {(x.vxtlt-x.iv30).mean()*100:.2f} pts")
    else:
        print(f"\n(no {ATM_PATH}: run scripts/gamma/tlt_atm_iv.py extract && build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
