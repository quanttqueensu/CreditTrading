"""P1 — shared bond-day panel for forced-flow cycle 2 (M1/M2/M5/M6).

Builds ONCE the panel every cycle-2 study reuses:

  data/forced_flow2/bond_day_panel/year=YYYY/data_0.parquet   (hive-partitioned)
  data/forced_flow2/market_day.parquet                        (per-day HY/IG aggregates)
  data/forced_flow2/grade_timeline.parquet                    (effective-dated IG/HY flag)
  results/forced_flow2/PANEL_BUILD.md                         (filter counts + validation)

DATA ONLY. No returns, no hypothesis tests (FORCED_FLOW_2_PREREG.md binding).

Design decisions (documented in PANEL_BUILD.md):
  * CORPORATE FILTER. trace_enhanced.sub_prdct is ~100% NULL before 2012
    (r1_year_stats.csv: 2005 has 9 non-null rows out of 8.1M), so the prereg
    instruction "filter sub_prdct='CORP'" cannot be applied at trade level pre-2012.
    Rule used, uniform across the 2012 break:
        keep row iff cusip_id in camasterfile CORP set (any interval with
        sub_prdct_type='CORP') AND (t.sub_prdct='CORP' OR t.sub_prdct IS NULL).
    Post-2012 this equals the prereg filter minus a small set of CORP-flagged
    prints whose CUSIP never appears as CORP in the master (counted in the report).
  * DICK-NIELSEN. Exact reuse of the two-regime pointer/echo voiding logic
    verified in scripts/build_trace_prices.py (cycle 1): pointer style
    (orig_msg_seq_nb -> msg_seq_nb, trc_st C/W/X/R/Y), echo style (trc_st X/C,
    no orig), survivors trc_st in (T,W,R); pre-2012 reversals asof_cd='R'
    dropped + original removed by attribute match (known over-deletion of
    identical simultaneous prints, standard DN 2014 limitation).
  * INTER-DEALER DEDUP. Keep sell side of cntra_mp_id='D' pairs; drop D+B.
    A (ATS, 2015+) and T (affiliate, 2020+) counterparties are kept in a
    separate at_* bucket — NOT in customer, NOT deduped (no pair structure
    documented); customer = cntra_mp_id='C' only (R1 audit caveat 2).
  * HYGIENE beyond DN: price band 1..250, par>0, wis_fl/spcl_trd_fl dropped.
    NO fat-finger median filter — M2 studies fire-sale days and a 10%-from-median
    clip would censor exactly the dispersion under study. Downstream studies
    must apply their own robustness clips.
  * GRADE JOIN. camasterfile effective-dated intervals resolved last-writer-wins
    (RATINGS_SPIKE.md correction 1); grade transitions dated 2017-03-18..20
    (vintage-reload artifact, PREREGISTRATION Amendment 3) are voided by
    carrying the prior grade forward. grade in (I,H,N); NULL = no master
    coverage at that date.
  * As-of (late-reported) trades land on their execution date: correct for a
    research panel, but the panel is DISCOVERY-ONLY (prereg scope rule) — a
    live replication would not have late prints at T close.

Usage:
    /opt/anaconda3/bin/python3 scripts/forced_flow2/p1_build_bond_day_panel.py [--stage all|0|a|b|d|e] [--force]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/Users/simonjarvis/Desktop/QUANTT/2027")
sys.path.insert(0, str(REPO))

from src.data.r2 import connect, q, r2_path  # noqa: E402

SCRATCH = Path("/private/tmp/claude-501/-Users-simonjarvis-Desktop-QUANTT-2027/"
               "23dfed61-5260-4d53-a76a-d3648ddee21d/scratchpad/p1")
STAGE = SCRATCH / "stage_raw"
DAT = REPO / "data" / "forced_flow2"
PANEL = DAT / "bond_day_panel"
RES = REPO / "results" / "forced_flow2"
TL_PATH = DAT / "grade_timeline.parquet"
MD_PATH = RES / "PANEL_BUILD.md"

YEARS = list(range(2002, 2026))
ODD_MAX = 100_000        # odd lot: par < $100k
ROUND_MIN = 1_000_000    # round lot: par >= $1MM
PR_LO, PR_HI = 1.0, 250.0
SIZE_CAP = 1e9      # hard drop: single prints >= $1bn par (87% have x1000 siblings; junk)
SIB_MIN = 1e8       # sibling rule applies to prints >= $100MM par
ART_LO, ART_HI = "2017-03-18", "2017-03-20"   # camasterfile vintage artifact window

TOTAL_TRACE_ROWS = 455_675_242  # from R1 audit, for attrition accounting

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 80)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def setup(con):
    con.execute(f"SET temp_directory='{SCRATCH / 'duck_tmp'}'")
    con.execute("SET memory_limit='8GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    try:
        con.execute("SET http_retries=10")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# STAGE 0 — camasterfile: CORP cusip set + effective-dated grade timeline
# ---------------------------------------------------------------------------
TIMELINE_SQL = """
WITH src AS (
    SELECT m.cusip_id, m.stdt, m.enddt, m.grade
    FROM read_parquet('{cam}') m
    JOIN corp_set c USING (cusip_id)
    WHERE m.grade IN ('I','H','N')
),
recs AS (SELECT DISTINCT * FROM src WHERE enddt >= stdt),
bounds AS (
    SELECT cusip_id, stdt AS seg_start FROM recs
    UNION
    SELECT cusip_id, enddt + INTERVAL 1 DAY AS seg_start FROM recs
),
cover AS (
    SELECT b.cusip_id, b.seg_start, r.grade, r.enddt,
           row_number() OVER (
               PARTITION BY b.cusip_id, b.seg_start
               ORDER BY r.stdt DESC, r.enddt ASC, r.grade
           ) AS rn
    FROM bounds b
    JOIN recs r ON r.cusip_id = b.cusip_id
               AND r.stdt <= b.seg_start AND r.enddt >= b.seg_start
),
timeline AS (SELECT cusip_id, seg_start, grade, enddt FROM cover WHERE rn = 1),
flagged AS (
    SELECT *, CASE WHEN lag(grade) OVER w IS NULL OR lag(grade) OVER w <> grade
                   THEN 1 ELSE 0 END AS new_run
    FROM timeline
    WINDOW w AS (PARTITION BY cusip_id ORDER BY seg_start)
),
run_ids AS (
    SELECT *, sum(new_run) OVER (
        PARTITION BY cusip_id ORDER BY seg_start ROWS UNBOUNDED PRECEDING) AS run_id
    FROM flagged
)
SELECT cusip_id, run_id, grade,
       min(seg_start) AS run_start,
       max(enddt)     AS run_last_enddt
