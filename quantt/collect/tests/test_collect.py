"""quantt/collect: the data day, idempotent steps, flags vs gaps, and read-only at the broker.

What these pin (the collector's brief, team lead 2026-09-29):
  * D is the latest day BOTH calendars call trading whose close + 45 min has
    passed by Alpaca's clock; a calendar disagreement raises naming both.
  * A completed step is never redone, a failed one is retried, and a day whose
    steps are all ok is one IDLE line with no network beyond clock + calendar.
  * Cross-check disagreements are FLAGS and never fail anything (report only);
    a value a source does not have is a GAP, never a substitute.
  * The official-close file is de-duplicated on (date, ticker).
  * The package never names the client's transmit method.

Hermetic: `FakeClient` has only GETs (no transmit method at all), subprocesses
and CEFConnect are injected fakes, panels and state live under tmp_path, and
the root conftest's netguard refuses any socket.
"""
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from ops.schedule.nyse_calendar import is_trading_day
from quantt.broker import alpaca as al
from quantt.collect import collect as co

ET = co.ET
D = dt.date(2026, 9, 29)            # Tuesday
PREV = dt.date(2026, 9, 28)         # Monday
NEXT = dt.date(2026, 9, 30)
DEPLOYED = ["AAA", "BBB"]
UNIVERSE = ["AAA", "BBB", "CCC"]


def et(day, h, m=0):
    return dt.datetime.combine(day, dt.time(h, m), ET)


class FakeClient:
    """The GET surface of AlpacaClient in its parsed shapes. No transmit method."""

    def __init__(self, *, now=None, is_open=False, next_open=None, extra_days=(),
                 missing_days=(), prints=None):
        self.now = now or et(D, 21, 0)
        self.is_open = is_open
        self.next_open = next_open or et(NEXT, 9, 30)
        self.extra, self.missing = set(extra_days), set(missing_days)
        self.prints = {"AAA": 9.50, "BBB": 19.00, "CCC": 5.00} if prints is None else prints
        self.calls = []

    def clock(self):
        self.calls.append("clock")
        return {"timestamp": self.now, "is_open": self.is_open, "next_open": self.next_open,
                "next_close": self.next_open + dt.timedelta(hours=6, minutes=30), "raw": {}}

    def calendar(self, start, end):
        self.calls.append("calendar")
        out, d = [], start
        while d <= end:
            if (is_trading_day(d) or d in self.extra) and d not in self.missing:
                out.append({"date": d, "open": "09:30", "close": "16:00", "raw": {}})
            d += dt.timedelta(days=1)
        return out

    def stock_exchanges(self):
        self.calls.append("exchanges")
        return {"N": "New York Stock Exchange"}

    def primary_sip_code(self, symbol, exchanges):
        return "N"

    def closing_auction_prints(self, symbols, date, *, exchange_codes, condition="M"):
        assert len(symbols) == 1 and exchange_codes == {symbols[0]: "N"} and condition == "M"
        self.calls.append(("prints", symbols[0]))
        p = self.prints.get(symbols[0])
        if p is None:
            raise al.MissingAuctionPrint(f"no print for {symbols}", symbols=list(symbols))
        return {symbols[0]: {"price": p, "exchange": "N", "condition": "M",
                             "t": "2026-09-29T20:00:01Z"}}

    def account(self):
        self.calls.append("account")
        return {"id": "acct", "status": "ACTIVE", "equity": 100_500.0, "last_equity": 100_000.0,
                "cash": 50_000.0, "long_market_value": 80_000.0,
                "short_market_value": -29_500.0, "raw": {"api_key_echo": "SHOULD-NOT-APPEAR"},
                "auth_token": "SHOULD-NOT-APPEAR"}

    def positions(self):
        self.calls.append("positions")
        return al.Positions(qty={"AAA": 100, "BBB": -50}, raw=[])

    def orders(self, *, status, after=None, until=None, limit=500, nested=False):
        assert status == "all"
        self.calls.append(("orders", after))
        return []

    def activities_fills(self, date):
        self.calls.append(("fills", date))
        return []


class FakeRun:
    def __init__(self, codes=None):
        self.codes = {"fetch_daily.py": 0, "fetch_cef_distributions.py": 0, **(codes or {})}
        self.cmds = []

    def __call__(self, cmd, timeout_s):
        self.cmds.append(cmd)
        name = Path(cmd[1]).name
        return self.codes[name], f"{name} output"


