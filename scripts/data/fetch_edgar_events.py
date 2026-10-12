"""The EDGAR event fetcher: corporate-action filings of CEFs and BDCs, 2010 onward (plan item 0.7).

    export QUANTT_ENV_FILE=/abs/path/config/.env      # SEC_USER_AGENT is read from it, never printed
    python3 scripts/data/fetch_edgar_events.py         # indexes -> event table, episodes, summary
    python3 scripts/data/fetch_edgar_events.py --offline   # rebuild from the cache, no network

WHY THIS EXISTS
---------------
`results/cef/RESEARCH_PLAN_2026-10-09.md` item 0.7. Three things wait on dated
corporate actions of closed-end funds and BDCs: the merger pair's entry date
(E1; the 2026-10-11 re-run had announcement dates for 12 of ~110 deal groups,
`results/events/REPRO_CEF_EVENTS_2026-10-11.md` §7), the corporate-action
filter on the live book (C1, gate G6), and the CEF IPO and term-CEF events
(G7, plan 0.8). CRSP gives a merger's completion date; only EDGAR gives the
date the market learned of it.

WHICH EDGAR ROUTE, AND WHY (all documented on sec.gov; docs/REFERENCES.md §12g)
------------------------------------------------------------------------------
1. **The quarterly full indexes**, `Archives/edgar/full-index/{YYYY}/QTR{n}/master.gz`
   (pipe-delimited `CIK|Company Name|Form Type|Date Filed|Filename`). This is
   the SEC's documented route for "every filing of a given form in a period"
   (https://www.sec.gov/os/accessing-edgar-data, "full indexes"). It is the
   only route that is COMPLETE across all filers without first knowing who
   they are, which is exactly the problem: there is no SEC list of closed-end
   funds, and most of the funds that merged away 2010-22 have no ticker in the
   SEC's ticker file today. One request per quarter (~3 MB gzipped).
   A filing appears once for EACH party it is indexed under -- a Rule 425
   communication is listed under the filer AND every subject company
   (verified on 2012-Q2: the Nuveen New York 425s of 2012-06-22 are indexed
   under the acquirer NRK and under each target). So a fund's own index rows
   include the deals it was the subject of.
2. **The submissions API**, `data.sec.gov/submissions/CIK##########.json`
   (https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
   per fund, where a caller needs fields the index lacks: 8-K item numbers,
   the primary document's name, the acceptance time. Used for named funds
   only (the 13 spec names, merger targets and acquirers), never as a crawl.
3. **The SEC ticker file**, `files/company_tickers_exchange.json`: CIK -> the
   ticker and exchange TODAY. "Ticker where mappable" means exactly that: a
   fund that no longer trades has no ticker in this table, by design. (A
   CRSP-matched ticker for dead funds exists only in the gitignored merger
   tables, because CRSP is licensed: `.gitignore`, results/events block.)
Full-text search (efts.sec.gov) is NOT used: it is the back end of a web form
the SEC documents as a user interface, not as an API, and the index route
above already finds every filing of the forms we need.

WHICH FUNDS: A CEF/BDC IS A FILER OF A CLOSED-END-ONLY FORM
-----------------------------------------------------------
No form says "I am a closed-end fund", but several are filed only by
closed-end funds or BDCs: the N-2 registration family (N-2, N-2/A, N-2ASR,
N-2 POSASR, N-2MEF), the closed-end merger registration N-14 8C (an open-end
fund files plain N-14), the BDC election and withdrawal (N-54A, N-54C, N-6F),
the closed-end redemption notice N-23C-2 and the interval-fund repurchase
notices N-23C3A/B/C. A CIK that filed any of them from 2008-Q1 on is in the
set with `set_rule = "marker_form"` (`MARKER_FORMS`). Its blind spot is a fund
that filed none of them in that time: an old fund that never raised capital,
redeemed preferred shares or acquired another fund. Measured, not assumed: of
the 44 tickers of `data/cef/cef_universe.csv`, 41 are in it and EDD, NIM and
TEI are not (2026-10-12).

So a second rule catches the old funds, labelled `set_rule = "ncsr_insider"`:
a CIK that filed an N-CSR (it is a registered management investment company)
AND appears in the index on a Form 3 or 4 (insider reports). Section 30(h) of
the Investment Company Act puts a CLOSED-END fund's directors, officers and
10% holders under Section 16 reporting; an open-end fund's do not file. It
catches all three misses. Its known false positive: the index lists a Form 4
under the REPORTING OWNER as well as the issuer, so an open-end trust that
itself owns 10% of a listed company appears too. A read of 60 randomly drawn
names from this tier (2026-10-12) found 6 open-end or ETF trusts (iShares
Trust, Schwab Strategic Trust, ...): about 90% precision [U, one sample].
Anything that needs certainty about a fund's type checks the fund, not the set.
Non-traded CEFs (interval funds, registered funds of hedge funds) and
non-traded BDCs are in the set too; `ticker_now` separates the listed ones.

WHAT IS OUTPUT
--------------
* `results/events/_cache_edgar/` -- raw responses (gitignored).
* `results/events/edgar_cef_bdc_filings.csv.gz` -- one row per (fund, filing)
  for the event forms below, 2008-01-01 on (2008-09 kept as look-back for deals
  completed in 2010; `in_scope` marks 2010+). Public EDGAR data.
* `results/events/edgar_cef_bdc_episodes.csv` -- the dated events: per fund,
  each tender offer, merger and proxy contest as an episode, with the dates the
  filings let us extract (see `episodes`).
* `results/events/edgar_events_summary.json` -- counts by form and year,
  coverage, the marker-set check, and the fetch log (requests, cache hits).

DATES: WHAT A FILING DATE MEANS (alignment for any later backtest)
------------------------------------------------------------------
EDGAR's filing date is the business day on which the submission was accepted
by 17:30 ET; a submission accepted after 17:30 gets the NEXT business day's
date (EDGAR Filer Manual Vol. II §3, [S]). So a filing dated t was public by
17:30 ET on t: an evening decision on t (the live book decides at 22:00 ET,
docs/RUNNER.md) may use it, a decision at t's close may not. Any consumer that
decides at the close must lag it a day.

NO SILENT FALLBACKS
-------------------
A malformed index line raises naming the quarter and the line number. A form
not in the taxonomy is not an event and is not kept (it is counted). A missing
quarter raises. Nothing here guesses a CIK, a ticker or a date.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events"
FILINGS_OUT = OUT / "edgar_cef_bdc_filings.csv.gz"
EPISODES_OUT = OUT / "edgar_cef_bdc_episodes.csv"
SUMMARY_OUT = OUT / "edgar_events_summary.json"

INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/master.gz"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
LOOKBACK_START = date(2008, 1, 1)   # indexes fetched from here
SCOPE_START = date(2010, 1, 1)      # the event table's stated scope (plan 0.7)
DAY = 86400

# ------------------------------------------------------------- the taxonomy

# Forms filed ONLY by closed-end funds or BDCs (module docstring).
MARKER_FORMS = frozenset({
    "N-2", "N-2/A", "N-2ASR", "N-2 POSASR", "N-2MEF",
    "N-14 8C", "N-14 8C/A",
    "N-54A", "N-54A/A", "N-54C", "N-54C/A", "N-6F", "N-6F/A",
    "N-23C-2", "N-23C-2/A", "N-23C3A", "N-23C3A/A", "N-23C3B", "N-23C3B/A", "N-23C3C", "N-23C3C/A",
})

# Event forms kept for funds in the set, by kind. The plan names SC TO-I/TO-C,
# N-14, 425, DEF/PRE 14A, 8-K, N-2/424B; the rest are added because each dates
# one of the same events: SC TO-T and SC 14D9 (a third-party tender and the
# fund's response), the merger and contest proxies, and N-8F (deregistration:
# the fund has ceased to exist, by merger or liquidation).
EVENT_KINDS = {
    "tender": ("SC TO-I", "SC TO-I/A", "SC TO-C", "SC TO-T", "SC TO-T/A",
               "SC 14D9", "SC 14D9/A", "SC14D9C"),
    "merger": ("425", "N-14", "N-14/A", "N-14 8C", "N-14 8C/A", "N-14MEF",
               "DEFM14A", "PREM14A", "DEFM14C", "PREM14C"),
    "vote": ("DEF 14A", "PRE 14A", "DEFA14A", "DEFR14A", "PRER14A"),
    "contest": ("DEFC14A", "PREC14A", "DFAN14A", "DEFN14A", "PREN14A"),
    "current": ("8-K", "8-K/A"),
    "offering": ("N-2", "N-2/A", "N-2ASR", "N-2 POSASR", "N-2MEF",
                 "424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8"),
    "dereg": ("N-8F", "N-8F/A", "N-8F NTC", "N-8F ORDR"),
}
FORM_KIND = {f: k for k, fs in EVENT_KINDS.items() for f in fs}
assert len(FORM_KIND) == sum(len(v) for v in EVENT_KINDS.values()), "a form is in two kinds"

# Episode grouping: filings of one kind for one fund belong to one episode if
# each follows the previous by at most this many days. A NAV tender runs from
# its announcement (often an SC TO-C) to the final SC TO-I/A that reports the
# result, usually inside two months; activist settlements can announce one a
# season ahead, so 120 days. A CEF merger runs from announcement to completion
# in four to twelve months, with filings throughout (425s, N-14 amendments,
# proxy supplements), so 180 days between consecutive filings. These are
# chosen from how the processes run, not fitted to any return.
EPISODE_GAP_DAYS = {"tender": 120, "merger": 180, "contest": 180}

_ACC_RE = re.compile(r"^edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})\.txt$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class IndexParseError(ValueError):
    pass


def accession_from_filename(fn: str) -> tuple[int, str]:
    """`edgar/data/1195739/0001193125-12-280520.txt` -> (1195739, '0001193125-12-280520')."""
    m = _ACC_RE.match(fn.strip())
    if not m:
        raise IndexParseError(f"not an EDGAR filing path: {fn!r}")
    return int(m.group(1)), m.group(2)


def parse_master_index(text: str, label: str = "", keep_forms=None) -> pd.DataFrame:
    """Parse a `master.idx` body into cik, company, form, date_filed, accession.

    The header ends at a line of dashes; every later non-blank line must have
    exactly five pipe-separated fields, a numeric CIK, an ISO date and a filing
    path whose CIK agrees with the first field. Anything else raises, naming
    `label` and the line number (a shifted column would otherwise put a date
    into the form field silently). `keep_forms`, if given, filters rows AFTER
    validation, so a malformed line is caught even in a form we do not keep.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("-----")) + 1
    except StopIteration:
        raise IndexParseError(f"{label}: no header separator line") from None
    if start < 2 or lines[start - 2].strip() != "CIK|Company Name|Form Type|Date Filed|Filename":
        raise IndexParseError(f"{label}: unexpected header {lines[start - 2] if start >= 2 else ''!r}")
    rows = []
    for n, line in enumerate(lines[start:], start=start + 1):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 5:
            raise IndexParseError(f"{label} line {n}: {len(parts)} fields, expected 5")
        cik_s, company, form, dfiled, fn = (p.strip() for p in parts)
        if not cik_s.isdigit() or not _DATE_RE.match(dfiled) or not form:
            raise IndexParseError(f"{label} line {n}: malformed CIK, form or date")
        cik_path, acc = accession_from_filename(fn)
        if cik_path != int(cik_s):
            raise IndexParseError(f"{label} line {n}: CIK {cik_s} != path CIK {cik_path}")
        if keep_forms is not None and form not in keep_forms:
            continue
        rows.append((int(cik_s), company, form, dfiled, acc))
    df = pd.DataFrame(rows, columns=["cik", "company", "form", "date_filed", "accession"])
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    return df


