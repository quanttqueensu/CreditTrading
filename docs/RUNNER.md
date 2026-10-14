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
| Scoring | Alpaca's fill (official) **and** the official closing-auction print, side by side, gross. **Third line from 2026-10-09** (team lead): auction-marked P&L **plus distributions** on shares held at the start of each ex-date (credited long, charged short), because Alpaca paper credits none. It is scored two sessions late, once the cross-check source has caught up, and written to `distribution_scores.csv`. It never changes the verdict (`quantt/session/dist_score.py`). |

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
          1b. NAV gate  only when the book json sets data.stale_nav (absent: off). A NAV(D)
                        equal to the name's previous NAV is checked against CEFConnect:
                        stale copy -> replaced, genuine repeat -> kept, unverified ->
                        dropped for the day. "As built (2026-10-13)" below.
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
| `quantt/session/nav_gate.py` | The stale-NAV gate (step 1b): finds each NAV(D) that repeats the previous NAV, reads CEFConnect, replaces stale copies in the NAV panel through the logged fallback, names the unverified for the sleeve to drop, records every binding. | Transmits. Decides a target. |
| `quantt/session/verify.py` | Post-close reconcile + dual scoring + the one-line verdict. Read-only against the broker. | Transmits. |
| `src/deploy/sleeves/cef_discount.py` | The strategy. Gains `extras["opening_session"]`: when True the band is skipped (trade to full target); **absent or False is byte-identical to today** (proved by test). Gains `extras["nav_unverified"]` (2026-10-13): names the stale-NAV gate could not verify, dropped on the `max_nav_age_bd` path; absent is byte-identical. | — |
| `quantt/deploy/` | launchd plist templates + an install script for the laptop prod clone + `docs/RUNBOOK.md`. | Stores a credential. |
| `src/data/r2.py` + `scripts/data/` | Research/backtest access to the R2 WRDS mirror. **Never on the live path.** | Is imported by `quantt/`. |

## The gates (all must pass to transmit; each refusal names itself)

