"""The uptime measurement must not be able to flatter itself.

WHY THESE TESTS EXIST, AND WHY THEY ARE NOT "RUN IT AND ASSERT GREEN"
---------------------------------------------------------------------
`ops/session_uptime.py` is the named reproducer for every uptime figure this
repo quotes. A parser that silently matched nothing would print `0 of 0`, or
`armed 0`, and look like a clean measurement — and the lesson inherited from
`ops/tests/test_promote_gate.py` is that

    "an exclusion that matches nothing is indistinguishable, from the outside,
     from one that matched and found nothing wrong"

So every test below WRITES a log tree whose content is copied from the real
logs, breaks or varies exactly one thing, and asserts the tool names it. Only
`test_the_live_trees_reproduce` reads the real trees, and it asserts invariants
rather than counts, because a count written into a test is a count that goes
stale — this repo has been wrong about a number in a document twice inside
twenty-four hours.

THE FOUR FAILURE SHAPES THAT ARE EACH A REAL SESSION
---------------------------------------------------
  * blocked on the broker port (2026-08-03 .. 2026-08-28, twenty in a row)
  * armed, then `book run FAILED rc=1`  (2026-09-08)
  * armed 17h after launch, the next morning (2026-09-10)
  * two blockers in one reason string (2026-08-07: data AND broker)

and two shapes that are about the MEASUREMENT rather than the session:

  * a session date present only in the prod tree — reading one tree undercounts
  * a log that ends before it says whether it armed — indeterminate, never
    "not armed", and it must make the whole rate refuse to stand

Nothing here touches git, the broker, or any file outside tmp_path.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from ops import session_uptime as su
from ops.schedule import nyse_calendar

# ---------------------------------------------------------------- fixtures ---
# Verbatim shapes from ops/schedule/logs. If the wrapper's wording changes these
# stay as they are: the tool has to keep reading the logs already on disk.
HEAD = "[{d} 17:15:05] launchd start (job=cef)\n{d} TRADING\n"
PREFLIGHT_OK = (
    "[preflight] [PASS] halt: no active halt\n"
    "[preflight] [PASS] broker: TWS/Gateway listening on 127.0.0.1:4002\n")
BOOK_LINE = ("\n[run_book] BOOK asof {d}  NAV $504,030.09  PnL $4,030.09  "
             "turnover $87,003  gross $820,199\n")

BROKER_REASON = ("[FAIL] broker: nothing listening on 127.0.0.1:{port} "
                 "(ConnectionRefusedError). TWS restarts daily and needs a "
                 "login — start it, or let the session run collect-only.")


def armed_log(d: str, *, armed_at: str | None = None, book_run: str = "ok",
              done: str = "ok") -> str:
    armed_at = armed_at or f"{d} 17:15:35"
    return (HEAD.format(d=d) + PREFLIGHT_OK
            + f"[{armed_at}] ARMED: EXECUTION=ibkr books-root=ops/books/cef_live"
              f" asof={d}\n"
            + "[ibkr] arm: ARMED\n"
            + BOOK_LINE.format(d=d)
            + f"[{armed_at}] book run {book_run}\n"
            + f"[{armed_at}] done status={done}\n")


def blocked_log(d: str, reason: str, done: str = "ok_not_armed") -> str:
    return (HEAD.format(d=d)
            + f"[preflight] {reason.split(' ', 1)[0]} broker: ...\n"
            + f"[{d} 19:01:50] NOT ARMED -> dry run in "
              f"ops/books/_dryruns/cef. Reason: {reason}\n"
            + f"[{d} 19:01:51] done status={done}\n")


def closed_log(d: str, why: str = "Labor Day") -> str:
    return (f"[{d} 17:15:05] launchd start (job=cef)\n"
            f"{d} CLOSED ({why})\n"
            f"[{d} 17:15:06] not an NYSE trading day - skip\n")


@pytest.fixture
def tree(tmp_path):
    """A factory for throwaway log trees. `tree("dev", {date: text})`."""
    def make(name, logs, job="cef"):
        root = tmp_path / name
        d = root / su.LOG_SUBDIR
        d.mkdir(parents=True, exist_ok=True)
        for date, text in logs.items():
            (d / f"{job}_{date}.log").write_text(text)
        return root
    return make


def _m(trees, **kw):
    """measure() with the window pinned, so `today` can never move the answer."""
    kw.setdefault("today", dt.date(2026, 9, 11))
    kw.setdefault("through", dt.date(2026, 9, 10))
    return su.measure(trees=trees, **kw)


# ------------------------------------------------------------------ parsing --
def test_an_armed_session_is_armed_and_clean(tree):
    t = tree("dev", {"2026-09-09": armed_log("2026-09-09")})
    m = _m([t], since=dt.date(2026, 9, 9), through=dt.date(2026, 9, 9))
    (s,) = m["sessions"]
    assert s["outcome"] == "armed" and s["clean"] is True
    assert s["armed_at"] == "2026-09-09 17:15:35"
    assert s["asof"] == "2026-09-09"
    assert m["n_armed"] == 1 and m["n_clean"] == 1 and m["n_missed"] == 0


def test_armed_then_book_run_failed_is_not_clean(tree):
    """2026-09-08: the arm line fired, then run_book raised on a ledger manifest
    mismatch. The loose count says armed; the count the target keys on must not."""
    t = tree("dev", {"2026-09-08": armed_log("2026-09-08", book_run="FAILED rc=1",
                                             done="failed")})
    m = _m([t], since=dt.date(2026, 9, 8), through=dt.date(2026, 9, 8))
    (s,) = m["sessions"]
    assert s["outcome"] == "armed"
    assert s["clean"] is False
    assert "book run FAILED rc=1" in s["caveat"]
    assert "done status=failed" in s["caveat"]
    assert m["n_armed"] == 1 and m["n_clean"] == 0


def test_arming_the_next_morning_is_a_late_arm(tree):
    """2026-09-10: launched 17:15, armed 10:38 the following day. `done
    status=ok`, so nothing but the timestamp distinguishes it from a good run."""
    t = tree("dev", {"2026-09-10": armed_log("2026-09-10",
                                             armed_at="2026-09-11 10:38:30")})
    m = _m([t], since=dt.date(2026, 9, 10), through=dt.date(2026, 9, 10))
    (s,) = m["sessions"]
    assert s["outcome"] == "armed" and s["late_arm"] is True
    assert s["clean"] is False
    assert "a day after the session date" in s["caveat"]


def test_a_blocked_session_names_the_code_and_the_port(tree):
    """The port IS the fault signature: 7497 in August, 4002 in September. A
    blocker row that loses it cannot tell you the config moved."""
    t = tree("dev", {"2026-08-03": blocked_log("2026-08-03",
                                               BROKER_REASON.format(port=7497))})
    m = _m([t], since=dt.date(2026, 8, 3), through=dt.date(2026, 8, 3))
    (s,) = m["sessions"]
    assert s["outcome"] == "blocked"
    assert s["primary"]["code"] == "broker_down"
    assert s["primary"]["check"] == "broker"
    assert s["primary"]["endpoint"] == "127.0.0.1:7497"
    assert s["primary"]["port"] == 7497
    (b,) = m["blockers"]
    assert b["code"] == "broker_down" and b["endpoints"] == ["127.0.0.1:7497"]


def test_two_blockers_in_one_reason_are_both_kept(tree):
    """2026-08-07 failed data AND broker. "the single blocking reason" is a
    simplification the data does not support, so primary is the log's own first
    and nothing is discarded."""
    reason = ("[FAIL] data: prices -> 2026-08-04 (3bd); NAV -> 2026-08-03 (4bd); "
              + BROKER_REASON.format(port=7497))
    t = tree("dev", {"2026-08-07": blocked_log("2026-08-07", reason)})
    m = _m([t], since=dt.date(2026, 8, 7), through=dt.date(2026, 8, 7))
    (s,) = m["sessions"]
    assert s["codes"] == ["broker_down", "stale_data"]
    assert s["primary"]["code"] == "stale_data"   # first in the log's own order
    assert {b["code"] for b in m["blockers"]} == {"stale_data", "broker_down"}
    # One session, two blocker rows. The sum deliberately exceeds the miss count.
    assert sum(b["sessions"] for b in m["blockers"]) == 2 and m["n_missed"] == 1


def test_a_free_text_reason_survives_verbatim(tree):
    """`human halt (DRY_RUN=1)` carries no [FAIL] verdict. Dropping it into an
    empty "other" bucket would lose the only sentence that explains the day."""
    t = tree("dev", {"2026-07-31": blocked_log("2026-07-31",
                                               "human halt (DRY_RUN=1)")})
    m = _m([t], since=dt.date(2026, 7, 31), through=dt.date(2026, 7, 31))
    (s,) = m["sessions"]
    assert s["primary"]["code"] == "human_halt"
    assert s["primary"]["text"] == "human halt (DRY_RUN=1)"
    assert s["primary"]["check"] is None


def test_a_log_with_no_verdict_is_indeterminate_and_refuses_a_rate(tree):
    """A session killed before preflight is NOT a stand-down. Calling it "not
    armed" would book a crash as an orderly refusal, and the rate would stand."""
    t = tree("dev", {"2026-09-09": HEAD.format(d="2026-09-09") + PREFLIGHT_OK})
    m = _m([t], since=dt.date(2026, 9, 9), through=dt.date(2026, 9, 9))
    (s,) = m["sessions"]
    assert s["outcome"] == "indeterminate"
    assert m["n_indeterminate"] == 1
    assert m["complete"] is False
    assert any("2026-09-09" in r for r in m["incomplete_reasons"])


