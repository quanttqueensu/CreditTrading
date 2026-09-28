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

    def submit_order(self, symbol, qty, side, client_order_id):
        started = (self.state / D.isoformat() / "STARTED").exists()
        self.calls.append(("submit", client_order_id, started))
        what = self._submit.get(client_order_id, "ok")
        if isinstance(what, Exception):
            raise what
        o = {"id": f"id-{client_order_id}", "client_order_id": client_order_id,
             "symbol": symbol, "side": side, "qty": str(qty), "type": "market",
             "time_in_force": "cls", "status": "accepted"}
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
         closes=None, navs=None, halts=None, refresh_incomplete=None, **ck):
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
                   utcnow=lambda: dt.datetime(2026, 9, 29, 12, 30, tzinfo=dt.timezone.utc),
                   out=SimpleNamespace(write=out.append, flush=lambda: None))
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


def test_rejection_stops_batch(tmp_path):
    rej = OrderRejected("403", status=403, client_order_id="cef-20260929-BBB-1")
    c, deps, state, _, _ = make(tmp_path, submit={"cef-20260929-BBB-1": rej})
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_FAIL
    assert len(c.submits()) == 1


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


def test_refresh_timeout_is_the_time_left_to_the_cutoff(tmp_path):
    c, deps, state, seen, _ = make(tmp_path)          # clock 08:30, close 16:00
    rn.run_session(BOOK, SPEC, deps, preview=True)
    assert seen.timeouts == [pytest.approx((7 * 60 + 15) * 60)]     # 08:30 -> 15:45


def test_refresh_timeout_refuses_on_data(tmp_path):
    c, deps, state, seen, out = make(tmp_path, refresh_incomplete="timed out after 5s")
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert c.submits() == [] and seen.targets == []
    assert "did not complete: timed out" in "".join(out)


def test_refresh_not_run_after_cutoff(tmp_path):
    late = dt.datetime(2026, 9, 29, 16, 0, tzinfo=ET)
    c, deps, state, seen, _ = make(tmp_path, clock_ts=late)
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(BOOK, SPEC, deps) == rn.EXIT_REFUSED
    assert seen.refresh == [] and c.submits() == []


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
