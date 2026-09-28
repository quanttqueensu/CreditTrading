# R2 catalog (WRDS mirror)

**Run:** 2026-09-28 20:38:10 UTC by `scripts/data/r2_catalog.py`. Read-only. True as of that timestamp only -- re-run before quoting a date or a column.
Bucket name redacted to `<bucket>`.

## Curated tables

### `crsp_a_stock.dsf`

path: `s3://<bucket>/wrds/crsp_a_stock/dsf.parquet`

rows: 107663470

date range `date`: 1925-12-31 .. 2024-12-31

| column | type |
|---|---|
| `cusip` | VARCHAR |
| `permno` | INTEGER |
| `permco` | INTEGER |
| `issuno` | INTEGER |
| `hexcd` | SMALLINT |
| `hsiccd` | INTEGER |
| `date` | DATE |
| `bidlo` | DECIMAL(11,5) |
| `askhi` | DECIMAL(11,5) |
| `prc` | DECIMAL(11,5) |
| `vol` | DECIMAL(10,0) |
| `ret` | DECIMAL(10,6) |
| `bid` | DECIMAL(11,5) |
| `ask` | DECIMAL(11,5) |
| `shrout` | DOUBLE |
| `cfacpr` | DOUBLE |
| `cfacshr` | DOUBLE |
| `openprc` | DECIMAL(11,5) |
| `numtrd` | INTEGER |
| `retx` | DECIMAL(10,6) |

### `crsp_a_stock.stocknames`

path: `s3://<bucket>/wrds/crsp_a_stock/stocknames.parquet`

rows: 83280

date range `namedt`: 1925-12-31 .. 2024-12-31
date range `nameenddt`: 1926-02-24 .. 2024-12-31
date range `st_date`: 1925-12-31 .. 2024-12-31
date range `end_date`: 1926-02-24 .. 2024-12-31

| column | type |
|---|---|
| `permno` | INTEGER |
| `namedt` | DATE |
| `nameenddt` | DATE |
| `shrcd` | SMALLINT |
| `exchcd` | SMALLINT |
| `siccd` | INTEGER |
| `ncusip` | VARCHAR |
| `ticker` | VARCHAR |
| `comnam` | VARCHAR |
| `shrcls` | VARCHAR |
| `permco` | INTEGER |
| `hexcd` | SMALLINT |
| `cusip` | VARCHAR |
| `st_date` | DATE |
| `end_date` | DATE |
| `namedum` | DOUBLE |

### `crsp_a_stock.dsenames`

path: `s3://<bucket>/wrds/crsp_a_stock/dsenames.parquet`

rows: 117859

date range `namedt`: 1925-12-31 .. 2024-12-31
date range `nameendt`: 1926-02-24 .. 2024-12-31

| column | type |
|---|---|
| `permno` | INTEGER |
| `namedt` | DATE |
| `nameendt` | DATE |
| `shrcd` | SMALLINT |
| `exchcd` | SMALLINT |
| `siccd` | INTEGER |
| `ncusip` | VARCHAR |
| `ticker` | VARCHAR |
| `comnam` | VARCHAR |
| `shrcls` | VARCHAR |
| `tsymbol` | VARCHAR |
| `naics` | VARCHAR |
| `primexch` | VARCHAR |
| `trdstat` | VARCHAR |
| `secstat` | VARCHAR |
| `permco` | INTEGER |
| `compno` | INTEGER |
| `issuno` | INTEGER |
| `hexcd` | SMALLINT |
| `hsiccd` | INTEGER |
| `cusip` | VARCHAR |

### `crsp_q_mutualfunds.daily_nav`

path: `s3://<bucket>/wrds/crsp_q_mutualfunds/daily_nav.parquet`

rows: 183733712

date range `caldt`: 1998-09-01 .. 2026-03-31

| column | type |
|---|---|
| `crsp_fundno` | DOUBLE |
| `caldt` | DATE |
| `dnav` | DOUBLE |

### `ff_all.factors_daily`

path: `s3://<bucket>/wrds/ff_all/factors_daily.parquet`

rows: 26233

date range `date`: 1926-07-01 .. 2026-04-30

| column | type |
|---|---|
| `date` | DATE |
| `mktrf` | DECIMAL(8,6) |
| `smb` | DECIMAL(8,6) |
| `hml` | DECIMAL(8,6) |
| `rf` | DECIMAL(7,5) |
| `umd` | DECIMAL(8,6) |

### `frb_all.rates_daily`

path: `s3://<bucket>/wrds/frb_all/rates_daily.parquet`

rows: 25924

date range `date`: 1954-01-04 .. 2025-02-13

