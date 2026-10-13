"""Gate G1a's computations (`scripts/events/g1a_shortability.py`), on synthetic inputs.

WHY THESE TESTS
---------------
* `deal_components` + `candidates` + `match_readings` decide which deals are
  pending. The failure that matters is SILENT: a new deal that no reading
  covers must raise, never vanish; a deal spanning two readings must raise;
  a merged-away (unlisted) fund must not need a reading.
* `check_readings` is how a stale reading is caught: a "pending" target that
  is gone from Alpaca or shows an effective merger in the feed must raise.
* `share_table` must never count an UNMEASURED name as not shortable, and the
  acquirer unit must count an acquirer once.
* `segment_verdict`: "most" is MORE than half; exactly 1/2 is not most.
* `last_before` is strictly before (a position settled on the announcement
  day itself may already reflect it).
* The two file parsers refuse a changed header and keep IBKR's '>' bound.
* `crsp_identity` must refuse a permno whose share code changed (a CEF that
  became an ETF is not the instrument the pair shorted) and must raise when no
  name record covers the announcement.
Synthetic inputs test the code, not the market. No network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import g1a_shortability as g


def F(rows):
    df = pd.DataFrame(rows, columns=["cik", "form", "kind", "date_filed", "accession", "company", "ticker_now"])
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    return df


def test_components_link_funds_that_share_an_accession():
    f = F([(1, "425", "merger", "2026-07-01", "A1", "ACQ", "AAA"),
           (2, "425", "merger", "2026-07-01", "A1", "TGT", "TTT"),     # same 425 under the target
           (1, "N-14 8C", "merger", "2026-06-01", "A2", "ACQ", "AAA"),
           (3, "425", "merger", "2026-07-02", "B1", "OTHER", "OOO"),
           (4, "DEF 14A", "vote", "2026-07-02", "B1", "X", "XXX")])     # not merger-kind: ignored
    c = g.deal_components(f, pd.Timestamp("2026-01-01"))
    assert sorted(c["ciks"].tolist()) == [(1, 2), (3,)]
    row = c[c["ciks"] == (1, 2)].iloc[0]
    assert row["n14_filers"] == (1,) and row["listed"] == (1, 2)


def test_candidates_need_a_listed_fund_and_a_recent_filing():
    comp = pd.DataFrame({"listed": [(1,), (), (3,)], "last": pd.to_datetime(["2026-09-01", "2026-09-01", "2026-01-01"]),
                         "ciks": [(1,), (2,), (3,)], "tickers": ["A", "", "C"]})
    k = g.candidates(comp, pd.Timestamp("2026-10-09"), gap_days=180)
    assert k["ciks"].tolist() == [(1,)]


def _cands(*listed):
    return pd.DataFrame({"listed": list(listed), "ciks": list(listed), "tickers": ["x"] * len(listed),
                         "first": pd.Timestamp("2026-05-01"), "last": pd.Timestamp("2026-09-01"),
                         "names": ["n"] * len(listed)})


def test_an_unread_candidate_raises():
    R = (g.Reading("A", "pending", frozenset({1, 2}), pairs=(("T", "A"),)),)
    assert g.match_readings(_cands((1, 2)), R)["reading"].tolist() == ["A"]
    with pytest.raises(g.UnreadCandidate):
        g.match_readings(_cands((9,)), R)                  # a new deal nobody has read
    R2 = R + (g.Reading("B", "completed", frozenset({3})),)
    with pytest.raises(g.UnreadCandidate):
        g.match_readings(_cands((1, 3)), R2)               # one component, two readings
    with pytest.raises(g.UnreadCandidate):
        g.match_readings(_cands((1, 5)), R)                # a listed fund outside the reading


def test_check_readings_catches_a_stale_status():
    R = (g.Reading("A", "pending", frozenset({1}), pairs=(("TGT", "ACQ"),)),)
    flags = pd.DataFrame([{"symbol": "TGT", "found": True, "status": "active"}])
    empty = pd.DataFrame(columns=["effective_date", "acquiree_symbol", "acquirer_symbol"])
    assert g.check_readings(R, flags, empty, "2026-10-13")[0]["target_active_today"]
    done = pd.DataFrame([{"effective_date": "2026-10-12", "acquiree_symbol": "TGT", "acquirer_symbol": "ACQ"}])
    with pytest.raises(g.ReadingOutOfDate):
        g.check_readings(R, flags, done, "2026-10-13")      # the feed says it completed
    gone = pd.DataFrame([{"symbol": "TGT", "found": True, "status": "inactive"}])
    with pytest.raises(g.ReadingOutOfDate):
        g.check_readings(R, gone, empty, "2026-10-13")      # the target no longer trades
    future = pd.DataFrame([{"effective_date": "2026-10-16", "acquiree_symbol": "TGT", "acquirer_symbol": "ACQ"}])
    g.check_readings(R, flags, future, "2026-10-13")         # a future-dated row is still pending
    C = (g.Reading("C", "completed", frozenset({1}), pairs=(("TGT", "ACQ"),)),)
    with pytest.raises(g.ReadingOutOfDate):
        g.check_readings(C, flags, empty, "2026-10-13")      # "completed" but still trading, no feed row


def test_share_table_never_counts_unmeasured_as_false():
    df = pd.DataFrame({"segment": ["muni"] * 4 + ["bdc"],
                       "acq": ["A", "A", "B", "C", "D"],
                       "flag": [True, True, None, False, np.nan]}).astype({"flag": object})
    t = g.share_table(df, "flag")
    assert t.loc["muni", "n"] == 4 and t.loc["muni", "measured"] == 3 and t.loc["muni", "true"] == 2
    assert t.loc["muni", "share"] == pytest.approx(2 / 3)
    assert pd.isna(t.loc["bdc", "share"])                  # nothing measured: no share, not 0
    a = g.share_table(df, "flag", unit="acquirer", key="acq")
    assert a.loc["muni", "n"] == 3 and a.loc["muni", "true"] == 1
    with pytest.raises(ValueError):
        g.share_table(df, "flag", unit="acquirer")
    two = pd.DataFrame({"segment": ["muni", "taxable_income"], "acq": ["A", "A"],
                        "flag": [True, True]}).astype({"flag": object})
    b = g.share_table(two, "flag", unit="acquirer", key="acq")
    assert b.loc["muni", "n"] == 1 and b.loc["taxable_income", "n"] == 1 and b.loc["all", "n"] == 1


def test_verdict_most_means_more_than_half():
    assert g.segment_verdict([0.75, 0.6]) == "PASS"
    assert g.segment_verdict([0.5, 0.3]) == "FAIL"          # exactly half is not most
    assert g.segment_verdict([0.5, 0.51]) == "PARTIAL"
    assert g.segment_verdict([None, 0.9]) == "PASS"
    assert g.segment_verdict([None, np.nan]) == "UNMEASURED"


def test_last_before_is_strict():
    d = ["2020-01-15", "2020-01-31", "2020-02-14"]
    assert g.last_before(d, "2020-01-31") == pd.Timestamp("2020-01-15")
    assert g.last_before(d, "2020-02-01") == pd.Timestamp("2020-01-31")
    assert g.last_before(d, "2020-01-15") is None


def test_ibkr_parser_keeps_the_bound_and_refuses_a_bad_file():
    txt = ("#BOF|2026.10.13|18:03:03\n#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|\n"
           "BRW|USD|SABA CAPITAL INCOME &amp; OPPORT|1|X|3.4529|0.4271|700000|B|\n"
           "SPY|USD|SPDR|2|X|3.6|0.25|>10000000|B|\n#EOF\n")
    d, stamp = g.parse_ibkr_shortstock(txt)
    assert stamp == "2026-10-13 18:03:03"
    r = d.set_index("symbol")
    assert r.loc["BRW", "ibkr_name"] == "SABA CAPITAL INCOME & OPPORT" and r.loc["BRW", "available"] == 700000
    assert r.loc["SPY", "available"] == 10_000_000 and bool(r.loc["SPY", "available_gt"])
    with pytest.raises(ValueError):
        g.parse_ibkr_shortstock("SYM|FEE\nX|1\n")
    with pytest.raises(ValueError):
        g.parse_ibkr_shortstock(txt.replace("|0.4271|", "|n/a|"))


def test_finra_parser():
    row = "20200131|MHD|Blackrock Muniholdings Fund, I|A|NYSE|14488|17647||8392|1.73||-17.90|-3159|2020-01-31"
    d = g.parse_finra_si(g.FINRA_HEADER + "\n" + row + "\n", "t")
    assert d.iloc[0]["symbol"] == "MHD" and d.iloc[0]["si_shares"] == 14488
    with pytest.raises(ValueError):
        g.parse_finra_si("a|b\n" + row, "t")
    with pytest.raises(ValueError):
        g.parse_finra_si(g.FINRA_HEADER + "\nMHD|1|2\n", "t")


def test_finra_name_score_tolerates_truncation_not_a_different_fund():
    assert g.finra_name_score("EATON VANCE CA MUNICIPAL BD FD", "Eaton Vance California Municip") >= 0.85
    assert g.finra_name_score("BLACKROCK MUNI INTERM DUR FD INC", "BLACKROCK MUNIYIELD NEW JERSEY") < 0.85


def test_crsp_identity_share_code_and_coverage():
    nm = pd.DataFrame({
        "permno": [1, 1, 2, 3],
        "namedt": pd.to_datetime(["2010-01-01", "2015-01-01", "2010-01-01", "2010-01-01"]),
        "nameendt": pd.to_datetime(["2014-12-31", "2024-12-31", "2024-12-31", "2019-06-30"]),
        "ticker": ["OLD", "NEW", "ETF", "GON"], "comnam": ["A FUND", "A FUND RENAMED", "B ETF", "C FUND"],
        "shrcd": [14, 14, 73, 14]})
    nm.loc[2, "namedt"] = pd.Timestamp("2010-01-01")
    s = pd.DataFrame({"nwperm": [1, 3], "ann": pd.to_datetime(["2012-05-01", "2012-05-01"])})
    out = g.crsp_identity(s, nm)
    assert out.loc[0, "ticker_at_ann"] == "OLD" and out.loc[0, "ticker_today"] == "NEW"
    assert out.loc[0, "crsp_end_state"] == "same_share_code"
    assert out.loc[1, "crsp_end_state"] == "gone_by_crsp_end" and out.loc[1, "ticker_today"] is None
    nm2 = nm.copy()
    nm2.loc[3, "shrcd"] = 14
    nm2 = pd.concat([nm2, pd.DataFrame({"permno": [4, 4], "namedt": pd.to_datetime(["2010-01-01", "2016-01-01"]),
                                        "nameendt": pd.to_datetime(["2015-12-31", "2024-12-31"]),
                                        "ticker": ["CEF", "ETF"], "comnam": ["D", "D"], "shrcd": [14, 73]})])
    out2 = g.crsp_identity(pd.DataFrame({"nwperm": [4], "ann": pd.to_datetime(["2012-01-01"])}), nm2)
    assert out2.loc[0, "crsp_end_state"] == "share_code_changed" and out2.loc[0, "ticker_today"] is None
    with pytest.raises(ValueError):
        g.crsp_identity(pd.DataFrame({"nwperm": [1], "ann": pd.to_datetime(["2009-01-01"])}), nm)


def test_identity_today():
    base = {"crsp_end_state": "same_share_code", "alp_found": True, "alp_status": "active"}
    assert g.identity_today({**base, "alp_name_score": 0.9}) == "same_fund"
    assert g.identity_today({**base, "alp_name_score": 0.2}).startswith("name_mismatch")
    assert g.identity_today({**base, "alp_status": "inactive", "alp_name_score": 0.9}) == "inactive_on_alpaca"
    assert g.identity_today({**base, "alp_found": False}) == "not_on_alpaca"
    assert g.identity_today({**base, "crsp_end_state": "gone_by_crsp_end"}) == "gone_by_crsp_end"


def test_readings_are_well_formed():
    keys = [r.key for r in g.READINGS]
    assert len(keys) == len(set(keys))
    for r in g.READINGS:
        assert r.status in ("pending", "completed", "not_a_merger")
        if r.status == "pending":
            assert r.pairs and r.segment in g.SEGMENTS and r.announced and r.evidence
    seen = [c for r in g.READINGS for c in r.ciks]
    assert len(seen) == len(set(seen)), "a CIK in two readings"