def quarters(start: date, end: date) -> list[tuple[int, int]]:
    """(year, quarter) from the quarter holding `start` to the one holding `end`."""
    if end < start:
        raise ValueError("end before start")
    out, y, q = [], start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def quarter_is_closed(y: int, q: int, today: date) -> bool:
    """A quarter's full index is final once the quarter has ended; a week's
    margin covers late dissemination. Until then it is re-fetched daily."""
    end_month = 3 * q
    first_after = date(y + 1, 1, 1) if end_month == 12 else date(y, end_month + 1, 1)
    return today >= first_after + timedelta(days=7)


# ------------------------------------------------------------------ episodes

def episodes(f: pd.DataFrame) -> pd.DataFrame:
    """Group one kind's filings per fund into dated episodes.

    `f` has cik, form, kind, date_filed, accession. For each (cik, kind) in
    EPISODE_GAP_DAYS, filings sorted by date start a new episode when the gap
    to the previous one exceeds the kind's limit. Dates extracted:

      first_date / first_form   the first filing: the earliest date the event
                                was public ON EDGAR. A press release can precede
                                it (CEFs need not file 8-Ks), so it is an UPPER
                                bound on the announcement, labelled as such;
      commence_date             tender only: the first SC TO-I or SC TO-T (the
                                offer is open from here);
      last_date                 the last filing in the episode. For a tender it
                                is normally the final amendment reporting the
                                result, filed after expiry: an upper bound on
                                the offer's end. For a merger it is the last
                                425 / N-14 amendment / proxy filing, NOT the
                                completion date (which the index cannot see);
      dereg_date                the fund's first N-8F filed after first_date
                                and within 730 days: the fund ceased to exist
                                (merged away or liquidated) by then.
    """
    need = {"cik", "form", "kind", "date_filed", "accession"}
    if not need <= set(f.columns):
        raise KeyError(f"episodes() needs {sorted(need)}; missing {sorted(need - set(f.columns))}")
    dereg = (f[f["kind"] == "dereg"].sort_values("date_filed").groupby("cik")["date_filed"].apply(list).to_dict())
    out = []
    for (cik, kind), g in f[f["kind"].isin(EPISODE_GAP_DAYS)].sort_values("date_filed").groupby(["cik", "kind"]):
        gap = pd.Timedelta(days=EPISODE_GAP_DAYS[kind])
        ep = (g["date_filed"].diff() > gap).cumsum()
        for k, e in g.groupby(ep):
            first = e.iloc[0]
            rec = {"cik": int(cik), "kind": kind, "episode": int(k), "first_date": first["date_filed"].date(),
                   "first_form": first["form"], "first_accession": first["accession"],
                   "last_date": e["date_filed"].max().date(), "n_filings": len(e),
                   "forms": ";".join(sorted(e["form"].unique()))}
            if kind == "tender":
                c = e[e["form"].isin(("SC TO-I", "SC TO-T"))]
                rec["commence_date"] = c["date_filed"].min().date() if len(c) else None
            d = [x for x in dereg.get(cik, []) if first["date_filed"] <= x <= first["date_filed"] + pd.Timedelta(days=730)]
            rec["dereg_date"] = d[0].date() if d else None
            out.append(rec)
    cols = ["cik", "kind", "episode", "first_date", "first_form", "first_accession", "commence_date",
            "last_date", "dereg_date", "n_filings", "forms"]
    return pd.DataFrame(out, columns=cols)


