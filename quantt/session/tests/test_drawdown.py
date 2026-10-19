"""The drawdown check (quantt/session/drawdown.py) and its place in the session, report mode.

THE RULE (team lead, 2026-10-19: HALVE/KILL in report mode), and what each test pins:

  * the series is `<state>/eod_equity.csv`, Alpaca's end-of-day portfolio
    history (the official daily P&L, team lead 2026-10-19), read BY HEADER NAME
    (`date`, `equity`); an empty `change_usd` on the first funded row and extra
    columns never break it; absent or unreadable is UNMEASURED naming the file,
    and there is never a fallback to `equity.csv` (snapshots, shown labelled);
  * the lines are the frozen spec's risk.halve_drawdown / risk.kill_drawdown,
    units-checked fractions, never literals: the tests read them from the live
    spec and build their equity paths relative to them;
  * HWM over rows dated on or before the as-of; no row after it is read; the
    newest row must be the as-of date;
  * `report` records the status and what `on` would do, in plan.json and the
    log, and changes nothing: the orders, the plan_sha and plan.json are a
    check-off session's, byte for byte, apart from `drawdown`;
  * `on` is not built: the book json cannot set it.

Hermetic: equity files under tmp_path, test_run's FakeClient for the broker. The
real-panel no-op proof reads `data/cef/` read-only and skips without it.
"""
import datetime as dt
import json
from pathlib import Path

import pytest

from quantt.session import drawdown as ddm
from quantt.session import records as rec
from quantt.session import run as rn
from quantt.session.tests.test_run import (ASOF, BOOK, D, EVE, LATE, SPEC, FakeClient, make,
                                           utc)

ET = rn.gt.ET
LIVE_SPEC = json.loads((rn.REPO / "ops/specs/cef_discount.frozen.json").read_text())
LV = ddm.levels(LIVE_SPEC)                      # the live lines, read as the session reads them
SPEC_DD = {**SPEC, "risk": {**SPEC["risk"],     # test_run's SPEC carrying the live lines
                            "halve_drawdown": LIVE_SPEC["risk"]["halve_drawdown"],
                            "kill_drawdown": LIVE_SPEC["risk"]["kill_drawdown"]}}
HWM = 104_000.0
# Equity at the as-of date for each case, placed between the live lines (never on one).
CASE_EQUITY = {
    ddm.OK: HWM * (1 - LV["halve"] / 2),
    ddm.HALVE: HWM * (1 - (LV["halve"] + LV["kill"]) / 2),
    ddm.KILL: HWM * (1 - LV["kill"] - 0.02),
}
EOD_HEADER = ("date", "equity", "change_usd", "profit_loss_pct")   # the collector's, plus an extra


def path_to(last_equity, asof=ASOF, n=6):
    """A business-day path of n rows ending on `asof`: 100k, up to HWM, then `last_equity`."""
    days, d = [], asof
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    days.reverse()
    eq = [100_000.0, 101_500.0, HWM, 103_000.0] + [102_000.0] * (n - 5) + [last_equity]
    return list(zip(days, eq[-n:] if len(eq) > n else eq))


def write_eod(state: Path, rows, header=EOD_HEADER, name=ddm.OFFICIAL_FILE) -> Path:
    """The collector's shape: `change_usd` empty on the first funded row, an extra column."""
    p = Path(state) / name
    out = [",".join(header)]
    prev = None
    for d, e in rows:
        vals = {"date": d.isoformat(), "equity": f"{e:.2f}",
                "change_usd": "" if prev is None else f"{e - prev:.2f}",
                "profit_loss_pct": "" if prev is None else f"{(e - prev) / prev:.6f}",
                "last_equity": "" if prev is None else f"{prev:.2f}", "cash": "1.00",
                "long_market_value": "2.00", "short_market_value": "-3.00",
                "n_positions": "13", "read_at_utc": "2026-09-28T21:00:00Z",
                "extra_a": "x"}
        out.append(",".join(vals[c] for c in header))
        prev = e
    p.write_text("\n".join(out) + "\n")
    return p


SNAP_HEADER = ("date", "equity", "last_equity", "cash", "long_market_value",
               "short_market_value", "n_positions", "read_at_utc")


# ------------------------------------------------------------- the measure

