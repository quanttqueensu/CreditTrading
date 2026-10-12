"""Merger announcement dates from EDGAR for the CRSP merger-pair sample (plan 0.7, use (a)).

    export QUANTT_ENV_FILE=/abs/path/config/.env
    python3 scripts/events/edgar_merger_dates.py            # -> results/events/merger_edgar_dates.csv (gitignored)
    python3 scripts/events/edgar_merger_dates.py --offline  # cache only
    python3 scripts/events/merger_pairs.py --edgar-dates    # then the at-announcement figure on these dates

ZERO TRIALS. It dates events; it computes no return.

WHY THIS EXISTS
---------------
The 2026-10-11 re-run (`results/events/REPRO_CEF_EVENTS_2026-10-11.md` §2)
found the at-announcement median of the NAV-for-NAV merger pair is +35bp on the
dates an agent supplied (N=36 in 12 groups), but -19bp on the 6 groups whose
dates were actually read in EDGAR. The sign of the only ex-ante figure turned on
where the dates came from. This script dates EVERY deal in the re-run's sample
from EDGAR by one rule, so the figure no longer depends on which dates someone
happened to look up.

HOW A DEAL IS DATED
-------------------
1. **CRSP fund -> EDGAR CIK, by name.** CRSP carries no CIK, and most of these
   funds have no ticker in the SEC's ticker file today. The CRSP name at
   delisting (32 characters, abbreviated: "NUVEEN NY QLTY INCOME MUN FD INC") is
   matched to the names EDGAR's quarterly indexes carry for each CIK ("NUVEEN
   NEW YORK QUALITY INCOME MUNICIPAL FUND INC"), by an in-order token alignment
   (`name_score`) that accepts an abbreviation when it starts with the same
   letter and is a subsequence of the word (QLTY -> QUALITY, FD -> FUND, MUN ->
   MUNICIPAL), a one-letter typo in a long word (CRSP spells one fund NUVEEEN),
   a two-letter state code only as that state (MA is Massachusetts, never
   Maryland; `STATES`), and a run of single letters as one word (R M R -> RMR,
   F S K K R -> FS KKR). Numbers must agree exactly (FUND 2 is not FUND 3).
   Only EDGAR names IN USE near the completion date are candidates (a target's
   name in the two years before completion; an acquirer's from a year before to
   90 days after), which keeps a later fund that inherited a name (RMR Asia
   Pacific renamed itself RMR Real Estate Income after absorbing it) from
   matching the dead fund. A match needs score >= MIN_SCORE and a margin of
   MIN_MARGIN over the next CIK; otherwise the deal is reported UNMATCHED, never
   given the nearest name.
2. **The first merger filing.** Candidate filings, all in the 730 days before
   completion (a CEF merger completes four to twelve months after it is
   announced): any Rule 425 communication indexed under the TARGET's CIK (the
   index lists a 425 under every subject company, so a target-specific press
   release appears here), the target's merger proxy (PREM14A / DEFM14A), the
   target's or acquirer's 8-K carrying item 1.01 (a material agreement: how a
   BDC announces a merger agreement), and the ACQUIRER's N-14 8C / N-14 (the
   registration of the shares it will issue). An acquirer whose name two CIKs
   share keeps both. The announcement is the earliest candidate that passes 3.
3. **Read before it is used.** Candidates are read in date order (at most
   MAX_READ per deal). A filing dates the deal only if its full text names the
   TARGET (an EDGAR name it used, or its CRSP ticker in a ticker context); a
   filing indexed under the target must also name the ACQUIRER when it is
   known (a fund that was itself an acquirer earlier in the window has 425s
   about that deal); and an 8-K must carry merger-agreement language (item
   1.01 is any material agreement). Why each test exists, measured on the
   first pass of 2026-10-12: without the 8-K test, SUNS, OCSI and FSKR were
   dated by credit-facility 8-Ks 22-24 months early; with a "previous
   completion" cut-off instead of the text test, Eaton Vance's 2018 deal,
   completed in three tranches, lost its N-14 for the later tranches. Each
   rejected candidate is listed (`rejected`). A deal with no passing candidate
   is reported, not dated.

WHAT THE DATE MEANS (alignment)
-------------------------------
EDGAR's filing date: the submission was accepted by 17:30 ET that day (EDGAR
Filer Manual, [S]). `merger_pairs.announcement_sample` enters at the close of
the first trading day AFTER it (A+1), as the original did, so a filing made
after the close cannot be traded at a close it followed. A deal dated only by
the acquirer's N-14 may have been announced earlier by a press release that
was never filed (CEFs need not file 8-Ks): its date is an UPPER bound, and the
output says so (`date_basis`).

HOLDOUTS. No returns here. The CRSP rows come from `crsp_events` (licensed):
the per-deal output is gitignored; only the summary is committed.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events"
DATES_OUT = OUT / "merger_edgar_dates.csv"          # gitignored: CRSP permnos and tickers
SUMMARY_OUT = OUT / "merger_edgar_dates_summary.json"

MIN_SCORE = 0.85
MAX_READ = 15          # candidate filings read per deal before it is reported undated
MIN_MARGIN = 0.02
WINDOW_DAYS = 730

# The name table for CIK matching: every name used by a CIK that filed a form
# only an investment company files (FUND_FORMS) -- broader than the fetcher's
# CEF set on purpose (a target that filed none of the closed-end marker forms
# after 2008 still filed N-CSRs; an acquirer can be an ETF trust), but without
# the operating companies that file 10-Ks and 425s, which made the matcher ten
# times slower and can only add wrong candidates. A BDC is in through its N-2
# or N-54A. NAME_FORMS are the rows whose names and dates are kept.
FUND_FORMS = frozenset({"N-CSR", "N-CSRS", "N-Q", "NSAR-A", "NSAR-B", "N-PX", "NPORT-P", "N-8F",
                        "N-8F/A", "N-14 8C", "N-14", "N-2", "N-2/A", "N-54A", "N-23C-2"})
NAME_FORMS = FUND_FORMS | frozenset({"425", "DEF 14A", "PRE 14A", "10-K", "10-Q"})
ANNOUNCE_FORMS_TARGET = ("425", "PREM14A", "DEFM14A")
ANNOUNCE_FORMS_ACQ = ("N-14 8C", "N-14")

# --------------------------------------------------------------- name match

GENERIC = frozenset({"INC", "INCORPORATED", "THE", "CO", "CORP", "CORPORATION", "LLC", "LP", "FUND",
                     "FD", "FUNDS", "TRUST", "TR", "PORTFOLIO", "PORTF", "OF", "AND", "&", "SHS",
                     "COM", "NEW", "LTD", "CAP", "CAPITAL"})
ROMAN = {"II": "2", "III": "3", "IV": "4", "VI": "6", "VII": "7", "VIII": "8", "IX": "9"}
# Two-letter codes that appear in CEF names as states. A code matches its state
# (or itself) at full weight, and anything else it abbreviates only at half
# weight: "MN" is Minnesota in one name and MUNICIPAL in Invesco's "VL MN IN TR".
STATES = {"AZ": ("ARIZONA",), "CA": ("CALIFORNIA",), "CT": ("CONNECTICUT",), "FL": ("FLORIDA",),
          "GA": ("GEORGIA",), "MA": ("MASSACHUSETTS",), "MD": ("MARYLAND",), "MI": ("MICHIGAN",),
          "MN": ("MINNESOTA",), "MO": ("MISSOURI",), "NC": ("NORTH", "CAROLINA"), "NJ": ("NEW", "JERSEY"),
          "NY": ("NEW", "YORK"), "OH": ("OHIO",), "PA": ("PENNSYLVANIA",), "TX": ("TEXAS",),
          "VA": ("VIRGINIA",), "SC": ("SOUTH", "CAROLINA"), "KY": ("KENTUCKY",), "WI": ("WISCONSIN",)}


def name_tokens(name: str) -> tuple[str, ...]:
    """Upper-case word tokens with EDGAR's state suffix (/MD/), parenthetical
    asides ("(f/k/a ...)"), punctuation and roman numerals normalised, and
    digits split from letters (30SM -> 30 SM)."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"no name to tokenise: {name!r}")
    s = name.upper()
    s = re.sub(r"\([^)]*\)", " ", s)        # "(f/k/a Old Mutual/Claymore Long-Short Fund)"
    s = re.sub(r"\s*[/\\][A-Z]{2,4}[/\\]?\s*$", " ", s)
    s = s.replace("&", " & ")
    s = re.sub(r"[.,'()\"]", "", s)
    s = re.sub(r"[-/\\:;]", " ", s)
    s = re.sub(r"(\d+)([A-Z]+)", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)(\d+)", r"\1 \2", s)
    return tuple(ROMAN.get(t, t) for t in s.split())


