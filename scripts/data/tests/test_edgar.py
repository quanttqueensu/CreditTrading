"""The EDGAR client and the event fetcher's parsers (plan 0.7), on literal strings.

WHY THESE TESTS
---------------
* The client is the only thing between this desk and an SEC block. The tests
  pin what the fair-access page asks for (https://www.sec.gov/os/accessing-edgar-data):
  the declared User-Agent and Accept-Encoding headers on every request, a
  spacing that never exceeds 10 requests a second, a bounded back-off on
  403/429/503 that ends in an exception rather than a loop, and a contact
  string that never appears in a repr.
* The index parser decides every date and form in the event table. A shifted
  column would put a date in the form field and nothing would error, so it
  must raise on every malformed shape.
* Episode grouping is where announcement and termination dates come from.

No network: a fake session stands in for `requests` (the root conftest blocks
sockets anyway). Synthetic strings test the code, not EDGAR.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.data import edgar_client as ec
from scripts.data import fetch_edgar_events as fe

UA = "Example Desk research@example.org"


# ------------------------------------------------------------------ client

class FakeResp:
    def __init__(self, status, body=b"ok"):
        self.status_code, self.content = status, body


class FakeSession:
    def __init__(self, statuses):
        self.statuses, self.calls = list(statuses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers)))
        return FakeResp(self.statuses.pop(0), b"body:" + url.encode())


def _client(tmp_path, statuses, backoff=(1.0, 2.0)):
    slept = []
    lim = ec.RateLimiter(clock=lambda: 0.0, sleep=lambda s: None)
    c = ec.EdgarClient(user_agent=UA, session=FakeSession(statuses), limiter=lim,
                       cache=tmp_path, backoff=backoff, sleep=slept.append)
    return c, slept


def test_headers_follow_the_sec_sample(tmp_path):
    c, _ = _client(tmp_path, [200])
    c.get("https://www.sec.gov/Archives/edgar/full-index/2015/QTR2/master.gz")
    _, h = c._session.calls[0]
    assert h == {"User-Agent": UA, "Accept-Encoding": "gzip, deflate", "Host": "www.sec.gov"}


def test_host_header_follows_the_url(tmp_path):
    c, _ = _client(tmp_path, [200])
    c.get("https://data.sec.gov/submissions/CIK0001160990.json")
    assert c._session.calls[0][1]["Host"] == "data.sec.gov"


def test_backoff_then_success(tmp_path):
    c, slept = _client(tmp_path, [429, 403, 200])
    assert c.get("https://www.sec.gov/files/x.json").startswith(b"body:")
    assert slept == [1.0, 2.0] and len(c._session.calls) == 3


def test_backoff_is_bounded_and_raises(tmp_path):
    c, slept = _client(tmp_path, [503, 503, 503])
    with pytest.raises(ec.EdgarHTTPError, match="HTTP 503 after 3"):
        c.get("https://www.sec.gov/files/x.json")
    assert slept == [1.0, 2.0]


def test_404_is_not_retried(tmp_path):
    c, slept = _client(tmp_path, [404])
    with pytest.raises(ec.EdgarNotFound):
        c.get("https://www.sec.gov/files/x.json")
    assert slept == [] and len(c._session.calls) == 1


def test_cache_hit_makes_no_request_and_manifest_has_no_header(tmp_path):
    c, _ = _client(tmp_path, [200])
    u = "https://www.sec.gov/files/x.json"
    a = c.get(u)
    b = c.get(u)
    assert a == b and len(c._session.calls) == 1 and c.n_cache_hits == 1
    man = (tmp_path / "_manifest.jsonl").read_text()
    assert "example.org" not in man and "User-Agent" not in man


def test_offline_miss_raises(tmp_path):
    c = ec.EdgarClient(cache=tmp_path, offline=True)
    with pytest.raises(ec.EdgarHTTPError, match="offline"):
        c.get("https://www.sec.gov/files/x.json")


def test_only_sec_hosts(tmp_path):
    c, _ = _client(tmp_path, [200])
    with pytest.raises(ValueError):
        c.get("https://efts.sec.gov/LATEST/search-index?q=x")
    with pytest.raises(ValueError):
        c.get("http://www.sec.gov/files/x.json")


def test_repr_redacts_the_contact(tmp_path):
    c, _ = _client(tmp_path, [])
    assert "example.org" not in repr(c) and "<redacted>" in repr(c)


def test_rate_limiter_spacing_is_under_the_sec_ceiling():
    t = [0.0]
    waits = []

    def sleep(s):
        waits.append(s)
        t[0] += s

    lim = ec.RateLimiter(clock=lambda: t[0], sleep=sleep)
    for _ in range(5):
        lim.wait()
    assert waits == [ec.MIN_INTERVAL_S] * 4
    assert 1.0 / ec.MIN_INTERVAL_S < ec.SEC_MAX_REQUESTS_PER_SECOND
    with pytest.raises(ValueError):
        ec.RateLimiter(min_interval=0.05)


@pytest.mark.parametrize("bad", ["", "   ", "Just A Name", "nobody@nowhere", "a@b.org\r\nX: y",
                                 "solo@example.org"])
def test_user_agent_validation_never_echoes(bad):
    with pytest.raises(ec.EdgarConfigError) as e:
        ec.validate_user_agent(bad)
    if bad.strip():
        assert bad.strip() not in str(e.value)


def test_user_agent_read_from_env_file_not_environ(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"SEC_USER_AGENT={UA}\n")
    monkeypatch.setenv("SEC_USER_AGENT", "Wrong Person wrong@example.com")
    assert ec.load_user_agent({"QUANTT_ENV_FILE": str(env)}) == UA
    env.write_text("OTHER=1\n")
    with pytest.raises(ec.EdgarConfigError, match="SEC_USER_AGENT not set"):
        ec.load_user_agent({"QUANTT_ENV_FILE": str(env)})


# ------------------------------------------------------------------ parser

HEAD = """Description:           Master Index of EDGAR Dissemination Feed
Last Data Received:    June 30, 2015

