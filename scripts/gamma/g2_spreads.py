"""G2(a)'s spread inputs for TLT options, from free data only (descriptive, 0 trials).

    export QUANTT_ENV_FILE=/abs/path/to/config/.env      # R2 + Alpaca CEF paper key; never printed
    python3 scripts/gamma/g2_spreads.py extract            # R2 trade prints -> per-month cache (read-only)
    python3 scripts/gamma/g2_spreads.py minute-bars        # TLT 1-min SIP bars from Alpaca (GET only)
    python3 scripts/gamma/g2_spreads.py roll               # Roll (1984) effective spread by month and leg
    python3 scripts/gamma/g2_spreads.py coverage           # which month-end sessions R2 is missing
    python3 scripts/gamma/g2_spreads.py underlying         # TLT stock snapshot (GET), just before
    python3 scripts/gamma/option_chain_snapshot.py alpaca --out-dir results/gamma/_cache_option_chains TLT
    python3 scripts/gamma/g2_spreads.py indicative         # Alpaca indicative snapshots -> leg widths

WHY THIS EXISTS
---------------
Gate G2 (`results/cef/RESEARCH_PLAN_2026-10-09.md` §2) asks whether the TLT
variance premium survives the cost of a four-leg defined-risk structure. Plan
item 0.10 wanted 20 live sessions of regular-hours NBBO; OPRA was refused and on
2026-10-12 the team lead ruled **no paid options data**, with a historical
spread series replacing the 20 sessions and 2023+ spreads usable as COSTS
(return statistics on 2023+ stay sealed) (`docs/SYSTEM.md` §5). So there are
two free spread inputs, and neither is an NBBO:

1. **R2 TLT option TRADE prints, 2023-11..2026-07** (no quotes). The effective
   spread is estimated from trades alone with **Roll (1984)**: if trades bounce
   between bid and ask around an efficient price, consecutive price changes are
   negatively autocorrelated and s = 2*sqrt(-cov(dp_t, dp_t-1)).
2. **Alpaca's free `indicative` option feed**, snapshotted in regular hours. Alpaca
   says it "is a free derivative of the original OPRA feed" and "the quotes are
   not actual OPRA quotes, they're just indicative derivatives" [V, Alpaca
   historical-option-data docs, read 2026-10-12]. Treated as indicative only.

THE ESTIMATOR AND ITS BIASES (stated before any number is read)
---------------------------------------------------------------
* **Roll is biased DOWN when order flow persists.** With trade signs following a
  Markov chain whose sign autocorrelation is rho, cov(dp_t, dp_t-1) =
  -(s/2)^2 (1-rho)^2, so Roll returns s(1-rho), not s (derivation in
  `roll_bias_factor`; the serially-dependent case is Choi, Salandro & Shastri
  (1988)). Option sweeps (ISO prints across venues) are persistent flow. Prints
  sharing a contract and a timestamp are therefore COLLAPSED to one trade at
  their volume-weighted price before any difference is taken.
* **A persistence-corrected Roll** divides by (1 - rho_hat), with rho_hat the
  first-order autocorrelation of tick-test signs (Lee & Ready 1991's tick rule).
  The tick rule gives a zero-tick trade the previous trade's sign, which
  OVERSTATES persistence, so the corrected figure is biased UP. It is reported as
  the trade-based upper estimate, never as the point estimate.
* **The underlying moves between trades.** That adds variance to dp but, with
  serially uncorrelated underlying returns, no expected covariance; it makes a
  contract-day Roll noisy and often undefined (positive covariance). So products
  are POOLED within a month and a leg bucket before the square root is taken;
  undefined pools are counted, never filled.
* **A delta-adjusted Roll** (`roll_adj`) subtracts delta x the TLT move between
  the two trades (1-minute SIP VWAPs from Alpaca) before taking the covariance.
  This is OUR adaptation for options (Hasbrouck's Gibbs versions of the Roll
  model add a market factor in the same spirit; the exact form in Hasbrouck
  (2009) was not read: [U]). It is the series the gate uses.
  **Its bias direction is [U] (corrected 2026-10-13).** This docstring said "it
  removes noise, not bias: it is still biased DOWN by persistence". A review
  found the adjusted estimate ABOVE plain Roll in most months where both are
  defined (`g2_gate.roll_comparison`: 20 of 24 ATM, 24 of 29 call-wing, 19 of
  25 put-wing; median ratios 1.36 / 1.11 / 1.25), which noise removal alone
  would not do. One candidate cause [U]: the minute-VWAP stands in for TLT's
  price at the trade, and that stand-in's error enters dp with negative
  autocovariance, which Roll reads as spread. Persistence still pulls it down;
  the net direction is not known. If it is biased up, the upper bound built on
  it is more conservative, not less.
* **Trades inside the spread** (price-improvement auctions, crosses) are kept: the
  effective spread is what customers actually paid, which is the cost we would pay.
* Multi-leg and stock-option prints are DROPPED (a spread leg prints at a
  package-derived price). The condition-code map is the Polygon/Massive option
  table as `tlt_atm_iv.py` uses it: **[U]**, not re-verified.

LEG BUCKETS (declared from the structure, not from results)
-----------------------------------------------------------
The declared structure (`g2_gate.py`) is Cboe's BFLY rule applied to TLT: short
the monthly at-the-money put and call, long the 5%-out-of-the-money put and call.
So the buckets are: expiries 20..45 calendar days out (a monthly cycle), and
moneyness K/S_prev in [0.99, 1.01] (ATM), [0.93, 0.97] (put wing, puts only),
[1.03, 1.07] (call wing, calls only). S_prev is TLT's unadjusted close of the
PREVIOUS session (`data/rv/etf_panel.parquet`), so no same-day price classifies
a print. Regular hours only, 09:30-16:00 ET.

R2 COVERAGE
-----------
`coverage` lists, per month, whether R2 holds the month's last NYSE session
(calendar: TLT's own sessions in `etf_panel`). Month-end gaps do not bias a
spread estimate unless month-end spreads differ; they are reported, not filled.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SYM = "TLT"
FIRST_MONTH, LAST_MONTH = "2023-11", "2026-07"           # R2 coverage, R2_CATALOG.md
CACHE = REPO / "results/gamma/_cache_g2_trades"
SNAP_DIR = REPO / "results/gamma/_cache_option_chains"
ETF_PANEL = REPO / "data/rv/etf_panel.parquet"
KEEP = ("209", "210", "219", "227", "228", "229", "230", "231")   # single-leg; tlt_atm_iv.KEEP
DTE_EXTRACT = (10, 60)
DTE_BUCKET = (20, 45)
BUCKETS = {                         # name: (lo, hi, option type or None for both)
    "atm": (0.99, 1.01, None),
    "put_wing": (0.93, 0.97, "P"),
    "call_wing": (1.03, 1.07, "C"),
}
OSI = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def months(a: str, b: str):
    p = pd.Period(a, "M")
    while p <= pd.Period(b, "M"):
        yield str(p)
        p += 1


# --------------------------------------------------------------------------- extract

def extract(first: str = FIRST_MONTH, last: str = LAST_MONTH) -> None:
    """Read-only DuckDB queries against R2; one cached parquet per month."""
    from src.data import r2
    CACHE.mkdir(parents=True, exist_ok=True)
    con = r2.connect()
    con.execute("SET TimeZone='America/New_York'")       # session dates and HH:MM in ET
    keep = ",".join(f"'{c}'" for c in KEEP)
    for m in months(first, last):
        out = CACHE / f"{SYM}_{m}_trades.parquet"
        if out.exists():
            continue
        t0 = time.time()
        p = r2.options_path(SYM, m)
        df = r2.q(con, f"""
            SELECT CAST(ts AS DATE) AS d, epoch_ms(ts) AS ms, expiry, opt_type, strike,
                   price, size, exchange, conditions
            FROM read_parquet('{p}')
            WHERE strftime(ts, '%H:%M') >= '09:30' AND strftime(ts, '%H:%M') < '16:00'
              AND conditions IN ({keep}) AND price > 0 AND size > 0
              AND expiry >= CAST(ts AS DATE) + {DTE_EXTRACT[0]}
              AND expiry <= CAST(ts AS DATE) + {DTE_EXTRACT[1]}
            ORDER BY expiry, opt_type, strike, ms""")
        df.to_parquet(out)
        print(f"{SYM} {m}: {len(df):,} single-leg regular-hours prints, "
              f"{df['d'].nunique()} sessions ({time.time()-t0:.1f}s)", flush=True)


# --------------------------------------------------------------------------- Roll

def roll_bias_factor(rho: float) -> float:
    """What plain Roll returns as a multiple of the true spread when trade signs
    follow a symmetric Markov chain with first-order autocorrelation `rho`.

    p_t = m_t + (s/2) q_t, q_t = +-1, corr(q_t, q_t-k) = rho^k. Then
    cov(dp_t, dp_t-1) = (s/2)^2 E[(q_t - q_t-1)(q_t-1 - q_t-2)]
                      = (s/2)^2 (rho - rho^2 - 1 + rho) = -(s/2)^2 (1 - rho)^2,
    so 2 sqrt(-cov) = s (1 - rho). rho = 0 is Roll (1984)'s iid case."""
    if not -1.0 < rho < 1.0:
        raise ValueError(f"rho {rho} outside (-1, 1): the Markov sign model is degenerate")
    return 1.0 - rho