| column | type |
|---|---|
| `date` | DATE |
| `daaa` | DOUBLE |
| `dbaa` | DOUBLE |
| `dcd1m` | DOUBLE |
| `dcd90` | DOUBLE |
| `dcd6m` | DOUBLE |
| `h1rifsgfpam03nb` | DOUBLE |
| `h0rifsgfpam06nb` | DOUBLE |
| `h0rifsgfpay01nb` | DOUBLE |
| `dbkac` | DOUBLE |
| `d_ba_m6` | DOUBLE |
| `dltboard` | DOUBLE |
| `d_cp_m1` | DOUBLE |
| `d_cp_m3` | DOUBLE |
| `d_cp_m6` | DOUBLE |
| `rifsppcusnb` | DOUBLE |
| `rifsppcunb` | DOUBLE |
| `d_dwb_na` | DOUBLE |
| `d_fp_m1` | DOUBLE |
| `d_fp_m3` | DOUBLE |
| `d_fp_m6` | DOUBLE |
| `d_ltnom_y25p` | DOUBLE |
| `d_tcmnom_y20` | DOUBLE |
| `dpcredit` | DOUBLE |
| `ded1` | DOUBLE |
| `ded3` | DOUBLE |
| `ded6` | DOUBLE |
| `effr` | DOUBLE |
| `dff` | DOUBLE |
| `dltiit` | DOUBLE |
| `obfr` | DOUBLE |
| `dprime` | DOUBLE |
| `sofr` | DOUBLE |
| `dswp1` | DOUBLE |
| `dswp10` | DOUBLE |
| `dswp2` | DOUBLE |
| `dswp3` | DOUBLE |
| `dswp30` | DOUBLE |
| `dswp4` | DOUBLE |
| `dswp5` | DOUBLE |
| `dswp7` | DOUBLE |
| `dtb3` | DOUBLE |
| `dtb6` | DOUBLE |
| `dtb4wk` | DOUBLE |
| `dtb1yr` | DOUBLE |
| `dfii10` | DOUBLE |
| `dfii20` | DOUBLE |
| `dfii30` | DOUBLE |
| `dfii5` | DOUBLE |
| `dfii7` | DOUBLE |
| `dgs1mo` | DOUBLE |
| `dgs3mo` | DOUBLE |
| `dgs6mo` | DOUBLE |
| `dgs1` | DOUBLE |
| `dgs10` | DOUBLE |
| `dgs2` | DOUBLE |
| `dgs20` | DOUBLE |
| `dgs3` | DOUBLE |
| `dgs30` | DOUBLE |
| `dgs5` | DOUBLE |
| `dgs7` | DOUBLE |
| `dcpf3m` | DOUBLE |
| `dcpn3m` | DOUBLE |
| `dcpf2m` | DOUBLE |
| `dcpn2m` | DOUBLE |
| `dcpf1m` | DOUBLE |
| `dcpn30` | DOUBLE |
| `dfedtaru` | DOUBLE |
| `dfedtarl` | DOUBLE |
| `tedrate` | DOUBLE |
| `t10y2y` | DOUBLE |
| `t10y3m` | DOUBLE |
| `t10yie` | DOUBLE |
| `t5yie` | DOUBLE |
| `iorb` | DOUBLE |
| `ioer` | DOUBLE |
| `iorr` | DOUBLE |
| `bamlh0a0hym2` | DOUBLE |
| `bamlh0a0hym2ey` | DOUBLE |
| `bamlc0a0cmey` | DOUBLE |
| `bamlc0a1caaaey` | DOUBLE |
| `bamlh0a1hybbey` | DOUBLE |
| `bamlh0a3hycey` | DOUBLE |

## Option underlyings present (`options/<SYM>/tick/`)

| underlying | month files | first | last |
|---|---|---|---|
| GLD | 34 | 2023-10 | 2026-07 |
| IWM | 34 | 2023-10 | 2026-07 |
| QQQ | 146 | 2014-06 | 2026-07 |
| SLV | 34 | 2023-10 | 2026-07 |
| SPY | 146 | 2014-06 | 2026-07 |
| TLT | 33 | 2023-11 | 2026-07 |

## Object listings

### `wrds/crsp_a_stock/` (94 objects)

