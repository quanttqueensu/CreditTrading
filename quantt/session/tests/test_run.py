"""run.py: the order of the session, and every way it must stop before or during transmit.

The fake client below records every call in one ordered list, together with
whether `<state>/<date>/STARTED` existed at the moment of each `submit_order`.
That is how "STARTED is written before the first order" is asserted rather than
assumed. Hermetic: no network (netguard), no key file (the client is a fake),
state under tmp_path, and the refresh/closes/sleeve are injected.
"""
import ast
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ops.schedule.nyse_calendar import is_trading_day
from quantt.broker.alpaca import AmbiguousSubmit, OrderRejected
from quantt.session import run as rn
from quantt.session.decide import Order
from src.deploy.sleeve import FLAT, LONG, SHORT, PositionTarget

ET = rn.gt.ET
D = dt.date(2026, 9, 29)          # Tuesday
ASOF = dt.date(2026, 9, 28)       # Monday
UNI = ["AAA", "BBB", "CCC"]
CLOSES = {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}

SPEC = {"spec_id": "test.v1", "capital_usd": 100_000.0,
        "allocation": {"type": "cef_discount"},
        "frozen": {"universe": UNI, "max_gross_stress": 1.8},
        "rebalance": {"min_trade_usd": 0.0},
        "risk": {"max_gross_exposure_usd": 260_000.0}}
BOOK = rn.Book("cef", "cef", Path("unused.json"), Path("unused_book.json"))


class FakeClient:
    ACCOUNT_NUMERIC = ()
    ACCOUNT_BOOL = ()

    def __init__(self, state, *, positions=None, closed=None, recent=None, open_=None,
                 submit=None, lookup=None, clock_ts=None, calendar=None, clock_seq=None,
                 assets=None):
        self.state = state
        self.calls = []
        self._pos = positions or {}
        self._closed = closed or []
        self._recent = recent or []
        self._open = open_ or []
        self._submit = submit or {}          # cid -> "ok" | exception instance | "noconfirm"
        self._lookup = lookup                # override for order_by_client_id
        self.accepted = {}
        self._clock = clock_ts or dt.datetime(2026, 9, 29, 8, 30, tzinfo=ET)
        self._clock_seq = list(clock_seq or [])    # successive reads; the last repeats
        self._calendar = calendar
        self._assets = assets or {}

    def clock(self):
        self.calls.append(("clock",))
        if self._clock_seq:
            ts = self._clock_seq.pop(0) if len(self._clock_seq) > 1 else self._clock_seq[0]
        else:
            ts = self._clock
        return {"timestamp": ts, "is_open": False, "next_open": ts, "next_close": ts}

    def calendar(self, start, end):
        self.calls.append(("calendar", start, end))
        if self._calendar is not None:
            return self._calendar
        out, d = [], start
        while d <= end:
            if is_trading_day(d):
                out.append({"date": d, "open": "09:30", "close": "16:00"})
            d += dt.timedelta(days=1)
        return out

    def account(self):
        self.calls.append(("account",))
        return {"id": "x", "status": "ACTIVE", "currency": "USD", "multiplier": "2",
                "equity": 100_000.0, "buying_power": 200_000.0,
                "regt_buying_power": getattr(self, "regt_bp", 200_000.0), "shorting_enabled": True,
                "trading_blocked": False, "account_blocked": False,
                "trade_suspended_by_user": False, "raw": {}}

    def positions(self):
        self.calls.append(("positions",))
        return SimpleNamespace(qty=dict(self._pos), raw=[])

    def orders(self, *, status, after=None, **kw):
        self.calls.append(("orders", status, after))
        return {"all": self._recent, "open": self._open, "closed": self._closed}[status]

    def asset(self, sym):
        self.calls.append(("asset", sym))
        a = {"symbol": sym, "shortable": True, "tradable": True,
             "borrow_status": "easy_to_borrow"}
        a.update(self._assets.get(sym, {}))
        return a

    def submit_order(self, symbol, qty, side, client_order_id, *, time_in_force):
        started = (self.state / D.isoformat() / "STARTED").exists()
        self.calls.append(("submit", client_order_id, started))
        what = self._submit.get(client_order_id, "ok")
        if isinstance(what, Exception):
            raise what
        self.tifs = getattr(self, "tifs", []) + [time_in_force]
        o = {"id": f"id-{client_order_id}", "client_order_id": client_order_id,
             "symbol": symbol, "side": side, "qty": str(qty), "type": "market",
             "time_in_force": time_in_force, "status": "accepted"}
        if what != "noconfirm":
            self.accepted[client_order_id] = o
        return o

    def order_by_client_id(self, cid):
        self.calls.append(("lookup", cid))
        if self._lookup is not None:
            return self._lookup(cid)
        return self.accepted.get(cid)

    def submits(self):
        return [c for c in self.calls if c[0] == "submit"]


def targets_book(asof, holdings, equity, opening):
    return [PositionTarget("AAA", LONG, weight=0.05, reason="z=-1"),
            PositionTarget("BBB", SHORT, weight=-0.05, reason="z=+1"),
            PositionTarget("CCC", FLAT, reason="flat")]