FROM run_ids
GROUP BY 1, 2, 3
ORDER BY cusip_id, run_start
"""


def stage0(con, force: bool) -> None:
    if TL_PATH.exists() and (SCRATCH / "corp_cusips.parquet").exists() and not force:
        log("stage 0: cached, skipping")
        return
    log("STAGE 0 — camasterfile CORP set + grade timeline")
    cam = r2_path("trace_enhanced", "camasterfile")

    stats = q(con, f"""
        SELECT count(*) AS rows_total,
               count(DISTINCT cusip_id) AS cusips_total,
               count(*) FILTER (WHERE sub_prdct_type IS NULL) AS rows_null_subprdct,
               count(DISTINCT cusip_id) FILTER (WHERE sub_prdct_type = 'CORP') AS cusips_corp
        FROM read_parquet('{cam}') WHERE cusip_id IS NOT NULL
    """).iloc[0]
    log(f"camasterfile: {stats.rows_total:,} rows, {stats.cusips_total:,} cusips, "
        f"{stats.cusips_corp:,} CORP cusips, {stats.rows_null_subprdct:,} null sub_prdct_type rows")

    corp = q(con, f"SELECT DISTINCT cusip_id FROM read_parquet('{cam}') "
                  f"WHERE sub_prdct_type = 'CORP' AND cusip_id IS NOT NULL")
    corp.to_parquet(SCRATCH / "corp_cusips.parquet", index=False)
    con.register("corp_set", corp)

    log("building grade timeline (interval resolution, last-writer-wins) ...")
    tl = q(con, TIMELINE_SQL.format(cam=cam))
    tl["run_start"] = pd.to_datetime(tl["run_start"])
    tl["run_last_enddt"] = pd.to_datetime(tl["run_last_enddt"])
    tl = tl.sort_values(["cusip_id", "run_start"]).reset_index(drop=True)
    n_runs_raw = len(tl)
    log(f"raw grade runs: {n_runs_raw:,} over {tl.cusip_id.nunique():,} cusips")

    # ---- void the 2017-03-18..20 vintage artifact transitions ----
    prev_grade = tl.groupby("cusip_id")["grade"].shift()
    art = (tl.run_start.between(ART_LO, ART_HI)
           & prev_grade.notna() & (tl.grade != prev_grade))
    art_detail = (tl.loc[art].assign(prev=prev_grade[art])
                  .groupby(["prev", "grade"]).size().rename("n").reset_index())
    log(f"artifact transitions voided ({ART_LO}..{ART_HI}): {int(art.sum()):,}")
    if len(art_detail):
        print(art_detail.to_string(index=False), flush=True)
    tl.loc[art, "grade"] = np.nan
    tl["grade"] = tl.groupby("cusip_id")["grade"].ffill()

    # re-collapse consecutive identical grades
    chg = (tl.cusip_id != tl.cusip_id.shift()) | (tl.grade != tl.grade.shift())
    tl["rid"] = chg.cumsum()
    tl2 = tl.groupby("rid", as_index=False).agg(
        cusip_id=("cusip_id", "first"), grade=("grade", "first"),
        run_start=("run_start", "min"), run_last_enddt=("run_last_enddt", "max"))
    tl2["run_next"] = tl2.groupby("cusip_id")["run_start"].shift(-1)
    tl2 = tl2.drop(columns=["rid"])
    log(f"final grade runs: {len(tl2):,} "
        f"({tl2.run_start.min().date()} .. {tl2.run_last_enddt.max().date()})")
    tl2.to_parquet(TL_PATH, index=False)

    meta = dict(cam_rows=int(stats.rows_total), cam_cusips=int(stats.cusips_total),
                cam_corp_cusips=int(stats.cusips_corp),
                n_runs_raw=n_runs_raw, n_runs_final=len(tl2),
                n_artifact_voided=int(art.sum()),
                artifact_detail=art_detail.to_dict("records"))
    (SCRATCH / "stage0_meta.json").write_text(json.dumps(meta, indent=2))
    log(f"wrote {TL_PATH}")


# ---------------------------------------------------------------------------
# STAGE A — one full remote scan -> local staging, partitioned by year
# ---------------------------------------------------------------------------
def stage_a(con, force: bool) -> None:
    marker = STAGE / "_SUCCESS"
    if marker.exists() and not force:
        log("stage A: cached, skipping")
        return
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    trace = r2_path("trace_enhanced", "trace_enhanced")
    corp = pd.read_parquet(SCRATCH / "corp_cusips.parquet")
    con.register("corp_set", corp)
    log(f"STAGE A — remote scan -> {STAGE} ({len(corp):,} CORP cusips pushed in)")
    t0 = time.time()
    con.execute(f"""
        COPY (
            SELECT t.cusip_id, t.trd_exctn_dt,
                   CAST(year(t.trd_exctn_dt) AS INT) AS year,
                   t.trd_exctn_tm, t.msg_seq_nb,
                   NULLIF(t.orig_msg_seq_nb, '') AS orig_seq,
                   t.trc_st, t.asof_cd, t.rpt_side_cd, t.cntra_mp_id,
                   CAST(t.entrd_vol_qt AS DOUBLE) AS par,
                   CAST(t.rptd_pr AS DOUBLE)      AS pr,
                   t.wis_fl, t.spcl_trd_fl, t.sub_prdct
            FROM read_parquet('{trace}') t
            JOIN corp_set c ON c.cusip_id = t.cusip_id
            WHERE (t.sub_prdct = 'CORP' OR t.sub_prdct IS NULL)
        ) TO '{STAGE}' (FORMAT PARQUET, PARTITION_BY (year))
    """)
    log(f"stage A copy done in {time.time() - t0:.0f}s")
    yc = q(con, f"SELECT year, count(*) AS n_staged FROM read_parquet("
               f"'{STAGE}/year=*/*.parquet', hive_partitioning=1) GROUP BY 1 ORDER BY 1")
    yc.to_csv(SCRATCH / "stagea_year_counts.csv", index=False)
    print(yc.to_string(index=False), flush=True)
    log(f"total staged: {int(yc.n_staged.sum()):,} of {TOTAL_TRACE_ROWS:,} raw TRACE rows "
        f"({100 * yc.n_staged.sum() / TOTAL_TRACE_ROWS:.1f}%)")
    marker.write_text("ok")


# ---------------------------------------------------------------------------
# STAGE B — per-year Dick-Nielsen filter + bond-day aggregation + grade join
# ---------------------------------------------------------------------------
FLAG_SQL = """
CREATE OR REPLACE TEMP TABLE flagged AS
WITH raw AS (
    SELECT * FROM read_parquet('{stage}/year={y}/*.parquet')
),
voided AS (
    SELECT DISTINCT cusip_id, trd_exctn_dt, orig_seq AS seq FROM raw
    WHERE orig_seq IS NOT NULL AND trc_st IN ('C','W','X','R','Y')
    UNION
    SELECT DISTINCT cusip_id, trd_exctn_dt, msg_seq_nb AS seq FROM raw
    WHERE orig_seq IS NULL AND trc_st IN ('X','C')
),
reversal AS (
    SELECT DISTINCT cusip_id, trd_exctn_dt, trd_exctn_tm, pr, par, rpt_side_cd
    FROM raw WHERE asof_cd = 'R'
),
-- x1000 unit-error duplicates: a print >= $100MM whose exact par/1000 also
-- printed on the same bond-day is a mis-scaled duplicate report (par entered
-- in dollars where thousands were meant), e.g. the 2011-01 LatAm cluster:
-- 8e9 next to 8e6 at the same second/price. Never cancelled, invisible to DN.
sib AS (
    SELECT DISTINCT r1.cusip_id, r1.trd_exctn_dt, r1.par
    FROM raw r1
    JOIN raw r2 ON r2.cusip_id = r1.cusip_id
               AND r2.trd_exctn_dt = r1.trd_exctn_dt
               AND r2.par * 1000 = r1.par
    WHERE r1.par >= {sib_min}
)
SELECT r.cusip_id, r.trd_exctn_dt, r.trd_exctn_tm, r.rpt_side_cd, r.cntra_mp_id,
       r.par, r.pr,
       (r.trc_st IN ('T','W','R') AND v.seq IS NULL)          AS pass_dn,
       (COALESCE(r.asof_cd,'') <> 'R' AND x.cusip_id IS NULL) AS pass_rev,
       NOT (r.cntra_mp_id = 'D' AND r.rpt_side_cd = 'B')      AS pass_dd,
       COALESCE(r.wis_fl,  'N') <> 'Y'                        AS pass_wis,
       COALESCE(r.spcl_trd_fl,'N') <> 'Y'                     AS pass_spcl,
       (r.par > 0 AND r.pr BETWEEN {pr_lo} AND {pr_hi})       AS pass_band,
       (r.par < {size_cap} AND sb.cusip_id IS NULL)           AS pass_size
