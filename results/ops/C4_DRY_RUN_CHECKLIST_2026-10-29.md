# C4 dry run on its own Alpaca paper account: the team lead's checklist (2026-10-29)

> **For the team lead. Nothing here has been run on the VM, and nothing is armed.**
> C4 (CEF trial 52) was fast-tracked on 2026-10-28/29 with every gate kept. Branch
> `c4-integrate` carries its whole path, dark: the frozen spec, the data path, the
> per-sleeve runner, `BOOKS["c4"]`, its book json and its installer units. The
> core's session and installer are proved byte-identical (below). Release is the
> team lead's. Zero trials; the CEF counter stays 52.

Reproducer for every claim on this page (offline, no network, no keys):

```bash
python3 -m pytest quantt/session/tests/test_c4_book.py quantt/deploy/tests/test_install_vm_books.py \
  quantt/session/tests/test_panels_noop.py quantt/collect/tests/test_collect_books.py \
  scripts/cef/tests/test_c4_paper_benchmark.py quantt/tests/test_alpaca_probe.py
```

The VM install wrapper used below is `docs/RUNBOOK.md` §8.3's:

```bash
qi() { sudo env PYTHONPATH=/home/quantt/prod/quantt-alpaca \
         /home/quantt/venv/bin/python -B -P -m quantt.deploy.install_vm "$@"; }
```

## What is proved before any of this

| claim | how | status |
|---|---|---|
| The core's session is cee16ad's (prod, release-20261029-3) with the corporate-action block absent, and 35b429f's (origin/main) with the released book json as is: exit, plan.json, plan_sha, orders, targets, refusals, run record, nav_gate.csv, send.json and what was sent | `quantt/session/tests/test_panels_noop.py`, synthetic panel (never skips) and the laptop's real panel; pins made in `git archive` trees of 5e627ff (= cee16ad's code) and 35b429f | [V] 2026-10-29 |
| The core's install is cee16ad's installer's: the whole dry run (every check, step and rendered unit) and every `--apply` file, byte for byte | `quantt/deploy/tests/test_install_vm_books.py`, cee16ad's `install_vm.py` read from git beside this one | [V] 2026-10-29 |
| A C4 session in DRY decides from `data/cef_c4/` only | `test_c4_book.py`: a fixture panel; every parquet opened is under `data/cef_c4/`, `data/cef/` does not exist; 65 orders on the 74; the send at 15:52 sends nothing | [V] 2026-10-29 |
| The same on the real seed | ad hoc, a scratch copy of step 2's seed (families history to 2026-10-09), a fake broker: as-of 2026-10-09, PLANNED, 17 orders, $116,390 gross, no refusal, nothing sent. Modelled; a statement about the code, not the market | [V] 2026-10-29, not committed |

## The steps

**0. Release and the core first.** Tag a release containing `c4-integrate` after
`/release-check`, and install the CORE at that tag on the VM as for any release
(`docs/RUNBOOK.md` §8.6). Both books run from the one prod clone at one tag:
`--book c4` never checks the clone out, and refuses unless the clone is already
at the tag.

**1. Create the vault secrets for C4's keys (the team lead's credentials; no agent
touches them).** In the Key Vault the core uses, create, as for the core
(`docs/RUNBOOK.md` §8.1):

- `alpaca-c4-key-id`: the key ID of the spare connector paper account (C4's
  account, team lead 2026-10-26);
- `alpaca-c4-secret-key`: its secret.

The VM identity's "Key Vault Secrets User" role is assigned at vault scope
(§8.1), so it reads the new secrets with no new assignment. For step 3 on the
laptop, also add `ALPACA_C4_KEY_ID` and `ALPACA_C4_SECRET_KEY` to `config/.env`;
`python3 -m quantt.broker.alpaca_probe --check-keys --book c4` prints SET or NOT
SET, never a value.

**2. Seed `data/cef_c4/` with the IGR ruling (laptop, dev tree at the release
tag, read-only on `data/`).**

```bash
python3 scripts/cef/data_books.py seed-c4 --from data/cef_families --out ~/c4_seed \
  --bar-rulings results/cef/c4/c4_seed_rulings_2026-10-29.json
scp -r ~/c4_seed quantt-vm:          # the three files: cef_prices.parquet, cef_nav.parquet, seed_manifest.json
```

Expect exit 0, and `treated_closes` in `seed_manifest.json` = IGR 2026-07-29,
08-04, 08-07, 08-11 (`rebase`, factor 3) and nothing else. Rehearsed on
2026-10-29 into a scratch directory: exactly those four; prices 401,688 rows and
NAV 325,588 rows to 2026-10-09; sha256 `3fb68e38…` and `c7073db8…`; ruling
`ba09b7c4…` [V, laptop `data/cef_families` as of 2026-10-29]. The installer
refuses a seed whose manifest does not name the tag's ruling and frozen universe
by sha256, or whose files do not match it. The seed applies the ruling to the
four closes (the guard's rebase), not to the ruling's logged open, high, low and
volume cells; the first fetch re-fetches those dates anyway (step 5).

**3. Re-derive the cap against the shared account's margin** (the spec's
`_max_gross_stress_note`, ruling 3; the agent lab shares the account since
2026-10-28):

