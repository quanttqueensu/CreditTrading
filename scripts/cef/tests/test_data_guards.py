"""The two data guards of 2026-10-19 (`scripts/cef/data_guards.py`), on synthetic frames.

WHY THESE TESTS. C4's holdout booked four IGR bars on the post-split basis inside a raw
pre-split series (+200% then -66.7%, four times; -10.87% of capital), and Stage 0 had
flagged them four days earlier with no one ruling on the flags. Each guard here must
(i) raise on exactly that shape, naming every bar; (ii) stay silent on a genuine split,
which does not revert; (iii) let a caller proceed only through a recorded ruling; and
(iv) leave every other number bit for bit as it was. `test_yf_total_returns_raises_on_an_
igr_shaped_spike` FAILED against the code before 2026-10-19 (checked: the old
`yf_total_returns` returned +200% / -66.7% and did not raise). Claims about the code,
never about the market.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scripts.cef import c4_families as c4
from scripts.cef import data_guards as dg

DATES = pd.bdate_range("2026-07-01", periods=40)


def _close(level=4.7, seed=7, n=len(DATES)):
    rng = np.random.default_rng(seed)
    return pd.Series(level * np.exp(np.cumsum(rng.normal(0, 0.008, n))), index=DATES[:n]).round(2)


def _panels(tmp_path, igr: pd.Series, nav_igr: pd.Series | None, splits=(), divs=None):
    """A families-shaped directory: prices, NAV, actions. Two funds: IGR (as given) and AAA (clean)."""
    aaa = _close(20.0, seed=3)
    px = pd.concat([pd.DataFrame(dict(date=igr.index, ticker="IGR", close=igr.values)),
                    pd.DataFrame(dict(date=aaa.index, ticker="AAA", close=aaa.values))])
    for c in ("open", "high", "low"):
        px[c] = px["close"]
    px["volume"], px["grp"] = 1000, "x"
    navs = [pd.DataFrame(dict(date=aaa.index, ticker="AAA", nav=(aaa * 1.05).values))]
    if nav_igr is not None:
        navs.append(pd.DataFrame(dict(date=nav_igr.index, ticker="IGR", nav=nav_igr.values)))
    nav = pd.concat(navs)
    divs = divs or [("IGR", DATES[3], 0.06), ("AAA", DATES[4], 0.10)]
    acts = [dict(date=d, ticker=t, dividends=a, stock_splits=0.0) for t, d, a in divs]
    acts += [dict(date=d, ticker=t, dividends=0.0, stock_splits=k) for t, d, k in splits]
    px.to_parquet(tmp_path / "cef_prices.parquet", index=False)
    nav.to_parquet(tmp_path / "cef_nav.parquet", index=False)
    pd.DataFrame(acts).to_parquet(tmp_path / "cef_actions.parquet", index=False)
    return px, nav


def _igr_shaped():
    """IGR's shape: single bars at x3 that revert next session (here two of them), NAV flat."""
    c = _close()
    nav = c.copy()
    c.iloc[20] = round(c.iloc[20] * 3, 2)
    c.iloc[26] = round(c.iloc[26] * 3, 2)
    return c, nav


def _rulings(tmp_path, bars, name="rulings.json", **top):
    doc = dict(ruled_by="team lead (test)", ruled_on="2026-10-19", record="test", bars=bars)
    doc.update(top)
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


def _bar(d, treatment, factor=3, run_end=None):
    return dict(ticker="IGR", date=str(d.date()), run_end=str((run_end or d).date()), factor=factor,
                treatment=treatment, reason="test")


# ------------------------------------------------------------------ (a) through yf_total_returns

