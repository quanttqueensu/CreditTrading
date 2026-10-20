"""DG-E1-3's reading pack and collector (scripts/events/e1_failed_reading.py), on synthetic filings.

Claims about the code only. What is pinned:
* a quote copied from the rendered excerpt is found by `quote_in` in the RAW filing (rendering
  changes whitespace only), including across a tag boundary and an HTML entity;
* the SGML header's parties and CIKs are read; an 8-K's press-release exhibit is excerpted;
* outcome windows prefer the strong failure language and are capped;
* batches respect the token cap and the episode cap, deterministically;
* the collector: a quote not in the filing, a cited filing not excerpted and a date that is not
  EDGAR's are problems; in_trial is Y only for a listed pair that failed; the target's and the
  acquirer's readings of one deal share a deal_id; a pair announced twice, years apart, is two deals.
"""
import json

import pandas as pd
import pytest

from scripts.events import e1_failed_reading as fr
from scripts.events import e1_merger_pair as e1
from scripts.events.conditional_tender_census import quote_in

RAW = """<SEC-HEADER>
CONFORMED SUBMISSION TYPE:\t8-K
SUBJECT COMPANY:\t
\tCOMPANY DATA:\t
\t\tCOMPANY CONFORMED NAME:\t\t\tALPHA MUNICIPAL FUND INC
\t\tCENTRAL INDEX KEY:\t\t\t0000000020
FILED BY:\t\t
\tCOMPANY DATA:\t
\t\tCOMPANY CONFORMED NAME:\t\t\tBETA MUNICIPAL FUND
\t\tCENTRAL INDEX KEY:\t\t\t0000000030
</SEC-HEADER>
<DOCUMENT>
<TYPE>8-K
<TEXT>
<html><body><p>Item 8.01 Other Events.</p><p>Alpha&#8217;s Board <b>has terminated</b> the
Agreement and Plan of Reorganization with Beta Municipal Fund (NYSE: BMF).</p></body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.1
<TEXT>
<p>PRESS RELEASE: Alpha Municipal Fund (NYSE: AMF) and Beta Municipal Fund announce that the
proposed reorganization will not proceed.</p>
</TEXT>
</DOCUMENT>
"""


def test_render_changes_whitespace_only():
    r = fr.render(RAW.split("<TEXT>")[1].split("</TEXT>")[0])
    assert "Alpha’s Board has terminated the" in r.replace("\n", " ")
    for q in ("Alpha’s Board has terminated the Agreement and Plan of Reorganization",
              "Alpha's Board has terminated", "Beta Municipal Fund (NYSE: BMF)."):
        assert quote_in(RAW, q)
    from scripts.events.conditional_tender_census import normalise
    body = RAW.split("<TEXT>")[1].split("</TEXT>")[0]
    assert normalise(fr.render(body)) == normalise(body)


def test_header_parties_and_exhibit_excerpt():
    assert fr.sgml_parties(RAW) == [{"role": "SUBJECT COMPANY", "name": "ALPHA MUNICIPAL FUND INC", "cik": 20},
                                    {"role": "FILED BY", "name": "BETA MUNICIPAL FUND", "cik": 30}]
    txt, _ = fr.excerpt_filing(RAW, "8-K")
    assert "exhibit EX-99.1" in txt and "will not proceed" in txt


def test_windows_prefer_failure_language_and_are_capped(monkeypatch):
    filler = "word " * 400
    t = (filler + " the meeting was adjourned " + filler + " the merger was terminated by the boards "
         + filler + " were not approved " + filler + " adjourn again " + filler + " has been withdrawn ")
    w = fr.windows(t, 0)
    assert len(w) == fr.MAX_WINDOWS
    labs = [lab for _, _, lab in w]
    assert labs.count("outcome") == 3          # the three strong matches win over 'adjourn'


