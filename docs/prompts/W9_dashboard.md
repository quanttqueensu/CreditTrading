# W9 — The dashboard: five questions, one broker session, push not poll

**Status:** queued — no commit references it, no deliverable of its exists, no trial spent.
**Reads first:** `00_BRIEF.md` §4 (the scoreboard), §6 (house rules).
**Lever:** the desk's instrument. **Trials:** 0. **Touches the live book:** no.
The dashboard stays **read-only with exactly one POST route** (`/api/connect`,
which starts the gateway). No code path from the dashboard transmits an order.
**Prerequisites:** Stage 1 stands alone and should run early. Stages 3–4
consume payloads defined in W5 (`/api/orders`, the journal), W7 (cost and
turnover CSVs), W8 (the borrow payload), W10 (`/api/groups`).
**Supersedes:** P0.3, P2.1, P2.2, P2.3, P3.1, P3.2, P3.3, P3.5, P3.6, P4.1,
P4.2.

---

## Paste from here

You are working on `dashboard/server.py` (Flask, ~1,700 lines) and
`dashboard/static/index.html` (single file, inline CSS/JS/SVG, no libraries,
~1,850 lines) in the QUANTT CEF repo. Read `docs/prompts/00_BRIEF.md` first —
§4 tells you which numbers matter and §6 the house rules this page inherits. The dashboard is a local read-only PM monitor at
http://127.0.0.1:8787 for a $500k IBKR paper book. Read both files in full and
the docstring at the top of `server.py` twice — "WHY LOCAL, AND WHY READ-ONLY"
and "NO SILENT FALLBACKS". Those two principles are not negotiable in anything
you do here. Then open the page and click every tab twice: once with the
gateway up, once with it down.

Four stages. **Stage 1 must land before the others**; it is the reason the page
is slow and flickering, and stages 3–4 assume its broker session and panel
cache.

---

## Stage 1 — Hardening: one broker session, cached panels, no null derefs

Six defects, each verified during the 2026-09-07 review.

**D1. Null dereference when the broker is down.** `loadLive()` (~line 826), in
its `!d.ok` branch, does `$("#bookExp").innerHTML = nodata(...)`. **There is no
element with id `bookExp`.** `$()` returns null, the assignment throws, and the
rest of the branch — clearing `#reconcile`, `#recChip`, `#attrProblems`, calling
`drawState()` — never runs. The state strip keeps showing the last good
reconcile state on a page whose broker is unreachable.

**D2. Undefined severity classes.** `loadFactors()` uses `chip ${sev}` with
`sev = "bad"` and `tileEl(..., "neg")`; `drawScoreboard()` uses `chip bad`. The
CSS defines `.chip.crit` and `.down`, not `.bad` or `.neg`. Visible today: the
top "Effective breadth 1.17" tile is red (it uses `down`), the risk-card
"EFFECTIVE BREADTH 1.17" tile is white, and the "BR_eff 1.17 of 17" chip is
grey. **The single most important risk number on the page renders as neutral in
two of its three places.**

**D3. Three transient broker connections.** `_probe_broker()` opens an IB
session with clientId 205; `_portfolio()` opens clientId 302 for every
`/api/live` call **and** again under the `factor_pos` cache key for
`/api/factors`. The page polls `/api/live` every 5 seconds, so the server
connects and disconnects roughly every 5 seconds forever. During the review the
header showed "Broker down 127.0.0.1:4002" in one screenshot while the
Positions tab, seconds later, showed "Broker connected" and 34 live positions.
The account was fine; the probe collided with a concurrent connect.

**D4. Panels re-read parquet on every call.** `_signal_frame()`, `api_trades()`,
`_decompose()`, `_br_history()` and `_freshness()` each call `pd.read_parquet`
on `cef_prices.parquet` (266k rows) and `cef_nav.parquet`. `/api/factors` runs
`_decompose` once per session in `_br_history` for 40 sessions. `/api/verify`
runs preflight, which probes the broker again.

