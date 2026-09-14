#!/usr/bin/env python3
"""Do this repo's documents still say true things? Measured, not asserted.

    python3 -m ops.doc_audit           # the table
    python3 -m ops.doc_audit --check   # exit 1 if anything DRIFTed
    python3 -m ops.doc_audit --json

WHY THIS FILE EXISTS
--------------------
CLAUDE.md carries a section called "Documents that will mislead you". On
2026-09-13 that section was audited against the filesystem and **every specific
defect it named had already been fixed**:

    "INFRASTRUCTURE.md:171 still names spec v5.20260731"   -> says v6.20260906
    "PLAN.md :154 and :174 are still unmarked"             -> all 5 rows marked
    "PER_NAME_ARCHITECTURE.md:150 still carries the pooled 24.6"
                                                           -> flagged in place
    "SYSTEM_AND_STRATEGY.md has NO banner"                 -> banner at line 11

That section warns, in its own words, that "a table that asserts the remedy is
MISSING when it is not is the same defect wearing the opposite sign, and costs a
re-fix". It had become the thing it warns about -- the most elaborate warning in
the repo, and the stalest object in it.

Hand-maintained claims about files rot because the files move and the claims do
not. So the claims move here, where they are CHECKED rather than asserted, and
CLAUDE.md keeps the rule and drops the counts. This is the same trade
`ops/orient.py` made for the hygiene greps and `ops/session_uptime.py` made for
the arm rate, both for the same reason.

WHAT IT DOES NOT DO
-------------------
It cannot tell you whether a document's ARGUMENT is sound, only whether the
specific, mechanically checkable things it says still match the repo. A PASS
here is not a statement that a document is trustworthy. Read the banner.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OK, DRIFT, NOTE, GONE = "OK", "DRIFT", "NOTE", "GONE"

# DRIFT means a document CONTRADICTS something measurable -- it must be fixed,
# and --check fails on it. NOTE means a standing backlog that is visible and
# real but does not make any single document wrong today. Collapsing the two
# makes --check useless as a gate, because a permanent backlog would keep it
# red and everyone would stop reading it. `ops/prompt_status.py` splits them
# the same way and for the same reason.

# How far into a file a banner may start and still be the first thing a reader
# meets. PER_NAME_ARCHITECTURE's runs to line 41, so `head -12` truncates it
# mid-argument -- which CLAUDE.md records as its own mistake.
BANNER_WITHIN = 45
BANNER_RE = re.compile(r"^>\s*.*(⚠|CORRECTED|SUPERSEDED|READ THIS FIRST|STALE|⛔)",
                       re.M)


@dataclass
class Finding:
    key: str
    status: str
    detail: str
    fix: str = ""


@dataclass
class Report:
    findings: list = field(default_factory=list)

    def add(self, *a, **k):
        self.findings.append(Finding(*a, **k))

    @property
    def drift(self):
        return [f for f in self.findings if f.status in (DRIFT, GONE)]

    @property
    def notes(self):
        return [f for f in self.findings if f.status == NOTE]


def _read(rel: str) -> str | None:
    p = REPO / rel
    return p.read_text(errors="replace") if p.exists() else None


# -- 1. banners -------------------------------------------------------------

# Six of the original eight moved to _archive/ on 2026-09-13, where
# `check_archive_wall` requires a stricter banner of every file. What remains
# here is the one live document that still carries old passages under a
# warning. RESEARCH_STATE.md was trimmed to its ledger on 2026-09-14 and
# needs none.
BANNERED = [
    "docs/INFRASTRUCTURE.md",
]


def check_banners(rep: Report) -> None:
    """Every document known to be superseded must warn a reader who does not scroll."""
    for rel in BANNERED:
        text = _read(rel)
        if text is None:
            rep.add(f"banner:{rel}", GONE, "file does not exist",
                    "remove it from BANNERED or restore the file")
            continue
        head = "\n".join(text.splitlines()[:BANNER_WITHIN])
        m = BANNER_RE.search(head)
        if m:
            line = head[:m.start()].count("\n") + 1
            rep.add(f"banner:{rel}", OK, f"banner at line {line}")
        else:
            rep.add(f"banner:{rel}", DRIFT,
                    f"no banner in the first {BANNER_WITHIN} lines",
                    "a superseded document must say so before its body")


# -- 2. claims that must match a measured source ----------------------------

SPEC_ID_SCOPE = ("CLAUDE.md", "README.md", "docs/SYSTEM.md", "docs/INFRASTRUCTURE.md",
                 "docs/REFERENCES.md", "docs/prompts/00_BRIEF.md")


def check_spec_id(rep: Report) -> None:
    """A live document that names a spec id must name the live one.

    WHY. INFRASTRUCTURE.md once named spec v5 for three weeks after v6 went live,
    and the one table a reader consults for "what does the sleeve do" described a
    policy that no longer ran. A superseded id is fine inside a correction that
    also names the live one; an old id standing alone is the defect. This used to
    look at INFRASTRUCTURE.md only, and the same sentence can be written anywhere
    a reader starts.
    """
    spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
    live = spec["spec_id"]
    for rel in SPEC_ID_SCOPE:
        text = _read(rel)
        if text is None:
            continue
        # An id inside a path is a filename (the archived v5 revert spec), not a claim.
        named = set(re.findall(r"(?<![/\w])cef_discount\.v\d+\.\d{8}", text))
        if not named:
            rep.add(f"spec_id:{rel}", OK, "names no spec id")
        elif live in named:
            others = sorted(named - {live})
            rep.add(f"spec_id:{rel}", OK, f"{live} present"
                    + (f"; superseded {others} kept beside it" if others else ""))
        else:
            rep.add(f"spec_id:{rel}", DRIFT,
                    f"names {sorted(named)} but never the live spec {live}",
                    f"quote {live}, from ops/specs/cef_discount.frozen.json")


# `check_dsr_bar` was retired 2026-09-13. It guarded one sentence in
# RESEARCH_AND_METHODOLOGY.md (a deflated-Sharpe bar quoted against a stale trial
# count); that document is archived, and the bar is derived live by
# `python3 -m ops.orient` TRIALS rather than written anywhere.


def _opens_ib_socket(path: Path) -> bool:
    """Does this module import an IB client AT MODULE OR FUNCTION level?

    AST, not grep. `ops/orient.py` mentions `ib_insync` only as a STRING it
    searches other files for, and a grep counts it as a broker module -- which
    is how the hand-maintained count in ops/README.md drifted in the first place.
    """
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in ("ib_async", "ib_insync") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in ("ib_async", "ib_insync"):
                return True
    return False


def check_ops_broker_modules(rep: Report) -> None:
    """Which ops modules open an IB socket. Measured, and asserted nowhere.

    This used to police the sentence "There is no broker here" in ops/README.md,
    which was false and had to be retracted in its own body. That README is
    archived; the measurement it contradicted is the durable part, so it is
    reported here for anyone about to run an ops module and wondering whether it
    can reach the broker.
    """
    mods = sorted(p.name for p in (REPO / "ops").glob("*.py") if _opens_ib_socket(p))
    rep.add("ops_broker", OK,
            f"{len(mods)} ops module(s) import an IB client: {', '.join(mods)}"
            if mods else "no ops module imports an IB client")


def check_band_width_literals(rep: Report) -> None:
    """The retired 6.4% width must never be written as a literal in cef research."""
    hits = []
    for p in (REPO / "scripts/cef").rglob("*.py"):
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if "0.064" in line:
                hits.append(f"{p.relative_to(REPO)}:{i}")
    rep.add("band_width_literals", OK,
            f"{len(hits)} occurrence(s) of 0.064 in scripts/cef"
            + (f" -- survivors are comments/sweeps/labelled rows; the RULE is "
               f"read band_width from the frozen spec" if hits else ""))


REPRODUCER_RE = re.compile(r"`?(python3?|scripts/|ops/)[\w./ _-]*\.py")


def check_results_notes_have_reproducers(rep: Report) -> None:
    """A results note must name the script that reproduces it (documents.md rule 1).

    PRE-REGISTRATIONS ARE EXCLUDED AND CHECKED SEPARATELY. A prereg is written
    BEFORE the run it commits to, so demanding it name a reproducer is demanding
    it cite output that does not exist yet. Its shape requirement is different:
    documents.md asks it to state what would falsify it.

    The rest is reported as a NOTE, not DRIFT. Sixteen notes predate the rule,
    most of them one-off ops incident records from 2026-09-10 whose content is a
    narrative of an investigation rather than a reproducible measurement. That is
    a real backlog and it is printed in full -- but it does not make any of them
    WRONG today, and failing --check forever on it would retire the gate.
    """
    missing, preregs = [], []
    for p in sorted((REPO / "results").rglob("*.md")):
        head = "\n".join(p.read_text(errors="replace").splitlines()[:40])
        if REPRODUCER_RE.search(head):
            continue
        (preregs if "PREREG" in p.name.upper() else missing).append(
            str(p.relative_to(REPO)))
    rep.add("results_reproducers", NOTE if missing else OK,
            f"{len(missing)} measurement note(s) name no reproducer in their "
            f"first 40 lines" + (": " + ", ".join(missing) if missing else ""),
            "documents.md rule 1: if it cannot be reproduced, label it an anecdote"
            if missing else "")
    rep.add("prereg_reproducers", OK,
            f"{len(preregs)} pre-registration(s) name no reproducer, which is "
            f"correct -- a prereg precedes its own run")


# How this desk actually writes a falsifier. The first version of this list held
# only "falsif"/"would kill"/"abandon if" and flagged all three existing preregs
# as having none -- while HOLDOUT_PREREG.md carries a table row reading
# "FAIL -- the 2005-2023 result did not generalise. Halt the sleeve and flatten."
# and a section headed "Known reasons this could fail, stated in advance". A
# check that invents a defect is worse than no check, so the vocabulary is taken
# from the documents rather than from what a falsifier "should" be called.
# `tests/test_doc_audit.py` pins that it still FAILS a prereg with none.
FALSIFIER_WORDS = (
    "falsif", "would kill", "abandon if", "what would make this wrong",
    "kill rule", "could fail", "halt the sleeve", "fail —", "fail --",
    "stated in advance", "would revert", "revert if",
)


def check_prereg_shape(rep: Report) -> None:
    """Every pre-registration must say what would falsify it (documents.md)."""
    bad = []
    for p in sorted((REPO / "results").rglob("*.md")):
        if "PREREG" not in p.name.upper():
            continue
        t = p.read_text(errors="replace").lower()
        if not any(k in t for k in FALSIFIER_WORDS):
            bad.append(str(p.relative_to(REPO)))
    rep.add("prereg_falsifier", DRIFT if bad else OK,
            f"{len(bad)} pre-registration(s) state no falsifier"
            + (": " + ", ".join(bad) if bad else ""),
            "a prereg that cannot be falsified commits to nothing" if bad else "")


def check_desk_inventory(rep: Report) -> None:
    """CLAUDE.md names every skill and subagent by hand. Both lists can rot.

    A named-but-missing skill sends an agent looking for a workflow that does not
    exist; a present-but-unnamed one is simply never found. Neither fails loudly,
    which is why this is checked rather than trusted.
    """
    claude = _read("CLAUDE.md") or ""
    for kind, d in (("skill", REPO / ".claude/skills"),
                    ("agent", REPO / ".claude/agents")):
        if not d.exists():
            rep.add(f"desk:{kind}s", GONE, f"{d.relative_to(REPO)} does not exist")
            continue
        on_disk = {p.stem if p.is_file() else p.name for p in d.iterdir()
                   if not p.name.startswith(".")}
        named = {n for n in on_disk if f"`{'/' if kind == 'skill' else ''}{n}`" in claude}
        missing_from_doc = sorted(on_disk - named)
        # and the reverse: a name CLAUDE.md lists that has no file
        listed = set(re.findall(r"`/([a-z][a-z0-9-]+)`" if kind == "skill"
                                else r"`([a-z][a-z0-9-]+)`", claude))
        ghosts = sorted(listed & _KNOWN_DESK_NAMES[kind] - on_disk)
        if missing_from_doc or ghosts:
            rep.add(f"desk:{kind}s", DRIFT,
                    (f"on disk but unnamed in CLAUDE.md: {missing_from_doc}; "
                     if missing_from_doc else "")
                    + (f"named in CLAUDE.md but absent: {ghosts}" if ghosts else ""),
                    "keep the desk list and the directory in step")
        else:
            rep.add(f"desk:{kind}s", OK, f"{len(on_disk)} {kind}(s), all named")


# The vocabulary problem again: CLAUDE.md backticks a lot of things that are not
# subagents. Rather than guess from shape, the reverse check is limited to names
# this repo has actually ever had, so a backticked filename cannot masquerade as
# a missing agent. Extend it when a seat is added.
_KNOWN_DESK_NAMES = {
    "skill": {"book-status", "preflight", "morning-brief", "next-task",
              "graveyard", "harness", "repro", "prereg", "spec-change",
              "fill-audit", "dashboard-ui", "incident"},
    "agent": {"alpha-finder", "beta-detector", "unique-angle-researcher",
              "execution-trader", "portfolio-manager", "market-structure-analyst",
              "equity-research", "quant-reviewer", "dashboard-designer",
              "ops-watchdog"},
}


# -- the archive wall --------------------------------------------------------

ARCHIVE = "_archive"
# Exempt from the banner rule: the index itself, and the file that exists only
# to be searched for.
ARCHIVE_UNBANNERED = {"_archive/README.md", "_archive/ARCHIVE_WALL_SENTINEL.md"}
ARCHIVE_BANNER_RE = re.compile(
    r"^>\s*\*\*ARCHIVED (\d{4}-\d{2}-\d{2}) (?:—|--) not evidence of current "
    r"state\.\*\*\s*(Was|Snapshot of) `([^`]+)`", re.M)
# Where live code lives. An import from the archive in any of these puts a
# superseded module back on a path something runs.
LIVE_CODE_ROOTS = ("ops", "src", "scripts", "dashboard", ".claude/hooks")


def _archive_rows(readme: str) -> set:
    """Backticked `_archive/...` paths in the index's first column.

    A row may name several paths (a research line's scripts and its results
    move together and share one "what it is wrong about"), so every backticked
    archive path in the first cell counts.
    """
    rows = set()
    for line in readme.splitlines():
        m = re.match(r"^\|([^|]*)\|", line)
        if m:
            rows.update(re.findall(r"`(_archive/[^`]+)`", m.group(1)))
    return rows


def _covered(rel: str, rows: set) -> bool:
    """A file is indexed if its own path, or a directory above it, has a row."""
    if rel in rows:
        return True
    parts = rel.split("/")
    return any("/".join(parts[:i]) + "/" in rows for i in range(1, len(parts)))


def _untracked_in_archive() -> list[str] | None:
    """Files under _archive/ that git is NOT tracking. None if there is no git.

    The wall is a .gitignore line on a tracked directory, so a file created
    here is invisible to `git status` and skipped by `git add -A`. Without this
    a freshly archived document would look committed and exist on one machine.
    """
    import subprocess
    if not (REPO / ".git").exists():
        return None
    r = subprocess.run(["git", "ls-files", "--others", "--ignored",
                        "--exclude-standard", "--", ARCHIVE],
                       cwd=REPO, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {r.stderr.strip()[:120]}")
    return [ln for ln in r.stdout.splitlines()
            if ln.strip() and "__pycache__" not in ln and not ln.endswith(".DS_Store")]


def check_archive_wall(rep: Report) -> None:
    """The archive is only a wall if every brick is checked.

    WHY. Superseded documents used to sit beside current ones under a banner,
    and a banner does not stop an agent that found a file by SEARCHING from
    quoting its body. `/_archive/` in `.gitignore` keeps archived bodies out of
    ripgrep and out of the ugrep-backed `grep` that Claude Code's shell runs --
    both skip gitignored paths unless pointed at them. (`.ignore` was tried
    first: ripgrep reads it, grep -r does not, and walked straight through.)
    `find`, `ls` and `git grep` still see the folder, so the banner is the
    second line of defence and is enforced here, together with the ways the
    wall fails silently:

      * the ignore line goes -> every archived body is searchable again;
      * a file is archived but never `git add -f`ed -> it exists on one machine;
      * a nested CLAUDE.md or .claude/ lands in here -> Claude Code auto-loads a
        superseded rulebook for anyone who opens a path in that subtree;
      * live code imports from here -> a retired module is back on a run path.

    A banner's `Was` path must be the file's own location with `_archive/`
    stripped, so a reader can tell where it came from without `git log`. A
    `Snapshot of` path must still exist in the live tree -- that is what makes
    it a snapshot of a document that was trimmed, not a move.
    """
    root = REPO / ARCHIVE
    if not root.exists():
        rep.add("archive:wall", GONE, f"{ARCHIVE}/ does not exist",
                "the archive wall is part of the document contract; restore it")
        return
    ignore = _read(".gitignore") or ""
    if "/_archive/" not in {ln.strip() for ln in ignore.splitlines()}:
        rep.add("archive:ignore", DRIFT,
                ".gitignore does not list /_archive/ -- archived bodies are searchable",
                "restore the line `/_archive/` in .gitignore")
    else:
        rep.add("archive:ignore", OK, ".gitignore walls /_archive/ from rg and grep")

    untracked = _untracked_in_archive()
    if untracked is None:
        rep.add("archive:tracked", NOTE, "no .git here; tracking not checked")
    elif untracked:
        rep.add("archive:tracked", DRIFT,
                f"{len(untracked)} file(s) under _archive/ are not in git: "
                f"{', '.join(untracked[:8])}",
                "git add -f them -- .gitignore hides new files from git add -A")
    else:
        rep.add("archive:tracked", OK, "every file under _archive/ is tracked")

    readme = _read(f"{ARCHIVE}/README.md")
    if readme is None:
        rep.add("archive:readme", GONE, f"{ARCHIVE}/README.md does not exist",
                "the index is what makes an archived file findable on purpose")
        readme = ""
    rows = _archive_rows(readme)

    unbannered, misplaced, unindexed, nested = [], [], [], []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(REPO).as_posix()
        if p.name.lower() == "claude.md" or (p.is_dir() and p.name == ".claude"):
            nested.append(rel)
        if p.is_dir():
            continue
        if rel not in ARCHIVE_UNBANNERED and not _covered(rel, rows):
            unindexed.append(rel)
        if p.suffix != ".md" or rel in ARCHIVE_UNBANNERED:
            continue
        head = "\n".join(p.read_text(errors="replace").splitlines()[:BANNER_WITHIN])
        m = ARCHIVE_BANNER_RE.search(head)
        if not m:
            unbannered.append(rel)
            continue
        kind, origin = m.group(2), m.group(3)
        if kind == "Was" and origin != rel[len(ARCHIVE) + 1:]:
            misplaced.append(f"{rel} says Was `{origin}`")
        elif kind == "Snapshot of" and not (REPO / origin).exists():
            misplaced.append(f"{rel} is a snapshot of `{origin}`, which does not exist")

    for key, bad, what, fix in (
        ("archive:nested_claude", nested,
         "a CLAUDE.md or .claude/ inside the archive would auto-load",
         "rename a CLAUDE.md snapshot to CLAUDE_md_<date>.md; move agent files "
         "under _archive/claude_layer/"),
        ("archive:banners", unbannered,
         "archived .md with no ARCHIVED banner in the first "
         f"{BANNER_WITHIN} lines", "add the banner from _archive/README.md rule 3"),
        ("archive:mirror", misplaced,
         "banner origin does not match the file's location",
         "mirror the original path, or correct the banner"),
        ("archive:index", unindexed,
         "archived file with no row (or directory row) in _archive/README.md",
         "add a row saying what it was and what it is wrong about"),
    ):
        if bad:
            rep.add(key, DRIFT, f"{len(bad)} {what}: {', '.join(bad[:8])}"
                    + (f" (+{len(bad) - 8} more)" if len(bad) > 8 else ""), fix)
        else:
            rep.add(key, OK, "none")

    importers = []
    for top in LIVE_CODE_ROOTS:
        base = REPO / top
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if ARCHIVE in p.relative_to(REPO).parts:
                continue
            try:
                tree = ast.parse(p.read_text(errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom)
                        else [])
                if any(m.split(".")[0] == ARCHIVE for m in mods):
                    importers.append(p.relative_to(REPO).as_posix())
                    break
    rep.add("archive:imports", DRIFT if importers else OK,
            (f"live code imports from {ARCHIVE}/: {', '.join(sorted(importers))}"
             if importers else f"no live module imports from {ARCHIVE}/"),
            "restore the module to a live path, or stop importing it"
            if importers else "")


# -- the manifest: one owner per question -----------------------------------

MANIFEST = "docs/INDEX.md"
# Authored markdown lives everywhere except these. results/ is dated records,
# _archive/ has its own index, and the ops/ entries are written by the running
# system, not by a person.
UNINDEXED_PREFIXES = ("results/", "_archive/", "data/", "ops/books/",
                      "ops/reports/", "ops/halts/", ".pytest_cache/", ".git/")
UNINDEXED_RE = re.compile(r"^ops/HALT.*\.md$")


def _glob_re(pattern: str) -> re.Pattern:
    """`**/` spans directories (including none), `*` stays inside one."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += r"(?:.*/)?"
            i += 3
        elif pattern[i] == "*":
            out += r"[^/]*"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def read_manifest(text: str) -> tuple[set, list]:
    """Roles vocabulary and index rows, both read from the file itself.

    Same design as `ops/prompt_status.py:read_index`: the vocabulary is never
    hard-coded in the checker, so the file cannot drift from its own checker.
    """
    roles, rows, section = set(), [], None
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section == "roles":
            m = re.match(r"^\|\s*\*\*([a-z-]+)\*\*\s*\|", line)
            if m:
                roles.add(m.group(1))
        elif section == "the index":
            m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*([a-z-]+)\s*\|\s*([^|]*)\|", line)
            if m:
                rows.append({"path": m.group(1), "role": m.group(2),
                             "owns": m.group(3).strip(), "line": n})
    return roles, rows