def make(tmp_path, env=None, *, client=None, refresh_exit=0, targets=targets_book,
         closes=None, navs=None, halts=None, refresh_incomplete=None, now_utc=None,
         execution=None, **ck):
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    c = client or FakeClient(state, **ck)
    seen = SimpleNamespace(refresh=[], targets=[], timeouts=[])
    out = []

    def refresh(asof, timeout_s):
        seen.refresh.append(asof)
        seen.timeouts.append(timeout_s)
        return rn.RefreshResult(exit=None if refresh_incomplete else refresh_exit,
                                tail="fetch output", incomplete=refresh_incomplete)

    def tg(*a):
        seen.targets.append(a)
        return targets(*a)

    e = {"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0"}
    e.update(env or {})
    e = {k: v for k, v in e.items() if v is not None}
    deps = rn.Deps(client=c, env=e, refresh=refresh,
                   closes=closes or (lambda asof, uni: {s: (CLOSES[s], ASOF) for s in uni}),
                   navs=navs or (lambda asof, uni: {s: asof for s in uni}),
                   targets=tg, halts=lambda: halts or [],
                   utcnow=lambda: now_utc or dt.datetime(2026, 9, 29, 12, 30, tzinfo=dt.timezone.utc),
                   out=SimpleNamespace(write=out.append, flush=lambda: None),
                   execution=execution or {"mode": "cls"})
    return c, deps, state, seen, out


def sha_of(tmp_path, **kw):
    """plan_sha as a preview computes it, in a separate state dir."""
    c, deps, state, _, _ = make(tmp_path / "preview", **kw)
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    return json.loads((state / D.isoformat() / "plan.json").read_text())["plan_sha"]


# ------------------------------------------------------------- dry / arming

@pytest.mark.parametrize("v", [None, "", "1", "false", "true"])
def test_dry_run_variants_never_submit(tmp_path, v):
    c, deps, state, _, _ = make(tmp_path, {"DRY_RUN": v})
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_DRY
    assert c.submits() == []
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    assert [r["gate"] for r in plan["refusals"]] == ["dry_run"]
    assert len(plan["orders"]) == 2
    assert not (state / D.isoformat() / "STARTED").exists()


def test_preview_never_submits_even_fully_armed(tmp_path):
    c, deps, state, _, out = make(tmp_path)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    assert c.submits() == []
    text = "".join(out)
    assert "plan_sha" in text and "cef-20260929-AAA-1" in text and "est_notional" in text


def test_not_armed_refuses(tmp_path):
    c, deps, _, _, _ = make(tmp_path)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []


def test_approve_sha_mismatch_refuses(tmp_path):
    c, deps, _, _, _ = make(tmp_path)
    assert rn.run_session(BOOK, SPEC, deps, approve="0" * 64) == rn.EXIT_REFUSED
    assert c.submits() == []


def test_approve_matching_sha_sends(tmp_path):
    sha = sha_of(tmp_path)
    c, deps, state, _, _ = make(tmp_path)
    assert rn.run_session(BOOK, SPEC, deps, approve=sha) == rn.EXIT_SENT
    assert [s[1] for s in c.submits()] == ["cef-20260929-BBB-1", "cef-20260929-AAA-1"]


def test_auto_armed_sends(tmp_path):
    c, deps, state, _, _ = make(tmp_path)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert len(c.submits()) == 2


def test_overnight_regt_buying_power_binds_not_intraday(tmp_path):
    """The book holds overnight: Reg T buying power, not the 4x intraday
    figure, must bind (review 2026-09-28). ~$10.2k needed vs $5k Reg T."""
    c, deps, state, _, _ = make(tmp_path)
    c.regt_bp = 5_000.0
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    assert "exposure" in [r["gate"] for r in plan["refusals"]]


# ------------------------------------------------------ record before send

def test_started_written_before_first_submit_and_holds_the_plan(tmp_path):
    c, deps, state, _, _ = make(tmp_path)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert all(started for _, _, started in c.submits())
    st = json.loads((state / D.isoformat() / "STARTED").read_text())
    assert st["client_order_ids"] == ["cef-20260929-BBB-1", "cef-20260929-AAA-1"]
    log = [json.loads(x) for x in (state / D.isoformat() / "orders.jsonl").read_text().splitlines()]
    assert [e["event"] for e in log] == ["submit", "accepted", "submit", "accepted",
                                         "confirm", "confirm"]


def test_second_run_same_day_refuses_and_keeps_the_sent_plan(tmp_path):
    c, deps, state, _, _ = make(tmp_path)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    plan_before = (state / D.isoformat() / "plan.json").read_text()
    c2, deps2, _, _, _ = make(tmp_path)          # fresh broker view: sees no orders
    assert rn.run_session(BOOK, SPEC, deps2) == rn.EXIT_REFUSED
    assert c2.submits() == []
    assert (state / D.isoformat() / "plan.json").read_text() == plan_before
    runs = sorted((state / D.isoformat() / "runs").iterdir())
    assert len(runs) >= 1


