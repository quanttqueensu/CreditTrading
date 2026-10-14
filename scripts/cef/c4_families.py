"""Trial C4 (CEF trial 52): the live discount z-score pooled over five CEF families.

    export QUANTT_ENV_FILE=<absolute path to the env file>   # Alpaca key, read-only GET; never printed
    python3 scripts/cef/c4_families.py stage0               # zero trials: data gates + quality screen

The pre-registration is `results/cef/PREREG_C4_FAMILIES_2026-10-13.md`
(approved by the team lead 2026-10-14, CEF 50 -> 52, judged at N = 52). This
script runs it in the order of its §12. Only Stage 0 exists so far.

WHY ONLY STAGE 0
----------------
§12 says Stage 0 fails on "a gate fails, or Q1", and then "no trial spent:
fixed, or referred to the team lead". On 2026-10-14 the Q1 screen found
name-days with a price and no return in the declared source (§4.4: "raise"),
and the run-time shortability re-read (§4.1) returned a different universe
from the 68 the document and the approval name. Neither can be resolved
without a choice the document does not make, so the run stops here, before
any C4 position, P&L or statistic exists. The fit and holdout stages are built
after the ruling, from this file. Nothing below computes a C4 weight, a C4
return or any moment of one.

WHAT STAGE 0 DOES (PREREG §4.5, §12 row 0)
------------------------------------------
* DG-C4-1: CRSP `ret`/`retx` for the pool, staged by
  `scripts/data/stage_crsp_cef_families.py --returns` to a gitignored cache;
  the QQQX predecessor rule decided by its own count (§4.4).
* DG-C4-2: the harness arguments (`band_frontier.build_panel/build_targets`
  `source`, `mask`, `min_adv`; `total_returns(actions=, prices=)`); the
  default path's hash is re-checked against the one recorded before the edit.
* DG-C4-3: the factor caches and their vintages; IEF and HYG in
  `data/etf_daily.parquet`.
* DG-C4-4: the shortability re-read, one read-only `GET /v2/assets` on the
  cef paper key (no order endpoint exists in this file), printed beside the
  68 of the 2026-10-12 snapshot.
* DG-C4-5: the deployed v7 book series and the WIDE series build; the
  deployed one must reproduce W4's first position, 2013-06-21.
* The quality screen Q1-Q7 (the XASSET slate's P2) on the PRIMARY return of
  every pool fund over 2005-01-03 -> 2026-09-30 (the fixed holdout end),
  tagged by membership of each candidate universe. Q1 halts; the rest flag.
  Nothing is dropped, filled or altered.
* Eligible breadth, by era, for each candidate universe and its fresh-NAV
  sub-book: a count of the sleeve's filters with the declared masks, exactly
  as `c4_feasibility.py` counts it (no signal, no return).

THE PRIMARY RETURN (PREREG §4.4)
--------------------------------
Through 2024-12-31: CRSP `dsf.ret` on the row the price build tied to the
fund. From 2025-01-02: r = (1 + r_px) * k - 1 + D / P(t-1) on the yfinance
close, with yfinance dividends and splits from `cef_actions.parquet`, through
`band_frontier.total_returns(actions=, prices=)`. r_px is
`pct_change(fill_method=None)` with NO outlier filter and NO fill: the
harness's own `build_targets` R drops |r| >= 50% and fills NaN with 0, which
for C4 would be the silent fallback H15 forbids.

LICENSED DATA. CRSP values (returns, prices) never leave the gitignored cache
`results/cef/c4/_cache_c4/`. The committed flag table carries the fund, the
date, the check and non-CRSP context only.

ALIGNMENT (H7). Nothing here is a forecast. The Q5 median and MAD are
`.shift(1)` (252 sessions through t-1); the eligibility counts are
`c4_feasibility.eligibility`, whose history count and ADV are `.shift(1)`.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import inspect
import io
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAM_DIR = REPO / "data" / "cef_families"
OUT_DIR = REPO / "results" / "cef" / "c4"
CACHE = OUT_DIR / "_cache_c4"
CRSP_RET = CACHE / "crsp_ret_families.parquet"
FACTOR_CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
STAMP = "2026-10-14"

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


class GateError(RuntimeError):
    """A Stage 0 data gate could not clear."""


def _need(p: Path, builder: str) -> Path:
    if not p.exists():
        raise FileNotFoundError(f"{p.relative_to(REPO)} is missing; build it with `{builder}`")
    return p


# --------------------------------------------------------------------------- universe

def universes(assets: pd.DataFrame | None) -> dict:
    """The pool (105), the 2026-10-12 shortable universe (68) and the run-time re-read."""
    from scripts.cef.c4_feasibility import NAMES_CSV, declare_pool
    names = pd.read_csv(_need(NAMES_CSV, "python3 scripts/data/cef_families_quality.py"))
    pool, left_out = declare_pool(names)
    fam = names.set_index("ticker")["family"]
    shortable = set(names.loc[names["alpaca_shortable"].astype(bool), "ticker"])   # c4_feasibility's rule
    snap = sorted(t for t in pool if t in shortable)
    out = dict(names=names, fam=fam, pool=pool, left_out=left_out, snap68=snap,
               snap_read=str(names["alpaca_read_utc"].dropna().iloc[0]))
    if assets is not None:
        a = assets.set_index("symbol")
        absent = [t for t in pool if t not in a.index]
        out["absent"] = absent
        out["runtime"] = sorted(t for t in pool if t in a.index
                                and bool(a.loc[t, "tradable"]) and bool(a.loc[t, "shortable"]))
        out["runtime_etb"] = {t: bool(a.loc[t, "easy_to_borrow"]) if a.loc[t, "easy_to_borrow"] is not None
                              else None for t in out["runtime"]}
    return out


def read_assets() -> tuple[pd.DataFrame, str]:
    """DG-C4-4: one read-only GET /v2/assets (cef paper key). Raw rows cached, never committed."""
    from quantt.broker.alpaca import AlpacaClient
    c = AlpacaClient.from_environment("cef")
    rows = c.assets(status="active", asset_class="us_equity")
    t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"alpaca_assets_{t.replace(':', '')}.json").write_text(json.dumps({"read_utc": t, "rows": rows}))
    return pd.DataFrame(rows), t


# --------------------------------------------------------------------------- panels

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


def primary_returns(pool, px, crsp, qr) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """(primary return, the yfinance-built total return, sessions). Sessions are the families
    price panel's dates for the pool from SAMPLE_START to HOLDOUT_END."""
    from scripts.cef.band_frontier import total_returns
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    sess = close.index[(close.index >= SAMPLE_START) & (close.index <= HOLDOUT_END)]
    c = crsp
    if not qr["use_predecessor"]:
        c = c[~((c["ticker"] == "QQQX") & (c["permno"] == QQQX_PRED_PERMNO))]
    cr = c.pivot_table(index="date", columns="ticker", values="ret").reindex(index=sess, columns=pool)
    rpx = close.pct_change(fill_method=None).reindex(index=sess, columns=pool)    # no filter, no fill
    yf_tr = total_returns(rpx, actions=FAM_DIR / "cef_actions.parquet", prices=FAM_DIR / "cef_prices.parquet")
    prim = pd.concat([cr.loc[:CRSP_END], yf_tr.loc[YF_START:]])
    if not prim.index.equals(sess):
        raise GateError("the CRSP and yfinance legs do not tile the session index at the seam")
    return prim, yf_tr, sess


