"""Emit the CEF sleeve's targets for the last N panel dates as canonical text.
Run once per source tree (cwd decides which `src` is imported). Reads the DEV panel
read-only; writes nothing but stdout."""
import sys, json, hashlib, math
from pathlib import Path
import pandas as pd
DEV = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027")
sys.path.insert(0, "")
from src.deploy.sleeves import cef_discount as m
from src.deploy.sleeve import MarketState
m.PX_PATH = DEV / "data/cef/cef_prices.parquet"
m.NAV_PATH = DEV / "data/cef/cef_nav.parquet"
spec = json.loads((DEV / "ops/specs/cef_discount.frozen.json").read_text())
P = pd.read_parquet(m.PX_PATH); dates = sorted(pd.to_datetime(P[P.ticker.isin(spec["frozen"]["universe"])].date).unique())[-8:]
lines = []
held = {}
for d in dates:
    asof = str(pd.Timestamp(d).date())
    sl = m.CEFDiscountSleeve(spec, 500000.0)
    # two holdings states: flat, and the book the previous date's targets imply
    for label, h in (("flat", {}), ("carried", dict(held))):
        ms = MarketState(asof=asof, prices=pd.DataFrame(), holdings=h, extras={"sleeve_nav": 500000.0})
        for pt in sl.target_positions(asof, ms):
            lines.append(f"{asof}|{label}|{pt.instrument}|{pt.side}|{pt.weight!r}|{pt.qty!r}|{pt.meta!r}|{pt.reason}")
    px = pd.read_parquet(m.PX_PATH); px = px[(pd.to_datetime(px.date) == pd.Timestamp(d))].set_index("ticker").close
    ms = MarketState(asof=asof, prices=pd.DataFrame(), holdings={}, extras={"sleeve_nav": 500000.0})
    held = {}
    for pt in sl.target_positions(asof, ms):
        if pt.weight:
            held[pt.instrument] = float(math.copysign(math.floor(500000.0*abs(pt.weight)/px[pt.instrument]), pt.weight))
txt = "\n".join(lines)
print("source:", Path(m.__file__).resolve())
print("dates:", [str(pd.Timestamp(d).date()) for d in dates])
print("n_lines:", len(lines), "sha256:", hashlib.sha256(txt.encode()).hexdigest())
Path(sys.argv[1]).write_text(txt)
