"""Is a vendor artefact in the panels the LIVE book decides on? The deployed 13,
yfinance against CEFConnect (NAV and close) and CRSP (close), with the defect's
footprint on the book's decision dates.

    QUANTT_ENV_FILE=<abs path to config/.env> python3 scripts/data/live_nav_quality.py \
        --state-dir <laptop quantt_state/cef> \
        --traded-panel-dir <laptop prod clone>/data/cef  # sources from the cache where present
    ... --refresh                                        # re-fetch every network source

WHY THIS EXISTS
---------------
The C4 families build (`results/cef/CEF_FAMILIES_DATA_2026-10-12.md` §3) found
two yfinance defects on equity CEFs: (1) **stale copies**, a NAV row that
repeats yfinance's own previous NAV while CEFConnect's NAV for that date moved,
in episodes (2019-20, 2022, and 1,514 of 6,488 weekly fund-days in 2023); and
(2) **re-based closes**, a close back-adjusted for an event (rights offering,
share distribution) whose NAV is not, so the discount is biased before the
event. The live book's `data/cef/cef_nav.parquet` and `cef_prices.parquet` come
from the same vendor through `scripts/cef/fetch_daily.py`. A stale NAV under a
moving price is exactly the artefact that killed `single-fund-PD`; a re-based
close is a discount level error. This script measures whether either is in the
live panels, and its footprint on the dates the book decides on.

WHAT IT MEASURES, NOT WHAT IT TESTS
-----------------------------------
ZERO TRIALS. No corrected panel is built and nothing is backtested against the
live one (that would be a variant comparison). No IC, P&L, Sharpe or forward
return is computed. The deployed book's HOLDINGS (the canonical harness,
`scripts/cef/band_frontier.py`: `build_panel`, `build_targets`,
`band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)`) are reconstructed only to
say WHICH names a defect touched on WHICH decision dates; the size of the
defect is reported as a discount error (pp) and a z-score error (pp / the
sleeve's own rolling sd on that date). Nothing else.

THE SOURCES, NEVER AVERAGED
---------------------------
* The development checkout's panels, read-only: `data/cef/cef_prices.parquet`,
  `cef_nav.parquet` (yfinance), restricted to the frozen spec's universe
  (`scripts/cef/spec.py`). Their last dates are printed (2026-09-28 / 2026-09-25
  when this ran). They are NOT the panels the laptop traded on: the 2026-10-12
  version called them "the live panel" (corrected 2026-10-13). The history
  sections [1]-[4] use them; they equal the traded panel on every common NAV row
  but two and every common close ([0b] measures that).
* The TRADED panels (`--traded-panel-dir`, read-only): the laptop prod clone's
  `data/cef`, last written by the asof-2026-10-07 decide run (23:00 ET). The
  fetcher (`scripts/cef/fetch_daily.py`) re-writes the last 6 months on every
  run (`drop_duplicates(keep="last")`), so its LAST date is exactly what that
  run decided on, and older rows are what Yahoo served at 23:00 ET 2026-10-07.
  Used for the live-period mu and sd ([5]) and for the direct read of the
  2026-10-07 decision ([0b]).
* CEFConnect `GET /api/v3/pricinghistory/{TK}/{1Y|All}` (docs/REFERENCES.md §8,
  §12h): `1Y` is daily (2025-10-13 onward), `All` is weekly (Fridays). The two
  windows are kept apart and their common rows are checked against each other.
* yfinance as served now (`history(period='max', auto_adjust=False)`, the live
  fetcher's call), to separate "the vendor's archive carries the defect" from
  "the panel captured a value the vendor later corrected".
* CRSP `crsp_a_stock.dsf` through R2 (`src/data/r2.py`), ticker -> permno by
  date range through `stocknames` (`scripts/data/cef_crosscheck_crsp.py`). To
  2024-12-31, the mirror's last date. Licensed: row-level rows stay in the
  gitignored cache.
* EDGAR: BIT's own filings for the 2025-08-19 event (`SEC_USER_AGENT` from the
  env file, read as `src/data/r2.py` reads values; never printed).
* The laptop prod state (`--state-dir`, read-only): each live session's
  `plan.json` (the z the sleeve computed per name, the closes it used) and the
  collector's `data/<D>/report.json` (its own NAV cross-check). The VM's state
  is not read: this task may not touch the VM.

CLASSIFICATION OF A NAV ROW (yfinance panel vs CEFConnect, one window at a time)
------------------------------------------------------------------------------
AGREE        |yf - cc| <= TOL_USD (half a cent: both quote to the cent).
Otherwise, in this order:
STALE_COPY   yf(t) == yf(t-1) exactly (yfinance repeated its previous row) and
             cc(t) differs from that value. `lagged` marks the subset where
             CEFConnect's value is yfinance's NEXT row (yfinance one day late);
             the rest skipped the day's NAV altogether. Category (a) of the task.
SHIFT_PREV   cc(t) == yf(t-1) while yfinance moved: CEFConnect carried the
             previous NAV (REFERENCES §8: CEFConnect itself flags carried-forward
             NAVs), or yfinance dated a NAV a day early. Not attributed.
SHIFT_NEXT   cc(t) == yf(t+1) without a yfinance repeat: yfinance one day late.
BASIS        a row in a name-year whose median yf/cc ratio over ALL compared
             rows differs from 1 by more than RATIO_TOL: one source on another
             share basis. Category (b).
OTHER        the rest (cent-level differences, restatements). Category (c).
SHIFT_* and OTHER together are category (c) of the task.

The same ladder classifies a CLOSE against CEFConnect's close and CRSP's raw
`prc`; a CRSP `prc <= 0` (no closing trade) is CRSP_NO_TRADE, never compared.

WHO IS RIGHT ON A STALE COPY (`tiebreak`). If CEFConnect's value is the true
NAV the yfinance row skipped, the NEXT yfinance change must contain the skipped
move: regress (first later yfinance NAV that differs) - yf(t) on cc(t) - yf(t).
A slope near 1 says CEFConnect is right; near 0, that its value is noise.

LAGGED WITHOUT A REPEAT (`lag_unrepeated`, daily window only). A stale copy is
not always a repeat. PDI as captured on 2026-09-28: yfinance's 09-24 row is
itself a stale copy (15.12, the 09-23 value), and its 09-25 row is 15.06,
CEFConnect's 09-24 value; the true 09-25 NAV is 15.10. yfinance(D) moved off
yfinance(D-1), so a gate keyed on "NAV(D) == NAV(D-1)" passes it. The test that
catches it: yfinance(D) equals CEFConnect's PREVIOUS row and differs from
CEFConnect(D). It can fire only when yfinance's own D-1 row already disagrees
with CEFConnect's (otherwise it coincides with a repeat).

ALIGNMENT (no lookahead). Every quantity is read at the date it describes. The
z-score error on decision date t uses the sleeve's sd at t, which is
`rolling(z_window).std().shift(1)` (window ending t-1), from the harness.

CORRECTIONS OF 2026-10-13 (independent review; the note's dated correction says
which figures moved):
* [5] rebuilt mu and sd from yfinance as served now, which fills 12 price bars
  the session's panel carried empty (NaN close: the 11 of [0] plus AWF
  2026-04-02, empty in the traded panel only). The sleeve drops those
  name-days, so the rebuild was not the session's; it moved implied NAV
  intervals by up to 0.0028, more than IMPLIED_TOL. mu and sd now come from the
  traded panel; the yfinance-now rebuild is kept as a printed sensitivity.
* [2c] printed |panel - CRSP| next to a dated public close, so CRSP's price was
  recoverable up to sign. CRSP disagreements are now printed only as counts by
  (ticker, year, category) and as magnitude bounds over eras of 3+ rows.
* Output tables are stamped with the UTC date of the latest network fetch they
  rest on, not the date of the run, so a re-run from the cache rewrites the same
  files instead of adding a second dated copy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LIVE_DIR = REPO / "data" / "cef"
OUT_DIR = REPO / "results" / "cef" / "live_nav_quality"
CACHE = OUT_DIR / "_cache_live_nav"          # gitignored: results/**/_cache_*
TOL_USD = 0.005                               # both sources quote to the cent
# yfinance stores float32-rounded values (12.5600004196167); a half-cent comparison
# must not turn 4e-7 of storage noise into a disagreement. 1e-5 is far below a cent.
FLOAT_EPS = 1e-5
# How far a cent-quoted NAV may sit outside the interval a printed z implies and
# still be "the NAV the session used". The interval is exact up to the z rounding
# GIVEN the session's own mu and sd, so those are rebuilt from the panel the
# laptop traded on (`--traded-panel-dir`), never from yfinance as served now.
# The 2026-10-12 version did the latter and so filled 12 price bars the session
# had empty (the sleeve drops a NaN close); that moved implied intervals by up to
# 0.0028, more than this tolerance (review 2026-10-13). The traded panel can
# still differ from the panel a given session read only in rows Yahoo corrected
# between that session and the panel's last write (2026-10-07), inside the 6
# months the fetcher re-writes: a few decide-time copies per name, each moving
# mu by about 0.6pp / 252 and the implied NAV by about 3e-4. 0.002 is a fifth of
# a cent, so two candidates a cent apart are never both accepted unless the
# interval itself is that wide (then the verdict says AMBIGUOUS). The run prints
# the largest accepted distance and the nearest rejected candidate, so the
# margin on both sides is measured, not assumed; the value was not re-chosen.
IMPLIED_TOL = 0.002
RATIO_TOL = 0.002                             # 20bp: a share-basis difference, not a cent
CC_URL = "https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/{window}"
CC_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}   # as scripts/cef/fetch_daily.py
CC_WINDOWS = ("1Y", "All")
W4_FIT_END = pd.Timestamp("2022-12-30")       # results/cef/W4_ARTIFACTS_2026-10-11.md
TIME_HOLDOUT = pd.Timestamp("2023-01-01")
PAPER_START = pd.Timestamp("2026-09-28")      # Alpaca paper, first decision asof (docs/SYSTEM.md)
BIT_CIK = 1562818                             # EDGAR company_tickers.json, read 2026-10-12
BIT_DOCS = (("0001193125-25-174551", "d32051d497ad.htm"),   # 497AD 2025-08-06: terms
            ("0001193125-25-184179", "d45938d424b2.htm"),   # 424B2 2025-08-20: prospectus supplement
            ("0001193125-25-199830", "d947113d497ad.htm"))  # 497AD 2025-09-10: results


class LiveNavQualityError(RuntimeError):
    """A required input is missing or inconsistent. The message names it."""


# ---------------------------------------------------------------- pure methods

def _neighbours(series: pd.DataFrame, col: str) -> pd.DataFrame:
    """(ticker, date, col, prev, next) over the series' OWN rows (its previous and next row)."""
    s = series[["ticker", "date", col]].sort_values(["ticker", "date"]).copy()
    g = s.groupby("ticker")[col]
    s["prev"], s["next"] = g.shift(1), g.shift(-1)
    return s


