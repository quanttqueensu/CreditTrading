"""Tests for the A2 insider-buying zero-trial gate (scripts/events/a2_insider_buying.py).

Synthetic frames and in-memory ZIPs only: these test the METHOD (the holdout
refusals, the cache layout, the extraction join, the inherited event rules, the
sleeve-identical z, the shift(2) outcome windows, the control mask, the matched
contrast and its second method, the gate's verdicts), never a claim about the
market. Nothing here opens a socket or reads an env file: the fetch test passes
an explicit contact string and a fake session to the EDGAR client.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from scripts.data.edgar_client import EdgarClient, RateLimiter, cache_path
from scripts.events import a2_insider_buying as A

pd.set_option("compute.use_numexpr", False)


# ------------------------------------------------------------------ holdout refusals

def test_fetch_urls_cover_2006q1_to_2022q4_and_refuse_2023():
    urls = A.fetch_urls()
    zips = [u for u in urls if u.endswith("_form345.zip")]
    idx = [u for u in urls if u.endswith("master.gz")]
    assert len(zips) == 68 and zips[0].endswith("2006q1_form345.zip") and zips[-1].endswith("2022q4_form345.zip")
    assert len(idx) == 60 and "/2008/QTR1/" in idx[0] and "/2022/QTR4/" in idx[-1]
    assert not any("2023" in u for u in urls)
    with pytest.raises(A.HoldoutError):
        A.fetch_urls(last=(2023, 1))


def test_assert_pre_holdout_raises_on_a_2023_date():
    A.assert_pre_holdout(pd.to_datetime(["2022-12-30"]), "ok")
    with pytest.raises(A.HoldoutError):
        A.assert_pre_holdout(pd.to_datetime(["2022-12-30", "2023-01-03"]), "x")


def test_guard_untouched_raises_on_a_comparison_set_name(monkeypatch):
    monkeypatch.setattr(A, "untouched_names", lambda: ["EDD", "VVR"])
    A.guard_untouched(["PDI", "BDJ"], "ok")
    with pytest.raises(A.HoldoutError):
        A.guard_untouched(["PDI", "VVR"], "x")


# ------------------------------------------------------------------ caches and the team lead's fetch

def test_cached_body_reads_the_client_layout_and_names_the_url_on_a_miss(tmp_path):
    url = A.ZIP_URL.format(y=2010, q=1)
    p = cache_path(url, tmp_path / "a")
    p.parent.mkdir(parents=True)
    p.write_bytes(b"body")
    body, src = A.cached_body(url, [tmp_path / "missing", tmp_path / "a"])
    assert body == b"body" and src == tmp_path / "a"
    with pytest.raises(FileNotFoundError, match="2010q2"):
        A.cached_body(A.ZIP_URL.format(y=2010, q=2), [tmp_path / "a"])


class _Resp:
    def __init__(self, content: bytes):
        self.status_code, self.content = 200, content


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return _Resp(b"x" * 10)


def test_fetch_goes_through_the_client_caches_and_caps(tmp_path):
    sess = _Session()
    c = EdgarClient(user_agent="Test Person test@example.com", session=sess, cache=tmp_path,
                    limiter=RateLimiter(min_interval=0.125, sleep=lambda s: None))
    rec = A.fetch(max_live=1000, client=c)
    assert rec["live_requests"] == len(A.fetch_urls()) == len(sess.urls)
    rec2 = A.fetch(max_live=1000, client=c)                    # closed quarters: cache only
    assert rec2["live_requests"] == rec["live_requests"]
    c2 = EdgarClient(user_agent="Test Person test@example.com", session=_Session(), cache=tmp_path / "b",
                     limiter=RateLimiter(min_interval=0.125, sleep=lambda s: None))
    with pytest.raises(RuntimeError, match="live-request cap"):
        A.fetch(max_live=3, client=c2)


# ------------------------------------------------------------------ extraction

def _tsv(cols, rows):
    return ("\t".join(cols) + "\n" + "".join("\t".join(r) + "\n" for r in rows)).encode()


def _zip(sub_rows, own_rows, tr_rows, drop_col=None):
    sub_cols = A.SUB_COLS
    own_cols = A.OWN_COLS
    tr_cols = [c for c in A.TR_COLS if c != drop_col]
    tr_rows = [[v for c, v in zip(A.TR_COLS, r) if c != drop_col] for r in tr_rows]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("SUBMISSION.tsv", _tsv(sub_cols, sub_rows))
        z.writestr("REPORTINGOWNER.tsv", _tsv(own_cols, own_rows))
        z.writestr("NONDERIV_TRANS.tsv", _tsv(tr_cols, tr_rows))
    return b.getvalue()


SUB = [["0001-22-000001", "05-JAN-2022", "03-JAN-2022", "4", "0000000111", "Fund One", "FND"],
       ["0001-22-000002", "05-JAN-2022", "03-JAN-2022", "4", "0000000999", "Operating Co", "OPC"]]
OWN = [["0001-22-000001", "0000005000", "Doe Jane", "Director", ""],
       ["0001-22-000002", "0000005001", "Roe Rick", "Officer", ""]]
TR = [["0001-22-000001", "1", "Common Shares", "03-JAN-2022", "P", "1000", "10.5", "A", "D"],
      ["0001-22-000001", "2", "Common Shares", "03-JAN-2022", "A", "50", "0", "A", "D"],
      ["0001-22-000002", "3", "Common Stock", "03-JAN-2022", "P", "10", "5", "A", "D"]]


def test_extract_quarter_keeps_fund_p_and_s_rows_with_their_owner():
    p, d = A.extract_quarter(_zip(SUB, OWN, TR), "2022Q1", {111})
    assert len(p) == 1 and p.issuercik.iloc[0] == 111 and p.ownercik.iloc[0] == 5000
    assert p.TRANS_CODE.iloc[0] == "P" and p.FILING_DATE.iloc[0] == pd.Timestamp("2022-01-05")
    assert p.TRANS_SHARES.iloc[0] == 1000.0 and d["p_s_rows_all_issuers"] == 2


def test_extract_quarter_raises_on_a_missing_column():
    with pytest.raises(KeyError, match="TRANS_PRICEPERSHARE"):
        A.extract_quarter(_zip(SUB, OWN, TR, drop_col="TRANS_PRICEPERSHARE"), "2022Q1", {111})


# ------------------------------------------------------------------ owners, purchases, events

def _rows(**over):
    base = {"ACCESSION_NUMBER": "a1", "NONDERIV_TRANS_SK": "1", "SECURITY_TITLE": "Common Shares",
            "TRANS_DATE": pd.Timestamp("2015-03-02"), "FILING_DATE": pd.Timestamp("2015-03-03"),
            "TRANS_CODE": "P", "TRANS_SHARES": 100.0, "TRANS_PRICEPERSHARE": 10.0,
            "TRANS_ACQUIRED_DISP_CD": "A", "DOCUMENT_TYPE": "4", "issuercik": 1, "ownercik": 7,
            "RPTOWNER_RELATIONSHIP": "Director", "RPTOWNERNAME": "Doe Jane", "RPTOWNER_TXT": None,
            "ISSUERTRADINGSYMBOL": "FND", "ISSUERNAME": "Fund"}
    base.update(over)
    return base


def test_owner_classes_follow_the_census_rule():
    f = pd.DataFrame([_rows(), _rows(RPTOWNER_RELATIONSHIP="Other", RPTOWNERNAME="Acme Advisors LLC"),
                      _rows(RPTOWNER_RELATIONSHIP="Other", RPTOWNERNAME="Smith Bob", RPTOWNER_TXT="Affiliate of investment adviser"),
                      _rows(RPTOWNER_RELATIONSHIP="Other", RPTOWNERNAME="Smith Bob"),
                      _rows(RPTOWNER_RELATIONSHIP="TenPercentOwner", RPTOWNERNAME="Saba Capital Management, L.P."),
                      _rows(RPTOWNER_RELATIONSHIP="Other", RPTOWNERNAME="Big Insurance Company")])
    assert list(A.classify_owners(f)) == ["DO", "adviser", "adviser", "other_person", "ten_pct_only", "other_entity"]


def test_qualifying_drops_amendments_grants_bad_dates_preferreds_and_activists():
    rows = pd.DataFrame([
        _rows(),
        _rows(NONDERIV_TRANS_SK="2", DOCUMENT_TYPE="4/A"),
        _rows(NONDERIV_TRANS_SK="3", TRANS_ACQUIRED_DISP_CD="D"),
        _rows(NONDERIV_TRANS_SK="4", TRANS_PRICEPERSHARE=0.0),
        _rows(NONDERIV_TRANS_SK="5", TRANS_DATE=pd.Timestamp("2013-01-01")),
        _rows(NONDERIV_TRANS_SK="6", SECURITY_TITLE="Auction Rate Preferred Shares"),
        _rows(NONDERIV_TRANS_SK="7", RPTOWNER_RELATIONSHIP="TenPercentOwner", RPTOWNERNAME="Saba Capital"),
        _rows(NONDERIV_TRANS_SK="8", TRANS_CODE="S", TRANS_ACQUIRED_DISP_CD="D")])
    d, diag = A.qualifying(rows, "P")
    assert list(d.NONDERIV_TRANS_SK) == ["1"] and d.usd.iloc[0] == 1000.0
    assert diag["date_error_rows_dropped"] == 1
    s, _ = A.qualifying(rows, "S")
    assert list(s.NONDERIV_TRANS_SK) == ["8"]


def _q(day, owner=7, sk=None):
    f = pd.Timestamp("2015-01-01") + pd.Timedelta(days=day)
    return _rows(ACCESSION_NUMBER=f"a{day}-{owner}", NONDERIV_TRANS_SK=sk or f"{day}{owner}", TRANS_DATE=f,
                 FILING_DATE=f, ownercik=owner)


def test_fund_events_respect_the_90_day_gap_and_the_owner_count():
    d = pd.DataFrame([_q(0), _q(30), _q(100), _q(105, owner=8)])
    d["oclass"], d["usd"] = "DO", 1000.0
    ev = A.fund_events(d, 1)
    assert list(ev.event_date) == [pd.Timestamp("2015-01-01"), pd.Timestamp("2015-04-11")]
    ev2 = A.fund_events(d, 2)
    assert list(ev2.event_date) == [pd.Timestamp("2015-04-16")] and ev2.n_owners.iloc[0] == 2


# ------------------------------------------------------------------ z and outcome windows

def _sleeve_z(disc, w):
    # The lines of src/deploy/sleeves/cef_discount.py target_positions, copied.
    mu = disc.rolling(w, min_periods=120).mean().shift(1)
    sd = disc.rolling(w, min_periods=120).std().shift(1)
    return ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)


def test_zscore_is_the_sleeve_formula_and_uses_nothing_after_t():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2010-01-01", periods=400)
    disc = pd.DataFrame({"X": rng.normal(-8, 2, 400)}, index=idx)
    z = A.zscore(disc, 252)
    pd.testing.assert_frame_equal(z, _sleeve_z(disc, 252))
    t = 300
    d2 = disc.copy()
    d2.iloc[t + 1:] = 99.0                                   # change the future only
    assert A.zscore(d2, 252).iloc[t, 0] == z.iloc[t, 0]


def _pan(px, nav, dist=None, split=None):
    idx = px.index
    return {"px": px, "nav": nav, "vol": px * 0 + 1000.0,
            "dist": dist if dist is not None else px * 0.0,
            "split": split if split is not None else px * 0.0,
            "group": pd.Series({c: "g" for c in px.columns}), "sub": pd.Series({c: "s" for c in px.columns})}


def test_post_event_windows_run_from_the_fill_close_shift2():
    idx = pd.bdate_range("2015-01-01", periods=40)
    px = pd.DataFrame({"X": np.linspace(9.0, 10.0, 40)}, index=idx)
    nav = pd.DataFrame({"X": np.full(40, 10.0)}, index=idx)
    dist = px * 0.0
    dist.iloc[10, 0] = 0.05                                   # an ex-date inside the window
    f = A.outcome_frames(_pan(px, nav, dist), 252)
    t, h = 3, 21
    disc = 100 * (px.X / nav.X - 1)
    assert f[f"dd_{h}"].iloc[t, 0] == pytest.approx(disc.iloc[t + 1 + h] - disc.iloc[t + 1])
    p = px.X.values
    d = dist.X.values
    tr = np.prod([(p[i] + d[i]) / p[i - 1] for i in range(t + 2, t + 2 + h)]) - 1
    assert f[f"px_{h}"].iloc[t, 0] == pytest.approx(tr)
    assert np.isnan(f[f"px_{h}"].iloc[40 - h - 1, 0])          # runs past the panel: NaN, never filled
    assert f["prof_-1"].iloc[t, 0] == pytest.approx(disc.iloc[t - 1] - disc.iloc[t])


def test_a_split_or_a_missing_close_inside_a_window_drops_it():
    idx = pd.bdate_range("2015-01-01", periods=40)
    px = pd.DataFrame({"X": np.full(40, 9.0)}, index=idx)
    nav = pd.DataFrame({"X": np.full(40, 10.0)}, index=idx)
    split = px * 0.0
    split.iloc[12, 0] = 1.0
    f = A.outcome_frames(_pan(px, nav, split=split), 252)
    assert np.isnan(f["dd_5"].iloc[8, 0]) and np.isnan(f["px_5"].iloc[8, 0])
    assert not np.isnan(f["dd_5"].iloc[0, 0])
    px2 = px.copy()
    px2.iloc[25, 0] = np.nan
    g = A.outcome_frames(_pan(px2, nav), 252)
    assert np.isnan(g["px_5"].iloc[20, 0]) and not np.isnan(g["px_5"].iloc[10, 0])


def test_control_mask_excludes_63_before_to_66_after_a_filing():
    idx = pd.bdate_range("2015-01-01", periods=300)
    pan = {"px": pd.DataFrame({"X": np.ones(300), "Y": np.ones(300)}, index=idx)}
    m = A.control_mask(pan, {"X": [idx[150]]})
    bad = m.X[~m.X]
    assert bad.index[0] == idx[150 - A.CTRL_POST] and bad.index[-1] == idx[150 + A.CTRL_PRE]
    assert m.Y.all()


# ------------------------------------------------------------------ the contrast and its second method

def test_matched_excess_and_clustered_mean():
    C = pd.DataFrame({"g": ["a", "a", "b", "b"], "ym": ["m1", "m1", "m2", "m2"], "y": [1.0, 3.0, 10.0, 12.0]})
    E = pd.DataFrame({"g": ["a", "b", "c"], "ym": ["m1", "m2", "m3"], "y": [4.0, 9.0, 5.0]})
    m = A.matched_excess(E, C, ["g"], ["y"])
    assert list(m.x_y.iloc[:2]) == [2.0, -2.0] and np.isnan(m.x_y.iloc[2])
    r = A.clustered(pd.Series([1.0, 3.0, 2.0, 4.0]), pd.Series(["a", "a", "b", "b"]))
    assert r["mean"] == 2.5 and r["G"] == 2
    assert r["se"] == pytest.approx(np.sqrt(2 / 1 * ((-1.0) ** 2 + 1.0 ** 2)) / 4)


def test_fe_estimate_recovers_a_planted_effect():
    rng = np.random.default_rng(3)
    n = 4000
    C = pd.DataFrame({"cell": rng.integers(0, 40, n), "ym": rng.integers(0, 40, n)})
    C["y"] = C.cell * 0.3 + rng.normal(0, 0.2, n)
    E = pd.DataFrame({"cell": rng.integers(0, 40, 400), "ym": rng.integers(0, 40, 400)})
    E["y"] = E.cell * 0.3 + 0.5 + rng.normal(0, 0.2, 400)
    r = A.fe_estimate(E, C, ["cell"], "y")
    assert r["beta"] == pytest.approx(0.5, abs=0.05) and r["t"] > 10


# ------------------------------------------------------------------ timing, links, the gate

def test_acceptance_hours_convert_utc_to_eastern_with_dst():
    h = A.accept_hours_et(pd.Series(["2022-07-01T20:30:00.000Z", "2022-01-03T21:30:00.000Z"]))
    assert list(h) == [16.5, 16.5]                              # EDT is UTC-4, EST is UTC-5
    assert list(A.accept_hours_et(pd.Series(["2022-07-01T20:30:00.000Z"]), 5.0)) == [11.5]


def test_link_symbols_needs_one_permno_spanning_the_date():
    names = pd.DataFrame({"permno": [1, 2, 3, 4], "ticker": ["ABC", "ABC", "XY", "XY"],
                          "namedt": pd.to_datetime(["2000-01-01", "2016-01-01", "2000-01-01", "2000-01-01"]),
                          "nameendt": pd.to_datetime(["2015-12-31", "2024-12-31", "2024-12-31", "2024-12-31"]),
                          "shrcls": [None, None, "A", "B"], "shrcd": 14, "comnam": "x"})
    ev = pd.DataFrame({"symbol": ["ABC", "ABC", "XY", "XY.B", "NONE"],
                       "event_date": pd.to_datetime(["2010-05-05", "2018-05-05", "2018-05-05", "2018-05-05", "2018-05-05"])})
    r = A.link_symbols(ev, names)
    assert list(r.permno.astype("float").fillna(-1)) == [1, 2, -1, 4, -1]
    assert list(r.link) == ["exact", "exact", "ambiguous", "class_suffix", "none"]


def test_days_since_filing():
    filed = np.array(pd.to_datetime(["2015-02-10", "2015-05-08"]).values)
    d = A.days_since_filing(pd.Series(pd.to_datetime(["2015-01-05", "2015-02-10", "2015-03-01"])), filed)
    assert np.isnan(d[0]) and list(d[1:]) == [0.0, 19.0]


def _main(p_dd, p_t, m2_dd, s_dd, px_bp):
    rows = [("purchases", "m1_group_month_zbin", "dd_21", p_dd, p_t),
            ("purchases", "m2_fund_year_zbin", "dd_21", m2_dd, 1.0),
            ("sales_placebo", "m1_group_month_zbin", "dd_21", s_dd, 1.0),
            ("purchases", "m1_group_month_zbin", "px_21", px_bp, 1.0)]
    return pd.DataFrame(rows, columns=["sample", "method", "outcome", "mean_excess", "t"])


def test_gate_verdicts():
    epy = pd.Series(80, index=range(2006, 2023))
    assert A.gate(_main(0.15, 1.1, -0.3, -0.1, 9.0), epy, None)["verdict"].startswith("CLOSE at zero trials: G2")
    assert A.gate(_main(0.5, 2.5, 0.2, 0.4, 60.0), epy, None)["verdict"].startswith("CLOSE at zero trials: G3")
    assert A.gate(_main(0.5, 2.5, 0.2, -0.1, 10.0), epy, None)["verdict"].startswith("WATCH (D2)")
    assert A.gate(_main(0.5, 2.5, 0.2, -0.1, 60.0), epy, None)["verdict"].startswith("PASS")
    assert A.gate(_main(0.5, 2.5, 0.2, -0.1, 60.0), epy * 0 + 10, None)["verdict"].startswith("D7")


def test_pull_crsp_links_bdc_events_only_and_asks_crsp_for_their_permnos():
    class _CE:
        CACHE = "fake"

        def __init__(self):
            self.asked = None

        def names(self):
            return pd.DataFrame({"permno": [11, 22], "ticker": ["BDCX", "CEFY"], "shrcls": [None, None],
                                 "namedt": pd.to_datetime(["2000-01-01"] * 2),
                                 "nameendt": pd.to_datetime(["2024-12-31"] * 2)})

        def daily(self, permnos):
            self.asked = list(permnos)
            return pd.DataFrame({"permno": permnos})

    ev = pd.DataFrame({"symbol": ["BDCX", "CEFY"], "kind": ["BDC", "CEF"],
                       "event_date": pd.to_datetime(["2015-05-05", "2015-05-05"])})
    ce = _CE()
    rec = A.pull_crsp({"ev_P": ev, "ev_S": ev.iloc[:0]}, ce=ce)
    assert ce.asked == [11] and rec["bdc_permnos"] == 1
