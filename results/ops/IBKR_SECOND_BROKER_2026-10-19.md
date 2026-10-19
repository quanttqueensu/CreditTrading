# IBKR as a second broker for the shorts Alpaca will not lend: design and plan (2026-10-19)

**Team lead, 2026-10-19:** open IBKR as a second broker, **equities only** (no options
data), for the shorts Alpaca will not lend. The team lead opens the account and does
the weekly two-factor login. IBKR may also carry SPAC redemption elections and an E1
merger-pair short leg; other agents own those.

**This is a design and a plan. ZERO TRIALS. No live-path code was written.** Nothing
was opened, signed up for, logged into or connected to at IBKR. No TWS, Gateway, API
or Client Portal session. Every IBKR fact below comes from IBKR's public pages or its
public shortstock file. No broker credential was loaded: the Alpaca figures come from
the committed probe snapshots.

Reproduce every number:

    python3 scripts/ops/ibkr_second_broker_names.py --today 2026-10-19 --offline   # §1 (drop --offline to refetch IBKR's file)
    python3 scripts/ops/ibkr_paper_moc_fills.py                                    # §2.6, §2.11 (IBKR-era record at tag pre-clean-slate)
    python3 -m pytest scripts/ops/tests/test_ibkr_second_broker_names.py

Tables: `results/ops/ibkr_second_broker/names_2026-10-19.csv`. Sources: `docs/REFERENCES.md`
§12af (this pass) and §12aa (the 2026-10-18 IBKR reading, `results/events/MERGER_ARB_AND_IBKR_2026-10-15.md`
Part B, which this note builds on and does not repeat). Labels: [V] fetched and read
this session, [S] sourced but not re-read, [U] not verified.

**Data as of.** Spec `cef_discount.v7.20260928` (13 names), read through `scripts/cef/spec.py`.
Alpaca: the five committed probe snapshots, 2026-09-28 to 2026-10-15 (the newest was
fetched 2026-10-15T20:01Z), plus the merger job's 2026-10-18 flag read. IBKR's
`shortstock/usa.txt` header is **`#BOF|2026.10.19|10:59:08`**. The file states no
time zone. It was fetched at 2026-10-19T15:04:15Z, which is 11:04 ET, five minutes
after the stamp read as ET. The price panel `data/cef/cef_prices.parquet` runs to
2026-10-15. Borrow flags are true on their date only (`CLAUDE.md` landmine 5).

---

## Verdicts

