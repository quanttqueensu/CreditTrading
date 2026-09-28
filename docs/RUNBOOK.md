# Runbook: the Alpaca prod on this laptop

**What this covers:** how to release, install, arm, disarm, read a day's verdict,
and respond to a FAIL, for the CEF book on Alpaca paper. It also covers keeping
the laptop awake and moving to a VM later. The design is `docs/RUNNER.md`; the plan
is `docs/ROADMAP.md` phases 4 to 6. This file holds no figures about the book:
`python3 -m ops.orient` measures those.

**Who does what.** **TL** = the team lead. **A** = an agent. Anything that
needs `sudo`, a credential or a broker order is a TL action. An agent in a chat
transmits nothing without the TL's go on a concrete order list (`CLAUDE.md`
order-path rule 1). After the first go, the scheduled runner trades on its own,
behind the gates (`docs/RUNNER.md`).

## What prod is

Prod runs on this laptop until a VM exists (TL, 2026-09-28). It holds this
repository at a release tag and nothing else (`docs/ROADMAP.md` phase 6).

| thing | where | made by |
|---|---|---|
| code | `~/prod/quantt-alpaca`: a `git clone` of `origin`, **detached at the tag** | `install_prod` |
| price/NAV panels | `~/prod/quantt-alpaca/data/cef/cef_prices.parquet`, `cef_nav.parquet`. Copied once from the dev tree, then prod's own. | `install_prod` seeds them; `fetch_daily` appends to them |
| runtime records (`QUANTT_STATE_DIR`) | `~/quantt_state/cef/`: `<date>/STARTED`, `verify.log`, `AUTO_ARMED` | `quantt.session` (and the TL for `AUTO_ARMED`) |
| job logs | `~/quantt_state/cef/logs/{session,verify}.{out,err}.log` | launchd |
| schedule | `~/Library/LaunchAgents/com.quantt.alpaca.cef.session.plist` (08:30 and 12:00 ET, Mon–Fri) and `...cef.verify.plist` (17:30 ET, Mon–Fri) | `install_prod`, rendered from the tag's templates |
| Alpaca keys (`QUANTT_ENV_FILE`) | a file **outside** the prod clone, mode 600 | TL only. `install_prod` checks it exists and is private, and never reads it. |

**Never touch** the retired IBKR prod: `~/prod/QUANTT` and the old
`~/Library/LaunchAgents/com.quantt.*.plist` files that do not contain `alpaca`.
Retiring them is `docs/ROADMAP.md` 6.6 (TL decides, A runs). The installer
refuses a layout that overlaps `~/prod/QUANTT`, and it writes only the two
`com.quantt.alpaca.*` files.

## 0. One-time preconditions (TL)

1. **Timezone.** launchd schedules run on local wall-clock time, and the plists
   are written in US/Eastern. **Measured 2026-09-28:** this Mac is set to
   `America/Toronto`, not `America/New_York`. The installer refuses that unless
   you choose one of these:
   - set the system zone: `sudo systemsetup -settimezone America/New_York`
     (then `readlink /etc/localtime` should end in `America/New_York`), **or**
   - pass `--accept-timezone America/Toronto` to the installer. It is honoured
     only if Toronto's UTC offset equals New York's at every hour of the next
     two years, checked against this machine's tz database at install time.
2. **Key file.** Put the Alpaca paper keys (`ALPACA_CEF_KEY_ID`,
   `ALPACA_CEF_SECRET_KEY`) in a file outside the prod clone and outside
   `~/Desktop`, `~/Documents` and `~/Downloads`, then run `chmod 600 <file>`.
   Those three folders are macOS privacy-protected. The 2026-07-31 IBKR job
   died under launchd with `getcwd: Operation not permitted` (exit 126) when it
   touched one (`ops/halt.py` docstring). This dev repo is under `~/Downloads`,
   so its `config/.env` is at risk. Whether this interpreter can read there
   under launchd **has not been measured**. The installer warns rather than
   refuses, and step 3.2 below proves it either way. A suggested location is
   `~/.config/quantt/alpaca.env`. Agents never read, copy or move this file.
