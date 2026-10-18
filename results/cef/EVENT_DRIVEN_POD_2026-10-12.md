# The event-driven pod: architecture, event trades, institutional deployment, and where data, ML and RL can add edge — 2026-10-12

**The question** (team lead, 2026-10-12): *"How can we make this pod event
driven? And expand our existing strategy (ideate)."* Then: *"Put this in a md file
for our research to get on to later, outline all of this in great detail and think
outside the box for making this deployable in our books institutionally. Also think
about how we can use data analysis, reinforcement learning and ML to improve our
edge."*

> **Overtaken, 2026-10-13.** Two items below were settled the same day, in
> another session, before this note was committed:
>
> - **The SEC user-agent** (§1 point 3, §3, §9.1) was supplied by the team lead
>   on 2026-10-12. It is read from `config/.env` (`SEC_USER_AGENT`), never
>   printed or tracked. The EDGAR fetcher it unblocked is
>   `scripts/data/fetch_edgar_events.py` (commit `9027e4b`, plan 0.7), and G6
>   is measured there. Read "blocked on the user-agent" as done.
> - **The §5.1 gross-cap defect** (§9.2) is fixed in `release-20261011-1`,
>   installed on the VM on 2026-10-12. The send-time fit now carries
>   `max_gross_stress`, and the cap is taken on the lower of sized and live
>   equity for a plan that adds gross (team lead, 2026-10-11, `docs/SYSTEM.md`
>   §5).

**What this note is.** An ideation and design note for the research and
production streams to pick up later. **It spends no trial, changes no spec and
trades nothing.** Every idea in it is a candidate. Each one is checked against
`/graveyard` and pre-registered (`/prereg`) before it spends a trial, and counted
in `docs/RESEARCH_STATE.md` in the same commit.

**How it fits the existing programme.** It extends three notes and does not replace
them:

- `results/cef/RESEARCH_AGENDA_2026-10-08.md`: product × signal families;
- `results/cef/SCALING_RESEARCH_2026-10-08.md`: how others clear 10%, and the
  eight-topic pass;
- `results/cef/RESEARCH_PLAN_2026-10-09.md`: the ordered programme under the
  team lead's rulings of 2026-10-09 (`docs/SYSTEM.md` §5).

Where this note and the plan overlap, **the plan governs** and this note says so.
The items new here are marked **NEW**.

**Labels.** `[V]` verified (fetched and read, by whom and when), `[S]` sourced but
not re-read here, `[U]` uncertain. `[doc: path]` is a figure copied from a repo
document and **not re-run** for this note. `[measured 2026-10-12]` was produced
for this note by the command named beside it. Nothing here keys a decision on a
written number (H14): every rule below says what to measure at run time.

**Reproducers for the figures measured here** (§1, §5.1, §5.2):

- `python3 -m ops.orient` (`ops/orient.py`, `ops/prod_state.py`): prod state, the
  2026-10-09 verdict, trial counters and panel dates;
- the code cited in §5.1, read at `d548130`: `quantt/session/run.py` and
  `quantt/session/gate.py`;
- `pd.read_parquet('data/cef/cef_borrow_history.parquet')` for its columns and
  date range;
- the Alpaca corporate-action count came from one read-only
  `GET /v2/corporate_actions/announcements` call (merger, 2026-09-12 to
  2026-10-12), made through the Alpaca MCP. No repo script reproduces it yet;
  the event fetcher in §3.5 would.

---

## 0. The answer

1. **Event-aware, not event-timed.** Events should change *what the book may hold*
   and feed a second, idiosyncratic sleeve. They should not change *when it
   trades*. The order path stays one netted MOC set per day: a second set fills in
   the same auction and doubles the book (`CLAUDE.md` order-path rules 2–3). The
   one intraday exception proposed here can only **remove or shrink** orders, never
   add them (§2.3).
2. **An event-driven book cannot replace the discount book; it sits beside it.**
   Credit-CEF events are few and thin. The merger pair's capacity is put at about
   $0.5m per deal, and entering at announcement gave a median near the breakeven
   (`SCALING_RESEARCH_2026-10-08.md` §7.1, **agent figures not yet reproduced in
   the repo**). Events add breadth, and breadth is the binding lever
   (`docs/SYSTEM.md` §3).
3. **The critical path for the whole event programme is one string from the team
   lead**: the SEC contact user-agent. It unblocks the EDGAR fetcher (plan 0.7),
   which unblocks the event log (§3), gates G6, G1a–c and G7, the
   corporate-action filter C1 and the merger pair E1.
4. **Five NEW event ideas** survive the graveyard check (§4.3). The strongest is a
   **conditional-tender tracker**: some funds are committed to tender near NAV if
   their average discount passes a stated threshold over a stated window, so the
   trigger can be computed daily from public data before anything is announced.
   **Two of our 13 names, MHD and MQY, were in such a programme from 2026-01-01
   to 2026-09-30.** Neither triggered, but the book did not know (§4.3 N1).
5. **The core book has cheaper wins than any new signal** (§5). In order:
   - an **uptime defect** that lost the 2026-10-09 session;
   - shortability modelled in the backtest;
   - **long-only eligibility** for names Alpaca will not let us short, instead of
     dropping them. Dropping four munis cost traded-era gross Sharpe 1.54 → 1.16
     on the band alone (`[doc: spec _universe_note; PREREG_ALPACA_V7 §5]`).
6. **ML and RL** (§6). Most of their value here is as *infrastructure*:
   - reading filings;
   - catching bad data;
   - resolving entities;
   - shrinkage across small samples.

   It is not prediction on 13 names: the graveyard has already answered that.
   - **RL** is a numerical solver for a control problem whose analytic answer
     (Gârleanu–Pedersen; the band) should be built first.
   - **A pooled nonlinear model** becomes worth a trial only once the universe
     widens to hundreds of CEFs (B1), and only if it beats a linear model on the
     same features.
7. **Institutional deployment** (§7). The parts that matter most:
   - an event-sourced, hash-chained audit trail;
   - pre-trade compliance fed by the event log (restricted list, locates, Reg M,
     ownership thresholds);
   - sleeve netting with per-sleeve attribution;
   - a broker that supports **voluntary corporate-action elections**: tendering
     into a NAV tender we are already long is execution, not a trial;
   - a warm standby that can never be armed at the same time as prod;
   - and counsel for everything about the entity.

---

## 1. Ground truth as of 2026-10-12

Measured for this note. These figures are true on their date only.

| what | value | source |
|---|---|---|
| Prod | the Azure VM, ARMED, at `release-20261011-1`; the laptop is off | `python3 -m ops.orient` PROD [measured 2026-10-12] |
| Live equity | $100,765.98 at the 2026-10-09 close, broker-confirmed | orient PROD [measured 2026-10-12] |
| Last verdict | 2026-10-09: **no trade**, refused at send: projected gross $182,154.75 > `max_gross_stress` 1.8 × equity $100,806.81 | orient PROD [measured 2026-10-12]; §5.1 |
| Trial counters | CEF 50 (bar √(2 ln 50) = 2.797); EVENTS 0; XASSET 0 (declared slate of 5, bar 1.79); GAMMA 0 | orient TRIALS, from `docs/RESEARCH_STATE.md` |
| Dev-tree panels | `cef_prices` to 2026-09-28; `cef_nav` to 2026-09-25 (**the dev tree, not prod**; the VM keeps its own) | orient PANELS [measured 2026-10-12] |
| Wider CEF set | `data/cef/cef_universe.csv`: 44 rows (the 17 original names and the 27-name holdout, opened for event trades on 2026-10-09) | [measured 2026-10-12] |
| Alpaca corporate-action feed | 182 merger announcements in the 30 days to 2026-10-12, **none** on a `cef_universe.csv` name. Fields: `ca_type`, `ca_sub_type`, `initiating_symbol`, `target_symbol`, `old_rate`, `new_rate`, `cash`, `record_date`, `effective_date`, CUSIPs. **No announcement or declaration date** | `GET /v2/corporate_actions/announcements` via the Alpaca MCP, read-only [measured 2026-10-12] |

**What the last row means.** Alpaca's feed is useful for *settlement mechanics*:
ratios, record and effective dates. It cannot be the announcement signal. EDGAR is
the announcement source.

---

## 2. Design principle: event-aware, not event-timed

### 2.1 Why the timing stays

- **Order type stays MOC** (`CLAUDE.md` rule 3). Alpaca rejects `cls` entries
  from 15:50 ET, and NYSE cancels no MOC after 15:50. Paper's `late_market`
  exception (15:52–15:58 market `day` orders) **never applies to a live account**.
- **The trade phase is not idempotent** (rule 2). An event-triggered "second run"
  is the doubling hazard by another name.
- **`shift(2)`** is the execution convention: decide at *t*, fill at *t+1*'s close,
  earn *t+2*. An event-driven book must map every event onto it.

### 2.2 Mapping an event onto `shift(2)`

The rule: an event enters the first decision made **after** its `observed_at`.
`observed_at` is when we could first have known, not when the event takes effect
(§3.6).

| the event is first observable | it enters | it fills | it earns |
|---|---|---|---|
| before the evening decision on *t* (22:00 ET retries) | the plan decided at *t* | *t+1* close | *t+2* |
| between the evening decision on *t* and the send window on *t+1* | **only through §2.3**, and only to shrink or remove orders in *t+1*'s set; otherwise the plan decided at *t+1* | as the row it lands in | as the row it lands in |
| after the *t+1* send window | the plan decided at *t+1* | *t+2* close | *t+3* |

The backtest must apply the same table: `evaluate()` takes weights decided at *t*,
so an event sleeve's `H.loc[t]` may only use events with `observed_at` ≤ the
decision time of *t*. **Assert it at runtime** (`CLAUDE.md`, no lookahead).

### 2.3 The one intraday exception: events can only subtract