- `s3://<bucket>/wrds/crsp_a_stock/dse.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dseall.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsedelist.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsedist.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dseexchdates.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsenames.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsenasdin.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dseshares.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsf.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsf_v2.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsfhdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsi.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/dsiy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/inddlyseriesdata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/indfamilyinfohdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/indmthseriesdata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/indseriesinfohdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metacalendarperiod.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metacolumncoverage.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metacolumninfo.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metaexchangecalendar.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metafileinfo.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metaflagcoverage.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metaflaginfo.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metaflagtype.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metaiteminfo.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/metasiztociz.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/mse.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/mseall.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msedelist.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msedist.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/mseexchdates.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msenames.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msenasdin.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/mseshares.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msf.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msf_v2.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msfhdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msi.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/msiy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_agg_ann.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_agg_ann_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_agg_mth.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_agg_mth_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_agg_qtr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_agg_qtr_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_del.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_del_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_dind.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_dind_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_dis.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_dis_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_dp_dly.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_dp_dly_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_ds_dly.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_ds_dly_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_hdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_hdr_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_indhdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_indhdr_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_mdel.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_mdel_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_mind.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_mind_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_mth.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_mth_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_nam.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_nam_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_ndi.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_ndi_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_shr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/saz_shr_legacy.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkannsecuritydata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkdelists.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkdistributions.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkdlycumulativeadjfactor.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkdlysecuritydata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkdlysecurityprimarydata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkissuerinfohdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkissuerinfohist.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkmthcumulativeadjfactor.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkmthfloatshares.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkmthsecuritydata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkqtrsecuritydata.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stksecurityinfohdr.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stksecurityinfohist.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stkshares.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stocknames.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/stocknames_v2.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/wrds_dailyindexret_query.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/wrds_dsfv2_query.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/wrds_monthlyindexret_query.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/wrds_msfv2_query.parquet`
- `s3://<bucket>/wrds/crsp_a_stock/wrds_names_query.parquet`

### `wrds/crsp_q_mutualfunds/` (29 objects)

- `s3://<bucket>/wrds/crsp_q_mutualfunds/contact_info.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/crsp_cik_map.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/crsp_portno_map.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/daily_nav.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/daily_nav_ret.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/daily_returns.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/dividends.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/front_load.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/front_load_det.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/front_load_grp.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_fees.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_flows.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_hdr.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_hdr_hist.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_names.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_style.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_summary.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/fund_summary2.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/holdings.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/holdings_co_info.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/mfdbname.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/monthly_nav.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/monthly_returns.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/monthly_tna.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/monthly_tna_ret_nav.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/portnomap.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/rear_load.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/rear_load_det.parquet`
- `s3://<bucket>/wrds/crsp_q_mutualfunds/rear_load_grp.parquet`

### `wrds/trace_enhanced/` (14 objects)

- `s3://<bucket>/wrds/trace_enhanced/absmasterfile.parquet`
- `s3://<bucket>/wrds/trace_enhanced/camasterfile.parquet`
- `s3://<bucket>/wrds/trace_enhanced/cmomasterfile.parquet`
- `s3://<bucket>/wrds/trace_enhanced/mbsmasterfile.parquet`
- `s3://<bucket>/wrds/trace_enhanced/tbamasterfile.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_agency_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_btds144a_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_spds144a_abs_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_spds144a_cmo_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_spds_abs_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_spds_cmo_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_spds_mbs_enhanced.parquet`
- `s3://<bucket>/wrds/trace_enhanced/trace_spds_tba_enhanced.parquet`

### `wrds/trace_standard/` (23 objects)

- `s3://<bucket>/wrds/trace_standard/absmasterfile.parquet`
- `s3://<bucket>/wrds/trace_standard/camasterfile.parquet`
- `s3://<bucket>/wrds/trace_standard/cmomasterfile.parquet`
- `s3://<bucket>/wrds/trace_standard/mbsmasterfile.parquet`
- `s3://<bucket>/wrds/trace_standard/tbamasterfile.parquet`
- `s3://<bucket>/wrds/trace_standard/trace.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_agency.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_btds144a.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_spds144a_abs.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_spds144a_cmo.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_spds_abs.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_spds_cmo.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_spds_mbs.parquet`
- `s3://<bucket>/wrds/trace_standard/trace_spds_tba.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_agency.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_btds144a.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_spds144a_abs.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_spds144a_cmo.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_spds_abs.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_spds_cmo.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_spds_mbs.parquet`
- `s3://<bucket>/wrds/trace_standard/trade_summary_spds_tba.parquet`

### `wrds/ff_all/` (12 objects)

