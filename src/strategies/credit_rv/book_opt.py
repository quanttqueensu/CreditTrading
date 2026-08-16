"""Credit RV book driven by the cost-aware optimiser (see optimizer.py)."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np, pandas as pd
from .costs import CostModel
from .optimizer import solve, calibrate_lambda, _project_null

@dataclass
class OptBookConfig:
    capital: float = 1_000_000.0
    vol_target: float = 0.13
    max_gross: float = 6.0
    cov_window: int = 120
    cov_shrink: float = 0.10
    horizon_days: float = 5.0
    cost_model: CostModel = field(default_factory=CostModel)
    lam_refresh: int = 21          # recalibrate risk aversion monthly
    max_weight: float = 0.50

def _cov(R, shrink):
    n=R.shape[1]; S=np.eye(n)*1e-4
    have=np.isfinite(R).sum(axis=0)>=max(20,int(0.5*R.shape[0]))
    if have.sum()<2: return S
    sub=R[:,have]; rows=np.isfinite(sub).all(axis=1)
    if rows.sum()<20: return S
    C=np.cov(sub[rows],rowvar=False); C=(1-shrink)*C+shrink*np.diag(np.diag(C))
    ix=np.where(have)[0]; S[np.ix_(ix,ix)]=C; return S

def simulate_opt(s_blend, mask, betas, sigma_eq, kappa, excess_returns,
                 dollar_volume, price, rf_daily, cfg: OptBookConfig, exec_lag=1):
    dates=s_blend.index; cols=list(s_blend.columns)
    hedges=[h for h in ["IEF","TLT","SHY","SPY"] if h in excess_returns.columns]
    all_cols=cols+[h for h in hedges if h not in cols]
    N=len(all_cols)
    rx=excess_returns.reindex(index=dates,columns=all_cols); rx_v=rx.values
    adv=np.nan_to_num(dollar_volume.reindex(index=dates,columns=all_cols).values,nan=0.0)
    px=price.reindex(index=dates,columns=all_cols).ffill().values
    dvb=(rx.rolling(60,min_periods=20).std()*1e4).fillna(50.0).values
    CM=cfg.cost_model

    se=sigma_eq.reindex(index=dates,columns=cols).values
    kp=kappa.reindex(index=dates,columns=cols).values
    sv=s_blend.values; mk=mask.values
    with np.errstate(over="ignore",invalid="ignore"):
        rev=1.0-np.exp(-np.clip(kp,0,None)*cfg.horizon_days/252.0)
    MU=np.zeros((len(dates),N))
    MU[:,:len(cols)]=np.nan_to_num(-np.sign(sv)*np.abs(sv)*np.abs(se)*rev)
    MU[:,:len(cols)]*=np.nan_to_num(mk.astype(float))

    hedge_idx=[all_cols.index(h) for h in hedges]
    held=np.zeros(N); pending=[]; nav=cfg.capital
    lam=None; recs=[]; w_hist=np.zeros((len(dates),N))
    cost_by_leg=np.zeros(N); turn_by_leg=np.zeros(N); prev_target=np.zeros(N)
    hold_run=np.zeros(N); hold_lengths=[]

    for i,d in enumerate(dates):
        new=[w for (fi,w) in pending if fi==i]; pending=[(fi,w) for (fi,w) in pending if fi!=i]
        spread_cost=impact_cost=0.0
        if new:
            tgt=new[-1]; notional=np.abs(tgt-held)*nav
            hs=np.array([CM.half_spread_bp(px[i,k] if np.isfinite(px[i,k]) else 50.0,
                                           adv[i,k]) for k in range(N)])/1e4
            spread_cost=float((notional*hs).sum())
            ib=CM.impact_bp(notional,adv[i],np.nan_to_num(dvb[i],nan=50.0))
            impact_cost=float((notional*ib/1e4).sum())
            cost_by_leg+=notional*hs+notional*ib/1e4; turn_by_leg+=notional
            nav-=(spread_cost+impact_cost)
            closed=(np.abs(held)>1e-6)&(np.abs(tgt)<=1e-6)
            for k in np.where(closed)[0]:
                if hold_run[k]>0: hold_lengths.append(hold_run[k])
            hold_run=np.where(np.abs(tgt)>1e-6,hold_run+1,0)
            held=tgt.copy()
        else:
            hold_run=np.where(np.abs(held)>1e-6,hold_run+1,hold_run)

        r=np.nan_to_num(rx_v[i],nan=0.0)
        gross_pnl=float(held@r)*nav
        long_n=float(np.clip(held,0,None).sum())*nav; short_n=float(np.abs(np.minimum(held,0)).sum())*nav
        rf_d=float(rf_daily.get(d,0.0))
        fin_cost,cash_yield=CM.financing_daily(nav,long_n,short_n,rf_d*252.0)
        nav+=gross_pnl-fin_cost+cash_yield

        B=betas.get(d)
        if B is None:
            w_new=prev_target.copy()
        else:
            Bv=B.reindex(all_cols).values
            hist=rx_v[max(0,i-cfg.cov_window+1):i+1]
            S=_cov(hist,cfg.cov_shrink)
            mu=MU[i]
            if mu.any():
                if lam is None or i%cfg.lam_refresh==0:
                    try: lam=calibrate_lambda(mu,S,Bv,cfg.vol_target)
                    except Exception: lam=lam or 1e3
                hs=np.array([CM.half_spread_bp(px[i,k] if np.isfinite(px[i,k]) else 50.0,
                                               adv[i,k]) for k in range(N)])/1e4
                c=2.0*hs
                w=solve(mu,S,c,held,Bv,lam,cfg.max_gross,n_sig=len(cols))
                w=np.clip(w,-cfg.max_weight,cfg.max_weight)
                # neutralise with the LIQUID hedge legs only, so the signal legs
                # keep the no-trade structure the L1 term produced. Rescaling the
                # whole vector to a vol target here would move every weight and
                # regenerate exactly the turnover we are trying to avoid, so the
                # vol target is expressed through lambda, not by post-hoc scaling.
                if hedge_idx:
                    Bh=np.nan_to_num(Bv[hedge_idx],nan=0.0,posinf=0.0,neginf=0.0)
                    exposure=np.nan_to_num(w[:len(cols)]@np.nan_to_num(Bv[:len(cols)]))
                    dollar=float(np.nansum(w[:len(cols)]))
                    A=np.vstack([Bh.T,np.ones((1,len(hedge_idx)))])
                    rhs=np.nan_to_num(np.concatenate([-exposure,[-dollar]]))
                    if np.isfinite(A).all() and np.isfinite(rhs).all() and np.abs(A).sum()>1e-12:
                        try:
                            hsol,*_=np.linalg.lstsq(A,rhs,rcond=None)
                            if np.isfinite(hsol).all():
                                for kk,hp in enumerate(hedge_idx): w[hp]=float(hsol[kk])
                        except Exception: pass
                g=np.abs(w).sum()
                if g>cfg.max_gross: w*=cfg.max_gross/g
                cap=np.where(adv[i]>0,adv[i]*CM.max_participation,0.0)
                tn=np.abs(w-held)*nav; over=(adv[i]>0)&(tn>cap)
                if over.any(): w=np.where(over,held+np.sign(w-held)*cap/max(nav,1.0),w)
                w=np.where(adv[i]>0,w,held)
                w_new=w
            else:
                w_new=np.zeros(N)
        prev_target=w_new
        if i+exec_lag<len(dates): pending.append((i+exec_lag,w_new.copy()))
        w_hist[i]=held
        recs.append({"date":d,"nav":nav,"gross_pnl":gross_pnl,"spread_cost":spread_cost,
                     "impact_cost":impact_cost,"fin_cost":fin_cost,"borrow_cost":0.0,
                     "cash_yield":cash_yield,"gross":float(np.abs(held).sum()),
                     "n_pos":int((np.abs(held)>1e-6).sum())})
    out=pd.DataFrame(recs).set_index("date"); out["ret"]=out["nav"].pct_change().fillna(0.0)
    return {"path":out,"weights":pd.DataFrame(w_hist,index=dates,columns=all_cols),
            "cost_by_leg":pd.Series(cost_by_leg,index=all_cols),
            "turnover_by_leg":pd.Series(turn_by_leg,index=all_cols),
            "median_hold":float(np.median(hold_lengths)) if hold_lengths else np.nan}
