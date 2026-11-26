"""THE SESSION LOCK (quantt/broker/ibkr.py; B10): the twin and the feed are never connected to the Gateway at
the same moment. On a stub `ib_async` and a real flock in tmp_path: no socket.

Each test here fails against the client of a31c10c (no lock): there two clients connect side by side,
and the twin's entry point builds clients with no lock at all."""
from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from quantt.broker import ibkr as I
from quantt.twin import config, feed as FD
from quantt.twin import run as R
from quantt.twin import status
from quantt.twin.tests import fakes as F
from quantt.twin.tests import feed_fakes as X

REPO = Path(__file__).resolve().parents[3]


def cfg(cid):
    return I.IBKRConfig(host="127.0.0.1", port=4002, client_id=cid, account=F.ACCOUNT)


def locked(world, lock, cid, *, mode="read", wait=0.0, mono=None, sleeps=None):
    kw = {}
    if mono is not None:
        kw["monotonic"] = mono
    if sleeps is not None:
        kw["lock_sleep"] = sleeps
    return I.IBKRClient(cfg(cid), mode=mode, ib_module=F.stub_module(world), sleep=lambda s: None,
                        session_lock=lock, lock_wait_s=wait, **kw)


def test_a_second_client_is_refused_without_a_socket_while_the_first_is_connected(tmp_path):
    world, lock = F.World(), tmp_path / "twin" / config.GATEWAY_LOCK_NAME
    lock.parent.mkdir()
    a = locked(world, lock, 31, mode="trade").connect()
    with pytest.raises(I.GatewayBusy, match="no session was opened"):
        locked(world, lock, 34).connect()
    assert [c.client_id for c in world.connections] == [31]
    assert issubclass(I.GatewayBusy, I.NotConnected)         # every caller's "Gateway down" path takes it
    a.disconnect()
    b = locked(world, lock, 34).connect()
    assert [c.client_id for c in world.connections] == [31, 34]
    b.disconnect()


