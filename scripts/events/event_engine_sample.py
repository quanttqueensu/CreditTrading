"""The event-engine prototype's sample: 50 EDGAR filings chosen by a rule declared before any was read.

    export QUANTT_ENV_FILE=/abs/path/config/.env      # SEC_USER_AGENT is read from it, never printed
    python3 scripts/events/event_engine_sample.py             # select, fetch (cache first), write text + manifest
    python3 scripts/events/event_engine_sample.py --offline   # the same from the cache only; raises on a miss

ZERO TRIALS. Special-situations sprint, job 1 (team lead, 2026-10-15): design
and prototype an event-extraction engine. Nothing here computes a return, a
P&L or a signal, and no counter moves. The output is a list of filings and
their text, which the prototype extraction (`results/events/event_engine/`)
reads; the design note is `results/events/EVENT_ENGINE_DESIGN_2026-10-15.md`.

THE RULE (declared 2026-10-15, written here before any filing below was read)
---------------------------------------------------------------------------
Frame. The CEF/BDC fund set of `scripts/data/fetch_edgar_events.py` (a CIK that
filed a closed-end-only form, or an N-CSR plus a Form 3/4, since 2008), built
from the SEC full indexes 2008-Q1..2026-Q3, restricted to CIKs that have an
exchange ticker in the SEC ticker file of 2026-10-12 (the file behind the
tracked `edgar_cef_bdc_episodes.csv`). The restriction keeps exchange-listed
funds and drops the non-traded tender-offer funds whose quarterly repurchases
are most of EDGAR's tender filings; its cost is survivorship (a fund that died
since 2021 has no ticker today), which matters less here than in a backtest
because a merger filing is indexed under every party, so a dead target's deal
still enters through its live acquirer.

Three strata, 50 filings:

* T, tender (20). Tender episodes of the tracked episodes table with
  `first_date` in 2021 and a ticker now, ordered by (first_date,
  first_accession), at most ONE episode per first_date (same-day episodes are
  one sponsor's batch on one template: reading three of them measures one
  reading three times). From each episode in that order: its first SC TO-I
  (the offer document; if it has none, its first filing), then its last filing
  if that is an SC TO-I/A (the final amendment: the result and the
  pro-ration). Stop at 20.
* M, merger (20). Merger episodes, the same frame and ordering and the same
  one-per-day rule. From each: its first filing (the announcement), then its
  first registration or proxy filing (N-14 8C, N-14, DEFM14A, PREM14A) if that
  is a different accession. An accession already taken is skipped (the index
  lists a filing under each party). Stop at 20.
* R, rights (10). Filings of forms 424B1..424B8 dated 2021 by frame CIKs,
  ordered by (date_filed, accession). A filing is taken if the first
  `RIGHTS_SCAN_CHARS_V1` characters of its primary document's text match
  `RIGHTS_RE_V1`, at most one per CIK (superseded: amendment 2). Stop at
  10. The rule is a keyword scan, so
  it can admit a shelf prospectus that merely lists rights among the
  securities it may offer; such a filing stays in the sample and its correct
  extraction is "not a rights offering", which is what a triage step must
  also get right.

Ties and gaps are not resolved by hand: a stratum short of its quota raises.

AMENDMENT 1 (2026-10-15, before any filing was read). The first run raised
"merger stratum short: 15 of 20": 2021 had merger episodes on only ten
distinct days among funds listed today. Rather than loosen the one-per-day
rule, every stratum now orders its candidates in two tiers: tier 1 is the
listed-now frame above, tier 2 is the rest of the fund set (funds with no
ticker today: dead targets, non-traded BDCs and funds), each in the stated
order, tier 1 first; the one-per-day rule (T, M) and one-per-CIK rule (R)
apply across both tiers. `tier` is recorded per filing. Nothing else changed.

AMENDMENT 2 (2026-10-15, before any rights filing's text was read). Rule R as
first written admitted ten filings, all 424B2/424B5 supplements of BDCs
(Ares, Stellus, Main Street, ...), seen from the manifest's form and company
columns only. A BDC's universal shelf lists "subscription rights" among the
securities it may offer, so the keyword scan was selecting debt and
at-the-market supplements, and the stratum would have tested triage ten times
and rights terms not at all. R now reads the COVER PAGE only (the first
`RIGHTS_COVER_CHARS` characters of the primary document's text) and needs an
offering phrase there (`RIGHTS_RE`): "rights offering", "rights to
subscribe/purchase/acquire", or "(non-)transferable (subscription) rights".
The bare phrase "subscription rights" no longer qualifies. The ten filings of
the first rule are listed in `sample_meta.json` (`rights_rule_v1_hits`), with
whether each passes the new rule; they were not read and are not in the sample.

TIME KEYS
---------
Each filing's `acceptanceDateTime` comes from the submissions API, in UTC (a
trailing Z; docs/REFERENCES.md §12j). The complete-submission file's header
carries ACCEPTANCE-DATETIME as a bare YYYYMMDDHHMMSS; this script converts it
from America/New_York and records whether the two agree, which is the
deterministic check that the store's time key is read the right way round.

POLITENESS
----------
Every request goes through `scripts/data/edgar_client.py`. Several sprint jobs
use EDGAR on the same day from the same address, and the SEC's 10/s limit is
per requester, not per job, so this script spaces its own requests 0.5 s apart
(`MIN_INTERVAL_S`), a quarter of the client's ceiling.

OUTPUTS
-------
* `results/events/event_engine/sample_manifest.csv` (tracked): one row per
  filing, with the stratum, the rule step that admitted it, the time keys, the
  documents kept and their character counts and hashes.
* `results/events/_cache_event_engine/text/<accession>.txt` (gitignored):
  the extraction input, the kept documents as text in filing order, each
  headed by a `===== DOCUMENT` line. EDGAR is public, but the texts are large
  and rebuilt from the EDGAR cache by `--offline`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events" / "event_engine"
TEXT_DIR = REPO / "results" / "events" / "_cache_event_engine" / "text"
MANIFEST = OUT / "sample_manifest.csv"
EPISODES = REPO / "results" / "events" / "edgar_cef_bdc_episodes.csv"

YEAR = 2021
INDEX_END = date(2026, 9, 30)        # closed quarters only: the frame is rebuilt from the cache
QUOTA = {"T": 20, "M": 20, "R": 10}
MIN_INTERVAL_S = 0.5
# Rule R as first declared (kept to report what it admitted; amendment 2).
RIGHTS_SCAN_CHARS_V1 = 15_000
RIGHTS_RE_V1 = re.compile(r"\brights\s+offering\b|\bsubscription\s+rights\b|\brights\s+to\s+(?:subscribe|purchase)\b",
                          re.IGNORECASE)
RIGHTS_RULE_V1_HITS = (  # the first rule's ten admissions, from the 2026-10-15 run (sample_manifest.csv then)
    "0001047469-21-000020", "0001104659-21-002783", "0001047469-21-000060", "0001213900-21-002128",
    "0001487918-21-000010", "0001213900-21-007203", "0001104659-21-024697", "0001193125-21-047758",
    "0001104659-21-031170", "0001213900-21-013066")
# Rule R in force (amendment 2): an offering phrase on the cover page.
RIGHTS_COVER_CHARS = 5_000
RIGHTS_RE = re.compile(r"\brights\s+offering\b|\brights\s+to\s+(?:subscribe|purchase|acquire)\b"
                       r"|\b(?:non-?\s?transferable|transferable)\s+(?:subscription\s+)?rights\b", re.IGNORECASE)
REGISTRATION_FORMS = ("N-14 8C", "N-14", "DEFM14A", "PREM14A")
RIGHTS_FORMS = tuple(f"424B{i}" for i in range(1, 9))
ET = ZoneInfo("America/New_York")

# Documents inside a submission that are never extraction input: images, XBRL,
# zips, PDFs (their text is uuencoded), and the filing-fee exhibit.
SKIP_DOC_TYPES = re.compile(r"^(GRAPHIC|ZIP|XML|JSON|PDF|EX-101\.|EX-FILING FEES|EX-27|COVER)", re.IGNORECASE)


# ------------------------------------------------------------ the submission file

_DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.DOTALL)
_FIELD_RE = {k: re.compile(rf"<{k}>([^\n<]*)") for k in ("TYPE", "SEQUENCE", "FILENAME", "DESCRIPTION")}
_TEXT_RE = re.compile(r"<TEXT>(.*?)</TEXT>", re.DOTALL)
_ACCEPT_RE = re.compile(r"<ACCEPTANCE-DATETIME>(\d{14})")


class SampleError(RuntimeError):
    pass


def split_submission(raw: str) -> list[dict]:
    """The <DOCUMENT> blocks of a complete-submission .txt: type, sequence, filename, description, body."""
    docs = []
    for block in _DOC_RE.findall(raw):
        rec = {}
        for k, rx in _FIELD_RE.items():
            m = rx.search(block)
            rec[k.lower()] = m.group(1).strip() if m else ""
        t = _TEXT_RE.search(block)
        if not rec["type"] or t is None:
            raise SampleError(f"a DOCUMENT block without TYPE or TEXT (filename {rec.get('filename')!r})")
        rec["body"] = t.group(1)
        docs.append(rec)
    if not docs:
        raise SampleError("no DOCUMENT blocks in the submission")
    return docs


def header_acceptance_utc(raw: str) -> str:
    """ACCEPTANCE-DATETIME of the SEC header (Eastern wall-clock time) as an ISO UTC string."""
    m = _ACCEPT_RE.search(raw[:20000])
    if not m:
        raise SampleError("no ACCEPTANCE-DATETIME in the submission header")
    local = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=ET)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_text(body: str) -> str:
    """One document's HTML (or plain text) as readable text: block structure kept, whitespace tidied.

    Deterministic: the same bytes always give the same text, so a span's
    character offset in it is reproducible. Table cells are separated by
    " | " so a number keeps its row label on one line.

    KNOWN DEFECT, kept so the 50 texts stay byte-identical to what the readers
    read: `EdgarClient.get_text` decodes Latin-1, so a windows-1252 document's
    curly quotes, apostrophes and dashes arrive here as C1 control characters
    (U+0091-U+0097). Readers could not see them, and one pass dropped them from
    six quotes (design note §5). `event_store.normalise` maps them back for
    matching; a production renderer should decode cp1252 before this step.
    """
    if re.search(r"<(html|body|div|p|table|font)\b", body[:5000], re.IGNORECASE):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body, "lxml")
        for bad in soup(["script", "style"]):
            bad.decompose()
        for td in soup.find_all(["td", "th"]):
            td.append(" | ")
        for br in soup.find_all(["br"]):
            br.replace_with("\n")
        text = soup.get_text("\n")
    else:
        text = body
    text = unicodedata.normalize("NFKC", text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln in ("", "|"):
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(ln)
        blank = False
    return "\n".join(out).strip() + "\n"


def kept_documents(docs: list[dict]) -> list[dict]:
    """Every document that is text a reader would use: the primary document and its text exhibits."""
    return [d for d in docs if not SKIP_DOC_TYPES.match(d["type"])]


def render(form: str, accession: str, docs: list[dict]) -> str:
    parts = [f"##### FILING {accession} FORM {form}\n"]
    for d in docs:
        parts.append(f"===== DOCUMENT seq={d['sequence']} type={d['type']} file={d['filename']} "
                     f"desc={d['description']}\n")
        parts.append(d["text"])
    return "\n".join(parts)


# ------------------------------------------------------------ the selection rule

def one_episode_per_day(ep: pd.DataFrame) -> pd.DataFrame:
    """Episodes ordered by (tier, first_date, first_accession), keeping the first of each first_date."""
    ep = ep.sort_values(["tier", "first_date", "first_accession"])
    return ep.drop_duplicates("first_date", keep="first")


def episode_filings(filings: pd.DataFrame, row) -> pd.DataFrame:
    """The filings of one episode: same CIK and kind, dated first_date..last_date, in filing order."""
    f = filings[(filings["cik"] == row.cik) & (filings["kind"] == row.kind)
                & (filings["date_filed"] >= pd.Timestamp(row.first_date))
                & (filings["date_filed"] <= pd.Timestamp(row.last_date))]
    f = f.sort_values(["date_filed", "accession"]).drop_duplicates("accession")
    if f.empty:
        raise SampleError(f"episode CIK {row.cik} {row.kind} {row.first_date}: no filings in the index")
    return f


def select_tender(ep: pd.DataFrame, filings: pd.DataFrame) -> list[dict]:
    out, taken = [], set()
    for row in one_episode_per_day(ep[ep["kind"] == "tender"]).itertuples():
        f = episode_filings(filings, row)
        to_i = f[f["form"] == "SC TO-I"]
        steps = [("offer_document", to_i.iloc[0] if len(to_i) else f.iloc[0])]
        last = f.iloc[-1]
        if last["form"] == "SC TO-I/A":
            steps.append(("final_amendment", last))
        for step, r in steps:
            if r["accession"] in taken:
                continue
            taken.add(r["accession"])
            out.append({"stratum": "T", "step": step, "tier": int(row.tier),
                        "episode_first_date": str(row.first_date.date()), **_row(r)})
            if len(out) == QUOTA["T"]:
                return out
    raise SampleError(f"tender stratum short: {len(out)} of {QUOTA['T']}")


def select_merger(ep: pd.DataFrame, filings: pd.DataFrame) -> list[dict]:
    out, taken = [], set()
    for row in one_episode_per_day(ep[ep["kind"] == "merger"]).itertuples():
        f = episode_filings(filings, row)
        steps = [("announcement", f.iloc[0])]
        reg = f[f["form"].isin(REGISTRATION_FORMS)]
        if len(reg):
            steps.append(("registration", reg.iloc[0]))
        for step, r in steps:
            if r["accession"] in taken:
                continue
            taken.add(r["accession"])
            out.append({"stratum": "M", "step": step, "tier": int(row.tier),
                        "episode_first_date": str(row.first_date.date()), **_row(r)})
            if len(out) == QUOTA["M"]:
                return out
    raise SampleError(f"merger stratum short: {len(out)} of {QUOTA['M']}")


def select_rights(candidates: pd.DataFrame, primary_text) -> list[dict]:
    """`primary_text(cik, accession)` returns the primary document's text (fetched through the client)."""
    out, ciks, scanned = [], set(), 0
    for _, r in candidates.sort_values(["tier", "date_filed", "accession"]).iterrows():
        if r["cik"] in ciks:
            continue
        scanned += 1
        head = primary_text(int(r["cik"]), r["accession"])[:RIGHTS_COVER_CHARS]
        if RIGHTS_RE.search(head):
            ciks.add(r["cik"])
            out.append({"stratum": "R", "step": "rights_scan_hit", "tier": int(r["tier"]),
                        "episode_first_date": "", **_row(r)})
            if len(out) == QUOTA["R"]:
                return out, scanned
    raise SampleError(f"rights stratum short: {len(out)} of {QUOTA['R']} after scanning {scanned}")


