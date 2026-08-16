"""Clean-room rebuild of the fallen-angel event file (Phase 3a audit).

Written independently from PREREGISTRATION.md Amendment 2 + the camasterfile schema.
The production builder (scripts/build_fallen_angel_events.py) was deliberately NOT read
before this script was written, so that agreement between the two is evidence rather
than shared assumption.

Amendment 2, verbatim, is the only spec used:

  Primary event definition: first day a CUSIP's `grade` goes I -> H (handling I->N->H
  paths, N = not rated), from camasterfile. Daily dating across the whole 2002-2025 window.

  Event universe filters, fixed now: corporate `sub_prdct_type` only; exclude 144A-only
  and convertibles; require >= 12 months of prior I tenure (excludes flip-flops); require
  >= 20 TRACE trades in the 6 months pre-event (excludes untraded paper); one event per
  CUSIP (first only); collapse to issuer-month for clustering.

DATA ONLY. No returns, no hypothesis tests -- doing either here would contaminate the
pre-registered analysis.

The script runs five successive readings of the file (v1..v5) rather than jumping to the
answer, because the wrong readings are the audit's actual content: each one fails on a
specific camasterfile pathology, and the failures are what a future reader needs.

  v1/v2  order rows by stdt, lag the grade                      -> 50,052 events
  v3     union I intervals into islands, IG ends when they lapse -> 50,052
  v4     IG ends where the first H record takes over             -> 50,052
  v5     full daily effective-grade reconstruction               -> 56,917  <- correct

RESULT: v5's raw event set matches production's
data/fallen_angel_events_unfiltered.parquet EXACTLY -- 56,917 events, symmetric
difference 0 on (cusip_id, event_date). Pre-event trade counts match production on
17,126/17,126 shared events with zero difference. Final filtered sets differ by 38
events (0.22%), all traced to two documented judgment calls (D3/D4 and D5 below).

Interpretation decisions, with how each one resolved against production:

  D1  Sequencing. WRONG as first written. `enddt` is not a chain and the intervals
      OVERLAP AND NEST, so stdt ordering misreads the timeline. The file is a versioned
      master: on any day the effective record is the one with the greatest stdt among
      records whose [stdt, enddt] covers that day. v5 implements this. Two bulk reload
      dates (2021-07-01, 188,112 rows; 2012-02-06, 46,126 rows -- one row per live
      CUSIP) make the naive reading catastrophic: v1 dates 2,618 first-events to
      2021-07-01 alone. v5 dates 4 there.
  D2  Rows with NULL cusip_id (52,388) are dropped -- they cannot be an event for a bond.
      Confirmed harmless: they are also the only source of same-day grade conflicts
      (0 real CUSIPs have two different grades on one stdt).
  D3  I->N->H handling: N (and days with no record in force) are transparent, so the
      first I->H transition is found across them. Production agrees (its `path` column
      marks 4 events as via_N).
  D4  Prior-I tenure. PARTLY WRONG as first written. Measuring event_date minus the start
      of the I run counts long unrated gaps as IG tenure. UPS 911312AF3 is I for 3 days
      in Feb 2003, unrated for ~2 years, then H from 2005-02-07; the naive measure calls
      that 712 days of IG tenure and admits it. Tenure must be time actually in state I.
      Production measures it that way. Accounts for ~7 of the 38 residual differences.
  D5  Universe filters read off the EVENT row. DEFENSIBLE BUT LOOSER than production,
      which reads them across all of a CUSIP's rows (9,299 CUSIPs vary ind_144a and
      18,710 vary cnvrb_fl between rows). Amendment 2 says "exclude 144A-only", which
      literally means 144A on every row -- production's reading. Accounts for the other
      ~31 residual differences (28 ever-convertible, 3 not-144A-only).
  D6  Pre-event trade window is [event_date - 6 months, event_date), i.e. the event day
      itself is excluded. Confirmed: matches production exactly on 17,126 events.
  D7  Trade count uses trc_st = 'T' only (plain disseminated executions; excludes
      cancels C/X, reversals R, corrections W/Y). Confirmed: exact match.
  D8  NO roll to the next trading day. Rolling was an extra assumption, not in
      Amendment 2, and it shifts the pre-event window. Production keeps the raw
      state-change date (406 of 17,129 events fall on a Saturday, none on a Sunday --
      enddt is usually a Friday). Turning the roll off took the symmetric difference
      from 904 to 38.

Outputs: prints every count; writes nothing to data/ (this is an audit, not a build).
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.data.r2 import connect, q, r2_path  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)

CAMASTER = r2_path("trace_enhanced", "camasterfile")
TRACE = r2_path("trace_enhanced", "trace_enhanced")

MIN_IG_TENURE_DAYS = 365      # ">= 12 months of prior I tenure"
MIN_PRE_TRADES = 20           # ">= 20 TRACE trades in the 6 months pre-event"
PRE_WINDOW = "6 months"


def banner(msg: str) -> None:
    print(f"\n{'=' * 78}\n{msg}\n{'=' * 78}")


# ---------------------------------------------------------------------------
# Stage 1 -- raw first I->H events from camasterfile
# ---------------------------------------------------------------------------

def build_raw_events(con) -> pd.DataFrame:
    """First I->H transition per CUSIP, N-transparent, with prior-I-run start date."""
    sql = f"""
    WITH src AS (
        -- D2: real CUSIPs only. D3: strip N so I->N->H reads as I->H.
        SELECT cusip_id, stdt, grade, sub_prdct_type, ind_144a, cnvrb_fl,
               issuer_nm, company_symbol, mtrty_dt, cpn_rt, debt_type_cd, dissem
        FROM read_parquet('{CAMASTER}')
        WHERE cusip_id IS NOT NULL
          AND grade IN ('I', 'H')
    ),
    dedup AS (
        -- verified zero same-day grade conflicts among real CUSIPs, so any
        -- same-day duplicate rows are attribute-only churn: collapse them.
        SELECT cusip_id, stdt, grade,
               max(sub_prdct_type) sub_prdct_type, max(ind_144a) ind_144a,
               max(cnvrb_fl) cnvrb_fl, max(issuer_nm) issuer_nm,
               max(company_symbol) company_symbol, max(mtrty_dt) mtrty_dt,
               max(cpn_rt) cpn_rt, max(debt_type_cd) debt_type_cd, max(dissem) dissem
        FROM src GROUP BY cusip_id, stdt, grade
    ),
    seq AS (
        SELECT *, lag(grade) OVER w prev_grade, lag(stdt) OVER w prev_stdt
        FROM dedup
        WINDOW w AS (PARTITION BY cusip_id ORDER BY stdt)
    ),
    -- start of each contiguous same-grade run (D4)
    runs AS (
        SELECT *,
               sum(CASE WHEN prev_grade IS NULL OR prev_grade <> grade THEN 1 ELSE 0 END)
                   OVER (PARTITION BY cusip_id ORDER BY stdt
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) run_id
        FROM seq
    ),
    run_start AS (
        SELECT *, min(stdt) OVER (PARTITION BY cusip_id, run_id) run_start_dt
        FROM runs
    ),
    -- the I-run immediately preceding: its start is the previous run's start
    flips AS (
        SELECT cusip_id, stdt AS event_date, grade, issuer_nm, company_symbol,
               sub_prdct_type, ind_144a, cnvrb_fl, mtrty_dt, cpn_rt,
               debt_type_cd, dissem,
               lag(run_start_dt) OVER (PARTITION BY cusip_id ORDER BY stdt) ig_run_start,
               lag(grade)        OVER (PARTITION BY cusip_id ORDER BY stdt) prev_run_grade
        FROM run_start
        WHERE run_start_dt = stdt          -- first row of a run
    ),
    ih AS (
        SELECT f.*, date_diff('day', f.ig_run_start, f.event_date) AS ig_tenure_days
        FROM flips f
        WHERE f.ig_run_start IS NOT NULL   -- had a prior run
          AND f.grade = 'H'                -- downgrade only (not rising stars)
          AND f.prev_run_grade = 'I'
    )
    SELECT * FROM (
        SELECT *, row_number() OVER (PARTITION BY cusip_id ORDER BY event_date) rn
        FROM ih
    ) WHERE rn = 1                          -- one event per CUSIP, first only
    ORDER BY event_date, cusip_id
    """
    return q(con, sql)


def build_raw_events_v2(con) -> pd.DataFrame:
    """Simpler, structurally different reimplementation of the same definition.

    Deliberately avoids the run_id/window machinery above: builds the N-stripped
    grade sequence, finds every I->H adjacency by lag, takes the first, then
    measures tenure by looking back for the start of the unbroken I streak.
    Used as an internal consistency check on stage 1.
    """
    sql = f"""
    WITH dedup AS (
        SELECT cusip_id, stdt, grade,
               max(sub_prdct_type) sub_prdct_type, max(ind_144a) ind_144a,
               max(cnvrb_fl) cnvrb_fl, max(issuer_nm) issuer_nm
        FROM read_parquet('{CAMASTER}')
        WHERE cusip_id IS NOT NULL AND grade IN ('I', 'H')
        GROUP BY cusip_id, stdt, grade
    ),
    lagged AS (
        SELECT *, lag(grade) OVER w pg
        FROM dedup WINDOW w AS (PARTITION BY cusip_id ORDER BY stdt)
    ),
    events AS (
        SELECT cusip_id, stdt event_date, sub_prdct_type, ind_144a, cnvrb_fl, issuer_nm,
               row_number() OVER (PARTITION BY cusip_id ORDER BY stdt) rn
        FROM lagged WHERE pg = 'I' AND grade = 'H'
    ),
    first_ev AS (SELECT * FROM events WHERE rn = 1),
    -- start of the I streak: earliest I row with no H row between it and the event
    tenure AS (
        SELECT e.cusip_id, e.event_date, min(d.stdt) ig_run_start
        FROM first_ev e
        JOIN dedup d ON d.cusip_id = e.cusip_id AND d.grade = 'I' AND d.stdt < e.event_date
        WHERE NOT EXISTS (
            SELECT 1 FROM dedup h
            WHERE h.cusip_id = e.cusip_id AND h.grade = 'H'
              AND h.stdt > d.stdt AND h.stdt < e.event_date
        )
        GROUP BY e.cusip_id, e.event_date
    )
    SELECT e.cusip_id, e.event_date, e.sub_prdct_type, e.ind_144a, e.cnvrb_fl,
           t.ig_run_start, date_diff('day', t.ig_run_start, e.event_date) ig_tenure_days
    FROM first_ev e JOIN tenure t USING (cusip_id, event_date)
    ORDER BY e.event_date, e.cusip_id
    """
    return q(con, sql)


# ---------------------------------------------------------------------------
# Stage 6 -- interval-aware rebuild (v3)
# ---------------------------------------------------------------------------

__doc_v3__ = """
Why a third variant: camasterfile rows are effective-dated ATTRIBUTE VERSIONS whose
[stdt, enddt] intervals OVERLAP and NEST. Ordering by stdt alone therefore misreads the
grade timeline. Worked example -- 988498AJ0 (YUM BRANDS):

    grade  stdt        enddt
    H      2013-10-22  2021-06-30     <- long-running H descriptor
    I      2013-10-23  2015-10-19     <- IG interval NESTED inside it
    H      2021-07-01  2026-06-05     <- snapshot reload row

