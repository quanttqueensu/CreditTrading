"""A2: insider open-market purchases (Form 4, code P) in CEFs and BDCs -- the zero-trial gate.

    # Every input is a LOCAL CACHE. Nothing below opens a socket or reads an env file.
    python3 scripts/events/a2_insider_buying.py all \
        --edgar-cache "<a worktree>/results/events/_cache_edgar" \
        --crsp-cache  "<a worktree>/results/events/_cache_crsp"
    # parts, in order: fundset extract counts mechanism bdc feasibility gate
    python3 -m pytest scripts/events/tests/test_a2_insider_buying.py

    # TEAM LEAD ONLY -- live EDGAR, reads SEC_USER_AGENT from the env file. Only
    # needed on a clone with no cache; the 2026-10-20 run used existing caches:
    export QUANTT_ENV_FILE=/abs/path/config/.env
    python3 scripts/events/a2_insider_buying.py fetch --max-live 140    # EDGAR: 130 GETs
    python3 scripts/events/a2_insider_buying.py fundset && python3 scripts/events/a2_insider_buying.py extract
    python3 scripts/events/a2_insider_buying.py events
    python3 scripts/events/a2_insider_buying.py pull-crsp               # R2: BDC dsf, < 2023
    python3 scripts/events/a2_insider_buying.py all

ZERO TRIALS. No counter moves. No strategy P&L is formed: there are no
positions, no turnover and no harness here. The mechanism check is an event
study -- the average change in a fund's discount, NAV and price after an
insider purchase, minus the same change on fund-days with the same discount
z-score in the same month. It is descriptive and it decides only whether a
pre-registration is worth writing (team lead, 2026-10-19: "zero-trial checks on
new event paths", path A2).

WHY THIS EXISTS
---------------
A director, officer or the adviser buying a fund's shares below NAV may signal
confidence in the marks (BDCs above all, where most assets are Level 3) or a
coming discount-management action (buyback, tender, distribution change). The
question this desk must answer first is the graveyard's: insiders may simply buy
WIDE discounts, which the live z-score already buys. Then A2 is the book's own
signal with a filing date attached. So the central statistic is INCREMENTAL to
the z-score by construction: event minus same-z, same-month control.

Section 30(h) of the Investment Company Act puts directors, officers, advisory
board members, the adviser, the adviser's affiliated persons and ten-percent
holders of a registered CLOSED-END company under "the same duties and
liabilities as those imposed by section 16" of the Exchange Act: Form 4 within
two business days of the trade (s16(a)(2)(C)), and short-swing profit
disgorgement for any purchase and sale "within any period of less than six
months" (s16(b)). Open-end funds are not covered. `docs/REFERENCES.md` s12ax.

SOURCES (all read from caches built by `scripts/data/edgar_client.py` or the
CRSP R2 extract scripts; this module never constructs an EdgarClient and so
never reads the env file -- it maps a URL to its cache file with the client's
pure `cache_path` and reads the bytes)
-------------------------------------------------------------------------------
* SEC Insider Transactions Data Sets, quarterly ZIPs by FILING date, 2006Q1 ->
  2022Q4 only. SUBMISSION, REPORTINGOWNER, NONDERIV_TRANS. Code P = "Open market
  or private purchase", S = "Open market or private sale" (readme s6.2). The
  data sets carry DATES, not acceptance times.
* EDGAR full-index master files 2008Q1 -> 2022Q4, for the fund set
  (`fetch_edgar_events.fund_set`, the repo's CEF/BDC rule).
* `company_tickers_exchange.json` (the SEC ticker file, as cached) for panel
  ticker -> CIK; the funds in our panels are alive today, so today's map holds.
* `data.sec.gov/submissions/CIK*.json` where cached, for Form 4
  `acceptanceDateTime` (timing only; see FEASIBILITY).
* `data/cef/` (credit universe) and `data/cef_families/` (the C4 families):
  close, NAV, volume, distributions, splits. Read only; nothing is written there.
* CRSP `dsenames` and a `dsf` extract with `date < 2023-01-01` (BDC prices and
  symbol -> permno). Licensed: row-level output stays in the gitignored cache.

HOLDOUTS
--------
* TIME: no ZIP after 2022Q4 is read; every panel and CRSP frame is cut to
  dates < 2023-01-01 BEFORE any window is formed, so a window that would need a
  2023 value is NaN and drops out; `assert_pre_holdout` checks every frame that
  reaches a statistic. Filings after 17:30 ET on 2022-12-30 sit in the 2023Q1
  ZIP (readme s1) and are not seen: a handful at most.
* NAMES: `cef_universe.csv` minus the touched set (the spec universe plus the
  four v6 munis NAD NEA NVG NZF, W4's convention) is the 27-name comparison set.
  It is COUNTED ONLY: `credit_panel()` drops it before any z or outcome exists,
  and `guard_untouched()` raises if one of its tickers reaches a statistic. The
  families panel contains no `cef_universe.csv` fund.

RULES FIXED BEFORE ANY OUTCOME WAS COMPUTED (2026-10-20)
--------------------------------------------------------
Inherited unchanged from the 2026-10-19 census (`research-ss-expansion`,
`scripts/events/ssx/ssx_ins_insider_census.py`, unmerged; ported, not
re-chosen):
* PURCHASE: NONDERIV_TRANS on an ORIGINAL Form 4 (DOCUMENT_TYPE '4'), code P,
  acquired 'A', shares > 0, price > 0, TRANS_DATE within 365 days before
  FILING_DATE; equity title (COMMON|ORDINARY|CLASS X|SHARES|STOCK and not
  PREFERRED|PFD|NOTE|DEBENTURE|BOND|WARRANT|RIGHT|UNIT|DEPOSITARY).
* OWNER CLASSES: 'DO' (director or officer), 'adviser' (name ADVIS[EO]R or
  ADVISORY, or relationship text ADVIS), 'other_person' (Other, not ten-percent,
  a natural person), 'ten_pct_only' (activists and blockholders: EXCLUDED, the
  graveyard's activist row), 'other_entity' (excluded). Qualifying = DO,
  adviser, other_person.
* FUND-EVENT: per fund, the first filing date with a qualifying purchase after
  a >= 90-day gap since the fund's previous event; variants: >= $10k per
  purchase (BDC purchases under $1k look like dividend reinvestment reported as
  P), and >= 2 distinct owners within 30 days ("cluster buy").
* FUND SET: marker forms or N-CSR plus Form 3/4 (the repo's rule); BDC = filed
  N-54A/N-54C, or files 10-K and no N-CSR; CEF = files N-CSR; else fund_other.
New here, fixed before the mechanism ran:
* SALES PLACEBO (H12): the same pipeline on code S, disposed 'D'. The mechanism
  predicts the opposite sign or nothing; the same sign at half the size or more
  means the purchase "effect" is the timing of insider trading windows (after
  a shareholder report or an earnings release), not information.
* SWEEP: an event whose triggering owner filed qualifying purchases in >= 3
  funds within +-5 calendar days (a complex-wide trustee buying round).
* TIMING (FEASIBILITY): a Form 3/4/5 transmitted by 22:00 ET is filed that day
  (Reg S-T 232.13(a)(4)); the book decides 22:00-01:00 ET (docs/RUNNER.md). So
  an event filed on day f is known at the evening decision of t = the first
  session >= f; MOC fill at t+1; earn from t+1's close (`shift(2)`). The "late"
  row decides at t+1 (EDGAR lag, morning backstop).
* OUTCOMES at decision session t, per fund: discount (P/NAV - 1, in percentage
  points) change, NAV total return and price total return from the FILL close
  t+1 to t+1+h, h in (5, 21, 63) sessions, PRIMARY h = 21. Profile: discount
  change from t to t+k, k in (-22, -6, -1, +1, +6, +22, +64). Any window that
  spans a split, a missing close or NAV, or 2023 is NaN and dropped (counted).
* Z: the sleeve's own formula (`src/deploy/sleeves/cef_discount.py`), window
  from the frozen spec, min_periods 120, mean and sd lagged one session, clip
  +-4. Fixed bins: -inf -2 -1.5 -1 -0.5 0 0.5 1 1.5 2 inf (not estimated).
* CONTROLS: fund-days of the same panel with NO qualifying P or S filing from
  63 sessions before to 66 sessions after. Method 1 (primary): cell = (group,
  year-month of t, z bin). Method 2 (second method): cell = (fund, year, z bin).
  Excess = event outcome - cell mean. Mean excess with standard errors
  clustered by year-month of t (CR0 with G/(G-1)).
* BDC (no daily NAV, so no z): price only, CRSP. Cell = (year-month, trailing
  63-session return bin: -inf -20% -10% -5% 0 5% 10% inf).
* GATE (zero-trial; `gate()`): G1 breadth >= 50 events a year (2010-22 mean) on
  the panel sample, else D7; G2 incremental information: primary-h excess
  discount change > 0 with month-clustered t >= 2.0 under method 1, and method 2
  the same sign, else KILL (z in disguise); G3 negative control: the sales
  placebo's method-1 excess must not have the purchases' sign at >= half their
  size, else KILL (artefact); G4 cost: primary-h excess PRICE total return >=
  2 units x 15bp (round trip at the middle of the 5/15/30bp grid), else D2.
  The BDC row (G5) is descriptive: t >= 2.0 recommends fetching BDC NAVs.

ENVIRONMENT: `compute.use_numexpr` off (results/events/numexpr_fault_2026-10-11.txt).

OUTPUTS: aggregates in results/events/a2_insider/ (tracked); row-level tables in
results/events/a2_insider/_cache_a2/ (gitignored; the CRSP-joined ones are
licensed and must stay there).
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data import fetch_edgar_events as fe          # noqa: E402  stdlib + pandas only
from scripts.data.edgar_client import cache_path           # noqa: E402  pure: URL -> cache file

pd.set_option("compute.use_numexpr", False)

OUT = REPO / "results" / "events" / "a2_insider"
CACHE = OUT / "_cache_a2"
DEFAULT_EDGAR_CACHE = REPO / "results" / "events" / "_cache_edgar"
DEFAULT_CRSP_CACHE = REPO / "results" / "events" / "_cache_crsp"
CREDIT_DIR = REPO / "data" / "cef"
FAM_DIR = REPO / "data" / "cef_families"

ZIP_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip"
README_URL = "https://www.sec.gov/files/insider_transactions_readme.pdf"
NY = ZoneInfo("America/New_York")

TIME_HOLDOUT = pd.Timestamp("2023-01-01")
FIRST_Q, LAST_Q = (2006, 1), (2022, 4)           # the data sets start 2006Q1 (readme s2); 2023+ is sealed
INDEX_FIRST_Q = (2008, 1)                        # fetch_edgar_events.LOOKBACK_START
V6_EXTRA = ("NAD", "NEA", "NVG", "NZF")          # traded until 2026-09-28 (W4): touched, not holdout

WINDOW_D, GAP_D, FLOOR_USD = 30, 90, 10_000.0    # inherited from the 2026-10-19 census
SWEEP_DAYS, SWEEP_MIN = 5, 3
HORIZONS = (5, 21, 63)
PRIMARY_H = 21
PROFILE_K = (-22, -6, -1, 1, 6, 22, 64)
CTRL_PRE, CTRL_POST = 63, 1 + max(HORIZONS) + 2  # 66: the longest window plus the late row's day
Z_EDGES = (-np.inf, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, np.inf)
RET_EDGES = (-np.inf, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, np.inf)
TRAIL_RET = 63
COST_GRID_BP = (5.0, 15.0, 30.0)
ROUND_TRIP_UNITS = 2
GATE_T = 2.0
GATE_MIN_EVENTS_YR = 50
GATE_COST_BP = 15.0
PLACEBO_SHARE = 0.5
ERAS = ((2006, 2009), (2010, 2014), (2015, 2019), (2020, 2022))
QUAL_CLASSES = ("DO", "adviser", "other_person")

EQUITY_RE = re.compile(r"COMMON|ORDINARY|CLASS [A-Z]\b|SHARES|STOCK")
NON_EQUITY_RE = re.compile(r"PREFERRED|PFD|NOTE|DEBENTURE|BOND|WARRANT|RIGHT|\bUNITS?\b|DEPOSITARY")
ADVISER_NAME_RE = re.compile(r"ADVIS[EO]RS?\b|ADVISORY")
ADVISER_TXT_RE = re.compile(r"ADVIS|INV\.? ADV")
ENTITY_RE = re.compile(r"\b(?:LLC|L\.L\.C|L\.?P|INC|CORP|CORPORATION|CO|COMPANY|LTD|PLC|GROUP|TRUST|PARTNERS|"
                       r"PARTNERSHIP|FUND|HOLDINGS|MANAGEMENT|CAPITAL|ADVISORS?|ADVISERS?|BANK|INSURANCE|N\.A|S\.A)\b")

SUB_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE",
            "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL"]
OWN_COLS = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TXT"]
TR_COLS = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "TRANS_DATE", "TRANS_CODE",
           "TRANS_SHARES", "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "DIRECT_INDIRECT_OWNERSHIP"]


class HoldoutError(RuntimeError):
    """A sealed date or a sealed name reached a statistic."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ holdout guards