- `s3://<bucket>/wrds/ff_all/factors_china.parquet`
- `s3://<bucket>/wrds/ff_all/factors_daily.parquet`
- `s3://<bucket>/wrds/ff_all/factors_monthly.parquet`
- `s3://<bucket>/wrds/ff_all/fivefactors_daily.parquet`
- `s3://<bucket>/wrds/ff_all/fivefactors_monthly.parquet`
- `s3://<bucket>/wrds/ff_all/industry12.parquet`
- `s3://<bucket>/wrds/ff_all/industry48.parquet`
- `s3://<bucket>/wrds/ff_all/liq_ps.parquet`
- `s3://<bucket>/wrds/ff_all/liq_sadka.parquet`
- `s3://<bucket>/wrds/ff_all/portfolios.parquet`
- `s3://<bucket>/wrds/ff_all/portfolios25.parquet`
- `s3://<bucket>/wrds/ff_all/portfolios_d.parquet`

### `wrds/frb_all/` (4 objects)

- `s3://<bucket>/wrds/frb_all/fx_daily.parquet`
- `s3://<bucket>/wrds/frb_all/fx_monthly.parquet`
- `s3://<bucket>/wrds/frb_all/rates_daily.parquet`
- `s3://<bucket>/wrds/frb_all/rates_monthly.parquet`

### `options/SPY/tick/` (146 objects)