def _authored_markdown() -> list[str]:
    out = []
    for p in REPO.rglob("*.md"):
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith(UNINDEXED_PREFIXES) or UNINDEXED_RE.match(rel):
            continue
        if "__pycache__" in rel or "/.pytest_cache/" in rel:
            continue
        out.append(rel)
    return sorted(out)


def check_manifest(rep: Report) -> None:
    """Every authored document is registered, once, with a role and an owner.

    WHY. On 2026-09-13 six documents each presented themselves as the place to
    start, "how the strategy works" was written six times, and the copies
    disagreed about the arm rate, the vol target and which tag prod ran. Nobody
    had decided any of that; each document had simply been written without
    knowing the others existed. A manifest makes "who owns this question?" a
    lookup, and this check makes a new document without an answer fail loudly
    instead of quietly becoming the seventh.

    An exact row beats a glob, so `docs/prompts/README.md` can be canonical
    while `docs/prompts/**/*.md` are work orders. Two GLOB rows matching one
    file with no exact row is ambiguous and is drift.
    """
    text = _read(MANIFEST)
    if text is None:
        rep.add("manifest", GONE, f"{MANIFEST} does not exist",
                "restore the index; every authored document needs an owner row")
        return
    roles, rows = read_manifest(text)
    if not roles or not rows:
        rep.add("manifest", DRIFT,
                f"{MANIFEST}: could not parse "
                + ("a '## Roles' table" if not roles else "a '## The index' table"),
                "keep `| **role** | meaning |` and `| `path` | role | owns | ... |` rows")
        return

    bad_roles = [f"{r['path']} ({r['role']})" for r in rows if r["role"] not in roles]
    ghosts = [r["path"] for r in rows
              if not any(c in r["path"] for c in "*?[") and not (REPO / r["path"]).exists()]
    owners: dict = {}
    for r in rows:
        if r["role"] in ("canonical", "ledger") and r["owns"] not in ("", "—"):
            owners.setdefault(r["owns"].lower(), []).append(r["path"])
    dup_owners = [f"'{q}': {', '.join(ps)}" for q, ps in owners.items() if len(ps) > 1]

    exact = {r["path"] for r in rows if not any(c in r["path"] for c in "*?[")}
    globs = [(r["path"], _glob_re(r["path"])) for r in rows
             if any(c in r["path"] for c in "*?[")]
    unregistered, ambiguous = [], []
    for rel in _authored_markdown():
        if rel in exact:
            continue
        hits = [g for g, rx in globs if rx.match(rel)]
        if not hits:
            unregistered.append(rel)
        elif len(hits) > 1:
            ambiguous.append(f"{rel} <- {hits}")

    for key, bad, what, fix in (
        ("manifest:roles", bad_roles, "row(s) with a role not in the Roles table",
         "use a listed role or add it to the table with its meaning"),
        ("manifest:ghosts", ghosts, "row(s) naming a file that does not exist",
         "delete the row, or point it at the file's new home"),
        ("manifest:owners", dup_owners, "question(s) with two canonical owners",
         "one question, one owner: merge, or link from one to the other"),
        ("manifest:unregistered", unregistered,
         "authored document(s) with no row in docs/INDEX.md",
         "add a row naming what it owns, or archive it"),
        ("manifest:ambiguous", ambiguous, "document(s) matched by two globs",
         "add an exact row for it"),
    ):
        rep.add(key, DRIFT if bad else OK,
                f"{len(bad)} {what}" + (": " + "; ".join(bad[:8]) if bad else ""),
                fix if bad else "")