3. **Python.** The jobs run the interpreter the installer ran under (on
   2026-09-28 that was `/opt/anaconda3/bin/python3`, Python 3.13.5), with
   `requirements.txt` installed in it. Step 2.3 (the test suite in the prod
   clone) proves the dependencies are there.
4. **Awake at 08:30.** See section 7.

## 1. Release (A, with TL approval to push)

A release is an annotated tag on a commit whose suite is green. The repo's tag
names follow `vYYYY.MM.DD.N`.

```bash
cd "<dev repo>"
python3 -m pytest                    # green; never quote a count
python3 -m ops.doc_audit --check
git tag -a v2026.09.29.1 -m "Alpaca runner: <one line>"
git push origin v2026.09.29.1        # the installer refuses a tag that is not on origin
```

Which branch the tag sits on (`alpaca-runner` or `main` after a merge) is the
TL's call. A tag is never moved after release. The installer refuses when
the dev repo's tag and origin's tag name different commits.

## 2. Install or update (A runs, TL approves `--load`)

```bash
cd "<dev repo>"
# 2.1 dry run: every check, then the exact steps and both rendered plists. Writes nothing.
python3 -m quantt.deploy.install_prod --tag v2026.09.29.1 --env-file ~/.config/quantt/alpaca.env
#       (add --accept-timezone America/Toronto if section 0.1 chose that)

# 2.2 apply: clone/fetch, checkout the tag detached, seed panels if absent,
#     make the state dir, write the plists with DRY_RUN=1. Does NOT load them.
python3 -m quantt.deploy.install_prod --tag v2026.09.29.1 --env-file ~/.config/quantt/alpaca.env --apply
```

2.3 **Prove the prod clone before scheduling it** (`docs/ROADMAP.md` 6.3). Use
the same interpreter:

```bash
cd ~/prod/quantt-alpaca
python3 -m pytest
python3 -m ops.doc_audit --check
python3 -m ops.orient
```

All three must be clean before 2.4.

2.4 **Load the jobs** (TL approves): re-run with `--apply --load`. This runs
`launchctl bootstrap gui/<uid>` for both plists, and boots out first any job
that is already loaded. Check both are loaded:

```bash
launchctl print gui/$(id -u)/com.quantt.alpaca.cef.session | grep -E 'state|path'
launchctl print gui/$(id -u)/com.quantt.alpaca.cef.verify  | grep -E 'state|path'
```

**The installer refuses on any of these:**
- a timezone other than New York (section 0.1)
- a missing, relative or in-prod key file
- a tag that is not on origin, that moved, or that lacks `quantt/session/__main__.py`, the templates or the sleeve
- a template at the tag whose schedule, command or environment differs from the contract
- a prod clone with any local modification or untracked file
- a job that is loaded in launchd when its plist would change but `--load` was not given (launchd would keep running the old definition)

Each refusal names the problem. Fix the cause. Do not work around it.

**Updating** to a new release is the same: tag, dry run, `--apply --load`.
Prod's panels are never overwritten, because they hold rows the dev tree may
not have. **Rolling back** is an install of the previous tag.

## 3. First sessions: shadow, then arm

3.1 **Shadow (DRY_RUN=1).** After 2.4 the jobs run on schedule and send
nothing. `DRY_RUN` is `1` in both plists, and the runner transmits only when it
is exactly `0` (`docs/RUNNER.md` gate 1).

3.2 **Prove the launchd environment now, not at 08:30.** With DRY_RUN=1 still in
the plist:

```bash
launchctl kickstart gui/$(id -u)/com.quantt.alpaca.cef.session
tail -n 50 ~/quantt_state/cef/logs/session.err.log ~/quantt_state/cef/logs/session.out.log
```

This runs one dry session immediately: the data refresh, the decision and the
gates. Nothing is sent. If the key file cannot be read (section 0.2), a module
is missing, or the working directory is refused, it shows here.

3.3 **The first armed session (Tue 2026-09-29, `docs/RUNNER.md`).** This session
is interactive. The TL runs it by hand from the prod clone, with the same
environment the plist sets:

```bash
cd ~/prod/quantt-alpaca
export QUANTT_STATE_DIR=~/quantt_state/cef QUANTT_ENV_FILE=~/.config/quantt/alpaca.env
DRY_RUN=1 python3 -m quantt.session run --book cef     # shows the order list and its plan_sha
#   the TL reads the order list and says go, or does not
DRY_RUN=0 python3 -m quantt.session run --book cef --approve <plan_sha>
```

`--approve` sends only if the freshly recomputed order list hashes to the
approved `plan_sha` (gate 2). The exact flags and output belong to
`quantt/session`. Confirm them against its `--help` at the release tag before
the session.

3.4 **Arm the schedule** after the TL's first go:

```bash
touch ~/quantt_state/cef/AUTO_ARMED                    # TL: docs/RUNNER.md gate 2
cd "<dev repo>"
python3 -m quantt.deploy.install_prod --tag <same tag> --env-file ~/.config/quantt/alpaca.env --armed --apply --load
```

A scheduled transmit needs **both** `DRY_RUN=0` in the plist **and**
`AUTO_ARMED`. It also still needs every other gate to pass: halt, clock, data,
no set already headed for the auction, shortability, exposure and sanity.

## 4. Disarm or halt

Fastest first. Each step stops the next scheduled session. **None of them
cancels an order already at Alpaca.**

1. **Halt file** (seconds; survives reboots). The runner reads
   `ops.halt.read_halt("cef")` **from the prod clone**, so write the halt there.
   A halt written in the dev tree does not stop prod.
   ```bash
   cd ~/prod/quantt-alpaca
   python3 -c "from ops.halt import write_halt; write_halt('why', source='runbook', book='cef')"   # this book
   python3 -c "from ops.halt import write_halt; write_halt('why', source='runbook')"              # every book
   ```
   `write_halt` also tries a macOS banner, speech and email, but only the file
   stops trading. Clear the halt once the cause is fixed:
   `python3 -c "from ops.halt import clear_halt; clear_halt('what was fixed', book='cef')"`.
2. **Remove `AUTO_ARMED`**: `rm ~/quantt_state/cef/AUTO_ARMED`. Scheduled runs
   then fail gate 2.
3. **DRY_RUN=1**: re-install without `--armed`, with `--apply --load`. The
   installer refuses to change a loaded job's plist without `--load`, so the
   file and launchd cannot disagree.
4. **Unload the jobs**: `launchctl bootout gui/$(id -u)/com.quantt.alpaca.cef.session`
   (and `.verify`). Nothing runs at all, including verification.

**Cancelling an order already sent** is an order-path action: the TL only.
NYSE accepts no MOC cancel after 15:50 ET (`CLAUDE.md` order-path rule 3).

Note: a halt file and the `ops/halts/` archive are files inside the prod clone.
They are not gitignored, so the installer sees them as local modifications and
refuses to update while they exist. See the open question at the end of this file.

## 5. Check a day's verdict

```bash
tail -n 5 ~/quantt_state/cef/verify.log        # one line per trading day: PASS or FAIL + reason
ls ~/quantt_state/cef/$(date +%Y-%m-%d)/       # STARTED exists only if orders were sent
tail -n 50 ~/quantt_state/cef/logs/session.err.log ~/quantt_state/cef/logs/verify.err.log
launchctl print gui/$(id -u)/com.quantt.alpaca.cef.session | grep -E 'last exit|runs'
python3 -m quantt.broker.alpaca_probe --book cef   # read-only account snapshot (run from the dev repo)
```

**No line for a trading day counts as a FAIL.** Silence never counts as success
(`docs/ROADMAP.md` 4.7).

## 6. On FAIL

1. **If orders may be at risk, or the cause is unknown, halt first** (section
   4.1). A halt costs one session. An unexplained second set in the auction
   doubles the book (`CLAUDE.md` order-path rule 2).
2. Read the verdict line and the four logs (section 5). Take the account's truth from
   the broker, never a local file: run the read-only probe and compare it with
   the day's `STARTED` record.