def test_a_dry_runs_zero_turnover_is_not_the_books_turnover(tree):
    """A not-armed session still prints `BOOK asof ... turnover $0`, because it
    downgrades to a dry run against a $0.00 book by design. Filing that 0 under
    "modelled turnover" would put "it traded nothing" and "it was never asked to
    trade" in one column under a header that says neither — and a zero that means
    "not measured" is the exact defect this whole panel exists to stop."""
    dry = (blocked_log("2026-09-09", BROKER_REASON.format(port=4002))
           + "\n[run_book] BOOK asof 2026-09-09  NAV $0.00  PnL $0.00  "
             "turnover $0  gross $0\n")
    t = tree("dev", {"2026-09-10": armed_log("2026-09-10"), "2026-09-09": dry})
    m = _m([t], since=dt.date(2026, 9, 9), through=dt.date(2026, 9, 10))
    by = {s["date"]: s for s in m["sessions"]}
    assert by["2026-09-10"]["modelled_turnover_usd"] == 87003.0
    assert by["2026-09-10"]["dryrun_turnover_usd"] is None
    assert by["2026-09-09"]["modelled_turnover_usd"] is None
    assert by["2026-09-09"]["dryrun_turnover_usd"] == 0.0


def test_an_armed_session_with_no_book_line_reports_no_turnover(tree):
    """2026-09-08 crashed before the BOOK line. Absent, not zero."""
    t = tree("dev", {"2026-09-08": armed_log("2026-09-08", book_run="FAILED rc=1",
                                             done="failed").replace(
        BOOK_LINE.format(d="2026-09-08"), "\n")})
    m = _m([t], since=dt.date(2026, 9, 8), through=dt.date(2026, 9, 8))
    (s,) = m["sessions"]
    assert s["modelled_turnover_usd"] is None
    assert s["dryrun_turnover_usd"] is None