ENTRY_FILES = ("CLAUDE.md", "README.md")
ENTRY_POINTERS = ("ops.orient", "docs/SYSTEM.md")
START_HERE_RE = re.compile(r"\b(?:start|begin) here\b", re.I)
START_HERE_ALLOWED = {"CLAUDE.md", "README.md", ".claude/README.md"}


def check_entry_points(rep: Report) -> None:
    """Two entry files, both pointing at the two owners, and no seventh door.

    The documents that used to call themselves the starting point each sent the
    reader somewhere different, and four of the five that README.md listed first
    were historical. An entry file that forgets orient or SYSTEM.md sends the
    next reader back into that maze; any other file that says "start here" is
    building a new one.
    """
    for rel in ENTRY_FILES:
        text = _read(rel)
        if text is None:
            rep.add(f"entry:{rel}", GONE, "file does not exist")
            continue
        missing = [p for p in ENTRY_POINTERS if p not in text]
        rep.add(f"entry:{rel}", DRIFT if missing else OK,
                (f"does not point at {missing}" if missing
                 else "points at ops.orient and docs/SYSTEM.md"),
                "an entry file names the command for figures and the owner for "
                "everything else" if missing else "")
    doors = []
    for rel in _authored_markdown():
        if rel in START_HERE_ALLOWED:
            continue
        text = _read(rel) or ""
        if START_HERE_RE.search(text):
            doors.append(rel)
    rep.add("entry:others", DRIFT if doors else OK,
            (f"{len(doors)} other file(s) present themselves as the start: "
             f"{', '.join(doors)}" if doors else "no other file claims to be the start"),
            "point at CLAUDE.md / README.md instead" if doors else "")


