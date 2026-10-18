"""Q1: vol target vs gross ceiling, LIVE policy (diagnostic, full sample allowed)."""
import numpy as np, pandas as pd
import common as c
bf = c.bf
d = c.live(); T, Rt, Hc, Hu = d["T"], d["Rt"], d["Hc"], d["Hu"]
CAP, VT = c.MAX_GROSS_STRESS, c.VOL_TARGET
r = bf.evaluate(Hc, Rt); pnl = r["pnl"]; turn = r["turn_series"]
gH = Hc.abs().sum(axis=1); gU = Hu.abs().sum(axis=1); gT = T.abs().sum(axis=1)
glag = gH.shift(2)                         # gross of the weights that EARNED day t (shift(2))
first = gH.gt(0).idxmax(); print("first position", first.date(), " sample", T.index[0].date(), "..", T.index[-1].date())

# reproduction check against PREREG_ALPACA_V7 §5 (traded era, to 2026-09-21 there)
def blk(a, b):
    p, t = pnl.loc[a:b], turn.loc[a:b]
    if gH.loc[a:b].max() == 0: return None
    ann, vol = p.mean()*252, p.std()*np.sqrt(252)
    eq = (1+p).cumprod(); mdd = (eq/eq.cummax()-1).min()
    tu = t.mean()*252
    gl = glag.loc[a:b]; on = gl > 0
    x = (p[on]/gl[on])                     # P&L per unit of gross held
    sig_g = x.std()*np.sqrt(252)
    return dict(sr=ann/vol, ann=ann*100, vol=vol*100, mdd=mdd*100, turn=tu,
                g_mean=gH.loc[a:b].mean(), g_on=gH.loc[a:b][gH.loc[a:b]>0].mean(),
                bind=(gH.loc[a:b] >= CAP-1e-9).mean(),
                T_over=(gT.loc[a:b] > CAP).mean(), U_over=(gU.loc[a:b] > CAP).mean(),
                pin=(gT.loc[a:b] >= 2.5-1e-9).mean(),
                ret_per_g=ann/ gl.mean()*100, sig_g=sig_g*100,
                n=[(ann - tu*k/1e4)/vol for k in (5,15,30)],
                na=[(ann - tu*k/1e4)*100 for k in (5,15,30)])
rows = [("traded 2013-06-14..", c.TRADED_START, None)] + [(e, a, b) for e, a, b in c.ERAS] + [("last 252d", str(pnl.index[-252].date()), None)]
print(f"\nLIVE v7 (13 names, band {c.BAND_WIDTH}, cap {CAP}, vt {VT}) TOTAL returns, shift(2), gross P&L")
print(f"{'era':<20}{'SR':>6}{'ann%':>7}{'vol%':>7}{'mdd%':>8}{'turn':>6}{'gAvg':>6}{'gOn':>6}{'cap bind':>9}{'T>cap':>7}{'Hu>cap':>7}{'pin2.5':>7}{'ret/g%':>7}{'vol/g%':>7}  net@5/15/30 SR | ann%")
for lab, a, b in rows:
    s = blk(a, b)
    if s is None: print(f"{lab:<20} flat"); continue
    print(f"{lab:<20}{s['sr']:6.2f}{s['ann']:7.2f}{s['vol']:7.2f}{s['mdd']:8.2f}{s['turn']:6.1f}{s['g_mean']:6.2f}{s['g_on']:6.2f}{s['bind']:9.1%}{s['T_over']:7.1%}{s['U_over']:7.1%}{s['pin']:7.1%}{s['ret_per_g']:7.2f}{s['sig_g']:7.2f}  "
          + " ".join(f"{v:5.2f}" for v in s['n']) + " | " + " ".join(f"{v:5.2f}" for v in s['na']))

# uncapped gross distribution, traded era
te = slice(c.TRADED_START, None)
for lab, g in (("target T (=vol scalar)", gT.loc[te]), ("band, no ceiling Hu", gU.loc[te]), ("LIVE capped Hc", gH.loc[te])):
    q = g.quantile([.05,.25,.5,.75,.95]).round(2).tolist()
    print(f"gross dist traded era {lab:<24} mean {g.mean():.2f} p5/25/50/75/95 {q}  >1.80 {(g>CAP).mean():.1%}  max {g.max():.2f}")

# realised rolling 63d vol vs target
rv63 = pnl.rolling(63).std()*np.sqrt(252)
for lab, a, b in [("traded", c.TRADED_START, None)] + [(e,a,b) for e,a,b in c.ERAS[1:]]:
    v = rv63.loc[a:b]; v = v[gH.loc[a:b].rolling(63).min() > 0]
    print(f"rolling-63d realised vol {lab:<8} median {v.median()*100:.2f}%  mean {v.mean()*100:.2f}%  share below target {(v<VT).mean():.1%}")

# ex-ante gross required for target x: G_req = scal * x/VT  (scal = gT on decision days; exact classification even when clipped)
sc = gT.loc[te]
print("\nEx-ante gross required for a vol target (from the sleeve's own 63d trailing rv of the unit-gross TARGET book; scal clip [0.2,2.5] => exact class.)")
for x in (0.06, 0.08, 0.10, 0.15, 0.20):
    req = sc * x / VT
    unclipped = (sc > 0.2+1e-9) & (sc < 2.5-1e-9)
    print(f"  vt {x:.0%}: median G_req {req.median():.2f}x (unclipped-days median {req[unclipped].median():.2f})  share days G_req>1.80 {(req>CAP).mean():.1%}   >2.0 {(req>2.0).mean():.1%}  >4 {(req>4).mean():.1%}")
# ex-ante rv of unit-gross target book (unclipped days)
rv_ex = (VT / sc[(sc > 0.2+1e-9) & (sc < 2.5-1e-9)])
print(f"  ex-ante unit-gross rv (unclipped days): median {rv_ex.median()*100:.2f}%  mean {rv_ex.mean()*100:.2f}%   pinned at 2.5: {(sc>=2.5-1e-9).mean():.1%}  at 0.2: {(sc<=0.2+1e-9).mean():.1%}")
for e, a, b in c.ERAS[2:]:
    s2 = gT.loc[a:b]; u = s2[(s2>0.2+1e-9)&(s2<2.5-1e-9)]
    print(f"  {e}: scalar mean {s2.mean():.2f} median {s2.median():.2f} pinned {(s2>=2.5-1e-9).mean():.1%}; ex-ante unit rv median {(VT/u).median()*100:.2f}%")
