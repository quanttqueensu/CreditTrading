"""Census of term and target-term closed-end funds in CRSP. Read-only.

    python3 scripts/data/term_cef_census.py

WHY THIS EXISTS
---------------
`results/cef/SCALING_RESEARCH_2026-10-08.md` proposes a discount pull-to-par
idea. A CEF with a fixed termination date (a "term" or "target term" trust)
liquidates at NAV, or tenders at NAV, on a known date. If so, its discount must
converge to about zero, like a bond's price to par. Before anyone designs that
test, the desk needs to know such funds exist in the data, how many there are,
and how many have already terminated, since those give the historical sample. This
lists them from CRSP names. Nothing here is guessed.

WHAT IT DOES NOT ESTABLISH
--------------------------
A name containing "TERM" or a year is not a contract. The actual termination
date, any extension or conversion option, and whether a "target term" fund aims
to return its IPO price must be read from each fund's N-2 or N-CSR before use.
Some matches are not term funds at all: "INTERMEDIATE", "INTERMARKET",
"ALTERMAN", "LONG TERM". Each row is printed so a reader can strike them; nothing
is filtered silently. The term-CEF pass of 2026-10-09
(`results/cef/SCALING_RESEARCH_2026-10-08.md` §7) struck ALF, MIN, PGT, CMK, KGT,
SBI, MUI, MNE, BTA and CIF.

NAMES ARE STALE AND INCOMPLETE. CRSP names lag: JLS kept "TERM" until 2024 after
dropping its term in 2019. The filter also MISSES three groups:
- abbreviated names (TM, TGT, TRGT, DEF OPP, DEFINED), e.g. JHA, JHD, NIQ, BHL,
  MTT, IGI, GDO, DMO, HYI;
- funds with 19xx dates;
- every fund with an eligible-tender-offer or limited-term clause and no marker
  in its name, e.g. PDO (a deployed name, dissolution on or about 2033-01-27),
  PAXS, PDX, DLY, NMCO, the RMI family, XFLT and FINS.

So this is a lower bound. A real census reads N-2 filings (EDGAR full text for
"eligible tender offer" or "Dissolution Date").
CRSP ends 2024-12-31, so `last_dt` at that date means "alive at CRSP's end", not
"alive today".

HOLDOUT. Any name in `data/cef/cef_universe.csv` (the deployed 13 plus the
sealed comparison set, H9) is flagged `in_universe`. A study that computes
returns on a flagged name consumes the holdout and needs the team lead's ruling.
The flag is by TICKER, so a recycled ticker gives a false positive. BGT was a
Blackstone/BlackRock term trust in 1990–2002 and is a different fund in the
universe file today. Check the name before treating a flag as real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))


def main() -> int:
    from src.data.r2 import connect, r2_path

    con = connect()
    names = r2_path("crsp_a_stock", "stocknames")
    # Share codes 14 and 44 are closed-end funds (results/data/cef_crosscheck_crsp_2026-09-28.md).
    df = con.execute(
        f"SELECT ticker, comnam, shrcd, min(namedt) AS first_dt, max(nameenddt) AS last_dt "
        f"FROM read_parquet('{names}') "
        f"WHERE shrcd IN (14, 44) AND (comnam ILIKE '%TERM%' OR regexp_matches(comnam, ' 20[0-9][0-9]')) "
        f"GROUP BY 1, 2, 3 ORDER BY first_dt").fetchdf()
    uni = set(pd.read_csv(REPO / "data" / "cef" / "cef_universe.csv")["ticker"])
    df["in_universe"] = df["ticker"].isin(uni)
    df["alive_at_crsp_end"] = pd.to_datetime(df["last_dt"]) >= pd.Timestamp("2024-12-31")
    pd.set_option("display.width", 200)
    print(df.to_string(max_colwidth=45))
    print(f"\n{len(df)} name records; {int(df['alive_at_crsp_end'].sum())} alive at CRSP's last date; "
          f"{int(df['in_universe'].sum())} in data/cef/cef_universe.csv (holdout/deployed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
