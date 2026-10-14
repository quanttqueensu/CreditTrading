"""Correlation of the live CEF book's P&L with short-variance legs on TLT and HYG.

    python3 scripts/gamma/book_vs_shortvol.py [--vol-panel PATH]

G2(c) of `results/cef/RESEARCH_PLAN_2026-10-09.md` ("correlation with the book")
and the "-0.01 daily, -0.11 monthly" of `SCALING_RESEARCH_2026-10-08.md` §7.1
row 3 (and HYG's "+0.09 / the book loses on the same days", row 10). Re-run of a
2026-10-09 scratch script (`book_vs_shortvol.py`, deleted with its session).
Descriptive, 0 trials; no position in any option is formed or scored.

THE BOOK
--------
The live v7 policy exactly as `scripts/xasset/book_profile.py` builds it: the
spec's band, gross-capped at the spec's `max_gross_stress`, P&L from
`band_frontier.evaluate()` -- `H.shift(2)`: decided at t, MOC fill at t+1, earns
the t+2 return (H1) -- on TOTAL returns (H15), from the book's first position
(pre-2013 is flat, CLAUDE.md landmine 8). Every parameter is read from the
frozen spec through `scripts/cef/spec.py`; none is written here.

THE SHORT-VARIANCE LEG (two constructions, never mixed)
-------------------------------------------------------
1. **Daily, the scratch run's proxy** -- the P&L per unit dollar-gamma of a
   delta-hedged short option position over day t:
       s_t = 0.5 * (IV_{t-1}^2 / 252 - r_t^2)
   with IV_{t-1} the Cboe index at the PREVIOUS session's close (no lookahead:
   known before day t) and r_t the ETF's day-t log total return. Correlated
   same-day with the book's day-t P&L; "monthly" = sums over consecutive
   non-overlapping 21-row blocks of the joint sample, as the scratch run did,
   and (added) over calendar months.
2. **Monthly, added here as a second method** -- the gross P&L of a short
   30-day variance swap struck at VXTLT_t^2 and held over sessions t+1..t+21
   (IV_t^2 - RV_{t+1..t+21}^2), on the non-overlapping IV-date sample, against
   the book's summed P&L over the same sessions t+1..t+21.

"About 0" is judged with a Fisher-z 95% interval, not by eye.

THE HOLDOUT (corrected 2026-10-13)
----------------------------------
2023+ returns are sealed (`docs/SYSTEM.md` §5: the GAMMA holdout; team lead
2026-10-12, spreads and costs may be used, return statistics stay sealed). Until
2026-10-13 this script broke that twice, and an independent review caught both:
it printed a labelled "2023+" block of book-vs-leg correlations on every run, and
the second method filtered only the IV DATE t <= 2022-12-31, so its last window
ran over sessions into January 2023. Now nothing after 2022 is printed, and
`varswap_windows` keeps only windows whose LAST session is on or before the
window bound, and refuses a bound in 2023 or later. `docs/RESEARCH_STATE.md`
records the touch.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import (build_targets, band_gross_capped,   # noqa: E402
                                       evaluate, total_returns)
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS                    # noqa: E402
from scripts.gamma.vrp_summary import load_iv, DEFAULT_PANEL, ETF_PANEL, H  # noqa: E402

LEGS = {"TLT": "VXTLT", "HYG": "VXHYG"}
FIT_END = "2022-12-31"
SEALED_FROM = pd.Timestamp("2023-01-01")      # 2023+ returns: the GAMMA holdout


def fisher_ci(r: float, n: int) -> tuple[float, float]:
    z, se = np.arctanh(r), 1.0 / np.sqrt(n - 3)
    return float(np.tanh(z - 1.96 * se)), float(np.tanh(z + 1.96 * se))


def book_pnl() -> pd.Series:
    if MAX_GROSS_STRESS is None:
        raise RuntimeError("spec has no max_gross_stress; the live book is gross-capped")
    T, R = build_targets()
    Hb = band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)
    first = Hb.abs().sum(axis=1).gt(0).idxmax()
    pnl = evaluate(Hb, total_returns(R))["pnl"]       # shift(2) inside evaluate()
    return pnl[pnl.index >= first].rename("book")


def describe(df: pd.DataFrame, leg: str) -> str:
    x = df[["book", leg]].dropna()
    n = len(x)
    rho = x.corr().iloc[0, 1]
    lo, hi = fisher_ci(rho, n)
    k = (n // H) * H
    m = x.iloc[:k].groupby(np.arange(k) // H).sum()
    rm = m.corr().iloc[0, 1]
    mlo, mhi = fisher_ci(rm, len(m))
    cm = x.resample("ME").sum()
    cm = cm[x.resample("ME").size() >= 15]          # drop stub months at the ends
    rc = cm.corr().iloc[0, 1]
    q = x["book"].quantile(0.05)
    wb = x[x["book"] <= q]
    ql = x[leg].quantile(0.05)
    wl = x[x[leg] <= ql]
    return (f"n={n} {x.index.min().date()}..{x.index.max().date()} | daily rho {rho:+.3f} "
            f"[{lo:+.3f},{hi:+.3f}] | 21-row blocks rho {rm:+.3f} [{mlo:+.3f},{mhi:+.3f}] "
            f"(n={len(m)}) | calendar months rho {rc:+.3f} (n={len(cm)}) | on the book's worst "
            f"5% days leg z {(wb[leg].mean()-x[leg].mean())/x[leg].std():+.2f} | on the leg's "
            f"worst 5% days book {wl['book'].mean()*1e4:+.1f}bp vs {x['book'].mean()*1e4:+.1f}bp")


def varswap_windows(book: pd.Series, iv: pd.Series, ret: pd.Series, a: str, b: str) -> pd.DataFrame:
    """Non-overlapping short var-swap P&L and the book's P&L over the same
    sessions t+1..t+21, for IV dates t >= a whose WHOLE window ends on or
    before b. Corrected 2026-10-13: the filter used to test only t <= b, so the
    last window ran into January 2023 (sealed). A bound in 2023+ is refused."""
    b_ts = pd.Timestamp(b)
    if b_ts >= SEALED_FROM:
        raise ValueError(f"window bound {b} is in the sealed 2023+ holdout (docs/SYSTEM.md §5)")
    idx = ret.index
    iv = iv.reindex(idx)
    lr2 = np.log1p(ret) ** 2
    b_on = book.reindex(idx)
    rows = []
    for i in range(0, len(idx) - H):
        t = idx[i]
        end = idx[i + H]                            # the window's last session
        if not (pd.Timestamp(a) <= t and end <= b_ts) or pd.isna(iv.iloc[i]):
            continue
        win = slice(i + 1, i + 1 + H)               # sessions t+1..t+21: strictly after t
        rv2 = 252.0 / H * lr2.iloc[win].sum()
        bk = b_on.iloc[win]
        if bk.isna().any() or lr2.iloc[win].isna().any():
            continue
        rows.append((t, end, iv.iloc[i] ** 2 - rv2, bk.sum()))
    d = pd.DataFrame(rows, columns=["t", "end", "leg", "book"]).set_index("t").iloc[::H]
    if not (d["end"] <= b_ts).all():
        raise AssertionError("a var-swap window ends after its bound")
    return d


def varswap_vs_book(book: pd.Series, iv: pd.Series, ret: pd.Series, a: str, b: str) -> str:
    """Second method: non-overlapping short var-swap P&L vs the book over the same sessions."""
    d = varswap_windows(book, iv, ret, a, b)
    r = d[["leg", "book"]].corr().iloc[0, 1]
    lo, hi = fisher_ci(r, len(d))
    return (f"non-overlapping n={len(d)} (IV dates {d.index.min().date()}..{d.index.max().date()}, "
            f"last window ends {d['end'].max().date()}) rho {r:+.3f} [{lo:+.3f},{hi:+.3f}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vol-panel", default=str(DEFAULT_PANEL))
    a = ap.parse_args()
    book = book_pnl()
    e = pd.read_parquet(ETF_PANEL)
    W = e.pivot(index="date", columns="ticker", values="ret_total")
    print(f"book (v7 band {BAND_WIDTH}, gross cap {MAX_GROSS_STRESS}, total returns, shift(2)): "
          f"first position {book.index.min().date()}, last {book.index.max().date()}; "
          f"etf_panel last {e['date'].max().date()}")
    legs = {}
    for u, idx in LEGS.items():
        iv = load_iv(Path(a.vol_panel), idx).reindex(W.index).shift(1)   # IV at t-1 close
        legs[f"shortvol_{u}"] = 0.5 * (iv ** 2 / 252 - np.log1p(W[u]) ** 2)
    df = book.to_frame().join(pd.DataFrame(legs), how="left")
    # The fit window only. A "2023+ (labelled, no inference)" block was printed
    # here until 2026-10-13; it was a sealed return statistic and is deleted.
    lab, s, t = "fit, first position..2022", str(book.index.min().date()), FIT_END
    print(f"\n== {lab}")
    x = df.loc[s:t]
    if x.index.max() >= SEALED_FROM:
        raise AssertionError("the fit block reaches a sealed 2023 date")
    for c in legs:
        if x[["book", c]].dropna().shape[0] < 60:
            print(f"  {c}: too few joint days")
            continue
        print(f"  {c}: {describe(x, c)}")
    print("\n== second method: short 30d variance swap (IV_t^2 - RV_t+1..t+21^2) vs book P&L over "
          "t+1..t+21, fit window")
    for u, idx in LEGS.items():
        iv = load_iv(Path(a.vol_panel), idx)
        print(f"  {u}: {varswap_vs_book(book, iv, W[u].dropna(), str(book.index.min().date()), FIT_END)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
