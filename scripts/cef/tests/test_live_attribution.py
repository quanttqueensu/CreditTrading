"""The live attribution (scripts/cef/live_attribution.py): its identity, its signs, its refusals.

WHY THESE TESTS
---------------
The attribution splits the paper account's P&L into hold, fill, NAV, discount and
distributions. On 2026-11-02 that split moved the explanation of the book's
-$982.14 from "the signal failed" to "muni NAVs rose under two shorts". A figure
that moves a judgement like that must not rest on a sign nobody checked. So the
fixture below is small enough to work by hand. Two names, AAA and BBB, go long
and short; AAA flips from long to short; CCC is bought on its own ex-date. Two
distributions fall on the flip day, one falls the day after, and one falls on a
market holiday. The account's equity is computed independently, as cash plus
positions marked at the close (the way Alpaca marks paper equity). It is never
computed from the attribution's own formulas, so the reconciliation test is a
real check.

The suite was run against four deliberately wrong copies of the module, one
mutation at a time (2026-11-02). Each copy failed:
  * nav_part with its sign flipped (`-qp * c_p * ...`): 2 failures, the
    hand-computed short and long NAV tests. The identity test still passes, as
    it must, because disc_part absorbs the error;
  * `sell_short` signed +1: 7 failures, among them the reconciliation, the
    short-sign, the flip, the entitlement and the fetch round trip;
  * the distribution charged on q_end instead of q_prev: 1 failure, the
    entitlement test;
  * the fill sign flipped: 4 failures, among them the reconciliation.
That first run caught a weak fixture. Its equity series used the module's own
sign table, so a wrong `sell_short` sign moved both sides and the
reconciliation still passed. The fixture now has its own table
(FIXTURE_SIGN).

The fixture's sessions skip Monday 2026-01-19 (Martin Luther King Jr. Day), so an
ex-date or a bar on that date is off the session calendar.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from fractions import Fraction as F
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.cef import live_attribution as LA  # noqa: E402

D = dt.date
PRE = [D(2026, 1, 14), D(2026, 1, 15)]                      # sessions before funding
S0, S1, S2, S3, S4 = (D(2026, 1, 16), D(2026, 1, 20), D(2026, 1, 21),
                      D(2026, 1, 22), D(2026, 1, 23))
SESSIONS = [S0, S1, S2, S3, S4]
HOLIDAY = D(2026, 1, 19)
GRP = {"AAA": "muni", "BBB": "multi", "CCC": "hy"}

CLOSES = {
    "AAA": {S0: "9.90", S1: "10.10", S2: "10.30", S3: "10.25", S4: "10.00"},
    "BBB": {S0: "20.10", S1: "19.90", S2: "20.10", S3: "19.80", S4: "20.40"},
    "CCC": {S2: "5.10", S3: "5.00", S4: "5.20"},
}
NAVS = {
    "AAA": {S0: "11.00", S1: "11.10", S2: "11.20", S3: "11.20", S4: "11.00"},
    "BBB": {S0: "22.00", S1: "22.00", S2: "22.44", S3: "22.00", S4: "22.22"},
    "CCC": {S2: "6.00", S3: "6.10", S4: "6.05"},
}
# (id, symbol, side, qty, price, NY date): 15:52 ET is 20:52 UTC in January (EST).
FILLS = [
    ("f1", "AAA", "buy", "100", "10.00", S1),
    ("f2", "BBB", "sell_short", "50", "20.00", S1),
    ("f3", "CCC", "buy", "10", "5.00", S2),          # bought on its ex-date
    ("f4", "AAA", "sell", "100", "10.20", S3),       # the flip, in two partial fills
    ("f5", "AAA", "sell_short", "50", "10.20", S3),
    ("f6", "BBB", "buy", "50", "20.50", S4),         # the short is closed
]
DISTS = [
    ("d1", "AAA", S3, "0.05"),      # held long 100 into S3 -> credited +5.00
    ("d2", "BBB", S3, "0.10"),      # held short 50 into S3 -> charged -5.00
    ("d3", "AAA", S4, "0.04"),      # short 50 after the flip -> charged -2.00
    ("d4", "CCC", S2, "0.02"),      # bought on the ex-date -> nothing
]


def raw_fills():
    return [{"id": i, "activity_type": "FILL", "symbol": s, "side": side, "qty": q,
             "price": px, "transaction_time": f"{d.isoformat()}T20:52:04.123456Z",
             "type": "fill", "order_id": f"o-{i}", "cum_qty": q, "leaves_qty": "0",
             "order_status": "filled"} for i, s, side, q, px, d in FILLS]


FIXTURE_SIGN = {"buy": 1, "sell": -1, "sell_short": -1}   # the fixture's own, not LA.SIDE_SIGN


def equity_series():
    """Cash plus positions at the close, per session: Alpaca's way of marking
    paper equity. Independent of the attribution's formulas AND of its sign table,
    so a wrong sign in the module cannot also move the fixture."""
    cash, q, out = F(100000), {}, []
    for d in SESSIONS:
        for _, s, side, qty, px, fd in FILLS:
            if fd == d:
                sq = FIXTURE_SIGN[side] * int(qty)
                cash -= sq * F(px)
                q[s] = q.get(s, 0) + sq
        out.append((d, cash + sum(x * F(CLOSES[s][d]) for s, x in q.items() if x)))
    return out


def table(src):
    return {(s, d): F(v) for s, days in src.items() for d, v in days.items()}


def inputs(**over):
    kw = dict(fills=LA.parse_fills(raw_fills()), eod=equity_series(), closes=table(CLOSES),
              navs=table(NAVS),
              dists=LA.parse_distributions([{"id": i, "symbol": s, "ex_date": d.isoformat(),
                                             "amount": a, "kind": "cash_dividend"}
                                            for i, s, d, a in DISTS]),
              corp=[], grp=dict(GRP), flat_start=S0, fills_from=PRE[0],
              corp_types=LA.SPLIT_TYPES, dist_kinds=LA.DIST_KINDS)
    kw.update(over)
    return LA.Inputs(**kw)


def row(res, s, d):
    r = res.name_day[(res.name_day["symbol"] == s) & (res.name_day["date"] == d)]
    assert len(r) == 1, (s, d, len(r))
    return r.iloc[0]


# --- the identity and the reconciliation -------------------------------------

def test_nav_plus_disc_equals_hold_exactly():
    res = LA.attribute(inputs())
    nd = res.name_day
    assert len(nd) > 0
    for r in nd.itertuples():
        assert isinstance(r.hold, F) and isinstance(r.nav_part, F)
        assert r.nav_part + r.disc_part == r.hold          # exact, not approximately
    assert sum(nd["nav_part"]) + sum(nd["disc_part"]) == sum(nd["hold"])


def test_daily_sum_matches_equity_change_exactly():
    res = LA.attribute(inputs())
    eq = dict(equity_series())
    assert list(res.daily["date"]) == SESSIONS[1:]
    assert all(r == 0 for r in res.daily["residual"])
    assert sum(res.daily["rebuilt"]) == eq[S4] - eq[S0]
    assert not [ln for ln in LA.reconcile_lines(res.daily) if ln.startswith("WARN")]


def test_warn_line_on_a_residual_above_threshold():
    eod = [(d, e + (10 if d == S2 else 0)) for d, e in equity_series()]
    res = LA.attribute(inputs(eod=eod))
    r = res.daily.set_index("date")["residual"]
    assert r[S2] == 10 and r[S3] == -10
    warns = [ln for ln in LA.reconcile_lines(res.daily) if ln.startswith("WARN")]
    assert len(warns) == 2 and warns[0].startswith(f"WARN {S2}")


# --- signs, by hand ------------------------------------------------------------

def test_short_side_signs():
    res = LA.attribute(inputs())
    b = row(res, "BBB", S2)                 # short 50; price 19.90 -> 20.10; NAV +2%
    assert b.side == "short" and b.q_prev == -50
    assert b.hold == F("-10")               # -50 * 0.20
    assert b.nav_part == F("-19.90")        # -50 * 19.90 * 0.02
    assert b.disc_part == F("9.90")         # the discount widened under a short: a gain
    b3 = row(res, "BBB", S3)                # price falls under the short: a gain
    assert b3.hold == F("15") and b3.nav_part > 0


def test_long_nav_part_by_hand():
    res = LA.attribute(inputs())
    a = row(res, "AAA", S2)                 # long 100; NAV 11.10 -> 11.20
    assert a.side == "long"
    assert a.hold == F("20")
    assert a.nav_part == 100 * F("10.10") * (F("11.20") / F("11.10") - 1)
    assert a.nav_part > 0


def test_fill_against_the_close():
    res = LA.attribute(inputs())
    assert row(res, "AAA", S1).fill == F("10")       # bought 100 at 10.00, closed 10.10
    assert row(res, "BBB", S1).fill == F("5")        # shorted 50 at 20.00, closed 19.90
    assert row(res, "AAA", S3).fill == F("-7.5")     # sold 150 at 10.20, closed 10.25
    assert row(res, "AAA", S1).hold == 0             # opened that day: nothing held into it
    assert row(res, "BBB", S1).side == "short"       # a name opened that day takes its side


def test_flip_long_to_short():
    res = LA.attribute(inputs())
    a3, a4 = row(res, "AAA", S3), row(res, "AAA", S4)
    assert (a3.q_prev, a3.q_end, a3.side) == (100, -50, "long")
    assert (a4.q_prev, a4.side) == (-50, "short")
    assert a4.hold == F("12.5")                      # -50 * (10.00 - 10.25)
    pos = res.positions_end.set_index("symbol")["qty"].to_dict()
    assert pos == {"AAA": -50, "CCC": 10}            # BBB closed on S4


# --- distributions: the holder at the previous close is entitled --------------------

def test_ex_date_entitlement():
    res = LA.attribute(inputs())
    assert row(res, "AAA", S3).dist == F("5")        # long 100 at S2's close; sold on S3
    assert row(res, "BBB", S3).dist == F("-5")       # short pays the lender
    assert row(res, "AAA", S4).dist == F("-2")       # short 50 after the flip
    assert row(res, "CCC", S2).dist == 0             # bought on its ex-date: trades ex
    ev = res.events.set_index("id")
    assert ev.loc["d4", "q_prev"] == 0 and ev.loc["d1", "q_prev"] == 100
    assert sum(res.daily["dist"]) == F("-2")
    # No event, no distribution: every other name-day is zero.
    others = res.name_day[~res.name_day.apply(
        lambda r: (r.symbol, r.date) in {(s, d) for _, s, d, _ in DISTS}, axis=1)]
    assert all(x == 0 for x in others["dist"])


def test_periods_split_after_the_equity_peak():
    res = LA.attribute(inputs())
    eq = dict(equity_series())
    # By hand: 100,000 / 100,015 / 100,026 / 100,027.50 / 100,007 -> the peak is S3.
    assert [eq[d] for d in SESSIONS] == [F(100000), F(100015), F(100026), F("100027.5"), F(100007)]
    assert [(p[1], p[2]) for p in res.periods] == [(S1, S3), (S4, S4)]
    assert "peak on 2026-01-22" in res.period_rule
    res2 = LA.attribute(inputs(), breaks=[S3, S3])
    assert [(p[1], p[2]) for p in res2.periods] == [(S1, S2), (S3, S4)]
    with pytest.raises(LA.AttributionError, match="a break must be a session"):
        LA.attribute(inputs(), breaks=[HOLIDAY])


def test_capital_gains_not_queried_is_a_stated_gap():
    res = LA.attribute(inputs(dist_kinds=("cash_dividend",)))
    assert res.gaps and "capital-gains" in res.gaps[0]


# --- refusals ------------------------------------------------------------------

def _drop(tbl, key):
    t = dict(tbl)
    del t[key]
    return t


def test_raises_on_missing_close_for_a_held_name():
    with pytest.raises(LA.AttributionError, match=f"missing close for AAA on {S2}"):
        LA.attribute(inputs(closes=_drop(table(CLOSES), ("AAA", S2))))


def test_a_nan_close_is_missing_not_filled():
    closes = _drop(table(CLOSES), ("BBB", S2))
    with pytest.raises(LA.AttributionError, match="missing close for BBB.*'nan'"):
        LA.attribute(inputs(closes=closes, bad_closes={("BBB", S2): "nan"}))


def test_raises_on_missing_nav_on_a_held_name_day():
    with pytest.raises(LA.AttributionError, match=f"missing NAV for BBB on {S2}"):
        LA.attribute(inputs(navs=_drop(table(NAVS), ("BBB", S2))))
    with pytest.raises(LA.AttributionError, match=f"missing NAV for AAA on {S1}"):
        LA.attribute(inputs(navs=_drop(table(NAVS), ("AAA", S1))))   # the previous NAV


def test_a_nav_is_not_needed_on_a_day_nothing_is_held():
    # AAA and BBB open on S1, so nothing needs their S0 NAV; BBB is closed on S4,
    # so nothing needs its S4 NAV... except hold on S4, which does (held into S4).
    LA.attribute(inputs(navs=_drop(_drop(table(NAVS), ("AAA", S0)), ("BBB", S0))))
    with pytest.raises(LA.AttributionError, match=f"missing NAV for BBB on {S4}"):
        LA.attribute(inputs(navs=_drop(table(NAVS), ("BBB", S4))))


def test_raises_on_fill_on_a_day_with_no_bar():
    with pytest.raises(LA.AttributionError, match="fill f3 in CCC .*no bar for that day"):
        LA.attribute(inputs(closes=_drop(table(CLOSES), ("CCC", S2))))


def test_raises_on_duplicate_activity_ids():
    raw = raw_fills()
    raw.append(dict(raw[0]))
    with pytest.raises(LA.AttributionError, match="duplicate FILL activity ids.*f1"):
        LA.parse_fills(raw)


def test_raises_on_a_split_in_the_window():
    split = {"id": "x1", "type": "reverse_split", "date": S3, "parties": [("AAA", "subject")]}
    with pytest.raises(LA.AttributionError, match="share-count corporate action.*reverse_split"):
        LA.attribute(inputs(corp=[split]))
    # A split on a name never traded, or outside the window, is not ours.
    LA.attribute(inputs(corp=[dict(split, parties=[("ZZZ", "subject")]),
                              dict(split, date=D(2026, 2, 2))]))


def test_raises_when_splits_were_not_queried():
    with pytest.raises(LA.AttributionError, match="cannot show that no split"):
        LA.attribute(inputs(corp_types=("cash_merger",)))


def test_raises_when_the_flat_start_is_not_shown():
    with pytest.raises(LA.AttributionError, match="cannot assert a flat start"):
        LA.attribute(inputs(fills_from=S1))
    raw = raw_fills()
    raw[0] = dict(raw[0], transaction_time=f"{PRE[1].isoformat()}T20:52:00Z")
    with pytest.raises(LA.AttributionError, match="before flat_start"):
        LA.attribute(inputs(fills=LA.parse_fills(raw)))


def test_raises_on_a_fill_at_the_first_eod_point():
    raw = raw_fills()
    raw[0] = dict(raw[0], transaction_time=f"{S0.isoformat()}T20:52:00Z")
    with pytest.raises(LA.AttributionError, match="on or before the first EOD point"):
        LA.attribute(inputs(fills=LA.parse_fills(raw)))


def test_raises_on_ex_date_off_the_session_calendar():
    d = LA.parse_distributions([{"id": "h", "symbol": "AAA", "ex_date": HOLIDAY.isoformat(),
                                 "amount": "0.05", "kind": "cash_dividend"}])
    with pytest.raises(LA.AttributionError, match="is not a session of the EOD history"):
        LA.attribute(inputs(dists=d))


def test_raises_on_a_bar_the_eod_history_lacks():
    with pytest.raises(LA.AttributionError, match="fall on no session"):
        LA.attribute(inputs(closes=table(CLOSES) | {("AAA", HOLIDAY): F("10.2")}))


def test_raises_on_a_symbol_with_no_grp():
    with pytest.raises(LA.AttributionError, match=r"\['CCC'\] have no grp"):
        LA.attribute(inputs(grp={"AAA": "muni", "BBB": "multi"}))


def test_raises_on_identical_distribution_records():
    with pytest.raises(LA.AttributionError, match="identical distribution records"):
        LA.parse_distributions([{"id": i, "symbol": "AAA", "ex_date": "2026-01-22",
                                 "amount": "0.05", "kind": "cash_dividend"} for i in ("a", "b")])


def test_fills_after_asof_are_excluded_and_counted():
    res = LA.attribute(inputs(), asof=S3)
    assert res.excluded_after_asof == 1 and res.daily["date"].max() == S3


# --- the cache round trip, and fetch against a fake client ---------------------

class FakeClient:
    """The read methods `fetch` calls, answering from the fixture. No network."""

    def eod_equity_history(self, start, end):
        return [(d, float(e), dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0),
                                                  dt.timezone.utc))
                for d, e in equity_series() if start <= d <= end]

    def calendar(self, start, end):
        return [{"date": d} for d in PRE + SESSIONS if start <= d <= end]

    def activities_fills(self, date):
        return [a for a in raw_fills() if a["transaction_time"][:10] == date.isoformat()]

    def distributions(self, symbols, start, end):
        return [{"id": i, "symbol": s, "ex_date": d, "amount": float(a), "kind": "cash_dividend",
                 "special": False, "sub_type": None} for i, s, d, a in DISTS if s in symbols]

    def corporate_actions(self, symbols, start, end):
        return []

    def _get(self, base, path, params):
        assert path == "/v2/stocks/bars" and params["feed"] == "sip" and params["adjustment"] == "raw"
        bars = {s: [{"t": f"{d.isoformat()}T05:00:00Z", "o": float(c), "h": float(c), "l": float(c),
                     "c": float(c), "v": 1000} for d, c in sorted(CLOSES[s].items())]
                for s in params["symbols"].split(",")}
        return {"bars": bars, "next_page_token": None}


def fake_navs(symbols, start, end):
    rows = [{"date": d.isoformat(), "ticker": s, "nav": v}
            for s in symbols for d, v in NAVS[s].items() if start <= d <= end]
    return pd.DataFrame(rows, columns=["date", "ticker", "nav"]), []


NOW = dt.datetime(2026, 1, 26, 12, tzinfo=dt.timezone.utc)


def test_fetch_then_analyse_reproduces_the_in_memory_result(tmp_path):
    man = LA.fetch(tmp_path / "cache", since=PRE[0], asof=S4, client=FakeClient(),
                   nav_fetcher=fake_navs, now=NOW)
    assert man["flat_start"]["date"] == S0.isoformat()
    assert "reverse_split" in man["corporate_actions"]["types"]
    res, paths = LA.analyse(tmp_path / "cache", tmp_path / "out", grp=dict(GRP))
    mem = LA.attribute(inputs())
    for k in LA.MONEY:
        assert sum(res.name_day[k]) == sum(mem.name_day[k]), k
    assert all(r == 0 for r in res.daily["residual"])
    for k in ("summary", "name_day", "daily", "by_name", "by_side", "by_grp", "by_period"):
        assert paths[k].is_file() and paths[k].parent == tmp_path / "out" / S4.isoformat()
    text = paths["summary"].read_text()
    assert "nav_part" in text and "NAV alignment" in text
    assert json.loads((tmp_path / "cache" / "manifest.json").read_text())["fills"]["n"] == len(FILLS)


def test_fetch_refuses_when_the_flat_start_cannot_be_shown(tmp_path):
    with pytest.raises(LA.AttributionError, match="pass an earlier --since"):
        LA.fetch(tmp_path / "c", since=S0, asof=S4, client=FakeClient(),
                 nav_fetcher=fake_navs, now=NOW)
    assert not (tmp_path / "c").exists()


def test_fetch_refuses_an_unfinished_eod_point(tmp_path):
    with pytest.raises(LA.AttributionError, match="not final yet"):
        LA.fetch(tmp_path / "c", since=PRE[0], asof=S4, client=FakeClient(),
                 nav_fetcher=fake_navs, now=dt.datetime(2026, 1, 23, 22, tzinfo=dt.timezone.utc))


def test_never_writes_under_data():
    with pytest.raises(LA.AttributionError, match="under data/"):
        LA._refuse_data_dir(LA.DATA_DIR / "cef" / "live_attribution")
