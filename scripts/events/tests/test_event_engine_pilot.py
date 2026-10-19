"""Tests for the event-engine free pilot: the rules-only extractor and the subagent pilot's inputs and collector.

No network, no model, no cache: every filing below is a literal written in
the shape of `event_engine_sample.render` (a `##### FILING` line, then
`===== DOCUMENT seq=` blocks), modelled on the cover-page conventions of the
sample's dev filings but not copied from any one of them. The v2-versus-v1
tests are the "fails against the old behaviour" check: each pins a v2 rule
change to the dev failure that motivated it, and asserts v1 still behaves as
first frozen (so `--version 1` reproduces the first score).
"""
import pandas as pd
import pytest

from scripts.events import event_engine_pilot as P
from scripts.events import event_engine_rules as R
from scripts.events import event_store as E

SC_TO_I = """##### FILING 0000000000-21-000001 FORM SC TO-I

===== DOCUMENT seq=1 type=SC TO-I file=a.htm desc=SC TO-I

SCHEDULE TO
Example Floating-Rate Income Trust
(Name of Subject Company (Issuer))
Common Shares of Beneficial Interest, $.01 par value
(Title of Class of Securities)
the Transactional Value was calculated by multiplying 19,931,845 shares in the offer
This Schedule TO relates to the Fund's offer to purchase for cash up to 50% or 19,931,845 of its outstanding
common shares upon the terms set forth in the Fund's Offer to Purchase dated June 29, 2021 (the "Offer to Purchase").

===== DOCUMENT seq=2 type=EX-99.(A)(1)(I) file=b.htm desc=OFFER TO PURCHASE

OFFER TO PURCHASE FOR CASH UP TO 50% OR 19,931,845 OF ITS OUTSTANDING COMMON SHARES AT 99% OF NET ASSET VALUE
THE FUND'S OFFER AND WITHDRAWAL RIGHTS WILL EXPIRE AT 5:00 P.M., EASTERN TIME ON JULY 30, 2021, UNLESS THE OFFER IS EXTENDED
The Fund, a closed-end management investment company, approved a tender offer. If more than 50% of the Fund's Shares
are tendered and not withdrawn, any purchases will be made on a pro rata basis.
Section 3. Certain Conditions of the Offer
The Fund will not be required to accept any Shares if such transactions, in the judgment of the Board, would result in
the delisting of the Shares from the New York Stock Exchange, or if there is any suspension of trading.
"""

SC_TO_I_A_GLYPH = """##### FILING 0000000000-21-000002 FORM SC TO-I/A

===== DOCUMENT seq=1 type=SC TO-I/A file=a.htm desc=SC TO-I/A

☒
Check the box if the filing is a final amendment reporting the results of the tender offer.
The Offer expired at one minute past 11:59 p.m. Eastern Time on July 19, 2021.
75,266,484 Shares of the Trust were validly tendered and not withdrawn, and 36,453,372 Shares were accepted for repurchase.
The closed-end fund pays a price equal to 99% of the net asset value per Share.
"""

RIGHTS = """##### FILING 0000000000-21-000003 FORM 424B1

===== DOCUMENT seq=1 type=424B1 file=a.htm desc=424B1

PROSPECTUS
EXAMPLE HEALTHCARE FUND
10,077,635 Shares
Issuable Upon Exercise Of Non-Transferable
Rights
The Fund (the "Trust") is issuing non-transferable rights ("Rights") to its Shareholders of record as of the close of
business on March 8, 2021 (the "Record Date"). These Rights will allow you to subscribe for one (1) common share of
beneficial interest of the Trust for every three (3) Rights held (the "Offer").
You will receive one Right for each whole Share that you hold of record as of the Record Date.
The subscription price per Share (the "Subscription Price") will be determined based upon a formula equal to 95% of the
volume weighted average price of a Share on the NYSE on the date on which the Offer expires. If, however, the Formula
Price is less than 90% of the net asset value ("NAV") per Share, then the Subscription Price will be 90% of NAV.
Shareholders may purchase additional Shares under an over-subscription privilege.
As the Offer expires ON APRIL 6, 2021, Shareholders who exercise will not know the Subscription Price.
The Trust is a non-diversified, closed-end management investment company.
"""

