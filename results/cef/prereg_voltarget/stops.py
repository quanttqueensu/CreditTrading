"""The raise-specific stops R1-R3, re-measured on the read date (CEF trial 53, DRAFT; H14).

    python3 results/cef/prereg_voltarget/stops.py --scratch SCRATCH --m-core 1.24 --m-c4 1.39
        (prints; writes nothing)

No decision rule may key on a number written in a document (H14), so the pre-registration writes the
RULE and this computes the threshold when the rule is read. Definitions (declared_2026-10-30.json):
  R1  D_R = the LARGEST over SB21 / SB63 / GAUSS of the 95th percentile of the 252-session maximum
      drawdown of the account's raised fit series at the FIT edge, the worse of total return and price
      only, on the account's own fit window, never above the spec's risk.halve_drawdown.
  R2  the 5th percentile of 120-session cumulative PRICE-ONLY returns of the raised fit series (SB21).
  R3  the 95th percentile of the 60-session realised vol (annualised) of the raised PRICE-ONLY fit
      series (SB21).
The raised fit series is the house cap model at the account's multiplier (_common.account); the exact
implementation differs from it by the amounts impl_core.py / impl_c4.py report. Fit window only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from _common import HALVE_DD, W1_START, W2_START, Paths, account, c4_spec_from, core_spec, load
from risk import pctl_maxdd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--m-core", type=float, required=True)
    ap.add_argument("--m-c4", type=float, required=True)
    ap.add_argument("--core-earning-only", type=Path, default=None,
                    help="flatten_series.py's flatten_masks.parquet: calibrate the CORE's stops on the sessions its "
                         "book earns on (FLATTEN_REMEASURE_2026-11-02.md); absent, every session, as before")
    a = ap.parse_args()
    D = load(a.scratch)
    cap = {"core": float(core_spec.MAX_GROSS_STRESS), "c4": float(c4_spec_from()["frozen"]["max_gross_stress"])}
    paths = Paths()
    for who, m, win in (("core", a.m_core, W1_START), ("c4", a.m_c4, W2_START)):
        x = {b: account((D["PT"] if b == "TR" else D["PP"])[who], D["G"][who], m, cap[who])[0].loc[win:]
             for b in ("TR", "PR")}
        if who == "core" and a.core_earning_only is not None:
            earn = pd.read_parquet(a.core_earning_only)["earning"].reindex(x["TR"].index)
            if earn.isna().any():
                raise ValueError("the earning mask does not cover the core's window")
            x = {b: v[earn.to_numpy(dtype=bool)] for b, v in x.items()}
        x = {b: v.values for b, v in x.items()}
        p95 = {b: max(pctl_maxdd(x[b], paths, 0.95).values()) for b in ("TR", "PR")}
        d_r = min(HALVE_DD, max(p95.values()))
        I21 = paths.get(len(x["PR"]))[0]
        r2 = float(np.quantile(np.prod(1 + x["PR"][I21[:, :120]], axis=1) - 1, 0.05))
        r3 = float(np.quantile(x["PR"][I21[:, :60]].std(axis=1, ddof=1) * np.sqrt(252), 0.95))
        print(f"{who} account x{m} (from {win.date()}): R1 D_R {d_r * 100:.2f}% (p95 TR {p95['TR'] * 100:.2f}%, "
              f"PR {p95['PR'] * 100:.2f}%, HALVE {HALVE_DD * 100:.0f}%) | R2 {r2 * 100:+.2f}% | R3 {r3 * 100:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