def test_batches_respect_caps():
    sizes = {f"e{i}": 30_000 for i in range(25)}
    b = fr.plan_batches(sizes, list(sizes))
    assert all(len(x) <= fr.BATCH_MAX_EPISODES for x in b)
    assert all(sum(sizes[i] for i in x) / fr.CHARS_PER_TOKEN <= fr.BATCH_TOKENS for x in b)
    assert sorted(i for x in b for i in x) == sorted(sizes) and b == fr.plan_batches(sizes, list(sizes))


LISTED = [{"seq": 1, "date": "2015-01-05", "form": "425", "accession": "0000000020-15-000001", "included": True},
          {"seq": 2, "date": "2015-06-01", "form": "8-K", "accession": "0000000020-15-000009", "included": True},
          {"seq": 3, "date": "2015-07-01", "form": "DEF 14A", "accession": "0000000020-15-000010", "included": False}]
DOCS = {"0000000020-15-000001": "Alpha Municipal Fund (NYSE: AMF) will reorganize into Beta Municipal Fund (NYSE: BMF).",
        "0000000020-15-000009": RAW}


def _reading(outcome="terminated", both=True, ann_date="2015-01-05"):
    return {"episode_cik": 20, "episode_accession": "0000000020-15-000001", "episode_role": "target",
            "deals": [{"target": {"name": "Alpha", "cik": 20, "ticker": "AMF"},
                       "acquirer": {"name": "Beta", "cik": 30, "ticker": "BMF"}, "both_listed": both,
                       "listed_quote": {"accession": "0000000020-15-000001", "quote": "(NYSE: BMF)"},
                       "outcome": outcome,
                       "announcement": {"accession": "0000000020-15-000001", "date": ann_date,
                                        "quote": "will reorganize into Beta Municipal Fund"},
                       "outcome_evidence": {"accession": "0000000020-15-000009", "date": "2015-06-01",
                                            "quote": "has terminated the Agreement and Plan of Reorganization"},
                       "notes": ""}], "problems": ""}


def test_validate_finds_quote_citation_and_date_problems():
    eid = "20_0000000020-15-000001"
    get = DOCS.__getitem__
    assert fr.validate(_reading(), eid, LISTED, get) == []
    bad = _reading()
    bad["deals"][0]["outcome_evidence"]["quote"] = "the merger was completed"
    assert any("quote not found" in p for p in fr.validate(bad, eid, LISTED, get))
    bad = _reading()
    bad["deals"][0]["outcome_evidence"]["accession"] = "0000000020-15-000010"   # listed but not excerpted
    assert any("not an excerpted filing" in p for p in fr.validate(bad, eid, LISTED, get))
    assert any("differs from EDGAR" in p for p in fr.validate(_reading(ann_date="2015-01-06"), eid, LISTED, get))
    assert any("not stated" in p for p in fr.validate(_reading(outcome=None), eid, LISTED, get))


def test_rows_in_trial_and_deal_ids():
    eid = "20_0000000020-15-000001"
    r1 = fr.to_rows(_reading(), eid, LISTED, "m", "2026-10-20")[0]
    assert r1["in_trial"] == "Y" and r1["fail_date"] == "2015-06-01" and r1["counterparty_cik"] == 30
    assert fr.to_rows(_reading(both=False, outcome="not_a_listed_pair"), eid, LISTED, "m", "d")[0]["in_trial"] == "N"
    assert fr.to_rows(_reading(outcome="completed"), eid, LISTED, "m", "d")[0]["fail_quote"] == ""
    # the acquirer's episode reads the same deal; a second proposal of the pair three years later
    r2 = {**r1, "episode_cik": "30", "episode_accession": "0000000030-15-000002"}
    r3 = {**r1, "episode_accession": "0000000020-18-000001", "ann_date": "2018-03-01"}
    r4 = {**r1, "target_cik": "", "_k": 0}
    R = pd.DataFrame([r1, r2, r3, r4])
    ids = fr.assign_deal_ids(R)
    assert ids[0] == ids[1] == "20>30" and ids[2] == "20>30#2" and ids[3].startswith("ep20:")