def write_panels(cef, *, nav=None, close=None):
    nav = nav or {"AAA": 10.00, "BBB": 20.00}
    close = close or {"AAA": 9.50, "BBB": 19.00}
    pd.DataFrame([{"date": pd.Timestamp(D), "nav": v, "ticker": t} for t, v in nav.items()]
                 ).to_parquet(cef / "cef_nav.parquet")
    pd.DataFrame([{"date": pd.Timestamp(D), "open": v, "high": v, "low": v, "close": v,
                   "volume": 1, "ticker": t, "grp": "x"} for t, v in close.items()]
                 ).to_parquet(cef / "cef_prices.parquet")
    pd.DataFrame({"ticker": UNIVERSE, "grp": "x"}).to_csv(cef / "cef_universe.csv", index=False)


@pytest.fixture
def env(tmp_path):
    state, cef = tmp_path / "state", tmp_path / "cef"
    state.mkdir()
    cef.mkdir()
    write_panels(cef)
    return state, cef


def make_ctx(env, client=None, run=None, cc=None):
    state, cef = env
    cc = {"AAA": 10.00, "BBB": 20.00} if cc is None else cc

    def cefconnect(t, day):
        assert day == D
        v = cc[t]
        if isinstance(v, Exception):
            raise v
        return v

    return co.Ctx(book="cef", client=client or FakeClient(), state_dir=state, cef_dir=cef,
                  repo=Path("/nonexistent"), book_path="ops/books/cef_discount_book.json",
                  deployed=list(DEPLOYED), run=run or FakeRun(), cefconnect_nav=cefconnect)


def status(env, day=D):
    return json.loads((env[0] / "data" / day.isoformat() / "status.json").read_text())


def log_lines(env):
    p = env[0] / "data.log"
    return p.read_text().splitlines() if p.exists() else []


# ------------------------------------------------------------------ the data day

@pytest.mark.parametrize("now, want", [
    (et(D, 16, 44), PREV),                 # before close + 45 min: the previous day
    (et(D, 16, 45), D),                    # exactly ready
    (et(D, 9, 0), PREV),                   # morning: yesterday
    (et(dt.date(2026, 10, 3), 12), dt.date(2026, 10, 2)),   # Saturday -> Friday
    (et(dt.date(2026, 10, 5), 10), dt.date(2026, 10, 2)),   # Monday morning -> Friday
])
def test_data_day(now, want):
    assert co.data_day(FakeClient(now=now))[0] == want


def test_calendars_disagree_raises_naming_both():
    # Alpaca calls Monday closed; nyse_calendar calls it trading.
    with pytest.raises(co.CalendarDisagreement, match=r"2026-09-28.*Alpaca.*closed.*nyse_calendar.*trading"):
        co.data_day(FakeClient(now=et(D, 9, 0), missing_days={PREV}))
    # And the other way: Alpaca trades a Saturday.
    sat = dt.date(2026, 10, 3)
    with pytest.raises(co.CalendarDisagreement, match="Alpaca /v2/calendar says trading"):
        co.data_day(FakeClient(now=et(sat, 12), extra_days={sat}))


# ------------------------------------------------------------------ idempotency

def test_complete_run_then_idle_with_no_further_network(env, capsys):
    client, run = FakeClient(), FakeRun()
    ctx = make_ctx(env, client, run)
    assert co.collect(ctx) == co.EXIT_OK
    s = status(env)
    assert all(s["steps"][k]["ok"] for k in co.STEPS), s
    assert all({"ok", "err", "detail", "at"} <= set(s["steps"][k]) for k in co.STEPS)
    assert log_lines(env) == [f"{D} DATA COMPLETE flags=0 gaps=0"]
    report = json.loads((env[0] / "data" / D.isoformat() / "report.json").read_text())
    assert report["complete"] and report["failed_steps"] == []

    client.calls.clear()
    n_cmds = len(run.cmds)
    capsys.readouterr()
    assert co.collect(make_ctx(env, client, run)) == co.EXIT_OK
    assert capsys.readouterr().out.strip() == f"IDLE {D} complete"
    assert client.calls == ["clock", "calendar"], "an idle run made more than the D lookup"
    assert len(run.cmds) == n_cmds
    assert len(log_lines(env)) == 1, "an idle run must not write a data.log line"


