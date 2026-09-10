"""The order map's key, and the append that would silently corrupt it.

TWO THINGS ARE PINNED HERE.

1. **The header migration.** `csv.DictWriter` writes values in `fieldnames`
   order and never looks at the file it appends to. The three live maps were
   written with an 8-field header; appending a 10-field row would put
   `client_id` where `sleeve` is and shift every column after it. Nothing would
   raise. The file would just start lying, in the shape of a plausible
   attribution — and attribution decides which live book owns a real position.

2. **What a legacy row must NOT gain.** Rows written before 2026-09-10 carry no
   client_id and no perm_id. The migration leaves those blank. Inventing either
   would put a false *global* key on precisely the rows the cross-book work
   exists to distrust.

NO BROKER, NO NETWORK. `IBKRBroker` is built with `__new__`.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.broker.ibkr import IBKRBroker  # noqa: E402

LEGACY_HEADER = "asof,recorded_utc,order_id,perm_id,sleeve,instrument,action,qty"
# a real row from ops/books/cef_live/_ibkr_shadow/_order_map.csv
LEGACY_ROW = ("2026-08-31 00:00:00,2026-08-31T21:15:36.453156+00:00,"
              "39,0,cef_discount,AWF,SELL,3549.0")

NEW_ROW = {"asof": "2026-09-11", "recorded_utc": "2026-09-11T20:00:00+00:00",
           "order_id": "99", "perm_id": "881234", "client_id": "17",
           "book_id": "cef_discount_paper", "sleeve": "cef_discount",
           "instrument": "NAD", "action": "BUY", "qty": "10"}


def _broker(root):
    b = IBKRBroker.__new__(IBKRBroker)
    b._books_root = str(root)
    b.verbose = False
    return b


def _rows(root):
    with open(Path(root) / "_ibkr_shadow" / "_order_map.csv", newline="") as fh:
        return list(csv.DictReader(fh))


def test_appending_to_a_legacy_header_migrates_instead_of_shifting(tmp_path):
    d = tmp_path / "_ibkr_shadow"
    d.mkdir(parents=True)
    (d / "_order_map.csv").write_text(LEGACY_HEADER + "\n" + LEGACY_ROW + "\n")

    _broker(tmp_path)._append_order_map_row(NEW_ROW)
    rows = _rows(tmp_path)

    assert len(rows) == 2
    assert list(rows[0]) == IBKRBroker.ORDER_MAP_COLUMNS
    # THE POINT: the legacy row's values did not shift under the new header.
    assert rows[0]["sleeve"] == "cef_discount"
    assert rows[0]["instrument"] == "AWF"
    assert rows[0]["action"] == "SELL"
    assert rows[0]["qty"] == "3549.0"
    assert rows[0]["order_id"] == "39"


def test_migration_leaves_the_new_fields_blank_not_guessed(tmp_path):
    d = tmp_path / "_ibkr_shadow"
    d.mkdir(parents=True)
    (d / "_order_map.csv").write_text(LEGACY_HEADER + "\n" + LEGACY_ROW + "\n")
    _broker(tmp_path)._append_order_map_row(NEW_ROW)
    old = _rows(tmp_path)[0]
    assert old["client_id"] == "" and old["book_id"] == "", (
        "a legacy row genuinely was written without these; filling them would "
        "put a false global key on the rows that most need distrusting")
    assert old["perm_id"] == "0", "unchanged — nothing on disk can recover it"


def test_a_fresh_map_gets_the_full_header(tmp_path):
    _broker(tmp_path)._append_order_map_row(NEW_ROW)
    rows = _rows(tmp_path)
    assert list(rows[0]) == IBKRBroker.ORDER_MAP_COLUMNS
    assert rows[0]["perm_id"] == "881234" and rows[0]["client_id"] == "17"


def test_backfill_writes_perm_ids_and_leaves_other_rows_alone(tmp_path):
    """perm_id is 0 at placement because TWS assigns it asynchronously."""
    d = tmp_path / "_ibkr_shadow"
    d.mkdir(parents=True)
    b = _broker(tmp_path)
    b._append_order_map_row({**NEW_ROW, "order_id": "3", "perm_id": "0"})
    b._append_order_map_row({**NEW_ROW, "order_id": "4", "perm_id": "0"})
    b._append_order_map_row({**NEW_ROW, "order_id": "5", "perm_id": "770000"})

    class _O:
        def __init__(self, oid, pid): self.orderId, self.permId = oid, pid

    class _T:
        def __init__(self, oid, pid): self.order = _O(oid, pid)

    b._backfill_perm_ids([_T(3, 881001), _T(4, 881002), _T(5, 999999)])
    got = {r["order_id"]: r["perm_id"] for r in _rows(tmp_path)}
    assert got["3"] == "881001" and got["4"] == "881002"
    assert got["5"] == "770000", "an already-assigned perm_id is never overwritten"


def test_backfill_never_raises_when_the_map_is_missing(tmp_path):
    """The orders are already at the exchange by the time this runs."""
    class _T:
        order = type("O", (), {"orderId": 3, "permId": 881001})()
    _broker(tmp_path)._backfill_perm_ids([_T()])      # must not raise
