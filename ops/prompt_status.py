#!/usr/bin/env python3
"""Derive each work order's status from the repo, and check the index against it.

    python3 -m ops.prompt_status                 # the report
    python3 -m ops.prompt_status --check         # exit 1 on DRIFT; what the test calls
    python3 -m ops.prompt_status --json
    python3 -m ops.prompt_status --strict        # promote the advisory NOTEs to DRIFT

WHY THIS FILE EXISTS
--------------------
Until 2026-09-10 **nothing in this repo read `docs/prompts/` programmatically.**
Status lived in three hand-typed places that could disagree -- the banner inside
a prompt, the Status column in `docs/prompts/README.md`, and the trial counters
in `docs/RESEARCH_STATE.md` -- and the index says of itself "this table copies
those, so it can drift". Within twelve hours of being written it had drifted in
four places, and every one was invisible until a person opened four files:

1. `W2`, `W5` and `W8` were filed `queued`, whose definition in the index is
   "written, never run. No commit references it." All three had landed work --
   W2's per-book halt scoping (`43ec054`, `26a5336`, with 11 tests), W5's dust
   orders (`9636502`), and W8's Part A method being measured dead. The index
   read *never started*, which is the drift direction that costs a session:
   somebody does the work twice.
2. Four prompts carried a "fix this first" warning about analysis scripts
   baselining against the retired `band(T, 0.064)`. The defect was fixed on
   2026-09-10 (`0b74658`, `9409762`, `666fab9`). The warnings outlived the fix.
3. Four prompts point at `results/vrp/`, `scripts/vrp/` and
   `src/deploy/lib/black76.py`, which W0 archived. A prompt that tells you to
   read a file that is not there costs a search before it costs a correction.
4. `NEXT_2026-09-11.md` named two release tags when three existed, and told the
   reader to promote the one the third tag's own annotation supersedes.

WHAT THIS TOOL WILL AND WILL NOT DO
-----------------------------------
It does **not** decide a status. It cannot know that W8 Part A's method is dead,
or that W14 is blocked on W2 -- those are human claims and they are the part
that carries information. What it checks is that a claim is *backed*: that the
index token equals the prompt's own `**Status:**` token, that every commit sha
named resolves and is an ancestor of HEAD, and that every `results/` note cited
exists. The judgement stays with a person; the evidence becomes falsifiable.

This mirrors `ops/weekly_report.py` -- "the report never grades anything itself
... so it cannot disagree" -- and the severity split is deliberately NOT
`ops/doctor.py`'s. Doctor's FAIL means "unattended operation is broken right
now"; a wrong Status cell is not that. Hence a vocabulary of two:

    DRIFT   the index asserts something the repo contradicts.   exit 1
    NOTE    a judgement a human owns. --strict promotes these to DRIFT.
    INFO    context only. NEVER promoted, by design -- the trial counters are
            reported here and H14 forbids any verdict keying on them.

THE BANNER EXTRACTOR, AND WHY IT IS NOT A GREP
----------------------------------------------
`grep -n 'EXECUTED'` -- which `W0c:188` explicitly recommends -- gets this
wrong. `W0c:185` *quotes* W0b's banner as an instruction to apply elsewhere, so
a grep marks the one in-progress prompt executed. The banner is only ever the
leading blockquote: the contiguous run of `>` lines after the `# ` title. Any
`EXECUTED` below that is prose about a banner, not a banner.

H14 (no decision rule may key on a number written in a document) binds this
file. The CEF and GAMMA counters are read and printed as context; **no check
branches on them.** `test_prompt_status.py` enforces that mechanically by
monkeypatching them to nonsense and asserting the findings do not move.

NO SILENT FALLBACKS: a missing index, an unparseable row, a prompt with no
`**Status:**` line and an unresolvable sha each raise `PromptStatusError`
naming what was missing and where it looked. Nothing here degrades to a guess.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS = REPO_ROOT / "docs" / "prompts"
INDEX = PROMPTS / "README.md"
RESEARCH_STATE = REPO_ROOT / "docs" / "RESEARCH_STATE.md"

DRIFT, NOTE, INFO = "DRIFT", "NOTE", "INFO"

# Prompts that are not prompts. They carry no `**Status:**` line by design and
# are never "run": two standing briefs and one dated work order.
NON_PROMPTS = {"00_BRIEF.md", "README.md", "G0_BRIEF.md"}
DATED_ARTIFACT = re.compile(r"^NEXT_\d{4}-\d{2}-\d{2}\.md$")

# Paths a prompt may name that legitimately do not exist in THIS tree.
# Halts are written in prod and are untracked (CLAUDE.md: "`ls ops/HALT*.md`
# shows everything active -- but only in the tree it is run in"), and live
# ledgers are session output. Each entry is a runtime artefact, not a pointer
# into the repo, so its absence here says nothing about the prompt.
RUNTIME_ARTEFACTS = (
    re.compile(r"^ops/HALT.*\.md$"),
    re.compile(r"^ops/halts/"),
    re.compile(r"^ops/books/\w+_live/"),
    re.compile(r"^ops/reports/"),
    re.compile(r"^ops/heartbeat\.json$"),
)

SHA = re.compile(r"`([0-9a-f]{7,40})`")
PATHLIKE = re.compile(
    r"`((?:ops|src|scripts|results|data|docs|config|dashboard)/[^`\s]*)`")


class PromptStatusError(RuntimeError):
    """Something this tool needs is missing. It names what, and where it looked."""


@dataclass(frozen=True)
class IndexRow:
    target: str
    status: str
    evidence: str
    line_no: int


@dataclass
class Report:
    findings: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, level: str, where: str, msg: str) -> None:
        # Deduped: a sha named in both the banner and the index row is one
        # fault, not two, and a doubled line reads like a doubled problem.
        if (level, where, msg) not in self.findings:
            self.findings.append((level, where, msg))

    def drifted(self) -> list[tuple[str, str, str]]:
        return [f for f in self.findings if f[0] == DRIFT]

    def render(self, strict: bool = False) -> str:
        out = []
        for level, where, msg in self.findings:
            out.append(f"  {level:<5}  {where:<40}  {msg}")
        n_d = len(self.drifted())
        n_n = len([f for f in self.findings if f[0] == NOTE])
        n_i = len([f for f in self.findings if f[0] == INFO])
        out.append("")
        out.append(f"  {n_d} DRIFT, {n_n} NOTE, {n_i} INFO"
                   + ("  (--strict: NOTEs count as DRIFT)" if strict else ""))
        return "\n".join(out)


# ---------------------------------------------------------------- extraction

def leading_banner(text: str) -> str:
    """The leading blockquote only -- see the module docstring on why not grep."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith("# ")):
        i += 1
    block = []
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        block.append(lines[i])
        i += 1
    return "\n".join(block)