- `s3://<bucket>/options/SPY/tick/2014-06.parquet`
- `s3://<bucket>/options/SPY/tick/2014-07.parquet`
- `s3://<bucket>/options/SPY/tick/2014-08.parquet`
- `s3://<bucket>/options/SPY/tick/2014-09.parquet`
- `s3://<bucket>/options/SPY/tick/2014-10.parquet`
- `s3://<bucket>/options/SPY/tick/2014-11.parquet`
- `s3://<bucket>/options/SPY/tick/2014-12.parquet`
- `s3://<bucket>/options/SPY/tick/2015-01.parquet`
- `s3://<bucket>/options/SPY/tick/2015-02.parquet`
- `s3://<bucket>/options/SPY/tick/2015-03.parquet`
- `s3://<bucket>/options/SPY/tick/2015-04.parquet`
- `s3://<bucket>/options/SPY/tick/2015-05.parquet`
- `s3://<bucket>/options/SPY/tick/2015-06.parquet`
- `s3://<bucket>/options/SPY/tick/2015-07.parquet`
- `s3://<bucket>/options/SPY/tick/2015-08.parquet`
- `s3://<bucket>/options/SPY/tick/2015-09.parquet`
- `s3://<bucket>/options/SPY/tick/2015-10.parquet`
- `s3://<bucket>/options/SPY/tick/2015-11.parquet`
- `s3://<bucket>/options/SPY/tick/2015-12.parquet`
- `s3://<bucket>/options/SPY/tick/2016-01.parquet`
- `s3://<bucket>/options/SPY/tick/2016-02.parquet`
- `s3://<bucket>/options/SPY/tick/2016-03.parquet`
- `s3://<bucket>/options/SPY/tick/2016-04.parquet`
- `s3://<bucket>/options/SPY/tick/2016-05.parquet`
- `s3://<bucket>/options/SPY/tick/2016-06.parquet`
- `s3://<bucket>/options/SPY/tick/2016-07.parquet`
- `s3://<bucket>/options/SPY/tick/2016-08.parquet`
- `s3://<bucket>/options/SPY/tick/2016-09.parquet`
- `s3://<bucket>/options/SPY/tick/2016-10.parquet`
- `s3://<bucket>/options/SPY/tick/2016-11.parquet`
- `s3://<bucket>/options/SPY/tick/2016-12.parquet`
- `s3://<bucket>/options/SPY/tick/2017-01.parquet`
- `s3://<bucket>/options/SPY/tick/2017-02.parquet`
- `s3://<bucket>/options/SPY/tick/2017-03.parquet`
- `s3://<bucket>/options/SPY/tick/2017-04.parquet`
- `s3://<bucket>/options/SPY/tick/2017-05.parquet`
- `s3://<bucket>/options/SPY/tick/2017-06.parquet`
- `s3://<bucket>/options/SPY/tick/2017-07.parquet`
- `s3://<bucket>/options/SPY/tick/2017-08.parquet`
- `s3://<bucket>/options/SPY/tick/2017-09.parquet`
- `s3://<bucket>/options/SPY/tick/2017-10.parquet`
- `s3://<bucket>/options/SPY/tick/2017-11.parquet`
- `s3://<bucket>/options/SPY/tick/2017-12.parquet`
- `s3://<bucket>/options/SPY/tick/2018-01.parquet`
- `s3://<bucket>/options/SPY/tick/2018-02.parquet`
- `s3://<bucket>/options/SPY/tick/2018-03.parquet`
- `s3://<bucket>/options/SPY/tick/2018-04.parquet`
- `s3://<bucket>/options/SPY/tick/2018-05.parquet`
- `s3://<bucket>/options/SPY/tick/2018-06.parquet`
- `s3://<bucket>/options/SPY/tick/2018-07.parquet`
- `s3://<bucket>/options/SPY/tick/2018-08.parquet`
- `s3://<bucket>/options/SPY/tick/2018-09.parquet`
- `s3://<bucket>/options/SPY/tick/2018-10.parquet`
- `s3://<bucket>/options/SPY/tick/2018-11.parquet`
- `s3://<bucket>/options/SPY/tick/2018-12.parquet`
- `s3://<bucket>/options/SPY/tick/2019-01.parquet`
- `s3://<bucket>/options/SPY/tick/2019-02.parquet`
- `s3://<bucket>/options/SPY/tick/2019-03.parquet`
- `s3://<bucket>/options/SPY/tick/2019-04.parquet`
- `s3://<bucket>/options/SPY/tick/2019-05.parquet`
- `s3://<bucket>/options/SPY/tick/2019-06.parquet`
- `s3://<bucket>/options/SPY/tick/2019-07.parquet`
- `s3://<bucket>/options/SPY/tick/2019-08.parquet`
- `s3://<bucket>/options/SPY/tick/2019-09.parquet`
- `s3://<bucket>/options/SPY/tick/2019-10.parquet`
- `s3://<bucket>/options/SPY/tick/2019-11.parquet`
- `s3://<bucket>/options/SPY/tick/2019-12.parquet`
- `s3://<bucket>/options/SPY/tick/2020-01.parquet`
- `s3://<bucket>/options/SPY/tick/2020-02.parquet`
- `s3://<bucket>/options/SPY/tick/2020-03.parquet`
- `s3://<bucket>/options/SPY/tick/2020-04.parquet`
- `s3://<bucket>/options/SPY/tick/2020-05.parquet`
- `s3://<bucket>/options/SPY/tick/2020-06.parquet`
- `s3://<bucket>/options/SPY/tick/2020-07.parquet`
- `s3://<bucket>/options/SPY/tick/2020-08.parquet`
- `s3://<bucket>/options/SPY/tick/2020-09.parquet`
- `s3://<bucket>/options/SPY/tick/2020-10.parquet`
- `s3://<bucket>/options/SPY/tick/2020-11.parquet`
- `s3://<bucket>/options/SPY/tick/2020-12.parquet`
- `s3://<bucket>/options/SPY/tick/2021-01.parquet`
- `s3://<bucket>/options/SPY/tick/2021-02.parquet`
- `s3://<bucket>/options/SPY/tick/2021-03.parquet`
- `s3://<bucket>/options/SPY/tick/2021-04.parquet`
- `s3://<bucket>/options/SPY/tick/2021-05.parquet`
- `s3://<bucket>/options/SPY/tick/2021-06.parquet`
- `s3://<bucket>/options/SPY/tick/2021-07.parquet`
- `s3://<bucket>/options/SPY/tick/2021-08.parquet`
- `s3://<bucket>/options/SPY/tick/2021-09.parquet`
- `s3://<bucket>/options/SPY/tick/2021-10.parquet`
- `s3://<bucket>/options/SPY/tick/2021-11.parquet`
- `s3://<bucket>/options/SPY/tick/2021-12.parquet`
- `s3://<bucket>/options/SPY/tick/2022-01.parquet`
- `s3://<bucket>/options/SPY/tick/2022-02.parquet`
- `s3://<bucket>/options/SPY/tick/2022-03.parquet`
- `s3://<bucket>/options/SPY/tick/2022-04.parquet`
- `s3://<bucket>/options/SPY/tick/2022-05.parquet`
- `s3://<bucket>/options/SPY/tick/2022-06.parquet`
- `s3://<bucket>/options/SPY/tick/2022-07.parquet`
- `s3://<bucket>/options/SPY/tick/2022-08.parquet`
- `s3://<bucket>/options/SPY/tick/2022-09.parquet`
- `s3://<bucket>/options/SPY/tick/2022-10.parquet`
- `s3://<bucket>/options/SPY/tick/2022-11.parquet`
- `s3://<bucket>/options/SPY/tick/2022-12.parquet`
- `s3://<bucket>/options/SPY/tick/2023-01.parquet`
- `s3://<bucket>/options/SPY/tick/2023-02.parquet`
- `s3://<bucket>/options/SPY/tick/2023-03.parquet`
- `s3://<bucket>/options/SPY/tick/2023-04.parquet`
- `s3://<bucket>/options/SPY/tick/2023-05.parquet`
- `s3://<bucket>/options/SPY/tick/2023-06.parquet`
- `s3://<bucket>/options/SPY/tick/2023-07.parquet`
- `s3://<bucket>/options/SPY/tick/2023-08.parquet`
- `s3://<bucket>/options/SPY/tick/2023-09.parquet`
- `s3://<bucket>/options/SPY/tick/2023-10.parquet`
- `s3://<bucket>/options/SPY/tick/2023-11.parquet`
- `s3://<bucket>/options/SPY/tick/2023-12.parquet`
- `s3://<bucket>/options/SPY/tick/2024-01.parquet`
- `s3://<bucket>/options/SPY/tick/2024-02.parquet`
- `s3://<bucket>/options/SPY/tick/2024-03.parquet`
- `s3://<bucket>/options/SPY/tick/2024-04.parquet`
- `s3://<bucket>/options/SPY/tick/2024-05.parquet`
- `s3://<bucket>/options/SPY/tick/2024-06.parquet`
- `s3://<bucket>/options/SPY/tick/2024-07.parquet`
- `s3://<bucket>/options/SPY/tick/2024-08.parquet`
- `s3://<bucket>/options/SPY/tick/2024-09.parquet`
- `s3://<bucket>/options/SPY/tick/2024-10.parquet`
- `s3://<bucket>/options/SPY/tick/2024-11.parquet`
- `s3://<bucket>/options/SPY/tick/2024-12.parquet`
- `s3://<bucket>/options/SPY/tick/2025-01.parquet`
- `s3://<bucket>/options/SPY/tick/2025-02.parquet`
- `s3://<bucket>/options/SPY/tick/2025-03.parquet`
- `s3://<bucket>/options/SPY/tick/2025-04.parquet`
- `s3://<bucket>/options/SPY/tick/2025-05.parquet`
- `s3://<bucket>/options/SPY/tick/2025-06.parquet`
- `s3://<bucket>/options/SPY/tick/2025-07.parquet`
- `s3://<bucket>/options/SPY/tick/2025-08.parquet`
- `s3://<bucket>/options/SPY/tick/2025-09.parquet`
- `s3://<bucket>/options/SPY/tick/2025-10.parquet`
- `s3://<bucket>/options/SPY/tick/2025-11.parquet`
- `s3://<bucket>/options/SPY/tick/2025-12.parquet`
- `s3://<bucket>/options/SPY/tick/2026-01.parquet`
- `s3://<bucket>/options/SPY/tick/2026-02.parquet`
- `s3://<bucket>/options/SPY/tick/2026-03.parquet`
- `s3://<bucket>/options/SPY/tick/2026-04.parquet`
- `s3://<bucket>/options/SPY/tick/2026-05.parquet`
- `s3://<bucket>/options/SPY/tick/2026-06.parquet`
- `s3://<bucket>/options/SPY/tick/2026-07.parquet`