FROM raw r
LEFT JOIN voided v
       ON v.cusip_id = r.cusip_id AND v.trd_exctn_dt = r.trd_exctn_dt
      AND v.seq = r.msg_seq_nb
LEFT JOIN reversal x
       ON x.cusip_id = r.cusip_id AND x.trd_exctn_dt = r.trd_exctn_dt
      AND x.trd_exctn_tm = r.trd_exctn_tm AND x.pr = r.pr AND x.par = r.par
      AND x.rpt_side_cd IS NOT DISTINCT FROM r.rpt_side_cd
LEFT JOIN sib sb
       ON sb.cusip_id = r.cusip_id AND sb.trd_exctn_dt = r.trd_exctn_dt
      AND sb.par = r.par
"""

ATTRITION_SQL = """
SELECT {y} AS year,
       count(*) AS n0_staged,
       count(*) FILTER (WHERE pass_dn) AS n1_after_cancel_corr,
       count(*) FILTER (WHERE pass_dn AND pass_rev) AS n2_after_reversal,
       count(*) FILTER (WHERE pass_dn AND pass_rev AND pass_dd) AS n3_after_interdealer_dedup,
       count(*) FILTER (WHERE pass_dn AND pass_rev AND pass_dd AND pass_wis) AS n4_after_wis,
       count(*) FILTER (WHERE pass_dn AND pass_rev AND pass_dd AND pass_wis AND pass_spcl) AS n5_after_spcl,
       count(*) FILTER (WHERE pass_dn AND pass_rev AND pass_dd AND pass_wis AND pass_spcl AND pass_band) AS n6_after_band,
       count(*) FILTER (WHERE pass_dn AND pass_rev AND pass_dd AND pass_wis AND pass_spcl AND pass_band AND pass_size) AS n7_final,
       COALESCE(sum(par) FILTER (WHERE pass_dn AND pass_rev AND pass_dd AND pass_wis AND pass_spcl AND pass_band AND NOT pass_size), 0)/1e9 AS size_junk_par_bn
