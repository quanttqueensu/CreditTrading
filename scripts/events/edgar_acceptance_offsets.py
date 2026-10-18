"""Is `data.sec.gov/submissions` `acceptanceDateTime` really UTC? Checked against the
filing's own SEC header.

    export QUANTT_ENV_FILE=/abs/path/config/.env   # SEC_USER_AGENT; never printed
    python3 scripts/events/edgar_acceptance_offsets.py            # fetch (cached), then count
    python3 scripts/events/edgar_acceptance_offsets.py --offline  # from the cache only

ZERO TRIALS. A DATA-QUALITY CHECK ON A TIMESTAMP, NOT A RETURN.

WHY IT EXISTS
-------------
The event layer keys every EDGAR event on `observed_at`, and `docs/REFERENCES.md`
§12j (2026-10-12) recorded that the submissions JSON's `acceptanceDateTime` is UTC
("…Z"), so it must be converted, never read as an Eastern time. That was measured
on HYT: 898 of 907 filings fit UTC plus the cut-offs.

On 2026-10-15 a terms-and-sources pass for
`results/events/PREDICTION_MARKETS_ALT_DATA_2026-10-15.md` found two filings where
the JSON value sat 8 hours after the filing index page's "Accepted" time, not 4.
In a first check of 12 filings (HYT, PDI, NAD, BMEZ), the index page and the
`<ACCEPTANCE-DATETIME>` line of the filing's own SEC header agreed with each other
every time, in Eastern time. The JSON agreed with them, read as UTC, for 5 of the
12, and was **4 hours later** for 7. So "convert it from UTC" is right for some
filings and 4 hours late for others.

A late `observed_at` is the conservative direction: it never lets an event in
before it could have been known. But it can push an evening filing past the
evening decision and cost the book a day. This script measures how often it
happens, on the 13 deployed names' most recent filings.

METHOD
------
For each name in the frozen spec's universe, take the latest `N_PER_NAME`
filings from the submissions JSON. Read each filing's full-text submission
(`{accession}.txt`, header only) and parse `<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS`,
which EDGAR writes in Eastern time. Convert it to UTC with America/New_York's
rules (EDT or EST on that date). Then offset = JSON value − header value, in
hours. A JSON that is true UTC gives 0.

READ-ONLY. Everything goes through `scripts/data/edgar_client.py`, which applies
the SEC's 10-requests-a-second ceiling, the declared user agent and a disk cache.
The output holds accession numbers, form types and times only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
N_PER_NAME = 20
OUT = REPO / "results/events/edgar_acceptance_offsets"
HEADER_RX = re.compile(r"<ACCEPTANCE-DATETIME>(\d{14})")


def header_utc(stamp: str) -> dt.datetime:
    """EDGAR's header stamp (Eastern wall-clock time) as an aware UTC datetime."""
    if not re.fullmatch(r"\d{14}", stamp or ""):
        raise ValueError(f"not a 14-digit EDGAR stamp: {stamp!r}")
    naive = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S")
    return naive.replace(tzinfo=NY).astimezone(UTC)


def json_utc(value: str) -> dt.datetime:
    """The submissions JSON's value, taken at its word ("…Z" = UTC)."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"acceptanceDateTime {value!r} is not a Z-suffixed timestamp")
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def offset_hours(json_value: str, header_stamp: str) -> float:
    return round((json_utc(json_value) - header_utc(header_stamp)).total_seconds() / 3600, 4)


def run(offline: bool) -> dict:
    from scripts.data.edgar_client import EdgarClient
    from scripts.cef.spec import UNIVERSE
    c = EdgarClient(offline=offline)
    tick = c.get_json("https://www.sec.gov/files/company_tickers.json", max_age_s=None)
    ciks = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}
    rows = []
    for t in sorted(UNIVERSE):
        if t not in ciks:
            raise KeyError(f"{t} is not in the SEC ticker file")
        cik = ciks[t]
        sub = c.get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", max_age_s=None)
        r = sub["filings"]["recent"]
        for i in range(min(N_PER_NAME, len(r["accessionNumber"]))):
            acc = r["accessionNumber"][i]
            txt = c.get_text(f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                             f"{acc.replace('-', '')}/{acc}.txt", max_age_s=None)
            m = HEADER_RX.search(txt[:5000])
            if not m:
                raise ValueError(f"{t} {acc}: no <ACCEPTANCE-DATETIME> in the SEC header")
            off = offset_hours(r["acceptanceDateTime"][i], m.group(1))
            rows.append({"ticker": t, "cik": cik, "accession": acc, "form": r["form"][i],
                         "filer_prefix": acc[:10], "json": r["acceptanceDateTime"][i],
                         "header_et": m.group(1), "offset_h": off})
    import pandas as pd
    df = pd.DataFrame(rows)
    # Which side is wrong? EDGAR accepts filings 06:00-22:00 ET on business days
    # (sec.gov "Accessing EDGAR Data", REFERENCES §12j). A JSON value that, read
    # as UTC, lands outside those hours cannot be the true acceptance time.
    def _json_et_hour(v):
        t = json_utc(v).astimezone(NY)
        return t.hour + t.minute / 60
    df["json_et_hour"] = df["json"].map(_json_et_hour)
    df["json_outside_edgar_hours"] = (df["json_et_hour"] < 6) | (df["json_et_hour"] >= 22)
    df["late"] = df["offset_h"] > 0
    # The offset expected if the ET->UTC shift were applied twice: the date's own UTC offset.
    df["date_utc_offset_h"] = [
        -NY.utcoffset(dt.datetime.strptime(s, "%Y%m%d%H%M%S")).total_seconds() / 3600
        for s in df["header_et"]]
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "offsets.csv", index=False)
    late = df[df["late"]]
    summ = {
        "n_filings": int(len(df)), "names": sorted(df["ticker"].unique().tolist()),
        "late_by_ticker": {t: int(g["late"].sum()) for t, g in df.groupby("ticker")},
        "late_equal_to_date_utc_offset": int((late["offset_h"] == late["date_utc_offset_h"]).sum()),
        "n_late": int(len(late)),
        "json_outside_edgar_hours": {"late": int(late["json_outside_edgar_hours"].sum()),
                                     "not_late": int(df.loc[~df["late"], "json_outside_edgar_hours"].sum())},
        "offset_counts_h": {str(k): int(v) for k, v in df["offset_h"].value_counts().sort_index().items()},
        "by_form": {f: {str(k): int(v) for k, v in g["offset_h"].value_counts().sort_index().items()}
                    for f, g in df.groupby("form")},
        "by_filer_prefix": {f: {str(k): int(v) for k, v in g["offset_h"].value_counts().sort_index().items()}
                            for f, g in df.groupby("filer_prefix")},
        "header_et_range": [df["header_et"].min(), df["header_et"].max()],
    }
    (OUT / "summary.json").write_text(json.dumps(summ, indent=2))
    return summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.offline), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
