"""Gate G2 for the standalone short TLT variance premium, on free data (0 trials).

    export QUANTT_ENV_FILE=/abs/path/to/config/.env      # nothing here reads it; the inputs do
    C=results/gamma/_cache_inputs
    python3 scripts/gamma/g2_gate.py premium --roll $C/g2_roll.parquet --indicative $C/g2_indicative.parquet
    python3 scripts/gamma/g2_gate.py replay  --vol-cap 0.20

Descriptive and zero-trial: GAMMA stays at 0. It does NOT run trial G1, forms no
2023+ return statistic (true since 2026-10-13: until then one G2(a) window ran
on January 2023 returns; see `fit_sample`), and chooses no parameter by looking
at an outcome. The
gate is `results/cef/RESEARCH_PLAN_2026-10-09.md` §2, row G2:

    (a) a VXTLT 2004-22 variance-swap proxy net of the 4-leg spread is positive;
    (b) a replay of 2008 and 2020 for a defined-risk structure stays inside the
        vol cap;
    (c) correlation with the book is about 0 (measured 2026-10-11; restated in
        the note, not re-run here).

The team lead ruled on 2026-10-12 (`docs/SYSTEM.md` §5): no paid options data;
G2 runs as a CONSERVATIVE gate, "an upper-bound spread and a bounded-loss crash
replay"; 2023+ TLT option spreads may be used as costs, 2023+ returns stay sealed.

THE DECLARED STRUCTURE (from the literature; nothing swept)
-----------------------------------------------------------
SCALING §7 names "iron flies and condors" and no strikes. The rule taken is
Cboe's S&P 500 Iron Butterfly Index (BFLY): "Sells a monthly at-the-money (ATM)
SPX put and SPX call option" and "Buys a monthly 5% OTM SPX put option that
expires at the next standard expiration"; the call wing likewise; rolled monthly
[S, Cboe Insights "Volatility Management with Cboe's BFLY and CNDR Indices",
read 2026-10-12]. Applied to TLT: enter at the close of each standard monthly
expiration day (third Friday, or the last TLT session before it), short the ATM
put and call at K0 = S, long the put at 0.95 K0 and the call at 1.05 K0, expiring
at the next standard expiration, held to expiry. Strikes are exact, not rounded
to TLT's listed grid ($0.50-$1, under 1.3% of S). The second published rule, Cboe's
Iron Condor Index (CNDR: short ~0.20-delta put and call, long ~0.05-delta), is
replayed beside it so a pre-registration cannot later pick whichever looks
better; deltas use VXTLT at the session before entry.

G2(a): THE PREMIUM NET OF A SPREAD
----------------------------------
Gross (re-run here from `vrp_summary.py`'s own functions): IV - RV in vol points
and the short variance-swap proxy IV^2 - RV^2 in %^2, VXTLT 2004-22,
non-overlapping 21-session windows.

EVERY WINDOW ENDS BEFORE 2023 (corrected 2026-10-13). Until 2026-10-13 the
headline sample took IV DATES in 2004-22, so its last window (IV date
2022-12-27) ran on January 2023 returns, which are the sealed GAMMA holdout; a
"strict" variant was printed beside it. An independent review caught it. Now
`fit_sample` cuts TLT's returns at the last session before 2023 BEFORE the
forward realised vol is computed, so a window that would need a 2023 return
is NaN and dropped, never formed; it asserts that every window ends before
2023, and a test proves the sample does not change when 2023 returns do. The
strict sample is the only sample.

A cost in dollars per structure becomes VOL POINTS by dividing by the
structure's net vega (short ATM vegas minus wing vegas), Black-Scholes at
sigma = VXTLT_t, T = 30/365, per fit date t; and VARIANCE POINTS by 2 IV_t x the
vol-point cost (dK^2 = 2K dK: a variance swap of vega notional N has variance
notional N/2K). Costs measured in dollars on 2023+ prices are carried as a
FRACTION OF THE UNDERLYING (dollars / TLT price of the month they were measured
in), so a fit date with TLT at $120 is charged proportionally, not the 2023+
dollar figure.

Cost rows (each labelled; the gate reads the UPPER BOUND):
* point, held to expiry: half the delta-adjusted Roll effective spread on each
  leg, entry only (the median month);
* point, round trip: the full effective spread on each leg;
* indicative, held to expiry / round trip: Alpaca indicative quoted width
  (median of the regular-hours snapshots) halved / full;
* **UPPER BOUND (declared)**: on each leg, the larger of the indicative median
  width and the 90th-percentile month of the persistence-corrected delta-adjusted
  Roll (`g2_spreads.py`; the persistence correction is biased UP), paid in FULL
  on all four legs, i.e. a round trip at the touch for a structure that is meant
  to be held to expiry. Three conservative choices stacked;
* the two relaxations (added 2026-10-13, after a review found the note's "relaxing
  either convention brings the net to zero or above" had no reproducer): the
  upper-bound widths held to expiry (half width), and the median month in place
  of the 90th percentile (full width). Each relaxes one convention and keeps
  the other two;
* plain Roll beside the delta-adjusted one (added 2026-10-13): the delta
  adjustment was described as "removes noise, not bias", but the adjusted
  estimate exceeds plain Roll in most months (`roll_comparison`), so the
  direction of its bias is [U] and the plain-Roll point row is shown too;
* stress: the widest indicative quote seen per leg, full width.

Robustness (added 2026-10-13): the non-overlapping t takes start phase 0 only;
`phase_robustness` reports all 21 start phases and a Newey-West (20 lags) t on
the overlapping daily series, gross and net of the point and upper-bound costs.

The 5/15/30bp grid, translated: a one-way cost of 5/15/30bp of the UNDERLYING's
notional per leg, four legs, entry only (each leg trades once when held to
expiry), in vol points through the same net vega. This translation is ours, not
a desk convention; it is shown so the sign flip is visible.

G2(b): THE BOUNDED-LOSS REPLAY
------------------------------
A defined-risk structure loses at most wing width minus credit. With the credit
set to ZERO (conservative; no option price before 2023 is needed), the P&L of
one short fly at expiry is -min(|S_T - K0|, W), W = 0.05 K0, and only TLT's
unadjusted closes are used (`data/rv/etf_panel.parquet`; ordinary distributions
do not adjust listed strikes).

Sizing to the book's vol target (`VOL_TARGET` through `scripts/cef/spec.py`,
never a literal): at each entry, structures n_t so that the EX-ANTE annualised
standard deviation of the cycle P&L, sqrt(12) x sd(payoff), equals
VOL_TARGET x capital. sd(payoff) is the standard deviation of the zero-credit
payoff under a lognormal TLT over the cycle, with one of two declared vols, both
known strictly before entry (asserted):
  * I: VXTLT at the session before entry (the market's forward estimate);
  * R: TLT's trailing 63-session realised vol to the session before entry (the
    window the live sleeve uses for its own vol scaling, `cef_discount.py`).
The verdict needs BOTH to stay inside the cap.

The cap is the vol cap of `docs/SYSTEM.md` §5 (team lead 2026-09-08 and
2026-10-09: "derive the vol target, cap 20%"). It is not a spec key, so it is a
REQUIRED argument here (`--vol-cap`), never a default. Two realised readings per
window: the vol of the cycle P&L (sample sd, ddof=1, x sqrt(12)) and the same
NOT demeaned (rms x sqrt(12)), because equal full-wing losses have a small sd.

TWO PATH BOUNDS (corrected 2026-10-13). Until then this docstring and the note
claimed one "any-path bound", sqrt(12) x max(nW)/2, and said the fly "cannot
breach 20% on any path". A review showed it is not a bound on what is printed:
* the realised vol is a SAMPLE sd (ddof=1), and Popoviciu's sd <= range/2 holds
  for the population sd; the sample sd can exceed it by sqrt(n/(n-1)) (CNDR
  sized on VXTLT, Feb-Apr 2020: vol 10.3% against the old "bound" 10.2%);
* the not-demeaned measure is bounded only by sqrt(12) x max(nW), twice as high;
* "whatever the credit C" is true per cycle only: with a credit that varies by
  cycle the P&Ls of different cycles do not share one interval.
So two bounds are printed, both for the zero-credit replay, where every cycle's
P&L lies in [-max(nW), 0]:
  bound_sd  = sqrt(12) x max(nW)/2 x sqrt(n/(n-1))   (the ddof=1 vol)
  bound_rms = sqrt(12) x max(nW)                      (the not-demeaned vol;
                                                       holds for any credit too)
The gate reads the REALISED path. Where bound_rms exceeds the cap, any-path
safety is not established for the not-demeaned measure, and the output says so.
The spec's risk.halve_drawdown and risk.kill_drawdown are printed beside the
losses as context.

What this replay cannot see: daily mark-to-market inside a cycle (no option
prices), early assignment of a short American leg (TLT pays monthly), and pin
risk at expiry. A Black-Scholes daily mark at flat VXTLT is printed as a labelled
model cross-check only.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.cef import spec                                          # noqa: E402
from scripts.gamma import vrp_summary as vs                           # noqa: E402

VXTLT_CACHE = REPO / "results/gamma/_cache_inputs/cboe_vxtlt.parquet"
RATE_PATH = REPO / "results/gamma/_cache_inputs/fred_DGS1MO.parquet"
ETF_PANEL = REPO / "data/rv/etf_panel.parquet"
FIT = ("2004-01-01", "2022-12-31")
SEALED_FROM = pd.Timestamp("2023-01-01")   # 2023+ returns: the GAMMA holdout (docs/SYSTEM.md §5)
H = 21
T30 = 30 / 365.0
WING = 0.05                     # BFLY: 5% OTM wings (Cboe; module docstring)
CNDR_SHORT, CNDR_LONG = 0.20, 0.05
RV_WINDOW = 63                  # cef_discount.py: hist.tail(63) for its own vol scaling
CYCLES_PER_YEAR = 12
GRID_BP = (5, 15, 30)
WINDOWS = {"2008": ("2008-01-01", "2008-12-31"), "2008-09..2009-02": ("2008-09-01", "2009-02-28"),
           "2020": ("2020-01-01", "2020-12-31"), "2020-02..2020-04": ("2020-02-01", "2020-04-30")}


# --------------------------------------------------------------------------- option maths

def _norm():
    from scipy.stats import norm
    return norm


def bs_vega_per_pt(S, K, T, sig):
    """Black-Scholes vega per ONE vol point, per share, r = q = 0."""
    norm = _norm()
    S, K, sig = np.asarray(S, float), np.asarray(K, float), np.asarray(sig, float)
    v = sig * np.sqrt(T)
    d1 = (np.log(S / K) + 0.5 * v * v) / v
    return S * norm.pdf(d1) * np.sqrt(T) / 100.0


def fly_net_vega_over_S(sig, T=T30, wing=WING):
    """Net vega of the short iron fly per $1 of underlying, per vol point: two ATM
    legs minus the two wings (the long wings give vega back)."""
    S = 1.0
    atm = 2 * bs_vega_per_pt(S, S, T, sig)
    wings = bs_vega_per_pt(S, S * (1 - wing), T, sig) + bs_vega_per_pt(S, S * (1 + wing), T, sig)
    return atm - wings


def bs_price(S, K, T, sig, cp, r=0.0, q=0.0):
    norm = _norm()
    if T <= 0:
        return max(S - K, 0.0) if cp == "C" else max(K - S, 0.0)
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / v
    d2 = d1 - v
    if cp == "C":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def strike_for_delta(S, T, sig, target, cp):
    """The strike whose Black-Scholes delta (r = q = 0) is `target` (calls > 0,
    puts given as a positive magnitude). Closed form: d1 = N^-1(delta)."""
    norm = _norm()
    d1 = norm.ppf(target) if cp == "C" else -norm.ppf(target)
    return S * math.exp(-d1 * sig * math.sqrt(T) + 0.5 * sig * sig * T)


def fly_payoff(ST, K0, wing=WING):
    """What the SHORT iron fly owes at expiry, per share: min(|S_T - K0|, W).
    Short call K0 + short put K0 + long call (1+w)K0 + long put (1-w)K0."""
    W = wing * K0
    return np.minimum(np.abs(np.asarray(ST, float) - K0), W)


def condor_payoff(ST, kps, kpl, kcs, kcl):
    """What the SHORT iron condor owes at expiry, per share."""
    ST = np.asarray(ST, float)
    return (np.maximum(kps - ST, 0) - np.maximum(kpl - ST, 0)
            + np.maximum(ST - kcs, 0) - np.maximum(ST - kcl, 0))


_Z = np.linspace(-9.0, 9.0, 36_001)                 # dense grid on N(0,1)
_W = np.exp(-0.5 * _Z ** 2)
_W[[0, -1]] *= 0.5                                   # trapezoid end weights


def payoff_sd(payoff_fn, S, T, sig) -> float:
    """sd of a payoff under a driftless lognormal S_T.

    A dense trapezoid on the normal density, not Gauss-Hermite: the payoffs are
    piecewise linear with kinks at the strikes, where a 120-node Gauss-Hermite
    rule was measured 1.6% off a 2-million-path Monte Carlo (the test pins it)."""
    x, w = _Z, _W / _W.sum()
    ST = S * np.exp(-0.5 * sig * sig * T + sig * math.sqrt(T) * x)
    p = payoff_fn(ST)
    m = (w * p).sum()
    return float(math.sqrt(max((w * (p - m) ** 2).sum(), 0.0)))


# --------------------------------------------------------------------------- inputs

def load_tlt() -> pd.DataFrame:
    p = pd.read_parquet(ETF_PANEL)
    t = p[p.ticker == "TLT"].set_index("date").sort_index()
    if t.empty:
        raise ValueError(f"TLT not in {ETF_PANEL}")
    return t


def load_vxtlt() -> pd.Series:
    if not VXTLT_CACHE.exists():
        raise FileNotFoundError(f"{VXTLT_CACHE} missing: python3 scripts/gamma/fetch_cboe_vol_indices.py "
                                f"--indices VXTLT --out {VXTLT_CACHE}")
    return vs.load_iv(VXTLT_CACHE, "VXTLT")


def monthly_expiries(sessions: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Standard monthly expiration sessions: the third Friday, or the last
    session on or before it when the exchange is shut (e.g. Good Friday
    2008-03-21 -> 2008-03-20)."""
    sessions = pd.DatetimeIndex(sessions).sort_values()
    out = []
    for per in pd.period_range(sessions.min(), sessions.max(), freq="M"):
        first = per.start_time
        fri = first + pd.Timedelta(days=(4 - first.weekday()) % 7) + pd.Timedelta(weeks=2)
        on_or_before = sessions[sessions <= fri]
        if len(on_or_before) and on_or_before[-1].to_period("M") == per:
            out.append(on_or_before[-1])
    return out


