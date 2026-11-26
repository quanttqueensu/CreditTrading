"""B10, the IBKR market-data feed (quantt/twin/feed.py, quantt/broker/ibkr_market.py), on a stub `ib_async`.

What is pinned: the producer can place, cancel or modify nothing; delayed data is labelled delayed and never
live; a symbol IBKR does not serve is UNMEASURED with IBKR's code; pacing is kept by spacing, and a pacing
violation stops the run with no retry; the twin's windows and the slots (early close included); no partial
bar; the files' modes, group and hashes; the account id never reaches a file; and the request files from
the shadow user are read as hostile input. No socket, no library (root conftest.py)."""
from __future__ import annotations

import ast
import csv
import datetime as dt
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from quantt.broker import ibkr as I
from quantt.broker import ibkr_market as M
from quantt.twin import config, feed as FD
from quantt.twin.tests import fakes as F
from quantt.twin.tests import feed_fakes as X

REPO = Path(__file__).resolve().parents[3]
WED = dt.date(2026, 11, 25)          # a 16:00 close
FRI = dt.date(2026, 11, 27)          # a 13:00 close (the day after Thanksgiving)
TUE = dt.date(2026, 11, 24)


def run_feed(tmp_path, start, slot, *, books=None, setup=None, **kw):
    states, feed, env, world, mw, clock = X.feed_setup(tmp_path, start, books)
    if setup:
        setup(mw, feed, states)
    deps = X.feed_deps(states, feed, env, world, mw, clock, **kw)
    code = FD.run(deps, slot=slot)
    return code, deps, world, mw, feed


def manifest_of(feed: Path, day: dt.date) -> dict:
    d = feed / day.isoformat()
    names = sorted(p.name for p in d.iterdir() if p.name.startswith("manifest-"))
    assert names, f"no manifest in {d}"
    return json.loads((d / names[-1]).read_text())


def bars_csv(feed: Path, man: dict) -> list:
    with open(feed / man["session"] / man["files"]["bars"]["name"], newline="") as f:
        return list(csv.DictReader(f))


def all_bars(mw, syms, last, n=3):
    for s in syms:
        mw.bars[s] = X.bars_for(last, n)


# ------------------------------------------------------------------ read only

ORDER_NAMES = {"place_moc", "placeOrder", "cancel", "cancelOrder", "global_cancel", "reqGlobalCancel",
               "submit_order", "replace_order", "cancel_order", "whatIfOrder", "bracketOrder"}


@pytest.mark.parametrize("rel", ["quantt/broker/ibkr_market.py", "quantt/twin/feed.py"])
def test_the_feed_and_its_reader_name_no_order_method(rel):
    tree = ast.parse((REPO / rel).read_text())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & ORDER_NAMES, f"{rel} names {names & ORDER_NAMES}"


def test_a_full_run_places_cancels_and_modifies_nothing_and_connects_read_only(tmp_path):
    start = F.et(2026, 11, 25, 16, 20)
    code, deps, world, mw, feed = run_feed(tmp_path, start, "after-close",
                                           setup=lambda mw, f, s: all_bars(mw, ["PDI", "PTY", "EVV", "SPY"], WED))
    assert code == FD.EXIT_OK, deps.out.getvalue()
    assert world.placed == [] and world.cancelled == 0 and world.global_cancels == 0
    assert [c.readonly for c in world.connections] == [True] and world.connections[0].client_id == 34


def test_the_feed_refuses_a_trade_client_before_connecting(tmp_path):
    start = F.et(2026, 11, 25, 16, 20)
    code, deps, world, mw, feed = run_feed(tmp_path, start, "after-close", mode="trade")
    assert code == FD.EXIT_REFUSED and "not in read mode" in deps.out.getvalue()
    assert world.connections == [] and mw.hist_calls == []


def test_the_market_reader_refuses_a_trade_client(tmp_path):
    world, mw, clock = F.World(), X.MarketWorld(), X.Clock(F.et(2026, 11, 25, 16, 20))
    mod = X.market_module(world, mw, clock)
    c = I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 34, F.ACCOUNT), mode="trade", ib_module=mod,
                     sleep=lambda s: None).connect()
    with pytest.raises(I.ReadOnlyClient):
        M.MarketReader(c, pacer=M.Pacer(10, monotonic=clock.monotonic, wait=clock.advance),
                       request_timeout_s=30, scrub=str)


