# R2 coverage for candidate signals

**Run:** 2026-10-08 19:10 UTC by `scripts/data/r2_signal_coverage.py`. Read-only. True as of that timestamp only -- re-run before quoting a figure.

## 1. Do our CEFs appear in `crsp_q_mutualfunds`?

Tickers tested: the 13 deployed (spec `UNIVERSE`) and the 44 in `data/cef/cef_universe.csv`, 44 distinct.

- matched in `fund_hdr.ticker`: **0** []
- matched in `fund_hdr_hist.ticker`: **0** []

A match would still need its fund name read: a ticker match is not an identity. No match means this table is not an independent NAV source for the book.

## 2. Open-end credit funds (a sub-class retail-flow series)

Distinct `crsp_fundno` per Lipper class in `fund_style` (share classes of one portfolio count separately; aggregate by `crsp_portno` before summing flows).

| lipper_class   | class_name                               |   funds | first               | last                |
|:---------------|:-----------------------------------------|--------:|:--------------------|:--------------------|
| IID            | Intermediate Investment Grade Debt Funds |    1854 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| HY             | High Current Yield Funds                 |    1636 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| MSI            | Multi-Sector Income Funds                |     998 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| BBB            | Corporate Debt Funds BBB-Rated           |     902 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| GLI            | Global Income Funds                      |     808 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| GM             | General Municipal Debt Funds             |     799 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| SII            | Short-Intmdt Investment Grade Debt Funds |     658 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| EMD            | Emerging Markets Debt Funds              |     587 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| IMD            | Intermediate Municipal Debt Funds        |     566 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| A              | Corporate Debt Funds A Rated             |     474 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| LP             | Loan Participation Funds                 |     389 | 2002-06-30 00:00:00 | 2026-03-31 00:00:00 |
| USM            | U.S. Mortgage Funds                      |     372 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| HM             | High Yield Municipal Debt Funds          |     315 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| FLX            | Flexible Income Funds                    |     195 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |
| SIM            | Short-Intmdt Municipal Debt Funds        |     185 | 1999-12-31 00:00:00 | 2026-03-31 00:00:00 |

- `monthly_tna`: 1960-03-31 .. **2026-03-31**, 9,923,098 rows
- `fund_flows`: 1990-07-31 .. **2026-01-30**, 2,706,224 rows

## 3. Hedge / nowcast / trend ETFs in `crsp_a_stock`

Every `stocknames` row for each ticker, with that PERMNO's `dsf` span. Share code 73 is an ETF; other codes are recycled tickers.