# --------------------------------------------------------------------------- G2(a)

def cost_rows(roll: pd.DataFrame, ind: pd.DataFrame, tlt: pd.DataFrame) -> pd.DataFrame:
    """Per-structure cost as a fraction of the underlying, one row per rule.

    Roll widths are converted month by month (dollars / median TLT close of that
    month); indicative widths by the snapshot's own spot."""
    px_m = tlt["close"].groupby(tlt.index.to_period("M")).median()
    r = roll.copy()
    r["S_m"] = pd.PeriodIndex(r["month"], freq="M").map(px_m)
    if r["S_m"].isna().any():
        raise ValueError(f"no TLT close for months {r.loc[r.S_m.isna(), 'month'].tolist()}")
    r["adj_pct"] = r["roll_adj"] / r["S_m"]
    r["adj_corr_pct"] = r["roll_adj"] / (1 - r["rho"]) / r["S_m"]
    r["plain_pct"] = r["roll"] / r["S_m"]
    # Undefined months (positive covariance) are NaN. They are EXCLUDED from each
    # statistic, never filled, and counted in `roll_comparison`'s output.
    by = r.groupby("bucket")
    adj_med = by["adj_pct"].median()
    plain_med = by["plain_pct"].median()
    corr_med = by["adj_corr_pct"].median()
    corr_p90 = by["adj_corr_pct"].quantile(0.9)
    i = ind.copy()
    i["w_pct"] = i["width"] / i["spot"]
    ind_med = i.groupby("leg")["w_pct"].median()
    ind_max = i.groupby("leg")["w_pct"].max()
    legs = {"atm_call": "atm", "atm_put": "atm", "put_wing": "put_wing", "call_wing": "call_wing"}
    for name, s in (("plain Roll median", plain_med), ("delta-adj. Roll median", adj_med),
                    ("corrected Roll median", corr_med), ("corrected Roll p90", corr_p90)):
        if s.reindex(sorted(set(legs.values()))).isna().any():
            raise ValueError(f"{name}: no defined month in bucket(s) "
                             f"{s[s.isna()].index.tolist() or sorted(set(legs.values()) - set(s.index))}")

    def tot(f):
        return sum(f(leg, b) for leg, b in legs.items())

    rows = [
        ("point, held to expiry (Roll adj. median, half spread, entry only)",
         tot(lambda leg, b: adj_med[b] / 2)),
        ("point, held to expiry, PLAIN Roll median (half spread, entry only)",
         tot(lambda leg, b: plain_med[b] / 2)),
        ("point, round trip (Roll adj. median, full spread)", tot(lambda leg, b: adj_med[b])),
        ("indicative median, held to expiry (half width)", tot(lambda leg, b: ind_med[leg] / 2)),
        ("indicative median, round trip (full width)", tot(lambda leg, b: ind_med[leg])),
        ("UPPER BOUND: max(indicative median, corrected Roll p90), full width",
         tot(lambda leg, b: max(ind_med[leg], corr_p90[b]))),
        ("relax (1) round trip: upper-bound widths, held to expiry (half width)",
         tot(lambda leg, b: max(ind_med[leg], corr_p90[b]) / 2)),
        ("relax (2) p90: max(indicative median, corrected Roll MEDIAN), full width",
         tot(lambda leg, b: max(ind_med[leg], corr_med[b]))),
        ("stress: widest indicative quote seen, full width", tot(lambda leg, b: ind_max[leg])),
    ]
    out = pd.DataFrame(rows, columns=["rule", "cost_pct_S"])
    out.attrs["legs"] = pd.DataFrame({"roll_plain_median_pct": plain_med, "roll_adj_median_pct": adj_med,
                                      "corr_roll_median_pct": corr_med, "corr_roll_p90_pct": corr_p90})
    out.attrs["indicative"] = pd.DataFrame({"median_pct": ind_med, "max_pct": ind_max})
    return out


