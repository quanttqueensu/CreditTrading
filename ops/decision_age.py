"""Is this decision still the decision the backtest scored?

WHY THIS EXISTS
---------------
On 2026-09-10 the cef session started at 17:15, the Mac clamshell-slept at
19:51 on battery, and the process resumed the next morning. `wait_for_nav.py`
found a complete pair at 09:46 and returned 0 -- the SUCCESS path -- because it
tests completeness (`:145`) before it tests the deadline (`:158`). That ordering
is deliberate and right for a session that is merely slow. The consequence is
that the deadline bounds the WAIT, not the SESSION, and nothing downstream ever
re-asked the question. The book armed at 10:38:30 on 2026-09-11, seventeen
hours and twenty-three minutes after its own launch.

IT COST NOTHING, AND THAT WAS LUCK. The execution convention is shift(2):
decide at t, MOC fills at t+1's close, earn the t+2 return (`evaluate()` in
scripts/cef/band_frontier.py). An order placed 10:38 on t+1 still reaches
t+1's auction. Ten minutes past the entry freeze and the same code would have
armed into a closed auction, or into the wrong one.

It also cost the NEXT session. The beat filed at 10:38 on 09-11 stamped
`armed: true` onto 09-11's calendar slot, and the same-day guard
(`launch_job.py:326-336`) then correctly refused the 09-11 session rather than
stack a second order set. One power event, two lost sessions.

TWO CONDITIONS, AND NEITHER IS SUFFICIENT ALONE
-----------------------------------------------
This is the part a single test gets wrong, and 2026-09-10 is the proof.

  (A) AUCTION IDENTITY -- the economic invariant. The order must reach the
      auction the convention scored: exactly one NYSE session after the
      decision. Not "tomorrow" -- that test is false every Friday and after
      every holiday, which is the defect `test_ledger_behind_guard.py` exists
      for.

  (B) SESSION WINDOW -- the operational ceiling. A session is the supervised
      session only while it is inside the window its own config allows.

The 09-10 timeline PASSES (A): next_trading_day(2026-09-10) is 2026-09-11, and
10:38 is before the freeze, so it genuinely reached the right auction. Only (B)
refuses it. Conversely a config whose ceiling reached past the freeze would
pass (B) and must still be refused by (A). Both, always.

ON REFUSAL: STAND DOWN. Do not re-decide on fresher data -- a re-decision at
10:38 has not seen the 16:00 close it is about to be scored against -- and do
not write a durable halt, which would convert one late session into an outage
until a human clears it.

THE EARLY-CLOSE GAP, NAMED RATHER THAN PAPERED OVER
----------------------------------------------------
NYSE Rule 7.35(a)(8) sets the Closing Auction Imbalance Freeze at ten minutes
before the end of Core Trading Hours, so on a 13:00 half-day it is 12:50, not
15:50. `ops/schedule/nyse_calendar.py` has NO early-close table -- its own
docstring says so and justifies it for a job that runs well after 1pm. We
therefore reuse `session_plan.MOC_CUTOFF_MIN`, the repo's single existing
cutoff constant, and inherit its assumption of a 16:00 close.

This is a real gap and it is NOT load-bearing here, which is why it is
documented rather than guessed at: condition (B) does not depend on the cutoff
at all, and (B) is what catches the late-wake case that (A)'s cutoff would
misjudge. A sourced early-close table belongs in nyse_calendar.py; inventing
one here would be exactly the kind of unsourced constant this desk has been
burned by. Until it exists, an early close is a known blind spot in (A) alone.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ops" / "schedule"))

# The exchange's zone, explicitly. This machine's local zone is America/Toronto
# -- same offsets today, but a freeze time is an exchange fact and must not be
# compared in whatever zone the laptop happens to carry.
EXCHANGE_TZ = ZoneInfo("America/New_York")

NYSE_CLOSE_MIN = 16 * 60


class DecisionAgeUnknown(RuntimeError):
    """The ceiling could not be derived, so no verdict is possible.

    NO SILENT FALLBACKS. The whole defect class this module addresses is a
    literal that stopped matching reality; defaulting to one here would rebuild
    it. An unparseable NAV_DEADLINE or a missing plist raises, and the caller
    refuses to arm -- it does not guess a window.
    """


def _now_et(now=None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(EXCHANGE_TZ)
    if now.tzinfo is None:
        raise DecisionAgeUnknown(
            "a naive datetime was passed as `now`; the exchange zone must be "
            "explicit or the freeze comparison is meaningless")
    return now.astimezone(EXCHANGE_TZ)


def reachable_auction(now_et: dt.datetime):
    """The NYSE session whose closing auction an MOC sent now would reach."""
    import nyse_calendar as cal

    d = now_et.date()
    if not cal.is_trading_day(d):
        return cal.next_trading_day(d)
    from ops.session_plan import MOC_CUTOFF_MIN
    if now_et.hour * 60 + now_et.minute < MOC_CUTOFF_MIN:
        return d
    return cal.next_trading_day(d)


def session_start(job: str, decision_date: dt.date) -> dt.datetime:
    """When the session that decided `decision_date` was scheduled to start.

    Derived from the INSTALLED plist, not written down, so it stays correct
    across the 17:15 -> 08:30/17:30 split without an edit here. A fire after
    the 16:00 close is deciding on that day's own pair and therefore started on
    the decision date; a fire before the close cannot be -- the pair has not
    been struck yet -- so it started on the following session.
    """
    import nyse_calendar as cal
    from ops import doctor

    start = doctor._plist_start_minutes(job)
    if start is None:
        raise DecisionAgeUnknown(
            f"no installed plist for job {job!r}, so its session start cannot "
            f"be derived (looked for com.quantt.{job}.daily in "
            f"~/Library/LaunchAgents)")
    day = decision_date if start >= NYSE_CLOSE_MIN else cal.next_trading_day(decision_date)
    if not isinstance(day, dt.date):
        day = dt.date.fromisoformat(str(day))
    return dt.datetime.combine(
        day, dt.time(start // 60, start % 60), tzinfo=EXCHANGE_TZ)


def refusal(job: str, decision_date, now=None) -> str | None:
    """None if it is still safe to arm, else the reason to stand down.

    ALIGNMENT: `decision_date` is the PAIR date the sleeve decided on -- the
    same value that reaches place_targets as `asof` and that ops/ledger.py
    writes as `decision_date`. It is NOT "today"; under the morning schedule
    they differ by one session, which is the whole point of that schedule.
    """
    import nyse_calendar as cal
    from ops import doctor

    if decision_date is None:
        raise DecisionAgeUnknown(
            "decision_date is None; the decision's age cannot be judged and "
            "arming on an unjudgeable decision is what 2026-09-10 did")
    if not isinstance(decision_date, dt.date):
        decision_date = dt.date.fromisoformat(str(decision_date)[:10])

    now_et = _now_et(now)

    # (B) SESSION WINDOW -- the condition that refuses 2026-09-10.
    ceiling = doctor._session_deadline_minutes(job)
    if ceiling is None:
        raise DecisionAgeUnknown(
            f"the session ceiling for job {job!r} could not be derived -- its "
            f"NAV_DEADLINE is missing or unparseable in "
            f"ops/schedule/{job}.env, or its plist start is not readable. "
            f"Refusing rather than guessing a window.")
    started = session_start(job, decision_date)
    latest_ok = started + dt.timedelta(minutes=ceiling)
    if now_et > latest_ok:
        age = now_et - started
        return (f"decision {decision_date} is stale: the session started "
                f"{started:%Y-%m-%d %H:%M %Z} and is now {_hm(age)} old, past "
                f"its derived ceiling of {_hm(dt.timedelta(minutes=ceiling))} "
                f"(latest {latest_ok:%Y-%m-%d %H:%M %Z}). Ceiling = "
                f"(NAV_DEADLINE - plist start) + slack, read at run time from "
                f"ops/schedule/{job}.env and the installed plist.")

    # (A) AUCTION IDENTITY -- one NYSE session of lag, exactly.
    want = cal.next_trading_day(decision_date)
    if not isinstance(want, dt.date):
        want = dt.date.fromisoformat(str(want))
    reach = reachable_auction(now_et)
    if not isinstance(reach, dt.date):
        reach = dt.date.fromisoformat(str(reach))
    if reach != want:
        return (f"decision {decision_date} would fill in the wrong auction: "
                f"shift(2) wants {want} (one NYSE session after the decision), "
                f"but an MOC sent at {now_et:%Y-%m-%d %H:%M %Z} reaches "
                f"{reach}. Standing down rather than earning a return the "
                f"backtest never scored.")
    return None


def _hm(delta: dt.timedelta) -> str:
    mins = int(delta.total_seconds() // 60)
    sign = "-" if mins < 0 else ""
    mins = abs(mins)
    return f"{sign}{mins // 60}h{mins % 60:02d}m"
