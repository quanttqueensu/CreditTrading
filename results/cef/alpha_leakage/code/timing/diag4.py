
import warnings; warnings.filterwarnings("ignore")
"""Send-time PRICE-leg refresh of the CEF discount signal. REPORT ONLY.

Fit period only (raw panel truncated at 2022-12-31 BEFORE anything is computed:
build_panel(end=...)), so no 2023+ number exists in memory. Spends no trial.

Signals, all on the 13-name v7 universe from scripts/cef/spec.py:
  z_t     live:   d_t   = 100(P_t - N_t)/N_t, mu/sd = rolling 252 of d through t-1 (shift 1)
  z'_{t+1} refresh: d'_{t+1} = 100(P_{t+1} - N_t)/N_t, z-scored with the mu/sd the live
          z_{t+1} uses, i.e. rolling 252 of d through t (all known by the evening of t).
          P_{t+1} = the t+1 CLOSE (optimistic proxy for a ~15:45 price; Q3).
  z_{t+1} 'full' (infeasible): published N_{t+1} too = old shift(1) scoring.
  open / mid variants: P_{t+1} replaced by the t+1 open (feasible decision price, known
          09:30) or by CRSP's t+1 closing bid/ask midpoint (removes shared bounce).
Every signal is put on the DECISION ROW t of the live book, so "fwd r_{t+2}" is the
return each one earns after a fill at the t+1 close.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path("/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027")
sys.path.insert(0, str(REPO))
from scripts.cef.band_frontier import (build_panel, build_targets, band, evaluate,  # noqa
    total_returns, fit_only, match_band_width, HOLDOUT_START, VOL_LOOKBACK, SAMPLE_START)
from scripts.cef.spec import (UNIVERSE, BAND_WIDTH, MIN_ADV_USD, MIN_NAMES,  # noqa
    VOL_TARGET, Z_WINDOW, summary)

U = list(UNIVERSE)
END = "2022-12-31"
CRSP = REPO / ".claude/worktrees/research-w4/results/cef/w4/_cache_w4/crsp_dsf_w4.parquet"
OPENPRINTS = REPO / ".claude/worktrees/research-core-signal/results/cef/w4/_cache_w4/alpaca_opening_prints_2016_2022.parquet"

p = build_panel(end=END)
px, nav, ret, disc, mu, sd, z, adv = (p[k] for k in ("px", "nav", "ret", "disc", "mu", "sd", "z", "adv"))
assert px.index.max() < HOLDOUT_START
idx = px.index

# raw price/open pivots (not conditioned on a same-day NAV existing)
P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
P = P[P.ticker.isin(U)].copy(); P["date"] = pd.to_datetime(P["date"])
P = P[P.date <= pd.Timestamp(END)]
rawc = P.pivot_table(index="date", columns="ticker", values="close").reindex(index=idx, columns=px.columns)
rawo = P.pivot_table(index="date", columns="ticker", values="open").reindex(index=idx, columns=px.columns)
grp = P.drop_duplicates("ticker").set_index("ticker")["grp"]

navprev = nav.shift(1)       # N_t on row t+1 (ALIGNMENT: previous panel session's NAV)

def zscore_refresh(price_t1):
    """z' on row t+1 from a t+1 price and N_t; mu/sd on row t+1 = window through t."""
    dp = 100.0 * (price_t1 - navprev) / navprev
    dp = dp.where((price_t1 > 0.5) & (navprev > 0.5))
    return ((dp - mu) / sd.replace(0, np.nan)).clip(-4, 4)

zr = zscore_refresh(rawc)                       # refresh on the t+1 close
zo = zscore_refresh(rawo)                       # refresh on the t+1 open (feasible)
c = pd.read_parquet(CRSP); c = c[c.ticker.isin(U)]; c["date"] = pd.to_datetime(c["date"])
c = c[c.date <= pd.Timestamp(END)]
mid = ((c.bid + c.ask) / 2).where((c.bid > 0) & (c.ask > 0) & (c.ask >= c.bid))
c["mid"] = mid.astype(float)
midp = c.pivot_table(index="date", columns="ticker", values="mid").reindex(index=idx, columns=px.columns)
crspo = c.assign(o=c.openprc.astype(float).where(c.openprc.astype(float) > 0)).pivot_table(
    index="date", columns="ticker", values="o").reindex(index=idx, columns=px.columns)
zm = zscore_refresh(midp)
zoc = zscore_refresh(crspo)

# H7 runtime check on random name-dates: recompute z'_{t+1} by hand
rng = np.random.default_rng(0)
ok = 0
for _ in range(200):
    i = rng.integers(400, len(idx)); tk = rng.choice(px.columns)
    v = zr.iloc[i][tk]
    if np.isnan(v): continue
    hist = disc[tk].iloc[max(0, i - Z_WINDOW):i].dropna()   # rows i-252..i-1 = d through t (pandas rolling is over rows)
    if len(hist) < 120: continue
    assert hist.index.max() < idx[i]
    man = (100 * (rawc[tk].iloc[i] - nav[tk].iloc[i - 1]) / nav[tk].iloc[i - 1] - hist.mean()) / hist.std()
    assert abs(np.clip(man, -4, 4) - v) < 1e-9, (idx[i], tk, man, v); ok += 1
print(f"H7 hand-check of z' on {ok} random name-dates: pass")