def test_yf_total_returns_raises_on_an_igr_shaped_spike(tmp_path, monkeypatch):
    """The test that failed against the old code: it booked +200% / -66.7% silently."""
    c, nav = _igr_shaped()
    px, _ = _panels(tmp_path, c, nav)
    monkeypatch.setattr(c4, "FAM_DIR", tmp_path)
    with pytest.raises(dg.SpikeRevertError) as e:
        c4.yf_total_returns(px, ["IGR", "AAA"], DATES[1:])
    msg = str(e.value)
    for d in (DATES[20], DATES[26]):                                  # every bar named, with its ratio
        assert f"(IGR, {d.date()}, ratio " in msg
    assert msg.count("factor 3") == 2 and "AAA" not in msg and "2 split-like" in msg


def test_a_genuine_split_that_does_not_revert_does_not_raise(tmp_path, monkeypatch):
    """IGR's real 1:3 reverse split: raw close and raw NAV x3 from the ex-date, recorded at 1/3."""
    c = _close()
    nav = c.copy()
    c.iloc[25:] *= 3
    nav.iloc[25:] *= 3
    px, _ = _panels(tmp_path, c, nav, splits=[("IGR", DATES[25], 1 / 3)])
    monkeypatch.setattr(c4, "FAM_DIR", tmp_path)
    r = c4.yf_total_returns(px, ["IGR", "AAA"], DATES[1:])
    assert abs(r.loc[DATES[25], "IGR"]) < 0.05                       # the split is not a return
    H, U = dg.split_like_spikes(c.to_frame("IGR"), nav.to_frame("IGR"), None)   # even unrecorded:
    assert H.empty and U.empty                                       # the NAV made the same move


def test_an_unrecorded_jump_with_flat_nav_and_no_revert_is_reported_not_raised():
    c = _close()
    c.iloc[25:] *= 3
    H, U = dg.split_like_spikes(c.to_frame("IGR"), _close().to_frame("IGR"), None)
    assert H.empty and list(U["date"]) == [DATES[25]] and U["factor"].iloc[0] == 3.0


def test_the_override_rebases_and_book_as_is_reproduces_the_old_formula(tmp_path, monkeypatch):
    c, nav = _igr_shaped()
    px, _ = _panels(tmp_path, c, nav)
    monkeypatch.setattr(c4, "FAM_DIR", tmp_path)
    idx, cols = DATES[1:], ["IGR", "AAA"]
    from scripts.cef.band_frontier import total_returns
    raw = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    formula = lambda cl: total_returns(cl.pct_change(fill_method=None).reindex(index=idx, columns=cols),   # noqa: E731
                                       actions=tmp_path / "cef_actions.parquet", prices=tmp_path / "cef_prices.parquet")
    asis = _rulings(tmp_path, [_bar(DATES[20], "book_as_is"), _bar(DATES[26], "book_as_is")], "asis.json")
    pd.testing.assert_frame_equal(c4.yf_total_returns(px, cols, idx, rulings=asis), formula(raw))
    reb = _rulings(tmp_path, [_bar(DATES[20], "rebase"), _bar(DATES[26], "rebase")], "rebase.json")
    fixed = raw.copy()
    fixed.loc[[DATES[20], DATES[26]], "IGR"] /= 3
    got = c4.yf_total_returns(px, cols, idx, rulings=reb)
    pd.testing.assert_frame_equal(got, formula(fixed))
    assert got["IGR"].abs().max() < 0.05 and got["AAA"].equals(formula(raw)["AAA"])


def test_one_ruled_bar_and_one_unruled_still_raises_naming_only_the_unruled(tmp_path, monkeypatch):
    c, nav = _igr_shaped()
    px, _ = _panels(tmp_path, c, nav)
    monkeypatch.setattr(c4, "FAM_DIR", tmp_path)
    p = _rulings(tmp_path, [_bar(DATES[20], "rebase")])
    with pytest.raises(dg.SpikeRevertError, match=f"1 split-like.*IGR, {DATES[26].date()}") as e:
        c4.yf_total_returns(px, ["IGR", "AAA"], DATES[1:], rulings=p)
    assert str(DATES[20].date()) not in str(e.value)


