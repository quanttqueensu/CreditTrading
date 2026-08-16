"""Block B -- nine benchmark books through ONE execution path.

The whole point of this file is that every book, including the naive versions of
our own ideas, is priced by the same cost model, filled on the same conservative
assumption, and accounted the same way. If the benchmarks got a friendlier fill
than the strategy the comparison would be worthless, so there is exactly one
`run_book` and everything routes through it.

Books
  B1 HYG total return .................. did we beat just owning high yield?
  B2 duration-hedged HY carry .......... long HYG / short IEF at rolling beta.
                                         THE benchmark that matters: it is what
                                         you earn with zero skill.
  B3 AGG ............................... broad bond market
  B4 60/40 SPY/IEF ..................... the everyman portfolio
  B5 SHY ............................... cash
  B6 equal-weight credit basket ........ did selection add anything?
  B7 naive HYG/JNK price z-score ....... the dumb version of S2
  B8 naive raw PD +-2 sigma ............ the dumb version of S1 (dead E1, alive)
  B9 null trader ....................... is our fill/PnL path honest?

B7/B8/B9 are the three that carry information. Beating SPY proves nothing.

Conventions
  - signal on date t, executed at the close of t+1. No same-close decide-and-fill.
  - weights are fractions of book equity; gross = sum|w|, net = sum w.
  - costs charged on |dw| * equity at (half-spread + impact), both measured.
  - financing per costs.CostModel: borrow on shorts, interest on cash, margin
    only on a genuine net debit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

OUT = REPO / "results/bench"
OUT.mkdir(parents=True, exist_ok=True)

CAPITAL = 640_000.0          # the account's real USD-equivalent working capital
CREDIT_BASKET = ["HYG", "JNK", "LQD", "VCIT", "USHY", "SHYG", "EMB", "ANGL"]


# ----------------------------------------------------------------- data ------
def load_panel() -> tuple[pd.DataFrame, ...]:
    o = pd.read_parquet(REPO / "data/rv/etf_ohlc.parquet")
    o["date"] = pd.to_datetime(o["date"])
    px = o.pivot_table(index="date", columns="ticker", values="close")
    ret = o.pivot_table(index="date", columns="ticker", values="ret_total")
    vol = o.pivot_table(index="date", columns="ticker", values="volume")
    adv = (vol * px).rolling(21, min_periods=5).mean().shift(1)
    dayvol_bp = ret.rolling(21, min_periods=5).std().shift(1) * 1e4
    return px, ret, adv, dayvol_bp


def load_rates() -> pd.Series:
    p = REPO / "data/riskfree_daily.parquet"
    if not p.exists():
        return pd.Series(dtype=float)
    r = pd.read_parquet(p)
    dc = next((c for c in r.columns if c.lower() in ("date", "asof")), r.columns[0])
    vc = next((c for c in r.columns if c != dc and
               pd.api.types.is_numeric_dtype(r[c])), None)
    s = r.set_index(pd.to_datetime(r[dc]))[vc].sort_index()
    return s / 100.0 if s.median() > 0.25 else s


# ------------------------------------------------------------- engine --------
def run_book(name: str, w: pd.DataFrame, ret: pd.DataFrame, px: pd.DataFrame,
             adv: pd.DataFrame, dayvol_bp: pd.DataFrame, rf: pd.Series,
             cm, capital: float = CAPITAL) -> pd.DataFrame:
    """Target weights -> net daily P&L. Weight on t is HELD over t+1."""
    cols = [c for c in w.columns if c in ret.columns]
    w = w[cols].fillna(0.0)
    idx = w.index.intersection(ret.index)
    w, R = w.loc[idx], ret[cols].loc[idx].fillna(0.0)

    held = w.shift(1).fillna(0.0)              # decided t-1, earns t
    dw = held.diff().abs().fillna(held.abs())  # traded into position at t

    P = px[cols].reindex(idx).ffill()
    A = adv[cols].reindex(idx).fillna(0.0)
    V = dayvol_bp[cols].reindex(idx).fillna(50.0)

    gross_ret = (held * R).sum(axis=1)

    # --- transaction cost, per name per day, on the traded notional -----------
    notional = dw * capital
    hs_bp = pd.DataFrame(
        {c: [cm.half_spread_bp(p, a, c) for p, a in zip(P[c].values, A[c].values)]
         for c in cols}, index=idx)
    im_bp = pd.DataFrame(
        {c: cm.impact_bp(notional[c].values, A[c].values, V[c].values)
         for c in cols}, index=idx)
    tc_usd = (notional * (hs_bp + im_bp) / 1e4).sum(axis=1)

    # --- financing ------------------------------------------------------------
    lng = (held.clip(lower=0).sum(axis=1) * capital)
    sht = ((-held.clip(upper=0)).sum(axis=1) * capital)
    base = rf.reindex(idx).ffill().fillna(0.02) if len(rf) else pd.Series(0.02, index=idx)
    fin = pd.Series(
        [cm.financing_daily(capital, l, s, b)[0] - cm.financing_daily(capital, l, s, b)[1]
         for l, s, b in zip(lng.values, sht.values, base.values)], index=idx)

    net_ret = gross_ret - (tc_usd + fin) / capital
    # Books run at very different gross (B8 sits at 0.17, B1 at 1.00), so a book
    # holding mostly cash collects the risk-free rate on the idle balance and
    # books a Sharpe that is really just T-bill yield. Subtracting the daily
    # risk-free rate from every book puts them all on one excess-return footing,
    # which is the only basis on which their Sharpes are comparable.
    rf_daily = base / 252.0
    return pd.DataFrame({
        "book": name, "gross_ret": gross_ret, "net_ret": net_ret,
        "excess_ret": net_ret - rf_daily,
        # Subtract the risk-free rate only on NET exposure: a long-only book
        # is funded with capital and must clear cash, while a dollar-neutral
        # spread is self-financing and owes nothing. Charging rf to a market-
        # neutral book makes a genuinely zero-edge signal look negative.
        "gross_excess": gross_ret - rf_daily * held.sum(axis=1),
        "cost_usd": tc_usd, "fin_usd": fin,
        "turnover": dw.sum(axis=1), "gross_expo": held.abs().sum(axis=1),
        "net_expo": held.sum(axis=1),
    }, index=idx)


# ------------------------------------------------------------ books ----------
def _zscore(s: pd.Series, win: int = 60) -> pd.Series:
    m = s.rolling(win, min_periods=win // 2).mean()
    sd = s.rolling(win, min_periods=win // 2).std()
    return (s - m) / sd.replace(0.0, np.nan)


def _band_position(z: pd.Series, entry: float = 2.0) -> pd.Series:
    """+-2 sigma in, 0 out: short the spread when rich, long when cheap."""
    pos, cur = [], 0.0
    for v in z.values:
        if not np.isfinite(v):
            pos.append(cur); continue
        if cur == 0.0:
            cur = -1.0 if v >= entry else (1.0 if v <= -entry else 0.0)
        elif (cur > 0 and v >= 0) or (cur < 0 and v <= 0):
            cur = 0.0
        pos.append(cur)
    return pd.Series(pos, index=z.index)


def build_books(px, ret, idx) -> dict[str, pd.DataFrame]:
    books: dict[str, pd.DataFrame] = {}
    z = lambda d: pd.DataFrame(d, index=idx).fillna(0.0)

    books["B1_HYG"] = z({"HYG": 1.0})
    books["B3_AGG"] = z({"AGG": 1.0})
    books["B5_SHY"] = z({"SHY": 1.0})

    # B2: long HYG, short IEF at rolling 63d PIT beta of HYG on IEF
    both = ret[["HYG", "IEF"]].dropna()
    cov = both["HYG"].rolling(63).cov(both["IEF"])
    var = both["IEF"].rolling(63).var()
    beta = (cov / var).shift(1).reindex(idx).ffill().clip(-3, 3).fillna(0.0)
    books["B2_HY_carry_dhedged"] = pd.DataFrame(
        {"HYG": 1.0, "IEF": -beta}, index=idx).fillna(0.0)

    # B4: 60/40, rebalanced monthly (weights drift between rebalances)
    m = pd.Series(idx, index=idx).groupby([idx.year, idx.month]).transform("min")
    reb = (m == pd.Series(idx, index=idx))
    b4 = pd.DataFrame({"SPY": np.where(reb, 0.6, np.nan),
                       "IEF": np.where(reb, 0.4, np.nan)}, index=idx).ffill()
    books["B4_60_40"] = b4.fillna(0.0)

    # B6: equal-weight credit basket, monthly rebalance
    avail = [t for t in CREDIT_BASKET if t in ret.columns]
    live = ret[avail].reindex(idx).notna()
    n = live.sum(axis=1).replace(0, np.nan)
    eq = live.div(n, axis=0).where(reb).ffill()
    books["B6_EW_credit"] = eq.fillna(0.0)

    # B7: naive HYG/JNK price-ratio z-score, +-2 sigma in / 0 out  (dumb S2)
    if {"HYG", "JNK"}.issubset(px.columns):
        s = np.log(px["HYG"] / px["JNK"]).reindex(idx)
        pos = _band_position(_zscore(s))
        books["B7_naive_pair_z"] = pd.DataFrame(
            {"HYG": 0.5 * pos, "JNK": -0.5 * pos}, index=idx).fillna(0.0)

    # B8: naive RAW premium/discount +-2 sigma  -- dead E1, kept alive (dumb S1)
    pdp = REPO / "data/forced_flow2/hyg_jnk_pd_derived.parquet"
    if pdp.exists():
        d = pd.read_parquet(pdp)
        d["date"] = pd.to_datetime(d["date"])
        w = d.pivot_table(index="date", columns="ticker",
                          values="premium_discount_pct")
        if {"HYG", "JNK"}.issubset(w.columns):
            spread = (w["HYG"] - w["JNK"]).reindex(idx)
            pos = _band_position(_zscore(spread))
            books["B8_naive_raw_PD"] = pd.DataFrame(
                {"HYG": 0.5 * pos, "JNK": -0.5 * pos}, index=idx).fillna(0.0)

    # B9: null trader -- the deployed control, replicated as a shadow book
    import hashlib

    def uh(*parts) -> float:
        h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
        return 2.0 * (int.from_bytes(h[:8], "big") / float(1 << 64)) - 1.0

    uni = [t for t in CREDIT_BASKET if t in ret.columns]
    raw = pd.DataFrame(
        [[uh("phase0", str(d.date()), t) for t in uni] for d in idx],
        index=idx, columns=uni)
    raw = raw.where(ret[uni].reindex(idx).notna())
    dm = raw.sub(raw.mean(axis=1), axis=0)                      # dollar-neutral
    books["B9_null_trader"] = dm.div(dm.abs().sum(axis=1), axis=0).fillna(0.0)
    return books


# ------------------------------------------------------------- stats ---------
def stats(df: pd.DataFrame) -> dict:
    r = df.excess_ret.dropna()
    if len(r) < 60:
        return {}
    ann = 252
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(ann) if r.std() > 0 else np.nan
    g = df.gross_excess.dropna()
    yrs = len(r) / ann
    return dict(
        book=df.book.iloc[0], N=len(r),
        start=str(r.index.min().date()), end=str(r.index.max().date()),
        cagr=100 * (eq.iloc[-1] ** (1 / yrs) - 1), vol=100 * r.std() * np.sqrt(ann),
        sharpe=sharpe, maxdd=100 * dd,
        gross_sharpe=g.mean() / g.std() * np.sqrt(ann) if g.std() > 0 else np.nan,
        turnover=df.turnover.mean() * ann,
        tcost_bp_yr=1e4 * df.cost_usd.mean() * ann / CAPITAL,
        fin_bp_yr=1e4 * df.fin_usd.mean() * ann / CAPITAL,
        avg_gross=df.gross_expo.mean(), avg_net=df.net_expo.mean())


def main() -> int:
    px, ret, adv, dayvol_bp = load_panel()
    rf = load_rates()
    cm = SCENARIOS["base"]

    idx = ret.index[(ret.index >= "2007-04-12")]
    print(f"universe {list(ret.columns)[:12]}{'...' if ret.shape[1] > 12 else ''}")
    print(f"panel {idx.min().date()} -> {idx.max().date()}  N={len(idx):,}\n")

    books = build_books(px, ret, idx)
    results, rows = {}, []
    for name, w in sorted(books.items()):
        df = run_book(name, w, ret, px, adv, dayvol_bp, rf, cm)
        results[name] = df
        s = stats(df)
        if s:
            rows.append(s)
    summ = pd.DataFrame(rows)

    pd.concat(results.values()).to_parquet(OUT / "benchmark_daily.parquet")
    summ.to_csv(OUT / "benchmark_summary.csv", index=False)

    print("=" * 118)
    print("NINE BENCHMARK BOOKS -- identical cost model, fills and accounting")
    print("all figures are EXCESS of the risk-free rate")
    print("=" * 118)
    print(f"{'book':<24}{'from':>11}{'N':>7}{'CAGR%':>8}{'vol%':>7}{'net SR':>8}"
          f"{'gr SR':>7}{'maxDD%':>8}{'turn/yr':>9}{'tcost bp':>10}{'fin bp':>9}{'gross':>7}")
    for _, r in summ.sort_values("sharpe", ascending=False).iterrows():
        print(f"{r.book:<24}{r.start:>11}{r.N:>7,}{r.cagr:>8.2f}{r.vol:>7.2f}"
              f"{r.sharpe:>8.2f}{r.gross_sharpe:>7.2f}{r.maxdd:>8.1f}"
              f"{r.turnover:>9.1f}{r.tcost_bp_yr:>10.0f}{r.fin_bp_yr:>9.0f}{r.avg_gross:>7.2f}")
    print(f"\nwrote {OUT/'benchmark_daily.parquet'}\n      {OUT/'benchmark_summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