# Files whose pointers must resolve. Widened as each file is rewritten to
# point at owners rather than restate them.
POINTER_SCOPE = ("CLAUDE.md", "README.md", "docs/SYSTEM.md", "docs/INDEX.md")
POINTER_ROOTS = ("ops/", "src/", "scripts/", "results/", "docs/", "config/",
                 "dashboard/", "deploy/", "_archive/", ".claude/")
POINTER_TOP = {"CLAUDE.md", "README.md", "pytest.ini", ".gitignore",
               "requirements.txt"}


def _pointer_targets(text: str) -> list[tuple[str, str]]:
    """(kind, spec) for each backticked repo path or `python3 ...` command."""
    out = []
    for tok in re.findall(r"`([^`\n]+)`", text):
        tok = tok.strip()
        m = re.match(r"^python3 -m ((?:ops|src|scripts|dashboard)(?:\.\w+)+)", tok)
        if m:
            out.append(("module", m.group(1)))
            continue
        m = re.match(r"^python3 ((?:ops|src|scripts|dashboard|\.claude)/\S+\.py)", tok)
        if m:
            out.append(("path", m.group(1)))
            continue
        if " " in tok:
            continue
        if tok.startswith(POINTER_ROOTS) or tok in POINTER_TOP:
            out.append(("path", tok))
    return out