def collapse_same_time(g: pd.DataFrame) -> pd.DataFrame:
    """One trade per (contract, millisecond) at its volume-weighted price: a sweep
    printed across venues is one order, and leaving it as several prints would
    manufacture persistence (Roll biased down) and zero price changes."""
    g = g.assign(pv=g["price"] * g["size"])
    c = g.groupby(["d", "expiry", "opt_type", "strike", "ms"], sort=True)[["pv", "size"]].sum()
    c["price"] = c["pv"] / c["size"]
    return c.drop(columns="pv").reset_index()


def tick_signs(p: np.ndarray) -> np.ndarray:
    """Lee-Ready tick rule on one contract-day's trade prices: +1 uptick, -1
    downtick, a zero tick takes the previous sign; the first trade (and any
    leading zero ticks) has no sign (0) and is excluded by the caller."""
    s = np.zeros(len(p), dtype=int)
    for i in range(1, len(p)):
        dp = p[i] - p[i - 1]
        s[i] = 1 if dp > 1e-12 else (-1 if dp < -1e-12 else s[i - 1])
    return s


def classify(tr: pd.DataFrame, s_prev: pd.Series) -> pd.DataFrame:
    """Attach the previous session's TLT close and the leg bucket. A session with
    no previous close in the panel is dropped and counted (never back-filled)."""
    tr = tr.copy()
    tr["d"] = pd.to_datetime(tr["d"])
    tr["expiry"] = pd.to_datetime(tr["expiry"])
    tr["S_prev"] = tr["d"].map(s_prev)
    tr["dte"] = (tr["expiry"] - tr["d"]).dt.days
    tr["mny"] = tr["strike"] / tr["S_prev"]
    tr["bucket"] = None
    for name, (lo, hi, cp) in BUCKETS.items():
        m = tr["mny"].between(lo, hi) & tr["dte"].between(*DTE_BUCKET)
        if cp is not None:
            m &= tr["opt_type"].eq(cp)
        tr.loc[m, "bucket"] = name
    return tr