**NEW.** Suppose a NAV tender, merger or liquidation is announced at 08:00 on a
name we are about to short at today's close. The plan was decided last night.
Waiting a day costs a known loss: shorting into a pinned price (`docs/BRIEF.md` §3).

**Proposal.** A same-day event on a name in today's set may **remove or shrink**
that name's order before the send window. It may never add an order or grow one.

- This mirrors the scale-to-fit rule: "what goes is always a subset of the decided
  plan" (`docs/RUNNER.md`, as built 2026-10-07).
- **On paper** (`late_market`) the set is not sent until 15:52. Removing a name is
  an edit to the saved plan before the send, so the plan's sha changes and is
  recorded.
- **On a live account** the evening set may already be queued at Alpaca. Orders
  sent after 19:00 ET are queued for the next auction (`docs/RUNNER.md`).
  Subtracting then means **cancelling a queued `cls` order before 15:50**. That is
  an order-path action with its own failure mode: a cancel that is not confirmed
  must stop everything else, never trigger a re-send. The rule:
  - cancel only;
  - confirm each cancel by re-reading the order;
  - never send a replacement in the same session.
- **Tests to write first:**
  - an event can never increase |quantity|;
  - an unconfirmed cancel leaves `STARTED` in place and sends nothing;
  - `DRY_RUN=1` wins;
  - each test fails on code without the rule.
- **Who decides:** the team lead. Whether the scheduled runner may cancel queued
  orders on its own is a new standing decision (§9).

### 2.4 What does not change

- One netted order per symbol per book, because Alpaca rejects opposite-side
  orders as wash trades.
- `STARTED` is written before the first order, and the runner refuses if a set is
  headed for an unclosed auction.
- `DRY_RUN=1` and `ops/HALT.md` win.
- Nothing intraday trades on a *signal* without its own pre-registration (ruling
  of 2026-09-08). §2.3 is risk reduction on a decided plan, not an intraday signal.

---

## 3. The runtime: an event log

Today the VM's timer wakes every 30 minutes. It decides on *t*'s complete price
and NAV pair in the evening, sends at 15:52, polls fills and verifies at 17:30
(`docs/RUNNER.md`). The nightly collector already runs dated steps: prices and
NAV, cross-checks, official closes, an account snapshot, distributions and the
borrow snapshot (`quantt/collect/collect.py`).

The 30-minute poll is already a crude event loop, so re-plumbing it for its own
sake buys little. **What is missing is a place for outside events to land**, one
that both the live runner and the research harness read.

### 3.1 The event record

One append-only table. On prod it is `<state>/events.jsonl`; for research it is the
same rows as `data/events/events.parquet`, with a fetcher and a
`docs/REFERENCES.md` source note (`CLAUDE.md`: never hand-copy a data series).

| field | meaning | why |
|---|---|---|
| `event_id` | source-unique: the EDGAR accession number, Alpaca's `corporate_action_id`, or a hash for calendar events | dedupe; at-least-once delivery is safe |
| `source` | `edgar`, `alpaca_ca`, `alpaca_news`, `borrow_snapshot`, `calendar`, `broker`, `dq` (data quality) | lineage |
| `kind` | an enum: `tender`, `conditional_tender`, `merger`, `rights_offering`, `liquidation`, `open_ending`, `term_change`, `activist_13d`, `distribution_declared`, `borrow_flip`, `bond_holiday`, `nav_missing`, … | consumers switch on it |
| `symbols`, `cik`, `series_id` | the instruments touched, both sides of a merger | entity resolution (§6.1c) |
| `observed_at` | UTC time we could first have known it: EDGAR acceptance time, our own poll time, Alpaca's timestamp | **the no-lookahead key** (§3.6) |
| `effective_at` | when it takes effect: expiry, effective date, record date | the event's own clock |
| `terms` | JSON: price basis (% of NAV), size, pro-ration, exchange basis, subscription formula, transferable or not, measurement window and threshold | sizing and the state machine |
| `status` | the state machine's current state (§3.2) | consumers read state, not raw rows |
| `extraction` | `rule` or `llm`; extractor version; prompt hash; model version | reproducibility (§6.1a) |
| `confidence`, `review` | the extractor's confidence; human or agent review status | low confidence never reaches the live path unreviewed |
| `backfilled` | true when the row was found after the fact, by a later search | **backfill bias**: research may not treat a backfilled row as known in real time |
| `raw_ref` | the filing or press-release URL | audit |
| `prev_hash`, `hash` | a hash chain over rows | tamper-evident audit trail (§7.3) |

### 3.2 A state machine per event

```
tender:              ANNOUNCED -> TERMS_SET -> OPEN -> EXPIRED -> PRICED(NAV at expiry close) -> PAID
                                                   \-> EXTENDED -> OPEN ...   \-> WITHDRAWN
conditional_tender:  PROGRAMME_ADOPTED -> MEASURING(window) -> TRIGGERED -> (tender, above)
                                                          \-> NOT_TRIGGERED -> MEASURING(next window) | EXPIRED
merger (N-14):       ANNOUNCED -> FILED(N-14) -> VOTE_SCHEDULED -> APPROVED -> EFFECTIVE(ratio at NAV)
                                                             \-> FAILED / ADJOURNED -> ...
rights_offering:     ANNOUNCED -> RECORD -> SUBSCRIPTION_OPEN -> EXPIRED -> PRICED -> ISSUED
liquidation / open_ending / term_change: ANNOUNCED -> VOTE -> APPROVED|FAILED -> EFFECTIVE
borrow_flip:         SHORTABLE <-> NOT_SHORTABLE ; EASY <-> HARD_TO_BORROW   (one row per transition)
```

Consumers read the **current state at the decision time**, rebuilt from the rows
with `observed_at` ≤ that time. They never read the latest row as if it were
always known. The same function serves live and research.

### 3.3 Producers

| producer | gives | cadence | status |
|---|---|---|---|
| **EDGAR** submissions per CIK: tender forms (SC TO-I/TO-C), merger forms (N-14, 425), proxies (DEF/PRE 14A), 8-K, offering forms (N-2, 424B), 13D/13G, N-PORT, N-CSR | the announcements and their terms: **the signal** | polled; nightly for research, every few minutes in market hours for the live layer, within SEC's fair-access limit (§11) | plan item 0.7, **blocked on the SEC user-agent** |
| **Alpaca corporate actions** | ratios; ex, record, payable and effective dates; splits, dividends, mergers, rights | nightly | works [measured 2026-10-12]; settlement only. The current `/v1/corporate-actions` has **no declaration date and no tender-offer type**. An SSE stream, `/v1beta1/events/corporate-actions`, stamps each event with the time Alpaca emitted it: a usable `observed_at` for settlement events, not the issuer's announcement time [V: agent, §12k] |
| **Alpaca news** | Benzinga articles, back to 2015, REST and websocket (sponsors often announce tenders and settlements by press release) | streaming | [V: agent, §12k]. The docs cite about 130 articles a day **across all symbols** and say nothing about CEFs, so coverage is probably thin. **Measure it on our 44 names before relying on it** |
| **Daily borrow snapshot** | shortable and hard-to-borrow transitions | daily | built 2026-10-09 (`eb663f5`) |
| **Calendar** | ex-dates and pay dates (distribution panel), SIFMA bond-market holidays and early closes, term dates (PDO 2033), tender expiries, index reconstitution dates (YYY, PCEF) | rebuilt nightly | partial: the distribution panel exists; the rest is NEW |
| **Broker** `trade_updates` | fills, partial fills, cancels, expiries and replacements, pushed rather than polled | streaming | documented for paper [V: agent, §12k]. Paper adds random partial fills 10% of the time. Nothing in `quantt/` subscribes yet; the runner polls, and a stream is an option, not a need |
| **Data-quality detector** | stale NAV, repeated values, NAV that two sources disagree on, bad prints (§6.1b) | nightly | NEW; extends the collector's cross-checks |

### 3.4 Consumers

1. **The eligibility layer.** This is trial C1 (`RESEARCH_PLAN` order 1, CEF
   counter). A name under an announced NAV tender, merger, liquidation or
   open-ending may not be newly shorted, and its short is reduced to zero by the
   event's pre-registered rule. It reads event state through
   `MarketState.extras["events"]`, so the sleeve stays a pure function of
   `(asof, market_state)`. The research harness passes the same structure,
   rebuilt point-in-time.
2. **Event sleeves** (E1 merger pair, the conditional-tender sleeve in §4.3, and
   the rest) take entry and exit dates from event state.
3. **The intraday subtract rule** (§2.3).
4. **Verify and attribution**: each day's P&L is split into event names and
   non-event names, per sleeve.
5. **Monitoring**: a new orient section, EVENTS. It shows the time of the last
   successful EDGAR poll, the open events on held names, and any `borrow_flip` on
   a held short. Dashboard and logs only (standing decision 2026-09-21,
   confirmed 2026-09-28).

### 3.5 Where it lives in the code

- **`quantt/events/`** (NEW package):
  - `store.py`: append-only, hash-chained, dedupe on `event_id`;
  - `state.py`: the state machines and `state_at(t)`;
  - `edgar.py`: the fetcher and parsers, shared with
    `scripts/data/fetch_edgar_events.py` so research and live parse identically;
  - `calendar.py`.
- **`quantt/collect/collect.py`** gains `step_edgar_events` and
  `step_event_calendar`, alongside `step_borrow_snapshot`.
- **The session** reads event state at decide and again at the subtract check.
  It writes the event ids it used into the plan record, so `plan_sha` covers them.
- **The research harness** gets an `events_at(t)` helper beside `evaluate()`. It
  is not a new backtester (`CLAUDE.md`, research rules): it is an input to the
  `H` matrix the canonical harness already scores.

### 3.6 No lookahead with events