def _subseq(c: str, e: str) -> bool:
    it = iter(e)
    return all(ch in it for ch in c)


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def token_credit(c: str, e: str) -> float:
    """How much CRSP token `c` earns against EDGAR token `e` (0 = no match)."""
    if c == e:
        return 1.0
    if "&" in (c, e):
        return 1.0 if {c, e} <= {"&", "AND"} else 0.0
    if c.isdigit() or e.isdigit():
        return 0.0
    ok = ((c[0] == e[0] and _subseq(c, e)) or (len(c) >= 5 and len(e) >= 5 and _edit1(c, e))
          # a -Y abbreviation of an -IES plural: OPPTY -> OPPORTUNITIES
          or (len(c) >= 3 and c.endswith("Y") and e.endswith("IES") and c[0] == e[0] and _subseq(c[:-1], e[:-3])))
    if not ok:
        return 0.0
    return 0.5 if c in STATES else 1.0


def _weight(t: str) -> float:
    return 2.0 if t.isdigit() else (0.25 if t in GENERIC else 1.0)


def name_score(crsp: tuple[str, ...], edgar: tuple[str, ...]) -> float:
    """In-order alignment score of a CRSP name against an EDGAR name, in [<0, 1].

    Each CRSP token earns its weight (digits 2, generic words 0.25, others 1)
    times its credit when aligned; an EDGAR token left unaligned costs 0.5
    (digits 2, generic 0.1), except trailing ones, which cost 0.1 (CRSP
    truncates names at 32 characters, so the tail of a long EDGAR name is
    expected to be missing) unless they are digits. Normalised by the CRSP
    name's total weight, so 1.0 means every CRSP token was accounted for.
    """
    n, m = len(crsp), len(edgar)

    @lru_cache(maxsize=None)
    def best(i: int, j: int) -> float:
        if i == n:
            return -sum(2.0 if edgar[k].isdigit() else 0.1 for k in range(j, m))
        if j == m:
            return 0.0
        c = crsp[i]
        opts = [best(i + 1, j),
                best(i, j + 1) - (2.0 if edgar[j].isdigit() else 0.1 if edgar[j] in GENERIC else 0.5)]
        cr = token_credit(c, edgar[j])
        if cr:
            opts.append(_weight(c) * cr + best(i + 1, j + 1))
        if c in STATES:
            words = STATES[c]
            if tuple(edgar[j:j + len(words)]) == words:
                opts.append(1.0 + best(i + 1, j + len(words)))
        k = i
        while k < n and len(crsp[k]) == 1 and crsp[k].isalpha():
            k += 1
        for kk in range(i + 2, k + 1):           # a run of single letters as one or more words
            run = "".join(crsp[i:kk])
            for ll in range(j + 1, m + 1):
                joined = "".join(edgar[j:ll])
                if joined == run:
                    opts.append(float(kk - i) + best(kk, ll))
                if len(joined) >= len(run):
                    break
        return max(opts)

    tot = sum(_weight(t) for t in crsp)
    return best(0, 0) / tot if tot else 0.0


