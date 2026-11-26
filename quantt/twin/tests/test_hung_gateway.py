"""A half-alive Gateway that never answers must not hold the Gateway session lock (final review,
2026-11-25, a blocker for arming). The stub "hangs" the way ib_async does: with `RequestTimeout` at
its default 0 a request waits for ever (the stub raises AssertionError to say so); with it set, the
library gives up and raises TimeoutError. The client must set it, raise RequestTimedOut, and release
the lock, so the 12:30 send is not left waiting behind a hung 12:00 probe."""
from __future__ import annotations

import datetime as dt
import io
import json

import pytest

from quantt.broker import ibkr as I
from quantt.twin import config, run
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_send import S, armed, world_and_books


def hang(self, *a, **kw):
    if not getattr(self, "RequestTimeout", 0):
        raise AssertionError("RequestTimeout is 0: this request would wait for ever and hold the lock")
    raise TimeoutError()                       # what ib_async's util.run raises at RequestTimeout


def client(world, lock, mode="read", cid=31, mod=None):
    cfg = I.IBKRConfig("127.0.0.1", 4002, cid, F.ACCOUNT)
    return I.IBKRClient(cfg, mode=mode, ib_module=mod or F.stub_module(world), session_lock=lock,
                        lock_wait_s=0.0, sleep=lambda s: None)


@pytest.mark.parametrize("method,call", [("reqAllOpenOrders", lambda c: c.open_orders()),
                                         ("accountSummary", lambda c: c.account_summary()),
                                         ("reqExecutions", lambda c: c.executions_today(since=F.et(2026, 11, 27, 0)))])
def test_a_hung_request_raises_within_the_timeout_and_releases_the_lock(tmp_path, method, call):
    w = F.World()
    twin = tmp_path / "twin"
    twin.mkdir()
    lock = config.gateway_lock_path(twin)
    mod = F.stub_module(w)
    setattr(mod.IB, method, hang)
    c = client(w, lock, mod=mod).connect()
    assert c.ib.RequestTimeout == I.REQUEST_TIMEOUT_S
    with pytest.raises(I.RequestTimedOut, match=method):
        call(c)
    assert c.ib is None                                    # the session was dropped
    other = client(w, lock, cid=32).connect()              # and the lock is free at once (no wait)
    other.disconnect()


def test_a_hung_probe_does_not_make_the_next_send_wait(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    lock = config.gateway_lock_path(st["twin"])
    mod = F.stub_module(w)
    mod.IB.reqAllOpenOrders = hang
    d.ibkr = lambda mode: client(w, lock, mode=mode, mod=mod)
    mk.now = F.et(2026, 11, 27, 12, 0)
    assert run.probe(d) == 1                               # the probe refuses, named ...
    good = F.stub_module(w)
    d.ibkr = lambda mode: client(w, lock, mode=mode, mod=good)
    mk.now = F.et(2026, 11, 27, 12, 30, 5)
    assert run.send(d) == 0, out.getvalue()                # ... and the 12:30 send takes the lock
    assert w.placed


def test_a_hung_read_at_the_send_writes_a_record_and_sends_nothing(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    lock = config.gateway_lock_path(st["twin"])
    mod = F.stub_module(w)
    mod.IB.reqExecutions = hang
    d.ibkr = lambda mode: client(w, lock, mode=mode, mod=mod)
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    send = json.loads((st["twin"] / "2026-11-27" / "send.json").read_text())
    assert send["refusals"][0]["gate"] == "ibkr_read" and "RequestTimedOut" in send["refusals"][0]["detail"]


def test_a_slow_send_stops_placing_before_the_unit_is_killed_and_the_backup_refuses(tmp_path, monkeypatch):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    t0 = F.et(2026, 11, 27, 12, 30, 5)
    ticks = iter(range(0, 100000, 40))                    # every reading of the clock is 40 s later
    d.utcnow = lambda: (t0 + dt.timedelta(seconds=next(ticks))).astimezone(dt.timezone.utc)
    monkeypatch.setattr(config, "SEND_RUN_LIMIT_S", 300)
    code = run.send(d)
    day = st["twin"] / "2026-11-27"
    events = [json.loads(x)["event"] for x in (day / "orders.jsonl").read_text().splitlines()]
    assert "cutoff" in events and code != 0, out.getvalue()
    assert len(w.placed) < events.count("intent") + events.count("cutoff")
    assert "run limit" in (day / "send.json").read_text()
    n = len(w.placed)
    mk.now = F.et(2026, 11, 27, 12, 40, 5)                # the backup: STARTED stands, nothing more goes
    d.utcnow = lambda: mk.now.astimezone(dt.timezone.utc)
    assert run.send(d) == run.EXIT_REFUSED and len(w.placed) == n


def test_the_installed_send_limit_is_the_runners():
    import re
    from pathlib import Path
    t = (Path(config.REPO) / "quantt/deploy/install_twin_vm.sh").read_text()
    assert int(re.search(r"^SEND_TIMEOUT_S=(\d+)$", t, re.M).group(1)) == config.SEND_RUN_LIMIT_S
    assert config.SEND_RUN_LIMIT_S < (config.SEND_SLOT_MIN[0] - config.SEND_SLOT_MIN[1]) * 60
    from quantt.broker.ibkr import ACK_WAIT_S
    assert ACK_WAIT_S < config.SEND_RUN_MARGIN_S
