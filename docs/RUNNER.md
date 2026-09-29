# The Alpaca runner — build contract

**Status: being built (2026-09-28, branch `alpaca-runner`).** This is the design every
piece of `quantt/` is written against. It covers `docs/ROADMAP.md` phase 4 plus the
deploy decisions the team lead took on 2026-09-28 (below). It holds no figures about
the book: those come from `python3 -m ops.orient`.

## Decisions it rests on (team lead, 2026-09-28)

| question | decision |
|---|---|
| Go-live | **Armed on Tue 2026-09-29.** The first armed session's concrete order list is shown to the team lead, who says go. |
| Where prod runs | **This laptop for now** (no VM). A separate clone at a release tag, scheduled by launchd. A VM later. |
| After the first go | **The scheduled runner trades daily on its own**, behind every gate below. `CLAUDE.md` order-path rule 1 governs agents in a chat, not the scheduled runner. Stop it with the halt file or `DRY_RUN=1`. |
| Day one (flat book) | **Trade to full target**, not to the band edge, so the book starts dollar-neutral. The band applies from the second session. |
| Phase 3 probes | **Design around them.** Never reuse a `client_order_id`, one netted order per symbol per session, a long↔short flip is two orders (close, then open), and never assume the uncertain answer. Day one's real orders answer 3.1 and 3.5. |
| Scoring | Alpaca's fill (official) **and** the official closing-auction print, side by side, gross. |

## The session, in order

Decide on the **as-of day's complete price+NAV pair**, MOC for the **next trading
day's** close. This matches the research's `shift(2)`: decide on *t*'s data, fill
at *t+1*'s close, earn *t+2*. **When** (team lead 2026-09-29): in the **evening**
of *t*, 22:00–01:00 ET, once *t*'s NAVs are in (they landed 21:21–21:51 ET on
2026-09-28), with a **morning backstop** 06:00–15:15 ET on *t+1*. The evening and
morning runs decide on the same pair and make the same plan; an order sent after
19:00 ET is queued by Alpaca for the next day's auction [V: docs; first paper
evening send confirms it]. See "As built (2026-09-29)" below.

```
every 30 min  python3 -m quantt.session run --book cef --scheduled
              (idles outside the evening/morning slots and once the session is done)
          1. refresh    scripts/cef/fetch_daily.py --require-asof <prev trading day>
                        --nav-fallback cefconnect --book ops/books/cef_discount_book.json
                        exit != 0  -> NO TRADE today, logged (stale data never trades)
          2. read       Alpaca account (equity), positions, today's orders, clock
          3. decide     sleeve.target_positions(asof=<prev trading day>, MarketState(
                          holdings=<Alpaca positions>, extras={"sleeve_nav": <equity>,
                          "opening_session": <bool>}))
                        -> whole-share orders, one netted order per symbol,
                           a flip split into two orders
          4. gate       every check below; any failure -> nothing sent, logged
          5. record     <state>/<date>/STARTED written BEFORE the first order
          6. transmit   POST /v2/orders, type=market, time_in_force=cls, whole-share qty,
                        client_order_id = cef-<YYYYMMDD>-<SYMBOL>-<leg>
          7. confirm    re-read orders; every sent id must be at Alpaca, else FAIL
17:30 ET  python3 -m quantt.session verify --book cef   # post-close
          reconcile fills from the broker, fetch the official auction prints, score
          both P&Ls, append ONE line to <state>/verify.log: PASS or FAIL + reason
```

## Module boundaries (one owner each)

| module | owns | never |
|---|---|---|
| `quantt/broker/alpaca.py` | The REST client: account, positions, orders (list/submit), clock, calendar, assets, account activities, stock auctions (data API). Retries only idempotent GETs. | Decides anything. Holds a default for a missing field. |
| `quantt/session/decide.py` | Pure function: sleeve targets + holdings + equity + last closes → order list. Whole shares, netting, flip split, shortability. | Touches the network. |
| `quantt/session/gate.py` | Pure checks → a list of refusals. | Transmits. |
| `quantt/session/run.py` (+ `__main__.py`) | Orchestration of the session above; the only caller of `submit_order`. | Transmits when any gate refuses. |
| `quantt/session/verify.py` | Post-close reconcile + dual scoring + the one-line verdict. Read-only against the broker. | Transmits. |
| `src/deploy/sleeves/cef_discount.py` | The strategy. Gains `extras["opening_session"]`: when True the band is skipped (trade to full target); **absent or False is byte-identical to today** (proved by test). | — |
| `quantt/deploy/` | launchd plist templates + an install script for the laptop prod clone + `docs/RUNBOOK.md`. | Stores a credential. |
| `src/data/r2.py` + `scripts/data/` | Research/backtest access to the R2 WRDS mirror. **Never on the live path.** | Is imported by `quantt/`. |

