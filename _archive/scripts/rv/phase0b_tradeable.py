"""The tradeable cell: signal from bounce-free mid, executed at the close.
Does it survive costs, and how much does cutting turnover help?"""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.costs import SCENARIOS
from src.strategies.credit_rv.trials import log_trial
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
p=pd.read_parquet(ROOT/"data/rv/etf_ohlc.parquet"); p=p[p.date<=IS_END]
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
ret_close=p.pivot(index="date",columns="ticker",values="ret_total").sort_index()
mid=p.pivot(index="date",columns="ticker",values="mid_hl").sort_index()
div=p.pivot(index="date",columns="ticker",values="dividend").sort_index().fillna(0.0)
ret_mid=(mid+div)/mid.shift(1)-1.0
dv=(p.assign(dv=p.close*p.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
pxl=p.pivot(index="date",columns="ticker",values="close").ffill().iloc[-1]
sig=compute_signals(ret_mid,rf,dv,SignalConfig())     # SIGNAL from bounce-free mid
S=sig["s_blend"]; S=S[S.index>=IS_START]; betas=sig["betas"]; cols=list(S.columns)
rt=ret_close.reindex(columns=cols)                     # EXECUTE at the close
cm=SCENARIOS["base"]; advm=dv.tail(180).median()
hs=np.array([cm.half_spread_bp(float(pxl.get(c,50) or 50),float(advm.get(c,0) or 0)) for c in cols])/1e4

def run(smooth):
    """smooth = EWMA span on the weight vector; higher = less turnover."""
    W=[];P=[];D=[];prev=None
    for d in S.index:
        B=betas.get(d)
        if B is None or d not in rt.index: continue
        j=rt.index.get_loc(d)
        if j+1>=len(rt): continue
        s=S.loc[d].values.astype(float); ok=np.isfinite(s)
        if ok.sum()<4: continue
        w=np.zeros(len(cols)); w[ok]=-s[ok]; w[ok]-=w[ok].mean()
        Bv=B.reindex(cols).values; good=ok&np.isfinite(Bv).all(axis=1)
        if good.sum()<7: continue
        Bk,wk=Bv[good],w[good]
        wk=wk-Bk@np.linalg.solve(Bk.T@Bk+1e-10*np.eye(Bk.shape[1]),Bk.T@wk)
        w=np.zeros(len(cols)); w[good]=wk-wk.mean()
        n=np.abs(w).sum()
        if n<1e-12: continue
        w/=n
        if prev is not None and smooth>1:
            a=2.0/(smooth+1.0); w=a*w+(1-a)*prev
            n=np.abs(w).sum(); w=w/n if n>1e-12 else w
        prev=w
        W.append(w); P.append(float(w@np.nan_to_num(rt.iloc[j+1].values,nan=0.0))); D.append(d)
    W=np.array(W); P=pd.Series(P,index=D)
    dW=np.abs(np.diff(W,axis=0))
    turn=dW.sum(axis=1).mean()*252
    cost=(dW*hs).sum(axis=1)
    gross=P.mean()*252*100; costyr=cost.mean()*252*100
    net=P.iloc[1:]-cost
    srg=P.mean()/P.std()*np.sqrt(252); srn=net.mean()/net.std()*np.sqrt(252)
    lev=0.13/(net.std()*np.sqrt(252))
    cagr=(1+net*lev).prod()**(252/len(net))-1
    dd=((1+net*lev).cumprod()/(1+net*lev).cumprod().cummax()-1).min()
    return dict(smooth=smooth,turn=turn,gross=gross,cost=costyr,net=gross-costyr,
                sr_gross=srg,sr_net=srn,cagr13=cagr*100,dd13=dd*100)

print("SIGNAL from mid (H+L)/2  ->  EXECUTED at the close.  Base cost scenario.\n")
print(f"{'smooth':>7s} {'turn x/yr':>10s} {'gross%':>8s} {'cost%':>7s} {'net%':>7s} "
      f"{'SR net':>8s} {'CAGR@13%':>9s} {'DD@13%':>8s}")
rows=[]
for sm in [1,3,5,10,20,40]:
    r=run(sm); rows.append(r)
    log_trial(f"MID_smooth{sm}",{"sharpe":r["sr_net"],"cagr":r["cagr13"]/100,"vol":0.13,
              "maxdd":r["dd13"]/100,"median_hold_days":sm,"avg_gross":1.0,
              "cost_drag_pct_yr":r["cost"]},note="mid-signal, close-executed, EWMA smoothing")
    print(f"{sm:>7d} {r['turn']:>10.0f} {r['gross']:>7.2f}% {r['cost']:>6.2f}% {r['net']:>6.2f}% "
          f"{r['sr_net']:>8.2f} {r['cagr13']:>8.2f}% {r['dd13']:>7.1f}%")
pd.DataFrame(rows).to_csv(ROOT/"results/credit_rv/mid_signal_smoothing.csv",index=False)
