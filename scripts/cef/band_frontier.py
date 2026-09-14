"""Part 2 of PLAN.md (archived: _archive/docs/PLAN.md) — the trading policy frontier.

Asks one question: at a given amount of trading, which policy keeps more of the
gross edge, a fixed rebalance calendar or a no-trade band?

Both policies run on an IDENTICAL signal (the live sleeve's z-score, ADV filter
and vol scalar) and identical execution (decide at t, MOC fill at t+1, so the
weights set at t earn the t+2 return). The only difference is when they trade.

  calendar(k)  ignore the signal for k days, then implement all of it
  band(b)      hold a position until it is more than b from target, then trade
               back only to the band EDGE -- the optimal form under proportional
               costs (Constantinides 1986, Davis & Norman 1990)

Costs are charged as bp per unit of turnover, swept rather than assumed, because
the realised figure is not yet known. `net` columns are therefore a sensitivity
surface, not a forecast.

IMPORTANT: this table characterises the POLICY CLASS. Do not read the argmax of a
column as the band width to deploy -- deriving a parameter from the cube-root law
and checking it lands on the plateau is legitimate; picking the top of a swept
column is how z_window=63 was selected, and it failed out of sample.

Usage:  python scripts/cef/band_frontier.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]

# Parameters the LIVE BOOK owns come from the frozen spec, never from a literal
# here. Until 2026-09-10 these were module constants that happened to agree with
# the spec; "happened to agree" stops being true at the next spec bump, and a
# baseline measured against a policy nobody deployed is worse than no baseline.
# See scripts/cef/spec.py for the full argument.
import sys                                                          # noqa: E402
sys.path.insert(0, str(REPO))
from scripts.cef.spec import (  # noqa: E402
    BAND_WIDTH, LIVE_POLICY, MIN_ADV_USD, MIN_NAMES,
    REBALANCE_DAYS, UNIVERSE, VOL_TARGET, Z_WINDOW, summary,
)

MIN_ADV = MIN_ADV_USD
# Not spec-owned: estimation choices local to this harness.
MIN_PERIODS, VOL_LOOKBACK = 120, 63
SAMPLE_START = "2005-01-03"
COSTS_BP = [5, 10, 15, 20, 30]

# The width sweep is a DELIBERATE variation -- characterising the policy class is
# the entire point of this script, and H8 permits it explicitly. The live width
# is unioned in so the sweep always contains the deployed policy, whatever it is.
BAND_SWEEP = sorted({0.002, 0.004, 0.008, 0.016, 0.024, 0.032,
                     0.048, 0.064, 0.096, 0.128, BAND_WIDTH})


def build_panel(end=None):
    """The signal panel `build_targets` is built from: px, nav, ret, disc, z, adv.

    `end` truncates the RAW price and NAV history before anything is computed,
    so a caller can ask "what did this panel look like on date X" and get an
    answer that exercises the pivot, the return filter and the ADV window --
    not merely the rolling mean. `scripts/cef/tests/test_pnl_series.py` uses it
    to test no-lookahead end to end. `end=None` is the production path and is
    byte-identical to the version before this argument existed.

    WHY THIS IS SPLIT OUT (2026-09-11, W14 Part A)
    ----------------------------------------------
    `z` never left this function, so anything that needed the SIGNAL rather than
    the POSITIONS -- a conditional IC, a per-group split, a diagnostic on the
    clip -- had to re-derive the z-score from the panel. Two copies of a
    signal definition is the same class of defect as two copies of the
    execution convention: they agree until one of them is edited.

    `build_targets` now calls this and is otherwise UNCHANGED. The no-op was
    proved by hashing `pickle.dumps((T, R))` before and after the split:
    sha256 2ee89432...4ed5 both times (see
    scripts/cef/tests/test_pnl_series.py::test_build_panel_is_a_noop, which
    re-derives the targets from the panel and compares them element-wise).

    ALIGNMENT (H7): `mu`, `sd` and `adv` are all `.shift(1)` -- the z-score on
    date t is standardised against a window ending at t-1, and eligibility uses
    ADV through t-1. `disc` itself is date-t information (t's close against t's
    published NAV), which is why the execution convention is shift(2) and not
    shift(1): t's NAV is published AFTER t's close.
    """
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    P, N = P[P.ticker.isin(UNIVERSE)], N[N.ticker.isin(UNIVERSE)]
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    if end is not None:
        d = d[d["date"] <= pd.Timestamp(end)]
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    piv = lambda c: d.pivot_table(index="date", columns="ticker", values=c).sort_index()
    px, nav, vol = piv("close"), piv("nav"), piv("volume")

    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    return dict(px=px, nav=nav, vol=vol, ret=ret, disc=disc, mu=mu, sd=sd, z=z, adv=adv)


def build_targets():
    """Frictionless daily target weights, exactly as the sleeve would build them."""
    p = build_panel()
    ret, z, adv = p["ret"], p["z"], p["adv"]

    tgt = pd.DataFrame(0.0, index=z.index, columns=UNIVERSE)
    start = z.index.searchsorted(pd.Timestamp(SAMPLE_START))
    for i in range(start, len(z.index)):
        row = z.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV]]
        if len(row) < MIN_NAMES:
            tgt.iloc[i] = tgt.iloc[i - 1]          # hold; nothing eligible
            continue
        w = -(row - row.mean())
        w = w / w.abs().sum()
        hist = ret[list(row.index)].iloc[:i + 1].mul(w, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w * scal).reindex(UNIVERSE).fillna(0.0).values
    T = tgt.iloc[start:]
    return T, ret.reindex(T.index)[UNIVERSE].fillna(0.0)


def calendar(T, k):
    """Refresh every k days, hold in between."""
    H = T.copy()
    keep = np.zeros(len(T), bool)
    keep[::k] = True
    H[~keep] = np.nan
    return H.ffill().fillna(0.0)


def band(T, b):
    """Hold unless a name is more than b from target; then trade to the EDGE."""
    A, cur = T.values, np.zeros(T.shape[1])
    H = np.zeros_like(A)
    for i in range(len(A)):
        gap = A[i] - cur
        mv = np.abs(gap) > b
        cur = cur.copy()
        cur[mv] = A[i][mv] - np.sign(gap[mv]) * b
        H[i] = cur
    return pd.DataFrame(H, index=T.index, columns=T.columns)


def evaluate(H, R):
    """H.loc[t] = weights decided at t. MOC fills at t+1 -> earns the t+2 return.

    Returns the summary statistics AND the daily P&L series that produced them
    (`pnl`), added 2026-09-11 for W14 Part A.

    WHY `pnl` IS RETURNED
    ---------------------
    Every number this function reports is a moment of one series, and until now
    that series was discarded at the return statement. Anything that asks a
    question about the SHAPE of the P&L rather than its first two moments -- a
    factor regression, a drawdown census, a conditional-state split -- therefore
    had to rebuild `(H.shift(2) * R).sum(axis=1)` for itself, and a second copy
    of the execution convention is exactly the defect `EXEC_LAG = 2` exists to
    prevent (see scripts/cef/tests/test_execution_convention.py, and the
    shift(1) incident of 2026-09-10 that cost gross 1.27 -> 0.94).

    This is an ADDITIVE extension: the existing keys and their values are
    untouched, and `pnl` is the identical object the statistics are computed
    from, not a recomputation. scripts/cef/tests/test_pnl_series.py holds that
    shut.

    `R` is whatever return matrix the caller supplies. The default from
    `build_targets()` is PRICE returns; `total_returns()` in this module adds
    the distribution leg. The choice belongs to the caller and is stated in
    every table, because the two conventions differ by era (RESEARCH_STATE.md,
    2026-09-09: -0.01%/yr full sample but -0.77%/yr in 2010-14).
    """
    pnl = (H.shift(2).fillna(0.0) * R).sum(axis=1)
    turn = H.diff().abs().sum(axis=1).fillna(0.0)
    gross_v = H.abs().sum(axis=1).mean()
    return dict(
        gross_sr=pnl.mean() / pnl.std() * np.sqrt(252),
        ann_ret=pnl.mean() * 252,
        vol=pnl.std() * np.sqrt(252),
        turn=turn.sum() * 252 / len(pnl),
        hold=gross_v / turn.mean() if turn.mean() > 0 else np.inf,
        turn_series=turn,
        pnl=pnl,
    )


def distribution_yield(index, columns):
    """D_it / P_i,t-1 on each ex-date -- the cash leg the price panel omits.

    WHY THIS IS NOT OPTIONAL FOR A FACTOR REGRESSION
    ------------------------------------------------
    The price panel is RAW (unadjusted), which is CORRECT for the discount --
    NAV is unadjusted too and the two must share a convention -- but it is
    wrong for the RETURN: `px.pct_change()` books the ex-date price drop and
    never books the cash, so the long is never credited its distribution and
    the short is never debited its payment in lieu.

    On the band's holdings path the mean bias nets to -0.01%/yr over 2005-2026
    (RESEARCH_STATE.md, measured 2026-09-09 over 3,962 ex-dates) because the
    book is not systematically long or short yield. Its standard deviation is
    1.23%/yr and it swings by era. For a Sharpe that hardly matters; for a
    LOADING on any factor correlated with the distribution calendar it matters
    a great deal, which is why W14 Part A insists on the total-return series.

    ALIGNMENT (H7): the yield is booked on the ex-date `t` itself, divided by
    the close of `t-1`, which is the last price that contains the distribution.
    Nothing here reads a date later than `t`.

    NO SILENT FALLBACK: raises if the distribution panel cannot cover a name
    that the caller asked for, rather than returning zeros -- a zero here is
    indistinguishable from "this fund paid nothing", and the two have opposite
    meanings for the bias above.
    """
    dist = pd.read_parquet(REPO / "data/cef/cef_distributions.parquet")
    dist["ex_date"] = pd.to_datetime(dist["ex_date"])
    missing = sorted(set(columns) - set(dist["ticker"].unique()))
    if missing:
        raise ValueError(
            "cef_distributions.parquet has no rows for "
            f"{missing} -- cannot build a total-return series for the "
            "universe requested. Fix the panel; do not fall back to price "
            "returns silently (house rule: no silent fallbacks).")
    dist = dist[dist.ticker.isin(columns)]

    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    P = P[P.ticker.isin(columns)]
    P["date"] = pd.to_datetime(P["date"])
    px = P.pivot_table(index="date", columns="ticker", values="close").sort_index()
    prev = px.shift(1)                       # close of t-1, cum-distribution

    amt = (dist.groupby(["ex_date", "ticker"])["amount"].sum()
               .unstack().reindex(index=index, columns=list(columns)))
    y = amt / prev.reindex(index=index, columns=list(columns))

    # THE TWO SILENT PATHS, MADE LOUD. `.fillna(0.0)` below is correct for the
    # common case -- a date with no ex-date for a name IS a genuine zero cash
    # flow -- but it is indistinguishable from two real failures:
    #   (a) an ex-date that falls on a date absent from `index`, which
    #       `.reindex` drops with no trace;
    #   (b) an ex-date with no prior close, which divides to NaN and becomes a
    #       zero yield.
    # Landmine 4 (HYT lags the price panel by a day) is exactly shape (b). So
    # count what went in against what came out and raise on any gap, rather
    # than asserting the paths are unreachable.
    window = dist[(dist.ex_date >= index[0]) & (dist.ex_date <= index[-1])]
    expected = int(window.groupby(["ex_date", "ticker"]).ngroups)
    booked = int((y.notna() & (y != 0)).sum().sum())
    if booked != expected:
        raise ValueError(
            f"{expected - booked} of {expected} ex-dates in "
            f"{index[0].date()}..{index[-1].date()} did not reach the yield "
            "matrix — either the ex-date is not a session in this index, or "
            "the prior close is missing (landmine 4: HYT lags the price panel "
            "by a day). A zero here is indistinguishable from 'this fund paid "
            "nothing' and means the opposite, so this raises rather than "
            "filling.")
    return y.fillna(0.0)


def split_factor(index, columns):
    """Share-count multiplier on each ex-split date; 1.0 everywhere else.

    WHY THIS SITS BESIDE THE DISTRIBUTION LEG AND NOT SOMEWHERE ELSE
    ---------------------------------------------------------------
    `RESEARCH_STATE.md`'s 2026-09-09 amendment on the raw price panel makes TWO
    points, and only the first was ever acted on. The second: "the +-50% single
    day return filter in `build_targets` silently drops any day where an
    unadjusted split would appear as a jump, and `data/cef/cef_splits.parquet`
    (one row: BIT 2025-08-19) is not applied in the harness at all."

    A 2.9% split is nowhere near the +-50% filter, so nothing is dropped and
    nothing looks wrong -- the harness simply books the split as a loss. On
    2025-08-19 BIT's raw close went 14.47 -> 13.84, a -4.354% "return", of
    which -2.818% (= 1/1.029 - 1) is the split and only -1.578% is price. The
    band held w_BIT = +0.0335 that day, so the phantom half is about -9.4bp of
    a -18.0bp session -- inside the 2023-26 holdout.

    RAW PRICES STAY RAW FOR THE DISCOUNT. NAV is unadjusted too and drops by
    the same factor, so price/NAV is unaffected and `build_panel` is untouched.
    It is only the RETURN that needs this, which is why it lives here with the
    other return-convention correction rather than in the panel.

    NO SILENT FALLBACK: raises if a split and a distribution ever land on the
    same name-date, because the per-share amount is then ambiguous (pre- or
    post-split) and this function cannot tell which. That has never happened in
    this panel; if it does, someone must decide rather than inherit a guess.
    """
    path = REPO / "data/cef/cef_splits.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. The harness cannot build a split-correct "
            "return series without it, and booking a split as a return is a "
            "silent loss -- see this function's docstring.")
    sp = pd.read_parquet(path)
    sp["ex_date"] = pd.to_datetime(sp["ex_date"])
    sp = sp[sp.ticker.isin(columns)]
    k = (sp.groupby(["ex_date", "ticker"])["stock_split"].prod()
           .unstack().reindex(index=index, columns=list(columns)))
    return k.fillna(1.0)


def total_returns(R):
    """Price returns corrected for splits, plus the distribution leg.

    Kept separate from `build_targets()` on purpose. Every baseline in this
    repo was measured on the raw price-return convention; silently switching
    what `build_targets` hands back would move nine scripts' numbers at once
    with nothing erroring. The caller opts in, and says which convention it
    used.

    r_total = (1 + r_px) * k - 1 + D/P_{t-1}, where k is the share-count
    multiplier. The two corrections never coincide on a name-date in this
    panel, and `split_factor` raises if they ever do.
    """
    y = distribution_yield(R.index, R.columns).reindex_like(R)
    k = split_factor(R.index, R.columns).reindex_like(R)
    clash = ((k != 1.0) & (y != 0.0))
    if clash.any().any():
        where = [(str(d.date()), c) for d, c in zip(*np.where(clash.values))]
        raise ValueError(
            f"a split and a distribution fall on the same name-date ({where}). "
            "The per-share distribution amount is then ambiguous -- pre- or "
            "post-split -- and this function will not guess.")
    return (1.0 + R) * k - 1.0 + y


def row(label, H, R):
    r = evaluate(H, R)
    nets = [(r["ann_ret"] - r["turn"] * c / 1e4) / r["vol"] for c in COSTS_BP]
    print(f"{label:<22}{r['gross_sr']:8.2f}{r['ann_ret'] * 100:7.2f}"
          f"{r['vol'] * 100:7.2f}{r['turn']:9.1f}{r['hold']:9.1f}"
          + "".join(f"{n:11.2f}" for n in nets))
    return r, nets


# --- labels -----------------------------------------------------------------
# Which row is LIVE is read from the frozen spec, never asserted here. Three
# scripts in this directory labelled "calendar 2d (LIVE)" for four days after
# the band replaced it on 2026-09-06, and PLAN.md carried the same claim in five
# tables. A label that can go stale silently is the same bug as a hardcoded
# baseline, one layer up.
LIVE_TAG = "  <-- LIVE"


def _cal_is_live(k: int) -> bool:
    from scripts.cef.spec import BAND_IS_LIVE
    return (not BAND_IS_LIVE) and k == REBALANCE_DAYS


def _band_is_live(b: float) -> bool:
    from scripts.cef.spec import BAND_IS_LIVE
    return BAND_IS_LIVE and abs(b - BAND_WIDTH) < 1e-12


def _lab_cal(k: int) -> str:
    return f"calendar {k}d" + (LIVE_TAG if _cal_is_live(k) else "")


def _lab_band(b: float) -> str:
    return f"band {b * 100:.1f}%" + (LIVE_TAG if _band_is_live(b) else "")


def main():
    T, R = build_targets()
    print(summary())
    print(f"sample {T.index[0].date()} .. {T.index[-1].date()}  ({len(T)} days)\n")

    hdr = (f"{'policy':<22}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'turn/yr':>9}{'hold(d)':>9}"
           + "".join(f"{'net@' + str(c) + 'bp':>11}" for c in COSTS_BP))
    print(hdr, "-" * len(hdr), sep="\n")
    for k in (1, 2, 5, 10):
        row(f"calendar {k}d" + (LIVE_TAG if _cal_is_live(k) else ""), calendar(T, k), R)
    for b in BAND_SWEEP:
        row(f"band {b * 100:.1f}% of gross" + (LIVE_TAG if _band_is_live(b) else ""),
            band(T, b), R)

    print("\n\n=== matched on turnover: the only honest comparison ===")
    print("H2: pairs must match turn/yr within 5%. Note that pairing calendar 5d")
    print("with the LIVE band is a near-exact match, where the retired 6.4%")
    print("baseline this block used until 2026-09-10 was ~19% adrift -- i.e. that")
    print("row was violating the rule it exists to demonstrate.\n")
    print(f"{'policy':<22}{'turn/yr':>9}{'grossSR':>9}{'net@15bp':>10}")
    for lab, H in [("calendar 1d", calendar(T, 1)), ("band 0.2%", band(T, 0.002)),
                   (_lab_cal(2), calendar(T, 2)), (_lab_band(0.016), band(T, 0.016)),
                   ("calendar 5d", calendar(T, 5)), (_lab_band(BAND_WIDTH), band(T, BAND_WIDTH))]:
        r = evaluate(H, R)
        net = (r["ann_ret"] - r["turn"] * 15 / 1e4) / r["vol"]
        print(f"{lab:<22}{r['turn']:9.1f}{r['gross_sr']:9.2f}{net:10.2f}")

    print("\n\n=== turnover stability, 2015+ (universe stable; pre-2010 is degenerate) ===")
    print("Recorded against an earlier draft of PLAN.md, which claimed the band")
    print("would be MORE turnover-stable. It is not. See PLAN.md 0.3 and 2.3.\n")
    eras = [("2015-2019", "2015", "2019"), ("2020-2022", "2020", "2022"),
            ("2023-2026", "2023", "2026")]
    print(f"{'policy':<22}" + "".join(f"{e[0]:>11}" for e in eras) + f"{'mean':>8}{'sd/mean':>9}")
    era_widths = sorted({0.016, 0.024, BAND_WIDTH})
    for lab, H in ([("calendar 1d", calendar(T, 1)), (_lab_cal(2), calendar(T, 2)),
                    ("calendar 5d", calendar(T, 5))]
                   + [(_lab_band(b), band(T, b)) for b in era_widths]):
        t = evaluate(H, R)["turn_series"]
        v = np.array([t.loc[a:b].mean() * 252 for _, a, b in eras])
        print(f"{lab:<22}" + "".join(f"{x:11.1f}" for x in v)
              + f"{v.mean():8.1f}{v.std() / v.mean():9.1%}")

    print("\n\n=== sensitivity to being wrong about cost — the robustness that matters ===")
    print(f"{'policy':<22}{'turn/yr':>9}{'net@5bp':>10}{'net@30bp':>10}{'span':>8}{'flips?':>9}")
    widths = sorted({0.024, 0.064, BAND_WIDTH})
    for lab, H in ([("calendar 1d", calendar(T, 1)), (_lab_cal(2), calendar(T, 2)),
                    ("calendar 5d", calendar(T, 5))]
                   + [(_lab_band(b), band(T, b)) for b in widths]):
        r = evaluate(H, R)
        lo = (r["ann_ret"] - r["turn"] * 5 / 1e4) / r["vol"]
        hi = (r["ann_ret"] - r["turn"] * 30 / 1e4) / r["vol"]
        print(f"{lab:<22}{r['turn']:9.1f}{lo:10.2f}{hi:10.2f}{lo - hi:8.2f}"
              f"{('YES' if hi < 0 else 'no'):>9}")


if __name__ == "__main__":
    main()
