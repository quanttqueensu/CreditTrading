"""Muni hazard flags B1/B2: the zero-trial gate (team lead, 2026-10-19). Report only; no P&L.

THE QUESTION
------------
Paths B1 and B2 of the team lead's 2026-10-19 list propose SUBTRACT-ONLY flags
for the live book's muni funds:

* B1, muni credit events (defaults, reserve-fund draws, downgrades) mapped to
  each fund's holdings through N-PORT;
* B2, disasters and state fiscal shocks hitting single-state or concentrated
  muni funds.

The mechanism: a matrix-priced muni NAV lags the news, the discount widens on
information rather than sentiment, and the discount z-score buys it. A flag
would stop that. This script measures, at zero trials, whether the premise
holds for the funds the book actually trades. It computes NO strategy return,
P&L or Sharpe. It reads price and NAV changes around dated events and the
band's own turnover, all strictly before the sealed 2023-01-01 time holdout.

WHAT IT MEASURES (results/cef/MUNI_HAZARD_FLAGS_GATE_2026-10-20.md is the note)
--------------------------------------------------------------------------------
1. `holdings`: which spec names are muni funds (spec universe x
   `data/cef/cef_facts.csv` grp), and their state and issuer concentration
   from N-PORT (latest cached filing, and every quarter filed before
   2023-01-01). The state of each holding is parsed from N-PORT's `title`
   (CUSIP-style issuer description, e.g. "HOUSTON TX ARPT SYS REVENUE") and
   checked against a second method, the state headings of the fund's own
   N-CSR schedule of investments at the same date (`ncsr_check`).
2. `b1`: holdings the fund itself flags `isDefault` or
   `areIntrstPmntsInArrs` in N-PORT, per quarter, and how many are new.
   N-PORT dates a flag only to the quarter, so this is incidence, never an
   event date.
3. `b2`: OpenFEMA declarations (`scripts/events/fetch_fema_declarations.py`)
   as (incidentId, state) events, dated at their EARLIEST declaration of any
   type, mapped to the fund's state weight from the latest N-PORT FILED
   STRICTLY BEFORE that date.
4. `signature`: the stale-mark test. For each touched (fund, event), the
   discount change over the news window and the NAV's later move, against the
   same quantities on non-event anchors (baseline) and on the book's taxable
   funds at the same anchors (negative control, H12).
5. `turnover`: the band's own turnover on the muni names, and the share of it
   decided on days a B2 flag would have covered: the upper bound on what the
   flag could ever subtract.
6. Added after the first run, and labelled as such in every output:
   `signature_posthoc_news_anchor` (timely weather events anchored at the
   incident's begin date; `POSTHOC_*` below); `muni_direction` (long/short
   split and the turnover a subtract-only flag could block); `adv_eligibility`
   (price x volume LEVELS, so the 2023-26 row reads no return); and the
   top-10-issuer-state count. None of them changed a declared choice.

DECLARED BEFORE ANY OUTCOME WAS READ (2026-10-20)
--------------------------------------------------
* Event date t0: the first NYSE session on or after the earliest
  declarationDate for that (incidentId, state). Knowable that day.
* News window: close(t0-3) -> close(t0+1). EM and FM declarations come a
  median 1-2 days after incidentBeginDate (counted from the FEMA CSV by
  `fema_lags`), so three sessions before t0 cover the news; t0+1 is the first
  session a t0 decision could fill (shift(2)).
* Catch-up window: close(t0+1) -> close(t0+6), five sessions: the
  shift(2) holding horizon and beyond.
* "Touched": the fund's N-PORT net-asset weight in the declared state is at
  least TOUCH_W (5%). Derivation: a NAV is quoted to the cent; one cent on an
  ~$11 muni fund is ~9bp; a state shock reprices that state's bonds by at most
  a few percent [U: assumption, no source], so only a state above ~5% of net
  assets can move the NAV by a cent. Buckets 0-2, 2-5, 5-10, >=10% are also
  reported, for description only.
* Excluded incident type: "Biological" (COVID-19 was declared in every state
  in 2020; it is a national event and is reported separately).
* Returns add the distribution back on the ex-date to BOTH price and NAV
  (log((X_t + D_t)/X_{t-1})), so ex-date arithmetic cancels in the gap
  (docs/BRIEF.md §3).

LOOKAHEAD (H7) AND THE HOLDOUT (H13)
------------------------------------
Holdings are used only from filings whose EDGAR filing date is strictly
before the event date (`exposure_asof`; tested). Every window used in
`signature` and `turnover` ends before 2023-01-01; `_assert_fit_only` raises
otherwise (tested). Events before the first N-PORT filing (2019-12-24) have no
point-in-time holdings; they are scored with the FIRST N-PORT's weights and
labelled PROXY (anachronistic), reported apart from the point-in-time rows, and
never used alone for a verdict.

DATA AND NO SILENT FALLBACKS
----------------------------
N-PORT and N-CSR documents are read from `results/events/_cache_edgar/`
(gitignored). `stage` copies them, read-only at the source, from sibling
worktrees' caches and records each SHA-256 in `_staged_from_worktrees.json`.
A document missing everywhere RAISES, naming the accession and the
credentialed command the team lead would run; this script never opens a
network connection and never reads the env file. A holding whose state
cannot be parsed is counted and reported as UNPARSED, never assigned.

Run (offline): `python3 scripts/events/muni_hazard_gate.py stage`
               `python3 scripts/events/muni_hazard_gate.py run`
Outputs: results/events/muni_hazard/ (summary JSON and aggregate CSVs).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATA = REPO / "data"
CACHE = REPO / "results" / "events" / "_cache_edgar"
OUT = REPO / "results" / "events" / "muni_hazard"
FEMA_CSV = OUT / "fema_declarations_state.csv"
HOLDOUT = pd.Timestamp("2023-01-01")
TOUCH_W = 5.0            # % of net assets; see the docstring's derivation
BUCKETS = (0.0, 2.0, 5.0, 10.0, np.inf)
NEWS = (-3, 1)           # close(t0-3) -> close(t0+1)
CATCH = (1, 6)           # close(t0+1) -> close(t0+6)
EXCLUDED_TYPES = ("Biological",)
FIRST_FIT_YEAR = 2005    # band_frontier.SAMPLE_START's year

# CIKs are checked against the cached submissions JSON's `tickers`; a mismatch raises.
CIK = {"MHD": 1034665, "MQY": 890196}

STATES = {
    "AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS", "CA": "CALIFORNIA",
    "CO": "COLORADO", "CT": "CONNECTICUT", "DE": "DELAWARE", "DC": "DISTRICT OF COLUMBIA",
    "FL": "FLORIDA", "GA": "GEORGIA", "HI": "HAWAII", "ID": "IDAHO", "IL": "ILLINOIS",
    "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS", "KY": "KENTUCKY", "LA": "LOUISIANA",
    "ME": "MAINE", "MD": "MARYLAND", "MA": "MASSACHUSETTS", "MI": "MICHIGAN", "MN": "MINNESOTA",
    "MS": "MISSISSIPPI", "MO": "MISSOURI", "MT": "MONTANA", "NE": "NEBRASKA", "NV": "NEVADA",
    "NH": "NEW HAMPSHIRE", "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "NY": "NEW YORK",
    "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA", "OH": "OHIO", "OK": "OKLAHOMA", "OR": "OREGON",
    "PA": "PENNSYLVANIA", "RI": "RHODE ISLAND", "SC": "SOUTH CAROLINA", "SD": "SOUTH DAKOTA",
    "TN": "TENNESSEE", "TX": "TEXAS", "UT": "UTAH", "VT": "VERMONT", "VA": "VIRGINIA",
    "WA": "WASHINGTON", "WV": "WEST VIRGINIA", "WI": "WISCONSIN", "WY": "WYOMING",
    "PR": "PUERTO RICO", "GU": "GUAM", "VI": "VIRGIN ISLANDS", "AS": "AMERICAN SAMOA",
    "MP": "NORTHERN MARIANA ISLANDS",
}
NAME_TO_CODE = {v: k for k, v in STATES.items()}
# CUSIP-era abbreviations seen in issuer descriptions that are not USPS codes
# ("SAN FRANCISCO CALIF", "TARRANT CNTY TEX", "LAS VEGAS VALLEY NEV").
ABBREV = {"ALA": "AL", "ARIZ": "AZ", "ARK": "AR", "CALIF": "CA", "COLO": "CO", "CONN": "CT",
          "FLA": "FL", "ILL": "IL", "IND": "IN", "KAN": "KS", "KANS": "KS", "MASS": "MA",
          "MICH": "MI", "MINN": "MN", "MISS": "MS", "MONT": "MT", "NEB": "NE", "NEBR": "NE",
          "NEV": "NV", "OKLA": "OK", "ORE": "OR", "PENN": "PA", "TENN": "TN", "TEX": "TX",
          "WASH": "WA", "WIS": "WI", "WISC": "WI", "WYO": "WY"}
# Issuers whose descriptions carry no state at all, or a misleading one: mostly
# tender-option-bond receipts, whose N-PORT `title` is the underlying issuer's
# plain name ("City of Los Angeles Department of Airports"). Geography, not data:
# each entry is the state the named issuer sits in. Kept short; anything not here
# and not otherwise parsed is reported UNPARSED. The N-CSR's own state headings
# are the check (`ncsr_check`). Patterns match the upper-cased title or name.
KNOWN_ISSUER = (
    (r"LOWER COLORADO RIVER", "TX"), (r"METROPOLITAN WASHINGTON AIRPORTS|MET WASHINGTON", "DC"),
    (r"PORT AUTHORITY OF NEW YORK", "NY"), (r"LOS ANGELES", "CA"), (r"SAN FRANCISCO", "CA"),
    (r"SACRAMENTO", "CA"), (r"BAY AREA TOLL", "CA"), (r"SAN DIEGO", "CA"), (r"SAN JOSE", "CA"),
    (r"HUDSON YARDS|TRIBOROUGH|NEW YORK CITY|METROPOLITAN TRANSPORTATION AUTH|BATTERY PARK", "NY"),
    (r"HARRIS COUNTY|HARRIS CNTY|SAN ANTONIO|EL PASO|DALLAS|FORT WORTH|TARRANT|HOUSTON|AUSTIN|HOWE INDEPENDENT", "TX"),
    (r"NARRAGANSETT", "RI"), (r"DALTON WHITFIELD", "GA"), (r"MORGANTOWN UTILITY", "WV"),
    (r"NORTHAMPTON COUNTY GENERAL PURPOSE|NORTHAMPTON CNTY PA", "PA"), (r"HAMPTON ROADS", "VA"),
    (r"SOUTH MIAMI|MIAMI-DADE|MIAMI DADE|GREATER ORLANDO|ESCAMBIA|HILLSBOROUGH|SOUTHERN GROVE|"
     r"VILLAGE CDD|VILLAGE COMMUNITY DEVELOPMENT|ORLANDO|TAMPA|JACKSONVILLE", "FL"),
    (r"LAS VEGAS|CLARK COUNTY SCHOOL", "NV"), (r"SOUTHEAST ENERGY AUTH", "AL"),
    (r"HUDSON COUNTY IMPROVEMENT", "NJ"), (r"CHICAGO|COOK COUNTY", "IL"),
    (r"DETROIT", "MI"), (r"DENVER", "CO"), (r"PHILADELPHIA|PITTSBURGH|ALLEGHENY", "PA"),
    (r"ATLANTA|MAIN STREET NATURAL GAS", "GA"), (r"SEATTLE", "WA"),
    (r"PHOENIX|MARICOPA|SALT RIVER", "AZ"), (r"BOSTON", "MA"), (r"BALTIMORE", "MD"),
    (r"MEMPHIS|NASHVILLE", "TN"), (r"LOUISVILLE", "KY"),
    (r"INDIANAPOLIS", "IN"), (r"OMAHA", "NE"),
    (r"MILWAUKEE|PUBLIC FINANCE AUTH", "WI"), (r"NEW ORLEANS", "LA"), (r"WYANDOTTE", "KS"), (r"KANSAS CITY", "MO"),
)


class GateError(RuntimeError):
    """A required input is missing or inconsistent. The message names it."""


def _code_tokens(raw: str) -> list[str]:
    """USPS codes written as standalone UPPER-CASE two-letter tokens in the ORIGINAL
    text. Case matters: in a mixed-case name "In" or "Or" is a word, never a state;
    in an all-caps CUSIP-style description a two-letter token is a state code
    (validated against the N-CSR, `ncsr_check`)."""
    toks = re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", html.unescape(raw or ""))
    return [t for t in toks if t in STATES]


# ----------------------------------------------------------------------------- state parse
def _norm(s: str | None) -> str:
    s = html.unescape(s or "").upper()
    return re.sub(r"[^A-Z0-9#&\- ]", " ", s)


def parse_state(title: str | None, name: str | None) -> tuple[str | None, str]:
    """(USPS code, method) for a muni holding, or (None, 'unparsed').

    Order, title before name at each step:
    (1) `code`: the last upper-case two-letter USPS token ("HOUSTON TX ARPT");
    (2) `abbrev`: a CUSIP-era abbreviation token ("SAN FRANCISCO CALIF");
    (3) `name_start`: a full state name at the start ("NEW JERSEY ST ECON DEV");
    (4) `known_issuer`: the short explicit map above (tender-option-bond rows);
    (5) `name_any`: a full state name anywhere ("MUNI ELEC AUTH OF GEORGIA").
    `holdings_panel` then gives (5) and unparsed rows the state of another row
    with the same CUSIP-6 where one exists (`cusip6`). Never a default.
    """
    fields = (title or "", name or "")
    for raw in fields:
        c = _code_tokens(raw)
        if c:
            # The LAST code: "DE KALB CNTY GA" is Georgia, "DENVER CO ... CO MET DIST"
            # is Colorado either way. Chosen on the N-CSR check, 2026-10-20.
            return c[-1], "code"
    for raw in fields:
        f = _norm(raw)
        for ab, code in ABBREV.items():
            if re.search(rf"(^| ){ab}( |$)", f):
                return code, "abbrev"
    for raw in fields:
        f = _norm(raw).strip()
        for nm in sorted(NAME_TO_CODE, key=len, reverse=True):
            if f.startswith(nm + " ") or f == nm:
                return NAME_TO_CODE[nm], "name_start"
    for raw in fields:
        f = _norm(raw)
        for pat, code in KNOWN_ISSUER:
            if re.search(pat, f):
                return code, "known_issuer"
    for raw in fields:
        f = _norm(raw)
        for nm in sorted(NAME_TO_CODE, key=len, reverse=True):
            if re.search(rf"(^| ){nm}( |$)", f):
                return NAME_TO_CODE[nm], "name_any"
    return None, "unparsed"


# ----------------------------------------------------------------------------- EDGAR cache
def _sibling_caches() -> list[Path]:
    roots = []
    wt = REPO.parent
    if wt.name == "worktrees":
        roots += sorted(p for p in wt.glob("*/results/events/_cache_edgar") if p.resolve() != CACHE.resolve())
        main = wt.parent.parent / "results" / "events" / "_cache_edgar"
        if main.exists():
            roots.append(main)
    return roots


def _submissions(ticker: str) -> dict:
    cik = CIK[ticker]
    rel = Path("data.sec.gov") / "submissions" / f"CIK{cik:010d}.json"
    p = CACHE / rel
    if not p.exists():
        raise GateError(f"{rel} is not in {CACHE}; run `stage` (or the team lead's EDGAR fetch)")
    d = json.loads(p.read_text())
    if ticker not in (d.get("tickers") or []):
        raise GateError(f"CIK {cik} lists tickers {d.get('tickers')}, not {ticker}")
    return d


def filings(ticker: str, forms: tuple[str, ...]) -> pd.DataFrame:
    r = _submissions(ticker)["filings"]["recent"]
    df = pd.DataFrame({k: r[k] for k in ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument")})
    df = df[df.form.isin(forms)].copy()
    df["filingDate"] = pd.to_datetime(df.filingDate)
    df["reportDate"] = pd.to_datetime(df.reportDate)
    return df.sort_values(["reportDate", "filingDate"]).reset_index(drop=True)


def _doc_candidates(ticker: str, acc: str) -> list[Path]:
    nod = acc.replace("-", "")
    base = Path("www.sec.gov") / "Archives" / "edgar" / "data" / str(CIK[ticker]) / nod
    return [base / "primary_doc.xml", base / f"{acc}.txt"]


def wanted(ticker: str) -> pd.DataFrame:
    """N-PORT filings filed before the holdout, the latest N-PORT, and the N-CSRs
    at the two dates the state parse is checked against."""
    npt = filings(ticker, ("NPORT-P",))
    # Last filing per report date (an amendment would supersede; none seen here).
    npt = npt.groupby("reportDate").tail(1)
    fit = npt[npt.filingDate < HOLDOUT]
    latest = npt.tail(1)
    nc = filings(ticker, ("N-CSR", "N-CSRS"))
    nc = nc[nc.reportDate.isin(pd.to_datetime(["2022-07-31", "2026-07-31"]))]
    w = pd.concat([fit, latest, nc]).drop_duplicates("accessionNumber")
    return w.reset_index(drop=True)


def stage() -> dict:
    """Copy wanted documents from sibling worktrees' caches. Sources are only read."""
    CACHE.mkdir(parents=True, exist_ok=True)
    roots = _sibling_caches()
    log, missing = [], []
    for tk in CIK:
        sub = Path("data.sec.gov") / "submissions" / f"CIK{CIK[tk]:010d}.json"
        if not (CACHE / sub).exists():
            src = next((r / sub for r in roots if (r / sub).exists()), None)
            if src is None:
                missing.append(str(sub))
                continue
            (CACHE / sub).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, CACHE / sub)
            log.append(dict(rel=str(sub), src=str(src.parent.parent.parent.parent.parent.parent.name),
                            sha256=hashlib.sha256((CACHE / sub).read_bytes()).hexdigest()))
    if missing:
        raise GateError(f"submissions JSON missing everywhere: {missing}")
    for tk in CIK:
        for acc in wanted(tk).accessionNumber:
            if any((CACHE / c).exists() for c in _doc_candidates(tk, acc)):
                continue
            hit = None
            for r in roots:
                for c in _doc_candidates(tk, acc):
                    if (r / c).exists():
                        hit = (r, c)
                        break
                if hit:
                    break
            if hit is None:
                missing.append(f"{tk} {acc}")
                continue
            r, c = hit
            (CACHE / c).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(r / c, CACHE / c)
            log.append(dict(rel=str(c), src=r.parent.parent.parent.name,
                            sha256=hashlib.sha256((CACHE / c).read_bytes()).hexdigest()))
    man = CACHE / "_staged_from_worktrees.json"
    prev = json.loads(man.read_text()) if man.exists() else dict(staged=[])
    prev.update(staged_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                how="copied from sibling worktrees' gitignored EDGAR caches (public documents); sources read-only")
    prev["staged"] = prev.get("staged", []) + log
    man.write_text(json.dumps(prev, indent=1))
    if missing:
        raise GateError(
            "documents not cached anywhere: " + "; ".join(missing) + ". The team lead fetches them with "
            "the repo's EDGAR client (it reads SEC_USER_AGENT from the env file, which agents never open), "
            "e.g. `python3 -c \"from scripts.data.edgar_client import EdgarClient; ...\"`.")
    return dict(copied=len(log))