def test_failed_step_is_retried_and_completed_steps_are_not_redone(env):
    client, run = FakeClient(), FakeRun({"fetch_daily.py": 4})
    assert co.collect(make_ctx(env, client, run)) == co.EXIT_INCOMPLETE
    s = status(env)
    assert not s["steps"]["prices_nav"]["ok"] and "exited 4" in s["steps"]["prices_nav"]["err"]
    assert s["steps"]["nav_crosscheck"]["err"] == "waiting on prices_nav"
    assert s["steps"]["official_closes"]["ok"] and s["steps"]["account_snapshot"]["ok"]
    assert log_lines(env) == [f"{D} DATA INCOMPLETE prices_nav,nav_crosscheck,"
                              f"close_crosscheck flags=0 gaps=0"]

    client.calls.clear()
    run.codes["fetch_daily.py"] = 0
    n_before = len(run.cmds)
    assert co.collect(make_ctx(env, client, run)) == co.EXIT_OK
    names = [Path(c[1]).name for c in run.cmds[n_before:]]
    assert names == ["fetch_daily.py"], "distributions re-ran although it was ok"
    assert not [c for c in client.calls if c in ("account", "positions")
                or (isinstance(c, tuple) and c[0] == "prints")], client.calls
    assert log_lines(env)[-1] == f"{D} DATA COMPLETE flags=0 gaps=0"


def test_fetch_daily_is_run_with_the_sessions_flags(env):
    run = FakeRun()
    co.collect(make_ctx(env, run=run))
    cmd = next(c for c in run.cmds if c[1].endswith("fetch_daily.py"))
    assert "--nav-fallback" not in cmd      # CEFConnect stays independent (review 2026-09-29)
    assert cmd[2:] == ["--require-asof", D.isoformat(),
                       "--book", "ops/books/cef_discount_book.json"]


def test_timeout_is_a_failed_step(env):
    class Hang(FakeRun):
        def __call__(self, cmd, timeout_s):
            self.cmds.append(cmd)
            return (None, "hung") if cmd[1].endswith("fetch_daily.py") else (0, "")
    assert co.collect(make_ctx(env, run=Hang())) == co.EXIT_INCOMPLETE
    assert "timed out" in status(env)["steps"]["prices_nav"]["err"]


# ------------------------------------------------------------------ flags vs gaps

def test_disagreements_are_flags_and_never_fail_the_run(env):
    state, cef = env
    write_panels(cef, close={"AAA": 9.50, "BBB": 19.10})     # BBB panel close 19.10 vs print 19.00
    ctx = make_ctx(env, cc={"AAA": 10.02, "BBB": 20.00})      # AAA CEFConnect 10.02 vs panel 10.00
    assert co.collect(ctx) == co.EXIT_OK, "a flag must never fail the run (report only)"
    report = json.loads((state / "data" / D.isoformat() / "report.json").read_text())
    flags = {(f["step"], f["fund"]): f for f in report["flags"]}
    assert set(flags) == {("nav_crosscheck", "AAA"), ("close_crosscheck", "BBB")}
    f = flags[("nav_crosscheck", "AAA")]
    assert (f["value_a"], f["value_b"]) == (10.00, 10.02)
    assert {"fund", "source_a", "value_a", "source_b", "value_b"} <= set(f)
    assert log_lines(env)[-1] == f"{D} DATA COMPLETE flags=2 gaps=0"


def test_a_half_cent_is_not_a_flag(env):
    ctx = make_ctx(env, cc={"AAA": 10.004, "BBB": 20.00})
    co.collect(ctx)
    assert status(env)["steps"]["nav_crosscheck"]["detail"]["flags"] == []


def test_cefconnect_without_d_is_a_gap_not_a_flag(env):
    ctx = make_ctx(env, cc={"AAA": None, "BBB": 20.00})
    assert co.collect(ctx) == co.EXIT_OK
    d = status(env)["steps"]["nav_crosscheck"]
    assert d["ok"] and d["detail"]["flags"] == []
    assert [g["fund"] for g in d["detail"]["gaps"]] == ["AAA"]


def test_cefconnect_unreadable_fails_the_step_so_it_is_retried(env):
    ctx = make_ctx(env, cc={"AAA": co.CefConnectError("AAA: ConnectionError"), "BBB": 20.0})
    assert co.collect(ctx) == co.EXIT_INCOMPLETE
    d = status(env)["steps"]["nav_crosscheck"]
    assert not d["ok"] and d["detail"]["fetch_errors"] == ["AAA: ConnectionError"]


