# Unattended operation — what runs, what stops it, what tells you

Built 2026-07-31, in response to a day on which the book traded $2.07M gross and
told nobody anything.

## The incident this is all shaped by

Three faults compounded within eight hours:

1. **09:35** — the scheduled job died with exit 126. macOS TCC denies a launchd
   agent read access to `~/Desktop`, so `/bin/bash` could not even read the
   script. It transmitted nothing and wrote no application log.
2. **16:33** — the CEF job transmitted 16 orders. `ops/ledger.py:511` then raised
   `KeyError('NVG')`, because **28 of the 31 deployed tickers had no entry in
   `config/costs.yaml`** and the ledger deliberately hard-fails on a missing one.
3. `ibkr.py` caught that exception, printed one `repr()` line, and returned
   normally. The run ended by logging `ok`.

The consequence was not a lost report. `place_targets` diffs targets against the
shadow ledger, and the ledger was frozen at its funding row showing zero
positions while the account held 35. **The next session would have re-bought both
books entire**, against 164,500 CAD of excess liquidity at 83% margin use.

Every mechanism below exists because of one of those three steps.

## What runs

| launchd job | when (ET) | what it does |
|---|---|---|
| `com.quantt.phase0.daily` | 09:35 Mon–Fri | null-trader control experiment |
| `com.quantt.cef.daily` | 17:15 Mon–Fri | CEF discount sleeve, MOC for the next close |
| `com.quantt.collect.daily` | 18:30 Mon–Fri | forward-only data collection |
| `com.quantt.watchdog.daily` | 19:30 Mon–Fri | alerts on any job that did not run |
| `com.quantt.weekly` | Sat 09:00 | book roll-up report |

All five execute exactly one file: `~/Library/Application Support/quantt/launch_job.py`.

**Nothing scheduled may go through the shell.** The Anaconda interpreter holds
Full Disk Access and `/bin/bash` does not, so a launchd agent can run Python that
reads this repo but cannot run a shell script that does. That is fault 1, and it
is why the entry point lives outside the protected folder and is `.py`, not `.sh`.

## A session has four phases with different failure policies

    1. REFRESH    fetch today's prices/NAV           fail -> no trading, still logs
    2. PREFLIGHT  decide whether trading is safe     fail -> no trading, still logs
    3. TRADE      run the book, live or dry          fail -> halt + alert
    4. CAPTURE    record real broker executions      ALWAYS, even after 1-3 fail

The split matters. Trading is dangerous when state is wrong and should fail
closed. Data collection is only lost if it does not happen — the issuers publish
no archive, so a missed day is gone permanently. The old design conflated them,
so any fault also cost us the day's data.

Phase 4 is unconditional because `ib.fills()` serves the **current TWS session
only**. The daily restart destroys it. A capture that runs only after a
successful trade would lose exactly the fills worth having — which is what
happened to 302 executions on 2026-07-31.

## What stops trading

`ops/preflight.py` runs before every session. Any blocker clears `arm` while
leaving `collect` true: **a halted book still records, it just does not trade.**

| check | blocks? | catches |
|---|---|---|
| `halt` | yes | an active `ops/HALT.md` |
| `costs` | yes | any deployed ticker with no `half_spread_bp` — **fault 2** |
| `cost_drift` | warn | a static cost that no longer matches the tick-floor model |
| `data` | yes | stale prices/NAV (a stale NAV is a blind signal, not a cheap fund) |
| `broker` | yes | TWS not listening (it restarts daily and needs a login) |
| `margin` | yes | cushion under 0.10 — a broker liquidation ends the experiment |
| `heartbeat` | warn | the previous session never ran — **fault 1** |

`DRY_RUN=1` in a job's `.env` is a human hard halt and always wins. `DRY_RUN=0`
does **not** mean "trade"; it means "trade if preflight agrees".

## What cannot happen any more

**A stale ledger cannot cause a double-buy.** `broker.arm()` runs after sleeve
registration and before any target is placed, and splits authority:

> the **broker** is authoritative for how many shares exist,
> the **ledger** is authoritative for which sleeve owns them.

It overwrites quantities from `ib.positions()` and refuses to arm only when
attribution is genuinely ambiguous. `place_targets` raises `NotArmed` if called
first.

One subtlety that cost a debugging cycle: a symbol another book in the same
account also trades is **never** adopted from the account net. The account holds
823 HYG, of which `null_trader` owns 541 and the benchmark books own 282.
Adopting 823 would have sold 282 shares the sleeve never bought.

**A desync cannot be silent.** `ibkr.py` now raises `ShadowLedgerDesync`, and
before raising it writes the transmitted fills to `_desync/`, prints the full
traceback, and writes `ops/HALT.md`.

## How it reaches you

`ops/halt.py` pushes on three channels, in increasing order of loudness:

* **`ops/HALT.md`** — durable, greppable, read by preflight as a hard gate. This
  is the one that stops the money; it survives reboots.
* **macOS banner + spoken alert** — if you are at the machine.
* **email** — if you are not.

Alerting is best-effort and individually wrapped: an SMTP timeout can never
prevent the halt from being recorded. The file write happens first and unguarded.

Clearing a halt is deliberately manual and attributed:

    python3 -c "from ops.halt import clear_halt; clear_halt('what you fixed')"

Preflight can re-arm itself when its checks pass, but a desync that needed a
ledger rebuild needs a human to say the rebuild happened and was correct.

## Two things still need you

**1. Email alerts need a Google App Password** (the account password will not
work over SMTP). Add to `config/.env`:

    ALERT_EMAIL_TO=simon.jarvis0@gmail.com
    ALERT_SMTP_HOST=smtp.gmail.com
    ALERT_SMTP_PORT=587
    ALERT_SMTP_USER=simon.jarvis0@gmail.com
    ALERT_SMTP_PASS=<16-char app password from myaccount.google.com/apppasswords>

Until then the banner and spoken alert still fire, and every send attempt is
logged with its reason rather than failing quietly.

**2. A sleeping Mac still skips sessions.** On AC power this machine never sleeps
(`sleep 0`), so plugged in it is already fine. On battery it sleeps after one
minute. launchd coalesces missed calendar events to a single firing at wake, so a
laptop asleep at 09:35 runs phase 0 late — and an MOC order placed late misses
the auction entirely. Set a repeating wake (needs sudo):

    sudo pmset repeat wakeorpoweron MTWRF 09:20:00

`pmset repeat` supports only one wake per day; the 09:20 wake plus `sleep 0` on
AC covers the evening jobs as long as the machine stays plugged in.

## Known limitations, stated rather than hidden

* **The books are over-committed against the account.** CEF ($500k) + phase 0
  ($640k) = $1.14M USD claimed against ~$722k USD of equity — 158%, at cushion
  0.166 and 2.09x gross/NLV. The margin check blocks new exposure below 0.10, but
  that is a backstop, not a fix. Resizing is a decision, not a bug.
* **The shadow ledger books MODELLED fills by design**, and remains the sole P&L
  source. Real executions live in `broker_fills.csv` with realised-vs-modelled
  slippage in `slippage.csv`. The one exception is `null_trader`, rebuilt from
  real fills on 2026-07-31 because its ledger had no history at all and measuring
  real execution is its entire mandate.
* **First measured slippage was 7.76x modelled** (realised 120.6bp vs 15.5bp).
  Those were plain market orders resting overnight that filled at 07:27 ET,
  before the exchange opened. The spec has since moved to market-on-close; that
  number is the "before" reading, and kill rule (b) trips at 2x for 5 consecutive
  sessions, so watch the next few sessions closely.
* **`orderRef` does not survive the round trip** on this TWS build — every
  execution came back with `ref=''`. Fill attribution is therefore by symbol,
  which is safe only while no two deployed sleeves share a ticker.
  `ops/capture_fills.py` refuses to run if that ever stops being true.