### `options/QQQ/tick/` (146 objects)

- `s3://<bucket>/options/QQQ/tick/2014-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2014-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2014-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2014-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2014-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2014-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2014-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2015-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2016-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2017-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2018-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2019-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2020-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2021-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2022-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2023-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2024-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-07.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-08.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-09.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-10.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-11.parquet`
- `s3://<bucket>/options/QQQ/tick/2025-12.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-01.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-02.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-03.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-04.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-05.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-06.parquet`
- `s3://<bucket>/options/QQQ/tick/2026-07.parquet`

### `options/TLT/tick/` (33 objects)

- `s3://<bucket>/options/TLT/tick/2023-11.parquet`
- `s3://<bucket>/options/TLT/tick/2023-12.parquet`
- `s3://<bucket>/options/TLT/tick/2024-01.parquet`
- `s3://<bucket>/options/TLT/tick/2024-02.parquet`
- `s3://<bucket>/options/TLT/tick/2024-03.parquet`
- `s3://<bucket>/options/TLT/tick/2024-04.parquet`
- `s3://<bucket>/options/TLT/tick/2024-05.parquet`
- `s3://<bucket>/options/TLT/tick/2024-06.parquet`
- `s3://<bucket>/options/TLT/tick/2024-07.parquet`
- `s3://<bucket>/options/TLT/tick/2024-08.parquet`
- `s3://<bucket>/options/TLT/tick/2024-09.parquet`
- `s3://<bucket>/options/TLT/tick/2024-10.parquet`
- `s3://<bucket>/options/TLT/tick/2024-11.parquet`
- `s3://<bucket>/options/TLT/tick/2024-12.parquet`
- `s3://<bucket>/options/TLT/tick/2025-01.parquet`
- `s3://<bucket>/options/TLT/tick/2025-02.parquet`
- `s3://<bucket>/options/TLT/tick/2025-03.parquet`
- `s3://<bucket>/options/TLT/tick/2025-04.parquet`
- `s3://<bucket>/options/TLT/tick/2025-05.parquet`
- `s3://<bucket>/options/TLT/tick/2025-06.parquet`
- `s3://<bucket>/options/TLT/tick/2025-07.parquet`
- `s3://<bucket>/options/TLT/tick/2025-08.parquet`
- `s3://<bucket>/options/TLT/tick/2025-09.parquet`
- `s3://<bucket>/options/TLT/tick/2025-10.parquet`
- `s3://<bucket>/options/TLT/tick/2025-11.parquet`
- `s3://<bucket>/options/TLT/tick/2025-12.parquet`
- `s3://<bucket>/options/TLT/tick/2026-01.parquet`
- `s3://<bucket>/options/TLT/tick/2026-02.parquet`
- `s3://<bucket>/options/TLT/tick/2026-03.parquet`
- `s3://<bucket>/options/TLT/tick/2026-04.parquet`
- `s3://<bucket>/options/TLT/tick/2026-05.parquet`
- `s3://<bucket>/options/TLT/tick/2026-06.parquet`
- `s3://<bucket>/options/TLT/tick/2026-07.parquet`

