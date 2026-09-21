# Team-lead decisions D1–D20 — hardening freeze, 2026-09-21

Decided by Simon Jarvis (team lead), 2026-09-21 ~14:30 ET, answered interactively
against the options in `PLAN.md` Appendix 2. Recorded verbatim; **nothing here was
inferred**. Standing instruction given with them: *"we don't need google emails or
anything"* — no email and no external alerting service.

`≠ rec` marks an answer that departs from the plan's recommendation. Those rows
change the plan; `PLAN_AMENDMENT.md` says how.

| # | question | decision | vs rec | what it changes |
|---|---|---|---|---|
| D1 | Shadow morning (promoted code, halt on) before clearing the halt | **Yes** | = | One trading day between promotion and re-arm. |
| D2 | Epoch mark convention | **Re-mark at the panel close** (shares unchanged, NAV $500,000) | = | G6v stays verify-first; both NAV classes reported until reproduced; choice logged in `_replay_log.jsonl`. |
| D3 | Off-machine dead-man | **No external service** | ≠ rec | A dead, rebooted or logged-out Mac is silent until someone looks. Accepted. No dead-man in WS5. |
| D4 | Alert channel (rewritten: email is out) | **Local only** — macOS notification, dashboard, logs | ≠ rec | Runbook H3 (App Password) is deleted. The email path stops being a doctor WARN/FAIL and stops printing `email: not configured`. Preflight never blocks on alerting. Acceptance criterion 7 is rewritten. |
| D5 | Turn off automatic macOS installs | **No, leave auto-install on** | ≠ rec | Runbook H5 deleted. Finding B6 (FileVault on, no auto-login: an update reboot stops every job until a human logs in) is an accepted residual risk. |
| D6 | phase0 retirement timing | **Retire phase0 BEFORE re-arm** | ≠ rec | phase0 retirement (W2 Part C) and the LQD −881 attribute-or-flatten call move onto the critical path, ahead of `clear_halt`. Contingency 7.4 (by-hand de-gross at cushion < 0.13) is no longer the mechanism; the TWS what-if stays mandatory at the preview. Named person for broker-side hand work: Simon Jarvis. |
| D7 | Benchmarks halted until after A+1 | **Repair benchmarks alongside CEF** | ≠ rec | The five benchmark sleeves join the repair. Finding C8 (perm_id / client-id attribution; b6's fill file holds another book's executions) is un-parked and becomes a prerequisite. `replay_ledger` must handle every benchmark sleeve. Phase 8 folds into Phases 1–6. |
| D8 | Sleeve cannot decide on a name | **Raise — a no-trade day** (rc 8) | = | The measured raise frequency from the sleeve no-op proof is shown to the team lead before it ships. |
| D9 | `fetch_daily` when the pair is value-complete on disk | **Skip the fetch**, say so in the log; rc 14 only when a fetch was needed and returned nothing | = | |
| D10 | Noon-retry clock | **Plist-derived, in the repo now** | = | Launcher-passed `--session-start` deferred. |
| D11 | Pre-trade gross cap inside the freeze | **Park** | = | The signed preview and the what-if substitute. |
| D12 | `cef_pm` stays DRY_RUN=1 through the 20-session window | **Yes** | = | |
| D13 | First armed order set may be large | **Accept in full** | = | |
| D14 | nextgen and spec v7 | **Parked and pushed, never merged** | = | Eligible after 20 clean sessions via `/spec-change` and `/prereg`. |
| D15 | Stale `CLAUDE.md` wording | **Agent drafts a diff, team lead applies** | ≠ rec | Draft goes to `results/ops/hardening_2026-09-21/CLAUDE_md_proposed.diff`. Agents still never edit `CLAUDE.md`. |
| D16 | DRY_RUN=1 in `benchmarks.env` and `phase0.env` with the RC | **Yes, both** | = | Given D7, `benchmarks.env` flips back to 0 only in a tag cut after its repair passes reconcile per sleeve. |
| D17 | Exit when every capture is lost on an armed day | **Build statement-ingest first** | ≠ rec | **Blocked on a human action:** a real IBKR Flex/Activity export must be pulled before any parser is written (data rule: never invent a format). On the critical path. |
| D18 | Apply the agent-drafted `settings_proposed.json` | **Yes — the team lead applies it after reading the diff** | = | |
| D19 | Off-disk copy | **`git push` to origin for code; an external drive for the state archive, launcher and plists** | — | Never `config/.env` or the IBC config. The drive must be attached by the team lead. |
| D20 | 20-session bar | **Launch-to-trade ≤ 30 min on complete-pair mornings; verifier verdict must be exactly PASS** | = | An UNVERIFIED day resets the streak. |

Copied into `docs/SYSTEM.md` §5 by the WS0 docs step, under a `Team lead, 2026-09-21` heading.
