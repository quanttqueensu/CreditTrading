# Desk journal — what we tried, found, ruled, shipped and earned, day by day

**One entry per day, newest at the bottom.** Each entry has the same five parts.
It is updated **in the same commit** as the change it records. Like the ledger
rule in `docs/RESEARCH_STATE.md`, it is never caught up at the end of a session.

It is the readable running record. **It owns nothing.** Every figure names the
file or command that owns it:
- trial counters and verdicts: `docs/RESEARCH_STATE.md`;
- team-lead rulings: `docs/SYSTEM.md` §5;
- release steps: `docs/RUNBOOK.md`;
- live figures: `python3 -m ops.orient`.

If this journal and an owner disagree, the owner is right, and the journal gets a
dated correction.

**Live P&L** is copied from prod's `verify.log` line for the day: Alpaca's 17:30 ET
snapshot and the auction-marked P&L, both gross. Alpaca's end-of-day history is
the **official** figure (team lead, 2026-10-19), and it lands the next day.
Until it does, the line says *official pending*. Labels: [V] measured or read
from a named source; [doc] copied from a named note.

| part | what goes in it |
|---|---|
| **Research** | every test or screen run, its verdict, its note |
| **Found** | anything discovered about the live system or the data |
| **Rulings** | team-lead decisions, pointing at `docs/SYSTEM.md` §5 |
| **Prod** | every change to the VM: release tags, data repairs, network |
| **Live** | the day's verify line and broker-confirmed equity |

---

## 2026-10-26 (Mon)

**Research (zero trials; dates ≤ 2022-12-30; gross)**: `results/cef/screens_2026-10-26/README.md`
- **Macro regime filters, by fund group:** NOTHING. No group's own macro reading changes the signal's within-group IC.
- **FOMC/CPI/NFP-day discount moves:** NOTHING. Extra reversion −6.9bp (t −0.36); the placebo scores more.
- **C4's ex-date concentration:** MIXED. A generic post-ex-date drift that a z-blind short earns. Paper overstates C4.
- **Fund-of-CEF index rebalances (YYY/PCEF/XMPT):** infeasible on free data (re-run 10-27).
- **BDC discounts:** infeasible locally (re-run 10-27).
- **New lead: the post-ex-date drift.** W4 had first recorded it, untested, on 2026-10-11.

**Rulings:** C4 proceeds toward paper despite MIXED. A pre-registration is drafted for the ex-date drift (`docs/SYSTEM.md` §5, 2026-10-26/27).

**Prod:** no change.

**Live [V, verify.log]:** PASS, 6 orders, 6 filled. Snapshot −$446.70 gross; auction-marked −$520.85.

## 2026-10-27 (Tue)

**Research**
- **BDC discounts**, on the team lead's R2 pull of Compustat: NOTHING in the tradable set. At ADV ≥ $3m the signal is short-term reversal.
- **Index rebalances**, on CRSP fund holdings: ARTIFACT pooled; the placebo scores more. PCEF alone (+184/−120bp) is a post-hoc subgroup.
- **Ex-date Stage 0:** HALTED. Alpaca's `declaration_date` is derived from the record date, so it is not a real declaration date.

**Found:** commit 7c02236's "pytest exit 0" had been read through a pipe (`| tail`), so it measured tail's exit. It was re-verified and corrected in ef6b1b4. Every later check reads the exit code without a pipe.

**Rulings** (`docs/SYSTEM.md` §5, 2026-10-26 and 2026-10-27):
- The ex-date pre-registration is approved as **EVENTS trial 3** (N = 7); part (a) is withdrawn.
- C4 gets its own paper account, the spare connector account.
- C4's setup is accepted as a set.

**Prod:** no change.

**Live [V]:** PASS, 6 orders, 6 filled. Snapshot +$251.43; auction-marked +$192.95.

## 2026-10-28 (Wed)

**Found**
- **`fetch_daily` wrote yfinance's empty ex-date rows** (no close, volume 0), which overwrote good bars. The laptop's refresh had blanked 15 bars; **prod's panel held 91 empty closes** (Feb–Apr 2026), 24 of them on the live book.

**Research:** Stage 0 cleared after rulings. Declaration dates come from the sponsors' own releases; Nuveen's are gone since 2019, so 86 of its events were recovered from CRSP.

**Rulings:**
- Fix the fetcher, NAV side included, in one release.
- Repair prod's panel from Alpaca's official prints.
- The Stage 0 rulings (sponsor declarations; keep the basket; O1–O4).

