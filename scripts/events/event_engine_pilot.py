"""The free reading pilot: inputs, batches and the collector for Claude Code subagents, and the shared scorer.

    python3 scripts/events/event_engine_pilot.py prepare --root <dir>   # write the inputs, batches and brief under <dir>
    python3 scripts/events/event_engine_pilot.py collect --root <dir>   # <dir>/out/<model>/*.json -> tracked copies + scores
    python3 scripts/events/event_engine_pilot.py collect --root <dir> --partial   # score whatever filings are present, labelled
    python3 scripts/events/event_engine_pilot.py references             # pass A, pass B, rules v1/v2 on the pilot's cells

ZERO TRIALS. No return, no P&L, no signal; no price is read and no holdout is
touched. Team lead, 2026-10-19: the ~$49 API pilot of
`results/events/EVENT_ENGINE_DESIGN_2026-10-15.md` §11 was declined; instead
(a) a rules-only baseline (`event_engine_rules.py`) and (b) this: the same 50
filings read by Claude Code subagents on the subscription (Haiku, Sonnet and
Opus), with NO API key and no API spend. The results note is
`results/events/EVENT_ENGINE_PILOT_2026-10-19.md`.

WHY AN EXCERPT, AND WHICH ONE
-----------------------------
The design's question is a single call per filing on the WHOLE filing. The
filings run to ~659k estimated tokens (mean ~142k, design note §8), which no
subagent turn holds, and a subagent left to search a long filing measures its
searching, not its reading (the prototype's readers searched, design §7.2).
So every model reads the same fixed input in full: the first
`EXCERPT_CHARS` characters of the rendered text, cut back to a line break.
Of the design's candidate inputs (§7.4) this one dominates "cover + keyword
sections": it recovered more gold values (0.91 against 0.84) at a smaller
mean size (~31k against ~41k estimated tokens), and its largest filing is
~45k tokens where the sections mode's largest is ~248k, more than a
subagent's context. What the excerpt cannot answer is stated in the note and
measured here per model: every score is reported on ALL gold values and on
the gold values whose every quote lies inside the excerpt (`recoverable`).

THE GOLD IS NOT INDEPENDENT OF THE READERS
------------------------------------------
The gold (`results/events/event_engine/gold/`) is two blind readings by Claude
Opus 5.5 subagents reconciled by the same session's Opus 5.5, with every
adjudication written in `event_engine_reconcile.py`; a 40-cell spot check was
re-read by the same model (design §7.2). An Opus reader scored against it is
scored partly against itself: a misreading Opus shares counts as right, and a
correct reading that differs from Opus's convention counts as wrong. So the
collector writes every disagreement with the gold (`pilot_disagreements.csv`)
for a reading against the text before any gap between models is called a
difference in reading skill.

THE SCORER
----------
`score_reader` wraps `event_engine_score.score_vs_gold` and `pr_table`
unchanged (the slot-filling convention: a wrong value is an FP and an FN), so
the rules, pass A, pass B and each pilot model are scored by one function.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import textwrap
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.events import event_engine_score as S  # noqa: E402
from scripts.events import event_store as E  # noqa: E402

OUT = REPO / "results" / "events" / "event_engine"
PILOT_DIR = OUT / "pilot"          # tracked copies of the subagents' JSON, one folder per model
MODELS = ("haiku", "sonnet", "opus")

EXCERPT_CHARS = 120_000            # the design's largest prefix window (event_engine_score.WINDOWS)
PART_CHARS = 30_000                # one Read call each, comfortably inside the tool's limits
PART_LINES = 1_200
WRAP_AT = 1_000                    # longer lines are wrapped at a space (the Read tool may cut very long lines)
BATCH_TOKENS = 90_000              # estimated input tokens per subagent, before instructions and output
BATCH_MAX_FILINGS = 10
INSTRUCTIONS = OUT / "extraction_instructions.txt"


# ============================================================ scoring (shared by rules, passes and pilot models)

def gold_spans(g: dict) -> dict[str, list[str]]:
    """field -> the gold value's quotes (first event), for non-null values only."""
    ev = S.first_event(g)
    out = {}
    for n, v in (ev.get("terms") or {}).items():
        if isinstance(v, dict) and v.get("value") not in (None, []):
            out[n] = [x for x in (v.get("spans") or [v.get("span")]) if x]
    return out


