"""Zero-trial feasibility for trial C5 (fill the live CEF book at the t+1
OPENING auction instead of the t+1 closing auction).

    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open
    python3 scripts/data/stage_crsp_w4.py                        # CRSP openprc, the pre-2016 second source
    python3 scripts/cef/c5_feasibility.py                        # ~1 min; read-only on data/

Writes `results/cef/c5/c5_feasibility_output_2026-10-13.txt` (the printed
report) and `results/cef/c5/c5_{coverage,trades,power}_2026-10-13.csv`. Every
file holds counts, shares and arithmetic only: no price, no return.

WHAT THIS IS FOR
----------------
`results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md` (a DRAFT awaiting the team
lead) declares C5's price source, its no-cross rule, its evaluation-set
options and its pass bar before any of its returns exist. This script measures
the inputs that declaration needs and nothing else:

* opening-print coverage: for every panel name-day 2016-22 (a close in
  `data/cef/cef_prices.parquet`), whether the primary listing (SIP exchange N)
  printed an opening-auction trade (condition `O`), only an official-open
  message (`Q`), or nothing; by name and by year;
* the declared defect classes of the price rule (O against Q, O outside the
  consolidated day's range, O against CRSP `openprc` and the yfinance open),
  as counts, so the halt thresholds are set before any return is seen;
* the share of name-days whose opening print sits at the previous close (the
  stale-open stratum the trial must report);
* the pre-2016 second source (CRSP `openprc`) coverage, by year;
* the two candidate evaluation sets' holdings paths (the deployed fit sample,
  with the spec's ADV floor; and WIDE, the same rule with the floor at zero):
  first position, active sessions, trade sessions and trade name-days, and
  turnover per year, in the decision window and before it -- and coverage of
  the opening print on the name-days where a trade would go to the open;
* arithmetic on the pass bar: the Sharpe at which `validate._dsr` reaches
  0.95 at the CEF counter's N for each window, the power at a grid of true
  Sharpes, the mapping from the candidates note's prior to the gain series,
  and the false-kill rate of the holdout sign rule.

WHAT IT DOES NOT DO (zero trials)
---------------------------------
No return of any kind is computed: not the book's P&L, not a session or
overnight return, not an IC, not the gain the open would capture, and not the
volatility of any of them. Turnover is computed from the holdings path H alone
with the formula `evaluate()` uses (`H.diff().abs().sum(axis=1)`), and
`evaluate()` itself is never called, because it computes a P&L. The holdings
path needs the sleeve's vol scalar, which reads trailing returns; that is how
every W4-era script obtains H and it is not a statistic of C5.

THE HOLDOUTS: every frame that reaches a statistic stops at 2022-12-30
(`_assert_fit`). The 2023+ opening prints are not fetched (the fetcher never
requests them). Only the 13 spec names are read; the 27-name set is untouched.

THE WIDE SET is built by calling the canonical `build_targets()` with
`band_frontier.MIN_ADV` set to 0 inside a context manager that restores it.
That is a zero-trial count only. The trial itself needs a default-off
`min_adv` argument on `build_targets` with a byte-for-byte no-op proof (the
pre-registration's DG-C5-4, the same flag as C4's DG-C4-5).

NO SILENT FALLBACK: a missing cache raises naming the script that builds it;
two `O` prints for one name-day raise; a name-day without an `O` print is
counted in its own column and never filled.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
OPEN_PRINTS = CACHE / "alpaca_opening_prints_2016_2022.parquet"
CRSP = CACHE / "crsp_dsf_w4.parquet"
OUT_DIR = REPO / "results" / "cef" / "c5"
STAMP = "2026-10-13"

HOLDOUT_START = pd.Timestamp("2023-01-01")
FIT_END = pd.Timestamp("2022-12-30")
PRINT_START = pd.Timestamp("2016-01-04")        # first session of the Alpaca SIP auction history
HOLDOUT_END = pd.Timestamp("2026-09-30")        # proposed fixed end (PREREG_C5 §7)
TICK = 0.005                                     # half a cent: the price-agreement tolerance used by W4 and the candidates note
MATERIAL = 0.005                                 # a trade of at least 0.5% of capital ($500 at $100k): the candidates note's "trade"
N_GRID = (51, 52, 58)                            # CEF counter if C5 is the next trial / after C4 / the plan's upper end
SR_GRID = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00)
PRIOR_DELTA = (0.1, 0.2, 0.3)                    # candidates note §1, "roughly +0.1 to +0.3 gross SR" [U]
VOL_RATIO = (0.10, 0.20, 0.30, 0.50)             # f = sd(gain) / sd(book): unknown, a grid, never measured here
DEPLOYED_REF_SR = 0.96                           # [S] W4: the deployed book's live gross SR 2013-06 -> 2022, total returns; a reference, never a decision input


def _need(path: Path, builder: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; build it with: {builder}")
    return path


def _assert_fit(*frames) -> None:
    """H13: nothing that reaches a statistic may carry a 2023+ date."""
    for f in frames:
        idx = f.index if hasattr(f, "index") else f
        if len(idx) and pd.Timestamp(idx.max()) >= HOLDOUT_START:
            raise AssertionError(f"holdout leak: a frame reaches {pd.Timestamp(idx.max()).date()}")


# --------------------------------------------------------------------------- the declared price rule

def nyse_open_prints(a: pd.DataFrame, index, columns) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(O, Q): the primary listing's opening-auction trade print (condition
    `O`, the print that updates volume, REFERENCES §12o) and its official-open
    message (`Q`), each a date x ticker frame of prices, NaN where absent.

    Raises if any name-day carries two `O` (or two `Q`) prints: the price rule
    would then be ambiguous, and choosing one silently is the defect this desk
    keeps paying for."""
    n = a[a["exchange"] == "N"].copy()
    n["date"] = pd.to_datetime(n["date"])
    out = []
    for cond in ("O", "Q"):
        s = n[n["condition"] == cond]
        dup = s.duplicated(["date", "ticker"], keep=False)
        if dup.any():
            raise ValueError(f"{int(dup.sum())} NYSE condition-{cond} rows share a name-day; "
                             "the opening price is ambiguous there")
        out.append(s.pivot(index="date", columns="ticker", values="price")
                     .reindex(index=index, columns=columns))
    return out[0], out[1]