def roll_comparison(roll: pd.DataFrame) -> pd.DataFrame:
    """Delta-adjusted against plain Roll, month by month, per bucket (added 2026-10-13).

    WHY: `g2_spreads.py` described the delta adjustment as removing noise, not
    bias, so the adjusted series would share plain Roll's DOWNWARD persistence
    bias. If that were all, the adjusted estimate would scatter around plain
    Roll. A review found it sits ABOVE plain Roll in most months. One candidate
    mechanism [U]: the adjustment uses 1-minute VWAPs of TLT, not the price at
    the trade, so the VWAP's own error enters dp as an MA(1) term with negative
    autocovariance, which Roll reads as spread. So the adjusted series' bias
    direction is unknown, and the counts are printed rather than assumed."""
    both = roll.dropna(subset=["roll", "roll_adj"]).assign(
        above=lambda x: (x["roll_adj"] > x["roll"]).astype(int),
        ratio=lambda x: x["roll_adj"] / x["roll"])
    g = both.groupby("bucket")
    return pd.DataFrame({
        "months": roll.groupby("bucket").size(),
        "plain_defined": roll.dropna(subset=["roll"]).groupby("bucket").size(),
        "adj_defined": roll.dropna(subset=["roll_adj"]).groupby("bucket").size(),
        "both_defined": g.size(),
        "adj_above_plain": g["above"].sum(),
        "median_ratio_adj_over_plain": g["ratio"].median(),
    })