# ---- targets: an exact copy of build_targets' loop, with z as an argument -----------
def targets_from_z(zz):
    tgt = pd.DataFrame(0.0, index=zz.index, columns=U)
    start = zz.index.searchsorted(pd.Timestamp(SAMPLE_START))
    for i in range(start, len(zz.index)):
        row = zz.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV_USD]]
        if len(row) < MIN_NAMES:
            tgt.iloc[i] = tgt.iloc[i - 1]; continue
        w = -(row - row.mean()); w = w / w.abs().sum()
        hist = ret[list(row.index)].iloc[:i + 1].mul(w, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w * scal).reindex(U).fillna(0.0).values
    return tgt.iloc[start:]

T_live = targets_from_z(z)
T0, R0 = fit_only(*build_targets())
assert T0.index.equals(T_live.index) and np.array_equal(T0.values, T_live.values), "copy != build_targets"
print("targets_from_z(z) == build_targets() on the fit period: byte-identical")
R_px = R0
R_tr = total_returns(R_px)
assert R_tr.index.max() < HOLDOUT_START

# ---- IC machinery -------------------------------------------------------------------
ret_nan = ret.reindex(index=T_live.index)
Rtr_nan = total_returns(ret_nan.fillna(0.0)).where(ret_nan.notna())
idxT = T_live.index
dep = (z.notna() & (adv >= MIN_ADV_USD)).reindex(idxT)
dep = dep & (dep.sum(axis=1) >= MIN_NAMES).values[:, None]
wide = z.notna().reindex(idxT)
wide = wide & (wide.sum(axis=1) >= MIN_NAMES).values[:, None]

def fwd1(k, R=Rtr_nan):
    return R.shift(-k)
def fwd2(a, R=Rtr_nan):     # (1+r_{t+a})(1+r_{t+a+1}) - 1
    return (1 + R.shift(-a)) * (1 + R.shift(-a - 1)) - 1

def ic_series(sig, fwd, mask, min_n=MIN_NAMES):
    s, f = sig.reindex(idxT), fwd.reindex(idxT)
    m = mask & s.notna() & f.notna()
    out = {}
    for d in idxT:
        mm = m.loc[d].values
        if mm.sum() < min_n: continue
        a = s.loc[d].values[mm]; b = f.loc[d].values[mm]
        out[d] = pd.Series(a).rank().corr(pd.Series(b).rank())
    return pd.Series(out, dtype=float).dropna()

def nw_t(x, L=5):
    x = x.dropna().values; n = len(x)
    if n < 10: return np.nan
    e = x - x.mean(); g0 = e @ e / n; s = g0
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / n
    return x.mean() / np.sqrt(s / n)

def naive_t(x):
    x = x.dropna(); return x.mean() / (x.std() / np.sqrt(len(x)))

ERAS = [("2010-14", "2010", "2014"), ("2015-19", "2015", "2019"), ("2020-22", "2020", "2022"),
        ("fit", "2005", "2022")]
def fmt_ic(s, tf=nw_t):
    cells = []
    for lab, a, b in ERAS:
        x = s.loc[a:b]
        cells.append(f"{lab} {x.mean():+.4f} ({tf(x):+.2f}, n{len(x)})" if len(x) > 9 else f"{lab} --")
    return " | ".join(cells)

def pooled(sig, fwd, mask, names):
    s, f = sig.reindex(idxT).where(mask), fwd.reindex(idxT).where(mask)
    m = s.notna() & f.notna()
    s, f = s.where(m), f.where(m)
    s = s.sub(s.mean(axis=1), axis=0); f = f.sub(f.mean(axis=1), axis=0)
    cols = [x for x in names if x in s.columns]
    x, y = s[cols], f[cols]
    sxx = (x ** 2).sum().sum(); beta = (x * y).sum().sum() / sxx
    e = y - beta * x
    sc = (x * e).sum(axis=1)
    se = np.sqrt((sc ** 2).sum()) / sxx
    return beta * 1e4, beta / se, int(x.notna().sum().sum())

grid = pd.Series(np.arange(len(idxT)) % 2, index=idxT)
def h6(sig, fwd, mask):
    s = ic_series(sig, fwd, mask)
    return [(s[grid.reindex(s.index) == ph]) for ph in (0, 1)]
d1 = dep.shift(-1).fillna(False).astype(bool)

groups = {g: [t for t in U if grp.get(t) == g] for g in ("multi", "hy", "loan", "muni")}
sig = {"live": z, "ref_close": zr.shift(-1), "ref_mid": zm.shift(-1), "full": z.shift(-1)}
for lab, base_mask in (("DEPLOYED t&t+1", dep & d1), ("WIDE", wide)):
    m = base_mask.copy()
    for s in sig.values(): m &= s.reindex(idxT).notna()
    print(f"[{lab}] slope bp/unit (date-clustered t); recovered = (ref-live)/(full-live)")
    for g, names in list(groups.items()) + [("all", U)]:
        o = {k: pooled(s, fwd1(2), m, names) for k, s in sig.items()}
        rc = lambda k: (o[k][0] - o["live"][0]) / (o["full"][0] - o["live"][0])
        print(f"  {g:<5} n{o['live'][2]:>6} live {o['live'][0]:+6.2f} ({o['live'][1]:+.2f}) close {o['ref_close'][0]:+6.2f} mid {o['ref_mid'][0]:+6.2f} ({o['ref_mid'][1]:+.2f}) full {o['full'][0]:+6.2f}  rec close {rc('ref_close'):+.2f} mid {rc('ref_mid'):+.2f}")