def test_the_older_rung_0_format_is_read_not_abandoned(tree):
    """phase0's July logs come from an earlier wrapper: no `launchd start`, no
    `NOT ARMED`, no `done status=`, just `RUNG-0 dry run ->`. That is a complete
    stand-down and must be read as one — otherwise `indeterminate` stops meaning
    "undecipherable" and exit 3 stops meaning anything. No cef log has this
    shape; two phase0 logs do."""
    text = ("2026-09-10 TRADING\n"
            "[2026-09-10 20:33:41] RUNG-0 dry run -> /tmp/x "
            "(nothing transmitted, live state untouched)\n"
            "[2026-09-10 20:49:13] ok\n")
    t = tree("dev", {"2026-09-10": text})
    m = _m([t], since=dt.date(2026, 9, 10), through=dt.date(2026, 9, 10))
    (s,) = m["sessions"]
    assert s["outcome"] == "blocked"
    assert s["primary"]["code"] == "rung_config"
    assert "RUNG-0" in s["reason"]
    assert m["n_indeterminate"] == 0 and m["complete"] is True


def test_a_second_run_refused_by_the_same_day_guard_is_a_note_not_a_fault(tree):
    """2026-09-01, benchmarks: the job fired twice and the SAME-DAY GUARD refused
    the second order set. Two facts follow and both were wrong before this:

      * the ARMED run's `done status=ok` governs, not the second run's
        `ok_already_traded` — taking the file's last value marked a good session
        not-clean;
      * it is a NOTE, not an anomaly. An anomaly list that fills with designed
        behaviour is an anomaly list nobody reads, which is this panel's own
        failure mode."""
    text = (HEAD.format(d="2026-09-10") + PREFLIGHT_OK
            + "[2026-09-10 17:22:11] ARMED: EXECUTION=ibkr "
              "books-root=ops/books/benchmarks_live asof=2026-09-10\n"
            + BOOK_LINE.format(d="2026-09-10")
            + "[2026-09-10 17:22:15] book run ok\n"
              "[2026-09-10 17:22:15] done status=ok\n"
            + HEAD.format(d="2026-09-10")
            + "[2026-09-10 17:25:05] SAME-DAY GUARD: benchmarks already ran "
              "ARMED today at 2026-09-10 17:22:15. NOT transmitting a second "
              "order set.\n"
              "[2026-09-10 17:25:05] NOT ARMED -> dry run in /tmp/x. Reason: "
              "already traded today (same-day guard)\n"
              "[2026-09-10 17:25:09] done status=ok_already_traded\n")
    t = tree("dev", {"2026-09-10": text})
    m = _m([t], since=dt.date(2026, 9, 10), through=dt.date(2026, 9, 10))
    (s,) = m["sessions"]
    assert s["n_runs"] == 2
    assert s["outcome"] == "armed" and s["clean"] is True
    assert s["done_status"] == "ok"            # the ARMED run's, not the second's
    assert s["anomalies"] == []
    assert s["notes"] and "same-day guard" in s["notes"][0]
    assert m["anomalies"] == [] and m["notes"]