def match_cik(crsp_name: str, names: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> dict:
    """Best EDGAR CIK for a CRSP name among names in use within [lo, hi].

    `names` has cik, company, first, last (the dates the index shows that name
    in use) and tok. Returns the best and runner-up CIK with their scores and
    a status: "matched", or why not.
    """
    t = name_tokens(crsp_name)
    cand = names[(names["last"] >= lo) & (names["first"] <= hi)]
    if cand.empty:
        return {"status": "no EDGAR names in use in the window"}
    sc = cand.assign(s=[name_score(t, e) for e in cand["tok"]])
    sc = sc.sort_values(["s", "last"], ascending=[False, False]).drop_duplicates("cik")
    b = sc.iloc[0]
    s2 = float(sc.iloc[1]["s"]) if len(sc) > 1 else -np.inf
    out = {"cik": int(b["cik"]), "edgar_name": b["company"], "score": round(float(b["s"]), 3),
           "runner_up_cik": int(sc.iloc[1]["cik"]) if len(sc) > 1 else None,
           "runner_up_name": sc.iloc[1]["company"] if len(sc) > 1 else None,
           "runner_up_score": round(s2, 3) if np.isfinite(s2) else None}
    if b["s"] < MIN_SCORE:
        out["status"] = f"best score {b['s']:.3f} < {MIN_SCORE}"
    elif b["s"] - s2 < MIN_MARGIN:
        out["status"] = f"ambiguous: margin {b['s'] - s2:.3f} < {MIN_MARGIN}"
    else:
        out["status"] = "matched"
    return out


# ------------------------------------------------------ text verification

_SUFFIX = {"INC", "INCORPORATED", "CORP", "CORPORATION", "LLC", "LP", "CO", "THE", "LTD"}
_MERGER_AGREEMENT = re.compile(r"AGREEMENT AND PLAN OF (?:MERGER|REORGANIZATION)|MERGER AGREEMENT")


def _flat(text: str) -> str:
    t = html.unescape(re.sub(r"<[^>]{0,400}>", " ", text)).upper()
    return " " + re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9&]+", " ", t)).strip() + " "


