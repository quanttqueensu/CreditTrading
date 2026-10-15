"""The citation check for trial C4's sponsor notices (2026-10-15): a cited quote must occur in its
fetched document, whatever the document's whitespace, tags or typographic quotes. Synthetic text:
a claim about the code."""
from __future__ import annotations

from scripts.data.fetch_sponsor_notices import normalise, quote_found


def test_a_quote_is_found_through_tags_whitespace_and_curly_quotes():
    doc = "<p>the Fund\u2019s stable monthly\n distribution will be <b>adjusted</b> from $0.06&nbsp;per share</p>"
    assert quote_found("the Fund's stable monthly distribution will be adjusted from $0.06 per share", doc)
    assert not quote_found("adjusted from $0.60 per share", doc)
    assert normalise("a\u2013b") == "a-b"
