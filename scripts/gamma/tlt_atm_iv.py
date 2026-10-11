"""30-day ATM implied vol for TLT built from R2 option TRADES (descriptive, 0 trials).

    export QUANTT_ENV_FILE=/abs/path/to/config/.env      # R2 credentials; never printed
    python3 scripts/gamma/tlt_atm_iv.py extract            # R2 -> per-month cache (read-only on R2)
    python3 scripts/gamma/tlt_atm_iv.py build              # cache -> 30d ATM IV series

WHY THIS EXISTS
---------------
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.1 row 3 quotes "+1.63 vol pts
from R2 ticks 2023-26" for TLT implied minus forward realised vol. The agent
that measured it (2026-10-09) built the series with scratch scripts that were
deleted with the session. This is that build, rebuilt in the repo so the figure
can be reproduced (RESEARCH_PLAN_2026-10-09 item 0.9), with the method written
down because R2 holds trades only and every choice below moves the number.

STATUS OF THE DATA: THE GAMMA HOLDOUT, DESCRIPTION ONLY
-------------------------------------------------------
R2's TLT option ticks start 2023-11. The team lead's 2026-10-09 ruling
(`docs/SYSTEM.md` §5) is "Fit and decide on Cboe VXTLT, 2004-2022. The 2023+
strike data is the GAMMA holdout, opened once for the defined-risk version."
So this series is a DESCRIPTION of a number already published, never fit data:
nothing here chooses a parameter, a strike, a structure or a threshold, and no
inference about the short-variance trade may be drawn from it. The only
statistics computed on it are the ones SCALING §7 already quotes.

METHOD (identical to the 2026-10-09 scratch build unless marked)
---------------------------------------------------------------
* **Prices.** Per contract and session, the MEDIAN single-leg trade price in
  15:30-16:00 ET, expiries 5..75 calendar days out. Early-close sessions have
  no prints in that window and drop out (counted).
* **Condition codes.** Kept: 209 (auto-execution), 210 (reopening), 219 (ISO),
  227/228 (single-leg auction), 229/230 (single-leg cross), 231 (single-leg
  floor). Dropped: cancels/late reports (201-208) and multi-leg or
  stock-option prints (232-247), because a spread leg prints at a
  package-derived price. The code -> meaning map is the Polygon/Massive option
  condition table as the 2026-10-09 agent read it: **[U]**, not re-verified
  against the vendor's reference endpoint (it needs a key we do not hold).
* **Forward.** Put-call parity on the 2-3 strikes nearest spot (within 3%)
  that printed BOTH a call and a put: F_K = K + (C - P)/DF; F = median F_K.
  An expiry whose F is more than 2% from S*e^{rT} is rejected (a stale-print
  guard, counted, not a fallback).
* **IV.** Black-76 on F with DF = e^{-rT}, r = FRED DGS1MO as last published ON
  OR BEFORE the session date (strictly no later rate). Out-of-the-money side
  only (put below F, call at/above), which keeps the American early-exercise
  premium small; ATM IV = linear interpolation in K between the nearest strike
  below F and the nearest at/above.
* **30-day constant maturity.** Total variance sigma^2*T interpolated linearly
  between the longest expiry with 7<=dte<=30 and the shortest with
  30<dte<=60 (the VIX convention). Missing either side -> session skipped.
* **Spot and realised.** Spot = TLT unadjusted close; realised = forward
  21-session close-to-close vol of log TOTAL returns (ex-dividend drops are
  anticipated by the forward and are not variance), t+1..t+21, sqrt(252/21*sum
  r^2), zero mean. Source `data/rv/etf_panel.parquet` (staged before the
  2026-09-28 clean slate; its fetcher is at tag `pre-clean-slate`, plan item
  0.1). Implied is 30 calendar days on 365; realised is 21 sessions on 252.

DEVIATIONS FROM THE SCRATCH BUILD
---------------------------------
None in method. The rate now comes from `scripts/gamma/fetch_fred.py` rather
than a hand curl; the tick aggregates are cached under
`results/gamma/_cache_tlt_ticks/` (gitignored), one file per month.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CACHE = REPO / "results/gamma/_cache_tlt_ticks"
INPUTS = REPO / "results/gamma/_cache_inputs"
RATE_PATH = INPUTS / "fred_DGS1MO.parquet"
OUT = INPUTS / "tlt_atm_iv30.parquet"
ETF_PANEL = REPO / "data/rv/etf_panel.parquet"

SYM = "TLT"
FIRST_MONTH, LAST_MONTH = "2023-11", "2026-07"      # R2 coverage, R2_CATALOG.md
KEEP = ("209", "210", "219", "227", "228", "229", "230", "231")
WINDOW = ("15:30", "16:00")
DTE_MIN, DTE_MAX = 5, 75
PARITY_MAX_STRIKES, PARITY_BAND, FWD_GUARD = 3, 0.03, 0.02
NEAR, NEXT = (7, 30), (30, 60)
H_RV = 21


def months(a: str, b: str):
    p = pd.Period(a, "M")
    while p <= pd.Period(b, "M"):
        yield str(p)
        p += 1


# --------------------------------------------------------------------------- extract

def extract(first: str = FIRST_MONTH, last: str = LAST_MONTH) -> None:
    """Read-only DuckDB queries against R2; one cached parquet pair per month."""
    from src.data import r2
    CACHE.mkdir(parents=True, exist_ok=True)
    con = r2.connect()
    con.execute("SET TimeZone='America/New_York'")       # session dates and HH:MM in ET
    keep = ",".join(f"'{c}'" for c in KEEP)
    for m in months(first, last):
        f_close = CACHE / f"{SYM}_{m}_close.parquet"
        f_vol = CACHE / f"{SYM}_{m}_dayvol.parquet"
        if f_close.exists() and f_vol.exists():
            continue
        t0 = time.time()
        p = r2.options_path(SYM, m)
        close = r2.q(con, f"""
            WITH x AS (SELECT CAST(ts AS DATE) d, strftime(ts, '%H:%M') hm, expiry,
                              opt_type, strike, price, size, conditions
                       FROM read_parquet('{p}'))
            SELECT d, expiry, opt_type, strike, median(price) AS px_med,
                   SUM(price*size)/SUM(size) AS vwap, SUM(size) AS vol, COUNT(*) AS n
            FROM x
            WHERE hm >= '{WINDOW[0]}' AND hm < '{WINDOW[1]}'
              AND conditions IN ({keep}) AND price > 0
              AND expiry >= d + {DTE_MIN} AND expiry <= d + {DTE_MAX}
            GROUP BY 1,2,3,4""")
        # Liquidity description: contracts per session, all prints and the kept
        # single-leg subset. Volume, not price: no strike-level P&L is formed.
        dayvol = r2.q(con, f"""
            SELECT CAST(ts AS DATE) d, SUM(size) AS contracts_all,
                   SUM(CASE WHEN conditions IN ({keep}) THEN size ELSE 0 END) AS contracts_single_leg,
                   COUNT(*) AS prints
            FROM read_parquet('{p}') GROUP BY 1""")
        close.to_parquet(f_close)
        dayvol.to_parquet(f_vol)
        print(f"{SYM} {m}: {len(close):,} close-window contract rows, "
              f"{dayvol['d'].nunique()} sessions ({time.time()-t0:.1f}s)", flush=True)


# --------------------------------------------------------------------------- IV maths

def b76(F, K, T, DF, sig, cp):
    """Black-76 price of a European option on a forward."""
    from scipy.stats import norm
    if sig <= 0:
        return DF * max((F - K) if cp == "C" else (K - F), 0.0)
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if cp == "C":
        return DF * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return DF * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def implied_vol(px, F, K, T, DF, cp):
    """Black-76 implied vol, or NaN when no vol in [1e-4, 5] reproduces `px`
    (price at or below intrinsic, or above the no-arbitrage bound). A NaN drops
    that expiry for that session and is counted by the caller; it is never
    replaced by a neighbour's vol."""
    from scipy.optimize import brentq
    intrinsic = DF * max((F - K) if cp == "C" else (K - F), 0.0)
    if not (px > intrinsic + 1e-9) or px >= DF * (F if cp == "C" else K):
        return np.nan
    try:
        return brentq(lambda s: b76(F, K, T, DF, s, cp) - px, 1e-4, 5.0, xtol=1e-7)
    except ValueError:
        return np.nan


