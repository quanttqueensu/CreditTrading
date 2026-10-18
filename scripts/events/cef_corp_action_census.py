"""Census of CEF/BDC corporate-action events that could be held LONG and hedged with a liquid ETF.

    export QUANTT_ENV_FILE=/abs/path/config/.env   # SEC_USER_AGENT, R2 and Alpaca keys; never printed
    python3 scripts/events/cef_corp_action_census.py            # EDGAR (cache first), R2, Alpaca reads
    python3 scripts/events/cef_corp_action_census.py --offline  # caches only; raises on a miss
    python3 -m pytest scripts/events/tests/test_cef_corp_action_census.py

WHY THIS EXISTS
---------------
Special-situations sprint, job 3 of 6 (team lead, 2026-10-15). The live book
cannot borrow most of the names an event trade would short (G1a: muni
acquirers 7 of 23 shortable), so the question is which CEF and BDC corporate
actions pay a holder who is LONG the fund and hedges its NAV beta with a liquid,
shortable ETF -- no borrow on the fund at all. The sprint wants, by event type:
how often it happens, how many independent decisions that is, what the terms
are, what spread the TERMS imply at announcement, how much of a position the
exit takes (pro-ration), how long it is held, how liquid the fund is, and which
ETF hedges it. Then a rank, and zero-trial gates for the best two or three.

ZERO TRIALS -- WHAT THIS SCRIPT NEVER COMPUTES
----------------------------------------------
* **No realised return or P&L of any event trade.** That would be a trial
  (EVENTS counter). Every spread here is TERMS-IMPLIED: the stated exit price
  (a percentage of NAV, NAV itself) set against a discount LEVEL observed on a
  stated date, `exit / (price/NAV) - 1`. The price that is later realised,
  the liquidating payment and the post-event discount are never read.
* **Level statistics only for events announced before 2023-01-01** (the time
  holdout). `assert_pre_holdout` guards every level computation; later events
  are COUNTED only. CRSP's daily file is read through
  `crsp_events.daily`, which cannot return a 2023 row.
* **No statistic on a `data/cef/cef_universe.csv` fund beyond counts.** The
  44 funds (the deployed 13, the 4 dropped munis and the 27-name holdout) are
  identified by CRSP permno (`crsp_events.universe_permnos`) AND by EDGAR CIK
  (the SEC ticker file); an event on either is counted and flagged, and every
  level field is left empty. The 27-name holdout is therefore not consumed.

THE EVENT TYPES AND WHERE EACH COMES FROM (one structural source each, so a
count never rests on a keyword search)
-----------------------------------------------------------------------------
* `nav_tender` -- an issuer tender for listed COMMON shares at k% of NAV.
  Source: the fetcher's tender episodes (`fetch_edgar_events`), each episode's
  first SC TO-I read for the cover-page class (`g6.classify_tender`), the price
  basis, listing, size and expiry; its last SC TO-I/A read for the result
  (shares tendered and accepted -> pro-ration). Interval-fund repurchases,
  preferred-share tenders and private funds drop out on the text, not by name.
* `fixed_price_tender` -- listed issuer tenders at a stated dollar price or a
  Dutch-auction range (mostly BDCs). Context row: the exit is a dollar price,
  so its spread needs no NAV.
* `liquidation`, `term_termination`, `open_ending` -- CRSP delistings of share
  code 14/44 funds (codes 4xx; 2xx, 3xx and 5xx with no successor permno), matched
  to an EDGAR CIK by name (`edgar_merger_dates.match_cik`, the matcher that
  dated 186 of 186 merger targets), then the fund's Form N-8F read: the box
  checked (Merger / Liquidation), the board-vote date (Item 15(a), the
  announcement proxy, labelled), the distribution dates (Item 16(a)) and, for a
  merger, the surviving fund. A term trust is a liquidation whose name carries
  a term marker. A merger into a fund that has no CRSP listing is an
  open-ending candidate, and is classified by reading the survivor's name
  (open-end series vs interval fund), not assumed. Conversions in place are
  found by form: a CIK that was a listed closed-end fund and later files an
  open-end registration (485APOS/485BPOS/N-1A).
* `activist_13d` -- initial Schedules 13D on fund-set CIKs whose filer is a
  known CEF activist (`ACTIVIST_RE`), plus the fetcher's proxy-contest
  episodes. There is no stated exit price, so no terms-implied spread exists.
* `rights_offering` -- CRSP distribution codes 45xx on share code 14/44
  permnos: first digit 4 "subscription rights", second digit 5 "same issue of
  common stock" (CRSP Data Definitions and Coding Schemes Guide, 1999, §6.2;
  docs/REFERENCES.md §12ab), cross-checked against the fund's own prospectus
  filings (424B*/497) within 60 days.
* `conditional_tender` -- read from `conditional_tender_census.csv` (the N1
  census, 2026-10-13); not re-derived.

LEVELS, AND WHY TWO DISCOUNTS
-----------------------------
A trade can only enter AFTER the announcement, so the spread it can capture is
the post-announcement one. For tenders the offer document states the NAV on a
named date a few days before the offer opens (the fee-calculation cover line,
or a "NAV ... was $X and the ... price was $Y" sentence); CRSP's close on that
SAME date gives `disc_post` -- but only where that date is on or after the
episode's first EDGAR filing (`post_discount`). In the 2026-10-15 build 33 of
130 offer NAVs were dated BEFORE it (by up to 25 days), so the predecessor
draft's "disc_post" was partly a pre-announcement level; the any-date figure
is kept as `disc_navdate` and reported only as a sensitivity. For dead funds that liquidated or open-ended there
is no daily NAV anywhere in this repository (plan item 0.8), so the only
discount available is the last fiscal period-end before the announcement:
`disc_pre`, read from the fund's N-CSR/N-CSRS (period of report < announcement)
and accepted ONLY where the filing's market price for that period equals CRSP's
close on that date to the cent (`nav_beside_price`); the NAV is the figure in
the same column or pair. `disc_pre` is stale by the stated number of days and is
an UPPER bound on what an entry after the announcement could capture. The same
`disc_pre` is computed for tenders, so the two can be compared like with like.

INDEPENDENT GROUPS
------------------
Sponsor x announcement date, as G1c and the N1 census use: one sponsor acting on
several funds on one day is one decision and one market. The sponsor is read
from the fund's name (`sponsor_of`); an unrecognised name is its own sponsor,
which can only overstate the groups, and the share of events so treated is
reported. A stricter clustering (sponsor x calendar month) is shown beside it.

HEDGES
------
Each event's asset class (from its name) maps to one primary ETF
(`HEDGE_ETF`) and declared alternates on the same exposure
(`HEDGE_ALTERNATES`), all read at Alpaca on one date. The first shortable one
is the hedge named. Whether any of them hedges the fund well is a return
question and is not asked here.

LICENSING
---------
CRSP is licensed and this repository is public. `cef_corp_action_events.csv`
(tracked) carries EDGAR facts and parsed terms only; CRSP-joined fields
(permno, prices, ADV, discounts) are in `cef_corp_action_events_full.csv`,
which is gitignored. Aggregates are tracked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events"
EVENTS_CSV = OUT / "cef_corp_action_events.csv"            # tracked: EDGAR facts + parsed terms
EVENTS_FULL_CSV = OUT / "cef_corp_action_events_full.csv"  # gitignored: + CRSP-joined levels
CENSUS_CSV = OUT / "cef_corp_action_census.csv"            # tracked: one row per event type
SUMMARY_JSON = OUT / "cef_corp_action_summary.json"
COND_TENDER_CSV = OUT / "conditional_tender_census.csv"

SCOPE_START = pd.Timestamp("2010-01-01")
TIME_HOLDOUT = pd.Timestamp("2023-01-01")
FIT_YEARS = 13                      # 2010..2022: the denominator of every "per year" rate in the rank
CRSP_LAST = pd.Timestamp("2024-12-31")  # names/delistings/distributions end here (R2 mirror)
ADV_SESSIONS = 63                   # a quarter of sessions before the announcement, as the live ADV filter
PAIR_RATIO = (0.5, 1.5)             # price/NAV outside this is a mis-parse, not a discount
PERIOD_MAX_STALE_DAYS = 400         # a period-end older than this is not "before the announcement"
RIGHTS_XCHECK_DAYS = 60
MON = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
       r"\s+\d{1,2}\s*,\s*\d{4}")
NUM = r"\d{1,4}(?:,\d{3})*\.\d{1,4}"

# ----------------------------------------------------------------- guards

class HoldoutError(AssertionError):
    pass


def assert_pre_holdout(when, what: str) -> None:
    """Raise if a LEVEL statistic is about to use an event dated on or after 2023-01-01."""
    t = pd.Timestamp(when)
    if pd.isna(t) or t >= TIME_HOLDOUT:
        raise HoldoutError(f"{what}: {when} is not before {TIME_HOLDOUT.date()} (time holdout)")


# -------------------------------------------------------------- text helpers

def parse_date(s: str) -> pd.Timestamp:
    """'January 6, 2014' (any spacing around the comma) -> Timestamp; raises on anything else."""
    s2 = re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", s.strip()))
    return pd.Timestamp(datetime.strptime(s2, "%B %d, %Y"))


def to_float(s: str) -> float:
    return float(s.replace(",", ""))


def span(text: str, m: re.Match, pad: int = 0, cap: int = 320) -> str:
    """The matched text (a source span), whitespace-collapsed and capped."""
    s = text[max(0, m.start() - pad): m.end() + pad]
    return re.sub(r"\s+", " ", s)[:cap]


# ------------------------------------------------------- sponsor and asset

SPONSORS = [
    (r"NUVEEN", "Nuveen"),
    (r"BLACKROCK|MUNIYIELD|MUNIHOLDINGS|MUNIVEST|MUNIENHANCED|MUNIASSETS|MUNI ?INTERMEDIATE|"
     r"CORPORATE HIGH YIELD FUND|DEBT STRATEGIES FUND|SENIOR HIGH INCOME|ENHANCED GOVERNMENT FUND", "BlackRock"),
    (r"EATON VANCE", "Eaton Vance"),
    (r"PIMCO", "PIMCO"),
    (r"INVESCO|VAN KAMPEN", "Invesco"),
    (r"MORGAN STANLEY", "Morgan Stanley"),
    (r"\bD ?W ?S\b|DEUTSCHE|SCUDDER|RREEF", "DWS"),        # CRSP spaces initials: "D W S"
    (r"WESTERN ASSET|LEGG MASON|\bL ?M ?P\b|CLEARBRIDGE", "Legg Mason"),
    (r"FRANKLIN|TEMPLETON", "Franklin Templeton"),
    (r"ABERDEEN|ABRDN", "abrdn"),
    (r"COHEN ?& ?STEERS", "Cohen & Steers"),
    (r"CALAMOS", "Calamos"),
    (r"FIRST TRUST", "First Trust"),
    (r"PIONEER", "Pioneer"),
    (r"\bMFS\b|M F S", "MFS"),
    (r"ALLIANCE ?BERNSTEIN|ALLIANCE (?:CA|NY|NATIONAL|WORLD|CALIFORNIA|NEW YORK)|^AB ", "AllianceBernstein"),
    (r"GABELLI|GAMCO|\bGDL\b", "Gabelli"),
    (r"JOHN HANCOCK|HANCOCK", "John Hancock"),
    (r"NEUBERGER", "Neuberger Berman"),
    (r"DOUBLELINE", "DoubleLine"),
    (r"BLACKSTONE|\bGSO\b", "Blackstone"),
    (r"\bKKR\b", "KKR"),
    (r"APOLLO", "Apollo"),
    (r"\bARES\b", "Ares"),
    (r"OXFORD (?:LANE|SQUARE)", "Oxford"),
    (r"PRUDENTIAL|\bPGIM\b", "PGIM"),
    (r"MACQUARIE", "Macquarie"),
    (r"TORTOISE", "Tortoise"),
    (r"KAYNE", "Kayne Anderson"),
    (r"GOLDMAN SACHS", "Goldman Sachs"),
    (r"VIRTUS|ZWEIG|DUFF ?& ?PHELPS", "Virtus"),
    (r"PUTNAM", "Putnam"),
    (r"JPMORGAN|J\.P\. MORGAN|PACHOLDER", "JPMorgan"),
    (r"FEDERATED", "Federated"),
    (r"DREYFUS|BNY MELLON|MELLON", "BNY Mellon"),
    (r"LIBERTY ALL[- ]STAR", "ALPS"),
    (r"ROYCE", "Royce"),
    (r"COLUMBIA|SELIGMAN|TRI-CONTINENTAL", "Columbia"),
    (r"HIGHLAND|NEXPOINT", "Highland/NexPoint"),
    (r"SABA CAPITAL", "Saba"),
    (r"HERZFELD", "Herzfeld"),
    (r"CLOUGH", "Clough"),
    (r"\bVOYA\b|\bING\b", "Voya"),
    (r"SUNAMERICA|SUN AMERICA", "SunAmerica"),
    (r"WELLS FARGO|EVERGREEN|ALLSPRING", "Wells Fargo/Allspring"),
    (r"RIVERNORTH", "RiverNorth"),
    (r"FLAHERTY", "Flaherty & Crumrine"),
    (r"MAINSTAY|NEW YORK LIFE|\bNYLI\b", "New York Life"),
    (r"CUSHING|\bNXG\b", "Cushing/NXG"),
    (r"SALIENT", "Salient"),
    (r"BROOKFIELD|CENTER COAST", "Brookfield"),
    (r"PROSPECT CAPITAL", "Prospect"),
    (r"GOLUB", "Golub"),
    (r"\bFS\b|FS KKR|FS INVESTMENT", "FS"),
    (r"THL CREDIT|FIRST EAGLE", "First Eagle"),
    (r"\bMVC\b", "MVC"),
    (r"FIRSTHAND", "Firsthand"),
    (r"SPECIAL OPPORTUNITIES FUND|BULLDOG", "Bulldog"),
    (r"VIRTUS|THE ZWEIG", "Virtus"),
    (r"ADAMS (?:EXPRESS|DIVERSIFIED|NATURAL)", "Adams"),
    (r"SWISS HELVETIA|TOTAL RETURN SECURITIES FUND", "Schroders/SWZ"),
]
_SPONSOR_RES = [(re.compile(p), s) for p, s in SPONSORS]


def sponsor_of(name: str) -> tuple[str, bool]:
    """(sponsor, recognised). An unrecognised fund is its own sponsor (name upper-cased).

    Recognising more sponsors can only MERGE groups, so the fallback errs
    towards more independent groups; the share of unrecognised events is
    reported with every group count so the reader can see how much that is.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"no fund name to read a sponsor from: {name!r}")
    u = name.upper()
    for rx, s in _SPONSOR_RES:
        if rx.search(u):
            return s, True
    return re.sub(r"\s+", " ", u.strip()), False


# Asset class from the fund's name, then the hedge ETF for that class. Order
# matters: "MUNICIPAL HIGH INCOME" is muni, "FLOATING RATE INCOME" is loans.
ASSET_RULES = [
    (r"MUNI|MUNICIPAL|TAX[- ]FREE|TAX[- ]EXEMPT|QUALITY INCOME MUN|INSURED|INVT? QU?A?LI?TY? MU", "muni"),
    (r"FLOAT|FLTG|SENIOR (?:LOAN|INCOME|FLOATING|FLTG|HIGH)|\bLOAN|PRIME RATE|\bCLO\b", "loans"),
    (r"MORTGAGE|\bMBS\b|GOVERNMENT|GOV'?T|INTERMARKET|MULTI[- ]?MARKET|MULTI[- ]?SECTOR|STRATEGIC INCOME|DIVERSIFIED INCOME", "multisector"),
    (r"HIGH YIELD|HIGH INCOME|HI YLD|CREDIT|INCOME OPPORTUNIT|CORPORATE (?:BOND|INCOME)|BOND|FIXED INCOME|DEBT|INCOME FUND|INCOME TRUST", "high_yield"),
    (r"EMERGING MARKETS? (?:DEBT|INCOME|LOCAL)|GLOBAL (?:HIGH )?INCOME|WORLD INCOME|EMERGING MARKETS INCOME", "em_debt"),
    (r"PREFERRED|PFD", "preferred"),
    (r"CONVERTIBLE|CONV ", "convertible"),
    (r"\bMLP\b|M L P|MIDSTREAM|ENERGY|PIPELINE|INFRASTR|INFRA\b|POWER", "energy_mlp"),
    (r"REAL ESTATE|\bREIT|RL EST|REALTY", "reit"),
    (r"UTILIT", "utilities"),
    (r"CHINA|GREATER CHINA|HONG KONG", "eq_china"),
    (r"INDIA", "eq_india"),
    (r"JAPAN", "eq_japan"),
    (r"KOREA", "eq_korea"),
    (r"TAIWAN", "eq_taiwan"),
    (r"GERMANY|GERMAN|EUROPE|EUROPEAN|IRELAND|IRISH|SWISS|ITALY|FRANCE|SPAIN|IBERIA|UNITED KINGDOM|\bUK\b|CENTRAL EUROPE", "eq_europe"),
    (r"LATIN|BRAZIL|MEXICO|CHILE|ARGENTINA|IBERO", "eq_latam"),
    (r"ASIA|PACIFIC|THAI|MALAYSIA|INDONESIA|SINGAPORE|PHILIPPINE|VIETNAM|TURK|RUSSIA|AFRICA|EMERGING|FRONTIER|GLOBAL EMRG|EMRG", "eq_em"),
    (r"BIOTECH|HEALTH|TECHNOLOG|SCIENCE", "eq_sector"),
    (r"GLOBAL|WORLD|INTERNATIONAL|INTL", "eq_global"),
]
_ASSET_RES = [(re.compile(p), a) for p, a in ASSET_RULES]

