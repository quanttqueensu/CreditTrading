"""Does pandas return wrong numbers in THIS Python environment? A self-contained check.

    python3 scripts/events/numexpr_fault.py            # exit 1 if the fault is present
    python3 scripts/events/numexpr_fault.py --agent    # also re-run the agent's original pandas
                                                       # path on the cached convert-study inputs
                                                       # (run convert_issuance.py first)

WHY THIS EXISTS (SCALING_RESEARCH_2026-10-08 §7.4, plan item 0.9)
------------------------------------------------------------------
On 2026-10-09 a desk agent's convertible-issuance event study got window sums
of about 1e-316 for roughly 40% of its events. It disabled bottleneck,
rewrote the arithmetic in numpy, and the headline announcement return moved
from -1.20% to -4.41%. The cause was never isolated. §7.4 then
re-checked rolling means and sums on the repo's discount panel, found nothing,
and recorded that the fault "does not reproduce on the live inputs".

The re-run of 2026-10-11 (`results/events/REPRO_CORP_EVENTS_2026-10-11.md`)
ran the agent's ORIGINAL code again and isolated the fault. The agent's code is
correct pandas. The wrong numbers come from **numexpr**:

  * pandas 2.3.3 hands DataFrame arithmetic to numexpr when the frame has more
    than 1,000,000 cells (`pandas.core.computation.expressions._MIN_ELEMENTS`)
    and the option `compute.use_numexpr` is on, which is the default whenever
    numexpr is importable;
  * on the team lead's laptop (Anaconda, Python 3.13.5, numexpr 2.10.1 with
    numpy 2.3.4), numexpr returns wrong cells whenever one operand is
    BROADCAST: `df.sub(series, axis=0)`, `df - df.mean()`,
    `df.div(df.abs().sum(axis=1), axis=0)`. The wrong cells hold other cells'
    values, NaN where the answer is finite, or denormals (~1e-316). The
    pattern changes from run to run (multithreaded), and some layouts are
    wrong even single-threaded. Same-shape operations (frame + frame, frame *
    scalar) were correct in every check;
  * bottleneck is irrelevant: turning it off changes nothing.

Why §7.4's re-check passed: the CEF discount panel is about 44 names x 7,000
days (about 300k cells), below the 1e6 threshold, and §7.4 tested rolling
reductions, not broadcast arithmetic.

WHAT TO DO WITH THE ANSWER
--------------------------
Any research script on this laptop that does broadcast arithmetic on a frame of
more than 1e6 cells (a wide CRSP or TRACE panel) can be silently wrong. The
scripts in `scripts/events/` set `compute.use_numexpr` off at import and do
their window arithmetic in numpy. `numexpr` is not in `requirements.txt`, so a
clean install (the VM) probably does not have it; that is [U] until someone
runs this script there. A repo-wide guard is a decision for the team lead.

This is a check on our environment, so synthetic data is the right input: the
conclusion is about the code, not about any market (CLAUDE.md, data rules).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _wrong_cells(got, ref, tol=1e-12) -> int:
    """Cells where `got` and `ref` disagree: NaN in one but not the other, or
    finite values more than `tol` apart."""
    got = np.asarray(got, dtype=float)
    ref = np.asarray(ref, dtype=float)
    nan_mismatch = np.isnan(got) != np.isnan(ref)
    both = ~np.isnan(got) & ~np.isnan(ref)
    off = np.zeros_like(both)
    off[both] = np.abs(got[both] - ref[both]) > tol
    return int(nan_mismatch.sum() + off.sum())


def run(rows: int = 3105, cols: int = 501, seed: int = 0) -> dict:
    """Broadcast arithmetic on a frame of rows x cols (default: the agent's
    event-study return matrix, 1.56m cells) with numexpr on and off, each
    checked against the same arithmetic done in numpy."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0, 0.02, (rows, cols))
    a[rng.random((rows, cols)) < 0.3] = np.nan          # a ragged panel, like CRSP
    df = pd.DataFrame(a)
    col0 = a[:, [0]]
    colmean = df.mean().to_numpy()[None, :]
    rowsum = np.nansum(np.abs(a), axis=1)[:, None]
    out = {"cells": df.size}
    try:
        import numexpr
        out["numexpr"] = numexpr.__version__
    except ImportError:
        out["numexpr"] = None
    before = pd.get_option("compute.use_numexpr")
    try:
        for flag in (True, False):
            pd.set_option("compute.use_numexpr", flag)
            out[flag] = {
                "df.sub(col, axis=0)": _wrong_cells(df.sub(df[0], axis=0), a - col0),
                "df - df.mean()": _wrong_cells(df - df.mean(), a - colmean),
                "df.div(rowsum, axis=0)": _wrong_cells(df.div(df.abs().sum(axis=1), axis=0), a / rowsum),
                "df + df (no broadcast)": _wrong_cells(df + df, a + a),
            }
    finally:
        pd.set_option("compute.use_numexpr", before)
    return out


