---
name: preflight
description: Run the trading gate and the machine health check without trading anything. Use before any session, when the book has not traded, when a job failed, or to answer "is it safe / is it able to run". Read-only — it transmits nothing.
allowed-tools: Bash(python3 -m ops.preflight*) Bash(python3 -m ops.doctor*) Bash(python3 -m ops.orient*) Read Grep Glob
---

# Preflight and plumbing

## The gate

```!
python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live --quiet-alerts 2>&1 | tail -30
```

## Halts, in both trees

**Run from dev, preflight's `halt` check reads dev's halt files, and halts are
written in prod.** A clean `halt` row here does not mean prod is unblocked:

```!
python3 -m ops.orient --no-tests 2>/dev/null | sed -n '/^HALTS/,/^$/p'
```

## The machine

```!
python3 -m ops.doctor --quick 2>&1 | tail -35
```

---

## What each check catches

`ops/preflight.py` answers **"is it safe to trade"**. `ops/doctor.py` answers **"is
this machine able to run the books unattended"**. They are deliberately separate,
because a guard that shares an assumption with the thing it guards is not a guard —
doctor runs *outside* every job for that reason.

| check | the failure it exists to catch |
|---|---|
| `halt` | an active `ops/HALT.md` (every book) or `ops/HALT_<book>.md` (one book) **in the tree preflight runs in** — the hard gate that actually stops the money |
| `costs` | every deployed ticker priced — the NVG/USHY KeyError that crashed the ledger mid-write **after** orders had transmitted |
| `cost_drift` | yaml drifting from the tick-floor model — silent staleness |
| `data` | price/NAV freshness — trading a blind signal. A stale NAV is not a cheap fund |
| `broker` | TWS actually reachable — a run that *thinks* it traded |
| `heartbeat` | did the last session fire — the 09:35 exit-126 silence |
| `margin` | cushion and gross/NLV — 83% utilisation at 2.09× gross has happened |

**A failed check downgrades the session; it does not cancel it.** `arm` clears (no
orders) while `collect` stays true, because today's closing prices, NAVs and
holdings are not re-fetchable later — the issuers publish no archive, so a day
skipped is a day gone permanently. Do not "simplify" that into a single abort.

**`--no-live` skips the broker probe**, so this is safe to run any time and does
not consume an IB client id. Drop it only when you specifically need to know
whether the gateway answers.

## Reading the result

- **All PASS and `armed` true** — the gate would let a session trade. It does not
  mean a session *will* run; that is launchd's job, and launchd has failed silently
  four separate ways. Check `/book-status` for whether it actually traded.
- **A FAIL** — read the reason. Preflight has been *right* every time it blocked;
  the historical failure was nobody reading it.
- **doctor FAIL** — unattended operation is broken right now.
- **doctor WARN** — it will break later, or you will not hear about it when it does.

## Do not

Do not run the live session entry point, `launch_job.py` or a launchd job to
"test" anything — with DRY_RUN=0 in the job's env they transmit real MOC orders,
and the trade phase is not idempotent. The hook that used to block these
was removed 2026-09-10; nothing stops you now, which is exactly why you should
not. If you need a real session run, say so and let the operator run it
with `! <command>`.