def test_a_nav_the_panel_took_from_cefconnect_is_not_counted_as_agreement(env):
    state, cef = env
    pd.DataFrame([{"date": D.isoformat(), "nav": 10.0, "ticker": "AAA", "source": "cefconnect",
                   "written_utc": "x"}]).to_csv(cef / "nav_fallback_log.csv", index=False)
    co.collect(make_ctx(env))
    gaps = status(env)["steps"]["nav_crosscheck"]["detail"]["gaps"]
    assert [g["fund"] for g in gaps] == ["AAA"] and "not an independent" in gaps[0]["reason"]


def test_missing_print_for_a_non_deployed_name_is_a_gap_only(env):
    client = FakeClient(prints={"AAA": 9.50, "BBB": 19.00})          # CCC has none
    assert co.collect(make_ctx(env, client)) == co.EXIT_OK
    d = status(env)["steps"]["official_closes"]
    assert d["ok"] and [g["fund"] for g in d["detail"]["gaps"]] == ["CCC"]


def test_a_transient_error_on_a_non_deployed_name_is_retried_not_a_gap(env):
    # review 2026-09-29: a 5xx used to become a permanent hole in the file
    client = FakeClient()
    real = client.closing_auction_prints

    def flaky(symbols, date, **kw):
        if symbols[0] == "CCC":
            raise al.AlpacaHTTPError("GET /v2/stocks/auctions -> HTTP 503", status=503)
        return real(symbols, date, **kw)
    client.closing_auction_prints = flaky
    assert co.collect(make_ctx(env, client)) == co.EXIT_INCOMPLETE
    d = status(env)["steps"]["official_closes"]
    assert not d["ok"] and d["detail"]["gaps"] == []
    assert "CCC" in d["detail"]["transient_errors"][0]
    client.closing_auction_prints = real                             # next slot: it answers
    co.collect(make_ctx(env, client))
    assert status(env)["steps"]["official_closes"]["ok"]


def test_missing_print_for_a_deployed_name_fails_the_step(env):
    client = FakeClient(prints={"AAA": 9.50, "CCC": 5.00})           # BBB is deployed
    assert co.collect(make_ctx(env, client)) == co.EXIT_INCOMPLETE
    d = status(env)["steps"]["official_closes"]
    assert not d["ok"] and "BBB" in d["err"]
    assert status(env)["steps"]["close_crosscheck"]["err"] == "waiting on official_closes"


def test_auction_is_not_queried_before_1645_et(env):
    # An early close (13:00) makes D ready at 13:45, but the print window ends 16:30.
    client = FakeClient(now=et(D, 14, 0))
    client.calendar = lambda s, e: [{"date": d, "open": "09:30",
                                     "close": "13:00" if d == D else "16:00", "raw": {}}
                                    for d in pd.date_range(s, e).date if is_trading_day(d)]
    assert co.collect(make_ctx(env, client)) == co.EXIT_INCOMPLETE
    assert "16:45" in status(env)["steps"]["official_closes"]["err"]
    assert not [c for c in client.calls if isinstance(c, tuple) and c[0] == "prints"]


# ------------------------------------------------------------------ the parquet

def test_official_close_file_is_deduplicated_and_not_refetched(env):
    state, cef = env
    pd.DataFrame([
        {"date": pd.Timestamp(PREV), "ticker": "AAA", "price": 9.0, "exchange": "N",
         "condition": "M", "t": "x", "fetched_at_utc": "old"},
        {"date": pd.Timestamp(D), "ticker": "AAA", "price": 9.50, "exchange": "N",
         "condition": "M", "t": "x", "fetched_at_utc": "old"},
    ]).to_parquet(cef / co.OFFICIAL_CLOSE_FILE)
    client = FakeClient()
    assert co.collect(make_ctx(env, client)) == co.EXIT_OK
    f = pd.read_parquet(cef / co.OFFICIAL_CLOSE_FILE)
    assert list(f.columns) == list(co.OFFICIAL_CLOSE_COLUMNS)
    assert not f.duplicated(["date", "ticker"]).any()
    assert len(f) == 4                                  # PREV AAA + D AAA, BBB, CCC
    queried = [c[1] for c in client.calls if isinstance(c, tuple) and c[0] == "prints"]
    assert queried == ["BBB", "CCC"], "AAA already had D's print and was queried again"
    assert f.loc[(f.ticker == "AAA") & (f.date == pd.Timestamp(D)), "fetched_at_utc"].item() == "old"