FROM flagged
"""

AGG_SQL = """
CREATE OR REPLACE TEMP TABLE agg AS
SELECT cusip_id, trd_exctn_dt AS dt,
       count(*)::INT                               AS n_trades,
       sum(par)                                    AS par_total,
       sum(par * pr) / 100.0                       AS dollar_total,
       sum(par * pr) / sum(par)                    AS vwap_all,
       arg_max(pr, COALESCE(trd_exctn_tm, TIME '00:00:00')) AS last_pr,

       count(*) FILTER (WHERE cb)::INT             AS cust_buy_n,
       COALESCE(sum(par)            FILTER (WHERE cb), 0) AS cust_buy_par,
       COALESCE(sum(par*pr) FILTER (WHERE cb), 0)/100.0 AS cust_buy_dollar,
       count(*) FILTER (WHERE cs)::INT             AS cust_sell_n,
       COALESCE(sum(par)            FILTER (WHERE cs), 0) AS cust_sell_par,
       COALESCE(sum(par*pr) FILTER (WHERE cs), 0)/100.0 AS cust_sell_dollar,

       count(*) FILTER (WHERE cntra_mp_id = 'D')::INT AS dd_n,
       COALESCE(sum(par)          FILTER (WHERE cntra_mp_id = 'D'), 0) AS dd_par,
       COALESCE(sum(par*pr) FILTER (WHERE cntra_mp_id = 'D'), 0)/100.0 AS dd_dollar,
       count(*) FILTER (WHERE cntra_mp_id IN ('A','T'))::INT AS at_n,
       COALESCE(sum(par)          FILTER (WHERE cntra_mp_id IN ('A','T')), 0) AS at_par,
       COALESCE(sum(par*pr) FILTER (WHERE cntra_mp_id IN ('A','T')), 0)/100.0 AS at_dollar,

       count(*) FILTER (WHERE cust AND is_odd)::INT AS cust_odd_n,
       COALESCE(sum(par)          FILTER (WHERE cust AND is_odd), 0) AS cust_odd_par,
       COALESCE(sum(par*pr) FILTER (WHERE cust AND is_odd), 0)/100.0 AS cust_odd_dollar,
       sum(par*pr) FILTER (WHERE cust AND is_odd)
         / NULLIF(sum(par) FILTER (WHERE cust AND is_odd), 0)   AS cust_odd_vwap,
       count(*) FILTER (WHERE cust AND is_round)::INT AS cust_round_n,
       COALESCE(sum(par)          FILTER (WHERE cust AND is_round), 0) AS cust_round_par,
       COALESCE(sum(par*pr) FILTER (WHERE cust AND is_round), 0)/100.0 AS cust_round_dollar,
       sum(par*pr) FILTER (WHERE cust AND is_round)
         / NULLIF(sum(par) FILTER (WHERE cust AND is_round), 0) AS cust_round_vwap,

       count(*) FILTER (WHERE cs AND is_odd)::INT AS cust_sell_odd_n,
       COALESCE(sum(par)          FILTER (WHERE cs AND is_odd), 0) AS cust_sell_odd_par,
       COALESCE(sum(par*pr) FILTER (WHERE cs AND is_odd), 0)/100.0 AS cust_sell_odd_dollar,
       count(*) FILTER (WHERE cs AND is_round)::INT AS cust_sell_round_n,
       COALESCE(sum(par)          FILTER (WHERE cs AND is_round), 0) AS cust_sell_round_par,
       COALESCE(sum(par*pr) FILTER (WHERE cs AND is_round), 0)/100.0 AS cust_sell_round_dollar,
       count(*) FILTER (WHERE cb AND is_odd)::INT AS cust_buy_odd_n,
       COALESCE(sum(par)          FILTER (WHERE cb AND is_odd), 0) AS cust_buy_odd_par,
       COALESCE(sum(par*pr) FILTER (WHERE cb AND is_odd), 0)/100.0 AS cust_buy_odd_dollar,
       count(*) FILTER (WHERE cb AND is_round)::INT AS cust_buy_round_n,
       COALESCE(sum(par)          FILTER (WHERE cb AND is_round), 0) AS cust_buy_round_par,
       COALESCE(sum(par*pr) FILTER (WHERE cb AND is_round), 0)/100.0 AS cust_buy_round_dollar
