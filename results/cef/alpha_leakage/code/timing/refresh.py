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

print("\n" + summary())
print(f"panel last dates: cef_prices {pd.read_parquet(REPO/'data/cef/cef_prices.parquet').date.max().date()}, "
      f"cef_nav {pd.read_parquet(REPO/'data/cef/cef_nav.parquet').date.max().date()}; used through {idx.max().date()}")
print(f"deployed name-days {int(dep.sum().sum())}, dates {int((dep.sum(axis=1)>0).sum())}, first {dep.index[dep.any(axis=1)][0].date()}")

print("\n=== Q1. IC of live z_t vs SINGLE-DAY total return r_{t+k}, deployed set, every session, NW(5) t ===")
q1 = {}
for k in (1, 2, 3, 4, 5, 6, 7, 8, 10):
    s = ic_series(z, fwd1(k), dep); q1[k] = s
    print(f"k={k:>2}: " + fmt_ic(s))
print("\n  WIDE set (context, not the book):")
for k in (1, 2, 3, 5, 10):
    s = ic_series(z, fwd1(k), wide)
    print(f"k={k:>2}: " + fmt_ic(s))

# H6 baseline: 2-day [t+2,t+3], non-overlapping grid, phase 0 / 1, date-clustered (one IC per date)
grid = pd.Series(np.arange(len(idxT)) % 2, index=idxT)
def h6(sig, fwd, mask):
    s = ic_series(sig, fwd, mask)
    return [(s[grid.reindex(s.index) == ph]) for ph in (0, 1)]

print("\n=== Q2. Same decision row t, same fill (t+1 close), same forward return ===")
print("common sample: deployed at t AND every signal below non-NaN")
common = dep & z.reindex(idxT).notna() & zr.shift(-1).reindex(idxT).notna() & z.shift(-1).reindex(idxT).notna()
common_m = common & zm.shift(-1).reindex(idxT).notna() & zo.shift(-1).reindex(idxT).notna()
sigs = {"live z_t (deployed)": z,
        "refresh z'_{t+1} on CLOSE t+1 (optimistic)": zr.shift(-1),
        "refresh on t+1 OPEN, yfinance (feasible decision price)": zo.shift(-1),
        "refresh on t+1 OPEN, CRSP openprc": zoc.shift(-1),
        "refresh on t+1 closing MIDPOINT (CRSP; bounce removed)": zm.shift(-1),
        "full z_{t+1}: N_{t+1} too (INFEASIBLE, old shift(1))": z.shift(-1)}
ics = {}
for nm, sg in sigs.items():
    for lab, fwd, mask in (("r_{t+2}", fwd1(2), common_m), ("[t+2,t+3] H6 ph0/ph1", fwd2(2), common_m)):
        if lab.startswith("r_"):
            s = ic_series(sg, fwd, mask); ics[nm] = s
            print(f"{nm:<58} vs {lab:<8} " + fmt_ic(s))
        else:
            a, b = h6(sg, fwd, mask)
            print(f"{'':<58}    {lab}: {a.mean():+.4f} (t {naive_t(a):+.2f}, n{len(a)}) / {b.mean():+.4f} (t {naive_t(b):+.2f})")
base = ics["live z_t (deployed)"]
for nm in list(sigs)[1:]:
    dlt = (ics[nm] - base.reindex(ics[nm].index)).dropna()
    print(f"  diff vs live, {nm[:45]:<45}: {dlt.mean():+.4f} (NW t {nw_t(dlt):+.2f})")

# live z vs r_{t+2} on the plain deployed sample (no common restriction), and W4 tie-out
a, b = h6(z, fwd2(2), dep)
print(f"\nW4 tie-out, live z vs [t+2,t+3] total, deployed, grid ph0/ph1: {a.mean():+.4f} (t {naive_t(a):+.2f}, n{len(a)}) / {b.mean():+.4f} (t {naive_t(b):+.2f}, n{len(b)})")
a2, b2 = h6(zr.shift(-1), fwd2(2), dep & zr.shift(-1).reindex(idxT).notna())
print(f"refresh (close) vs [t+2,t+3], deployed at t: {a2.mean():+.4f} (t {naive_t(a2):+.2f}, n{len(a2)}) / {b2.mean():+.4f} (t {naive_t(b2):+.2f})")

# mid-to-mid return as the second bounce control
Rmid = midp.pct_change(fill_method=None).reindex(idxT)
for nm in ("live z_t (deployed)", "refresh z'_{t+1} on CLOSE t+1 (optimistic)",
           "refresh on t+1 closing MIDPOINT (CRSP; bounce removed)"):
    s = ic_series(sigs[nm], Rmid.shift(-2), common_m)
    print(f"  mid-to-mid r_{{t+2}} (price, no distributions): {nm[:50]:<50} " + fmt_ic(s))

# ---- Q2 P&L ---------------------------------------------------------------------------
def stats(pnl, turn, a=None, b=None):
    pnl, turn = pnl.loc[a:b], turn.loc[a:b]
    ann, vol, t = pnl.mean() * 252, pnl.std() * np.sqrt(252), turn.mean() * 252
    return ann / vol, ann, vol, t, [(ann - t * cc / 1e4) / vol for cc in (5, 15, 30)]

