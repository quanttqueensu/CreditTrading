"""Hand readings of the 20-deal reading sample (merger_arb_feasibility.py, part 6). Data only.

WHY THIS FILE
-------------
The reading problem is measured by comparing what a regex reader pulls out of
an announcement 8-K (`merger_arb_feasibility.machine_terms`) with what a reader
finds in the SAME document. A reading that cannot be checked is an anecdote,
so every field that states a term carries a verbatim quote from the document,
and `verify` re-finds each quote in the fetched filing on every run (after
`conditional_tender_census.normalise`: case, curly quotes, dashes and spacing
only, so a different number never matches). A quote that is not found raises.

Fields (None = the document does not state it; never a guess):
  consideration    'cash' | 'stock' | 'mixed'
  cash_per_share   str, as printed ("$36.00")
  ratio            str, as printed ("0.4500")
  collar           True / False (a collar, floor, cap or VWAP-dependent ratio)
  election         True / False (holder elects cash or stock, with proration)
  cvr              True / False
  outside_date     str, as printed, with any automatic extension in `outside_ext`
  approvals        list of regulatory approvals the document names as conditions
  vote             'target' | 'acquirer' | 'both' | 'none (tender)' | 'written consent'
  financing_cond   False if the document says there is none; None if silent
  term_fee         str, as printed
  quotes           {field: verbatim text from the document}
  notes            free text: what made this deal hard to read
"""
from __future__ import annotations

# THE SAMPLE. The rule (`merger_arb_feasibility.run`, written before any deal was
# read): among in-scope deals announced on or after 2026-01-01 whose announcement
# document is the target's own 8-K item 1.01, the 10 most recent cash deals and
# the 10 most recent stock-involved deals (a 425 lists the target), by d0, ties
# by CIK. It was applied once, on the run date in SAMPLE_DRAWN, and the 20
# accessions it picked are frozen here BEFORE any of them was read, so a later
# run (more anchors, a refreshed index) reads the same 20.
SAMPLE_DRAWN: str | None = "2026-10-18"   # run date; EDGAR index to 2026-10-16
SAMPLE_ACCESSIONS: tuple[str, ...] = (
    "0001140361-26-037107",
    "0000950103-26-013874",
    "0001104659-26-114571",
    "0001104659-26-103936",
    "0001193125-26-406024",
    "0001193125-26-341431",
    "0001104659-26-106499",
    "0001193125-26-290439",
    "0001609151-26-000100",
    "0001104659-26-085824",
    "0001140361-26-035986",
    "0001193125-26-384457",
    "0001140361-26-031930",
    "0001104659-26-089425",
    "0001493152-26-035196",
    "0001628280-26-049232",
    "0001193125-26-310388",
    "0001104659-26-083891",
    "0001104659-26-078482",
    "0001140361-26-026434",
)

READINGS: dict[str, dict] = {}

FIELDS = ("consideration", "cash_per_share", "ratio", "collar", "election", "cvr", "outside_date",
          "outside_ext", "approvals", "vote", "financing_cond", "term_fee")


def verify(reading: dict, text: str, accession: str) -> None:
    """Raise unless every quote of `reading` occurs in the fetched document `text`."""
    from scripts.events.conditional_tender_census import quote_in
    quotes = reading.get("quotes") or {}
    if not quotes:
        raise ValueError(f"{accession}: a reading with no quotes is an anecdote")
    missing = [k for k, q in quotes.items() if not quote_in(text, q)]
    if missing:
        raise AssertionError(f"{accession}: quote(s) not found in the filing: {missing}")


def flatten(reading: dict | None) -> dict:
    """The reading's fields for the sample table, prefixed `r_`; `read` says whether one exists."""
    if reading is None:
        return {"read": False}
    out = {"read": True}
    for k in FIELDS:
        v = reading.get(k)
        out[f"r_{k}"] = "; ".join(v) if isinstance(v, list) else v
    out["r_notes"] = reading.get("notes")
    return out