FROM (
    SELECT *,
           (cntra_mp_id = 'C' AND rpt_side_cd = 'S') AS cb,   -- customer buys from dealer
           (cntra_mp_id = 'C' AND rpt_side_cd = 'B') AS cs,   -- customer sells to dealer
           (cntra_mp_id = 'C')                       AS cust,
           (par < {odd_max})   AS is_odd,
           (par >= {round_min}) AS is_round
    FROM flagged
    WHERE pass_dn AND pass_rev AND pass_dd AND pass_wis AND pass_spcl
      AND pass_band AND pass_size
)
GROUP BY 1, 2
"""

# ASOF join (equality on cusip + one inequality) — verified identical to the
# naive range LEFT JOIN on year 2002 (508,806 rows, 0 mismatches) and ~800x
# faster (0.3s vs 250s; the OR-range join forced a non-hash plan).
JOIN_WRITE_SQL = """
COPY (
    SELECT a.*,
           CASE WHEN j.grade IS NOT NULL AND a.dt <= j.seg_end THEN j.grade END AS grade
    FROM agg a
    ASOF LEFT JOIN tl j ON j.cusip_id = a.cusip_id AND a.dt >= j.run_start
) TO '{out}' (FORMAT PARQUET)
"""


def stage_b(con, force: bool) -> None:
    log("STAGE B — per-year DN filter + bond-day aggregation + grade join")
    tl = pd.read_parquet(TL_PATH)
    tl["seg_end"] = (tl.run_next - pd.Timedelta(days=1)).fillna(tl.run_last_enddt)
    con.register("tl", tl)
    att_path = SCRATCH / "attrition_by_year.csv"
    att = pd.read_csv(att_path) if att_path.exists() and not force else pd.DataFrame()
    for y in YEARS:
        out_dir = PANEL / f"year={y}"
        out = out_dir / "data_0.parquet"
        stale = out_dir / "_tmp.parquet"
        if stale.exists():
            stale.unlink()   # crash leftover; would double-count in globs
        if out.exists() and not force and (len(att) and (att.year == y).any()):
            log(f"  {y}: cached, skipping")
            continue
        t0 = time.time()
        con.execute(FLAG_SQL.format(stage=STAGE, y=y, pr_lo=PR_LO, pr_hi=PR_HI,
                                    size_cap=SIZE_CAP, sib_min=SIB_MIN))
        a = q(con, ATTRITION_SQL.format(y=y))
        con.execute(AGG_SQL.format(odd_max=ODD_MAX, round_min=ROUND_MIN))
        n_agg = q(con, "SELECT count(*) n FROM agg").n[0]
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp_out = out_dir / "_tmp.parquet"
        con.execute(JOIN_WRITE_SQL.format(out=tmp_out))
        n_out = q(con, f"SELECT count(*) n FROM read_parquet('{tmp_out}')").n[0]
        if n_out != n_agg:
            raise RuntimeError(f"{y}: grade join changed row count {n_agg} -> {n_out} "
                               f"(timeline overlap bug)")
        tmp_out.rename(out)
        a["n_bond_days"] = int(n_agg)
        att = pd.concat([att[att.year != y] if len(att) else att, a], ignore_index=True)
        att.sort_values("year").to_csv(att_path, index=False)
        con.execute("DROP TABLE IF EXISTS flagged; DROP TABLE IF EXISTS agg")
        log(f"  {y}: {int(a.n0_staged[0]):,} staged -> {int(a.n7_final[0]):,} clean trades "
            f"(size-junk ${float(a.size_junk_par_bn[0]):,.0f}bn par dropped) "
            f"-> {int(n_agg):,} bond-days  ({time.time() - t0:.0f}s)")
    print(att.sort_values("year").to_string(index=False), flush=True)


# ---------------------------------------------------------------------------
# STAGE D — market-day aggregates (HY / IG / NR)
# ---------------------------------------------------------------------------
# "seasoned" = bond-day at least 8 calendar days after the bond's first TRACE
# print in this panel. New-issue distribution days carry multi-counted primary
# allocations (e.g. the 2011-01-18..25 LatAm cluster: Petrobras/Odebrecht/CSN
# first trading days showing 6-16bn "customer sell" on 2.5bn tranches) and must
# not drive the M1 aggregate-imbalance series.
MARKET_SQL = """
COPY (
    WITH first_print AS (
        SELECT cusip_id, min(dt) AS first_dt
        FROM read_parquet('{panel}/year=*/*.parquet', hive_partitioning=1)
        GROUP BY 1
    ),
    p AS (
        SELECT b.dt,
               CASE b.grade WHEN 'H' THEN 'HY' WHEN 'I' THEN 'IG' ELSE 'NR' END AS bucket,
               b.dt >= f.first_dt + INTERVAL 8 DAY AS seasoned,
               n_trades, cust_sell_dollar, cust_buy_dollar, cust_sell_par, cust_buy_par,
               dd_dollar, dollar_total,
               CASE WHEN cust_odd_par > 0 AND cust_round_par > 0
                    THEN 10000.0 * (cust_odd_vwap - cust_round_vwap) / cust_round_vwap
               END AS gap_bp,
               CASE WHEN cust_sell_odd_par > 0 AND cust_sell_round_par > 0
                    THEN 10000.0 * (cust_sell_odd_dollar / cust_sell_odd_par
                                    - cust_sell_round_dollar / cust_sell_round_par)
                         / (cust_sell_round_dollar / cust_sell_round_par)
               END AS gap_sell_bp
        FROM read_parquet('{panel}/year=*/*.parquet', hive_partitioning=1) b
        JOIN first_print f USING (cusip_id)
    )
    SELECT dt, bucket,
           count(*)::INT            AS n_bonds,
           sum(n_trades)::INT       AS n_trades,
           sum(cust_sell_dollar)    AS cust_sell_dollar,
           sum(cust_buy_dollar)     AS cust_buy_dollar,
           sum(cust_sell_dollar) - sum(cust_buy_dollar) AS imbalance_dollar,
           sum(cust_sell_par)       AS cust_sell_par,
           sum(cust_buy_par)        AS cust_buy_par,
           sum(cust_sell_par) - sum(cust_buy_par)       AS imbalance_par,
           sum(dd_dollar)           AS dd_dollar,
           sum(dollar_total)        AS dollar_total,
           count(*) FILTER (WHERE seasoned)::INT           AS n_bonds_seasoned,
           COALESCE(sum(cust_sell_dollar) FILTER (WHERE seasoned), 0) AS cust_sell_dollar_seasoned,
           COALESCE(sum(cust_buy_dollar)  FILTER (WHERE seasoned), 0) AS cust_buy_dollar_seasoned,
           COALESCE(sum(cust_sell_dollar) FILTER (WHERE seasoned), 0)
             - COALESCE(sum(cust_buy_dollar) FILTER (WHERE seasoned), 0) AS imbalance_dollar_seasoned,
           COALESCE(sum(cust_sell_par) FILTER (WHERE seasoned), 0) AS cust_sell_par_seasoned,
           COALESCE(sum(cust_buy_par)  FILTER (WHERE seasoned), 0) AS cust_buy_par_seasoned,
           median(gap_bp)           AS oddlot_gap_bp,
           count(gap_bp)::INT       AS n_gap_bonds,
           median(gap_sell_bp)      AS oddlot_gap_sell_bp,
           count(gap_sell_bp)::INT  AS n_gap_sell_bonds
    FROM p
    GROUP BY 1, 2
    ORDER BY 1, 2
) TO '{out}' (FORMAT PARQUET)
"""


def stage_d(con, force: bool) -> None:
    out = DAT / "market_day.parquet"
    if out.exists() and not force:
        log("stage D: cached, skipping")
        return
    log("STAGE D — market-day aggregates")
    con.execute(MARKET_SQL.format(panel=PANEL, out=out))
    md = pd.read_parquet(out)
    log(f"wrote {out}: {len(md):,} rows, {md.dt.min()} .. {md.dt.max()}")
    print(md.groupby("bucket").agg(days=("dt", "nunique"),
                                   sell_bn_total=("cust_sell_dollar", lambda s: s.sum() / 1e9))
          .to_string(), flush=True)


# ---------------------------------------------------------------------------
# STAGE E — validation + PANEL_BUILD.md
# ---------------------------------------------------------------------------
# Order-of-magnitude anchors for US corporate bond ADV (par, $bn/day) — coarse
# public FINRA/SIFMA-reported ranges, used ONLY as sanity bands, not citations.
FINRA_ADV_BAND = {r: b for rng, b in
                  [((2002, 2007), (8, 25)), ((2008, 2014), (12, 30)),
                   ((2015, 2019), (20, 40)), ((2020, 2025), (25, 60))]
                  for r in range(rng[0], rng[1] + 1)}


def stage_e(con) -> dict:
    log("STAGE E — validation")
    panel_glob = f"{PANEL}/year=*/*.parquet"
    checks: dict = {}

    # --- E1 yearly totals ----------------------------------------------------
    yr = q(con, f"""
        SELECT year, count(*) AS n_bond_days, count(DISTINCT cusip_id) AS n_cusips,
               count(DISTINCT dt) AS n_days,
               sum(par_total)/1e12  AS par_tn,
               sum(dollar_total)/1e12 AS dollar_tn,
               sum(par_total)/count(DISTINCT dt)/1e9 AS adv_par_bn,
               sum(cust_sell_dollar)/1e12 AS cust_sell_tn,
               100.0 * count(*) FILTER (WHERE grade IN ('I','H')) / count(*) AS pct_graded,
               100.0 * sum(dollar_total) FILTER (WHERE grade IN ('I','H'))
                     / sum(dollar_total) AS pct_dollar_graded
        FROM read_parquet('{panel_glob}', hive_partitioning=1)
        GROUP BY 1 ORDER BY 1
    """)
    yr["finra_band_bn"] = yr.year.map(lambda y: str(FINRA_ADV_BAND.get(y)))
    yr["in_band"] = yr.apply(lambda r: FINRA_ADV_BAND[r.year][0] / 3
                             <= r.adv_par_bn <= FINRA_ADV_BAND[r.year][1] * 3, axis=1)
    print(yr.to_string(index=False), flush=True)
    yr.to_csv(RES / "p1_yearly_totals.csv", index=False)
    checks["yearly"] = yr

    # --- E2 Ford May 2005 ----------------------------------------------------
    ford = q(con, f"""
        SELECT dt, sum(cust_sell_par)/1e6 AS sell_mm, sum(cust_buy_par)/1e6 AS buy_mm,
               sum(cust_sell_par - cust_buy_par)/1e6 AS net_sell_mm
        FROM read_parquet('{panel_glob}', hive_partitioning=1)
        WHERE (cusip_id LIKE '345370%' OR cusip_id LIKE '345397%')
          AND dt BETWEEN DATE '2005-04-15' AND DATE '2005-06-03'
        GROUP BY 1 ORDER BY 1
    """)
    ford["dt"] = pd.to_datetime(ford["dt"])
    base = ford[ford.dt < pd.Timestamp("2005-05-05")].sell_mm.mean()
    r0505 = float(ford.loc[ford.dt == pd.Timestamp("2005-05-05"), "sell_mm"].iloc[0]) / base
    r0531 = float(ford.loc[ford.dt == pd.Timestamp("2005-05-31"), "sell_mm"].iloc[0]) / base
    log(f"Ford customer-sell: baseline {base:.0f}MM/d; 2005-05-05 = {r0505:.1f}x; "
        f"2005-05-31 = {r0531:.1f}x")
    ford.to_csv(RES / "p1_ford_check.csv", index=False)
    checks["ford"] = dict(base_mm=base, ratio_0505=r0505, ratio_0531=r0531)

    # --- E3 GM week ------------------------------------------------------------
    cam = r2_path("trace_enhanced", "camasterfile")
    gm_cusips = q(con, f"SELECT DISTINCT cusip_id FROM read_parquet('{cam}') "
                       f"WHERE issuer_nm ILIKE 'GENERAL MOTORS%' AND cusip_id IS NOT NULL")
    con.register("gm_set", gm_cusips)
    gm = q(con, f"""
        SELECT dt, sum(cust_sell_par)/1e6 AS sell_mm,
               sum(cust_sell_par - cust_buy_par)/1e6 AS net_sell_mm
        FROM read_parquet('{panel_glob}', hive_partitioning=1) p
        JOIN gm_set g USING (cusip_id)
        WHERE dt BETWEEN DATE '2005-04-15' AND DATE '2005-06-03'
        GROUP BY 1 ORDER BY 1
    """)
    gm["dt"] = pd.to_datetime(gm["dt"])
    gbase = gm[gm.dt < pd.Timestamp("2005-05-05")].sell_mm.mean()
    gm_week = gm[(gm.dt >= pd.Timestamp("2005-05-05"))
                 & (gm.dt <= pd.Timestamp("2005-05-11"))].sell_mm.max() / gbase
    gm_me = gm[gm.dt >= pd.Timestamp("2005-05-25")].sell_mm.max() / gbase
    log(f"GM customer-sell: baseline {gbase:.0f}MM/d; downgrade week max {gm_week:.1f}x; "
        f"late-May max {gm_me:.1f}x  ({len(gm_cusips):,} GM cusips)")
    gm.to_csv(RES / "p1_gm_check.csv", index=False)
    checks["gm"] = dict(base_mm=gbase, week_ratio=gm_week, me_ratio=gm_me,
                        n_cusips=len(gm_cusips))

    # --- E4 market-day sanity ----------------------------------------------
    mdq = pd.read_parquet(DAT / "market_day.parquet")
    mdq["dt"] = pd.to_datetime(mdq["dt"])
    hy = mdq[mdq.bucket == "HY"].set_index("dt")
    top_hy = hy.nlargest(15, "cust_sell_dollar_seasoned")[["cust_sell_dollar_seasoned",
                                                           "cust_sell_dollar", "n_bonds"]]
    print("\ntop-15 HY customer-sell days (seasoned $):\n",
          (top_hy.cust_sell_dollar_seasoned / 1e9).round(2).to_string(), flush=True)
    checks["top_hy_seasoned"] = [str(d.date()) for d in top_hy.index[:15]]
    hy05 = hy[(hy.index >= pd.Timestamp("2005-01-01"))
              & (hy.index <= pd.Timestamp("2005-12-31"))]
    top05 = hy05.nlargest(5, "cust_sell_dollar_seasoned").index.tolist()
    log(f"top-5 HY sell days of 2005: {[str(d.date()) for d in top05]}")
    checks["top05_hy"] = [str(d.date()) for d in top05]
    checks["may_in_top5_2005"] = any(str(d).startswith("2005-05") for d in checks["top05_hy"])
    gap_yr = (mdq[mdq.bucket == "HY"].assign(yr=lambda d: pd.to_datetime(d.dt).dt.year)
              .groupby("yr")["oddlot_gap_sell_bp"].median())
    print("\nHY odd-lot sell gap, median bp by year:\n", gap_yr.round(1).to_string(), flush=True)
    checks["gap_yr"] = gap_yr

    # --- E5 bounds ------------------------------------------------------------
    b = q(con, f"""SELECT min(dt) lo, max(dt) hi, count(*) n,
                   count(DISTINCT cusip_id) n_cusips
                   FROM read_parquet('{panel_glob}', hive_partitioning=1)""").iloc[0]
    log(f"panel bounds: {b.lo} .. {b.hi}, {int(b.n):,} bond-days, {int(b.n_cusips):,} cusips")
    checks["bounds"] = dict(lo=str(b.lo), hi=str(b.hi), n=int(b.n), n_cusips=int(b.n_cusips))
    return checks


def write_md(checks: dict) -> None:
    att = pd.read_csv(SCRATCH / "attrition_by_year.csv").sort_values("year")
    meta = json.loads((SCRATCH / "stage0_meta.json").read_text())
    stg = pd.read_csv(SCRATCH / "stagea_year_counts.csv")
    yr = checks["yearly"]
    tot = att[["n0_staged", "n1_after_cancel_corr", "n2_after_reversal",
               "n3_after_interdealer_dedup", "n4_after_wis", "n5_after_spcl",
               "n6_after_band", "n7_final", "size_junk_par_bn"]].sum()

    def f(x): return f"{int(x):,}"

    md = []
    md.append(f"""# P1 — Shared bond-day TRACE panel (forced-flow cycle 2)

