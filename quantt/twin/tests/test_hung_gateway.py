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
from quantt.session import gate as gt
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
    send = run.latest_send_record(st["twin"] / "2026-11-27")
    assert send["refusals"][0]["gate"] == "ibkr_read" and "RequestTimedOut" in send["refusals"][0]["detail"]


def test_on_a_13_00_close_the_batch_places_until_12_47_and_the_backup_refuses(tmp_path):
    """The placement deadline is the session's own (final check, 2026-11-25): a slow batch that began at
    12:30:05 keeps placing past 12:37 (start + 420 s, the limit it replaces) and stops at 12:47."""
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    day = st["twin"] / "2026-11-27"
    placed_at = []

    def utcnow():                                  # after STARTED, each reading of the clock is 150 s later
        if (day / "STARTED").exists():
            mk.now = mk.now + dt.timedelta(seconds=150)
        return mk.now.astimezone(dt.timezone.utc)
    d.utcnow = utcnow
    real = d.ibkr

    def ibkr(mode):
        c = real(mode)
        place = c.place_moc

        def timed(*a, **kw):
            placed_at.append(mk.now.astimezone(gt.ET))
            return place(*a, **kw)
        c.place_moc = timed
        return c
    d.ibkr = ibkr
    code = run.send(d)
    events = [json.loads(x)["event"] for x in (day / "orders.jsonl").read_text().splitlines()]
    assert "cutoff" in events and code != 0, out.getvalue()
    assert placed_at and max(placed_at) < F.et(2026, 11, 27, 12, 47)
    assert max(placed_at) >= F.et(2026, 11, 27, 12, 38)          # past start + 420 s: not the old limit
    assert "12:47 ET (the batch stop 12:48 less 60 s)" in (day / "send.json").read_text()
    n = len(w.placed)
    mk.now = F.et(2026, 11, 27, 12, 40, 5)                        # a backup that does start: STARTED refuses
    d.utcnow = lambda: mk.now.astimezone(dt.timezone.utc)
    d.ibkr = real
    assert run.send(d) == run.EXIT_REFUSED and len(w.placed) == n


def test_the_deadline_and_the_kill_on_each_close():
    for close, place_by, kill in ((F.et(2026, 11, 27, 13), F.et(2026, 11, 27, 12, 47), F.et(2026, 11, 27, 12, 48)),
                                  (F.et(2026, 11, 25, 16), F.et(2026, 11, 25, 15, 47), F.et(2026, 11, 25, 15, 48))):
        t = config.times(close)
        assert t["place_by"] == place_by
        assert t["slots"][0] + dt.timedelta(seconds=config.SEND_RUN_LIMIT_S) == kill     # just after place_by
        assert t["place_by"] < kill < t["freeze"]


def test_the_installed_send_limit_is_the_runners():
    import re
    from pathlib import Path
    t = (Path(config.REPO) / "quantt/deploy/install_twin_vm.sh").read_text()
    assert int(re.search(r"^SEND_TIMEOUT_S=(\d+)$", t, re.M).group(1)) == config.SEND_RUN_LIMIT_S
    from quantt.broker.ibkr import ACK_WAIT_S
    assert ACK_WAIT_S < config.SEND_PLACE_MARGIN_S
