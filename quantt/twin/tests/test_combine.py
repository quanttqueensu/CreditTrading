"""combine.py and books.py: targets per strategy, one order a symbol, never re-deciding a plan."""
from __future__ import annotations

import datetime as dt

import pytest

from quantt.twin import books, combine
from quantt.twin.books import BookRead, SlugPlan, TwinRefused
from quantt.twin.tests import fakes as F

S, A = dt.date(2026, 11, 27), dt.date(2026, 11, 25)


def decided(name, slugs):
    return BookRead(book=name, status="decided", why="", slugs=tuple(slugs))


def test_the_combined_target_is_the_sum_and_each_symbol_gets_one_order():
    reads = {"cef": decided("cef", [SlugPlan("cef", "decided", "", {"NAD": -50, "PDI": 100})]),
             "c4": decided("c4", [SlugPlan("c4", "decided", "", {"NAD": 20})]),
             "events": decided("events", [SlugPlan("events/a", "decided", "", {"NAD": 10, "IWM": -5})])}
    plans = combine.slug_plans(reads, {})
    orders, tgt = combine.make_orders(plans, {"NAD": 5}, S, {"NAD": 12.0, "PDI": 20.0, "IWM": 230.0})
    assert tgt == {"IWM": -5, "NAD": -20, "PDI": 100}
    assert sorted((o.symbol, o.side, o.qty) for o in orders) == [("IWM", "sell", 5), ("NAD", "sell", 25),
                                                                 ("PDI", "buy", 100)]
    assert len({o.symbol for o in orders}) == len(orders), "both sides of one symbol"


def test_a_flip_is_one_order_at_ibkr():
    reads = {n: decided(n, [SlugPlan(n, "decided", "", {"PDI": -40} if n == "cef" else {})]) for n in ("cef", "c4")}
    reads["events"] = decided("events", [])
    orders, _ = combine.make_orders(combine.slug_plans(reads, {}), {"PDI": 60}, S, {"PDI": 20.0})
    assert [(o.symbol, o.side, o.qty, o.opens_short) for o in orders] == [("PDI", "sell", 100, True)]


def test_a_book_that_did_not_decide_holds_its_twin_ledger_shares():
    reads = {"cef": books.hold("cef", "no plan"), "c4": decided("c4", [SlugPlan("c4", "decided", "", {})]),
             "events": books.hold("events", "refused")}
    held = {"cef": {"PDI": 100}, "events/a": {"IWM": -5}, "c4": {"MHD": 7}}
    plans = combine.slug_plans(reads, held)
    by = {p.slug: p for p in plans}
    assert by["cef"].targets == {"PDI": 100} and by["cef"].action == "hold"
    assert by["events/a"].targets == {"IWM": -5}
    orders, _ = combine.make_orders(plans, {"PDI": 100, "IWM": -5, "MHD": 7}, S, {"MHD": 11.0})
    assert [(o.symbol, o.qty) for o in orders] == [("MHD", 7)]   # only C4's decided flatten


def test_legacy_is_flattened_and_an_unknown_slug_refuses():
    reads = {n: decided(n, []) for n in ("cef", "c4", "events")}
    plans = combine.slug_plans(reads, {"legacy": {"OLD": 10}})
    assert [(p.slug, p.targets) for p in plans] == [("legacy", {})]
    with pytest.raises(TwinRefused, match="no book"):
        combine.slug_plans(reads, {"nobody": {"X": 1}})


def test_no_order_is_sent_without_a_price():
    reads = {n: decided(n, [SlugPlan(n, "decided", "", {"PDI": 1})]) if n == "cef" else decided(n, [])
             for n in ("cef", "c4", "events")}
    with pytest.raises(TwinRefused, match="PDI"):
        combine.make_orders(combine.slug_plans(reads, {}), {}, S, {})


def test_plan_sha_moves_with_one_share():
    reads = {n: decided(n, [SlugPlan(n, "decided", "", {"PDI": 10})]) if n == "cef" else decided(n, [])
             for n in ("cef", "c4", "events")}
    o1, _ = combine.make_orders(combine.slug_plans(reads, {}), {}, S, {"PDI": 20.0})
    o2, _ = combine.make_orders(combine.slug_plans(reads, {}), {"PDI": 1}, S, {"PDI": 20.0})
    assert combine.plan_sha(o1) != combine.plan_sha(o2)