# --------------------------------------------------------------------------- quality screen

def _runs(eq: pd.Series, min_len: int) -> list[tuple]:
    """(first, last, length) of runs of True of at least `min_len` sessions."""
    out, start, n = [], None, 0
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
    """Q1-Q7 by fund and date. Returns one row per flag; CRSP values in `crsp_*` columns
    (cache only), everything else committable."""
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    yvol = px.pivot_table(index="date", columns="ticker", values="volume").sort_index()
    cpr = crsp.pivot_table(index="date", columns="ticker", values="prc")
    cvol = crsp.pivot_table(index="date", columns="ticker", values="vol")
    rows = []
    for t in pool:
        s = close[t].dropna()
        first, last = s.index.min(), s.index.max()
        w = sess[(sess > max(first, SAMPLE_START - pd.Timedelta(days=1))) & (sess <= last)]
        w = w[w > first]                                   # the first price has no return by construction
        r = prim[t].reindex(w)
        # Q1: a session inside the fund's live range with no primary return (H15) -> halt
        for d in r.index[r.isna()]:
            src = "CRSP" if d <= CRSP_END else "yfinance"
            why = ("no yfinance close" if pd.isna(close[t].get(d)) else
                   ("no CRSP row" if d <= CRSP_END and pd.isna(cpr.get(t, pd.Series(dtype=float)).get(d))
                    else "return undefined"))
            rows.append(dict(check="Q1", ticker=t, date=d, source=src, detail=why))
        # Q2: >= 3 consecutive sessions with an unchanged raw close (CRSP prc to 2024, yfinance after)
        rc = pd.concat([cpr.get(t, pd.Series(dtype=float)).reindex(w[w <= CRSP_END]).where(lambda x: x > 0),
                        close[t].reindex(w[w > CRSP_END])])
        eq = rc.eq(rc.shift(1)) & rc.notna()
        for a, b, n in _runs(eq, Q2_RUN - 1):      # n equalities = n + 1 sessions at one close
            a0 = rc.index[rc.index.get_loc(a) - 1]   # the run's first session is the one before the first equality
            rows.append(dict(check="Q2", ticker=t, date=a0, date_end=b, source="CRSP" if b <= CRSP_END else "yfinance",
                             detail=f"close unchanged for {n + 1} sessions"))
        # Q3: zero volume
        v = pd.concat([cvol.get(t, pd.Series(dtype=float)).reindex(w[w <= CRSP_END]),
                       yvol[t].reindex(w[w > CRSP_END])])
        for d in v.index[v.eq(0)]:
            rows.append(dict(check="Q3", ticker=t, date=d, source="CRSP" if d <= CRSP_END else "yfinance",
                             detail="zero volume"))
        yz = yvol[t].reindex(w)
        for d in yz.index[yz.eq(0)]:
            rows.append(dict(check="Q3", ticker=t, date=d, source="yfinance", detail="zero volume (yfinance bar; M2)"))
        # Q4: CRSP prc < 0 (no closing trade) on an eligible fund-day
        if t in elig.columns:
            p4 = cpr.get(t, pd.Series(dtype=float)).reindex(w[w <= CRSP_END])
            e4 = elig[t].reindex(p4.index).fillna(False).astype(bool)
            for d in p4.index[(p4 < 0) & e4]:
                rows.append(dict(check="Q4", ticker=t, date=d, source="CRSP", detail="no closing trade on an eligible fund-day"))
        # Q5: robust z > 10 over the 252 sessions through t-1, or |r| > 15%
        # the full 252 sessions through t-1, as P2 states it; |r| > 15% screens a fund's first year
        med = r.rolling(Q5_WIN, min_periods=Q5_WIN).median().shift(1)
        mad = (r - med).abs().rolling(Q5_WIN, min_periods=Q5_WIN).median().shift(1)
        z = (r - med).abs() / (1.4826 * mad.replace(0, np.nan))
        for d in r.index[(z > Q5_Z) | (r.abs() > Q5_ABS)]:
            rows.append(dict(check="Q5", ticker=t, date=d, source="CRSP" if d <= CRSP_END else "yfinance",
                             detail=f"|r|>{Q5_ABS:.0%}" if abs(r[d]) > Q5_ABS else f"robust z>{Q5_Z:g}",
                             value=float(r[d]) if d > CRSP_END else np.nan,
                             crsp_value=float(r[d]) if d <= CRSP_END else np.nan))
        # Q6: yfinance-built total return against CRSP, 2013-2024, > 5bp
        c6 = prim[t].reindex(w[(w >= Q6_START) & (w <= CRSP_END)])
        y6 = yf_tr[t].reindex(c6.index)
        d6 = (y6 - c6).abs() * 1e4
        for d in d6.index[d6 > Q6_BP]:
            rows.append(dict(check="Q6", ticker=t, date=d, source="CRSP vs yfinance",
                             detail=f"|diff| {d6[d]:.1f}bp", value=float(y6[d]), crsp_value=float(c6[d])))
        both_nan = c6.notna() & y6.isna()
        for d in both_nan.index[both_nan]:
            rows.append(dict(check="Q6", ticker=t, date=d, source="CRSP vs yfinance",
                             detail="yfinance-built return missing", crsp_value=float(c6[d])))
        # Q7: the seam
        for d in SEAM:
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


