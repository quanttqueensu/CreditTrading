# The dashboard

**This file owns** what the dashboard may read and what a snapshot of the book may
never carry. Who keeps this folder is `docs/TEAM.md` §1 (the dashboard-and-data
lane). The ruling behind it is `docs/SYSTEM.md` §5, "Team lead, 2026-10-26". What is
true about the book right now is `python3 -m ops.orient`, never this folder.

The dashboard is a read-only page for the book: what it holds, what it traded, and
how each day scored. It is meant to be the thing we check every day instead of
running orient by hand.

---

## 1. It reads one thing: the snapshot

```
the VM (prod)                          this repository (public)
quantt_state/  ──►  exporter  ──►  dashboard/snapshots/<date>.json  ──►  dashboard
 (the session's                     (read-only, one file a night)        (reads only
  own records)                                                            this folder)
```

- **The dashboard reads `dashboard/snapshots/` and nothing else.** It does not reach
  the VM, the broker, `config/.env`, or `data/`. It imports nothing from `quantt/`
  that can open a connection.
- **No code path from it may send, replace or cancel an order** (`CLAUDE.md`, "Any
  monitor is read-only"). A dashboard that cannot reach a broker cannot break that
  rule.
- **The exporter runs on the VM**, after the night's records are written, and reads
  only what the session has already recorded (`quantt/session/records.py`). This
  lane writes its spec and its tests; the team lead reviews it, releases it and
  installs it. The exporter never changes what the book trades.
- **How a snapshot gets from the VM into this folder is not decided yet.** The team
  lead rules on it when the exporter is ready. Until then, the dashboard is built
  against a fixture snapshot committed here.

## 2. What a snapshot may never carry

The repository is public. **A committed snapshot is published**, and git keeps it
after it is deleted.

| never | why |
|---|---|
| a key, a token, or anything read from `config/.env` | `CLAUDE.md`, hard rule 5 |
| the Alpaca account number or id | it identifies the account |
| the VM's address or hostname, the vault's name, the subscription | `CLAUDE.md`, "Where it runs" |
| row-level licensed data: CRSP, TRACE, Compustat, permnos, CUSIPs | the licence, and `docs/TEAM.md` §5 |
| a figure with no source and no read time | `CLAUDE.md`, "Hard rules: data". A number the exporter could not measure is written as unmeasured, never filled in |

The exporter's tests assert every row of this table on the fixture and on a real
night's output, before any snapshot is committed.

## 3. The snapshot's schema

The schema is set in this lane's first pull request, together with:

- one fixture snapshot;
- a test that the fixture matches the schema;
- a test that it carries nothing from §2.

The team lead approves the schema. Every figure in it says where it came from and
when it was read, the way `ops/orient.py` labels its lines (broker-confirmed,
modelled, or unmeasured). Read `ops/orient.py` and `ops/prod_state.py` before
designing it: they already read the same records without touching them.

Tests under `dashboard/` run in CI once `pytest.ini` lists the folder. CI is the
team lead's, so ask for that in the pull request.