1. **The names that need IBKR change from week to week, so routing must be decided
   daily at run time.** It cannot be a list written here (H14).
   - The newest probe snapshot (2026-10-15) has one spec name `shortable: false`:
     **MHD**.
   - Across the five snapshots, **PHK** was unshortable on 2 dates and **MHD** on 1.
   - On 2026-10-18, **MHD and MQY** were unshortable.
   - IBKR lists all three today, at **MHD 2.57%/yr, MQY 1.84%, PHK 0.57%** [V on the
     file's stamp]. Its listed availability is 445 times the largest recent MHD short
     and 58 times the largest MQY one. PHK has recently been held long.
2. **Run one book across two accounts, routed by symbol.** Each symbol has one home
   broker. A symbol never has orders at both brokers in one session, and no open
   position ever sits at both. The rule-2 guard runs per broker, and checks both
   brokers before sending to either (§2.3).
3. **MOC at IBKR on paper too: the `late_market` exception is not needed there.**
   - IBKR paper filled 41 of 42 recorded MOC orders in full, and 1 in part [V, our record].
   - It does **not** run the auction. Fills were stamped 15:59:30–15:59:59 ET, and only
     10 of 43 were at the close to the half-cent [V].
   - So IBKR paper fills, like Alpaca's, say nothing about auction cost.
   - Because the Alpaca paper leg goes after 15:50, the IBKR leg needs a **15:45
     go/no-go** before NYSE's freeze (§2.7).
4. **The hardest part is the IB Gateway on the VM, not the order path.**
   - IBKR says headless operation "is not supported" [V].
   - IBKR recommends 4,000 MB of memory for API users. The VM has 1 GiB [V].
   - IBC, the usual login automator, was **retired on 2026-09-01** [V].
   - Recommendation: no IBC and no stored IBKR password. Run the Gateway under Xvfb.
     The team lead logs in each week through an ssh tunnel. Use a dedicated API
     username. Resize the VM or measure first (§2.9).
5. **No market-data subscription is needed** (§2.10). The cost is Pro commissions,
   about 5bp a side on a $10 fund at Fixed. Shorts also pay IBKR's borrow fee. Short
   proceeds earn nothing on the first USD 100,000 (§2.11–2.12).

---

## 1. Which names need it, re-measured

`python3 scripts/ops/ibkr_second_broker_names.py --today 2026-10-19`. "Unshortable" means
Alpaca's `shortable: false`. In every snapshot, `shortable` equalled `easy_to_borrow`.

| name | in spec | probe snapshots | unshortable in | 2026-10-18 read | IBKR fee %/yr | IBKR rebate %/yr | IBKR available |
|---|---|---:|---|---|---:|---:|---:|
| **MHD** | yes | 5 | **1** (10-15) | **false** | **2.5734** | 1.3066 | 850,000 |
| **MQY** | yes | 5 | 0 | **false** | **1.8368** | 2.0432 | 150,000 |
| **PHK** | yes | 5 | **2** (10-10, 10-13) | true | **0.5705** | 3.3095 | 3,000,000 |
| AWF | yes | 5 | 0 | true | 0.8948 | 2.9852 | 600,000 |
| BIT | yes | 5 | 0 | true | 0.9218 | 2.9582 | 200,000 |
| DSL | yes | 5 | 0 | true | 0.4500 | 3.4300 | 1,100,000 |
| HYT | yes | 5 | 0 | true | 0.4663 | 3.4137 | 3,600,000 |
| JFR | yes | 5 | 0 | true | 1.8090 | 2.0710 | 1,300,000 |
| PCN | yes | 5 | 0 | true | 0.6464 | 3.2336 | 2,500,000 |
| PDI | yes | 5 | 0 | true | 0.3168 | 3.5632 | > 10,000,000 |
| PDO | yes | 5 | 0 | true | 0.4135 | 3.4665 | 2,300,000 |
| PFN | yes | 5 | 0 | true | 0.5067 | 3.3733 | 1,500,000 |
| PTY | yes | 5 | 0 | true | 0.9768 | 2.9032 | 6,900,000 |
| NAD | dropped in v7 | 1 | 1 (09-28) | false | 4.9725 | −1.0925 | 250,000 |
| NEA | dropped in v7 | 1 | 1 (09-28) | false | 2.4642 | 1.4158 | 800,000 |
| NVG | dropped in v7 | 1 | 1 (09-28) | false | 4.4412 | −0.5612 | 150,000 |
| NZF | dropped in v7 | 1 | 1 (09-28) | false | 3.2079 | 0.6721 | 350,000 |

What the table says, and what it does not:

- **Frequency.** Five snapshots on five dates is not a rate. It shows that the set
  moves:
  - PHK went from ETB on 09-28 to HTB on 10-10 and 10-13, then back to ETB on 10-14.
  - MHD went to HTB on 10-15 and stayed there on 10-18.
  - MQY was ETB in all five snapshots, but `shortable: false` on 10-18.
  - Two more records sit outside the snapshot count. HYT was `shortable=False` at
    send on 2026-10-01 (`results/cef/ALPHA_LEAKAGE_2026-10-13.md` B1, from the
    laptop's run record). PHK read HTB on 2026-10-12 (`results/cef/REAL_MONEY_COSTS_2026-10-12.md`).
    Neither has a committed snapshot.
  - A daily count needs a daily read. Step A5 (§4) makes the collector record one.
- **Size against availability.** The committed snapshots show the book's recent
  shorts at Alpaca:
  - MHD −1,450 to −1,909 shares (10-10 to 10-14);
  - MQY −1,298 to −2,596 shares (10-10 to 10-15).

  That is at most about 1.7% of MQY's and 0.2% of MHD's listed availability. **The
  file is indicative.** On 2026-09-08/10 it disagreed with TWS tick 236 by up to 28×
  in both directions (`docs/REFERENCES.md` §4). Whether IBKR lends at order time is
  settled only by the order (§5, R5).
- **The fee moves.** MQY was 0.8308% in the file stamped 2026-10-16
  (`results/events/merger_arb/cef_names_borrow_2026-10-18.csv`). It is 1.8368% in
  today's: more than double in one session. Its availability went from 85,000 to
  150,000. A fee is true at its stamp only.
- **Fee + rebate = 3.88** on every row. That is IBKR's benchmark for the day (§2.12).
  A negative rebate (NAD, NVG) means the fee exceeds the benchmark.
- **The four dropped munis are not a decision for this note.** The 2026-09-28 ruling
  dropped NAD, NEA, NVG and NZF because Alpaca would not lend them (`docs/SYSTEM.md`
  §5). IBKR lists all four today at 2.46–4.97%. Bringing them back is a spec change
  (v8) and a CEF trial, under `/spec-change` and `/prereg`, and needs its own ruling.
  The routing below works for any name the spec carries.
- **The MHD short left the account between the 10-14 and 10-15 snapshots.** It was
  −1,450 shares on 10-14 and gone after the 10-15 close, the day Alpaca turned MHD
  HTB. Whether the band closed it or Alpaca bought it in is not in the repo [U]. The
  VM's `2026-10-15/send.json` would say.

---

## 2. Architecture: one book, two brokers

The order-path rules in `CLAUDE.md` (1–5) and the runner's nine gates (`docs/RUNNER.md`)
are the frame. This design changes none of them. It applies each one to a second account.

### 2.1 Accounts

- **Two accounts, one per broker, both for this book:** the existing Alpaca CEF paper
  account and one IBKR account. Margin does not cross brokers (§12aa B8). Each account
  carries its own Reg T and buying-power check, and the book's stress cap is judged on
  combined equity (§2.13).
- **Equities only.** No options permission, and no OPRA or any other paid data
  (team lead, 2026-10-12 and 2026-10-19).
- **The IBKR account takes only what Alpaca will not do: opening shorts Alpaca will
  not lend.** Longs and lendable shorts stay at Alpaca. The 2026-10-09 ruling ("sleeves
  in one account") puts later SPAC and E1 legs in the same IBKR account. So the
  one-symbol-one-broker invariant (§2.2) must hold across sleeves, not only within this one.
- **Base currency USD.** The IBKR-era paper account was CAD-denominated, and every
  figure needed a conversion (`pre-clean-slate:_archive/docs/INFRASTRUCTURE_2026-09-28.md`
  §5.1) [S]. A USD-base account removes that class of error.

### 2.2 Routing: one symbol, one broker, sticky

Decide computes each symbol's netted order as today (`quantt/session/decide.py`: whole
shares, one order per symbol, flips deferred). A new pure function then assigns a
**home broker** to each symbol, from the positions at both brokers and today's flags:

1. **A symbol held at one broker has that broker as its home.** Every order in it,
   reducing or increasing, goes there.
2. **A symbol held at both brokers is an error.** The session refuses before
   `STARTED`, naming it, and verify FAILs. It cannot arise from this design, so if it
   does, something else is trading the account.
3. **A flat symbol goes to Alpaca by default.** It goes to IBKR only when its order
   **opens a short** and two things hold:
   - Alpaca's `/v2/assets/<sym>` reads `shortable: false` at decide;
   - IBKR's evidence for the name passes (§2.5, gate 7 at IBKR).
4. **Positions never migrate.** A short at Alpaca that Alpaca stops lending stays at
   Alpaca.
   - Its reductions go to Alpaca. An increase is skipped, as gate 7 skips it today
     ("skip that name, send the rest", 2026-09-28).
   - A short at IBKR that Alpaca would lend again stays at IBKR until it is closed.
   - Moving a position means closing at one broker and opening at the other: two
     opposite-side orders in one symbol in one auction, at two firms. §12aa B8 rules
     that out (FINRA 5210.02, Exchange Act §9(a)(1)). It would also pay the spread twice.
5. **Flips stay deferred** (`docs/RUNNER.md` "Flips are deferred"). A long at Alpaca
   that the signal turns short is closed today and is flat tomorrow. Rule 3 then routes
   the new short, to IBKR if Alpaca will not lend it.

The plan records each symbol's home and the reason (`held`, `flat-default`,
`short-unlendable-at-alpaca`). The plan's `plan_sha` covers both legs, so an approval
binds both.

**The alternative, a static pin list in the book json** (`brokers.ibkr: [MHD, MQY]`), is
simpler and avoids daily flips. But it is a number written in a document (H14). PHK,
MHD and MQY have each changed state within a week. The sticky rule gets the stability
without the pin. If the team lead prefers a pin, it is one reviewed key in the book
json, whose absence routes everything to Alpaca.

### 2.3 Rule 2, the idempotency guard, per broker

Today gate 6 refuses on any of three things: `<state>/<D>/STARTED`, any Alpaca order
today with the `cef-<YYYYMMDD>-` prefix, or any open order in the account. With two
brokers:

- **A `STARTED` per broker.** `<state>/<D>/STARTED.alpaca` and `<state>/<D>/STARTED.ibkr`,
  each written before that broker's first order. One per broker, because on paper the
  two legs go at different times (§2.7). A single marker would make the later leg
  refuse.
- **Check both brokers before sending to either.** Before the first order to either
  broker, the session asks both, and refuses unless each shows exactly what this
  session's own records say has been sent. For the second leg of a split send, that
  means the first leg's recorded orders and nothing else.
- **At IBKR the check uses three sources, because no single one is reliable:**
  - `reqAllOpenOrders()` on a connection made as the **Master Client ID**. IBKR:
    "Connecting without using the Master Client ID will mean only trades on the
    connected Client ID will be returning" [V]. That is how 79 MOC orders stacked
    unseen on 2026-07-31: `openTrades()` showed one client's orders only (archived
    `INFRASTRUCTURE_2026-09-28.md` §5.4) [S].
  - **Our own order map**, `<state>/<D>/ibkr_orders.jsonl`. It carries `clientId`,
    `orderId` and `permId` and is written immediately after each `placeOrder`. It
    cannot be blind to a restart.
  - **Today's executions** (`reqExecutions`, which covers "since midnight" only [V]).
  - The query fails closed: an error is "not knowing", never "nothing pending"
    (`pre-clean-slate:_archive/ops/pending_orders.py`).
