# Roadmap — from a clean slate to the Alpaca book in prod

**The one plan.** Every step between today and a strategy trading from the cloud
VM, in order, with who does it. Update the status column in the same commit as the
work. Figures are never written here: `python3 -m ops.orient` measures them. The
decisions behind this plan are `docs/SYSTEM.md` §5 (team lead, 2026-09-28).

**Who:** **TL** = the team lead (anything involving a credential or a broker
account). **A** = an agent. An agent transmits an order only when the team lead
asks in the session and says "go" to the concrete order list (`CLAUDE.md`,
order-path rule 1).

## Phase 0 — clean slate · DONE 2026-09-28

IBKR retired and its jobs unloaded; everything not needed for the Alpaca build
deleted (recoverable from tag `pre-clean-slate`, summary in `docs/HISTORY.md`). What
remains is the whole system: the strategy, its spec, the research harness and
fetchers, the research memory, `quantt/`, and the agent layer.

## Phase 1 — accounts and facts

| # | step | who | status |
|---|---|---|---|
| 1.1 | Create two Alpaca **paper** accounts at $100k: `cef` and `b6`. Regenerate the key pasted into the 2026-09-28 chat. | TL | `cef` done 2026-09-28; `b6` later (TL) |
| 1.2 | Put `ALPACA_CEF_KEY_ID`, `ALPACA_CEF_SECRET_KEY`, `ALPACA_B6_KEY_ID`, `ALPACA_B6_SECRET_KEY` in `config/.env` with a text editor. Never paste them into a chat. | TL | `cef` pair set 2026-09-28; `b6` later |
| 1.3 | `python3 -m quantt.broker.alpaca_probe --check-keys`, then the probe itself: which of the 17 CEFs and b6's 8 ETFs are tradable, shortable, easy- or hard-to-borrow, marginable. | A | `cef` done 2026-09-28 (`results/ops/alpaca_probe/2026-09-28_cef.json`): all 17 tradable; **4 not shortable, hard-to-borrow** — orient ALPACA lists them. `b6` after 1.2 |
| 1.4 | **Universe decision** if any name is untradable or hard-to-borrow — this can change the strategy. | TL | done 2026-09-28: drop NAD, NEA, NVG, NZF (17 → 13) |

## Phase 2 — the spec on Alpaca

