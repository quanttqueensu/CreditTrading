"""Is 'short rich in stress' a real repeatable edge, or one or two episodes?"""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
df=pd.read_parquet(ROOT/"results/credit_rv/stress_diag.parquet")
# rebuild the date index (stress_diag lost it) -> recompute with dates