# ----------------------------------------------------------------- fetching

INSIDER_FORMS = frozenset({"3", "4"})
NCSR_FORMS = frozenset({"N-CSR"})


def fund_set(idx: pd.DataFrame) -> dict[int, str]:
    """CIK -> the rule that put it in the CEF/BDC set (module docstring).

    "marker_form" wins where both rules hold, because it is the stronger one.
    """
    marker = set(idx.loc[idx["form"].isin(MARKER_FORMS), "cik"])
    ncsr = set(idx.loc[idx["form"].isin(NCSR_FORMS), "cik"])
    insider = set(idx.loc[idx["form"].isin(INSIDER_FORMS), "cik"])
    out = {int(c): "marker_form" for c in marker}
    for c in (ncsr & insider) - marker:
        out[int(c)] = "ncsr_insider"
    return out


def fetch_indexes(client, start: date, end: date, today: date) -> tuple[pd.DataFrame, dict]:
    """Every quarter's master index from `start` to `end`, filtered to the forms we use.

    Returns (rows, counts): rows of the set-defining forms and the event forms
    for ALL filers (the fund set is decided afterwards), and per-quarter counts.
    """
    keep = MARKER_FORMS | INSIDER_FORMS | NCSR_FORMS | set(FORM_KIND)
    frames, counts = [], {}
    for y, q in quarters(start, end):
        url = INDEX_URL.format(y=y, q=q)
        text = client.get_text(url, max_age_s=None if quarter_is_closed(y, q, today) else DAY)
        df = parse_master_index(text, label=f"{y}Q{q}", keep_forms=keep)
        counts[f"{y}Q{q}"] = len(df)
        frames.append(df)
    return pd.concat(frames, ignore_index=True), counts