| ticker   |   permno |   shrcd | comnam                     | namedt              | nameenddt           | first               | last                |   days |
|:---------|---------:|--------:|:---------------------------|:--------------------|:--------------------|:--------------------|:--------------------|-------:|
| BKLN     |    12631 |      73 | POWERSHARES E T F TRUST II | 2011-03-03 00:00:00 | 2018-06-03 00:00:00 | 2011-03-03 00:00:00 | 2024-12-31 00:00:00 |   3481 |
| BKLN     |    12631 |      73 | INVESCO E T F TRUST II     | 2018-06-04 00:00:00 | 2024-12-31 00:00:00 | 2011-03-03 00:00:00 | 2024-12-31 00:00:00 |   3481 |
| EMB      |    92491 |      73 | ISHARES TRUST              | 2007-12-19 00:00:00 | 2017-08-01 00:00:00 | 2007-12-19 00:00:00 | 2024-12-31 00:00:00 |   4287 |
| EMB      |    92491 |      73 | ISHARES TRUST              | 2017-08-02 00:00:00 | 2024-12-31 00:00:00 | 2007-12-19 00:00:00 | 2024-12-31 00:00:00 |   4287 |
| HYG      |    91933 |      73 | ISHARES TRUST              | 2007-04-11 00:00:00 | 2008-11-05 00:00:00 | 2007-04-11 00:00:00 | 2024-12-31 00:00:00 |   4463 |
| HYG      |    91933 |      73 | ISHARES TRUST              | 2008-11-06 00:00:00 | 2024-12-31 00:00:00 | 2007-04-11 00:00:00 | 2024-12-31 00:00:00 |   4463 |
| IEF      |    89469 |      73 | ISHARES TRUST              | 2002-07-26 00:00:00 | 2007-08-30 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| IEF      |    89469 |      73 | ISHARES TRUST              | 2007-08-31 00:00:00 | 2017-08-01 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| IEF      |    89469 |      73 | ISHARES TRUST              | 2017-08-02 00:00:00 | 2024-12-31 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| JNK      |    92922 |      73 | SPDR SERIES TRUST          | 2007-12-04 00:00:00 | 2008-11-06 00:00:00 | 2007-12-04 00:00:00 | 2024-12-31 00:00:00 |   4298 |
| JNK      |    92922 |      73 | SPDR SERIES TRUST          | 2008-11-07 00:00:00 | 2019-05-05 00:00:00 | 2007-12-04 00:00:00 | 2024-12-31 00:00:00 |   4298 |
| JNK      |    92922 |      73 | SPDR SERIES TRUST          | 2019-05-06 00:00:00 | 2024-12-31 00:00:00 | 2007-12-04 00:00:00 | 2024-12-31 00:00:00 |   4298 |
| LQD      |    89467 |      73 | ISHARES TRUST              | 2002-07-26 00:00:00 | 2007-08-30 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| LQD      |    89467 |      73 | ISHARES TRUST              | 2007-08-31 00:00:00 | 2024-12-31 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| MUB      |    20503 |      10 | MUELLER BRASS CO           | 1962-07-02 00:00:00 | 1965-09-24 00:00:00 | 1937-03-15 00:00:00 | 1965-09-24 00:00:00 |   7800 |
| MUB      |    92273 |      73 | ISHARES TRUST              | 2007-09-10 00:00:00 | 2008-11-05 00:00:00 | 2007-09-10 00:00:00 | 2024-12-31 00:00:00 |   4358 |
| MUB      |    92273 |      73 | ISHARES TRUST              | 2008-11-06 00:00:00 | 2024-12-31 00:00:00 | 2007-09-10 00:00:00 | 2024-12-31 00:00:00 |   4358 |
| PFF      |    91874 |      73 | ISHARES TRUST              | 2007-03-30 00:00:00 | 2008-11-05 00:00:00 | 2007-03-30 00:00:00 | 2024-12-31 00:00:00 |   4470 |
| PFF      |    91874 |      73 | ISHARES TRUST              | 2008-11-06 00:00:00 | 2017-08-01 00:00:00 | 2007-03-30 00:00:00 | 2024-12-31 00:00:00 |   4470 |
| PFF      |    91874 |      73 | ISHARES TRUST              | 2017-08-02 00:00:00 | 2024-12-31 00:00:00 | 2007-03-30 00:00:00 | 2024-12-31 00:00:00 |   4470 |
| SRLN     |    13859 |      73 | SSGA ACTIVE E T F TRUST    | 2013-04-04 00:00:00 | 2015-02-22 00:00:00 | 2013-04-04 00:00:00 | 2024-12-31 00:00:00 |   2957 |
| SRLN     |    13859 |      73 | SSGA ACTIVE TRUST          | 2015-02-23 00:00:00 | 2024-12-31 00:00:00 | 2013-04-04 00:00:00 | 2024-12-31 00:00:00 |   2957 |
| TLT      |    89468 |      73 | ISHARES TRUST              | 2002-07-26 00:00:00 | 2007-08-30 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| TLT      |    89468 |      73 | ISHARES TRUST              | 2007-08-31 00:00:00 | 2016-02-01 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |
| TLT      |    89468 |      73 | ISHARES TRUST              | 2016-02-02 00:00:00 | 2024-12-31 00:00:00 | 2002-07-26 00:00:00 | 2024-12-31 00:00:00 |   5647 |

- tickers with no `stocknames` row: **[]**