def test_broker_order_with_todays_prefix_refuses(tmp_path):
    o = {"client_order_id": "cef-20260929-AAA-1", "status": "filled",
         "time_in_force": "cls", "symbol": "AAA"}
    c, deps, state, _, _ = make(tmp_path, recent=[o])
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []


# ----------------------------------------------------------- transmit faults

def test_ambiguous_submit_stops_batch_and_looks_up(tmp_path):
    amb = AmbiguousSubmit("timeout", client_order_id="cef-20260929-BBB-1")
    c, deps, state, _, _ = make(tmp_path, submit={"cef-20260929-BBB-1": amb})
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert [s[1] for s in c.submits()] == ["cef-20260929-BBB-1"]      # AAA never sent
    assert ("lookup", "cef-20260929-BBB-1") in c.calls
    log = [json.loads(x)["event"] for x in
           (state / D.isoformat() / "orders.jsonl").read_text().splitlines()]
    assert log == ["submit", "ambiguous", "lookup"]


def test_rejection_skips_that_name_and_sends_the_rest(tmp_path):
    """Team lead 2026-09-28: a rejected order skips its symbol, the rest go,
    and the day is FAIL naming the rejection."""
    rej = OrderRejected("403", status=403, client_order_id="cef-20260929-BBB-1")
    c, deps, state, _, _ = make(tmp_path, submit={"cef-20260929-BBB-1": rej})
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert [s[1] for s in c.submits()] == ["cef-20260929-BBB-1", "cef-20260929-AAA-1"]
    runs = sorted((state / D.isoformat() / "runs").glob("*.json"))
    run_rec = json.loads(runs[-1].read_text())
    assert run_rec["rejected"] == ["cef-20260929-BBB-1"]
    assert run_rec["sent"] == ["cef-20260929-AAA-1"]


def test_every_order_rejected_sends_nothing_and_fails(tmp_path):
    """The `cls`-not-allowed case: every order rejected -> nothing sent, FAIL,
    and never a resend as `day`."""
    rej = lambda cid: OrderRejected("422 cls", status=422, client_order_id=cid)
    c, deps, state, _, out = make(tmp_path, submit={
        "cef-20260929-BBB-1": rej("cef-20260929-BBB-1"),
        "cef-20260929-AAA-1": rej("cef-20260929-AAA-1")})
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert len(c.submits()) == 2
    assert "NOTHING was sent" in "".join(out)


def test_confirm_miss_is_fail(tmp_path):
    c, deps, state, _, _ = make(tmp_path, submit={"cef-20260929-BBB-1": "noconfirm"})
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert len(c.submits()) == 2


# --------------------------------------------------------- data and dates

def test_refresh_uses_previous_trading_day_and_failure_refuses_without_deciding(tmp_path):
    c, deps, state, seen, _ = make(tmp_path, refresh_exit=4)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert seen.refresh == [ASOF]
    assert seen.targets == []
    assert c.submits() == []


def test_monday_asof_is_friday(tmp_path):
    mon = dt.datetime(2026, 9, 28, 8, 30, tzinfo=ET)
    c, deps, state, seen, _ = make(tmp_path, clock_ts=mon,
                                   closes=lambda a, u: {s: (CLOSES[s], a) for s in u})
    rn.run_session(BOOK, SPEC, deps, preview=True)
    assert seen.refresh == [dt.date(2026, 9, 25)]


def test_skip_refresh_does_not_refresh_but_requires_asof_closes(tmp_path):
    stale = lambda asof, uni: {s: (CLOSES[s], dt.date(2026, 9, 25)) for s in uni}
    c, deps, state, seen, _ = make(tmp_path, closes=stale)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, skip_refresh=True) == rn.EXIT_REFUSED
    assert seen.refresh == [] and c.submits() == []


def test_calendars_disagree_on_asof_fails(tmp_path):
    cal = [{"date": dt.date(2026, 9, 25), "open": "09:30", "close": "16:00"},
           {"date": D, "open": "09:30", "close": "16:00"}]      # Alpaca "skips" Monday
    c, deps, state, _, out = make(tmp_path, calendar=cal)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert c.submits() == []
    assert "disagrees" in "".join(out)


def test_state_dir_required(tmp_path):
    c, deps, _, _, _ = make(tmp_path, {"QUANTT_STATE_DIR": None})
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert c.calls == []


# --------------------------------------------------------- opening session

def test_opening_session_true_when_flat_and_never_filled(tmp_path):
    closed = [{"client_order_id": "probe", "filled_qty": "0"}]
    c, deps, _, seen, _ = make(tmp_path, closed=closed)
    rn.run_session(BOOK, SPEC, deps, preview=True)
    asof, holdings, equity, opening = seen.targets[0]
    assert (asof, holdings, equity, opening) == (ASOF, {}, 100_000.0, True)


def test_opening_session_false_after_any_fill(tmp_path):
    closed = [{"client_order_id": "x", "filled_qty": "3"}]
    c, deps, _, seen, _ = make(tmp_path, closed=closed)
    rn.run_session(BOOK, SPEC, deps, preview=True)
    assert seen.targets[0][3] is False


