"""Tests for scripts/events/event_store.py: schema, time keys, the point-in-time query, validation, subtract-only.

No network and no model call: every input is a literal. Each test names the
failure it guards against; the ones on the time key and the point-in-time
query were checked to fail against the naive version (noted per test).
"""
from datetime import date, datetime, timezone

import pytest

from scripts.events import event_store as E

UTC = timezone.utc


def row(row_id="edgar:0000000000-21-000001:0", kind="cef_tender", observed="2021-06-29T21:03:25Z",
        recorded="2021-06-29T21:10:00Z", symbols=("EVG",), **kw):
    return E.EventRow(row_id=row_id, source=kw.pop("source", "edgar"), kind=kind, observed_at=observed,
                      recorded_at=recorded, symbols=list(symbols), **kw)


# ----------------------------------------------------------------- schema

def test_schema_has_the_eight_kinds_and_triage():
    assert set(E.KINDS) == {"cef_tender", "merger", "liquidation", "rights_offering",
                            "conditional_tender_programme", "activist_13d", "spac", "equity_mna", "none"}
    for k, specs in E.FIELDS.items():
        names = [s.name for s in specs]
        assert len(names) == len(set(names)), k
        for s in specs:
            assert s.dtype in ("number", "percent", "date", "bool", "enum", "text", "set")
            if s.dtype in ("enum", "set"):
                assert s.enum, f"{k}.{s.name} needs its allowed values"


def test_row_rejects_terms_outside_the_schema():
    with pytest.raises(ValueError, match="not in the cef_tender schema"):
        row(terms={"exchange_ratio": {"value": 1.0, "span": "x"}})


def test_value_without_span_is_refused():
    with pytest.raises(ValueError, match="source span"):
        E.FieldValue(value=98.0, span="")


def test_naive_times_are_refused():
    with pytest.raises(ValueError):
        row(observed="2021-06-29T21:03:25")


def test_instructions_render_every_field():
    txt = E.agent_instructions()
    for specs in E.FIELDS.values():
        for s in specs:
            assert f"`{s.name}`" in txt


# ----------------------------------------------------------------- time keys

def test_header_time_is_eastern_not_utc():
    # 0001140361-21-005674: index page "Accepted 2021-02-22 17:09:11" (EST) -> 22:09:11Z.
    # A parser that treated the digits as UTC would say 17:09Z and fail this.
    assert E.parse_header_acceptance("20210222170911") == datetime(2021, 2, 22, 22, 9, 11, tzinfo=UTC)
    # Summer (EDT, -4h): 0000350797-21-000080, 17:03:25 ET -> 21:03:25Z.
    assert E.parse_header_acceptance("20210629170325") == datetime(2021, 6, 29, 21, 3, 25, tzinfo=UTC)


def test_api_offset_error_is_detected_and_header_used():
    # The submissions API gave 2021-02-23T03:09:11Z for the filing accepted 17:09:11 EST.
    t, verdict = E.acceptance_from_edgar("20210222170911", "2021-02-23T03:09:11.000Z")
    assert verdict == "api_offset_error"
    assert t == datetime(2021, 2, 22, 22, 9, 11, tzinfo=UTC)
    t, verdict = E.acceptance_from_edgar("20210629170325", "2021-06-29T21:03:25.000Z")
    assert verdict == "agree"


def test_other_disagreement_raises():
    with pytest.raises(E.TimeKeyError):
        E.acceptance_from_edgar("20210222170911", "2021-02-22T23:09:11Z")


def test_observed_at_holds_an_evening_filing_until_its_filing_date():
    # KYN N-14 8C: header 2021-10-22 18:06:45 ET (Friday), EDGAR filing date Monday 2021-10-25.
    acc = E.parse_header_acceptance("20211022180645")
    obs = E.observed_at(acc, date(2021, 10, 25))
    assert obs == datetime(2021, 10, 25, 10, 0, tzinfo=UTC)          # 06:00 EDT Monday
    # Keyed on acceptance it would reach Friday's 22:00 ET decision: the lookahead this prevents.
    assert acc < E.research_decision_time(date(2021, 10, 22)) < obs
    # A same-day filing is unchanged: EVG SC TO-I accepted 17:03:25 ET on its filing date.
    same = E.parse_header_acceptance("20210629170325")
    assert E.observed_at(same, date(2021, 6, 29)) == same
    with pytest.raises(E.TimeKeyError):
        E.observed_at(same, date(2021, 6, 28))


