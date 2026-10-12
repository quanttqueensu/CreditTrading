"""Gate G2 for the standalone short TLT variance premium, on free data (0 trials).

    export QUANTT_ENV_FILE=/abs/path/to/config/.env      # nothing here reads it; the inputs do
    C=results/gamma/_cache_inputs
    python3 scripts/gamma/g2_gate.py premium --roll $C/g2_roll.parquet --indicative $C/g2_indicative.parquet
    python3 scripts/gamma/g2_gate.py replay  --vol-cap 0.20

Descriptive and zero-trial: GAMMA stays at 0. It does NOT run trial G1, forms no
2023+ return statistic, and chooses no parameter by looking at an outcome. The
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
  Roll (an estimator biased UP, `g2_spreads.py`), paid in FULL on all four legs,
  i.e. a round trip at the touch for a structure that is meant to be held to
  expiry. Three conservative choices stacked; the rows above say how much each
  one costs;
* stress: the widest indicative quote seen per leg, full width.

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
REQUIRED argument here (`--vol-cap`), never a default. Two readings per window:
the realised vol of the cycle P&L (sd x sqrt(12)), and the bound that holds on
ANY path: one cycle's P&L lies in [-(W - C), C], a range of exactly W whatever the
credit C, so sd <= n W / 2 and the annualised vol can never exceed
sqrt(12) x max_t(n_t W_t) / 2 / capital. The spec's risk.halve_drawdown and
risk.kill_drawdown are printed beside the losses as context.

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
    by = r.groupby("bucket")
    adj_med = by["adj_pct"].median()
    corr_p90 = by["adj_corr_pct"].quantile(0.9)
    i = ind.copy()
    i["w_pct"] = i["width"] / i["spot"]
    ind_med = i.groupby("leg")["w_pct"].median()
    ind_max = i.groupby("leg")["w_pct"].max()
    legs = {"atm_call": "atm", "atm_put": "atm", "put_wing": "put_wing", "call_wing": "call_wing"}

    def tot(f):
        return sum(f(leg, b) for leg, b in legs.items())

    rows = [
        ("point, held to expiry (Roll adj. median, half spread, entry only)",
         tot(lambda leg, b: adj_med[b] / 2)),
        ("point, round trip (Roll adj. median, full spread)", tot(lambda leg, b: adj_med[b])),
        ("indicative median, held to expiry (half width)", tot(lambda leg, b: ind_med[leg] / 2)),
        ("indicative median, round trip (full width)", tot(lambda leg, b: ind_med[leg])),
        ("UPPER BOUND: max(indicative median, corrected Roll p90), full width",
         tot(lambda leg, b: max(ind_med[leg], corr_p90[b]))),
        ("stress: widest indicative quote seen, full width", tot(lambda leg, b: ind_max[leg])),
    ]
    out = pd.DataFrame(rows, columns=["rule", "cost_pct_S"])
    out.attrs["legs"] = pd.DataFrame({"roll_adj_median_pct": adj_med, "corr_roll_p90_pct": corr_p90})
    out.attrs["indicative"] = pd.DataFrame({"median_pct": ind_med, "max_pct": ind_max})
    return out


def premium_sample(strict: bool = False) -> pd.DataFrame:
    """VXTLT 2004-22 against forward realised vol, the non-overlapping sample
    exactly as `vrp_summary.stats` takes it (every 21st row from the first).

    The main reading (the plan's +1.28 / +24.0) takes IV DATES in 2004-22, so its
    last window runs into January 2023. `strict` keeps only IV dates whose
    21-session forward window ends by 2022-12-30 (vrp_summary's strict variant),
    so no sealed 2023 return enters."""
    iv = load_vxtlt()
    rv, _ = vs.etf_rv("TLT", ETF_PANEL)
    j = pd.concat([iv, rv], axis=1, join="inner").loc[FIT[0]:FIT[1]].dropna()
    if strict:
        last_ok = j.index[j.index.get_indexer([pd.Timestamp("2022-12-30")], method="pad")[0] - H]
        j = j.loc[:last_ok]
    m = j.iloc[::H].copy()
    m["nv_over_S"] = fly_net_vega_over_S(m["iv"].to_numpy())
    return m


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
    m = premium_sample()
    print(f"inputs: VXTLT {VXTLT_CACHE.name} (last {load_vxtlt().index.max().date()}), etf_panel TLT "
          f"last {tlt.index.max().date()}; fit sample {m.index.min().date()}..{m.index.max().date()}, "
          f"n {len(m)} non-overlapping")
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
    print("\nNET of each cost rule (per cycle; costs carried as bp of S):")
    print(f"{'rule':<72}{'bp of S':>8}{'vol pts':>9}{'IV-RV net':>11}{'t':>7}{'var net %^2':>13}{'t':>7}")
    for _, r in rows.iterrows():
        s = net_stats(m, r["cost_pct_S"])
        print(f"{r['rule']:<72}{r['cost_pct_S']*1e4:>8.2f}{s['cost_volpts']:>9.3f}{s['ivrv_net']:>+11.3f}"
              f"{s['ivrv_t']:>7.2f}{s['var_net']:>+13.1f}{s['var_t']:>7.2f}")
    ms = premium_sample(strict=True)
    ub = rows.loc[rows.rule.str.startswith("UPPER"), "cost_pct_S"].iloc[0]
    for lab, cst in (("gross", 0.0), ("UPPER BOUND", ub)):
        s = net_stats(ms, cst)
        print(f"strict window (IV dates to {ms.index.max().date()}, n {len(ms)}), {lab}: IV-RV "
              f"{s['ivrv_net']:+.3f} (t {s['ivrv_t']:.2f}), var-swap {s['var_net']:+.1f} %^2 (t {s['var_t']:.2f})")
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


def window_stats(x: pd.DataFrame, vol_cap: float) -> dict:
    p = x["pnl"]
    vol = p.std(ddof=1) * math.sqrt(CYCLES_PER_YEAR) if len(p) > 1 else np.nan
    rms = math.sqrt((p ** 2).mean()) * math.sqrt(CYCLES_PER_YEAR)
    bound = x["max_loss"].max() / 2 * math.sqrt(CYCLES_PER_YEAR)
    cum = p.cumsum()
    dd = float((cum - cum.cummax().clip(lower=0)).min())
    return dict(n=len(p), vol=vol, rms_vol=rms, bound=bound, worst=float(p.min()), total=float(p.sum()),
                max_dd=dd, max_nW=float(x["max_loss"].max()),
                contracts=float(x["contracts_at_capital"].median()),
                inside=bool(vol <= vol_cap and rms <= vol_cap))


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
    any_out = False
    for struct, name in (("fly", "BFLY rule: short ATM, long 5% wings"),
                         ("con", "CNDR rule: short 0.20-delta, long 0.05-delta")):
        for lab, sname in (("I", "sigma = VXTLT"), ("R", "sigma = trailing 63d RV")):
            x = sized(c, struct, lab)
            print(f"\n== {name}; sized on {sname}")
            print(f"   {'window':<18}{'cycles':>7}{'vol':>8}{'rms vol':>9}{'bound':>8}{'worst':>9}"
                  f"{'total':>9}{'max dd':>9}{'max nW':>9}{'contr.@cap':>11}  inside cap")
            for wname, (a, b) in {"2004-22 (fit)": FIT, **WINDOWS}.items():
                s = window_stats(x.loc[a:b], vol_cap)
                if wname in WINDOWS and not s["inside"]:
                    any_out = True
                print(f"   {wname:<18}{s['n']:>7}{s['vol']:>8.1%}{s['rms_vol']:>9.1%}{s['bound']:>8.1%}"
                      f"{s['worst']:>9.2%}{s['total']:>9.2%}{s['max_dd']:>9.2%}{s['max_nW']:>9.2%}"
                      f"{s['contracts']:>11.1f}  {'yes' if s['inside'] else 'NO'}")
            worst = x["pnl"].idxmin()
            print(f"   worst cycle 2004-22: entered {worst.date()}, {x.loc[worst, 'pnl']:.2%} of capital "
                  f"(S {c.loc[worst, 'S0']:.2f} -> {c.loc[worst, 'S1']:.2f})")
    print(f"\nall declared variants inside the {vol_cap:.0%} cap in 2008 and 2020: "
          f"{'NO' if any_out else 'yes'}")
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
            sg = float(vxa.loc[d]) if np.isfinite(vxa.loc[d]) else sig0
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
