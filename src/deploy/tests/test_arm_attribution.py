"""`arm()` decides who owns what. Every branch of that decision is an incident.

WHY THIS FILE EXISTS
--------------------
`IBKRBroker.arm()` is the gate between "the account holds N shares" and "this
sleeve will diff its targets against N shares". Getting it wrong does not
produce an error; it produces a correct-looking order that sells a leg the
sleeve never took, or re-buys a book it already holds. Its own docstring records
four separate incidents in prose — and prose caught none of the fifth, on
2026-09-09, when a book dead since 2026-07-30 was still counted as a live
claimant and halted the benchmarks session over ANGL.

So each test below pins ONE branch of the decision and names the incident that
branch encodes. The share counts are the measured ones from those incidents
(823 HYG split 541/251/31, 67 USHY, 87 ANGL), not invented round numbers, so a
failure here reads as the incident it is.

THE SPLIT OF AUTHORITY UNDER TEST (ibkr.py:806-830 in the docstring, :836-903 in
the code):

    the BROKER is authoritative for HOW MANY shares exist
    the shadow LEDGER is authoritative for WHICH SLEEVE owns them

and the account net may only ever be adopted for a symbol nobody else can be
holding.

NO BROKER, NO NETWORK, NO LIVE LEDGERS. `IBKRBroker` is built with `__new__` and
the handful of attributes `arm()` actually reads are set by hand; `ib` is a stub
whose only job is to answer `positions()`. Every book spec is written into
`tmp_path`. Nothing here touches `ops/books/*_live/`, which holds the only
record of real fills.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.broker.ibkr import IBKRBroker  # noqa: E402


# -- stubs ----------------------------------------------------------------

class _Contract:
    """Only the two attributes `sync_positions(None)` reads off a contract."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.localSymbol = None


class _Position:
    def __init__(self, symbol, qty):
        self.contract = _Contract(symbol)
        self.position = float(qty)


class _StubIB:
    """Stands in for a connected `ib_async.IB`. `arm()` only calls positions()."""

    def __init__(self, account):
        self._account = dict(account)

    def positions(self):
        return [_Position(s, q) for s, q in self._account.items()]


def _broker(books_root, sleeves, ledger, account):
    """An IBKRBroker that was never connected and never will be.

    `__new__` deliberately skips `__init__`, which would load bond state off
    disk and build an IBKRConfig from the environment — neither of which `arm()`
    reads, and both of which would couple this test to the machine it runs on.
    """
    b = IBKRBroker.__new__(IBKRBroker)
    b.ib = _StubIB(account)
    b.verbose = False
    b._sleeves = {n: {"instruments": list(i)} for n, i in sleeves.items()}
    b._live_positions = {n: dict(p) for n, p in ledger.items()}
    b._books_root = str(books_root)
    b._armed = False
    b._arm_report = None
    return b


def _books(tmp_path):
    """`ops/books/`-shaped tree: the book we are arming plus room for siblings.

    `_foreign_book_claims()` globs the PARENT of `books_root`, mirroring the
    real layout (`ops/books/phase0_live` -> `ops/books`), so the returned dir is
    where sibling specs go.

    The `ops/` level is real, not decoration: a repo-relative `spec_path` is
    resolved against the repo root derived as `<books_root>/../..`, so a fixture
    that flattened this would put the repo root in the wrong place and a
    `spec_path` test would fail for a reason that has nothing to do with the
    behaviour under test.
    """
    books = tmp_path / "ops" / "books"
    (books / "this_live").mkdir(parents=True)
    return books


def _sibling(books, filename, sleeves, subdir=None):
    """Write a sibling book spec claiming a universe.

    The universe goes INLINE under `spec.frozen.universe` rather than behind a
    `spec_path`, to keep these tests about the claim logic alone. The
    `spec_path` route is covered separately by the cwd regression test at the
    end of this file.
    """
    d = books / subdir if subdir else books
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps({
        "book_id": filename.replace(".json", ""),
        "sleeves": [{"name": name, "enabled": True,
                     "spec": {"frozen": {"universe": list(universe)}}}
                    for name, universe in sleeves.items()],
    }))


# -- sole owner, uncontested ----------------------------------------------