def test_a_read_client_still_cannot_place_through_the_feeds_connection(tmp_path):
    """The read mode IS the guard (quantt/broker/ibkr.py): the client the feed holds refuses orders."""
    start = F.et(2026, 11, 25, 16, 20)
    states, feed, env, world, mw, clock = X.feed_setup(tmp_path, start)
    deps = X.feed_deps(states, feed, env, world, mw, clock)
    c = deps.read_client().connect()
    try:
        c.qualify(["PDI"])
        with pytest.raises(I.ReadOnlyClient):
            c.place_moc("PDI", 1, "buy", "feed-x")
        with pytest.raises(I.ReadOnlyClient):
            c.global_cancel()
    finally:
        c.disconnect()
    assert world.placed == []


# ------------------------------------------------------------------ labels and gaps

def test_quote_labels_never_call_delayed_live():
    assert M.quote_label("delayed", 3) == "delayed" and M.quote_label("delayed", 1) == "delayed"
    assert M.quote_label("delayed", None) == "delayed" and M.quote_label("delayed", 4) == "delayed_frozen"
    assert M.quote_label("live", 1) == "live" and M.quote_label("live", 2) == "frozen"
    assert M.quote_label("live", 3) == "unlabelled" and M.quote_label("live", 4) == "unlabelled"
    assert M.quote_label("live", None) == "unlabelled"
    assert set(M.DELAYED_PRICE_TICKS) == {66, 67, 68, 75} and set(M.LIVE_PRICE_TICKS) == {1, 2, 4, 9}


def test_an_intraday_run_labels_every_quote_by_the_tick_that_carried_it(tmp_path):
    start = F.et(2026, 11, 25, 10, 30)

    def setup(mw, feed, states):
        all_bars(mw, ["DLY", "LIV", "MIX", "NOP", "DFZ"], TUE)
        mw.ticks["DLY"] = [(66, 10.0), (67, 10.2), (68, 10.1), (75, 9.9)]
        mw.reported["DLY"] = 3
        mw.ticks["LIV"] = [(1, 20.0), (2, 20.1), (4, 20.05), (9, 19.8)]        # no type reported: live
        mw.ticks["MIX"] = [(1, 30.0), (68, 30.2)]
        mw.reported["MIX"] = 3                                                 # IBKR says delayed
        mw.quote_errors["NOP"] = [(354, X.NOT_SUBSCRIBED_STUB)]
        mw.ticks["DFZ"] = [(75, 5.0)]
        mw.reported["DFZ"] = 4

    code, deps, world, mw, feed = run_feed(tmp_path, start, "intraday",
                                           books={"cef": ["DLY", "LIV", "MIX"], "c4": ["NOP"], "events": ["DFZ"]},
                                           setup=setup)
    assert code == FD.EXIT_PARTIAL, deps.out.getvalue()
    man = manifest_of(feed, WED)
    with open(feed / "2026-11-25" / man["files"]["quotes"]["name"], newline="") as f:
        q = {r["symbol"]: r for r in csv.DictReader(f)}
    assert {q["DLY"][k + "_type"] for k in ("bid", "ask", "last", "close")} == {"delayed"}
    assert {q["LIV"][k + "_type"] for k in ("bid", "ask", "last", "close")} == {"live"}
    assert q["MIX"]["bid_type"] == "unlabelled" and q["MIX"]["last_type"] == "delayed"
    assert q["DFZ"]["close_type"] == "delayed_frozen" and q["DFZ"]["bid"] == ""
    for r in q.values():                       # no delayed-numbered tick is ever written as live
        for k in ("bid", "ask", "last", "close"):
            if r[k + "_tick"] and int(r[k + "_tick"]) >= 66:
                assert r[k + "_type"] != "live"
    assert "NOP" not in q
    gap = [u for u in man["unmeasured"] if u["symbol"] == "NOP"]
    assert gap and gap[0]["what"] == "quote" and gap[0]["codes"] == [354]
    assert man["requested_market_data_type"] == 3 and mw.market_types == [3]
    assert all(rs is False and snap is False for _, snap, rs in mw.mkt_calls)      # never a paid snapshot
    assert sorted(mw.cancels) == sorted(s for s, _, _ in mw.mkt_calls)            # every line cancelled