def assert_pre_holdout(dates, what: str) -> None:
    """Raise if any date in `dates` is on or after 2023-01-01 (the sealed time holdout)."""
    d = pd.to_datetime(pd.Index(dates))
    if len(d) and d.max() >= TIME_HOLDOUT:
        raise HoldoutError(f"{what}: a date on or after {TIME_HOLDOUT.date()} ({d.max().date()}) reached a statistic")


def touched_names() -> list[str]:
    """The spec universe (read through scripts/cef/spec.py) plus the four v6 munis."""
    from scripts.cef.spec import UNIVERSE
    return sorted(set(UNIVERSE) | set(V6_EXTRA))


def untouched_names() -> list[str]:
    uni = pd.read_csv(CREDIT_DIR / "cef_universe.csv").ticker.str.upper()
    t = set(touched_names())
    missing = t - set(uni)
    if missing:
        raise ValueError(f"touched names absent from cef_universe.csv: {sorted(missing)}")
    return sorted(set(uni) - t)


def guard_untouched(tickers, what: str) -> None:
    bad = sorted(set(map(str, tickers)) & set(untouched_names()))
    if bad:
        raise HoldoutError(f"{what}: untouched comparison-set names reached a statistic: {bad}")


# ------------------------------------------------------------------ caches (read-only)

def quarters(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    if first > last:
        raise ValueError(f"{first} is after {last}")
    out, (y, q) = [], first
    while (y, q) <= last:
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def cached_body(url: str, caches: list[Path]) -> tuple[bytes, Path]:
    """The cached body of `url` from the first cache that holds it. Never fetches.

    `cache_path` is the EDGAR client's own URL -> file rule, so a cache written by
    any worktree's client reads here unchanged. A miss raises naming the URL and
    every cache searched: the team lead's `fetch` part fills it.
    """
    tried = []
    for c in caches:
        p = cache_path(url, Path(c))
        if p.exists():
            return p.read_bytes(), Path(c)
        tried.append(str(c))
    raise FileNotFoundError(f"not cached: {url} (searched {tried}); the team lead's `fetch` part fills the cache")


def cached_text(url: str, caches: list[Path], encoding: str = "latin-1") -> str:
    body, _ = cached_body(url, caches)
    if body[:2] == b"\x1f\x8b":       # a .gz document, as EdgarClient.get_text unpacks it
        body = gzip.decompress(body)
    return body.decode(encoding)


# ------------------------------------------------------------------ the fund set

def fundset(caches: list[Path]) -> pd.DataFrame:
    """CEF/BDC issuer CIKs from the cached master indexes, 2008Q1-2022Q4, with a kind."""
    keep = fe.MARKER_FORMS | fe.NCSR_FORMS | fe.INSIDER_FORMS | {"10-K", "N-54A", "N-54C"}
    frames = []
    for y, q in quarters(INDEX_FIRST_Q, LAST_Q):
        text = cached_text(fe.INDEX_URL.format(y=y, q=q), caches)
        df = fe.parse_master_index(text, label=f"{y}Q{q}", keep_forms=keep)
        frames.append(df[["cik", "form"]].drop_duplicates())
    idx = pd.concat(frames, ignore_index=True).drop_duplicates()
    return classify_funds(idx)


def classify_funds(idx: pd.DataFrame) -> pd.DataFrame:
    """The census's kind rule on an index frame of (cik, form)."""
    rule = fe.fund_set(idx)
    forms = idx.groupby("cik").form.agg(lambda s: set(s))
    rows = []
    for cik, r in rule.items():
        f = forms.get(cik, set())
        if f & {"N-54A", "N-54C"} or ("10-K" in f and "N-CSR" not in f):
            kind = "BDC"
        elif "N-CSR" in f:
            kind = "CEF"
        else:
            kind = "fund_other"
        rows.append({"cik": int(cik), "set_rule": r, "kind": kind})
    return pd.DataFrame(rows, columns=["cik", "set_rule", "kind"])


# ------------------------------------------------------------------ the insider data sets

def read_table(zf: zipfile.ZipFile, table: str, cols: list[str], label: str) -> pd.DataFrame:
    """One TSV from an in-memory ZIP (untrusted input: nothing is extracted to disk)."""
    names = {Path(n).name.upper(): n for n in zf.namelist()}
    key = f"{table}.TSV"
    if key not in names:
        raise KeyError(f"{label}: ZIP has no {key} (members: {sorted(names)})")
    df = pd.read_csv(io.BytesIO(zf.read(names[key])), sep="\t", dtype=str, keep_default_na=False,
                     na_values=[""], quoting=3, encoding="utf-8", encoding_errors="replace", on_bad_lines="error")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{label} {table}: columns {missing} absent (have {list(df.columns)})")
    return df[cols]


def parse_dates(s: pd.Series) -> pd.Series:
    """DD-MON-YYYY (readme s5). Unparseable stays NaT and is COUNTED by the caller."""
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


def extract_quarter(body: bytes, label: str, fund_ciks: set[int]) -> tuple[pd.DataFrame, dict]:
    """Code P and S rows on fund issuers, joined to SUBMISSION and REPORTINGOWNER (one row per owner)."""
    zf = zipfile.ZipFile(io.BytesIO(body))
    sub = read_table(zf, "SUBMISSION", SUB_COLS, label)
    own = read_table(zf, "REPORTINGOWNER", OWN_COLS, label)
    tr = read_table(zf, "NONDERIV_TRANS", TR_COLS, label)
    if sub.empty or tr.empty:
        raise RuntimeError(f"{label}: empty SUBMISSION or NONDERIV_TRANS")
    if sub.ACCESSION_NUMBER.duplicated().any():
        raise RuntimeError(f"{label}: SUBMISSION has duplicate accession numbers (its primary key)")
    sub = sub.assign(issuercik=pd.to_numeric(sub.ISSUERCIK, errors="raise").astype("int64"))
    t = tr[tr.TRANS_CODE.isin(["P", "S"])]
    p = t.merge(sub, on="ACCESSION_NUMBER", how="left", validate="many_to_one")
    if p.FILING_DATE.isna().any():
        raise RuntimeError(f"{label}: {int(p.FILING_DATE.isna().sum())} code P/S rows have no SUBMISSION row")
    n_ps = len(p)
    p = p[p.issuercik.isin(fund_ciks)]
    p = p.merge(own, on="ACCESSION_NUMBER", how="left", validate="many_to_many")
    if p.RPTOWNERCIK.isna().any():
        raise RuntimeError(f"{label}: {int(p.RPTOWNERCIK.isna().sum())} fund P/S rows have no REPORTINGOWNER")
    p["FILING_DATE"] = parse_dates(p.FILING_DATE)
    p["TRANS_DATE"] = parse_dates(p.TRANS_DATE)
    if p.FILING_DATE.isna().any():
        raise RuntimeError(f"{label}: unparseable FILING_DATE on {int(p.FILING_DATE.isna().sum())} rows")
    for c in ("TRANS_SHARES", "TRANS_PRICEPERSHARE"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    p["ownercik"] = pd.to_numeric(p.RPTOWNERCIK, errors="raise").astype("int64")
    diag = {"quarter": label, "submissions": int(len(sub)), "p_s_rows_all_issuers": int(n_ps),
            "fund_p_s_rows_x_owner": int(len(p)),
            "fund_unparsed_trans_date": int(p.TRANS_DATE.isna().sum()),
            "fund_unparsed_shares_or_price": int((p.TRANS_SHARES.isna() | p.TRANS_PRICEPERSHARE.isna()).sum()),
            "max_filing_date": str(p.FILING_DATE.max().date()) if len(p) else None}
    return p.drop(columns=["ISSUERCIK", "RPTOWNERCIK"]), diag


def extract(caches: list[Path], fset: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    ciks = set(fset.cik.astype("int64"))
    frames, diags = [], []
    for y, q in quarters(FIRST_Q, LAST_Q):
        body, src = cached_body(ZIP_URL.format(y=y, q=q), caches)
        p, d = extract_quarter(body, f"{y}Q{q}", ciks)
        d["cache"] = src.parent.parent.parent.name if src.name == "_cache_edgar" else str(src)
        frames.append(p)
        diags.append(d)
    rows = pd.concat(frames, ignore_index=True)
    assert_pre_holdout(rows.FILING_DATE, "extract")
    return rows, diags


# ------------------------------------------------------------------ owners, purchases, events

def classify_owners(f: pd.DataFrame) -> pd.Series:
    """The census's owner classes (module docstring). Relationship flags are substring
    tests because the field is comma-joined and sometimes missing the comma."""
    rel = f.RPTOWNER_RELATIONSHIP.fillna("")
    is_do = rel.str.contains("Director") | rel.str.contains("Officer")
    is_ten = rel.str.contains("TenPercent")
    is_oth = rel.str.contains("Other")
    nm = f.RPTOWNERNAME.fillna("").str.upper()
    txt = f.RPTOWNER_TXT.fillna("").str.upper()
    adv = nm.str.contains(ADVISER_NAME_RE) | txt.str.contains(ADVISER_TXT_RE)
    entity = nm.str.contains(ENTITY_RE)
    return pd.Series(np.select([is_do, adv, is_oth & ~is_ten & ~entity, is_ten],
                               ["DO", "adviser", "other_person", "ten_pct_only"], default="other_entity"),
                     index=f.index)


def equity_title(title: pd.Series) -> pd.Series:
    t = title.fillna("").str.upper()
    return t.str.contains(EQUITY_RE) & ~t.str.contains(NON_EQUITY_RE)


def qualifying(rows: pd.DataFrame, code: str) -> tuple[pd.DataFrame, dict]:
    """Original-Form-4 open-market rows of `code` ('P' or 'S') by qualifying owners.

    One row per (accession, transaction, owner). Rows dropped at each step are
    counted, never coerced: an unparseable trade date is a dropped row.
    """
    if code not in ("P", "S"):
        raise ValueError(f"code must be P or S, got {code!r}")
    ad = "A" if code == "P" else "D"
    d = rows[(rows.TRANS_CODE == code)]
    n0 = d.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]).shape[0]
    d = d[d.DOCUMENT_TYPE == "4"]
    n1 = d.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]).shape[0]
    d = d[(d.TRANS_ACQUIRED_DISP_CD == ad) & (d.TRANS_SHARES > 0) & (d.TRANS_PRICEPERSHARE > 0)]
    lag = (d.FILING_DATE - d.TRANS_DATE).dt.days
    bad = d.TRANS_DATE.isna() | (lag < 0) | (lag > 365)
    n_bad = int(bad.sum())
    d = d[~bad]
    d = d[equity_title(d.SECURITY_TITLE)].copy()
    d["oclass"] = classify_owners(d)
    classes = d.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "ownercik"]).oclass.value_counts().to_dict()
    d = d[d.oclass.isin(QUAL_CLASSES)].copy()
    d["usd"] = d.TRANS_SHARES * d.TRANS_PRICEPERSHARE
    d = d.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "ownercik"])
    diag = {"code": code, "trans_all_doc_types": int(n0), "trans_original_form4": int(n1),
            "date_error_rows_dropped": n_bad, "owner_class_rows_equity": {k: int(v) for k, v in classes.items()},
            "qualifying_rows": int(len(d)),
            "qualifying_trans": int(d.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]).shape[0])}
    return d, diag