def test_the_broker_share_count_overrides_a_stale_ledger_for_a_symbol_only_we_trade():
    """2026-07-31: the ledger was flat while the account held ~$2.07M gross.

    `place_targets` diffs against the ledger seed, so a ledger that has fallen
    behind the account makes the next run re-establish positions it already
    holds. When nobody else can be holding the symbol, the account net IS this
    sleeve's position and is adopted wholesale — that is the whole point of
    arming.
    """
    b = _broker("/nonexistent/books/this_live",
                sleeves={"cef_discount": ["PDO"]},
                ledger={"cef_discount": {"PDO": 0.0}},
                account={"PDO": 4200.0})
    rep = b.arm()

    assert rep["ok"] is True
    assert rep["adopted"]["cef_discount"]["PDO"] == 4200.0
    assert b._live_positions["cef_discount"]["PDO"] == 4200.0
    assert b._armed is True
    assert any("PDO" in c and "4200" in c for c in rep["changes"])


def test_a_symbol_no_registered_sleeve_trades_is_ignored_rather_than_flagged():
    """One process per book, one shared paper account.

    A CEF run legitimately sees the null trader's credit ETFs in
    `ib.positions()`. Treating them as drift would make every session refuse,
    and a guard that always fires is one nobody reads.
    """
    b = _broker("/nonexistent/books/this_live",
                sleeves={"cef_discount": ["PDO"]},
                ledger={"cef_discount": {}},
                account={"PDO": 100.0, "JNK": 961.0})
    rep = b.arm()

    assert rep["ok"] is True
    assert rep["foreign"] == {"JNK": 961.0}
    assert "JNK" not in rep["adopted"].get("cef_discount", {})
    assert rep["problems"] == []


# -- sole owner here, but another book trades it too -----------------------

def test_a_symbol_another_book_also_trades_is_taken_from_the_ledger_not_the_account(tmp_path):
    """2026-07-31: arming phase0 reported ok=True while mis-attributing 9 symbols.

    null_trader is the only sleeve in its own process and therefore looked like
    the sole owner of HYG — of which it holds 541 while the ACCOUNT holds 823,
    the other 282 belonging to the benchmark books. Adopting 823 would have made
    the next run sell 282 shares it never bought.
    """
    books = _books(tmp_path)
    _sibling(books, "benchmarks_book.json", {"bench_b1_hyg": ["HYG"]})
    b = _broker(books / "this_live",
                sleeves={"null_trader": ["HYG"]},
                ledger={"null_trader": {"HYG": 541.0}},
                account={"HYG": 823.0})
    rep = b.arm()

    assert rep["ok"] is True
    assert rep["adopted"]["null_trader"]["HYG"] == 541.0, \
        "the account net was adopted for a symbol another book also holds"
    assert b._live_positions["null_trader"]["HYG"] == 541.0


def test_a_contested_symbol_with_no_ledger_entry_blocks_instead_of_guessing(tmp_path):
    """2026-09-09 17:25, the ANGL refusal that halted benchmarks_paper.

    The ledger is the only attribution that exists. When it has nothing to say
    about a symbol a sibling book also trades, no rule can divide the account
    net, and guessing is precisely how a sleeve flattens a leg it never took.
    The refusal itself is correct behaviour — what was wrong on 2026-09-09 was
    that the contesting book had been dead for six weeks (see the retired-book
    tests below).
    """
    books = _books(tmp_path)
    _sibling(books, "phase0_book.json", {"null_trader": ["ANGL"]})
    b = _broker(books / "this_live",
                sleeves={"bench_b6_ew_credit": ["ANGL"]},
                ledger={"bench_b6_ew_credit": {}},
                account={"ANGL": 87.0})
    rep = b.arm()

    assert rep["ok"] is False
    assert b._armed is False
    assert len(rep["problems"]) == 1
    assert "ANGL" in rep["problems"][0]
    assert "no entry" in rep["problems"][0]


def test_an_explicit_zero_claim_resolves_a_contested_symbol(tmp_path):
    """2026-08-31: USHY blocked the whole phase0 session on one symbol.

    A ledger can never say "I own NONE of this" — a flat leg simply is not in
    it — so for a contested symbol that silence is indistinguishable from "no
    claim recorded". `_attribution.json` is the only place an explicit zero can
    live (`_attribution_seed` keeps zeros where the ledger seed drops them,
    ibkr.py:735-740), and this is the branch that makes that worth doing: 0.0 is
    a real claim and must be adopted, not read as a missing entry.
    """
    books = _books(tmp_path)
    _sibling(books, "benchmarks_book.json", {"bench_b6_ew_credit": ["USHY"]})
    b = _broker(books / "this_live",
                sleeves={"null_trader": ["USHY"]},
                ledger={"null_trader": {"USHY": 0.0}},
                account={"USHY": 67.0})
    rep = b.arm()

    assert rep["ok"] is True, "an explicit zero claim was read as a missing entry"
    assert rep["adopted"]["null_trader"]["USHY"] == 0.0
    assert b._live_positions["null_trader"]["USHY"] == 0.0