def declared_status(text: str, vocab: set[str], where: str) -> tuple[str, str]:
    """Parse `**Status:** <token> — <evidence>` from a prompt's preamble."""
    m = re.search(r"^\*\*Status:\*\*\s*(.+)$", text, re.M)
    if not m:
        raise PromptStatusError(
            f"{where}: no `**Status:**` line. Every prompt declares its own "
            f"status in its preamble; the index is checked against it.")
    return split_status(m.group(1).strip(), vocab, where)


def split_status(cell: str, vocab: set[str], where: str) -> tuple[str, str]:
    """Longest-match a vocabulary token off the front of a status cell."""
    bare = cell.replace("**", "").strip()
    for token in sorted(vocab, key=len, reverse=True):
        if bare == token or bare.startswith(token + " ") or bare.startswith(token + "—"):
            return token, bare[len(token):].lstrip(" —-").strip()
    raise PromptStatusError(
        f"{where}: status {bare[:40]!r} is not in the index's own vocabulary "
        f"{sorted(vocab)}. Add it to the vocabulary table or fix the cell.")


def read_index(path: Path = INDEX) -> tuple[list[IndexRow], set[str]]:
    """The vocabulary table and the index table, both read FROM THE FILE.

    The vocabulary is never hard-coded here. `test_promote_gate.py` records why:
    a hand-copied list in the checker lets the guarded thing regress while the
    checker stays green.
    """
    if not path.exists():
        raise PromptStatusError(f"no index at {path}")
    lines = path.read_text().splitlines()

    vocab: set[str] = set()
    in_vocab = False
    for ln in lines:
        if ln.startswith("## Status vocabulary"):
            in_vocab = True
            continue
        if in_vocab:
            if ln.startswith("## "):
                break
            m = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|", ln)
            if m:
                vocab.add(m.group(1).strip())
    if not vocab:
        raise PromptStatusError(
            f"{path}: could not parse a Status vocabulary table. Expected a "
            f"'## Status vocabulary' section with `| **token** | meaning |` rows.")

    rows: list[IndexRow] = []
    in_index = False
    for n, ln in enumerate(lines, 1):
        if ln.startswith("## The index"):
            in_index = True
            continue
        if in_index:
            if ln.startswith("## "):
                break
            if not ln.startswith("|") or ln.startswith("|---") or " lever " in ln:
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) < 6:
                continue
            tm = re.match(r"^`([^`]+)`", cells[0])
            if not tm:
                raise PromptStatusError(
                    f"{path}:{n}: first cell {cells[0]!r} does not start with a "
                    f"backticked target path.")
            status, _ = split_status(cells[4], vocab, f"{path}:{n}")
            rows.append(IndexRow(tm.group(1), status, cells[5], n))
    if not rows:
        raise PromptStatusError(f"{path}: could not parse any index rows.")
    return rows, vocab


