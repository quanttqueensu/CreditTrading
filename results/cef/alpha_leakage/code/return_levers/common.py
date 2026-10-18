"""Scratch: shared setup. Uses ONLY the canonical harness (band_frontier) and spec.
Reads data/ read-only, writes nothing in the repo."""
import sys, pickle, os
from pathlib import Path
import numpy as np, pandas as pd
REPO = Path("/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027")
sys.path.insert(0, str(REPO))
from scripts.cef import band_frontier as bf
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, VOL_TARGET, UNIVERSE
SCR = Path(__file__).resolve().parent
ERAS = [("2005-09", "2005", "2009"), ("2010-14", "2010", "2014"), ("2015-19", "2015", "2019"),
        ("2020-22", "2020", "2022"), ("2023-26", "2023", "2026")]
TRADED_START = "2013-06-14"   # as pre-registered (PREREG_ALPACA_V7 §4)

def live():
    cache = SCR / "live.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    T, R = bf.build_targets()                 # spec universe (13), spec vol target
    Rt = bf.total_returns(R)
    Hc = bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)   # LIVE policy
    Hu = bf.band(T, BAND_WIDTH)                                   # same, no ceiling
    out = dict(T=T, R=R, Rt=Rt, Hc=Hc, Hu=Hu)
    cache.write_bytes(pickle.dumps(out))
    return out