# -- shared inside this process -------------------------------------------

def test_two_sleeves_whose_tags_explain_the_account_exactly_keep_their_own_split():
    """The uncontested shared case: ledger split 251 + 31 against 282 held.

    Nothing is taken from the account net here either — each sleeve keeps its
    own tagged quantity. The account is only used to confirm the split adds up.
    """
    b = _broker("/nonexistent/books/this_live",
                sleeves={"bench_b1_hyg": ["HYG"], "bench_b6_ew_credit": ["HYG"]},
                ledger={"bench_b1_hyg": {"HYG": 251.0},
                        "bench_b6_ew_credit": {"HYG": 31.0}},
                account={"HYG": 282.0})
    rep = b.arm()

    assert rep["ok"] is True
    assert rep["adopted"]["bench_b1_hyg"]["HYG"] == 251.0
    assert rep["adopted"]["bench_b6_ew_credit"]["HYG"] == 31.0


def test_sleeves_summing_short_of_a_contested_account_are_not_treated_as_drift(tmp_path):
    """2026-08-31, THE 282-VS-823 BUG THAT BLOCKED EVERY BENCHMARK SESSION.

    The account holds 823 HYG: bench_b1_hyg 251, bench_b6_ew_credit 31, and
    null_trader — another book, another process — the remaining 541. The old
    rule demanded that the sleeves registered HERE explain the whole account
    net, compared 282 against 823, and refused. When a sibling book also trades
    the symbol, summing short is the CORRECT state, not ambiguity.
    """
    books = _books(tmp_path)
    _sibling(books, "phase0_book.json", {"null_trader": ["HYG"]})
    b = _broker(books / "this_live",
                sleeves={"bench_b1_hyg": ["HYG"], "bench_b6_ew_credit": ["HYG"]},
                ledger={"bench_b1_hyg": {"HYG": 251.0},
                        "bench_b6_ew_credit": {"HYG": 31.0}},
                account={"HYG": 823.0})
    rep = b.arm()

    assert rep["ok"] is True, \
        f"the 282-vs-823 refusal is back: {rep['problems']}"
    assert rep["adopted"]["bench_b1_hyg"]["HYG"] == 251.0
    assert rep["adopted"]["bench_b6_ew_credit"]["HYG"] == 31.0
    assert 823.0 not in rep["adopted"]["bench_b1_hyg"].values()


def test_a_contested_shared_symbol_blocks_when_one_claimant_has_no_attribution(tmp_path):
    """Summing short is only safe while every claimant here can answer for itself.

    bench_b1_hyg claims 251 and bench_b6_ew_credit claims nothing at all. The
    shortfall against the account could be null_trader's 541, or it could be
    bench_b6 holding shares its ledger lost — and the difference decides whether
    a sell order is right or catastrophic. Refuse, naming the sleeve that cannot
    answer.
    """
    books = _books(tmp_path)
    _sibling(books, "phase0_book.json", {"null_trader": ["HYG"]})
    b = _broker(books / "this_live",
                sleeves={"bench_b1_hyg": ["HYG"], "bench_b6_ew_credit": ["HYG"]},
                ledger={"bench_b1_hyg": {"HYG": 251.0}, "bench_b6_ew_credit": {}},
                account={"HYG": 823.0})
    rep = b.arm()

    assert rep["ok"] is False
    assert len(rep["problems"]) == 1
    assert "bench_b6_ew_credit has no attribution entry" in rep["problems"][0]


def test_a_shared_symbol_no_other_book_trades_must_add_up_exactly():
    """No sibling claimant, so the sleeves here own all of it — or attribution
    is broken. 251 + 31 = 282 cannot explain 823 when there is no third party,
    and the only honest answer is to refuse rather than pick a split."""
    b = _broker("/nonexistent/books/this_live",
                sleeves={"bench_b1_hyg": ["HYG"], "bench_b6_ew_credit": ["HYG"]},
                ledger={"bench_b1_hyg": {"HYG": 251.0},
                        "bench_b6_ew_credit": {"HYG": 31.0}},
                account={"HYG": 823.0})
    rep = b.arm()

    assert rep["ok"] is False
    assert "attribution is ambiguous" in rep["problems"][0]
    assert "+823" in rep["problems"][0] and "+282" in rep["problems"][0]


# -- positions that left the account --------------------------------------

