"""The event store: extraction schema, point-in-time query and validation hooks (skeleton; no network, no LLM).

Special-situations sprint, job 1 (team lead, 2026-10-15). ZERO TRIALS. The design
is `results/events/EVENT_ENGINE_DESIGN_2026-10-15.md`; the architecture it
implements is `results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §3 (the event log,
the record, the state machine, `events_at(t)`) and §6.1a (LLMs reading
filings). This module is the part of that design that must be right before any
model is wired in, because it is what stops a model's output reaching the
runner unchecked:

* **the schema** (`KINDS`, `FIELDS`): what an extraction may contain, per event
  type, with a type per field. The prototype's 50-filing extraction was made
  against exactly these specs (`agent_instructions()` renders them);
* **the time key** (`acceptance_from_edgar`, `observed_at`): the UTC instant
  a filing became public. Acceptance comes from the submission header,
  cross-checked against the submissions API (wrong by exactly one UTC offset
  on 23 of the 50 filings); publication is the later of acceptance and 06:00 ET on
  EDGAR's filing date, because EDGAR holds most evening filings until the next
  business day (the design note, §4);
* **the store** (`EventStore`): append-only JSONL, one row per extracted event
  per filing, hash-chained, deduplicated on `row_id`; corrections are new rows
  that supersede old ones as of their own `recorded_at`, so a human review
  dated tomorrow cannot change what was known today;
* **the point-in-time query** (`EventStore.events_at`): rows observable by a
  decision time, with the supersessions known by then, and a runtime assertion
  that nothing later leaks through;
* **validation hooks** (`verify_spans`, `value_in_span`, `consistency_checks`,
  `review_reasons`): every extracted number carries the exact quote it came
  from, and a deterministic check runs wherever arithmetic or structured data
  allows one;
* **the consumer contract** (`subtract_only`): event state may remove or shrink
  an order in a decided plan, never add or grow one (pod note §2.3).

WHAT IS NOT HERE, ON PURPOSE
----------------------------
No EDGAR fetch (that is `scripts/data/edgar_client.py`), no model call (the
team lead has not approved API spend, 2026-10-15), no state machine beyond the
fold the consumers need, and nothing on the live path: `quantt/` imports none
of this until the design note's open decisions are taken.

NO SILENT FALLBACKS. A missing time key raises. A span that is not in the text
is a validation failure, never dropped. An unparsed filing is a row with
`status = "UNPARSED"` that consumers treat as the most restrictive reading of
its form type, never as "no event".

Imports at module level are stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
SCHEMA_VERSION = "event-schema/0.1 (2026-10-15)"

# ===================================================================== schema

# Event kinds. The first eight are the team lead's list (2026-10-15); `none`
# is the triage answer for a filing that carries no event of these kinds (a
# shelf supplement, an open-end reorganisation the desk cannot trade).
KINDS = ("cef_tender", "merger", "liquidation", "rights_offering", "conditional_tender_programme",
         "activist_13d", "spac", "equity_mna", "none")

DOC_ROLES = ("announcement", "offer_document", "amendment", "final_result", "registration_or_proxy",
             "prospectus", "ownership_report", "other")
FUND_TYPES = ("closed_end_fund", "bdc", "interval_or_tender_offer_fund", "open_end_fund", "etf",
              "spac", "operating_company", "reit", "unknown")

# Condition categories for tenders and mergers. Conditions are free legal prose;
# scoring them as text is meaningless, so the schema asks for the SET of
# categories present, each with its own span.
CONDITION_CATS = ("shareholder_approval", "regulatory_approval", "registration_effective", "tax_opinion",
                  "listing", "financing", "minimum_tender", "market_disruption", "legal_injunction",
                  "ric_or_tax_status", "board_discretion", "nav_or_price_decline", "other")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    dtype: str          # number | percent | date | bool | enum | text | set
    doc: str
    enum: tuple = ()
    scored: bool = True  # scored in the prototype's precision/recall
    counted: bool = False  # a count of things the span names, not a printed number: no value-in-span check


def _f(name, dtype, doc, enum=(), scored=True, counted=False):
    return FieldSpec(name, dtype, doc, tuple(enum), scored, counted)


COMMON = (
    _f("subject_names", "text", "the fund(s) or company the event is about, as named; '; '-separated", scored=False),
    _f("subject_tickers", "text", "exchange tickers as printed in the filing; '; '-separated", scored=False),
    _f("security_class", "enum", "the class the event acts on", ("common", "preferred", "notes", "units", "other")),
)

FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "cef_tender": COMMON + (
        _f("price_basis", "enum", "how the offer price is set",
           ("pct_of_nav", "fixed_price", "dutch_auction", "pct_of_market", "other")),
        _f("price_pct_nav", "percent", "offer price as a percent of NAV per share (98 for 98%)"),
        _f("nav_pricing_date", "text", "when the NAV used for the price is struck (e.g. 'close on expiration date')",
           scored=False),
        _f("size_pct_outstanding", "percent", "maximum shares sought as a percent of outstanding"),
        _f("size_shares", "number", "maximum shares sought, as a share count"),
        _f("commencement_date", "date", "the date the offer opens"),
        _f("expiration_date", "date", "the scheduled expiration date (the latest one stated in this filing)"),
        _f("proration", "bool", "the filing states purchases are pro rata if over-subscribed"),
        _f("conditions", "set", "categories of conditions the offer is subject to", CONDITION_CATS),
        _f("trigger_origin", "enum", "why the tender exists",
           ("conditional_programme", "activist_settlement", "board_discretionary", "periodic_liquidity",
            "merger_related", "other")),
        _f("shares_tendered", "number", "result: shares properly tendered"),
        _f("shares_accepted", "number", "result: shares accepted for purchase"),
        _f("proration_factor_pct", "percent", "result: the pro-ration factor, percent of tendered shares bought"),
        _f("final_price_per_share", "number", "result: the purchase price per share in dollars"),
    ),
    "merger": COMMON + (
        _f("acquirer", "text", "the surviving or acquiring entity", scored=False),
        _f("targets", "text", "the target(s), '; '-separated", scored=False),
        _f("n_targets", "number", "how many targets the filing's transaction has", counted=True),
        _f("exchange_basis", "enum", "how target holders are paid",
           ("nav_for_nav", "fixed_ratio", "cash", "cash_and_stock", "other")),
        _f("exchange_ratio", "number", "a fixed exchange ratio, acquirer shares per target share"),
        _f("cash_per_share", "number", "cash per target share, dollars"),
        _f("collar", "bool", "the consideration has a collar or price-protection band"),
        _f("conditions", "set", "categories of closing conditions", CONDITION_CATS),
        _f("expected_close", "text", "the expected closing time as stated (date, quarter or half-year)"),
        _f("termination_date", "date", "the outside date after which either party may terminate"),
        _f("meeting_date", "date", "the shareholder meeting date"),
        _f("record_date", "date", "the record date for the vote"),
    ),
    "rights_offering": COMMON + (
        _f("rights_per_share", "number", "rights issued per share held on the record date"),
        _f("rights_per_new_share", "number", "rights needed to buy one new share"),
        _f("price_reference", "enum", "what the subscription price is a percent of",
           ("nav", "market", "lesser_of_nav_and_market", "greater_of_nav_and_market", "fixed", "other")),
        _f("price_pct", "percent", "the percent applied to the reference (95 for 95%)"),
        _f("price_floor_pct_nav", "percent", "a floor on the price as a percent of NAV, if any"),
        _f("record_date", "date", "the record date"),
        _f("expiration_date", "date", "the subscription expiration date"),
        _f("transferable", "bool", "rights are transferable (listed)"),
        _f("over_subscription", "bool", "an over-subscription privilege exists"),
        _f("max_new_shares", "number", "maximum shares offered (excluding any secondary over-allotment)"),
    ),
    "liquidation": COMMON + (
        _f("action", "enum", "what is proposed", ("liquidate", "open_end", "merge_into_open_end", "term_extend", "other")),
        _f("vote_required", "bool", "a shareholder vote is required"),
        _f("meeting_date", "date", "the meeting date"),
        _f("expected_effective", "text", "expected completion as stated"),
    ),
    "conditional_tender_programme": COMMON + (
        _f("threshold_pct", "percent", "the average-discount trigger (10 for 10%)"),
        _f("metric", "enum", "how the discount is averaged", ("daily_close", "vwap", "weekly_close", "other")),
        _f("window_start", "date", "measurement window start"),
        _f("window_end", "date", "measurement window end"),
        _f("tender_size_pct", "percent", "the tender's size if triggered"),
        _f("tender_price_pct_nav", "percent", "the tender's price if triggered"),
        _f("origin", "enum", "who set it up", ("board", "activist_settlement", "merger_condition", "prospectus", "other")),
    ),
    "activist_13d": COMMON + (
        _f("filer", "text", "the reporting person or group", scored=False),
        _f("pct_owned", "percent", "percent of class owned"),
        _f("shares_owned", "number", "shares beneficially owned"),
        _f("event_date", "date", "date of the event requiring the filing"),
        _f("purpose", "set", "Item 4 intentions",
           ("board_seats", "tender_or_buyback", "liquidation", "open_ending", "merger", "proxy_contest", "other")),
    ),
    "spac": COMMON + (
        _f("trust_per_share", "number", "trust value per public share, dollars"),
        _f("redemption_deadline", "date", "the date by which a combination must close"),
        _f("extension_vote", "bool", "the filing seeks or reports an extension vote"),
        _f("new_deadline", "date", "the extended deadline"),
        _f("extension_contribution_per_share", "number", "sponsor contribution per public share per extension"),
        _f("target", "text", "the business-combination target, if any", scored=False),
    ),
    "equity_mna": COMMON + (
        _f("acquirer", "text", "the acquirer", scored=False),
        _f("target", "text", "the target", scored=False),
        _f("cash_per_share", "number", "cash per target share"),
        _f("exchange_ratio", "number", "acquirer shares per target share"),
        _f("collar", "bool", "a collar exists"),
        _f("conditions", "set", "closing condition categories", CONDITION_CATS),
        _f("expected_close", "text", "expected close as stated"),
        _f("termination_date", "date", "outside date"),
        _f("termination_fee", "number", "target termination fee, dollars"),
    ),
    "none": (),
}
TRIAGE = (
    _f("kind", "enum", "the event kind this filing carries ('none' if none)", KINDS),
    _f("fund_type", "enum", "what the filer is", FUND_TYPES),
    _f("doc_role", "enum", "what this document is in the event's life", DOC_ROLES),
)


def field_spec(kind: str, name: str) -> FieldSpec:
    for s in FIELDS[kind] + TRIAGE:
        if s.name == name:
            return s
    raise KeyError(f"{kind}.{name} is not in the schema ({SCHEMA_VERSION})")


# ===================================================================== time keys

def parse_header_acceptance(raw14: str) -> datetime:
    """The submission header's ACCEPTANCE-DATETIME (YYYYMMDDHHMMSS, Eastern wall clock) as an aware UTC datetime.

    Eastern, not UTC: the filing index page prints the same digits as
    "Accepted" (checked on 4 filings, 2026-10-15, design note §4), and the
    filing date follows from them under 17 CFR 232.13.
    """
    if not re.fullmatch(r"\d{14}", raw14 or ""):
        raise ValueError(f"not a 14-digit acceptance time: {raw14!r}")
    return datetime.strptime(raw14, "%Y%m%d%H%M%S").replace(tzinfo=ET).astimezone(UTC)


class TimeKeyError(ValueError):
    pass


def acceptance_from_edgar(header_raw14: str, api_utc: str | None) -> tuple[datetime, str]:
    """(acceptance time in UTC, the check's verdict) for one filing.

    The header is the authority. The submissions API's `acceptanceDateTime`
    is a cross-check: equal -> "agree"; later by exactly the Eastern UTC
    offset of that instant -> "api_offset_error" (the double conversion found
    on 23 of the prototype's 50 filings; the header is used and the row says so); anything else
    RAISES, because then neither source can be trusted without a reading of
    the index page.
    """
    hdr = parse_header_acceptance(header_raw14)
    if api_utc is None:
        return hdr, "api_missing"
    api = datetime.fromisoformat(api_utc.replace("Z", "+00:00")).astimezone(UTC)
    if api == hdr:
        return hdr, "agree"
    offset = -hdr.astimezone(ET).utcoffset()          # +4h (EDT) or +5h (EST)
    if api - hdr == offset:
        return hdr, "api_offset_error"
    raise TimeKeyError(f"header {hdr.isoformat()} and API {api.isoformat()} differ by {api - hdr}, "
                       "not by the Eastern offset; read the filing index page")


# EDGAR "accepts ... filings ... Monday through Friday, from 6:00 a.m. to 10:00
# p.m., ET", and "Some filing submissions that begin after 5:30 p.m. ET--or
# 10:00 p.m. for Ownership forms 3, 4, 5--will be disseminated the next
# business day, showing up in the following business day's index" (sec.gov,
# Accessing EDGAR Data, fetched 2026-10-15). The latest-filings feed read at
# 21:07 ET that evening showed Schedule 13D/A filings accepted up to 19:56 ET
# but nothing else accepted after 17:31 ET (design note §4). So ACCEPTANCE is
# not PUBLICATION for an evening filing, and the time key must not be the
# acceptance time alone.
EDGAR_OPEN = time(6, 0)


def observed_at(acceptance: datetime, filing_date: date) -> datetime:
    """When the world could first have read the filing: max(acceptance, 06:00 ET on EDGAR's filing date).

    EDGAR's filing date already encodes the cut-offs and the federal-holiday
    calendar (an evening filing gets the next business day's date), so this
    needs no holiday table: a filing accepted at 18:06 ET on Friday 2021-10-22
    and dated Monday 2021-10-25 (KYN's N-14 8C) is observed at 06:00 ET on the
    25th, not on Friday evening. 06:00 is EDGAR's opening and an assumption
    about when a held filing is disseminated [U]; the live poller's first-seen
    time replaces it wherever one exists (`EventRow.time_check`). Same-day
    filings are unaffected (acceptance is after 06:00 on their filing date).
    """
    if acceptance.tzinfo is None:
        raise ValueError("acceptance must be aware")
    open_utc = datetime.combine(filing_date, EDGAR_OPEN, tzinfo=ET).astimezone(UTC)
    if filing_date < acceptance.astimezone(ET).date():
        raise TimeKeyError(f"filing date {filing_date} precedes acceptance {acceptance.isoformat()}")
    return max(acceptance.astimezone(UTC), open_utc)


EDGAR_CUTOFF = time(17, 30)        # 17 CFR 232.13(a)(2); docs/REFERENCES.md §12j
EDGAR_CUTOFF_LATE = time(22, 0)    # Schedules 13D/13G, Forms 3/4/5, 144, 14N, Rule 462(b)
LATE_FORMS = re.compile(r"^(SC 13D|SC 13G|SCHEDULE 13D|SCHEDULE 13G|3|4|5|144)(/A)?$")


# The rule turns on when transmission COMMENCES; the header records ACCEPTANCE,
# which follows it. Two Clough 424B2s accepted 31 and 45 seconds after 17:30
# kept their day (2021-05-21). Inside this grace either date is consistent.
CUTOFF_GRACE = timedelta(minutes=10)


def filing_date_consistent(acceptance: datetime, filing_date: date, form: str) -> bool:
    """Is EDGAR's filing date what 17 CFR 232.13 gives for this acceptance time?

    Before the cut-off on a weekday: the same day. More than `CUTOFF_GRACE`
    after it, or on a weekend: a later day (the next business day; federal
    holidays are not modelled, so "later" is checked, not "next"). A
    validation hook: the header passed it on 48 of 50 filings without the
    grace and 50 of 50 with it; the submissions API's time on 36 without the
    grace and 38 with it (design note §4).
    """
    local = acceptance.astimezone(ET)
    cutoff = EDGAR_CUTOFF_LATE if LATE_FORMS.match(form.strip().upper()) else EDGAR_CUTOFF
    if local.weekday() >= 5:
        return filing_date > local.date()
    cut = datetime.combine(local.date(), cutoff, tzinfo=ET)
    if local <= cut:
        return filing_date == local.date()
    if local <= cut + CUTOFF_GRACE:
        return filing_date >= local.date()
    return filing_date > local.date()


# The runner decides in the evening of t, 22:00-01:00 ET, with a morning
# backstop on t+1 (docs/RUNNER.md, team lead 2026-09-29). Research uses the
# EARLIEST evening slot as t's decision time: an event a backtest lets in must
# have been observable by then, so the backtest can only know less than the
# live runner did, never more.
RESEARCH_DECISION_ET = time(22, 0)


def research_decision_time(t: date) -> datetime:
    return datetime.combine(t, RESEARCH_DECISION_ET, tzinfo=ET).astimezone(UTC)


# ===================================================================== the record

@dataclass
class FieldValue:
    value: object
    span: str            # the exact quote the value was read from
    doc_seq: str = ""    # which document of the submission

    def __post_init__(self):
        if self.value is not None and not (self.span or "").strip():
            raise ValueError("a non-null extracted value needs its source span")


@dataclass
class EventRow:
    row_id: str                  # "<source>:<source id>:<event index>", e.g. "edgar:0001193125-21-284573:0"
    source: str                  # edgar | alpaca_news | alpaca_ca | review | rule
    kind: str
    observed_at: str             # ISO UTC: when the world could first have known (the no-lookahead key)
    recorded_at: str             # ISO UTC: when THIS row was written (extraction or review time)
    cik: int | None = None
    symbols: list = field(default_factory=list)
    form: str = ""
    filing_date: str = ""
    effective_at: str = ""
    status: str = "EXTRACTED"    # EXTRACTED | UNPARSED | REVIEWED | REJECTED
    terms: dict = field(default_factory=dict)        # field name -> FieldValue as dict
    triage: dict = field(default_factory=dict)
    extraction: dict = field(default_factory=dict)   # method, schema, extractor, model, prompt_sha256
    confidence: float | None = None
    review: str = "pending"      # pending | accepted | corrected | rejected
    supersedes: str | None = None
    backfilled: bool = False     # extracted after the fact (research): never "known in real time"
    raw_ref: str = ""
    time_check: str = ""         # acceptance_from_edgar's verdict, or "first_seen" when the live poller's time is used
    prev_hash: str = ""
    hash: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"kind {self.kind!r} not in schema")
        for k in ("observed_at", "recorded_at"):
            v = getattr(self, k)
            if not v or _utc(v).tzinfo is None:
                raise ValueError(f"{k} must be an ISO UTC time, got {v!r}")
        if _utc(self.recorded_at) < _utc(self.observed_at):
            raise ValueError(f"{self.row_id}: recorded_at {self.recorded_at} is before observed_at "
                             f"{self.observed_at}; nothing can be written before it was observable")
        allowed = {s.name for s in FIELDS[self.kind]}
        extra = set(self.terms) - allowed
        if extra:
            raise ValueError(f"terms not in the {self.kind} schema: {sorted(extra)}")


def _utc(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"naive time {s!r}: the store holds UTC only")
    return d.astimezone(UTC)


def _row_payload(row: EventRow) -> str:
    d = asdict(row)
    d.pop("hash")
    return json.dumps(d, sort_keys=True, default=str)


class StoreIntegrityError(RuntimeError):
    pass


class LookaheadError(AssertionError):
    pass


class EventStore:
    """Append-only, hash-chained JSONL. On prod `<state>/events.jsonl`; research reads the same rows."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rows: list[EventRow] = []
        if self.path.exists():
            for n, line in enumerate(self.path.read_text().splitlines(), 1):
                if line.strip():
                    self.rows.append(EventRow(**json.loads(line)))
            self.verify_chain()
        self._ids = {r.row_id: r for r in self.rows}

    def verify_chain(self) -> None:
        prev = ""
        for i, r in enumerate(self.rows):
            if r.prev_hash != prev:
                raise StoreIntegrityError(f"row {i} ({r.row_id}): prev_hash breaks the chain")
            h = hashlib.sha256((prev + _row_payload(r)).encode()).hexdigest()
            if h != r.hash:
                raise StoreIntegrityError(f"row {i} ({r.row_id}): hash mismatch (edited after writing)")
            prev = r.hash

    def append(self, row: EventRow) -> bool:
        """Append; True if written, False if an identical row is already there (at-least-once delivery).

        The same row_id with a different payload RAISES: a correction is a NEW
        row with `supersedes`, so the old reading stays visible to any query
        dated before the correction.
        """
        old = self._ids.get(row.row_id)
        if old is not None:
            a, b = asdict(old), asdict(row)
            for k in ("prev_hash", "hash", "recorded_at"):
                a.pop(k), b.pop(k)
            if a == b:
                return False
            raise StoreIntegrityError(f"{row.row_id} already stored with different content; append a "
                                      "correction row with supersedes= instead")
        if row.supersedes is not None and row.supersedes not in self._ids:
            raise StoreIntegrityError(f"{row.row_id} supersedes unknown row {row.supersedes}")
        if row.supersedes is not None and _utc(row.recorded_at) < _utc(self._ids[row.supersedes].recorded_at):
            raise StoreIntegrityError(f"{row.row_id}: a correction cannot be recorded before the row it corrects")
        row.prev_hash = self.rows[-1].hash if self.rows else ""
        row.hash = hashlib.sha256((row.prev_hash + _row_payload(row)).encode()).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(asdict(row), sort_keys=True, default=str) + "\n")
        self.rows.append(row)
        self._ids[row.row_id] = row
        return True

    def events_at(self, t: datetime, include_backfilled: bool = True) -> list[EventRow]:
        """The rows a decision at instant `t` (aware) may use.

        A row is visible if the world could have known it (`observed_at` <= t)
        AND we had written it (`recorded_at` <= t) -- except that research
        replaying history with backfilled extractions sets
        `include_backfilled=True` to accept rows recorded later than t whose
        observed_at is <= t; those carry `backfilled=True` and the caller must
        report results with and without them (pod note §3.6). A correction
        applies only from its own recorded_at. ALIGNMENT: every returned row
        has observed_at <= t, asserted below.
        """
        if t.tzinfo is None:
            raise ValueError("events_at needs an aware datetime")
        t = t.astimezone(UTC)

        def visible(r: EventRow) -> bool:
            if _utc(r.observed_at) > t:
                return False
            if _utc(r.recorded_at) <= t:
                return True
            return include_backfilled and r.backfilled and r.source != "review"

        live = [r for r in self.rows if visible(r)]
        superseded = {r.supersedes for r in live if r.supersedes}
        out = [r for r in live if r.row_id not in superseded and r.status != "REJECTED"]
        late = [r.row_id for r in out if _utc(r.observed_at) > t]
        if late:
            raise LookaheadError(f"rows observed after {t.isoformat()}: {late}")
        return out


# ===================================================================== validation hooks

_TRANS = str.maketrans({"’": "'", "‘": "'", "`": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\xa0": " "})
# EDGAR documents in windows-1252 decoded as Latin-1 (the client's default) turn
# curly quotes and dashes into C1 control characters (U+0080-U+009F): a reader
# found them in the GDL prospectus (2026-10-15). Map them back through cp1252.
_C1 = {}
for _i in range(0x80, 0xA0):
    try:
        _C1[_i] = bytes([_i]).decode("cp1252")
    except UnicodeDecodeError:
        _C1[_i] = ""
_C1 = str.maketrans(_C1)
# Invisible characters that break a verbatim match (GAB's zero-width spaces, soft hyphens).
_INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")


def normalise(s: str) -> str:
    """The form in which a span is matched against a filing's text.

    The same rules as the conditional-tender census's quote check
    (`scripts/events/conditional_tender_census.normalise`): curly quotes,
    dashes, whitespace and case carry no meaning; a different NUMBER never
    matches. Table-cell separators (" | ") written by the text renderer are
    dropped too, so a quote copied across a table row still matches; so are
    cp1252 characters that arrived as C1 controls and zero-width characters,
    which a reader cannot reproduce when copying a quote.
    """
    s = _INVISIBLE.sub("", s.translate(_C1))
    s = unicodedata.normalize("NFKC", s).translate(_TRANS).casefold()
    s = s.replace("|", " ")
    s = re.sub(r"(?<=\d)\s+%", "%", s)
    s = re.sub(r"-\s+(?=\d)", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def span_in_text(span: str, text_norm: str) -> bool:
    """`text_norm` is `normalise(text)` (computed once per filing)."""
    if not span or not span.strip():
        raise ValueError("empty span")
    return normalise(span) in text_norm


_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"), 1)}


def _numbers_in(s: str) -> list[float]:
    out = []
    for m in re.finditer(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", s):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def _dates_in(s: str) -> set[date]:
    out = set()
    s2 = normalise(s)
    for m in re.finditer(r"(january|february|march|april|may|june|july|august|september|october|november|december)"
                         r"\.?\s+(\d{1,2}),?\s+(\d{4})", s2):
        try:
            out.add(date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s2):
        try:
            out.add(date(int(m.group(3)), int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", s2):
        try:
            out.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return out


# "At a price equal to the net asset value per share" states 100% of NAV in
# words; pass A's readers wrote 100 from four such sentences (2026-10-15).
_PAR_NAV_RE = re.compile(r"\b(equal to|which was|which is|is|was|at)\s+(the\s+)?(nav|net asset value)\b")

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25, "fifty": 50,
                 "ninety-five": 95, "ninety-eight": 98, "ninety-nine": 99, "one hundred": 100}


def value_in_span(value, dtype: str, span: str) -> bool | None:
    """Can `value` be read off `span` deterministically? None where no check applies (bool, enum, set, text).

    number/percent: the number appears in the span (digits, or a small set of
    number words). date: the date appears in the span in a written form. This
    is the check that catches a model that quotes the right sentence and
    types the wrong figure.
    """
    if value is None:
        return None
    if dtype in ("number", "percent"):
        v = float(value)
        if any(abs(v - x) <= 1e-9 * max(1.0, abs(v)) for x in _numbers_in(span)):
            return True
        low = normalise(span)
        if dtype == "percent" and abs(v - 100.0) < 1e-9 and _PAR_NAV_RE.search(low):
            return True
        return any(w in low and abs(n - v) < 1e-9 for w, n in _WORD_NUMBERS.items())
    if dtype == "date":
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
        return d in _dates_in(span)
    return None


@dataclass
class SpanFailure:
    field: str
    reason: str          # span_not_in_text | value_not_in_span | missing_span
    detail: str = ""


def verify_spans(kind: str, terms: dict, text: str) -> list[SpanFailure]:
    """Every non-null term: its span is in the filing text, and its value can be read off the span."""
    norm = normalise(text)
    out = []
    for name, fv in terms.items():
        if fv is None or fv.get("value") is None:
            continue
        spec = field_spec(kind, name)
        spans = fv.get("spans") if spec.dtype == "set" else [fv.get("span")]
        spans = [s for s in (spans or []) if s]
        if not spans:
            out.append(SpanFailure(name, "missing_span"))
            continue
        for s in spans:
            if not span_in_text(s, norm):
                out.append(SpanFailure(name, "span_not_in_text", s[:120]))
        if (spec.dtype in ("number", "percent", "date") and not spec.counted and spans
                and all(span_in_text(s, norm) for s in spans)):
            ok = value_in_span(fv["value"], spec.dtype, " ".join(spans))
            if ok is False:
                out.append(SpanFailure(name, "value_not_in_span", f"{fv['value']!r} vs {spans[0][:120]!r}"))
    return out


def consistency_checks(kind: str, terms: dict, nav_per_share: float | None = None,
                       tol_dollars: float = 0.011) -> list[str]:
    """Deterministic checks inside one record and against structured data passed in.

    * tender: accepted <= tendered; pro-ration factor = accepted / tendered
      (to a tenth of a percent); final price = price_pct_nav x NAV at
      expiry when the NAV is supplied from a structured source (our NAV
      panel), to a cent plus rounding.
    * rights: rights_per_new_share > 0; price_pct in (0, 100].
    * merger: a fixed ratio needs exchange_basis fixed_ratio or cash_and_stock.
    Returns the failed checks as strings (empty when all pass or none apply).
    """
    v = {k: (fv or {}).get("value") for k, fv in terms.items()}
    bad = []
    if kind == "cef_tender":
        t, a, pf = v.get("shares_tendered"), v.get("shares_accepted"), v.get("proration_factor_pct")
        if t is not None and a is not None and a > t * (1 + 1e-9):
            bad.append("shares_accepted > shares_tendered")
        if t and a is not None and pf is not None and abs(100 * a / t - pf) > 0.1:
            bad.append(f"proration_factor {pf} != accepted/tendered {100 * a / t:.3f}")
        p, pct = v.get("final_price_per_share"), v.get("price_pct_nav")
        if p is not None and pct is not None and nav_per_share is not None:
            if abs(p - pct / 100 * nav_per_share) > tol_dollars:
                bad.append(f"final price {p} != {pct}% x NAV {nav_per_share}")
    elif kind == "rights_offering":
        r = v.get("rights_per_new_share")
        if r is not None and r <= 0:
            bad.append("rights_per_new_share <= 0")
        pp = v.get("price_pct")
        if pp is not None and not (0 < pp <= 100):
            bad.append(f"price_pct {pp} outside (0, 100]")
    elif kind == "merger":
        if v.get("exchange_ratio") is not None and v.get("exchange_basis") not in ("fixed_ratio", "cash_and_stock"):
            bad.append("exchange_ratio set but exchange_basis is not fixed_ratio/cash_and_stock")
    return bad


# Kinds whose announcement on a name the book holds short changes what the
# runner may do (pod note §2.3, §3.4): they go to the front of the queue.
LIVE_PATH_KINDS = ("cef_tender", "merger", "liquidation", "rights_offering", "conditional_tender_programme")


def review_reasons(row: EventRow, span_failures: list[SpanFailure], held: set[str] = frozenset(),
                   min_confidence: float = 0.9, rule_disagrees: bool = False) -> tuple[str, list[str]]:
    """(queue, reasons). Queues: P1 (live path, today), P2 (research gold set), none.

    P1 when the event touches a symbol the book holds or plans to trade and
    its kind can change an order; anything unverified there waits for a human
    before the runner may rely on its TERMS (the subtract-only rule acts on
    the KIND alone and does not wait, `subtract_only`).
    """
    reasons = []
    if row.status == "UNPARSED":
        reasons.append("unparsed")
    if span_failures:
        reasons.append(f"{len(span_failures)} span failure(s)")
    if row.confidence is not None and row.confidence < min_confidence:
        reasons.append(f"confidence {row.confidence:.2f} < {min_confidence}")
    if rule_disagrees:
        reasons.append("rule-based parser disagrees")
    if row.time_check == "api_offset_error":
        reasons.append("API acceptance time off by the UTC offset (header used)")
    on_book = bool(set(row.symbols) & set(held))
    if on_book and row.kind in LIVE_PATH_KINDS:
        return "P1", reasons or ["live-path kind on a held or planned name"]
    return ("P2", reasons) if reasons else ("none", [])


# ===================================================================== the consumer contract

def restrictive_kinds(rows: list[EventRow]) -> dict[str, set[str]]:
    """symbol -> the event kinds (or UNPARSED form kinds) open on it, from rows already filtered by events_at."""
    out: dict[str, set[str]] = {}
    for r in rows:
        if r.kind == "none" and r.status != "UNPARSED":
            continue
        for s in r.symbols:
            out.setdefault(s, set()).add(r.kind if r.status != "UNPARSED" else f"UNPARSED:{r.form}")
    return out


def subtract_only(plan: dict[str, int], held: dict[str, int], open_kinds: dict[str, set[str]],
                  events_fresh: bool) -> tuple[dict[str, int], list[str]]:
    """Apply event state to a decided plan of ORDER quantities (signed shares).

    The rule (pod note §2.3, a proposal for the team lead): an event may
    remove or shrink an order, never add one, grow one or flip its side. Here,
    a name with any open live-path event (or an UNPARSED filing) may not
    increase its SHORT exposure: an order that would take the position
    further below zero is cut to the part that does not. If the event feed is
    stale (`events_fresh` False), no order may increase short exposure on ANY
    name (pod note §3.7). Returns (new plan, log lines).
    """
    new, log = {}, []
    for sym, q in plan.items():
        pos = held.get(sym, 0)
        blocked = (not events_fresh) or any(k in LIVE_PATH_KINDS or k.startswith("UNPARSED")
                                            for k in open_kinds.get(sym, ()))
        if not blocked or q >= 0:
            new[sym] = q
            continue
        # q < 0: the part of the sell that only reduces a long is allowed; the rest would add short exposure.
        allowed = -max(0, pos)                  # at most sell down to flat
        q2 = max(q, allowed)                    # q is negative; keep the smaller sell
        if q2 != q:
            why = "events stale" if not events_fresh else ",".join(sorted(open_kinds[sym]))
            log.append(f"{sym}: order {q} -> {q2} ({why})")
        if q2 != 0:
            new[sym] = q2
    for sym in new:
        if abs(new[sym]) > abs(plan[sym]) or new[sym] * plan[sym] < 0:
            raise AssertionError(f"subtract_only grew or flipped {sym}: {plan[sym]} -> {new[sym]}")
    return new, log


# ===================================================================== the prototype's instructions

def agent_instructions() -> str:
    """The extraction instructions the prototype's readers worked from, rendered from the schema."""
    lines = [f"# Extraction schema {SCHEMA_VERSION}", "",
             "Output one JSON object per filing:", "",
             '{"accession": "...", "triage": {"kind": ..., "fund_type": ..., "doc_role": ...,',
             '  "kind_span": "<quote that shows the kind>"},',
             ' "events": [{"kind": ..., "terms": {"<field>": {"value": ..., "span": "<exact quote>", "doc_seq": "<n>"}, ...}}],',
             ' "notes": "<anything a reviewer must know: ambiguity, a value that needed arithmetic>"}', "",
             "Field types: number (a plain number; no commas), percent (98 for 98%), date (YYYY-MM-DD),",
             "bool, enum (one of the listed values), text, set (a list of listed values, with `spans`: one quote",
             "per element, instead of `span`). A field the filing does not state is null; omit nothing from",
             "the list below, write null. Never infer a value from outside knowledge.", ""]
    for kind, specs in FIELDS.items():
        if not specs:
            continue
        lines.append(f"## {kind}")
        for s in specs:
            e = f" one of: {', '.join(s.enum)}" if s.enum else ""
            lines.append(f"- `{s.name}` ({s.dtype}): {s.doc}.{e}")
        lines.append("")
    lines.append("## triage")
    for s in TRIAGE:
        lines.append(f"- `{s.name}` (enum): {s.doc}. one of: {', '.join(s.enum)}")
    return "\n".join(lines) + "\n"