def fund_events(d: pd.DataFrame, min_owners: int, window_d: int = WINDOW_D, gap_d: int = GAP_D) -> pd.DataFrame:
    """Per fund: the first filing date with >= `min_owners` distinct qualifying owners
    (trades in the trailing `window_d` days, filed by then) after a `gap_d`-day gap.

    The event's point-in-time date is the filing date `f` of the filing that
    completed it. Nothing filed before the previous event re-enters. Ported from
    the 2026-10-19 census, with the triggering filing's trade date and price added.
    """
    cols = ["issuercik", "event_date", "symbol", "issuername", "trigger_owner", "trigger_trade_date",
            "trigger_price", "owner_classes", "n_owners", "usd", "min_trans_usd", "max_trans_usd"]
    out = []
    for cik, g in d.groupby("issuercik", sort=False):
        g = g.sort_values(["FILING_DATE", "TRANS_DATE"])
        fd, td, own = g.FILING_DATE.values, g.TRANS_DATE.values, g.ownercik.values
        last = None
        for f in g.FILING_DATE.drop_duplicates().values:
            if last is not None and f <= last + np.timedelta64(gap_d, "D"):
                continue
            m = (fd <= f) & (td >= f - np.timedelta64(window_d, "D"))
            if last is not None:
                m &= fd > last
            if len(set(own[m])) >= min_owners:
                q = g[m]
                trig = q[q.FILING_DATE == q.FILING_DATE.max()]
                tx = q.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"])
                ttx = trig.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"])
                out.append({"issuercik": int(cik), "event_date": pd.Timestamp(f),
                            "symbol": str(trig.ISSUERTRADINGSYMBOL.iloc[-1]).strip().upper(),
                            "issuername": trig.ISSUERNAME.iloc[-1],
                            "trigger_owner": int(trig.ownercik.iloc[0]),
                            "trigger_trade_date": ttx.TRANS_DATE.max(),
                            "trigger_price": float((ttx.usd.sum()) / ttx.TRANS_SHARES.sum()),
                            "owner_classes": "|".join(sorted(set(q.oclass))),
                            "n_owners": int(len(set(own[m]))), "usd": float(tx.usd.sum()),
                            "min_trans_usd": float(tx.usd.min()), "max_trans_usd": float(tx.usd.max())})
                last = f
    return pd.DataFrame(out, columns=cols)


def sweep_counts(ev: pd.DataFrame, d: pd.DataFrame, days: int = SWEEP_DAYS) -> pd.Series:
    """For each event: distinct funds in which its triggering owner filed a qualifying row within +-`days`."""
    by_owner = {o: g[["FILING_DATE", "issuercik"]].drop_duplicates() for o, g in d.groupby("ownercik")}
    n = []
    for r in ev.itertuples(index=False):
        g = by_owner.get(r.trigger_owner)
        if g is None:
            raise KeyError(f"event owner {r.trigger_owner} has no qualifying rows: the event table and rows disagree")
        w = g[(g.FILING_DATE >= r.event_date - pd.Timedelta(days=days)) &
              (g.FILING_DATE <= r.event_date + pd.Timedelta(days=days))]
        n.append(int(w.issuercik.nunique()))
    return pd.Series(n, index=ev.index, dtype="int64")


def build_events(rows: pd.DataFrame, fset: pd.DataFrame) -> dict:
    """Qualifying rows and event tables for purchases (three declared variants) and sales."""
    kind = dict(zip(fset.cik.astype("int64"), fset.kind))
    res = {"diag": {}}
    for code in ("P", "S"):
        d, diag = qualifying(rows, code)
        d["kind"] = d.issuercik.map(kind)
        if d.kind.isna().any():
            raise RuntimeError(f"{int(d.kind.isna().sum())} qualifying rows on issuers outside the fund set")
        res["diag"][code] = diag
        res[f"rows_{code}"] = d
        base = fund_events(d, 1)
        base["kind"] = base.issuercik.map(kind)
        base["n_funds_owner_pm5d"] = sweep_counts(base, d)
        base["sweep"] = base.n_funds_owner_pm5d >= SWEEP_MIN
        base["adviser"] = base.owner_classes.str.contains("adviser")
        res[f"ev_{code}"] = base
        if code == "P":
            fl = fund_events(d[d.usd >= FLOOR_USD], 1)
            two = fund_events(d, 2)
            res["ev_P_floor"] = fl.assign(kind=fl.issuercik.map(kind))
            res["ev_P_2own"] = two.assign(kind=two.issuercik.map(kind))
    for k in ("ev_P", "ev_S", "ev_P_floor", "ev_P_2own"):
        assert_pre_holdout(res[k].event_date, k)
    return res


# ------------------------------------------------------------------ panels (read-only, cut before 2023)

def _wide(d: pd.DataFrame, col: str) -> pd.DataFrame:
    if d.duplicated(["date", "ticker"]).any():
        raise ValueError(f"duplicate (date, ticker) rows in the {col} panel")
    return d.pivot(index="date", columns="ticker", values=col).sort_index()


def _align_events(sessions: pd.DatetimeIndex, ev: pd.DataFrame, date_col: str, val_col: str,
                  tickers) -> pd.DataFrame:
    """Sum `val_col` onto the first session on or after each `date_col` (ex-dates, splits)."""
    out = pd.DataFrame(0.0, index=sessions, columns=list(tickers))
    e = ev[ev.ticker.isin(out.columns)]
    pos = sessions.searchsorted(e[date_col].values, side="left")
    ok = pos < len(sessions)
    for p, tk, v in zip(pos[ok], e.ticker.values[ok], e[val_col].values[ok]):
        out.iat[p, out.columns.get_loc(tk)] += float(v)
    return out


def _panel(P: pd.DataFrame, N: pd.DataFrame, tickers, dist: pd.DataFrame, splits: pd.DataFrame,
           group: dict, sub: dict) -> dict:
    """Price, NAV and volume on the sleeve's rule (inner join, NAV and close > 0.5), cut before 2023."""
    P = P[P.ticker.isin(tickers)]
    N = N[N.ticker.isin(tickers)]
    d = P[["date", "ticker", "close", "volume"]].merge(N[["date", "ticker", "nav"]], on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d.date)
    d = d[(d.nav > 0.5) & (d.close > 0.5) & (d.date < TIME_HOLDOUT)]
    px, nav, vol = _wide(d, "close"), _wide(d, "nav"), _wide(d, "volume")
    assert_pre_holdout(px.index, "panel")
    s = px.index
    dist = dist[pd.to_datetime(dist.date) < TIME_HOLDOUT].assign(date=lambda x: pd.to_datetime(x.date))
    splits = splits[pd.to_datetime(splits.date) < TIME_HOLDOUT].assign(date=lambda x: pd.to_datetime(x.date), one=1.0)
    return {"px": px, "nav": nav, "vol": vol,
            "dist": _align_events(s, dist, "date", "amount", px.columns),
            "split": _align_events(s, splits, "date", "one", px.columns),
            "group": pd.Series(group).reindex(px.columns), "sub": pd.Series(sub).reindex(px.columns)}


def credit_panel() -> dict:
    """The touched credit names only. The untouched 27 are dropped here, before anything is computed."""
    tk = touched_names()
    P = pd.read_parquet(CREDIT_DIR / "cef_prices.parquet")
    N = pd.read_parquet(CREDIT_DIR / "cef_nav.parquet")
    D = pd.read_parquet(CREDIT_DIR / "cef_distributions.parquet")
    S = pd.read_parquet(CREDIT_DIR / "cef_splits.parquet")
    dist = D[D.amount > 0].rename(columns={"ex_date": "date"})[["date", "ticker", "amount"]]
    splits = pd.concat([D[D.stock_split != 0].rename(columns={"ex_date": "date"})[["date", "ticker"]],
                        S.rename(columns={"ex_date": "date"})[["date", "ticker"]]], ignore_index=True)
    sub = P.drop_duplicates("ticker").set_index("ticker").grp.to_dict()
    pan = _panel(P, N, tk, dist, splits, {t: "credit" for t in tk}, {t: sub.get(t) for t in tk})
    guard_untouched(pan["px"].columns, "credit panel")
    return pan


def families_panel() -> dict:
    U = pd.read_csv(FAM_DIR / "universe.csv")
    U = U[U.included.astype(bool)]
    if U.in_cef_universe_csv.astype(bool).any():
        raise HoldoutError("a families fund is in cef_universe.csv: the families panel would touch the comparison set")
    P = pd.read_parquet(FAM_DIR / "cef_prices.parquet")
    N = pd.read_parquet(FAM_DIR / "cef_nav.parquet")
    A = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
    dist = A[A.dividends > 0].rename(columns={"dividends": "amount"})[["date", "ticker", "amount"]]
    splits = A[A.stock_splits != 0][["date", "ticker"]]
    fam = dict(zip(U.ticker, U.family))
    pan = _panel(P, N, list(U.ticker), dist, splits, fam, dict(zip(U.ticker, U["sub"])))
    guard_untouched(pan["px"].columns, "families panel")
    return pan


# ------------------------------------------------------------------ signal and outcomes

def zscore(disc: pd.DataFrame, window: int) -> pd.DataFrame:
    """The sleeve's z (cef_discount.target_positions): mean and sd over `window` sessions
    lagged one session, min_periods 120, clip +-4. z at t uses discounts through t
    for the level and through t-1 for the mean and sd: no lookahead."""
    mu = disc.rolling(window, min_periods=120).mean().shift(1)
    sd = disc.rolling(window, min_periods=120).std().shift(1)
    return ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)


def bin_of(x: pd.Series, edges) -> pd.Series:
    return pd.cut(x, bins=list(edges), labels=False, right=False).astype("float")


def _shift(df: pd.DataFrame, k: int) -> pd.DataFrame:
    """Value at session t+k, indexed at t (k may be negative). Beyond the panel: NaN."""
    return df.shift(-k)