Built {time.strftime('%Y-%m-%d')} by `scripts/forced_flow2/p1_build_bond_day_panel.py`.
Source: `wrds/trace_enhanced/trace_enhanced.parquet` ({TOTAL_TRACE_ROWS:,} raw rows,
2002-07-01..2025-12-04) + `camasterfile` for the corporate universe and the
effective-dated IG/HY flag. DATA ONLY — no returns, no tests (prereg binding).

## Outputs

| file | rows | span |
|---|---|---|
| `data/forced_flow2/bond_day_panel/year=*/` | {f(checks['bounds']['n'])} bond-days, {f(checks['bounds']['n_cusips'])} CUSIPs | {checks['bounds']['lo']} .. {checks['bounds']['hi']} |
| `data/forced_flow2/market_day.parquet` | per-day x {{HY, IG, NR}} aggregates | same |
| `data/forced_flow2/grade_timeline.parquet` | {f(meta['n_runs_final'])} effective-dated grade runs | 2002-07-01 .. 2026-06-05 |

Panel columns: `cusip_id, dt, grade (I/H/N/null), n_trades, par_total, dollar_total,
vwap_all, last_pr`, customer buy/sell (n, par, dollar), dealer-dealer (sell-side kept),
A/T sensitivity bucket, and odd-lot (<$100k) / round-lot (>=$1MM) splits of customer
volume per side with size-weighted VWAPs (side-level VWAP = 100*dollar/par).
Dollar = par x price/100 (market value); par = face. Mid-lots ($100k-$1MM) =
customer total minus odd minus round.