def test_opening_session_false_with_positions(tmp_path):
    c, deps, _, seen, _ = make(tmp_path, positions={"AAA": 10})
    rn.run_session(BOOK, SPEC, deps, preview=True)
    assert seen.targets[0][3] is False


def test_sleeve_targets_passes_extras_to_the_sleeve(monkeypatch, tmp_path):
    from src.deploy import registry
    from src.deploy.sleeves import cef_discount as cefmod
    got = {}

    class FakeSleeve:
        def target_positions(self, asof, ms):
            got.update(asof=asof, holdings=ms.holdings, extras=ms.extras)
            return []

    px = tmp_path / "px.parquet"
    pd.DataFrame({"date": pd.to_datetime(["2026-09-28", "2026-09-29"]),
                  "ticker": ["AAA", "AAA"], "close": [1.0, 2.0]}).to_parquet(px)
    monkeypatch.setattr(cefmod, "PX_PATH", px)
    monkeypatch.setattr(registry, "build_sleeve", lambda spec, cap: FakeSleeve())
    rn.sleeve_targets(SPEC, 100_000.0, ASOF, {"AAA": 5}, 123.0, False)
    assert got["extras"] == {"sleeve_nav": 123.0, "opening_session": False}
    assert got["holdings"] == {"AAA": 5} and got["asof"] == pd.Timestamp(ASOF)


# ------------------------------------------------------------- last_closes

def test_last_closes_ffill_per_name_dates_and_no_lookahead(tmp_path):
    rows = [("2026-09-25", "AAA", 9.0), ("2026-09-28", "AAA", 10.0),
            ("2026-09-25", "HYT", 5.0),                         # HYT lags a day
            ("2026-09-29", "AAA", 99.0)]                        # after as-of: must be ignored
    p = tmp_path / "px.parquet"
    pd.DataFrame(rows, columns=["date", "ticker", "close"]).assign(
        date=lambda d: pd.to_datetime(d["date"])).to_parquet(p)
    got = rn.last_closes(p, ASOF, ["AAA", "HYT", "ZZZ"])
    assert got == {"AAA": (10.0, ASOF), "HYT": (5.0, dt.date(2026, 9, 25)),
                   "ZZZ": (None, None)}


def test_last_closes_duplicate_rows_raise(tmp_path):
    p = tmp_path / "px.parquet"
    pd.DataFrame({"date": pd.to_datetime(["2026-09-28"] * 2), "ticker": ["AAA"] * 2,
                  "close": [1.0, 2.0]}).to_parquet(p)
    with pytest.raises(rn.SessionError, match="duplicate"):
        rn.last_closes(p, ASOF, ["AAA"])


# --------------------------------------------------------------- the edges

def test_refresh_subprocess_flags(monkeypatch, tmp_path):
    got = {}

    def fake_run(cmd, **kw):
        got["cmd"] = cmd
        return SimpleNamespace(returncode=4, stdout="a\n", stderr="b\n")

    monkeypatch.setattr(rn.subprocess, "run", fake_run)
    book = rn.BOOKS["cef"]
    r = rn.refresh_subprocess(ASOF, book, 600.0)
    assert r.exit == 4
    assert got["cmd"][1].endswith("scripts/cef/fetch_daily.py")
    assert got["cmd"][2:] == ["--require-asof", "2026-09-28", "--nav-fallback", "cefconnect",
                              "--book", "ops/books/cef_discount_book.json"]


def test_cli_unknown_subcommand_and_help():
    from quantt.session.__main__ import main
    assert main(["bogus"]) == 2
    assert main([]) == 2
    assert main(["--help"]) == 0


def test_run_py_is_the_only_caller_of_submit_order():
    root = Path(rn.__file__).resolve().parents[2]
    callers = []
    for top in ("quantt", "src", "ops", "scripts"):
        for f in (root / top).rglob("*.py"):
            if "tests" in f.parts:
                continue
            tree = ast.parse(f.read_text())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == "submit_order":
                    callers.append(str(f.relative_to(root)))
    assert sorted(set(callers)) == ["quantt/session/run.py"]


def test_dry_run_with_another_refusal_is_refused_not_dry(tmp_path):
    # A shadow session must surface a real gate failure, not hide it behind DRY.
    c, deps, state, _, _ = make(tmp_path, {"DRY_RUN": "1"},
                                halts=[{"reason": "manual", "scope": "global", "path": "x"}])
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []


# ------------------------------------------------ review 2026-09-28 fixes

def test_skip_refresh_close_asof_but_nav_stale_refuses(tmp_path):
    # The sleeve inner-joins price and NAV: a missing as-of NAV turns a name
    # FLAT. With --skip-refresh nothing else checks it.
    navs = lambda asof, uni: {**{s: asof for s in uni}, "BBB": dt.date(2026, 9, 25)}
    c, deps, state, seen, out = make(tmp_path, navs=navs)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, skip_refresh=True) == rn.EXIT_REFUSED
    assert c.submits() == [] and seen.targets == []
    assert "NAV not dated 2026-09-28" in "".join(out)


