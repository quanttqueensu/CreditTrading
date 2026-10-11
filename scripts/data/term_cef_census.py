"""Census of term and target-term closed-end funds in CRSP. Read-only.

    python3 scripts/data/term_cef_census.py            # prints; --csv also writes results/events/term_cef_census.csv

WHY THIS EXISTS
---------------
`results/cef/SCALING_RESEARCH_2026-10-08.md` proposes a discount pull-to-par
idea. A CEF with a fixed termination date (a "term" or "target term" trust) is
meant to liquidate, or tender at NAV, near a known date, so its discount should
converge towards zero, like a bond's price to par. (Not always: boards can
extend a term by 6-24 months, and votes can remove it with no tender -- DMO
2019, XFLT 2024; SCALING §7, row 2c.) Before anyone designs that test, the desk
needs to know such funds exist in the data, how many there are, and how many
have already terminated, since those give the historical sample. This lists
them from CRSP names. Nothing here is guessed.

THE FILTER, AND HOW IT WAS CORRECTED (2026-10-11)
-------------------------------------------------
Until 2026-10-11 the filter was `comnam ILIKE '%TERM%' OR ' 20xx'`. The
2026-10-09 targeted pass (SCALING §7.4) found it missed three groups; each is
now a separate rule, and every row says which rule(s) matched it (`match`):

- `term`     -- "TERM" anywhere in the name (also catches DEFTERM).
- `abbrev`   -- an abbreviated marker as a whole word: TM, TRM, TT, TGT,
               TRGT, TARGET, DEF / DEFINED (e.g. JHA "DEC18 TRGT TM", NIQ
               "QLTY MUNI TM", NHA "TGT TRM", XFLT "ALT INC TT", HYI "HIGH YLD
               DEF OP", MTT/IGI/GDO/DMO "DEF OPP"). It also catches "SH TM"
               (short term, JGT) and DEFINED STRATEGY (DSF): printed, not dropped.
- `year`     -- a four-digit year 19xx or 20xx as a whole word (TGB "TRIPLE A
               & GOVT SER 1997", and the 20xx-dated targets as before).
- `tender_list` -- funds with an eligible-tender-offer or limited-term clause
               and NO marker in the name. A name filter cannot find them; they
               come from the 2026-10-09 agent's EDGAR full-text search for
               "eligible tender offer" in N-2 filings (383 hits from 2010 on,
               [V] count; the ticker list itself [S], from that transcript).
               Matched by TICKER, so every hit is printed with its name.
               When the EDGAR event fetcher (plan item 0.7) exists, this list
               must be re-derived from it rather than maintained by hand.

WHAT IT DOES NOT ESTABLISH
--------------------------
A name containing "TERM" or a year is not a contract. The actual termination
date, any extension or conversion option, and whether a "target term" fund aims
to return its IPO price must be read from each fund's N-2 or N-CSR before use.
Some matches are not term funds at all: "INTERMEDIATE", "INTERMARKET",
"ALTERMAN", "LONG TERM", "SHORT TERM", or TM as a trademark (MGC "SMALLCAP FUND
INC TM"). Each row is printed so a reader can strike them; nothing is filtered
silently. The 2026-10-09 pass struck ALF, MIN, PGT, CMK, KGT, SBI, MUI, MNE,
BTA and CIF; those rows carry `struck_2026_10_09 = True` rather than being
dropped.

NAMES ARE STALE. CRSP names lag: JLS kept "TERM" until 2024 after dropping its
term in 2019. So this is still a lower bound. A real census reads N-2 filings
(EDGAR full text for "eligible tender offer" or "Dissolution Date").
CRSP ends 2024-12-31, so `last_dt` at that date means "alive at CRSP's end",
not "alive today".

HOLDOUT. Any name in `data/cef/cef_universe.csv` (the deployed 13 plus the
comparison set, H9) is flagged `in_universe`. A study that computes returns on
a flagged name consumes the comparison set, which since 2026-10-09 is open for
event trades only through a pre-registered test that says so (`docs/SYSTEM.md`
§5). The flag is by TICKER, so a recycled ticker gives a false positive. BGT
was a Blackstone/BlackRock term trust in 1990-2002 (permno 75610) and is a
different fund in the universe file today. Check the name before treating a
flag as real.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

# Rule patterns, applied to the upper-case CRSP name in Python so each rule
# can be reported separately (module docstring).
RULES = {
    "term": re.compile(r"TERM"),
    "abbrev": re.compile(r"\b(TM|TRM|TT|TGT|TRGT|TARGET|DEF|DEFINED)\b"),
    "year": re.compile(r"\b(19|20)\d\d\b"),
}
# Eligible-tender-offer / limited-term funds with no marker in the name
# (2026-10-09 agent, EDGAR full-text search; [S], see the module docstring).
TENDER_CLAUSE_TICKERS = ("PDO", "PAXS", "PDX", "DLY", "WDI", "NPCT", "NPFD", "NDMO", "NMCO", "PTA",
                         "MIO", "RMI", "RMM", "RFM", "RFMZ", "RMMZ", "SDHY", "TBLD", "XFLT", "FINS")
STRUCK_2026_10_09 = ("ALF", "MIN", "PGT", "CMK", "KGT", "SBI", "MUI", "MNE", "BTA", "CIF")


def match_rules(comnam: str, ticker: str) -> list[str]:
    """Which census rules a CRSP name record matches (empty list: none)."""
    n = str(comnam).upper()
    hits = [k for k, rx in RULES.items() if rx.search(n)]
    if ticker in TENDER_CLAUSE_TICKERS:
        hits.append("tender_list")
    return hits


def census(rec: pd.DataFrame) -> pd.DataFrame:
    """Filter CRSP CEF name records (ticker, comnam, shrcd, first_dt, last_dt)."""
    rec = rec.copy()
    rec["match"] = [",".join(match_rules(c, t)) for c, t in zip(rec["comnam"], rec["ticker"])]
    return rec[rec["match"] != ""].reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Census of term and target-term CEFs in CRSP")
    ap.add_argument("--csv", action="store_true", help="also write results/events/term_cef_census.csv")
    args = ap.parse_args(argv)
    from src.data.r2 import connect, r2_path

    con = connect()
    names = r2_path("crsp_a_stock", "stocknames")
    # Share codes 14 and 44 are closed-end funds (results/data/cef_crosscheck_crsp_2026-09-28.md).
    rec = con.execute(
        f"SELECT ticker, comnam, shrcd, min(namedt) AS first_dt, max(nameenddt) AS last_dt "
        f"FROM read_parquet('{names}') WHERE shrcd IN (14, 44) "
        f"GROUP BY 1, 2, 3").fetchdf()
    df = census(rec).sort_values("first_dt").reset_index(drop=True)
    uni = set(pd.read_csv(REPO / "data" / "cef" / "cef_universe.csv")["ticker"])
    df["in_universe"] = df["ticker"].isin(uni)
    df["alive_at_crsp_end"] = pd.to_datetime(df["last_dt"]) >= pd.Timestamp("2024-12-31")
    df["struck_2026_10_09"] = df["ticker"].isin(STRUCK_2026_10_09)
    missing = sorted(set(TENDER_CLAUSE_TICKERS) - set(df["ticker"]))
    pd.set_option("display.width", 220)
    print(df.to_string(max_colwidth=40))
    old = df["match"].str.contains("term") | df["comnam"].str.contains(r" 20[0-9][0-9]", regex=True)
    print(f"\n{len(df)} name records ({int(old.sum())} would have matched the pre-2026-10-11 filter); "
          f"by rule: " + ", ".join(f"{k} {int(df['match'].str.contains(k).sum())}"
                                   for k in ("term", "abbrev", "year", "tender_list")))
    print(f"{int(df['alive_at_crsp_end'].sum())} alive at CRSP's last date; "
          f"{int(df['in_universe'].sum())} in data/cef/cef_universe.csv (holdout/deployed, by ticker); "
          f"{int(df['struck_2026_10_09'].sum())} records of tickers struck on 2026-10-09")
    print(f"tender-clause tickers with no CRSP CEF name record (listed after CRSP's end, or not a CEF "
          f"share code): {missing or 'none'}")
    if args.csv:
        out = REPO / "results" / "events" / "term_cef_census.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
