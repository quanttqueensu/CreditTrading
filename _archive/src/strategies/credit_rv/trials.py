"""Trial accounting (CREDIT_RV_PREREG.md §8). Every config evaluated against
returns is logged here, kept or not. Searching harder raises the DSR bar."""
from __future__ import annotations
import csv, datetime as _dt
from pathlib import Path
LOG = Path(__file__).resolve().parents[3] / "results" / "credit_rv" / "trial_log.csv"
FIELDS = ["n","ts","tag","sharpe","cagr","vol","maxdd","median_hold_days",
          "avg_gross","cost_drag_pct_yr","note"]

def _rows():
    if not LOG.exists(): return []
    with LOG.open() as f: return list(csv.DictReader(f))

def log_trial(tag: str, st: dict, note: str = "") -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rows = _rows(); n = len(rows) + 1
    new = {"n": n, "ts": _dt.datetime.now().isoformat(timespec="seconds"), "tag": tag,
           "sharpe": round(float(st.get("sharpe", float("nan"))), 4),
           "cagr": round(float(st.get("cagr", float("nan"))), 5),
           "vol": round(float(st.get("vol", float("nan"))), 5),
           "maxdd": round(float(st.get("maxdd", float("nan"))), 4),
           "median_hold_days": st.get("median_hold_days", ""),
           "avg_gross": round(float(st.get("avg_gross", float("nan"))), 3),
           "cost_drag_pct_yr": round(float(st.get("cost_drag_pct_yr", float("nan"))), 3),
           "note": note}
    write_header = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header: w.writeheader()
        w.writerow(new)
    return n

def trial_count() -> int:
    return len(_rows())