- **Key on `observed_at`, never `effective_at` and never the filing date.**
  [V: 17 CFR 232.13(a); data.sec.gov; fetched 2026-10-12, `docs/REFERENCES.md`
  §12j]:
  - A filing whose transmission **commences** after 5:30 p.m. ET is deemed filed
    on the next business day. Schedules 13D/13G and Forms 3/4/5 get until
    10 p.m.
  - `data.sec.gov/submissions` gives an `acceptanceDateTime` per filing **in UTC**
    (a trailing `Z`). The filing index page shows the same instant in ET.
    **Convert it; never compare it to an ET clock as if it were local.**

  So a filing can be visible on EDGAR in the evening while its filing date says
  tomorrow, and a sponsor's press release can come before both.

  **CORRECTION 2026-10-15** (`results/events/EVENT_ENGINE_DESIGN_2026-10-15.md` §4,
  `docs/REFERENCES.md` §12z):
  - The SEC says submissions begun after 5:30 p.m. ET (10 p.m. for ownership
    forms) "will be disseminated the next business day". One evening's feed
    showed no non-ownership filing accepted after 17:31 ET. So the sentence
    above is wrong for most forms: an evening filing is not public that evening.
  - The submissions API's `acceptanceDateTime` is one UTC offset late on 23 of
    50 filings.
  - The key is `observed_at = max(header acceptance, 06:00 ET on the filing
    date)` (`scripts/events/event_store.py`).
  - Keyed on acceptance, 7 of 50 sampled filings would have reached a 22:00 ET
    decision 8–56 hours early. Use the earliest
  timestamp we can **prove** we could have seen, normally `acceptanceDateTime`.
  Record our own poll time beside it, so the gap between the two is measured
  rather than assumed.
- **Backfill bias.** A research table built in 2026 from a 2026 search of EDGAR
  knows about events a 2015 trader may not have found that day: amended filings,
  forms later reclassified. Mark rows found by a later search as `backfilled`.
  Report results with and without them.
- **Survivorship.** The CEF panel holds only funds alive today
  (`docs/SYSTEM.md` §2). Merged and liquidated funds are exactly the event names.
  Event studies need CRSP delisting returns (`dlret`, delisting codes). SCALING
  §7.1 reports CRSP delisting amounts matching filed ratios to 6 decimals
  `[doc; agent figure]`.
- **The runtime assertion.** `events_at(t)` raises if any row it returns has
  `observed_at` after the decision time of *t*. A test proves it raises.

### 3.7 Failure behaviour (no silent fallbacks)

| failure | behaviour | why |
|---|---|---|
| EDGAR poll stale beyond a declared age | the eligibility layer **refuses to open or increase any short** that day, logs `EVENTS_STALE`, and lets longs and reductions trade | not knowing about a tender is exactly when a short loses; refusing everything would cost uptime for no reason |
| an extractor fails on a filing | the row is written with `status=UNPARSED` and `kind` from the form type. The name is treated as under an event of that form type until reviewed | raise, naming what was missing; never assume "no event" |
| an LLM extraction disagrees with the rule-based one | both are kept; the row goes to review; the live layer uses the more restrictive reading | report disagreement, never average (`CLAUDE.md`, data rules) |
| Alpaca CA feed unavailable | nothing on the live path depends on it; logged | settlement data only |

---

## 4. Event trades: the full map

### 4.1 Already queued (the plan governs; listed so nobody re-ideates them)

| plan id | trade | counter | gates | blocked on |
|---|---|---|---|---|
| C1 | corporate-action filter on the live book | CEF 50→51 | G6 | EDGAR fetcher (0.7) |
| E1 | NAV-for-NAV CEF merger pair | EVENTS 0→1 | G1a (borrow), G1b (ex-ante sign), G1c (≥30 groups) | 0.7, 0.8 (NAV history beyond the 44) |
| E2 | convertible-issuance reversal | EVENTS | G3 (reproduce in repo) | 0.9 |
| E3 | listed mandatory convertibles, delta-hedged | EVENTS | G4 (N ≥ 30) | 0.9 |
| E4 | CEF IPO lifecycle pair | EVENTS | G7 (≥30 IPOs, shortable) | 0.7 |
| 2d | rights-offering window | EVENTS | count post-2010 offerings first (D7 below about 100) | 0.7 |
| B2 | fund-of-CEF index reconstitution (YYY, PCEF) | NPORT | count events first | N-PORT parse |
| B3 | dividend-reinvestment buying on payable dates | EVENTS | — | CRSP pay dates × NAV panel |
| B4 | tax-loss and January across retail wrappers | CEF | — | — |
| 2c | term-CEF pull-to-par | — | PARKED as a sleeve (D7); folded into C1 and the event layer | — |

### 4.2 The critical path

```
TL: SEC user-agent string
  -> 0.7 EDGAR fetcher (scripts/data/fetch_edgar_events.py + quantt/events/edgar.py)
       -> event log (sec. 3)  -> G6 (does C1 matter?)  -> C1 trial (CEF)
       -> G1a-c               -> E1 trial (EVENTS); consumes the 27-name holdout if it touches a cef_universe.csv name
       -> G7, 2d count        -> E4, rights-offering decisions
       -> NEW: conditional-tender census (sec. 4.3 N1)
```

The borrow snapshot (0.3) is already built, so G1a can run as soon as the merger
event list exists.

**G6 has a live first case.** BlackRock announced on 2026-02-09 that MHD, one of our
13 names, would absorb MUE, BFK, BYM and BLE. MHD then adopted a 2026
discount-management programme on completion [V: agent, §12k]. So the live book
traded MHD as a **merger acquirer** and through a **live measurement window**
this year.

Two zero-trial checks follow:
- **(a) The panel.** Does MHD's price, NAV or share-count series show a break at
  the merger's effective date that the z-score read as a dislocation? The check
  agent flagged it as a share-count break to verify.
- **(b) Positions.** What did the book hold in MHD between announcement and
  completion, and what did it earn there? Read from broker-confirmed fills
  (Alpaca from 2026-09-29; earlier fills are IBKR and only at tag
  `pre-clean-slate`).

### 4.3 NEW event ideas

Each idea has a 0-trial first step. None has been tested.

#### N1. Conditional-tender tracker (EVENTS)

- **Mechanism.** Some fund boards adopt, or settle with activists into, a
  **conditional tender programme** (BlackRock calls it a discount-management
  programme). If the average discount over a defined measurement window exceeds
  a threshold, the fund tenders for part of its shares at a fixed fraction of
  NAV.
- **It already touches our book** [V: agent, 2026-10-12, `docs/REFERENCES.md` §12k;
  primary filings and BlackRock releases]:
  - **MHD and MQY, two of our 13 names,** were in BlackRock's 2026 muni programme.
    The window ran 2026-01-01 to 2026-09-30. A tender of at least 5% at 98% of
    NAV would have followed if the average daily discount exceeded 10.00%.
  - Results published 2026-10-01: MHD −8.17%, MQY −7.41%, so **no muni tender**.
    Only BMEZ (equity, not ours) triggered, with a tender open 2026-10-16 to
    2026-11-18.
  - No 2027 programme has been announced. **The book therefore traded two names
    through a live measurement window this year without knowing it.**
- **More examples** [V: agent, §12k]:
  - **MVF (muni):** a Karpus standstill of 2024-05-03 set up a quarterly test.
    Above a 7.50% average discount, the fund tenders 2.5% at 98% of NAV. The
    Q4-2024 average was −8.28%, and the fund tendered in 2025-01/02.
  - **EFT and EVF (Eaton Vance loans):** announced 2021-05-12. A
    January–August average discount above 10% triggers a tender of up to 10% at
    98% of NAV. Both triggered in 2023.
  - **EIM (Eaton Vance muni):** a firm 20% tender plus two 5% tenders at 98% if
    a four-month average exceeds 7.5%. The 2025 window triggered.
  - **Not every "conditional tender" is discount-triggered.** MFS's CXH tender is
    conditional on a merger vote, so the census must read each programme's terms.
  - **No aggregate count of programmes was found** [S, a negative search]. The
    census is the first count.
  - The trigger is computable **daily** from public prices and NAVs, so the
    probability that the tender happens moves during the window, before any
    announcement.
  - Once triggered, the tender is a dated, NAV-priced convergence on part of the
    float. The rest of the float usually widens back afterwards (`docs/BRIEF.md`
    §3, the activist round trip).
- **Who is on the other side.** Holders who do not track the rule: retail, and
  index funds of CEFs. Also sellers who need liquidity before the window closes.
- **Graveyard check.** "Tender capture alone: about 0.5% gross, not significant net"
  (SCALING §3, *do not build*). That killed *trading the announced tender*. N1 is
  *pre-announcement*, using a known, mechanical rule. It is **not**
  "pre-positioning on activist attacks" (killed), which guessed whether an attack
  would come. Here the rule is published. **Name the control before running**: the
  same funds and windows in years with no programme, plus funds whose average
  discount sat just inside the threshold.
- **Design sketch.**
  - State: the running window-average discount; the days left; the threshold.
  - Signal: a closed-form probability that the average ends past the threshold,
    from the fund's own discount volatility (point-in-time, `shift(1)` like the
    z-score) and the days remaining.
  - Position: long the fund in proportion to (probability × expected tender gain
    on the pro-rated fraction), short a matched seasoned fund or the group basket.
  - Exit: at the tender's pricing date, or at the window's end if not triggered.
- **First step (0 trials).** A census from the EDGAR fetcher of every programme
  in the CEF universe: fund, terms, measurement windows, how many triggered,
  dates. Below about 30 independent windows it is D7: fold it into C1 as hygiene.
- **Second use, and this one is free.** Even if N1 never becomes a sleeve, a fund
  in a live measurement window near its threshold should not be **shorted** by the
  core book. Add it to C1's pre-registration.

#### N2. An expiry date in C1 (no extra trial; part of C1's pre-registration)