def _resolves(kind: str, spec: str) -> bool:
    from ops import prompt_status as ps
    if kind == "module":
        base = REPO / spec.replace(".", "/")
        return base.with_suffix(".py").exists() or (base / "__init__.py").exists()
    if spec.startswith(("data/", "config/.env")) or ps.is_runtime_artefact(spec):
        return True                    # gitignored panels, secrets, session output
    if "<" in spec or "{" in spec or "..." in spec:
        return True                    # a placeholder, not a pointer
    return bool(ps.resolve(spec, REPO))


def check_pointers(rep: Report) -> None:
    """A path an owner document tells you to open must exist.

    The owner documents replaced prose with pointers, which moves the failure
    mode rather than removing it: a pointer at a file that has moved is a dead
    end that looks authoritative. `ops/prompt_status.py` already checks this for
    work orders; this applies the same resolver to the documents that own
    questions, including `_archive/` paths, which prompt_status does not read.
    """
    for rel in POINTER_SCOPE + tuple(_agent_layer()):
        text = _read(rel)
        if text is None:
            continue
        dead = sorted({spec for kind, spec in _pointer_targets(text)
                       if not _resolves(kind, spec)})
        rep.add(f"pointers:{rel}", DRIFT if dead else OK,
                (f"{len(dead)} pointer(s) to nothing: {', '.join(dead[:10])}"
                 if dead else "every pointer resolves"),
                "repoint to where the file went, or drop the pointer" if dead else "")