T_ref = targets_from_z(zr)
T_open = targets_from_z(zo)
T_mid = targets_from_z(zm)
H_live = band(T_live, BAND_WIDTH)
first = H_live.index[(H_live.abs().sum(axis=1) > 0).values][0]
pols = {"live band (z_t, shift 2)": H_live,
        "refresh@close, live width": band(T_ref, BAND_WIDTH).shift(-1),
        "refresh@open (yf), live width": band(T_open, BAND_WIDTH).shift(-1),
        "refresh@mid, live width": band(T_mid, BAND_WIDTH).shift(-1),
        "INFEASIBLE shift(1) of live band": H_live.shift(-1)}
live_turn = evaluate(H_live, R_tr)["turn"]
for nm, Tx in (("refresh@close", T_ref), ("refresh@open (yf)", T_open), ("refresh@mid", T_mid)):
    tt = evaluate(band(Tx, BAND_WIDTH), R_tr)["turn"]
    if abs(tt / live_turn - 1) > 0.05:
        bm = match_band_width(Tx, R_tr, live_turn)
        pols[f"{nm}, turnover-matched b={bm*100:.2f}%"] = band(Tx, bm).shift(-1)
print(f"\n=== Q2 P&L via evaluate(): TOTAL returns, plain band; refresh rows = evaluate(H.shift(-1)) i.e. P&L_t = H[t-1]*R_t ===")
print(f"live band width {BAND_WIDTH} from spec; first live position {first.date()}")
res = {}
for nm, H in pols.items():
    r = evaluate(H, R_tr); res[nm] = r
    for lab, a_, b_ in (("fit", None, None), ("live 13-06..22", first, None), ("2015-19", "2015", "2019"), ("2020-22", "2020", "2022")):
        sr, ann, vol, t, nets = stats(r["pnl"], r["turn_series"], a_, b_)
        flip = "YES" if len({np.sign(sr)} | {np.sign(x) for x in nets}) > 1 else "no"
        print(f"{nm:<45}{lab:<15} SR {sr:5.2f} ann {ann*100:5.2f}% vol {vol*100:5.2f}% turn {t:5.1f} "
              f"net5/15/30 {nets[0]:5.2f} {nets[1]:5.2f} {nets[2]:5.2f} flips {flip}")
    print(f"   turnover gap vs live (fit): {r['turn']/live_turn-1:+.1%}")
pl = res["live band (z_t, shift 2)"]["pnl"]
for nm in list(res)[1:]:
    d = (res[nm]["pnl"] - pl).loc[first:]
    print(f"  daily P&L diff vs live from {first.date()}: {nm:<45} {d.mean()*252*100:+.2f}%/yr  NW t {nw_t(d):+.2f}")
# price-return convention, one line each
for nm in ("live band (z_t, shift 2)", "refresh@close, live width"):
    r = evaluate(pols[nm], R_px); print(f"PRICE returns {nm:<35} fit SR {r['gross_sr']:.2f} turn {r['turn']:.1f}")

# ---- Q4 by group ---------------------------------------------------------------------
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
print("\n=== Q4 by family: pooled slope, bp of r_{t+2} per unit signal (xs-demeaned), date-clustered t ===")
groups = {g: [t for t in U if grp.get(t) == g] for g in ("multi", "hy", "loan", "muni")}
for setlab, mask in (("DEPLOYED", common), ("WIDE (context)", wide & z.reindex(idxT).notna() & zr.shift(-1).reindex(idxT).notna() & z.shift(-1).reindex(idxT).notna())):
    print(f"[{setlab}]")
    for g, names in list(groups.items()) + [("all", U)]:
        out = []
        for nm, sg in (("live", z), ("refresh", zr.shift(-1)), ("full", z.shift(-1))):
            b, t, n = pooled(sg, fwd1(2), mask, names); out.append((b, t, n))
        rec = (out[1][0] - out[0][0]) / (out[2][0] - out[0][0]) if out[2][0] != out[0][0] else np.nan
        print(f"  {g:<6} n{out[0][2]:>6}  live {out[0][0]:+7.2f} ({out[0][1]:+.2f})  refresh {out[1][0]:+7.2f} ({out[1][1]:+.2f})"
              f"  full {out[2][0]:+7.2f} ({out[2][1]:+.2f})  share of live->full gap recovered {rec:+.2f}")

# NAV freshness per name, fit period
nr = nav.pct_change(fill_method=None).loc["2005":"2022"]
nr = nr.where(nr.abs() < 0.2)
print("\nNAV freshness per name (2005-22): AC(1) of daily NAV return, sd bp; sd of (z_{t+1}-z'_{t+1}) = unpublished-NAV part")
gap = (z - zr).loc["2005":"2022"]
for t_ in U:
    print(f"  {t_:<4} {grp.get(t_):<5} NAV AC1 {nr[t_].autocorr():+.2f}  NAVsd {nr[t_].std()*1e4:5.1f}bp  "
          f"sd(z-z') {gap[t_].std():.3f}  sd(z_t+1 - z_t) {z[t_].diff().loc['2005':'2022'].std():.3f}")
