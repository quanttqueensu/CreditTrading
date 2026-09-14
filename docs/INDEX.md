# Document index — which file owns which question

**Every markdown file in this repo outside `results/` and `_archive/` has a row
here, and `python3 -m ops.doc_audit` fails if one does not.** One question has
one owner. If you are about to write the same fact into a second file, link to
the owner instead. Duplication is how this repo came to hold four different arm
rates at once.

Figures are not owned by any document: `python3 -m ops.orient` produces them.

## Roles

| role | meaning |
|---|---|
| **entry** | Where a reader starts. Points at orient and `docs/SYSTEM.md`; carries no status figures. |
| **rules** | Durable rules that do not rot. No dated figures. |
| **manifest** | This file. |
| **canonical** | The single owner of a question about what the system is or has decided. |
| **ledger** | A canonical table that is updated in the same commit as the event it records. |
| **reference** | Stable reference material: setup, external claims, market structure. |
| **work-order** | A prompt in `docs/prompts/`. Status comes from `python3 -m ops.prompt_status`, not from the file. |
| **desk** | Agent-layer files Claude Code loads: rules, skills, subagents. Must point at owners, not restate them. |
| **convention** | Explains how a directory is used. |

## The index

| path or glob | role | owns | checked by |
|---|---|---|---|
| `CLAUDE.md` | rules | the hard rules for agents: order path, code, data, research; landmines; the desk | `ops.doc_audit` (desk inventory, entry point) |
| `README.md` | entry | where a human starts, and the repo layout | `ops.doc_audit` (entry point) |
| `docs/INDEX.md` | manifest | which file owns which question | `ops.doc_audit` (manifest) |
| `docs/SYSTEM.md` | canonical | what we trade, how it runs, what we know, standing decisions | `ops.doc_audit` (pointers) |
| `docs/RESEARCH_STATE.md` | ledger | trial counters and the killed list | `ops.orient` TRIALS, `ops.prompt_status`, `ops.gamma_status` |
| `docs/REFERENCES.md` | reference | every external claim and its verification status | — |
| `docs/INFRASTRUCTURE.md` | reference | onboarding, data rebuild, broker client ids, preflight checks | `ops.doc_audit` (banner, spec id) |
| `docs/handoffs/README.md` | convention | how dated session handoffs are kept | — |
| `docs/prompts/README.md` | canonical | the work-order index and its status vocabulary | `ops.prompt_status` |
| `docs/prompts/00_BRIEF.md` | reference | the edge's theory, CEF market structure, and harness rules H1–H15 | `ops.prompt_status` |
| `docs/prompts/**/*.md` | work-order | one unit of work each | `ops.prompt_status` |
| `.claude/README.md` | desk | the map of the agent layer | — |
| `.claude/rules/*.md` | desk | path-scoped rules loaded when matching files are opened | `ops.doc_audit` |
| `.claude/skills/*/SKILL.md` | desk | one workflow each | `ops.doc_audit` (desk inventory) |
| `.claude/agents/*.md` | desk | one specialist seat each | `ops.doc_audit` (desk inventory) |
| `deploy/ibgw/README.md` | reference | IB Gateway and IBC setup | — |

**Not indexed, by design:** `results/**` (dated records, each true as of its
date; `ops.doc_audit` checks their reproducers and pre-registration shape),
`_archive/**` (indexed by `_archive/README.md`), and runtime output that is
written rather than authored — `ops/books/**`, `ops/reports/**`, `ops/halts/**`
and `ops/HALT*.md`.