def sec_tickers(client) -> pd.DataFrame:
    """The SEC's CIK -> ticker/exchange table, as of today (one row per ticker)."""
    j = client.get_json(TICKERS_URL, max_age_s=DAY)
    if j.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ValueError(f"company_tickers_exchange.json fields changed: {j.get('fields')}")
    return pd.DataFrame(j["data"], columns=j["fields"])


def submissions(client, cik: int, max_age_s: float = 7 * DAY) -> pd.DataFrame:
    """A fund's complete filing list from the submissions API, older pages included.

    The `recent` block holds "at least one year's of filing or to 1,000 ... of
    the most recent filings" (EDGAR API page); `files` names further JSON pages
    for the rest, and every one is fetched: a history cut at 1,000 filings would
    drop exactly the old events a backtest needs, without an error.
    """
    j = client.get_json(SUBMISSIONS_URL.format(cik=cik), max_age_s=max_age_s)
    blocks = [j["filings"]["recent"]]
    for page in j["filings"].get("files", []):
        blocks.append(client.get_json(SUBMISSIONS_PAGE_URL.format(name=page["name"]), max_age_s=max_age_s))
    frames = []
    for b in blocks:
        n = len(b["accessionNumber"])
        if any(len(v) != n for v in b.values() if isinstance(v, list)):
            raise ValueError(f"CIK {cik}: ragged submissions block")
        frames.append(pd.DataFrame({k: v for k, v in b.items() if isinstance(v, list)}))
    s = pd.concat(frames, ignore_index=True).drop_duplicates("accessionNumber")
    s["filingDate"] = pd.to_datetime(s["filingDate"])
    s["cik"] = int(cik)
    s["entity_name"] = j.get("name")
    return s.sort_values("filingDate").reset_index(drop=True)


