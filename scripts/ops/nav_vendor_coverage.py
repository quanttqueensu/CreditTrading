"""Does a vendor's public ticker list carry the deployed CEFs' NAV symbols, and how fresh are they?

    python3 scripts/ops/nav_vendor_coverage.py --zip <path to supported_tickers.zip> --since 2026-10-01

WHY (team lead, 2026-10-19: "or find a workaround" for the NAV source;
`results/ops/NAV_SOURCE_WORKAROUND_2026-10-19.md` §2, `docs/REFERENCES.md` §12ar).
The live NAV path rests on sources whose terms restrict automated commercial use
(§12ad). Before anyone pays for a feed, two things must be measured rather than
assumed: whether the vendor lists each deployed fund's NAV symbol (`X<TK>X`, the
Nasdaq Fund Network shape), and under which exchange code, because the code names
the upstream and NFN's licence (§6) bars trading use by any Recipient. Tiingo
publishes such a list (`supported_tickers.csv`: ticker, exchange, assetType,
priceCurrency, startDate, endDate) at the URL its end-of-day documentation gives.

NO FETCHER, BY DESIGN. Tiingo's terms forbid software that would "scrape" or
download data "from any web pages contained in the Website". The zip is a file its
documentation offers for download, so a person downloads it once by hand
(`https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip`) and this
script reads that local copy. Nothing here opens a socket. Never commit the file:
it is vendor content and this repository is public. Output goes to stdout only.

WHAT IT REPORTS. For each name in the frozen universe (`scripts/cef/spec.py`
`UNIVERSE`, read at run time, never a literal): every row whose ticker is the
name itself or `X<name>X`, with exchange, assetType, startDate and endDate. A name
with no NAV-symbol row prints ABSENT: that is the measurement, not a gap filled.
Then the distribution of `endDate` over all `X[A-Z]{3}X` tickers whose endDate is
on or after `--since`, which shows how many NAV symbols had the latest date when
the vendor wrote the file. The file's own timestamp (the zip member's) is printed
verbatim; it states no time zone.

WHAT IT DOES NOT SAY. Whether the vendor's API serves those NAVs on time (endDate
is "the latest date we have price data available", per the vendor's docs, but how
it relates to the API's real-time state is not established), whether its values
agree with the sponsors', or whether its licence permits trading on them.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

MEMBER = "supported_tickers.csv"
NEED_COLS = ("ticker", "exchange", "assetType", "startDate", "endDate")
NAV_SYMBOL_RE = re.compile(r"X[A-Z]{3}X")


class CoverageError(RuntimeError):
    """The file is not the documented ticker list. Names what was missing."""


def read_rows(zip_path: Path) -> tuple[list[dict], str]:
    """(rows, the member's own timestamp 'YYYY-MM-DD HH:MM:SS') from the vendor's zip.

    Raises if the member or a documented column is missing: reading endDate from
    the wrong column would be a confident wrong number.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if MEMBER not in names:
            raise CoverageError(f"{zip_path}: no member {MEMBER!r} (members: {names})")
        info = zf.getinfo(MEMBER)
        stamp = dt.datetime(*info.date_time).strftime("%Y-%m-%d %H:%M:%S")
        text = zf.read(MEMBER).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in NEED_COLS if c not in (reader.fieldnames or [])]
    if missing:
        raise CoverageError(f"{zip_path}:{MEMBER} lacks column(s) {missing}; "
                            f"header is {reader.fieldnames}")
    return list(reader), stamp


def coverage(rows: list[dict], universe: list[str]) -> dict[str, dict]:
    """Per fund: its own listing rows and its NAV-symbol rows (`X<TK>X`), as written."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["ticker"].upper()].append(r)
    out = {}
    for tk in universe:
        out[tk] = {"listing": by.get(tk.upper(), []),
                   "nav_symbol": f"X{tk.upper()}X",
                   "nav": by.get(f"X{tk.upper()}X", [])}
    return out


def end_date_counts(rows: list[dict], since: dt.date) -> collections.Counter:
    """endDate counts over NAV-shaped tickers (`X[A-Z]{3}X`) with endDate >= since.

    A row whose endDate is blank or not an ISO date is skipped only if it is not
    NAV-shaped; a NAV-shaped row with an unreadable endDate raises, naming it.
    """
    counts = collections.Counter()
    for r in rows:
        if not NAV_SYMBOL_RE.fullmatch(r["ticker"].upper()):
            continue
        raw = (r["endDate"] or "").strip()
        if not raw:
            continue                       # never priced: not on or after `since`
        try:
            d = dt.date.fromisoformat(raw)
        except ValueError as e:
            raise CoverageError(f"{r['ticker']}: endDate {raw!r} is not an ISO date") from e
        if d >= since:
            counts[d.isoformat()] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zip", required=True, type=Path,
                    help="local copy of the vendor's supported_tickers.zip (downloaded by hand)")
    ap.add_argument("--since", required=True, type=dt.date.fromisoformat,
                    help="count NAV-shaped tickers whose endDate is on or after this date")
    a = ap.parse_args(argv)

    from scripts.cef.spec import UNIVERSE   # a JSON read; at run time, never a literal

    rows, stamp = read_rows(a.zip)
    print(f"file {a.zip.name}: member {MEMBER} stamped {stamp} (no time zone stated); "
          f"{len(rows)} rows")
    cov = coverage(rows, list(UNIVERSE))
    n_listed = 0
    for tk, c in cov.items():
        if c["nav"]:
            n_listed += 1
            for r in c["nav"]:
                print(f"  {tk:4s} {c['nav_symbol']}: exchange={r['exchange']} "
                      f"assetType={r['assetType']} startDate={r['startDate']} "
                      f"endDate={r['endDate']}")
        else:
            print(f"  {tk:4s} {c['nav_symbol']}: ABSENT")
    print(f"NAV symbols listed: {n_listed} of {len(cov)} deployed names")
    counts = end_date_counts(rows, a.since)
    total = sum(counts.values())
    print(f"NAV-shaped tickers with endDate >= {a.since}: {total}")
    for d in sorted(counts, reverse=True):
        print(f"  {d}: {counts[d]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