- **Not `orderRef`.** IBKR documents it as "Intended for institutional customers only"
  [V]. The IBKR-era record returned `orderRef=''` on all 257 executions of 2026-07-31
  [V, `pre-clean-slate:…/broker_fills.csv`]. Alpaca's `client_order_id` prefix has no
  IBKR equivalent.
- **Order ids** are client-managed, strictly increasing and persistent [V §12aa]. Take
  `nextValidId` at connect and never reuse one.
- **A transmit lock per broker** (`fcntl.flock`, non-blocking, released by the kernel at
  exit; the archived `_acquire_transmit_lock`). systemd starts a job again when a firing
  passes while it runs (`docs/RUNBOOK.md` §8.2). Two processes could both pass the
  check before either order is acknowledged.
- **Turn off "Maintain and resubmit orders when connection is restored"** in the
  Gateway's API settings. It is on by default [V]. With it on, an order the runner
  counted as failed can reach the exchange after a reconnect. With it off, an ambiguous
  submit still stops the batch (`docs/RUNNER.md`, as built 2026-09-28).

### 2.4 `DRY_RUN`, arming and halts

- **One `DRY_RUN` for both legs.** Either broker transmits only when it is exactly `"0"`
  (rule 4). `AUTO_ARMED`, per-day `APPROVED`, `--approve <plan_sha>` and `ops/HALT.md`
  also govern both legs, unchanged. The sha covers both legs, so what is approved is
  what goes to each broker.
- **Read-only tools never call `placeOrder`.** That covers the IBKR probe, verify and
  the collector. Each connects with its own client id. Two connections on one id evict
  each other (archived `INFRASTRUCTURE_2026-09-28.md` §6.2) [S].
- **`readonly=True` is a second guard, not the first.** It is enforced at the Gateway,
  and `ib_async.IB.placeOrder` has no read-only check of its own (`docs/REFERENCES.md`
  §9) [S]. Safety comes from the code path.

### 2.5 MOC at IBKR

- **The order.** `orderType="MOC"`, `tif="DAY"`, SMART-routed to the primary listing.
  IBKR rejects an MOC with an empty TIF (archived `ibkr.py` `_order` comment) [S].
  IBKR: SMART-routed on-close orders "are designed to be routed to, and execute on the
  Primary Listing Exchange" [V].
- **The cutoff.** IBKR, re-read 2026-10-19: "All MOC orders must be received at NYSE
  markets by 15:50 ET, unless entered to offset a published imbalance. NYSE markets'
  rules also prohibit the cancellation or reduction in size of any market-on-close (MOC)
  order after 15:50 ET" [V].
  - The NYSE freeze is ten minutes before the end of Core Trading Hours, so it moves
    with early closes (Rule 7.35(a)(8), `docs/REFERENCES.md` §3) [V].
  - All 13 names list on NYSE (probe `exchange`, 2026-10-15). Nasdaq's 15:55 does not
    apply.
  - **The IBKR send window ends at the calendar close minus 20 minutes**: 15:40, or
    12:40 on a 13:00 close. That is the archived flatten tool's margin.
  - Nothing at IBKR is cancelled after 15:50, and nothing can be.
- **Evening entry works.** IBKR held MOC orders entered after the close for the next
  auction [V, our record]. The set sent 2026-08-31 17:15 ET filled at the 09-01 close.
  The set sent Friday 2026-09-04 17:58 rested over the Labor Day weekend and filled in
  full at the 09-08 close.
- **Shortability at IBKR (gate 7 for this leg).** A short-opening IBKR order needs
  three things:
  - the symbol in IBKR's file at decide, with `AVAILABLE` at least the order's
    quantity;
  - if the Gateway can read it, tick 236 (`Shortable` > 2.5, "at least 1000 shares";
    `Shortable Shares`, tick 89) [V doc];
  - IBKR's acceptance of the order: "all short sale orders are subject to approval"
    [V §12aa].

  A failure skips the name and sends the rest, and the day is FAIL naming it (the
  2026-09-28 ruling). The name is never substituted.

### 2.6 What IBKR paper does with an MOC order: our own record

