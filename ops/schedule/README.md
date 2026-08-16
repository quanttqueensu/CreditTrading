# ops/schedule — the book runs itself after each close (macOS)

Wires the 5-sleeve book (`ops/books/book.json`) to launchd (or cron) so that:

- **every NYSE trading weekday after the close** the daily unit runs
  (`src.deploy.run_daily`: advance all sleeves → broker → rollup → monitor);
- **every Saturday morning** a weekly book report is written to
  `ops/reports/weekly_book_<date>.md`;
- **holidays / weekends / special closures are no-ops** — the wrapper gates on
  `nyse_calendar.py`, so `--asof` is only ever a true trading day and the
  calendar-timed sleeves (EOM j-countdown, FOMC day-0) never shift phase;
- it ships **disarmed**: nothing is installed or loaded by the build, and the
  wrapper defaults to `DRY_RUN=1` + `EXECUTION=simulator` (compute + log the
  target book; transmit nothing).

## Files

| file | what |
|---|---|
| `nyse_calendar.py` | rule-based NYSE full-day-close calendar (stdlib only) + `--check/--prev/--next/--list` CLI; `SPECIAL_CLOSURES` is the hand-edited one-off list |
| `run_after_close.sh` | daily wrapper: trading-day gate → missed-day catch-up (`--replay-start`) → `run_daily --asof <today>` (+ `--dry-run` unless `DRY_RUN=0`) |
| `run_weekly.sh` | Saturday wrapper → `weekly_book_report.py` |
| `weekly_book_report.py` | read-only weekly roll-up: per-sleeve NAV/week-PnL, book rollup, monitor verdicts, the week's dry-run logs |
| `schedule.env` | the human-owned switchboard: `DRY_RUN`, `EXECUTION`, optional `PYTHON`/`BOOK` |
| `com.quantt.book.{daily,weekly}.plist.template` | launchd job templates (times + paths substituted by `install.sh`) |
| `install.sh` | renders → lints → (only on request) stages/enables the plists |
| `smoke_schedule.py` | the smoke check (see below) |
| `logs/`, `rendered/` | wrapper logs; rendered plists |

## How to enable (human steps — the build does NOT do this)

```bash
cd /Users/simonjarvis/Desktop/QUANTT/2027

# 1. render + lint the plists (already done by the build; re-run any time)
./ops/schedule/install.sh                       # default 16:40 daily, Sat 09:00
#   ./ops/schedule/install.sh --hour 17 --minute 0    # if this Mac is NOT in ET

# 2. stage into ~/Library/LaunchAgents (still inert)
./ops/schedule/install.sh --install

# 3. flip the live switch
./ops/schedule/install.sh --enable              # launchctl bootstrap gui/$UID

# verify
launchctl print gui/$(id -u)/com.quantt.book.daily | head
tail -f ops/schedule/logs/daily_$(date +%F).log

# disable everything
./ops/schedule/install.sh --disable
```

**Cron equivalent** (instead of launchd; `crontab -e`):

```cron
40 16 * * 1-5 /bin/bash /Users/simonjarvis/Desktop/QUANTT/2027/ops/schedule/run_after_close.sh
0  9  * * 6   /bin/bash /Users/simonjarvis/Desktop/QUANTT/2027/ops/schedule/run_weekly.sh
```

Holiday no-ops are inside the wrapper, so the cron lines stay dumb weekday
lines. Times are **local machine time** — the daily job must fire after the
4:00pm ET close (16:40 local is correct only in ET; adjust otherwise).

## The go-live ladder (edit `schedule.env`)

1. **Shipped state — `DRY_RUN=1`**: each close, the book computes every
   sleeve's targets and writes `ops/books/dryrun_<date>.json` +
   `book_status_dryrun.json`. No orders, no ledger writes, no monitor grade.
2. **`DRY_RUN=0`, `EXECUTION=simulator`**: the paper book actually advances —
   sub-ledgers fill T+1 under `ops/books/<sleeve>/`, `book_status.json` +
   `book_monitor.json` + daily report are written.
3. **`DRY_RUN=0`, `EXECUTION=ibkr`**: same runner trades IBKR paper. Requires
   the IB Gateway runbook first (human login, creds/host/port in
   `config/.env`). The scheduler itself needs no change.

## Dry-run mode (also available by hand)

```bash
/opt/anaconda3/bin/python3 -m src.deploy.run_daily --asof 2026-07-20 \
    --book ops/books/book.json --dry-run
```

`--dry-run` swaps in `DryRunBroker` (a `Simulator` whose `place_targets`
records targets and returns no fills): no order is transmitted, no sub-ledger
file is created or advanced, `book_status.json`/`book_monitor.json` are
untouched, and the target book (instrument, side, qty/weight, held qty,
reason) is printed and logged to `ops/books/dryrun_<asof>.json`. Verified by
`smoke_schedule.py --full`, which runs a real dry-run day into a throwaway
directory and asserts nothing else was written.

## Signal-timing guarantees

- The wrapper refuses to run on non-trading days, so `days_to_month_end` and
  the FOMC day-0 mapping only ever see real NYSE trading days — a holiday can
  never masquerade as the EOM j=4 entry or an FOMC emission day.
- **Missed days** (Mac off): on the next trading day the wrapper compares
  `book_status.json`'s `asof` with the previous trading day and, if behind,
  replays day-by-day via `--replay-start` — each replayed day re-derives its
  own targets, so calendar sleeves catch up in phase (never applying today's
  target to yesterday). Sleep (not shutdown) is simpler: launchd coalesces to
  one firing at wake.
- **Early closes** (Jul 3, day after Thanksgiving, Christmas Eve — 1:00pm ET)
  are trading days and run normally; 16:40 ET is after the early close too.

## Maintaining the calendar

Rule holidays (incl. Good Friday via Easter computus, the New-Year's-Saturday
non-observance, Juneteenth from 2022) are generated for any year — nothing to
update annually. Only **ad-hoc closures** (days of mourning, disasters) need a
one-line addition to `SPECIAL_CLOSURES` in `nyse_calendar.py`; then re-run the
smoke check.

## Smoke check

```bash
/opt/anaconda3/bin/python3 ops/schedule/smoke_schedule.py         # ~1s
/opt/anaconda3/bin/python3 ops/schedule/smoke_schedule.py --full  # + real dry-run day
```

Asserts: plists render valid (labels, Mon–Fri/Sat weekday sets, daily hour
≥ 16, wrapper paths exist, `RunAtLoad=false`); the 2024/2026 holiday lists
match the NYSE's published calendars date-for-date plus a dozen edge cases;
wrappers `bash -n` clean, executable, `schedule.env` in the safe state;
`--dry-run` is exposed end-to-end. `--full` additionally proves a dry-run day
writes nothing but its log. Exit 0 = green.