def atm_for_session(g: pd.DataFrame, S: float, r: float):
    """30d constant-maturity ATM IV for one session's close-window prices, or
    (None, reason)."""
    per_exp = {}
    d0 = pd.Timestamp(g["d"].iloc[0])
    for e, ge in g.groupby("expiry"):
        dte = (pd.Timestamp(e) - d0).days
        T = dte / 365.0
        DF = math.exp(-r * T)
        c = ge[ge.opt_type == "C"].set_index("strike")["px"]
        p = ge[ge.opt_type == "P"].set_index("strike")["px"]
        both = sorted(set(c.index) & set(p.index), key=lambda k: abs(k - S))
        both = [k for k in both if abs(k / S - 1) <= PARITY_BAND][:PARITY_MAX_STRIKES]
        if len(both) < 2:
            continue
        F = float(np.median([k + (c[k] - p[k]) / DF for k in both]))
        if abs(F / (S / DF) - 1) > FWD_GUARD:
            continue
        ks = sorted(set(c.index) | set(p.index))
        below = [k for k in ks if k < F]
        above = [k for k in ks if k >= F]
        if not below or not above:
            continue
        K1, K2 = below[-1], above[0]
        if K1 not in p.index or K2 not in c.index:
            continue
        v1 = implied_vol(p[K1], F, K1, T, DF, "P")
        v2 = implied_vol(c[K2], F, K2, T, DF, "C")
        if np.isnan(v1) or np.isnan(v2):
            continue
        w = (F - K1) / (K2 - K1) if K2 != K1 else 0.0
        per_exp[dte] = (v1 * (1 - w) + v2 * w, F)
    near = [d for d in per_exp if NEAR[0] <= d <= NEAR[1]]
    nxt = [d for d in per_exp if NEXT[0] < d <= NEXT[1]]
    if not near or not nxt:
        return None
    d1, d2 = max(near), min(nxt)
    w1, w2 = per_exp[d1][0] ** 2 * d1, per_exp[d2][0] ** 2 * d2
    w30 = w1 + (w2 - w1) * (30 - d1) / (d2 - d1)
    if w30 <= 0:
        return None
    return math.sqrt(w30 / 30.0), d1, d2, per_exp[d1][1]


