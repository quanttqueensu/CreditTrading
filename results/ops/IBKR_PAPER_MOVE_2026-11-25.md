# The three paper books move to IBKR paper: design, bar and build contract (2026-11-25)

**Team lead, 2026-11-25, by question prompt.**
- Asked "can we switch to ibrk to use MOC". Ruled **"Move paper books to IBKR paper."**
- Then: "we need the moc but it needs to be able to trade all our books equaly as good if not better."
- The later rulings in this note (§1) came the same evening.

**This is a design, a bar and a build contract. Nothing has been sent, armed or installed, and no IBKR session has been opened.**
- Every IBKR fact here was read on 2026-11-25 from IBKR's public pages.
- The pages are listed in `docs/REFERENCES.md` §12ib.
- The account facts come from the team lead's answers.
- This note supersedes the plan of `results/ops/IBKR_SECOND_BROKER_2026-10-19.md`, which used IBKR as a second broker for the shorts Alpaca will not lend. That note's IBKR mechanics still hold, and this note points to them rather than repeating them: §2.3 (the rule-2 guard), §2.5–2.6 (MOC at IBKR and what IBKR paper did with it), §2.8 (`ib_async`), §2.9 (the Gateway) and §3 (what to port from tag `pre-clean-slate`).

Reproduce the baseline (§2): `python3 results/ops/ibkr_paper_move_2026-11-25/baseline.py ROOT`, on local copies of the VM's verify records (`<book>/scores.csv`, `<book>/tca.csv`).

## 1. What the team lead ruled

| question | ruling |
|---|---|
| Move the paper books to IBKR for MOC | **"Move paper books to IBKR paper."** This supersedes 2026-10-28's "Where paper runs meanwhile: Alpaca paper, unchanged". It is chosen knowing that IBKR paper does not run the auction either (§3) |
| The bar | **"Equaly as good if not better"**, for every book (§2) |
| How a book leaves Alpaca | **"Side by side, 10 sessions"**, then narrowed the same evening to **"1 clean session"**: "honestly we dont need a week, i want to switch to ibrk as soon as posisble if it works better". No read-only week; a weekend dry check on saved plans replaces it. Each book's IBKR twin trades the same plan as the Alpaca book, on the same days. A book cuts over after one clean side-by-side session in which it matches or beats Alpaca on every line of §2, and the team lead rules on that table. Until then the Alpaca account stays the book's P&L of record |
| Which account | **The team lead's existing IBKR account, the one the book traded on until 2026-09-28, which is still open.** The team lead: "we cant pay for a account". So there are no new or extra funded accounts. IBKR allows "only one paper trading account" per account [V], so the three books share that account's one paper account |
| How the three books share it | **"All three together."** Core, C4 and events go into the one paper account from the first day. Orders are netted per symbol into one MOC order, and a per-book ledger keeps each book's shares and cash. This is the pattern the events book already uses for its eight sleeves (`quantt/sleeves/ledger.py`) |
| A logged-out connection | **"No phone."** A logged-out IBKR Gateway shows on the daily page and in orient only. This keeps the 2026-09-28 dashboard-and-logs-only rule. Asked first as a phone notification, then withdrawn |
| When the build starts | **"Start now, ship later."** It is built on a branch and ships at a later weekend release, after a release check, with the team lead's go. The 28 Nov release is unchanged |
| What the IBKR account runs | **"Copy all our existing logic and execution strategy for all 3 sleeves and stratgies on our ibrk account hosted on a vm."** The twin trades every book's own decisions, so the logic is the same code and the same plans. The ledger tracks all ten strategies: core, C4 and the events book's eight sleeves (§4.2). The send carries over the books' gates that do not depend on Alpaca, and the buying-power rule (§4.1) |
| Hosting | **"Whatever we can do for free / student account free."** The Gateway goes on the existing VM, whose size, B2pts v2, is in Azure for Students' free hours ("750 hours each of B1s, B2pts v2 (ARM-based), and B2ats v2 (AMD-based) burstable VMs", 12 months, renewable while a student [V]). A resize is not free, so it is not taken (§4.5) |
| How the work reaches the VM and git | **"Get it all done locally, tested and working then host it on the vm, then push to git."** Build and test locally; stage on the VM from a local copy, read-only with `DRY_RUN=1`; then one push. The armed install runs from a release tag on origin, because `quantt/deploy/install_vm.py` refuses a tag that is not there ("push it first") |
| The account structure (asked as "what would make most institutional sense") | Answered by the research in §6. Its institutional answer was a corporation with a Proprietary Trading Group account and OAuth. It needs a funded new account and a legal entity, so it is recorded for real money and not taken now |

