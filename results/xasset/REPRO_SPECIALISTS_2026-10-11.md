# What the CEF specialists earn: SCALING §7.3 re-run — 2026-10-11

**Report only. Spends no trial: XASSET stays at 0, GAMMA at 0. No signal is
scored and no name is traded.** This is research plan item 0.9
(`results/cef/RESEARCH_PLAN_2026-10-09.md`), applied to
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.3.

**Provenance of the figures checked.** They come from a desk agent's 2026-10-09
work:
- its CRSP regressions (scratch `betas.py`, `betas2.py`, `xcheck.py`, deleted
  with its session; the code was recovered from its transcript as provenance);
- its WebFetch reads of EDGAR filings.

**How they were checked.**
- The regressions were rebuilt as `scripts/xasset/specialist_betas.py`.
- Every filed figure under test was re-read today from the primary filing.
- Where CRSP covers the same period, it was also recomputed independently.

**Holdout guard.** None of the 19 vehicles is among the 44 names in
`data/cef/cef_universe.csv`; the script raises if one ever is. The 27-name
holdout is untouched.

## Reproducers

```bash
export QUANTT_ENV_FILE=".../config/.env"       # R2; never printed
python3 scripts/xasset/specialist_betas.py      # CRSP pulls cached under results/xasset/_cache_specialists/ (gitignored)
```

**How the filings were re-read.** Each filing was fetched on 2026-10-11 with
the WebFetch tool, quoting the table rows verbatim. The URLs are below.
- **This is not a scripted EDGAR fetcher.** SEC asks automated clients to
  declare a contact user-agent, and plan item 0.7 leaves that string to the
  team lead ("never the user's email by default").
- **The reads are model-mediated,** so every filed return that CRSP can also
  compute was cross-checked against CRSP.

**Inputs and last dates [V, read 2026-10-11].**
- CRSP `dsf`: to **2024-12-31**.
- CRSP MF `daily_returns`: to **2026-03-31**.
- Fama-French daily `rf`: to 2026-04-30.

## The reproduction table