- **What "NAV-priced" rests on.** `docs/BRIEF.md` §3 says SEC staff require a
  CEF tender to be priced at NAV at the close of its last day. Re-checked
  2026-10-12 [`docs/REFERENCES.md`, amended row]:
  - that is a **sponsor's description** of a staff position, in a Nuveen N-2. It
    is not SEC text;
  - Rule 13e-4 itself has no NAV-pricing requirement. It does require a tender to
    stay open at least 20 business days, plus 10 more after any change in price
    or size;
  - no staff letter was found;
  - tenders at 97% and 99.5% of NAV exist.

  Read it as **fixing the NAV date, not the percentage**. Take each tender's
  price basis from its own offer document (§3.1 `terms`).
- After a tender prices, the discount tends to widen back (`docs/BRIEF.md` §3:
  excess discount narrowed to −0.2% during activist-forced tenders and widened to
  −3.3% the year after `[doc]`).
- The live z-score already harvests that: a fund pinned near NAV reads rich
  against its own history, so the book goes short once the pin is gone.
- **A filter that blocks a name until "completion" with no explicit release
  date blocks this trade too.** C1's pre-registration must state when each event
  kind releases the name. Examples: the close after the tender's pricing date; the
  merger's effective date (the target then ceases to exist); the vote date for a
  failed open-ending.

#### N3. Bond-holiday stale NAV (0 trials to measure; CEF trial only if it changes the policy)

- **Mechanism.** On days when NYSE is open but SIFMA recommends the bond market
  close, credit funds still strike a NAV. Their bond prices may be carried from
  the previous day while the shares trade. The discount then moves only with the
  share price. That is graveyard pattern 1, the stale-price artifact, on a
  calendar we can know in advance.
- **The 2026 calendar** [V: sifma.org and nyse.com, fetched 2026-10-12,
  `docs/REFERENCES.md` §12j]:
  - SIFMA's 2026 bond-market holidays include **Columbus Day (2026-10-12, today)**
    and **Veterans Day (2026-11-11)**. NYSE trades on both.
  - Those are the only two 2026 days with the bond market closed and NYSE fully
    open.
  - SIFMA's 2 p.m. early closes on full NYSE days are May 22, Jul 2 and Dec 31.
    On Nov 27 and Dec 24 NYSE itself closes at 1 p.m.
  - SIFMA's recommendations are "recommendations only". Whether each sponsor's
    pricing vendor actually carries prices on those days is unmeasured, and is
    what the measurement below finds out.
- **This is live tonight.** The VM's evening session decides on 2026-10-12's
  price and NAV pair. That is a bond-holiday NAV, if the funds strike one.
  Nothing changes without a trial. But recording tonight's per-fund NAV changes
  (are they near zero?) and the plan they produce starts the measurement at no
  cost. The next case is 2026-11-11.
- **Measure.** On SIFMA-closed days with NYSE open, against all other days:
  - the NAV change distribution per fund (is it near zero?);
  - the discount change;
  - whether the band traded the next day;
  - the next-day P&L of those trades.
- **If the book trades on them**, the candidate rule is: a NAV struck on a bond
  holiday does not enter the z-score window, and the decision uses the prior
  complete pair. Because it changes the live policy it is one CEF trial, with a
  no-op proof (`/spec-change`).
- **The same lens** applies to SIFMA early-close days and to month-end NAV
  pricing-source changes.

#### N4. Fund-of-CEF flow pressure (NPORT counter)

- **Mechanism.** Coval & Stafford's fire sales (2007) [S], applied to CEFs.
  ETFs and mutual funds that hold CEFs (YYY, PCEF, CEFS; RiverNorth and Matisse
  funds) must buy or sell their holdings when their own shares are created or
  redeemed.
  - Map each vehicle's daily flow through its holdings to an implied buy or sell
    per CEF, in days of that CEF's ADV.
  - RiverNorth holds 11 of our 13 names (SCALING §7.3, 13F 2026Q2 `[doc; agent
    figure]`). The overlap is real.
- **How it relates to queued and dead work:**
  - **B2** (index reconstitution) is the dated special case of N4. N4 is the
    continuous version.
  - **Graveyard neighbour:** `raw-flow-z` (D1) asked whether an ETF's own flow
    predicts **its own** return. N4 asks whether a vehicle's flow, passed through
    its holdings, predicts **the holdings'** discounts. Different question, related
    data: say so in the pre-registration.
- **Control** (declared before running): the same flows passed through a
  *permuted* holdings map, and the flows of a bond ETF that holds no CEFs.
- **Data.**
  - Daily shares outstanding: issuer sites, or CRSP `shrout` for history.
  - Holdings: N-PORT (quarterly public) or issuer daily files.
- **Use first as a risk input**, not a signal: implied forced selling across many
  of our names at once is a co-movement risk the z-score does not see (§6.4,
  effective breadth).

#### N5. Short-interest releases as a crowding check (POSITIONING counter)

- **Mechanism.** FINRA publishes short interest twice a month.
  `docs/BRIEF.md` §3 cites Alexander & Peterson (2017): CEF short selling rises
  with the premium, and heavily shorted funds see the premium fall over five days,
  which is our horizon.
  - Other short sellers are doing what we do. Crowding raises recall and squeeze
    risk on our shorts.
- **Graveyard.** `short-pressure` (D1) on credit ETFs died because its rates
  control scored higher. **The control here, named now:** the z-score alone,
  and the same rule on equity CEFs.
- **Test.** Does short interest as a fraction of float add to the z-score's IC at
  the 5-day horizon? Is it incremental, or subsumed the way price reversal was
  (+0.1%, KILLED)?
- **Use if it fails as a signal:** a cap on our short in a name where short
  interest is extreme. That is risk control (§7), and costs no trial if it never
  binds in the backtest.

#### N6. Asset-coverage stress (NPORT counter; D6/D7)

- **What the statute does and does not do** [V: 15 U.S.C. 80a-18, fetched
  2026-10-12, `docs/REFERENCES.md` §12j and the amended §18 row]:
  - §18 requires **300%** asset coverage for debt and **200%** for preferred,
    tested **immediately after issuance**.
  - Below those levels it **bars declaring common distributions and
    repurchasing common shares**. Preferred dividends are still allowed at 200%.
  - Debt-holders may elect a board majority after 12 consecutive months below
    100%.
  - **It sets no maintenance test that compels redemption.**
- **So the mechanism has two parts, one verified and one not:**
  - **Statutory and verified:** a fund below coverage **cannot pay its common
    distribution**. For a yield-bought retail base that is the event.
  - **Contractual and unverified [U]:** any *forced* deleveraging comes from the
    fund's own preferred terms or credit agreement, and has to be read fund by
    fund. *This note first said the Act itself forces deleveraging. That was
    wrong, and so was `docs/BRIEF.md`'s "forces deleveraging mechanically", now
    corrected there with a dated note.*
- **Event.** A coverage ratio estimated daily from the last filed leverage
  (N-PORT, N-CSR) and the daily NAV, crossing a declared buffer above 300% or
  200%.
- **Graveyard caution.** A distribution suspension is a distribution event, and
  M7 (distribution policy) is dead as a signal. N6 is therefore **risk control
  only**, never a sizing input.
- **Use.** Risk: no new long in such a fund during a drawdown until the coverage
  event resolves. It is a sibling of S3-forced-flow (WATCH): crisis-only, few
  events, high marginal value when it fires.
- **First step.** Count the episodes, 2008 and 2020 included. If there are under
  about 30 it is D7. Build it as governance in W6, not as a sleeve.

#### N7. Borrow-state events and the spec's own reopen clause (0 trials)

- The frozen spec's `_universe_note` says: reopen NAD, NEA, NVG and NZF "if a
  later probe shows any of the four shortable and easy-to-borrow for 20
  consecutive sessions (a new trial)".
- The borrow snapshot now records the data. The event log turns it into a
  `borrow_flip` stream, and orient can print each name's run of shortable
  sessions.
- **Detecting the condition is free. Acting on it is a trial.**

#### N8. Sponsor-wave risk (0 trials; risk, not alpha)

- Fund mergers come in sponsor-level programmes. A family consolidates several
  funds at once.
- The first announcement in a family is information about its siblings. Do not
  open a new short in a sibling of a fund that has just announced a merger or
  tender, until the family's proxy filings show no programme.
- **First step.** From the EDGAR event table, measure the probability that a
  sibling announces within 6 months of a family's first announcement, against the
  base rate. Not alpha; a C1 input.

#### N9. Rights offerings: the compliance note (adds to queued item 2d)

If 2d ever shorts during a subscription period, check **Regulation M Rule 105**
first [V: 17 CFR 242.105, fetched 2026-10-12, `docs/REFERENCES.md` §12j]:

- **What it bars:** buying the offered securities *from an underwriter or a
  participating broker-dealer* after a short sale in the restricted period. That
  period is the shorter of 5 business days before pricing and filing-to-pricing.
- **Its scope:** offerings for cash under a registration statement. §105(c):
  "This section shall not apply to offerings that are not conducted on a firm
  commitment basis."
- **What is not settled:** no clause names rights offerings or closed-end funds.
  Whether a given offering is covered turns on whether it is firm-commitment. Read
  that from each offering's prospectus, never assume it.

**The desk's own rule is stricter than the regulation**, because it costs nothing:
the sleeve never subscribes to an offering it shorted into. Encode it as a
pre-trade check (§7.2).

#### N10. Distribution declarations as data hygiene, not alpha

Ex-dates, record dates and pay dates enter the event log so W4 (plan 0.6) can
locate the IC around ex-dates, and so the third P&L line credits the right days.
**Distribution policy is not proposed as a signal**: M7 was tested twice and failed
at a 2-day hold, and `docs/BRIEF.md` says do not rebuild it.

### 4.4 Not proposed (graveyard)