## 2. The bar: how well the books trade on Alpaca today

The baseline comes from the books' own verify records, up to the 2026-11-24 close. `baseline.py` produces `baseline.csv`. Fills are measured against the primary exchange's official close (condition `M`), notional-weighted per session; + is worse for us.

| | core (`cef`) | C4 |
|---|---|---|
| sessions traded / sessions scored | 34 / 38 (from 2026-09-28) | 13 / 16 (from 2026-11-03) |
| orders filled in full, since `late_market` began | 251 of 251 (33 sessions from 2026-10-07) | 55 of 55 (13 sessions) |
| fill vs official close, per session | median +9.22bp, mean +7.08bp | median +9.74bp, mean +11.63bp |
| fill P&L / hold P&L at the official close | −$816.27 / +$763.70 | −$169.80 / +$1,127.17 |

- **The events book** has no fill-vs-close score yet: its verify marks at Alpaca's daily bar, not at the auction print. On 2026-11-24 it sent 205 orders and all 205 filled (`verify.json` reason).
- **Its twin is scored on the same basis as the CEF twins** (§4.6). Its side-by-side therefore starts its own fill-vs-close series, and the Alpaca events book's fills must be scored the same way for the comparison. That is part of the build (§5, B6).

**Each book's twin is measured on the same sessions as its Alpaca book, line by line:**
1. **Sessions.** Every session the Alpaca book trades, the twin trades. A twin session missed because the Gateway was logged out, or because the twin itself refused, counts against the twin.
2. **Orders filled in full.** At least Alpaca's rate.
3. **Fill against the official close.** A notional-weighted mean no worse than Alpaca's on the same sessions, shown with the paired difference and its standard error. Ten sessions is a short sample, so the team lead rules on the table, not on a threshold written here (H14).
4. **Reconciliation.** The ledger's shares sum to IBKR's positions on every symbol, every session.
5. **No double send** (rule 2): zero sessions with two sets of orders headed for one auction.
6. **Shorts.** Each short IBKR refuses is named. A short Alpaca would not lend but IBKR does counts in the twin's favour.

## 3. What MOC on IBKR paper is, and is not

- **IBKR paper takes MOC orders and fills them.** In September, on the four auctions whose executions were captured, it filled 41 of 42 MOC orders in full and one in part (`results/ops/IBKR_SECOND_BROKER_2026-10-19.md` §2.6, `scripts/ops/ibkr_paper_moc_fills.py`).
  - For three more auctions no execution was captured. That cannot be told apart from "unfilled", and the side-by-side measures it.
