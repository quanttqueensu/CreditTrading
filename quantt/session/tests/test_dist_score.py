"""`quantt/session/dist_score.py`: the distribution-adjusted third score.

What these pin (team lead 2026-10-09, `docs/SYSTEM.md` §5; the module docstring):
  * the entitlement rule: shares held at the START of the ex-date are credited if
    long and charged if short; D's fills earn nothing;
  * the two-source rule: Alpaca primary, the yfinance panel a cross-check within
    rounding; a real conflict, or an ex-date only the panel lists, is UNMEASURED
    naming both; never averaged;
  * a missing term makes the sum UNMEASURED, as in `score.py`;
  * it writes only its own file, never scores.csv, never twice for one day, and a
    failure is a row naming it, never a changed verdict.
Hermetic: a fake client, a temporary state dir, an in-memory panel.
"""
import ast
import csv
import datetime as dt
import inspect

import pandas as pd
import pytest

from quantt.session import dist_score as ds
from quantt.session import score as sc
from quantt.session import verify as vf

D = dt.date(2026, 10, 13)
NOW = dt.datetime(2026, 10, 13, 21, 30, tzinfo=dt.timezone.utc)


def ev(sym, amount, ex=D, kind="cash_dividend", i=None):
    return {"id": i or f"{sym}-{ex}-{amount}", "symbol": sym, "ex_date": ex, "amount": amount,
            "kind": kind, "special": False, "sub_type": None}


def panel(rows):
    return pd.DataFrame(rows, columns=["ticker", "ex_date", "amount"]).assign(
        ex_date=lambda d: pd.to_datetime(d["ex_date"]))


class FakeClient:
    def __init__(self, events=(), exc=None):
        self.events, self.exc, self.calls = list(events), exc, []

    def distributions(self, symbols, start, end):
        self.calls.append((tuple(symbols), start, end))
        if self.exc:
            raise self.exc
        return list(self.events)


def rows_of(state):
    p = state / "distribution_scores.csv"
    with p.open(newline="") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------ the rule

def test_a_long_is_credited_and_a_short_is_charged():
    pnl, rows, un = ds.score({"PDI": 100, "PTY": -200}, {"PDI": 0.2205, "PTY": 0.1188}, {})
    assert un == [] and pnl == pytest.approx(100 * 0.2205 - 200 * 0.1188)
    by = {r["symbol"]: r for r in rows}
    assert by["PDI"]["dist_pnl"] > 0 and by["PTY"]["dist_pnl"] < 0


def test_no_distribution_on_d_is_an_explicit_zero():
    pnl, rows, un = ds.score({"PDI": 100}, {"PDI": 0.0}, {})
    assert pnl == 0.0 and rows[0]["dist_pnl"] == 0.0 and un == []


def test_a_missing_term_makes_the_sum_unmeasured():
    pnl, rows, un = ds.score({"PDI": 100, "PTY": 50}, {"PDI": 0.22}, {"PTY": "sources disagree"})
    assert pnl is None and un == ["PTY: sources disagree"]


@pytest.mark.parametrize("per_share,gaps", [({}, {}), ({"PDI": 0.1}, {"PDI": "x"})])
def test_a_symbol_must_be_resolved_exactly_once(per_share, gaps):
    with pytest.raises(ds.DistError, match="exactly one"):
        ds.score({"PDI": 100}, per_share, gaps)


@pytest.mark.parametrize("q", [0, 1.5, True])
def test_held_must_be_non_zero_whole_shares(q):
    with pytest.raises(ds.DistError, match="non-zero int"):
        ds.score({"PDI": q}, {"PDI": 0.1}, {})


@pytest.mark.parametrize("a", [-0.01, float("nan"), float("inf"), "0.1", None])
def test_a_per_share_amount_must_be_a_finite_non_negative_number(a):
    with pytest.raises(ds.DistError, match="per-share"):
        ds.score({"PDI": 100}, {"PDI": a}, {})


# ------------------------------------------------------- the two-source rule

def test_agreement_within_rounding_uses_alpacas_more_precise_amount():
    ps, gaps, notes = ds.resolve(["MHD"], D, [ev("MHD", 0.0595)], panel([("MHD", D, 0.060)]))
    assert ps == {"MHD": 0.0595} and gaps == {} and "Alpaca used" in notes["MHD"]


def test_a_real_conflict_is_unmeasured_naming_both_and_never_averaged():
    ps, gaps, _ = ds.resolve(["PDI"], D, [ev("PDI", 0.2205)], panel([("PDI", D, 0.25)]))
    assert ps == {} and "Alpaca 0.2205" in gaps["PDI"] and "0.25" in gaps["PDI"]
    assert "not averaged" in gaps["PDI"]


def test_only_alpaca_listing_d_uses_alpaca():
    ps, gaps, notes = ds.resolve(["PDI"], D, [ev("PDI", 0.2205)], panel([]))
    assert ps == {"PDI": 0.2205} and "does not list" in notes["PDI"]


def test_only_the_panel_listing_d_is_unmeasured_because_silence_is_not_zero():
    ps, gaps, _ = ds.resolve(["PDI"], D, [], panel([("PDI", D, 0.221)]))
    assert ps == {} and "silence is not a zero" in gaps["PDI"]


def test_neither_source_listing_d_is_zero_and_says_so():
    other_day = D - dt.timedelta(days=30)
    ps, gaps, notes = ds.resolve(["PDI"], D, [ev("PDI", 0.2205, ex=other_day)],
                                 panel([("PDI", other_day, 0.221)]))
    assert ps == {"PDI": 0.0} and gaps == {} and "none listed" in notes["PDI"]