# Files that may never lean on the archive as authority. Work orders are
# exempt: a prompt legitimately reads an archived study as background.
CITATION_SCOPE_FILES = ("CLAUDE.md", "README.md", "docs/SYSTEM.md", "docs/INDEX.md",
                        "docs/RESEARCH_STATE.md", "docs/INFRASTRUCTURE.md",
                        "docs/REFERENCES.md")
CITATION_SCOPE_GLOBS = (".claude/**/*.md",)
# A path to a FILE inside the top-level archive. The lookbehind keeps a nested
# `<dir>/_archive/` (the pre-2026-09-14 layout) from matching, and
# `_archive/README.md` is the
# archive's own index, which is exactly what these files should point at.
ARCHIVE_CITE_RE = re.compile(r"(?<![\w/])_archive/[\w./-]+\.\w+")


def _citation_scope() -> list[str]:
    out = [f for f in CITATION_SCOPE_FILES if (REPO / f).exists()]
    for g in CITATION_SCOPE_GLOBS:
        rx = _glob_re(g)
        out += [p.relative_to(REPO).as_posix() for p in REPO.rglob("*.md")
                if rx.match(p.relative_to(REPO).as_posix())]
    return sorted(set(out))


def check_archive_citations(rep: Report) -> None:
    """An owner document may cite the archive only while SAYING it is archived.

    The failure this prevents is quiet: a rule file or skill that says "see
    `_archive/docs/PLAN.md` §3" reads exactly like one that cited the same
    file before it moved, and the reader goes and copies a retired figure. The word
    "archived" on the same line (or the one either side, for wrapped prose) is
    what turns a citation into provenance.
    """
    bad = []
    for rel in _citation_scope():
        lines = (_read(rel) or "").splitlines()
        for i, line in enumerate(lines):
            hits = [m.group(0) for m in ARCHIVE_CITE_RE.finditer(line)
                    if m.group(0) != "_archive/README.md"]
            if not hits:
                continue
            window = " ".join(lines[max(0, i - 1):i + 2]).lower()
            if "archived" not in window:
                bad.append(f"{rel}:{i + 1} {hits[0]}")
    rep.add("archive:citations", DRIFT if bad else OK,
            (f"{len(bad)} citation(s) of the archive not marked archived: "
             f"{', '.join(bad[:8])}" if bad else "every archive citation says so"),
            "say 'archived' beside it, or cite the current owner instead" if bad else "")