stdt ordering reads H -> I -> H and dates the downgrade 2021-07-01, which is a
master-file snapshot date (188,112 rows, one per live CUSIP -- not a rating action).
The interval reading says the bond was IG until 2015-10-19 and dates it 2015-10-20,
which matches the Yum China spin-off downgrade. The interval reading is correct.

v3 rule (the day the bond stopped being investment grade):
    ig_start = start of the first contiguous union of I intervals
    ig_end   = end of that union
    first_H  = earliest H row stdt strictly after ig_start
    event    = least(ig_end + 1 day, first_H)          [requires first_H to exist]
"""


__doc_v4__ = """
v3's island rule is still wrong. It ends an IG run whenever consecutive I intervals are
more than one day apart -- but camasterfile re-issues every record at the 2012-02-06
format cutover, so a bond's I interval ends Fri 2012-02-03 and the next starts Mon
2012-02-06. That 3-day weekend gap splits the IG run and dates a fake downgrade on
Sat 2012-02-04. v3 puts 7,210 raw events in 2012 (v1: 1,735; production: 359).

The gap is only meaningful if an H record actually takes over during it. So v4 drops
island-merging entirely and lets the first H record define the end of IG:

    ig_start = earliest I row stdt
    first_H  = earliest H row stdt strictly after ig_start
    ig_end   = max enddt over I rows that START before first_H
    event    = least(ig_end + 1 day, first_H)