def window_mask(count_cum: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    """True where no counted event (split, missing value) falls in sessions [t+lo, t+hi]."""
    a = _shift(count_cum, hi)
    b = _shift(count_cum, lo - 1) if lo - 1 != 0 else count_cum
    b = b.fillna(0.0) if lo - 1 < 0 else b
    return (a - b) == 0


def tr_window(level: pd.DataFrame, dist: pd.DataFrame, split_cum: pd.DataFrame, a: int, b: int) -> pd.DataFrame:
    """Total return over the close-to-close window (t+a, t+b], b > a, distributions added
    on ex-dates. A window spanning a missing value, a split or the end of the panel is NaN."""
    if b <= a:
        raise ValueError("tr_window needs b > a")
    r = (level + dist) / level.shift(1) - 1.0
    bad = r.isna().astype(float).cumsum()
    L = np.log1p(r).fillna(0.0).cumsum()
    out = np.exp(_shift(L, b) - _shift(L, a)) - 1.0
    ok = (_shift(bad, b) - _shift(bad, a) == 0) & window_mask(split_cum, a, b)
    return out.where(ok)


def disc_change(disc: pd.DataFrame, split_cum: pd.DataFrame, a: int, b: int) -> pd.DataFrame:
    """disc(t+b) - disc(t+a), percentage points; NaN across a split."""
    lo, hi = min(a, b), max(a, b)
    return (_shift(disc, b) - _shift(disc, a)).where(window_mask(split_cum, lo, hi))


def outcome_frames(pan: dict, window: int) -> dict[str, pd.DataFrame]:
    """Every per-fund quantity the event study reads, indexed at decision session t.

    Execution convention (H1, shift(2)): decide on t's close and NAV in the evening,
    MOC fill at t+1's close, earn from t+1. So post-event windows run (t+1, t+1+h].
    """
    px, nav, vol = pan["px"], pan["nav"], pan["vol"]
    disc = 100.0 * (px - nav) / nav
    sc = pan["split"].cumsum()
    f = {"disc": disc, "z": zscore(disc, window),
         "adv": (px * vol).rolling(63, min_periods=21).mean().shift(1)}
    for h in HORIZONS:
        f[f"dd_{h}"] = disc_change(disc, sc, 1, 1 + h)
        f[f"nav_{h}"] = tr_window(nav, pan["dist"], sc, 1, 1 + h)
        f[f"px_{h}"] = tr_window(px, pan["dist"], sc, 1, 1 + h)
    f[f"dd_late_{PRIMARY_H}"] = disc_change(disc, sc, 2, 2 + PRIMARY_H)
    f[f"px_late_{PRIMARY_H}"] = tr_window(px, pan["dist"], sc, 2, 2 + PRIMARY_H)
    for k in PROFILE_K:
        f[f"prof_{k}"] = disc_change(disc, sc, 0, k)
    return f


def long_frame(frames: dict[str, pd.DataFrame], pan: dict) -> pd.DataFrame:
    """Stack to one row per (date, ticker) with a finite z; add group, cell keys."""
    st = {k: v.stack(future_stack=True) for k, v in frames.items()}
    L = pd.DataFrame(st)
    L.index.names = ["date", "ticker"]
    L = L[L.z.notna()].reset_index()
    assert_pre_holdout(L.date, "long frame")
    L["group"] = L.ticker.map(pan["group"])
    L["sub"] = L.ticker.map(pan["sub"])
    L["ym"] = L.date.dt.to_period("M").astype(str)
    L["year"] = L.date.dt.year
    L["zbin"] = bin_of(L.z, Z_EDGES)
    return L


def control_mask(pan: dict, filing_sessions: dict[str, list[pd.Timestamp]]) -> pd.DataFrame:
    """True where fund-day t has no qualifying P or S filing in sessions [t-CTRL_PRE, t+CTRL_POST]."""
    s = pan["px"].index
    ind = pd.DataFrame(0.0, index=s, columns=pan["px"].columns)
    for tk, dates in filing_sessions.items():
        if tk not in ind.columns:
            continue
        pos = s.searchsorted(pd.to_datetime(pd.Index(dates)).values, side="left")
        for p in pos[pos < len(s)]:
            ind.iat[p, ind.columns.get_loc(tk)] += 1.0
    C = ind.cumsum()
    hi = C.shift(-CTRL_POST).ffill()           # beyond the panel: no later filing is visible (sealed)
    lo = C.shift(CTRL_PRE + 1).fillna(0.0)
    return (hi - lo) == 0


def matched_excess(ev: pd.DataFrame, ctrl: pd.DataFrame, keys: list[str], cols: list[str]) -> pd.DataFrame:
    """Event outcome minus the mean of control fund-days in the same cell."""
    g = ctrl.groupby(keys, observed=True)
    cm = g[cols].mean().add_suffix("_ctrl")
    cn = g.size().rename("n_ctrl")
    m = ev.join(cm, on=keys).join(cn, on=keys)
    for c in cols:
        m[f"x_{c}"] = m[c] - m[f"{c}_ctrl"]
    return m


def clustered(x: pd.Series, g: pd.Series) -> dict:
    """Mean with a cluster-robust standard error (CR0 x G/(G-1)), clusters `g`."""
    ok = x.notna() & g.notna()
    x, g = x[ok].astype(float), g[ok]
    n, G = len(x), int(g.nunique())
    if n == 0:
        return {"n": 0, "G": 0, "mean": np.nan, "se": np.nan, "t": np.nan, "median": np.nan}
    m = float(x.mean())
    if G < 2:
        return {"n": n, "G": G, "mean": m, "se": np.nan, "t": np.nan, "median": float(x.median())}
    u = (x - m).groupby(g).sum()
    se = float(np.sqrt(G / (G - 1) * (u ** 2).sum()) / n)
    return {"n": n, "G": G, "mean": m, "se": se, "t": m / se if se > 0 else np.nan, "median": float(x.median())}


# ------------------------------------------------------------------ panel funds -> CIK

def panel_cik_map(caches: list[Path]) -> pd.DataFrame:
    """Every panel ticker with its CIK from the SEC ticker file, and which set it is in.

    The ticker file is today's map; every panel fund trades today, and a fund's CIK
    does not change with its ticker, so it is the fund's CIK across its history.
    A ticker missing from the file is reported, never guessed.
    """
    j = json.loads(cached_text(fe.TICKERS_URL, caches, "utf-8"))
    if j.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ValueError(f"company_tickers_exchange.json fields changed: {j.get('fields')}")
    t = pd.DataFrame(j["data"], columns=j["fields"])
    if t.ticker.duplicated().any():
        raise ValueError("the SEC ticker file maps one ticker to two CIKs")
    ck = dict(zip(t.ticker, t.cik.astype("int64")))
    touched, untouched = set(touched_names()), set(untouched_names())
    U = pd.read_csv(FAM_DIR / "universe.csv")
    U = U[U.included.astype(bool)]
    rows = [{"ticker": x, "set": "credit_touched" if x in touched else "credit_untouched"}
            for x in sorted(touched | untouched)]
    rows += [{"ticker": x, "set": "families"} for x in sorted(U.ticker)]
    m = pd.DataFrame(rows)
    m["cik"] = m.ticker.map(ck).astype("Int64")
    dup = m.dropna(subset=["cik"]).cik.duplicated(keep=False)
    if dup.any():
        raise ValueError(f"two panel tickers share a CIK: {m.dropna(subset=['cik'])[dup].to_dict('records')}")
    return m


# ------------------------------------------------------------------ the mechanism check

OUTCOME_COLS = ([f"{p}_{h}" for h in HORIZONS for p in ("dd", "nav", "px")]
                + [f"dd_late_{PRIMARY_H}", f"px_late_{PRIMARY_H}"] + [f"prof_{k}" for k in PROFILE_K])


def attach_events(ev: pd.DataFrame, L: pd.DataFrame, pan: dict, cik_to_ticker: dict, label: str) -> tuple[pd.DataFrame, dict]:
    """Events on this panel's funds at their decision session t (the first session >= filing date)."""
    e = ev[ev.issuercik.isin(cik_to_ticker)].copy()
    n0 = len(e)
    e["ticker"] = e.issuercik.map(cik_to_ticker)
    s = pan["px"].index
    pos = s.searchsorted(e.event_date.values, side="left")
    e = e[pos < len(s)].copy()
    n_after_end = n0 - len(e)
    e["date"] = s[s.searchsorted(e.event_date.values, side="left")]
    # NAV at the insider's own trade (the last NAV on or before the trade date).
    navf = pan["nav"].ffill(limit=5)
    tpos = s.searchsorted(e.trigger_trade_date.values, side="right") - 1
    nav_t = [navf.iat[p, navf.columns.get_loc(tk)] if p >= 0 else np.nan for p, tk in zip(tpos, e.ticker)]
    e["prem_trade"] = e.trigger_price.values / np.asarray(nav_t, dtype=float) - 1.0
    m = e.merge(L, on=["date", "ticker"], how="left", validate="many_to_one")
    n_no_z = int(m.z.isna().sum())
    m = m[m.z.notna()].copy()
    m["sample"] = label
    return m, {"events_on_panel_funds": int(n0), "after_last_pre2023_session": int(n_after_end),
               "no_row_or_no_z_at_t": n_no_z, "usable": int(len(m))}


def run_panel(name: str, pan: dict, cmap: pd.DataFrame, evs: dict, window: int) -> dict:
    sets = ("credit_touched",) if name == "credit" else ("families",)
    sub = cmap[cmap.set.isin(sets) & cmap.cik.notna()]
    cik_to_ticker = {int(c): t for c, t in zip(sub.cik, sub.ticker) if t in pan["px"].columns}
    frames = outcome_frames(pan, window)
    L = long_frame(frames, pan)
    guard_untouched(L.ticker.unique(), f"{name} long frame")
    filings: dict[str, list] = {}
    for code in ("P", "S"):
        r = evs[f"rows_{code}"]
        r = r[r.issuercik.isin(cik_to_ticker)]
        for cik, g in r.groupby("issuercik"):
            filings.setdefault(cik_to_ticker[int(cik)], []).extend(g.FILING_DATE.drop_duplicates().tolist())
    cm = control_mask(pan, filings).stack(future_stack=True)
    cm.index.names = ["date", "ticker"]
    L = L.join(cm.rename("ctrl"), on=["date", "ticker"])
    if L.ctrl.isna().any():
        raise RuntimeError(f"{name}: control mask misaligned with the long frame")
    out = {"L": L, "events": [], "diag": {}}
    for label, key in (("purchases", "ev_P"), ("purchases_floor10k", "ev_P_floor"),
                       ("purchases_2owners", "ev_P_2own"), ("sales_placebo", "ev_S")):
        m, d = attach_events(evs[key], L, pan, cik_to_ticker, label)
        guard_untouched(m.ticker.unique(), f"{name} {label}")
        out["events"].append(m)
        out["diag"][label] = d
    return out


def summarise(m: pd.DataFrame, label: str, method: str, cols: list[str]) -> list[dict]:
    rows = []
    for c in cols:
        r = clustered(m[f"x_{c}"], m.ym)
        scale = 1.0 if c.startswith(("dd", "prof")) else 1e4      # pp for discounts, bp for returns
        rows.append({"sample": label, "method": method, "outcome": c,
                     "unit": "pp" if scale == 1.0 else "bp", "n": r["n"], "months": r["G"],
                     "mean_excess": r["mean"] * scale, "se": r["se"] * scale, "t": r["t"],
                     "median_excess": r["median"] * scale,
                     "mean_event": float(m.loc[m[f"x_{c}"].notna(), c].mean()) * scale,
                     "mean_control": float(m.loc[m[f"x_{c}"].notna(), f"{c}_ctrl"].mean()) * scale,
                     "events_without_cell": int((m[c].notna() & m[f"{c}_ctrl"].isna()).sum())})
    return rows


METHODS = {"m1_group_month_zbin": ["group", "ym", "zbin"], "m2_fund_year_zbin": ["ticker", "year", "zbin"]}


def strata(E: pd.DataFrame) -> dict[str, pd.Series]:
    """Declared strata of the base purchase events (module docstring)."""
    credit_like = E.group.isin(["credit", "preferred", "multi_asset"])
    s = {"all": pd.Series(True, index=E.index), "credit_touched": E.group == "credit",
         "credit_like (credit, preferred, multi_asset)": credit_like, "equity families": ~credit_like}
    for g in sorted(E.group.dropna().unique()):
        s[f"group={g}"] = E.group == g
    s.update({"adviser involved": E.adviser.astype(bool), "not adviser": ~E.adviser.astype(bool),
              "sweep (owner bought >=3 funds +-5d)": E.sweep.astype(bool), "single-fund buy": ~E.sweep.astype(bool),
              "bought below NAV at trade": E.prem_trade < 0, "bought at/above NAV": E.prem_trade >= 0,
              "z(t) < -1": E.z < -1, "z(t) >= -1": E.z >= -1})
    for a, b in ERAS:
        s[f"era {a}-{b}"] = E.date.dt.year.between(a, b)
    return s


def mechanism(caches: list[Path], evs: dict) -> dict:
    from scripts.cef.spec import Z_WINDOW
    cmap = panel_cik_map(caches)
    runs = {"credit": run_panel("credit", credit_panel(), cmap, evs, Z_WINDOW),
            "families": run_panel("families", families_panel(), cmap, evs, Z_WINDOW)}
    L = pd.concat([r["L"] for r in runs.values()], ignore_index=True)
    E = pd.concat([m for r in runs.values() for m in r["events"]], ignore_index=True)
    assert_pre_holdout(L.date, "controls")
    assert_pre_holdout(E.date, "events")
    guard_untouched(set(L.ticker) | set(E.ticker), "mechanism")
    C = L[L.ctrl]
    rows, prof = [], []
    matched = {}
    for method, keys in METHODS.items():
        for label in E["sample"].unique():
            m = matched_excess(E[E["sample"] == label], C, keys, OUTCOME_COLS)
            matched[(method, label)] = m
            rows += summarise(m, label, method, [c for c in OUTCOME_COLS if not c.startswith("prof")])
            prof += summarise(m, label, method, [f"prof_{k}" for k in PROFILE_K])
    main = pd.DataFrame(rows)
    # Strata: method 1, base purchases and the sales placebo, primary horizon and its price return.
    srows = []
    for label in ("purchases", "sales_placebo"):
        m = matched[("m1_group_month_zbin", label)]
        for sname, mask in strata(m).items():
            for c in (f"dd_{PRIMARY_H}", f"nav_{PRIMARY_H}", f"px_{PRIMARY_H}"):
                srows += [dict(r, stratum=sname) for r in summarise(m[mask], label, "m1_group_month_zbin", [c])]
    st = pd.DataFrame(srows)
    # Is it the z-score in disguise? z at t for events against every fund-day.
    zrows = []
    for grp_name, mask_L, mask_E in (("all", L.index == L.index, E.index == E.index),
                                     ("credit_touched", L.group == "credit", E.group == "credit"),
                                     ("families", L.group != "credit", E.group != "credit")):
        for lab, z in (("all fund-days", L.loc[mask_L, "z"]),
                       ("control fund-days", L.loc[mask_L & L.ctrl, "z"]),
                       ("purchase events", E.loc[mask_E & (E["sample"] == "purchases"), "z"]),
                       ("sales events", E.loc[mask_E & (E["sample"] == "sales_placebo"), "z"])):
            zrows.append({"panel": grp_name, "set": lab, "n": int(z.notna().sum()), "mean_z": float(z.mean()),
                          "median_z": float(z.median()), "share_z_lt_-1": float((z < -1).mean()),
                          "share_z_lt_-2": float((z < -2).mean()), "share_z_gt_+1": float((z > 1).mean())})
    zd = pd.DataFrame(zrows)
    P = E[E["sample"] == "purchases"]
    below = {"purchase_events_with_trade_nav": int(P.prem_trade.notna().sum()),
             "share_bought_below_nav": float((P.prem_trade < 0).mean()),
             "median_premium_at_trade_pct": float(100 * P.prem_trade.median()),
             "sales_share_sold_below_nav": float((E.loc[E["sample"] == "sales_placebo", "prem_trade"] < 0).mean())}
    yr = (P.assign(year=P.date.dt.year).groupby(["year", "group"]).size().unstack(fill_value=0))
    diag = {k: r["diag"] for k, r in runs.items()}
    return {"main": main, "profile": pd.DataFrame(prof), "strata": st, "zdist": zd, "below_nav": below,
            "events_per_year": yr, "diag": diag, "E": E, "L": L, "cmap": cmap,
            "n_control_fund_days": int(len(C)), "n_fund_days": int(len(L)),
            "panel_last_date": str(L.date.max().date())}


# ------------------------------------------------------------------ the double-check (CLAUDE.md: a second method)

def fe_estimate(E: pd.DataFrame, C: pd.DataFrame, keys: list[str], col: str, cluster: str = "ym") -> dict:
    """Pooled OLS of `col` on an event dummy with cell fixed effects (within transformation),
    standard errors clustered by `cluster`. A different weighting of the same contrast as
    `matched_excess`: cells with more events count more."""
    use = list(dict.fromkeys(keys + [col, cluster]))     # `cluster` may also be a cell key
    X = pd.concat([E[use].assign(d=1.0), C[use].assign(d=0.0)], ignore_index=True).dropna(subset=[col] + keys)
    g = X.groupby(keys, observed=True)
    X = X[g.d.transform("max") > 0]                        # cells holding at least one event
    g = X.groupby(keys, observed=True)
    yt = X[col] - g[col].transform("mean")
    dt = X.d - g.d.transform("mean")
    sxx = float((dt * dt).sum())
    if sxx == 0:
        return {"beta": np.nan, "t": np.nan, "n_events": 0}
    beta = float((dt * yt).sum() / sxx)
    e = yt - beta * dt
    u = (dt * e).groupby(X[cluster]).sum()
    G = len(u)
    se = float(np.sqrt(G / (G - 1) * (u ** 2).sum()) / sxx)
    return {"beta": beta, "se": se, "t": beta / se, "n_events": int(X.d.sum()), "n_rows": int(len(X)), "clusters": G}


def raw_recompute(E: pd.DataFrame, n: int = 40, seed: int = 20261020) -> dict:
    """Recompute dd_21 and px_21 for `n` random events straight from the parquet files,
    on the fund's own rows, with none of the frame machinery. Max absolute differences."""
    h = PRIMARY_H
    S = E[E["sample"] == "purchases"].dropna(subset=[f"dd_{h}", f"px_{h}"])
    S = S.sample(min(n, len(S)), random_state=seed)
    cred = set(pd.read_csv(CREDIT_DIR / "cef_universe.csv").ticker)
    diffs = []
    for r in S.itertuples(index=False):
        d = CREDIT_DIR if r.ticker in cred else FAM_DIR
        P = pd.read_parquet(d / "cef_prices.parquet", filters=[("ticker", "==", r.ticker)])
        N = pd.read_parquet(d / "cef_nav.parquet", filters=[("ticker", "==", r.ticker)])
        x = P[["date", "close"]].merge(N[["date", "nav"]], on="date").sort_values("date")
        x = x[(x.nav > .5) & (x.close > .5) & (pd.to_datetime(x.date) < TIME_HOLDOUT)].set_index("date")
        if r.ticker in cred:
            D = pd.read_parquet(CREDIT_DIR / "cef_distributions.parquet")
            D = D[(D.ticker == r.ticker) & (D.amount > 0)].rename(columns={"ex_date": "date"})
        else:
            A = pd.read_parquet(FAM_DIR / "cef_actions.parquet")
            D = A[(A.ticker == r.ticker) & (A.dividends > 0)].rename(columns={"dividends": "amount"})
        i = x.index.get_loc(r.date)
        w = x.iloc[i + 1:i + 2 + h]
        dd = 100 * (w.close.iloc[-1] / w.nav.iloc[-1] - w.close.iloc[0] / w.nav.iloc[0])
        dv = pd.Series(0.0, index=w.index)
        for dte, am in zip(D.date, D.amount):
            if w.index[0] < dte <= w.index[-1]:
                dv.iloc[w.index.searchsorted(dte)] += am
        tr = float(np.prod(((w.close + dv) / w.close.shift(1)).iloc[1:]) - 1)
        diffs.append((abs(dd - getattr(r, f"dd_{h}")), abs(tr - getattr(r, f"px_{h}")) * 1e4))
    a = np.array(diffs)
    return {"n": int(len(a)), "max_abs_dd_diff_pp": float(a[:, 0].max()), "max_abs_px_diff_bp": float(a[:, 1].max())}


def crosscheck(E: pd.DataFrame, L: pd.DataFrame) -> dict:
    C = L[L.ctrl]
    out = {"raw_recompute": raw_recompute(E)}
    for label in ("purchases", "sales_placebo"):
        for col in (f"dd_{PRIMARY_H}", f"px_{PRIMARY_H}", f"nav_{PRIMARY_H}"):
            out[f"fe_m1_{label}_{col}"] = fe_estimate(E[E["sample"] == label], C, METHODS["m1_group_month_zbin"], col)
    return out


# ------------------------------------------------------------------ CRSP (BDC prices, listing status)

def norm_symbol(s: str) -> tuple[str, str | None]:
    """'ABC.B' / 'ABC-B' / 'ABC/B' -> ('ABC', 'B'); 'ABC' -> ('ABC', None)."""
    s = re.sub(r"\s+", "", str(s).upper())
    m = re.match(r"^([A-Z]+)[./\-]([A-Z])$", s)
    return (m.group(1), m.group(2)) if m else (s, None)


def crsp_names(crsp_cache: Path) -> pd.DataFrame:
    n = pd.read_parquet(Path(crsp_cache) / "dsenames.parquet",
                        columns=["permno", "namedt", "nameendt", "shrcd", "ticker", "comnam", "shrcls"])
    n["namedt"] = pd.to_datetime(n.namedt)
    n["nameendt"] = pd.to_datetime(n.nameendt)
    return n[n.ticker.notna()]


def link_symbols(ev: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
    """Symbol as filed -> one CRSP permno whose name record spans the event date; else unlinked."""
    by_t = {t: g for t, g in names.groupby("ticker")}
    perm, stage = [], []
    for r in ev.itertuples(index=False):
        base, cls = norm_symbol(r.symbol)
        g = by_t.get(base)
        c = g[(g.namedt <= r.event_date) & (g.nameendt >= r.event_date)] if g is not None else names.iloc[:0]
        if cls is not None and c.permno.nunique() > 1:
            c = c[c.shrcls.fillna("") == cls]
        if c.permno.nunique() == 1:
            perm.append(int(c.permno.iloc[0]))
            stage.append("exact" if cls is None else "class_suffix")
        else:
            perm.append(np.nan)
            stage.append("none" if c.empty else "ambiguous")
    return ev.assign(permno=pd.array(perm, dtype="Int64"), link=stage)


def crsp_dsf(crsp_cache: Path, permnos) -> pd.DataFrame:
    """Daily rows for `permnos` from cached pre-2023 dsf extracts (the manifest says which)."""
    import pyarrow.parquet as pq
    man = json.loads((Path(crsp_cache) / "_manifest.json").read_text())
    files = [Path(crsp_cache) / f"{k}.parquet" for k, v in man.items()
             if k.startswith("dsf_") and "date < DATE '2023-01-01'" in v.get("sql", "")]
    files = [f for f in files if f.exists()]
    if not files:
        raise FileNotFoundError(f"{crsp_cache}: no pre-2023 dsf extract in the manifest")
    want = sorted({int(p) for p in permnos})
    frames = [pq.read_table(f, columns=["permno", "date", "prc", "ret", "vol"],
                            filters=[("permno", "in", want)]).to_pandas() for f in files]
    d = pd.concat(frames, ignore_index=True).drop_duplicates(["permno", "date"])
    d["date"] = pd.to_datetime(d.date)
    assert_pre_holdout(d.date, "CRSP dsf")
    return d


def bdc(crsp_cache: Path, evs: dict) -> dict:
    """BDCs, price only (no daily NAV, so no z): event minus same-month, same trailing-return cell."""
    names = crsp_names(crsp_cache)
    links = {}
    for code in ("P", "S"):
        e = evs[f"ev_{code}"]
        links[code] = link_symbols(e[e.kind == "BDC"].reset_index(drop=True), names)
    allp = pd.concat([links["P"], links["S"]]).dropna(subset=["permno"])
    cik_perm = allp.groupby("issuercik").permno.agg(lambda s: sorted(set(int(x) for x in s)))
    d = crsp_dsf(crsp_cache, allp.permno.unique())
    ret = d.pivot(index="date", columns="permno", values="ret").sort_index().astype(float)
    prc = d.pivot(index="date", columns="permno", values="prc").sort_index().abs()
    vol = d.pivot(index="date", columns="permno", values="vol").sort_index()
    missing = sorted(set(allp.permno.astype(int)) - set(ret.columns))
    s = ret.index
    bad = ret.isna().astype(float).cumsum()
    Lr = np.log1p(ret).fillna(0.0).cumsum()
    zero = pd.DataFrame(0.0, index=s, columns=ret.columns)

    def win(a: int, b: int) -> pd.DataFrame:
        out = np.exp(_shift(Lr, b) - _shift(Lr, a)) - 1.0
        return out.where((_shift(bad, b) - _shift(bad, a)) == 0)

    f = {f"px_{h}": win(1, 1 + h) for h in HORIZONS}
    f[f"px_late_{PRIMARY_H}"] = win(2, 2 + PRIMARY_H)
    trail = (np.exp(Lr - Lr.shift(TRAIL_RET)) - 1.0).where(bad - bad.shift(TRAIL_RET) == 0)
    f["trail"] = trail
    f["adv"] = (prc * vol).rolling(63, min_periods=21).mean().shift(1)
    st = pd.DataFrame({k: v.stack(future_stack=True) for k, v in f.items()})
    st.index.names = ["date", "permno"]
    st = st[st.trail.notna()].reset_index()
    filings: dict = {}
    for code in ("P", "S"):
        r = evs[f"rows_{code}"]
        r = r[r.issuercik.isin(cik_perm.index)]
        for cik, g in r.groupby("issuercik"):
            for p in cik_perm[cik]:
                filings.setdefault(p, []).extend(g.FILING_DATE.drop_duplicates().tolist())
    cm = control_mask({"px": zero}, filings).stack(future_stack=True)
    cm.index.names = ["date", "permno"]
    st = st.join(cm.rename("ctrl"), on=["date", "permno"])
    st["ym"] = st.date.dt.to_period("M").astype(str)
    st["year"] = st.date.dt.year
    st["rbin"] = bin_of(st.trail, RET_EDGES)
    st["group"] = "bdc"
    C = st[st.ctrl]
    cols = [f"px_{h}" for h in HORIZONS] + [f"px_late_{PRIMARY_H}"]
    rows, ev_rows, diag = [], [], {}
    for code, label in (("P", "purchases"), ("S", "sales_placebo")):
        e = links[code].dropna(subset=["permno"]).copy()
        e["permno"] = e.permno.astype(int)
        pos = s.searchsorted(e.event_date.values, side="left")
        e = e[pos < len(s)].copy()
        e["date"] = s[s.searchsorted(e.event_date.values, side="left")]
        m = e.merge(st, on=["date", "permno"], how="left", validate="many_to_one")
        diag[label] = {"bdc_events": int(len(links[code])), "linked": int(links[code].permno.notna().sum()),
                       "link_stages": links[code].link.value_counts().to_dict(),
                       "usable_trailing_return": int(m.trail.notna().sum())}
        m = m[m.trail.notna()]
        m["sample"] = label
        for method, keys in (("m1_month_retbin", ["group", "ym", "rbin"]), ("m2_fund_year_retbin", ["permno", "year", "rbin"])):
            mm = matched_excess(m, C, keys, cols)
            rows += summarise(mm, f"bdc_{label}", method, cols)
            if method == "m1_month_retbin":
                ev_rows.append(mm)
                for era_a, era_b in ERAS:
                    rows += [dict(r, sample=f"bdc_{label} era {era_a}-{era_b}")
                             for r in summarise(mm[mm.date.dt.year.between(era_a, era_b)], f"bdc_{label}", method,
                                                [f"px_{PRIMARY_H}"])]
    assert_pre_holdout(st.date, "BDC long frame")
    return {"main": pd.DataFrame(rows), "diag": diag, "permnos_missing_from_dsf": missing,
            "events": pd.concat(ev_rows, ignore_index=True), "last_date": str(st.date.max().date()),
            "n_control_days": int(len(C)), "st": st, "links": links, "sessions": s}


# ------------------------------------------------------------------ BDC report-only diagnostic

FILING_BUCKETS = (-0.5, 10, 30, 60, 10_000)        # days since the fund's last 10-Q/10-K


def periodic_filing_dates(caches: list[Path], ciks) -> dict[int, np.ndarray]:
    """10-Q and 10-K filing dates per CIK from the cached master indexes, 2008Q1-2022Q4."""
    want = {int(c) for c in ciks}
    frames = []
    for y, q in quarters(INDEX_FIRST_Q, LAST_Q):
        df = fe.parse_master_index(cached_text(fe.INDEX_URL.format(y=y, q=q), caches),
                                   label=f"{y}Q{q}", keep_forms={"10-Q", "10-K"})
        frames.append(df[df.cik.isin(want)][["cik", "date_filed"]])
    f = pd.concat(frames, ignore_index=True)
    assert_pre_holdout(f.date_filed, "10-Q/10-K dates")
    return {int(c): np.sort(g.date_filed.values) for c, g in f.groupby("cik")}


def days_since_filing(dates: pd.Series, filed: np.ndarray | None) -> np.ndarray:
    """Calendar days from the latest filing on or before each date; NaN if none (or none indexed)."""
    if filed is None or len(filed) == 0:
        return np.full(len(dates), np.nan)
    d = dates.values.astype("datetime64[ns]")
    pos = np.searchsorted(filed, d, side="right") - 1
    out = (d - filed[np.clip(pos, 0, None)]).astype("timedelta64[D]").astype(float)
    out[pos < 0] = np.nan
    return out


def bdc_filing_window(caches: list[Path], res: dict, evs: dict) -> pd.DataFrame:
    """REPORT-ONLY, DESIGNED AFTER SEEING THE BDC ROWS (2026-10-20): it can neither rescue nor
    kill anything. Do BDC insider trades of either sign sit just after the fund's own 10-Q/10-K
    (the insider trading window), and does the excess survive matching on that timing?"""
    st, links = res["st"], res["links"]
    perm_cik = (pd.concat([links["P"], links["S"]]).dropna(subset=["permno"])
                .assign(permno=lambda x: x.permno.astype(int)).drop_duplicates("permno")
                .set_index("permno").issuercik.astype(int).to_dict())
    filed = periodic_filing_dates(caches, set(perm_cik.values()))
    st = st[st.date >= pd.Timestamp("2008-04-01")].copy()       # the indexes start 2008Q1
    st["dsf"] = np.nan
    for p, g in st.groupby("permno"):
        st.loc[g.index, "dsf"] = days_since_filing(g.date, filed.get(perm_cik.get(int(p))))
    st["fbucket"] = pd.cut(st.dsf, bins=list(FILING_BUCKETS), labels=False).astype(float)
    C = st[st.ctrl & st.fbucket.notna()]
    rows = []
    col = f"px_{PRIMARY_H}"
    # Control days only: does the price drift after a BDC's own quarterly report, with no insider?
    month_mean = C.groupby("ym")[col].mean()
    for b in range(len(FILING_BUCKETS) - 1):
        cb = C[C.fbucket == b]
        r = clustered(cb[col] - cb.ym.map(month_mean), cb.ym)
        rows.append({"sample": "bdc_control_days", "row": f"{col} minus all control days in the month, bucket {b}",
                     "bucket": f"({FILING_BUCKETS[b]:g}, {FILING_BUCKETS[b + 1]:g}]", "n_events": r["n"],
                     "months": r["G"], "mean_excess_bp": r["mean"] * 1e4, "t": r["t"]})
    for code, label in (("P", "purchases"), ("S", "sales_placebo")):
        e = links[code].dropna(subset=["permno"]).copy()
        e["permno"] = e.permno.astype(int)
        s = res["sessions"]
        e = e[s.searchsorted(e.event_date.values, side="left") < len(s)].copy()
        e["date"] = s[s.searchsorted(e.event_date.values, side="left")]
        m = e.merge(st, on=["date", "permno"], how="inner", validate="many_to_one")
        m = m[m.fbucket.notna()]
        for b in range(len(FILING_BUCKETS) - 1):
            rows.append({"sample": f"bdc_{label}", "row": f"share of events, days since 10-Q/10-K in bucket {b}",
                         "bucket": f"({FILING_BUCKETS[b]:g}, {FILING_BUCKETS[b + 1]:g}]",
                         "events": float((m.fbucket == b).mean()), "control_days": float((C.fbucket == b).mean()),
                         "n_events": int(len(m))})
        for keys, lab in ((["group", "ym", "rbin"], "m1 (as G5), 2008-04+"),
                          (["group", "ym", "rbin", "fbucket"], "m1 + filing-window bucket, 2008-04+")):
            mm = matched_excess(m, C, keys, [col])
            r = clustered(mm[f"x_{col}"], mm.ym)
            rows.append({"sample": f"bdc_{label}", "row": lab, "n_events": r["n"], "months": r["G"],
                         "mean_excess_bp": r["mean"] * 1e4, "t": r["t"]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ counts

def counts(evs: dict, cmap: pd.DataFrame, names: pd.DataFrame | None) -> dict:
    P = evs["rows_P"]
    tx = P.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]).assign(year=lambda x: x.FILING_DATE.dt.year)
    by = tx.groupby(["year", "kind"]).agg(qual_purchase_trans=("NONDERIV_TRANS_SK", "size"),
                                          filings=("ACCESSION_NUMBER", "nunique"), funds=("issuercik", "nunique"),
                                          median_trans_usd=("usd", "median")).reset_index()
    ev = evs["ev_P"].assign(year=lambda x: x.event_date.dt.year)
    if names is not None:
        lk = link_symbols(ev, names)
        ev["listed_crsp"] = lk.permno.notna().values
    e1 = ev.groupby(["year", "kind"]).agg(fund_events=("issuercik", "size"), event_funds=("issuercik", "nunique"),
                                          sweep_events=("sweep", "sum"), adviser_events=("adviser", "sum"),
                                          **({"listed_crsp_events": ("listed_crsp", "sum")} if names is not None else {})
                                          ).reset_index()
    for key, col in (("ev_P_floor", "fund_events_floor10k"), ("ev_P_2own", "fund_events_2owners")):
        x = evs[key].assign(year=lambda z: z.event_date.dt.year).groupby(["year", "kind"]).size().rename(col)
        e1 = e1.join(x, on=["year", "kind"])
    sx = evs["ev_S"].assign(year=lambda z: z.event_date.dt.year).groupby(["year", "kind"]).size().rename("sale_events")
    by = by.merge(e1, on=["year", "kind"], how="outer").join(sx, on=["year", "kind"]).fillna(0)
    setmap = {int(c): s for c, s in zip(cmap.cik.dropna(), cmap.dropna(subset=["cik"]).set)}
    ours = ev.assign(set=ev.issuercik.map(setmap).fillna("not in our panels"))
    os_ = ours.groupby(["year", "set"]).size().unstack(fill_value=0)
    for k in ("ev_P_floor", "ev_P_2own"):
        z = evs[k].assign(year=lambda q: q.event_date.dt.year, set=lambda q: q.issuercik.map(setmap))
        z = z[z.set.notna()].groupby(["year", "set"]).size().unstack(fill_value=0)
        os_ = os_.join(z.add_suffix("__" + ("floor10k" if k.endswith("floor") else "2owners")), how="left")
    sizes = []
    for kind, g in tx.groupby("kind"):
        q = g.usd.quantile([.1, .25, .5, .75, .9]).to_dict()
        sizes.append({"kind": kind, "unit": "per qualifying purchase transaction, USD", "n": int(len(g)),
                      **{f"p{int(k * 100)}": float(v) for k, v in q.items()}, "share_under_10k": float((g.usd < FLOOR_USD).mean())})
    for kind, g in ev.groupby("kind"):
        q = g.usd.quantile([.1, .25, .5, .75, .9]).to_dict()
        sizes.append({"kind": kind, "unit": "per fund-event (sum over its 30-day set), USD", "n": int(len(g)),
                      **{f"p{int(k * 100)}": float(v) for k, v in q.items()}, "share_under_10k": float((g.usd < FLOOR_USD).mean())})
    return {"by_year_kind": by.sort_values(["year", "kind"]), "our_sets_by_year": os_.fillna(0).astype(int),
            "sizes": pd.DataFrame(sizes)}


# ------------------------------------------------------------------ feasibility

def bdays(start: pd.Series, end: pd.Series) -> np.ndarray:
    """SEC business days between two dates (federal holiday calendar; EDGAR follows it [S])."""
    from pandas.tseries.holiday import USFederalHolidayCalendar
    hol = USFederalHolidayCalendar().holidays("2005-01-01", "2023-12-31").values.astype("datetime64[D]")
    return np.busday_count(start.values.astype("datetime64[D]"), end.values.astype("datetime64[D]"), holidays=hol)


ACCEPT_BINS = ((0.0, 9.5, "before 09:30"), (9.5, 16.0, "09:30-16:00 (market hours)"),
               (16.0, 17.5, "16:00-17:30"), (17.5, 22.0, "17:30-22:00 (Forms 3/4/5 still same-day)"),
               (22.0, 24.01, "after 22:00 (filed next business day)"))


def accept_hours_et(json_times: pd.Series, shift_h: float = 0.0) -> pd.Series:
    """ET clock hour of an `acceptanceDateTime` read as UTC, minus `shift_h` hours.

    The submissions JSON's value is either true UTC or 4-5 hours late
    (`results/events/edgar_acceptance_offsets/`), so shift 0 is the LATEST the
    filing can have been accepted and shift 5 the earliest.
    """
    t = pd.to_datetime(json_times, utc=True) - pd.Timedelta(hours=shift_h)
    et = t.dt.tz_convert(NY)
    return et.dt.hour + et.dt.minute / 60.0 + et.dt.second / 3600.0


def acceptance_table(caches: list[Path], ciks) -> tuple[pd.DataFrame, dict]:
    rows, have, miss = [], 0, 0
    for cik in sorted({int(c) for c in ciks}):
        try:
            j = json.loads(cached_text(fe.SUBMISSIONS_URL.format(cik=cik), caches, "utf-8"))
        except FileNotFoundError:
            miss += 1
            continue
        have += 1
        r = j.get("filings", {}).get("recent", {})
        n = len(r.get("form", []))
        for k in ("form", "filingDate", "acceptanceDateTime"):
            if len(r.get(k, [])) != n:
                raise ValueError(f"CIK {cik}: submissions 'recent' arrays have unequal lengths")
        for f, fd, a in zip(r["form"], r["filingDate"], r["acceptanceDateTime"]):
            if f == "4":
                rows.append({"cik": cik, "filingDate": fd, "acceptance": a})
    return pd.DataFrame(rows, columns=["cik", "filingDate", "acceptance"]), {"ciks_with_cached_json": have,
                                                                             "ciks_without": miss}


def feasibility(caches: list[Path], evs: dict, mech: dict) -> dict:
    from scripts.cef.spec import CAPITAL_USD, MIN_ADV_USD
    P = evs["rows_P"].drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]).copy()
    P["lag_bd"] = bdays(P.TRANS_DATE, P.FILING_DATE)
    lag = []
    for (a, b) in ERAS + ((2006, 2022),):
        for kind in ("CEF", "BDC", "all"):
            s = P[(P.FILING_DATE.dt.year.between(a, b)) & ((P.kind == kind) if kind != "all" else True)].lag_bd
            if len(s):
                lag.append({"era": f"{a}-{b}", "kind": kind, "n": int(len(s)), "share_le_2bd": float((s <= 2).mean()),
                            "share_0bd": float((s == 0).mean()), "p50": float(s.median()), "p90": float(s.quantile(.9)),
                            "share_gt_10bd": float((s > 10).mean())})
    acc, adiag = acceptance_table(caches, mech["cmap"].cik.dropna())
    abins = {}
    if len(acc):
        acc["fd"] = pd.to_datetime(acc.filingDate)
        for lab, sh in (("json_as_utc (latest possible)", 0.0), ("json minus 5h (earliest possible)", 5.0)):
            h = accept_hours_et(acc.acceptance, sh)
            abins[lab] = {b[2]: int(((h >= b[0]) & (h < b[1])).sum()) for b in ACCEPT_BINS}
        et_date = pd.to_datetime(acc.acceptance, utc=True).dt.tz_convert(NY).dt.tz_localize(None).dt.normalize()
        adiag.update({"form4_rows": int(len(acc)), "filing_years": [int(acc.fd.dt.year.min()), int(acc.fd.dt.year.max())],
                      "share_filingDate_equals_json_et_date": float((et_date == acc.fd).mean())})
    E = mech["E"]
    Pm = E[E["sample"] == "purchases"]
    adv = Pm.adv
    cap = {"events_with_adv": int(adv.notna().sum()), "adv_p10": float(adv.quantile(.1)),
           "adv_median": float(adv.median()), "adv_p90": float(adv.quantile(.9)),
           "share_adv_ge_spec_min_adv": float((adv >= MIN_ADV_USD).mean()), "spec_min_adv_usd": MIN_ADV_USD,
           "share_adv_ge_1m": float((adv >= 1e6).mean()), "spec_capital_usd": CAPITAL_USD,
           "clip_10pct_of_capital_as_share_of_median_adv": float(0.10 * CAPITAL_USD / adv.median())}
    by_year = (Pm.assign(year=Pm.date.dt.year, ok=Pm.adv >= MIN_ADV_USD).groupby("year")
               .agg(events=("ok", "size"), events_adv_ge_spec_min=("ok", "sum")))
    return {"lag": pd.DataFrame(lag), "acceptance_bins": abins, "acceptance_diag": adiag,
            "capacity": cap, "events_by_year_adv": by_year}