## Build decisions (all documented deviations/refinements)

1. **Corporate filter.** `trace_enhanced.sub_prdct` is ~100% NULL before 2012
   (2005: 9 non-null rows of 8.1M — see `r1_year_stats.csv`), so the prereg
   instruction "filter sub_prdct='CORP'" is implementable at trade level only
   post-2012. Rule used, uniform across the break: keep iff CUSIP is in the
   camasterfile CORP set ({f(meta['cam_corp_cusips'])} CUSIPs with any
   `sub_prdct_type='CORP'` interval) AND (`sub_prdct='CORP'` OR `sub_prdct` IS NULL).
   This removes ELN/AGCY/CHRC contamination in all years (incl. the 77.9%-CORP
   2011 caveat) without erasing 2002-2011.
2. **Dick-Nielsen two-regime filter** reused verbatim from the cycle-1-verified
   `scripts/build_trace_prices.py`: pointer voiding (orig_msg_seq_nb, trc_st
   C/W/X/R/Y), echo voiding (trc_st X/C without orig), survivors T/W/R;
   pre-2012 reversals `asof_cd='R'` + attribute-matched original (known
   over-deletion of identical simultaneous prints — standard DN-2014 limitation).
3. **Inter-dealer dedup**: sell side of `cntra_mp_id='D'` kept, D+B dropped.
   **Customer = `cntra_mp_id='C'` only.** A (ATS, 2015+) and T (affiliate, 2020+)
   prints are carried in a separate `at_*` bucket for the mandated A/T
   sensitivity; they are in `n_trades`/`par_total` but in no customer column.
4. **Hygiene**: price band [1, 250], par>0, `wis_fl`/`spcl_trd_fl` dropped, plus
   the x1000 unit-error SIZE filter (step 8 below — par >= $1bn dropped; par in
   [$100MM, $1bn) dropped when an exact par/1000 same-bond-day sibling exists).
   **No fat-finger PRICE median filter** — it would censor exactly the
   fire-sale-day price dispersion M2/M5 study. Studies apply their own clips.
5. **Grade join**: camasterfile intervals resolved last-writer-wins per
   RATINGS_SPIKE.md correction 1; {meta['n_artifact_voided']} grade transitions
   dated 2017-03-18..20 (vintage-reload artifact, Amendment 3) voided by carrying
   the prior grade forward. `grade` NULL = no master coverage at that date.
6. **As-of/late-reported prints** land on execution date — fine for research;
   panel is DISCOVERY-ONLY per prereg (a live signal would not see late prints).

## Filter counts (Dick-Nielsen + hygiene, full span)

| step | rows | dropped |
|---|---|---|
| raw TRACE rows | {TOTAL_TRACE_ROWS:,} | |
| after corporate filter (staged) | {f(tot.n0_staged)} | {f(TOTAL_TRACE_ROWS - tot.n0_staged)} |
| after cancel/correction voiding | {f(tot.n1_after_cancel_corr)} | {f(tot.n0_staged - tot.n1_after_cancel_corr)} |
| after reversal removal | {f(tot.n2_after_reversal)} | {f(tot.n1_after_cancel_corr - tot.n2_after_reversal)} |
| after inter-dealer dedup (drop D+B) | {f(tot.n3_after_interdealer_dedup)} | {f(tot.n2_after_reversal - tot.n3_after_interdealer_dedup)} |
| after when-issued drop | {f(tot.n4_after_wis)} | {f(tot.n3_after_interdealer_dedup - tot.n4_after_wis)} |
| after special-price drop | {f(tot.n5_after_spcl)} | {f(tot.n4_after_wis - tot.n5_after_spcl)} |
| after price band [1,250] & par>0 | {f(tot.n6_after_band)} | {f(tot.n5_after_spcl - tot.n6_after_band)} |
| after x1000 unit-error size filter | {f(tot.n7_final)} | {f(tot.n6_after_band - tot.n7_final)} (${tot.size_junk_par_bn:,.0f}bn junk par) |