def roll_pool(tr: pd.DataFrame) -> dict:
    """Pooled Roll for one (month, bucket): products of consecutive collapsed
    price changes within each contract-day, averaged over every pair in the pool.
    Also: the tick-sign autocorrelation, the persistence-corrected Roll, the mean
    price (for % of price) and the counts. Undefined (cov >= 0) is reported as NaN
    with its count, never replaced."""
    prods, sgn_a, sgn_b, px = [], [], [], []
    for _, g in tr.groupby(["d", "expiry", "opt_type", "strike"], sort=False):
        p = g["price"].to_numpy()
        if len(p) < 3:
            continue
        dp = np.diff(p)
        prods.append(dp[1:] * dp[:-1])
        s = tick_signs(p)
        ok = (s[1:] != 0) & (s[:-1] != 0)
        sgn_a.append(s[1:][ok])
        sgn_b.append(s[:-1][ok])
        px.append(p)
    if not prods:
        return dict(pairs=0, roll=np.nan, rho=np.nan, roll_corr=np.nan, mean_px=np.nan)
    pr = np.concatenate(prods)
    cov = pr.mean()
    roll = 2.0 * math.sqrt(-cov) if cov < 0 else np.nan
    a, b = np.concatenate(sgn_a), np.concatenate(sgn_b)
    rho = float(np.corrcoef(a, b)[0, 1]) if len(a) > 10 and a.std() > 0 and b.std() > 0 else np.nan
    roll_corr = roll / roll_bias_factor(rho) if (np.isfinite(roll) and np.isfinite(rho)
                                                  and -1 < rho < 1) else np.nan
    return dict(pairs=len(pr), cov=cov, roll=roll, rho=rho, roll_corr=roll_corr,
                mean_px=float(np.concatenate(px).mean()))