# ------------------------------------------------------------------ the gate

def _row(main: pd.DataFrame, sample: str, method: str, outcome: str) -> dict:
    r = main[(main["sample"] == sample) & (main.method == method) & (main.outcome == outcome)]
    if len(r) != 1:
        raise KeyError(f"no unique row for {sample}/{method}/{outcome}")
    return r.iloc[0].to_dict()


def gate(main: pd.DataFrame, events_per_year: pd.Series, bdc_main: pd.DataFrame | None) -> dict:
    """The zero-trial gate of the module docstring, evaluated on this run's numbers."""
    h = PRIMARY_H
    p1 = _row(main, "purchases", "m1_group_month_zbin", f"dd_{h}")
    p2 = _row(main, "purchases", "m2_fund_year_zbin", f"dd_{h}")
    s1 = _row(main, "sales_placebo", "m1_group_month_zbin", f"dd_{h}")
    px = _row(main, "purchases", "m1_group_month_zbin", f"px_{h}")
    yrs = events_per_year[(events_per_year.index >= 2010) & (events_per_year.index <= 2022)]
    g1 = float(yrs.mean())
    out = {"G1_breadth": {"events_per_year_2010_22_mean": g1, "bar": GATE_MIN_EVENTS_YR,
                          "pass": bool(g1 >= GATE_MIN_EVENTS_YR), "fail_means": "D7"},
           "G2_incremental_to_z": {"m1_mean_pp": p1["mean_excess"], "m1_t": p1["t"], "m2_mean_pp": p2["mean_excess"],
                                   "m2_t": p2["t"], "bar_t": GATE_T,
                                   "pass": bool(p1["mean_excess"] > 0 and p1["t"] >= GATE_T and p2["mean_excess"] > 0),
                                   "fail_means": "KILL: insider buying adds nothing beyond the z-score"},
           "G3_sales_placebo": {"sales_m1_mean_pp": s1["mean_excess"], "sales_m1_t": s1["t"],
                                "purchases_m1_mean_pp": p1["mean_excess"],
                                "pass": bool(not (np.sign(s1["mean_excess"]) == np.sign(p1["mean_excess"])
                                                  and abs(s1["mean_excess"]) >= PLACEBO_SHARE * abs(p1["mean_excess"]))),
                                "fail_means": "KILL: the placebo moves the same way (artefact of insider trading windows)"},
           "G4_cost": {"px_excess_bp": px["mean_excess"], "px_t": px["t"],
                       "bar_bp": ROUND_TRIP_UNITS * GATE_COST_BP,
                       "net_bp_at_grid": {f"{c:g}bp": px["mean_excess"] - ROUND_TRIP_UNITS * c for c in COST_GRID_BP},
                       "pass": bool(px["mean_excess"] >= ROUND_TRIP_UNITS * GATE_COST_BP),
                       "fail_means": "D2 (costs eat it) -- reported, not a kill on its own"}}
    if bdc_main is not None:
        b = _row(bdc_main, "bdc_purchases", "m1_month_retbin", f"px_{h}")
        bs = _row(bdc_main, "bdc_sales_placebo", "m1_month_retbin", f"px_{h}")
        out["G5_bdc_descriptive"] = {"px_excess_bp": b["mean_excess"], "t": b["t"], "n": b["n"],
                                     "sales_px_excess_bp": bs["mean_excess"], "sales_t": bs["t"],
                                     "recommend_bdc_nav_fetch": bool(b["mean_excess"] > 0 and b["t"] >= GATE_T)}
    core = ("G1_breadth", "G2_incremental_to_z", "G3_sales_placebo")
    if not out["G2_incremental_to_z"]["pass"]:
        verdict = "CLOSE at zero trials: G2 fails -- no information beyond the discount z-score"
    elif not out["G3_sales_placebo"]["pass"]:
        verdict = "CLOSE at zero trials: G3 fails -- the sales placebo moves the same way"
    elif not out["G1_breadth"]["pass"]:
        verdict = "D7: too few events to judge a sleeve"
    elif not out["G4_cost"]["pass"]:
        verdict = "WATCH (D2): information beyond z, but below the round-trip cost bar"
    else:
        verdict = "PASS: draft a pre-registration (counter by the team lead's ruling)"
    out["core_all_pass"] = bool(all(out[k]["pass"] for k in core))
    out["verdict"] = verdict
    return out