# -- reading the books' plans ------------------------------------------------------

def test_core_plans_are_read_with_the_books_own_check(tmp_path):
    st = F.make_states(tmp_path)
    plan = F.write_core_plan(st["cef"], "cef", S, A, {"PDI": 100}, {"PDI": 80}, {"PDI": 20.0})
    r = books.read_session_book("cef", st["cef"], S, A)
    assert r.status == "decided" and r.slugs[0].targets == {"PDI": 100} and r.plan_sha == plan["plan_sha"]
    # a hand-edited plan (its orders no longer hash to plan_sha) is one the book would not send: hold
    import json
    p = st["cef"] / S.isoformat() / "plan.json"
    d = json.loads(p.read_text())
    d["orders"][0]["qty"] += 1
    p.write_text(json.dumps(d))
    r = books.read_session_book("cef", st["cef"], S, A)
    assert r.status == "hold" and "hash" in r.why


def test_a_refused_or_stale_plan_holds(tmp_path):
    st = F.make_states(tmp_path)
    F.write_core_plan(st["c4"], "c4", S, A, {"PDI": 1}, {}, {"PDI": 20.0}, status="refused")
    assert books.read_session_book("c4", st["c4"], S, A).status == "hold"
    F.write_core_plan(st["cef"], "cef", S, dt.date(2026, 11, 24), {"PDI": 1}, {}, {"PDI": 20.0})
    r = books.read_session_book("cef", st["cef"], S, A)
    assert r.status == "hold" and "as-of" in r.why
    assert books.read_session_book("cef", st["cef"], dt.date(2026, 11, 30), A).status == "hold"


def test_another_books_plan_in_the_directory_refuses(tmp_path):
    st = F.make_states(tmp_path)
    F.write_core_plan(st["cef"], "c4", S, A, {"PDI": 1}, {}, {"PDI": 20.0})
    with pytest.raises(TwinRefused, match="not 'cef'"):
        books.read_session_book("cef", st["cef"], S, A)


def test_events_sleeves_become_their_own_slugs(tmp_path):
    st = F.make_states(tmp_path)
    F.write_events_plan(st["events"], S, A, {"specdiv_wait": {"IWM": -10, "PDI": 5}, "pead_small_long": {"IWM": -5}},
                        {}, {"IWM": 229.0, "PDI": 19.9})
    r = books.read_events_book(st["events"], S, A)
    assert r.status == "decided"
    assert {s.slug: s.targets for s in r.slugs} == {"events/specdiv_wait": {"IWM": -10, "PDI": 5},
                                                    "events/pead_small_long": {"IWM": -5}}


def test_events_sleeves_that_do_not_sum_to_the_book_refuse_naming_the_symbol(tmp_path):
    st = F.make_states(tmp_path)
    F.write_events_plan(st["events"], S, A, {"a": {"IWM": -10}}, {}, {"IWM": 229.0}, break_sum="IWM")
    with pytest.raises(TwinRefused, match=r"\['IWM'\]"):
        books.read_events_book(st["events"], S, A)


def test_a_non_decided_events_sleeve_keeps_the_targets_its_plan_gives(tmp_path):
    st = F.make_states(tmp_path)
    plan = F.write_events_plan(st["events"], S, A, {"a": {"IWM": -10}, "b": {"PDI": 3}}, {}, {"IWM": 229.0, "PDI": 20.0})
    import json
    from quantt.sleeves.run import _record_sha
    plan["sleeves"][1]["action"], plan["sleeves"][1]["why"] = "hold", "no decision"
    plan["record_sha"] = _record_sha(plan)
    (st["events"] / S.isoformat() / "plan.json").write_text(json.dumps(plan))
    r = books.read_events_book(st["events"], S, A)
    b = {s.slug: s for s in r.slugs}["events/b"]
    assert (b.action, b.targets, b.why) == ("hold", {"PDI": 3}, "no decision")