3. **Never re-run `run` armed on the same day** to "retry". Never delete a
   `STARTED` file. Gate 6 exists because Alpaca does not dedupe
   `client_order_id` after an order closes.
4. Fix the cause in the dev repo, with a test that fails against the old
   behaviour. Then release a new tag and install it (sections 1–2). Never
   hand-edit prod.
5. Clear the halt with a note of what was fixed.

## 7. Keeping the laptop awake

launchd runs a missed calendar job **once on wake**, and coalesces several
missed runs into one (`man launchd.plist`, StartCalendarInterval). A laptop
asleep at 08:30 therefore runs the session when it wakes. The runner's clock
gate (15:45 ET) stops a late wake from trading. A laptop that stays asleep all
day trades nothing, and its verify line is missing, which counts as a FAIL.

**Measured 2026-09-28 (`pmset -g`, `pmset -g sched`):** `SleepDisabled 1`;
`sleep 0 (sleep prevented by caffeinate, powerd)`; no scheduled or repeating
power events. Where the `caffeinate` assertion comes from was not traced. It may
be one of the retired `com.quantt.*` jobs, whose names include `awake` (name
listed, contents not read). If so, retiring them (6.6) removes it. `SleepDisabled`
is a separate setting.

A backstop wake before the morning session is a TL command that needs sudo.
It was **not run** by any agent:

```bash
sudo pmset repeat wakeorpoweron MTWRF 08:25:00
pmset -g sched                                   # verify
```

`pmset` allows **one** repeating power-on/wake event and one power-off/sleep
event (`man pmset`), so this replaces any existing repeating wake. Undo with
`sudo pmset repeat cancel`. The times are local time, so section 0.1 applies.

Unmeasured, and the TL's call: behaviour with the lid closed, on battery or
without network. Keep the laptop on power and online on trading days.

## 8. Moving to the VM later

`docs/ROADMAP.md` phase 6 is the plan. What changes from this laptop:

- **Secrets:** use the provider's secrets manager, not a copied file
  (`ROADMAP` 6.2). The runner only needs `QUANTT_ENV_FILE` to point at a
  dotenv-format file with mode 600 at run time. How the secrets manager
  produces that file is a 6.2 decision.
- **Schedule:** use the VM's scheduler instead of launchd, with the same
  commands (`python3 -m quantt.session run|verify --book cef`), the same
  environment variables and the same times in America/New_York. Set the VM's
  zone to America/New_York, or set the scheduler's own timezone explicitly.
  This installer is macOS/launchd-specific. A VM installer, whether systemd
  timers or cron, is a new piece of `quantt/deploy/` with its own tests, not an
  edit to this one.
- **Cut-over, so there is never two armed schedulers:** halt the laptop book
  (section 4.1), unload its jobs (section 4.4), and remove its `AUTO_ARMED`.
  Then install the VM at the same tag with DRY_RUN=1, shadow it, and arm it.
  Two machines armed for the same account would each pass gate 6 on their own
  state dir. Only the Alpaca-side check (orders with the day's
  `client_order_id` prefix) would stand between them and a doubled book.
- **Panels:** seed the VM's `data/cef/` from the laptop **prod** panels, the
  newest copy and the one prod has been trading on. Record where they came from.

## Open questions (for the TL)

1. **Timezone:** set this Mac to `America/New_York`, or accept `America/Toronto`
   through the installer's equivalence check? (Section 0.1.)
2. **Halt files inside the prod clone** (`ops/HALT*.md`, `ops/halts/`,
   `ops/heartbeat.json`) are not gitignored. A halt, or any halt ever cleared,
   leaves untracked files that make the installer refuse every later update
   until they are removed by hand. One option is adding `/ops/HALT*.md`,
   `/ops/halts/` and `/ops/heartbeat.json` to `.gitignore`. That has a
   consequence of its own: an update could then proceed while a halt stands.
3. **Key file location** (section 0.2): keep `config/.env` in `~/Downloads`
   (unproven under launchd) or move it to `~/.config/quantt/`?