# ------------------------------------------------------------------ the team lead's fetch (live; never run by an agent)

def fetch_urls(first: tuple[int, int] = FIRST_Q, last: tuple[int, int] = LAST_Q) -> list[str]:
    """Every URL this module reads, in fetch order. Refuses any quarter in the sealed 2023+."""
    if last >= (2023, 1):
        raise HoldoutError(f"refusing to fetch {last}: quarters from 2023Q1 are the sealed time holdout")
    urls = [ZIP_URL.format(y=y, q=q) for y, q in quarters(first, last)]
    urls += [fe.INDEX_URL.format(y=y, q=q) for y, q in quarters(max(first, INDEX_FIRST_Q), last)]
    return urls + [fe.TICKERS_URL, README_URL]


def fetch(max_live: int, client=None) -> dict:
    """GET every URL in `fetch_urls()` into the EDGAR cache, at most `max_live` live requests.

    Live EDGAR: `EdgarClient` reads SEC_USER_AGENT from the env file, paces requests
    (1.5 s here: the SEC's budget is shared with other jobs) and caches every body.
    A closed quarter is immutable, so a cached copy is always used.
    """
    from scripts.data.edgar_client import EdgarClient, RateLimiter
    c = client if client is not None else EdgarClient(limiter=RateLimiter(min_interval=1.5))
    log = []
    for u in fetch_urls():
        if c.n_requests >= max_live:
            raise RuntimeError(f"live-request cap {max_live} reached before {u}; raise --max-live deliberately")
        before = c.n_requests
        body = c.get(u, max_age_s=None)
        log.append({"url": u, "bytes": len(body), "live": c.n_requests - before})
    return {"ran_utc": _now(), "live_requests": c.n_requests, "cache_hits": c.n_cache_hits, "urls": log}