| idea | why not |
|---|---|
| Distribution cuts or raises as a signal | M7: failed twice; do not rebuild |
| Pre-positioning on activist 13Ds | killed: we will never hold a 13D-sized stake; surviving targets give the narrowing back; the 2026 ruling closed §47(b) |
| Tender capture alone | about 0.5% gross, not significant net (SCALING §3) |
| General merger arbitrage | PARK: a short put (D4/D5) |
| CDX, OTC convertible arbitrage, equity–CDS | KILLED on access (SCALING §7.1) |

---

## 5. Expanding the core discount book

`docs/SYSTEM.md` §3: **work that raises the transfer coefficient (TC) or uptime
beats work that sharpens IC, every time.** So this section starts there.

### 5.1 Uptime: the gross cap refuses whole days (a defect, found while writing this note)

- **What happened.** 2026-10-09 did not trade: "refused at send: [exposure]
  projected gross $182,154.75 > max_gross_stress 1.8 x equity $100,806.81"
  (orient PROD [measured 2026-10-12]). The overage was **$702.49, or 0.39%**.
- **Why.** At send the runner re-fits the plan to the live account, but only for
  buying power and margin:
  - `fit_to_buying_power` (`quantt/session/run.py:974`, called at `run.py:852`)
    takes no `max_gross_stress`;
  - `gate_exposure` (`quantt/session/gate.py:537`) then refuses the **whole set**;
  - and it values gross at the plan's as-of closes (`run.py:851`, `plan["closes"]`)
    against **live** equity.

  So any day the plan is sized at the cap and equity dips before 15:52, the
  session is lost. The comment at `run.py:848` describes exactly this failure for
  buying power: "a plan scaled to the limit at decide would otherwise be refused
  by any small adverse move by 15:52". The gross cap was left out.
- **Fix.** Add the gross cap to the send-time fit, under the existing
  `execution.bp_shortfall = scale` behaviour or a sibling key whose absence keeps
  today's refusal (`CLAUDE.md`: a new key defaults to current behaviour). It only
  ever shrinks opening orders.
- **Test.** A plan sized exactly at the cap with live equity 0.5% lower: refused
  on today's code, scaled and passed on the new code. Live path, so it goes
  through `/release-check`, a release tag and `install_vm`.
- **Measure** how many sessions since 2026-09-29 were refused or scaled for any
  exposure reason. That is the uptime figure `docs/SYSTEM.md` §3 asks the runner
  to measure from day one.

### 5.2 Model daily shortability in the backtest (TC)

- The runner re-reads `shortable` at send and skips shorts that have flipped.
  AWF and MHD were not shortable on 2026-10-08 (`RESEARCH_AGENDA_2026-10-08.md` §1).
- `band_frontier.py` assumes every name is shortable every day. The live book is
  therefore lopsided on exactly the days borrow tightens, which is a cost nobody
  counts.
- **Measure** with the daily borrow snapshot: the share of name-days a target
  short was skipped, and the P&L of the skipped legs at the auction print.
- **Historical borrow availability does not exist in the repo.**
  `cef_borrow_history.parquet` holds fees only (`date`, `ticker`,
  `fee_rate_pct`; 2021-09-13 to 2026-09-09) [measured 2026-10-12]. Do not invent
  an availability history. Report the forward measurement only.

### 5.3 Long-only eligibility instead of dropping names (CEF trial)

- **The cost of dropping.** The four munis left the universe because Alpaca will
  not let us short them, and "a dollar-neutral book that cannot short four of its
  names is not the book that was tested" (spec `_universe_note`). The measured
  consequence was traded-era gross Sharpe **1.54 → 1.16** on the band alone,
  "better since 2023, worse before" (`[doc: spec _universe_note; PREREG_ALPACA_V7
  §5; python3 scripts/cef/alpaca_v7_derivation.py]`; **re-run before quoting**).
  The muni group is now MHD and MQY only.
- **The idea.** Keep unshortable names in the cross-section as **long-only**:
  - they enter the demeaning;
  - a cheap one can be held long;
  - a rich one gets zero weight;
  - the rest of the book re-neutralises.
- **The same mechanism generalises.** Any name whose borrow flips becomes
  long-only that day, inside the sleeve rather than as a skip at send. That
  closes the gap in §5.2 by design.
- **The risk.** A built-in net-long muni tilt when munis are cheap, which is
  group beta in costume (D4; and hard muni neutrality was itself killed, gross
  0.97 → 0.82).
- **Report:**
  - gross, with the cost grid beside it;
  - turnover-matched against v7;
  - the muni-group net exposure distribution (p95);
  - five eras;
  - the 2023+ row.
- **Kill.** No gross improvement at matched turnover, or the muni net exposure's
  p95 breaches a pre-declared bound.

### 5.4 Live-versus-backtest parity waterfall (0 trials; the TC measurement)

**NEW as a standing report.** For each live day, replay the decision through the
research path:

1. the sleeve on the frozen panel, then `evaluate()` → the modelled P&L;
2. **data**: the live panel against the research panel on that day (revisions,
   fallbacks);
3. **availability**: shorts skipped for borrow;
4. **rounding**: whole shares;
5. **limits**: buying-power and gross-cap scaling (§5.1);
6. **uptime**: sessions refused or missed;
7. **execution**: fill against the official close (`tca.csv`);
8. **distributions and borrow**: the third P&L line; borrow fees on a real
   account.

Each step is a bar in a waterfall from modelled gross to the broker-confirmed
P&L. **Net ÷ gross is the transfer coefficient.** Measuring it daily is what
`docs/SYSTEM.md` §3 asks for and nothing produces today.

### 5.5 Breadth already queued

Plan orders 3–12: B1 (other CEF families, the largest breadth lever on the CEF
counter), C2 (W10 group fair value), C3 (stale-NAV correction), the XASSET slate
and the GAMMA TLT test. Nothing here re-orders them, except that §5.1–5.4 should
go first because they cost no trial and raise TC or uptime.

---

## 6. Data analysis, ML and RL: where they can add edge, and where the graveyard has already answered

### 6.0 What the desk already concluded, and what would have to change

The graveyard says: **"Do not build: machine learning — 17 names, one feature,
IC 0.075; the bias–variance trade-off is emphatically against it."** Its cousins
are dead too:

- regime-switching;
- sizing up on |z| (every threshold lowered Sharpe);
- sizing on dislocation;
- the Kalman state-space model, beaten by a one-line window change.

That verdict is about **prediction on a tiny cross-section with one feature**. It
changes only if one of three things changes:

| condition | today | what would change it |
|---|---|---|
| **names** | 13 traded; 44 in `cef_universe.csv` | B1: daily-NAV CEF families (145 equity and multi-asset CEFs tradable, 24 clear the ADV floor, `RESEARCH_AGENDA` §1 `[doc]`); NAV history beyond the 44 (plan 0.8) |
| **features** | one: the discount z-score | the event log (§3), holdings and flows (N4), short interest (N5), leverage and coverage (N6), sponsor, liquidity |
| **labels** | one daily return per name | event outcomes: tender triggered, deal completed, pro-ration factor, rights priced |

**The rule this note proposes for any ML trial** (to be written into the
pre-registration):

1. **The comparison is the best linear model on the same features**, not the
   z-score alone. If ML beats the z-score but not a ridge regression on the same
   inputs, the gain belongs to the features, and the features are the trial.
2. **Every configuration tried is a trial.** A hyperparameter search of 50
   settings is 50 trials on its counter, or a declared grid judged against the
   bar for its full size, as XASSET does. The deflated-Sharpe bar √(2 ln N) is
   unforgiving by design.
3. **Nested, purged, embargoed cross-validation** (López de Prado [S]), with the
   embargo at least the label horizon plus the `shift(2)` lag. Inner folds choose
   settings; outer folds score; the 2023-01-01 time holdout stays sealed.
4. **Scored only in the canonical harness**: `evaluate()`, `shift(2)`,
   turnover-matched, gross headline with the 5/15/30bp grid beside it, five
   eras, a 2023+ row. A model's own validation metric is never the result.
5. **A negative control declared before running**: shuffled labels within date,
   and the same model on a group where the mechanism should not exist.

### 6.1 Tier 1: ML as infrastructure (no alpha claim, 0 trials, highest value)

#### 6.1a Reading filings with LLMs: event extraction

- **Job.** Turn EDGAR text (tender forms, N-14s, proxies, 8-Ks, press releases,
  N-2 term clauses, conditional-tender programmes, rights-offering terms) into the
  `terms` field of §3.1.
- **Why an LLM.** These documents are semi-structured legal prose. Rule-based
  parsers break on every sponsor's template. The census already found that a name
  filter misses term funds whose names carry no term marker (SCALING §7.4).
- **Controls:**
  - **A gold set.** Hand-label at least 100 filings across sponsors and kinds.
    Report precision and recall per field. Nothing reaches the live path below a
    pre-declared recall on `kind` and on the price basis.
  - **Dual extraction.** A rule-based parser runs beside the LLM. Disagreement is
    reported and reviewed, never averaged. The live layer uses the more
    restrictive reading.
  - **Reproducibility.** Pinned model version, temperature 0, and the prompt hash
    and model version written into each event row.
  - **Cross-checks against structured sources.** Alpaca CA ratios and effective
    dates; CRSP delisting codes and amounts.
- **The LLM lookahead problem: an outside-the-box risk.** A language model
  trained on text up to its cutoff may "know" how a 2018 merger ended. Used to
  *classify or predict*, it leaks the future into a backtest (Glasserman & Lin,
  2023, on GPT sentiment [S]). Mitigations:
  - extraction only: fields stated in the document, never "will this complete?";
  - redact fund names and dates in a leakage audit, and check the extraction does
    not change;
  - measure extraction accuracy separately on filings dated **after** the model's
    training cutoff;
  - **never** use an LLM's judgement as a feature in a backtest that spans its
    training period.
- **Agents.** The desk's agent layer can run the review queue. An agent proposes
  an extraction, a second agent verifies it against the filing text, and
  disagreements go to a human.