| figure in SCALING §7.3 | original | re-run / re-read 2026-10-11 | verdict |
|---|---|---|---|
| MDCEX 13.08% over 5 years, 11.39% over 10 | 13.08 / 11.39 | Filing [V]: 1y 20.73, 5y 13.08, 10y 11.39, as of 2026-03-31 (Matisse N-CSR/A, Amendment No. 2). **CRSP MF, independently: 20.73 / 13.08 / 11.39** | **reproduced, two sources** |
| SPE 10.07% over 5 years at NAV | 10.07 | Filing [V]: NAV 1y 11.59, 5y 10.07, 10y 9.61; market 14.65 / 12.18 / 11.17; S&P 500 17.88 / 14.42 / 14.82; to 2025-12-31 (N-CSR) | **reproduced** (filing only; CRSP holds no NAV for SPE and ends 2024) |
| **MDFIX 8.72% over 5 years**, "window starting at the COVID trough" | 8.72 | Filing [V]: the column **is headed "5 Years"**: 1y 4.31, "5 Years" 8.72, since inception (2020-04-30) 7.87. **CRSP MF: 1y 4.31, 5y (2021-03-31..2026-03-31) 3.58, 3y (2023-03-31..2026-03-31) 8.72**; since inception 7.73 (from 2020-05-08) | **corrected**: 8.72% is MDFIX's **3-year** return. Its **5-year NAV return is 3.58%/yr**. Its since-inception figure (7.87% filed) is the one that starts at the COVID trough |
| Matisse credits discount capture with +147bp (MDFIX), in its last year | +147bp | Filing [V], verbatim: "“discount capture” contributed +147 bps to our Fund performance during the period" (fiscal year to 2026-03-31). MDCEX: +490 bps | **reproduced** |
| BRW 9.27%/yr since 2021 | 9.27 | Filing [V]: "Average annual returns for the period since Saba Capital Management, L.P. began managing the Fund on June 4, 2021 are at NAV 9.27% and at market value 7.73%", to 2025-10-31 | **reproduced** |
| BRW "at about 12% vol" | ~12 | CRSP: **12.05%**, annualised daily **market-price** vol, 2021-06-08..2024-12-31 | **reproduced; label made precise**: the vol is market-price, to 2024-12-31; the 9.27% is NAV, to 2025-10-31 |
| SPX + HY explain R² 0.44–0.88 | 0.44–0.88 | **0.22 (RSF) – 0.88 (FCEF)** across the 19 vehicles. Five fall below 0.44: SABA 0.39, RSF 0.22, RMI 0.35, RMM 0.35, XMPT 0.26 | **corrected**: 0.22–0.88. The 0.44 floor holds only after dropping those five (the agent's own report said "0.50–0.88 of the long-biased vehicles") |
| Intercept negative for 15 of 17 vehicles | 15 of 17 | **14 of 19**. Positive: BRW, SABA, CEFS, RSF, XMPT. Over any plausible 17 (dropping SABA, which has 12 months, and one of XMPT or RSF): **14 of 17**. No subset gives 15 of 17. Only **two** negative intercepts have \|t_NW3\| ≥ 2: RFMZ −2.13 and YYY −2.95 | **corrected**: 14 of 17 (14 of 19), and mostly within noise |
| RiverNorth holds 11 of our 13 (13F 2026Q2) | 11 of 13 | 13F-HR [V], period 06-30-2026, signed 08-14-2026, 585 entries, $2.10bn. Matched by CUSIP from CRSP `dsenames` to all three pages of the information table. Held: AWF, BIT, DSL, HYT 5.53m, MHD 11.99m, MQY 7.09m, PCN, PDI, PFN, PHK, PTY. Not held: JFR, PDO | **reproduced** |
| Karpus 11.03% of MHD | 11.03% | Schedule 13G [V]: Karpus Management, Inc., issuer BlackRock MuniHoldings Fund (CUSIP 09253N104); event 2026-02-27; 19,267,035 shares; **11.03%**; signed 2026-03-06 | **reproduced** |

## 1. How much of their return is beta

`scripts/xasset/specialist_betas.py` [V, re-run]. The data are CRSP monthly
returns, compounded from daily, from each manager-era start to 2024-12-31. The
regression is two-factor OLS on excess returns: SPY and HYG, both from CRSP and
both total returns. NAV is used for the open-end MDCEX, MDFIX and RNCOX; market
price for everything else. The agent's numbers reproduce to two decimals.

| vehicle | from | months | CAGR % | vol % | max DD % | β SPY | β HY | R² | intercept %/yr | t (OLS) | t (NW 3) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SPE | 2009-12 | 181 | 9.11 | 15.2 | −46.9 | 0.76 | 0.22 | 0.65 | −1.85 | −0.75 | −0.72 |
| BRW | 2021-06 | 43 | 7.39 | 12.0 | −10.5 | 0.28 | 0.39 | 0.44 | +2.23 | 0.45 | 0.71 |
| SABA | 2024-01 | 12 | 29.76 | 12.2 | −4.1 | −0.23 | 1.62 | 0.39 | +20.83 | 2.51 | 3.67 |
| CEFS | 2017-03 | 94 | 10.86 | 15.6 | −39.0 | 0.38 | 0.97 | 0.80 | +2.31 | 0.92 | 1.33 |
| RIV | 2015-12 | 109 | 7.81 | 21.3 | −42.9 | 0.60 | 0.29 | 0.50 | −1.65 | −0.43 | −0.45 |
| OPP | 2016-09 | 100 | 2.51 | 16.3 | −36.4 | 0.17 | 0.98 | 0.53 | −2.97 | −0.85 | −0.96 |
| RSF | 2019-06 | 67 | 7.58 | 13.8 | −23.1 | 0.18 | 0.18 | 0.22 | +2.61 | 0.65 | 0.65 |
| RMI | 2018-10 | 75 | 2.45 | 16.9 | −32.7 | 0.08 | 0.97 | 0.35 | −1.79 | −0.32 | −0.41 |
| RMM | 2019-07 | 66 | 0.42 | 19.2 | −36.0 | 0.21 | 0.89 | 0.35 | −4.03 | −0.57 | −0.80 |
| RFM | 2020-03 | 58 | 1.98 | 13.4 | −33.9 | 0.30 | 0.75 | 0.44 | −7.29 | −1.18 | −1.63 |
| RFMZ | 2021-02 | 47 | −3.41 | 14.4 | −39.4 | 0.53 | 0.46 | 0.54 | −10.41 | −1.70 | −2.13 |
| RMMZ | 2022-02 | 35 | −0.15 | 19.8 | −27.1 | 0.33 | 1.02 | 0.55 | −5.59 | −0.66 | −0.98 |
| RNCOX (NAV) | 2007-04 | 213 | 7.46 | 14.9 | −45.6 | 0.49 | 0.53 | 0.85 | −0.08 | −0.07 | −0.06 |
| MDCEX (NAV) | 2012-11 | 146 | 8.48 | 14.2 | −48.7 | 0.61 | 0.76 | 0.75 | −2.36 | −0.98 | −0.84 |
| MDFIX (NAV) | 2020-05 | 56 | 8.46 | 7.5 | −23.4 | 0.33 | 0.71 | 0.72 | −0.83 | −0.24 | −0.33 |
| YYY | 2013-06 | 139 | 4.30 | 13.3 | −42.5 | 0.46 | 0.86 | 0.81 | −4.66 | −2.52 | −2.95 |
| PCEF | 2010-02 | 179 | 6.46 | 12.1 | −38.6 | 0.44 | 0.60 | 0.79 | −2.49 | −1.72 | −1.74 |
| FCEF | 2016-09 | 100 | 7.08 | 16.0 | −44.8 | 0.63 | 0.68 | 0.88 | −3.59 | −1.82 | −1.93 |
| XMPT | 2011-07 | 162 | 3.83 | 10.1 | −35.2 | 0.01 | 0.74 | 0.26 | +0.48 | 0.17 | 0.16 |

**"Most of this is beta" stands, on the betas and R², not on the intercept
signs.**
- **The intercepts are mostly noise.** 14 of 19 are negative, but only RFMZ and
  YYY are below −2 on a Newey-West t.
- **The only intercept above +2 is SABA's**, which rests on 12 months.
- **R² is low where the vehicle is hedged (BRW 0.44, RSF 0.22) or muni (RMI,
  RMM, XMPT).** For a muni vehicle, SPY and HYG are the wrong factors, so a low
  R² there says nothing about alpha.

**The pipeline checks.**
- **PCEF and FCEF, CRSP market returns to 2024-12-31:**
  - PCEF: 1y 16.63, 5y 4.65, 10y 6.18;
  - FCEF: 1y 17.47, 5y 5.30, since 2016-09-27 7.07.

  These are the values the agent printed against the 497K figures (16.29 / 4.62
  / 6.16 and 17.49 / 5.19 / 7.05). The 497Ks were **not** re-read today, so
  those filed figures stay [S].
- **MDCEX: the stronger check.** CRSP MF matches the filing to the hundredth on
  all three horizons.

## 2. The MDFIX correction, in detail

The Matisse N-CSR/A (Amendment No. 2, period ended 2026-03-31) prints, for
MDFIX: "1 Year 4.31%, 5 Years 8.72%, Since Inception 7.87%". Inception was
2020-04-30. Re-read twice today; the header is "5 Years".

The 8.72% cannot be a 5-year figure:
- **The filing's own columns contradict it.** A 5-year return above the
  since-inception return would need the first 11 months, May 2020 to March 2021,
  to have earned about +3%. CRSP MF shows +30.3% for that stretch: the post-COVID
  CEF rally.
- **It matches the 3-year window to the hundredth.** CRSP MF gives MDFIX
  3.58%/yr over 2021-03-31..2026-03-31 and **8.72%/yr over
  2023-03-31..2026-03-31**. The 1-year (4.31) matches exactly, and since
  inception CRSP gives 7.73% against 7.87%; CRSP starts 2020-05-08, so it misses
  the first week.
- **The benchmark rows show the same mismatch.** The filing's Bloomberg U.S.
  Aggregate "5 Years" is 3.63%. The AGG ETF's total return from
  `data/rv/etf_panel.parquet` is 0.29%/yr over 5 years and 3.59%/yr over 3. Its
  since-inception figure (0.08%) matches the filing's (0.09%).

**Reading [U, inferred]:** the "5 Years" column of MDFIX's table holds 3-year
returns, an error in the filing. **For our purposes the closest analogue to our
book returned 3.58%/yr over five years at NAV**, not 8.72%. That strengthens
§7.3's first conclusion: no audited record shows 10%+ from credit-CEF discount
capture.

## Not re-run in this pass (still the agent's [V] of 2026-10-09)

- "Specialists hold about 18.5% of MHD in total". This needs the 13Fs of 1607
  and CLIM plus a share count.
- MQY's share-count conflict: `cef_facts.csv` 71.8m against 150.5m implied by
  RiverNorth's 13G. Both are still unresolved.
- The Saba 13D history on JFR; JPMorgan's VMTP holding in MHD.
- Form ADV assets under management; CLIG's FY26 figures.
- CEFS's filed returns (`docs/REFERENCES.md` §12c).
- RIV, OPP, RNCOX and YYY filed returns.

## Sources re-read 2026-10-11 (via WebFetch; [V] = the table rows quoted)

- **Matisse N-CSR/A, period 2026-03-31:** https://www.sec.gov/Archives/edgar/data/1464413/000199937126022197/matisse-ncsr_033126.htm
- **SPE N-CSR, 2025-12-31:** https://www.sec.gov/Archives/edgar/data/897802/000199937126005469/spe_ncsr-123125.htm
- **BRW N-CSR, FY to 2025-10-31:** https://www.sec.gov/Archives/edgar/data/826020/000139834426000054/fp0096546-1_ncsrixbrl.htm
- **RiverNorth 13F-HR, 2026Q2:**
  - information table: https://www.sec.gov/Archives/edgar/data/1447578/000139834426014659/fp0099124-1_13fhr-table.xml (read in three pages);
  - cover: `.../primary_doc.xml`.
- **Karpus 13G on MHD:** https://www.sec.gov/Archives/edgar/data/1034665/000107261326000243/xslSCHEDULE_13G_X01/primary_doc.xml
- **CRSP via R2** (`dsf`, `dsenames`, MF `daily_returns`, `fund_hdr_hist`; FF `factors_daily`), read 2026-10-11.