def classify(a: pd.DataFrame, col_a: str, b: pd.DataFrame, col_b: str, tol: float = TOL_USD,
             ratio_tol: float = RATIO_TOL) -> pd.DataFrame:
    """Row-level (ticker, date) comparison of series a (the panel) against b (a check).

    Returns the inner join with `diff = a - b`, `ratio = a / b`, `category` (the
    module docstring's ladder) and `lagged` (STALE_COPY rows whose b value is
    a's next row). Neighbours are taken over a's own rows, so a weekly b is
    compared with a's daily previous/next rows. Nothing is filled or averaged."""
    n = _neighbours(a, col_a)
    m = n.merge(b[["ticker", "date", col_b]], on=["ticker", "date"], how="inner")
    m = m[(m[col_a] > 0) & (m[col_b] > 0)].copy()
    m["diff"] = m[col_a] - m[col_b]
    m["ratio"] = m[col_a] / m[col_b]
    m["year"] = m["date"].dt.year
    tol = tol + FLOAT_EPS
    agree = m["diff"].abs() <= tol
    repeat = m[col_a] == m["prev"]
    stale = ~agree & repeat
    sprev = ~agree & ~stale & ((m[col_b] - m["prev"]).abs() <= tol)
    snext = ~agree & ~stale & ~sprev & ((m[col_b] - m["next"]).abs() <= tol)
    med = m.groupby(["ticker", "year"])["ratio"].transform("median")
    basis = ~agree & ~stale & ~sprev & ~snext & ((med - 1).abs() > ratio_tol)
    m["category"] = np.select([agree, stale, sprev, snext, basis],
                              ["AGREE", "STALE_COPY", "SHIFT_PREV", "SHIFT_NEXT", "BASIS"], "OTHER")
    m["lagged"] = stale & ((m[col_b] - m["next"]).abs() <= tol)
    m["repeat"] = repeat
    return m


CATS = ("AGREE", "STALE_COPY", "SHIFT_PREV", "SHIFT_NEXT", "BASIS", "OTHER")


def by_name_year(m: pd.DataFrame, label: str) -> pd.DataFrame:
    """Counts per (ticker, year) and category, with the share of compared rows."""
    t = m.groupby(["ticker", "year", "category"]).size().unstack(fill_value=0)
    for c in CATS:
        if c not in t.columns:
            t[c] = 0
    t = t[list(CATS)]
    t.insert(0, "compared", t.sum(axis=1))
    t["stale_lagged"] = m[m["lagged"]].groupby(["ticker", "year"]).size().reindex(t.index).fillna(0).astype(int)
    t["stale_share"] = t["STALE_COPY"] / t["compared"]
    t["basis_share"] = t["BASIS"] / t["compared"]
    t["other_share"] = (t["SHIFT_PREV"] + t["SHIFT_NEXT"] + t["OTHER"]) / t["compared"]
    t.insert(0, "check", label)
    return t.reset_index()


def tiebreak(m: pd.DataFrame, a: pd.DataFrame, col_a: str, col_b: str) -> dict:
    """On STALE_COPY rows: does yfinance's next CHANGE contain the move CEFConnect shows?

    For each stale row, `missed = b(t) - a(t)`; `catch = a(t') - a(t)` with t'
    the first later row of a whose value differs from a(t). OLS slope of catch
    on missed (no intercept is forced; both are reported)."""
    s = a[["ticker", "date", col_a]].sort_values(["ticker", "date"]).reset_index(drop=True)
    out = []
    for tk, g in s.groupby("ticker"):
        v, d = g[col_a].to_numpy(), g["date"].to_numpy()
        # index of the first later row whose value differs, for every row
        nxt = np.full(len(v), -1)
        j = len(v)
        for i in range(len(v) - 1, -1, -1):
            if i + 1 < len(v) and v[i + 1] != v[i]:
                j = i + 1
            nxt[i] = j if j < len(v) else -1
        out.append(pd.DataFrame({"ticker": tk, "date": d,
                                 "catch": np.where(nxt >= 0, v[np.clip(nxt, 0, len(v) - 1)] - v, np.nan),
                                 "steps": np.where(nxt >= 0, nxt - np.arange(len(v)), -1)}))
    c = pd.concat(out, ignore_index=True)
    x = m[m["category"] == "STALE_COPY"].merge(c, on=["ticker", "date"], how="left")
    x["missed"] = x[col_b] - x[col_a]
    x = x[x["catch"].notna()]
    if len(x) < 3:
        return {"n": len(x)}
    X = np.column_stack([np.ones(len(x)), x["missed"].to_numpy()])
    beta, *_ = np.linalg.lstsq(X, x["catch"].to_numpy(), rcond=None)
    resid = x["catch"].to_numpy() - X @ beta
    s2 = resid @ resid / (len(x) - 2)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return {"n": int(len(x)), "intercept": float(beta[0]), "slope": float(beta[1]), "slope_se": float(se[1]),
            "corr": float(np.corrcoef(x["missed"], x["catch"])[0, 1]),
            "sign_agree": float((np.sign(x["missed"]) == np.sign(x["catch"])).mean()),
            "median_steps_to_change": float(np.median(x["steps"]))}


def lag_unrepeated(a: pd.DataFrame, col_a: str, b: pd.DataFrame, col_b: str,
                   tol: float = TOL_USD) -> pd.DataFrame:
    """Rows of a (yfinance) that moved off a's previous row, equal b's PREVIOUS row
    (CEFConnect's D-1) and differ from b(D): D-1's NAV dated D, with no repeat.

    The module docstring's PDI 2026-09-25 case. Meaningful on a DAILY b only: on
    the weekly window b's previous row is a week old. Nothing is filled."""
    n = _neighbours(a, col_a)
    bb = b[["ticker", "date", col_b]].sort_values(["ticker", "date"]).copy()
    bb["b_prev"] = bb.groupby("ticker")[col_b].shift(1)
    m = n.merge(bb, on=["ticker", "date"], how="inner")
    m = m[(m[col_a] > 0) & (m[col_b] > 0)]
    tol = tol + FLOAT_EPS
    moved = (m[col_a] - m["prev"]).abs() > tol
    hit = moved & ((m[col_a] - m["b_prev"]).abs() <= tol) & ((m[col_a] - m[col_b]).abs() > tol)
    return m[hit].copy()