#### 6.1b Data-quality anomaly detection

- **Job.** Catch the stale-price artifact before it trades. It has caused six of
  the 13 graveyard deaths.
- **Robust statistics first:**
  - a NAV unchanged for k days;
  - a NAV change larger than m robust standard deviations of the fund's own
    history with no matching move in its group's ETF;
  - price and NAV dated on different days around ex-dates;
  - yfinance against CEFConnect disagreement (the collector already cross-checks).
- **Unsupervised ML** (an isolation forest on these features) only if the robust
  rules miss labelled incidents. The collector's history of disagreements is the
  label set.
- **Output.** `dq` events (§3.3). A `dq` event on a name blocks *new* trades in
  that name for the day. Raise, naming what is wrong.

#### 6.1c Entity resolution

- Map ticker ↔ CIK ↔ series and class ids ↔ CUSIP, through renames, mergers,
  sponsor changes and adviser changes.
- Boring and essential. Every event study fails quietly without it, and the MQY
  shares-outstanding disagreement is an example of what it catches (SCALING
  §7.4: 71.8m against about 150.5m, unresolved `[doc]`).

### 6.2 Tier 2: statistical learning that fits small data (trials, on the right counter)

#### 6.2a Hierarchical shrinkage (CEF counter)

- The 2026-09-09 ruling already chose this: "model form by group (four
  mechanisms), parameters by fund shrunk within group. Four trials, not
  seventeen."
- Empirical-Bayes shrinkage is the form of "learning" a 13-name book can afford.
  - Each fund's z-window, band width or vol scalar is pulled toward its group's
    value, by an amount set by the noise in its own estimate.
  - Derive the shrinkage from the data; do not sweep it.

#### 6.2b NAV nowcast (CEF counter; this is queued C3)

- A regularised regression of each fund's daily NAV change on same-day ETF
  closes (HYG, LQD, MUB, BKLN, TLT and their history), fit point-in-time.
- It corrects M2, stale NAV. **The Kalman death is the warning**: no fitted latent
  level, only observables.
- Its control is the equity CEFs, whose NAVs are struck on exchange closes, so
  the nowcast should add nothing there.

#### 6.2c Event-outcome models (EVENTS counter)

- Logistic models with a handful of declared features, for:
  - P(a tender is oversubscribed), which sets the pro-ration;
  - P(a merger completes on schedule);
  - P(a conditional tender triggers), where the closed form in N1 is the
    benchmark the model must beat;
  - P(a rights offering prices below its formula floor).
- **Judged on calibration** (Brier score, reliability curve) before any P&L.
  A miscalibrated probability sized into a position is the "sizing on |z|"
  failure again.

#### 6.2d A pooled panel model on the wider CEF universe (CEF counter; only after B1)

- **The one place a nonlinear learner might earn its keep.** Hundreds of CEFs,
  20 years, a dozen declared features:
  - discount z;
  - NAV momentum;
  - distribution rate against NAV yield;
  - leverage and its cost;
  - premium regime;
  - sponsor;
  - liquidity;
  - event-state flags;
  - short interest;
  - fund-of-CEF ownership.
- **Protocol** (§6.0): ridge with group interactions first; gradient-boosted
  trees only if ridge's incremental IC over the z-score is positive out of fold;
  the whole grid declared as the trial count.
- **Known failure modes to test for:**
  - distribution features failed twice (M7);
  - price reversal is 95% subsumed;
  - the muni-vs-taxable factor dominates variance, so a model can "learn" group
    beta. Report the pooled model's group-net exposure, and run the D4 test.

### 6.3 Tier 3: reinforcement learning, assessed honestly

**What RL would be for.** The trading policy: when to trade and how far, given
the signal, costs, borrow, margin and the gross cap. That is a stochastic control
problem.

**What is already known about it:**

- **Proportional costs** give a no-trade band, traded back to its edge
  (Constantinides 1986; Davis & Norman 1990). That is the live policy.
- **Quadratic costs with mean-reverting alpha** have a closed form (Gârleanu &
  Pedersen 2013 [S]): trade a fixed fraction of the way toward an "aim portfolio"
  that weights the current and future expected Markowitz portfolios by each
  signal's decay speed.
