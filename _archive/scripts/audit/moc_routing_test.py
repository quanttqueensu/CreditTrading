import ib_async as ibi
ib = ibi.IB(); ib.connect('127.0.0.1', 7497, clientId=95, timeout=20)

c = ibi.Stock('PHK', 'SMART', 'USD'); ib.qualifyContracts(c)
o = ibi.Order(); o.action='BUY'; o.totalQuantity=1; o.orderType='MOC'; o.tif='DAY'

errs=[]
ib.errorEvent += lambda rid,code,msg,ct=None: errs.append((rid,code,msg))

t = ib.placeOrder(c, o)
ib.sleep(6)
print(f"orderType={o.orderType} tif={o.tif}")
print(f"STATUS        : {t.orderStatus.status}")
print(f"filled/remain : {t.orderStatus.filled}/{t.orderStatus.remaining}")
print(f"whyHeld       : {t.orderStatus.whyHeld!r}")
print("log:")
for e in t.log: print(f"   {e.time:%H:%M:%S} {e.status:12s} {e.message}")
print("errors/warnings:")
for rid,code,msg in errs: print(f"   id={rid} code={code} {msg}")

if t.orderStatus.status not in ('Cancelled','Inactive','ApiCancelled'):
    ib.cancelOrder(o); ib.sleep(3)
    print(f"AFTER CANCEL  : {t.orderStatus.status}")
print("\nremaining open orders:", [(x.contract.symbol,x.order.orderType,x.orderStatus.status) for x in ib.openTrades()])
print("PHK position   :", [p.position for p in ib.positions() if p.contract.symbol=='PHK'] or "none")
ib.disconnect()