def excerpt_of(text: str, chars: int = EXCERPT_CHARS) -> str:
    """The first `chars` characters, cut back to the last line break (the whole text if shorter)."""
    if len(text) <= chars:
        return text
    cut = text.rfind("\n", 0, chars)
    if cut <= 0:
        raise ValueError("no line break inside the excerpt window")
    return text[:cut + 1]


def recoverable_cells(gold: dict, man: pd.DataFrame, texts: dict[str, str], chars: int | None) -> set[tuple[str, str]]:
    """(accession, field) cells a reader of the input could get right: a null gold, a triage field, or a
    non-null gold whose every quote is inside the input (all of the text when `chars` is None)."""
    cells = set()
    for acc in man["accession"]:
        inp = E.normalise(texts[acc] if chars is None else excerpt_of(texts[acc], chars))
        sp = gold_spans(gold[acc])
        kg = S.kind_of(gold[acc])
        names = ["triage.kind", "triage.fund_type", "triage.doc_role"] + [s.name for s in E.FIELDS[kg] if s.scored]
        for n in names:
            if n.startswith("triage.") or n not in sp or all(E.normalise(q) in inp for q in sp[n]):
                cells.add((acc, n))
    return cells


def load_texts(man: pd.DataFrame) -> dict[str, str]:
    """The 50 rendered texts (gitignored cache), each checked against the manifest's sha256.

    The texts are rebuilt by `event_engine_sample.py --offline` or copied from
    another checkout; a text that is not byte-identical to the one the gold
    was read from would move every span check and every excerpt, so it raises.
    """
    out = {}
    for acc, h in zip(man["accession"], man["sha256_text"]):
        p = S.TEXT_DIR / f"{acc}.txt"
        if not p.exists():
            raise FileNotFoundError(f"{p}: the text cache is missing (event_engine_sample.py --offline rebuilds it)")
        t = p.read_text()
        if hashlib.sha256(t.encode()).hexdigest() != h:
            raise ValueError(f"{p}: sha256 differs from sample_manifest.csv; not the text the gold was read from")
        out[acc] = t
    return out