def fit_sample(iv: pd.Series, ret_total: pd.Series) -> pd.DataFrame:
    """Daily IV_t against the forward realised vol over TLT sessions t+1..t+21,
    IV dates in 2004-22, with EVERY window ending before 2023.

    HOLDOUT (corrected 2026-10-13): TLT's returns are cut at the last session
    before `SEALED_FROM` BEFORE `forward_rv` runs, so a window that would need a
    2023 return comes out NaN and is dropped: no 2023 return is ever summed.
    Until 2026-10-13 the headline took IV dates in 2004-22 on the full panel,
    and its last sampled window (IV date 2022-12-27) ran on January 2023
    returns. ALIGNMENT: RV at t uses returns strictly after t (forward_rv);
    `win_end` is the session of the window's last return, asserted < 2023."""
    r = ret_total.sort_index()
    r = r[r.index < SEALED_FROM]
    rv = vs.forward_rv(r).rename("rv")
    j = pd.concat([iv.rename("iv"), rv], axis=1, join="inner").loc[FIT[0]:FIT[1]].dropna()
    pos = r.index.get_indexer(j.index)
    if (pos < 0).any():
        raise ValueError(f"IV dates that are not TLT sessions: {j.index[pos < 0][:5].tolist()}")
    j["win_end"] = r.index[pos + H]
    if not (j["win_end"] < SEALED_FROM).all():
        raise AssertionError("a forward window reaches a sealed 2023 return")
    j["nv_over_S"] = fly_net_vega_over_S(j["iv"].to_numpy())
    return j


def premium_sample(phase: int = 0) -> pd.DataFrame:
    """The non-overlapping sample exactly as `vrp_summary.stats` takes it (every
    21st row, from row `phase`; the headline is phase 0), on `fit_sample`."""
    if not 0 <= phase < H:
        raise ValueError(f"phase must be in 0..{H - 1}, got {phase}")
    return fit_sample(load_vxtlt(), load_tlt()["ret_total"]).iloc[phase::H].copy()


def net_daily(j: pd.DataFrame, cost_pct_S: float) -> pd.Series:
    """Variance-swap proxy net of a per-cycle cost, on every row (in %^2)."""
    return (j["iv"] ** 2 - j["rv"] ** 2) * 1e4 - 2 * (j["iv"] * 100) * (cost_pct_S / j["nv_over_S"])