IBKR's paper guide says "Fills are simulated from the top of the book" and lists
"Auction" among unsupported order types. It says nothing about MOC [V, "Last updated on
January 30, 2026"]. The book sent MOC orders to an IBKR paper account in September, and
the record survives at tag `pre-clean-slate`. `python3 scripts/ops/ibkr_paper_moc_fills.py`:

| auction | orders (sent ET) | filled in full | in part | no execution captured |
|---|---|---:|---:|---:|
| 2026-09-01 | 17 (08-31 17:15) | 16 | 1 (PCN 2,900 / 3,400) | 0 |
| 2026-09-02 | 17 (09-01 17:15) | 0 | 0 | 17 |
| 2026-09-08 | 17 (09-04 17:58) | 17 | 0 | 0 |
| 2026-09-10 | 4 (09-09 21:46) | 0 | 0 | 4 |
| 2026-09-11 | 1 (09-11 10:38) | 0 | 0 | 1 |
| 2026-09-14 | 4 (09-14 09:50) | 4 | 0 | 0 |
| 2026-09-15 | 4 (09-15 08:39) | 4 | 0 | 0 |

- **On the four auctions with captured executions, 41 of 42 orders filled in full and
  one in part.** That is unlike Alpaca paper's 2 of 13 on 2026-09-29.
- **No execution was captured for three auctions.** "Not captured" can mean unfilled,
  cancelled, or filled and never captured. `ib.fills()` forgets at IBKR's daily restart,
  and the capture ran separately. The record cannot tell these apart, so they are not
  counted either way.
- **The fills are not the auction.** Every execution is stamped 15:59:30–15:59:59 ET.
  Of 43 fills with a panel close, **10** were within half a cent of it. The signed
  difference (positive is worse for us) has median **+8.1bp**, mean +4.9bp and median
  absolute 8.8bp, and reaches 36.5bp. Two fills (2026-09-15 NEA and JFR) have no panel
  close and are left out.
- **The panel close stands in for the official print here.** It is yfinance,
  unadjusted. These dates were not cross-checked against NYSE's own print, so "at the
  close" means at the panel close.
- **Consequence:** IBKR paper, like Alpaca paper, simulates a fill near the close from
  the quote. It does not run the auction. Score the IBKR leg against the official
  closing print exactly as the Alpaca leg is scored (`docs/RUNNER.md`, "Scoring").
  Paper fills are not evidence about auction cost (`docs/SYSTEM.md` §4.3).

### 2.7 The `late_market` paper exception, and the timing it forces

- **The exception is Alpaca's, and stays Alpaca's.** Rule 3's recorded exception
  exists because Alpaca paper under-fills `cls` (2 of 13 on 2026-09-29). IBKR paper
  filled its MOC orders (§2.6), so **the IBKR leg stays MOC on paper**, with no
  exception. The exception never applies to a live account at either broker.
- **The book json makes execution per broker.** Today's block becomes
  `execution.alpaca = {mode: late_market, …}` and `execution.ibkr = {mode: moc}`. With no
  `ibkr` block the session is Alpaca-only and byte-identical to today. That has to be
  proved by test, as with every new key.
- **On paper the IBKR short is committed before the Alpaca longs go.** The IBKR MOC
  must be in by 15:50; Alpaca paper's market orders go 15:52–15:58.
  - Proposed schedule for the session day:
    - the IBKR leg goes from the saved plan between **15:30 and 15:40** ET (never
      re-decided);
    - at **15:45** a go/no-go re-runs the Alpaca send's deliberate gates on fresh
      reads: dry run, arming, halt, clock and exposure;
    - on no-go the session **cancels the IBKR leg**, which is allowed until 15:50.
  - An Alpaca failure after 15:50 can still leave a one-legged day. Verify FAILs it,
    naming both legs.
  - In live `cls` mode both legs are MOC and go in one slot before 15:40, and the
    mismatch disappears.
- **Why not send the IBKR leg the evening before?** It works mechanically (§2.5).
  But availability is re-read at 15:30 on the session day, not 20 hours earlier. And
  Alpaca cancels a queued short whose name flips HTB overnight (§12t). Whether IBKR does
  the same for a queued MOC short is [U] (§5, R12).

### 2.8 `ib_async` only

- **Use `ib_async` 2.1.0** (PyPI, uploaded 2025-12-08, `requires_python >=3.10`). It
  is a pure-Python wheel. Its dependencies are `aeventkit>=2.1.0,<3.0.0`, `nest_asyncio`
  and `tzdata>=2025.2,<2026.0`, all pure-Python wheels [V, 2026-10-19].
  - The VM's `--no-build` install takes it unchanged.
  - Pin `aeventkit` below 3: the current 3.0.1 is outside `ib_async`'s range.
  - The GitHub repository is not archived, and its README names a maintainer [V].
- **Never fall back to `ib_insync`.** Its last release was 0.9.86 (2023-07-02), and it
  hangs on Python 3.12+ (`CLAUDE.md` landmine 10). The archived adapter fell back to it
  when `ib_async` was absent. That fallback is deleted, not ported.
- **Import inside functions only**, so tests and `pytest.ini`'s collection never import
  it. Tests inject a stub module, the archived pattern.

### 2.9 IB Gateway on the VM, and the weekly login

What IBKR says [V, 2026-10-19]:

- **Headless is not supported.** "Both TWS and IB Gateway are designed to have a user
  interface for the client to enter their account credentials. For that reason, headless
  or GUI-less operation is not supported."
- **Daily restart, weekly login.** Gateway and TWS "automatically restart daily without
  user authentication at a chosen time from Monday-Saturday. On Sunday, following the
  Saturday night server reset, it is necessary for the user to re-authenticate". With
  auto-restart, "the session is designed to be able to continue until the following
  Sunday **as long as there are no other logins with the same username** to Client
  Portal, TWS, or IBKR mobile." The API pages put the start of the weekly cycle on Monday.
- **Third-party software is unsupported.** "Interactive Brokers cannot provide any kind
  of support or advice for software not developed by IBKR itself."
- **ARM64 is supported.** IBKR ships **`ibgateway-stable-standalone-linux-arm.sh`**, a
  native Linux ARM64 build, beside the x64 one. The VM (Standard_B2pts_v2, Arm64) can run
  it without emulation.
- **Memory.** "Normally, it is recommended for API users to set 4000 [MB]. However, it
  depends on your computer memory size."

**IBC is retired.** Its repository reads "This repository was archived by the owner on
Sep 1, 2026. It is now read-only" and "This project has been retired, as of 1 September
2026" [V]. Even maintained, it "cannot itself assist" with a 2FA device prompt. It
re-sends the IBKR Mobile alert, and a person must approve it [V, user guide].

Recommended set-up:

- **No IBC, and no IBKR password on the VM or in the vault.**
  - The Gateway runs as `quantt` under Xvfb, from a systemd unit (`quantt-ibgw.service`).
  - A VNC server listens on **127.0.0.1 only**.
  - Each week the team lead runs `ssh -L` to the VM, types the password into the
    Gateway and approves the IBKR Mobile prompt. No NSG change and no new port.
  - Mid-week the Gateway's own "Auto restart" keeps the session.
  - This keeps the password out of every file. The cost is that any mid-week Gateway
    crash or VM reboot needs the team lead again (§5, R1).
- **A dedicated API username.** IBKR allows extra usernames (§12aa B6). Otherwise the
  team lead's own phone or Client Portal login with the same username ends the Gateway's
  session (quote above).
  - Today's paper guide: holders "can log into TWS with their production account
    credentials and select either a production or paper trading account" [V].
  - So the paper session uses a production username, and the same rule binds it.
  - Whether a second username can select the paper account is [U] (§5, R4).
- **Gateway API settings, written down and checked by the installer where it can read
  them:**
  - socket port 4002 (paper) on 127.0.0.1;
  - trusted IP 127.0.0.1 only;
  - Master Client ID set;
  - "Bypass Order Precautions for API orders" on (§2.10);
  - "Maintain and resubmit orders when connection is restored" off (§2.3);
  - "Auto restart" at a time outside every job window: not 15:30–16:00, not the 17:30
    verify, not the 22:00–01:00 decide;
  - "Never lock".
- **Memory.** Standard_B2pts_v2 has **1 GiB**, which already holds the decide's pandas
  run and 2 GB of swap (`docs/RUNBOOK.md` §8). The next Arm sizes [V: Microsoft Learn,
  Bpsv2 series; Azure Retail Prices API, canadacentral, Linux, 2026-10-19]:

  | size | vCPU | memory | USD/hour |
  |---|---:|---:|---:|
  | Standard_B2pts_v2 (today) | 2 | 1 GiB | 0.0092 |
  | Standard_B2pls_v2 | 2 | 4 GiB | 0.0368 |
  | Standard_B2ps_v2 | 2 | 8 GiB | 0.0736 |

  B2pls_v2 at 730 hours is about USD 26.9 a month (arithmetic). Against the USD 100
  student credit that is under four months (`docs/RUNBOOK.md` §8.7). Whether the free
  12 months covers any size but B2pts_v2 was not checked [U].
  - **Measure before resizing:** the Gateway's resident memory and the swap during a
    decide, in shadow (§4, step A9).
  - **The alternative:** a second B2pts_v2 for the Gateway alone, reached over the
    virtual network. It still has 1 GiB.

### 2.10 Market data: none

- **Orders need no subscription.** Decide reads the yfinance panel, and the book's
  equity and positions come from the brokers. IBKR's FAQ: an order without market data
  draws a precaution that holds it "unless user click[s] Transmit". "Bypass Order
  Precautions for API Orders" removes the hold [V]. The IBKR-era account traded MOC
  with "no real-time data subscription; quotes arrive 15 minutes delayed" (archived
  `INFRASTRUCTURE_2026-09-28.md` §5.1) [S].
- **Scoring needs none either.** The IBKR leg is marked against the same official
  closing-auction print the Alpaca leg uses (`/v2/stocks/auctions`, SIP feed,
  condition `M`, exchange `N`). One scorer serves both legs.
- **Free data, where the Gateway can read it:**
  - delayed (15–20 minute) data for NYSE and Nasdaq names [V];
  - tick 236. Whether it needs a subscription is [U]. It answered on the IBKR-era
    account, which had none [S];
  - `FEE_RATE` historical bars, the archived `fetch_borrow_history.py` source [S].
- **A paper username sees no data** unless the live username shares its data with it
  ("Market data is attached to each username") [V].
- **If a subscription is ever wanted** (§12aa B5, [V] 2026-10-18): NYSE L1 USD 1.50 a
  month non-professional and USD 45.00 professional. Any entity account is
  professional. No equities data is needed for this design.

### 2.11 Pro vs Lite, and commissions at our size

- **The API needs IBKR Pro** (§12aa B6) [V]. IBKR Lite is "available to US residents"
  only.
  - Lite's on-close trades are commission-free only while open-auction, close-auction,
    outside-RTH and sub-dollar volume together stays within 10% of the month's US stock
    volume. Above that, Lite charges "the lesser of (i) USD 0.005 per share or (ii) 1% of
    trade value" [V].
  - All of this book's volume is close-auction, so Lite would not be free even where the
    API allowed it.
- **IBKR Pro Fixed:** USD 0.005 a share, minimum USD 1.00, maximum 1% of trade value.
  Regulatory fees pass through:
  - SEC fee USD 0.0000206 × sale value;
  - FINRA TAF USD 0.00 per share sold, with a "Fee Holiday … from Oct 1, 2026 through
    Dec 31, 2026";
  - CAT USD 0.000003 a share [V].
- **IBKR Pro Tiered:** USD 0.0035 a share (up to 300,000 shares a month), minimum USD
  0.35, plus exchange, clearing (USD 0.00020 a share) and pass-through fees [V].
  - "Directed API orders cannot use the Tiered fee structure."
  - The NYSE closing-auction exchange fee was not read [U].
- **The IBKR-era paper account was on Fixed, to the cent** [V, our record]:
  - buys USD 0.005003 a share;
  - sells about USD 0.0054 (with the SEC and FINRA fees);
  - USD 1.00 minimum (JFR 13 shares);
  - the 1% cap (DSL 3 shares, USD 0.325 on USD 31.50).

  Fixed is the measured default. Tiered saves at most about USD 0.0013 a share before
  the unread auction fee.

Fixed commission at our size (arithmetic on the schedule):

| share price | 100 shares | 500 shares | 1,500 shares |
|---|---|---|---|
| USD 10 (MHD, MQY ≈ 10.2 on 2026-10-15) | USD 1.00 = 10.0bp | USD 2.50 = 5.0bp | USD 7.50 = 5.0bp |
| USD 4.08 (PHK, 2026-10-15) | USD 1.00 = 24.5bp | USD 2.50 = 12.3bp | USD 7.50 = 12.3bp |

Alpaca charges no commission. So the IBKR leg pays about 5bp a side on a USD 10 fund,
more on small band trades, where the USD 1.00 minimum binds below 200 shares. That is
the price of a short the book otherwise could not hold.

### 2.12 Borrow fee accrual

- **The formula.** IBKR charges market value × fee rate ÷ 360, every calendar day, with
  market value marked up to 102% of the prior settlement price and rounded up to the
  nearest dollar (`docs/REFERENCES.md` §4) [V].
- **Short proceeds earn nothing on the first USD 100,000.** IBKR Pro pays 0% on
  USD 0–100,000 of short proceeds, then 2.630% (BM − 1.25%) to USD 1m, re-read
  2026-10-19 [V]. The benchmark implied by the file's fee + rebate is 3.88% today. The
  IBKR leg is far below USD 100,000, so it earns no rebate.
- At today's file rates, per USD 10,000 of short market value (formula above, 365 days):

  | name | fee %/yr | USD a year | USD a day |
  |---|---:|---:|---:|
  | MHD | 2.5734 | 266 | 0.73 |
  | MQY | 1.8368 | 190 | 0.52 |
  | PHK | 0.5705 | 59 | 0.16 |

  These are true at the stamp only. MQY's rate doubled in a day (§1). This is a
  forward illustration, not a historical cost (`docs/BRIEF.md` H4).
- **On paper,** Alpaca charges no borrow [V]. Whether IBKR paper accrues borrow or
  payment in lieu is [U] (§5, R6). Paper is scored gross (D19/D20). The IBKR leg's
  borrow goes on its own labelled line:
  - **MODELLED** from the day's file rate when the account charges nothing;
  - **IBKR-charged** when its statements show a charge.
- **For a live account** (the real-money cost re-run the 2026-10-09 ruling makes the
  gate for capital), two reads would record the fee the book would pay, each day:
  - the collector's daily read of the public file (§4, step A5);
  - once the Gateway is up, the archived `fetch_borrow_history.py`'s `FEE_RATE` bars.

### 2.13 Verify, equity and scoring across two brokers

- **Positions are the union of both brokers', keyed by symbol.** A symbol at both is a
  FAIL (§2.2). `is_opening_session` reads both.
- **Equity for sizing is the book's, not IBKR paper's USD 1,000,000** [V paper equity].
  Two options for the team lead:
  - **(a)** Book equity = Alpaca equity + (IBKR NetLiquidation − IBKR NetLiquidation at
    the IBKR epoch). The epoch value is read from the broker once, before the first
    IBKR order, and recorded in the state dir with its time. The book stays at its
    `capital_usd`. This is the default.
  - **(b)** The team lead resets the paper equity to the leg's intended capital (paper
    equity "up to five times your production account's value", reset requests before
    16:00 ET for the next day [V]). Book equity is then the plain sum, and the book's
    capital grows by that amount, which is a `/spec-change`.
