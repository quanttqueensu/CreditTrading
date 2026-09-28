"""A live session must arm exactly once.

THE DEFECT THIS PINS (found 2026-09-10). `run_book.main` carried TWO adjacent,
near-identical arming blocks:

    if not args.dry_run and execution == "ibkr":     # ~line 452
        report = broker.arm()
        ...  write_halt(book=...); return 3
    # 13 lines of comment, no executable statement
    if execution == "ibkr" and not args.dry_run:     # ~line 490
        report = broker.arm()
        ...  print("ABORT"); return 2

Nothing ran between them, so every live session armed twice. Two symptoms, one
of them not cosmetic:

  1. Every session log carried two `[ibkr] arm: ARMED` lines and did two full
     `ib.positions()` syncs. Confirmed in ops/schedule/logs/cef_2026-09-09.log.
  2. The two copies DISAGREED about what a refusal means. The first writes the
     per-book scoped halt and returns 3; the second only prints and returns 2.
     Because the first always ran first, the second's failure path was dead
     code -- but anyone reading it would conclude a refusal does not halt.
     Their comments had drifted into contradicting each other outright, one
     saying a refusal "is not a crash: the run continues", the other "a refusal
     is fatal on purpose".

Arming twice was not itself dangerous -- `arm()` re-reads the account and is
effectively idempotent -- which is exactly why it survived unnoticed. The risk
is the ambiguity: two arming sites with two failure contracts is how a future
edit fixes one and not the other.

WHY THIS TEST IS STRUCTURAL. Driving `run_book.main` to the arming line needs a
book spec, a price panel and a live-ish broker; a test that heavy would be
skipped in CI and would not run here. The regression to prevent is precisely
"someone re-adds a second call site", which is a property of the source, so the
source is what is asserted. This is a guard against duplication, not a proof
that arming works -- test_arm_attribution.py covers the behaviour.
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TARGET = REPO / "src" / "deploy" / "run_book.py"


def _tree():
    return ast.parse(TARGET.read_text(), filename=str(TARGET))


def _arm_calls(tree):
    """Every `<something>.arm(...)` call site, as (lineno, receiver name)."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "arm"):
            recv = getattr(node.func.value, "id", "<expr>")
            out.append((node.lineno, recv))
    return sorted(out)


def test_exactly_one_arm_call_site():
    calls = _arm_calls(_tree())
    assert len(calls) == 1, (
        "run_book must arm exactly once per session; found "
        f"{len(calls)} call sites at lines {[c[0] for c in calls]}. "
        "Two arming blocks sat back to back until 2026-09-10 and every live "
        "session armed twice with two different failure contracts."
    )


def test_the_arm_call_is_on_the_broker():
    (_, recv), = _arm_calls(_tree())
    assert recv == "broker", f"expected broker.arm(), got {recv}.arm()"


def test_arming_failure_writes_a_scoped_halt():
    """A refusal must halt THIS book, not print and carry on.

    The deleted second copy returned 2 without writing any halt. If a future
    edit keeps the wrong copy, this fails: `write_halt` must still be called
    with a `book=` keyword, which is what makes the halt per-book rather than
    global (see test_halt_scope.py for why that distinction cost two sessions).
    """
    src = TARGET.read_text()
    assert "write_halt(" in src, "arming failure must write a halt"
    tree = _tree()
    scoped = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", getattr(n.func, "attr", None)) == "write_halt"
        and any(kw.arg == "book" for kw in n.keywords)
    ]
    assert scoped, (
        "write_halt must be called with book=<book_id> so an arming failure "
        "blocks only the failing book. A global halt here stopped the $500k "
        "strategy twice in two days over a $20k book's bookkeeping."
    )


def test_the_live_arm_call_passes_a_decision_date_and_a_job():
    """The decision-age check is opt-in at the signature, so hold the LIVE
    call site to opting in -- structurally, where a reviewer cannot miss it.

    `arm(decision_date=..., job=...)` are keyword-only and default to None so
    that ops/rebuild_ledger.py, a recovery tool with neither a decision nor a
    schedule, still arms. That default is a deliberate hole, and this test is
    the thing that stops the live path falling through it. Without it, deleting
    one kwarg would silently disable the guard that exists because the
    2026-09-10 session armed 17h23m late and cost two sessions.
    """
    tree = _tree()
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "arm"]
    assert len(calls) == 1, "see test_exactly_one_arm_call_site"
    kwargs = {k.arg for k in calls[0].keywords}
    missing = {"decision_date", "job"} - kwargs
    assert not missing, (
        f"run_book's arm() call is missing {sorted(missing)}; the decision-age "
        f"guard is silently inert without them (src/deploy/broker/ibkr.py, "
        f"arm(): the check runs only when BOTH are not None)."
    )