def _name_core(name: str) -> str:
    """An EDGAR name as it is written in prose: punctuation flattened, a bare
    state suffix (/MD/) and a leading THE or trailing INC/CORP/LLC dropped,
    because a press release writes "Lazard World Dividend & Income Fund
    (LOR)" for the registrant "LAZARD WORLD DIVIDEND & INCOME FUND INC"."""
    w = re.sub(r"[^A-Z0-9&]+", " ", html.unescape(re.sub(r"\([^)]*\)", " ", name)).upper()).split()
    if len(w) > 1 and len(w[-1]) == 2 and w[-1] not in ("II", "IV"):  # /MD/ -> trailing "MD"
        w = w[:-1]
    while w and w[-1] in _SUFFIX:
        w = w[:-1]
    while w and w[0] == "THE":
        w = w[1:]
    return " ".join(w)


def mentions_target(text: str, edgar_names: list[str], ticker: str | None) -> str | None:
    """How a filing names a fund, or None if it does not.

    A name counts if its words appear in order, punctuation and HTML entities
    aside (any name EDGAR shows the fund using; `_name_core`). A ticker counts
    only in a ticker context -- "(NYSE: NQN)", "(NQN)", "NYSE MKT: NQN",
    "Ticker: NQN" -- because a short ticker as a bare word (IF, GDF) matches
    prose.
    """
    flat = _flat(text)
    for nm in edgar_names:
        core = _name_core(nm)
        if len(core.split()) >= 2 and f" {core} " in flat:
            return "name"
    if isinstance(ticker, str) and ticker:
        t = re.escape(ticker.upper())
        up = html.unescape(text).upper()
        pats = [rf"\(\s*(?:NYSE|NYSE\s*MKT|NYSE\s*AMERICAN|NASDAQ|AMEX)?\s*:?\s*{t}\s*\)",
                rf"(?:NYSE|NYSE\s*MKT|NYSE\s*AMERICAN|NASDAQ|AMEX)\s*:\s*{t}(?![A-Z])",
                rf"TICKER(?:\s*SYMBOL)?\s*:?\s*{t}(?![A-Z])"]
        if any(re.search(p, up) for p in pats):
            return "ticker"
    return None


