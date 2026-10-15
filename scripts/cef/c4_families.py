"""Trial C4 (CEF trial 52): the live discount z-score pooled over five CEF families.

    export QUANTT_ENV_FILE=<absolute path to the env file>   # read-only Alpaca and R2; never printed
    python3 scripts/data/stage_crsp_cef_families.py --returns                  # DG-C4-1 (R2, read-only)
    python3 scripts/data/fetch_ff_factors.py && python3 scripts/data/fetch_pastor_liquidity.py   # DG-C4-3
    python3 scripts/data/fetch_alpaca_split_bars.py --c4-pool --start 2024-12-02 --end 2026-09-30
    python3 scripts/cef/c4_families.py stage0     # zero trials: gates, the 2026-10-14 rulings, quality screen
    python3 scripts/cef/c4_families.py fit        # Stage 0's diagnostics and Stages 1-6, fit window only
    python3 scripts/data/fetch_cefconnect_distributions.py --c4-universe --start 2024-12-01 --end 2026-10-14
    python3 scripts/cef/c4_families.py distributions   # the 2026-10-14 distribution ruling (amounts only)
    python3 scripts/cef/c4_families.py holdout    # Stages 8-9; refuses until the fit is reviewed and confirmed

The pre-registration is `results/cef/PREREG_C4_FAMILIES_2026-10-13.md` (approved
2026-10-14, CEF 50 -> 52, judged at N = 52), with the team lead's amendment of
2026-10-14 (the universe is the 74 funds of the 2026-10-14 re-read, frozen; GRX
and QQQX's Q1 days are outside eligibility and asserted not held; IGR's
2026-09-08/09 are filled from Alpaca's split-adjusted bars). The stages run in
the order of its §12. The write-up is `results/cef/C4_RESULT_2026-10-14.md`.

THE HARNESS. There is no backtester here. Targets come from
`band_frontier.build_targets(universe=, source=, mask=)` (DG-C4-2: the same code
the live book's baseline runs, pointed at the families panels), the policy is
`band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)` and every P&L is
`band_frontier.evaluate(H, R)`: decide t, fill at the close of t+1, earn t+2
(H1). Every parameter is read through `scripts/cef/spec.py`. The placebo's
fast path is checked against `evaluate()` to the last bit before it is used.

THE PRIMARY RETURN (PREREG §4.4). Through 2024-12-31: CRSP `dsf.ret` on the
row the price build tied to the fund (QQQX's predecessor permno by its own
rule). From 2025-01-02 (holdout only): r = (1 + r_px) k - 1 + D / P(t-1) on
the yfinance close with yfinance dividends and splits, IGR's two split days
from Alpaca. H15 on the P&L: a held weight that meets a name-day with no
return RAISES (`check_held`); the zeros that replace the remaining NaNs
multiply weights proved to be zero.

THE HOLDOUT. `build_targets` runs on the full families panel (to 2026-10-09);
its targets are causal (the row for t reads data through t only, H7), and the
fit stage truncates them at 2022-12-30 (`fit_slice`) BEFORE the band, the gross
cap and `evaluate()` are applied. No fit statistic reads a 2023+ row
(`_assert_fit`). Corrected 2026-10-15: until then this paragraph said every frame
was truncated before the policy ran, which is not what the code does; the
independent review of 3be92cd proved that no fit number changes either way.
The holdout stage refuses to run until the fit verdict is committed, the two
fit reviews have confirmed it, the distribution ruling clears (every disagreeing
ex-date confirmed) and the CRSP identity check passes on the holdout's CRSP leg.

LICENSED DATA. CRSP values never leave `results/cef/c4/_cache_c4/`; the
committed tables are portfolio aggregates and counts.

ALIGNMENT (H7). z's mean and sd, the history count and the ADV are `.shift(1)`
inside `build_panel`; the held book is `H.shift(2)` inside `evaluate`; the IC's
forward window is closes t+1 -> t+3 (`w4_artifacts.fwd(R, 2, 3)`); factor
regressors are aligned to the P&L row's own date (and t-1 for Dimson).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import inspect
import io
import json
import math
import pickle
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAM_DIR = REPO / "data" / "cef_families"
FAM_SRC = (FAM_DIR / "cef_prices.parquet", FAM_DIR / "cef_nav.parquet")
OUT_DIR = REPO / "results" / "cef" / "c4"
CACHE = OUT_DIR / "_cache_c4"
CRSP_RET = CACHE / "crsp_ret_families.parquet"
FACTOR_CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
ALP_POOL = CACHE / "alpaca_bars_c4pool_2024-12-02_2026-09-30.parquet"
ALP_POOL_META = CACHE / "alpaca_bars_c4pool_2024-12-02_2026-09-30_meta.json"
STAMP = "2026-10-14"
FROZEN = OUT_DIR / f"c4_universe_frozen_{STAMP}.csv"
FROZEN_READ_UTC = "2026-10-14T21:40:33Z"       # the read the team lead froze (amendment, 2026-10-14)
STAGE0_OUT = OUT_DIR / f"c4_stage0_output_{STAMP}.txt"
FIT_OUT = OUT_DIR / f"c4_fit_output_{STAMP}.txt"
FIT_JSON = OUT_DIR / f"c4_fit_verdict_{STAMP}.json"
FIT_TABLES = OUT_DIR / f"c4_fit_tables_{STAMP}.csv"

SAMPLE_START = pd.Timestamp("2005-01-03")
FIT_END = pd.Timestamp("2022-12-30")
HOLDOUT_START = pd.Timestamp("2023-01-01")
HOLDOUT_END = pd.Timestamp("2026-09-30")       # fixed by the team lead, 2026-10-14 (APPROVED block)
CRSP_END = pd.Timestamp("2024-12-31")
YF_START = pd.Timestamp("2025-01-02")
Q6_START = pd.Timestamp("2013-01-01")
SEAM = (pd.Timestamp("2024-12-31"), pd.Timestamp("2025-01-02"))
QQQX_PRED_PERMNO, QQQX_RULE_SHARE, QQQX_TOL = 91745, 0.95, 0.005    # §4.4
Q2_RUN, Q5_Z, Q5_ABS, Q5_WIN, Q6_BP = 3, 10.0, 0.15, 252, 5.0        # XASSET P2 as §4.5 cites it
DEPLOYED_FIRST = pd.Timestamp("2013-06-21")    # W4's first position (DG-C4-5 asserts the build reproduces it)
# The sha256 of pickle.dumps(build_targets()) -- FIRST call in a fresh process -- on the
# unmodified harness at 9d1d9ab, live panels of 2026-10-14 (cef_prices last 2026-09-28).
# A later edit of the live panel changes it; then the no-op must be re-proved, not assumed.
NOOP_SHA_PRE_EDIT = "007e221b574418095acae07c4ef7d1f650cc31c18ef05c3d4528d49867c37cdc"

FRESH = ("equity_domestic", "equity_sector", "equity_covered_call")    # the stale-NAV control (§8)
FAMILIES = ("equity_domestic", "equity_sector", "equity_covered_call", "preferred", "multi_asset")
# Declared in §8, not chosen here:
SEED = 20261013
NW_L, NW_L_W4 = 21, 5
BOOT_BLOCK, BOOT_BLOCK_2, BOOT_REPS = 21, 63, 10_000
PLACEBO_DRAWS, PLACEBO_BLOCK = 1000, 21
D1_T, D4_ALPHA_T, D4_BETA, CORR_KILL, DSR_PASS = 1.96, 3.0, 0.10, 0.5, 0.95
HY_START = pd.Timestamp("2007-04-12")
CORR_BLOCK = 21
FIT_ERAS = [("2005-09", "2005-01-01", "2009-12-31"), ("2010-14", "2010-01-01", "2014-12-31"),
            ("2015-19", "2015-01-01", "2019-12-31"), ("2020-22", "2020-01-01", "2022-12-31")]
FF6 = ["mktrf", "smb", "hml", "rmw", "cma", "umd"]

# The team lead's rulings of 2026-10-14 (PREREG amendment block), encoded:
RULED_NOT_HELD = {"GRX": ("2007-06-20", "2007-06-29"), "QQQX": ("2014-12-22", "2014-12-22")}
# ACV 2015-05-22 is the same case as GRX (CRSP's first row, a yfinance bar the session before)
# in the 105-fund pool only (robustness row R-S); it is treated, and asserted, the same way.
EXTENDED_NOT_HELD = {"ACV": ("2015-05-22", "2015-05-22")}
IGR_FILL = (pd.Timestamp("2026-09-08"), pd.Timestamp("2026-09-09"))
DIV_TOL = 0.001                                 # $/share: Yahoo rounds to 3dp (alpaca_daily.py docstring)
# The yfinance leg's distributions disagree with Alpaca's for some funds (Stage 0, 2026-10-14).
# The team lead's ruling of 2026-10-14 (PREREG amendment, second block): on each disagreeing
# ex-date use Alpaca's amount ONLY where a third source confirms it -- CEFConnect's distribution
# history for that fund and ex-date or, failing that, the ex-date NAV drop -- and HALT the
# holdout on any ex-date no third source confirms. The uncorrected yfinance version is
# reported beside it and never decides. Encoded in `confirm_distributions` / `holdout_actions`.
YF_LEG_DISTRIBUTION_RULING = "2026-10-14: Alpaca where a third source confirms; otherwise halt"
CC_DIST = CACHE / "cefconnect_distributions.parquet"
DIST_STAMP = "2026-10-15"
DIST_OUT = OUT_DIR / f"c4_distribution_confirmation_{DIST_STAMP}.txt"
DIST_TABLE = OUT_DIR / f"c4_distribution_confirmation_{DIST_STAMP}.csv"
# The NAV-drop test, fixed BEFORE any NAV-drop outcome was computed (2026-10-15): Alpaca's
# amount A is confirmed only if the ex-date NAV drop lies within NAV_K sigma of A AND more than
# NAV_K sigma from yfinance's amount Y -- a confirmation must tell the two sources apart.
# sigma is the fund's own sd of daily NAV changes ($) over the NAV_WIN sessions before the
# ex-date, excluding ex-dates (either source) and unchanged-NAV repeats; fewer than NAV_MIN_OBS
# usable changes, a missing NAV, or a repeated NAV on the ex-date leaves the test unusable.
NAV_K, NAV_WIN, NAV_MIN_OBS = 2.0, 63, 40
CC_ABSENCE_WINDOW_DAYS = 31        # CEFConnect can confirm "no distribution" only inside its own coverage
# The coordinator, 2026-10-15: the holdout opens only after two independent reviews of the fit
# (3be92cd) confirm it. CONFIRMED 2026-10-15 (team lead, PREREG amendment 3): the independent
# re-derivation reproduced every fit number exactly; the adversarial (beta-detector) review found
# the fit likely real as a gross price effect, with about a third of the P&L in the ex-date
# window [0,2].
FIT_REVIEWS_CONFIRMED = True
# Team lead, 2026-10-15 (PREREG amendment 3), ruling 1: the fund sponsor's own published
# distribution notices (press releases, Section 19(a) notices; EDGAR or the sponsor's site,
# fetched and cited with URLs) are ALSO a third source; a fund with any holdout ex-date still
# unconfirmed is EXCLUDED FROM THE HOLDOUT ENTIRELY, as a fund. This run's reading, fixed before
# any holdout return: a sponsor notice that CONTRADICTS Alpaca's amount or date leaves the row
# unconfirmed whatever the NAV drop says (ADX 2025-01-27: Adams states $0.47; Alpaca $0.63).
SPONSOR_VERIFIED = CACHE / "sponsor_notices_verified.parquet"
SPONSOR_CITATIONS = OUT_DIR / "c4_sponsor_notices_2026-10-15.csv"
EXCLUSIONS_JSON = OUT_DIR / "c4_holdout_exclusions_2026-10-15.json"
HOLDOUT_OUT = OUT_DIR / "c4_holdout_output_2026-10-15.txt"
HOLDOUT_JSON = OUT_DIR / "c4_holdout_verdict_2026-10-15.json"
EX_WINDOW = (0, 2)          # sessions from each ex-date: the beta-detector's [0,2] (amendment 3; report-only row)


class GateError(RuntimeError):
    """A gate could not clear, or a stage was asked to run out of order."""


def _need(p: Path, builder: str) -> Path:
    if not p.exists():
        raise FileNotFoundError(f"{p.relative_to(REPO)} is missing; build it with `{builder}`")
    return p


def _tracked_clean(*paths: Path) -> None:
    """Every path is committed and unmodified: a stage that needs an earlier commit refuses otherwise."""
    for p in paths:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(p)], cwd=REPO, capture_output=True)
        if r.returncode:
            raise GateError(f"{p.relative_to(REPO)} is not committed")
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(p)], cwd=REPO)
        if r.returncode:
            raise GateError(f"{p.relative_to(REPO)} differs from its committed version")


def cef_counter() -> int:
    """The CEF trial count, read from the canonical table (H14: read, never written here)."""
    txt = (REPO / "docs" / "RESEARCH_STATE.md").read_text()
    m = re.search(r"^\| \*\*CEF\*\* \|[^\n]*\| \*\*(\d+)\*\* \|", txt, re.M)
    if not m:
        raise GateError("docs/RESEARCH_STATE.md: no CEF counter row")
    return int(m.group(1))


# --------------------------------------------------------------------------- universe

def universes() -> dict:
    """The pool (105), the approved 68 (R-68), and the frozen 74 (the declared universe)."""
    from scripts.cef.c4_feasibility import NAMES_CSV, declare_pool
    names = pd.read_csv(_need(NAMES_CSV, "python3 scripts/data/cef_families_quality.py"))
    pool, left_out = declare_pool(names)
    fam = names.set_index("ticker")["family"]
    sub = names.set_index("ticker")["sub"]
    shortable = set(names.loc[names["alpaca_shortable"].astype(bool), "ticker"])   # c4_feasibility's rule
    snap = sorted(t for t in pool if t in shortable)
    fz = pd.read_csv(_need(FROZEN, "the 2026-10-14 amendment commit"))
    if set(fz["read_utc"]) != {FROZEN_READ_UTC}:
        raise GateError(f"{FROZEN.name}: read time {set(fz['read_utc'])}, not the frozen {FROZEN_READ_UTC}")
    if not (fz["tradable"].astype(bool) & fz["shortable"].astype(bool)).all() or not set(fz["ticker"]) <= set(pool):
        raise GateError(f"{FROZEN.name}: a fund that is not a shortable pool fund")
    return dict(names=names, fam=fam, sub=sub, pool=pool, left_out=left_out, snap68=snap,
                snap_read=str(names["alpaca_read_utc"].dropna().iloc[0]), frozen=sorted(fz["ticker"]), frozen_df=fz)


# --------------------------------------------------------------------------- panels and returns

def load_panels(pool):
    px = pd.read_parquet(_need(FAM_DIR / "cef_prices.parquet", "scripts/data/fetch_cef_families_yf.py"))
    nav = pd.read_parquet(_need(FAM_DIR / "cef_nav.parquet", "scripts/data/fetch_cef_families_yf.py"))
    px, nav = px[px["ticker"].isin(pool)].copy(), nav[nav["ticker"].isin(pool)].copy()
    for f in (px, nav):
        f["date"] = pd.to_datetime(f["date"])
    return px, nav


def crsp_returns(pool) -> pd.DataFrame:
    c = pd.read_parquet(_need(CRSP_RET, "python3 scripts/data/stage_crsp_cef_families.py --returns"))
    c["date"] = pd.to_datetime(c["date"])
    missing = sorted(set(pool) - set(c["ticker"]))
    if missing:
        raise GateError(f"DG-C4-1: pool funds with no staged CRSP returns: {missing}")
    if c["date"].max() != CRSP_END:
        raise GateError(f"DG-C4-1: CRSP cache ends {c['date'].max().date()}, not {CRSP_END.date()}")
    return c[c["ticker"].isin(pool)]


def qqqx_rule(crsp: pd.DataFrame, px: pd.DataFrame) -> dict:
    """§4.4: use QQQX's predecessor permno only if its raw price equals yfinance's close
    within $0.005 on at least 95% of common dates."""
    q = crsp[(crsp["ticker"] == "QQQX") & (crsp["permno"] == QQQX_PRED_PERMNO)]
    y = px[px["ticker"] == "QQQX"][["date", "close"]]
    j = q.merge(y, on="date", how="inner")
    tr = j[j["prc"] > 0]                                   # a closing trade: CRSP's raw print
    agree = int(((tr["close"] - tr["prc"]).abs() <= QQQX_TOL).sum())
    share = agree / len(tr) if len(tr) else float("nan")
    cur = crsp[(crsp["ticker"] == "QQQX") & (crsp["permno"] != QQQX_PRED_PERMNO)]["date"].min()
    return dict(pred_rows=len(q), common=len(tr), agree=agree, share=share,
                use_predecessor=bool(share >= QQQX_RULE_SHARE), current_first=cur,
                pred_last=q["date"].max())


IDENTITY_MIN_AGREE, IDENTITY_TOL, IDENTITY_TICK = 0.99, 0.001, 0.005
# 2026-10-15: >= 99% of days within 10bp (the review of 3be92cd); team lead, 2026-10-15 (amendment 3,
# ruling 2): a day agrees within max(10bp, $0.005 / price), for every fund, fit and holdout, so a
# half-cent CRSP print against a cent-rounded yfinance close on a sub-$5 fund is not a disagreement.
CEF_SHRCD = {14, 44}


def crsp_identity(c: pd.DataFrame, px: pd.DataFrame, cols, lo, hi, raise_on_fail: bool = True,
                  acts: pd.DataFrame | None = None) -> pd.DataFrame:
    """Is each fund's CRSP security the fund? Added 2026-10-15 after the independent review of
    C4's fit found BTX mapped to a biotech (share code 11) that matched 0 of 446 closes.

    Over [lo, hi], for every fund in `cols` with CRSP rows there:
      * every row's share code is a CEF's (14, 44);
      * the daily PRICE MOVE agrees: |yfinance close_t / close_t-1 - 1 - CRSP retx_t| <=
        max(10bp, $0.005 / CRSP print at t-1) on at least 99% of common days (CRSP closing prints
        on t and t-1). The reviewer's 10bp, widened by the team lead's ruling of 2026-10-15 to
        half a cent of price. It compares the price path, so a constant re-basing of yfinance's close (GLV's
        is 0.999 x CRSP's print through 2019) does not read as another security, and a wrong
        security (BTX's old map: 0 of 446) fails at once.
    Reported beside it, never deciding: the share of days the close LEVEL agrees within $0.005
    (raw, or after undoing yfinance's own later split factors). Raises naming every failing
    fund unless `raise_on_fail` is False. Returns the per-fund table."""
    from scripts.data.cef_families_quality import split_factor
    if acts is None:
        acts = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
    acts = acts.assign(date=pd.to_datetime(acts["date"]))
    w = c[(c["date"] >= lo) & (c["date"] <= hi) & c["ticker"].isin(cols)]
    yc = px[px["ticker"].isin(cols)].pivot_table(index="date", columns="ticker", values="close").sort_index()
    ry = yc.pct_change(fill_method=None)
    prc = c[c["ticker"].isin(cols)].pivot(index="date", columns="ticker", values="prc")
    rx = c[c["ticker"].isin(cols)].pivot(index="date", columns="ticker", values="retx")
    rows = []
    for t in sorted(set(w["ticker"])):
        d = pd.concat([ry[t].rename("y"), rx[t].rename("x"), prc[t].rename("p"), prc[t].shift(1).rename("pp"),
                       yc[t].rename("c")], axis=1).loc[lo:hi]
        rr = d[d["y"].notna() & d["x"].notna() & (d["p"] > 0) & (d["pp"] > 0)]
        lv = d[d["c"].notna() & (d["p"] > 0)].reset_index().rename(columns={"index": "date"})
        lv["ticker"] = t
        F = split_factor(lv[["ticker", "date"]], acts).to_numpy()
        lok = ((lv["c"] - lv["p"]).abs() <= 0.005) | ((lv["c"] - lv["p"] / F).abs() <= 0.005 / np.minimum(1.0, F))
        sc = w.loc[w["ticker"] == t, "shrcd"]
        tol = np.maximum(IDENTITY_TOL, IDENTITY_TICK / rr["pp"])
        rows.append(dict(ticker=t, move_days=len(rr), move_share=float(((rr["y"] - rr["x"]).abs() <= tol).mean())
                         if len(rr) else np.nan, level_days=len(lv), level_share=float(lok.mean()) if len(lv) else np.nan,
                         shrcd=" ".join(str(int(v)) for v in sorted(set(sc.dropna()))) + (" missing" if sc.isna().any() else "")))
    tab = pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame(
        columns=["move_days", "move_share", "level_days", "level_share", "shrcd"])
    bad_sc = [t for t, v in tab["shrcd"].items() if not set(v.split()) <= {str(x) for x in CEF_SHRCD}]
    bad_mv = [t for t, v in tab["move_share"].items() if not (v >= IDENTITY_MIN_AGREE)]
    tab["identity"] = ["FAIL" if (t in bad_sc or t in bad_mv) else "ok" for t in tab.index]
    if (bad_sc or bad_mv) and raise_on_fail:
        raise GateError(f"CRSP identity check {pd.Timestamp(lo).date()}..{pd.Timestamp(hi).date()}: share code not a "
                        f"CEF's {bad_sc}; daily price move within max(10bp, $0.005/price) on < "
                        f"{IDENTITY_MIN_AGREE:.0%} of days {[(t, round(tab.loc[t, 'move_share'], 4)) for t in bad_mv]}")
    return tab


def crsp_pivot(crsp, cols, index, qr, col="ret", px=None, check_identity=True) -> pd.DataFrame:
    """CRSP `ret` (or `retx`) as a date x fund frame on `index`; NaN where CRSP has none.

    Two checks before the frame is returned (2026-10-15): the identity of every fund's
    security over the index's CRSP span (`crsp_identity`, which needs the yfinance `px`), and
    the calendar -- every CRSP trading day of the pool in that span must be a session of
    `index` and every session a CRSP trading day, so `reindex` can never drop a return
    silently."""
    c = crsp if qr["use_predecessor"] else crsp[~((crsp["ticker"] == "QQQX") & (crsp["permno"] == QQQX_PRED_PERMNO))]
    c = c[c["ticker"].isin(cols)]
    if c.duplicated(["ticker", "date"]).any():
        raise GateError("two CRSP rows for one (fund, date)")
    lo, hi = index[0], min(index[-1], CRSP_END)
    if check_identity:
        if px is None:
            raise GateError("crsp_pivot needs the yfinance prices for its identity check")
        crsp_identity(c, px, cols, lo, hi)
    cal = pd.DatetimeIndex(sorted(crsp.loc[(crsp["date"] >= lo) & (crsp["date"] <= hi), "date"].unique()))
    sess = index[(index >= lo) & (index <= hi)]
    if len(cal.difference(sess)) or len(sess.difference(cal)):
        raise GateError(f"CRSP calendar and harness sessions differ on {lo.date()}..{hi.date()}: CRSP-only "
                        f"{[str(d.date()) for d in cal.difference(sess)[:5]]}, session-only "
                        f"{[str(d.date()) for d in sess.difference(cal)[:5]]}")
    return c.pivot(index="date", columns="ticker", values=col).reindex(index=index, columns=list(cols))


def yf_total_returns(px, cols, index) -> pd.DataFrame:
    """The declared yfinance-leg formula on every session of `index` (no outlier filter, no fill)."""
    from scripts.cef.band_frontier import total_returns
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    rpx = close.pct_change(fill_method=None).reindex(index=index, columns=list(cols))
    return total_returns(rpx, actions=FAM_DIR / "cef_actions.parquet", prices=FAM_DIR / "cef_prices.parquet")


def primary_returns(pool, px, crsp, qr) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """(primary return as declared, the yfinance-built total return, sessions) for the screen."""
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    sess = close.index[(close.index >= SAMPLE_START) & (close.index <= HOLDOUT_END)]
    cr = crsp_pivot(crsp, pool, sess, qr, px=px, check_identity=False)   # stage0 runs the check per window
    yf_tr = yf_total_returns(px, pool, sess)
    prim = pd.concat([cr.loc[:CRSP_END], yf_tr.loc[YF_START:]])
    if not prim.index.equals(sess):
        raise GateError("the CRSP and yfinance legs do not tile the session index at the seam")
    return prim, yf_tr, sess


# --------------------------------------------------------------------------- Alpaca second source

def alpaca_pool() -> dict:
    """The cached Alpaca bars (raw and split-adjusted) and corporate actions for the pool."""
    b = pd.read_parquet(_need(ALP_POOL, "python3 scripts/data/fetch_alpaca_split_bars.py --c4-pool "
                                        "--start 2024-12-02 --end 2026-09-30"))
    b["date"] = pd.to_datetime(b["date"])
    meta = json.loads(ALP_POOL_META.read_text())
    divs, splits = [], []
    for page in meta["corporate_actions"]:
        for typ, items in page.items():
            for x in items or []:
                if typ in ("cash_dividends", "capital_gains_distributions"):
                    divs.append((x["symbol"], pd.Timestamp(x["ex_date"]), float(x["rate"]), typ))
                else:
                    splits.append((typ, x.get("symbol"), x.get("ex_date") or x.get("effective_date"),
                                   x.get("old_rate"), x.get("new_rate")))
    d = pd.DataFrame(divs, columns=["ticker", "date", "rate", "type"])
    if d.duplicated(["ticker", "date", "rate", "type"]).any():
        raise GateError("Alpaca: identical distribution records (would double-count)")
    return dict(bars=b, divs=d.groupby(["ticker", "date"])["rate"].sum(), splits=splits,
                fetched=meta["fetched_utc"], sessions=[pd.Timestamp(s) for s in meta["sessions"]])


def igr_fill(alp: dict, px: pd.DataFrame, sess: pd.DatetimeIndex) -> tuple[dict, dict]:
    """The ruling's fill for IGR on 2026-09-08 and 09-09, from Alpaca's split-adjusted closes,
    and the cross-check of Alpaca's adjacent bars against the panel. Raises if a needed bar
    is missing (the ruling: the holdout then halts)."""
    b = alp["bars"]
    s = b[(b["ticker"] == "IGR") & (b["adjustment"] == "split")].set_index("date")["close"]
    prev = sess[sess < IGR_FILL[0]][-1]
    need = [prev, *IGR_FILL]
    miss = [str(d.date()) for d in need if d not in s.index]
    if miss:
        raise GateError(f"holdout halt (ruling 2026-10-14): Alpaca has no split-adjusted IGR bar for {miss}")
    sp = [x for x in alp["splits"] if x[1] == "IGR"]
    if [(x[0], x[2], x[3], x[4]) for x in sp] != [("reverse_splits", "2026-09-08", 3, 1)]:
        raise GateError(f"Alpaca's IGR split record is not the one the fill assumes: {sp}")
    acts = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
    acts["date"] = pd.to_datetime(acts["date"])
    on = acts[(acts["ticker"] == "IGR") & acts["date"].isin(IGR_FILL) & (acts["dividends"] > 0)]
    if len(on) or any((("IGR", d) in alp["divs"].index) for d in IGR_FILL):
        raise GateError("a distribution falls on an IGR fill date; the fill as ruled does not cover it")
    fill = {IGR_FILL[0]: s[IGR_FILL[0]] / s[prev] - 1.0, IGR_FILL[1]: s[IGR_FILL[1]] / s[IGR_FILL[0]] - 1.0}
    y = px[px["ticker"] == "IGR"].set_index("date")["close"]
    adj = s.index[(s.index >= pd.Timestamp("2026-08-17")) & (s.index <= HOLDOUT_END) & (s.index != IGR_FILL[0])]
    basis = pd.Series(np.where(adj < IGR_FILL[0], 3.0, 1.0), index=adj)
    diff = (s.reindex(adj) - y.reindex(adj) * basis).abs()
    ra, ry = (s.reindex(adj)).pct_change(), (y.reindex(adj) * basis).pct_change()
    chk = dict(sessions=len(adj), within_half_cent=int((diff <= 0.005).sum()), max_abs_diff=float(diff.max()),
               max_return_diff_bp=float(((ra - ry).abs() * 1e4).max()), prev=prev,
               closes={str(d.date()): float(s[d]) for d in need}, raw_0908=float(
                   b[(b["ticker"] == "IGR") & (b["adjustment"] == "raw") & (b["date"] == IGR_FILL[0])]["close"].iloc[0]))
    return fill, chk


def yf_leg_crosscheck(cols, px, alp) -> tuple[pd.DataFrame, dict]:
    """The yfinance leg (2025-01-02 -> 2026-09-30) against Alpaca: distributions by ex-date and
    raw closes. Reported; never averaged; the holdout gate reads it."""
    acts = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
    acts["date"] = pd.to_datetime(acts["date"])
    yd = acts[(acts["dividends"] > 0) & acts["ticker"].isin(cols)].set_index(["ticker", "date"])["dividends"]
    m = pd.concat([yd.rename("yfinance"), alp["divs"].rename("alpaca")], axis=1)
    d = m.index.get_level_values(1)
    m = m[(d >= YF_START) & (d <= HOLDOUT_END) & m.index.get_level_values(0).isin(cols)]
    bad = m[m["yfinance"].isna() | m["alpaca"].isna() | ((m["yfinance"] - m["alpaca"]).abs() > DIV_TOL)].reset_index()
    bad.columns = ["ticker", "date", "yfinance", "alpaca"]
    bad["ratio"] = bad["yfinance"] / bad["alpaca"]
    b = alp["bars"]
    ac = b[b["adjustment"] == "raw"].pivot(index="date", columns="ticker", values="close")
    yc = px.pivot_table(index="date", columns="ticker", values="close")
    idx = yc.index[(yc.index >= YF_START) & (yc.index <= HOLDOUT_END)]
    ac, yc = ac.reindex(index=idx, columns=list(cols)), yc.reindex(index=idx, columns=list(cols))
    both = ac.notna() & yc.notna()
    cd = (ac - yc).abs().where(both)
    closes = dict(compared=int(both.sum().sum()), within_half_cent=int((cd <= 0.005).sum().sum()),
                  yf_only=int((yc.notna() & ac.isna()).sum().sum()),
                  alpaca_only=int((yc.isna() & ac.notna()).sum().sum()),
                  dividend_rows=len(m), dividend_rows_disagreeing=len(bad))
    return bad, closes


# --------------------------------------------------------------------------- quality screen

def _runs(eq: pd.Series, min_len: int) -> list[tuple]:
    """(first, last, length) of runs of True of at least `min_len` sessions."""
    out, start, n = [], None, 0
    prev = None
    for d, v in eq.items():
        if v:
            start, n = (d if n == 0 else start), n + 1
        else:
            if n >= min_len:
                out.append((start, prev, n))
            n = 0
        prev = d
    if n >= min_len:
        out.append((start, prev, n))
    return out


def quality_screen(pool, px, nav, crsp, prim, yf_tr, sess, elig, qr) -> pd.DataFrame:
    """Q1-Q7 by fund and date, on the primary return AS DECLARED (before any ruling's fill).
    One row per flag; CRSP values in `crsp_value` (cache only), the rest committable."""
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    yvol = px.pivot_table(index="date", columns="ticker", values="volume").sort_index()
    cpr = crsp.pivot_table(index="date", columns="ticker", values="prc")
    cvol = crsp.pivot_table(index="date", columns="ticker", values="vol")
    rows = []
    for t in pool:
        s = close[t].dropna()
        first, last = s.index.min(), s.index.max()
        w = sess[(sess > first) & (sess <= last)]          # the first price has no return by construction
        r = prim[t].reindex(w)
        for d in r.index[r.isna()]:                        # Q1: no primary return inside the price span
            src = "CRSP" if d <= CRSP_END else "yfinance"
            why = ("no yfinance close" if pd.isna(close[t].get(d)) else
                   ("no CRSP row" if d <= CRSP_END and pd.isna(cpr.get(t, pd.Series(dtype=float)).get(d))
                    else "return undefined"))
            rows.append(dict(check="Q1", ticker=t, date=d, source=src, detail=why))
        rc = pd.concat([cpr.get(t, pd.Series(dtype=float)).reindex(w[w <= CRSP_END]).where(lambda x: x > 0),
                        close[t].reindex(w[w > CRSP_END])])
        eq = rc.eq(rc.shift(1)) & rc.notna()
        for a, b, n in _runs(eq, Q2_RUN - 1):              # Q2: n equalities = n + 1 sessions at one close
            a0 = rc.index[rc.index.get_loc(a) - 1]
            rows.append(dict(check="Q2", ticker=t, date=a0, date_end=b, source="CRSP" if b <= CRSP_END else "yfinance",
                             detail=f"close unchanged for {n + 1} sessions"))
        v = pd.concat([cvol.get(t, pd.Series(dtype=float)).reindex(w[w <= CRSP_END]),
                       yvol[t].reindex(w[w > CRSP_END])])
        for d in v.index[v.eq(0)]:                         # Q3
            rows.append(dict(check="Q3", ticker=t, date=d, source="CRSP" if d <= CRSP_END else "yfinance",
                             detail="zero volume"))
        yz = yvol[t].reindex(w)
        for d in yz.index[yz.eq(0)]:
            rows.append(dict(check="Q3", ticker=t, date=d, source="yfinance", detail="zero volume (yfinance bar; M2)"))
        if t in elig.columns:                              # Q4
            p4 = cpr.get(t, pd.Series(dtype=float)).reindex(w[w <= CRSP_END])
            e4 = elig[t].reindex(p4.index).fillna(False).astype(bool)
            for d in p4.index[(p4 < 0) & e4]:
                rows.append(dict(check="Q4", ticker=t, date=d, source="CRSP", detail="no closing trade on an eligible fund-day"))
        # Q5: the full 252 sessions through t-1, as P2 states it; |r| > 15% screens a fund's first year
        med = r.rolling(Q5_WIN, min_periods=Q5_WIN).median().shift(1)
        mad = (r - med).abs().rolling(Q5_WIN, min_periods=Q5_WIN).median().shift(1)
        z = (r - med).abs() / (1.4826 * mad.replace(0, np.nan))
        for d in r.index[(z > Q5_Z) | (r.abs() > Q5_ABS)]:
            rows.append(dict(check="Q5", ticker=t, date=d, source="CRSP" if d <= CRSP_END else "yfinance",
                             detail=f"|r|>{Q5_ABS:.0%}" if abs(r[d]) > Q5_ABS else f"robust z>{Q5_Z:g}",
                             value=float(r[d]) if d > CRSP_END else np.nan,
                             crsp_value=float(r[d]) if d <= CRSP_END else np.nan))
        c6 = prim[t].reindex(w[(w >= Q6_START) & (w <= CRSP_END)])   # Q6
        y6 = yf_tr[t].reindex(c6.index)
        d6 = (y6 - c6).abs() * 1e4
        for d in d6.index[d6 > Q6_BP]:
            rows.append(dict(check="Q6", ticker=t, date=d, source="CRSP vs yfinance",
                             detail=f"|diff| {d6[d]:.1f}bp", value=float(y6[d]), crsp_value=float(c6[d])))
        both_nan = c6.notna() & y6.isna()
        for d in both_nan.index[both_nan]:
            rows.append(dict(check="Q6", ticker=t, date=d, source="CRSP vs yfinance",
                             detail="yfinance-built return missing", crsp_value=float(c6[d])))
        for d in SEAM:                                     # Q7
            if d in w:
                rows.append(dict(check="Q7", ticker=t, date=d, source="CRSP" if d <= CRSP_END else "yfinance",
                                 detail="CRSP/yfinance seam",
                                 value=float(prim[t].get(d)) if d > CRSP_END else np.nan,
                                 crsp_value=float(prim[t].get(d)) if d <= CRSP_END else np.nan))
    f = pd.DataFrame(rows)
    for c in ("date_end", "value", "crsp_value"):
        if c not in f.columns:
            f[c] = np.nan
    return f


def ruling_of(row) -> str:
    """How the 2026-10-14 ruling treats a Q1 row ('' = not covered)."""
    for book, rule in ((RULED_NOT_HELD, "ruled 2026-10-14: outside eligibility; asserted not held"),
                       (EXTENDED_NOT_HELD, "same case as GRX, R-S only: asserted not held")):
        if row.ticker in book:
            a, b = (pd.Timestamp(x) for x in book[row.ticker])
            if a <= row.date <= b:
                return rule
    if row.ticker == "IGR" and row.date in IGR_FILL:
        return "ruled 2026-10-14: filled from Alpaca split-adjusted bars"
    return ""


# --------------------------------------------------------------------------- the deployed book (DG-C4-5)

def book_series() -> dict:
    """The deployed v7 series and the WIDE series, as `scripts/xasset/book_profile.py` builds them:
    live panel, band to the edge, gross-capped, daily gross TOTAL-return P&L."""
    from scripts.cef.band_frontier import band_gross_capped, build_targets, evaluate, total_returns
    from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS
    if MAX_GROSS_STRESS is None:
        raise GateError("DG-C4-5: the spec has no max_gross_stress; the deployed book is gross-capped")
    out = {}
    for lab, mn in (("deployed", None), ("WIDE", 0.0)):
        T, R = build_targets(min_adv=mn)
        H = band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)
        pnl = evaluate(H, total_returns(R))["pnl"]
        first = H.abs().sum(axis=1).gt(0).idxmax()
        out[lab] = dict(first=first, span=(pnl.index.min(), pnl.index.max()), n=len(pnl), pnl=pnl)
    return out


# --------------------------------------------------------------------------- stage 0

def noop_hashes() -> tuple[str, str]:
    """sha256 of pickle.dumps(build_targets()) on this tree's harness and on the harness at 9d1d9ab
    (git show), each the first call in a fresh process, both on the live panel as it is now."""
    old = CACHE / "band_frontier_9d1d9ab.py"
    CACHE.mkdir(parents=True, exist_ok=True)
    old.write_text(subprocess.run(["git", "show", "9d1d9ab:scripts/cef/band_frontier.py"], cwd=REPO,
                                  capture_output=True, text=True, check=True).stdout)
    new_code = ("import sys,pickle,hashlib; sys.path.insert(0,'.'); from scripts.cef.band_frontier import "
                "build_targets; print(hashlib.sha256(pickle.dumps(build_targets())).hexdigest())")
    old_code = ("import sys,pickle,hashlib; sys.path.insert(0,'.'); g={'__name__':'bf_old','__file__':"
                f"'{REPO / 'scripts/cef/band_frontier.py'}'}}; exec(compile(open('{old}').read(),g['__file__'],'exec'),g); "
                "print(hashlib.sha256(pickle.dumps(g['build_targets']())).hexdigest())")
    run = lambda c: subprocess.run([sys.executable, "-c", c], cwd=REPO, capture_output=True, text=True,  # noqa: E731
                                   check=True).stdout.strip().splitlines()[-1]
    return run(new_code), run(old_code)


def stage0() -> int:
    from scripts.cef import band_frontier as bf
    from scripts.cef.c4_feasibility import (FRESH_NAV_FAMILIES, eligibility, era_rows, first_active,
                                            repeat_mask)
    from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES, Z_WINDOW, summary
    fit_halts, ho_halts, notes = [], [], []

    # DG-C4-2: the no-op, RE-PROVED on today's live panel (2026-10-15: the panel was refreshed at
    # 16:24 and the stored pre-edit hash went stale). Each hash is the first call in a fresh process,
    # one on this tree's harness and one on the unmodified harness at 9d1d9ab, on the same data.
    h, h_old = noop_hashes()
    sig = {f: list(inspect.signature(getattr(bf, f)).parameters)
           for f in ("build_panel", "build_targets", "total_returns")}
    print(summary())
    print(f"C4 STAGE 0 (zero trials), run {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC; "
          f"holdout end fixed at {HOLDOUT_END.date()}; the team lead's rulings of 2026-10-14 encoded")
    print("\n[DG-C4-2] harness arguments:", sig)
    print(f"  sha256(pickle.dumps(build_targets())), first call, fresh process, today's live panel: this tree {h}")
    print(f"                                                                    unmodified harness (9d1d9ab) {h_old}")
    print(f"  (the hash recorded on 2026-10-14 on that day's panel: {NOOP_SHA_PRE_EDIT})")
    if h != h_old:
        fit_halts.append("DG-C4-2: the extended harness's default path differs from the unmodified harness's")
    print("  ->", "PASS (byte-for-byte no-op on the default path)" if h == h_old else "FAIL")

    # DG-C4-4: the frozen universe (ruling 1); no re-read
    U = universes()
    pool, fam, UF = U["pool"], U["fam"], U["frozen"]
    fz = U["frozen_df"]
    print(f"\n[DG-C4-4] the universe is FROZEN (team lead, 2026-10-14): {len(UF)} funds of the "
          f"GET /v2/assets read at {FROZEN_READ_UTC} ({FROZEN.relative_to(REPO)}); not re-read")
    print(f"  by family {fam.reindex(UF).value_counts().to_dict()}; easy to borrow "
          f"{int(fz['easy_to_borrow'].sum())}; fresh-NAV sub-book {sum(fam[t] in FRESH_NAV_FAMILIES for t in UF)}; "
          f"exchanges {fz['exchange'].value_counts().to_dict()}")
    print(f"  beside the approved 68 (R-68, reported only): in both {len(set(UF) & set(U['snap68']))}; "
          f"in the 68 only {sorted(set(U['snap68']) - set(UF))}; in the 74 only {sorted(set(UF) - set(U['snap68']))}")

    # DG-C4-1
    px, nav = load_panels(pool)
    crsp = crsp_returns(pool)
    qr = qqqx_rule(crsp, px)
    print(f"\n[DG-C4-1] CRSP ret/retx staged for {crsp['ticker'].nunique()} pool funds, "
          f"{crsp['date'].min().date()}..{crsp['date'].max().date()} ({CRSP_RET.relative_to(REPO)}, gitignored)")
    print(f"  QQQX rule: predecessor permno {QQQX_PRED_PERMNO} ({qr['pred_rows']} rows, to "
          f"{qr['pred_last'].date()}): {qr['agree']} of {qr['common']} common closing-trade dates within "
          f"${QQQX_TOL} of yfinance ({qr['share']:.2%}); rule >= {QQQX_RULE_SHARE:.0%} -> "
          f"{'USED' if qr['use_predecessor'] else 'NOT used; QQQX enters at ' + str(qr['current_first'].date())}")

    # the CRSP identity check (2026-10-15, after the review of 3be92cd found BTX on a biotech's permno)
    print(f"  CRSP identity (daily price move vs CRSP retx within max(10bp, $0.005/price) on "
          f">= {IDENTITY_MIN_AGREE:.0%} of days, CEF share code); BTX on permno 20674 (BIGZ), the map's 76963 overridden:")
    idt = []
    for wl, lo, hi, halts in (("fit", SAMPLE_START, FIT_END, fit_halts),
                              ("holdout CRSP leg", HOLDOUT_START, CRSP_END, ho_halts)):
        for lab, cols in (("frozen 74", UF), ("pool 105 (R-S)", pool)):
            tab = crsp_identity(crsp, px, cols, lo, hi, raise_on_fail=False)
            idt.append(tab.reset_index().assign(window=wl, book=lab))
            f = tab[tab["identity"] == "FAIL"]
            print(f"    {wl:<17} {lab:<15} {len(tab)} funds; min share {tab['move_share'].min():.4f} "
                  f"({tab['move_share'].idxmin()}); FAIL {f['move_share'].round(4).to_dict() or 'none'}; level within "
                  f"$0.005 on < 99% of days (reported): {tab.loc[tab['level_share'] < 0.99, 'level_share'].round(3).to_dict()}")
            if lab == "frozen 74" and len(f):
                halts.append(f"CRSP identity, {wl}: {sorted(f.index)} below {IDENTITY_MIN_AGREE:.0%} "
                             f"({f['move_share'].round(4).to_dict()})")
    pd.concat(idt).to_csv(OUT_DIR / f"c4_crsp_identity_{DIST_STAMP}.csv", index=False)

    # DG-C4-3
    ff = pd.read_parquet(_need(FACTOR_CACHE / "ff5_umd_daily.parquet", "python3 scripts/data/fetch_ff_factors.py"))
    ffm = pd.read_parquet(_need(FACTOR_CACHE / "ff5_umd_monthly.parquet", "python3 scripts/data/fetch_ff_factors.py"))
    ps = pd.read_parquet(_need(FACTOR_CACHE / "ps_liquidity_monthly.parquet",
                               "python3 scripts/data/fetch_pastor_liquidity.py"))
    etf = pd.read_parquet(REPO / "data" / "etf_daily.parquet", columns=["date", "ticker", "ret_total"])
    etf = etf[etf["ticker"].isin(["IEF", "HYG"])]
    span = etf.dropna().groupby("ticker")["date"].agg(["min", "max"])
    print(f"\n[DG-C4-3] French FF5+UMD daily {ff.date.min().date()}..{ff.date.max().date()} "
          f"(CRSP vintage {ff.crsp_vintage.iloc[0]}, fetched {ff.fetched_at_utc.iloc[0]}); monthly to "
          f"{ffm.date.max().date()}; Pastor-Stambaugh to {ps.date.max().date()} ({ps.header_through.iloc[0]}, "
          f"fetched {ps.fetched_at_utc.iloc[0]}); IEF {span.loc['IEF', 'min'].date()}..{span.loc['IEF', 'max'].date()}, "
          f"HYG {span.loc['HYG', 'min'].date()}..{span.loc['HYG', 'max'].date()} (data/etf_daily.parquet)")
    if ff.date.max() < FIT_END or ps.date.max() < FIT_END or span["max"].min() < HOLDOUT_END:
        fit_halts.append("DG-C4-3: a factor series does not cover the fit window")
    print("  -> fit window covered;", f"daily factors end {ff.date.max().date()} (the library's lag), "
          "holdout regressions (reported only) run to that date")

    # DG-C4-5
    bs = book_series()
    for lab, b in bs.items():
        print(f"\n[DG-C4-5] {lab} v7 book series builds: first position {b['first'].date()}, P&L rows "
              f"{b['span'][0].date()}..{b['span'][1].date()} ({b['n']}); live panel (no statistic computed here)")
    if bs["deployed"]["first"] != DEPLOYED_FIRST:
        fit_halts.append(f"DG-C4-5: deployed first position {bs['deployed']['first'].date()} != {DEPLOYED_FIRST.date()}")

    # eligibility (counts only) and the declared masks
    nav = nav.assign(repeat=repeat_mask(nav))
    E = eligibility(px, nav, MIN_ADV_USD, Z_WINDOW)
    elig = E["elig"]
    print(f"\n[ELIGIBILITY] counts of the sleeve's filters with M1 (NAV repeat) and M2 (zero volume), "
          f"floor ${MIN_ADV_USD:,.0f}, min_names {MIN_NAMES} (no signal, no return)")
    erows = []
    for lab, L in ((f"{len(UF)} (frozen, declared)", UF), ("68 (approved; R-68)", U["snap68"])):
        sub = elig[[c for c in elig.columns if c in L]]
        fr = [t for t in L if fam[t] in FRESH_NAV_FAMILIES]
        f0 = first_active(sub, MIN_NAMES)
        cnt = sub.sum(axis=1)
        fit_s = int(((cnt.index >= f0) & (cnt.index <= FIT_END)).sum())
        ho = int(((cnt.index >= HOLDOUT_START) & (cnt.index <= HOLDOUT_END)).sum())
        print(f"  universe {lab}: first active session {f0.date()}; fit sessions {fit_s}; holdout sessions "
              f"to {HOLDOUT_END.date()} {ho}")
        erows += era_rows(sub, MIN_NAMES, f"universe {lab}")
        erows += era_rows(sub[[c for c in sub.columns if c in fr]], MIN_NAMES, f"fresh-NAV sub-book of {lab}")
    et = pd.DataFrame(erows)
    print(et[["book", "era", "median_eligible", "active_share", "funds_ever_eligible"]].round(3).to_string(index=False))
    et.to_csv(OUT_DIR / f"c4_stage0_breadth_{STAMP}.csv", index=False)

    # the quality screen, on the primary return as declared
    prim, yf_tr, sess = primary_returns(pool, px, crsp, qr)
    flags = quality_screen(pool, px, nav, crsp, prim, yf_tr, sess, elig, qr)
    flags["in_frozen74"] = flags["ticker"].isin(set(UF))
    flags["in_68"] = flags["ticker"].isin(set(U["snap68"]))
    flags["ruling"] = [ruling_of(r) if r.check == "Q1" else "" for r in flags.itertuples()]
    CACHE.mkdir(parents=True, exist_ok=True)
    flags.to_parquet(CACHE / f"c4_stage0_flags_with_values_{STAMP}.parquet", index=False)  # licensed values
    pub = flags.drop(columns=["crsp_value"]).copy()
    pub.loc[pub["date"] <= CRSP_END, "value"] = np.nan          # nothing derived from CRSP leaves the cache
    pub.loc[(pub["check"] == "Q6") & pub["detail"].str.startswith("|diff|"), "detail"] = f"|diff| > {Q6_BP:g}bp"
    pub.to_csv(OUT_DIR / f"c4_stage0_flags_{STAMP}.csv", index=False)
    print(f"\n[QUALITY SCREEN] primary return as declared, {len(pool)} pool funds, {sess[0].date()}..{sess[-1].date()} "
          f"({len(sess)} sessions); flags by check:")
    tab = flags.groupby("check").agg(flags=("ticker", "size"), funds=("ticker", "nunique"),
                                     in_frozen74=("in_frozen74", "sum"), in_68=("in_68", "sum"))
    print(tab.to_string())
    q1 = flags[flags["check"] == "Q1"].sort_values(["ticker", "date"])
    print("\n  Q1 in full, with the 2026-10-14 ruling that covers each row:")
    print(q1[["ticker", "date", "source", "detail", "in_frozen74", "ruling"]].to_string(index=False))
    uncovered = q1[q1["ruling"] == ""]
    if len(uncovered):
        fit_halts.append(f"Q1: {len(uncovered)} name-days no ruling covers "
                         f"({', '.join(sorted(uncovered['ticker'].unique()))})")
    for c in ("Q2", "Q3", "Q4", "Q5", "Q6", "Q7"):
        x = flags[(flags["check"] == c) & flags["in_frozen74"]]
        if len(x):
            by = x.groupby("ticker").size().sort_values(ascending=False)
            print(f"  {c}: {len(x)} flags on {x['ticker'].nunique()} funds of the 74; most: {by.head(8).to_dict()}")

    # ruling 2: IGR's two days from Alpaca, and the cross-check of the adjacent bars
    alp = alpaca_pool()
    print(f"\n[ALPACA] second source fetched {alp['fetched']} (raw and split-adjusted SIP daily bars, "
          f"corporate actions; {ALP_POOL.relative_to(REPO)}, gitignored); Alpaca split records in the window: "
          f"{alp['splits']}")
    try:
        fill, chk = igr_fill(alp, px, sess)
        print(f"  IGR fill (ruling 2): split-adjusted closes {chk['closes']} (raw close on 2026-09-08 "
              f"{chk['raw_0908']}); r(2026-09-08) = {fill[IGR_FILL[0]]:+.4%}, r(2026-09-09) = {fill[IGR_FILL[1]]:+.4%}")
        print(f"  cross-check, Alpaca's adjacent bars (2026-08-17 -> 2026-09-30 without 09-08) against the "
              f"panel on one share basis: {chk['within_half_cent']} of {chk['sessions']} closes within $0.005 "
              f"(max |diff| ${chk['max_abs_diff']:.6f}); daily returns agree within {chk['max_return_diff_bp']:.3f}bp")
    except GateError as e:
        ho_halts.append(str(e))

    # the yfinance leg against Alpaca (an addition to the declared screen; it gates the holdout)
    for lab, L in (("frozen 74", UF), ("pool 105", pool)):
        bad, cl = yf_leg_crosscheck(L, px, alp)
        print(f"\n[YF LEG vs ALPACA, {lab}] 2025-01-02 -> 2026-09-30: closes {cl['within_half_cent']} of "
              f"{cl['compared']} within $0.005 (yfinance-only {cl['yf_only']}, Alpaca-only {cl['alpaca_only']}); "
              f"distribution ex-dates {cl['dividend_rows']}, of which {cl['dividend_rows_disagreeing']} disagree "
              f"(one side missing, or |diff| > ${DIV_TOL})")
        if lab == "frozen 74":
            g = bad.groupby("ticker").agg(n=("date", "size"), first=("date", "min"), last=("date", "max"),
                                          ratio_median=("ratio", "median"),
                                          yf_missing=("yfinance", lambda s: int(s.isna().sum())),
                                          alpaca_missing=("alpaca", lambda s: int(s.isna().sum())))
            print(g.to_string())
            bad.to_csv(OUT_DIR / f"c4_yf_leg_distribution_disagreements_{STAMP}.csv", index=False)
            if len(bad):
                if not DIST_TABLE.exists():
                    ho_halts.append(f"yfinance-leg distributions: {len(bad)} disagreeing ex-dates; run "
                                    "`c4_families.py distributions` (the 2026-10-14 ruling)")
                else:
                    T = pd.read_csv(DIST_TABLE, parse_dates=["date"])
                    ex = excluded_funds(T)
                    print(f"  rulings of 2026-10-14 and 2026-10-15 ({DIST_TABLE.name}): "
                          f"{int((~T['decision'].str.startswith('UNCONFIRMED')).sum())} of {len(T)} confirmed for Alpaca "
                          f"{T['decision'].value_counts().to_dict()}; funds excluded from the holdout (amendment 3): {ex}")
    if not FIT_REVIEWS_CONFIRMED:
        ho_halts.append("two independent reviews of the fit (3be92cd) have not yet confirmed it")

    print("\n" + "=" * 100)
    print("FIT GATE: " + ("CLEAR" if not fit_halts else "HALT"))
    for i, x in enumerate(fit_halts, 1):
        print(f"  {i}. {x}")
    print("HOLDOUT GATE: " + ("CLEAR" if not ho_halts else "HALT"))
    for i, x in enumerate(ho_halts, 1):
        print(f"  {i}. {x}")
    for x in notes:
        print(f"  note: {x}")
    return 1 if fit_halts else 0


# --------------------------------------------------------------------------- the distribution ruling

def confirm_distributions(bad: pd.DataFrame, cc: pd.DataFrame, nav: pd.DataFrame,
                          ex_dates: dict, sponsor: pd.DataFrame | None = None) -> pd.DataFrame:
    """The 2026-10-14 ruling, one row per disagreeing (fund, ex-date). Pure.

    bad      `ticker date yfinance alpaca` (NaN = that source has no distribution that day)
    cc       CEFConnect summed per ex-date: `ticker ex_date cc_amount cc_records`
    nav      the fund's daily NAV, date x ticker (the families yfinance NAV symbol)
    ex_dates {ticker: set of ex-dates in EITHER source}, excluded from sigma

    Decision, in the ruling's order: 'Alpaca (CEFConnect)' if CEFConnect's amount on that fund
    and ex-date equals Alpaca's within DIV_TOL (for an Alpaca absence: CEFConnect has records
    within CC_ABSENCE_WINDOW_DAYS on both sides and none that day); else 'Alpaca (NAV drop)'
    under the NAV_K rule; else 'UNCONFIRMED' (the holdout halts). CEFConnect's own reading is
    recorded either way ('= Alpaca', '= yfinance', 'neither', 'no record').

    `sponsor` (amendment 3, 2026-10-15): verified citations `ticker ex_date verdict` from the
    fund sponsor's own notices. A row no earlier source confirms becomes 'Alpaca (sponsor)' if a
    sponsor notice confirms it. A sponsor notice that CONTRADICTS Alpaca makes the row
    'UNCONFIRMED (sponsor contradicts Alpaca)' whatever CEFConnect or the NAV drop said."""
    out = []
    for r in bad.itertuples(index=False):
        A = 0.0 if pd.isna(r.alpaca) else float(r.alpaca)
        Y = 0.0 if pd.isna(r.yfinance) else float(r.yfinance)
        c = cc[(cc["ticker"] == r.ticker)]
        on = c[c["ex_date"] == r.date]
        ccv = float(on["cc_amount"].iloc[0]) if len(on) else np.nan
        if len(on):
            cc_read = ("= Alpaca" if abs(ccv - A) <= DIV_TOL else
                       "= yfinance" if abs(ccv - Y) <= DIV_TOL else "neither")
        else:
            lo = (c["ex_date"] < r.date) & (c["ex_date"] >= r.date - pd.Timedelta(days=CC_ABSENCE_WINDOW_DAYS))
            hi = (c["ex_date"] > r.date) & (c["ex_date"] <= r.date + pd.Timedelta(days=CC_ABSENCE_WINDOW_DAYS))
            cc_read = "covered, no record" if (lo.any() and hi.any()) else "no record"
        cc_ok = (cc_read == "= Alpaca") or (A == 0.0 and cc_read == "covered, no record")
        # the NAV drop
        s = nav[r.ticker].dropna() if r.ticker in nav.columns else pd.Series(dtype=float)
        drop = sigma = za = zy = np.nan
        nav_read = "unusable: no NAV"
        if r.date in s.index and s.index.get_loc(r.date) > 0:
            i = s.index.get_loc(r.date)
            prev_v, v = float(s.iloc[i - 1]), float(s.iloc[i])
            if v == prev_v:
                nav_read = "unusable: NAV repeated on the ex-date"
            else:
                ch = s.diff().iloc[max(1, i - NAV_WIN):i]
                ch = ch[(ch != 0) & ~ch.index.isin(list(ex_dates.get(r.ticker, ())))]
                if len(ch) < NAV_MIN_OBS:
                    nav_read = f"unusable: {len(ch)} usable NAV changes"
                else:
                    drop, sigma = prev_v - v, float(ch.std())
                    za, zy = (drop - A) / sigma, (drop - Y) / sigma
                    nav_read = ("confirms Alpaca" if abs(za) <= NAV_K and abs(zy) > NAV_K else
                                "cannot tell the sources apart" if abs(za) <= NAV_K else
                                "confirms yfinance, not Alpaca" if abs(zy) <= NAV_K else "matches neither")
        sp = (sponsor[(sponsor["ticker"] == r.ticker) & (sponsor["ex_date"] == r.date)]
              if sponsor is not None else pd.DataFrame(columns=["verdict"]))
        sp_read = ("contradicts Alpaca" if (sp["verdict"] == "contradicts Alpaca").any() else
                   "confirms Alpaca" if (sp["verdict"] == "confirms Alpaca").any() else "no notice")
        if sp_read == "contradicts Alpaca":
            decision = "UNCONFIRMED (sponsor contradicts Alpaca)"
        else:
            decision = ("Alpaca (CEFConnect)" if cc_ok else
                        "Alpaca (NAV drop)" if nav_read == "confirms Alpaca" else
                        "Alpaca (sponsor)" if sp_read == "confirms Alpaca" else "UNCONFIRMED")
        out.append(dict(ticker=r.ticker, date=r.date, yfinance=r.yfinance, alpaca=r.alpaca, cefconnect=ccv,
                        cefconnect_reads=cc_read, nav_drop=drop, nav_sigma=sigma, z_alpaca=za, z_yfinance=zy,
                        nav_reads=nav_read, sponsor_reads=sp_read, decision=decision))
    return pd.DataFrame(out)


def excluded_funds(table: pd.DataFrame) -> list:
    """Amendment 3: every fund with any unconfirmed disagreeing ex-date leaves the holdout. Pure."""
    return sorted(set(table.loc[table["decision"].str.startswith("UNCONFIRMED"), "ticker"]))


def holdout_actions(yf_actions: pd.DataFrame, table: pd.DataFrame, excluded=None) -> pd.DataFrame:
    """The yfinance actions with the rulings applied: on each confirmed row Alpaca's amount
    replaces yfinance's (0 removes a yfinance-only distribution; a date Alpaca alone carries is
    added). Splits untouched. An UNCONFIRMED row is allowed only in an `excluded` fund (amendment
    3); otherwise it raises, because the holdout cannot use it. Rows of excluded funds are not
    applied: those funds are not in the holdout. Pure."""
    excluded = set(excluded or ())
    un = table[table["decision"].str.startswith("UNCONFIRMED") & ~table["ticker"].isin(excluded)]
    if len(un):
        raise GateError(f"holdout halt: {len(un)} unconfirmed ex-dates in funds not excluded "
                        f"{sorted(set(un['ticker']))}")
    a = yf_actions.copy()
    a["date"] = pd.to_datetime(a["date"])
    for r in table[~table["ticker"].isin(excluded)].itertuples(index=False):
        A = 0.0 if pd.isna(r.alpaca) else float(r.alpaca)
        m = (a["ticker"] == r.ticker) & (a["date"] == r.date)
        if m.sum() > 1:
            raise GateError(f"two yfinance action rows for {r.ticker} {r.date.date()}")
        if m.any():
            a.loc[m, "dividends"] = A
        elif A > 0:
            a = pd.concat([a, pd.DataFrame([dict(date=r.date, ticker=r.ticker, dividends=A, stock_splits=0.0)])],
                          ignore_index=True)
    return a.sort_values(["ticker", "date"]).reset_index(drop=True)


def distributions() -> int:
    """Fetch-free: apply the 2026-10-14 distribution ruling to the 71 disagreeing ex-dates.
    Distribution amounts only; no return is computed."""
    U = universes()
    UF = U["frozen"]
    px, nav = load_panels(U["pool"])
    alp = alpaca_pool()
    bad, cl = yf_leg_crosscheck(UF, px, alp)
    raw = pd.read_parquet(_need(CC_DIST, "python3 scripts/data/fetch_cefconnect_distributions.py --c4-universe "
                                         "--start 2024-12-01 --end 2026-10-14"))
    from scripts.data.fetch_cefconnect_distributions import per_ex_date
    cc = per_ex_date(raw)
    navp = nav.pivot_table(index="date", columns="ticker", values="nav").sort_index()
    acts = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
    acts["date"] = pd.to_datetime(acts["date"])
    exd = {t: set(acts[(acts["ticker"] == t) & (acts["dividends"] > 0)]["date"])
           | set(d for (tk, d) in alp["divs"].index if tk == t) for t in UF}
    print(f"C4 DISTRIBUTION RULING (team lead, 2026-10-14), run {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC. "
          f"Distribution amounts only; no return is computed; the holdout is NOT opened.")
    print(f"  disagreeing ex-dates on the frozen 74 (yfinance leg 2025-01-02 -> 2026-09-30): {len(bad)} "
          f"of {cl['dividend_rows']}; CEFConnect fetched {raw['fetched_utc'].iloc[0]} ({len(raw)} records, "
          f"{raw['ticker'].nunique()} funds); Alpaca fetched {alp['fetched']}")
    print(f"  tolerances: CEFConnect = Alpaca within ${DIV_TOL} per share; NAV drop: |drop - A| <= {NAV_K:g} sigma and "
          f"|drop - Y| > {NAV_K:g} sigma, sigma the sd of the fund's daily NAV changes over the {NAV_WIN} prior "
          f"sessions (ex-dates and repeats excluded, at least {NAV_MIN_OBS}); NAV = the families yfinance NAV symbol")
    # calibration: CEFConnect on the ex-dates where yfinance and Alpaca AGREE
    yd = acts[(acts["dividends"] > 0) & acts["ticker"].isin(UF)].set_index(["ticker", "date"])["dividends"]
    m = pd.concat([yd.rename("yf"), alp["divs"].rename("alp")], axis=1)
    d = m.index.get_level_values(1)
    m = m[(d >= YF_START) & (d <= HOLDOUT_END) & m.index.get_level_values(0).isin(UF)].dropna()
    m = m[(m["yf"] - m["alp"]).abs() <= DIV_TOL].reset_index()
    m.columns = ["ticker", "ex_date", "yf", "alp"]
    j = m.merge(cc, on=["ticker", "ex_date"], how="left")
    agree = int(((j["cc_amount"] - j["alp"]).abs() <= DIV_TOL).sum())
    print(f"  calibration: on the {len(j)} ex-dates where yfinance and Alpaca agree, CEFConnect agrees on {agree}, "
          f"differs on {int(((j['cc_amount'] - j['alp']).abs() > DIV_TOL).sum())}, has no record on "
          f"{int(j['cc_amount'].isna().sum())}")
    sp = pd.read_parquet(_need(SPONSOR_VERIFIED, "python3 scripts/data/fetch_sponsor_notices.py"))
    if not sp["quote_found"].all():
        raise GateError("a sponsor citation's quote was not found in its document")
    sp["ex_date"] = pd.to_datetime(sp["ex_date"])
    print(f"  sponsor notices (amendment 3): {len(sp)} verified citations from {sp['url'].nunique()} documents, "
          f"fetched {sp['fetched_utc'].iloc[0]} ({SPONSOR_CITATIONS.name}); every quote found in its document")
    T = confirm_distributions(bad, cc, navp, exd, sponsor=sp[["ticker", "ex_date", "verdict"]])
    T.to_csv(DIST_TABLE, index=False)
    ex = excluded_funds(T)
    EXCLUSIONS_JSON.write_text(json.dumps(dict(
        rule="PREREG amendment 3 (team lead, 2026-10-15): a fund with any unconfirmed disagreeing ex-date is "
             "excluded from the holdout entirely", excluded=ex,
        reasons={t: T.loc[(T["ticker"] == t) & T["decision"].str.startswith("UNCONFIRMED"),
                          ["date", "decision"]].assign(date=lambda x: x["date"].dt.date.astype(str)).values.tolist()
                 for t in ex}), indent=1))
    pd.set_option("display.width", 250)
    print("\n" + T.assign(date=T["date"].dt.date).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\n  by fund and decision:")
    print(T.groupby(["ticker", "decision"]).size().unstack(fill_value=0).to_string())
    print("\n  CEFConnect's reading of the 71:", T["cefconnect_reads"].value_counts().to_dict())
    print("  NAV-drop reading of the 71:", T["nav_reads"].value_counts().to_dict())
    un = T[T["decision"].str.startswith("UNCONFIRMED")]
    print("\n" + "=" * 100)
    print(f"CONFIRMED for Alpaca: {len(T) - len(un)} of {len(T)} ({T['decision'].value_counts().to_dict()})")
    print(f"EXCLUDED FROM THE HOLDOUT (amendment 3, a fund with any unconfirmed ex-date): {ex or 'none'} "
          f"({un.groupby('ticker').size().to_dict()}); the holdout universe is the {len(UF) - len(ex)} other frozen funds")
    print(f"HOLDOUT GATE (fit reviews): {'CLEAR' if FIT_REVIEWS_CONFIRMED else 'HALT -- two independent reviews of the fit (3be92cd) are pending'}")
    return 0


# --------------------------------------------------------------------------- fit machinery

def declared_mask(universe, kind: str = "M1M2"):
    """The §4.3 masks on `build_panel`'s own index: M1 (NAV repeat) | M2 (zero volume).
    kind 'none' (R-Q0) or 'cc' (R-Q1: only CEFConnect-confirmed stale copies, plus M2)."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.c4_feasibility import repeat_mask
    if kind == "none":
        return None
    p = bf.build_panel(universe=universe, source=FAM_SRC)
    paired = p["px"].notna()
    zv = p["vol"].reindex_like(paired).eq(0) & paired
    if kind == "M1M2":
        nav = pd.read_parquet(FAM_SRC[1])
        nav = nav[nav["ticker"].isin(universe)].copy()
        nav["date"] = pd.to_datetime(nav["date"])
        nav["repeat"] = repeat_mask(nav)
        rep = nav.pivot_table(index="date", columns="ticker", values="repeat", aggfunc="max")
        m1 = rep.reindex(index=paired.index, columns=paired.columns).eq(True) & paired
    elif kind == "cc":
        fl = pd.read_parquet(FAM_DIR / "nav_flags.parquet")
        fl = fl[fl["ticker"].isin(universe)].copy()
        fl["date"] = pd.to_datetime(fl["date"])
        chk = fl["cc_nav_All"].where(fl["cc_nav_All"].notna(), fl["cc_nav_1Y"])
        fl["stale"] = chk.eq("A_REPEATED")
        st = fl.pivot_table(index="date", columns="ticker", values="stale", aggfunc="max")
        m1 = st.reindex(index=paired.index, columns=paired.columns).eq(True) & paired
    else:
        raise ValueError(kind)
    return m1 | zv


def build_book(universe, kind: str = "M1M2") -> pd.DataFrame:
    from scripts.cef import band_frontier as bf
    T, _ = bf.build_targets(universe=list(universe), source=FAM_SRC, mask=declared_mask(list(universe), kind))
    return T


def fit_slice(f):
    out = f.loc[:FIT_END]
    if len(out) and out.index.max() >= HOLDOUT_START:
        raise AssertionError("holdout leak")
    return out


def check_held(H: pd.DataFrame, R: pd.DataFrame, label: str, extended: bool = False) -> pd.DataFrame:
    """H15 on the P&L: no held weight may meet a name-day with no return; the ruled name-days are
    asserted unheld (decided and held). Returns R with NaN -> 0, safe because every NaN that
    remains multiplies a weight just proved to be zero."""
    held = H.shift(2).fillna(0.0)
    R = R.reindex_like(H)
    bad = (held != 0) & R.isna()
    if bad.any().any():
        where = bad.stack()
        raise GateError(f"{label}: a held position meets a name-day with no primary return: "
                        f"{[(str(d.date()), t) for d, t in where[where].index[:10]]}")
    books = dict(RULED_NOT_HELD, **(EXTENDED_NOT_HELD if extended else {}))
    for t, (a, b) in books.items():
        if t in H.columns:
            if (H.loc[a:b, t] != 0).any() or (held.loc[a:b, t] != 0).any():
                raise GateError(f"{label}: {t} is held on {a}..{b}, which the ruling says it cannot be")
    return R.fillna(0.0)


def sr_of(x: pd.Series) -> float:
    return float(x.mean() / x.std() * np.sqrt(252))


def row_stats(P: pd.Series, TU: pd.Series) -> dict:
    from scripts.cef.band_frontier import _stats
    s = _stats(P, TU)
    signs = {np.sign(v) for v in [s["sr"], *s["nets"]]}
    return dict(sr=s["sr"], ann_pct=s["ann"] * 100, vol_pct=s["vol"] * 100, turn=s["turn"],
                net5=s["nets"][0], net15=s["nets"][1], net30=s["nets"][2], flips="YES" if len(signs) > 1 else "no",
                days=len(P), years=len(P) / 252)


_PAIRED: set = set()


def paired_before_holdout() -> set:
    """The pool funds with at least one paired price and NAV (both > $0.50) before 2023: the funds
    a fit-window book can ever hold. Counted 2026-10-15 after the review of 3be92cd found that
    "74 funds" overstated the fit universe (65 of the 74 have such a row)."""
    if not _PAIRED:
        from scripts.cef import band_frontier as bf
        U = universes()
        p = bf.build_panel(universe=U["pool"], source=FAM_SRC)["px"].loc[:FIT_END]
        _PAIRED.update(p.columns[p.notna().any()])
    return _PAIRED


def run_book(label, universe, R_all, kind="M1M2", policy="capped", extended=False, T=None):
    """One book on the fit window: (row, P, H, R0, p0). R_all holds the primary return for every
    fund of `universe` on the fit index (NaN kept)."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS
    T = fit_slice(build_book(universe, kind) if T is None else T)
    H = bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS) if policy == "capped" else bf.band(T, BAND_WIDTH)
    R0 = check_held(H, R_all[list(universe)].reindex(T.index), label, extended)
    r = bf.evaluate(H, R0)
    held = H.shift(2).abs().sum(axis=1)
    if not (held > 0).any():
        raise GateError(f"{label}: the book never holds a position in the fit window")
    p0 = held.index[held > 0][0]
    P, TU = r["pnl"].loc[p0:FIT_END], r["turn_series"].loc[p0:FIT_END]
    row = dict(book=label, universe=len(universe), funds=len(set(universe) & paired_before_holdout()),
               first_held=str(p0.date()), **row_stats(P, TU))
    return row, P, H, R0, p0, T


def hac(y, X, lags):
    import statsmodels.api as sm
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    f = sm.OLS(d["y"], sm.add_constant(d.drop(columns="y"))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return f, len(d)


def factor_frame() -> pd.DataFrame:
    """FF5 + UMD (French, daily), TERM = IEF - RF, HY = HYG - IEF (total returns, data/etf_daily)."""
    ff = pd.read_parquet(FACTOR_CACHE / "ff5_umd_daily.parquet")
    ff["date"] = pd.to_datetime(ff["date"])
    ff = ff.set_index("date").sort_index()
    e = pd.read_parquet(REPO / "data" / "etf_daily.parquet", columns=["date", "ticker", "ret_total"])
    e["date"] = pd.to_datetime(e["date"])
    e = e[e["ticker"].isin(["IEF", "HYG"])].pivot(index="date", columns="ticker", values="ret_total")
    X = ff[FF6].copy()
    X["TERM"] = e["IEF"].reindex(ff.index) - ff["rf"]
    X["HY"] = e["HYG"].reindex(ff.index) - e["IEF"].reindex(ff.index)
    return X


def dimson(y, X, cols, scale):
    """Factors at t and t-1 (on the factor calendar), betas summed, HAC(21). Betas scaled to the vol
    target by `scale` = vol_target / sigma_fit (ruling 4 of 2026-10-12, PREREG §5)."""
    Z = pd.concat([X[cols].reindex(y.index), X[cols].shift(1).reindex(y.index).add_suffix("_l1")], axis=1)
    f, n = hac(y, Z, NW_L)
    betas = {c: (f.params[c] + f.params[c + "_l1"]) * scale for c in cols}
    return dict(n=n, alpha_pct=f.params["const"] * 252 * 100, alpha_t=f.tvalues["const"], r2=f.rsquared,
                betas=betas, max_abs_beta=max(abs(v) for v in betas.values()))


def contemporaneous(y, X, cols, scale):
    f, n = hac(y, X[cols].reindex(y.index), NW_L)
    betas = {c: f.params[c] * scale for c in cols}
    return dict(n=n, alpha_pct=f.params["const"] * 252 * 100, alpha_t=f.tvalues["const"], r2=f.rsquared,
                betas=betas, max_abs_beta=max(abs(v) for v in betas.values()))


def block_sums(x: pd.Series, k: int) -> pd.Series:
    n = len(x) // k
    return pd.Series([x.iloc[i * k:(i + 1) * k].sum() for i in range(n)],
                     index=[x.index[i * k] for i in range(n)])


# --------------------------------------------------------------------------- fit

def fit() -> int:
    from scipy import stats as sst
    from scripts.cef import band_frontier as bf
    from scripts.cef import w4_artifacts as w4
    from scripts.cef.spec import (BAND_WIDTH, MAX_GROSS_STRESS, MIN_NAMES, SPEC_ID, VOL_TARGET,
                                  Z_WINDOW, summary)
    from scripts.cef.spec import MIN_ADV_USD as MIN_ADV
    from scripts.cef.validate import _dsr
    from scripts.cef.w10_partb import decompose_holdings, decompose_signal, pooled_components
    _tracked_clean(FROZEN, STAGE0_OUT)
    if "FIT GATE: CLEAR" not in STAGE0_OUT.read_text():
        raise GateError(f"{STAGE0_OUT.name} does not say FIT GATE: CLEAR")
    N = cef_counter()
    out: dict = dict(spec=SPEC_ID, N=N, run_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    print(summary())
    print(f"C4 FIT (CEF trial 52): the fit window only; the 2023-01-01 holdout is sealed and never computed "
          f"here. Run {out['run_utc'][:16]} UTC. CEF counter N = {N} (docs/RESEARCH_STATE.md), bar "
          f"sqrt(2 ln N) = {math.sqrt(2 * math.log(N)):.3f}")
    if N != 52:
        raise GateError(f"the approval judges C4 at N = 52; the counter reads {N}")

    U = universes()
    fam, sub, pool, UF = U["fam"], U["sub"], U["pool"], U["frozen"]
    px, nav = load_panels(pool)
    crsp = crsp_returns(pool)
    qr = qqqx_rule(crsp, px)
    if not qr["use_predecessor"]:
        raise GateError("the QQQX rule's decision changed since Stage 0")

    # the fit index and the primary return (CRSP only: every fit date is before 2024-12-31)
    T74 = fit_slice(build_book(UF))
    idx = T74.index
    R_ret = crsp_pivot(crsp, pool, idx, qr, "ret", px=px)
    R_retx = crsp_pivot(crsp, pool, idx, qr, "retx", px=px)
    w4._assert_fit(idx, R_ret)

    # ---------------- the declared book
    row, P, H, R0, p0, _ = run_book("C4 (74, declared)", UF, R_ret, T=T74)
    t0 = H.index[H.abs().sum(axis=1) > 0][0]
    res = bf.evaluate(H, R0)
    TU = res["turn_series"].loc[p0:FIT_END]
    w4._assert_fit(P, TU)
    n_fit = len(set(UF) & paired_before_holdout())
    out["funds_with_fit_data"] = n_fit
    out["funds_without_fit_data"] = sorted(set(UF) - paired_before_holdout())
    print(f"\nTHE TRADABLE SLEEVE: {len(UF)} frozen funds, of which {n_fit} have a paired price and NAV before 2023 "
          f"(not: {', '.join(out['funds_without_fit_data'])}); band {BAND_WIDTH} to the edge, gross cap {MAX_GROSS_STRESS}, "
          f"vol target {VOL_TARGET}, z_window {Z_WINDOW}, min_names {MIN_NAMES}, ADV floor ${MIN_ADV:,.0f} "
          f"(spec {SPEC_ID}). First decision {t0.date()}, first held session {p0.date()}; fit P&L "
          f"{p0.date()}..{P.index[-1].date()}, {len(P)} sessions ({len(P) / 252:.2f} years)")

    # ---------------- Stage 0's remaining items (zero trials, fit window)
    prev = H.shift(1).fillna(0.0).loc[t0:FIT_END]
    Tw, Hw = T74.loc[t0:FIT_END], H.loc[t0:FIT_END]
    act = (Tw.ne(0) | prev.ne(0)).to_numpy()
    trig = ((Tw - prev).abs() > BAND_WIDTH).to_numpy()
    off = ((Hw - Tw).abs() > 1e-12).to_numpy()
    gross = Hw.abs().sum(axis=1)
    cap_bind = float((gross >= MAX_GROSS_STRESS - 1e-9).mean())
    st0 = dict(turn_per_yr=row["turn"], band_trade_share=float(trig[act].mean()),
               off_target_share=float(off[act].mean()), cap_binding_share=cap_bind,
               mean_gross_held=float(gross.mean()), mean_gross_target=float(Tw.abs().sum(axis=1).mean()),
               realised_vol_pct=row["vol_pct"], vol_target_pct=VOL_TARGET * 100, universe=len(UF))
    out["stage0_items"] = st0
    print(f"\n[STAGE 0, remaining items] turnover {st0['turn_per_yr']:.1f}/yr; the band trades a name on "
          f"{st0['band_trade_share']:.1%} of active name-days (|target - held| > band) and holds it off "
          f"target on {st0['off_target_share']:.1%}; the gross cap binds on {st0['cap_binding_share']:.1%} of "
          f"decision days (mean held gross {st0['mean_gross_held']:.2f}, mean target gross "
          f"{st0['mean_gross_target']:.2f}); realised vol {st0['realised_vol_pct']:.2f}%/yr against the "
          f"{st0['vol_target_pct']:.0f}% target; universe {len(UF)}")
    print("\n" + "-" * 100 + "\nTHE TRIAL IS SPENT FROM HERE (counted at approval; N = 52)\n" + "-" * 100)

    # ---------------- Stage 1
    t21, t5 = w4.nw_t(P, NW_L), w4.nw_t(P, NW_L_W4)
    L94 = w4.nw94_lag(P)
    t94 = w4.nw_t(P, L94)
    m21, s21 = w4.stationary_boot(P, BOOT_BLOCK, BOOT_REPS, SEED)
    m63, s63 = w4.stationary_boot(P, BOOT_BLOCK_2, BOOT_REPS, SEED)
    tmb, lomb, himb = w4.block_boot_t(P)
    ci = lambda a: [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]  # noqa: E731
    s1 = dict(gross_sr=row["sr"], nw_t21=t21, nw_t5=t5, nw94_lag=L94, nw_t94=t94,
              boot21_mean_ci_pct=[x * 252 * 100 for x in ci(m21)], boot21_sr_ci=ci(s21),
              boot63_mean_ci_pct=[x * 252 * 100 for x in ci(m63)], boot63_sr_ci=ci(s63),
              moving_block_t=tmb, moving_block_mean_ci_pct=[lomb * 252 * 100, himb * 252 * 100],
              pass_=bool(t21 >= D1_T))
    out["stage1"] = s1
    print(f"\n[STAGE 1] HEADLINE: gross Sharpe {row['sr']:.3f} (ann {row['ann_pct']:.2f}%, vol {row['vol_pct']:.2f}%), "
          f"NW t (L=21) {t21:.2f}  -> rule t >= {D1_T}: {'PASS' if s1['pass_'] else 'FAIL (KILL D1)'}")
    print(f"  beside it: NW t (L=5) {t5:.2f}; NW (1994) automatic lag {L94}, t {t94:.2f}; stationary bootstrap "
          f"(mean block 21, {BOOT_REPS:,}, seed {SEED}) 95% CI mean {s1['boot21_mean_ci_pct'][0]:+.2f}..{s1['boot21_mean_ci_pct'][1]:+.2f} %/yr, "
          f"Sharpe {s1['boot21_sr_ci'][0]:+.2f}..{s1['boot21_sr_ci'][1]:+.2f}; mean block 63: mean "
          f"{s1['boot63_mean_ci_pct'][0]:+.2f}..{s1['boot63_mean_ci_pct'][1]:+.2f}, Sharpe {s1['boot63_sr_ci'][0]:+.2f}..{s1['boot63_sr_ci'][1]:+.2f}; "
          f"moving block (w4 block_boot_t, block 20, 2,000, seed 20261011) t {tmb:.2f}")
    fee = pd.DataFrame(0.0, index=H.index, columns=H.columns)
    bc = bf.borrow_charge(H, fee)
    short = bc["short"].loc[p0:FIT_END]
    out["cost_grid"] = dict(gross=row["sr"], net5=row["net5"], net15=row["net15"], net30=row["net30"],
                            turn=row["turn"], flips=row["flips"])
    out["borrow"] = dict(charge_pct_per_yr=float(bc["cost"].loc[p0:FIT_END].mean() * 252 * 100),
                         mean_short_notional=float(short.mean()), covered_share=bc["covered_share"])
    print("\n  COST GRID (bp per unit one-way turnover; gross is the headline, never mixed in):")
    print(f"  {'book':<22}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'turn/yr':>9}{'net@5':>8}{'net@15':>8}{'net@30':>8}{'flips?':>8}")
    print(f"  {'C4 (74, declared)':<22}{row['sr']:8.3f}{row['ann_pct']:7.2f}{row['vol_pct']:7.2f}{row['turn']:9.1f}"
          f"{row['net5']:8.3f}{row['net15']:8.3f}{row['net30']:8.3f}{row['flips']:>8}")
    print(f"  BORROW (separate, labelled; a COUNTERFACTUAL: one snapshot, 2026-10-14, applied to {len(P) / 252:.1f} "
          f"years): every fund was easy to borrow at the frozen read, and Alpaca charges no fee on an "
          f"easy-to-borrow short (REFERENCES §12l), so the charge is {out['borrow']['charge_pct_per_yr']:.3f}%/yr. "
          f"Mean short notional {short.mean():.3f} of capital, for any other rate. No historical fee series exists.")

    # eras, years, halves
    erows = []
    for lab, a, b in FIT_ERAS:
        x, tx = P.loc[a:b], TU.loc[a:b]
        if len(x) > 20:
            erows.append(dict(book="C4 (74, declared)", era=lab, **row_stats(x, tx)))
    ev = np.array([e["turn"] for e in erows])
    yr = P.groupby(P.index.year).sum()
    h1, h2 = P.iloc[:len(P) // 2], P.iloc[len(P) // 2:]
    out["eras"] = erows
    out["era_turnover_sd_over_mean"] = float(ev.std() / ev.mean())
    out["years_positive"] = [int((yr > 0).sum()), int(len(yr))]
    out["halves_sr"] = [sr_of(h1), sr_of(h2)]
    print("\n  ERAS (fit; the 2023-26 row is the holdout, opened later):")
    for e in erows:
        print(f"    {e['era']:<9}{e['sr']:8.3f}{e['ann_pct']:7.2f}{e['vol_pct']:7.2f}{e['turn']:9.1f}"
              f"{e['net5']:8.3f}{e['net15']:8.3f}{e['net30']:8.3f}{e['flips']:>8}  ({e['days']} sessions)")
    print(f"    era turnover sd/mean {out['era_turnover_sd_over_mean']:.1%}; calendar years with positive gross "
          f"{out['years_positive'][0]} of {out['years_positive'][1]}; first half Sharpe {out['halves_sr'][0]:.3f} "
          f"({h1.index[0].date()}..{h1.index[-1].date()}), second half {out['halves_sr'][1]:.3f}")

    # ---------------- Stage 2: the stale-NAV control
    fresh = [t for t in UF if fam[t] in FRESH]
    rowf, Pf, Hf, _, p0f, _ = run_book("fresh-NAV sub-book", fresh, R_ret)
    sr_f_pooledwin = sr_of(bf.evaluate(Hf, check_held(Hf, R_ret[fresh].reindex(Hf.index), "fresh"))["pnl"].loc[p0:FIT_END])
    s2 = dict(sub_sr=rowf["sr"], sub_first_held=rowf["first_held"], sub_turn=rowf["turn"], pooled_turn=row["turn"],
              half_pooled=0.5 * row["sr"], sub_sr_on_pooled_window=sr_f_pooledwin, funds=len(fresh),
              funds_with_fit_data=len(set(fresh) & paired_before_holdout()),
              pass_=bool(rowf["sr"] > 0 and rowf["sr"] >= 0.5 * row["sr"]))
    out["stage2"] = s2
    print(f"\n[STAGE 2] STALE-NAV CONTROL: the identical rule on the {len(fresh)} domestic, sector and covered-call "
          f"funds ({len(set(fresh) & paired_before_holdout())} with fit data; own vol scalar and cap), from its own first held session {rowf['first_held']}: gross Sharpe "
          f"{rowf['sr']:.3f} (turnover {rowf['turn']:.1f}/yr; pooled {row['turn']:.1f}/yr)  -> rule > 0 and >= "
          f"1/2 x pooled ({0.5 * row['sr']:.3f}): {'PASS' if s2['pass_'] else 'FAIL (KILL D1, stale-NAV artefact)'}")
    print(f"  beside it: the sub-book over the pooled window ({p0.date()}..): {sr_f_pooledwin:.3f}")

    # ---------------- Stage 3a: block-shuffled placebo (fast path checked against evaluate())
    Hv, Rv = H.to_numpy(), R0.to_numpy()
    nan_v = R_ret[UF].reindex(H.index).isna().to_numpy()
    i0, iL, jp0 = H.index.get_loc(t0), len(H.index) - 1, H.index.get_loc(p0)
    lag2 = lambda A: np.vstack([np.zeros((2, A.shape[1])), A[:-2]])  # noqa: E731  (== H.shift(2).fillna(0))
    fast = (lag2(Hv) * Rv).sum(axis=1)[jp0:]
    gap = float(np.abs(fast - res["pnl"].loc[p0:FIT_END].to_numpy()).max())
    if gap > 1e-15:                    # summation order only; a P&L row is ~1e-3
        raise AssertionError(f"the placebo's fast path differs from evaluate() by {gap:.2e}")
    seg = Hv[i0:iL + 1]
    nb = math.ceil(len(seg) / PLACEBO_BLOCK)
    blocks = [seg[k * PLACEBO_BLOCK:(k + 1) * PLACEBO_BLOCK] for k in range(nb)]
    rng = np.random.default_rng(SEED)
    psr, nanshare = np.empty(PLACEBO_DRAWS), np.empty(PLACEBO_DRAWS)
    for d in range(PLACEBO_DRAWS):
        Hp = Hv.copy()
        Hp[i0:iL + 1] = np.concatenate([blocks[k] for k in rng.permutation(nb)])
        held = lag2(Hp)
        x = (held * Rv).sum(axis=1)[jp0:]
        psr[d] = x.mean() / x.std(ddof=1) * np.sqrt(252)
        ha = np.abs(held[jp0:])
        nanshare[d] = (ha * nan_v[jp0:]).sum() / ha.sum()
    p95 = float(np.percentile(psr, 95))
    s3a = dict(placebo_p50=float(np.median(psr)), placebo_p95=p95, placebo_max=float(psr.max()),
               rank=int((psr < row["sr"]).sum()), draws=PLACEBO_DRAWS, blocks=nb,
               mean_held_on_no_return_share=float(nanshare.mean()), pass_=bool(row["sr"] > p95))
    out["stage3a"] = s3a
    print(f"\n  (placebo fast path reproduces evaluate() to {gap:.1e} per row)")
    print(f"\n[STAGE 3a] PLACEBO: rows of the tradable H permuted in {nb} contiguous {PLACEBO_BLOCK}-session blocks "
          f"(returns fixed), {PLACEBO_DRAWS} draws, seed {SEED}: median {s3a['placebo_p50']:.3f}, 95th percentile "
          f"{p95:.3f}, max {s3a['placebo_max']:.3f}; real {row['sr']:.3f} beats {s3a['rank']} of {PLACEBO_DRAWS}  "
          f"-> rule real > p95: {'PASS' if s3a['pass_'] else 'FAIL (KILL D1)'}")
    print(f"  a shuffled position can land on a name-day before its fund existed, where it earns nothing: "
          f"{s3a['mean_held_on_no_return_share']:.2%} of placebo held gross on average (a property of the declared design)")

    # ---------------- Stage 3b: shift(3)
    H1 = H.shift(1).fillna(0.0)
    R01 = check_held(H1, R_ret[UF].reindex(H.index), "shift(3)")
    P3 = bf.evaluate(H1, R01)["pnl"].loc[p0:FIT_END]
    s3b = dict(sr_shift3=sr_of(P3), half=0.5 * row["sr"], ratio=sr_of(P3) / row["sr"],
               pass_=bool(sr_of(P3) >= 0.5 * row["sr"]))
    out["stage3b"] = s3b
    print(f"\n[STAGE 3b] SHIFT(3): evaluate(H.shift(1), R) over the same window: gross Sharpe {s3b['sr_shift3']:.3f} "
          f"({s3b['ratio']:.0%} of shift(2))  -> rule >= 1/2 x shift(2) ({s3b['half']:.3f}): "
          f"{'PASS' if s3b['pass_'] else 'FAIL (KILL D1)'}")

    # ---------------- Stage 4: R-D4 and the reported regressions
    X = factor_frame()
    sig_fit = float(P.std() * np.sqrt(252))
    scale = VOL_TARGET / sig_fit
    A = dimson(P, X, FF6 + ["TERM"], scale)
    PB = P.loc[max(HY_START, p0):FIT_END]
    B = dimson(PB, X, FF6 + ["TERM", "HY"], scale)
    okA = A["alpha_t"] >= D4_ALPHA_T and A["max_abs_beta"] <= D4_BETA
    okB = B["alpha_t"] >= D4_ALPHA_T and B["max_abs_beta"] <= D4_BETA
    A0 = contemporaneous(P, X, FF6 + ["TERM"], scale)
    B0 = contemporaneous(PB, X, FF6 + ["TERM", "HY"], scale)
    out["stage4"] = dict(sigma_fit_pct=sig_fit * 100, scale=scale, full=A, hy=B, r0_full=A0, r0_hy=B0,
                         pass_=bool(okA and okB))
    print(f"\n[STAGE 4] R-D4: daily gross P&L on FF5 + UMD, TERM (= IEF - RF) and HY (= HYG - IEF), each at t and "
          f"t-1 (Dimson; betas summed), HAC(21); betas scaled to the {VOL_TARGET:.0%} target by "
          f"{VOL_TARGET:.2f} / sigma_fit ({sig_fit:.2%}) = {scale:.3f}")
    for lab, r_, ok in (("full fit, no HY", A, okA), (f"{max(HY_START, p0).date()}.. with HY", B, okB)):
        print(f"  {lab:<24} n {r_['n']}  alpha {r_['alpha_pct']:+.2f}%/yr  t {r_['alpha_t']:.2f}  R2 {r_['r2']:.3f}  "
              + "  ".join(f"{k} {v:+.3f}" for k, v in r_["betas"].items())
              + f"  -> {'pass' if ok else 'FAIL'}")
    print(f"  -> rule alpha t >= {D4_ALPHA_T} and every |beta| <= {D4_BETA} in BOTH: "
          f"{'PASS' if out['stage4']['pass_'] else 'FAIL (KILL D4)'}")
    for lab, r_ in (("R-0 full (contemporaneous)", A0), ("R-0 with HY (contemporaneous)", B0)):
        print(f"  {lab:<32} alpha {r_['alpha_pct']:+.2f}%/yr t {r_['alpha_t']:.2f}  max|beta| {r_['max_abs_beta']:.3f}")
    # R-FF monthly
    ffm = pd.read_parquet(FACTOR_CACHE / "ff5_umd_monthly.parquet")
    ffm["date"] = pd.to_datetime(ffm["date"])
    ps = pd.read_parquet(FACTOR_CACHE / "ps_liquidity_monthly.parquet")
    ps["date"] = pd.to_datetime(ps["date"])
    mp = (1 + P).groupby(pd.Grouper(freq="ME")).prod() - 1
    first_full = (p0 + pd.offsets.MonthBegin(1)) + pd.offsets.MonthEnd(0)
    mp = mp.loc[first_full:]
    Xm = pd.concat([ffm.set_index("date")[FF6], ps.set_index("date")["liq_v"]], axis=1).reindex(mp.index)
    fm_, nm = hac(mp, Xm, 4)
    out["r_ff_monthly"] = dict(n=nm, alpha_pct=fm_.params["const"] * 12 * 100, alpha_t=fm_.tvalues["const"],
                               betas={c: fm_.params[c] for c in FF6 + ["liq_v"]}, r2=fm_.rsquared)
    print(f"  R-FF (monthly, FF5 + UMD + PS traded liquidity, HAC(4), {nm} months from {first_full.date()}): "
          f"alpha {out['r_ff_monthly']['alpha_pct']:+.2f}%/yr t {out['r_ff_monthly']['alpha_t']:.2f}  "
          + "  ".join(f"{k} {v:+.3f}" for k, v in out["r_ff_monthly"]["betas"].items()))

    # ---------------- Stage 5: correlation with the book
    bs = book_series()
    s5 = {}
    for lab in ("deployed", "WIDE"):
        b = bs[lab]["pnl"]
        common = P.loc[DEPLOYED_FIRST:FIT_END].index.intersection(b.loc[DEPLOYED_FIRST:FIT_END].index)
        x, y = P.reindex(common), b.reindex(common)
        bx, by = block_sums(x, CORR_BLOCK), block_sums(y, CORR_BLOCK)
        hy = X["HY"].reindex(common)
        if hy.isna().any():
            raise GateError(f"HY (HYG - IEF) has no value on {int(hy.isna().sum())} sessions of the correlation window")
        bh = block_sums(hy, CORR_BLOCK)
        stress = bh <= bh.quantile(0.2)
        s5[lab] = dict(blocks=len(bx), rho21=float(np.corrcoef(bx, by)[0, 1]), rho_daily=float(np.corrcoef(x, y)[0, 1]),
                       spearman21=float(sst.spearmanr(bx, by)[0]),
                       rho21_hy_stress=float(np.corrcoef(bx[stress], by[stress])[0, 1]), stress_blocks=int(stress.sum()),
                       window=[str(common[0].date()), str(common[-1].date())])
        if lab == "deployed":
            fb, _ = hac(x, y.rename("book").to_frame(), NW_L)
            out["r_book"] = dict(beta=fb.params["book"], t=fb.tvalues["book"], r2=fb.rsquared,
                                 alpha_pct=fb.params["const"] * 252 * 100, alpha_t=fb.tvalues["const"])
    wide_full = P.index.intersection(bs["WIDE"]["pnl"].index)
    xw, yw = P.reindex(wide_full), bs["WIDE"]["pnl"].reindex(wide_full)
    s5["WIDE_full_overlap"] = dict(window=[str(wide_full[0].date()), str(wide_full[-1].date())],
                                   rho21=float(np.corrcoef(block_sums(xw, 21), block_sums(yw, 21))[0, 1]))
    rho_max = max(s5["deployed"]["rho21"], s5["WIDE"]["rho21"])
    s5["rho21_max"] = rho_max
    s5["pass_"] = bool(rho_max < CORR_KILL)
    out["stage5"] = s5
    print(f"\n[STAGE 5] CORRELATION WITH THE BOOK: Pearson of non-overlapping {CORR_BLOCK}-session sums, "
          f"{s5['deployed']['window'][0]} -> {s5['deployed']['window'][1]}")
    for lab in ("deployed", "WIDE"):
        d = s5[lab]
        print(f"  {lab:<9} rho21 {d['rho21']:+.3f} ({d['blocks']} blocks); daily {d['rho_daily']:+.3f}; Spearman21 "
              f"{d['spearman21']:+.3f}; HY-stress blocks (worst quintile of 21-session HYG-IEF, {d['stress_blocks']}) "
              f"{d['rho21_hy_stress']:+.3f}")
    print(f"  WIDE over the full overlap {s5['WIDE_full_overlap']['window'][0]}..: rho21 {s5['WIDE_full_overlap']['rho21']:+.3f} (reported)")
    print(f"  R-BOOK: C4 on the deployed book's daily P&L: beta {out['r_book']['beta']:+.3f} (t {out['r_book']['t']:.2f}), "
          f"R2 {out['r_book']['r2']:.3f}")
    print(f"  -> rule the larger rho21 ({rho_max:+.3f}) < {CORR_KILL}: {'PASS' if s5['pass_'] else 'FAIL (KILL: not new breadth)'}")

    # ---------------- Stage 6: the bar
    sk, ku = float(P.skew()), float(P.kurt() + 3.0)
    dsr, sr0, emax = _dsr(row["sr"], len(P), sk, ku, N)
    s6 = dict(dsr=float(dsr), sr0=float(sr0), emax=float(emax), skew=sk, kurt=ku, T=len(P),
              sr_sqrt_years=row["sr"] * math.sqrt(len(P) / 252), pass_=bool(dsr > DSR_PASS))
    out["stage6"] = s6
    print(f"\n[STAGE 6] THE BAR: validate._dsr(obs {row['sr']:.3f}, T {len(P)}, skew {sk:+.2f}, kurt {ku:.2f}, N {N}) "
          f"= {dsr:.4f} (expected best-of-N Sharpe {sr0:.3f})  -> rule > {DSR_PASS}: "
          f"{'PASS' if s6['pass_'] else 'FAIL (NEITHER: below the bar)'}")
    print(f"  beside it: SR x sqrt(years) {s6['sr_sqrt_years']:.2f} against sqrt(2 ln N) {emax:.3f}")

    # ---------------- diagnostics: IC, family split, NAV catch-up (reported, never kills)
    pnl_ = bf.build_panel(universe=UF, source=FAM_SRC, mask=declared_mask(UF))
    z = pnl_["z"].reindex(idx)
    M = z.notna() & (pnl_["adv"].reindex(idx) >= MIN_ADV)
    F = w4.fwd(R_ret[UF], 2, 3)
    w4._assert_fit(F)
    dates = w4.grid(idx[idx >= t0], 0)
    ic = w4.ic_series(z, F, M, dates)
    fms = w4.fm_slopes(z, F, M, dates)
    out["ic"] = dict(**w4.ic_row(ic), fm_bp=float(fms.mean() * 1e4),
                     fm_t=float(fms.mean() / fms.std(ddof=1) * np.sqrt(len(fms))))
    print(f"\n[DIAGNOSTICS] IC (H6): Spearman of z_t on the forward 2-day total return (closes t+1 -> t+3), "
          f"every second session, eligible funds, min {MIN_NAMES}: mean {out['ic']['ic']:+.4f} over {out['ic']['n']} "
          f"dates, t (clustered by date) {out['ic']['t']:.2f}, NW t {out['ic']['t_nw']:.2f}; Fama-MacBeth slope "
          f"{out['ic']['fm_bp']:+.2f} bp per unit z (t {out['ic']['fm_t']:.2f})")
    fams = {}
    for g in FAMILIES:
        cols = [t for t in UF if fam[t] == g]
        icg = w4.ic_series(z[cols], F[cols], M[cols], dates, min_n=3)
        fams[g] = w4.ic_row(icg)
        print(f"  IC within {g:<20} (min 3 funds): {fams[g]['ic']:+.4f} over {fams[g]['n']} dates, t {fams[g]['t']:.2f}")
    out["ic_by_family"] = fams
    grp = {t: fam[t] for t in UF}
    zb, zw = decompose_signal(z, M, grp, "algebraic")
    pc, _ = pooled_components(zb, zw, F, M, dates)
    Bh, Wh = decompose_holdings(H, grp, "algebraic")
    pb, pw = bf.evaluate(Bh, R0)["pnl"].loc[p0:FIT_END], bf.evaluate(Wh, R0)["pnl"].loc[p0:FIT_END]
    out["family_split"] = dict(**{k: float(v) for k, v in pc.items()}, pnl_between_pct=float(pb.mean() * 252 * 100),
                               pnl_within_pct=float(pw.mean() * 252 * 100))
    print(f"  within / between FAMILY (W10-B's algebraic split): slope z {pc['slope_z']:+.2f} bp (t {pc['t_z']:.2f}); "
          f"between {pc['slope_between']:+.2f} (t {pc['t_between']:.2f}); within {pc['slope_within']:+.2f} "
          f"(t {pc['t_within']:.2f}); between's variance share {pc['var_share_between']:.1%}; P&L between "
          f"{out['family_split']['pnl_between_pct']:+.2f}%/yr, within {out['family_split']['pnl_within_pct']:+.2f}%/yr")
    navp = pnl_["nav"].reindex(idx)
    from scripts.cef.band_frontier import load_families_actions, split_factor
    dist, spl = load_families_actions(FAM_DIR / "cef_actions.parquet")
    amt = (dist[dist["ticker"].isin(UF)].groupby(["ex_date", "ticker"])["amount"].sum().unstack()
           .reindex(index=idx, columns=UF))
    full_nav = pnl_["nav"]
    rn = full_nav.pct_change(fill_method=None).reindex(idx)
    yn = (amt / full_nav.shift(1).reindex(idx)).where(amt.notna(), 0.0)   # 0 only where no ex-date
    kn = split_factor(idx, UF, splits=spl).reindex(index=idx, columns=UF)
    R_nav = (1 + rn) * kn - 1 + yn
    Fn = w4.fwd(R_nav, 2, 3)
    fmn = w4.fm_slopes(z, Fn, M, dates)
    out["nav_catchup"] = dict(fm_bp=float(fmn.mean() * 1e4), t=float(fmn.mean() / fmn.std(ddof=1) * np.sqrt(len(fmn))),
                              n=len(fmn))
    print(f"  NAV catch-up: Fama-MacBeth slope of the NAV's own total return over closes t+1 -> t+3 on z: "
          f"{out['nav_catchup']['fm_bp']:+.2f} bp per unit z (t {out['nav_catchup']['t']:.2f}; positive would mean a wide "
          f"discount predicts a falling NAV). NAV distributions are yfinance's (navp rows {int(navp.notna().sum().sum())})")

    # ---------------- robustness (reported; never chosen from; none rescues a failed headline)
    rob = [dict(row)]
    snap = U["snap68"]
    yfR = yf_total_returns(px, pool, idx)
    specs = [("R-68 (approved 68)", snap, R_ret, "M1M2", "capped", False),
             ("R-S (105 pool, shortability assumed)", pool, R_ret, "M1M2", "capped", True),
             ("R-G (no global allocation)", [t for t in UF if sub[t] != "global_allocation"], R_ret, "M1M2", "capped", False),
             ("R-Q0 (no masks)", UF, R_ret, "none", "capped", False),
             ("R-Q1 (CEFConnect-confirmed stale copies only)", UF, R_ret, "cc", "capped", False)]
    specs += [(f"leave out {g}", [t for t in UF if fam[t] != g], R_ret, "M1M2", "capped", False) for g in FAMILIES]
    for lab, L, R_, kind, pol, ext in specs:
        r_, *_ = run_book(lab, L, R_, kind=kind, policy=pol, extended=ext)
        rob.append(r_)
    for lab, R_, pol in (("R-P (CRSP retx: price returns)", R_retx, "capped"),
                         ("R-yf (yfinance-built total returns)", yfR, "capped"),
                         ("raw band (no gross cap)", R_ret, "raw")):
        r_, *_ = run_book(lab, UF, R_, policy=pol, T=T74)
        rob.append(r_)
    out["robustness"] = rob
    print("\n[ROBUSTNESS] reported, never chosen from, none of it rescues a failed headline (each from its own first held session):")
    print(f"  {'book':<46}{'univ':>5}{'fit':>5}{'from':>12}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'turn':>7}{'net@5':>7}{'net@15':>7}{'net@30':>7}{'flips?':>7}")
    for r_ in rob:
        print(f"  {r_['book']:<46}{r_['universe']:>5}{r_['funds']:>5}{r_['first_held']:>12}{r_['sr']:8.3f}{r_['ann_pct']:7.2f}{r_['vol_pct']:7.2f}"
              f"{r_['turn']:7.1f}{r_['net5']:7.3f}{r_['net15']:7.3f}{r_['net30']:7.3f}{r_['flips']:>7}")

    # capacity
    adv = pnl_["adv"].reindex(idx)[UF]
    trades = H.diff().abs().loc[t0:FIT_END]
    reb = trades.sum(axis=1) > 0
    part = (trades[reb] / adv.loc[trades[reb].index]).replace([np.inf, -np.inf], np.nan).max(axis=1)
    mmed = float(part.median())
    out["capacity"] = dict(rebalance_days=int(reb.sum()), median_max_participation_per_dollar=mmed,
                           capital_at_1pct_adv=0.01 / mmed,
                           participation={f"${c / 1e6:g}m": mmed * c for c in (1e6, 1e7, 1e8)})
    print(f"\n[CAPACITY] on {int(reb.sum())} rebalance days, the median of each day's largest single-fund trade "
          f"over that fund's 63-session ADV is {mmed:.3e} per dollar of capital: it reaches 1% of ADV at a sleeve "
          f"of ${0.01 / mmed:,.0f}; participation at $1m {mmed * 1e6:.2%}, $10m {mmed * 1e7:.2%}, $100m {mmed * 1e8:.1%}")

    # ---------------- the verdict: the first failing rule, in §12's order
    order = [("1", s1["pass_"], "KILL D1 (stage 1: NW t < 1.96)"),
             ("2", s2["pass_"], "KILL D1 (stage 2: stale-NAV artefact)"),
             ("3a", s3a["pass_"], "KILL D1 (stage 3: placebo)"),
             ("3b", s3b["pass_"], "KILL D1 (stage 3: shift(3))"),
             ("4", out["stage4"]["pass_"], "KILL D4 (stage 4: R-D4)"),
             ("5", s5["pass_"], "KILL (stage 5: correlation with the book >= 0.5, not new breadth)"),
             ("6", s6["pass_"], "NEITHER (stage 6: _dsr <= 0.95; real at most, below the bar)")]
    fails = [(s, v) for s, ok, v in order if not ok]
    out["stage_pass"] = {s: bool(ok) for s, ok, _ in order}
    out["verdict"] = fails[0][1] if fails else "FIT PASS (stages 1-6); the holdout sign rule decides"
    out["all_failing"] = [v for _, v in fails]
    print("\n" + "=" * 100)
    print(f"FIT VERDICT: {out['verdict']}")
    print("  stages: " + ", ".join(f"{s} {'pass' if ok else 'FAIL'}" for s, ok, _ in order))
    print(f"  every failing rule, in order: {out['all_failing'] or 'none'}")
    print("  the holdout is opened once, next, whatever this verdict; it can kill and never rescue")
    FIT_JSON.write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    pd.DataFrame(rob + [dict(book="C4 era " + e["era"], **{k: v for k, v in e.items() if k not in ("book", "era")})
                        for e in erows]).to_csv(FIT_TABLES, index=False)
    CACHE.mkdir(parents=True, exist_ok=True)
    P.to_frame("c4_gross_pnl").to_parquet(CACHE / f"c4_fit_pnl_{STAMP}.parquet")
    return 0


def holdout() -> int:
    _tracked_clean(FIT_JSON, FIT_OUT, DIST_TABLE)
    if not FIT_REVIEWS_CONFIRMED:
        raise GateError("holdout halted: it opens only after two independent reviews of the fit (3be92cd) "
                        "confirm it (coordinator, 2026-10-15); no holdout number has been computed")
    T = pd.read_csv(DIST_TABLE, parse_dates=["date"])
    if (T["decision"] == "UNCONFIRMED").any():
        raise GateError("holdout halted (ruling 2026-10-14): disagreeing ex-dates no third source confirms")
    raise GateError("the holdout computation is written in the commit that opens it")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=["stage0", "fit", "distributions", "holdout"])
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            buf.write(s)
            return len(s)

    fn = dict(stage0=stage0, fit=fit, distributions=distributions, holdout=holdout)[a.stage]
    with contextlib.redirect_stdout(Tee()):
        rc = fn()
    target = dict(stage0=STAGE0_OUT, fit=FIT_OUT, distributions=DIST_OUT).get(a.stage)
    if target is not None:
        target.write_text(buf.getvalue())
    return rc


if __name__ == "__main__":
    sys.exit(main())