**D5. Sequential client fetches.** `loadSlow()` awaits `/api/signal`, then
`/api/benchmarks`, then `/api/provenance`, then eight draw steps, in sequence.
First paint waits on the slowest.

**D6. Network fonts on a local-only page.** Inter and JetBrains Mono load from
fonts.googleapis.com; offline, the page falls back to system fonts mid-render.

### The work

**1. One broker session, owned by the server.** `dashboard/broker_session.py`:

- One `ib_async.IB()` connection, `readonly=True`, a single clientId from
  `config/.env` (`DASHBOARD_CLIENT_ID`, default 900), documented as not
  colliding with W3's morning/retry/capture jobs or `DATA_CLIENT_ID`. W2's
  audit lists every id in use.
- A background thread with its own asyncio loop. Connects at server start,
  reconnects with exponential backoff (2s → 60s), and **never raises into a
  request handler**.
- Subscribes to `updatePortfolioEvent`, `accountSummaryEvent`, `openOrderEvent`,
  `orderStatusEvent`, `execDetailsEvent`, `connectedEvent`,
  `disconnectedEvent`. Each event updates an in-memory snapshot under a lock:
  positions, account tags (NetLiquidation, GrossPositionValue, TotalCashValue,
  ExcessLiquidity, Cushion, MaintMarginReq, AvailableFunds, **AccountType**),
  open orders, today's fills, and `updated_at` per section.
- `snapshot()` returns a deep copy plus `ok`, `connected_since`, `last_error`,
  `endpoint`. If the connection is down, `ok: False` with the reason, **and the
  last positions are still returned, stamped `stale: True` with their
  `updated_at`** — so the page shows them greyed with a time, never as live.
- `_probe_broker`, `_portfolio` and the `factor_pos` cache are replaced by
  snapshot reads. `ops/preflight.py`'s own probe is left alone (it runs in the
  scheduled job); `api_verify` either passes the snapshot through a
  `want_probe=False` argument or reports "checked via dashboard session" with
  the timestamp.

Test: run the server, `watch -n1 curl -s :8787/api/status`, restart the gateway,
confirm the header goes down and back up **once** with no flicker, and that
`lsof` shows one Python process holding one socket to port 4002.

**2. Fix D1 and D2.** Remove the `#bookExp` reference (the exposure card is not
wanted; the Positions tiles carry it). Map `bad` → `crit` and `neg` → `down`,
then grep for any other undefined class. Simulate broker-down and confirm every
panel degrades independently and the state strip updates.

**3. Cache the panels by mtime.** A `PanelCache` keyed on `(path, st_mtime_ns)`
loading `cef_prices.parquet`, `cef_nav.parquet`, `cef_universe.csv`,
`cef_borrow.csv`, `cef_distributions.parquet`, plus W3's `nav_channel_log.csv`
and `price_source_log.csv` so the freshness strip can say **which channel**
today's pair came from. The pivoted frames (`px`, `nav`, `vol`, `disc`) are
cached too. **No TTL: the file's mtime is the truth.** Log a line on reload.
Measure before and after with a 20-request loop against `/api/signal`,
`/api/trades`, `/api/factors`, `/api/verify` and report p50/p95 in the commit
message.

**4. Parallel client fetches** with `Promise.allSettled`, keeping `step()`'s
per-panel error isolation: a rejected promise renders that panel's `nodata()`
and nothing else.

**5. Vendor the fonts** — Inter 400/500/600/700 and JetBrains Mono 400/500/600
as woff2 in `dashboard/static/fonts/`, `@font-face` with `font-display: swap`,
Google Fonts links removed. Confirm the page renders identically offline.

**6. Regression pass.** Every endpoint's JSON unchanged in shape except the new
`stale`/`updated_at` fields; diff a capture of each endpoint before and after
with volatile fields stripped. `python3 -m pytest src -q` green.

---

## Stage 2 — Information architecture and the visual system

### Five screens, in the order a PM asks

1. **Is it running?** Broker, gateway, last session (armed or not, and why
   not), the session-progress strip and log tail (W3 Part D), data freshness by
   channel, alerts, next session time.