def score_reader(reader_dir: Path, label: str, splits: bool = False, excerpt_chars: int | None = None,
                 accessions: list[str] | None = None, read_whole: bool = False) -> dict:
    """Score one reader's folder of JSON against the gold. Returns {"summary", "by_field", "cells"}.

    `excerpt_chars`: cells are flagged `recoverable` against that prefix and
    every summary is given on all cells and on the recoverable ones.
    `read_whole`: the reader read the whole filing (pass A, pass B, the
    rules), so its quotes are checked against the whole text even when
    `excerpt_chars` restricts the cells; a pilot model's quotes are checked
    against the excerpt it was given, where a quote from beyond the cut can
    only be memory. `splits`: add the rules' dev/test split. `accessions`:
    score only these (a partial pilot), and say so in the summary.
    """
    man = pd.read_csv(S.MANIFEST)
    if accessions is not None:
        man = man[man["accession"].isin(accessions)].reset_index(drop=True)
    gold = S.load_dir(OUT / "gold")
    x = S.load_dir(reader_dir)
    missing = sorted(set(man["accession"]) - set(x))
    if missing:
        raise FileNotFoundError(f"{label}: {len(missing)} filings have no JSON in {reader_dir}: {missing[:4]}...")
    texts = load_texts(man)
    cells = S.score_vs_gold(x, gold, man, label)
    cells["stratum"] = cells["accession"].map(dict(zip(man["accession"], man["stratum"])))
    rec = recoverable_cells(gold, man, texts, excerpt_chars)
    cells["recoverable"] = [(a, f) in rec for a, f in zip(cells["accession"], cells["field"])]
    if splits:
        from scripts.events.event_engine_rules import split
        cells["split"] = cells["accession"].map(dict(zip(split(man)["accession"], split(man)["split"])))
    terms = cells[~cells["field"].str.startswith("triage")]

    def block(c: pd.DataFrame) -> dict:
        t = c[~c["field"].str.startswith("triage")]
        tot = S.pr_table(t.assign(all="all"), ["all"]).drop(columns="all").to_dict("records")[0]
        return {"terms": tot,
                "by_dtype": S.pr_table(t, ["dtype"]).set_index("dtype").to_dict("index"),
                "by_stratum": S.pr_table(t, ["stratum"]).set_index("stratum").to_dict("index"),
                "triage": {f: float(c.loc[c["field"] == f, "tp"].mean()) for f in
                           ("triage.kind", "triage.fund_type", "triage.doc_role")}}

    span_rows = []
    for acc in man["accession"]:
        inp = texts[acc] if (excerpt_chars is None or read_whole) else excerpt_of(texts[acc], excerpt_chars)
        f = S.span_failures(x[acc], inp)
        span_rows.append({"accession": acc, "nonnull": S.n_nonnull(x[acc]), "failures": len(f), "detail": f})
    summary = {"reader": label, "n_filings": len(man), "partial": accessions is not None,
               "input": "whole text" if excerpt_chars is None else f"first {excerpt_chars} characters (to a line break)",
               "all_cells": block(cells),
               "recoverable_cells": block(cells[cells["recoverable"]]),
               "gold_values": int(terms["gold"].notna().sum()),
               "gold_values_recoverable": int((terms["gold"].notna() & terms["recoverable"]).sum()),
               "span_checks": {"values": sum(r["nonnull"] for r in span_rows),
                               "failures": sum(r["failures"] for r in span_rows),
                               "against": ("the whole text" if (excerpt_chars is None or read_whole)
                                           else "the excerpt the reader was given"),
                               "failed": [{"accession": r["accession"], **d} for r in span_rows for d in r["detail"]][:40]}}
    if splits:
        summary["by_split"] = {s: block(cells[cells["split"] == s]) for s in ("dev", "test")}
    by_field = S.pr_table(terms, ["kind", "field", "dtype"])
    by_field.insert(0, "reader", label)
    return {"summary": summary, "by_field": by_field, "cells": cells}


# ============================================================ prepare: inputs, batches, instructions, brief

def est_tokens(chars: int) -> float:
    return chars / S.CHARS_PER_TOKEN        # [S] the design's estimate (event_engine_score docstring)


def wrap_long_lines(text: str, width: int = WRAP_AT) -> str:
    """Break lines longer than `width` at spaces only, so `event_store.normalise` of the result is unchanged."""
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


def split_parts(text: str, max_chars: int = PART_CHARS, max_lines: int = PART_LINES) -> list[str]:
    """Consecutive parts at line breaks, each at most `max_chars` characters and `max_lines` lines."""
    parts, cur, n = [], [], 0
    for ln in text.split("\n"):
        if cur and (n + len(ln) + 1 > max_chars or len(cur) >= max_lines):
            parts.append("\n".join(cur) + "\n")
            cur, n = [], 0
        cur.append(ln)
        n += len(ln) + 1
    if cur:
        parts.append("\n".join(cur) + "\n")
    return parts


def plan_batches(sizes: dict[str, int], order: list[str]) -> list[list[str]]:
    """First-fit decreasing on estimated tokens, capped by BATCH_TOKENS and BATCH_MAX_FILINGS; deterministic."""
    items = sorted(order, key=lambda a: (-sizes[a], order.index(a)))
    bins: list[list[str]] = []
    load: list[float] = []
    for a in items:
        t = est_tokens(sizes[a])
        if t > BATCH_TOKENS:
            raise ValueError(f"{a}: {t:.0f} estimated tokens exceeds one batch ({BATCH_TOKENS})")
        for i, b in enumerate(bins):
            if load[i] + t <= BATCH_TOKENS and len(b) < BATCH_MAX_FILINGS:
                b.append(a)
                load[i] += t
                break
        else:
            bins.append([a])
            load.append(t)
    return [sorted(b, key=order.index) for b in bins]


