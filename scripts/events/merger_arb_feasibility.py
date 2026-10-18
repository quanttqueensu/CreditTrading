"""Equity merger arbitrage for this desk: the deal flow, the short leg, the reading problem. ZERO TRIALS.

    export QUANTT_ENV_FILE=/abs/path/config/.env   # SEC_USER_AGENT, R2, Alpaca cef key; never printed
    python3 scripts/events/merger_arb_feasibility.py              # EDGAR, CRSP (R2), Alpaca GETs, IBKR file
    python3 scripts/events/merger_arb_feasibility.py --offline    # the same tables from the caches only

WHY THIS EXISTS
---------------
Special-situations sprint, job 5 of 6 (team lead, 2026-10-15): is equity merger
arbitrage feasible for this desk at all, before anyone spends a trial on it?
The note is `results/events/MERGER_ARB_AND_IBKR_2026-10-15.md`. This script
produces every number in its part A. It computes NO RETURN of any kind: no
spread, no realised P&L, no price change. A realised spread is a trial (EVENTS
counter), and this job is feasibility only. What it does compute:

  1. DEAL COUNTS 2010-2026 from EDGAR, by year, cash / stock / mixed.
  2. A SECOND METHOD for 2010-2024: CRSP merger delistings by code (R2 mirror,
     `dsedelist`, which ends 2024-12-31), and a deal-level match of the two.
  3. TODAY's pending stock deals and whether the acquirer can be shorted:
     Alpaca asset flags (read-only `GET /v2/assets/{symbol}`) and IBKR's public
     shortstock file (the file `scripts/cef/real_money_costs.py` reads).
  4. The IBKR file's fee and availability for the CEF names (part B).
  5. Liquidity of today's pending deals (Alpaca daily bars, volume x close):
     a capacity count, not a return.
  6. The DEAL-TERM READING PROBLEM on a declared sample of 20 recent deals:
     what a machine reader extracts from the announcement 8-K against a
     reading of the same document (`merger_arb_readings.py`, quotes verified
     against the fetched filing on every run). The rule (10 most recent cash,
     10 most recent stock-involved, 2026 announcements whose document is the
     target's 8-K 1.01) was written before any reading, applied once on
     2026-10-18 and its 20 accessions frozen (`SAMPLE_ACCESSIONS`, committed
     before READINGS was filled). Each reading also says whether the document
     is a TARGET's deal at all: 4 of the 10 cash-class picks were not.
  7. SC 13E3 (Rule 13e-3 going-private) accessions by year and the in-scope
     deals whose target is on one: the controller / affiliate freeze-out
     sub-case (counts only).
  8. CAPACITY: how many pending deals absorb a position of $10k-$500k at the
     desk's 5% participation guard, by class, with the acquirer's borrow.

HISTORY: begun 2026-10-15 by a session that hit its usage limit; resumed and
finished 2026-10-18. The resume replaced the pending-deal role rule (425
header subject -> registration, see PENDING TODAY), added the SPAC-name and
split-off exclusions, the 13E-3 and capacity tables, and the readings.

HOW A DEAL IS FOUND IN EDGAR (the rules are stated once, here)
---------------------------------------------------------------
EDGAR's quarterly full index (`fetch_edgar_events.parse_master_index`) lists a
filing under EVERY party (filer and subject company), with no role. So:

* TARGETS are the filers of target-only forms: DEFM14A / PREM14A (merger proxy;
  the company whose holders vote), DEFM14C / PREM14C (merger information
  statement), SC 14D9 and SC14D9C (the subject company's response to a
  third-party tender offer). These are the ANCHORS. A target's anchors split
  into separate deals where consecutive anchors are more than
  `EPISODE_GAP_DAYS` (365) apart: one transaction's proxy, supplements and
  14D-9 amendments come within months; a gap of a year is a new transaction.
* The DEAL DATE `d0` walks back from the first anchor through the target's
  deal-form filings (425, SC TO-T, SC TO-C, SC14D9C, PREM14A ...) while
  consecutive gaps are at most `CHAIN_GAP_DAYS` (120; the repo's tender
  episode gap, `fetch_edgar_events.EPISODE_GAP_DAYS`) and no more than
  `LOOKBACK_DAYS` (365) before the anchor. 8-K item 1.01 (entry into a material
  definitive agreement) is then read from the target's submissions JSON and,
  where one is found in [d0-30d, d0+10d], it is the announcement document.
* STOCK-INVOLVED: Rule 425 covers communications in a business combination
  that offers REGISTERED securities, so a deal is stock-involved when any 425
  lists the target in its window. This is structural and ignores the text.
* STOCK vs MIXED (and a check on the 425 rule): `classify_consideration` reads
  the announcement 8-K's body (falling back to the target's first 425, then its
  SC 14D9) and finds the per-share consideration. The rule is declared here,
  before any comparison; it is then scored against CRSP's codes and against
  the 20 readings, never tuned to them.
* JOINT PROXIES: in a stock deal both parties can file a DEFM14A. Anchored
  episodes linked through a shared 425 or SC TO-T accession with overlapping
  windows are ONE deal (union-find). Within a merged deal the target is the
  member that did not register shares (no S-4/F-4 in the window); failing
  that, the member delisted within `COMPLETE_DAYS`; failing that, the deal is
  kept once and flagged `target_ambiguous`.
* EXCLUDED, each counted: closed-end funds and BDCs (any filer of a 1940-Act
  form in `FUND_FORMS`; they have their own work, `G1A_SHORTABILITY`), blank
  checks (SIC 6770 from the submissions JSON, or a SPAC name at the anchor,
  `SPAC_NAME_RE`: a de-SPAC proxy's "target" is the SPAC), and targets never
  listed (below). A target that itself registered shares in the window is
  kept but flagged `target_registered` (a holdco reorganisation, a reverse
  merger, or the issuer side of a joint proxy that no 425 links).
* LISTED: the target has a Form 25-NSE or 25 (removal from listing) filed on
  or after d0, or is listed today in the SEC ticker file on NYSE, Nasdaq,
  Cboe or TXSE (the file's own exchange labels; 'OTC' and blank do not count). A target that was OTC at the deal and listed later would pass wrongly;
  stated, not measured.
* COMPLETED: a 25/25-NSE within `COMPLETE_DAYS` (730, two years) of the last
  anchor. Two years, not 18 months: Activision Blizzard's vote (DEFM14A
  2022-03-21) preceded its 25-NSE (2023-10-13) by 19 months of antitrust
  review, and an 18-month bound filed it as 'not completed'. Not completed means failed, pending, OR a transaction the company
  survives (an asset sale or a reverse merger also files DEFM14A). That bucket
  is a mixture and is reported as one.

PENDING TODAY
-------------
A deal is a pending candidate if it is not completed, its d0 is within
`PENDING_DAYS` (548) of the index's last date, the target is listed today
(SEC ticker file) and active at Alpaca, and no 8-K item 1.02 (termination of a
material definitive agreement) whose body mentions a merger agreement was filed
by the target after d0. Recently announced STOCK deals often have no anchor yet
(the joint proxy sits inside the acquirer's S-4), so the 425 filings of the last
`PENDING_DAYS` whose parties are in no anchored deal are grouped into
components (CIKs sharing a 425 accession) and given roles by REGISTRATION,
never by the 425 header's "subject company": an acquirer in a stock deal
registers the shares it issues (S-4 / F-4), a target does not. (2026-10-18: the
header rule this replaced named the subject company the target, and 75 of its
113 "targets" were registrants -- PNC, Amazon, Palo Alto Networks -- because an
issuer often names ITSELF the subject of its own 425.)
* A component of two or more CIKs with exactly one registrant: that member is
  the acquirer and the one other (listed) member the target. Any other pattern
  is `unresolved`, with its reason, and counted.
* A component of one CIK (every 425 names only the filer): an
  `acquirer_only` if it registered shares, else a `target_only`. A
  target_only is paired with the one acquirer_only whose first 425 is within
  `PAIR_TOL_DAYS` of its own AND whose name appears in the target's
  announcement document; the same match fills in an anchored stock deal that
  has no co-listed acquirer. Zero or two candidates leave it unresolved.
* The acquirer leg's borrow is also measured on every listed acquirer with a
  425 in the last `LIVE_425_DAYS` (a live or just-closed stock deal), paired or
  not: shortability is a property of the acquirer, not of the pairing.

READ-ONLY, AND WHAT IS CALLED
-----------------------------
* EDGAR, only through `scripts/data/edgar_client.py` (rate limit, contact,
  cache): quarterly indexes, the ticker file, submissions JSONs, filing
  headers (`-index-headers.html`) and primary documents.
* R2 (CRSP mirror): `dsedelist` and `dsenames` only. No price or return table.
* Alpaca, paper endpoint, cef key: `GET /v2/assets/{symbol}` and
  `GET /v2/stocks/bars`. No order path is reachable from this module.
* `https://www.interactivebrokers.com/shortstock/usa.txt`, once per run.
Every response is cached under `results/events/_cache_marb/` (gitignored by
`results/**/_cache_*`) or the EDGAR client's cache, and is true on its date
only (CLAUDE.md landmine 5 for borrow flags).

NO SILENT FALLBACKS. A form or file that will not parse raises. A reading whose
quote is not in the fetched document raises. An unclassifiable consideration is
counted as `unclassified`, never assigned a class.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

from scripts.events.conditional_tender_census import normalise, plain, quote_in  # noqa: E402 (stdlib + pandas)

OUT = REPO / "results" / "events" / "merger_arb"
CACHE = REPO / "results" / "events" / "_cache_marb"

INDEX_FROM = date(2009, 7, 1)          # look-back for 2010 deals (LOOKBACK_DAYS before the first anchor)
COUNT_FROM_YEAR = 2010
ANCHOR_FORMS = ("DEFM14A", "DEFM14C", "PREM14A", "PREM14C", "SC 14D9", "SC14D9C")
TENDER_ANCHORS = ("SC 14D9", "SC14D9C")
CHAIN_FORMS = ANCHOR_FORMS + ("425", "SC TO-T", "SC TO-C")
REG_FORMS = ("S-4", "F-4", "S-4EF")
DELIST_FORMS = ("25-NSE", "25")
FREEZE_FORMS = ("SC 13E3",)            # Rule 13e-3 going-private statement (initial filing only)
SPLITOFF_FORMS = ("SC TO-I",)          # an issuer tender offer: in a 425 component, a split-off exchange offer
FUND_FORMS = frozenset({"N-2", "N-2/A", "N-CSR", "N-CSRS", "NPORT-P", "N-14 8C", "N-14 8C/A", "N-54A",
                        "N-1A", "485BPOS", "N-8F"})
INDEX_FORMS = frozenset(set(CHAIN_FORMS) | set(REG_FORMS) | set(DELIST_FORMS) | set(FREEZE_FORMS)
                        | set(SPLITOFF_FORMS) | FUND_FORMS)

EPISODE_GAP_DAYS = 365
CHAIN_GAP_DAYS = 120
LOOKBACK_DAYS = 365
TAIL_DAYS = 30
COMPLETE_DAYS = 730
PENDING_DAYS = 548
SPAC_SIC = 6770
# A blank check whose CURRENT SIC is no longer 6770 (the de-SPACed company keeps the CIK and takes the
# target's SIC) is caught by the name it filed the proxy under. Measured 2026-10-18: 125 in-scope deals
# matched this, all of them visibly SPACs in a 25-name read ("Opes Acquisition Corp.", "CF Acquisition
# Corp. VIII", "FG Merger II Corp."). An operating company named "... Acquisition Corp" would be
# dropped wrongly; stated, not measured.
SPAC_NAME_RE = re.compile(r"\bACQUISITION\s+(?:CORP|CORPORATION|CO|COMPANY|INC|LTD|LIMITED|HOLDINGS)\b"
                          r"|\bMERGER\s+(?:[IVX]+\s+)?CORP\b", re.I)
LISTED_EXCHANGES = frozenset({"NYSE", "Nasdaq", "CBOE", "TXSE"})
ANNOUNCE_WINDOW = (-30, 10)             # 8-K 1.01 relative to d0, days
PAIR_TOL_DAYS = 3                       # a target's and an acquirer's first 425: the same announcement, +-3 days
LIVE_425_DAYS = 120                     # an acquirer with a 425 this recent is in a live (or just-closed) deal
STALE_DAYS = 180                        # pending pairs with no 425 by either party for this long are flagged
ADV_SESSIONS = 63                       # one quarter of sessions, as `real_money_costs.RECENT`
# Capacity (part A): a position of POSITION_USD per deal against PARTICIPATION of the
# median daily dollar volume. 5% is the cost model's own participation guard
# (`scripts/cef/plan_diagnostics.py`, `adv`); it is the desk's convention, not a
# measured impact threshold for merger targets.
PARTICIPATION = 0.05
POSITION_USD = (10_000, 25_000, 50_000, 100_000, 250_000, 500_000)
STOCK_CLASSES = ("stock", "mixed", "stock_involved_unsplit", "conflict_stock_cash")

IBKR_URL = "https://www.interactivebrokers.com/shortstock/usa.txt"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
HEADER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{acc}-index-headers.html"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{doc}"
DAY = 86400


# =============================================================== episodes and deals

def _days(a, b) -> float:
    return (pd.Timestamp(b) - pd.Timestamp(a)) / pd.Timedelta(days=1)


def split_episodes(dates, gap_days: int = EPISODE_GAP_DAYS) -> list[list[pd.Timestamp]]:
    """Sorted anchor dates -> runs whose consecutive gaps are <= gap_days."""
    ds = sorted(pd.Timestamp(d) for d in dates)
    if not ds:
        return []
    out, cur = [], [ds[0]]
    for d in ds[1:]:
        if _days(cur[-1], d) > gap_days:
            out.append(cur)
            cur = [d]
        else:
            cur.append(d)
    out.append(cur)
    return out


def chain_start(anchor0: pd.Timestamp, deal_dates, gap_days: int = CHAIN_GAP_DAYS,
                lookback_days: int = LOOKBACK_DAYS) -> pd.Timestamp:
    """Walk back from the first anchor through deal-form dates while each gap <= gap_days.

    Only dates in [anchor0 - lookback_days, anchor0] are eligible. A 425 the
    company filed as an ACQUIRER in an unrelated deal ten months earlier is
    excluded by the chain gap, not by luck.
    """
    lo = anchor0 - pd.Timedelta(days=lookback_days)
    prior = sorted((pd.Timestamp(d) for d in deal_dates if lo <= pd.Timestamp(d) <= anchor0), reverse=True)
    start = anchor0
    for d in prior:
        if _days(d, start) <= gap_days:
            start = min(start, d)
        else:
            break
    return start


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def build_episodes(idx: pd.DataFrame, funds: set) -> pd.DataFrame:
    """One row per (target CIK, anchor run). Funds are excluded here and counted by the caller."""
    a = idx[idx["form"].isin(ANCHOR_FORMS) & ~idx["cik"].isin(funds)]
    chain = idx[idx["form"].isin(CHAIN_FORMS)].groupby("cik")["date_filed"].apply(list).to_dict()
    rows = []
    for cik, g in a.groupby("cik"):
        for run in split_episodes(g["date_filed"]):
            a0, a1 = run[0], run[-1]
            d0 = chain_start(a0, chain.get(cik, []))
            forms = set(g.loc[(g["date_filed"] >= a0) & (g["date_filed"] <= a1), "form"])
            rows.append({"cik": int(cik), "name": g["company"].iloc[-1], "d0": d0, "a0": a0, "a1": a1,
                         "n_anchor": len(run), "tender": bool(forms & set(TENDER_ANCHORS)),
                         "anchor_forms": "|".join(sorted(forms))})
    return pd.DataFrame(rows)


def colisted(idx: pd.DataFrame, forms=("425", "SC TO-T")) -> dict[int, list[tuple[pd.Timestamp, int, str]]]:
    """CIK -> [(date, other CIK, form)] for every accession of `forms` that lists both."""
    x = idx[idx["form"].isin(forms)]
    out: dict[int, list] = defaultdict(list)
    for acc, g in x.groupby("accession"):
        ciks = sorted(set(int(c) for c in g["cik"]))
        if len(ciks) < 2:
            continue
        d, f = g["date_filed"].iloc[0], g["form"].iloc[0]
        for c in ciks:
            for o in ciks:
                if o != c:
                    out[c].append((d, o, f))
    return out


def window(ep) -> tuple[pd.Timestamp, pd.Timestamp]:
    return ep["d0"], ep["a1"] + pd.Timedelta(days=TAIL_DAYS)


def link_deals(eps: pd.DataFrame, co: dict) -> pd.Series:
    """Deal id per episode: episodes joined by a shared 425/SC TO-T accession with overlapping windows."""
    uf = UnionFind()
    by_cik = defaultdict(list)
    for i, e in eps.iterrows():
        by_cik[e["cik"]].append(i)
        uf.find(i)
    for i, e in eps.iterrows():
        lo, hi = window(e)
        for d, other, _f in co.get(e["cik"], []):
            if not (lo <= d <= hi):
                continue
            for j in by_cik.get(other, []):
                lo2, hi2 = window(eps.loc[j])
                if lo2 <= hi and lo <= hi2:
                    uf.union(i, j)
    return pd.Series({i: uf.find(i) for i in eps.index})


# =============================================================== consideration reader

_NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
CASH_RE = re.compile(
    r"\$\s?(?:" + _NUM + r")(?:\s+per\s+share)?(?:,)?(?:\s+net\s+to\s+the\s+(?:seller|holder)s?)?"
    r"(?:\s+thereof)?\s*,?\s+in\s+cash"
    r"|\$\s?(?:" + _NUM + r")\s+(?:in\s+)?cash(?:\s+per\s+share)?"
    r"|an\s+amount\s+in\s+cash\s+equal\s+to\s+\$"
    r"|cash\s+consideration\s+of\s+\$"
    r"|\$\s?(?:" + _NUM + r")\s+per\s+share\s+in\s+cash", re.I)
STOCK_RE = re.compile(
    r"\b(?:" + _NUM + r")\s+(?:of\s+a\s+)?(?:(?:validly\s+issued,?\s+)?fully\s+paid\s+and\s+non-?assessable\s+)?"
    r"(?:ordinary\s+|common\s+)?shares?\s+of\b"
    r"|\bexchange\s+ratio\b"
    r"|\bshares?\s+of\s+(?:parent|acquir\w*|buyer)\s+(?:class\s+\w+\s+)?(?:common|ordinary)\s+stock\b", re.I)
LIEU_RE = re.compile(r"cash\s+(?:payment\s+)?in\s+lieu\s+of\s+(?:any\s+)?fractional", re.I)
ELECTION_RE = re.compile(r"\belect(?:ion|s)?\s+to\s+receive\b|\bcash\s+election\b|\bstock\s+election\b"
                         r"|\bsubject\s+to\s+proration\b", re.I)
RECEIVE_RE = re.compile(r"(?:converted\s+into\s+the\s+right\s+to\s+receive|entitled\s+to\s+receive"
                        r"|will\s+receive|shall\s+receive|right\s+to\s+receive|offer\s+price"
                        r"|per\s+share\s+consideration|merger\s+consideration\s+(?:of|is|will|equal))", re.I)
CONTEXT_CHARS = 700


def consideration_windows(text: str, n: int = 3) -> list[str]:
    """The first `n` stretches of text around a 'right to receive' phrase (plain text in)."""
    out = []
    for m in RECEIVE_RE.finditer(text):
        s = text[max(0, m.start() - 150): m.end() + CONTEXT_CHARS]
        if out and m.start() - 150 < out[-1][1]:
            continue
        out.append((s, m.end() + CONTEXT_CHARS))
        if len(out) >= n:
            break
    return [s for s, _ in out]


def classify_consideration(text: str) -> dict:
    """cash / stock / mixed / unclassified from the consideration language. Declared before any scoring.

    Cash in lieu of fractional shares is struck out first: every stock deal
    says it, and it is not a cash component. An election between cash and
    stock is mixed (the holder base receives both after proration).
    """
    wins = consideration_windows(text)
    if not wins:
        return {"class": "unclassified", "why": "no consideration phrase", "snippet": ""}
    joined = " ".join(LIEU_RE.sub(" ", w) for w in wins)
    cash = bool(CASH_RE.search(joined))
    stock = bool(STOCK_RE.search(joined))
    elect = bool(ELECTION_RE.search(joined)) and cash and stock
    cls = "mixed" if (cash and stock) or elect else "cash" if cash else "stock" if stock else "unclassified"
    return {"class": cls, "why": f"cash={cash} stock={stock} election={elect}", "snippet": wins[0][:400]}


# =============================================================== header parser

_HDR_BLOCK = re.compile(r"<(SUBJECT-COMPANY|FILED-BY)>(.*?)</\1>", re.S)
_HDR_FIELD = {k: re.compile(rf"<{k}>([^\n<]*)") for k in ("CONFORMED-NAME", "CIK", "ASSIGNED-SIC", "FILE-NUMBER")}


def parse_header(text: str) -> dict:
    """An `-index-headers.html` page -> {'subject': [...], 'filed_by': [...], 'type': ...}.

    Raises if the SGML header is absent (a moved or throttled page would
    otherwise read as 'no parties').
    """
    if "<SEC-HEADER>" not in text:
        raise ValueError("no <SEC-HEADER> in the header page")
    m = re.search(r"<TYPE>([^\n<]*)", text)
    out = {"type": m.group(1).strip() if m else None, "subject": [], "filed_by": []}
    for role, body in _HDR_BLOCK.findall(text):
        rec = {}
        for k, rx in _HDR_FIELD.items():
            mm = rx.search(body)
            rec[k.lower().replace("-", "_")] = mm.group(1).strip() if mm else None
        if rec["cik"] is None:
            raise ValueError(f"{role} block without a CIK")
        rec["cik"] = int(rec["cik"])
        rec["assigned_sic"] = int(rec["assigned_sic"]) if rec["assigned_sic"] else None
        out["subject" if role == "SUBJECT-COMPANY" else "filed_by"].append(rec)
    return out


# =============================================================== deal-term reader (sample)

OUTSIDE_RE = re.compile(r"(?:outside\s+date|end\s+date|termination\s+date)[^.]{0,200}?"
                        r"((?:january|february|march|april|may|june|july|august|september|october|november|december)"
                        r"\s+\d{1,2},\s+20\d\d)", re.I)
COLLAR_RE = re.compile(r"\bcollar\b|\bvolume[- ]weighted\s+average\b[^.]{0,300}\b(?:greater|less)\s+than\b", re.I)
CVR_RE = re.compile(r"contingent\s+value\s+right", re.I)
HSR_RE = re.compile(r"Hart-Scott-Rodino|\bHSR\s+Act\b", re.I)
REG_RE = re.compile(r"\bCFIUS\b|\bFederal\s+Reserve\b|\bFCC\b|\bFERC\b|\bState\s+Department\b|\bEuropean\s+Commission\b"
                    r"|\bOCC\b|\bFDIC\b|\bNRC\b|foreign\s+(?:antitrust|investment)|\bSAMR\b|\bCMA\b", re.I)
FIN_RE = re.compile(r"not\s+(?:subject\s+to|conditioned\s+(?:up)?on)\s+(?:a|any)\s+financing\s+condition"
                    r"|no\s+financing\s+condition", re.I)
VOTE_RE = re.compile(r"(?:approval|adoption)\s+of\s+the\s+merger\s+agreement\s+by[^.]{0,80}(?:stockholders|shareholders)"
                     r"|stockholder\s+approval|shareholder\s+approval|requisite\s+(?:company\s+)?(?:stockholder|shareholder)", re.I)
FEE_RE = re.compile(r"termination\s+fee\s+(?:of|equal\s+to)\s+(?:approximately\s+)?\$\s?(" + _NUM + r")\s*(million|billion)?",
                    re.I)
RATIO_RE = re.compile(r"\b(\d+\.\d{2,6})\s+(?:of\s+a\s+)?(?:(?:validly\s+issued,?\s+)?fully\s+paid\s+and\s+non-?assessable\s+)?"
                      r"(?:ordinary\s+|common\s+)?shares?\s+of\b", re.I)
PRICE_RE = re.compile(r"\$\s?(" + _NUM + r")(?:\s+per\s+share)?(?:,)?(?:\s+net\s+to\s+the\s+(?:seller|holder)s?)?\s*,?\s+in\s+cash",
                      re.I)


def machine_terms(text: str) -> dict:
    """What a regex reader pulls from one announcement document (plain text in).

    This is the 'machine' column of the reading-problem table. Each field is
    the first match or None; nothing is inferred.
    """
    def first(rx, grp=0):
        m = rx.search(text)
        return (m.group(grp) if m else None)
    fee = FEE_RE.search(text)
    return {
        "m_cash_per_share": first(PRICE_RE, 1),
        "m_ratio": first(RATIO_RE, 1),
        "m_outside_date": first(OUTSIDE_RE, 1),
        "m_collar": bool(COLLAR_RE.search(text)),
        "m_cvr": bool(CVR_RE.search(text)),
        "m_hsr": bool(HSR_RE.search(text)),
        "m_other_reg": sorted(set(x.upper() for x in REG_RE.findall(text))),
        "m_no_financing_condition": bool(FIN_RE.search(text)),
        "m_vote": bool(VOTE_RE.search(text)),
        "m_termination_fee": (fee.group(1) + (" " + fee.group(2) if fee.group(2) else "")) if fee else None,
        "m_class": classify_consideration(text)["class"],
    }


# =============================================================== fetchers (network, cached)

def _age(offline: bool, seconds):
    """max_age for the EDGAR client: None (use any cached copy) when offline."""
    return None if offline else seconds


def edgar(offline: bool):
    from scripts.data.edgar_client import EdgarClient
    return EdgarClient(offline=offline)


def load_index(client, today: date, offline: bool) -> pd.DataFrame:
    """Every quarter's master index from INDEX_FROM, filtered to INDEX_FORMS (cached per run date)."""
    from scripts.data.fetch_edgar_events import (DAY as _D, INDEX_URL, parse_master_index, quarter_is_closed,
                                                 quarters)
    p = CACHE / f"index_{today}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    if offline:
        raise FileNotFoundError(f"offline and no cached {p.name}")
    frames = []
    for y, q in quarters(INDEX_FROM, today):
        t = client.get_text(INDEX_URL.format(y=y, q=q), max_age_s=None if quarter_is_closed(y, q, today) else _D)
        frames.append(parse_master_index(t, label=f"{y}Q{q}", keep_forms=INDEX_FORMS))
    idx = pd.concat(frames, ignore_index=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    idx.to_parquet(p)
    return idx


def sec_tickers(client, today: date, offline: bool) -> pd.DataFrame:
    p = CACHE / f"sec_tickers_{today}.json"
    if not p.exists():
        if offline:
            raise FileNotFoundError(f"offline and no cached {p.name}")
        j = client.get_json(TICKERS_URL, max_age_s=DAY)
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(j))
    j = json.loads(p.read_text())
    if j.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ValueError(f"company_tickers_exchange.json fields changed: {j.get('fields')}")
    return pd.DataFrame(j["data"], columns=j["fields"])