# The hedge for each class: the most liquid US-listed ETF on the same exposure
# (by the 2026-10-08 universe map's ADV where the map has it). Equity classes
# default to the broad index of the region. This is a MAPPING, chosen before
# any return was looked at; whether it hedges well is a return question and is
# NOT answered here (zero trials) -- see the note's gaps.
HEDGE_ETF = {
    "muni": "MUB", "loans": "BKLN", "multisector": "AGG", "high_yield": "HYG", "em_debt": "EMB",
    "preferred": "PFF", "convertible": "CWB", "energy_mlp": "AMLP", "reit": "VNQ", "utilities": "XLU",
    "eq_china": "FXI", "eq_india": "INDA", "eq_japan": "EWJ", "eq_korea": "EWY", "eq_taiwan": "EWT",
    "eq_europe": "VGK", "eq_latam": "ILF", "eq_em": "EEM", "eq_sector": "XLV", "eq_global": "ACWI",
    "eq_us": "SPY",
}
# The muni fallback is not a hedge of the same exposure: a duration hedge only.
# It is used solely to state what is shortable if no muni ETF is.
MUNI_DURATION_FALLBACK = "IEF"

# Alternates on the SAME exposure, read at Alpaca beside each primary. Added
# 2026-10-18 after the 2026-10-15 read showed MUB `shortable: False`: a hedge
# question decided by one symbol's flag on one day is decided by the wrong
# thing. The lists were written before any alternate was read, and no return
# was looked at (zero trials). An event is hedgeable on the read date if its
# primary OR any alternate is shortable; the first shortable symbol in
# (primary,) + alternates is the hedge named, with its 2022 ADV beside it.
HEDGE_ALTERNATES = {
    "muni": ("VTEB", "TFI", "HYD", "SUB"), "loans": ("SRLN",), "multisector": ("BND",),
    "high_yield": ("JNK", "USHY"), "em_debt": ("VWOB", "PCY"), "preferred": ("PGX",), "convertible": ("ICVT",),
    "energy_mlp": ("MLPA",), "reit": ("IYR", "XLRE"), "utilities": ("VPU",), "eq_china": ("MCHI",),
    "eq_india": ("EPI",), "eq_japan": ("BBJP",), "eq_korea": ("FLKR",), "eq_taiwan": ("FLTW",),
    "eq_europe": ("IEUR", "EZU"), "eq_latam": ("FLLA",), "eq_em": ("VWO", "IEMG"), "eq_sector": ("IBB",),
    "eq_global": ("VT",), "eq_us": ("IVV", "VOO"),
}


def hedge_choice(primary: str, flags: pd.DataFrame) -> tuple[str | None, bool]:
    """(the first shortable symbol among the primary and its declared alternates, primary shortable?).

    `flags` is indexed by symbol with `found` and `shortable` (Alpaca, one day).
    A symbol absent from `flags` raises: every candidate is read, so a missing
    one is a bug, not "not shortable".
    """
    cls = next((c for c, e in HEDGE_ETF.items() if e == primary), None)
    if cls is None:
        raise KeyError(f"{primary} is not a primary hedge ETF")
    cands = (primary,) + HEDGE_ALTERNATES.get(cls, ())
    missing = [c for c in cands if c not in flags.index]
    if missing:
        raise KeyError(f"hedge candidates not read at Alpaca: {missing}")
    ok = {c: bool(flags.loc[c, "found"]) and bool(flags.loc[c, "shortable"]) for c in cands}
    return next((c for c in cands if ok[c]), None), ok[primary]