@pytest.mark.parametrize("case", [ddm.OK, ddm.HALVE, ddm.KILL])
def test_status_against_the_spec_lines(tmp_path, case):
    write_eod(tmp_path, path_to(CASE_EQUITY[case]))
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == case and r["would_on"] == ddm.WOULD_ON[case]
    got = r["reading"]
    assert got["hwm"] == HWM and got["last_date"] == ASOF
    assert got["drawdown"] == pytest.approx(1 - CASE_EQUITY[case] / HWM, abs=1e-8)
    assert r["levels"]["halve"] == LIVE_SPEC["risk"]["halve_drawdown"]
    assert r["levels"]["kill"] == LIVE_SPEC["risk"]["kill_drawdown"]
    assert r["acted"] is False and r["file"].endswith(ddm.OFFICIAL_FILE)


def test_the_lines_come_from_the_spec_not_a_literal(tmp_path):
    """Same series, two specs: the status follows the spec's numbers."""
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.OK]))
    dd = 1 - CASE_EQUITY[ddm.OK] / HWM
    tight = {"spec_id": "t", "risk": {"halve_drawdown": dd / 2, "kill_drawdown": dd * 2}}
    assert ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)["status"] == ddm.OK
    assert ddm.check(tmp_path, tight, ASOF, ddm.REPORT)["status"] == ddm.HALVE


@pytest.mark.parametrize("risk, why", [
    ({"kill_drawdown": 0.18}, "no risk.halve_drawdown"),
    ({"halve_drawdown": 0.12}, "no risk.kill_drawdown"),
    ({"halve_drawdown": 12, "kill_drawdown": 18}, "FRACTION"),          # the units trap
    ({"halve_drawdown": 0.12, "kill_drawdown": 1.0}, "FRACTION"),
    ({"halve_drawdown": 0.0, "kill_drawdown": 0.18}, "FRACTION"),
    ({"halve_drawdown": 0.18, "kill_drawdown": 0.12}, "is not below"),
    ({"halve_drawdown": True, "kill_drawdown": 0.18}, "not a finite number"),
    ({"halve_drawdown": "0.12", "kill_drawdown": 0.18}, "not a finite number"),
    ({"halve_drawdown": float("nan"), "kill_drawdown": 0.18}, "not a finite number"),
], ids=["no_halve", "no_kill", "percent", "one", "zero", "inverted", "bool", "string", "nan"])
def test_levels_are_units_checked_and_never_defaulted(tmp_path, risk, why):
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.KILL]))
    r = ddm.check(tmp_path, {"spec_id": "t", "risk": risk}, ASOF, ddm.REPORT)
    assert r["status"] == ddm.UNMEASURED and why in r["why"]
    assert r["would_on"] == ddm.WOULD_ON[ddm.UNMEASURED]


def test_a_spec_without_a_risk_block_is_unmeasured(tmp_path):
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.OK]))
    r = ddm.check(tmp_path, {"spec_id": "t"}, ASOF, ddm.REPORT)
    assert r["status"] == ddm.UNMEASURED and "no `risk` block" in r["why"]


# ------------------------------------------------------------- the series

def test_missing_eod_file_is_unmeasured_names_it_and_never_falls_back_to_equity_csv(tmp_path):
    """equity.csv holds a KILL-deep path; eod_equity.csv is absent. The status must
    be UNMEASURED naming eod_equity.csv, and the snapshot shown only, labelled."""
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.KILL]), header=SNAP_HEADER,
              name=ddm.SNAPSHOT_FILE)
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.UNMEASURED
    assert f"no {ddm.OFFICIAL_FILE} at {tmp_path / ddm.OFFICIAL_FILE}" in r["why"]
    assert "reading" not in r
    snap = r["snapshot"]
    assert snap["reading"]["status"] == ddm.KILL and "NOT the check's input" in snap["label"]
    text = "\n".join(ddm.lines(r))
    assert "UNMEASURED" in text and "KILL LINE BREACHED" not in text
    assert "NOT the check's input" in text