def test_two_armed_runs_on_one_date_is_an_anomaly(tree):
    """The doubling hazard: the trade phase is not idempotent, there is no dedupe
    at the broker, and `arm()` re-seeds from positions that do not include
    unfilled MOC orders, so both sets fill in the same closing auction."""
    text = (armed_log("2026-09-10")
            + armed_log("2026-09-10").replace("17:15:35", "17:40:00"))
    t = tree("dev", {"2026-09-10": text})
    m = _m([t], since=dt.date(2026, 9, 10), through=dt.date(2026, 9, 10))
    (s,) = m["sessions"]
    assert s["notes"] == []
    assert any("two armed runs" in a for a in s["anomalies"])
    assert [a["date"] for a in m["anomalies"]] == ["2026-09-10"]
    # An anomaly must NOT silently move the rate; it is a different question.
    assert m["n_armed"] == 1 and m["n_eligible"] == 1


def test_anomalies_are_reported_but_never_change_the_rate(tree):
    """A filename/banner date mismatch is a record-integrity problem, not a
    trading outcome. It must be named and must leave the counts alone."""
    t = tree("dev", {"2026-09-10": armed_log("2026-09-10").replace(
        "2026-09-10 TRADING", "2026-09-09 TRADING", 1)})
    m = _m([t], since=dt.date(2026, 9, 10), through=dt.date(2026, 9, 10))
    (s,) = m["sessions"]
    assert any("log banner date 2026-09-09" in a for a in s["anomalies"])
    assert m["n_armed"] == 1 and m["n_clean"] == 1