1. `DRY_RUN` — transmits only if the environment variable is **exactly `"0"`**. Unset, empty, `1`, anything else → dry. Always wins.
2. **Arming** — transmit additionally needs **either** `--approve <plan_sha>` equal to the sha256 of the freshly recomputed order list (the interactive first session: what was approved is what is sent) **or** the file `<state>/AUTO_ARMED` (created after the team lead's first go).
3. **Halt** — `ops/halt.read_halt(book)` returns a halt → refuse.
4. **Clock** — the session date is a trading day by both calendars and Alpaca's `/v2/clock` is inside the auction's send window: the as-of evening from **19:15 ET** (Alpaca queues `cls` sent after 19:00 into the next auction) to 01:00 ET, or the session day until **15:45 ET** (Alpaca rejects `cls` from 15:50; five minutes of margin). Early-close days: use `/v2/calendar`'s close, minus 10 minutes, cls cutoff per Alpaca docs.
5. **Data** — the refresh exited 0 for the required as-of date. That checks each NAV's *date*, not its value; the stale-NAV gate (step 1b, "As built (2026-10-13)") checks the value when the book turns it on.
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
  UNMEASURED and the day FAIL. It is never substituted.
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

## As built (2026-10-13): the stale-NAV gate, on only when the book json sets it

**The defect.** Yahoo serves a NAV row dated D that still carries D−1's NAV, and
corrects it later. Gate 5 and `fetch_daily --require-asof` check the row's date, so
they pass it. On the laptop's paper sessions 28 of 73 checkable name-days were
decided on NAV(D−1), and 11 submitted orders were sized on one; plans written
20–23 hours after the close still used stale rows
(`results/cef/LIVE_NAV_QUALITY_2026-10-12.md` §5, `docs/REFERENCES.md` §12n).

**The ruling (team lead, 2026-10-13): "Use CEFConnect, else drop."** At decide time,
for each deployed name whose panel NAV for D equals its previous NAV to the cent,
read CEFConnect's daily row for D:

| CEFConnect for D | verdict | action |
|---|---|---|
| present, differs by more than half a cent | stale copy | CEFConnect's value replaces the panel row, through fetch_daily's logged fallback (`data/cef/nav_fallback_log.csv`, source `cefconnect_stale_copy`) |
| present, agrees | genuine repeat | kept |
| no row for D, or unreadable (the error is named) | unverified | the name is dropped for the day |

**Where it sits.** Step 1b of `quantt/session/run.py`, after the refresh and before
anything reads the panel: `quantt/session/nav_gate.py`. It holds fetch_daily's panel
lock from its read to its write. A drop reaches the strategy as
`extras["nav_unverified"] = {"asof", "names"}`, and the sleeve drops those names in
the same eligibility loop as `max_nav_age_bd` (`src/deploy/sleeves/cef_discount.py`
`_nav_unverified`). The signal math is unchanged, and with the extra absent the
sleeve's targets are byte-identical to before (checked on 56 panel dates, flat and
held books, against the previous commit). After the sleeve has read the panel,
`PanelGate.still_holds` checks that it was the panel the gate certified. A fetch in
between (the collector's, every 30 minutes) could write a stale copy back; if one
did, the session FAILs and the next slot retries.

**What a drop does is the sleeve's existing rule.** The name leaves the
cross-section and its target is zero. The band then holds a position inside
`band_width` and trades one outside it to the band edge. If the drops leave fewer
than `min_names` eligible names, the sleeve emits every name FLAT ("cef: only N
eligible names") before the band, and decide turns that into orders that close the
whole book. No gate refuses a plan that only reduces gross. Nothing new was added
for this case.

**Records (H14: measured at run time, never keyed on a document).** `plan.json` and
the run record carry `nav_gate`: the mode, and for every repeat the name, D, the
panel NAV(D), the previous row's date and NAV, CEFConnect's value or `absent` or the
error, the verdict and the action. `<state>/nav_gate.csv` gets one row per repeat
per decide, or one `no_repeat` row, so it counts how often the gate binds. The
session log prints one `NAV GATE` line and one line per repeat.

**Modes** (`ops/books/cef_discount_book.json`, `"data": {"stale_nav": <mode>}`;
absent = off, the session exactly as before):

- `cefconnect_else_drop` is the ruling above.
- `report` runs the same checks and writes the same records, and acts on none of
  them: no panel write, no drop. An error is recorded as UNMEASURED and never
  stops the session. In `cefconnect_else_drop` an error that is not a CEFConnect
  read error FAILs the session.

Enabling is one reviewed edit of the book json (`/spec-change` covers
`ops/books/`), with a `_stale_nav_note`. REVERT: delete the `data` block.

**The collector** flags `nav_repeat_unverified` for a name whose panel NAV(D)
equals its previous NAV while CEFConnect has no row for D. Until now that was a
gap, and at ~21:40 ET it was a gap on nearly every evening
(`quantt/collect/collect.py` `step_nav_crosscheck`). It is report only, like
every collector flag.

**The replay** (report only; `python3 scripts/data/nav_gate_replay.py --state-dir
<laptop state>`, tables in `results/cef/nav_gate_replay/`). It applies the gate's
rule to the laptop's recorded decides, as-of 2026-09-28 → 2026-10-07. The NAV each
decide used comes from inverting its printed z. CEFConnect's state comes from the
collector's checks, and CEFConnect as served on 2026-10-13. Every evening decide
whose CEFConnect state the collector measured, five of them, found **no CEFConnect
row for D**. So under the drop rule every repeat would have been dropped: 2–9
identified repeats an evening, and up to 11 counting names whose decide-time NAV
the printed z cannot identify. On 2026-09-30 that may already have left fewer than
`min_names`. On 2026-10-05, decided at 00:00 ET, that is 9 names (8 stale
copies and 1 genuine repeat), leaving 4 eligible. That is below `min_names`, so the
book would have been flattened. On 2026-10-06 it leaves 6–7 and cuts JFR, PFN and
PHK, held outside the band, to the band edge. The one decide made when CEFConnect
had the row (2026-10-01, at 12:00 ET the next day) would have replaced 5 stale
copies, kept 3 genuine repeats and dropped nothing.

**Not built, proposed:** at the evening decide, *defer* an unverified name rather
than drop it. Decide in the morning backstop (06:00–15:15 ET), once CEFConnect has
the row, and drop only if it still has none by the last backstop slot.
CEFConnect's publication time is [U]. It had D's row by 11:41 ET on D+1 (2026-10-01),
not yet at 00:10 ET (2026-10-05), and Friday's row was still missing at 09:40 ET on
Saturday (2026-10-02).

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