def sleeve_mu_sd(P: pd.DataFrame, N: pd.DataFrame, universe: list[str], z_window: int
                 ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(disc, mu, sd) built as `CEFDiscountSleeve._panel` + `target_positions` build them.

    Inner join of close and NAV on (date, ticker), `nav > 0.5` and `close > 0.5`
    (so a NaN close -- an empty bar -- drops that name-day), pivot, discount in
    pp, `rolling(z_window, min_periods=120)` mean and sd, `shift(1)`: mu and sd at
    D use rows strictly before D (no lookahead). Feed it the panel the session
    read; a panel with the empty bars filled is a different rolling window."""
    d = P[P.ticker.isin(universe)][["ticker", "date", "close"]].merge(
        N[N.ticker.isin(universe)][["ticker", "date", "nav"]], on=["ticker", "date"], how="inner")
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    pxw = d.pivot_table(index="date", columns="ticker", values="close").sort_index()
    nvw = d.pivot_table(index="date", columns="ticker", values="nav").sort_index()
    disc = 100.0 * (pxw - nvw) / nvw
    mu = disc.rolling(z_window, min_periods=120).mean().shift(1)
    sd = disc.rolling(z_window, min_periods=120).std().shift(1)
    return disc, mu, sd


V_FINAL = "used the final NAV(D)"
V_FINAL_EQ = "used the final NAV(D) (equal to NAV(D-1))"
V_STALE = "STALE COPY at decision: used NAV(D-1)"
V_AMBIG = "AMBIGUOUS: NAV(D) and NAV(D-1) both fit the printed z"
V_NEITHER = "used a NAV that is neither final NAV(D) nor NAV(D-1)"
V_NONE = "no z printed (band hold / below min weight / illiquid) or z clipped"


def nav_verdict(lo: float, hi: float, nav_final: float, nav_prev: float,
                tol: float = IMPLIED_TOL) -> tuple[str, float, float]:
    """Which NAV a session used, given the interval [lo, hi] its printed z implies.

    Returns (verdict, distance of final NAV(D), distance of NAV(D-1)); a distance
    is 0 inside the interval and inf for a missing candidate. A candidate within
    `tol` is accepted. When NAV(D) equals NAV(D-1) the two cannot be told apart,
    and the verdict says so rather than calling it stale or final."""
    def dist(v):
        return max(lo - v, 0.0, v - hi) if np.isfinite(v) else np.inf
    df, dp = dist(nav_final), dist(nav_prev)
    fin, prv = df <= tol, dp <= tol
    same = bool(np.isfinite(nav_prev) and np.isfinite(nav_final) and abs(nav_prev - nav_final) < FLOAT_EPS)
    if same:
        return (V_FINAL_EQ if fin else V_NEITHER), df, dp
    if fin and prv:
        return V_AMBIG, df, dp
    if fin:
        return V_FINAL, df, dp
    if prv:
        return V_STALE, df, dp
    return V_NEITHER, df, dp


CRSP_ERAS = ((1900, 2000, "to 2000 (fractional ticks)"), (2001, 2007, "2001-2007"),
             (2008, 2012, "2008-2012"), (2013, 2100, "2013 on"))


def crsp_disagreement_summary(m: pd.DataFrame, min_rows_for_max: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """What may be printed about panel-vs-CRSP disagreements in a public repository.

    (1) counts by (ticker, year, category), with no date; (2) per era: rows
    compared, agreeing, disagreeing, and max |diff| over the disagreeing rows,
    WITHHELD (NaN) when fewer than `min_rows_for_max` rows disagree, since a
    maximum over one row is that row's CRSP price up to sign once the row is
    known. No single row's date sits beside its magnitude."""
    bad = m[m.category != "AGREE"]
    by_tyc = bad.groupby(["ticker", "year", "category"]).size().rename("rows").to_frame()
    out = []
    for lo, hi, lab in CRSP_ERAS:
        x = m[(m.year >= lo) & (m.year <= hi)]
        b = x[x.category != "AGREE"]
        out.append({"era": lab, "compared": len(x), "agree": int((x.category == "AGREE").sum()),
                    "differ": len(b),
                    "max_abs_diff_usd": round(float(b["diff"].abs().max()), 3) if len(b) >= min_rows_for_max
                    else np.nan})
    return by_tyc, pd.DataFrame(out)


def implied_nav(close: float, z: float, mu: float, sd: float, z_dp: int = 2) -> tuple[float, float, float]:
    """The NAV a session must have used, given the z it printed (rounded to z_dp places).

    The sleeve: disc = 100 (px - nav) / nav, z = (disc - mu) / sd, clipped to
    [-4, 4]. Inverting, nav = px / (1 + (mu + z sd) / 100). The printed z is
    rounded, so the NAV is an interval: returns (nav_mid, nav_lo, nav_hi).
    A clipped z (|z| == 4) does not identify the NAV and raises."""
    if abs(abs(z) - 4.0) < 1e-9:
        raise LiveNavQualityError("z is at the clip (|z| = 4): the NAV is not identified")
    h = 0.5 * 10 ** (-z_dp)
    f = lambda zz: close / (1.0 + (mu + zz * sd) / 100.0)   # noqa: E731
    a, b = f(z - h), f(z + h)
    return f(z), min(a, b), max(a, b)


# ---------------------------------------------------------------- sources (network inside functions)

def _cache(name: str) -> Path:
    p = CACHE / name
    p.parent.mkdir(parents=True, exist_ok=True)
    rp, live = p.resolve(), LIVE_DIR.resolve()
    if live in rp.parents or rp == live:
        raise LiveNavQualityError(f"refusing to write {rp}: inside the live panel directory {live}")
    return p


def load_live(universe: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The live panels for the universe, read-only. Raises if a name is absent."""
    P = pd.read_parquet(LIVE_DIR / "cef_prices.parquet")
    N = pd.read_parquet(LIVE_DIR / "cef_nav.parquet")
    for f, lab in ((P, "cef_prices"), (N, "cef_nav")):
        miss = sorted(set(universe) - set(f["ticker"]))
        if miss:
            raise LiveNavQualityError(f"{lab}.parquet has no rows for {miss}")
        f["date"] = pd.to_datetime(f["date"]).dt.normalize()
        if f.duplicated(["ticker", "date"]).any():
            raise LiveNavQualityError(f"{lab}.parquet has duplicate (ticker, date) rows")
    return P[P.ticker.isin(universe)].copy(), N[N.ticker.isin(universe)].copy()


def load_traded(traded_dir: Path, universe: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """The panels the laptop prod clone traded on, read-only, and their file write times (UTC).

    Raises if a file or a universe name is missing, or a (ticker, date) repeats:
    the live-period inversion must rest on the session's own panel or on nothing."""
    out, mt = [], {}
    for name in ("cef_prices.parquet", "cef_nav.parquet"):
        f = traded_dir / name
        if not f.exists():
            raise LiveNavQualityError(f"traded panel {f} does not exist")
        x = pd.read_parquet(f)
        miss = sorted(set(universe) - set(x["ticker"]))
        if miss:
            raise LiveNavQualityError(f"traded {name} has no rows for {miss}")
        x["date"] = pd.to_datetime(x["date"]).dt.normalize()
        if x.duplicated(["ticker", "date"]).any():
            raise LiveNavQualityError(f"traded {name} has duplicate (ticker, date) rows")
        out.append(x[x.ticker.isin(universe)].copy())
        mt[name] = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out[0], out[1], mt


def fetch_cefconnect(universe: list[str], refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """CEFConnect 1Y (daily) and All (weekly) rows; raw JSON cached with the fetch time."""
    rows, log = [], []
    for tk in universe:
        for w in CC_WINDOWS:
            p = _cache(f"cefconnect/{tk}_{w}.json")
            if refresh or not p.exists():
                import requests
                url = CC_URL.format(ticker=tk, window=w)
                r = requests.get(url, headers=CC_HEADERS, timeout=30)
                if r.status_code != 200:
                    raise LiveNavQualityError(f"GET {url} -> HTTP {r.status_code}")
                body = r.json()
                try:
                    data = body["Data"]["PriceHistory"]
                except (KeyError, TypeError) as e:
                    raise LiveNavQualityError(f"GET {url}: no Data.PriceHistory") from e
                p.write_text(json.dumps({"url": url, "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                                         "rows": data}) + "\n")
                time.sleep(0.3)
            d = json.loads(p.read_text())
            x = pd.DataFrame(d["rows"] or [], columns=["DataDate", "NAVData", "Data", "DiscountData"])
            log.append({"ticker": tk, "window": w, "rows": len(x), "fetched_at_utc": d["fetched_at_utc"],
                        "rows_without_nav": int(x["NAVData"].isna().sum())})
            x = x[x["NAVData"].notna()]
            if x.empty:
                continue
            x = pd.DataFrame({"ticker": tk, "date": pd.to_datetime(x["DataDate"]).dt.normalize(),
                              "nav_cc": x["NAVData"].astype(float), "close_cc": x["Data"].astype(float),
                              "disc_cc": x["DiscountData"].astype(float), "window": w})
            if x.duplicated("date").any():
                raise LiveNavQualityError(f"CEFConnect {tk} {w}: rows share a date")
            rows.append(x)
    return pd.concat(rows, ignore_index=True), pd.DataFrame(log)


def fetch_yf_now(universe: list[str], refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    """yfinance as served now: the live fetcher's call, full history. Cached."""
    pp, pn, pa, pt = (_cache("yfinance/yf_prices_now.parquet"), _cache("yfinance/yf_nav_now.parquet"),
                      _cache("yfinance/yf_actions_now.parquet"), _cache("yfinance/fetched_at_utc.txt"))
    if refresh or not (pp.exists() and pn.exists() and pa.exists() and pt.exists()):
        import yfinance as yf
        px, nav, act = [], [], []
        for tk in universe:
            h = yf.Ticker(tk).history(period="max", auto_adjust=False, actions=True).reset_index()
            if h.empty:
                raise LiveNavQualityError(f"yfinance returned no price history for {tk}")
            h["date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.normalize()
            px.append(pd.DataFrame({"date": h.date, "open": h.Open, "high": h.High, "low": h.Low,
                                    "close": h.Close, "volume": h.Volume, "ticker": tk}))
            act.append(pd.DataFrame({"date": h.date, "ticker": tk, "dividends": h["Dividends"],
                                     "stock_splits": h["Stock Splits"]}))
            n = yf.Ticker(f"X{tk}X").history(period="max", auto_adjust=False).reset_index()
            if n.empty:
                raise LiveNavQualityError(f"yfinance returned no NAV history for X{tk}X")
            n["date"] = pd.to_datetime(n["Date"]).dt.tz_localize(None).dt.normalize()
            nav.append(pd.DataFrame({"date": n.date, "nav": n.Close, "ticker": tk}))
        A = pd.concat(act, ignore_index=True)
        pd.concat(px, ignore_index=True).to_parquet(pp)
        pd.concat(nav, ignore_index=True).to_parquet(pn)
        A[(A.dividends != 0) | (A.stock_splits != 0)].to_parquet(pa)
        pt.write_text(dt.datetime.now(dt.timezone.utc).isoformat() + "\n")
    return pd.read_parquet(pp), pd.read_parquet(pn), pd.read_parquet(pa), pt.read_text().strip()


def fetch_crsp(universe: list[str], lo: pd.Timestamp, refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """CRSP stocknames for the tickers and dsf rows for their permnos (R2, read-only). Cached."""
    pn, pd_ = _cache("crsp/stocknames.parquet"), _cache("crsp/dsf.parquet")
    if refresh or not (pn.exists() and pd_.exists()):
        from src.data import r2
        cfg = r2.load_config()
        con = r2.connect(cfg)
        base = f"s3://{cfg.bucket}/wrds/crsp_a_stock"
        names = con.execute(
            f"SELECT permno, ticker, namedt, nameenddt, shrcd, comnam FROM read_parquet('{base}/stocknames.parquet') "
            f"WHERE ticker IN ({','.join('?' * len(universe))})", list(universe)).df()
        permnos = sorted(int(p) for p in names["permno"].unique())
        if not permnos:
            raise LiveNavQualityError("no universe ticker appears in crsp_a_stock.stocknames")
        dsf = con.execute(
            f"SELECT permno, date, prc, cfacpr, vol FROM read_parquet('{base}/dsf.parquet') "
            f"WHERE permno IN ({','.join('?' * len(permnos))}) AND date >= ?", permnos + [lo.date()]).df()
        names.to_parquet(pn)
        dsf.to_parquet(pd_)
    names, dsf = pd.read_parquet(pn), pd.read_parquet(pd_)
    dsf["date"] = pd.to_datetime(dsf["date"]).dt.normalize()
    return names, dsf


def fetch_edgar_bit(refresh: bool) -> dict:
    """BIT's three filings for the 2025 rights offering, cached; key facts parsed, each asserted."""
    import html as _html
    txt = {}
    for acc, doc in BIT_DOCS:
        p = _cache(f"edgar/{doc}")
        if refresh or not p.exists():
            import requests
            from src.data import r2
            ua = r2._read_env(r2.env_file_path()).get("SEC_USER_AGENT")
            if not ua:
                raise LiveNavQualityError("SEC_USER_AGENT is not set in the env file")
            url = f"https://www.sec.gov/Archives/edgar/data/{BIT_CIK}/{acc.replace('-', '')}/{doc}"
            r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=60)
            if r.status_code != 200:
                raise LiveNavQualityError(f"GET {url} -> HTTP {r.status_code}")
            p.write_text(r.text)
            time.sleep(0.5)
        t = re.sub(r"<[^>]+>", " ", p.read_text())
        txt[doc] = re.sub(r"\s+", " ", _html.unescape(t))
    facts = {}
    need = {
        "record_date": (BIT_DOCS[1][1], r"Record Date (\w+ \d{1,2}, \d{4})"),
        "expiration": (BIT_DOCS[1][1], r"Expiration Date\* (\w+ \d{1,2}, \d{4})"),
        "issuance": (BIT_DOCS[1][1], r"Issuance Date (\w+ \d{1,2}, \d{4})"),
        "rights": (BIT_DOCS[1][1], r"([\d,]+) Rights for ([\d,]+) Common Shares"),
        "ratio": (BIT_DOCS[0][1], r"one new Share for every (\d) Rights held"),
        "subscription_price": (BIT_DOCS[2][1], r"final subscription price of \$([\d.]+) per Common Share"),
        "price_rule": (BIT_DOCS[2][1], r"formula equal to (\d+)% of the net asset value as of ([\d/]+)"),
    }
    for k, (doc, pat) in need.items():
        mm = re.search(pat, txt[doc])
        if not mm:
            raise LiveNavQualityError(f"EDGAR {doc}: could not find {k!r} ({pat})")
        facts[k] = mm.groups() if len(mm.groups()) > 1 else mm.group(1)
    return facts


def load_plans(state_dir: Path, universe: list[str]) -> pd.DataFrame:
    """One row per (live decision asof, name): the z the session printed, its close, what it did.

    Read-only from the laptop prod state. A plan with no z for a name (band hold,
    below min weight, illiquid) carries z = NaN and says why. `submitted` is True
    only if `orders.jsonl` records a `submit` event for the name (an order that
    reached the broker); `sent` is the session's DONE line. `decided_at_utc` is
    the run that wrote the plan (DECIDED file), or the first run for a plan
    without one (the opening session)."""
    rows = []
    for f in sorted(state_dir.glob("2026-*/plan.json")):
        p = json.loads(f.read_text())
        d = f.parent
        asof = pd.Timestamp(p["asof"])
        submitted, n_submit = set(), 0
        if (d / "orders.jsonl").exists():
            for line in (d / "orders.jsonl").read_text().splitlines():
                e = json.loads(line)
                if e.get("event") == "submit":
                    submitted.add(e["symbol"])
                    n_submit += 1               # every order, a flip's two legs included
        done = (d / "DONE").read_text().strip() if (d / "DONE").exists() else ""
        # When the z values were computed: the plan file's own write time. A refused plan
        # is rewritten by every retry, so the DECIDED line or the first run would be wrong.
        decided = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        closes = p.get("closes") or {}
        for tk in universe:
            t = (p.get("targets") or {}).get(tk, {})
            reason = t.get("reason", "")
            mz = re.search(r"z=([-+]?\d+\.\d+)", reason)
            rows.append({"session": p["session_date"], "asof": asof, "status": p.get("status", "opening (no status field)"),
                         "decided_at_utc": decided, "sent": done.startswith("SENT") or bool(submitted),
                         "ticker": tk, "z_plan": float(mz.group(1)) if mz else np.nan,
                         "close_plan": closes.get(tk, np.nan), "current": t.get("current"),
                         "target": t.get("target"), "submitted": tk in submitted,
                         "session_orders_submitted": n_submit, "reason": reason})
    if not rows:
        raise LiveNavQualityError(f"no plan.json under {state_dir}")
    return pd.DataFrame(rows)


def load_collector(state_dir: Path) -> pd.DataFrame:
    """The collector's own nav_crosscheck per data day: flags and gaps (read-only)."""
    out = []
    for f in sorted(state_dir.glob("data/*/report.json")):
        r = json.loads(f.read_text())
        st = (r.get("steps") or {}).get("nav_crosscheck") or {}
        fl = [x for x in r.get("flags", []) if x.get("step") == "nav_crosscheck"]
        gp = [x for x in r.get("gaps", []) if x.get("step") == "nav_crosscheck"]
        at = st.get("at")
        # The ET wall time, with its weekday: the 2026-10-12 note called every run
        # "about 21:40 ET", which held for 4 of 7 (review 2026-10-13).
        et = (pd.Timestamp(at).tz_convert("America/New_York").strftime("%a %Y-%m-%d %H:%M ET")
              if at else None)
        out.append({"day": r["date"], "checked_at_utc": at, "checked_at_et": et, "flags": len(fl),
                    "gaps": len(gp),
                    "flagged": " ".join(f"{x['fund']}:{x['value_a']:.2f}/{x['value_b']:.2f}" for x in fl)})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- analysis

def deployed_book():
    """The harness's deployed book on the live panel: (panel dict, eligible mask, decision dates, H)."""
    from scripts.cef.band_frontier import MIN_ADV, band_gross_capped, build_panel, build_targets
    from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, MIN_NAMES, UNIVERSE
    U = list(UNIVERSE)
    p = build_panel()
    z, adv = p["z"][U], p["adv"][U]
    elig = z.notna() & (adv >= MIN_ADV)
    dec = elig.sum(axis=1) >= MIN_NAMES             # the dates build_targets acts on
    T, _ = build_targets()
    H = band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf)
    return p, elig, dec, H


def footprint(cls: pd.DataFrame, p: dict, elig: pd.DataFrame, dec: pd.Series, H: pd.DataFrame,
              nav: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per (decision date, name): eligible / held / traded, checked or not, the defect, its size.

    `cls` is the NAV classification (both windows; a date in both uses the
    daily row). Size on a defective NAV row: d_disc = 100 px (1/nav_yf -
    1/nav_cc) in pp, d_z = d_disc / sd_t (the sleeve's sd at t)."""
    first = H.index[(H.abs().sum(axis=1) > 0)].min()
    dates = dec[dec & (dec.index >= first)].index
    U = list(H.columns)
    Hd = H.reindex(dates)
    prevH = H.shift(1).reindex(dates)
    held = (Hd.abs() > 1e-12)
    traded = ((Hd - prevH).abs() > 1e-12)
    e = elig.reindex(index=dates, columns=U).fillna(False)
    long = pd.DataFrame({"date": np.repeat(dates.values, len(U)), "ticker": np.tile(U, len(dates)),
                         "eligible": e.values.ravel(), "held": held.values.ravel(),
                         "traded": traded.values.ravel()})
    c = cls.sort_values("window").drop_duplicates(["ticker", "date"], keep="first")   # "1Y" < "All"
    long = long.merge(c[["ticker", "date", "category", "nav_cc", "window", "lagged"]], on=["ticker", "date"], how="left")
    rep = nav.sort_values(["ticker", "date"]).copy()
    rep["repeat"] = rep.groupby("ticker")["nav"].diff() == 0
    long = long.merge(rep[["ticker", "date", "nav", "repeat"]], on=["ticker", "date"], how="left")
    # a decision date with no NAV row for the name cannot be a repeat; it is not an invented value
    long["repeat"] = long["repeat"].astype("boolean").fillna(False).astype(bool)
    px = p["px"].reindex(index=dates, columns=U).stack().rename("px").reset_index()
    sd = p["sd"].reindex(index=dates, columns=U).stack().rename("sd").reset_index()
    z = p["z"].reindex(index=dates, columns=U).stack().rename("z").reset_index()
    for f in (px, sd, z):
        f.columns = ["date", "ticker", f.columns[-1]]
        long = long.merge(f, on=["date", "ticker"], how="left")
    long["checked"] = long["category"].notna()
    bad = long["category"].isin(["STALE_COPY", "SHIFT_PREV", "SHIFT_NEXT", "BASIS", "OTHER"])
    long["d_disc_pp"] = np.where(bad, 100 * long["px"] * (1 / long["nav"] - 1 / long["nav_cc"]), np.nan)
    long["d_z"] = long["d_disc_pp"] / long["sd"]
    return long, pd.DataFrame({"first_position": [first.date()], "decision_dates": [len(dates)]})


def summarise_footprint(long: pd.DataFrame, eras: list[tuple[str, str, str]]) -> pd.DataFrame:
    out = []
    for lab, lo, hi in eras:
        x = long[(long["date"] >= pd.Timestamp(lo)) & (long["date"] <= pd.Timestamp(hi))]
        if x.empty:
            continue
        dd = x.groupby("date")
        row = {"era": lab, "from": x["date"].min().date(), "to": x["date"].max().date(),
               "decision_dates": x["date"].nunique(),
               "checked_dates": int(dd["checked"].any().sum())}
        for scope in ("eligible", "held", "traded"):
            s = x[x[scope]]
            sd_ = s.groupby("date")
            st = s["category"] == "STALE_COPY"
            dfx = s["category"].isin(["STALE_COPY", "SHIFT_PREV", "SHIFT_NEXT", "BASIS", "OTHER"])
            row[f"{scope}_name_days"] = len(s)
            row[f"{scope}_name_days_checked"] = int(s["checked"].sum())
            row[f"{scope}_stale_name_days"] = int(st.sum())
            row[f"{scope}_any_defect_name_days"] = int(dfx.sum())
            row[f"{scope}_dates_with_stale"] = int(st.groupby(s["date"]).any().sum())
            row[f"{scope}_dates_with_any_defect"] = int(dfx.groupby(s["date"]).any().sum())
            row[f"{scope}_repeat_name_days_unchecked"] = int((s["repeat"] & ~s["checked"]).sum())
            row[f"{scope}_dates_with_repeat_unchecked"] = int((s["repeat"] & ~s["checked"])
                                                              .groupby(s["date"]).any().sum())
            v = s.loc[st, "d_disc_pp"].abs()
            w = s.loc[st, "d_z"].abs()
            row[f"{scope}_stale_abs_ddisc_pp_median"] = float(v.median()) if len(v) else np.nan
            row[f"{scope}_stale_abs_ddisc_pp_p90"] = float(v.quantile(0.9)) if len(v) else np.nan
            row[f"{scope}_stale_abs_ddisc_pp_max"] = float(v.max()) if len(v) else np.nan
            row[f"{scope}_stale_abs_dz_median"] = float(w.median()) if len(w) else np.nan
            row[f"{scope}_stale_abs_dz_p90"] = float(w.quantile(0.9)) if len(w) else np.nan
            row[f"{scope}_stale_abs_dz_max"] = float(w.max()) if len(w) else np.nan
        out.append(row)
    return pd.DataFrame(out)


def live_period(plans: pd.DataFrame, traded_P: pd.DataFrame, traded_N: pd.DataFrame,
                nav_now: pd.DataFrame, px_now: pd.DataFrame, cc: pd.DataFrame) -> pd.DataFrame:
    """For every live decision (asof, name) with a printed z: the NAV the session must have used,
    against yfinance-now NAV(D), NAV(D-1) and CEFConnect's daily NAV(D).

    mu and sd come from the TRADED panel (`sleeve_mu_sd`), which carries the empty
    bars the session carried; at D they use rows before D only, all of which the
    traded panel holds for every laptop decision. The candidates (final NAV(D),
    NAV(D-1)) come from yfinance as served now. A second rebuild from yfinance-now
    (the 2026-10-12 method) is kept as `*_yfnow` columns, a sensitivity only.
    `z_final` is the z the session would have printed on the final NAV(D), with
    its own mu and sd. The plan's own close is used."""
    from scripts.cef.spec import Z_WINDOW
    U = sorted(plans["ticker"].unique())
    _, mu, sd = sleeve_mu_sd(traded_P, traded_N, U, Z_WINDOW)
    _, mu_y, sd_y = sleeve_mu_sd(px_now, nav_now, U, Z_WINDOW)
    n = nav_now.sort_values(["ticker", "date"]).copy()
    n["nav_prev_now"] = n.groupby("ticker")["nav"].shift(1)
    c1 = cc[cc.window == "1Y"][["ticker", "date", "nav_cc"]]
    out = []
    for _, r in plans.iterrows():
        a, tk = r["asof"], r["ticker"]
        if a not in mu.index:
            raise LiveNavQualityError(f"the traded panel has no row dated {a.date()} (decision asof); "
                                      f"it cannot give that session's mu and sd")
        row = r.to_dict()
        nn = n[(n.ticker == tk) & (n.date == a)]
        row["nav_now"] = float(nn["nav"].iloc[0]) if len(nn) else np.nan
        row["nav_prev_now"] = float(nn["nav_prev_now"].iloc[0]) if len(nn) else np.nan
        cr = c1[(c1.ticker == tk) & (c1.date == a)]
        row["nav_cc"] = float(cr["nav_cc"].iloc[0]) if len(cr) else np.nan
        row["mu"], row["sd"] = float(mu.at[a, tk]), float(sd.at[a, tk])
        row["mu_yfnow"] = float(mu_y.at[a, tk]) if a in mu_y.index else np.nan
        row["sd_yfnow"] = float(sd_y.at[a, tk]) if a in sd_y.index else np.nan
        # The opening session's plan predates the `closes` field. Its close is then read
        # from the traded panel, which the session read (and which equals yfinance-now
        # on every common close, [0b]); the source is recorded, never blended.
        close, row["close_source"] = float(r["close_plan"]), "plan"
        if not np.isfinite(close):
            pc = traded_P[(traded_P.ticker == tk) & (traded_P.date == a)]["close"]
            close, row["close_source"] = (float(pc.iloc[0]), "traded panel (plan has no closes)") if len(pc) \
                else (np.nan, "none")
        row["close_used"] = close
        if np.isfinite(row["z_plan"]) and np.isfinite(row["mu"]) and np.isfinite(close) \
                and abs(abs(row["z_plan"]) - 4) > 1e-9:
            mid, lo, hi = implied_nav(close, float(r["z_plan"]), row["mu"], row["sd"])
            row.update(nav_used_mid=mid, nav_used_lo=lo, nav_used_hi=hi)
            row["verdict"], row["dist_final"], row["dist_prev"] = nav_verdict(lo, hi, row["nav_now"],
                                                                                row["nav_prev_now"])
            same = np.isfinite(row["nav_prev_now"]) and abs(row["nav_prev_now"] - row["nav_now"]) < FLOAT_EPS
            row["one_cent_case"] = (not same) and abs(row["nav_prev_now"] - row["nav_now"]) <= 0.01 + FLOAT_EPS
            disc_final = 100.0 * (close - row["nav_now"]) / row["nav_now"]
            row["z_final"] = float(np.clip((disc_final - row["mu"]) / row["sd"], -4, 4))
            row["dz_plan_minus_final"] = row["z_plan"] - row["z_final"]
            if np.isfinite(row["mu_yfnow"]):
                _, lo_y, hi_y = implied_nav(close, float(r["z_plan"]), row["mu_yfnow"], row["sd_yfnow"])
                row["verdict_yfnow"], row["dist_final_yfnow"], row["dist_prev_yfnow"] = nav_verdict(
                    lo_y, hi_y, row["nav_now"], row["nav_prev_now"])
                row["interval_shift_vs_yfnow"] = max(abs(lo - lo_y), abs(hi - hi_y))
        else:
            row["verdict"] = V_NONE
        out.append(row)
    return pd.DataFrame(out)


def bit_event(P: pd.DataFrame, N: pd.DataFrame, cc: pd.DataFrame, px_now: pd.DataFrame, dsf: pd.DataFrame,
              names: pd.DataFrame, facts: dict, p: dict) -> dict:
    """BIT 2025-08-19: is the panel close re-based against its NAV, and what does the event do to
    the discount and the z window? Measured, not assumed."""
    from scripts.cef.spec import Z_WINDOW
    rec = pd.Timestamp(dt.datetime.strptime(facts["record_date"], "%B %d, %Y"))
    exp_ = pd.Timestamp(dt.datetime.strptime(facts["expiration"], "%B %d, %Y"))
    b = P[P.ticker == "BIT"][["date", "close"]].merge(N[N.ticker == "BIT"][["date", "nav"]], on="date").sort_values("date")
    b["disc"] = 100 * (b.close / b.nav - 1)
    res = {"record_date": rec.date(), "expiration": exp_.date(), **{k: facts[k] for k in ("issuance", "rights", "ratio",
                                                                                              "subscription_price", "price_rule")}}
    # 1) basis BEFORE the event: panel close vs CEFConnect close (weekly) and vs CRSP raw prc
    c = cc[(cc.ticker == "BIT")].drop_duplicates("date")
    j = b.merge(c[["date", "close_cc", "nav_cc"]], on="date")
    pre = j[j.date < rec]
    res["pre_close_vs_cc_rows"] = len(pre)
    tol = TOL_USD + FLOAT_EPS
    res["pre_close_vs_cc_agree"] = int(((pre.close - pre.close_cc).abs() <= tol).sum())
    res["pre_close_over_cc_median"] = float((pre.close / pre.close_cc).median())
    res["pre_nav_vs_cc_agree"] = int(((pre.nav - pre.nav_cc).abs() <= tol).sum())
    res["close_vs_cc_disagree_rows"] = j.loc[(j.close - j.close_cc).abs() > tol, ["date", "close", "close_cc"]].to_dict("records")
    post = j[j.date >= rec]
    res["post_close_vs_cc_rows"] = len(post)
    res["post_close_vs_cc_agree"] = int(((post.close - post.close_cc).abs() <= tol).sum())
    res["post_rows_with_no_panel_close"] = post.loc[post.close.isna(), "date"].dt.date.astype(str).tolist()
    nm = names[(names.ticker == "BIT") & names.shrcd.isin([14, 44])]
    if nm.empty:
        raise LiveNavQualityError("no CRSP closed-end-fund permno for BIT")
    cr = dsf[dsf.permno.isin(nm.permno.unique())][["date", "prc"]]
    k = b.merge(cr, on="date")
    k = k[k.prc > 0]
    res["crsp_rows"] = len(k)
    res["crsp_close_agree"] = int(((k.close - k.prc).abs() <= tol).sum())
    res["crsp_last"] = cr["date"].max().date()
    # 2) yfinance as served now: is BIT's pre-event close re-based today?
    yn = px_now[px_now.ticker == "BIT"][["date", "close"]].rename(columns={"close": "close_now"})
    q = b.merge(yn, on="date")
    res["panel_vs_yf_now_close_differ"] = int(((q.close - q.close_now).abs() > tol).sum())
    # 3) the event in the panel: ex-date price step, NAV step after expiration
    i = b.index[b.date == rec][0]
    prev = b.loc[b.index[b.index.get_loc(i) - 1]]
    res["close_pre"], res["close_ex"] = float(prev.close), float(b.loc[i, "close"])
    res["nav_pre"], res["nav_ex"] = float(prev.nav), float(b.loc[i, "nav"])
    res["disc_pre_pp"], res["disc_ex_pp"] = float(prev.disc), float(b.loc[i, "disc"])
    after = b[b.date > exp_].iloc[0]
    at = b[b.date == exp_].iloc[0]
    res["nav_step_date"] = after.date.date()
    res["nav_step_pct"] = float(100 * (after.nav / at.nav - 1))
    res["disc_at_expiration_pp"], res["disc_after_step_pp"] = float(at.disc), float(after.disc)
    # 4) bias of the raw discount over [record date, expiration]: the dilution not yet in the NAV.
    #    A discount on the post-dilution basis divides the NAV by (1 + step); the bias is raw - that.
    f = after.nav / at.nav
    win = b[(b.date >= rec) & (b.date <= exp_)].copy()
    win["disc_diluted"] = 100 * (win.close / (win.nav * f) - 1)
    win["bias_pp"] = win["disc"] - win["disc_diluted"]
    res["rights_window_sessions"] = len(win)
    res["rights_window_bias_pp_median"] = float(win["bias_pp"].median())
    sdw = p["sd"]["BIT"].reindex(win.date)
    res["rights_window_bias_z_median"] = float(np.median(win["bias_pp"].values / sdw.values))
    res["rights_window_bit_sd_pp_median"] = float(np.median(sdw.values))
    # 5) when the rights-window rows leave the z window (rolling Z_WINDOW, shift(1))
    idx = p["px"].index
    last_pos = idx.get_loc(win.date.max())
    res["window_rows_in_z_until"] = idx[last_pos + Z_WINDOW].date() if last_pos + Z_WINDOW < len(idx) else None
    res["z_window"] = Z_WINDOW
    return res


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="re-fetch every network source")
    ap.add_argument("--state-dir", type=Path, required=True,
                    help="laptop prod state for the cef book (plans, collector reports), read-only")
    ap.add_argument("--traded-panel-dir", type=Path, required=True,
                    help="the data/cef the laptop prod clone traded on (cef_prices/cef_nav.parquet), read-only")
    args = ap.parse_args(argv)
    pd.set_option("compute.use_numexpr", False)        # scripts/events/numexpr_fault.py
    pd.set_option("display.width", 250)
    from scripts.cef.spec import MIN_NAMES, UNIVERSE, Z_WINDOW, summary
    U = sorted(UNIVERSE)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"spec {summary()}; z_window {Z_WINDOW}; min_names {MIN_NAMES}")

    P, N = load_live(U)
    print(f"dev-checkout panels data/cef (read-only; not the traded panel): prices last {P.date.max().date()}, "
          f"NAV last {N.date.max().date()}")
    TP, TN, tmt = load_traded(args.traded_panel_dir, U)
    print(f"traded panels {args.traded_panel_dir} (read-only): prices last {TP.date.max().date()}, "
          f"NAV last {TN.date.max().date()}; written {tmt}")
    cc, cclog = fetch_cefconnect(U, args.refresh)
    print(f"CEFConnect: {len(cc):,} rows; 1Y {cc[cc.window=='1Y'].date.min().date()}..{cc[cc.window=='1Y'].date.max().date()}, "
          f"All {cc[cc.window=='All'].date.min().date()}..{cc[cc.window=='All'].date.max().date()}; "
          f"fetched {cclog.fetched_at_utc.min()} .. {cclog.fetched_at_utc.max()}")
    a = cc[cc.window == "1Y"].merge(cc[cc.window == "All"], on=["ticker", "date"], suffixes=("_1y", "_all"))
    print(f"CEFConnect 1Y vs All on {len(a)} common rows: NAV differ {int(((a.nav_cc_1y-a.nav_cc_all).abs()>TOL_USD).sum())}, "
          f"close differ {int(((a.close_cc_1y-a.close_cc_all).abs()>TOL_USD).sum())}")
    px_now, nav_now, act_now, yf_at = fetch_yf_now(U, args.refresh)
    print(f"yfinance now (fetched {yf_at}): prices last {px_now.date.max().date()}, NAV last {nav_now.date.max().date()}")
    print("yfinance splits now:", act_now[act_now.stock_splits != 0][["ticker", "date", "stock_splits"]].to_dict("records"))
    # Tables are stamped with the UTC date of the latest network fetch they rest on, so a
    # re-run from the cache rewrites the same files (module docstring, 2026-10-13).
    day = max(pd.Timestamp(yf_at).date(), *(pd.Timestamp(x).date() for x in cclog.fetched_at_utc)).isoformat()
    print(f"output tables stamped {day} (latest network fetch); run {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%MZ}")

    # ---- 0. the panel against yfinance as served now
    q = N.merge(nav_now.rename(columns={"nav": "nav_now"}), on=["ticker", "date"], how="inner")
    qd = q[(q.nav - q.nav_now).abs() > TOL_USD]
    r = P.merge(px_now[["ticker", "date", "close"]].rename(columns={"close": "close_now"}), on=["ticker", "date"])
    print(f"\n[0] panel vs yfinance-now: NAV {len(q):,} common rows, {len(qd)} differ; "
          f"close {len(r):,} common rows, {int(((r.close-r.close_now).abs()>TOL_USD).sum())} differ")
    print(qd[["ticker", "date", "nav", "nav_now"]].to_string(index=False))
    # A bar captured empty (NaN close) is invisible to the comparisons above (NaN never
    # compares); the sleeve's `close > 0.5` filter drops the name that day. Count them.
    nc = P[P.close.isna()].merge(px_now[["ticker", "date", "close"]].rename(columns={"close": "close_now"}),
                                 on=["ticker", "date"], how="left")
    print(f"    panel price rows with NaN close: {len(nc)}; yfinance-now has a close for "
          f"{int(nc.close_now.notna().sum())} of them: " + ", ".join(f"{r.ticker} {r.date.date()}" for r in nc.itertuples()))
    print(f"    panel NAV rows with NaN NAV: {int(N.nav.isna().sum())}")

    # ---- 0b. the TRADED panel: against the dev checkout and yfinance-now; the last decision read directly
    print(f"\n[0b] traded panel ({args.traded_panel_dir}) against the dev checkout's and yfinance-now:")
    for lab, (fp, fn) in (("dev checkout", (P, N)), ("yfinance-now", (px_now, nav_now))):
        qn = TN.merge(fn[["ticker", "date", "nav"]].rename(columns={"nav": "nav_other"}), on=["ticker", "date"])
        dn = qn[(qn.nav - qn.nav_other).abs() > TOL_USD]
        qp = TP.merge(fp[["ticker", "date", "close"]].rename(columns={"close": "close_other"}), on=["ticker", "date"])
        print(f"    vs {lab}: NAV {len(qn):,} common rows, {len(dn)} differ "
              f"({', '.join(f'{r.ticker} {r.date.date()} {r.nav:.2f}/{r.nav_other:.2f}' for r in dn.itertuples())}); "
              f"close {len(qp):,} common rows, {int(((qp.close - qp.close_other).abs() > TOL_USD).sum())} differ")
    tnc = TP[TP.close.isna()]
    print(f"    traded price rows with NaN close (the sleeve drops these name-days): {len(tnc)}: "
          + ", ".join(f"{r.ticker} {r.date.date()}" for r in tnc.itertuples()))
    print(f"    of which also NaN in the dev checkout: "
          f"{len(tnc.merge(P[P.close.isna()][['ticker', 'date']], on=['ticker', 'date']))}")
    tl = TN.date.max()
    tr = TN.sort_values(["ticker", "date"]).copy()
    tr["prev"] = tr.groupby("ticker")["nav"].shift(1)
    last = tr[tr.date == tl].merge(nav_now.rename(columns={"nav": "nav_final"}), on=["ticker", "date"], how="left") \
        .merge(cc[cc.window == "1Y"][["ticker", "date", "nav_cc"]], on=["ticker", "date"], how="left")
    print(f"    traded panel's last NAV date {tl.date()} (the decide-time capture of that asof), "
          f"NAV(D) = NAV(D-1) on: "
          + (", ".join(f"{r.ticker} {r.nav:.2f}/{r.prev:.2f} (final {r.nav_final:.2f}, CEFConnect {r.nav_cc:.2f})"
                       for r in last[(last.nav - last.prev).abs() < FLOAT_EPS].itertuples()) or "none"))
    print(f"    names whose decide-time NAV for {tl.date()} differs from the final one: "
          f"{sorted(last.loc[(last.nav - last.nav_final).abs() > TOL_USD, 'ticker'])}")

    # ---- 1. NAV: panel vs CEFConnect
    tabs, clsall = [], []
    for w in CC_WINDOWS:
        m = classify(N, "nav", cc[cc.window == w], "nav_cc")
        m["window"] = w
        clsall.append(m)
        tabs.append(by_name_year(m, f"nav_vs_cc_{w}"))
    cls = pd.concat(clsall, ignore_index=True)
    navtab = pd.concat(tabs, ignore_index=True)
    navtab.to_csv(OUT_DIR / f"nav_by_name_year_{day}.csv", index=False)
    cls[cls.category != "AGREE"].to_csv(_cache("nav_disagreements.csv"), index=False)
    print("\n[1] NAV vs CEFConnect, all names, by window and category:")
    print(cls.groupby(["window", "category"]).size().unstack(fill_value=0).to_string())
    wk = navtab[navtab.check == "nav_vs_cc_All"]
    print("\n[1a] weekly (All): STALE_COPY per name and year (compared rows in the last row):")
    t = wk.pivot_table(index="ticker", columns="year", values="STALE_COPY", aggfunc="sum").fillna(0).astype(int)
    t.loc["ALL 13"] = t.sum()
    t.loc["compared"] = wk.groupby("year")["compared"].sum()
    print(t.loc[:, t.columns >= 2013].to_string())
    # The weekly rows are Fridays. [1h] shows that the Friday sample is not representative of
    # other weekdays, so a share below is a share OF FRIDAYS, never a daily rate (2026-10-13).
    print("\n[1b] weekly (All): Friday counts by year, all 13 (stale / compared Fridays), and other categories:")
    y = wk.groupby("year")[["compared", "STALE_COPY", "stale_lagged", "SHIFT_PREV", "SHIFT_NEXT", "BASIS", "OTHER"]].sum()
    y["friday_share"] = (y.STALE_COPY / y.compared).round(4)
    print(y.to_string())
    print("\n[1c] weekly (All): share of Fridays stale, by name and year, 2018-2026 (not a daily rate, [1h]):")
    print(wk[wk.year >= 2018].pivot_table(index="ticker", columns="year", values="stale_share").round(3).to_string())
    dly = navtab[navtab.check == "nav_vs_cc_1Y"]
    print("\n[1d] daily (1Y): per name, compared and categories:")
    print(dly.groupby("ticker")[["compared", "AGREE", "STALE_COPY", "stale_lagged", "SHIFT_PREV", "SHIFT_NEXT",
                                 "BASIS", "OTHER"]].sum().to_string())
    print(cls[(cls.window == "1Y") & (cls.category != "AGREE")][["ticker", "date", "prev", "nav", "next", "nav_cc",
                                                                "category"]].to_string(index=False))
    rp = N.sort_values(["ticker", "date"]).copy()
    rp["repeat"] = rp.groupby("ticker")["nav"].diff() == 0
    rs = rp.groupby(rp.date.dt.year)["repeat"].mean()
    print("\n[1e] share of panel NAV rows that repeat the previous row (all 13), by year:")
    print(rs.loc[2013:].round(3).to_string())
    tb = tiebreak(cls[cls.window == "All"], N, "nav", "nav_cc")
    print(f"\n[1f] who is right on a weekly STALE_COPY: catch = next yfinance change, missed = cc - yf: {tb}")
    tb1 = tiebreak(cls[cls.window == "1Y"], N, "nav", "nav_cc")
    print(f"     daily: {tb1}")
    sw = cls[(cls.window == "All") & (cls.category == "STALE_COPY")].groupby("date").size()
    print("\n[1g] weekly stale copies come in vendor-wide episodes: per year, the Fridays with any, "
          "and the median / max number of the 13 stale on such a Friday:")
    print(sw.groupby(sw.index.year).agg(["size", "median", "max"]).rename(columns={"size": "fridays"}).to_string())

    # ---- 1h. is the Friday sample representative? The daily window answers it (review 2026-10-13).
    wd = lambda s: s.dt.day_name().str[:3]   # noqa: E731
    print("\n[1h] weekday of the weekly (All) CEFConnect rows compared:",
          wd(cls[cls.window == "All"].date).value_counts().to_dict())
    d1 = cls[(cls.window == "1Y") & (cls.category == "STALE_COPY")]
    print(f"     daily (1Y) STALE_COPY in the dev-checkout panel, {cls[cls.window == '1Y'].date.min().date()} .. "
          f"{cls[cls.window == '1Y'].date.max().date()}: {len(d1)} by weekday {wd(d1.date).value_counts().to_dict()}; "
          f"on Fridays: " + ", ".join(f"{r.ticker} {r.date.date()}" for r in d1[d1.date.dt.dayofweek == 4].itertuples()))
    cyn = classify(nav_now, "nav", cc[cc.window == "1Y"], "nav_cc")
    for lab, x in (("to the dev panel's last NAV date", cyn[cyn.date <= N.date.max()]), ("whole 1Y overlap", cyn)):
        s1 = x[x.category == "STALE_COPY"]
        print(f"     daily (1Y) STALE_COPY in yfinance-now, {lab} ({x.date.min().date()} .. {x.date.max().date()}, "
              f"{len(x):,} compared): {len(s1)} by weekday {wd(s1.date).value_counts().to_dict()}")
    print(f"     daily stale copies, dev panel, by date: {d1.groupby('date').size().rename(lambda d: str(d.date())).to_dict()}")

    # ---- 1i. a stale copy without a repeat: yfinance(D) == CEFConnect(D-1) != CEFConnect(D)
    print("\n[1i] daily (1Y): yfinance(D) moved off yfinance(D-1), equals CEFConnect(D-1) and differs from "
          "CEFConnect(D) -- D-1's NAV dated D with no repeat (a repeat-keyed gate misses these):")
    for lab, a_ in (("dev-checkout panel", N), ("traded panel", TN), ("yfinance-now", nav_now)):
        lu = lag_unrepeated(a_, "nav", cc[cc.window == "1Y"], "nav_cc")
        print(f"     {lab}: {len(lu)}" + (": " + ", ".join(
            f"{r.ticker} {r.date.date()} yf(D-1) {r.prev:.2f} yf(D) {r.nav:.2f} cc(D-1) {r.b_prev:.2f} cc(D) {r.nav_cc:.2f}"
            for r in lu.itertuples()) if len(lu) else ""))

    # ---- 1j. row-level evidence on basis: BASIS is a name-year MEDIAN ratio test, so cite the rows too
    print("\n[1j] row-level: NAV rows agreeing within half a cent, and what the rest are:")
    for w in CC_WINDOWS:
        x = cls[cls.window == w]
        oth = x[x.category == "OTHER"]["diff"].abs()
        print(f"     {w}: agree {int((x.category == 'AGREE').sum()):,} of {len(x):,}; stale {int((x.category == 'STALE_COPY').sum())}, "
              f"shift {int(x.category.isin(['SHIFT_PREV', 'SHIFT_NEXT']).sum())}, other {len(oth)} "
              f"(|diff| median {oth.median():.3f}, max {oth.max():.3f}); "
              f"OTHER rows from 2013: {int((oth.index.isin(x.index[x.year >= 2013])).sum())}, max |diff| "
              f"{x.loc[(x.category == 'OTHER') & (x.year >= 2013), 'diff'].abs().max():.3f}")
        # A share-basis difference is a CONSTANT ratio across a run of rows. Show the name-years
        # with the most non-stale disagreement and whether their differences carry a sign.
        nz = x[~x.category.isin(["AGREE", "STALE_COPY"])]
        g = nz.groupby(["ticker", "year"])["diff"].agg(rows="size", mean_diff="mean",
                                                       median_abs=lambda s: s.abs().median())
        g["share_of_rows"] = g["rows"] / x.groupby(["ticker", "year"]).size().reindex(g.index)
        print("       name-years with the largest share neither AGREE nor STALE_COPY:")
        print(g.sort_values("share_of_rows", ascending=False).head(3).round(3).to_string())
    print("     weekly SHIFT_NEXT by year (if CEFConnect dated NAVs a day early, every week the NAV moved "
          "would be SHIFT_NEXT):", y["SHIFT_NEXT"][y["SHIFT_NEXT"] > 0].to_dict(),
          f"; 2023 AGREE {int(y.loc[2023, 'compared'] - y.loc[2023, ['STALE_COPY', 'SHIFT_PREV', 'SHIFT_NEXT', 'BASIS', 'OTHER']].sum())} "
          f"of {int(y.loc[2023, 'compared'])}")

    # ---- 2. prices: panel vs CEFConnect close; vs CRSP raw prc
    ptabs = []
    for w in CC_WINDOWS:
        m = classify(P, "close", cc[cc.window == w], "close_cc")
        ptabs.append(by_name_year(m, f"close_vs_cc_{w}"))
        print(f"\n[2] close vs CEFConnect {w}:", m.groupby("category").size().to_dict())
        if (m.category != "AGREE").any():
            print(m[m.category != "AGREE"].groupby(["ticker", "year", "category"]).size().to_string())
    names, dsf = fetch_crsp(U, pd.Timestamp("1990-01-01"), args.refresh)
    from scripts.data.cef_crosscheck_crsp import map_permnos
    mp = map_permnos(P[P.date <= dsf.date.max()][["ticker", "date", "close"]], names)
    nm = mp[mp.map_status == "MAPPED"].merge(names[["permno", "shrcd"]].drop_duplicates("permno"), on="permno", how="left")
    if not nm.shrcd.isin([14, 44]).all():
        raise LiveNavQualityError("a mapped permno is not a closed-end fund share code (14/44)")
    j = nm.merge(dsf[["permno", "date", "prc"]], on=["permno", "date"], how="left")
    j["crsp_close"] = np.where(j.prc > 0, j.prc, np.nan)
    no_trade = j[j.prc.notna() & ~(j.prc > 0)]
    not_in = j[j.prc.isna()]
    m = classify(P[P.date <= dsf.date.max()], "close", j[j.crsp_close.notna()][["ticker", "date", "crsp_close"]],
                 "crsp_close")
    ptabs.append(by_name_year(m, "close_vs_crsp"))
    print(f"\n[2c] close vs CRSP raw prc to {dsf.date.max().date()}: mapped {len(nm):,} of {len(mp):,}; "
          f"CRSP no-trade days with a panel bar {len(no_trade)}; panel dates absent from CRSP {len(not_in)}")
    print("    ", m.groupby("category").size().to_dict())
    # CRSP is licensed and this repository is public: CRSP values stay in the cache. Until
    # 2026-10-13 this printed each disagreeing row's date beside |panel - CRSP|, which with
    # the public close gave CRSP's price up to sign. `crsp_disagreement_summary` prints no
    # date and no single row's magnitude.
    by_tyc, by_era = crsp_disagreement_summary(m)
    print("    disagreeing rows by ticker, year and category (counts only):")
    print(by_tyc.to_string())
    print("    by era (max |diff| withheld where fewer than 3 rows disagree):")
    print(by_era.to_string(index=False))
    m[m.category != "AGREE"].to_csv(_cache("price_vs_crsp_disagreements.csv"), index=False)
    print("    CRSP no-trade days with a panel bar:", [(r.ticker, str(r.date.date())) for r in no_trade.itertuples()])
    print("    per name-year median panel/CRSP ratio outside [0.998, 1.002]:",
          m.groupby(["ticker", "year"])["ratio"].median().pipe(lambda s: s[(s - 1).abs() > RATIO_TOL]).to_dict())
    pd.concat(ptabs, ignore_index=True).to_csv(OUT_DIR / f"price_by_name_year_{day}.csv", index=False)

    # ---- 3. BIT 2025-08-19
    facts = fetch_edgar_bit(args.refresh)
    p, elig, dec, H = deployed_book()
    be = bit_event(P, N, cc, px_now, dsf, names, facts, p)
    print("\n[3] BIT 2025-08-19 (EDGAR + panels):")
    for k, v in be.items():
        print(f"    {k}: {v}")
    pd.DataFrame([be]).to_csv(OUT_DIR / f"bit_event_{day}.csv", index=False)

    # ---- 4. footprint on the deployed book's decision dates
    long, fp0 = footprint(cls, p, elig, dec, H, N)
    eras = [("W4 fit window, deployed (first position .. 2022-12-30)", "2013-01-01", str(W4_FIT_END.date())),
            ("time-holdout years (2023-01-03 .. panel end)", str(TIME_HOLDOUT.date()), "2026-12-31"),
            ("all decision dates", "2013-01-01", "2026-12-31")] + \
           [(str(yr), f"{yr}-01-01", f"{yr}-12-31") for yr in range(2013, 2027)]
    fs = summarise_footprint(long, eras)
    fs.to_csv(OUT_DIR / f"footprint_{day}.csv", index=False)
    long.drop(columns=["nav", "nav_cc", "px"]).to_parquet(_cache("footprint_rows.parquet"))
    print(f"\n[4] deployed book: first position {fp0.first_position[0]}, decision dates {fp0.decision_dates[0]} "
          f"(of which before 2023: {int((long.drop_duplicates('date').date < TIME_HOLDOUT).sum())})")
    cols = ["era", "decision_dates", "checked_dates", "eligible_name_days_checked", "eligible_stale_name_days",
            "eligible_dates_with_stale", "held_stale_name_days", "held_dates_with_stale", "traded_stale_name_days",
            "traded_dates_with_stale", "eligible_any_defect_name_days", "eligible_dates_with_any_defect",
            "eligible_dates_with_repeat_unchecked", "held_dates_with_repeat_unchecked",
            "eligible_stale_abs_ddisc_pp_median", "eligible_stale_abs_ddisc_pp_p90", "eligible_stale_abs_ddisc_pp_max",
            "eligible_stale_abs_dz_median", "eligible_stale_abs_dz_p90", "eligible_stale_abs_dz_max"]
    print(fs[cols].to_string(index=False))
    sg = long[long.eligible & (long.category == "STALE_COPY")]
    print("\n    eligible STALE_COPY rows, signed d_disc (pp) by year: mean / median / n (is the error directional?)")
    print(sg.groupby(sg.date.dt.year)["d_disc_pp"].agg(["mean", "median", "size"]).round(3).to_string())
    w4 = long[long.date <= W4_FIT_END]
    print("\n    W4 fit window, eligible STALE_COPY name-days by year:",
          w4[w4.eligible & (w4.category == "STALE_COPY")].groupby(w4.date.dt.year).size().to_dict())

    # ---- 5. the live paper period
    plans = load_plans(args.state_dir, U)
    lp = live_period(plans, TP, TN, nav_now, px_now, cc)
    # quantities stay in the state dir; the tracked table says held / targeted / submitted
    lp["held_going_in"] = lp["current"].fillna(0) != 0
    lp["targeted"] = lp["target"].fillna(0) != 0
    lp.drop(columns=["reason", "current", "target"]).to_csv(OUT_DIR / f"live_period_{day}.csv", index=False)
    print(f"\n[5] live paper period, laptop plans (asof {plans['asof'].min().date()} .. {plans['asof'].max().date()}); "
          f"mu and sd from the TRADED panel:")
    lp["stale_at_decision"] = lp.verdict == V_STALE
    lp["checkable"] = lp.verdict != V_NONE
    per = lp.groupby(["asof", "session", "status", "decided_at_utc", "sent"]).agg(
        names_checkable=("checkable", "sum"), stale_at_decision=("stale_at_decision", "sum"),
        stale_and_submitted=("stale_at_decision", lambda v: int((v & lp.loc[v.index, "submitted"]).sum())),
        stale_and_held=("stale_at_decision", lambda v: int((v & lp.loc[v.index, "held_going_in"]).sum())),
        neither=("verdict", lambda v: int((v == V_NEITHER).sum())),
        orders_submitted=("session_orders_submitted", "first")).reset_index()
    print(per.to_string(index=False))
    per.to_csv(OUT_DIR / f"live_period_by_date_{day}.csv", index=False)
    print("    verdicts:", lp.verdict.value_counts().to_dict())
    show = lp[lp.verdict.isin([V_STALE, V_NEITHER, V_AMBIG])]
    print(show[["asof", "ticker", "z_plan", "z_final", "close_used", "close_source", "nav_used_lo", "nav_used_hi",
                "nav_prev_now", "nav_now", "nav_cc", "dist_final", "dist_prev", "one_cent_case", "held_going_in",
                "submitted", "verdict"]].round(4).to_string(index=False))
    st = lp[lp.stale_at_decision]
    print(f"    stale at decision: {len(st)} of {int(lp.checkable.sum())} checkable name-days on "
          f"{st['asof'].nunique()} of {lp['asof'].nunique()} decision dates; |z_plan - z_final| median "
          f"{st.dz_plan_minus_final.abs().median():.3f}, max {st.dz_plan_minus_final.abs().max():.3f}; "
          f"submitted to the broker {int(st.submitted.sum())}; held going in {int(st.held_going_in.sum())}; "
          f"one-cent cases {int(st.one_cent_case.sum())}")
    print(f"    the decided-at times of the stale plans (UTC): {sorted(st.decided_at_utc.unique())}")
    # The tolerance's margin on both sides, measured: the farthest candidate accepted, and the
    # nearest candidate rejected (on a row where the other candidate was accepted).
    ck = lp[lp.verdict.isin([V_STALE, V_FINAL, V_FINAL_EQ])].copy()
    ck["accepted"] = np.where(ck.verdict == V_STALE, ck.dist_prev, ck.dist_final)
    rj = ck[ck.verdict.isin([V_STALE, V_FINAL])].copy()
    rj["rejected"] = np.where(rj.verdict == V_STALE, rj.dist_final, rj.dist_prev)
    a_ = ck.loc[ck.accepted.idxmax()]
    r_ = rj.loc[rj.rejected.idxmin()]
    print(f"    tolerance {IMPLIED_TOL}: largest accepted distance {a_.accepted:.4f} ({a_.ticker} {a_['asof'].date()}); "
          f"nearest rejected candidate {r_.rejected:.4f} ({r_.ticker} {r_['asof'].date()}, {r_.verdict})")
    # Sensitivity: the 2026-10-12 method (mu and sd from yfinance-now, the empty bars filled).
    print(f"    sensitivity, mu and sd from yfinance-now instead (the 2026-10-12 method): verdicts "
          f"{lp.verdict_yfnow.value_counts().to_dict()}; implied interval moves by up to "
          f"{lp.interval_shift_vs_yfnow.max():.4f} ({lp.loc[lp.interval_shift_vs_yfnow.idxmax(), 'ticker']} "
          f"{lp.loc[lp.interval_shift_vs_yfnow.idxmax(), 'asof'].date()}); verdicts that differ: "
          + (", ".join(f"{r.ticker} {r.asof.date()} {r.verdict} -> {r.verdict_yfnow}"
                       for r in lp[lp.checkable & (lp.verdict != lp.verdict_yfnow)].itertuples()) or "none"))
    acc_y = np.where(lp.verdict_yfnow == V_STALE, lp.dist_prev_yfnow,
                     np.where(lp.verdict_yfnow.isin([V_FINAL, V_FINAL_EQ]), lp.dist_final_yfnow, np.nan))
    print(f"    (under that method the largest accepted distance was {np.nanmax(acc_y):.4f})")
    print(f"    INFERRED, not observed: on {int(len(st) + (lp.verdict == V_FINAL_EQ).sum())} of "
          f"{int(lp.checkable.sum())} checkable name-days the NAV the session used equalled yfinance's NAV(D-1) "
          f"({len(st)} stale copies + {int((lp.verdict == V_FINAL_EQ).sum())} genuinely flat). "
          f"Only the last asof's decide-time panel survives to be read directly ([0b], and below).")
    # The direct read: the traded panel's last date is that asof's decide-time capture.
    from scripts.cef.spec import Z_WINDOW as _ZW
    tdisc, tmu, tsd = sleeve_mu_sd(TP, TN, U, _ZW)
    tz = ((tdisc - tmu) / tsd).clip(-4, 4)
    la = lp[(lp["asof"] == TN.date.max()) & lp.z_plan.notna()].copy()
    la["z_traded"] = [round(float(tz.at[r.asof, r.ticker]), 2) for r in la.itertuples()]
    print(f"    asof {TN.date.max().date()}: z recomputed from the traded panel (its decide-time NAVs) equals the "
          f"printed z on {int((la.z_traded - la.z_plan).abs().lt(0.005).sum())} of {len(la)} names with a z: "
          + ", ".join(f"{r.ticker} {r.z_plan:+.2f}/{r.z_traded:+.2f}" for r in la.itertuples()))
    # Orders: every order of a session is sized from the whole cross-section (w = -(z - mean z),
    # normalised by sum |w|, the vol scalar, the min-weight re-neutralisation), so a stale NAV
    # in ANY eligible name moves every order of that session, not only its own (review 2026-10-13).
    ss = per[per.sent & (per.orders_submitted > 0)]
    hit = ss[ss.stale_at_decision > 0]
    print(f"    orders submitted, by sent session: {dict(zip(ss.session, ss.orders_submitted))}; "
          f"in a name whose own NAV was stale: {int(st.submitted.sum())}; "
          f"on the {len(hit)} sessions whose plan included a stale NAV: {int(hit.orders_submitted.sum())} "
          f"({', '.join(f'{r.session}: {r.orders_submitted}' for r in hit.itertuples())}); "
          f"sessions sent with no stale NAV identified: "
          f"{', '.join(f'{r.session} ({r.orders_submitted} orders, {r.names_checkable} of 13 checkable)' for r in ss[ss.stale_at_decision == 0].itertuples()) or 'none'}")
    col = load_collector(args.state_dir)
    print("\n    collector nav_crosscheck (laptop), per data day:")
    print(col.to_string(index=False))
    lv = long[long.date >= PAPER_START]
    print(f"    dev-checkout panel rows inside the live period: {lv.date.nunique()} decision date(s) "
          f"({', '.join(str(d.date()) for d in sorted(lv.date.unique()))})")
    print(f"\nwrote {OUT_DIR}/*_{day}.csv; row-level under {CACHE} (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