def forward_rv(ret_total: pd.Series, h: int = H_RV) -> pd.Series:
    """Annualised realised vol over sessions t+1..t+h, aligned to t.

    ALIGNMENT (asserted in tests): the value at t uses returns strictly AFTER t,
    because it is compared with an implied vol struck at t's close. NaN where
    fewer than h forward returns exist; never filled."""
    sq = np.log1p(ret_total) ** 2
    fwd = sq[::-1].rolling(h, min_periods=h).sum()[::-1].shift(-1)
    return np.sqrt(252.0 / h * fwd)


def load_rate() -> pd.Series:
    if not RATE_PATH.exists():
        raise FileNotFoundError(f"{RATE_PATH} missing: run "
                                f"python3 scripts/gamma/fetch_fred.py DGS1MO --out {RATE_PATH}")
    r = pd.read_parquet(RATE_PATH)
    return r.set_index("date")["value"].sort_index() / 100.0


def load_tlt() -> pd.DataFrame:
    p = pd.read_parquet(ETF_PANEL)
    s = p[p.ticker == SYM].set_index("date").sort_index()
    if s.empty:
        raise ValueError(f"{SYM} not in {ETF_PANEL}")
    return s


def build() -> pd.DataFrame:
    files = sorted(CACHE.glob(f"{SYM}_*_close.parquet"))
    if not files:
        raise FileNotFoundError(f"no cached ticks under {CACHE}: run `extract` first")
    agg = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    agg["d"] = pd.to_datetime(agg["d"])
    agg["expiry"] = pd.to_datetime(agg["expiry"])
    agg["px"] = agg["px_med"]
    tlt = load_tlt()
    close = tlt["close"]
    rv = forward_rv(tlt["ret_total"])
    rates = load_rate()
    rows, skipped = [], {"no_close": 0, "no_rate": 0, "no_constant_maturity": 0}
    for d, g in agg.groupby("d"):
        if d not in close.index or pd.isna(close.get(d)):
            skipped["no_close"] += 1
            continue
        rr = rates.loc[:d]                     # last published on or before d
        if rr.empty:
            skipped["no_rate"] += 1
            continue
        assert rr.index[-1] <= d               # no later rate reaches day d
        res = atm_for_session(g, float(close[d]), float(rr.iloc[-1]))
        if res is None:
            skipped["no_constant_maturity"] += 1
            continue
        rows.append({"date": d, "iv30": res[0], "dte_near": res[1], "dte_next": res[2],
                     "F": res[3], "S": float(close[d]), "rv_fwd21": rv.get(d, np.nan)})
    df = pd.DataFrame(rows).set_index("date")
    df.attrs["skipped"] = skipped
    df.attrs["sessions_with_prints"] = int(agg["d"].nunique())
    print(f"{SYM}: sessions with close-window prints {agg['d'].nunique()}, built {len(df)}, "
          f"skipped {skipped}, {df.index.min().date()}..{df.index.max().date()}; "
          f"etf_panel last {tlt.index.max().date()}, DGS1MO last {rates.index.max().date()}")
    INPUTS.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT)
    print(f"[written] {OUT}")
    return df