def _row(r) -> dict:
    return {"cik": int(r["cik"]), "company": r["company"], "form": r["form"],
            "date_filed": str(pd.Timestamp(r["date_filed"]).date()), "accession": r["accession"]}


# ------------------------------------------------------------ fetching

class Fetcher:
    def __init__(self, offline: bool):
        from scripts.data.edgar_client import EdgarClient, RateLimiter
        self.client = EdgarClient(offline=offline, limiter=RateLimiter(min_interval=MIN_INTERVAL_S))
        self._raw: dict[str, str] = {}

    def raw(self, cik: int, accession: str) -> str:
        from scripts.data.edgar_client import filing_txt_url
        if accession not in self._raw:
            self._raw[accession] = self.client.get_text(filing_txt_url(cik, accession))
        return self._raw[accession]

    def primary_text(self, cik: int, accession: str) -> str:
        docs = split_submission(self.raw(cik, accession))
        return to_text(docs[0]["body"])

    def acceptance_api(self, cik: int) -> dict[str, str]:
        """accession -> acceptanceDateTime (UTC string) from the submissions API, all pages."""
        from scripts.data.fetch_edgar_events import submissions
        s = submissions(self.client, cik, max_age_s=None)
        return dict(zip(s["accessionNumber"], s["acceptanceDateTime"]))