def phase_robustness(j: pd.DataFrame, cost_pct_S: float) -> dict:
    """The net variance-swap proxy over all 21 start phases of the non-overlapping
    sample, and a Newey-West t (20 lags: the overlap of 21-session windows is
    MA(20)) on the overlapping daily series. Added 2026-10-13: the headline t is
    phase 0 only. Chooses nothing; it says whether the sign depends on phase."""
    means, ts = [], []
    for ph in range(H):
        x = net_daily(j.iloc[ph::H], cost_pct_S)
        means.append(float(x.mean()))
        ts.append(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))))
    return dict(t_min=min(ts), t_med=float(np.median(ts)), t_max=max(ts),
                mean_min=min(means), mean_max=max(means),
                n_pos=sum(m > 0 for m in means), n_neg=sum(m < 0 for m in means),
                nw20_t=float(vs.newey_west_t(net_daily(j, cost_pct_S), 20)))


def snapshot_vega_check(ind: pd.DataFrame, vx: pd.Series) -> dict:
    """The fly's net vega per $1 of S from the indicative snapshots' own greeks,
    against Black-Scholes at the latest VXTLT published BEFORE the snapshot date
    (on 2026-10-12 that was the 2026-10-09 close: the note once called it "that
    day's", corrected 2026-10-13) and 30 days, the conversion the fit uses."""
    if ind["vega"].isna().any():
        raise ValueError("an indicative leg has no vega; no model value is put in its place")
    sign = ind["leg"].map({"atm_call": 1, "atm_put": 1, "put_wing": -1, "call_wing": -1})
    if sign.isna().any():
        raise ValueError(f"unknown legs {sorted(set(ind.loc[sign.isna(), 'leg']))}")
    nv = (ind["vega"] * sign).groupby(ind["snapshot"]).sum() / ind.groupby("snapshot")["spot"].first()
    snap_day = pd.Timestamp(dt_from_stamp(ind["snapshot"].min()).date())
    before = vx.loc[:snap_day - pd.Timedelta(days=1)]
    if before.empty:
        raise ValueError(f"no VXTLT before {snap_day.date()}")
    return dict(snapshot_day=snap_day.date(), nv_median=float(nv.median()), n=len(nv),
                vx_date=before.index[-1].date(), vx=float(before.iloc[-1]),
                bs_nv=float(fly_net_vega_over_S(before.iloc[-1])))


def dt_from_stamp(stamp: str) -> pd.Timestamp:
    """'20261012T184346Z' -> the snapshot's time in New York."""
    return pd.Timestamp(stamp).tz_convert("America/New_York")


def net_stats(m: pd.DataFrame, cost_pct_S: float) -> dict:
    """Mean and t of the two proxies net of a per-cycle cost (fraction of S)."""
    c_vol = cost_pct_S / m["nv_over_S"]                 # vol points per cycle
    a = (m["iv"] - m["rv"]) * 100 - c_vol
    b = (m["iv"] ** 2 - m["rv"] ** 2) * 1e4 - 2 * (m["iv"] * 100) * c_vol
    t = lambda x: x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))
    return dict(cost_volpts=float(c_vol.mean()), ivrv_net=float(a.mean()), ivrv_t=float(t(a)),
                var_net=float(b.mean()), var_t=float(t(b)))