def load_s_prev() -> pd.Series:
    """TLT unadjusted close of the PREVIOUS session, indexed by session date."""
    p = pd.read_parquet(ETF_PANEL)
    s = p[p.ticker == SYM].set_index("date").sort_index()["close"]
    if s.empty:
        raise ValueError(f"{SYM} not in {ETF_PANEL}")
    return s.shift(1).dropna()


def roll_table() -> pd.DataFrame:
    files = sorted(CACHE.glob(f"{SYM}_*_trades.parquet"))
    if not files:
        raise FileNotFoundError(f"no cached trades under {CACHE}: run `extract` first")
    s_prev = load_s_prev()
    if not MINUTE_BARS.exists():
        raise FileNotFoundError(f"{MINUTE_BARS} missing: run `minute-bars` first")
    bars = pd.read_parquet(MINUTE_BARS)
    if not VXTLT_CACHE.exists():
        raise FileNotFoundError(f"{VXTLT_CACHE} missing: run scripts/gamma/fetch_cboe_vol_indices.py "
                                f"--indices VXTLT --out {VXTLT_CACHE}")
    from scripts.gamma import fetch_cboe_vol_indices as cboe
    vx_prev = (cboe.series(pd.read_parquet(VXTLT_CACHE), "VXTLT") / 100.0).shift(1).dropna()
    rows, dropped, no_bar = [], 0, 0
    for f in files:
        m = f.stem.split("_")[1]
        tr = pd.read_parquet(f)
        tr = collapse_same_time(tr)
        tr = classify(tr, s_prev)
        dropped += int(tr["S_prev"].isna().sum())
        tr = tr[tr["bucket"].notna()]
        tr = attach_underlying(tr, bars, vx_prev)
        no_bar += int(tr["S_min"].isna().sum() + tr["delta"].isna().sum())
        for b, g in tr.groupby("bucket"):
            g = g.sort_values(["d", "expiry", "opt_type", "strike", "ms"])
            r = roll_pool(g)
            ra = roll_pool_adjusted(g)
            rows.append(dict(month=m, bucket=b, sessions=g["d"].nunique(), trades=len(g), **r, **ra))
    t = pd.DataFrame(rows)
    t.attrs["dropped_no_prev_close"] = dropped
    t.attrs["no_minute_bar_or_delta"] = no_bar
    return t


def summarise_roll(t: pd.DataFrame) -> pd.DataFrame:
    out = []
    for b, g in t.groupby("bucket"):
        d = g.dropna(subset=["roll"])
        out.append(dict(bucket=b, months=len(g), months_defined=len(d),
                        roll_median=d["roll"].median(), roll_p90=d["roll"].quantile(.9),
                        roll_max=d["roll"].max(), rho_median=g["rho"].median(),
                        corr_median=d["roll_corr"].median(), corr_p90=d["roll_corr"].quantile(.9),
                        corr_max=d["roll_corr"].max(),
                        adj_defined=int(g["roll_adj"].notna().sum()),
                        adj_median=g["roll_adj"].median(), adj_p90=g["roll_adj"].quantile(.9),
                        adj_max=g["roll_adj"].max(),
                        adj_corr_p90=(g["roll_adj"] / (1 - g["rho"])).quantile(.9),
                        mean_px_median=g["mean_px"].median(),
                        pairs_median=g["pairs"].median()))
    return pd.DataFrame(out).set_index("bucket")


