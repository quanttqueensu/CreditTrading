"""US (NYSE) market-holiday calendar for the scheduler — pure stdlib, rule-based.

The launchd/cron job fires every weekday; the wrapper asks THIS module whether
today is actually a trading day and no-ops on closes. That is what keeps the
calendar-timed sleeves honest: the runner only ever passes a true NYSE trading
day as --asof, so `days_to_month_end` (EOM j-countdown) and the FOMC day-0
mapping are never fed a holiday and never shift phase by a day.

Rules implemented (full-day closes):
  New Year's Day (Jan 1; Sun->Mon observed; **Saturday NOT observed** — NYSE
  did not close Fri 2021-12-31 for Sat 2022-01-01), Martin Luther King Jr. Day
  (3rd Mon Jan), Washington's Birthday (3rd Mon Feb), Good Friday (2 days
  before Easter, Butcher's computus), Memorial Day (last Mon May), Juneteenth
  (Jun 19, observed, from 2022), Independence Day (Jul 4, observed), Labor Day
  (1st Mon Sep), Thanksgiving (4th Thu Nov), Christmas (Dec 25, observed).
Sat->preceding Fri, Sun->following Mon (except the New Year's Saturday rule).

Early closes (1:00pm ET — typically Jul 3, day after Thanksgiving, Christmas
Eve) are TRADING days here; the job runs well after 1pm so nothing mis-times.

SPECIAL_CLOSURES holds one-off closes (days of mourning etc.) — edit by hand
when one is announced; the scheduled job no-ops on them like any holiday.

CLI (used by ops/schedule/run_after_close.sh):
    python3 ops/schedule/nyse_calendar.py --check 2026-07-20   # exit 0 = trading, 1 = closed
    python3 ops/schedule/nyse_calendar.py --prev  2026-07-20   # print previous trading day
    python3 ops/schedule/nyse_calendar.py --list  2026         # print the year's closes
"""

import argparse
import datetime as dt
import sys

# One-off full closures (announced ad hoc; keep appending).
SPECIAL_CLOSURES = {
    dt.date(2025, 1, 9),    # National Day of Mourning — President Carter
    dt.date(2018, 12, 5),   # National Day of Mourning — President G.H.W. Bush
    dt.date(2012, 10, 29),  # Hurricane Sandy
    dt.date(2012, 10, 30),  # Hurricane Sandy
}


def easter(year):
    """Easter Sunday (Gregorian), Butcher's algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _nth_weekday(year, month, weekday, n):
    """n-th `weekday` (Mon=0) of a month; n=-1 for the last one."""
    if n > 0:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    d = (dt.date(year + 1, 1, 1) if month == 12
         else dt.date(year, month + 1, 1)) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d, saturday_observed=True):
    """Sat -> preceding Fri (or None if NYSE skips it), Sun -> following Mon."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1) if saturday_observed else None
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def nyse_holidays(year):
    """Full-day NYSE holidays for `year` as {date: name} (rule closes only —
    SPECIAL_CLOSURES are layered on in is_trading_day)."""
    out = {}

    def add(d, name):
        if d is not None and d.year == year:
            out[d] = name

    # New Year's: Saturday NOT observed (Rule 7.2 convention); a Jan-1 Sunday
    # of NEXT year observes on Mon Jan 2 of next year, so check both years.
    for y in (year, year + 1):
        add(_observed(dt.date(y, 1, 1), saturday_observed=False),
            "New Year's Day")
    add(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")
    add(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")
    add(easter(year) - dt.timedelta(days=2), "Good Friday")
    add(_nth_weekday(year, 5, 0, -1), "Memorial Day")
    if year >= 2022:
        add(_observed(dt.date(year, 6, 19)), "Juneteenth")
    add(_observed(dt.date(year, 7, 4)), "Independence Day")
    add(_nth_weekday(year, 9, 0, 1), "Labor Day")
    add(_nth_weekday(year, 11, 3, 4), "Thanksgiving Day")
    add(_observed(dt.date(year, 12, 25)), "Christmas Day")
    return out


def is_trading_day(d):
    d = _as_date(d)
    if d.weekday() >= 5:
        return False
    if d in SPECIAL_CLOSURES:
        return False
    return d not in nyse_holidays(d.year)


def previous_trading_day(d):
    """Latest trading day strictly BEFORE d."""
    d = _as_date(d) - dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(d):
    """Earliest trading day strictly AFTER d."""
    d = _as_date(d) + dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def _as_date(d):
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d)[:10])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", metavar="YYYY-MM-DD",
                   help="exit 0 if a trading day, 1 if closed")
    g.add_argument("--prev", metavar="YYYY-MM-DD",
                   help="print the previous trading day (strictly before)")
    g.add_argument("--next", dest="next_", metavar="YYYY-MM-DD",
                   help="print the next trading day (strictly after)")
    g.add_argument("--list", metavar="YEAR", type=int,
                   help="print the year's full-day closes")
    args = ap.parse_args(argv)

    if args.check:
        d = _as_date(args.check)
        if is_trading_day(d):
            print(f"{d} TRADING")
            return 0
        why = nyse_holidays(d.year).get(d) or (
            "special closure" if d in SPECIAL_CLOSURES else "weekend")
        print(f"{d} CLOSED ({why})")
        return 1
    if args.prev:
        print(previous_trading_day(args.prev))
        return 0
    if args.next_:
        print(next_trading_day(args.next_))
        return 0
    if args.list:
        hols = sorted(nyse_holidays(args.list).items())
        specials = sorted(d for d in SPECIAL_CLOSURES if d.year == args.list)
        for d, name in hols:
            print(f"{d}  {name}")
        for d in specials:
            print(f"{d}  special closure")
        print(f"# {args.list}: {len(hols)} rule holidays, "
              f"{len(specials)} special closures")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