def submissions(client, cik: int, lo: pd.Timestamp, hi: pd.Timestamp, offline: bool,
                max_age_days: float = 30) -> dict:
    """SIC, current tickers/exchanges and the filings that overlap [lo, hi] for one CIK.

    The `recent` block plus only the older JSON pages whose filingFrom..filingTo
    span overlaps the window (EDGAR API page: `files` names the older pages).
    `max_age_days` is 30 for history (a completed deal's filings do not
    change) and 1 for a deal that may be pending today, whose termination
    8-K could be days old.
    """
    j = client.get_json(SUBMISSIONS_URL.format(cik=cik), max_age_s=_age(offline, max_age_days * DAY))
    blocks = [j["filings"]["recent"]]
    for page in j["filings"].get("files", []):
        f0, f1 = pd.Timestamp(page["filingFrom"]), pd.Timestamp(page["filingTo"])
        if f1 >= lo and f0 <= hi:
            blocks.append(client.get_json(SUBMISSIONS_PAGE_URL.format(name=page["name"]), max_age_s=None))
    frames = []
    for b in blocks:
        n = len(b["accessionNumber"])
        keep = {k: b[k] for k in ("accessionNumber", "filingDate", "form", "items", "primaryDocument") if k in b}
        if any(len(v) != n for v in keep.values()):
            raise ValueError(f"CIK {cik}: ragged submissions block")
        frames.append(pd.DataFrame(keep))
    s = pd.concat(frames, ignore_index=True).drop_duplicates("accessionNumber")
    s["filingDate"] = pd.to_datetime(s["filingDate"])
    sic = j.get("sic")
    return {"cik": int(cik), "name": j.get("name"), "sic": int(sic) if sic not in (None, "") else None,
            "tickers": j.get("tickers") or [], "exchanges": j.get("exchanges") or [],
            "filings": s.sort_values("filingDate").reset_index(drop=True)}


