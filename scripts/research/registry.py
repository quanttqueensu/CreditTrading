"""The trial registry: every trial's daily P&L series, stored where the inference
module can read it back.

WHY THIS FILE EXISTS (2026-10-27). The team lead ruled (docs/SYSTEM.md §5,
2026-10-27) that the paper's deflated-Sharpe bar gates "once trials store their
daily P&L series". That bar uses the Gumbel expected maximum, the effective N
and the measured cross-trial V[SR_n]. Until then, the desk's sqrt(2 ln N) on the
raw counter gates. Every input the paper's bar needs beyond the selected
strategy is a property of the whole SET of trials:

  - the effective number of independent trials: N_hat = rho_bar + (1 - rho_bar) M,
    which needs every trial's series to measure rho_bar
    (Bailey & López de Prado 2014, Appendix A.3);
  - the variance of Sharpe ratios across trials, V[SR_n];
  - the T x N P&L matrix that PBO/CSCV ranks (Bailey, Borwein, López de Prado &
    Zhu 2017).

A counter cannot supply any of them. López de Prado & Lewis (2019): "ignorance
of [E[K] and E[V[SR_k]]] makes it impossible to assess whether a discovery is
false" (3-0 verified, 2026-10-27). So every trial stores its series here, and
`bar_inputs` measures the inputs at run time (H14). It never reads them from a
document.

WHAT IS STORED WHERE
- `ledger.jsonl` (tracked) has one line per stored variant: counter, trial,
  variant, the commit and whether the tree was dirty, the series' first and
  last dates, n, gross Sharpe, skew, raw kurtosis, the series' sha256 and the
  parameters.
- `series/<counter>/<trial>/<variant>.parquet` (GITIGNORED) is the series
  itself. The repository is public, and an event book's daily P&L can be one
  CRSP-licensed security's return in all but name. E1's module rule is "never a
  row-level price or return" in a tracked file. The ledger's sha256 is the
  tracked commitment: `load` refuses a series whose bytes no longer match it.

A TRIAL HERE IS THE COUNTER'S TRIAL. `trial` is the id the counter was
incremented for (for example "CEF-53"). `variant` names each configuration that
trial evaluated. Clustering for the effective N runs over variants, because
correlated variants of one idea are the case it exists for.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "results" / "research" / "trials"
LEDGER = "ledger.jsonl"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def _counters() -> dict:
    """The canonical counters, read through `ops.orient.trials()`, so there is
    one parser for the table (docs/RESEARCH_STATE.md)."""
    import sys
    sys.path.insert(0, str(REPO))
    from ops.orient import trials
    return trials()["counters"]


def _git(*args) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}; "
                           "a trial with no commit has no provenance")
    return out.stdout.strip()


def _series_bytes(pnl: pd.Series) -> bytes:
    """The canonical bytes a series is hashed and stored as: float64 values,
    plus the index as int64 nanoseconds. Parquet is written from these
    values, and `load` re-derives the bytes before comparing."""
    return (pnl.to_numpy(dtype="float64").tobytes()
            + pnl.index.asi8.tobytes())


def _check_series(pnl: pd.Series) -> None:
    if not isinstance(pnl, pd.Series):
        raise TypeError("pnl must be a pandas Series (one value per session)")
    if not isinstance(pnl.index, pd.DatetimeIndex) or pnl.index.tz is not None:
        raise TypeError("pnl must be indexed by tz-naive session dates")
    if not pnl.index.is_monotonic_increasing or not pnl.index.is_unique:
        raise ValueError("pnl's index must be sorted and unique")
    if len(pnl) < 2:
        raise ValueError("a series of fewer than 2 sessions has no Sharpe")
    if not np.isfinite(pnl.to_numpy(dtype=float)).all():
        raise ValueError("pnl holds NaN or inf; store the series evaluate() returned, "
                         "which has neither")
    if np.ptp(pnl.to_numpy(dtype=float)) == 0:       # std() of a constant float is ~1e-19, not 0
        raise ValueError("pnl is constant; a flat book is not a trial")


def record(pnl: pd.Series, *, counter: str, trial: str, variant: str, params: dict,
           note: str = "", root: Path = ROOT, allow_dirty: bool = False) -> dict:
    """Store one variant's daily P&L under its counter and trial.

    Refuses:
    - a counter the canonical table does not hold;
    - a name the filesystem would mangle;
    - a series with NaN, inf, an unsorted index or zero variance;
    - a dirty working tree unless `allow_dirty`, because the commit is the
      provenance and a dirty tree's commit does not reproduce the series (the
      ledger records the flag either way);
    - a second, DIFFERENT series under an existing (counter, trial, variant).
      Re-recording identical bytes is a no-op that returns the existing line,
      so a re-run is safe and a changed result can never silently replace the
      one that was judged.
    """
    _check_series(pnl)
    pnl = pd.Series(pnl.to_numpy(dtype="float64"),
                    index=pnl.index.as_unit("ns"))       # one byte layout to hash and store
    counters = _counters()
    if counter not in counters:
        raise ValueError(f"counter {counter!r} is not in the canonical table "
                         f"({sorted(counters)}); open a counter there first")
    for what, v in (("trial", trial), ("variant", variant)):
        if not _NAME.match(v):
            raise ValueError(f"{what} {v!r} must match {_NAME.pattern}")
    try:
        json.dumps(params)
    except TypeError as e:
        raise TypeError(f"params must be JSON-serialisable: {e}") from None
    commit = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    if dirty and not allow_dirty:
        raise RuntimeError("the working tree has uncommitted changes, so HEAD does not "
                           "reproduce this series; commit first, or pass allow_dirty=True "
                           "and the ledger will say so")
    root = Path(root)
    sha = hashlib.sha256(_series_bytes(pnl)).hexdigest()
    existing = [r for r in _read_ledger(root)
                if (r["counter"], r["trial"], r["variant"]) == (counter, trial, variant)]
    if existing:
        if existing[-1]["sha256"] == sha:
            return existing[-1]
        raise ValueError(f"{counter}/{trial}/{variant} is already stored with a different "
                         "series; a judged result is never replaced. Use a new variant name")
    rel = Path("series") / counter / trial / f"{variant}.parquet"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pnl.rename("pnl").to_frame().to_parquet(tmp)
    tmp.replace(path)
    x = pnl.to_numpy(dtype=float)
    line = dict(
        ts=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        counter=counter, trial=trial, variant=variant, note=note,
        commit=commit, dirty=dirty,
        first=pnl.index[0].date().isoformat(), last=pnl.index[-1].date().isoformat(),
        n=len(x), sr_annual=float(x.mean() / x.std(ddof=1) * np.sqrt(252)),
        skew=float(pd.Series(x).skew()), kurt=float(pd.Series(x).kurt() + 3.0),
        sha256=sha, path=str(rel), params=params)
    with open(root / LEDGER, "a") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
    return line


def _read_ledger(root: Path) -> list[dict]:
    p = Path(root) / LEDGER
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]


def entries(counter: str, *, trials=None, root: Path = ROOT) -> list[dict]:
    """The ledger lines for one counter, optionally restricted to some trials."""
    rows = [r for r in _read_ledger(root) if r["counter"] == counter]
    if trials is not None:
        want = set(trials)
        rows = [r for r in rows if r["trial"] in want]
        missing = want - {r["trial"] for r in rows}
        if missing:
            raise ValueError(f"no stored series for trial(s) {sorted(missing)} on {counter}")
    return rows


def load(entry: dict, *, root: Path = ROOT) -> pd.Series:
    """One stored series. Raises if its bytes no longer match the ledger."""
    path = Path(root) / entry["path"]
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; the series lives only on the machine "
                                "that recorded it (it is gitignored)")
    s = pd.read_parquet(path)["pnl"]
    s.index = pd.DatetimeIndex(s.index).as_unit("ns")
    if hashlib.sha256(_series_bytes(s)).hexdigest() != entry["sha256"]:
        raise ValueError(f"{path} does not match its ledger sha256; it was altered after it "
                         "was recorded")
    return s


def matrix(counter: str, *, trials=None, root: Path = ROOT) -> tuple[pd.DataFrame, dict]:
    """The T x N matrix of a counter's stored variants, on the sessions all of
    them share (PBO/CSCV and the correlation need a common T). The second value
    says how many sessions the intersection dropped, so a short variant cannot
    silently cut the sample."""
    rows = entries(counter, trials=trials, root=root)
    if not rows:
        raise ValueError(f"no stored series on {counter}")
    cols = {f"{r['trial']}/{r['variant']}": load(r, root=root) for r in rows}
    full = pd.concat(cols, axis=1)
    common = full.dropna()
    return common, dict(n_variants=len(cols), union_sessions=len(full),
                        common_sessions=len(common), dropped=len(full) - len(common))


def bar_inputs(counter: str, *, root: Path = ROOT) -> dict:
    """Everything the paper's deflated-Sharpe bar needs beyond the selected
    strategy, measured now from the stored series. It also says whether the
    paper's bar may gate under the 2026-10-27 ruling.

    `coverage` compares the stored TRIALS with the counter's canonical count.
    The ruling is that the paper's bar gates "once trials store their daily
    P&L series". While some of the counter's trials have no stored series, the
    measured rho_bar and V[SR] describe only part of the search, so
    `paper_bar_may_gate` is False and the desk's bar gates. This is measured at
    every call (H14). Whether to backfill old trials is the team lead's
    decision (DESK_METHOD §7 item 6).

    rho_bar is the mean off-diagonal correlation of the variants' P&L on their
    common sessions, floored at 0 because effective_trials needs 0 <= rho <= 1.
    `ill_conditioned` is True when T < M(M-1)/2: there are too few sessions to
    pin down M(M-1)/2 correlations (López de Prado & Lewis 2019).
    """
    from scripts.research.inference import effective_trials
    canon = _counters()[counter]["trials"]
    M, info = matrix(counter, root=root)
    stored_trials = sorted({c.split("/", 1)[0] for c in M.columns})
    m = M.shape[1]
    if m >= 2:
        C = M.corr().to_numpy()
        rho = float(C[~np.eye(m, dtype=bool)].mean())
    else:
        rho = 1.0
    rho_c = min(max(rho, 0.0), 1.0)
    sr = M.mean() / M.std(ddof=1)                       # per period
    return dict(counter=counter, canonical_trials=canon, stored_trials=len(stored_trials),
                coverage=len(stored_trials) / canon if canon else None,
                paper_bar_may_gate=bool(canon) and len(stored_trials) >= canon,
                variants=m, T=info["common_sessions"], dropped_sessions=info["dropped"],
                rho_bar=rho, n_effective=effective_trials(m, rho_c),
                sr_var=float(sr.var(ddof=1)) if m >= 2 else None,
                ill_conditioned=info["common_sessions"] < m * (m - 1) / 2)