def shas_in(text: str) -> tuple[str, ...]:
    """Backticked hex tokens. `W0-A`…`W0-G` are subject prefixes and do not match."""
    return tuple(dict.fromkeys(SHA.findall(text)))


def sha_state(sha: str, repo: Path = REPO_ROOT) -> str:
    """'ok', 'unknown' (does not resolve) or 'unreachable' (not an ancestor)."""
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", sha + "^{commit}"],
                       cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        return "unknown"
    r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                       cwd=repo, capture_output=True, text=True)
    return "ok" if r.returncode == 0 else "unreachable"


def results_paths_in(text: str) -> tuple[str, ...]:
    return tuple(p for p in dict.fromkeys(PATHLIKE.findall(text))
                 if p.startswith("results/"))


def is_runtime_artefact(spec: str) -> bool:
    return any(rx.match(spec) for rx in RUNTIME_ARTEFACTS)


def resolve(spec: str, root: Path = REPO_ROOT) -> list[Path]:
    """Resolve a named path. `<date>` is a placeholder -> prefix glob."""
    spec = spec.rstrip(".,;:").split("::")[0]
    spec = re.sub(r":\d+$", "", spec)
    if "<" in spec:
        spec = re.sub(r"<[^>]+>", "*", spec)
    if any(ch in spec for ch in "*?["):
        return sorted(root.glob(spec))
    p = root / spec
    return [p] if p.exists() else []


def reads_region(text: str) -> str | None:
    """The part of a prompt that names things to READ, not things to build.

    Everything above the first `## Part` / `## Stage` / `## Deliverables`. A
    prompt with none of those markers is not shaped like a prompt and is
    skipped rather than guessed at.
    """
    m = re.search(r"^## (?:Part|Stage|Deliverables)\b", text, re.M)
    return text[:m.start()] if m else None


# A prompt that says a path is missing is being careful, not stale. Flagging
# those was this checker's first calibration error: all five of its opening
# findings were prompts that already told the reader the file was not there
# (`G1:25` "(`scripts/vrp/` is gone)", `W14:38` "**which does not exist**"). A
# NOTE that fires on the careful case teaches the reader to skip the column.
ACKNOWLEDGED = re.compile(
    r"do(?:es)? not exist|is gone|are gone|never existed|no longer|absent|"
    r"was archived|has been archived|to (?:be )?(?:build|built|create|written)",
    re.I)


def dead_read_pointers(text: str, repo: Path = REPO_ROOT) -> tuple[str, ...]:
    region = reads_region(text)
    if region is None:
        return ()
    out = []
    for spec in dict.fromkeys(PATHLIKE.findall(region)):
        if is_runtime_artefact(spec) or "<" in spec or "{" in spec:
            continue
        if resolve(spec, repo):
            continue
        # Look at the sentence around each mention before calling it stale.
        acknowledged = False
        for m in re.finditer(re.escape("`" + spec + "`"), region):
            window = region[max(0, m.start() - 160):m.end() + 200]
            if ACKNOWLEDGED.search(window):
                acknowledged = True
                break
        if not acknowledged:
            out.append(spec)
    return tuple(out)


def counters(path: Path = RESEARCH_STATE) -> dict[str, int]:
    """The canonical trial counters. CONTEXT ONLY -- no check may branch on these."""
    if not path.exists():
        raise PromptStatusError(f"no research state at {path}")
    out = {}
    for ln in path.read_text().splitlines():
        m = re.match(r"^\|\s*\*\*(CEF|GAMMA)\*\*\s*\|.*?\|\s*\*\*(\d+)\*\*\s*\|", ln)
        if m:
            out[m.group(1)] = int(m.group(2))
    if "CEF" not in out or "GAMMA" not in out:
        raise PromptStatusError(
            f"{path}: could not read the canonical CEF/GAMMA counter rows.")
    return out


# -------------------------------------------------------------------- audit

def prompt_files(prompts: Path = PROMPTS) -> list[Path]:
    return sorted(p for p in prompts.rglob("*.md")
                  if "_superseded" not in p.parts)