NOTES_SUPPLEMENT = """##### FILING 0000000000-21-000004 FORM 424B2

===== DOCUMENT seq=1 type=424B2 file=a.htm desc=424B2

PRELIMINARY PROSPECTUS SUPPLEMENT
% Notes due
We are offering notes. Our investment objective includes warrants, convertible securities and other rights to acquire
equity securities in a portfolio company. We are a closed-end, non-diversified management investment company that has
elected to be treated as a business development company under the Investment Company Act of 1940.
"""

N14_NAV = """##### FILING 0000000000-21-000005 FORM N-14 8C

===== DOCUMENT seq=1 type=N-14 8C file=a.htm desc=N-14

The Target Fund's common shareholders will receive Acquiring Fund common shares with an aggregate net asset value
equal to the aggregate net asset value of their Target Fund shares. For illustration, a shareholder would have received
1.32 shares of Acquiring Fund common stock for each share of the Target Fund.
The special meeting of shareholders is scheduled to be held on August 24, 2021.
Shareholders of record as of the close of business on May 24, 2021, are entitled to vote.
The Funds are closed-end management investment companies.
"""


def _check_spans(x: dict, text: str) -> None:
    """Every non-null value's quote is verbatim in the text, and its value can be read off it."""
    ev = x["events"][0]
    assert E.verify_spans(ev["kind"], {k: v for k, v in ev["terms"].items() if v}, text) == []


def test_schedule_to_cover_rules():
    x = R.extract("0000000000-21-000001", "SC TO-I", SC_TO_I, ["EXAMPLE FLOATING-RATE INCOME TRUST"])
    assert x["triage"] == {**x["triage"], "kind": "cef_tender", "doc_role": "offer_document",
                           "fund_type": "closed_end_fund"}
    t = {k: (v["value"] if v else None) for k, v in x["events"][0]["terms"].items()}
    assert t["security_class"] == "common"
    assert t["price_basis"] == "pct_of_nav" and t["price_pct_nav"] == 99
    assert t["size_pct_outstanding"] == 50 and t["size_shares"] == 19931845
    assert t["commencement_date"] == "2021-06-29"      # the gold's rule: the Offer to Purchase's date
    assert t["expiration_date"] == "2021-07-30"
    assert t["proration"] is True
    assert {"board_discretion", "listing", "market_disruption"} <= set(t["conditions"])
    assert set(x["events"][0]["terms"]) == {s.name for s in E.FIELDS["cef_tender"]}   # every field present, null if unread
    _check_spans(x, SC_TO_I)


def test_final_amendment_box_glyph_and_pm_clause_are_v2_changes():
    """GDV's '☒ Check the box ...' and Saba's '11:59 p.m.' clause: read in v2, missed in v1 (as first frozen)."""
    x2 = R.extract("0000000000-21-000002", "SC TO-I/A", SC_TO_I_A_GLYPH, ["X"], v=2)
    x1 = R.extract("0000000000-21-000002", "SC TO-I/A", SC_TO_I_A_GLYPH, ["X"], v=1)
    assert x2["triage"]["doc_role"] == "final_result"
    assert x1["triage"]["doc_role"] == "amendment"
    t2 = x2["events"][0]["terms"]
    assert t2["expiration_date"]["value"] == "2021-07-19"
    assert x1["events"][0]["terms"]["expiration_date"] is None
    assert t2["shares_tendered"]["value"] == 75266484 and t2["shares_accepted"]["value"] == 36453372
    _check_spans(x2, SC_TO_I_A_GLYPH)


def test_rights_cover_rules():
    x = R.extract("0000000000-21-000003", "424B1", RIGHTS, ["EXAMPLE HEALTHCARE FUND"])
    assert x["triage"]["kind"] == "rights_offering" and x["triage"]["doc_role"] == "prospectus"
    t = {k: (v["value"] if v else None) for k, v in x["events"][0]["terms"].items()}
    assert t["rights_per_share"] == 1 and t["rights_per_new_share"] == 3
    assert t["price_reference"] == "market" and t["price_pct"] == 95 and t["price_floor_pct_nav"] == 90
    assert t["record_date"] == "2021-03-08" and t["expiration_date"] == "2021-04-06"
    assert t["transferable"] is False and t["over_subscription"] is True
    assert t["max_new_shares"] == 10077635
    _check_spans(x, RIGHTS)