| # | step | who | status |
|---|---|---|---|
| 2.1 | Re-derive `max_gross_stress` with the pre-registered rule (`results/cef/PREREG_GROUP_CAP_2026-09-16.md`) on the Alpaca account: Reg T, one book per account. | A | done 2026-09-28: 1.80 (and `group_cap` left off — its rule gives k = 0 on 13 names) |
| 2.2 | Re-derive `min_trade_usd` (its old derivation used IBKR's $1 minimum commission; Alpaca charges none) and re-size capital to $100k. | A | done 2026-09-28: $0 (whole shares), $100k |
| 2.3 | One `/spec-change` to v7-on-Alpaca: universe, `max_gross_stress`, capital, min trade. Pre-registration, CEF counter in the same commit. | A, TL approves | done 2026-09-28: `cef_discount.v7.20260928`, `results/cef/PREREG_ALPACA_V7_2026-09-28.md`, CEF 48 → 50, revert tag `spec-cef_discount.v6.20260906` |

## Phase 3 — how Alpaca actually behaves (paper, before any code relies on it)

Each is an order-path action: the agent drafts it, shows the orders, the team lead
says go. **Team lead, 2026-09-28: design around them, no probe orders.** The runner
never relies on the uncertain answer (flips deferred, one netted order per symbol,
ids never reused); the first armed session's real orders answer 3.1 and 3.5.

| # | question | status |
|---|---|---|
| 3.1 | Does paper accept `time_in_force=cls`? At what price and time does a paper MOC fill, versus the official close from `/v2/stocks/auctions`? | open |
| 3.2 | Can a long flip to short in one order, or must it close then open? | open |
| 3.3 | Do opposite-side orders in one symbol in one account get the wash-trade 403? | open |
| 3.4 | Is `client_order_id` reusable after a fill or cancel? (It decides the idempotency key.) | open |
| 3.5 | Where do fills, fees and dividends appear in account activities on paper? | open |

## Phase 4 — build the runner (`quantt/`)

Tests first; each shown to fail against the wrong behaviour; `quant-reviewer` on
every piece. **Built 2026-09-28** (`docs/RUNNER.md`, release `release-20260928-1`);
4.1–4.7 done, 4.2 decided (day one trades to full target); 4.8 done 2026-10-08.

| # | piece | status |
|---|---|---|
| 4.1 | Data refresh: prices + NAV panels, freshness gate (stale NAV → no trade, still log). | open |
| 4.2 | Decision: sleeve targets from the frozen spec → whole-share orders, netted per symbol, flips split per 3.2. Note: from a flat book the band trades each name only to its band edge, so the first session's book is not exactly dollar-neutral (net −0.05 to −0.10 of NAV on the last three panel dates; v6 on 17 names does the same). Decide before the first armed session whether the opening session trades to target instead. | open |
| 4.3 | Pre-trade gate: `DRY_RUN`, halt file, buying power, borrow status, the "a set is already headed for this auction" refusal, record-before-first-order. | open |
| 4.4 | Transmit: MOC via `cls` before 15:50 ET, idempotent per 3.4. | open |
| 4.5 | Reconcile from the broker (positions, orders, activities, `trade_updates`), never a local ledger. | open |
| 4.6 | Scoring: Alpaca's fill P&L (official) and closing-auction-print P&L, side by side, gross. | open |
| 4.7 | Post-close verification: one log line per trading day, pass or fail — silence never reads as success. | open |
| 4.8 | `orient` / banner / status line read the live book's broker-confirmed fills. | done 2026-10-08: `ops/prod_state.py` measures both prod machines (laptop launchd; VM systemd over one read-only ssh call): which is armed (`DRY_RUN` + `AUTO_ARMED`, gates 1–2), tag, last verify verdict, the broker-confirmed `equity.csv`, and a WARNING if both are armed. orient PROD/ALPACA, the SessionStart banner and the status line all read it; the probe snapshot is labelled with its age. |

## Phase 5 — shadow on paper

**Skipped by the team lead, 2026-09-28:** armed on 2026-09-29 after one dry run,
with the first order list shown before transmit.

Run the full session daily with `DRY_RUN=1` against both paper accounts: decide,
gate, reconcile, score — send nothing. Exit when the team lead is satisfied with a
run of clean sessions (the length is the team lead's call, recorded here when made).

## Phase 6 — prod on the cloud VM

**Interim, team lead 2026-09-28: prod is this laptop** — `~/prod/quantt-alpaca` at
`release-20260928-1`, launchd jobs `com.quantt.alpaca.cef.{session,verify}`,
`DRY_RUN=1` until the go (`docs/RUNBOOK.md`). The VM steps below still apply later.

**The rule for prod: it contains only this repository at a tag, and nothing else.**
No copies of old trees, no IBKR software, no hand-edited files.

| # | step | who |
|---|---|---|
| 6.1 | Choose the provider and region; create the VM. **Chosen 2026-10-07: Azure for Students, `Standard_B2pts_v2` (Arm64, like the laptop), `canadacentral`**, the allowed region closest to New York (`docs/SYSTEM.md` §5). `Standard_B2ats_v2` is not offered there. **Created 2026-10-07**: Ubuntu 24.04, Standard SSD 32 GB, SSH from the team lead's IP only. | TL |
| 6.2 | Secrets on the VM through the provider's secrets manager, not a file copied from a laptop. **Azure Key Vault, secrets `alpaca-cef-key-id` and `alpaca-cef-secret-key`**, read through the VM's managed identity into a tmpfs file: once per boot when it succeeds, and again at every job start after a failure (`docs/RUNBOOK.md` §8). **Vault created 2026-10-07**; the two secrets are the team lead's to paste. | TL |
| 6.3 | Clone at a release tag; install `requirements.txt`; run `python3 -m pytest`, `python3 -m ops.doc_audit --check`, `python3 -m ops.orient` — all clean before anything is scheduled. **Done 2026-10-08 at `release-20261008-2`** on the VM: bootstrap, seeded from the laptop prod panels (through 2026-10-07), pytest 1038 passed / 2 skipped (httpfs, stated reason), doc_audit 0 DRIFT, orient exit 0. The first VM install found `duckdb` missing from `requirements.txt` (fixed in `release-20261008-2`). | A |
| 6.4 | Schedule the session (the VM's scheduler), `DRY_RUN=1` first. **Shadow started 2026-10-08 10:40 ET** (`DRY_RUN=1`, timers enabled, keys from the vault) beside the armed laptop. First comparison, 2026-10-08: the same 8 orders. 6 quantities were identical; JFR and PFN differed by 1 share, explained by equity read 0.02% apart (the VM decided in the morning, the laptop the evening before). Shadow length: 3 trading days by default (proposed to the team lead 2026-10-07; their call). The cut-over follows `docs/RUNBOOK.md` §8.5. | A, TL approves |
| 6.5 | Arm: `DRY_RUN=0` after the team lead's go. The first armed session's orders are shown before transmit. **Armed 2026-10-08 11:35 ET** at `release-20261008-2`; first send approved (plan `c5f20357…`, 8 orders) for that day's 15:52 window; `AUTO_ARMED` after its verify PASSes (`docs/SYSTEM.md` §5). | TL |
| 6.6 | **Laptop Alpaca jobs disabled 2026-10-08** (cut-over); their plists still say `DRY_RUN=0` on disk and should be re-installed disarmed or deleted. Retire this laptop's leftovers: `~/prod/QUANTT` (old IBKR worktree), `~/Library/LaunchAgents/com.quantt.*.plist`, `~/Library/Application Support/quantt/`, `~/ibc`, IB Gateway. | TL decides, A runs |
| 6.7 | Monitoring per the standing decision: dashboard and logs only (a dashboard rebuild is a later item). | A |

## Later

- A read-only dashboard, rebuilt fresh.
- New research work orders, written against `docs/BRIEF.md` and checked against
  `/graveyard` first.