def test_clock_is_reread_at_the_gate_and_a_slow_refresh_past_cutoff_refuses(tmp_path):
    # First read 08:30; the refresh "takes" until 19:05. Gating on the first
    # read let these orders be queued into tomorrow's auction.
    seq = [dt.datetime(2026, 9, 29, 8, 30, tzinfo=ET),
           dt.datetime(2026, 9, 29, 19, 5, tzinfo=ET)]
    c, deps, state, _, out = make(tmp_path, clock_seq=seq)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    assert "[clock]" in "".join(out)


def test_refresh_timeout_is_capped_below_the_30_minute_slot(tmp_path):
    # 08:30 -> 15:45 is 7h15m left, but a hung fetch must not block the next
    # scheduled slot (launchd never starts a second instance of a running job).
    c, deps, state, seen, _ = make(tmp_path)          # clock 08:30, close 16:00
    rn.run_session(BOOK, SPEC, deps, preview=True)
    assert seen.timeouts == [pytest.approx(rn.REFRESH_TIMEOUT_CAP_S)]
    assert rn.REFRESH_TIMEOUT_CAP_S < 30 * 60


def test_refresh_timeout_is_the_time_left_when_that_is_shorter(tmp_path):
    c, deps, state, seen, _ = make(tmp_path, clock_ts=dt.datetime(2026, 9, 29, 15, 35, tzinfo=ET))
    rn.run_session(BOOK, SPEC, deps, preview=True)
    assert seen.timeouts == [pytest.approx(10 * 60)]                # 15:35 -> 15:45


def test_refresh_timeout_refuses_on_data(tmp_path):
    c, deps, state, seen, out = make(tmp_path, refresh_incomplete="timed out after 5s")
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == [] and seen.targets == []
    assert "did not complete: timed out" in "".join(out)


def test_after_the_cutoff_the_session_is_the_next_auction_and_the_clock_refuses(tmp_path):
    # 16:00 on the 29th: the next order could only join the 30th's auction, and
    # 15:50-19:00 Alpaca rejects cls [V] -- so gate 4 refuses, nothing is sent.
    late = dt.datetime(2026, 9, 29, 16, 0, tzinfo=ET)
    c, deps, state, seen, out = make(tmp_path, clock_ts=late)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []
    assert seen.refresh == [D]                      # as-of for the 30th is the 29th
    assert "[clock]" in "".join(out) and "2026-09-30" in "".join(out)


def test_transmit_stops_when_the_clock_crosses_the_cutoff_mid_batch(tmp_path):
    # reads: session start, gate, before order 1, before order 2 (past 15:45)
    seq = [dt.datetime(2026, 9, 29, 15, 40, tzinfo=ET)] * 3 + \
          [dt.datetime(2026, 9, 29, 15, 46, tzinfo=ET)]
    c, deps, state, _, out = make(tmp_path, clock_seq=seq)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert [s[1] for s in c.submits()] == ["cef-20260929-BBB-1"]
    log = [json.loads(x)["event"] for x in
           (state / D.isoformat() / "orders.jsonl").read_text().splitlines()]
    assert log == ["submit", "accepted", "cutoff", "confirm"]


def test_refresh_subprocess_timeout_is_recorded_not_raised(monkeypatch):
    import subprocess

    def fake_run(cmd, **kw):
        assert kw["timeout"] == 12.0
        raise subprocess.TimeoutExpired(cmd, 12.0, output=b"partial\n", stderr=None)

    monkeypatch.setattr(rn.subprocess, "run", fake_run)
    r = rn.refresh_subprocess(ASOF, rn.BOOKS["cef"], 12.0)
    assert r.exit is None and "timed out after 12s" in r.incomplete and "partial" in r.tail


def test_hard_to_borrow_short_open_is_warned_in_the_preview(tmp_path):
    c, deps, state, _, out = make(tmp_path, assets={"BBB": {"borrow_status": "hard_to_borrow"}})
    assert rn.run_session(BOOK, SPEC, deps, preview=True) == rn.EXIT_PREVIEW
    text = "".join(out)
    assert "WARNING cef-20260929-BBB-1 opens/increases a short in BBB" in text
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    assert len(plan["borrow_warnings"]) == 1


def test_last_navs_dates_ignore_nan_and_lookahead(tmp_path):
    rows = [("2026-09-25", "AAA", 9.0), ("2026-09-28", "AAA", 10.0),
            ("2026-09-25", "PDI", 8.0), ("2026-09-28", "PDI", float("nan")),
            ("2026-09-29", "AAA", 11.0)]
    p = tmp_path / "nav.parquet"
    pd.DataFrame(rows, columns=["date", "ticker", "nav"]).assign(
        date=lambda d: pd.to_datetime(d["date"])).to_parquet(p)
    assert rn.last_navs(p, ASOF, ["AAA", "PDI", "ZZZ"]) == {
        "AAA": ASOF, "PDI": dt.date(2026, 9, 25), "ZZZ": None}


def test_last_navs_duplicate_rows_raise(tmp_path):
    p = tmp_path / "nav.parquet"
    pd.DataFrame({"date": pd.to_datetime(["2026-09-28"] * 2), "ticker": ["AAA"] * 2,
                  "nav": [1.0, 2.0]}).to_parquet(p)
    with pytest.raises(rn.SessionError, match="duplicate"):
        rn.last_navs(p, ASOF, ["AAA"])


