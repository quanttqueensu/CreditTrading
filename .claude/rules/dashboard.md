---
paths:
  - "dashboard/**"
---

# The dashboard

`dashboard/server.py` (Flask, `127.0.0.1:8787`) + `dashboard/static/index.html`
(one file: tokens, CSS, markup, vanilla JS). **No build step, no framework, no
bundler, no CDN JavaScript.** Keep it that way — this thing has to start from a
`.command` double-click on a machine that also has to run the book tonight.

## The invariant

**Read-only by design.** Exactly one non-GET route exists: `POST /api/connect`,
which starts IB Gateway and does nothing else. **No code path from the dashboard
transmits an order, cancels one, edits a spec, or writes to a ledger.** If a
feature seems to need one, it does not belong here — it belongs in `ops/` behind a
human. Adding a mutating route is a decision for the team lead, not a refactor.

## Routes

`GET /api/status · /api/risk · /api/signal · /api/trades · /api/provenance ·
/api/pnl · /api/benchmarks · /api/live · /api/factors · /api/verify · /api/doctor`
and `POST /api/connect`.

Every handler is defensive: the book state it reads is written by processes that
crash. A route that 500s takes a whole tab down, so failures come back as a JSON
body with an `ok: false` and a reason the UI can render.

**NaN is the recurring bug.** Python's `json` emits bare `NaN`, which
`JSON.parse` in a browser rejects outright, and Flask's `jsonify` does it
silently. Sanitise every float before it leaves a handler. This has broken the
dashboard more than once.

## Front-end conventions

Follow what is already there rather than introducing a second style.

- **Tokens only.** Never a raw hex in a rule — use `--ink`, `--surface`, `--good`,
  `--crit`, `--cheap`/`--rich` (valuation), `--up`/`--down` (P&L), `--s1`…`--s8`
  (categorical series, used in **fixed order, never cycled**). `--s1` is reserved
  for the strategy itself so it is the same colour in every chart.
- **Both themes, always.** Every dark value is declared twice — once under
  `@media (prefers-color-scheme:dark)` with a `:where(:not([data-theme="light"]))`
  guard, and once under `:root[data-theme="dark"]` — so the toggle wins in both
  directions. Add new tokens to all three blocks or the toggle breaks.
- **Structure**: `header.mast` → `nav.mtabs` → one `section.sec#tab-<name>` per
  tab → `.tiles` (stat row) → `.card` with `.card-hd > h3` → `.scroll > table` or
  `.chartbox`. Register a new tab in the `TABS` array and give it a loader in
  `loadSlow()`/`boot()`.
- **Formatting helpers exist — use them**: `money`, `num`, `pct`, `signed`,
  `pctBare`, `dirCls`, `esc`, `isNum`, `tileEl`, `nodata`, `showTip`. Do not
  re-implement a number formatter.
- **`ND` for missing data.** Never render `0`, `—`, or a blank where a value is
  absent: `nodata(title, reason)` says *why* it is missing. This is the
  no-silent-fallback rule applied to pixels — a zero that means "not measured"
  is a lie on a screen the operator trusts.
- **Escape everything interpolated** with `esc()`. Ticker and note fields come
  from files written by other processes.
- Charts are hand-drawn SVG against the tokens; `addEventListener("resize", …)`
  redraws via `drawAll()`. Read `drawNav`/`drawEq`/`drawZ` before adding a chart.

## What the dashboard is for

It is the only surface that can catch a silently non-trading book. Design every
addition against that: **make the failure visible, not the success pretty.** The
2026-08 outage ran 21 sessions where every log, heartbeat and ledger read "ok".

The highest-value panels, in order (`docs/prompts/W9`):

1. **Session watch** — did today's session arm, and if not, which blocker fired.
2. **Order lifecycle journal** — decided → sent → acknowledged → filled, per name,
   with the gaps visible.
3. **Realised vs modelled cost** — split by session, never pooled. The logged
   `4.59×` average blends the pre-MOC disaster that *caused* the switch to MOC.
4. **Effective breadth / factor concentration** — `/api/factors`. The number that
   matters is 1.17, not 17.
5. **Borrow desk** — fee, availability, and which names are unbuildable.
6. **Event calendar** — ex-dates, tenders, rights offerings, 13D filings.

Use `/dashboard-ui` for the add-a-panel workflow, and the `dashboard-designer`
subagent for a design pass.

## Running it

```bash
python3 dashboard/server.py            # foreground, :8787
curl -s http://127.0.0.1:8787/api/status | jq .
```

Never leave it running in the background from an agent session; it holds the port
and an IB client id.
