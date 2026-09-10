---
name: dashboard-ui
description: Add or rework a panel on the read-only trading dashboard at :8787 — route, tab, tiles, table or chart, in the existing token system and both themes. Use when asked to build a dashboard view, surface a book state visually, or improve the monitor's information architecture.
argument-hint: [panel or view to build]
allowed-tools: Bash(python3 dashboard/server.py*) Bash(curl -s http://127.0.0.1:8787/api/*) Bash(lsof -i :8787*) Read Edit Write Grep Glob
---

# Building a dashboard panel

## What exists now

```!
python3 - <<'PY'
import re, pathlib
srv = pathlib.Path("dashboard/server.py").read_text()
routes = re.findall(r'@app\.(get|post)\("([^"]+)"\)', srv)
print("ROUTES")
for verb, path in routes:
    print(f"  {verb.upper():5} {path}" + ("   <- the ONLY mutating route" if verb == "post" else ""))
idx = pathlib.Path("dashboard/static/index.html").read_text()
tabs = re.search(r'const TABS=\[([^\]]+)\]', idx)
print("\nTABS:", tabs.group(1) if tabs else "?")
print(f"index.html: {len(idx.splitlines())} lines")
PY
```

---

## The invariant

**Read-only by design.** Exactly one non-GET route: `POST /api/connect`, which
starts IB Gateway and nothing else. **No code path from the dashboard transmits an
order, cancels one, edits a spec, or writes a ledger.** If a panel seems to need
one, it belongs in `ops/` behind a human.

## The design principle

This screen is the only surface that can catch a **silently non-trading book**.
Twenty-one consecutive sessions once logged "ok", wrote a heartbeat and advanced a
ledger while trading nothing. So: **make the failure visible, not the success
pretty.** A panel that looks calm when something is broken is worse than no panel.

- **Absence is information.** `nodata(title, reason)` says *why* a value is
  missing. Never render `0` or a blank where a measurement is absent — a zero that
  means "not measured" is a lie on a screen the operator trusts. This is the
  no-silent-fallback rule applied to pixels.
- **Distinguish modelled from broker-confirmed everywhere.** 22 of 24 ledger trade
  dates are modelled. A panel that blends them is actively misleading.

## Steps

**1. Server route** in `dashboard/server.py`:

```python
@app.get("/api/<name>")
def api_<name>():
    """One sentence on what this answers and which failure it makes visible."""
    try:
        ...
        return jsonify({"ok": True, "asof": ..., "rows": rows})
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "reason": f"missing {exc.filename}"})
```

Return `ok: false` with a reason rather than raising — a 500 takes the whole tab
down. **Sanitise every float**: Python's `json` emits bare `NaN`, which a browser's
`JSON.parse` rejects outright and Flask's `jsonify` produces silently. This has
broken the dashboard more than once.

**2. Markup** — follow the existing shape:

```html
<section class="sec" id="tab-<name>">
  <div class="tiles" id="<name>Tiles" style="margin-bottom:12px"></div>
  <div class="grid">
    <div class="card">
      <div class="card-hd"><h3>Title</h3><div class="spacer"></div><div id="<name>Chip"></div></div>
      <div class="scroll"><table id="<name>Table">…</table></div>
    </div>
  </div>
</section>
```

**3. Register the tab** in the `TABS` array and add a loader in `loadSlow()` or
`boot()`.

**4. Use the existing helpers** — `money`, `num`, `pct`, `signed`, `pctBare`,
`dirCls`, `esc`, `isNum`, `tileEl`, `nodata`, `showTip`. Do not write a second
number formatter. **Escape everything interpolated** with `esc()`; ticker and note
fields are written by other processes.

**5. Tokens only.** Never a raw hex. `--ink`, `--surface`, `--good`, `--crit`;
`--cheap`/`--rich` for valuation; `--up`/`--down` for P&L; `--s1`…`--s8` for
categorical series **in fixed order, never cycled**, with `--s1` reserved for the
strategy so it is the same colour in every chart. A new token goes in **all three**
blocks (`:root`, the `prefers-color-scheme` block with its `:not([data-theme="light"])`
guard, and `:root[data-theme="dark"]`) or the toggle breaks in one direction.

**6. Charts** — hand-drawn SVG against the tokens, redrawn by `drawAll()` on
resize. Read `drawNav`, `drawEq`, `drawZ` first. Load the `dataviz` skill before
writing chart code.

## Verify

```bash
python3 dashboard/server.py &
curl -s http://127.0.0.1:8787/api/<name> | jq .
```

Check it renders at phone width, in **both** themes, and **with the underlying file
missing** — that last case is the one that will actually happen.

Do not leave the server running in the background from an agent session; it holds
the port and an IB client id.

## The panel queue, ranked by value

1. **Session watch** — did today's session arm, and if not which blocker fired.
2. **Order lifecycle journal** — decided → sent → acknowledged → filled, per name,
   gaps visible rather than inferred.
3. **Realised vs modelled cost** — split by session and method, never pooled.
4. **Effective breadth / factor concentration** (`/api/factors`) — the headline
   number is **1.17**, not 17.
5. **Borrow desk** — fee, availability, unbuildable names. NAD's pool supports
   ~$45,000 against an 8,129-share short.
6. **Event calendar** — ex-dates, tenders, rights offerings, 13Ds. Being short into
   a NAV-priced tender is a known, avoidable loss.

For a full design pass rather than one panel, use the `dashboard-designer` subagent.