```bash
python3 -m quantt.broker.alpaca_probe --book c4      # read-only; writes results/ops/alpaca_probe/<date>_c4.json
python3 scripts/cef/c4_paper_benchmark.py recap \
  --probe results/ops/alpaca_probe/<date>_c4.json --mark-sensitivity <the lab book's>
```

NLV is the account's equity, M_other its maintenance margin (the lab's, while C4
holds nothing; the command refuses a snapshot holding any C4 name), and w5 and m
the committed derivation's. The mark sensitivity is the team lead's input; there
is no default. Exit 0: the rule still gives 1.90. Exit 1: a new spec id
(`/spec-change`) and a release before C4 arms. The read is true on its date only:
run it again on the day of the arming go (step 6).

**4. Install C4 UNARMED (DRY_RUN=1) on the VM**, on a weekday outside
15:30-16:00 ET (the installer refuses inside it):

```bash
qi --tag <T> --vault <V> --book c4 --eod-from <YYYY-MM-DD> --seed-from /home/<admin>/c4_seed          # dry run: read every unit
qi --tag <T> --vault <V> --book c4 --eod-from <YYYY-MM-DD> --seed-from /home/<admin>/c4_seed --apply --enable
sudo systemctl list-timers 'quantt-*'                 # both books' timers
```

Never `--armed` here. `--eod-from` is the date C4's paper account was first
funded: REQUIRED, no default, and only the team lead knows it. The collector
dates the official end-of-day P&L from it (`QUANTT_EOD_FROM` in
`quantt-c4-collect.service`). What gets installed: seven `quantt-c4-*` units (the
core's jobs with `--book c4`, the same times), state in
`/home/quantt/quantt_state/c4`, keys in `/run/quantt-c4/alpaca.env`, panels in
`data/cef_c4/`. None of the core's units is touched.

**5. Five sessions of DRY run.** Read, each day, `/home/quantt/quantt_state/c4/`:

- `data.log`: the collector's day. The first night's `fetch_daily --data-book c4`
  exits 0, or 6 (`SPIKE-REVERT`): an unruled split-like bar in the fetched window.
  If IGR's four bars come back from Yahoo, the standing rule needs a new ruling.
  Until then gate 5 refuses every C4 session.
- **After the first fetch, compare the replaced rows with the seed.** The fetch
  replaces every seeded row in its six-month window (from about 2026-04-29) with
  Yahoo's. If Yahoo's basis differs from the families build's, the price steps at
  the window's start. Look hardest at IGR (1:3 reverse split, 2026-09-08) and the
  split-ruled BTO, TYG, NXG and EMO. The spike guard catches a spike that
  reverts, not a step. Any step: stop, and rule on it before arming.
  UNMEASURED: this build had no network.
- `logs/session.out.log` and `<D>/plan.json`: the evening decide is PLANNED
  (exit 6) on C4's 74, and the 15:52 send is DRY (exit 10). Alpaca shows no
  orders on the account. Expected on every decide:
  - `drawdown` UNMEASURED: the spec names no halve/kill levels;
  - `missing_nav` naming any late NAV, held at the final check;
  - `corporate_actions` CLEAR, or a named refusal.
- `verify.log`: one line per trading day.
- Measure, for the arming go: the 74-name fetch time against the 25-minute cap;
  memory on the 1 GiB VM when both books run at :00/:30 and :10/:40; and how
  often NAVs arrive late. All UNMEASURED today (deploy plan §5).

**6. The arming go (the team lead's).**

- Re-run step 3 that day: it must give 1.90, or the new spec is released.
- Decide C4's halve/kill levels. The 2026-10-29 ruling left them to the book
  json; the runner reads levels only from the spec, which names none (H14). Open.
- Then `qi --tag <T> --vault <V> --book c4 --eod-from <YYYY-MM-DD> --apply --armed`.
- Then, as the service user, `touch /home/quantt/quantt_state/c4/AUTO_ARMED`.
- CLAUDE.md order rule 1 holds: the first armed session's order list is shown,
  and the go given on it.

## Running both books

- **Disable C4:** `sudo systemctl disable --now quantt-c4-session.timer
  quantt-c4-verify.timer quantt-c4-collect.timer`. To halt C4 alone, write
  `ops/HALT_c4.md` in the prod clone. `ops/HALT.md` halts both books.
- **A new release:** the core's install refuses to move the shared clone while a
  C4 timer is enabled or running, or a C4 job is busy. Disable C4's timers,
  install the core at the new tag, then re-run step 4's `--apply --enable` at the
  same tag.
- **Not built yet:**
  - `ops.prod_state` and `ops.orient` report the core's units only;
  - the probe reads C4 only when named (`--book c4`);
  - how the agent lab's sleeves net against C4's targets in the shared account is
    decided when the lab book is built (`docs/SYSTEM.md` §5, 2026-10-28).