def test_a_symbol_ibkr_does_not_serve_is_unmeasured_with_its_code_and_never_filled(tmp_path):
    start = F.et(2026, 11, 25, 16, 20)

    def setup(mw, feed, states):
        all_bars(mw, ["PDI", "PTY", "SPY"], WED)
        mw.hist_errors["EVV"] = [(162, X.NO_PERMISSION_STUB)]       # no bars come back
        mw.unknown.add("PTY")

    code, deps, world, mw, feed = run_feed(tmp_path, start, "after-close", setup=setup)
    assert code == FD.EXIT_PARTIAL
    man = manifest_of(feed, WED)
    rows = bars_csv(feed, man)
    assert {r["symbol"] for r in rows} == {"PDI", "SPY"}
    un = {u["symbol"]: u for u in man["unmeasured"]}
    assert un["EVV"]["what"] == "bars" and un["EVV"]["codes"] == [162]
    assert un["PTY"]["what"] == "contract" and un["PTY"]["codes"] == [200]
    assert {r["source"] for r in rows} == {"ibkr"} and {r["data_type"] for r in rows} == {"historical"}


# ------------------------------------------------------------------ pacing

def test_requests_are_spaced_one_at_a_time_each_symbol_once_with_the_ruled_shape(tmp_path):
    start = F.et(2026, 11, 25, 16, 20)
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    code, deps, world, mw, feed = run_feed(tmp_path, start, "after-close", books={"cef": syms, "c4": [], "events": []},
                                           setup=lambda mw, f, s: all_bars(mw, syms, WED))
    assert code == FD.EXIT_OK, deps.out.getvalue()
    times = [t for t, _, _ in mw.hist_calls]
    assert [s for _, s, _ in mw.hist_calls] == syms
    assert all(b - a >= deps.settings.request_spacing_s - 1e-9 for a, b in zip(times, times[1:]))
    assert deps.settings.request_spacing_s >= 600 / 60                 # the strictest IBKR family
    for _, _, r in mw.hist_calls:
        assert r == {"end": "", "duration": deps.settings.bar_duration, "bar": "1 day", "what": "TRADES",
                     "rth": True, "keep": False, "format": 1, "timeout": deps.settings.request_timeout_s}


def test_a_pacing_violation_stops_the_run_with_no_retry(tmp_path):
    start = F.et(2026, 11, 25, 16, 20)
    syms = ["AAA", "BBB", "CCC", "DDD"]

    def setup(mw, feed, states):
        all_bars(mw, syms, WED)
        mw.pacing_on.add("BBB")

    code, deps, world, mw, feed = run_feed(tmp_path, start, "after-close", books={"cef": syms, "c4": [], "events": []},
                                           setup=setup)
    assert code == FD.EXIT_PARTIAL
    assert [s for _, s, _ in mw.hist_calls] == ["AAA", "BBB"]          # nothing after, BBB never again
    man = manifest_of(feed, WED)
    assert man["stopped"].startswith("PacingViolation")
    un = {u["symbol"]: u["reason"] for u in man["unmeasured"]}
    assert set(un) == {"BBB", "CCC", "DDD"} and all("the run stopped" in r for r in un.values())


def test_the_run_stops_before_the_twins_next_window_and_names_what_it_did_not_reach(tmp_path):
    start = F.et(2026, 11, 25, 15, 5)            # intraday; the 15:15 probe window opens 15:12
    syms = [f"S{c}{d}" for c in "ABCDEFGH" for d in "ABCDE"]           # 40 symbols, 400 s at 10 s spacing
    code, deps, world, mw, feed = run_feed(tmp_path, start, "intraday", books={"cef": syms, "c4": [], "events": []},
                                           setup=lambda mw, f, s: all_bars(mw, syms, TUE))
    assert code == FD.EXIT_PARTIAL
    man = manifest_of(feed, WED)
    stop = dt.datetime.fromisoformat(man["stop_by"]["at"])
    assert stop <= F.et(2026, 11, 25, 15, 12) and "probe 15:15" in man["stop_by"]["why"]
    assert all(X.Clock(start).start + dt.timedelta(seconds=t) < stop for t, _, _ in mw.hist_calls)
    assert man["stopped"].startswith("deadline") and len(mw.hist_calls) < len(syms)
    assert mw.mkt_calls == []                    # a stopped run takes no quotes


# ------------------------------------------------------------------ the times