### `options/IWM/tick/` (34 objects)

- `s3://<bucket>/options/IWM/tick/2023-10.parquet`
- `s3://<bucket>/options/IWM/tick/2023-11.parquet`
- `s3://<bucket>/options/IWM/tick/2023-12.parquet`
- `s3://<bucket>/options/IWM/tick/2024-01.parquet`
- `s3://<bucket>/options/IWM/tick/2024-02.parquet`
- `s3://<bucket>/options/IWM/tick/2024-03.parquet`
- `s3://<bucket>/options/IWM/tick/2024-04.parquet`
- `s3://<bucket>/options/IWM/tick/2024-05.parquet`
- `s3://<bucket>/options/IWM/tick/2024-06.parquet`
- `s3://<bucket>/options/IWM/tick/2024-07.parquet`
- `s3://<bucket>/options/IWM/tick/2024-08.parquet`
- `s3://<bucket>/options/IWM/tick/2024-09.parquet`
- `s3://<bucket>/options/IWM/tick/2024-10.parquet`
- `s3://<bucket>/options/IWM/tick/2024-11.parquet`
- `s3://<bucket>/options/IWM/tick/2024-12.parquet`
- `s3://<bucket>/options/IWM/tick/2025-01.parquet`
- `s3://<bucket>/options/IWM/tick/2025-02.parquet`
- `s3://<bucket>/options/IWM/tick/2025-03.parquet`
- `s3://<bucket>/options/IWM/tick/2025-04.parquet`
- `s3://<bucket>/options/IWM/tick/2025-05.parquet`
- `s3://<bucket>/options/IWM/tick/2025-06.parquet`
- `s3://<bucket>/options/IWM/tick/2025-07.parquet`
- `s3://<bucket>/options/IWM/tick/2025-08.parquet`
- `s3://<bucket>/options/IWM/tick/2025-09.parquet`
- `s3://<bucket>/options/IWM/tick/2025-10.parquet`
- `s3://<bucket>/options/IWM/tick/2025-11.parquet`
- `s3://<bucket>/options/IWM/tick/2025-12.parquet`
- `s3://<bucket>/options/IWM/tick/2026-01.parquet`
- `s3://<bucket>/options/IWM/tick/2026-02.parquet`
- `s3://<bucket>/options/IWM/tick/2026-03.parquet`
- `s3://<bucket>/options/IWM/tick/2026-04.parquet`
- `s3://<bucket>/options/IWM/tick/2026-05.parquet`
- `s3://<bucket>/options/IWM/tick/2026-06.parquet`
- `s3://<bucket>/options/IWM/tick/2026-07.parquet`

### `options/GLD/tick/` (34 objects)