def test_notes_supplement_is_not_a_rights_offering():
    """The sampling rule admitted it on 'other rights to acquire'; triage must say none, and the filer is a BDC."""
    x = R.extract("0000000000-21-000004", "424B2", NOTES_SUPPLEMENT, ["EXAMPLE CAPITAL CORP"])
    assert x["triage"]["kind"] == "none" and x["events"] == []
    assert x["triage"]["fund_type"] == "bdc"


def test_nav_for_nav_beats_an_illustrative_ratio_in_v2():
    x2 = R.extract("0000000000-21-000005", "N-14 8C", N14_NAV, ["X"], v=2)
    x1 = R.extract("0000000000-21-000005", "N-14 8C", N14_NAV, ["X"], v=1)
    t2, t1 = x2["events"][0]["terms"], x1["events"][0]["terms"]
    assert t2["exchange_basis"]["value"] == "nav_for_nav" and t2["exchange_ratio"] is None
    assert t1["exchange_basis"]["value"] == "fixed_ratio"
    assert t2["meeting_date"]["value"] == "2021-08-24" and t2["record_date"]["value"] == "2021-05-24"
    _check_spans(x2, N14_NAV)


def test_unknown_form_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="outside the rules' form map"):
        R.extract("0000000000-21-000006", "10-K", SC_TO_I, ["X"])


def test_split_is_seeded_balanced_and_never_splits_an_episode():
    man = pd.read_csv(R.MANIFEST)
    s = R.split(man)
    assert (s["split"] == "dev").sum() == 25 and (s["split"] == "test").sum() == 25
    assert s.groupby("group")["split"].nunique().max() == 1
    assert s.equals(R.split(man))


# ----------------------------------------------------------------- pilot inputs and collector

def test_excerpt_cuts_at_a_line_break_and_keeps_short_texts_whole():
    text = "a" * 50 + "\n" + "b" * 50 + "\n"
    assert P.excerpt_of(text, 60) == "a" * 50 + "\n"
    assert P.excerpt_of(text, 1000) == text


def test_wrapping_and_parts_leave_the_normalised_text_unchanged():
    text = ("word " * 600).strip() + "\n" + "\n".join(f"line {i}" for i in range(3000)) + "\n"
    wrapped = P.wrap_long_lines(text, width=100)
    assert max(len(x) for x in wrapped.split("\n")) <= 100
    parts = P.split_parts(wrapped, max_chars=5000, max_lines=400)
    assert all(len(p) <= 5000 and p.count("\n") <= 400 for p in parts)
    assert E.normalise("".join(parts)) == E.normalise(text)


def test_batches_respect_the_cap_and_raise_on_an_oversize_filing():
    per_tok = P.S.CHARS_PER_TOKEN
    sizes = {f"f{i}": int(per_tok * t) for i, t in enumerate([44_000, 44_000, 30_000, 10_000, 1_000, 500])}
    order = list(sizes)
    b = P.plan_batches(sizes, order)
    assert sorted(a for x in b for a in x) == sorted(order)
    assert all(sum(P.est_tokens(sizes[a]) for a in x) <= P.BATCH_TOKENS for x in b)
    assert b == P.plan_batches(sizes, order)
    with pytest.raises(ValueError, match="exceeds one batch"):
        P.plan_batches({"big": int(per_tok * (P.BATCH_TOKENS + 1))}, ["big"])


def test_collector_rejects_malformed_reader_json():
    good = {"accession": "A", "triage": {"kind": "cef_tender"},
            "events": [{"kind": "cef_tender", "terms": {"price_pct_nav": None}}]}
    assert P.validate_reader_json(good, "A") == []
    bad = {"accession": "A", "triage": {"kind": "cef_tender"},
           "events": [{"kind": "merger", "terms": {"exchange_ratio": None}}]}
    assert any("differs" in p for p in P.validate_reader_json(bad, "A"))
    extra = {"accession": "A", "triage": {"kind": "cef_tender"},
             "events": [{"kind": "cef_tender", "terms": {"exchange_ratio": None}}]}
    assert any("outside" in p for p in P.validate_reader_json(extra, "A"))
    assert any("file name" in p for p in P.validate_reader_json(good, "B"))