def classify_open(O: pd.DataFrame, Q: pd.DataFrame, priced: pd.DataFrame) -> pd.DataFrame:
    """Per priced name-day: 'O' (an opening-auction trade print), 'Q_only' (an
    official open but no auction trade: no round-lot cross), or 'none'.
    Unpriced name-days are NaN and are never counted."""
    c = pd.DataFrame(np.where(O.notna(), "O", np.where(Q.notna(), "Q_only", "none")),
                     index=O.index, columns=O.columns)
    return c.where(priced)


def coverage_table(cls: pd.DataFrame, by: str) -> pd.DataFrame:
    """Counts of each class by name ('name') or by year ('year')."""
    s = cls.stack()
    s.index = s.index.set_names(["date", "ticker"])
    df = s.rename("cls").reset_index()
    key = df["ticker"] if by == "name" else df["date"].dt.year.rename("year")
    t = pd.crosstab(key, df["cls"]).reindex(columns=["O", "Q_only", "none"], fill_value=0)
    t["name_days"] = t.sum(axis=1)
    t["O_share"] = t["O"] / t["name_days"]
    return t


# --------------------------------------------------------------------------- holdings paths (no returns)

@contextlib.contextmanager
def adv_floor(value: float):
    """Temporarily set the harness's ADV floor (zero-trial counts only)."""
    from scripts.cef import band_frontier as bf
    old = bf.MIN_ADV
    bf.MIN_ADV = value
    try:
        yield
    finally:
        bf.MIN_ADV = old


def holdings(min_adv: float | None) -> pd.DataFrame:
    """The deployed policy's holdings path H (band_gross_capped on the spec),
    on the spec's ADV floor (None) or another floor; truncated to the fit."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS
    cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
    ctx = contextlib.nullcontext() if min_adv is None else adv_floor(min_adv)
    with ctx:
        T, R = bf.build_targets()
    T, _ = bf.fit_only(T, R)
    H = bf.band_gross_capped(T, BAND_WIDTH, cap)
    _assert_fit(H)
    return H


def turnover(H: pd.DataFrame) -> pd.Series:
    """Daily one-way turnover, exactly `evaluate()`'s `turn` line (without its P&L)."""
    return H.diff().abs().sum(axis=1).fillna(0.0)