def test_filing_date_rule():
    # 17:09 ET on a Monday: same day. 22:09 ET (what the API implied): next day.
    assert E.filing_date_consistent(datetime(2021, 2, 22, 22, 9, 11, tzinfo=UTC), date(2021, 2, 22), "SC TO-I")
    assert not E.filing_date_consistent(datetime(2021, 2, 23, 3, 9, 11, tzinfo=UTC), date(2021, 2, 22), "SC TO-I")
    # Friday 17:38 ET -> Monday's filing date (XAI 424B2, 2021-02-05 -> 2021-02-08).
    assert E.filing_date_consistent(datetime(2021, 2, 5, 22, 38, 5, tzinfo=UTC), date(2021, 2, 8), "424B2")
    # A 13D at 21:00 ET keeps its day (10 p.m. cut-off); an SC TO-C at 21:00 does not.
    t = datetime(2021, 3, 2, 2, 0, tzinfo=UTC)  # 21:00 EST on 2021-03-01
    assert E.filing_date_consistent(t, date(2021, 3, 1), "SC 13D")
    assert not E.filing_date_consistent(t, date(2021, 3, 1), "SC TO-C")
    # Clough 424B2 accepted 17:30:45 ET kept its day (transmission began before the cut-off).
    assert E.filing_date_consistent(E.parse_header_acceptance("20210521173045"), date(2021, 5, 21), "424B2")
    # ...but 18:06 ET on the same day must not.
    assert not E.filing_date_consistent(E.parse_header_acceptance("20210521180600"), date(2021, 5, 21), "424B2")


def test_research_decision_time_is_22_et():
    assert E.research_decision_time(date(2021, 6, 29)) == datetime(2021, 6, 30, 2, 0, tzinfo=UTC)
    assert E.research_decision_time(date(2021, 2, 22)) == datetime(2021, 2, 23, 3, 0, tzinfo=UTC)


# ----------------------------------------------------------------- store

def test_append_chain_dedupe_and_tamper(tmp_path):
    p = tmp_path / "events.jsonl"
    s = E.EventStore(p)
    assert s.append(row())
    assert not s.append(row(recorded="2021-06-30T00:00:00Z"))   # same content: at-least-once is safe
    with pytest.raises(E.StoreIntegrityError, match="different content"):
        s.append(row(symbols=("EVF",)))
    s.append(row(row_id="edgar:0000000000-21-000002:0", observed="2021-08-03T20:07:15Z",
                 recorded="2021-08-03T20:10:00Z"))
    E.EventStore(p).verify_chain()
    lines = p.read_text().splitlines()
    p.write_text(lines[0].replace("EVG", "EVX") + "\n" + lines[1] + "\n")
    with pytest.raises(E.StoreIntegrityError):
        E.EventStore(p)


def test_events_at_excludes_the_future(tmp_path):
    s = E.EventStore(tmp_path / "e.jsonl")
    s.append(row("a", observed="2021-06-29T21:03:25Z", recorded="2021-06-29T21:05:00Z"))
    s.append(row("b", observed="2021-06-30T21:00:00Z", recorded="2021-06-30T21:05:00Z"))
    got = [r.row_id for r in s.events_at(E.research_decision_time(date(2021, 6, 29)))]
    assert got == ["a"]   # a naive "latest rows" read would also return b


def test_a_filing_after_the_cutoff_misses_that_evening_only_if_after_22et(tmp_path):
    # Accepted 17:24 ET (header) -> visible at the 22:00 ET decision. The API's
    # double-converted 21:24 ET would still be visible; 22:09 ET (the Feb case) would not.
    s = E.EventStore(tmp_path / "e.jsonl")
    s.append(row("feb", observed="2021-02-23T03:09:11Z", recorded="2021-02-23T03:10:00Z"))
    assert s.events_at(E.research_decision_time(date(2021, 2, 22))) == []
    s2 = E.EventStore(tmp_path / "e2.jsonl")
    s2.append(row("feb", observed="2021-02-22T22:09:11Z", recorded="2021-02-22T22:10:00Z"))
    assert [r.row_id for r in s2.events_at(E.research_decision_time(date(2021, 2, 22)))] == ["feb"]