@pytest.mark.parametrize("when,slot,runs", [
    (F.et(2026, 11, 27, 13, 20), "after-close", True),     # 13:00 close: the 13:20 fire runs
    (F.et(2026, 11, 27, 16, 20), "after-close", False),    # ... and the 16:20 fire idles
    (F.et(2026, 11, 25, 13, 20), "after-close", False),    # 16:00 close: the 13:20 fire idles
    (F.et(2026, 11, 25, 16, 20), "after-close", True),
    (F.et(2026, 11, 25, 20, 20), "evening", True),
    (F.et(2026, 11, 27, 20, 20), "evening", True),
    (F.et(2026, 11, 25, 16, 20), "evening", False),
    (F.et(2026, 11, 26, 20, 20), "evening", False),        # Thanksgiving
    (F.et(2026, 11, 25, 15, 30), "intraday", False),       # inside the twin's send window
    (F.et(2026, 11, 27, 12, 30), "intraday", False),       # the early-close send window
    (F.et(2026, 11, 25, 9, 1), "intraday", False),         # before the open (and the 09:00 probe)
    (F.et(2026, 11, 25, 17, 45), "evening", False),
])
def test_the_slots_and_the_twins_windows(tmp_path, when, slot, runs):
    syms = ["PDI", "PTY", "EVV", "SPY"]
    code, deps, world, mw, feed = run_feed(tmp_path, when, slot,
                                           setup=lambda mw, f, s: all_bars(mw, syms, when.date()))
    if runs:
        assert code == FD.EXIT_OK, deps.out.getvalue()
        assert len(world.connections) == 1
    else:
        assert code == FD.EXIT_IDLE, deps.out.getvalue()
        assert world.connections == [] and mw.hist_calls == []


def test_the_windows_are_the_twins_own_times():
    from quantt.session.gate import ET
    w = {x.name: (x.start.time(), x.end.time()) for x in FD.windows(WED, F.et(2026, 11, 25, 16, 0))}
    assert w["twin send (16:00 close)"] == (dt.time(15, 25), dt.time(15, 50))
    assert w["twin send (13:00 close)"] == (dt.time(12, 25), dt.time(12, 50))
    assert w["twin verify 17:45"] == (dt.time(17, 40), dt.time(17, 55))
    for v in config.VERIFY_SLOTS_ET:                 # every verify slot, the 07:00 catch-up included
        assert f"twin verify {v:%H:%M}" in w
    assert {f"twin probe {p:%H:%M}" for p in config.PROBE_ET} <= set(w)
    assert ET is not None


def test_an_intraday_run_writes_no_partial_bar_and_an_after_close_run_keeps_the_session(tmp_path):
    syms = ["PDI", "PTY", "EVV", "SPY"]
    code, deps, world, mw, feed = run_feed(tmp_path / "a", F.et(2026, 11, 25, 11, 0), "intraday",
                                           setup=lambda mw, f, s: all_bars(mw, syms, WED))
    man = manifest_of(feed, WED)
    assert man["complete_through"] == "2026-11-24" and man["dropped_partial_bars"] == 4
    assert max(r["date"] for r in bars_csv(feed, man)) == "2026-11-24"
    code, deps, world, mw, feed = run_feed(tmp_path / "b", F.et(2026, 11, 25, 16, 20), "after-close",
                                           setup=lambda mw, f, s: all_bars(mw, syms, WED))
    man = manifest_of(feed, WED)
    assert man["complete_through"] == "2026-11-25" and man["dropped_partial_bars"] == 0
    assert max(r["date"] for r in bars_csv(feed, man)) == "2026-11-25"


# ------------------------------------------------------------------ files