def test_a_ledger_position_the_account_no_longer_holds_is_written_down_to_zero():
    """The mirror of the stale-ledger case: a leg that filled OUT.

    If the tag book kept 500 PDO the broker no longer reports, the next diff
    would size a sell against shares that do not exist. The broker is
    authoritative for how many shares exist, including zero.
    """
    b = _broker("/nonexistent/books/this_live",
                sleeves={"cef_discount": ["PDO", "MHD"]},
                ledger={"cef_discount": {"PDO": 500.0, "MHD": 200.0}},
                account={"MHD": 200.0})
    rep = b.arm()

    assert rep["ok"] is True
    assert "PDO" not in b._live_positions["cef_discount"]
    assert b._live_positions["cef_discount"]["MHD"] == 200.0
    assert any("PDO" in c and "broker 0" in c for c in rep["changes"])


# -- what a refusal must NOT do -------------------------------------------

def test_a_refusal_leaves_the_tag_books_untouched_and_the_adapter_disarmed(tmp_path):
    """A blocked arm must change nothing.

    `place_targets` raises NotArmed on `_armed=False`, but a partially adopted
    tag book would survive into the next process via the shadow ledger. All or
    nothing: adoption happens only when `problems` is empty (ibkr.py:923).
    """
    books = _books(tmp_path)
    _sibling(books, "phase0_book.json", {"null_trader": ["ANGL"]})
    b = _broker(books / "this_live",
                sleeves={"bench_b6_ew_credit": ["ANGL", "HYG"]},
                ledger={"bench_b6_ew_credit": {"HYG": 31.0}},
                account={"ANGL": 87.0, "HYG": 400.0})
    rep = b.arm()

    assert rep["ok"] is False
    assert b._armed is False
    assert b._live_positions == {"bench_b6_ew_credit": {"HYG": 31.0}}, \
        "a refused arm still rewrote the tag book"
    assert rep["adopted"]["bench_b6_ew_credit"]["HYG"] == 400.0, \
        "the report should still show what WOULD have been adopted"


def test_arm_can_report_without_rewriting_the_tag_books():
    """`adopt=False` is the read-only path used to inspect state.

    It must still set `_armed` (that is the verdict) while leaving
    `_live_positions` exactly as it found them.
    """
    b = _broker("/nonexistent/books/this_live",
                sleeves={"cef_discount": ["PDO"]},
                ledger={"cef_discount": {"PDO": 1.0}},
                account={"PDO": 4200.0})
    rep = b.arm(adopt=False)

    assert rep["ok"] is True
    assert b._armed is True
    assert b._live_positions == {"cef_discount": {"PDO": 1.0}}


# -- _foreign_book_claims: who counts as a live claimant -------------------

def test_a_retired_book_spec_no_longer_contests_symbols_for_a_live_book(tmp_path):
    """TODAY'S BUG, 2026-09-10. A dead book still voted.

    credit_rv was killed 2026-07-30 (sealed holdout net SR -1.44) but its spec
    stayed in `ops/books/`, claiming 21 symbols it could never hold: no ledger
    directory, no attribution entry, no broker fills, no schedule entry, no
    launchd job. `_foreign_book_claims()` counts any `*.json` carrying a
    `sleeves` list as a live sibling, so those 21 symbols became CONTESTED for
    the books that were still trading — 8 contested for bench_b6_ew_credit
    instead of 7, and 14 instead of 7 for null_trader.

    ANGL is what that cost: it was contested by a corpse, bench_b6's ledger had
    been re-seeded empty on 09-07, and the benchmarks book halted at 17:25 on
    2026-09-09.

    The fix is that `ops/books/retired/` is a SUBDIRECTORY and the glob is
    non-recursive (ibkr.py:767, `root.glob("*.json")`). This test pins that
    non-recursiveness, because it is the only thing standing between a retired
    spec and a live session: with the spec retired, ANGL is solely owned and
    adopted from the account net, needing no ledger entry at all.
    """
    books = _books(tmp_path)
    _sibling(books, "credit_rv_book.json", {"credit_rv": ["ANGL", "HYG", "JNK"]},
             subdir="retired")
    b = _broker(books / "this_live",
                sleeves={"bench_b6_ew_credit": ["ANGL"]},
                ledger={"bench_b6_ew_credit": {}},
                account={"ANGL": 87.0})

    assert b._foreign_book_claims() == set(), \
        "a spec under ops/books/retired/ is still voting"
    rep = b.arm()
    assert rep["ok"] is True, f"a retired book blocked a live one: {rep['problems']}"
    assert rep["adopted"]["bench_b6_ew_credit"]["ANGL"] == 87.0