- **Gate 8 per account.** Each leg's opening notional is checked against its own
  broker's buying power. The overnight Reg T and maintenance checks run per account.
  The `max_gross_stress` cap is judged on the combined book and combined equity. The
  2026-10-11 lower-of rule is unchanged.
- **Fills.** Alpaca's come from orders and activities, as today. IBKR's come from
  `reqExecutions` **on the session day**, because it returns "current day's (since
  midnight)" executions only [V]. The archived `capture_fills.py` lost 2026-07-31's 302
  executions that way [S].
  - Verify at 17:30 is same-day.
  - The durable record is a **Flex Web Service** trade query: a "standalone HTTP API"
    that delivers the same reports as Client Portal, using a token made there [V].
  - It needs no Gateway, so a down Gateway cannot lose the record.
- **One verdict line.** Verify PASSes only if both legs reconcile. A leg that could not
  be sent because the Gateway was logged out is a `MISSED:` FAIL naming IBKR. The
  2026-10-09 rule stands: only `DRY_RUN`, arming or a halt explains a no-trade.
- **Scores.** Each leg's broker fill is that leg's official record, labelled by broker.
  The auction-print P&L and the distribution-adjusted third line (`docs/RUNNER.md`) cover
  the whole book. The IBKR borrow line sits beside them, labelled (§2.12).
