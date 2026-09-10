"""Preflight is the gate every scheduled session passes through. Test the gate.

`test_halt_scope.py` already covers `check_halt`. This file covers the three
other checks that can be exercised without a broker socket:

  phantom_books  added 2026-09-10, after a book dead since 2026-07-30 halted
                 the benchmarks session over ANGL
  costs          "the check that would have prevented the whole 2026-07-31
                 incident" (its own docstring)
  data           a stale NAV is not a cheap fund, it is a blind one

WHAT THESE TESTS ARE ACTUALLY PROTECTING
----------------------------------------
Preflight's design rule is that a failed check DOWNGRADES a session rather than
cancelling it: `arm` goes false, `collect` stays true. That makes the
`blocking` flag on each Check load-bearing in both directions. A check wrongly
marked blocking stops a $500k strategy over another book's bookkeeping — which
is exactly what happened twice in two days before halts were scoped. A check
wrongly marked non-blocking lets a session trade on a signal built from a NAV
that no longer exists. So every test below asserts `blocking` as well as `ok`.

NO BROKER, NO NETWORK, NO LIVE LEDGERS. `preflight.REPO_ROOT` is redirected at
`tmp_path` and the fixtures are built there. The only real files read are book
specs and frozen specs under `ops/specs/` — never `ops/books/*_live/`, which
holds the only record of real fills.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import preflight  # noqa: E402

SHADOW = "_ibkr" + "_shadow"     # matches ops/preflight.py:332; never written to


@pytest.fixture
def books(tmp_path, monkeypatch):
    """An `ops/books/` tree under tmp_path, with preflight pointed at it."""
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    d = tmp_path / "ops" / "books"
    d.mkdir(parents=True)
    return d


def _spec_book(books, filename, sleeves):
    """Write a book spec whose sleeves carry an inline universe."""
    (books / filename).write_text(json.dumps({
        "book_id": filename.replace("_book.json", ""),
        "sleeves": [{"name": n, "enabled": True,
                     "spec": {"frozen": {"universe": list(u)}}}
                    for n, u in sleeves.items()],
    }))


def _ledger_dir(books, book_dir, sleeve):
    """The shape `check_phantom_books` reads as "this sleeve has traded":
    `ops/books/<book>_live/_ibkr_shadow/<sleeve>/`."""
    p = books / book_dir / SHADOW / sleeve
    p.mkdir(parents=True)
    return p


def _copy_real(books, tmp_path, book_rel):
    """Copy a REAL book spec and the frozen specs it points at into the fixture.

    The specs are the fact under test — how many symbols a book contests, and
    under which sleeve names — so inventing a lookalike would test the lookalike.
    `spec_path` is resolved by preflight against REPO_ROOT (ops/preflight.py:359),
    which the `books` fixture has already redirected at tmp_path, so the relative
    layout is reproduced verbatim.
    """
    src = REPO / book_rel
    spec = json.loads(src.read_text())
    (books / src.name).write_text(src.read_text())
    for s in spec["sleeves"]:
        rel = s["spec_path"]
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((REPO / rel).read_text())
    return [s["name"] for s in spec["sleeves"]]


# -- phantom books: the 2026-09-10 check ----------------------------------

def test_a_book_that_has_never_held_a_share_but_claims_symbols_is_reported(
        books, tmp_path):
    """2026-09-09 17:25: a corpse halted benchmarks_paper over ANGL.

    credit_rv was killed 2026-07-30 (sealed holdout net SR -1.44). Its spec
    stayed in `ops/books/`, and `IBKRBroker._foreign_book_claims()` counts any
    `*.json` there carrying a `sleeves` list as a live sibling in the shared
    paper account — so its 21 symbols stayed CONTESTED for the books still
    trading, and arm() demanded a per-sleeve ledger entry for each of them.

    The real retired spec is used here, so the count this asserts is the count
    the dead book actually claimed.
    """
    names = _copy_real(books, tmp_path, "ops/books/retired/credit_rv_book.json")
    assert names == ["credit_rv"]

    chk = preflight.check_phantom_books()

    assert chk.ok is False
    assert "credit_rv_book.json" in chk.detail
    assert "credit_rv" in chk.detail
    assert "21 symbols" in chk.detail, \
        f"claim count changed; the check read: {chk.detail}"
    assert "retired" in chk.detail, "the warning must say what to do about it"


def test_the_phantom_warning_can_never_stop_a_session(books, tmp_path):
    """NON-BLOCKING BY CONSTRUCTION.

    This reports a fault in ANOTHER book's bookkeeping. Making it blocking would
    reproduce the failure it exists to describe: on 2026-09-09 a $20k benchmark
    book's missing ledger row wrote a GLOBAL halt and nearly blocked the $500k
    CEF session at 22:45. A dead book's spec is never a reason to stop the book
    in front of us from trading.
    """
    _copy_real(books, tmp_path, "ops/books/retired/credit_rv_book.json")
    chk = preflight.check_phantom_books()

    assert chk.ok is False
    assert chk.blocking is False
    assert repr(chk).startswith("[WARN]")


def test_a_book_with_a_shadow_ledger_directory_is_not_reported(books):
    """"Has never held a share" is tested against the ledger, not the filename.

    The ledger directory is not named after the spec — `cef_discount_book.json`
    lives at `ops/books/cef_live/` — so any filename-derived rule would flag
    every live book at once and be switched off within a session.
    """
    _spec_book(books, "live_book.json", {"some_sleeve": ["HYG", "JNK"]})
    _ledger_dir(books, "some_live", "some_sleeve")

    chk = preflight.check_phantom_books()

    assert chk.ok is True
    assert chk.detail == "no dead books claiming symbols"


def test_a_book_known_only_to_attribution_json_is_not_reported(books):
    """A sleeve can be real while its shadow ledger is missing.

    On 2026-07-31 a costs.yaml KeyError froze the ledger at the funding row
    while the account filled $2.07M gross; `_attribution.json`, rebuilt from
    broker fills, was the only record that those positions belonged to anyone.
    A book in that state is broken, but it is emphatically not dead, and calling
    it a phantom would tell someone to retire a book that holds live shares.
    """
    _spec_book(books, "live_book.json", {"some_sleeve": ["HYG", "JNK"]})
    (books / "some_live").mkdir()
    (books / "some_live" / "_attribution.json").write_text(
        json.dumps({"some_sleeve": {"HYG": 100.0}}))

    assert preflight.check_phantom_books().ok is True


def test_a_dead_book_that_claims_nothing_is_not_reported(books):
    """The check flags CONTESTED SYMBOLS, not unused files.

    `ops/books/` also holds dry-run books and status artefacts. A spec with no
    universe takes nothing away from anyone, and warning about it every session
    is how a warning becomes wallpaper.
    """
    _spec_book(books, "empty_book.json", {"ghost": []})
    (books / "not_a_book.json").write_text(json.dumps({"note": "scratch"}))
    (books / "broken.json").write_text("{not json")

    assert preflight.check_phantom_books().ok is True


def test_the_live_books_are_not_flagged_as_phantoms(books, tmp_path):
    """The seven deployed sleeves, from their real specs, must stay silent.

    A check that fires on the live book is worse than no check: it trains
    whoever reads the preflight output to skip the line, and the next real
    phantom goes past unread. Sleeve names come from the three real book specs
    rather than a hand-typed list, so adding an eighth sleeve cannot silently
    drop out of this assertion.
    """
    names = []
    for rel in ("ops/books/cef_discount_book.json",
                "ops/books/phase0_book.json",
                "ops/books/benchmarks_book.json"):
        names += _copy_real(books, tmp_path, rel)
    assert len(names) == 7, f"expected 7 live sleeves, book specs name {names}"

    for i, n in enumerate(names):
        _ledger_dir(books, f"book{i}_live", n)

    chk = preflight.check_phantom_books()
    assert chk.ok is True, f"a live book was called a phantom: {chk.detail}"


# -- costs: the 2026-07-31 KeyError ---------------------------------------

def test_a_ticker_with_no_cost_entry_blocks_before_anything_is_transmitted(
        monkeypatch):
    """2026-07-31: 28 of 31 deployed tickers had no cost entry.

    `ops/ledger.py` reads `costs["tickers"][t]["half_spread_bp"]` and raises a
    deliberate KeyError on a miss, so the ledger died mid-advance every session
    — AFTER the orders had gone out. That ordering is the whole point: the
    orders were real and the book that was supposed to record them was not.
    This check must be blocking, and must name the sleeve and the ticker, or
    whoever reads it has to go find both.
    """
    monkeypatch.setattr(preflight, "deployed_tickers",
                        lambda p: {"cef_discount": ["PDO", "NVG", "MHD"]})
    monkeypatch.setattr("ops.common.load_costs",
                        lambda: {"tickers": {"PDO": {"half_spread_bp": 5.0},
                                             "MHD": {"half_spread_bp": 6.0}}})

    chk = preflight.check_costs("unused_book.json")

    assert chk.ok is False
    assert chk.blocking is True
    assert "NVG" in chk.detail
    assert "cef_discount" in chk.detail
    assert "PDO" not in chk.detail, "only the MISSING tickers should be named"


def test_a_fully_priced_book_passes_the_cost_check(monkeypatch):
    """The other direction, so the check cannot pass by always failing."""
    monkeypatch.setattr(preflight, "deployed_tickers",
                        lambda p: {"cef_discount": ["PDO", "MHD"],
                                   "null_trader": ["HYG"]})
    monkeypatch.setattr("ops.common.load_costs",
                        lambda: {"tickers": {t: {"half_spread_bp": 5.0}
                                             for t in ("PDO", "MHD", "HYG")}})

    chk = preflight.check_costs("unused_book.json")

    assert chk.ok is True
    assert "3 deployed ticker(s) priced" in chk.detail


def test_an_empty_cost_file_does_not_quietly_pass(monkeypatch):
    """A missing `tickers` map must read as "nothing is priced", not "nothing to
    check". An empty dict is the shape a half-written config takes."""
    monkeypatch.setattr(preflight, "deployed_tickers",
                        lambda p: {"cef_discount": ["PDO"]})
    monkeypatch.setattr("ops.common.load_costs", lambda: {})

    chk = preflight.check_costs("unused_book.json")

    assert chk.ok is False
    assert "PDO" in chk.detail