def premium(roll_path: Path, ind_path: Path) -> None:
    tlt = load_tlt()
    vx = load_vxtlt()
    j = fit_sample(vx, tlt["ret_total"])
    m = j.iloc[::H].copy()
    print(f"inputs: VXTLT {VXTLT_CACHE.name} (last {vx.index.max().date()}), etf_panel TLT "
          f"last {tlt.index.max().date()}; fit sample IV dates {m.index.min().date()}..{m.index.max().date()}, "
          f"n {len(m)} non-overlapping; last window ends {m['win_end'].max().date()} "
          f"(every window ends before {SEALED_FROM.date()}: no sealed return is read)")
    g = net_stats(m, 0.0)
    print(f"\nGROSS  IV-RV {g['ivrv_net']:+.3f} vol pts (t {g['ivrv_t']:.2f});  var-swap proxy "
          f"{g['var_net']:+.1f} %^2 (t {g['var_t']:.2f});  mean IV {m.iv.mean()*100:.2f}")
    nv = m["nv_over_S"]
    print(f"fly net vega per $1 of S per vol pt (BS, sigma=VXTLT, T=30/365): median {nv.median():.6f} "
          f"(range {nv.min():.6f}..{nv.max():.6f})")
    be_a = (m["iv"] - m["rv"]).mean() * 100 / (1 / nv).mean()
    be_b = ((m["iv"] ** 2 - m["rv"] ** 2) * 1e4).mean() / (2 * m["iv"] * 100 / nv).mean()
    print(f"break-even structure cost: IV-RV {be_a*1e4:.2f}bp of S ({be_a*1e4/4:.2f}bp per leg); "
          f"var-swap {be_b*1e4:.2f}bp of S ({be_b*1e4/4:.2f}bp per leg)")

    roll = pd.read_parquet(roll_path)
    ind = pd.read_parquet(ind_path)
    rows = cost_rows(roll, ind, tlt)
    print("\nleg widths, fraction of S (bp):")
    print((rows.attrs["legs"] * 1e4).round(2).to_string())
    print((rows.attrs["indicative"] * 1e4).round(2).to_string())
    print(f"indicative snapshots: {ind['snapshot'].nunique()} ({ind['snapshot'].min()}..{ind['snapshot'].max()}), "
          f"expiry {sorted(ind['expiry'].astype(str).unique())}, spot {ind['spot'].min()}..{ind['spot'].max()}")
    v = snapshot_vega_check(ind, vx)
    print(f"fly net vega per $1 of S, snapshot greeks ({v['n']} snapshots, {v['snapshot_day']}): median "
          f"{v['nv_median']:.6f}; Black-Scholes at the latest VXTLT before that day ({v['vx_date']}, "
          f"{v['vx']*100:.2f}) and 30 days: {v['bs_nv']:.6f}")
    print("\ndelta-adjusted vs plain Roll, months where both are defined (bias direction [U]):")
    print(roll_comparison(roll).round(3).to_string())
    print("\nNET of each cost rule (per cycle; costs carried as bp of S):")
    print(f"{'rule':<74}{'bp of S':>8}{'vol pts':>9}{'IV-RV net':>11}{'t':>7}{'var net %^2':>13}{'t':>7}")
    for _, r in rows.iterrows():
        s = net_stats(m, r["cost_pct_S"])
        print(f"{r['rule']:<74}{r['cost_pct_S']*1e4:>8.2f}{s['cost_volpts']:>9.3f}{s['ivrv_net']:>+11.3f}"
              f"{s['ivrv_t']:>7.2f}{s['var_net']:>+13.1f}{s['var_t']:>7.2f}")
    ub = rows.loc[rows.rule.str.startswith("UPPER"), "cost_pct_S"].iloc[0]
    pt = rows.loc[rows.rule.str.startswith("point, held to expiry (Roll adj."), "cost_pct_S"].iloc[0]
    print(f"\nROBUSTNESS: var-swap proxy over all {H} start phases (headline = phase 0) and Newey-West(20) "
          f"on the overlapping daily series (n {len(j)})")
    for lab, cst in (("gross", 0.0), ("point, held to expiry", pt), ("UPPER BOUND", ub)):
        p = phase_robustness(j, cst)
        print(f"   {lab:<22} t across phases {p['t_min']:+.2f}..{p['t_max']:+.2f} (median {p['t_med']:+.2f}); "
              f"mean {p['mean_min']:+.1f}..{p['mean_max']:+.1f} %^2; positive in {p['n_pos']} of {H}, "
              f"negative in {p['n_neg']} of {H}; NW(20) t {p['nw20_t']:+.2f}")
    print("\nGRID: one-way cost per leg in bp of the underlying, 4 legs, entry only (held to expiry)")
    for bp in GRID_BP:
        s = net_stats(m, 4 * bp * 1e-4)
        print(f"{bp:>3}bp/leg  {4*bp:>4}bp of S  {s['cost_volpts']:>7.3f} vol pts   IV-RV net "
              f"{s['ivrv_net']:+.3f} (t {s['ivrv_t']:.2f})   var-swap net {s['var_net']:+.1f} %^2 "
              f"(t {s['var_t']:.2f})")


# --------------------------------------------------------------------------- G2(b)

def cycles(tlt: pd.DataFrame, vx: pd.Series, a: str, b: str) -> pd.DataFrame:
    """One row per monthly cycle entered in [a, b]: entry/expiry sessions and closes,
    the two declared sizing vols (both from the session BEFORE entry), BFLY and
    CNDR strikes, zero-credit payoffs, ex-ante sds and the size n per $ of capital
    that puts the ex-ante annualised sd at VOL_TARGET."""
    S = tlt["close"]
    logr = np.log1p(tlt["ret_total"])
    rv63 = logr.rolling(RV_WINDOW, min_periods=RV_WINDOW).std() * math.sqrt(252)
    exp = monthly_expiries(S.index)
    rows = []
    for e0, e1 in zip(exp[:-1], exp[1:]):
        # Entered in [a, b] AND settled by b: a cycle entered in December 2022
        # settles on a January 2023 close, and 2023+ returns are sealed.
        if not (pd.Timestamp(a) <= e0 and e1 <= pd.Timestamp(b)):
            continue
        prev = S.index[S.index.get_loc(e0) - 1]                   # the session before entry
        assert prev < e0
        vx_prev = vx.loc[:prev]
        if vx_prev.empty or vx_prev.index[-1] < prev - pd.Timedelta(days=7):
            raise ValueError(f"no VXTLT within a week before {e0.date()}")
        sig_i, sig_r = float(vx_prev.iloc[-1]), float(rv63.loc[prev])
        assert vx_prev.index[-1] < e0 and np.isfinite(sig_r)       # strictly before entry
        T = (e1 - e0).days / 365.0
        s0, s1 = float(S.loc[e0]), float(S.loc[e1])
        kps = strike_for_delta(s0, T, sig_i, CNDR_SHORT, "P")
        kpl = strike_for_delta(s0, T, sig_i, CNDR_LONG, "P")
        kcs = strike_for_delta(s0, T, sig_i, CNDR_SHORT, "C")
        kcl = strike_for_delta(s0, T, sig_i, CNDR_LONG, "C")
        fly = lambda x, k=s0: fly_payoff(x, k)
        con = lambda x: condor_payoff(x, kps, kpl, kcs, kcl)
        row = dict(entry=e0, expiry=e1, S0=s0, S1=s1, T=T, sig_I=sig_i, sig_R=sig_r,
                   fly_W=WING * s0, fly_pay=float(fly(s1)),
                   con_W=max(kps - kpl, kcl - kcs), con_pay=float(con(s1)))
        for lab, sig in (("I", sig_i), ("R", sig_r)):
            row[f"fly_sd_{lab}"] = payoff_sd(fly, s0, T, sig)
            row[f"con_sd_{lab}"] = payoff_sd(con, s0, T, sig)
        rows.append(row)
    return pd.DataFrame(rows).set_index("entry")