def test_empty_change_usd_and_extra_columns_are_never_read(tmp_path):
    """The contract (2026-10-19): `change_usd` is empty on the first funded row, and
    columns may follow it. A reordered header still reads by name."""
    rows = path_to(CASE_EQUITY[ddm.HALVE])
    p = write_eod(tmp_path, rows)
    first = p.read_text().splitlines()[1].split(",")
    assert first[EOD_HEADER.index("change_usd")] == ""                # the fixture is the shape
    assert ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)["status"] == ddm.HALVE
    write_eod(tmp_path, rows, header=("change_usd", "equity", "extra_a", "date", "cash"))
    assert ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)["status"] == ddm.HALVE


@pytest.mark.parametrize("text, why", [
    ("", "is empty"),
    ("date,change_usd\n2026-09-28,1.0\n", "no ['equity'] column"),
    ("day,equity\n2026-09-28,1.0\n", "no ['date'] column"),
    ("date,equity,equity\n2026-09-28,1,1\n", "repeats a column"),
    ("date,equity,change_usd\n2026-09-28,100000.00\n", "line 2 has 2 fields for 3"),
    ("date,equity,change_usd\n09/28/2026,100000.00,\n", "is not YYYY-MM-DD"),
    ("date,equity,change_usd\n2026-09-28,,\n", "equity '' is not a number"),
    ("date,equity,change_usd\n2026-09-28,abc,\n", "equity 'abc' is not a number"),
    ("date,equity,change_usd\n2026-09-28,nan,\n", "not a finite positive"),
    ("date,equity,change_usd\n2026-09-28,-5,\n", "not a finite positive"),
    ("date,equity,change_usd\n2026-09-28,100,\n2026-09-28,101,1\n", "two rows dated 2026-09-28"),
    ("date,equity,change_usd\n2026-09-29,100,\n", "no row dated on or before the as-of"),
], ids=["empty", "no_equity", "no_date", "dup_col", "short_row", "bad_date", "blank_equity",
        "text_equity", "nan_equity", "negative", "dup_date", "nothing_by_asof"])
def test_an_unreadable_eod_file_is_unmeasured_naming_the_file(tmp_path, text, why):
    (tmp_path / ddm.OFFICIAL_FILE).write_text(text)
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.UNMEASURED and why in r["why"], r["why"]
    assert ddm.OFFICIAL_FILE in r["why"]


def test_a_file_that_cannot_be_read_is_unmeasured_and_the_snapshot_still_shown(tmp_path):
    """An OS-level failure (here a directory where the file should be) is a named
    UNMEASURED, not a crash, for either file; one never hides the other."""
    (tmp_path / ddm.OFFICIAL_FILE).mkdir()
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.OK]), header=SNAP_HEADER, name=ddm.SNAPSHOT_FILE)
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.UNMEASURED and "could not be read: IsADirectoryError" in r["why"]
    assert r["snapshot"]["reading"]["status"] == ddm.OK
    (tmp_path / ddm.OFFICIAL_FILE).rmdir()
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.OK]))
    (tmp_path / ddm.SNAPSHOT_FILE).unlink()
    (tmp_path / ddm.SNAPSHOT_FILE).mkdir()
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.OK and "could not be read" in r["snapshot"]["unmeasured"]


def test_no_row_after_the_asof_is_read(tmp_path):
    """NO LOOKAHEAD: a crash and a new high after the as-of date change nothing."""
    rows = path_to(CASE_EQUITY[ddm.OK])
    later = [(ASOF + dt.timedelta(days=1), 50_000.0), (ASOF + dt.timedelta(days=2), 500_000.0)]
    write_eod(tmp_path, rows + later)
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.OK and r["reading"]["hwm"] == HWM
    assert r["reading"]["last_date"] == ASOF


def test_a_series_that_ends_before_the_asof_is_unmeasured_with_its_own_date(tmp_path):
    rows = path_to(CASE_EQUITY[ddm.HALVE], asof=ASOF - dt.timedelta(days=3))   # ends Friday
    write_eod(tmp_path, rows)
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.UNMEASURED and "not the as-of 2026-09-28" in r["why"]
    assert r["reading"]["last_date"] == dt.date(2026, 9, 25)          # labelled, not hidden
    assert r["would_on"] == ddm.WOULD_ON[ddm.UNMEASURED]
    assert "stale reading: " in ddm.lines(r)[0] and "(2026-09-25)" in ddm.lines(r)[0]


