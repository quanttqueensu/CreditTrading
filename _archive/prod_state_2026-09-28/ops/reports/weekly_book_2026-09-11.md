# Weekly book report — week ending 2026-09-11

Read-only roll-up of the daily runs across 3 live book(s) (window 2026-09-05..2026-09-11).

## Sleeves

### Book `cef_discount_paper`

| sleeve | last asof | NAV | week PnL | since-inception PnL | N days | note |
|---|---|---:|---:|---:|---:|---|
| cef_discount | 2026-09-10 | $504,030 | $+4,030 | $+4,030 | 3 |  |

Sample: 2026-09-08..2026-09-11 across 1 live sub-ledger(s).

- rollup asof **2026-09-10** — NAV $504,030.09, PnL $4,030.09, gross $820,199, turnover $87,003
- limit `max_gross_exposure_usd`: OK
- limit `book_drawdown_suspend_pct`: OK
- limit `per_sleeve_capital_band`: OK
- limit `book_worst_month_usd`: OK

### Book `phase0_null`

| sleeve | last asof | NAV | week PnL | since-inception PnL | N days | note |
|---|---|---:|---:|---:|---:|---|
| null_trader | 2026-09-10 | $641,105 | $+35 | $+1,105 | 30 |  |

Sample: 2026-07-30..2026-09-11 across 1 live sub-ledger(s).

- rollup asof **2026-09-10** — NAV $641,105.36, PnL $1,105.36, gross $639,524, turnover $941,272
- limit `max_gross_exposure_usd`: OK
- limit `book_drawdown_suspend_pct`: OK
- limit `per_sleeve_capital_band`: OK
- limit `book_worst_month_usd`: OK

### Book `benchmarks_paper`

| sleeve | last asof | NAV | week PnL | since-inception PnL | N days | note |
|---|---|---:|---:|---:|---:|---|
| bench_b1_hyg | 2026-09-11 | $19,859 | $-141 | $-141 | 4 |  |
| bench_b3_agg | 2026-09-11 | $19,790 | $-210 | $-210 | 4 |  |
| bench_b4_60_40 | 2026-09-08 **STALE 3bd** | $20,000 | $+0 | $+0 | 1 |  |
| bench_b5_shy | 2026-09-11 | $19,922 | $-78 | $-78 | 4 |  |
| bench_b6_ew_credit | 2026-09-11 | $19,827 | $-173 | $-173 | 4 |  |

Sample: 2026-09-08..2026-09-11 across 5 live sub-ledger(s).

- rollup asof **2026-09-11** — NAV $99,397.27, PnL $-602.73, gross $86,944, turnover $0
- limit `max_gross_exposure_usd`: OK
- limit `book_drawdown_suspend_pct`: OK
- limit `per_sleeve_capital_band`: OK
- limit `book_worst_month_usd`: OK

## Dry-run activity this week

- cef/dryrun_2026-09-08.json: 17 targets logged, transmitted=False
- cef/dryrun_2026-09-11.json: 17 targets logged, transmitted=False
- phase0/dryrun_2026-09-11.json: 14 targets logged, transmitted=False

N = 3 dry-run file(s) in 2026-09-05..2026-09-11.
