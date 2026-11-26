"""probe, epoch and cancel-open; and the package-wide promises: no Alpaca order path, no alert."""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

from quantt.twin import run
from quantt.twin.market import MarketData
from quantt.twin.tests import fakes as F

PKG = Path(__file__).resolve().parents[1]


def deps(tmp_path, world, **env):
    st = F.make_states(tmp_path)
    mk = F.FakeMarket(F.et(2026, 11, 28, 11, 0), F.nov_calendar())
    out = io.StringIO()
    return st, F.deps_for(st, world, mk, F.env_for(st, **env), out=out), out


def test_probe_cannot_place_or_cancel(tmp_path):
    """The probe is read-only by construction: a read client, and a read-only Gateway session."""
    w = F.World()
    w.positions = {"OLD": 10}
    st, d, out = deps(tmp_path, w, DRY_RUN="0")
    modes = []
    orig = d.ibkr
    d.ibkr = lambda mode: (modes.append(mode), orig(mode))[1]
    assert run.probe(d) == 0
    assert modes == ["read"] and w.placed == [] and w.cancelled == 0 and w.global_cancels == 0
    assert all(c.readonly for c in w.connections)
    line = out.getvalue()
    assert "logged in" in line and "OLD" not in line and F.ACCOUNT not in line   # aggregates only
    assert json.loads((st["twin"] / "status.json").read_text())["gateway"]["positions"] == 1


def _code_names(node) -> set:
    """Attribute names, bare names and string constants in CODE (docstrings excluded)."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 40:
            out.add(n.value)
    return out


def test_probe_source_never_names_a_write():
    fn = next(n for n in ast.parse((PKG / "run.py").read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == "probe")
    assert not _code_names(fn) & {"place_moc", "cancel", "global_cancel", "trade", "placeOrder"}


def test_probe_reports_a_logged_out_gateway(tmp_path):
    w = F.World()
    w.reachable = False
    st, d, out = deps(tmp_path, w)
    assert run.probe(d) == 2
    assert json.loads((st["twin"] / "status.json").read_text())["gateway"]["logged_in"] is False


def test_the_epoch_seeds_legacy_once(tmp_path):
    w = F.World()
    w.positions = {"OLD": 10, "OLD2": -3}
    st, d, out = deps(tmp_path, w)
    assert run.epoch(d) == 0
    led = json.loads((st["twin"] / "ledger.json").read_text())
    assert led["sleeves"]["legacy"]["shares"] == {"OLD": 10, "OLD2": -3}
    assert run.epoch(d) == run.EXIT_REFUSED and "once" in out.getvalue()


def test_the_epoch_refuses_while_an_order_rests(tmp_path):
    w = F.World()
    m = F.stub_module(w)
    ib = m.IB()
    ib.connect("h", 4002, clientId=5)
    o = m.Order()
    o.action, o.totalQuantity, o.orderType = "SELL", 34, "MOC"
    ib.placeOrder(m.Stock("OLD", "SMART", "USD"), o)
    st, d, out = deps(tmp_path, w)
    assert run.epoch(d) == run.EXIT_REFUSED and not (st["twin"] / "EPOCH.json").exists()


def test_cancel_open_lists_read_only_and_cancels_only_on_a_matching_confirm(tmp_path):
    w = F.World()
    m = F.stub_module(w)
    ib = m.IB()
    ib.connect("h", 4002, clientId=5)
    for s in ("A", "B"):
        o = m.Order()
        o.action, o.totalQuantity, o.orderType = "SELL", 1, "MOC"
        ib.placeOrder(m.Stock(s, "SMART", "USD"), o)
    st, d, out = deps(tmp_path, w, DRY_RUN="1")
    assert run.cancel_open(d, confirm=None) == 0 and w.global_cancels == 0
    assert "2 open order(s)" in out.getvalue()
    assert run.cancel_open(d, confirm=2) == run.EXIT_REFUSED and w.global_cancels == 0   # DRY_RUN wins
    d.env["DRY_RUN"] = "0"
    assert run.cancel_open(d, confirm=1) == run.EXIT_REFUSED and w.global_cancels == 0   # count differs
    d.env["QUANTT_TWIN_STAGING"] = "1"
    assert run.cancel_open(d, confirm=2) == run.EXIT_REFUSED and w.global_cancels == 0
    del d.env["QUANTT_TWIN_STAGING"]
    assert run.cancel_open(d, confirm=2) == 0 and w.global_cancels == 1


def test_the_twin_never_names_an_alpaca_order_or_an_alert():
    for p in sorted(PKG.rglob("*.py")):
        if "tests" in p.parts:
            continue
        names = _code_names(ast.parse(p.read_text()))
        assert not names & {"submit_order", "alert", "smtplib", "SMTP"}, f"{p.name}: {names & {'submit_order', 'alert'}}"
    assert not hasattr(MarketData, "submit_order")
    with pytest.raises(AttributeError):
        MarketData(object()).x = 1


def test_nothing_in_the_twin_writes_under_the_alpaca_packages():
    """The twin imports the books' checks; it must not import a module that writes their state."""
    for p in sorted(PKG.rglob("*.py")):
        if "tests" in p.parts:
            continue
        tree = ast.parse(p.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith(("quantt.collect",)):
                raise AssertionError(f"{p.name} imports {n.module}")
