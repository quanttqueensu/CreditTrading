#!/usr/bin/env python3
"""One command that tells a new agent where it is and what is true RIGHT NOW.

    python3 -m ops.orient              # the readout
    python3 -m ops.orient --json       # machine-readable
    python3 -m ops.orient --no-tests   # skip the pytest collection count

WHY THIS FILE EXISTS
--------------------
`CLAUDE.md` is loaded into every agent's context, and by 2026-09-11 roughly a
third of it was archaeology of its own wrong numbers: "3 of 26" corrected to
"5 of 29"; a test count that read 126, then 271, then 211 inside 24 hours; a
`0.064` literal count that said four and missed three including the one in its
own new file; a table asserting its own remedy was applied when it was not, and
later that it was missing when it was not. Each correction was itself a fact
with a shelf life, so the file grew by the square of its own staleness.

Every one of those passages already carried the command that settles it. The
commands were just scattered across 473 lines, so nobody ran all of them and the
prose kept being the cheaper thing to read. This module runs them.

THE HOUSE RULE THIS SERVES (CLAUDE.md, H14)
-------------------------------------------
"No decision rule may key on a number written in a document. Every figure in
these docs is a dated observation with a method, not an input." A document
cannot follow that rule on its own behalf -- a written number is a written
number. A command can. So the intended end state is that `CLAUDE.md` keeps the
RULES, which do not rot, and points here for the FIGURES, which do.

Accordingly: every line of output below names the reproducer that produced it,
and nothing here is a constant. The one exception is labelled `[doc]` -- the
trial counter, which the repo deliberately keeps canonical in prose because it
counts human decisions and no code can observe it. It is shown with its source
file so that it reads as a citation and not as a measurement.

NO SILENT FALLBACKS, AND WHAT THAT MEANS FOR A READ-ONLY REPORT
---------------------------------------------------------------
Each section is independently guarded, and a section that cannot measure prints
`UNMEASURED` with the exception that stopped it. That is the opposite of a
fallback: it is a named gap, and the repo's rule is "raise, naming what was
missing". A monitor that aborts the whole readout because one panel is absent
tells you less than one that reports nine facts and one gap, and an orientation
tool that invented a plausible value for the tenth would be the exact failure
this desk has paid for most often.

TRANSMITS NOTHING. Reads files and runs `git`, `pytest --collect-only` and two
read-only sibling modules. No broker socket is opened anywhere in this path, and
none of the modules it imports opens one at import time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Same convention as ops/session_uptime.py:114 and .claude/hooks/book_state.py.
PROD_TREE = Path.home() / "prod" / "QUANTT"

RESEARCH_STATE = REPO / "docs/RESEARCH_STATE.md"
PANELS = {
    "cef_prices": REPO / "data/cef/cef_prices.parquet",
    "cef_nav": REPO / "data/cef/cef_nav.parquet",
}


class Unmeasured(Exception):
    """Raised by a section that cannot honestly produce its number."""


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> str:
    r = subprocess.run(cmd, cwd=cwd or REPO, capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0 and not r.stdout.strip():
        raise Unmeasured(f"{' '.join(cmd[:3])}… rc={r.returncode}: "
                         f"{r.stderr.strip()[:120]}")
    return r.stdout


def _trading_days_since(d: dt.date) -> int | None:
    try:
        from ops.schedule import nyse_calendar as cal
        n, cur = 0, d
        today = dt.date.today()
        while cur < today and n < 2000:
            cur += dt.timedelta(days=1)
            if cal.is_trading_day(cur):
                n += 1
        return n
    except Exception:
        return None


# ------------------------------------------------------------------- trees --
def trees() -> dict:
    """Which worktree is which, and what prod is actually detached at.

    `git worktree list` is the only command that shows this. Prod is a detached
    worktree, so it will NEVER appear in `git branch` -- which is exactly why
    the team lead asked "what is prod/dev? i dont see it on the git" after
    reading three documents that each named the concept and none of which gave
    the command.
    """
    out = {"reproducer": "git worktree list", "dev": {}, "prod": {}}
    out["dev"] = {
        "path": str(REPO),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip(),
        "sha": _run(["git", "rev-parse", "--short", "HEAD"]).strip(),
        "uncommitted": len([l for l in _run(
            ["git", "status", "--porcelain"]).splitlines() if l.strip()]),
    }
    if not PROD_TREE.is_dir():
        out["prod"] = {"path": str(PROD_TREE), "present": False}
        return out
    out["prod"] = {
        "path": str(PROD_TREE),
        "present": True,
        "sha": _run(["git", "-C", str(PROD_TREE), "rev-parse",
                     "--short", "HEAD"]).strip(),
    }
    try:
        out["prod"]["tag"] = _run(
            ["git", "-C", str(PROD_TREE), "describe", "--tags"]).strip()
    except Unmeasured as exc:
        out["prod"]["tag"] = f"UNMEASURED ({exc})"
    # data/ is a symlink from prod back to dev, deliberately and temporarily:
    # a research script in dev can still corrupt what the live sleeve prices
    # from. `ops/sync_dev_data.sh` reverses it once prod owns the panels.
    d = PROD_TREE / "data"
    out["prod"]["data_symlink"] = str(d.resolve()) if d.is_symlink() else None
    try:
        out["delta"] = tree_delta(out["prod"]["sha"], "HEAD")
    except Unmeasured as exc:
        out["delta"] = {"UNMEASURED": str(exc)}
    return out


def tree_delta(prod: str, dev: str, cwd: Path | None = None,
               show: int = 8) -> dict:
    """What dev has that prod does not, and the reverse. Measured, never written.

    Every document that said what prod runs was wrong within a day of being
    written: "prod is detached at v2026.09.10.1" stood in CLAUDE.md while prod
    had moved twice, and "the morning session is planned, not built" stood while
    it was committed in dev and not yet promoted. "Is this fix live?" is a git
    question, so it gets a git answer. The two trees share one object store, so
    this needs no network and no prod checkout.

    `dev_lacks` is normally zero. When it is not, prod carries commits dev does
    not (a hotfix tag cut off the prod tag), and a promotion from dev would
    silently drop them -- which is the case worth printing.
    """
    rng = f"{prod}..{dev}"
    lacks = int(_run(["git", "rev-list", "--count", rng], cwd=cwd).strip())
    behind = int(_run(["git", "rev-list", "--count", f"{dev}..{prod}"],
                      cwd=cwd).strip())
    subjects = [l for l in _run(["git", "log", "--oneline", f"-{show}", rng],
                                cwd=cwd).splitlines() if l.strip()]
    return {"reproducer": f"git log --oneline {rng}",
            "prod_lacks": lacks, "dev_lacks": behind, "newest": subjects}


# ------------------------------------------------------------------- halts --
def halts() -> dict:
    """Every halt file active in EITHER tree. Halts are WRITTEN IN PROD and are
    untracked, so `ls ops/HALT*.md` in dev returns nothing while the book is
    halted -- the trap this section exists to close."""
    sys.path.insert(0, str(REPO / ".claude/hooks"))
    import book_state
    h = book_state.halted()
    return {"reproducer": "ls ~/prod/QUANTT/ops/HALT*.md  ·  "
                          "python3 .claude/hooks/book_state.py -p",
            "global": {"active": h["active"], "reason": h.get("reason")},
            "scoped": h.get("scoped") or [],
            "trees_read": h.get("trees_read") or []}


# -------------------------------------------------------------------- book --
def book() -> dict:
    sys.path.insert(0, str(REPO / ".claude/hooks"))
    import book_state
    s = book_state.collect()
    hb = {k: v.get("status") for k, v in (s.get("heartbeat") or {}).items()
          if isinstance(v, dict) and v.get("status") not in (None, "ok")}
    return {"reproducer": "python3 .claude/hooks/book_state.py -p",
            "fills": s.get("fills") or {},
            "last_session": s.get("today") or {},
            "heartbeat_not_ok": hb,
            "ledger_nav": s.get("ledger") or {}}


# ------------------------------------------------------------------ uptime --
def uptime() -> dict:
    """Delegated whole to `ops.session_uptime`, which reads BOTH log trees.

    Not recomputed here. Three different figures for this one quantity were in
    circulation inside two days because it was being hand-tallied with shell
    one-liners against a single tree; a second implementation is how that
    happens again.
    """
    d = json.loads(_run([sys.executable, "-m", "ops.session_uptime", "--json"]))
    return {"reproducer": d.get("reproducer", "python3 -m ops.session_uptime"),
            "complete": d.get("complete"),
            "n_eligible": d.get("n_eligible"), "n_armed": d.get("n_armed"),
            "n_clean": d.get("n_clean"), "arm_rate_pct": d.get("arm_rate_pct"),
            "streak_clean": d.get("streak_clean"),
            "target": d.get("target_consecutive"),
            "target_met": d.get("target_met"),
            "window": d.get("window"), "trees": d.get("trees")}


# -------------------------------------------------------------------- spec --
def spec() -> dict:
    """Read through `scripts/cef/spec.py`, the single reader of that JSON."""
    sys.path.insert(0, str(REPO / "scripts/cef"))
    import importlib
    sp = importlib.import_module("spec")
    return spec_fields(sp.spec())


def spec_fields(s: dict) -> dict:
    """The live spec's decision-relevant keys, with ABSENT kept distinct from a value.

    `vol_target_annual` is here because documents disagreed about the vol
    target while the spec held one number: "we target 6%" in three places, "the
    20% cap" in two, and neither said which the sleeve actually reads. When the
    key is missing this reports None and says the sleeve's own default applies
    -- it does not print that default, because a number shown here gets quoted
    as the spec's, and a code default is not a governance decision.
    """
    fr = s.get("frozen", {})
    return {"reproducer": "python3 -c \"import sys; sys.path.insert(0,"
                          "'scripts/cef'); import spec; print(spec.summary())\"",
            "spec_id": s.get("spec_id"), "status": s.get("status"),
            "vol_target_annual": fr.get("vol_target_annual"),
            "vol_target_absent": "vol_target_annual" not in fr,
            "capital_usd": s.get("capital_usd"),
            "band_width": fr.get("band_width"),
            "rebalance_days": fr.get("rebalance_days"),
            "rebalance_days_inert": fr.get("band_width") is not None,
            "z_window": fr.get("z_window"),
            "order_type": fr.get("order_type"),
            "n_universe": len(fr.get("universe") or []),
            "min_trade_usd": (s.get("rebalance") or {}).get("min_trade_usd")}


# ------------------------------------------------------------------ trials --
def trials() -> dict:
    """The ONLY figure here read from a document, and labelled as such.

    A trial counter counts human decisions to test something. No code can
    observe it, so the repo keeps it canonical in one table
    (`docs/RESEARCH_STATE.md`) and requires it to be updated in the same commit
    as the trial. It is cited here, with its file, rather than measured -- and
    the deflated-Sharpe bar sqrt(2 ln N) is DERIVED from it live, because that
    bar was wrong in three documents at once when it was written out by hand.
    """
    import math
    if not RESEARCH_STATE.exists():
        raise Unmeasured(f"{RESEARCH_STATE} is missing")
    text = RESEARCH_STATE.read_text(errors="replace")
    rows = re.findall(r"^\|\s*\*\*([A-Z]+)\*\*\s*\|[^|]*\|\s*\*\*(\d+)\*\*\s*\|",
                      text, re.M)
    if not rows:
        raise Unmeasured("no canonical counter rows matched in "
                         f"{RESEARCH_STATE.name}; the table format changed")
    counters = {}
    for name, n in rows:
        n = int(n)
        counters[name] = {"trials": n,
                          "dsr_bar": round(math.sqrt(2 * math.log(n)), 3)
                          if n > 1 else None}
    return {"reproducer": f"grep -nE '^\\| \\*\\*[A-Z]+\\*\\*' "
                          f"docs/{RESEARCH_STATE.name}   [doc, not measured]",
            "source": f"docs/{RESEARCH_STATE.name} (canonical counter table)",
            "counters": counters}


# ------------------------------------------------------------------ panels --
def panels() -> dict:
    """Last date in each panel the live sleeve prices from. Stale is a form of
    wrong, and several panels in this repo lag by weeks."""
    import pandas as pd
    out = {"reproducer": "python3 -c \"import pandas as pd; "
                         "print(pd.read_parquet(P)['date'].max())\"",
           "panels": {}}
    for name, path in PANELS.items():
        if not path.exists():
            out["panels"][name] = {"last": None,
                                   "error": f"missing: {path}"}
            continue
        df = pd.read_parquet(path, columns=["date"])
        last = pd.to_datetime(df["date"]).max().date()
        out["panels"][name] = {"last": last.isoformat(),
                               "trading_days_old": _trading_days_since(last)}
    return out


# ----------------------------------------------------------------- hygiene --
def hygiene(run_tests: bool = True) -> dict:
    """The greps CLAUDE.md asks a reader to run before believing its prose.

    Each of these has been quoted wrongly in that file at least once. They are
    cheap, so the answer should be produced rather than remembered.
    """
    out = {"checks": {}}

    lits = [l for l in _run(
        ["grep", "-rn", r"0\.064", "--include=*.py", "scripts/cef"]
    ).splitlines() if l.strip()]
    out["checks"]["band_width_literals"] = {
        "reproducer": r"grep -rn '0\.064' --include=*.py scripts/cef",
        "count": len(lits),
        "lines": [l.split(":", 2)[0] + ":" + l.split(":", 2)[1] for l in lits],
        "rule": "read band_width from the frozen spec; never write the literal. "
                "Some hits are legitimate (sweep grids, historical comments) — "
                "the COUNT is what keeps rotting, so read the lines, not this."}

    bad = _unguarded_ib_insync()
    out["checks"]["ib_insync_unguarded"] = {
        "reproducer": "python3 -m ops.orient --json   (AST, not grep — see "
                      "_unguarded_ib_insync)",
        "count": len(bad), "lines": bad,
        "rule": "ib_insync hangs forever in its asyncio handshake on Python "
                "3.12+ and looks exactly like a dead broker connection. The "
                "safe shape is `try: ib_async / except ImportError: ib_insync`."}

    if run_tests:
        txt = _run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                   timeout=180)
        # `-q --collect-only` emits one `path: N` line per file and NO total.
        # Summing them is the whole parse; there is no "N tests collected" line
        # to regex for, and a regex that finds nothing must not silently become
        # a zero.
        per_file = re.findall(r"^\S+\.py: (\d+)$", txt, re.M)
        out["checks"]["tests_collected"] = {
            "reproducer": "python3 -m pytest --collect-only -q",
            "count": sum(int(n) for n in per_file) if per_file else None,
            "n_files": len(per_file) or None,
            "rule": "A green suite says nothing about the code that places "
                    "orders. Write a test with any change to the live path."}
        if not per_file:
            out["checks"]["tests_collected"]["UNMEASURED"] = (
                "pytest --collect-only -q produced no `path: N` lines; its "
                "output format changed and this parse needs updating")
    return out


def _unguarded_ib_insync(root: Path | None = None) -> list[str]:
    """`ib_insync` imports that do NOT sit behind an `ib_async` preference.

    WHY THIS IS AN AST WALK AND NOT THE GREP `CLAUDE.md` PRESCRIBES
    ---------------------------------------------------------------
    That file says to check with

        grep -rn '^ *from ib_insync' ops/ src/ scripts/ | grep -v ImportError

    and asserts the answer is zero. Run it on 2026-09-11 and it returns FIVE,
    because the `except ImportError:` that makes an import safe is on a
    DIFFERENT LINE from the import itself, so `grep -v ImportError` filters
    nothing. The recipe cannot express the property it is checking.

    The real answer that day was TWO -- `scripts/rv/measure_rth_liquidity.py`
    and `scripts/rv/probe_ibkr_spreads.py` both do `try: from ib_insync ...`
    with no `ib_async` attempt first, so on this machine's Python 3.13.5 they
    hang rather than fall back. Three others are correctly guarded. A check
    that says 5 and a document that says 0 are both useless in the same way:
    neither tells you which files to open.

    So: find every ib_insync import, then subtract those reached only as the
    ImportError fallback of a try whose body imports ib_async.
    """
    import ast
    root = root or REPO
    found: list[str] = []
    for d in ("ops", "src", "scripts"):
        if not (root / d).is_dir():
            continue
        for path in sorted((root / d).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(errors="replace"))
            except SyntaxError:
                continue

            def imports(node, mod: str) -> list[ast.AST]:
                hits = []
                for n in ast.walk(node):
                    if isinstance(n, ast.ImportFrom) and (n.module or "") == mod:
                        hits.append(n)
                    elif isinstance(n, ast.Import):
                        if any(a.name.split(".")[0] == mod for a in n.names):
                            hits.append(n)
                return hits

            guarded: set[int] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                # the try body must PREFER ib_async ...
                if not any(imports(s, "ib_async") for s in node.body):
                    continue
                for h in node.handlers:
                    names = []
                    if isinstance(h.type, ast.Name):
                        names = [h.type.id]
                    elif isinstance(h.type, ast.Tuple):
                        names = [e.id for e in h.type.elts
                                 if isinstance(e, ast.Name)]
                    elif h.type is None:
                        names = ["ImportError"]  # bare except catches it
                    if "ImportError" not in names:
                        continue
                    # ... and ib_insync must be the FALLBACK, not the first try
                    for s in h.body:
                        for hit in imports(s, "ib_insync"):
                            guarded.add(hit.lineno)

            for hit in imports(tree, "ib_insync"):
                if hit.lineno not in guarded:
                    found.append(f"{path.relative_to(root)}:{hit.lineno}")
    return found


# -------------------------------------------------------------------- docs --
def doc_drift() -> dict:
    """Delegated to `ops.prompt_status`, which derives each work order's real
    status from the repo and checks the hand-typed index against it."""
    r = subprocess.run([sys.executable, "-m", "ops.prompt_status", "--json"],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    d = json.loads(r.stdout) if r.stdout.strip() else {}
    findings = d.get("findings") or []
    out = {"reproducer": "python3 -m ops.prompt_status --check  ·  "
                         "python3 -m ops.doc_audit --check",
           "n_findings": len(findings),
           "findings": [f for f in findings][:5]}
    # The document audit, run as a subprocess for the same reason as above: it
    # imports this module, and a report that imports its own auditor in-process
    # is one refactor from a cycle.
    r = subprocess.run([sys.executable, "-m", "ops.doc_audit", "--json"],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    try:
        rows = json.loads(r.stdout)
        drift = [f"{x['key']}: {x['detail']}" for x in rows
                 if x.get("status") in ("DRIFT", "GONE")]
        out["doc_audit_drift"] = len(drift)
        out["doc_audit_rows"] = drift[:5]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        out["doc_audit_drift"] = (f"UNMEASURED ({type(exc).__name__}; "
                                  f"rc={r.returncode} {r.stderr.strip()[:80]})")
    return out


# ------------------------------------------------------------------ render --
SECTIONS = [
    ("TREES", trees), ("HALTS", halts), ("BOOK", book), ("UPTIME", uptime),
    ("SPEC", spec), ("TRIALS", trials), ("PANELS", panels),
    ("HYGIENE", hygiene), ("DOC DRIFT", doc_drift),
]


def collect(run_tests: bool = True) -> dict:
    out = {"measured_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "running_in": str(REPO), "sections": {}}
    for name, fn in SECTIONS:
        try:
            out["sections"][name] = (fn(run_tests=run_tests)
                                     if fn is hygiene else fn())
        except Exception as exc:
            out["sections"][name] = {
                "UNMEASURED": f"{type(exc).__name__}: {exc}"}
    return out


LABEL_W = 30


def _p(label: str, value: str = "") -> None:
    """Pad, but never TRUNCATE a label into the value column: a check name
    that collides with its own number is how a readout starts lying."""
    print(f"  {label:<{LABEL_W}}{value}" if len(label) <= LABEL_W
          else f"  {label}\n  {'':<{LABEL_W}}{value}")


def render(d: dict) -> None:
    print(f"\nQUANTT ORIENTATION — measured {d['measured_at']}")
    print("Every figure below was produced just now by the reproducer named "
          "beside it.\nNothing here is copied from a document except the line "
          "marked [doc].\n")

    s = d["sections"]

    def head(name: str) -> dict | None:
        sec = s.get(name) or {}
        if "UNMEASURED" in sec:
            print(f"{name}\n  UNMEASURED — {sec['UNMEASURED']}\n")
            return None
        print(f"{name:<22}{sec.get('reproducer', '')}")
        return sec

    if (sec := head("TREES")) is not None:
        dv, pr = sec["dev"], sec["prod"]
        _p("dev  (you are here)", f"{dv['path']}  {dv['branch']} {dv['sha']}"
                                  f"  {dv['uncommitted']} uncommitted")
        if pr.get("present"):
            _p("prod (what trades)", f"{pr['path']}  {pr.get('tag')} "
                                     f"{pr.get('sha')} (detached)")
            if pr.get("data_symlink"):
                _p("data/", f"prod -> {pr['data_symlink']}  (SHARED: a research "
                            "script can corrupt what the sleeve prices from)")
            dl = sec.get("delta") or {}
            if "UNMEASURED" in dl:
                _p("prod lacks", f"UNMEASURED — {dl['UNMEASURED']}")
            elif dl:
                _p("prod lacks", f"{dl['prod_lacks']} commit(s) in dev   "
                                 f"({dl['reproducer']})")
                for line in dl["newest"]:
                    _p("", f"  {line[:96]}")
                if dl["prod_lacks"] > len(dl["newest"]):
                    _p("", f"  … {dl['prod_lacks'] - len(dl['newest'])} more")
                if dl["dev_lacks"]:
                    _p("dev lacks", f"{dl['dev_lacks']} commit(s) that prod has "
                                    "— a promotion from dev would DROP them")
        else:
            _p("prod", f"{pr['path']} — NOT PRESENT on this machine")
        print()

    if (sec := head("HALTS")) is not None:
        g = sec["global"]
        _p("global", f"HALT ACTIVE — {g['reason']}" if g["active"]
           else "none — no global halt in either tree")
        for sc in sec["scoped"]:
            _p(f"scoped: {sc['book']}", f"BLOCKED — {(sc.get('reason') or '')[:90]}")
            _p("", f"  {sc['path']}")
        if not sec["scoped"]:
            _p("scoped", "none")
        print()

    if (sec := head("BOOK")) is not None:
        f = sec["fills"]
        gap = f.get("gap_sessions")
        _p("last broker-confirmed fill",
           f"{f.get('date')}  ({gap} trading day(s) ago)"
           f"{'  <-- STALE' if (gap or 0) >= 3 else ''}")
        _p("", f"{f.get('n_sessions')} session(s), {f.get('n_fills')} executions"
               f"   [{f.get('tree')}]")
        by = f.get("by_date") or {}
        if by:
            _p("executions by fill date", "   ".join(
                f"{d} {n}" for d, n in list(by.items())[-6:]))
        ls = sec["last_session"]
        _p("last CEF session log", f"{ls.get('date')} armed={ls.get('armed')} "
                                   f"status={ls.get('status')}")
        if sec["heartbeat_not_ok"]:
            _p("heartbeat not ok", str(sec["heartbeat_not_ok"]))
        nav = sec["ledger_nav"]
        if nav.get("nav"):
            _p("shadow-ledger NAV", f"${nav['nav']:,.0f} as of {nav.get('date')}"
                                    "  (indicative; the account is the fact)")
        print()

    if (sec := head("UPTIME")) is not None:
        _p("armed", f"{sec['n_armed']} of {sec['n_eligible']} eligible sessions "
                    f"({sec['arm_rate_pct']}%)   clean {sec['n_clean']}")
        _p("clean streak", f"{sec['streak_clean']} / {sec['target']}   "
                           f"{'MET' if sec['target_met'] else 'NOT MET'}")
        if not sec.get("complete"):
            _p("", "INCOMPLETE — see the reproducer for why")
        print()

    if (sec := head("SPEC")) is not None:
        _p("spec_id", f"{sec['spec_id']}   ({sec['status']})")
        _p("vol_target_annual",
           "ABSENT from the frozen spec — the sleeve applies its own code "
           "default (src/deploy/sleeves/cef_discount.py _vol_target)"
           if sec["vol_target_absent"] else f"{sec['vol_target_annual']}")
        _p("band_width", f"{sec['band_width']}   "
                         f"z_window {sec['z_window']}   "
                         f"{sec['n_universe']} names   {sec['order_type']}")
        _p("rebalance_days", f"{sec['rebalance_days']}"
           + ("   INERT while band_width is set" if sec["rebalance_days_inert"]
              else ""))
        _p("capital / min trade", f"${sec['capital_usd']:,.0f}  /  "
                                  f"${sec['min_trade_usd']}")
        print()

    if (sec := head("TRIALS")) is not None:
        for name, c in sec["counters"].items():
            _p(f"{name}  [doc]", f"{c['trials']} trials   "
               + (f"deflated-Sharpe bar sqrt(2 ln N) = {c['dsr_bar']}"
                  if c["dsr_bar"] else "no bar at N<=1"))
        _p("", f"source: {sec['source']}")
        print()

    if (sec := head("PANELS")) is not None:
        for name, p in sec["panels"].items():
            if p.get("error"):
                _p(name, f"UNMEASURED — {p['error']}")
            else:
                age = p.get("trading_days_old")
                _p(name, f"last {p['last']}"
                         + (f"   ({age} trading day(s) old)" if age is not None
                            else ""))
        print()

    sec = s.get("HYGIENE") or {}
    if "UNMEASURED" in sec:
        print(f"HYGIENE\n  UNMEASURED — {sec['UNMEASURED']}\n")
    else:
        print("HYGIENE")
        for k, c in (sec.get("checks") or {}).items():
            _p(k, f"{c.get('count')}")
            _p("", f"  {c['reproducer']}")
        print()

    if (sec := head("DOC DRIFT")) is not None:
        _p("prompt-index findings", str(sec["n_findings"]))
        _p("doc-audit DRIFT", str(sec.get("doc_audit_drift")))
        for row in sec.get("doc_audit_rows") or []:
            _p("", f"  {row[:96]}")
        print()

    print("Read CLAUDE.md for the RULES. Read this for the FIGURES.\n"
          "Anything you are about to quote that is not above: re-measure it, "
          "or state it as a gap.\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-tests", action="store_true",
                    help="skip the pytest collection count")
    a = ap.parse_args(argv)
    d = collect(run_tests=not a.no_tests)
    if a.json:
        json.dump(d, sys.stdout, indent=2, default=str)
        print()
    else:
        render(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