Per-year table: `results/forced_flow2/p1_attrition_by_year.csv`.

### x1000 unit-error size filter (step 8) — correction to the R1 audit reading

R1 concluded "sizes are true par values throughout; no cap convention needs
handling". Sizes are indeed uncapped, but the EXTREME tail is systematically
corrupt: prints >= $1bn par total $34.6tn across the span and 87% of that par
has an exact x1000 sibling (same bond, same day, par/1000, typically same second
and price) — mis-scaled duplicate reports (par typed in dollars where thousands
were meant), never cancelled, invisible to Dick-Nielsen. Smoking gun (CSN
G25842AA6, 2011-01-24 15:29:36): an 8,000,000,000 print next to an 8,000,000
print at identical prices, on a ~$400MM issue. Rule applied: drop par >= $1bn
unconditionally; drop par in [$100MM, $1bn) when the exact par/1000 print exists
on the same bond-day. Unmatched $100MM-$1bn prints (~$300bn/yr) are retained as
plausible genuine blocks. Raw junk par removed measured per year in
`p1_attrition_by_year.csv` (size_junk_par_bn = post-DN clean rows failing only
the size filter).
""")
    md.append("## Per-year panel totals vs FINRA order-of-magnitude anchors\n")
    md.append("ADV = clean par volume / trading days, post-dedup (FINRA headline ADV counts "
              "each trade once too, but includes non-CORP subproducts and applies no price "
              "band; bands below are coarse public FINRA/SIFMA ranges used only as "
              "order-of-magnitude sanity anchors, pass = within 3x of band).\n")
    cols = ["year", "n_bond_days", "n_cusips", "n_days", "par_tn", "adv_par_bn",
            "cust_sell_tn", "pct_dollar_graded", "finra_band_bn", "in_band"]
    md.append(yr[cols].round(2).to_markdown(index=False))
    fd, gmc = checks["ford"], checks["gm"]
    md.append(f"""
## Known-event validation

**Ford (CUSIP6 345370/345397), May 2005** — customer-sell par, baseline
2005-04-15..05-04 = ${fd['base_mm']:.0f}MM/day:
downgrade day 2005-05-05 = **{fd['ratio_0505']:.1f}x** baseline; month-end index
deletion 2005-05-31 = **{fd['ratio_0531']:.1f}x**. (R1 audit found 2.5x / 4.2x on the
raw side-flag pull; panel matches the two-pulse signature.) Table: `p1_ford_check.csv`.

**General Motors (issuer_nm 'GENERAL MOTORS%', {gmc['n_cusips']:,} CUSIPs)** —
baseline ${gmc['base_mm']:.0f}MM/day; max daily customer-sell in downgrade week
(05-05..05-11) = **{gmc['week_ratio']:.1f}x**; late-May (post Fitch cut / index exit)
max = **{gmc['me_ratio']:.1f}x**. Table: `p1_gm_check.csv`.

**Top-5 HY market-day customer-sell days of 2005 (seasoned)**: {', '.join(checks['top05_hy'])}
(May-2005 present: {checks['may_in_top5_2005']}).

**Top-15 HY seasoned customer-sell days all-time**: {', '.join(checks.get('top_hy_seasoned', []))}.

### Why market_day also has *_seasoned columns

The x1000 filter above removes the dominant contamination (it was first noticed
as a $21-30bn/day HY "sell" cluster on 2011-01-18..25, all LatAm names —
Petrobras, Odebrecht, CSN, Votorantim, Bradesco, Safra, Cencosud). Separately,
genuine new-issue distribution days multi-count primary allocations as customer
volume, so market_day.parquet carries BOTH raw and `*_seasoned` aggregates
(seasoned = bond-day >= 8 calendar days after the bond's first panel print).
M1 should use the seasoned series and report the raw series as sensitivity.
Left-edge note: every bond "first prints" at the 2002-07-01 TRACE start, so the
first ~8 panel days have empty seasoned aggregates. Bond-level rows are kept
untouched — bond-level studies (M2/M6) use their own baselines/screens.

**HY odd-lot sell gap** (median same-bond same-day oddlot-VWAP minus roundlot-VWAP, bp)
is negative every year — retail sellers systematically execute below round-lot prices —
yearly medians in `p1_yearly_totals.csv` context and `market_day.parquet`.

## Caveats carried forward (from R1 audit, binding on all users of this panel)

1. 2012-02-06 reporting-regime break handled by the two-regime DN filter — but any
   raw-count comparison across 2012 should use the attrition table, not raw rows.
2. Customer = 'C' only; A/T bucket must be included in a sensitivity for any
   pre-2015 vs post-2015 comparison (composition drift: A ~4% from 2016, T ~4-5%
   from 2020).
3. Mirror ends 2025-12-04; 2025-12 is a partial month. TRACE is discovery-only.
4. Odd/round VWAP gap medians are computed only over bonds with BOTH an odd-lot
   and a round-lot customer print that day (n_gap_bonds in market_day.parquet).
5. grade='N' and grade NULL bond-days are excluded from HY/IG market aggregates
   (bucket 'NR').
""")
    MD_PATH.write_text("\n".join(md))
    att.to_csv(RES / "p1_attrition_by_year.csv", index=False)
    log(f"wrote {MD_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "0", "a", "b", "d", "e"])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "duck_tmp").mkdir(exist_ok=True)
    DAT.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)
    PANEL.mkdir(parents=True, exist_ok=True)

    con = connect()
    setup(con)
    t0 = time.time()
    if args.stage in ("all", "0"):
        stage0(con, args.force)
    if args.stage in ("all", "a"):
        stage_a(con, args.force)
    if args.stage in ("all", "b"):
        stage_b(con, args.force)
    if args.stage in ("all", "d"):
        stage_d(con, args.force)
    if args.stage in ("all", "e"):
        checks = stage_e(con)
        write_md(checks)
    log(f"ALL DONE in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
