"""Descriptive data quality of the C4 family panels: coverage, gaps, NAV staleness,
ADV against the floor, and NAV/price source agreement.

    python3 scripts/data/cef_families_quality.py     # reads data/cef_families/; writes results/cef/cef_families/

WHAT IT IS NOT. No discount z-score, IC, P&L, Sharpe, correlation with the
book or any forward return is computed here: those are the C4 trial
(`results/cef/RESEARCH_PLAN_2026-10-09.md` §3, order 9), which is spent only
after its pre-registration. The one statistic on changes is the lag-1
autocorrelation of NAV changes, a property of how a NAV is struck, and it is
read only on dates BEFORE the 2023-01-01 time holdout.

OUTPUTS (aggregates only; the repository is public and row-level data stays
under the gitignored data/cef_families/):

    results/cef/cef_families/names_<D>.csv          one row per included fund
    results/cef/cef_families/families_<D>.csv       one row per family
    results/cef/cef_families/breadth_<D>.csv        eligible-name counts by family and year
    results/cef/cef_families/splits_<D>.csv         share-basis check at every yfinance split
    results/cef/cef_families/nav_repeats_<D>.csv    repeated-NAV share by year and family (+ deployed 13)
    results/cef/cef_families/staleness_ref13_<D>.csv  the deployed 13, same NAV method, for reference
    data/cef_families/nav_flags.parquet             per (fund, date): repeat, CEFConnect category, discount check
    data/cef_families/{nav,price,discount}_disagreements.csv   every disagreeing row

METHODS, EACH STATED SO IT CAN BE DISPUTED
------------------------------------------
* **Sessions.** A date is a session if at least MIN_NAMES_FOR_SESSION funds
  in the yfinance panel have a bar on it. The rule-based NYSE calendar
  (`ops/schedule/nyse_calendar.py`) lacks historical one-off closures
  (2001-09-11..14, 2004-06-11, 2007-01-02, ...), so it would count real
  closures as gaps; the panel's own dates do not.
* **Price gaps** = sessions inside [first, last] bar with no bar for the fund.
  **NAV gaps** = sessions inside [first, last] NAV on which the fund has a
  price but no NAV (the sleeve's inner join drops exactly those days).
* **NAV level agreement** (yfinance panel vs CEFConnect, separately for
  CEFConnect's daily `1Y` and weekly `All` windows). AGREE = |difference| <=
  $0.005, the live collector's threshold (docs/DATA.md §5). A disagreeing row
  is then named: SHIFT_PREV / SHIFT_NEXT (CEFConnect equals yfinance's NAV of
  the previous / next session), A_REPEATED (yfinance printed exactly its own
  previous NAV while CEFConnect moved: a stale copy), SPLIT_ADJ (equal once
  yfinance's own split factors are undone), else UNEXPLAINED. Never averaged.
* **Discount agreement** (the quantity the signal uses). yfinance close/NAV - 1
  against CEFConnect's own price/NAV - 1 on common dates. This is basis-free:
  a source that re-based BOTH its price and its NAV still gives the right
  discount. The per-row tolerance is derived, not tuned: half a cent on each of
  the four inputs, summed as fractions. Per fund and era (1Y daily; weekly
  before 2023; weekly 2023 on) the share of rows that agree is binned
  clean (>= 95%), episodic (50-95%) or SYSTEMATIC (< 50%). These bins describe;
  the C4 pre-registration must re-measure and declare its own exclusion rule (H14).
  A defect BOTH vendors share is invisible to this check; the split-basis test
  below is the guard for that.
* **Leg attribution**, for every fund with all four of yfinance close and NAV,
  CEFConnect close and NAV, and CRSP's raw close on a pre-2023 weekly date:
  the medians a = yf close / CRSP, b = CEFConnect close / CRSP, c = yf NAV /
  CEFConnect NAV (`_attribute`). CRSP referees the price leg only.
* **Price agreement** (yfinance close vs CRSP `prc`, to 2024-12-31): AGREE raw,
  SPLIT_ADJ (agrees with CRSP / F(d), F the product of yfinance's split factors
  after d), DISAGREE; CRSP no-trade days (prc <= 0) are counted separately,
  never compared as closes (docs/DATA.md §4 convention). Also vs CEFConnect's
  price over its daily `1Y` window.
* **Split basis.** For each split yfinance records on the price ticker, the
  median close/NAV ratio over the SPLIT_WINDOW paired sessions either side.
  A jump by the split factor means price and NAV sit on different share bases
  on one side of the split. Informative only where |log f| >= log(1.25);
  smaller factors (rights offerings, share distributions) move the ratio less
  than an ordinary premium swing and are left to the discount check.
* **Repeats.** Share of NAV rows exactly equal to the previous NAV row, by
  year and family, all years: an integrity count, not a return statistic.
* **Staleness.** Lag-1 autocorrelation of daily NAV total-return changes,
  (NAV_t + D_t) / NAV_{t-1} - 1, D_t the distribution yfinance books on the
  price ticker's ex-date, over consecutive NAV observations at most
  MAX_GAP_DAYS calendar days apart, on STALE_WINDOW (2013-01-01..2022-12-31:
  the years the live book has traded, cut at the time holdout). A fund
  needs MIN_STALE_OBS changes. Also the share of changes exactly zero. The
  deployed 13 are measured the same way from data/cef/ (read-only) as the
  reference the "stale-NAV control" claim is made against.
* **ADV** is the sleeve's own rule (`src/deploy/sleeves/cef_discount.py`):
  mean close x volume over 63 sessions, at least 21 present, shifted one
  session, read on the panel's last session, against the frozen spec's
  `min_adv_usd` (read through scripts/cef/spec.py, never the literal).
* **Eligible breadth** per session mirrors the sleeve's filters without
  computing a signal: a paired price and NAV that day; at least
  MIN_Z_OBS paired observations in the trailing `z_window` (spec) before it
  (the sleeve's `rolling(z_window, min_periods=120).shift(1)`); ADV as above
  at or above the floor. Reported as the median daily count per year, for
  all funds and again without the funds whose discount is SYSTEMATIC or
  split-basis mismatched. Survivors only: CEFConnect lists live funds, so a
  fund that died before 2026-10-12 is in no count.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data.cef_families_common import (  # noqa: E402
    ACTIONS, FAMILIES, LIVE_DIR, NAV, NAV_CEFCONNECT, OUT_DIR, PRICES, PRICES_CRSP, RESULTS_DIR,
    TIME_HOLDOUT, FamiliesDataError, assert_no_universe_names, cef_universe_names, included,
    load_universe, write_frame)

TOL_USD = 0.005
MIN_NAMES_FOR_SESSION = 10
SPLIT_WINDOW = 20
SPLIT_TEST_MIN_FACTOR = 1.25          # |log f| below log(1.25): the ratio-jump test is not informative
RATIO_TOL = 0.002                     # 20bp: two cent-quoted series on one basis agree far inside this
MAX_GAP_DAYS = 5
STALE_WINDOW = (pd.Timestamp("2013-01-01"), pd.Timestamp("2022-12-31"))
MIN_STALE_OBS = 500
ADV_DAYS, ADV_MIN = 63, 21            # src/deploy/sleeves/cef_discount.py, the `adv` line
MIN_Z_OBS = 120                       # src/deploy/sleeves/cef_discount.py, rolling(..., min_periods=120)
DISC_FLAG = 0.5                       # |close/NAV - 1| above this is flagged as implausible, not dropped
INCEPTION_TOL_DAYS = 31


# ------------------------------------------------------------------ helpers (pure)

def sessions_from(px: pd.DataFrame, min_names: int = MIN_NAMES_FOR_SESSION) -> pd.DatetimeIndex:
    c = px.groupby("date")["ticker"].nunique()
    return pd.DatetimeIndex(sorted(c[c >= min_names].index))


def longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def coverage(px: pd.DataFrame, nav: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Per fund: first/last/rows of price and NAV, gap sessions, longest NAV gap, NAV age at the end."""
    out = []
    last_session = sessions.max()
    for tk, p in px.groupby("ticker"):
        pd_ = pd.DatetimeIndex(p["date"])
        s = sessions[(sessions >= pd_.min()) & (sessions <= pd_.max())]
        row = {"ticker": tk, "px_first": pd_.min().date(), "px_last": pd_.max().date(), "px_rows": len(p),
               "px_gap_sessions": int((~s.isin(pd_)).sum()),
               "px_dates_not_sessions": int((~pd_.isin(sessions)).sum())}
        n = nav[nav["ticker"] == tk]
        if n.empty:
            row.update({"nav_rows": 0})
            out.append(row); continue
        nd = pd.DatetimeIndex(n["date"])
        sn = s[(s >= nd.min()) & (s <= nd.max())]
        has_px = sn.isin(pd_)
        miss = has_px & ~sn.isin(nd)
        paired = pd_.intersection(nd)
        row.update({"nav_first": nd.min().date(), "nav_last": nd.max().date(), "nav_rows": len(n),
                    "nav_gap_sessions": int(miss.sum()), "nav_longest_gap_sessions": longest_run(miss[has_px]),
                    "nav_dates_without_price": int((~nd.isin(pd_)).sum()),
                    "paired_first": paired.min().date() if len(paired) else None,
                    "paired_rows": len(paired),
                    "paired_rows_pre2023": int((paired < TIME_HOLDOUT).sum()),
                    "nav_age_sessions_at_end": int(((sessions > nd.max()) & (sessions <= last_session)).sum())})
        out.append(row)
    return pd.DataFrame(out)


