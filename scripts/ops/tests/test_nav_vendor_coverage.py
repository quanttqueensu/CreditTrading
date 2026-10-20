"""Tests for scripts/ops/nav_vendor_coverage.py on synthetic zips (no network, no vendor file)."""
from __future__ import annotations

import datetime as dt
import zipfile

import pytest

from scripts.ops import nav_vendor_coverage as nvc

HEADER = "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"


def _zip(tmp_path, body, member=nvc.MEMBER, header=HEADER):
    p = tmp_path / "supported_tickers.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zi = zipfile.ZipInfo(member, date_time=(2026, 10, 19, 6, 5, 0))
        zf.writestr(zi, header + body)
    return p


def test_reads_rows_and_the_members_own_stamp(tmp_path):
    p = _zip(tmp_path, "JFR,NYSE,ETF,USD,2004-03-25,2026-10-16\n")
    rows, stamp = nvc.read_rows(p)
    assert stamp == "2026-10-19 06:05:00"
    assert rows[0]["ticker"] == "JFR"


def test_missing_member_raises_naming_it(tmp_path):
    p = _zip(tmp_path, "JFR,NYSE,ETF,USD,2004-03-25,2026-10-16\n", member="other.csv")
    with pytest.raises(nvc.CoverageError, match="supported_tickers.csv"):
        nvc.read_rows(p)


def test_missing_column_raises_naming_it(tmp_path):
    p = _zip(tmp_path, "JFR,NYSE,ETF,USD,2004-03-25\n",
             header="ticker,exchange,assetType,priceCurrency,startDate\n")
    with pytest.raises(nvc.CoverageError, match="endDate"):
        nvc.read_rows(p)


def test_coverage_reports_nav_symbol_rows_and_absence_explicitly(tmp_path):
    body = ("JFR,NYSE,ETF,USD,2004-03-25,2026-10-16\n"
            "XJFRX,NMFQS,Mutual Fund,USD,2004-05-13,2026-10-15\n"
            "PDI,NYSE,ETF,USD,2012-05-25,2026-10-16\n")
    rows, _ = nvc.read_rows(_zip(tmp_path, body))
    cov = nvc.coverage(rows, ["JFR", "PDI"])
    assert [r["exchange"] for r in cov["JFR"]["nav"]] == ["NMFQS"]
    assert cov["PDI"]["nav"] == []              # absent is reported, never filled
    assert cov["PDI"]["nav_symbol"] == "XPDIX"


def test_end_date_counts_only_nav_shaped_tickers_on_or_after_since(tmp_path):
    body = ("XJFRX,NMFQS,Mutual Fund,USD,2004-05-13,2026-10-15\n"
            "XMQYX,NMFQS,Mutual Fund,USD,1998-11-18,2026-10-16\n"
            "XOLDX,NMFQS,Mutual Fund,USD,1998-11-18,2019-01-10\n"
            "XNEWX,NMFQS,Mutual Fund,USD,,\n"
            "VINIX,NMFQS,Mutual Fund,USD,1990-07-31,2026-10-16\n"
            "JFR,NYSE,ETF,USD,2004-03-25,2026-10-16\n")
    rows, _ = nvc.read_rows(_zip(tmp_path, body))
    got = nvc.end_date_counts(rows, dt.date(2026, 10, 1))
    assert dict(got) == {"2026-10-15": 1, "2026-10-16": 1}


def test_unreadable_end_date_on_a_nav_symbol_raises(tmp_path):
    rows, _ = nvc.read_rows(_zip(tmp_path, "XJFRX,NMFQS,Mutual Fund,USD,2004-05-13,15/10/2026\n"))
    with pytest.raises(nvc.CoverageError, match="XJFRX"):
        nvc.end_date_counts(rows, dt.date(2026, 10, 1))