# --------------------------------------------------------------------------- delta-adjusted Roll

MINUTE_BARS = REPO / "results/gamma/_cache_inputs/tlt_minute_bars.parquet"
VXTLT_CACHE = REPO / "results/gamma/_cache_inputs/cboe_vxtlt.parquet"


def fetch_minute_bars(first: str = "2023-11-01", last: str = "2026-07-10") -> pd.DataFrame:
    """TLT 1-minute SIP bars, raw, from Alpaca (read-only GET, CEF paper key).

    Used ONLY to take the underlying's move out of an option's trade-to-trade
    price change (the delta-adjusted Roll below). A day-old bar is SIP data
    older than 15 minutes, which the free plan serves."""
    from scripts.rv import alpaca_daily as ad
    client = ad.make_client()
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    rows = []
    params = {"symbols": SYM, "timeframe": "1Min", "feed": "sip", "adjustment": "raw",
              "start": ad._ny(a, 9), "end": ad._ny(b, 17), "limit": ad.BARS_LIMIT}
    for page in ad._paged(client, "/v2/stocks/bars", params, "bars"):
        for sym, items in page.items():
            if sym != SYM:
                raise ValueError(f"minute bars: {sym!r} returned, {SYM} requested")
            rows.extend({"t": x["t"], "vw": x["vw"], "c": x["c"], "v": x["v"]} for x in items)
    if not rows:
        raise ValueError(f"minute bars: nothing returned for {SYM} {first}..{last}")
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    if df["t"].duplicated().any():
        raise ValueError("minute bars: duplicate timestamps")
    MINUTE_BARS.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(MINUTE_BARS)
    print(f"[written] {MINUTE_BARS}: {len(df):,} bars {df.t.min()}..{df.t.max()}")
    return df


def bs_delta(S, K, T, sig, cp):
    """Black-Scholes delta, r = q = 0 (a hedge ratio for de-noising only)."""
    from scipy.stats import norm
    d1 = (np.log(S / K) + 0.5 * sig * sig * T) / (sig * np.sqrt(T))
    return norm.cdf(d1) if cp == "C" else norm.cdf(d1) - 1.0


def attach_underlying(tr: pd.DataFrame, bars: pd.DataFrame, vx_prev: pd.Series) -> pd.DataFrame:
    """Per trade: the VWAP of TLT's 1-minute bar containing it, and a BS delta at
    the previous session's close and the previous session's VXTLT (both known
    before the session). A trade whose minute has no TLT bar keeps NaN and is
    excluded from the adjusted pool, counted by the caller."""
    tr = tr.copy()
    minute = pd.to_datetime(tr["ms"], unit="ms", utc=True).dt.floor("min")
    vw = bars.set_index("t")["vw"]
    tr["S_min"] = minute.map(vw).to_numpy()
    sig = tr["d"].map(vx_prev).to_numpy()
    T = tr["dte"].to_numpy() / 365.0
    tr["delta"] = np.where(tr["opt_type"].eq("C"),
                           bs_delta(tr["S_prev"].to_numpy(), tr["strike"].to_numpy(), T, sig, "C"),
                           bs_delta(tr["S_prev"].to_numpy(), tr["strike"].to_numpy(), T, sig, "P"))
    return tr