def frame(fetcher: Fetcher) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """The 2021 frame: fund-set filings of the event forms, and the episodes, both for listed-now CIKs."""
    from scripts.data import fetch_edgar_events as F
    idx, _ = F.fetch_indexes(fetcher.client, F.LOOKBACK_START, INDEX_END, today=date(2026, 10, 15))
    rule = F.fund_set(idx)
    tk = fetcher.client.get_json(F.TICKERS_URL, max_age_s=None)  # the 2026-10-12 file (module docstring)
    if tk.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise SampleError(f"ticker file fields changed: {tk.get('fields')}")
    listed = {int(r[0]) for r in tk["data"]}
    funds = set(rule)
    keep = funds & listed
    ev = idx[idx["cik"].isin(funds) & idx["form"].isin(set(F.FORM_KIND) | set(RIGHTS_FORMS))].copy()
    ev["kind"] = ev["form"].map(F.FORM_KIND)
    ev["tier"] = (~ev["cik"].isin(keep)).astype(int) + 1   # 1 = listed now, 2 = the rest (amendment 1)
    ev = ev.drop_duplicates(["cik", "accession", "form"])
    ep = pd.read_csv(EPISODES, parse_dates=["first_date", "last_date"])
    ep = ep[(ep["first_date"].dt.year == YEAR) & ep["cik"].isin(funds)].copy()
    ep["tier"] = (~(ep["ticker_now"].notna() & ep["cik"].isin(keep))).astype(int) + 1
    meta = {"fund_set_ciks": len(rule), "listed_now_ciks": len(keep),
            "index_quarters": f"{F.LOOKBACK_START}..{INDEX_END}",
            "episodes_2021_by_tier": {f"{k}_tier{t}": int(n) for (k, t), n in ep.groupby(["kind", "tier"]).size().items()}}
    return ev, ep, meta