def test_no_bar_in_range_is_bit_for_bit_the_old_formula(tmp_path, monkeypatch):
    c, nav = _igr_shaped()
    px, _ = _panels(tmp_path, c, nav)
    monkeypatch.setattr(c4, "FAM_DIR", tmp_path)
    from scripts.cef.band_frontier import total_returns
    idx, cols = DATES[1:15], ["IGR", "AAA"]                          # ends before the first bad bar
    raw = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    ref = total_returns(raw.pct_change(fill_method=None).reindex(index=idx, columns=cols),
                        actions=tmp_path / "cef_actions.parquet", prices=tmp_path / "cef_prices.parquet")
    got = c4.yf_total_returns(px, cols, idx)
    assert (pd.util.hash_pandas_object(got).values == pd.util.hash_pandas_object(ref).values).all()


def test_a_rebased_close_that_is_an_ex_dates_prior_close_raises(tmp_path, monkeypatch):
    c, nav = _igr_shaped()
    px, _ = _panels(tmp_path, c, nav, divs=[("IGR", DATES[21], 0.06), ("AAA", DATES[4], 0.10)])
    monkeypatch.setattr(c4, "FAM_DIR", tmp_path)
    p = _rulings(tmp_path, [_bar(DATES[20], "rebase"), _bar(DATES[26], "rebase")])
    with pytest.raises(dg.SpikeRevertError, match="prior close of an ex-date"):
        c4.yf_total_returns(px, ["IGR", "AAA"], DATES[1:], rulings=p)


# ------------------------------------------------------------------ (a) the rule itself

def test_the_tolerance_is_the_desks_declared_q5_line():
    assert dg.GENUINE_MOVE_MAX == c4.Q5_ABS
    assert dg.SPLIT_TOL < np.log(1.5) / 2 and dg.SPLIT_TOL < np.log(2)


def test_missing_nav_does_not_exempt_a_fund_and_a_nav_that_moves_does():
    c, nav = _igr_shaped()
    H, _ = dg.split_like_spikes(c.to_frame("IGR"), None, None)
    assert list(H["date"]) == [DATES[20], DATES[26]] and H["nav_ratio"].isna().all()
    moved = nav.copy()
    moved.iloc[20] *= 3                                              # NAV makes the same x3 move
    H2, _ = dg.split_like_spikes(c.to_frame("IGR"), moved.to_frame("IGR"), None)
    assert list(H2["date"]) == [DATES[26]]


def test_a_wrong_basis_run_inside_the_window_is_one_hit_and_a_longer_one_is_reported():
    c = _close()
    two = c.copy()
    two.iloc[20:22] *= 3
    H, _ = dg.split_like_spikes(two.to_frame("IGR"), c.to_frame("IGR"), None)
    assert len(H) == 1 and H["run_end"].iloc[0] == DATES[21] and H["bars"].iloc[0] == 2
    long_ = c.copy()
    long_.iloc[20:20 + dg.REVERT_WINDOW + 1] *= 3
    H, U = dg.split_like_spikes(long_.to_frame("IGR"), c.to_frame("IGR"), None)
    assert H.empty and len(U) >= 1


def test_a_large_jump_that_is_not_split_like_is_not_a_hit_and_a_down_factor_is():
    c = _close()
    odd = c.copy()
    odd.iloc[20] *= 2.45                                             # between the bands of 2 and 3
    assert dg.split_like_spikes(odd.to_frame("IGR"), c.to_frame("IGR"), None)[0].empty
    half = c.copy()
    half.iloc[20] /= 2                                               # a post-forward-split bar
    H, _ = dg.split_like_spikes(half.to_frame("IGR"), c.to_frame("IGR"), None)
    assert len(H) == 1 and H["factor"].iloc[0] == 0.5


