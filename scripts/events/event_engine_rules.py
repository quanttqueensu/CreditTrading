"""A rules-only extractor for the event-engine prototype's 50 filings: form type, header, cover and keyword rules, no model.

    python3 scripts/events/event_engine_rules.py              # v2 (current): extract -> event_engine/rules/, score
    python3 scripts/events/event_engine_rules.py --version 1  # v1 as first frozen -> event_engine/rules_v1/, score
    python3 scripts/events/event_engine_rules.py --score      # score the existing output only

Scores go to `results/events/event_engine/rules_v<N>_scores.json` and
`rules_v<N>_field_scores.csv`.

ZERO TRIALS. No return, no P&L, no signal; nothing here touches a price or a
holdout. Team lead, 2026-10-19: the ~$49 API pilot of the design note
(`results/events/EVENT_ENGINE_DESIGN_2026-10-15.md` §11) was declined in
favour of two free options, of which this is (a): a deterministic baseline
that says how much of the schema needs no model at all. Its results note is
`results/events/EVENT_ENGINE_PILOT_2026-10-19.md`.

WHY A BASELINE
--------------
The design (§5.5) wants a rule-based parser running beside the model, with
disagreement routed to review, and its tiering (§8) puts a "tier 0: rules"
under every model. Neither was built. Without a baseline, a model's 0.97 on
these filings has nothing to be compared with: if rules alone reach 0.9 on a
field, the model's value on that field is small, and if rules reach 0.2, the
model is doing the work.

WHAT THE RULES MAY READ
-----------------------
* the EDGAR form type (the manifest's `form`, which is the index's);
* the complete submission's SEC header (`COMPANY CONFORMED NAME`), read from
  the EDGAR cache, for the ETF test only;
* the rendered text the model readers read (`_cache_event_engine/text/`), by
  regular expression: the Schedule TO cover page, the 424B cover, the N-14
  letter and notice, and keyword-anchored sentences anywhere in the text.
Every non-null value carries the exact substring of the text it was read from
as its `span`, and the `doc_seq` of the document that substring sits in, so
the same span and value-in-span checks apply to it as to a model.

HOW THE RULES WERE WRITTEN, AND WHAT THAT DOES TO THE SCORE
-----------------------------------------------------------
The 50 filings were split BEFORE any rule was written (`split()`, seeded,
by episode, so an offer and its final amendment fall on the same side; the R
stratum by filing agent, so the Clough/Liberty template sits on one side):
25 `dev` filings, whose texts the author read while writing the rules, and 25
`test` filings, whose texts were not opened. The test score is the honest
one. Two leaks remain and are stated in the results note: the author printed
the gold VALUES of all 50 filings once before the split (to learn the
output shape), and the Eaton Vance tender template appears on both sides
(EFT/EVF dev, EVG test). The rules are version `RULES_VERSION`; a rule changed
after the first score would be a new version, scored and reported beside it.

NO SILENT FALLBACKS. A field no rule can read is null, never a default: there
is no "most filings are common shares" prior, because that would score as
reading. The one exception is written down where it lives: the gold's rule
that a price "equal to the net asset value" is 100% of NAV (design note
§7.2), which is a reading of words, not a prior.
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.events import event_store as E  # noqa: E402

RULES_VERSIONS = {1: "event-rules/1 (2026-10-19)", 2: "event-rules/2 (2026-10-19)"}
RULES_VERSION = RULES_VERSIONS[2]   # the current version; v1 stays runnable (`--version 1`)
OUT = REPO / "results" / "events" / "event_engine"
RULES_DIR = OUT / "rules"          # the current version's output; v1 writes rules_v1/
TEXT_DIR = REPO / "results" / "events" / "_cache_event_engine" / "text"
MANIFEST = OUT / "sample_manifest.csv"
SPLIT_SEED = 20261019
SPAN_MAX = 300          # the readers' instruction: quotes of up to about 300 characters

TENDER_FORMS = re.compile(r"^SC TO-(I|C|T)(/A)?$")
MERGER_FORMS = re.compile(r"^(425|N-14( 8C)?(/A)?|DEFM14A|PREM14A|DEF 14A|PRE 14A|DEFA14A)$")
PROSPECTUS_FORMS = re.compile(r"^424B[1-8]$")

_MONTH = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
DATE_RE = rf"{_MONTH}\.?\s+\d{{1,2}},?\s+\d{{4}}"
# v2: a clause may run through "5:00 p.m." without ending at its full stop (v1 stopped there and missed
# "expired at one minute past 11:59 p.m. Eastern Time on July 19, 2021", a dev filing).
CLAUSE = r"(?:[^.;]|\b[ap]\.\s?m\.)"
NUM_RE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20}
_DOC_RE = re.compile(r"^===== DOCUMENT seq=(\S+)", re.M)


# ============================================================ the split (declared before any rule was written)

def split(man: pd.DataFrame) -> pd.DataFrame:
    """Add `group` and `split` (dev | test) to the manifest. Seeded; groups never straddle the split.

    Groups: T and M by episode (`episode_first_date` within the stratum), so a
    tender offer and its final amendment, or a merger announcement and its
    N-14, are on one side; R by the accession's filing-agent prefix, so one
    agent's typeset template is on one side. Within each stratum the groups
    are shuffled with `SPLIT_SEED` and taken into `dev` until it holds half
    the stratum's filings.
    """
    m = man.copy()
    m["group"] = [f"{s}:{d}" if s in ("T", "M") else f"R:{a[:10]}"
                  for s, d, a in zip(m["stratum"], m["episode_first_date"], m["accession"])]
    rng = random.Random(SPLIT_SEED)
    dev: set[str] = set()
    for _, g in m.groupby("stratum", sort=True):
        groups = sorted(g["group"].unique())
        rng.shuffle(groups)
        n = 0
        for gr in groups:
            if n >= len(g) / 2:
                break
            dev.add(gr)
            n += int((g["group"] == gr).sum())
    m["split"] = m["group"].map(lambda x: "dev" if x in dev else "test")
    return m


# ============================================================ matching helpers

class Doc:
    """The rendered text with its document boundaries, so every match knows its `doc_seq`."""

    def __init__(self, text: str):
        self.text = text
        self.starts = [(m.start(), m.group(1)) for m in _DOC_RE.finditer(text)]
        if not self.starts:
            raise ValueError("no '===== DOCUMENT seq=' line: not a rendered filing text")

    def seq_at(self, pos: int) -> str:
        seq = self.starts[0][1]
        for start, s in self.starts:
            if start > pos:
                break
            seq = s
        return seq

    def doc_text(self, seq: str) -> str:
        for i, (start, s) in enumerate(self.starts):
            if s == seq:
                end = self.starts[i + 1][0] if i + 1 < len(self.starts) else len(self.text)
                return self.text[start:end]
        raise KeyError(seq)


def _span(doc: Doc, start: int, end: int) -> str:
    """The verbatim substring, cut to SPAN_MAX characters around [start, end) without leaving the match."""
    if end - start > SPAN_MAX:
        end = start + SPAN_MAX
    return doc.text[start:end].strip()


def fv(value, doc: Doc, m: re.Match, group: int | str = 0) -> dict:
    """A field value: the value, the whole match as its quote, and the document it sits in."""
    return {"value": value, "span": _span(doc, m.start(), m.end()), "doc_seq": doc.seq_at(m.start())}


def search(doc: Doc, pattern: str, start: int = 0, end: int | None = None, flags=re.I | re.S) -> re.Match | None:
    rx = re.compile(pattern, flags)
    return rx.search(doc.text, start, len(doc.text) if end is None else end)


def to_num(s: str) -> float:
    s = s.strip().lower()
    if s in WORDS:
        return float(WORDS[s])
    return float(s.replace(",", ""))


def to_date(s: str) -> str:
    m = re.match(rf"({_MONTH})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", s.strip(), re.I)
    if not m:
        raise ValueError(f"not a written date: {s!r}")
    months = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december")
    return date(int(m.group(3)), months.index(m.group(1).lower()) + 1, int(m.group(2))).isoformat()


def first_doc_end(doc: Doc) -> int:
    """End of the primary document (seq of the first block): the cover page lives there."""
    return doc.starts[1][0] if len(doc.starts) > 1 else len(doc.text)


# ============================================================ triage

def kind_from_form(form: str) -> str | None:
    f = form.strip().upper()
    if TENDER_FORMS.match(f):
        return "cef_tender"
    if MERGER_FORMS.match(f):
        return "merger"
    if PROSPECTUS_FORMS.match(f):
        return "prospectus"    # resolved by the cover: rights_offering or none
    return None


def fund_type(doc: Doc, header_names: list[str], v: int = 2) -> tuple[str, re.Match | None]:
    """The filer's type from the first 30,000 characters, by the first phrase that names one.

    Order: ETF (by the registrant's conformed name, because a fund's text can
    mention ETFs as holdings), BDC, REIT, a non-listed fund (interval or
    tender-offer fund), then open-end against closed-end by whichever phrase
    comes first. Nothing found: `unknown`, which is a schema value, not a guess.
    """
    head_end = min(len(doc.text), 30_000)
    if any(re.search(r"\bETF\b", n) for n in header_names):
        m = search(doc, r"\bETF\b", 0, head_end, flags=re.S)
        return "etf", m
    if v >= 2:
        # v2 (dev failures: Barings and SLR N-14 8Cs, whose BDC election sits after 30,000 characters; Tekla, a
        # closed-end fund that names REITs among its holdings; GDV, whose preferred shares "are not listed";
        # Guggenheim, whose "closed-end" comes after 30,000 characters): the filer's own BDC election in the
        # first 100,000 characters, then narrower REIT and non-listed phrases, then open- against closed-end
        # over 100,000 characters.
        m = search(doc, r"elected\s+to\s+be\s+(?:regulated|treated)\s+as\s+a\s+business\s+development\s+company",
                   0, min(len(doc.text), 100_000))
        if m:
            return "bdc", m
        rules = (("bdc", r"business\s+development\s+compan(?:y|ies)"),
                 ("reit", r"(?:we|the\s+company|the\s+trust)\s+(?:is|are)\s+(?:a\s+)?(?:\w+\s+)?real\s+estate\s+investment\s+trust"
                          r"|qualif\w*\s+(?:to\s+be\s+taxed\s+)?as\s+a\s+real\s+estate\s+investment\s+trust"),
                 ("interval_or_tender_offer_fund",
                  r"interval\s+fund|no\s+public\s+(?:trading\s+)?market\s+for\s+(?:the\s+|our\s+)?(?:common\s+)?shares"))
    else:
        rules = (("bdc", r"business\s+development\s+compan(?:y|ies)"),
                 ("reit", r"real\s+estate\s+investment\s+trust"),
                 ("interval_or_tender_offer_fund",
                  r"interval\s+fund|no\s+public\s+(?:trading\s+)?market\s+for\s+(?:the\s+|our\s+)?shares"
                  r"|(?:shares|we)\s+(?:are|do)\s+not\s+(?:currently\s+)?(?:intend\s+to\s+)?(?:be\s+)?list"))
    for ft, pat in rules:
        m = search(doc, pat, 0, head_end)
        if m:
            return ft, m
    oc_end = min(len(doc.text), 100_000 if v >= 2 else 30_000)
    mo = search(doc, r"open-end", 0, oc_end)
    mc = search(doc, r"closed-end", 0, oc_end)
    if mo and (not mc or mo.start() < mc.start()):
        return "open_end_fund", mo
    if mc:
        return "closed_end_fund", mc
    return "unknown", None


def final_box_checked(doc: Doc, v: int = 2) -> re.Match | None:
    """The Schedule TO cover's 'final amendment reporting the results' box, when it is checked.

    The renderer writes a box as "[x]", "[X]" or "[_]" (or a ballot-box
    character) either just after the label or on the line before it.
    """
    m = search(doc, r"final\s+amendment\s+reporting\s+the\s+results\s+of\s+the\s+tender\s+offer\s*[.:]?\s*"
                    r"(\[\s*[xX]\s*\]|☒|■)", 0, first_doc_end(doc))
    if m:
        return m
    m = search(doc, r"(\[\s*[xX]\s*\]|☒|■)\s*(?:check\s+the\s+following\s+box\s+if\s+the\s+filing\s+is\s+)?"
                    r"a?\s*final\s+amendment\s+reporting\s+the\s+results", 0, first_doc_end(doc))
    if m or v < 2:
        return m
    # v2 (dev failures: GDV prints "☒ Check the box if the filing is a final amendment"; FS Credit heads its
    # filing "FINAL AMENDMENT TO TENDER OFFER STATEMENT" and prints no box)
    return (search(doc, r"(\[\s*[xX]\s*\]|☒|■)\s*check\s+the\s+(?:following\s+)?box\s+if\s+the\s+filing\s+is\s+a\s+"
                        r"final\s+amendment", 0, first_doc_end(doc))
            or search(doc, r"final\s+amendment\s+to\s+(?:the\s+)?(?:tender\s+offer\s+statement|schedule\s+to)"
                           r"|is\s+the\s+final\s+amendment", 0, first_doc_end(doc)))


def doc_role(form: str, doc: Doc, v: int = 2) -> str:
    f = form.strip().upper()
    if f in ("SC TO-I", "SC TO-T"):
        return "offer_document"
    if f in ("SC TO-I/A", "SC TO-T/A"):
        return "final_result" if final_box_checked(doc, v) else "amendment"
    if f == "SC TO-C" or f in ("425", "DEFA14A"):
        return "announcement"
    if MERGER_FORMS.match(f):
        return "registration_or_proxy"
    if PROSPECTUS_FORMS.match(f):
        return "prospectus"
    return "other"


RIGHTS_COVER_RE = (r"rights\s+offering|rights\s+to\s+(?:subscribe|purchase|acquire)"
                   r"|(?:non-?\s?transferable|transferable)\s+(?:subscription\s+)?rights")


def is_rights_offering(doc: Doc) -> re.Match | None:
    """A 424B is a rights offering only if its cover names the offering AND its mechanics.

    The sampling rule (amendment 2) admitted any cover with an offering
    phrase; a BDC notes supplement passes that on "other rights to acquire
    equity securities". The mechanics test needs, in the first 8,000
    characters of the primary document, a record date and a subscription
    price or period as well.
    """
    end = min(first_doc_end(doc), doc.starts[0][0] + 8_000)
    m = search(doc, RIGHTS_COVER_RE, 0, end)
    if not m:
        return None
    if not search(doc, r"record\s+date", 0, end):
        return None
    if not search(doc, r"subscription\s+(?:price|period)", 0, end):
        return None
    return m


# ============================================================ conditions

CONDITION_RULES = (
    ("shareholder_approval", r"(?:shareholder|stockholder)s?['’]?\s+approv|approv\w*\s+(?:of|by)\s+(?:the\s+)?(?:requisite\s+)?(?:shareholders|stockholders)"
                             r"|vote\s+of\s+(?:the\s+)?(?:shareholders|stockholders)"),
    ("regulatory_approval", r"governmental\s+(?:authority|entity|approval|consent)|regulatory\s+approval|exemptive\s+(?:relief|order)"
                            r"|no-action|approval\s+of\s+the\s+(?:sec|commission)"),
    ("registration_effective", r"registration\s+statement[^.]{0,120}?(?:become|been\s+declared|declared)\s+effective|stop\s+order"),
    ("tax_opinion", r"opinion[^.]{0,160}?(?:tax|section\s+368|reorganization\s+within\s+the\s+meaning)"),
    ("listing", r"delist|listed\s+(?:for\s+trading\s+)?on\s+(?:the\s+)?(?:new\s+york\s+stock\s+exchange|nyse|nasdaq)"
                r"|approved\s+for\s+listing|national\s+securities\s+exchange"),
    ("financing", r"financing\s+condition|obtain(?:ing)?\s+(?:the\s+)?financing"),
    ("minimum_tender", r"minimum\s+(?:number\s+of\s+shares|tender\s+condition|condition)"),
    ("market_disruption", r"suspension\s+of\s+(?:or\s+limitation\s+on\s+)?trading|banking\s+moratorium|commencement\s+of\s+(?:a\s+)?war"
                          r"|armed\s+hostilities|limitation\s+on\s+prices|decline\s+in\s+(?:the\s+)?(?:general\s+)?(?:level\s+of\s+)?market"),
    ("legal_injunction", r"injunction|action\s+or\s+proceeding|threatened,?\s+instituted\s+or\s+pending|restraining\s+order"),
    ("ric_or_tax_status", r"regulated\s+investment\s+company|subchapter\s+m\b|\bric\b"),
    ("board_discretion", r"(?:sole\s+)?(?:judgment|judgement|discretion)\s+of\s+the\s+board|board[^.]{0,60}?(?:sole\s+)?(?:judgment|judgement|discretion)"
                         r"|in\s+its\s+(?:sole\s+)?(?:reasonable\s+)?(?:judgment|judgement|discretion)"),
    ("nav_or_price_decline", r"decline\s+in\s+(?:the\s+)?(?:fund['’]s\s+)?(?:net\s+asset\s+value|nav)\b"),
    ("other", r"fiduciary\s+dut|material\s+adverse\s+effect|investment\s+objective"),
)
CONDITION_HEADINGS = (r"(?:certain\s+)?conditions\s+(?:of|to)\s+(?:the|this)\s+(?:offer|tender\s+offer)"
                      r"|conditions\s+precedent|conditions\s+to\s+(?:the\s+)?(?:obligations|closing|consummation|completion)"
                      r"|closing\s+conditions")
CONDITION_WINDOW = 6_000


def conditions(doc: Doc, limit: int | None = None) -> dict | None:
    """The set of condition categories named in the conditions sections, one quote per category.

    A conditions section is the CONDITION_WINDOW characters after a heading
    that names one (on a line of its own, at most 120 characters); within all
    such windows each category takes its first keyword match. The categories
    are the schema's (`event_store.CONDITION_CATS`); the keywords are written
    from the categories' own names, not from the gold.
    """
    end = len(doc.text) if limit is None else min(limit, len(doc.text))
    windows = []
    for m in re.finditer(rf"^[^\n]{{0,40}}(?:{CONDITION_HEADINGS})[^\n]{{0,80}}$", doc.text[:end], re.I | re.M):
        windows.append((m.start(), min(end, m.end() + CONDITION_WINDOW)))
    if not windows:
        return None
    found: dict[str, re.Match] = {}
    for cat, pat in CONDITION_RULES:
        for a, b in windows:
            m = search(doc, pat, a, b)
            if m:
                found[cat] = m
                break
    if not found:
        return None
    cats = [c for c, _ in CONDITION_RULES if c in found]
    spans = [_sentence(doc, found[c]) for c in cats]
    return {"value": cats, "spans": spans, "doc_seq": doc.seq_at(found[cats[0]].start())}


def _sentence(doc: Doc, m: re.Match) -> str:
    """A quote around a keyword: up to 120 characters either side, inside one line, verbatim."""
    a = max(doc.text.rfind("\n", 0, m.start()) + 1, m.start() - 120)
    b = doc.text.find("\n", m.end())
    b = len(doc.text) if b < 0 else min(b, m.end() + 120)
    return doc.text[a:b].strip()


# ============================================================ tender

def tender_terms(doc: Doc, form: str, role: str, v: int = 2) -> dict:
    t: dict = {}
    cover_end = first_doc_end(doc)
    # security class: the line above "(Title of Class of Securities)" on the Schedule TO cover.
    # v2 (dev failure: FS Global prints "Par Value $0.001 per share" between the class and the caption):
    # the three lines above it.
    above = r"((?:[^\n]{1,200}\n\s*){1,3})" if v >= 2 else r"([^\n]{3,200})\n\s*"
    m = search(doc, above + r"\(title\s+of\s+class\s+of\s+securities\)", 0, cover_end)
    if m:
        line = m.group(1).lower()
        cls = ("preferred" if "preferred" in line else "notes" if re.search(r"\bnotes?\b|debenture", line)
               else "common" if re.search(r"common|beneficial\s+interest|\bshares\b|\bstock\b", line) else "other")
        t["security_class"] = fv(cls, doc, m)
    # price basis and percent of NAV
    m_dutch = search(doc, r"dutch\s+auction|not\s+(?:greater|more)\s+than\s+\$[\d.]+\s+(?:nor|or)\s+less\s+than\s+\$")
    m_pct = search(doc, rf"({NUM_RE})\s*%\s+of\s+(?:the\s+)?(?:fund['’]s\s+|trust['’]s\s+|company['’]s\s+)?"
                        r"(?:net\s+asset\s+value|nav)\b")
    m_par = search(doc, r"(?:price|amount)[^.]{0,60}?equal\s+to\s+(?:the\s+)?(?:fund['’]s\s+|company['’]s\s+)?"
                        r"(?:net\s+asset\s+value|nav)\s+per\s+(?:share|unit)")
    m_mkt = search(doc, rf"({NUM_RE})\s*%\s+of\s+(?:the\s+)?(?:market|closing)\s+price")
    m_fix = search(doc, r"(?:purchase\s+price|price)\s+of\s+\$(\d+(?:\.\d+)?)\s+per\s+(?:share|unit|note)")
    if m_dutch:
        t["price_basis"] = fv("dutch_auction", doc, m_dutch)
    elif m_pct:
        t["price_basis"] = fv("pct_of_nav", doc, m_pct)
        t["price_pct_nav"] = fv(to_num(m_pct.group(1)), doc, m_pct)
    elif m_par:
        # the gold's written rule (design note §7.2): a price "equal to the net asset value" is 100% of NAV
        t["price_basis"] = fv("pct_of_nav", doc, m_par)
        t["price_pct_nav"] = fv(100.0, doc, m_par)
    elif m_mkt:
        t["price_basis"] = fv("pct_of_market", doc, m_mkt)
    elif m_fix:
        t["price_basis"] = fv("fixed_price", doc, m_fix)
    # size: "up to 50% or 19,931,845 of its outstanding", "up to 400,000 shares", the fee table's "N shares ... (X% of"
    m = search(doc, rf"up\s+to\s+({NUM_RE})\s*%\s+or\s+({NUM_RE})\s+(?:of\s+its\s+)?(?:issued\s+and\s+)?(?:outstanding\s+)?")
    if m:
        t["size_pct_outstanding"] = fv(to_num(m.group(1)), doc, m)
        t["size_shares"] = fv(to_num(m.group(2)), doc, m)
    else:
        m = search(doc, rf"up\s+to\s+({NUM_RE})\s*%\s+of\s+(?:its|the|the\s+fund['’]s|our)\s+(?:issued\s+and\s+)?"
                        r"(?:then\s+)?outstanding")
        if m:
            t["size_pct_outstanding"] = fv(to_num(m.group(1)), doc, m)
        m = search(doc, r"up\s+to\s+(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s+(?:of\s+(?:its|the)\s+)?(?:issued\s+and\s+)?"
                        r"(?:outstanding\s+)?(?:common\s+|preferred\s+)?(?:shares|units)")
        if m:
            t["size_shares"] = fv(to_num(m.group(1)), doc, m)
    # commencement: the gold's rule (design note §7.2) is the Offer to Purchase's date, absent another stated start
    if form.upper() != "SC TO-C":
        m = search(doc, rf"offer\s+to\s+purchase,?\s+dated\s+({DATE_RE})")
        if m:
            t["commencement_date"] = fv(to_date(m.group(1)), doc, m)
    # expiration: the latest date the expiry phrases state (instructions rule 4)
    best = None
    if v >= 2:
        # v2 (dev failures: a credit-agreement exhibit's date, a "40 business days" withdrawal date, and
        # "11:59 p.m." ending the clause early): only "expire(s|d) at <time> on <date>" and "<date> (the
        # Expiration Date)" in the first 60,000 characters; the first such date in an offer document, the
        # latest in an amendment (rule 4's extensions arrive in amendments)
        pats = (rf"expire[sd]?\s+at\s+{CLAUSE}{{0,90}}?({DATE_RE})",
                rf"({DATE_RE})\s*,?\s*\(\s*(?:such\s+date\s+)?(?:the\s+)?[“\"]?expiration\s+date")
        lim = min(len(doc.text), 60_000)
        cands = sorted(((m.start(), i, m) for i, p in enumerate(pats)
                        for m in re.finditer(p, doc.text[:lim], re.I | re.S)), key=lambda z: (z[0], z[1]))
        for _, _, m in cands:
            d = to_date(m.group(1))
            if best is None or (form.upper().endswith("/A") and d > best[0]):
                best = (d, m)
    else:
        for m in re.finditer(rf"(?:will\s+expire|expire[sd]?|expiration\s+date)[^.;]{{0,90}}?({DATE_RE})", doc.text, re.I | re.S):
            d = to_date(m.group(1))
            if best is None or d > best[0]:
                best = (d, m)
    if best:
        t["expiration_date"] = fv(best[0], doc, best[1])
    m = search(doc, r"pro\s*-?\s*rata|pro-?ration|prorat")
    if m:
        t["proration"] = fv(True, doc, m)
    if role != "final_result":
        c = conditions(doc)
        if c:
            t["conditions"] = c
    # trigger origin, by the first rule that fires (a judgement field: rules read words, not intent)
    for origin, pat in (("activist_settlement", r"standstill\s+agreement|settlement\s+agreement"),
                        ("conditional_programme", r"conditional\s+tender"),
                        ("merger_related", r"tender\s+offer[^.]{0,200}?(?:in\s+connection\s+with|related\s+to)\s+(?:the\s+)?(?:proposed\s+)?(?:reorganization|merger)"),
                        ("periodic_liquidity", r"quarterly\s+(?:tender|repurchase)|periodic\s+(?:tender|repurchase)|share\s+repurchase\s+program")):
        m = search(doc, pat)
        if m:
            t["trigger_origin"] = fv(origin, doc, m)
            break
    if form.upper().endswith("/A"):
        m = search(doc, rf"({NUM_RE})\s+(?:common\s+|preferred\s+)?shares[^.]{{0,80}}?(?:were|had\s+been)\s+(?:validly\s+|properly\s+)?tendered")
        if m:
            t["shares_tendered"] = fv(to_num(m.group(1)), doc, m)
        m = (search(doc, rf"({NUM_RE})\s+(?:common\s+|preferred\s+)?shares\s+(?:were|have\s+been)\s+accepted")
             or search(doc, rf"accepted\s+for\s+(?:purchase|payment|repurchase)\s+({NUM_RE})\s+(?:common\s+|preferred\s+)?shares"))
        if m:
            t["shares_accepted"] = fv(to_num(m.group(1)), doc, m)
        m = search(doc, rf"pro-?\s?ration\s+factor[^.]{{0,60}}?({NUM_RE})\s*%")
        if m:
            t["proration_factor_pct"] = fv(to_num(m.group(1)), doc, m)
        m = search(doc, r"(?:repurchased|purchased|accepted)[^.]{0,80}?(?:at\s+a|at\s+the)\s+(?:purchase\s+)?price\s+of\s+\$(\d+(?:\.\d+)?)")
        if m:
            t["final_price_per_share"] = fv(to_num(m.group(1)), doc, m)
    return t


# ============================================================ merger

def merger_terms(doc: Doc, v: int = 2) -> dict:
    t: dict = {}
    head = min(len(doc.text), 50_000)
    m = search(doc, r"common\s+(?:shares|stock)", 0, head)
    if m:
        t["security_class"] = fv("common", doc, m)
    else:
        m = search(doc, r"class\s+[A-Z]\s+shares|investor\s+class|institutional\s+class", 0, head)
        if m:
            t["security_class"] = fv("other", doc, m)
    m_ratio = search(doc, r"(\d\.\d{2,6})\s+shares?\s+of\s+[^.]{0,80}?(?:common\s+(?:stock|shares)\s+)?for\s+each\s+(?:outstanding\s+)?share")
    if not m_ratio:
        m_ratio = search(doc, r"exchange\s+ratio\s+(?:of|equal\s+to)\s+(\d\.\d{2,6})")
    m_cash = search(doc, r"\$(\d+\.\d+)\s+per\s+(?:share|[A-Z]\w+\s+share)[^.]{0,40}?in\s+cash"
                         r"|(?:cash|in\s+cash)[^.]{0,60}?approximately\s+\$(\d+\.\d+)\s+per\s+share")
    m_nav = search(doc, r"aggregate\s+net\s+asset\s+value[^.]{0,160}?equal|equal\s+(?:in\s+value\s+)?to\s+the\s+(?:aggregate\s+)?net\s+asset\s+value"
                        r"|based\s+on\s+(?:the\s+)?(?:relative\s+)?net\s+asset\s+values?\s+(?:per\s+share\s+)?of")
    if v >= 2 and m_nav and m_ratio and not m_cash:
        # v2 (dev failures: KYN and SLR state NAV-for-NAV exchanges and print an illustrative ratio, 1.32 and
        # 0.7763, which v1 read as a fixed ratio): a NAV-for-NAV statement wins over a ratio without cash
        m_ratio = None
    if m_ratio:
        t["exchange_ratio"] = fv(to_num(m_ratio.group(1)), doc, m_ratio)
    if m_cash:
        t["cash_per_share"] = fv(to_num(m_cash.group(1) or m_cash.group(2)), doc, m_cash)
    if m_ratio and m_cash:
        t["exchange_basis"] = fv("cash_and_stock", doc, m_ratio)
    elif m_ratio:
        t["exchange_basis"] = fv("fixed_ratio", doc, m_ratio)
    elif m_nav:
        t["exchange_basis"] = fv("nav_for_nav", doc, m_nav)
    elif m_cash:
        t["exchange_basis"] = fv("cash", doc, m_cash)
    # v2 (dev failures: Guggenheim, KYN and Nuveen name "caps, floors and collars" among derivatives): a
    # collar counts only within 150 characters of the deal's consideration or exchange ratio
    m = (search(doc, r"(?:consideration|exchange\s+ratio)[^\n]{0,150}?\bcollar\b|\bcollar\b[^\n]{0,150}?(?:consideration|exchange\s+ratio)")
         if v >= 2 else search(doc, r"\bcollar\b"))
    if m:
        neg = search(doc, r"(?:no|without\s+a|not\s+subject\s+to\s+a)\s+collar")
        t["collar"] = fv(False, doc, neg) if neg else fv(True, doc, m)
    c = conditions(doc)
    if c:
        t["conditions"] = c
    m = search(doc, rf"expected\s+to\s+(?:close|be\s+completed|be\s+consummated|occur|take\s+place)\s+"
                    rf"(?:in\s+the\s+|during\s+the\s+|in\s+|during\s+)?((?:on\s+or\s+(?:about|around)\s+)?(?:{DATE_RE}|"
                    r"(?:first|second|third|fourth)\s+(?:quarter|half)\s+of\s+(?:calendar\s+(?:year\s+)?|fiscal\s+(?:year\s+)?)?\d{4}))")
    if m:
        t["expected_close"] = fv(re.sub(r"\s+", " ", m.group(1)).strip(), doc, m)
    m = (search(doc, rf"(?:has|shall)\s+not\s+(?:been\s+)?(?:occurred|consummated|closed|completed)\s+(?:on\s+or\s+)?"
                     rf"(?:before|by|prior\s+to)\s+({DATE_RE})")
         or search(doc, rf"({DATE_RE})\s*\(\s*(?:as\s+it\s+may\s+be\s+extended,?\s+)?the\s+[“\"]?(?:outside|end|termination)\s+date"))
    if m:
        t["termination_date"] = fv(to_date(m.group(1)), doc, m)
    m = (search(doc, rf"meeting[^.]{{0,250}}?(?:to\s+be\s+held|scheduled\s+to\s+be\s+held|will\s+be\s+held)\s+on\s+"
                     rf"(?:\w+day,\s+)?({DATE_RE})", 0, head)
         or search(doc, rf"to\s+be\s+held\s+on\s+(?:\w+day,\s+)?({DATE_RE})", 0, head))
    if m:
        t["meeting_date"] = fv(to_date(m.group(1)), doc, m)
    m = (search(doc, rf"of\s+record\s+(?:as\s+of|at|on)\s+the\s+close\s+of\s+business\s+on\s+(?:\w+day,\s+)?({DATE_RE})", 0, head)
         or search(doc, rf"({DATE_RE})\s*\(\s*the\s+[“\"]?record\s+date", 0, head))
    if m:
        t["record_date"] = fv(to_date(m.group(1)), doc, m)
    return t


# ============================================================ rights offering

def rights_terms(doc: Doc, v: int = 2) -> dict:
    t: dict = {}
    cover = min(len(doc.text), doc.starts[0][0] + 15_000)
    # v2 (dev failures: Gabelli states the per-share right and the fixed price in "The Offer", after the
    # first 15,000 characters): those two rules read the first 60,000
    terms_end = min(len(doc.text), doc.starts[0][0] + 60_000) if v >= 2 else cover
    m = search(doc, r"common\s+(?:shares|stock)|shares\s+of\s+(?:common\s+stock|beneficial\s+interest)", 0, cover)
    if m:
        t["security_class"] = fv("common", doc, m)
    issued = r"(?:receive|be\s+issued|issued|issue|issuing)" if v >= 2 else r"(?:receive|be\s+issued|issue|issuing)"
    m = search(doc, issued + r"\s+(one|1)\s+(?:\(1\)\s+)?(?:transferable\s+|non-?\s?transferable\s+)?"
                    r"(?:subscription\s+)?right\s+for\s+(?:each|every)", 0, terms_end)
    if m:
        t["rights_per_share"] = fv(1.0, doc, m)
    m = (search(doc, r"for\s+every\s+(\w+)\s+(?:\(\d+\)\s+)?rights", 0, cover)
         or search(doc, r"(\w+)\s+(?:\(\d+\)\s+)?rights\s+(?:are|will\s+be)\s+required\s+to\s+(?:purchase|subscribe\s+for)\s+one", 0, cover)
         or search(doc, r"one\s+(?:\(1\)\s+)?(?:new\s+)?(?:common\s+)?share\s+for\s+(?:each|every)\s+(\w+)\s+(?:\(\d+\)\s+)?rights", 0, cover))
    if m and (m.group(1).lower() in WORDS or m.group(1).isdigit()):
        t["rights_per_new_share"] = fv(to_num(m.group(1)), doc, m)
    m_less = search(doc, r"lesser\s+of|whichever\s+is\s+(?:lower|less)", 0, cover)
    m_great = search(doc, r"greater\s+of|whichever\s+is\s+(?:higher|greater)", 0, cover)
    m_mkt = search(doc, rf"({NUM_RE})\s*%\s+of\s+the\s+(?:volume[\s-]+weighted|average|last\s+reported|reported|market|closing)", 0, cover)
    m_nav = search(doc, rf"({NUM_RE})\s*%\s+of\s+(?:the\s+)?(?:\w+['’]s\s+)?(?:reported\s+)?(?:net\s+asset\s+value|nav)\b", 0, cover)
    m_fix = search(doc, r"subscription\s+price\s+(?:of|is|will\s+be)\s+\$\d+(?:\.\d+)?\s+per", 0, cover)
    if v >= 2 and not m_fix:   # v2 (dev failures: Gabelli's "$5.50 (the “Subscription Price”)")
        m_fix = search(doc, r"\$\d+(?:\.\d+)?\s*(?:per\s+(?:\w+\s+)?share\s*)?\(\s*the\s+[“\"]?subscription\s+price", 0, terms_end)
    if m_less:
        t["price_reference"] = fv("lesser_of_nav_and_market", doc, m_less)
        mp = m_mkt or m_nav
        if mp:
            t["price_pct"] = fv(to_num(mp.group(1)), doc, mp)
    elif m_great:
        t["price_reference"] = fv("greater_of_nav_and_market", doc, m_great)
        if m_mkt:
            t["price_pct"] = fv(to_num(m_mkt.group(1)), doc, m_mkt)
        if m_nav:
            t["price_floor_pct_nav"] = fv(to_num(m_nav.group(1)), doc, m_nav)
    elif m_mkt:
        t["price_reference"] = fv("market", doc, m_mkt)
        t["price_pct"] = fv(to_num(m_mkt.group(1)), doc, m_mkt)
        mf = search(doc, rf"less\s+than\s+({NUM_RE})\s*%\s+of\s+(?:the\s+)?(?:\w+['’]s\s+)?(?:net\s+asset\s+value|nav)\b", 0, cover)
        if mf:
            t["price_floor_pct_nav"] = fv(to_num(mf.group(1)), doc, mf)
    elif m_nav:
        t["price_reference"] = fv("nav", doc, m_nav)
        t["price_pct"] = fv(to_num(m_nav.group(1)), doc, m_nav)
    elif m_fix:
        t["price_reference"] = fv("fixed", doc, m_fix)
    m = (search(doc, rf"({DATE_RE})\s*\(\s*the\s+[“\"]?record\s+date", 0, cover)
         or search(doc, rf"of\s+record\s+(?:as\s+of|on|at)\s+(?:the\s+close\s+of\s+business\s+on\s+)?({DATE_RE})", 0, cover))
    if m:
        t["record_date"] = fv(to_date(m.group(1)), doc, m)
    m = (search(doc, rf"({DATE_RE})\s*,?\s*(?:\(\s*the\s+[“\"]?expiration\s+date|unless\s+(?:the\s+offer\s+is\s+)?extended)", 0, cover)
         or search(doc, rf"(?:expires?|expiration\s+date)[^.;]{{0,90}}?({DATE_RE})", 0, cover))
    if m:
        t["expiration_date"] = fv(to_date(m.group(1)), doc, m)
    m = search(doc, r"non-?\s?transferable|transferable", 0, cover)
    if m:
        t["transferable"] = fv(not m.group(0).lower().startswith("non"), doc, m)
    m = search(doc, r"over-?\s?subscription\s+privilege|oversubscription\s+privilege|over-subscription", 0, cover)
    if m:
        t["over_subscription"] = fv(True, doc, m)
    m = (search(doc, r"(\d{1,3}(?:,\d{3})+)\s+(?:common\s+)?shares[^.]{0,120}?issuable\s+upon\s+(?:the\s+)?exercise", 0, cover)
         or search(doc, r"offering\s+(?:up\s+to\s+)?(\d{1,3}(?:,\d{3})+)\s+(?:common\s+)?shares", 0, cover))
    if v >= 2 and not m:   # v2 (dev failures: Gabelli's cover line "262,669,923 Rights for 26,266,993 Shares")
        m = search(doc, r"[\d,]+\s+rights\s+for\s+(\d{1,3}(?:,\d{3})+)\s+(?:shares|common\s+shares)", 0, cover)
    if m:
        t["max_new_shares"] = fv(to_num(m.group(1)), doc, m)
    return t


# ============================================================ one filing

def extract(accession: str, form: str, text: str, header_names: list[str], v: int = 2) -> dict:
    """One filing -> the readers' JSON shape (`extraction_instructions.txt`), every term of the kind present (null if unread)."""
    doc = Doc(text)
    k = kind_from_form(form)
    if k is None:
        raise ValueError(f"{accession}: form {form!r} is outside the rules' form map")
    ft, ft_m = fund_type(doc, header_names, v)
    role = doc_role(form, doc, v)
    kind_m = search(doc, rf"#####\s+FILING\s+{re.escape(accession)}\s+FORM\s+{re.escape(form)}", flags=re.S)
    kind_span = doc.text[kind_m.start():kind_m.end()] if kind_m else None
    if k == "prospectus":
        rm = is_rights_offering(doc)
        k = "rights_offering" if rm else "none"
        if rm:
            kind_span = _sentence(doc, rm)
    if k == "merger" and ft in ("reit", "operating_company"):
        k = "equity_mna"
    terms: dict = {}
    if k == "cef_tender":
        terms = tender_terms(doc, form, role, v)
    elif k == "merger":
        terms = merger_terms(doc, v)
    elif k == "equity_mna":
        mt = merger_terms(doc, v)
        names = {s.name for s in E.FIELDS["equity_mna"]}
        terms = {n: x for n, x in mt.items() if n in names}
    elif k == "rights_offering":
        terms = rights_terms(doc, v)
    out_terms = {s.name: terms.get(s.name) for s in E.FIELDS[k]}
    bad = set(terms) - set(out_terms)
    if bad:
        raise ValueError(f"{accession}: rule produced fields outside the {k} schema: {sorted(bad)}")
    return {"accession": accession,
            "triage": {"kind": k, "fund_type": ft, "doc_role": role, "kind_span": kind_span},
            "events": [] if k == "none" else [{"kind": k, "terms": out_terms}],
            "uncertain_fields": [],
            "notes": f"{RULES_VERSIONS[v]}; fund_type from {('“' + ft_m.group(0)[:60] + '”') if ft_m else 'no phrase'}",
            "extractor": RULES_VERSIONS[v]}