def compare_levels(a: pd.DataFrame, b: pd.DataFrame, col_a: str, col_b: str, tol: float = TOL_USD,
                   shift_ref: pd.DataFrame | None = None, shift_col: str | None = None) -> pd.DataFrame:
    """Row-level (ticker, date) comparison of two level series; category per row.

    AGREE / DISAGREE; a DISAGREE row is re-tested against `shift_ref` (the a-side
    series) on the previous and next available date of the same ticker:
    SHIFT_PREV / SHIFT_NEXT if b equals that within tol, else UNEXPLAINED."""
    m = a[["ticker", "date", col_a]].merge(b[["ticker", "date", col_b]], on=["ticker", "date"])
    m["diff"] = m[col_a] - m[col_b]
    m["category"] = np.where(m["diff"].abs() <= tol, "AGREE", "DISAGREE")
    if shift_ref is not None and (m["category"] == "DISAGREE").any():
        r = shift_ref[["ticker", "date", shift_col]].sort_values(["ticker", "date"]).copy()
        r["prev"] = r.groupby("ticker")[shift_col].shift(1)
        r["next"] = r.groupby("ticker")[shift_col].shift(-1)
        m = m.merge(r[["ticker", "date", "prev", "next"]], on=["ticker", "date"], how="left")
        dis = m["category"] == "DISAGREE"
        prev_ok = dis & ((m["prev"] - m[col_b]).abs() <= tol)
        next_ok = dis & ~prev_ok & ((m["next"] - m[col_b]).abs() <= tol)
        # the a-side printed exactly its previous value while b moved: a stale copy
        repeat = dis & ~prev_ok & ~next_ok & (m[col_a] == m["prev"])
        m.loc[prev_ok, "category"] = "SHIFT_PREV"
        m.loc[next_ok, "category"] = "SHIFT_NEXT"
        m.loc[repeat, "category"] = "A_REPEATED"
        m.loc[dis & ~prev_ok & ~next_ok & ~repeat, "category"] = "UNEXPLAINED"
        m = m.drop(columns=["prev", "next"])
    return m


