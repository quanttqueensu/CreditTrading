---
paths:
  - "src/deploy/**"
  - "ops/**"
---

# The live order path

You are in code that can move money at a broker. Everything here is written from
an incident. Read the docstrings — this repo keeps its incident history in them,
and they are the only record of why several of these guards exist.

## The session contract

Four phases with **different failure policies**. Do not collapse them.

| phase | on failure |
|---|---|
| 1. REFRESH prices/NAV | do not trade — a stale NAV is a blind signal, not a cheap fund |
| 1b. PANELS (borrow) | log and continue — never blocks a session |
| 2. PREFLIGHT | do not trade, still collect |
| 3. TRADE | halt + alert |
| 4. CAPTURE fills | **runs unconditionally, even after 1–3 fail** |

Phase 4 is unconditional because `ib.fills()` serves the current TWS session only
and TWS force-restarts daily. There is no historical execution endpoint that
reaches back past the restart. **A fill not captured today is gone.** The old
design captured fills as a side effect of a successful run, which is why 302 real
executions from 2026-07-31 exist nowhere.

A failed check must **downgrade** the session, not cancel it: clear `arm`, leave
`collect` true. Today's closing prices, NAVs and holdings are not re-fetchable
later — the issuers publish no archive — so a day skipped is a day gone.

## Safety machinery you must not weaken

- **`arm()`** adopts quantities from `ib.positions()` before every live session,
  because *the ledger is a local reconstruction and the account is the fact*. On
  2026-07-31 the ledger read flat while the account held $2.07M gross; the next
  fire would have re-bought the entire book against 164,500 CAD of excess
  liquidity at 83% margin use. `arm()` raises `NotArmed` rather than transmitting
  on unverified state.
- **The same-day guard.** The trade phase is not idempotent and there is no dedupe
  at the broker. A second armed run stacks a second order set — worse than a
  duplicate, because `arm()` reads positions that do not include the still-unfilled
  MOC orders, so both sets fill in the same auction and the book doubles.
- **Sibling-book attribution.** Three books share one IBKR account with overlapping
  tickers. `_live_positions` is per-sleeve; `reconcile()` checks the tagged books
  sum to `ib.positions()`. **Never take a symbol from the account net.**
- **`DRY_RUN=1` is a human hard halt** and always wins.
- **The halt file is a hard gate.** `ops/HALT.md` is durable, greppable and read by
  preflight. It survives reboots and outlives any notification. Alerting is
  best-effort and must never be able to mask the fault it reports: the file write
  happens first and unguarded, and every notification path is individually wrapped.

## Alerting

The 2026-08 lesson: **a guard that lives inside a job cannot catch a job that never
starts, and a guard that shares a broken assumption with the thing it guards is not
a guard.** That is why `ops/doctor.py` runs outside every job and checks plumbing
rather than strategy.

A non-armed session is currently silent — it writes `ok_not_armed` to the heartbeat
and raises nothing, which is why a 21-session outage went unnoticed for a month.
This is the highest-value operational fix available and it is what `docs/prompts/W3`
covers. If you touch alerting, make a non-armed session loud.

## When you change anything here

- New behaviour goes behind a frozen-spec key that **defaults to current
  behaviour**, and you prove the no-op by diffing sleeve output byte-for-byte with
  the key absent.
- Add a test next to the existing ones in `src/deploy/tests/`.
- Prefer expressing an intent in **shares**, not weights, where the broker will see
  it: the dust-order defect was cured at source that way, and `min_trade_usd` is
  only a backstop.
- `PositionTarget.weight` is signed. Do not apply the side sign twice.
- Order type stays MOC unless a pre-registered A/B changes it.

## Broker client

`ib_async` only. `ib_insync` 0.9.86 is unmaintained and hangs forever in its
asyncio handshake on Python 3.12+ — it looks exactly like a dead broker connection,
and an hour was lost to that before the socket was proved fine by hand. Two legacy
scripts still import it; do not add a third.

`IBKRConfig.from_env()` reads process env, then the config file. Before that
existed, `make_broker` passed only `books_root`/`verbose`, so the dataclass default
port always won and every live run would have died with `ConnectionRefused`.