# -------------------------------------------------------------- eligibility --
def test_a_non_trading_day_is_excluded_from_the_denominator(tree):
    """2026-09-07 was Labor Day and has a log. Counting it as a miss is a false
    alarm, and a panel that cries wolf is a panel nobody reads."""
    assert not nyse_calendar.is_trading_day(dt.date(2026, 9, 7))
    t = tree("dev", {"2026-09-04": armed_log("2026-09-04"),
                     "2026-09-07": closed_log("2026-09-07"),
                     "2026-09-08": armed_log("2026-09-08")})
    m = _m([t], since=dt.date(2026, 9, 4), through=dt.date(2026, 9, 8))
    assert [s["date"] for s in m["sessions"]] == ["2026-09-04", "2026-09-08"]
    assert m["n_eligible"] == 2 and m["n_armed"] == 2 and m["n_missed"] == 0
    assert m["closed_days_with_logs"] == [{"date": "2026-09-07",
                                           "outcome": "closed"}]


def test_weekends_are_never_eligible(tree):
    t = tree("dev", {"2026-09-04": armed_log("2026-09-04")})
    m = _m([t], since=dt.date(2026, 9, 4), through=dt.date(2026, 9, 6))
    assert [s["date"] for s in m["sessions"]] == ["2026-09-04"]


def test_a_trading_day_with_no_log_is_a_miss(tree):
    """The worst outcome is the one a log parser cannot see: the job never ran.
    It must land in the denominator, not vanish from it."""
    t = tree("dev", {"2026-09-08": armed_log("2026-09-08"),
                     "2026-09-10": armed_log("2026-09-10")})
    m = _m([t], since=dt.date(2026, 9, 8), through=dt.date(2026, 9, 10))
    by = {s["date"]: s for s in m["sessions"]}
    assert by["2026-09-09"]["outcome"] == "no_log"
    assert m["n_eligible"] == 3 and m["n_no_log"] == 1 and m["n_missed"] == 1
    assert any(b["code"] == "no_log" for b in m["blockers"])
    # no_log is a measured miss, not an unmeasurable gap.
    assert m["complete"] is True


def test_the_default_window_excludes_todays_unfinished_session(tree):
    """cef fires 17:15 and may poll for NAV until 23:30. Counting today as a
    miss at noon would make the panel wrong every single morning — and the
    exclusion is STATED in the payload, not hidden."""
    t = tree("dev", {"2026-09-10": armed_log("2026-09-10")})
    m = su.measure(trees=[t], since=dt.date(2026, 9, 10),
                   today=dt.date(2026, 9, 11))
    assert m["window"]["through"] == "2026-09-10"
    assert "2026-09-11" in m["window"]["excluded_today"]
    assert [s["date"] for s in m["sessions"]] == ["2026-09-10"]


# -------------------------------------------------------------- both trees ---
def test_reading_one_tree_undercounts_and_the_union_does_not(tree):
    """The logs bifurcated on 2026-09-10. This is the defect that produced two
    different published uptime figures for the same book."""
    dev = tree("dev", {"2026-09-09": armed_log("2026-09-09")})
    prod = tree("prod", {"2026-09-10": armed_log("2026-09-10")})
    one = _m([dev], since=dt.date(2026, 9, 9))
    both = _m([dev, prod], since=dt.date(2026, 9, 9))
    assert one["n_armed"] == 1 and one["n_eligible"] == 2      # 09-10 a no_log
    assert both["n_armed"] == 2 and both["n_eligible"] == 2
    assert [t["n_logs"] for t in both["trees"]] == [1, 1]


def test_a_date_in_both_trees_is_reported_and_the_later_tree_wins(tree):
    """Do not average and do not pick silently. Prod decides, because prod is
    where the scheduler runs — and the disagreement is printed either way."""
    dev = tree("dev", {"2026-09-10": blocked_log("2026-09-10",
                                                 BROKER_REASON.format(port=4002))})
    prod = tree("prod", {"2026-09-10": armed_log("2026-09-10")})
    m = _m([dev, prod], since=dt.date(2026, 9, 10))
    (d,) = m["duplicates"]
    assert d["date"] == "2026-09-10"
    assert d["agree"] is False
    assert sorted(d["outcomes"]) == ["armed", "blocked"]
    assert d["used"] == str(prod)
    assert m["n_armed"] == 1


