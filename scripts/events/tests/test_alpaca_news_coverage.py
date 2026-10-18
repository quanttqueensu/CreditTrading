"""The pure parts of the Alpaca news coverage count, on synthetic items.

WHY THESE TESTS
---------------
The deliverable is a set of counts, so the ways a count goes wrong silently
are what is tested:

  * `ny_date`: Alpaca stamps `created_at` in UTC. An article at 01:30Z on
    2026-10-02 was published at 21:30 ET on 2026-10-01. Taking the UTC date
    would push every evening release a day later and make the wire look
    slower than EDGAR. Checked to fail against `ts[:10]`.
  * `article_rows` raises on an item with no `created_at` or `symbols`, rather
    than dropping it from the count.
  * `name_summary` refuses an article that is not tagged with the queried
    symbol (a symbol-query bug would otherwise inflate coverage), and counts
    an article tagged with many tickers as NOT specific.
  * `event_match` takes the EARLIEST relevant article and keeps the sign
    (negative = before EDGAR); an irrelevant article inside the window counts
    toward `any` but not toward `relevant`.

Synthetic inputs test the code, not the market. No network: nothing here
calls `make_client`.
"""
import datetime as dt

import pandas as pd
import pytest

from scripts.events import alpaca_news_coverage as m


def _item(i, ts, syms, headline="", summary=""):
    return {"id": i, "created_at": ts, "symbols": syms, "headline": headline,
            "summary": summary, "source": "benzinga"}


def test_ny_date_converts_utc_evening_to_previous_ny_day():
    assert m.ny_date("2026-10-02T01:30:00Z") == dt.date(2026, 10, 1)
    assert m.ny_date("2026-10-02T14:00:00Z") == dt.date(2026, 10, 2)


def test_ny_date_raises_on_missing_or_naive():
    with pytest.raises(ValueError):
        m.ny_date("")
    with pytest.raises(ValueError):
        m.ny_date("2026-10-02T01:30:00")


def test_article_rows_raises_on_missing_field():
    bad = {"id": 1, "symbols": ["PDI"]}            # no created_at
    with pytest.raises(KeyError):
        m.article_rows([bad], "PDI")


def test_classify_buckets():
    assert m.classify("Fund Announces Tender Offer") == ["tender"]
    assert "distribution" in m.classify("PIMCO Closed-End Funds Declare Monthly Distributions")
    assert m.classify("Shares hit a 52-week low") == []


def test_name_summary_specific_and_tag_check():
    items = [
        _item(1, "2025-03-03T15:00:00Z", ["PDI"], "PDI declares distribution"),
        _item(2, "2025-03-04T15:00:00Z", ["PDI", "PTY", "PCN", "PHK"], "Four funds"),
        _item(3, "2016-05-04T15:00:00Z", ["PDI"], "Rights offering"),
    ]
    df = m.article_rows(items, "PDI")
    s = m.name_summary(df, "PDI", dt.date(2026, 10, 15))
    assert s["n_articles"] == 3
    assert s["n_specific"] == 2                      # the four-ticker item is a list
    assert s["n_2025"] == 2
    assert s["per_year_2016_2025"] == 0.3
    assert s["first"] == "2016-05-04" and s["last"] == "2025-03-04"
    assert s["n_distribution"] == 1 and s["n_rights"] == 1

    untagged = m.article_rows([_item(4, "2025-03-03T15:00:00Z", ["PTY"])], "PDI")
    with pytest.raises(ValueError):
        m.name_summary(untagged, "PDI", dt.date(2026, 10, 15))


def test_name_summary_empty_is_measured_zero():
    s = m.name_summary(m.article_rows([], "XYZ"), "XYZ", dt.date(2026, 10, 15))
    assert s["n_articles"] == 0 and s["first"] is None and s["n_tender"] == 0


def test_event_match_earliest_relevant_and_sign():
    fd = dt.date(2025, 1, 22)
    arts = pd.DataFrame({
        "ny_date": [dt.date(2025, 1, 20), dt.date(2025, 1, 21), dt.date(2025, 1, 23)],
        "text": ["Fund declares distribution", "Fund announces tender offer", "Tender offer commences"],
    })
    r = m.event_match(arts, "tender", fd)
    assert r["any"] and r["n_window"] == 3
    assert r["first_any_offset"] == -2              # the distribution notice
    assert r["relevant"] and r["first_relevant_offset"] == -1


def test_event_match_irrelevant_only_and_unknown_kind():
    fd = dt.date(2025, 1, 22)
    arts = pd.DataFrame({"ny_date": [dt.date(2025, 1, 22)], "text": ["52-week low list"]})
    r = m.event_match(arts, "merger", fd)
    assert r["any"] and not r["relevant"] and r["first_relevant_offset"] is None
    with pytest.raises(ValueError):
        m.event_match(arts, "spinoff", fd)