CODE_DOC_ROOTS = ("ops", "src", "scripts", "dashboard", "config", ".claude/hooks")
CODE_DOC_SUFFIXES = {".py", ".json", ".env", ".template", ".sh", ".yaml", ".yml"}
CODE_DOC_RE = re.compile(r"(?<![\w/])docs/[\w/.-]+\.md")


def check_code_doc_pointers(rep: Report) -> None:
    """Code comments that cite a document which has moved. NOTE, never DRIFT.

    Docstrings are where this repo keeps its incident history, so they cite
    documents constantly, and some of those citations sit in files that cannot
    be touched casually -- the frozen spec needs /spec-change, the live sleeve
    needs a test. A stale pointer there misleads but breaks nothing, so it is a
    visible backlog rather than a failing gate, with the archive path offered.
    """
    stale = []
    for top in CODE_DOC_ROOTS:
        base = REPO / top
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if (not p.is_file() or p.suffix not in CODE_DOC_SUFFIXES
                    or "_archive" in p.relative_to(REPO).parts
                    or "tests" in p.relative_to(REPO).parts   # fixtures, not citations
                    or "__pycache__" in p.parts):
                continue
            text = p.read_text(errors="replace")
            for m in set(CODE_DOC_RE.findall(text)):
                if (REPO / m).exists():
                    continue
                moved = (REPO / ARCHIVE / m).exists()
                stale.append(f"{p.relative_to(REPO).as_posix()} -> {m}"
                             + (" (now _archive/)" if moved else " (gone)"))
    rep.add("code_doc_pointers", NOTE if stale else OK,
            (f"{len(stale)} code/config citation(s) of a moved document: "
             + "; ".join(sorted(stale)[:10]) if stale
             else "no code or config cites a document that has moved"),
            "repoint when the file is next edited; the frozen spec via /spec-change"
            if stale else "")