def test_correction_applies_only_from_its_recorded_time(tmp_path):
    s = E.EventStore(tmp_path / "e.jsonl")
    s.append(row("x", terms={"price_pct_nav": {"value": 95.0, "span": "95%"}},
                 recorded="2021-06-29T21:05:00Z"))
    s.append(row("x-fix", source="review", supersedes="x", terms={"price_pct_nav": {"value": 98.0, "span": "98%"}},
                 recorded="2021-07-01T15:00:00Z"))
    before = s.events_at(datetime(2021, 6, 30, tzinfo=UTC))
    after = s.events_at(datetime(2021, 7, 2, tzinfo=UTC))
    assert [r.row_id for r in before] == ["x"]
    assert [r.row_id for r in after] == ["x-fix"]


def test_backfilled_rows_are_visible_to_research_only_when_asked(tmp_path):
    s = E.EventStore(tmp_path / "e.jsonl")
    s.append(row("bf", observed="2021-06-29T21:03:25Z", recorded="2026-10-15T12:00:00Z", backfilled=True))
    t = datetime(2021, 6, 30, 3, tzinfo=UTC)
    assert [r.row_id for r in s.events_at(t, include_backfilled=True)] == ["bf"]
    assert s.events_at(t, include_backfilled=False) == []


def test_a_backfilled_row_observed_after_t_never_leaks(tmp_path):
    # The case the observed_at filter exists for: research replaying 2021 with rows
    # extracted in 2026. A row observable only on 2021-07-01 must not reach 2021-06-30.
    s = E.EventStore(tmp_path / "e.jsonl")
    s.append(row("late", observed="2021-07-01T20:00:00Z", recorded="2026-10-15T12:00:00Z", backfilled=True))
    assert s.events_at(datetime(2021, 6, 30, 3, tzinfo=UTC), include_backfilled=True) == []


def test_a_row_cannot_be_recorded_before_it_was_observable():
    with pytest.raises(ValueError, match="before observed_at"):
        row(observed="2021-06-29T21:03:25Z", recorded="2021-06-29T21:00:00Z")


def test_correction_cannot_predate_its_target(tmp_path):
    s = E.EventStore(tmp_path / "e.jsonl")
    s.append(row("x", observed="2021-06-29T20:00:00Z", recorded="2021-06-29T21:05:00Z"))
    with pytest.raises(E.StoreIntegrityError, match="before the row it corrects"):
        s.append(row("y", source="review", supersedes="x", observed="2021-06-29T20:00:00Z",
                     recorded="2021-06-29T21:00:00Z"))


# ----------------------------------------------------------------- validation

TEXT = ("The Fund is offering to purchase up to 20% of its outstanding Common Shares at a price equal to "
        "98% of the net asset value per share determined as of the close of the regular trading session "
        "of the New York Stock Exchange on August 2, 2021. If more than 2,520,567 Shares are tendered, "
        "the Fund will purchase Shares on a pro rata basis.")


def test_spans_found_after_normalisation():
    norm = E.normalise(TEXT)
    assert E.span_in_text("price equal to 98%   of the net asset value", norm)
    assert E.span_in_text("PRICE EQUAL TO 98 % OF THE NET ASSET VALUE", norm)
    assert not E.span_in_text("price equal to 95% of the net asset value", norm)


def test_c1_controls_and_zero_width_characters_do_not_break_a_match():
    # GDL: cp1252 curly quotes decoded as Latin-1 arrive as U+0093/U+0094.
    text = "the \x93Fund\x94 may offer\u200b rights"
    norm = E.normalise(text)
    assert E.span_in_text('the "Fund" may offer rights', norm)
    assert E.span_in_text("the \u201cFund\u201d may offer rights", norm)


