"""`capture_fills`'s two readers must RAISE on a corrupt file, never read it as zero.

WHY THESE ARE NOT HYGIENE TESTS
-------------------------------
Both readers used to swallow every exception and return an empty-or-partial
result, and in both cases the empty result is INDISTINGUISHABLE from a
legitimate one:

  `_recorded_exec_ids`  -> {} reads as "this sleeve has recorded no fills yet",
                           which is exactly what a brand-new sleeve looks like.
                           The dedup then re-writes every execution the file
                           already held. The module docstring calls this dedup
                           LOAD-BEARING and cites 2026-07-31, where three blind
                           captures of one session produced 514 rows for 257
                           real executions. The slippage statistic kill rule (b)
                           reads is volume-weighted, so a doubled file does not
                           inflate a row count, it corrupts the statistic.

  `_load_order_map`     -> a PARTIAL map reads as a complete one. Its only
                           consumer is the shared-ticker branch, which treats a
                           lookup miss as UNATTRIBUTED and does not record the
                           fill at all. So a half-read CSV silently drops real
                           executions out of the slippage record.

Both are the repo's NO SILENT FALLBACKS rule, on the one path whose entire
purpose is that a fill record is never lost. A missing file is still a
legitimate state and still returns empty -- that distinction is the point.

NO BROKER, NO NETWORK, NO LIVE LEDGERS. Everything below is built in tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import capture_fills  # noqa: E402

HEADER = "recorded_utc,fill_date,instrument,side,qty,price,source,note\n"
ROW = ("2026-09-08T13:35:19+00:00,2026-09-08,LQD,SELL,50.0,105.54,ibkr_paper,"
       "execId=00012ec5.6b3b4068.01.01 orderRef='' commission=0.37 "
       "time=2026-09-08 13:35:18+00:00\n")


# --- _recorded_exec_ids ---------------------------------------------------

def test_missing_broker_fills_is_a_legitimate_empty_set(tmp_path):
    """A sleeve that has never traded is not an error. Keep this working."""
    seen = capture_fills._recorded_exec_ids(tmp_path / "phase0_live", ["null_trader"])
    assert seen == {"null_trader": set()}


def test_a_readable_broker_fills_yields_its_exec_ids(tmp_path):
    """The happy path the dedup depends on."""
    d = tmp_path / "phase0_live" / "_ibkr_shadow" / "null_trader"
    d.mkdir(parents=True)
    (d / "broker_fills.csv").write_text(HEADER + ROW)

    seen = capture_fills._recorded_exec_ids(tmp_path / "phase0_live", ["null_trader"])

    assert seen["null_trader"] == {"00012ec5.6b3b4068.01.01"}


def test_broker_fills_without_a_note_column_raises(tmp_path):
    """THE DEFECT. No `note` column means no execId can be read from the file.

    Silently that is an empty `seen` set and the next capture doubles the file.
    """
    d = tmp_path / "phase0_live" / "_ibkr_shadow" / "null_trader"
    d.mkdir(parents=True)
    (d / "broker_fills.csv").write_text(
        "recorded_utc,fill_date,instrument,side,qty,price,source\n"
        "2026-09-08T13:35:19+00:00,2026-09-08,LQD,SELL,50.0,105.54,ibkr_paper\n")

    with pytest.raises(ValueError, match="no 'note' column"):
        capture_fills._recorded_exec_ids(tmp_path / "phase0_live", ["null_trader"])


def test_an_unparseable_broker_fills_raises_rather_than_reading_as_zero(tmp_path):
    """A truncated or malformed CSV must stop the run, not disarm the dedup."""
    d = tmp_path / "phase0_live" / "_ibkr_shadow" / "null_trader"
    d.mkdir(parents=True)
    # Ragged quoting: pandas cannot parse this into a frame.
    (d / "broker_fills.csv").write_text(HEADER + '"unterminated,,,,,,\n' * 3)

    with pytest.raises(Exception):
        capture_fills._recorded_exec_ids(tmp_path / "phase0_live", ["null_trader"])


# --- _load_order_map ------------------------------------------------------

def test_missing_order_map_is_a_legitimate_empty_map(tmp_path):
    """No order has been placed from this book yet. Not an error."""
    assert capture_fills._load_order_map(tmp_path / "phase0_live") == {}


def test_a_readable_order_map_is_parsed(tmp_path):
    d = tmp_path / "phase0_live" / "_ibkr_shadow"
    d.mkdir(parents=True)
    (d / "_order_map.csv").write_text(
        "asof,recorded_utc,order_id,perm_id,sleeve,instrument,action,qty\n"
        "2026-09-08 00:00:00,2026-09-08T13:35:18+00:00,3,0,null_trader,HYG,SELL,442.0\n")

    # Three keys per row since 2026-09-10, most specific first. A LEGACY row
    # like this one carries no perm_id and no client_id, so it contributes only
    # the two ambiguous keys and no ("perm", ...) key at all -- see
    # ops/tests/test_capture_fills_cross_book.py for why that ambiguity is left
    # visible rather than papered over.
    assert capture_fills._load_order_map(tmp_path / "phase0_live") == {
        ("cid", "", "3"): "null_trader",
        ("day", "2026-09-08", "3"): "null_trader",
    }


def test_an_unreadable_order_map_raises_rather_than_returning_a_partial_map(tmp_path):
    """THE DEFECT. A partial map is indistinguishable from a complete one, and a
    lookup miss makes a real execution UNATTRIBUTED and unrecorded."""
    d = tmp_path / "phase0_live" / "_ibkr_shadow"
    d.mkdir(parents=True)
    p = d / "_order_map.csv"
    p.write_bytes(
        b"asof,recorded_utc,order_id,perm_id,sleeve,instrument,action,qty\n"
        b"2026-09-08 00:00:00,2026-09-08T13:35:18+00:00,3,0,null_trader,HYG,SELL,442.0\n"
        b"\xff\xfe\x00 not utf-8 \xff\n")

    with pytest.raises(Exception):
        capture_fills._load_order_map(tmp_path / "phase0_live")