def test_a_line_crossed_earlier_is_reported_for_the_sticky_rule(tmp_path):
    rows = path_to(CASE_EQUITY[ddm.OK])
    deep = (rows[-2][0], CASE_EQUITY[ddm.HALVE])                       # crossed, then recovered
    write_eod(tmp_path, rows[:-2] + [deep, rows[-1]])
    r = ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT)
    assert r["status"] == ddm.OK
    assert r["reading"]["first_crossed"] == {"halve": deep[0], "kill": None}
    assert r["reading"]["worst_drawdown"] >= LV["halve"]
    assert f"the halve line was crossed on {deep[0]}" in ddm.lines(r)[0]


def test_the_log_line_names_the_series_the_lines_and_report_mode(tmp_path):
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.HALVE]))
    write_eod(tmp_path, path_to(CASE_EQUITY[ddm.OK]), header=SNAP_HEADER, name=ddm.SNAPSHOT_FILE)
    first, snap = ddm.lines(ddm.check(tmp_path, LIVE_SPEC, ASOF, ddm.REPORT))
    assert first.startswith("  DRAWDOWN (report): HALVE LINE BREACHED")
    assert ddm.OFFICIAL_FILE in first and "Report mode: no order changed." in first
    assert f"halve {100 * LV['halve']:.2f}%" in first and "`on` would: halve" in first
    assert snap.startswith("  DRAWDOWN snapshot (equity.csv, after-hours marks, NOT")


def test_check_refuses_a_mode_that_is_not_built(tmp_path):
    with pytest.raises(ValueError):
        ddm.check(tmp_path, LIVE_SPEC, ASOF, "on")


# ------------------------------------------------------------- in the session

def plan_bytes_without_drawdown(state, tmp_path):
    """plan.json with `drawdown` removed, re-serialised by the session's own writer."""
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    dd = plan.pop("drawdown", None)
    out = tmp_path / "plan_wo_dd.json"
    rec.write_json_atomic(out, plan)
    return out.read_bytes(), dd


def one_session(tmp_path, mode, eod_rows=None, spec=SPEC_DD, **kw):
    kw.setdefault("execution", LATE)
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, now_utc=utc(EVE), **kw)
    if eod_rows is not None:
        write_eod(state, eod_rows)
    deps.drawdown = mode
    code = rn.run_session(BOOK, spec, deps)
    return code, state, seen, "".join(out)


@pytest.mark.parametrize("case", [ddm.OK, ddm.HALVE, ddm.KILL, "missing"])
def test_report_mode_records_the_check_and_leaves_the_orders_and_plan_identical(tmp_path, case):
    """FAILS ON THE CODE BEFORE 2026-10-19: nothing recorded a drawdown, so a
    HALVE- or KILL-deep book decided exactly as a flat one with no trace. Now the
    check is in plan.json and the log, and everything else is the check-off
    session's, byte for byte: exit, orders, plan_sha, the sleeve call."""
    rows = None if case == "missing" else path_to(CASE_EQUITY[case])
    c0, s0, seen0, out0 = one_session(tmp_path / "off", None, rows)
    c1, s1, seen1, out1 = one_session(tmp_path / "rep", ddm.REPORT, rows)
    off_bytes, off_dd = plan_bytes_without_drawdown(s0, tmp_path / "off")
    rep_bytes, dd = plan_bytes_without_drawdown(s1, tmp_path / "rep")
    assert off_dd is None and "DRAWDOWN" not in out0
    assert c1 == c0 == rn.EXIT_PLANNED
    assert rep_bytes == off_bytes                      # plan.json, orders and plan_sha
    assert seen1.targets == seen0.targets              # the sleeve was asked the same thing
    assert dd is not None
    want = ddm.UNMEASURED if case == "missing" else case
    assert dd["status"] == want and dd["mode"] == ddm.REPORT and dd["acted"] is False
    assert dd["would_on"] == ddm.WOULD_ON[want]
    assert "DRAWDOWN (report)" in out1 and "Report mode: no order changed." in out1
    run_rec = json.loads(next((s1 / D.isoformat() / "runs").glob("*-run.json")).read_text())
    assert run_rec["drawdown"]["status"] == want