def test_value_in_span():
    assert E.value_in_span(2520567, "number", "If more than 2,520,567 Shares are tendered")
    assert not E.value_in_span(2520576, "number", "If more than 2,520,567 Shares are tendered")
    assert E.value_in_span("2021-08-02", "date", "on August 2, 2021")
    assert not E.value_in_span("2021-08-03", "date", "on August 2, 2021")
    assert E.value_in_span(98.0, "percent", "98% of the net asset value")
    assert E.value_in_span(None, "number", "x") is None
    # 100% of NAV stated in words (FS Global Credit, MSC Income), and not a stray 100.
    assert E.value_in_span(100, "percent", "The Offer is for cash at a price equal to the NAV per Share")
    assert not E.value_in_span(100, "percent", "at a price equal to 98% of the NAV per Share")


def test_counted_fields_skip_the_value_check():
    terms = {"n_targets": {"value": 2, "span": "the reorganizations of PKO and PCI with and into PDI"}}
    assert E.verify_spans("merger", terms, "the reorganizations of PKO and PCI with and into PDI") == []


def test_verify_spans_reports_each_failure_kind():
    terms = {
        "price_pct_nav": {"value": 98.0, "span": "98% of the net asset value per share"},
        "size_pct_outstanding": {"value": 25.0, "span": "up to 20% of its outstanding Common Shares"},
        "expiration_date": {"value": "2021-08-02", "span": "on August 9, 2021"},
        "conditions": {"value": ["market_disruption"], "spans": []},
    }
    f = {(x.field, x.reason) for x in E.verify_spans("cef_tender", terms, TEXT)}
    assert ("price_pct_nav", "value_not_in_span") not in f
    assert ("size_pct_outstanding", "value_not_in_span") in f
    assert ("expiration_date", "span_not_in_text") in f
    assert ("conditions", "missing_span") in f


def test_consistency_checks():
    t = {"shares_tendered": {"value": 10_000_000}, "shares_accepted": {"value": 2_520_567},
         "proration_factor_pct": {"value": 25.2}, "price_pct_nav": {"value": 98.0},
         "final_price_per_share": {"value": 9.80}}
    assert E.consistency_checks("cef_tender", t, nav_per_share=10.0) == []
    t["proration_factor_pct"] = {"value": 30.0}
    assert any("proration_factor" in b for b in E.consistency_checks("cef_tender", t))
    assert any("final price" in b for b in E.consistency_checks("cef_tender", t, nav_per_share=10.5))


def test_review_queue_puts_live_path_kinds_on_held_names_first():
    r = row(confidence=0.99)
    assert E.review_reasons(r, [], held={"EVG"})[0] == "P1"
    assert E.review_reasons(r, [], held={"HYT"}) == ("none", [])
    q, why = E.review_reasons(row(confidence=0.5), [], held=set())
    assert q == "P2" and "confidence" in why[0]


# ----------------------------------------------------------------- subtract-only

def test_subtract_only_never_adds_grows_or_flips():
    plan = {"EVG": -300, "HYT": -100, "PDI": 200, "MHD": -50}
    held = {"EVG": 100, "HYT": -200, "PDI": 0, "MHD": 0}
    kinds = {"EVG": {"cef_tender"}, "HYT": {"merger"}, "MHD": {"UNPARSED:SC TO-C"}}
    new, log = E.subtract_only(plan, held, kinds, events_fresh=True)
    assert new == {"EVG": -100, "PDI": 200}     # EVG sells to flat only; HYT adds no short; MHD unparsed -> blocked
    for s, q in new.items():
        assert abs(q) <= abs(plan[s]) and q * plan[s] > 0
    assert set(new) <= set(plan)


def test_stale_events_block_every_new_short_but_not_longs_or_covers():
    plan = {"A": -10, "B": 20, "C": 5}
    held = {"A": 0, "B": 0, "C": -5}
    new, log = E.subtract_only(plan, held, {}, events_fresh=False)
    assert new == {"B": 20, "C": 5}
    assert log and "stale" in log[0]


def test_restrictive_kinds_treats_unparsed_as_its_form():
    rows = [row("u", kind="none", status="UNPARSED", form="SC TO-C"), row("n", kind="none", symbols=("HYT",))]
    k = E.restrictive_kinds(rows)
    assert k == {"EVG": {"UNPARSED:SC TO-C"}}