def _read_doc(tk: str, acc: str) -> str:
    for c in _doc_candidates(tk, acc):
        p = CACHE / c
        if p.exists():
            b = p.read_bytes()
            if b[:2] == b"\x1f\x8b":
                b = gzip.decompress(b)
            return b.decode("utf-8", errors="replace")
    raise GateError(f"{tk} {acc} is not in {CACHE}; run `stage`")


# ----------------------------------------------------------------------------- N-PORT parse
def _tag(rec: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", rec, flags=re.S)
    return m.group(1).strip() if m else None


def parse_nport(text: str) -> tuple[dict, pd.DataFrame]:
    """(fund info, holdings) from an NPORT-P primary_doc.xml or full submission .txt."""
    i = text.find("<edgarSubmission")
    if i < 0:
        raise GateError("no <edgarSubmission> element: not an N-PORT XML document")
    x = text[i:]
    # repPdEnd is the FISCAL period's end; repPdDate is the as-of date of the holdings
    # (MHD's 2019-10-31 report carries repPdEnd 2020-04-30). The check uses repPdDate.
    info = dict(rep_pd_date=_tag(x, "repPdDate"), rep_pd_end=_tag(x, "repPdEnd"), net_assets=_tag(x, "netAssets"),
                tot_assets=_tag(x, "totAssets"), reg_name=_tag(x, "regName"))
    for k in ("rep_pd_date", "net_assets"):
        if info[k] is None:
            raise GateError(f"N-PORT document lacks {k}")
    info["net_assets"] = float(info["net_assets"])
    recs = re.findall(r"<invstOrSec>(.*?)</invstOrSec>", x, flags=re.S)
    if not recs:
        raise GateError("N-PORT document has no <invstOrSec> holdings")
    rows = []
    for r in recs:
        pct = _tag(r, "pctVal")
        val = _tag(r, "valUSD")
        if pct is None or val is None:
            raise GateError("a holding lacks pctVal or valUSD")
        rows.append(dict(name=html.unescape(_tag(r, "name") or ""), title=html.unescape(_tag(r, "title") or ""),
                         cusip=_tag(r, "cusip"), val_usd=float(val), pct_val=float(pct),
                         asset_cat=_tag(r, "assetCat"), issuer_cat=_tag(r, "issuerCat"),
                         fair_val_level=_tag(r, "fairValLevel"), maturity=_tag(r, "maturityDt"),
                         is_default=_tag(r, "isDefault"), in_arrears=_tag(r, "areIntrstPmntsInArrs"),
                         is_pik=_tag(r, "isPaidKind")))
    return info, pd.DataFrame(rows)


def holdings_panel() -> pd.DataFrame:
    out = []
    for tk in CIK:
        w = wanted(tk)
        for _, f in w[w.form == "NPORT-P"].iterrows():
            info, h = parse_nport(_read_doc(tk, f.accessionNumber))
            if pd.Timestamp(info["rep_pd_date"]) != f.reportDate:
                raise GateError(f"{tk} {f.accessionNumber}: repPdDate {info['rep_pd_date']} != reportDate {f.reportDate.date()}")
            h["fund"], h["acc"] = tk, f.accessionNumber
            h["report_date"], h["filing_date"] = f.reportDate, f.filingDate
            h["net_assets"] = info["net_assets"]
            st = [parse_state(a, b) for a, b in zip(h.title, h.name)]
            h["state"] = [s for s, _ in st]
            h["state_method"] = [m for _, m in st]
            h["cusip6"] = h.cusip.where(h.cusip.notna() & (h.cusip.str.len() >= 6), None).str[:6]
            out.append(h)
    if not out:
        raise GateError("no N-PORT holdings parsed")
    H = pd.concat(out, ignore_index=True)
    # CUSIP-6 propagation: a weak parse (name_any) or none takes the state that a
    # strong parse gives the same issuer elsewhere in the panel, if exactly one.
    strong = H[H.state_method.isin(["code", "abbrev", "name_start", "known_issuer"]) & H.cusip6.notna()]
    by6 = strong.groupby("cusip6").state.agg(lambda s: s.iloc[0] if s.nunique() == 1 else None).dropna()
    weak = H.state_method.isin(["name_any", "unparsed"]) & H.cusip6.isin(by6.index)
    H.loc[weak, "state"] = H.loc[weak, "cusip6"].map(by6)
    H.loc[weak, "state_method"] = "cusip6"
    return H


def muni_rows(H: pd.DataFrame) -> pd.DataFrame:
    return H[(H.issuer_cat == "MUN") & (H.asset_cat == "DBT")]


def state_weights(H: pd.DataFrame) -> pd.DataFrame:
    """% of net assets by (fund, report_date, state); UNPARSED kept as its own row."""
    M = muni_rows(H).copy()
    M["state"] = M.state.fillna("UNPARSED")
    return (M.groupby(["fund", "report_date", "filing_date", "state"]).pct_val.sum()
            .rename("pct_nav").reset_index())


def concentration(H: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (tk, rd), g in muni_rows(H).groupby(["fund", "report_date"]):
        tot = g.pct_val.sum()
        s = g.groupby(g.state.fillna("UNPARSED")).pct_val.sum().sort_values(ascending=False)
        iss = g.groupby(g.cusip6.fillna(g.name)).pct_val.sum().sort_values(ascending=False)
        sh_s, sh_i = s / tot, iss / tot
        rows.append(dict(
            fund=tk, report_date=rd.date().isoformat(), filing_date=g.filing_date.iloc[0].date().isoformat(),
            n_muni_holdings=len(g), muni_pct_nav=round(tot, 2), n_states=int((s.index != "UNPARSED").sum()),
            unparsed_pct_nav=round(float(s.get("UNPARSED", 0.0)), 3),
            top1_state=s.index[0], top1_state_pct_nav=round(float(s.iloc[0]), 2),
            top5_states_share=round(float(sh_s.head(5).sum()), 3), state_hhi=round(float((sh_s ** 2).sum()), 4),
            n_issuers_cusip6=len(iss), top1_issuer_pct_nav=round(float(iss.iloc[0]), 2),
            top10_issuers_share=round(float(sh_i.head(10).sum()), 3), issuer_hhi=round(float((sh_i ** 2).sum()), 4),
            level3_pct_nav=round(float(g.loc[g.fair_val_level == "3", "pct_val"].sum()), 3),
        ))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- N-CSR check
def ncsr_state_headings(text: str, fund_label: str) -> dict[str, float]:
    """Sum the '<State> — x.x%' headings in one fund's schedule of investments
    (both the direct and the TOB-trust sections), % of net assets."""
    t = re.sub(r"<[^>]+>", " ", text)
    t = html.unescape(t)
    t = re.sub(r"[^\S\n]+", " ", t)        # every Unicode space (N-CSRs use U+2009 in "New York")
    t = re.sub(r"\s*\n\s*", "\n", t)
    starts = [m.start() for m in re.finditer(r"Schedule of Investments\s", t)
              if fund_label in t[m.start():m.start() + 250]]
    if not starts:
        raise GateError(f"no schedule of investments for {fund_label} in the N-CSR")
    a = starts[0]
    nxt = [m.start() for m in re.finditer(r"Schedule of Investments\s", t)
           if m.start() > a and fund_label not in t[m.start():m.start() + 250]]
    b = nxt[0] if nxt else len(t)
    seg = t[a:b]
    out: dict[str, float] = {}
    # MULTILINE anchors, not literal newlines: two headings on adjacent lines must
    # both count (a trailing "\n" consumed by one match hid the next; test pins it).
    for m in re.finditer(r"^([A-Z][A-Za-z .]+?) [—–-] (\d+(?:\.\d+)?)%$", seg, flags=re.M):
        nm = m.group(1).strip().upper()
        if nm in NAME_TO_CODE:
            out[NAME_TO_CODE[nm]] = out.get(NAME_TO_CODE[nm], 0.0) + float(m.group(2))
    if not out:
        raise GateError(f"no state headings parsed for {fund_label}")
    return out


FUND_LABEL = {"MHD": "BlackRock MuniHoldings Fund, Inc. (MHD)", "MQY": "BlackRock MuniYield Quality Fund, Inc. (MQY)"}


def ncsr_check(H: pd.DataFrame) -> pd.DataFrame:
    """N-PORT parse vs N-CSR headings, same report date. Both % of net assets."""
    rows = []
    sw = state_weights(H)
    for tk in CIK:
        w = wanted(tk)
        for _, f in w[w.form.isin(["N-CSR", "N-CSRS"])].iterrows():
            nc = ncsr_state_headings(_read_doc(tk, f.accessionNumber), FUND_LABEL[tk])
            npt = sw[(sw.fund == tk) & (sw.report_date == f.reportDate)].set_index("state").pct_nav
            if npt.empty:
                raise GateError(f"no N-PORT for {tk} at {f.reportDate.date()} to check the N-CSR against")
            for st in sorted(set(nc) | set(npt.index)):
                rows.append(dict(fund=tk, report_date=f.reportDate.date().isoformat(), state=st,
                                 ncsr_pct_nav=nc.get(st, np.nan), nport_pct_nav=round(float(npt.get(st, np.nan)), 2)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- B1: N-PORT flags
def b1_flags(H: pd.DataFrame) -> pd.DataFrame:
    M = muni_rows(H).copy()
    M["flag"] = (M.is_default == "Y") | (M.in_arrears == "Y")
    rows = []
    for tk, g in M.groupby("fund"):
        prev: set = set()
        for rd, q in g.groupby("report_date"):
            f = q[q.flag]
            cur = set(f.cusip.dropna())
            new = cur - prev
            rows.append(dict(fund=tk, report_date=rd.date().isoformat(), n_flagged=len(cur),
                             flagged_pct_nav=round(float(f.pct_val.sum()), 3), n_new=len(new),
                             new_pct_nav=round(float(f[f.cusip.isin(new)].pct_val.sum()), 3),
                             new_names="; ".join(sorted(set(f[f.cusip.isin(new)].name)))[:300]))
            prev = cur
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- B2: FEMA
def fema_events() -> pd.DataFrame:
    if not FEMA_CSV.exists():
        raise GateError(f"{FEMA_CSV} missing; run scripts/events/fetch_fema_declarations.py")
    d = pd.read_csv(FEMA_CSV, parse_dates=["declarationDate", "incidentBeginDate"])
    need = {"incidentId", "state", "declarationDate", "declarationType", "incidentType", "declarationTitle"}
    if need - set(d.columns):
        raise GateError(f"FEMA CSV lacks {sorted(need - set(d.columns))}")
    g = d.sort_values("declarationDate").groupby(["incidentId", "state"], sort=False)
    ev = g.agg(t_declared=("declarationDate", "min"), incident_begin=("incidentBeginDate", "min"),
               incident_type=("incidentType", "first"), title=("declarationTitle", "first"),
               types=("declarationType", lambda s: "+".join(sorted(set(s))))).reset_index()
    return ev


def fema_lags() -> pd.DataFrame:
    d = pd.read_csv(FEMA_CSV, parse_dates=["declarationDate", "incidentBeginDate"])
    d["lag_days"] = (d.declarationDate - d.incidentBeginDate).dt.days
    return d.groupby("declarationType").lag_days.describe()[["count", "25%", "50%", "75%"]]


def exposure_asof(sw: pd.DataFrame, fund: str, state: str, t: pd.Timestamp) -> tuple[float, str, pd.Timestamp | None]:
    """(% NAV in `state`, basis, filing date used) from the latest N-PORT FILED
    STRICTLY BEFORE `t`. Before the first filing: the first filing, basis PROXY."""
    f = sw[sw.fund == fund]
    if f.empty:
        raise GateError(f"no state weights for {fund}")
    dates = np.sort(f.filing_date.unique())
    prior = dates[dates < np.datetime64(t)]
    if len(prior):
        fd, basis = pd.Timestamp(prior[-1]), "pit"
    else:
        fd, basis = pd.Timestamp(dates[0]), "proxy"
    assert basis == "proxy" or fd < t, "lookahead: holdings filed on/after the event date"
    x = f[(f.filing_date == fd) & (f.state == state)].pct_nav.sum()
    return float(x), basis, fd


def b2_incidence(sw: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    ev = fema_events()
    ev = ev[(ev.t_declared.dt.year >= FIRST_FIT_YEAR) & (ev.t_declared < HOLDOUT)].copy()
    pos = sessions.searchsorted(ev.t_declared)
    ok = pos < len(sessions)
    ev = ev[ok].copy()
    ev["t0"] = sessions[pos[ok]]
    # The news date, for the POST-HOC descriptive cut only: incidentBeginDate is
    # stated in the declaration, so for a DR-only event it is not knowable on the
    # day it names. Never a flag input.
    pi = sessions.searchsorted(ev.incident_begin.fillna(ev.t_declared))
    ev["t_news"] = [sessions[i] if i < len(sessions) else pd.NaT for i in pi]
    rows = []
    for _, e in ev.iterrows():
        for tk in CIK:
            w, basis, fd = exposure_asof(sw, tk, e.state, e.t_declared)
            rows.append(dict(fund=tk, incidentId=e.incidentId, state=e.state, incident_type=e.incident_type,
                             types=e.types, title=e.title, t_declared=e.t_declared, t0=e.t0, t_news=e.t_news,
                             incident_begin=e.incident_begin, pct_nav=w, basis=basis, holdings_filed=fd))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- prices and NAV
def _assert_fit_only(dates) -> None:
    d = pd.DatetimeIndex(dates)
    if len(d) and d.max() >= HOLDOUT:
        raise GateError(f"a window reaches {d.max().date()}: the 2023-01-01 time holdout is sealed")


def tr_logs(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily log total-return of price and NAV, distribution added back on the ex-date
    to BOTH (so ex-date arithmetic cancels in the gap). Rows before the holdout only."""
    P = pd.read_parquet(DATA / "cef" / "cef_prices.parquet")
    N = pd.read_parquet(DATA / "cef" / "cef_nav.parquet")
    D = pd.read_parquet(DATA / "cef" / "cef_distributions.parquet")
    P, N, D = P[P.ticker.isin(tickers)], N[N.ticker.isin(tickers)], D[D.ticker.isin(tickers)]
    px = P.pivot_table(index="date", columns="ticker", values="close").sort_index()
    nv = N.pivot_table(index="date", columns="ticker", values="nav").sort_index()
    idx = px.index.intersection(nv.index)
    idx = idx[idx < HOLDOUT]
    px, nv = px.reindex(idx), nv.reindex(idx)
    dv = D.groupby(["ex_date", "ticker"]).amount.sum().unstack().reindex(idx).fillna(0.0)
    dv = dv.reindex(columns=px.columns).fillna(0.0)   # a name with no distribution row has none on that date
    rp = np.log((px + dv) / px.shift(1))
    rn = np.log((nv + dv) / nv.shift(1))
    return rp, rn


def window_sum(r: pd.DataFrame, i0: int, a: int, b: int, col: str) -> float:
    """Sum of daily log returns from close(i0+a) to close(i0+b), i.e. rows i0+a+1 .. i0+b."""
    lo, hi = i0 + a + 1, i0 + b
    if lo < 1 or hi >= len(r):
        return np.nan
    v = r[col].iloc[lo:hi + 1]
    return float(v.sum()) if v.notna().all() else np.nan


def anchor_stats(rp, rn, anchors: list[tuple[str, int]]) -> pd.DataFrame:
    rows = []
    for col, i0 in anchors:
        dp_n, dn_n = window_sum(rp, i0, *NEWS, col), window_sum(rn, i0, *NEWS, col)
        dp_c, dn_c = window_sum(rp, i0, *CATCH, col), window_sum(rn, i0, *CATCH, col)
        rows.append(dict(ticker=col, t0=rp.index[i0], gap_news=dp_n - dn_n, nav_news=dn_n, px_news=dp_n,
                         nav_catch=dn_c, px_catch=dp_c, gap_catch=dp_c - dn_c))
    return pd.DataFrame(rows).dropna()


def _ols_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    n = len(x)
    if n < 10:
        return np.nan, np.nan, n
    X = np.column_stack([np.ones(n), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    # White (HC1) standard error: event anchors are non-overlapping by construction
    # within a fund; across funds they share dates, so this is optimistic (stated).
    XtX = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    V = XtX @ S @ XtX * n / (n - 2)
    return float(b[1]), float(np.sqrt(V[1, 1])), n


# POST-HOC (added after the first run, 2026-10-20, labelled as such everywhere):
# weather events whose earliest declaration came within a week of the incident's
# begin date, fire-management (FM-only) declarations excluded, anchored at the
# NEWS date. It asks the descriptive question ("did the discount move before the
# NAV around the actual news?") that the declaration-dated test cannot, because
# DR-only declarations come weeks late. It is not a flag design.
POSTHOC_TYPES = ("Hurricane", "Tropical Storm", "Typhoon", "Severe Storm", "Flood", "Winter Storm",
                 "Snowstorm", "Severe Ice Storm", "Tornado", "Coastal Storm")
POSTHOC_MAX_LAG_DAYS = 7


def posthoc_filter(inc: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    """The post-hoc cut, re-anchored at the news date, with exposure re-read from the
    latest N-PORT filed strictly before the NEWS date (not the declaration date)."""
    lag = (inc.t_declared - inc.incident_begin).dt.days
    m = inc.incident_type.isin(POSTHOC_TYPES) & (inc.types != "FM") & (lag <= POSTHOC_MAX_LAG_DAYS)
    out = inc[m].copy()
    re_w = [exposure_asof(sw, r.fund, r.state, r.incident_begin) for r in out.itertuples()]
    out["pct_nav"] = [w for w, _, _ in re_w]
    out["basis"] = [b for _, b, _ in re_w]
    out["t0"] = out["t_news"]
    return out


def _diff(a: dict, b: dict, key: str, se_key: str) -> dict:
    if a.get(key) is None or b.get(key) is None or a.get(se_key) is None or b.get(se_key) is None:
        return dict(diff=None)
    d = a[key] - b[key]
    se = float(np.hypot(a[se_key], b[se_key]))
    return dict(diff=round(d, 4), se=round(se, 4), t=round(d / se, 2) if se > 0 else None)


def signature(inc: pd.DataFrame, taxable: list[str]) -> dict:
    tick = list(CIK) + taxable
    rp, rn = tr_logs(tick)
    idx = rp.index
    pos = {d: i for i, d in enumerate(idx)}
    out: dict = {}
    hz = inc[~inc.incident_type.isin(EXCLUDED_TYPES)]
    # Only anchors whose catch-up window closes before the holdout.
    def ok(i):
        return i is not None and i + CATCH[1] < len(idx) and i + NEWS[0] >= 1
    touched = hz[hz.pct_nav >= TOUCH_W]
    # One anchor per (fund, t0): several states/incidents can share a session.
    ev_anchor = (touched.groupby(["fund", "t0", "basis"]).pct_nav.max().reset_index())
    ev_anchor["i0"] = ev_anchor.t0.map(pos)
    ev_anchor = ev_anchor[ev_anchor.i0.map(lambda i: ok(i) if pd.notna(i) else False)]
    for i in ev_anchor.i0:
        _assert_fit_only([idx[int(i) + CATCH[1]]])
    # Baseline: every 9th session per fund (non-overlapping 9-session windows), dropping
    # any within 10 sessions of an event anchor for that fund.
    res = {}
    for basis in ("pit", "proxy"):
        ea = ev_anchor[ev_anchor.basis == basis]
        if ea.empty:
            res[basis] = dict(n_event_anchors=0)
            continue
        lo_d, hi_d = ea.t0.min(), ea.t0.max()
        S = {}
        for grp, names in (("muni", list(CIK)), ("taxable_control", taxable)):
            ev_rows, base_rows = [], []
            for tk in CIK:
                ei = sorted(int(i) for i in ea[ea.fund == tk].i0)
                cols = [tk] if grp == "muni" else names
                for c in cols:
                    ev_rows.append(anchor_stats(rp, rn, [(c, i) for i in ei]).assign(fund=tk))
                    lo, hi = pos[lo_d], pos[hi_d]
                    near = set()
                    for i in ei:
                        near.update(range(i - 10, i + 11))
                    bi = [i for i in range(max(lo, 4), min(hi, len(idx) - CATCH[1] - 1) + 1, 9) if i not in near]
                    base_rows.append(anchor_stats(rp, rn, [(c, i) for i in bi]).assign(fund=tk))
            E = pd.concat(ev_rows, ignore_index=True)
            B = pd.concat(base_rows, ignore_index=True)
            _assert_fit_only(list(E.t0) + list(B.t0))
            def desc(df):
                if df.empty:
                    return dict(n=0)
                b, se, n = _ols_slope(df.gap_news.values, df.nav_catch.values)
                return dict(n=int(len(df)), mean_gap_news_bp=round(1e4 * df.gap_news.mean(), 2),
                            sd_gap_news_bp=round(1e4 * df.gap_news.std(), 2),
                            se_mean_gap_news_bp=round(1e4 * df.gap_news.std() / np.sqrt(len(df)), 2),
                            mean_nav_news_bp=round(1e4 * df.nav_news.mean(), 2),
                            mean_px_news_bp=round(1e4 * df.px_news.mean(), 2),
                            mean_nav_catch_bp=round(1e4 * df.nav_catch.mean(), 2),
                            mean_px_catch_bp=round(1e4 * df.px_catch.mean(), 2),
                            catchup_slope=round(b, 4) if np.isfinite(b) else None,
                            catchup_slope_se=round(se, 4) if np.isfinite(se) else None)
            de, db = desc(E), desc(B)
            S[grp] = dict(event=de, baseline=db,
                          event_minus_baseline_gap_news_bp=_diff(de, db, "mean_gap_news_bp", "se_mean_gap_news_bp"),
                          event_minus_baseline_slope=_diff(de, db, "catchup_slope", "catchup_slope_se"))
            if grp == "muni":
                # Minimum detectable mean gap at 5% two-sided, 80% power, from the baseline sd.
                sd = B.gap_news.std()
                S[grp]["mde_mean_gap_news_bp"] = round(1e4 * 2.8 * sd / np.sqrt(max(len(E), 1)), 1)
                S[grp]["event_rows"] = E.assign(t0=E.t0.dt.date.astype(str)).round(6).to_dict("records")
        mu_d, co_d = S["muni"]["event_minus_baseline_slope"], S["taxable_control"]["event_minus_baseline_slope"]
        if mu_d.get("diff") is not None and co_d.get("diff") is not None:
            S["muni_minus_control_slope_did"] = _diff(mu_d, co_d, "diff", "se")
        res[basis] = dict(n_event_anchors=int(len(ea)), first=str(lo_d.date()), last=str(hi_d.date()), **S)
    out["by_basis"] = res
    return out


# ----------------------------------------------------------------------------- turnover
def turnover_share(inc: pd.DataFrame) -> dict:
    from scripts.cef.band_frontier import build_targets, band
    from scripts.cef.spec import BAND_WIDTH, UNIVERSE
    T, _R = build_targets()           # R is never read: no return enters this gate
    T = T[T.index < HOLDOUT]
    _assert_fit_only(T.index)
    H = band(T, BAND_WIDTH)
    turn = H.diff().abs()
    turn.iloc[0] = H.iloc[0].abs()
    tot = float(turn.values.sum())
    eras = {"2005-09": ("2005", "2009"), "2010-14": ("2010", "2014"), "2015-19": ("2015", "2019"), "2020-22": ("2020", "2022")}
    muni_cols = [c for c in CIK if c in UNIVERSE]
    by_era = {}
    for k, (a, b) in eras.items():
        t = turn.loc[a:b]
        s = float(t.values.sum())
        by_era[k] = dict(book_turnover=round(s, 3),
                         muni_share=round(float(t[muni_cols].values.sum()) / s, 4) if s > 0 else None,
                         muni_days_targeted=round(float((T.loc[a:b, muni_cols] != 0).mean().mean()), 3))
    # Flag coverage: a touched fund's decisions on t0 .. t0+CATCH[1]-1 (the sessions
    # whose shift(2) trades would still sit inside the catch-up window).
    hz = inc[(~inc.incident_type.isin(EXCLUDED_TYPES)) & (inc.pct_nav >= TOUCH_W)]
    flag = pd.DataFrame(False, index=turn.index, columns=muni_cols)
    for _, e in hz.iterrows():
        if e.fund not in muni_cols or e.t0 not in flag.index:
            continue
        i = flag.index.get_loc(e.t0)
        flag.iloc[i:i + CATCH[1], flag.columns.get_loc(e.fund)] = True
    out = {}
    dH = H.diff()
    dH.iloc[0] = H.iloc[0]
    grow_long = (dH > 0) & (H > 0)        # what a subtract-only flag would block
    for basis_lbl, sub in (("pit_2019-12-24_to_2022", turn.loc["2019-12-24":"2022-12-31"]),
                           ("proxy_2005_to_2019-12-23", turn.loc["2005-01-01":"2019-12-23"])):
        fl = flag.reindex(sub.index)
        m = sub[muni_cols]
        gl = grow_long.reindex(sub.index)[muni_cols]
        out[basis_lbl] = dict(
            flagged_muni_turnover_opening_or_growing_long_share_of_book=round(
                float(m.where(fl & gl).fillna(0).values.sum()) / float(sub.values.sum()), 4) if sub.values.sum() > 0 else None,
            sessions=int(len(sub)),
            share_of_muni_name_days_flagged=round(float(fl.values.mean()), 4),
            muni_turnover_share_of_book=round(float(m.values.sum()) / float(sub.values.sum()), 4) if sub.values.sum() > 0 else None,
            flagged_muni_turnover_share_of_book=round(float(m.where(fl).fillna(0).values.sum()) / float(sub.values.sum()), 4)
            if sub.values.sum() > 0 else None)
    return dict(book_turnover_total=round(tot, 3), muni_names=muni_cols, by_era=by_era, flag=out,
                note="turnover = sum |dH| of band(T, BAND_WIDTH), fit period; no return read")


def muni_direction() -> dict:
    """Fit-period muni holdings by sign, and the turnover a subtract-only flag could
    block: trades that OPEN OR GROW A LONG (the hazard as posed: the z-score buys an
    information-driven widening). Covering a short is a subtraction and stays allowed."""
    from scripts.cef.band_frontier import build_targets, band
    from scripts.cef.spec import BAND_WIDTH
    T, _R = build_targets()           # R is never read
    T = T[T.index < HOLDOUT]
    _assert_fit_only(T.index)
    H = band(T, BAND_WIDTH)
    out = {}
    for c in CIK:
        h = H[c]
        d = h.diff().fillna(h)
        grow_long = (d > 0) & (h > 0)
        h2, d2 = h.loc["2020":"2022"], d.loc["2020":"2022"]
        out[c + "_2020-22"] = dict(share_days_long=round(float((h2 > 0).mean()), 4),
                                   share_days_short=round(float((h2 < 0).mean()), 4),
                                   turnover=round(float(d2.abs().sum()), 3),
                                   turnover_opening_or_growing_long=round(float(d2[(d2 > 0) & (h2 > 0)].abs().sum()), 3))
        out[c] = dict(share_days_long=round(float((h > 0).mean()), 4), share_days_short=round(float((h < 0).mean()), 4),
                      turnover=round(float(d.abs().sum()), 3),
                      turnover_opening_or_growing_long=round(float(d[grow_long].abs().sum()), 3))
    return out


def adv_eligibility() -> dict:
    """Share of sessions on which each muni name clears the spec's ADV floor, by era.
    PRICE x VOLUME LEVELS ONLY, no return, so the 2023-26 row does not open the time
    holdout; the alignment is build_panel's (63-session mean, shift(1))."""
    from scripts.cef.spec import MIN_ADV_USD
    P = pd.read_parquet(DATA / "cef" / "cef_prices.parquet")
    P = P[P.ticker.isin(list(CIK))]
    px = P.pivot_table(index="date", columns="ticker", values="close").sort_index()
    vol = P.pivot_table(index="date", columns="ticker", values="volume").sort_index()
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    eras = {"2005-09": ("2005", "2009"), "2010-14": ("2010", "2014"), "2015-19": ("2015", "2019"),
            "2020-22": ("2020", "2022"), "2023-26 (levels only)": ("2023", "2026")}
    return dict(last_date=str(adv.index.max().date()), min_adv_usd=MIN_ADV_USD,
                share=({k: (adv.loc[a:b] >= MIN_ADV_USD).mean().round(3).to_dict() for k, (a, b) in eras.items()}))


# ----------------------------------------------------------------------------- main
def muni_spec_names() -> list[str]:
    from scripts.cef.spec import UNIVERSE
    f = pd.read_csv(DATA / "cef" / "cef_facts.csv")
    grp = dict(zip(f.ticker, f.grp))
    missing = [t for t in UNIVERSE if t not in grp]
    if missing:
        raise GateError(f"cef_facts.csv has no group for spec name(s) {missing}")
    return [t for t in UNIVERSE if grp[t] == "muni"]


def run() -> dict:
    from scripts.cef.spec import UNIVERSE
    munis = muni_spec_names()
    if sorted(munis) != sorted(CIK):
        raise GateError(f"spec muni names are {munis}; this script's CIK table covers {sorted(CIK)}")
    f = pd.read_csv(DATA / "cef" / "cef_facts.csv")
    grp = dict(zip(f.ticker, f.grp))
    taxable = [t for t in UNIVERSE if grp[t] != "muni"]
    OUT.mkdir(parents=True, exist_ok=True)
    H = holdings_panel()
    sw = state_weights(H)
    conc = concentration(H)
    chk = ncsr_check(H)
    b1 = b1_flags(H)
    methods = (muni_rows(H).groupby(["fund", "state_method"]).pct_val.sum().round(2).unstack(fill_value=0.0))
    P = pd.read_parquet(DATA / "cef" / "cef_prices.parquet")
    sessions = pd.DatetimeIndex(sorted(P[P.ticker.isin(list(CIK))].date.unique()))
    sessions = sessions[sessions < HOLDOUT]
    inc = b2_incidence(sw, sessions)
    # Top holdings: the states of each filing's ten largest issuers (CUSIP-6), joined
    # on the SAME filing `exposure_asof` chose, so no lookahead is added.
    M_all = muni_rows(H)
    top10 = (M_all.groupby(["fund", "filing_date", "cusip6"]).agg(w=("pct_val", "sum"), state=("state", "first"))
             .reset_index().sort_values("w", ascending=False).groupby(["fund", "filing_date"]).head(10)
             .groupby(["fund", "filing_date"]).state.agg(lambda x: set(x.dropna())))
    inc["top10_issuer_state"] = [r.state in top10.get((r.fund, r.holdings_filed), set()) for r in inc.itertuples()]
    sig = signature(inc, taxable)
    sig_posthoc = signature(posthoc_filter(inc, sw), taxable)
    tov = turnover_share(inc)
    direction = muni_direction()

    # Incidence tables
    hz = inc[~inc.incident_type.isin(EXCLUDED_TYPES)].copy()
    hz["bucket"] = pd.cut(hz.pct_nav, BUCKETS, right=False, labels=["0-2", "2-5", "5-10", ">=10"])
    hz["year"] = hz.t0.dt.year
    inc_year = (hz.groupby(["fund", "basis", "year"]).agg(
        events=("incidentId", "size"), touched=("pct_nav", lambda s: int((s >= TOUCH_W).sum())))
        .reset_index())
    inc_bucket = hz.groupby(["fund", "basis", "bucket"], observed=False).size().unstack(fill_value=0)
    inc_type = (hz[hz.pct_nav >= TOUCH_W].groupby(["fund", "basis", "incident_type"]).size().unstack(fill_value=0))
    touched_list = (hz[hz.pct_nav >= TOUCH_W].sort_values("t0")
                    [["fund", "basis", "t0", "state", "incident_type", "types", "title", "pct_nav"]])
    bio = inc[inc.incident_type.isin(EXCLUDED_TYPES)]

    # Latest holdings snapshot
    latest = conc.sort_values("report_date").groupby("fund").tail(1)
    sw_latest = sw.merge(latest[["fund", "report_date"]].assign(report_date=lambda d: pd.to_datetime(d.report_date)))
    top_states = (sw_latest.sort_values("pct_nav", ascending=False).groupby("fund").head(10)
                  [["fund", "report_date", "state", "pct_nav"]])
    M = muni_rows(H)
    lastM = M.merge(latest[["fund", "report_date"]].assign(report_date=lambda d: pd.to_datetime(d.report_date)))
    top_iss = (lastM.groupby(["fund", "cusip6"]).agg(pct_nav=("pct_val", "sum"), name=("name", "first"),
                                                       state=("state", "first"))
               .reset_index().sort_values("pct_nav", ascending=False).groupby("fund").head(10))

    # Persist aggregates (tracked) and the row-level holdings (gitignored cache).
    conc.to_csv(OUT / "concentration_by_quarter.csv", index=False)
    sw.assign(report_date=sw.report_date.dt.date, filing_date=sw.filing_date.dt.date).round(4).to_csv(
        OUT / "state_weights_by_quarter.csv", index=False)
    chk.to_csv(OUT / "ncsr_state_check.csv", index=False)
    b1.to_csv(OUT / "b1_nport_default_flags.csv", index=False)
    touched_list.assign(t0=touched_list.t0.dt.date, pct_nav=touched_list.pct_nav.round(2)).to_csv(
        OUT / "b2_touched_events.csv", index=False)
    top_iss.round(3).to_csv(OUT / "top_issuers_latest.csv", index=False)
    (OUT / "_cache_holdings").mkdir(exist_ok=True)
    H.to_csv(OUT / "_cache_holdings" / "nport_holdings_rows.csv.gz", index=False)

    chk2 = chk.dropna()
    summary = dict(
        generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        script="scripts/events/muni_hazard_gate.py run", zero_trials=True,
        holdout="no price or NAV row dated on/after 2023-01-01 is read (asserted)",
        spec_muni_names=munis, taxable_control=taxable,
        nport_filings={tk: [d.date().isoformat() for d in sorted(H[H.fund == tk].report_date.unique())] for tk in CIK},
        nport_filing_lag_days=(lambda f: dict(min=int(f.min()), median=float(f.median()), max=int(f.max()), n=int(len(f))))(
            (H.drop_duplicates(["fund", "acc"]).filing_date - H.drop_duplicates(["fund", "acc"]).report_date).dt.days),
        latest=latest.to_dict("records"),
        top_states_latest=top_states.round(2).to_dict("records"),
        state_parse_methods_pct_nav=methods.to_dict(),
        ncsr_check=dict(rows=int(len(chk2)),
                        max_abs_diff_pp=round(float((chk2.ncsr_pct_nav - chk2.nport_pct_nav).abs().max()), 2),
                        mean_abs_diff_pp=round(float((chk2.ncsr_pct_nav - chk2.nport_pct_nav).abs().mean()), 3),
                        states_only_in_one=int(chk.isna().any(axis=1).sum())),
        b1=dict(quarters=int(len(b1)), max_flagged_pct_nav=float(b1.flagged_pct_nav.max()),
                new_flags_fit=int(b1[pd.to_datetime(b1.report_date) < HOLDOUT].n_new.sum()),
                new_flag_pct_nav_fit=float(b1[pd.to_datetime(b1.report_date) < HOLDOUT].new_pct_nav.sum())),
        fema_lag_days=fema_lags().round(1).to_dict("index"),
        b2_incidence=dict(
            events_by_bucket=inc_bucket.reset_index().astype({"basis": str}).to_dict("records"),
            touched_by_type=inc_type.reset_index().to_dict("records"),
            per_year=inc_year.to_dict("records"),
            biological_rows=int(len(bio)), biological_touched=int((bio.pct_nav >= TOUCH_W).sum()),
            touched_fm_only=int(((hz.pct_nav >= TOUCH_W) & (hz.types == "FM")).sum()),
            touched_total=int((hz.pct_nav >= TOUCH_W).sum()),
            top10_issuer_state=(hz.groupby(["fund", "basis"]).agg(
                events=("incidentId", "size"), in_a_top10_issuer_state=("top10_issuer_state", "sum"),
                touched=("pct_nav", lambda x: int((x >= TOUCH_W).sum())))
                .reset_index().to_dict("records"))),
        signature=sig, signature_posthoc_news_anchor=sig_posthoc, turnover=tov, direction=direction,
        adv_eligibility=adv_eligibility(),
        declared=dict(touch_w_pct_nav=TOUCH_W, news_window=NEWS, catch_window=CATCH, excluded=EXCLUDED_TYPES),
    )
    # Per-event price/NAV rows stay in the gitignored cache; the tracked JSON keeps statistics.
    rows = {}
    for lab in ("signature", "signature_posthoc_news_anchor"):
        for basis, v in summary[lab]["by_basis"].items():
            if "muni" in v and "event_rows" in v["muni"]:
                rows[f"{lab}|{basis}"] = v["muni"].pop("event_rows")
    (OUT / "_cache_holdings" / "signature_event_rows.json").write_text(json.dumps(rows, default=str))
    (OUT / "summary_2026-10-20.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("stage", "run"))
    a = ap.parse_args(argv)
    if a.cmd == "stage":
        print(json.dumps(stage()))
        return 0
    s = run()
    print(json.dumps({k: s[k] for k in ("spec_muni_names", "ncsr_check", "b1", "turnover")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