def test_the_files_are_the_readers_group_0640_in_a_2750_session_dir_and_the_manifest_hashes_them(tmp_path):
    syms = ["PDI", "PTY", "EVV", "SPY"]
    code, deps, world, mw, feed = run_feed(tmp_path, F.et(2026, 11, 25, 16, 20), "after-close",
                                           setup=lambda mw, f, s: all_bars(mw, syms, WED))
    d = feed / "2026-11-25"
    gid = os.stat(feed).st_gid
    assert stat.S_IMODE(os.lstat(d).st_mode) == 0o2750 and os.lstat(d).st_gid == gid
    for p in d.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o640 and p.stat().st_gid == gid, p
    man = manifest_of(feed, WED)
    b = man["files"]["bars"]
    data = (d / b["name"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == b["sha256"] and len(data) == b["bytes"]
    assert data.decode().splitlines()[0] == ",".join(FD.BARS_COLUMNS)
    assert man["label"] == FD.LABEL and "never evidence" in man["label"]


def test_bars_columns_are_the_shadow_readers():
    """shadow/ibkr_feed.py (the shadow branch) pins the same literal; change both together."""
    assert FD.BARS_COLUMNS == ("symbol", "date", "open", "high", "low", "close", "volume", "wap", "bar_count",
                               "source", "data_type", "what_to_show", "use_rth", "bar_size", "fetched_utc")
    assert FD.SYMBOL_RE.pattern == r"^[A-Z]{1,5}(?:\.[A-Z])?$"


def test_a_feed_file_is_never_rewritten(tmp_path):
    d = X.make_feed_dir(tmp_path)
    FD._write(d / "bars-20261125T212000Z.csv", b"x", gid=os.stat(d).st_gid)
    with pytest.raises(FD.FeedRefused, match="never rewritten"):
        FD._write(d / "bars-20261125T212000Z.csv", b"y", gid=os.stat(d).st_gid)


def test_the_account_id_never_reaches_a_file(tmp_path):
    def setup(mw, feed, states):
        all_bars(mw, ["PDI", "PTY", "SPY"], WED)
        mw.hist_errors["EVV"] = [(321, f"Error validating request for account {F.ACCOUNT} (stub)")]
        mw.global_msgs = [(2104, f"Market data farm connection is OK:usfarm {F.ACCOUNT} (stub)")]

    code, deps, world, mw, feed = run_feed(tmp_path, F.et(2026, 11, 25, 16, 20), "after-close", setup=setup)
    blob = "".join(p.read_text() for p in (feed / "2026-11-25").iterdir()) + deps.out.getvalue()
    assert F.ACCOUNT not in blob and "<account>" in blob


def test_a_second_run_of_the_session_counts_the_closes_ibkr_revised(tmp_path):
    states, feed, env, world, mw, clock = X.feed_setup(tmp_path, F.et(2026, 11, 25, 16, 20))
    all_bars(mw, ["PDI", "PTY", "EVV", "SPY"], WED)
    assert FD.run(X.feed_deps(states, feed, env, world, mw, clock), slot="after-close") == FD.EXIT_OK
    d, o, h, lo, c, v = mw.bars["PDI"][-1]
    mw.bars["PDI"][-1] = (d, o, h, lo, c + 0.01, v)
    clock2 = X.Clock(F.et(2026, 11, 25, 20, 20))
    assert FD.run(X.feed_deps(states, feed, env, world, mw, clock2), slot="evening") == FD.EXIT_OK
    man = manifest_of(feed, WED)
    assert man["slot"] == "evening" and man["revision"]["compared"] == 4 and man["revision"]["changed_close"] == 1


def test_a_logged_out_gateway_writes_a_manifest_naming_every_symbol_unmeasured(tmp_path):
    states, feed, env, world, mw, clock = X.feed_setup(tmp_path, F.et(2026, 11, 25, 16, 20))
    world.reachable = False
    deps = X.feed_deps(states, feed, env, world, mw, clock)
    assert FD.run(deps, slot="after-close") == FD.EXIT_REFUSED
    man = manifest_of(feed, WED)
    assert man["files"]["bars"] is None and man["stopped"].startswith("gateway")
    assert {u["symbol"] for u in man["unmeasured"]} == {"PDI", "PTY", "EVV", "SPY"}


def test_the_sandbox_check_refuses_a_writable_requests_dir(tmp_path):
    states, feed, env, world, mw, clock = X.feed_setup(tmp_path, F.et(2026, 11, 25, 16, 20))
    deps = X.feed_deps(states, feed, env, world, mw, clock)
    assert FD.run(deps, slot="after-close", require_sandbox=True) == FD.EXIT_REFUSED
    assert "not inside the sandbox" in deps.out.getvalue() and world.connections == []


def test_the_settings_file_has_every_key_and_refuses_a_spacing_below_the_strict_family(tmp_path):
    s = FD.load_settings()
    assert s.request_spacing_s >= 10 and s.market_data_type == 3 and s.max_symbols > 0
    raw = json.loads(FD.SETTINGS_PATH.read_text())
    bad = tmp_path / "f.json"
    bad.write_text(json.dumps({**raw, "request_spacing_s": 1}))
    with pytest.raises(FD.FeedRefused, match="request_spacing_s"):
        FD.load_settings(bad)
    bad.write_text(json.dumps({k: v for k, v in raw.items() if k != "max_symbols"}))
    with pytest.raises(FD.FeedRefused, match="max_symbols"):
        FD.load_settings(bad)


def test_the_symbol_cap_names_what_it_left_out(tmp_path):
    s = FD.load_settings()
    small = FD.FeedSettings(**{**s.to_dict(), "max_symbols": 2})
    code, deps, world, mw, feed = run_feed(tmp_path, F.et(2026, 11, 25, 16, 20), "after-close", settings=small,
                                           setup=lambda mw, f, st: all_bars(mw, ["PDI", "PTY", "EVV", "SPY"], WED))
    man = manifest_of(feed, WED)
    assert code == FD.EXIT_PARTIAL and man["symbols"]["asked"] == 2 and len(man["symbols"]["over_cap"]) == 2
    assert len(mw.hist_calls) == 2


# ------------------------------------------------------------------ request files

def req_dir(tmp_path) -> Path:
    d = tmp_path / "requests"
    d.mkdir(parents=True)
    os.chmod(d, 0o750)
    return d


def read(d, uid=None, **over):
    s = FD.load_settings()
    s = FD.FeedSettings(**{**s.to_dict(), **over})
    return FD.read_requests(d, s, producer_uid=os.getuid() + 1 if uid is None else uid)


def test_requests_take_only_tickers_one_a_line(tmp_path):
    d = req_dir(tmp_path)
    (d / "pead_small_long.txt").write_text("# my book\nAAPL\n\n  MSFT  \nBRK.B\nAAPL\n")
    r = read(d)
    assert r["symbols"] == ["AAPL", "BRK.B", "MSFT"] and r["files"] == ["pead_small_long.txt"] and not r["rejected"]


def test_garbage_lines_are_rejected_by_line_number_and_never_echoed(tmp_path):
    d = req_dir(tmp_path)
    lines = ["aapl", "AAPL; rm -rf /", "../../etc/passwd", "TOOLONGX", "BRK/B", "SECRETTOKENXYZ", "A B", "OK"]
    (d / "evil.txt").write_text("\n".join(lines) + "\n")
    r = read(d)
    assert r["symbols"] == ["OK"]
    assert sorted(x["line"] for x in r["rejected"]) == [1, 2, 3, 4, 5, 6, 7]
    blob = json.dumps(r)
    for bad in lines[:-1]:
        assert bad not in blob


@pytest.mark.parametrize("name", ["Evil.txt", "a.b.txt", "x.json", "-x.txt", "x" * 70 + ".txt", "x.txt.bak", "x y.txt"])
def test_a_bad_file_name_is_rejected(tmp_path, name):
    d = req_dir(tmp_path)
    (d / name).write_text("AAPL\n")
    r = read(d)
    assert r["symbols"] == [] and len(r["rejected"]) == 1 and "file name" in r["rejected"][0]["reason"]


def test_a_symlink_is_refused_not_followed(tmp_path):
    d = req_dir(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("ZZZZ\n")
    (d / "link.txt").symlink_to(secret)
    r = read(d)
    assert r["symbols"] == [] and r["rejected"] == [{"file": "link.txt", "reason": "a symbolic link"}]


def test_a_symlinked_requests_directory_is_refused(tmp_path):
    real = req_dir(tmp_path)
    (real / "a.txt").write_text("AAPL\n")
    link = tmp_path / "requests_link"
    link.symlink_to(real)
    r = read(link)
    assert r["symbols"] == [] and "cannot open" in r["rejected"][0]["reason"]


def test_a_fifo_a_directory_and_a_hard_link_are_refused_without_hanging(tmp_path):
    d = req_dir(tmp_path)
    os.mkfifo(d / "pipe.txt")
    (d / "dir.txt").mkdir()
    (d / "one.txt").write_text("AAPL\n")
    os.link(d / "one.txt", d / "two.txt")
    r = read(d)
    why = {x["file"]: x["reason"] for x in r["rejected"]}
    assert why["pipe.txt"] == "not a regular file" and why["dir.txt"] == "not a regular file"
    assert why["one.txt"] == "has 2 links" and why["two.txt"] == "has 2 links" and r["symbols"] == []


def test_size_ascii_and_caps(tmp_path):
    d = req_dir(tmp_path)
    (d / "big.txt").write_text("AAPL\n" * 5000)
    (d / "uni.txt").write_bytes("ÄPPL\n".encode())
    r = read(d)
    why = {x["file"]: x["reason"] for x in r["rejected"]}
    assert "bytes" in why["big.txt"] and why["uni.txt"] == "not ASCII text"
    d2 = req_dir(tmp_path / "b")
    for i in range(4):
        (d2 / f"f{i}.txt").write_text("\n".join(f"A{chr(65 + i)}{chr(65 + j)}" for j in range(5)) + "\n")
    r = read(d2, max_request_files=3, max_request_symbols=7)
    assert len(r["files"]) == 3 and len(r["symbols"]) == 7
    assert any("over the cap of 3 files" in x["reason"] for x in r["rejected"])
    assert any("over the cap of 7" in x["reason"] for x in r["rejected"])


def test_the_requests_directory_must_be_the_shadow_users_and_not_world_writable(tmp_path):
    d = req_dir(tmp_path)
    (d / "a.txt").write_text("AAPL\n")
    r = read(d, uid=os.getuid())
    assert r["symbols"] == [] and "producer's own" in r["rejected"][0]["reason"]
    os.chmod(d, 0o777)
    r = read(d)
    assert r["symbols"] == [] and "world-writable" in r["rejected"][0]["reason"]


def test_a_writers_temporary_file_is_ignored(tmp_path):
    d = req_dir(tmp_path)
    (d / ".a.txt.123.tmp").write_text("AAPL\n")
    r = read(d)
    assert r["symbols"] == [] and r["ignored"] == 1 and r["rejected"] == []


def test_requested_symbols_join_the_books_and_reach_the_manifest(tmp_path):
    def setup(mw, feed, states):
        all_bars(mw, ["PDI", "PTY", "EVV", "SPY", "IEF"], WED)
        (feed / "requests" / "month_end_ief.txt").write_text("IEF\nPDI\nbad line\n")

    code, deps, world, mw, feed = run_feed(tmp_path, F.et(2026, 11, 25, 16, 20), "after-close", setup=setup)
    man = manifest_of(feed, WED)
    assert [s for _, s, _ in mw.hist_calls] == ["EVV", "PDI", "PTY", "SPY", "IEF"]     # the books first
    assert man["symbols"]["from_requests"] == 1 and man["requests"]["files"] == ["month_end_ief.txt"]
    assert man["requests"]["rejected"] == [{"file": "month_end_ief.txt", "line": 3,
                                            "reason": "not a ticker (one per line, [A-Z]{1,5} with an optional .[A-Z] class)"}]


# ------------------------------------------------------------------ pins to the installer and IBC

def test_the_twins_times_here_are_the_installers_timers():
    t = (REPO / "quantt/deploy/install_twin_vm.sh").read_text()
    slots = " ".join(f'"Mon..Fri *-*-* {v:%H:%M}:00"' for v in config.VERIFY_SLOTS_ET)
    assert f'timer verify {slots}' in t
    from quantt.twin import verify
    assert config.VERIFY_SLOTS_ET[-1] == verify.LAST_SLOT
    probe = " ".join(f'"Mon..Fri *-*-* {p:%H:%M}:00"' for p in config.PROBE_ET)
    assert f"timer probe {probe}" in t
    assert 'timer feed-close "Mon..Fri *-*-* 13:20:00" "Mon..Fri *-*-* 16:20:00"' in t
    assert 'timer feed-evening "Mon..Fri *-*-* 19:05:00"' in t
    for c in FD.STANDARD_CLOSES:                      # the after-close timer is close + SETTLE on both closes
        fire = (dt.datetime.combine(WED, c) + FD.SETTLE).time()
        assert f"{fire:%H:%M}:00" in t


def test_the_gateway_restart_the_feed_avoids_is_the_one_ibc_sets():
    from quantt.deploy import ibc_config as C
    text = C.render({C.ENV_USERNAME: "u", C.ENV_PASSWORD: "p"}, api_port=4002, order_precautions="keep")
    kv = dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln and not ln.startswith("#"))
    assert dt.datetime.strptime(kv["AutoRestartTime"], "%I:%M %p").time() == FD.GATEWAY_RESTART_ET