- **It does not run the auction.** Executions were stamped 15:59:30–15:59:59 ET, simulated "from the top of the book" (IBKR's paper guide [V]).
  - The signed median against the panel close was +8.1bp. That close was yfinance, not checked against NYSE's print.
  - So paper fills at either broker say nothing about our impact on a real closing auction. That is still decided at go-live (2026-11-25, "the closing auction").
- **What it does give:**
  - every book's orders are MOC, with no rule-3 exception;
  - the books run on the broker that real money would use, since IBKR Canada is the only broker open to a Canadian resident (`results/ops/BROKER_OPTIONS_CANADA_2026-10-28.md`);
  - MOC's own failure modes get exercised: the cut-offs, orders resting from the send until the auction (rule 2), and IBKR's short approvals.
- **No corporate-action gain.** IBKR paper does not process dividends or splits either [V].

## 4. Design

### 4.1 One account, a twin per book, the Alpaca runners untouched

- The three books keep deciding exactly as today: core and C4 at 22:00 with the morning backstop, events at 09:45 with a backup at 15:20.
- **A new twin runner** reads each book's saved `plan.json` for the session, read-only, and checks its `plan_sha`. Every book writes `targets` as whole shares per symbol, so the combined target per symbol is the sum of the three books' targets.
- **The twin sends to IBKR paper the difference between that combined target and IBKR's position, one MOC order a symbol.** It never touches an Alpaca account. It changes no Alpaca runner, so the Alpaca books stay byte-identical by construction; the release check proves that no file under `quantt/session/`, `quantt/sleeves/` or `quantt/collect/` changed.
- **A book whose Alpaca plan did not decide** (refused, or no plan) gets a twin target equal to what its ledger already holds, so it does not trade, as its Alpaca book does not.
  - The twin also re-runs the send-time gates that do not depend on Alpaca: plan freshness and status, the corporate-action gate in the book's mode, and the rule-2 guard at IBKR.
  - A session where only one side traded is counted under §2 line 1 and left out of the fill comparison.
- **Buying power.** At send, the combined opening notional is checked against IBKR's buying power with 3% headroom, the events book's rule. Below 1 the send refuses and records it, as a labelled difference. The scale-fit itself (`quantt/sleeves/fit.py`, in the 28 Nov release) ports once it is on main.
- **Sizing.** During the side-by-side the twin copies the Alpaca books' share targets, so the comparison is like for like.
  - The paper account's USD 1,000,000 default [V] is ample buying power for the three books' gross.
  - At cut-over, each book's equity for sizing becomes its ledger equity: starting capital plus ledger P&L, with no account-wide equity. That needs a `/spec-change` for each book's sizing input, and is recorded then.

### 4.2 The ledger

- `quantt/sleeves/ledger.py` is reused as it stands, with **ten slugs**: `cef`, `c4` and each of the events book's eight sleeves. The events `plan.json` lists each sleeve's targets in whole shares, after the book's gross scaling, and on the 2026-11-24 plan they sum exactly to the book's targets on all 222 symbols. The twin refuses, naming the symbol, if they ever do not.
- Netting and allocation follow its rules: the side opposite the net order is met in full inside the account, and the net side shares the fill in proportion to what each book wanted. A symbol with any fill books every share at the fills' average price. A symbol fully crossed inside the account books at the official close, the price an MOC fill aims at.
- Its invariant binds: the books' shares sum to IBKR's position on every symbol, or the twin refuses until a person repairs it.
- The events book's own eight-sleeve ledger stays on its Alpaca book during the side-by-side. The twin's ledger keeps the same eight sleeves at IBKR from the first session, so a per-sleeve P&L exists on both brokers.

### 4.3 Order timing

IBKR's MOC page [V]: NYSE, NYSE American and NYSE Arca take MOC until 15:50 ET, with no cancel or reduction after. Nasdaq takes it until 15:55, with no cancel or change after 15:50. Cboe BZX's own notice gives 15:55. NYSE's own page puts Arca's closing freeze at 15:59, which disagrees with IBKR; **the twin uses IBKR's earlier 15:50 for every venue.**

- **Send at 15:30 ET, with a backup slot at 15:40.** On a 13:00 early close they move to 12:30 and 12:40.
- The backup refuses if `STARTED` exists or if IBKR shows any open order on the account (rule 2).
- The send refuses after 15:45 (12:45 early), which leaves five minutes before the cut-off.
- **Verify runs at 17:45 ET**, after the Alpaca books' verifies at 17:30 and 17:35, so it can read their records for the comparison.

### 4.4 Rule 2 at IBKR

MOC orders rest at IBKR from the send until the auction. That is exactly the window in which a second run would double the book. The twin's guard is the one `results/ops/IBKR_SECOND_BROKER_2026-10-19.md` §2.3 specifies:
- `STARTED` is written before the first order;
- `reqAllOpenOrders` runs across client ids;
- an order map keyed on the twin's `orderRef`.

Either source showing a set already headed for the auction refuses. The resubmit-on-reconnect, master-client-id and precaution settings are Gateway settings. They are read back at install and on every probe where the API exposes them (§2.9 there; R7 and R11 below).

### 4.5 The Gateway

- **One paper username, so one IB Gateway and one weekly login.**
  - The Gateway runs as the native ARM64 build at a pinned version and sha256: stable 10.50.1h when read [V].
  - It runs under Xvfb, from a systemd unit, as `quantt`.
  - VNC listens on 127.0.0.1 only, for a manual login through `ssh -L`. No port opens.
  - **The login is automatic** (team lead, 2026-11-25: "Yes, store the paper login"). It uses a separate paper-only password, stored by the team lead in the vault, read into memory at boot, and typed into the Gateway by IBC 3.24.2, pinned. IBC is archived, but the most-used Gateway container image still bundles it. If the paper login asks for 2FA, the Gateway stays logged out until the team lead approves it, and the probe shows it.
- **IBKR's support stance and the weekly cycle.** IBKR says headless running is "not supported" [V]. The Gateway restarts itself daily and needs a person to log in after the Saturday-night reset [V]. The team lead logs in on Sunday evening, or on Monday before 15:30.
- **Memory.** The VM has 944 MB (measured 2026-11-25). IBKR's 4,000 MB is a heap ceiling, not resident use, and its own pages disagree on it [U]. One public measurement of a logged-in paper Gateway is 459–494 MB [U].
  - The Gateway's unit gets a `MemoryMax`, so a blow-up kills the Gateway and never an Alpaca runner.
  - **Free hosting only.** The VM's size, B2pts v2, is in Azure for Students' free hours [V]; B2pls_v2 (4 GiB, $26.86 a month at list price [V]) is not, so it is not taken.
  - The Gateway gets an explicit JVM heap, documented, and a swap file is added at bootstrap. The first week runs read-only and measures `MemoryPeak`.
  - **If it does not fit,** the fallback is a second free-size VM (B2ats v2, x64, 1 GiB) for the Gateway alone, with no public IP, reached from the trading VM. Its disk is not stated as free: an E4 is $2.64 a month from the student credit (`docs/RUNBOOK.md` §8.7). Whether the 750 free hours are counted per size or shared is not stated [U]. The Gateway's host and port are configuration, so the move needs no code.
- **The library.** `ib_async` is added to `requirements.txt`, so the VM's venv is rebuilt by `bootstrap.sh` at that release (`quantt/deploy/install_vm.py` refuses a venv built from another requirements file). `ib_insync` is never used (landmine 10).

### 4.6 Scoring and the record

- **Fills.** `reqExecutions` returns only the current day's executions [V], so verify runs the same day (§4.3). The same-day read is the record of fills, kept in the twin's state directory.
- **Each book's fills are scored against the official close**, exactly as the Alpaca books' TCA is: `quantt/session/score.py` and Alpaca's closing-auction prints, which stay on Alpaca's market data.
- **The account record.** IBKR's net liquidation value is read at verify as the account's own record, and the books' ledger values must sum to it within a stated tolerance.
- **Currency.** The old account was CAD-based [S]; the probe reads its base currency. The ledger works in USD from fills and closing prints, so it does not depend on the base currency.
- **The P&L of record.** During the side-by-side, each book's Alpaca account stays its record. After cut-over, a book's record is its ledger, cross-checked against the account. That follows from one shared account, and the cut-over records it.

### 4.7 What stays on Alpaca

- Market data: the calendar, the closing-auction prints, distributions, corporate-action announcements and the daily bars. These are read with the existing Alpaca keys, and none of them trades.
- The Alpaca paper accounts keep trading until each book's cut-over.

## 5. Build contract

Items B1–B8 are built on a branch from `main` and reviewed by an independent `quant-reviewer`. They ship at a weekend release after a release check. Nothing in B1–B8 opens a socket at import (`pytest.ini`, `ops/netguard.py`), and nothing connects to IBKR in tests.

| # | build | notes |
|---|---|---|
| B1 | `quantt/broker/ibkr.py`: the adapter, in `AlpacaClient`'s style | Connects to the paper port only; a live port is a test failure. Host, port, client id and the expected account id are required environment variables with no defaults. The account id is compared at run time and never printed. Reads: account summary (net liquidation, buying power, base currency), positions, all-client open orders, today's executions with commission reports. Writes: MOC `place` (`orderType="MOC"`, `tif="DAY"`, `orderRef` = the twin's order id) and `cancel`. Ported from `pre-clean-slate:_archive/src/deploy/broker/ibkr.py` as October §3 lists (keep the order and guard pieces and their incident docstrings; drop the `ib_insync` fallback, `IBKRConfig.from_env`'s defaults, the shadow ledger and `arm()`). Tests run on a stub `ib_async` module |
| B2 | `quantt/twin/`: `combine` (plans → combined targets → MOC orders), `send`, `verify`, `compare`, `probe`; `python3 -m quantt.twin {probe,send,verify,compare}` | §4.1–4.4 and §4.6. `DRY_RUN=1` always wins. The state directory is its own (`quantt_state/twin/`). `probe` is read-only, and a test proves it cannot place an order |
| B3 | Ledger reuse | `quantt/sleeves/ledger.py` imported as is; if it must change, the events book's ledger output is proved byte-identical |
| B4 | The rule-2 guard at IBKR | `STARTED`, `reqAllOpenOrders`, the `orderRef` map; the backup slot refuses on any of them; tests with real incident shapes (the 2026-07-31 stack, October §3) |
| B5 | Deploy | `quantt-ibgw.service` (Xvfb, Gateway, VNC on localhost, `MemoryMax`), `quantt-twin-send` (15:30 and 15:40; 12:30 and 12:40 on early closes), `quantt-twin-verify` (17:45), all `DRY_RUN=1` when installed. Installer checks in the shape of `docs/RUNBOOK.md` §8.3. The Gateway's daily auto-restart is set outside 15:20–16:00, 17:30–18:00 and the 22:00 decides |
| B6 | The comparison | Per book and session: orders, filled in full, fill vs official close (the twin, and the Alpaca book on the same basis, events included), residual, refused shorts. `compare` prints the §2 table over the side-by-side so far. Aggregates only in any committed file |
| B7 | orient and the daily page | An IBKR TWIN section: Gateway logged in or not (read-only probe), the last twin session's verdict, the side-by-side tally per book. No alert leaves the VM ("No phone") |
| B9 | The switch: a per-book setting so the decide reads the twin ledger for holdings and equity, the book's Alpaca send and verify stand down cleanly, and its daily official record comes from the twin ledger | Changes `quantt/session`, `quantt/sleeves` and `quantt/collect`. With the setting absent, every book is proved byte-identical (`/spec-change`). It ships dormant, and the team lead switches each book |
| B10 | IBKR quotes and bars for the shadow books and idea tests ("we can trade/interacti with ibrk quotes to run shadow books / test ideas") | The trading user, which owns the Gateway, writes a read-only feed directory for `quantt-shadow` (the C4 shadow-feed pattern, `docs/RUNBOOK.md` §8.15). The shadow user never reaches the Gateway's API port, which can send orders. Without paid subscriptions the paper account gets delayed data [V]; the probe records what it actually gets |
| B8 | Documents | `docs/RUNNER.md` "The IBKR twin (as built)"; `docs/RUNBOOK.md` §9 (Gateway install, the weekly login through `ssh -L`, the settings list, the flatten and cancel tools); `CLAUDE.md` rule 3's exception narrowed to the Alpaca paper accounts, as a diff for the team lead |

## 6. The account structure: what was found

The team lead asked what would make "most institutional sense". Sources were read on 2026-11-25 (`docs/REFERENCES.md` §12ib).

- **IBKR's institutional answer is a Proprietary Trading Group account with Separate Trading Limit sub-accounts.**
  - IBKR's description: "Configure sub-accounts and limits for different traders and strategies" [V].
  - In IB Canada's account guide: "At trade initiation, each sub account is margined separately. For maintenance and liquidation purposes, all accounts are consolidated" [V].
  - The Web API's OAuth 1.0a lists Proprietary Trading Group accounts among its supported types, and names "organizations looking to trade their own capital" as first-party examples [V]. OAuth would remove the Gateway and the weekly login.
  - It needs a legal entity, a funded account, and IBKR's answers on three points [U]: whether its paper account holds paper sub-accounts, whether OAuth works on paper, and whether either is offered through IB Canada.
  - Securities counsel would also need to say whether a corporation trading only its own money must register under NI 31-103.
- **Individual accounts:** "OAuth 2.0 is not available to Individual account structures" [V], so an individual account needs the Gateway.
- **Recorded for real money, not taken now.** The team lead cannot fund a new account. The structure goes into the go-live proposal's broker section.

## 7. Steps

| # | who | step | needs |
|---|---|---|---|
| 1 | agent | B1–B8 on a branch; independent review; release check | this note |
| 2 | team lead | Read the paper username of the existing account in Client Portal (Settings → Paper Trading Account). Put it, the paper account id (for the run-time identity check) and nothing else in the vault, under the names the B8 runbook gives. The values never go in a chat or a file | — |
| 3 | agent, with the team lead's `!` for sudo | VM staging, before any push: Xvfb, a swap file, the Gateway at its pinned sha256, and the twin run from a staging copy of the local tree with `DRY_RUN=1` forced (it cannot arm from staging) | 1 |
| 4 | team lead | First login: `ssh -L` to the Gateway's VNC, type the paper username's password, approve any 2FA. Set the API settings of §4.4; they are read back and screenshotted for the record | 3 |
| 5 | agent | Read-only probe: account id check, base currency, net liquidation, positions and open orders left from September (34 flatten orders were left unacknowledged on 2026-09-28), one quote snapshot to see whether paper's data is live or delayed. Committed as a redacted aggregate | 4 |
| 6 | team lead | If September positions remain, flatten them by MOC with the human-run flatten tool (rule 1: the order list shown, then a go). IBKR's reset leaves positions open [V], so it is not a substitute | 5 |
| 7 | agent | Weekend dry check: `quantt.twin send --dry` on Friday 27 Nov's saved plans against IBKR's positions (the order list and gates, nothing sent), and the probe. `MemoryPeak` and the automatic login are measured from then on | 5, 6 |
| 8 | agent | One push: main and the release tag. Then the install from the tag (the installer refuses a tag not on origin). If step 7 says the Gateway does not fit, the fallback free VM is set up first, on the team lead's go | 7 |
| 9 | team lead | Arm the twin: its first concrete order list shown, then an explicit go (rule 1) | 8 |
| 10 | agent | The side-by-side session(s); `compare` after each; the §2 table to the team lead | 9 |
| 11 | team lead | Cut over each book that passes: its decide reads the twin ledger for holdings and equity (a separate build, B9, shipped dormant), its Alpaca send disarmed, its sizing moved to its ledger by `/spec-change`, and its Alpaca account flattened on a go | 10 |

**Not before step 11:** peer session 2027-3f's read-only forward record of would-be MOC size reads the core's orders from Alpaca. It keeps working through the side-by-side and needs an IBKR read path at cut-over. 3f has asked to be told the date.

## 8. Risks and open questions

These carry over from October §5 where they still apply (R1 uptime of a manually logged-in Gateway, R3 Xvfb outside IBKR's support, R5–R7, R11, R12, R15), with these changes:

| # | risk or question | what settles it |
|---|---|---|
| N1 | **Uptime.** A missed Sunday login, a Gateway crash or a VM reboot stops the twin until the team lead logs in. With "No phone", nobody is alerted. Alpaca has no such failure. This is the line of §2 most likely to fail | Step 7 counts it. During the side-by-side, only the twin misses; the Alpaca book still trades |
| N2 | **Memory on 944 MB.** The Gateway beside the runners could push the VM into swap at 15:30–15:58 | `MemoryMax` on the Gateway's unit; the measurement in step 7; the ruling in step 8 |
| N3 | **The September account.** Leftover positions, open orders, a CAD base and an unknown cash balance | The step 5 probe, before any order |
| N4 | **Market data.** Without live subscriptions, paper gets "delayed data, as available" [V]. Whether paper's MOC fills need live data is not documented [U]. Live subscriptions need USD 500 of equity in the live account [V], against "we cant pay" | The step 5 quote snapshot; then the fills of step 10 |
| N5 | **Netting changes what the twin sends.** Netting one symbol across the three books means the twin's orders differ from the three Alpaca books' orders. The per-book fill score is therefore measured on the ledger's bookings, and crossed shares book at the close. The comparison labels crossed shares separately so they cannot flatter the twin | B6 |
| N6 | **Consolidated risk in one account.** A loss in one book uses margin all three share. At USD 1,000,000 of paper equity against books sized at $100k each this does not bind [V paper equity]; it is a go-live question | The go-live proposal |
| N8 | **Found while building, and older than this work: the Alpaca units' logs.** Their `StandardOutput=append:` files sit in directories `quantt` owns (`quantt/deploy/templates/systemd/`). systemd opens those files as root, so a symlink planted there would have root append to its target. The twin's units log to a root-owned `/var/log/quantt-twin` instead. The Alpaca units are unchanged here | A separate fix for the team lead's ruling; the twin does not depend on it |
| N7 | **Self-trade across books.** All three books are one owner. Netting before routing means the account never sends both sides of a symbol. No IBKR page on self-trade prevention for stocks within an account was found [U] | B2's netting; a test that no session sends both sides of one symbol |
