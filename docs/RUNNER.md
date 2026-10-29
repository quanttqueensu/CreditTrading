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
| Scoring | Alpaca's fill (official) **and** the official closing-auction print, side by side, gross. **Which Alpaca number is official, from 2026-10-19** (team lead): Alpaca's **end-of-day portfolio history** (`GET /v2/account/portfolio/history`, `timeframe=1D`), EOD(D) − EOD(previous session). The 17:30 ET `equity − last_equity` reading is a labelled **snapshot**, kept and never blended ("As built (2026-10-19)" below). **Third line from 2026-10-09** (team lead): auction-marked P&L **plus distributions** on shares held at the start of each ex-date (credited long, charged short), because Alpaca paper credits none. It is scored two sessions late, once the cross-check source has caught up, and written to `distribution_scores.csv`. It never changes the verdict (`quantt/session/dist_score.py`). |

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
          1b. NAV gate  only when the book json sets data.stale_nav (absent: off; report:
                        record only). A NAV(D) equal to the previous NAV or to CEFConnect's
                        NAV(D-1) is checked against CEFConnect's D: stale copy -> replaced,
                        genuine repeat -> kept, unverified -> the decide is deferred to the
                        morning; from the final check the name keeps its shares.
                        "As built (2026-10-13)" below. With data.missing_nav = hold
                        (dark), a name whose NAV is not dated the as-of date is held
                        the same way from the final check. "As built (2026-10-29)".
          2. read       Alpaca account (equity), positions, today's orders, clock
          2b. drawdown  only when the book json sets risk.drawdown (absent: off; report
                        is the only mode built: record only). The drawdown from the
                        high-water mark of <state>/eod_equity.csv against the frozen
                        spec's risk.halve_drawdown / risk.kill_drawdown, recorded in
                        plan.json and the log. "As built (2026-10-19)" below.
          3. decide     sleeve.target_positions(asof=<prev trading day>, MarketState(
                          holdings=<Alpaca positions>, extras={"sleeve_nav": <equity>,
                          "opening_session": <bool>}))
                        -> whole-share orders, one netted order per symbol,
                           a flip split into two orders
          3b. corp. actions  only when the book json sets corporate_actions.mode
                        (absent: off; report: record and send; halt: refuse). Every
                        non-dividend corporate action naming a held or targeted name
                        inside that name's window; again at the late-market send.
                        "As built (2026-10-28)" below.
          4. gate       every check below; any failure -> nothing sent, logged
          5. record     <state>/<date>/STARTED written BEFORE the first order
          6. transmit   POST /v2/orders, type=market, time_in_force=cls, whole-share qty,
                        client_order_id = cef-<YYYYMMDD>-<SYMBOL>-<leg>
          7. confirm    re-read orders; every sent id must be at Alpaca, else FAIL
17:30 ET  python3 -m quantt.session verify --book cef   # post-close
          reconcile fills from the broker, fetch the official auction prints, score
          (official EOD figure or PENDING, snapshot, auction-marked), append ONE line
          to <state>/verify.log: PASS or FAIL + reason