def test_an_absent_default_tree_makes_the_rate_incomplete(tree, monkeypatch):
    """An undercounted denominator flatters the rate. The tool must say so
    rather than print a smaller, nicer number."""
    dev = tree("dev", {"2026-09-10": armed_log("2026-09-10")})
    monkeypatch.setattr(su, "REPO", dev)
    monkeypatch.setattr(su, "PROD_TREE", dev.parent / "not-there")
    m = su.measure(since=dt.date(2026, 9, 10), today=dt.date(2026, 9, 11))
    assert m["complete"] is False
    assert any("not-there" in r for r in m["incomplete_reasons"])
    assert [t["present"] for t in m["trees"]] == [True, False]


def test_a_named_tree_that_does_not_exist_raises(tmp_path):
    """Named explicitly, a missing tree is an error. You cannot ask for a tree
    that is not there and be handed a number anyway."""
    with pytest.raises(FileNotFoundError) as e:
        su.measure(trees=[tmp_path / "nope"])
    assert "nope" in str(e.value)


def test_no_logs_at_all_is_not_a_zero_percent_uptime(tmp_path):
    """`0 of 0` and `0 of 29` look alike in a headline and mean opposite things."""
    root = tmp_path / "empty"
    (root / su.LOG_SUBDIR).mkdir(parents=True)
    m = su.measure(trees=[root])
    assert m["ok"] is False and m["complete"] is False
    assert "no cef_*.log" in m["reason"]


