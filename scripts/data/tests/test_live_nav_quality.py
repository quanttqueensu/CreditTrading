"""The pure methods behind results/cef/LIVE_NAV_QUALITY_2026-10-12.md (scripts/data/live_nav_quality.py).

WHY THESE TESTS
---------------
The note's figures rest on four small functions, each of which could be
quietly wrong without raising: the row classifier (a stale copy must be named
as one, and a float32-stored 10.979999542 must still equal a quoted 10.98);
the implied-NAV inversion that says which NAV a live session used from the z it
printed; the tie-break regression that says which source is right on a stale
copy; and the write guard that keeps the cache out of the live `data/cef/`.

Synthetic frames only: these test the code, not the market. No network (the
root conftest blocks it). Each test marked "Broken variant checked" was run
against that variant on 2026-10-12 and failed, before it was kept.

Added 2026-10-13, after an independent review: the live-period verdict logic
(`nav_verdict`, and `live_period` end to end, which must rebuild mu and sd from
the panel the session traded on, empty bars included); `lag_unrepeated` (a
stale copy that is not a repeat); and `crsp_disagreement_summary` (no tracked
output may let CRSP's licensed price be recovered). Their broken variants were
run on 2026-10-13 and failed before the tests were kept.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data import live_nav_quality as L


def _daily(values, start="2024-01-01", tk="AAA"):
    d = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({"ticker": tk, "date": d, "nav": np.asarray(values, dtype=float)})


def test_classify_names_a_stale_copy_and_its_lagged_subset():
    # Broken variant checked: dropping the `repeat` rung labels both rows OTHER / SHIFT_NEXT.
    a = _daily([10.00, 10.10, 10.10, 10.30, 10.30, 10.40])        # rows 2 and 4 repeat their previous row
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [10.00, 10.10, 10.20, 10.30, 10.35, 10.40]       # cc moved on both repeat days
    m = L.classify(a, "nav", b, "nav_cc").set_index("date")["category"]
    assert list(m.values) == ["AGREE", "AGREE", "STALE_COPY", "AGREE", "STALE_COPY", "AGREE"]
    lag = L.classify(a, "nav", b, "nav_cc").set_index("date")["lagged"]
    assert not lag.iloc[2] and not lag.iloc[4]                     # 10.20 / 10.35 never appear in a


def test_classify_lagged_when_cc_equals_the_next_yfinance_row():
    a = _daily([10.0, 10.1, 10.1, 10.2])
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [10.0, 10.1, 10.2, 10.2]                         # yfinance one day late on row 2
    m = L.classify(a, "nav", b, "nav_cc")
    assert m["category"].iloc[2] == "STALE_COPY" and bool(m["lagged"].iloc[2])


def test_classify_float32_noise_is_agreement_not_a_defect():
    # Broken variant checked: FLOAT_EPS = 0 makes the 0.0050000x row a disagreement.
    a = _daily([12.5600004196167, 15.955, 10.0])
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [12.56, 15.96, 10.0]
    assert (L.classify(a, "nav", b, "nav_cc")["category"] == "AGREE").all()


def test_classify_shift_prev_and_next_and_basis():
    a = _daily([10.0, 10.1, 10.2, 10.3, 10.4])
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [10.0, 10.0, 10.3, 10.3, 10.4]                   # row1 = a.prev (SHIFT_PREV); row2 = a.next
    m = L.classify(a, "nav", b, "nav_cc")["category"].tolist()
    assert m[1] == "SHIFT_PREV" and m[2] == "SHIFT_NEXT"
    # one source on another share basis for a whole name-year: every row 3% apart
    a2 = _daily(np.linspace(10, 11, 30), tk="BBB")
    b2 = a2[["ticker", "date"]].copy()
    b2["nav_cc"] = a2["nav"] / 1.03
    assert (L.classify(a2, "nav", b2, "nav_cc")["category"] == "BASIS").all()


def test_implied_nav_brackets_the_true_nav_and_refuses_a_clipped_z():
    # Broken variant checked: inverting with disc = 100 (nav - px) / px misses the true NAV.
    px, nav, mu, sd = 10.71, 10.97, 4.57, 2.96
    disc = 100 * (px - nav) / nav
    z = round((disc - mu) / sd, 2)
    mid, lo, hi = L.implied_nav(px, z, mu, sd)
    assert lo <= nav <= hi and hi - lo < 0.01
    with pytest.raises(L.LiveNavQualityError):
        L.implied_nav(px, -4.0, mu, sd)


def test_tiebreak_slope_is_one_when_cc_holds_the_skipped_move():
    # Broken variant checked: measuring the catch from the NEXT row (not the next CHANGE)
    # gives slope 0 on two-day repeats.
    rng = np.random.default_rng(0)
    true = 10 + np.cumsum(rng.normal(0, 0.03, 400)).round(2)
    yf = true.copy()
    skip = np.arange(5, 395, 7)
    yf[skip] = yf[skip - 1]                                        # yfinance repeats for two days,
    yf[skip + 1] = yf[skip - 1]                                    # then catches up
    a = _daily(yf)
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = true
    m = L.classify(a, "nav", b, "nav_cc")
    tb = L.tiebreak(m, a, "nav", "nav_cc")
    # the variant still finds the move on the SECOND repeat day, so the slope alone separates
    # weakly (0.75 vs 1.14 on this seed); the sign agreement does not (0.41 vs 0.78)
    assert tb["n"] > 20 and abs(tb["slope"] - 1) < 0.2 and tb["sign_agree"] > 0.6


def test_cache_refuses_the_live_panel_directory(tmp_path, monkeypatch):
    # Broken variant checked: comparing unresolved paths lets a symlinked base through.
    live = tmp_path / "real" / "cef"
    live.mkdir(parents=True)
    (tmp_path / "data").symlink_to(tmp_path / "real")
    monkeypatch.setattr(L, "LIVE_DIR", tmp_path / "data" / "cef")
    monkeypatch.setattr(L, "CACHE", tmp_path / "real")
    with pytest.raises(L.LiveNavQualityError):
        L._cache("cef/x.json")
    monkeypatch.setattr(L, "CACHE", tmp_path / "elsewhere")
    assert L._cache("x.json").parent == tmp_path / "elsewhere"


# ---------------------------------------------------------------- added 2026-10-13

def test_nav_verdict_each_branch_and_the_tolerance():
    # Broken variant checked: testing `fin` before `fin and prv` returns V_FINAL on the
    # ambiguous row; treating NAV(D) == NAV(D-1) as stale returns V_STALE on the flat row.
    v = lambda lo, hi, f, p: L.nav_verdict(lo, hi, f, p)[0]          # noqa: E731
    assert v(10.968, 10.972, 10.97, 11.04) == L.V_FINAL
    assert v(11.038, 11.042, 10.97, 11.04) == L.V_STALE
    assert v(10.965, 10.985, 10.97, 10.98) == L.V_AMBIG               # interval a cent wide
    assert v(10.968, 10.972, 10.97, 10.97) == L.V_FINAL_EQ            # flat: cannot be called stale
    assert v(11.038, 11.042, 10.97, 10.97) == L.V_NEITHER
    assert v(11.50, 11.51, 10.97, 11.04) == L.V_NEITHER
    # a candidate 0.0015 outside is accepted, 0.0025 outside is not (IMPLIED_TOL = 0.002)
    assert v(10.9715, 10.975, 10.97, 11.04) == L.V_FINAL
    assert v(10.9725, 10.975, 10.97, 11.04) == L.V_NEITHER
    _, df, dp = L.nav_verdict(10.968, 10.972, 10.97, float("nan"))
    assert df == 0.0 and dp == np.inf


def _synthetic_session(n=400, seed=1):
    """One name, a traded panel with an EMPTY bar inside the z window, and yfinance-now with
    that bar filled. The session at D decides on NAV(D-1) (a stale copy)."""
    from scripts.cef.spec import Z_WINDOW
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2025-01-01", periods=n)
    nav = (10 + np.cumsum(rng.normal(0, 0.02, n))).round(2)
    nav[-1] = round(nav[-2] + 0.08, 2)                             # NAV(D) clearly differs from NAV(D-1)
    close = (nav * (1 + (-5 + rng.normal(0, 0.5, n)) / 100)).round(2)
    P_now = pd.DataFrame({"ticker": "AAA", "date": d, "close": close})
    N_now = pd.DataFrame({"ticker": "AAA", "date": d, "nav": nav})
    k = n - 60                                                     # inside the last Z_WINDOW rows before D
    P_now.loc[k, "close"] = round(nav[k] * 1.30, 2)                # a print the session never had
    P_tr = P_now.copy()
    P_tr.loc[k, "close"] = np.nan                                  # the session's panel: an empty bar
    _, mu, sd = L.sleeve_mu_sd(P_tr, N_now, ["AAA"], Z_WINDOW)
    a = d[-1]
    disc_stale = 100 * (close[-1] - nav[-2]) / nav[-2]
    z_plan = round((disc_stale - mu.at[a, "AAA"]) / sd.at[a, "AAA"], 2)
    assert abs(z_plan) < 4
    plans = pd.DataFrame([{"session": "s", "asof": a, "status": "decided", "decided_at_utc": "x", "sent": True,
                           "ticker": "AAA", "z_plan": z_plan, "close_plan": float(close[-1]), "current": 0,
                           "target": 1, "submitted": True, "session_orders_submitted": 1, "reason": ""}])
    cc = pd.DataFrame({"window": "1Y", "ticker": "AAA", "date": d, "nav_cc": nav})
    return plans, P_tr, N_now, P_now, cc


def test_live_period_takes_mu_and_sd_from_the_traded_panel():
    # Broken variant checked: building mu and sd from yfinance-now (the 2026-10-12 method,
    # empty bar filled) gives V_NEITHER here, not V_STALE.
    plans, P_tr, N_tr, P_now, cc = _synthetic_session()
    lp = L.live_period(plans, P_tr, N_tr, N_tr, P_now, cc)
    r = lp.iloc[0]
    assert r["verdict"] == L.V_STALE
    assert r["verdict_yfnow"] != L.V_STALE                         # the sensitivity sees the difference
    assert r["interval_shift_vs_yfnow"] > L.IMPLIED_TOL


def test_live_period_refuses_a_decision_the_traded_panel_cannot_cover():
    plans, P_tr, N_tr, P_now, cc = _synthetic_session()
    plans.loc[0, "asof"] = plans.loc[0, "asof"] + pd.offsets.BDay(5)
    with pytest.raises(L.LiveNavQualityError):
        L.live_period(plans, P_tr, N_tr, N_tr, P_now, cc)


def test_lag_unrepeated_catches_d_minus_1_dated_d_without_a_repeat():
    # Broken variant checked: dropping the "differs from CEFConnect(D)" clause also flags
    # row 5, a genuinely flat NAV after a wrong yfinance row.
    yf = _daily([15.20, 15.12, 15.12, 15.06, 15.30, 15.30], start="2026-09-21", tk="PDI")
    yf.loc[4, "nav"] = 15.25                                       # yfinance wrong on row 4 (cc 15.30)
    cc = yf[["ticker", "date"]].copy()
    cc["nav_cc"] = [15.20, 15.12, 15.06, 15.10, 15.30, 15.30]      # true: row 2 = 15.06, row 3 = 15.10
    hit = L.lag_unrepeated(yf, "nav", cc, "nav_cc")
    assert list(hit["date"]) == [yf["date"].iloc[3]]               # 15.06 dated row 3 = cc(row 2)
    assert L.classify(yf, "nav", cc, "nav_cc")["category"].iloc[3] != "STALE_COPY"   # not a repeat


def test_crsp_summary_has_no_dates_and_withholds_a_maximum_over_few_rows():
    # Broken variant checked: min_rows_for_max = 1 prints the single 2013-on row's |diff|,
    # which with its (ticker, year) and the public close bounds CRSP's price to two values.
    m = pd.DataFrame({
        "ticker": ["AAA"] * 6, "date": pd.to_datetime(["2004-01-02", "2004-01-05", "2004-01-06", "2014-03-03",
                                                       "2014-03-04", "2014-03-05"]),
        "category": ["OTHER", "STALE_COPY", "OTHER", "OTHER", "AGREE", "AGREE"],
        "diff": [0.02, -0.05, 0.01, 0.03, 0.0, 0.0]})
    m["year"] = m["date"].dt.year
    by_tyc, by_era = L.crsp_disagreement_summary(m)
    assert "date" not in by_tyc.reset_index().columns and list(by_tyc.columns) == ["rows"]
    e = by_era.set_index("era")
    assert e.loc["2001-2007", "differ"] == 3 and e.loc["2001-2007", "max_abs_diff_usd"] == 0.05
    assert e.loc["2013 on", "differ"] == 1 and np.isnan(e.loc["2013 on", "max_abs_diff_usd"])