def build(offline: bool) -> dict:
    fetcher = Fetcher(offline)
    ev, ep, meta = frame(fetcher)
    rows = select_tender(ep, ev) + select_merger(ep, ev)
    rights_cands = ev[ev["form"].isin(RIGHTS_FORMS) & (ev["date_filed"].dt.year == YEAR)]
    rights, scanned = select_rights(rights_cands, fetcher.primary_text)
    rows += rights
    meta["rights_candidates_2021"] = int(len(rights_cands))
    meta["rights_scanned"] = scanned
    v1 = rights_cands.drop_duplicates("accession").set_index("accession")
    meta["rights_rule_v1_hits"] = [
        {"accession": a, "company": v1.loc[a, "company"], "form": v1.loc[a, "form"],
         "passes_rule_v2": bool(RIGHTS_RE.search(fetcher.primary_text(int(v1.loc[a, "cik"]), a)[:RIGHTS_COVER_CHARS]))}
        for a in RIGHTS_RULE_V1_HITS]

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in TEXT_DIR.glob("*.txt"):   # a filing dropped by an amendment must not linger as input
        old.unlink()
    api_cache: dict[int, dict] = {}
    for i, r in enumerate(rows):
        raw = fetcher.raw(r["cik"], r["accession"])
        docs = split_submission(raw)
        kept = kept_documents(docs)
        for d in kept:
            d["text"] = to_text(d["body"])
        text = render(r["form"], r["accession"], kept)
        (TEXT_DIR / f"{r['accession']}.txt").write_text(text)
        if r["cik"] not in api_cache:
            api_cache[r["cik"]] = fetcher.acceptance_api(r["cik"])
        api = api_cache[r["cik"]].get(r["accession"])
        if api is None:
            raise SampleError(f"{r['accession']} is not in CIK {r['cik']}'s submissions")
        api_utc = pd.Timestamp(api).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        hdr_utc = header_acceptance_utc(raw)
        r.update({
            "sample_order": i + 1,
            "acceptance_utc": api_utc,
            "acceptance_header_as_et_utc": hdr_utc,
            "acceptance_agree": api_utc == hdr_utc,
            "n_docs_all": len(docs), "n_docs_kept": len(kept),
            "doc_types_kept": ";".join(d["type"] for d in kept),
            "chars_submission_raw": len(raw),
            "chars_primary_text": len(kept[0]["text"]) if kept else 0,
            "chars_kept_text": len(text),
            "sha256_text": hashlib.sha256(text.encode()).hexdigest(),
            "url": f"https://www.sec.gov/Archives/edgar/data/{r['cik']}/{r['accession'].replace('-', '')}/{r['accession']}.txt",
        })
    meta["requests"] = fetcher.client.n_requests
    meta["cache_hits"] = fetcher.client.n_cache_hits
    return {"rows": rows, "meta": meta}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    res = build(a.offline)
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(res["rows"])
    df.to_csv(MANIFEST, index=False)
    (OUT / "sample_meta.json").write_text(json.dumps(res["meta"], indent=1, default=str))
    print(json.dumps(res["meta"], indent=1, default=str))
    print(df.groupby(["stratum", "form"]).size().to_string())
    print("acceptance keys agree:", int(df["acceptance_agree"].sum()), "of", len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
