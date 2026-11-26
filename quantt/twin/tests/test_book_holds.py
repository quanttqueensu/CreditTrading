"""A book that must not trade at the twin gets a HOLD target and a record naming why, never an order:
its own send is DRY_RUN=1, its AUTO_ARMED is missing, a halt names it, its unit cannot be read, or
(the revert barrier, the switch branch's re-review) its state shows an open IBKR segment while its
plan was decided at Alpaca. The core holds PDI 80 in the twin ledger, so a decided core would trade."""
from __future__ import annotations

import datetime as dt
import io
import json

import pytest

from quantt.twin import run
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_send import A, PRINTS, S, armed

DAY = "2026-11-27"


def setup(tmp_path):
    st = F.make_states(tmp_path)
    w = F.World()
    w.positions = {"PDI": 80}
    mk = F.FakeMarket(F.et(2026, 11, 27, 12, 30, 5), F.nov_calendar(), prints=dict(PRINTS))
    F.write_core_plan(st["cef"], "cef", S, A, {"PDI": 100, "NAD": -50}, {"PDI": 80}, {"PDI": 19.9, "NAD": 12.1})
    F.write_core_plan(st["c4"], "c4", S, A, {"MHD": 30, "NAD": 20}, {}, {"MHD": 11.0, "NAD": 12.1})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN="0"), out=out)
    assert run.epoch(d) == 0
    led = json.loads((st["twin"] / "ledger.json").read_text())
    led["sleeves"] = {"cef": {"shares": {"PDI": 80}, "cash": -1592.0, "stale_sessions": 0}}
    (st["twin"] / "ledger.json").write_text(json.dumps(led))
    armed(st)
    return st, w, mk, d, out


def sources(st, segs):
    (st["cef"] / "eod_equity_sources.json").write_text(json.dumps({"file": "eod_equity.csv", "segments": segs}))


def _dry(st, d):
    d.unit_env = lambda u: dict(F.UNIT_ENV, **{"quantt-cef-session.service": "DRY_RUN=1"})[u]


def _no_auto(st, d):
    (st["cef"] / "AUTO_ARMED").unlink()


def _halt_books_clone(st, d):
    (st["books_clone"] / "ops" / "HALT_cef.md").write_text("# HALT\n## 2026-11-27  test\n")


def _halt_state(st, d):
    (st["cef"] / "HALT").write_text("why\n")


def _unreadable(st, d):
    def env(u):
        if u == "quantt-cef-session.service":
            raise RuntimeError("systemctl show exited 1")
        return F.UNIT_ENV[u]
    d.unit_env = env


def _revert(st, d):
    sources(st, [{"source": "alpaca_eod_history", "label": "x", "first": "2026-09-28", "last": "2026-11-26"},
                 {"source": "ibkr_twin_ledger", "label": "y", "first": "2026-11-27", "last": None}])


def _sources_unreadable(st, d):
    (st["cef"] / "eod_equity_sources.json").write_text("{broken")


@pytest.mark.parametrize("make,word", [(_dry, "DRY_RUN=1"), (_no_auto, "AUTO_ARMED"),
                                       (_halt_books_clone, "HALT_cef.md"), (_halt_state, "HALT exists"),
                                       (_unreadable, "could not be read"), (_revert, "revert barrier"),
                                       (_sources_unreadable, "revert barrier")],
                         ids=["dry_run", "no_auto_armed", "halt_books_clone", "halt_state", "unreadable_unit",
                              "revert_barrier", "sources_unreadable"])
def test_the_book_holds_with_a_record_and_sends_nothing_of_its_own(tmp_path, make, word):
    st, w, mk, d, out = setup(tmp_path)
    make(st, d)
    assert run.send(d) == 0, out.getvalue()
    plan = json.loads((st["twin"] / DAY / "plan.json").read_text())
    assert plan["books"]["cef"]["status"] == "hold" and word in plan["books"]["cef"]["why"]
    assert word in plan["books_own_arming"]["cef"]
    cef = next(s for s in plan["slugs"] if s["slug"] == "cef")
    assert cef["action"] == "hold" and cef["targets"] == {"PDI": 80}            # the hold target
    assert plan["targets"].get("PDI") == 80 and plan["targets"].get("NAD") == 20   # C4's NAD only
    assert [(s, o.action, o.totalQuantity) for _, s, o in w.placed if s in ("PDI", "NAD")] == [("NAD", "BUY", 20)]


def test_a_plan_decided_for_ibkr_trades_through_the_barrier(tmp_path):
    st, w, mk, d, out = setup(tmp_path)
    _revert(st, d)
    p = st["cef"] / DAY / "plan.json"
    plan = json.loads(p.read_text())
    plan["broker"] = {"name": "ibkr", "from": "2026-11-27", "session_date": DAY, "note": "t"}
    p.write_text(json.dumps(plan))
    assert run.send(d) == 0, out.getvalue()
    tw = json.loads((st["twin"] / DAY / "plan.json").read_text())
    assert tw["books"]["cef"]["status"] == "decided" and tw["targets"]["PDI"] == 100


def test_a_closed_ibkr_segment_is_no_barrier(tmp_path):
    st, w, mk, d, out = setup(tmp_path)
    sources(st, [{"source": "ibkr_twin_ledger", "label": "y", "first": "2026-11-20", "last": "2026-11-25"},
                 {"source": "alpaca_eod_history", "label": "x", "first": "2026-11-26", "last": None}])
    assert run.send(d) == 0
    assert json.loads((st["twin"] / DAY / "plan.json").read_text())["books"]["cef"]["status"] == "decided"
