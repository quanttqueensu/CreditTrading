import warnings; warnings.filterwarnings("ignore")
exec(open("refresh.py").read().split("# ---- Q2 P&L")[0].split('print("\\n" + summary())')[0])
d1 = dep.shift(-1).fillna(False).astype(bool)          # deployed at t+1 (ADV through t), on row t
m = d1 & zr.shift(-1).reindex(idxT).notna() & z.shift(-1).reindex(idxT).notna()
print("[mask = deployed at t+1, the set a t+1 decision would trade]")
for nm, sg in (("refresh close", zr.shift(-1)), ("refresh mid", zm.shift(-1)), ("refresh open", zo.shift(-1)), ("full z_{t+1}", z.shift(-1))):
    s = ic_series(sg, fwd1(2), m & sg.reindex(idxT).notna()); print(f"  {nm:<14} vs r_t+2: " + fmt_ic(s))
s = ic_series(z, fwd1(2), dep); print("  live z_t on dep_t vs r_t+2: " + fmt_ic(s))
# WIDE context
wm = wide & z.reindex(idxT).notna() & zr.shift(-1).reindex(idxT).notna() & z.shift(-1).reindex(idxT).notna()
print("[WIDE context, common sample]")
base = None
for nm, sg in (("live z_t", z), ("refresh close", zr.shift(-1)), ("refresh mid", zm.shift(-1)), ("refresh open", zo.shift(-1)), ("full z_{t+1}", z.shift(-1))):
    s = ic_series(sg, fwd1(2), wm & sg.reindex(idxT).notna())
    if base is None: base = s
    dd = (s - base.reindex(s.index)).dropna()
    print(f"  {nm:<14} vs r_t+2: " + fmt_ic(s) + f"   diff vs live {dd.mean():+.4f} (NW t {nw_t(dd):+.2f})")
# half-life: ratios of single-day IC
for lab, mask in (("DEPLOYED", dep), ("WIDE", wide)):
    ic = {k: ic_series(z, fwd1(k), mask).mean() for k in (1, 2, 3, 4, 5)}
    r = {k: ic[k] / ic[1] for k in ic}
    # log-linear fit of IC(k)/IC(1) on k-1 for k=1..3 (where all same sign)
    ks = [k for k in (1, 2, 3) if r[k] > 0]
    b = np.polyfit(np.array(ks) - 1, np.log([r[k] for k in ks]), 1)[0]
    print(f"{lab}: IC(k)/IC(1) " + " ".join(f"k{k} {r[k]:+.2f}" for k in r) + f"  per-day decay {np.exp(b):.2f}  half-life {np.log(0.5)/b:.2f} sessions (fit k=1..3)")
# per-name: pooled slope of r_{t+2} on demeaned signal within each name, WIDE
print("[per name, WIDE: slope bp/unit for live, refresh, full; NAV AC1]")
nr = nav.pct_change(fill_method=None).loc["2005":"2022"]; nr = nr.where(nr.abs() < 0.2)
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

rows = []
for t_ in U:
    out = [pooled(sg, fwd1(2), wm, [t_])[0] for sg in (z, zr.shift(-1), z.shift(-1))]
    rows.append((t_, grp.get(t_), nr[t_].autocorr(), *out))
df = pd.DataFrame(rows, columns=['tk','grp','ac1','live','ref','full']); df['ref_minus_live'] = df.ref - df.live
print(df.round(2).to_string(index=False))
print('Spearman(NAV AC1, refresh-live slope) =', round(df.ac1.corr(df.ref_minus_live, method='spearman'), 2), ' (positive = refresh helps LESS where NAV staler)')
