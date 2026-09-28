"""What is actually in the R2 WRDS mirror: columns, row counts, date ranges. Read-only.

    python3 scripts/data/r2_catalog.py            # writes results/data/R2_CATALOG.md

WHY THIS EXISTS
---------------
Research on this desk has been burned more by confident wrong numbers than by
missing ones (CLAUDE.md, data rules). The mirror's contents were listed once by
hand on 2026-09-28; a column name or a last date recalled from that listing is
exactly the kind of recalled figure the rules say to fetch instead. So before
any script keys on `dsf.prc` or on "CRSP ends 2025-12-31", it reads this file,
which states what the bucket held WHEN THIS RAN, with the timestamp on top.
Staleness is visible, not implied: re-run it.

WHAT IT MEASURES, AND HOW
-------------------------
For every object under each schema in `LIST_SCHEMAS` and each options
underlying in `OPTION_SYMBOLS`: the object keys (bucket name redacted to
`<bucket>`; it is configuration, and the report is committed). Plus every
underlying present under `options/` with its first and last month file.

For each table in `CURATED` (the research-relevant ones):
  * columns and DuckDB types      -- `DESCRIBE`, reads the parquet footer only;
  * row count                     -- `count(*)`, which DuckDB answers from
                                     footer metadata;
  * min/max of every DATE- or TIMESTAMP-typed column -- a real scan of that
    one column. A date stored as a string or an integer is NOT parsed; the
    report says "no DATE/TIMESTAMP-typed column" and lists the columns, and
    the reader decides. Parsing it here would be guessing a format.

A curated table that is not found at `s3://<bucket>/wrds/<schema>/<table>.parquet`
is recorded as ABSENT -- a finding, not a crash -- and the script exits 1
after writing the report, so a scheduled run cannot report success over a
missing table. The curated names below are the ones the team lead listed on
2026-09-28 plus the CRSP name-history tables the ticker->permno map needs
(`stocknames`, `dsenames`); whether the mirror holds either is precisely what
this run finds out.

It never writes to the bucket. The only output is the local markdown file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

OUT_PATH = REPO / "results" / "data" / "R2_CATALOG.md"

# Schemas whose full object listing goes into the report (team lead's listing,
# 2026-09-28). Listing is keys only -- cheap -- so TRACE is listed even though
# none of its tables is deep-described.
LIST_SCHEMAS = ("crsp_a_stock", "crsp_q_mutualfunds", "trace_enhanced",
                "trace_standard", "ff_all", "frb_all")
OPTION_SYMBOLS = ("SPY", "QQQ", "TLT", "IWM", "GLD", "SLV")

# (schema, table): the tables research reads first. Everything else in the
# listing can be described on demand by adding it here.
CURATED = (
    ("crsp_a_stock", "dsf"),          # CRSP daily stock file: CEF prices, the cross-check
    ("crsp_a_stock", "stocknames"),   # ticker history with date ranges (permno map)
    ("crsp_a_stock", "dsenames"),     # the same, daily-events flavour
    ("crsp_q_mutualfunds", "daily_nav"),
    ("ff_all", "factors_daily"),
    ("frb_all", "rates_daily"),
)

_DATE_TYPES = ("DATE", "TIMESTAMP")


@dataclass
class TableReport:
    schema: str
    table: str
    path: str                                       # redacted form, for the report
    present: bool
    columns: list[tuple[str, str]] = field(default_factory=list)
    rows: int | None = None
    date_ranges: dict[str, tuple[str, str]] = field(default_factory=dict)
    error: str | None = None


def _redact(path: str, base: str) -> str:
    """`s3://<real-bucket>/x` -> `s3://<bucket>/x`, so the report names no config value."""
    return path.replace(base, "s3://<bucket>", 1) if base.startswith("s3://") else path


def list_objects(con, base: str, prefix: str) -> list[str]:
    """Every object key under `<base>/<prefix>/`, recursively, sorted, redacted."""
    rows = con.execute("SELECT file FROM glob(?) ORDER BY file",
                       [f"{base}/{prefix}/**"]).fetchall()
    return [_redact(r[0], base) for r in rows]


def list_option_underlyings(con, base: str) -> dict[str, tuple[int, str, str]]:
    """Every underlying under `options/<SYM>/tick/`: (n month files, first, last month).

    Enumerated rather than assumed, because `OPTION_SYMBOLS` is only the list
    someone remembered on 2026-09-28; whether the bucket also carries e.g. HYG
    or LQD is a question `docs/SYSTEM.md` leaves open.
    """
    rows = con.execute("SELECT file FROM glob(?)", [f"{base}/options/*/tick/*.parquet"]).fetchall()
    by: dict[str, list[str]] = {}
    for (f,) in rows:
        parts = f[len(base):].strip("/").split("/")   # options, SYM, tick, YYYY-MM.parquet
        by.setdefault(parts[1], []).append(parts[3].removesuffix(".parquet"))
    return {k: (len(v), min(v), max(v)) for k, v in sorted(by.items())}


def describe_table(con, base: str, schema: str, table: str) -> TableReport:
    """Columns, row count and date-column ranges of one parquet table."""
    path = f"{base}/wrds/{schema}/{table}.parquet"
    rep = TableReport(schema, table, _redact(path, base), present=False)
    if not con.execute("SELECT count(*) FROM glob(?)", [path]).fetchone()[0]:
        return rep
    rep.present = True
    try:
        rep.columns = [(r[0], r[1]) for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()]
        rep.rows = int(con.execute("SELECT count(*) FROM read_parquet(?)", [path]).fetchone()[0])
        for name, typ in rep.columns:
            if typ.upper().startswith(_DATE_TYPES):
                ident = '"' + name.replace('"', '""') + '"'
                lo, hi = con.execute(
                    f"SELECT min({ident}), max({ident}) FROM read_parquet(?)", [path]).fetchone()
                rep.date_ranges[name] = (str(lo), str(hi))
    except Exception as exc:  # recorded verbatim in the report and fails the exit code
        rep.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    return rep


def render(run_utc: str, listings: dict[str, list[str]], tables: list[TableReport],
           underlyings: dict[str, tuple[int, str, str]] | None = None) -> str:
    out = [
        "# R2 catalog (WRDS mirror)",
        "",
        f"**Run:** {run_utc} UTC by `scripts/data/r2_catalog.py`. Read-only. "
        "True as of that timestamp only -- re-run before quoting a date or a column.",
        "Bucket name redacted to `<bucket>`.",
        "",
        "## Curated tables",
        "",
    ]
    for t in tables:
        out.append(f"### `{t.schema}.{t.table}`")
        out.append("")
        out.append(f"path: `{t.path}`")
        out.append("")
        if not t.present:
            out.append("**ABSENT** -- no object at this path.")
            out.append("")
            continue
        if t.error:
            out.append(f"**ERROR** -- {t.error}")
            out.append("")
        out.append(f"rows: {t.rows if t.rows is not None else 'NOT MEASURED'}")
        out.append("")
        if t.columns:
            if t.date_ranges:
                for c, (lo, hi) in t.date_ranges.items():
                    out.append(f"date range `{c}`: {lo} .. {hi}")
            else:
                out.append("date range: no DATE/TIMESTAMP-typed column (not parsed; see types)")
            out.append("")
            out.append("| column | type |")
            out.append("|---|---|")
            out.extend(f"| `{c}` | {ty} |" for c, ty in t.columns)
            out.append("")
    if underlyings is not None:
        out.append("## Option underlyings present (`options/<SYM>/tick/`)")
        out.append("")
        if not underlyings:
            out.append("(none)")
        else:
            out.append("| underlying | month files | first | last |")
            out.append("|---|---|---|---|")
            out.extend(f"| {k} | {n} | {lo} | {hi} |" for k, (n, lo, hi) in underlyings.items())
        out.append("")
    out.append("## Object listings")
    out.append("")
    for prefix, keys in listings.items():
        out.append(f"### `{prefix}/` ({len(keys)} objects)")
        out.append("")
        if not keys:
            out.append("(none)")
        else:
            out.extend(f"- `{k}`" for k in keys)
        out.append("")
    return "\n".join(out)


def run(con, base: str, run_utc: str) -> tuple[str, bool]:
    """Build the report. Returns (markdown, ok) -- ok False if any curated table
    is absent or errored."""
    listings: dict[str, list[str]] = {}
    for s in LIST_SCHEMAS:
        listings[f"wrds/{s}"] = list_objects(con, base, f"wrds/{s}")
    for sym in OPTION_SYMBOLS:
        listings[f"options/{sym}/tick"] = list_objects(con, base, f"options/{sym}/tick")
    tables = [describe_table(con, base, s, t) for s, t in CURATED]
    ok = all(t.present and not t.error for t in tables)
    return render(run_utc, listings, tables, list_option_underlyings(con, base)), ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)
    from src.data import r2
    cfg = r2.load_config()
    con = r2.connect(cfg)
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    md, ok = run(con, f"s3://{cfg.bucket}", run_utc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md + "\n")
    print(f"wrote {args.out.relative_to(REPO) if args.out.is_relative_to(REPO) else args.out}"
          f" ({'all curated tables present' if ok else 'SOME CURATED TABLES ABSENT OR ERRORED'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
