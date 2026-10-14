"""Zero-trial feasibility for trial E2 (convertible-issuance reversal).

    export QUANTT_ENV_FILE=<absolute path to the env file holding the R2 keys>
    python3 scripts/events/e2_feasibility.py          # event caches from convert_issuance.py;
                                                       # one R2 pull of CRSP price x volume (cached)

WHAT THIS IS FOR
----------------
`results/events/PREREG_E2_CONVERT_REVERSAL_2026-10-13.md` (a DRAFT awaiting the
team lead) fixes E2's event set, filters, hedge, sizing and pass bar before
the trial runs. This script measures what that declaration needs, and nothing
that is a return:

* events per year, 2011 to 2024, on `convert_issuance.py`'s own event rule
  (spec A, and spec B: one event per issuer-day), for the convert sample and
  the straight-debt control, including the 2023-24 time holdout (counts of
  dates and identities, never of returns);
* how many events clear the spec's liquidity floor (`min_adv_usd`, read
  through scripts/cef/spec.py) on CRSP |prc| x vol over the 63 sessions
  through the session before day 0 -- a level, not a return;
* the Alpaca flags (2026-10-12 snapshot, cef paper key) of the holdout
  issuers and of SPY, the hedge: tradable, shortable, easy to borrow;
* arithmetic on the bar and on figures ALREADY PUBLISHED in
  `results/events/REPRO_CORP_EVENTS_2026-10-11.md` [V there]: the per-event
  dispersion they imply, the power of the declared holdout rule at the
  holdout's counted size, and the Sharpe `validate._dsr` needs at the EVENTS
  counter's N.

WHAT IT DOES NOT DO (zero trials)
---------------------------------
It reads no CRSP `ret` at all (the event study's cached returns are not
opened), computes no abnormal return, no window sum and no P&L. The CRSP pull
is `prc` and `vol` only, for event issuers, through 2024-12-31; prices and
volumes are levels, which the families data note and the XASSET slate also
counted through the holdout.

ALIGNMENT (H7): the ADV for an event is the mean of |prc| x vol over the 63
CRSP sessions ending the session BEFORE day 0 (at least 21 present), as the
sleeve's `adv` is `.shift(1)`. Day 0 is the first CRSP session on or after the
first 144A trade (convert_issuance.add_windows).

ENVIRONMENT: `compute.use_numexpr` off, as every script in scripts/events/
(scripts/events/numexpr_fault.py).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("compute.use_numexpr", False)

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.events import convert_issuance as ci  # noqa: E402

CACHE = ci.CACHE
OUT_DIR = REPO / "results" / "events"
STAMP = "2026-10-13"
ALPACA_ASSETS = REPO / "data" / "cef_families" / "raw" / "alpaca_assets_active_2026-10-12.json"
FIT_START, FIT_END = pd.Timestamp("2011-01-01"), pd.Timestamp("2022-10-31")   # ci.D0_START/D0_END
HO_START, CRSP_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")
ADV_DAYS, ADV_MIN = 63, 21
PX_START = "2010-06-01"            # 63 sessions before the first fit day 0, with room

# Figures published in results/events/REPRO_CORP_EVENTS_2026-10-11.md §1-§2 and its run
# log results/events/convert_issuance_2026-10-11.txt [V there], used here only as inputs
# to power arithmetic. [+2,+5], market-adjusted. Spec B is E2's primary event set.
PUB = dict(n=755, mean_pct=0.54, t_plain=2.56, t_week=2.24, t_ct=2.58, t_ct_nw=2.45,
           n_b=696, mean_b_pct=0.54, t_plain_b=2.39, t_week_b=2.10,
           n_ctrl_b=1574, mean_ctrl_b_pct=-0.17, t_plain_ctrl_b=-1.25, t_week_ctrl_b=-1.12,
           era_2015_19_pct=0.14)


def last_holdout_d0(crsp_end: pd.Timestamp = CRSP_END, hi: int = 5) -> pd.Timestamp:
    """The latest calendar day whose day 0 still has day +hi inside CRSP.

    Day 0 is the first NYSE session on or after d0; day +hi must be a session
    on or before `crsp_end`."""
    from ops.schedule.nyse_calendar import is_trading_day, previous_trading_day
    d = crsp_end.date()
    while not is_trading_day(d):
        d = previous_trading_day(d)
    for _ in range(hi):
        d = previous_trading_day(d)
    return pd.Timestamp(d)


def per_year(m: pd.DataFrame) -> pd.Series:
    return m.groupby(m["d0"].dt.year).size()


def spec_b(m: pd.DataFrame) -> pd.DataFrame:
    """One event per (CUSIP6, day 0): convert_issuance.collapse_issuer's grouping,
    applied to the event table before windows (identities only)."""
    return m.drop_duplicates(["c6", "d0"])


def adv_before(events: pd.DataFrame, pv: pd.DataFrame) -> pd.Series:
    """ADV through the session before day 0, per event row. NaN if fewer than
    ADV_MIN of the 63 sessions have a price and volume (liquidity UNMEASURED,
    counted separately, never a pass)."""
    pv = pv.copy()
    pv["date"] = pd.to_datetime(pv["date"])
    pv["dv"] = pv["prc"].abs() * pv["vol"]
    out = {}
    for p, g in pv.groupby("permno"):
        s = g.set_index("date")["dv"].sort_index()
        out[p] = s.rolling(ADV_DAYS, min_periods=ADV_MIN).mean().shift(1)
    res = []
    for e in events.itertuples(index=False):
        s = out.get(e.permno)
        if s is None or s.empty:
            res.append(np.nan)
            continue
        i = int(s.index.searchsorted(e.d0, side="left"))       # day 0 = first CRSP row on/after d0
        res.append(float(s.iloc[i]) if i < len(s) else np.nan)  # shift(1): through day -1
    return pd.Series(res, index=events.index)


def pull_px_vol(permnos, refresh: bool) -> pd.DataFrame:
    """CRSP |prc| and vol for the event issuers, PX_START..2024-12-31. No `ret`."""
    want = pd.DataFrame({"permno": sorted(set(int(x) for x in permnos))})
    req = CACHE / "crsp_pxvol_request.parquet"
    p = CACHE / "crsp_pxvol.parquet"
    if not refresh and p.exists() and req.exists() and pd.read_parquet(req)["permno"].equals(want["permno"]):
        return pd.read_parquet(p)
    from src.data import r2
    con = r2.connect()
    con.register("pp", want)
    df = r2.q(con, f"""
        SELECT d.permno, d.date, CAST(d.prc AS DOUBLE) AS prc, CAST(d.vol AS DOUBLE) AS vol
        FROM read_parquet('{r2.r2_path("crsp_a_stock", "dsf")}') d JOIN pp USING (permno)
        WHERE d.date BETWEEN DATE '{PX_START}' AND DATE '{CRSP_END.date()}'
          AND d.prc IS NOT NULL AND d.vol IS NOT NULL""")
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    want.to_parquet(req, index=False)
    return df


def alpaca_flags(tickers) -> pd.DataFrame:
    a = json.loads(ALPACA_ASSETS.read_text())
    meta, rows = a["meta"], {r["symbol"]: r for r in a["data"]}
    out = []
    for t in tickers:
        r = rows.get(t)
        out.append(dict(ticker=t, listed=r is not None,
                        tradable=bool(r and r["tradable"]), shortable=bool(r and r["shortable"]),
                        easy_to_borrow=bool(r and r["easy_to_borrow"])))
    df = pd.DataFrame(out)
    df.attrs["read_utc"] = meta["received_utc"]
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="re-pull the CRSP price x volume")
    args = ap.parse_args(argv)
    from statistics import NormalDist
    from scripts.cef.spec import MIN_ADV_USD, summary
    from scripts.xasset.slate_feasibility import power, required_sharpe
    assert (FIT_START, FIT_END) == (ci.D0_START, ci.D0_END)
    pd.set_option("display.width", 200)
    print(summary())
    ho_end = last_holdout_d0()
    print(f"floor min_adv_usd {MIN_ADV_USD:,.0f} (scripts/cef/spec.py); holdout day 0 "
          f"{HO_START.date()}..{ho_end.date()} (day +5 inside CRSP, which ends {CRSP_END.date()})")

    # [1] events: identities and dates only
    ev = {}
    for flag, lab in (("Y", "convert"), ("N", "straight-debt control")):
        m = ci.build_events(flag, refresh=False, d0_start=FIT_START, d0_end=ho_end)
        m["era"] = np.where(m["d0"] >= HO_START, "holdout 2023-24",
                            np.where(m["d0"] <= FIT_END, "fit 2011-22", "gap 2022-11..12"))
        ev[flag] = m
        A, B = per_year(m), per_year(spec_b(m))
        print(f"\n[1] {lab}: matched events (before return windows), spec A / spec B by year")
        print(pd.DataFrame({"spec_A": A, "spec_B": B}).T.to_string())
        for era in ("fit 2011-22", "gap 2022-11..12", "holdout 2023-24"):
            x = m[m["era"] == era]
            wk = x["d0"].dt.to_period("W-FRI").nunique()
            print(f"    {era:<16} spec A {len(x):>5}  spec B {len(spec_b(x)):>5}  "
                  f"issuers {x['permno'].nunique():>4}  weeks with an event {wk:>4}")

    # [2] the liquidity floor (levels; no returns)
    allp = pd.concat([ev["Y"]["permno"], ev["N"]["permno"]]).unique()
    pv = pull_px_vol(allp, args.refresh)
    print(f"\n[2] CRSP |prc| x vol pulled for {len(allp)} issuers: {pd.to_datetime(pv['date']).min().date()}"
          f" .. {pd.to_datetime(pv['date']).max().date()} (no `ret` read)")
    rows = []
    for flag, lab in (("Y", "convert"), ("N", "control")):
        m = spec_b(ev[flag]).copy()
        m["adv"] = adv_before(m, pv)
        for era in ("fit 2011-22", "holdout 2023-24"):
            x = m[m["era"] == era]
            ok = x["adv"] >= MIN_ADV_USD
            rows.append(dict(sample=lab, era=era, events_B=len(x), adv_unmeasured=int(x["adv"].isna().sum()),
                             clear_floor=int(ok.sum()), share=float(ok.mean()),
                             median_adv_musd=float(x["adv"].median() / 1e6)))
        if flag == "Y":
            ev["Y_B"] = m
    L = pd.DataFrame(rows)
    print(L.round(3).to_string(index=False))
    L.to_csv(OUT_DIR / f"e2_feasibility_counts_{STAMP}.csv", index=False)
    yb = ev["Y_B"]
    liq = yb[yb["adv"] >= MIN_ADV_USD]
    print("    convert spec B clearing the floor, by year:", per_year(liq).to_dict())

    # [3] Alpaca, 2026-10-12 snapshot: the hedge and the holdout issuers
    ho = liq[liq["era"] == "holdout 2023-24"]
    fl = alpaca_flags(sorted(set(ho["ticker"].dropna())))
    spy = alpaca_flags(["SPY"]).iloc[0]
    print(f"\n[3] Alpaca active assets read {fl.attrs['read_utc']} (paper, cef key; true on that date only)")
    print(f"    SPY: tradable {spy.tradable}, shortable {spy.shortable}, easy_to_borrow {spy.easy_to_borrow}")
    print(f"    holdout convert issuers clearing the floor, by CRSP ticker at day 0: {len(fl)}; "
          f"listed {int(fl.listed.sum())}, tradable {int(fl.tradable.sum())}, shortable "
          f"{int(fl.shortable.sum())}, easy to borrow {int(fl.easy_to_borrow.sum())}")

    # [4] arithmetic on published figures and the bar
    def sd_deff(mean, n, t_plain, t_week):
        """Per-event sd (= |mean| x sqrt(n) / |plain t|) and the week-cluster design effect."""
        return abs(mean) * math.sqrt(n) / abs(t_plain), (t_plain / t_week) ** 2
    sd, deff = sd_deff(PUB["mean_b_pct"], PUB["n_b"], PUB["t_plain_b"], PUB["t_week_b"])
    sdc, deffc = sd_deff(PUB["mean_ctrl_b_pct"], PUB["n_ctrl_b"], PUB["t_plain_ctrl_b"], PUB["t_week_ctrl_b"])
    print(f"\n[4] from REPRO_CORP_EVENTS (spec B, fit): per-event sd of CAR[+2,+5] {sd:.2f}% convert, "
          f"{sdc:.2f}% control (= |mean| x sqrt(n) / plain t); week-cluster design effects {deff:.2f}, {deffc:.2f}")
    n_ho = len(ho)
    hoc = L[(L["sample"] == "control") & (L["era"] == "holdout 2023-24")]["clear_floor"].iloc[0]
    se_ho = sd / math.sqrt(n_ho) * math.sqrt(deff)
    se_hc = sdc / math.sqrt(hoc) * math.sqrt(deffc)
    se_d = math.sqrt(se_ho ** 2 + se_hc ** 2)
    print(f"    holdout (spec B, liquid): convert n {n_ho}, clustered SE of the mean ~ {se_ho:.3f}%; "
          f"control n {hoc}, SE ~ {se_hc:.3f}%; SE of the difference ~ {se_d:.3f}% (independence assumed)")
    for lab, mu in (("the fit's", PUB["mean_b_pct"]), ("half the fit's", PUB["mean_b_pct"] / 2),
                    ("the 2015-19 era's", PUB["era_2015_19_pct"])):
        z = mu / se_ho
        print(f"      true convert mean {mu:.2f}% ({lab}): P(holdout mean > 0) {NormalDist().cdf(z):.3f}; "
              f"P(t >= 1.645) {NormalDist().cdf(z - 1.645):.3f}; P(t >= 2) {NormalDist().cdf(z - 2.0):.3f}")
    for lab, d in (("the fit's +0.71%", PUB["mean_b_pct"] - PUB["mean_ctrl_b_pct"]),
                   ("2020-22's +0.17%", 0.17)):
        print(f"      true convert - control {d:.2f}% ({lab}): P(holdout difference > 0) "
              f"{NormalDist().cdf(d / se_d):.3f}")
    from ops.schedule.nyse_calendar import is_trading_day
    fit_days = sum(1 for d in pd.bdate_range(FIT_START, "2022-12-30") if is_trading_day(d))
    yrs = fit_days / 252
    sr_ct = PUB["t_ct_nw"] / math.sqrt(yrs)
    print(f"    fit sessions {FIT_START.date()}..2022-12-30: {fit_days} ({yrs:.1f} yr). The calendar-time "
          f"portfolio's NW t {PUB['t_ct_nw']} implies an annual SR ~ {sr_ct:.2f} over them (in sample: "
          "these windows were already examined)")
    print(f"{'N':>4}{'req SR':>8}{'P(pass|SR=' + format(sr_ct, '.2f') + ')':>18}{'P(pass|0.5x)':>14}")
    for N in (1, 2, 3, 4):
        print(f"{N:>4}{required_sharpe(N, fit_days):>8.3f}{power(sr_ct, N, fit_days):>18.3f}"
              f"{power(sr_ct / 2, N, fit_days):>14.3f}")
    print(f"    D4 alpha t >= 3.0 at a true t of {PUB['t_ct_nw']}: P ~ {NormalDist().cdf(PUB['t_ct_nw'] - 3.0):.3f}")
    print("\nzero trials: no CRSP `ret`, abnormal return, window sum or P&L was read or computed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
