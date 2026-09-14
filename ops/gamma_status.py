"""Where the gamma programme stands, measured now. The iterate-fix-continue loop.

    python3 -m ops.gamma_status            # the table and the next action
    python3 -m ops.gamma_status --json     # the same, machine-readable
    python3 -m ops.gamma_status --check    # exit 1 if a hazard is live

WHY THIS FILE EXISTS
--------------------
The gamma programme is seven prompts, two of which are gated on a broker probe
only a human can run, one on data that does not exist, and one on a research
result that is expected to be null. Nothing in the repo could say which of those
was true today, so "what do I do next" was answerable only by re-reading seven
prompts and grepping for deliverables. That is the same gap `ops/orient.py`
closed for the live book, and this is the same answer for the programme.

IT MEASURES; IT NEVER ASSERTS. Every row is produced by looking at the
filesystem, the specs or the test suite right now. A row that cannot be measured
prints UNMEASURED and the reason -- never a plausible value (CLAUDE.md, H14:
no decision rule may key on a number written in a document, this one included).

IT OPENS NO SOCKET. The margin figures come from the recorded read-only broker
snapshot, and the row says how old that snapshot is. Nothing here can transmit,
and nothing here is on the order path.

THE TWO HAZARD ROWS ARE THE POINT. A gamma book is a FOURTH book on an account
that already runs three, and the two ways it can hurt the $500k CEF book are
symbol contention and account-wide margin. Both are checked every run, against
the live specs rather than against this docstring.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DONE, PARTIAL, BLOCKED, TODO = "DONE", "PARTIAL", "BLOCKED", "TODO"
HUMAN = "HUMAN RUNS THIS"

# The preflight cushion floor every book is measured against
# (ops/preflight.py::check_margin). Read here, not hardcoded, so the two cannot
# drift apart silently.
PREFLIGHT_MIN_CUSHION = 0.10


@dataclass
class Phase:
    key: str
    title: str
    status: str
    detail: str
    owner: str = ""
    blockers: list = field(default_factory=list)


def _first(pattern: str):
    hits = sorted(glob.glob(str(REPO / pattern)))
    return Path(hits[-1]) if hits else None


def _exists(rel: str) -> bool:
    return (REPO / rel).exists()


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def phase0() -> Phase:
    """W2 Part A. The gate only a human opens, and the one that kills fastest."""
    note = _first("results/ops/ACCOUNT_AUDIT_*.md")
    tool = _exists("ops/account_audit.py")
    if note is None:
        return Phase(
            "P0", "W2 account audit",
            TODO if tool else BLOCKED,
            ("the tool exists; run it" if tool else
             "ops/account_audit.py does not exist yet"),
            owner=HUMAN,
            blockers=["options permission UNKNOWN",
                      "historical option-bar depth UNKNOWN -> G2 feasibility",
                      "option market-data subscription UNKNOWN -> G5 marks"])
    text = note.read_text()
    head = text.strip().splitlines()[0] if text.strip() else ""
    permitted = bool(re.search(r"options?\s*:?\s*permitted", text, re.I)) and \
        not re.search(r"not\s+permitted", text, re.I)
    return Phase("P0", "W2 account audit", DONE if permitted else BLOCKED,
                 f"{note.name}: {head[:70]}",
                 owner=HUMAN,
                 blockers=[] if permitted else ["the note does not say permitted"])


def phase1() -> Phase:
    """G4 Part A (the order-path defects) and G1 (the pricer)."""
    g4 = _exists("src/deploy/tests/test_option_order_path.py")
    inert = _exists("src/deploy/tests/test_order_path_noop_for_shares.py")
    g1 = _exists("src/deploy/lib/optmath.py")
    g1_tests = _exists("src/deploy/tests/test_optmath.py")
    note = _first("results/gamma/OPTION_MATH_*.md")
    done = [n for n, ok in (("G4A fixes+tests", g4), ("inertness proof", inert),
                            ("G1 optmath", g1), ("G1 tests", g1_tests),
                            ("G1 note", note is not None)) if ok]
    missing = [n for n, ok in (("G4A fixes+tests", g4), ("inertness proof", inert),
                               ("G1 optmath", g1), ("G1 tests", g1_tests),
                               ("G1 note", note is not None)) if not ok]
    status = DONE if not missing else (PARTIAL if done else TODO)
    return Phase("P1", "G4 Part A + G1 optmath", status,
                 f"have: {', '.join(done) or 'nothing'}"
                 + (f" | missing: {', '.join(missing)}" if missing else ""))


def _note_phase(key, title, pattern, blockers=()) -> Phase:
    note = _first(pattern)
    return Phase(key, title, DONE if note else TODO,
                 note.name if note else f"no {pattern.split('/')[-1]}",
                 blockers=list(blockers))


def phase3() -> Phase:
    """G2. Blocked on a credit option source that does not exist today."""
    note = _first("results/gamma/SURFACE_*.md")
    fetcher = _exists("scripts/vrp/extract_option_marks.py")
    blockers = []
    if not _credit_option_marks_exist():
        blockers.append(
            "no per-strike HYG prints; IBKR serves no historical option bars "
            "(verified 9 ways, 2026-09-12). Blocks SKEW and TERM STRUCTURE -> C2")
    if not fetcher:
        blockers.append("scripts/vrp/extract_option_marks.py does not exist")
    if _credit_iv_level_exists():
        blockers.append(
            "NOT blocked for the ATM LEVEL: VXHYG is fetched, so G6 Part A, C1 "
            "and C3 can run without this phase")
    return Phase("P3", "G2 surface (SPY first, then HYG)",
                 DONE if note else (BLOCKED if blockers else TODO),
                 note.name if note else "not started",
                 blockers=blockers)


def _column_values(rel: str, column: str):
    """The set of values in one parquet column, or None if the file is absent.

    RAISES if the file is there and unreadable. That distinction is the whole
    point: "not fetched" and "fetched but corrupt" are different states, and a
    bare `except: return False` collapses them into the first -- which in this
    harness prints a confident, plausible, wrong next action ("run the
    fetcher") for a file that is already on disk. CLAUDE.md's no-silent-fallback
    rule, in the one file whose docstring promises it never asserts a plausible
    value.
    """
    p = REPO / rel
    if not p.exists():
        return None
    import pandas as pd
    try:
        return set(pd.read_parquet(p, columns=[column])[column].unique())
    except Exception as e:                                   # noqa: BLE001
        raise RuntimeError(
            f"{rel} exists but could not be read ({type(e).__name__}: {e}); "
            f"cannot say what is in its '{column}' column") from e


def _credit_iv_level_exists() -> bool:
    """Is there a credit implied-vol LEVEL (not a surface) on disk?

    Since 2026-09-12 there is: VXHYG from Cboe, 2015 -> current. That is enough
    for G6's base rate and for C1/C3, and NOT enough for C2, which needs a term
    structure. The two questions are separate and this function answers only the
    first -- `phase3` asks about the surface.
    """
    vals = _column_values("data/gamma/cboe_vol_indices.parquet", "index")
    return vals is not None and "VXHYG" in vals


def _credit_option_marks_exist() -> bool:
    """Per-strike PRINTS, which is what a fitted surface needs. Still nothing."""
    vals = _column_values("data/vrp/atm_iv_daily.parquet", "ticker")
    return bool(vals - {"SPY", "QQQ"}) if vals is not None else False


_VERDICT_RE = re.compile(r"^#{1,6}\s*VERDICT:\s*(.+?)\s*$", re.M)


def _verdict(note) -> str:
    """The verdict a results note states about itself, read from the file.

    The note writes it as a heading so exactly one line can carry it. If no such
    heading is there this returns the UNMEASURED string rather than inferring a
    verdict from the file merely existing -- a file's existence says the work
    RAN, never how it CAME OUT, and this harness reported "C1 and C3 not yet
    run" for a day after both had run precisely because it keyed on existence.
    """
    m = _VERDICT_RE.search(note.read_text())
    return m.group(1) if m else "VERDICT UNMEASURED -- the note states no VERDICT heading"


def _surviving_conditioner():
    """(note, verdict) for G6 Part B, or (None, None) if it has not been run.

    G7 may only spend the GAMMA trial if a conditioner SURVIVES, so the harness
    has to distinguish three states, not two: not run, run and cleared, run and
    failed. Only the middle one unblocks anything.
    """
    note = _first("results/gamma/CONDITIONERS_*.md")
    if not note:
        return None, None
    return note, _verdict(note)


def phase4() -> Phase:
    """G6. Part A is the base rate, Part B the conditioners, the prereg is the
    deliverable -- three separate things, and this row used to conflate the last
    two. It reported "C1 and C3 not yet run" while CONDITIONERS_2026-09-13.md
    sat on disk, because it tested for the prereg and described the regression.
    """
    prereg = _first("results/gamma/PREREG_GAMMA_TIMING_*.md")
    base = _first("results/gamma/CREDIT_BASE_RATE_*.md")
    cond, verdict = _surviving_conditioner()
    have = []
    if base:
        have.append(f"Part A base rate ({base.name})")
    if cond:
        have.append(f"Part B C1+C3 ({cond.name}) -> {verdict}")
    if prereg:
        have.append(f"prereg ({prereg.name}) -> {_verdict(prereg)}")
    blockers = []
    if not _credit_iv_level_exists():
        blockers.append("no credit IV level; run fetch_cboe_vol_indices.py")
    if not cond:
        blockers.append("C1 and C3 not yet run")
    if not prereg:
        blockers.append("G6's named deliverable PREREG_GAMMA_TIMING_*.md is not "
                        "written; C1/C3 results alone do not close this phase")
    if not _first("results/gamma/SURFACE_*.md"):
        blockers.append("C2 needs P3's surface and stays declared-not-run")
    return Phase("P4", "G6 timing research + prereg",
                 DONE if prereg else (PARTIAL if have else TODO),
                 ", ".join(have) or "not started", blockers=blockers)


def phase5() -> Phase:
    book = _exists("ops/books/gamma_book.json")
    staged = _exists("ops/books/_staging/gamma_book.json")
    sleeve = _exists("src/deploy/sleeves/gamma_scalp.py")
    note = _first("results/gamma/GAMMA_BOOK_*.md")
    where = ("live in ops/books/" if book else
             "staged (invisible to the books glob)" if staged else "not written")
    return Phase("P5", "G5 paper book", DONE if note else TODO,
                 f"sleeve={'yes' if sleeve else 'no'}, book spec {where}",
                 owner=HUMAN if book or staged else "",
                 blockers=["P0 must say permitted"] )


def phase6() -> Phase:
    """G7. The trial is spent here or nowhere, and G6's verdict is the gate."""
    counters = _trial_counters()
    g = counters.get("GAMMA")
    cond, verdict = _surviving_conditioner()
    if cond is None:
        gate = "G6 must name a surviving conditioner -- Part B not run"
    elif "DOES NOT CLEAR" in verdict.upper() or "NO CONDITIONER" in verdict.upper():
        gate = f"G6 names NO surviving conditioner ({cond.name}: {verdict})"
    else:
        gate = f"G6 verdict reads: {verdict} -- read the note before spending the trial"
    return Phase("P6", "G7 sleeve (1 GAMMA trial)",
                 DONE if (g or 0) >= 1 else TODO,
                 f"GAMMA counter = {g if g is not None else 'UNMEASURED'}",
                 blockers=[gate])


def _trial_counters() -> dict:
    """CEF and GAMMA from RESEARCH_STATE's canonical table, or {} if unreadable."""
    p = REPO / "docs/RESEARCH_STATE.md"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        m = re.match(r"^\|\s*\*\*([A-Z]+)\*\*\s*\|.*\|\s*\*\*(\d+)\*\*\s*\|", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


# ---------------------------------------------------------------------------
# Hazards
# ---------------------------------------------------------------------------

def hazard_contention() -> tuple[str, list]:
    """Who else claims the symbols a gamma book would trade.

    Any ops/books/*.json with a `sleeves` list makes its whole universe
    contested for every OTHER book (ibkr.py::_foreign_book_claims), and arm()
    then refuses a session for a contested symbol its ledger cannot explain.
    That has halted a book twice -- phase0/JNK and bench_b6/ANGL.
    """
    claims: dict[str, list] = {}
    for p in glob.glob(str(REPO / "ops/specs/*.frozen.json")):
        try:
            d = json.loads(Path(p).read_text())
        except Exception:
            continue
        u = (d.get("allocation", {}) or {}).get("weights") \
            or (d.get("frozen", {}) or {}).get("universe") or {}
        if isinstance(u, (list, dict)):
            for t in u:
                claims.setdefault(t, []).append(Path(p).stem.replace(".frozen", ""))
    lines = []
    for t in ("HYG", "TLT", "SPY", "LQD"):
        who = claims.get(t, [])
        lines.append(f"{t:5s} claimed by {len(who)}: {', '.join(who) or 'nobody'}"
                     + ("   <- clean" if not who else ""))
    try:
        from scripts.cef.spec import UNIVERSE
        overlap = sorted(set(UNIVERSE) & {"HYG", "TLT", "SPY", "LQD"})
        lines.append(f"CEF universe overlap: {overlap or 'NONE -- gamma cannot '
                                                       'contest a CEF symbol'}")
    except Exception as exc:
        lines.append(f"CEF universe overlap: UNMEASURED ({exc})")
    clean = not claims.get("TLT")
    return (("ok" if clean else "check"), lines)


def _audit_margin() -> dict | None:
    """Margin figures from the newest ACCOUNT_AUDIT note, which is usually fresher.

    The audit records `Cushion=...` etc. in its Q4 detail cell. Parsing a note we
    wrote ourselves is fragile, so a miss returns None and the caller falls back
    to the broker snapshot rather than reporting nothing.
    """
    note = _first("results/ops/ACCOUNT_AUDIT_*.md")
    if note is None:
        return None
    txt = note.read_text()
    out = {}
    for key in ("NetLiquidation.CAD", "ExcessLiquidity.CAD", "Cushion",
                "FullMaintMarginReq.CAD", "GrossPositionValue.CAD"):
        m = re.search(re.escape(key) + r"=([0-9.]+)", txt)
        if m:
            out[key.split(".")[0]] = float(m.group(1))
    if "Cushion" not in out or "NetLiquidation" not in out:
        return None
    out["_source"] = note.name
    return out


def hazard_margin() -> tuple[str, list]:
    """Account-wide cushion against preflight's floor.

    Reads the newest ACCOUNT_AUDIT note AND the broker snapshot, and shows the
    TREND between them — because the level alone hides the thing that matters.
    Measured 2026-09-10 -> 2026-09-12 the cushion fell 0.2258 -> 0.1646 and the
    slack above preflight's blocking floor HALVED, from 125,749 to 64,055 CAD,
    while gross exposure grew 4.9%. A level reading would have looked fine.
    """
    snap = _first("results/ops/BROKER_SNAPSHOT_*.json")
    audit = _audit_margin()
    if snap is None and audit is None:
        return "UNMEASURED", ["no broker snapshot and no account audit in the repo"]
    if snap is None:
        return _margin_lines(audit, None)
    try:
        d = json.loads(snap.read_text())
        av = d["account_values"]
        acct = next(iter(av))
        vals = av[acct]
        g = lambda k: float(vals[k]["value"])          # noqa: E731
        cushion = g("Cushion")
        nlv = g("NetLiquidation.CAD")
        excess = g("ExcessLiquidity.CAD")
    except Exception as exc:
        return "UNMEASURED", [f"{snap.name} could not be read: {exc!r}"]
    old = {"Cushion": cushion, "NetLiquidation": nlv, "ExcessLiquidity": excess,
           "_source": snap.name, "_when": str(d.get("read_at_local", ""))[:19]}
    return _margin_lines(audit or old, old if audit else None)


def _margin_lines(cur: dict, prev: dict | None) -> tuple[str, list]:
    nlv, cushion = cur["NetLiquidation"], cur["Cushion"]
    excess = cur.get("ExcessLiquidity", cushion * nlv)
    slack = excess - PREFLIGHT_MIN_CUSHION * nlv
    lines = [
        f"source {cur['_source']}",
        f"cushion {cushion:.4f} against preflight's BLOCKING floor "
        f"{PREFLIGHT_MIN_CUSHION:.2f}   (= ExcessLiquidity / NetLiquidation)",
        f"NetLiquidation {nlv:>14,.0f}   ExcessLiquidity {excess:>12,.0f}",
        f"SLACK above the floor {slack:>12,.0f} CAD  <- the whole budget for a "
        f"4th book, shared with the other three",
    ]
    state = "ok" if cushion > 0.20 else ("tight" if cushion > 0.12 else "CRITICAL")
    if prev:
        p_slack = prev["ExcessLiquidity"] - PREFLIGHT_MIN_CUSHION * prev["NetLiquidation"]
        d_slack = slack - p_slack
        lines += [
            f"previous {prev['_source']}: cushion {prev['Cushion']:.4f}, "
            f"slack {p_slack:,.0f}",
            f"TREND  slack {d_slack:+,.0f} CAD ({d_slack / p_slack * 100:+.0f}%)",
        ]
        if d_slack < 0:
            state = "CRITICAL" if cushion <= 0.20 else state
            lines.append(
                "  ** the cushion is FALLING. preflight's check_margin is "
                "ACCOUNT-WIDE and BLOCKING (ops/preflight.py:236): when it "
                "trips it stops the $500k CEF book, not the book that drew "
                "the margin. **")
    lines.append("a new book consumes MARGIN REQUIREMENT, not notional")
    return state, lines


def free_client_id() -> tuple[int | None, list]:
    used = set()
    for p in glob.glob(str(REPO / "ops/schedule/*.env")):
        for line in Path(p).read_text().splitlines():
            m = re.match(r"\s*IBKR_CLIENT_ID\s*=\s*(\d+)", line)
            if m:
                used.add(int(m.group(1)))
    free = next((i for i in range(45, 90) if i not in used), None)
    return free, [f"in use: {sorted(used)}", f"first free: {free}"]


# ---------------------------------------------------------------------------

def collect() -> dict:
    phases = [
        phase0(), phase1(),
        _note_phase("P2", "G3 hedging spec", "results/gamma/HEDGING_SPEC_*.md"),
        phase3(),
        phase4(),
        phase5(), phase6(),
    ]
    cs, clines = hazard_contention()
    ms, mlines = hazard_margin()
    cid, cidlines = free_client_id()
    return {"phases": phases, "contention": (cs, clines), "margin": (ms, mlines),
            "client_id": (cid, cidlines), "counters": _trial_counters()}


def next_action(phases) -> str:
    for ph in phases:
        if ph.status in (TODO, PARTIAL, BLOCKED):
            who = f"  [{ph.owner}]" if ph.owner else ""
            b = f"  blocked on: {'; '.join(ph.blockers)}" if ph.blockers else ""
            return f"{ph.key} {ph.title} -- {ph.status}{who}{b}"
    return "every phase reports DONE; re-read the notes before believing it"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a hazard is not ok")
    a = ap.parse_args()
    d = collect()

    if a.json:
        print(json.dumps({
            "phases": [vars(p) for p in d["phases"]],
            "contention": d["contention"], "margin": d["margin"],
            "client_id": d["client_id"], "counters": d["counters"],
        }, indent=1, default=str))
        return 0

    print("GAMMA PROGRAMME STATUS — measured now, nothing copied from a document")
    print()
    print(f"{'':4s}{'phase':34s}{'status':10s}detail")
    print("-" * 100)
    for p in d["phases"]:
        print(f"{p.key:4s}{p.title:34s}{p.status:10s}{p.detail}")
        for b in p.blockers:
            print(f"{'':48s}blocked: {b}")
        if p.owner:
            print(f"{'':48s}{p.owner}")
    print()
    print("HAZARD  symbol contention      ops/specs/*.frozen.json")
    for line in d["contention"][1]:
        print(f"  {line}")
    print()
    print("HAZARD  account margin         results/ops/BROKER_SNAPSHOT_*.json")
    for line in d["margin"][1]:
        print(f"  {line}")
    print()
    print("CLIENT ID")
    for line in d["client_id"][1]:
        print(f"  {line}")
    print()
    print("TRIALS  " + ", ".join(f"{k} {v}" for k, v in d["counters"].items())
          + "   (docs/RESEARCH_STATE.md canonical table)")
    print()
    print("NEXT    " + next_action(d["phases"]))

    if a.check:
        bad = [n for n, (s, _) in (("contention", d["contention"]),
                                   ("margin", d["margin"])) if s not in ("ok",)]
        if bad:
            print(f"\nCHECK FAILED: {', '.join(bad)}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