```

## Module boundaries (one owner each)

| module | owns | never |
|---|---|---|
| `quantt/broker/alpaca.py` | The REST client: account, positions, orders (list/submit), clock, calendar, assets, account activities, end-of-day portfolio history, stock auctions and corporate actions (data API). Retries only idempotent GETs. | Decides anything. Holds a default for a missing field. |
| `quantt/session/decide.py` | Pure function: sleeve targets + holdings + equity + last closes → order list. Whole shares, netting, flip split, shortability. | Touches the network. |
| `quantt/session/gate.py` | Pure checks → a list of refusals. | Transmits. |
| `quantt/session/run.py` (+ `__main__.py`) | Orchestration of the session above; the only caller of `submit_order`. | Transmits when any gate refuses. |
| `quantt/session/nav_gate.py` | The stale-NAV gate (step 1b): finds each NAV(D) equal to the previous NAV or to CEFConnect's NAV(D-1), reads CEFConnect, replaces stale copies in the NAV panel through the logged fallback, defers or holds the unverified, records every check. | Transmits. Decides a target. |
| `quantt/session/drawdown.py` | The drawdown check (step 2b): reads `<state>/eod_equity.csv` by header, the frozen spec's two drawdown lines (units-checked), and records the status and what an acting mode would do. | Transmits. Changes an order. Falls back to `equity.csv`. |
| `quantt/session/combine.py` | The multi-sleeve combiner (2026-10-28, **dark**): reads the book json's `sleeves[]`; for a book whose enabled sleeves all carry `risk_budget`, builds each from its own spec on its own sleeve_nav, nets the whole-share targets per symbol into one `decide`, and records the per-sleeve attribution. Absent a budget, `None`: the single-spec session, byte-identical to de6e9c5 (proved by test). | Transmits. Splits a held position between sleeves. |
| `quantt/session/corp_actions.py` | The corporate-action gate (step 3b): dates each held name's shares from the account's closed orders, draws each name's window, keeps the actions that block, and writes the record and the refusal's sentence. Pure apart from the read it is handed. | Transmits. Changes an order. Reads an absent or failed feed as clear. |
| `quantt/session/verify.py` | Post-close reconcile + dual scoring + the one-line verdict. Read-only against the broker. | Transmits. |
| `src/deploy/sleeves/cef_discount.py` | The strategy. Gains `extras["opening_session"]`: when True the band is skipped (trade to full target); **absent or False is byte-identical to today** (proved by test). Gains `extras["nav_hold"]` (2026-10-13): names the stale-NAV gate could not verify by its final check keep their current shares and leave the cross-section; holds never trigger the `min_names` flatten; absent is byte-identical. | — |
| `quantt/deploy/` | launchd plist templates + an install script for the laptop prod clone + `docs/RUNBOOK.md`. | Stores a credential. |
| `src/data/r2.py` + `scripts/data/` | Research/backtest access to the R2 WRDS mirror. **Never on the live path.** | Is imported by `quantt/`. |

## The gates (all must pass to transmit; each refusal names itself)

1. `DRY_RUN` — transmits only if the environment variable is **exactly `"0"`**. Unset, empty, `1`, anything else → dry. Always wins.
2. **Arming** — transmit additionally needs **either** `--approve <plan_sha>` equal to the sha256 of the freshly recomputed order list (the interactive first session: what was approved is what is sent) **or** the file `<state>/AUTO_ARMED` (created after the team lead's first go).
3. **Halt** — `ops/halt.read_halt(book)` returns a halt → refuse.
4. **Clock** — the session date is a trading day by both calendars and Alpaca's `/v2/clock` is inside the auction's send window: the as-of evening from **19:15 ET** (Alpaca queues `cls` sent after 19:00 into the next auction) to 01:00 ET, or the session day until **15:45 ET** (Alpaca rejects `cls` from 15:50; five minutes of margin). Early-close days: use `/v2/calendar`'s close, minus 10 minutes, cls cutoff per Alpaca docs.
5. **Data** — the refresh exited 0 for the required as-of date. That checks each NAV's *date*, not its value; the stale-NAV gate (step 1b, "As built (2026-10-13)") checks the value when the book turns it on.
   - **Corporate actions** (step 3b, when the book json sets `corporate_actions.mode`; team lead 2026-10-28). Under `halt`, refuse when Alpaca lists a non-dividend corporate action (split, stock dividend, spin-off, merger, redemption, name change, worthless removal, reorganization, partial call) naming a held or targeted name, in any role, inside the window that role and match call for: the long window for an acquiree, a split, a name change and the rest, and the short window `(as-of, session]`, one session, for a merger acquirer and a reorganization's allocated leg (both on the market date only) and for any other match through the process date alone (team lead and re-review, 2026-10-29). Also refuse when that list cannot be read. The refusal is a gate-5 `data` refusal naming each event or the error. It runs at decide and again at the late-market send. Under `report` the same is recorded and the session sends. "As built (2026-10-28)" below.
6. **No set already headed for this auction** — refuse if `<state>/<date>/STARTED` exists, or Alpaca shows any order today whose `client_order_id` starts with `cef-<YYYYMMDD>-`, or any open `cls` order in the account.
7. **Shortability** — an order that opens or increases a short needs `/v2/assets/<sym>` `shortable: true` today; else that symbol sends nothing and is logged (prereg v7 §6). Never substitute a name.
8. **Exposure** — projected gross ≤ spec `risk.max_gross_exposure_usd`; ≤ `max_gross_stress` × the **lower** of the equity the plan was sized on and live equity, unless the plan does not add to the gross held now (2026-10-09; the lower of the two from 2026-10-11); and, on the live account, opening notional ≤ Alpaca `buying_power` and the overnight Reg T / maintenance limits on the book after the plan (2026-10-07). *Corrected 2026-10-09: this line read "≤ `max_gross_stress` × equity, and projected initial margin ≤ Alpaca buying power", the rule that refused 2026-10-09 ("As built (2026-10-09)" below).*
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
  *Superseded 2026-10-07 ("As built (2026-10-07)"): it refused a plan Alpaca would
  have accepted. Gate 8 is now an order-time and an overnight check.*
- **Send order** is `transmit_sequence` (decide.py), not alphabetical.
- **Scoring** uses only the primary listing exchange's official-close print
  (condition `M`, exchange `N` for NYSE); a missing print leaves that name
  UNMEASURED and the day FAIL. It is never substituted. *(The Alpaca figure called
  official here until 2026-10-19 is now the snapshot; see "As built (2026-10-19)".)*
- **Records:** `<state>/<D>/plan.json`, `orders.jsonl` (event log), `STARTED`,
  `reconcile.json`; `<state>/verify.log` (one line per day) and `scores.csv`.
- **Distribution-adjusted score** (third line, 2026-10-09; redesigned the same day after
  review). After the verdict, as with the shadow score, `quantt/session/dist_score.py`
  scores every session **at least two sessions old** that has no measured row yet. It
  reads that day's `reconcile.json` (`held_into_close`) and its `scores.csv` row, and
  upserts one row per session into `<state>/distribution_scores.csv`.
  - **Primary source:** Alpaca corporate actions.
  - **Cross-check:** the yfinance panel, within 0.0005 per share of rounding.
  - **When it is UNMEASURED:** a real conflict, or an ex-date only the panel lists.
  - **A zero needs both sources silent,** with the panel file rewritten after the
    close of the session following D. Otherwise the day is UNMEASURED and retried.
    A measured row is final.
  - **Never the verdict, never the exit code:** each post-verdict hook (shadow,
    distributions) is guarded separately in `main()`, and an error goes to stderr.
    `scores.csv`'s columns are unchanged.

## Paper execution (2026-09-29): decide in the evening, send as market orders at 15:52

Team lead, 2026-09-29, after the first armed session: paper filled 2 of 13 `cls`
orders (PHK 4,019/4,019, PFN 1,529/2,227; eleven expired), and Alpaca staff confirm
paper treats `cls` as a market order at the close with random partial fills. Rule 3
gets one recorded exception, **paper only**: `ops/books/cef_discount_book.json`
`execution = {mode: late_market, window_minutes_before_close: [8, 2]}`.

- **DECIDE** (evening 22:00–01:00 ET, morning backstop 06:00–15:15): refresh, read,
  decide, and every gate except dry-run, arming and clock. The plan is saved as
  `status: decided` with its `plan_sha`; nothing is sent (exit 6 PLANNED; `DECIDED`
  marker for scheduled runs).
- **APPROVE** (until `AUTO_ARMED`): `python3 -m quantt.session approve --book cef
  --date D --sha <plan_sha>` writes `<D>/APPROVED`, only for the decided plan with
  that sha, only before STARTED. Run on the team lead's explicit go (rule 1).
- **SEND** (15:52–15:58 ET, from the calendar close; 12:52–12:58 on a 13:00 close;
  launchd fires 15:52 and 15:55): the SAVED plan is loaded -- never re-decided,
  because intraday equity moves the sizing and what was approved must be what goes
  -- its orders must still hash to its sha, positions must still equal its
  "current", and dry-run, arming (`--approve`, `APPROVED` or `AUTO_ARMED`), halt,
  late clock, no-set, shortability, exposure and sanity are re-evaluated on fresh
  broker reads. Sent as `type=market, time_in_force=day`, the window re-checked
  before every POST.
- **A decided plan is never overwritten** -- not by a later manual run, and never
  by `--preview` (which would re-size on intraday equity). To re-decide on purpose,
  delete `<D>/plan.json` and `<D>/DECIDED` first.
- **A name that turned unshortable since the decision is skipped at send and the
  rest go** (team lead 2026-09-28, "skip that name, send the rest"); the arming
  check still binds to the decided plan's sha, so what goes is a subset of it.
  If that leaves nothing to send, the day is a `MISSED:` FAIL (2026-10-13, below).
- **The send records its outcome** in `<D>/send.json` (exit, refusals, skipped,
  and since 2026-10-13 `bp_scale_at_send`, the re-fit's result); verify explains
  a no-trade day from it, and a decided plan with no send record is FAIL "no send
  ran in the late window".
- **A set the window cannot finish is not started** (added 2026-10-08,
  release-check #6). `gate.gate_late_send_budget` refuses before STARTED and before
  any POST unless the time left on Alpaca's clock is at least
  `n_orders × 3 s + 42 s`; the constants and their provenance are in `gate.py`. The
  42 s margin is the connect and read timeouts plus one retry backoff (corrected
  from 30 s, release-check #7). At 13 orders a set may start until 15:56:39, so the
  15:52 send and the 15:55 retry are unaffected. The case it closes: a decide that hangs until about 15:57,
  followed by a timer firing queued behind it, would otherwise send a partial
  batch cut off at 15:58. Such a refusal is recorded as `budget_short` in
  `send.json`. verify FAILs the day when time was the only obstacle; a halt, dry run
  or arming refusal on the same send explains the day instead. (Since 2026-10-09
  every refusal but those three is a FAIL: "As built (2026-10-09)".)
- **Scoring is unchanged:** verify marks every fill against the official closing
  print (`fill_vs_auction_bp`), beside the shadow benchmark. Revisit after a week.
- **Revert:** delete the `execution` block; the runner sends `cls` exactly as before.

## As built (2026-10-29): gate 5's missing-NAV hold, dark

The team lead approved it on 2026-10-29. On 2026-10-22 PDO's NAV for the as-of
2026-10-21 never reached the panel. fetch_daily exited 4 on every slot, because
its CEFConnect fallback has failed with JSONDecodeError since 2026-10-21. Gate 5
then refused all 13 names, and the book missed the day. The why of each choice is
in `quantt/session/gate.py` `missing_nav_hold`.

- **Off by default in code; ON in the book json since 2026-10-29** (team lead: `hold`,
  `missing_nav_max_sessions` 2). The book json key is `data.missing_nav`, and `hold` is its only
  value. With the key absent, `Deps.missing_nav` is None and the session is bd87144's
  (release-20261029-1), byte for byte. The proof is hashes computed by bd87144's code
  on the real panel and on a synthetic panel that never skips: a complete day, and a
  day with one as-of NAV missing at the evening decide and at the final check
  (`quantt/session/tests/test_missing_nav_hold.py`).
- **Evening and morning, before the final check** (close − 90 min, the stale-NAV
  gate's `final_check_at`). A name whose NAV is not dated the as-of date refuses the
  decide with today's gate-5 refusals, plus one line saying it is deferred. Nothing is
  decided or marked, and the next slot re-runs the refresh. A NAV that lands in the
  meantime is simply used.
- **From the final check.** Each such name is held. It keeps its current shares, gets
  no order, leaves the cross-section and is never targeted to zero. The other names
  decide. The hold goes to the sleeve as the stale-NAV gate's `nav_hold` extra. A held
  name has no paired row on the date, so the sleeve counts it toward `min_names`: if
  the holds leave too few eligible names, the whole book holds. They never cause the
  flatten. The stale-NAV gate also runs on that exit-4 refresh.
- **Still refused, at any hour, as today.** A missing or stale close; a name with no
  NAV at all; a refresh failure other than exit 4; and more missing NAVs than
  `gate.max_missing_nav_holds` = n − `min_names`, read from the frozen spec. Past that
  limit fewer than `min_names` names would have a NAV, the sleeve could trade none of
  them on its signal, and so it is a broken feed, not a late NAV.
- **Short of `min_names` after the sleeve's own exclusions** (release-check of 6d42f4f).
  The n − `min_names` cap counts only the names without a NAV. Holds plus names the
  sleeve leaves out (illiquid, ADV unmeasured, NAV stale, no z-score, no panel) can still
  leave fewer than `min_names` names eligible on their signal. The sleeve would then hold
  the whole book, the plan would read NOTHING_TO_SEND, and the day would be marked DONE.
  Instead the day is **refused** as without the key, naming the held funds, the eligible
  count and each exclusion. The count is the sleeve's own `min_names` count, carried in a
  structured tag on its targets (`cef_discount._tag_short`); the runner never parses a
  reason string. The stale-NAV gate's own holds keep their ruled whole-book hold.
- **The age limit (team lead 2026-10-29, a policy).** A fund may be held for at most
  `data.missing_nav_max_sessions` consecutive sessions: 2. This is the book json's value,
  not a code literal, and it is required when the hold is on. It was meant to be derived
  from how long the vendor's NAV gaps last, but prod's NAV panel (copy of 2026-10-28) shows
  no gap in 12 months. The vendor backfills dates, so a late NAV survives only as a
  repeated value. Two sessions were chosen because PDO's 10-22 gap was one session long,
  so a late NAV can land the next day. The limit is to be reviewed against the live gaps
  in the run records' `nav_dates`.
  At the final check after that limit, if the fund's NAV is still not dated as-of, the day
  is **refused** exactly as without the key, with one line naming the fund and its count.
  The count is re-read at each final check from the prior sessions' plan.json
  (`run.missing_nav_streaks`). A dated NAV resets it. A record that is missing,
  unreadable or silent about the fund refuses the day; it is never counted as zero.
- **Records.** plan.json and the run record carry `missing_nav`: the action (`none`,
  `deferred`, `held` or `refused`), why, each missing name's last NAV date, the limit,
  each name's prior count (`held_before`), and what was held. The log prints one
  `MISSING NAV` line.
- **Single-sleeve book only.** A combined book holds whole sleeves
  (`gate.gate_data_by_sleeve`). The key with a combined book fails the session,
  naming it.
- **Revert:** delete both keys.

## As built (2026-10-28): the multi-sleeve combiner, dark

The team lead approved building it on 2026-10-28 ("build the combiner, decide
placement after"). One Alpaca account takes one order per symbol (CLAUDE.md
landmine 2), and the agent lab must net into C4's targets in the account they
share (`docs/SYSTEM.md` §5, 2026-10-28). The design is the portfolio framework's
phase C (`results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md` §2.10, §7). The why of
each choice is in `quantt/session/combine.py`'s docstring.

- **Off by default.** It is on only when every enabled entry of the book json's
  `sleeves[]` carries `risk_budget`. The released json carries none, so
  `Deps.sleeves` is None and the session is de6e9c5's, byte for byte. That is
  proved against hashes computed by de6e9c5's code on the real panel and on a
  synthetic panel that never skips (`quantt/session/tests/test_combine_noop.py`).
  With no budget, the json must name exactly one enabled sleeve whose spec is the
  book's, else the run fails before it starts.
- **Sizing.** sleeve_nav = equity × risk_budget × σ_book / σ_sleeve. σ_book is the
  book spec's `frozen.vol_target_annual`, so the budget is the sleeve's share of the
  book's vol target. The budgets are inputs from the allocation analysis.
- **Netting.** The sleeves' whole-share targets are summed per symbol, and `decide`
  runs once on the net: one order per symbol, flips and shortability on the net.
  **Enabled sleeves may not share a symbol** until per-sleeve sub-ledgers exist
  (release-check of 00ec423). `load_sleeves` and `combine.decide` refuse an
  overlap, naming the symbols. Accepted, the shared symbol would net from flat on
  day one, and every later session would FAIL on the position that built. The
  cross-sleeve arithmetic is kept behind `combine.SHARED_SYMBOLS_ALLOWED` (False).
- **Book-level limits.** The book spec's `max_gross_stress`, applied once to the
  netted orders by `fit_to_buying_power` and gate 8. Its value was derived for the
  13 alone and must be re-derived on the combined book before a second sleeve is
  enabled (framework §2.7).
- **Gates.** Gate 9 and the send read the union of the enabled sleeves' universes.
  Gate 5 runs per sleeve (`gate.gate_data_by_sleeve`). Before the final check
  (close − 90 min) a failing sleeve refuses the decide, as today. From the final
  check it is held at its shares and the rest decide. fetch_daily's exit 4 is
  attributed by that per-name check, and every other refresh failure stays
  book-wide. The stale-NAV gate's holds go to the sleeve that owns each name; a
  deferral stays book-wide (one plan per day). On a combined book the stale-NAV
  gate also runs when the refresh exits 4, over every enabled sleeve's names, and
  its record says so (`refresh_exit`). Exit 4 is the case in which some sleeves
  decide; 00ec423 skipped the gate there and sent them unchecked. That is safe
  because the gate never acts on a name with no NAV dated as-of; that name is
  gate 5's.
- **Attribution.** plan.json `combine`: each sleeve's spec, budget, sleeve_nav,
  status, and per symbol its current and target shares. Verify, score and TCA do
  not split P&L by sleeve yet.
- **Not built:** per-sleeve sub-ledgers (a held position in a symbol two enabled
  sleeves trade fails the session, naming it), a per-sleeve opening session,
  per-sleeve panels (C4 plan row 6A), sleeve `state` and sleeve-scoped halts
  (framework §3.5).

## As built (2026-10-28): the corporate-action gate, `halt` on paper

**The defect.** Alpaca paper processes no corporate actions: no splits and no
mergers (`docs/REFERENCES.md` §12pc). IBKR paper processes none either, so paper
stays on Alpaca (`docs/SYSTEM.md` §5, 2026-10-28). The runner reads broker share
counts as they are and prices them at the as-of close. Take a held fund that
reverse-splits 1:4. Paper keeps the old count while the price is four times
higher, so the plan's dollar exposure, equity and the orders sent to reach
target are all wrong. Nothing handled this. The team lead ruled a HALT guard
(2026-10-28).

**What runs.** `quantt/session/corp_actions.py` is step 3b of every DECIDE, after
the decision and before the gate's clock read. It runs again at the late-market
SEND, on fresh reads, because Alpaca can list an action effective today after the
evening decide.
`AlpacaClient.corporate_actions` reads the thirteen non-dividend types: reverse,
forward and unit splits, stock dividends, spin-offs, cash, stock and
stock-and-cash mergers, redemptions, name changes, worthless removals,
reorganizations and partial calls. The request sends no `symbols` filter,
because the reference does not say which field it matches on a merger. Every
symbol field is matched client-side, so the acquirer and the acquiree are both
mapped. It asks for `data_quality=all`, which includes the early, unprocessed
records (2026-10-29). A reorganization leg with no ticker but a CUSIP names
nobody. On twelve months of the real feed, 29 reorganizations carried such legs,
and the first version of the parser raised on them (`docs/REFERENCES.md` §12pc).

**The windows** (ET calendar dates, inclusive; the module docstring has the
alignment in full):

| window | for | why |
|---|---|---|
| long, held name: from the earlier of the date its shares were last set and the as-of date, through the session date | a market-date match in any role but a merger acquirer: acquiree, every split type, stock dividend, spin-off, reorganization, name change, redemption, worthless removal, partial call | paper never adjusts a count, so an action after the shares were last set leaves them on the wrong basis until the name trades again. A name change stays long because paper may leave the position under the old symbol |
| long, target-only name: the as-of date through the session date | the same | every order is priced at the as-of close and fills on the session date |
| short: after the as-of date, through the session date, `(as-of, session]` (team lead 2026-10-29) | a merger acquirer (all three merger types) and a reorganization's allocated leg, both on the **market date only**; and any other match through the process date alone | an acquirer's count does not change, only its price on the terms; the allocated security's holders likewise keep their count (re-review 2026-10-29, flagged to the team lead). The market date only, because the feed lists each real MQY merger twice, processed 02-23 and 02-24, and paper never applies a process date. The feed also backfills old actions years later (a 2016 split processed in 2025), so a process date by itself matters only on the day a broker applies it |

"Last set" is the NYSE trading day before the ET submission date of the latest
order in that name that filled anything. The order comes from the closed-order
history step 2 already reads. That day's close is the latest the order can have
been sized on. A late-market order submitted Monday at 15:52 ET was sized on
Friday's close, so an action effective that Saturday is inside the window
(re-review 2026-10-29). So in both modes the window can only start early. Every role blocks, each on
its own window. A short-window match blocks ONE session: the one whose window
holds its date. The next session's as-of is that date, so it is outside, and the
match clears by itself. By then the as-of close and the counts are post-event and
consistent, so there is nothing left to protect. The long window keeps the as-of
inside, because there the count is wrong.

**The query** asks for process dates from 31 days before the earliest window to
731 days after the session. The API filters on the process date. On the real
feed, process dates ran from 4 days before an action's market date to 3,358 days
after it (`corp_actions.py`, the constants' comment; §12pc).

**On a combined book** (the multi-sleeve combiner above, when a book json turns it
on), the gate's targets are the netted decision's non-zero targets **and** every
sleeve's own (`run._plan_targets`, from plan.json's `combine`). A name two sleeves
net to zero still blocks. Today enabled sleeves may not share a symbol, so the net
equals the owning sleeve's target, but the gate does not rely on that switch. The
held names are still the broker's positions. The decide and the send both run the
gate on that path (`quantt/session/tests/test_corp_actions.py`, the `combined`
tests).

A malformed `combine` record makes the session FAIL (exit 20). It does not
produce the gate's UNMEASURED: `_plan_targets` reads the record as an argument,
before the gate's own error handling, so the error ends the session as any
unexpected error does. That still fails closed, since nothing is sent. Only the
runner writes `combine`: `combine.decide` builds it in-process at decide, and
the send reads it back from that run's plan.json (third review, 2026-10-29;
no code change).

**Modes** (`ops/books/cef_discount_book.json`, `"corporate_actions": {"mode": ...}`;
absent = no gate, today's behaviour, `run.corporate_actions_for`):

- **`report`.** Records the result in plan.json, the run record and send.json,
  prints it, and sends anyway. A read that fails is recorded as UNMEASURED, never
  as clear. With a blocking event it sends the same orders as the gate absent,
  and plan.json is identical once `corporate_actions` is removed
  (`quantt/session/tests/test_corp_actions.py`).
- **`halt`** (set). A blocking event is a gate-5 `data` refusal naming the
  symbol, its role, the type, the id, the dates and the window: exit 11 REFUSED,
  nothing sent. A failed or unparseable read refuses too and names the error. So
  does a held name the order history cannot date.

**Verify.** A refused day reads `MISSED: ... [data] corporate-action gate ...`, a
FAIL. It is not a deliberate `halt`. The book should have traded and could not,
and a person has to look.

**What clears it.** A short-window match clears by itself once the as-of passes
it. A long-window match does not clear by itself. While the gate refuses,
nothing trades, so the event stays inside the window. It clears in one of two
ways. One is a person's order in the name, through the team lead (CLAUDE.md
order-path rule 1). It must be submitted on the SECOND trading day after the
event's latest date or later. An order submitted on the first trading day after
is sized on the event's own close, and the inclusive window start keeps the
halt on. A reverse split ex Wednesday 10-07 is not cleared by a Thursday 10-08
order, and is cleared by a Friday 10-09 one. The start stays inclusive so that
a late-listed action dated on an ordinary fill's sizing close is still flagged
(third review, 2026-10-29). The other way is for the team lead to set the mode
to `report` for the sessions that should go. No per-event acknowledgement was built. `docs/RUNBOOK.md`,
"Corporate-action halt", is the procedure, including the phantom P&L that paper
keeps.

**Latency at the send.** The gate adds at least two GETs to the SEND phase: the
closed-order history and the corporate-action pages. Both come before the gate's
clock read. One GET that exhausts its retries takes about 250 s:
- five attempts at the 10 s connect and 30 s read timeouts, 200 s;
- the backoffs 2 + 5 + 15 + 30, 52 s;
- `alpaca.GET_BACKOFF_S` and `TIMEOUT_S` hold the constants.

The late window is 360 s (15:52–15:58 ET), and a 13-order set needs 81 s of it
(`gate.send_budget_s`). So one such stall at the 15:52 send leaves too little
time. The outcome is a refusal, never a partial or late batch. Under `halt` a
failed read refuses. A slow read that succeeds puts the gate's clock read late,
and the late-clock or send-budget gate refuses before STARTED. Either way verify
reads a MISSED FAIL. Under `report` the same time is spent although the result
blocks nothing. Normal reads take a fraction of a second; the slowest measured
order cycle, a clock GET and a POST, was 0.259 s (`gate.py`). No code was
changed for this (review 2026-10-29).

**Not covered.** Rights distributions, cash dividends and capital-gains
distributions change no share count. An action Alpaca never lists is not seen
either: its merger coverage is mostly effective actions (§12p). A split inside
the signal's own lookback is a panel-quality question for gates 5 and 1b.

## As built (2026-10-19): the drawdown check, HALVE/KILL in `report` mode

**The defect.** The frozen spec carries `risk.halve_drawdown` and
`risk.kill_drawdown`, and the standing decision is to arm HALVE/KILL on
broker-confirmed NAV (`docs/SYSTEM.md` §5, 2026-09-08). On the Alpaca path no code
read either line, and the runner never called the sleeve's `risk_check`, which
writes the lines as literals and returns OK on an exception
(`results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md` §1 item 4 and §3.4; re-verified by
grep at main `832aeaa` on 2026-10-19).

**The rule (team lead, 2026-10-19): report mode first.**
`quantt/session/drawdown.py` runs as step 2b of every DECIDE, after the account
read and before the sleeve. The late-market SEND phase does not run it: the plan
it sends already carries the record.

- **Series.** `<state>/eod_equity.csv`: Alpaca's end-of-day portfolio history
  (timeframe 1D), which the team lead ruled on 2026-10-19 is the **official** daily
  P&L. The collector writes it and backfills it from 2026-09-28. The check reads
  `date` and `equity` **by header name** and nothing else, so an empty `change_usd`
  or an added column changes nothing.
  - Absent or unreadable: **UNMEASURED, naming the file.** There is never a
    fallback to `equity.csv`. Those rows are after-hours account snapshots, and a
    snapshot can set a high-water mark the book never closed at.
  - The snapshot reading is still shown, as a second labelled line and a
    `snapshot` record. It never changes the status.
- **Measure.** HWM = the largest `equity` on rows dated on or before the as-of
  date; drawdown = 1 − newest ÷ HWM. Rows after the as-of are never read
  (asserted). The newest row must be the as-of date. If it is not, the status is
  UNMEASURED, and the figures are recorded under their own date. Whether the EOD
  row exists by the 22:00 ET evening decide is [U]; report mode measures it.
- **Lines.** `risk.halve_drawdown` and `risk.kill_drawdown`, read from the spec
  that `run.load_spec` loaded, never a literal. Each must be a fraction in (0, 1),
  with halve below kill. A percent written where a fraction belongs is refused,
  not rescaled (the `book_drawdown_suspend_pct` units trap).
- **Status.** KILL at or past the kill line, HALVE at or past the halve line, else
  OK; UNMEASURED when any of the above fails. The record also gives the worst
  drawdown in the series and the first date each line was crossed, which is what
  a sticky acting mode would still be holding.

**Modes** (`ops/books/cef_discount_book.json`, `"risk": {"drawdown": <mode>}`;
absent means off, and the session runs exactly as before):

- `report` **(the release setting)** records the status, the reading and what an
  acting mode **would** do in plan.json and the run record (`drawdown`), and
  prints one `DRAWDOWN` line plus the labelled snapshot line. It changes nothing.
  - The orders, the `plan_sha` and plan.json are those of a check-off session,
    byte for byte, apart from `drawdown`. This is proved on the live spec, the real
    sleeve and the real panel, with the series at OK, HALVE-deep, KILL-deep and
    absent (`quantt/session/tests/test_drawdown.py`).
  - An unexpected error is recorded as UNMEASURED with its type and never stops
    the session.
- **An acting mode is not built.** Setting anything but `report` raises
  (`run.drawdown_for`), so the book json cannot claim an armed HALVE/KILL that
  nothing enforces.

**What an acting mode would do** (recorded each session as `would_on`; a later
ruling):

- **HALVE:** size every sleeve on half its budget, so the vol target halves.
  **Sticky**: it holds until the team lead records a review, never lifted
  automatically on recovery (framework §3.4).
- **KILL:** flatten every sleeve through the normal order path, every gate
  applying. Then write `ops/HALT_cef.md`; the halt must follow the flatten's send,
  or the halt gate refuses the flatten. The team lead restarts.
- **UNMEASURED:** refuse the decide, as a named `risk` refusal; verify reads the
  day as MISSED. Why it should fail closed: `drawdown.py` docstring. A survival stop
  that fails open is the defect being replaced, and a missed day is already loud.
  The alternative for the ruling is a close-only day.
- **Before real money:** the HWM is not flow-adjusted. Alpaca paper has no
  deposits or withdrawals; a live account does.

**Records (H14).** `plan.json` and `runs/<stamp>-run.json` carry `drawdown`: the
mode, the file and series label, the as-of, the levels and their spec source, the
status (and `why` when UNMEASURED), the reading (rows, first and last date,
equity, HWM and its date, drawdown, worst drawdown and its date, first crossing
of each line), `would_on`, `acted: false` and the snapshot. Nothing else is
written.

## As built (2026-10-19): the P&L of record is Alpaca's end-of-day history

Team lead, 2026-10-19 (`docs/SYSTEM.md` §5): Alpaca's end-of-day portfolio
history is the paper book's official daily P&L. Until then verify's line called
the 17:30 ET `equity − last_equity` reading "(official, gross)". That reading is
marked after the close. On the four days compared on 2026-10-19 it disagreed
with the history every time, while the history agreed with the auction-marked
score (`docs/REFERENCES.md` §12an). Nothing on the order path changed: `run.py`,
the gates, decide, the NAV gate and the scheduler units are untouched.

- **Client** (`AlpacaClient.eod_equity_history`): one GET,
  `period=<n>M&timeframe=1D`, the shape read live. Every daily stamp must be
  exactly 00:00 UTC, the only stamp the live read and Alpaca's own example
  show, and in New York time (the evening before) it must fall on a trading
  day by `/v2/calendar`. Otherwise the call raises naming it. Together these
  stop a change of stamping convention, or an intraday reading, from being
  filed under the wrong date. **If Alpaca's winter stamps are not 00:00 UTC**
  (first one: the 2026-11-02 session), the client raises and the official
  figure stays PENDING until a person looks; it is never put on a wrong date.
  Days before the account was funded come back as equity 0 and are dropped
  by name. A zero after funding raises.
- **Final or not.** Alpaca documents neither when a day's point appears nor
  whether it changes later. It stamped the 2026-10-16 close at 20:00 ET. So a
  point whose stamp is still in the future when it is read is not used yet.
- **Verify** writes `official +X USD (Alpaca EOD history, gross)` when D's
  point and the previous session's are both in and stamped before the read.
  Otherwise it writes `official PENDING (<why>)`. Then comes
  `snapshot HH:MM ET +Y USD (gross)` (the old figure, relabelled), then the
  auction mark, unchanged. Nothing stands in for a PENDING figure. **PASS and
  FAIL do not move with it**, and an unreadable history is a PENDING reason,
  not a FAIL. `reconcile.json` keeps `official_eod` (the figure or the reason,
  and the points read) and `snapshot`. `scores.csv` gains no column: it is
  append-only with a fixed header that other code reads by name, and its
  `alpaca_equity_change_usd` is the snapshot.
- **The series of record** is `<state>/eod_equity.csv`, written by the collector's
  step `eod_equity`. **A contract**: another branch and a HALVE/KILL monitor
  read it by name. Columns are `date` (ISO session date, ET), `equity` (USD),
  `change_usd` (equity minus the previous session's row; empty for the first
  funded session and wherever the previous session is missing, never an
  invented baseline), then `read_at_utc`. Each write rewrites every funded
  session from 2026-09-28, atomically. So the first run after install
  backfills on its own. A changed value is rewritten, with a
  `DATA EOD_REVISED <date> equity <old> -> <new>` line in `data.log` and a
  report flag.
- **When the collector reads it**: every 30-minute slot until D's point is in
  the file and stamped before the read, then not again until the next data
  day, whose read re-checks every earlier day. Until D's point lands the day
  reads `INCOMPLETE eod_equity`, as it reads `INCOMPLETE prices_nav` until
  the evening NAVs arrive.

## As built (2026-10-13): the stale-NAV gate, in `report` mode first

**The defect.** Yahoo serves a NAV row dated D that still carries an older NAV, and
corrects it later. Gate 5 and `fetch_daily --require-asof` check the row's date, so
they pass it. On the laptop's paper sessions 28 of 73 checkable name-days were
decided on NAV(D−1), and 11 submitted orders were sized on one
(`results/cef/LIVE_NAV_QUALITY_2026-10-12.md` §5, `docs/REFERENCES.md` §12n).

**The rule (team lead, 2026-10-13, redesigned the same day).** The first version
("Use CEFConnect, else drop") was replayed. CEFConnect had no row for D at every
measured evening decide, so it would have dropped every suspect name, and on
2026-10-05 the drops would have flattened the whole book (`docs/REFERENCES.md` §12s).
The rule now:

- **Trigger.** The panel's NAV(D) equals, to the cent, its previous NAV row, **or**
  CEFConnect's NAV for D−1 (the previous NYSE day) when CEFConnect has that row. The
  second catches the reviewer's PDI case: 09-25 was captured as 15.06 against a 09-24
  row of 15.12, which was itself Yahoo's stale copy. 15.06 is CEFConnect's 09-24 NAV;
  the true 09-25 NAV is 15.10.
- **Resolution.** CEFConnect has D and it differs by more than half a cent: its value
  replaces the panel row through fetch_daily's logged fallback (`nav_fallback_log.csv`,
  source `cefconnect_stale_copy`). CEFConnect has D and it agrees: the row is kept.
- **Unverified** (no row for D, or an error, which is named). Never dropped.
  - Before the **final check**, the decide is **deferred**. The final check is the
    session's calendar close minus 90 minutes, on the session date: 14:30 ET, or 11:30 ET
    on a 13:00 close.
  - From the final check, a name still unverified **keeps its current shares**: no
    order in it. It leaves the cross-section and is never targeted to zero.
  - If the holds leave fewer than `min_names` eligible names, the **whole book holds**
    for the day: no order at all. The holds never trigger the sleeve's FLAT-everything
    `min_names` rule.

**Where it sits.**

- `quantt/session/nav_gate.py` runs as step 1b of `quantt/session/run.py`, after the
  refresh and before anything reads the panel. It reads CEFConnect once per deployed
  name, for D−1 and D together (`fetch_daily._cefconnect_navs`). In `on` mode it holds
  fetch_daily's panel lock from its read to its write.
- Holds reach the sleeve as `extras["nav_hold"] = {"asof", "names"}`
  (`src/deploy/sleeves/cef_discount.py` `_nav_hold`). Held names stay out of the band
  and the sleeve's gross cap, because their shares are fixed. Their gross is judged with
  the rest of the book by gate 8 and the send-time fit.
- With the extra absent, the sleeve's targets are byte-identical to the code before the
  gate: 56 panel dates, flat and held books.
- After the sleeve has read the panel, `PanelGate.still_holds` checks that it read the
  panel the gate certified, or the session FAILs.

**The deferral and the order path** (`run.py` docstring, "DEFERRAL AND THE ORDER
PATH"). A deferral is a gate-5 `data` refusal at DECIDE that names the names. Nothing
else was built for it.

- **One plan per day.** A refused plan is not `decided`: no `DECIDED` marker is written,
  and the next run overwrites plan.json. The morning backstop's slots (06:00–15:15 ET)
  re-run refresh and gate, and re-read CEFConnect. The first slot that verifies every
  name decides. If none does, the first slot at or after the final check decides,
  holding what is still unverified. A decided plan is never re-decided.
- **STARTED and idempotency (rule 2).** Untouched. A deferral happens before any order,
  and `done_reason` and gate 6 still stop a second set.
- **Approval.** A refused plan cannot be approved or sent: `approve` and the send both
  need a decided plan. APPROVED and `--approve` bind to the morning plan's `plan_sha`.
  AUTO_ARMED sends whatever is decided, as now.
- **Dry run.** A deferral is REFUSED, never DRY, so it can never write `DRY_DONE` and
  leave the morning slots idle.
- **Late-market send (rule 3, the paper exception).** The window is unchanged. The final
  check sits 82 minutes before it opens, and the 15:00 slot is left to retry a final
  decide that failed. In `cls` mode the morning slots decide and send before the cls
  cutoff.
- **Verify.** A day still deferred at the send reads `MISSED: ... [data] stale-NAV gate:
  ... deferred`: a FAIL, never a PASS.

**Modes** (`ops/books/cef_discount_book.json`, `"data": {"stale_nav": <mode>}`; absent
means off, and the session runs exactly as before):

- `report` **(the release setting)** records every check and what `on` *would* do:
  replace, keep, defer or hold. It changes nothing.
  - The orders, the `plan_sha` and plan.json are those of a gate-off session apart from
    the added `nav_gate`. This is proved on the live spec, the real sleeve and the real
    panel (`quantt/session/tests/test_nav_gate.py`).
  - An error is recorded as UNMEASURED and never stops the session.
- `on` applies the rule. Team lead: `on` after a measured week of `report`. Turning it
  on is a reviewed edit of that key, and so is the revert (delete the `data` block).

**Records (H14).** These are measured at run time and never keyed on a document.

- `plan.json` and the run record carry `nav_gate`: the mode, whether this was the final
  check, `would_defer` and `deferred`. For every deployed name they give the panel
  NAV(D), its previous row, CEFConnect's D−1 and D or the error, the trigger, the
  verdict and the action.
- `<state>/nav_gate.csv` gets one row per triggered name per decide, or one
  `no_trigger` row.
- **Record first** (2026-10-14). Under `on` that row is written *before* the panel.
  If it cannot be written, the panel is not touched and the session stops, naming
  the file.
- **A bad record file.** An empty `nav_gate.csv` or `cefconnect_arrival.csv`, or one
  with another header, is moved aside whole as `<name>.<UTC stamp>.unreadable`,
  never written into. For `nav_gate.csv` that run is UNMEASURED in `report` mode and
  stopped under `on`. The collector names both files in its detail and starts a new
  file in the same slot.
- The session log prints one `NAV GATE` line, plus one line per triggered name.

**The collector.**

- A panel NAV(D) equal to its previous NAV while CEFConnect has no row for D is a flag,
  `nav_repeat_unverified`, not a gap.
- A new watch step, `cefconnect_arrival`, polls CEFConnect each slot until every
  deployed name's row for D has appeared. It logs each row's arrival, bracketed between
  the last poll without it and the first with it, to `<state>/cefconnect_arrival.csv`.
- It keeps the collector from idling but never makes the day INCOMPLETE. Why: when
  CEFConnect publishes D decides how often a name is held, and that rests on three
  readings.

**The replay, under `on`** (report only: `python3 scripts/data/nav_gate_replay.py
--state-dir <laptop state>`; tables in `results/cef/nav_gate_replay/`; sources in
`docs/REFERENCES.md` §12s).

- **Every measured evening deferred.** All five laptop evening decides whose CEFConnect
  state the collector measured would have deferred to the morning.
- **At the final check, best case** (CEFConnect has D by then): nothing is held, stale
  copies are replaced and genuine repeats kept. That is what the one decide made with
  CEFConnect present would have done: 2026-10-01, 12:00 ET, 5 replaced and 3 kept.
- **At the final check, worst case** (CEFConnect still has no row for D): every
  triggered name keeps its shares.
  - 2026-10-05: 9 names held, 4 left eligible, so the whole book holds that day.
  - 2026-09-30 and 2026-10-02: the same is possible.
- **No date flattens the book.**
- On the local panel as captured on 2026-09-28, the second trigger catches PDI and
  replaces it with 15.10. DSL (11.11 = 11.11) is replaced with 11.10, and BIT is a
  genuine repeat.

## As built (2026-10-13): the re-fit keeps the most that fits; a send it empties is MISSED

The two non-blocking follow-ups of the 2026-10-11 release-check of
`release-20261011-1`. Neither changes a limit, a gate or what counts as a fit.

**B. The re-fit cut far more than it needed** (the execution desk's finding).
`run.fit_to_buying_power` searched its four factors on a 0.05 grid refined on
0.01, ranked first by the post-trade net's distance from the full plan's rounded
to the cent. A grid almost never lands on exact neutrality, so it took whichever
grid point came a few dollars closer, whatever that cost in trade. On the laptop's
recorded 2026-10-07 plan sent on equity 0.5% lower (the reviewer's case, a
hypothetical dip), it kept **72.0%** of the traded notional. The same objectives,
in the same order (every limit; the post-trade net closest to the full plan's; then
the most traded), are now solved exactly: with every order wholly opening or wholly
reducing, every limit is linear in each factor, so the search is a linear program in
two variables (`run._fit_cuts`). Same case: **98.7%** in whole shares, $4.61 from
the full plan's net (the grid's was $4.98 off). Reproducer: `test_fit.py`
`test_the_2026_10_07_plan_after_a_half_percent_dip_keeps_what_fits`, which carries
that plan. It failed safe before (never above a limit, never a refusal, never the
wrong side), so this is uptime, not safety.

What did not change, and is tested (`quantt/session/tests/test_fit.py`, seeded
synthetic plans checked against the released fit, kept verbatim as a test
reference, and against scipy's linear program as an independent solver): every
fitted plan passes gate 8 term for term; each order stays wholly opening or wholly
reducing, on its side, no larger than the plan's, so no name ends past the plan or
flips; whole shares round the safe way (openings down, reductions up, capped);
the stress cap is read as the gate reads it; a plan that does not add gross is not
scaled for it. Measured 2026-10-13 on 2,400 synthetic draws (`test_fit._draw` on
seeds 20000–22399, both fits; 1,741 draws where the fit binds and something fits):
gate 8 refused none of the new fits, and the mean share kept rose from 48.3% to
60.0%. In 1,738 of the 1,741 the new fit kept at least as much as the grid. The
other 3 are the 2026-10-07 neutrality rule at work: buying power binds on a small
opening buy, and the new fit trims a large reduction by the same dollars to hold the
full plan's net. The grid was too coarse to do that (0.01 of a 5,773-share order is
58 shares), so it ended $74–$1,314 further from that net, and kept up to 0.37 points
more. The committed test allows exactly that exception, and only where each dollar
of trade given up buys at least a dollar of neutrality (to within one share per
order). **For the team lead:** that is the rule as written (net first, then trade);
say if trade should come first when the difference is that small.

Three details changed: `kept` (recorded as `bp_scale.factor` and
`bp_scale_at_send.kept`) is now the share the WHOLE-SHARE orders trade, not the
fractional plan's; the fit sums the post-trade gross in the gate's own order, so its
check and gate 8's agree to the last bit; and a `PRE-FLIGHT WARNING` that the send
would scale now says to what share. When only trading nothing fits (the book above
the cap, every order adding gross), the plan comes back empty, as the grid's did.

**A. A send the re-fit scaled to nothing read PASS.** With every order scaled to
zero, the send ends `NOTHING_TO_SEND` with no refusal, and verify read the day
"nothing left to send" and passed it. Under the team lead's 2026-10-09 rule
only `DRY_RUN`, arming or a halt explains a no-trade day, so verify now reads it as
`MISSED:` naming the limit (`verify._fit_emptied`): "the send-time fit to
max_gross_stress ... kept 0 of N order(s)". The same holds when every
order was skipped as unshortable at send (named order by order), and when the
DECIDE-time fit emptied the plan. `send.json` records `bp_scale_at_send` and
`plan.json` records `bp_scale` (`orders_in`, `orders_out`, `binding`) so verify can
tell an emptied plan from one with nothing to do; a `send.json` from before
2026-10-13 that ended `NOTHING_TO_SEND` is still `MISSED:`, saying it records no
reason.

**Left for the team lead.** A send the re-fit empties exits `NOTHING_TO_SEND`, which
writes `DONE`, so the 15:55 retry does not run, even though equity may have
recovered by then. A refusal at 15:52 leaves the retry free. Whether an emptied
send should leave the retry free too is a change to the run path, not made here.

## As built (2026-10-09, amended 2026-10-11): the stress cap, missed days FAIL, the pre-flight

**The incident.** On Friday 2026-10-09 the book did not trade. Gate 8 refused both
the 15:52 send and the 15:55 retry: "projected gross $182,154.75 > max_gross_stress
1.8 x equity $100,666.16". The plan had been decided at 22:00 ET on 2026-10-08,
sized at 1.7994× that evening's equity ($101,229.74), where the sleeve's cap
binds. Equity was 0.56% lower at 15:52, so the same plan was 1.8095× the live
equity. The plan took gross **down**, from $183,413.36 to $182,154.75 at the
as-of closes, and refusing it left the book at 1.83× at that close. The verify
line read `PASS ... no trade: refused at send`. Nobody saw it until the team lead
asked how Friday went. All figures are from the prod VM's `2026-10-09/plan.json`,
`send.json` and `runs/*-run.json`.

**The audit** (`python3 -m ops.replay_exposure <copy of the prod state>`, run
2026-10-09 on all 40 recorded runs, 38 replayable). The old rule passed 2026-10-07
by $168 and 2026-10-08 by $765, both only because equity rose between the
evening decide and the send. It refused 2026-10-09 by $956 at 15:52 and $702 at
15:55. On every day the cap binds, the old rule refused whenever equity fell
before 15:52. The new code refuses none of the 38 runs. The only other
refusals of this kind on record, 2026-10-06's 21 buying-power refusals, were
already fixed on 2026-10-07; the replay confirms the new code passes them too.

What changed (team lead's go, 2026-10-09):

- **The stress cap is judged on the lower of the equity the plan was sized on
  and live equity** (`gate.stress_breach`). The send reads the plan's own
  `equity`; a plan without one is refused, never assumed. *Amended 2026-10-11
  (team lead's ruling, after the release-check review).* As first built on
  2026-10-09 it read the sized equity alone, on the argument that the 0.043×
  between the cap 1.80 and the derived G_stress 1.843 absorbs the movement. Both
  reviewers showed that holds only for a fall of up to 1 − 1.8/1.843 = 2.34%:
  past that, a plan that ADDS gross could go out above 1.843× live equity, with
  only Reg T (2.0×) left to stop it. So a plan that adds gross is held to the cap
  on whichever equity is lower, and with `bp_shortfall = scale` (prod's setting)
  the send's re-fit scales it to fit rather than refusing it. 2026-10-09's plan
  took gross down, so it still passes. Buying power and the overnight Reg T and
  maintenance limits are checked on live numbers, unchanged.
- **A plan that does not add gross always passes the stress cap**, even when the
  book is above it. A ceiling stops the book adding past it; it must never block
  a plan that brings gross down.
- **The re-fit fits the stress cap too** (`fit_to_buying_power`). Scaling
  reductions for neutrality can leave more gross than the plan, so the cap is
  one of its limits, read as the gate reads it. **Whole shares round the safe
  way** (2026-10-11): opening orders down, reducing orders up (capped at the
  order), so the whole-share plan never holds more gross or needs more buying
  power than the fractional plan that passed. Until then every order was
  floored, and both release-check reviewers produced a fitted plan that gate 8
  refused on the very cap it was fitted to. The rounded plan is re-checked. **When nothing fits** (the book
  held now is already past a limit and no scaling fixes it), the plan is
  returned unscaled with the limit named, and the gate refuses it. Until now
  that case raised `TypeError` (`coarse[1]` on `None`): a FAIL with a traceback.
- **A missed day is a FAIL** (`verify.DELIBERATE_GATES`). A no-trade day is
  explained only by a human's choice: `DRY_RUN`, no arming, or a halt. Any other
  refusal, at decide or at send, gives a FAIL line beginning `MISSED:` (and since
  2026-10-13 so does a plan the re-fit or the shortable skip left with nothing to send). It
  exits 1, so it also shows in `systemctl --failed` on the VM, and orient and
  the status line show it red.
- **The evening pre-flight** (`run.preflight_send`). After a plan is decided,
  the decide re-runs the send's exposure path (re-fit, then gate 8) on an
  account whose equity is lower by the worst one-day loss of the book held now
  over the last 252 sessions. That book moves equity until 15:52. The result goes
  into `plan.json` (`preflight`) and the session log, as `PRE-FLIGHT ok`,
  `PRE-FLIGHT WARNING` or `PRE-FLIGHT UNMEASURED`. It decides nothing, and a
  pre-flight that cannot run never stops the plan being saved. Buying power is
  held at its decide-time value. On the book held into 2026-10-12 the worst day
  was $2,074.61 (2.06% of equity) on 2026-03-20, measured on the laptop's panel
  ending 2026-09-28.
- **Orient shows the newest plan** (`ops.prod_state`, `newest plan`): its date,
  status, order count, whether it was sent, and its pre-flight. A WARNING on an
  unsent plan is a PROD caution. Only counts and verdicts leave the VM, never
  positions.

**Left as it was, for the team lead.** The overnight margin checks still refuse
a plan that leaves the book past Reg T even when the plan reduces gross. That
needs equity to fall about 8.5% with gross unchanged (the book was 1.83× at the
2026-10-09 close: equity.csv). The principle above says such a
plan should go. The team lead kept those checks unchanged on 2026-10-09, so the
question is open.

## As built (2026-10-07): buying power, scale-to-fit, fills, TCA

Execution-desk review after the first week (plan: items 3–5).
- **Gate 8 is two checks.** Order-time: opening notional (shorts ×1.03) ≤ Alpaca's
  live `buying_power` -- what Alpaca enforces. Overnight: on the book AFTER the
  plan, Reg T initial margin (50% of gross) ≤ equity, and maintenance at the
  account's live measured ratio (`maintenance_margin / current gross`, 47.8% on
  2026-10-06) ≤ equity. The old `min(buying_power, regt_buying_power)` refused
  2026-10-06's catch-up plan that Alpaca would have accepted.
- **`execution.bp_shortfall = scale`** (absent = refuse): a plan that does not fit
  is scaled with four factors (opening/reducing × buy/sell) that satisfy every
  limit and keep the post-trade net closest to the full plan's, at DECIDE and again
  at SEND on the live account. What goes is always a subset of the decided plan.
  (Searched on a grid until 2026-10-13, solved exactly since: see "As built
  (2026-10-13)".)
- **Fills are polled** to a final state (to close − 30 s) and recorded in
  `orders.jsonl` / `send.json`; unfilled shares are reported, never topped up.
- **`<state>/tca.csv`**, one row per traded day: fill rate, signed slippage vs the
  official close (buy/sell), residual vs the sent orders' targets.
  `scripts/ops/tca_backfill.py` scores past days read-only.
- Slower rebalancing was re-tested (`results/cef/FRONTIER_REPRO_2026-10-07.md`):
  no slower policy matches or beats the live band on the fit period; no trial spent.

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