def header_names(raw: str) -> list[str]:
    hdr = raw[: raw.find("</SEC-HEADER>")] if "</SEC-HEADER>" in raw else ""
    if not hdr:
        raise ValueError("no SEC header in the submission")
    return [n.strip() for n in re.findall(r"COMPANY CONFORMED NAME:\s*(.+)", hdr)]


def out_dir(v: int) -> Path:
    return RULES_DIR if v == max(RULES_VERSIONS) else OUT / f"rules_v{v}"


def run(v: int) -> pd.DataFrame:
    from scripts.data.edgar_client import cache_path, filing_txt_url
    man = pd.read_csv(MANIFEST)
    d = out_dir(v)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.json"):
        old.unlink()
    for r in man.itertuples():
        text = (TEXT_DIR / f"{r.accession}.txt").read_text()
        raw_p = cache_path(filing_txt_url(int(r.cik), r.accession))
        if not raw_p.exists():
            raise FileNotFoundError(f"{raw_p}: the submission is not in the EDGAR cache "
                                    "(python3 scripts/events/event_engine_sample.py --offline rebuilds the texts from it)")
        names = header_names(raw_p.read_bytes().decode("latin-1"))
        x = extract(r.accession, r.form, text, names, v)
        (d / f"{r.accession}.json").write_text(json.dumps(x, indent=1, ensure_ascii=False))
    return man


def main(argv: list[str]) -> int:
    from scripts.events import event_engine_pilot as P
    v = int(argv[argv.index("--version") + 1]) if "--version" in argv else max(RULES_VERSIONS)
    if v not in RULES_VERSIONS:
        raise ValueError(f"no rules version {v}; known: {sorted(RULES_VERSIONS)}")
    if "--score" not in argv:
        run(v)
    res = P.score_reader(out_dir(v), f"rules_v{v}", splits=True)
    (OUT / f"rules_v{v}_scores.json").write_text(json.dumps(res["summary"], indent=1, default=str))
    res["by_field"].to_csv(OUT / f"rules_v{v}_field_scores.csv", index=False)
    print(json.dumps(res["summary"], indent=1, default=str)[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