# ------------------------------------------- evening decision (team lead 2026-09-29)

EVE = dt.datetime(2026, 9, 28, 22, 0, tzinfo=ET)          # Monday evening, for Tuesday


def test_evening_run_trades_the_next_auction_on_the_evenings_pair(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert seen.refresh == [ASOF]                         # decided on the 28th's close+NAV
    cids = [x[1] for x in c.submits()]
    assert cids and all(cid.startswith("cef-20260929-") for cid in cids)
    assert all(x[2] for x in c.submits())                 # STARTED before every order
    assert (state / D.isoformat() / "STARTED").exists()


def test_evening_and_morning_runs_make_the_same_plan(tmp_path):
    eve = sha_of(tmp_path / "e", clock_ts=EVE)
    morn = sha_of(tmp_path / "m")
    assert eve == morn


def test_orders_since_the_night_before_the_asof_are_read(tmp_path):
    # a Friday-evening set for Monday must be visible to a Monday-morning run
    mon = dt.datetime(2026, 10, 5, 8, 30, tzinfo=ET)
    c, deps, state, _, _ = make(tmp_path, clock_ts=mon,
                                closes=lambda asof, uni: {s: (CLOSES[s], asof) for s in uni})
    rn.run_session(BOOK, SPEC, deps, preview=True)
    afters = [x[2] for x in c.calls if x[0] == "orders" and x[1] == "all"]
    assert afters == [dt.datetime(2026, 10, 1, 0, 0, tzinfo=ET)]   # Thu 00:00 before Fri as-of


def test_transmit_stops_when_the_clock_leaves_the_evening_window(tmp_path):
    # start and gate at 22:00 on the 28th; before order 2 the clock reads 19:00
    # on the 28th (impossible in life, but the window is what is checked).
    seq = [EVE] * 3 + [dt.datetime(2026, 9, 28, 19, 0, tzinfo=ET)]
    c, deps, state, _, out = make(tmp_path, clock_seq=seq)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert len(c.submits()) == 1
    assert "outside the send window" in "".join(out)


@pytest.mark.parametrize("now,want", [
    (dt.datetime(2026, 9, 29, 8, 30, tzinfo=ET), dt.date(2026, 9, 29)),    # morning: today
    (dt.datetime(2026, 9, 29, 15, 44, tzinfo=ET), dt.date(2026, 9, 29)),
    (dt.datetime(2026, 9, 29, 15, 45, tzinfo=ET), dt.date(2026, 9, 30)),   # past cutoff
    (dt.datetime(2026, 9, 28, 22, 0, tzinfo=ET), dt.date(2026, 9, 29)),    # evening
    (dt.datetime(2026, 9, 29, 0, 30, tzinfo=ET), dt.date(2026, 9, 29)),    # after midnight
    (dt.datetime(2026, 10, 2, 22, 0, tzinfo=ET), dt.date(2026, 10, 5)),    # Fri -> Mon
    (dt.datetime(2026, 10, 3, 0, 30, tzinfo=ET), dt.date(2026, 10, 5)),    # Sat 00:30 -> Mon
    (dt.datetime(2026, 11, 25, 22, 0, tzinfo=ET), dt.date(2026, 11, 27)),  # Thanksgiving skipped
])
def test_session_for(now, want):
    cal = FakeClient(Path("."), clock_ts=now).calendar(now.date() - dt.timedelta(days=14),
                                                       now.date() + dt.timedelta(days=14))
    assert rn.session_for(now, cal) == want


def test_session_for_refuses_when_the_calendars_disagree():
    now = dt.datetime(2026, 9, 28, 22, 0, tzinfo=ET)
    cal = [{"date": dt.date(2026, 9, 28), "open": "09:30", "close": "16:00"},
           {"date": dt.date(2026, 9, 30), "open": "09:30", "close": "16:00"}]   # 29th missing
    with pytest.raises(rn.SessionError, match="disagrees"):
        rn.session_for(now, cal)


# ------------------------------------------------------------- --scheduled

def utc(et):
    return et.astimezone(dt.timezone.utc)


def test_scheduled_outside_the_windows_idles_without_calling_alpaca(tmp_path):
    for t in (dt.datetime(2026, 9, 29, 17, 0, tzinfo=ET), dt.datetime(2026, 9, 29, 3, 0, tzinfo=ET)):
        c, deps, state, _, out = make(tmp_path, now_utc=utc(t), clock_ts=t)
        assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_IDLE
        assert c.calls == []
        assert not (state / D.isoformat()).exists()


def test_scheduled_evening_sends_then_later_slots_idle(tmp_path):
    c, deps, state, _, out = make(tmp_path, now_utc=utc(EVE), clock_ts=EVE)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_SENT
    assert (state / D.isoformat() / "DONE").exists()
    n = len(c.submits())
    for t in (dt.datetime(2026, 9, 28, 22, 30, tzinfo=ET), dt.datetime(2026, 9, 29, 8, 0, tzinfo=ET)):
        deps.utcnow = lambda t=t: utc(t)
        c._clock = t
        assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_IDLE
    assert len(c.submits()) == n


def test_scheduled_refusal_leaves_the_next_slot_free_to_retry(tmp_path):
    c, deps, state, seen, _ = make(tmp_path, now_utc=utc(EVE), clock_ts=EVE, refresh_exit=4)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_REFUSED
    day = state / D.isoformat()
    assert not (day / "DONE").exists() and not (day / "DRY_DONE").exists()
    assert rn.done_reason(day, deps.env) is None


def test_scheduled_dry_run_is_done_only_while_dry(tmp_path):
    c, deps, state, _, _ = make(tmp_path, {"DRY_RUN": "1"}, now_utc=utc(EVE), clock_ts=EVE)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_DRY
    day = state / D.isoformat()
    assert (day / "DRY_DONE").exists()
    assert rn.done_reason(day, {"DRY_RUN": "1"}) is not None
    # armed later the same night: the next slot must trade, not idle behind the dry run
    assert rn.done_reason(day, {"DRY_RUN": "0"}) is None
    later = dt.datetime(2026, 9, 28, 22, 30, tzinfo=ET)
    deps.utcnow = lambda: utc(later)
    c._clock = later
    deps.env["DRY_RUN"] = "0"
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_SENT


@pytest.mark.parametrize("now,slot", [
    (dt.datetime(2026, 9, 28, 21, 59, tzinfo=ET), None),
    (dt.datetime(2026, 9, 28, 22, 0, tzinfo=ET), "evening"),
    (dt.datetime(2026, 9, 29, 0, 59, tzinfo=ET), "evening"),
    (dt.datetime(2026, 9, 29, 1, 0, tzinfo=ET), None),
    (dt.datetime(2026, 9, 29, 5, 59, tzinfo=ET), None),
    (dt.datetime(2026, 9, 29, 6, 0, tzinfo=ET), "morning"),
    (dt.datetime(2026, 9, 29, 15, 14, tzinfo=ET), "morning"),
    (dt.datetime(2026, 9, 29, 15, 15, tzinfo=ET), None),
])
def test_scheduled_slot_edges(now, slot):
    assert rn.scheduled_slot(now, D, ASOF) == slot


def test_scheduled_friday_evening_slots_run_past_midnight_into_saturday():
    mon, fri = dt.date(2026, 10, 5), dt.date(2026, 10, 2)
    assert rn.scheduled_slot(dt.datetime(2026, 10, 3, 0, 30, tzinfo=ET), mon, fri) == "evening"
    assert rn.scheduled_slot(dt.datetime(2026, 10, 3, 22, 0, tzinfo=ET), mon, fri) is None
    assert rn.scheduled_slot(dt.datetime(2026, 10, 5, 9, 0, tzinfo=ET), mon, fri) == "morning"


def test_scheduled_run_writes_no_record_when_idle(tmp_path):
    t = dt.datetime(2026, 9, 29, 16, 30, tzinfo=ET)       # after the cutoff, before evening
    c, deps, state, _, out = make(tmp_path, now_utc=utc(t), clock_ts=t)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_IDLE
    assert not any(state.rglob("*.json"))


# ------------------------------------ paper late-market execution (team lead 2026-09-29)

LATE = {"mode": "late_market", "window_minutes_before_close": (8, 2)}
SEND = dt.datetime(2026, 9, 29, 15, 53, tzinfo=ET)


def decided(tmp_path, **kw):
    """Decide D's plan in the evening; return (client, deps, state, plan)."""
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, execution=LATE, **kw)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_PLANNED
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    return c, deps, state, plan