**Prod [V, ops.prod_state]**
- **16:30 ET: `release-20261028-1` (de6e9c5).** Empty price or NAV rows are never merged; NAVs must be finite (and later positive).
- **17:14 ET: prod panel repair.** 87 closes filled from Alpaca's closing-auction prints; a backup sits next to the panel; one log line per cell (`quantt_state/cef/logs/repair_empty_closes.log`). Measured effect on the day's plan: weights moved ≤ 0.0008, and PTY went flat. 4 NYSE American cells (DHY, EAD) are left empty. DHY's history is split-adjusted, so a raw print would be 10× off.

**Live [V]:** PASS, 10 orders, 10 filled. Snapshot +$414.46; auction-marked +$421.90. Equity $99,528.31 at the close.

## 2026-10-29 (Thu)

**Found**
- **CEFConnect has refused every scripted request since 2026-10-21** (JSONDecodeError). That is why **2026-10-22 was missed**: PDO's NAV was late, there was no fallback, and gate 5 refused all 13. It is also why the collector ended INCOMPLETE and the stale-NAV gate could verify nothing. NAV licensing is upstream, at Nasdaq Fund Network (`results/ops/NAV_SOURCE_WORKAROUND_2026-10-19.md`).
- **PR #20 (corporate-action gate, another session) put an order-path defect on `main`:** gate 6 judges order lists read before the corporate-action fetch. It is not released; a fix is on branch `fix-gate6-stale`.
- The release-check workflow on `main` names a reviewer agent (`quant-trader`) that older sessions don't have. Launch it from the main checkout, or run execution-trader by hand.

**Research (zero trials)**
- **Ex-date short on the full 2005–22 fit:** passes D4. +11.6bp per event, t 3.87, alpha t 4.57, rate betas ≈ −0.05. **Every 3.8-year era fails D4 on its own.** Amendment 1, a duration hedge, was worse and is withdrawn.
- **Risk split, after an independent review** (scratchpad `alloc/` and `alloc_review/`): equal-risk weights. Core + C4 is about 9% gross on the fit, with a realistic Sharpe of 1.2–1.5 and P(HALVE in 12m) of 4–6%. Three sleeves is about 10.6% in-sample. Reg T binds before KILL.
- **C4 step 2:** the live sleeve rebuilds the trial's book on 907 of 907 fit sessions. C4's cap is re-derived as 1.90.
- **PCEF pre-registration drafted:** about 23 test events, so power is weak.

**Rulings** (`docs/SYSTEM.md` §5, 2026-10-29):
- Fast-track C4; the combiner is built first.
- Hold one fund on a missing NAV, for at most **2 sessions** (a policy, not derived); the collector marks CEFConnect as down.
- C4's cap is 1.90, **not a trial**. IGR is seeded with the trial's correction.
- Three sleeves; the ex-date sleeve goes in the spare account beside C4.
- **"Add all 3":**
  - C4 (passed);
  - the ex-date short as a **forward test** (EVENTS 3; the sealed 2023+ test still runs once French publishes);
  - PCEF as **EVENTS trial 4** (N = 8) in a **third** paper account. Its counter moves in the commit that records its pre-registration.
- **Full equal-risk share for every sleeve from day one.**
- Keep this journal.
- **Corporate-action gate (PR #20):** skip and record a malformed row unless it could be ours. A stuck backfilled action clears only by the team lead's recorded acknowledgement. Release `main` only after these and the gate-6 fix.

**Prod [V, ops.prod_state]**
- **10:36 ET: `release-20261029-1` (bd87144).** The multi-sleeve combiner, dark. The first release-check was NO-GO on two defects, both fixed.
- **19:04 ET: `release-20261029-2` (5e627ff).** The missing-NAV hold code (dark); the collector's CEFConnect-down status; official closes for NYSE American (A) and Nasdaq (Q).
- **20:20 ET: `release-20261029-3` (cee16ad).** **The missing-NAV hold is ON** (book json). It deliberately excludes PR #20.
- Ssh allowlist: the team lead's current IP was added to the VM's network rule (`vmallow.sh`, git-excluded), keeping the existing entries.
- Every release passed a release-check (both reviewers) and a history replay (0 new refusals), and was applied with `--armed`. The VM is ARMED at `release-20261029-3`.

**Live [V]:** PASS, 3 orders, 3 filled. Snapshot +$78.64; auction-marked −$13.43. Equity $99,530.59 at the close.

**Open at end of day:**
- the gate-6 fix for PR #20 (4c63b1f, done), plus rulings A and B (being built);
- C4 integration (book, installer, verify per book);
- the ex-date and PCEF sleeves (built dark);
- the four-sleeve, three-account risk split;
- the team lead to create the C4 vault secrets and the third paper account;
- French's 202610 factors for the ex-date test;
- watch the hold's first final check (2026-10-30, 14:30 ET).