def roll_pool_adjusted(tr: pd.DataFrame) -> dict:
    """Roll on dp_t - delta * dS_t: the underlying as a factor with its loading
    fixed at the option's delta rather than estimated (our adaptation). The variance
    the underlying adds is removed, so fewer pools come out undefined. It shares
    plain Roll's persistence bias (DOWN), but its NET bias direction is [U]
    (corrected 2026-10-13; the module docstring): it exceeds plain Roll in most
    months, possibly because the minute VWAP is not the price at the trade."""
    prods = []
    for _, g in tr.groupby(["d", "expiry", "opt_type", "strike"], sort=False):
        g = g.dropna(subset=["S_min", "delta"])
        if len(g) < 3:
            continue
        dp = np.diff(g["price"].to_numpy()) - g["delta"].to_numpy()[1:] * np.diff(g["S_min"].to_numpy())
        prods.append(dp[1:] * dp[:-1])
    if not prods:
        return dict(pairs_adj=0, roll_adj=np.nan)
    pr = np.concatenate(prods)
    cov = pr.mean()
    return dict(pairs_adj=len(pr), cov_adj=cov, roll_adj=2.0 * math.sqrt(-cov) if cov < 0 else np.nan)


# --------------------------------------------------------------------------- coverage

def coverage() -> pd.DataFrame:
    """Per month: R2 sessions present vs TLT sessions in etf_panel, and whether the
    month's last session is present. Reads the cache (extracted prints)."""
    p = pd.read_parquet(ETF_PANEL)
    cal = pd.to_datetime(p[p.ticker == SYM]["date"]).sort_values()
    rows = []
    for f in sorted(CACHE.glob(f"{SYM}_*_trades.parquet")):
        m = f.stem.split("_")[1]
        have = set(pd.to_datetime(pd.read_parquet(f, columns=["d"])["d"]).unique())
        want = cal[cal.dt.to_period("M") == pd.Period(m, "M")]
        if want.empty:
            raise ValueError(f"{m}: no TLT sessions in {ETF_PANEL}; the calendar ends early")
        missing = [d.date() for d in want if d not in have]
        rows.append(dict(month=m, sessions=len(want), r2_sessions=len(have),
                         last_session=want.iloc[-1].date(),
                         last_present=want.iloc[-1] in have, missing=missing))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- indicative

def _bs_vega(S, K, T, sig, r=0.0, q=0.0):
    """Black-Scholes vega per ONE vol point (0.01), per share."""
    from scipy.stats import norm
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / v
    return S * math.exp(-q * T) * norm.pdf(d1) * math.sqrt(T) / 100.0