def summarise_compare(m: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if m.empty:
        return pd.DataFrame(columns=["ticker"])
    g = m.groupby("ticker")
    out = pd.DataFrame({f"{prefix}_n": g.size(),
                        f"{prefix}_agree": g["category"].apply(lambda s: int((s == "AGREE").sum())),
                        f"{prefix}_max_abs_diff": g["diff"].apply(lambda s: float(s.abs().max())),
                        f"{prefix}_first": g["date"].min().dt.date, f"{prefix}_last": g["date"].max().dt.date})
    for c in ("SHIFT_PREV", "SHIFT_NEXT", "A_REPEATED", "SPLIT_ADJ", "UNEXPLAINED", "DISAGREE"):
        if (m["category"] == c).any():
            out[f"{prefix}_{c.lower()}"] = g["category"].apply(lambda s, c=c: int((s == c).sum()))
    return out.reset_index()


def nav_tr_changes(nav: pd.DataFrame, dist: pd.DataFrame, max_gap_days: int = MAX_GAP_DAYS) -> pd.DataFrame:
    """(ticker, date, r) daily NAV total-return changes between consecutive NAV rows <= max_gap_days apart.

    `dist` has ticker, date, amount (cash distribution per share on that ex-date)."""
    n = nav.sort_values(["ticker", "date"]).copy()
    d = dist.assign(amount=pd.to_numeric(dist["amount"]), date=pd.to_datetime(dist["date"]))
    d = d.groupby(["ticker", "date"])["amount"].sum().rename("amount").reset_index()
    n = n.merge(d, on=["ticker", "date"], how="left")
    # `dist` is an EVENT table: a (ticker, date) absent from it is a day with no
    # distribution, so nothing is added back. That is the table's meaning, not a
    # filled-in value. (Its completeness is yfinance's: on the deployed 13, CRSP
    # books 11 distributions yfinance lacks, docs/REFERENCES.md §8; the raw-NAV
    # column `r_raw` is reported beside `r` so a missing event cannot hide.)
    amt = n["amount"].where(n["amount"].notna(), 0.0).astype(float)
    prev = n.groupby("ticker")["nav"].shift(1)
    prev_date = n.groupby("ticker")["date"].shift(1)
    gap = (n["date"] - prev_date).dt.days
    ok = prev.notna() & (prev > 0) & (gap <= max_gap_days)
    n["r"] = np.where(ok, (n["nav"] + amt) / prev - 1.0, np.nan)
    n["r_raw"] = np.where(ok, n["nav"] / prev - 1.0, np.nan)
    return n[["ticker", "date", "r", "r_raw"]]


def lag1(ch: pd.DataFrame, col: str, lo: pd.Timestamp, hi: pd.Timestamp, min_obs: int) -> pd.DataFrame:
    """Per ticker lag-1 autocorrelation of `col` over consecutive valid changes in [lo, hi]."""
    if hi >= TIME_HOLDOUT:
        raise FamiliesDataError(f"staleness window ends {hi.date()}, inside the sealed time holdout")
    out = []
    for tk, g in ch[(ch["date"] >= lo) & (ch["date"] <= hi)].groupby("ticker"):
        x = g[col].to_numpy()
        a, b = x[1:], x[:-1]
        ok = np.isfinite(a) & np.isfinite(b)
        n = int(ok.sum())
        row = {"ticker": tk, "n_changes": int(np.isfinite(x).sum()), "n_pairs": n}
        if n >= min_obs and np.std(a[ok]) > 0 and np.std(b[ok]) > 0:
            row["ac1"] = float(np.corrcoef(a[ok], b[ok])[0, 1])
        row["zero_share"] = float((x[np.isfinite(x)] == 0).mean()) if np.isfinite(x).any() else np.nan
        out.append(row)
    return pd.DataFrame(out)


def split_basis(px: pd.DataFrame, nav: pd.DataFrame, actions: pd.DataFrame, window: int = SPLIT_WINDOW) -> pd.DataFrame:
    """At every yfinance split of a fund with a NAV: median close/NAV before vs after, and a verdict."""
    sp = actions[actions["stock_splits"].fillna(0) != 0]
    pr = px[["ticker", "date", "close"]].merge(nav, on=["ticker", "date"])
    pr["ratio"] = pr["close"] / pr["nav"]
    out = []
    for _, s in sp.iterrows():
        g = pr[pr["ticker"] == s["ticker"]].sort_values("date")
        if g.empty:
            continue
        pre = g[g["date"] < s["date"]].tail(window)["ratio"]
        post = g[g["date"] >= s["date"]].head(window)["ratio"]
        row = {"ticker": s["ticker"], "split_date": s["date"].date(), "factor": float(s["stock_splits"]),
               "n_pre": len(pre), "n_post": len(post)}
        if len(pre) >= 5 and len(post) >= 5:
            jump = float(post.median() / pre.median())
            row.update({"ratio_pre": float(pre.median()), "ratio_post": float(post.median()), "jump": jump})
            f = row["factor"]
            if abs(np.log(f)) < np.log(SPLIT_TEST_MIN_FACTOR):
                # A 1.007-1.10 'split' (rights offering, share distribution) moves the
                # ratio by less than an ordinary premium swing over 20 sessions, so
                # this test cannot see it. The discount check against CEFConnect can.
                row["verdict"] = "factor too small for this test (see the discount check)"
            elif abs(jump - 1) < 0.10:
                row["verdict"] = "same basis"
            elif min(abs(jump / f - 1), abs(jump * f - 1)) < 0.10:
                row["verdict"] = "BASIS MISMATCH (jump ~ split factor)"
            else:
                row["verdict"] = "unclear"
        else:
            row["verdict"] = "no paired NAV on both sides"
        out.append(row)
    return pd.DataFrame(out)


def split_factor(rows: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """F(d) per (ticker, date) row: the product of yfinance's split factors dated AFTER d.

    yfinance back-adjusts a value dated d to `raw / F(d)` (a 1:3 reverse split has
    factor 1/3 and triples earlier prices; a 1.023 'split' -- how Yahoo books
    some rights offerings and stock distributions -- shrinks them by 1/1.023).
    Verified on the data, not assumed: `cef_families_quality` reports how many
    disagreements this explains, per fund."""
    sp = actions[actions["stock_splits"].fillna(0) != 0][["ticker", "date", "stock_splits"]]
    out = pd.Series(1.0, index=rows.index)
    for tk, g in sp.groupby("ticker"):
        m = (rows["ticker"] == tk).to_numpy()
        if not m.any():
            continue
        d = rows.loc[m, "date"].to_numpy()
        f = np.ones(m.sum())
        for sd, fac in zip(g["date"].to_numpy(), g["stock_splits"].to_numpy(dtype=float)):
            f = np.where(d < sd, f * fac, f)
        out[m] = f
    return out


def discount_compare(yf: pd.DataFrame, cc: pd.DataFrame) -> pd.DataFrame:
    """Per (ticker, date): the discount from yfinance (close/NAV - 1) against CEFConnect's
    (its own price/NAV - 1). Basis-free: a source whose price and NAV share a share
    basis gives the same discount whatever adjustment it applied to both.

    Tolerance per row is DERIVED, not tuned: each of the four inputs is quoted to
    the cent, so each can be off by half a cent, and the discount moves by at
    most the sum of 0.005/x over the four of them."""
    m = yf[["ticker", "date", "close", "nav"]].merge(cc[["ticker", "date", "close_cc", "nav", "window"]]
                                                     .rename(columns={"nav": "nav_cc"}), on=["ticker", "date"])
    m = m[(m["nav"] > 0) & (m["nav_cc"] > 0) & (m["close_cc"] > 0)]
    m["disc_yf"] = m["close"] / m["nav"] - 1
    m["disc_cc"] = m["close_cc"] / m["nav_cc"] - 1
    m["ddisc"] = m["disc_yf"] - m["disc_cc"]
    m["tol"] = 0.005 * (1 / m["close"] + 1 / m["nav"] + 1 / m["close_cc"] + 1 / m["nav_cc"])
    m["agree"] = m["ddisc"].abs() <= m["tol"]
    return m


def repeat_share(nav: pd.DataFrame, by) -> pd.DataFrame:
    """Share of NAV rows exactly equal to the fund's previous NAV row, grouped by `by`.

    A data-integrity count (a stale vendor copy prints yesterday's NAV again),
    not a return statistic. On an equity fund an honest repeat needs a move of
    under half a cent, so a share far above the fund's quiet-year level points
    at the vendor, which the CEFConnect check then confirms row by row."""
    n = nav.sort_values(["ticker", "date"]).copy()
    n["repeat"] = n.groupby("ticker")["nav"].diff() == 0
    n["year"] = n["date"].dt.year
    return n.groupby(by)["repeat"].mean()


def adv_panel(px: pd.DataFrame) -> pd.DataFrame:
    """Sleeve ADV: mean close*volume over ADV_DAYS sessions (>= ADV_MIN), shifted one session."""
    dv = (px.assign(dv=px["close"] * px["volume"])
            .pivot_table(index="date", columns="ticker", values="dv").sort_index())
    return dv.rolling(ADV_DAYS, min_periods=ADV_MIN).mean().shift(1)


def eligible_counts(px: pd.DataFrame, nav: pd.DataFrame, floor: float, z_window: int) -> pd.DataFrame:
    """Per session and fund: paired today, >= MIN_Z_OBS paired obs in the trailing z_window
    (shifted one session, as the sleeve's mu/sd are), ADV >= floor. Returns a boolean frame."""
    pr = px[["ticker", "date", "close", "volume"]].merge(nav, on=["ticker", "date"])
    paired = pr.pivot_table(index="date", columns="ticker", values="nav").notna()
    idx = paired.index
    nobs = paired.astype(float).rolling(z_window, min_periods=1).sum().shift(1)
    adv = adv_panel(pr)                                   # the sleeve computes ADV on the inner-joined panel
    adv = adv.reindex(index=idx, columns=paired.columns)
    return paired & (nobs >= MIN_Z_OBS) & (adv >= floor)


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    pd.set_option("compute.use_numexpr", False)        # scripts/events/numexpr_fault.py
    sys.path.insert(0, str(REPO / "scripts" / "cef"))
    import spec                                        # the only reader of the frozen spec
    floor, z_window = float(spec.MIN_ADV_USD), int(spec.Z_WINDOW)
    u = included(load_universe())
    the44 = cef_universe_names()
    assert_no_universe_names(u["ticker"], the44)
    rd = lambda n: pd.read_parquet(OUT_DIR / n)        # noqa: E731
    px, nav, act, cc, crsp = rd(PRICES), rd(NAV), rd(ACTIONS), rd(NAV_CEFCONNECT), rd(PRICES_CRSP)
    craw = rd("crsp_dsf_raw.parquet")
    pmap = pd.read_csv(OUT_DIR / "crsp_permno_map.csv")
    yflog = pd.read_csv(OUT_DIR / "yf_fetch_log.csv")
    for f in (px, nav, act, cc, crsp, craw):
        f["date"] = pd.to_datetime(f["date"]).dt.normalize()
        assert_no_universe_names(f["ticker"].unique(), the44)
    fam = dict(zip(u["ticker"], u["family"]))
    sub = dict(zip(u["ticker"], u["sub"]))
    day = dt.date.today().isoformat()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    sessions = sessions_from(px)
    cov = coverage(px, nav, sessions)

    # ---- NAV agreement: yfinance panel vs CEFConnect, per window
    navc = []
    for w in ("1Y", "All"):
        c = cc[cc["window"] == w].rename(columns={"nav": "nav_cc"})
        m = compare_levels(nav, c, "nav", "nav_cc", shift_ref=nav, shift_col="nav")
        m["window"] = w
        # an UNEXPLAINED row that matches once yfinance's own split factors are undone
        F = split_factor(m, act)
        adj_ok = (m["category"] == "UNEXPLAINED") & ((m["nav"] * F - m["nav_cc"]).abs() <= TOL_USD * np.maximum(1.0, F))
        m.loc[adj_ok, "category"] = "SPLIT_ADJ"
        navc.append(m)
        cov = cov.merge(summarise_compare(m, f"nav_cc{w}"), on="ticker", how="left")
        # CEFConnect dates the yfinance NAV lacks, inside the yfinance NAV's own span
        span = nav.groupby("ticker")["date"].agg(["min", "max"])
        cj = c.merge(span, left_on="ticker", right_index=True)
        cj = cj[(cj["date"] >= cj["min"]) & (cj["date"] <= cj["max"])]
        miss = cj.merge(nav[["ticker", "date"]], on=["ticker", "date"], how="left", indicator=True)
        cov = cov.merge(miss[miss["_merge"] == "left_only"].groupby("ticker").size()
                        .rename(f"nav_cc{w}_dates_missing_in_yf").reset_index(), on="ticker", how="left")
    navc = pd.concat(navc, ignore_index=True)
    write_frame(navc[navc["category"] != "AGREE"], "nav_disagreements.csv")
    # CEFConnect self-consistency: 1Y vs All on common dates
    self_cc = compare_levels(cc[cc.window == "1Y"].rename(columns={"nav": "a"}),
                             cc[cc.window == "All"].rename(columns={"nav": "b"}), "a", "b")
    # CEFConnect funds with no yfinance NAV at all: what CEFConnect alone holds
    cc_span = cc.groupby(["ticker", "window"])["date"].agg(["min", "max", "size"]).unstack("window")
    cc_span.columns = [f"cc_{w}_{s}" for s, w in cc_span.columns]
    cov = cov.merge(cc_span.reset_index(), on="ticker", how="left")

    # ---- price agreement: yfinance vs CRSP (raw prc), and vs CEFConnect price
    cr = craw.copy()
    cr["crsp_close"] = np.where(cr["prc"] > 0, cr["prc"], np.nan)
    yc = px[px["date"] <= cr["date"].max()]
    j = yc[["ticker", "date", "close", "volume"]].merge(cr[["ticker", "date", "prc", "crsp_close", "vol", "cfacpr"]],
                                                         on=["ticker", "date"], how="left")
    F = split_factor(j, act)
    j["crsp_close_yfadj"] = j["crsp_close"] / F
    j["category"] = np.select(
        [j["prc"].isna(), ~(j["prc"] > 0), (j["close"] - j["crsp_close"]).abs() <= TOL_USD,
         (j["close"] - j["crsp_close_yfadj"]).abs() <= TOL_USD / np.minimum(1.0, F)],
        ["NOT_IN_CRSP", "CRSP_NO_TRADE", "AGREE", "SPLIT_ADJ"], "DISAGREE")
    j["diff"] = j["close"] - j["crsp_close"]
    g = j.groupby("ticker")
    pc = pd.DataFrame({
        "crsp_cmp_n": g["category"].apply(lambda s: int(s.isin(["AGREE", "SPLIT_ADJ", "DISAGREE"]).sum())),
        "crsp_cmp_agree": g["category"].apply(lambda s: int((s == "AGREE").sum())),
        "crsp_cmp_split_adj": g["category"].apply(lambda s: int((s == "SPLIT_ADJ").sum())),
        "crsp_cmp_disagree": g["category"].apply(lambda s: int((s == "DISAGREE").sum())),
        "crsp_cmp_max_abs_diff": g["diff"].apply(lambda s: float(s.abs().max()) if s.notna().any() else np.nan),
        "crsp_ratio_median": g[["close", "crsp_close"]].apply(lambda x: float((x["close"] / x["crsp_close"]).median())),
        "yf_bars_on_crsp_no_trade": g["category"].apply(lambda s: int((s == "CRSP_NO_TRADE").sum())),
        "yf_bars_not_in_crsp": g["category"].apply(lambda s: int((s == "NOT_IN_CRSP").sum())),
        "volume_ratio_median_yf_over_crsp": g[["volume", "vol", "category"]].apply(
            lambda x: float((x["volume"] / x["vol"]).replace([np.inf, -np.inf], np.nan)[x["category"] == "AGREE"].median())),
    }).reset_index()
    cov = cov.merge(pc, on="ticker", how="left")
    write_frame(j[j["category"].isin(["DISAGREE"])], "price_disagreements.csv")
    price_cat = j.assign(family=j["ticker"].map(fam)).groupby(["family", "category"]).size().unstack(fill_value=0)
    cps = compare_levels(px, cc[cc.window == "1Y"].rename(columns={"close_cc": "close_cc1y"}), "close", "close_cc1y",
                         shift_ref=px, shift_col="close")
    cov = cov.merge(summarise_compare(cps, "px_cc1Y"), on="ticker", how="left")
    pmap["crsp_mapped"] = pmap["current_permno"].notna()
    # counts only: permno values are licensed identifiers and stay in data/ (.gitignore)
    pmap["permnos_refused_n"] = pmap["permnos_refused"].fillna("").map(lambda v: len(str(v).split()))
    cov = cov.merge(pmap[["ticker", "crsp_mapped", "current_shrcds", "crsp_first", "crsp_last", "crsp_trade_rows",
                          "crsp_no_trade_rows", "predecessor_rows", "permnos_refused_n"]], on="ticker", how="left")
    # CRSP history before the yfinance price history starts (where CRSP adds dates)
    first_yf = px.groupby("ticker")["date"].min()
    first_cr = crsp.groupby("ticker")["date"].min()
    cov["crsp_sessions_before_yf_first"] = cov["ticker"].map(
        lambda t: int(((crsp["ticker"] == t) & (crsp["date"] < first_yf.get(t, pd.Timestamp.max))).sum()))
    cov["crsp_first_trade"] = cov["ticker"].map(lambda t: first_cr.get(t, pd.NaT))

    # ---- discount agreement: yfinance vs CEFConnect (basis-free), per window and era
    dc = discount_compare(px[["ticker", "date", "close"]].merge(nav, on=["ticker", "date"]), cc)
    dc["era"] = np.where(dc["window"] == "1Y", "1Y", np.where(dc["date"] < TIME_HOLDOUT, "All_pre2023", "All_2023on"))
    for era, x in dc.groupby("era"):
        gg = x.groupby("ticker")
        cov = cov.merge(pd.DataFrame({f"disc_{era}_n": gg.size(), f"disc_{era}_agree": gg["agree"].sum(),
                                      f"disc_{era}_median_abs_pp": gg["ddisc"].apply(lambda v: 100 * v.abs().median()),
                                      f"disc_{era}_max_abs_pp": gg["ddisc"].apply(lambda v: 100 * v.abs().max())})
                        .reset_index(), on="ticker", how="left")
    write_frame(dc[~dc["agree"]], "discount_disagreements.csv")
    # Row-level flags for the C4 pre-registration to apply (gitignored data/; never applied here)
    nf = nav.sort_values(["ticker", "date"])[["ticker", "date", "nav"]].copy()
    nf["yf_nav_repeated"] = nf.groupby("ticker")["nav"].diff() == 0
    nf = nf.merge(navc.pivot_table(index=["ticker", "date"], columns="window", values="category", aggfunc="first")
                  .add_prefix("cc_nav_").reset_index(), on=["ticker", "date"], how="left")
    nf = nf.merge(dc.pivot_table(index=["ticker", "date"], columns="window", values="agree", aggfunc="first")
                  .add_prefix("disc_agree_").reset_index(), on=["ticker", "date"], how="left")
    write_frame(nf.drop(columns=["nav"]), "nav_flags.parquet")
    for era in ("1Y", "All_pre2023", "All_2023on"):
        n_, a_ = cov.get(f"disc_{era}_n"), cov.get(f"disc_{era}_agree")
        share = a_ / n_
        cov[f"disc_{era}_class"] = np.select([n_.isna() | (n_ == 0), share >= 0.95, share >= 0.5],
                                             ["unchecked", "clean", "episodic"], "SYSTEMATIC")
    rep = repeat_share(nav.assign(family=nav["ticker"].map(fam)), ["year", "family"]).unstack("family")
    ref_nav = pd.read_parquet(LIVE_DIR / "cef_nav.parquet")
    ref_nav = ref_nav[ref_nav["ticker"].isin(list(spec.UNIVERSE))]
    ref_nav["date"] = pd.to_datetime(ref_nav["date"]).dt.normalize()
    rep["deployed13_reference"] = repeat_share(ref_nav, "year")
    rep.reset_index().to_csv(RESULTS_DIR / f"nav_repeats_{day}.csv", index=False)

    # ---- which leg differs, for every fund (pre-2023 weekly rows where all four sources exist)
    q = dc[dc["era"] == "All_pre2023"].merge(cr[["ticker", "date", "crsp_close"]], on=["ticker", "date"], how="inner")
    q = q[q["crsp_close"] > 0]
    gq = q.groupby("ticker")
    att = pd.DataFrame({"att_n": gq.size(),
                        "med_yfclose_over_crsp": gq.apply(lambda x: float((x["close"] / x["crsp_close"]).median()), include_groups=False),
                        "med_ccclose_over_crsp": gq.apply(lambda x: float((x["close_cc"] / x["crsp_close"]).median()), include_groups=False),
                        "med_yfnav_over_ccnav": gq.apply(lambda x: float((x["nav"] / x["nav_cc"]).median()), include_groups=False)})
    att["leg_attribution"] = att.apply(_attribute, axis=1)
    cov = cov.merge(att.reset_index(), on="ticker", how="left")

    # ---- implausible discount levels (flag, never drop)
    pr = px[["ticker", "date", "close"]].merge(nav, on=["ticker", "date"])
    pr["absdisc"] = (pr["close"] / pr["nav"] - 1).abs()
    flag = pr.groupby("ticker")["absdisc"].agg(lambda s: int((s > DISC_FLAG).sum())).rename("paired_days_abs_disc_gt_50pct")
    cov = cov.merge(flag.reset_index(), on="ticker", how="left")

    # ---- split basis
    sb = split_basis(px, nav, act)
    sb["family"] = sb["ticker"].map(fam)
    sb.to_csv(RESULTS_DIR / f"splits_{day}.csv", index=False)
    mism = sb[sb["verdict"].str.startswith("BASIS MISMATCH")].groupby("ticker")["split_date"].agg(
        lambda v: " ".join(str(x) for x in v)).rename("split_basis_mismatch_before")
    cov = cov.merge(mism.reset_index(), on="ticker", how="left")

    # ---- staleness, pre-holdout only
    dist = act[act["dividends"].fillna(0) != 0][["ticker", "date", "dividends"]].rename(columns={"dividends": "amount"})
    ch = nav_tr_changes(nav, dist)
    st = lag1(ch, "r", *STALE_WINDOW, MIN_STALE_OBS).rename(columns={"ac1": "nav_ac1", "zero_share": "nav_zero_share",
                                                                     "n_changes": "stale_n_changes", "n_pairs": "stale_n_pairs"})
    st_raw = lag1(ch, "r_raw", *STALE_WINDOW, MIN_STALE_OBS)[["ticker", "ac1"]].rename(columns={"ac1": "nav_ac1_raw"})
    cov = cov.merge(st, on="ticker", how="left").merge(st_raw, on="ticker", how="left")
    # reference: the deployed 13 from the live panels, read-only, same method
    ref = _reference13(spec)
    ref.to_csv(RESULTS_DIR / f"staleness_ref13_{day}.csv", index=False)

    # ---- ADV now, against the floor
    adv = adv_panel(px)
    last = adv.index.max()
    adv_last = adv.loc[last].rename("adv63_usd")
    cov = cov.merge(adv_last.reset_index(), on="ticker", how="left")
    cov["adv_asof"] = last.date()
    cov["clears_floor"] = cov["adv63_usd"] >= floor

    # ---- assemble the per-name table
    keep = u[["ticker", "family", "sub", "sponsor", "inception_cefconnect", "alpaca_exchange", "alpaca_tradable",
              "alpaca_shortable", "alpaca_easy_to_borrow", "alpaca_read_utc", "nav_ticker_cefconnect",
              "map_family_2026_10_08", "in_cef_universe_csv"]]
    names = keep.merge(yflog[["ticker", "nav_symbol", "nav_status", "px_duplicate_dates",
                              "px_dropped_no_close_or_volume", "nav_duplicate_dates"]], on="ticker", how="left")
    names = names.merge(cov, on="ticker", how="left")
    inc = pd.to_datetime(names["inception_cefconnect"])
    names["inception_vs_px_first_days"] = (pd.to_datetime(names["px_first"]) - inc).dt.days
    names["inception_vs_crsp_first_days"] = (pd.to_datetime(names["crsp_first_trade"]) - inc).dt.days
    names["nav_verdict"] = names.apply(_nav_verdict, axis=1)
    names.to_csv(RESULTS_DIR / f"names_{day}.csv", index=False)

    # ---- family table and breadth
    fams = _families(names, floor)
    fams.to_csv(RESULTS_DIR / f"families_{day}.csv", index=False)
    systematic = set(names.loc[(names["disc_All_pre2023_class"] == "SYSTEMATIC")
                               | names["split_basis_mismatch_before"].notna(), "ticker"])
    br = _breadth(px, nav, fam, floor, z_window)
    br_clean = _breadth(px, nav[~nav["ticker"].isin(systematic)], fam, floor, z_window)
    br = br.merge(br_clean[["family", "year", "median_eligible"]].rename(
        columns={"median_eligible": "median_eligible_excl_systematic"}), on=["family", "year"], how="left")
    # reference: the deployed 13 on the live panels, read-only, by the same eligibility rule
    lp = pd.read_parquet(LIVE_DIR / "cef_prices.parquet")
    ln = pd.read_parquet(LIVE_DIR / "cef_nav.parquet")
    uni = list(spec.UNIVERSE)
    lp, ln = lp[lp["ticker"].isin(uni)].copy(), ln[ln["ticker"].isin(uni)].copy()
    lp["date"], ln["date"] = pd.to_datetime(lp["date"]).dt.normalize(), pd.to_datetime(ln["date"]).dt.normalize()
    ref_br = _breadth(lp, ln, {t: "deployed13_reference" for t in uni}, floor, z_window,
                      groups={"deployed13_reference": uni})
    ref_br["median_eligible_excl_systematic"] = np.nan
    ref_br["panel_last"] = lp["date"].max().date()
    br = pd.concat([br, ref_br], ignore_index=True)
    br.to_csv(RESULTS_DIR / f"breadth_{day}.csv", index=False)

    print(f"spec min_adv_usd {floor:,.0f}; z_window {z_window}; panel last session {sessions.max().date()}; "
          f"ADV read at {last.date()}")
    print(f"sessions {len(sessions)}; CRSP last {craw['date'].max().date()}; CEFConnect last {cc['date'].max().date()}")
    print(f"CEFConnect 1Y vs All self-check: {len(self_cc)} common rows, "
          f"{int((self_cc.category != 'AGREE').sum())} disagree")
    print(price_cat.to_string())
    print(navc.assign(family=navc["ticker"].map(fam)).groupby(["window", "family", "category"]).size()
          .unstack(fill_value=0).to_string())
    print(fams.T.to_string())
    print(br.pivot(index="year", columns="family", values="median_eligible").to_string())
    print(br.pivot(index="year", columns="family", values="median_eligible_excl_systematic").to_string())
    print("SYSTEMATIC discount disagreement pre-2023 or split-basis mismatch:", sorted(systematic))
    print(names.loc[names["ticker"].isin(systematic), ["ticker", "family", "disc_All_pre2023_n", "disc_All_pre2023_agree",
          "disc_All_pre2023_median_abs_pp", "med_yfclose_over_crsp", "med_ccclose_over_crsp", "med_yfnav_over_ccnav",
          "leg_attribution", "split_basis_mismatch_before"]].to_string(index=False))
    print(rep.loc[2013:].round(3).to_string())
    print(sb.to_string(index=False))
    print(ref.to_string(index=False))
    return 0


def _nav_verdict(r) -> str:
    """Per fund, in words: does the yfinance NAV agree with CEFConnect to the cent,
    and does the DISCOUNT agree within rounding? Stated, never resolved by averaging."""
    if not (r.get("nav_rows") or 0):
        return "NO NAV (yfinance)"
    parts, full = [], True
    for lab in ("1Y", "All"):
        n, a = r.get(f"nav_cc{lab}_n"), r.get(f"nav_cc{lab}_agree")
        if pd.notna(n) and n > 0:
            sa = r.get(f"nav_cc{lab}_split_adj")
            parts.append(f"NAV {lab} {int(a)}/{int(n)} to the cent"
                         + (f" (+{int(sa)} after yf split factors)" if pd.notna(sa) and sa > 0 else ""))
            full &= bool(a == n)
    for era in ("1Y", "All_pre2023", "All_2023on"):
        n, a = r.get(f"disc_{era}_n"), r.get(f"disc_{era}_agree")
        if pd.notna(n) and n > 0:
            parts.append(f"discount {era} {int(a)}/{int(n)}")
    if not parts:
        return "UNCHECKED (no CEFConnect overlap)"
    return ("AGREE: " if full else "DISAGREES: ") + "; ".join(parts)


def _families(names: pd.DataFrame, floor: float) -> pd.DataFrame:
    out = []
    for f in FAMILIES:
        g = names[names["family"] == f]
        withnav = g[g["nav_rows"].fillna(0) > 0]
        n1 = withnav["nav_cc1Y_n"].fillna(0).sum()
        a1 = withnav["nav_cc1Y_agree"].fillna(0).sum()
        nA = withnav["nav_ccAll_n"].fillna(0).sum()
        aA = withnav["nav_ccAll_agree"].fillna(0).sum()
        ac = g["nav_ac1"].dropna()
        out.append({
            "family": f, "names_tradable": len(g), "shortable_today": int(g["alpaca_shortable"].astype(bool).sum()),
            "with_yf_nav": len(withnav),
            "paired_first_min": pd.to_datetime(withnav["paired_first"]).min().date() if len(withnav) else None,
            "paired_first_median": pd.to_datetime(withnav["paired_first"]).median().date() if len(withnav) else None,
            "with_252_paired_pre2023": int((withnav["paired_rows_pre2023"] >= 252).sum()),
            "nav_names_agree_all": int(withnav["nav_verdict"].str.startswith("AGREE").sum()),
            "nav_cc1Y_rows_agree_share": a1 / n1 if n1 else np.nan,
            "nav_ccAll_rows_agree_share": aA / nA if nA else np.nan,
            "disc_1Y_rows_agree_share": _share(withnav, "disc_1Y"),
            "disc_All_pre2023_rows_agree_share": _share(withnav, "disc_All_pre2023"),
            "disc_All_2023on_rows_agree_share": _share(withnav, "disc_All_2023on"),
            "names_disc_pre2023_clean": int((withnav["disc_All_pre2023_class"] == "clean").sum()),
            "names_disc_pre2023_episodic": int((withnav["disc_All_pre2023_class"] == "episodic").sum()),
            "names_disc_pre2023_SYSTEMATIC": int((withnav["disc_All_pre2023_class"] == "SYSTEMATIC").sum()),
            "names_disc_1Y_SYSTEMATIC": int((withnav["disc_1Y_class"] == "SYSTEMATIC").sum()),
            "clear_floor_shortable_not_systematic": int((g["clears_floor"].fillna(False) & g["alpaca_shortable"].astype(bool)
                                                         & (g["nav_rows"].fillna(0) > 0)
                                                         & (g["disc_All_pre2023_class"] != "SYSTEMATIC")
                                                         & (g["disc_1Y_class"] != "SYSTEMATIC")
                                                         & g["split_basis_mismatch_before"].isna()).sum()),
            "names_split_basis_mismatch": int(g["split_basis_mismatch_before"].notna().sum()),
            "crsp_rows_compared": int(g["crsp_cmp_n"].fillna(0).sum()),
            "crsp_rows_agree_raw": int(g["crsp_cmp_agree"].fillna(0).sum()),
            "crsp_rows_agree_after_yf_splits": int(g["crsp_cmp_split_adj"].fillna(0).sum()),
            "crsp_rows_disagree": int(g["crsp_cmp_disagree"].fillna(0).sum()),
            "yf_bars_on_crsp_no_trade": int(g["yf_bars_on_crsp_no_trade"].fillna(0).sum()),
            "nav_ac1_n": len(ac), "nav_ac1_median": ac.median() if len(ac) else np.nan,
            "nav_ac1_p25": ac.quantile(.25) if len(ac) else np.nan, "nav_ac1_p75": ac.quantile(.75) if len(ac) else np.nan,
            "nav_zero_share_median": g["nav_zero_share"].median(),
            "adv63_median_usd": g["adv63_usd"].median(), "adv63_p75_usd": g["adv63_usd"].quantile(.75),
            "adv63_max_usd": g["adv63_usd"].max(),
            "clear_floor": int(g["clears_floor"].fillna(False).sum()),
            "clear_floor_with_nav": int((g["clears_floor"].fillna(False) & (g["nav_rows"].fillna(0) > 0)).sum()),
            "clear_floor_and_shortable": int((g["clears_floor"].fillna(False) & g["alpaca_shortable"].astype(bool)
                                              & (g["nav_rows"].fillna(0) > 0)).sum()),
            "floor_usd": floor,
        })
    return pd.DataFrame(out)


def _attribute(r) -> str:
    """Which leg makes the yfinance and CEFConnect discounts differ, judged against CRSP's raw close.

    yf_disc+1 / cc_disc+1 = (a / b) / c, with a = yf close / CRSP, b = CEFConnect
    close / CRSP, c = yf NAV / CEFConnect NAV (medians). CRSP is the referee for
    prices only; nothing referees the NAV basis, so a NAV-leg difference is left
    open rather than assigned."""
    a, b, c = r["med_yfclose_over_crsp"], r["med_ccclose_over_crsp"], r["med_yfnav_over_ccnav"]
    if any(pd.isna(v) for v in (a, b, c)):
        return "not attributable (a source missing)"
    near = lambda v: abs(v - 1) < RATIO_TOL      # noqa: E731
    if near(a / (b * c)):
        return "consistent (medians)"
    if near(b) and near(c) and not near(a):
        return "yfinance CLOSE re-based, its NAV not: yfinance discount biased"
    if near(a / b) and not near(c):
        return "NAV legs differ; prices agree: attribution open"
    return "mixed"


def _share(g: pd.DataFrame, prefix: str) -> float:
    n, a = g[f"{prefix}_n"].fillna(0).sum(), g[f"{prefix}_agree"].fillna(0).sum()
    return float(a / n) if n else np.nan


def _breadth(px, nav, fam, floor, z_window, groups: dict | None = None) -> pd.DataFrame:
    rows = []
    if groups is None:
        groups = {f: [t for t, x in fam.items() if x == f] for f in FAMILIES}
        groups["all_six"] = list(fam)
    for f, tks in groups.items():
        p, n = px[px["ticker"].isin(tks)], nav[nav["ticker"].isin(tks)]
        if n.empty:
            continue
        el = eligible_counts(p, n, floor, z_window)
        cnt = el.sum(axis=1)
        paired = p[["ticker", "date"]].merge(n[["ticker", "date"]]).groupby("date").size().reindex(cnt.index).fillna(0)
        for y, c in cnt.groupby(cnt.index.year):
            rows.append({"family": f, "year": y, "sessions": len(c), "median_eligible": float(c.median()),
                         "min_eligible": int(c.min()), "max_eligible": int(c.max()),
                         "median_paired": float(paired[paired.index.year == y].median())})
    return pd.DataFrame(rows)


def _reference13(spec) -> pd.DataFrame:
    """The deployed 13 (spec UNIVERSE), NAV staleness by the same method, read-only from data/cef/."""
    n = pd.read_parquet(LIVE_DIR / "cef_nav.parquet")
    d = pd.read_parquet(LIVE_DIR / "cef_distributions.parquet")
    uni = list(spec.UNIVERSE)
    n = n[n["ticker"].isin(uni)].copy()
    n["date"] = pd.to_datetime(n["date"]).dt.normalize()
    d = d[d["ticker"].isin(uni)].rename(columns={"ex_date": "date"})[["ticker", "date", "amount"]]
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    ch = nav_tr_changes(n, d[d["amount"].fillna(0) != 0])
    s = lag1(ch, "r", *STALE_WINDOW, MIN_STALE_OBS).rename(columns={"ac1": "nav_ac1", "zero_share": "nav_zero_share"})
    s["panel_last"] = n["date"].max().date()
    return s


if __name__ == "__main__":
    sys.exit(main())