def trade_summary(H: pd.DataFrame, cls: pd.DataFrame, lo, hi) -> dict:
    """Trades decided on session s-1 go to the open of session s. Counts, over
    sessions s in [lo, hi]: trade sessions, material trade name-days, the
    opening-print class of each, and the share of traded notional covered."""
    dH = H.diff().abs().shift(1)                     # row s: |trade decided at s-1|, filled at the open of s
    w = (dH.index >= pd.Timestamp(lo)) & (dH.index <= pd.Timestamp(hi))
    dH = dH.loc[w]
    mat = dH >= MATERIAL
    anyt = dH > 1e-12
    first = H.index[(H.abs().sum(axis=1) > 0).to_numpy()]
    out = dict(sessions=int(w.sum()),
               first_position=str(first.min().date()) if len(first) else "none",
               trade_sessions_any=int(anyt.any(axis=1).sum()),
               trade_sessions_material=int(mat.any(axis=1).sum()),
               trade_name_days_material=int(mat.sum().sum()),
               turnover_per_year=float(turnover(H).loc[w].mean() * 252),
               held_gross_mean=float(H.abs().sum(axis=1).loc[w].mean()),
               trade_gross_per_material_session=float(dH.where(mat, 0.0).sum(axis=1)[mat.any(axis=1)].mean())
               if mat.any(axis=1).any() else float("nan"))
    if cls is not None:
        c = cls.reindex(index=dH.index, columns=dH.columns)
        for k in ("O", "Q_only", "none"):
            out[f"material_{k}"] = int((mat & (c == k)).sum().sum())
        out["material_unpriced"] = int((mat & c.isna()).sum().sum())
        notional = dH.where(mat, 0.0)
        out["notional_share_with_O"] = float(notional.where(c == "O", 0.0).sum().sum()
                                             / notional.sum().sum()) if notional.sum().sum() > 0 else float("nan")
    return out


