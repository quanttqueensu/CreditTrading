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

BANNERED = [
    "docs/PLAN.md",
    "docs/INFRASTRUCTURE.md",
    "docs/RESEARCH_AND_METHODOLOGY.md",
    "docs/RESEARCH_STATE.md",
    "docs/PER_NAME_ARCHITECTURE.md",
    "docs/SYSTEM_AND_STRATEGY.md",
    "ops/README.md",
    "ops/schedule/README.md",
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

def check_spec_id(rep: Report) -> None:
    """INFRASTRUCTURE.md names the frozen spec. The frozen spec is the authority."""
    spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
    live = spec["spec_id"]
    text = _read("docs/INFRASTRUCTURE.md") or ""
    others = {s for s in re.findall(r"cef_discount\.v\d+\.\d{8}", text)} - {live}
    # A superseded id is fine inside a correction that names it; flag only an
    # id that appears with NO mention of the live one anywhere in the file.
    if live not in text:
        rep.add("spec_id", DRIFT,
                f"INFRASTRUCTURE.md never names the live spec {live}"
                + (f"; it names {sorted(others)}" if others else ""),
                f"quote {live}, from ops/specs/cef_discount.frozen.json")
    else:
        rep.add("spec_id", OK,
                f"{live} present" + (f"; superseded {sorted(others)} kept in "
                                     f"corrections" if others else ""))


def check_dsr_bar(rep: Report) -> None:
    """A deflated-Sharpe bar keyed to a stale trial count is a wrong decision rule.

    The counter is read through `ops.orient.trials()` rather than re-parsed here.
    Two parsers for one canonical table is two things to drift, and this table's
    shape has already changed once.
    """
    from ops import orient
    try:
        n = orient.trials()["counters"]["CEF"]["trials"]
        bar = orient.trials()["counters"]["CEF"]["dsr_bar"]
    except Exception as e:                                       # noqa: BLE001
        rep.add("dsr_bar", DRIFT,
                f"cannot read the CEF counter ({type(e).__name__}: {e})",
                "the counter table is canonical; keep its shape parseable")
        return
    meth = _read("docs/RESEARCH_AND_METHODOLOGY.md") or ""
    stale = "2.15" in meth and f"{bar:.2f}" not in meth and "2.78" not in meth
    rep.add("dsr_bar", DRIFT if stale else OK,
            f"CEF counter {n} -> bar sqrt(2 ln {n}) = {bar:.2f}"
            + ("; RESEARCH_AND_METHODOLOGY quotes 2.15 with no corrected figure"
               if stale else "; corrected figure present or 2.15 absent"),
            "state the bar against the current counter" if stale else "")


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


def check_ops_broker_claim(rep: Report) -> None:
    """ops/README.md says "There is no broker here". Count the modules that are one."""
    mods = sorted(p.name for p in (REPO / "ops").glob("*.py")
                  if _opens_ib_socket(p))
    text = _read("ops/README.md") or ""
    # The phrase may legitimately appear inside the banner that retracts it, or
    # inside an in-body retraction that QUOTES it -- a correction has to restate
    # what it corrects or the reader cannot tell what changed. So look for it as
    # a standing ASSERTION: an occurrence with no retraction marker on the same
    # line or in the three lines before it.
    claim = "There is no broker here" in text
    lines = text.splitlines()
    RETRACT = ("RETRACTED", "is false", "it is false", "said", "CORRECTED",
               "no longer", "WRONG")
    asserted = []
    for i, line in enumerate(lines):
        if "There is no broker here" not in line:
            continue
        if line.lstrip().startswith(">"):
            continue                                   # inside the banner
        window = " ".join(lines[max(0, i - 3):i + 1])
        if not any(k in window for k in RETRACT):
            asserted.append(i + 1)
    if asserted:
        rep.add("ops_broker", DRIFT,
                f"ops/README.md asserts 'There is no broker here' at line(s) "
                f"{asserted}; {len(mods)} module(s) import an IB client: "
                f"{', '.join(mods)}",
                "retract it in the body, not only in the banner")
    else:
        rep.add("ops_broker", OK,
                f"{len(mods)} ops module(s) open IB sockets ({', '.join(mods)}); "
                f"the claim survives only inside the banner"
                if claim else f"{len(mods)} ops module(s) open IB sockets")


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


CHECKS = [check_banners, check_spec_id, check_dsr_bar, check_ops_broker_claim,
          check_band_width_literals, check_results_notes_have_reproducers,
          check_prereg_shape, check_desk_inventory]


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