def pull_crsp(evs: dict, ce=None) -> dict:
    """TEAM LEAD ONLY (R2 credentials, through `scripts/events/crsp_events.py`): `dsenames`,
    then pre-2023 `dsf` for every BDC permno the purchase and sale events link to. The cut
    at 2023-01-01 is in crsp_events' SQL and asserted there. Only needed where no CRSP
    cache holds those permnos; the 2026-10-20 run read an existing extract."""
    if ce is None:
        from scripts.events import crsp_events as ce
    names = ce.names()
    names = names[names.ticker.notna()]
    perm: set[int] = set()
    for code in ("P", "S"):
        e = evs[f"ev_{code}"]
        e = e[e.kind == "BDC"].reset_index(drop=True)
        perm |= {int(x) for x in link_symbols(e, names).permno.dropna()}
    d = ce.daily(sorted(perm))
    return {"ran_utc": _now(), "bdc_permnos": len(perm), "dsf_rows": int(len(d)), "cache": str(ce.CACHE)}


# ------------------------------------------------------------------ orchestration

def _write_csv(df: pd.DataFrame, name: str, index: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / name, index=index, float_format="%.6g")


def _write_json(obj: dict, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1, default=str) + "\n")


def _cache_write(df: pd.DataFrame, name: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE / name, index=False)