def build(client, today: date) -> dict:
    idx, qcounts = fetch_indexes(client, LOOKBACK_START, today, today)
    rule = fund_set(idx)
    funds = set(rule)
    ev = idx[idx["cik"].isin(funds) & idx["form"].isin(FORM_KIND)].copy()
    ev["kind"] = ev["form"].map(FORM_KIND)
    ev["set_rule"] = ev["cik"].map(rule)
    ev = ev.drop_duplicates(["cik", "accession", "form"])
    tk = sec_tickers(client)
    tk_by_cik = tk.groupby("cik").agg(ticker_now=("ticker", lambda v: ";".join(sorted(v))),
                                      exchange_now=("exchange", lambda v: ";".join(sorted(set(map(str, v))))))
    ev = ev.merge(tk_by_cik, left_on="cik", right_index=True, how="left")
    ev["in_scope"] = ev["date_filed"] >= pd.Timestamp(SCOPE_START)
    ev = ev.sort_values(["cik", "date_filed", "accession"]).reset_index(drop=True)

    # Marker-set recall against the funds we know are CEFs.
    uni = pd.read_csv(REPO / "data" / "cef" / "cef_universe.csv")["ticker"]
    t2c = dict(zip(tk["ticker"], tk["cik"]))
    missing_ticker = sorted(t for t in uni if t not in t2c)
    in_rule = {t: rule.get(int(t2c[t]), "not in set") for t in uni if t in t2c}

    ep = episodes(ev)
    ep = ep.merge(tk_by_cik, left_on="cik", right_index=True, how="left")
    names = ev.sort_values("date_filed").groupby("cik")["company"].last()
    ep["company_last"] = ep["cik"].map(names)
    ep["set_rule"] = ep["cik"].map(rule)

    scope = ev[ev["in_scope"]]
    rules = pd.Series(rule)
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "route": "EDGAR full-index master.gz per quarter + company_tickers_exchange.json",
        "index_quarters": [min(qcounts), max(qcounts)], "n_quarters": len(qcounts),
        "last_date_filed_seen": str(idx["date_filed"].max().date()),
        "fund_set": {"rules": {"marker_form": "filed any of MARKER_FORMS since " + str(LOOKBACK_START),
                               "ncsr_insider": "filed N-CSR and indexed on a Form 3 or 4 since "
                                               + str(LOOKBACK_START) + " (not marker_form)"},
                     "n_ciks": len(funds), "n_by_rule": rules.value_counts().to_dict(),
                     "n_with_ticker_now": int(ev.loc[ev["ticker_now"].notna(), "cik"].nunique()),
                     "universe44_without_sec_ticker": missing_ticker,
                     "universe44_by_rule": pd.Series(in_rule).value_counts().to_dict(),
                     "universe44_not_marker_form": sorted(t for t, r in in_rule.items() if r != "marker_form"),
                     "universe44_not_in_set": sorted(t for t, r in in_rule.items() if r == "not in set")},
        "filings_2010_on": {"rows": len(scope), "funds": int(scope["cik"].nunique()),
                            "funds_by_set_rule": scope.groupby("set_rule")["cik"].nunique().to_dict(),
                            "listed_funds_now": int(scope.loc[scope["ticker_now"].notna(), "cik"].nunique()),
                            "by_kind": scope["kind"].value_counts().to_dict(),
                            "by_form": scope["form"].value_counts().to_dict(),
                            "by_kind_year": {k: g["date_filed"].dt.year.value_counts().sort_index()
                                             .rename(index=str).to_dict()
                                             for k, g in scope.groupby("kind")}},
        "lookback_2008_09_rows": int((~ev["in_scope"]).sum()),
        "episodes_2010_on": {k: int(((ep["kind"] == k) & (pd.to_datetime(ep["first_date"]) >= pd.Timestamp(SCOPE_START))).sum())
                             for k in EPISODE_GAP_DAYS},
        # Most tender filings are non-traded interval funds' quarterly repurchase
        # offers; the funds with an exchange ticker today are the listed CEFs/BDCs
        # (a fund that has since died has no ticker, so this undercounts them).
        "episodes_2010_on_funds_listed_now": {
            k: int(((ep["kind"] == k) & ep["ticker_now"].notna()
                    & (pd.to_datetime(ep["first_date"]) >= pd.Timestamp(SCOPE_START))).sum())
            for k in EPISODE_GAP_DAYS},
        "fetch": {"requests": client.n_requests, "cache_hits": client.n_cache_hits,
                  "min_interval_s": client._limiter.min_interval},
    }
    return {"filings": ev, "episodes": ep, "summary": summary}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="read the cache only; no network")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (for a reproducible rebuild)")
    a = ap.parse_args(argv)
    from scripts.data.edgar_client import EdgarClient
    client = EdgarClient(offline=a.offline)
    today = date.fromisoformat(a.today) if a.today else date.today()
    res = build(client, today)
    OUT.mkdir(parents=True, exist_ok=True)
    f = res["filings"].copy()
    f["date_filed"] = f["date_filed"].dt.date
    f.to_csv(FILINGS_OUT, index=False, compression="gzip")
    res["episodes"].to_csv(EPISODES_OUT, index=False)
    SUMMARY_OUT.write_text(json.dumps(res["summary"], indent=1, default=str))
    s = res["summary"]
    print(json.dumps({k: s[k] for k in ("index_quarters", "last_date_filed_seen", "fund_set", "episodes_2010_on", "fetch")},
                     indent=1, default=str))
    print(f"filings 2010+: {s['filings_2010_on']['rows']} rows, {s['filings_2010_on']['funds']} funds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