def test_collect_writes_the_file_stage0_reads(tmp_path, monkeypatch):
    root = tmp_path / "pack"
    (root / "input").mkdir(parents=True)
    (root / "out" / "sonnet").mkdir(parents=True)
    eid = "20_0000000020-15-000001"
    (root / "input" / "plan.json").write_text(json.dumps(
        {"batches": [{"batch": "01", "episodes": [{"id": eid}]}], "filings": {eid: LISTED}}))
    (root / "out" / "sonnet" / f"{eid}.json").write_text(json.dumps(_reading()))
    (root / "out" / "sonnet" / "_batch_01.json").write_text(json.dumps({"batch": "01", "model_id": "claude-sonnet-x"}))
    monkeypatch.setattr(e1, "OUT_DIR", tmp_path / "e1")
    monkeypatch.setattr(e1, "READINGS", tmp_path / "e1" / "r.csv")

    class C:
        def get_text(self, url):
            acc = url.rsplit("/", 1)[1][:-4]
            return DOCS[acc]
    out = fr.collect(root, "sonnet", partial=False, client=C())
    R = pd.read_csv(tmp_path / "e1" / "r.csv", dtype=str, keep_default_na=False)
    assert list(R.columns) == list(e1.READING_COLUMNS) and out["in_trial_deals"] == 1
    assert R.loc[0, "read_by"] == "claude-sonnet-x (batch 01)" and R.loc[0, "deal_id"] == "20>30"
    cen = pd.DataFrame({"episode_cik": [20], "episode_accession": ["0000000020-15-000001"]})
    _, probs = e1.check_readings(cen, C())
    assert probs == []                          # what the collector writes passes Stage 0's own check
    (root / "out" / "sonnet" / f"{eid}.json").unlink()
    with pytest.raises(e1.GateError, match="no reading"):
        fr.collect(root, "sonnet", partial=False, client=C())


def test_episode_text_shows_every_filing_and_points_duplicates(monkeypatch):
    rows = [("0000000020-15-000001", "425", "2015-01-05"), ("0000000020-15-000002", "425", "2015-01-06"),
            ("0000000020-15-000009", "8-K", "2015-06-01")]
    fl = pd.DataFrame({"accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows],
                       "filingDate": pd.to_datetime([r[2] for r in rows])})
    monkeypatch.setattr(fr, "episode_filings", lambda client, cik, first: fl)
    press = RAW.replace("8-K", "425").split("<DOCUMENT>")[0] + "<DOCUMENT>\n<TYPE>425\n<TEXT>\n<p>Alpha will reorganize into Beta.</p>\n</TEXT>\n</DOCUMENT>\n"
    docs = {"0000000020-15-000001": press, "0000000020-15-000002": press, "0000000020-15-000009": RAW}

    class C:
        def get_text(self, url):
            return docs[url.rsplit("/", 1)[1][:-4]]
    ep = pd.Series({"episode_cik": 20, "episode_accession": "0000000020-15-000001", "first_date": "2015-01-05",
                    "first_form": "425", "company_last": "ALPHA MUNICIPAL FUND INC"})
    txt, listed = fr.episode_text(C(), ep)
    by = {x["accession"]: x for x in listed}
    assert by["0000000020-15-000002"]["why"] == "identical text to seq=1"
    assert by["0000000020-15-000001"]["mode"] == "full" and by["0000000020-15-000009"]["included"]
    assert "has terminated" in txt and txt.count("Alpha will reorganize into Beta.") == 1


def test_assign_deal_ids_keeps_two_series_of_one_trust_apart():
    base = {"episode_cik": "35315", "episode_accession": "a", "target_cik": "35315", "acquirer_cik": "1562565",
            "ann_date": "2024-10-03"}
    R = pd.DataFrame([{**base, "_k": 0}, {**base, "_k": 1}])
    ids = fr.assign_deal_ids(R)
    assert list(ids) == ["35315>1562565", "35315>1562565/2"]