# --------------------------------------------------------------------------- the deployed book (DG-C4-5)

def book_series() -> dict:
    """The deployed v7 series and the WIDE series (zero-trial; no statistic printed)."""
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
        out[lab] = dict(first=first, span=(pnl.index.min(), pnl.index.max()), n=len(pnl))
    return out


# --------------------------------------------------------------------------- stage 0

def stage0(skip_alpaca: bool = False) -> int:
    from scripts.cef import band_frontier as bf
    from scripts.cef.c4_feasibility import (FRESH_NAV_FAMILIES, eligibility, era_rows, first_active,
                                            repeat_mask)
    from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES, Z_WINDOW, summary
    halts, notes = [], []

    # DG-C4-2 first, in a fresh process, before anything else builds a frame (hash protocol)
    h = hashlib.sha256(pickle.dumps(bf.build_targets())).hexdigest()
    sig = {f: list(inspect.signature(getattr(bf, f)).parameters)
           for f in ("build_panel", "build_targets", "total_returns")}
    print(summary())
    print(f"C4 STAGE 0 (zero trials), run {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC; "
          f"holdout end fixed at {HOLDOUT_END.date()}")
    print("\n[DG-C4-2] harness arguments:", sig)
    print(f"  sha256(pickle.dumps(build_targets())) first call: {h}")
    print(f"  recorded on the unmodified harness (9d1d9ab):       {NOOP_SHA_PRE_EDIT}")
    if h != NOOP_SHA_PRE_EDIT:
        halts.append("DG-C4-2: default-path hash differs from the pre-edit hash (re-prove the no-op)")
    print("  ->", "PASS (byte-for-byte no-op on the default path)" if h == NOOP_SHA_PRE_EDIT else "FAIL")

    # DG-C4-4: universe re-read
    assets, read_t = (None, None) if skip_alpaca else read_assets()
    U = universes(assets)
    pool, fam = U["pool"], U["fam"]
    print(f"\n[DG-C4-4] pool {len(pool)} funds; shortable on the {U['snap_read']} snapshot: {len(U['snap68'])}")
    if assets is None:
        halts.append("DG-C4-4: shortability not re-read (--skip-alpaca)")
    else:
        rt = U["runtime"]
        print(f"  re-read GET /v2/assets (cef paper key, read-only) at {read_t}: {len(assets)} active assets; "
              f"pool funds absent {U['absent']}; shortable and tradable now: {len(rt)} "
              f"(easy_to_borrow {sum(1 for v in U['runtime_etb'].values() if v)})")
        lost, gained = sorted(set(U["snap68"]) - set(rt)), sorted(set(rt) - set(U["snap68"]))
        print(f"  beside the 68: in both {len(set(rt) & set(U['snap68']))}; no longer shortable {lost}; "
              f"newly shortable {gained}")
        for lab, L in (("68 (2026-10-12)", U["snap68"]), (f"{len(rt)} (re-read)", rt)):
            print(f"  {lab} by family: {fam.reindex(L).value_counts().to_dict()}; fresh-NAV sub-book "
                  f"{sum(fam[t] in FRESH_NAV_FAMILIES for t in L)}")
        if set(rt) != set(U["snap68"]):
            notes.append(f"universe: the re-read gives {len(rt)} funds, the document and approval name 68 "
                         f"(in both {len(set(rt) & set(U['snap68']))}); which list is the universe is the "
                         "team lead's ruling (QUESTION 2)")
        pd.DataFrame({"ticker": pool, "family": [fam[t] for t in pool],
                      "shortable_2026_10_12": [t in U["snap68"] for t in pool],
                      "shortable_rerun": [t in rt for t in pool],
                      "rerun_read_utc": read_t}).to_csv(OUT_DIR / f"c4_universe_{STAMP}.csv", index=False)

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
        halts.append("DG-C4-3: a factor series does not cover the fit window")
    print("  -> fit window covered;", f"daily factors end {ff.date.max().date()} (the library's lag), "
          "holdout regressions (reported only) run to that date")

    # DG-C4-5
    bs = book_series()
    for lab, b in bs.items():
        print(f"\n[DG-C4-5] {lab} v7 book series builds: first position {b['first'].date()}, P&L rows "
              f"{b['span'][0].date()}..{b['span'][1].date()} ({b['n']}); live panel (no statistic computed here)")
    if bs["deployed"]["first"] != DEPLOYED_FIRST:
        halts.append(f"DG-C4-5: deployed first position {bs['deployed']['first'].date()} != {DEPLOYED_FIRST.date()}")

    # eligibility (counts only) and the declared masks
    nav = nav.assign(repeat=repeat_mask(nav))
    E = eligibility(px, nav, MIN_ADV_USD, Z_WINDOW)
    elig = E["elig"]
    print(f"\n[ELIGIBILITY] counts of the sleeve's filters with M1 (NAV repeat) and M2 (zero volume), "
          f"floor ${MIN_ADV_USD:,.0f}, min_names {MIN_NAMES} (no signal, no return)")
    cands = [("68 (2026-10-12)", U["snap68"])]
    if "runtime" in U:
        both = sorted(set(U["snap68"]) & set(U["runtime"]))
        cands += [(f"{len(U['runtime'])} (re-read)", U["runtime"]),
                  (f"{len(both)} (shortable on both reads; reported, not declared)", both)]
    erows = []
    for lab, L in cands:
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

    # the quality screen
    prim, yf_tr, sess = primary_returns(pool, px, crsp, qr)
    flags = quality_screen(pool, px, nav, crsp, prim, yf_tr, sess, elig, qr)
    mem = {"in_68": set(U["snap68"]), "in_rerun": set(U.get("runtime", [])), "in_pool": set(pool)}
    for k, s in mem.items():
        flags[k] = flags["ticker"].isin(s)
    CACHE.mkdir(parents=True, exist_ok=True)
    flags.to_parquet(CACHE / f"c4_stage0_flags_with_values_{STAMP}.parquet", index=False)  # licensed values
    pub = flags.drop(columns=["crsp_value"]).copy()
    pub.loc[pub["date"] <= CRSP_END, "value"] = np.nan          # nothing derived from CRSP leaves the cache
    pub.loc[(pub["check"] == "Q6") & pub["detail"].str.startswith("|diff|"), "detail"] = f"|diff| > {Q6_BP:g}bp"
    pub.to_csv(OUT_DIR / f"c4_stage0_flags_{STAMP}.csv", index=False)
    print(f"\n[QUALITY SCREEN] primary return of the {len(pool)} pool funds, {sess[0].date()}..{sess[-1].date()} "
          f"({len(sess)} sessions); flags by check and universe:")
    tab = flags.groupby("check").agg(flags=("ticker", "size"), funds=("ticker", "nunique"),
                                     in_68=("in_68", "sum"), in_rerun=("in_rerun", "sum"))
    print(tab.to_string())
    q1 = flags[flags["check"] == "Q1"].sort_values(["ticker", "date"])
    print("\n  Q1 (halt) in full:")
    print(q1[["ticker", "date", "source", "detail", "in_68", "in_rerun"]].to_string(index=False))
    q1u = q1[q1["in_68"] | q1["in_rerun"]]
    print("\n  eligibility of each Q1 fund (declared filters and masks; counts, no signal) around its gap:")
    for t, g in q1u.groupby("ticker"):
        e = elig[t] if t in elig.columns else pd.Series(dtype=bool)
        fe = e.index[e.fillna(False).astype(bool)].min() if e.fillna(False).any() else None
        lo, hi = g["date"].min(), g["date"].max()
        win = e.loc[lo - pd.Timedelta(days=10):hi + pd.Timedelta(days=10)]
        eb = e.loc[:lo - pd.Timedelta(days=1)].fillna(False).astype(bool)
        le = eb.index[eb].max() if eb.any() else None
        print(f"    {t}: gap {lo.date()}..{hi.date()} ({len(g)} name-days); first eligible session "
              f"{fe.date() if fe is not None else 'never'}; last eligible before the gap "
              f"{le.date() if le is not None else 'none'}; eligible on {int(win.fillna(False).sum())} of "
              f"{len(win)} sessions within 10 days of the gap. A fund never eligible before its gap has a "
              "zero target and cannot be held; one eligible earlier may still hold a residual band position "
              "(that needs the holdings path, which Stage 0 does not compute)")
    print("\n  Q1 context (yfinance and CEFConnect values; CRSP shown only as present / absent):")
    cc = pd.read_parquet(_need(FAM_DIR / "cef_nav_cefconnect.parquet",
                               "scripts/data/fetch_cef_families_cefconnect.py"))
    cc["date"] = pd.to_datetime(cc["date"])
    acts = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
    acts["date"] = pd.to_datetime(acts["date"])
    for t, g in q1u.groupby("ticker"):
        lo, hi = g["date"].min(), g["date"].max()
        ix = sess[(sess >= lo - pd.Timedelta(days=12)) & (sess <= hi + pd.Timedelta(days=5))]
        y = px[px["ticker"] == t].set_index("date").reindex(ix)
        n_ = nav[nav["ticker"] == t].set_index("date")["nav"].reindex(ix)
        c_ = cc[(cc["ticker"] == t)].drop_duplicates("date").set_index("date").reindex(ix)
        k_ = crsp[crsp["ticker"] == t].set_index("date").reindex(ix)
        a_ = acts[(acts["ticker"] == t) & acts["date"].between(ix[0], ix[-1])
                  & ((acts["stock_splits"] != 0) | (acts["dividends"] > 0))]
        ctx = pd.DataFrame({"yf_close": y["close"], "yf_volume": y["volume"], "yf_nav": n_,
                            "cc_close": c_["close_cc"], "cc_nav": c_["nav"],
                            "crsp_row": k_["permno"].map(lambda v: "no" if pd.isna(v) else f"permno {int(v)}"),
                            "crsp_ret": k_["ret"].map(lambda v: "NaN" if pd.isna(v) else "present")})
        print(f"    {t}  (yfinance actions in the window: "
              f"{a_[['date', 'dividends', 'stock_splits']].to_dict('records') or 'none'})")
        print("      " + ctx.to_string().replace("\n", "\n      "))
    if len(q1u):
        halts.append(f"Q1: {len(q1u)} name-days in a candidate universe with no primary return inside the "
                     f"fund's price span ({', '.join(sorted(q1u['ticker'].unique()))}); §4.4 says raise, "
                     "§12 says halt (QUESTION 1)")
    q1o = q1[~(q1["in_68"] | q1["in_rerun"])]
    if len(q1o):
        notes.append(f"Q1 also hits {', '.join(sorted(q1o['ticker'].unique()))}, in the 105-fund pool only "
                     "(robustness row R-S)")
    for c in ("Q2", "Q3", "Q4", "Q5", "Q6", "Q7"):
        x = flags[(flags["check"] == c) & (flags["in_68"] | flags["in_rerun"])]
        if len(x):
            by = x.groupby("ticker").size().sort_values(ascending=False)
            print(f"  {c}: {len(x)} flags on {x['ticker'].nunique()} candidate-universe funds; most: "
                  f"{by.head(8).to_dict()}")

    print("\n" + "=" * 100)
    if halts:
        print("STAGE 0: HALT. No C4 weight, return or statistic was computed. Referred to the team lead:")
        for i, x in enumerate(halts, 1):
            print(f"  {i}. {x}")
    else:
        print("STAGE 0: every gate clear, Q1 clean.")
    for x in notes:
        print(f"  note: {x}")
    return 1 if halts else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=["stage0"])
    ap.add_argument("--skip-alpaca", action="store_true", help="do not re-read shortability (the gate then fails)")
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            buf.write(s)
            return len(s)

    with contextlib.redirect_stdout(Tee()):
        rc = stage0(skip_alpaca=a.skip_alpaca)
    (OUT_DIR / f"c4_stage0_output_{STAMP}.txt").write_text(buf.getvalue())
    return rc


if __name__ == "__main__":
    sys.exit(main())