- **The graveyard points here.** "Sequential Σ⁻¹α + band" lost (gross 1.07 against
  plain α's 1.10), with the note **"use the joint objective instead"**.
  Gârleanu–Pedersen *is* a joint objective, and it has never been built in this
  repo.

**Recommendation, in order:**

1. **Build the analytic joint-objective policy first** (CEF counter, one trial).
   Gârleanu–Pedersen with the measured decay of the z-score (`plan_diagnostics.py`
   gives κ), the measured covariance and the cost grid.
   - It is the benchmark any learned policy must beat.
   - It may beat the scalar band on its own, because it is the multi-asset version
     the band cannot be.
2. **RL only as a solver for constraints that break the closed form:**
   - whole shares;
   - borrow that flips;
   - Reg T margin;
   - the gross cap;
   - event blackouts (§3.4);
   - MOC once a day.
3. **Train only in a simulator; evaluate only in the harness.** One 13-name
   history is one path, and an RL agent trained on it memorises it.
   - **The simulator:** per-fund OU discounts with the measured κ and σ, NAV
     returns from a factor model, event jumps from the event log's empirical
     rates, a Markov chain for borrow flips from the snapshot, and the cost grid.
   - **Synthetic data tests whether the method behaves, never a claim about the
     market** (`CLAUDE.md`).
   - The learned policy is then frozen and scored once in `evaluate()` on real
     data: turnover-matched against the band and against Gârleanu–Pedersen, gross
     headline and grid, five eras, 2023+ row. It is one CEF trial, and every
     architecture or reward tried before it is counted too.
4. **The kill.** It does not beat the analytic policy at matched turnover. The
   prior is that it rediscovers a band.
   - A real gain would be state-dependence the band lacks, for example trading
     earlier when borrow is about to tighten.
   - But regime-switching and dislocation sizing are dead, so the bar to believe
     that is high.

**Where RL does not belong:**

- **Execution.** One auction at under 1% participation: "there is nothing to
  schedule" (graveyard, Almgren–Chriss).
- **Sleeve allocation by bandits.** With a handful of sleeves and noisy returns,
  a bandit chases noise. The standing rule is Σ⁻¹·IR on measured correlations.
  Shrink the IR estimates (§6.2a), do not learn them online.

**One place RL could be distinctive: sharing the gross cap between sleeves.**

- Event opportunities are sparse and dated. The discount book wants gross every
  day. When an event arrives, how much gross should move from the discount book to
  the event sleeve, and for how long?
- That is a sequential allocation problem with a hard constraint, and the closed
  forms do not cover it.
- **Start with a greedy rule as the control**: an event gets the gross its
  pre-registered size asks for, taken pro rata from the discount book. Consider RL
  only if the greedy rule's cost, measured in the parity waterfall (§5.4), is
  material.

### 6.4 Tier 4: data analysis that raises TC (the highest value per hour)

| analysis | question | status |
|---|---|---|
| **Parity waterfall** (§5.4) | where does modelled gross go before it reaches the broker? | NEW |
| **TCA** | fill against the official close, by side, by name, by day | `<state>/tca.csv` exists (2026-10-07) |
| **Three P&L lines** | fill, auction print, distribution-adjusted | built 2026-10-09/11 |
| **Real-money cost re-run** (plan 0.5) | is the book positive after measured borrow, distributions owed on shorts and real auction fills? | **the gate for capital** |
| **Effective breadth** | how many independent bets do today's weights hold? Eigenvalues of the weight-scaled covariance; the muni-vs-taxable share of risk (it was 92.5% at one measurement `[doc: BRIEF M5]`) | the IBKR dashboard's `/api/factors` did this; deleted, no replacement |
| **Common-holder network** | do our names co-move through shared specialist holders (13F, N-PORT)? It is the "connected stocks" effect (Anton & Polk 2014 [S]) applied to CEFs | NEW; a risk-model input, not a signal |
| **Sequential monitoring** | is the live book still the backtested book? A CUSUM or sequential probability ratio test on daily P&L against the backtest distribution, with the pre-registered H11 statistic and horizon | NEW; it makes "the 60-live-session review" a running test |
| **Capacity curves** | P&L against size, per sleeve, at measured ADV | plan 4.3 |
| **Event-study kit** | one shared function: abnormal discount change around `observed_at`, matched controls, synthetic control for single-fund events, clustered SEs by sponsor and date | NEW; every EVENTS trial uses it, so none rebuilds it |

### 6.5 Model governance (applies to every tier)

- **A model inventory**: every model, its owner, its counter, its pre-registration,
  its validation note, and its live monitoring statistic.
- **A model card per model**: data and dates, features, the point-in-time
  alignment comment (`CLAUDE.md`), known failure modes, and the graveyard
  neighbours it was checked against.
- **Pinned versions and seeds**: library versions in `requirements.txt`, model
  versions for LLMs, seeds recorded in results.
- **Drift monitoring**: for extraction models, a monthly gold-set re-score; for
  signals, the sequential test in §6.4.

---

## 7. Making it deployable institutionally

"Institutional" here means: what an allocator, a prime broker, an auditor or a
regulator would ask before money is at risk, and what a desk must have so a
mistake cannot double the book or break a rule. The desk already has more than
most small shops:

- frozen specs;
- pre-registration;
- counted trials;
- release tags;
- read-only monitors;
- a broker-confirmed record.

What follows is the gap list.

### 7.1 The gap table

| area | have | gap | proposal |
|---|---|---|---|
| **Model risk** (the three lines of defence; SR 11-7 is the reference framework [S]) | first line: the desk; review: `quant-reviewer`, `beta-detector`, `/release-check`; audit: `doc_audit`, `/repro` | no written **validation report** per sleeve; review is a habit, not a gate | each sleeve needs a validation note, by a reviewer who did not build it, before its spec key goes live. `/release-check` refuses without it |
| **Pre-trade compliance** | gates for shortability, exposure, sanity and the late clock | no **restricted list**; no ownership thresholds; no Reg M or Reg SHO price-test awareness | §7.2 |
| **Position limits** | a gross cap; a min-ADV floor | no per-name % of shares outstanding; no % of ADV; no per-sponsor, per-event or per-sleeve limits; no liquidation horizon | spec keys, default absent: per-name days-to-exit at a declared participation rate; per-sponsor net; per-event gross; per-sleeve gross |
| **Risk** | the vol target; the gross cap; HALVE/KILL on broker-confirmed NAV (decided 2026-09-08, armed once W6 lands) | no stress replay on the live book; no deal-break or borrow-recall scenarios | a nightly stress report (read-only): replays of 2008, 2020 and 2022 on today's weights; every open event breaks; every short recalled at once |
| **Operational resilience** | one VM; release tags; a runbook; Key Vault | **single point of failure**; the student subscription disables when its credit or 12 months run out, and **the book stops** (`docs/SYSTEM.md` §5); alerting is logs and dashboard only | a **warm standby with a lease** (§7.3); a heartbeat; a subscription-expiry check in orient; the team lead to revisit alerting for real money (§9) |
| **Audit trail** | `plan_sha`; `STARTED`; `orders.jsonl`; `verify.log`; `equity.csv` | not hash-chained; events and data inputs are not part of the record | the event-sourced book (§7.3) |
| **Broker** | Alpaca paper; one account per book | real-money broker undecided (plan 4.2) | a broker adapter interface; the selection checklist in §7.4 |
| **Track record** | broker-confirmed daily equity; three P&L lines; paper and live kept apart | no composite definition; no independent verification | define the composite now: which account, which P&L line is official, how sleeves enter. Performance-standards compliance and an administrator are counsel and consultant questions |
| **Entity, registration, tax** | — | **not researched; needs counsel** (plan 4.4) | no guess is made here. The questions are listed in §7.5 |

### 7.2 Pre-trade compliance fed by the event log

| check | rule it serves | implementation |
|---|---|---|
| **Restricted list** | names under an event that the pre-registered policy restricts (C1), names under review, names with an unparsed filing | a derived list from event state; the gate refuses any order that opens or increases a short in a restricted name |
| **Short locate** | Reg SHO Rule 203(b)(1) [V, §12j]: a broker-dealer may not accept or make a short sale unless it has borrowed, has arranged to borrow, or has reasonable grounds to believe the security can be borrowed, and it must document this | at Alpaca [V: agent, §12k]: **easy-to-borrow shorts need no locate and pay $0 borrow**. Hard-to-borrow shorts need a locate: `GET /v1/locates/quotes` gives quantity and a fee per share; `POST /v1/locates` takes round lots of 100, single-use and non-refundable, **live accounts only**. Hard-to-borrow shorts are charged short value × rate ÷ 360 a day. **No endpoint publishes the per-symbol rate**, so plan 0.5's "measured borrow" must come from locate quotes and charged fees. The gate requires a locate per opening hard-to-borrow short |
| **Short-sale price test** | Reg SHO Rule 201 [V, §12j]: after a fall of **10% or more from the prior-day close**, short sales may not execute or display at or below the national best bid, **for the rest of that day and the next**. The duty sits on trading centres | how a **MOC short sale** is handled on a price-test day is [U]; ask the real-money broker. Until then the gate flags names under the test, and the plan does not count on those shorts filling |
| **Regulation M Rule 105** | firm-commitment offerings only [V, §12j; N9] | rights offerings and follow-ons enter the event log with their pricing dates and their firm-commitment status; the gate blocks any subscription after a restricted-period short |
| **Ownership thresholds** | **13D/13G** [V, §12j]: over 5%, file within 5 business days (13D) or as 13d-1 requires (13G); "business day" excludes Federal holidays. **ICA §12(d)(1)** [V, §12j]: a fund relying on §3(c)(1)/§3(c)(7) is held to the **3% voting-stock cap** in any registered fund; the 5% and 10% asset tests do not reach it, and Rule 12d1-4 gives a private fund no relief. Control-share provisions many CEFs have adopted [U, not fetched] | per-name % of shares outstanding, measured daily from a resolved share count (§6.1c). At this book's size it never binds, but it must be **measured, not assumed**, before capital grows. **The 3% cap would bind a private-fund structure long before 13D does**: a capacity input to plan 4.3, and a question for counsel (§7.5) |
| **Wash-trade and netting** | Alpaca rejects opposite-side orders in one symbol | already enforced: one netted order per symbol per account; now across sleeves too (§7.3) |

### 7.3 Outside-the-box architecture for an institutional book

1. **The event-sourced book.**
   - Every input (data rows, events, broker messages) and every output (plans,
     orders, fills) goes into append-only, hash-chained logs.
   - The book's state on any date is a pure function of the logs up to that date.
   - That gives three things at once: a **tamper-evident audit trail**; **exact
     replay** of any past decision (the parity waterfall, §5.4, becomes a
     replay); and **research-live parity**, because the research harness reads the
     same event rows.
   - `plan_sha` is the seed of this. Extend it to cover the input rows the plan
     used.
2. **Sleeves as plug-ins with netting and attribution.**
   - Each sleeve returns `PositionTarget`s through the existing `Sleeve`
     interface (`src/deploy/sleeve.py`).
   - A **book combiner** nets them per symbol into one order (the wash-trade
     rule), enforces book-level limits, and allocates each fill back to the sleeves
     pro rata to their target change. Each sleeve keeps its own P&L line,
     following the "seventeen sleeves, one combined book" ruling (2026-09-09).
   - **Internal crossing is a free benefit.** When the discount sleeve sells what
     the event sleeve buys, no order goes out. Measure the saving in the parity
     waterfall.
3. **A warm standby that can never be armed beside prod.**
   - A second machine runs the full session in `DRY_RUN=1` every day: decide,
     gate, score, send nothing. That doubles as a daily parity check.
   - Arming the standby requires taking a **lease**: a lock object prod renews
     every few minutes, and the standby may arm only after it has expired and
     been taken atomically.
   - That turns `CLAUDE.md`'s "never two schedulers armed for one account" from a
     procedure into a mechanism. orient already warns if both are armed; the lease
     makes it impossible.
4. **Shadow sleeves on live data.**
   - Every candidate sleeve that passes its trial runs in DRY on the VM, on live
     data, before it gets capital. Its plans and modelled P&L are recorded beside
     the live book.
   - This is **not evidence** about the market. Modelled sessions are not evidence
     (`CLAUDE.md`). It is an **operational** test: does the sleeve's data arrive,
     does its plan net cleanly, would it have hit a limit?
   - It is also a forward record of the *signal*, which the pre-registered live
     statistic (H11) can start reading on day one of capital.
5. **The agents as the second line.**
   - Adversarial review becomes part of the release gate. `beta-detector` must fail
     to break a sleeve's claim, and `quant-reviewer` must pass its code, before
     `/release-check` can say go.
   - Their reports are saved with the release tag, which is what an auditor would
     ask for.
6. **Corporate-action elections as execution, not alpha.**
   - If the book is **already long** a fund running a NAV tender, tendering the
     shares captures (NAV × tender price fraction − market price) on the accepted
     portion. That is better than selling at the close.
   - If it holds a fund with a rights offering, exercising, or selling
     transferable rights, beats letting them lapse into dilution.
   - "Tender capture alone" is dead as a *strategy*. As an *execution choice on a
     position the book already holds* it costs no trial and raises TC.
   - It needs a broker that supports voluntary elections (§7.4). Paper cannot
     measure it.
   - **A fixed fee can eat it at our size.** Alpaca's Broker API FAQ charges
     "$100 per client per voluntary corporate action", which covers tenders.
     Whether that applies to a Trading API account is [U] (§12k). Compare the fee
     with (tender price − market price) × expected accepted shares, per event,
     before electing.
7. **Securities-lending income on the long side.**
   - Our longs are CEFs, many of them hard to borrow. Lending them out earns a fee
     that offsets the borrow cost on our shorts.
   - **Alpaca runs fully-paid lending for Trading API accounts** [V: agent,
     §12k]. Real-money items only; paper cannot show them:
     - it is opt-in for the **whole portfolio**: names cannot be chosen;
     - the lender gets a share of the interest ("up to 50%" for Elite accounts,
       about 20% in the standard example);
     - lent shares **lose their vote**, which matters for N1 and N8 proxy events;
     - the dividend is replaced by a **payment in lieu**. For muni CEFs that can
       change the income's tax character (§7.5, counsel).
8. **Liquidity provision in the closing auction** (later; broker-dependent; [U]).
   Some venues accept closing orders that only offset the auction imbalance. A
   desk that already trades every close might take the other side of the
   imbalance in its own names. Whether any candidate broker routes such orders,
   and whether it fits order-path rule 3, is unresearched.

### 7.4 Real-money broker selection checklist (plan 4.2)

| need | why |
|---|---|
| MOC (`cls`) in all our names, with a stated cut-off per venue | order-path rule 3; plan 0.2 |
| Locates API and per-name borrow fees, daily | §7.2; plan 0.5 needs measured borrow |
| Fully paid securities lending | §7.3 (7) |
| **Voluntary corporate-action elections** by API or a clear manual process (tenders, rights exercise, oversubscription) | §7.3 (6) |
| Daily positions, activities and fees by API | the broker is the fact (`docs/SYSTEM.md` §0) |
| One account per book, sub-accounts or models per sleeve | attribution |
| Futures in the same or a linked account | hedging NAV beta (SCALING §3, stage 3) |
| Portfolio-margin eligibility rules for a small entity | plan 4.2 |
| Options level 3 | the GAMMA test's condition 6 |

### 7.5 Questions only counsel can answer (listed, not guessed)

- the entity (a private fund, managed accounts, or something else) and adviser
  registration;
- how §12(d)(1) applies to the chosen entity when it owns CEFs (§11 has the
  statute text, not advice);
- proxy-voting policy obligations if the firm becomes a registered adviser;
- tax character of muni-CEF distributions in the chosen entity, and of
  substitute payments on shorts;
- information barriers if the desk ever speaks to fund boards, sponsors or
  activists (material non-public information).

---

## 8. The ordered work list

| order | item | stream | trials | gate or blocker |
|---|---|---|---|---|
| 1 | **§5.1 gross-cap send-time fix**, with its failing test | P | 0 | `/release-check`; team lead's go |
| 2 | **SEC user-agent** → plan 0.7 EDGAR fetcher → **event log** (§3), with the research parquet and the point-in-time `events_at(t)` and its runtime assertion | P + R | 0 | the team lead's string |
| 3 | §5.4 **parity waterfall** and §5.2 **shortability skip measurement** | R | 0 | — |
| 4 | §6.1a **LLM extraction** with a gold set; §6.1b **data-quality events**; §6.1c **entity resolution** | R | 0 | 2 |
| 5 | Zero-trial gates: G6, G1a–c, G7, the 2d count; NEW: N1 census, N3 bond-holiday measurement, N6 episode count, N8 sibling base rate | R | 0 | 2, 4 |
| 6 | **C1** (with N1's "no short inside a live window" and N2's release dates) | R → P | CEF 1 | G6 |
| 7 | **Gârleanu–Pedersen joint-objective policy** (§6.3) | R | CEF 1 | `plan_diagnostics.py` κ re-run |
| 8 | **§5.3 long-only eligibility** | R | CEF 1 | 3 (the skip measurement) |
| 9 | **E1 merger pair**; N1 sleeve if its census passes | R | EVENTS 1–2 | G1a–c; N1 count ≥ about 30 windows |
| 10 | Plan orders 3–12 (XASSET, GAMMA, E2–E4, C2, C3, B1) | R | per plan | per plan |
| 11 | §6.2d pooled model, only after B1 | R | CEF, the declared grid | B1 data; §6.0 protocol |
| 12 | §6.3 RL solver, only if 7 leaves a measured constraint cost | R | CEF, counted with every architecture tried | 7 |
| 13 | §7: warm standby with lease; restricted list; stress report; validation-note gate | P | 0 | real-capital timing |

**P** = production (`quantt/`, the live path: a failing test first,
`/release-check`, release tag, `install_vm`). **R** = research (`scripts/`, never on
the live path).

---

## 9. Decisions for the team lead

1. **The SEC contact user-agent** for EDGAR (plan 0.7). It blocks everything in §3
   and §4.
2. **The §5.1 fix**: approve building it (test first, `/release-check`).
3. **The intraday subtract rule** (§2.3): may the scheduled runner remove or
   shrink today's orders on a same-day event, and on a live account cancel queued
   `cls` orders before 15:50?
4. **Long-only eligibility** (§5.3): worth a CEF trial?
5. **Counters for the new ideas:** N1 and N8 on EVENTS; N4 and N6 on NPORT; N5 on
   POSITIONING; the pooled model (§6.2d) and the RL solver (§6.3) on CEF. Confirm
   or re-assign.
6. **Alerting for real money:** logs and dashboard only was decided for paper
   (2026-09-21, confirmed 2026-09-28). Does it stand once capital is live?
7. **When to engage counsel** for §7.5.

---

## 10. What is not established

- **No idea in this note has been tested.** Every NEW item is a mechanism and a
  design, with a 0-trial first step.
- **Figures copied from other notes are marked `[doc]` and were not re-run here.**
  The agent figures in SCALING §7 must be reproduced in the repo before any
  pre-registration rests on them (plan 0.9).
- **Paper cannot measure most of §7:** borrow fees, locates, lending income,
  elections, real auction fills. Alpaca paper charges no borrow, credits no
  dividends and runs no auction (`CLAUDE.md` landmine 1).
- **The literature cited [S] was not fetched for this note.** §11 lists it for
  `docs/REFERENCES.md`.

---

## 11. Facts verified for this note, and references to fetch

**Two read-only verification passes ran on 2026-10-12.** "[V: agent]" means a
desk agent fetched and read the primary source that day; this note's author did
not re-read it (the convention of `RESEARCH_AGENDA_2026-10-08.md`). The
regulatory pass wrote its findings into **`docs/REFERENCES.md` §12j**, and
amended two existing rows there in place, dated: §18 asset coverage, and the
tender-pricing staff position. **Read §12j for the exact rule text and URLs.**
Rows still [U] may not be cited by a pre-registration until fetched.

| # | claim this note relies on | used in | status, 2026-10-12 | source |
|---|---|---|---|---|
| 1 | Reg M Rule 105 covers firm-commitment offerings for cash only; no clause names rights offerings, at-the-market offerings or CEFs | N9, §7.2 | **[V: agent] PARTLY.** Scope verified; whether a given CEF rights offering is firm-commitment must be read from its prospectus | 17 CFR 242.105 |
| 2 | ICA §12(d)(1): a §3(c)(1)/(7) private fund is held to the 3% voting-stock cap only; Rule 12d1-4 gives it no relief | §7.2, §7.5 | **[V: agent]** statute and rule. That managed accounts which are not investment companies fall outside §12(d)(1) is the agent's inference [U]: counsel | 15 U.S.C. 80a-12(d)(1), 80a-3(c); 17 CFR 270.12d1-4 |
| 3 | Reg SHO 203(b)(1) locate; Rule 201: a 10% fall from the prior close, for the rest of the day and the next | §7.2 | **[V: agent]**. How a MOC short is handled under Rule 201 is [U] | 17 CFR 242.201, 242.203 |
| 4 | 13D: over 5%, within 5 business days; 13G deadlines by filer type; business days exclude Federal holidays | §7.2 | **[V: agent]** | 17 CFR 240.13d-1, 13d-2 |
| 5 | EDGAR: transmission commencing after 5:30 p.m. ET is filed the next business day (13D/G and Forms 3/4/5 until 10 p.m.); `acceptanceDateTime` is in **UTC**; fair access 10 requests/second with a declared User-Agent | §3.3, §3.6 | **[V: agent]**, with one correction to this note's first draft: the cut-off is keyed to when transmission *commences*, not to acceptance | 17 CFR 232.13(a); data.sec.gov; sec.gov "Accessing EDGAR Data" |
| 6 | SIFMA 2026: Oct 12 and Nov 11 are bond-market holidays with NYSE open; the early closes | N3 | **[V: agent]** | sifma.org; nyse.com |
| 7 | CEF tender priced at NAV at the close of its last day | N2, §4 | **[U] as an SEC position.** Only a sponsor's N-2 describes it; Rule 13e-4 has no such text and no staff letter was found | Nuveen N-2, 2022-10-04; 17 CFR 240.13e-4 |
| 8 | Concrete conditional-tender programmes in US CEFs | N1, §4.2 | **[V: agent]** six examples, including MHD and MQY in BlackRock's 2026 programme. No aggregate count was found [S, negative] | EDGAR filings and BlackRock releases, `docs/REFERENCES.md` §12k |
| 9 | Alpaca news: Benzinga, from 2015, REST and websocket; CEF coverage | §3.3 | **[V: agent] PARTLY.** Source and endpoints verified; CEF coverage is not documented, so measure it | docs.alpaca.markets, §12k |
| 10 | Alpaca locates (live only, round lots, single-use); no per-symbol borrow-rate endpoint; $0 borrow on easy-to-borrow shorts; fully-paid lending terms; a $100 voluntary-action fee on the Broker API | §7.2, §7.3 | **[V: agent]**. Whether the $100 fee applies to Trading API accounts is [U] | docs.alpaca.markets; Alpaca blog 2025-07-29; §12k |
| 11 | `trade_updates` on paper: fill, partial-fill, cancel, expiry and replace events; random partial fills 10% of the time | §3.3 | **[V: agent]** from the docs; never observed by our code | docs.alpaca.markets, §12k |
| 12 | 1940 Act §18: 300% for debt, 200% for preferred, tested at issuance; below them, no common distributions or repurchases; **no maintenance test that compels redemption** | N6 | **[V: agent] PARTLY.** The percentages are right; "forces deleveraging" was wrong (corrected in N6, and in `docs/BRIEF.md` §3 with a dated note, 2026-10-12) | 15 U.S.C. 80a-18 |
| 13 | Saba–BlackRock settlement of 2025-01-20: BMEZ 40% and BTX (formerly BIGZ) 50% at 99.5% of NAV; the standstill runs to the later of the day after the 2027 annual meeting and 2027-08-31, not "3 years" | SCALING §1 | **[V: agent]** from the primary filing. Corrected visibly in `docs/REFERENCES.md` and `SCALING_RESEARCH_2026-10-08.md` §1. `results/data/universe_2026-10-08/universe_map.csv` still lists `BIGZ` | BTT proxy, §12k |

**Literature cited [S], not fetched for this note:**

- Gârleanu & Pedersen (2013), *Dynamic Trading with Predictable Returns and
  Transaction Costs*, Journal of Finance;
- Coval & Stafford (2007), *Asset Fire Sales (and Purchases) in Equity Markets*,
  Journal of Financial Economics;
- López de Prado (2018), *Advances in Financial Machine Learning* (purged and
  combinatorial cross-validation);
- Glasserman & Lin (2023), on look-ahead bias in GPT-based return predictions;
- Anton & Polk (2014), *Connected Stocks*, Journal of Finance;
- Federal Reserve SR 11-7 (2011), model risk management guidance.

Already in the repo and cited from it: Constantinides (1986), Davis & Norman
(1990), Alexander & Peterson (2017) (`docs/BRIEF.md`).