# ------------------------------------------------------------------ account

def test_account_snapshot_drops_raw_and_credential_like_fields(env):
    state, _ = env
    co.collect(make_ctx(env))
    text = (state / "data" / D.isoformat() / "account.json").read_text()
    assert "SHOULD-NOT-APPEAR" not in text
    acct = json.loads(text)
    assert "raw" not in acct["account"] and acct["account"]["equity"] == 100_500.0
    rows = (state / "equity.csv").read_text().splitlines()
    assert rows[0] == ",".join(co.EQUITY_COLUMNS)
    assert rows[1].startswith(f"{D},100500.0,100000.0,50000.0,80000.0,-29500.0,2,")


def test_account_snapshot_replaces_its_row(env):
    state, _ = env
    (state / "equity.csv").write_text(",".join(co.EQUITY_COLUMNS) + "\n"
                                      f"{PREV},1,1,1,1,1,0,x\n{D},9,9,9,9,9,9,old\n")
    co.collect(make_ctx(env))
    rows = (state / "equity.csv").read_text().splitlines()
    assert len(rows) == 3 and rows[1].startswith(str(PREV)) and "old" not in rows[2]


def test_orders_are_read_from_the_previous_trading_day(env):
    client = FakeClient(now=et(dt.date(2026, 10, 5), 21), next_open=et(dt.date(2026, 10, 6), 9, 30))
    co.collect(make_ctx(env, client))
    after = next(c[1] for c in client.calls if isinstance(c, tuple) and c[0] == "orders")
    assert after == et(dt.date(2026, 10, 2), 0)          # Monday's orders went in on Friday


def test_account_is_not_recorded_once_the_next_session_has_opened(env):
    client = FakeClient(now=et(NEXT, 10), is_open=True, next_open=et(dt.date(2026, 10, 1), 9, 30))
    assert co.collect(make_ctx(env, client)) == co.EXIT_INCOMPLETE
    # D is NEXT's previous day here (NEXT's own close is not yet past).
    s = status(env)
    assert not s["steps"]["account_snapshot"]["ok"]
    assert "account" not in client.calls


# ------------------------------------------------------------------ distributions

def test_distributions_need_the_universe_file(env):
    state, cef = env
    (cef / "cef_universe.csv").unlink()
    co.collect(make_ctx(env))
    s = status(env)["steps"]
    assert not s["distributions"]["ok"] and "cef_universe.csv" in s["distributions"]["err"]


# ------------------------------------------------------------------ main / exit codes

def test_unexpected_error_is_recorded_and_exits_20(env, capsys):
    state, _ = env

    class Broken(FakeClient):
        def calendar(self, start, end):
            raise RuntimeError("calendar exploded")

    rc = co.main(["--book", "cef"], env={"QUANTT_STATE_DIR": str(state)},
                 make_ctx=lambda book, sd: make_ctx(env, Broken()))
    assert rc == co.EXIT_UNEXPECTED == 20
    assert log_lines(env) == ["????-??-?? DATA ERROR RuntimeError: calendar exploded"]
    assert "Traceback" in capsys.readouterr().err


def test_unset_state_dir_exits_20():
    assert co.main(["--book", "cef"], env={}, make_ctx=lambda *a: pytest.fail("built")) == 20


def test_a_second_concurrent_run_is_refused(env):
    state, _ = env
    held = co._CollectorLock(state / "data" / ".collect.lock")
    assert held.acquire()
    try:
        rc = co.main(["--book", "cef"], env={"QUANTT_STATE_DIR": str(state)},
                     make_ctx=lambda *a: pytest.fail("a second run built a client"))
    finally:
        held.release()
    assert rc == co.EXIT_INCOMPLETE


# ------------------------------------------------------------------ read-only

def test_collect_package_never_names_the_transmit_method():
    pkg = Path(co.__file__).parent
    for f in pkg.glob("*.py"):
        assert "submit_order" not in f.read_text(), f"{f.name} names submit_order"
    assert not hasattr(FakeClient, "submit_order")