2. **Is it real?** Which sessions have broker-confirmed fills and which are
   modelled; realised cost against the 32.6bp breakeven; realised turnover
   against the pre-registered 17.6×/yr; the NAV line broken at the first
   unconfirmed session. This book armed on 3 of 26 sessions and 22 of 24 ledger
   dates were modelled until the epoch reset. **The second question exists
   because of that history.**
3. **What do we hold and what is the risk?** The blotter, group subtotals,
   gross, net, effective breadth, the muni-vs-taxable share of variance, net
   muni weight, borrow drag, utilisation, the signal columns.
4. **What trades today?** The order list the executor will send, the lifecycle
   after 15:50, and for names that will not trade, how far each is from its
   band edge.
5. **What did it cost?** Fill-level shortfall, the session series, the running
   mean against breakeven, the impact test.

Everything else — benchmarks (empty until each reference book has two NAV rows),
independent re-derivation checks, the risk-limits table, doctor's plumbing rows,
inference statistics (W1) — moves into a **More** drawer reached from screen 1's
status line, and each surfaces on screen 1 **only when it is not green**.

### What to cut, and why

- The **Book** tab today is eight "n/a" tiles and a banner explaining the n/a.
  Eight identical reasons are one sentence. It becomes screen 2.
- The **Signal** tab duplicates Positions with different columns. Merge: the
  blotter carries z, discount, target weight and gap, with the
  valuation-dispersion bar chart above it as the only chart on screen 3.
- The **Benchmarks** tab has one plotted series. Until three books have ≥ 20
  sessions it is one drawer row: "Benchmarks: 0 of 5 comparable".
- The **Controls** tab becomes the drawer; its chip lives on screen 1.
- Four masthead numbers duplicate screen 3. Keep NAV and as-of; drop the rest.

### The visual system

The reference is a professional trading blotter: dense, quiet, every number
aligned, colour only where it carries a verdict.

**Type** — one modular scale, five sizes, nothing else: screen heading 15px
Inter 600 (−0.01em); body/labels 13px Inter 400/500; table cells and numbers
12px JetBrains Mono with `font-variant-numeric: tabular-nums`; column headers
and units 11px Inter 500 (+0.02em, sentence case, **never all-caps with
tracking**); KPI value 20px Inter 600 (−0.02em, proportional-nums). No 9.5px
uppercase micro-labels — if a label needs to be that small it is not needed.

**Colour** — neutrals (plane, surface, raised, sunken, ink, ink-2, ink-muted,
hair, axis, grid) plus exactly: `--good` / `--warn` / `--crit` for status, each
with a bg/ink pair; `--cheap` / `--rich` for the signal's two poles; `--up` /
`--down` for signed P&L. **Delete the eight categorical slots `--s1`…`--s8`** —
no chart has more than three series, and the benchmark chart gets strategy =
ink, benchmarks = ink-muted with dash patterns, not hues. Keep the
`[data-theme]` double declaration so the toggle wins both ways.

**Density** — 8px grid, 28px table rows, 12px 14px card padding. No card inside
a card; where a boundary carries meaning use a card, otherwise a 1px hairline.
KPI tiles are a single row of at most six, never a grid of eight.

**Glyphs** — replace every unicode glyph (◇ ▢ ✓ ! ◷ ⚠) with a 12px inline SVG
`<symbol>` sprite: check, alert, dot, clock, lock. Or no glyph; a coloured chip
with a word is usually enough.

**Motion** — keep the 0.9s flash on a changed cell; remove the pulsing
freshness dot (freshness is a timestamp).

**Units** in the column header, once, never in the cell. Signed values carry a
real minus (U+2212). Money has no decimals above $1,000.

**States** — a stale value is greyed with its timestamp, not hidden; an
unavailable value is `nodata(title, reason)` with the **server's** reason; a
loading value is a hairline skeleton, not "loading…". Keep `nodata()`; it is
the most important component on the page. But **one gap, one sentence**: when a
whole card is unavailable for one reason, render one block, not one per tile.