def sized(c: pd.DataFrame, struct: str, lab: str) -> pd.DataFrame:
    """Per cycle, as fractions of capital: P&L (zero credit) and the most it could
    lose (n W). n x 100 shares = VOL_TARGET x capital / (sqrt(12) sd)."""
    k = spec.VOL_TARGET / math.sqrt(CYCLES_PER_YEAR) / c[f"{struct}_sd_{lab}"]   # n*100/capital, per $ of payoff
    return pd.DataFrame({"pnl": -k * c[f"{struct}_pay"], "max_loss": k * c[f"{struct}_W"],
                         "contracts_at_capital": k * spec.CAPITAL_USD / 100.0})


def assignment_exposure(c: pd.DataFrame, lab: str) -> pd.DataFrame:
    """The stock position physical settlement would leave after each BFLY expiry
    (added 2026-10-13, a review gap; the replay itself settles in cash at S_T).

    TLT options are American and settle in shares [U: not re-read from the OCC
    or Cboe contract specification here]. At expiry, when 0.95 K0 < S_T < 1.05 K0
    and S_T != K0, exactly one short ATM leg is in the money and its wing is
    not: the fly becomes -100 shares (S_T above K0, short call assigned) or
    +100 shares (below, short put assigned) per fly, held from Friday's close
    until it can be traded out. Beyond a wing both legs on that side exercise
    and the shares net to zero. Returned per cycle as a fraction of capital
    (shares/capital = k, the replay's n*100/capital)."""
    k = spec.VOL_TARGET / math.sqrt(CYCLES_PER_YEAR) / c[f"fly_sd_{lab}"]
    inside = ((c["S1"] - c["S0"]).abs() < WING * c["S0"]) & (c["S1"] != c["S0"])
    side = np.sign(c["S0"] - c["S1"]).where(inside, 0.0)         # -1: short shares, +1: long
    return pd.DataFrame({"assigned": inside, "side": side,
                         "notional_frac": (k * c["S1"]).where(inside, 0.0),
                         "contracts_at_capital": k * spec.CAPITAL_USD / 100.0})


def window_stats(x: pd.DataFrame, vol_cap: float) -> dict:
    """Realised vol (ddof=1 and not demeaned) of a window's zero-credit cycle
    P&Ls, and the two path bounds (module docstring; corrected 2026-10-13):
    every P&L lies in [-max(nW), 0], so the population sd is at most max(nW)/2
    (Popoviciu), the ddof=1 sd at most that x sqrt(n/(n-1)), and the rms at
    most max(nW). `inside` is the REALISED path; the bounds say whether ANY
    path could breach the cap."""
    p = x["pnl"]
    n = len(p)
    if n < 2:
        raise ValueError(f"a window needs at least two cycles for a sample sd, got {n}")
    if (p > 0).any():
        raise ValueError("a zero-credit P&L is positive: the [-max(nW), 0] bounds do not apply")
    ann = math.sqrt(CYCLES_PER_YEAR)
    vol = p.std(ddof=1) * ann
    rms = math.sqrt((p ** 2).mean()) * ann
    max_nW = float(x["max_loss"].max())
    bound_sd = max_nW / 2 * math.sqrt(n / (n - 1)) * ann
    bound_rms = max_nW * ann
    cum = p.cumsum()
    dd = float((cum - cum.cummax().clip(lower=0)).min())
    return dict(n=n, vol=vol, rms_vol=rms, bound_sd=bound_sd, bound_rms=bound_rms,
                worst=float(p.min()), total=float(p.sum()), max_dd=dd, max_nW=max_nW,
                contracts=float(x["contracts_at_capital"].median()),
                inside=bool(vol <= vol_cap and rms <= vol_cap),
                any_path_inside=bool(bound_sd <= vol_cap and bound_rms <= vol_cap))


def replay(vol_cap: float) -> None:
    tlt = load_tlt()
    vx = load_vxtlt()
    print(f"{spec.summary()} | VOL_TARGET {spec.VOL_TARGET} | capital ${spec.CAPITAL_USD:,.0f} | "
          f"vol cap {vol_cap} (docs/SYSTEM.md §5) | halve/kill drawdown {spec.risk('halve_drawdown')}/"
          f"{spec.risk('kill_drawdown')} (spec risk block, context only)")
    print(f"inputs: etf_panel TLT {tlt.index.min().date()}..{tlt.index.max().date()}; VXTLT "
          f"{vx.index.min().date()}..{vx.index.max().date()}")
    c = cycles(tlt, vx, "2004-02-01", FIT[1])
    print(f"cycles: {len(c)} entered {c.index.min().date()}..{c.index.max().date()} "
          f"(standard monthly expirations; zero credit; fractional contracts)")
    any_out, bound_out = False, []
    for struct, name in (("fly", "BFLY rule: short ATM, long 5% wings"),
                         ("con", "CNDR rule: short 0.20-delta, long 0.05-delta")):
        for lab, sname in (("I", "sigma = VXTLT"), ("R", "sigma = trailing 63d RV")):
            x = sized(c, struct, lab)
            print(f"\n== {name}; sized on {sname}")
            print(f"   {'window':<18}{'cycles':>7}{'vol':>8}{'rms vol':>9}{'bnd sd':>8}{'bnd rms':>9}"
                  f"{'worst':>9}{'total':>9}{'max dd':>9}{'max nW':>9}{'contr.@cap':>11}"
                  f"  realised inside / any path")
            for wname, (a, b) in {"2004-22 (fit)": FIT, **WINDOWS}.items():
                s = window_stats(x.loc[a:b], vol_cap)
                if wname in WINDOWS and not s["inside"]:
                    any_out = True
                if not s["any_path_inside"]:
                    bound_out.append(f"{struct}/{lab} {wname}")
                print(f"   {wname:<18}{s['n']:>7}{s['vol']:>8.1%}{s['rms_vol']:>9.1%}{s['bound_sd']:>8.1%}"
                      f"{s['bound_rms']:>9.1%}{s['worst']:>9.2%}{s['total']:>9.2%}{s['max_dd']:>9.2%}"
                      f"{s['max_nW']:>9.2%}{s['contracts']:>11.1f}  {'yes' if s['inside'] else 'NO'} / "
                      f"{'bounded' if s['any_path_inside'] else 'NOT bounded'}")
            worst = x["pnl"].idxmin()
            print(f"   worst cycle 2004-22: entered {worst.date()}, {x.loc[worst, 'pnl']:.2%} of capital "
                  f"(S {c.loc[worst, 'S0']:.2f} -> {c.loc[worst, 'S1']:.2f})")
    print(f"\nREALISED PATH: all declared variants inside the {vol_cap:.0%} cap in 2008 and 2020: "
          f"{'NO' if any_out else 'yes'}")
    print(f"ANY PATH: windows where a bound exceeds the cap ({len(bound_out)}): "
          f"{', '.join(bound_out) if bound_out else 'none'}. Where it does, any-path safety is not "
          f"established for that measure.")
    for lab, sname in (("I", "VXTLT"), ("R", "trailing 63d RV")):
        a = assignment_exposure(c, lab)
        z = a[a["assigned"]]
        print(f"ASSIGNMENT (not in the replay P&L) BFLY sized on {sname}: S_T between the wings in "
              f"{len(z)} of {len(a)} cycles (short {int((z.side < 0).sum())}, long {int((z.side > 0).sum())}); "
              f"stock left after expiry, median {z['notional_frac'].median():.0%} of capital "
              f"(max {z['notional_frac'].max():.0%}); median {z['contracts_at_capital'].median():.1f} flies "
              f"at ${spec.CAPITAL_USD:,.0f}")
    model_mark(tlt, vx, vol_cap)