def active_share(min_adv: float | None, lo, hi) -> float:
    """Share of sessions in [lo, hi] on which >= min_names names are eligible."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES
    p = bf.build_panel(end=FIT_END)
    floor = MIN_ADV_USD if min_adv is None else min_adv
    elig = p["z"].notna() & (p["adv"] >= floor)
    s = elig.sum(axis=1) >= MIN_NAMES
    s = s.loc[pd.Timestamp(lo):pd.Timestamp(hi)]
    _assert_fit(s)
    return float(s.mean())


# --------------------------------------------------------------------------- the bar

def required_sharpe(n_trials: int, n_days: int) -> float:
    from scripts.xasset.slate_feasibility import required_sharpe as rs
    return rs(n_trials, n_days)


def p_pass(sr_true: float, n_trials: int, n_days: int) -> float:
    from scripts.xasset.slate_feasibility import power
    return power(sr_true, n_trials, n_days)


def holdout_false_kill(sr_true: float, n_days: int) -> float:
    """P(the holdout mean has the wrong sign | true Sharpe), normal approximation."""
    return NormalDist().cdf(-sr_true * math.sqrt(n_days / 252))


# --------------------------------------------------------------------------- main

def run() -> str:
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import (BAND_WIDTH, MAX_GROSS_STRESS, MIN_ADV_USD, MIN_NAMES,
                                  UNIVERSE, Z_WINDOW, summary)
    assert bf.HOLDOUT_START == HOLDOUT_START
    U = list(UNIVERSE)
    print(summary())
    print(f"spec read through scripts/cef/spec.py: band_width {BAND_WIDTH}, max_gross_stress {MAX_GROSS_STRESS}, "
          f"min_adv_usd {MIN_ADV_USD:,.0f}, min_names {MIN_NAMES}, z_window {Z_WINDOW}")

    # ---- panels
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    P = P[P.ticker.isin(U)].copy()
    P["date"] = pd.to_datetime(P["date"])
    print(f"cef_prices last date {P['date'].max().date()}; only rows to {FIT_END.date()} are used below")
    P = P[P["date"] <= FIT_END]
    pv = lambda c: P.pivot_table(index="date", columns="ticker", values=c).sort_index().reindex(columns=U)
    close, op_y, hi, lo = pv("close"), pv("open"), pv("high"), pv("low")
    _assert_fit(close)
    idx = close.index

    # ---- [1] the opening prints and the declared price rule
    a = pd.read_parquet(_need(OPEN_PRINTS, "QUANTT_ENV_FILE=... python3 scripts/data/fetch_alpaca_auction_history.py --side open"))
    a["date"] = pd.to_datetime(a["date"])
    _assert_fit(a.set_index("date"))
    print(f"\n[1] ALPACA SIP OPENING PRINTS {a['date'].min().date()} -> {a['date'].max().date()}: {len(a):,} rows")
    print("    rows by exchange/condition:", a.groupby(["exchange", "condition"]).size().to_dict())
    w16 = idx >= PRINT_START
    O, Q = nyse_open_prints(a, idx[w16], U)
    priced = close.loc[w16].notna()
    cls = classify_open(O, Q, priced)
    tot = int(priced.sum().sum())
    nO, nQ, nN = (int((cls == k).sum().sum()) for k in ("O", "Q_only", "none"))
    print(f"    panel name-days 2016-22 with a close: {tot:,}; NYSE 'O' print {nO:,} ({nO / tot:.2%}); "
          f"'Q' only {nQ:,}; neither {nN:,}")
    both = O.notna() & Q.notna()
    dis = ((O - Q).abs() > TICK) & both
    print(f"    O and Q both present on {int(both.sum().sum()):,} name-days; differ by > $0.005 on {int(dis.sum().sum())}")
    hasO = (cls == "O")
    out_rng = ((O < lo.loc[w16] - TICK) | (O > hi.loc[w16] + TICK)) & hasO & lo.loc[w16].notna()
    print(f"    O outside the yfinance day's [low, high] by > $0.005: {int(out_rng.sum().sum())} name-days")
    eq_y = ((O - op_y.loc[w16]).abs() <= TICK) & hasO & op_y.loc[w16].notna()
    c = pd.read_parquet(_need(CRSP, "python3 scripts/data/stage_crsp_w4.py"))
    c["date"] = pd.to_datetime(c["date"])
    c = c[c.ticker.isin(U) & (c["date"] <= FIT_END)]
    _assert_fit(c.set_index("date"))
    op_c = c.pivot_table(index="date", columns="ticker", values="openprc").reindex(index=idx, columns=U)
    op_c = op_c.where(op_c > 0)
    eq_c = ((O - op_c.loc[w16]).abs() <= TICK) & hasO & op_c.loc[w16].notna()
    both_bad = hasO & op_y.loc[w16].notna() & op_c.loc[w16].notna() & ~eq_y & ~eq_c & out_rng
    print(f"    O = yfinance open within $0.005: {int(eq_y.sum().sum()):,} of {int((hasO & op_y.loc[w16].notna()).sum().sum()):,}; "
          f"O = CRSP openprc within $0.005: {int(eq_c.sum().sum()):,} of {int((hasO & op_c.loc[w16].notna()).sum().sum()):,}")
    print(f"    declared defect class D-3 (O disagrees with BOTH consolidated opens AND lies outside the day's range): "
          f"{int(both_bad.sum().sum())} name-days")
    stale = ((O - close.shift(1).loc[w16]).abs() <= TICK) & hasO & close.shift(1).loc[w16].notna()
    print(f"    stale-open stratum: O within $0.005 of the previous close on {int(stale.sum().sum()):,} of "
          f"{int(hasO.sum().sum()):,} ({stale.sum().sum() / hasO.sum().sum():.1%})")

    # when the cross printed: an MOO order waits for the DMM to open the name, so a late open is still the
    # opening auction (REFERENCES §12o); counted so the divergence is sized, never filtered
    tO = a[(a["exchange"] == "N") & (a["condition"] == "O")]["t"]
    tod = pd.to_datetime(tO, utc=True, format="ISO8601").dt.tz_convert("America/New_York")
    mins = tod.dt.hour * 60 + tod.dt.minute + tod.dt.second / 60
    med_s = int(round(mins.median() * 60))
    print(f"    NYSE 'O' print time (ET): median {med_s // 3600:02d}:{med_s % 3600 // 60:02d}:{med_s % 60:02d}; "
          f"after 09:31 {int((mins > 571).sum())}, after 09:35 {int((mins > 575).sum())}, "
          f"after 10:00 {int((mins > 600).sum())}, before 09:30 {int((mins < 570).sum())} of {len(mins):,}")

    cov_name = coverage_table(cls, "name")
    cov_year = coverage_table(cls, "year")
    st_y = pd.Series({y: stale.loc[str(y)].sum().sum() / hasO.loc[str(y)].sum().sum() for y in range(2016, 2023)})
    eqy_y = pd.Series({y: eq_y.loc[str(y)].sum().sum() / (hasO & op_y.loc[w16].notna()).loc[str(y)].sum().sum()
                       for y in range(2016, 2023)})
    eqc_y = pd.Series({y: eq_c.loc[str(y)].sum().sum() / (hasO & op_c.loc[w16].notna()).loc[str(y)].sum().sum()
                       for y in range(2016, 2023)})
    cov_year["stale_open_share"] = st_y
    cov_year["O_eq_yf_open"] = eqy_y
    cov_year["O_eq_crsp_open"] = eqc_y
    print("\n    coverage by name, 2016-22 (panel name-days with a close):")
    print(cov_name.to_string(float_format=lambda x: f"{x:.4f}"))
    print("\n    coverage by year, with the stale-open share and agreement with the two consolidated opens:")
    print(cov_year.to_string(float_format=lambda x: f"{x:.4f}"))

    # ---- [2] the pre-2016 second source
    print("\n[2] PRE-2016 SECOND SOURCE (CRSP openprc > 0) on panel name-days with a close, by year:")
    pre = (idx < PRINT_START) & (idx >= pd.Timestamp(bf.SAMPLE_START))
    pr = close.loc[pre].notna()
    rows = {}
    for y in sorted(set(idx[pre].year)):
        m = pr.loc[str(y)]
        rows[y] = dict(name_days=int(m.sum().sum()),
                       crsp_open_share=float((m & op_c.loc[str(y)].notna()).sum().sum() / m.sum().sum()),
                       yf_open_share=float((m & op_y.loc[str(y)].notna() & (op_y.loc[str(y)] > 0)).sum().sum() / m.sum().sum()),
                       crsp_eq_yf=float((((op_c - op_y).abs() <= TICK) & m.reindex(op_c.index, fill_value=False)).loc[str(y)].sum().sum()
                                        / (m & op_c.loc[str(y)].notna() & op_y.loc[str(y)].notna()).sum().sum()))
    pre_t = pd.DataFrame(rows).T
    print(pre_t.to_string(float_format=lambda x: f"{x:.4f}"))

    # ---- [3] the two evaluation sets' holdings paths (no returns)
    print("\n[3] HOLDINGS PATHS (band_gross_capped on the spec; H only, no P&L). A trade decided at s-1 goes to the open of s.")
    H_dep = holdings(None)
    H_wide = holdings(0.0)
    trows = []
    for lab, H, mn in (("deployed (ADV floor on)", H_dep, None), ("WIDE (ADV floor 0)", H_wide, 0.0)):
        first = H.index[(H.abs().sum(axis=1) > 0).to_numpy()].min()
        lo_pre = H.index[H.index.get_loc(first) + 2]
        for win, a_, b_, cl in (("decision 2016-01-04..2022-12-30", PRINT_START, FIT_END, cls),
                                ("pre-2016 (CRSP openprc)", lo_pre, PRINT_START - pd.Timedelta(days=1), None)):
            if a_ > b_:
                continue
            r = trade_summary(H, cl, a_, b_)
            r.update(set=lab, window=win, active_share=active_share(mn, a_, b_), window_start=str(pd.Timestamp(a_).date()))
            trows.append(r)
    tdf = pd.DataFrame(trows).set_index(["set", "window"])
    print(tdf.T.to_string())
    # by year, material trade name-days, decision window
    by = {}
    for lab, H in (("deployed", H_dep), ("WIDE", H_wide)):
        for y in range(2016, 2023):
            r = trade_summary(H, cls, f"{y}-01-01", f"{y}-12-31")
            by[(lab, y)] = dict(trade_sessions=r["trade_sessions_material"], trade_name_days=r["trade_name_days_material"],
                                with_O=r["material_O"], turnover=r["turnover_per_year"])
    byt = pd.DataFrame(by).T
    print("\n    material trades by year (decision window):")
    print(byt.to_string(float_format=lambda x: f"{x:.2f}"))
    wide_extra = int(((H_wide.abs().sum(axis=1) > 0) & ~(H_dep.abs().sum(axis=1) > 0)).sum())
    # where each set's material trades fall, by the universe file's group, and how many of WIDE's
    # fall on name-days below the spec's ADV floor (the name-days the deployed rule cannot trade)
    from scripts.cef.w4_artifacts import groups
    grp = pd.Series(groups())                     # ticker -> group (cef_universe.csv)
    adv = bf.build_panel(end=FIT_END)["adv"].reindex(columns=U)
    gt, n_below = {}, {}
    for lab, H in (("deployed", H_dep), ("WIDE", H_wide)):
        dH = H.diff().abs().shift(1).loc[PRINT_START:FIT_END]
        mat = dH >= MATERIAL
        gt[lab] = mat.sum().groupby(grp.reindex(mat.columns).values).sum()
        # a deployed trade can fall on a below-floor name too: a name leaving eligibility gets target 0
        below = mat & (adv.shift(1).reindex(index=mat.index, columns=mat.columns) < MIN_ADV_USD)
        n_below[lab] = (int(below.sum().sum()), int(mat.sum().sum()))
    print("    material trade name-days by group, decision window:", {k: v.to_dict() for k, v in gt.items()})
    print("    material trade name-days on which the name's ADV (through the decision date) was below the "
          "spec's floor (below, all):", n_below)
    print(f"    sessions on which WIDE holds a position and the deployed set holds none (to {FIT_END.date()}): {wide_extra}")

    # ---- [4] the bar and its power
    print("\n[4] THE BAR: validate._dsr > 0.95 (skew 0, kurtosis 3; SE = 1/sqrt(years)). Arithmetic, no data.")
    n_dec = int(((idx >= PRINT_START) & (idx <= FIT_END)).sum())
    first_dep = H_dep.index[(H_dep.abs().sum(axis=1) > 0).to_numpy()].min()
    first_wide = H_wide.index[(H_wide.abs().sum(axis=1) > 0).to_numpy()].min()
    n_dep_long = int(((idx > first_dep) & (idx <= FIT_END)).sum()) - 1
    n_wide_long = int(((idx > first_wide) & (idx <= FIT_END)).sum()) - 1
    wins = {"decision 2016-22": n_dec, "deployed, first position+2 -> 2022": n_dep_long,
            "WIDE, first position+2 -> 2022": n_wide_long}
    prow = []
    for wl, nd in wins.items():
        for N in N_GRID:
            rq = required_sharpe(N, nd)
            row = dict(window=wl, sessions=nd, years=nd / 252, N=N, bar=math.sqrt(2 * math.log(N)), sr_required=rq,
                       sr_80pct=rq + NormalDist().inv_cdf(0.80) / math.sqrt(nd / 252))
            for s in SR_GRID:
                row[f"p_pass@{s:.2f}"] = p_pass(s, N, nd)
            prow.append(row)
    pdf = pd.DataFrame(prow)
    print(pdf.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    print(f"\n    the LEVEL option (decision 2): the C5 book's own Sharpe at the bar, decision window, N = 51. "
          f"Reference [S]: the deployed book's gross SR {DEPLOYED_REF_SR} (W4, 2013-06 -> 2022), never a decision input")
    for d in PRIOR_DELTA:
        s = DEPLOYED_REF_SR + d
        print(f"      true level SR {s:.2f} (reference + {d:.1f}): P(pass) {p_pass(s, 51, n_dec):.3f} over 2016-22; "
              f"{p_pass(s, 51, n_dep_long):.3f} over the deployed long window")
    print("\n    the GAIN option (default): SR_gain = delta / f, where delta is the candidates note's level prior "
          "and f = sd(gain)/sd(book), which is NOT measured (a return statistic of the trial). P(pass) at N = 51, 2016-22:")
    mrow = []
    for d in PRIOR_DELTA:
        for f in VOL_RATIO:
            mrow.append(dict(delta=d, f=f, sr_gain=d / f, p_pass=p_pass(d / f, 51, n_dec)))
    mdf = pd.DataFrame(mrow).pivot(index="delta", columns="f", values="p_pass")
    print(mdf.to_string(float_format=lambda x: f"{x:.3f}"))

    n_hold = int(((idx >= HOLDOUT_START)).sum())  # zero: the fit panel stops at 2022-12-30
    Pfull = pd.read_parquet(REPO / "data/cef/cef_prices.parquet", columns=["date"])
    hold_sessions = pd.DatetimeIndex(sorted(pd.to_datetime(Pfull["date"]).unique()))
    hold_sessions = hold_sessions[(hold_sessions >= HOLDOUT_START) & (hold_sessions <= HOLDOUT_END)]
    print(f"\n    holdout 2023-01-03 -> {HOLDOUT_END.date()}: {len(hold_sessions)} sessions in the price panel "
          f"(it ends {hold_sessions.max().date()}; the fixed end needs the panel through {HOLDOUT_END.date()}). "
          "False-kill rate of the sign rule:")
    # sessions after the panel's last date up to the fixed end: weekdays, printed so a reader can check
    # them against the NYSE holiday calendar (none falls in late September 2026)
    extra = int(np.busday_count((hold_sessions.max() + pd.Timedelta(days=1)).date(),
                                (HOLDOUT_END + pd.Timedelta(days=1)).date()))
    nh = len(hold_sessions) + extra
    print(f"      + {extra} weekday session(s) after the panel's last date = {nh} sessions to the fixed end")
    print("      " + "  ".join(f"SR {s:.2f}: {holdout_false_kill(s, nh):.3f}" for s in SR_GRID))
    assert n_hold == 0

    # ---- [5] holdout eligibility: counts on prices, NAVs and volumes only. No position, no return.
    ph = bf.build_panel(end=HOLDOUT_END)
    zh, advh = ph["z"].reindex(columns=U), ph["adv"].reindex(columns=U)
    w = (zh.index >= HOLDOUT_START) & (zh.index <= HOLDOUT_END)
    zh, advh = zh.loc[w], advh.loc[w]
    has_z = zh.notna()
    below = has_z & (advh < MIN_ADV_USD)
    act = ((has_z & (advh >= MIN_ADV_USD)).sum(axis=1) >= MIN_NAMES)
    print(f"\n[5] HOLDOUT ELIGIBILITY 2023-01-03 -> {zh.index.max().date()} (counts only; nothing is positioned or "
          f"returned): the deployed set is active on {act.mean():.1%} of {len(act)} sessions; "
          f"{int(below.sum().sum())} of {int(has_z.sum().sum())} name-days with a z-score ({below.sum().sum() / has_z.sum().sum():.1%}) "
          f"are below the ADV floor, i.e. where the two evaluation sets can differ")
    return cov_name, cov_year, tdf, pdf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cov_name, cov_year, tdf, pdf = run()
    text = buf.getvalue()
    sys.stdout.write(text)
    (OUT_DIR / f"c5_feasibility_output_{STAMP}.txt").write_text(
        f"# python3 scripts/cef/c5_feasibility.py  (run {STAMP}; counts, shares and arithmetic only)\n" + text)
    pd.concat({"by_name": cov_name, "by_year": cov_year.rename(index=str)}).to_csv(OUT_DIR / f"c5_coverage_{STAMP}.csv")
    tdf.to_csv(OUT_DIR / f"c5_trades_{STAMP}.csv")
    pdf.to_csv(OUT_DIR / f"c5_power_{STAMP}.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