def test_a_waiting_client_polls_for_its_wait_and_then_stands_down(tmp_path):
    world, lock = F.World(), tmp_path / ".gateway.lock"
    a = locked(world, lock, 31).connect()
    t = {"now": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        t["now"] += s

    with pytest.raises(I.GatewayBusy, match="after 3s"):
        locked(world, lock, 32, wait=3.0, mono=lambda: t["now"], sleeps=sleep).connect()
    assert sum(slept) >= 3.0 and len(world.connections) == 1
    a.disconnect()


def test_the_lock_is_released_when_the_connect_fails_or_the_account_is_wrong(tmp_path):
    lock = tmp_path / ".gateway.lock"
    down = F.World()
    down.reachable = False
    with pytest.raises(I.NotConnected):
        locked(down, lock, 31).connect()
    other = F.World()
    other.accounts = ["DU9999999"]
    with pytest.raises(I.WrongAccount):
        locked(other, lock, 31).connect()
    ok = F.World()
    locked(ok, lock, 31).connect().disconnect()         # neither failure left the lock held
    assert len(ok.connections) == 1


def test_the_lock_file_names_its_holder_and_never_the_account(tmp_path):
    world, lock = F.World(), tmp_path / ".gateway.lock"
    a = locked(world, lock, 34).connect()
    text = lock.read_text()
    assert "client 34" in text and "mode read" in text and F.ACCOUNT not in text
    with pytest.raises(I.GatewayBusy) as e:
        locked(world, lock, 31).connect()
    assert "client 34" in str(e.value) and F.ACCOUNT not in str(e.value)
    a.disconnect()


def test_the_lock_path_is_the_twins_state_and_refuses_another_directory(tmp_path):
    assert config.gateway_lock_path(tmp_path / "twin") == tmp_path / "twin" / ".gateway.lock"
    with pytest.raises(config.ConfigError):
        config.gateway_lock_path(tmp_path / "cef")


def _env(states):
    return F.env_for(states, QUANTT_STATE_DIR=str(states["twin"]), QUANTT_IBKR_HOST="127.0.0.1",
                     QUANTT_IBKR_PORT="4002", QUANTT_IBKR_CLIENT_ID="31", QUANTT_IBKR_ACCOUNT=F.ACCOUNT,
                     QUANTT_IBKR_FEED_DIR=str(states["twin"].parent / "feed"))


def test_the_twins_entry_point_builds_every_client_with_the_lock_and_a_bounded_wait(tmp_path, monkeypatch):
    from quantt.twin import __main__ as main
    from quantt.twin import market
    monkeypatch.setattr(market.MarketData, "from_environment", classmethod(lambda cls, env: object()))
    states = F.make_states(tmp_path)
    deps = main._deps(_env(states))
    for mode in ("read", "trade"):
        c = deps.ibkr(mode)
        assert c._lock_path == states["twin"] / config.GATEWAY_LOCK_NAME
        assert c._lock_wait_s == config.TWIN_LOCK_WAIT_S > 0
    fdeps = main._feed_deps(_env(states))
    c = fdeps.read_client()
    assert c.mode == "read" and c._lock_path == states["twin"] / config.GATEWAY_LOCK_NAME and c._lock_wait_s == 0


def test_every_ibkr_client_built_outside_the_tests_passes_a_session_lock():
    """An IBKRClient built without `session_lock=` could connect beside the feed or the twin."""
    found = []
    for p in sorted(f for d in ("quantt", "ops", "scripts") for f in (REPO / d).rglob("*.py")):
        if "tests" in p.parts:
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == "IBKRClient":
                found.append(p.name)
                assert "session_lock" in {k.arg for k in n.keywords}, f"{p}: IBKRClient(...) without session_lock"
    assert sorted(found) == ["__main__.py", "__main__.py"]          # the twin's and the feed's


def test_the_feed_stands_down_while_the_twin_holds_the_gateway(tmp_path):
    start = F.et(2026, 11, 25, 16, 20)
    states, feed, env, world, mw, clock = X.feed_setup(tmp_path, start)
    for s in ("PDI", "PTY", "EVV", "SPY"):
        mw.bars[s] = X.bars_for(start.date())
    twin = locked(world, config.gateway_lock_path(states["twin"]), 31, mode="trade").connect()
    deps = X.feed_deps(states, feed, env, world, mw, clock)
    assert FD.run(deps, slot="after-close") == FD.EXIT_IDLE
    assert "session lock is held" in deps.out.getvalue()
    assert [c.client_id for c in world.connections] == [31] and mw.hist_calls == []
    twin.disconnect()
    assert FD.run(X.feed_deps(states, feed, env, world, mw, clock), slot="after-close") == FD.EXIT_OK


def test_the_twins_probe_is_refused_as_busy_while_the_feed_is_connected_and_says_nothing_of_the_login(tmp_path):
    states = F.make_states(tmp_path)
    world = F.World()
    lock = config.gateway_lock_path(states["twin"])
    feedc = locked(world, lock, 34).connect()
    market = F.FakeMarket(F.et(2026, 11, 25, 16, 30), F.nov_calendar())
    out = io.StringIO()
    deps = R.Deps(env=F.env_for(states), state=states["twin"], market=market,
                  ibkr=lambda mode: locked(world, lock, 31, mode=mode),
                  utcnow=lambda: market.now, out=out, own_clone=states["own_clone"],
                  unit_env=lambda unit: F.UNIT_ENV[unit])
    assert R.probe(deps) == 2
    assert "BUSY" in out.getvalue() and "LOGGED OUT" not in out.getvalue()
    assert "gateway" not in status.read(states["twin"])         # a busy lock is not a logout
    assert [c.client_id for c in world.connections] == [34]
    feedc.disconnect()
    assert R.probe(deps) == 0
