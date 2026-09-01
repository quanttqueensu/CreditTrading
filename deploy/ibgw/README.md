# IB Gateway + IBC — running the broker without a human

TWS needs a person to log in every day. That is why the book sat flat from
2026-08-01 to 2026-08-31: preflight blocked on a dead socket for 21 consecutive
sessions and nobody noticed. Gateway is TWS with the UI removed; IBC automates
its login and daily restart. Together they remove the human from the loop.

**This fixes the broker, not the scheduler.** The other outage — 2026-08-31,
when `collect` and `watchdog` never fired and `benchmarks` ran 51 minutes late —
was the Mac sleeping, and no gateway change touches that. You still need:

    sudo pmset repeat wakeorpoweron MTWRF 09:20:00

An always-up gateway that a sleeping laptop never connects to buys nothing.

---

## Which path

| | native | Docker |
|---|---|---|
| this Mac, today | **use this** | Docker is not installed |
| moving to a VPS later | no | **use this** |

Both give the same thing: a gateway on `127.0.0.1:4002` that logs itself in.
Do **not** run both, and do not run either alongside TWS — see the cutover
order below.

### Native (macOS, recommended for now)

1. Download **IB Gateway** (stable) and **IBC** (`IBCMacos-3.x.zip`) from
   IBKR and the IBC releases page.
2. Install IBC to `~/ibc`, copy `config.ini.example` to `~/ibc/config.ini`.
3. In `config.ini` set:
   - `IbLoginId` / `IbPassword`
   - `TradingMode=paper`
   - `IbAutoClosedown=no`
   - `AutoRestartTime=03:00 AM` — must sit clear of 17:15 (CEF) and 17:25
     (benchmarks), or a restart eats a session
4. Start it with `~/ibc/gatewaystart.sh`. To survive reboots, wrap that in a
   launchd agent the same way the trading jobs are.

### Docker (portable / VPS)

`docker-compose.yml` here is ready. It needs Docker installed first — as of
2026-09-01 this machine has only a stale homebrew `docker-compose` v1 and no
daemon.

    cp deploy/ibgw/.env.example deploy/ibgw/.env   # then fill it in
    docker compose -f deploy/ibgw/docker-compose.yml up -d
    docker logs -f quantt-ibgw                     # watch the login complete

The API port is bound to `127.0.0.1` deliberately. It is an unauthenticated
order-entry socket to a brokerage account: anything that can reach it can
trade. On a VPS keep it behind a VPN or SSH tunnel, never `0.0.0.0`.

---

## Cutover

Order matters. IBKR allows one market-data session per username, so Gateway and
TWS running together will fight over it and produce failures that read like
config bugs.

    1. finish the day's session      (do not cut over mid-book)
    2. quit TWS completely
    3. start Gateway + IBC, wait for the login to complete
    4. python3 -m ops.switch_broker --verify        # proves it, changes nothing
    5. python3 -m ops.switch_broker --to 4002       # verifies, then repoints
    6. run one book and watch the log

Step 4 is the point of the exercise. `IBKR_PORT` is the only thing deciding
which brokerage account this repo trades, so `switch_broker` refuses to change
it until the target has proven three things:

- it speaks the API, not just TCP — a listening socket is not a logged-in
  gateway, and the August outage looked identical at the TCP layer
- it is the same account id as the current endpoint, or (when TWS is already
  stopped) it holds the positions the shadow ledgers claim
- its holdings match, so a paper login pointed at live shows up as a position
  set that does not overlap

Verified behaviour, 2026-09-01: refuses on a closed port (exit 1, `config/.env`
untouched); passes against the live endpoint, confirming account `DUQ199038`
and 34/34 ledger-claimed symbols.

### Rollback

    python3 -m ops.switch_broker --rollback

Restores the `config/.env` saved at switch time. Restart TWS and you are back
where you were.

---

## Notes

- **`ib_async` is already what this repo uses** (`requirements.txt`,
  `ibkr.py:333`). No client change is needed. `ib_insync` remains pinned only
  for two legacy scripts and must not be used in new code — it hangs its
  asyncio handshake on Python 3.12+, which presents exactly like a dead gateway.
- **Reconnect handling is already correct.** Every call site connects and
  disconnects inside a session (`ibkr.py:339`, `preflight.py:230`,
  `capture_fills.py:110`, `reconcile_orders.py:121`), so nothing holds a socket
  across Gateway's daily restart or the Sunday maintenance window.
- **Client ids** are 17 (phase0), 45 (cef), 46 (benchmarks), with `+50/+60/+70`
  for the read-only tools and 199 reserved for `switch_broker`'s probe. Many
  client ids against one session is fine; two *sessions* is not.
- **2FA**: paper logins do not carry live's enforcement, which is why this is
  tractable at all. If this is ever pointed at a live account, IBKR Mobile push
  works with IBC and SMS does not.
- **Credentials** live in `deploy/ibgw/.env` (gitignored), never in the compose
  file. That is a different secret from `config/.env`, which says *where* to
  connect, not *who* to log in as.