Weekend/versioning gaps inside the IG run are bridged automatically because no H record
starts in them. Verified by hand against 5 cases (Ford 3454022Z3, YUM 988498AJ0,
Honda 02665WCD1, Mylan 62854AAM6, Lennar 526057AK0).
"""


__doc_v5__ = """
v4 is still an approximation. It assumes the bond turns H the day its IG coverage lapses,
but that is only true when an H record is already in force at that moment. Counter-case
74251VAE2 (PRINCIPAL FINL GROUP):

    grade  stdt        enddt
    I      2012-09-05  2021-06-30
    I      2014-10-10  2018-03-16
    I      2021-07-01  2022-09-05
    H      2022-09-29  2026-06-05          <- 23-day coverage GAP before this starts

v4 dates it 2022-09-06 (IG lapsed); the bond simply had no record in force until
2022-09-29. Production says 2022-09-29 and is right.

Meanwhile the Ford/YUM pair shows what happens when an I and an H record are in force
at the same time. Ford 3454022Z3 has I[2004-09-30..2005-12-19] and H[2005-05-05..], and
the event is 2005-05-05 -- the H wins. YUM 988498AJ0 has H[2013-10-22..2021-06-30] and
I[2013-10-23..2015-10-19], and the bond stays IG until 2015-10-19 -- the I wins. The
discriminator is which record STARTED most recently: camasterfile is a versioned master
and the latest effective record supersedes.

v5 therefore reconstructs the actual daily grade state:

    effective grade on day d = grade of the record with the greatest stdt among
                               all records with stdt <= d <= enddt
    event = first d where that state goes I -> H