def test_check_off_reads_no_equity_file(tmp_path):
    """Absent key = today: a broken eod_equity.csv in the state dir is never opened."""
    c, deps, state, seen, out = make(tmp_path, clock_ts=EVE, now_utc=utc(EVE), execution=LATE)
    (state / ddm.OFFICIAL_FILE).write_text("garbage")
    assert deps.drawdown is None
    assert rn.run_session(BOOK, SPEC_DD, deps) == rn.EXIT_PLANNED
    plan = json.loads((state / D.isoformat() / "plan.json").read_text())
    assert "drawdown" not in plan and "DRAWDOWN" not in "".join(out)


def test_a_spec_without_the_lines_is_unmeasured_in_the_session_and_still_decides(tmp_path):
    code, state, _, out = one_session(tmp_path, ddm.REPORT, path_to(CASE_EQUITY[ddm.KILL]),
                                      spec=SPEC)
    assert code == rn.EXIT_PLANNED
    dd = json.loads((state / D.isoformat() / "plan.json").read_text())["drawdown"]
    assert dd["status"] == ddm.UNMEASURED and "risk.halve_drawdown" in dd["why"]


def test_a_bug_in_the_check_never_stops_a_report_mode_session(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("synthetic bug")
    monkeypatch.setattr(ddm, "check", boom)
    code, state, _, out = one_session(tmp_path, ddm.REPORT, path_to(CASE_EQUITY[ddm.OK]))
    assert code == rn.EXIT_PLANNED
    dd = json.loads((state / D.isoformat() / "plan.json").read_text())["drawdown"]
    assert dd["status"] == ddm.UNMEASURED and dd["why"] == "RuntimeError: synthetic bug"
    assert "DRAWDOWN (report): UNMEASURED: RuntimeError: synthetic bug" in out


def test_report_mode_in_a_cls_session_changes_no_order_sent(tmp_path):
    """The `cls` path decides and sends in one run: a KILL-deep book sends the same
    orders, in the same order, as with the check off."""
    sent = {}
    for sub, mode in (("off", None), ("rep", ddm.REPORT)):
        c, deps, state, seen, out = make(tmp_path / sub)
        write_eod(state, path_to(CASE_EQUITY[ddm.KILL], asof=ASOF))
        (state / "AUTO_ARMED").touch()
        deps.drawdown = mode
        assert rn.run_session(BOOK, SPEC_DD, deps) == rn.EXIT_SENT
        sent[sub] = c.submits()
    assert sent["rep"] == sent["off"] and sent["off"]


# ------------------------------------------------------------- the book json switch

@pytest.mark.parametrize("risk, want", [(None, None), ({"drawdown": "report"}, "report"),
                                        ({"drawdown": "report", "_drawdown_note": "x"},
                                         "report")])
def test_drawdown_setting_absent_is_off(tmp_path, risk, want):
    book = {"book_id": "b"} if risk is None else {"book_id": "b", "risk": risk}
    path = tmp_path / "book.json"
    path.write_text(json.dumps(book))
    assert rn.drawdown_for(rn.Book("cef", "cef", Path("x"), path)) == want


@pytest.mark.parametrize("risk", [{"drawdown": "on"}, {"drawdown": "off"}, {"drawdown": None},
                                  {}, "report"])
def test_a_drawdown_setting_that_is_not_built_raises(tmp_path, risk):
    path = tmp_path / "book.json"
    path.write_text(json.dumps({"book_id": "b", "risk": risk}))
    with pytest.raises(rn.SessionError):
        rn.drawdown_for(rn.Book("cef", "cef", Path("x"), path))


def test_the_released_book_runs_the_check_in_report_mode(monkeypatch):
    """The release setting (team lead 2026-10-19). Changing it is a reviewed
    book-json edit; this test moves with it. default_deps wires it (broker client
    faked: no key file is read)."""
    from quantt.broker import alpaca
    assert rn.drawdown_for(rn.BOOKS["cef"]) == ddm.REPORT
    monkeypatch.setattr(alpaca.AlpacaClient, "from_environment",
                        staticmethod(lambda name: object()))
    book = rn.BOOKS["cef"]
    deps = rn.default_deps(book, rn.load_spec(book.spec_path), {"QUANTT_ENV_FILE": "unused"})
    assert deps.drawdown == ddm.REPORT


# ------------------------------------------------------------- the real panel, report mode

def _real_panel_ready():
    from src.deploy.sleeves import cef_discount as cefmod
    return cefmod.PX_PATH.exists() and cefmod.NAV_PATH.exists()


@pytest.mark.skipif(not _real_panel_ready(), reason="real CEF panels absent (data/ is "
                                                     "gitignored); the synthetic tests still run")
@pytest.mark.parametrize("case", [ddm.OK, ddm.HALVE, ddm.KILL, "missing"])
def test_real_sleeve_on_the_real_panel_report_mode_is_byte_identical(tmp_path, case):
    """The no-op proof for the release setting: the live spec, the real sleeve and
    the real panels (read only), decided as of 2026-09-25 on a held book (half the
    day-one book, so the band has trades and holds), late-market with the
    re-fit, as prod runs. Check off and check in report mode give the same exit,
    orders and plan_sha, and plan.json byte-identical once `drawdown` is removed,
    with the official series at OK, HALVE-deep, KILL-deep and absent. The equity
    paths are test inputs relative to the live spec's lines, not data."""
    from src.deploy.sleeves import cef_discount as cefmod
    real = {f: f.read_bytes() for f in (cefmod.PX_PATH, cefmod.NAV_PATH)}
    spec = LIVE_SPEC
    p = rn.spec_params(spec)
    asof = dt.date(2026, 9, 25)
    eve = dt.datetime(2026, 9, 25, 22, 0, tzinfo=ET)
    uni = p["universe"]
    day1 = rn.sleeve_targets(spec, p["capital_usd"], asof, {}, p["capital_usd"], True)
    closes = {s: v[0] for s, v in rn.last_closes(cefmod.PX_PATH, asof, uni).items()}
    held = {t.instrument: int(0.5 * p["capital_usd"] * float(t.weight) / closes[t.instrument])
            for t in day1 if t.weight}
    held = {s: q for s, q in held.items() if q}
    rows = None if case == "missing" else path_to(CASE_EQUITY[case], asof=asof)

    def one(sub, mode):
        state = tmp_path / sub / "state"
        state.mkdir(parents=True)
        if rows is not None:
            write_eod(state, rows)
        client = FakeClient(state, positions=held, clock_ts=eve)
        client.long_mv = sum(q * closes[s] for s, q in held.items() if q > 0)
        client.short_mv = sum(q * closes[s] for s, q in held.items() if q < 0)
        client.maint = 0.5 * (client.long_mv - client.short_mv)     # fixture, not a measurement
        deps = rn.Deps(
            client=client, env={"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0"},
            refresh=lambda a, t: rn.RefreshResult(exit=0, tail="fixture"),
            closes=lambda a, u: rn.last_closes(cefmod.PX_PATH, a, u),
            navs=lambda a, u: rn.last_navs(cefmod.NAV_PATH, a, u),
            targets=lambda a, h, eq, op, **kw: rn.sleeve_targets(spec, p["capital_usd"], a, h,
                                                                 eq, op, **kw),
            halts=lambda: [], utcnow=lambda: eve.astimezone(dt.timezone.utc),
            out=type("O", (), {"write": lambda s, x: None, "flush": lambda s: None})(),
            execution={**LATE, "bp_shortfall": "scale"},
            drawdown=mode)
        code = rn.run_session(BOOK, spec, deps)
        day = state / "2026-09-28"
        return code, json.loads((day / "plan.json").read_text()), (day / "plan.json").read_bytes()

    c_off, off, off_bytes = one("off", None)
    c_rep, rep, _ = one("rep", ddm.REPORT)
    assert all(f.read_bytes() == b for f, b in real.items()), "a real panel changed"
    dd = rep.pop("drawdown")
    out = tmp_path / "rep_wo_dd.json"
    rec.write_json_atomic(out, rep)
    assert out.read_bytes() == off_bytes               # byte for byte, apart from `drawdown`
    assert c_rep == c_off == rn.EXIT_PLANNED and off["status"] == "decided"
    assert off["orders"] and off["plan_sha"] == rep["plan_sha"]
    assert any("band hold" in t["reason"] for t in off["targets"].values())
    assert dd["status"] == (ddm.UNMEASURED if case == "missing" else case)