def fetch_doc(client, cik: int, acc: str, doc: str) -> str:
    if not doc or "/" in doc or ".." in doc:
        raise ValueError(f"bad primary document name {doc!r} for {acc}")
    url = DOC_URL.format(cik=int(cik), acc_nd=acc.replace("-", ""), doc=doc)
    return client.get_text(url, max_age_s=None, encoding="latin-1")


def fetch_header(client, cik: int, acc: str) -> dict:
    url = HEADER_URL.format(cik=int(cik), acc_nd=acc.replace("-", ""), acc=acc)
    return parse_header(client.get_text(url, max_age_s=None))


def crsp_delistings(offline: bool) -> pd.DataFrame:
    """CRSP merger delistings (dlstcd 200-299) from 2010, with the name record in force at delisting.

    `dsedelist` and `dsenames` only: no price or return is read, so the
    2023-01-01 time holdout is not touched (counts only).
    """
    p = CACHE / "crsp_merger_delistings.parquet"
    if p.exists():
        return pd.read_parquet(p)
    if offline:
        raise FileNotFoundError(f"offline and no cached {p.name}")
    from src.data.r2 import connect, q, r2_path
    dl, nm = r2_path("crsp_a_stock", "dsedelist"), r2_path("crsp_a_stock", "dsenames")
    sql = (f"SELECT d.permno, d.dlstdt, d.dlstcd, d.nwperm, n.shrcd, n.exchcd, n.comnam, n.ticker, n.siccd "
           f"FROM read_parquet('{dl}') d LEFT JOIN read_parquet('{nm}') n "
           f"ON n.permno = d.permno AND d.dlstdt BETWEEN n.namedt AND n.nameendt "
           f"WHERE d.dlstdt >= DATE '2010-01-01' AND d.dlstcd BETWEEN 200 AND 299")
    df = q(connect(), sql)
    df["dlstdt"] = pd.to_datetime(df["dlstdt"])
    if df.duplicated("permno").any():
        raise ValueError("a permno has two merger delistings or two name records at its delisting date")
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p)
    return df


def ibkr_file(today: date, offline: bool) -> tuple[pd.DataFrame, str]:
    from scripts.events.g1a_shortability import parse_ibkr_shortstock, _http_get
    p = CACHE / f"ibkr_usa_{today}.txt"
    if not p.exists():
        if offline:
            raise FileNotFoundError(f"offline and no cached {p.name}")
        code, body = _http_get(IBKR_URL)
        if code != 200:
            raise RuntimeError(f"GET {IBKR_URL} -> HTTP {code}")
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return parse_ibkr_shortstock(p.read_text(encoding="utf-8", errors="replace"))