CIK|Company Name|Form Type|Date Filed|Filename
--------------------------------------------------------------------------------
"""


def test_parse_master_index():
    txt = HEAD + ("1195739|NUVEEN NEW YORK AMT-FREE MUNICIPAL INCOME FUND|425|2012-06-22|"
                  "edgar/data/1195739/0001193125-12-280520.txt\n"
                  "868449|NUVEEN NEW YORK INVESTMENT QUALITY MUNICIPAL FUND INC|N-14 8C|2012-07-03|"
                  "edgar/data/868449/0001193125-12-290001.txt\n")
    df = fe.parse_master_index(txt, "t")
    assert list(df["form"]) == ["425", "N-14 8C"]
    assert df["accession"].iloc[0] == "0001193125-12-280520"
    assert df["date_filed"].iloc[1] == pd.Timestamp("2012-07-03")
    assert fe.parse_master_index(txt, "t", keep_forms={"425"})["cik"].tolist() == [1195739]


@pytest.mark.parametrize("line", [
    "1195739|NAME|425|2012-06-22",                                             # 4 fields
    "1195739|NAME|425|06/22/2012|edgar/data/1195739/0001193125-12-280520.txt",  # date format
    "11957x9|NAME|425|2012-06-22|edgar/data/1195739/0001193125-12-280520.txt",  # CIK
    "1195739|NAME|425|2012-06-22|edgar/data/9999999/0001193125-12-280520.txt",  # path CIK differs
    "1195739|NAME|425|2012-06-22|edgar/data/1195739/0001193125-12-28052.txt",   # accession shape
    "1195739|NAME||2012-06-22|edgar/data/1195739/0001193125-12-280520.txt",     # empty form
])
def test_parse_master_index_raises_on_malformed_lines(line):
    with pytest.raises(fe.IndexParseError):
        fe.parse_master_index(HEAD + line + "\n", "t", keep_forms={"N-2"})  # raises even if not kept


def test_parse_master_index_needs_the_header():
    with pytest.raises(fe.IndexParseError):
        fe.parse_master_index("CIK|Company Name|Form Type|Date Filed\n-----\n", "t")


def test_quarters_and_closure():
    from datetime import date
    assert fe.quarters(date(2008, 2, 1), date(2008, 12, 31)) == [(2008, 1), (2008, 2), (2008, 3), (2008, 4)]
    assert fe.quarters(date(2025, 11, 1), date(2026, 1, 2)) == [(2025, 4), (2026, 1)]
    assert not fe.quarter_is_closed(2026, 3, date(2026, 10, 5))
    assert fe.quarter_is_closed(2026, 3, date(2026, 10, 8))
    assert fe.quarter_is_closed(2025, 4, date(2026, 1, 8))


def test_fund_set_rules():
    idx = pd.DataFrame({"cik": [1, 2, 2, 3, 4], "form": ["N-2", "N-CSR", "4", "N-CSR", "3"]})
    assert fe.fund_set(idx) == {1: "marker_form", 2: "ncsr_insider"}


def _f(rows):
    df = pd.DataFrame(rows, columns=["cik", "form", "date_filed"])
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    df["kind"] = df["form"].map(fe.FORM_KIND)
    df["accession"] = [f"0000000000-00-{i:06d}" for i in range(len(df))]
    return df


def test_episodes_tender_dates_and_gap():
    f = _f([(7, "SC TO-C", "2019-06-18"), (7, "SC TO-I", "2019-06-25"), (7, "SC TO-I/A", "2019-07-29"),
            (7, "SC TO-I", "2023-08-15"), (7, "SC TO-I/A", "2023-09-20")])
    ep = fe.episodes(f)
    assert len(ep) == 2
    e = ep.iloc[0]
    assert (str(e.first_date), e.first_form, str(e.commence_date), str(e.last_date)) == \
           ("2019-06-18", "SC TO-C", "2019-06-25", "2019-07-29")


def test_episodes_merger_dereg_window():
    f = _f([(9, "425", "2012-06-22"), (9, "425", "2012-09-01"), (9, "N-8F", "2013-05-01"),
            (9, "N-8F", "2016-01-01")])
    ep = fe.episodes(f)
    assert len(ep) == 1 and str(ep.iloc[0].dereg_date) == "2013-05-01"
    # a gap longer than 180 days starts a new merger episode
    f2 = _f([(9, "425", "2012-01-01"), (9, "425", "2012-08-01")])
    assert len(fe.episodes(f2)) == 2


def test_every_event_form_has_one_kind():
    assert fe.FORM_KIND["SC TO-I"] == "tender" and fe.FORM_KIND["N-14 8C"] == "merger"
    assert fe.FORM_KIND["8-K"] == "current" and fe.FORM_KIND["424B2"] == "offering"
    assert "N-14" not in fe.MARKER_FORMS  # plain N-14 is an open-end merger registration