def to_send_time(c, deps, t=SEND):
    c._clock = t
    deps.utcnow = lambda: t.astimezone(dt.timezone.utc)


def test_late_decide_saves_a_decided_plan_of_day_orders_and_sends_nothing(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    assert c.submits() == []
    assert plan["status"] == "decided" and plan["execution"] == "late_market"
    assert {o["time_in_force"] for o in plan["orders"]} == {"day"}
    assert plan["send_window"][0].startswith("2026-09-29 15:52") or \
        plan["send_window"][0].startswith("2026-09-29T15:52")
    assert not (state / D.isoformat() / "STARTED").exists()


def test_late_decide_with_stale_data_is_refused_not_decided(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, execution=LATE, refresh_exit=4)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    assert plan["status"] == "refused" and c.submits() == []


def test_late_send_sends_the_saved_plan_as_day_orders_when_auto_armed(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    to_send_time(c, deps)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert [x[1] for x in c.submits()] == [o["client_order_id"] for o in plan["orders"]]
    assert set(c.tifs) == {"day"}
    assert all(x[2] for x in c.submits())                 # STARTED before every order


def test_late_send_never_redecides(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    to_send_time(c, deps)
    calls = []
    deps.targets = lambda *a: calls.append(a) or []
    deps.refresh = lambda *a: calls.append(a)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT
    assert calls == []


def test_late_send_needs_the_approval_of_that_exact_plan(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    to_send_time(c, deps)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED          # no approval
    assert c.submits() == []
    day = state / D.isoformat()
    (day / "APPROVED").write_text(json.dumps({"plan_sha": "0" * 64}))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED          # someone else's plan
    (day / "APPROVED").write_text(json.dumps({"plan_sha": plan["plan_sha"]}))
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_SENT


def test_late_send_refuses_when_positions_moved_since_the_plan(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    to_send_time(c, deps)
    c._pos = {"AAA": 7}
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == []


def test_late_send_refuses_a_tampered_plan(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    path = state / D.isoformat() / "plan.json"
    plan["orders"][0]["qty"] += 1
    path.write_text(json.dumps(plan))
    to_send_time(c, deps)
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert c.submits() == []


def test_late_send_with_no_decided_plan_sends_nothing(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=SEND, execution=LATE)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert c.submits() == [] and "nothing was decided" in "".join(out)


def test_late_send_dry_run_never_sends(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    to_send_time(c, deps)
    deps.env["DRY_RUN"] = "1"
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_DRY
    assert c.submits() == []


def test_late_send_stops_when_the_clock_leaves_the_window_mid_batch(tmp_path):
    c, deps, state, plan = decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    deps.utcnow = lambda: SEND.astimezone(dt.timezone.utc)
    # start, gate, before order 1 inside; before order 2 at 15:58
    c._clock_seq = [SEND] * 3 + [dt.datetime(2026, 9, 29, 15, 58, tzinfo=ET)]
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert len(c.submits()) == 1


@pytest.mark.parametrize("t,want", [
    (dt.datetime(2026, 9, 29, 15, 51, 59, tzinfo=ET), ["clock"]),
    (dt.datetime(2026, 9, 29, 15, 52, tzinfo=ET), []),
    (dt.datetime(2026, 9, 29, 15, 57, 59, tzinfo=ET), []),
])
def test_late_clock_gate_edges(t, want):
    w = rn.gt.late_window_et(D, "16:00", (8, 2))
    cal = [{"date": D, "open": "09:30", "close": "16:00"}]
    assert [r.gate for r in rn.gt.gate_late_clock(t, D, cal, True, w)] == want


def test_late_window_follows_an_early_close():
    lo, hi = rn.gt.late_window_et(dt.date(2026, 11, 27), "13:00", (8, 2))
    assert (lo.hour, lo.minute, hi.hour, hi.minute) == (12, 52, 12, 58)


def test_late_session_date_rolls_at_the_window_end_not_1545(tmp_path):
    cut = lambda d, close: rn.gt.late_window_et(d, close, (8, 2))[1]
    cal = FakeClient(Path(".")).calendar(D - dt.timedelta(days=14), D + dt.timedelta(days=14))
    assert rn.session_for(dt.datetime(2026, 9, 29, 15, 55, tzinfo=ET), cal, cut) == D
    assert rn.session_for(dt.datetime(2026, 9, 29, 15, 58, tzinfo=ET), cal, cut) == \
        dt.date(2026, 9, 30)


def test_late_scheduled_decides_once_then_sends_once(tmp_path):
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, execution=LATE,
                                     now_utc=utc(EVE))
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_PLANNED
    later = dt.datetime(2026, 9, 29, 8, 0, tzinfo=ET)          # morning slot: already decided
    to_send_time(c, deps, later)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_IDLE
    to_send_time(c, deps, SEND)
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_SENT
    n = len(c.submits())
    to_send_time(c, deps, dt.datetime(2026, 9, 29, 15, 55, tzinfo=ET))
    assert rn.run_session(BOOK, SPEC, deps, scheduled=True) == rn.EXIT_IDLE
    assert len(c.submits()) == n


def test_approve_writes_approved_only_for_the_decided_plan(tmp_path, monkeypatch, capsys):
    c, deps, state, plan = decided(tmp_path)
    monkeypatch.setenv("QUANTT_STATE_DIR", str(state))
    args = ["--book", "cef", "--date", D.isoformat(), "--sha"]
    assert rn.approve_main(args + ["f" * 64]) == rn.EXIT_REFUSED
    assert not (state / D.isoformat() / "APPROVED").exists()
    assert rn.approve_main(args + [plan["plan_sha"]]) == 0
    assert rn.approval_for(state / D.isoformat()) == plan["plan_sha"]
    (state / D.isoformat() / "STARTED").write_text("{}")
    assert rn.approve_main(args + [plan["plan_sha"]]) == rn.EXIT_REFUSED


def test_execution_absent_is_cls_and_unknown_raises(tmp_path):
    b = tmp_path / "book.json"
    b.write_text(json.dumps({"book_id": "x"}))
    book = rn.Book("cef", "cef", Path("s"), b)
    assert rn.execution_for(book) == {"mode": "cls"}
    b.write_text(json.dumps({"execution": {"mode": "late_market",
                                           "window_minutes_before_close": [8, 2]}}))
    assert rn.execution_for(book)["mode"] == "late_market"
    b.write_text(json.dumps({"execution": {"mode": "twap"}}))
    with pytest.raises(rn.SessionError):
        rn.execution_for(book)