def agent_path() -> dict:
    """The agent's ORIGINAL window arithmetic (its second run, 2026-10-09:
    `R = px.pivot(...)`, `AR = R.sub(spy, axis=0)`, `AR[p].iloc[a:b].sum()`), on the
    same inputs `convert_issuance.py` caches, with numexpr on and then off. The
    inputs are the convert sample only, as in the agent's pull (500 issuers + SPY,
    2010-09-01..2022-12-30), so the frame has the agent's shape."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import convert_issuance as ci                      # sets use_numexpr off at import
    m = ci.build_events("Y", refresh=False)
    ret = pd.read_parquet(ci.CACHE / "crsp_returns.parquet")
    px = ret[ret.permno.isin(set(m.permno) | {ci.SPY_PERMNO})].copy()
    px["date"] = pd.to_datetime(px["date"])
    out = {}
    for flag in (True, False):
        pd.set_option("compute.use_numexpr", flag)
        R = px.pivot(index="date", columns="permno", values="ret")
        AR = R.sub(R[ci.SPY_PERMNO], axis=0)
        idx = AR.index
        sums = {k: [] for k in ci.WINDOWS}
        for _, e in m.iterrows():
            i = idx.searchsorted(e.d0)
            if i - 5 < 0 or i + 60 >= len(idx) or e.permno not in AR.columns:
                continue
            a = AR[e.permno]
            segs = {k: a.iloc[i + lo:i + hi + 1] for k, (lo, hi) in ci.WINDOWS.items()}
            if any(s_.isna().any() for s_ in segs.values()):
                continue
            for k, s_ in segs.items():
                sums[k].append(s_.sum())
        x = {k: np.asarray(v) for k, v in sums.items()}
        out[flag] = {"cells": R.size, "events": len(x["evt[-1,0]"]),
                     "denormal_sums": {k: int(((np.abs(v) < 1e-12) & (v != 0)).sum()) for k, v in x.items()},
                     "mean_pct": {k: round(100 * float(v.mean()), 2) for k, v in x.items()}}
    pd.set_option("compute.use_numexpr", False)
    return out


def main() -> int:
    if "--agent" in sys.argv[1:]:
        a = agent_path()
        for flag in (True, False):
            print(f"agent's pandas path, compute.use_numexpr={flag}: frame {a[flag]['cells']:,} cells, "
                  f"{a[flag]['events']} events")
            print("   denormal-like window sums:", a[flag]["denormal_sums"])
            print("   window means %:", a[flag]["mean_pct"])
    r = run()
    print(f"pandas {pd.__version__}, numpy {np.__version__}, numexpr {r['numexpr']}, "
          f"frame of {r['cells']:,} cells")
    for flag in (True, False):
        print(f"compute.use_numexpr={flag}:")
        for k, v in r[flag].items():
            print(f"   {k:<26} wrong cells: {v:,}")
    bad = any(v for v in r[True].values()) or any(v for v in r[False].values())
    print("FAULT PRESENT: broadcast arithmetic on large frames is wrong here" if bad
          else "no fault: every operation matched numpy")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