def test_a_wrong_basis_bar_the_day_before_a_recorded_split_is_caught():
    """The raw series steps x3 on the ex-date; a bar one day early already on the new basis
    would book no move on the ex-date and a -66.7% split correction. On the split-corrected
    series it is a spike and revert."""
    c = _close()
    c.iloc[25:] *= 3
    c.iloc[24] *= 3                                                  # one bar early
    nav = _close()
    nav.iloc[25:] *= 3
    sp = pd.DataFrame(dict(ex_date=[DATES[25]], ticker=["IGR"], stock_split=[1 / 3]))
    H, _ = dg.split_like_spikes(c.to_frame("IGR"), nav.to_frame("IGR"), sp)
    assert list(H["date"]) == [DATES[24]]


def test_a_non_positive_close_raises():
    c = _close()
    c.iloc[5] = 0.0
    with pytest.raises(ValueError, match="non-positive close"):
        dg.split_like_spikes(c.to_frame("IGR"))


def test_rulings_that_do_not_fit_raise(tmp_path):
    c, nav = _igr_shaped()
    kw = dict(cols=["IGR"], lo=DATES[1], hi=DATES[-1], nav=nav.to_frame("IGR"), splits=None)
    close = c.to_frame("IGR")
    stale = _rulings(tmp_path, [_bar(DATES[20], "rebase"), _bar(DATES[26], "rebase"), _bar(DATES[10], "rebase")])
    with pytest.raises(dg.SpikeRevertError, match="matches no spike-and-revert bar"):
        dg.guard_closes(close, rulings=stale, **kw)
    wrong = _rulings(tmp_path, [_bar(DATES[20], "rebase", factor=2), _bar(DATES[26], "rebase")], "w.json")
    with pytest.raises(dg.SpikeRevertError, match="at factor 2"):
        dg.guard_closes(close, rulings=wrong, **kw)
    for bad in (dict(ruled_by=""), dict(bars=[dict(_bar(DATES[20], "rebase"), reason="")]),
                dict(bars=[_bar(DATES[20], "drop")]), dict(bars=[_bar(DATES[20], "rebase", factor=2.5)])):
        with pytest.raises(dg.SpikeRevertError):
            top = {k: v for k, v in bad.items() if k != "bars"}
            dg.load_bar_rulings(_rulings(tmp_path, bad.get("bars", [_bar(DATES[20], "rebase")]), "b.json", **top))
    out, log = dg.guard_closes(close, rulings=None, **dict(kw, hi=DATES[15]))   # out of range: untouched
    assert out is close and log.empty


def test_the_committed_c4_rulings_load_and_name_the_four_igr_bars():
    R, doc = dg.load_bar_rulings(c4.BAR_RULINGS)
    assert sorted(str(d.date()) for d in R["date"]) == ["2026-07-29", "2026-08-04", "2026-08-07", "2026-08-11"]
    assert set(R["treatment"]) == {"rebase"} and set(R["factor"]) == {3.0} and doc["ruled_on"] == "2026-10-19"


# ------------------------------------------------------------------ (b) Stage-0 flags block P&L

def _flags():
    return pd.DataFrame(dict(check=["Q5", "Q5", "Q2"], ticker=["IGR", "IGR", "ACV"],
                             date=pd.to_datetime(["2026-07-29", "2026-07-30", "2015-06-03"]),
                             detail=["|r|>15%", "|r|>15%", "close unchanged"]))


def _write(tmp_path, rows):
    p = tmp_path / "stage0_rulings.csv"
    pd.DataFrame(rows, columns=["check", "ticker", "date", "ruling", "ruled_by", "ruled_on"]).to_csv(p, index=False)
    return p


def test_no_rulings_file_refuses_naming_every_flag(tmp_path):
    with pytest.raises(dg.Stage0BlockError, match="3 Stage-0 flag") as e:
        dg.require_stage0_rulings(_flags(), tmp_path / "missing.csv", context="T")
    for s in ("(Q5, IGR, 2026-07-29)", "(Q5, IGR, 2026-07-30)", "(Q2, ACV, 2015-06-03)"):
        assert s in str(e.value)


