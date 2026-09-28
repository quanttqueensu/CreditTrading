# Document index — which file owns which question

**Every markdown file in this repo outside `results/` has a row here, and
`python3 -m ops.doc_audit` fails if one does not.** One question has one owner. If
you are about to write the same fact into a second file, link to the owner instead.

Figures are not owned by any document: `python3 -m ops.orient` produces them.

## Roles

| role | meaning |
|---|---|
| **entry** | Where a reader starts. Points at orient and `docs/SYSTEM.md`; carries no status figures. |
| **rules** | Durable rules that do not rot. No dated figures. |
| **manifest** | This file. |
| **canonical** | The single owner of a question about what the system is or has decided. |
| **ledger** | A canonical table that is updated in the same commit as the event it records. |
| **reference** | Stable reference material: theory, external claims, history. |
| **desk** | Agent-layer files Claude Code loads: rules, skills, subagents. Must point at owners, not restate them. |

## The index

| path or glob | role | owns | checked by |
|---|---|---|---|
| `CLAUDE.md` | rules | the hard rules for agents: order path, code, data, research; landmines; the desk | `ops.doc_audit` (desk inventory, entry point) |
| `README.md` | entry | where a human starts, setup, and the repo layout | `ops.doc_audit` (entry point) |
| `docs/INDEX.md` | manifest | which file owns which question | `ops.doc_audit` (manifest) |
| `docs/SYSTEM.md` | canonical | what we trade, how it runs, what we know, standing decisions | `ops.doc_audit` (pointers) |
| `docs/ROADMAP.md` | ledger | every step from here to the Alpaca book in prod, and its status | `ops.doc_audit` (pointers) |
| `docs/RESEARCH_STATE.md` | ledger | trial counters and the killed list | `ops.orient` TRIALS |
| `docs/BRIEF.md` | reference | the edge's theory, CEF market structure, and harness rules H1–H15 | `ops.doc_audit` (spec id) |
| `docs/REFERENCES.md` | reference | every external claim and its verification status | — |
| `docs/HISTORY.md` | reference | what existed before the 2026-09-28 clean slate, and how to recover it | — |
| `.claude/README.md` | desk | the map of the agent layer | — |
| `.claude/rules/*.md` | desk | path-scoped rules loaded when matching files are opened | `ops.doc_audit` |
| `.claude/skills/*/SKILL.md` | desk | one workflow each | `ops.doc_audit` (desk inventory) |
| `.claude/agents/*.md` | desk | one specialist seat each | `ops.doc_audit` (desk inventory) |

**Not indexed, by design:** `results/**` (dated records, each true as of its date;
`ops.doc_audit` checks their pre-registration shape) and runtime output written
rather than authored — `results/ops/alpaca_probe/` and `ops/HALT*.md`.
