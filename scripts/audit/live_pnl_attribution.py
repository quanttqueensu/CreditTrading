from ib_async import IB
import collections
ib = IB(); ib.connect('127.0.0.1', 7497, clientId=93, timeout=20)
port = {it.contract.symbol: it for it in ib.portfolio()}
ib.disconnect()

# sleeve share maps, straight from ops/books/*/_ibkr_shadow/*/orders.csv
CEF = dict(AWF=5292,BIT=3320,DSL=4426,HYT=5009,JFR=-3248,MHD=-4822,MQY=-2977,NAD=-6226,
           NEA=-5284,NVG=-6337,NZF=-3763,PCN=5020,PDI=4390,PDO=642,PFN=-602,PTY=4651)
NULL = dict(HYG=541,JNK=961,SPHY=1072,SHYG=358,SJNK=-2579,LQD=-43,VCSH=696,VCIT=-1231,
            IGSB=763,BKLN=796,SRLN=-2485,EMB=360,JAAA=-1006)
B1=dict(HYG=251); B3=dict(AGG=204); B5=dict(SHY=243)
B6=dict(ANGL=86,EMB=26,HYG=31,JNK=26,LQD=23,SHYG=59,USHY=67,VCIT=30)
B4=dict(SPY=16,IEF=85)   # inferred: present in account, absent from local ledger
# decision prices captured at order time (orders.csv decision_price)
DEC={'AWF':10.11,'BIT':12.20,'DSL':10.70,'HYT':8.37,'JFR':7.67,'MHD':11.54,'MQY':11.25,
     'NAD':11.70,'NEA':11.26,'NVG':12.45,'NZF':12.29,'PCN':11.68,'PDI':16.11,'PDO':13.13,
     'PFN':7.06,'PTY':11.74,'HYG':79.47,'JNK':95.66,'SPHY':23.26,'SHYG':42.14,'SJNK':24.85,
     'LQD':106.41,'VCSH':78.67,'VCIT':81.38,'IGSB':52.18,'BKLN':20.38,'SRLN':40.39,
     'EMB':94.79,'JAAA':50.67,'AGG':97.62,'SHY':82.01,'ANGL':28.93,'USHY':36.79}

def sleeve(name, m, capital):
    gross=pnl_fill=pnl_dec=0.0; rows=[]
    for t,sh in m.items():
        it=port.get(t)
        if it is None: rows.append((t,sh,None,None,0.0,0.0)); continue
        mk=it.marketPrice; avg=it.averageCost
        p_fill=sh*(mk-avg)
        d=DEC.get(t); p_dec=sh*(mk-d) if d else float('nan')
        gross+=abs(sh*mk); pnl_fill+=p_fill
        if d: pnl_dec+=p_dec
        rows.append((t,sh,avg,mk,p_fill,p_dec if d else 0.0))
    print(f"\n=== {name}   capital ${capital:,.0f}   gross ${gross:,.0f} ({gross/capital:.2f}x)")
    print(f"{'tkr':6s} {'shares':>8s} {'fill':>9s} {'mark':>9s} {'P&L vs fill':>12s} {'P&L vs decision':>16s}")
    for t,sh,avg,mk,pf,pd in sorted(rows,key=lambda r:r[4]):
        if avg is None: print(f"{t:6s} {sh:>8.0f}   NOT HELD"); continue
        print(f"{t:6s} {sh:>8.0f} {avg:9.4f} {mk:9.4f} {pf:>12.2f} {pd:>16.2f}")
    print(f"{'TOTAL':6s} {'':>8s} {'':>9s} {'':>9s} {pnl_fill:>12.2f} {pnl_dec:>16.2f}")
    print(f"       vs fill: {pnl_fill/capital*100:+.3f}% of capital  |  vs decision: {pnl_dec/capital*100:+.3f}%")
    return pnl_fill, pnl_dec, gross

r={}
r['CEF discount']       = sleeve('CEF DISCOUNT (the strategy)', CEF, 500_000)
r['Null trader']        = sleeve('PHASE-0 NULL TRADER (control)', NULL, 640_000)
r['B1 HYG']             = sleeve('BENCH B1 — HYG', B1, 20_000)
r['B3 AGG']             = sleeve('BENCH B3 — AGG', B3, 20_000)
r['B4 60/40']           = sleeve('BENCH B4 — 60/40 SPY-IEF', B4, 20_000)
r['B5 SHY']             = sleeve('BENCH B5 — SHY', B5, 20_000)
r['B6 EW credit']       = sleeve('BENCH B6 — EW credit', B6, 20_000)

print("\n\n================ SUMMARY (mark-to-market, USD) ================")
cap={'CEF discount':500_000,'Null trader':640_000,'B1 HYG':20_000,'B3 AGG':20_000,
     'B4 60/40':20_000,'B5 SHY':20_000,'B6 EW credit':20_000}
print(f"{'book':16s} {'capital':>10s} {'gross':>12s} {'P&L $':>10s} {'ret %':>8s}")
for k,(pf,pd,g) in r.items():
    print(f"{k:16s} {cap[k]:>10,.0f} {g:>12,.0f} {pf:>10,.0f} {pf/cap[k]*100:>7.2f}%")