def main_document(txt: str, form: str) -> str:
    """The filing's own document out of EDGAR's complete-submission text, without
    its exhibits. The text tests read only this: an exhibit is often a credit
    agreement or an old merger agreement whose defined terms ("Merger
    Documents", "Agreement and Plan of Merger") say nothing about this filing.
    Measured 2026-10-12: FSKR's 8-K of 2020-09-17 (a credit facility, items
    1.01/2.03) passed the merger-language test on its exhibit's definitions.
    A submission with no <DOCUMENT> of that type raises."""
    for block in txt.split("<DOCUMENT>")[1:]:
        m = re.search(r"<TYPE>([^\n<]+)", block)
        if m and m.group(1).strip().upper() == form.upper():
            return block
    raise ValueError(f"no <DOCUMENT> of type {form} in the submission")


def merger_agreement_language(text: str) -> bool:
    """An 8-K item 1.01 is ANY material agreement (a credit facility, an
    advisory contract). It dates a merger only if it is the merger agreement.
    Measured 2026-10-12: without this test SUNS, OCSI and FSKR were dated by
    unrelated 8-Ks 22 to 24 months before completion."""
    return bool(_MERGER_AGREEMENT.search(_flat(text)))


# --------------------------------------------------------------- the build

def name_table(client, today: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(names, index rows): (cik, company, first, last, tok) for every name EDGAR's
    indexes show a fund using, and the index rows themselves (NAME_FORMS and the
    fetcher's event forms)."""
    from scripts.data import fetch_edgar_events as fe
    frames = []
    for y, q in fe.quarters(fe.LOOKBACK_START, today):
        url = fe.INDEX_URL.format(y=y, q=q)
        text = client.get_text(url, max_age_s=None if fe.quarter_is_closed(y, q, today) else fe.DAY)
        frames.append(fe.parse_master_index(text, label=f"{y}Q{q}",
                                            keep_forms=NAME_FORMS | set(fe.FORM_KIND)))
    idx = pd.concat(frames, ignore_index=True)
    funds = set(idx.loc[idx["form"].isin(FUND_FORMS), "cik"])
    idx = idx[idx["cik"].isin(funds)]
    names = (idx.groupby(["cik", "company"])["date_filed"].agg(first="min", last="max").reset_index())
    names["tok"] = names["company"].map(name_tokens)
    return names, idx


def crsp_sample() -> pd.DataFrame:
    """The re-run's priced merger sample, rebuilt from the same code path."""
    from scripts.events import crsp_events as ce
    from scripts.events import merger_pairs as mp
    nm, dl = ce.names(), ce.delistings()
    x = mp.flag_universe(mp.build_events(nm, dl, mp.START, mp.END), nm)
    return mp.pairable_events(x)


# Forms that make up a party's run of merger filings, and the longest silence
# inside one run: the fetcher's merger-episode rule (fetch_edgar_events
# EPISODE_GAP_DAYS["merger"]), so the two agree on what one deal is.
MERGER_SERIES_FORMS = ("425", "N-14", "N-14/A", "N-14 8C", "N-14 8C/A", "PREM14A", "DEFM14A")
EPISODE_GAP_DAYS = 180


def last_episode_start(dates: pd.Series, before: pd.Timestamp, gap_days: int = EPISODE_GAP_DAYS):
    """Start of the last run of `dates` (strictly before `before`) in which no
    two consecutive dates are more than `gap_days` apart; None if there are none.

    Measured 2026-10-12: FS KKR Capital Corp. II's 425s of August 2019 (its own
    2019 merger with FSIC III, IV and CCT II) named both it and FSK and passed
    every text test, dating its 2021 merger into FSK 467 days early. The runs
    are separated by eleven months of silence; this keeps only the last run.
    """
    d = pd.to_datetime(pd.Series(dates)).sort_values()
    d = d[d < before]
    if d.empty:
        return None
    gaps = d.diff().dt.days.fillna(0).to_numpy()
    breaks = [i for i in range(len(d)) if gaps[i] > gap_days]
    return d.iloc[breaks[-1] if breaks else 0]


def _cik(v) -> int:
    """A matched CIK as an int (a pandas column with a gap holds floats)."""
    if pd.isna(v) or float(v) != int(v):
        raise ValueError(f"not a CIK: {v!r}")
    return int(v)


def date_deals(client, today: date) -> tuple[pd.DataFrame, dict]:
    from scripts.data.edgar_client import filing_txt_url
    names, idx = name_table(client, today)
    ev = crsp_sample()
    rows = []
    for e in ev.itertuples():
        C = pd.Timestamp(e.dlstdt)
        rec = {"permno": int(e.permno), "ticker": e.ticker, "comnam": e.comnam, "nwperm": int(e.nwperm),
               "a_ticker": e.a_ticker, "a_comnam": e.a_comnam, "completion": C.date()}
        t = match_cik(e.comnam, names, C - pd.Timedelta(days=WINDOW_DAYS), C)
        rec.update({f"t_{k}": v for k, v in t.items()})
        if isinstance(e.a_comnam, str):
            a = match_cik(e.a_comnam, names, C - pd.Timedelta(days=365), C + pd.Timedelta(days=90))
        else:
            a = {"status": "acquirer has no CRSP name"}
        rec.update({f"a_{k}": v for k, v in a.items()})
        rows.append(rec)
    d = pd.DataFrame(rows)

    idx = idx.copy()
    by_cik = {c: g for c, g in idx.groupby("cik")}
    sub_cache: dict[int, pd.DataFrame] = {}
    from scripts.data import fetch_edgar_events as fe

    def subs(cik: int) -> pd.DataFrame:
        if cik not in sub_cache:
            sub_cache[cik] = fe.submissions(client, cik, max_age_s=30 * fe.DAY)
        return sub_cache[cik]

    def names_of(ciks) -> list[str]:
        return list(names.loc[names["cik"].isin(ciks), "company"])

    out = []
    for r in d.itertuples():
        C = pd.Timestamp(r.completion)
        lo = C - pd.Timedelta(days=WINDOW_DAYS)
        rec = {"permno": r.permno}
        t_ciks = [_cik(r.t_cik)] if r.t_status == "matched" else []
        # An acquirer whose name two CIKs share (a fund and its successor) keeps
        # both: the text test below decides which one filed for THIS target.
        a_ciks = ([_cik(r.a_cik)] if r.a_status == "matched" else
                  [_cik(r.a_cik), _cik(r.a_runner_up_cik)] if str(r.a_status).startswith("ambiguous") else [])
        cands = []
        # Candidates come from the deal's LAST run of merger filings before
        # completion (`last_episode_start`), counting filings indexed under
        # either party: an earlier run is an earlier deal, and a filing by the
        # other party keeps this deal's run alive across a quiet spell at one.
        series = pd.concat([by_cik.get(c, pd.DataFrame(columns=idx.columns)) for c in t_ciks + a_ciks]
                           or [pd.DataFrame(columns=idx.columns)])
        series = series[(series["date_filed"] >= lo) & series["form"].isin(MERGER_SERIES_FORMS)]
        ep0 = last_episode_start(series["date_filed"], C)
        start = ep0 if ep0 is not None else lo
        rec["deal_run_start"] = None if ep0 is None else ep0.date()
        for who, ciks, forms in (("target", t_ciks, ANNOUNCE_FORMS_TARGET), ("acquirer", a_ciks, ANNOUNCE_FORMS_ACQ)):
            for cik in ciks:
                g = by_cik.get(cik, pd.DataFrame(columns=idx.columns))
                g = g[(g["date_filed"] >= start) & (g["date_filed"] < C) & g["form"].isin(forms)]
                cands += [(x.date_filed, x.form, cik, x.accession, who) for x in g.itertuples()]
        # 8-K item 1.01 (how a BDC announces a merger agreement), from the submissions API
        for who, ciks in (("target", t_ciks), ("acquirer", a_ciks)):
            for cik in ciks:
                g = by_cik.get(cik, pd.DataFrame(columns=idx.columns))
                if not ((g["form"] == "8-K") & (g["date_filed"] >= lo) & (g["date_filed"] < C)).any():
                    continue
                sb = subs(cik)
                # an 8-K may precede the run's first 425/N-14 (a BDC signs, files
                # the 8-K, then the 425s), but not by more than one gap
                sb = sb[(sb["form"] == "8-K") & (sb["filingDate"] >= start - pd.Timedelta(days=EPISODE_GAP_DAYS))
                        & (sb["filingDate"] >= lo) & (sb["filingDate"] < C)
                        & sb["items"].fillna("").str.contains(r"(?:^|,)1\.01(?:,|$)")]
                cands += [(x.filingDate, "8-K 1.01", cik, x.accessionNumber, who) for x in sb.itertuples()]
        cands.sort(key=lambda z: (z[0], z[3]))
        rec["n_candidates"] = len(cands)
        t_names, a_names = names_of(t_ciks), names_of(a_ciks)
        chosen, tried, rejects = None, 0, []
        for dt_, form, cik, acc, who in cands:
            if tried >= MAX_READ:
                break
            tried += 1
            txt = main_document(client.get_text(filing_txt_url(cik, acc)), form.split()[0] if form.startswith("8-K") else form)
            how = mentions_target(txt, t_names, r.ticker)
            if not how:
                rejects.append(f"{form} {pd.Timestamp(dt_).date()}: target not named")
                continue
            names_acq = bool(mentions_target(txt, a_names, r.a_ticker)) if a_names else None
            # A filing indexed under the TARGET must also name the acquirer when
            # we know it: a fund that was itself an acquirer earlier in the
            # window has 425s about that other deal, and they name it too.
            if who == "target" and a_names and not names_acq:
                rejects.append(f"{form} {pd.Timestamp(dt_).date()}: acquirer not named")
                continue
            if form == "8-K 1.01" and not merger_agreement_language(txt):
                rejects.append(f"{form} {pd.Timestamp(dt_).date()}: not a merger agreement")
                continue
            chosen = (dt_, form, cik, acc, who, how, names_acq)
            break
        rec["n_read"] = tried
        rec["rejected"] = "; ".join(rejects) if rejects else None
        rec["why_undated"] = None
        if chosen:
            dt_, form, cik, acc, who, how, names_acq = chosen
            rec.update({"ann_date": pd.Timestamp(dt_).date(), "ann_form": form, "ann_cik": cik,
                        "ann_accession": acc, "ann_party": who, "ann_verified_by": how,
                        "ann_names_acquirer": names_acq,
                        "date_basis": ("registration (upper bound)" if form in ANNOUNCE_FORMS_ACQ
                                       else "merger communication")})
        else:
            rec["ann_date"] = None
            rec["why_undated"] = ("no candidate filing" if not cands else
                                  f"none of the {tried} candidates read passed the text test")
        out.append(rec)
    res = d.merge(pd.DataFrame(out), on="permno", how="left")
    res["group_acq_x_ann"] = res["nwperm"].astype(str) + "@" + res["ann_date"].astype(str)
    summ = {
        "events": len(res), "groups_acq_x_completion": int(res.groupby(["nwperm", "completion"]).ngroups),
        "target_match": res["t_status"].value_counts().to_dict(),
        "acquirer_match": res["a_status"].value_counts().to_dict(),
        "dated": int(res["ann_date"].notna().sum()),
        "undated_reasons": res.loc[res["ann_date"].isna(), "why_undated"].fillna("(match failed)").value_counts().to_dict(),
        "by_form": res["ann_form"].value_counts().to_dict(),
        "by_basis": res["date_basis"].value_counts().to_dict(),
        "verified_by": res["ann_verified_by"].value_counts().to_dict(),
        "names_acquirer": res["ann_names_acquirer"].astype(str).value_counts().to_dict(),
        "deals_with_rejected_candidates": int(res["rejected"].notna().sum()),
        "days_ann_to_completion": res.assign(dd=(pd.to_datetime(res["completion"]) - pd.to_datetime(res["ann_date"])).dt.days)
                                     ["dd"].describe().round(1).to_dict(),
        "fetch": {"requests": client.n_requests, "cache_hits": client.n_cache_hits},
    }
    return res, summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    from scripts.data.edgar_client import EdgarClient
    client = EdgarClient(offline=a.offline)
    today = date.fromisoformat(a.today) if a.today else date.today()
    res, summ = date_deals(client, today)
    res.to_csv(DATES_OUT, index=False)
    SUMMARY_OUT.write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
