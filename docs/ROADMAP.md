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
| 1.4 | **Universe decision** if any name is untradable or hard-to-borrow — this can change the strategy. | TL | **open — needed now** (see 1.3) |

## Phase 2 — the spec on Alpaca

| # | step | who | status |
|---|---|---|---|
| 2.1 | Re-derive `max_gross_stress` with the pre-registered rule (`results/cef/PREREG_GROUP_CAP_2026-09-16.md`) on the Alpaca account: Reg T, one book per account. | A | open |
| 2.2 | Re-derive `min_trade_usd` (its old derivation used IBKR's $1 minimum commission; Alpaca charges none) and re-size capital to $100k. | A | open |
| 2.3 | One `/spec-change` to v7-on-Alpaca: `group_cap`, `max_gross_stress`, capital, min trade. No-op proof, pre-registration (`/prereg`), CEF counter 48 → 49 in the same commit. | A, TL approves | open |

## Phase 3 — how Alpaca actually behaves (paper, before any code relies on it)

Each is an order-path action: the agent drafts it, shows the orders, the team lead
says go.

| # | question | status |
|---|---|---|
| 3.1 | Does paper accept `time_in_force=cls`? At what price and time does a paper MOC fill, versus the official close from `/v2/stocks/auctions`? | open |
| 3.2 | Can a long flip to short in one order, or must it close then open? | open |
| 3.3 | Do opposite-side orders in one symbol in one account get the wash-trade 403? | open |
| 3.4 | Is `client_order_id` reusable after a fill or cancel? (It decides the idempotency key.) | open |
| 3.5 | Where do fills, fees and dividends appear in account activities on paper? | open |

## Phase 4 — build the runner (`quantt/`)

Tests first; each shown to fail against the wrong behaviour; `quant-reviewer` on
every piece.

| # | piece | status |
|---|---|---|
| 4.1 | Data refresh: prices + NAV panels, freshness gate (stale NAV → no trade, still log). | open |
| 4.2 | Decision: sleeve targets from the frozen spec → whole-share orders, netted per symbol, flips split per 3.2. | open |
| 4.3 | Pre-trade gate: `DRY_RUN`, halt file, buying power, borrow status, the "a set is already headed for this auction" refusal, record-before-first-order. | open |
| 4.4 | Transmit: MOC via `cls` before 15:50 ET, idempotent per 3.4. | open |
| 4.5 | Reconcile from the broker (positions, orders, activities, `trade_updates`), never a local ledger. | open |
| 4.6 | Scoring: Alpaca's fill P&L (official) and closing-auction-print P&L, side by side, gross. | open |
| 4.7 | Post-close verification: one log line per trading day, pass or fail — silence never reads as success. | open |
| 4.8 | `orient` / banner / status line read the live book's broker-confirmed fills. | open |

## Phase 5 — shadow on paper

Run the full session daily with `DRY_RUN=1` against both paper accounts: decide,
gate, reconcile, score — send nothing. Exit when the team lead is satisfied with a
run of clean sessions (the length is the team lead's call, recorded here when made).

## Phase 6 — prod on the cloud VM

**The rule for prod: it contains only this repository at a tag, and nothing else.**
No copies of old trees, no IBKR software, no hand-edited files.

| # | step | who |
|---|---|---|
| 6.1 | Choose the provider and region; create the VM. | TL |
| 6.2 | Secrets on the VM through the provider's secrets manager, not a file copied from a laptop. | TL |
| 6.3 | Clone at a release tag; install `requirements.txt`; run `python3 -m pytest`, `python3 -m ops.doc_audit --check`, `python3 -m ops.orient` — all clean before anything is scheduled. | A |
| 6.4 | Schedule the session (the VM's scheduler), `DRY_RUN=1` first. | A, TL approves |
| 6.5 | Arm: `DRY_RUN=0` after the team lead's go. The first armed session's orders are shown before transmit. | TL |
| 6.6 | Retire this laptop's leftovers: `~/prod/QUANTT` (old IBKR worktree), `~/Library/LaunchAgents/com.quantt.*.plist`, `~/Library/Application Support/quantt/`, `~/ibc`, IB Gateway. | TL decides, A runs |
| 6.7 | Monitoring per the standing decision: dashboard and logs only (a dashboard rebuild is a later item). | A |

## Later

- A read-only dashboard, rebuilt fresh.
- New research work orders, written against `docs/BRIEF.md` and checked against
  `/graveyard` first.
