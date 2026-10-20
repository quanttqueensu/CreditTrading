"""DG-E1-3's reading pack and collector: the failed-deal census read by Claude Code subagents. Zero trials.

    python3 scripts/events/e1_failed_reading.py prepare --root <dir>
        # <dir>/input/: per-episode excerpts (part files), batches, INSTRUCTIONS.md, BRIEF_TEMPLATE.txt, plan.json
    python3 scripts/events/e1_failed_reading.py collect --root <dir> --model sonnet [--partial]
        # <dir>/out/<model>/*.json -> results/events/e1/e1_failed_deal_readings.csv (what Stage 0 reads),
        #   results/events/e1/e1_failed_reading_review.csv, tracked copies in results/events/e1/readings_raw/<model>/

WHY
---
E1's data gate DG-E1-3 (`results/events/PREREG_E1_MERGER_PAIR_2026-10-19.md` §4.3, §13) reads every
census candidate episode (273 on 2026-10-19; `e1_merger_pair.failed_census`), recording the outcome,
the first public filing announcing the deal and the filing that made a failure public, each with a
verbatim quote that the trial re-finds in the filing on every run. Reading R10, ruled 2026-10-20,
keeps all 273 (the counterparty is named only inside the filings). The coordinator, 2026-10-20: the
episodes are read by Sonnet subagents in batches, in the event-engine pilot's format
(`scripts/events/event_engine_pilot.py`), not by the agent that runs the trial.

WHAT A READER SEES, AND WHY AN EXCERPT
--------------------------------------
For each episode, every filing of `e1_merger_pair.CENSUS_FORMS` filed by or about the episode's CIK
from 30 days before its first filing to 730 days after (exactly what `fetch-edgar` cached), listed
with its date, form, accession and the parties its SGML header names (with their CIKs). The whole
filings run to gigabytes (7.9 GB for the 202 CIKs), so each filing is EXCERPTED by a fixed rule:
its first `HEAD_CHARS[form]` characters, plus up to `MAX_WINDOWS` windows of +-`WINDOW` characters
around outcome language (`OUTCOME_RE`), in that order of priority, within `EPISODE_CHARS` per
episode. The first filing and any RW, 8-K or DEFA14A come first. A filing or a window the budget
leaves out is LISTED as omitted, so a reader knows it has not seen it and writes null rather than
guessing. The rendering (`render`) only changes whitespace relative to `conditional_tender_census.plain`,
so a quote copied from the excerpt is found by `quote_in` in the raw filing (tested).

WHAT THE COLLECTOR DOES
-----------------------
It validates each reader's JSON (shape, the outcome vocabulary, every quote re-found in the RAW cached
filing it cites, every cited accession one of the episode's listed filings), takes each cited
filing's date from EDGAR's own filing list (a reader's date that disagrees is a problem, recorded),
assigns `deal_id` (target CIK > acquirer CIK, split when two announcements of one pair are more than
a year apart), sets `in_trial` = Y exactly when both parties are listed and the outcome is a failure,
and writes the readings file `e1_merger_pair.check_readings` validates. Problems never stop the
write: they go to the review file, and Stage 0's own check fails on them until they are resolved.
A missing reading is listed there too, and `--partial` is required to collect while any is missing.

Tests: scripts/events/tests/test_e1_failed_reading.py (synthetic filings; no network).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.events import e1_merger_pair as e1  # noqa: E402

CHARS_PER_TOKEN = 2.692307692307692   # event_engine_score.CHARS_PER_TOKEN, the design's estimate [S]
BATCH_TOKENS = 90_000                 # the pilot's per-subagent input cap (event_engine_pilot.BATCH_TOKENS)
BATCH_MAX_EPISODES = 10
EPISODE_CHARS = 40_000               # the budget for full excerpts; every filing first gets a compact one
EPISODE_MAX = 200_000                # an episode with many filings may grow to this (~74k tokens, one batch)
COMPACT_HEAD = 800                   # a compact excerpt: the lead and the strong outcome windows only
COMPACT_WINDOW = 400
COMPACT_MAX_WINDOWS = 2
PART_CHARS = 30_000                   # one Read call each (the pilot's PART_CHARS)
WRAP_AT = 1_000
WINDOW = 600
MAX_WINDOWS = 3
HEAD_CHARS = {"RW": 4_000, "8-K": 4_000, "DEFA14A": 3_000, "425": 3_000}
HEAD_DEFAULT = 2_500                  # N-14s, proxies, N-8F: the cover and letter state the deal
EXHIBIT_HEAD = 3_000                  # an 8-K's or 425's press release (EX-99*)
FIRST_PRIORITY = ("RW", "8-K", "DEFA14A")
# Outcome language, strongest first. Boilerplate ("the Agreement may be terminated") also matches the
# weaker patterns, which is why windows are capped and the strong patterns are taken first.
OUTCOME_RE = (
    re.compile(r"withdr[ae]wn?|withdraw(?:al|ing)|abandon|will not (?:proceed|be (?:consummated|completed))|"
               r"did not (?:approve|receive|obtain|achieve)|(?:was|were|has been|have been) not approved|"
               r"failed to (?:approve|obtain|receive|achieve)|insufficient (?:votes|number)|lack of (?:a )?quorum|"
               r"(?:has|have|had) (?:mutually )?(?:agreed to )?terminated|(?:was|were) terminated|no longer (?:be )?pursu", re.I),
    re.compile(r"(?:was|were|has been|have been) (?:successfully )?(?:completed|consummated)|completed the (?:reorganization|merger)|"
               r"consummation of the (?:reorganization|merger)|approved (?:by|the) (?:the )?(?:shareholders|stockholders)|"
               r"adjourn|postpone", re.I),
)
READER_OUTCOMES = tuple(o for o in e1.OUTCOMES if o != "completed_after_crsp")
_TAG_RE = re.compile(r"<[^>]{0,400}>")       # conditional_tender_census._TAG_RE, the same rule
_BLOCK_TAGS = re.compile(r"^</?(?:p|div|br|tr|li|h[1-6]|table|center|pre|ul|ol)\b", re.I)


# ============================================================ rendering and excerpts

def render(text: str) -> str:
    """HTML/SGML -> readable text that differs from `plain(text)` in whitespace only: tags become a
    space (block tags a line break), entities are decoded AFTER tags are removed (plain's order),
    spaces collapse within lines, blank lines go. So normalise(render(x)) == normalise(x)."""
    t = _TAG_RE.sub(lambda m: "\n" if _BLOCK_TAGS.match(m.group(0)) else " ", text)
    t = html.unescape(t)
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in t.split("\n"))
    return "\n".join(ln for ln in lines if ln) + "\n"


def wrap_long_lines(text: str, width: int = WRAP_AT) -> str:
    """Break lines longer than `width` at spaces only (whitespace-only, so quotes are unaffected)."""
    out = []
    for ln in text.split("\n"):
        while len(ln) > width:
            cut = ln.rfind(" ", 0, width)
            if cut <= 0:
                cut = ln.find(" ", width)
                if cut < 0:
                    break
            out.append(ln[:cut])
            ln = ln[cut + 1:]
        out.append(ln)
    return "\n".join(out)


def sgml_parties(raw: str) -> list[dict]:
    """The parties the SGML header names: [{role, name, cik}] (SUBJECT COMPANY, FILED BY, FILER)."""
    head = raw.split("</SEC-HEADER>")[0]
    out = []
    for m in re.finditer(r"^(SUBJECT COMPANY|FILED BY|FILER):\s*(.*?)(?=^(?:SUBJECT COMPANY|FILED BY|FILER):|\Z)",
                         head, re.M | re.S):
        nm = re.search(r"COMPANY CONFORMED NAME:\s*(.+)", m.group(2))
        ck = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", m.group(2))
        if nm and ck:
            out.append({"role": m.group(1), "name": nm.group(1).strip(), "cik": int(ck.group(1))})
    return out


def documents(raw: str) -> list[tuple[str, str]]:
    """[(type, text)] of a complete submission's <DOCUMENT> blocks."""
    out = []
    for block in raw.split("<DOCUMENT>")[1:]:
        m = re.search(r"<TYPE>([^\n<]+)", block)
        t = block.split("<TEXT>", 1)[1] if "<TEXT>" in block else block
        out.append(((m.group(1).strip().upper() if m else ""), t.split("</TEXT>", 1)[0]))
    return out


def _cut(text: str, n: int) -> str:
    """The first `n` characters, cut back to a line break (the whole text if shorter)."""
    if len(text) <= n:
        return text
    c = text.rfind("\n", 0, n)
    return text[:c + 1] if c > 0 else text[:n]


def windows(text: str, start_after: int, width: int = WINDOW, cap: int = MAX_WINDOWS,
            strong_only: bool = False) -> list[tuple[int, int, str]]:
    """Up to `cap` (start, end, pattern label) around OUTCOME_RE matches after `start_after`,
    strongest pattern first, merged where they overlap."""
    picked: list[tuple[int, int, str]] = []
    pats = list(zip(("outcome", "outcome-weak"), OUTCOME_RE))[: 1 if strong_only else 2]
    for lab, rx in pats:
        for m in rx.finditer(text, start_after):
            a, b = max(start_after, m.start() - width), min(len(text), m.end() + width)
            if any(a < q and b > p for p, q, _ in picked):
                continue
            picked.append((a, b, lab))
            if len(picked) >= cap:
                return sorted(picked)
    return sorted(picked)


def excerpt_filing(raw: str, form: str, compact: bool = False) -> tuple[str, dict]:
    """One filing's excerpt: its main document's head, its press-release exhibits' heads (8-K, 425,
    DEFA14A), then the outcome windows; returns (text, stats). `compact`: the lead (COMPACT_HEAD)
    and at most COMPACT_MAX_WINDOWS windows of strong outcome language only."""
    docs = documents(raw)
    main = [t for ty, t in docs if ty == form.upper()] or [docs[0][1] if docs else ""]
    body = render(main[0])
    head_n = COMPACT_HEAD if compact else HEAD_CHARS.get(form, HEAD_DEFAULT)
    ex_n = COMPACT_HEAD if compact else EXHIBIT_HEAD
    parts = [f"--- start of the document (first {min(head_n, len(body)):,} of {len(body):,} characters) ---\n",
             _cut(body, head_n)]
    shown = len(_cut(body, head_n))
    ex_texts = []
    if form in ("8-K", "425", "DEFA14A"):
        for ty, t in docs:
            if ty.startswith("EX-99"):
                r = render(t)
                ex_texts.append(r)
                parts += [f"--- exhibit {ty} (first {min(ex_n, len(r)):,} of {len(r):,} characters) ---\n",
                          _cut(r, ex_n)]
    wins = (windows(body, shown, COMPACT_WINDOW, COMPACT_MAX_WINDOWS, strong_only=True) if compact
            else windows(body, shown))
    for a, b, lab in wins:
        # cut to whole words so a window never starts or ends inside one
        a2 = body.rfind(" ", 0, a) + 1 if a > shown else a
        b2 = body.find(" ", b) if body.find(" ", b) > 0 else b
        parts += [f"--- excerpt at characters {a2:,}-{b2:,} of the document ({lab} language) ---\n", body[a2:b2], "\n"]
    return "".join(parts), {"doc_chars": len(body), "exhibit_chars": sum(len(x) for x in ex_texts),
                            "strong": bool(OUTCOME_RE[0].search(body) or any(OUTCOME_RE[0].search(x) for x in ex_texts)),
                            "body_sha": hashlib.sha256(body.encode()).hexdigest()}


# ============================================================ the pack

def episode_filings(client, cik: int, first_date) -> pd.DataFrame:
    """The episode's census filings from EDGAR's filing list (cached by `fetch-edgar`)."""
    from scripts.data import fetch_edgar_events as fe
    sb = fe.submissions(client, int(cik), max_age_s=None)
    f0 = pd.Timestamp(first_date)
    sb = sb[sb["form"].isin(e1.CENSUS_FORMS) & (sb["filingDate"] >= f0 - pd.Timedelta(days=e1.CENSUS_PRE_DAYS))
            & (sb["filingDate"] <= f0 + pd.Timedelta(days=e1.FAIL_WINDOW_DAYS))]
    return sb.sort_values(["filingDate", "accessionNumber"]).reset_index(drop=True)


def episode_text(client, ep: pd.Series) -> tuple[str, list[dict]]:
    """The episode's reading text and its filing list, with what each filing shows.

    Every filing gets at least a COMPACT excerpt (its lead and strong outcome language), so no
    filing in the window is unseen; a filing whose main text is identical to an earlier one's (the
    same press release filed again) points to it instead. The budget is EPISODE_CHARS, raised for
    an episode whose compact excerpts alone exceed it (up to EPISODE_MAX). What is left upgrades
    filings to their FULL excerpt in priority order: the episode's first filing, filings with strong
    outcome language, RW / 8-K / DEFA14A, then the rest by date."""
    from scripts.data.edgar_client import filing_txt_url
    fl = episode_filings(client, int(ep["episode_cik"]), ep["first_date"])
    first = ep["episode_accession"]
    recs = []
    for seq, r in enumerate(fl.itertuples(), 1):
        rec = {"seq": seq, "date": str(r.filingDate.date()), "form": r.form, "accession": r.accessionNumber}
        try:
            raw = client.get_text(filing_txt_url(int(ep["episode_cik"]), r.accessionNumber))
        except Exception as ex:
            recs.append({**rec, "included": False, "why": f"not cached ({type(ex).__name__})"})
            continue
        full, st = excerpt_filing(raw, r.form)
        comp, _ = excerpt_filing(raw, r.form, compact=True)
        parties = "; ".join(f"{p['role']} {p['name']} (CIK {p['cik']})" for p in sgml_parties(raw))
        line = (f"\n===== FILING seq={seq} | form {r.form} | filed {r.filingDate.date()} | accession "
                f"{r.accessionNumber} | {parties} =====\n")
        recs.append({**rec, "included": True, "why": None, "parties": parties, "_line": line, "_full": full,
                     "_comp": comp, "_strong": st["strong"], "_sha": st["body_sha"]})
    seen: dict[str, int] = {}
    for x in recs:
        if x["included"]:
            if x["_sha"] in seen and x["accession"] != first:
                x.update(included=False, why=f"identical text to seq={seen[x['_sha']]}")
            else:
                seen.setdefault(x["_sha"], x["seq"])
    live = [x for x in recs if x["included"]]
    compact_total = sum(len(x["_line"]) + len(x["_comp"]) for x in live)
    budget = min(max(EPISODE_CHARS, compact_total), EPISODE_MAX)
    pri = sorted(live, key=lambda x: (0 if x["accession"] == first else 1 if x["_strong"] else
                                      2 if x["form"] in FIRST_PRIORITY else 3, x["date"]))
    used = 0
    for x in pri:                                    # compact for all, in priority order, while it fits
        n = len(x["_line"]) + len(x["_comp"])
        if used + n > EPISODE_MAX:
            x.update(included=False, why="omitted: even compact excerpts exceed the episode's maximum")
            continue
        x["show"], x["mode"] = x["_comp"], "compact"
        used += n
    for x in pri:                                    # then upgrade to the full excerpt while the budget allows
        if not x["included"]:
            continue
        extra = len(x["_full"]) - len(x["_comp"])
        if used + extra <= budget:
            x["show"], x["mode"] = x["_full"], "full"
            used += extra
    head = [f"EPISODE cik={int(ep['episode_cik'])} first filing {ep['first_date']} ({ep['first_form']}, "
            f"{first}); EDGAR's last name for this CIK: {ep['company_last']}\n"]
    if first not in {x["accession"] for x in recs}:
        head.append(f"NOTE: the episode's first filing ({ep['first_form']}, {first}) is not among the fetched "
                    "forms, so it is not in this excerpt.\n")
    head.append("FILINGS IN THE WINDOW (seq | filed | form | accession | shown):\n")
    for x in recs:
        how = (f"{x['mode']} excerpt" if x["included"] else x["why"])
        head.append(f"  {x['seq']:>3} | {x['date']} | {x['form']} | {x['accession']} | {how}\n")
    body = "".join(x["_line"] + x["show"] for x in recs if x["included"])
    listed = [{k: v for k, v in x.items() if not k.startswith("_") and k not in ("show",)} for x in recs]
    return wrap_long_lines("".join(head) + body), listed


def split_parts(text: str, max_chars: int = PART_CHARS) -> list[str]:
    parts, cur, n = [], [], 0
    for ln in text.split("\n"):
        if cur and n + len(ln) + 1 > max_chars:
            parts.append("\n".join(cur) + "\n")
            cur, n = [], 0
        cur.append(ln)
        n += len(ln) + 1
    if cur:
        parts.append("\n".join(cur) + "\n")
    return parts


def plan_batches(sizes: dict[str, int], order: list[str]) -> list[list[str]]:
    """First-fit decreasing on estimated tokens, capped by BATCH_TOKENS and BATCH_MAX_EPISODES; deterministic."""
    items = sorted(order, key=lambda a: (-sizes[a], order.index(a)))
    bins: list[list[str]] = []
    load: list[float] = []
    for a in items:
        t = sizes[a] / CHARS_PER_TOKEN
        if t > BATCH_TOKENS:
            raise ValueError(f"{a}: {t:.0f} estimated tokens exceeds one batch")
        for i, b in enumerate(bins):
            if load[i] + t <= BATCH_TOKENS and len(b) < BATCH_MAX_EPISODES:
                b.append(a)
                load[i] += t
                break
        else:
            bins.append([a])
            load.append(t)
    return [sorted(b, key=order.index) for b in bins]


def ep_id(cik, acc) -> str:
    return f"{int(cik)}_{acc}"


INSTRUCTIONS = """\
# E1 failed-deal census: reader instructions (2026-10-20)

You read EDGAR filings about one proposed fund merger at a time ("an episode") and record what
they say happened. Your readings decide which proposed mergers between listed closed-end funds
FAILED, which a backtest then includes. A wrong value is worse than a null: **write null whenever
the text in front of you does not state the answer.**

## What you are given

* An episode is the merger filings of ONE fund (its EDGAR CIK), from 30 days before its first
  merger filing to 730 days after. Its text (split into parts `<cik>_<accession>.partNN.txt`)
  starts with a list of every filing in that window (form, date, accession) and how each is
  shown below:
  - a **full excerpt**: the start of the main document, the start of any press-release exhibit
    (8-K, 425, DEFA14A), and up to three passages around outcome language;
  - a **compact excerpt**: the document's first lines and up to two passages around strong
    outcome language only;
  - **identical text to seq=K**: the same document filed again, shown once.

  Each filing appears as
  `===== FILING seq=N | form ... | filed YYYY-MM-DD | accession ... | <parties with CIKs> =====`.
  **Text outside an excerpt is not in front of you: do not assume what it says.** A late filing
  in the list may carry the outcome, so look at every filing's excerpt before deciding.
* The parties line comes from EDGAR's header: SUBJECT COMPANY is the fund the filing is about;
  FILED BY or FILER is who filed it. Use these CIKs.

## What to record for each episode

Write `<cik>_<accession>.json` (the episode's id, as your batch file gives it):

```json
{
  "episode_cik": 3906,
  "episode_accession": "0001104659-09-060229",
  "episode_role": "target",
  "deals": [
    {
      "target":   {"name": "...", "cik": 1234, "ticker": "ABC"},
      "acquirer": {"name": "...", "cik": 5678, "ticker": "XYZ"},
      "both_listed": true,
      "listed_quote": {"accession": "...", "quote": "..."},
      "outcome": "terminated",
      "announcement": {"accession": "...", "date": "YYYY-MM-DD", "quote": "..."},
      "outcome_evidence": {"accession": "...", "date": "YYYY-MM-DD", "quote": "..."},
      "notes": ""
    }
  ],
  "problems": ""
}
```

Field by field:

* `episode_role`: what this episode's fund (`episode_cik`) is in the merger: `"target"` (it would
  be absorbed: its shareholders would receive the other fund's shares), `"acquirer"` (the
  surviving fund that issues shares), or `"other"`; null if the text does not say.
* `deals`: one entry per target-acquirer pair the filings propose. A filing that merges three
  funds into one acquirer is three deals. Use an empty list only if no merger of this fund is
  described at all, and then say so in `problems`.
* `target` / `acquirer`: the name as written, the CIK from a FILING header line (null if neither
  party's CIK appears), and the exchange ticker only as printed (for example "(NYSE: ABC)" gives
  "ABC"); null when not printed.
* `both_listed`: true only if the text shows BOTH funds are closed-end funds or business
  development companies whose shares trade on a stock exchange (for example a ticker with
  "NYSE" or "NYSE American" or "Nasdaq" for each, or "listed on the New York Stock Exchange").
  false if either is an open-end fund (mutual fund), an ETF, a non-traded or unlisted fund, an
  interval fund, or an operating company. null if the text does not settle it. Give the quote
  that settles it in `listed_quote` (null when null).
* `outcome`, exactly one of:
  - `"completed"`: the text states the merger was completed (closed, consummated, became effective);
  - `"completed_other_structure"`: a merger of these funds was completed, but in a different form
    from the one first proposed (a different acquirer or survivor, or cash instead of shares);
  - `"terminated"`: the funds or their boards terminated the agreement, or abandoned or ended the proposal;
  - `"vote_failed"`: the shareholder vote did not approve it, or could not reach a quorum, and it was not completed;
  - `"withdrawn"`: the registration or proxy was withdrawn (form RW, or text saying so) and the merger was not completed;
  - `"superseded"`: the proposal was replaced by a different merger proposal for the same fund;
  - `"not_a_listed_pair"`: `both_listed` is false;
  - `null`: the excerpts do not say how it ended. **This is the right answer whenever the
    outcome is not stated in front of you**; do not infer completion from silence.
* `announcement`: the earliest filing in the excerpt that publicly announces this proposed
  merger. Give its accession and filed date exactly as the FILING line gives them, and a quote
  of one or two sentences that names the merger. null if none of the excerpted filings
  announces it.
* `outcome_evidence`: the filing that first states the outcome above (for a failure, the filing
  that makes the failure public). Give its accession and filed date from the FILING line, and the
  sentence(s) stating it. null when `outcome` is null.
* `notes`: anything a second reader needs (for example "vote adjourned three times, then the
  merger was terminated").

## Quotes

Copy every quote character for character from the part files. Line breaks may be written as
single spaces, and a quote may run across two parts (join them with one space). Never
paraphrase, never fix typos, and never quote text that is not in the parts. Each quote is
checked against the filing. Quote only the filings' own text: never the `===== FILING` lines,
the filing list or the `---` markers, which this pack writes (the CIKs and dates in them are for
your fields, not for quotes).

## How to work

* Read every part file of an episode in full, in order, with the Read tool, before you write its
  JSON. Do not use Grep, Glob or any search, and do not read only part of a file.
* Use no outside knowledge of these funds, sponsors or deals. Only the text counts.
* Open only this file, your batch file and the part files your batch lists. Write only into
  the output directory your brief names. No network, no web, no `sudo`, no `ssh`. Never open
  `config/.env`, any key or credential file, or anything under the repository. Do not start
  other agents.
* The only shell command you may run is the parse check:
  `python3 -c "import json,sys; json.load(open(sys.argv[1]))" <file>`.
* After your last episode, write `_batch_<NN>.json` in the output directory:
  `{"batch": "<NN>", "model_id": "<your exact model ID>", "episodes": ["<cik>_<accession>", ...],
  "parts_read": <number>, "problems": "<anything that troubled you, or empty>"}`.
"""

BRIEF = """\
You are a reader for QUANTT's E1 failed-merger census (DG-E1-3, 2026-10-20). Do exactly this and nothing else.

1. Read {ROOT}/input/INSTRUCTIONS.md in full with the Read tool. It binds you.
2. Read {ROOT}/input/batches/batch_{NN}.json. It lists your episodes in order, each with its part files. Your output directory is {ROOT}/out/{MODEL}/.
3. For each episode, in the listed order: read every one of its part files in full, in order, with the Read tool; then write {ROOT}/out/{MODEL}/<episode id>.json in the shape INSTRUCTIONS.md gives (null wherever the text does not state the answer); then run the parse check on it.
4. Write {ROOT}/out/{MODEL}/_batch_{NN}.json as INSTRUCTIONS.md describes, with your exact model ID.

Forbidden: opening any other file or directory (in particular anything under the repository, other batches' outputs, and config/.env or any key file); Grep, Glob or any search; any shell command except the JSON parse check; network or web access; sudo; ssh; starting agents; using outside knowledge of these funds or deals.

Hand back one line: batch {NN}, your model ID, the number of JSON files written, and any problem.
"""


def prepare(root: Path, client=None) -> dict:
    """Write <root>/input/ (parts, batches, instructions, brief, plan) and <root>/out/."""
    client = client or e1.edgar_client(online=False)
    cen = pd.read_csv(e1.CENSUS)
    inp = root / "input"
    parts_dir, batch_dir = inp / "episodes", inp / "batches"
    for d in (parts_dir, batch_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    (root / "out").mkdir(parents=True, exist_ok=True)
    order, sizes, files, listed, hashes = [], {}, {}, {}, {}
    for _, ep in cen.iterrows():
        i = ep_id(ep["episode_cik"], ep["episode_accession"])
        txt, lst = episode_text(client, ep)
        parts = split_parts(txt)
        names = []
        for k, p in enumerate(parts, 1):
            fn = parts_dir / f"{i}.part{k:02d}.txt"
            fn.write_text(p)
            names.append(str(fn))
            hashes[fn.name] = hashlib.sha256(p.encode()).hexdigest()
        order.append(i)
        sizes[i], files[i], listed[i] = len(txt), names, lst
    batches = plan_batches(sizes, order)
    plan = {"made": str(date.today()), "census": str(e1.CENSUS.relative_to(REPO)), "episodes": len(order),
            "episode_chars_cap": EPISODE_CHARS, "batch_tokens_cap_est": BATCH_TOKENS,
            "chars_per_token_assumed": CHARS_PER_TOKEN, "batches": [], "filings": listed}
    for b_i, b in enumerate(batches, 1):
        nn = f"{b_i:02d}"
        rec = {"batch": nn, "episodes": [{"id": i, "parts": files[i], "chars": sizes[i]} for i in b],
               "est_input_tokens": round(sum(sizes[i] for i in b) / CHARS_PER_TOKEN)}
        (batch_dir / f"batch_{nn}.json").write_text(json.dumps(
            {**rec, "output_dir": "<ROOT>/out/<MODEL>/ as your brief names it"}, indent=1))
        plan["batches"].append(rec)
    (inp / "INSTRUCTIONS.md").write_text(INSTRUCTIONS)
    (inp / "BRIEF_TEMPLATE.txt").write_text(BRIEF)
    plan["part_sha256"] = hashes
    (inp / "plan.json").write_text(json.dumps(plan, indent=1, default=str))
    return plan


# ============================================================ collect

def validate(x: dict, eid: str, listed: list[dict], raw_text) -> list[str]:
    """Problems with one reader JSON. `raw_text(accession)` returns the raw cached filing."""
    from scripts.events.conditional_tender_census import quote_in
    p = []
    cik, acc = eid.split("_", 1)
    if str(x.get("episode_cik")) != cik or x.get("episode_accession") != acc:
        p.append("episode id differs from the file name")
    deals = x.get("deals")
    if not isinstance(deals, list):
        return p + ["deals is not a list"]
    if not deals:
        p.append("no deal recorded")
    dates = {f["accession"]: f["date"] for f in listed}
    shown = {f["accession"] for f in listed if f.get("included")}
    for k, d in enumerate(deals):
        o = d.get("outcome")
        if o is not None and o not in READER_OUTCOMES:
            p.append(f"deal {k}: outcome {o!r} is not in the vocabulary")
        if o is None:
            p.append(f"deal {k}: outcome not stated in the excerpts")
        if d.get("both_listed") is False and o not in (None, "not_a_listed_pair"):
            p.append(f"deal {k}: both_listed false but outcome {o!r}")
        for f in ("listed_quote", "announcement", "outcome_evidence"):
            q = d.get(f)
            if not q:
                continue
            a = q.get("accession")
            if a not in shown:
                p.append(f"deal {k}: {f} cites {a}, not an excerpted filing of this episode")
                continue
            if f != "listed_quote" and q.get("date") not in (None, dates.get(a)):
                p.append(f"deal {k}: {f} date {q.get('date')} differs from EDGAR's {dates.get(a)}")
            if not q.get("quote") or not quote_in(raw_text(a), q["quote"]):
                p.append(f"deal {k}: {f} quote not found in {a}")
    return p


def to_rows(x: dict, eid: str, listed: list[dict], read_by: str, read_on: str) -> list[dict]:
    """One readings row per deal (an episode with no deal gives one row with a blank outcome)."""
    cik, acc = eid.split("_", 1)
    dates = {f["accession"]: f["date"] for f in listed}
    rows = []
    for k, d in enumerate(x.get("deals") or [None]):
        d = d or {}
        t, a = d.get("target") or {}, d.get("acquirer") or {}
        o = d.get("outcome") or ""
        bl = {True: "Y", False: "N"}.get(d.get("both_listed"), "")
        ann, ev = d.get("announcement") or {}, d.get("outcome_evidence") or {}
        failed = o in e1.FAILED_OUTCOMES
        me_target = str(t.get("cik")) == cik
        cp = a if me_target else t
        rows.append({
            "episode_cik": cik, "episode_accession": acc, "deal_id": "",
            "role": x.get("episode_role") or "", "counterparty_cik": cp.get("cik") or "",
            "counterparty_name": cp.get("name") or "", "both_listed": bl, "outcome": o,
            "in_trial": "Y" if (failed and bl == "Y") else "N",
            "target_cik": t.get("cik") or "", "acquirer_cik": a.get("cik") or "",
            "target_ticker": t.get("ticker") or "", "acquirer_ticker": a.get("ticker") or "",
            "ann_date": dates.get(ann.get("accession"), "") if ann else "", "ann_accession": ann.get("accession") or "",
            "ann_quote": ann.get("quote") or "",
            "fail_date": dates.get(ev.get("accession"), "") if (failed and ev) else "",
            "fail_accession": (ev.get("accession") or "") if failed else "",
            "fail_quote": (ev.get("quote") or "") if failed else "",
            "outcome_date": dates.get(ev.get("accession"), "") if ev else "",
            "outcome_accession": ev.get("accession") or "", "outcome_quote": ev.get("quote") or "",
            "read_by": read_by, "read_on": read_on, "_k": k})
    return rows


def assign_deal_ids(R: pd.DataFrame) -> pd.Series:
    """target CIK > acquirer CIK; a pair announced twice more than a year apart is two deals (#2, ...);
    a deal with a party's CIK unknown is its own deal (ep<cik>:<k>)."""
    ids = pd.Series("", index=R.index)
    known = (R["target_cik"].astype(str) != "") & (R["acquirer_cik"].astype(str) != "")
    for pair, g in R[known].groupby([R["target_cik"].astype(str), R["acquirer_cik"].astype(str)]):
        base = f"{pair[0]}>{pair[1]}"
        d = pd.to_datetime(g["ann_date"].replace("", None))
        order = d.sort_values(na_position="last").index
        n, last = 1, None
        for ix in order:
            if last is not None and pd.notna(d[ix]) and (d[ix] - last).days > 365:
                n += 1
            if pd.notna(d[ix]):
                last = d[ix]
            ids[ix] = base if n == 1 else f"{base}#{n}"
    for ix in R.index[~known]:
        ids[ix] = f"ep{R.at[ix, 'episode_cik']}:{R.at[ix, '_k']}"
    # Two deals of ONE episode on one CIK pair (the series of one trust share a CIK) stay two deals.
    ep = R["episode_cik"].astype(str) + "|" + R["episode_accession"].astype(str)
    dup = ids.groupby([ep, ids]).cumcount()
    ids[dup > 0] = ids[dup > 0] + "/" + (dup[dup > 0] + 1).astype(str)
    return ids


def collect(root: Path, model: str, partial: bool, client=None) -> dict:
    from scripts.data.edgar_client import filing_txt_url
    client = client or e1.edgar_client(online=False)
    plan = json.loads((root / "input" / "plan.json").read_text())
    src = root / "out" / model
    batch_of = {e["id"]: b["batch"] for b in plan["batches"] for e in b["episodes"]}
    model_ids = {}
    for f in src.glob("_batch_*.json"):
        j = json.loads(f.read_text())
        model_ids[str(j.get("batch"))] = j.get("model_id") or model
    rows, review = [], []
    missing = []
    for eid, listed in plan["filings"].items():
        f = src / f"{eid}.json"
        if not f.exists():
            missing.append(eid)
            review.append({"episode": eid, "problem": "no reading"})
            continue
        try:
            x = json.loads(f.read_text())
        except json.JSONDecodeError as ex:
            review.append({"episode": eid, "problem": f"unparseable JSON ({ex})"})
            continue
        cik = int(eid.split("_", 1)[0])
        probs = validate(x, eid, listed, lambda a: client.get_text(filing_txt_url(cik, a)))
        review += [{"episode": eid, "problem": p} for p in probs]
        bt = batch_of.get(eid)
        rows += to_rows(x, eid, listed, f"{model_ids.get(bt, model)} (batch {bt})", str(date.today()))
    if missing and not partial:
        raise e1.GateError(f"{len(missing)} episode(s) have no reading in {src} (first {missing[:4]}); "
                           "pass --partial to collect what exists")
    R = pd.DataFrame(rows)
    if len(R):
        R["deal_id"] = assign_deal_ids(R)
        R = R.drop(columns="_k")[list(e1.READING_COLUMNS)]
    else:
        R = pd.DataFrame(columns=e1.READING_COLUMNS)
    e1.OUT_DIR.mkdir(parents=True, exist_ok=True)
    R.to_csv(e1.READINGS, index=False)
    pd.DataFrame(review, columns=["episode", "problem"]).to_csv(e1.OUT_DIR / "e1_failed_reading_review.csv", index=False)
    raw = e1.OUT_DIR / "readings_raw" / model
    raw.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.json"):
        shutil.copy2(f, raw / f.name)
    out = {"episodes": len(plan["filings"]), "read": len(plan["filings"]) - len(missing), "rows": int(len(R)),
           "in_trial_rows": int((R["in_trial"] == "Y").sum()) if len(R) else 0,
           "in_trial_deals": int(R.loc[R["in_trial"] == "Y", "deal_id"].nunique()) if len(R) else 0,
           "review_rows": len(review),
           "outcomes": R["outcome"].replace("", "(null)").value_counts().to_dict() if len(R) else {}}
    print(json.dumps(out, indent=1))
    print(f"wrote {e1._rel(e1.READINGS)} and e1_failed_reading_review.csv; now re-run "
          "`python3 scripts/events/e1_merger_pair.py stage0`")
    return out


# ============================================================ triage: which readings can change the trial

TRIAGE_CLASSES = {
    "T1": "in the trial: a failure, both parties listed, failure public by 2024-12-31",
    "T2": "a failure of a listed pair made public after 2024-12-31: in no set (§4.2, §4.3), recorded",
    "I1": "INDIVIDUAL: a failure whose parties' listing neither the reader nor CRSP settles",
    "I2": "INDIVIDUAL: outcome unstated, both parties listed, no CRSP completion within 730 days",
    "I3": "INDIVIDUAL: outcome unstated, listing unsettled, the episode's own fund a listed CEF or BDC-named",
    "C1": "class: CRSP shows the target merged within 730 days of A (the census rule: not a failed deal)",
    "C2": "class: not a listed pair, or completed (by the reader or by CRSP listing)",
    "C3": "class: outcome unstated, listing unsettled, the episode's own fund not a listed CEF",
}


def crsp_listed(nm: pd.DataFrame, ticker: str, when) -> bool | None:
    """§4.3's listing test: a CRSP CEF (share code 14/44) or BDC (11) permno carrying `ticker` on
    `when`, on NYSE, NYSE American or Nasdaq (exchcd 1-3). None if the ticker is blank or matches no
    single permno (unsettled, never guessed)."""
    if not ticker or not when or pd.isna(pd.Timestamp(when)):
        return None
    w = pd.Timestamp(when)
    r = nm[(nm["ticker"] == ticker) & (nm["namedt"] <= w) & (nm["nameendt"] >= w) & nm["shrcd"].isin((11, 14, 44))]
    if r["permno"].nunique() != 1:
        return None
    return bool(r["exchcd"].isin([1, 2, 3]).any())


def crsp_target_merged(nm, dl, ticker: str, when) -> bool | None:
    """True if the target's CRSP permno has a merger delisting (dlstcd 2xx) within 730 days after
    `when`; False if it has none and CRSP covers the window; None if unsettled."""
    if not ticker or not when or pd.isna(pd.Timestamp(when)):
        return None
    w = pd.Timestamp(when)
    r = nm[(nm["ticker"] == ticker) & (nm["namedt"] <= w) & (nm["nameendt"] >= w)]
    if r["permno"].nunique() != 1:
        return None
    d = dl[(dl["permno"] == int(r["permno"].iloc[0])) & (dl["dlstcd"] // 100 == 2)
           & (dl["dlstdt"] >= w) & (dl["dlstdt"] <= w + pd.Timedelta(days=e1.FAIL_WINDOW_DAYS))]
    if len(d):
        return True
    return False if w + pd.Timedelta(days=e1.FAIL_WINDOW_DAYS) <= e1.CRSP_END else None


def triage(R: pd.DataFrame, census: pd.DataFrame, nm: pd.DataFrame, dl: pd.DataFrame, own_listed: dict) -> pd.DataFrame:
    """Each readings row's class (TRIAGE_CLASSES) and whether it can change the trial. Names,
    delisting records and the readers' fields only; no price or return. `own_listed`: episode id ->
    True if the episode's own CIK maps to a CRSP CEF listed on its first filing date, or its EDGAR
    name is BDC-like (`e1_rulings_facts.r10`'s rule)."""
    first = dict(zip(census["episode_cik"].astype(str) + "_" + census["episode_accession"], census["first_date"]))
    out = []
    for r in R.itertuples(index=False):
        eid = f"{r.episode_cik}_{r.episode_accession}"
        when = r.ann_date or first.get(eid)
        lt, la = crsp_listed(nm, r.target_ticker, when), crsp_listed(nm, r.acquirer_ticker, when)
        listed = ("Y" if r.both_listed == "Y" or (lt and la) else
                  "N" if r.both_listed == "N" or lt is False or la is False else "")
        merged = crsp_target_merged(nm, dl, r.target_ticker, when)
        o = r.outcome
        if o in e1.FAILED_OUTCOMES:
            f = pd.Timestamp(r.fail_date or r.outcome_date) if (r.fail_date or r.outcome_date) else pd.NaT
            cls = ("C2" if listed == "N" else "I1" if listed == "" else
                   "T2" if (pd.notna(f) and f > e1.CRSP_END) else "T1")
        elif o in ("not_a_listed_pair", "completed", "completed_other_structure") or listed == "N":
            cls = "C2"
        elif merged:
            cls = "C1"
        elif listed == "Y":
            cls = "I2"
        else:
            cls = "I3" if own_listed.get(eid) else "C3"
        out.append({"crsp_listed_pair": listed, "crsp_target_merged_730d": {True: "Y", False: "N"}.get(merged, ""),
                    "triage": cls})
    T = pd.concat([R.reset_index(drop=True), pd.DataFrame(out)], axis=1)
    T["can_change_trial"] = T["triage"].str[0].isin(["T", "I"]).map({True: "Y", False: "N"})
    return T


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--root", type=Path, required=True)
    c = sub.add_parser("collect")
    c.add_argument("--root", type=Path, required=True)
    c.add_argument("--model", required=True)
    c.add_argument("--partial", action="store_true")
    sub.add_parser("triage")
    a = ap.parse_args(argv)
    if a.cmd == "triage":
        return run_triage()
    if a.cmd == "prepare":
        plan = prepare(a.root)
        print(f"{plan['episodes']} episodes in {len(plan['batches'])} batches under {a.root}/input/")
        return 0
    collect(a.root, a.model, a.partial)
    return 0


def run_triage() -> int:  # pragma: no cover - reads the CRSP cache and the census; its core is tested (triage)
    from scripts.events import e1_rulings_facts as rf
    nm, dl = e1.crsp_tables()
    R = pd.read_csv(e1.READINGS, dtype=str, keep_default_na=False)
    cen = pd.read_csv(e1.CENSUS, dtype={"episode_cik": str})
    own = rf.own_listed(nm)
    T = triage(R, cen, nm, dl, own)
    path = e1.OUT_DIR / "e1_failed_reading_triage.csv"
    T.to_csv(path, index=False)
    by = T.groupby("triage").agg(rows=("deal_id", "size"), deals=("deal_id", "nunique"),
                                 episodes=("episode_cik", lambda v: (v + T.loc[v.index, "episode_accession"]).nunique()))
    print(by.to_string())
    print("in-trial deals (T1):", sorted(T.loc[T["triage"] == "T1", "target_ticker"] + "->" + T.loc[T["triage"] == "T1", "acquirer_ticker"]))
    print(f"wrote {e1._rel(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
