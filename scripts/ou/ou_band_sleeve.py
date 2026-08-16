"""D2 response: OU-optimal bands on wrapper pairs, breadth from instruments.

WHY THIS EXISTS. The naive HYG/JNK z-score pair (benchmark B7) has a GROSS Sharpe
of +0.54 in 2023-26 and a NET Sharpe of -0.25. That is not a dead signal, it is
D2: a real edge destroyed by trading it too often. The prescribed response is to
re-derive the entry band from the mean-reversion parameters and the MEASURED
round-trip cost, so each trade is only taken when its expected capture pays for
itself several times over.

THE BAND. Fit an OU process to the pair spread (as an AR(1), point-in-time on a
trailing window only). That gives:
    phi        persistence
    sigma_eq   equilibrium sd of the spread = resid_sd / sqrt(1 - phi^2)
    halflife   -ln2 / ln(phi)
Entering at k*sigma_eq and exiting at the mean captures ~k*sigma_eq per leg, so a
round trip captures ~2*k*sigma_eq against a round-trip cost c. Requiring the
gate's 2.5x margin:

    2 * k * sigma_eq >= 2.5 * c      =>      k = 1.25 * c / sigma_eq

k is therefore MEASURED, not searched. Cheap, wide-dispersion pairs get tight
bands and trade often; expensive, tight pairs get wide bands and rarely trade.
That is the whole point -- one specification, no per-pair tuning.

BREADTH, NOT PARAMETERS. The same single specification is applied to every
same-class pair we can trade. Grinold: IR ~ IC * sqrt(BR). Adding pairs adds
independent bets without burning statistical budget, because no parameter is
re-fitted per pair. Adding parameters would be the opposite.

NEUTRALITY. Every pair is within one asset class and beta-hedged on a trailing
window, so no leg carries a credit or duration view. Treasury pairs are included
ONLY as a negative control and are never traded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

OUT = REPO / "results/ou"
OUT.mkdir(parents=True, exist_ok=True)
CM = SCENARIOS["base"]

# within-class pairs only. (long, short, class)
PAIRS = [
    ("HYG", "JNK", "HY"), ("HYG", "USHY", "HY"), ("JNK", "USHY", "HY"),
    ("SHYG", "HYG", "HY"), ("SJNK", "JNK", "HY"), ("SPHY", "USHY", "HY"),
    ("LQD", "VCIT", "IG"), ("LQD", "USIG", "IG"), ("IGIB", "VCIT", "IG"),
    ("IGSB", "VCSH", "IG"), ("SPIB", "IGIB", "IG"), ("SPSB", "IGSB", "IG"),
    ("IGLB", "VCLT", "IGL"), ("SPLB", "IGLB", "IGL"),
    ("MBB", "VMBS", "MBS"), ("SPMB", "MBB", "MBS"),
    ("PFF", "PGX", "PREF"), ("PFFD", "PFF", "PREF"),
    ("MUB", "TFI", "MUNI"), ("HYD", "HYMB", "MUNI"),
    ("EMB", "PCY", "EM"), ("VWOB", "EMB", "EM"),
    ("BKLN", "SRLN", "LOAN"),
    # negative controls -- measured, never traded
    ("IEF", "IEI", "UST_ctl"), ("TLT", "TLH", "UST_ctl"), ("SHY", "IEI", "UST_ctl"),
]

WIN = 252          # trailing window for the hedge ratio (stable beta)
REV_WIN = 21       # window the DISLOCATION is measured against (1-10d horizon)
MIN_MULT = 2.5     # the gate: expected capture must be >= 2.5x round-trip cost


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    for p in ["data/rv/etf_ohlc.parquet", "data/rv/etf_ohlc_extended.parquet"]:
        f = REPO / p
        if f.exists():
            o = pd.read_parquet(f)
            o["date"] = pd.to_datetime(o["date"])
            frames.append(o[["date", "ticker", "high", "low", "close", "volume"]])
    o = pd.concat(frames).sort_values("date").drop_duplicates(
        subset=["date", "ticker"], keep="last")
    last = o.date.max()
    if o[o.date == last].ticker.nunique() < 0.8 * o.ticker.nunique():
        o = o[o.date < last]                       # partial final bar
    cl = o.pivot_table(index="date", columns="ticker", values="close")
    hi = o.pivot_table(index="date", columns="ticker", values="high")
    lo = o.pivot_table(index="date", columns="ticker", values="low")
    vol = o.pivot_table(index="date", columns="ticker", values="volume")
    return cl, (hi + lo) / 2.0, (cl * vol).rolling(21, min_periods=5).mean().shift(1)


def rt_cost_bp(a: str, b: str, cl: pd.DataFrame, adv: pd.DataFrame) -> float:
    """Round trip on BOTH legs: in and out, two instruments."""
    pa, pb = cl[a].iloc[-1], cl[b].iloc[-1]
    aa, ab = adv[a].iloc[-1], adv[b].iloc[-1]
    return 2.0 * (CM.half_spread_bp(pa, aa, a) + CM.half_spread_bp(pb, ab, b))


def build_pair(a: str, b: str, cl: pd.DataFrame, mid: pd.DataFrame,
               adv: pd.DataFrame, start="2019-01-01"):
    """PIT spread, OU fit and measured band. Returns a per-date frame."""
    idx = cl.index[(cl.index >= start) & cl[a].notna() & cl[b].notna()]
    if len(idx) < WIN + 250:
        return None
    # Hedge ratio on log prices, trailing window, lagged one day so today's
    # observation never enters its own hedge.
    la, lb = np.log(mid[a].reindex(idx)), np.log(mid[b].reindex(idx))
    cov = la.rolling(WIN).cov(lb)
    var = lb.rolling(WIN).var()
    beta = (cov / var).shift(1).clip(0.2, 3.0)
    spread = la - beta * lb

    # The DISLOCATION lives at a 1-10 day horizon; the spread LEVEL drifts over a
    # year as the two funds' compositions diverge. Measuring sigma on a 252-day
    # window therefore captures that drift (it returned sigma_eq ~ 78%), the
    # z-score collapses, the band pins to its floor and the "trade" becomes a
    # slow trend-follower -- which is why the Treasury control won. Anchor on a
    # short window so the deviation is the dislocation and nothing else.
    mu = spread.rolling(REV_WIN).mean().shift(1)
    sd = spread.rolling(REV_WIN).std().shift(1)
    dev = spread - mu
    phi = dev.rolling(WIN).corr(dev.shift(1)).shift(1).clip(-0.95, 0.95)
    sigma_eq = sd
    halflife = -np.log(2) / np.log(phi.abs().clip(0.05, 0.95))

    c_bp = rt_cost_bp(a, b, cl, adv)
    # k measured from cost and dispersion, not searched
    k = (MIN_MULT / 2.0) * (c_bp / 1e4) / sigma_eq.replace(0, np.nan)
    k = k.clip(0.75, 5.0)
    z = dev / sigma_eq.replace(0, np.nan)
    return pd.DataFrame({"z": z, "k": k, "phi": phi, "halflife": halflife,
                         "sigma_eq_bp": sigma_eq * 1e4, "beta": beta,
                         "cost_bp": c_bp}, index=idx)


def band_position(z: pd.Series, k: pd.Series) -> pd.Series:
    """Enter at -/+k, exit at 0. Short the spread when rich, long when cheap."""
    pos, cur = [], 0.0
    for zi, ki in zip(z.values, k.values):
        if not (np.isfinite(zi) and np.isfinite(ki)):
            pos.append(cur); continue
        if cur == 0.0:
            cur = -1.0 if zi >= ki else (1.0 if zi <= -ki else 0.0)
        elif (cur > 0 and zi >= 0) or (cur < 0 and zi <= 0):
            cur = 0.0
        pos.append(cur)
    return pd.Series(pos, index=z.index)


def main() -> int:
    cl, mid, adv = load()
    rows, weights = [], {}
    for a, b, klass in PAIRS:
        if a not in cl.columns or b not in cl.columns:
            continue
        f = build_pair(a, b, cl, mid, adv)
        if f is None:
            continue
        pos = band_position(f.z, f.k)
        # returns on the MID (bounce-free), executed with the repo's t+1 lag
        ra = mid[a].pct_change(fill_method=None).reindex(f.index)
        rb = mid[b].pct_change(fill_method=None).reindex(f.index)
        held = pos.shift(1).fillna(0.0)
        gross = held * (ra - f.beta * rb)
        turn = held.diff().abs().fillna(0) * (1 + f.beta)
        cost = turn * (f.cost_bp / 2.0) / 1e4         # cost_bp is a full round trip
        net = (gross - cost).replace([np.inf, -np.inf], np.nan).dropna()
        if len(net) < 400 or net.std() == 0:
            continue
        ann = np.sqrt(252)
        rows.append(dict(
            pair=f"{a}/{b}", klass=klass, n=len(net),
            trades=int((held.diff().abs() > 0).sum() / 2),
            gross_sr=gross.dropna().mean() / gross.dropna().std() * ann,
            net_sr=net.mean() / net.std() * ann,
            cagr=100 * ((1 + net).prod() ** (252 / len(net)) - 1),
            vol=100 * net.std() * ann,
            k_med=f.k.median(), sigma_bp=f.sigma_eq_bp.median(),
            cost_bp=f.cost_bp.iloc[0], hl=f.halflife.median(),
            time_on=100 * (held != 0).mean()))
        if klass != "UST_ctl":
            weights[f"{a}/{b}"] = net
    r = pd.DataFrame(rows).sort_values("net_sr", ascending=False)
    r.to_csv(OUT / "ou_pairs.csv", index=False)

    print("=" * 112)
    print("OU-BAND PAIRS -- band width MEASURED from cost and dispersion, not searched")
    print(f"  entry k = {MIN_MULT/2:.2f} * roundtrip_cost / sigma_eq   (gate: capture >= {MIN_MULT}x cost)")
    print("  2019+, mid returns, t+1 execution, measured IBKR spreads")
    print("=" * 112)
    print(f"{'pair':<13}{'class':<9}{'n':>6}{'trades':>8}{'gross SR':>10}"
          f"{'net SR':>9}{'CAGR%':>8}{'vol%':>7}{'k':>6}{'sig bp':>8}"
          f"{'cost bp':>9}{'HL':>6}{'on%':>7}")
    for _, x in r.iterrows():
        tag = "  <- CONTROL" if x.klass == "UST_ctl" else ""
        print(f"{x.pair:<13}{x.klass:<9}{x.n:>6,.0f}{x.trades:>8.0f}{x.gross_sr:>10.2f}"
              f"{x.net_sr:>9.2f}{x.cagr:>8.2f}{x.vol:>7.2f}{x.k_med:>6.2f}"
              f"{x.sigma_bp:>8.0f}{x.cost_bp:>9.2f}{x.hl:>6.1f}{x.time_on:>7.0f}{tag}")

    tradable = r[r.klass != "UST_ctl"]
    ctl = r[r.klass == "UST_ctl"]
    print(f"\n  tradable pairs: mean net SR {tradable.net_sr.mean():+.2f}, "
          f"{int((tradable.net_sr > 0).sum())}/{len(tradable)} positive")
    print(f"  UST CONTROL   : mean net SR {ctl.net_sr.mean():+.2f}, "
          f"{int((ctl.net_sr > 0).sum())}/{len(ctl)} positive  <- must be ~0")

    if weights:
        W = pd.DataFrame(weights).dropna(how="all")
        eq = W.fillna(0.0).mean(axis=1)
        ann = np.sqrt(252)
        cm = W.corr().values
        off = cm[~np.eye(len(cm), dtype=bool)]
        print(f"\n  EQUAL-WEIGHT COMBINATION of {W.shape[1]} tradable pairs")
        print(f"    mean pairwise correlation  {np.nanmean(off):+.3f}")
        print(f"    combined net Sharpe        {eq.mean()/eq.std()*ann:+.2f}")
        print(f"    combined vol               {eq.std()*ann*100:.2f}%")
        n, rho = W.shape[1], max(np.nanmean(off), 0.0)
        s_avg = tradable.net_sr.mean()
        print(f"    theory S*sqrt(N/(1+(N-1)rho)) = "
              f"{s_avg*np.sqrt(n/(1+(n-1)*rho)):+.2f}")
        W.to_parquet(OUT / "pair_returns.parquet")
    print(f"\nwrote {OUT/'ou_pairs.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