def _cache_read(name: str, part: str) -> pd.DataFrame:
    p = CACHE / name
    if not p.exists():
        raise FileNotFoundError(f"{p}: run the `{part}` part first")
    return pd.read_parquet(p)


def part_fundset(caches: list[Path]) -> pd.DataFrame:
    fs = fundset(caches)
    _cache_write(fs, "fund_set.parquet")
    _write_json({"ran_utc": _now(), "index_quarters": f"{INDEX_FIRST_Q} -> {LAST_Q}", "n_fund_ciks": int(len(fs)),
                 "by_rule_kind": {f"{a}|{b}": int(n) for (a, b), n in fs.groupby(["set_rule", "kind"]).size().items()}},
                "a2_fundset_summary.json")
    return fs


def part_extract(caches: list[Path]) -> pd.DataFrame:
    fs = _cache_read("fund_set.parquet", "fundset")
    rows, diags = extract(caches, fs)
    _cache_write(rows, "rows_ps.parquet")
    _write_csv(pd.DataFrame(diags), "a2_extract_by_quarter.csv")
    return rows


def part_events() -> dict:
    fs = _cache_read("fund_set.parquet", "fundset")
    rows = _cache_read("rows_ps.parquet", "extract")
    evs = build_events(rows, fs)
    for k in ("rows_P", "rows_S", "ev_P", "ev_S", "ev_P_floor", "ev_P_2own"):
        _cache_write(evs[k], f"{k}.parquet")
    _write_json({"ran_utc": _now(), "qualifying": evs["diag"]}, "a2_qualifying_diag.json")
    return evs


def load_events() -> dict:
    return {k: _cache_read(f"{k}.parquet", "events")
            for k in ("rows_P", "rows_S", "ev_P", "ev_S", "ev_P_floor", "ev_P_2own")}


def run(parts: list[str], caches: list[Path], crsp_cache: Path) -> dict:
    res = {}
    if "fundset" in parts:
        part_fundset(caches)
    if "extract" in parts:
        part_extract(caches)
    if "events" in parts:
        part_events()
    need = {"counts", "mechanism", "bdc", "feasibility", "gate"} & set(parts)
    if not need:
        return res
    evs = load_events()
    names = crsp_names(crsp_cache) if (Path(crsp_cache) / "dsenames.parquet").exists() else None
    mech = None
    if {"counts", "mechanism", "feasibility", "gate"} & set(parts):
        mech = mechanism(caches, evs)
        _write_csv(mech["main"], "a2_mech_main.csv")
        _write_csv(mech["profile"], "a2_mech_profile.csv")
        _write_csv(mech["strata"], "a2_mech_strata.csv")
        _write_csv(mech["zdist"], "a2_mech_zdist.csv")
        _write_csv(mech["events_per_year"], "a2_mech_events_per_year_group.csv", index=True)
        _write_csv(mech["cmap"], "a2_panel_cik_map.csv")
        _write_json({"ran_utc": _now(), "panel_last_date": mech["panel_last_date"], "diag": mech["diag"],
                     "below_nav": mech["below_nav"], "n_fund_days": mech["n_fund_days"],
                     "n_control_fund_days": mech["n_control_fund_days"]}, "a2_mech_summary.json")
        keep = ["sample", "issuercik", "ticker", "group", "event_date", "date", "z", "zbin", "prem_trade", "adv",
                "sweep", "adviser", "usd"] + OUTCOME_COLS
        _cache_write(mech["E"][keep], "mech_events.parquet")
        cc = crosscheck(mech["E"], mech["L"])
        _write_json({"ran_utc": _now(), **cc}, "a2_crosscheck.json")
    if "counts" in parts:
        c = counts(evs, mech["cmap"], names)
        _write_csv(c["by_year_kind"], "a2_counts_by_year_kind.csv")
        _write_csv(c["our_sets_by_year"], "a2_counts_our_sets_by_year.csv", index=True)
        _write_csv(c["sizes"], "a2_sizes.csv")
        res["counts"] = c
    bdc_res = None
    if {"bdc", "gate"} & set(parts):
        bdc_res = bdc(crsp_cache, evs)
        _write_csv(bdc_res["main"], "a2_bdc_main.csv")
        # Permnos are licensed-derived identifiers (.gitignore): the tracked file holds the count only.
        _write_json({"ran_utc": _now(), "diag": bdc_res["diag"], "last_date": bdc_res["last_date"],
                     "n_permnos_missing_from_dsf": len(bdc_res["permnos_missing_from_dsf"]),
                     "n_control_days": bdc_res["n_control_days"]}, "a2_bdc_summary.json")
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "bdc_permnos_missing_from_dsf_LICENSED.json").write_text(
            json.dumps(bdc_res["permnos_missing_from_dsf"]) + "\n")
        _cache_write(bdc_res["events"][["sample", "issuercik", "permno", "event_date", "date", "trail", "adv"]
                                       + [f"px_{h}" for h in HORIZONS]], "bdc_events_crsp_LICENSED.parquet")
        _write_csv(bdc_filing_window(caches, bdc_res, evs), "a2_bdc_filing_window_REPORT_ONLY.csv")
    if "feasibility" in parts:
        f = feasibility(caches, evs, mech)
        _write_csv(f["lag"], "a2_feasibility_lag.csv")
        _write_csv(f["events_by_year_adv"], "a2_feasibility_events_adv_by_year.csv", index=True)
        _write_json({"ran_utc": _now(), "acceptance_bins": f["acceptance_bins"], "acceptance_diag": f["acceptance_diag"],
                     "capacity": f["capacity"]}, "a2_feasibility.json")
    if "gate" in parts:
        P = mech["E"][mech["E"]["sample"] == "purchases"]
        epy = P.groupby(P.date.dt.year).size()
        g = gate(mech["main"], epy, bdc_res["main"] if bdc_res is not None else None)
        g["ran_utc"] = _now()
        g["events_per_year_panel_sample"] = {int(k): int(v) for k, v in epy.items()}
        _write_json(g, "a2_gate.json")
        res["gate"] = g
    return res


PARTS = ("fundset", "extract", "events", "counts", "mechanism", "bdc", "feasibility", "gate")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part", choices=PARTS + ("all", "fetch", "pull-crsp"))
    ap.add_argument("--edgar-cache", action="append", type=Path, default=None,
                    help="an EDGAR cache root (repeatable; searched in order). Default: this repo's.")
    ap.add_argument("--crsp-cache", type=Path, default=DEFAULT_CRSP_CACHE)
    ap.add_argument("--max-live", type=int, default=140, help="fetch only: live-request cap")
    a = ap.parse_args(argv)
    if a.part == "fetch":
        rec = fetch(a.max_live)
        _write_json(rec, "a2_fetch_log.json")
        print(json.dumps({k: v for k, v in rec.items() if k != "urls"}, indent=1))
        return 0
    if a.part == "pull-crsp":
        rec = pull_crsp(load_events())
        _write_json(rec, "a2_pull_crsp_log.json")
        print(json.dumps(rec, indent=1))
        return 0
    caches = a.edgar_cache or [DEFAULT_EDGAR_CACHE]
    parts = list(PARTS) if a.part == "all" else [a.part]
    res = run(parts, caches, a.crsp_cache)
    if "gate" in res:
        print(json.dumps(res["gate"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