def snapshot_underlying(snap_dir: Path = SNAP_DIR) -> Path:
    """Read-only GET of TLT's stock snapshot (IEX feed, free) beside an option
    snapshot, so `indicative` can place strikes against a same-minute spot.
    Run it immediately BEFORE `option_chain_snapshot.py alpaca`: `indicative`
    pairs each chain with the latest stock snapshot at or before it.
    (On 2026-10-12 the same GET ran from a scratch helper; this is that helper.)"""
    from quantt.broker import alpaca_probe as ap
    env_path = Path(os.environ["QUANTT_ENV_FILE"]) if os.environ.get("QUANTT_ENV_FILE") \
        else ap.ENV_FILE
    kid, sec = ap.load_credentials("cef", ap.read_env_file(env_path))
    sess = ap._session(kid, sec)
    del kid, sec
    r = sess.get(f"https://data.alpaca.markets/v2/stocks/{SYM}/snapshot",
                 params={"feed": "iex"}, timeout=30)                      # GET only
    if r.status_code != 200:
        raise RuntimeError(f"{SYM} stock snapshot: Alpaca HTTP {r.status_code}: {r.text[:200]}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir.mkdir(parents=True, exist_ok=True)
    out = snap_dir / f"{SYM}stock_iex_{stamp}.json"
    out.write_text(r.text)
    print(f"[written] {out}")
    return out


def indicative(snap_dir: Path = SNAP_DIR) -> pd.DataFrame:
    """Leg widths of the declared structure in each Alpaca indicative snapshot.

    Pairs each option snapshot with the TLT stock snapshot taken just before it
    (same loop). Expiry: the listed monthly (third-Friday) expiry nearest 30 days
    out. Strikes: nearest listed to S (ATM call and put), to 0.95 S (put wing)
    and 1.05 S (call wing). Width = ask - bid of the latest indicative quote.
    Vega per vol point from the snapshot's own greeks where present, else NaN
    (never a model value in its place); the quote's own timestamp is reported."""
    opts = sorted(snap_dir.glob(f"{SYM}_alpaca_*.json"))
    stocks = sorted(snap_dir.glob(f"{SYM}stock_iex_*.json"))
    if not opts:
        raise FileNotFoundError(f"no {SYM}_alpaca_*.json under {snap_dir}")
    rows, no_spot = [], []
    for po in opts:
        stamp = po.stem.split("_")[-1]
        prior = [s for s in stocks if s.stem.split("_")[-1] <= stamp]
        if not prior:
            no_spot.append(stamp)                      # reported below; no spot, no row
            continue
        st = json.loads(prior[-1].read_text())
        q = st["latestQuote"]
        S = (q["ap"] + q["bp"]) / 2
        t_snap = dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        today = t_snap.astimezone(dt.timezone(dt.timedelta(hours=-4))).date()
        d = json.loads(po.read_text())
        chain = []
        for k, x in d.items():
            m = OSI.match(k)
            if not m:
                continue
            e = dt.datetime.strptime(m.group(2), "%y%m%d").date()
            chain.append(dict(sym=k, e=e, cp=m.group(3), K=int(m.group(4)) / 1000, x=x))
        monthlies = sorted({c["e"] for c in chain if c["e"].weekday() == 4 and 15 <= c["e"].day <= 21})
        e30 = min(monthlies, key=lambda e: abs((e - today).days - 30))
        legs_def = {"atm_call": ("C", S), "atm_put": ("P", S),
                    "put_wing": ("P", 0.95 * S), "call_wing": ("C", 1.05 * S)}
        for leg, (cp, target) in legs_def.items():
            cands = [c for c in chain if c["e"] == e30 and c["cp"] == cp]
            c = min(cands, key=lambda c: abs(c["K"] - target))
            lq = c["x"].get("latestQuote") or {}
            bid, ask = lq.get("bp"), lq.get("ap")
            g = c["x"].get("greeks") or {}
            rows.append(dict(snapshot=stamp, spot=S, expiry=e30, dte=(e30 - today).days, leg=leg,
                             K=c["K"], bid=bid, ask=ask,
                             width=(ask - bid) if (bid is not None and ask is not None) else np.nan,
                             mid=(ask + bid) / 2 if (bid is not None and ask is not None) else np.nan,
                             vega=g.get("vega", np.nan), iv=c["x"].get("impliedVolatility", np.nan),
                             quote_t=lq.get("t", "")[:19], bx=lq.get("bx"), ax=lq.get("ax")))
    if no_spot:
        print(f"option snapshots with no TLT stock snapshot at or before them (not used): {no_spot}")
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["extract", "minute-bars", "roll", "coverage", "underlying",
                                     "indicative"])
    ap.add_argument("--out", help="roll/indicative: also write the table to this parquet")
    a = ap.parse_args()
    pd.set_option("display.width", 200)
    if a.step == "extract":
        if not os.environ.get("QUANTT_ENV_FILE") and not (REPO / "config/.env").exists():
            raise SystemExit("R2 credentials: set QUANTT_ENV_FILE to the absolute env-file path")
        extract()
    elif a.step == "minute-bars":
        fetch_minute_bars()
    elif a.step == "underlying":
        snapshot_underlying()
    elif a.step == "roll":
        t = roll_table()
        print(f"dropped prints with no previous TLT close: {t.attrs['dropped_no_prev_close']}; "
              f"bucketed prints with no TLT minute bar or delta (excluded from the adjusted "
              f"pool only): {t.attrs['no_minute_bar_or_delta']}")
        print(t.round(5).to_string(index=False))
        print("\nby bucket, across months ($ per contract-share):")
        print(summarise_roll(t).round(4).to_string())
        if a.out:
            t.to_parquet(a.out)
    elif a.step == "coverage":
        c = coverage()
        print(c.drop(columns="missing").to_string(index=False))
        print(f"\nmonths whose last session is missing: {int((~c.last_present).sum())} of {len(c)}")
        for _, r in c.iterrows():
            if r["missing"]:
                print(f"  {r['month']}: missing {', '.join(str(x) for x in r['missing'])}")
    else:
        t = indicative()
        print(t.to_string(index=False))
        if a.out:
            t.to_parquet(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