## The gates (all must pass to transmit; each refusal names itself)

1. `DRY_RUN` — transmits only if the environment variable is **exactly `"0"`**. Unset, empty, `1`, anything else → dry. Always wins.
2. **Arming** — transmit additionally needs **either** `--approve <plan_sha>` equal to the sha256 of the freshly recomputed order list (the interactive first session: what was approved is what is sent) **or** the file `<state>/AUTO_ARMED` (created after the team lead's first go).
3. **Halt** — `ops/halt.read_halt(book)` returns a halt → refuse.
4. **Clock** — the session date is a trading day by both calendars and Alpaca's `/v2/clock` is inside the auction's send window: the as-of evening from **19:15 ET** (Alpaca queues `cls` sent after 19:00 into the next auction) to 01:00 ET, or the session day until **15:45 ET** (Alpaca rejects `cls` from 15:50; five minutes of margin). Early-close days: use `/v2/calendar`'s close, minus 10 minutes, cls cutoff per Alpaca docs.
5. **Data** — the refresh exited 0 for the required as-of date.
6. **No set already headed for this auction** — refuse if `<state>/<date>/STARTED` exists, or Alpaca shows any order today whose `client_order_id` starts with `cef-<YYYYMMDD>-`, or any open `cls` order in the account.
7. **Shortability** — an order that opens or increases a short needs `/v2/assets/<sym>` `shortable: true` today; else that symbol sends nothing and is logged (prereg v7 §6). Never substitute a name.
8. **Exposure** — projected gross ≤ spec `risk.max_gross_exposure_usd` and ≤ `max_gross_stress` × equity, and projected initial margin ≤ Alpaca buying power.
9. **Sanity** — every qty a positive integer, every symbol in the frozen universe, no symbol with two opposite-side orders.

## Rules the code must obey

- No silent fallbacks: a missing field, price or env var raises, naming it (`CLAUDE.md`).
- `QUANTT_STATE_DIR` (runtime records) and `QUANTT_ENV_FILE` (Alpaca keys) are **required** environment variables for `quantt.session`; unset → raise. Keys are read with `dotenv_values` and never printed, logged or written.
- Paper endpoint only: `https://paper-api.alpaca.markets`. A live endpoint anywhere is a test failure.
- Tests never touch the network (`ops/netguard.py` blocks it); the HTTP layer is mocked.
- Every live-path change ships with a test shown to fail against the wrong behaviour.

## As built (2026-09-28, after review)

The build, two independent reviews (quant, execution) and the fixes changed or
settled these points. Alpaca facts, each with its source and status:
`results/ops/ALPACA_API_FACTS_2026-09-28.md`.

- **Flips are deferred.** Alpaca reserves the shares of a pending sell and says to
  close a long fully before opening a short [V, Alpaca Learn]; staff say two orders
  like that are not supported [S]. So a long↔short flip sends only the closing leg
  today and logs `flip deferred`; the band opens the new side next session.
- **`cls` availability is [U].** Alpaca Learn says CLS orders are for Elite Smart
  Router users. The first real `cls` order answers it. The runner never falls back
  to `day`; if every order is rejected nothing was sent and the team lead decides.
- **A rejected order skips its symbol and the rest are sent** (team lead,
  2026-09-28); the day is FAIL naming it. Anything with an unknown outcome
  (ambiguous submit, unexpected error, clock) still stops the batch.
- **Gate 7** checks `shortable` only; hard-to-borrow is a preview warning (team
  lead, 2026-09-28).
- **Gate 4** re-reads the Alpaca clock at the gate and again before every POST; the
  refresh subprocess's timeout is the time left to the cutoff.
- **Gate 5** requires an as-of **NAV** as well as an as-of close for every name.
- **Gate 6** refuses on **any** open order in the account, not only `cls`.
- **Gate 8** checks buying power against `min(buying_power, regt_buying_power)`: the
  book holds overnight, where Reg T binds, not the 4× intraday figure.
- **Send order** is `transmit_sequence` (decide.py), not alphabetical.
- **Scoring** uses only the primary listing exchange's official-close print
  (condition `M`, exchange `N` for NYSE); a missing print leaves that name
  UNMEASURED and the day FAIL. It is never substituted.
- **Records:** `<state>/<D>/plan.json`, `orders.jsonl` (event log), `STARTED`,
  `reconcile.json`; `<state>/verify.log` (one line per day) and `scores.csv`.

## As built (2026-09-29): evening decision, morning backstop, nightly data

Team lead, 2026-09-29: *"we dont have to do it at 830 why have it a hard time -
should be flexible"*. The 08:30 run of that morning died on a DNS failure as the
laptop woke. What changed:

- **The session date is the auction an order sent now would join**
  (`run.session_for`): today before today's cutoff, else the next trading day.
  Both calendars must agree. `<D>` in every record is that auction's date.
- **Gate 4 and the per-POST check use one window** (`gate.in_send_window`): the
  as-of evening, 19:15 ET to 01:00 ET the next day, and the session day itself,
  00:00 ET to the cutoff. Not the daytime of a weekend or holiday in between:
  Alpaca documents no `cls` routing for those hours [U] (review 2026-09-29).
- **Known limit, kept deliberately:** `STARTED` is written before the first POST
  and blocks every later slot for that auction (CLAUDE.md rule 2). So if every
  evening order is rejected, or the clock read fails before the first POST, the
  morning backstop does not retry; the day is FAIL and the team lead decides
  (as for a `cls` rejection, 2026-09-28). Whether paper accepts an evening `cls`
  is [U] until the first evening send, which is watched live.
- **Nightly collector checks against an independent source:** it runs
  `fetch_daily` without the CEFConnect fallback, so its NAV cross-check compares
  yfinance (what is traded) against CEFConnect. The distributions script now
  writes nothing if any ticker fails, rather than dropping that ticker's
  history; transient print errors are retried, not recorded as gaps (review
  2026-09-29).
- **`--scheduled`** (launchd fires it every 30 minutes, every day): tries only
  in the evening slot (22:00 on the as-of date to 01:00) or the morning slot
  (06:00–15:15 on the session date), and only while the session is not done.
  Otherwise it prints one `IDLE` line and exits **5** with no record. A local-clock
  pre-check skips obviously-idle firings without calling Alpaca; it never permits
  one. Done means `STARTED`, `DONE` (a scheduled SENT or NOTHING_TO_SEND), or
  `DRY_DONE` (a scheduled DRY, honoured only while `DRY_RUN` is not `"0"`, so
  arming lets the next slot trade). REFUSED and FAIL leave the next slot free.
- **The refresh timeout is capped at 25 minutes**, so a hung fetch cannot hold
  the job past the next slot (launchd never runs two instances of one job).
- **Gate 6 reads orders from midnight before the as-of date**, so a Friday
  evening set is in view on Monday morning.
- **Verify** treats the next auction's runner orders as the runner's, not foreign.
- **Nightly data collector** (`quantt.collect`, launchd every 30 minutes at :10
  and :40): prices and NAVs, Alpaca's official closes, cross-checks between
  sources (**report only**, team lead 2026-09-29), an account snapshot and the
  distribution/split panels. Read-only at Alpaca. `docs/DATA.md`.
- **Shadow benchmark** (`quantt/session/shadow.py`, run by verify after the
  verdict, never able to change it): the runner's intended book, as if every
  order filled at the official closing print, marked close to close. One row per
  day in `<state>/shadow.csv`, labelled MODELLED; its state is
  `<state>/shadow_book.json`. Why: on 2026-09-29 paper filled 2 of 13 `cls`
  orders (PHK 4,019/4,019, PFN 1,529/2,227; eleven expired) although every NYSE
  auction printed more shares than we asked for; Alpaca staff confirm paper treats
  `cls` as a market order at the close with random partial fills (forum,
  2026-06-24).
