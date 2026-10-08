# Data — which source feeds what

**Written 2026-09-28 (branch `alpaca-runner`).** This file says where each kind of data
comes from and which code reads it. It is not a place to learn figures from: every
date or count below names the run that measured it. Re-run that script before you
quote one. **Stale is a form of wrong** (`CLAUDE.md`).

## 1. The one rule

**R2 is never on the live path.** The live sleeve decides on `data/cef/*.parquet`, and
nothing under `quantt/` or `src/deploy/` imports `src/data/` or `scripts/data/`.
`src/data/tests/test_r2.py::test_live_path_never_imports_r2` fails if either does
(`docs/RUNNER.md`, module boundaries). The reason: the mirror is refreshed on WRDS's
schedule, which nobody on this desk controls. A session that read it would be deciding
on a panel whose last date is somebody else's choice.

## 2. Sources

| use | source | code | notes |
|---|---|---|---|
| **Live: prices** the sleeve decides on | yfinance `Ticker(tk).history(auto_adjust=False)` | `scripts/cef/fetch_daily.py` → `data/cef/cef_prices.parquet` | Only one source. §4 is the first independent check of it. |
| **Live: NAV** | yfinance NAV symbol `X<TK>X`, with CEFConnect's dated row as an explicit, logged fallback (`--nav-fallback cefconnect`, every fill written to `data/cef/nav_fallback_log.csv`) | `scripts/cef/fetch_daily.py` → `data/cef/cef_nav.parquet` | The session runs it with `--require-asof`. Stale data never trades (`docs/RUNNER.md` step 1). |
| **Research / backtest** | Cloudflare R2 bucket, a WRDS mirror | `src/data/r2.py` (DuckDB over httpfs, read-only) | §3. Never live. |
| **Broker truth** (positions, fills, tradability, shortability) | Alpaca Trading API, paper | `quantt/broker/` | The authority on our accounts (`CLAUDE.md` data rule 2). |
| **Official closes, cross-check** | Alpaca Market Data API, closing-auction prints (condition M, primary exchange) | `quantt/collect` → `data/cef/alpaca_official_close.parquet` (§5) | A second live-era price source beside yfinance. The auction prints are also the second P&L score (`docs/RUNNER.md`, verify step). CEF coverage on the Basic plan is **not yet measured** over any run. |

The other files in `data/cef/` (distributions, borrow, splits, universe, facts) have
their own fetchers. This file does not describe them.

## 3. The R2 mirror

### Layout

```
s3://<bucket>/wrds/<schema>/<table>.parquet          one file per WRDS table
s3://<bucket>/options/<SYM>/tick/<YYYY-MM>.parquet   one file per underlying-month
```

`src/data/r2.py` builds both paths: `r2_path(schema, table)` and
`options_path(SYM, "YYYY-MM")`. It validates each identifier before it goes into SQL.

### What is in it

**`results/data/R2_CATALOG.md` is the inventory.** Regenerate it with
`python3 scripts/data/r2_catalog.py` (read-only, about 2 minutes). For each curated
table it gives the columns, the row count and the min/max of every DATE-typed column.
It lists every object under the research schemas, and it enumerates every options
underlying present rather than trusting a remembered list. It exits 1 if a curated
table is absent.

As measured by that run at **2026-09-28 20:31 UTC** [V]. The option-underlying table is
from the rerun at about 20:40 UTC the same day. True on that date only:

| table | what research uses it for | date coverage |
|---|---|---|
| `crsp_a_stock.dsf` | daily prices; the independent check in §4 | 1925-12-31 .. **2024-12-31** |
| `crsp_a_stock.stocknames`, `dsenames` | ticker → PERMNO by date range | to 2024-12-31 |
| `crsp_a_stock.dsf_v2`, `stocknames_v2`, `stk*` | CRSP's newer CIZ-format tables, also present | not yet described |
| `crsp_q_mutualfunds.daily_nav` | fund NAVs (`crsp_fundno`, `caldt`, `dnav`) | 1998-09-01 .. 2026-03-31 |
| `ff_all.factors_daily` | Fama-French 3 factors + momentum | 1926-07-01 .. 2026-04-30 |
| `frb_all.rates_daily` | Fed H.15-style rates, swap rates, ICE BofA OAS/yield series | 1954-01-04 .. 2025-02-13 |
| `trace_enhanced.*`, `trace_standard.*` | corporate bond trades | listed, not yet described |
| `options/{SPY,QQQ}/tick` | option ticks | 2014-06 .. 2026-07 |
| `options/{GLD,IWM,SLV}/tick` | option ticks | 2023-10 .. 2026-07 |
| `options/TLT/tick` | option ticks | 2023-11 .. 2026-07 |

The following are consequences of those dates. Re-measure before you act on any of them.

- The CRSP stock file stops at 2024-12-31. **It cannot check any price in 2025–26.**
  That covers most of the 2023-01-01 time holdout's live years.
- The only options underlyings present are SPY, QQQ, TLT, IWM, GLD and SLV. **There is no
  HYG or LQD.** `docs/SYSTEM.md` names "the R2 trades source if it carries HYG/LQD/TLT"
  for options. As of this run, R2 carries only TLT of those three.
- Whether `crsp_q_mutualfunds.daily_nav` covers closed-end funds at all is **not
  measured**. Do not assume it does. It is the obvious candidate for an independent NAV
  check, and nobody has tried it yet.

### Credentials

The keys go in the env file `$QUANTT_ENV_FILE`, or `<repo>/config/.env` when that is
unset. Both are absolute paths, never relative to the working directory. The file must
set all four of `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and
`R2_BUCKET`. A missing one raises and names the variable. There are no defaults and no
alias names, and `os.environ` is not consulted. The file is read with `dotenv_values`,
so it is never exported into the environment.

The connection is a DuckDB **TEMPORARY secret scoped to `s3://<bucket>`**. It lives in
memory only and applies to nothing else. There are no global `SET s3_*` statements.

```bash
python3 -m src.data.r2 --check-keys     # SET / NOT SET per variable; no network, no values
```

Agents never open the env file (`CLAUDE.md` order-path rule 5). On 2026-09-28,
python-dotenv warned that it `could not parse statement starting at line 14` of
`config/.env`. The four R2 variables still loaded. Line 14 is for the team lead to look
at.

## 4. Independent check: the live price panel against CRSP

`python3 scripts/data/cef_crosscheck_crsp.py` compares
`data/cef/cef_prices.parquet` closes for the frozen universe (`scripts/cef/spec.py`
`UNIVERSE`) against CRSP `dsf.prc`, mapping ticker → PERMNO through `stocknames` date
ranges. It never averages the two sources and never picks one. It writes
`results/data/cef_crosscheck_crsp_<date>.md`, plus a CSV of every row that did not agree.
It exits 1 unless every row maps and every comparable raw close agrees within $0.005.
The docstring explains the categories: a negative CRSP `prc` means no closing trade, so
it is never compared as a close.

**First run: 2026-09-28 20:37 UTC** [V]. The panel's last date was 2026-09-21 and CRSP's
last date was 2024-12-31. Verdict **FAIL**, for these findings (full detail in the report):

- All 13 names mapped to one PERMNO each. Every mapped PERMNO's name records carry CRSP
  share code 14 or 44. No row was ambiguous. Six tickers (BIT, DSL, PCN, PDI, PDO, PFN) were
  recycled from unrelated earlier issuers with share code 10/11 (e.g. DSL = Downey
  Financial until 2008). PDI was also Putnam Dividend Income Fund until 2001. The
  date-range join correctly left all of those out.
- Raw closes agree on all but 131 of 65,664 compared rows. 98 of the 131 differ by
  between $0.005 and $0.0051: one source prints a sub-cent or half-cent price. The
  largest are AWF in 1994–2000 (up to $0.125, the fractional-tick era), PCN and JFR in
  the days right after their IPOs (up to $0.05), and scattered single days of up to $0.03.