def audit(prompts: Path = PROMPTS, index: Path = INDEX,
          repo: Path = REPO_ROOT, strict: bool = False) -> Report:
    rep = Report()
    rows, vocab = read_index(index)
    files = prompt_files(prompts)

    # -- A1 coverage, both directions ------------------------------------
    by_target: dict[str, IndexRow] = {r.target: r for r in rows}
    for r in rows:
        if not (prompts / r.target.rstrip("/")).exists():
            rep.add(DRIFT, r.target,
                    f"index:{r.line_no} names a target that does not exist")
    for f in files:
        rel = f.relative_to(prompts).as_posix()
        if rel == "README.md":
            continue
        covered = rel in by_target or any(
            t.endswith("/") and rel.startswith(t) for t in by_target)
        if not covered:
            rep.add(DRIFT, rel, "no index row covers this prompt")

    # -- per prompt -------------------------------------------------------
    for f in files:
        rel = f.relative_to(prompts).as_posix()
        if f.name in NON_PROMPTS or DATED_ARTIFACT.match(f.name):
            continue
        text = f.read_text()
        banner = leading_banner(text)
        p_status, p_evidence = declared_status(text, vocab, rel)

        row = by_target.get(rel)
        if row is None:  # covered by a directory row; compare against it
            row = next((r for r in rows if r.target.endswith("/")
                        and rel.startswith(r.target)), None)
        if row is None:
            continue

        # -- A2/A7 the prompt and the index must agree on the token -------
        if row.target.endswith("/"):
            pass  # a directory row speaks for many prompts; token is a summary
        elif p_status != row.status:
            rep.add(DRIFT, rel,
                    f"prompt declares {p_status!r}, index:{row.line_no} says "
                    f"{row.status!r}. The prompt is authoritative.")

        # -- A3 the banner biconditional ---------------------------------
        has_banner = "EXECUTED" in banner
        if has_banner and p_status != "executed":
            rep.add(DRIFT, rel,
                    f"carries an EXECUTED banner but declares {p_status!r}")
        if p_status == "executed" and not has_banner:
            rep.add(DRIFT, rel,
                    "declared executed but has no EXECUTED banner in its "
                    "leading blockquote")

        # -- A5 queued means never run ------------------------------------
        if p_status == "queued" and shas_in(p_evidence):
            rep.add(DRIFT, rel,
                    "declared queued but its evidence names a commit")

        # -- A4 every sha resolves and is reachable -----------------------
        for sha in shas_in(banner) + shas_in(p_evidence) + shas_in(row.evidence):
            st = sha_state(sha, repo)
            if st != "ok":
                rep.add(DRIFT, rel, f"cites commit `{sha}` which is {st}")

        # -- evidence notes must exist ------------------------------------
        for spec in results_paths_in(p_evidence) + results_paths_in(row.evidence):
            if not resolve(spec, repo):
                rep.add(DRIFT, rel, f"cites `{spec}`, which does not exist")

        # -- NOTE: dead READ pointers -------------------------------------
        # Only the preamble region counts. Below the first `## Part`/`## Stage`
        # a missing path is almost always something the prompt is asking you to
        # BUILD (`scripts/cef/holdout.py`, `results/cef/inference.json`), and
        # flagging those would bury the real finding in ~40 lines of noise.
        # Above it, a missing path is a pointer at something that is not there
        # -- which is how four prompts came to point at `results/vrp/` and
        # `src/deploy/lib/black76.py` after W0 archived them.
        for spec in dead_read_pointers(text, repo):
            rep.add(DRIFT if strict else NOTE, rel,
                    f"tells you to read `{spec}`, which does not exist")

    c = counters(RESEARCH_STATE if repo == REPO_ROOT else repo / "docs/RESEARCH_STATE.md")
    rep.add(INFO, "trial counters",
            f"CEF {c['CEF']}, GAMMA {c['GAMMA']} (context only; no check reads these)")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any DRIFT")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="treat advisory NOTEs as DRIFT")
    ap.add_argument("--prompts", type=Path, default=PROMPTS)
    ap.add_argument("--index", type=Path, default=None)
    ap.add_argument("--repo", type=Path, default=REPO_ROOT)
    a = ap.parse_args(argv)
    idx = a.index or (a.prompts / "README.md")

    try:
        rep = audit(a.prompts, idx, a.repo, strict=a.strict)
    except PromptStatusError as e:
        print(f"  DRIFT  {'(parse)':<40}  {e}", file=sys.stderr)
        return 1
    bad = ([f for f in rep.findings if f[0] != INFO] if a.strict
           else rep.drifted())

    if a.json:
        print(json.dumps({"findings": [
            {"level": l, "where": w, "message": m} for l, w, m in rep.findings]},
            indent=2))
    else:
        print(f"prompt status — {a.prompts}")
        print(rep.render(strict=a.strict))

    if a.check or a.strict:
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
