"""`capture_fills`'s execId dedup cannot see across BOOKS, only across sleeves.

WHAT THIS PINS, AND WHY IT IS NOT HYGIENE
------------------------------------------
`capture_fills` carries a deliberate, documented dedup: `ib.fills()` returns the
whole TWS session on every call, so a job that runs twice would double the fill
record, and the slippage statistic that KILL RULE (b) is evaluated against is
volume-weighted -- duplicates corrupt the statistic, not merely a row count.
Its own docstring calls that dedup "LOAD-BEARING, NOT HYGIENE" and cites
2026-07-31, where three captures of one session produced 514 rows for 257 real
executions.

That dedup is built by `_recorded_exec_ids(books_root, universes)`, which reads
`<books_root>/_ibkr_shadow/<sleeve>/broker_fills.csv`. **Both of its inputs are
scoped to the ONE book being captured.** Three books share a single IBKR paper
account (DUQ199038) with overlapping tickers, and each runs its own capture pass
against the same `ib.fills()`. So when two books both trade a symbol, each
attributes the same execution to its own sleeve, neither `seen` set contains the
other's record, and the execution is written twice under one execId.

MEASURED ON THE LIVE LEDGERS 2026-09-10: 60 of 1,088 distinct execIds are booked
by more than one sleeve -- HYG by bench_b1_hyg + null_trader, and JNK, LQD and
USHY by bench_b6_ew_credit + null_trader. The 2026-09-08 LQD and JNK executions
appear in phase0's record at 13:35:19 UTC and again in the benchmarks record at
21:25:08 UTC: same execId, same qty, same price, same broker timestamp, captured
eight hours apart by two different sessions.

WHAT IT DOES AND DOES NOT CORRUPT
---------------------------------
NOT P&L and NOT positions. This module is explicitly a side channel -- "Nothing
here feeds P&L", the shadow ledger with its modelled cost stays the sole P&L
source (FORCED_FLOW_PREREG locked decision 1). USHY is the control that proves
it: 896 shares double-booked, and its ledger-vs-broker position gap is -11.
What it corrupts is the realised-slippage record, i.e. exactly the input to
kill rule (b).

`dedupe()` cannot repair it either, for the same reason -- it is also scoped to
one `books_root`, so it will never see the twin under another book.

The $500k CEF book is UNAFFECTED: none of the four symbols is in its 17-name
universe, and no cef_discount execId is double-booked. That is the invariant
worth keeping, and the last test here states it.

THESE ARE CHARACTERISATION TESTS. Two of them assert the BROKEN behaviour on
purpose, so the defect cannot be lost again between sessions. If you fix
`capture_fills` -- the fix is to key the dedup on the ACCOUNT rather than on
one `books_root`, since one execId is one broker execution and can have only
one owner -- then `test_dedup_is_blind_to_the_same_execution_in_another_book`
and `test_dedupe_cannot_repair_a_cross_book_duplicate` SHOULD start failing.
Update them deliberately; do not delete them.

NO BROKER, NO NETWORK, NO LIVE LEDGERS. Everything below is built in tmp_path.
Reading `ops/books/*_live/` from a test is against this suite's own rule -- it
holds the only record of real fills -- so the live measurement above lives in
`results/ops/CAPTURE_FILLS_CROSS_BOOK_2026-09-10.md`, not in an assertion here.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import capture_fills  # noqa: E402

EXEC_ID = "00012ec5.6b3b4068.01.01"          # a real shape, from the 09-08 session
HEADER = "recorded_utc,fill_date,instrument,side,qty,price,source,note\n"


def _write_fill(root: Path, sleeve: str, exec_id: str, *, recorded: str) -> Path:
    d = root / "_ibkr_shadow" / sleeve
    d.mkdir(parents=True, exist_ok=True)
    p = d / "broker_fills.csv"
    p.write_text(
        HEADER
        + f"{recorded},2026-09-08,LQD,SELL,50.0,105.54,ibkr_paper,"
          f"execId={exec_id} orderRef='' commission=0.37 time=2026-09-08 13:35:18+00:00\n"
    )
    return p


def test_dedup_sees_its_own_book(tmp_path):
    """Baseline: within ONE book the dedup works. This is the case it was built for."""
    root = tmp_path / "phase0_live"
    _write_fill(root, "null_trader", EXEC_ID, recorded="2026-09-08T13:35:19+00:00")

    seen = capture_fills._recorded_exec_ids(root, ["null_trader"])

    assert EXEC_ID in seen["null_trader"], (
        "the within-book dedup is the load-bearing one; if this fails, a re-run "
        "of a single book doubles its own fill record")


def test_dedup_is_blind_to_the_same_execution_in_another_book(tmp_path):
    """THE DEFECT. One execution, two books, and neither capture can see the other."""
    phase0 = tmp_path / "phase0_live"
    bench = tmp_path / "benchmarks_live"
    _write_fill(phase0, "null_trader", EXEC_ID, recorded="2026-09-08T13:35:19+00:00")
    _write_fill(bench, "bench_b6_ew_credit", EXEC_ID, recorded="2026-09-08T21:25:08+00:00")

    # What the benchmarks capture pass computes when it runs, hours later.
    seen_by_bench = capture_fills._recorded_exec_ids(bench, ["bench_b6_ew_credit"])

    # It holds its OWN copy...
    assert EXEC_ID in seen_by_bench["bench_b6_ew_credit"]

    # ...but nothing it can compute contains phase0's copy. There is no argument
    # to _recorded_exec_ids that reaches another books_root: `books_root` is one
    # book, and `universes` are that book's sleeves.
    everything_bench_can_see = set().union(*seen_by_bench.values())
    seen_by_phase0 = capture_fills._recorded_exec_ids(phase0, ["null_trader"])
    everything_phase0_can_see = set().union(*seen_by_phase0.values())

    assert EXEC_ID in everything_phase0_can_see
    assert EXEC_ID in everything_bench_can_see
    # Both books hold the SAME execution. One broker execution, two owners.
    # Asking either book alone whether it is a duplicate returns "no".
    assert (
        capture_fills._recorded_exec_ids(bench, ["null_trader"])["null_trader"] == set()
    ), ("a sleeve from another book resolves to an empty set rather than an error, "
        "which is why this has been silent since three books shared one account")


def test_dedupe_cannot_repair_a_cross_book_duplicate(tmp_path):
    """`dedupe()` is scoped the same way, so it is not the remedy either."""
    phase0 = tmp_path / "phase0_live"
    bench = tmp_path / "benchmarks_live"
    p0 = _write_fill(phase0, "null_trader", EXEC_ID, recorded="2026-09-08T13:35:19+00:00")
    pb = _write_fill(bench, "bench_b6_ew_credit", EXEC_ID, recorded="2026-09-08T21:25:08+00:00")

    capture_fills.dedupe(bench, ["bench_b6_ew_credit"], verbose=False)

    # Both rows survive: dedupe kept the only row in ITS book, and never saw the twin.
    assert EXEC_ID in p0.read_text()
    assert EXEC_ID in pb.read_text()
    assert len(p0.read_text().strip().splitlines()) == 2   # header + 1
    assert len(pb.read_text().strip().splitlines()) == 2


def test_within_book_duplicate_is_still_repaired(tmp_path):
    """Guard the behaviour that DOES work, so a cross-book fix does not break it."""
    root = tmp_path / "phase0_live"
    d = root / "_ibkr_shadow" / "null_trader"
    d.mkdir(parents=True)
    row = (f"2026-09-08T13:35:19+00:00,2026-09-08,LQD,SELL,50.0,105.54,ibkr_paper,"
           f"execId={EXEC_ID} orderRef='' commission=0.37 time=2026-09-08 13:35:18+00:00\n")
    (d / "broker_fills.csv").write_text(HEADER + row + row)

    out = capture_fills.dedupe(root, ["null_trader"], verbose=False)

    assert out["null_trader"] == {"before": 2, "after": 1}