def alpaca_symbol(sec_ticker: str) -> str | None:
    """The SEC ticker file's symbol as Alpaca writes it ('BRK-B' -> 'BRK.B'), or None if Alpaca's
    equity-symbol pattern (`quantt.broker.alpaca._SYMBOL_RE`) cannot hold it. None is recorded as
    'not queryable', never guessed into another symbol."""
    from quantt.broker.alpaca import _SYMBOL_RE
    s = sec_ticker.replace("-", ".")
    return s if _SYMBOL_RE.match(s) else None


def alpaca_assets(symbols, today: date, offline: bool) -> pd.DataFrame:
    """GET /v2/assets/{symbol} (read-only), cached as one JSON per day; read time kept per symbol."""
    p = CACHE / f"alpaca_assets_{today}.json"
    have = json.loads(p.read_text()) if p.exists() else {}
    want = sorted(set(symbols) - set(have))
    if want:
        if offline:
            raise FileNotFoundError(f"offline and {len(want)} symbols not in {p.name}: {want[:10]}")
        from quantt.broker.alpaca import AlpacaClient, AssetNotFound
        client = AlpacaClient.from_environment("cef")
        for s in want:
            t = datetime.now(timezone.utc).isoformat(timespec="seconds")
            alp = alpaca_symbol(s)
            if alp is None:
                have[s] = {"read_utc": t, "found": False, "why": "not an Alpaca equity symbol"}
                continue
            try:
                a = client.asset(alp)
                have[s] = {"read_utc": t, "found": True, **{k: a.get(k) for k in (
                    "name", "status", "exchange", "tradable", "shortable", "easy_to_borrow", "borrow_status")}}
            except AssetNotFound:
                have[s] = {"read_utc": t, "found": False}
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(have, indent=1, sort_keys=True))
    return pd.DataFrame([{"symbol": s, **have[s]} for s in sorted(set(symbols))])