ADDENDUM = """\
# Pilot reader instructions (2026-10-19)

You are one reader in a blind pilot that measures how well a model reads
EDGAR event filings into a fixed schema. Your extraction is scored against a
reference set you cannot see. This page comes first and overrides the older
instructions below it wherever they differ.

## What you are given, and what changes

* **A fixed excerpt, not the whole filing.** Each filing is the first
  ~120,000 characters of its text (cut at a line break), split into part
  files `<accession>.partNN.txt`. A value the filing states only after the
  cut is not in front of you: write null. Never complete a value from memory
  or from knowledge of the fund, the deal or how it ended.
* **Read, do not search.** Read every part file of a filing in full, in order,
  with the Read tool, before writing its JSON. Do not use Grep, Glob or any
  search; do not read part of a file. (This replaces rule 8 below.)
* **Quotes.** Every `span` is copied from the part files, character for
  character (line breaks may be written as single spaces). A quote may run
  across the end of one part into the next: join it with a single space.
  `doc_seq` is the `seq=` of the last `===== DOCUMENT` line at or before the
  quote, which may be in an earlier part.
* **Files.** Open only this file, your batch file, and the part files your
  batch file lists. Write only into the output directory your batch file
  names. (This replaces rule 9 below.) No network, no web, no `sudo`, no
  `ssh`; never open `config/.env`, any key or credential file, or anything
  under the repository's `results/` folder. Do not start other agents.
* **The only shell command you may run** is the parse check of rule 10:
  `python3 -c "import json,sys; json.load(open(sys.argv[1]))" <file>`.
* After the last filing, write `_batch_<NN>.json` in the output directory:
  `{"batch": "<NN>", "model_id": "<your exact model ID, as your system prompt
  gives it>", "filings": ["<accession>", ...], "parts_read": <number of part
  files you read>, "problems": "<anything that stopped or troubled you, or
  empty>"}`.

The older instructions, unchanged from the 2026-10-15 prototype (pass A and
pass B read with exactly these), follow.

---

"""

BRIEF = """\
You are a reader in the QUANTT event-engine pilot (2026-10-19). Do exactly this and nothing else.

1. Read {ROOT}/input/PILOT_INSTRUCTIONS.md in full with the Read tool. It binds you.
2. Read {ROOT}/input/batches/batch_{NN}.json. It lists your filings in order, each with its part files, and gives your output directory {ROOT}/out/{MODEL}/.
3. For each filing, in the listed order: read every one of its part files in full, in order, with the Read tool; then write {ROOT}/out/{MODEL}/<accession>.json in the shape PILOT_INSTRUCTIONS.md gives (every field of the kind present, null where the excerpt does not state it); then run the parse check on it.
4. Write {ROOT}/out/{MODEL}/_batch_{NN}.json as PILOT_INSTRUCTIONS.md describes, with your exact model ID.

Forbidden: opening any other file or directory (in particular anything under the repository, its results/ folder, other batches' outputs, and config/.env or any key file); Grep, Glob or any search; any shell command except the JSON parse check; network or web access; sudo; ssh; starting agents; using outside knowledge of these funds or deals.

Hand back one line: batch {NN}, your model ID, the number of JSON files written, and any problem.
"""