**Print** — `@media print`: screens 3 and 4 each fit one landscape page, no
drawer, no masthead buttons, black on white.

**Rules the redesign inherits.** Colour carries a verdict or nothing. Every
panel degrades independently (`step()` stays). Tabs are deep-linkable
(`#running`, `#real`, `#book`, `#trades`, `#cost`) and the last tab is
remembered. Charts measure their container and redraw on tab show and resize.
Provenance is one fact per ledger: one chip on screen 2's NAV card and one word
("modelled") wherever a modelled number appears.

Server changes in this stage are **payload reshaping only** — a `/api/screen1`
assembling status, freshness, heartbeat, alert flags and next-session timing in
one call so screen 1 paints in one round trip. No new broker paths.

Then: a contrast check script parsing both token sets, reporting every
text/background pair below 4.5:1 and every chart-mark/background pair below
3:1; fix until clean and commit its output. Screenshots of every screen at
1440×900 in both themes with the gateway up and down into `docs/dashboard/`,
plus `docs/dashboard/README.md` describing each screen's question and sources.
A 20-line style guide as a comment at the top of the CSS.

---

## Stage 3 — The screens

### Screen 2, "Is it real?" — replace the n/a wall

The ledger was re-seeded on 2026-09-08 and the Book tab shows NAV $500,000,
P&L $0, return 0.00%, five "n/a" tiles and a banner explaining the n/a. That is
honest and useless. A PM opening the page already knows things that are not on
the screen.

Top: one KPI strip, six tiles — NAV (ledger) · Intraday P&L (broker, live) ·
Confirmed sessions / traded sessions · Realised cost, MOC sessions (mean ± SE
vs 32.6) · Realised turnover ×/yr vs 17.6 · Borrow drag $/yr on the current
book. Each carries its source and as-of in the hover title; the intraday tile
is stamped with the snapshot time and greys when the broker session is down.

Middle: **the NAV card**. The line breaks at the first modelled session, with
the provenance strip beneath. Add a shaded reference band — the backtest's
expected path at the band policy's ann return and vol, drawn as mean ± 1 sd
growing with √t from the epoch, **labelled "backtest reference, not a forecast;
survivor-only panel; price-return convention until W4 lands"**. With one NAV row
the band still draws, so the card is never empty.