def alpaca_adv(symbols, end: date, offline: bool) -> pd.DataFrame:
    """Median daily dollar volume (close x volume) over the last ADV_SESSIONS sessions to `end`.

    One request per symbol, so a symbol with no bars is recorded as such
    (n_sessions 0, adv None) rather than failing the batch or being filled.
    """
    p = CACHE / f"alpaca_bars_{end}.parquet"
    have = pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=["date", "ticker", "close", "volume"])
    want = sorted(set(symbols) - set(have["ticker"]))
    nob = CACHE / f"alpaca_nobars_{end}.json"
    none = set(json.loads(nob.read_text())) if nob.exists() else set()
    want = [s for s in want if s not in none]
    if want:
        if offline:
            raise FileNotFoundError(f"offline and {len(want)} symbols lack cached bars: {want[:10]}")
        from scripts.rv.alpaca_daily import AlpacaLegError, fetch_bars, make_client
        client = make_client()
        frames = [have]
        for s in want:
            alp = alpaca_symbol(s)
            if alp is None:
                none.add(s)
                continue
            try:
                b = fetch_bars(client, [alp], end - timedelta(days=120), end)[["date", "ticker", "close", "volume"]]
                frames.append(b.assign(ticker=s))
            except AlpacaLegError as e:
                if "no bars at all" not in str(e) and "nothing returned" not in str(e):
                    raise
                none.add(s)
        have = pd.concat(frames, ignore_index=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        have.to_parquet(p)
        nob.write_text(json.dumps(sorted(none)))
    rows = []
    for s in sorted(set(symbols)):
        g = have[have["ticker"] == s].sort_values("date").tail(ADV_SESSIONS)
        rows.append({"symbol": s, "n_sessions": len(g),
                     "adv_usd_median": float((g["close"] * g["volume"]).median()) if len(g) else None,
                     "last_bar": str(pd.Timestamp(g["date"].iloc[-1]).date()) if len(g) else None})
    return pd.DataFrame(rows)


# =============================================================== assembling deals

def _dates_by_cik(idx: pd.DataFrame, forms) -> dict[int, np.ndarray]:
    x = idx[idx["form"].isin(forms)]
    return {int(c): np.sort(g["date_filed"].values) for c, g in x.groupby("cik")}


def _any_in(arr, lo, hi) -> bool:
    if arr is None:
        return False
    lo, hi = np.datetime64(pd.Timestamp(lo)), np.datetime64(pd.Timestamp(hi))
    return bool(((arr >= lo) & (arr <= hi)).any())


def _first_in(arr, lo, hi):
    if arr is None:
        return None
    lo, hi = np.datetime64(pd.Timestamp(lo)), np.datetime64(pd.Timestamp(hi))
    m = arr[(arr >= lo) & (arr <= hi)]
    return pd.Timestamp(m[0]) if len(m) else None


def listed_today(tickers: pd.DataFrame) -> dict[int, str]:
    """CIK -> a ticker listed today on NYSE / Nasdaq / Cboe (the SEC ticker file's own labels)."""
    t = tickers[tickers["exchange"].isin(LISTED_EXCHANGES)]
    return {int(c): g["ticker"].iloc[0] for c, g in t.groupby("cik")}


def assemble_deals(idx: pd.DataFrame, funds: set, tickers: pd.DataFrame) -> pd.DataFrame:
    """Anchored deals with target, acquirer, stock-involvement, listing and completion (rules: docstring)."""
    eps = build_episodes(idx, funds)
    co = colisted(idx)
    eps["deal"] = link_deals(eps, co)
    reg = _dates_by_cik(idx, REG_FORMS)
    dl = _dates_by_cik(idx, DELIST_FORMS)
    f425 = _dates_by_cik(idx, ("425",))
    live = listed_today(tickers)
    rows = []
    for deal, g in eps.groupby("deal"):
        d0, a1 = g["d0"].min(), g["a1"].max()
        hi = a1 + pd.Timedelta(days=TAIL_DAYS)
        regs = [c for c in g["cik"] if _any_in(reg.get(c), d0 - pd.Timedelta(days=LOOKBACK_DAYS), hi)]
        non_reg = [c for c in g["cik"] if c not in regs]
        dl_in = [c for c in g["cik"] if _any_in(dl.get(c), d0, a1 + pd.Timedelta(days=COMPLETE_DAYS))]
        if len(set(g["cik"])) == 1:
            target, rule = int(g["cik"].iloc[0]), "single"
        elif len(set(non_reg)) == 1:
            target, rule = int(non_reg[0]), "non_registrant"
        elif len(set(dl_in)) == 1:
            target, rule = int(dl_in[0]), "delisted"
        else:
            target, rule = int(g.sort_values("a0")["cik"].iloc[0]), "target_ambiguous"
        t = g[g["cik"] == target].iloc[0]
        cands = Counter()
        for d, other, form in co.get(target, []):
            if d0 <= d <= hi and other not in funds:
                cands[(other, form)] += 1
        stock = _any_in(f425.get(target), d0, hi)
        acq = None
        if cands:
            by = Counter()
            for (o, form), n in cands.items():
                by[o] += n
            reg_c = [o for o in by if _any_in(reg.get(o), d0 - pd.Timedelta(days=LOOKBACK_DAYS), hi)]
            pool = reg_c if (stock and reg_c) else list(by)
            acq = max(pool, key=lambda o: (by[o], -o))
        delist = _first_in(dl.get(target), d0, a1 + pd.Timedelta(days=COMPLETE_DAYS))
        ever = _first_in(dl.get(target), d0, pd.Timestamp("2100-01-01"))
        rows.append({"deal": int(deal), "target_cik": target, "target_name": t["name"], "target_rule": rule,
                     "members": "|".join(str(c) for c in sorted(set(g["cik"]))), "d0": d0, "a0": g["a0"].min(),
                     "a1": a1, "year": d0.year, "tender": bool(g["tender"].any()),
                     "stock_structural": stock, "acquirer_cik": acq,
                     "completed": delist is not None, "delist_date": delist,
                     "listed": (ever is not None) or (target in live),
                     "ticker_today": live.get(target), "acquirer_ticker_today": live.get(acq) if acq else None})
    return pd.DataFrame(rows).sort_values(["d0", "target_cik"]).reset_index(drop=True)


# =============================================================== reading one deal

def announcement_doc(prof: dict, d0: pd.Timestamp, a0: pd.Timestamp, tender: bool) -> tuple[str, str, str] | None:
    """(source, accession, primary document) of the document that states the consideration.

    Order: 8-K with item 1.01 in [d0-30, d0+10]; 8-K 1.01 in [d0-120, a0]; the
    target's first 425 in [d0, a0]; for a tender, its first SC 14D9. None if
    nothing qualifies (the deal is then `unclassified`).
    """
    f = prof["filings"]
    k8 = f[(f["form"] == "8-K") & f["items"].fillna("").str.contains(r"\b1\.01\b")]
    lo, hi = d0 + pd.Timedelta(days=ANNOUNCE_WINDOW[0]), d0 + pd.Timedelta(days=ANNOUNCE_WINDOW[1])
    for (a, b), src in (((lo, hi), "8-K 1.01"), ((d0 - pd.Timedelta(days=120), a0), "8-K 1.01 (wide)")):
        x = k8[(k8["filingDate"] >= a) & (k8["filingDate"] <= b)]
        if len(x):
            r = x.iloc[0]
            return src, r["accessionNumber"], r["primaryDocument"]
    x = f[(f["form"] == "425") & (f["filingDate"] >= d0) & (f["filingDate"] <= a0)]
    if len(x):
        r = x.iloc[0]
        return "425", r["accessionNumber"], r["primaryDocument"]
    if tender:
        x = f[(f["form"] == "SC 14D9") & (f["filingDate"] >= d0)]
        if len(x):
            r = x.iloc[0]
            return "SC 14D9", r["accessionNumber"], r["primaryDocument"]
    return None


def terminated_after(client, prof: dict, d0: pd.Timestamp) -> str | None:
    """Accession of an 8-K item 1.02 after d0 whose body mentions a merger agreement, else None."""
    f = prof["filings"]
    x = f[(f["form"] == "8-K") & f["items"].fillna("").str.contains(r"\b1\.02\b") & (f["filingDate"] >= d0)]
    for _, r in x.iterrows():
        body = normalise(fetch_doc(client, prof["cik"], r["accessionNumber"], r["primaryDocument"]))
        if "merger agreement" in body or "agreement and plan of merger" in body:
            return r["accessionNumber"]
    return None


def enrich(client, deals: pd.DataFrame, offline: bool, today: date) -> pd.DataFrame:
    """Submissions (SIC, 8-K items) and the consideration class for every listed deal."""
    out = []
    n = len(deals)
    for i, r in deals.iterrows():
        rec = r.to_dict()
        if not r["listed"]:
            out.append(rec)
            continue
        lo = r["d0"] - pd.Timedelta(days=130)
        hi = max(r["a1"], r["d0"]) + pd.Timedelta(days=COMPLETE_DAYS)
        from scripts.data.edgar_client import EdgarNotFound
        maybe_pending = (not r["completed"]) and r["d0"] >= pd.Timestamp(today) - pd.Timedelta(days=PENDING_DAYS)
        try:
            prof = submissions(client, r["target_cik"], lo, min(hi, pd.Timestamp(today)), offline,
                               max_age_days=1 if maybe_pending else 30)
        except EdgarNotFound:
            # A fact about EDGAR (no submissions JSON for the CIK), recorded and counted, never filled.
            rec.update(sic=None, doc_source=None, doc_accession=None, doc_name=None, text_class="unclassified",
                       text_why="submissions JSON 404")
            out.append(rec)
            continue
        rec["sic"] = prof["sic"]
        doc = announcement_doc(prof, r["d0"], r["a0"], r["tender"])
        if doc is None:
            rec.update(doc_source=None, doc_accession=None, doc_name=None, text_class="unclassified",
                       text_why="no announcement document found")
        else:
            src, acc, name = doc
            rec["doc_date"] = prof["filings"].loc[prof["filings"]["accessionNumber"] == acc, "filingDate"].iloc[0]
            try:
                text = plain(fetch_doc(client, r["target_cik"], acc, name))
                c = classify_consideration(text)
                rec.update(doc_source=src, doc_accession=acc, doc_name=name, text_class=c["class"],
                           text_why=c["why"])
            except EdgarNotFound:
                rec.update(doc_source=src, doc_accession=acc, doc_name=name, text_class="unclassified",
                           text_why="primary document 404")
        if maybe_pending:
            rec["terminated_by"] = terminated_after(client, prof, r["d0"])
        out.append(rec)
        if (len(out) % 250) == 0:
            print(f"  enrich: {len(out)}/{n} deals, EDGAR requests {client.n_requests}, cache hits {client.n_cache_hits}",
                  flush=True)
    return pd.DataFrame(out)


# =============================================================== 425-only recent components (pending)

def recent_425_components(idx: pd.DataFrame, deals: pd.DataFrame, since: pd.Timestamp, funds: set) -> list[dict]:
    """425 components since `since` with no CIK in an anchored deal whose window overlaps."""
    x = idx[(idx["form"] == "425") & (idx["date_filed"] >= since)]
    uf = UnionFind()
    for acc, g in x.groupby("accession"):
        c = sorted(set(int(v) for v in g["cik"]))
        for o in c[1:]:
            uf.union(c[0], o)
        uf.find(c[0])
    comp = defaultdict(set)
    for c in x["cik"].unique():
        comp[uf.find(int(c))].add(int(c))
    anchored = set()
    for _, r in deals[deals["a1"] >= since - pd.Timedelta(days=LOOKBACK_DAYS)].iterrows():
        anchored |= {int(c) for c in r["members"].split("|")}
        if r["acquirer_cik"] is not None and not pd.isna(r["acquirer_cik"]):
            anchored.add(int(r["acquirer_cik"]))
    out = []
    for root, ciks in comp.items():
        if ciks & anchored or ciks <= funds:
            continue
        rows = x[x["cik"].isin(ciks)].sort_values(["date_filed", "accession"])
        out.append({"ciks": sorted(ciks), "first_acc": rows["accession"].iloc[0], "first_cik": int(rows["cik"].iloc[0]),
                    "first": rows["date_filed"].iloc[0], "last": rows["date_filed"].iloc[-1], "n425": rows["accession"].nunique()})
    return out


def _parties(h: dict) -> dict[int, dict]:
    """CIK -> {name, sic, file_number} for every party on one 425 header."""
    return {x["cik"]: {"name": x["conformed_name"], "sic": x.get("assigned_sic"), "file_number": x.get("file_number")}
            for x in h["subject"] + h["filed_by"]}


def resolve_components(client, comps: list[dict], funds: set, live: dict, reg: dict,
                       today: pd.Timestamp, splitoff: dict | None = None) -> list[dict]:
    """Roles inside each recent 425 component, by registration (module docstring, PENDING TODAY).

    Returns one record per component: `kind` is 'pair' (target_cik and
    acquirer_cik set), 'acquirer_only', 'target_only', 'skip' (blank check or
    fund party, a SPAC name, or a split-off) or 'unresolved' (with `why`). The
    first 425's SEC header gives each party's SIC and file number, for the
    blank-check and fund exclusions. A member that filed an issuer tender offer
    (SC TO-I) in the window makes the component a split-off exchange offer
    (2026-10-18: Medtronic / MiniMed, Lennar / Millrose read as 'pairs'),
    which is not a merger arbitrage.
    """
    splitoff = splitoff or {}
    out = []
    for c in comps:
        h = fetch_header(client, c["first_cik"], c["first_acc"])
        parties = _parties(h)
        ciks = [x for x in c["ciks"] if x not in funds]
        rec = {**c, "header_type": h["type"], "kind": None, "why": None, "target_cik": None, "acquirer_cik": None}
        if any(parties.get(x, {}).get("sic") == SPAC_SIC for x in c["ciks"]):
            rec.update(kind="skip", why="a party is a blank check (SIC 6770)")
        elif any(SPAC_NAME_RE.search(v.get("name") or "") for v in parties.values()):
            rec.update(kind="skip", why="a party has a blank-check name")
        elif any(_any_in(splitoff.get(x), c["first"] - pd.Timedelta(days=TAIL_DAYS), today) for x in c["ciks"]):
            rec.update(kind="skip", why="a member filed SC TO-I (split-off exchange offer)")
        elif any((parties.get(x, {}).get("file_number") or "").startswith(("811-", "814-")) for x in c["ciks"]) or not ciks:
            rec.update(kind="skip", why="a party files as an investment company")
        else:
            lo = c["first"] - pd.Timedelta(days=LOOKBACK_DAYS)
            regs = [x for x in ciks if _any_in(reg.get(x), lo, today)]
            non = [x for x in ciks if x not in regs]
            if len(ciks) == 1:
                rec.update(kind="acquirer_only" if regs else "target_only")
                rec["acquirer_cik" if regs else "target_cik"] = ciks[0]
            elif len(regs) == 1:
                listed_non = [x for x in non if x in live]
                tgt = non[0] if len(non) == 1 else (listed_non[0] if len(listed_non) == 1 else None)
                if tgt is None:
                    rec.update(kind="unresolved", why=f"one registrant, {len(non)} other members")
                else:
                    rec.update(kind="pair", target_cik=tgt, acquirer_cik=regs[0])
            else:
                rec.update(kind="unresolved", why="no registrant yet" if not regs else f"{len(regs)} registrants")
        for k in ("target", "acquirer"):
            x = rec[f"{k}_cik"]
            rec[f"{k}_name"] = parties.get(x, {}).get("name") if x is not None else None
            rec[f"{k}_ticker_today"] = live.get(x) if x is not None else None
        out.append(rec)
    return out


def name_phrase(name: str) -> str | None:
    """The first two distinctive tokens of a company name, lower-case ('PNC FINANCIAL SERVICES GROUP' -> 'pnc
    financial'); None if the name has none. Generic words ('INC', 'CORP', 'THE') are the merger-date matcher's."""
    from scripts.events.edgar_merger_dates import GENERIC, name_tokens
    toks = [t for t in name_tokens(name) if t not in GENERIC]
    return " ".join(toks[:2]).lower() if toks else None


def names_in(text: str, name: str) -> bool:
    """Does the document name the company? Punctuation-insensitive phrase match of `name_phrase`."""
    ph = name_phrase(name)
    if ph is None:
        return False
    norm = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    return f" {re.sub(r'[^a-z0-9]+', ' ', ph).strip()} " in norm


def match_acquirer(first: pd.Timestamp, text: str | None, acquirers: list[dict],
                   tol: int = PAIR_TOL_DAYS) -> tuple[dict | None, str]:
    """The one acquirer_only whose first 425 is within `tol` days of `first` and whom `text` names.

    Returns (record, why). No document, no candidate in the window, or a name
    test passed by zero or by two candidates: (None, the reason). Never the
    nearest date alone: two banks announce deals on the same day often enough.
    """
    cands = [a for a in acquirers if abs(_days(a["first"], first)) <= tol]
    if not cands:
        return None, "no acquirer_only 425 within the window"
    if text is None:
        return None, "no announcement document to confirm the name"
    hits = [a for a in cands if a.get("acquirer_name") and names_in(text, a["acquirer_name"])]
    if len(hits) == 1:
        return hits[0], f"matched: 1 of {len(cands)} candidates named in the document"
    return None, f"{len(hits)} of {len(cands)} candidates named in the document"


# =============================================================== tables

def year_table(d: pd.DataFrame) -> pd.DataFrame:
    """Deals in scope by year of d0: structural split and the text split, completed or not."""
    rows = []
    for y, g in d.groupby("year"):
        st = g[g["stock_structural"]]
        ca = g[~g["stock_structural"]]
        rows.append({"year": int(y), "deals": len(g), "completed": int(g["completed"].sum()),
                     "not_completed": int((~g["completed"]).sum()), "tender": int(g["tender"].sum()),
                     "cash_struct": len(ca), "stock_involved_struct": len(st),
                     "text_cash": int((g["text_class"] == "cash").sum()),
                     "text_stock": int((g["text_class"] == "stock").sum()),
                     "text_mixed": int((g["text_class"] == "mixed").sum()),
                     "text_unclassified": int((g["text_class"] == "unclassified").sum()),
                     "struct_cash_text_cash": int((ca["text_class"] == "cash").sum()),
                     "struct_stock_text_stock": int((st["text_class"] == "stock").sum()),
                     "struct_stock_text_mixed": int((st["text_class"] == "mixed").sum()),
                     "struct_stock_text_cash": int((st["text_class"] == "cash").sum()),
                     "struct_cash_text_stock_or_mixed": int(ca["text_class"].isin(["stock", "mixed"]).sum())})
    return pd.DataFrame(rows)


def final_class(r) -> str:
    """The note's cash / stock / mixed: structure decides cash vs stock-involved; text splits stock from mixed.

    Where structure and text disagree the deal is reported as
    `conflict_<struct>_<text>`, never forced into a class.
    """
    t = r["text_class"]
    if not r["stock_structural"]:
        return "cash" if t in ("cash", "unclassified") else f"conflict_cash_{t}"
    if t in ("stock", "mixed"):
        return t
    return "stock_involved_unsplit" if t == "unclassified" else f"conflict_stock_{t}"


def crsp_by_year(c: pd.DataFrame) -> pd.DataFrame:
    x = c[c["shrcd"].isin([10, 11]) & c["exchcd"].isin([1, 2, 3])].copy()
    x["year"] = x["dlstdt"].dt.year
    t = x.pivot_table(index="year", columns="dlstcd", values="permno", aggfunc="count", fill_value=0)
    t.columns = [f"dlstcd_{int(k)}" for k in t.columns]
    t["total"] = t.sum(axis=1)
    return t.reset_index()


def match_crsp(d: pd.DataFrame, c: pd.DataFrame, days: int = 15) -> pd.DataFrame:
    """EDGAR completed deals <-> CRSP merger delistings: dlstdt within +-days of the 25/25-NSE, best name >= MIN_SCORE."""
    from scripts.events.edgar_merger_dates import MIN_SCORE, name_score, name_tokens
    x = c[c["shrcd"].isin([10, 11, 12, 18])].copy()
    out = []
    for _, r in d[d["completed"] & (d["delist_date"] <= pd.Timestamp("2024-12-31"))].iterrows():
        dd = pd.Timestamp(r["delist_date"])
        cand = x[(x["dlstdt"] >= dd - pd.Timedelta(days=days)) & (x["dlstdt"] <= dd + pd.Timedelta(days=days))]
        et = name_tokens(r["target_name"])
        best, sc = None, -9.0
        for _, k in cand.iterrows():
            if not isinstance(k["comnam"], str):
                continue
            s = name_score(name_tokens(k["comnam"]), et)
            if s > sc:
                best, sc = k, s
        hit = best is not None and sc >= MIN_SCORE
        out.append({"deal": r["deal"], "target_cik": r["target_cik"], "matched": hit,
                    "score": round(sc, 3) if best is not None else None,
                    "dlstcd": int(best["dlstcd"]) if hit else None, "shrcd": int(best["shrcd"]) if hit else None,
                    "final_class": r["final_class"], "text_class": r["text_class"],
                    "stock_structural": r["stock_structural"]})
    return pd.DataFrame(out)


# =============================================================== freeze-outs, sample scoring, capacity

def freeze_out(idx: pd.DataFrame, scope: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """SC 13E3 (Rule 13e-3 going-private) accessions by year, and which in-scope deals carry one.

    The index cannot say which CIK on an SC 13E3 is the issuer and which the
    filing affiliate, so an accession is counted once and a deal is flagged
    when its TARGET appears on an SC 13E3 in [d0 - TAIL_DAYS, a1 + TAIL_DAYS].
    A flagged deal is a going-private transaction with an affiliate on the
    buy side: a controller freeze-out, or a management or sponsor buyout with
    management rolling equity. The index does not separate the two.
    """
    x = idx[idx["form"].isin(FREEZE_FORMS)].drop_duplicates("accession")
    x = x[x["date_filed"].dt.year >= COUNT_FROM_YEAR]
    acc_by_year = x.groupby(x["date_filed"].dt.year).size().rename("sc13e3_accessions")
    dates = _dates_by_cik(idx, FREEZE_FORMS)
    flag = pd.Series([_any_in(dates.get(int(r["target_cik"])), r["d0"] - pd.Timedelta(days=TAIL_DAYS),
                              r["a1"] + pd.Timedelta(days=TAIL_DAYS)) for _, r in scope.iterrows()],
                     index=scope.index, name="freeze_out")
    return acc_by_year.reset_index().rename(columns={"date_filed": "year"}), flag


def freeze_out_table(scope: pd.DataFrame) -> pd.DataFrame:
    """In-scope deals by year: how many carry an SC 13E3, their class mix and completion (counts only)."""
    rows = []
    for y, g in scope.groupby("year"):
        f = g[g["freeze_out"]]
        rows.append({"year": int(y), "deals": len(g), "freeze_out": len(f),
                     "fo_cash": int((f["final_class"] == "cash").sum()),
                     "fo_stock_involved": int(f["final_class"].isin(STOCK_CLASSES).sum()),
                     "fo_other": int((~f["final_class"].isin(("cash",) + STOCK_CLASSES)).sum()),
                     "fo_completed": int(f["completed"].sum()), "fo_tender": int(f["tender"].sum())})
    return pd.DataFrame(rows)


def _num(v) -> float | None:
    """'$36.00' / '36.00' / '1,250' -> float; None or '' -> None. Raises on anything else."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip()):
        return None
    t = str(v).replace("$", "").replace(",", "").strip()
    return float(t)


def _date(v):
    """A calendar date, or the text itself for a relative date ('six months after signing'), or None."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return pd.Timestamp(str(v)).date()
    except (ValueError, TypeError):
        return str(v)


def _fee_musd(v) -> float | None:
    """'125 million' / '1.2 billion' / '$45,000,000' -> USD millions."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip()):
        return None
    t = str(v).lower().replace("$", "").replace(",", "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(million|billion)?$", t)
    if not m:
        raise ValueError(f"termination fee {v!r} will not parse")
    x = float(m.group(1))
    return x * 1000 if m.group(2) == "billion" else x if m.group(2) == "million" else x / 1e6


def _outcome(machine, reader) -> str:
    """One field: agree / missed (reader has it, machine none) / wrong (both, differ) / spurious (machine only)."""
    mz, rz = machine in (None, False), reader in (None, False)
    if mz and rz:
        return "agree"
    if mz:
        return "missed"
    if rz:
        return "spurious"
    return "agree" if machine == reader else "wrong"


def _pairs(x) -> dict[str, tuple]:
    """(machine, reader) for each scored field of one READ target row (see `score_sample`)."""
    appr = [a.strip().upper() for a in str(x.get("r_approvals") or "").split(";") if a.strip()]
    hsr_r = any("HSR" in a or "HART-SCOTT" in a for a in appr)
    other_r = any(not ("HSR" in a or "HART-SCOTT" in a) for a in appr)
    fin_r = True if x.get("r_financing_cond") is False else None    # True = 'no financing condition' stated
    vote_r = x.get("r_vote") in ("target", "both", "written consent")
    m_other = x["m_other_reg"]
    m_other = bool(m_other) and m_other != "[]"
    return {
        "consideration class": (x["m_class"] if x["m_class"] != "unclassified" else None, x.get("r_consideration")),
        "cash per share": (_num(x["m_cash_per_share"]), _num(x.get("r_cash_per_share"))),
        "exchange ratio": (_num(x["m_ratio"]), _num(x.get("r_ratio"))),
        "collar": (bool(x["m_collar"]), bool(x.get("r_collar"))),
        "CVR": (bool(x["m_cvr"]), bool(x.get("r_cvr"))),
        "outside date": (_date(x["m_outside_date"]), _date(x.get("r_outside_date"))),
        "HSR condition": (bool(x["m_hsr"]), hsr_r),
        "other regulatory condition": (m_other, other_r),
        "no financing condition": (True if x["m_no_financing_condition"] else None, fin_r),
        "target vote": (bool(x["m_vote"]), vote_r),
        "termination fee": (_fee_musd(x["m_termination_fee"]), _fee_musd(x.get("r_term_fee"))),
    }


def score_sample(sample: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Field-by-field and deal-by-deal: does the regex reader agree with the hand reading of the same document?

    Only rows with a reading count, and only rows whose reading says the
    document is a TARGET's deal; the others (a buyer's share-issuance proxy, a
    reorganisation, the wrong 8-K) are counted once in their own row.
    'missed' means the document states the term and the machine found
    nothing; 'wrong' that it found a different value; 'spurious' that it
    reported a term the reader found absent. Numeric fields compare as numbers
    ('$36.00' = '36.00', '0.4500' = '0.45'); a relative outside date ('one year
    from signing') can only be missed or wrong, never matched by a calendar date.
    Returns (by field, by deal).
    """
    r = sample[sample["read"]] if "read" in sample else sample.iloc[0:0]
    out, deals = defaultdict(Counter), []
    for _, x in r.iterrows():
        if x.get("r_role") != "target":
            # Not an arbitrageable target (the anchor is a buyer's share-issuance vote, a reorganisation,
            # or the pipeline picked the wrong 8-K): counted once, never scored field by field.
            out["(document is not a target's deal: excluded below)"]["wrong"] += 1
            deals.append({"target": x["target"], "accession": x["accession"], "role": x.get("r_role"),
                          "fields_scored": 0, "fields_not_agreeing": None})
            continue
        res = {k: _outcome(m, rd) for k, (m, rd) in _pairs(x).items()}
        for k, o in res.items():
            out[k][o] += 1
        bad = [k for k, o in res.items() if o != "agree"]
        deals.append({"target": x["target"], "accession": x["accession"], "role": "target",
                      "fields_scored": len(res), "fields_not_agreeing": len(bad), "which": "; ".join(bad)})
    t = pd.DataFrame(out).T.fillna(0).astype(int)
    for c in ("agree", "missed", "wrong", "spurious"):
        if c not in t:
            t[c] = 0
    t = t[["agree", "missed", "wrong", "spurious"]]
    t["n"] = t.sum(axis=1)
    return t, pd.DataFrame(deals)


def capacity_table(pend: pd.DataFrame) -> pd.DataFrame:
    """Pending deals that can absorb a position of X at PARTICIPATION of median ADV in one session.

    Cash deals need the target leg only. Stock-involved deals also need the
    acquirer short: at Alpaca `shortable` and `easy_to_borrow`, and its ADV.
    For a pure stock deal the short's dollar size is about the long's, so the
    same X is applied to both legs (stated, not measured per deal).
    """
    rows = []
    cash = pend[pend["final_class"] == "cash"]
    stk = pend[pend["final_class"].isin(STOCK_CLASSES)]
    borrow_ok = (stk["acq_alp_shortable"] == True) & (stk["acq_alp_etb"] == True)  # noqa: E712 (None is not True)
    for x in POSITION_USD:
        need = x / PARTICIPATION
        rows.append({
            "position_usd": x, "adv_needed_usd": need,
            "cash_deals": len(cash), "cash_fit": int((cash["tgt_adv_usd"] >= need).sum()),
            "stock_deals": len(stk), "stock_borrow_ok": int(borrow_ok.sum()),
            "stock_fit_both_legs": int((borrow_ok & (stk["tgt_adv_usd"] >= need) & (stk["acq_adv_usd"] >= need)).sum()),
        })
    return pd.DataFrame(rows)


# =============================================================== main

def cef_names() -> list[str]:
    from scripts.cef.spec import UNIVERSE
    return sorted(set(UNIVERSE) | {"NAD", "NEA", "NVG", "NZF"})


def run(today: date, offline: bool) -> dict:
    from scripts.events import merger_arb_readings as R
    OUT.mkdir(parents=True, exist_ok=True)
    client = edgar(offline)
    idx = load_index(client, today, offline)
    last_idx = idx["date_filed"].max()
    tickers = sec_tickers(client, today, offline)
    live = listed_today(tickers)
    funds = set(int(c) for c in idx.loc[idx["form"].isin(FUND_FORMS), "cik"])
    deals = assemble_deals(idx, funds, tickers)
    deals = deals[deals["d0"] >= pd.Timestamp(f"{COUNT_FROM_YEAR}-01-01")].reset_index(drop=True)
    print(f"index rows {len(idx):,}, last filing date {last_idx.date()}; anchored deals 2010+ {len(deals):,}", flush=True)
    d = enrich(client, deals, offline, today)
    d["spac_name"] = d["target_name"].str.contains(SPAC_NAME_RE)
    d["spac"] = (d["sic"] == SPAC_SIC) | d["spac_name"]
    reg_all = _dates_by_cik(idx, REG_FORMS)
    d["target_registered"] = [_any_in(reg_all.get(int(r["target_cik"])), r["d0"] - pd.Timedelta(days=LOOKBACK_DAYS),
                                      r["a1"] + pd.Timedelta(days=TAIL_DAYS)) for _, r in d.iterrows()]
    scope = d[d["listed"] & ~d["spac"].fillna(False)].copy()
    scope["final_class"] = scope.apply(final_class, axis=1)
    excl = {"anchored_deals_2010_plus": len(d), "not_listed": int((~d["listed"]).sum()),
            "blank_check_sic_6770_or_name": int((d["listed"] & d["spac"].fillna(False)).sum()),
            "blank_check_by_name_only": int((d["listed"] & d["spac_name"] & (d["sic"] != SPAC_SIC)).sum()),
            "in_scope": len(scope), "in_scope_target_registered": int(scope["target_registered"].sum()),
            "in_scope_target_registered_not_completed": int((scope["target_registered"] & ~scope["completed"]).sum()),
            "fund_ciks_excluded_before_assembly": len(funds),
            "target_rule": scope["target_rule"].value_counts().to_dict(),
            "doc_source": scope["doc_source"].fillna("none").value_counts().to_dict()}
    fo_acc, scope["freeze_out"] = freeze_out(idx, scope)
    yt = year_table(scope)
    # d0 for a cash merger with no 425 is its first proxy, weeks after the announcement. How many deals
    # would change YEAR if the announcement 8-K's date were used instead (the 8-K found in the narrow window)?
    near = scope[(scope["doc_source"] == "8-K 1.01") & scope["doc_date"].notna()]
    excl["year_shift_if_8k_date"] = int((pd.to_datetime(near["doc_date"]).dt.year != near["year"]).sum())
    excl["median_days_8k_before_d0"] = float((near["d0"] - pd.to_datetime(near["doc_date"])).dt.days.median())
    fc = scope.pivot_table(index="year", columns="final_class", values="deal", aggfunc="count", fill_value=0)
    fcc = scope[scope["completed"]].pivot_table(index="year", columns="final_class", values="deal",
                                                 aggfunc="count", fill_value=0)
    yt.to_csv(OUT / "edgar_deals_by_year.csv", index=False)
    fc.to_csv(OUT / "edgar_final_class_by_year.csv")
    fcc.to_csv(OUT / "edgar_final_class_completed_by_year.csv")
    cols = ["deal", "target_cik", "target_name", "ticker_today", "d0", "a1", "year", "tender", "stock_structural",
            "text_class", "final_class", "completed", "delist_date", "acquirer_cik", "acquirer_ticker_today",
            "doc_source", "doc_accession", "doc_name", "text_why", "target_rule", "sic"]
    cols += ["freeze_out", "target_registered", "doc_date"]
    scope[cols].to_csv(OUT / "edgar_deals.csv", index=False)
    fot = freeze_out_table(scope).merge(fo_acc, on="year", how="outer")
    fot.to_csv(OUT / "freeze_out_by_year.csv", index=False)

    # ---- CRSP second method (2010-2024 counts; no returns)
    c = crsp_delistings(offline)
    cy = crsp_by_year(c)
    cy.to_csv(OUT / "crsp_merger_delistings_by_year.csv", index=False)
    m = match_crsp(scope, c)
    conf = pd.crosstab(m.loc[m["matched"], "final_class"], m.loc[m["matched"], "dlstcd"])
    conf.to_csv(OUT / "edgar_vs_crsp_confusion.csv")
    match_rate = {"edgar_completed_to_2024": len(m), "matched": int(m["matched"].sum())}

    # ---- pending deals today (rules: module docstring, PENDING TODAY)
    from scripts.data.edgar_client import EdgarNotFound
    tnow = pd.Timestamp(today)
    since = pd.Timestamp(last_idx) - pd.Timedelta(days=PENDING_DAYS)
    reg = _dates_by_cik(idx, REG_FORMS)
    dl = _dates_by_cik(idx, DELIST_FORMS)
    f425 = _dates_by_cik(idx, ("425",))
    pend = scope[~scope["completed"] & (scope["d0"] >= since) & scope["ticker_today"].notna()].copy()
    pend["source"] = "anchored"
    pend["pair_why"] = np.where(pend["acquirer_cik"].notna(), "co-listed on a 425 / SC TO-T", None)
    comps = recent_425_components(idx, d, since, funds)
    res = resolve_components(client, comps, funds, live, reg, tnow, splitoff=_dates_by_cik(idx, SPLITOFF_FORMS))
    acq_only = [r for r in res if r["kind"] == "acquirer_only"]

    def doc_text(cik, first):
        """(profile, (source, accession, name) or None, plain text or None) for a target's announcement."""
        prof = submissions(client, cik, first - pd.Timedelta(days=130), tnow, offline, max_age_days=1)
        doc = announcement_doc(prof, first, tnow, False)
        if doc is None:
            return prof, None, None
        try:
            return prof, doc, plain(fetch_doc(client, cik, doc[1], doc[2]))
        except EdgarNotFound:
            return prof, doc, None          # recorded: the document is named, its text is not read

    # anchored stock deals with no co-listed acquirer: the singleton match, confirmed by name
    for i, r in pend[pend["acquirer_cik"].isna() & pend["stock_structural"]].iterrows():
        text = None
        if isinstance(r["doc_accession"], str):
            try:
                text = plain(fetch_doc(client, r["target_cik"], r["doc_accession"], r["doc_name"]))
            except EdgarNotFound:
                text = None
        a, why = match_acquirer(r["d0"], text, acq_only)
        pend.loc[i, "pair_why"] = why
        if a is not None:
            pend.loc[i, "acquirer_cik"] = a["acquirer_cik"]
            pend.loc[i, "acquirer_ticker_today"] = a["acquirer_ticker_today"]
    extra, funnel = [], Counter(r["kind"] if r["kind"] != "unresolved" else f"unresolved: {r['why']}" for r in res)
    for r in res:
        if r["kind"] not in ("pair", "target_only"):
            continue
        t = r["target_cik"]
        if live.get(t) is None:
            funnel["target not listed today"] += 1
            continue
        if _any_in(dl.get(t), r["first"], tnow):
            funnel["target delisted since its first 425 (completed)"] += 1
            continue
        prof, doc, text = doc_text(t, r["first"])
        if prof["sic"] == SPAC_SIC or SPAC_NAME_RE.search(prof["name"] or ""):
            funnel["target is a blank check (submissions SIC)"] += 1
            continue
        why = "co-listed with its one registrant on a 425"
        if r["kind"] == "target_only":
            a, why = match_acquirer(r["first"], text, acq_only)
            if a is not None:
                r = {**r, "acquirer_cik": a["acquirer_cik"], "acquirer_ticker_today": a["acquirer_ticker_today"]}
        cls = classify_consideration(text)["class"] if text is not None else "unclassified"
        extra.append({"target_cik": t, "target_name": prof["name"], "ticker_today": live.get(t),
                      "d0": r["first"], "stock_structural": True, "text_class": cls,
                      "final_class": final_class({"stock_structural": True, "text_class": cls}),
                      "acquirer_cik": r["acquirer_cik"], "acquirer_ticker_today": r["acquirer_ticker_today"],
                      "doc_source": doc[0] if doc else None, "doc_accession": doc[1] if doc else None,
                      "terminated_by": terminated_after(client, prof, r["first"]), "source": f"425 {r['kind']}",
                      "pair_why": why, "tender": False, "completed": False})
    pend = pd.concat([pend, pd.DataFrame(extra)], ignore_index=True)
    funnel["terminated (8-K 1.02 naming a merger agreement)"] = int(pend["terminated_by"].notna().sum())
    pend = pend[pend["terminated_by"].isna()].copy()

    def last425(*ciks):
        ds = [pd.Timestamp(f425[c][-1]) for c in ciks if c is not None and not pd.isna(c) and int(c) in f425]
        return max(ds) if ds else None
    pend["last_425"] = [last425(r["target_cik"], r["acquirer_cik"]) for _, r in pend.iterrows()]
    pend["stale"] = pend["last_425"].map(lambda x: bool(pd.isna(x)) or _days(x, last_idx) > STALE_DAYS) & pend["stock_structural"]
    # every listed acquirer in a live stock deal: the borrow question does not need the pairing
    live_acq = {}
    for r in res:
        a = r["acquirer_cik"]
        if a is None or live.get(a) is None:
            continue
        la = last425(a)
        if la is not None and _days(la, last_idx) <= LIVE_425_DAYS:
            live_acq[a] = {"acquirer_cik": a, "acquirer_name": r["acquirer_name"], "symbol": live[a], "last_425": la,
                           "kind": r["kind"]}
    for _, r in pend[pend["acquirer_ticker_today"].notna()].iterrows():
        a = int(r["acquirer_cik"])
        la = last425(a)
        if la is not None and _days(la, last_idx) <= LIVE_425_DAYS and a not in live_acq:
            live_acq[a] = {"acquirer_cik": a, "acquirer_name": None, "symbol": r["acquirer_ticker_today"],
                           "last_425": la, "kind": "anchored pair"}
    live_acq = pd.DataFrame(list(live_acq.values()),
                            columns=["acquirer_cik", "acquirer_name", "symbol", "last_425", "kind"])
    syms = sorted(set(pend["ticker_today"].dropna()) | set(pend["acquirer_ticker_today"].dropna()) | set(cef_names())
                  | set(live_acq["symbol"]))
    flags = alpaca_assets(syms, today, offline).set_index("symbol")
    ib, ib_stamp = ibkr_file(today, offline)
    ib_rows = {k: g for k, g in ib.groupby("symbol")}
    pend = pend[pend["ticker_today"].map(lambda s: bool(flags.loc[s, "found"]) and flags.loc[s, "status"] == "active")]

    def leg(sym, pre):
        """One symbol's borrow at both brokers. A symbol the IBKR file lists twice (two
        contracts) gets no single fee: both rows are written to `_ibkr_dup` instead."""
        if sym is None or (isinstance(sym, float) and np.isnan(sym)):
            return {f"{pre}_alp_shortable": None, f"{pre}_alp_etb": None, f"{pre}_alp_borrow": None,
                    f"{pre}_ibkr_fee_pct": None, f"{pre}_ibkr_available": None, f"{pre}_ibkr_dup": None}
        a = flags.loc[sym] if sym in flags.index else None
        g = ib_rows.get(sym)
        k = g.iloc[0] if g is not None and len(g) == 1 else None
        dup = ("; ".join(f"{r['ibkr_name']}: fee {r['fee_rate_pct']} avail {r['available']:.0f}" for _, r in g.iterrows())
               if g is not None and len(g) > 1 else None)
        fee = k["fee_rate_pct"] if k is not None else None
        return {f"{pre}_alp_shortable": (a["shortable"] if a is not None and a["found"] else None),
                f"{pre}_alp_etb": (a["easy_to_borrow"] if a is not None and a["found"] else None),
                f"{pre}_alp_borrow": (a["borrow_status"] if a is not None and a["found"] else None),
                f"{pre}_ibkr_fee_pct": (float(fee) if fee is not None and not pd.isna(fee) else None),
                f"{pre}_ibkr_available": (("> " if k["available_gt"] else "") + f"{k['available']:.0f}") if k is not None else None,
                f"{pre}_ibkr_dup": dup}
    pend = pd.concat([pend.reset_index(drop=True),
                      pd.DataFrame([{**leg(r["acquirer_ticker_today"], "acq"), **leg(r["ticker_today"], "tgt")}
                                    for _, r in pend.iterrows()])], axis=1)
    adv = alpaca_adv(sorted(set(pend["ticker_today"].dropna()) | set(pend["acquirer_ticker_today"].dropna())),
                     today - timedelta(days=1), offline).set_index("symbol")
    pend["tgt_adv_usd"] = pend["ticker_today"].map(lambda s: adv.loc[s, "adv_usd_median"] if s in adv.index else None)
    pend["acq_adv_usd"] = pend["acquirer_ticker_today"].map(
        lambda s: adv.loc[s, "adv_usd_median"] if isinstance(s, str) and s in adv.index else None)
    pcols = ["source", "pair_why", "target_name", "ticker_today", "d0", "last_425", "stale", "final_class", "tender",
             "acquirer_ticker_today",
             "acq_alp_shortable", "acq_alp_etb", "acq_alp_borrow", "acq_ibkr_fee_pct", "acq_ibkr_available",
             "acq_ibkr_dup", "tgt_alp_shortable", "tgt_alp_etb", "tgt_ibkr_fee_pct",
             "tgt_adv_usd", "acq_adv_usd", "doc_source", "doc_accession", "target_cik", "acquirer_cik"]
    pend.sort_values("d0")[pcols].to_csv(OUT / f"pending_deals_{today}.csv", index=False)
    cap = capacity_table(pend)
    cap.to_csv(OUT / f"capacity_{today}.csv", index=False)
    la = pd.concat([live_acq.reset_index(drop=True),
                    pd.DataFrame([leg(sym, "acq") for sym in live_acq["symbol"]])], axis=1)
    la.to_csv(OUT / f"live_acquirers_{today}.csv", index=False)
    (OUT / f"pending_funnel_{today}.json").write_text(json.dumps(dict(funnel), indent=1, sort_keys=True))

    # ---- CEF names at both brokers (part B)
    cef = pd.DataFrame([{"symbol": s, **{k: v for k, v in leg(s, "x").items()}} for s in cef_names()])
    cef.columns = [col.replace("x_", "") for col in cef.columns]
    cef.to_csv(OUT / f"cef_names_borrow_{today}.csv", index=False)

    # ---- the declared reading sample: 10 most recent cash and 10 most recent stock-involved (rule: docstring)
    samp_pool = scope[(scope["d0"] >= pd.Timestamp("2026-01-01")) & scope["doc_source"].isin(["8-K 1.01", "8-K 1.01 (wide)"])]
    samp = pd.concat([samp_pool[~samp_pool["stock_structural"]].sort_values(["d0", "target_cik"], ascending=[False, True]).head(10),
                      samp_pool[samp_pool["stock_structural"]].sort_values(["d0", "target_cik"], ascending=[False, True]).head(10)])
    rule_accs = list(samp["doc_accession"])
    sample_drift = None
    if R.SAMPLE_ACCESSIONS:
        # The rule was applied once, on R.SAMPLE_DRAWN, and its 20 accessions frozen before any
        # reading. A later run reads the frozen 20 and reports how far today's rule has drifted.
        frozen = list(R.SAMPLE_ACCESSIONS)
        samp = scope[scope["doc_accession"].isin(frozen)].drop_duplicates("doc_accession")
        if len(samp) != len(frozen):
            missing = sorted(set(frozen) - set(samp["doc_accession"]))
            raise ValueError(f"frozen sample accessions no longer in scope: {missing}")
        samp = samp.set_index("doc_accession", drop=False).loc[frozen].reset_index(drop=True)
        sample_drift = sorted(set(rule_accs) ^ set(frozen))
    srows = []
    for _, r in samp.iterrows():
        text = plain(fetch_doc(client, r["target_cik"], r["doc_accession"], r["doc_name"]))
        mt = machine_terms(text)
        rd = R.READINGS.get(r["doc_accession"])
        if rd is not None:
            R.verify(rd, text, r["doc_accession"])
        srows.append({"target": r["target_name"], "ticker": r["ticker_today"], "d0": r["d0"].date(),
                      "accession": r["doc_accession"], "struct": "stock" if r["stock_structural"] else "cash",
                      **mt, **R.flatten(rd)})
    sample = pd.DataFrame(srows)
    sample.to_csv(OUT / f"deal_term_sample_{today}.csv", index=False)
    scored, by_deal = score_sample(sample)
    scored.to_csv(OUT / f"deal_term_scores_{today}.csv")
    by_deal.to_csv(OUT / f"deal_term_scores_by_deal_{today}.csv", index=False)

    summary = {"today": str(today), "index_last_filing_date": str(last_idx.date()), "exclusions": excl,
               "crsp_match": match_rate, "ibkr_file_stamp": ib_stamp,
               "pending": {"n": len(pend), "by_class": pend["final_class"].value_counts().to_dict(),
                           "by_source": pend["source"].value_counts().to_dict(),
                           "components": len(res), "funnel": dict(funnel),
                           "stock_involved": int(pend["final_class"].isin(STOCK_CLASSES).sum()),
                           "stock_involved_with_listed_acquirer": int((pend["final_class"].isin(STOCK_CLASSES)
                                                                       & pend["acquirer_ticker_today"].notna()).sum()),
                           "stock_involved_stale": int((pend["final_class"].isin(STOCK_CLASSES) & pend["stale"]).sum()),
                           "live_acquirers": len(live_acq)},
               "sample_n": len(sample), "sample_read": int(sample["read"].sum()) if "read" in sample else 0,
               "sample_frozen": bool(R.SAMPLE_ACCESSIONS), "sample_rule_today": rule_accs,
               "sample_roles": by_deal["role"].value_counts().to_dict() if len(by_deal) else {},
               "sample_targets_all_fields_agree": int((by_deal["fields_not_agreeing"] == 0).sum()) if len(by_deal) else 0,
               "sample_drift_vs_rule_today": sample_drift,
               "edgar_requests": client.n_requests}
    (OUT / f"summary_{today}.json").write_text(json.dumps(summary, indent=1, default=str))
    return {"years": yt, "final": fc, "final_completed": fcc, "crsp": cy, "conf": conf, "pending": pend,
            "cef": cef, "sample": sample, "summary": summary, "match": m, "freeze": fot, "capacity": cap,
            "scored": scored, "live_acq": la}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="read every input from the caches; raise on a miss")
    ap.add_argument("--today", default=str(date.today()), help="the run date that keys the caches (YYYY-MM-DD)")
    a = ap.parse_args(argv)
    res = run(date.fromisoformat(a.today), a.offline)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print("\n== EDGAR deals by year (structure and text) ==")
    print(res["years"].to_string(index=False))
    print("\n== final class by year (all announced) ==")
    print(res["final"].to_string())
    print(f"\n== final class by year (completed: 25/25-NSE within {COMPLETE_DAYS} days of the last anchor) ==")
    print(res["final_completed"].to_string())
    print("\n== CRSP merger delistings, US common (shrcd 10/11, exchcd 1-3), by delisting year ==")
    print(res["crsp"].to_string(index=False))
    print("\n== EDGAR final class x CRSP dlstcd (matched completed deals to 2024) ==")
    print(res["conf"].to_string())
    print("\n== pending deals today ==")
    print(res["pending"][["target_name", "ticker_today", "d0", "final_class", "acquirer_ticker_today",
                          "acq_alp_shortable", "acq_alp_etb", "acq_ibkr_fee_pct", "acq_ibkr_available",
                          "tgt_adv_usd"]].sort_values("d0").to_string(index=False))
    print("\n== live stock-deal acquirers (a 425 in the last LIVE_425_DAYS): borrow at both brokers ==")
    print(res["live_acq"].to_string(index=False))
    print("\n== CEF names: Alpaca and IBKR today ==")
    print(res["cef"].to_string(index=False))
    print("\n== freeze-outs: in-scope deals whose target is on an SC 13E3; SC 13E3 accessions by year ==")
    print(res["freeze"].to_string(index=False))
    print(f"\n== capacity: pending deals that absorb X at {PARTICIPATION:.0%} of median ADV in one session ==")
    print(res["capacity"].to_string(index=False))
    print("\n== reading sample: regex reader vs hand reading, by field ==")
    print(res["scored"].to_string())
    print("\n== summary ==")
    print(json.dumps(res["summary"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