# -- data freshness -------------------------------------------------------

@pytest.fixture
def panels(tmp_path, monkeypatch):
    """Writer for the two parquet panels `check_data` reads, under tmp_path."""
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    d = tmp_path / "data" / "cef"
    d.mkdir(parents=True)

    def write(name, last_date):
        import pandas as pd
        dates = pd.bdate_range(end=pd.Timestamp(last_date), periods=5)
        pd.DataFrame({"date": dates, "ticker": "PDO",
                      "close": 1.0}).to_parquet(d / name)
    return write


def test_a_stale_nav_blocks_because_the_signal_is_price_minus_nav(panels):
    """The CEF signal is discount = price - NAV.

    A NAV that stopped publishing does not make a fund look cheap for a real
    reason; it makes the signal a difference against a number that no longer
    exists, and the position it sizes is noise wearing the shape of alpha. This
    is one of the few checks that must stop live orders outright.
    """
    panels("cef_prices.parquet", "2026-09-09")
    panels("cef_nav.parquet", "2026-09-01")

    chk = preflight.check_data("2026-09-10", max_price_age_bd=3, max_nav_age_bd=3)

    assert chk.ok is False
    assert chk.blocking is True
    assert "NAV -> 2026-09-01" in chk.detail
    assert "prices -> 2026-09-09" in chk.detail, \
        "the passing panel's date must still be reported, not just the failure"


def test_current_panels_pass_the_freshness_check(panels):
    """A one-session-old panel is normal, not stale: NAVs publish after the
    close, so the newest usable NAV is routinely yesterday's."""
    panels("cef_prices.parquet", "2026-09-09")
    panels("cef_nav.parquet", "2026-09-09")

    chk = preflight.check_data("2026-09-10", max_price_age_bd=3, max_nav_age_bd=3)

    assert chk.ok is True
    assert "(1bd)" in chk.detail


def test_a_missing_panel_is_named_rather_than_treated_as_fresh(panels):
    """NO SILENT FALLBACK. A panel that is absent must fail loudly and say which
    file is gone — the alternative is a check that passes hardest exactly when
    the data pipeline has stopped running."""
    panels("cef_prices.parquet", "2026-09-09")

    chk = preflight.check_data("2026-09-10")

    assert chk.ok is False
    assert chk.blocking is True
    assert "MISSING cef_nav.parquet" in chk.detail
