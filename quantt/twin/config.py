"""The twin's ruled settings (`ops/twin/ibkr_twin.json`) and its clock rules. Every key is required.

THE TIMES (contract §4.3; team lead 2026-11-25). Measured from the Alpaca calendar's close for the
session, so a 13:00 early close moves every one with it (2026-11-27, the day after Thanksgiving,
is the first armed session and a 13:00 close):

    send slot        close - 30 min     15:30   (12:30 on a 13:00 close)
    backup slot      close - 20 min     15:40   (12:40)
    refuse from      close - 15 min     15:45   (12:45): five minutes before the MOC cut-off
    stop the batch   close - 12 min     15:48   (12:48): an order not out by then is not sent
    verify           17:45, after the Alpaca books' verifies (17:30, 17:35), any close

The MOC cut-off is IBKR's 15:50 for every venue, the earlier of the two published figures (IBKR's
MOC page; NYSE puts Arca's freeze at 15:59; contract §4.3). NYSE's freeze is ten minutes before the
end of Core Trading Hours (Rule 7.35), so it is 12:50 on a 13:00 close. NYSE cancels and reduces no
MOC after the freeze, so nothing here ever cancels.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "ops" / "twin" / "ibkr_twin.json"
STATE_DIR_NAME = "twin"
ENV_STAGING = "QUANTT_TWIN_STAGING"

SEND_SLOT_MIN = (30, 20)
REFUSE_FROM_MIN = 15
STOP_BATCH_MIN = 12
CANCEL_REFUSE_MIN = 10       # the freeze: NYSE cancels no MOC after it (cancel-open refuses)
SLOT_SLACK = dt.timedelta(minutes=5)
assert SEND_SLOT_MIN[0] > SEND_SLOT_MIN[1] > REFUSE_FROM_MIN > STOP_BATCH_MIN > CANCEL_REFUSE_MIN


class ConfigError(RuntimeError):
    """The twin's settings file is missing a key or holds a value outside its range."""


@dataclasses.dataclass(frozen=True)
class TwinConfig:
    bp_fit_fraction: float
    nlv_report_only: bool


def load(path: Path = CONFIG_PATH) -> TwinConfig:
    d = json.loads(Path(path).read_text())
    for k in ("bp_fit_fraction", "nlv_report_only"):
        if k not in d:
            raise ConfigError(f"{path} has no {k}")
    f = d["bp_fit_fraction"]
    if isinstance(f, bool) or not isinstance(f, (int, float)) or not math.isfinite(f) or not 0 < f <= 1:
        raise ConfigError(f"{path}: bp_fit_fraction {f!r} is not a number in (0, 1]")
    if d["nlv_report_only"] is not True:
        raise ConfigError(f"{path}: nlv_report_only must be true until a measured tolerance is ruled")
    return TwinConfig(float(f), True)


def expected_close(day: dt.date) -> str:
    """The NYSE close this repo expects on a trading day, "HH:MM", to check Alpaca's calendar row
    against (review of the build, finding 14: refuse when they disagree, as the books do on
    whether a day trades). `ops/schedule/nyse_calendar.py` knows full closes only and treats early
    closes as trading days; it is not changed here (the Alpaca books read it). The early closes
    NYSE has scheduled for years [S: NYSE holiday schedule, not re-read in this build]: the day
    after Thanksgiving, December 24, and July 3, each at 13:00 when it is a trading day. Any other
    early close (a special one) makes the twin refuse, by name, which is the safe direction."""
    from ops.schedule.nyse_calendar import _nth_weekday, is_trading_day
    if not is_trading_day(day):
        raise ValueError(f"{day} is not a trading day by nyse_calendar")
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    early = {thanksgiving + dt.timedelta(days=1), dt.date(day.year, 12, 24), dt.date(day.year, 7, 3)}
    return "13:00" if day in early else "16:00"


def close_et(day: dt.date, calendar_close: str) -> dt.datetime:
    from quantt.session.gate import ET
    if not re.fullmatch(r"\d{2}:\d{2}", calendar_close or ""):
        raise ValueError(f"calendar close {calendar_close!r} is not HH:MM")
    hh, mm = map(int, calendar_close.split(":"))
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=ET)


def times(close: dt.datetime) -> dict:
    m = dt.timedelta(minutes=1)
    return {"slots": [close - SEND_SLOT_MIN[0] * m, close - SEND_SLOT_MIN[1] * m],
            "refuse_from": close - REFUSE_FROM_MIN * m, "stop_batch": close - STOP_BATCH_MIN * m,
            "freeze": close - CANCEL_REFUSE_MIN * m, "close": close}


def slot_state(now: dt.datetime, close: dt.datetime) -> str:
    """"early" (before the first slot, less the slack: the 12:30 fire on a 16:00 day), "slot",
    "too_late" (from the refuse time to the close: a REFUSED send), or "after_close" (the 15:30
    fire on a 13:00 day). Only "slot" may send."""
    t = times(close)
    if now < t["slots"][0] - SLOT_SLACK:
        return "early"
    if now >= close:
        return "after_close"
    if now >= t["refuse_from"]:
        return "too_late"
    return "slot"
