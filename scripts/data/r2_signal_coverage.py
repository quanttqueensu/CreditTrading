"""Which candidate signals the R2 mirror can actually backtest. Read-only.

    python3 scripts/data/r2_signal_coverage.py     # writes results/data/R2_SIGNAL_COVERAGE.md

WHY THIS EXISTS
---------------
`results/cef/RESEARCH_AGENDA_2026-10-08.md` ranks new signals and legs partly by
whether the mirror can test them. Three of those judgements turn on facts that
were open questions in `docs/DATA.md` §6 or were never measured:

  1. Does `crsp_q_mutualfunds` hold our CEFs at all? If it did, it would be an
     independent NAV history (DATA.md §6 Q1). Measured here by ticker against
     the current header AND the header history, because CRSP keys funds by
     `crsp_fundno` and a CEF could have been listed under an earlier ticker.
  2. If not, what does it hold that a CEF signal could use? Open-end credit
     funds share the CEFs' retail base (docs/BRIEF.md M1, M3), so their
     aggregate flows by Lipper class are a candidate sub-class sentiment
     series. Counted here by Lipper class, with the class's date span.
  3. Are the ETFs a NAV nowcast, a NAV hedge or a credit-trend leg would trade
     (HYG, JNK, BKLN, ...) in the CRSP stock file, and over which dates?

Ticker -> PERMNO is by `stocknames` date range, and EVERY match is reported
with its share code and name. Tickers are recycled (DSL was Downey Financial
until 2008, results/data/cef_crosscheck_crsp_2026-09-28.md), so nothing is
filtered silently: the reader sees which PERMNO is the ETF (share code 73).

It never writes to the bucket. The only output is the local markdown file. A
table that is absent raises, naming it: a coverage report that silently skipped
a table would answer the question wrongly.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "cef"))

OUT_PATH = REPO / "results" / "data" / "R2_SIGNAL_COVERAGE.md"
UNIVERSE_CSV = REPO / "data" / "cef" / "cef_universe.csv"

# Lipper classes of open-end funds whose holdings overlap a credit CEF
# sub-class. Codes as CRSP `fund_style.lipper_class` stores them; the report
# prints CRSP's own class name beside each so a wrong code is visible.
CREDIT_LIPPER = ("HY", "LP", "GM", "IMD", "HM", "SIM", "MSI", "EMD", "BBB",
                 "A", "IID", "SII", "GLI", "USM", "FLX")

# The ETFs a nowcast, a NAV hedge or a trend leg would use, one per sub-class
# plus the Treasury controls the graveyard demands (leadlag, short-pressure).
ETFS = ("HYG", "JNK", "BKLN", "SRLN", "LQD", "MUB", "EMB", "PFF", "TLT", "IEF")


def _cols(con, path: str) -> list[str]:
    return [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]


def _require(con, path: str, cols: tuple[str, ...]) -> None:
    have = set(_cols(con, path))
    missing = [c for c in cols if c not in have]
    if missing:
        raise RuntimeError(f"{path.split('/wrds/')[-1]} lacks columns {missing}")


def main() -> int:
    from src.data.r2 import connect, r2_path
    import spec  # scripts/cef/spec.py, the only authority on the universe

    con = connect()
    hdr = r2_path("crsp_q_mutualfunds", "fund_hdr")
    hh = r2_path("crsp_q_mutualfunds", "fund_hdr_hist")
    sty = r2_path("crsp_q_mutualfunds", "fund_style")
    tna = r2_path("crsp_q_mutualfunds", "monthly_tna")
    flw = r2_path("crsp_q_mutualfunds", "fund_flows")
    names = r2_path("crsp_a_stock", "stocknames")
    dsf = r2_path("crsp_a_stock", "dsf")
    for p, c in ((hdr, ("ticker", "crsp_fundno")), (hh, ("ticker", "crsp_fundno")),
                 (sty, ("crsp_fundno", "lipper_class", "begdt", "enddt")),
                 (tna, ("crsp_fundno", "caldt", "mtna")),
                 (flw, ("crsp_portno", "trans_dt")),
                 (names, ("permno", "ticker", "namedt", "nameenddt", "shrcd", "comnam")),
                 (dsf, ("permno", "date"))):
        _require(con, p, c)

    out: list[str] = []
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out += [f"# R2 coverage for candidate signals",
            "",
            f"**Run:** {now} by `scripts/data/r2_signal_coverage.py`. Read-only. "
            "True as of that timestamp only -- re-run before quoting a figure.",
            ""]

    # 1. CEFs in CRSP MF, by ticker, current header and history.
    deployed = list(spec.UNIVERSE)
    wider = pd.read_csv(UNIVERSE_CSV)["ticker"].tolist()
    tickers = sorted(set(deployed) | set(wider))
    tl = ",".join(f"'{t}'" for t in tickers)
    cur = con.execute(f"SELECT DISTINCT ticker FROM read_parquet('{hdr}') "
                      f"WHERE ticker IN ({tl})").fetchdf()
    hist = con.execute(f"SELECT DISTINCT ticker FROM read_parquet('{hh}') "
                       f"WHERE ticker IN ({tl})").fetchdf()
    out += ["## 1. Do our CEFs appear in `crsp_q_mutualfunds`?", "",
            f"Tickers tested: the {len(deployed)} deployed (spec `UNIVERSE`) and the "
            f"{len(wider)} in `data/cef/cef_universe.csv`, {len(tickers)} distinct.", "",
            f"- matched in `fund_hdr.ticker`: **{len(cur)}** {sorted(cur['ticker'])}",
            f"- matched in `fund_hdr_hist.ticker`: **{len(hist)}** {sorted(hist['ticker'])}",
            "", "A match would still need its fund name read: a ticker match is not "
            "an identity. No match means this table is not an independent NAV "
            "source for the book.", ""]

    # 2. Open-end credit funds by Lipper class.
    cl = ",".join(f"'{c}'" for c in CREDIT_LIPPER)
    lip = con.execute(
        f"SELECT lipper_class, any_value(lipper_class_name) AS class_name, "
        f"count(DISTINCT crsp_fundno) AS funds, min(begdt) AS first, max(enddt) AS last "
        f"FROM read_parquet('{sty}') WHERE lipper_class IN ({cl}) "
        f"GROUP BY 1 ORDER BY funds DESC").fetchdf()
    t_rng = con.execute(f"SELECT min(caldt), max(caldt), count(*) "
                        f"FROM read_parquet('{tna}')").fetchone()
    f_rng = con.execute(f"SELECT min(trans_dt), max(trans_dt), count(*) "
                        f"FROM read_parquet('{flw}')").fetchone()
    out += ["## 2. Open-end credit funds (a sub-class retail-flow series)", "",
            "Distinct `crsp_fundno` per Lipper class in `fund_style` (share classes "
            "of one portfolio count separately; aggregate by `crsp_portno` before "
            "summing flows).", "",
            lip.to_markdown(index=False), "",
            f"- `monthly_tna`: {t_rng[0]} .. **{t_rng[1]}**, {t_rng[2]:,} rows",
            f"- `fund_flows`: {f_rng[0]} .. **{f_rng[1]}**, {f_rng[2]:,} rows", ""]

    # 3. ETFs in the CRSP stock file.
    el = ",".join(f"'{t}'" for t in ETFS)
    m = con.execute(
        f"SELECT ticker, permno, shrcd, comnam, namedt, nameenddt "
        f"FROM read_parquet('{names}') WHERE ticker IN ({el}) "
        f"ORDER BY ticker, namedt").fetchdf()
    perms = ",".join(str(int(p)) for p in m["permno"].unique()) or "NULL"
    rng = con.execute(
        f"SELECT permno, min(date) AS first, max(date) AS last, count(*) AS days "
        f"FROM read_parquet('{dsf}') WHERE permno IN ({perms}) GROUP BY 1").fetchdf()
    m = m.merge(rng, on="permno", how="left")
    absent = sorted(set(ETFS) - set(m["ticker"]))
    out += ["## 3. Hedge / nowcast / trend ETFs in `crsp_a_stock`", "",
            "Every `stocknames` row for each ticker, with that PERMNO's `dsf` span. "
            "Share code 73 is an ETF; other codes are recycled tickers.", "",
            m.to_markdown(index=False), "",
            f"- tickers with no `stocknames` row: **{absent}**", ""]

    OUT_PATH.write_text("\n".join(out))
    print("\n".join(out))
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
