"""Re-run the bounce-free book with MEASURED IBKR spreads instead of modelled ones.

This is not a new search. It swaps ONE INPUT — the per-name half-spread — from a
modelled tick-floor estimate to a quantity measured from IBKR's own quoted book,
and re-runs the configuration grid that was already run against the modelled
number. The signal, the factor neutralisation, the smoothing rule and the universe
rule are all unchanged.

That distinction matters for trial accounting. Correcting a mis-specified input is
not the same as hunting configurations: it cannot manufacture a false positive by
itself, because it moves every cell in the grid by the same multiplicative factor.
The grid is still 16 cells wide, so best-cell selection is still deflated below,
and the sealed holdout remains the real test.

The book being run is the one that survived Phase 0:
    signal from (H+L)/2 mid  ->  executed at the next close     ["mid -> close"]
which is the only cell of the 2x2 that is both bounce-free and executable.

Cost here is spread only. That is deliberate and it is the honest treatment for
this book: per §8c impact inside the displayed touch is zero for an ETF, and the
financing on a dollar-neutral book is a borrow fee on the short leg, both of which
are reported separately rather than smuggled into the spread term.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "credit_rv"

from src.strategies.credit_rv.signal import SignalConfig, compute_signals  # noqa: E402
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

IS_START, IS_END = pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31")

CREDIT = ["HYG", "JNK", "USHY", "SPHY", "SHYG", "SJNK", "HYGH", "ANGL", "FALN",
          "LQD", "VCSH", "VCIT", "VCLT", "IGSB", "LQDH",
          "BKLN", "SRLN", "JAAA", "JBBB", "EMB", "PFF", "CWB"]


def load_measured() -> tuple[dict, str]:
    """Per-name measured half-spread in bp. Prefers the closing-window figure."""
    f = OUT / "ibkr_measured_spreads.csv"
    if not f.exists():
        raise SystemExit("no ibkr_measured_spreads.csv - run fetch_ibkr_spreads.py first")
    m = pd.read_csv(f)
    half, src = {}, {}
    for _, r in m.iterrows():
        t = r["ticker"]
        v = r.get("close_half_spread_bp")
        if pd.notna(v):
            half[t], src[t] = float(v), "close_window"
        elif pd.notna(r.get("half_spread_bp_median")):
            half[t], src[t] = float(r["half_spread_bp_median"]), "daily_avg"
    n_close = sum(1 for v in src.values() if v == "close_window")
    return half, f"{len(half)} names ({n_close} from closing window)"


def build_panel():
    p = pd.read_parquet(ROOT / "data/rv/etf_ohlc.parquet")
    p = p[p.date <= IS_END]
    rf = pd.read_parquet(ROOT / "data/riskfree_daily.parquet").set_index("date")["rf_daily"]
    rf.index = pd.to_datetime(rf.index)
    ret_close = p.pivot(index="date", columns="ticker", values="ret_total").sort_index()
    mid = p.pivot(index="date", columns="ticker", values="mid_hl").sort_index()
    div = p.pivot(index="date", columns="ticker", values="dividend").sort_index().fillna(0.0)
    ret_mid = (mid + div) / mid.shift(1) - 1.0
    dv = p.assign(dv=p.close * p.volume).pivot(
        index="date", columns="ticker", values="dv").sort_index()
    return ret_close, ret_mid, dv, rf


_SIG_CACHE = {}


def _signals(ret_mid, rf, dv, keep):
    """compute_signals depends only on the universe, not on the smoothing
    constant, so cache it across the smoothing sweep."""
    key = tuple(keep)
    if key not in _SIG_CACHE:
        _SIG_CACHE[key] = compute_signals(ret_mid, rf, dv,
                                          SignalConfig(tradeable=list(keep)))
    return _SIG_CACHE[key]


def run(ret_close, ret_mid, dv, rf, half, max_hs, smooth, cost_mult=1.0):
    keep = [c for c in CREDIT if c in half and half[c] <= max_hs]
    if len(keep) < 6:
        return None
    sig = _signals(ret_mid, rf, dv, keep)
    S = sig["s_blend"]
    S = S[S.index >= IS_START]
    betas, cols = sig["betas"], list(S.columns)
    rt = ret_close.reindex(columns=cols)
    hs = np.array([half[c] for c in cols]) / 1e4 * cost_mult

    W, P = [], []
    prev = None
    for d in S.index:
        B = betas.get(d)
        if B is None or d not in rt.index:
            continue
        j = rt.index.get_loc(d)
        if j + 1 >= len(rt):
            continue
        s = S.loc[d].values.astype(float)
        ok = np.isfinite(s)
        if ok.sum() < 4:
            continue
        w = np.zeros(len(cols))
        w[ok] = -s[ok]
        w[ok] -= w[ok].mean()
        Bv = B.reindex(cols).values
        good = ok & np.isfinite(Bv).all(axis=1)
        if good.sum() < 7:
            continue
        Bk, wk = Bv[good], w[good]
        wk = wk - Bk @ np.linalg.solve(Bk.T @ Bk + 1e-10 * np.eye(Bk.shape[1]), Bk.T @ wk)
        w = np.zeros(len(cols))
        w[good] = wk - wk.mean()
        n = np.abs(w).sum()
        if n < 1e-12:
            continue
        w /= n
        if prev is not None and smooth > 1:
            a = 2.0 / (smooth + 1.0)
            w = a * w + (1 - a) * prev
            n = np.abs(w).sum()
            w = w / n if n > 1e-12 else w
        prev = w
        W.append(w)
        P.append(float(w @ np.nan_to_num(rt.iloc[j + 1].values, nan=0.0)))

    if len(P) < 200:
        return None
    W = np.array(W)
    P = pd.Series(P)
    dW = np.abs(np.diff(W, axis=0))
    cost = (dW * hs).sum(axis=1)
    net = P.iloc[1:].reset_index(drop=True) - cost
    sr = net.mean() / net.std() * np.sqrt(252)
    lev = 0.13 / (net.std() * np.sqrt(252))
    cagr = (1 + net * lev).prod() ** (252 / len(net)) - 1
    turn = dW.sum(axis=1).mean() * 252
    gross_yr = P.mean() * 252 * 100
    cost_yr = cost.mean() * 252 * 100
    return dict(max_hs=max_hs, smooth=smooth, n_names=len(keep), names=keep,
                turn=turn, gross=gross_yr, cost=cost_yr, sr_net=sr,
                cagr13=cagr * 100, n_obs=len(net),
                # the scale-invariant economics that decide everything
                earn_bp_per_turn=(P.iloc[1:].mean() / dW.sum(axis=1).mean()) * 1e4
                if dW.sum(axis=1).mean() > 0 else np.nan,
                pay_bp_per_turn=(cost.mean() / dW.sum(axis=1).mean()) * 1e4
                if dW.sum(axis=1).mean() > 0 else np.nan)


def main() -> int:
    half_meas, prov = load_measured()
    cm = SCENARIOS["base"]
    ret_close, ret_mid, dv, rf = build_panel()

    p = pd.read_parquet(ROOT / "data/rv/etf_ohlc.parquet")
    pxl = p.pivot(index="date", columns="ticker", values="close").ffill().iloc[-1]
    advm = p.assign(dv=p.close * p.volume).pivot(
        index="date", columns="ticker", values="dv").sort_index().tail(180).median()
    half_model = {c: cm.half_spread_bp(float(pxl.get(c, 50) or 50),
                                       float(advm.get(c, 0) or 0)) for c in CREDIT}

    print(f"MEASURED SPREADS: {prov}\n")
    print(f"{'name':>6s} {'modelled':>9s} {'measured':>9s} {'ratio':>7s}")
    rows = []
    for c in CREDIT:
        if c not in half_meas:
            print(f"{c:>6s} {half_model[c]:>8.2f}bp {'--':>9s} {'--':>7s}")
            continue
        r = half_meas[c] / half_model[c] if half_model[c] > 0 else np.nan
        rows.append(dict(ticker=c, modelled=half_model[c], measured=half_meas[c], ratio=r))
        print(f"{c:>6s} {half_model[c]:>8.2f}bp {half_meas[c]:>8.2f}bp {r:>7.2f}x")
    cmp = pd.DataFrame(rows)
    cmp.to_csv(OUT / "spread_model_vs_measured.csv", index=False)
    if not cmp.empty:
        print(f"\nmedian measured/modelled ratio: {cmp['ratio'].median():.2f}x")

    print("\n" + "=" * 78)
    print("BOOK RE-RUN WITH MEASURED COSTS  (mid signal -> close execution)")
    print("=" * 78)
    print(f"{'max hs':>7s} {'names':>6s} {'smooth':>7s} {'turn':>6s} {'gross%':>8s} "
          f"{'cost%':>7s} {'SR net':>8s} {'CAGR@13%':>9s} {'earn bp':>8s} {'pay bp':>7s}")

    results = []
    for mh in [0.8, 1.2, 1.8, 2.5, 4.0]:
        for sm in [1, 5, 10, 20, 40]:
            r = run(ret_close, ret_mid, dv, rf, half_meas, mh, sm)
            if r is None:
                continue
            results.append(r)
            print(f"{mh:>7.1f} {r['n_names']:>6d} {sm:>7d} {r['turn']:>6.0f} "
                  f"{r['gross']:>7.2f}% {r['cost']:>6.2f}% {r['sr_net']:>8.2f} "
                  f"{r['cagr13']:>8.2f}% {r['earn_bp_per_turn']:>8.2f} "
                  f"{r['pay_bp_per_turn']:>7.2f}")

    if not results:
        print("no runnable configuration")
        return 1

    df = pd.DataFrame([{k: v for k, v in r.items() if k != "names"} for r in results])
    df.to_csv(OUT / "measured_cost_grid.csv", index=False)
    best = max(results, key=lambda r: r["sr_net"])

    # Deflate for selecting the best of this grid (Bailey/Lopez de Prado, N cells).
    n_cells = len(results)
    e_max = np.sqrt(2 * np.log(max(n_cells, 2)))          # expected max |z| under null
    sr_se = np.sqrt((1 + 0.5 * best["sr_net"] ** 2) / best["n_obs"]) * np.sqrt(252)
    dsr_haircut = e_max * sr_se

    print("\n" + "-" * 78)
    print(f"BEST CELL: SR {best['sr_net']:.2f}  CAGR@13% {best['cagr13']:.2f}%  "
          f"({best['n_names']} names, hs<={best['max_hs']}bp, smooth={best['smooth']})")
    print(f"  earns {best['earn_bp_per_turn']:.2f}bp per unit turnover, "
          f"pays {best['pay_bp_per_turn']:.2f}bp")
    print(f"  selection over {n_cells} cells -> Sharpe haircut ~{dsr_haircut:.2f}")
    print(f"  DEFLATED Sharpe ~= {best['sr_net'] - dsr_haircut:.2f}")
    print(f"  names: {best['names']}")

    json.dump({k: (v if not isinstance(v, (np.floating, np.integer)) else float(v))
               for k, v in best.items()},
              open(OUT / "measured_best_cell.json", "w"), indent=2, default=str)
    print(f"\nwrote {OUT/'measured_cost_grid.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