def model_mark(tlt: pd.DataFrame, vx: pd.Series, vol_cap: float) -> None:
    """CROSS-CHECK ONLY [model]: the BFLY marked daily at Black-Scholes with a
    FLAT vol = that day's VXTLT (no skew, European, r = q = 0), sized as variant I
    and now WITH the model credit. Daily P&L annualised on 252. A flat-vol mark
    misprices the wings in a crash, so this is a second look, not the gate."""
    S = tlt["close"]
    exp = monthly_expiries(S.index)
    vxa = vx.reindex(S.index).ffill(limit=5)
    daily = []
    for e0, e1 in zip(exp[:-1], exp[1:]):
        if not (pd.Timestamp("2007-12-01") <= e0 <= pd.Timestamp("2020-12-31")):
            continue
        prev = S.index[S.index.get_loc(e0) - 1]
        sig0 = float(vx.loc[:prev].iloc[-1])
        s0 = float(S.loc[e0])
        T0 = (e1 - e0).days / 365.0
        sd = payoff_sd(lambda x: fly_payoff(x, s0), s0, T0, sig0)
        k = spec.VOL_TARGET / math.sqrt(CYCLES_PER_YEAR) / sd
        legs = ((s0, "C", -1), (s0, "P", -1), (s0 * (1 + WING), "C", 1), (s0 * (1 - WING), "P", 1))
        days = S.loc[e0:e1].index
        val = []
        for d in days:
            T = max((e1 - d).days, 0) / 365.0
            # No fallback (corrected 2026-10-13): this line used to mark with the
            # entry vol `sig0` whenever VXTLT was missing for more than five
            # sessions, a silent substitute that was dormant only because 2008
            # and 2020 have no such gap.
            if not np.isfinite(vxa.loc[d]):
                raise ValueError(f"model mark: no VXTLT on or within 5 sessions before {d.date()} "
                                 f"(cycle {e0.date()} -> {e1.date()}); no other vol is put in its place")
            sg = float(vxa.loc[d])
            val.append(sum(sgn * bs_price(float(S.loc[d]), K, T, sg, cp) for K, cp, sgn in legs))
        v = pd.Series(val, index=days) * k
        daily.append(v.diff().dropna())
    d = pd.concat(daily)
    d = d[~d.index.duplicated(keep="first")]
    print("\nCROSS-CHECK [model, flat-vol BS daily marks, WITH model credit; not the gate]: BFLY sized on VXTLT")
    for wname, (a, b) in WINDOWS.items():
        x = d.loc[a:b]
        cum = x.cumsum()
        print(f"   {wname:<18} daily-P&L vol {x.std()*math.sqrt(252):6.1%}   total {x.sum():+7.2%}   "
              f"worst day {x.min():+6.2%}   max dd {(cum - cum.cummax().clip(lower=0)).min():+7.2%}   "
              f"{'inside' if x.std()*math.sqrt(252) <= vol_cap else 'OUTSIDE'} the {vol_cap:.0%} cap")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["premium", "replay"])
    ap.add_argument("--roll", help="premium: g2_spreads.py roll --out parquet")
    ap.add_argument("--indicative", help="premium: g2_spreads.py indicative --out parquet")
    ap.add_argument("--vol-cap", type=float, help="replay: the vol cap (docs/SYSTEM.md §5); required")
    a = ap.parse_args()
    pd.set_option("display.width", 200)
    if a.step == "premium":
        if not (a.roll and a.indicative):
            raise SystemExit("premium needs --roll and --indicative")
        premium(Path(a.roll), Path(a.indicative))
    else:
        if a.vol_cap is None:
            raise SystemExit("replay needs --vol-cap (the cap in docs/SYSTEM.md §5); there is no default")
        replay(a.vol_cap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