def volume() -> pd.DataFrame:
    """Contracts traded per session from the cached R2 ticks: a liquidity
    DESCRIPTION across the whole tick history, set beside the one-day chain
    snapshots (`option_chain_snapshot.py`). Sums of trade sizes; no price, no
    strike and no P&L enter it."""
    files = sorted(CACHE.glob(f"{SYM}_*_dayvol.parquet"))
    if not files:
        raise FileNotFoundError(f"no cached day volumes under {CACHE}: run `extract` first")
    v = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    v["d"] = pd.to_datetime(v["d"])
    v = v.groupby("d")[["contracts_all", "contracts_single_leg", "prints"]].sum()
    by = v.groupby(v.index.year)["contracts_all"].describe(percentiles=[.25, .5, .75])
    print(f"{SYM} option contracts per session, R2 ticks {v.index.min().date()}..{v.index.max().date()} "
          f"({len(v)} sessions)")
    print(by[["count", "25%", "50%", "75%", "max"]].round(0).to_string())
    a = v["contracts_all"]
    print(f"all sessions: median {a.median():,.0f}, IQR {a.quantile(.25):,.0f}..{a.quantile(.75):,.0f}; "
          f"single-leg share of contracts {v.contracts_single_leg.sum()/a.sum():.1%}")
    return v


def volume_check(day: str, top: int = 100) -> None:
    """Is R2 complete? Per-contract volume on one session from R2 against
    Alpaca's daily option bars for the same contracts (GET only, CEF paper
    key; credentials never printed). Run on 2026-07-09 (2026-10-11): the top
    100 contracts summed 534,430 in R2 and 539,066 at Alpaca, median ratio
    1.002 -- so a low R2 daily volume is the market, not missing ticks."""
    from src.data import r2
    from quantt.broker import alpaca_probe as ap
    con = r2.connect()
    con.execute("SET TimeZone='America/New_York'")
    p = r2.options_path(SYM, day[:7])
    v = r2.q(con, f"select osi, sum(size) vol from read_parquet('{p}') "
                  f"where cast(ts as date) = DATE '{day}' group by 1 order by vol desc")
    env_path = Path(os.environ["QUANTT_ENV_FILE"]) if os.environ.get("QUANTT_ENV_FILE") else ap.ENV_FILE
    kid, sec = ap.load_credentials("cef", ap.read_env_file(env_path))
    s = ap._session(kid, sec)
    del kid, sec
    syms = [o.replace("O:", "") for o in v.osi.head(top)]
    r = s.get("https://data.alpaca.markets/v1beta1/options/bars",
              params={"symbols": ",".join(syms), "timeframe": "1Day", "start": day,
                      "end": day, "limit": 1000}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Alpaca HTTP {r.status_code}: {r.text[:200]}")
    bars = r.json().get("bars", {})
    a = pd.Series({k: b[0]["v"] for k, b in bars.items() if b}, dtype=float)
    rr = v.assign(sym=v.osi.str.replace("O:", "")).set_index("sym")["vol"].head(top)
    x = pd.concat([rr.rename("r2"), a.rename("alpaca")], axis=1)
    print(f"{SYM} {day}: R2 all contracts {int(v.vol.sum()):,} over {len(v)} contracts; top {top}: "
          f"R2 {int(x.r2.sum()):,} vs Alpaca {int(x.alpaca.sum()):,} ({x.alpaca.notna().sum()} with "
          f"bars), median per-contract ratio Alpaca/R2 {(x.alpaca / x.r2).median():.4f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["extract", "build", "volume", "volume-check"])
    ap.add_argument("--day", help="volume-check: the session to compare (YYYY-MM-DD)")
    a = ap.parse_args()
    if a.step == "extract":
        if not os.environ.get("QUANTT_ENV_FILE") and not (REPO / "config/.env").exists():
            raise SystemExit("R2 credentials: set QUANTT_ENV_FILE to the absolute env-file path")
        extract()
    elif a.step == "build":
        build()
    elif a.step == "volume":
        volume()
    else:
        if not a.day:
            raise SystemExit("volume-check needs --day YYYY-MM-DD")
        volume_check(a.day)
    return 0


if __name__ == "__main__":
    sys.exit(main())