def _nm_dl():
    nm = pd.DataFrame({"permno": [1, 2, 3, 4], "ticker": ["AMF", "BMF", "OEF", "TGM"],
                       "namedt": pd.to_datetime(["2000-01-01"] * 4), "nameendt": pd.to_datetime(["2024-12-31"] * 4),
                       "shrcd": [14, 14, 73, 14], "exchcd": [1, 1, 3, 1], "comnam": ["A", "B", "C", "D"]})
    dl = pd.DataFrame({"permno": [4], "dlstdt": pd.to_datetime(["2016-03-01"]), "dlstcd": [231], "nwperm": [2]})
    return nm, dl


def test_triage_classes():
    nm, dl = _nm_dl()
    cen = pd.DataFrame({"episode_cik": ["20", "21", "22", "23", "24", "25"], "episode_accession": ["a"] * 6,
                        "first_date": ["2015-01-05"] * 6})
    row = {c: "" for c in e1.READING_COLUMNS}
    rows = [
        {**row, "episode_cik": "20", "episode_accession": "a", "target_ticker": "AMF", "acquirer_ticker": "BMF",
         "outcome": "withdrawn", "ann_date": "2015-01-05", "outcome_date": "2015-06-01"},          # T1 via CRSP listing
        {**row, "episode_cik": "21", "episode_accession": "a", "target_ticker": "AMF", "acquirer_ticker": "BMF",
         "outcome": "superseded", "both_listed": "Y", "ann_date": "2023-09-08", "fail_date": "2025-06-09"},  # T2
        {**row, "episode_cik": "22", "episode_accession": "a", "target_ticker": "AMF", "acquirer_ticker": "OEF",
         "outcome": "", "ann_date": "2015-01-05"},                                                   # C3: listing unsettled, own fund unlisted
        {**row, "episode_cik": "23", "episode_accession": "a", "target_ticker": "TGM", "acquirer_ticker": "BMF",
         "outcome": "", "ann_date": "2015-06-01"},                                                   # C1: CRSP merger within 730 days
        {**row, "episode_cik": "24", "episode_accession": "a", "outcome": ""},                       # I3 or C3 by own listing
        {**row, "episode_cik": "25", "episode_accession": "a", "outcome": ""},
    ]
    T = fr.triage(pd.DataFrame(rows), cen, nm, dl, {"24_a": True, "25_a": False})
    # OEF is an ETF (share code 73): no CEF permno, so that pair's listing is unsettled, not "N"
    assert list(T["triage"]) == ["T1", "T2", "C3", "C1", "I3", "C3"]
    assert T.loc[0, "crsp_listed_pair"] == "Y" and T.loc[3, "crsp_target_merged_730d"] == "Y"
    assert list(T["can_change_trial"])[:2] == ["Y", "Y"] and T.loc[5, "can_change_trial"] == "N"


def test_failed_deal_rows_take_one_deal_read_from_four_episodes(monkeypatch):
    nm, _ = _nm_dl()
    monkeypatch.setattr(e1.ce, "universe_permnos", lambda nm: {"XXX": [99]})
    monkeypatch.setattr(e1, "spec_names", lambda: set())
    row = {c: "" for c in e1.READING_COLUMNS}
    base = {**row, "deal_id": "902722>1137391", "in_trial": "Y", "outcome": "vote_failed", "target_ticker": "AMF",
            "acquirer_ticker": "BMF", "ann_date": "2009-10-26"}
    R = pd.DataFrame([{**base, "episode_cik": c, "fail_date": f} for c, f in
                      (("902722", "2009-12-28"), ("1169027", "2009-12-29"), ("1176196", "2009-12-28"), ("1181027", "2009-12-29"))])
    D = e1.failed_deal_rows(R, nm)
    assert len(D) == 1 and D.loc[0, "fail_date"] == pd.Timestamp("2009-12-28") and D.loc[0, "ann"] == pd.Timestamp("2009-10-26")