- **Cross-broker wash sales are ours to compute**, live only. Neither 1099-B will
  (§12aa B8).

---

## 3. Code: what to revive from `pre-clean-slate`, what to build

Everything below is read with `git show pre-clean-slate:<path>`. **Revive means port
the logic and its incident docstrings into the `quantt/` design.** Nothing is checked out
as it was. The old adapter carried a shadow ledger and per-sleeve attribution. The
2026-09 halts came from those, and the Alpaca design removed them ("the broker is the
fact").

| path at the tag | what it did | revive? what it needs |
|---|---|---|
| `_archive/src/deploy/broker/ibkr.py` (2,144 lines) | The IBKR paper adapter. `ib_async`, imported lazily. Contracts. MOC `Order(orderType="MOC", tif="DAY")`. `_check_pending` (`reqAllOpenOrders` + `openTrades` + order map, fails closed). The flock transmit lock. Commission reports (a defaulted report has `execId == ""`). `permId` backfill. Order map keyed on `client_id` + `book_id`. Shadow ledger, `arm()`, per-sleeve attribution | **Port the order and guard pieces** into `quantt/broker/ibkr.py`. **Drop:** the `ib_insync` fallback; `IBKRConfig.from_env`, which reads `config/.env` itself and defaults every missing value (a silent fallback; host, port and client id become required env vars); the shadow ledger and `arm()`; bonds, options and combos |
| `_archive/ops/pending_orders.py` (241) | Two-source check for "a set already headed for this auction": broker plus own order map, each with a named blind spot | **Port** into gate 6's IBKR branch (§2.3), with its tests' incident cases |
| `_archive/ops/capture_fills.py` (586) | Same-day capture of `ib.fills()` before the restart; refuses symbol attribution when two books share a ticker | **Port the timing lesson** into verify's IBKR reconcile, plus Flex as the durable source (§2.13). One book per account removes the attribution problem |
| `_archive/ops/flatten_ibkr_account.py` (304) + `_archive/ops/tests/test_flatten_ibkr_account.py` | Human-run flatten by MOC. Dry and read-only by default. `--account` must match the broker's. Refuses after 15:40 (12:40 early), on a second run, and on non-stock or non-USD positions | **Revive as a human-run tool** for the IBKR leg (rule 1). The expected account id comes from the environment at run time, never from a tracked file |
| `_archive/ops/cancel_open_orders.py` (113) | Lists, then cancels, one client id's resting orders. Lesson: `cancelOrder` fails across client ids (error 10147); `reqGlobalCancel()` cleared the 2026-07-31 stack | **Revive as a human-run tool.** It is the only undo before 15:50, and the 15:45 no-go (§2.7) uses the same call |
| `_archive/ops/switch_broker.py` (276) | Proves a Gateway endpoint before trusting it: it speaks the API, it is the same account, its positions are recognisable | **Port its checks** into the IBKR probe and the session's connect: the account id must equal the expected one, compared at run time and never printed |
| `_archive/scripts/cef/fetch_borrow_rates.py` (307), `_archive/scripts/cef/fetch_borrow_history.py` (118) | Daily IBKR file panel plus a tick-236 cross-check; `FEE_RATE` history bars (NAD: 1,249 bars, 2021-09-13 → 2026-09-09 [S]) | **Revive the file part now** (no account; §4, A5). The tick-236 and `FEE_RATE` parts follow once the Gateway is up |
| `_archive/src/deploy/tests/test_pending_orders_guard.py` | Guard tests on a broker built with `__new__` and an order map in `tmp_path`; real incident timestamps | **Port the pattern**: a stub `ib_async` module, no socket, `ops/netguard.py` |
| `_archive/docs/INFRASTRUCTURE_2026-09-28.md` §5–6 | Client-id table, the 79-order stack, CAD sizing, "one session per client id" | Read before building. Do not restore |
| `_archive/scripts/rv/probe_ibkr_spreads.py`, `fetch_ibkr_spreads.py` | Quote and spread probes | **No:** market data is out of scope |
| `_archive/ops/reconcile_orders.py`, `rebuild_ledger.py`, `src/deploy/exec_ledger.py` | Ledger against broker | **No:** there is no ledger to reconcile |

New in `quantt/` (a build contract like `docs/RUNNER.md` comes first, for review):

- **`quantt/broker/ibkr.py`**, with `AlpacaClient`'s shape:
  - account summary (NetLiquidation, buying power, excess liquidity, margin);
  - positions, all-client open orders, today's executions with commission reports,
    `place_moc`, `cancel`, `next_order_id`;
  - paper port only: a live port anywhere is a test failure, as Alpaca's live endpoint
    is;
  - `ib_async` imported inside functions;
  - no default for a missing field.
- **`quantt/broker/ibkr_probe.py`:** a read-only snapshot to `results/ops/ibkr_probe/`,
  account identifiers redacted (2026-10-12 ruling).
- **`quantt/broker/ibkr_flex.py`:** the Flex fetch for verify. Its token is from the vault.
- **`quantt/session/route.py`:** the pure routing function of §2.2.
- **Changes to existing modules:**
  - `decide.py`: legs per broker;
  - `gate.py`: per-broker gates 6–8 and the IBKR send window;
  - `run.py`: per-broker `STARTED`, the 15:30 IBKR send, the 15:45 go/no-go;
  - `verify.py`: union reconcile, per-leg scores;
  - with no `ibkr` block in the book json, each is **proved byte-identical** to today.
- **`quantt/collect`:** the daily IBKR file read for the 13 names and the four dropped
  ones. It also records Alpaca's flags daily, already read by the collector's account
  snapshot.
- **`quantt/deploy`:**
  - `quantt-ibgw.service` (Xvfb, Gateway, VNC on localhost);
  - a bootstrap step that installs the ARM64 Gateway at a pinned version and sha256;
  - installer checks on its unit, as `docs/RUNBOOK.md` §8.3 does for the others.

---

## 4. Steps, in order

**Before the account exists, an agent can do A1–A6.** A2–A6 are live-path or deploy
code. Each needs the team lead's go to start and a release-check to ship. None
transmits anything.

| # | who | step | needs |
|---|---|---|---|
| A1 | agent | This note; `scripts/ops/ibkr_second_broker_names.py`; `scripts/ops/ibkr_paper_moc_fills.py` | done 2026-10-19 |
| T1 | **team lead** | Decide: individual or entity (market data, §2.10); Reg T margin (USD 2,000 minimum to short [V §12aa]); **Pro, Fixed**; USD base; who the second (API) username is; equity option (a) or (b) of §2.13; the sticky rule or a pin (§2.2); the 15:30 send and 15:45 go/no-go (§2.7) | this note |
| A2 | agent | Build contract `docs/` note for the IBKR leg (the RUNNER.md shape), for review | T1 |
| T2 | **team lead** | Apply for the IBKR Pro margin account (USD base). Fund it. Request short-selling. Find the paper account (individual holders get one automatically [V]) | account approval time [U] |
| A3 | agent | `quantt/session/route.py` and per-broker gates, with tests proving the Alpaca-only path byte-identical | T1 go |
| A4 | agent | `quantt/broker/ibkr.py`, probe, flex, against a stub module; never connected | T1 go |
| A5 | agent | Collector: daily IBKR file read, cached and recorded (public file, no account) | T1 go |
| A6 | agent | `quantt-ibgw.service`, bootstrap and installer changes; `docs/RUNBOOK.md` §9 draft (Gateway, tunnel, weekly login, settings list) | T1 go |
| T3 | **team lead** | 2FA: IBKR Mobile (IB Key) for the API username. Add that username in Client Portal. Check it can select the paper account (R4) | T2 |
| T4 | **team lead** | Client Portal: create the Flex token and a trade-confirmation query. Put both in the vault as two secrets (names in A6's runbook; values never in a chat or a file). Put the expected IBKR paper account id in the vault too, for the run-time identity check | T2 |
| T5 | **team lead** | Paper equity: leave at USD 1,000,000 (option a) or reset (option b) | T1 |
| T6 | **team lead, `!`** | VM: resize (`az vm resize`, with the go) or approve a measured trial on 1 GiB (A9) | T1, credit |
| T7 | **team lead, `!`** | VM: run the bootstrap additions with sudo (Xvfb, VNC bound to localhost, Gateway as `quantt`), then the installer, dry (`docs/RUNBOOK.md` §8.3 shape) | A6 released at a tag |
| T8 | **team lead** | First login: `ssh -L` to the VNC port, type the API username's password into the Gateway, approve on the phone. Set the §2.9 API settings and screenshot them for the record | T3, T7 |
| A7 | agent | Read-only IBKR probe through the Gateway: account id check, positions, open orders, tick 236 and `FEE_RATE` for the 17 names. Commit a redacted snapshot | T8; the probe never transmits |
| A8 | agent | Settle R7 and R11 **by asking, not trading**: Gateway settings readback; `reqAllOpenOrders` across a Gateway restart with no orders resting. Any probe order needs rule 1: the team lead sees it first | T8 |
| A9 | agent | Shadow: the VM decides with the IBKR leg planned and **not sent** (`DRY_RUN=1` for the leg) for N sessions the team lead sets. Measure Gateway memory and swap, missed logins, and routing flips | T8 |
| T9 | **team lead** | The first armed IBKR leg: its concrete order list shown, then an explicit go (rule 1), then `approve`. `AUTO_ARMED` stays as today | A9 |
| T10 | **team lead** | Weekly, every Sunday after the reset, or Monday before 15:30 ET: the 2FA login (T8) | ongoing |

**Realistic order:**

1. T1 now.
2. T2 and A2–A6 in parallel. The account application is the long pole [U].
3. Then T3–T5, T6–T7, T8.
4. Then A7–A8, the shadow (A9), and T9.

**What waits for the account:** nothing in A2–A6. Everything from T3 on does.

---

## 5. Risks and open questions

Each item is [U] unless marked, with what would settle it.

| # | risk or question | what settles it |
|---|---|---|
| R1 | **Uptime of a manually logged-in Gateway.** A missed Sunday or Monday login, a Gateway crash, or a VM reboot (kernel updates are manual, `docs/RUNBOOK.md` §8.2) leaves the IBKR leg down until the team lead logs in. Those shorts are skipped, so the book is net long by them (the alpha-only mandate; see R13) | Count logged-out sessions in shadow (A9). Ruling on R13 |
| R2 | **Memory.** 1 GiB VM against IBKR's 4,000 MB recommendation [V]. The swap could thrash during the decide or the 15:52 send | Measure resident memory and swap in shadow; resize (T6) |
| R3 | **Xvfb and no IBC are outside IBKR's support** ("headless … not supported"; no support for third-party software [V]). Whether the ARM64 Gateway runs stably under Xvfb for a week is unknown | A9 |
| R4 | **The dedicated API username and paper.** Paper logs in with production credentials [V]. Whether a second username can select the paper account, and whether IBKR Mobile can hold two users' IB Key, are unknown | T3, in Client Portal |
| R5 | **The file is indicative.** IBKR's actual lend at order time can differ (28× in September, §4 of REFERENCES); "all short sale orders are subject to approval" [V] | The first armed IBKR orders. Each rejection is named in `send.json` |
| R6 | **Does IBKR paper check real availability, charge borrow, or charge payment in lieu?** The IBKR-era paper account did carry the very shorts Alpaca now refuses: −8,856 MHD, −6,550 NAD, −4,679 NVG on 2026-09-08/15, reconstructed from captured fills [V record]. Whether it charged for them was never read | Flex statements after the first week (T4) |
| R7 | **Does `reqAllOpenOrders` on the Master Client ID report another client's MOC across the nightly restart?** Flagged unmeasured in the archived `pending_orders.py` | A8. Until then the order map is the guard that cannot be blind to a restart |
| R8 | **IBKR paper fills are not the auction** [V, §2.6], and "no execution captured" for three September auctions cannot be told from "unfilled" | Score against the official print. Fill rate from verify's same-day capture plus Flex |
| R9 | **One-legged days on paper.** The IBKR MOC commits before the Alpaca send (§2.7). The 15:45 go/no-go covers the deliberate gates, not an Alpaca failure after 15:50 | Count them in verify. They vanish in live `cls` mode |
| R10 | **Capital and margin split.** Shorts at IBKR need IBKR collateral. Alpaca's longs cannot use IBKR's short proceeds (§12aa B8). In live the book needs more capital than its gross implies | Team lead, with option (a)/(b) of §2.13 and a `/spec-change` if capital changes |
| R11 | **Resubmit-on-reconnect, master client id and precaution bypass are Gateway settings, not code.** A reinstall or upgrade can reset them | Read back in A8, and on every probe if the API exposes them; otherwise a screenshot at each install |
| R12 | **Queued shorts.** Alpaca cancels a queued short whose name turns HTB overnight (§12t). Whether IBKR cancels or rejects a short MOC when availability vanishes between entry and the auction is unknown | The 15:30 send keeps the gap short. Watch rejections in shadow and live |
| R13 | **What the Alpaca leg does when the IBKR leg cannot go.** Today's rule ("skip that name, send the rest", 2026-09-28) leaves the book net long. Holding the whole book, or scaling the longs, are the alternatives | Team lead ruling |
| R14 | **Account jurisdiction.** The IBKR-era paper account was CAD-denominated [S], which suggests a non-US account. Lite is US-only [V], which does not matter since the API needs Pro. Whether USD base, US short selling and IB Key work as described for the team lead's jurisdiction is unknown | T2 |
| R15 | **Fees and rates move.** The MQY fee doubled in a day. The FINRA TAF holiday ends 2026-12-31 [V]. The NYSE closing-auction fee under Tiered was not read | The collector's daily file read; re-read the commission page before any live capital |
| R16 | **Other sleeves in the same account** (SPAC elections, E1 short leg) must respect one-symbol-one-broker and per-broker `STARTED`. SPAC elections are voluntary corporate actions, and their IBKR process and fee were not read | The owners of those sleeves, against §2.2–2.3 |
| R17 | **The four dropped munis** would need a v8 spec and a CEF trial. Out of scope here | Team lead ruling, then `/prereg` |

**Corrections and negatives recorded by this pass.**

- **§12aa line "Paper: needs a funded live account (or free trial)".** The paper guide,
  re-read 2026-10-19, does not say "funded". It says "New individual account holders
  automatically receive a paper trading account" and links "Open a Free Trial Account".
  The funded-account requirement binds through the API instead: "a funded and opened
  IBKR Pro account" (§12aa B6). The Web API says "Must maintain a funded account" [V].
  Recorded in §12af.
- **The Web API is not a route around the weekly login for an individual account.**
  "OAuth 2.0 is not available to Individual account structures" [V]. Individuals
  authenticate through the Client Portal Gateway, by a browser on the same machine [S].
  This settles §12aa's open "Web API and FIX" item for the Web API. FIX was not read.