Bottom: the **pre-registered readouts** card (W7's data): four rows — realised
turnover vs 17.6, holding period vs ~12, realised cost vs 32.6bp, armed
sessions ÷ trading days — each with expected, realised, "n of 20 sessions", and
a state (not enough data / on track / review). **This card replaces the eight
n/a tiles as the thing screen 2 answers.**

Right rail: **cost to date** — each session as a row with method, fills,
modelled, realised, excess; the abandoned overnight-market method struck
through with its reason; the running MOC mean with its SE and the sessions
needed to reach SE ≤ 1bp.

Sharpe anywhere on this screen appears as `value ± SE (n sessions; MinTRL N)`
from W1, or not at all.

`/api/real` returns `nav`, `provenance`, `intraday` (broker snapshot restricted
to the CEF universe, by name and group), `cost`, `turnover`, `borrow`,
`reference` (ann return and vol, computed once from the harness and cached in
`results/cef/reference_band.json` with its run date). Every block carries
`asof` and `source`; a block that cannot be built carries `reason`.

### Screen 3, the blotter — one table

Today the same 17 names appear in three places with three column sets. A trader
has to hold three tables in their head to answer "what is NAD doing and what
happens to it today?". **One row per name, every column that carries a
decision, sorted by what is about to happen.**

| column | definition | source |
|---|---|---|
| ticker, group | | universe.csv |
| side | LONG / SHORT / flat | broker snapshot |
| held wt | qty × last ÷ sleeve NAV | snapshot, ledger NAV |
| target wt | the sleeve's frictionless target | `/api/signal` |
| gap | target − held | derived |
| **dist. to edge** | \|gap\| − band width; negative = inside, will not trade. **Default sort, ascending** | derived |
| today | BUY/SELL n shares, or "hold" | `/api/trades` |
| z, discount % | | `/api/signal` |
| NAV age (bd), NAV channel | | nav panel, W3's channel log |
| price, 1c half-spread bp | 0.005/price × 1e4 | price panel |
| ADV $m, participation % | | price panel, W7 |
| fee %, pool, utilisation | our short ÷ pool; **crit above 25%** | W8's payload |
| borrow $/yr | short MV × fee | derived |
| next ex-date / record date | flag within 2 sessions; **recall watch** (W8 Part D) | distributions + declared |
| unrealised $ | | snapshot |
| last fill vs decision bp | most recent session this name traded | W7's shortfall log |

Names in the frozen universe with no position stay in the table, flat, so the
trader sees what is about to enter. Names held by another book are not here;
they are the account, not the book. Group subtotal rows (muni / multi / hy /
loan) carry gross, net, n, borrow $/yr, unrealised; then a book total.

Colour carries a verdict only: distance to edge within 1 point of trading
(warn), utilisation > 25% (crit), NAV age > `max_nav_age_bd` (crit), tick bp >
10 (warn), ex-date tomorrow (warn), record date inside 5 sessions on a short
above φ (crit).

Above the table, one line: "Held = broker snapshot at HH:MM:SS · ledger agrees
/ N material breaks". Above that, `drawZ` (the diverging bar of z against
today's mean) at 180px, the only chart on this screen; hovering a bar
highlights the row.

`/api/blotter` assembles every row from the cached panels in **one call**. Each
cell that cannot be computed is `null` with a sibling `<col>_reason` string
rendered on hover. **No medians, no zeros for missing.** Sorting is client-side
on any column. Clicking a ticker opens the drill-down.

### Screen 3 detail — per-name drill-down (`#name/NAD`)

Answers: "Why are we short NAD at 18.6% of NAV, how long have we been, what
would make the band move it, and what has it cost to hold?"

1. **Header** — ticker, longName, group, price, NAV, discount, z, side, held
   weight, target, distance to edge, fee, utilisation. The same numbers as the
   blotter row.
2. **Discount chart, 500 sessions** — the discount, its 252-day rolling mean,
   ±1 and ±2 sd shaded. **Exactly the quantities the z-score uses**, with the
   one-day shift applied, so the trader sees the signal's own frame of
   reference. Mark the last value. Mark ex-dates as small x-axis ticks.
   **Label them correctly:** the distribution leaves the fund's assets, so NAV
   drops on the ex-date too and the discount barely moves — W4 Part A measures
   the real coefficient; use it in the tooltip and do not repeat the old claim
   that an ex-date moves price and not NAV.
3. **Price vs NAV**, same window, two lines, log scale, so convergence reads as
   the lines meeting.
4. **Our position**, same window: held weight as a step line, fills from
   `broker_fills.csv` as dots (buy above, sell below) sized by notional,
   modelled-only sessions shaded.
5. **Borrow**, when there is history: fee and pool as two small lines, with
   record dates marked; "1 day of data" until there is more. Never interpolate.
6. **Measured attributes** from `per_name_resolution.py` (cached daily):
   half-life, discount sd, price vol, tick bp, ADV, and the derived per-name
   band width beside the live 4.8%, with the sentence from
   PER_NAME_ARCHITECTURE: *"an expensive name is not a bad name, it is a slow
   one."*
7. **Recent sessions** — last 10 for this name: date, decision, order, fill,
   fill vs decision bp, provenance.

`/api/name/<ticker>` validates against the frozen universe plus the 27 (a name
in the csv but not traded gets charts and "not in the live universe"); unknown
ticker → 404 with a JSON reason. Reads cached panels only. Renders in under
300ms warm; the header's z equals the z recomputed from the chart's last
discount, mu and sd to 2 dp (assert in a test against `_signal_frame`).

### Screen 3 detail — the group view

The risk panel says PC2 is 92.5% of variance and net muni weight is −74.9%. It
does not say the thing a trader needs: **the book is, in effect, one trade —
short the muni-CEF discount against the taxable-CEF discount, at some level of
that spread, with a borrow bill attached.** Nobody sized that trade; the
demeaning produced it.

- **Group table:** group, n, gross wt, net wt, mean z, mean discount, borrow
  $/yr, fee-weighted, unrealised, and share of book variance from the same
  Ledoit-Wolf Σ `_decompose` fits (own plus cross terms, as a share of `w'Σw`).
- **The spread chart:** `S_t` = equal-weight mean discount of the muni names
  minus the mean of the others on the eligible set each day, five years, with
  its own 252-day rolling mean and ±1/±2 sd bands — the same construction as
  the per-name z, so the trader reads it the same way — plus its current z. A
  marker: "book is SHORT this spread; PC2 loading 92.5%; net muni weight
  −74.9%". A smaller second panel for multi-minus-rest.
- **A one-line reading, computed not written:** "Muni-vs-taxable spread is at
  z = ±x.x against its own history; the book is short it. Historical net Sharpe
  of the live policy by spread-z quintile: …" cached in
  `results/cef/spread_quintiles.json`. **It is a mirror, not a rule**, and the
  footer must say so: *"Sizing on this level was measured and lowers Sharpe
  (PLAN §3.1). This panel is a mirror."*
- **History sparkline:** BR_eff and PC2 share per session, labelled
  ledger-derived.

`/api/groups`: groups come from the universe csv; a name with no group
**raises** (it cannot be "other"). Acceptance: group gross and net sum to the
masthead's within rounding; variance shares plus cross terms sum to 100%; the
chart's current z matches the one-line reading.

### Screen 3 detail — the borrow desk

Why it is on screen: borrow costs 3.62% on today's book, $13,732/yr, 2.75% of
capital — **more than half the strategy's expected net return, and it is not on
any screen.** Availability is separate: NAD's visible pool is 3,000 shares
against our 8,129 short; we hold it, but a recall leaves nothing to re-borrow
and we cannot add. And fees move with the fund's own premium, which is the
signal, so a short can get more expensive the same week it gets more
attractive.

Render W8's payload: the per-name table (every universe name, greyed when not
short), book totals for the held book **and** for the frictionless target from
`/api/signal` — so the trader sees what today's orders would do to the bill —
the capacity line, the recall watch, and per-name fee/pool history once there
is more than one date.