def test_a_live_sibling_books_universe_is_still_contested(tmp_path):
    """The other half of the same fix: retiring must not disarm the guard.

    If retirement were implemented by loosening the claim rule rather than by
    moving one file, the 2026-07-31 HYG mis-attribution comes straight back. A
    sibling spec sitting in `ops/books/` still claims its whole universe.
    """
    books = _books(tmp_path)
    _sibling(books, "phase0_book.json", {"null_trader": ["ANGL", "HYG", "JNK"]})
    b = _broker(books / "this_live",
                sleeves={"bench_b6_ew_credit": ["ANGL"]},
                ledger={"bench_b6_ew_credit": {}},
                account={"ANGL": 87.0})

    assert b._foreign_book_claims() == {"ANGL", "HYG", "JNK"}
    assert b.arm()["ok"] is False, "a live sibling book stopped contesting ANGL"


def test_this_books_own_spec_is_not_read_as_a_foreign_claimant(tmp_path):
    """A book must not contest itself.

    `_foreign_book_claims()` skips a spec whose sleeve names are all registered
    in this process (ibkr.py:781-782). Without that, every symbol the book
    trades would be contested by the book trading it, and every session would
    demand a ledger entry for every name — turning arming into a coin flip on
    whether the ledger happens to be current.
    """
    books = _books(tmp_path)
    _sibling(books, "this_book.json", {"cef_discount": ["PDO", "MHD"]})
    b = _broker(books / "this_live",
                sleeves={"cef_discount": ["PDO", "MHD"]},
                ledger={"cef_discount": {}},
                account={"PDO": 4200.0})

    assert b._foreign_book_claims() == set()
    assert b.arm()["ok"] is True


def test_a_spec_with_no_sleeves_list_contributes_no_claims(tmp_path):
    """`ops/books/` also holds dry-run artefacts and status files.

    Only a `sleeves` list makes a file a book. A stray JSON must not silently
    become a claimant, and must not raise either — this runs inside the gate
    that decides whether a session may trade.
    """
    books = _books(tmp_path)
    (books / "not_a_book.json").write_text(json.dumps({"note": "scratch"}))
    (books / "broken.json").write_text("{not json")
    b = _broker(books / "this_live",
                sleeves={"cef_discount": ["PDO"]},
                ledger={"cef_discount": {}},
                account={"PDO": 4200.0})

    assert b._foreign_book_claims() == set()
    assert b.arm()["ok"] is True


def test_sibling_claims_do_not_depend_on_the_processs_working_directory(
        tmp_path, monkeypatch):
    """A claim must not disappear because launchd started us somewhere else.

    Every book spec in `ops/books/` points at its frozen spec through a
    repo-relative `spec_path`; none carries an inline `spec`. So this is not a
    hypothetical layout — it is the only layout in use.

    REGRESSION, fixed 2026-09-10. `_foreign_book_claims()` opened `spec_path`
    with a bare `open()`, resolving it against the process working directory,
    and the `except` below it swallowed the miss silently. Measured before the
    fix: 36 claims from the repo root, **0 from /tmp**. Every contested symbol
    then looks solely owned and `arm()` adopts the account NET — the exact
    2026-07-31 HYG 823-vs-541 mis-attribution the function exists to prevent.
    `launch_job.py:210` passes `cwd=REPO` to every scheduled session, so this
    was latent rather than live, but nothing here may depend on a caller's cwd.
    """
    books = _books(tmp_path)
    repo_root = books.parent.parent          # <repo>/ops/books -> <repo>
    (repo_root / "ops" / "specs").mkdir(parents=True)
    (repo_root / "ops" / "specs" / "sib.frozen.json").write_text(
        json.dumps({"frozen": {"universe": ["ANGL", "HYG"]}}))
    (books / "phase0_book.json").write_text(json.dumps({
        "book_id": "phase0_null",
        "sleeves": [{"name": "null_trader", "enabled": True,
                     "spec_path": "ops/specs/sib.frozen.json"}],
    }))
    b = _broker(books / "this_live",
                sleeves={"bench_b6_ew_credit": ["ANGL"]},
                ledger={"bench_b6_ew_credit": {}},
                account={"ANGL": 87.0})

    monkeypatch.chdir(books)
    assert b._foreign_book_claims() == {"ANGL", "HYG"}, \
        "fixture is wrong: the claim is not even seen from the right cwd"

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert b._foreign_book_claims() == {"ANGL", "HYG"}
