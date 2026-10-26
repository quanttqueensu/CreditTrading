# The team: who works on what, and how work reaches prod

**This file owns** the lanes, who keeps which part of the repository, and the path
from a branch to `main` to prod. The standing decision behind it is
`docs/SYSTEM.md` §5, "Team lead, 2026-10-22: the pod". New here: start with
`docs/ONBOARDING.md`. What is true right now: `python3 -m ops.orient`, never this file.

The pod is the team lead (the PM) and three analysts, each on a branch named for
them: `simon` (PM), `ryan` (MACRO, fixed income), `james` (equities and ETFs) and
`lucy` (dashboard and data). **This repository is public**: first names appear only
as those branch names (team lead, 2026-10-26); nothing else here names a person.
Each analyst is a collaborator on this repository with Write access (§6).

---

## 1. The lanes

| lane | trial counter(s) | keeps | the queue it works from |
|---|---|---|---|
| **PM** (team lead) | CEF, EVENTS, GAMMA | The core CEF book, its execution and costs (TC), everything in §2, prod, release tags, approving pre-registrations, `docs/SYSTEM.md` §5, `docs/ROADMAP.md`. The corporate-event work (`scripts/events/`, `results/events/`), including the special-situations slate and its ETF hedge overlay, and the options test (`scripts/gamma/`, `results/gamma/`). CI (`.github/`, `pytest.ini`, `conftest.py`). Installing the dashboard's snapshot exporter on the VM | `docs/ROADMAP.md`; `results/cef/RESEARCH_PLAN_2026-10-09.md` §1, §2, §3 and §5 |
| **MACRO** (fixed income) | MACRO | `scripts/macro/`, `results/macro/` | New fixed-income signals: macro events, credit events and fixed-income instruments, each as an overlay or conditioner on the CEF book, a sleeve, or a hedge. Not the PM's EVENTS rows. Start from the KILLED and WATCH tables of `docs/RESEARCH_STATE.md` |
| **Equities and ETFs** | XASSET | `scripts/xasset/`, `results/xasset/` | New equity and ETF signals, single names included, each slate declared up front. Not the PM's EVENTS rows. The XASSET rows of `docs/RESEARCH_STATE.md` |
| **Dashboard and data** | none | The read-only dashboard and its snapshot (`dashboard/`, `dashboard/snapshots/`), and the spec and tests of the snapshot exporter. The research data platform: `scripts/data/`, `scripts/rv/`, `scripts/holdings/`, `scripts/build_etf_daily.py`, `src/data/`, `results/data/`, and the event store once the EVENTS work on `simon` is merged into `main`. Whatever else the team lead assigns case by case | `dashboard/README.md`; `docs/DATA.md`; the other lanes' data requests |

What the table means:

- **Anyone may propose a change to any file**, through a pull request. Keeping a
  path means you are the one who keeps it working and answers for it. It does not
  stop anyone else from proposing a change to it.
- **The team lead is the only reviewer and the only person who merges.**
- **The dashboard is read-only.** No code path from it may send, replace or cancel
  an order (`CLAUDE.md`, "Hard rules: code"). `quantt/` and every file in §2 stay
  with the PM; a change that would touch one is proposed by PR like any other.
- Each lane keeps its own counter rows in `docs/RESEARCH_STATE.md` (§4).
- **Every lane feeds one book** (team lead, 2026-10-26). A passing signal joins the
  CEF book and the EVENTS sleeves as a sleeve of its own, an overlay or conditioner
  on the CEF book, or a hedge, and is weighed at book level
  (`results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md`).

---

## 2. The live path: what can change the book

Every file here can change what the book trades or how its orders are sent. A
change to one goes through a pull request, a test that fails against the old
behaviour (`CLAUDE.md`, "Hard rules: code"), the team lead's `/release-check`, and
a release tag. **Nothing merged into `main` reaches the VM until the team lead tags
it and installs it** (`docs/RUNBOOK.md` §8.6).

| path | what it is |
|---|---|
| `src/deploy/` | the strategy; `sleeves/cef_discount.py` is the book |
| `quantt/` | the session runner, the broker client, the nightly collector, the prod installers |
| `ops/specs/`, `ops/books/` | the frozen spec and the book json: governance objects, changed only through `/spec-change` |
| `ops/schedule/`, `ops/netguard.py` | the NYSE calendar and the network guard, both imported by `quantt/` |
| `config/costs.yaml` | the cost model |
| `scripts/cef/spec.py`, `scripts/cef/fetch_daily.py`, `scripts/fetch_cef_distributions.py` | three files in research folders that the runner calls: the spec reader, the daily price and NAV refresh, and the distribution history |
| `data/cef/` on the prod machine | what the book decides on (`CLAUDE.md`, landmine 9) |

---

## 3. From a branch to `main`, then to prod

1. **Work on your branch**: `ryan`, `james` or `lucy`.
   `git fetch origin && git switch <your first name>`. **GitHub holds
   five branches and no others** (team lead, 2026-10-22; renamed 2026-10-26):
   `main`, those three, and the team lead's `simon`, which holds the team lead's
   work in progress. A pull request opened by the team lead has its own branch only
   while it is open.
2. **Start every day by taking in `main`**: `git merge origin/main`. Merge, do not
   rebase: no force-push is ever needed.
3. **Commit small, and push at least daily**: `git push`. Work that only exists on
   one laptop is invisible to everyone else, and is lost with it.
