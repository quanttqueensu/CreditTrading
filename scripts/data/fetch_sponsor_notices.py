"""Fetch and verify the fund sponsors' own distribution notices cited for trial C4's holdout.

    export QUANTT_ENV_FILE=<absolute path to the env file>   # SEC_USER_AGENT for EDGAR; never printed
    python3 scripts/data/fetch_sponsor_notices.py

WHY THIS EXISTS (2026-10-15, trial C4)
--------------------------------------
After the 2026-10-14 distribution ruling, 22 of the 71 ex-dates on which the
yfinance leg disagrees with Alpaca had no confirming third source. The team
lead ruled on 2026-10-15 (PREREG amendment 3) that the fund sponsor's own
published notices -- press releases and Section 19(a) notices, from EDGAR or
the sponsor's site, fetched and cited with URLs -- are also allowed as the
third source, and that a fund with any ex-date still unconfirmed is excluded
from the holdout entirely.

WHAT IT DOES. `results/cef/c4/c4_sponsor_notices_2026-10-15.csv` is the citation
table: per row, the fund and ex-date it bears on, the document's URL, a
VERBATIM quote from it, and the verdict (does the notice confirm or contradict
Alpaca's amount and date). This script re-fetches every URL and checks that
each quote occurs in the document's text, after normalising whitespace and
typographic quotes. A quote that is not found RAISES: a citation that cannot
be reproduced is an anecdote (`.claude/rules/documents.md`).

SOURCES. EDGAR documents go through `scripts/data/edgar_client.py` (its declared
User-Agent, rate limit and cache). Sponsor sites (franklintempleton.com,
adamsfunds.com) are fetched with a plain read-only GET; a PDF is read with
pypdf. Business Wire refuses scripted requests (HTTP 403, 2026-10-15), so no
citation here depends on it. Raw documents are cached under the gitignored
`results/cef/c4/_cache_c4/sponsor_notices/` with the fetch time and SHA-256.

AMENDMENT 4 (team lead, 2026-10-16; this file changed 2026-10-18). The ruling
no longer asks whether a notice confirms ALPACA: each disputed ex-date resolves
to whichever amount, yfinance's or Alpaca's, a third source confirms, and a
sponsor notice decides when the third sources conflict. So the citation table
(now `c4_sponsor_notices_2026-10-18.csv`; the 2026-10-15 table is kept as the
record of amendment 3) carries what each notice STATES, `stated_amount`, in
place of a hand-written verdict, and `c4_families.resolve_distributions`
compares it with both vendors' amounts. `stated_amount` is the per-share
amount the quote gives for that fund and ex-date; 0 where the notice puts the
distribution on another date; blank where the quote gives the date but no
amount. A stated amount above zero must itself occur in the quote (trailing
zeros allowed), so a number cannot enter the table that its own citation does
not show.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CITATIONS = REPO / "results" / "cef" / "c4" / "c4_sponsor_notices_2026-10-18.csv"
CACHE = REPO / "results" / "cef" / "c4" / "_cache_c4" / "sponsor_notices"
VERIFIED = REPO / "results" / "cef" / "c4" / "_cache_c4" / "sponsor_notices_verified_2026-10-18.parquet"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class NoticeError(RuntimeError):
    pass


def normalise(text: str) -> str:
    """Whitespace collapsed, HTML entities and tags removed, typographic quotes made plain. Pure."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", text))
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def quote_found(quote: str, text: str) -> bool:
    return normalise(quote) in normalise(text)


def amount_in_quote(amount: float, quote: str) -> bool:
    """A stated amount above zero occurs in its own quote as a decimal (0.113 matches '$0.1130',
    not '0.1135'); zero and blank state no number and pass. Pure."""
    if pd.isna(amount) or amount == 0:
        return True
    s = f"{amount:.6f}".rstrip("0")
    return re.search(r"(?<![\d.])" + re.escape(s) + r"0*(?![\d])", normalise(quote)) is not None


def fetch(url: str, edgar) -> tuple[bytes, str]:
    """(raw bytes, text). EDGAR through its client; anything else by a plain GET."""
    if url.startswith("https://www.sec.gov/"):
        raw = edgar.get(url)
    else:
        import requests
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code != 200:
            raise NoticeError(f"HTTP {r.status_code} from {url}")
        raw = r.content
    if raw[:5] == b"%PDF-":
        import pypdf
        text = " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    else:
        text = raw.decode("utf-8", errors="replace")
    return raw, text


def main(argv=None) -> int:
    from scripts.data.edgar_client import EdgarClient
    cit = pd.read_csv(CITATIONS)
    if "stated_amount" not in cit.columns or (cit["stated_amount"].dropna() < 0).any():
        raise NoticeError(f"{CITATIONS.name}: every row needs a stated_amount (>= 0, or blank)")
    noamt = cit[[not amount_in_quote(a, q) for a, q in zip(cit["stated_amount"], cit["quote"])]]
    if len(noamt):
        raise NoticeError(f"stated amounts that do not occur in their own quotes: "
                          f"{noamt[['ticker', 'ex_date', 'stated_amount']].to_dict('records')}")
    edgar = EdgarClient()
    CACHE.mkdir(parents=True, exist_ok=True)
    t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs, out = {}, []
    for url in cit["url"].unique():
        raw, text = fetch(url, edgar)
        h = hashlib.sha256(raw).hexdigest()
        (CACHE / f"{h[:16]}.bin").write_bytes(raw)
        docs[url] = (text, h)
    for r in cit.itertuples(index=False):
        text, h = docs[r.url]
        ok = quote_found(r.quote, text)
        out.append(dict(r._asdict(), quote_found=ok, sha256=h, fetched_utc=t))
        print(f"{r.ticker} {r.ex_date} states {r.stated_amount!s:<8} quote {'FOUND' if ok else 'NOT FOUND'}  {r.url}")
    o = pd.DataFrame(out)
    missing = o[~o["quote_found"]]
    if len(missing):
        raise NoticeError(f"{len(missing)} cited quotes do not occur in their documents: "
                          f"{missing[['ticker', 'ex_date', 'url']].to_dict('records')}")
    o.to_parquet(VERIFIED, index=False)
    (CACHE / "manifest.json").write_text(json.dumps({u: {"sha256": h, "fetched_utc": t} for u, (_, h) in docs.items()}, indent=1))
    print(f"verified {len(o)} citations from {len(docs)} documents at {t} -> {VERIFIED.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
