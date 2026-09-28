> **ARCHIVED 2026-09-28 — not evidence of current state.** Was `.claude/skills/incident/SKILL.md`.
> Now owned by: `results/ops/ALPACA_MIGRATION_MANIFEST_2026-09-28.md` (retired with IBKR on 2026-09-28). Numbers: `python3 -m ops.orient`.

---
name: incident
description: Diagnose and write up a live incident — a failed session, a halt, a broker disagreement, a job that did not fire. Use when something has gone wrong on the live path. Produces a durable record and, more importantly, the guard that would have caught it.
argument-hint: [what went wrong]
---

# Incident

## Current state

```!
python3 -m ops.orient --no-tests 2>/dev/null | sed -n '1,45p'
echo "--- active halts, both trees (written in prod, untracked) ---"
ls ~/prod/QUANTT/ops/HALT*.md ops/HALT*.md 2>/dev/null || echo "no active halt in either tree"
echo "--- recently cleared halts ---"
ls -t ~/prod/QUANTT/ops/halts/HALT_*.md ops/halts/HALT_*.md 2>/dev/null | head -3
```

---

## Diagnose outward from the thing that cannot lie

1. **`broker_fills.csv`** — the last `fill_date` is the only honest answer to "did
   it trade". Everything else can read "ok" for a book that has not traded in a month.
2. **The halt files, in prod** — `ops/HALT.md` hard-gates every book,
   `ops/HALT_<book>.md` one book. They are untracked and written in prod, so read
   them where orient HALTS says they are. Every entry, not the first line.
3. **`ops/heartbeat.json`** — per-job status. `ok_not_armed` means the session ran
   and *declined* to trade. That is the silent case, and it raises no alert.
4. **`~/prod/QUANTT/ops/schedule/logs/cef_<date>.log`** — `[FAIL]` lines, the
   `ARMED:` line, `status=`. Logs land in prod; dev's copies stop at the split.
5. **`python3 -m ops.doctor --quick`** — the out-of-band plumbing check.
6. **`python3 -m ops.preflight --book … --no-live`** — the gate itself.
7. **`python3 ops/reconcile_orders.py`** — ledger vs broker.

## The prior

**Every failure this system has had was silent**, and each was invisible to the
guards that existed at the time. Before theorising, check whether this is one of the
five known shapes:

| shape | signature |
|---|---|
| **TCC / launchd cannot read the repo** | exit 126, `getcwd: Operation not permitted`, two log lines, nothing transmitted |
| **wrong broker port** | preflight blocks correctly every session; heartbeat says `ok_not_armed`; silence for weeks |
| **repo moved** | `mkdir(parents=True)` silently *recreated* the old path; the session logged into a ghost directory and died before the heartbeat |
| **stale plist `WorkingDirectory`** | launchd refuses to spawn (EX_CONFIG 78) — no process, no log, no heartbeat, no alert. One of the four affected was the **watchdog itself** |
| **exception after transmit** | the ledger KeyError'd on a missing cost entry *after* orders had gone; caught and printed as one `repr()` inside a run that ended "ok"; 302 executions recorded nowhere |

**The pattern is always the same: a guard that lives inside a job cannot catch a
job that never starts, and a guard that shares a broken assumption with the thing
it guards is not a guard.**

## The write-up

`ops/halts/HALT_<YYYYMMDD>_<HHMMSS>.md`:

```markdown
# HALT — <one line>
Detected: <timestamp ET>   Detected by: <who or what>
First occurrence: <timestamp>   Sessions affected: <n>

## What happened
Sequence of events with timestamps. What the system believed at each point.

## What it cost
Sessions not traded. Fills not captured (irrecoverable — ib.fills() serves the
current TWS session only). P&L effect, if any. Data lost permanently.

## Root cause
The actual mechanism. Not "the gateway was down" but why nobody knew for N days.

## Why nothing caught it
The specific guard that should have fired, and the assumption it shared with the
failure.

## The guard that would have caught it
Concrete: a check, where it runs, and — critically — whether it runs OUTSIDE the
thing it guards.

## Resolution
What was changed. What was deliberately NOT changed and why.
```

## Rules

- **Write the file first, unguarded.** Alerting is best-effort and must never be
  able to mask the fault it reports: an SMTP timeout cannot be allowed to prevent
  the durable record. That ordering is deliberate in `ops/halt.py`.
- **Do not clear a halt to make a symptom go away.** A halt is cleared deliberately,
  with a written record — never with `rm`. The hook that used to block both was
  removed 2026-09-10; the rule stands without it.
- **Capture fills before anything else**, even after a failure. `ib.fills()` serves
  the current TWS session only and TWS force-restarts daily. A fill not captured
  today is gone.
- **Do not run the live session to "see if it works now."** Not idempotent. Propose
  the command; let the operator run it with `! <command>`.
- **The incident is not closed until a guard exists.** That is the deliverable, not
  the diagnosis.