# ------------------------------------------------------- definition of done --
def test_the_target_is_a_rate_not_a_fix(tree):
    """Twenty consecutive clean sessions, measured backward from the end of the
    window. One clean session after a month of misses must not read as fixed."""
    days = [d for d in su.eligible_days(dt.date(2026, 8, 3), dt.date(2026, 9, 10))]
    logs = {d.isoformat(): armed_log(d.isoformat()) for d in days}
    m = _m([tree("dev", logs)], since=days[0], target=20)
    assert m["n_eligible"] >= 20
    assert m["streak_clean"] == m["n_eligible"]
    assert m["target_met"] is True

    # Break the MIDDLE: the streak that matters is the one you are in now, so a
    # break in the middle must not stop the tail streak reaching the target...
    mid = days[len(days) // 2].isoformat()
    logs[mid] = blocked_log(mid, BROKER_REASON.format(port=4002))
    m2 = _m([tree("dev2", logs)], since=days[0], target=20)
    assert m2["streak_clean"] < m2["n_eligible"]
    assert m2["target_met"] is (m2["streak_clean"] >= 20)

    # ...but breaking the LAST session resets it to zero regardless of history.
    last = days[-1].isoformat()
    logs[last] = blocked_log(last, BROKER_REASON.format(port=4002))
    m3 = _m([tree("dev3", logs)], since=days[0], target=20)
    assert m3["streak_clean"] == 0 and m3["target_met"] is False
    assert m3["longest_clean_run"] > 0


def test_a_late_arm_breaks_the_streak(tree):
    """The strict streak is what the target keys on, so the 2026-09-10 shape
    must not be able to carry it."""
    days = su.eligible_days(dt.date(2026, 9, 1), dt.date(2026, 9, 10))
    logs = {d.isoformat(): armed_log(d.isoformat()) for d in days}
    last = days[-1].isoformat()
    nxt = (days[-1] + dt.timedelta(days=1)).isoformat()
    logs[last] = armed_log(last, armed_at=f"{nxt} 10:38:30")
    m = _m([tree("dev", logs)], since=days[0], target=20)
    assert m["streak_armed"] == m["n_eligible"]     # loose count is fooled
    assert m["streak_clean"] == 0                   # strict count is not
    assert m["target_met"] is False


def test_exit_codes(tree, capsys):
    """0 met, 1 not met, 3 could not measure. A cron needs the three to be
    distinguishable: "not met" is expected for weeks, "cannot measure" is a bug
    in the measurement and must not be mistaken for bad uptime.

    `--through` is passed so the window cannot move with the wall clock."""
    days = su.eligible_days(dt.date(2026, 8, 3), dt.date(2026, 9, 10))
    logs = {d.isoformat(): armed_log(d.isoformat()) for d in days}
    good = ["--tree", str(tree("good", logs)), "--through", "2026-09-10"]
    assert su.main(good + ["--target", "20"]) == 0
    assert su.main(good + ["--target", "999"]) == 1

    broken = dict(logs)
    d0 = days[-1].isoformat()
    broken[d0] = HEAD.format(d=d0)          # indeterminate
    assert su.main(["--tree", str(tree("bad", broken)),
                    "--through", "2026-09-10"]) == 3
    assert "INCOMPLETE" in capsys.readouterr().out


def test_the_json_flag_emits_parseable_json(tree, capsys):
    t = tree("dev", {"2026-09-10": armed_log("2026-09-10")})
    su.main(["--tree", str(t), "--through", "2026-09-10", "--json"])
    assert json.loads(capsys.readouterr().out)["n_armed"] == 1


# ----------------------------------------------------------------- payload ---
def test_the_payload_has_no_nan_and_survives_a_browser_parse(tree):
    """Python's json emits a bare NaN token that a browser's JSON.parse rejects
    outright, which has blanked this dashboard before. The payload the route
    returns must be clean at source, not only after sanitising."""
    t = tree("dev", {"2026-09-10": armed_log("2026-09-10")})
    blob = json.dumps(_m([t], since=dt.date(2026, 9, 10)))
    assert "NaN" not in blob and "Infinity" not in blob
    assert json.loads(blob)["n_armed"] == 1


def test_every_session_carries_a_reason_when_it_is_not_armed(tree):
    """Absence is information. No outcome may be reported without saying why."""
    days = su.eligible_days(dt.date(2026, 9, 1), dt.date(2026, 9, 10))
    logs = {days[0].isoformat(): blocked_log(days[0].isoformat(),
                                             BROKER_REASON.format(port=4002)),
            days[-1].isoformat(): HEAD.format(d=days[-1].isoformat())}
    m = _m([tree("dev", logs)], since=days[0])
    for s in m["sessions"]:
        if s["outcome"] != "armed":
            assert s["reason"], f"{s['date']} has no reason"


def test_the_calendar_is_the_schedulers_own_module():
    """Not a second holiday list. If these two ever disagree the measurement and
    the scheduler disagree about what a session is."""
    assert su.cal is nyse_calendar


# ------------------------------------------------------------- the live tree -
def test_the_live_trees_reproduce():
    """The weakest test here, and meaningful only because the others prove the
    parser is non-vacuous. Asserts INVARIANTS, never counts — a count in a test
    is a count that goes stale, and this repo has been wrong about one twice in
    twenty-four hours."""
    m = su.measure()
    assert m["ok"], m.get("reason")
    assert 0 <= m["n_armed"] <= m["n_eligible"]
    assert m["n_clean"] <= m["n_armed"]
    assert m["n_armed"] + m["n_missed"] == m["n_eligible"]
    for s in m["sessions"]:
        d = dt.date.fromisoformat(s["date"])
        assert nyse_calendar.is_trading_day(d), f"{s['date']} is not a trading day"
        if s["outcome"] == "armed":
            assert s["armed_at"], f"{s['date']} armed with no timestamp"
        else:
            assert s["reason"], f"{s['date']} missed with no reason"
    # The union can never see less than one tree alone. This is the property the
    # bifurcation broke, and the only one worth asserting against live data.
    dev_only = su.measure(trees=[su.REPO])
    assert m["n_armed"] >= dev_only["n_armed"]
    assert m["n_eligible"] >= dev_only["n_eligible"]