- **JFR 2004-03-25**: the panel has a zero-volume bar (close 15.96) one day before
  CRSP's first JFR date. That looks like a phantom pre-listing bar in the yfinance panel.
- MHD has 3 CRSP no-trade days (1997, 2001) on which the panel shows a close.
- The panel's closes match CRSP **raw** prices, not CRSP's `cfacpr`-adjusted prices. That
  is visible for HYT (`cfacpr` 1.003397 over 2004–2018) and PFN (a `cfacpr` change after
  2023-05-26). So the panel is **not** adjusted for those events. Which corporate action
  each `cfacpr` step reflects is not established here.

## 5. The nightly collector (`quantt/collect`, 2026-09-29)

`python3 -m quantt.collect --book cef` records every trading day, whether or not the
book traded. It runs every 30 minutes, all day. When the day is
already complete it reads Alpaca's clock and calendar, prints `IDLE <D> complete` and
exits 0. Prod schedules it every 30 minutes at :10 and :40 (`quantt/deploy/`: a launchd job
on the laptop, a systemd timer on the VM). The module docstring has the full design.

- **Data day D.** D is the latest date that both Alpaca's `/v2/calendar` and
  `ops/schedule/nyse_calendar` call a trading day, and whose close + 45 minutes has
  passed by Alpaca's clock. If the two calendars disagree, the run raises and names both.
- **Steps.** Each step is idempotent and recorded in
  `$QUANTT_STATE_DIR/data/<D>/status.json`. A failed step is retried next slot, and a
  step that completed is not run again.
  1. `prices_nav` runs `fetch_daily.py --require-asof D`, with the session's flags and a
     15-minute timeout.
  2. `nav_crosscheck` compares each deployed name's panel NAV with CEFConnect.
  3. `official_closes` fetches the Alpaca auction prints into
     `data/cef/alpaca_official_close.parquet`, de-duplicated on (date, ticker).
  4. `close_crosscheck` compares each official close with the panel close.
  5. `account_snapshot` writes `<D>/account.json` and one row per day in
     `$QUANTT_STATE_DIR/equity.csv`. It is taken only before the next session opens.
  6. `distributions` runs `scripts/fetch_cef_distributions.py`, with a 20-minute timeout.
- **Where it writes.** Each run that did work writes `<D>/report.json` (steps, flags,
  gaps) and appends one line to `$QUANTT_STATE_DIR/data.log`:
  `<D> DATA COMPLETE|INCOMPLETE <failed steps> flags=<n> gaps=<n>`.
- **Exit codes.** 0 means complete or idle. 5 means incomplete and will be retried.
  20 means an unexpected error: it is recorded in data.log and the traceback goes to
  stderr.
- **Report only (team lead, 2026-09-29).** A cross-check disagreement of more than
  $0.005 is a *flag*. The flag names both sources and both values. It never blocks
  trading and never fails a step, and the two values are never averaged. A value that one
  source lacks is a *gap* naming the fund. Suppose the panel's NAV for D was itself
  filled from CEFConnect (`nav_fallback_log.csv`). Then that name is a gap, because
  comparing a source with itself is not a check.
- **Panel lock.** The session and the collector both run `fetch_daily.py`. Its
  read-modify-write of the price and NAV panels holds an exclusive `flock` on
  `data/cef/.fetch.lock`. A second run waits up to 10 minutes, then exits 3 and names
  the lock (`fetch_daily.py` docstring, LOCKING).

## 6. Open questions

1. `crsp_q_mutualfunds.daily_nav`: does it cover our CEFs? If it does, it would be an
   independent NAV source for the history.
2. Alpaca Market Data: the feed tier, and CEF coverage of daily bars and closing-auction
   prints. Measure it before relying on either.
3. Should the JFR 2004-03-25 bar be dropped from the live panel? That is a panel change
   under `data/`, so it is the team lead's call. It does not affect any date the book
   now decides on.
