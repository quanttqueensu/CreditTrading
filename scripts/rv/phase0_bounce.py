"""PHASE 0 — is the lag-1 reversal real, or is it bid-ask bounce?

Three independent lines of evidence:

  A. ROLL (1984) effective spread from serial covariance of price changes:
         s_eff = 2*sqrt(-Cov(dp_t, dp_{t-1}))     when the covariance is negative
     Bounce is the ONLY thing that makes that covariance negative in an efficient
     price, so this estimates each name's implied spread from returns alone.

  B. CORWIN-SCHULTZ (2012) high-low estimator, which uses entirely different
     information (daily ranges) and is therefore an independent check on A.

  C. THE DECISIVE TEST — a 2x2. Bounce lives in the CLOSE. If the lag-1 edge is
     bounce, it exists only when the signal and the return share the same
     contaminated close price, and must collapse when either side is computed on a
     bounce-free mid proxy (H+L)/2:

                          return measured on
                        close            mid
        signal   close   contaminated     clean-ish
        built    mid     clean-ish        clean

     Real predictive information survives all four cells. Bounce survives only the
     top-left.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals  # noqa: E402
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

IS_START, IS_END = pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31")


def roll_spread(ret: pd.Series, window: int = 252) -> pd.Series:
    """Roll (1984) effective half-spread in bp, rolling."""
    d = ret.dropna()
    cov = d.rolling(window).cov(d.shift(1))
    s = 2.0 * np.sqrt(np.clip(-cov, 0.0, None))
    return (s / 2.0) * 1e4          # half-spread in bp


def corwin_schultz(h: pd.Series, l: pd.Series, window: int = 252) -> pd.Series:
    """Corwin-Schultz (2012) high-low spread estimator, half-spread in bp."""
    hl = np.log(h / l) ** 2
    beta = (hl + hl.shift(1)).rolling(window).mean()
    h2 = pd.concat([h, h.shift(1)], axis=1).max(axis=1)
    l2 = pd.concat([l, l.shift(1)], axis=1).min(axis=1)
    gamma = (np.log(h2 / l2) ** 2).rolling(window).mean()
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(np.clip(gamma, 0, None) / k)
    S = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return np.clip(S, 0, None) / 2.0 * 1e4


def main() -> int:
    p = pd.read_parquet(ROOT / "data/rv/etf_ohlc.parquet")
    p = p[p["date"] <= IS_END]
    rf = pd.read_parquet(ROOT / "data/riskfree_daily.parquet").set_index("date")["rf_daily"]
    rf.index = pd.to_datetime(rf.index)

    ret_close = p.pivot(index="date", columns="ticker", values="ret_total").sort_index()
    # mid total return: (mid_t + div_t)/mid_{t-1} - 1, same dividend convention
    mid = p.pivot(index="date", columns="ticker", values="mid_hl").sort_index()
    div = p.pivot(index="date", columns="ticker", values="dividend").sort_index().fillna(0.0)
    ret_mid = (mid + div) / mid.shift(1) - 1.0
    dv = (p.assign(dv=p.close * p.volume)
            .pivot(index="date", columns="ticker", values="dv").sort_index())
    high = p.pivot(index="date", columns="ticker", values="high").sort_index()
    low = p.pivot(index="date", columns="ticker", values="low").sort_index()

    # ---------------- A + B: implied spreads ----------------
    cm = SCENARIOS["base"]
    advm = dv.tail(180).median()
    px_last = p.pivot(index="date", columns="ticker", values="close").ffill().iloc[-1]
    rows = []
    for c in ret_close.columns:
        r = roll_spread(ret_close[c]).dropna()
        cs = corwin_schultz(high[c], low[c]).dropna()
        rows.append({
            "ticker": c,
            "modelled_half_bp": cm.half_spread_bp(float(px_last.get(c, 50) or 50),
                                                  float(advm.get(c, 0) or 0)),
            "roll_half_bp": float(r.median()) if len(r) else np.nan,
            "cs_half_bp": float(cs.median()) if len(cs) else np.nan,
        })
    sp = pd.DataFrame(rows).set_index("ticker")
    sp["roll_vs_model"] = sp.roll_half_bp / sp.modelled_half_bp
    print("=== A/B: implied effective half-spread (bp) ===")
    print(sp.sort_values("roll_half_bp", ascending=False).round(2).to_string())
    print(f"\n  median Roll/modelled ratio: {sp.roll_vs_model.median():.2f}x")
    print("  (>1 means the true tradeable spread is WIDER than the backtest charged)")
    sp.to_csv(ROOT / "results/credit_rv/implied_spreads.csv")

    # ---------------- C: the 2x2 ----------------
    print("\n=== C: 2x2 — does the edge survive a bounce-free price? ===")
    cfg = SignalConfig()
    sig_close = compute_signals(ret_close, rf, dv, cfg)
    sig_mid = compute_signals(ret_mid, rf, dv, cfg)

    def ladder(sig, ret_target, label):
        S = sig["s_blend"]
        S = S[S.index >= IS_START]
        betas = sig["betas"]
        cols = list(S.columns)
        rt = ret_target.reindex(columns=cols)
        out = {}
        for lag in (1, 2, 3):
            pnl = []
            for d in S.index:
                B = betas.get(d)
                if B is None or d not in rt.index:
                    continue
                j = rt.index.get_loc(d)
                if j + lag >= len(rt):
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
                wk = wk - Bk @ np.linalg.solve(
                    Bk.T @ Bk + 1e-10 * np.eye(Bk.shape[1]), Bk.T @ wk)
                w = np.zeros(len(cols))
                w[good] = wk - wk.mean()
                n = np.abs(w).sum()
                if n < 1e-12:
                    continue
                w /= n
                pnl.append(float(w @ np.nan_to_num(rt.iloc[j + lag].values, nan=0.0)))
            ser = pd.Series(pnl)
            out[lag] = (ser.mean() / ser.std() * np.sqrt(252), ser.mean() * 252 * 100)
        print(f"  {label:32s} " + "   ".join(
            f"lag{l}: SR {out[l][0]:5.2f} ({out[l][1]:+5.2f}%/yr)" for l in (1, 2, 3)))
        return out

    a = ladder(sig_close, ret_close, "signal CLOSE -> return CLOSE")
    b = ladder(sig_mid, ret_close, "signal MID   -> return CLOSE")
    c = ladder(sig_close, ret_mid, "signal CLOSE -> return MID")
    d = ladder(sig_mid, ret_mid, "signal MID   -> return MID")

    print("\n=== VERDICT ===")
    base = a[1][0]
    surv = [b[1][0], c[1][0], d[1][0]]
    print(f"  contaminated cell (close->close) lag1 Sharpe : {base:.2f}")
    print(f"  the three cleaner cells                      : "
          f"{surv[0]:.2f}, {surv[1]:.2f}, {surv[2]:.2f}")
    frac = np.mean(surv) / base if base > 0 else np.nan
    print(f"  mean of clean cells as a fraction of the contaminated one: {frac:.0%}")
    if frac < 0.35:
        print("\n  -> BOUNCE. The edge exists only where signal and return share the "
              "same close. Not tradeable.")
    elif frac > 0.7:
        print("\n  -> REAL. The edge survives on bounce-free prices. Tradeable.")
    else:
        print("\n  -> MIXED. Part real, part bounce; size the strategy on the clean cells only.")
    pd.DataFrame({"close_close": {k: v[0] for k, v in a.items()},
                  "mid_close": {k: v[0] for k, v in b.items()},
                  "close_mid": {k: v[0] for k, v in c.items()},
                  "mid_mid": {k: v[0] for k, v in d.items()}}).to_csv(
        ROOT / "results/credit_rv/phase0_2x2.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