def prepare(root: Path) -> dict:
    """Write <root>/input/ (parts, batches, instructions, brief) and <root>/out/<model>/; return the plan."""
    man = pd.read_csv(S.MANIFEST)
    inp, outd = root / "input", root / "out"
    parts_dir, batch_dir = inp / "filings", inp / "batches"
    for d in (parts_dir, batch_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    for mdl in MODELS:
        (outd / mdl).mkdir(parents=True, exist_ok=True)
    order = list(man["accession"])
    files: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}
    hashes = {}
    texts = load_texts(man)
    for acc in order:
        ex = excerpt_of(texts[acc])
        wrapped = wrap_long_lines(ex)
        if E.normalise(wrapped) != E.normalise(ex):
            raise AssertionError(f"{acc}: wrapping changed the normalised text")
        parts = split_parts(wrapped)
        if E.normalise("".join(parts)) != E.normalise(ex):
            raise AssertionError(f"{acc}: the parts do not reassemble the excerpt")
        names = []
        for i, p in enumerate(parts, 1):
            fn = parts_dir / f"{acc}.part{i:02d}.txt"
            fn.write_text(p)
            names.append(str(fn))
            hashes[fn.name] = hashlib.sha256(p.encode()).hexdigest()
        files[acc] = names
        sizes[acc] = len(ex)
    batches = plan_batches(sizes, order)
    plan = {"excerpt_chars": EXCERPT_CHARS, "batch_tokens_cap_est": BATCH_TOKENS,
            "chars_per_token_assumed": S.CHARS_PER_TOKEN, "models": list(MODELS), "batches": []}
    for i, b in enumerate(batches, 1):
        nn = f"{i:02d}"
        rec = {"batch": nn, "output_dir_template": str(outd / "{MODEL}"),
               "filings": [{"accession": a, "parts": files[a], "excerpt_chars": sizes[a]} for a in b],
               "est_input_tokens": round(sum(est_tokens(sizes[a]) for a in b))}
        (batch_dir / f"batch_{nn}.json").write_text(json.dumps(
            {**rec, "output_dir": "<ROOT>/out/<MODEL>/ as your brief names it"}, indent=1))
        plan["batches"].append(rec)
    (inp / "PILOT_INSTRUCTIONS.md").write_text(ADDENDUM + INSTRUCTIONS.read_text())
    (inp / "BRIEF_TEMPLATE.txt").write_text(BRIEF)
    plan["part_sha256"] = hashes
    plan["instructions_sha256"] = hashlib.sha256((inp / "PILOT_INSTRUCTIONS.md").read_bytes()).hexdigest()
    (inp / "plan.json").write_text(json.dumps(plan, indent=1))
    return plan


# ============================================================ collect

def validate_reader_json(x: dict, acc: str) -> list[str]:
    """Shape problems that would make a score meaningless (the scorer raises on some; list them all first)."""
    p = []
    if x.get("accession") != acc:
        p.append(f"accession {x.get('accession')!r} != file name")
    tri = x.get("triage") or {}
    if tri.get("kind") not in E.KINDS:
        p.append(f"triage.kind {tri.get('kind')!r} not in the schema")
    k = tri.get("kind")
    evs = x.get("events")
    if not isinstance(evs, list):
        p.append("events is not a list")
    elif k in E.KINDS and k != "none":
        if not evs or evs[0].get("kind") != k:
            p.append("first event's kind differs from triage.kind")
        else:
            names = {s.name for s in E.FIELDS[k]}
            extra = set(evs[0].get("terms") or {}) - names
            if extra:
                p.append(f"fields outside the {k} schema: {sorted(extra)}")
    return p


def collect(root: Path, partial: bool) -> dict:
    man = pd.read_csv(S.MANIFEST)
    plan = json.loads((root / "input" / "plan.json").read_text())
    results, fields, disagreements = {}, [], []
    for mdl in MODELS:
        src = root / "out" / mdl
        got = sorted(p for p in src.glob("*.json") if not p.name.startswith("_")) if src.exists() else []
        if not got:
            continue
        accs = [p.stem for p in got]
        unknown = sorted(set(accs) - set(man["accession"]))
        if unknown:
            raise ValueError(f"{mdl}: files for filings outside the sample: {unknown}")
        problems = {}
        for p in got:
            x = json.loads(p.read_text())
            pr = validate_reader_json(x, p.stem)
            if pr:
                problems[p.stem] = pr
        if problems:
            raise ValueError(f"{mdl}: malformed reader JSON (fix by re-running that batch, never by hand): "
                             f"{json.dumps(problems)[:1500]}")
        missing = sorted(set(man["accession"]) - set(accs))
        if missing and not partial:
            raise FileNotFoundError(f"{mdl}: {len(missing)} of {len(man)} filings missing (e.g. {missing[:3]}); "
                                    "re-run their batches, or pass --partial to score what is there, labelled")
        reports = [json.loads(p.read_text()) for p in sorted(src.glob("_batch_*.json"))]
        dst = PILOT_DIR / mdl
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        for p in got + sorted(src.glob("_batch_*.json")):
            shutil.copy2(p, dst / p.name)
        r = score_reader(dst, mdl, excerpt_chars=plan["excerpt_chars"], accessions=accs if missing else None)
        r["summary"]["batch_reports"] = [{k: v for k, v in b.items() if k in ("batch", "model_id", "parts_read", "problems")}
                                         for b in reports]
        r["summary"]["model_ids_reported"] = sorted({str(b.get("model_id")) for b in reports})
        results[mdl] = r["summary"]
        fields.append(r["by_field"])
        c = r["cells"]
        d = c[~(c["tp"] | c["both_null"])]
        disagreements.append(d.assign(reader=mdl))
    if not results:
        raise FileNotFoundError(f"no reader output under {root / 'out'}")
    refs = references(plan["excerpt_chars"])
    out = {"pilot": results, "references_scored_on_the_same_cells": refs,
           "note": ("references read the WHOLE filing; their 'recoverable_cells' block restricts them to the cells "
                    "a reader of the excerpt could get right, so it is the like-for-like comparison")}
    (OUT / "pilot_scores.json").write_text(json.dumps(out, indent=1, default=str))
    pd.concat(fields).to_csv(OUT / "pilot_field_scores.csv", index=False)
    pd.concat(disagreements).to_csv(OUT / "pilot_disagreements.csv", index=False)
    return out