def asset_class_of(name: str) -> str:
    """Asset class from a fund name; "eq_us" when nothing matches (a US equity fund)."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"no fund name: {name!r}")
    u = name.upper()
    for rx, a in _ASSET_RES:
        if rx.search(u):
            return a
    return "eq_us"


TERM_RE = re.compile(r"\bTERM\b|\bTARGET\b|\b20[0-4]\d\b|\b19\d\d\b|\bTM TR\b|\bTRM\b|\bTM\b")


def is_term_fund(name: str) -> bool:
    """A name with a term marker: 'TERM', 'TARGET', a year (BLACKROCK MUN 2018 TERM TR)."""
    return bool(TERM_RE.search(name.upper()))


# ------------------------------------------------------ tender offer parsing

_PCT_NAV_RE = re.compile(
    r"(?P<k>\d{2,3}(?:\.\d+)?)\s?%\s+of\s+(?:the\s+|its\s+)?(?:Fund[’'`]?s\s+|Trust[’'`]?s\s+)?"
    r"(?:net\s+asset\s+value|NAV)", re.I)
_LISTED_RE = re.compile(
    r"(?:traded|listed|trade|trades)\s+on\s+the\s+(?:New\s+York\s+Stock\s+Exchange|NYSE|NASDAQ|Nasdaq|"
    r"American\s+Stock\s+Exchange|NYSE\s+(?:Amex|MKT|American))", re.I)
_TICKER_RE = re.compile(r"(?:under|with)\s+the\s+(?:ticker\s+|trading\s+)?symbol\s*[\"“”'‘’]?\s?(?P<t>[A-Z]{2,5})\b")
_DUTCH_RE = re.compile(
    r"not\s+(?:greater|more)\s+than\s+\$\s?(?P<hi>\d+\.\d+)\s+(?:nor|and\s+not)\s+less\s+than\s+\$\s?(?P<lo>\d+\.\d+)"
    r"|modified\s+[\"“]?Dutch\s+auction", re.I)
_FIXED_RE = re.compile(r"(?:at\s+a\s+(?:cash\s+)?(?:purchase\s+)?price\s+of|for)\s+\$\s?(?P<p>\d{1,4}\.\d{2})\s+per\s+(?:share|Share)", re.I)
_SIZE_RES = [
    re.compile(r"up\s+to\s+(?P<p>\d{1,3}(?:\.\d+)?)\s?%\s+of\s+(?:its|the)\s+(?:Fund[’'`]?s\s+|Trust[’'`]?s\s+)?"
               r"(?:issued\s+and\s+)?outstanding", re.I),
    # "4,579,480 shares of common stock of the Fund (approximately 15% of the total ...)". A bare
    # "(20%)" anywhere read a tax rate (JPT 2022) and uuencoded image bytes (IRL 2012) as offer sizes.
    re.compile(r"\d{1,3}(?:,\d{3})+\s+(?:[A-Za-z’'`]+\s+){0,8}\(\s*(?:approximately\s+)?(?P<p>\d{1,3}(?:\.\d+)?)\s?%"
               r"\s*(?:of\s+[^)]{0,80})?\)", re.I),
    re.compile(r"(?P<p>\d{1,3}(?:\.\d+)?)\s?%\s+of\s+the\s+(?:total\s+number\s+of\s+)?(?:its\s+)?(?:issued\s+and\s+)?"
               r"(?:outstanding\s+)?(?:common\s+)?shares\s+(?:then\s+)?outstanding", re.I),
]
# Shares sought: "Up to 4,579,480 Shares of Common Stock"; "repurchase up to 4,829,532
# (approximately 15%) of its issued and outstanding common shares".
_SOUGHT_RE = re.compile(
    r"up\s+to\s+(?P<n>\d{1,3}(?:,\d{3})+)\s+(?:\(\s*(?:approximately\s+)?\d{1,3}(?:\.\d+)?\s?%\s*\)\s+)?"
    r"(?:of\s+(?:its|the\s+Fund[’'`]?s)\s+)?(?:issued\s+and\s+outstanding\s+)?(?:common\s+)?(?:Shares|shares)", re.I)
_EXPIRE_RE = re.compile(r"(?:WILL\s+)?EXPIRE[S]?\s+AT\s+.{0,90}?\bON\s+(?:\w+DAY\s*,\s+)?(?P<d>" + MON + ")", re.I)

# The NAV on a named date, as offer documents state it (in order of preference).
_NAV_STMT_RES = [
    # "... by $14.52 (95% of the net asset value per share of $15.28 as of the close ... on January 6, 2014)"
    ("fee_nav", re.compile(
        r"(?P<k>\d{2,3}(?:\.\d+)?)\s?%\s+of\s+(?:the\s+)?(?:Fund[’'`]?s\s+)?(?:net\s+asset\s+value|NAV)\s+"
        r"(?:\(\s*[\"“]?NAV[\"”]?\s*\)\s+)?per\s+(?:common\s+)?share\s+of\s+\$\s?(?P<nav>" + NUM + r")\s+"
        r"(?:as\s+of|on|at)\s+(?:the\s+close\s+of\s+[^.;()]{0,110}?\bon\s+)?(?P<d>" + MON + ")", re.I)),
    # "... based upon a price per share of $18.44, which represents 99% of the net asset value per share on April 23, 2010"
    ("fee_price", re.compile(
        r"\$\s?(?P<price>" + NUM + r")\s*,?\s*(?:\(\s*|which\s+represents\s+|being\s+|equal\s+to\s+|or\s+)?"
        r"(?P<k>\d{2,3}(?:\.\d+)?)\s?%\s+of\s+(?:the\s+)?(?:Fund[’'`]?s\s+)?(?:net\s+asset\s+value|NAV)\s+per\s+"
        r"(?:common\s+)?share\s+(?:as\s+of|on|at)\s+(?:the\s+close\s+of\s+[^.;()]{0,110}?\bon\s+)?(?P<d>" + MON + ")",
        re.I)),
    # "... the net asset value per share as of July 31, 2026 of $16.40"
    ("nav_asof", re.compile(
        r"net\s+asset\s+value\s+per\s+(?:common\s+)?share\s+(?:as\s+of|on)\s+(?P<d>" + MON + r")\s+(?:of|was)\s+\$\s?"
        r"(?P<nav>" + NUM + ")", re.I)),
    # "The NAV per share as of the close ... on January 6, 2014 was $15.28 and the last reported sale price ... was $13.72"
    ("nav_sentence", re.compile(
        r"(?:net\s+asset\s+value|NAV)\s+per\s+(?:common\s+)?share\s+(?:as\s+of|on|at)\s+(?:the\s+close\s+of\s+"
        r"[^.;()]{0,110}?\bon\s+)?(?P<d>" + MON + r")\s+was\s+\$\s?(?P<nav>" + NUM + r")", re.I)),
    # "On June 19, 2012, the Fund's net asset value per share was $4.36 ..."
    ("on_date", re.compile(
        r"\bOn\s+(?P<d>" + MON + r")\s*,?\s+the\s+(?:last\s+(?:reported|calculated)\s+)?(?:Fund[’'`]?s\s+)?"
        r"(?:net\s+asset\s+value|NAV)\s+(?:per\s+(?:common\s+)?share\s+)?was\s+\$\s?(?P<nav>" + NUM + ")", re.I)),
]


def _mode(vals: list[float]) -> float | None:
    """The most frequent value; a tie goes to the one that appears FIRST (vals are in document
    order). The first draft broke ties by the smallest value, and IRL 2012's offer ("up to 15%",
    then "a second tender offer for up to 5%") read as 5%."""
    if not vals:
        return None
    c = pd.Series(vals).value_counts()
    top = set(c[c == c.max()].index)
    return float(next(v for v in vals if v in top))


def parse_tender_offer(text: str) -> dict:
    """Terms of an issuer tender offer, from its plain text (the complete submission).

    Returns a dict with: listed, ticker, basis ('pct_nav' | 'dutch' | 'fixed' |
    'none'), k_pct (price as % of NAV, the MODE over every statement, so one
    stray "95% of NAV" in a history section cannot set it), k_span, size_pct and
    its span, expire (Timestamp or None), and the NAV statement (nav_date, nav,
    nav_kind, nav_span) or None. Every value carries the text it came from.
    """
    out: dict = {"listed": bool(_LISTED_RE.search(text))}
    tm = _TICKER_RE.search(text)
    out["ticker"] = tm.group("t") if tm else None
    out["listed"] = out["listed"] or out["ticker"] is not None
    ks = [(float(m.group("k")), m) for m in _PCT_NAV_RE.finditer(text) if 90.0 <= float(m.group("k")) <= 100.5]
    k = _mode([v for v, _ in ks])
    out["k_pct"] = k
    out["k_span"] = span(text, next(m for v, m in ks if v == k), pad=60) if k is not None else None
    dm = _DUTCH_RE.search(text)
    fm = _FIXED_RE.search(text)
    if k is not None:
        out["basis"] = "pct_nav"
    elif dm:
        out["basis"] = "dutch"
    elif fm:
        out["basis"] = "fixed"
    else:
        out["basis"] = "none"
    out["dutch_lo"] = float(dm.group("lo")) if dm and dm.group("lo") else None
    out["dutch_hi"] = float(dm.group("hi")) if dm and dm.group("hi") else None
    out["fixed_price"] = float(fm.group("p")) if (fm and out["basis"] == "fixed") else None
    out["basis_span"] = span(text, dm or fm, pad=40) if out["basis"] in ("dutch", "fixed") else out["k_span"]
    sizes = []
    for rx in _SIZE_RES:
        for m in rx.finditer(text):
            v = float(m.group("p"))
            if 0.5 <= v <= 100.0:
                sizes.append((v, m))
    sz = _mode([v for v, _ in sizes])
    out["size_pct"] = sz
    out["size_span"] = span(text, next(m for v, m in sizes if v == sz), pad=60) if sz is not None else None
    so = [(to_float(m.group("n")), m) for m in _SOUGHT_RE.finditer(text)]
    sv = _mode([v for v, _ in so])
    out["sought_shares"] = sv
    out["sought_span"] = span(text, next(m for v, m in so if v == sv), pad=30) if sv is not None else None
    em = _EXPIRE_RE.search(text)
    out["expire"] = parse_date(em.group("d")) if em else None
    out.update(parse_nav_statement(text))
    out["stated_price"], out["stated_price_span"] = stated_price_on(text, out["nav_date"])
    return out


_STATED_PX_RE = re.compile(
    r"(?:last\s+(?:reported\s+)?(?:sale|sales|closing)\s+price|closing\s+(?:market\s+)?price|market\s+price)\s+"
    r"(?:per\s+(?:common\s+)?share\s+)?(?:of\s+the\s+(?:common\s+)?shares\s+)?"
    r"(?:on\s+the\s+(?:NYSE|New\s+York\s+Stock\s+Exchange|NASDAQ|Nasdaq)\s+)?(?:was|of)\s+\$\s?(?P<p>\d{1,4}\.\d{2,4})",
    re.I)


def stated_price_on(text: str, nav_date) -> tuple[float | None, str | None]:
    """A market price the offer prints for its NAV date ("On June 19, 2012 ... NAV was $4.36 and the
    last reported sale price was $3.92"), within 420 characters after a mention of that date.

    An INDEPENDENT source for the price leg of disc_post: CRSP supplies the close
    that is used; this is only compared with it (agreement to the cent is counted).
    """
    if nav_date is None or pd.isna(nav_date):
        return None, None
    d = pd.Timestamp(nav_date)
    ds = re.escape(f"{d.strftime('%B')} {d.day}, {d.year}").replace(r"\ ", r"\s+").replace(",", r"\s*,")
    for m in re.finditer(ds, text):
        w = text[m.start(): m.start() + 420]
        pm = _STATED_PX_RE.search(w)
        if pm:
            return float(pm.group("p")), re.sub(r"\s+", " ", w[: pm.end()])[-260:]
    return None, None


def parse_nav_statement(text: str) -> dict:
    """The first NAV-on-a-named-date statement, by `_NAV_STMT_RES` preference.

    'fee_price' states a price and its percentage of NAV, so NAV = price / k.
    Returns nav_kind None if no pattern matches: a stated gap, never a guess.
    """
    for kind, rx in _NAV_STMT_RES:
        m = rx.search(text)
        if not m:
            continue
        gd = m.groupdict()
        if gd.get("nav"):
            nav = to_float(gd["nav"])
        else:
            nav = to_float(gd["price"]) / (float(gd["k"]) / 100.0)
        return {"nav_kind": kind, "nav_date": parse_date(gd["d"]), "nav": round(nav, 6), "nav_span": span(text, m)}
    return {"nav_kind": None, "nav_date": None, "nav": None, "nav_span": None}


_SHARES_N = r"(?P<n>\d{1,3}(?:,\d{3})+|\d{5,})(?:\.\d+)?"
# "[^.;]" alone stops at the dot of "60.34% of the Fund's outstanding stock" and
# missed every sentence that states the tendered share as a decimal percentage
# (the 2026-10-15 build lost 49 of 129 result filings to this and its siblings).
_NOSTOP = r"(?:[^.;]|\.(?=\d))"
_TENDERED_RE = re.compile(
    _SHARES_N + r"\s+(?:of\s+the\s+Fund[’'`]?s\s+)?(?:common\s+)?(?:Shares|shares)\b" + _NOSTOP + r"{0,160}?\b"
    r"(?:were|had\s+been|was)\s+(?:validly\s+|properly\s+|duly\s+|and\s+|not\s+withdrawn\s+)*tendered", re.I)
_TENDERED2_RE = re.compile(
    r"(?:total|aggregate)\s+of\s+" + _SHARES_N + r"\s+(?:common\s+)?(?:Shares|shares)" + _NOSTOP + r"{0,80}?"
    r"(?:were|had\s+been)\s+(?:validly\s+|properly\s+|duly\s+)*tendered", re.I)
_ACCEPTED_RES = [
    re.compile(
        r"(?:accepted|purchased|repurchased)\s*,?\s+(?:subject\s+to\s+adjustment\s+for\s+fractional\s+shares[^,]{0,30},\s+)?"
        r"(?:for\s+(?:payment|purchase)\s+)?(?:all\s+|a\s+(?:total|aggregate)\s+of\s+|an\s+aggregate\s+of\s+)?"
        + _SHARES_N + r"\s+(?:of\s+the\s+)?(?:common\s+)?(?:Shares|shares)", re.I),
    # "... and 4,829,532 of those Common Shares were accepted for repurchase"
    re.compile(_SHARES_N + r"\s+of\s+those\s+(?:common\s+)?(?:Shares|shares)\s+were\s+accepted", re.I),
    # "... and 21,576,552 Shares were accepted for repurchase"; "7,796,312 Shares have been accepted"
    re.compile(_SHARES_N + r"\s+(?:common\s+)?(?:Shares|shares)\s+(?:were|have\s+been|has\s+been)\s+accepted", re.I),
]
_PRORATION_RES = [
    re.compile(r"pro[- ]?ration\s+(?:factor|ratio|percentage)\s+(?:of\s+|was\s+|is\s+|equal\s+to\s+)?(?:approximately\s+)?"
               r"(?P<p>\d{1,3}(?:\.\d+)?)\s?%", re.I),
    re.compile(r"(?P<p>\d{1,3}(?:\.\d+)?)\s?%\s+of\s+(?:the\s+)?(?:Fund[’'`]?s\s+)?(?:common\s+)?(?:Shares|shares)\s+"
               r"(?:properly\s+|validly\s+|duly\s+)*tendered", re.I),
    # (A third pattern -- the first percentage within 300 characters after a
    # "Pro-Ration Factor" header -- was removed 2026-10-18: it read a table by
    # position with nothing to check it against. Tables go through `_table_row`.)
]
# Words that say an offer was NOT filled whole. Where any appears, no "all accepted"
# phrase is believed (a release can say "not all shares that were tendered were accepted").
_OVERSUB_RE = re.compile(r"over-?\s?subscribed|pro[- ]?rata|pro[- ]?rat(?:ed|ion)", re.I)
_ALL_ACCEPTED_RES = [
    # "All Shares validly tendered and not withdrawn were accepted"
    re.compile(r"(?<!not )(?:all|each\s+of\s+the)\s+(?:Shares|shares)\s+(?:that\s+were\s+)?(?:validly\s+|properly\s+)*tendered\s+"
               r"(?:and\s+not\s+(?:properly\s+)?withdrawn\s+)?(?:were|have\s+been|will\s+be)\s+accepted", re.I),
    # "has accepted for purchase all shares properly tendered"; "elected to purchase all shares tendered"
    re.compile(r"(?<!not )(?:accepted|purchased|elected\s+to\s+purchase|will\s+purchase)\s+(?:for\s+(?:payment|purchase)\s+)?"
               r"all\s+(?:of\s+the\s+)?(?:Shares|shares)\s+(?:that\s+were\s+)?(?:validly\s+|properly\s+|duly\s+)*tendered", re.I),
    # "The Fund accepted all properly tendered and not withdrawn shares"
    re.compile(r"(?<!not )(?:accepted|purchased)\s+all\s+(?:validly\s+|properly\s+|duly\s+)*tendered\s+"
               r"(?:and\s+not\s+(?:properly\s+)?withdrawn\s+)?(?:Shares|shares)", re.I),
    # Nuveen term-fund elective tenders at 100% of NAV: "Properly tendered shares will be repurchased"
    re.compile(r"(?<!not )\b[Pp]roperly\s+tendered\s+shares\s+will\s+be\s+repurchased"),
]
_PCT_TENDERED_RE = re.compile(
    r"(?P<p>\d{1,3}(?:\.\d+)?)\s?(?:%|percent)\s+of\s+(?:the\s+)?(?:Fund[’'`]?s|fund[’'`]?s|Trust[’'`]?s|its)\s+"
    r"(?:issued\s+and\s+)?(?:outstanding\s+)?(?:common\s+)?(?:shares|stock|Shares|Common\s+Shares)"
    r"(?:\s+of\s+common\s+stock)?(?:\s+outstanding)?" + _NOSTOP + r"{0,60}?(?:were|was)\s+(?:validly\s+|properly\s+|duly\s+)*tendered"
    r"|tendered,?\s+representing\s+approximately\s+(?P<p2>\d{1,3}(?:\.\d+)?)\s?(?:%|percent)\s+of\s+the\s+fund[’'`]?s\s+"
    r"(?:common\s+)?shares\s+outstanding", re.I)
TABLE_TOL = 0.005    # a results-table row is believed only if accepted/tendered matches its printed factor


def _table_row(text: str, ticker: str | None) -> tuple[float, float, re.Match] | None:
    """(tendered, accepted, match) from a results table, or None.

    With a ticker: the row that starts with it ("TYG 5,215,915 596,395 0.1144").
    Without: the first "N1 N2 f" triple within 700 characters after a
    "Pro-Ration Factor" header. Either is believed only when N2/N1 equals the
    printed factor f (a decimal or a percentage) within TABLE_TOL -- the table
    checks itself, so a row of another fund or a column of prices cannot pass
    as a pro-ration by accident of position.
    """
    trip = (r"(?P<t>\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s+(?P<a>\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s+"
            r"(?P<f>0?\.\d{2,6}|1\.0+|\d{1,3}(?:\.\d+)?\s?%)")
    cands = []
    if ticker:
        cands += list(re.finditer(r"\b" + re.escape(ticker) + r"\s+" + trip, text))
    h = re.search(r"pro[- ]?ration\s+factor", text, re.I)
    if h and not cands:
        cands += list(re.finditer(trip, text[h.end(): h.end() + 700]))[:1]
    for m in cands:
        tt, aa = to_float(m.group("t")), to_float(m.group("a"))
        f = m.group("f")
        fv = float(f.rstrip("% ").strip()) / 100.0 if "%" in f else float(f)
        if 0 < aa <= tt and abs(aa / tt - fv) <= TABLE_TOL:
            return tt, aa, m
    return None


_EXCH_TICKER_RE = re.compile(
    r"\((?:NYSE|NYSE\s+American|NYSE\s+MKT|NYSE\s+Amex|Nasdaq|NASDAQ|AMEX)\s*:\s*(?P<t>[A-Z]{2,5})\s*\)")
_ITEM_BLOCK_RE = re.compile(r"Rule\s+13e-4\(c\)\(4\)", re.I)
ITEM_BLOCK_CHARS = 900


def other_fund_tickers(text: str, own: str | None, cef_tickers: set) -> set:
    """Tickers printed as "(NYSE: XXX)" that belong to OTHER closed-end funds (CRSP share code 14/44
    at any date). A sponsor's own listing ("Invesco Ltd. (NYSE: IVZ)") is not a fund and does not count.

    When the fund's own ticker is unknown (a dead fund whose offer printed none), one fund ticker in
    the release is presumed to be its own: only two or more make a joint release. Without this the
    Malaysia, Thai and Turkish funds' own single-fund releases read as joint ones."""
    found = {m.group("t") for m in _EXCH_TICKER_RE.finditer(text)} & set(cef_tickers)
    if own is None:
        return found if len(found) >= 2 else set()
    return found - {own}


def parse_tender_result(text: str, ticker: str | None = None, sought_shares: float | None = None,
                        multi_fund: bool = False) -> dict:
    """Pro-ration from a final SC TO-I/A, in order of directness:

      1. accepted / tendered, both stated as share counts (accepted <= tendered);
      2. a results-table row that checks itself (`_table_row`);
      3. a stated factor, the fund's own ticker first ("53.59% of the DHG shares
         that were tendered", a two-fund release), then the generic phrasings;
      4. shares SOUGHT by the offer / shares tendered, where the release says
         the offer was oversubscribed but prints no accepted count (the fund
         buys what it offered for; Rule 13e-4(f)(1)(ii) lets it buy up to 2% of
         outstanding more, so this can understate a slightly);
      5. 1.0 where the filing says every tendered share was accepted AND says
         nothing of oversubscription or pro-ration;
      else None (a stated gap).

    MULTI-FUND RELEASES (`multi_fund`, decided by the caller from
    `other_fund_tickers`). A sponsor's joint release prints every fund's
    numbers, and the generic patterns take whichever fund comes first: the
    2026-10-15 build gave VLT the numbers of VTA, and IDE the table row of IGA.
    In such a filing only FUND-ANCHORED reads are believed: the fund's own
    Rule 13e-4(c)(4) item block (the amendment's body, before any exhibit), its
    ticker's table row, a factor or share counts printed against its ticker,
    and (5), which says the same of every fund. Anything else is a gap.

    CONFLICTS. Where a count-based a and a stated factor in the same filing
    differ by more than 0.05, neither is believed (IRL 2017 prints accepted =
    tendered beside "approximately 64.75% ... have been accepted").

    Independently, `pct_tendered` (the % of outstanding shares tendered, where
    stated, and only outside multi-fund releases) is returned for the caller's
    second method. A factor outside (0, 1] raises: it is a mis-read.
    """
    oversub = bool(_OVERSUB_RE.search(text))
    out = {"tendered": None, "accepted": None, "proration": None, "proration_span": None, "proration_how": None,
           "pct_tendered": None, "pct_tendered_span": None, "multi_fund": bool(multi_fund)}
    blk_m = _ITEM_BLOCK_RE.search(text)
    block = text[blk_m.end(): blk_m.end() + ITEM_BLOCK_CHARS] if blk_m else ""

    def counts(src: str):
        t = _TENDERED_RE.search(src) or _TENDERED2_RE.search(src)
        a = next((m for m in (rx.search(src) for rx in _ACCEPTED_RES) if m), None)
        return t, a

    def ticker_counts():
        if not ticker:
            return None, None
        tk = re.escape(ticker)
        t = re.search(_SHARES_N + r"\s+shares\s+of\s+" + tk + r"[’'`]s\s+common\s+stock" + _NOSTOP + r"{0,200}?tendered",
                      text, re.I)
        a = re.search(r"\b" + tk + r"\s+has\s+accepted\s+" + _SHARES_N, text)
        return t, a

    if multi_fund:
        t, a = counts(block) if block else (None, None)
        src = block
        if not (t and a):
            t2, a2 = ticker_counts()
            if t2 and a2:
                t, a, src = t2, a2, text
        if t is None:
            t = ticker_counts()[0] or (counts(block)[0] if block else None)
            src = block if (t and block and t.group(0) in block) else text
    else:
        t, a = counts(text)
        src = text
        pt = _PCT_TENDERED_RE.search(text)
        if pt:
            out["pct_tendered"] = float(pt.group("p") or pt.group("p2"))
            out["pct_tendered_span"] = span(text, pt, pad=20)
    out["tendered"] = to_float(t.group("n")) if t else None
    out["accepted"] = to_float(a.group("n")) if a else None
    if out["tendered"] and out["accepted"] and out["accepted"] <= out["tendered"] * 1.0001:
        out["proration"] = out["accepted"] / out["tendered"]
        out["proration_span"] = span(src, t, pad=40) + " | " + span(src, a, pad=40)
        out["proration_how"] = "accepted/tendered" + (" (fund-anchored, multi-fund release)" if multi_fund else "")
    if out["proration"] is None:
        row = _table_row(text, ticker) if not multi_fund else (_table_row(text, ticker) if ticker else None)
        if row and (not multi_fund or row[2].group(0).startswith(ticker)):
            tt, aa, m = row
            out.update(tendered=tt, accepted=aa, proration=aa / tt, proration_span=span(text, m, pad=20),
                       proration_how="results-table row (self-consistent)" + (f", ticker {ticker}" if ticker
                                                                               and m.group(0).startswith(ticker) else ""))
    tick_rx = ([re.compile(r"(?P<p>\d{1,3}(?:\.\d+)?)\s?%\s+of\s+the\s+" + re.escape(ticker) + r"\s+(?:common\s+)?shares\s+"
                           r"(?:that\s+were\s+)?(?:properly\s+|validly\s+|duly\s+)*tendered", re.I)] if ticker else [])
    stated = None
    for rx in tick_rx + ([] if multi_fund else _PRORATION_RES):
        m = rx.search(text)
        if m:
            stated = (float(m.group("p")) / 100.0, m)
            break
    if out["proration"] is not None and stated is not None and abs(out["proration"] - stated[0]) > 0.05:
        out.update(proration=None, proration_how="conflicting statements in the filing (a gap)",
                   proration_span=out["proration_span"] + " | " + span(text, stated[1], pad=40))
        return out
    if out["proration"] is None and out["proration_how"] is None and stated is not None:
        out["proration"] = stated[0]
        out["proration_span"] = span(text, stated[1], pad=60)
        out["proration_how"] = "stated factor"
    if out["proration"] is None and out["proration_how"] is None and oversub and out["tendered"] and sought_shares \
            and sought_shares < out["tendered"]:
        out["proration"] = sought_shares / out["tendered"]
        out["proration_span"] = span(src, t, pad=40) + f" | sought {sought_shares:,.0f} (offer)"
        out["proration_how"] = "shares sought (offer) / shares tendered (oversubscribed)"
    if out["proration"] is None and out["proration_how"] is None and not oversub:
        m = next((m for m in (rx.search(text) for rx in _ALL_ACCEPTED_RES) if m), None)
        if m:
            out["proration"] = 1.0
            out["proration_span"] = span(text, m, pad=40)
            out["proration_how"] = "all accepted"
    if out["proration"] is None and out["proration_how"] is None and multi_fund:
        out["proration_how"] = "multi-fund release, no fund-anchored statement (a gap)"
    if out["proration"] is not None and not (0.0 < out["proration"] <= 1.0):
        raise ValueError(f"pro-ration {out['proration']} outside (0, 1]: {out['proration_span']}")
    return out


# ------------------------------------------------------------ Form N-8F

_N8F_OPTIONS = ("Merger", "Liquidation", "Abandonment of Registration", "Election of status as a Business Development Company")
_CHECKED = r"(?:\[\s*[xX✓✔√]\s*\]|☒|☑|þ|ý|ü|■|\(\s*[xX]\s*\)|\b[xX]\b)"
_UNCHECKED = r"(?:\[\s*\]|☐|¨|o\b|q\b|\(\s*\)|_+)"


def parse_n8f(text: str) -> dict:
    """Reason, board-vote date, holder-vote date, distribution dates and survivor from a Form N-8F.

    Item 1's boxes are read in a window that starts at "Reason fund is applying
    to deregister" and ends before Item 2. Exactly one option must carry a
    check mark; zero or two is 'unknown' (stated), never guessed.
    """
    out = {"reason": "unknown", "board_date": None, "holder_date": None, "dist_first": None, "dist_last": None,
           "survivor": None, "reason_span": None, "board_span": None, "dist_span": None}
    m = re.search(r"Reason\s+fund\s+is\s+applying\s+to\s+deregister", text, re.I)
    if m:
        win = text[m.end(): m.end() + 900]
        win = re.split(r"\b2\s*\.\s+Name\s+of\s+fund", win, flags=re.I)[0]
        found = []
        for opt in _N8F_OPTIONS:
            o = re.search(r"(?P<box>" + _CHECKED + r"|" + _UNCHECKED + r")\s*" + re.escape(opt), win, re.I)
            if o and re.fullmatch(_CHECKED, o.group("box").strip()):
                found.append(opt)
        if len(found) == 1:
            out["reason"] = {"Merger": "merger", "Liquidation": "liquidation",
                             "Abandonment of Registration": "abandonment"}.get(found[0], "bdc_election")
        out["reason_span"] = re.sub(r"\s+", " ", win[:420])
    date_rx = r"(?P<d>" + MON + r"|\d{1,2}/\d{1,2}/\d{2,4})"
    b = re.search(r"date\s+on\s+which\s+the\s+board\s+vote\s+took\s+place\s*:?\s*" + date_rx, text, re.I)
    if b:
        out["board_date"] = _any_date(b.group("d"))
        out["board_span"] = span(text, b)
    h = re.search(r"date\s+on\s+which\s+the\s+shareholder\s+vote\s+took\s+place\s*:?\s*" + date_rx, text, re.I)
    if h:
        out["holder_date"] = _any_date(h.group("d"))
    d = re.search(r"list\s+the\s+date\(?s\)?\s+on\s+which\s+the\s+fund\s+made\s+those\s+distributions\s*:?(?P<w>.{0,400})",
                  text, re.I | re.S)
    if d:
        w = re.split(r"\(b\)|Were\s+the\s+distributions", d.group("w"))[0]
        ds = [_any_date(x.group(0)) for x in re.finditer(MON + r"|\d{1,2}/\d{1,2}/\d{2,4}", w)]
        ds = [x for x in ds if x is not None]
        if ds:
            out["dist_first"], out["dist_last"] = min(ds), max(ds)
            out["dist_span"] = re.sub(r"\s+", " ", w)[:240]
    s = re.search(r"name\s+of\s+the\s+fund\s+surviving\s+the\s+Merger\s*:?\s*(?P<n>.{0,160}?)\s*\(?b\)?\s*State\s+the",
                  text, re.I | re.S)
    if s:
        out["survivor"] = re.sub(r"\s+", " ", s.group("n")).strip(" :;.") or None
    return out


def _any_date(s: str):
    s = s.strip()
    try:
        return parse_date(s)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return pd.Timestamp(year=y, month=int(m.group(1)), day=int(m.group(2)))
        except ValueError:
            return None
    return None


# --------------------------------------- period-end NAV beside a CRSP close

_NAV_ROW_RE = re.compile(r"(?:net\s+asset\s+value|\bNAV\b)[^$\d]{0,70}?(?:end\s+of\s+(?:the\s+)?(?:period|year)|ending)", re.I)
_MKT_ROW_RE = re.compile(
    r"(?:market\s+(?:price|value)|share\s+price|closing\s+(?:market\s+)?price|price\s+per\s+share)"
    r"[^$\d]{0,70}?(?:end\s+of\s+(?:the\s+)?(?:period|year)|ending)", re.I)
_NAV_LABEL_RE = re.compile(r"net\s+asset\s+value|\bNAV\b|Ending\s+NAV", re.I)
_MKT_LABEL_RE = re.compile(r"market\s+(?:price|value)|share\s+price|closing\s+price", re.I)
_NUM_TOKEN_RE = re.compile(r"(?<![\d.,])\d{1,4}\.\d{2,4}(?![\d])")
# Nuveen's "share information" table: column per fund, a NAV row then a price row,
# no "end of period" words: "JMF JMLP NAV $ 9.98 $ 6.92 Share price $ 9.19 $ 6.24".
# Also Tortoise's highlights: "Net asset value per common share (2) 20.67 ... 38.68 Market value
# per common share (2) 17.74 ... 32.47" (one column per period).
_LABEL_TAIL = r"(?:\s+per\s+(?:common\s+)?share)?(?:\s*\(\s*\d\s*\))?"
_ROW2_RE = re.compile(
    r"(?:\bNAV\b|Net\s+asset\s+value)" + _LABEL_TAIL + r"\s*(?P<navs>(?:\$?\s*\d{1,4}\.\d{2,4}\s*){1,8})"
    r"(?:Share\s+price|Market\s+price|Market\s+value|Closing\s+price)" + _LABEL_TAIL + r"\s*"
    r"(?P<pxs>(?:\$?\s*\d{1,4}\.\d{2,4}\s*){1,8})", re.I)
_ONLY_NUMBERS_RE = re.compile(r"[\s$\d.,()%*\-–]*")
# Pair layout: the two numbers must be ADJACENT -- nothing but spaces, "$" or a footnote mark
# between them. Anything looser read "from $16.31 on October 31, 2010 to $12.60" (a price change)
# and "$ 6.19 (NAV) -8.11 %† $ 5.51" (a return) as NAV-beside-price: 13 of 35 pair reads in the
# 2026-10-18 audit.
_ADJACENT_RE = re.compile(r"[\s$*†‡]*")
_MONTH_ROW_RE = re.compile(r"\b\d{1,2}/\d{2}\s+\$?\s*\d")          # "5/16 11.08 12.24 ...": a monthly price table
_SENTENCE_RES = [
    # "As of June 30, 2010, the Fund's NAV was $14.26, and its market price was $13.40."
    re.compile(r"\bNAV\s+(?:per\s+share\s+)?was\s+\$\s?(?P<nav>\d{1,4}\.\d{2,4})\s*,?\s+and\s+(?:its|the)\s+"
               r"(?:market|share)\s+price\s+(?:per\s+share\s+)?was\s+\$\s?(?P<px>\d{1,4}\.\d{2,4})", re.I),
    # "Performance Snapshot ... Price Per Share ... $9.72 (NAV) 32.2 % 0.1 % $8.50 (Market Price)"
    re.compile(r"\$\s?(?P<nav>\d{1,4}\.\d{2,4})\s*\(NAV\)[^$]{0,80}\$\s?(?P<px>\d{1,4}\.\d{2,4})\s*\(Market", re.I),
]


def nav_beside_price(text: str, close: float) -> dict | None:
    """The NAV that a shareholder report prints beside a market price equal to `close`.

    `close` is CRSP's close on the report's period-end (or the last session
    before it). Every occurrence of it, to the cent, is examined:

      row layout  (BlackRock, JPMorgan, Eaton Vance): "Net asset value, end of
                  period $ 7.86 $ 6.97 ... Market value per share, end of
                  period $ 7.20 $ 6.07 ..." -> the price is column j of the
                  market row; the NAV is column j of the NAV row above it.
      row2 layout (Nuveen's share-information table, one column per fund:
                  "JMF JMLP NAV $ 9.98 $ 6.92 Share price $ 9.19 $ 6.24"): the
                  NAV is the same column of the NAV row.
      pair layout (fund-facts boxes "NAV ... Market Price ... $ 7.86 $
                  7.20"): the NAV is the number printed immediately before the
                  price, with a NAV label within 700 characters before -- and
                  NOT when that number sits in a price-labelled row (the
                  2026-10-15 build read JMF's share price 9.19 as JMLP's NAV
                  from the row2 table above and called JMLP's discount -32%).

    The first occurrence that yields a NAV with price/NAV inside PAIR_RATIO is
    returned with its layout and span; None if none does. The exact-cent match
    against an independent source (CRSP) is what makes a multi-fund report
    safe: another fund's table does not print this fund's closing price.
    """
    tok = f"{close:.2f}"
    for m2 in _ROW2_RE.finditer(text):
        navs = _NUM_TOKEN_RE.findall(m2.group("navs"))
        pxs = _NUM_TOKEN_RE.findall(m2.group("pxs"))
        if len(navs) == len(pxs) and tok in pxs:
            nav = to_float(navs[pxs.index(tok)])
            if nav > 0 and PAIR_RATIO[0] < close / nav < PAIR_RATIO[1]:
                return {"nav": nav, "layout": "row2", "span": re.sub(r"\s+", " ", m2.group(0))[:320]}
    for rx in _SENTENCE_RES:
        for ms in rx.finditer(text):
            if ms.group("px") == tok:
                nav = to_float(ms.group("nav"))
                if nav > 0 and PAIR_RATIO[0] < close / nav < PAIR_RATIO[1]:
                    return {"nav": nav, "layout": "sentence", "span": re.sub(r"\s+", " ", ms.group(0))[:320]}
    for m in re.finditer(r"(?<![\d.,])" + re.escape(tok) + r"(?![\d])", text):
        pre = text[max(0, m.start() - 900): m.start()]
        rows = list(_MKT_ROW_RE.finditer(pre))
        if rows:
            last = rows[-1]
            seg = pre[last.end():]
            if not _NAV_LABEL_RE.search(seg) and len(seg) < 260:
                j = len(_NUM_TOKEN_RE.findall(seg))
                navrows = list(_NAV_ROW_RE.finditer(pre[: last.start()]))
                if navrows:
                    nseg = pre[navrows[-1].end(): last.start()]
                    navs = _NUM_TOKEN_RE.findall(nseg)
                    if len(navs) > j:
                        nav = to_float(navs[j])
                        if nav > 0 and PAIR_RATIO[0] < close / nav < PAIR_RATIO[1]:
                            return {"nav": nav, "layout": "row", "span": re.sub(r"\s+", " ", text[max(0, m.start() - 260): m.end() + 10])}
        nums = list(_NUM_TOKEN_RE.finditer(pre[-40:]))
        mk = list(_MKT_LABEL_RE.finditer(pre[-700:]))
        tail = re.sub(r"^" + _LABEL_TAIL, "", pre[-700:][mk[-1].end():], flags=re.I) if mk else ""
        in_price_row = bool(mk) and bool(_ONLY_NUMBERS_RE.fullmatch(tail))
        adjacent = bool(nums) and bool(_ADJACENT_RE.fullmatch(pre[-40:][nums[-1].end():]))
        month_row = bool(nums) and bool(_MONTH_ROW_RE.search(pre[max(0, len(pre) - 40 + nums[-1].start() - 200):]))
        if nums and adjacent and not month_row and not in_price_row and _NAV_LABEL_RE.search(pre[-700:]) and mk:
            nav = to_float(nums[-1].group(0))
            if nav > 0 and PAIR_RATIO[0] < close / nav < PAIR_RATIO[1] and abs(nav - close) > 1e-9:
                return {"nav": nav, "layout": "pair", "span": re.sub(r"\s+", " ", text[max(0, m.start() - 260): m.end() + 10])}
    return None


# --------------------------------------------------------------- activists

ACTIVIST_RE = re.compile(
    r"SABA CAPITAL|KARPUS|BULLDOG|GOLDSTEIN PHILLIP|DAKOS|OPPORTUNITY PARTNERS|FULL VALUE PARTNERS|"
    r"SPECIAL OPPORTUNITIES FUND|CITY OF LONDON|WESTERN INVESTMENT|SIT INVESTMENT|OCEAN CAPITAL|RIVERNORTH|"
    r"RELATIVE VALUE PARTNERS|ANCORA|LAZARD ASSET|1607 CAPITAL|ALMITAS|AMSTER HOWARD|MATISSE|LAXEY|"
    r"ELLIOTT (?:ASSOCIATES|MANAGEMENT|INVESTMENT)", re.I)


def is_activist(filer: str) -> bool:
    """A known closed-end-fund activist (by filer name on the 13D's index row).

    The list is the set of CEF activists named in ICI's activism briefs and in
    this repo's notes (Saba, Karpus, Bulldog, City of London, Western
    Investment, ...), extended by reading the filer list of 13Ds on fund-set
    CIKs (2026-10-15). Banks and insurers that file 13Ds as holders of a fund's
    VRDP/ARPS preferreds (Bank of America, Wells Fargo, TD, JPMorgan) are NOT
    activists and are excluded by construction.
    """
    return bool(ACTIVIST_RE.search(filer or ""))


# ------------------------------------------------------------ the arithmetic

def accepted_slice_spread(k_pct: float, disc: float) -> float:
    """Gross spread on the shares a tender ACCEPTS: (k x NAV) / price - 1.

    `disc` is price/NAV - 1 (negative for a discount). k_pct=98, disc=-0.10
    gives 0.98/0.90 - 1 = 8.9%. Terms and a level; no realised price.
    """
    if not (0 < k_pct <= 105):
        raise ValueError(f"k_pct {k_pct}")
    if not (PAIR_RATIO[0] - 1 < disc < PAIR_RATIO[1] - 1):
        raise ValueError(f"discount {disc}")
    return (k_pct / 100.0) / (1.0 + disc) - 1.0


def position_spread(k_pct: float, disc: float, a: float) -> float:
    """Terms-implied gross on the WHOLE position: a x accepted-slice spread.

    The (1 - a) of shares a tender returns are assumed to be worth what they
    cost (residual discount unchanged). That is an assumption about a level,
    stated, and it is generous: ICI's activist-tender figure has the excess
    discount widening from -0.2% during the tender to -3.3% the year after
    (docs/REFERENCES.md §5). The residual's fate is a return question (a trial).
    """
    if not (0 < a <= 1):
        raise ValueError(f"pro-ration {a}")
    return a * accepted_slice_spread(k_pct, disc)


def giveback_spread(k_pct: float, disc_post: float, disc_pre: float, a: float) -> float:
    """A harsher terms-implied position spread: the residual gives the announcement narrowing back.

    Entry at disc_post; a of the position exits at k x NAV; the (1 - a) residual
    is valued at the PRE-announcement discount level, (1 + disc_pre) /
    (1 + disc_post) - 1 per unit. Levels only, no realised price: it states what
    the terms imply if the discount returns to where it stood before the
    announcement (the direction ICI's post-tender figure points, §5). disc_pre
    is a stale period-end level, so this is a sensitivity, never a gate.
    """
    if not (0 < a <= 1):
        raise ValueError(f"pro-ration {a}")
    if not (PAIR_RATIO[0] - 1 < disc_pre < PAIR_RATIO[1] - 1):
        raise ValueError(f"discount {disc_pre}")
    return a * accepted_slice_spread(k_pct, disc_post) + (1.0 - a) * ((1.0 + disc_pre) / (1.0 + disc_post) - 1.0)


def post_discount(nav: float, nav_date, ann_date, close: float | None) -> tuple[float | None, str]:
    """(disc_post, reason): the offer-stated NAV against CRSP's close on the SAME date, kept
    only if that date is on or after the announcement.

    An offer document's NAV is often dated a few days BEFORE the episode's
    first EDGAR filing (33 of 130 in the 2026-10-15 build). A level from before
    the announcement is not one an entry after it could trade at, so it is not
    disc_post; it is returned as None with the reason, and the any-date figure
    is kept separately (`disc_navdate`) as a labelled sensitivity.
    """
    if close is None:
        return None, "no CRSP close on the NAV date"
    d = close / nav - 1.0
    if not (PAIR_RATIO[0] - 1 < d < PAIR_RATIO[1] - 1):
        return None, "price/NAV outside PAIR_RATIO (a mis-parse)"
    if pd.Timestamp(nav_date) < pd.Timestamp(ann_date):
        return None, "NAV date before the announcement"
    return d, "ok"


def nav_exit_spread(disc: float) -> float:
    """Liquidation, termination or open-ending: the whole position exits at NAV. 1/(1+disc) - 1."""
    return accepted_slice_spread(100.0, disc)


# =========================================================================
# THE BUILD (network through the shared clients; every cache is gitignored)
# =========================================================================

CENSUS_CACHE = OUT / "_cache_census"
EXTRA_FORMS = frozenset({"SC 13D", "SCHEDULE 13D", "N-CSR", "N-CSRS", "485APOS", "485BPOS", "N-1A",
                         "497", "424B2", "424B3", "424B5"})
EXIT_CODES = "4xx; 2xx, 3xx and 5xx with no successor permno"


# Slower than the client's default 8/s on purpose. The SEC's limit is per IP
# ("10 requests/second", docs/REFERENCES.md §12g), and on 2026-10-15 several
# sprint jobs ran EDGAR fetchers from this desk's address at the same time; each
# at 8/s together exceed it, and a 403 lock-out stops all of them. 2/s keeps this
# census's share small. Most documents come from the cache anyway.
CENSUS_MIN_INTERVAL_S = 0.5


def _client(offline: bool):
    from scripts.data.edgar_client import EdgarClient, RateLimiter
    return EdgarClient(offline=offline, limiter=RateLimiter(min_interval=CENSUS_MIN_INTERVAL_S))


TRANSPORT_RETRY_S = (10.0, 30.0, 90.0)


def fetch_raw(client, cik: int, accession: str, sleep=None) -> str:
    """One filing's complete-submission text through the shared EDGAR client.

    The client backs off on EDGAR's refusals (403/429/503) but lets a transport
    failure (a read time-out) propagate. A census of ~1,000 documents meets a
    few, so the SAME request is retried after TRANSPORT_RETRY_S pauses, one
    request at a time (the client's rate limit still applies), and the last
    failure is raised. Nothing is skipped silently.
    """
    import time
    import requests
    from scripts.data.edgar_client import filing_txt_url
    url = filing_txt_url(int(cik), accession)
    sleep = sleep or time.sleep
    for i, pause in enumerate((0.0,) + TRANSPORT_RETRY_S):
        if pause:
            sleep(pause)
        try:
            return client.get_text(url)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if i == len(TRANSPORT_RETRY_S):
                raise
    raise AssertionError("unreachable")


_UUENCODED_RE = re.compile(r"(?ms)^begin [0-7]{3} \S+[ \t]*$.*?^end[ \t]*$")


def strip_binary(raw: str) -> str:
    """Remove uuencoded attachments (images, PDFs) from a complete-submission text.

    EDGAR's .txt carries every attachment; binary ones are uuencoded between
    "begin 644 <name>" and "end". Left in, their bytes are text to a regex:
    "(2%)" inside a JPEG became an offer size (IRL 2012).
    """
    return _UUENCODED_RE.sub(" ", raw)


def fetch_plain(client, cik: int, accession: str) -> str:
    from scripts.events.conditional_tender_census import plain
    return plain(strip_binary(fetch_raw(client, cik, accession)))


def load_edgar() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The fetcher's filings and episodes tables (plan 0.7). Raises if absent: rebuild with
    `python3 scripts/data/fetch_edgar_events.py --offline`."""
    from scripts.data import fetch_edgar_events as fe
    for p in (fe.FILINGS_OUT, fe.EPISODES_OUT):
        if not p.exists():
            raise FileNotFoundError(f"{p} missing: run scripts/data/fetch_edgar_events.py (--offline if cached)")
    f = pd.read_csv(fe.FILINGS_OUT, parse_dates=["date_filed"])
    e = pd.read_csv(fe.EPISODES_OUT, parse_dates=["first_date", "commence_date", "last_date", "dereg_date"])
    return f, e


def index_rows(client, today: date) -> pd.DataFrame:
    """EXTRA_FORMS rows of every quarterly master index 2008-Q1 -> today, all filers.

    The fetcher keeps only its event forms; this census also needs Schedules
    13D, shareholder reports (N-CSR/N-CSRS: period-end NAVs), open-end
    registrations (conversions) and prospectus supplements (rights offerings).
    Parsed with the fetcher's own validating parser; cached as parquet by the
    last quarter read.
    """
    from scripts.data import fetch_edgar_events as fe
    qs = fe.quarters(fe.LOOKBACK_START, today)
    CENSUS_CACHE.mkdir(parents=True, exist_ok=True)
    p = CENSUS_CACHE / f"index_extra_{qs[-1][0]}Q{qs[-1][1]}_{today.isoformat()}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    frames = []
    for y, q in qs:
        url = fe.INDEX_URL.format(y=y, q=q)
        text = client.get_text(url, max_age_s=None if fe.quarter_is_closed(y, q, today) else fe.DAY)
        frames.append(fe.parse_master_index(text, label=f"{y}Q{q}", keep_forms=EXTRA_FORMS))
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(p)
    return df


def universe_ids(client, nm: pd.DataFrame) -> tuple[set, set, list]:
    """(CIKs, permnos, tickers) of the 44 `cef_universe.csv` funds: the counts-only set.

    CIKs from the SEC ticker file (fetched by the EDGAR fetcher, cached), permnos
    from `crsp_events.universe_permnos` (which raises if a ticker matches
    nothing). Both are used, so an event is excluded whichever key it carries.
    """
    from scripts.data import fetch_edgar_events as fe
    from scripts.events import crsp_events as ce
    u = ce.universe()
    j = client.get_json(fe.TICKERS_URL, max_age_s=None)
    tk = pd.DataFrame(j["data"], columns=j["fields"])
    ciks = set(int(c) for c in tk[tk["ticker"].isin(set(u["ticker"]))]["cik"])
    missing = set(u["ticker"]) - set(tk["ticker"])
    if missing:
        raise LookupError(f"universe tickers not in the SEC ticker file: {sorted(missing)}")
    perms = set(p for v in ce.universe_permnos(nm).values() for p in v)
    return ciks, perms, sorted(u["ticker"])


class CrspMap:
    """EDGAR fund (name at a date, optional ticker) -> CRSP permno, and back.

    Ticker first: a CRSP name record carrying the ticker on that date, with a
    loose name check (score >= 0.5) so a reassigned ticker cannot map one fund
    onto another. Else the merger matcher's rule on names
    (`edgar_merger_dates`: score >= MIN_SCORE, margin >= MIN_MARGIN) among
    share-code 14/44 records in force within 30 days of the date. Unmatched is
    returned as None with the reason; nothing is guessed.
    """

    def __init__(self, nm: pd.DataFrame):
        from scripts.events.edgar_merger_dates import name_tokens
        self.nm = nm.copy()
        self.nm["tok"] = self.nm["comnam"].fillna("").map(lambda s: name_tokens(s) if s.strip() else ())
        self.cef = self.nm[self.nm["shrcd"].isin((14, 44))]

    def permno(self, edgar_name: str, ticker: str | None, when) -> tuple[int | None, str]:
        from scripts.events.edgar_merger_dates import MIN_MARGIN, MIN_SCORE, name_score, name_tokens
        when = pd.Timestamp(when)
        et = name_tokens(edgar_name)
        if isinstance(ticker, str) and ticker.strip():
            for t in ticker.split(";"):
                r = self.nm[(self.nm["ticker"] == t.strip()) & (self.nm["namedt"] <= when) & (self.nm["nameendt"] >= when)]
                ps = r["permno"].unique()
                if len(ps) == 1:
                    sc = max(name_score(x, et) for x in r["tok"] if x)
                    if sc >= 0.5:
                        return int(ps[0]), f"ticker {t.strip()} (name score {sc:.2f})"
        w = pd.Timedelta(days=30)
        c = self.cef[(self.cef["namedt"] <= when + w) & (self.cef["nameendt"] >= when - w)]
        if c.empty:
            return None, "no CRSP CEF names in force"
        sc = c.assign(s=[name_score(x, et) if x else -9 for x in c["tok"]]).sort_values("s", ascending=False)
        sc = sc.drop_duplicates("permno")
        b = sc.iloc[0]
        s2 = float(sc.iloc[1]["s"]) if len(sc) > 1 else -np.inf
        if b["s"] < MIN_SCORE:
            return None, f"best name score {b['s']:.2f} < {MIN_SCORE}"
        if b["s"] - s2 < MIN_MARGIN:
            return None, f"ambiguous name match (margin {b['s'] - s2:.3f})"
        return int(b["permno"]), f"name (score {b['s']:.2f})"


# ------------------------------------------------------------------ tenders

def tender_events(client, filings: pd.DataFrame, episodes: pd.DataFrame, cef_tickers: set) -> pd.DataFrame:
    """One row per tender episode 2010+, classified from its own offer document.

    type: nav_tender (listed, common, k% of NAV), fixed_price_tender (listed,
    common, $ price or Dutch range), or not_in_scope with the reason
    (communications only, unlisted, preferred class, no price basis).
    """
    from scripts.events.g6_corporate_action_shorts import classify_tender
    from scripts.events.conditional_tender_census import plain
    from scripts.data.edgar_client import filing_txt_url
    ep = episodes[(episodes["kind"] == "tender") & (episodes["first_date"] >= SCOPE_START)]
    ft = filings[filings["kind"] == "tender"]
    rows = []
    for e in ep.itertuples():
        g = ft[(ft["cik"] == e.cik) & (ft["date_filed"] >= e.first_date) & (ft["date_filed"] <= e.last_date)]
        g = g.sort_values("date_filed")
        first = g[g["form"].isin(("SC TO-I", "SC TO-T"))]
        fin = g[g["form"].isin(("SC TO-I/A", "SC TO-T/A"))]
        name_then = g["company"].iloc[0]
        r = {"type": None, "cik": int(e.cik), "fund": name_then, "ticker_now": e.ticker_now,
             "ann_date": e.first_date, "ann_form": e.first_form, "ann_accession": e.first_accession,
             "end_date": e.last_date, "doc_accession": None, "result_accession": None, "scope_reason": None}
        if first.empty:
            r.update(type="not_in_scope", scope_reason="no SC TO-I/TO-T (communications only)")
            rows.append(r)
            continue
        f0 = first.iloc[0]
        r["doc_accession"], r["doc_date"] = f0["accession"], f0["date_filed"]
        raw = fetch_raw(client, int(e.cik), f0["accession"])
        cls = classify_tender(raw)
        p = parse_tender_offer(plain(strip_binary(raw)))
        r.update({"offer_form": f0["form"], "class": cls, **{k: p[k] for k in (
            "listed", "ticker", "basis", "k_pct", "k_span", "basis_span", "dutch_lo", "dutch_hi", "fixed_price",
            "size_pct", "size_span", "sought_shares", "sought_span", "expire", "nav_kind", "nav_date", "nav",
            "nav_span", "stated_price", "stated_price_span")}})
        if f0["form"] == "SC TO-T":
            r.update(type="not_in_scope", scope_reason="third-party tender (SC TO-T)")
        elif cls == "preferred":
            r.update(type="not_in_scope", scope_reason="preferred-share tender")
        elif not p["listed"]:
            r.update(type="not_in_scope", scope_reason="not exchange-listed (interval or private fund)")
        elif p["basis"] == "pct_nav":
            r["type"] = "nav_tender"
        elif p["basis"] in ("dutch", "fixed"):
            r["type"] = "fixed_price_tender"
        else:
            r.update(type="not_in_scope", scope_reason="no price basis found in the offer")
        if r["type"] in ("nav_tender", "fixed_price_tender") and len(fin):
            f1 = fin.iloc[-1]
            r["result_accession"] = f1["accession"]
            own = p["ticker"] or (e.ticker_now.split(";")[0] if isinstance(e.ticker_now, str) else None)
            rt = fetch_plain(client, int(e.cik), f1["accession"])
            others = other_fund_tickers(rt, own, cef_tickers)
            res = parse_tender_result(rt, ticker=own, sought_shares=p["sought_shares"], multi_fund=bool(others))
            r["result_other_funds"] = ";".join(sorted(others)) or None
            r.update({k: res[k] for k in ("tendered", "accepted", "proration", "proration_span", "proration_how",
                                          "pct_tendered", "pct_tendered_span", "multi_fund")})
            # The second method: offer size (% of outstanding) / % of outstanding tendered, capped at 1.
            # Different numbers from the same two filings; reported as agreement, never substituted.
            if res["pct_tendered"] and p["size_pct"]:
                r["proration_xcheck"] = min(1.0, p["size_pct"] / res["pct_tendered"])
            if res["proration"] is None and p["size_pct"] == 100.0:
                r.update(proration=1.0, proration_how="offer for 100% of shares: no pro-ration possible",
                         proration_span=p["size_span"])
        rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------- liquidation / open-end

def exit_events(client, filings: pd.DataFrame, idx: pd.DataFrame, nm: pd.DataFrame, dl: pd.DataFrame,
                names: pd.DataFrame) -> pd.DataFrame:
    """Funds that left the exchange at (or near) NAV: liquidations, term terminations, open-endings.

    Start from CRSP: every delisting 2010-01-01..2024-12-31 of a permno whose
    last name record is share code 14/44, with code 4xx (liquidated), or 2xx /
    3xx / 5xx with no successor permno (merged into, exchanged for, or became
    something CRSP does not list). The 3xx case is not hypothetical: the Taiwan
    Greater China Fund's 2011 conversion to an open-end fund is CRSP code 332
    with no successor (read 2026-10-15). Mergers into another LISTED fund (2xx with a successor) are the
    merger pair's census, not this one. Each is matched to a CIK and its N-8F
    read; a fund with no N-8F that later files open-end registrations was
    converted in place.
    """
    from scripts.events import crsp_events as ce
    from scripts.events.edgar_merger_dates import match_cik
    last = ce.last_name(nm)[["permno", "shrcd", "comnam", "ticker"]]
    d = dl.merge(last, on="permno", how="left")
    d = d[(d["dlstdt"] >= SCOPE_START) & (d["dlstdt"] <= CRSP_LAST) & d["shrcd"].isin((14, 44))]
    succ = d["nwperm"].fillna(0) > 0
    code = d["dlstcd"] // 100
    d = d[(code == 4) | (code.isin((2, 3, 5)) & ~succ)].copy()
    n8f = filings[filings["form"] == "N-8F"]
    oe = idx[idx["form"].isin(("485APOS", "485BPOS", "N-1A"))]
    rows = []
    for r in d.itertuples():
        rec = {"permno": int(r.permno), "crsp_name": r.comnam, "dlstdt": r.dlstdt, "dlstcd": int(r.dlstcd),
               "type": None,
               "cik": None, "fund": None, "match": None, "n8f_accession": None}
        m = match_cik(r.comnam, names, r.dlstdt - pd.Timedelta(days=730), r.dlstdt + pd.Timedelta(days=60))
        rec["match"] = m["status"]
        if m["status"] == "matched":
            cik = int(m["cik"])
            rec.update(cik=cik, fund=m["edgar_name"])
            g = n8f[(n8f["cik"] == cik) & (n8f["date_filed"] >= r.dlstdt - pd.Timedelta(days=400))
                    & (n8f["date_filed"] <= r.dlstdt + pd.Timedelta(days=900))].sort_values("date_filed")
            if len(g):
                rec["n8f_accession"] = g.iloc[0]["accession"]
                rec.update(parse_n8f(fetch_plain(client, cik, g.iloc[0]["accession"])))
            later_oe = oe[(oe["cik"] == cik) & (oe["date_filed"] >= r.dlstdt - pd.Timedelta(days=200))]
            rec["files_open_end_forms_after"] = bool(len(later_oe))
            v = filings[(filings["cik"] == cik) & filings["kind"].isin(("vote", "contest", "merger", "current"))
                        & (filings["date_filed"] >= r.dlstdt - pd.Timedelta(days=500)) & (filings["date_filed"] <= r.dlstdt)]
            rec["first_proxy_date"] = v["date_filed"].min() if len(v) else None
        rows.append(rec)
    out = pd.DataFrame(rows)
    out["type"] = [classify_exit(r) for r in out.to_dict("records")]
    out["ann_date"] = [exit_announcement(r) for r in out.to_dict("records")]
    out["ann_how"] = [exit_announcement(r, how=True) for r in out.to_dict("records")]
    out["end_date"] = [r["dist_last"] if isinstance(r.get("dist_last"), pd.Timestamp) else r["dlstdt"]
                       for r in out.to_dict("records")]
    return out


SURVIVOR_INTERVAL_RE = re.compile(r"INTERVAL|CREDIT OPPORTUNITIES FUND$|FLOATING RATE OPPORTUNITIES|PRIVATE", re.I)


def classify_exit(r: dict) -> str:
    """liquidation | term_termination | open_ending | merger_into_unlisted | unresolved.

    The N-8F's checked box decides between merger and liquidation. CRSP's code
    decides only where no N-8F was found or its box could not be read
    (`reason` None or "unknown"), and the event row keeps `reason` so the
    reader can see which rows rest on CRSP alone. A merger whose survivor's name
    marks an interval or private fund is NOT an open-ending: an interval fund
    repurchases 5-25% a quarter, not the whole position at NAV.
    """
    reason = r.get("reason") if isinstance(r.get("reason"), str) else None
    name = r.get("fund") if isinstance(r.get("fund"), str) else (r.get("crsp_name") or "")
    code = int(r["dlstcd"]) // 100
    if reason == "liquidation" or (reason in (None, "unknown") and code == 4):
        return "term_termination" if is_term_fund(name) or is_term_fund(r.get("crsp_name") or "") else "liquidation"
    if reason == "merger":
        surv = r.get("survivor") if isinstance(r.get("survivor"), str) else ""
        if not surv or SURVIVOR_INTERVAL_RE.search(surv):
            return "merger_into_unlisted"
        return "open_ending"
    if r.get("files_open_end_forms_after") is True and code in (3, 5):
        return "open_ending"
    return "unresolved"


def exit_announcement(r: dict, how: bool = False):
    """The announcement proxy: the N-8F board-vote date (Item 15(a)) if it precedes
    delisting; else the first proxy/8-K/merger filing in the 500 days before
    delisting; else None.

    The fallback can be a routine annual-meeting proxy filed BEFORE the real
    announcement, so it is labelled for what it bounds: the hold measured from
    it is an upper bound, and disc_pre measured before it is staler than it
    need be (never later than the announcement on that account). It is not an
    upper bound on the announcement date itself."""
    b = r.get("board_date")
    if isinstance(b, pd.Timestamp) and b <= r["dlstdt"] and b >= r["dlstdt"] - pd.Timedelta(days=900):
        return "N-8F board vote" if how else b
    p = r.get("first_proxy_date")
    if isinstance(p, pd.Timestamp):
        return "first proxy/8-K/merger filing in 500d before delisting (hold is an upper bound)" if how else p
    return None if not how else "none found"


# ------------------------------------------------------------------ activists

def activist_events(idx: pd.DataFrame, fund_ciks: set, filings: pd.DataFrame) -> pd.DataFrame:
    """Initial Schedules 13D on fund-set CIKs whose filer is a known CEF activist.

    The index lists a 13D under the subject AND each filer; the subject is the
    fund-set CIK, the filer the other CIK(s) of the same accession. One row per
    (activist, fund) first filing in a run (a second 13D by the same filer on
    the same fund within 365 days is the same campaign).
    """
    d = idx[idx["form"].isin(("SC 13D", "SCHEDULE 13D"))]
    sub = d[d["cik"].isin(fund_ciks)]
    acc = d[d["accession"].isin(set(sub["accession"]))]
    rows = []
    for a, g in acc.groupby("accession"):
        funds = g[g["cik"].isin(fund_ciks)]
        filers = g[~g["cik"].isin(fund_ciks)]
        act = [n for n in filers["company"] if is_activist(n)]
        if not act or funds.empty:
            continue
        for f in funds.itertuples():
            rows.append({"type": "activist_13d", "cik": int(f.cik), "fund": f.company, "ann_date": f.date_filed,
                         "activist": act[0], "accession": a})
    out = pd.DataFrame(rows).sort_values("ann_date")
    tk = filings.dropna(subset=["ticker_now"]).drop_duplicates("cik").set_index("cik")["ticker_now"]
    out["ticker_now"] = out["cik"].map(tk)
    keep, seen = [], {}
    for r in out.itertuples():
        k = (r.cik, _activist_key(r.activist))
        if k in seen and (r.ann_date - seen[k]).days <= 365:
            keep.append(False)
        else:
            keep.append(True)
        seen[k] = r.ann_date
    return out[keep].reset_index(drop=True)


def _activist_key(name: str) -> str:
    m = ACTIVIST_RE.search(name or "")
    k = m.group(0).upper() if m else (name or "").upper()
    return {"GOLDSTEIN PHILLIP": "BULLDOG", "DAKOS": "BULLDOG", "OPPORTUNITY PARTNERS": "BULLDOG",
            "FULL VALUE PARTNERS": "BULLDOG", "SPECIAL OPPORTUNITIES FUND": "BULLDOG"}.get(k, k)


def contest_events(episodes: pd.DataFrame) -> pd.DataFrame:
    e = episodes[(episodes["kind"] == "contest") & (episodes["first_date"] >= SCOPE_START)]
    return pd.DataFrame({"type": "proxy_contest", "cik": e["cik"].astype(int), "fund": e["company_last"],
                         "ann_date": e["first_date"], "accession": e["first_accession"], "ticker_now": e["ticker_now"]})


# ------------------------------------------------------------ rights offerings

_RIGHTS_PRICE_RE = re.compile(
    r"(?P<k>\d{2,3}(?:\.\d+)?)\s?%\s+of\s+the\s+(?:volume[- ]weighted\s+)?average\s+of\s+the\s+(?:last\s+reported\s+sales?|"
    r"closing|reported\s+closing)\s+prices?", re.I)
_RIGHTS_FLOOR_RE = re.compile(
    r"(?:less\s+than|below|floor\s+of|not\s+be\s+(?:less|lower)\s+than)\s+(?P<f>\d{2,3}(?:\.\d+)?)\s?%\s+of\s+(?:the\s+)?"
    r"(?:Fund[’'`]?s\s+)?(?:net\s+asset\s+value|NAV)", re.I)
_RIGHTS_RATIO_RE = re.compile(
    r"one\s+(?:new\s+)?(?:additional\s+)?(?:common\s+)?(?:share|Share)\s+(?:of\s+common\s+stock\s+)?for\s+(?:each|every)\s+"
    r"(?P<n>\w+)\s+(?:\(\d+\)\s+)?[Rr]ights", re.I)
_NONTRANSFERABLE_RE = re.compile(r"non-?\s?transferable", re.I)
_TRANSFERABLE_RE = re.compile(r"(?<!non-)(?<!non)\btransferable\s+(?:subscription\s+)?rights", re.I)


def parse_rights_terms(text: str) -> dict:
    """Subscription-price formula, NAV floor, ratio and transferability of a rights offering."""
    k = _RIGHTS_PRICE_RE.search(text)
    f = _RIGHTS_FLOOR_RE.search(text)
    r = _RIGHTS_RATIO_RE.search(text)
    nt = len(_NONTRANSFERABLE_RE.findall(text))
    tr = len(_TRANSFERABLE_RE.findall(text))
    return {"mkt_pct": float(k.group("k")) if k else None, "mkt_span": span(text, k, pad=60) if k else None,
            "nav_floor_pct": float(f.group("f")) if f else None, "floor_span": span(text, f, pad=60) if f else None,
            "ratio": r.group("n") if r else None, "ratio_span": span(text, r, pad=30) if r else None,
            "transferable": None if (nt == 0 and tr == 0) else (tr > nt)}


def rights_events(client, nm: pd.DataFrame, dist: pd.DataFrame, idx: pd.DataFrame, cmap_names, today) -> pd.DataFrame:
    """CRSP distribution codes 45xx on share-code 14/44 permnos, 2010-01-01..2024-12-31.

    CRSP's first distribution digit 4 is "subscription rights" and second digit
    5 "same issue of common stock" (CRSP coding guide §6.2, read 2026-10-18).
    The meaning is also checked in the data: each event's fund should have
    filed a prospectus supplement (424B2/3/5 or 497) within RIGHTS_XCHECK_DAYS of
    the ex-date, and the share that did is reported. Terms are read from the
    nearest such filing that mentions rights.
    """
    from scripts.events import crsp_events as ce
    from scripts.events.edgar_merger_dates import match_cik
    d = dist[(dist["distcd"] // 100 == 45) & (dist["exdt"] >= SCOPE_START) & (dist["exdt"] <= CRSP_LAST)]
    last = ce.last_name(nm)[["permno", "comnam"]]
    pros = idx[idx["form"].isin(("424B2", "424B3", "424B5", "497"))]
    rows = []
    for r in d.merge(last, on="permno", how="left").itertuples():
        nm_then = ce.name_at(nm, int(r.permno), r.exdt)
        if nm_then is None or int(nm_then["shrcd"]) not in (14, 44):
            continue
        rec = {"type": "rights_offering", "permno": int(r.permno), "crsp_name": r.comnam, "ann_date": r.exdt,
               "distcd": int(r.distcd), "cik": None, "fund": None, "prospectus_accession": None, "xcheck": False}
        crsp_name = nm_then["comnam"]
        m = match_cik(crsp_name, cmap_names, r.exdt - pd.Timedelta(days=400), r.exdt + pd.Timedelta(days=60))
        if m["status"] == "matched":
            cik = int(m["cik"])
            rec.update(cik=cik, fund=m["edgar_name"])
            g = pros[(pros["cik"] == cik) & ((pros["date_filed"] - r.exdt).abs() <= pd.Timedelta(days=RIGHTS_XCHECK_DAYS))]
            rec["xcheck"] = bool(len(g))
            if len(g) and r.exdt < TIME_HOLDOUT:
                for a in g.sort_values("date_filed")["accession"]:
                    t = fetch_plain(client, cik, a)
                    if re.search(r"rights\s+offering|subscription\s+rights", t, re.I):
                        rec["prospectus_accession"] = a
                        rec.update(parse_rights_terms(t))
                        break
        rows.append(rec)
    return pd.DataFrame(rows)


# --------------------------------------------------------- conditional tenders

def conditional_tender_rows() -> pd.DataFrame:
    """The N1 census's fund-window rows (`conditional_tender_census.csv`), as published."""
    if not COND_TENDER_CSV.exists():
        raise FileNotFoundError(f"{COND_TENDER_CSV} missing: run scripts/events/conditional_tender_census.py")
    c = pd.read_csv(COND_TENDER_CSV, parse_dates=["announced", "window_start", "window_end"])
    return c


# ------------------------------------------------------------------- levels

def close_on(dsf: pd.DataFrame, permno: int, d) -> float | None:
    """CRSP's close for `permno` ON date d exactly (no nearby day substituted)."""
    x = dsf[(dsf["permno"] == permno) & (dsf["date"] == pd.Timestamp(d))]
    if x.empty or not np.isfinite(x["prc"].iloc[0]) or x["prc"].iloc[0] <= 0:
        return None
    return float(x["prc"].iloc[0])


def last_close_at_or_before(dsf: pd.DataFrame, permno: int, d, max_gap_days: int = 5):
    x = dsf[(dsf["permno"] == permno) & (dsf["date"] <= pd.Timestamp(d))].sort_values("date")
    if x.empty or (pd.Timestamp(d) - x["date"].iloc[-1]).days > max_gap_days:
        return None, None
    return float(x["prc"].iloc[-1]), x["date"].iloc[-1]


def adv_before(dsf: pd.DataFrame, permno: int, d, n: int = ADV_SESSIONS) -> float | None:
    """Median dollar volume over the n CRSP sessions strictly before d (needs >= 2/3 of them)."""
    assert_pre_holdout(d, "ADV")
    x = dsf[(dsf["permno"] == permno) & (dsf["date"] < pd.Timestamp(d))].sort_values("date").tail(n)
    x = x[np.isfinite(x["vol"]) & np.isfinite(x["prc"])]
    if len(x) < (2 * n) // 3:
        return None
    return float((x["vol"] * x["prc"]).median())


def period_end_discount(client, ncsr: pd.DataFrame, cik: int, permno: int, ann, dsf: pd.DataFrame) -> dict:
    """disc_pre: the last fiscal period-end discount BEFORE the announcement.

    Candidate reports are the fund's N-CSR/N-CSRS filed from 450 days before to
    200 days after the announcement (a report for a period before the
    announcement is often filed after it: the level is still as of that period).
    The period is the submission header's CONFORMED PERIOD OF REPORT; the latest
    period strictly before the announcement and within PERIOD_MAX_STALE_DAYS is
    used. Price = CRSP close at that period-end (last session on or before it);
    NAV = `nav_beside_price`. Returns the fields, or a reason it is missing.
    """
    assert_pre_holdout(ann, "disc_pre")
    ann = pd.Timestamp(ann)
    g = ncsr[(ncsr["cik"] == cik) & (ncsr["date_filed"] > ann - pd.Timedelta(days=450))
             & (ncsr["date_filed"] <= ann + pd.Timedelta(days=200))].sort_values("date_filed", ascending=False)
    best = None
    # Newest filing first: periods rise with filing dates, so the first report whose
    # period precedes the announcement is the latest such period, and older reports
    # need not be fetched (fewer requests to EDGAR, same answer barring an
    # out-of-order amendment).
    for a in g["accession"]:
        raw = fetch_raw(client, cik, a)
        m = re.search(r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", raw)
        if not m:
            continue
        p = pd.Timestamp(m.group(1))
        if p < ann:
            if (ann - p).days <= PERIOD_MAX_STALE_DAYS:
                best = (p, a, raw)
            break
    if best is None:
        return {"pre_reason": "no N-CSR/N-CSRS period before the announcement"}
    p, a, raw = best
    px, pxd = last_close_at_or_before(dsf, permno, p)
    if px is None:
        return {"pre_reason": f"no CRSP close at period-end {p.date()}", "pre_period": p, "pre_accession": a}
    from scripts.events.conditional_tender_census import plain
    hit = nav_beside_price(plain(raw), px)
    if hit is None:
        return {"pre_reason": "CRSP close not found beside a NAV in the report", "pre_period": p, "pre_accession": a}
    return {"pre_reason": None, "pre_period": p, "pre_accession": a, "pre_close": px, "pre_nav": hit["nav"],
            "disc_pre": px / hit["nav"] - 1.0, "pre_layout": hit["layout"], "pre_span": hit["span"],
            "pre_stale_days": int((ann - p).days)}


# ------------------------------------------------------------------- hedges

def hedge_flags(symbols, today: str, offline: bool) -> pd.DataFrame:
    """Alpaca `GET /v2/assets/{symbol}` for each hedge ETF (read-only; cached per day by G1a's reader).

    True on `today` only: `borrow_status` and `shortable` change daily
    (CLAUDE.md landmine 5). A rule built on this re-reads it on the day.
    """
    from scripts.events.g1a_shortability import alpaca_reads
    return alpaca_reads(sorted(set(symbols)), today, offline)


def etf_adv_2022(nm: pd.DataFrame, symbols) -> pd.DataFrame:
    """Median dollar volume of each hedge ETF over its 2022 CRSP sessions (the last pre-holdout year)."""
    from scripts.events import crsp_events as ce
    d = pd.Timestamp("2022-12-30")
    rows, perms = [], {}
    for s in sorted(set(symbols)):
        r = nm[(nm["ticker"] == s) & (nm["namedt"] <= d) & (nm["nameendt"] >= d)]
        ps = r["permno"].unique()
        perms[s] = int(ps[0]) if len(ps) == 1 else None
    dsf = ce.daily([p for p in perms.values() if p])
    for s, p in perms.items():
        x = dsf[(dsf["permno"] == p) & (dsf["date"] >= "2022-01-01")] if p else dsf.iloc[0:0]
        rows.append({"etf": s, "etf_adv_2022_musd": float((x["vol"] * x["prc"]).median() / 1e6) if len(x) else None,
                     "etf_sessions_2022": int(len(x))})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- assembly

LEVEL_TYPES = ("nav_tender", "fixed_price_tender", "liquidation", "term_termination", "open_ending")
TYPE_ORDER = ("nav_tender", "conditional_tender", "liquidation", "term_termination", "open_ending",
              "fixed_price_tender", "rights_offering", "activist_13d", "proxy_contest")
TYPE_LABEL = {
    "nav_tender": "Issuer tender at % of NAV (listed, common)",
    "conditional_tender": "Conditional (discount-triggered) tender programme",
    "liquidation": "Liquidation (discretionary)",
    "term_termination": "Term / target-term termination",
    "open_ending": "Open-ending (conversion, or merger into an open-end fund)",
    "fixed_price_tender": "Issuer tender at a $ price / Dutch auction (mostly BDCs)",
    "rights_offering": "Rights offering",
    "activist_13d": "Activist Schedule 13D (initial)",
    "proxy_contest": "Proxy contest (contest filings)",
}


def base_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("sponsor", "sponsor_recognised", "asset_class", "hedge_etf"):
        df[c] = None
    for i, r in df.iterrows():
        nm = r["fund"] if isinstance(r.get("fund"), str) and r["fund"].strip() else r.get("crsp_name")
        if not isinstance(nm, str) or not nm.strip():
            continue
        s, ok = sponsor_of(nm)
        a = asset_class_of(nm)
        df.at[i, "sponsor"], df.at[i, "sponsor_recognised"] = s, ok
        df.at[i, "asset_class"], df.at[i, "hedge_etf"] = a, HEDGE_ETF[a]
    df["ann_date"] = pd.to_datetime(df["ann_date"])
    df["year"] = df["ann_date"].dt.year
    df["pre_holdout"] = df["ann_date"] < TIME_HOLDOUT
    return df


def add_levels(client, ev: pd.DataFrame, ncsr: pd.DataFrame, cmap: CrspMap, univ: tuple) -> pd.DataFrame:
    """CRSP permno, the universe flag, ADV, disc_post (tenders) and disc_pre (all level types).

    Only rows announced before 2023-01-01 and outside the 44 get any level;
    `assert_pre_holdout` is called inside every level function as well.
    """
    from scripts.events import crsp_events as ce
    ucik, uperm, utk = univ
    ev = ev.copy()
    for c in ("permno_how", "in_universe", "adv_usd", "close_nav_date", "price_xcheck_cent", "disc_post", "disc_navdate",
              "post_reason",
              "pre_reason", "pre_period",
              "pre_accession", "pre_close", "pre_nav", "disc_pre", "pre_layout", "pre_span", "pre_stale_days",
              "close_doc_date"):
        if c not in ev:
            ev[c] = None
    ev["permno"] = ev["permno"] if "permno" in ev else None
    for i, r in ev.iterrows():
        # An activist or contest target with a ticker today is listed; the (slow) CRSP name
        # match is needed only for one without, to tell a dead listed fund from a private one.
        needs = r["type"] in LEVEL_TYPES or (r["type"] in ("activist_13d", "proxy_contest")
                                              and not isinstance(r.get("ticker_now"), str))
        if pd.isna(r.get("permno")) and needs and isinstance(r.get("fund"), str) and r["ann_date"] <= CRSP_LAST:
            tk = r.get("ticker") if isinstance(r.get("ticker"), str) else r.get("ticker_now")
            p, how = cmap.permno(r["fund"], tk if isinstance(tk, str) else None, r["ann_date"])
            ev.at[i, "permno"], ev.at[i, "permno_how"] = p, how
        cik = r.get("cik")
        tkn = r.get("ticker_now") if isinstance(r.get("ticker_now"), str) else ""
        ev.at[i, "in_universe"] = bool((pd.notna(cik) and int(cik) in ucik)
                                       or (pd.notna(ev.at[i, "permno"]) and int(ev.at[i, "permno"]) in uperm)
                                       or any(t in utk for t in tkn.split(";") if t))
    want = ev[ev["type"].isin(LEVEL_TYPES) & ev["pre_holdout"] & ~ev["in_universe"].astype(bool) & ev["permno"].notna()]
    dsf = ce.daily(sorted({int(p) for p in want["permno"]})) if len(want) else None
    for i, r in want.iterrows():
        p = int(r["permno"])
        ev.at[i, "adv_usd"] = adv_before(dsf, p, r["ann_date"])
        if r["type"] in ("nav_tender", "fixed_price_tender"):
            if isinstance(r.get("nav_date"), pd.Timestamp) and pd.notna(r.get("nav")) and r["nav_date"] < TIME_HOLDOUT:
                c = close_on(dsf, p, r["nav_date"])
                d, why = post_discount(float(r["nav"]), r["nav_date"], r["ann_date"], c)
                ev.at[i, "post_reason"] = why
                if c is not None and PAIR_RATIO[0] < c / r["nav"] < PAIR_RATIO[1]:
                    ev.at[i, "close_nav_date"], ev.at[i, "disc_navdate"] = c, c / r["nav"] - 1.0
                    if pd.notna(r.get("stated_price")):     # the offer's own price for that date, beside CRSP's
                        ev.at[i, "price_xcheck_cent"] = bool(abs(float(r["stated_price"]) - c) < 0.005)
                ev.at[i, "disc_post"] = d
            if r["type"] == "fixed_price_tender" and isinstance(r.get("doc_date"), pd.Timestamp):
                c, _ = last_close_at_or_before(dsf, p, r["doc_date"])
                ev.at[i, "close_doc_date"] = c
        if pd.notna(r.get("cik")):
            pe = period_end_discount(client, ncsr, int(r["cik"]), p, r["ann_date"], dsf)
            for k, v in pe.items():
                ev.at[i, k] = v
    return ev


def hold_days(r: dict):
    a = r.get("ann_date")
    if r["type"] in ("nav_tender", "fixed_price_tender"):
        x = r.get("expire")
        if isinstance(x, pd.Timestamp) and x >= a:
            return int((x - a).days) + 1, "announcement -> expiry + 1 (pricing date)"
        e = r.get("end_date")
        return (int((e - a).days), "announcement -> final amendment (upper bound)") if isinstance(e, pd.Timestamp) else (None, None)
    if r["type"] in ("liquidation", "term_termination", "open_ending"):
        e = r.get("end_date")
        return (int((e - a).days), "announcement -> last distribution or delisting") if isinstance(e, pd.Timestamp) and isinstance(a, pd.Timestamp) else (None, None)
    return None, None


def add_spreads(ev: pd.DataFrame, a_expected: float | None) -> pd.DataFrame:
    """Terms-implied spreads from levels (module docstring). No realised price enters."""
    ev = ev.copy()
    for c in ("slice_post", "pos_post", "slice_pre", "pos_pre", "pos_navdate", "pos_giveback", "hold", "hold_how",
              "fixed_spread"):
        ev[c] = None
    for i, r in ev.iterrows():
        h, how = hold_days(r.to_dict())
        ev.at[i, "hold"], ev.at[i, "hold_how"] = h, how
        if not r["pre_holdout"] or bool(r.get("in_universe")):
            continue
        if r["type"] == "nav_tender":
            if pd.notna(r.get("disc_post")):
                ev.at[i, "slice_post"] = accepted_slice_spread(r["k_pct"], float(r["disc_post"]))
                if a_expected:
                    ev.at[i, "pos_post"] = position_spread(r["k_pct"], float(r["disc_post"]), a_expected)
            if pd.notna(r.get("disc_pre")):
                ev.at[i, "slice_pre"] = accepted_slice_spread(r["k_pct"], float(r["disc_pre"]))
                if a_expected:
                    ev.at[i, "pos_pre"] = position_spread(r["k_pct"], float(r["disc_pre"]), a_expected)
            if a_expected and pd.notna(r.get("disc_navdate")):
                ev.at[i, "pos_navdate"] = position_spread(r["k_pct"], float(r["disc_navdate"]), a_expected)
            if a_expected and pd.notna(r.get("disc_post")) and pd.notna(r.get("disc_pre")):
                ev.at[i, "pos_giveback"] = giveback_spread(r["k_pct"], float(r["disc_post"]), float(r["disc_pre"]),
                                                           a_expected)
        elif r["type"] in ("liquidation", "term_termination", "open_ending") and pd.notna(r.get("disc_pre")):
            ev.at[i, "slice_pre"] = ev.at[i, "pos_pre"] = nav_exit_spread(float(r["disc_pre"]))
        elif r["type"] == "fixed_price_tender" and pd.notna(r.get("close_doc_date")):
            px = r.get("fixed_price") if pd.notna(r.get("fixed_price")) else r.get("dutch_lo")
            if pd.notna(px):
                ev.at[i, "fixed_spread"] = float(px) / float(r["close_doc_date"]) - 1.0
    return ev


# ------------------------------------------------------------------ summary

def groups(df: pd.DataFrame) -> dict:
    """Independent groups: sponsor x announcement date, and the stricter sponsor x month."""
    d = df.dropna(subset=["sponsor", "ann_date"])
    return {"events": int(len(df)), "with_sponsor": int(len(d)),
            "sponsor_x_date": int(d.groupby(["sponsor", d["ann_date"].dt.normalize()]).ngroups),
            "sponsor_x_month": int(d.groupby(["sponsor", d["ann_date"].dt.to_period("M")]).ngroups),
            "unrecognised_sponsor_share": round(float((d["sponsor_recognised"] == False).mean()), 3) if len(d) else None}


def _med(s) -> float | None:
    s = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
    return float(s.median()) if len(s) else None


def _q(s, q) -> float | None:
    s = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
    return float(s.quantile(q)) if len(s) else None


def per_year(df: pd.DataFrame, years=range(2010, 2027)) -> dict:
    c = df["year"].value_counts()
    return {int(y): int(c.get(y, 0)) for y in years}


def cond_tender_summary(c: pd.DataFrame, univ_tickers: set) -> dict:
    """The N1 census, summarised in this census's terms (counts, groups, terms, terms-implied spreads)."""
    c = c.copy()
    c["in_universe"] = c["ticker"].isin(univ_tickers)
    known = c["outcome"].astype(str).str.startswith(("triggered", "not_triggered"))
    trig = c["outcome"].astype(str).str.startswith("triggered") & ~c["outcome"].astype(str).str.contains("cancel")
    c["end"] = pd.to_datetime(c["window_end"])
    pre = c["end"] < TIME_HOLDOUT
    k = c[pre & known]
    clusters = k.dropna(subset=["end"]).groupby(["sponsor", "end"])
    # Whether a window triggered is read from the fund's discount LEVEL, so a
    # cef_universe.csv fund's outcome is a level statistic: the trigger share
    # and the window length are computed outside the 44 (counts include them).
    kk = k[~k["in_universe"]].dropna(subset=["end"])
    p_trig = float(trig[kk.index].groupby([kk["sponsor"], kk["end"]]).any().mean()) if len(kk) else None
    lv = c[pre & trig & ~c["in_universe"] & c["published_avg_pct"].notna() & c["tender_price_pct_nav"].notna()]
    sl = [accepted_slice_spread(float(r.tender_price_pct_nav), float(r.published_avg_pct) / 100.0) for r in lv.itertuples()]
    a = pd.to_numeric(c.loc[pre & ~c["in_universe"], "proration_pct"], errors="coerce").dropna() / 100.0
    a_med = float(a.median()) if len(a) else None
    span_days = (pd.to_datetime(c["window_end"]) - pd.to_datetime(c["window_start"])).dt.days
    return {"fund_windows": int(len(c)), "fund_windows_pre2023": int(pre.sum()),
            "fund_windows_in_44": int(c["in_universe"].sum()),
            "funds_in_44": sorted(c.loc[c["in_universe"], "ticker"].dropna().unique().tolist()),
            "clusters_known_pre2023": int(clusters.ngroups),
            "clusters_known_all": int(c[known].dropna(subset=["end"]).groupby(["sponsor", "end"]).ngroups),
            "groups_sponsor_x_announced": int(c.dropna(subset=["announced"]).groupby(["sponsor", "announced"]).ngroups),
            "clusters_known_pre2023_ex44": int(k[~k["in_universe"]].dropna(subset=["end"]).groupby(["sponsor", "end"]).ngroups),
            "clusters_per_window_end_year": {int(y): int(n) for y, n in c.dropna(subset=["end"])
                                             .drop_duplicates(["sponsor", "end"])["end"].dt.year.value_counts().sort_index().items()},
            "p_trigger_cluster_pre2023": p_trig,
            "threshold_median_pct": _med(c["threshold_pct"]), "price_median_pct_nav": _med(c["tender_price_pct_nav"]),
            "slice_spread_median": _med(sl), "slice_spread_n": len(sl),
            "slice_spread_groups": int(lv.groupby(["sponsor", "end"]).ngroups) if len(lv) else 0,
            "proration_median": a_med, "proration_n": int(len(a)),
            "window_days_median": _med(span_days[pre & ~c["in_universe"]]),
            "position_spread_if_triggered": (a_med * _med(sl)) if (a_med and sl) else None,
            "expected_position_spread": (p_trig * a_med * _med(sl)) if (p_trig and a_med and sl) else None}


GATE_MIN_GROUPS = 30            # G1c's bar (RESEARCH_PLAN_2026-10-09 §2): below it, D7
COST_GRID_BP = (5, 15, 30)


def cost_units(t: str, a: float | None) -> float | None:
    """Fund-leg trading units per event: entry 1, plus selling whatever does not exit at NAV.

    A liquidation, termination or open-ending exits the whole position at NAV
    (no sale). A tender exits a; the (1 - a) residual is sold. The hedge leg's
    cost (an ETF at a fraction of the fund's spread) is NOT charged: stated.
    """
    if t in ("liquidation", "term_termination", "open_ending"):
        return 1.0
    if t in ("nav_tender", "conditional_tender") and a is not None:
        return 1.0 + (1.0 - a)
    return None


def proration_agreement(d: pd.DataFrame) -> dict:
    """Parsed pro-ration a against the second method (offer size % / % of outstanding tendered)."""
    if "proration_xcheck" not in d:
        return {"xcheck_n": 0, "xcheck_within_005": None, "xcheck_median_abs_diff": None, "xcheck_median": None}
    x = d[["proration", "proration_xcheck"]].apply(pd.to_numeric, errors="coerce").dropna()
    dd = (x["proration"] - x["proration_xcheck"]).abs()
    allx = pd.to_numeric(d["proration_xcheck"], errors="coerce").dropna()
    return {"xcheck_n": int(len(x)), "xcheck_within_005": round(float((dd <= 0.05).mean()), 3) if len(x) else None,
            "xcheck_median_abs_diff": round(float(dd.median()), 4) if len(x) else None,
            "xcheck_median": _med(allx), "xcheck_median_n": int(len(allx))}


def hedge_summary(etfs: list, hz: pd.DataFrame) -> dict:
    """For a list of events' primary hedge ETFs: the mode, the mix, the share whose PRIMARY is
    shortable on the read date, the share with ANY declared candidate shortable, and the
    hedge named per primary (`hedge_choice`)."""
    if not etfs:
        return {"hedge_etf_mode": None, "hedge_mix": {}, "hedge_shortable_share": None,
                "hedge_any_shortable_share": None, "hedge_used": {}}
    e = pd.Series(etfs)
    ch = {x: hedge_choice(x, hz) for x in sorted(set(etfs))}
    return {"hedge_etf_mode": e.mode().iloc[0], "hedge_mix": e.value_counts().head(4).to_dict(),
            "hedge_shortable_share": round(float(e.map(lambda x: ch[x][1]).mean()), 3),
            "hedge_any_shortable_share": round(float(e.map(lambda x: ch[x][0] is not None).mean()), 3),
            "hedge_used": {x: ch[x][0] for x in ch}}


def type_rows(ev: pd.DataFrame, cond: dict, hedges: pd.DataFrame, etf_adv: pd.DataFrame, a_expected) -> list[dict]:
    rows = []
    if hedges.empty:
        raise ValueError("no Alpaca hedge reads: the hedge columns cannot be filled")
    hz = hedges.set_index("symbol")
    for t in TYPE_ORDER:
        if t == "conditional_tender":
            gpy = cond["clusters_known_pre2023_ex44"] / FIT_YEARS
            rows.append({"type": t, "label": TYPE_LABEL[t], "events_all": cond["fund_windows"],
                         "events_2010_22": cond["fund_windows_pre2023"],
                         "groups_2010_22": cond["clusters_known_pre2023"],
                         "groups_2010_22_ex44": cond["clusters_known_pre2023_ex44"],
                         "per_year": cond["clusters_per_window_end_year"],
                         "groups_per_year": round(gpy, 2), "terms": (f"threshold median {cond['threshold_median_pct']}%; "
                                                                   f"price median {cond['price_median_pct_nav']}% NAV"),
                         "proration_median": cond["proration_median"], "proration_n": cond["proration_n"],
                         "spread_basis": "published window average (at trigger) x P(trigger)",
                         "spread_slice_median": cond["slice_spread_median"], "spread_n": cond["slice_spread_n"],
                         "spread_position_median": cond["expected_position_spread"],
                         "hold_days_median": cond["window_days_median"], "adv_musd_median": None,
                         "adv_n": cond.get("adv_n"), **hedge_summary(cond.get("hedge_etfs") or [], hz),
                         "usable_groups": cond["slice_spread_groups"]})
            continue
        d = ev[ev["type"] == t]
        fit = d[d["pre_holdout"] & (d["year"] >= 2010)]
        fitx = fit[~fit["in_universe"].astype(bool)] if "in_universe" in fit else fit
        g_all, g_ex = groups(fit), groups(fitx)
        r = {"type": t, "label": TYPE_LABEL[t], "events_all": int(len(d)), "events_2010_22": int(len(fit)),
             "events_in_44": int(d["in_universe"].astype(bool).sum()) if "in_universe" in d else None,
             "groups_2010_22": g_all["sponsor_x_date"], "groups_2010_22_ex44": g_ex["sponsor_x_date"],
             "groups_2010_22_ex44_month": g_ex["sponsor_x_month"],
             "unrecognised_sponsor_share": g_ex["unrecognised_sponsor_share"],
             "groups_per_year": round(g_ex["sponsor_x_date"] / FIT_YEARS, 2), "per_year": per_year(d)}
        if t == "nav_tender":
            r.update(terms=f"price median {_med(fitx['k_pct'])}% NAV (IQR {_q(fitx['k_pct'], .25)}-{_q(fitx['k_pct'], .75)}); "
                           f"size median {_med(fitx['size_pct'])}% of shares",
                     proration_median=_med(fitx["proration"]), proration_n=int(fitx["proration"].notna().sum()),
                     proration_groups=groups(fitx[fitx["proration"].notna()])["sponsor_x_date"],
                     proration_how=fitx["proration_how"].value_counts().to_dict(),
                     **proration_agreement(fitx),
                     disc_post_median=_med(fitx["disc_post"]), disc_post_n=int(fitx["disc_post"].notna().sum()),
                     disc_navdate_median=_med(fitx["disc_navdate"]), disc_navdate_n=int(fitx["disc_navdate"].notna().sum()),
                     post_reasons=fitx["post_reason"].value_counts().to_dict(),
                     price_xcheck_n=int(fitx["price_xcheck_cent"].notna().sum()),
                     price_xcheck_agree_cent=int((fitx["price_xcheck_cent"] == True).sum()),
                     disc_pre_median=_med(fitx["disc_pre"]), disc_pre_n=int(fitx["disc_pre"].notna().sum()),
                     spread_basis="disc_post (offer-stated NAV dated on/after the announcement, CRSP close same date) "
                                  "x expected pro-ration",
                     spread_slice_median=_med(fitx["slice_post"]), spread_n=int(fitx["slice_post"].notna().sum()),
                     spread_position_median=_med(fitx["pos_post"]),
                     spread_position_pre_median=_med(fitx["pos_pre"]),
                     spread_position_navdate_median=_med(fitx["pos_navdate"]),
                     spread_position_giveback_median=_med(fitx["pos_giveback"]),
                     spread_position_giveback_n=int(pd.to_numeric(fitx["pos_giveback"], errors="coerce").notna().sum()),
                     usable_groups=groups(fitx[fitx["slice_post"].notna()])["sponsor_x_date"])
        elif t in ("liquidation", "term_termination", "open_ending"):
            r.update(terms="whole position exits at NAV (less any liquidation cost or redemption fee, not read)",
                     proration_median=1.0, proration_n=None,
                     disc_pre_median=_med(fitx["disc_pre"]), disc_pre_n=int(fitx["disc_pre"].notna().sum()),
                     spread_basis="disc_pre (last period-end before announcement): an UPPER bound",
                     spread_slice_median=_med(fitx["slice_pre"]), spread_n=int(fitx["slice_pre"].notna().sum()),
                     spread_position_median=_med(fitx["pos_pre"]),
                     stale_days_median=_med(fitx["pre_stale_days"]),
                     ann_basis=fitx["ann_how"].value_counts().to_dict(),
                     ann_basis_usable=fitx.loc[fitx["slice_pre"].notna(), "ann_how"].value_counts().to_dict(),
                     usable_groups=groups(fitx[fitx["slice_pre"].notna()])["sponsor_x_date"])
        elif t == "fixed_price_tender":
            r.update(terms="$ price or Dutch range", spread_basis="tender $ price (Dutch: bottom) / CRSP close at offer date",
                     spread_slice_median=_med(fitx["fixed_spread"]), spread_n=int(fitx["fixed_spread"].notna().sum()),
                     spread_position_median=None, proration_median=_med(fitx["proration"]),
                     proration_n=int(fitx["proration"].notna().sum()))
        elif t == "rights_offering":
            r.update(terms=(f"subscription at median {_med(fitx.get('mkt_pct'))}% of market, NAV floor median "
                            f"{_med(fitx.get('nav_floor_pct'))}% (n {int(pd.Series(fitx.get('mkt_pct')).notna().sum())}); "
                            f"transferable {int((fitx.get('transferable') == True).sum())} / non-transferable "
                            f"{int((fitx.get('transferable') == False).sum())}"),
                     spread_basis="none: no exit above the market for a holder; the long side carries the subscription-period decline",
                     spread_position_median=None,
                     xcheck_share=round(float(d["xcheck"].mean()), 3) if len(d) else None)
        else:
            r.update(terms="no stated exit price", spread_basis="none: no terms to imply a spread",
                     spread_position_median=None)
        r["hold_days_median"] = _med(fitx["hold"]) if "hold" in fitx else None
        r["adv_musd_median"] = (_med(fitx["adv_usd"]) / 1e6) if "adv_usd" in fitx and _med(fitx["adv_usd"]) else None
        r["adv_n"] = int(pd.to_numeric(fitx.get("adv_usd"), errors="coerce").notna().sum()) if "adv_usd" in fitx else 0
        r.update(hedge_summary(fitx["hedge_etf"].dropna().tolist(), hz))
        rows.append(r)
    for r in rows:
        a = r.get("proration_median")
        if r["type"] == "conditional_tender" and a is not None and cond.get("p_trigger_cluster_pre2023") is not None:
            a = cond["p_trigger_cluster_pre2023"] * a     # untriggered windows are sold whole
        u = cost_units(r["type"], a)
        r["cost_units"] = u
        sp = r.get("spread_position_median")
        for c in COST_GRID_BP:
            r[f"net_{c}bp"] = (sp - u * c / 1e4) if (sp is not None and u is not None) else None
        adv = r.get("adv_musd_median")
        if r["type"] == "conditional_tender":
            adv = cond.get("adv_musd_median")
            r["adv_musd_median"] = adv
        r["rank_score_kusd_per_yr"] = (r["groups_per_year"] * sp * adv * 1e3) if (sp and adv) else None
    return rows


SAMPLE_SEED = 20261018
SAMPLE_FIELDS = {
    "nav_tender": ("doc_accession", "result_accession", "k_pct", "k_span", "size_pct", "size_span", "nav", "nav_date",
                   "nav_span", "proration", "proration_how", "proration_span"),
    "fixed_price_tender": ("doc_accession", "basis_span", "proration", "proration_span"),
    "liquidation": ("n8f_accession", "reason_span", "board_span", "dist_span", "pre_accession", "pre_span"),
    "term_termination": ("n8f_accession", "reason_span", "board_span", "dist_span", "pre_accession", "pre_span"),
    "open_ending": ("n8f_accession", "reason_span", "board_span", "survivor", "pre_accession", "pre_span"),
    "rights_offering": ("prospectus_accession", "mkt_span", "floor_span", "ratio_span", "transferable"),
    "activist_13d": ("accession", "activist"),
    "proxy_contest": ("accession",),
}


def terms_sample(ev: pd.DataFrame, k: int = 3) -> dict:
    """A seeded random sample per type of the terms as read, each with its accession and source span.

    Pre-2023 events outside the 44 only, and EDGAR facts only (the tracked columns),
    so the note can quote filings without quoting CRSP. The seed is fixed so the
    note's examples are reproducible, not chosen.
    """
    out = {}
    for t, cols in SAMPLE_FIELDS.items():
        d = ev[(ev["type"] == t) & ev["pre_holdout"] & ~ev["in_universe"].astype(bool)]
        key = cols[1] if t in ("nav_tender", "liquidation", "term_termination", "open_ending", "rights_offering") else cols[0]
        d = d[d[key].notna()] if key in d else d
        if d.empty:
            out[t] = []
            continue
        smp = d.sample(min(k, len(d)), random_state=SAMPLE_SEED)
        out[t] = [{"fund": r["fund"], "cik": int(r["cik"]) if pd.notna(r.get("cik")) else None,
                   "ann_date": str(pd.Timestamp(r["ann_date"]).date()) if t != "rights_offering" else None,
                   **{c: (None if (not isinstance(r.get(c), str) and pd.isna(r.get(c))) else
                          (str(r[c])[:300] if isinstance(r.get(c), str) else (str(r[c]) if isinstance(r.get(c), pd.Timestamp)
                                                                              else r.get(c))))
                      for c in cols if c in r}}
                  for _, r in smp.iterrows()]
    return out


def gate_table(rows: list[dict], top: list[str]) -> list[dict]:
    """Zero-trial gates in G1c's style for the best types. Thresholds are declared, not fitted:
    30 groups is G1c's bar; the cost bar is the top of the desk's grid (30bp per unit)."""
    out = []
    by = {r["type"]: r for r in rows}
    for t in top:
        r = by[t]
        g = r.get("groups_2010_22_ex44") if r.get("groups_2010_22_ex44") is not None else r.get("groups_2010_22")
        out.append({"type": t, "gate": f"{t}-a: independent groups 2010-22 (sponsor x date, the 44 excluded) >= 30",
                    "value": g, "pass": bool(g is not None and g >= GATE_MIN_GROUPS)})
        u = r.get("usable_groups")
        if u is not None:
            out.append({"type": t, "gate": f"{t}-b: usable groups (terms-implied spread measurable) >= 30",
                        "value": u, "pass": bool(u >= GATE_MIN_GROUPS)})
        n30 = r.get("net_30bp")
        upper = "disc_pre" in (r.get("spread_basis") or "")
        out.append({"type": t, "gate": f"{t}-c: median terms-implied position spread net of {r.get('cost_units')} units x 30bp > 0"
                    + (" (on disc_post; disc_pre is an upper bound and cannot pass it)" if upper else ""),
                    "value": None if n30 is None else round(n30 * 1e4, 1),
                    "pass": bool(n30 is not None and n30 > 0 and not upper)})
        h = r.get("hedge_any_shortable_share")
        out.append({"type": t, "gate": (f"{t}-d: share of events with a shortable same-exposure ETF at Alpaca on the read "
                                        f"date (primary or declared alternate) > 0.5 [primary alone: "
                                        f"{r.get('hedge_shortable_share')}]"),
                    "value": h, "pass": bool(h is not None and h > 0.5)})
        if t == "nav_tender":
            pg = r.get("proration_groups")
            out.append({"type": t, "gate": f"{t}-e: groups with a measured pro-ration >= 30",
                        "value": pg, "pass": bool(pg is not None and pg >= GATE_MIN_GROUPS)})
    return out


# --------------------------------------------------------------------- main

TRACKED_COLS = [
    "type", "cik", "fund", "ticker_now", "ann_date", "ann_how", "sponsor", "sponsor_recognised", "asset_class",
    "hedge_etf", "in_universe", "pre_holdout", "scope_reason",
    "ann_form", "ann_accession", "doc_accession", "doc_date", "result_accession", "class", "listed", "ticker", "basis",
    "k_pct", "k_span", "size_pct", "size_span", "dutch_lo", "dutch_hi", "fixed_price", "expire", "nav_kind",
    "nav_date", "nav", "nav_span", "stated_price", "stated_price_span", "sought_shares", "sought_span", "tendered", "accepted", "proration", "proration_how",
    "proration_span", "pct_tendered", "pct_tendered_span", "proration_xcheck", "multi_fund", "result_other_funds",
    "n8f_accession", "reason", "board_date", "holder_date", "dist_first", "dist_last", "survivor", "reason_span",
    "board_span", "dist_span", "files_open_end_forms_after",
    "activist", "accession", "prospectus_accession", "mkt_pct", "mkt_span", "nav_floor_pct", "floor_span", "ratio",
    "transferable", "pre_accession", "pre_period", "pre_nav", "pre_layout", "pre_span"]
# CRSP-derived (licensed): permno, CRSP names, delisting codes/dates, closes, ADV, every discount and spread.
LICENSED_COLS = ["permno", "permno_how", "crsp_name", "dlstdt", "dlstcd", "distcd", "xcheck", "adv_usd",
                 "close_nav_date", "price_xcheck_cent", "close_doc_date", "disc_post", "disc_navdate", "post_reason", "pre_close", "disc_pre",
                 "pre_stale_days", "slice_post", "pos_post", "slice_pre", "pos_pre", "pos_navdate", "pos_giveback",
                 "fixed_spread", "hold", "hold_how", "end_date", "year"]


def tracked_view(ev: pd.DataFrame) -> pd.DataFrame:
    """EDGAR facts only. Rights events are dated by their prospectus filing (EDGAR), not CRSP's ex-date;
    exits without an EDGAR CIK are dropped (they exist only as CRSP rows)."""
    v = ev.copy()
    r = v["type"] == "rights_offering"
    v.loc[r, "ann_date"] = None
    v = v[~(v["type"].isin(("liquidation", "term_termination", "open_ending", "merger_into_unlisted", "unresolved",
                            "rights_offering")) & v["cik"].isna())]
    cols = [c for c in TRACKED_COLS if c in v.columns]
    return v[cols]


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(today: date, offline: bool) -> dict:
    from scripts.events import crsp_events as ce
    from scripts.events.edgar_merger_dates import name_table
    client = _client(offline)
    filings, episodes = load_edgar()
    idx = index_rows(client, today)
    nm, dl = ce.names(), ce.delistings()
    univ = universe_ids(client, nm)
    cmap = CrspMap(nm)
    names, _ = name_table(client, today)

    # Every ticker CRSP ever carried on a closed-end share code: what marks a joint release.
    cef_tickers = set(nm.loc[nm["shrcd"].isin((14, 44)), "ticker"].dropna().astype(str))
    tend = tender_events(client, filings, episodes, cef_tickers)
    _log(f"tenders: {len(tend)} episodes; EDGAR requests {client.n_requests}")
    exits = exit_events(client, filings, idx, nm, dl, names)
    _log(f"exits: {len(exits)} CRSP candidates; EDGAR requests {client.n_requests}")
    acts = activist_events(idx, set(filings["cik"]), filings)
    conts = contest_events(episodes)
    cef_perms = sorted(nm[nm["shrcd"].isin((14, 44)) & (nm["nameendt"] >= "2009-01-01")]["permno"].unique())
    rights = rights_events(client, nm, ce.distributions(cef_perms), idx, names, today)
    cond = conditional_tender_rows()
    _log(f"activists {len(acts)}, contests {len(conts)}, rights {len(rights)}; EDGAR requests {client.n_requests}")

    ev = pd.concat([tend[tend["type"] != "not_in_scope"], exits, acts, conts, rights], ignore_index=True)
    ev = base_columns(ev)
    ncsr = idx[idx["form"].isin(("N-CSR", "N-CSRS"))]
    ev = add_levels(client, ev, ncsr, cmap, univ)
    _log(f"levels done; EDGAR requests {client.n_requests}")
    # activists and contests count only where the target was listed (a CRSP CEF record or a ticker today)
    lst = ev["type"].isin(("activist_13d", "proxy_contest"))
    ev = ev[~lst | ev["permno"].notna() | ev["ticker_now"].notna()].reset_index(drop=True)
    nt = ev[(ev["type"] == "nav_tender") & ev["pre_holdout"] & ~ev["in_universe"].astype(bool)]
    a_expected = _med(nt["proration"])
    ev = add_spreads(ev, a_expected)

    # conditional tenders: ADV of the programme funds before each pre-2023 window end
    cs = cond_tender_summary(cond, set(univ[2]))
    cpre = cond[(pd.to_datetime(cond["window_end"]) < TIME_HOLDOUT) & ~cond["ticker"].isin(set(univ[2]))]
    fnames = filings.sort_values("date_filed").groupby("cik")["company"].last()
    cperm, cetf = [], []
    for r in cpre.itertuples():
        nmf = fnames.get(int(r.cik)) if pd.notna(r.cik) else None
        if nmf is None:
            continue
        cetf.append(HEDGE_ETF[asset_class_of(nmf)])
        p, _ = cmap.permno(nmf, r.ticker, r.window_end)
        if p:
            cperm.append((p, r.window_end))
    cs["hedge_etfs"] = cetf
    if cperm:
        dsf = ce.daily(sorted({p for p, _ in cperm}))
        advs = [adv_before(dsf, p, w) for p, w in cperm]
        cs["adv_musd_median"] = (_med(advs) or 0) / 1e6 or None
        cs["adv_n"] = int(sum(a is not None for a in advs))

    symbols = sorted(set(HEDGE_ETF.values()) | {MUNI_DURATION_FALLBACK}
                     | {a for v in HEDGE_ALTERNATES.values() for a in v})
    flags = hedge_flags(symbols, today.isoformat(), offline)
    etf_adv = etf_adv_2022(nm, symbols)
    rows = type_rows(ev, cs, flags, etf_adv, a_expected)
    ranked = sorted([r for r in rows if r.get("rank_score_kusd_per_yr")], key=lambda r: -r["rank_score_kusd_per_yr"])
    ranked += [r for r in rows if not r.get("rank_score_kusd_per_yr")]
    for i, r in enumerate(ranked, 1):
        r["rank"] = i if r.get("rank_score_kusd_per_yr") else None
    top = [r["type"] for r in ranked if r.get("rank_score_kusd_per_yr")][:3]
    gates = gate_table(rows, top)

    OUT.mkdir(parents=True, exist_ok=True)
    ev.to_csv(EVENTS_FULL_CSV, index=False)
    tracked_view(ev).to_csv(EVENTS_CSV, index=False)
    pd.DataFrame(ranked).drop(columns=["per_year", "hedge_mix"], errors="ignore").to_csv(CENSUS_CSV, index=False)
    hz = flags.merge(etf_adv, left_on="symbol", right_on="etf", how="left")
    exits_unresolved = exits[exits["type"].isin(("unresolved", "merger_into_unlisted"))]
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zero_trials": "no realised return or P&L of any event; level statistics on events announced before 2023-01-01 only; "
                       "no statistic on any cef_universe.csv fund beyond counts",
        "data": {"edgar_last_filing_in_fetcher": json.loads((OUT / "edgar_events_summary.json").read_text())["last_date_filed_seen"],
                 "crsp_names_delistings_last": str(nm["nameendt"].max().date()),
                 "crsp_daily": "rows before 2023-01-01 only (crsp_events.daily)",
                 "alpaca_read_date": today.isoformat(),
                 "conditional_tender_census": str(COND_TENDER_CSV.relative_to(REPO))},
        "fetch": {"edgar_requests": client.n_requests, "edgar_cache_hits": client.n_cache_hits},
        "tender_episodes": {"total_2010_on": int(len(tend)), "by_type": tend["type"].value_counts().to_dict(),
                            "not_in_scope_reasons": tend["scope_reason"].value_counts().to_dict()},
        "exits": {"crsp_candidates": int(len(exits)), "by_type": exits["type"].value_counts().to_dict(),
                  "cik_match": exits["match"].value_counts().to_dict(),
                  "n8f_read": int(exits["n8f_accession"].notna().sum()),
                  "announcement_basis": exits["ann_how"].value_counts().to_dict(),
                  "unresolved_or_unlisted_survivor": int(len(exits_unresolved))},
        "rights": {"crsp_events": int(len(rights)), "prospectus_within_60d_share": round(float(rights["xcheck"].mean()), 3)
                   if len(rights) else None, "terms_read": int(rights["prospectus_accession"].notna().sum())},
        "expected_proration_nav_tender": a_expected,
        "conditional_tender": cs,
        "hedges": hz.to_dict("records"),
        "types": rows, "rank_order": [r["type"] for r in ranked], "gates": gates,
        "terms_sample": terms_sample(ev),
        "universe_events_counted_only": int(ev["in_universe"].astype(bool).sum()),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="caches only (EDGAR, CRSP, Alpaca); raise on a miss")
    ap.add_argument("--today", default=date.today().isoformat(), help="date of the Alpaca read (cache key)")
    a = ap.parse_args(argv)
    s = run(date.fromisoformat(a.today), a.offline)
    w = 22
    print(f"{'type':<{w}} {'events':>6} {'grp10-22':>8} {'grp/yr':>6} {'spread':>8} {'net30':>7} {'ADV$m':>6} {'hold':>5} {'hedge':>5} score")
    for t in s["rank_order"]:
        r = next(x for x in s["types"] if x["type"] == t)
        f = lambda v, k=1, d=1: "-" if v is None else f"{v * k:.{d}f}"
        print(f"{t:<{w}} {r['events_all']:>6} {str(r.get('groups_2010_22_ex44', r.get('groups_2010_22'))):>8} "
              f"{f(r.get('groups_per_year'), 1, 2):>6} {f(r.get('spread_position_median'), 1e4, 0):>8} "
              f"{f(r.get('net_30bp'), 1e4, 0):>7} {f(r.get('adv_musd_median'), 1, 2):>6} "
              f"{f(r.get('hold_days_median'), 1, 0):>5} {str(r.get('hedge_etf_mode')):>5} {f(r.get('rank_score_kusd_per_yr'), 1, 1)}")
    for g in s["gates"]:
        print(f"  {'PASS' if g['pass'] else 'FAIL'}  {g['gate']}: {g['value']}")
    print(f"wrote {EVENTS_CSV.name}, {EVENTS_FULL_CSV.name} (gitignored), {CENSUS_CSV.name}, {SUMMARY_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