- `s3://<bucket>/options/GLD/tick/2023-10.parquet`
- `s3://<bucket>/options/GLD/tick/2023-11.parquet`
- `s3://<bucket>/options/GLD/tick/2023-12.parquet`
- `s3://<bucket>/options/GLD/tick/2024-01.parquet`
- `s3://<bucket>/options/GLD/tick/2024-02.parquet`
- `s3://<bucket>/options/GLD/tick/2024-03.parquet`
- `s3://<bucket>/options/GLD/tick/2024-04.parquet`
- `s3://<bucket>/options/GLD/tick/2024-05.parquet`
- `s3://<bucket>/options/GLD/tick/2024-06.parquet`
- `s3://<bucket>/options/GLD/tick/2024-07.parquet`
- `s3://<bucket>/options/GLD/tick/2024-08.parquet`
- `s3://<bucket>/options/GLD/tick/2024-09.parquet`
- `s3://<bucket>/options/GLD/tick/2024-10.parquet`
- `s3://<bucket>/options/GLD/tick/2024-11.parquet`
- `s3://<bucket>/options/GLD/tick/2024-12.parquet`
- `s3://<bucket>/options/GLD/tick/2025-01.parquet`
- `s3://<bucket>/options/GLD/tick/2025-02.parquet`
- `s3://<bucket>/options/GLD/tick/2025-03.parquet`
- `s3://<bucket>/options/GLD/tick/2025-04.parquet`
- `s3://<bucket>/options/GLD/tick/2025-05.parquet`
- `s3://<bucket>/options/GLD/tick/2025-06.parquet`
- `s3://<bucket>/options/GLD/tick/2025-07.parquet`
- `s3://<bucket>/options/GLD/tick/2025-08.parquet`
- `s3://<bucket>/options/GLD/tick/2025-09.parquet`
- `s3://<bucket>/options/GLD/tick/2025-10.parquet`
- `s3://<bucket>/options/GLD/tick/2025-11.parquet`
- `s3://<bucket>/options/GLD/tick/2025-12.parquet`
- `s3://<bucket>/options/GLD/tick/2026-01.parquet`
- `s3://<bucket>/options/GLD/tick/2026-02.parquet`
- `s3://<bucket>/options/GLD/tick/2026-03.parquet`
- `s3://<bucket>/options/GLD/tick/2026-04.parquet`
- `s3://<bucket>/options/GLD/tick/2026-05.parquet`
- `s3://<bucket>/options/GLD/tick/2026-06.parquet`
- `s3://<bucket>/options/GLD/tick/2026-07.parquet`

### `options/SLV/tick/` (34 objects)

- `s3://<bucket>/options/SLV/tick/2023-10.parquet`
- `s3://<bucket>/options/SLV/tick/2023-11.parquet`
- `s3://<bucket>/options/SLV/tick/2023-12.parquet`
- `s3://<bucket>/options/SLV/tick/2024-01.parquet`
- `s3://<bucket>/options/SLV/tick/2024-02.parquet`
- `s3://<bucket>/options/SLV/tick/2024-03.parquet`
- `s3://<bucket>/options/SLV/tick/2024-04.parquet`
- `s3://<bucket>/options/SLV/tick/2024-05.parquet`
- `s3://<bucket>/options/SLV/tick/2024-06.parquet`
- `s3://<bucket>/options/SLV/tick/2024-07.parquet`
- `s3://<bucket>/options/SLV/tick/2024-08.parquet`
- `s3://<bucket>/options/SLV/tick/2024-09.parquet`
- `s3://<bucket>/options/SLV/tick/2024-10.parquet`
- `s3://<bucket>/options/SLV/tick/2024-11.parquet`
- `s3://<bucket>/options/SLV/tick/2024-12.parquet`
- `s3://<bucket>/options/SLV/tick/2025-01.parquet`
- `s3://<bucket>/options/SLV/tick/2025-02.parquet`
- `s3://<bucket>/options/SLV/tick/2025-03.parquet`
- `s3://<bucket>/options/SLV/tick/2025-04.parquet`
- `s3://<bucket>/options/SLV/tick/2025-05.parquet`
- `s3://<bucket>/options/SLV/tick/2025-06.parquet`
- `s3://<bucket>/options/SLV/tick/2025-07.parquet`
- `s3://<bucket>/options/SLV/tick/2025-08.parquet`
- `s3://<bucket>/options/SLV/tick/2025-09.parquet`
- `s3://<bucket>/options/SLV/tick/2025-10.parquet`
- `s3://<bucket>/options/SLV/tick/2025-11.parquet`
- `s3://<bucket>/options/SLV/tick/2025-12.parquet`
- `s3://<bucket>/options/SLV/tick/2026-01.parquet`
- `s3://<bucket>/options/SLV/tick/2026-02.parquet`
- `s3://<bucket>/options/SLV/tick/2026-03.parquet`
- `s3://<bucket>/options/SLV/tick/2026-04.parquet`
- `s3://<bucket>/options/SLV/tick/2026-05.parquet`
- `s3://<bucket>/options/SLV/tick/2026-06.parquet`
- `s3://<bucket>/options/SLV/tick/2026-07.parquet`