REFERENCE_READERS = (("pass_a", OUT / "pass_a"), ("pass_b", OUT / "pass_b"),
                     ("rules_v1", OUT / "rules_v1"), ("rules_v2", OUT / "rules"))


def references(excerpt_chars: int = EXCERPT_CHARS) -> dict:
    """The prototype's passes (whole filing, agentic Opus 5.5) and the rules (whole text), on the pilot's cells.

    They read the whole filing, so their quotes are checked against the whole
    text; their `recoverable_cells` block restricts them to the cells a reader
    of the excerpt could get right, which is the like-for-like comparison
    with a pilot model.
    """
    return {label: score_reader(d, label, excerpt_chars=excerpt_chars, read_whole=True)["summary"]
            for label, d in REFERENCE_READERS if d.exists()}


def table(out: dict) -> str:
    """The headline table, one row per reader, all cells and recoverable cells."""
    rows = []
    for label, s in list(out["pilot"].items()) + list(out["references_scored_on_the_same_cells"].items()):
        a, r = s["all_cells"], s["recoverable_cells"]
        if s["partial"]:
            label = f"{label} (PARTIAL: {s['n_filings']} of 50 filings)"
        rows.append(f"| {label} | {a['triage']['triage.kind']:.2f} | {a['terms']['cell_accuracy']:.3f} | "
                    f"{a['terms']['precision']:.3f} / {a['terms']['recall']:.3f} | "
                    f"{r['terms']['precision']:.3f} / {r['terms']['recall']:.3f} | "
                    f"{s['span_checks']['failures']} of {s['span_checks']['values']} |")
    head = ("| reader | kind | cell accuracy (all) | P / R (all gold values) | P / R (recoverable) | span failures |\n"
            "|---|---|---|---|---|---|")
    return head + "\n" + "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("prepare", "collect", "references"))
    ap.add_argument("--root", type=Path, help="pilot folder (inputs and outputs; out of tree)")
    ap.add_argument("--partial", action="store_true", help="score the filings present; the summary says so")
    a = ap.parse_args(argv)
    if a.cmd == "references":    # the reference rows alone, before any pilot output exists
        out = {"pilot": {}, "references_scored_on_the_same_cells": references()}
        (OUT / "pilot_references.json").write_text(json.dumps(out["references_scored_on_the_same_cells"],
                                                               indent=1, default=str))
        print(table(out))
        return 0
    if a.root is None:
        raise ValueError(f"{a.cmd} needs --root (the out-of-tree pilot folder)")
    root = a.root.resolve()
    if REPO in root.parents or root == REPO:
        raise ValueError(f"--root {root} is inside the repository; the inputs are large and the outputs are "
                         "copied in by `collect`: keep the pilot folder out of tree")
    if a.cmd == "prepare":
        plan = prepare(root)
        n = len(plan["batches"])
        print(f"{n} batches per model x {len(MODELS)} models = {n * len(MODELS)} subagents")
        for b in plan["batches"]:
            print(b["batch"], len(b["filings"]), "filings", b["est_input_tokens"], "est. tokens")
        print(textwrap.indent(BRIEF, "    "))
        return 0
    out = collect(root, a.partial)
    print(table(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