def test_a_flag_without_a_ruling_or_with_an_empty_field_refuses(tmp_path):
    ok = ("team lead", "2026-10-19")
    p = _write(tmp_path, [("Q5", "IGR", "2026-07-29", "rebase x3 (vendor basis)", *ok),
                          ("Q2", "ACV", "2015-06-03", "genuine; no action", *ok)])
    with pytest.raises(dg.Stage0BlockError, match=r"1 of 3 .*\(Q5, IGR, 2026-07-30\)"):
        dg.require_stage0_rulings(_flags(), p)
    p = _write(tmp_path, [("Q5", "IGR", "2026-07-29", "rebase", *ok), ("Q5", "IGR", "2026-07-30", "rebase", "", ""),
                          ("Q2", "ACV", "2015-06-03", "genuine", *ok)])
    with pytest.raises(dg.Stage0BlockError, match=r"\(Q5, IGR, 2026-07-30\)"):
        dg.require_stage0_rulings(_flags(), p)


def test_every_flag_ruled_passes_and_a_stale_or_doubled_ruling_refuses(tmp_path):
    ok = ("team lead", "2026-10-19")
    rows = [("Q5", "IGR", "2026-07-29", "rebase", *ok), ("Q5", "IGR", "2026-07-30", "revert of the rebased bar", *ok),
            ("Q2", "ACV", "2015-06-03", "genuine", *ok)]
    J = dg.require_stage0_rulings(_flags(), _write(tmp_path, rows))
    assert len(J) == 3 and (J["ruling"] != "").all()
    with pytest.raises(dg.Stage0BlockError, match="no longer raises"):
        dg.require_stage0_rulings(_flags(), _write(tmp_path, rows + [("Q5", "TY", "2025-12-12", "x", *ok)]))
    with pytest.raises(dg.Stage0BlockError, match="twice"):
        dg.require_stage0_rulings(_flags(), _write(tmp_path, rows + [rows[0]]))
    with pytest.raises(dg.Stage0BlockError, match="not a date"):
        dg.require_stage0_rulings(_flags(), _write(tmp_path, rows[:2] + [rows[2][:5] + ("last week",)]))


def test_zero_flags_need_no_file_and_the_template_never_overwrites(tmp_path):
    assert dg.require_stage0_rulings(_flags().iloc[:0], tmp_path / "none.csv").empty
    p = dg.stage0_rulings_template(_flags(), tmp_path / "t.csv")
    T = pd.read_csv(p, dtype=str, keep_default_na=False)
    assert list(T.columns) == ["check", "ticker", "date", "ruling", "ruled_by", "ruled_on"] and len(T) == 3
    with pytest.raises(dg.Stage0BlockError, match="refuse|never overwritten"):
        dg.stage0_rulings_template(_flags(), p)
    with pytest.raises(dg.Stage0BlockError, match="lack a recorded ruling"):
        dg.require_stage0_rulings(_flags(), p)                     # the blank form rules on nothing


def test_c4s_committed_stage0_flags_would_be_refused():
    """Why the block is not wired into C4: its committed Stage 0 carries thousands of flags with
    no recorded ruling (only Q1 is ruled), the eight IGR Q5 rows among them."""
    f = pd.read_csv(c4.OUT_DIR / "c4_stage0_flags_2026-10-14.csv")
    keys = ("check", "ticker", "date", "source")                     # Q3 flags one day from two sources
    with pytest.raises(dg.Stage0BlockError, match="two flags share one key"):
        dg.require_stage0_rulings(f, c4.OUT_DIR / "none.csv")
    with pytest.raises(dg.Stage0BlockError, match="no rulings file") as e:
        dg.require_stage0_rulings(f, c4.OUT_DIR / "c4_stage0_rulings_does_not_exist.csv", keys=keys)
    assert "(Q5, IGR, 2026-07-29, yfinance)" in str(e.value)