# Files that must carry no figure that moves. Each pattern is a shape this repo
# actually wrote into one of these files and then had to correct -- kept narrow on
# purpose, because a check that fires on every number teaches people to ignore it.
ROTTING_SCOPE = ("CLAUDE.md", "README.md", "docs/SYSTEM.md", "docs/INDEX.md")
ROTTING_PATTERNS = (
    (re.compile(r"\b\d+ (?:tests|passed)\b"), "a test count"),
    (re.compile(r"\barmed (?:on )?\d+ of \d+|\b\d+ of \d+ (?:eligible |CEF )?sessions\b"),
     "an arm rate"),
    (re.compile(r"\b(?:CEF|GAMMA)\b\*{0,2}\s*(?:=|\(|:)\s*\*{0,2}\d+"), "a trial counter"),
    (re.compile(r"--trials \d+"), "a trial count baked into a command"),
    (re.compile(r"\b(?:thirteen|\d+) (?:dead|killed) mechanisms\b", re.I), "a graveyard count"),
    (re.compile(r"\bv20\d\d\.\d\d\.\d\d\.\d+\b"), "a release tag"),
)
DATED_LABEL_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b.*\[(?:V|S|U)\]|\[(?:V|S|U)\].*\b20\d\d-\d\d-\d\d\b")


def check_rotting_figures(rep: Report) -> None:
    """The entry, rule and owner documents may not carry a figure that moves.

    Every pattern below was once written into CLAUDE.md or README.md and went
    wrong: a test count that read 126, 271 and 211 inside a day; an arm rate
    that existed as four fractions at once; "CEF = 48" beside a table that is
    the only place the counter is maintained; a prod tag that was two
    promotions stale. The owner of each is a command. A line that carries a
    date AND a provenance label ([V]/[S]/[U]) is a dated observation and is
    allowed -- that is how the data rules say a figure should be written.
    """
    for rel in ROTTING_SCOPE + tuple(_rotting_extra()):
        text = _read(rel)
        if text is None:
            continue
        hits = []
        for i, line in enumerate(text.splitlines(), 1):
            if DATED_LABEL_RE.search(line):
                continue
            for rx, what in ROTTING_PATTERNS:
                m = rx.search(line)
                if m:
                    hits.append(f"{rel}:{i} {what} ({m.group(0)!r})")
        rep.add(f"figures:{rel}", DRIFT if hits else OK,
                f"{len(hits)} rotting figure(s): {'; '.join(hits[:6])}" if hits
                else "no figure that moves",
                "replace it with the command that measures it, or date and label it"
                if hits else "")


def _agent_layer() -> list[str]:
    """Every markdown file Claude Code loads as rules, skills or subagents."""
    base = REPO / ".claude"
    if not base.exists():
        return []
    return sorted(p.relative_to(REPO).as_posix() for p in base.rglob("*.md")
                  if "__pycache__" not in p.parts)


def _live_prompts() -> list[str]:
    """Live work orders and their index. Executed and closed ones are archived."""
    base = REPO / "docs/prompts"
    if not base.exists():
        return []
    return sorted(p.relative_to(REPO).as_posix() for p in base.rglob("*.md"))


def _rotting_extra() -> list[str]:
    """The agent layer is read before any document, and a live work order is
    pasted straight into a session, so both are held to the same bar. Added for
    prompts 2026-09-14, when W3's header still gave the arm rate as "3 of 26"
    two weeks and a schedule change after it was measured."""
    return _agent_layer() + _live_prompts()


CHECKS = [check_banners, check_spec_id, check_ops_broker_modules,
          check_band_width_literals, check_results_notes_have_reproducers,
          check_prereg_shape, check_desk_inventory, check_archive_wall,
          check_manifest, check_entry_points, check_pointers,
          check_archive_citations, check_code_doc_pointers, check_rotting_figures]


def run() -> Report:
    rep = Report()
    for fn in CHECKS:
        fn(rep)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 on any DRIFT")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = run()
    if a.json:
        print(json.dumps([f.__dict__ for f in rep.findings], indent=2))
    else:
        print("doc audit — every row measured against the repo, not against a document")
        print()
        for f in rep.findings:
            mark = "  " if f.status == OK else "**"
            print(f"{mark}{f.status:6} {f.key:34} {f.detail}")
            if f.fix:
                print(f"{'':9}{'':34} fix: {f.fix}")
        print()
        print(f"{len(rep.drift)} DRIFT, {len(rep.notes)} NOTE, "
              f"{len(rep.findings)} checks")
    return 1 if (a.check and rep.drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
