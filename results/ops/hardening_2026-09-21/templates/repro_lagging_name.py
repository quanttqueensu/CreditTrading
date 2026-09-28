"""SYNTHETIC -- tests OUR CODE's behaviour, not the market. One held name loses its
last-row NAV (the HYT-lags-a-day shape). What does the band-mode sleeve emit?"""
import numpy as np, pandas as pd, tempfile, pathlib, math
from src.deploy.sleeve import MarketState
from src.deploy.sleeves import cef_discount as m
T = ["AAA","BBB","CCC","DDD","EEE","FFF","GGG","HHH"]; NAV=500000.0
spec={"capital_usd":NAV,"allocation":{"type":"cef_discount"},"rebalance":{},"risk":{},
 "frozen":{"universe":T,"z_window":252,"rebalance_days":1,"vol_target_annual":0.06,"min_adv_usd":3e6,
 "max_nav_age_bd":3,"min_names":6,"min_abs_weight":0.005,"gross_leverage":1.0,"order_type":"MOC","band_width":0.048}}
rng=np.random.default_rng(20260908); dates=pd.bdate_range("2024-09-02",periods=330); px_rows=[];nav_rows=[]
for i,tk in enumerate(T):
    nav=10+np.cumsum(rng.normal(0,.02,len(dates))); d=np.zeros(len(dates)); d[0]=-.03+.01*i
    for t in range(1,len(dates)): d[t]=.97*d[t-1]+.03*(-.03+.01*i)+rng.normal(0,.004)
    for dt,c,n in zip(dates,nav*(1+d),nav):
        px_rows.append({"date":dt,"ticker":tk,"close":float(c),"volume":1e6}); nav_rows.append({"date":dt,"ticker":tk,"nav":float(n)})
tmp=pathlib.Path(tempfile.mkdtemp(dir=str(pathlib.Path(__file__).parent)))
def run(nav_rows, holdings, label):
    pd.DataFrame(px_rows).to_parquet(tmp/"px.parquet"); pd.DataFrame(nav_rows).to_parquet(tmp/"nav.parquet")
    m.PX_PATH, m.NAV_PATH = tmp/"px.parquet", tmp/"nav.parquet"
    asof=str(dates[-1].date()); sl=m.CEFDiscountSleeve(spec,NAV)
    out=sl.target_positions(asof, MarketState(asof=asof,prices=pd.DataFrame(),holdings=dict(holdings),extras={"sleeve_nav":NAV}))
    print(f"== {label}")
    for pt in out: print(f"   {pt.instrument} {pt.side:5} w={pt.weight!s:>22} qty={pt.qty!s:>8}  {pt.reason}")
    return out
# a book held exactly at the full-panel band-mode decision
base=run(nav_rows, {}, "full panel, flat book (reference)")
last_close={r["ticker"]:r["close"] for r in px_rows if r["date"]==dates[-1]}
held={pt.instrument: math.copysign(math.floor(NAV*abs(pt.weight)/last_close[pt.instrument]), pt.weight) for pt in base if pt.weight}
print("held book:", held)
run(nav_rows, held, "full panel, held book -> expect all HOLD / no trade")
victim=[k for k in held][0]
lag=[r for r in nav_rows if not (r["ticker"]==victim and r["date"]==dates[-1])]
run(lag, held, f"{victim}'s NAV for the last date NOT YET PUBLISHED (1bd lag, inside max_nav_age_bd=3), same held book")
