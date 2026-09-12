"""Which decision a cef session may make, on which pair, and whether it may arm.

WHY THIS IS A REPO MODULE AND NOT A BLOCK INSIDE launch_job.py
--------------------------------------------------------------
`launch_job.py` lives outside the repo (macOS TCC denies launchd access to
~/Desktop; see its own header). That placement has a consequence nobody wrote
down: it is not in git, so it is not versioned, not covered by the prod/dev
split, and NOT GATED BY ops/promote.sh. An edit to it is live on the next fire
with no tag, no smoke test and no rollback path -- the exact opposite of every
other change to the order path.

So the part that decides whether a session is allowed to transmit lives HERE,
behind the promotion gate and under test, and `launch_job.py` only obeys it.
Nothing in this module performs I/O, connects to anything, or reads the clock:
every input is passed in, which is what makes the transition matrix in
ops/tests/test_session_plan.py able to cover cases that only occur once a
quarter in real time.

THE SCHEDULE THIS ENCODES, AND THE INCIDENT THAT MOTIVATED IT
--------------------------------------------------------------
Until 2026-09-11 there was one cef session, at 17:15, and it opened by waiting
for the day's NAV. That is a race against a publication time we do not control
and have now measured four times:

    2026-09-08  pair complete 22:43   armed 22:44
    2026-09-09  pair complete 21:45   armed 21:46
    2026-09-10  NOT complete at the 21:27 poll; the machine clamshell-slept at
                19:51:36 on battery, the next poll was 09:46 the FOLLOWING
                morning, and the session armed at 10:38 -- 17h23m after it
                started, for asof=2026-09-10
    2026-09-11  0/17 at 18:30, still polling

Two evenings in four the race was won with under two hours to spare, one was
lost to a power event, and the cost of losing it is not just a missed decision:
the 2026-09-10 session's four MOC orders DID fill at the 09-10 close (proved by
arm() adopting broker truth on 09-11: ledger JFR -5837 + SELL 4630 = -10467 =
broker, and the same arithmetic on MHD, MQY and NEA), but capture ran at 10:38
the next day, after IB's 03:00 restart had emptied reqExecutions. The positions
survived; the execution records did not, and those four fills have no slippage
row and never will. The book armed on 6 of 29 eligible sessions (20.7%).

THE INSIGHT (W3 Part A, docs/prompts/W3_session_architecture.md)
----------------------------------------------------------------
A decision made at 08:30 on day D from the completed pair of D-1, placed as MOC
for D's close, is THE SAME TRADE as a decision made at 20:00 on D-1 from the
same pair: identical information, identical fill, identical
`band_frontier.evaluate` convention (decide at t, MOC fill at t+1). What differs
is that at 08:30 the pair is complete on every vendor and has been for ten
hours, and the gateway has been up since its 03:00 restart. The race disappears
because we stop running it.

The one thing a morning session cannot do is capture the previous day's fills,
for exactly the reason the 09-10 executions were lost. So capture moves to a
small evening job:

    cef      08:30 and 12:00   decides on the PREVIOUS trading day's pair
    cef_pm   17:30             captures today's fills; decides only as fallback

TWO GUARDS, AND THEY ASK DIFFERENT QUESTIONS
---------------------------------------------
The trade phase is not idempotent and there is no dedupe at the broker, so a
second armed run stacks a second order set into the same auction (cef.env has
warned about this since 2026-07-31). Two jobs that can each decide need two
distinct refusals, and conflating them would leave a hole:

  PAIR GUARD    "has this pair already been decided?" -- protects the morning.
                Yesterday evening's fallback decides pair D-1; this morning
                would decide pair D-1 again, from a different calendar day, so
                the existing same-day guard cannot see it.

  TODAY GUARD   "has anything already decided today?" -- protects the evening.
                If the morning armed on pair D-1, the evening must not go on to
                decide pair D as well. Those are different pairs, so the PAIR
                guard cannot see it, and the book would trade into two
                consecutive auctions at double the intended turnover.

Both read the heartbeat, which keeps only the last beat per job. That is
sufficient and the tests prove the four transitions it has to survive: a
morning that arms, a morning refused by yesterday's fallback, a morning that
fails and is rescued by the 12:00 retry, and a day that falls through to the
evening and is then refused by the next morning.

THE CUTOFF IS NOT A STYLE POINT
--------------------------------
NYSE MOC and LOC interest may be entered, modified or cancelled only until
15:50 ET; after that it cannot be pulled at all, not even to correct a
legitimate error. A morning-mode session that somehow fires late (a wake from
sleep, a hand-run) must refuse rather than send an order it could not take back.
The evening path is NOT subject to this: its order is entered for the NEXT
session's auction, which is how the 21:46 arming on 2026-09-09 filled at the
09-10 close.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Session modes.
MORNING = "morning"            # decide on the previous trading day's pair
EVENING = "evening"            # fallback: wait for today's NAV, decide on it
CAPTURE_ONLY = "capture_only"  # record fills; make no decision

# Every job whose beat can represent a cef decision. A new decision-making cef
# job MUST be added here or both guards develop a blind spot the size of it.
CEF_JOBS = ("cef", "cef_pm")

# NYSE closing-auction entry cutoff, minutes past midnight ET. Not configurable:
# it is an exchange rule, not a preference.
MOC_CUTOFF_MIN = 15 * 60 + 50


@dataclass(frozen=True)
class SessionPlan:
    """What this fire is allowed to do. `may_arm` is the only authorising field.

    `asof` is the pair the sleeve decides on and the date preflight checks data
    freshness against -- NOT the calendar date of the session. Conflating them
    is the specific error W3 warns about: with asof left at today and the sleeve
    "falling back to the last complete pair", the ledger dates the fill tomorrow
    while the broker fills today, and the P&L record is wrong by a day.
    """
    job: str
    mode: str
    asof: str
    wait: bool
    may_arm: bool
    refusal: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Whether the refresh must PROVE the pair complete for `asof`
    # (fetch_daily --require-asof) or is merely keeping the panel current.
    #
    # It is False in capture-only mode for a reason that is easy to get
    # backwards: the evening job still refreshes, because the panel it writes
    # tonight is what TOMORROW MORNING's decision reads. But it is no longer
    # deciding anything itself, so a NAV that has not published by 17:30 is not
    # a stand-down -- it is just a fetch that will be redone at 08:30 against a
    # published number. Demanding --require-asof there would turn every normal
    # evening into a false alarm, since the pair typically completes at ~21:45.
    require_asof: bool = True

    @property
    def decides(self) -> bool:
        return self.mode in (MORNING, EVENING)


def _armed_beats(beats: dict) -> dict:
    """The cef-family beats that represent a real armed decision.

    A beat is only evidence of a transmitted order set if it says so. Dry runs,
    stand-downs and non-trading days all write beats too, and treating any of
    them as a decision would make the guards refuse sessions that never traded
    -- which fails in the dangerous direction for uptime rather than for safety,
    but fails silently either way.
    """
    out = {}
    for job in CEF_JOBS:
        beat = (beats or {}).get(job) or {}
        detail = beat.get("detail") or {}
        if detail.get("armed"):
            out[job] = beat
    return out


def pair_already_decided(beats: dict, pair_date: str) -> str | None:
    """Which job already armed on `pair_date`, or None.

    Reads `detail.pair_date`, which launch_job.py has written since 2026-09-08.
    A beat that armed but recorded NO pair_date is treated as a MATCH for any
    pair, because the alternative is to let an unlabelled armed session through
    the guard, and this module may never resolve an ambiguity in the direction
    of transmitting.
    """
    for job, beat in _armed_beats(beats).items():
        recorded = (beat.get("detail") or {}).get("pair_date")
        if recorded is None or str(recorded) == str(pair_date):
            return job
    return None


def decided_today(beats: dict, today: str) -> str | None:
    """Which job already armed on the calendar date `today`, or None."""
    for job, beat in _armed_beats(beats).items():
        if str(beat.get("date")) == str(today):
            return job
    return None


def plan(job: str, *, today: str, prev_trading_day: str, beats: dict,
         minutes_now: int, force: bool = False) -> SessionPlan:
    """Decide this fire's mode, pair and arming permission. Pure.

    `minutes_now` is local minutes past midnight; the machine runs on ET (the
    plists fire on local weekday slots and every deadline in cef.env is ET), so
    it is compared against the exchange cutoff directly. `force` is the
    FORCE_TRADE=1 escape hatch and it deliberately does NOT bypass the cutoff:
    a human who wants to override a guard can still not un-send an MOC.
    """
    if job == "cef":
        asof = prev_trading_day
        notes = []
        if minutes_now >= MOC_CUTOFF_MIN:
            return SessionPlan(job, MORNING, asof, wait=False, may_arm=False,
                               refusal=(f"past the 15:50 ET MOC entry cutoff "
                                        f"({minutes_now // 60:02d}:"
                                        f"{minutes_now % 60:02d}); an order "
                                        f"sent now could not be cancelled"))
        blocker = None if force else pair_already_decided(beats, asof)
        if blocker:
            return SessionPlan(job, MORNING, asof, wait=False, may_arm=False,
                               refusal=(f"pair {asof} was already decided by an "
                                        f"armed {blocker} session; refusing a "
                                        f"second order set into the same auction"))
        if force:
            notes.append("FORCE_TRADE=1: pair guard bypassed by a human")
        return SessionPlan(job, MORNING, asof, wait=False, may_arm=True,
                           notes=tuple(notes))

    if job == "cef_pm":
        # Capture is the evening job's REASON TO EXIST and never depends on any
        # of this; the caller runs phase 4 whatever comes back.
        earlier = None if force else decided_today(beats, today)
        if earlier:
            return SessionPlan(job, CAPTURE_ONLY, today, wait=False,
                               may_arm=False, require_asof=False,
                               refusal=(f"{earlier} already decided today; the "
                                        f"evening job records fills only"))
        blocker = None if force else pair_already_decided(beats, today)
        if blocker:
            return SessionPlan(job, CAPTURE_ONLY, today, wait=False,
                               may_arm=False, require_asof=False,
                               refusal=(f"pair {today} was already decided by an "
                                        f"armed {blocker} session"))
        notes = ("no armed session today - falling back to the evening NAV wait",)
        if force:
            notes = notes + ("FORCE_TRADE=1: guards bypassed by a human",)
        return SessionPlan(job, EVENING, today, wait=True, may_arm=True,
                           notes=notes)

    raise ValueError(
        f"session_plan.plan() does not know job {job!r}; known: {CEF_JOBS}. "
        f"A cef job absent from CEF_JOBS is invisible to both guards, so this "
        f"raises rather than defaulting to a permissive plan.")