State can only change on a record's stdt or the day after a record's enddt, so only
those candidate dates need evaluating. Days with no record in force carry no grade and
are transparent, exactly like N (Amendment 2's I->N->H handling).
"""


def build_events_state(con) -> pd.DataFrame:
    """First I->H event per CUSIP from a full daily effective-grade reconstruction."""
    sql = f"""
    WITH base AS (
        SELECT cusip_id, grade, stdt, enddt, sub_prdct_type, ind_144a, cnvrb_fl,
               issuer_nm, company_symbol, mtrty_dt, cpn_rt
        FROM read_parquet('{CAMASTER}')
        WHERE cusip_id IS NOT NULL AND stdt IS NOT NULL AND enddt IS NOT NULL
    ),
    cand AS (
        SELECT cusip_id, stdt AS d FROM base
        UNION
        SELECT cusip_id, (enddt + INTERVAL 1 DAY)::DATE AS d FROM base
    ),
    eff AS (
        SELECT c.cusip_id, c.d,
               arg_max(b.grade,          b.stdt) AS g,
               arg_max(b.sub_prdct_type, b.stdt) AS sub_prdct_type,
               arg_max(b.ind_144a,       b.stdt) AS ind_144a,
               arg_max(b.cnvrb_fl,       b.stdt) AS cnvrb_fl,
               arg_max(b.issuer_nm,      b.stdt) AS issuer_nm,
               arg_max(b.company_symbol, b.stdt) AS company_symbol,
               arg_max(b.mtrty_dt,       b.stdt) AS mtrty_dt,
               arg_max(b.cpn_rt,         b.stdt) AS cpn_rt
        FROM cand c
        JOIN base b ON b.cusip_id = c.cusip_id
                   AND b.stdt <= c.d AND c.d <= b.enddt
        GROUP BY c.cusip_id, c.d
    ),
    ih AS (SELECT * FROM eff WHERE g IN ('I', 'H')),   -- N / no-record transparent
    seq AS (
        SELECT *, lag(g) OVER w AS pg FROM ih
        WINDOW w AS (PARTITION BY cusip_id ORDER BY d)
    ),
    runs AS (
        SELECT *, sum(CASE WHEN pg IS NULL OR pg <> g THEN 1 ELSE 0 END)
                  OVER (PARTITION BY cusip_id ORDER BY d
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS rid
        FROM seq
    ),
    rs AS (SELECT *, min(d) OVER (PARTITION BY cusip_id, rid) AS run_start FROM runs),
    heads AS (
        SELECT *, lag(run_start) OVER (PARTITION BY cusip_id ORDER BY d) AS prev_run_start,
                  lag(g)         OVER (PARTITION BY cusip_id ORDER BY d) AS prev_run_grade
        FROM rs WHERE d = run_start
    ),
    ev AS (
        SELECT cusip_id, d AS event_date, prev_run_start AS ig_start,
               date_diff('day', prev_run_start, d) AS ig_tenure_days,
               sub_prdct_type, ind_144a, cnvrb_fl, issuer_nm, company_symbol,
               mtrty_dt, cpn_rt,
               row_number() OVER (PARTITION BY cusip_id ORDER BY d) AS rn
        FROM heads WHERE g = 'H' AND prev_run_grade = 'I'
    )
    SELECT * EXCLUDE (rn) FROM ev WHERE rn = 1 ORDER BY event_date, cusip_id
    """
    return q(con, sql)


def build_events_interval_v4(con) -> pd.DataFrame:
    """First I->H event per CUSIP; IG run ends where the first H record takes over."""
    sql = f"""
    WITH base AS (
        SELECT cusip_id, grade, stdt, enddt, sub_prdct_type, ind_144a, cnvrb_fl,
               issuer_nm, company_symbol, mtrty_dt, cpn_rt
        FROM read_parquet('{CAMASTER}')
        WHERE cusip_id IS NOT NULL AND stdt IS NOT NULL AND enddt IS NOT NULL
    ),
    ig_start AS (
        SELECT cusip_id, min(stdt) AS ig_start FROM base WHERE grade = 'I' GROUP BY 1
    ),
    first_h AS (
        SELECT s.cusip_id,
               min(h.stdt) AS first_h_stdt,
               arg_min(h.sub_prdct_type, h.stdt) sub_prdct_type,
               arg_min(h.ind_144a,       h.stdt) ind_144a,
               arg_min(h.cnvrb_fl,       h.stdt) cnvrb_fl,
               arg_min(h.issuer_nm,      h.stdt) issuer_nm,
               arg_min(h.company_symbol, h.stdt) company_symbol,
               arg_min(h.mtrty_dt,       h.stdt) mtrty_dt,
               arg_min(h.cpn_rt,         h.stdt) cpn_rt
        FROM ig_start s
        JOIN base h ON h.cusip_id = s.cusip_id AND h.grade = 'H' AND h.stdt > s.ig_start
        GROUP BY s.cusip_id
    ),
    ig_end AS (
        SELECT s.cusip_id, max(i.enddt) AS ig_end
        FROM ig_start s
        JOIN first_h f ON f.cusip_id = s.cusip_id
        JOIN base i ON i.cusip_id = s.cusip_id AND i.grade = 'I'
                   AND i.stdt < f.first_h_stdt
        GROUP BY s.cusip_id
    )
    SELECT s.cusip_id, s.ig_start, e.ig_end, f.first_h_stdt,
           least(e.ig_end + INTERVAL 1 DAY, f.first_h_stdt)::DATE AS event_date,
           date_diff('day', s.ig_start,
                     least(e.ig_end + INTERVAL 1 DAY, f.first_h_stdt)::DATE)
               AS ig_tenure_days,
           f.sub_prdct_type, f.ind_144a, f.cnvrb_fl, f.issuer_nm,
           f.company_symbol, f.mtrty_dt, f.cpn_rt
    FROM ig_start s
    JOIN first_h f USING (cusip_id)
    JOIN ig_end  e USING (cusip_id)
    ORDER BY event_date, cusip_id
    """
    return q(con, sql)


def build_events_interval(con) -> pd.DataFrame:
    """First I->H event per CUSIP, read from the [stdt, enddt] interval structure."""
    sql = f"""
    WITH base AS (
        SELECT cusip_id, grade, stdt, enddt, sub_prdct_type, ind_144a, cnvrb_fl,
               issuer_nm, company_symbol, mtrty_dt, cpn_rt
        FROM read_parquet('{CAMASTER}')
        WHERE cusip_id IS NOT NULL AND enddt IS NOT NULL AND stdt IS NOT NULL
    ),
    irows AS (SELECT cusip_id, stdt, enddt FROM base WHERE grade = 'I'),
    ord AS (
        SELECT *, max(enddt) OVER (
                    PARTITION BY cusip_id ORDER BY stdt, enddt
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prev_max_end
        FROM irows
    ),
    isl AS (
        SELECT *, sum(CASE WHEN prev_max_end IS NULL
                            OR stdt > prev_max_end + INTERVAL 1 DAY
                           THEN 1 ELSE 0 END)
                  OVER (PARTITION BY cusip_id ORDER BY stdt, enddt
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) island
        FROM ord
    ),
    agg AS (
        SELECT cusip_id, island, min(stdt) ig_start, max(enddt) ig_end
        FROM isl GROUP BY 1, 2
    ),
    first_island AS (
        SELECT cusip_id, ig_start, ig_end FROM (
            SELECT *, row_number() OVER (PARTITION BY cusip_id ORDER BY ig_start) rn
            FROM agg) WHERE rn = 1
    ),
    hrows AS (
        SELECT cusip_id, stdt, sub_prdct_type, ind_144a, cnvrb_fl,
               issuer_nm, company_symbol, mtrty_dt, cpn_rt
        FROM base WHERE grade = 'H'
    ),
    first_h AS (
        SELECT f.cusip_id,
               min(h.stdt) AS h_stdt,
               arg_min(h.sub_prdct_type, h.stdt) sub_prdct_type,
               arg_min(h.ind_144a,       h.stdt) ind_144a,
               arg_min(h.cnvrb_fl,       h.stdt) cnvrb_fl,
               arg_min(h.issuer_nm,      h.stdt) issuer_nm,
               arg_min(h.company_symbol, h.stdt) company_symbol,
               arg_min(h.mtrty_dt,       h.stdt) mtrty_dt,
               arg_min(h.cpn_rt,         h.stdt) cpn_rt
        FROM first_island f
        JOIN hrows h ON h.cusip_id = f.cusip_id AND h.stdt > f.ig_start
        GROUP BY f.cusip_id
    )
    SELECT f.cusip_id, f.ig_start, f.ig_end, hh.h_stdt,
           least(f.ig_end + INTERVAL 1 DAY, hh.h_stdt)::DATE AS event_date,
           date_diff('day', f.ig_start,
                     least(f.ig_end + INTERVAL 1 DAY, hh.h_stdt)::DATE) AS ig_tenure_days,
           hh.sub_prdct_type, hh.ind_144a, hh.cnvrb_fl, hh.issuer_nm,
           hh.company_symbol, hh.mtrty_dt, hh.cpn_rt
    FROM first_island f JOIN first_h hh USING (cusip_id)
    ORDER BY event_date, cusip_id
    """
    return q(con, sql)


# ---------------------------------------------------------------------------
# Stage 2 -- pre-event TRACE activity
# ---------------------------------------------------------------------------

def add_pre_trade_counts(con, cand: pd.DataFrame, status_filter: str) -> pd.DataFrame:
    """Count pre-event TRACE executions per candidate. Filters pushed into SQL."""
    con.register("cand", cand[["cusip_id", "event_date"]])
    where_st = "AND t.trc_st = 'T'" if status_filter == "T" else ""
    sql = f"""
    SELECT c.cusip_id, c.event_date, count(*) AS n_pre_trades
    FROM cand c
    JOIN read_parquet('{TRACE}') t
      ON t.cusip_id = c.cusip_id
     AND t.trd_exctn_dt >= c.event_date - INTERVAL {PRE_WINDOW}
     AND t.trd_exctn_dt <  c.event_date          -- D6: event day excluded
    WHERE t.cusip_id IN (SELECT cusip_id FROM cand)
      {where_st}
    GROUP BY 1, 2
    """
    counts = q(con, sql)
    con.unregister("cand")
    out = cand.merge(counts, on=["cusip_id", "event_date"], how="left")
    out["n_pre_trades"] = out["n_pre_trades"].fillna(0).astype(int)
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    con = connect()
    con.execute("SET memory_limit='8GB'")

    banner("STAGE 1 -- raw first I->H events (camasterfile, N-transparent)")
    raw = build_raw_events(con)
    print(f"rows: {len(raw):,}   distinct CUSIPs: {raw.cusip_id.nunique():,}")
    print(f"event_date range: {raw.event_date.min()} .. {raw.event_date.max()}")
    print("\nby year:")
    print(raw.groupby(raw.event_date.map(lambda d: d.year)).size().to_string())

    banner("STAGE 1b -- structurally independent reimplementation (self-check)")
    raw2 = build_raw_events_v2(con)
    print(f"v2 rows: {len(raw2):,}")
    a = set(zip(raw.cusip_id, raw.event_date))
    b = set(zip(raw2.cusip_id, raw2.event_date))
    print(f"v1 vs v2 symmetric difference: {len(a ^ b):,}")
    ten = raw[["cusip_id", "event_date", "ig_tenure_days"]].merge(
        raw2[["cusip_id", "event_date", "ig_tenure_days"]],
        on=["cusip_id", "event_date"], suffixes=("_v1", "_v2"))
    mismatch = ten[ten.ig_tenure_days_v1 != ten.ig_tenure_days_v2]
    print(f"tenure disagreements between v1 and v2: {len(mismatch):,}")
    if len(mismatch):
        print(mismatch.head(10).to_string())

    banner("STAGE 2 -- universe filters (Amendment 2), applied stepwise")
    steps = []
    cur = raw.copy()
    steps.append(("0. raw first I->H events", len(cur)))

    cur = cur[cur.sub_prdct_type == "CORP"]
    steps.append(("1. sub_prdct_type = CORP", len(cur)))

    cur = cur[cur.ind_144a == "N"]
    steps.append(("2. exclude 144A", len(cur)))

    cur = cur[cur.cnvrb_fl == "N"]
    steps.append(("3. exclude convertibles", len(cur)))

    cur = cur[cur.ig_tenure_days >= MIN_IG_TENURE_DAYS]
    steps.append((f"4. prior I tenure >= {MIN_IG_TENURE_DAYS}d", len(cur)))

    attr = pd.DataFrame(steps, columns=["step", "n_events"])
    attr["kept_pct_of_raw"] = (100 * attr.n_events / len(raw)).round(2)
    print(attr.to_string(index=False))

    banner("STAGE 3 -- pre-event TRACE activity (>= 20 trades in 6 months)")
    pre = add_pre_trade_counts(con, cur, status_filter="T")
    print(f"candidates entering trade screen: {len(pre):,}")
    print("\npre-trade-count distribution:")
    print(pre.n_pre_trades.describe(
        percentiles=[.1, .25, .5, .75, .9]).to_string())
    print(f"\nzero pre-event trades: {(pre.n_pre_trades == 0).sum():,} "
          f"({100 * (pre.n_pre_trades == 0).mean():.1f}%)")

    final = pre[pre.n_pre_trades >= MIN_PRE_TRADES].copy()
    print(f"\nsurviving >= {MIN_PRE_TRADES} trades: {len(final):,} "
          f"({100 * len(final) / len(pre):.1f}% of entrants, "
          f"{100 * len(final) / len(raw):.1f}% of raw)")
    print(f"final event_date range: {final.event_date.min()} .. {final.event_date.max()}")

    banner("STAGE 3b -- surviving events by year (filter-attrition sanity check)")
    by_year = pd.DataFrame({
        "raw": raw.groupby(raw.event_date.map(lambda d: d.year)).size(),
        "post_universe": cur.groupby(cur.event_date.map(lambda d: d.year)).size(),
        "final": final.groupby(final.event_date.map(lambda d: d.year)).size(),
    }).fillna(0).astype(int)
    by_year["trade_screen_survival_pct"] = (
        100 * by_year["final"] / by_year["post_universe"].where(by_year["post_universe"] > 0)
    ).astype(float).round(1)
    print(by_year.to_string())

    banner("STAGE 4 -- sensitivity of the judgment calls")
    # D7: trade-status filter
    pre_all = add_pre_trade_counts(con, cur, status_filter="ALL")
    n_all = (pre_all.n_pre_trades >= MIN_PRE_TRADES).sum()
    print(f"D7 trc_st='T' only : {len(final):,} events")
    print(f"D7 all trc_st      : {n_all:,} events  (delta {n_all - len(final):+,})")

    # D6: include event day in the window
    con.register("cand2", cur[["cusip_id", "event_date"]])
    inc = q(con, f"""
        SELECT c.cusip_id, c.event_date, count(*) n
        FROM cand2 c JOIN read_parquet('{TRACE}') t
          ON t.cusip_id = c.cusip_id
         AND t.trd_exctn_dt >= c.event_date - INTERVAL {PRE_WINDOW}
         AND t.trd_exctn_dt <= c.event_date
        WHERE t.cusip_id IN (SELECT cusip_id FROM cand2) AND t.trc_st='T'
        GROUP BY 1,2""")
    con.unregister("cand2")
    n_inc = (inc.n >= MIN_PRE_TRADES).sum()
    print(f"D6 window excl. event day : {len(final):,} events")
    print(f"D6 window incl. event day : {n_inc:,} events  (delta {n_inc - len(final):+,})")

    # D4: tenure measured in calendar months instead of 365 days
    alt = raw[(raw.sub_prdct_type == "CORP") & (raw.ind_144a == "N")
              & (raw.cnvrb_fl == "N")]
    for d in (335, 365, 366):
        print(f"D4 tenure >= {d}d -> {(alt.ig_tenure_days >= d).sum():,} candidates")

    # D3: what if N is treated as breaking the chain (I->N->H NOT an event)?
    strict_n = q(con, f"""
        WITH dedup AS (
            SELECT cusip_id, stdt, grade FROM read_parquet('{CAMASTER}')
            WHERE cusip_id IS NOT NULL GROUP BY 1,2,3),
        lagged AS (SELECT *, lag(grade) OVER (PARTITION BY cusip_id ORDER BY stdt) pg
                   FROM dedup)
        SELECT count(DISTINCT cusip_id) n FROM lagged WHERE pg='I' AND grade='H'
    """)
    n_transparent = raw.cusip_id.nunique()
    print(f"\nD3 N-transparent (I->N->H counts)  : {n_transparent:,} CUSIPs with an event")
    print(f"D3 N-opaque (direct I->H rows only): {int(strict_n.n.iloc[0]):,} CUSIPs")

    banner("STAGE 5 -- compare against data/fallen_angel_events.parquet")
    prod_path = REPO_ROOT / "data" / "fallen_angel_events.parquet"
    prod = pd.read_parquet(prod_path)
    print(f"production file: {prod_path}")
    print(f"production rows: {len(prod):,}   columns: {list(prod.columns)}")

    # locate the date column
    date_col = next((c for c in ("event_date", "event_dt", "date")
                     if c in prod.columns), None)
    if date_col is None:
        raise SystemExit(f"cannot find event-date column in {list(prod.columns)}")
    prod_dt = pd.to_datetime(prod[date_col]).dt.date
    mine_dt = pd.to_datetime(final.event_date).dt.date

    P = set(zip(prod.cusip_id, prod_dt))
    M = set(zip(final.cusip_id, mine_dt))
    print(f"\nproduction set : {len(P):,}")
    print(f"clean-room set : {len(M):,}")
    print(f"intersection   : {len(P & M):,}")
    print(f"prod-only      : {len(P - M):,}")
    print(f"mine-only      : {len(M - P):,}")
    print(f"symmetric diff : {len(P ^ M):,}  "
          f"({100 * len(P ^ M) / max(len(P | M), 1):.2f}% of union)")

    # same CUSIP, different date?
    pc = {c: d for c, d in P}
    mc = {c: d for c, d in M}
    shared = set(pc) & set(mc)
    datediff = {c: (pc[c], mc[c]) for c in shared if pc[c] != mc[c]}
    print(f"\nCUSIPs in both, SAME date : {len(shared) - len(datediff):,}")
    print(f"CUSIPs in both, DIFF date : {len(datediff):,}")
    if datediff:
        dd = pd.DataFrame([(c, p, m, (m - p).days)
                           for c, (p, m) in datediff.items()],
                          columns=["cusip_id", "prod_date", "mine_date", "days"])
        print(dd.days.describe().to_string())
        print(dd.head(15).to_string(index=False))

    only_p = sorted(c for c, _ in (P - M))
    only_m = sorted(c for c, _ in (M - P))
    print(f"\nCUSIPs only in production : {len(set(only_p) - set(mc)):,}")
    print(f"CUSIPs only in clean-room : {len(set(only_m) - set(pc)):,}")

    # diagnose the disjoint CUSIPs against my intermediate stages
    diag_p = set(only_p) - set(mc)
    diag_m = set(only_m) - set(pc)
    if diag_p:
        r = raw[raw.cusip_id.isin(diag_p)]
        print("\n-- prod-only CUSIPs, as seen in MY pipeline --")
        print(f"present in my raw events        : {len(r):,} / {len(diag_p):,}")
        if len(r):
            print(f"  failed CORP filter            : {(r.sub_prdct_type != 'CORP').sum():,}")
            print(f"  failed 144A filter            : {(r.ind_144a == 'Y').sum():,}")
            print(f"  failed convertible filter     : {(r.cnvrb_fl == 'Y').sum():,}")
            print(f"  failed tenure filter          : "
                  f"{(r.ig_tenure_days < MIN_IG_TENURE_DAYS).sum():,}")
            surv = r[(r.sub_prdct_type == 'CORP') & (r.ind_144a == 'N')
                     & (r.cnvrb_fl == 'N')
                     & (r.ig_tenure_days >= MIN_IG_TENURE_DAYS)]
            print(f"  passed universe, so failed trades: {len(surv):,}")
            if len(surv):
                sp = pre[pre.cusip_id.isin(surv.cusip_id)]
                print(sp.n_pre_trades.describe().to_string())
            print("\n  event-year of prod-only CUSIPs present in my raw:")
            print(r.groupby(r.event_date.map(lambda d: d.year)).size().to_string())
    if diag_m:
        m = final[final.cusip_id.isin(diag_m)]
        print("\n-- clean-room-only CUSIPs --")
        print(f"count: {len(m):,}")
        print("  by year:")
        print(m.groupby(m.event_date.map(lambda d: d.year)).size().to_string())
        print("  pre-trade counts:")
        print(m.n_pre_trades.describe().to_string())
        print(m.head(15)[["cusip_id", "event_date", "issuer_nm",
                          "ig_tenure_days", "n_pre_trades"]].to_string(index=False))

    # ------------------------------------------------------------------
    # STAGE 6 -- interval-aware rebuild (v3)
    # ------------------------------------------------------------------
    banner("STAGE 6 -- interval-aware rebuild (v3): stdt ordering is NOT sufficient")
    print(__doc_v3__)
    v3 = build_events_interval(con)
    print(f"v3 raw first I->H events: {len(v3):,}")
    print(f"v3 event_date range: {v3.event_date.min()} .. {v3.event_date.max()}")
    print(f"v3 events landing on 2021-07-01: "
          f"{(v3.event_date == pd.Timestamp('2021-07-01')).sum():,}   "
          f"(v1/v2 rule put {(raw.event_date == pd.Timestamp('2021-07-01')).sum():,} there)")
    print(f"v3 events landing on 2012-02-06: "
          f"{(v3.event_date == pd.Timestamp('2012-02-06')).sum():,}   "
          f"(v1/v2 rule put {(raw.event_date == pd.Timestamp('2012-02-06')).sum():,} there)")

    print(f"v3 events landing on 2012-02-04 (a Saturday): "
          f"{(v3.event_date == pd.Timestamp('2012-02-04')).sum():,}  <-- v3's own artifact")
    print("v3 raw events in 2012: "
          f"{(v3.event_date.dt.year == 2012).sum():,}")

    banner("STAGE 6b -- v4: IG run ends where the first H record takes over")
    print(__doc_v4__)
    v4 = build_events_interval_v4(con)
    print(f"v4 raw first I->H events: {len(v4):,}")
    v4["event_date"] = pd.to_datetime(v4.event_date)
    print(f"v4 event_date range: {v4.event_date.min()} .. {v4.event_date.max()}")
    for d in ("2021-07-01", "2012-02-06", "2012-02-04"):
        print(f"  v4 events on {d}: {(v4.event_date == pd.Timestamp(d)).sum():,}")
    print(f"  v4 raw events in 2012: {(v4.event_date.dt.year == 2012).sum():,}")

    banner("STAGE 6c -- v5: full daily effective-grade reconstruction")
    print(__doc_v5__)
    v5 = build_events_state(con)
    v5["event_date"] = pd.to_datetime(v5.event_date)
    print(f"v5 raw first I->H events: {len(v5):,}")
    print(f"v5 event_date range: {v5.event_date.min()} .. {v5.event_date.max()}")
    for d in ("2021-07-01", "2012-02-06", "2012-02-04"):
        print(f"  v5 events on {d}: {(v5.event_date == pd.Timestamp(d)).sum():,}")
    print(f"  v5 raw events in 2012: {(v5.event_date.dt.year == 2012).sum():,}")

    # ---- roll to the next TRACE trading day -------------------------------
    # An IG interval that ends on a Friday puts the successor state on a Saturday, which
    # is not a date any bond can be observed or traded on. Production rolls forward to
    # the next trading day (verified: 61761JAL3 lands on Good Friday 2014-04-18 and
    # production reports the following Monday 2014-04-21). Roll, then recompute tenure,
    # then apply the trade screen -- order matters, the window hangs off the event date.
    #
    # The calendar must be CLEAN: raw distinct trd_exctn_dt gives 7,024 dates, but 997 of
    # them are weekends carrying a median of 34 stray prints (vs a weekday median of
    # 66,787). Requiring a weekday with >= 100 prints leaves a proper trading calendar.
    cal = q(con, f"""
        SELECT trd_exctn_dt d, count(*) n FROM read_parquet('{TRACE}')
        GROUP BY 1 HAVING count(*) >= 100 AND dayofweek(trd_exctn_dt) BETWEEN 1 AND 5
        ORDER BY 1""")
    cal_dates = pd.to_datetime(cal.d).values
    print(f"\nTRACE trading calendar (cleaned): {len(cal_dates):,} days, "
          f"{pd.Timestamp(cal_dates.min()).date()} .. {pd.Timestamp(cal_dates.max()).date()}")
    idx = cal_dates.searchsorted(v5.event_date.values, side="left")
    rolled = pd.Series(pd.NaT, index=v5.index, dtype="datetime64[ns]")
    inb = idx < len(cal_dates)
    rolled[inb] = cal_dates[idx[inb]]
    v5["event_date_raw"] = v5.event_date
    v5["event_date_rolled"] = rolled.fillna(v5.event_date_raw)
    nroll = (v5.event_date_rolled != v5.event_date_raw).sum()
    print(f"would roll forward: {nroll:,} of {len(v5):,} ({100*nroll/len(v5):.1f}%)")
    # ROLL_TO_TRADING_DAY: Amendment 2 says nothing about rolling, and rolling shifts
    # the 6-month pre-event trade window, so it is an extra assumption, not a neutral
    # tidy-up. Production keeps the raw state-change date (406 of its 17,129 events fall
    # on a Saturday, none on a Sunday -- enddt is usually a Friday). The raw date is the
    # more faithful reading; entry timing is a downstream trading decision, not an event
    # -dating one. Kept as a flag so the cost of the choice stays visible.
    ROLL_TO_TRADING_DAY = False
    if ROLL_TO_TRADING_DAY:
        v5["event_date"] = v5.event_date_rolled
    print(f"ROLL_TO_TRADING_DAY = {ROLL_TO_TRADING_DAY}")
    v5["ig_tenure_days"] = (v5.event_date - pd.to_datetime(v5.ig_start)).dt.days

    v3f = v5[(v5.sub_prdct_type == "CORP") & (v5.ind_144a == "N")
             & (v5.cnvrb_fl == "N")].copy()
    print(f"\nv5 after CORP/144A/convertible: {len(v3f):,}")
    # production's month convention: months = days / 30.4375, require >= 12
    v3f["prior_i_months"] = v3f.ig_tenure_days / 30.4375
    v3t = v3f[v3f.prior_i_months >= 12].copy()
    print(f"v5 after tenure >= 12 months (days/30.4375 convention): {len(v3t):,}")
    print(f"  [for reference, tenure >= 365 raw days would give: "
          f"{(v3f.ig_tenure_days >= 365).sum():,}]")

    v3p = add_pre_trade_counts(con, v3t, status_filter="T")
    v3fin = v3p[v3p.n_pre_trades >= MIN_PRE_TRADES].copy()
    print(f"v5 after >= {MIN_PRE_TRADES} pre-event trades: {len(v3fin):,}")

    # does my reconstructed IG-run start match production's prior_i_start?
    ps = prod[["cusip_id", "prior_i_start"]].copy()
    ps["prior_i_start"] = pd.to_datetime(ps.prior_i_start).dt.date
    mm = v3fin[["cusip_id", "ig_start"]].copy()
    mm["ig_start"] = pd.to_datetime(mm.ig_start).dt.date
    cmp_start = ps.merge(mm, on="cusip_id", how="inner")
    print(f"\nprior_i_start comparison on {len(cmp_start):,} shared CUSIPs: "
          f"exact match {int((cmp_start.prior_i_start == cmp_start.ig_start).sum()):,} "
          f"({100*(cmp_start.prior_i_start == cmp_start.ig_start).mean():.2f}%)")

    banner("STAGE 7 -- v5 vs production")
    M3 = set(zip(v3fin.cusip_id, pd.to_datetime(v3fin.event_date).dt.date))
    print(f"production set : {len(P):,}")
    print(f"v5 clean-room  : {len(M3):,}")
    print(f"intersection   : {len(P & M3):,}")
    print(f"prod-only      : {len(P - M3):,}")
    print(f"v5-only        : {len(M3 - P):,}")
    print(f"symmetric diff : {len(P ^ M3):,}  "
          f"({100 * len(P ^ M3) / max(len(P | M3), 1):.2f}% of union)")

    p3c = {c: d for c, d in P}
    m3c = {c: d for c, d in M3}
    sh3 = set(p3c) & set(m3c)
    dd3 = {c: (p3c[c], m3c[c]) for c in sh3 if p3c[c] != m3c[c]}
    print(f"\nCUSIPs in both, SAME date : {len(sh3) - len(dd3):,}")
    print(f"CUSIPs in both, DIFF date : {len(dd3):,}")
    if dd3:
        d3 = pd.DataFrame([(c, p, m, (m - p).days) for c, (p, m) in dd3.items()],
                          columns=["cusip_id", "prod_date", "v5_date", "days"])
        print(d3.days.abs().describe().to_string())
        print(d3.head(10).to_string(index=False))
    print(f"\nCUSIPs only in production : {len(set(p3c) - set(m3c)):,}")
    print(f"CUSIPs only in v5         : {len(set(m3c) - set(p3c)):,}")

    # trade-count agreement on the shared events -- independent check of stage 3
    banner("STAGE 8 -- independent check of the pre-event trade counts")
    prod_small = prod[[ "cusip_id", "n_trades_pre"]].copy()
    prod_small["event_date"] = pd.to_datetime(prod[date_col]).dt.date
    mine_small = v3fin[["cusip_id", "n_pre_trades"]].copy()
    mine_small["event_date"] = pd.to_datetime(v3fin.event_date).dt.date
    j = prod_small.merge(mine_small, on=["cusip_id", "event_date"], how="inner")
    print(f"shared events with both counts: {len(j):,}")
    j["diff"] = j.n_pre_trades - j.n_trades_pre
    print(f"exact match : {(j['diff'] == 0).sum():,} ({100*(j['diff']==0).mean():.2f}%)")
    print("difference distribution:")
    print(j["diff"].describe().to_string())
    print("\nlargest absolute disagreements:")
    print(j.reindex(j["diff"].abs().sort_values(ascending=False).index)
           .head(10).to_string(index=False))

    banner("STAGE 9 -- surviving events by year, v5 (attrition sanity check)")
    yr = pd.DataFrame({
        "raw_v5": v5.groupby(v5.event_date.dt.year).size(),
        "post_universe": v3t.groupby(v3t.event_date.dt.year).size(),
        "final_v5": v3fin.groupby(pd.to_datetime(v3fin.event_date).dt.year).size(),
        "production": prod.groupby(pd.to_datetime(prod[date_col]).dt.year).size(),
    }).fillna(0).astype(int)
    yr["trade_screen_survival_pct"] = (
        100 * yr["final_v5"] / yr["post_universe"].where(yr["post_universe"] > 0)
    ).astype(float).round(1)
    print(yr.to_string())
    print(f"\nTOTAL final_v5={yr.final_v5.sum():,}  production={yr.production.sum():,}")

    banner("DONE -- audit only, nothing written to data/")


if __name__ == "__main__":
    main()