4. **Before asking for review**, check it:

   ```bash
   git fetch origin && git merge origin/main
   python3 -m pytest
   python3 -m ops.doc_audit --check
   ```

   A branch can have only one open pull request, so commits pushed while one is
   open join it. Keep pieces small so each pull request merges quickly; do not
   create another branch on GitHub.
5. **Open a pull request into `main`** (`gh pr create`, or on GitHub). The template
   asks what the team lead will ask: which lane, whether it spends a trial, whether
   it touches §2, and how each figure was produced.
6. **The team lead reviews it**, then asks for changes or merges it. GitHub refuses
   anyone else's merge, push, force-push or deletion on `main`, and anyone else's
   creation, move or deletion of a protected tag (§6).
7. **Prod is the team lead's alone**: `/release-check`, a release tag, the VM
   install. An analyst never deploys, and never needs to.

---

## 4. Trials and the shared ledgers

Four files are written by more than one lane. Each has one rule, so two branches
cannot each claim the same thing.

| file | the rule |
|---|---|
| `docs/RESEARCH_STATE.md` counter table | **A counter moves in the commit that records the team lead's approval of a pre-registration**, so the team lead's approval order sets the trial number, never who ran first. Each row is kept by its lane (§1). A trial on another lane's counter is agreed with the team lead first. |
| `docs/SYSTEM.md` §5 | Written only for a ruling the team lead has made. An analyst proposes a ruling in a PR description; the team lead records it. |
| `docs/REFERENCES.md` | **From 2026-10-22 a new section's id carries its lane**: `MAC-1`, `MAC-2`… for MACRO, `XA-` for equities and ETFs, `DASH-` for the dashboard. The PM's sections (CEF, EVENTS, GAMMA) continue the `12` series. Existing ids are never renumbered. Before this rule, parallel sessions claimed ids out of order and left gaps in the `12` series. |
| `docs/INDEX.md` | A new authored document gets its row in the same PR. `ops.doc_audit` fails otherwise. |

**Zero-trial work** (feasibility counts, gates, reproductions, data builds) needs
nothing beyond the PR. **A trial needs the team lead's approval before any return is
computed**: draft its pre-registration with `/prereg` on your branch and open a PR.
The rules for counting, holdouts and pre-registration are `CLAUDE.md`, "Hard rules:
research".

---

## 5. What an analyst never does

Most of these cannot happen from an analyst's machine, because it does not have the
access. The rest are rules.

| never | what stops it |
|---|---|
| Send, replace or cancel an order for the book | An analyst holds no key for the book's Alpaca account |
| Reach the prod VM | No ssh alias and no access. Prod reads `UNMEASURED` in orient on your machine; that is correct |
| Push to `main`; create, move or delete a protected tag | GitHub rulesets (§6) |
| Run `python3 -m quantt.session` or `python3 -m quantt.collect` | A rule. With your own paper keys in `config/.env` they would act on your own account. The runner sends nothing unless `DRY_RUN=0`: never set it |
| Run the full `quantt.broker.alpaca_probe` | A rule. Its snapshots in `results/ops/alpaca_probe/` are the team lead's record of the book's account; yours would be your own account under the book's name. `--check-keys` (no network) is fine |
| Commit a credential, or write the VM's address, the vault's name or the subscription into any file | `CLAUDE.md`; this repository is public |
| Commit row-level licensed data (anything derived from WRDS: CRSP, TRACE, Compustat; permnos, CUSIPs, per-event returns) | A rule; the licence and a public repository. `.gitignore` lists every such file known so far; a script that writes a new one adds it to `.gitignore` in the same PR. Aggregates (counts, summaries) may be committed |
| Write research output into `data/cef/` | `CLAUDE.md`, landmine 9 |
| Compute returns on a trial before its pre-registration is approved, or open a holdout | A rule. The counters and holdouts are worth something only while it holds |

---

## 6. Access

| what | from | where it lives |
|---|---|---|
| Write access to this repository as a collaborator: push branches, open PRs | the team lead adds you; GitHub e-mails you the invitation | GitHub |
| A read-only Cloudflare R2 token (the WRDS mirror and the team's `data/` copy, `docs/DATA.md` §3; research only) | the team lead | your own `config/.env` |
| Your own free Alpaca **paper** account: market data and asset and borrow flags | you open it | your own `config/.env` |
| Your own SEC EDGAR contact (`SEC_USER_AGENT`) | you | your own `config/.env` |

The variable names are in `docs/ONBOARDING.md` §2. Credentials are personal: never
share one, and never paste one into a chat, an issue or a Claude session.

**What GitHub enforces** (rulesets on `quanttqueensu/CreditTrading`, set by the team
lead, who is the only bypass actor; both active since 2026-10-26):

- on `main`: no update except by the team lead, so analysts' work arrives only
  through a PR the team lead merges; no force-push; no deletion. GitHub counts even
  the team lead's merge as a bypass, so it is made with `gh pr merge --admin`;
- on the tags `release-*`, `spec-*`, `pre-clean-slate` and `ibkr-final`: no
  creation, move or deletion except by the team lead. A release tag is what prod
  runs; the other two are the provenance of everything before 2026-09-28.

**What it does not stop.** The QUANTT organisation's owners hold admin rights over
every repository in the organisation, this one included, and can edit these
rulesets. The rulesets do not exempt them, so any bypass by an owner is a
deliberate change to a setting, recorded by GitHub (team lead, 2026-10-22: accepted,
and stated here so no page claims more than GitHub enforces). Prod is out of reach
either way: the VM runs only a release tag the team lead installs there, over a
route only the team lead has.