**Acceptance is self-consistency, not pinned values.** Do not write "NAD shows
271%" into a test — the borrow panel is a live file and every one of those
numbers changes. Assert instead that:

- utilisation equals our short shares ÷ the pool for that name **on that date's
  row**, and renders crit above φ and warn above the lower threshold;
- book drag equals the sum of per-name short MV × fee, and matches the same
  figure computed independently from the positions file;
- a name with **no** borrow row on the latest date renders its reason and the
  totals carry `partial: true` listing it;
- **no cell is ever populated by a median, a group mean, or a carried-forward
  value** — the strongest test on this screen, and the one most likely to be
  quietly violated later.

Then, as a *smoke* check rather than an assertion, eyeball one high-utilisation
name, one expensive-but-plentiful name and one cheap-to-borrow premium name and
confirm each renders the severity you would expect. **The panel must not imply
that a fund's premium drives its borrow fee** — that relationship is unconfirmed
and at least one name in the book contradicts it.

### Screen 4 — today's orders, and the event calendar

Order lifecycle from W5's `/api/orders`: before the close, each order with its
state, a resting indicator and the **15:50 commitment marker**; after the close,
fills as they arrive with `exec_bp` coloured by sign, a session total, and the
count still unfilled. An unfilled MOC after the close is a red row. "Held, no
order" expands into the distance-to-edge list.

**The event calendar**, next 10 sessions, one row per day:

- NYSE holidays and early closes from `ops/schedule/nyse_calendar.py`.
- **Bond-market holidays on which the NYSE trades** — Columbus/Indigenous
  Peoples' Day and Veterans Day. On those days price moves and NAV is carried
  forward stale, producing a mechanical discount swing. W4 Part C decides how
  the panel treats them; the calendar must flag them either way.
- Ex-dates in the universe (ticker, amount, and the implied one-day discount
  effect **computed with W4's measured coefficient**, not assumed), and
  **record dates**, which are what drive recall (W8 Part D).
- Names whose NAV routinely publishes late: the fraction of the last 60
  sessions where the name's NAV date lagged the panel max, per channel.
- Manual events from `ops/books/cef_live/events.yaml`:

```yaml
- ticker: NAD
  kind: tender | rights_offering | merger | open_ending | activist_13d |
        distribution_change | leverage_change | other
  date: 2026-10-15
  detail: "Saba 13D filed 2026-09-05; tender for 15% at 98% of NAV"
  source: "https://..."
  entered_by: initials
```

A name with an event inside 5 sessions is flagged on the blotter with its kind.
**A short on a name with a `tender`, `rights_offering` or `open_ending` inside
20 sessions is flagged crit: "jump-to-NAV risk on the short leg."** That flag
is not decoration — SEC staff require a CEF tender to be priced at NAV as of
the close of the tender's last day, so an announced tender is a dated,
NAV-priced convergence event, and being short into one is a known, avoidable
loss. Rights offerings need the **transferable / non-transferable** field
recorded, because non-transferable rights force mechanical dilution on
non-participants and the two cases trade differently.

**Forward ex-dates.** `cef_distributions.parquet` ends in late July 2026.
Extend the fetch (`scripts/cef/fetch_declared_distributions.py`) to pull
declared-but-not-yet-ex distributions from the fund families' pages or
CEFConnect into `data/cef/cef_declared.csv` with a source column, run in the
PANELS phase. **Never infer an ex-date from cadence** — a monthly payer that
skips is exactly the event a trader needs to see. W4 Part A and W8 Part D both
consume this file.

`/api/calendar` reads only; a malformed manual entry is reported as malformed,
never dropped.

---

## Stage 4 — Push, not poll, and the intraday monitor

### Why polling is the wrong shape

The broker moves on events; the ledger moves once a session; the plumbing
checks move slower still. One interval either hammers the gateway or leaves
live numbers stale, and today the page does both. The right shape: the server
knows when something changed, tells the page, and the page redraws that card.

**1. Event bus** (`dashboard/events.py`): `publish(topic, payload)` with
per-client `queue.Queue` subscribers. Topics — `broker.positions`,
`broker.account`, `broker.orders`, `broker.fills`, `broker.quotes`,
`broker.state`, published by the session thread from its `ib_async` handlers,
coalesced to at most one per 500ms carrying the whole section;
`ledger.changed` with the file name, from a 2-second `os.stat` loop over the
ledger CSVs, `heartbeat.json`, `book_status.json`, `cef_borrow.csv`,
`session_progress.json`, the current session log and the parquets (**no
external watcher library; a stat loop is enough and it is obvious**);
`panel.<name>` after the PanelCache recomputes; `session.progress` and
`session.log` (tail by byte offset, never re-send); `heartbeat` every 15s
carrying server time so a stalled stream is visible.

**2. `/api/stream`** — a Flask `text/event-stream` route, one generator per
client, `event: <topic>\ndata: <json>\n\n`. On connect send a `snapshot` event
with every topic's current state so the page never starts blank. Remove the
queue on disconnect. Cap queue size; a client that falls behind drops to the
latest snapshot rather than buffering forever.

**3. Client** — one `EventSource("/api/stream")` replacing every interval. Each
card registers for topics and redraws itself from the payload. `broker.state`
drives the masthead chip and greys the live columns with the last `updated_at`.
If `EventSource` errors twice consecutively, fall back to the old polling at
the old intervals, show a "polling" tag in the footer, and retry the stream
every 60s.

**4. Per-card "as of"** from the event payload, never `Date.now()`. A card that
has not received an event within its expected cadence (positions 30s during
RTH, ledger one session) marks itself stale.

### The intraday convergence monitor (display only)

The asymmetry is the whole point, and it is structural:

- **Entry cannot be intraday.** The signal is price minus NAV and a fund's NAV
  does not exist until after the close. There is no intraday discount for a new
  position.
- **Exit can be.** A position we already hold has a known prior NAV. Price moves
  all day against it. A position whose price has converged toward yesterday's
  NAV has captured its move with no new information; the remaining expected
  return is smaller and the position is cheap to exit.

The account has no NYSE top-of-book subscription (error 10089); the API works
under `reqMarketDataType(3)`, delayed 15 minutes. During RTH only (NYSE
calendar, 09:30–16:00 ET), qualify the 17 contracts once, cache conIds, handle
`pendingTickersEvent`, update the snapshot's `quotes` section and publish
`broker.quotes` coalesced to one event per 2s. Outside RTH, cancel the
subscriptions and publish an empty section with the reason.

Per held name: `P_now` (delayed last, or the mid of delayed bid/ask when last
is stale), `N` and its date, `d_now = 100(P_now − N)/N`, `z_now` using the
**same** 252-day moments (shift 1) the signal uses, `z_sig` at the last signal
date, and **converged fraction** `1 − z_now/z_sig` when `|z_sig| > 0.5` else
"n/a: no dislocation to converge", clipped to [−1, 2] for display with the raw
number on hover. Every value carries the quote timestamp and the word
**DELAYED**. A name whose NAV panel is older than one session says "NAV stale
Nbd" and computes nothing.

A card on screen 3 sorts by converged fraction descending, footer: *"Delayed
data. Display only. Not a sleeve input."* Plus a blotter column "conv." and a
per-name intraday sparkline held in memory, reset at the open, not persisted.

Write `docs/dashboard/INTRADAY_NOTE.md`: what a real-time subscription would
cost (**look up IBKR's current NYSE top-of-book non-professional pricing; do
not quote from memory**), what it would change (a mid-quote LOC limit in W7
Part D; a 15-minute-fresher convergence read), and what it would not change
(entry is still impossible intraday).

---

## Acceptance

- With the gateway down, every screen renders; screen 1 is red with the reason;
  screen 3 shows the last snapshot greyed with its timestamp.
- Time to first paint of screen 1 under 500ms on a warm server.
- No tab shows more than one chart. No screen shows more than one table plus
  one card row. A new team member can say what each screen is for from its
  heading alone.
- Zero undefined CSS classes referenced from JS; every number on screens 3 and
  4 right-aligned and tabular; no colour outside the token list; the page
  renders identically with the network disabled.
- `lsof` shows one socket to port 4002 from the dashboard process and no
  periodic reconnects in the gateway log. With the page open for an hour during
  RTH the network tab shows one long-lived request plus on-demand fetches, not
  720 `/api/live` calls. Killing and restarting the gateway produces exactly one
  disconnected and one connected event.
- A smoke test asserts every `/api/*` route returns JSON with
  `Content-Type: application/json` and no NaN token. `pytest src -q` green.

## Do not

- Do not add a second POST route, and do not add any code path that calls
  `placeOrder`, `cancelOrder`, or `reqGlobalCancel`. `readonly=True` is a
  guard, not the design; the design is that no such call exists.
- Do not add a framework, a bundler, or a chart library. Inline SVG stays.
- Do not compute a target, a Sharpe, or a cost in JavaScript. The server states
  every number with its source.
- Do not remove any server-side reason string; move them, do not drop them.
- Do not smooth, resample or interpolate any series for display; gaps are gaps.
- Do not present the NAV reference band as a prediction; the label is
  mandatory.
- Do not fabricate a return from intraday unrealised P&L; it is a mark, not a
  session.
- Do not turn any calendar item, group reading or borrow number into a sleeve
  input from the dashboard. The research path does that.
- Do not import `dashboard.*` anywhere under `src/` or `ops/`; the dependency
  runs one way.