def test_two_events_on_one_ex_date_are_summed_with_a_wider_tolerance():
    alp = [ev("PDI", 0.2205, i="a"), ev("PDI", 0.5, i="b")]
    ps, gaps, _ = ds.resolve(["PDI"], D, alp, panel([("PDI", D, 0.221), ("PDI", D, 0.5)]))
    assert ps["PDI"] == pytest.approx(0.7205) and gaps == {}


def test_split_rows_with_zero_amount_in_the_panel_are_not_distributions():
    ps, gaps, _ = ds.resolve(["PDI"], D, [], panel([("PDI", D, 0.0)]))
    assert ps == {"PDI": 0.0} and gaps == {}


def test_no_panel_at_all_still_resolves_and_says_the_second_source_was_absent():
    ps, gaps, notes = ds.resolve(["PDI"], D, [ev("PDI", 0.2205)], None)
    assert ps == {"PDI": 0.2205} and "panel absent" in notes["PDI"]


# ------------------------------------------------------------- the records

def test_run_day_writes_its_own_file_with_the_combined_line(tmp_path):
    p = tmp_path / "panel.parquet"
    panel([("PDI", D, 0.221)]).to_parquet(p)
    c = FakeClient([ev("PDI", 0.2205), ev("PTY", 0.1188)])
    row = ds.run_day(c, tmp_path, D, held={"PDI": 100, "PTY": -200}, auction_pnl=50.0,
                     now_utc=NOW, panel_path=p)
    want = 100 * 0.2205 - 200 * 0.1188
    assert row["distribution_pnl_usd"] == f"{want:.2f}"
    assert row["auction_pnl_with_distributions_usd"] == f"{50.0 + want:.2f}"
    assert not (tmp_path / "scores.csv").exists()
    assert tuple(rows_of(tmp_path)[0]) == ds.COLUMNS
    # The query window brackets D widely: the API's date filter is not the ex-date.
    (syms, start, end), = c.calls
    assert syms == ("PDI", "PTY") and start < D - dt.timedelta(days=30) and end > D + dt.timedelta(days=60)


def test_an_unmeasured_auction_makes_the_combined_line_unmeasured(tmp_path):
    row = ds.run_day(FakeClient([ev("PDI", 0.2205)]), tmp_path, D, held={"PDI": 100},
                     auction_pnl=None, now_utc=NOW, panel_path=tmp_path / "none.parquet")
    assert row["distribution_pnl_usd"] == "22.05"
    assert row["auction_pnl_with_distributions_usd"] == ds.UNMEASURED


def test_a_day_is_scored_once_even_if_verify_is_rerun(tmp_path):
    args = dict(held={"PDI": 100}, auction_pnl=1.0, now_utc=NOW, panel_path=tmp_path / "x.parquet")
    assert ds.run_day(FakeClient([ev("PDI", 0.2205)]), tmp_path, D, **args) is not None
    assert ds.run_day(FakeClient([ev("PDI", 0.2205)]), tmp_path, D, **args) is None
    assert len(rows_of(tmp_path)) == 1


def test_no_positions_means_nothing_is_entitled_and_no_query(tmp_path):
    c = FakeClient()
    row = ds.run_day(c, tmp_path, D, held={}, auction_pnl=0.0, now_utc=NOW)
    assert row["distribution_pnl_usd"] == "0.00" and c.calls == []


def test_a_file_with_foreign_columns_is_refused(tmp_path):
    (tmp_path / "distribution_scores.csv").write_text("a,b\n1,2\n")
    with pytest.raises(ds.DistError, match="header"):
        ds.run_day(FakeClient([ev("PDI", 0.1)]), tmp_path, D, held={"PDI": 1}, auction_pnl=0.0,
                   now_utc=NOW, panel_path=tmp_path / "x.parquet")


# ------------------------------------------------- inside verify, never the verdict

def _verdict(ok=True, held=None, score=True):
    # The DayScore is built empty; the hook reads only `auction_pnl` from it and
    # takes the held book from `detail`, as verify writes it.
    s = sc.score_day(held={}, fills=[], auction_d=sc.AuctionPrints(),
                     auction_prev=sc.AuctionPrints(), equity=1.0, last_equity=1.0) if score else None
    return vf.Verdict(date=D, book="cef", ok=ok, reason="r", score=s,
                      detail={"held_into_close": held or {}} if score else {})


def test_verify_hook_records_a_failure_as_an_unmeasured_row_and_leaves_the_verdict(tmp_path):
    v = _verdict(ok=True, held={"PDI": 100})
    vf.run_distributions(FakeClient(exc=RuntimeError("data API down")), tmp_path, v)
    assert v.ok is True
    r, = rows_of(tmp_path)
    assert r["distribution_pnl_usd"] == ds.UNMEASURED and "data API down" in r["unmeasured"]


def test_verify_hook_with_no_score_says_why(tmp_path):
    v = _verdict(ok=False, score=False)
    vf.run_distributions(FakeClient(), tmp_path, v)
    r, = rows_of(tmp_path)
    assert "verify produced no score" in r["unmeasured"]


def test_verify_hook_skips_non_trading_days(tmp_path):
    v = _verdict()
    v.date = dt.date(2026, 10, 10)            # a Saturday
    vf.run_distributions(FakeClient(), tmp_path, v)
    assert not (tmp_path / "distribution_scores.csv").exists()


def test_dist_score_never_transmits():
    tree = ast.parse(inspect.getsource(ds))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (attrs | names) & {"submit_order", "post", "delete", "patch", "put", "request"}
